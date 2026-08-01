"""版本注册表：同一包的多个版本并存与生命周期管理。

规则：版本包不可覆盖；每个版本独立完整性摘要/契约信息/验证状态；
项目依赖锁决定实际版本；新版本发布不影响旧项目；旧版本仍被引用时
禁止删除；版本删除前执行引用扫描并确认无运行实例和无回滚任务。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

发布状态_已发布 = "已发布"
发布状态_灰度中 = "灰度中"
发布状态_已激活 = "已激活"
发布状态_已弃用 = "已弃用"
发布状态_已卸载 = "已卸载"


@dataclass
class 版本包:
    """一个 包id@版本 的版本包记录。"""

    包id: str
    版本: str
    契约版本: str = "1.0.0"
    提供者版本: str = ""
    完整性摘要: str = ""
    发布时间: str = ""
    验证状态: str = "未验证"
    发布状态: str = 发布状态_已发布
    弃用状态: str = ""
    引用项目: list[str] = field(default_factory=list)
    可回滚版本: list[str] = field(default_factory=list)
    能力清单: list[str] = field(default_factory=list)

    def 键(self) -> str:
        return f"{self.包id}@{self.版本}"

    def 转字典(self) -> dict[str, Any]:
        return {
            "包id": self.包id, "版本": self.版本, "契约版本": self.契约版本,
            "提供者版本": self.提供者版本, "完整性摘要": self.完整性摘要,
            "发布时间": self.发布时间, "验证状态": self.验证状态,
            "发布状态": self.发布状态, "弃用状态": self.弃用状态,
            "引用项目": self.引用项目, "可回滚版本": self.可回滚版本,
            "能力清单": self.能力清单,
        }


def 计算包摘要(声明字典: dict[str, Any]) -> str:
    """计算包声明的完整性摘要（内容寻址 sha256 前 16 位）。"""
    规范文本 = json.dumps(声明字典, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(规范文本.encode("utf-8")).hexdigest()[:16]


class 版本注册表:
    """版本注册表：多版本并存注册、查询、引用扫描、删除保护。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(版本注册表.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.版本表: dict[str, 版本包] = {}
        self.加载()

    @staticmethod
    def 默认存储目录() -> str:
        import os, tempfile
        return os.environ.get("系统库版本目录", str(Path(tempfile.gettempdir()) / "系统级支持库_版本"))

    def 加载(self) -> None:
        文件 = self.存储目录 / "版本注册表.json"
        if not 文件.is_file():
            return
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
            for 条目 in 数据.get("版本表", []):
                包 = 版本包(**{k: v for k, v in 条目.items() if k in 版本包.__dataclass_fields__})
                self.版本表[包.键()] = 包
        except (json.JSONDecodeError, TypeError):
            pass

    def 保存(self) -> None:
        文件 = self.存储目录 / "版本注册表.json"
        with 文件.open("w", encoding="utf-8") as 输出:
            json.dump({"版本表": [包.转字典() for 包 in self.版本表.values()]},
                      输出, ensure_ascii=False, indent=2)

    def 注册版本(self, 包id: str, 版本: str, *, 契约版本: str = "1.0.0",
                 提供者版本: str = "", 声明字典: dict | None = None,
                 能力清单: list[str] | None = None) -> tuple[bool, str]:
        """注册一个新版本；版本包不可覆盖（同键已存在必须失败）。"""
        键 = f"{包id}@{版本}"
        if 键 in self.版本表:
            return False, f"版本包不可覆盖: {键} 已存在"
        摘要 = 计算包摘要(声明字典 or {"包id": 包id, "版本": 版本})
        版本包记录 = 版本包(
            包id=包id, 版本=版本, 契约版本=契约版本, 提供者版本=提供者版本,
            完整性摘要=摘要, 发布时间=time.strftime("%Y-%m-%d %H:%M:%S"),
            能力清单=能力清单 or [],
        )
        self.版本表[键] = 版本包记录
        self.保存()
        return True, 摘要

    def 查询版本(self, 包id: str = "", 版本: str = "") -> list[版本包]:
        结果列表 = []
        for 包 in self.版本表.values():
            if 包id and 包.包id != 包id:
                continue
            if 版本 and 包.版本 != 版本:
                continue
            结果列表.append(包)
        return 结果列表

    def 获取版本(self, 包id: str, 版本: str) -> 版本包 | None:
        return self.版本表.get(f"{包id}@{版本}")

    def 引用扫描(self, 包id: str, 版本: str) -> list[str]:
        """删除前引用扫描：返回引用项目列表。"""
        包 = self.获取版本(包id, 版本)
        if 包 is None:
            return []
        return list(包.引用项目)

    def 确认可删除(self, 包id: str, 版本: str, *, 运行实例数: int = 0, 回滚任务数: int = 0) -> tuple[bool, str]:
        """确认版本可删除：无引用项目、无运行实例、无回滚任务。"""
        包 = self.获取版本(包id, 版本)
        if 包 is None:
            return False, f"版本不存在: {包id}@{版本}"
        if 包.引用项目:
            return False, f"仍被项目引用: {', '.join(包.引用项目)}，禁止删除"
        if 运行实例数 > 0:
            return False, f"仍有 {运行实例数} 个运行实例，禁止删除"
        if 回滚任务数 > 0:
            return False, f"仍有 {回滚任务数} 个回滚任务，禁止删除"
        return True, "可以删除"

    def 删除版本(self, 包id: str, 版本: str, *, 运行实例数: int = 0, 回滚任务数: int = 0) -> tuple[bool, str]:
        """删除版本；未通过引用扫描禁止删除。"""
        可删, 原因 = self.确认可删除(包id, 版本, 运行实例数=运行实例数, 回滚任务数=回滚任务数)
        if not 可删:
            return False, 原因
        del self.版本表[f"{包id}@{版本}"]
        self.保存()
        return True, "已删除"

    def 标记引用(self, 包id: str, 版本: str, 项目id: str) -> None:
        包 = self.获取版本(包id, 版本)
        if 包 and 项目id not in 包.引用项目:
            包.引用项目.append(项目id)
            self.保存()

    def 标记弃用(self, 包id: str, 版本: str, 弃用状态: str = "已弃用") -> None:
        包 = self.获取版本(包id, 版本)
        if 包:
            包.弃用状态 = 弃用状态
            self.保存()
