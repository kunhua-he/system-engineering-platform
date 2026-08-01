"""第六阶段：真实运行时、真实包管理与发布闭环测试。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.包仓库.版本仓库 import 包仓库, 计算目录摘要
from 平台控制面.包仓库.生命周期 import 包生命周期
from 运行核心.加载器.提供者隔离.独立进程 import 独立进程
from 运行核心.加载器.版本系统.灰度指标 import 灰度指标库
from 运行核心.加载器.版本系统.热切换 import 热切换管理器
from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
from 支持库.适配层.配置安全.密钥引用 import 密钥引用解析器, 校验引用完整性


def 构造测试包(目录: Path, *, 包id: str, 版本: str) -> Path:
    """构造一个可安装的测试包（含权限声明）。"""
    包目录 = 目录 / f"{包id}@{版本}"
    (包目录 / "能力契约").mkdir(parents=True, exist_ok=True)
    (包目录 / "实现").mkdir(parents=True, exist_ok=True)
    (包目录 / "权限声明").mkdir(parents=True, exist_ok=True)
    (包目录 / "配置声明").mkdir(parents=True, exist_ok=True)
    (包目录 / "包声明.json").write_text(json.dumps({
        "包id": 包id, "名称": 包id.split(".")[-1], "类型": "支持库",
        "版本": 版本, "契约版本": "1.0.0", "入口": "__init__.py",
        "依赖": [], "能力": [{"能力id": f"{包id}.能力", "名称": "能力", "参数": [], "返回": "结果"}],
    }, ensure_ascii=False), encoding="utf-8")
    (包目录 / "能力契约" / "参数契约.json").write_text('{"能力契约": []}', encoding="utf-8")
    (包目录 / "实现" / "实现.py").write_text('def 示例():\n    return 1\n', encoding="utf-8")
    (包目录 / "权限声明" / "权限声明.json").write_text(
        '{"第三方依赖": [], "网络访问": false, "文件访问": "受限"}', encoding="utf-8")
    (包目录 / "__init__.py").write_text('def 注册能力(注册表):\n    pass\n', encoding="utf-8")
    return 包目录


class Test包仓库(unittest.TestCase):
    """场景1-4 + 25-26：安装/拒绝/清理/摘要/引用保护/安全清理。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段仓库_"))
        self.仓库 = 包仓库(self.临时目录 / "仓库")
        self.源目录 = 构造测试包(self.临时目录, 包id="测试.包甲", 版本="1.0.0")

    def test_本地包安装(self):
        成功, 记录 = self.仓库.安装(self.源目录)
        self.assertTrue(成功, str(记录))
        self.assertTrue(self.仓库.已安装("测试.包甲", "1.0.0"))
        self.assertTrue(记录.完整性摘要)
        self.assertEqual(len(self.仓库.查询安装记录(包id="测试.包甲")), 1)

    def test_重复版本安装拒绝(self):
        成功, _ = self.仓库.安装(self.源目录)
        self.assertTrue(成功)
        再次, 原因 = self.仓库.安装(self.源目录)
        self.assertFalse(再次)
        self.assertIn("不能重复覆盖", 原因)

    def test_安装失败清理(self):
        # 源目录缺实现 → 失败且无残留临时目录
        坏源 = self.临时目录 / "坏包"
        坏源.mkdir()
        (坏源 / "包声明.json").write_text(json.dumps({"包id": "坏.包", "版本": "1.0.0"}), encoding="utf-8")
        成功, 原因 = self.仓库.安装(坏源)
        self.assertFalse(成功)
        残留 = [文件 for 文件 in (self.临时目录 / "仓库" / "版本").iterdir() if ".临时" in 文件.name]
        self.assertEqual(len(残留), 0)

    def test_完整性摘要校验(self):
        成功, 记录 = self.仓库.安装(self.源目录)
        self.assertTrue(成功)
        通过, 摘要 = self.仓库.校验完整性("测试.包甲", "1.0.0", 记录.完整性摘要)
        self.assertTrue(通过)
        self.assertEqual(摘要, 记录.完整性摘要)

    def test_卸载前引用保护(self):
        成功, _ = self.仓库.安装(self.源目录)
        self.assertTrue(成功)
        可删, 原因 = self.仓库.删除("测试.包甲", "1.0.0", 引用项目=["旧项目"])
        self.assertFalse(可删)
        self.assertIn("仍被项目引用", 原因)

    def test_旧版本安全清理(self):
        成功, _ = self.仓库.安装(self.源目录)
        self.assertTrue(成功)
        可删, 原因 = self.仓库.删除("测试.包甲", "1.0.0")
        self.assertTrue(可删, 原因)
        self.assertFalse(self.仓库.已安装("测试.包甲", "1.0.0"))


class Test真实子进程(unittest.TestCase):
    """场景5-11 + 12：真实 subprocess 全生命周期。"""

    @classmethod
    def setUpClass(cls):
        cls.临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段进程_"))
        cls.进程 = 独立进程("测试进程", 调用超时秒=1.0)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.进程.关闭并清理()
        except Exception:
            pass

    def test_真实子进程启动(self):
        成功, 消息 = self.进程.启动()
        self.assertTrue(成功, 消息)
        self.assertEqual(self.进程.状态, "运行中")

    def test_子进程调用(self):
        if self.进程.状态 != "运行中":
            self.进程.启动()
        结果 = self.进程.调用(能力id="进程.最小操作", 参数={"名称": "测试调用"})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值.get("工作器"), "真实子进程")

    def test_子进程超时(self):
        进程 = 独立进程("超时进程", 调用超时秒=0.2)
        成功, _ = 进程.启动()
        self.assertTrue(成功)
        结果 = 进程.调用(能力id="进程.最小操作", 参数={"名称": "慢操作"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        进程.关闭并清理()

    def test_子进程崩溃与自动重启(self):
        进程 = 独立进程("崩溃进程", 最大重启次数=2)
        成功, _ = 进程.启动()
        self.assertTrue(成功)
        # 直接终止子进程模拟崩溃
        进程.进程.terminate()
        进程.进程.wait(timeout=3)
        崩溃 = 进程.崩溃检测()
        self.assertFalse(崩溃)  # 已自动重启
        self.assertGreaterEqual(进程.重启次数, 1)
        self.assertEqual(进程.状态, "运行中")
        进程.关闭并清理()

    def test_优雅停止(self):
        if self.进程.状态 != "运行中":
            self.进程.启动()
        成功, 消息 = self.进程.优雅停止()
        self.assertTrue(成功, 消息)
        self.assertEqual(self.进程.状态, "已停止")
        self.assertEqual(self.进程.退出码, 0)

    def test_强制终止(self):
        进程 = 独立进程("强制进程")
        self.assertTrue(进程.启动()[0])
        成功, 消息 = 进程.强制终止()
        self.assertTrue(成功, 消息)
        self.assertEqual(进程.状态, "已停止")

    def test_新旧提供者并行(self):
        """旧新进程并行运行（有状态不可迁移场景）。"""
        from 运行核心.加载器.版本系统.热切换 import 热切换管理器
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段并行_"))
        注册表 = 版本注册表(临时目录)
        注册表.注册版本("并行.能力", "1.0.0", 声明字典={"包id": "并行.能力", "版本": "1.0.0"})
        注册表.注册版本("并行.能力", "1.1.0", 声明字典={"包id": "并行.能力", "版本": "1.1.0"})
        切换 = 热切换管理器(注册表)
        切换.设置激活("并行.能力", "1.0.0", 回退版本="1.0.0")
        结果 = 切换.真实热切换(
            能力id="并行.能力", 新版本="1.1.0", 回退版本="1.0.0",
            状态可迁移=False,  # 不可迁移 → 并行运行
        )
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertTrue(any("并行运行" in 步骤 for 步骤 in 结果.步骤列表))
        旧进程 = 切换.提供者进程表["并行.能力"]["1.0.0"]
        新进程 = 切换.提供者进程表["并行.能力"]["1.1.0"]
        self.assertEqual(旧进程.状态, "运行中")  # 旧进程未停止（并行）
        self.assertEqual(新进程.状态, "运行中")
        旧进程.关闭并清理()
        新进程.关闭并清理()


class Test真实热切换(unittest.TestCase):
    """场景13-15：无状态切换/有状态排空/失败回滚。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段切换_"))
        self.注册表 = 版本注册表(self.临时目录)
        for 版本 in ("1.0.0", "1.1.0"):
            self.注册表.注册版本("切换.能力", 版本, 声明字典={"包id": "切换.能力", "版本": 版本})
        self.切换 = 热切换管理器(self.注册表)
        self.切换.设置激活("切换.能力", "1.0.0", 回退版本="1.0.0")

    def tearDown(self):
        for 版本进程表 in self.切换.提供者进程表.values():
            for 进程 in 版本进程表.values():
                try:
                    进程.关闭并清理()
                except Exception:
                    pass

    def test_无状态热切换(self):
        结果 = self.切换.真实热切换(能力id="切换.能力", 新版本="1.1.0", 回退版本="1.0.0")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(self.切换.激活映射["切换.能力"], "1.1.0")
        调用 = self.切换.调用路由("切换.能力", {"名称": "切换后调用"})
        self.assertTrue(调用.成功)
        self.assertEqual(调用.值.get("工作器"), "真实子进程")

    def test_有状态排空切换(self):
        结果 = self.切换.真实热切换(
            能力id="切换.能力", 新版本="1.1.0", 回退版本="1.0.0", 状态可迁移=True,
        )
        self.assertTrue(结果.成功)
        self.assertTrue(any("排空" in 步骤 for 步骤 in 结果.步骤列表))
        self.assertTrue(any("优雅停止" in 步骤 for 步骤 in 结果.步骤列表))

    def test_热切换失败回滚(self):
        """新进程健康失败 → 自动回滚，旧进程可继续调用。"""
        结果 = self.切换.真实热切换(
            能力id="切换.能力", 新版本="1.1.0", 回退版本="1.0.0",
            新进程健康失败=True,
        )
        self.assertFalse(结果.成功)
        self.assertTrue(结果.自动回滚)
        旧进程 = self.切换.提供者进程表["切换.能力"]["1.0.0"]
        self.assertEqual(旧进程.状态, "运行中")  # 旧提供者不受影响
        调用 = 旧进程.调用(能力id="进程.最小操作", 参数={"名称": "回滚后调用"})
        self.assertTrue(调用.成功)
        self.assertEqual(len(self.切换.回滚记录表), 1)

    def test_重复回滚幂等(self):
        结果1 = self.切换.真实热切换(能力id="切换.能力", 新版本="1.1.0", 回退版本="1.0.0", 新进程启动失败=True)
        结果2 = self.切换.真实热切换(能力id="切换.能力", 新版本="1.1.0", 回退版本="1.0.0", 新进程启动失败=True)
        self.assertTrue(结果1.自动回滚 and 结果2.自动回滚)
        self.assertEqual(self.切换.激活映射["切换.能力"], "1.0.0")


class Test灰度指标持久化(unittest.TestCase):
    """场景16-17：持久化 + 重启恢复。"""

    def test_指标持久化与恢复(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段灰度_"))
        库 = 灰度指标库(临时目录)
        for _ in range(3):
            问题 = 库.观测(能力id="灰.能力", 版本="1.1.0", 成功=True, 耗时毫秒=15)
        self.assertFalse(问题)
        库.观测(能力id="灰.能力", 版本="1.1.0", 成功=False)
        # 新实例（模拟进程重启）恢复
        库2 = 灰度指标库(临时目录)
        指标 = 库2.聚合(能力id="灰.能力", 版本="1.1.0")
        self.assertEqual(指标.请求总数, 4)
        self.assertEqual(指标.成功数, 3)
        self.assertEqual(指标.失败数, 1)
        self.assertTrue(库2.指标文件.is_file())

    def test_阈值自动回滚触发(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段灰度回滚_"))
        库 = 灰度指标库(临时目录)
        问题列表 = []
        for _ in range(6):
            问题列表 = 库.观测(能力id="灰.能力", 版本="1.1.0", 成功=False)
        self.assertTrue(问题列表)
        self.assertTrue(any("失败率" in 问题 for 问题 in 问题列表))
        库.触发回滚("灰.能力", "1.1.0", "失败率超阈值")
        库2 = 灰度指标库(临时目录)
        self.assertIn("触发回滚原因", 库2.状态表.get("灰.能力@1.1.0", {}))


class Test诊断复现(unittest.TestCase):
    """场景18-19：真实复现 + 输入脱敏。"""

    def test_错误诊断真实复现(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段复现_"))
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
        from 运行核心.运行诊断.诊断中心.诊断复现 import 复现执行, 结论_可稳定复现
        失败库 = 失败记录库(临时目录)
        记录 = 失败库.登记失败(追踪id="复现1", 包id="复现.包", 错误码="外部未安装",
                              错误说明="驱动缺失", 复现输入="查询=SELECT 1")
        结果 = 复现执行(记录, 临时目录=临时目录)
        self.assertEqual(结果.结论, 结论_可稳定复现)
        复现文件 = 临时目录 / f"复现_{结果.复现id}.json"
        self.assertTrue(复现文件.is_file())  # 证据在临时目录

    def test_复现输入脱敏(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段脱敏_"))
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
        from 运行核心.运行诊断.诊断中心.诊断复现 import 复现执行
        失败库 = 失败记录库(临时目录)
        记录 = 失败库.登记失败(追踪id="脱敏1", 包id="脱敏.包", 错误码="内部错误",
                              错误说明="认证失败 sk-真实密钥9999")
        结果 = 复现执行(记录, 临时目录=临时目录)
        复现文件 = 临时目录 / f"复现_{结果.复现id}.json"
        内容 = 复现文件.read_text(encoding="utf-8")
        self.assertNotIn("sk-真实密钥9999", 内容)
        self.assertIn("已脱敏", 内容)

    def test_复现失败不覆盖原始记录(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段复现保留_"))
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
        from 运行核心.运行诊断.诊断中心.诊断复现 import 复现执行
        失败库 = 失败记录库(临时目录)
        记录 = 失败库.登记失败(追踪id="保留1", 包id="保留.包", 错误码="超时", 错误说明="x")
        结果 = 复现执行(记录, 临时目录=临时目录, 提供者可用=False)
        self.assertEqual(结果.结论, "外部提供者不可用")
        原记录 = 失败库.记录表[记录.记录id]
        self.assertEqual(原记录.错误码, "超时")  # 原始失败记录未被覆盖


class Test密钥引用(unittest.TestCase):
    """场景20-21：环境变量引用 + 敏感值不进日志。"""

    def test_敏感配置环境变量引用(self):
        os.environ["测试数据库密钥环境变量"] = "内部值123"
        try:
            解析器 = 密钥引用解析器()
            结果 = 解析器.解析("数据库连接密钥", "测试数据库密钥环境变量", 请求方="门禁测试")
            self.assertTrue(结果.成功)
            self.assertEqual(结果.值, "内部值123")  # 敏感值只在内存
            记录 = 解析器.查询访问记录()
            self.assertEqual(记录[0]["结果"], "允许")
            self.assertEqual(记录[0]["请求方"], "门禁测试")  # 来源记录
        finally:
            del os.environ["测试数据库密钥环境变量"]

    def test_缺少环境变量明确失败(self):
        解析器 = 密钥引用解析器()
        结果 = 解析器.解析("数据库连接密钥", "不存在的环境变量XYZ", 请求方="测试")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "敏感配置缺失")

    def test_明文密钥拒绝(self):
        解析器 = 密钥引用解析器()
        结果 = 解析器.解析("数据库连接密钥", "sk-真实明文密钥9999", 请求方="测试")
        self.assertFalse(结果.成功)
        self.assertIn("疑似明文", 结果.错误说明)
        # 校验引用完整性
        问题 = 校验引用完整性({"数据库连接密钥": "sk-明文"})
        self.assertTrue(问题)

    def test_敏感值不进入日志(self):
        os.environ["测试密钥日志"] = "超级敏感值999"
        try:
            from 运行核心.运行诊断.运行事件.事件日志 import 事件日志
            from 运行核心.运行诊断.运行事件.事件模型 import 生成事件
            临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段日志_"))
            日志 = 事件日志(临时目录)
            日志.写入(生成事件("调用失败", 成功=False, 错误码="内部错误",
                              错误说明="处理失败，连接密钥=sk-敏感值999"))
            内容 = 日志.当前文件.read_text(encoding="utf-8")
            self.assertNotIn("sk-敏感值999", 内容)
            self.assertIn("已脱敏", 内容)
        finally:
            del os.environ["测试密钥日志"]


class Test本地协议(unittest.TestCase):
    """场景22：本地 JSON 查询协议。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段协议_"))
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
        from 开发工具.统一能力入口.Agent查询.本地协议 import 本地协议服务器
        self.失败库 = 失败记录库(self.临时目录)
        self.失败库.登记失败(追踪id="协议1", 包id="协议.包", 错误码="超时", 错误说明="连接超时")
        self.服务器 = 本地协议服务器(失败库=self.失败库)

    def test_本地JSON查询协议(self):
        响应 = self.服务器.处理({"操作": "查看版本", "参数": {}})
        self.assertEqual(响应.状态, "完成")
        self.assertTrue(响应.操作id)
        self.assertIsInstance(响应.结果, list)

    def test_协议查询失败记录(self):
        响应 = self.服务器.处理({"操作": "查询失败记录", "参数": {"包id": "协议.包"}})
        self.assertEqual(响应.状态, "完成")
        self.assertEqual(len(响应.结果), 1)

    def test_协议未知操作失败(self):
        响应 = self.服务器.处理({"操作": "不存在的操作", "参数": {}})
        self.assertEqual(响应.状态, "失败")
        self.assertEqual(响应.错误码, "未知操作")

    def test_协议命令行入口(self):
        import subprocess as _子进程
        import json as _json
        请求 = _json.dumps({"操作": "查看版本", "参数": {}}, ensure_ascii=False)
        运行 = _子进程.run(
            ["python3.14", str(系统根 / "开发工具" / "统一能力入口" / "Agent查询" / "本地协议.py"), "--请求", 请求],
            capture_output=True, text=True,
        )
        self.assertEqual(运行.returncode, 0)
        响应 = _json.loads(运行.stdout)
        self.assertEqual(响应["操作"], "查看版本")
        self.assertNotEqual(响应["状态"], "失败")


class Test包生命周期(unittest.TestCase):
    """场景27：16 态状态机。"""

    def test_正常流转与非法跳转拒绝(self):
        生命周期 = 包生命周期("生命.包", "1.0.0")
        for 状态 in ("安装中", "已安装", "校验中", "已校验", "已解析", "启动中", "已就绪", "灰度中", "已激活"):
            记录 = 生命周期.流转(状态)
            self.assertTrue(记录.成功, f"{状态}: {记录.错误说明}")
        非法 = 生命周期.流转("已卸载")  # 已激活 → 已卸载 非法
        self.assertFalse(非法.成功)
        self.assertEqual(非法.错误码, "状态跳转非法")

    def test_重复操作幂等(self):
        生命周期 = 包生命周期("生命.包", "1.0.0")
        生命周期.流转("安装中")
        生命周期.流转("已安装")
        生命周期.流转("校验中")
        生命周期.流转("已校验")
        生命周期.流转("已解析")
        生命周期.流转("启动中")
        生命周期.流转("已就绪")
        记录 = 生命周期.流转("已激活")
        self.assertTrue(记录.成功)
        重复 = 生命周期.流转("已激活")  # 重复激活幂等
        self.assertTrue(重复.成功)

    def test_失败回滚与历史保留(self):
        生命周期 = 包生命周期("生命.包", "1.0.0")
        生命周期.流转("安装中")
        生命周期.流转("已安装")
        生命周期.流转("校验中")
        生命周期.流转("已校验")
        生命周期.流转("已解析")
        生命周期.流转("启动中")
        生命周期.流转("已就绪")
        生命周期.流转("故障", 成功=True, 错误码="启动失败", 错误说明="提供者崩溃")
        self.assertEqual(生命周期.状态, "故障")
        生命周期.回滚("启动失败")
        self.assertEqual(生命周期.状态, "已就绪")  # 回滚到上一稳定状态
        self.assertTrue(生命周期.检查历史("失败回滚"))
        self.assertGreaterEqual(len(生命周期.历史记录), 8)  # 历史不丢失


class Test发布门禁(unittest.TestCase):
    """场景23-24：门禁阻断/通过。"""

    def test_跳过测试必须阻断发布(self):
        from 开发工具.发布门禁.运行发布门禁 import 执行门禁
        临时目录 = Path(tempfile.mkdtemp(prefix="第六阶段门禁_"))
        包目录 = 构造测试包(临时目录, 包id="门禁.包", 版本="1.0.0")
        结果 = 执行门禁(包目录=包目录, 运行测试=False, 真实进程=True)
        self.assertEqual(结果.发布状态, "失败", 结果.打印())
        测试项 = next(项 for 项 in 结果.门禁项列表 if 项.名称 == "测试全部通过")
        self.assertFalse(测试项.通过)


if __name__ == "__main__":
    unittest.main()
