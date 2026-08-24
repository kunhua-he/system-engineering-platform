"""轻代码页面模型的唯一结构校验器。

所有保存、预览和编译入口都必须先经过这里，避免设计态与制品态各自接受
不同的页面结构。组件目录是支持库的事实源，页面 JSON 只保存实例和绑定。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 开发工具.项目编译.正式包索引 import 构建索引

根目录 = Path(__file__).resolve().parents[2]
组件目录文件 = 根目录 / "支持库" / "前端" / "组件控件" / "组件目录" / "组件目录.json"


def _读取组件目录() -> dict[str, dict[str, Any]]:
    try:
        数据 = json.loads(组件目录文件.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"组件目录不可读取: {错误}") from 错误
    项 = 数据.get("组件类型") if isinstance(数据, dict) else None
    if not isinstance(项, list):
        raise ValueError("组件目录缺少组件类型列表")
    结果: dict[str, dict[str, Any]] = {}
    for 条目 in 项:
        if not isinstance(条目, dict) or not str(条目.get("类型", "")).strip():
            raise ValueError("组件目录存在无效组件条目")
        结果[str(条目["类型"])] = 条目
        别名 = str(条目.get("别名", "")).strip()
        if 别名:
            结果[别名] = 条目
    return 结果


def _读取能力目录() -> set[str]:
    """读取公开能力声明；页面绑定只能引用已登记的唯一能力。"""
    return set(构建索引(根目录)["能力所有者"])


def _读取能力契约() -> dict[str, dict[str, Any]]:
    结果: dict[str, dict[str, Any]] = {}
    索引 = 构建索引(根目录)
    包表 = [*索引["支持库"].values(), *索引["模块库"].values()]
    for 包目录, _ in 包表:
        文件 = 包目录 / "能力契约" / "参数契约.json"
        if 文件.is_file():
            try:
                数据 = json.loads(文件.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
                raise ValueError(f"能力契约不可读取: {文件}: {错误}") from 错误
            for 条目 in 数据.get("能力契约", []) if isinstance(数据, dict) else []:
                if isinstance(条目, dict) and 条目.get("能力id"):
                    能力id = str(条目["能力id"])
                    if 能力id in 结果 and 结果[能力id] != 条目:
                        raise ValueError(f"能力契约重复且不一致: {能力id}")
                    结果[能力id] = 条目
    return 结果


def _属性类型匹配(值: Any, 类型: str) -> bool:
    return {
        "文本型": isinstance(值, str), "整数型": isinstance(值, int) and not isinstance(值, bool),
        "逻辑型": isinstance(值, bool), "字典型": isinstance(值, dict), "列表型": isinstance(值, list),
    }.get(类型, True)


def 校验页面(页面: dict[str, Any]) -> dict[str, Any]:
    """校验并返回深拷贝后的规范页面；任何结构问题都 fail-closed。"""
    if not isinstance(页面, dict):
        raise ValueError("页面定义必须是对象")
    for 字段 in ("页面id", "标题", "路由", "组件列表"):
        if not str(页面.get(字段, "")).strip() and 字段 != "组件列表":
            raise ValueError(f"页面字段不能为空: {字段}")
    组件列表 = 页面.get("组件列表")
    if not isinstance(组件列表, list):
        raise ValueError("组件列表必须是数组")
    目录 = _读取组件目录()
    能力目录 = _读取能力目录()
    能力契约 = _读取能力契约()
    规范: dict[str, Any] = json.loads(json.dumps(页面, ensure_ascii=False))
    规范组件 = 规范["组件列表"]
    对象表: dict[str, dict[str, Any]] = {}
    组件表: dict[str, dict[str, Any]] = {}
    for 索引, 组件 in enumerate(规范组件, 1):
        if not isinstance(组件, dict):
            raise ValueError(f"第 {索引} 个组件必须是对象")
        组件id = str(组件.get("组件id", "")).strip()
        类型 = str(组件.get("类型", "")).strip()
        对象id = str(组件.get("对象id") or 组件id).strip()
        if not 组件id or not 类型 or not 对象id:
            raise ValueError(f"第 {索引} 个组件缺少组件id、对象id或类型")
        if 类型 not in 目录:
            raise ValueError(f"未知组件类型: {类型}")
        if 组件id in 组件表:
            raise ValueError(f"组件id重复: {组件id}")
        if 对象id in 对象表:
            raise ValueError(f"对象id重复: {对象id}")
        属性 = 组件.get("属性", {})
        if not isinstance(属性, dict):
            raise ValueError(f"组件 {组件id} 的属性必须是对象")
        默认属性 = 目录[类型].get("默认属性", {})
        for 名称, 值 in 属性.items():
            if 名称 not in 默认属性 and 名称 not in {"能力id", "参数模板", "绑定", "结果组件id"}:
                raise ValueError(f"组件 {组件id} 不支持属性: {名称}")
            if 名称 in {"左", "上", "宽度", "高度"} and (not isinstance(值, int) or isinstance(值, bool) or 值 < 0):
                raise ValueError(f"组件 {组件id} 属性 {名称} 必须是非负整数")
            if 名称 in {"只读", "禁用", "可见"} and not isinstance(值, bool):
                raise ValueError(f"组件 {组件id} 属性 {名称} 必须是逻辑型")
        属性能力id = 属性.get("能力id", "")
        if 属性能力id:
            if not isinstance(属性能力id, str) or 属性能力id.strip() not in 能力目录:
                raise ValueError(f"组件 {组件id} 属性能力不存在: {属性能力id}")
            模板 = 属性.get("参数模板", {})
            契约 = 能力契约.get(属性能力id.strip())
            if 契约 is None:
                raise ValueError(f"组件 {组件id} 属性能力契约不存在: {属性能力id}")
            已知参数 = {str(参数.get("名称")) for 参数 in 契约.get("参数", []) if isinstance(参数, dict)}
            if not isinstance(模板, dict) or set(模板) - 已知参数:
                raise ValueError(f"组件 {组件id} 属性参数模板包含未知参数")
        事件 = 组件.get("事件", [])
        if not isinstance(事件, list):
            raise ValueError(f"组件 {组件id} 的事件必须是数组")
        支持事件 = set(目录[类型].get("事件", []))
        规范事件: list[dict[str, Any]] = []
        已绑定事件: set[str] = set()
        for 事件项 in 事件:
            if isinstance(事件项, str):
                事件项 = {"名称": 事件项, "能力id": ""}
            if not isinstance(事件项, dict) or not str(事件项.get("名称", "")).strip():
                raise ValueError(f"组件 {组件id} 存在无效事件")
            名称 = str(事件项["名称"])
            if 名称 not in 支持事件:
                raise ValueError(f"组件 {组件id} 不支持事件: {名称}")
            if 名称 in 已绑定事件:
                raise ValueError(f"组件 {组件id} 重复绑定事件: {名称}")
            已绑定事件.add(名称)
            能力id = 事件项.get("能力id", "")
            if 能力id and not isinstance(能力id, str):
                raise ValueError(f"组件 {组件id} 事件能力id必须是文本型")
            if isinstance(能力id, str) and 能力id.strip() and 能力id.strip() not in 能力目录:
                raise ValueError(f"组件 {组件id} 事件能力不存在: {能力id.strip()}")
            if isinstance(能力id, str) and 能力id.strip():
                契约 = 能力契约.get(能力id.strip())
                模板 = 事件项.get("参数模板", {})
                if 契约 is None:
                    raise ValueError(f"组件 {组件id} 事件能力契约不存在: {能力id.strip()}")
                已知参数 = {str(参数.get("名称")) for 参数 in 契约.get("参数", []) if isinstance(参数, dict)}
                未知参数 = set(模板) - 已知参数
                if 未知参数:
                    raise ValueError(f"组件 {组件id} 事件参数模板包含未知参数: {sorted(未知参数)}")
            if "参数模板" in 事件项 and not isinstance(事件项["参数模板"], dict):
                raise ValueError(f"组件 {组件id} 事件参数模板必须是字典型")
            规范事件.append(事件项)
        组件["事件"] = 规范事件
        对象表[对象id] = 组件
        组件表[组件id] = 组件
    容器类型 = {类型 for 类型, 条目 in 目录.items() if 条目.get("事件") is not None and 类型 == "容器"}
    for 组件id, 组件 in 组件表.items():
        父id = 组件.get("父组件id")
        if 父id in (None, ""):
            continue
        父id = str(父id)
        父 = 组件表.get(父id)
        if 父 is None:
            raise ValueError(f"组件 {组件id} 的父组件不存在: {父id}")
        声明父对象id = 组件.get("父对象id")
        if 声明父对象id not in (None, "") and str(声明父对象id) != str(父.get("对象id") or 父id):
            raise ValueError(f"组件 {组件id} 的父对象id与父组件不一致: {声明父对象id}")
        if 父.get("类型") not in 容器类型:
            raise ValueError(f"组件 {组件id} 的父组件不是容器: {父id}")
        已见: set[str] = set()
        当前 = 组件id
        while 当前:
            if 当前 in 已见:
                raise ValueError(f"组件父子关系存在环: {组件id}")
            已见.add(当前)
            当前父 = 组件表[当前].get("父组件id")
            当前 = str(当前父) if 当前父 not in (None, "") else ""
    return 规范
