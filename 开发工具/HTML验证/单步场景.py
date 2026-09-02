"""单步验证场景和有序验证步骤。"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


def _解析断言(断言: Any, 场景id: str, 步骤id: str, 预期成功: bool) -> dict[str, Any]:
    if not isinstance(断言, dict) or not 断言:
        raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言不可为空")
    允许 = {"错误码", "包含", "值类型", "关键值", "必需字段", "字段类型", "值"}
    if set(断言) - 允许:
        raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言含未知字段")
    for 字段, 类型 in (("关键值", dict), ("必需字段", list), ("字段类型", dict)):
        if not isinstance(断言.get(字段, 类型()), 类型):
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 返回断言结构不合法")
    错误码 = 断言.get("错误码", "")
    if not isinstance(错误码, str) or (not 预期成功 and not 错误码):
        raise ValueError(f"场景 {场景id} 步骤 {步骤id} 负向断言必须声明错误码")
    return 断言


@dataclass
class 验证场景:
    场景id: str
    能力id: str
    方法: str = "POST"
    路径: str = "/网关/调用"
    参数: dict[str, Any] = field(default_factory=dict)
    预期状态码: int = 200
    预期成功: bool = True
    预期错误码: str = ""
    预期包含: str = ""
    预期值类型: str = ""
    预期关键值: dict[str, Any] = field(default_factory=dict)
    预期返回契约: dict[str, Any] = field(default_factory=dict)
    预期值: Any = None
    校验完整值: bool = False
    说明: str = ""
    制品摘要: str = ""
    步骤id: str = ""

    def 转字典(self) -> dict[str, Any]:
        预期 = {"成功": self.预期成功, "状态码": self.预期状态码}
        for 键, 值 in (("错误码", self.预期错误码), ("包含", self.预期包含),
                      ("值类型", self.预期值类型), ("关键值", self.预期关键值),
                      ("返回契约", self.预期返回契约)):
            if 值:
                预期[键] = 值
        if self.校验完整值:
            预期["值"] = self.预期值
        return {"场景id": self.场景id, "能力id": self.能力id, "方法": self.方法,
                "路径": self.路径, "参数": self.参数, "预期": 预期,
                "说明": self.说明, "制品摘要": self.制品摘要}

    @classmethod
    def 从字典(cls, 数据: dict[str, Any]) -> 验证场景:
        if not isinstance(数据, dict):
            raise ValueError("验证场景必须是对象")
        场景id, 能力id = 数据.get("场景id"), 数据.get("能力id")
        if not isinstance(场景id, str) or not 场景id.strip():
            raise ValueError("验证场景缺少场景id")
        if not isinstance(能力id, str) or not 能力id.strip():
            raise ValueError(f"验证场景 {场景id} 缺少能力id")
        方法, 路径, 参数, 预期 = 数据.get("方法", "POST"), 数据.get("路径", "/网关/调用"), 数据.get("参数", {}), 数据.get("预期")
        if not isinstance(方法, str) or 方法.upper() not in {"GET", "POST"}:
            raise ValueError(f"验证场景 {场景id} 方法不合法")
        if not isinstance(路径, str) or not 路径.startswith("/"):
            raise ValueError(f"验证场景 {场景id} 路径不合法")
        if not isinstance(参数, dict):
            raise ValueError(f"验证场景 {场景id} 参数必须是对象")
        if not isinstance(预期, dict) or type(预期.get("成功")) is not bool:
            raise ValueError(f"验证场景 {场景id} 必须声明预期.成功布尔值")
        状态码 = 预期.get("状态码", 200 if 预期["成功"] else 0)
        if type(状态码) is not int or not 0 <= 状态码 <= 599:
            raise ValueError(f"验证场景 {场景id} 预期状态码不合法")
        错误码, 关键值, 返回契约 = 预期.get("错误码", ""), 预期.get("关键值", {}), 预期.get("返回契约", {})
        if not isinstance(错误码, str) or (not 预期["成功"] and not 错误码):
            raise ValueError(f"验证场景 {场景id} 负向场景必须声明错误码")
        if not isinstance(关键值, dict) or not isinstance(返回契约, dict):
            raise ValueError(f"验证场景 {场景id} 关键值/返回契约必须是对象")
        if 预期["成功"] and not any(("值" in 预期, 预期.get("值类型"), 关键值, 返回契约)):
            raise ValueError(f"验证场景 {场景id} 的真实成功场景缺少值/类型/关键值断言")
        return cls(场景id.strip(), 能力id.strip(), 方法.upper(), 路径, 参数, 状态码,
                   预期["成功"], 错误码, str(预期.get("包含", "")), str(预期.get("值类型", "")),
                   关键值, 返回契约, 预期.get("值"), "值" in 预期,
                   str(数据.get("说明", "")), str(数据.get("制品摘要", "")))


@dataclass
class 验证步骤:
    步骤id: str
    能力id: str
    参数: dict[str, Any] = field(default_factory=dict)
    预期状态码: int = 200
    预期成功: bool = True
    预期错误码: str = ""
    预期包含: str = ""
    预期值类型: str = ""
    预期关键值: dict[str, Any] = field(default_factory=dict)
    预期返回契约: dict[str, Any] = field(default_factory=dict)
    预期值: Any = None
    校验完整值: bool = False
    制品摘要: str = ""

    def 转字典(self) -> dict[str, Any]:
        断言 = {键: 值 for 键, 值 in (("错误码", self.预期错误码), ("包含", self.预期包含),
                  ("值类型", self.预期值类型), ("关键值", self.预期关键值)) if 值}
        断言.update(self.预期返回契约)
        if self.校验完整值:
            断言["值"] = self.预期值
        return {"步骤id": self.步骤id, "能力id": self.能力id, "参数": self.参数,
                "预期": {"成功": self.预期成功, "状态码": self.预期状态码, "返回断言": 断言}}

    @classmethod
    def 从字典(cls, 数据: Any, 场景id: str) -> 验证步骤:
        if not isinstance(数据, dict):
            raise ValueError(f"场景 {场景id} 的步骤必须是对象")
        if set(数据) - {"步骤id", "能力id", "参数", "预期"}:
            raise ValueError(f"场景 {场景id} 步骤含未授权字段: {sorted(set(数据) - {'步骤id', '能力id', '参数', '预期'})}")
        步骤id, 能力id, 参数, 预期 = 数据.get("步骤id"), 数据.get("能力id"), 数据.get("参数", {}), 数据.get("预期")
        if not isinstance(步骤id, str) or not 步骤id.strip():
            raise ValueError(f"场景 {场景id} 的步骤缺少步骤id")
        if not isinstance(能力id, str) or not 能力id.strip():
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 缺少真实能力id")
        if not isinstance(参数, dict):
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 参数必须是对象")
        if not isinstance(预期, dict) or set(预期) != {"成功", "状态码", "返回断言"}:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 必须声明预期成功/状态码/返回断言")
        if type(预期["成功"]) is not bool or type(预期["状态码"]) is not int or not 100 <= 预期["状态码"] <= 599:
            raise ValueError(f"场景 {场景id} 步骤 {步骤id} 状态码不合法")
        断言 = _解析断言(预期["返回断言"], 场景id, 步骤id, 预期["成功"])
        返回契约 = {键: copy.deepcopy(断言[键]) for 键 in ("必需字段", "字段类型") if 键 in 断言}
        return cls(步骤id.strip(), 能力id.strip(), copy.deepcopy(参数), 预期["状态码"], 预期["成功"],
                   断言.get("错误码", ""), str(断言.get("包含", "")), str(断言.get("值类型", "")),
                   copy.deepcopy(断言.get("关键值", {})), 返回契约, copy.deepcopy(断言.get("值")), "值" in 断言)
