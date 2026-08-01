"""平台控制面专属依赖防火墙·规则层（AST 判定）。"""
from __future__ import annotations

import ast
from pathlib import Path

from 运行核心.依赖防火墙 import 依赖审计结果, 依赖违规, 标准库前缀表

外部驱动模块表 = {"psycopg2", "psycopg", "pg8000", "pymysql", "pymongo", "redis"}
# 路径标记动态拼接：避免审计规则自身的源码文本命中"实现目录路径"规则
实现路径标记表 = ("/" + "实现", "实现" + "/", "\\" + "实现")
系统根 = Path(__file__).resolve().parents[2]
平台控制面目录 = 系统根 / "平台控制面"
动态导入函数表 = {"__import__", "import_module", "动态导入"}
反射导入函数表 = {"反射导入", "动态加载", "执行导入",
                "spec_from_file_location", "module_from_spec", "exec_module"}
直连函数名表 = {"urlopen", "create_connection", "HTTPConnection", "HTTPSConnection", "CDLL"}
直连属性表 = {"urlopen", "HTTPConnection", "HTTPSConnection",
            "create_connection", "CDLL", "socket", "Socket"}

def 登记提供者表(提供者声明文件: Path | None) -> set[str]:
    """解析提供者声明文件（提供者/__init__.py）的导入表 → 已登记提供者文件名集合。"""
    if 提供者声明文件 is None or not Path(提供者声明文件).is_file():
        return set()
    try:
        树 = ast.parse(Path(提供者声明文件).read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    目录 = Path(提供者声明文件).parent
    登记表: set[str] = set()
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ImportFrom):
            for 别名 in 节点.names:
                if (目录 / f"{别名.name}.py").is_file():
                    登记表.add(f"{别名.name}.py")
    return 登记表


def _函数名(节点: ast.Call) -> str | None:
    """调用函数名：Name（__import__）或 Attribute（importlib.import_module）。"""
    if isinstance(节点.func, ast.Name):
        return 节点.func.id
    if isinstance(节点.func, ast.Attribute):
        return 节点.func.attr
    return None


def _是直连调用(节点: ast.Call) -> bool:
    """直连外部服务连接 API 调用判定（数据库/网络/动态库）。"""
    if isinstance(节点.func, ast.Name):
        return 节点.func.id in 直连函数名表
    if isinstance(节点.func, ast.Attribute):
        if 节点.func.attr == "connect":
            模块 = 节点.func.value
            return isinstance(模块, ast.Name) and 模块.id in 外部驱动模块表
        return 节点.func.attr in 直连属性表
    return False


def _直连名称(节点: ast.Call) -> str:
    函数 = 节点.func.attr if isinstance(节点.func, ast.Attribute) else 节点.func.id
    return f"{函数}()"


def 审计文件(文件路径: Path, 登记表: set[str]) -> 依赖审计结果:
    """单文件审计：动态导入、反射、实现目录、直连外部服务四类规则。"""
    结果 = 依赖审计结果()
    路径 = Path(文件路径)
    try:
        树 = ast.parse(路径.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return 结果
    结果.审计文件数 = 1
    try:
        相对 = str(路径.relative_to(系统根))
    except ValueError:
        相对 = str(路径)
    文件名 = 路径.name
    父表: dict[int, ast.AST] = {}
    for 父 in ast.walk(树):
        for 子 in ast.iter_child_nodes(父):
            父表[id(子)] = 父

    def 在函数作用域内(节点: ast.AST) -> bool:
        当前 = 节点
        while id(当前) in 父表:
            当前 = 父表[id(当前)]
            if isinstance(当前, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda, ast.ClassDef)):
                return True
        return False

    for 节点 in ast.walk(树):
        函数名 = _函数名(节点) if isinstance(节点, ast.Call) else None
        if 函数名 in 动态导入函数表:
            参数 = 节点.args[0] if 节点.args else None
            if isinstance(参数, ast.Constant) and isinstance(参数.value, str):
                顶层 = 参数.value.split(".")[0]
                if 顶层 in 标准库前缀表:
                    continue  # 标准库字面量动态导入（如 hashlib）豁免
                结果.违规列表.append(依赖违规("平台控制面", 参数.value,
                                              "动态导入绕过依赖审计", 相对, 节点.lineno))
            else:
                结果.违规列表.append(依赖违规("平台控制面", "<动态参数>",
                                              "路径拼接动态导入绕过依赖审计", 相对, 节点.lineno))
            continue
        if 函数名 in 反射导入函数表:
            结果.违规列表.append(依赖违规("平台控制面", 函数名,
                                          "反射导入绕过依赖审计", 相对, 节点.lineno))
            continue
        if 函数名 in ("eval", "exec", "compile"):
            for 参数 in 节点.args:
                if isinstance(参数, ast.Constant) and isinstance(参数.value, str) \
                        and "import" in 参数.value:
                    结果.违规列表.append(依赖违规("平台控制面", 节点.func.id,
                                                  "反射导入绕过依赖审计", 相对, 节点.lineno))
                    break
        if isinstance(节点, (ast.Import, ast.ImportFrom)):
            模块表 = [别名.name for 别名 in 节点.names] if isinstance(节点, ast.Import) \
                else [节点.module or ""]
            for 模块名 in 模块表:
                if "实现" in 模块名.split("."):
                    结果.违规列表.append(依赖违规("平台控制面", 模块名,
                                                  "跨包深入实现目录", 相对, 节点.lineno))
        if isinstance(节点, ast.Constant) and isinstance(节点.value, str) \
                and any(标记 in 节点.value for 标记 in 实现路径标记表):
            结果.违规列表.append(依赖违规("平台控制面", 节点.value[:40],
                                          "路径引用实现目录", 相对, 节点.lineno))
        if isinstance(节点, ast.Call) and _是直连调用(节点):
            if 文件名 not in 登记表:
                结果.违规列表.append(依赖违规("平台控制面", _直连名称(节点),
                                              "提供者直连外部服务绕过注册表", 相对, 节点.lineno))
            elif not 在函数作用域内(节点):
                结果.违规列表.append(依赖违规("平台控制面", _直连名称(节点),
                                              "模块级直连外部服务（注册表外初始化）", 相对, 节点.lineno))
    return 结果

