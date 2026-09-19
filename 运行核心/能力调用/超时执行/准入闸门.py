"""准入闸门：线程侧有界准入的后端解析与降级（平台原语优先，探测不到如实降级）。

源：`运行核心/能力调用/超时执行.py`（20260919 拆分，开工-20260919-225500-e4a1）。
"""

from __future__ import annotations

from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假
import threading

# ═══════════════════════════════════════════════════════════════════
# 闸门后端：优先复用平台并发原语，探测不到才降级（降级如实暴露、不隐瞒）
# ═══════════════════════════════════════════════════════════════════
class _平台闸门后端:
    """复用 `支持库.后端.并发控制支持库` 的容量闸门（只用包级公开入口）。

    语义与需求逐条对齐：`创建容量闸门` 同名复用（幂等，且可同步上限），
    `占用容量` 是「同锁检查 + 占用」、`等待秒=0` ⇒ 满载直接拒绝不排队，
    `释放容量` 幂等、负数钳到 0 —— 正是本模块要的「有界准入 + 明确失败」。
    """

    名称 = "支持库.后端.并发控制支持库.容量闸门（等待秒=0，满载直接拒绝）"

    @staticmethod
    def 确保(闸门名: str, 上限: int) -> None:
        from 支持库.后端.并发控制支持库 import 创建容量闸门
        结果 = 创建容量闸门(闸门名=闸门名, 上限=上限)
        if not 结果.成功:
            raise RuntimeError(f"容量闸门不可用: {结果.错误说明}")

    @staticmethod
    def 尝试占用(闸门名: str, 上限: int) -> dict[str, Any]:
        from 支持库.后端.并发控制支持库 import 占用容量
        结果 = 占用容量(闸门名=闸门名, 槽位数=1, 等待秒=0)
        if not 结果.成功:
            raise RuntimeError(f"容量闸门占用失败: {结果.错误说明}")
        值 = dict(结果.值 or {})
        return {
            "占用": bool(值.get("占用")),
            "当前占用": 值.get("当前占用"),
            "上限": 值.get("上限", 上限),
            "拒绝原因": str(值.get("拒绝原因") or ""),
        }

    @staticmethod
    def 归还(闸门名: str) -> tuple[bool, str]:
        from 支持库.后端.并发控制支持库 import 释放容量
        结果 = 释放容量(闸门名=闸门名, 槽位数=1)
        return bool(结果.成功), "" if 结果.成功 else 结果.错误说明

    @staticmethod
    def 查占用(闸门名: str) -> tuple[int | None, str]:
        from 支持库.后端.并发控制支持库 import 查询容量闸门
        结果 = 查询容量闸门(闸门名=闸门名)
        if not 结果.成功:
            if "闸门不存在" in (结果.错误码 or ""):
                return 0, ""
            return None, 结果.错误说明
        return int((结果.值 or {}).get("占用", 0)), ""

    @staticmethod
    def 列表(前缀: str, 条数上限: int) -> list[dict[str, Any]]:
        from 支持库.后端.并发控制支持库 import 查询容量闸门
        结果 = 查询容量闸门()
        if not 结果.成功:
            return []
        表 = [{"闸门名": str(项.get("闸门名", "")), "上限": 项.get("上限"),
               "占用": 项.get("占用")}
              for 项 in (结果.值 or {}).get("闸门列表", [])
              if str(项.get("闸门名", "")).startswith(前缀)]
        表.sort(key=lambda 项: (-int(项.get("占用") or 0), 项["闸门名"]))
        return 表[:条数上限]


class _标准库闸门后端:
    """降级后端：探测不到平台并发原语时，用标准库实现**语义逐条对齐**的闸门。

    对齐的四条：①同名闸门复用（`确保` 同步上限）；②占用是「同锁检查 + 占用」；
    ③满载**直接拒绝、不排队**（不阻塞等待）；④归还幂等、负数钳到 0。
    降级不隐瞒：`_解析准入后端()` 把原因写进快照 `准入降级说明`。
    """

    名称 = "内置标准库有界闸门（降级后端）"

    def __init__(self) -> None:
        self._锁 = threading.Lock()
        self._表: dict[str, dict[str, Any]] = {}

    def 确保(self, 闸门名: str, 上限: int) -> None:
        with self._锁:
            项 = self._表.get(闸门名)
            if 项 is None:
                self._表[闸门名] = {"上限": int(上限), "占用": 0}
            else:
                项["上限"] = int(上限)

    def 尝试占用(self, 闸门名: str, 上限: int) -> dict[str, Any]:
        with self._锁:
            项 = self._表.get(闸门名)
            if 项 is None:
                项 = {"上限": int(上限), "占用": 0}
                self._表[闸门名] = 项
            if int(项["占用"]) + 1 <= int(项["上限"]):
                项["占用"] = int(项["占用"]) + 1
                return {"占用": 真, "当前占用": 项["占用"], "上限": 项["上限"],
                        "拒绝原因": ""}
            return {"占用": 假, "当前占用": 项["占用"], "上限": 项["上限"],
                    "拒绝原因": "超限直接拒绝不排队"}

    def 归还(self, 闸门名: str) -> tuple[bool, str]:
        with self._锁:
            项 = self._表.get(闸门名)
            if 项 is not None:
                项["占用"] = max(0, int(项["占用"]) - 1)
        return 真, ""

    def 查占用(self, 闸门名: str) -> tuple[int | None, str]:
        with self._锁:
            项 = self._表.get(闸门名)
            return (0, "") if 项 is None else (int(项["占用"]), "")

    def 列表(self, 前缀: str, 条数上限: int) -> list[dict[str, Any]]:
        with self._锁:
            表 = [{"闸门名": 名, "上限": 项["上限"], "占用": 项["占用"]}
                  for 名, 项 in self._表.items() if 名.startswith(前缀)]
        表.sort(key=lambda 项: (-int(项.get("占用") or 0), 项["闸门名"]))
        return 表[:条数上限]


_后端解析锁 = threading.Lock()
_后端缓存: tuple[Any, str] | None = None


def _解析准入后端() -> tuple[Any, str]:
    """解析线程准入后端：优先复用平台原语，不可用则降级（返回 (后端, 降级说明)）。"""
    global _后端缓存
    with _后端解析锁:
        if _后端缓存 is None:
            try:
                import 支持库.后端.并发控制支持库  # noqa: F401 - 只探可用性
                后端, 说明 = _平台闸门后端(), ""
            except BaseException as 错误:  # noqa: BLE001 - 任何导入失败都降级，不阻断调用
                后端 = _标准库闸门后端()
                说明 = (f"平台并发控制支持库不可用（{type(错误).__name__}: {错误}）；"
                        f"已降级为 {后端.名称} —— 同名复用/同锁占用/满载直接拒绝/"
                        f"释放幂等，语义逐条对齐；生产全量制品应保持平台原语路径")
            _后端缓存 = (后端, 说明)
        return _后端缓存


def 重置准入后端() -> None:
    """丢弃后端缓存（热接入/测试用）：下次执行重新探测平台并发原语。"""
    global _后端缓存
    with _后端解析锁:
        _后端缓存 = None


def _归一上限(给定: Any, 默认值: int) -> int:
    """上限归一：None / 布尔 / 非整数 / <=0 一律回落**默认值**。

    不把非法值静默变成 0 上限（那等于关掉准入），也不抛异常打断装配：
    「配置非法 ⇒ 用平台默认上界」是本模块唯一的归一语义。
    """
    if isinstance(给定, bool) or not isinstance(给定, int) or 给定 <= 0:
        return 默认值
    return 给定
