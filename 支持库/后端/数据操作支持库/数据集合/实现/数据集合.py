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


def 集合取并集(集合1: list = None, 集合2: list = None) -> 结果:
    """返回两个列表的去重并集（排序稳定）。"""
    if not isinstance(集合1, list) or not isinstance(集合2, list):
        return _失败("参数不合法", "集合1与集合2必须是列表")
    return _成功(sorted(set(集合1) | set(集合2)))


def 集合取交集(集合1: list = None, 集合2: list = None) -> 结果:
    """返回两个列表的去重交集（排序稳定）。"""
    if not isinstance(集合1, list) or not isinstance(集合2, list):
        return _失败("参数不合法", "集合1与集合2必须是列表")
    return _成功(sorted(set(集合1) & set(集合2)))


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


def _取非负整数(值: Any, 默认: int) -> int:
    """把入参安全取成非负整数；非法或布尔值回落到默认值。"""
    if isinstance(值, bool) or not isinstance(值, (int, float)):
        return 默认
    try:
        return max(0, int(值))
    except (TypeError, ValueError):
        return 默认


def 展平结构条目(数据: Any = None, 分隔符: str = ".", 列表索引格式: str = "[{索引}]",
                 最大深度: int = 10, 最大条目数: int = 3000,
                 超深标记: str = "(已超最大深度)", 根路径: str = "$") -> 结果:
    """把任意嵌套结构展平为「路径 + 值」的有序条目列表。

    字典键用 分隔符 连接；列表元素路径用 列表索引格式（`{索引}` 为占位符）；
    容器超过 最大深度 时产出一条 超深=真 的标记条目；标量不分深度直接产出。
    总条目数 计全部（含被截断部分），条目列表 最多 最大条目数 条。
    """
    分隔 = 分隔符 if isinstance(分隔符, str) and 分隔符 else "."
    索引格式 = 列表索引格式 if isinstance(列表索引格式, str) and 列表索引格式 else "[{索引}]"
    根 = 根路径 if isinstance(根路径, str) and 根路径 else "$"
    标记 = 超深标记 if isinstance(超深标记, str) else "(已超最大深度)"
    深度上限 = _取非负整数(最大深度, 10)
    条目上限 = _取非负整数(最大条目数, 3000)
    条目列表: list = []
    状态 = {"总条目数": 0, "已截断": False}

    def 添加(路径: str, 值: Any, 超深: bool = False) -> None:
        状态["总条目数"] += 1
        if len(条目列表) < 条目上限:
            条目列表.append({"路径": 路径, "值": 值, "超深": 超深})
        else:
            状态["已截断"] = True

    def 遍历(值: Any, 路径: str, 深度: int) -> None:
        if 深度 > 深度上限:
            添加(路径 or 根, 标记, True)
            return
        if isinstance(值, dict):
            for 键, 项 in 值.items():
                子路径 = f"{路径}{分隔}{键}" if 路径 else str(键)
                if isinstance(项, (dict, list)):
                    遍历(项, 子路径, 深度 + 1)
                else:
                    添加(子路径, 项)
            return
        if isinstance(值, list):
            for 索引, 项 in enumerate(值):
                段 = 索引格式.replace("{索引}", str(索引))
                子路径 = f"{路径}{段}" if 路径 else 段
                if isinstance(项, (dict, list)):
                    遍历(项, 子路径, 深度 + 1)
                else:
                    添加(子路径, 项)
            return
        添加(路径 or 根, 值)

    遍历(数据, "", 0)
    return 结果.成功结果({
        "条目列表": 条目列表,
        "总条目数": 状态["总条目数"],
        "已截断": 状态["已截断"],
    })


def 规范化条目指纹(条目列表: Any = None, 字段顺序: list = None,
                   条目分隔符: str = "||", 字段分隔符: str = "|",
                   缺失文本: str = "", 排序: bool = True) -> 结果:
    """把条目集合归一化为可比较的指纹文本（用于两侧结构一致性判定）。

    列表型：逐条按 字段顺序 取值，非字典型条目跳过；
    字典型：每个键为一条目，键名作为第一个字段的值，其余字段从值字典取。
    字段缺失或为 空值 → 缺失文本；顺序=真 时条目排序后再连接。
    """
    if not isinstance(字段顺序, list) or not 字段顺序:
        return _失败("参数不合法", "字段顺序必须是非空列表")
    顺序 = [str(项) for 项 in 字段顺序]
    条目分隔 = 条目分隔符 if isinstance(条目分隔符, str) else "||"
    字段分隔 = 字段分隔符 if isinstance(字段分隔符, str) else "|"
    缺失 = 缺失文本 if isinstance(缺失文本, str) else ""

    def 取文本(容器: dict, 键: str) -> str:
        值 = 容器.get(键)
        return 缺失 if 值 is None else str(值)

    指纹表: list = []
    if isinstance(条目列表, list):
        for 条目 in 条目列表:
            if not isinstance(条目, dict):
                continue
            指纹表.append(字段分隔.join(取文本(条目, 键) for 键 in 顺序))
    elif isinstance(条目列表, dict):
        for 键, 详情 in 条目列表.items():
            容器 = 详情 if isinstance(详情, dict) else {}
            指纹表.append(字段分隔.join([str(键)] + [取文本(容器, 字段) for 字段 in 顺序[1:]]))
    else:
        return _失败("参数不合法", "条目列表必须是列表或字典")
    if 排序:
        指纹表.sort()
    return 结果.成功结果({"指纹": 条目分隔.join(指纹表), "条目数": len(指纹表)})
