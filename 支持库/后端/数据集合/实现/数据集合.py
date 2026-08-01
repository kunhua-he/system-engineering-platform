"""原子能力实现（不对外暴露，只经包级中文入口调用）。"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="数据集合")


def 列表添加(列表: list, 条目: Any) -> 结果:
    return _成功([*列表, 条目])


def 列表移除(列表: list, 条目: Any) -> 结果:
    新列表 = list(列表)
    if 条目 in 新列表:
        新列表.remove(条目)
    return _成功(新列表)


def 列表排序(列表: list, 倒序: bool = False) -> 结果:
    return _成功(sorted(列表, reverse=bool(倒序)))


def 列表查找(列表: list, 目标: Any) -> 结果:
    try:
        return _成功(列表.index(目标))
    except ValueError:
        return _成功(-1)


def 字典设置(字典: dict, 键: str, 值: Any) -> 结果:
    新字典 = dict(字典)
    新字典[键] = 值
    return _成功(新字典)


def 字典获取(字典: dict, 键: str, 默认值: Any = None) -> 结果:
    return _成功(字典.get(键, 默认值))


def 集合取并集(集合甲: list, 集合乙: list) -> 结果:
    return _成功(sorted(set(集合甲) | set(集合乙)))


def 集合取交集(集合甲: list, 集合乙: list) -> 结果:
    return _成功(sorted(set(集合甲) & set(集合乙)))


def 统计数量(列表: list) -> 结果:
    return _成功(len(列表))


def 按字段查找(列表: list, 字段名: str, 匹配值: Any, 直接匹配: bool = False) -> 结果:
    """按字段查找第一个匹配项；直接匹配=True 时忽略字段名直接比较元素。"""
    目标列表 = _校验列表(列表)
    for 项目 in 目标列表:
        if 直接匹配 or not 字段名:
            if 项目 == 匹配值:
                return _成功(项目)
        elif isinstance(项目, dict) and 项目.get(字段名) == 匹配值:
            return _成功(项目)
    return _成功(None)


def 过滤(列表: list, 字段名: str, 等于值: Any, 直接匹配: bool = False) -> 结果:
    """按字段过滤返回新列表；直接匹配=True 时直接比较元素。"""
    目标列表 = _校验列表(列表)
    结果列表 = []
    for 项目 in 目标列表:
        if 直接匹配 or not 字段名:
            if 项目 == 等于值:
                结果列表.append(项目)
        elif isinstance(项目, dict) and 项目.get(字段名) == 等于值:
            结果列表.append(项目)
    return _成功(结果列表)


def 映射转换(列表: list, 字段映射: dict) -> 结果:
    """按原字段到新字段映射重命名项目字段；返回新列表，原列表不变。"""
    目标列表 = _校验列表(列表)
    if not isinstance(字段映射, dict):
        return _失败("参数不合法", "字段映射必须是映射")
    if not 字段映射:
        return _成功(list(目标列表))
    结果列表 = []
    for 项目 in 目标列表:
        if isinstance(项目, dict):
            新项目 = {}
            for 原字段, 新字段 in 字段映射.items():
                if 原字段 in 项目:
                    新项目[新字段] = 项目[原字段]
            结果列表.append(新项目)
        else:
            结果列表.append(项目)
    return _成功(结果列表)


def 按字段排序(列表: list, 字段名: str, 升序: bool = True, 直接匹配: bool = False) -> 结果:
    """按字段或元素排序返回新列表；直接匹配=True 时按元素本身排序。"""
    目标列表 = _校验列表(列表)
    if 直接匹配 or not 字段名:
        return _成功(sorted(目标列表, reverse=not bool(升序)))
    for 项目 in 目标列表:
        if not isinstance(项目, dict) or 字段名 not in 项目:
            return _失败("参数不合法", f"列表项目缺少排序字段: {字段名}")
    return _成功(sorted(目标列表, key=lambda 项目: 项目[字段名], reverse=not bool(升序)))


def _校验列表(列表: Any) -> list:
    if not isinstance(列表, list):
        raise TypeError("列表必须是列表")
    return 列表
