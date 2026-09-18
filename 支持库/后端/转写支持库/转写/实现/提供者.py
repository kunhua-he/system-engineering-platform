"""MLX Whisper 转写独立提供者：配置驱动 + 受管子进程执行。
未配置模型 → 如实返回 未配置模型；模型目录缺失 → 模型缺失；绝不伪装可用、
绝不模拟转写成功。mlx_whisper 只在隔离子进程加载；转写覆盖 超时/取消/进程组回收/输出上限。

**管道读取不做平台判断**（华哥 2026-09-16 裁决：底座做完整跨平台）：stdout/stderr 由
后台读线程用 `公共契约/运行时/有界IO.受限读取` 直读内核并排空+限界，调用方在
`threading.Event` 上等 EOF/超限 —— **不再用 `select` 轮询管道 fd**（Windows 的 `select`
只接受 socket，轮询管道 fd 必然报错，旧实现把该异常吞成 `break`，等于在 Windows 上
永远收不到子进程输出、直接按「无效响应」返回）。范式与本仓
`运行核心/加载器/提供者隔离/独立进程.py` 同源（同一 `受限读取` 唯一实现）。"""

from __future__ import annotations

import json, os, subprocess, sys, threading, time
from pathlib import Path
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 进程终止, 有界IO

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 300.0
默认最大输出字节 = 16 * 1024 * 1024
环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="MLXWhisper提供者", 可重试=可重试)


def 读取模型配置(配置: dict | None = None) -> dict[str, str]:
    """读取模型配置：优先配置对象，其次环境变量（非字典一律视为空配置）。"""
    配置 = 配置 if isinstance(配置, dict) else {}
    return {"模型路径": str(配置.get("模型路径") or os.environ.get(环境变量模型路径) or "").strip(),
            "模型名": str(配置.get("模型名") or os.environ.get(环境变量模型名) or "").strip()}


def _校验配置类型(配置: Any) -> 结果 | None:
    """配置必须是 字典 或 None（跨宿主只允许可序列化数据）。"""
    if 配置 is not None and not isinstance(配置, dict):
        return _失败("参数不合法", f"配置必须是字典或 None，收到 {type(配置).__name__}")
    return None


def _检查配置(配置: dict | None) -> tuple[结果 | None, str, str]:
    """主进程判定 未配置模型/模型缺失/供应链校验；其余交给子进程。"""
    模型路径, 模型名 = 读取模型配置(配置).values()
    if not 模型路径 and not 模型名:
        return _失败("未配置模型", "未配置 MLX Whisper 模型（模型路径与模型名均为空）"), "", ""
    if 模型路径 and not Path(模型路径).is_dir():
        return _失败("模型缺失", f"模型目录不存在: {模型路径}"), 模型路径, 模型名
    供应链错误 = _供应链守卫(模型路径)
    if 供应链错误 is not None:
        return 供应链错误, 模型路径, 模型名
    return None, 模型路径, 模型名


def _供应链守卫(模型路径: str) -> 结果 | None:
    """语音权重目录的供应链校验（B9）：判定与模型连接器**同一份实现**，不另写第二套。

    只对「配置了模型路径」的情况生效；模型名走 HuggingFace 在线仓库时不适用
    （那不是本机二进制制品，无法固定哈希）。判定语义：
      目录内已登记制品 → 逐条校验（存在性 → 字节数 → sha256），任一不符即拒绝转写；
      目录不在受管模型根内且未登记 → 放行并如实标注（调用方自备路径/测试临时目录）；
      清单读不成 → fail-closed 拒绝，绝不「校验不了就放行」。

    取用方式：经 `支持库.后端.大语言模型支持库.模型连接器` **包级公开入口**（不是它的
    `实现/`，那会被依赖防火墙判「跨包禁止导入 实现/ 目录」）；惰性导入，避免装载期耦合。
    """
    if not 模型路径:
        return None
    try:
        from 支持库.后端.大语言模型支持库.模型连接器 import 校验模型目录 as _校验模型目录
        判定 = _校验模型目录(模型路径)
    except Exception as 错误:  # 校验层自身异常同样 fail-closed
        return _失败("文件摘要不符", f"语音权重供应链校验执行失败: {错误}")
    if not 判定.get("通过"):
        return 结果.失败(str(判定.get("错误码") or "文件摘要不符"),
                          str(判定.get("错误说明") or "语音权重供应链校验未通过"),
                          来源="MLXWhisper提供者", 可重试=False,
                          详情={k: v for k, v in 判定.items() if k != "错误说明"})
    return None


def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    return subprocess.Popen([sys.executable, str(子进程入口路径)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(包目录.parents[3]), **平台适配.子进程组启动标志(), env=dict(os.environ))


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """终止进程组（终止→宽限→强杀→复查）：唯一实现在 公共契约.运行时.进程终止。

    本处不再持有任何平台判断或信号实现；保留同签名同名的薄委托，是因为
    既有测试（测试中心/支持库/测试_MLXWhisper提供者.py）直接调用本名并以 patch.object 打桩。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)



def _关闭流(进程: subprocess.Popen) -> None:
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        try:
            if 流 is not None:
                流.close()
        except (OSError, ValueError):
            pass


class _管道收集器:
    """子进程 stdout/stderr 的**唯一后台读者**：阻塞式 `受限读取` + 交接缓冲。

    为什么不用 `select` 轮询：Windows 的 `select` 只接受 socket，对管道 fd 直接抛
    `OSError`；旧实现把该异常吞成 `break`，等于在 Windows 上永远收不到输出。这里
    与 `运行核心/加载器/提供者隔离/独立进程.py` 同一范式（同一 `有界IO.受限读取`
    唯一实现）：后台线程读内核 → 回调累积到 `_缓冲` → 事件通知调用方。

    超限后**继续排空但不再累积**（防管道回压），EOF/超限置事件供等待侧判据；
    轮询退化为「等事件 + 切片超时判取消/超时」，不再有平台判断。
    """

    __slots__ = ("_缓冲", "_事件", "_条件", "_结束", "_超限", "_流", "_上限字节")

    def __init__(self, 流: Any, 上限字节: int = 默认最大输出字节) -> None:
        self._缓冲 = bytearray()
        self._事件 = threading.Event()   # 有新数据 / EOF / 超限时唤醒等待侧
        self._条件 = threading.Condition()
        self._结束 = False
        self._超限 = False
        self._流 = 流
        # 上限必须来自**调用方**（`执行任务` 的 最大输出字节）：写死默认值会在调用方
        # 放宽上限时把多出来的字节静默截断。
        self._上限字节 = max(1, int(上限字节))

    def 启动(self) -> threading.Thread:
        线程 = threading.Thread(target=self._消费, daemon=True, name="MLXWhisper-管道收集")
        线程.start()
        return 线程

    def _消费(self) -> None:
        try:
            有界IO.受限读取(self._流, 上限字节=self._上限字节, 数据回调=self._收块,
                          超限回调=self._置超限)
        except (OSError, ValueError):
            pass
        finally:
            with self._条件:
                self._结束 = True
                self._条件.notify_all()
            self._事件.set()

    def _收块(self, 块: bytes) -> None:
        with self._条件:
            self._缓冲.extend(块)
            self._条件.notify_all()
        self._事件.set()

    def _置超限(self) -> None:
        with self._条件:
            self._超限 = True
            self._条件.notify_all()
        self._事件.set()

    def 取(self) -> tuple[bytes, bool, bool]:
        """非阻塞取走当前已累积字节，返回（片段、是否超限、是否已结束）。

        取走后清空缓冲：与旧实现「read 后从管道搬走」同语义 —— 字节只能被搬走一次。
        """
        with self._条件:
            片段 = bytes(self._缓冲)
            self._缓冲.clear()
            超限, 结束 = self._超限, self._结束
        if not 片段:
            self._事件.clear()
        return 片段, 超限, 结束

    def 等(self, 超时秒: float) -> None:
        """等新数据 / EOF / 超限，最多 `超时秒`（超时正常返回，由调用方判取消与总超时）。"""
        self._事件.wait(max(0.01, 超时秒))


def 执行任务(请求: dict[str, Any], 超时秒: float = 默认超时秒,
            取消判断: Callable[[], bool] | None = None,
            最大输出字节: int = 默认最大输出字节) -> 结果:
    """受管子进程执行：超时/取消/输出上限/进程组回收/崩溃映射稳定错误码。

    stdout/stderr 由后台线程经 `_管道收集器` 唯一读取，主循环只等事件并按
    切片超时判取消/超时 —— **本函数不含任何平台判断、不含 `select`**。
    """
    try:
        进程 = _启动子进程()
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动 MLX Whisper 隔离子进程: {错误}", 可重试=True)
    输出 = bytearray()
    错误输出 = bytearray()
    收集器 = []
    for 流, 容器 in ((进程.stdout, 输出), (进程.stderr, 错误输出)):
        if 流 is not None:
            收集器.append((_管道收集器(流, 最大输出字节), 容器))
    try:
        for 收集, _容器 in 收集器:
            收集.启动()
    except (OSError, ValueError, RuntimeError):
        pass
    try:
        try:
            进程.stdin.write((json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"))
            进程.stdin.close()
        except (OSError, ValueError):
            pass
        开始 = time.monotonic()
        while True:
            if 取消判断 is not None and 取消判断():
                _终止进程组(进程)
                return _失败("取消", "转写已被调用方取消")
            if time.monotonic() - 开始 >= 超时秒:
                _终止进程组(进程)
                return _失败("超时", f"MLX Whisper 隔离子进程执行超过 {超时秒} 秒", 可重试=True)
            全部结束 = True
            for 收集, 容器 in 收集器:
                片段, _超限, 结束 = 收集.取()
                容器.extend(片段)
                if len(容器) > 最大输出字节:
                    _终止进程组(进程)
                    return _失败("超出限制", f"MLX Whisper 隔离子进程输出超过上限 {最大输出字节} 字节")
                全部结束 = 全部结束 and 结束
            if 进程.poll() is not None and 全部结束:
                break
            for 收集, _容器 in 收集器:
                收集.等(0.2)
    finally:
        if 进程.poll() is None:
            _终止进程组(进程)
        _关闭流(进程)
    if 进程.returncode:
        return _失败("进程崩溃", f"MLX Whisper 隔离子进程异常退出（退出码 {进程.returncode}）", 可重试=True)
    try:
        响应 = json.loads(输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("进程崩溃", "MLX Whisper 隔离子进程返回了无效响应", 可重试=True)
    if not 响应.get("成功"):
        return 结果.失败(str(响应.get("错误码") or "进程崩溃"),
                          str(响应.get("错误说明") or "子进程执行失败"), 来源="MLXWhisper提供者",
                          可重试=str(响应.get("错误码")) in ("提供者不可用", "超时", "进程崩溃", "模型缺失"),
                          详情={"值": 响应.get("值")})
    return 结果.成功结果(响应.get("值"))


def 检查转写可用性(超时秒: float = 默认超时秒, 配置: dict | None = None) -> 结果:
    """检查转写可用性：未配置模型 → 未配置模型；模型缺失 → 模型缺失。"""
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    return 错误 or 执行任务({"操作": "检查可用性", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 获取模型版本(超时秒: float = 默认超时秒, 配置: dict | None = None) -> 结果:
    """获取模型与库版本：未配置模型 → 未配置模型。"""
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    return 错误 or 执行任务({"操作": "获取模型版本", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 转写音频文件(文件路径: str, 超时秒: float = 默认超时秒,
                取消判断: Callable[[], bool] | None = None,
                配置: dict | None = None, 附加术语: str = "",
                返回分段: bool = False) -> 结果:
    """转写音频文件：受管子进程；超时/取消/进程组回收/输出上限。

    返回分段 为真时值里额外带 分段 指标（供疑难标记/复核使用）；默认不返回，保持旧行为。
    """
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败("参数不合法", "文件路径必须为非空文本")
    if not isinstance(返回分段, bool):
        return _失败("参数不合法", "返回分段 必须为逻辑型")
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    if 错误 or not Path(文件路径).is_file():
        return 错误 or _失败("文件不存在", f"音频文件不存在: {文件路径}")
    请求: dict[str, object] = {"操作": "转写音频", "文件路径": 文件路径, "模型路径": 模型路径, "模型名": 模型名}
    if 附加术语:
        if not isinstance(附加术语, str):
            return _失败("参数不合法", "附加术语必须为文本")
        请求["附加术语"] = 附加术语
    if 返回分段:
        请求["返回分段"] = True
    return 执行任务(请求, 超时秒=超时秒, 取消判断=取消判断)


def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    for 进程 in 进程列表:
        if 进程.poll() is None:
            _终止进程组(进程, 宽限秒=超时秒)
