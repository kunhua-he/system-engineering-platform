"""转写后端选择（**同一份实现 + 模式变量**，哲学第 8 条②）：Apple Silicon → mlx；其余 → faster-whisper。"""

from __future__ import annotations

from 公共契约.运行时.平台适配.硬件画像 import 是否AppleSilicon


# ── 转写后端选择（**同一份实现 + 模式变量**，哲学第 8 条②）──────────────
#
# 口径与依据（2026-09-19）：Apple Silicon（macOS + arm64）上 `mlx-whisper` 的 MLX
# 运行时走 **Metal**，是平台专有能力；其余平台（Windows / Linux）**结构性不可用** ——
# 阿里云 Linux x86_64 / Python 3.14 实测：`pip install mlx-whisper==0.4.3` 能把整个
# 闭包装完（含 torch 526MB），但 `import mlx.core` 恒报
# `ImportError: libmlx.so: cannot open shared object file: No such file or directory`
# （wheel 内只有 1 个 `.so`：`mlx/core.cpython-314-x86_64-linux-gnu.so`，
# **不存在 libmlx.so 文件**）⇒ 不是装依赖能解决的问题，只能在**后端**上分叉。
# 实测反向：`faster-whisper==1.2.1` 在 Linux x86_64 + Python 3.14 上可装可用
# （`ctranslate2` 4.8.2，不依赖 Metal）。
#
# **这是「同一份实现 + 模式变量」，不是第二条腿**（第 1.2① / 2.4① 内部第二执行腿：
# 禁止）：转写链路仍然只有一条 —— `支持库/后端/转写支持库/转写` 与
# `支持库/适配层/MLXWhisper提供者` 各一处子进程解析，两份都按本模块的 `转写后端()`
# 选后端；后端调用差异**吸收在子进程解析内部**，对外返回结构
# （`值.文本` / `值.语言` / `值.模型名` / `值.分段`）与全部错误码**逐字不变**，
# 调用方零改动。平台差异只在本模块判断（跨平台收口铁律：调用点不许写 `sys.platform`）。

#: 转写后端标识表：识别到的后端标识 → 该后端的适用平台口径（**别名/反查名**，供机器校验）。
转写后端标识表 = {
    "mlx": "Apple Silicon（macOS + arm64）专有：mlx-whisper 的 MLX 运行时走 Metal",
    "faster-whisper": "Windows / Linux（含非 arm64 的 macOS）：ctranslate2 后端，不依赖 Metal",
}

#: 后端标识 → 子进程内要加载的第三方模块名（**反查表**，供机器校验与实现侧取值）。
转写后端库名表 = {
    "mlx": "mlx_whisper",
    "faster-whisper": "faster_whisper",
}

#: 后端标识字面量（避免实现侧散写字符串；标识值本身是本模块对外契约，不得改字）
转写后端标识_MLX = "mlx"
转写后端标识_FASTER_WHISPER = "faster-whisper"


def 转写后端() -> str:
    """返回当前平台的转写后端标识：Apple Silicon → ``mlx``；其余平台 → ``faster-whisper``。

    判定依据（**全平台唯一一处**，调用点不得自己写 `sys.platform`）：
    `是否AppleSilicon()` 为真 → ``mlx``（用 `AppleSilicon架构表`，**不是**准入矩阵
    `正式支持矩阵`——MLX 只认 Apple Silicon，与「该平台有没有验收证据」是两回事）；
    其余一律 ``faster-whisper``。

    **为什么不是「不认识就抛异常」**：本函数是**后端选择器**，不是环境准入判据 ——
    准入仍由 `校验支持范围()` 负责（fail-closed，按 `正式支持矩阵` 放行）。这里回答的是
    「该加载哪个后端」，在 Windows / Linux 上给出 ``faster-whisper`` 是**正确结论**，
    不是静默降级（第 3.2 条）：真正的可用性由两件事实决定，本函数都不假装知道 ——
    ① 依赖锁按 `适用平台` 过滤后该后端的依赖是否装得上；② 子进程内真实 `import`
    是否成功。库装载不上就返回 `提供者不可用`，**绝不伪装可用、绝不模拟转写成功**。

    与 `平台表` 的对照：``macOS`` 但非 arm64（Intel Mac）返回 ``faster-whisper``
    —— MLX 需要 Apple Silicon，Intel Mac 上结构性不可用；故本函数与
    「Apple Silicon → mlx」严格互补，不留无主区间。

    **诚实标注：Windows / Linux 分支未经真机实测**（开发机为 macOS，仅做
    monkeypatch 分支选择验证；见模块文件头与 README《当前支持矩阵》）。
    """
    if 是否AppleSilicon():
        return 转写后端标识_MLX
    return 转写后端标识_FASTER_WHISPER


def 转写后端库名(后端标识: str = "") -> str:
    """把后端标识翻成子进程内要 ``import`` 的第三方模块名；**不认识的标识返回空串**。

    省略 `后端标识` 时取当前平台的 `转写后端()`。反查表 `转写后端库名表` 是唯一
    定义处，本函数是它的唯一取值出口（实现侧一处取值，不散写模块名字符串）。

    **不认识的标识返回空串**（fail-closed，不猜）：调用方据此明确报 `提供者不可用`；
    猜一个模块名去 import 会让错误码从「提供者不可用」漂成别的语义，违反第 3.2 条。
    """
    return 转写后端库名表.get((后端标识 or 转写后端()).strip(), "")
