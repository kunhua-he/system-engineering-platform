"""漂移检测：契约与实现/产物的漂移拒绝。

全面漂移检测 实际执行：声明能力但没有实现（按实现目录内文件名匹配）、
参数顺序/类型漂移、返回结构漂移、错误码漂移（该两项需调用方传入 实现文件；
未传入且按 实现目录/{能力id末段}.py 猜不中时，显式登记「未执行」而非静默
通过——本仓实现文件是「一包一文件」，猜路径命中率实测为 0）、说明书与入口
不一致、契约破坏但未升级主版本。

其余检测器（检测实现无声明 / 检测生成文件被改 / 检测完整性摘要格式 /
检测能力定义漂移 / 检测注册口径漂移）供调用方按场景单独选用，不并入
全面漂移检测——检测实现无声明 见其文档串（函数级粒度无法区分能力入口与内部
辅助函数）；注册口径 见 检测注册口径漂移（按包整包比对，且必须先按
契约.归一注册口径 归一口径，否则约 300 条「注册 `结果` / 契约 `结果型`」的
写法噪声会把真问题淹掉）。
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 公共契约.基础类型.类型表 import 正式类型表
from 公共契约.能力契约.契约 import 归一注册口径

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"


class _未解析哨兵类型:
    """AST 静态求值的「不可判定」哨兵类型（与 None / 空串等合法值区分开）。"""


未解析哨兵 = _未解析哨兵类型()
"""不可静态判定的表达式的唯一哨兵值（单例，用 `is` 比较）。"""


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
    """实现文件中的函数没有对应契约声明。

    **不要并入 全面漂移检测**：本实现按「实现目录下每个公开函数名 == 某能力id
    的末段」判定，而真实支持库的实现模块普遍带内部辅助函数（测得的样本：
    100 个含实现目录的包中 54 个包共报出 237 条，如 余弦相似度/主循环/
    校验OOXML安全/加载提供者，全是合法内部函数）。函数级粒度无法区分
    「能力入口」与「辅助函数」，直接启用等于给正式包制造大面积假红。
    要真做这项，必须按注册映射（__init__ 的 注册能力）反查能力入口。
    """
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
    # 类型漂移：契约类型 vs 入口注解。短类型不再作为正式契约输入。
    类型映射 = {"文本型": "str", "整数型": "int", "长整数型": "int",
              "逻辑型": "bool", "列表型": "list", "字典型": "dict",
              "字节集型": "bytes", "双精度数型": "float",
              "单精度数型": "float"}
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
    """契约破坏但未升级主版本（只对真破坏变更要求升主版本）。"""
    旧主版 = 主版本号(旧契约.get("版本", "0.0.0"))
    新主版 = 主版本号(新契约.get("版本", "0.0.0"))
    破坏原因 = 检测破坏(旧契约, 新契约)
    if 破坏原因 and 新主版 <= 旧主版:
        return f"契约破坏但未升级主版本: {破坏原因}（{旧契约.get('版本')} → {新契约.get('版本')}）"
    return None


def 检测非破坏变更(旧契约: dict, 新契约: dict) -> list[str]:
    """兼容变更清单（非破坏，不需升主版本），供调用方记录。"""
    变更: list[str] = []
    旧参数 = {参数["名称"]: 参数 for 参数 in 旧契约.get("参数", [])}
    新参数 = {参数["名称"]: 参数 for 参数 in 新契约.get("参数", [])}
    for 名称, 参数 in 旧参数.items():
        if 名称 in 新参数 and 参数.get("必填", True) and not 新参数[名称].get("必填", True):
            变更.append(f"必填参数改为可选（非破坏）: {名称}")
    for 名称, 参数 in 新参数.items():
        if 名称 not in 旧参数 and not 参数.get("必填", True):
            变更.append(f"增加参数（非破坏）: {名称}")
    for 错误码 in sorted(set(新契约.get("错误码", [])) - set(旧契约.get("错误码", []))):
        变更.append(f"新增错误码（非破坏）: {错误码}")
    return 变更


def 检测破坏(旧契约: dict, 新契约: dict) -> str | None:
    """检测破坏性变更（非破坏变更不算破坏，见 检测非破坏变更）。

    判据与唯一权威 `运行核心/加载器/版本系统/契约兼容.检查契约兼容` 同口径：
    删除参数、可选参数改为必填、新增必填参数、返回结构变更、删除错误码 才是破坏；
    「必填参数改为可选」「增加可选参数」是非破坏变更。

    原实现把「必填参数改为可选（非破坏）」「增加参数（非破坏）」也当破坏返回，并把
    非破坏变更 return 得比后续检查更早 → 两类错误同时存在：①非破坏变更被上层
    `检测契约升级` 当破坏处理，要求升主版本（假报破坏）；②其后的「返回结构变更」
    「删除错误码」等真破坏被提前 return 掩盖（真破坏漏报）。现按真破坏判据逐项检查、
    中途不因非破坏变更短路。
    """
    旧参数 = {参数["名称"]: 参数 for 参数 in 旧契约.get("参数", [])}
    新参数 = {参数["名称"]: 参数 for 参数 in 新契约.get("参数", [])}
    for 名称, 参数 in 旧参数.items():
        if 名称 not in 新参数:
            return f"删除参数: {名称}"
        if not 参数.get("必填", True) and 新参数[名称].get("必填", True):
            return f"可选参数改为必填: {名称}"
    for 名称, 参数 in 新参数.items():
        if 名称 not in 旧参数 and 参数.get("必填", True):
            return f"新增必填参数: {名称}"
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


def 检测完整性摘要格式(包目录: Path) -> list[str]:
    """完整性摘要.json 必须为文件清单格式（拒绝旧'能力数'格式/缺文件清单）。"""
    问题列表 = []
    摘要路径 = 包目录 / "完整性摘要.json"
    if not 摘要路径.is_file():
        return 问题列表
    try:
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"完整性摘要.json 不是合法 JSON: {摘要路径}"]
    文件清单 = 摘要数据.get("文件清单")
    if not isinstance(文件清单, list) or not 文件清单:
        问题列表.append(f"完整性摘要.json 非文件清单格式（缺文件清单或为空）: {摘要路径}")
    if 摘要数据.get("摘要算法", "sha256") != "sha256":
        问题列表.append(f"完整性摘要.json 摘要算法不合法: {摘要数据.get('摘要算法')}")
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
    # 完整性摘要必须为文件清单格式（拒绝旧'能力数'格式漂移）
    问题列表.extend(检测完整性摘要格式(包目录))
    # 加入平台根以导入编译器
    平台根 = str(包目录.resolve().parents[1])
    if 平台根 not in sys.path:
        sys.path.insert(0, 平台根)
    from 开发工具.契约编译.能力定义编译器 import (
        生成Agent数据, 生成包声明, 生成能力契约, 生成注册入口,
        生成搜索数据, 读取能力定义, 校验能力定义,
    )
    from 开发工具.契约编译.聚合契约解析 import 读取原始
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
    # 口径必须与编译器一致（哲学第 1 条 3 项：一个事实源）：编译器是**非破坏性**生成——
    # 它按既有契约保留手写 `中文名称`/`名称`/自定义键、手写 `调用示例`，契约版本恒等于契约事实源。
    # 因此这里必须把**既有契约**传进去再比对；否则凡有手写保留键的包都会被误报成「需重新编译」。
    契约文件 = 包目录 / "能力契约" / "参数契约.json"
    期望契约 = json.loads(生成能力契约(定义, 读取原始(契约文件) if 契约文件.is_file() else None))
    if 契约文件.is_file():
        实际契约 = 读取原始(契约文件)
        if 实际契约 is None:
            问题列表.append(f"能力契约 JSON 解析失败: {契约文件}")
        elif 实际契约 != 期望契约:
            问题列表.append(f"能力契约与能力定义不一致（需重新编译）: {包目录}")
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


def _静态字面量(节点: ast.AST, 绑定: dict[str, Any], 深度: int = 0) -> Any:
    """把 AST 表达式求值为字面量；不可静态判定的返回 未解析哨兵。

    绑定表里既可能是字面量，也可能是**赋值语句的 AST 节点**（注册表四元组里含
    函数引用，预先整体求值必然失败，所以赋值只登记节点、按需解引用）。
    """
    if 深度 > 8:
        return 未解析哨兵
    if isinstance(节点, ast.Constant):
        return 节点.value
    if isinstance(节点, ast.Name):
        if 节点.id not in 绑定:
            return 未解析哨兵
        值 = 绑定[节点.id]
        if isinstance(值, ast.AST):
            return _静态字面量(值, 绑定, 深度 + 1)
        return 值
    if isinstance(节点, (ast.List, ast.Tuple)):
        值表 = []
        for 元素 in 节点.elts:
            值 = _静态字面量(元素, 绑定, 深度 + 1)
            if 值 is 未解析哨兵:
                return 未解析哨兵
            值表.append(值)
        return tuple(值表) if isinstance(节点, ast.Tuple) else 值表
    if isinstance(节点, ast.Dict):
        字典: dict[Any, Any] = {}
        for 键节点, 值节点 in zip(节点.keys, 节点.values):
            if 键节点 is None:
                return 未解析哨兵
            键 = _静态字面量(键节点, 绑定, 深度 + 1)
            值 = _静态字面量(值节点, 绑定, 深度 + 1)
            if 键 is 未解析哨兵 or 值 is 未解析哨兵:
                return 未解析哨兵
            字典[键] = 值
        return 字典
    if isinstance(节点, ast.Subscript):
        # `返回表[能力id]` 形态：先解析容器（多为模块内字面量表），再按键取值。
        容器 = _静态字面量(节点.value, 绑定, 深度 + 1)
        if 容器 is 未解析哨兵 or not isinstance(容器, (dict, list, tuple)):
            return 未解析哨兵
        键 = _静态字面量(节点.slice, 绑定, 深度 + 1)
        if 键 is 未解析哨兵:
            return 未解析哨兵
        try:
            return 容器[键]
        except (KeyError, IndexError, TypeError):
            return 未解析哨兵
    return 未解析哨兵


def _注册参数表(节点: ast.AST, 绑定: dict[str, Any]) -> list[dict[str, str]] | None:
    """注册 `参数=` 的四种实际写法 → [{名称,类型}]；不全静态可判定时返回 None。

    写法：① [{名称,类型}]；② [("名称","类型")]；③ ["名称", ...]（只有名）；
    ④ [{...} for 参数名, 类型 in 参数类型表]（列表推导 + 循环变量表）。
    """
    if isinstance(节点, ast.ListComp):
        return _列表推导参数表(节点, 绑定)
    值 = _静态字面量(节点, 绑定)
    if 值 is 未解析哨兵 or not isinstance(值, (list, tuple)):
        return None
    表: list[dict[str, str]] = []
    for 项 in 值:
        if isinstance(项, dict) and "名称" in 项:
            表.append({"名称": str(项.get("名称", "")), "类型": str(项.get("类型") or "")})
        elif isinstance(项, str):
            表.append({"名称": 项, "类型": ""})
        elif isinstance(项, tuple) and len(项) == 2:
            表.append({"名称": str(项[0]), "类型": str(项[1])})
        else:
            return None
    return 表


def _列表推导参数表(节点: ast.ListComp, 绑定: dict[str, Any]) -> list[dict[str, str]] | None:
    """`[{名称,类型} for 参数名, 类型 in 参数类型表]` 形态（前端描述型包装用）。"""
    if len(节点.generators) != 1:
        return None
    生成器 = 节点.generators[0]
    序列 = _静态字面量(生成器.iter, 绑定)
    if 序列 is 未解析哨兵 or not isinstance(序列, (list, tuple)):
        return None
    if isinstance(生成器.target, ast.Tuple):
        目标名 = [元素.id for 元素 in 生成器.target.elts if isinstance(元素, ast.Name)]
    elif isinstance(生成器.target, ast.Name):
        目标名 = [生成器.target.id]
    else:
        return None
    if not 目标名:
        return None
    表: list[dict[str, str]] = []
    for 元素 in 序列:
        子绑定 = dict(绑定)
        if isinstance(元素, (list, tuple)) and len(元素) == len(目标名):
            子绑定.update(dict(zip(目标名, 元素)))
        elif len(目标名) == 1:
            子绑定[目标名[0]] = 元素
        else:
            return None
        行 = _静态字面量(节点.elt, 子绑定)
        if isinstance(行, dict) and "名称" in 行:
            表.append({"名称": str(行.get("名称", "")), "类型": str(行.get("类型") or "")})
        elif isinstance(行, tuple) and len(行) == 2:
            表.append({"名称": str(行[0]), "类型": str(行[1])})
        else:
            return None
    return 表


def _收集注册调用(调用: ast.Call, 绑定: dict[str, Any], 表: dict[str, dict[str, Any]]) -> None:
    """从 注册表.注册(能力实现(...)) 调用里抽出注册口径。"""
    if isinstance(调用.func, ast.Name):
        函数名 = 调用.func.id
    elif isinstance(调用.func, ast.Attribute):
        函数名 = 调用.func.attr
    else:
        函数名 = ""
    关键字 = {关键字节点.arg: 关键字节点.value for 关键字节点 in 调用.keywords if 关键字节点.arg}
    if 函数名 == "注册":
        for 实参 in list(调用.args) + list(关键字.values()):
            if isinstance(实参, ast.Call):
                _收集注册调用(实参, 绑定, 表)
        return
    if 函数名 != "能力实现":
        return
    能力id = _静态字面量(关键字["能力id"], 绑定) if "能力id" in 关键字 else 未解析哨兵
    if not isinstance(能力id, str) or "." not in 能力id:
        return
    if "返回" not in 关键字:
        返回口径: str | None = ""      # 未传 返回 → 能力实现 默认空串，属真实空口径
    else:
        返回值 = _静态字面量(关键字["返回"], 绑定)
        返回口径 = 返回值 if isinstance(返回值, str) else None   # None=不可静态判定，跳过比对
    表[能力id] = {
        "返回": 返回口径,
        "参数": _注册参数表(关键字["参数"], 绑定) if "参数" in 关键字 else [],
    }


def _扫描注册语句(语句列表: list[ast.stmt], 绑定: dict[str, Any],
                表: dict[str, dict[str, Any]]) -> None:
    """按语句顺序维护名字绑定（赋值只登记节点），逐条抽出注册口径。

    `for 能力id, 函数, 参数表[, 返回类型|说明] in 表名:` 是仓库主流写法，且
    循环变量名各不相同（返回类型 / 返回 / 说明 / 参数名 / 参数类型表），所以必须
    按**位置绑定循环变量名**再解引用，不能假定第 4 项就是返回。
    """
    for 语句 in 语句列表:
        if isinstance(语句, ast.Assign) and len(语句.targets) == 1 \
                and isinstance(语句.targets[0], ast.Name):
            绑定[语句.targets[0].id] = 语句.value
        elif isinstance(语句, ast.For):
            序列节点: ast.AST = 语句.iter
            if isinstance(序列节点, ast.Name) and 序列节点.id in 绑定 \
                    and isinstance(绑定[序列节点.id], ast.AST):
                序列节点 = 绑定[序列节点.id]
            if isinstance(语句.target, ast.Tuple):
                目标名 = [元素.id for 元素 in 语句.target.elts
                         if isinstance(元素, ast.Name)]
            elif isinstance(语句.target, ast.Name):
                目标名 = [语句.target.id]
            else:
                目标名 = []
            元素表 = 序列节点.elts if isinstance(序列节点, ast.List) else None
            if 元素表 is None or len(目标名) < 2 or not 元素表:
                _扫描注册语句(语句.body, 绑定, 表)
                continue
            for 元素 in 元素表:
                子绑定 = dict(绑定)
                if isinstance(元素, ast.Tuple) and len(元素.elts) == len(目标名):
                    for 名, 值节点 in zip(目标名, 元素.elts):
                        子绑定[名] = 值节点
                elif isinstance(元素, ast.Dict):
                    for 键节点, 值节点 in zip(元素.keys, 元素.values):
                        键 = _静态字面量(键节点, 绑定) if 键节点 is not None else None
                        if isinstance(键, str):
                            子绑定[键] = 值节点
                _扫描注册语句(语句.body, 子绑定, 表)
        elif isinstance(语句, ast.If):
            _扫描注册语句(语句.body, dict(绑定), 表)
            _扫描注册语句(语句.orelse, dict(绑定), 表)
        elif isinstance(语句, ast.Expr) and isinstance(语句.value, ast.Call):
            _收集注册调用(语句.value, 绑定, 表)


def 读取注册口径(入口文件: Path) -> dict[str, dict[str, Any]]:
    """AST 抽取包入口 `注册能力` 的真实注册口径：能力id → {返回, 参数}。

    只静态解析，不导入实现模块（零副作用、零依赖）。仓库实测的三种数据流都覆盖：
    ① 四元组表 `("能力id", 函数, [参数表], "返回")`（循环变量名各异）；
    ② 三元组表 + 函数体内 `能力实现(..., 返回="结果")`；
    ③ inline `能力实现(能力id="…", 参数=[…], 返回="…")`。
    解析不出的（动态拼装）能力不进返回表，由 全仓注册口径统计 如实登记「未解析」。
    """
    if not 入口文件.is_file():
        return {}
    try:
        树 = ast.parse(入口文件.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
    表: dict[str, dict[str, Any]] = {}
    注册函数表 = [节点 for 节点 in ast.walk(树)
                if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == "注册能力"]
    if 注册函数表:
        for 函数 in 注册函数表:
            _扫描注册语句(函数.body, {}, 表)
    else:
        _扫描注册语句(树.body, {}, 表)
    return 表


def 读取契约口径(契约文件: Path) -> dict[str, dict[str, Any]]:
    """读 `能力契约/参数契约.json` → 能力id → {返回, 参数:[{名称,类型}]}。

    契约侧 返回 有两种写法：`{"类型": "结果型", ...}` 与纯文本串（结构描述），
    两者都归一成「口径名」再比对。
    """
    if not 契约文件.is_file():
        return {}
    try:
        数据 = json.loads(契约文件.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    表: dict[str, dict[str, Any]] = {}
    for 条目 in 数据.get("能力契约") or []:
        if not isinstance(条目, dict) or not 条目.get("能力id"):
            continue
        返回 = 条目.get("返回")
        返回口径 = str(返回.get("类型", "")) if isinstance(返回, dict) else str(返回 or "")
        表[str(条目["能力id"])] = {
            "返回": 返回口径,
            "参数": [{"名称": str(项.get("名称", "")), "类型": str(项.get("类型") or "")}
                   for 项 in 条目.get("参数") or [] if isinstance(项, dict)],
        }
    return 表


def 比对注册口径(契约表: dict[str, dict[str, Any]],
                注册表: dict[str, dict[str, Any]]) -> list[str]:
    """逐条比对注册口径与契约口径，返回不一致清单（与 契约.校验声明一致 同口径）。

    - 返回：两边经 `契约.归一注册口径` 归一后比较（注册 `结果` ≡ 契约 `结果型`）；
      不归一的话全仓首报约 300 条纯写法噪声，会把真问题淹掉。
    - 参数：① 参数名序；② 参数类型——**只比对两侧都是正式类型名**的项
      （历史短名 布尔/文本/字典/数值 属批次4「注册元数据-类型名非正式」治理范围，
      不是本检测的口径漂移，混进来会造出第二套清单）。
    只在两侧都解析出的能力上比对；未解析的能力由调用方按覆盖率如实登记。
    """
    问题列表: list[str] = []
    for 能力id, 契约项 in sorted(契约表.items()):
        注册项 = 注册表.get(能力id)
        if 注册项 is None:
            continue
        注册返回 = 注册项.get("返回")
        契约返回 = str(契约项.get("返回", ""))
        # 返回口径解析不出（动态拼装）时跳过，不伪造「空返回」的假红。
        if 注册返回 is not None and 归一注册口径(str(注册返回)) != 归一注册口径(契约返回):
            问题列表.append(f"{能力id}: 注册返回 {注册返回} ≠ 契约返回 {契约返回}")
        注册参数 = 注册项.get("参数")
        if 注册参数 is None:
            continue
        注册名 = [项["名称"] for 项 in 注册参数]
        契约名 = [项["名称"] for 项 in 契约项.get("参数", [])]
        if 注册名 and 契约名 and 注册名 != 契约名:
            问题列表.append(f"{能力id}: 注册参数名序 {注册名} ≠ 契约参数名序 {契约名}")
        契约类型 = {项["名称"]: 项["类型"] for 项 in 契约项.get("参数", [])}
        for 项 in 注册参数:
            类型 = str(项.get("类型", ""))
            期望 = str(契约类型.get(项["名称"], ""))
            if 类型 in 正式类型表 and 期望 in 正式类型表 and 类型 != 期望:
                问题列表.append(
                    f"{能力id}: 注册参数 {项['名称']} 类型 {类型} ≠ 契约类型 {期望}"
                )
    return 问题列表


def 检测注册口径漂移(包目录: Path) -> list[str]:
    """「注册口径」子检测：包入口注册表 ↔ `能力契约/参数契约.json` 的不一致清单。

    落点清单_03 重要-10：`契约.校验声明一致` 曾零生产调用点，注册口径漂移长期
    无人发现；本检测是它的**编译期**落点（运行期落点见批次0-4 接线说明）。
    """
    问题列表 = 比对注册口径(读取契约口径(包目录 / "能力契约" / "参数契约.json"),
                        读取注册口径(包目录 / "__init__.py"))
    if not 问题列表:
        return []
    相对路径 = 包目录.name
    return [f"{相对路径}: {问题}" for 问题 in 问题列表]


def 全仓注册口径统计(系统根: Path) -> dict[str, Any]:
    """全仓注册口径检测（只读）：遍历 支持库/模块库/技能库 下全部 参数契约.json。

    返回 `{包数, 契约能力数, 已解析注册数, 未解析注册数, 返回未解析数,
    参数未解析数, 问题列表}`：问题列表每条都带「包相对路径」便于定位；
    三个「未解析」计数如实暴露 AST 静态解析覆盖率与跳过比对的项，不假装 100%。
    """
    包数 = 契约能力数 = 已解析 = 未解析注册 = 返回未解析 = 参数未解析 = 0
    问题列表: list[str] = []
    for 顶层 in ("支持库", "模块库", "技能库"):
        根目录 = 系统根 / 顶层
        if not 根目录.is_dir():
            continue
        for 契约文件 in sorted(根目录.glob("**/能力契约/参数契约.json")):
            包目录 = 契约文件.parent.parent
            契约表 = 读取契约口径(契约文件)
            注册表 = 读取注册口径(包目录 / "__init__.py")
            包数 += 1
            契约能力数 += len(契约表)
            for 能力id in 契约表:
                注册项 = 注册表.get(能力id)
                if 注册项 is None:
                    未解析注册 += 1
                    continue
                已解析 += 1
                if 注册项.get("返回") is None:
                    返回未解析 += 1
                if 注册项.get("参数") is None:
                    参数未解析 += 1
            相对路径 = 包目录.relative_to(系统根) if 包目录.is_relative_to(系统根) else 包目录
            for 问题 in 比对注册口径(契约表, 注册表):
                问题列表.append(f"{相对路径}: {问题}")
    return {"包数": 包数, "契约能力数": 契约能力数, "已解析注册数": 已解析,
            "未解析注册数": 未解析注册, "返回未解析数": 返回未解析,
            "参数未解析数": 参数未解析, "问题列表": 问题列表}


def 全仓注册口径检测(系统根: Path) -> list[str]:
    """全仓注册口径漂移清单（只读；拦还是只报由调用方决定）。"""
    return 全仓注册口径统计(系统根)["问题列表"]


def 全面漂移检测(*, 契约: dict[str, Any], 实现目录: Path,
                  入口文件: Path, 说明书文件: Path,
                  旧契约: dict[str, Any] | None = None,
                  实现文件: Path | None = None) -> 漂移结果:
    """执行全部漂移检测。

    实现文件：返回结构漂移与错误码漂移都要读「实现该能力的那个 .py」。
    调用方知道就显式传入；不传时按 实现目录/{能力id末段}.py 猜想，猜不中
    就如实登记「未执行」而不是当成「无漂移」——见下方 3./4. 说明。
    """
    结果 = 漂移结果()
    # 1. 声明能力但没有实现
    声明无实现 = 检测声明无实现(契约, 实现目录)
    if 声明无实现:
        结果.问题列表.append(声明无实现)
    # 2. 参数顺序漂移
    参数漂移 = 检测参数漂移(契约, 入口文件)
    if 参数漂移:
        结果.问题列表.append(参数漂移)
    # 3./4. 返回结构漂移 + 错误码漂移（都需要真实实现文件）
    # 原实现按 实现目录/{能力id末段}.py 拼接后直接传给两个检测器：路径不存在时
    # 检测返回漂移 返回 None、检测错误码漂移 返回 []，二者都不产生任何问题，
    # 即「找不到实现文件」被静默当成「无漂移」。而本仓实现文件普遍是「一包一文件」
    # （实现/包名.py 内含该包全部能力，如 支持库/前端/桌面宿主/实现/桌面宿主.py），
    # 能力id 末段几乎不与文件名相同——全仓 549 条能力实测两项检测命中 0，属永久空跑。
    # 契约本身不含实现文件信息，注册入口又有多种数据流写法（静态解析不可靠），
    # 故不再臆造路径：猜不中时显式登记「未执行」，由调用方决定传入 实现文件。
    能力名 = 契约.get("能力id", "").split(".")[-1]
    定位文件 = 实现文件
    if 定位文件 is None and 实现目录.is_dir() and 能力名:
        直接候选 = 实现目录 / f"{能力名}.py"
        if 直接候选.is_file():
            定位文件 = 直接候选
    if 定位文件 is None or not 定位文件.is_file():
        结果.问题列表.append(
            f"实现文件未定位，返回结构/错误码漂移未执行: "
            f"{契约.get('能力id') or '（无能力id）'}"
            f"（{实现目录} 下无 {能力名 or '（无能力名）'}.py，契约亦不含实现文件信息）"
        )
    else:
        返回漂移 = 检测返回漂移(契约, 定位文件)
        if 返回漂移:
            结果.问题列表.append(返回漂移)
        结果.问题列表.extend(检测错误码漂移(契约, 定位文件))
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
