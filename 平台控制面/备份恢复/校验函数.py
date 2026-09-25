"""权威数据备份契约的三类真实校验函数（第十四阶段工作包 P1-09）。

校验权威状态：真实打开 sqlite 运行 PRAGMA integrity_check 必须返回 ok。
校验证据账本：重放每条证据的哈希字段 == sha256(内容) 前 16 位。
校验包仓库：制品目录逐文件重算 sha256 与备份清单比对。
"""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.数据库连接 import 打开只读

# 内容寻址摘要（sha256 全文 hexdigest）的唯一实现 = 包仓库.物料清单（包仓库主链）。
# 本模块原持一份逐字相同的同名副本，已删并改为转调：平台控制面 同层内部转调，
# 方向与既有 `备份恢复/类根解析.py → 平台控制面.包仓库.制品布局` 一致，不引入新层向、无环。
from 平台控制面.包仓库.物料清单 import 内容摘要


def 校验权威状态(目录: Path, 备份项: dict) -> tuple[bool, str]:
    """真实打开 sqlite 运行 PRAGMA integrity_check，必须返回 ok。"""
    # 转调 `公共契约/运行时/数据库连接.py`，原参数 uri=True（无 timeout）→ 档 打开只读(路径)
    # （默认超时 5.0 = stdlib 默认，逐字等价）。仍**只读**打开：打开只读 走 只读库URI 的 mode=ro，
    # 不会对不存在的文件隐式建库，缺失快照不会被 PRAGMA integrity_check 误判「完整性通过」。
    try:
        连接 = 打开只读(目录 / 备份项['文件'])
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
