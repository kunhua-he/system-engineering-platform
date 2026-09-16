"""备份执行能力：四类权威数据的备份写入与快照落盘（权威数据备份契约 mixin）。"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from 公共契约.诊断.忽略记录 import 记录忽略
from 平台控制面.备份恢复.校验函数 import 内容摘要
from 支持库.后端.数据库连接支持库.SQLite数据库 import 查询

四类数据表 = ("权威状态", "包仓库", "证据账本", "项目锁")

#: 备份快照的认证标记：写在快照目录里的最后一步，**没有它就等于该快照未被认证**。
清单文件名 = "备份清单.json"


def _尽力复制附加文件(源: Path, 目标: Path) -> bool:
    """尽力复制 SQLite 附加文件（``-wal`` / ``-shm``）；返回是否真的复制了。

    **为什么不能 is_file() + copy2()**：SQLite 在最后一个连接关闭时会自行删除
    ``-wal``/``-shm``，二者是**瞬时文件**，`is_file()` 与 `copy2()` 之间必然存在
    窗口。2026-09-16 HTML 黑盒（并发 32）实测：本函数原先直接 ``copy2``，抛出的
    ``FileNotFoundError`` 被 ``运行核心/统一网关/网关核心.py`` 的处理分支收口成公开码
    ``文件不存在`` = **HTTP 404**，把「WAL 瞬时文件被回收」伪装成「路由不存在」
    （备份恢复.备份与校验 两步双双 404）。

    消失即等于「没有这个附加文件」：WAL 内容此时已由前面的
    ``PRAGMA wal_checkpoint(TRUNCATE)`` 合并进主库快照，故如实忽略并留痕，
    既不上抛异常、也不伪装成功态。
    """
    try:
        shutil.copy2(源, 目标)
        return True
    except FileNotFoundError:
        # 半份文件不留：copy2 抛错时目标要么未被创建、要么是被截断的半份。
        try:
            目标.unlink()
        except OSError:
            pass
        记录忽略("备份执行.附加文件", f"{源} 在复制前被 SQLite 回收（WAL/SHM 属瞬时文件）")
        return False


class 备份执行能力:
    """备份写入能力：单类备份到时间戳快照子目录，返回备份条目。"""

    def _备份一类(self, 类名: str, 快照目录: Path) -> dict:
        """备份单类；数据源缺失时标记缺失（校验将失败）。"""
        源 = self.存储根目录 / ("权威状态.db" if 类名 == "证据账本" else self.文件名表[类名])
        缺失项 = {"缺失": True, "文件": self.文件名表[类名]}
        if 类名 == "包仓库":
            if not 源.is_dir():
                return 缺失项
            目标 = 快照目录 / "制品"
            文件摘要表 = {}
            总字节 = 0
            for 文件 in 源.rglob("*"):
                if not 文件.is_file():
                    continue
                相对 = 文件.relative_to(源).as_posix()
                (目标 / 相对).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(文件, 目标 / 相对)
                内容 = 文件.read_bytes()
                文件摘要表[相对] = 内容摘要(内容)
                总字节 += len(内容)
            摘要 = 内容摘要(json.dumps(文件摘要表, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            return {"文件": "制品/", "文件数": len(文件摘要表), "大小": 总字节,
                    "摘要": 摘要, "文件摘要表": 文件摘要表}
        if not 源.is_file():
            return 缺失项
        if 类名 == "权威状态":
            shutil.copy2(源, 快照目录 / "权威状态.db")
            for 后缀 in ("-wal", "-shm"):
                附加 = Path(str(源) + 后缀)
                if 附加.is_file():
                    _尽力复制附加文件(附加, 快照目录 / f"权威状态.db{后缀}")
            内容 = (快照目录 / "权威状态.db").read_bytes()
            return {"文件": "权威状态.db", "大小": len(内容), "摘要": 内容摘要(内容)}
        文件名 = "证据账本.json" if 类名 == "证据账本" else "项目锁.json"
        条数 = 0
        if 类名 == "证据账本":
            # 读证据账本一律经唯一 SQLite 支持库入口（参数化只读查询，连接随调用释放）
            有表列表 = 查询(str(源), "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                          ["证据"]).确保成功()["行列表"]
            证据表 = []
            if 有表列表:
                行列表 = 查询(str(源), "SELECT * FROM 证据").确保成功()["行列表"]
                证据表 = [{**条, "内容": json.loads(条["内容"])} for 条 in 行列表]
            条数 = len(证据表)
            (快照目录 / 文件名).write_text(json.dumps(证据表, ensure_ascii=False), encoding="utf-8")
        else:
            shutil.copy2(源, 快照目录 / 文件名)
        内容 = (快照目录 / 文件名).read_bytes()
        return {"文件": 文件名, "大小": len(内容), "摘要": 内容摘要(内容),
                **( {"条数": 条数} if 类名 == "证据账本" else {})}

    def 执行备份(self, 备份目录: Path | str) -> dict:
        """真实备份四类数据到时间戳快照子目录，返回备份清单。

        失败即不落盘：快照目录在清单写入前失败时**整目录回收**再上抛，对齐本能力
        声明的 补偿动作「失败即不落盘，不留半份状态」。历史实测（2026-09-16 HTML
        黑盒并发 32）留下过只有 `快照_*` 目录、没有 `备份清单.json` 的半份快照，
        下一步 校验备份 把它当备份去读清单 → `FileNotFoundError` → 网关收口成
        HTTP 404「文件不存在」：调用方看到的是「路由缺失」，而不是真实原因。
        """
        快照目录 = Path(备份目录) / f"快照_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() % 1 * 1000):03d}"
        快照目录.mkdir(parents=True, exist_ok=True)
        try:
            return self._写快照(快照目录)
        except BaseException:
            # 清单是最后一步：任何异常都意味着本快照未被认证，整目录回收（不留半份状态）。
            shutil.rmtree(快照目录, ignore_errors=True)
            raise

    def _写快照(self, 快照目录: Path) -> dict:
        """写一份完整快照并返回清单（清单最后写入 = 认证标记）。"""
        # 合并 WAL 回主库，尽力而为：经唯一入口的只读查询能力执行 checkpoint PRAGMA
        # （checkpoint 不能在显式事务内跑，实测走 事务执行 报「database table is locked」，
        #  故只能走 查询；它不改业务数据）。失败不阻断备份，但必须留痕（哲学第 3 条 2 项）。
        合并结果 = 查询(str(self.存储根目录 / "权威状态.db"),
                        "PRAGMA wal_checkpoint(TRUNCATE)", 超时秒=10)
        if not 合并结果.成功:
            记录忽略("备份执行.WAL合并", f"{合并结果.错误码}: {合并结果.错误说明}")
        契约 = self.声明契约()
        文件清单 = {类: self._备份一类(类, 快照目录) for 类 in 四类数据表}
        清单 = {"快照目录": str(快照目录), "备份时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "契约": {类: {键: 值 for 键, 值 in 契约[类].items() if 键 != "校验方法"}
                         for 类 in 四类数据表},
                "文件": 文件清单}
        (快照目录 / 清单文件名).write_text(
            json.dumps(清单, ensure_ascii=False, indent=2), encoding="utf-8")
        return 清单
