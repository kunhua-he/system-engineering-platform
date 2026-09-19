"""项目适配层测试：初始化、声明、绑定、锁定、入口全链路。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表
from 后端核心.后端核心 import 后端核心
from 运行核心.加载器.生命周期管理.管理器 import 装配系统
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器
from 项目适配层.能力适配.能力适配 import 从项目声明构建映射
from 项目适配层.依赖锁定.依赖锁定 import 生成依赖锁定
from 项目适配层.模块绑定.模块绑定 import 校验绑定 as 校验模块
from 项目适配层.项目初始化.项目初始化 import 创建项目
from 项目适配层.项目声明.项目声明 import 加载项目声明, 写入项目声明
from 项目适配层.运行入口.项目入口 import 项目入口
from 项目适配层.支持库绑定.支持库绑定 import 校验绑定 as 校验支持库
from 公共契约.基础类型.逻辑类型 import 真, 假


class Test项目初始化(unittest.TestCase):
    def test_创建完整骨架(self):
        临时目录 = tempfile.mkdtemp(prefix="适配层测试_")
        项目根 = 创建项目(临时目录, "测试项目", "测试项目.初始化")
        self.assertTrue((项目根 / "项目声明.json").is_file())
        self.assertTrue((项目根 / "依赖声明.json").is_file())
        self.assertTrue((项目根 / "依赖锁定.json").is_file())
        for 子目录 in ("项目代码", "项目模块", "项目配置", "项目资源", "测试", "运行入口"):
            self.assertTrue((项目根 / 子目录).is_dir(), f"缺少 {子目录}")

    def test_重复创建幂等(self):
        临时目录 = tempfile.mkdtemp(prefix="适配层测试_")
        项目根1 = 创建项目(临时目录, "幂等项目")
        项目根2 = 创建项目(临时目录, "幂等项目")
        声明1 = (项目根1 / "项目声明.json").read_text(encoding="utf-8")
        声明2 = (项目根2 / "项目声明.json").read_text(encoding="utf-8")
        self.assertEqual(声明1, 声明2)


class Test项目声明(unittest.TestCase):
    def test_读写往返(self):
        临时目录 = tempfile.mkdtemp(prefix="适配层测试_")
        项目根 = 创建项目(临时目录, "声明项目", "测试项目.声明")
        声明 = 加载项目声明(项目根 / "项目声明.json")
        self.assertEqual(声明.项目名称, "声明项目")
        self.assertIn("项目适配", 声明.验证范围)
        声明.支持库绑定 = [{"包id": "支持库.后端.文件系统支持库.文件操作", "版本约束": ">=1.0.0"}]
        写入项目声明(声明, 项目根 / "项目声明.json")
        重读 = 加载项目声明(项目根 / "项目声明.json")
        self.assertEqual(重读.支持库绑定[0]["包id"], "支持库.后端.文件系统支持库.文件操作")

    def test_缺失必填字段拒绝(self):
        from 项目适配层.项目声明.项目声明 import 从字典构建
        with self.assertRaises(ValueError):
            从字典构建({"项目id": "x"})


class Test支持库绑定(unittest.TestCase):
    def test_有效绑定(self):
        结果 = 校验支持库("支持库.后端.文件系统支持库.文件操作", ">=1.0.0", 系统根 / "支持库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        声明 = json.loads(
            (系统根 / "支持库" / "后端" / "文件系统支持库" / "文件操作" / "包声明.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(结果.绑定版本, 声明["版本"])

    def test_不存在的支持库失败(self):
        结果 = 校验支持库("支持库.后端.不存在", "", 系统根 / "支持库")
        self.assertFalse(结果.成功)
        self.assertIn("不存在", 结果.问题列表[0])

    def test_版本不满足失败(self):
        结果 = 校验支持库("支持库.后端.文件系统支持库.文件操作", ">=3.0.0", 系统根 / "支持库")
        self.assertFalse(结果.成功)
        self.assertIn("版本不满足", 结果.问题列表[0])


class Test模块绑定(unittest.TestCase):
    def test_有效绑定(self):
        结果 = 校验模块("模块库.文件管理", ">=1.0.0", 系统根)
        self.assertTrue(结果.成功, str(结果.问题列表))

    def test_依赖支持库能力存在(self):
        结果 = 校验模块("模块库.文档读取", "", 系统根)
        self.assertTrue(结果.成功, str(结果.问题列表))

    def test_不存在的模块失败(self):
        结果 = 校验模块("模块库.不存在", "", 系统根)
        self.assertFalse(结果.成功)


class Test依赖锁定(unittest.TestCase):
    def setUp(self):
        self.适配示例目录 = 系统根 / "示例项目" / "适配层示例"

    def test_可重复生成(self):
        结果1 = 生成依赖锁定(self.适配示例目录, 系统根)
        结果2 = 生成依赖锁定(self.适配示例目录, 系统根)
        self.assertTrue(结果1.成功, str(结果1.问题列表))
        self.assertTrue(结果2.成功, str(结果2.问题列表))
        文本1 = (self.适配示例目录 / "依赖锁定.json").read_text(encoding="utf-8")
        文本2 = (self.适配示例目录 / "依赖锁定.json").read_text(encoding="utf-8")
        self.assertEqual(文本1, 文本2)

    def test_锁定包含绑定包(self):
        结果 = 生成依赖锁定(self.适配示例目录, 系统根)
        self.assertTrue(结果.成功)
        锁定 = json.loads((self.适配示例目录 / "依赖锁定.json").read_text(encoding="utf-8"))
        包id集合 = {条目["包id"] for 条目 in 锁定["包列表"]}
        self.assertIn("支持库.后端.文件系统支持库.文件操作", 包id集合)
        self.assertIn("支持库.后端.数据操作支持库.文本处理", 包id集合)
        self.assertIn("模块库.文件管理", 包id集合)

    def test_锁定含完整性摘要与依赖顺序(self):
        锁定 = json.loads((self.适配示例目录 / "依赖锁定.json").read_text(encoding="utf-8"))
        for 条目 in 锁定["包列表"]:
            self.assertIn("完整性摘要", 条目)
            self.assertIn("依赖顺序", 条目)
            self.assertIn("提供者", 条目)


class Test项目入口(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._原网关凭证 = os.environ.get("系统库网关凭证")
        os.environ["系统库网关凭证"] = "test"
        try:
            cls.后端 = 后端核心(系统根)
            启动结果 = cls.后端.启动()
            if not 启动结果.成功:
                raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
            cls.网关 = 本地网关服务器(
                网关核心实例=网关核心(cls.后端), 端口=0, 地址="127.0.0.1",
                配置={"请求超时秒": 1800, "要求凭证": 假, "禁止客户端身份": 假},
            )
            成功, 说明 = cls.网关.启动()
            if not 成功:
                cls.后端.强制关闭()
                raise RuntimeError(f"测试网关启动失败: {说明}")
        except Exception:
            if cls._原网关凭证 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = cls._原网关凭证
            raise

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()
        cls.后端.优雅关闭()
        if cls._原网关凭证 is None:
            os.environ.pop("系统库网关凭证", None)
        else:
            os.environ["系统库网关凭证"] = cls._原网关凭证

    def setUp(self):
        self.适配示例目录 = 系统根 / "示例项目" / "适配层示例"
        self.注册表 = 能力注册表()
        装配 = 装配系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.assertTrue(装配.成功, str(装配.问题列表))
        项目数据 = json.loads((self.适配示例目录 / "项目声明.json").read_text(encoding="utf-8"))
        from 运行核心.加载器.包发现.发现器 import 发现全部
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        映射 = 从项目声明构建映射(项目数据, 发现.声明列表)
        self.连接器 = HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口)
        # 2026-09-19（开工-20260919-193541-2a8e）：文件管理模块已按「断第二条腿」
        # 删除 `设置HTTP连接器` 第二入口，只经 `获取能力调用器()` 组合公开能力；
        # 项目入口自身持 HTTP 连接器（经真实 POST /网关/调用），故此处不再注入模块级连接器。
        self.入口 = 项目入口(self.注册表, 映射, self.连接器)

    def test_未装配连接器时拒绝进程内旁路(self):
        with self.assertRaises(ValueError):
            项目入口(self.注册表, self.入口.映射)

    def test_入口调用返回统一结果(self):
        # 通过真实 POST /网关/调用 执行能力，验证入口不再进程内旁路。
        调用结果 = self.入口.调用("分割文本", {"文本": "入口,测试", "分隔符": ","})
        self.assertTrue(调用结果.成功)
        self.assertTrue(hasattr(调用结果, "成功"))
        self.assertTrue(hasattr(调用结果, "值"))
        self.assertTrue(hasattr(调用结果, "错误"))
        self.assertEqual(调用结果.值, ["入口", "测试"])

    def test_未知能力返回失败结果(self):
        结果 = self.入口.调用("不存在的能力")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误.错误码, "能力不存在")

    def test_能力名映射解析(self):
        临时文件 = str(self.适配示例目录 / "项目资源" / "映射测试.txt")
        结果 = self.入口.调用("分割文本", {"文本": "a,b", "分隔符": ","})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
