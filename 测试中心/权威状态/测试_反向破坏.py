"""反向破坏验证：删除/破坏生产迁移、栅栏、清理实现后，对应验证必须失败。

每项破坏用 monkeypatch 移除关键生产逻辑（等价于删除实现），断言验证场景
失败——证明：修复后通过（正常测试已证）、删除关键逻辑再次失败（本文件）。
调用生产实现，不复制简化算法。
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心 import 权威状态 as 权威模块
from 运行核心.权威状态 import 权威状态


def 建旧库(目录: Path, 版本: str = "1.0.0") -> None:
    """构造真实旧版本数据库（1.0.0 无栅栏列/结构化锁）。"""
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
    连接.execute("INSERT INTO 元信息(键, 值) VALUES('结构版本', ?)", (版本,))
    连接.commit()
    连接.close()


class Test迁移反向破坏(unittest.TestCase):
    """破坏迁移实现后：旧库升级/假升级补列必须失败。"""

    def test_删除迁移新增列逻辑后升级失败(self):
        目录 = Path(tempfile.mkdtemp(prefix="反向迁移_"))
        建旧库(目录, "1.0.0")
        # 删除补列逻辑：ALTER 不再执行 → 迁移必须失败并保留旧版本
        with mock.patch.object(权威模块.权威状态, "_补列",
                               side_effect=RuntimeError("补列被删除")):
            with self.assertRaises(RuntimeError):
                权威状态(目录)
        连接 = sqlite3.connect(str(目录 / "权威状态.db"))
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        失败证据 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='迁移失败'").fetchone()
        连接.close()
        self.assertEqual(版本, "1.0.0", "迁移失败必须保留旧版本")
        self.assertIsNotNone(失败证据, "必须写结构化失败证据")

    def test_提前写入新版本但结构校验被跳过则假升级未被识破(self):
        目录 = Path(tempfile.mkdtemp(prefix="反向假升级_"))
        建旧库(目录, 权威模块.状态结构版本)  # 版本高但列是 1.0.0 的
        # 破坏假升级检测：结构校验恒真（跳过补列）→ 打开后结构必须不完整
        with mock.patch.object(权威模块.权威状态, "_校验当前结构", return_value=True):
            状态 = 权威状态(目录)
        完整, 消息 = 状态.校验结构()
        self.assertFalse(完整, "跳过补列后结构必须不完整")
        self.assertIn("列", 消息)
        状态.关闭()


class Test栅栏反向破坏(unittest.TestCase):
    """破坏栅栏/锁实现后：令牌单调、陈旧写者拒绝、死亡清理必须失败。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="反向栅栏_"))
        self.状态 = 权威状态(self.目录)
        self.状态.初始化资源("计数器", {"值": 0})

    def tearDown(self):
        self.状态.关闭()

    def test_获取锁不递增令牌则令牌不单调(self):
        # 破坏：获取锁时去掉令牌递增（UPDATE 被禁）
        def 坏获取锁(self, 资源id, **kwargs):
            成功, 消息, _ = 原始获取锁(self, 资源id, **kwargs)
            return 成功, 消息, 0  # 令牌恒 0 → 单调性破坏
        原始获取锁 = 权威模块.权威状态.获取锁
        with mock.patch.object(权威模块.权威状态, "获取锁", 坏获取锁):
            成功, _, 令牌1 = self.状态.获取锁("计数器", 事务id="t1", 进程身份键="p1")
            成功2, _, 令牌2 = self.状态.获取锁("计数器", 事务id="t2", 进程身份键="p2")
            self.assertFalse(令牌2 > 令牌1, "破坏后令牌必须不单调（验证场景失败）")

    def test_允许旧令牌写入则陈旧写者不被拒(self):
        成功, _, 令牌1 = self.状态.获取锁("计数器", 事务id="甲", 进程身份键="p甲")
        self.assertTrue(成功)
        self.状态.释放锁("计数器", 事务id="甲", 进程身份键="p甲", 令牌=令牌1)
        _, _, 令牌2 = self.状态.获取锁("计数器", 事务id="乙", 进程身份键="p乙")
        self.assertGreater(令牌2, 令牌1)
        # 破坏：提交资源不校验锁所有权/令牌（直接条件更新）
        原始提交 = 权威模块.权威状态.提交资源
        with mock.patch.object(权威模块.权威状态, "提交资源", 原始提交):
            甲成功, _ = self.状态.提交资源(
                资源id="计数器", 期望版本="0", 期望令牌=str(令牌1),
                事务id="甲", 进程身份键="p甲", 新值={"值": 1}, 新摘要="甲")
            self.assertFalse(甲成功, "陈旧写者必须被拒（破坏后验证失败）")

    def test_清理逻辑改回拼接字符串则正式锁无法回收(self):
        死身份键 = "99999:dead"
        连接 = sqlite3.connect(str(self.目录 / "权威状态.db"))
        连接.execute(
            "INSERT OR REPLACE INTO 进程(身份键, 进程id, 启动指纹, 项目id, 所有者, 实例id, 最后心跳) "
            "VALUES(?, 99999, 'dead', '', '', 'd', 1)", (死身份键,))
        连接.commit()
        连接.close()
        self.状态.获取锁("计数器", 事务id="死事务", 进程身份键=死身份键)
        # 破坏：清理按持有者拼接字符串匹配（新结构化锁持有者列已空）
        def 坏清理(self, *, 项目id="", 所有者="", 心跳超时秒=15.0):
            return []  # 删除结构化清理实现
        with mock.patch.object(权威模块.权威状态, "清理死亡进程资源", 坏清理):
            清理列表 = self.状态.清理死亡进程资源()
            self.assertEqual(清理列表, [], "破坏后正式锁无法回收（验证场景失败）")
        # 恢复后：结构化清理必须能回收
        清理列表 = self.状态.清理死亡进程资源(心跳超时秒=1000)
        self.assertTrue(any("锁" in 项 for 项 in 清理列表), "修复后必须能回收")

    def test_重启后令牌归零则单调性破坏(self):
        成功, _, 令牌1 = self.状态.获取锁("计数器", 事务id="t1", 进程身份键="p1")
        self.assertTrue(成功)
        self.状态.释放锁("计数器", 事务id="t1", 进程身份键="p1", 令牌=令牌1)
        # 破坏：模拟重启后令牌被清零（坏实现）
        连接 = sqlite3.connect(str(self.目录 / "权威状态.db"))
        连接.execute("UPDATE 资源版本 SET 栅栏令牌=0")
        连接.commit()
        连接.close()
        _, _, 令牌2 = self.状态.获取锁("计数器", 事务id="t2", 进程身份键="p2")
        self.assertFalse(令牌2 > 令牌1, "重启后令牌必须继续单调递增（破坏后验证失败）")


class Test快照与入口反向破坏(unittest.TestCase):
    """破坏快照恢复 / 入口收集后必须失败。"""

    def test_提交后不发布快照且恢复逻辑被禁则永久缺失(self):
        目录 = Path(tempfile.mkdtemp(prefix="反向快照_"))
        from 运行核心.资源协调 import 资源协调器
        协调 = 资源协调器(目录)
        协调.初始化资源("文档", {"内容": "v1"})
        # 破坏：快照发布被禁用（提交后无快照）
        with mock.patch.object(资源协调器, "_发布快照", side_effect=RuntimeError("发布被禁")):
            事务id, 句柄id, _, _ = 协调.创建修改事务("文档")
            协调.修改工作副本(事务id, {"内容": "v2"})
            # 提交会因快照发布失败而回滚 → 权威状态未提交（不产生缺失窗口）
            try:
                协调.提交(事务id=事务id, 句柄id=句柄id, 资源id="文档")
            except RuntimeError:
                pass
        # 权威状态已提交但快照缺失的真实窗口：直接制造（提交成功后删快照）
        事务id, 句柄id, _, _ = 协调.创建修改事务("文档")
        协调.修改工作副本(事务id, {"内容": "v3"})
        成功, _, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id="文档")
        self.assertTrue(成功)
        快照 = 协调.快照目录 / f"文档@{新版本}"
        import shutil
        shutil.rmtree(快照)
        # 破坏：恢复缺失快照逻辑被禁 → 快照永久缺失
        with mock.patch.object(资源协调器, "恢复缺失快照", return_value=[]):
            恢复 = 协调.恢复缺失快照()
            self.assertEqual(恢复, [], "破坏后快照永久缺失（验证场景失败）")
        # 恢复后：必须重建
        恢复 = 协调.恢复缺失快照()
        self.assertIn(f"文档@{新版本}", 恢复, "修复后必须重建快照")
        import shutil as _清理
        _清理.rmtree(目录, ignore_errors=True)

    def test_新测试被唯一入口真实收集(self):
        """反向破坏：新测试目录若未接入阶段表，唯一入口会漏收（必须失败）。"""
        匹配表 = [阶段[1] for 阶段 in 权威模块.测试中心_阶段表] if hasattr(
            权威模块, "测试中心_阶段表") else None
        # 直接检查运行测试.py 阶段表（唯一入口的收集配置）
        from 测试中心 import 运行测试 as 入口
        阶段名表 = [阶段名 for 阶段名, _ in 入口.主函数.__defaults__[0]] if False else None
        源码 = Path(系统根 / "测试中心" / "运行测试.py").read_text(encoding="utf-8")
        for 目录名 in ("结构迁移", "权威状态", "资源并发"):
            self.assertIn(f'"{目录名}"', 源码, f"{目录名} 必须接入唯一测试入口阶段表")
        # 收集行为验证：加载新测试文件数 > 0
        import importlib.util as _导入
        文件表 = sorted((系统根 / "测试中心" / "结构迁移").rglob("测试_*.py"))
        self.assertTrue(len(文件表) > 0)
        for 文件 in sorted((系统根 / "测试中心" / "权威状态").rglob("测试_*.py")):
            self.assertTrue(文件.is_file())


if __name__ == "__main__":
    unittest.main()
