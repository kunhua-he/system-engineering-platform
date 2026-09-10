"""原子能力实现（不对外暴露，只经包级中文入口调用）。

全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失或类型非法
返回 参数不合法，不抛出异常、不以成功形状伪装失败。原容器一律不变，
返回新容器。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="数据集合")


def 列表添加(列表: list = None, 条目: Any = None) -> 结果:
    """追加条目并返回新列表（原列表不变）。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    return _成功([*列表, 条目])


def 列表移除(列表: list = None, 条目: Any = None) -> 结果:
    """移除首个匹配条目并返回新列表（原列表不变）。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    新列表 = list(列表)
    if 条目 in 新列表:
        新列表.remove(条目)
    return _成功(新列表)


def 列表排序(列表: list = None, 倒序: bool = False) -> 结果:
    """排序列表并返回新列表。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    try:
        return _成功(sorted(列表, reverse=bool(倒序)))
    except TypeError as 错误:
        return _失败("参数不合法", f"列表元素不可比较: {错误}")


def 列表查找(列表: list = None, 目标: Any = None) -> 结果:
    """返回首个匹配条目索引（未找到返回 -1）。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    try:
        return _成功(列表.index(目标))
    except ValueError:
        return _成功(-1)


def 字典设置(字典: dict = None, 键: str = None, 值: Any = None) -> 结果:
    """设置键值并返回新字典（原字典不变）。"""
    if not isinstance(字典, dict):
        return _失败("参数不合法", "字典必须是映射")
    if 键 is None:
        return _失败("参数不合法", "键不能为空")
    新字典 = dict(字典)
    新字典[键] = 值
    return _成功(新字典)


def 字典获取(字典: dict = None, 键: str = None, 默认值: Any = None) -> 结果:
    """获取键值（键不存在返回默认值）。"""
    if not isinstance(字典, dict):
        return _失败("参数不合法", "字典必须是映射")
    if 键 is None:
        return _失败("参数不合法", "键不能为空")
    return _成功(字典.get(键, 默认值))


def 集合取并集(集合甲: list = None, 集合乙: list = None) -> 结果:
    """返回两个列表的去重并集（排序稳定）。"""
    if not isinstance(集合甲, list) or not isinstance(集合乙, list):
        return _失败("参数不合法", "集合甲与集合乙必须是列表")
    return _成功(sorted(set(集合甲) | set(集合乙)))


def 集合取交集(集合甲: list = None, 集合乙: list = None) -> 结果:
    """返回两个列表的去重交集（排序稳定）。"""
    if not isinstance(集合甲, list) or not isinstance(集合乙, list):
        return _失败("参数不合法", "集合甲与集合乙必须是列表")
    return _成功(sorted(set(集合甲) & set(集合乙)))


def 统计数量(列表: list = None) -> 结果:
    """返回列表条目数量。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    return _成功(len(列表))


def 按字段查找(列表: list = None, 字段名: str = None, 匹配值: Any = None,
               直接匹配: bool = False) -> 结果:
    """按字段查找第一个匹配项；直接匹配=True 时忽略字段名直接比较元素。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    for 项目 in 列表:
        if 直接匹配 or not 字段名:
            if 项目 == 匹配值:
                return _成功(项目)
        elif isinstance(项目, dict) and 项目.get(字段名) == 匹配值:
            return _成功(项目)
    return _成功(None)


def 过滤(列表: list = None, 字段名: str = None, 等于值: Any = None,
         直接匹配: bool = False) -> 结果:
    """按字段过滤返回新列表；直接匹配=True 时直接比较元素。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    结果列表 = []
    for 项目 in 列表:
        if 直接匹配 or not 字段名:
            if 项目 == 等于值:
                结果列表.append(项目)
        elif isinstance(项目, dict) and 项目.get(字段名) == 等于值:
            结果列表.append(项目)
    return _成功(结果列表)


def 映射转换(列表: list = None, 字段映射: dict = None) -> 结果:
    """按原字段到新字段映射重命名项目字段；返回新列表，原列表不变。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    if not isinstance(字段映射, dict):
        return _失败("参数不合法", "字段映射必须是映射")
    if not 字段映射:
        return _成功(list(列表))
    结果列表 = []
    for 项目 in 列表:
        if isinstance(项目, dict):
            新项目 = {}
            for 原字段, 新字段 in 字段映射.items():
                if 原字段 in 项目:
                    新项目[新字段] = 项目[原字段]
            结果列表.append(新项目)
        else:
            结果列表.append(项目)
    return _成功(结果列表)


def 按字段排序(列表: list = None, 字段名: str = None, 升序: bool = True,
               直接匹配: bool = False) -> 结果:
    """按字段或元素排序返回新列表；直接匹配=True 时按元素本身排序。"""
    if not isinstance(列表, list):
        return _失败("参数不合法", "列表必须是列表")
    if 直接匹配 or not 字段名:
        try:
            return _成功(sorted(列表, reverse=not bool(升序)))
        except TypeError as 错误:
            return _失败("参数不合法", f"列表元素不可比较: {错误}")
    for 项目 in 列表:
        if not isinstance(项目, dict) or 字段名 not in 项目:
            return _失败("参数不合法", f"列表项目缺少排序字段: {字段名}")
    return _成功(sorted(列表, key=lambda 项目: 项目[字段名], reverse=not bool(升序)))

def 展平字典(数据: dict = None, 分隔符: str = ".", 保留扁平键: bool = True, 最大深度: int = 32) -> 结果:
    """把嵌套字典展平为单层字典。

    键拼接规则：嵌套路径用 分隔符 连接（如 a.b.c）；保留扁平键=True 时
    同时写入末级键名（与 V3 既有 展平metrics 行为一致）。
    同名键后写覆盖。最大深度防环。
    """
    if not isinstance(数据, dict):
        return 结果.失败("参数不合法", "数据必须是字典型", 来源="数据集合")
    分隔 = 分隔符 if isinstance(分隔符, str) and 分隔符 else "."
    展平: dict = {}

    def _递归(当前: dict, 前缀: str, 深度: int) -> None:
        if 深度 > 最大深度:
            return
        for 键, 值 in 当前.items():
            名 = str(键)
            完整键 = f"{前缀}{分隔}{名}" if 前缀 else 名
            展平[完整键] = 值
            if 保留扁平键:
                展平[名] = 值
            if isinstance(值, dict):
                _递归(值, 完整键, 深度 + 1)

    _递归(数据, "", 0)
    return 结果.成功结果({"展平结果": 展平, "键数": len(展平)})
