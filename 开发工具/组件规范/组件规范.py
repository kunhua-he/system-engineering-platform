"""统一组件包规范：支持库/基础模块/功能模块/项目代码 统一九要素包结构。

九要素：包声明/能力契约/依赖契约/配置契约/权限契约/执行单元/验证场景/
说明书/完整性摘要。区别只由颗粒度和依赖方向决定：
支持库=原子能力；基础模块=通用流程；功能模块=完整功能；项目代码=项目特例。
不得复制多套加载器、版本、诊断、日志、发布和验证逻辑。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

组件类型表 = {"支持库", "基础模块", "功能模块", "项目代码"}
九要素 = ("包声明", "能力契约", "依赖契约", "配置契约", "权限契约",
          "执行单元", "验证场景", "说明书", "完整性摘要")


@dataclass
class 规范校验结果:
    """组件规范校验结果。"""

    组件id: str = ""
    问题列表: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 计算目录摘要(目录: Path) -> str:
    """计算目录内全部文件的内容寻址摘要（排除缓存/临时/摘要自身）。"""
    import hashlib as _哈希
    摘要器 = _哈希.sha256()
    for 文件 in sorted(目录.rglob("*")):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件) \
                and 文件.name != "完整性摘要.json":  # 排除摘要自身（避免自引用漂移）
            相对 = str(文件.relative_to(目录))
            摘要器.update(相对.encode("utf-8"))
            摘要器.update(文件.read_bytes())
    return 摘要器.hexdigest()[:16]


def 校验组件规范(组件目录: Path) -> 规范校验结果:
    """校验组件目录符合统一九要素规范。"""
    结果 = 规范校验结果(组件id=组件目录.name)
    声明路径 = 组件目录 / "包声明.json"
    if not 声明路径.is_file():
        结果.问题列表.append("缺少 包声明.json")
        return 结果
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        结果.问题列表.append("包声明.json 不是合法 JSON")
        return 结果
    if 声明.get("类型") not in 组件类型表:
        结果.问题列表.append(f"类型不合法: {声明.get('类型')}（应为 {组件类型表}）")
    if not 声明.get("包id"):
        结果.问题列表.append("缺少 包id")
    if not 声明.get("版本"):
        结果.问题列表.append("缺少 版本")
    # 能力契约目录
    能力契约目录 = 组件目录 / "能力契约"
    if not 能力契约目录.is_dir() or not any(能力契约目录.glob("*.json")):
        结果.问题列表.append("缺少 能力契约/（至少一个契约 JSON）")
    # 依赖契约（可选但推荐）
    if not (组件目录 / "依赖契约").is_dir():
        结果.问题列表.append("缺少 依赖契约/")
    # 配置契约（支持库/模块应有）
    if not (组件目录 / "配置契约").is_dir():
        结果.问题列表.append("缺少 配置契约/")
    # 权限契约
    if not (组件目录 / "权限契约").is_dir():
        结果.问题列表.append("缺少 权限契约/")
    # 执行单元
    if not (组件目录 / "实现").is_dir() and not (组件目录 / "执行单元").is_dir():
        结果.问题列表.append("缺少 实现/ 或 执行单元/")
    # 验证场景
    if not (组件目录 / "验证场景").is_dir() and not (组件目录 / "验证场景引用.json").is_file():
        结果.问题列表.append("缺少 验证场景/ 或 验证场景引用.json")
    # 说明书
    if not (组件目录 / "说明").is_dir() and not (组件目录 / "说明书.md").is_file():
        结果.问题列表.append("缺少 说明/ 或 说明书.md")
    # 完整性摘要
    if not (组件目录 / "完整性摘要.json").is_file():
        结果.问题列表.append("缺少 完整性摘要.json")
    else:
        try:
            摘要数据 = json.loads((组件目录 / "完整性摘要.json").read_text(encoding="utf-8"))
            期望摘要 = 摘要数据.get("摘要", "")
            实际摘要 = 计算目录摘要(组件目录)
            if 期望摘要 != 实际摘要:
                结果.问题列表.append(f"完整性摘要不匹配（期望 {期望摘要}，实际 {实际摘要}）")
        except json.JSONDecodeError:
            结果.问题列表.append("完整性摘要.json 不是合法 JSON")
    return 结果


def 生成完整性摘要(组件目录: Path) -> str:
    """生成并写入完整性摘要.json（排除摘要文件自身与缓存）。"""
    摘要 = 计算目录摘要(组件目录)
    (组件目录 / "完整性摘要.json").write_text(
        json.dumps({"组件id": 组件目录.name, "摘要": 摘要}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 摘要


def 说明颗粒度(组件目录: Path) -> str:
    """按颗粒度说明组件定位。"""
    声明路径 = 组件目录 / "包声明.json"
    if not 声明路径.is_file():
        return "未知"
    类型 = json.loads(声明路径.read_text(encoding="utf-8")).get("类型", "未知")
    return {
        "支持库": "原子能力（文件系统/文本处理等）",
        "基础模块": "通用流程（组合支持库公开入口）",
        "功能模块": "完整功能（面向场景组合）",
        "项目代码": "项目特例（唯一项目专属）",
    }.get(类型, 类型)
