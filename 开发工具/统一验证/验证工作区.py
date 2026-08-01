"""验证工作区隔离：每次验证创建独立运行目录，不修改正式资产。

工程缓存/验证运行/<运行id>/{输入快照,工作副本,依赖锁定.json,验证结果.json,运行证据.jsonl}
临时文件必须包含操作id；异常退出后必须回收工作区、句柄、进程、端口和锁。
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any


class 验证工作区:
    """验证工作区：创建/校验/回收。"""

    def __init__(self, 工程根: Path, 运行id: str = "") -> None:
        self.工程根 = Path(工程根)
        self.运行id = 运行id or uuid.uuid4().hex[:16]
        self.根目录 = self.工程根 / "工程缓存" / "验证运行" / self.运行id
        self.输入快照目录 = self.根目录 / "输入快照"
        self.工作副本目录 = self.根目录 / "工作副本"
        self.依赖锁定文件 = self.根目录 / "依赖锁定.json"
        self.验证结果文件 = self.根目录 / "验证结果.json"
        self.运行证据文件 = self.根目录 / "运行证据.jsonl"
        self.已回收 = False

    def 创建(self) -> Path:
        """创建完整工作区结构。"""
        for 目录 in (self.输入快照目录, self.工作副本目录):
            目录.mkdir(parents=True, exist_ok=False)
        self.依赖锁定文件.write_text(
            json.dumps({"运行id": self.运行id, "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "依赖": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.验证结果文件.write_text(
            json.dumps({"运行id": self.运行id, "状态": "进行中"}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return self.根目录

    def 复制输入快照(self, 来源目录: Path) -> None:
        """复制输入快照（只读拷贝，不引用正式资产）。"""
        for 文件 in Path(来源目录).rglob("*"):
            if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件):
                相对 = 文件.relative_to(来源目录)
                目标 = self.输入快照目录 / 相对
                目标.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(文件, 目标)

    def 记录证据(self, 事件类型: str, 详情: dict[str, Any] | None = None) -> None:
        """运行证据（JSONL 追加）。"""
        with self.运行证据文件.open("a", encoding="utf-8") as 输出:
            输出.write(json.dumps({
                "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "运行id": self.运行id, "事件": 事件类型, "详情": 详情 or {},
            }, ensure_ascii=False) + "\n")

    def 写入结果(self, *, 状态: str, 测试数: int = 0, 失败数: int = 0,
                 耗时秒: float = 0.0, 详情: str = "") -> None:
        数据 = {
            "运行id": self.运行id, "状态": 状态, "测试数": 测试数,
            "失败数": 失败数, "耗时秒": round(耗时秒, 3), "详情": 详情,
            "完成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.验证结果文件.write_text(
            json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")

    def 回收(self) -> list[str]:
        """异常退出后回收：工作区/句柄/进程/端口/锁（此处回收工作区与锁）。"""
        if self.已回收:
            return ["工作区已回收（幂等）"]
        清理列表 = []
        if self.根目录.is_dir():
            shutil.rmtree(self.根目录, ignore_errors=True)
            清理列表.append(f"工作区: {self.运行id}")
        self.已回收 = True
        return 清理列表


def 校验临时文件名(文件: Path, 操作id: str) -> bool:
    """临时文件必须包含操作id（禁止共享 依赖锁定.tmp 等固定名）。"""
    名称 = 文件.name
    if 名称.endswith(".tmp") and 操作id not in 名称:
        return False
    return True


def 校验不写正式目录(路径: Path, 正式目录表: list[Path]) -> bool:
    """验证工作区不得写入正式目录（路径在任一正式目录内 → 拒绝）。"""
    路径 = Path(路径).resolve()
    for 正式目录 in 正式目录表:
        try:
            路径.relative_to(Path(正式目录).resolve())
            return False  # 路径在正式目录内 → 会写入正式资产 → 拒绝
        except ValueError:
            pass
    return True
