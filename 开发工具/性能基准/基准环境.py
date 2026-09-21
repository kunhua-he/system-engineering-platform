"""轻量运行态装配：只装载基准需要的最小包集，不碰制品、不碰正式运行库。

为什么不用 `后端核心.装配()`：那是**全量装配**（全部支持库 + 全部模块库 + 技能库，
并做包指纹扫描），会导入与本次度量无关的重量级包（OCR/转写/大模型等），
既违背「不为测性能加载模型」，也让装配耗时（秒级）污染每一轮的度量口径。

本模块的装配口径（唯一、可复现）：
1. 经 **平台既有加载器**（`运行核心.加载器.包安装.支持库安装`）发现并安装**指定的**
   支持库包 —— 不 import 任何支持库的 `实现/`，只走公开装配入口；
2. 构造 `后端核心` 时把**运行缓存根指向独立临时目录**（构造参数显式覆盖），
   因此句柄账本/权威状态库落在临时目录，正式 `工程缓存/运行数据`、
   `工程缓存/权威状态` 只做**只读探测**（只解析路径，不写入）；
3. 网关用 `本地网关服务器.创建测试服务器`（回环地址 + 端口 0 自动分配 + 免凭证），
   **不起制品、不占制品仓库**，退出时优雅停止。

工程根解析规则（单一来源，入口脚本共用同一条规则）：
`Path(__file__).resolve().parents[2]` —— 本文件位于 `<工程根>/开发工具/性能基准/`。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from 公共契约.运行时 import 平台适配
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

from 开发工具.性能基准.基准口径 import (
    报场景失败, 报落盘失败,
)

#: 基准需要的最小包集（纯计算 + 本地 SQLite，均只依赖标准库）
需要包id表 = (
    "支持库.后端.数据操作支持库.数据交换",
    "支持库.后端.数据库连接支持库.SQLite数据库",
)


def 工程根目录() -> Path:
    """本工具所属工程根（固定深度：开发工具/性能基准/ → 上两级）。"""
    return Path(__file__).resolve().parents[2]


def 解析正式运行数据根() -> Path:
    """**只读**探测正式运行数据根（经唯一解析器；本函数不创建任何目录）。"""
    from 公共契约.运行时.运行缓存 import 解析运行数据根

    return 解析运行数据根(工程根目录())


def 网关HTTP请求(地址: str, 方法: str, 路径: str, *,
                 体: dict[str, Any] | None = None,
                 请求id: str = "", 超时秒: float = 10.0) -> tuple[int, dict[str, Any]]:
    """对网关发一次最小 HTTP 请求，返回 (状态码, 响应字典)。

    收发一律走**全平台唯一一条 HTTP 腿**（`开发工具.薄壳.网关转发.发送`）—— 本文件
    不再自建 `http.client` 客户端（#85 收口）。每次调用**新建连接**（网关响应带
    `Connection: close`，是平台现状，不是基准额外加的开销）。非 JSON 响应即明确失败，
    不静默当成功。

    `凭证` 传空串：被测网关是 `本地网关服务器.创建测试服务器`（回环 + 免凭证），
    带凭证头会与「免凭证」配置分叉。`路径` 允许是已百分号编码的 ASCII 路径
    （本基准的调用点传的就是 `"/" + quote(...)`），统一件对已编码路径原样使用。
    """
    from 开发工具.薄壳.网关转发 import 发送

    结果 = 发送(路径, 体, 方法=方法, 基地址=地址, 凭证="", 超时秒=超时秒,
                附加头=({"X-请求-id": 请求id} if 请求id else None))
    if 结果["HTTP状态码"] is None:
        报场景失败(f"网关请求失败 {方法} {路径}：{结果['错误码']} {结果['错误说明']}")
    状态码 = int(结果["HTTP状态码"])
    数据 = 结果["信封"]
    if 数据 is None:
        报场景失败(f"网关响应不是合法 JSON（状态码 {状态码}）：{结果['错误说明']}")
    if not isinstance(数据, dict):
        报场景失败(f"网关响应不是对象（状态码 {状态码}）：{type(数据).__name__}")
    return 状态码, 数据


class 轻量运行态:
    """基准的被测环境：最小包集 + 真实网关核心 + 可选进程内 HTTP 服务器。

    生命周期：`装配()` → 用 → `关闭()`；支持 `with` 语句。
    """

    def __init__(self, *, 临时父目录: Path | None = None) -> None:
        self.工程根 = 工程根目录()
        self.临时根 = Path(tempfile.mkdtemp(
            prefix="性能基准-", dir=str(临时父目录) if 临时父目录 else None))
        self.运行缓存根 = self.临时根 / "运行缓存"
        self.正式运行数据根 = 解析正式运行数据根()
        self.已装配包id: list[str] = []
        self.装配耗时秒 = 0.0
        self.后端: Any = None
        self.服务: Any = None
        self.网关核心: Any = None
        self.网关服务器: Any = None
        self.网关地址: str = ""
        self.限流器: Any = None
        self.限流放宽说明: str = ""
        self._已装配 = False

    # ── 装配 ─────────────────────────────────────────────────
    def 装配(self) -> "轻量运行态":
        from 后端核心.后端核心 import 后端核心
        from 运行核心.加载器.包安装.支持库安装 import 发现支持库, 安装支持库
        from 运行核心.能力调用.唯一能力调用 import (
            唯一能力调用服务, 设置全局唯一服务,
        )

        起点 = time.perf_counter()
        self.后端 = 后端核心(系统根目录=self.工程根, 运行缓存根目录=self.运行缓存根)
        声明表 = 发现支持库(self.工程根 / "支持库")
        命中 = {声明.包id: 声明 for 声明 in 声明表}
        缺失 = [包id for 包id in 需要包id表 if 包id not in 命中]
        if 缺失:
            报场景失败(f"基准需要的支持库包未发现：{'、'.join(缺失)}"
                     f"（工程根 {self.工程根}）")
        for 包id in 需要包id表:
            安装支持库(命中[包id], self.后端.注册表)
            self.已装配包id.append(包id)
        self.服务 = 唯一能力调用服务(self.后端.注册表)
        # 后端核心的内部调用服务与全局调用器都指向同一实例：保证「经后端核心」
        # 与「经唯一调用服务」两条被测路径命中同一注册表、同一证据链口径。
        self.后端._唯一调用服务 = self.服务
        设置全局唯一服务(self.服务)
        self.后端.状态.状态 = "运行中"
        self.后端.状态.能力数 = len(self.后端.注册表.能力id列表)
        self.装配耗时秒 = round(time.perf_counter() - 起点, 4)
        self._已装配 = True
        if self.运行缓存根.resolve() == self.正式运行数据根.parent.resolve():
            报场景失败(f"临时运行缓存根不得等于正式缓存根：{self.运行缓存根}")
        return self

    @property
    def 能力数(self) -> int:
        return len(self.后端.注册表.能力id列表) if self.后端 is not None else 0

    # ── 网关 ─────────────────────────────────────────────────
    def 启动进程内网关(self, *, 单能力频率: int = 5_000_000) -> str:
        """起真实 HTTP 网关（回环 + 端口 0 + 免凭证）；返回可请求地址。

        **限流放宽是显式且必须的**：网关限流器默认「单能力频率 200 次/10 秒」，
        而基准要在一个窗口内打上千次同一能力 —— 不放宽就只会量到 429 拒绝，
        而不是网关的处理能力（那才是本场景要回答的问题）。放宽后的取值如实
        记进 `限流放宽说明`，并在结果里回报「累计拒绝数」，绝不隐瞒。
        """
        from 运行核心.统一网关.网关核心 import 网关核心
        from 运行核心.统一网关.本地网关 import 本地网关服务器
        from 运行核心.统一网关.安全.限流器 import 限流器

        if not self._已装配:
            报场景失败("必须先装配轻量运行态，再启动网关")
        默认限流器 = 限流器()
        self.限流器 = 限流器(
            最大并发请求=256, 最大任务数=256, 最大流式连接=256, 单维度并发=256,
            单项目频率=单能力频率, 单用户频率=单能力频率, 单能力频率=单能力频率,
            单任务频率=单能力频率, 单提供者频率=单能力频率, 窗口秒=10.0,
        )
        self.限流放宽说明 = (
            f"网关限流器已放宽以测处理链路而非限流拒绝：默认 单能力频率 "
            f"{默认限流器.频率上限表['能力']} 次/{默认限流器.窗口秒:g} 秒、"
            f"单维度并发 {默认限流器.单维度并发}、最大并发请求 {默认限流器.最大并发请求}；"
            f"本次放宽为 频率 {单能力频率} 次/10 秒、单维度并发 256、最大并发请求 256"
        )
        self.网关核心 = 网关核心(后端核心=self.后端, 限流器实例=self.限流器)
        self.网关服务器 = 本地网关服务器.创建测试服务器(
            网关核心实例=self.网关核心, 地址="127.0.0.1", 端口=0,
            配置={"并发上限": 64, "请求超时秒": 60},
        )
        成功, 说明 = self.网关服务器.启动()
        if not 成功:
            报场景失败(f"进程内网关启动失败：{说明}")
        self.网关地址 = f"http://127.0.0.1:{self.网关服务器.端口}"
        return self.网关地址

    # ── 关闭 ─────────────────────────────────────────────────
    def 关闭(self) -> None:
        if self.网关服务器 is not None:
            try:
                self.网关服务器.优雅停止()
            except Exception:  # noqa: BLE001 - 关闭失败不掩盖真实结论，但必须留痕
                print("警告：进程内网关优雅停止失败", file=sys.stderr)
            self.网关服务器 = None
        if self.服务 is not None:
            from 运行核心.能力调用.唯一能力调用 import 销毁全局唯一服务

            销毁全局唯一服务()
            self.服务 = None
        try:
            清只读后删除树(self.临时根, 忽略失败=真)
        except OSError:
            print(f"警告：临时目录未清理干净：{self.临时根}", file=sys.stderr)

    def __enter__(self) -> "轻量运行态":
        return self.装配()

    def __exit__(self, 异常类型, 异常, 回溯) -> None:
        self.关闭()


def 环境快照() -> dict[str, Any]:
    """记录解释器/主机/负载口径，让不同时间的数字可比。"""
    import os
    import platform

    try:
        负载 = [round(值, 3) for 值 in os.getloadavg()]
    except (OSError, AttributeError):
        负载 = []
    return {
        "Python": platform.python_version(),
        "解释器": sys.executable,
        "主机": platform.node(),
        "平台": f"{平台适配.本机系统名()} {platform.release()}",
        "架构": 平台适配.当前架构(),
        "CPU核数": os.cpu_count(),
        "负载均值": 负载,
    }


def 校验结果可落盘(目录: Path) -> None:
    """落盘前先探一次可写性：不可写即明确失败（不留半截结果）。"""
    try:
        目录.mkdir(parents=True, exist_ok=True)
    except OSError as 异常:
        报落盘失败(f"输出目录不可用 {目录}：{type(异常).__name__}: {异常}")
    探针 = 目录 / ".性能基准写入探针"
    try:
        探针.write_text("探针\n", encoding="utf-8")
    except OSError as 异常:
        报落盘失败(f"输出目录不可写 {目录}：{type(异常).__name__}: {异常}")
    finally:
        探针.unlink(missing_ok=True)
