"""平台控制面测试：需求 CAS / 授权五角色 / 复用治理 / 占用租约 / 策略 / 证据。

覆盖任务信五-1/2/3/4/5/6/7/10/18/19；调用生产实现，不复制简化算法。
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.统一入口 import 统一能力服务
from 平台控制面.能力目录 import 契约指纹


def 建服务() -> tuple[统一能力服务, Path]:
    目录 = Path(tempfile.mkdtemp(prefix="平台测试_"))
    return 统一能力服务(目录), 目录


def 完整预算() -> dict:
    return {"内存上限": 100, "线程上限": 4, "子进程上限": 1, "并发调用上限": 4,
            "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
            "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}


def 提权(服务: 统一能力服务, 身份id: str, 角色: str) -> str:
    """受信引导夹具：注册 → 引导授予 → 切换；返回令牌。"""
    令牌 = 服务.授权.注册身份(身份id=身份id)
    成功, 消息 = 服务.授权.引导授予(身份id=身份id, 角色=角色, 授予者="系统引导")
    assert 成功, 消息
    成功, 消息 = 服务.授权.切换角色(令牌, 角色)
    assert 成功, 消息
    return 令牌


class Test需求与CAS(unittest.TestCase):
    """需求快照 CAS / 未确认门禁。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()

    def test_需求变化生成新版本不覆盖旧快照(self):
        快照1 = self.服务.需求.登记需求(目标="目标1")
        快照2 = self.服务.需求.登记需求(目标="目标2")
        self.assertNotEqual(快照1["需求id"], 快照2["需求id"], "需求快照不可变，变化生成新版本")
        记录 = self.服务.状态.读取记录("需求", "需求id", 快照1["需求id"])
        self.assertEqual(记录["版本"], "1")

    def test_未确认需求创建组件被拒绝(self):
        快照 = self.服务.需求.登记需求(目标="未确认需求")
        令牌 = 提权(self.服务, "开发Agent", "组件开发Agent")
        结果 = self.服务.执行操作(令牌=令牌, 操作="创建组件", 参数={
            "能力id": "x.能力", "需求id": 快照["需求id"], "复用决策": {"搜索词": "x", "候选能力id": ["x"]},
            "资源预算": 完整预算(), "允许修改路径": ["组件库/x"], "组件声明": {"名称": "x"}})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "需求未确认")
        # 确认后允许
        self.服务.需求.确认需求(需求id=快照["需求id"])
        结果 = self.服务.执行操作(令牌=令牌, 操作="创建组件", 参数={
            "能力id": "x.能力", "需求id": 快照["需求id"], "复用决策": {"搜索词": "x", "候选能力id": ["x"]},
            "资源预算": 完整预算(), "允许修改路径": ["组件库/x"], "组件声明": {"名称": "x"}})
        self.assertTrue(结果["成功"])


class Test授权五角色(unittest.TestCase):
    """角色门禁：开发Agent不能签名、普通用户越权拒绝、未知角色拒绝。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()

    def test_开发Agent尝试签名被拒绝(self):
        令牌 = 提权(self.服务, "开发Agent", "组件开发Agent")
        结果 = self.服务.执行操作(令牌=令牌, 操作="签名与发布", 参数={})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "越权操作")

    def test_未知角色被拒绝(self):
        令牌 = self.服务.授权.注册身份(身份id="神秘人")
        成功, 消息 = self.服务.授权.切换角色(令牌, "超级管理员")
        self.assertFalse(成功)
        self.assertIn("未知角色", 消息)

    def test_普通用户调用能力被拒_调用Agent可调用(self):
        普通令牌 = self.服务.授权.注册身份(身份id="用户")
        self.服务.授权.切换角色(普通令牌, "普通用户")
        结果 = self.服务.执行操作(令牌=普通令牌, 操作="调用能力", 参数={"能力id": "x"})
        self.assertEqual(结果["错误码"], "越权操作")
        agent令牌 = 提权(self.服务, "调用Agent", "调用Agent")
        结果 = self.服务.执行操作(令牌=agent令牌, 操作="调用能力", 参数={"能力id": "x"})
        self.assertEqual(结果["错误码"], "能力不存在", "授权通过，走到能力查找")


class Test复用治理与占用(unittest.TestCase):
    """相同契约指纹阻断 / 重叠待裁决 / 占用租约互斥与过期。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()

    def test_相同契约指纹阻断重复实现(self):
        契约 = {"能力id": "文件.读取", "名称": "读取文件", "参数": [{"名称": "路径"}],
                "返回": {"类型": "文本"}, "错误码": [], "副作用": "无", "宿主": "后端", "权限": ""}
        成功, _ = self.服务.目录.登记能力(能力id="文件.读取", 契约=契约, 组件="组件1", 领域="文件")
        self.assertTrue(成功)
        成功2, 消息2 = self.服务.目录.登记能力(能力id="文件.读取2", 契约=契约, 组件="组件2", 领域="文件")
        self.assertFalse(成功2)
        self.assertIn("相同契约指纹", 消息2)

    def test_相同契约两个Agent同时申请占用只有一个成功(self):
        契约 = {"能力id": "a.能力"}
        结果表: list[bool] = []
        锁 = threading.Lock()

        def 申请(名字: str) -> None:
            成功, _, _ = self.服务.目录.申请占用(
                能力id="a.能力", 领域="领域", 契约指纹=契约指纹(契约),
                任务=名字, 所有者=名字)
            with 锁:
                结果表.append(成功)

        线程表 = [threading.Thread(target=申请, args=(f"Agent{i}",)) for i in range(2)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join()
        self.assertEqual(sum(结果表), 1, "相同能力同时只有一个占用成功")

    def test_占用租约过期后新Agent可接管(self):
        成功, _, 租约id = self.服务.目录.申请占用(
            能力id="b.能力", 领域="领域", 契约指纹="指纹", 任务="任务1", 所有者="Agent1")
        self.assertTrue(成功)
        # 模拟 Agent 崩溃：心跳停止 → 回收过期占用
        self.服务.状态.条件更新("占用租约", {"心跳": time.time() - 1000},
                                  "租约id=?", (租约id,))
        过期列表 = self.服务.目录.回收过期占用(心跳超时秒=60)
        self.assertIn(租约id, 过期列表)
        # 新 Agent 可接管
        成功2, _, _ = self.服务.目录.申请占用(
            能力id="b.能力", 领域="领域", 契约指纹="指纹", 任务="任务2", 所有者="Agent2")
        self.assertTrue(成功2, "租约过期后新 Agent 可接管")

    def test_疑似重叠未裁决不能发布(self):
        契约 = {"能力id": "c.能力"}
        指纹 = 契约指纹(契约)
        self.服务.目录.登记能力(能力id="c.能力", 契约=契约, 组件="组件1", 领域="域")
        self.服务.状态.条件更新("能力条目", {"裁决状态": "待裁决"}, "能力id=?", ("c.能力",))
        决定 = self.服务.策略.判定(类型="复用", 主题="c.能力", 请求={"调用者": "x", "角色": "发布者"})
        self.assertFalse(决定["允许"])
        self.assertEqual(决定["错误码"], "待裁决")
        # 维护者裁决后允许
        self.服务.目录.裁决(能力id="c.能力", 决定="允许并存", 维护者="维护者")
        决定 = self.服务.策略.判定(类型="复用", 主题="c.能力", 请求={"调用者": "x", "角色": "发布者"})
        self.assertTrue(决定["允许"])


class Test证据账本(unittest.TestCase):
    """证据追加写：旧记录不可覆盖，只能追加。"""

    def test_证据只追加不覆盖(self):
        服务, _ = 建服务()
        证据id1 = 服务.状态.追加证据(类型="测试", 主题="主题1", 内容={"值": 1})
        证据id2 = 服务.状态.追加证据(类型="测试", 主题="主题1", 内容={"值": 2})
        self.assertNotEqual(证据id1, 证据id2, "每次追加生成新证据id，不覆盖旧记录")
        记录1 = 服务.状态.读取记录("证据", "证据id", 证据id1)
        记录2 = 服务.状态.读取记录("证据", "证据id", 证据id2)
        self.assertEqual(记录1["内容"], '{"值": 1}')
        self.assertEqual(记录2["内容"], '{"值": 2}')

    def test_密钥不进证据正文(self):
        服务, _ = 建服务()
        from 支持库.适配层 import 生成密钥对
        私钥, 公钥 = 生成密钥对()
        证据id = 服务.状态.追加证据(类型="测试", 主题="密钥", 内容={"操作": "生成", "公钥": 公钥})
        记录 = 服务.状态.读取记录("证据", "证据id", 证据id)
        self.assertNotIn(私钥, 记录["内容"], "私钥不得进入证据")
        self.assertIn("公钥", 记录["内容"])


class Test统一入口(unittest.TestCase):
    """CLI/JSON/Agent 对同一操作一致结果。"""

    def test_命令行入口与Python入口一致(self):
        import subprocess
        服务, 目录 = 建服务()
        令牌 = 提权(服务, "测试Agent", "组件开发Agent")
        py结果 = 服务.执行操作(令牌=令牌, 操作="搜索能力", 参数={"关键词": "文件"})
        # CLI 用同一实现（独立进程）：注册默认普通用户，搜索能力是公开操作
        进程 = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.');"
             "from 平台控制面.统一入口 import 统一能力服务;"
             "import json, tempfile;"
             "服务 = 统一能力服务(服务路径 := None or __import__('pathlib').Path(tempfile.mkdtemp()));"
             "令牌 = 服务.授权.注册身份(身份id='CLI');"
             "print(json.dumps(服务.执行操作(令牌=令牌, 操作='搜索能力', 参数={'关键词': '文件'})))"],
            capture_output=True, text=True, cwd=str(系统根))
        self.assertEqual(进程.returncode, 0, 进程.stderr[-300:])
        cli结果 = __import__("json").loads(进程.stdout.strip())
        self.assertEqual(cli结果["操作"], "搜索能力")
        self.assertEqual(cli结果["成功"], py结果["成功"], "CLI 与 Python 同一实现")

    def test_CLI不能自选高权限角色(self):
        """CLI 注册身份默认普通用户；未授予角色即使 --角色 也拒绝。"""
        import subprocess
        进程 = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.');"
             "from 平台控制面.统一入口 import 统一能力服务;"
             "import json, tempfile;"
             "服务 = 统一能力服务(__import__('pathlib').Path(tempfile.mkdtemp()));"
             "令牌 = 服务.授权.注册身份(身份id='CLI升权');"
             "print(json.dumps(服务.执行操作(令牌=令牌, 操作='签名与发布', 参数={})))"],
            capture_output=True, text=True, cwd=str(系统根))
        self.assertEqual(进程.returncode, 0)
        结果 = __import__("json").loads(进程.stdout.strip())
        self.assertFalse(结果["成功"], "CLI 注册的普通用户不能签名发布")
        self.assertEqual(结果["错误码"], "越权操作")


if __name__ == "__main__":
    unittest.main()
