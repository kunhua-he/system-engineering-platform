"""子进程解析逻辑：在隔离子进程内执行语音转写操作（**跨平台双后端，一份实现 + 模式变量**）。

后端选择（**唯一判定处**：`公共契约/运行时/平台适配.转写后端()`；本文件不写任何
平台判断，遵守跨平台收口铁律）：

- Apple Silicon（macOS + arm64）→ ``mlx``：加载 ``mlx_whisper``，
  ``mlx_whisper.transcribe(path_or_hf_repo=…)`` 返回 **dict**
  （带 ``text`` / ``language`` / ``segments``）。
- 其余平台（Windows / Linux，含非 arm64 的 macOS）→ ``faster-whisper``：加载
  ``faster_whisper``，``WhisperModel(...).transcribe(...)`` 返回
  **(segments 生成器, info)** 二元组（文本在 ``info.text`` / ``info.language``，
  分段是**惰性生成器**，字段在对象属性上而非 dict 键）。

**为什么是「同一份实现 + 模式变量」而不是第二条腿**（哲学第 8 条②；第 1.2① /
2.4① 内部第二执行腿禁止）：转写链路只有一条 —— 平台判定在收口层一处，后端差异
**全部吸收在本文件内部**，对外返回结构（``值.文本`` / ``值.语言`` / ``值.模型名`` /
``值.分段``）与全部错误码**逐字不变**，调用方零改动。

本模块只在子进程中导入；这里才允许加载第三方转写库，崩溃不影响主进程。
未配置模型/模型缺失如实返回对应错误码，绝不伪装可用或模拟转写成功。
成功返回**裸值**字典（`公共契约/运行时/子进程协议.组装应答` 的「其余按成功转信封」一支
直接把它当 `值`；不再自带 `{"值": ...}` 包一层 —— 那会多包一层信封）；
失败返回 `{"错误码": ..., "错误说明": ..., "值": ...}`（按「含错误码的字典」保留 `值`）。

**诚实标注：Windows / Linux（faster-whisper 支）未经真机实测**（开发机为 macOS，
只做过 monkeypatch 分支选择验证）。真机证据由阿里云 Linux 与 GitHub Actions
Windows runner 补；在此之前**不许把「代码写好了」当成「Windows / Linux 能跑了」**。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from 公共契约.运行时 import 平台适配

禁用库环境变量名 = "MLXWhisper提供者_禁用库"
_库模块 = None  # 子进程内惰性加载；主进程绝不加载
_后端标识 = ""  # 最近一次 `_加载库` 选定的后端标识（供错误说明如实报出后端）

#: 本实例被禁用时必须报「提供者不可用」的库名前缀（**对两个后端都成立**，与后端选择无关）：
#: 旧版禁用写法 ``MLXWhisper提供者_禁用库=mlx_whisper`` 必须继续有效（既有测试与说明文档
#: 都按这个口径写）；``faster_whisper`` 与更通用的 ``转写库`` 一并接受，便于在
#: Windows/Linux 上做同样的依赖注入验证。
禁用库可识别名表 = ("mlx_whisper", "faster_whisper", "转写库")


def 当前转写后端() -> str:
    """本子进程应使用的转写后端标识（Apple Silicon → ``mlx``；其余 → ``faster-whisper``）。

    判定**只委托收口层** `平台适配.转写后端()`：本文件不做平台判断
    （跨平台收口铁律：平台差异只允许在 `平台适配.py` 与 `进程终止.py` 两处判断）。
    """
    return 平台适配.转写后端()


def _加载库(禁用库表: set[str]) -> Any:
    """按平台选后端并加载对应第三方库；禁用或缺失返回 None（提供者不可用）。

    选后端：`公共契约.运行时.平台适配.转写后端库名()`（本模块不写平台判断）。
    两个后端**都是惰性加载**：主进程/装配期不加载任何转写库。
    """
    global _库模块, _后端标识
    _后端标识 = 当前转写后端()
    if any(名 in 禁用库表 for 名 in 禁用库可识别名表):
        _库模块 = None
        return None
    # **必须是字面量 `import`（不许 `__import__(模块名)`）**：`开发工具/依赖派生/生成依赖分两段.py`
    # 与 `运行核心/依赖防火墙.py` 都按 **AST** 收第三方导入现场；动态导入会让「锁里声明了
    # 第三方、实现里却找不到 import 现场」判红（实测：改成动态导入后该门禁立刻报
    # 「mlx-whisper 锁内为第三方却无 import 现场」并把它误判成环境依赖）。
    # 两个分支各自写死模块名，平台差异仍只来自收口层的 `转写后端()`。
    try:
        if _后端标识 == 平台适配.转写后端标识_MLX:
            import mlx_whisper
            _库模块 = mlx_whisper
        elif _后端标识 == 平台适配.转写后端标识_FASTER_WHISPER:
            import faster_whisper
            _库模块 = faster_whisper
        else:
            _库模块 = None
    except Exception:
        _库模块 = None
    return _库模块


def 初始化(禁用库表: set[str]) -> bool:
    return _加载库(禁用库表) is not None


def _不可用() -> dict[str, Any]:
    """库不可用 → `提供者不可用`（如实报出**选中的后端**与模块名，便于换平台排查）。"""
    模块名 = 平台适配.转写后端库名(_后端标识 or 当前转写后端())
    后端 = _后端标识 or 当前转写后端()
    return {"错误码": "提供者不可用",
            "错误说明": f"{模块名} 库不可用（当前平台转写后端: {后端}），无法执行转写",
            "可重试": True}


def _未配置() -> dict[str, Any]:
    return {"错误码": "未配置模型", "错误说明": "未配置 MLX Whisper 模型（模型路径与模型名均为空）"}


def _模型缺失(模型路径: str) -> dict[str, Any]:
    return {"错误码": "模型缺失", "错误说明": f"模型目录不存在: {模型路径}"}


def _检查模型(模型路径: str, 模型名: str) -> tuple[str, str, dict | None]:
    模型路径 = (模型路径 or "").strip()
    模型名 = (模型名 or "").strip()
    if not 模型路径 and not 模型名:
        return 模型路径, 模型名, _未配置()
    if 模型路径 and not Path(模型路径).is_dir():
        return 模型路径, 模型名, _模型缺失(模型路径)
    return 模型路径, 模型名, None


def 检查可用性(模型路径: str, 模型名: str) -> dict[str, Any]:
    """转写可用性探针：只查库版本与模型配置，不加载模型权重。"""
    if _库模块 is None:
        return _不可用()
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    return {
        "可用": True,
        "模型名": 模型名 or 模型路径,
        "模型版本": str(getattr(_库模块, "__version__", "未知")),
    }


def 获取模型版本(模型路径: str, 模型名: str) -> dict[str, Any]:
    """获取模型与库版本；未配置 → 未配置模型。"""
    if _库模块 is None:
        return _不可用()
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    return {
        "模型名": 模型名 or 模型路径,
        "模型版本": str(getattr(_库模块, "__version__", "未知")),
    }


def _取字段(段: Any, 键名: str, 默认: Any = None) -> Any:
    """从**分段**里取一个字段，兼容两种后端的表达形态。

    ``mlx_whisper`` 的分段是 **dict**（``段["start"]``）；``faster_whisper`` 的分段是
    ``Segment`` **命名元组/对象**（``段.start``）。本次改动只做「取值方式」的适配，
    输出的键名与口径**逐字沿用改动前**（`序号`/`开始秒`/… 一个都不改）。
    """
    if isinstance(段, dict):
        值 = 段.get(键名, 默认)
    else:
        值 = getattr(段, 键名, 默认)
    return 默认 if 值 is None else 值


def _物化分段(原始分段: Any) -> Any:
    """把惰性分段迭代器物化成 list（已是序列则原样返回；物化不了返回 None）。

    ``faster_whisper`` 的 ``transcribe`` 返回的分段是**惰性生成器**：不物化就随
    ``info`` 一起被丢弃，`分段` 恒为空 —— 那是「看起来支持、实际拿不到指标」的假支持。
    mlx 返回的本来就是 list，此处是零操作。
    """
    if 原始分段 is None:
        return None
    if isinstance(原始分段, (list, tuple)):
        return 原始分段
    try:
        return list(原始分段)
    except TypeError:
        return None


def _轻量分段(原始分段: Any) -> list[dict[str, Any]]:
    """把转写分段压成疑难标记所需字段（丢弃 token 等大字段，控制子进程输出体积）。

    **键名与口径与改动前逐字一致**：`序号`/`开始秒`/`结束秒`/`文本`/
    `平均对数概率`/`压缩比`/`无语音概率`。两个后端的分段对象形态不同（dict 与命名
    元组），差异由 `_取字段` 吸收；进入本函数前先经 `_物化分段` 统一成 list。
    """
    分段表: list[dict[str, Any]] = []
    原始分段 = _物化分段(原始分段)
    if not isinstance(原始分段, (list, tuple)):
        return 分段表
    for 序号, 段 in enumerate(原始分段, start=1):
        if 段 is None:
            continue
        try:
            分段表.append({
                "序号": 序号,
                "开始秒": round(float(_取字段(段, "start", 0.0) or 0.0), 3),
                "结束秒": round(float(_取字段(段, "end", 0.0) or 0.0), 3),
                "文本": str(_取字段(段, "text", "") or "").strip(),
                "平均对数概率": round(float(_取字段(段, "avg_logprob", 0.0) or 0.0), 4),
                "压缩比": round(float(_取字段(段, "compression_ratio", 0.0) or 0.0), 4),
                "无语音概率": round(float(_取字段(段, "no_speech_prob", 0.0) or 0.0), 4),
            })
        except (TypeError, ValueError):
            continue
    return 分段表


def _转写_mlx(库: Any, 文件: str, 目标: str, 附加术语: str) -> tuple[str, str, Any]:
    """``mlx_whisper`` 调用适配：``transcribe(path_or_hf_repo=…)`` 返回 **dict**。

    返回 ``(文本, 语言, 原始分段)``；文本为空即由调用方判「转写失败」。
    """
    参数: dict[str, Any] = {"path_or_hf_repo": 目标}
    if 附加术语:
        参数["initial_prompt"] = 附加术语
    结果 = 库.transcribe(文件, **参数)
    if not isinstance(结果, dict):
        return "", "", None
    return str(结果.get("text") or ""), str(结果.get("language") or ""), 结果.get("segments")


def _转写_faster_whisper(库: Any, 文件: str, 目标: str, 附加术语: str) -> tuple[str, str, Any]:
    """``faster_whisper`` 调用适配：``WhisperModel(...).transcribe(...)`` 返回 **(生成器, info)**。

    **两个后端的调用差异吸收在这里**：

    - 模型构造：``WhisperModel(目标)``（目标＝本地模型目录或模型名/hf 仓库名）；
    - ``initial_prompt`` 语义对齐 mlx 的 ``initial_prompt``（同为附加领域术语提示）；
    - 文本在 ``info.text`` / 语言在 ``info.language``（mlx 是 dict 的 ``text``/``language``）；
    - **分段是惰性生成器**，交付前由 `_轻量分段`→`_物化分段` 统一物化，
      与 mlx 的 list 分段进入**同一段解析逻辑**（键名口径逐字一致）。

    返回 ``(文本, 语言, 原始分段)``；文本为空即由调用方判「转写失败」。
    """
    模型 = 库.WhisperModel(目标)
    参数: dict[str, Any] = {}
    if 附加术语:
        参数["initial_prompt"] = 附加术语
    段生成器, info = 模型.transcribe(文件, **参数)
    文本 = str(getattr(info, "text", "") or "")
    语言 = str(getattr(info, "language", "") or "")
    return 文本, 语言, 段生成器


def 转写音频(文件路径: str, 模型路径: str, 模型名: str, 附加术语: str = "",
             返回分段: bool = False) -> dict[str, Any]:
    """转写音频文件；失败逐类映射稳定错误码，不伪装成功。

    按平台选后端并**在内部吸收两个后端的调用差异**；对外返回结构
    （``值.文本``/``值.语言``/``值.模型名``，``返回分段`` 为真时另带 ``值.分段``）
    与改动前逐字一致，调用方零改动。

    返回分段 为真时额外返回 分段 指标（平均对数概率/压缩比/无语音概率），供疑难标记使用。
    """
    库 = _库模块
    if 库 is None:
        return _不可用()
    文件 = Path(文件路径)
    if not 文件.is_file():
        return {"错误码": "文件不存在", "错误说明": f"音频文件不存在: {文件路径}"}
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    目标 = 模型路径 or 模型名
    后端 = _后端标识 or 当前转写后端()
    try:
        if 后端 == 平台适配.转写后端标识_MLX:
            文本, 语言, 原始分段 = _转写_mlx(库, str(文件), 目标, 附加术语)
        elif 后端 == 平台适配.转写后端标识_FASTER_WHISPER:
            文本, 语言, 原始分段 = _转写_faster_whisper(库, str(文件), 目标, 附加术语)
        else:
            # 不认识的标识（收口层与实现侧口径分叉）→ 如实报不可用，不猜后端。
            return _不可用()
    except Exception as 错误对象:
        return {"错误码": "转写失败", "错误说明": f"转写失败: {错误对象}"}
    if not str(文本 or "").strip():
        return {"错误码": "转写失败", "错误说明": "转写未返回文本"}
    值: dict[str, Any] = {
        "文本": str(文本).strip(),
        "语言": str(语言 or ""),
        "模型名": 模型名 or 模型路径,
    }
    if 返回分段:
        值["分段"] = _轻量分段(原始分段)
    return 值
