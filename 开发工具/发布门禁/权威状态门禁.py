"""发布门禁中的权威状态生产场景。"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "测试中心").is_dir():
        系统根 = _祖先
        break


def _创建旧库(目录: Path, *, 中断迁移: bool = False) -> None:
    连接 = sqlite3.connect(str(目录 / "权威状态.db"))
    连接.executescript("""
        CREATE TABLE 元信息(键 TEXT PRIMARY KEY, 值 TEXT);
        CREATE TABLE 句柄(句柄id TEXT PRIMARY KEY, 句柄类型 TEXT, 资源id TEXT,
            项目id TEXT, 所有者 TEXT, 状态 TEXT, 版本 TEXT,
            创建时间 TEXT, 失效时间 TEXT, 失效原因 TEXT);
        CREATE TABLE 租约(租约id TEXT PRIMARY KEY, 资源id TEXT, 项目id TEXT, 所有者 TEXT,
            句柄id TEXT, 空闲超时秒 REAL, 硬截止时间 REAL, 最后心跳 REAL, 已回收 INTEGER);
        CREATE TABLE 资源版本(资源id TEXT PRIMARY KEY, 版本 TEXT, 值 TEXT, 摘要 TEXT, 更新时间 TEXT);
        CREATE TABLE 事务(事务id TEXT PRIMARY KEY, 资源id TEXT, 句柄id TEXT, 基础版本 TEXT,
            状态 TEXT, 结果 TEXT, 新版本 TEXT, 创建时间 TEXT, 提交时间 TEXT);
        CREATE TABLE 锁(资源id TEXT PRIMARY KEY, 持有者 TEXT, 锁时间 TEXT);
        CREATE TABLE 进程(身份键 TEXT PRIMARY KEY, 进程id INTEGER, 启动指纹 TEXT,
            项目id TEXT, 所有者 TEXT, 实例id TEXT, 最后心跳 REAL);
        CREATE TABLE 回收证据(证据id TEXT PRIMARY KEY, 句柄id TEXT, 资源id TEXT, 类型 TEXT,
            失效原因 TEXT, 时间 TEXT, 版本 TEXT);
        CREATE TABLE 引用计数(引用键 TEXT PRIMARY KEY, 包id TEXT, 版本 TEXT, 计数 INTEGER);
    """)
    连接.execute("INSERT INTO 元信息 VALUES('结构版本', '1.0.0')")
    连接.execute(
        "INSERT INTO 资源版本 VALUES('老资源', '0', '{\"内容\": \"旧数据\"}', '', '')")
    if 中断迁移:
        连接.execute("ALTER TABLE 资源版本 ADD COLUMN 栅栏令牌 INTEGER DEFAULT 0")
    连接.commit()
    连接.close()


def _旧库迁移() -> str:
    from 运行核心.权威状态 import 权威状态, 状态结构版本

    with tempfile.TemporaryDirectory(prefix="门禁_旧库迁移_") as 临时目录:
        目录 = Path(临时目录)
        _创建旧库(目录)
        状态 = 权威状态(目录)
        结构正常, 说明 = 状态.校验结构()
        资源 = 状态.读取资源("老资源")
        版本 = sqlite3.connect(str(目录 / "权威状态.db")).execute(
            "SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        状态.关闭()
        if not (结构正常 and 版本 == 状态结构版本 and 资源["值"]["内容"] == "旧数据"):
            raise AssertionError(f"迁移结果异常: {说明} / {版本} / {资源}")
        return f"旧数据保留，结构版本 {版本}"


def _中断迁移恢复() -> str:
    from 运行核心.权威状态 import 权威状态

    with tempfile.TemporaryDirectory(prefix="门禁_中断迁移_") as 临时目录:
        目录 = Path(临时目录)
        _创建旧库(目录, 中断迁移=True)
        状态 = 权威状态(目录)
        结构正常, 说明 = 状态.校验结构()
        状态.关闭()
        if not 结构正常:
            raise AssertionError(说明)
        return "部分列已存在的中断迁移可幂等恢复"


def _陈旧写者拒绝() -> str:
    from 运行核心.权威状态 import 权威状态

    with tempfile.TemporaryDirectory(prefix="门禁_陈旧写者_") as 临时目录:
        状态 = 权威状态(Path(临时目录), 项目id="门禁", 所有者="门禁")
        状态.初始化资源("资源", {"值": 0})
        成功甲, _, 令牌甲 = 状态.获取锁(
            "资源", 事务id="甲", 进程身份键="进程甲", 项目id="门禁", 所有者="门禁")
        状态.释放锁("资源", 事务id="甲", 进程身份键="进程甲", 令牌=令牌甲)
        成功乙, _, 令牌乙 = 状态.获取锁(
            "资源", 事务id="乙", 进程身份键="进程乙", 项目id="门禁", 所有者="门禁")
        旧成功, 旧说明 = 状态.提交资源(
            资源id="资源", 期望版本="0", 期望令牌=str(令牌甲),
            事务id="甲", 进程身份键="进程甲", 新值={"值": 1}, 新摘要="甲")
        新成功, 新说明 = 状态.提交资源(
            资源id="资源", 期望版本="0", 期望令牌=str(令牌乙),
            事务id="乙", 进程身份键="进程乙", 项目id="门禁", 所有者="门禁",
            新值={"值": 2}, 新摘要="乙")
        状态.关闭()
        if not (成功甲 and 成功乙 and 令牌乙 > 令牌甲 and not 旧成功 and 新成功):
            raise AssertionError(f"陈旧写者门禁异常: {旧说明} / {新说明}")
        return f"旧令牌 {令牌甲} 被拒，新令牌 {令牌乙} 成功"


def _强杀持锁恢复() -> str:
    from 运行核心.权威状态 import 权威状态

    with tempfile.TemporaryDirectory(prefix="门禁_强杀持锁_") as 临时目录:
        目录 = Path(临时目录)
        脚本 = """
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from 运行核心.权威状态 import 权威状态
状态 = 权威状态(Path(sys.argv[2]), 项目id="门禁", 所有者="死进程")
状态.初始化资源("资源", {"值": 0})
成功, _, 令牌 = 状态.获取锁(
    "资源", 事务id="死事务", 进程身份键=状态.身份.身份键(),
    项目id="门禁", 所有者="死进程")
print(json.dumps({"成功": 成功, "令牌": 令牌}), flush=True)
time.sleep(30)
"""
        进程 = subprocess.Popen(
            [sys.executable, "-S", "-c", 脚本, str(系统根), str(目录)],
            cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        握手 = json.loads(进程.stdout.readline())
        进程.kill()
        进程.wait(timeout=5)
        状态 = 权威状态(目录, 项目id="门禁", 所有者="接管者")
        清理 = 状态.清理死亡进程资源(项目id="门禁", 所有者="死进程")
        成功, _, 新令牌 = 状态.获取锁(
            "资源", 事务id="新事务", 进程身份键=状态.身份.身份键(),
            项目id="门禁", 所有者="接管者")
        状态.关闭()
        if not (握手["成功"] and any("锁" in 条目 for 条目 in 清理)
                and 成功 and 新令牌 > 握手["令牌"]):
            raise AssertionError(f"强杀恢复异常: {握手} / {清理} / {新令牌}")
        return f"死亡锁已回收，令牌 {握手['令牌']} -> {新令牌}"


def _重启令牌单调() -> str:
    from 运行核心.权威状态 import 权威状态

    with tempfile.TemporaryDirectory(prefix="门禁_令牌重启_") as 临时目录:
        目录 = Path(临时目录)
        状态 = 权威状态(目录)
        状态.初始化资源("资源", {})
        _, _, 令牌一 = 状态.获取锁("资源", 事务id="一", 进程身份键="进程一")
        状态.释放锁("资源", 事务id="一", 进程身份键="进程一", 令牌=令牌一)
        状态.关闭()
        重启状态 = 权威状态(目录)
        _, _, 令牌二 = 重启状态.获取锁("资源", 事务id="二", 进程身份键="进程二")
        重启状态.关闭()
        if 令牌二 <= 令牌一:
            raise AssertionError(f"令牌回退: {令牌一} -> {令牌二}")
        return f"重启后令牌 {令牌一} -> {令牌二}"


def _快照恢复一致() -> str:
    from 运行核心.资源协调 import 资源协调器

    with tempfile.TemporaryDirectory(prefix="门禁_快照恢复_") as 临时目录:
        协调 = 资源协调器(Path(临时目录))
        协调.初始化资源("资源", {"值": 0})
        事务id, 句柄id, _, _ = 协调.创建修改事务("资源")
        协调.修改工作副本(事务id, {"值": 1})
        成功, 说明, 新版本 = 协调.提交(
            事务id=事务id, 句柄id=句柄id, 资源id="资源")
        快照 = 协调.快照目录 / f"资源@{新版本}"
        import shutil
        shutil.rmtree(快照)
        恢复 = 协调.恢复缺失快照()
        值 = 协调.读取快照值("资源", 新版本)
        协调.状态.关闭()
        if not (成功 and f"资源@{新版本}" in 恢复 and 值 == {"值": 1}):
            raise AssertionError(f"快照恢复异常: {说明} / {恢复} / {值}")
        return f"权威版本 {新版本} 的缺失快照已重建"


def _错误身份释放拒绝() -> str:
    from 运行核心.权威状态 import 权威状态

    with tempfile.TemporaryDirectory(prefix="门禁_释放身份_") as 临时目录:
        状态 = 权威状态(Path(临时目录))
        状态.初始化资源("资源", {})
        成功, _, 令牌 = 状态.获取锁(
            "资源", 事务id="正确事务", 进程身份键="正确进程")
        错误释放 = 状态.释放锁(
            "资源", 事务id="错误事务", 进程身份键="错误进程", 令牌=令牌)
        仍持有 = bool(状态.锁持有者("资源"))
        正确释放 = 状态.释放锁(
            "资源", 事务id="正确事务", 进程身份键="正确进程", 令牌=令牌)
        状态.关闭()
        if not (成功 and not 错误释放 and 仍持有 and 正确释放):
            raise AssertionError("错误身份释放锁未被完整拒绝")
        return "错误身份拒绝，正确身份释放成功"


def 执行权威状态门禁() -> list[tuple[str, bool, str]]:
    """运行七项生产场景，每项独立返回可复核证据。"""
    场景表: list[tuple[str, Callable[[], str]]] = [
        ("真实旧库迁移", _旧库迁移),
        ("中断迁移恢复", _中断迁移恢复),
        ("陈旧写者栅栏拒绝", _陈旧写者拒绝),
        ("强杀持锁进程恢复", _强杀持锁恢复),
        ("栅栏令牌重启单调", _重启令牌单调),
        ("权威状态与快照一致", _快照恢复一致),
        ("错误身份释放锁拒绝", _错误身份释放拒绝),
    ]
    结果表: list[tuple[str, bool, str]] = []
    for 名称, 场景 in 场景表:
        try:
            结果表.append((名称, True, 场景()))
        except Exception as 错误:
            结果表.append((名称, False, f"{type(错误).__name__}: {错误}"))
    return 结果表

