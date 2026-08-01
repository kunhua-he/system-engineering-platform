"""恢复执行能力：备份定位、版本回退检测与单类恢复（权威数据备份契约 mixin）。"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


class 恢复执行能力:
    """恢复执行能力：按契约顺序恢复四类数据并逐类真实校验。"""

    def _定位清单(self, 备份目录: Path) -> dict:
        """备份目录直接含清单则用之；否则取最新时间戳快照。"""
        备份目录 = Path(备份目录)
        清单文件 = 备份目录 / "备份清单.json"
        if not 清单文件.is_file():
            候选 = sorted(备份目录.glob("快照_*"), reverse=True)
            if not 候选:
                raise FileNotFoundError(f"备份目录无任何备份: {备份目录}")
            清单文件 = 候选[0] / "备份清单.json"
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
                附加 = 快照目录 / f"权威状态.db{后缀}"
                if 附加.is_file():
                    shutil.copy2(附加, 目标目录 / f"权威状态.db{后缀}")
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
        for 类名 in 顺序类表:
            备份项 = 清单["文件"].get(类名, {})
            if 备份项.get("缺失"):
                结果表.append({"类": 类名, "成功": False, "原因": "备份缺失"})
                continue
            校验目录 = self._恢复一类(类名, 快照目录, 目标目录)
            成功, 原因 = 契约表[类名]["校验方法"](校验目录, 备份项)
            结果表.append({"类": 类名, "成功": 成功, "原因": 原因})
        return {"成功": bool(结果表) and all(项["成功"] for 项 in 结果表),
                "恢复顺序": 顺序类表, "结果": 结果表, "目标目录": str(目标目录),
                "回退警告": 回退警告}
