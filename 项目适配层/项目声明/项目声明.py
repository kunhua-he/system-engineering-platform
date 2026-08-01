"""项目声明：项目身份与绑定声明的解析校验。

项目声明.json 定义项目身份、所需支持库与模块绑定、验证范围。
适配层只消费声明，不读取业务项目代码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

必填字段 = ("项目id", "项目名称", "系统版本", "支持库绑定", "模块绑定", "验证范围")


@dataclass
class 项目声明:
    """一份项目声明的解析结果。"""

    项目id: str
    项目名称: str
    系统版本: str = ">=1.0.0"
    支持库绑定: list[dict] = field(default_factory=list)
    模块绑定: list[dict] = field(default_factory=list)
    验证范围: list[str] = field(default_factory=list)
    来源路径: str = ""

    def 转字典(self) -> dict:
        return {
            "项目id": self.项目id,
            "项目名称": self.项目名称,
            "系统版本": self.系统版本,
            "支持库绑定": self.支持库绑定,
            "模块绑定": self.模块绑定,
            "验证范围": self.验证范围,
        }


def 从字典构建(数据: dict, 来源路径: str = "") -> 项目声明:
    """从字典构建项目声明；缺失必填字段抛 ValueError。"""
    缺失 = [字段 for 字段 in 必填字段 if 字段 not in 数据]
    if 缺失:
        raise ValueError(f"项目声明缺少必填字段: {', '.join(缺失)}")
    return 项目声明(
        项目id=数据["项目id"],
        项目名称=数据["项目名称"],
        系统版本=数据.get("系统版本", ">=1.0.0"),
        支持库绑定=数据.get("支持库绑定", []),
        模块绑定=数据.get("模块绑定", []),
        验证范围=数据.get("验证范围", []),
        来源路径=来源路径,
    )


def 加载项目声明(声明路径: Path) -> 项目声明:
    """从文件加载项目声明；JSON 不合法抛 ValueError。"""
    try:
        数据 = json.loads(声明路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        raise ValueError(f"项目声明读取失败 {声明路径}: {错误}") from 错误
    return 从字典构建(数据, 来源路径=str(声明路径))


def 写入项目声明(声明: 项目声明, 声明路径: Path) -> None:
    """写入项目声明 JSON（原子写盘）。"""
    声明路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = 声明路径.with_suffix(".tmp")
    临时路径.write_text(json.dumps(声明.转字典(), ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(声明路径)
