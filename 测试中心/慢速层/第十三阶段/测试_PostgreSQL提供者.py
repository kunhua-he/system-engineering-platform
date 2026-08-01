"""第十三阶段：PostgreSQL 提供者真实行为测试。

场景一/二（默认路径，本机无 PG_DSN / 无服务）：必须明确返回宿主不可用
（错误码 HOST_UNAVAILABLE），禁止伪造成功；驱动检测必须如实上报。
场景三/四：自动创建一次性隔离容器，真实验证连接/查询/查询超时/关闭释放/
断开重连/事务回滚；验证结束销毁容器，不读取任何业务数据库连接。
"""
import atexit
import importlib
import os
import shutil
import subprocess
import sys
import time
import unittest
import unittest.mock
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.提供者.PostgreSQL提供者 import (PostgreSQL提供者, _探测驱动,
                                      错误码_宿主不可用, 错误码_超时)

测试镜像 = "postgres:16-alpine"
测试库名 = "system_library_test"
测试密码 = "test-password"


class PostgreSQL隔离实例:
    """为真实连接场景创建一次性 PostgreSQL 容器，不接触任何业务库。"""

    def __init__(self):
        self.容器名 = f"system-library-postgresql-test-{uuid.uuid4().hex[:12]}"
        self.连接串 = ""
        self.已启动 = False

    def _运行(self, 参数: list[str], 超时秒: float = 20.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *参数], capture_output=True, text=True, timeout=超时秒,
        )

    def 启动(self) -> str:
        if not shutil.which("docker"):
            raise RuntimeError("真实 PostgreSQL 门禁失败：未安装 docker，无法创建隔离实例")
        镜像结果 = self._运行(["image", "inspect", 测试镜像])
        if 镜像结果.returncode != 0:
            raise RuntimeError(f"真实 PostgreSQL 门禁失败：本机缺少测试镜像 {测试镜像}")
        启动结果 = self._运行([
            "run", "-d", "--rm", "--name", self.容器名,
            "--label", "system-library-test=postgresql",
            "-e", f"POSTGRES_PASSWORD={测试密码}",
            "-e", f"POSTGRES_DB={测试库名}",
            "-p", "127.0.0.1::5432", 测试镜像,
        ], 超时秒=30.0)
        if 启动结果.returncode != 0:
            raise RuntimeError(f"创建 PostgreSQL 隔离实例失败：{启动结果.stderr.strip()}")
        self.已启动 = True
        atexit.register(self.停止)
        端口结果 = self._运行(["port", self.容器名, "5432/tcp"])
        if 端口结果.returncode != 0 or ":" not in 端口结果.stdout:
            self.停止()
            raise RuntimeError(f"读取 PostgreSQL 隔离端口失败：{端口结果.stderr.strip()}")
        端口 = 端口结果.stdout.strip().rsplit(":", 1)[-1]
        self.连接串 = f"postgresql://postgres:{测试密码}@127.0.0.1:{端口}/{测试库名}"
        截止时间 = time.monotonic() + 20.0
        while time.monotonic() < 截止时间:
            就绪结果 = self._运行([
                "exec", self.容器名, "pg_isready", "-U", "postgres", "-d", 测试库名,
            ], 超时秒=3.0)
            if 就绪结果.returncode == 0:
                return self.连接串
            time.sleep(0.2)
        日志结果 = self._运行(["logs", "--tail", "30", self.容器名])
        self.停止()
        raise RuntimeError(f"PostgreSQL 隔离实例未在时限内就绪：{日志结果.stdout[-1000:]}")

    def 停止(self) -> None:
        if not self.已启动:
            return
        self.已启动 = False
        try:
            self._运行(["rm", "-f", self.容器名], 超时秒=10.0)
        except (OSError, subprocess.SubprocessError):
            pass


class Test宿主不可用检测(unittest.TestCase):
    """场景一/二：默认路径必须明确宿主不可用，禁止伪造成功。"""

    def test_无连接串时明确返回宿主不可用(self):
        with unittest.mock.patch.dict(os.environ, {"PG_DSN": ""}):
            提供者 = PostgreSQL提供者(连接串=None)  # 走环境变量默认路径
            结果 = 提供者.检测()
        self.assertFalse(结果.成功, "宿主不可用时禁止伪造成功")
        self.assertEqual(结果.错误码, 错误码_宿主不可用)
        self.assertIn("宿主不可用", 结果.错误说明)
        self.assertIn("驱动表", 结果.详情)

    def test_无驱动时明确返回宿主不可用(self):
        with unittest.mock.patch("平台控制面.提供者.PostgreSQL提供者._探测驱动",
                                 return_value={"psycopg2": False, "psycopg": False,
                                               "pg8000": False, "psql命令行": False}):
            提供者 = PostgreSQL提供者(连接串="host=127.0.0.1")
            结果 = 提供者.检测()
        self.assertFalse(结果.成功, "无驱动时禁止伪造成功")
        self.assertEqual(结果.错误码, 错误码_宿主不可用)

    def test_驱动检测与实际情况一致(self):
        驱动表 = _探测驱动()
        for 模块名 in ("psycopg2", "psycopg", "pg8000"):
            try:
                importlib.import_module(模块名)
                实际 = True
            except Exception:
                实际 = False
            self.assertEqual(驱动表.get(模块名), 实际, f"{模块名} 检测必须与实际导入一致")
        self.assertIn("psql命令行", 驱动表)

    def test_连接目标不可达时返回宿主不可用(self):
        提供者 = PostgreSQL提供者(连接串="host=127.0.0.1 port=1 dbname=不存在 user=不存在",
                                连接超时秒=1.0)
        结果 = 提供者.检测()
        self.assertFalse(结果.成功, "连接失败不得伪造成功")
        self.assertEqual(结果.错误码, 错误码_宿主不可用)
        self.assertIn("真实连接失败", 结果.错误说明)


class Test真实连接与事务(unittest.TestCase):
    """场景三/四：真实连接/查询/查询超时/关闭释放/断开重连/事务回滚。"""

    @classmethod
    def setUpClass(cls):
        cls.隔离实例 = PostgreSQL隔离实例()
        cls.连接串 = cls.隔离实例.启动()

    @classmethod
    def tearDownClass(cls):
        cls.隔离实例.停止()

    def setUp(self):
        self.提供者 = PostgreSQL提供者(连接串=self.连接串, 连接超时秒=5.0, 查询超时秒=3.0)
        结果 = self.提供者.打开连接()
        self.assertTrue(结果.成功, f"PostgreSQL 隔离实例连接失败：{结果.错误说明}")

    def tearDown(self):
        self.提供者.关闭()

    def test_真实连接查询超时关闭释放(self):
        结果 = self.提供者.查询("SELECT 1")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值[0][0], 1, "真实查询必须返回真实值")
        超时 = self.提供者.查询("SELECT pg_sleep(10)")
        self.assertFalse(超时.成功)
        self.assertEqual(超时.错误码, 错误码_超时, f"查询超时必须真实生效：{超时.错误说明}")
        self.assertTrue(self.提供者.关闭().成功)
        self.assertEqual(self.提供者.查询("SELECT 1").错误码, 错误码_宿主不可用,
                         "关闭释放后查询必须明确宿主不可用")
        self.assertEqual(self.提供者.执行("SELECT 1").错误码, 错误码_宿主不可用)
        self.assertTrue(self.提供者.关闭().成功, "重复关闭必须幂等")

    def test_断开重连成功(self):
        self.assertEqual(self.提供者.查询("SELECT 1").值[0][0], 1)
        self.assertTrue(self.提供者.关闭().成功)
        self.assertEqual(self.提供者.查询("SELECT 1").错误码, 错误码_宿主不可用)
        重连 = self.提供者.重连()
        self.assertTrue(重连.成功, f"断开重连失败：{重连.错误说明}")
        self.assertEqual(self.提供者.查询("SELECT 1").值[0][0], 1, "重连后必须可真实查询")

    def test_事务回滚数据不落库(self):
        表名 = f"回滚验证_{int(time.time() * 1000)}"
        建表 = self.提供者.执行(f"CREATE TABLE {表名}(编号 integer)")
        self.assertTrue(建表.成功, f"建表失败：{建表.错误说明}")
        self.assertTrue(self.提供者.提交().成功, "建表提交失败")
        try:
            插入 = self.提供者.执行(f"INSERT INTO {表名} VALUES (42)")
            self.assertTrue(插入.成功, f"插入失败：{插入.错误说明}")
            事务内 = self.提供者.查询(f"SELECT COUNT(*) FROM {表名}")
            self.assertTrue(事务内.成功)
            self.assertEqual(事务内.值[0][0], 1, "未提交前同事务应可见插入数据")
            self.assertTrue(self.提供者.回滚().成功, "回滚失败")
            回滚后 = self.提供者.查询(f"SELECT COUNT(*) FROM {表名}")
            self.assertTrue(回滚后.成功, f"回滚后查询失败：{回滚后.错误说明}")
            self.assertEqual(回滚后.值[0][0], 0, "回滚后插入数据不得落库")
        finally:
            self.提供者.回滚()  # 清理可能中止的事务
            self.提供者.执行(f"DROP TABLE IF EXISTS {表名}")
            self.提供者.提交()


if __name__ == "__main__":
    unittest.main(verbosity=2)
