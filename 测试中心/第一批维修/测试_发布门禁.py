"""第一批发布门禁维修：坏制品必须 fail-closed，正式矩阵必须逐能力对账。"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import sys
import shutil
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
门禁路径 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁.py"
规格 = importlib.util.spec_from_file_location("第一批发布门禁", 门禁路径)
assert 规格 and 规格.loader
门禁 = importlib.util.module_from_spec(规格)
sys.modules[规格.name] = 门禁
规格.loader.exec_module(门禁)


def 写JSON(路径: Path, 数据: object) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")


def 建制品(根: Path, *, 能力id: str = "模块1.求和") -> Path:
    制品 = 根 / "候选制品"
    (制品 / "运行入口").mkdir(parents=True)
    (制品 / "运行入口" / "启动.py").write_text("print('ready')\n", encoding="utf-8")
    (制品 / "正式文件.txt").write_text("正式字节", encoding="utf-8")
    写JSON(制品 / "制品来源.json", {
        "提交": "a" * 40, "工作区字节指纹": "b" * 64,
    })
    写JSON(制品 / "编译清单.json", {
        "来源提交": "a" * 40, "来源工作区字节指纹": "b" * 64,
        "能力引用": [能力id],
    })
    写JSON(制品 / "制品完整性摘要.json", {
        "制品摘要": "c" * 64, "文件数": 2, "文件清单": [],
    })
    契约 = {
        "契约版本": "1.0.0",
        "能力契约": [{
            "能力id": 能力id, "版本": "1.0.0", "说明": "求和",
            "参数": [
                {"名称": "加数1", "类型": "整数型", "必填": True, "默认值": 1},
                {"名称": "加数2", "类型": "整数型", "必填": True, "默认值": 2},
            ],
            "返回": {"类型": "结果型", "值结构": {"和": "整数型"}},
            "错误码": ["参数不合法"],
            "调用示例": {"能力id": 能力id, "参数": {"加数1": 1, "加数2": 2}},
            "行为": {"副作用": "纯计算", "资源释放": "无资源残留"},
            "提供者": {"默认": "模块库.模块1", "版本": ">=1.0.0"},
        }],
    }
    写JSON(制品 / "模块库" / "模块1" / "能力契约" / "参数契约.json", 契约)
    写JSON(制品 / "模块库" / "模块1" / "包声明.json", {
        "包id": "模块库.模块1", "版本": "1.0.0", "类型": "模块库",
        "能力": [{"能力id": 能力id}],
    })
    from 开发工具.项目编译.项目编译器 import _制品文件摘要
    写JSON(制品 / "制品完整性摘要.json", _制品文件摘要(制品))
    return 制品


def 建通过矩阵(制品: Path, 能力id: str = "模块1.求和") -> dict:
    return {
        "制品路径": str(制品.resolve()),
        "场景总数": 1, "通过数": 1, "失败数": 0,
        "正向目标能力全集": [能力id], "实际成功目标能力全集": [能力id],
        "结果列表": [{
            "场景id": f"能力.{能力id}.成功", "步骤id": "目标求和", "步骤类型": "目标",
            "能力id": 能力id, "通过": True, "状态码": 200,
            "返回": {"成功": True, "值": {"和": 3}, "错误码": "", "错误说明": ""},
        }],
        "资源回收": {"已回收": True, "进程组残留": False},
        "资源残留数": 0, "清理失败数": 0,
        "制品摘要前": {"制品摘要": "c" * 64},
        "制品摘要后": {"制品摘要": "c" * 64},
    }


class 正式制品选择测试(unittest.TestCase):
    def test_显式候选是唯一目标且缺运行入口直接阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时) / "坏制品"
            制品.mkdir()
            演示 = Path(临时) / "20260822-demo"
            (演示 / "运行入口").mkdir(parents=True)
            (演示 / "运行入口" / "启动.py").write_text("pass", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "运行入口"):
                门禁.选择待验证制品(制品, lambda: 演示)

    def test_未显式指定时只接受正式激活制品(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            路径, 来源 = 门禁.选择待验证制品(None, lambda: 制品)
            self.assertEqual(路径, 制品.resolve())
            self.assertEqual(来源, "正式激活")


class 制品绑定与只读测试(unittest.TestCase):
    def test_来源绑定当前提交和统一工作区字节指纹(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            通过, 详情, 身份 = 门禁.校验制品来源绑定(
                制品, 当前指纹={"提交": "a" * 40, "工作区字节指纹": "b" * 64,
                              "工作区状态": "干净"})
            self.assertTrue(通过, 详情)
            self.assertEqual(身份["来源提交"], "a" * 40)
            self.assertEqual(身份["能力数"], 1)

    def test_源码脏且旧制品指纹不同必须阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            通过, 详情, _ = 门禁.校验制品来源绑定(
                制品, 当前指纹={"提交": "a" * 40, "工作区字节指纹": "d" * 64,
                              "工作区状态": "含未提交变更"})
            self.assertFalse(通过)
            self.assertIn("旧制品", 详情)

    def test_任何新增缓存或字节变化都被检出(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            前 = 门禁.读取制品字节快照(制品)
            (制品 / "__pycache__").mkdir()
            (制品 / "__pycache__" / "污染.pyc").write_bytes(b"cache")
            后 = 门禁.读取制品字节快照(制品)
            通过, 详情 = 门禁.核验制品字节未变(前, 后)
            self.assertFalse(通过)
            self.assertIn("__pycache__/污染.pyc", 详情)

    def test_验证缓存环境全部位于制品外受管临时目录(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            缓存根, 环境 = 门禁.构建验证缓存环境(制品)
            self.assertFalse(缓存根.resolve().is_relative_to(制品.resolve()))
            for 键 in ("TMPDIR", "TMP", "TEMP", "PYTHONPYCACHEPREFIX", "系统底座_工程缓存根"):
                self.assertTrue(Path(环境[键]).resolve().is_relative_to(缓存根.resolve()), 键)
            self.assertEqual(环境["PYTHONDONTWRITEBYTECODE"], "1")


class 契约与HTML矩阵测试(unittest.TestCase):
    def test_正式HTML矩阵逐能力对账真实成功值全集与资源收口(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            通过, 详情, 数量 = 门禁.校验契约与HTML矩阵(制品, 建通过矩阵(制品))
            self.assertTrue(通过, 详情)
            self.assertEqual(数量, 1)

    def test_坏矩阵只有AST式名称计数不得假绿(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            假矩阵 = {"制品路径": str(制品), "场景总数": 1, "通过数": 1, "失败数": 0,
                    "结果列表": [{"场景id": "模块1", "能力id": "模块1.求和", "通过": True}]}
            通过, 详情, _ = 门禁.校验契约与HTML矩阵(制品, 假矩阵)
            self.assertFalse(通过)
            self.assertRegex(详情, "目标能力|真实成功|资源回收|制品摘要")

    def test_矩阵制品路径不是同一制品必须阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            矩阵 = 建通过矩阵(制品)
            矩阵["制品路径"] = str(Path(临时) / "另一个制品")
            通过, 详情, _ = 门禁.校验契约与HTML矩阵(制品, 矩阵)
            self.assertFalse(通过)
            self.assertIn("同一制品", 详情)


class 第三方声明测试(unittest.TestCase):
    def test_第三方提供者缺真实依赖锁不得按无第三方放行(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            提供者 = 制品 / "支持库" / "适配层" / "漏锁提供者"
            写JSON(提供者 / "包声明.json", {
                "包id": "支持库.适配层.漏锁提供者", "版本": "1.0.0", "类型": "支持库",
                "能力": [{"能力id": "漏锁.调用"}],
            })
            通过, 详情 = 门禁.校验第三方访问声明(制品)
            self.assertFalse(通过)
            self.assertIn("依赖锁", 详情)

    def test_真实第三方依赖缺权限进程文件声明必须阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时))
            提供者 = 制品 / "支持库" / "适配层" / "坏提供者"
            写JSON(提供者 / "包声明.json", {
                "包id": "支持库.适配层.坏提供者", "版本": "1.0.0", "类型": "支持库",
                "能力": [{"能力id": "坏能力.读取"}],
            })
            写JSON(提供者 / "依赖锁.json", {"包": [{"名称": "thirdparty", "版本": "1.0"}]})
            写JSON(提供者 / "能力定义.json", {"包id": "支持库.适配层.坏提供者", "能力列表": [{
                "能力id": "坏能力.读取", "版本": "1.0.0", "中文名称": "读取", "说明": "读取",
                "参数": [{"名称": "文件路径", "类型": "文本型"}], "返回": "结果型",
                "错误码": ["参数不合法"], "行为": {"副作用": "只读", "资源释放": ""},
                "提供者": {"默认": "支持库.适配层.坏提供者", "版本": ">=1.0.0"},
            }]})
            (提供者 / "实现").mkdir(parents=True)
            (提供者 / "实现" / "实现.py").write_text(
                "import subprocess, urllib.request\nfrom pathlib import Path\ndef 读取(p): return Path(p).read_bytes()\n",
                encoding="utf-8")
            通过, 详情 = 门禁.校验第三方访问声明(制品)
            self.assertFalse(通过)
            self.assertIn("坏提供者", 详情)
            for 声明 in ("权限", "网络", "文件", "进程"):
                self.assertIn(声明, 详情)


class 生产门禁独立性测试(unittest.TestCase):
    def test_删除测试中心后生产门禁仍可导入并执行制品选择(self):
        for 文件 in (系统根 / "开发工具" / "发布门禁").glob("*.py"):
            文本 = 文件.read_text(encoding="utf-8")
            self.assertNotIn("测试中心", 文本, 文件.name)
            self.assertNotIn('系统根.rglob("*.py")', 文本, 文件.name)
        with tempfile.TemporaryDirectory() as 临时:
            隔离根 = Path(临时) / "隔离平台"
            (隔离根 / "平台控制面").mkdir(parents=True)
            (隔离根 / "开发工具").mkdir()
            shutil.copytree(系统根 / "开发工具" / "发布门禁", 隔离根 / "开发工具" / "发布门禁")
            隔离门禁路径 = 隔离根 / "开发工具" / "发布门禁" / "运行发布门禁.py"
            隔离规格 = importlib.util.spec_from_file_location("无测试中心发布门禁", 隔离门禁路径)
            assert 隔离规格 and 隔离规格.loader
            隔离门禁 = importlib.util.module_from_spec(隔离规格)
            sys.modules[隔离规格.name] = 隔离门禁
            隔离规格.loader.exec_module(隔离门禁)
            self.assertEqual(隔离门禁.系统根.resolve(), 隔离根.resolve())
            制品 = 建制品(Path(临时) / "制品夹具")
            路径, 来源 = 隔离门禁.选择待验证制品(制品)
            self.assertEqual(路径, 制品.resolve())
            self.assertEqual(来源, "明确待发布")


if __name__ == "__main__":
    unittest.main()
