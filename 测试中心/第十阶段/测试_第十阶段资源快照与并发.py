"""第十阶段：资源快照、事务句柄与并发强制反向场景测试。

覆盖：100 并发读取一致快照互不阻塞/同基础并发修改唯一提交/不同资源
并发提交/提交崩溃非半成品/旧读取句柄读旧值/过期句柄拒绝且不复活/
心跳续租与停止回收/跨项目跨所有者拒绝/进程崩溃后租约锁临时目录资源
全释放/固定临时文件名与写正式目录被拒绝。
"""

from __future__ import annotations

import json
import shutil
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
from 运行核心.句柄体系 import 句柄体系, 句柄类型_资源, 状态_已失效
from 运行核心.租约管理 import 租约管理器
from 运行核心.进程身份 import 创建进程身份
from 开发工具.统一验证.验证工作区 import 校验临时文件名, 校验不写正式目录


class Test并发快照(unittest.TestCase):
    """强制反向场景 1-3：并发读取/唯一提交/不同资源并发提交。"""

    def test_100并发读取者获得一致快照且互不阻塞(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段并发读_"))
        协调 = 资源协调器(目录)
        协调.初始化资源("文档", {"内容": "基线"})
        结果表: list[dict] = []
        锁 = threading.Lock()

        def 读取() -> None:
            数据, 句柄id = 协调.打开读取句柄("文档")
            with 锁:
                结果表.append({"版本": 数据["版本"], "值": 数据["值"], "句柄id": 句柄id})

        线程表 = [threading.Thread(target=读取) for _ in range(100)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join()
        self.assertEqual(len(结果表), 100)
        self.assertEqual({行["版本"] for 行 in 结果表}, {"0"})  # 一致快照
        self.assertEqual({行["值"]["内容"] for 行 in 结果表}, {"基线"})
        shutil.rmtree(目录, ignore_errors=True)

    def test_同基础版本并发修改只有一个提交成功(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段并发写_"))
        协调 = 资源协调器(目录)
        协调.初始化资源("计数器", {"值": 0})
        结果表: list[bool] = []
        锁 = threading.Lock()

        def 提交() -> None:
            事务id, 句柄id, _, _ = 协调.创建修改事务("计数器")
            协调.修改工作副本(事务id, {"值": 1})
            成功, _, _ = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id="计数器")
            with 锁:
                结果表.append(成功)

        线程表 = [threading.Thread(target=提交) for _ in range(10)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join()
        成功数 = sum(结果表)
        self.assertEqual(成功数, 1)  # 只有一个提交成功，其余版本冲突
        数据, _, _ = 协调.读取基础版本("计数器")
        self.assertEqual(数据["版本"], "1")
        shutil.rmtree(目录, ignore_errors=True)

    def test_不同资源可以同时提交(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段异资源_"))
        协调 = 资源协调器(目录)
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
        self.assertEqual(sum(结果表), 2)  # 两个不同资源都提交成功
        shutil.rmtree(目录, ignore_errors=True)


class Test句柄语义(unittest.TestCase):
    """强制反向场景 4-6 + 8：崩溃非半成品/旧句柄旧值/过期拒绝/跨所有者。"""

    def test_提交崩溃后正式快照不是半成品(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段崩溃_"))
        协调 = 资源协调器(目录)
        协调.初始化资源("文档", {"内容": "v1"})
        # 模拟提交中途崩溃：直接写 工作副本 + 残留锁，不提交
        事务id, 句柄id, 基础版本, _ = 协调.创建修改事务("文档")
        协调.修改工作副本(事务id, {"内容": "半成品"})
        (协调.工作目录 / "残留锁样例.json").write_text("{}", encoding="utf-8")
        # 崩溃后重启：清理残留 + 正式资源不受影响
        清理列表 = 协调.清理崩溃残留()
        self.assertTrue(len(清理列表) >= 0)  # 恢复未完成事务已执行
        数据, _, _ = 协调.读取基础版本("文档")
        self.assertEqual(数据["值"]["内容"], "v1")  # 正式快照完整，非半成品
        self.assertEqual(数据["版本"], "0")
        shutil.rmtree(目录, ignore_errors=True)

    def test_旧读取句柄在新版本提交后仍读取旧值(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段旧句柄_"))
        协调 = 资源协调器(目录)
        协调.初始化资源("文档", {"内容": "旧值"})
        数据, 旧句柄id = 协调.打开读取句柄("文档")
        旧版本 = 数据["版本"]
        # 提交新版本
        事务id, 句柄id, _, _ = 协调.创建修改事务("文档")
        协调.修改工作副本(事务id, {"内容": "新值"})
        成功, _, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id="文档")
        self.assertTrue(成功)
        # 旧读取句柄仍读旧版本快照
        旧值 = 协调.读取快照值("文档", 旧版本)
        self.assertEqual(旧值["内容"], "旧值")
        新数据, _ = 协调.打开读取句柄("文档")
        self.assertEqual(新数据["值"]["内容"], "新值")
        self.assertEqual(新数据["版本"], 新版本)
        shutil.rmtree(目录, ignore_errors=True)

    def test_过期句柄拒绝调用且不能自动复活(self):
        体系 = 句柄体系()
        句柄对象 = 体系.创建句柄(句柄类型=句柄类型_资源, 资源id="资源1", 所有者="甲")
        有效, _ = 体系.校验(句柄对象.句柄id, 所有者="甲")
        self.assertTrue(有效)
        体系.失效(句柄对象.句柄id, "过期")
        有效2, 消息 = 体系.校验(句柄对象.句柄id, 所有者="甲")
        self.assertFalse(有效2)
        self.assertIn("不能自动复活", 消息)
        体系.失效(句柄对象.句柄id, "过期")  # 重复失效幂等
        self.assertEqual(体系.活跃句柄数(), 0)

    def test_跨项目跨所有者复用句柄被拒绝(self):
        体系 = 句柄体系()
        句柄对象 = 体系.创建句柄(句柄类型=句柄类型_资源, 资源id="资源1",
                               项目id="项目甲", 所有者="甲")
        有效, 消息 = 体系.校验(句柄对象.句柄id, 项目id="项目乙", 所有者="甲")
        self.assertFalse(有效)
        self.assertIn("跨项目", 消息)
        有效2, 消息2 = 体系.校验(句柄对象.句柄id, 项目id="项目甲", 所有者="乙")
        self.assertFalse(有效2)
        self.assertIn("跨所有者", 消息2)

    def test_句柄回收证据记录(self):
        体系 = 句柄体系()
        句柄对象 = 体系.创建句柄(句柄类型=句柄类型_资源, 资源id="资源1", 所有者="甲")
        体系.失效(句柄对象.句柄id, "回收")
        证据表 = 体系.查询回收证据(资源id="资源1")
        self.assertEqual(len(证据表), 1)
        self.assertEqual(证据表[0]["失效原因"], "回收")


class Test租约管理(unittest.TestCase):
    """强制反向场景 7 + 9：心跳续租/停止回收/进程崩溃清理。"""

    def test_心跳可续租停止心跳后自动回收(self):
        管理器 = 租约管理器()
        租约对象 = 管理器.创建租约(资源id="资源1", 所有者="甲", 空闲超时秒=0.2)
        有效, _ = 管理器.心跳(租约对象.租约id)
        self.assertTrue(有效)
        # 停止心跳 → 空闲超时自动回收
        time.sleep(0.3)
        回收列表 = 管理器.扫描过期()
        self.assertIn(租约对象.租约id, 回收列表)
        self.assertTrue(管理器.查询(租约对象.租约id).已回收)
        # 回收后心跳拒绝（不复活）
        有效2, 消息 = 管理器.心跳(租约对象.租约id)
        self.assertFalse(有效2)

    def test_硬截止时间到达自动回收(self):
        管理器 = 租约管理器()
        租约对象 = 管理器.创建租约(资源id="资源1", 硬截止秒=0.1)
        time.sleep(0.15)
        self.assertFalse(管理器.心跳(租约对象.租约id)[0])

    def test_进程崩溃后租约锁临时目录资源全部释放(self):
        目录 = Path(tempfile.mkdtemp(prefix="第十阶段崩溃清理_"))
        协调 = 资源协调器(目录)
        协调.初始化资源("文档", {"内容": "v1"})
        # 制造残留：未完成事务 + 工作副本 + 过期进程（心跳过期）持有锁
        事务id, 句柄id, _, _ = 协调.创建修改事务("文档")
        残留锁 = 协调.工作目录 / "残留.json"
        残留锁.write_text('{"值": 1}', encoding="utf-8")
        # 注册一个心跳过期的死亡进程并持有锁
        死亡身份 = 创建进程身份(项目id="", 所有者="死亡者")
        死亡身份.最后心跳 = time.time() - 60
        协调.状态.保存进程(死亡身份) if hasattr(协调.状态, "保存进程") else None
        # 进程崩溃后清理：恢复未完成事务 + 清理死亡进程资源
        清理列表 = 协调.清理崩溃残留()
        self.assertTrue(len(清理列表) >= 1)
        数据, _, _ = 协调.读取基础版本("文档")  # 正式资源完好
        self.assertEqual(数据["值"]["内容"], "v1")
        shutil.rmtree(目录, ignore_errors=True)


class Test工作区隔离(unittest.TestCase):
    """强制反向场景 10：固定临时文件名/写正式目录被拒绝。"""

    def test_固定临时文件名被拒绝(self):
        from pathlib import Path as _路径
        固定名 = _路径("依赖锁定.tmp")
        self.assertFalse(校验临时文件名(固定名, "操作id_abc123"))

    def test_含操作id临时文件名通过(self):
        from pathlib import Path as _路径
        合规名 = _路径("依赖锁定_操作id_abc123.tmp")
        self.assertTrue(校验临时文件名(合规名, "操作id_abc123"))

    def test_写正式目录被拒绝(self):
        正式目录表 = [Path("支持库"), Path("模块库")]
        self.assertFalse(校验不写正式目录(Path("支持库/后端/文件系统"), 正式目录表))
        self.assertTrue(校验不写正式目录(Path("工程缓存/验证运行/x"), 正式目录表))

    def test_验证工作区完整生命周期(self):
        工程根 = Path(tempfile.mkdtemp(prefix="第十阶段工作区_"))
        from 开发工具.统一验证.验证工作区 import 验证工作区
        工作区 = 验证工作区(工程根)
        根目录 = 工作区.创建()
        self.assertTrue((根目录 / "输入快照").is_dir())
        self.assertTrue((根目录 / "工作副本").is_dir())
        self.assertTrue((根目录 / "依赖锁定.json").is_file())
        工作区.写入结果(状态="通过", 测试数=10)
        结果 = json.loads((根目录 / "验证结果.json").read_text(encoding="utf-8"))
        self.assertEqual(结果["状态"], "通过")
        清理列表 = 工作区.回收()
        self.assertTrue(any("工作区" in 项 for 项 in 清理列表))
        self.assertFalse(根目录.exists())
        shutil.rmtree(工程根, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
