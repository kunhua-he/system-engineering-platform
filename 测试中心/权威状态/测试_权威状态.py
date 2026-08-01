"""权威状态测试：锁所有权校验 / 栅栏令牌单调 / 连接回收 / WAL 备份 / 损坏恢复。

覆盖任务信第九节第 8、9、11 项；调用生产实现，禁止复制简化算法。
"""
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.权威状态 import 权威状态


class Test锁所有权(unittest.TestCase):
    """错误身份/事务/令牌不能释放或提交他人的锁。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="权威锁_"))
        self.状态 = 权威状态(self.目录, 项目id="测试项目", 所有者="测试者")
        self.状态.初始化资源("文档", {"内容": "v1"})

    def tearDown(self):
        self.状态.关闭()

    def _持锁(self, 事务id: str = "甲事务", 身份键: str = "进程甲") -> int:
        成功, _, 令牌 = self.状态.获取锁(
            "文档", 事务id=事务id, 进程身份键=身份键,
            项目id="测试项目", 所有者="测试者")
        self.assertTrue(成功)
        return 令牌

    def test_错误进程不能释放他人锁(self):
        令牌 = self._持锁()
        self.assertFalse(self.状态.释放锁("文档", 事务id="甲事务",
                                         进程身份键="进程乙", 令牌=令牌),
                         "错误进程不能释放锁")
        self.assertTrue(self.状态.锁持有者("文档"), "锁仍在")

    def test_错误事务不能释放他人锁(self):
        令牌 = self._持锁()
        self.assertFalse(self.状态.释放锁("文档", 事务id="乙事务",
                                         进程身份键="进程甲", 令牌=令牌),
                         "错误事务不能释放锁")

    def test_错误令牌不能释放锁(self):
        令牌 = self._持锁()
        self.assertFalse(self.状态.释放锁("文档", 事务id="甲事务",
                                         进程身份键="进程甲", 令牌=令牌 + 1),
                         "错误令牌不能释放锁")

    def test_错误身份不能提交(self):
        令牌 = self._持锁()
        成功, 消息 = self.状态.提交资源(
            资源id="文档", 期望版本="0", 期望令牌=str(令牌),
            事务id="甲事务", 进程身份键="进程乙", 新值={"内容": "x"}, 新摘要="s")
        self.assertFalse(成功)
        self.assertIn("所有权", 消息)

    def test_无锁不能提交(self):
        成功, 消息 = self.状态.提交资源(
            资源id="文档", 期望版本="0", 期望令牌="0",
            事务id="甲事务", 进程身份键="进程甲", 新值={"内容": "x"}, 新摘要="s")
        self.assertFalse(成功)
        self.assertIn("锁", 消息)


class Test栅栏令牌(unittest.TestCase):
    """失败提交后令牌不回退；重启后继续单调递增；锁授予即签发。"""

    def test_失败提交后令牌不回退(self):
        目录 = Path(tempfile.mkdtemp(prefix="权威令牌_"))
        状态 = 权威状态(目录)
        状态.初始化资源("计数器", {"值": 0})
        成功, _, 令牌1 = 状态.获取锁("计数器", 事务id="事务甲", 进程身份键="进程甲")
        self.assertTrue(成功)
        self.assertEqual(令牌1, 1, "首次授锁令牌=1")
        # 提交失败（期望版本错误）→ 令牌不回退
        失败, _ = 状态.提交资源(
            资源id="计数器", 期望版本="9", 期望令牌=str(令牌1),
            事务id="事务甲", 进程身份键="进程甲", 新值={"值": 1}, 新摘要="s")
        self.assertFalse(失败)
        资源 = 状态.读取资源("计数器")
        self.assertEqual(资源["栅栏令牌"], 1, "失败提交后令牌不回退")
        状态.释放锁("计数器", 事务id="事务甲", 进程身份键="进程甲", 令牌=令牌1)
        状态.关闭()
        # 重启后继续单调递增
        状态2 = 权威状态(目录)
        成功, _, 令牌2 = 状态2.获取锁("计数器", 事务id="事务乙", 进程身份键="进程乙")
        self.assertTrue(成功)
        self.assertGreater(令牌2, 令牌1, "重启后令牌继续单调递增")
        状态2.关闭()

    def test_锁授予与版本独立递增(self):
        状态 = 权威状态(Path(tempfile.mkdtemp(prefix="权威令牌2_")))
        状态.初始化资源("计数器", {"值": 0})
        _, _, 令牌1 = 状态.获取锁("计数器", 事务id="t1", 进程身份键="p1")
        成功, _ = 状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(令牌1),
            事务id="t1", 进程身份键="p1", 新值={"值": 1}, 新摘要="s1")
        self.assertTrue(成功)
        状态.释放锁("计数器", 事务id="t1", 进程身份键="p1", 令牌=令牌1)
        资源 = 状态.读取资源("计数器")
        self.assertEqual(资源["版本"], "1", "提交后版本+1")
        self.assertEqual(资源["栅栏令牌"], 令牌1, "提交不递增令牌（令牌只在授锁时递增）")
        # 再授锁 → 令牌2（>令牌1），版本仍 1
        _, _, 令牌2 = 状态.获取锁("计数器", 事务id="t2", 进程身份键="p2")
        self.assertEqual(令牌2, 令牌1 + 1)
        资源 = 状态.读取资源("计数器")
        self.assertEqual(资源["版本"], "1")
        状态.关闭()

    def test_陈旧写者旧令牌被拒新令牌提交成功(self):
        目录 = Path(tempfile.mkdtemp(prefix="权威令牌3_"))
        状态 = 权威状态(目录, 项目id="项目", 所有者="所有者")
        状态.初始化资源("计数器", {"值": 0})
        # 写者甲拿锁令牌1 → 模拟锁被清理（进程死亡回收）
        成功, _, 令牌1 = 状态.获取锁(
            "计数器", 事务id="甲事务", 进程身份键="进程甲",
            项目id="项目", 所有者="所有者")
        self.assertTrue(成功)
        状态.释放锁("计数器", 事务id="甲事务", 进程身份键="进程甲", 令牌=令牌1)
        # 写者乙拿锁令牌2
        成功, _, 令牌2 = 状态.获取锁(
            "计数器", 事务id="乙事务", 进程身份键="进程乙",
            项目id="项目", 所有者="所有者")
        self.assertTrue(成功)
        self.assertGreater(令牌2, 令牌1)
        # 甲恢复带令牌1提交 → 必须被拒
        甲成功, 甲消息 = 状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(令牌1),
            事务id="甲事务", 进程身份键="进程甲", 新值={"值": 1}, 新摘要="甲")
        self.assertFalse(甲成功, "陈旧写者必须被拒")
        # 乙带令牌2提交 → 成功
        乙成功, 乙消息 = 状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(令牌2),
            事务id="乙事务", 进程身份键="进程乙",
            项目id="项目", 所有者="所有者", 新值={"值": 2}, 新摘要="乙")
        self.assertTrue(乙成功, f"新写者必须成功: {乙消息}")
        资源 = 状态.读取资源("计数器")
        self.assertEqual(资源["值"], {"值": 2})
        self.assertEqual(资源["栅栏令牌"], 令牌2)
        状态.关闭()


class Test可靠性(unittest.TestCase):
    """连接回收 / WAL 备份 / 损坏恢复。"""

    def test_死线程连接被回收(self):
        状态 = 权威状态(Path(tempfile.mkdtemp(prefix="权威连接_")))
        主线程id = threading.get_ident()
        线程id表: list[int] = []
        线程异常表: list[Exception] = []

        def 开连接() -> None:
            try:
                状态._连接().execute("SELECT 1").fetchone()
                线程id表.append(threading.get_ident())
            except Exception as 错误:
                线程异常表.append(错误)

        线程表 = [threading.Thread(target=开连接) for _ in range(5)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join()
        状态._清理死连接()  # 线程已退出 → 死线程连接被回收，仅剩主线程连接
        self.assertEqual(线程异常表, [], f"工作线程建立连接失败: {线程异常表}")
        self.assertGreaterEqual(len(set(线程id表)), 1)
        self.assertTrue(all(线程id not in 状态._连接表 for 线程id in 线程id表))
        self.assertIn(主线程id, 状态._连接表)
        self.assertEqual(len(状态._连接表), 1, "仅主线程连接保留，死线程连接已回收")
        状态.关闭()

    def test_普通读取不隐式回收其他线程连接(self):
        状态 = 权威状态(Path(tempfile.mkdtemp(prefix="权威读取不回收_")))
        工作线程已连接 = threading.Event()
        允许退出 = threading.Event()

        def 保持连接() -> None:
            状态._连接().execute("SELECT 1").fetchone()
            工作线程已连接.set()
            允许退出.wait(1)

        线程 = threading.Thread(target=保持连接)
        线程.start()
        self.assertTrue(工作线程已连接.wait(1))
        连接数 = len(状态._连接表)
        for _ in range(20):
            状态._连接().execute("SELECT 1").fetchone()
        self.assertEqual(len(状态._连接表), 连接数)
        with self.assertRaisesRegex(RuntimeError, "仍有工作线程"):
            状态.关闭()
        允许退出.set()
        线程.join()
        状态.关闭()

    def test_WAL备份与恢复(self):
        目录 = Path(tempfile.mkdtemp(prefix="权威备份_"))
        状态 = 权威状态(目录)
        状态.初始化资源("备份资源", {"值": 1})
        备份路径 = 目录 / "备份" / "自动备份.db"
        自成功 = 状态.备份(备份路径)
        self.assertTrue(自成功)
        self.assertTrue(备份路径.is_file())
        # 从备份恢复
        成功, 消息 = 状态.损坏恢复(备份目录=目录 / "备份")
        self.assertTrue(成功, 消息)
        self.assertEqual(状态.读取资源("备份资源")["值"], {"值": 1})
        状态.关闭()

    def test_损坏检测与恢复(self):
        目录 = Path(tempfile.mkdtemp(prefix="权威损坏_"))
        状态 = 权威状态(目录)
        状态.初始化资源("损坏资源", {"值": 1})
        备份目录 = 目录 / "备份"
        备份目录.mkdir()
        # 用生产备份入口（内部先 WAL checkpoint 再复制，保证备份完整）
        self.assertTrue(状态.备份(备份目录 / "损坏前.db"))
        状态.关闭()  # 关闭所有连接后破坏主库
        # 破坏数据库：整体覆盖为垃圾字节
        数据库路径 = 目录 / "权威状态.db"
        数据库路径.write_bytes(b"corrupt" * 2000)
        # 完整性检测必须发现损坏：integrity_check 返回非 ok 或直接抛 DatabaseError
        校验连接 = sqlite3.connect(f"file:{数据库路径}?mode=ro", uri=True)
        try:
            结果 = 校验连接.execute("PRAGMA integrity_check").fetchone()
            自损坏 = 结果[0] != "ok"
        except sqlite3.DatabaseError:
            自损坏 = True  # 文件完全损坏（file is not a database）同样算检测到损坏
        finally:
            校验连接.close()
        self.assertTrue(自损坏, "破坏后完整性必须非 ok")
        # 损坏恢复：新实例自动检测损坏并从备份恢复 + 结构重新校验
        状态2 = 权威状态(目录)  # __init__ 遇损坏自动恢复（备份存在）
        完整, 校验消息 = 状态2.校验结构()
        self.assertTrue(完整, f"恢复后结构校验: {校验消息}")
        self.assertEqual(状态2.读取资源("损坏资源")["值"], {"值": 1})
        状态2.关闭()


if __name__ == "__main__":
    unittest.main()
