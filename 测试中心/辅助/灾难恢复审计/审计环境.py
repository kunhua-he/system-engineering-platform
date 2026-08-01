"""工作包19 审计环境构造：真实权威状态库/证据账本/项目锁/制品/源码快照/依赖锁/编排器备份。

全部为真实文件与真实 sqlite 库，禁止桩实现；证据哈希按 校验证据账本 规则计算。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

最小能力输出 = '{"能力": "最小调用", "状态": "就绪"}'


def 内容摘要(内容: bytes) -> str:
    """真实 sha256 十六进制摘要。"""
    return hashlib.sha256(内容).hexdigest()


def 证据哈希(内容对象: dict) -> str:
    """证据行哈希：与 平台状态.追加证据 同构（sha256 前 16 位）。"""
    正文 = json.dumps(内容对象, ensure_ascii=False)
    return hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]


def 构造权威状态库(目录: Path, 版本标记: str) -> Path:
    """真实 sqlite：权威表 + 证据表；证据哈希可被 校验证据账本 重放通过。"""
    路径 = 目录 / "权威状态.db"
    连接 = sqlite3.connect(str(路径), timeout=10)
    with 连接:
        连接.execute("CREATE TABLE IF NOT EXISTS 权威(键 TEXT PRIMARY KEY, 值 TEXT)")
        连接.execute(
            "CREATE TABLE IF NOT EXISTS 证据(证据id TEXT PRIMARY KEY, 类型 TEXT, 主题 TEXT, "
            "内容 TEXT, 操作id TEXT, 调用者 TEXT, 角色 TEXT, 来源快照 TEXT, 结果 TEXT, "
            "错误码 TEXT, 时间 TEXT, 哈希 TEXT)")
        连接.execute("INSERT OR REPLACE INTO 权威(键, 值) VALUES('版本标记', ?)", (版本标记,))
        内容 = {"步骤": "激活", "目标": 版本标记}
        连接.execute(
            "INSERT OR REPLACE INTO 证据(证据id, 类型, 主题, 内容, 哈希) VALUES(?, ?, ?, ?, ?)",
            (f"证据_{版本标记}", "发布", "审计包", json.dumps(内容, ensure_ascii=False),
             证据哈希(内容)))
    return 路径


def 读取版本标记(权威状态库: Path) -> str:
    """只读查询权威状态库的版本标记（重放前后比对用）。"""
    连接 = sqlite3.connect(f"file:{权威状态库}?mode=ro", uri=True)
    try:
        行 = 连接.execute("SELECT 值 FROM 权威 WHERE 键='版本标记'").fetchone()
    finally:
        连接.close()
    return 行[0] if 行 else ""


def 构造项目锁(目录: Path, 锁定时间: str = "2026-01-01 08:00:00") -> Path:
    路径 = 目录 / "项目锁.json"
    路径.write_text(json.dumps({"项目id": "审计项目", "所有者": "审计所有者",
                                 "锁定时间": 锁定时间}, ensure_ascii=False), encoding="utf-8")
    return 路径


def 构造制品目录(目录: Path, 文件表: dict[str, str]) -> Path:
    """制品目录：{相对路径: 文本内容} 直接写入目录下。"""
    for 相对, 文本 in 文件表.items():
        文件 = 目录 / 相对
        文件.parent.mkdir(parents=True, exist_ok=True)
        文件.write_bytes(文本.encode("utf-8"))
    return 目录


def 构造存储根(目录: Path, *, 版本标记: str = "v1", 制品表: dict | None = None) -> Path:
    """完整权威数据存储根：权威状态库 + 项目锁 + 制品目录。"""
    目录.mkdir(parents=True, exist_ok=True)
    构造权威状态库(目录, 版本标记)
    构造项目锁(目录)
    构造制品目录(目录 / "制品", 制品表 if 制品表 is not None else {"制品A.bin": "制品内容A"})
    return 目录


def 最小能力样板文本() -> str:
    """最小能力样板源码：真实可运行，输出固定 JSON 行。"""
    return ("import json\n"
            "print(json.dumps({'能力': '最小调用', '状态': '就绪'}, ensure_ascii=False))\n")


def 构造源码快照(目录: Path) -> Path:
    """源码快照：最小能力样板 + 一个普通源码文件。"""
    目录.mkdir(parents=True, exist_ok=True)
    (目录 / "最小能力.py").write_text(最小能力样板文本(), encoding="utf-8")
    (目录 / "业务源码.py").write_text("版本标记 = '源码快照v1'\n", encoding="utf-8")
    return 目录


def 构造依赖锁(路径: Path, 包名: str = "示例包", 版本: str = "1.0.0") -> Path:
    路径.write_text(json.dumps({"包列表": [{"名称": 包名, "版本": 版本}]},
                                ensure_ascii=False), encoding="utf-8")
    return 路径


def 构造编排器备份(备份目录: Path, 文件表: dict[str, str]) -> Path:
    """编排器格式备份：备份清单.json(条目) + 内容/ 真实文件。"""
    for 相对, 文本 in 文件表.items():
        文件 = 备份目录 / "内容" / 相对
        文件.parent.mkdir(parents=True, exist_ok=True)
        文件.write_bytes(文本.encode("utf-8"))
    条目表 = [{"相对路径": 相对, "摘要": 内容摘要(文本.encode("utf-8"))}
              for 相对, 文本 in 文件表.items()]
    (备份目录 / "备份清单.json").write_text(
        json.dumps({"条目": 条目表}, ensure_ascii=False), encoding="utf-8")
    return 备份目录
