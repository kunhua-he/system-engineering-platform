"""第二十六阶段wp1：角色MCP门面收敛矩阵测试（五类核心角色默认拒绝）。

覆盖：五类核心门面分类与工具/目录正向；专项角色决策；
未知角色拒绝；伪造令牌拒绝；越权工具拒绝；越界路径拒绝（含穿越/绝对路径）；
验证命令白名单（测试文件范围 / py_compile 范围 / 通用命令禁止）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

服务路径 = Path(__file__).resolve().parents[2] / "MCP工具箱" / "项目服务.py"
sys.path.insert(0, str(服务路径.parent))
规格 = importlib.util.spec_from_file_location("系统工程平台项目服务", 服务路径)
assert 规格 and 规格.loader
服务模块 = importlib.util.module_from_spec(规格)
规格.loader.exec_module(服务模块)

# 与服务模块共用同一角色权限实例，避免包/顶层双导入导致异常类不一致
角色权限模块 = sys.modules.get("MCP工具箱.角色权限") or sys.modules["角色权限"]

调用者 = 角色权限模块.调用者
支持库开发者 = 角色权限模块.支持库开发者
模块开发者 = 角色权限模块.模块开发者
核心开发者 = 角色权限模块.核心开发者
项目开发者 = 角色权限模块.项目开发者
平台构建开发者 = 角色权限模块.平台构建开发者
平台维护者 = 角色权限模块.平台维护者
发布者 = 角色权限模块.发布者
允许角色 = 角色权限模块.允许角色
五类核心门面 = 角色权限模块.五类核心门面
专项角色 = 角色权限模块.专项角色
可用工具 = 角色权限模块.可用工具
代码地图范围 = 角色权限模块.代码地图范围
允许测试范围 = 角色权限模块.允许测试范围
校验工具权限 = 角色权限模块.校验工具权限
校验角色令牌 = 角色权限模块.校验角色令牌
校验修改路径 = 角色权限模块.校验修改路径
校验验证命令 = 角色权限模块.校验验证命令
读取当前角色 = 角色权限模块.读取当前角色
门面分类 = 角色权限模块.门面分类
角色说明 = 角色权限模块.角色说明
越权拒绝 = 角色权限模块.越权拒绝

基础工具 = {"project_context", "role_profile", "capability_search", "capability_read",
            "mcp_feedback", "feedback_status"}
开发工具 = {"codegraph_explore", "memory_search", "memory_write", "verify_and_record",
            "verification_plan", "development_start", "temporary_context", "task_observation"}


class 五类核心门面测试(unittest.TestCase):
    """五类核心角色门面：分类、工具面与允许目录正向。"""

    def test_五类核心门面分类正确(self) -> None:
        self.assertEqual(门面分类(调用者), "调用者门面")
        self.assertEqual(门面分类(支持库开发者), "支持库开发者门面")
        self.assertEqual(门面分类(模块开发者), "模块开发者门面")
        self.assertEqual(门面分类(核心开发者), "核心开发者门面")
        self.assertEqual(门面分类(平台维护者), "平台维护与发布门面")
        self.assertEqual(门面分类(发布者), "平台维护与发布门面")
        self.assertIn(平台维护者, 五类核心门面["平台维护与发布门面"])
        self.assertIn(发布者, 五类核心门面["平台维护与发布门面"])

    def test_五类核心门面工具面正确(self) -> None:
        期望专属 = {
            支持库开发者: {"support_library_development_guide"},
            模块开发者: {"module_development_guide"},
            核心开发者: {"core_development_guide"},
            平台维护者: {"platform_maintenance_guide", "feedback_review"},
            发布者: {"release_guide", "feedback_review"},
        }
        self.assertEqual(可用工具(调用者), 基础工具, "调用者只读门面无开发工具")
        for 角色, 专属 in 期望专属.items():
            工具表 = 可用工具(角色)
            self.assertEqual(工具表, 基础工具 | 开发工具 | 专属, f"{角色} 工具面不符")

    def test_调用者门面无开发工具无源码范围(self) -> None:
        self.assertEqual(可用工具(调用者), 基础工具)
        self.assertEqual(代码地图范围(调用者), [])
        self.assertEqual(允许测试范围(调用者), [])

    def test_五类核心门面允许目录正确(self) -> None:
        期望目录 = {
            支持库开发者: ["公共契约", "支持库", "测试中心/支持库"],
            模块开发者: ["模块库", "测试中心/模块库"],
            核心开发者: ["运行核心", "前端核心", "后端核心", "启动监督器", "测试中心"],
            平台维护者: ["平台控制面", "开发工具", "MCP工具箱", "测试中心"],
            发布者: ["平台控制面/发布管理", "平台控制面/包仓库", "开发工具/发布门禁"],
        }
        for 角色, 目录表 in 期望目录.items():
            self.assertEqual(代码地图范围(角色), 目录表, f"{角色} 允许目录不符")

    def test_专项角色保留且受同一套默认拒绝(self) -> None:
        """收敛决策：项目开发者/平台构建开发者 保留为专项角色（非五类核心门面）。"""
        self.assertEqual(set(专项角色), {项目开发者, 平台构建开发者})
        self.assertEqual(门面分类(项目开发者), 项目开发者)
        self.assertEqual(门面分类(平台构建开发者), 平台构建开发者)
        self.assertIn("project_development_guide", 可用工具(项目开发者))
        self.assertIn("platform_build_development_guide", 可用工具(平台构建开发者))
        # 专项角色同样默认拒绝
        with self.assertRaises(越权拒绝):
            校验工具权限(项目开发者, "feedback_review")
        with self.assertRaises(越权拒绝):
            校验修改路径(项目开发者, ["运行核心/加载器/加载器.py"])

    def test_角色说明携带边界且未知角色拒绝(self) -> None:
        说明 = 角色说明(核心开发者)
        self.assertEqual(说明["角色"], 核心开发者)
        self.assertIn("允许目录", 说明)
        with self.assertRaises(越权拒绝) as 上下文:
            角色说明("不存在角色")
        self.assertEqual(上下文.exception.错误码, "未知角色")


class 默认拒绝测试(unittest.TestCase):
    """默认拒绝：未知角色、伪造令牌、越权工具、越界路径必须真实失败。"""

    def test_未知角色令牌拒绝(self) -> None:
        with self.assertRaises(越权拒绝) as 上下文:
            校验角色令牌("不存在角色")
        self.assertEqual(上下文.exception.错误码, "未知角色")
        self.assertNotIn("不存在角色", 允许角色)
        self.assertEqual(可用工具("不存在角色"), set())
        self.assertEqual(代码地图范围("不存在角色"), [])

    def test_伪造令牌拒绝(self) -> None:
        """空白/控制字符/超长/非字符串/大小写变体一律拒绝，不清洗。"""
        for 伪造值 in ["平台维护者 ", " 平台维护者", "平台维护者\n", "平台\t维护者",
                        "平台维护者" * 5, "平台维护者;rm -rf /", "", 123]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验角色令牌(伪造值)  # type: ignore[arg-type]
            self.assertEqual(上下文.exception.错误码, "伪造令牌", f"{伪造值!r} 应判伪造令牌")

    def test_环境变量注入不可信值拒绝(self) -> None:
        with mock.patch.dict(os.environ, {"SYSTEM_ENGINEERING_MCP_ROLE": "平台维护者;注入"}):
            with self.assertRaises(越权拒绝) as 上下文:
                读取当前角色()
            self.assertEqual(上下文.exception.错误码, "伪造令牌")
        with mock.patch.dict(os.environ, {"SYSTEM_ENGINEERING_MCP_ROLE": "核心开发者 "}):
            with self.assertRaises(越权拒绝) as 上下文:
                读取当前角色()
            self.assertEqual(上下文.exception.错误码, "伪造令牌")

    def test_环境变量未配置保持历史默认(self) -> None:
        """缺省值只服务于测试/裸跑场景；显式令牌一律严格校验，异常值一律拒绝。"""
        原值 = os.environ.pop("SYSTEM_ENGINEERING_MCP_ROLE", None)
        try:
            self.assertEqual(读取当前角色(), 平台维护者)
        finally:
            if 原值 is not None:
                os.environ["SYSTEM_ENGINEERING_MCP_ROLE"] = 原值
        self.assertEqual(读取当前角色(令牌=平台维护者), 平台维护者)
        with self.assertRaises(越权拒绝):
            读取当前角色(令牌="平台维护者 ")

    def test_未知角色令牌在门面分类中拒绝(self) -> None:
        with self.assertRaises(越权拒绝) as 上下文:
            门面分类("不存在角色")
        self.assertEqual(上下文.exception.错误码, "未知角色")

    def test_越权工具拒绝且错误码为权限不足(self) -> None:
        for 角色, 越权工具 in [
            (调用者, "codegraph_explore"),
            (支持库开发者, "module_development_guide"),
            (模块开发者, "support_library_development_guide"),
            (核心开发者, "feedback_review"),
            (平台维护者, "release_guide"),
            (发布者, "platform_maintenance_guide"),
        ]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验工具权限(角色, 越权工具)
            self.assertEqual(上下文.exception.错误码, "权限不足")
            self.assertIn("无权调用工具", 上下文.exception.消息)
            self.assertNotIn(越权工具, 可用工具(角色))

    def test_合法工具放行与越权拒绝成对(self) -> None:
        """拒绝不是恒真：同一角色合法放行、越权拒绝并存。"""
        for 角色, 合法工具, 越权工具 in [
            (支持库开发者, "support_library_development_guide", "module_development_guide"),
            (模块开发者, "module_development_guide", "core_development_guide"),
            (核心开发者, "core_development_guide", "release_guide"),
            (平台维护者, "feedback_review", "release_guide"),
            (发布者, "release_guide", "platform_maintenance_guide"),
        ]:
            self.assertIsNone(校验工具权限(角色, 合法工具))
            with self.assertRaises(越权拒绝):
                校验工具权限(角色, 越权工具)


class 越界路径测试(unittest.TestCase):
    """越界路径：允许目录外拒绝；穿越/绝对路径拒绝。"""

    def test_允许目录内修改路径放行(self) -> None:
        self.assertIsNone(校验修改路径(核心开发者, ["运行核心/加载器/加载器.py"]))
        self.assertIsNone(校验修改路径(支持库开发者, ["支持库/能力域/原子能力.py"]))
        self.assertIsNone(校验修改路径(模块开发者, ["模块库/业务模块/模块.py"]))
        self.assertIsNone(校验修改路径(平台维护者, ["MCP工具箱/角色权限.py"]))
        self.assertIsNone(校验修改路径(发布者, ["平台控制面/发布管理/发布.py"]))

    def test_允许目录外修改路径拒绝且错误码为角色越权(self) -> None:
        for 角色, 越权路径 in [
            (支持库开发者, ["模块库/业务模块/模块.py"]),
            (模块开发者, ["支持库/能力域/原子能力.py"]),
            (核心开发者, ["平台控制面/包仓库/制品.py"]),
            (平台维护者, ["运行核心/加载器/加载器.py"]),
            (发布者, ["运行核心/加载器/加载器.py"]),
        ]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验修改路径(角色, 越权路径)
            self.assertEqual(上下文.exception.错误码, "角色越权", f"{角色} {越权路径}")

    def test_路径穿越拒绝(self) -> None:
        """.. 穿越不得借允许目录前缀逃逸；出根穿越判越界路径，域内越权判角色越权。"""
        # 穿越后落在允许目录外：角色越权（真实目标不在角色范围内）
        for 穿越路径 in [
            "运行核心/../平台控制面/包仓库/制品.py",
            "支持库/../模块库/模块.py",
            "测试中心/../MCP工具箱/角色权限.py",
        ]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验修改路径(核心开发者, [穿越路径])
            self.assertEqual(上下文.exception.错误码, "角色越权", f"域内穿越未拒绝: {穿越路径}")
        # 穿越后越出仓库根：越界路径
        for 出根路径 in [
            "运行核心/../../平台控制面/制品.py",
            "测试中心/../../秘密/密钥.py",
            "./运行核心/../../后端核心/x.py",
        ]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验修改路径(核心开发者, [出根路径])
            self.assertEqual(上下文.exception.错误码, "越界路径", f"出根穿越未拒绝: {出根路径}")
        # 穿越后真实目标仍在允许目录内：规范化后放行（真实目标即校验对象）
        self.assertIsNone(校验修改路径(核心开发者, ["测试中心/../运行核心/加载器/加载器.py"]))

    def test_绝对路径与盘符拒绝(self) -> None:
        for 非法路径 in ["/etc/passwd", "/Users/共享/密钥.py", "C:/Windows/x.py", "C:\\Windows\\x.py"]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验修改路径(核心开发者, [非法路径])
            self.assertEqual(上下文.exception.错误码, "越界路径", f"绝对路径未拒绝: {非法路径}")

    def test_调用者无任何修改路径(self) -> None:
        with self.assertRaises(越权拒绝):
            校验修改路径(调用者, ["支持库/能力域/原子能力.py"])


class 验证命令白名单测试(unittest.TestCase):
    """验证命令固定入口白名单：范围内放行、越权/通用命令拒绝。"""

    def test_固定入口白名单放行(self) -> None:
        校验验证命令(核心开发者, ["python3.14", "测试中心/运行测试.py",
                                  "--测试文件", "测试中心/MCP工具箱/测试_x.py", "--并行数", "0"])
        校验验证命令(支持库开发者, ["python3.14", "测试中心/运行测试.py",
                                 "--测试文件", "测试中心/支持库/测试_x.py"])
        校验验证命令(平台维护者, ["python3.14", "测试中心/运行测试.py",
                               "--测试文件", "测试中心/MCP工具箱/测试_x.py"])
        校验验证命令(核心开发者, ["python3.14", "-m", "py_compile", "运行核心/加载器/加载器.py"])
        校验验证命令(核心开发者, ["git", "diff", "--check"])
        校验验证命令(核心开发者, ["codegraph", "status"])
        校验验证命令(发布者, ["python3.14", "开发工具/发布门禁/运行发布门禁.py"])
        校验验证命令(平台维护者, ["python3.14", "开发工具/发布门禁/运行发布门禁.py"])

    def test_测试文件越出角色范围拒绝(self) -> None:
        with self.assertRaises(越权拒绝) as 上下文:
            校验验证命令(支持库开发者, ["python3.14", "测试中心/运行测试.py",
                                     "--测试文件", "测试中心/模块库/测试_x.py"])
        self.assertEqual(上下文.exception.错误码, "角色越权")
        with self.assertRaises(越权拒绝) as 上下文2:
            校验验证命令(发布者, ["python3.14", "测试中心/运行测试.py",
                               "--测试文件", "测试中心/平台控制面/测试_x.py"])
        self.assertEqual(上下文2.exception.错误码, "权限不足")

    def test_通用命令执行器被拒(self) -> None:
        for 命令 in [
            ["python3.14", "-c", "print(1)"],
            ["python3.14", "-c", "import os; os.system('rm -rf /')"],
            ["bash", "-c", "echo 越权"],
            ["python3.14", "随便的脚本.py"],
            ["python3.14", "测试中心/../运行核心/加载器.py"],
            ["python3.14", "/tmp/任意.py"],
            ["python3.14", "测试中心/运行测试.py", "--测试文件", "测试中心/../运行核心/x.py"],
        ]:
            with self.assertRaises(越权拒绝):
                校验验证命令(核心开发者, 命令)

    def test_py_compile文件范围校验(self) -> None:
        校验验证命令(核心开发者, ["python3.14", "-m", "py_compile", "运行核心/加载器/加载器.py"])
        with self.assertRaises(越权拒绝) as 上下文:
            校验验证命令(核心开发者, ["python3.14", "-m", "py_compile",
                                     "平台控制面/包仓库/制品.py"])
        self.assertEqual(上下文.exception.错误码, "角色越权")
        with self.assertRaises(越权拒绝) as 穿越:
            校验验证命令(核心开发者, ["python3.14", "-m", "py_compile",
                                     "运行核心/../../平台控制面/制品.py"])
        self.assertEqual(穿越.exception.错误码, "越界路径")

    def test_无测试范围角色拒绝测试入口(self) -> None:
        with self.assertRaises(越权拒绝) as 上下文:
            校验验证命令(调用者, ["python3.14", "测试中心/运行测试.py"])
        self.assertEqual(上下文.exception.错误码, "权限不足")

    def test_核心开发者全量测试范围无需限定文件(self) -> None:
        校验验证命令(核心开发者, ["python3.14", "测试中心/运行测试.py"])
        校验验证命令(平台维护者, ["python3.14", "测试中心/运行测试.py"])

    def test_专项角色测试范围(self) -> None:
        校验验证命令(项目开发者, ["python3.14", "测试中心/运行测试.py",
                                "--测试文件", "测试中心/项目适配层/测试_x.py"])
        with self.assertRaises(越权拒绝):
            校验验证命令(项目开发者, ["python3.14", "测试中心/运行测试.py",
                                    "--测试文件", "测试中心/支持库/测试_x.py"])
        校验验证命令(平台构建开发者, ["python3.14", "测试中心/运行测试.py",
                                   "--测试文件", "测试中心/客户端/测试_x.py"])

    def test_角色与命令范围一致无第二套白名单(self) -> None:
        测试文件表 = 允许测试范围(支持库开发者)
        self.assertEqual(测试文件表, ["测试中心/支持库"])
        self.assertEqual(允许测试范围(调用者), [])
        self.assertEqual(允许测试范围(发布者), [])


if __name__ == "__main__":
    unittest.main()
