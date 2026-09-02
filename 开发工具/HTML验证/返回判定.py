"""统一返回与业务值断言。"""
from __future__ import annotations
import json
from typing import Any
from 开发工具.HTML验证.常量 import 未指定, 统一返回字段, 默认超时秒
from 开发工具.HTML验证.单步场景 import 验证场景
from 开发工具.HTML验证.验证报告 import 验证结果
from 开发工具.HTML验证.HTTP请求 import _发送请求
def _类型匹配(值: Any, 类型名: str) -> bool:
    映射 = {
        "字典型": lambda 项: isinstance(项, dict),
        "对象型": lambda 项: isinstance(项, dict),
        "列表型": lambda 项: isinstance(项, list),
        "文本型": lambda 项: isinstance(项, str),
        "字符串型": lambda 项: isinstance(项, str),
        "整数型": lambda 项: type(项) is int,
        "数值型": lambda 项: type(项) in {int, float},
        "浮点型": lambda 项: type(项) is float,
        "逻辑型": lambda 项: type(项) is bool,
        "布尔型": lambda 项: type(项) is bool,
        "空值型": lambda 项: 项 is None,
    }
    判断 = 映射.get(类型名)
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
        return False, "返回必须是JSON对象"
    缺失 = [字段 for 字段 in 统一返回字段 if 字段 not in 返回]
    if 缺失:
        return False, f"统一返回缺字段: {缺失}"
    if type(返回["成功"]) is not bool:
        return False, "成功必须是真正布尔型"
    if "可重试" in 返回 and type(返回["可重试"]) is not bool:
        return False, "可重试存在时必须是真正布尔型"
    if not isinstance(返回["错误码"], str) or not isinstance(返回["错误说明"], str):
        return False, "错误码/错误说明必须是文本型"
    if not isinstance(返回["请求id"], str) or not 返回["请求id"]:
        return False, "请求id必须是非空文本"
    if type(返回["耗时毫秒"]) not in {int, float} or 返回["耗时毫秒"] < 0:
        return False, "耗时毫秒必须是非负数值"
    if 返回["成功"]:
        if 返回["值"] is None:
            return False, "成功结果的值不可为空"
        if 返回["错误码"] or 返回["错误说明"]:
            return False, "成功结果与错误字段互斥"
    else:
        if 返回["值"] is not None:
            return False, "错误结果的值必须为空"
        if not 返回["错误码"] or not 返回["错误说明"]:
            return False, "错误结果必须包含错误码和错误说明"
    return True, ""

def _判定(场景: 验证场景, 状态码: int, 返回: dict[str, Any]) -> tuple[bool, str, str]:
    合法, 原因 = _校验统一返回(返回)
    if not 合法:
        return False, 原因, "返回契约"
    if 场景.预期状态码 and 状态码 != 场景.预期状态码:
        return False, f"状态码 {状态码} != 预期 {场景.预期状态码}", "路由" if 状态码 in {404, 405} else "网关"
    if 返回["成功"] is not 场景.预期成功:
        return False, f"成功={返回['成功']} != 预期 {场景.预期成功}", "能力"
    if not 场景.预期成功:
        if 返回["错误码"] != 场景.预期错误码:
            return False, f"错误码 {返回['错误码']!r} != 预期 {场景.预期错误码!r}", "能力"
        return True, "", ""
    值 = 返回["值"]
    if 场景.预期值类型 and not _类型匹配(值, 场景.预期值类型):
        return False, f"值类型不符合 {场景.预期值类型}", "值"
    for 路径, 预期值 in 场景.预期关键值.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or 实际值不等于预期(实际, 预期值):
            return False, f"关键值 {路径}={实际!r} != {预期值!r}", "值"
    契约 = 场景.预期返回契约
    必需字段 = 契约.get("必需字段", []) if isinstance(契约, dict) else []
    字段类型 = 契约.get("字段类型", {}) if isinstance(契约, dict) else {}
    if not isinstance(必需字段, list) or not isinstance(字段类型, dict):
        return False, "返回契约的必需字段/字段类型格式不合法", "返回契约"
    for 路径 in 必需字段:
        if _取路径(值, str(路径)) is 未指定:
            return False, f"返回值缺少必需字段: {路径}", "返回契约"
    for 路径, 类型名 in 字段类型.items():
        实际 = _取路径(值, str(路径))
        if 实际 is 未指定 or not isinstance(类型名, str) or not _类型匹配(实际, 类型名):
            return False, f"返回字段 {路径} 类型不符合 {类型名}", "返回契约"
    if 场景.校验完整值 and 实际值不等于预期(值, 场景.预期值):
        return False, f"完整值 {值!r} != 预期 {场景.预期值!r}", "值"
    if 场景.预期包含 and 场景.预期包含 not in json.dumps(返回, ensure_ascii=False):
        return False, f"返回未包含预期子串: {场景.预期包含}", "值"
    return True, "", ""

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
