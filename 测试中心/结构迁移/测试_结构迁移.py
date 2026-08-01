"""结构迁移测试：真实旧库升级 / 中断恢复 / 错误历史补列 / 幂等 / 并发迁移。

覆盖任务信第九节第 1、2 项；调用生产迁移器（权威状态.权威状态），禁止复制简化算法。
"""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.权威状态 import 权威状态, 状态结构版本


def 建真实旧库(目录: Path, 版本: str = "1.0.0") -> Path:
    """手工构造真实旧版本数据库（1.0.0 无栅栏列）。"""
    库 = 目录 / "权威状态.db"
    连接 = sqlite3.connect(str(库))
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
    连接.execute(
        "INSERT INTO 资源版本(资源id, 版本, 值, 摘要, 更新时间) "
        "VALUES('老资源', '0', '{\"内容\": \"旧数据\"}', '', '')")
    连接.execute(
        "INSERT INTO 事务(事务id, 资源id, 句柄id, 基础版本, 状态, 结果, 新版本, 创建时间, 提交时间) "
        "VALUES('旧事务', '老资源', '旧句柄', '0', '进行中', '', '', '', '')")
    连接.commit()
    连接.close()
    return 库


class Test真实旧库升级(unittest.TestCase):
    """真实 1.0.0 数据库升级：列、默认值、数据、最终版本。"""

    def test_旧库升级列全数据保留版本正确(self):
        目录 = Path(tempfile.mkdtemp(prefix="迁移升级_"))
        库 = 建真实旧库(目录, "1.0.0")
        状态 = 权威状态(目录)
        连接 = sqlite3.connect(str(库))
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        资源列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(资源版本)").fetchall()}
        事务列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(事务)").fetchall()}
        锁列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(锁)").fetchall()}
        旧资源 = 连接.execute("SELECT 值 FROM 资源版本 WHERE 资源id='老资源'").fetchone()
        旧事务 = 连接.execute("SELECT 状态 FROM 事务 WHERE 事务id='旧事务'").fetchone()
        连接.close()
        self.assertEqual(版本, 状态结构版本)
        self.assertIn("栅栏令牌", 资源列)
        self.assertIn("基础令牌", 事务列)
        self.assertIn("进程身份键", 锁列)
        self.assertEqual(旧资源[0], '{"内容": "旧数据"}', "旧资源不丢失")
        self.assertEqual(旧事务[0], "进行中", "旧事务不丢失")
        完整, 消息 = 状态.校验结构()
        self.assertTrue(完整, 消息)
        状态.关闭()

    def test_中断迁移恢复(self):
        """已加一部分列但未更新版本（中断迁移）→ 打开后补齐剩余列。"""
        目录 = Path(tempfile.mkdtemp(prefix="迁移中断_"))
        库 = 建真实旧库(目录, "1.0.0")
        连接 = sqlite3.connect(str(库))
        连接.execute("ALTER TABLE 资源版本 ADD COLUMN 栅栏令牌 INTEGER DEFAULT 0")
        连接.execute("UPDATE 元信息 SET 值='1.0.0' WHERE 键='结构版本'")  # 列加了一半但版本未更新
        连接.commit()
        连接.close()
        状态 = 权威状态(目录)
        连接 = sqlite3.connect(str(库))
        事务列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(事务)").fetchall()}
        锁列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(锁)").fetchall()}
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        连接.close()
        self.assertEqual(版本, 状态结构版本)
        self.assertIn("基础令牌", 事务列)
        self.assertIn("进程身份键", 锁列)
        状态.关闭()

    def test_错误历史状态补列(self):
        """元信息已写 1.2.0 但列不完整（假升级产物）→ 打开后补列并校验。"""
        目录 = Path(tempfile.mkdtemp(prefix="迁移假升级_"))
        库 = 建真实旧库(目录, 状态结构版本)  # 版本高但列是 1.0.0 的
        状态 = 权威状态(目录)
        连接 = sqlite3.connect(str(库))
        资源列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(资源版本)").fetchall()}
        事务列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(事务)").fetchall()}
        连接.close()
        self.assertIn("栅栏令牌", 资源列)
        self.assertIn("基础令牌", 事务列)
        完整, _ = 状态.校验结构()
        self.assertTrue(完整)
        状态.关闭()

    def test_重复迁移幂等(self):
        """重复执行同一迁移：数据不丢、版本不变、结构稳定。"""
        目录 = Path(tempfile.mkdtemp(prefix="迁移幂等_"))
        库 = 建真实旧库(目录, "1.0.0")
        for _ in range(3):  # 多次打开同一库
            状态 = 权威状态(目录)
            状态.初始化资源("新资源", {"值": 1})
            状态.关闭()
        连接 = sqlite3.connect(str(库))
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        资源数 = 连接.execute("SELECT COUNT(*) FROM 资源版本").fetchone()[0]
        连接.close()
        self.assertEqual(版本, 状态结构版本)
        self.assertEqual(资源数, 2, "重复迁移不重复破坏数据")


class Test并发迁移(unittest.TestCase):
    """多进程同时首次初始化 / 多进程同时升级同一旧库。"""

    def test_多进程同时首次初始化(self):
        目录 = Path(tempfile.mkdtemp(prefix="迁移并发新_"))
        脚本 = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from 运行核心.权威状态 import 权威状态\n"
            "状态 = 权威状态(sys.argv[2], 项目id='并发')\n"
            "状态.初始化资源('并发资源', {'值': 1})\n"
            "print(状态.校验结构()[0])\n"
            "状态.关闭()\n")
        进程表 = []
        for _ in range(4):
            进程 = subprocess.Popen(
                [sys.executable, "-S", "-c", 脚本, str(系统根), str(目录)],
                cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            进程表.append(进程)
        结果 = [进程.communicate(timeout=30) for 进程 in 进程表]
        for 进程, (输出, 错误) in zip(进程表, 结果):
            self.assertEqual(进程.returncode, 0, 错误[-300:])
            self.assertEqual(输出.strip(), "True", 输出)
        连接 = sqlite3.connect(str(目录 / "权威状态.db"))
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        连接.close()
        self.assertEqual(版本, 状态结构版本)

    def test_多进程同时升级同一旧库(self):
        目录 = Path(tempfile.mkdtemp(prefix="迁移并发旧_"))
        建真实旧库(目录, "1.0.0")
        脚本 = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from 运行核心.权威状态 import 权威状态\n"
            "状态 = 权威状态(sys.argv[2], 项目id='并发升级')\n"
            "print(状态.校验结构()[0])\n"
            "状态.关闭()\n")
        进程表 = []
        for _ in range(4):
            进程 = subprocess.Popen(
                [sys.executable, "-S", "-c", 脚本, str(系统根), str(目录)],
                cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            进程表.append(进程)
        结果 = [进程.communicate(timeout=30) for 进程 in 进程表]
        for 进程, (输出, 错误) in zip(进程表, 结果):
            self.assertEqual(进程.returncode, 0, 错误[-300:])
            self.assertEqual(输出.strip(), "True", 输出)
        连接 = sqlite3.connect(str(目录 / "权威状态.db"))
        版本 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()[0]
        旧资源 = 连接.execute("SELECT 值 FROM 资源版本 WHERE 资源id='老资源'").fetchone()
        连接.close()
        self.assertEqual(版本, 状态结构版本)
        self.assertEqual(旧资源[0], '{"内容": "旧数据"}', "并发升级不丢数据")


if __name__ == "__main__":
    unittest.main()
