"""消费者契约注册表：真实请求、响应约束、错误码、超时、释放要求绑定消费者与能力。

契约登记写入 JSON 存储（存储目录/消费者契约.json）；漂移判定按结构化字段逐项
真实对比（参数/返回键/错误码/超时/释放），发现漂移即返回漂移列表供发布门禁
阻断（门禁判定）。契约结构参照 契约编译/消费者契约.py 的操作契约字段语义。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# 对外错误码（中文口径，决策记录 0003「不用英文枚举」）：错误返回的错误码一律中文，
# 与 能力定义.json 声明的 消费者必填/能力必填/契约非法/未登记 逐字一致。
错误码表 = ("成功", "消费者必填", "能力必填", "契约非法", "未登记")


def 统一返回(成功: bool, 错误码: str, 消息: str, 数据=None) -> dict:
    """统一返回结构：成功/错误码/消息/数据。"""
    return {"成功": 成功, "错误码": 错误码, "消息": 消息, "数据": 数据}


class 消费者契约注册表:
    """消费者契约注册表；存储目录下 消费者契约.json 保存全部绑定。"""

    def __init__(self, 存储目录: Path | str) -> None:
        self.存储文件 = Path(存储目录) / "消费者契约.json"

    # ---- 存储基础 ----
    def _读取(self) -> dict:
        """读取存储；文件缺失或损坏视为空注册表。"""
        try:
            return json.loads(self.存储文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _写入(self, 存储: dict) -> None:
        self.存储文件.parent.mkdir(parents=True, exist_ok=True)
        self.存储文件.write_text(json.dumps(存储, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 登记与查询 ----
    def 登记契约(self, 消费者id: str, 能力id: str, 契约: dict) -> dict:
        """登记消费者对能力的契约（请求/响应约束/错误码/超时/释放要求）并落盘。"""
        if not 消费者id:
            return 统一返回(False, "消费者必填", "消费者id不能为空")
        if not 能力id:
            return 统一返回(False, "能力必填", "能力id不能为空")
        问题 = self._契约问题(契约)
        if 问题:
            return 统一返回(False, "契约非法", 问题)
        记录 = {**契约, "消费者id": 消费者id, "能力id": 能力id,
                "登记时间": time.strftime("%Y-%m-%d %H:%M:%S")}
        存储 = self._读取()
        存储.setdefault(能力id, {})[消费者id] = 记录
        self._写入(存储)
        return 统一返回(True, "成功",
                        f"消费者 {消费者id} 对能力 {能力id} 的契约已登记", 记录)

    def 查询契约(self, 能力id: str) -> dict:
        """查询能力下全部消费者契约（未登记能力返回空列表）。"""
        能力表 = self._读取().get(能力id, {})
        return 统一返回(True, "成功",
                        f"能力 {能力id} 共 {len(能力表)} 份消费者契约",
                        list(能力表.values()))

    def 删除契约(self, 消费者id: str, 能力id: str) -> dict:
        """删除消费者与能力的契约绑定。"""
        存储 = self._读取()
        能力表 = 存储.get(能力id, {})
        if 消费者id not in 能力表:
            return 统一返回(False, "未登记",
                            f"能力 {能力id} 未登记消费者 {消费者id} 的契约")
        del 能力表[消费者id]
        if not 能力表:
            del 存储[能力id]
        self._写入(存储)
        return 统一返回(True, "成功",
                        f"已删除消费者 {消费者id} 对能力 {能力id} 的契约")

    # ---- 漂移判定 ----
    def 漂移判定(self, 能力id: str, 当前契约: dict) -> dict:
        """当前能力契约与全部登记消费者契约逐项对比，返回漂移列表。"""
        能力表 = self._读取().get(能力id, {})
        漂移列表: list[dict] = []
        for 消费者id, 登记 in sorted(能力表.items()):
            漂移列表.extend(self._对比消费者(消费者id, 登记, 当前契约))
        return 统一返回(True, "成功",
                        f"能力 {能力id} 发现 {len(漂移列表)} 处契约漂移", 漂移列表)

    def _对比消费者(self, 消费者id: str, 登记: dict, 当前契约: dict) -> list[dict]:
        """逐项对比一个消费者登记契约与当前能力契约；每项漂移含 期望值/实际值/类型。"""
        漂移: list[dict] = []
        当前请求参数 = 当前契约.get("请求", {}).get("参数列表", [])
        for 参数 in 登记.get("请求", {}).get("参数列表", []):
            if 参数 not in 当前请求参数:
                漂移.append({"消费者id": 消费者id, "期望值": 参数,
                            "实际值": 当前请求参数, "漂移类型": "参数漂移"})
        当前返回键 = 当前契约.get("响应约束", {}).get("返回键", [])
        for 键 in 登记.get("响应约束", {}).get("返回键", []):
            if 键 not in 当前返回键:
                漂移.append({"消费者id": 消费者id, "期望值": 键,
                            "实际值": 当前返回键, "漂移类型": "返回键漂移"})
        当前错误码 = 当前契约.get("错误码集", [])
        for 码 in 登记.get("错误码集", []):
            if 码 not in 当前错误码:
                漂移.append({"消费者id": 消费者id, "期望值": 码,
                            "实际值": 当前错误码, "漂移类型": "错误码漂移"})
        登记超时 = 登记.get("超时")
        当前超时 = 当前契约.get("超时")
        if 当前超时 is None or (登记超时 is not None and 当前超时 < 登记超时):
            漂移.append({"消费者id": 消费者id, "期望值": 登记超时,
                        "实际值": 当前超时, "漂移类型": "超时漂移"})
        当前释放 = 当前契约.get("释放要求", [])
        for 项 in 登记.get("释放要求", []):
            if 项 not in 当前释放:
                漂移.append({"消费者id": 消费者id, "期望值": 项,
                            "实际值": 当前释放, "漂移类型": "释放漂移"})
        return 漂移

    def 门禁判定(self, 能力id: str, 当前契约: dict) -> dict:
        """门禁判定：存在任一漂移则阻断；数据含 是否阻断 与 漂移列表。"""
        结果 = self.漂移判定(能力id, 当前契约)
        漂移列表 = 结果["数据"]
        return 统一返回(True, "成功",
                        f"门禁{'阻断' if 漂移列表 else '放行'}：发现 {len(漂移列表)} 处漂移",
                        {"是否阻断": bool(漂移列表), "漂移列表": 漂移列表})

    # ---- 契约结构校验 ----
    def _契约问题(self, 契约: dict) -> str:
        """校验契约结构：请求/响应约束/错误码集/超时/释放要求 字段齐备；返回问题或空串。"""
        if not isinstance(契约, dict):
            return "契约必须为字典"
        请求 = 契约.get("请求")
        响应约束 = 契约.get("响应约束")
        if not isinstance(请求, dict) or not isinstance(请求.get("参数列表"), list) \
                or not isinstance(请求.get("示例"), dict):
            return "请求 必须含 参数列表(列表) 与 示例(字典)"
        if not isinstance(响应约束, dict) or not isinstance(响应约束.get("返回键"), list) \
                or not 响应约束.get("结构"):
            return "响应约束 必须含 返回键(列表) 与 结构"
        if not isinstance(契约.get("错误码集"), list):
            return "错误码集 必须为列表"
        if not isinstance(契约.get("超时"), (int, float)):
            return "超时 必须为秒数"
        if not isinstance(契约.get("释放要求"), list):
            return "释放要求 必须为列表"
        return ""
