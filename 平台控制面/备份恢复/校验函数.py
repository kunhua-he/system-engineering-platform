"""权威数据备份契约的四类真实校验函数（第十四阶段工作包 P1-09）。

校验权威状态：真实打开 sqlite 运行 PRAGMA integrity_check 必须返回 ok。
校验证据账本：重放每条证据的哈希字段 == sha256(内容) 前 16 位。
校验包仓库：制品目录逐文件重算 sha256 与备份清单比对。
校验项目锁：JSON 可解析且必填字段齐全。
"""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.数据库URI import 只读库URI

锁必填字段表 = ("项目id", "所有者", "锁定时间")


def 内容摘要(内容: bytes) -> str:
    return hashlib.sha256(内容).hexdigest()


def 校验权威状态(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """真实打开 sqlite 运行 PRAGMA integrity_check，必须返回 ok。"""
    # 保留 sqlite3 直连、不收敛到唯一入口的技术必要（已实测）：备份快照必须**只读**打开——
    # 统一入口的 查询 以读写方式开库，对不存在的文件会**隐式建库**并让 PRAGMA integrity_check
    # 返回 ok，缺失快照会被误判「完整性通过」；且校验不得在可能改写快照的连接上跑。
    try:
        连接 = sqlite3.connect(只读库URI(目录 / 备份项['文件']), uri=True)
        try: 结果 = 连接.execute("PRAGMA integrity_check").fetchone()
        finally: 连接.close()
        return (真, "完整性检查通过") if 结果 and 结果[0] == "ok" else (假, f"完整性检查: {结果}")
    except (sqlite3.DatabaseError, OSError) as 错误:
        return 假, f"sqlite 打开或检查失败: {错误}"


def 校验证据账本(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """重放校验哈希字段：每条证据的哈希 == sha256(内容) 前 16 位。

    空账本一律判失败：没有可校验的证据时循环体不执行，「全部一致」是空集
    恒真（判据① 空跑），不能据此认证备份有效。
    """
    try: 证据表 = json.loads((目录 / 备份项["文件"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误: return 假, f"证据账本不可解析: {错误}"
    if not isinstance(证据表, list) or not 证据表:
        return 假, "证据账本为空或不是数组（无可校验证据）"
    for 条 in 证据表:
        if not isinstance(条, dict):
            return 假, f"证据条目不是对象: {条!r}"
        内容 = 条.get("内容", "")
        正文 = 内容 if isinstance(内容, str) else json.dumps(内容, ensure_ascii=False)
        if 条.get("哈希") != hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]:
            return 假, f"证据哈希不符: {条.get('证据id')}"
    return 真, f"{len(证据表)} 条证据哈希全部一致"


def 校验包仓库(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """制品目录逐文件重算 sha256 与备份清单比对。

    空摘要表一律判失败：没有可比对的制品时循环体不执行，「全部一致」是
    空集恒真（判据① 空跑），不能据此认证备份有效。
    """
    文件摘要表 = 备份项.get("文件摘要表")
    if not isinstance(文件摘要表, dict) or not 文件摘要表:
        return 假, "制品摘要表为空或缺失（无可比对制品）"
    for 相对路径, 期望摘要 in 文件摘要表.items():
        文件 = 目录 / 相对路径
        if not 文件.is_file() or 内容摘要(文件.read_bytes()) != 期望摘要:
            return 假, f"制品缺失或摘要不符: {相对路径}"
    return 真, "全部制品摘要一致"


def 校验项目锁(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """JSON 可解析且必填字段齐全。"""
    try: 锁 = json.loads((目录 / 备份项["文件"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误: return 假, f"项目锁不可解析: {错误}"
    if not isinstance(锁, dict) or any(字段 not in 锁 for 字段 in 锁必填字段表):
        return 假, "项目锁必须为 JSON 对象且必填字段齐全"
    return 真, "必填字段齐全"
