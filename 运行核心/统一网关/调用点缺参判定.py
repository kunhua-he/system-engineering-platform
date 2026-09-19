"""调用点缺参判定：区分「实现少了位置参数」（参数问题）与「真故障」。

2026-09-19 从 `网关核心.py` 按职责拆出（华哥：按职责拆、能拆多细就多细）。
原处再导出，调用方零改动。
"""

from __future__ import annotations
import inspect as _inspect


class 操作不存在错误(Exception):
    """请求的操作不在允许操作表内：未知操作必须明确报错，不混进「参数不合法」。"""



def _是调用点缺参错误(错误: TypeError) -> bool:
    """判「能力实现缺必填位置参数」——按**异常类型 + 抛错帧归属**，不看消息文案。

    为什么能不看文案：CPython 的「缺必填位置参数 / 多传关键字参数」是**解释器在调用点**
    抛的（实参绑定失败就没进函数体），所以被调函数在栈里**没有自己的帧**，最深帧是发起
    那次调用的那一层。本网关只在 `_执行` 里发起过 `后端核心.调用(...)`：

    - 最深帧就在本网关这一层 → 是本网关/后端契约的调用写错，**不降级成 400**，原样上抛；
    - 最深帧在更下层（后端核心 → 注册表 → 实现）→ 是能力实现的参数口径不匹配，
      属调用方输入问题（哲学第 3 条 2 项：失败必须明确），报 `参数不合法`。

    口径边界（有意放宽，已登记）：改前只认「required positional argument」这一句英文文案，
    实现体内其它 TypeError 会穿到外层变成 500 内部错误；现在凡**从后端链路里抛上来的
    TypeError** 都按参数问题明确回报，错误说明里保留异常原文当证据。
    """
    最深 = 错误.__traceback__
    while 最深 is not None and 最深.tb_next is not None:
        最深 = 最深.tb_next
    if 最深 is None:
        return 假
    try:
        抛错文件 = Path(最深.tb_frame.f_code.co_filename).resolve()
    except (OSError, ValueError):
        return 假
    return 抛错文件 != _本文件路径
from 公共契约.基础类型.逻辑类型 import 真, 假
