"""统一返回与业务值断言。"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假
import json
from typing import Any
from 公共契约.基础类型.类型表 import 正式类型表
from 公共契约.基础类型.数值类型 import 数值类型定义, 校验数值类型
from 运行核心.统一网关.网关核心 import 类型匹配表
from 开发工具.HTML验证.常量 import 未指定, 统一返回字段, 默认超时秒
from 开发工具.HTML验证.单步场景 import 验证场景, 正向断言有实断言
from 开发工具.HTML验证.验证报告 import 验证结果
from 开发工具.HTML验证.HTTP请求 import _发送请求


def _类型匹配(值: Any, 类型名: str) -> bool:
    """值是否符合**正式类型名**；只消费唯一事实源，本模块不维护第二份类型名表。

    三段判定顺序（每一段都给出去处）：

    1. 名字闸门 = `公共契约/基础类型/类型表.py:正式类型表`（16 个正式类型名的唯一清单）。
       不在表内的名字（历史短名 `文本/结果/浮点数…`、历史自造名
       `对象型/字符串型/数值型/浮点型/布尔型`）一律判**不符合**——它们的语义无冻结定义，
       放行等于"声明了类型却没人校验"的假绿。
    2. 四类数值型 = `公共契约/基础类型/数值类型.py`：边界冻结、不做隐式转换
       （`校验数值类型` 只接受真 int/真 float，布尔不算整数）。
    3. 其余 12 类 = `运行核心/统一网关/网关核心.py:类型匹配表`：网关在 JSON 边界上的
       **同一张**判定表；HTML 黑盒与线上网关因此逐项同强度，不存在"两套类型表"的裂缝。
    """
    if 类型名 not in 正式类型表:
        return 假
    if 类型名 in 数值类型定义:
        try:
            return bool(校验数值类型(值, 类型名))
        except ValueError:
            return 假
    判断 = 类型匹配表.get(类型名)
    return bool(判断 and 判断(值))

def _取路径(值: Any, 路径: str) -> Any:
    当前 = 值
    if 路径 in {"", "$"}:
        return 当前
    for 段 in 路径.removeprefix("$.").split("."):
        if isinstance(当前, dict) and 段 in 当前:
            当前 = 当前[段]
        elif isinstance(当前, list) and 段.isdigit() and int(段) < len(当前):
            当前 = 当前[int(段)]
        else:
            return 未指定
    return 当前

def _校验统一返回(返回: Any) -> tuple[bool, str]:
    if not isinstance(返回, dict):
        return 假, "返回必须是JSON对象"
    缺失 = [字段 for 字段 in 统一返回字段 if 字段 not in 返回]
    if 缺失:
        return 假, f"统一返回缺字段: {缺失}"
    if type(返回["成功"]) is not bool:
        return 假, "成功必须是真正布尔型"
    if "可重试" in 返回 and type(返回["可重试"]) is not bool:
        return 假, "可重试存在时必须是真正布尔型"
    if not isinstance(返回["错误码"], str) or not isinstance(返回["错误说明"], str):
        return 假, "错误码/错误说明必须是文本型"
    if not isinstance(返回["请求id"], str) or not 返回["请求id"]:
        return 假, "请求id必须是非空文本"
    if type(返回["耗时毫秒"]) not in {int, float} or 返回["耗时毫秒"] < 0:
        return 假, "耗时毫秒必须是非负数值"
    if 返回["成功"]:
        if 返回["值"] is None:
            return 假, "成功结果的值不可为空"
        if 返回["错误码"] or 返回["错误说明"]:
            return 假, "成功结果与错误字段互斥"
    else:
        if 返回["值"] is not None:
            return 假, "错误结果的值必须为空"
        if not 返回["错误码"] or not 返回["错误说明"]:
            return 假, "错误结果必须包含错误码和错误说明"
    return 真, ""

def _判定(场景: 验证场景, 状态码: int, 返回: dict[str, Any]) -> tuple[bool, str, str]:
    合法, 原因 = _校验统一返回(返回)
    if not 合法:
        return 假, 原因, "返回契约"
    if 场景.预期状态码 and 状态码 != 场景.预期状态码:
        return 假, f"状态码 {状态码} != 预期 {场景.预期状态码}", "路由" if 状态码 in {404, 405} else "网关"
    if 返回["成功"] is not 场景.预期成功:
        return 假, f"成功={返回['成功']} != 预期 {场景.预期成功}", "能力"
    if not 场景.预期成功:
        if 返回["错误码"] != 场景.预期错误码:
            return 假, f"错误码 {返回['错误码']!r} != 预期 {场景.预期错误码!r}", "能力"
        return 真, "", ""
    值 = 返回["值"]
    if not 正向断言有实断言(
            关键值=场景.预期关键值, 值类型=场景.预期值类型,
            必需字段=(场景.预期返回契约 or {}).get("必需字段"),
            字段类型=(场景.预期返回契约 or {}).get("字段类型"),
            有完整值=场景.校验完整值, 包含=场景.预期包含):
        # 执行期第二道闸门（与解析期 `单步场景._解析断言` 同口径）：程序化构造的验证场景
        # 绕不过「必须有实断言」——否则空字段契约/恒真包含仍能一路"通过"。
        return 假, "正向断言必须有实断言（空字段契约、空对象与恒真包含不算，见 单步场景）", "返回契约"
    if 场景.预期值类型 and not _类型匹配(值, 场景.预期值类型):
        return 假, f"值类型不符合 {场景.预期值类型}", "值"
    for 路径, 预期值 in 场景.预期关键值.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or 实际值不等于预期(实际, 预期值):
            return 假, f"关键值 {路径}={实际!r} != {预期值!r}", "值"
    契约 = 场景.预期返回契约
    必需字段 = 契约.get("必需字段", []) if isinstance(契约, dict) else []
    字段类型 = 契约.get("字段类型", {}) if isinstance(契约, dict) else {}
    if not isinstance(必需字段, list) or not isinstance(字段类型, dict):
        return 假, "返回契约的必需字段/字段类型格式不合法", "返回契约"
    for 路径 in 必需字段:
        if _取路径(值, str(路径)) is 未指定:
            return 假, f"返回值缺少必需字段: {路径}", "返回契约"
    for 路径, 类型名 in 字段类型.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or not isinstance(类型名, str) or not _类型匹配(实际, 类型名):
            return 假, f"返回字段 {路径} 类型不符合 {类型名}", "返回契约"
    if 场景.校验完整值 and 实际值不等于预期(值, 场景.预期值):
        return 假, f"完整值 {值!r} != 预期 {场景.预期值!r}", "值"
    if 场景.预期包含 and 场景.预期包含 not in json.dumps(值, ensure_ascii=False):
        # 匹配目标**只到 `值` 的序列化**（2026-09-17 修「整包匹配 = 恒真断言」）：
        # 修前拿 `json.dumps(返回)` 整包匹配，于是 `"成功"`（信封必现字段名）在任意
        # 成功信封里都命中，场景自称"验了返回值"实际零断言。
        return 假, f"返回值未包含预期子串: {场景.预期包含}", "值"
    return 真, "", ""

def 实际值不等于预期(实际: Any, 预期: Any) -> bool:
    """严格比较，避免 bool 与 0/1 被 Python 相等语义混淆。"""
    return type(实际) is not type(预期) or 实际 != 预期

def 验证单个(地址: str, 场景: 验证场景, 超时秒: float = 默认超时秒) -> 验证结果:
    结果 = 验证结果(场景id=场景.场景id, 能力id=场景.能力id)
    try:
        状态码, 返回, 耗时 = _发送请求(地址, 场景, 超时秒)
        结果.状态码 = 状态码
        结果.返回 = 返回
        结果.耗时毫秒 = 耗时
        结果.通过, 结果.失败原因, 结果.定位线索 = _判定(场景, 状态码, 返回)
    except BaseException as 错误:
        结果.失败原因 = f"验证任务异常: {type(错误).__name__}: {错误}"
        结果.定位线索 = "验证器"
    return 结果
