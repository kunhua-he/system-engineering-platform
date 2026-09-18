"""恢复执行能力：备份定位、版本回退检测与单类恢复（权威数据备份契约 mixin）。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path


from 平台控制面.备份恢复.备份执行 import 清单文件名, _尽力复制附加文件
from 公共契约.基础类型.逻辑类型 import 真, 假


def _取独占目标库(目标库: Path) -> tuple[sqlite3.Connection | None, str]:
    """恢复期间**独占**目标权威状态库；返回 `(连接, 失败原因)`，成功时原因为空串。

    **为什么必须独占**（B-20）：恢复是**覆盖写**目标库文件。另一进程（网关/监督器/
    另一个恢复任务）正开着它读写时直接覆盖，会得到「一半旧一半新」的混合库，
    且对方持有的旧文件句柄还能把旧内容写回。`BEGIN EXCLUSIVE` 是唯一可靠的探针：
    它只能被一个连接拿到，有活跃连接持锁即抛 `database is locked`。
    目标库不存在（全新恢复目标）时无需加锁，返回 `(None, "")`。

    WAL 模式下 `BEGIN EXCLUSIVE` 同样拦截活跃写事务；拿到锁期间 SQLite 不会让
    第二个写连接介入，覆盖期间的库状态对外不可见（当前连接不提交、随后 rollback）。

    **不抛异常**：占用是**预期的业务结论**（调用方要如实返回失败原因），
    不能穿透到网关被收口成「路由缺失/未知错误」。
    """
    if not 目标库.exists():
        return None, ""
    try:
        连接 = sqlite3.connect(str(目标库), timeout=0, isolation_level=None)
    except sqlite3.Error as 错误:
        return None, f"目标权威状态库无法打开，拒绝覆盖恢复: {错误}"
    try:
        连接.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as 错误:
        连接.close()
        return None, f"目标权威状态库被占用，拒绝无锁覆盖恢复: {错误}"
    except sqlite3.DatabaseError as 错误:
        # 目标不是 sqlite 库 / 文件已损坏：**无从证明独占**，故同样拒绝覆盖，
        # 并如实说明（先把损坏库移走再恢复），不猜「反正要恢复就随便覆盖」。
        连接.close()
        return None, f"目标权威状态库不可用（非 sqlite 库或已损坏），拒绝覆盖恢复: {错误}"
    return 连接, ""


def _释放目标库(连接: sqlite3.Connection | None) -> None:
    """释放独占锁（未提交事务回滚，绝不把恢复期的库状态写回业务语义）。"""
    if 连接 is None:
        return
    try:
        连接.rollback()
    finally:
        连接.close()


class 恢复执行能力:
    """恢复执行能力：按契约顺序恢复四类数据并逐类真实校验。"""

    def _定位清单(self, 备份目录: Path) -> dict:
        """备份目录直接含清单则用之；否则取**已认证**（含清单）的最新时间戳快照。

        未被认证的快照（只有 `快照_*` 目录、没有 `备份清单.json`——写清单是备份的
        最后一步）一律跳过：把它当备份去读清单会抛 `FileNotFoundError`，被
        `运行核心/统一网关/网关核心.py` 收口成公开码 `文件不存在` = **HTTP 404**，
        把「备份未认证」伪装成「路由缺失」（2026-09-16 HTML 黑盒实测）。
        """
        备份目录 = Path(备份目录)
        清单文件 = 备份目录 / 清单文件名
        if not 清单文件.is_file():
            候选 = [子目录 for 子目录 in sorted(备份目录.glob("快照_*"), reverse=True)
                    if (子目录 / 清单文件名).is_file()]
            if not 候选:
                raise FileNotFoundError(f"备份目录无已认证备份（缺 {清单文件名}）: {备份目录}")
            清单文件 = 候选[0] / 清单文件名
        return json.loads(清单文件.read_text(encoding="utf-8"))

    def _检测版本回退(self, 清单: dict, 目标目录: Path) -> str:
        """比较备份恢复点与目标现有权威状态库写入时间；备份更旧则返回回退警告。"""
        备份恢复点 = 清单.get("恢复点") or 清单.get("备份时间") or ""
        目标库 = 目标目录 / "权威状态.db"
        if not (备份恢复点 and 目标库.is_file()):
            return ""
        try:
            现有写入时间 = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(目标库.stat().st_mtime))
        except OSError:
            return ""
        if 备份恢复点 < 现有写入时间:
            return (f"检测到版本回退: 备份恢复点 {备份恢复点} 早于目标现有权威状态 "
                    f"写入时间 {现有写入时间}，旧快照将覆盖更新状态")
        return ""

    def _恢复一类(self, 类名: str, 快照目录: Path, 目标目录: Path) -> Path:
        if 类名 == "包仓库":
            shutil.copytree(快照目录 / "制品", 目标目录 / "制品", dirs_exist_ok=True)
            return 目标目录 / "制品"
        if 类名 == "权威状态":
            shutil.copy2(快照目录 / "权威状态.db", 目标目录 / "权威状态.db")
            for 后缀 in ("-wal", "-shm"):
                目标附加 = 目标目录 / f"权威状态.db{后缀}"
                附加 = 快照目录 / f"权威状态.db{后缀}"
                if 附加.is_file():
                    # 与备份侧同一语义：WAL/SHM 是瞬时文件，缺失即「本快照没有它」。
                    _尽力复制附加文件(附加, 目标附加)
                else:
                    # 新快照（VACUUM INTO）不带附加文件：目标目录里遗留的旧 `-wal`
                    # 属于**上一个库**，留着会被 SQLite 当成本库日志回放 → 混合状态。
                    # 覆盖后必须清掉，否则恢复出的库内容不可预期。
                    try:
                        目标附加.unlink()
                    except OSError:
                        pass
            return 目标目录
        文件名 = "证据账本.json" if 类名 == "证据账本" else "项目锁.json"
        shutil.copy2(快照目录 / 文件名, 目标目录 / 文件名)
        return 目标目录

    def 恢复(self, 备份目录: Path | str, 目标目录: Path | str) -> dict:
        """按契约恢复顺序恢复四类数据，恢复后逐类真实校验。

        版本回退检测：若目标目录已存在权威状态库且其最后写入时间晚于本备份
        的恢复点，则判定为旧快照重放——结果附带「版本回退」警告（重放仍按
        用户意图执行，但调用方必须看到回退标记，防止旧备份无警告覆盖新状态）。
        """
        清单 = self._定位清单(备份目录)
        快照目录 = Path(清单["快照目录"])
        目标目录 = Path(目标目录)
        目标目录.mkdir(parents=True, exist_ok=True)
        契约表 = self.声明契约(清单["契约"])
        顺序类表 = sorted(契约表, key=lambda 类: 契约表[类]["恢复顺序"])
        回退警告 = self._检测版本回退(清单, 目标目录)
        结果表 = []
        独占连接, 占用原因 = _取独占目标库(目标目录 / "权威状态.db")
        if 占用原因:
            # 目标库被占用：必须在**写任何东西之前**中止（B-20）。
            # 如实返回失败结论，不抛异常穿透到网关被收口成「路由缺失/未知错误」。
            return {"成功": 假, "恢复顺序": 顺序类表,
                    "结果": [{"类": "权威状态", "成功": 假, "原因": 占用原因}],
                    "目标目录": str(目标目录), "回退警告": 回退警告}
        # 权威状态库正被本函数的 BEGIN EXCLUSIVE 独占：**校验必须等锁释放之后**再做。
        # 否则 `校验权威状态` 以 `mode=ro` 再开一次同一文件时被自己的写锁挡住（实测：
        # 目标库已存在的第 2 次恢复到同一目录，稳定报
        # `sqlite 打开或检查失败: database is locked`；目标库不存在时不加锁，
        # 所以第 1 次能过——即「重试/覆盖恢复」这条路径长期必假红）。
        # 这里只延迟校验（校验不写盘、不受锁保护），恢复顺序与结果顺序都不变。
        待校验表: list[tuple[int, str, Path, dict]] = []
        try:
            for 类名 in 顺序类表:
                备份项 = 清单["文件"].get(类名, {})
                if 备份项.get("缺失"):
                    结果表.append({"类": 类名, "成功": 假, "原因": "备份缺失"})
                    continue
                校验目录 = self._恢复一类(类名, 快照目录, 目标目录)
                if 类名 == "权威状态":
                    待校验表.append((len(结果表), 类名, 校验目录, 备份项))
                    结果表.append({})
                    continue
                成功, 原因 = 契约表[类名]["校验方法"](校验目录, 备份项)
                结果表.append({"类": 类名, "成功": 成功, "原因": 原因})
        finally:
            _释放目标库(独占连接)
        for 位置, 类名, 校验目录, 备份项 in 待校验表:
            成功, 原因 = 契约表[类名]["校验方法"](校验目录, 备份项)
            结果表[位置] = {"类": 类名, "成功": 成功, "原因": 原因}
        return {"成功": bool(结果表) and all(项["成功"] for 项 in 结果表),
                "恢复顺序": 顺序类表, "结果": 结果表, "目标目录": str(目标目录),
                "回退警告": 回退警告}
