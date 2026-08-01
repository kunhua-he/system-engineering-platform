"""资源并发测试：十进程唯一提交 / 异资源并发 / 陈旧写者 / 强杀接管 / 快照重建。

覆盖任务信第九节第 3、4、5、6、7、10 项；调用生产实现（资源协调器+权威状态）。
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.资源协调 import 资源协调器
from 运行核心.权威状态 import 权威状态

跨进程脚本 = '''
import sys, json, time
from pathlib import Path
系统根 = sys.argv[1]
sys.path.insert(0, 系统根)
from 运行核心.资源协调 import 资源协调器
操作 = sys.argv[2]
存储目录 = Path(sys.argv[3])
资源id = sys.argv[4] if len(sys.argv) > 4 else "文档"
协调 = 资源协调器(存储目录, 项目id="并发测试", 所有者=操作)
if 操作 == "初始化":
    协调.初始化资源(资源id, {"内容": "基线"})
    print(json.dumps({"成功": True}))
elif 操作 == "提交":
    # 序号 "立即" = 单提交者直通；数字序号 = 栅栏同步
    序号 = sys.argv[5] if len(sys.argv) > 5 else "0"
    协调.初始化资源(资源id, {"内容": "基线"})
    事务id, 句柄id, 基础, _ = 协调.创建修改事务(资源id)
    协调.修改工作副本(事务id, {"内容": f"提交者:{操作}"})
    if 序号 != "立即":
        就绪文件 = Path(sys.argv[3]) / f"就绪_{序号}.json"
        就绪文件.write_text(json.dumps({"事务id": 事务id}), encoding="utf-8")
        栅栏文件 = Path(sys.argv[3]) / "栅栏.json"
        for _ in range(200):
            if 栅栏文件.is_file():
                break
            time.sleep(0.02)
    成功, 消息, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id=资源id, 所有者=操作)
    print(json.dumps({"成功": 成功, "消息": 消息, "新版本": 新版本}))
elif 操作 == "持锁暂停":
    # 强杀恢复场景：真实持锁并保持心跳过期（模拟死亡）
    协调.初始化资源(资源id, {"内容": "基线"})
    成功, _, 令牌 = 协调.状态.获取锁(
        资源id, 操作id="持锁者", 进程身份键=协调.状态.身份.身份键(),
        项目id="并发测试", 所有者=操作)
    print(json.dumps({"成功": 成功, "令牌": 令牌, "身份键": 协调.状态.身份.身份键()}), flush=True)
    time.sleep(3)  # 保持锁足够久（心跳不刷新 → 过期）
'''


def 跑子进程(操作: str, 存储目录: Path, 资源id: str = "文档", 额外: str = "") -> tuple[int, str]:
    命令 = [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), 操作, str(存储目录), 资源id]
    if 额外:
        命令.append(额外)
    进程 = subprocess.run(命令, capture_output=True, text=True, timeout=30, cwd=str(系统根))
    return 进程.returncode, (进程.stdout or 进程.stderr).strip()


class Test并发提交(unittest.TestCase):
    """十进程同资源唯一提交 / 不同资源并发全部成功。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="并发_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_十进程同资源提交只有一个成功(self):
        跑子进程("初始化", self.目录)
        进程表 = []
        for 序号 in range(10):
            进程 = subprocess.Popen(
                [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), "提交",
                 str(self.目录), "文档", str(序号)],
                cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            进程表.append(进程)
        截止 = time.monotonic() + 20
        while time.monotonic() < 截止:
            if len(list(self.目录.glob("就绪_*.json"))) >= 10:
                break
            time.sleep(0.02)
        (self.目录 / "栅栏.json").write_text("{}", encoding="utf-8")
        结果表 = []
        for 进程 in 进程表:
            输出, 错误 = 进程.communicate(timeout=30)
            if not 输出.strip():
                self.fail(f"子进程无输出: {错误[-300:]}")
            结果表.append(json.loads(输出.strip()))
        成功数 = sum(1 for 结果 in 结果表 if 结果["成功"])
        self.assertEqual(成功数, 1, [结果["消息"] for 结果 in 结果表])

    def test_不同资源并发提交全部成功(self):
        协调 = 资源协调器(self.目录, 项目id="并发测试")
        协调.初始化资源("资源甲", {"值": 0})
        协调.初始化资源("资源乙", {"值": 0})
        结果表: list[bool] = []
        锁 = threading.Lock()

        def 提交(资源id: str) -> None:
            事务id, 句柄id, _, _ = 协调.创建修改事务(资源id)
            协调.修改工作副本(事务id, {"值": 1})
            成功, _, _ = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id=资源id)
            with 锁:
                结果表.append(成功)

        线程甲 = threading.Thread(target=提交, args=("资源甲",))
        线程乙 = threading.Thread(target=提交, args=("资源乙",))
        线程甲.start(); 线程乙.start()
        线程甲.join(); 线程乙.join()
        self.assertEqual(sum(结果表), 2, "不同资源并发提交全部成功")

    def test_活跃进程锁不被误删(self):
        协调 = 资源协调器(self.目录, 项目id="活跃者")
        协调.初始化资源("文档", {"内容": "基线"})
        协调.状态.刷新心跳()
        成功, _, 令牌 = 协调.状态.获取锁(
            "文档", 操作id="活跃者", 进程身份键=协调.状态.身份.身份键())
        self.assertTrue(成功)
        清理列表 = 协调.清理死亡进程资源()
        锁信息 = 协调.状态.锁持有者("文档")
        self.assertEqual(锁信息.get("操作id"), "活跃者", "活跃进程锁不能被误删")
        协调.状态.释放锁("文档", 操作id="活跃者",
                        进程身份键=协调.状态.身份.身份键(), 令牌=令牌)


class Test陈旧写者与强杀(unittest.TestCase):
    """陈旧写者旧令牌被拒 / 强杀持锁进程后新进程接管。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="陈旧写者_"))
        self.协调 = 资源协调器(self.目录, 项目id="并发测试", 所有者="测试者")
        self.协调.初始化资源("计数器", {"值": 0})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_陈旧写者携带旧令牌恢复后被拒绝(self):
        状态 = self.协调.状态
        # 写者甲取得令牌1并暂停（模拟：锁被清理后乙接管）
        成功甲, _, 令牌1 = 状态.获取锁(
            "计数器", 事务id="甲事务", 进程身份键="进程甲",
            项目id="并发测试", 所有者="测试者")
        self.assertTrue(成功甲)
        self.assertEqual(令牌1, 1)
        状态.释放锁("计数器", 事务id="甲事务", 进程身份键="进程甲", 令牌=令牌1)
        # 写者乙取得令牌2
        成功乙, _, 令牌2 = 状态.获取锁(
            "计数器", 事务id="乙事务", 进程身份键="进程乙",
            项目id="并发测试", 所有者="测试者")
        self.assertTrue(成功乙)
        self.assertGreater(令牌2, 令牌1, "令牌2 必须大于令牌1")
        # 甲恢复并携带令牌1提交 → 最底层写入明确拒绝旧栅栏令牌
        甲成功, 甲消息 = 状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(令牌1),
            事务id="甲事务", 进程身份键="进程甲", 新值={"值": 1}, 新摘要="甲")
        self.assertFalse(甲成功, f"陈旧写者必须被拒: {甲消息}")
        # 拒绝原因：锁所有权不匹配（锁已被乙接管）或旧令牌，均为栅栏拒绝语义
        self.assertTrue(
            ("令牌" in 甲消息) or ("所有权" in 甲消息) or ("锁" in 甲消息),
            f"拒绝原因必须指向令牌/所有权: {甲消息}")
        # 乙携带令牌2正常提交
        乙成功, 乙消息 = 状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(令牌2),
            事务id="乙事务", 进程身份键="进程乙",
            项目id="并发测试", 所有者="测试者", 新值={"值": 2}, 新摘要="乙")
        self.assertTrue(乙成功, f"新写者必须成功: {乙消息}")
        资源 = 状态.读取资源("计数器")
        self.assertEqual(资源["值"], {"值": 2})

    def test_强杀持锁进程后清理并接管更大令牌(self):
        # 子进程真实持锁（Popen 非阻塞：子进程持锁期间即清理，不等待退出）
        进程 = subprocess.Popen(
            [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), "持锁暂停",
             str(self.目录), "计数器"],
            cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        持锁信息 = json.loads(进程.stdout.readline())
        self.assertTrue(持锁信息["成功"], f"子进程未完成获锁握手: {持锁信息}")
        进程.kill()  # 真实强杀：子进程已确认持锁后被杀
        进程.wait(timeout=5)
        self.assertTrue(持锁信息["成功"])
        # 清理死亡进程资源：操作系统已确认子进程不存在，立即精确回收
        清理列表 = self.协调.状态.清理死亡进程资源(
            项目id="并发测试", 所有者="持锁暂停", 心跳超时秒=1.0)
        self.assertTrue(any("锁" in 项 for 项 in 清理列表), f"必须清理正式锁: {清理列表}")
        锁信息 = self.协调.状态.锁持有者("计数器")
        self.assertEqual(锁信息, {}, "死亡进程正式锁必须被回收")
        # 新进程立即取得更大令牌并提交
        成功, _, 新令牌 = self.协调.状态.获取锁(
            "计数器", 事务id="新事务", 进程身份键=self.协调.状态.身份.身份键(),
            项目id="并发测试", 所有者="测试者")
        self.assertTrue(成功)
        self.assertGreater(新令牌, 持锁信息["令牌"], "新进程必须获得更大栅栏令牌")
        提交成功, 消息 = self.协调.状态.提交资源(
            资源id="计数器", 期望版本="0", 期望令牌=str(新令牌),
            事务id="新事务", 进程身份键=self.协调.状态.身份.身份键(),
            项目id="并发测试", 所有者="测试者", 新值={"值": 1}, 新摘要="新")
        self.assertTrue(提交成功, 消息)


class Test快照重建(unittest.TestCase):
    """权威状态提交后快照未发布（崩溃窗口）→ 重建快照。"""

    def test_提交后快照缺失可重建(self):
        目录 = Path(tempfile.mkdtemp(prefix="快照重建_"))
        协调 = 资源协调器(目录, 项目id="快照测试")
        协调.初始化资源("文档", {"内容": "v1"})
        # 提交新版本
        事务id, 句柄id, _, _ = 协调.创建修改事务("文档")
        协调.修改工作副本(事务id, {"内容": "v2"})
        成功, _, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id="文档")
        self.assertTrue(成功)
        快照 = 协调.快照目录 / f"文档@{新版本}"
        self.assertTrue(快照.is_dir(), "提交后快照应存在")
        # 模拟崩溃窗口：删除最新快照（权威状态已提交但快照未发布）
        import shutil
        shutil.rmtree(快照)
        self.assertFalse(快照.is_dir())
        # 崩溃恢复：根据权威状态重建缺失快照
        恢复列表 = 协调.恢复缺失快照()
        self.assertIn(f"文档@{新版本}", 恢复列表, "缺失快照必须重建")
        self.assertTrue(快照.is_dir(), "重建后快照存在")
        # 幂等：再次恢复不再重复
        self.assertEqual(协调.恢复缺失快照(), [])
        # 读取快照值一致
        self.assertEqual(协调.读取快照值("文档", 新版本)["内容"], "v2")
        shutil.rmtree(目录, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
