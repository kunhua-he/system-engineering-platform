"""发布事务记录、原子持久化与包仓库/版本/路由跨存储一致性校验。"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

操作_安装 = "安装"
操作_校验 = "校验"
操作_注册 = "注册"
操作_激活 = "激活"
操作_灰度 = "灰度"
操作_切换 = "切换"
操作_回滚 = "回滚"
操作_弃用 = "弃用"
操作_停止新调用 = "停止新调用"
操作_卸载 = "卸载"
操作_删除 = "删除"


@dataclass
class 事务步骤:
    步骤名: str
    操作id: str = ""
    成功: bool = False
    详情: str = ""


@dataclass
class 发布事务:
    事务id: str = ""
    包id: str = ""
    版本: str = ""
    创建时间: str = ""
    更新时间: str = ""
    状态: str = "进行中"
    步骤列表: list[事务步骤] = field(default_factory=list)

    def 转字典(self) -> dict[str, Any]:
        return {
            "事务id": self.事务id, "包id": self.包id, "版本": self.版本,
            "创建时间": self.创建时间, "更新时间": self.更新时间,
            "状态": self.状态,
            "步骤": [步骤.__dict__.copy() for 步骤 in self.步骤列表],
        }


class 发布事务管理器:
    """写盘使用同目录临时文件加原子替换；事务状态不会半写。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(self.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.事务表: dict[str, 发布事务] = {}
        self.锁 = threading.RLock()
        self.加载问题: list[str] = []
        self._加载全部()

    @staticmethod
    def 默认存储目录() -> str:
        import tempfile
        return os.environ.get("系统库事务目录", str(Path(tempfile.gettempdir()) / "系统工程平台_事务"))

    def _从数据(self, 数据: dict[str, Any]) -> 发布事务:
        事务 = 发布事务(**{键: 值 for 键, 值 in 数据.items()
                         if 键 in 发布事务.__dataclass_fields__ and 键 != "步骤列表"})
        事务.步骤列表 = [事务步骤(**步骤) for 步骤 in 数据.get("步骤", [])]
        return 事务

    def _加载全部(self) -> None:
        for 文件 in self.存储目录.glob("*.json"):
            try:
                事务 = self._从数据(json.loads(文件.read_text(encoding="utf-8")))
                self.事务表[事务.事务id] = 事务
            except (OSError, json.JSONDecodeError, TypeError, KeyError) as 错误:
                self.加载问题.append(f"事务文件 {文件.name} 损坏: {type(错误).__name__}")

    def 开始(self, 包id: str, 版本: str) -> 发布事务:
        if not 包id or not 版本:
            raise ValueError("包id 和版本不能为空")
        时间文本 = time.strftime("%Y-%m-%d %H:%M:%S")
        事务 = 发布事务(
            事务id=uuid.uuid4().hex[:16], 包id=包id, 版本=版本,
            创建时间=时间文本, 更新时间=时间文本,
        )
        self.事务表[事务.事务id] = 事务
        self.保存(事务)
        return 事务

    def 记录步骤(self, 事务: 发布事务, 步骤名: str, 成功: bool, 详情: str = "") -> str:
        操作id = uuid.uuid4().hex[:16]
        事务.步骤列表.append(事务步骤(步骤名, 操作id, 成功, 详情))
        事务.更新时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.保存(事务)
        return 操作id

    def 保存(self, 事务: 发布事务) -> None:
        with self.锁:
            目标文件 = self.存储目录 / f"{事务.事务id}.json"
            临时文件 = self.存储目录 / f".{事务.事务id}.{uuid.uuid4().hex}.tmp"
            try:
                with 临时文件.open("w", encoding="utf-8") as 输出:
                    json.dump(事务.转字典(), 输出, ensure_ascii=False, sort_keys=True, indent=2)
                    输出.flush()
                    os.fsync(输出.fileno())
                os.replace(临时文件, 目标文件)
                self.事务表[事务.事务id] = 事务
            finally:
                if 临时文件.exists():
                    临时文件.unlink()

    def 提交(self, 事务: 发布事务, *, 一致性问题: list[str] | None = None) -> None:
        if not 事务.步骤列表:
            事务.状态 = "失败"
        elif 一致性问题:
            事务.状态 = "失败"
            self.记录步骤(事务, "一致性校验", False, "；".join(一致性问题))
        elif all(步骤.成功 for 步骤 in 事务.步骤列表):
            事务.状态 = "已提交"
        else:
            事务.状态 = "失败"
        事务.更新时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.保存(事务)

    def 回滚(self, 事务: 发布事务, 原因: str,
             回滚函数: Callable[[事务步骤], Any] | None = None) -> None:
        回滚错误: list[str] = []
        if 回滚函数 is not None:
            for 步骤 in reversed([项 for 项 in 事务.步骤列表 if 项.成功]):
                try:
                    回滚函数(步骤)
                except Exception as 错误:
                    回滚错误.append(f"{步骤.步骤名}:{type(错误).__name__}")
        事务.状态 = "回滚失败" if 回滚错误 else "已回滚"
        self.记录步骤(事务, "回滚", not 回滚错误,
                      原因 if not 回滚错误 else f"{原因}；{'；'.join(回滚错误)}")
        self.保存(事务)

    def 查询(self, 事务id: str) -> 发布事务 | None:
        return self.事务表.get(事务id)

    def 查询未完成(self) -> list[发布事务]:
        return [事务 for 事务 in self.事务表.values() if 事务.状态 in ("进行中", "失败", "回滚失败")]

    def 一致性检查(self, *, 包仓库: Any = None, 版本注册表: Any = None,
                    热切换: Any = None) -> list[str]:
        问题列表 = list(self.加载问题)
        if 版本注册表 is None:
            return 问题列表
        版本列表 = list(版本注册表.查询版本())
        版本键表 = {(包.包id, 包.版本): 包 for 包 in 版本列表}
        if len(版本键表) != len(版本列表):
            问题列表.append("版本注册表存在重复的包id与版本")

        if 包仓库 is not None:
            for (包id, 版本), 版本包 in 版本键表.items():
                已安装 = bool(包仓库.已安装(包id, 版本))
                if 版本包.发布状态 == "已激活" and not 已安装:
                    问题列表.append(f"注册表显示已激活但包未安装: {包id}@{版本}")
                if not 已安装 and 版本包.发布状态 != "已卸载":
                    问题列表.append(f"包已删除但注册表仍可用: {包id}@{版本}")
            版本目录 = getattr(包仓库, "版本目录", None)
            if isinstance(版本目录, Path) and 版本目录.is_dir():
                for 目录 in 版本目录.iterdir():
                    if not 目录.is_dir() or 目录.name.startswith(".") or "@" not in 目录.name:
                        continue
                    包id, 版本 = 目录.name.rsplit("@", 1)
                    if (包id, 版本) not in 版本键表:
                        问题列表.append(f"包已安装但版本注册表缺失: {包id}@{版本}")

        if 热切换 is not None:
            for 能力id, 激活版本 in dict(getattr(热切换, "激活映射", {})).items():
                if not 激活版本:
                    continue
                候选 = [包 for 包 in 版本列表 if 包.版本 == 激活版本 and
                      (not 包.能力清单 or 能力id in 包.能力清单)]
                if not 候选:
                    问题列表.append(f"激活映射指向未安装版本: {能力id}@{激活版本}")
                elif len(候选) > 1 and all(not 包.能力清单 for 包 in 候选):
                    问题列表.append(f"激活映射无法唯一定位包: {能力id}@{激活版本}")
                elif not any(包.发布状态 == "已激活" for 包 in 候选):
                    状态 = "、".join(sorted({包.发布状态 for 包 in 候选}))
                    问题列表.append(f"激活映射指向未激活版本: {能力id}@{激活版本}（状态 {状态}）")
        return list(dict.fromkeys(问题列表))

    def 校验并提交(self, 事务: 发布事务, *, 包仓库: Any = None,
                   版本注册表: Any = None, 热切换: Any = None) -> list[str]:
        问题列表 = self.一致性检查(包仓库=包仓库, 版本注册表=版本注册表, 热切换=热切换)
        self.提交(事务, 一致性问题=问题列表)
        return 问题列表
