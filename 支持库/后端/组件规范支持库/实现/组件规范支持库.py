"""组件规范支持库 公开能力实现：把内部原子实现包装成对外能力（统一结果信封）。

内部实现（同包 实现/ 目录，禁止跨包导入）：
- `实现/完整性摘要.py`：文件清单 sha256 摘要唯一生成器与校验器（含扫描正式包/迁移旧格式）；
- `实现/组件规范.py`：九要素组件规范校验、生成并写入 完整性摘要.json；
- `实现/模块模板生成器.py`：模块模板（含测试骨架）生成；
- `实现/支持库模板生成器.py` / `实现/技能模板生成器.py`：支持库/技能包脚手架生成；
- `实现/说明书生成器.py`：由包内数据源生成 说明/使用说明.md；
- `实现/核心快照模板.py`：核心快照清单模板生成与校验。

能力函数名必须等于能力id 末段（失败语义按函数名提取错误码），故本文件只做
参数归一 + 统一失败码映射，不复制任何第二套算法。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.组件规范支持库.实现.完整性摘要 import (
    是否应当收录,
)
from 支持库.后端.组件规范支持库.实现.完整性摘要 import (
    生成完整性摘要 as _生成文件清单摘要,
)
from 支持库.后端.组件规范支持库.实现.完整性摘要 import (
    校验完整性摘要 as _校验文件清单摘要,
)
from 支持库.后端.组件规范支持库.实现.模块模板生成器 import (
    生成模块模板 as _生成模块模板,
)

来源 = "组件规范支持库"


def _包目录(参数: Any) -> Path | None:
    """归一 包目录 参数：空/非文本返回 None（由调用方如实报 参数不合法）。"""
    if isinstance(参数, Path):
        return 参数
    if isinstance(参数, str) and 参数.strip():
        return Path(参数)
    return None


def _包声明取值(包目录: Path, 键名: str) -> str:
    """从 包声明.json 读取指定键；不可读或缺失返回空串（由调用方如实报错）。"""
    声明路径 = 包目录 / "包声明.json"
    if not 声明路径.is_file():
        return ""
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ""
    if not isinstance(声明, dict):
        return ""
    值 = 声明.get(键名)
    return 值 if isinstance(值, str) else ""


def 生成完整性摘要(包目录: Any = None, 包id: Any = None, 版本: Any = None) -> 结果:
    """生成完整性摘要（唯一生成器口径：路径有序、与时间无关；只计算不写盘）。"""
    目标 = _包目录(包目录)
    if 目标 is None:
        return 结果.失败("参数不合法", f"包目录 必须是非空路径文本: {包目录!r}", 来源=来源)
    if not 目标.is_dir():
        return 结果.失败("包目录不存在", f"包目录不是目录: {目标}", 来源=来源)
    包标识 = 包id if isinstance(包id, str) and 包id.strip() else _包声明取值(目标, "包id")
    包版本 = 版本 if isinstance(版本, str) and 版本.strip() else _包声明取值(目标, "版本")
    if not 包标识:
        return 结果.失败("参数不合法", f"包id 缺省且 包声明.json 未声明: {目标}", 来源=来源)
    if not 包版本:
        return 结果.失败("参数不合法", f"版本 缺省且 包声明.json 未声明: {目标}", 来源=来源)
    if not any(是否应当收录(文件, 目标) for 文件 in 目标.rglob("*")):
        return 结果.失败("包无正式文件", f"包内没有可纳入摘要的正式文件: {目标}", 来源=来源)
    摘要 = _生成文件清单摘要(目标, 包id=包标识, 版本=包版本)
    return 结果.成功结果(摘要)


def 校验完整性摘要(包目录: Any = None) -> 结果:
    """校验完整性摘要：摘要与真实文件是否闭合（不通过时问题列表如实回带）。"""
    目标 = _包目录(包目录)
    if 目标 is None:
        return 结果.失败("参数不合法", f"包目录 必须是非空路径文本: {包目录!r}", 来源=来源)
    if not 目标.is_dir():
        return 结果.失败("包目录不存在", f"包目录不是目录: {目标}", 来源=来源)
    通过, 问题列表 = _校验文件清单摘要(目标)
    return 结果.成功结果({"通过": bool(通过), "问题列表": list(问题列表)})


def 生成模块模板(模块名: Any = None, 类型: Any = "基础模块", 能力清单: Any = None,
                依赖能力清单: Any = None, 系统根: Any = None, 模块库根: Any = None,
                测试中心根: Any = None) -> 结果:
    """生成模块模板：参数归一后委托唯一模板生成器（失败码原样透传）。"""
    if not isinstance(能力清单, list):
        return 结果.失败("参数不合法", "能力清单 必须是列表", 来源=来源)
    依赖清单 = 依赖能力清单 if isinstance(依赖能力清单, list) else []
    return _生成模块模板(
        模块名=模块名,
        类型=类型 if isinstance(类型, str) and 类型.strip() else "基础模块",
        能力清单=能力清单,
        依赖能力清单=依赖清单,
        系统根=系统根,
        模块库根=模块库根,
        测试中心根=测试中心根,
    )
