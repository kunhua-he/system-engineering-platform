"""HTML 黑盒验证器第一批维修回归测试。"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
验证器路径 = 系统根 / "开发工具" / "HTML验证" / "验证器.py"
规格 = importlib.util.spec_from_file_location("HTML验证器", 验证器路径)
验证器 = importlib.util.module_from_spec(规格)
assert 规格 and 规格.loader
sys.modules[规格.name] = 验证器
规格.loader.exec_module(验证器)

from 公共契约.运行时.进程终止 import 进程组号
from 开发工具.HTML验证 import (
    常量, 制品事实, 场景加载, HTTP请求, 制品进程, 返回判定, 动态值,
    场景执行器, 验证证据, 单实例验证, 验证应用, 验证服务,
)
from 开发工具.HTML验证.单步场景 import 验证场景
from 开发工具.HTML验证.验证报告 import 验证报告


def 写JSON(路径: Path, 数据) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(json.dumps(数据, ensure_ascii=False), encoding="utf-8")


def 建制品(根: Path, 能力表: list[tuple[str, dict]], 场景表: list[dict] | None) -> Path:
    包 = 根 / "模块库" / "样例包"
    声明能力 = [{"能力id": 能力id} for 能力id, _ in 能力表]
    契约能力 = [{"能力id": 能力id, "参数": 参数, "返回": {"类型": "结果型"}}
            for 能力id, 参数 in 能力表]
    写JSON(包 / "包声明.json", {"包id": "模块库.样例包", "能力": 声明能力})
    写JSON(包 / "能力定义.json", {"能力列表": 声明能力})
    写JSON(包 / "能力契约" / "参数契约.json", {"契约版本": "1.0.0", "能力契约": 契约能力})
    if 场景表 is not None:
        新格式 = []
        for 场景 in 场景表:
            预期 = 场景.get("预期", {})
            断言 = {键: 预期[键] for 键 in ("错误码", "包含", "值类型", "关键值", "值") if 键 in 预期}
            if not 断言:
                断言 = {"值类型": "字典型"} if 预期.get("成功") else {"错误码": "参数不合法"}
            新格式.append({"场景": {
                "场景id": 场景.get("场景id", "场景"), "前置步骤": [], "清理步骤": [],
                "目标步骤": [{
                    "步骤id": 场景.get("场景id", "步骤"), "能力id": 场景.get("能力id", ""),
                    "参数": 场景.get("参数", {}),
                    "预期": {"成功": bool(预期.get("成功")),
                             "状态码": 200 if 预期.get("成功") else 400, "返回断言": 断言},
                }],
            }})
        写JSON(包 / "验证场景引用.json", {
            "契约版本": "验证场景/v1", "验证场景引用": 新格式,
        })
    return 根


def 成功场景(能力id="样例.相加", 场景id="相加成功", 参数=None) -> dict:
    return {
        "场景id": 场景id,
        "能力id": 能力id,
        "方法": "POST",
        "路径": "/网关/调用",
        "参数": 参数 or {"加数1": 1, "加数2": 2},
        "预期": {"成功": True, "值类型": "字典型", "关键值": {"和": 3}},
    }


def 统一成功返回(值=None) -> dict:
    return {
        "成功": True,
        "值": {"和": 3} if 值 is None else 值,
        "错误码": "",
        "错误说明": "",
        "可重试": False,
        "请求id": "请求-1",
        "耗时毫秒": 1.2,
    }


def 绑定场景(场景, 制品: Path):
    场景.制品摘要 = 制品事实._制品全文件摘要(制品)["制品摘要"]
    return 场景


class Test场景事实源与阻断(unittest.TestCase):
    def test_记忆支持库场景引用为v1并覆盖全部公开能力(self):
        包目录 = 系统根 / "支持库" / "后端" / "记忆支持库"
        场景表 = 场景加载._解析场景引用(包目录)
        能力定义 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
        公开能力 = {项["能力id"] for 项 in 能力定义["能力列表"]}
        成功目标能力 = {
            步骤["能力id"]
            for 场景, _ in 场景表
            for 步骤 in 场景["目标步骤"]
            if 步骤["预期"]["成功"]
        }
        self.assertEqual(成功目标能力, 公开能力)
        for 场景, _ in 场景表:
            self.assertEqual(set(场景), {"场景id", "前置步骤", "目标步骤", "清理步骤"})

    def test_聚合父包声明不重复占用子包能力owner(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时), [("样例.相加", {})], [成功场景()])
            写JSON(
                制品 / "模块库" / "聚合父包" / "包声明.json",
                {"包id": "模块库.聚合父包", "能力": [{"能力id": "样例.相加"}]},
            )
            写JSON(
                制品 / "模块库" / "聚合父包" / "子包" / "包声明.json",
                {"包id": "模块库.聚合父包.子包", "能力": []},
            )
            场景 = 场景加载._加载场景(制品, None)
            self.assertEqual([项.能力id for 项 in 场景], ["样例.相加"])

    def test_平台客户端嵌套制品仍使用同一公开能力扫描链(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            嵌套根 = 制品 / "平台客户端"
            建制品(嵌套根, [("样例.相加", {"加数1": {"必填": True}})], [成功场景()])
            场景 = 场景加载._加载场景(制品, None)
            self.assertEqual([项.能力id for 项 in 场景], ["样例.相加"])
            self.assertEqual(
                场景[0].制品摘要,
                制品事实._制品全文件摘要(制品)["制品摘要"],
            )

    def test_包级引用提供真实成功参数且不从契约猜输入(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时), [("样例.相加", {"加数1": {"必填": True}})], [成功场景()])
            场景 = 场景加载._加载场景(制品, None)
            self.assertEqual(len(场景), 1)
            self.assertEqual(场景[0].参数, {"加数1": 1, "加数2": 2})
            self.assertTrue(场景[0].预期成功)
            self.assertEqual(场景[0].预期关键值, {"和": 3})
            self.assertEqual(场景[0].制品摘要, 制品事实._制品全文件摘要(制品)["制品摘要"])

    def test_每个公开能力必须有真实成功场景(self):
        with tempfile.TemporaryDirectory() as 临时:
            负向 = {
                "场景id": "相加缺参", "能力id": "样例.相加", "参数": {},
                "预期": {"成功": False, "错误码": "参数不合法"},
            }
            制品 = 建制品(Path(临时), [("样例.相加", {})], [负向])
            with self.assertRaisesRegex(ValueError, "真实成功场景|正向目标步骤能力全集"):
                场景加载._加载场景(制品, None)

    def test_零场景空文件和全无效均阻断(self):
        for 内容 in ({"验证场景引用": []}, {"验证场景引用": [None, "坏场景"]}):
            with self.subTest(内容=内容), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], None)
                写JSON(制品 / "模块库" / "样例包" / "验证场景引用.json", 内容)
                with self.assertRaises(ValueError):
                    场景加载._加载场景(制品, None)

    def test_坏JSON坏契约缺能力id与重复均阻断(self):
        情况表 = ["坏JSON", "坏契约", "缺能力id", "重复能力id"]
        for 情况 in 情况表:
            with self.subTest(情况=情况), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], [成功场景()])
                契约 = 制品 / "模块库" / "样例包" / "能力契约" / "参数契约.json"
                if 情况 == "坏JSON":
                    (制品 / "模块库" / "样例包" / "验证场景引用.json").write_text("{坏", encoding="utf-8")
                elif 情况 == "坏契约":
                    契约.write_text("{坏", encoding="utf-8")
                elif 情况 == "缺能力id":
                    写JSON(契约, {"能力契约": [{"参数": []}]})
                else:
                    写JSON(契约, {"能力契约": [{"能力id": "样例.相加"}, {"能力id": "样例.相加"}]})
                with self.assertRaises(ValueError):
                    场景加载._加载场景(制品, None)

    def test_重复场景和契约场景差集均阻断(self):
        for 场景表 in (
            [成功场景(), 成功场景(场景id="相加成功")],
            [成功场景(), 成功场景("样例.多余", "多余成功")],
        ):
            with self.subTest(), tempfile.TemporaryDirectory() as 临时:
                制品 = 建制品(Path(临时), [("样例.相加", {})], 场景表)
                with self.assertRaises(ValueError):
                    场景加载._加载场景(制品, None)

    def test_外部场景束必须绑定当前制品摘要且来源为包级引用(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时) / "制品", [("样例.相加", {})], [成功场景()])
            场景束 = Path(临时) / "场景.json"
            写JSON(场景束, {
                "来源": "包级验证场景引用", "制品摘要": "错误摘要", "验证场景": [成功场景()],
            })
            with self.assertRaisesRegex(ValueError, "制品摘要"):
                场景加载._加载场景(制品, 场景束)


def 新步骤(步骤id: str, 能力id: str, 参数=None, 成功=True, 状态码=200, 返回断言=None) -> dict:
    return {
        "步骤id": 步骤id,
        "能力id": 能力id,
        "参数": {} if 参数 is None else 参数,
        "预期": {
            "成功": 成功,
            "状态码": 状态码,
            "返回断言": 返回断言 or ({"值类型": "字典型"} if 成功 else {"错误码": "预期失败"}),
        },
    }


def 新场景(场景id: str, 目标步骤: list[dict], 前置步骤=None, 清理步骤=None) -> dict:
    return {
        "场景id": 场景id,
        "前置步骤": 前置步骤 or [],
        "目标步骤": 目标步骤,
        "清理步骤": 清理步骤 or [],
    }


def 建新制品(根: Path, 能力ids: list[str], 场景表: list[dict], 引用文件=False) -> Path:
    制品 = 建制品(根, [(能力id, {}) for 能力id in 能力ids], None)
    包 = 制品 / "模块库" / "样例包"
    if 引用文件:
        写JSON(包 / "验证场景" / "场景.json", {
            "契约版本": "验证场景/v1", "验证场景": 场景表,
        })
        引用 = [{"场景文件": "验证场景/场景.json"}]
    else:
        引用 = [{"场景": 场景} for 场景 in 场景表]
    写JSON(包 / "验证场景引用.json", {
        "契约版本": "验证场景/v1", "验证场景引用": 引用,
    })
    return 制品


class TestP020多步骤场景契约(unittest.TestCase):
    def _执行(self, 制品: Path, 返回函数):
        场景束 = 场景加载._加载场景(制品, None)
        with mock.patch.object(场景执行器, "_发送请求", side_effect=返回函数):
            return 场景执行器._执行场景束(制品, 场景束, "http://127.0.0.1:45080", 超时秒=1)

    def test_独立场景按并发执行且场景内步骤保持顺序(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.包1", "样例.包2"], [
                新场景("场景1", [新步骤("目标1", "样例.包1")]),
                新场景("场景2", [新步骤("目标2", "样例.包2")]),
            ])
            活跃 = 0
            峰值 = 0
            锁 = threading.Lock()

            def 返回(_地址, _步骤, _超时):
                nonlocal 活跃, 峰值
                with 锁:
                    活跃 += 1
                    峰值 = max(峰值, 活跃)
                time.sleep(0.05)
                with 锁:
                    活跃 -= 1
                return 200, 统一成功返回(), 1

            场景束 = 场景加载._加载场景(制品, None)
            with mock.patch.object(场景执行器, "_发送请求", side_effect=返回):
                报告 = 场景执行器._执行场景束(
                    制品, 场景束, "http://127.0.0.1:45080", 超时秒=1, 并发=2)
            self.assertGreaterEqual(峰值, 2)
            self.assertGreaterEqual(报告.并发峰值, 2)
            self.assertEqual(报告.失败数, 0)

    def test_正式嵌套制品的制品根指向平台客户端代码根(self):
        with tempfile.TemporaryDirectory() as 临时:
            外层 = Path(临时)
            代码根 = 外层 / "平台客户端"
            目标 = 代码根 / "支持库" / "夹具.py"
            目标.parent.mkdir(parents=True)
            (代码根 / "__init__.py").write_text("", encoding="utf-8")
            目标.write_text("通过 = True\n", encoding="utf-8")
            展开 = 动态值._展开动态值(
                {"$动态": "制品根", "相对路径": "支持库/夹具.py"},
                制品目录=外层, 包目录=代码根, 临时目录=外层 / "临时", 步骤返回表={},
            )
            self.assertEqual(Path(展开).resolve(), 目标.resolve())

    def test_静态成功与引用场景文件消费同一契约(self):
        for 引用文件 in (False, True):
            with self.subTest(引用文件=引用文件), tempfile.TemporaryDirectory() as 临时:
                制品 = 建新制品(Path(临时), ["样例.相加"], [
                    新场景("静态", [新步骤("相加", "样例.相加", {"加数1": 1, "加数2": 2}, 返回断言={"关键值": {"和": 3}})])
                ], 引用文件=引用文件)
                场景束 = 场景加载._加载场景(制品, None)
                self.assertEqual(场景束.目标能力全集, {"样例.相加"})
                self.assertEqual(场景束.步骤总数, 1)

    def test_正式验证入口消费同一场景束执行器(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.相加"], [
                新场景("静态", [新步骤("相加", "样例.相加", 返回断言={"关键值": {"和": 3}})])
            ])
            场景束 = 场景加载._加载场景(制品, None)
            def 返回(_地址, 请求场景, _超时):
                if 请求场景.能力id == "制品.健康":
                    return 200, {}, 1
                return 200, 统一成功返回({"和": 3}), 1
            with mock.patch.object(单实例验证, "_发送请求", side_effect=返回), \
                 mock.patch.object(场景执行器, "_发送请求", side_effect=返回):
                报告, _, 进程 = 单实例验证.验证全部(
                    制品, 场景束, 直连地址="http://127.0.0.1:45080")
            self.assertIsNone(进程)
            self.assertEqual(报告.失败数, 0)
            self.assertEqual(报告.实际成功目标能力全集, ["样例.相加"])

    def test_多步骤句柄和任意JSON路径传递(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.创建", "样例.读取"], [
                新场景("句柄链", [新步骤("读取", "样例.读取", {
                    "句柄": {"$动态": "步骤返回", "步骤id": "创建", "JSON路径": "$.值.资源.句柄"},
                    "种子": {"$动态": "步骤返回", "步骤id": "创建", "JSON路径": "$.参数.种子"},
                }, 返回断言={"关键值": {"内容": "已读取"}})], 前置步骤=[
                    新步骤("创建", "样例.创建", {"种子": "示例种子"}, 返回断言={"关键值": {"资源.句柄": "句柄-1"}}),
                ], 清理步骤=[新步骤("释放", "样例.创建", {
                    "句柄": {"$动态": "步骤返回", "步骤id": "创建", "JSON路径": "$.值.资源.句柄"},
                })]),
                新场景("创建覆盖", [新步骤("创建能力目标", "样例.创建")]),
            ])
            收到 = []
            def 返回(地址, 步骤, 超时):
                收到.append((步骤.步骤id, 步骤.参数))
                值 = ({"资源": {"句柄": "句柄-1"}} if 步骤.步骤id == "创建"
                     else {"内容": "已读取"} if 步骤.步骤id == "读取" else {"已释放": True})
                return 200, 统一成功返回(值), 1
            报告 = self._执行(制品, 返回)
            self.assertEqual(dict(收到)["读取"]["句柄"], "句柄-1")
            self.assertEqual(dict(收到)["读取"]["种子"], "示例种子")
            self.assertEqual(dict(收到)["释放"]["句柄"], "句柄-1")
            self.assertEqual(报告.失败数, 0)

    def test_文件夹具复制与动态路径均限制在允许根(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.读文件", "样例.删除"], [
                新场景("文件", [新步骤("读取", "样例.读文件", {
                    "输入": {"$动态": "夹具文件复制", "来源": "夹具/输入.txt", "目标": "工作/输入.txt"},
                    "夹具": {"$动态": "制品根", "相对路径": "模块库/样例包/夹具/输入.txt"},
                    "目录": {"$动态": "受管临时目录", "相对路径": "工作"},
                    "输出": {"$动态": "受管临时路径", "相对路径": "工作/输出.txt"},
                }, 返回断言={"关键值": {"内容": "夹具内容"}})], 清理步骤=[
                    新步骤("删除", "样例.删除", {"路径": {"$动态": "受管临时目录", "相对路径": "工作/输入.txt"}}),
                ]),
                新场景("删除覆盖", [新步骤("删除能力目标", "样例.删除", {
                    "路径": {"$动态": "夹具文件复制", "来源": "夹具/输入.txt", "目标": "删除/输入.txt"},
                })]),
            ])
            夹具 = 制品 / "模块库" / "样例包" / "夹具" / "输入.txt"
            夹具.parent.mkdir(parents=True)
            夹具.write_text("夹具内容", encoding="utf-8")
            def 返回(地址, 步骤, 超时):
                if 步骤.步骤id == "读取":
                    self.assertEqual(Path(步骤.参数["输入"]).read_text(encoding="utf-8"), "夹具内容")
                    self.assertEqual(Path(步骤.参数["夹具"]).read_text(encoding="utf-8"), "夹具内容")
                    self.assertTrue(Path(步骤.参数["目录"]).is_dir())
                    self.assertTrue(Path(步骤.参数["输出"]).parent.is_dir())
                    self.assertFalse(Path(步骤.参数["输出"]).exists())
                    return 200, 统一成功返回({"内容": "夹具内容"}), 1
                if "路径" in 步骤.参数:
                    Path(步骤.参数["路径"]).unlink()
                return 200, 统一成功返回({"已删除": True}), 1
            报告 = self._执行(制品, 返回)
            self.assertEqual(报告.资源残留数, 0)
            self.assertEqual(报告.制品摘要前["制品摘要"], 报告.制品摘要后["制品摘要"])

    def test_目标步骤失败仍执行finally清理(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.目标", "样例.清理"], [
                新场景("失败清理", [新步骤("目标", "样例.目标")], 清理步骤=[新步骤("清理", "样例.清理")]),
                新场景("清理覆盖", [新步骤("清理能力目标", "样例.清理")]),
            ])
            已清理 = []
            def 返回(地址, 步骤, 超时):
                if 步骤.步骤id == "目标":
                    return 500, {**统一成功返回(), "成功": False, "值": None, "错误码": "失败", "错误说明": "目标失败"}, 1
                已清理.append(True)
                return 200, 统一成功返回({"已清理": True}), 1
            报告 = self._执行(制品, 返回)
            self.assertTrue(已清理)
            self.assertGreater(报告.失败数, 0)

    def test_清理失败单独计数并阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.目标", "样例.清理"], [
                新场景("清理失败", [新步骤("目标", "样例.目标")], 清理步骤=[新步骤("清理", "样例.清理")]),
                新场景("清理覆盖", [新步骤("清理能力目标", "样例.清理")]),
            ])
            def 返回(地址, 步骤, 超时):
                if 步骤.步骤id == "清理":
                    return 500, {**统一成功返回(), "成功": False, "值": None, "错误码": "清理失败", "错误说明": "未释放"}, 1
                return 200, 统一成功返回({"完成": True}), 1
            报告 = self._执行(制品, 返回)
            self.assertEqual(报告.清理失败数, 1)
            self.assertGreater(报告.失败数, 0)

    def test_引用和动态路径逃逸均阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.目标"], [新场景("正常", [新步骤("目标", "样例.目标")])])
            包 = 制品 / "模块库" / "样例包"
            写JSON(包 / "验证场景引用.json", {
                "契约版本": "验证场景/v1", "验证场景引用": [{"场景文件": "../逃逸.json"}],
            })
            with self.assertRaisesRegex(ValueError, "越出包目录"):
                场景加载._加载场景(制品, None)
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.目标"], [
                新场景("逃逸", [新步骤("目标", "样例.目标", {
                    "路径": {"$动态": "受管临时目录", "相对路径": "../逃逸"},
                })])
            ])
            报告 = self._执行(制品, lambda *参数: self.fail("动态路径非法时不得发请求"))
            self.assertGreater(报告.失败数, 0)

    def test_前置和清理步骤不能冒充目标覆盖(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.包1", "样例.包2"], [
                新场景("伪覆盖", [新步骤("调用样例包1", "样例.包1")], 前置步骤=[新步骤("样例包2前置", "样例.包2")],
                    清理步骤=[新步骤("样例包2清理", "样例.包2")]),
            ])
            with self.assertRaisesRegex(ValueError, "正向目标步骤能力全集"):
                场景加载._加载场景(制品, None)

    def test_每能力缺正向目标步骤阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.包1"], [
                新场景("只有负向", [新步骤("样例包1失败", "样例.包1", 成功=False, 状态码=400,
                    返回断言={"错误码": "预期失败"})]),
            ])
            with self.assertRaisesRegex(ValueError, "正向目标步骤能力全集"):
                场景加载._加载场景(制品, None)

    def test_动态引用缺失和旧格式均阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建新制品(Path(临时), ["样例.目标"], [
                新场景("缺引用", [新步骤("目标", "样例.目标", {
                    "句柄": {"$动态": "步骤返回", "步骤id": "不存在", "JSON路径": "$.值"},
                })]),
            ])
            with self.assertRaisesRegex(ValueError, "动态引用缺失"):
                场景加载._加载场景(制品, None)
        with tempfile.TemporaryDirectory() as 临时:
            制品 = 建制品(Path(临时), [("样例.相加", {})], None)
            写JSON(制品 / "模块库" / "样例包" / "验证场景引用.json", {
                "验证场景引用": [成功场景()],
            })
            with self.assertRaisesRegex(ValueError, "旧格式|契约版本"):
                场景加载._加载场景(制品, None)


class Test返回契约(unittest.TestCase):
    def setUp(self):
        self.场景 = 验证场景.从字典(成功场景())

    def test_成功结果必须具备统一字段与正确类型(self):
        for 返回 in (
            {"成功": True, "值": {"和": 3}},
            {**统一成功返回(), "成功": 1},
            {**统一成功返回(), "请求id": ""},
            {**统一成功返回(), "耗时毫秒": "1"},
        ):
            with self.subTest(返回=返回):
                通过, 原因, _ = 返回判定._判定(self.场景, 200, 返回)
                self.assertFalse(通过)
                self.assertTrue(原因)

    def test_成功值不可为空且成功错误字段互斥(self):
        for 返回 in (
            统一成功返回(None) | {"值": None},
            统一成功返回() | {"错误码": "参数不合法"},
            统一成功返回() | {"错误说明": "不应存在"},
        ):
            with self.subTest(返回=返回):
                self.assertFalse(返回判定._判定(self.场景, 200, 返回)[0])

    def test_错误结果值为空且错误字段完整(self):
        错误场景 = 验证场景.从字典({
            "场景id": "负向", "能力id": "样例.相加", "参数": {},
            "预期": {"成功": False, "错误码": "参数不合法"},
        })
        正确 = {
            "成功": False, "值": None, "错误码": "参数不合法", "错误说明": "缺参数",
            "可重试": False, "请求id": "请求-2", "耗时毫秒": 1,
        }
        self.assertTrue(返回判定._判定(错误场景, 400, 正确)[0])
        self.assertFalse(返回判定._判定(错误场景, 400, {**正确, "值": {}})[0])
        self.assertFalse(返回判定._判定(错误场景, 400, {**正确, "错误说明": ""})[0])

    def test_校验关键值值类型完整值和返回契约(self):
        基础 = 成功场景()
        基础["预期"].update({
            "值": {"和": 3, "明细": [1, 2]},
            "返回契约": {"必需字段": ["和", "明细"], "字段类型": {"和": "整数型", "明细": "列表型"}},
        })
        场景 = 验证场景.从字典(基础)
        self.assertTrue(返回判定._判定(场景, 200, 统一成功返回({"和": 3, "明细": [1, 2]}))[0])
        self.assertFalse(返回判定._判定(场景, 200, 统一成功返回({"和": "3", "明细": [1, 2]}))[0])
        self.assertFalse(返回判定._判定(场景, 200, 统一成功返回({"和": 3, "明细": []}))[0])


class Test激活稳定指针(unittest.TestCase):
    def test_激活稳定指针指向不可变版本目录(self):
        with tempfile.TemporaryDirectory(prefix=f"激活指针_{os.getpid()}_", dir="/tmp") as 临时:
            根 = Path(临时)
            部署 = 根 / "部署"
            指纹 = "a" * 32
            版本 = 根 / "缓存" / "版本" / 指纹
            版本.mkdir(parents=True)
            写JSON(部署 / "编译清单.json", {"项目id": "样例项目", "制品指纹": 指纹})
            写JSON(部署 / "候选.json", {"制品版本目录": str(版本)})
            指针 = 验证应用._激活稳定指针(部署 / "当前.json", 部署)
            数据 = json.loads(指针.read_text(encoding="utf-8"))
            self.assertEqual(数据["状态"], "已验收")
            self.assertEqual(数据["当前制品指纹"], 指纹)
            self.assertEqual(Path(数据["制品版本目录"]).resolve(), 版本.resolve())

class Test直连异常与证据(unittest.TestCase):
    def test_直连地址只接受显式端口的IP回环HTTP根地址(self):
        for 地址 in ("http://127.0.0.1:45080", "http://[::1]:45080"):
            self.assertEqual(HTTP请求._校验直连地址(地址), 地址)
        for 地址 in ("http://localhost:45080", "https://example.com:443", "http://127.0.0.1", "http://127.0.0.1:45080/x", "ftp://127.0.0.1:21"):
            with self.subTest(地址=地址), self.assertRaises(ValueError):
                HTTP请求._校验直连地址(地址)

    def test_直连模式绝不查找启动器(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 绑定场景(验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(单实例验证, "_找启动器", side_effect=AssertionError("不应查启动器")), \
                 mock.patch.object(单实例验证, "_发送请求", return_value=(200, 统一成功返回(), 1)), \
                 mock.patch.object(返回判定, "_发送请求", return_value=(200, 统一成功返回(), 1)):
                报告, _, 进程 = 单实例验证.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertEqual(报告.失败数, 0)
            self.assertIsNone(进程)

    def test_单任务异常转成结构化失败而不击穿总流程(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 绑定场景(验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(单实例验证, "_发送请求", return_value=(200, {}, 1)), \
                 mock.patch.object(单实例验证, "验证单个", side_effect=RuntimeError("任务爆炸")):
                报告, _, _ = 单实例验证.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertEqual(报告.失败数, 1)
            self.assertIn("任务爆炸", 报告.结果列表[-1].失败原因)

    def test_制品全文件摘要前后漂移阻断(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "a.txt").write_text("第一版", encoding="utf-8")
            前 = 制品事实._制品全文件摘要(制品)
            (制品 / "a.txt").write_text("第二版", encoding="utf-8")
            后 = 制品事实._制品全文件摘要(制品)
            self.assertNotEqual(前["制品摘要"], 后["制品摘要"])
            报告 = 验证报告(制品摘要前=前, 制品摘要后=后)
            验证证据._校验制品前后绑定(报告)
            self.assertGreater(报告.失败数, 0)

    def test_证据按制品摘要隔离且同秒不覆盖(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时) / "制品"; 制品.mkdir()
            (制品 / "a").write_text("x", encoding="utf-8")
            摘要 = 制品事实._制品全文件摘要(制品)
            报告 = 验证报告(
                制品路径=str(制品), 制品摘要前=摘要, 制品摘要后=摘要,
                场景制品摘要=摘要["制品摘要"],
            )
            输出 = Path(临时) / "证据"
            一 = 验证证据.保存证据(报告, 制品, 输出)
            二 = 验证证据.保存证据(报告, 制品, 输出)
            self.assertNotEqual(一, 二)
            self.assertEqual(一.parent.name, 摘要["制品摘要"])
            数据 = json.loads(一.read_text(encoding="utf-8"))
            self.assertEqual(数据["证据绑定"]["制品摘要"], 摘要["制品摘要"])
            self.assertEqual(数据["证据绑定"]["场景制品摘要"], 摘要["制品摘要"])

    def test_执行时拒绝未绑定或错绑制品的场景(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            场景 = 验证场景.从字典(成功场景())
            场景.制品摘要 = "旧制品"
            报告, _, _ = 单实例验证.验证全部(制品, [场景], 直连地址="http://127.0.0.1:45080")
            self.assertGreater(报告.失败数, 0)
            self.assertIn("场景制品摘要", 报告.结果列表[0].失败原因)

    def test_主流程异常也在finally保存失败证据(self):
        with tempfile.TemporaryDirectory() as 临时:
            参数 = types.SimpleNamespace(
                制品=临时, 只生成场景=False, 服务=0, 场景="",
                并发=1, 超时秒=1, 端口=45080, 直连地址="",
            )
            with mock.patch.object(验证应用, "_加载场景", side_effect=ValueError("坏场景")), \
                 mock.patch.object(验证应用, "保存证据") as 保存:
                退出码 = 验证应用.主函数(参数)
        self.assertNotEqual(退出码, 0)
        保存.assert_called_once()
        self.assertGreater(保存.call_args.args[0].失败数, 0)

    def test_工作区指纹复用编译控制面实现(self):
        with mock.patch.object(制品事实, "_编译来源指纹", return_value={
            "提交": "abc", "工作区字节指纹": "def", "工作区状态": "干净",
        }) as 公共实现:
            指纹 = 制品事实._工作区指纹()
        公共实现.assert_called_once_with(None)
        self.assertEqual(指纹["工作区字节指纹"], "def")

    def test_自启动后总流程异常仍由finally回收进程(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "运行入口").mkdir()
            启动器 = 制品 / "运行入口" / "启动.py"
            启动器.write_text("", encoding="utf-8")
            场景 = 绑定场景(验证场景.从字典(成功场景()), 制品)
            假进程 = object()
            参数 = types.SimpleNamespace(
                制品=临时, 只生成场景=False, 服务=0, 场景="",
                并发=1, 超时秒=1, 端口=45080, 直连地址="",
            )
            with mock.patch.object(验证应用, "_加载场景", return_value=[场景]), \
                 mock.patch.object(单实例验证, "_启动制品", return_value=(假进程, 45080, {})), \
                 mock.patch.object(单实例验证, "_检查端口可用", return_value=(True, "")), \
                 mock.patch.object(单实例验证, "_发送请求", side_effect=RuntimeError("健康检查爆炸")), \
                 mock.patch.object(验证应用, "_回收进程组", return_value={"已回收": True}) as 回收, \
                 mock.patch.object(验证应用, "保存证据"):
                退出码 = 验证应用.主函数(参数)
        self.assertNotEqual(退出码, 0)
        self.assertIn(mock.call(假进程), 回收.call_args_list)


class Test制品端口策略(unittest.TestCase):
    """动态端口（0）= 系统分配、句柄回收即释放；显式端口仅诊断保留占用检查。"""

    def test_动态端口直通启动不查占用(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "运行入口").mkdir()
            (制品 / "运行入口" / "启动.py").write_text("", encoding="utf-8")
            场景 = 绑定场景(验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(单实例验证, "_启动制品",
                                   return_value=(object(), 52301, {})) as 启动, \
                 mock.patch.object(单实例验证, "_检查端口可用",
                                   side_effect=AssertionError("动态端口不得检查占用")), \
                 mock.patch.object(单实例验证, "_发送请求",
                                   return_value=(200, 统一成功返回(), 1)), \
                 mock.patch.object(返回判定, "_发送请求",
                                   return_value=(200, 统一成功返回(), 1)):
                报告, 实际端口, 进程 = 单实例验证.验证全部(制品, [场景], 端口=0)
            self.assertEqual(报告.失败数, 0)
            self.assertEqual(实际端口, 52301)
            self.assertIsNotNone(进程)
            启动.assert_called_once()
            启动.assert_called_once_with(制品 / "运行入口" / "启动.py", 制品, 0)

    def test_显式固定端口保留占用检查(self):
        with tempfile.TemporaryDirectory() as 临时:
            制品 = Path(临时)
            (制品 / "运行入口").mkdir()
            (制品 / "运行入口" / "启动.py").write_text("", encoding="utf-8")
            场景 = 绑定场景(验证场景.从字典(成功场景()), 制品)
            with mock.patch.object(单实例验证, "_检查端口可用", return_value=(False, "端口 45080 已被占用: 测试")) as 检查, \
                 mock.patch.object(单实例验证, "_启动制品",
                                   side_effect=AssertionError("端口被占用时禁止启动制品")):
                报告, 实际端口, 进程 = 单实例验证.验证全部(制品, [场景], 端口=45080)
            self.assertGreater(报告.失败数, 0)
            self.assertIn("已被占用", 报告.结果列表[-1].失败原因)
            检查.assert_called_once_with(45080)
            self.assertIsNone(实际端口)


@unittest.skipUnless(os.name == "posix", "进程组回收仅在 POSIX 验证")
class Test进程生命周期(unittest.TestCase):
    def test_首次提供者环境安装有足够启动预算(self):
        self.assertGreaterEqual(常量.默认启动超时秒, 120)

    def test_自启动独立进程组且子进程一并回收(self):
        with tempfile.TemporaryDirectory() as 临时:
            根 = Path(临时)
            启动器 = 根 / "启动.py"
            启动器.write_text(
                "import subprocess,time,os\n"
                "子=subprocess.Popen(['sleep','60'])\n"
                "open('子进程.pid','w').write(str(子.pid))\n"
                "print('已启动 http://127.0.0.1:45080',flush=True)\n"
                "time.sleep(60)\n", encoding="utf-8")
            进程, _, _ = 制品进程._启动制品(启动器, 根, 45080, 2, 1024)
            子pid = int((根 / "子进程.pid").read_text())
            self.assertNotEqual(进程组号(进程), 进程组号(os.getpid()))
            回收 = 制品进程._回收进程组(进程)
            self.assertTrue(回收["已回收"])
            self.assertIsNotNone(进程.poll())
            状态 = subprocess.run(["ps", "-p", str(子pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
            self.assertTrue(not 状态 or 状态.startswith("Z"), 状态)

    def test_静默启动硬超时且输出有界并回收(self):
        with tempfile.TemporaryDirectory() as 临时:
            根 = Path(临时)
            启动器 = 根 / "启动.py"
            启动器.write_text("import sys,time\nprint('X'*10000,flush=True)\ntime.sleep(60)\n", encoding="utf-8")
            开始 = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "启动超时") as 上下文:
                制品进程._启动制品(启动器, 根, 45080, 0.3, 256)
            self.assertLess(time.monotonic() - 开始, 2)
            self.assertLess(len(str(上下文.exception).encode()), 1024)


class Test验证页安全与并发(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.HTML = (系统根 / "开发工具" / "HTML验证" / "验证页.html").read_text(encoding="utf-8")

    def test_动态内容不使用innerHTML且服务添加最小CSP(self):
        self.assertNotIn(".innerHTML", self.HTML)
        self.assertIn("Content-Security-Policy", (系统根 / "开发工具" / "HTML验证" / "验证服务.py").read_text(encoding="utf-8"))

    def test_页面只展示服务端唯一执行器报告(self):
        self.assertIn("并发峰值", self.HTML)
        self.assertIn("fetch('/执行验证'", self.HTML)
        self.assertIn("服务端唯一场景执行器", self.HTML)
        for 旁路实现 in ("运行有界并发池", "验证一个(场景)", "function 校验返回", "预期.返回契约"):
            self.assertNotIn(旁路实现, self.HTML)


if __name__ == "__main__":
    unittest.main()
