"""提供者生命周期管理：提供者路由与生命周期权威化（第三十阶段C3）。

唯一事实点（运行核心侧）：
- 提供者路由：目录 + 依赖锁 扫描（依赖锁事实点）→ 与 支持库/适配层/
  提供者注册表 的登记路由 三方对齐核对（注册表/实际进程/依赖锁）。
- 生命周期：启动、健康检查、调用（超时/取消）、停止、崩溃检测与自动
  重启（次数限制）、资源回收全部由本管理器统一管理。
- 有界与零残留：线程（每次调用最多一个临时 daemon 线程且必 join）、
  进程（最大进程数上限）、队列（同步调用无残留队列）、临时目录（登记
  清理）、句柄（停止后关闭管道）、日志（环形裁剪有上限）。
- 提供者隔离边界：原生扩展与不可控全局状态第三方不得在主进程导入
  （sys.modules / sys.path 检查，fail-closed 报告）。

禁止修改 运行核心/加载器/提供者隔离/独立进程.py（C1 负责）：本管理器
只经其公开中文协议调用 独立进程，不泄漏原生进程对象。
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 运行核心.加载器.提供者隔离.独立进程 import (
    独立进程,
    进程调用结果,
    进程状态_已停止,
    进程状态_故障,
    进程状态_运行中,
)
from 运行核心.运行环境管理器.环境管理器 import 确保环境, 读取依赖锁
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假

默认最大进程数 = 8
默认日志上限 = 200
默认最大重启次数 = 3
取消等待上限秒 = 2.0
排空滞留预算秒 = 2.0
排空滞留预算字节 = 64 * 1024


def _进程已结束(进程: Any) -> bool:
    """进程是否已确认结束：poll()!=None（三管道关闭由独立进程负责）。"""
    try:
        底层 = getattr(进程, "进程", None)
        if 底层 is None:
            return 真  # 无底层进程对象视为已结束
        return 底层.poll() is not None
    except (AttributeError, OSError):
        return 假


@dataclass
class 提供者路由:
    """提供者级路由：提供者id → 目录/依赖锁/运行方式（三方对齐事实点）。"""

    提供者id: str
    提供者目录: Path
    依赖锁路径: Path | None = None
    依赖锁摘要: str = ""
    pip模块名表: list[str] = field(default_factory=list)
    运行方式: str = "系统解释器"  # 独立进程（隔离环境）| 系统解释器（无第三方锁）
    能力列表: list[str] = field(default_factory=list)

    def 转字典(self) -> dict[str, Any]:
        return {
            "提供者id": self.提供者id,
            "提供者目录": str(self.提供者目录),
            "依赖锁路径": str(self.依赖锁路径) if self.依赖锁路径 else "",
            "依赖锁摘要": self.依赖锁摘要,
            "pip模块名表": list(self.pip模块名表),
            "运行方式": self.运行方式,
            "能力列表": list(self.能力列表),
        }


class 提供者生命周期管理器:
    """提供者生命周期权威管理器：路由对齐 + 生命周期 + 有界零残留。"""

    def __init__(self, 提供者根目录=None, 注册表=None, *,
                 最大进程数: int = 默认最大进程数,
                 日志上限: int = 默认日志上限,
                 最大重启次数: int = 默认最大重启次数,
                 启动超时秒: float = 10.0,
                 调用超时秒: float = 3.0) -> None:
        self._提供者根目录 = Path(提供者根目录) if 提供者根目录 else None
        self._注册表 = 注册表  # 支持库/适配层/提供者注册表（只读事实点）
        self._最大进程数 = max(1, int(最大进程数))
        self._日志上限 = max(1, int(日志上限))
        self._最大重启次数 = max(0, int(最大重启次数))
        self._启动超时秒 = float(启动超时秒)
        self._调用超时秒 = float(调用超时秒)
        self._路由表: dict[str, 提供者路由] = {}
        self._进程表: dict[str, 独立进程] = {}
        self._状态表: dict[str, str] = {}
        self._日志表: dict[str, list[str]] = {}
        self._临时目录表: list[Path] = []
        self._锁 = threading.Lock()

    def _定位系统根(self) -> Path | None:
        系统根 = Path(__file__).resolve()
        for _祖先 in 系统根.parents:
            if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
                return _祖先
        return None

    # ---------- 路由扫描与三方对齐 ----------

    def 扫描提供者路由(self) -> list[提供者路由]:
        """扫描 提供者根目录 下含 依赖锁.json 的目录 → 提供者路由。

        依赖锁是提供者的唯一事实点：有锁目录一律按第三方提供者登记，
        运行方式 独立进程（含 pip 包走隔离环境，仅外部应用走系统解释器）；
        无锁目录不自动登记（需显式登记，供无第三方依赖的测试/适配器）。
        """
        路由表: list[提供者路由] = []
        if self._提供者根目录 is None or not self._提供者根目录.is_dir():
            return 路由表
        for 目录 in sorted(self._提供者根目录.iterdir()):
            if not 目录.is_dir():
                continue
            锁文件 = 目录 / "依赖锁.json"
            if not 锁文件.is_file():
                continue
            依赖锁 = 读取依赖锁(目录)
            pip模块名表 = [
                包["模块名"] for 包 in 依赖锁.get("包", [])
                if str(包.get("来源", "") or "").lower() not in ("外部应用", "系统工具", "pip")
                and 包.get("模块名")
            ]
            路由表.append(提供者路由(
                提供者id=目录.name,
                提供者目录=目录,
                依赖锁路径=锁文件,
                依赖锁摘要=hashlib.sha256(锁文件.read_bytes()).hexdigest()[:16],
                pip模块名表=pip模块名表,
                运行方式="独立进程",
            ))
        return 路由表

    def 登记路由(self, 路由: 提供者路由, *, 能力列表: list[str] | None = None) -> 结果:
        """登记提供者路由（能力列表同步到注册表路由事实点）。

        同一提供者id 重复登记不同目录 → 冲突失败；能力已登记不同目录
        （注册表侧）→ 冲突失败。
        """
        with self._锁:
            已有 = self._路由表.get(路由.提供者id)
        if 已有 is not None:
            if str(已有.提供者目录.resolve()) == str(Path(路由.提供者目录).resolve()):
                return 结果.成功结果(路由.提供者id)  # 幂等
            return 结果.失败(
                "提供者冲突",
                f"提供者 {路由.提供者id} 已登记目录 {已有.提供者目录}，禁止改登记 {路由.提供者目录}",
                来源="提供者生命周期",
            )
        目录 = Path(路由.提供者目录)
        if not 目录.is_dir():
            return 结果.失败("参数不合法", f"提供者目录不存在: {目录}", 来源="提供者生命周期")
        能力列表 = 能力列表 or 路由.能力列表 or []
        路由.能力列表 = list(能力列表)
        if 路由.依赖锁路径 is None and (目录 / "依赖锁.json").is_file():
            路由.依赖锁路径 = 目录 / "依赖锁.json"
        if 路由.依赖锁路径 is not None:
            锁文件 = Path(路由.依赖锁路径)
            if 锁文件.is_file():
                路由.依赖锁摘要 = hashlib.sha256(锁文件.read_bytes()).hexdigest()[:16]
                # 依赖锁是 pip 模块名事实点：登记时一律从锁同步（覆盖传入值）
                依赖锁 = 读取依赖锁(目录)
                路由.pip模块名表 = [
                    包["模块名"] for 包 in 依赖锁.get("包", [])
                    if str(包.get("来源", "") or "").lower()
                    not in ("外部应用", "系统工具", "pip")
                    and 包.get("模块名")
                ]
        已登记能力: list[str] = []
        try:
            if self._注册表 is not None:
                from 支持库.适配层.提供者注册表 import 提供者路由信息
                for 能力id in 能力列表:
                    登记结果 = self._注册表.登记路由(提供者路由信息(
                        能力id=能力id,
                        提供者名称=路由.提供者id,
                        提供者目录=str(路由.提供者目录),
                        依赖锁路径=str(路由.依赖锁路径) if 路由.依赖锁路径 else "",
                        运行方式=路由.运行方式,
                        进程名称=路由.提供者id,
                    ))
                    if not 登记结果.成功:
                        # 回滚本次已登记能力（不留半登记状态）
                        for 已登记 in 已登记能力:
                            self._注册表.移除路由(已登记)
                        return 登记结果
                    已登记能力.append(能力id)
            with self._锁:
                self._路由表[路由.提供者id] = 路由
        except Exception as 错误:
            if self._注册表 is not None:
                for 已登记 in 已登记能力:
                    self._注册表.移除路由(已登记)
            return 结果.失败("内部错误", f"登记路由失败: {错误}", 来源="提供者生命周期")
        return 结果.成功结果(路由.提供者id)

    def 对齐核对(self, *, 严格: bool = 假) -> list[str]:
        """注册表 ↔ 实际进程 ↔ 依赖锁 三方对齐核对（fail-closed 报告）。

        规则：
        1. 登记路由的 提供者目录 必须存在，登记依赖锁必须与目录一致；
        2. 严格 模式：扫描发现的含锁第三方目录未登记 → 报告（目录有记录、
           运行时却选择另一实现属于禁止行为）；
        3. 运行中进程必须已登记。
        """
        问题列表: list[str] = []
        if self._注册表 is not None:
            问题列表.extend(self._注册表.对齐核对())
        扫描表 = {路由.提供者id: 路由 for 路由 in self.扫描提供者路由()}
        if 严格:
            for 提供者id in 扫描表:
                if 提供者id not in self._路由表:
                    问题列表.append(
                        f"目录 {提供者id} 含依赖锁但未登记路由（运行时不得选择另一实现）")
        for 提供者id, 路由 in self._路由表.items():
            目录 = Path(路由.提供者目录)
            if not 目录.is_dir():
                问题列表.append(f"登记提供者 {提供者id} 目录不存在: {目录}")
                continue
            实际锁 = 目录 / "依赖锁.json"
            if 路由.依赖锁路径 is not None:
                锁文件 = Path(路由.依赖锁路径)
                if not 锁文件.is_file():
                    问题列表.append(f"登记提供者 {提供者id} 依赖锁缺失: {锁文件}")
                elif str(锁文件.resolve()) != str(实际锁.resolve()):
                    问题列表.append(
                        f"登记提供者 {提供者id} 依赖锁与目录不一致: {锁文件} vs {实际锁}")
            elif 实际锁.is_file():
                问题列表.append(f"登记提供者 {提供者id} 登记无锁但目录含依赖锁（不一致）")
        with self._锁:
            for 提供者id, 进程 in self._进程表.items():
                if 进程.状态 == 进程状态_运行中 and 提供者id not in self._路由表:
                    问题列表.append(f"运行中进程 {提供者id} 未登记（进程与注册表不对齐）")
        return 问题列表

    # ---------- 提供者隔离边界 ----------

    def 检查隔离边界(self) -> list[str]:
        """原生扩展/不可控全局状态第三方不得在主进程导入（隔离边界检查）。

        规则：
        1. 登记路由的依赖锁 pip 包模块名（顶层）不得已存在于主进程
           sys.modules；
        2. 系统根下 支持库/适配层 提供者实现目录不得出现在主进程
           sys.path。
        违规返回问题列表（fail-closed），调用方应拒绝装配/启动。
        """
        问题列表: list[str] = []
        for 路由 in self._路由表.values():
            for 模块名 in 路由.pip模块名表:
                顶层名 = 模块名.split(".")[0]
                if 顶层名 in sys.modules:
                    问题列表.append(
                        f"第三方模块 {顶层名} 已在主进程导入，违反提供者隔离边界: "
                        f"{路由.提供者id}（原生扩展/不可控全局状态不得在主进程导入）")
        系统根 = self._定位系统根()
        if 系统根 is not None:
            适配层 = 系统根 / "支持库" / "适配层"
            for 路径 in sys.path:
                try:
                    解析路径 = Path(路径).resolve()
                except OSError:
                    continue
                解析适配层 = 适配层.resolve()
                if 解析路径 == 解析适配层 or str(解析路径).startswith(str(解析适配层)):
                    问题列表.append(f"主进程 sys.path 含提供者实现目录: {路径}")
                    break
        return 问题列表

    # ---------- 生命周期：启动/健康/停止/重启/崩溃 ----------

    def 启动提供者(self, 提供者id: str) -> tuple[bool, str]:
        """启动提供者独立进程；进程数有界；重复启动幂等。"""
        with self._锁:
            if 提供者id in self._进程表:
                现有进程 = self._进程表[提供者id]
                if 现有进程.状态 == 进程状态_运行中:
                    return 真, "已在运行"
                现有进程.关闭并清理()
                self._进程表.pop(提供者id, None)
            运行中数量 = sum(1 for 进程 in self._进程表.values()
                           if 进程.状态 == 进程状态_运行中)
            if 运行中数量 >= self._最大进程数:
                return 假, f"运行中进程数已达上限（{self._最大进程数}），拒绝启动 {提供者id}"
        路由 = self._路由表.get(提供者id)
        if 路由 is None:
            return 假, f"提供者未登记: {提供者id}"
        目录 = Path(路由.提供者目录)
        if not 目录.is_dir():
            return 假, f"提供者目录不存在: {目录}"
        解释器 = sys.executable
        if 路由.pip模块名表:
            环境结果 = 确保环境(目录)
            if not 环境结果.成功:
                return 假, f"独立环境构建失败: {环境结果.错误码}: {环境结果.错误说明}"
            解释器 = 环境结果.解释器路径
        进程 = 独立进程(
            提供者id,
            提供者目录=目录,
            解释器路径=解释器,
            启动超时秒=self._启动超时秒,
            调用超时秒=self._调用超时秒,
            最大重启次数=self._最大重启次数,
        )
        成功, 消息 = 进程.启动()
        with self._锁:
            # 启动完成回锁复查：启动期间其他线程可能抢先启动新进程，超限则
            # 强制终止新进程并拒绝（消除检查-启动之间的 TOCTOU 窗口）
            运行中数量 = sum(1 for 进程对象 in self._进程表.values()
                           if 进程对象.状态 == 进程状态_运行中)
            if 成功 and 运行中数量 >= self._最大进程数:
                进程.强制终止()
                self._记录日志(提供者id, "启动拒绝：启动期间进程数达上限，新进程已终止")
                return 假, f"运行中进程数已达上限（{self._最大进程数}），拒绝启动 {提供者id}"
            self._进程表[提供者id] = 进程
            self._状态表[提供者id] = 进程.状态
            self._记录日志(提供者id, f"启动: {消息}")
        return 成功, 消息

    def 健康检查(self, 提供者id: str) -> bool:
        """进程健康检查（真实健康请求）。"""
        进程 = self._进程表.get(提供者id)
        if 进程 is None:
            return 假
        return 进程.健康检查()

    def 停止提供者(self, 提供者id: str) -> tuple[bool, str]:
        """停止提供者（优雅 → 强制兜底）；重复停止幂等。"""
        进程 = self._进程表.get(提供者id)
        if 进程 is None:
            return 真, "未启动（幂等）"
        if 进程.状态 == 进程状态_已停止:
            return 真, "已停止（幂等）"
        成功, 消息 = 进程.优雅停止()
        if not 成功:
            成功, 消息 = 进程.强制终止()
        with self._锁:
            self._状态表[提供者id] = 进程.状态
            self._记录日志(提供者id, f"停止: {消息}")
        return 成功, 消息

    def 重启提供者(self, 提供者id: str) -> tuple[bool, str]:
        """重启提供者（停止 → 再启动，独立新进程）。"""
        进程 = self._进程表.get(提供者id)
        if 进程 is not None and 进程.状态 == 进程状态_运行中:
            成功, 消息 = self.停止提供者(提供者id)
            if not 成功:
                return 假, f"停止失败，拒绝重启: {消息}"
        return self.启动提供者(提供者id)

    def 崩溃检测(self, 提供者id: str) -> bool:
        """崩溃检测：进程退出即崩溃并自动重启（重启次数有界）。"""
        进程 = self._进程表.get(提供者id)
        if 进程 is None:
            return 假
        未恢复 = 进程.崩溃检测()
        with self._锁:
            self._状态表[提供者id] = 进程.状态
            self._记录日志(提供者id, f"崩溃检测（未恢复={未恢复}，状态 {进程.状态}）")
        return 未恢复

    # ---------- 调用：超时/取消/排空 ----------

    def 调用能力(self, 提供者id: str, 能力id: str, 参数: dict | None = None, *,
                 超时秒: float | None = None,
                 取消事件: threading.Event | None = None) -> 进程调用结果:
        """统一调用：超时/取消由运行核心管理，滞留响应有界排空。

        超时：独立进程 内部 select 超时返回 错误码=超时；随后排空 stdout
        滞留响应行，进程保持可用。取消：取消事件触发立即返回 错误码=已取消；
        工作线程 join 等待其读完滞留响应（取消等待上限 2 秒），超时兜底
        终止进程并自动重启。每次调用最多一个临时 daemon 线程且必 join。
        """
        进程 = self._进程表.get(提供者id)
        if 进程 is None or 进程.状态 != 进程状态_运行中:
            return 进程调用结果(假, 错误码="外部不可访问",
                                错误说明=f"提供者未运行: {提供者id}")
        if 取消事件 is not None and 取消事件.is_set():
            return 进程调用结果(假, 错误码="已取消", 错误说明="调用在开始前已被取消")
        超时 = float(超时秒) if 超时秒 else self._调用超时秒
        原超时 = 进程.调用超时秒
        进程.调用超时秒 = 超时
        try:
            if not self._排空滞留响应(进程):  # 调用前排空滞留行（防超时响应错位）
                self._终止并重启(提供者id)
                return 进程调用结果(
                    假, 错误码="滞留响应超预算",
                    错误说明="调用前排空滞留响应超预算，进程已重置", 可重试=真)
            if 取消事件 is None:
                结果 = 进程.调用(能力id=能力id, 参数=参数)
                if not 结果.成功 and 结果.错误码 == "超时":
                    if not self._排空滞留响应(进程):
                        self._终止并重启(提供者id)
                        self._记录日志(提供者id, "调用超时后排空超预算，进程已重置")
                    else:
                        # 排空窗口内无数据即视为已收敛；但无法证明工作器已结束
                        # 当前能力，若再次请求写入同一管道仍有顺序风险。为满足
                        # “资源释放无硬截止”审计，超时后进程视为不可复用：重置
                        # 进程保证后续调用不受旧任务污染。
                        self._终止并重启(提供者id)
                        self._记录日志(提供者id, f"调用超时已排空但进程不可复用，已重置: {能力id}")
                return 结果
            结果盒: list = []
            线程 = threading.Thread(
                target=lambda: 结果盒.append(进程.调用(能力id=能力id, 参数=参数)),
                daemon=True, name=f"提供者调用-{提供者id}",
            )
            线程.start()
            被取消 = 取消事件.wait(超时 + 0.5)
            if 被取消:
                线程.join(取消等待上限秒)
                if 线程.is_alive():
                    self._终止并重启(提供者id)
                    return 进程调用结果(
                        假, 错误码="已取消",
                        错误说明="调用被取消（工作线程未及时返回，进程已重置）",
                        可重试=真)
                self._记录日志(提供者id, f"调用已取消: {能力id}")
                return 进程调用结果(假, 错误码="已取消", 错误说明="调用被取消",
                                    可重试=真)
            线程.join(超时 + 1.0)
            if 线程.is_alive():
                return 进程调用结果(假, 错误码="超时",
                                    错误说明="调用超时且未返回", 可重试=真)
            if not 结果盒:
                return 进程调用结果(假, 错误码="内部错误", 错误说明="调用结果缺失")
            结果 = 结果盒[0]
            if not 结果.成功 and 结果.错误码 == "超时":
                if not self._排空滞留响应(进程):
                    self._终止并重启(提供者id)
            return 结果
        finally:
            进程.调用超时秒 = 原超时

    def _排空滞留响应(self, 进程: 独立进程, *, 窗口秒: float = 0.05) -> bool:
        """排空子进程 stdout 滞留响应行（时间/字节双重有界），返回是否排空完成。

        累计排空时间超过 排空滞留预算秒（2 秒）或累计字节超过
        排空滞留预算字节（64KB）即放弃并返回 False，由调用方终止并重置
        进程（进程已不可复用）；每次 select 窗口内无可读即停止。异常记录
        日志（环形有界）并按失败处理。
        """
        import select as _select
        标准输出 = 进程.进程.stdout if 进程.进程 is not None else None
        if 标准输出 is None:
            return 真
        开始 = time.monotonic()
        累计字节 = 0
        try:
            while (time.monotonic() - 开始 <= 排空滞留预算秒
                   and 累计字节 < 排空滞留预算字节):
                可读, _, _ = _select.select([标准输出], [], [], 窗口秒)
                if not 可读:
                    break
                行 = 标准输出.readline()
                if not 行:
                    break
                累计字节 += len(行.encode("utf-8", "ignore"))
        except Exception as 错误:
            self._记录日志(进程.名称, f"排空滞留响应异常: {错误}")
            return 假
        if (累计字节 >= 排空滞留预算字节
                or time.monotonic() - 开始 > 排空滞留预算秒):
            return 假
        return 真

    def _终止并重启(self, 提供者id: str) -> None:
        """兜底：终止占用中的进程并自动重启（重启次数有界）。

        强杀失败时保留旧进程对象、进入故障态，不启动替代进程（新旧进程
        并存会破坏唯一权威和资源上限）；只有确认进程组退出才允许重启。
        """
        进程 = self._进程表.get(提供者id)
        if 进程 is not None:
            成功, 消息 = 进程.强制终止()
            with self._锁:
                if _进程已结束(进程):
                    self._进程表.pop(提供者id, None)
                    self._状态表[提供者id] = 进程状态_已停止
                    self._记录日志(提供者id, f"取消兜底：进程已终止并自动重启（{消息}）")
                else:
                    self._状态表[提供者id] = 进程状态_故障
                    self._记录日志(提供者id,
                                   f"取消兜底：强杀未收敛（{消息}），保留故障记录不重启")
                    return
        self.启动提供者(提供者id)

    # ---------- 资源有界与零残留 ----------

    def _记录日志(self, 提供者id: str, 消息: str) -> None:
        """环形有界日志：超过上限裁剪最旧行。"""
        列表 = self._日志表.setdefault(提供者id, [])
        列表.append(f"[{time.strftime('%H:%M:%S')}] {消息}")
        if len(列表) > self._日志上限:
            del 列表[:len(列表) - self._日志上限]

    def 登记临时目录(self, 路径) -> None:
        """登记临时目录（供资源回收统一清理）。"""
        with self._锁:
            self._临时目录表.append(Path(路径))

    def 清理临时目录(self) -> list[str]:
        """清理全部登记临时目录并清空登记表。

        逐目录删除后检查 exists()；删除失败的目录保留登记并返回失败明细，
        退出流程不得宣称零残留（权限/占用/LibreOffice 锁文件会导致失败）。
        """
        with self._锁:
            目录表 = list(self._临时目录表)
            self._临时目录表 = []
        失败表: list[str] = []
        for 目录 in 目录表:
            try:
                shutil.rmtree(目录)
            except Exception:
                try:
                    if Path(目录).exists():
                        失败表.append(str(目录))
                        with self._锁:
                            self._临时目录表.append(Path(目录))
                except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                    记录忽略('提供者生命周期.清理临时目录', 错误)
        return 失败表

    def 清理全部(self) -> list[str]:
        """停止全部进程并回收资源（进程/句柄/日志/临时目录）。

        只有确认进程已结束（poll()!=None）才允许从进程表移除；强杀失败的
        进程保留为故障记录，不能清空唯一观测引用（否则零残留核对失去观察
        对象，形成假阴性）。
        """
        结果列表: list[str] = []
        with self._锁:
            进程表 = dict(self._进程表)
        for 提供者id, 进程 in 进程表.items():
            if 进程.状态 == 进程状态_运行中:
                _, 消息 = self.停止提供者(提供者id)
                结果列表.append(f"{提供者id}: {消息}")
                # 停止提供者内部已按结果决定是否移除；此处只需记录
                if not _进程已结束(进程):
                    结果列表.append(f"{提供者id}: 强杀未收敛，保留故障记录")
            else:
                进程.关闭并清理()
                结果列表.append(f"{提供者id}: 已清理")
        with self._锁:
            # 只移除已确认结束的进程；未收敛的保留供零残留核对/重试
            存活表 = {提供者id: 进程 for 提供者id, 进程 in self._进程表.items()
                      if not _进程已结束(进程)}
            self._进程表.clear()
            self._进程表.update(存活表)
            self._状态表.clear()
            self._日志表.clear()
        self.清理临时目录()
        return 结果列表

    def 资源统计(self) -> dict[str, Any]:
        """资源统计：进程/线程/日志/临时目录有界情况。"""
        with self._锁:
            return {
                "进程数": len(self._进程表),
                "运行中": sum(1 for 进程 in self._进程表.values()
                            if 进程.状态 == 进程状态_运行中),
                "最大进程数": self._最大进程数,
                "日志条数": sum(len(表) for 表 in self._日志表.values()),
                "日志上限": self._日志上限,
                "临时目录数": len(self._临时目录表),
                "残留调用线程": [
                    线程.name for 线程 in threading.enumerate()
                    if 线程.name.startswith("提供者调用-") and 线程.is_alive()
                ],
            }

    def 零残留核对(self) -> list[str]:
        """异常/超时/取消/崩溃/停止后资源零残留核对。

        检查项：子进程已退出、stdin/stdout/stderr 句柄已关闭、无调用线程
        残留、无登记临时目录残留、日志条数未超出有界上限。
        """
        问题列表: list[str] = []
        with self._锁:
            for 提供者id, 进程 in self._进程表.items():
                子进程 = 进程.进程
                if 子进程 is not None and 子进程.poll() is None:
                    问题列表.append(f"提供者 {提供者id} 子进程仍在运行（pid {子进程.pid}）")
                if 子进程 is not None:
                    for 管道 in (子进程.stdin, 子进程.stdout, 子进程.stderr):
                        if 管道 is not None and not 管道.closed:
                            问题列表.append(f"提供者 {提供者id} 句柄未关闭: {管道}")
            残留线程 = [线程 for 线程 in threading.enumerate()
                       if 线程.name.startswith("提供者调用-") and 线程.is_alive()]
            if 残留线程:
                问题列表.append(f"调用线程残留: {[线程.name for 线程 in 残留线程]}")
            if self._临时目录表:
                问题列表.append(
                    f"临时目录残留: {[str(目录) for 目录 in self._临时目录表]}")
            for 提供者id, 日志表 in self._日志表.items():
                if len(日志表) > self._日志上限:
                    问题列表.append(f"提供者 {提供者id} 日志超出有界上限: {len(日志表)}")
        return 问题列表
