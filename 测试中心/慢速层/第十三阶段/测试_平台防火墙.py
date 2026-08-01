"""第十三阶段：平台控制面专属依赖防火墙测试（4 个真实绕过场景）。

场景 1：动态导入 __import__ 在平台控制面内被审计发现（写临时含 __import__ 的
        py 文件 → 审计必须报违规；真实 平台控制面/ 目录零动态导入违规）。
场景 2：统一入口代码不深入实现目录（AST 检查真实 统一入口.py 无违规；构造
        跨包导入 实现/ 的绕过文件与路径字符串引用 → 必须被拒）。
场景 3：提供者直连外部服务绕过注册表（构造未登记提供者文件直连 urlopen →
        审计标记；声明登记的提供者文件直连不标记；真实目录零违规）。
场景 4：依赖未声明时发布策略拒绝（真实 平台状态+能力目录+策略中心 →
        DEPENDENCY_MISSING；策略中心对"声明但未登记"同码拒绝）。
"""
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.能力目录 import 能力目录
from 平台控制面.策略中心 import 策略中心
from 平台控制面.提供者.防火墙审计 import 审计平台控制面, 审计文件, 发布依赖判定
from 运行核心.依赖防火墙 import 审计结果转清单


def 写文件(目录: Path, 文件名: str, 内容: str) -> Path:
    文件 = 目录 / 文件名
    文件.write_text(内容, encoding="utf-8")
    return 文件


class Test平台防火墙(unittest.TestCase):
    """4 个真实绕过场景全被拒绝 + 真实目录零冲突。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="平台防火墙测试_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    # ---- 场景 1：动态导入 __import__ 被审计发现 ----
    def test_动态导入被审计发现(self):
        写文件(self.临时目录, "偷导入.py",
               '"""绕过尝试：动态导入平台控制面模块。"""\n'
               '模块 = __import__("平台控制面.需求登记")\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        动态违规 = [违规 for 违规 in 结果.违规列表
                   if 违规.规则 == "动态导入绕过依赖审计"]
        self.assertTrue(动态违规, "平台控制面内 __import__ 必须被审计发现")
        self.assertTrue(动态违规[0].文件.endswith("偷导入.py"),
                        f"违规文件应指向绕过文件: {动态违规[0].文件}")
        self.assertFalse(结果.成功, "存在动态导入违规，审计必须不通过")

    def test_路径拼接动态导入被审计发现(self):
        写文件(self.临时目录, "偷拼接.py",
               '"""绕过尝试：路径拼接后动态导入。"""\n'
               'import importlib\n'
               '模块 = importlib.import_module("平台控制面." + "需求登记")\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        self.assertTrue(any(违规.规则 == "路径拼接动态导入绕过依赖审计"
                            for 违规 in 结果.违规列表),
                        "非字面量动态导入参数（路径拼接）必须被拒")

    def test_反射导入被审计发现(self):
        写文件(self.临时目录, "偷反射.py",
               '"""绕过尝试：反射执行导入。"""\n'
               'exec("import 平台控制面.需求登记")\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        self.assertTrue(any(违规.规则 == "反射导入绕过依赖审计"
                            for 违规 in 结果.违规列表),
                        "exec 反射导入必须被审计发现")

    def test_真实平台控制面目录零动态导入违规(self):
        结果 = 审计平台控制面()
        动态违规 = [违规 for 违规 in 结果.违规列表
                   if "动态导入" in 违规.规则 or "反射导入" in 违规.规则]
        self.assertEqual(动态违规, [],
                         "真实平台控制面目录不允许存在动态导入/反射导入违规: "
                         + ", ".join(审计结果转清单(结果)))
        self.assertGreater(结果.审计文件数, 10, "审计必须真实扫描平台控制面目录")

    # ---- 场景 2：统一入口代码不深入实现目录（AST 检查）----
    def test_统一入口代码不深入实现目录(self):
        结果 = 审计文件(系统根 / "平台控制面" / "统一入口.py", set())
        self.assertTrue(结果.成功, "统一入口.py 不得深入实现目录: "
                        + ", ".join(审计结果转清单(结果)))

    def test_跨包深入实现目录被审计发现(self):
        写文件(self.临时目录, "偷深实现.py",
               '"""绕过尝试：跨包直接深入实现目录。"""\n'
               'from 支持库.后端.文件系统.实现.文件系统 import 读取文件\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        self.assertTrue(any(违规.规则 == "跨包深入实现目录"
                            for 违规 in 结果.违规列表),
                        "跨包导入 实现/ 目录必须被拒")

    def test_路径字符串引用实现目录被审计发现(self):
        写文件(self.临时目录, "偷路径.py",
               '"""绕过尝试：字符串直接引用实现目录路径。"""\n'
               '目标 = "工程缓存/实现/内部文件.txt"\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        self.assertTrue(any(违规.规则 == "路径引用实现目录"
                            for 违规 in 结果.违规列表),
                        "字符串引用实现目录路径必须被审计发现")

    # ---- 场景 3：提供者直连外部服务绕过注册表（审计标记）----
    def test_未登记提供者直连外部服务被标记(self):
        提供者目录 = self.临时目录 / "提供者"
        提供者目录.mkdir()
        写文件(提供者目录, "__init__.py", '"""提供者声明：未登记任何提供者。"""\n')
        写文件(提供者目录, "偷连外部.py",
               '"""绕过尝试：未登记提供者直连外部服务。"""\n'
               'import urllib.request\n'
               'def 取数据():\n'
               '    return urllib.request.urlopen("http://外部服务/数据", timeout=1)\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        直连违规 = [违规 for 违规 in 结果.违规列表
                   if 违规.规则 == "提供者直连外部服务绕过注册表"]
        self.assertTrue(直连违规, "未登记提供者直连外部服务必须被审计标记")
        self.assertIn("urlopen()", 直连违规[0].目标)

    def test_已登记提供者直连外部服务不标记(self):
        提供者目录 = self.临时目录 / "提供者"
        提供者目录.mkdir()
        写文件(提供者目录, "__init__.py",
               '"""提供者声明。"""\nfrom 平台控制面.提供者 import 正经提供者\n')
        写文件(提供者目录, "正经提供者.py",
               '"""已登记提供者：真实外部调用。"""\n'
               'import urllib.request\n'
               'class 正经提供者:\n'
               '    def 取数据(self, 地址):\n'
               '        return urllib.request.urlopen(地址, timeout=1)\n')
        写文件(提供者目录, "偷连外部.py",
               '"""未登记提供者：绕过注册表。"""\n'
               'import urllib.request\n'
               'def 取数据():\n'
               '    return urllib.request.urlopen("http://外部服务/数据", timeout=1)\n')
        结果 = 审计平台控制面(目标目录=self.临时目录)
        直连违规 = [违规 for 违规 in 结果.违规列表
                   if "直连外部服务" in 违规.规则]
        self.assertEqual(len(直连违规), 1,
                         "只应标记未登记的 偷连外部.py，不标记声明登记的提供者")
        self.assertTrue(直连违规[0].文件.endswith("偷连外部.py"),
                        f"违规文件应指向未登记的绕过文件: {直连违规[0].文件}")

    def test_真实平台控制面目录零直连违规(self):
        结果 = 审计平台控制面()
        self.assertTrue(结果.成功,
                        "真实平台控制面目录必须零违规（冲突清单应为空）: "
                        + ", ".join(审计结果转清单(结果)))

    # ---- 场景 4：依赖未声明时发布策略拒绝（DEPENDENCY_MISSING）----
    def test_依赖未声明发布策略拒绝(self):
        状态 = 平台状态(self.临时目录 / "平台状态", 项目id="平台防火墙测试")
        try:
            目录 = 能力目录(状态)
            成功, 消息 = 目录.登记能力(
                能力id="文本处理.分割", 组件="文本组件", 领域="文本",
                契约={"能力id": "文本处理.分割", "参数": [], "返回": {}})
            self.assertTrue(成功, 消息)
            策略 = 策略中心(状态)
            # 发布请求缺少依赖声明 → 平台防火墙判定拒绝 DEPENDENCY_MISSING
            决定 = 发布依赖判定(状态, 请求={"调用者": "发布者A", "角色": "发布者"})
            self.assertFalse(决定["允许"], "依赖未声明必须拒绝发布")
            self.assertEqual(决定["错误码"], "DEPENDENCY_MISSING")
            # 声明了未登记依赖 → 真实策略中心同码拒绝（DEPENDENCY_MISSING）
            决定2 = 策略.判定(类型="依赖", 主题="包_新",
                             请求={"依赖": [{"能力id": "未登记.能力"}],
                                   "调用者": "发布者A", "角色": "发布者"})
            self.assertFalse(决定2["允许"])
            self.assertEqual(决定2["错误码"], "DEPENDENCY_MISSING")
            # 依赖已声明且已登记 → 允许
            决定3 = 发布依赖判定(状态, 请求={"依赖": [{"能力id": "文本处理.分割"}],
                                         "调用者": "发布者A", "角色": "发布者"})
            self.assertTrue(决定3["允许"], 决定3["理由"])
            # 依赖已声明但含未登记项 → 防火墙判定同码拒绝
            决定4 = 发布依赖判定(状态, 请求={"依赖": [{"能力id": "文本处理.分割"},
                                              {"能力id": "未登记.能力"}],
                                         "调用者": "发布者A"})
            self.assertFalse(决定4["允许"])
            self.assertEqual(决定4["错误码"], "DEPENDENCY_MISSING")
        finally:
            状态.关闭()


if __name__ == "__main__":
    unittest.main()
