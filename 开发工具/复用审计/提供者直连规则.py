"""提供者直连规则注册表：直连模式 → AST 检测规则的结构化登记与门禁判定。

背景：平台控制面/提供者/防火墙审计_规则.py 以 AST 启发式函数名表判定
直连外部服务。本注册表把“直连模式 → 检测特征（模块列表、函数名/属性名
列表）”结构化登记：新增第三方提供者必须通过 登记规则() 声明其直连模式；
源码中出现未登记的直连模式时，门禁判定() 阻断发布。

已声明判定：登记规则 表中有该直连模式（如 "grpc"）即视为已声明；未登记
的模式（如 "thrift"、"zeromq"）在源码中出现必须阻断。内置规则为平台已知
直连模式（默认全部视为未声明），thrift/zeromq 为已知但默认未登记的 rpc
直连模式。
"""
from __future__ import annotations

import ast

内置规则: dict[str, dict[str, list[str]]] = {
    "HTTP": {
        "模块": ["http.client", "urllib.request"],
        "函数名": ["urlopen", "HTTPConnection", "HTTPSConnection"],
    },
    "数据库": {
        "模块": ["psycopg2", "psycopg", "pg8000", "pymysql", "pymongo", "redis", "sqlite3"],
        "函数名": ["connect"],
    },
    "动态库": {
        "模块": ["ctypes"],
        "函数名": ["CDLL"],
    },
    "进程": {
        "模块": ["subprocess", "multiprocessing"],
        # os.system / os.popen 以“os 下函数名”特征登记，避免 import os 误伤
        "函数名": ["Popen", "run", "call", "system", "popen"],
    },
    "grpc": {
        "模块": ["grpc", "grpc.aio"],
        "函数名": ["secure_channel", "insecure_channel"],
    },
    "thrift": {  # 已知直连模式，默认未登记 → 源码出现即阻断
        "模块": ["thrift", "thriftpy", "thriftpy2"],
        "函数名": [],
    },
    "zeromq": {  # 已知直连模式，默认未登记 → 源码出现即阻断
        "模块": ["zmq", "pyzmq"],
        "函数名": [],
    },
}


class 直连规则注册表:
    """直连模式注册表：内置检测特征 + 第三方提供者声明（登记规则）。"""

    def __init__(self) -> None:
        self.已登记规则: dict[str, dict] = {}

    def 登记规则(self, 提供者id: str, 直连模式: str, 规则: dict) -> None:
        """第三方提供者声明其直连规则；规则含 模块列表、函数名/属性名列表。"""
        if not 直连模式:
            raise ValueError("直连模式不能为空")
        self.已登记规则[直连模式] = {
            "提供者id": 提供者id,
            "模块": list(规则.get("模块", [])),
            "函数名": list(规则.get("函数名", [])),
        }

    def _检测特征表(self) -> dict[str, dict[str, list[str]]]:
        """内置规则与已登记规则合并的检测特征表（登记规则的模块/函数也参与检测）。"""
        特征表 = {模式: {"模块": list(规则["模块"]), "函数名": list(规则["函数名"])}
                 for 模式, 规则 in 内置规则.items()}
        for 模式, 规则 in self.已登记规则.items():
            if 模式 not in 特征表:
                特征表[模式] = {"模块": [], "函数名": []}
            特征表[模式]["模块"].extend(规则["模块"])
            特征表[模式]["函数名"].extend(规则["函数名"])
        return 特征表

    @staticmethod
    def _模块命中模式(模块名: str, 特征表: dict) -> list[tuple[str, str]]:
        """模块名命中的 (模式, 匹配模块) 列表：完全相等或为“模式模块.”的子树。"""
        命中 = []
        for 模式, 规则 in 特征表.items():
            for 已知模块 in 规则["模块"]:
                if 模块名 == 已知模块 or 模块名.startswith(已知模块 + "."):
                    命中.append((模式, 已知模块))
                    break
        return 命中

    def 审计源码(self, 源码文本: str) -> list[dict]:
        """ast 解析源码，检测直连调用（import 模块名 或 调用函数名）。

        返回命中列表，每项含 模式、模块或函数、行号。
        """
        try:
            树 = ast.parse(源码文本)
        except SyntaxError:
            return []
        特征表 = self._检测特征表()
        命中: list[dict] = []
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                模块候选 = [别名.name for 别名 in 节点.names]
            elif isinstance(节点, ast.ImportFrom) and 节点.module:
                模块候选 = [节点.module]
            elif isinstance(节点, ast.Call):
                if isinstance(节点.func, ast.Name):
                    函数名 = 节点.func.id
                elif isinstance(节点.func, ast.Attribute):
                    函数名 = 节点.func.attr
                else:
                    continue
                for 模式, 规则 in 特征表.items():
                    if 函数名 in 规则["函数名"]:
                        命中.append({"模式": 模式, "模块或函数": 函数名, "行号": 节点.lineno})
                        break
                continue
            else:
                continue
            for 模块名 in 模块候选:
                for 模式, 已知模块 in self._模块命中模式(模块名, 特征表):
                    命中.append({"模式": 模式, "模块或函数": 已知模块, "行号": 节点.lineno})
        # 去重：同一 (模式, 模块或函数, 行号) 只保留一次
        去重后: list[dict] = []
        for 项 in 命中:
            if 项 not in 去重后:
                去重后.append(项)
        return 去重后

    def 门禁判定(self, 源码文本: str) -> tuple[bool, list[dict]]:
        """命中直连模式但未登记 → 阻断发布；返回 (是否阻断, 未声明直连列表)。"""
        未声明 = [命中 for 命中 in self.审计源码(源码文本)
                 if 命中["模式"] not in self.已登记规则]
        return (bool(未声明), 未声明)

    def 导出规则(self) -> dict:
        """返回全部规则（内置 + 已登记），JSON 可序列化。"""
        return {
            "内置规则": {模式: dict(规则) for 模式, 规则 in 内置规则.items()},
            "已登记规则": {模式: dict(规则) for 模式, 规则 in self.已登记规则.items()},
        }
