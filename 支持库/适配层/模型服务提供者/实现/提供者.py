"""模型服务提供者 的能力实现：`模型服务.检查提供者`（本地模型服务运行栈可用性探针）。

**探针口径（为什么只定位不导入）**：

1. 逐个 `importlib.util.find_spec` **定位** torch / transformers / fastapi / uvicorn，
   **不执行导入** —— 这四个都带原生扩展（torch 尤其），主进程导入会推翻
   「原生扩展不在主进程加载」的既有结论，也会把模型服务的依赖强加给底座主进程；
2. 版本取 `importlib.metadata.version(发行包)`（读发行包元数据，不执行模块代码）；
3. 任一缺件 → `结果.失败("提供者不可用")` + 缺件名单，**不伪装成功**（fail-closed）。

**本能力不启动服务、不加载权重**：服务进程由 `模型连接器` 的本地启动链按路径拉起
（`支持库/适配层/模型服务.py --model-path … --model-type … --port …`），
本能力只回答「这台机器装没装齐运行栈、版本各是多少」。
"""

from __future__ import annotations

import importlib.metadata as _发行包元数据
import importlib.util as _导入工具

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.基础类型.结果类型 import 结果

#: 运行栈清单（模块名 → 发行包名）：本提供者 `依赖锁.json` 里锁的就是这四项。
运行栈清单 = (
    ("torch", "torch"),
    ("transformers", "transformers"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
)

#: 可重试错误码：提供者不可用（运行栈缺件）属环境态，装齐即可重试。
可重试错误码 = ("提供者不可用",)


def _失败(错误码: str, 消息: str) -> 结果:
    """统一失败信封（错误码必须是网关公开错误码状态映射里的码）。"""
    return 结果.失败(错误码, 消息, 来源="模型服务提供者",
                    可重试=错误码 in 可重试错误码)


def 检查提供者() -> 结果:
    """检查本机本地模型服务运行栈是否齐备（真实探针：定位 + 读发行包版本）。

    返回：结果型；成功时 值 = {可用, 探针, 依赖[{名称, 发行包, 版本}], 缺失, 说明}；
    任一缺件 → 失败("提供者不可用") + 缺件名单。
    """
    依赖列表: list[dict] = []
    缺失列表: list[str] = []
    for 模块名, 发行包 in 运行栈清单:
        try:
            定位 = _导入工具.find_spec(模块名)
        except (ImportError, ValueError):
            定位 = None
        if 定位 is None:
            缺失列表.append(模块名)
            continue
        try:
            版本 = _发行包元数据.version(发行包)
        except Exception:  # 发行包元数据读不到不影响「在位」判定，如实留空
            版本 = ""
        依赖列表.append({"名称": 模块名, "发行包": 发行包, "版本": 版本})
    if 缺失列表:
        return _失败("提供者不可用",
                     f"本地模型服务运行栈缺件: {'、'.join(缺失列表)}")
    return 结果.成功结果({
        "可用": 真,
        "探针": "本地模型服务运行栈定位（不导入原生扩展）",
        "依赖": 依赖列表,
        "缺失": [],
        "说明": f"{len(依赖列表)} 项运行栈齐备（torch/transformers/fastapi/uvicorn）",
    })
