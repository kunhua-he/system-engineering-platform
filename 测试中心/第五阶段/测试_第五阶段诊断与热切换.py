"""第五阶段：工业化诊断、版本升级与热切换闭环测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库, 状态_已关闭, 状态_待诊断, 状态_已忽略
from 运行核心.运行诊断.诊断中心.诊断中心 import 归类失败, 关联验证场景, 诊断失败
from 运行核心.运行诊断.运行事件.事件日志 import 事件日志
from 运行核心.运行诊断.运行事件.事件模型 import 生成事件
from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏事件字典, 脱敏文本
from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
from 运行核心.加载器.版本系统.契约兼容 import 检查契约兼容
from 运行核心.加载器.版本系统.兼容适配器 import 适配器声明, 兼容适配器
from 运行核心.加载器.版本系统.热切换 import 热切换管理器
from 运行核心.加载器.版本系统.状态切换 import 执行切换, 判断有无状态
from 运行核心.加载器.版本系统.弃用清理 import 卸载条件, 执行卸载


class Test事件日志(unittest.TestCase):
    """场景1-5：结构化日志/脱敏/过滤/聚合。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段日志_"))
        self.日志 = 事件日志(self.临时目录)

    def tearDown(self):
        pass

    def test_结构化成功日志(self):
        事件 = 生成事件("调用成功", 能力id="文件系统支持库.文件操作.读取文件", 版本="1.0.0",
                      包id="支持库.后端.文件系统支持库.文件操作")
        self.assertTrue(self.日志.写入(事件))
        结果 = self.日志.查询(事件类型="调用成功")
        self.assertEqual(len(结果), 1)
        self.assertTrue(结果[0]["成功"])
        self.assertEqual(结果[0]["能力id"], "文件系统支持库.文件操作.读取文件")

    def test_结构化失败日志(self):
        事件 = 生成事件("调用失败", 成功=False, 错误码="外部不可访问",
                      错误说明="无法连接数据库", 包id="支持库.后端.文件系统支持库.文件操作")
        self.assertTrue(self.日志.写入(事件))
        结果 = self.日志.最近失败(1)
        self.assertEqual(结果[0]["错误码"], "外部不可访问")
        self.assertFalse(结果[0]["成功"])

    def test_敏感信息脱敏(self):
        事件 = 生成事件("调用失败", 成功=False, 错误码="内部错误",
                      错误说明="认证失败 sk-真实密钥123456")
        脱敏后 = 脱敏事件字典(事件.转字典())
        self.assertNotIn("sk-真实密钥123456", 脱敏后["错误说明"])
        self.assertIn("已脱敏", 脱敏后["错误说明"])
        # 大文本截断
        长文本 = "x" * 500
        self.assertLess(len(脱敏文本(长文本)), 200)

    def test_日志查询过滤(self):
        for 包id in ("包.甲", "包.乙"):
            self.日志.写入(生成事件("调用失败", 成功=False, 错误码="超时", 包id=包id))
        self.日志.写入(生成事件("调用成功", 包id="包.甲"))
        甲失败 = self.日志.查询(包id="包.甲", 成功=False)
        乙失败 = self.日志.查询(包id="包.乙", 成功=False)
        self.assertEqual(len(甲失败), 1)
        self.assertEqual(len(乙失败), 1)

    def test_错误码聚合(self):
        for _ in range(3):
            self.日志.写入(生成事件("调用失败", 成功=False, 错误码="超时", 包id="包.甲"))
        self.日志.写入(生成事件("调用失败", 成功=False, 错误码="协议错误", 包id="包.甲"))
        统计 = self.日志.聚合错误码()
        self.assertEqual(统计.get("超时"), 3)
        self.assertEqual(统计.get("协议错误"), 1)


class Test失败记录与诊断(unittest.TestCase):
    """场景6-7：状态流转/关联验证场景。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段诊断_"))
        self.失败库 = 失败记录库(self.临时目录)

    def test_失败记录状态流转(self):
        记录 = self.失败库.登记失败(
            追踪id="追踪1", 包id="支持库.后端.文件系统支持库.文件操作", 错误码="版本不兼容",
            错误说明="契约漂移", 能力id="文件系统支持库.文件操作.读取文件", 版本="1.0.0",
        )
        self.assertEqual(记录.状态, 状态_待诊断)
        成功, _ = self.失败库.流转状态(记录.记录id, "已定位")
        self.assertTrue(成功)
        成功, 原因 = self.失败库.流转状态(记录.记录id, 状态_已忽略, 忽略原因="", 忽略有效期="")
        self.assertFalse(成功)  # 已忽略必须填原因
        self.assertIn("忽略原因", 原因)
        成功, _ = self.失败库.流转状态(记录.记录id, 状态_已忽略, 忽略原因="临时噪声", 忽略有效期="2026-08-07")
        self.assertTrue(成功)
        self.assertEqual(记录.状态, 状态_已忽略)

    def test_失败关联验证场景(self):
        场景 = 关联验证场景("版本不兼容")
        self.assertEqual(场景, "契约兼容判断")
        记录 = self.失败库.登记失败(
            追踪id="追踪2", 包id="包.甲", 错误码="外部未安装", 错误说明="驱动缺失",
        )
        诊断 = 诊断失败(记录)
        self.assertIn("失败位于", 诊断.结论)
        self.assertIn("推荐执行验证场景", 诊断.结论)
        self.assertIn("提供者不可用失败", 诊断.推荐验证场景)
        self.assertEqual(归类失败("配置类型错误"), "配置问题")


class Test版本并存(unittest.TestCase):
    """场景8-10：多版本并存/旧版本锁定/不影响旧项目。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段版本_"))
        self.注册表 = 版本注册表(self.临时目录)

    def test_多版本并存(self):
        成功1, _ = self.注册表.注册版本("模块库.文件管理", "1.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "1.0.0"})
        成功2, _ = self.注册表.注册版本("模块库.文件管理", "1.1.0", 声明字典={"包id": "模块库.文件管理", "版本": "1.1.0"})
        成功3, _ = self.注册表.注册版本("模块库.文件管理", "2.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "2.0.0"})
        self.assertTrue(成功1 and 成功2 and 成功3)
        self.assertEqual(len(self.注册表.查询版本(包id="模块库.文件管理")), 3)
        # 版本包不可覆盖
        覆盖, 原因 = self.注册表.注册版本("模块库.文件管理", "1.0.0", 声明字典={})
        self.assertFalse(覆盖)
        self.assertIn("不可覆盖", 原因)

    def test_旧版本依赖锁定(self):
        self.注册表.注册版本("模块库.文件管理", "1.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "1.0.0"})
        self.注册表.标记引用("模块库.文件管理", "1.0.0", "旧项目甲")
        可删, 原因 = self.注册表.确认可删除("模块库.文件管理", "1.0.0")
        self.assertFalse(可删)
        self.assertIn("仍被项目引用", 原因)

    def test_新版本不影响旧项目(self):
        self.注册表.注册版本("模块库.文件管理", "1.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "1.0.0"})
        self.注册表.标记引用("模块库.文件管理", "1.0.0", "旧项目甲")
        成功, _ = self.注册表.注册版本("模块库.文件管理", "2.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "2.0.0"})
        self.assertTrue(成功)  # 新版本发布不影响旧项目
        旧包 = self.注册表.获取版本("模块库.文件管理", "1.0.0")
        self.assertIsNotNone(旧包)
        self.assertIn("旧项目甲", 旧包.引用项目)


class Test契约兼容(unittest.TestCase):
    """场景11-14：兼容判断/不兼容拒绝/适配器成功/不适用拒绝。"""

    旧契约 = {
        "能力": [
            {"能力id": "文件管理.复制文件", "参数": [{"名称": "源路径", "必填": True}, {"名称": "目标路径", "必填": True}], "返回": "结果"},
            {"能力id": "文件管理.读取文件", "参数": [{"名称": "文件路径", "必填": True}], "返回": "结果"},
        ],
        "错误码": ["参数不合法", "文件不存在"],
    }

    def test_契约兼容判断(self):
        新契约 = {
            "能力": [
                {"能力id": "文件管理.复制文件", "参数": [{"名称": "源路径", "必填": True}, {"名称": "目标路径", "必填": True}, {"名称": "覆盖", "必填": False}], "返回": "结果"},
                {"能力id": "文件管理.读取文件", "参数": [{"名称": "文件路径", "必填": True}], "返回": "结果"},
            ],
            "错误码": ["参数不合法", "文件不存在", "文件不可写"],
        }
        结果 = 检查契约兼容(self.旧契约, 新契约)
        self.assertEqual(结果.结论, "兼容")
        self.assertFalse(结果.是否必须升主版本)

    def test_契约不兼容拒绝(self):
        新契约 = {
            "能力": [
                {"能力id": "文件管理.复制文件", "参数": [{"名称": "源路径", "必填": True}], "返回": "结果"},  # 删除目标路径
            ],
            "错误码": ["参数不合法"],
        }
        结果 = 检查契约兼容(self.旧契约, 新契约)
        self.assertIn(结果.结论, ("不兼容", "需要适配器", "无法升级"))
        self.assertTrue(结果.是否必须升主版本)

    def test_兼容适配器成功(self):
        适配器 = 兼容适配器(适配器声明(
            适配器id="适配器.复制文件v1v2", 来源契约版本="1.0.0", 目标契约版本="2.0.0",
        ))
        适配器.注册参数转换("文件管理.复制文件", lambda 参数: {
            **参数, "覆盖": 参数.get("覆盖", False),
        })
        适配器.注册错误码转换("文件不存在", "文件不存在或不可读")
        转换后 = 适配器.转换参数("文件管理.复制文件", {"源路径": "a", "目标路径": "b"})
        self.assertEqual(转换后["覆盖"], False)
        self.assertEqual(适配器.转换错误码("文件不存在"), "文件不存在或不可读")

    def test_适配器不适用拒绝(self):
        适配器 = 兼容适配器(适配器声明(
            适配器id="适配器.只适用v1v2", 来源契约版本="1.0.0", 目标契约版本="2.0.0",
        ))
        self.assertTrue(适配器.适用于("1.0.0", "2.0.0"))
        self.assertFalse(适配器.适用于("1.0.0", "3.0.0"))


class Test热切换(unittest.TestCase):
    """场景15-19：影子启动失败/灰度自动回滚/无状态/有状态/重复回滚幂等。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段切换_"))
        self.注册表 = 版本注册表(self.临时目录)
        self.注册表.注册版本("文件管理", "1.0.0", 声明字典={"包id": "文件管理", "版本": "1.0.0"})
        self.注册表.注册版本("文件管理", "1.1.0", 声明字典={"包id": "文件管理", "版本": "1.1.0"})
        self.切换 = 热切换管理器(self.注册表)
        self.切换.设置激活("文件管理.读取文件", "1.0.0", 回退版本="1.0.0")

    def test_影子启动失败(self):
        结果 = self.切换.热切换(
            能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0",
            影子启动结果=False,
        )
        self.assertFalse(结果.成功)
        self.assertTrue(结果.自动回滚)
        self.assertEqual(self.切换.当前激活版本("文件管理.读取文件"), "1.0.0")
        self.assertEqual(len(self.切换.回滚记录表), 1)

    def test_灰度失败自动回滚(self):
        self.切换.热切换(能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0")
        self.assertEqual(self.切换.当前激活版本("文件管理.读取文件"), "1.1.0")
        # 灰度观测触发阈值 → 自动回滚
        问题 = self.切换.记录灰度观测("文件管理.读取文件", 成功=False)
        for _ in range(10):
            self.切换.记录灰度观测("文件管理.读取文件", 成功=False)
        self.assertTrue(问题 or self.切换.记录灰度观测("文件管理.读取文件", 成功=False))
        # 直接验证超阈值路径
        结果 = self.切换.热切换(
            能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0",
            健康检查结果=False,
        )
        self.assertTrue(结果.自动回滚)
        self.assertEqual(self.切换.当前激活版本("文件管理.读取文件"), "1.0.0")

    def test_无状态热切换(self):
        结果 = self.切换.热切换(能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0")
        self.assertTrue(结果.成功)
        self.assertEqual(self.切换.当前激活版本("文件管理.读取文件"), "1.1.0")

    def test_有状态排空切换(self):
        self.assertTrue(判断有无状态("数据库.执行查询"))
        self.assertFalse(判断有无状态("数据操作支持库.文本处理.分割文本"))
        结果 = 执行切换("数据库.执行查询", 状态可迁移=True)
        self.assertTrue(结果.成功)
        self.assertIn("等待旧任务完成", 结果.步骤列表)
        # 状态不可迁移 → 禁止进程内热替换
        结果2 = 执行切换("数据库.执行查询", 状态可迁移=False)
        self.assertFalse(结果2.成功)
        self.assertTrue(any("并行运行" in 步骤 for 步骤 in 结果2.步骤列表))

    def test_重复回滚幂等(self):
        结果1 = self.切换.热切换(
            能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0",
            健康检查结果=False,
        )
        结果2 = self.切换.热切换(
            能力id="文件管理.读取文件", 新版本="1.1.0", 回退版本="1.0.0",
            健康检查结果=False,
        )
        self.assertTrue(结果1.自动回滚 and 结果2.自动回滚)
        self.assertEqual(self.切换.当前激活版本("文件管理.读取文件"), "1.0.0")  # 回滚后稳定


class Test版本清理(unittest.TestCase):
    """场景20-21：引用扫描/安全卸载。"""

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段清理_"))
        self.注册表 = 版本注册表(self.临时目录)
        self.注册表.注册版本("模块库.文件管理", "1.0.0", 声明字典={"包id": "模块库.文件管理", "版本": "1.0.0"})

    def test_旧版本引用扫描(self):
        self.注册表.标记引用("模块库.文件管理", "1.0.0", "项目甲")
        引用 = self.注册表.引用扫描("模块库.文件管理", "1.0.0")
        self.assertEqual(引用, ["项目甲"])
        可删, _ = self.注册表.确认可删除("模块库.文件管理", "1.0.0", 运行实例数=1)
        self.assertFalse(可删)

    def test_旧版本安全卸载(self):
        条件 = 卸载条件(无项目依赖=True, 无运行中任务=True, 无连接和句柄=True,
                     无待迁移状态=True, 无待处理失败记录=True, 无回滚窗口=True,
                     已超过弃用期限=True)
        结果 = 执行卸载(条件)
        self.assertTrue(结果.成功)
        self.assertIn("激活映射", 结果.撤销清单)
        # 有未满足条件 → 拒绝
        条件2 = 卸载条件(无运行中任务=False)
        结果2 = 执行卸载(条件2)
        self.assertFalse(结果2.成功)
        self.assertIn("仍有运行中任务", 结果2.未满足条件)


class Test提供者隔离(unittest.TestCase):
    """场景22：提供者进程崩溃恢复。"""

    def test_进程崩溃恢复(self):
        from 运行核心.加载器.提供者隔离.独立进程 import 进程管理器
        管理器 = 进程管理器()
        进程 = 管理器.创建进程("原生库桥接", 版本="1.0.0")
        启动结果, 消息 = 管理器.启动并检查(进程)
        self.assertTrue(启动结果, 消息)
        # 调用成功
        结果 = 进程.调用(能力id="进程.最小操作", 参数={"名称": "查询"})
        self.assertTrue(结果.成功)
        # 模拟崩溃：终止真实子进程
        进程.进程.terminate()
        进程.进程.wait(timeout=3)
        崩溃 = 进程.崩溃检测()
        self.assertFalse(崩溃)  # 已自动重启
        self.assertGreaterEqual(进程.重启次数, 1)
        self.assertEqual(进程.状态, "运行中")
        # 重启后恢复调用
        结果 = 进程.调用(能力id="进程.最小操作", 参数={"名称": "恢复"})
        self.assertTrue(结果.成功)
        # 优雅停止 + 强制终止兜底
        进程.优雅停止()
        self.assertEqual(进程.状态, "已停止")
        进程.启动()
        进程.强制终止()
        self.assertEqual(进程.状态, "已停止")
        # 停止后调用失败
        结果 = 进程.调用(能力id="进程.最小操作")
        self.assertFalse(结果.成功)
        进程.关闭并清理()


class TestAgent查询(unittest.TestCase):
    """场景23：MCP 查询失败信息。"""

    def test_MCP查询失败信息(self):
        from 开发工具.统一能力入口.Agent查询.查询入口 import 查询入口
        from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库

        临时目录 = Path(tempfile.mkdtemp(prefix="第五阶段查询_"))
        失败库 = 失败记录库(临时目录)
        失败库.登记失败(追踪id="追踪9", 包id="包.甲", 错误码="超时", 错误说明="连接超时")
        入口 = 查询入口(失败库=失败库)
        # 查看失败记录
        结果 = 入口.查询失败记录(包id="包.甲")
        self.assertTrue(结果.成功)
        self.assertEqual(len(结果.数据), 1)
        # 查看诊断详情
        记录id = 失败库.最近失败(1)[0].记录id
        诊断 = 入口.查看诊断详情(记录id)
        self.assertTrue(诊断.成功)
        self.assertIn("失败位于", 诊断.数据)
        # 查看关联验证场景
        场景 = 入口.查看关联验证场景("外部未安装")
        self.assertEqual(场景.数据, "提供者不可用失败")
        # 标准流程
        步骤 = 入口.标准流程("读取文件")
        self.assertEqual(len(步骤), 6)
        self.assertIn("① 搜索能力", 步骤[0])


if __name__ == "__main__":
    unittest.main()
