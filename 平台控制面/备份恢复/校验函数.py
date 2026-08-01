"""权威数据备份契约的四类真实校验函数（第十四阶段工作包 P1-09）。

校验权威状态：真实打开 sqlite 运行 PRAGMA integrity_check 必须返回 ok。
校验证据账本：重放每条证据的哈希字段 == sha256(内容) 前 16 位。
校验包仓库：制品目录逐文件重算 sha256 与备份清单比对。
校验项目锁：JSON 可解析且必填字段齐全。
"""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path

锁必填字段表 = ("项目id", "所有者", "锁定时间")


def 内容摘要(内容: bytes) -> str:
    return hashlib.sha256(内容).hexdigest()


def 校验权威状态(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """真实打开 sqlite 运行 PRAGMA integrity_check，必须返回 ok。"""
    try:
        连接 = sqlite3.connect(f"file:{目录 / 备份项['文件']}?mode=ro", uri=True)
        try: 结果 = 连接.execute("PRAGMA integrity_check").fetchone()
        finally: 连接.close()
        return (True, "完整性检查通过") if 结果 and 结果[0] == "ok" else (False, f"完整性检查: {结果}")
    except (sqlite3.DatabaseError, OSError) as 错误:
        return False, f"sqlite 打开或检查失败: {错误}"


def 校验证据账本(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """重放校验哈希字段：每条证据的哈希 == sha256(内容) 前 16 位。"""
    try: 证据表 = json.loads((目录 / 备份项["文件"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误: return False, f"证据账本不可解析: {错误}"
    for 条 in 证据表:
        内容 = 条.get("内容", "")
        正文 = 内容 if isinstance(内容, str) else json.dumps(内容, ensure_ascii=False)
        if 条.get("哈希") != hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]:
            return False, f"证据哈希不符: {条.get('证据id')}"
    return True, f"{len(证据表)} 条证据哈希全部一致"


def 校验包仓库(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """制品目录逐文件重算 sha256 与备份清单比对。"""
    for 相对路径, 期望摘要 in 备份项.get("文件摘要表", {}).items():
        文件 = 目录 / 相对路径
        if not 文件.is_file() or 内容摘要(文件.read_bytes()) != 期望摘要:
            return False, f"制品缺失或摘要不符: {相对路径}"
    return True, "全部制品摘要一致"


def 校验项目锁(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """JSON 可解析且必填字段齐全。"""
    try: 锁 = json.loads((目录 / 备份项["文件"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误: return False, f"项目锁不可解析: {错误}"
    if not isinstance(锁, dict) or any(字段 not in 锁 for 字段 in 锁必填字段表):
        return False, "项目锁必须为 JSON 对象且必填字段齐全"
    return True, "必填字段齐全"
