"""发布门禁：唯一发布门禁（合并第五阶段已有验证，不造第三套）。

发布前检查：包结构完整/包声明合法/能力契约合法/版本兼容/依赖锁一致/
完整性摘要一致/第三方权限声明/中文边界/提供者可启动可停止/最小能力
调用成功/热切换成功/自动回滚成功/失败日志可查询/诊断复现可执行/
旧版本引用保护生效/测试全部通过/语法编译全部通过。
任一强制门禁失败，发布状态必须为失败或阻断。

用法：python3.14 -m 开发工具.发布门禁.运行发布门禁 [--包目录 路径] [--允许真实进程]
      （直接执行 python3.14 开发工具/发布门禁/运行发布门禁.py 亦可）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import os
import signal
import threading
import tempfile
import time
import ast
import re
import atexit
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 项目根入 sys.path：本脚本既可 `-m 开发工具.发布门禁.运行发布门禁`，也可直接
# `python3.14 开发工具/发布门禁/运行发布门禁.py`（直接执行时项目根不在 path）。
系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "开发工具").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.有界IO import 受限读取


_门禁临时目录表: set[Path] = set()
发布输出上限字节 = 200 * 1024


def _清理门禁临时目录() -> None:
    """进程退出时清理门禁创建的临时目录，避免测试数据长期残留。"""
    for 路径 in list(_门禁临时目录表):
        try:
            shutil.rmtree(路径, ignore_errors=True)
        finally:
            _门禁临时目录表.discard(路径)


atexit.register(_清理门禁临时目录)


def _创建门禁临时目录(*, 前缀: str) -> Path:
    路径 = Path(tempfile.mkdtemp(prefix=前缀))
    _门禁临时目录表.add(路径)
    return 路径


正式源码目录名表 = (
    "公共契约", "平台控制面", "启动监督器", "运行核心", "前端核心", "后端核心",
    "支持库", "模块库", "项目适配层", "开发工具", "MCP工具箱", "客户端", "示例项目",
)


def _正式Python源码文件() -> list[Path]:
    """只枚举生产源码边界；发布门禁不读取开发期测试源码。"""
    return sorted(
        文件
        for 名称 in 正式源码目录名表
        for 文件 in (系统根 / 名称).rglob("*.py")
        if (系统根 / 名称).is_dir() and "__pycache__" not in 文件.parts
    )


@dataclass
class 门禁项:
    """一项门禁检查。"""

    名称: str
    通过: bool = False
    详情: str = ""
    强制: bool = True

    def 转字典(self) -> dict[str, Any]:
        return {"名称": self.名称, "通过": self.通过, "详情": self.详情, "强制": self.强制}


@dataclass
class 门禁结果:
    """发布门禁结果。"""

    发布状态: str = "未执行"  # 通过/失败/阻断
    门禁项列表: list[门禁项] = field(default_factory=list)
    时间: str = ""

    def 汇总(self) -> str:
        self.时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        强制项 = [项 for 项 in self.门禁项列表 if 项.强制]
        失败强制项 = [项 for 项 in 强制项 if not 项.通过]
        if not 强制项:
            self.发布状态 = "阻断"
            return "阻断: 无任何强制门禁项"
        if 失败强制项:
            self.发布状态 = "失败"
            return f"失败: {len(失败强制项)} 项强制门禁未通过"
        self.发布状态 = "通过"
        return f"通过: {len(强制项)}/{len(强制项)} 项强制门禁全部通过"

    def 打印(self) -> str:
        行列表 = [f"发布门禁结果: {self.发布状态}（{self.时间}）", "=" * 40]
        for 项 in self.门禁项列表:
            标记 = "✓" if 项.通过 else "✗"
            行列表.append(f"  {标记} {项.名称}: {项.详情}")
        return "\n".join(行列表)


def 运行子进程(命令列表: list[str], *, 超时秒: float = 60.0,
            实时输出: bool = False, 环境覆盖: dict[str, str] | None = None) -> tuple[int, str]:
    """运行子进程：输出边读边限额，超时/超限均回收整个进程组。"""
    try:
        进程对象 = subprocess.Popen(
            命令列表, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=False, start_new_session=(os.name == "posix"),
            env={**os.environ, **(环境覆盖 or {}), "PYTHONUNBUFFERED": "1"},
        )
    except OSError as 错误:
        return -1, f"启动子进程失败: {错误}"

    输出盒 = bytearray()
    读取完成 = threading.Event()
    输出超限 = threading.Event()
    打印字节数 = 0

    def 输出回调(数据: bytes) -> None:
        nonlocal 打印字节数
        if not 实时输出 or 打印字节数 >= 发布输出上限字节:
            return
        剩余 = 发布输出上限字节 - 打印字节数
        可打印 = 数据[:剩余]
        if 可打印:
            print(可打印.decode("utf-8", "replace"), end="", flush=True)
            打印字节数 += len(可打印)

    def 读取() -> None:
        try:
            assert 进程对象.stdout is not None
            内容, _超限 = 受限读取(
                进程对象.stdout, 发布输出上限字节,
                数据回调=输出回调, 超限回调=输出超限.set,
            )
            输出盒.extend(内容)
        finally:
            读取完成.set()

    读取线程 = threading.Thread(target=读取, name="门禁输出读取", daemon=True)
    读取线程.start()
    截止时间 = time.monotonic() + max(0.0, float(超时秒))
    超时 = False
    while not 读取完成.is_set():
        if 输出超限.is_set():
            break
        if time.monotonic() >= 截止时间:
            超时 = True
            break
        if 进程对象.poll() is not None:
            读取完成.wait(timeout=0.1)
        else:
            time.sleep(0.05)

    if 超时 or 输出超限.is_set():
        原因 = "输出超过上限" if 输出超限.is_set() else f"超时（> {超时秒} 秒）"
        try:
            if os.name == "posix":
                os.killpg(进程对象.pid, signal.SIGKILL)
            else:
                进程对象.kill()
        except OSError:
            pass
        try:
            进程对象.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return -1, f"{原因}，进程组未能回收"
        读取线程.join(timeout=5)
        if 进程对象.stdout is not None:
            try:
                进程对象.stdout.close()
            except OSError:
                pass
        后缀 = "\n" + bytes(输出盒).decode("utf-8", "replace") if 输出盒 else ""
        return -1, f"{原因}，已回收进程组{后缀}"

    读取线程.join(timeout=5)
    if 进程对象.stdout is not None:
        try:
            进程对象.stdout.close()
        except OSError:
            pass
    try:
        退出码 = 进程对象.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(进程对象.pid, signal.SIGKILL)
            else:
                进程对象.kill()
        except OSError:
            pass
        return -1, "子进程退出确认超时，已请求回收进程组"
    return 退出码, bytes(输出盒).decode("utf-8", "replace")


def _扫描英文函数命名() -> str:
    """使用 Python AST 扫描正式源码，避免依赖平台差异化 grep -P。"""
    # 正式源码边界必须与项目目录约定一致；漏扫任一正式层都会产生假绿。
    扫描根列表 = [系统根 / 名称 for 名称 in 正式源码目录名表]
    协议方法 = {"log_message", "do_GET", "do_POST", "setup", "finish", "read", "close", "headers", "status",
                "handle_error",
                "is_set", "handle_starttag", "handle_endtag", "handle_data",
                "redirect_request", "http_error_302", "http_error_301",
                "do_OPTIONS", "do_HEAD", "do_PUT", "do_DELETE", "do_PATCH", "do_TRACE", "do_CONNECT",
                "process_request", "process_request_thread"}
    违规: list[str] = []
    for 根 in 扫描根列表:
        if not 根.is_dir():
            continue
        for 文件 in sorted(根.rglob("*.py")):
            if "__pycache__" in 文件.parts:
                continue
            try:
                树 = ast.parse(文件.read_text(encoding="utf-8"), filename=str(文件))
            except (OSError, UnicodeDecodeError, SyntaxError) as 错误:
                违规.append(f"{文件}: AST扫描失败: {错误}")
                continue
            for 节点 in ast.walk(树):
                if not isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                名称 = 节点.name
                if 名称.startswith("__") or 名称 in 协议方法:
                    continue
                # ast.NodeVisitor 回调族：名字由 Python 按节点类名拼出
                # （visit_FunctionDef/visit_ClassDef/…）或固定为 generic_visit，
                # 不可改中文。原白名单只枚举了 visit_Import/visit_ImportFrom 两个，
                # 一旦实现新增 visit 方法（语法索引.py 即如此）门禁就恒红：
                # 发布状态被这一条压成永久「失败」，真实问题反而被淹掉。
                if 名称 == "generic_visit" or 名称.startswith("visit_"):
                    continue
                if 名称 and 名称.isascii() and 名称[0].isalpha():
                    违规.append(f"{文件}:{节点.lineno}: {名称}")
    return "\n".join(违规)


def _是聚合父包(包目录: Path) -> bool:
    """包目录内还存在其他包声明（子包）→ 聚合父包，能力由子包声明。

    功能域分组 v2 后，6 大聚合库（系统核心/大语言模型/数据操作/文件系统/
    网络通信/办公文档）的父包只做聚合入口（包声明 + __init__ 转出），
    没有 能力定义.json/实现/契约 等正式包合规件；其能力由子包声明并注册，
    发布门禁按与发现器/正式包索引相同的规则跳过聚合父包。
    """
    for 子声明 in 包目录.rglob("包声明.json"):
        if 子声明.parent != 包目录:
            return True
    return False


def _监听端口快照() -> set[str]:
    """读取当前 TCP 监听端点；工具不可用或输出异常时 fail-closed。"""
    try:
        结果 = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as 错误:
        raise RuntimeError(f"无法获取监听端口快照: {错误}") from 错误
    if 结果.returncode != 0:
        错误输出 = 结果.stderr or b""
        if isinstance(错误输出, bytes):
            错误输出 = 错误输出.decode("utf-8", errors="replace")
        raise RuntimeError(f"监听端口快照失败（退出码 {结果.returncode}）: {错误输出[:200]}")
    原始输出 = 结果.stdout or b""
    if isinstance(原始输出, bytes):
        # lsof 的命令/路径字段可能来自系统原始字节，不能让本地编码污染发布门禁。
        原始输出 = 原始输出.decode("utf-8", errors="replace")
    端点表: set[str] = set()
    for 行 in 原始输出.splitlines()[1:]:
        列 = 行.split()
        if len(列) < 9:
            continue
        端点表.add(列[8].replace("(LISTEN)", "").strip())
    return 端点表


def _是否已废弃包(包目录: Path) -> bool:
    """已废弃包保留文件但不参与装配/审计/门禁（与发现器/加载器同口径）。"""
    try:
        import json as _json
        声明 = _json.loads((包目录 / "包声明.json").read_text(encoding="utf-8"))
        return bool(声明.get("已废弃"))
    except Exception:
        return False


def _校验文件清单摘要(包目录: Path) -> tuple[bool, str]:
    """委托唯一校验器：完整性摘要.json 必须为文件清单格式且与真实文件闭合。"""
    from 开发工具.组件规范.完整性摘要 import 校验完整性摘要

    通过, 问题列表 = 校验完整性摘要(包目录)
    if 通过:
        return True, "逐文件校验通过，清单与实际文件闭合"
    return False, "；".join(问题列表[:3])


def 选择待验证制品(
    显式制品: Path | None,
    激活制品获取器: Any | None = None,
) -> tuple[Path, str]:
    """只选择明确待发布制品或正式激活制品，不允许演示/历史/备用回退。"""
    来源 = "明确待发布" if 显式制品 is not None else "正式激活"
    if 显式制品 is not None:
        制品 = Path(显式制品).resolve()
    else:
        if 激活制品获取器 is None:
            from 平台控制面.包仓库.平台客户端制品 import 平台客户端制品接入
            有效, 消息, 激活路径 = 平台客户端制品接入().校验稳定路径()
            if not 有效 or 激活路径 is None:
                raise ValueError(f"正式激活制品不可用: {消息}")
            制品 = Path(激活路径).resolve()
        else:
            激活结果 = 激活制品获取器()
            if isinstance(激活结果, tuple):
                有效, 消息, 激活路径 = 激活结果
                if not 有效 or 激活路径 is None:
                    raise ValueError(f"正式激活制品不可用: {消息}")
                制品 = Path(激活路径).resolve()
            else:
                if 激活结果 is None:
                    raise ValueError("正式激活制品不存在")
                制品 = Path(激活结果).resolve()
    if not 制品.is_dir():
        raise ValueError(f"{来源}制品目录不存在: {制品}")
    启动器 = 制品 / "运行入口" / "启动.py"
    if not 启动器.is_file():
        raise ValueError(f"{来源}制品缺少正式运行入口: {启动器}")
    return 制品, 来源


def 读取统一工作区字节指纹() -> dict[str, str]:
    """消费编译器唯一字节指纹契约；共享实现未合并时 fail-closed。"""
    from 开发工具.项目编译 import 项目编译器

    for 名称 in ("读取工作区字节指纹", "计算工作区字节指纹", "_工作区字节指纹"):
        函数 = getattr(项目编译器, 名称, None)
        if callable(函数):
            结果 = 函数()
            if isinstance(结果, dict):
                return 结果
    raise RuntimeError(
        "编译器唯一工作区字节指纹契约尚未合并；门禁禁止退回状态文本摘要或自造算法"
    )


def _读取契约能力(制品目录: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """经唯一聚合契约解析器读取制品全部正式能力。"""
    from 开发工具.契约编译.聚合契约解析 import 解析聚合契约

    能力表: list[dict[str, Any]] = []
    问题表: list[str] = []
    已见: set[str] = set()
    for 契约文件 in sorted(制品目录.rglob("能力契约/参数契约.json")):
        标准契约, 问题 = 解析聚合契约(契约文件, 严格=True)
        相对 = 契约文件.relative_to(制品目录).as_posix()
        问题表.extend(f"{相对}: {项}" for 项 in 问题)
        for 能力 in 标准契约.get("能力契约", []):
            能力id = str(能力.get("能力id", ""))
            if 能力id in 已见:
                问题表.append(f"公开能力重复: {能力id}")
                continue
            已见.add(能力id)
            缺字段 = [字段 for 字段 in ("返回", "错误码", "行为", "提供者", "版本")
                   if not 能力.get(字段)]
            if "参数" not in 能力 or not isinstance(能力.get("参数"), list):
                缺字段.insert(0, "参数")
            if 缺字段:
                问题表.append(f"{能力id}: 唯一契约缺字段 {缺字段}")
            能力表.append(能力)
    if not 能力表:
        问题表.append("制品内没有可校验的正式能力契约")
    return 能力表, 问题表


def 校验制品来源绑定(
    制品目录: Path,
    *,
    当前指纹: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """绑定当前 HEAD、统一工作区字节指纹与制品全文件摘要。"""
    身份: dict[str, Any] = {"制品路径": str(Path(制品目录).resolve())}
    try:
        来源 = json.loads((制品目录 / "制品来源.json").read_text(encoding="utf-8"))
        清单 = json.loads((制品目录 / "编译清单.json").read_text(encoding="utf-8"))
        摘要文件 = json.loads((制品目录 / "制品完整性摘要.json").read_text(encoding="utf-8"))
        指纹 = 当前指纹 if 当前指纹 is not None else 读取统一工作区字节指纹()
        当前提交 = str(指纹.get("提交", ""))
        当前字节指纹 = str(指纹.get("工作区字节指纹", ""))
        来源提交 = str(来源.get("提交", ""))
        清单提交 = str(清单.get("来源提交", ""))
        来源字节指纹 = str(来源.get("工作区字节指纹", ""))
        清单字节指纹 = str(清单.get("来源工作区字节指纹", ""))
        能力表, 契约问题 = _读取契约能力(制品目录)
        if 契约问题:
            raise ValueError("；".join(契约问题[:5]))
        from 开发工具.项目编译.项目编译器 import _制品文件摘要
        实际摘要 = _制品文件摘要(制品目录)
        身份.update({
            "全文件摘要": 实际摘要.get("制品摘要", ""),
            "文件数": 实际摘要.get("文件数", 0),
            "来源提交": 来源提交,
            "工作区字节指纹": 来源字节指纹,
            "能力数": len(能力表),
        })
        if not 当前提交 or not 当前字节指纹:
            raise ValueError("统一工作区字节指纹缺少 提交/工作区字节指纹")
        if 来源提交 != 当前提交 or 清单提交 != 当前提交:
            raise ValueError(f"来源提交与当前 HEAD 不一致: {来源提交 or '<空>'} != {当前提交}")
        if not 来源字节指纹 or not 清单字节指纹:
            raise ValueError("制品缺少统一工作区字节指纹字段")
        if 来源字节指纹 != 清单字节指纹:
            raise ValueError("制品来源与编译清单的工作区字节指纹不一致")
        if 来源字节指纹 != 当前字节指纹:
            状态 = 指纹.get("工作区状态", "未知")
            raise ValueError(f"旧制品阻断: 当前工作区({状态})真实字节指纹已变化")
        if 实际摘要.get("制品摘要") != 摘要文件.get("制品摘要"):
            raise ValueError("制品全文件摘要与真实制品不一致")
        详情 = (
            f"制品路径={身份['制品路径']}；全文件摘要={身份['全文件摘要']}；"
            f"来源提交={来源提交}；能力数={len(能力表)}"
        )
        return True, 详情, 身份
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError, TypeError, AttributeError) as 错误:
        return False, str(错误), 身份



# 本地环境依赖变量（哲学第 7 条：模型文件、外部应用这类「环境依赖」由运行环境提供，
# 不进场景静态路径）。取值顺序：① 当前进程环境；② 本机 40007 网关 launchd 配置
# （本机就是在这里声明这些提供者环境依赖的）。取不到就不注入——相关场景会以
# 「环境依赖未就绪：环境变量 X 未设置或为空」明确失败，不会被静默跳过。
环境依赖变量表 = ("MLXWhisper提供者_模型路径", "MLXWhisper提供者_模型名")
环境依赖注入问题: list[str] = []


def 环境依赖注入() -> dict[str, str]:
    """返回要注入到 HTML 验证子进程的环境依赖变量。"""
    注入 = {名称: os.environ[名称] for 名称 in 环境依赖变量表 if os.environ.get(名称)}
    缺失 = [名称 for 名称 in 环境依赖变量表 if 名称 not in 注入]
    if not 缺失:
        return 注入
    plist = Path.home() / "Library/LaunchAgents/com.huashi.gateway-40007.plist"
    if not plist.is_file():
        环境依赖注入问题.append(f"缺少 launchd 配置，无法取环境依赖: {plist}")
        return 注入
    try:
        import plistlib

        环境 = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables", {})
    except Exception as 错误:  # noqa: BLE001 —— 读取失败必须留痕，不静默
        环境依赖注入问题.append(f"读取 launchd 环境失败: {错误}")
        return 注入
    for 名称 in 缺失:
        if 环境.get(名称):
            注入[名称] = str(环境[名称])
    return 注入

def 读取制品字节快照(制品目录: Path) -> dict[str, bytes]:
    """读取制品全部文件原始字节，用于前后逐路径精确比较。"""
    快照: dict[str, bytes] = {}
    for 文件 in sorted(Path(制品目录).rglob("*")):
        if 文件.is_symlink():
            raise ValueError(f"制品包含符号链接: {文件.relative_to(制品目录)}")
        if 文件.is_file():
            快照[文件.relative_to(制品目录).as_posix()] = 文件.read_bytes()
    if not 快照:
        raise ValueError("制品没有正式文件")
    return 快照


def 核验制品字节未变(
    验证前: dict[str, bytes], 验证后: dict[str, bytes],
) -> tuple[bool, str]:
    """核验验证器没有新增、删除或修改制品内任何字节。"""
    if 验证前 == 验证后:
        return True, f"验证前后 {len(验证前)} 个文件逐字节一致"
    新增 = sorted(set(验证后) - set(验证前))
    删除 = sorted(set(验证前) - set(验证后))
    漂移 = sorted(路径 for 路径 in set(验证前) & set(验证后)
                if 验证前[路径] != 验证后[路径])
    return False, f"制品被验证过程修改：新增{新增[:3]} 删除{删除[:3]} 字节漂移{漂移[:3]}"


def 构建验证缓存环境(制品目录: Path) -> tuple[Path, dict[str, str]]:
    """创建制品外受管缓存，并返回验证子进程必须使用的环境。"""
    缓存根 = _创建门禁临时目录(前缀="发布门禁受管缓存_").resolve()
    if 缓存根.is_relative_to(Path(制品目录).resolve()):
        raise ValueError(f"受管缓存不得位于待验证制品内: {缓存根}")
    字节码根 = 缓存根 / "字节码"
    工程缓存根 = 缓存根 / "工程缓存"
    字节码根.mkdir(parents=True, exist_ok=True)
    工程缓存根.mkdir(parents=True, exist_ok=True)
    from 公共契约.运行时.运行缓存 import 解析运行缓存根
    共享提供者根 = 解析运行缓存根(Path(制品目录) / "平台客户端")
    return 缓存根, {
        "TMPDIR": str(缓存根), "TMP": str(缓存根), "TEMP": str(缓存根),
        "PYTHONPYCACHEPREFIX": str(字节码根),
        "PYTHONDONTWRITEBYTECODE": "1",
        "系统底座_工程缓存根": str(工程缓存根),
        "系统底座_提供者环境根": str(共享提供者根),
    }


def _资源释放证据通过(证据: Any) -> bool:
    if not isinstance(证据, dict) or not 证据:
        return False
    for 键, 值 in 证据.items():
        if "已退出" in str(键):
            if 值 is not True:
                return False
        elif "残留" in str(键) and 值 != 0:
            return False
    return any("已退出" in str(键) or "残留" in str(键) for 键 in 证据)


def 校验契约与HTML矩阵(
    制品目录: Path, 报告: dict[str, Any],
) -> tuple[bool, str, int]:
    """消费冻结v1报告：契约完整、408目标全集、真实成功值、清理和制品不变。"""
    能力表, 问题表 = _读取契约能力(制品目录)
    if Path(str(报告.get("制品路径", ""))).resolve() != Path(制品目录).resolve():
        问题表.append("HTML执行矩阵不是同一制品")
    结果表 = 报告.get("结果列表")
    if not isinstance(结果表, list) or not 结果表:
        问题表.append("HTML执行矩阵缺少非空结果列表")
        结果表 = []
    if int(报告.get("失败数", 0) or 0) != 0:
        问题表.append(f"HTML执行矩阵有 {报告.get('失败数')} 项失败")
    正式全集 = {能力["能力id"] for 能力 in 能力表}
    目标全集 = set(报告.get("正向目标能力全集") or [])
    实际全集 = set(报告.get("实际成功目标能力全集") or [])
    if 目标全集 != 正式全集:
        问题表.append(f"目标能力全集不一致: 缺少={sorted(正式全集 - 目标全集)[:5]}")
    if 实际全集 != 正式全集:
        问题表.append(f"实际成功能力全集不一致: 缺少={sorted(正式全集 - 实际全集)[:5]}")
    资源回收 = 报告.get("资源回收")
    if (not isinstance(资源回收, dict) or 资源回收.get("已回收") is not True
            or 资源回收.get("进程组残留") is not False
            or int(报告.get("资源残留数", -1)) != 0
            or int(报告.get("清理失败数", -1)) != 0):
        问题表.append("HTML执行矩阵资源回收或清理证据不完整")
    摘要前 = (报告.get("制品摘要前") or {}).get("制品摘要")
    摘要后 = (报告.get("制品摘要后") or {}).get("制品摘要")
    if not 摘要前 or 摘要前 != 摘要后:
        问题表.append("HTML执行前后制品摘要不一致")
    for 能力id in sorted(正式全集):
        成功结果 = next((项 for 项 in 结果表
                     if isinstance(项, dict) and 项.get("能力id") == 能力id
                     and 项.get("步骤类型") == "目标" and 项.get("通过") is True
                     and isinstance(项.get("返回"), dict) and 项["返回"].get("成功") is True), None)
        if 成功结果 is None:
            问题表.append(f"{能力id}: 缺少真实成功目标场景")
            continue
        状态码 = 成功结果.get("状态码")
        if not isinstance(状态码, int) or not 200 <= 状态码 < 300:
            问题表.append(f"{能力id}: 成功状态码证据缺失或非法")
        if "值" not in 成功结果["返回"] or 成功结果["返回"].get("值") is None:
            问题表.append(f"{能力id}: 缺少真实业务值")
    return not 问题表, "；".join(问题表[:12]) or f"{len(能力表)} 个能力真实HTTP成功并完成资源收口", len(能力表)


def _代码使用类型(实现目录: Path) -> set[str]:
    """从第三方提供者真实实现识别网络/文件/进程访问类型。"""
    类型表: set[str] = set()
    网络模块 = {"socket", "urllib", "http", "ftplib", "smtplib"}
    进程模块 = {"subprocess", "multiprocessing"}
    文件调用 = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "unlink", "mkdir", "rmdir"}
    for 文件 in 实现目录.rglob("*.py") if 实现目录.is_dir() else []:
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"), filename=str(文件))
        except (OSError, UnicodeDecodeError, SyntaxError):
            类型表.add("不可审计")
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                模块表 = {别名.name.split(".")[0] for 别名 in 节点.names}
            elif isinstance(节点, ast.ImportFrom):
                模块表 = {(节点.module or "").split(".")[0]}
            else:
                模块表 = set()
            if 模块表 & 网络模块:
                类型表.add("网络")
            if 模块表 & 进程模块:
                类型表.add("进程")
            if isinstance(节点, ast.Call):
                名称 = 节点.func.id if isinstance(节点.func, ast.Name) else (
                    节点.func.attr if isinstance(节点.func, ast.Attribute) else "")
                if 名称 in 文件调用:
                    类型表.add("文件")
    return 类型表


_跳过前缀 = "跳过（空集，不构成证据）"
"""空集分支统一用的显式跳过前缀。

空集不能出具“通过/无需声明”这类看上去已验证的说法（哲学第 11 条：空转即杀）：
本项在空集时既不改判红，也不得冒充核验证据，只在同一行如实说明“没东西可查”。
"""


def 校验第三方访问声明(制品目录: Path) -> tuple[bool, str]:
    """按真实第三方依赖及实现访问类型强制核验权限/网络/文件/进程声明。"""
    from 开发工具.契约编译.能力定义编译器 import 提取能力列表

    问题表: list[str] = []
    提供者数 = 0
    适配层根 = Path(制品目录) / "支持库" / "适配层"
    from 开发工具.依赖生命周期审计.审计核心 import 扫描提供者目录
    标准提供者表, _ = 扫描提供者目录(Path(制品目录))
    for 提供者目录 in 标准提供者表:
        if not (提供者目录 / "依赖锁.json").is_file():
            问题表.append(f"{提供者目录.name}: 第三方提供者缺真实依赖锁")
    锁文件表 = sorted(适配层根.rglob("依赖锁.json")) if 适配层根.is_dir() else []
    for 锁路径 in 锁文件表:
        提供者 = 锁路径.parent
        if not (提供者 / "包声明.json").is_file():
            问题表.append(f"{提供者.name}: 有第三方依赖锁但缺包声明")
            continue
        try:
            锁 = json.loads(锁路径.read_text(encoding="utf-8"))
            if not isinstance(锁, dict):
                raise ValueError("依赖锁必须是对象")
            第三方包 = 锁.get("包") or 锁.get("直接依赖") or []
        except (OSError, json.JSONDecodeError, ValueError):
            问题表.append(f"{提供者.name}: 第三方依赖锁不可读")
            continue
        if not 第三方包:
            # 空依赖锁不能当成“无第三方依赖”放行：依赖锁本身就是第三方声明，
            # 锁里没有任何包条目等于这份声明不可核验，必须点名而不是静默跳过。
            问题表.append(f"{提供者.name}: 第三方依赖锁没有任何包/直接依赖条目，访问声明不可核验")
            continue
        提供者数 += 1
        前缀 = 提供者.name
        if any(not isinstance(项, dict) or not 项.get("名称") or not 项.get("版本")
               or any(符号 in str(项.get("版本")) for 符号 in (">", "<", "~", "^", "*"))
               for 项 in 第三方包):
            问题表.append(f"{前缀}: 真实第三方依赖缺名称或精确版本")
        try:
            定义 = json.loads((提供者 / "能力定义.json").read_text(encoding="utf-8"))
            if not isinstance(定义, dict):
                raise ValueError("能力定义必须是对象")
        except (OSError, json.JSONDecodeError, ValueError):
            问题表.append(f"{前缀}: 能力定义不可读，无法核验访问声明")
            continue
        能力表 = 提取能力列表(定义)
        if not 能力表:
            问题表.append(f"{前缀}: 第三方提供者没有可核验能力")
        try:
            权限 = json.loads((提供者 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            权限 = {}
        if not isinstance(权限, dict):
            权限 = {}
        缺权限 = [能力.get("能力id") for 能力 in 能力表
                if 能力.get("能力id") not in 权限
                or not isinstance(权限.get(能力.get("能力id")), dict)
                or not 权限.get(能力.get("能力id"))]
        if 缺权限:
            问题表.append(f"{前缀}: 权限声明缺能力 {缺权限[:3]}")
        实际类型 = _代码使用类型(提供者 / "实现")
        参数文本 = json.dumps([能力.get("参数", []) for 能力 in 能力表], ensure_ascii=False)
        if "文件" in 参数文本 or "路径" in 参数文本:
            实际类型.add("文件")
        行为表: list[dict[str, Any]] = []
        for 能力 in 能力表:
            行为 = 能力.get("行为")
            行为表.append(行为 if isinstance(行为, dict) else {})
        副作用文本 = " ".join(str(行为.get("副作用", "")) for 行为 in 行为表)
        释放文本 = " ".join(str(行为.get("资源释放", "")) for 行为 in 行为表)
        if any(not str(行为.get("副作用", "")).strip()
               or not str(行为.get("资源释放", "")).strip() for 行为 in 行为表):
            问题表.append(f"{前缀}: 第三方能力缺显式副作用或资源释放声明")
        if "网络" in 实际类型 and "网络" not in 副作用文本:
            问题表.append(f"{前缀}: 真实网络访问缺网络声明")
        if "文件" in 实际类型 and (not 副作用文本.strip() or not 释放文本.strip()):
            问题表.append(f"{前缀}: 真实文件访问缺文件副作用/资源释放声明")
        if "进程" in 实际类型:
            try:
                生命周期 = json.loads((提供者 / "生命周期契约.json").read_text(encoding="utf-8"))
                预算 = json.loads((提供者 / "资源预算.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                生命周期, 预算 = {}, {}
            if ("进程" not in str(生命周期.get("资源模型", ""))
                    or int(预算.get("子进程上限", 0) or 0) <= 0
                    or "进程" not in (释放文本 + str(生命周期.get("释放策略", "")))):
                问题表.append(f"{前缀}: 真实进程访问缺进程模型/预算/释放声明")
        if "不可审计" in 实际类型:
            问题表.append(f"{前缀}: 实现源码不可审计")
    if 提供者数 == 0 and not 问题表:
        # 空集不能直接断言“未声明第三方依赖”：本项统计口径只有 支持库/适配层，必须把
        # 扫描范围与适配层外的依赖锁数量一起报出来，避免“没扫到”被读成“不存在”。
        # 两个空集分支一律走显式跳过语义：不判红（通过位保持 True，不改变发布判定），
        # 但绝不出具“通过/无需声明”这类看上去已验证的说法，避免空集冒充核验证据。
        支持库根 = Path(制品目录) / "支持库"
        if not 支持库根.is_dir():
            return True, (f"{_跳过前缀}：现役制品不含 支持库/ 目录"
                          f"（{支持库根.relative_to(制品目录)} 不存在），"
                          "无第三方提供者与依赖锁可核验，本项不构成核验证据")
        外置锁数 = len([路径 for 路径 in 支持库根.rglob("依赖锁.json")
                       if 适配层根 not in 路径.parents])
        return True, (f"{_跳过前缀}：支持库/适配层 下未发现第三方提供者"
                      f"（标准提供者 0、依赖锁 0），本项不构成核验证据；"
                      f"适配层外另有 {外置锁数} 份依赖锁不在本项声明核验范围")
    return not 问题表, "；".join(问题表[:12]) or f"{提供者数} 个第三方提供者权限/网络/文件/进程声明与真实依赖一致"


def _扫描工程缓存Python源码() -> list[str]:
    """扫描非制品工程缓存中的 Python 源码。

    嵌套门禁运行在工作包子进程内时，当前工作包的验证运行目录仍在使用，
    不能把它误判为持久源码；工作包结束后的最终残留由运行测试统一核对。
    其他验证运行目录、未登记目录和持久目录仍必须返回并阻断。
    """
    缓存目录 = 系统根 / "工程缓存"
    当前任务id = os.environ.get("系统底座_任务id", "").strip()
    当前验证根 = None
    if 当前任务id:
        当前验证根 = (缓存目录 / "验证运行" / 当前任务id).resolve()
    源码表: list[str] = []
    if not 缓存目录.is_dir():
        return 源码表
    # 制品仓库、提供者虚拟环境和验证运行目录可能包含数 GB 文件，
    # 直接 Path.rglob 会把无关内容全部枚举；这些目录本身已有独立门禁。
    跳过目录 = {"制品仓库", "编译缓存", "提供者运行环境", "__pycache__"}
    try:
        for 当前根, 目录名表, 文件名表 in os.walk(缓存目录):
            目录名表[:] = [名称 for 名称 in 目录名表 if 名称 not in 跳过目录]
            当前路径 = Path(当前根)
            for 名称 in 文件名表:
                if not 名称.endswith(".py"):
                    continue
                文件 = 当前路径 / 名称
                if 当前验证根 is not None and 文件.resolve().is_relative_to(当前验证根):
                    continue
                源码表.append(str(文件.relative_to(系统根)))
    except OSError:
        # 访问异常按发现了问题处理，避免扫描失败产生假绿。
        源码表.append("工程缓存/<扫描失败>")
    return sorted(源码表)


def _执行单包权威合规(包目录: Path) -> tuple[str, str, bool, int]:
    """在独立工作进程中执行单包合规，避免入口模块/sys.path互相污染。"""
    from 开发工具.组件合规.合规测试包 import 组件合规
    # 每个进程使用独立真实输入根；合规器会在结束时清理该根，不能共享。
    原输入根 = os.environ.get("系统底座_合规输入根")
    专属输入根 = Path(tempfile.mkdtemp(prefix="合规真实输入_", dir=str(系统根 / "工程缓存")))
    os.environ["系统底座_合规输入根"] = str(专属输入根)
    try:
        报告 = 组件合规(包目录).执行()
    finally:
        if 原输入根 is None:
            os.environ.pop("系统底座_合规输入根", None)
        else:
            os.environ["系统底座_合规输入根"] = 原输入根
        shutil.rmtree(专属输入根, ignore_errors=True)
    失败场景 = "；".join(
        f"{名称}({详情[:160]})"
        for 名称, 通过, 详情 in 报告.场景结果表 if not 通过
    )
    return 包目录.name, 失败场景, 报告.成功, 报告.通过数


def 执行逐包权威合规(
    包目录列表: list[Path], *, 并行数: int = 1,
) -> tuple[bool, list[tuple[str, str, bool, int]]]:
    """逐包真实调用唯一权威合规验证器（S0.4），输出每包 13/13 证据。

    返回 (模块全通过, 逐包证据列表[(包名, 失败场景文本, 通过, 通过数)])；
    正式模块（基础模块/功能模块）任一不是 13/13 即整体失败；
    支持库/前端描述包未迁移 S0.1 的记录为历史债务（披露不阻断，进升级池）。
    """
    证据列表: list[tuple[str, str, bool, int]] = []
    未达标: list[str] = []
    # 默认串行供测试和调用方保持确定性；发布门禁传入并行度时使用独立
    # 进程。组件合规会临时修改 sys.path，不能在线程池内并发。
    # 进程并发是有界资源；即使命令行传入 100/200，也不能一次创建同等
    # 数量的解释器，避免把门禁本身变成资源耗尽攻击面。
    并行数 = max(1, min(int(并行数), 32, len(包目录列表) or 1))
    if 并行数 == 1 or len(包目录列表) <= 1:
        原始结果 = [_执行单包权威合规(包目录) for 包目录 in 包目录列表]
    else:
        原始结果表: dict[int, tuple[str, str, bool, int]] = {}
        with ProcessPoolExecutor(max_workers=并行数) as 池:
            任务表 = {
                池.submit(_执行单包权威合规, 包目录): 序号
                for 序号, 包目录 in enumerate(包目录列表)
            }
            for 任务 in as_completed(任务表):
                序号 = 任务表[任务]
                try:
                    原始结果表[序号] = 任务.result()
                except Exception as 错误:
                    包目录 = 包目录列表[序号]
                    原始结果表[序号] = (
                        包目录.name, f"工作进程异常({type(错误).__name__}: {错误})", False, 0
                    )
        原始结果 = [原始结果表[序号] for 序号 in range(len(包目录列表))]
    for 结果 in 原始结果:
        证据列表.append(结果)
        名称, _, 通过, 通过数 = 结果
        if not 通过:
            未达标.append(f"{名称}({通过数}/13)")
    return not 未达标, 证据列表


def _校验依赖锁与反向篡改() -> tuple[bool, str, bool, str]:
    """校验真实依赖锁，并证明篡改后校验器会阻断。"""
    from 项目适配层.依赖锁定.锁定校验 import 校验锁定文件

    项目目录 = 系统根 / "示例项目" / "适配层示例"
    正向结果 = 校验锁定文件(项目目录, 系统根)
    正向证据 = (
        f"校验{正向结果.校验项数}项，无漂移"
        if 正向结果.成功
        else f"漂移: {'；'.join(正向结果.漂移列表[:3])}"
    )
    锁定路径 = 项目目录 / "依赖锁定.json"
    if not 锁定路径.is_file():
        return False, 正向证据, False, "缺少可供篡改验证的依赖锁定.json"
    try:
        锁定数据 = json.loads(锁定路径.read_text(encoding="utf-8"))
        if not 锁定数据.get("包列表"):
            return 正向结果.成功, 正向证据, False, "依赖锁没有可篡改的包条目"
        with tempfile.TemporaryDirectory(prefix="门禁_锁篡改_") as 临时目录:
            临时项目 = Path(临时目录)
            锁定数据["包列表"][0]["完整性摘要"] = "0" * 16
            (临时项目 / "依赖锁定.json").write_text(
                json.dumps(锁定数据, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            反向结果 = 校验锁定文件(临时项目, 系统根)
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as 错误:
        return 正向结果.成功, 正向证据, False, f"反向篡改检查异常: {错误}"
    反向通过 = not 反向结果.成功 and any("完整性摘要漂移" in 项 for 项 in 反向结果.漂移列表)
    反向证据 = f"篡改摘要后被阻断: {'；'.join(反向结果.漂移列表[:2])}"
    return 正向结果.成功, 正向证据, 反向通过, 反向证据


def _校验包反向篡改(包目录: Path) -> tuple[bool, str]:
    """安装候选包后篡改真实文件，证明仓库摘要校验会拒绝。"""
    from 平台控制面.包仓库.版本仓库 import 包仓库

    with tempfile.TemporaryDirectory(prefix="门禁_包篡改_") as 临时目录:
        仓库 = 包仓库(Path(临时目录) / "仓库")
        安装成功, 安装结果 = 仓库.安装(包目录)
        if not 安装成功:
            return False, f"候选包无法安装，不能执行反向检查: {安装结果}"
        目标路径 = Path(安装结果.安装路径)
        可篡改文件 = next(
            (文件 for 文件 in sorted(目标路径.rglob("*")) if 文件.is_file() and 文件.name != "完整性摘要.json"),
            None,
        )
        if 可篡改文件 is None:
            return False, "安装包没有可供篡改验证的文件"
        with 可篡改文件.open("ab") as 文件流:
            文件流.write("\n门禁反向篡改".encode("utf-8"))
        校验成功, 校验证据 = 仓库.校验完整性(
            安装结果.包id, 安装结果.版本, 安装结果.完整性摘要
        )
        return not 校验成功, f"篡改{可篡改文件.relative_to(目标路径)}后校验结果: {校验证据}"


def 执行门禁(*, 包目录: Path | None = None, 制品目录: Path | None = None, 运行测试: bool = True,
             运行编译: bool = True, 真实进程: bool = True,
             测试并行数: int = 16, 工作包超时秒: int = 180) -> 门禁结果:
    """执行全部发布门禁检查。"""
    结果 = 门禁结果()
    门禁项列表 = 结果.门禁项列表
    全部测试已执行 = False
    门禁HTML端口 = 0  # 制品句柄动态分配端口；门禁不占用固定端口，回收即释放

    def 检查(名称: str, 通过: bool, 详情: str = "", 强制: bool = True) -> None:
        if 强制 and not 详情.strip():
            通过 = False
            详情 = "缺少可复核证据"
        门禁项列表.append(门禁项(名称, 通过, 详情, 强制))

    待验证制品: Path | None = None
    制品来源 = ""
    try:
        待验证制品, 制品来源 = 选择待验证制品(制品目录)
        检查("正式制品目标", True, f"来源={制品来源}；制品路径={待验证制品}")
        身份通过, 身份详情, _ = 校验制品来源绑定(待验证制品)
        检查("正式制品来源与字节指纹", 身份通过, 身份详情)
        声明通过, 声明详情 = 校验第三方访问声明(待验证制品)
        检查("第三方权限网络文件进程声明", 声明通过, 声明详情)
    except Exception as 错误:
        检查("正式制品目标", False, str(错误))
        检查("正式制品来源与字节指纹", False, "无唯一正式制品可绑定")
        检查("第三方权限网络文件进程声明", False, "无唯一正式制品可核验")

    # 1. 包结构完整 + 包声明合法 + 能力契约合法。
    # 未指定单包时校验全部正式支持库和模块，模板不参与发布。
    包目录列表 = [包目录] if 包目录 is not None else sorted(
        [路径.parent for 路径 in (系统根 / "支持库").rglob("包声明.json")
         if not _是否已废弃包(路径.parent) and not _是聚合父包(路径.parent)]
        + [路径.parent for 路径 in (系统根 / "模块库").rglob("包声明.json")
           if 路径.parent.name != "_模板" and not _是否已废弃包(路径.parent)
           and not _是聚合父包(路径.parent)]
    )
    if 包目录列表:
        import json as _json
        结构问题: list[str] = []
        声明问题: list[str] = []
        for 当前包目录 in 包目录列表:
            声明路径 = 当前包目录 / "包声明.json"
            if not (声明路径.is_file() and (当前包目录 / "能力契约").is_dir() and (当前包目录 / "实现").is_dir()):
                结构问题.append(str(当前包目录.relative_to(系统根)))
                continue
            try:
                声明 = _json.loads(声明路径.read_text(encoding="utf-8"))
                if not (声明.get("包id") and 声明.get("版本") and 声明.get("类型")):
                    声明问题.append(str(当前包目录.relative_to(系统根)))
            except (_json.JSONDecodeError, OSError):
                声明问题.append(str(当前包目录.relative_to(系统根)))
        检查("包结构完整", not 结构问题,
             f"校验 {len(包目录列表)} 包；结构问题: {结构问题[:3] or '无'}")
        检查("包声明合法", not 声明问题,
             f"校验 {len(包目录列表)} 包；声明问题: {声明问题[:3] or '无'}")
        # 1.5 权威合规-逐包13/13 已移除（华哥裁决 2026-08-29：慢速审计不需要，
        #     能访问能拿数据就是没毛病）。发布只认 HTML 黑盒验证（编译产物真实 HTTP）。

        # 1.6 生产装配闭环（第三十阶段强制）：注册表唯一性 / 冷启动装配 /
        #     提供者进程一致 / 资源零残留 / 客户端制品一致性（全部调用生产验证器）
        try:
            # 1.6.1 注册表唯一性：全仓只允许一个 能力注册表 类定义（公共契约 权威）
            注册表定义文件: list[str] = []
            for 文件 in list((系统根 / "公共契约").rglob("*.py")) + list((系统根 / "运行核心").rglob("*.py")) + list((系统根 / "平台控制面").rglob("*.py")):
                if 文件.name.startswith("__"):
                    continue
                try:
                    if "class 能力注册表" in 文件.read_text(encoding="utf-8"):
                        注册表定义文件.append(str(文件.relative_to(系统根)))
                except OSError:
                    pass
            检查("注册表唯一性", len(注册表定义文件) == 1,
                 f"能力注册表 类定义位置: {注册表定义文件 or '未发现'}")
        except Exception as 错误:
            检查("注册表唯一性", False, f"异常: {错误}")


        try:
            # 1.6.3 提供者进程一致性（静态）：每个含 依赖锁.json 的适配层包，
            #     锁.提供者id 必须与包声明.包id 一致，且无锁适配层包不得存在
            #     （删锁/锁错绑 必须阻断）；隔离边界另查（C3 生产管理器）。
            import json as _锁json
            适配层根 = 系统根 / "支持库" / "适配层"
            锁问题: list[str] = []
            for 锁文件 in 适配层根.rglob("依赖锁.json"):
                锁数据 = _锁json.loads(锁文件.read_text(encoding="utf-8"))
                声明路径 = 锁文件.parent / "包声明.json"
                if not 声明路径.is_file():
                    锁问题.append(f"{锁文件.parent.name} 有锁无包声明")
                    continue
                声明 = _锁json.loads(声明路径.read_text(encoding="utf-8"))
                锁提供者 = str(锁数据.get("提供者id", "") or "")
                if 锁提供者 != 声明.get("包id"):
                    锁问题.append(
                        f"{锁文件.parent.name} 锁提供者id({锁提供者})≠包id({声明.get('包id')})"
                    )
            检查("提供者进程一致性", not 锁问题,
                 f"锁一致性问题: {锁问题[:5] or '无'}")
            from 运行核心.运行环境管理器.提供者生命周期 import 提供者生命周期管理器
            生命周期管理器 = 提供者生命周期管理器(提供者根目录=适配层根)
            隔离问题 = 生命周期管理器.检查隔离边界()
            检查("提供者隔离边界", not 隔离问题,
                 f"隔离边界问题: {隔离问题[:5] or '无'}")
        except Exception as 错误:
            检查("提供者进程一致性", False, f"异常: {错误}")
            检查("提供者隔离边界", False, f"异常: {错误}")

        # 原名「发布链制品一致性」名实不符：此处只断言「选出了唯一待验证制品」，
        # 并不比对各阶段是否同一制品（那需要 HTML 报告，此刻尚未产出）。真正的
        # 跨阶段一致性由 校验契约与HTML矩阵 里 报告.制品路径==待验证制品 断言，
        # 外加 待验证制品字节不变 复核；本项只做存在性，故如实更名。
        检查(
            "唯一待验证制品", 待验证制品 is not None,
            f"来源={制品来源}；制品路径={待验证制品}；"
            "跨阶段一致性（来源绑定/HTML矩阵/字节不变）由对应判定项分别断言"
            if 待验证制品 is not None else "无唯一待验证制品，无法进入 HTML 矩阵核验",
        )
    else:
        检查("包结构完整", False, "未发现任何正式候选包")
        检查("包声明合法", False, "未发现任何正式候选包")

    # 依赖方向与公开调用完整性是发布必经门禁，不能只作为独立脚本存在。
    # 两者都直接审计当前源码树，失败时保留文件/行号清单供修复定位。
    try:
        from 运行核心.依赖防火墙 import 审计依赖, 审计结果转清单
        依赖结果 = 审计依赖(系统根)
        依赖详情 = "无" if 依赖结果.成功 else "；".join(审计结果转清单(依赖结果)[:20])
        检查("依赖防火墙", 依赖结果.成功,
             f"审计文件数={依赖结果.审计文件数}；违规={依赖详情}")
    except Exception as 错误:
        检查("依赖防火墙", False, f"审计异常: {错误}")
    try:
        from 开发工具.公开调用完整性门禁 import 运行门禁 as 运行公开调用门禁
        公开调用违规 = 运行公开调用门禁(系统根)
        公开调用详情 = "无" if not 公开调用违规 else "；".join(
            f"{项.get('缺口类型')}:{项.get('包')}:{项.get('能力id')}" for 项 in 公开调用违规[:20])
        检查("公开调用完整性", not 公开调用违规,
             f"违规={公开调用详情}")
    except Exception as 错误:
        检查("公开调用完整性", False, f"审计异常: {错误}")

    # 契约声明一致（注册口径）：**只报不拦**接线（批次0-4）。
    # `契约.能力契约.契约.校验声明一致` 曾零生产调用点（落点清单_03 重要-10），
    # 这里是它的编译期落点：逐包比对 包入口注册表 的 返回/参数 与 能力契约 JSON，
    # 返回口径先经 `契约.归一注册口径` 归一（注册 `结果` ≡ 契约 `结果型`），
    # 否则首报约 370 条里 351 条是纯写法噪声。
    # 判据是「归一后仍不一致」，量级约 19 条真实存量差异 → 逐包修复属批次4，
    # 因此此刻**显式 强制=False**：只报不拦，避免全仓门禁变红掩盖其它真实回归。
    try:
        from 开发工具.契约编译.漂移检测 import 全仓注册口径统计
        口径统计 = 全仓注册口径统计(系统根)
        口径问题 = 口径统计["问题列表"]
        检查(
            "契约声明一致（注册口径，只报）",
            not 口径问题,
            f"契约能力 {口径统计['契约能力数']}；已解析注册 {口径统计['已解析注册数']}"
            f"（未解析注册 {口径统计['未解析注册数']}／返回口径未解析 "
            f"{口径统计['返回未解析数']}／参数口径未解析 {口径统计['参数未解析数']}）；"
            f"归一后不一致 {len(口径问题)} 条: {'；'.join(口径问题[:5]) or '无'}",
            强制=False,
        )
    except Exception as 错误:
        检查("契约声明一致（注册口径，只报）", False, f"检测异常: {错误}", 强制=False)


    # 2. 中文边界（核心代码无英文业务命名扫描；排除协议回调）
    中文扫描 = _扫描英文函数命名()
    检查("中文边界", not 中文扫描, f"英文命名文件: {中文扫描[:100] or '无'}")

    # 3. HTML 黑盒验证：只运行上面已确定的同一正式制品；不允许任何回退。
    if 运行测试:
        if 待验证制品 is None:
            检查("HTML黑盒验证", False, "缺少明确待发布或正式激活制品")
            检查("HTML契约真实执行矩阵", False, "无制品，未产生正式HTML执行矩阵")
            检查("待验证制品字节不变", False, "无制品，无法核验验证前后字节")
            全部测试已执行 = False
        else:
            验证器 = 系统根 / "开发工具" / "HTML验证" / "验证器.py"
            if not 验证器.is_file():
                检查("HTML黑盒验证", False, f"验证器缺失: {验证器}")
                检查("HTML契约真实执行矩阵", False, "冻结HTML验证器缺失")
                检查("待验证制品字节不变", False, "验证未执行")
                全部测试已执行 = False
            else:
                验证前: dict[str, bytes] = {}
                只读通过 = False
                只读详情 = "验证未完成"
                try:
                    验证前 = 读取制品字节快照(待验证制品)
                    缓存根, 缓存环境 = 构建验证缓存环境(待验证制品)
                    退出码, 输出 = 运行子进程([
                        sys.executable, "-u", "-m", "开发工具.HTML验证.验证器", "--制品", str(待验证制品),
                        "--并发", str(max(1, int(测试并行数))),
                        "--端口", str(门禁HTML端口),
                    ], 超时秒=600, 实时输出=True, 环境覆盖={**缓存环境, **环境依赖注入()})
                    失败项 = "\n".join(
                        行 for 行 in 输出.splitlines()
                        if "失败" in 行 or "✗" in 行 or "阻断" in 行
                    )
                    测试证据 = f"退出码 {退出码}（{'通过' if 退出码 == 0 else '失败'}）"
                    if 失败项:
                        测试证据 += f"；失败摘要: {失败项[:600]}"
                    证据匹配 = re.findall(r"^证据:\s*(.+)$", 输出, flags=re.MULTILINE)
                    if not 证据匹配:
                        raise ValueError("冻结HTML验证器未输出证据路径")
                    证据路径 = Path(证据匹配[-1].strip())
                    报告 = json.loads(证据路径.read_text(encoding="utf-8"))
                    矩阵通过, 矩阵详情, 能力数 = 校验契约与HTML矩阵(待验证制品, 报告)
                    检查("HTML黑盒验证", 退出码 == 0, 测试证据)
                    检查("HTML契约真实执行矩阵", 矩阵通过,
                         f"能力数={能力数}；{矩阵详情}；证据={证据路径}")
                    全部测试已执行 = 退出码 == 0 and 矩阵通过
                except Exception as 错误:
                    检查("HTML黑盒验证", False, f"验证器执行异常: {错误}")
                    检查("HTML契约真实执行矩阵", False, f"执行矩阵不可消费: {错误}")
                    全部测试已执行 = False
                finally:
                    try:
                        if 验证前:
                            验证后 = 读取制品字节快照(待验证制品)
                            只读通过, 只读详情 = 核验制品字节未变(验证前, 验证后)
                    except Exception as 错误:
                        只读通过, 只读详情 = False, f"字节复核异常: {错误}"
                    检查("待验证制品字节不变", 只读通过, 只读详情)
                    全部测试已执行 = 全部测试已执行 and 只读通过
    else:
        检查("HTML黑盒验证", False, "已请求跳过验证，强制门禁未执行")
        检查("HTML契约真实执行矩阵", False, "已请求跳过验证")
        检查("待验证制品字节不变", False, "已请求跳过验证")
    if 运行编译:
        # 编译必须验证当前门禁实际运行的解释器，避免 PATH 中另一个
        # python3.14 对不同标准库/语法环境产生错误绿灯。
        编译命令 = [sys.executable, "-m", "py_compile"]
        编译命令 += [str(文件) for 文件 in _正式Python源码文件()]
        退出码, 输出 = 运行子进程(编译命令, 超时秒=120)
        检查("语法编译全部通过", 退出码 == 0, f"退出码 {退出码}")
    else:
        检查("语法编译全部通过", False, "已请求跳过编译，强制门禁未执行")


    # 4. 提供者可启动可停止 + 最小能力调用成功（真实子进程）
    if 真实进程:
        try:
            from 运行核心.加载器.提供者隔离.独立进程 import 独立进程
            进程 = 独立进程("门禁进程")
            启动成功, 启动消息 = 进程.启动()
            调用结果 = 进程.调用(能力id="进程.最小操作", 参数={"名称": "门禁调用"}) if 启动成功 else None
            停止成功, _ = 进程.优雅停止()
            检查("提供者可启动可停止", 启动成功 and 调用结果 is not None and 调用结果.成功 and 停止成功,
                 f"启动:{启动消息} 调用:{调用结果.成功 if 调用结果 else '未执行'} 停止:{停止成功}")
            检查("最小能力调用成功", bool(调用结果 and 调用结果.成功), f"值: {调用结果.值 if 调用结果 else '无'}")
        except Exception as 错误:
            检查("提供者可启动可停止", False, f"异常: {错误}")
            检查("最小能力调用成功", False, f"异常: {错误}")
    else:
        检查("提供者可启动可停止", False, "已禁止真实进程，强制门禁未执行")
        检查("最小能力调用成功", False, "已禁止真实进程，强制门禁未执行")

    # 4.5 权威状态、真实迁移和栅栏令牌生产场景
    try:
        from 开发工具.发布门禁.权威状态门禁 import 执行权威状态门禁
        for 名称, 通过, 详情 in 执行权威状态门禁():
            检查(名称, 通过, 详情)
    except Exception as 错误:
        检查("权威状态专项门禁", False, f"专项门禁不可执行: {错误}")

    # 5. 热切换成功 + 自动回滚成功（真实进程路径，失败场景）
    切换 = None
    try:
        from 运行核心.加载器.版本系统.热切换 import 热切换管理器
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        注册表 = 版本注册表(Path(门禁临时目录()) / "版本")
        注册表.注册版本("门禁.能力", "1.0.0", 声明字典={"包id": "门禁.能力", "版本": "1.0.0"})
        注册表.注册版本("门禁.能力", "1.1.0", 声明字典={"包id": "门禁.能力", "版本": "1.1.0"})
        切换 = 热切换管理器(注册表)
        切换.设置激活("门禁.能力", "1.0.0", 回退版本="1.0.0")
        成功结果 = 切换.真实热切换(能力id="门禁.能力", 新版本="1.1.0", 回退版本="1.0.0",
                               新进程启动失败=False)
        检查("热切换成功", 成功结果.成功, f"步骤: {' → '.join(成功结果.步骤列表[-3:])}")
        失败结果 = 切换.真实热切换(能力id="门禁.能力", 新版本="1.1.0", 回退版本="1.0.0",
                               新进程健康失败=True)
        检查("自动回滚成功", 失败结果.自动回滚, f"回滚记录: {失败结果.回滚记录}")
    except Exception as 错误:
        检查("热切换成功", False, f"异常: {错误}")
        检查("自动回滚成功", False, f"异常: {错误}")
    finally:
        if 切换 is not None:
            临时进程集合 = set(切换.路由表.values())
            for 版本进程表 in 切换.提供者进程表.values():
                临时进程集合.update(版本进程表.values())
            for 临时进程 in 临时进程集合:
                临时进程.关闭并清理()

    # 6. 失败日志可查询 + 诊断复现可执行
    try:
        import tempfile as _临时
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
        from 运行核心.运行诊断.诊断中心.诊断复现 import 复现执行
        临时目录 = _创建门禁临时目录(前缀="门禁_")
        失败库 = 失败记录库(临时目录)
        记录 = 失败库.登记失败(追踪id="门禁", 包id="门禁.包", 错误码="外部未安装", 错误说明="驱动缺失")
        可查询 = len(失败库.查询(包id="门禁.包")) == 1
        检查("失败日志可查询", 可查询, f"查询到 {1 if 可查询 else 0} 条")
        复现 = 复现执行(记录, 临时目录=临时目录)
        检查("诊断复现可执行", 复现.结论 in ("可稳定复现", "无法复现"), f"结论: {复现.结论}")
    except Exception as 错误:
        检查("失败日志可查询", False, f"异常: {错误}")
        检查("诊断复现可执行", False, f"异常: {错误}")

    # 7. 旧版本引用保护生效
    try:
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        注册表 = 版本注册表(Path(门禁临时目录()) / "版本保护")
        注册表.注册版本("门禁.保护", "1.0.0", 声明字典={"包id": "门禁.保护", "版本": "1.0.0"})
        注册表.标记引用("门禁.保护", "1.0.0", "旧项目")
        可删, 原因 = 注册表.确认可删除("门禁.保护", "1.0.0")
        检查("旧版本引用保护生效", not 可删, f"拒绝原因: {原因}")
    except Exception as 错误:
        检查("旧版本引用保护生效", False, f"异常: {错误}")

    # 8. 依赖锁一致 + 完整性摘要一致 + 真实反向篡改阻断
    try:
        锁一致, 锁证据, 锁篡改阻断, 锁篡改证据 = _校验依赖锁与反向篡改()
        检查("依赖锁一致", 锁一致, 锁证据)
        检查("依赖锁反向篡改阻断", 锁篡改阻断, 锁篡改证据)
    except Exception as 错误:
        检查("依赖锁一致", False, f"校验异常: {错误}")
        检查("依赖锁反向篡改阻断", False, f"校验异常: {错误}")
    if 包目录列表:
        try:
            摘要结果 = [(目录, *_校验文件清单摘要(目录)) for 目录 in 包目录列表]
            摘要问题 = [f"{目录.relative_to(系统根)}: {证据}" for 目录, 通过, 证据 in 摘要结果 if not 通过]
            检查("完整性摘要一致", not 摘要问题,
                 f"逐文件校验 {len(摘要结果)} 包；问题: {摘要问题[:2] or '无'}")
            篡改阻断, 篡改证据 = _校验包反向篡改(包目录列表[0])
            检查("包内容反向篡改阻断", 篡改阻断, 篡改证据)
        except Exception as 错误:
            检查("完整性摘要一致", False, f"校验异常: {错误}")
            检查("包内容反向篡改阻断", False, f"校验异常: {错误}")
    else:
        检查("完整性摘要一致", False, "没有候选包可供校验")
        检查("包内容反向篡改阻断", False, "没有候选包可执行反向篡改")


    # 9. 浏览器真实交互（页面生成 + 网关调用要素）
    try:
        from 前端核心.浏览器交互 import 浏览器交互提供者
        from 支持库.前端.浏览器宿主 import 启动网页服务
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        提供者 = 浏览器交互提供者(网关地址="http://127.0.0.1:0")
        页面 = 提供者.渲染(_浏览器请求())
        HTML通过 = 页面["成功"] and "fetch" in 页面["html"] and "调用网关" in 页面["html"] \
            and "错误区" in 页面["html"] and "加载状态" in 页面["html"]
        服务 = None
        try:
            服务, 地址 = 启动网页服务(
                标题="门禁网页", 页面说明="真实 HTTP 交互",
                网关地址="http://127.0.0.1:45082", 能力id="门禁.回显",
                端口=0, 自动打开=False,
            )
            页面响应 = urlopen(Request(地址, method="GET"), timeout=3).read().decode("utf-8")
            旧API请求 = Request(地址 + "/api/%E8%B0%83%E7%94%A8", data=b"{}",
                               headers={"Content-Type": "application/json"}, method="POST")
            try:
                urlopen(旧API请求, timeout=3)
                旧API状态 = 200
            except HTTPError as 错误:
                旧API状态 = 错误.code
            HTTP通过 = "门禁网页" in 页面响应 and "/网关/调用" in 页面响应 \
                and "/api/调用" not in 页面响应 and 旧API状态 == 404
        finally:
            if 服务 is not None:
                服务.shutdown()
                服务.server_close()
        浏览器通过 = HTML通过 and HTTP通过
        检查("浏览器真实交互", 浏览器通过,
             f"HTML要素={'通过' if HTML通过 else '失败'}；旧API 404={'通过' if HTTP通过 else '失败'}")
    except Exception as 错误:
        检查("浏览器真实交互", False, f"异常: {错误}")

    # 10. HTTP 流式响应（事件序列 + 完成 + 断开清理）
    try:
        from 运行核心.统一网关.流式HTTP import HTTP流式管理器
        管理器 = HTTP流式管理器()
        通道 = 管理器.开始(能力id="门禁.流式", 事件生成函数=lambda: iter([{"片段": "a"}, {"片段": "b"}]))
        事件类型表 = [事件["事件类型"] for 事件 in 通道.事件队列]
        流式通过 = "首个事件" in 事件类型表 and "中间事件" in 事件类型表 and "完成事件" in 事件类型表
        管理器.断开(通道.请求id)
        # 完成态通道由管理器自动移除，不再要求消费端对象被强行改成
        # “断开”；未完成态则必须显式断开并清空待消费事件。
        断开清理 = (
            (通道.断开 and 通道.事件队列 == [])
            or (通道.结束 and 管理器.查询(通道.请求id) is None)
        )
        检查("HTTP 流式响应", 流式通过, f"事件: {'→'.join(事件类型表)}")
        检查("客户端断开清理", 断开清理, "事件已释放，通道已移除")
    except Exception as 错误:
        检查("HTTP 流式响应", False, f"异常: {错误}")
        检查("客户端断开清理", False, f"异常: {错误}")

    # 11. 独立任务进程 + 任务取消
    try:
        import tempfile as _临时2
        from 运行核心.任务调度.任务进程 import 任务进程池
        进程池 = 任务进程池(存储目录=_创建门禁临时目录(前缀="门禁_任务_"))
        进程池.注册执行函数("门禁.任务", lambda 参数: {"完成": True})
        任务对象 = 进程池.提交(能力id="门禁.任务", 参数={"x": 1}, 超时秒=5)
        截止 = time.monotonic() + 5
        while 进程池.查询状态(任务对象.任务id) not in ("成功", "失败", "崩溃", "超时") and time.monotonic() < 截止:
            time.sleep(0.02)
        检查("独立任务进程", 进程池.查询状态(任务对象.任务id) == "成功", f"状态: {进程池.查询状态(任务对象.任务id)}")
        # 真取消：必须取消一个**运行中**的任务。原实现提交的是未注册的能力「门禁.慢任务」，
        # 提交即落终态「失败」，取消只走了「已在终态 → 幂等 True」这条分支，
        # 真正终止工作进程组的路径零证据（判据 5 反向检查恒真）。
        进程池.注册执行函数(
            "门禁.慢任务",
            lambda 参数: (time.sleep(float(参数.get("睡", 5))), {"完成": True})[1],
        )
        慢任务 = 进程池.提交(能力id="门禁.慢任务", 参数={"睡": 5}, 超时秒=20)
        运行截止 = time.monotonic() + 5
        while (进程池.查询状态(慢任务.任务id) not in ("运行中", "成功", "失败", "崩溃", "超时")
               and time.monotonic() < 运行截止):
            time.sleep(0.02)
        取消成功, 取消消息 = 进程池.取消(慢任务.任务id)
        收敛截止 = time.monotonic() + 10
        while (进程池.查询状态(慢任务.任务id) not in ("成功", "失败", "崩溃", "超时", "已取消")
               and time.monotonic() < 收敛截止):
            time.sleep(0.02)
        取消终态 = 进程池.查询状态(慢任务.任务id)
        检查("任务取消（运行中真终止）", 取消成功 and 取消终态 == "已取消",
             f"取消返回={取消成功}（{取消消息}）；终态={取消终态}")
        取消幂等, _ = 进程池.取消(慢任务.任务id)
        检查("任务取消幂等", 取消幂等, "已终态任务再次取消必须返回成功（幂等）")
        进程池.关闭全部()
    except Exception as 错误:
        检查("独立任务进程", False, f"异常: {错误}")
        检查("任务取消（运行中真终止）", False, f"异常: {错误}")
        检查("任务取消幂等", False, f"异常: {错误}")

    # 12. 发布事务恢复（未完成操作 → 回滚）
    try:
        from 平台控制面.发布管理.发布事务.事务恢复 import 事务恢复
        恢复 = 事务恢复(Path(门禁临时目录()) / "门禁事务")
        操作id = 恢复.记录准备(操作名="安装", 包id="门禁.包", 版本="1.0.0",
                             回滚函数名="回滚安装")
        恢复.注册回滚函数("回滚安装", lambda 记录: None)
        未完成 = 恢复.扫描未完成()
        恢复结果 = 恢复.恢复()
        检查("发布事务恢复", len(未完成) == 1 and 恢复结果 and 恢复结果[0]["处理"] == "回滚",
             f"未完成 {len(未完成)} 项 → 已回滚")
    except Exception as 错误:
        检查("发布事务恢复", False, f"异常: {错误}")

    # 13. 网关权限 + 限流 + 敏感配置保护
    try:
        from 运行核心.统一网关.安全边界 import 凭证管理器, 脱敏错误信息
        import os as _os
        旧值 = _os.environ.get("门禁凭证", "")
        _os.environ["门禁凭证"] = "门禁密钥123"
        凭证 = 凭证管理器("门禁凭证")
        加载成功, _ = 凭证.加载()
        校验成功, _ = 凭证.校验("门禁密钥123")
        校验失败, _ = 凭证.校验("错误")
        缺失凭证 = 凭证管理器("不存在的变量名_门禁")
        缺失成功, 缺失消息 = 缺失凭证.加载()
        脱敏后 = 脱敏错误信息("连接失败 sk-门禁密钥原文")
        检查("网关权限", 加载成功 and 校验成功 and not 校验失败 and not 缺失成功,
             f"凭证校验: {'通过' if 校验成功 else '失败'}；缺失凭证: {缺失消息}")
        检查("敏感配置保护", "sk-门禁密钥原文" not in 脱敏后 and "已脱敏" in 脱敏后,
             f"脱敏: {脱敏后[:30]}")
        if 旧值:
            _os.environ["门禁凭证"] = 旧值
        else:
            _os.environ.pop("门禁凭证", None)
    except Exception as 错误:
        检查("网关权限", False, f"异常: {错误}")
        检查("敏感配置保护", False, f"异常: {错误}")
    try:
        from 运行核心.统一网关.限流器 import 限流器
        限流 = 限流器(最大并发请求=1, 单用户频率=2)
        通过1, _ = 限流.进入请求(用户id="门禁用户", 能力id="门禁.能力")
        限流.离开请求()
        通过2, _ = 限流.进入请求(用户id="门禁用户", 能力id="门禁.能力")
        限流.离开请求()
        通过3, _ = 限流.进入请求(用户id="门禁用户", 能力id="门禁.能力")
        限流通过 = 通过1 and 通过2 and not 通过3
        检查("网关限流", 限流通过, f"第1次:{通过1} 第2次:{通过2} 第3次(超限拒绝):{not 通过3}")
    except Exception as 错误:
        检查("网关限流", False, f"异常: {错误}")

    # 14. 有状态自动排空（后端核心自动计数）
    try:
        from 后端核心.后端核心 import 后端核心
        后端 = 后端核心()
        后端.启动()
        后端.启用自动排空(排空超时秒=1)
        调用结果 = 后端.调用("文件系统支持库.文件操作.读取文件", {"文件路径": "不存在.txt"})
        自动排空通过 = 后端.排空 is not None and 后端.排空.活动总数() == 0
        检查("有状态自动排空", 自动排空通过, f"活动计数归零: {后端.排空.活动总数()}")
    except Exception as 错误:
        检查("有状态自动排空", False, f"异常: {错误}")

    # 15. 进程内流式完成（原判定项名「性能阈值」声称核心回归 < 2.5 秒，但代码从不比较
    #     任何耗时，秒数只是打印信息 → 名实不符，故更名如实描述；真实耗时仍打出来供观察）
    try:
        开始 = time.monotonic()
        from 运行核心.统一网关.流式HTTP import HTTP流式管理器
        流式 = HTTP流式管理器()
        调用对象 = 流式.开始(
            能力id="门禁.性能", 事件生成函数=lambda: iter([{"i": 1}, {"i": 2}]),
        )
        性能通过 = 调用对象.结束 and any(
            事件.get("事件类型") == "完成事件" for 事件 in 调用对象.事件队列
        )
        检查("进程内流式完成", 性能通过, f"真实耗时 {time.monotonic() - 开始:.2f} 秒")
    except Exception as 错误:
        检查("进程内流式完成", False, f"异常: {错误}")

    # 16. 所有子进程清理 + 所有监听端口释放
    try:
        from 运行核心.加载器.提供者隔离.独立进程 import 独立进程
        基线监听 = _监听端口快照()
        进程 = 独立进程("门禁清理")
        启动成功, 启动消息 = 进程.启动()
        进程.优雅停止()
        清理通过 = 进程.进程 is None or 进程.进程.poll() is not None
        检查("所有子进程清理", 清理通过, f"进程退出码: {进程.退出码}")
        终态监听 = _监听端口快照()
        新增监听 = sorted(终态监听 - 基线监听)
        # 原判定项名「所有监听端口释放」声称覆盖「所有」端口，实际只观察这一个
        # stdin/stdout 管道子进程（它本就不开 TCP 监听）→ 新增监听集合恒空，
        # 该项等价于「启动→停止→无残留」的回归哨兵，故更名如实描述观察范围。
        检查("子进程无新增监听端口", 启动成功 and not 新增监听,
             f"观察对象=门禁清理子进程（管道型，不监听端口）；基线 {len(基线监听)} 个；"
             f"终态新增监听: {新增监听 or '无'}")
    except Exception as 错误:
        检查("所有子进程清理", False, f"异常: {错误}")
        检查("子进程无新增监听端口", False, f"异常: {错误}")

    # ---- 平台控制面专项（第十二阶段：真实行为检查，复用验证证据不重复跑测试）----
    try:
        import tempfile as _临时
        from 平台控制面.统一入口 import 统一能力服务
        from 平台控制面.发布管理 import 发布管理
        from 支持库.适配层 import 生成密钥对 as _密钥对
        平台目录 = _创建门禁临时目录(前缀="门禁平台_")
        平台服务 = 统一能力服务(平台目录)
        # 1. 未确认需求创建组件必须被拒（需求直达门禁）+ 授权不可自举
        快照 = 平台服务.需求.登记需求(目标="门禁需求")
        令牌 = 平台服务.授权.注册身份(身份id="门禁Agent")
        # 授权自举检查：注册后不能自行切高权限
        升权被拒, _ = 平台服务.授权.切换角色(令牌, "组件开发Agent")
        检查("平台-授权不可自举", not 升权被拒, "注册身份默认最低角色，禁止自选高权限")
        平台服务.授权.引导授予(身份id="门禁Agent", 角色="组件开发Agent", 授予者="系统引导")
        平台服务.授权.切换角色(令牌, "组件开发Agent")
        预算 = {"内存上限": 50, "线程上限": 2, "子进程上限": 1, "并发调用上限": 2,
                "队列长度": 5, "文件句柄上限": 20, "临时空间上限": 50, "单次调用超时": 3,
                "每分钟重启次数": 2, "空闲回收时间": 30}
        # 空需求id绕过检查
        结果空 = 平台服务.执行操作(令牌=令牌, 操作="创建组件", 参数={
            "能力id": "门禁.能力", "需求id": "", "复用决策": {"搜索词": "门禁", "候选能力id": ["x"]},
            "资源预算": 预算, "允许修改路径": ["a"], "组件声明": {"名称": "x"}})
        检查("平台-空需求id阻断", 结果空.get("错误码") == "REQUIREMENT_REQUIRED",
              f"错误码={结果空.get('错误码')}")
        结果1 = 平台服务.执行操作(令牌=令牌, 操作="创建组件", 参数={
            "能力id": "门禁.能力", "需求id": 快照["需求id"],
            "复用决策": {"搜索词": "门禁", "候选能力id": ["x"]}, "资源预算": 预算,
            "允许修改路径": ["a"], "组件声明": {"名称": "x"}})
        检查("平台-未确认需求阻断开发", not 结果1["成功"],
              f"错误码={结果1.get('错误码')}")
        # 2. 陈旧监督器旧令牌切换必须被拒（激活指针 CAS）
        发布 = 发布管理(平台服务.状态)
        发布id = 发布.登记期望版本(包id="门禁核心", 期望版本="1")
        发布.激活(发布id=发布id, 目标="v1")
        新令牌切换, 切换消息 = 发布.切换激活指针(
            指针id="门禁核心", 目标="v2", 期望版本=1, 期望令牌=1)
        陈旧被拒, _ = 发布.切换激活指针(指针id="门禁核心", 目标="v3", 期望版本=1, 期望令牌=1)
        # 必须带正向对照：若首次切换本身没成（指针未建/CAS 失效），两次都 False，
        # 只断言「第二次被拒」会恒真通过。
        检查("平台-陈旧栅栏令牌被拒", 新令牌切换 and not 陈旧被拒,
              f"首次新令牌切换={新令牌切换}（{切换消息}）；同一旧令牌再次切换被拒={not 陈旧被拒}")
        # 3. 未签名包拒绝安装（可信制品门禁）
        私钥, 公钥 = _密钥对()
        平台服务.仓库.登记发布者(发布者="门禁发布者", 公钥PEM=公钥)
        成功构建, _, 摘要 = 平台服务.仓库.构建制品(
            包id="门禁包", 版本="1", 文件表={"主.py": "x"}, 构建输入={"源": "门禁"})
        安装成功, 安装消息 = 平台服务.仓库.安装制品(
            制品摘要=摘要, 目标目录=平台目录 / "安装")
        检查("平台-未签名包拒绝安装", 成功构建 and not 安装成功,
              f"安装消息={安装消息[:60]}")
        # 4. 需求确认后创建组件通过（正向闭环）
        平台服务.需求.确认需求(需求id=快照["需求id"])
        结果4 = 平台服务.执行操作(令牌=令牌, 操作="创建组件", 参数={
            "能力id": "门禁.能力", "需求id": 快照["需求id"],
            "复用决策": {"搜索词": "门禁", "候选能力id": ["x"]}, "资源预算": 预算,
            "允许修改路径": ["a"], "组件声明": {"名称": "x"}})
        检查("平台-需求确认后开发放行", 结果4["成功"],
              f"消息={结果4.get('消息', '')[:60]}")
    except Exception as 错误:
        检查("平台-授权不可自举", False, f"异常: {错误}")
        检查("平台-空需求id阻断", False, f"异常: {错误}")
        检查("平台-未确认需求阻断开发", False, f"异常: {错误}")
        检查("平台-陈旧栅栏令牌被拒", False, f"异常: {错误}")
        检查("平台-未签名包拒绝安装", False, f"异常: {错误}")
        检查("平台-需求确认后开发放行", False, f"异常: {错误}")

    # 5. 提供者注册表真实调用（第十三阶段：真实提供者链）
    try:
        from 平台控制面.提供者.注册表 import 注册表
        平台注册表 = 注册表(平台服务.状态, 平台服务.监督)
        预算提供者 = {"内存上限": 50, "线程上限": 2, "子进程上限": 1, "并发调用上限": 2,
                      "队列长度": 5, "文件句柄上限": 20, "临时空间上限": 50,
                      "单次调用超时": 3, "每分钟重启次数": 2, "空闲回收时间": 30}
        平台注册表.注册(能力id="门禁.真实能力", 调用函数=lambda: 42, 预算=预算提供者)
        调用结果 = 平台注册表.调用(能力id="门禁.真实能力")
        检查("平台-提供者真实调用", 调用结果["成功"] and 调用结果["结果"] == 42,
              f"真实返回值={调用结果.get('结果')}")
        未注册结果 = 平台注册表.调用(能力id="门禁.未注册")
        检查("平台-未注册提供者失败",
              not 未注册结果["成功"] and 未注册结果["错误码"] == "CAPABILITY_NOT_FOUND",
              f"错误码={未注册结果.get('错误码')}")
        # 动态库提供者宿主检测（真实加载 libsqlite3，模块级中文契约）
        from 平台控制面.提供者.动态库提供者 import 调用 as 动态库调用
        库结果 = 动态库调用("libsqlite3", "sqlite3_libversion", [])
        检查("平台-动态库真实调用", 库结果.成功 and bool(库结果.值),
              f"版本={库结果.值}")
    except Exception as 错误:
        检查("平台-提供者真实调用", False, f"异常: {错误}")
        检查("平台-未注册提供者失败", False, f"异常: {错误}")
        检查("平台-动态库真实调用", False, f"异常: {错误}")

    # 6. 慢速层真实执行 已移除（华哥裁决 2026-08-29：慢速审计不需要，
    #    能访问能拿数据就是没毛病）。发布只认 HTML 黑盒验证（编译产物真实 HTTP）。

    # ===== 第十四阶段十项门禁（真实调用生产实现，禁止复制测试判断）=====
    try:
        from 开发工具.发布门禁.第十四阶段门禁 import 执行十项门禁
        for 名称, 通过, 详情 in 执行十项门禁(系统根):
            检查(名称, 通过, 详情)
    except Exception as 错误:
        检查("第十四阶段-十项门禁加载", False, f"异常: {错误}")

    # 工程缓存不得有 Python 正式源码（候选实现必须已生产化；制品仓库是
    # 内容寻址制品数据目录，其内文件为构建产物，不属于源码；提供者运行
    # 环境是受管 venv（pip 安装的第三方依赖），不属于正式源码）
    try:
        缓存源码表 = _扫描工程缓存Python源码()
        检查("工程缓存无Python源码", not 缓存源码表,
             f"工程缓存源码文件数: {len(缓存源码表)}（应为0）{缓存源码表[:3]}")
    except Exception as 错误:
        检查("工程缓存无Python源码", False, f"异常: {错误}")


    # 24 个旧过渡顶层目录不得存在
    try:
        旧过渡目录表 = ["加载器", "异步任务", "有状态排空", "控制调用", "网关", "诊断中心",
                      "提供者隔离", "版本系统", "运行上下文", "运行事件", "能力搜索器",
                      "说明书生成器", "契约编译", "组件规范", "组件合规", "反向破坏",
                      "审计", "发布门禁", "外部适配层", "配置安全", "Agent查询",
                      "验证器", "包仓库", "发布事务"]
        残留表 = [名称 for 名称 in 旧过渡目录表 if (系统根 / 名称).exists()]
        检查("旧过渡目录不存在", not 残留表, f"残留: {残留表 or '无'}")
    except Exception as 错误:
        检查("旧过渡目录不存在", False, f"异常: {错误}")

    结果.汇总()
    return 结果


def _浏览器请求() -> Any:
    """构造浏览器渲染请求（供门禁检查用）。"""
    from 前端核心.前端核心 import 组件定义, 窗口定义, 页面定义
    from 前端核心.前端核心 import 渲染请求
    窗口 = 窗口定义(
        "门禁窗口", "门禁浏览器",
        [页面定义("主页", "/", "门禁页", [
            组件定义("输入", "输入框", {"默认值": "a"}, ["输入"]),
            组件定义("按钮", "按钮", {"能力id": "门禁.能力", "参数": {}}, ["点击"]),
            组件定义("加载状态", "状态区", {}, []),
            组件定义("错误区", "状态区", {}, []),
        ])],
    )
    return 渲染请求(窗口, {}, "浏览器交互")


def 门禁临时目录() -> str:
    import tempfile
    return tempfile.gettempdir()


def 主函数(argv: list[str] | None = None) -> int:
    import argparse
    解析器 = argparse.ArgumentParser(description="系统级支持库 发布门禁")
    解析器.add_argument("--制品", default="", help="明确待发布制品目录；缺省只验证正式激活制品")
    解析器.add_argument("--包目录", default="", help="待发布包目录（含 包声明.json）")
    解析器.add_argument("--跳过测试", action="store_true", help="跳过测试执行（不推荐）")
    解析器.add_argument("--禁止真实进程", action="store_true", help="跳过真实进程检查")
    解析器.add_argument(
        "--测试并行数", type=int, default=32,
        help="全量测试工作包并行数（默认最多32；共享资源阶段仍串行）",
    )
    解析器.add_argument(
        "--工作包超时秒", type=int, default=180,
        help="单个测试工作包硬超时秒数（默认180；超时立即终止并报告失败）",
    )
    参数 = 解析器.parse_args(argv)
    结果 = 执行门禁(
        包目录=Path(参数.包目录) if 参数.包目录 else None,
        制品目录=Path(参数.制品) if 参数.制品 else None,
        运行测试=not 参数.跳过测试,
        真实进程=not 参数.禁止真实进程,
        测试并行数=参数.测试并行数,
        工作包超时秒=参数.工作包超时秒,
    )
    print(结果.打印())
    print("发布状态:", 结果.发布状态)
    return 0 if 结果.发布状态 == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(主函数())
