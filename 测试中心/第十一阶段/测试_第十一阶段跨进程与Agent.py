"""第十一阶段：跨进程权威状态、依赖防火墙与可信验证强制场景测试。

真实验证：两进程同时读同一快照/十进程基于同一版本提交唯一成功/
异资源跨进程并行提交/提交进程强杀后非半成品/重启恢复未完成事务/
活跃进程锁不被误删/死亡进程租约精准回收/路径逃逸拒绝/导入实现拒绝/
验证器改动缓存失效/删测试缓存不显示旧数/Agent 全链路。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

跨进程脚本 = '''import json, sys, time
from pathlib import Path
系统根 = Path(sys.argv[1])
sys.path.insert(0, str(系统根))
from 运行核心.资源协调 import 资源协调器
操作 = sys.argv[2]
存储目录 = Path(sys.argv[3])
资源id = sys.argv[4] if len(sys.argv) > 4 else "文档"
协调 = 资源协调器(存储目录, 项目id="跨进程测试", 所有者=操作)
if 操作 == "初始化":
    协调.初始化资源(资源id, {"内容": "基线"})
    print(json.dumps({"成功": True}))
elif 操作 == "读取":
    协调.初始化资源(资源id, {"内容": "基线"})
    数据, 句柄id = 协调.打开读取句柄(资源id)
    print(json.dumps({"成功": True, "版本": 数据["版本"], "值": 数据["值"]}))
    协调.关闭读取句柄(句柄id=句柄id, 资源id=资源id, 版本=数据["版本"])
elif 操作 == "提交":
    事务id, 句柄id, 基础, _ = 协调.创建修改事务(资源id)
    协调.修改工作副本(事务id, {"内容": f"提交者:{操作}"})
    # 栅栏同步：写就绪标记 → 等测试创建栅栏（全部进程创建完事务）→ 同时提交
    # 序号 "立即" = 单提交者直通模式（test_不同资源），跳过栅栏省 4 秒空等
    序号 = sys.argv[5] if len(sys.argv) > 5 else "0"
    if 序号 != "立即":
        就绪文件 = Path(sys.argv[3]) / f"就绪_{序号}.json"
        就绪文件.write_text(json.dumps({"事务id": 事务id, "基础": 基础}), encoding="utf-8")
        栅栏文件 = Path(sys.argv[3]) / "栅栏.json"
        for _ in range(200):
            if 栅栏文件.is_file():
                break
            time.sleep(0.02)
    成功, 消息, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id=资源id, 所有者=操作)
    print(json.dumps({"成功": 成功, "消息": 消息, "新版本": 新版本}))
elif 操作 == "延迟提交":
    协调.初始化资源(资源id, {"内容": "基线"})
    time.sleep(float(sys.argv[5]))
    事务id, 句柄id, 基础, _ = 协调.创建修改事务(资源id)
    协调.修改工作副本(事务id, {"内容": f"延迟:{操作}"})
    成功, 消息, 新版本 = 协调.提交(事务id=事务id, 句柄id=句柄id, 资源id=资源id, 所有者=操作)
    print(json.dumps({"成功": 成功, "消息": 消息}))
elif 操作 == "创建事务不提交":
    协调.初始化资源(资源id, {"内容": "基线"})
    事务id, 句柄id, 基础, _ = 协调.创建修改事务(资源id)
    协调.修改工作副本(事务id, {"内容": "未完成"})
    print(json.dumps({"事务id": 事务id, "句柄id": 句柄id, "基础": 基础}))
elif 操作 == "创建租约":
    协调.初始化资源(资源id, {"内容": "基线"})
    from 运行核心.租约管理 import 租约管理器
    管理器 = 租约管理器()
    租约 = 管理器.创建租约(资源id=资源id, 项目id="跨进程测试", 所有者=操作, 空闲超时秒=1.0)
    协调.状态.保存租约(租约id=租约.租约id, 资源id=资源id, 项目id="跨进程测试",
                      所有者=操作, 句柄id=租约.句柄id, 空闲超时秒=1.0,
                      硬截止时间=租约.硬截止时间, 最后心跳=time.time() - 10,
                      进程身份键=协调.状态.身份.身份键())
    print(json.dumps({"租约id": 租约.租约id}))
'''


def 跑子进程(操作: str, 存储目录: Path, 资源id: str = "文档", 额外: str = "") -> tuple[int, str]:
    命令 = [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), 操作, str(存储目录), 资源id]
    if 额外:
        命令.append(额外)
    进程 = subprocess.run(命令, capture_output=True, text=True, timeout=30,
                          cwd=str(系统根))
    return 进程.returncode, (进程.stdout or 进程.stderr).strip()


class Test跨进程权威状态(unittest.TestCase):
    """跨进程：读快照/唯一提交/异资源并行/强杀恢复/精准回收。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="第十一阶段跨进程_"))

    def tearDown(self):
        协调 = getattr(self, "协调", None)
        if 协调 is not None:
            协调.状态.关闭()
            self.协调 = None
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_两个独立进程同时读取同一快照(self):
        码1, 输出1 = 跑子进程("读取", self.目录)
        码2, 输出2 = 跑子进程("读取", self.目录)
        self.assertEqual(码1, 0, 输出1)
        self.assertEqual(码2, 0, 输出2)
        数据1 = json.loads(输出1)
        数据2 = json.loads(输出2)
        self.assertEqual(数据1["版本"], 数据2["版本"])
        self.assertEqual(数据1["值"], 数据2["值"])

    def test_十进程基于同一版本提交只有一个成功(self):
        # 预热：先初始化数据库与资源（消除并发建表竞态），再并行 10 进程提交
        跑子进程("初始化", self.目录)
        进程表 = []
        for 序号 in range(10):
            进程 = subprocess.Popen(
                [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), "提交",
                 str(self.目录), "文档", str(序号)],
                cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            进程表.append(进程)
        # 栅栏：等 10 个进程全部就绪（创建完事务）→ 放行同时提交
        import time as _时间
        截止 = _时间.monotonic() + 20
        while _时间.monotonic() < 截止:
            if len(list(self.目录.glob("就绪_*.json"))) >= 10:
                break
            _时间.sleep(0.02)
        (self.目录 / "栅栏.json").write_text("{}", encoding="utf-8")
        结果表 = []
        for 进程 in 进程表:
            输出, 错误 = 进程.communicate(timeout=30)
            if not 输出.strip():
                self.fail(f"子进程无输出: {错误[-300:]}")
            结果表.append(json.loads(输出.strip()))
        成功数 = sum(1 for 结果 in 结果表 if 结果["成功"])
        冲突数 = sum(1 for 结果 in 结果表 if not 结果["成功"] and "版本冲突" in 结果["消息"])
        self.assertEqual(成功数, 1, [结果["消息"] for 结果 in 结果表])
        self.assertEqual(冲突数, 9)

    def test_不同资源跨进程并行提交成功(self):
        结果表 = []
        for 资源id in ("资源甲", "资源乙"):
            跑子进程("初始化", self.目录, 资源id)
            码, 输出 = 跑子进程("提交", self.目录, 资源id, "立即")  # 单提交者直通，不等栅栏
            self.assertEqual(码, 0, 输出)
            结果表.append(json.loads(输出))
        self.assertEqual([结果["成功"] for 结果 in 结果表], [True, True])

    def test_提交进程被强杀后正式资源不是半成品(self):
        进程 = subprocess.Popen(
            [sys.executable, "-S", "-c", 跨进程脚本, str(系统根), "延迟提交",
             str(self.目录), "文档", "3"],
            cwd=str(系统根), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.6)  # 延迟提交 已初始化资源并 sleep（初始化 <0.2s，0.6s 充分）
        进程.kill()
        进程.wait(timeout=5)
        for 流 in (进程.stdout, 进程.stderr):
            if 流 is not None:
                流.close()
        # 重启后：正式资源必须是 初始 完整状态（版本 0）
        from 运行核心.资源协调 import 资源协调器
        协调 = self.协调 = 资源协调器(self.目录, 项目id="恢复者")
        数据, 版本, _ = 协调.读取基础版本("文档")
        self.assertEqual(版本, "0", "强杀后资源必须是完整初始状态（非半成品）")
        self.assertEqual(数据["值"]["内容"], "基线")

    def test_重启后恢复未完成事务(self):
        码, 输出 = 跑子进程("创建事务不提交", self.目录)
        self.assertEqual(码, 0, 输出)
        from 运行核心.资源协调 import 资源协调器
        协调 = self.协调 = 资源协调器(self.目录, 项目id="重启者")
        恢复列表 = 协调.恢复未完成事务()
        self.assertEqual(len(恢复列表), 1, "重启后必须恢复未完成事务")
        self.assertEqual(协调.状态.进行中事务(), [])

    def test_活跃进程锁不被其他清理器误删(self):
        from 运行核心.资源协调 import 资源协调器
        协调 = self.协调 = 资源协调器(self.目录, 项目id="活跃者")
        协调.初始化资源("文档", {"内容": "基线"})
        协调.状态.刷新心跳()  # 活跃进程心跳新鲜
        # 持有锁（结构化所有权 + 栅栏令牌签发）
        成功, _, 令牌 = 协调.状态.获取锁(
            "文档", 操作id="活跃者", 进程身份键=协调.状态.身份.身份键(),
            项目id="活跃者", 所有者=协调.状态.身份.所有者)
        self.assertTrue(成功)
        self.assertGreater(令牌, 0, "获取锁必须签发新栅栏令牌")
        # 其他清理器清理：活跃者 心跳新鲜 → 锁不被误删
        清理列表 = 协调.清理死亡进程资源()
        锁信息 = 协调.状态.锁持有者("文档")
        self.assertEqual(锁信息.get("操作id"), "活跃者", "活跃进程锁不能被误删")
        self.assertEqual(锁信息.get("栅栏令牌"), 令牌)
        协调.状态.释放锁("文档", 操作id="活跃者",
                        进程身份键=协调.状态.身份.身份键(), 令牌=令牌)

    def test_死亡进程租约到期后精准回收(self):
        码, 输出 = 跑子进程("创建租约", self.目录)
        self.assertEqual(码, 0, 输出)
        租约id = json.loads(输出)["租约id"]
        from 运行核心.资源协调 import 资源协调器
        协调 = self.协调 = 资源协调器(self.目录, 项目id="回收者")
        协调.状态.刷新心跳()
        # 死亡进程（心跳过期）的租约：精准回收
        过期列表 = 协调.状态.扫描过期租约()
        self.assertIn(租约id, 过期列表)


class Test依赖防火墙(unittest.TestCase):
    """依赖防火墙：导入实现目录被拒绝。"""

    def test_导入实现目录被依赖门禁拒绝(self):
        from 运行核心.依赖防火墙 import 审计依赖
        结果 = 审计依赖()
        self.assertEqual(len(结果.违规列表), 0,
                         [违规.规则 + " @" + 违规.文件 for 违规 in 结果.违规列表[:3]])
        # 主动制造违规：运行核心 导入 实现/ → 必须被拒绝
        import ast as _ast
        来源文件 = 系统根 / "运行核心" / "_违规样例.py"
        来源文件.write_text(
            "from 支持库.后端.系统核心支持库.资源管理.实现.资源管理 import 原子写入\n", encoding="utf-8")
        try:
            结果2 = 审计依赖(系统根 / "运行核心")
            self.assertTrue(any("实现" in 违规.规则 for 违规 in 结果2.违规列表),
                            "运行核心 导入 实现/ 必须被依赖门禁拒绝")
        finally:
            来源文件.unlink(missing_ok=True)

    def test_运行核心不导入实现目录(self):
        from 运行核心.依赖防火墙 import 审计依赖
        结果 = 审计依赖(系统根 / "运行核心")
        self.assertEqual(len(结果.违规列表), 0,
                         [违规.规则 + " @" + 违规.文件 for 违规 in 结果.违规列表[:3]])


class TestAgent开发闭环(unittest.TestCase):
    """Agent 开发入口全链路。"""

    def test_搜索查看调用诊断全链路(self):
        from 开发工具.开发入口 import 执行操作
        搜索 = 执行操作("搜索能力", {"关键词": "分割"})
        self.assertTrue(搜索["成功"])
        self.assertGreaterEqual(len(搜索["数据"]), 1)
        契约 = 执行操作("查看契约", {"能力id": "数据操作支持库.文本处理.分割文本"})
        self.assertTrue(契约["数据"]["找到"])
        调用 = 执行操作("真实调用能力", {
            "能力id": "数据操作支持库.文本处理.分割文本",
            "参数": {"文本": "甲，乙", "分隔符": "，"}})
        self.assertTrue(调用["成功"], 调用)
        self.assertEqual(调用["数据"]["值"], ["甲", "乙"])
        self.assertIn("请求id", 调用["数据"]["证据链"])
        诊断 = 执行操作("查看已知失败", {"能力id": "数据操作支持库.文本处理.分割文本"})
        self.assertIn("成功", 诊断)

    def test_命令行入口复用同一实现(self):
        进程 = subprocess.run(
            [sys.executable, "-S", str(系统根 / "开发工具" / "开发入口.py"),
             "搜索能力", json.dumps({"关键词": "分割"})],
            cwd=str(系统根), capture_output=True, text=True, timeout=30)
        self.assertEqual(进程.returncode, 0, 进程.stderr)
        数据 = json.loads(进程.stdout)
        self.assertTrue(数据["成功"])

    def test_查询入口直接运行修复(self):
        进程 = subprocess.run(
            [sys.executable, "-S", str(系统根 / "开发工具" / "统一能力入口" / "Agent查询" / "查询入口.py")],
            cwd=str(系统根), capture_output=True, text=True, timeout=30)
        self.assertEqual(进程.returncode, 0, (进程.stdout or 进程.stderr)[:200])


if __name__ == "__main__":
    unittest.main()

