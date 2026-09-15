"""统一组件包规范：支持库/基础模块/功能模块/项目代码 统一九要素包结构。

九要素：包声明/能力契约/依赖契约/配置契约/权限契约/执行单元/验证场景/
说明书/完整性摘要。区别只由颗粒度和依赖方向决定：
支持库=原子能力；基础模块=通用流程；功能模块=完整功能；项目代码=项目特例。
完整性摘要生成/校验一律委托唯一生成器（完整性摘要.py，文件清单 sha256
唯一权威格式），不得复制第二套摘要算法；旧 {组件id,摘要} 格式一律拒绝。
不得复制多套加载器、版本、诊断、日志、发布和验证逻辑。
"""

from __future__ import annotations

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
    # 依赖契约：可选 —— 无目录 = 无内部依赖（2026-09-15 定：空白声明删掉，不留占位目录；
    # 与组件合规「依赖」判据同源：声明缺失即独立组件）
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
    # 完整性摘要（委托唯一校验器：文件清单格式唯一权威，旧格式一律拒绝）
    if not (组件目录 / "完整性摘要.json").is_file():
        结果.问题列表.append("缺少 完整性摘要.json")
    else:
        from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
        通过, 问题列表 = 校验完整性摘要(组件目录)
        结果.问题列表.extend(问题列表)
    return 结果


def 生成完整性摘要(组件目录: Path) -> dict[str, Any]:
    """生成并写入 完整性摘要.json（委托唯一生成器，文件清单唯一权威格式）。

    包id/版本取自 包声明.json（缺省时用 组件目录名/1.0.0），
    不复制任何第二套摘要算法。
    """
    from 开发工具.组件规范.完整性摘要 import 生成完整性摘要 as 生成文件清单摘要
    声明路径 = 组件目录 / "包声明.json"
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        声明 = {}
    摘要 = 生成文件清单摘要(
        组件目录, 包id=声明.get("包id", 组件目录.name),
        版本=声明.get("版本", "1.0.0"))
    (组件目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 摘要
