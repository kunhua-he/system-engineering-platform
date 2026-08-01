"""发布操作日志与崩溃恢复；所有阶段写入均持久化且可重放。"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

阶段_准备 = "准备"
阶段_提交 = "提交"
阶段_完成 = "完成"
阶段_回滚 = "回滚"


@dataclass
class 操作记录:
    操作id: str
    操作名: str
    包id: str = ""
    版本: str = ""
    阶段: str = 阶段_准备
    事务id: str = ""
    时间: str = ""
    详情: str = ""
    回滚函数名: str = ""
    校验函数名: str = ""
    序号: int = 0

    def 转字典(self) -> dict[str, Any]:
        return {字段: getattr(self, 字段) for 字段 in self.__dataclass_fields__}


class 事务恢复:
    """以追加日志为事实源；损坏日志会阻断新发布而非静默跳过。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(self.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.日志文件 = self.存储目录 / "操作日志.jsonl"
        self.状态文件 = self.存储目录 / "操作状态.json"
        self.操作表: dict[str, 操作记录] = {}
        self.回滚函数表: dict[str, Callable[[操作记录], Any]] = {}
        self.校验函数表: dict[str, Callable[[操作记录], Any]] = {}
        self.加载问题: list[str] = []
        self.锁 = threading.RLock()
        self.加载()

    @staticmethod
    def 默认存储目录() -> str:
        import tempfile
        return os.environ.get("系统库事务目录", str(Path(tempfile.gettempdir()) / "系统工程平台_事务恢复"))

    def 加载(self) -> None:
        if not self.日志文件.is_file():
            return
        for 行号, 行 in enumerate(self.日志文件.read_text(encoding="utf-8").splitlines(), 1):
            if not 行.strip():
                continue
            try:
                数据 = json.loads(行)
                合法数据 = {键: 值 for 键, 值 in 数据.items() if 键 in 操作记录.__dataclass_fields__}
                记录 = 操作记录(**合法数据)
                旧记录 = self.操作表.get(记录.操作id)
                if 旧记录 is None or 记录.序号 >= 旧记录.序号:
                    self.操作表[记录.操作id] = 记录
            except (json.JSONDecodeError, TypeError, KeyError) as 错误:
                self.加载问题.append(f"操作日志第 {行号} 行损坏: {type(错误).__name__}")

    def _原子保存状态(self) -> None:
        临时文件 = self.状态文件.with_suffix(f".tmp.{uuid.uuid4().hex}")
        数据 = {"操作表": [记录.转字典() for 记录 in self.操作表.values()]}
        with 临时文件.open("w", encoding="utf-8") as 输出:
            json.dump(数据, 输出, ensure_ascii=False, sort_keys=True, indent=2)
            输出.flush()
            os.fsync(输出.fileno())
        os.replace(临时文件, self.状态文件)

    def _追加(self, 记录: 操作记录) -> None:
        with self.锁:
            原记录 = self.操作表.get(记录.操作id)
            记录 = replace(记录, 序号=(原记录.序号 + 1 if 原记录 else max(1, 记录.序号)))
            行 = (json.dumps(记录.转字典(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            文件号 = os.open(self.日志文件, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(文件号, 行)
                os.fsync(文件号)
            finally:
                os.close(文件号)
            self.操作表[记录.操作id] = 记录
            self._原子保存状态()

    def 记录准备(self, *, 操作名: str, 包id: str = "", 版本: str = "",
                 事务id: str = "", 回滚函数名: str = "", 详情: str = "",
                 校验函数名: str = "") -> str:
        操作id = uuid.uuid4().hex[:16]
        self._追加(操作记录(
            操作id=操作id, 操作名=操作名, 包id=包id, 版本=版本,
            事务id=事务id or 操作id, 阶段=阶段_准备,
            时间=time.strftime("%Y-%m-%d %H:%M:%S"), 详情=详情,
            回滚函数名=回滚函数名, 校验函数名=校验函数名,
        ))
        return 操作id

    def _推进(self, 操作id: str, 阶段: str, 详情: str = "") -> None:
        记录 = self.操作表.get(操作id)
        if 记录 is None:
            raise KeyError(f"未知操作id: {操作id}")
        允许表 = {
            阶段_准备: {阶段_提交, 阶段_回滚},
            阶段_提交: {阶段_完成, 阶段_回滚},
            阶段_完成: {阶段_完成},
            阶段_回滚: {阶段_回滚},
        }
        if 阶段 not in 允许表.get(记录.阶段, set()):
            raise ValueError(f"非法事务阶段: {记录.阶段} -> {阶段}")
        self._追加(replace(
            记录, 阶段=阶段, 详情=详情 or 记录.详情,
            时间=time.strftime("%Y-%m-%d %H:%M:%S"),
        ))

    def 记录提交(self, 操作id: str, 详情: str = "") -> None:
        self._推进(操作id, 阶段_提交, 详情)

    def 记录完成(self, 操作id: str) -> None:
        self._推进(操作id, 阶段_完成)

    def 记录回滚(self, 操作id: str, 原因: str) -> None:
        self._推进(操作id, 阶段_回滚, f"回滚: {原因}")

    def 注册回滚函数(self, 名称: str, 函数: Callable[[操作记录], Any]) -> None:
        self.回滚函数表[名称] = 函数

    def 注册一致性校验函数(self, 名称: str, 函数: Callable[[操作记录], Any]) -> None:
        self.校验函数表[名称] = 函数

    def 扫描未完成(self) -> list[操作记录]:
        return [记录 for 记录 in self.操作表.values() if 记录.阶段 in (阶段_准备, 阶段_提交)]

    def _校验通过(self, 记录: 操作记录) -> tuple[bool, str]:
        if not 记录.校验函数名:
            return True, "未声明跨存储校验"
        函数 = self.校验函数表.get(记录.校验函数名)
        if 函数 is None:
            return False, "一致性校验函数未注册"
        try:
            结果 = 函数(记录)
        except Exception as 错误:
            return False, f"一致性校验异常: {type(错误).__name__}"
        if isinstance(结果, tuple):
            return bool(结果[0]), str(结果[1]) if len(结果) > 1 else ""
        if isinstance(结果, list):
            return not 结果, "；".join(str(项) for 项 in 结果)
        return bool(结果), ""

    def _执行回滚(self, 记录: 操作记录, 原因: str) -> tuple[bool, str]:
        if 记录.回滚函数名:
            函数 = self.回滚函数表.get(记录.回滚函数名)
            if 函数 is None:
                return False, "回滚函数未注册"
            try:
                函数(记录)
            except Exception as 错误:
                return False, f"回滚执行失败: {type(错误).__name__}"
        self.记录回滚(记录.操作id, 原因)
        return True, ""

    def 恢复(self, *, 自动回滚: bool = True) -> list[dict[str, Any]]:
        结果列表: list[dict[str, Any]] = []
        for 记录 in list(self.扫描未完成()):
            if 记录.阶段 == 阶段_准备:
                if not 自动回滚:
                    结果列表.append({"操作id": 记录.操作id, "操作名": 记录.操作名, "处理": "等待回滚", "阶段": 记录.阶段})
                    continue
                成功, 详情 = self._执行回滚(记录, "崩溃恢复自动回滚")
                结果列表.append({"操作id": 记录.操作id, "操作名": 记录.操作名,
                              "处理": "回滚" if 成功 else "回滚失败",
                              "阶段": 阶段_回滚 if 成功 else 记录.阶段, "详情": 详情})
                continue
            校验通过, 校验详情 = self._校验通过(记录)
            if 校验通过:
                self.记录完成(记录.操作id)
                结果列表.append({"操作id": 记录.操作id, "操作名": 记录.操作名,
                              "处理": "继续完成", "阶段": 阶段_完成, "详情": 校验详情})
            elif 自动回滚:
                成功, 回滚详情 = self._执行回滚(记录, f"跨存储一致性失败: {校验详情}")
                结果列表.append({"操作id": 记录.操作id, "操作名": 记录.操作名,
                              "处理": "回滚" if 成功 else "一致性失败待处理",
                              "阶段": 阶段_回滚 if 成功 else 记录.阶段,
                              "详情": 回滚详情 or 校验详情})
            else:
                结果列表.append({"操作id": 记录.操作id, "操作名": 记录.操作名,
                              "处理": "一致性失败待处理", "阶段": 记录.阶段, "详情": 校验详情})
        return 结果列表

    def 查询(self, 操作id: str) -> 操作记录 | None:
        return self.操作表.get(操作id)

    def 拒绝半成品(self) -> bool:
        return bool(self.加载问题 or self.扫描未完成())
