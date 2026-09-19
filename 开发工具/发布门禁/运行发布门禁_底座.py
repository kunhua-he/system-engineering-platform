"""发布门禁底座：主文件与全部子模块共用的低层件。

内容：项目根 `系统根`、门禁结果模型（`门禁项`/`门禁结果`）、门禁临时目录注册表
（`_清理门禁临时目录`/`_创建门禁临时目录`/`门禁临时目录`）、受限子进程运行器 `运行子进程`、
唯一能力调用入口（`_调用包仓库能力`/`_调用治理能力`）。

**为什么抽出来**：这些符号被主文件与多个子模块同时使用，留在主文件会迫使子模块反向 import
主文件（循环导入）。放这里 → 依赖恒为单向。外部注入点不变：主文件仍持有 `系统根` 同名全局
（re-export），`patch.object(门禁, "系统根", …)` 继续生效。

**本文件由 `开发工具/发布门禁/运行发布门禁.py` 按检查项簇**逐字搬移**（成员名一个不改、
判据一处不复制）。依赖方向**单向**：本文件只依赖底座/同族子模块，**不得 import 主文件**
（主文件 import 本文件；反向 import 会成循环）。主文件仍 re-export 本文件全部对外符号，
故 `from 开发工具.发布门禁.运行发布门禁 import <名>` 照旧可用。
"""

from __future__ import annotations

# 本模块自持项目根解析（原文搬移），不导入本包任何符号，故为依赖链末端。
from typing import Any
from pathlib import Path
import atexit
from dataclasses import dataclass, field
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
from 公共契约.运行时 import 平台适配
from 公共契约.运行时 import 进程终止
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
@dataclass
class 门禁项:
    """一项门禁检查。

    `核验状态` 只有两个取值：
    - `已核验`：本项真的取到了证据，`通过` 才可信、才占通过位；
    - `未核验`：本项**没取到任何核验证据**（如定位不到核验对象）。它既不占
      通过位（不得被 `汇总()` 计入「N/N 项强制门禁全部通过」），也不冒充
      失败证据（内容上并没有查出问题），由 `汇总()` 单列一桶。
    """

    名称: str
    通过: bool = False
    详情: str = ""
    强制: bool = True
    核验状态: str = "已核验"

    def 转字典(self) -> dict[str, Any]:
        return {"名称": self.名称, "通过": self.通过, "详情": self.详情,
                "强制": self.强制, "核验状态": self.核验状态}


@dataclass
class 门禁结果:
    """发布门禁结果。"""

    发布状态: str = "未执行"  # 通过/失败/阻断
    门禁项列表: list[门禁项] = field(default_factory=list)
    时间: str = ""

    def 汇总(self) -> str:
        self.时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        强制项 = [项 for 项 in self.门禁项列表 if 项.强制]
        未核验项 = [项 for 项 in 强制项 if 项.核验状态 == "未核验"]
        失败强制项 = [项 for 项 in 强制项 if not 项.通过 and 项.核验状态 != "未核验"]
        通过强制项 = [项 for 项 in 强制项 if 项.通过 and 项.核验状态 != "未核验"]
        if not 强制项:
            self.发布状态 = "阻断"
            return "阻断: 无任何强制门禁项"
        # 未核验是独立状态：它既不是通过，也不是「查出问题」，所以单独成桶报出。
        # 分母仍是全部强制项，但「通过数」只数真正取到证据且通过的项——因此不可能
        # 再出现「N/N 项强制门禁全部通过」把未核验项算进去。
        未核验说明 = (
            f"；另 {len(未核验项)} 项强制门禁未核验（不占通过位）："
            + "、".join(项.名称 for 项 in 未核验项[:5])
        ) if 未核验项 else ""
        if 失败强制项:
            self.发布状态 = "失败"
            return f"失败: {len(失败强制项)} 项强制门禁未通过{未核验说明}"
        if 未核验项:
            self.发布状态 = "阻断"
            return (f"阻断: {len(未核验项)} 项强制门禁未核验（不占通过位）："
                    f"{'、'.join(项.名称 for 项 in 未核验项[:5])}；"
                    f"已核验通过 {len(通过强制项)}/{len(强制项)} 项"
                    f"（分母含未核验项，不得读作全部通过）")
        self.发布状态 = "通过"
        return f"通过: {len(通过强制项)}/{len(强制项)} 项强制门禁全部通过"

    def 打印(self) -> str:
        行列表 = [f"发布门禁结果: {self.发布状态}（{self.时间}）", "=" * 40]
        for 项 in self.门禁项列表:
            if 项.核验状态 == "未核验":
                标记, 后缀 = "◇", "（未核验，不占通过位）"
            else:
                标记, 后缀 = ("✓" if 项.通过 else "✗"), ""
            行列表.append(f"  {标记} {项.名称}: {项.详情}{后缀}")
        return "\n".join(行列表)
def 运行子进程(命令列表: list[str], *, 超时秒: float = 60.0,
            实时输出: bool = False, 环境覆盖: dict[str, str] | None = None) -> tuple[int, str]:
    """运行子进程：输出边读边限额，超时/超限均回收整个进程组。"""
    try:
        进程对象 = subprocess.Popen(
            命令列表, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=False, **平台适配.子进程组启动标志(),
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
        # 回收整个进程组：POSIX SIGKILL / Windows 终止命令的选择由收口层执行，
        # 本处只看「结论是否成功」，不再按 os.name 自己分平台。
        回收结果 = 进程终止.强制结束子进程(进程对象, 宽限秒=0.0, 等待秒=5.0)
        if not 回收结果.成功:
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
        回收结果 = 进程终止.强制结束子进程(进程对象, 宽限秒=0.0, 等待秒=5.0)
        回收说明 = "已回收进程组" if 回收结果.成功 else "进程组未能回收"
        return -1, f"子进程退出确认超时，{回收说明}"
    return 退出码, bytes(输出盒).decode("utf-8", "replace")
_包仓库后端: Any = None


def _调用包仓库能力(能力id: str, 参数: dict[str, Any]) -> Any:
    """经完整装配调用 平台控制面.包仓库 的公开能力（唯一能力入口）。

    `开发工具` 是进程外调用方：惰性装配钩子只装 支持库/模块库，取不到
    `平台控制面` 的能力，故这里按唯一可用口径自建装配并按**惰性单例**复用
    （约 1.5 秒，不塞进 import 期）。返回统一结果信封（成功/值/错误）。
    """
    global _包仓库后端
    if _包仓库后端 is None:
        from 后端核心.后端核心 import 后端核心
        实例 = 后端核心(系统根)
        启动结果 = 实例.启动()
        if not 启动结果.成功:
            raise RuntimeError(
                f"平台控制面.包仓库 能力装配失败: {启动结果.错误说明}")
        _包仓库后端 = 实例
    return _包仓库后端.调用(能力id, 参数)
_治理后端: Any = None


def _调用治理能力(能力id: str, 参数: dict[str, Any]) -> Any:
    """经完整装配调用 平台控制面 任一正式包的公开能力（唯一能力调用入口）。

    `开发工具` 是进程外调用方：惰性装配钩子只装 支持库/模块库，取不到
    `平台控制面` 的能力，故这里按唯一可用口径自建装配并按**惰性单例**复用
    （约 1.5 秒，不塞进 import 期）。返回统一结果信封（成功/值/错误），
    不做任何兜底降级：装配失败即 RuntimeError，能力失败即失败信封原样外传。
    """
    global _治理后端
    if _治理后端 is None:
        from 后端核心.后端核心 import 后端核心
        实例 = 后端核心(系统根)
        启动结果 = 实例.启动()
        if not 启动结果.成功:
            raise RuntimeError(
                f"平台控制面 能力装配失败: {启动结果.错误说明}")
        _治理后端 = 实例
    return _治理后端.调用(能力id, 参数)
def 门禁临时目录() -> str:
    import tempfile
    return tempfile.gettempdir()
