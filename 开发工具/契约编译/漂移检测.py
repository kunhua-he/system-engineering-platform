"""漂移检测：契约与实现/产物的漂移拒绝。

拒绝：声明能力但没有实现；有实现但没有声明；参数顺序漂移；返回结构
漂移；错误码漂移；说明书与入口不一致；契约破坏但未升级主版本；
生成文件被手工修改。
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"


@dataclass
class 漂移结果:
    """一次漂移检测结果。"""

    问题列表: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 主版本号(版本: str) -> int:
    """提取主版本号（1.0.0 → 1）。"""
    try:
        return int(str(版本).split(".")[0])
    except (ValueError, AttributeError):
        return 0


def 检测声明无实现(契约: dict[str, Any], 实现目录: Path) -> str | None:
    """契约声明了能力但实现目录无对应实现。"""
    能力id = 契约.get("能力id", "")
    if not 能力id:
        return None
    实现名 = 能力id.split(".")[-1]
    for 文件 in 实现目录.rglob("*.py"):
        if 实现名 in 文件.name:
            return None
    return f"声明能力但无实现: {能力id}（{实现目录} 下未找到 {实现名}）"


def 检测实现无声明(实现目录: Path, 契约列表: list[dict]) -> list[str]:
    """实现文件中的函数没有对应契约声明。"""
    问题列表 = []
    声明能力表 = {契约.get("能力id", "").split(".")[-1] for 契约 in 契约列表}
    for 文件 in 实现目录.rglob("*.py"):
        if "pycache" in str(文件):
            continue
        内容 = 文件.read_text(encoding="utf-8")
        for 匹配 in re.finditer(r"^def ([一-龥\w]+)\(", 内容, re.MULTILINE):
            函数名 = 匹配.group(1)
            if 函数名.startswith("_"):
                continue
            if 函数名 not in 声明能力表:
                问题列表.append(f"有实现但无声明: {文件.name} 中的 {函数名}")
    return 问题列表


def 检测参数漂移(契约: dict[str, Any], 入口文件: Path) -> str | None:
    """契约参数与生成入口参数顺序/类型不一致（ast 解析函数签名+注解）。"""
    if not 入口文件.is_file():
        return f"入口文件缺失: {入口文件}"
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except SyntaxError as 错误:
        return f"入口文件语法错误: {错误}"
    契约参数 = [参数["名称"] for 参数 in 契约.get("参数", [])]
    函数定义 = next((节点 for 节点 in ast.walk(树) if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if 函数定义 is None:
        return "入口文件未找到函数定义"
    入口参数 = []
    入口注解表 = {}
    for 参数 in 函数定义.args.args:
        名称 = 参数.arg
        if 名称 not in ("无参数", "self", "cls"):
            入口参数.append(名称)
        if 参数.annotation is not None:
            try:
                入口注解表[名称] = ast.unparse(参数.annotation)
            except TypeError:
                入口注解表[名称] = ""
    if 入口参数 != 契约参数:
        return f"参数顺序漂移: 契约 {契约参数} ≠ 入口 {入口参数}"
    # 类型漂移：契约类型 vs 入口注解（文本=str/整数=int/布尔=bool/列表=list/字典=dict）
    类型映射 = {"文本": "str", "整数": "int", "布尔": "bool", "列表": "list", "字典": "dict"}
    for 参数 in 契约.get("参数", []):
        名称 = 参数["名称"]
        契约类型 = 参数.get("类型", "")
        期望注解 = 类型映射.get(契约类型, "")
        实际注解 = 入口注解表.get(名称, "")
        if 期望注解 and 实际注解 and 期望注解 != 实际注解:
            return f"参数类型漂移: {名称} 契约类型 {契约类型} ≠ 入口注解 {实际注解}"
    return None


def 检测返回漂移(契约: dict[str, Any], 实现文件: Path) -> str | None:
    """返回结构漂移：实现返回值与契约 返回 字段不一致（ast 分析返回路径）。"""
    if not 实现文件.is_file():
        return None
    try:
        树 = ast.parse(实现文件.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    返回类型 = 契约.get("返回", "普通返回")
    能力名 = 契约.get("能力id", "").split(".")[-1]
    函数定义 = next((节点 for 节点 in ast.walk(树)
                    if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and 节点.name == 能力名), None)
    if 函数定义 is None:
        return None
    # 返回路径分析：yield = 生成器（流式）；任务提交调用 = 任务句柄
    yield节点 = any(isinstance(节点, ast.Yield) for 节点 in ast.walk(函数定义))
    return节点 = any(isinstance(节点, ast.Return) for 节点 in ast.walk(函数定义))
    调用名表 = {节点.func.id for 节点 in ast.walk(函数定义)
                if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name)}
    异常处理 = any(isinstance(节点, ast.Try) for 节点 in ast.walk(函数定义))
    if 返回类型 == "任务句柄返回" and not (调用名表 & {"提交", "提交任务"}):
        return f"返回结构漂移: 契约声明任务句柄返回但实现未提交任务"
    if 返回类型 == "流式返回" and not yield节点:
        return f"返回结构漂移: 契约声明流式返回但实现无 yield 生成器"
    if 返回类型 == "普通返回" and not return节点:
        return f"返回结构漂移: 契约声明普通返回但实现无 return"
    if 返回类型 == "事件返回" and not (yield节点 or 调用名表 & {"追加事件", "emit"}):
        return f"返回结构漂移: 契约声明事件返回但实现无事件产出"
    if 契约.get("失败语义", "") == "异常上报" and not 异常处理:
        return f"失败语义漂移: 契约声明异常上报但实现无 try/except"
    return None


def 检测错误码漂移(契约: dict[str, Any], 实现文件: Path) -> list[str]:
    """错误码漂移：实现引用的错误码不在契约声明中。"""
    问题列表 = []
    if not 实现文件.is_file():
        return 问题列表
    内容 = 实现文件.read_text(encoding="utf-8")
    声明错误码 = set(契约.get("错误码", []))
    for 错误码 in re.findall(r'"(参数不合法|能力不存在|权限不足|外部不可访问|超时|内部错误|契约不兼容|资源泄漏)"', 内容):
        if 错误码 not in 声明错误码:
            问题列表.append(f"错误码漂移: 实现引用 {错误码} 但契约未声明（{实现文件.name}）")
    return 问题列表


def 检测说明书一致(契约: dict[str, Any], 说明书文件: Path) -> str | None:
    """说明书与入口不一致：说明书缺参数/错误码/版本。"""
    if not 说明书文件.is_file():
        return f"说明书缺失: {说明书文件}"
    内容 = 说明书文件.read_text(encoding="utf-8")
    if 契约.get("版本") and 契约["版本"] not in 内容:
        return f"说明书与契约不一致: 缺少版本 {契约['版本']}"
    for 参数 in 契约.get("参数", []):
        if 参数["名称"] not in 内容:
            return f"说明书与入口不一致: 缺少参数 {参数['名称']}"
    for 错误码 in 契约.get("错误码", [])[:3]:
        if 错误码 not in 内容:
            return f"说明书与入口不一致: 缺少错误码 {错误码}"
    return None


def 检测契约升级(旧契约: dict, 新契约: dict) -> str | None:
    """契约破坏但未升级主版本。"""
    旧主版 = 主版本号(旧契约.get("版本", "0.0.0"))
    新主版 = 主版本号(新契约.get("版本", "0.0.0"))
    破坏原因 = 检测破坏(旧契约, 新契约)
    if 破坏原因 and 新主版 <= 旧主版:
        return f"契约破坏但未升级主版本: {破坏原因}（{旧契约.get('版本')} → {新契约.get('版本')}）"
    return None


def 检测破坏(旧契约: dict, 新契约: dict) -> str | None:
    """检测破坏性变更。"""
    旧参数 = {参数["名称"]: 参数 for 参数 in 旧契约.get("参数", [])}
    新参数 = {参数["名称"]: 参数 for 参数 in 新契约.get("参数", [])}
    for 名称, 参数 in 旧参数.items():
        if 名称 not in 新参数:
            return f"删除参数: {名称}"
        if 参数.get("必填", True) and not 新参数[名称].get("必填", True):
            return f"必填参数改为可选（非破坏）"
        if not 参数.get("必填", True) and 新参数[名称].get("必填", True):
            return f"可选参数改为必填: {名称}"
    for 名称 in 新参数:
        if 名称 not in 旧参数:
            return f"增加参数（非破坏）"
    旧返回 = 旧契约.get("返回", "普通返回")
    新返回 = 新契约.get("返回", "普通返回")
    if 旧返回 != 新返回:
        return f"返回结构变更: {旧返回} → {新返回}"
    旧错误码 = set(旧契约.get("错误码", []))
    新错误码 = set(新契约.get("错误码", []))
    for 错误码 in 旧错误码 - 新错误码:
        return f"删除错误码: {错误码}"
    return None


def 检测生成文件被改(产物目录: Path) -> list[str]:
    """生成文件被手工修改：缺少生成标记的文件报告。"""
    问题列表 = []
    for 文件 in 产物目录.rglob("*"):
        if 文件.suffix in (".py", ".js", ".md") and 文件.is_file():
            内容 = 文件.read_text(encoding="utf-8")
            if 生成标记 not in 内容 and 文件.name not in ("能力搜索数据.json", "Agent查询数据.json"):
                问题列表.append(f"生成文件被手工修改: {文件.name}（缺少生成标记）")
    return 问题列表


def 检测能力定义漂移(包目录: Path) -> list[str]:
    """能力定义 → 生成物一致性：从能力定义重编译并与现有生成物对比。

    拒绝：能力定义缺失行为字段；生成物被手工篡改；生成物与能力定义不一致；
    有生成物但无能力定义（应重新编译）；有包声明但无能力定义。
    """
    import sys
    from pathlib import Path as 路径

    问题列表 = []
    定义文件 = 包目录 / "能力定义.json"
    if not 定义文件.is_file():
        # 无能力定义：若包声明存在则必须提示迁移
        声明文件 = 包目录 / "包声明.json"
        if 声明文件.is_file():
            问题列表.append(f"存在包声明但无能力定义（需迁移到唯一事实源）: {包目录}")
        return 问题列表
    # 加入平台根以导入编译器
    平台根 = str(包目录.resolve().parents[1])
    if 平台根 not in sys.path:
        sys.path.insert(0, 平台根)
    from 开发工具.契约编译.能力定义编译器 import (
        生成Agent数据, 生成包声明, 生成能力契约, 生成注册入口,
        生成搜索数据, 生成验证场景引用, 读取能力定义, 校验能力定义,
    )
    try:
        定义 = 读取能力定义(定义文件)
    except json.JSONDecodeError as 错误:
        问题列表.append(f"能力定义 JSON 解析失败: {定义文件}：{错误}")
        return 问题列表
    结构问题 = 校验能力定义(定义)
    问题列表.extend(f"能力定义结构: {问题}" for 问题 in 结构问题)
    if 结构问题:
        return 问题列表
    声明文件 = 包目录 / "包声明.json"
    依赖 = []
    包id = ""
    包名称 = ""
    包类型 = "支持库"
    实现模块 = ""
    if 声明文件.is_file():
        try:
            声明 = json.loads(声明文件.read_text(encoding="utf-8"))
            包id = 声明.get("包id", "")
            包名称 = 声明.get("名称", "")
            包类型 = 声明.get("类型", "支持库")
            依赖 = 声明.get("依赖", [])
        except json.JSONDecodeError:
            问题列表.append(f"包声明 JSON 解析失败: {声明文件}")
    # 与生成物对比（重编译 → 摘要一致）
    期望契约 = json.loads(生成能力契约(定义))
    契约文件 = 包目录 / "能力契约" / "参数契约.json"
    if 契约文件.is_file():
        try:
            实际契约 = json.loads(契约文件.read_text(encoding="utf-8"))
            if 实际契约 != 期望契约:
                问题列表.append(f"能力契约与能力定义不一致（需重新编译）: {包目录}")
        except json.JSONDecodeError:
            问题列表.append(f"能力契约 JSON 解析失败: {契约文件}")
    else:
        问题列表.append(f"能力契约缺失（需重新编译）: {契约文件}")
    # 注册入口含生成标记（或手写入口含 注册能力 → 合法）
    入口文件 = 包目录 / "__init__.py"
    if 入口文件.is_file():
        内容 = 入口文件.read_text(encoding="utf-8")
        if 生成标记 not in 内容 and "def 注册能力" not in 内容:
            问题列表.append(f"注册入口未由编译器生成（缺少生成标记且无注册能力）: {入口文件}")
    else:
        问题列表.append(f"注册入口缺失: {入口文件}")
    return 问题列表


def 全面漂移检测(*, 契约: dict[str, Any], 实现目录: Path,
                  入口文件: Path, 说明书文件: Path,
                  旧契约: dict[str, Any] | None = None) -> 漂移结果:
    """执行全部漂移检测。"""
    结果 = 漂移结果()
    # 1. 声明能力但没有实现
    声明无实现 = 检测声明无实现(契约, 实现目录)
    if 声明无实现:
        结果.问题列表.append(声明无实现)
    # 2. 参数顺序漂移
    参数漂移 = 检测参数漂移(契约, 入口文件)
    if 参数漂移:
        结果.问题列表.append(参数漂移)
    # 3. 返回结构漂移
    返回漂移 = 检测返回漂移(契约, 实现目录 / f"{契约.get('能力id', '').split('.')[-1]}.py")
    if 返回漂移:
        结果.问题列表.append(返回漂移)
    # 4. 错误码漂移
    错误码漂移 = 检测错误码漂移(契约, 实现目录 / f"{契约.get('能力id', '').split('.')[-1]}.py")
    结果.问题列表.extend(错误码漂移)
    # 5. 说明书与入口不一致
    说明书问题 = 检测说明书一致(契约, 说明书文件)
    if 说明书问题:
        结果.问题列表.append(说明书问题)
    # 6. 契约破坏但未升级主版本
    if 旧契约 is not None:
        升级问题 = 检测契约升级(旧契约, 契约)
        if 升级问题:
            结果.问题列表.append(升级问题)
    return 结果
