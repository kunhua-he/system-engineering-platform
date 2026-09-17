"""单步验证场景和有序验证步骤。"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import copy
from dataclasses import dataclass, field
from typing import Any

from 公共契约.基础类型.类型表 import 正式类型表
from 开发工具.HTML验证.常量 import 统一返回字段

#: 任意统一返回信封都必现的文本：六个必现字段名（`常量.统一返回字段`）与 JSON 标点。
#: 用途：判「包含」是不是**恒真**断言 —— 期望子串若落在这些必现文本里，命中的是信封本身
#: 而不是业务值，任意信封都能通过（2026-09-17 修的真实缺陷：`"成功"` 是必现字段名）。
_信封必现标点 = frozenset('{}[],:" \t\r\n')


def 包含是恒真(期望: Any) -> bool:
    """`包含` 的期望文本是否为「任意统一返回信封必现」的内容（信封字段名或 JSON 标点）。

    修前 `返回判定._判定` 拿 `json.dumps(返回)` 整包匹配，于是 `"成功"`（信封必现字段名）
    在任意成功信封里都命中 —— 场景声称「验了返回值」，实际什么都没验。本判定在**解析期**
    把这种恒真期望当空气断言挡掉；执行期另有匹配目标收窄（只匹配 `值` 的序列化）。
    """
    if not isinstance(期望, str) or not 期望:
        return 假
    if 期望 in "".join(统一返回字段):
        return 真
    return all(字符 in _信封必现标点 for 字符 in 期望)


def 正向断言有实断言(*, 关键值: Any = None, 值类型: Any = "", 必需字段: Any = None,
                    字段类型: Any = None, 有完整值: bool = False, 包含: Any = "") -> bool:
    """正向（`预期.成功=true`）断言是否至少有**一条能对返回 `值` 说谎**的实断言通道。

    为什么要有这道闸门（2026-09-17 修「HTML 黑盒正向场景可写成恒真空气断言」）：
    修前正向断言只校验「允许字段集」，于是 `{"必需字段": []}`（零字段契约）与
    `{"返回契约": {"必需字段": [], "字段类型": {}}}` 都能被接受、并被 `返回判定._判定`
    的两个空循环全部空转跳过 —— 场景自称「验过」而实际零断言；`预期包含` 又走整包匹配，
    `"成功"` 这类信封必现字段名同样恒真。逐条通道（一律要求**非空**，空壳不算）：

    ① `关键值` 非空对象：逐路径比对返回值；
    ② `值类型` 取 `公共契约/基础类型/类型表.正式类型表` 的 16 个正式类型名之一
       （历史短名/自造名不算：`返回判定._类型匹配` 会判它们不符合，写上去等于没写）；
    ③ `必需字段` 非空列表、④ `字段类型` 非空对象：对返回值逐路径断言存在性/类型；
    ⑤ **完整值断言**（断言里给了 `值`）：与返回值严格全等，是最强的一条；
    ⑥ `包含` 非空文本、且**不是恒真包含**（匹配目标已在 `返回判定._判定` 收窄到 `值` 的序列化）。

    > 口径说明：①~③ 是「实断言」的最小集合；④⑤⑥ 同样只能靠 `值` 说话，故一并认作实断言
    > —— 不认它们会误伤本仓现有正向场景（仅「完整值」一条通道的合法步骤就有 181 条，
    > 仅「包含」的 2 条是真实业务值断言，见体检器 0 不合格的验收口径）。
    """
    if isinstance(关键值, dict) and 关键值:
        return 真
    if isinstance(值类型, str) and 值类型 in 正式类型表:
        return 真
    if isinstance(必需字段, list) and 必需字段:
        return 真
    if isinstance(字段类型, dict) and 字段类型:
        return 真
    if 有完整值:
        return 真
    return bool(包含) and not 包含是恒真(包含)


def _正向断言不合规说明(场景id: str, 位置: str, 包含: Any) -> str:
    """生成正向断言不合规的失败原因（恒真包含单独说清，便于作者知道该补什么）。

    `位置` 传「步骤 <步骤id>」即步骤口径，传空串即整场景口径（措辞沿用包级场景原有
    「真实成功场景」说法，避免把既有报错词表改乱）。
    """
    if 包含是恒真(包含):
        return (f"场景 {场景id}{位置} 正向断言只有恒真包含（{包含!r} 是统一返回信封"
                "必现文本，任意信封都能命中）——必须补实断言：关键值/正式类型名/必需字段/"
                "字段类型/完整值")
    if not 位置:
        return (f"验证场景 {场景id} 的真实成功场景缺少实断言"
                "（关键值 非空 或 值类型 为 16 个正式类型名 或 必需字段/字段类型 非空 或 完整值 "
                "或 非恒真包含；空字段契约与空对象不算）")
    return (f"场景 {场景id}{位置} 正向断言必须有实断言"
            "（关键值 非空 或 值类型 为 16 个正式类型名 或 必需字段/字段类型 非空 或 完整值 "
            "或 非恒真包含；空字段契约与空对象不算）")


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
    if 预期成功 and not 正向断言有实断言(
            关键值=断言.get("关键值"), 值类型=断言.get("值类型"),
            必需字段=断言.get("必需字段"), 字段类型=断言.get("字段类型"),
            有完整值="值" in 断言, 包含=断言.get("包含")):
        raise ValueError(_正向断言不合规说明(场景id, f" 步骤 {步骤id}", 断言.get("包含")))
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
        if 预期["成功"] and not 正向断言有实断言(
                关键值=关键值, 值类型=预期.get("值类型"),
                必需字段=返回契约.get("必需字段"), 字段类型=返回契约.get("字段类型"),
                有完整值="值" in 预期, 包含=预期.get("包含")):
            raise ValueError(_正向断言不合规说明(场景id, "", 预期.get("包含")))
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
