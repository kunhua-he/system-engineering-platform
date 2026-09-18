"""备份恢复演练的核对引擎（B7）：副本构建、四类数据一致性核对、反向验证。

为什么单独成文件：`开发工具/备份恢复演练.py` 是**主入口**，只做调度与输出（口径：主入口尽量只
调度）；核对算法（逐表行数/全行指纹、逐条关键字段、逐文件 sha256）与副本构建是本工具里唯一有
判断逻辑的部分，拆在这里便于单独复核与复用。

口径红线：
- **空集不判绿**：源副本某类数据为空 ⇒ 「无可核对」判不出结论，必须报红，不得当通过
  （否则「什么都没恢复」会被算成「核对一致」）。
- 只读：核对一律 `mode=ro` 打开且**立即关闭连接**——留在打开态会挡住恢复能力的
  `BEGIN EXCLUSIVE` 独占锁，把「恢复被自己的核对连接挡死」伪装成「恢复失败」。
- 绝不碰生产数据根：一切读写都发生在受管临时目录的副本里。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from 公共契约.运行时.数据库URI import 只读库URI


def _查询(库: Path, SQL: str, 参数: tuple = ()) -> list:
    """只读查询并**立即关闭连接**（打开态会挡住恢复的 BEGIN EXCLUSIVE 独占锁）。"""
    with contextlib.closing(sqlite3.connect(只读库URI(库), uri=True, timeout=10)) as 连接:
        return 连接.execute(SQL, 参数).fetchall()


def _指纹(对象: Any) -> str:
    return hashlib.sha256(
        json.dumps(对象, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _表快照(库: Path) -> dict:
    """逐表 `{表: (行数, 全行取值指纹)}`；指纹按排序后的全列取值算，防「行数一样内容不同」。"""
    出 = {}
    for 表 in [行[0] for 行 in _查询(库, "select name from sqlite_master where type='table' order by name")]:
        行列表 = _查询(库, f'select * from "{表}"')
        出[表] = (len(行列表), _指纹(sorted(str(值) for 行 in 行列表 for 值 in 行)))
    return 出


def _证据行(库: Path) -> list:
    if not _查询(库, "select name from sqlite_master where type='table' and name='证据'"):
        return []
    return sorted((str(行[0]), str(行[-1])) for 行 in _查询(库, "select * from 证据"))


def _制品表(目录: Path) -> dict:
    return {文件.relative_to(目录).as_posix(): hashlib.sha256(文件.read_bytes()).hexdigest()
            for 文件 in sorted(目录.rglob("*")) if 文件.is_file()} if 目录.is_dir() else {}


def 核对一致性(源根: Path, 目标根: Path) -> dict:
    """按备份契约四类数据逐类核对（权威状态/证据账本/包仓库/项目锁）；空集不判绿。"""
    差异: list[str] = []
    类结果: list[dict] = []

    def 记(类名: str, 件数: int, 本类: list[str]) -> None:
        差异.extend(本类)
        类结果.append({"类": 类名, "一致": not 本类, "件数": 件数, "差异": 本类})

    源库, 目标库 = 源根 / "权威状态.db", 目标根 / "权威状态.db"
    if not 目标库.is_file():
        记("权威状态", 0, [f"恢复副本缺权威状态库：{目标库}"])
    else:
        源, 目标 = _表快照(源库), _表快照(目标库)
        本类 = [f"表 {表} 在恢复副本{'缺失' if 表 not in 目标 else '多余'}" for 表 in sorted(set(源) ^ set(目标))]
        本类 += [f"表 {表} 行数 {源[表][0]}→{目标[表][0]}" if 源[表][0] != 目标[表][0]
                else f"表 {表} 全行指纹不符（行数同为 {源[表][0]}）"
                for 表 in sorted(set(源) & set(目标)) if 源[表] != 目标[表]]
        if not 源:
            本类.append("源副本零表（空集不判绿）")
        记("权威状态", sum(项[0] for 项 in 源.values()), 本类)
    源证据 = _证据行(源库) if 源库.is_file() else []
    目标证据 = _证据行(目标库) if 目标库.is_file() else []
    if not 源证据:
        记("证据账本", 0, ["源副本证据账本为空（空集不判绿）"])
    else:
        记("证据账本", len(源证据), [] if 源证据 == 目标证据
           else [f"证据条数/关键字段（证据id/哈希）不符：{len(源证据)}→{len(目标证据)}"])
    源制品, 目标制品 = _制品表(源根 / "制品"), _制品表(目标根 / "制品")
    if not 源制品:
        记("包仓库", 0, ["源副本无制品（空集不判绿）"])
    else:
        记("包仓库", len(源制品),
           [f"制品缺失或摘要不符: {相对}" for 相对 in sorted(源制品) if 目标制品.get(相对) != 源制品[相对]]
           + [f"恢复副本多余制品: {相对}" for 相对 in sorted(set(目标制品) - set(源制品))])
    源锁, 目标锁 = 源根 / "项目锁.json", 目标根 / "项目锁.json"
    取值 = lambda 路径: {键: str(json.loads(路径.read_text(encoding="utf-8")).get(键, ""))
                      for 键 in ("项目id", "所有者", "锁定时间")}
    if not 源锁.is_file():
        记("项目锁", 0, ["源副本无 项目锁.json（空集不判绿）"])
    elif not 目标锁.is_file():
        记("项目锁", 1, ["恢复副本缺 项目锁.json"])
    else:
        记("项目锁", 1, [] if 取值(源锁) == 取值(目标锁)
           else ["项目锁关键字段（项目id/所有者/锁定时间）不符"])
    return {"一致": not 差异, "类结果": 类结果, "差异": 差异}


def 建源副本(生产根: Path, 副本根: Path, 制品夹具: Path) -> dict:
    """建演练源副本：生产逐类真实复制（权威状态走只读 `VACUUM INTO` 一致性快照）。

    生产数据根当前缺 `制品/` 与 `项目锁.json`（实测），这类「缺失类」按需补**真实文件夹具**
    （不是造假数据），并在 `逐类来源` 里逐类标注，让报告能分清「恢复了生产真数据」与
    「恢复的是演练夹具」——不标注等于把夹具伪装成生产数据。
    """
    副本根.mkdir(parents=True, exist_ok=True)
    来源: dict[str, str] = {}
    if (生产根 / "权威状态.db").is_file():
        with contextlib.closing(sqlite3.connect(
                只读库URI(生产根 / '权威状态.db'), uri=True, timeout=10)) as 连接:
            连接.execute("VACUUM INTO ?", (str(副本根 / "权威状态.db"),))
        来源["权威状态"] = "生产副本（VACUUM INTO 一致性快照）"
    if (生产根 / "制品").is_dir():
        shutil.copytree(生产根 / "制品", 副本根 / "制品", dirs_exist_ok=True)
        来源["包仓库"] = "生产副本"
    elif 制品夹具.is_file():
        (副本根 / "制品").mkdir(parents=True, exist_ok=True)
        shutil.copy2(制品夹具, 副本根 / "制品" / 制品夹具.name)
        来源["包仓库"] = f"演练夹具（真实文件副本：{制品夹具.name}；生产数据根缺 制品/）"
    if (生产根 / "项目锁.json").is_file():
        shutil.copy2(生产根 / "项目锁.json", 副本根 / "项目锁.json")
        来源["项目锁"] = "生产副本"
    else:
        (副本根 / "项目锁.json").write_text(json.dumps(
            {"项目id": "系统工程平台.底座", "所有者": "小马仔（备份恢复演练）",
             "锁定时间": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
        来源["项目锁"] = "演练自建（生产数据根缺 项目锁.json）"
    return 来源


def 破坏恢复副本(恢复根: Path) -> None:
    """反向验证第 1 步：真实删掉恢复副本的一行（`元信息` 表在 VACUUM 快照里必有且非空）。"""
    with contextlib.closing(sqlite3.connect(str(恢复根 / "权威状态.db"))) as 连接:
        连接.execute("delete from 元信息")
        连接.commit()


def 反向验证(源根: Path, 恢复根: Path, 备份根: Path, 存储: dict, 恢复调用) -> dict:
    """弄坏恢复副本 → 核对必须变红；重新恢复 → 必须变绿。任一步不符预期即 `符合预期=False`。"""
    破坏恢复副本(恢复根)
    破坏后 = 核对一致性(源根, 恢复根)
    还原 = 恢复调用({"备份目录": str(备份根), "目标目录": str(恢复根), **存储})
    还原后 = 核对一致性(源根, 恢复根)
    return {"破坏后一致": 破坏后["一致"], "破坏后差异": 破坏后["差异"],
            "还原恢复成功": bool(还原["成功"]), "还原恢复结果": 还原["结果"],
            "还原后一致": 还原后["一致"], "还原后差异": 还原后["差异"],
            "符合预期": (not 破坏后["一致"]) and 还原后["一致"]}
