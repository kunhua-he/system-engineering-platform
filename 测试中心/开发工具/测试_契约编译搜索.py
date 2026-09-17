"""第二十九阶段G1：唯一聚合契约解析与搜索收敛测试。

覆盖：聚合契约解析（合法/缺字段/任意类型拒绝）、能力定义编译器输出聚合
格式、搜索 14 字段（真实 模块库.OCR 等）、说明书生成复用唯一解析器、
重复解析删除确认。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 公共契约.包声明 import 加载声明文件
from 开发工具.契约编译.能力定义编译器 import 编译能力定义, 生成能力契约
from 开发工具.契约编译.聚合契约解析 import 解析聚合契约
from 开发工具.能力搜索.能力搜索器 import 搜索公开能力
from 开发工具.说明书生成.说明书生成器 import _包契约表, 生成单包说明书

十四字段 = (
    "能力id", "中文名", "说明", "参数类型", "必填", "默认值", "返回结构",
    "错误码", "调用示例", "权限", "资源预算", "依赖", "版本", "最近成功验证",
)


def 样例定义() -> dict:
    return {
        "包id": "支持库.适配层.python_docx提供者",
        "能力列表": [
            {
                "能力id": "办公文档支持库.文字文档.解析文字文档",
                "版本": "1.0.0",
                "中文名称": "解析文字文档",
                "说明": "解析 DOC/DOCX 为平台通用文档",
                "参数": [
                    {"名称": "文件路径", "类型": "文本型", "必填": True, "说明": "文件绝对路径"},
                    {"名称": "格式", "类型": "文本型", "必填": False, "默认值": "docx", "说明": "doc/docx"},
                ],
                "返回": "结果型",
                "错误码": ["文件不存在", "参数不合法", "提供者不可用", "文件损坏"],
                "行为": {
                    "修改输入": False, "幂等": True, "副作用": "只读", "排序稳定": True,
                    "时区": "Asia/Shanghai", "编码": "utf-8", "精度": "高",
                    "空值": "返回空文档", "输入上限": "200MB", "超时可重试": True,
                    "取消": "支持", "重试条件": "超时/提供者不可用",
                    "事务边界": "无", "补偿动作": "无", "线程安全": True, "进程安全": True,
                    "资源释放": "自动", "错误码": "统一", "可重试性": "超时可重试",
                },
                "提供者": {"默认": "支持库.适配层.python_docx提供者", "版本": ">=1.0.0"},
            }
        ],
    }


class 聚合契约解析测试(unittest.TestCase):
    """唯一聚合契约解析函数：合法/缺字段/任意类型拒绝。"""

    def test_真实Pillow聚合契约读取成功(self):
        契约文件 = 项目根 / "支持库" / "适配层" / "Pillow提供者" / "能力契约" / "参数契约.json"
        数据, 问题 = 解析聚合契约(契约文件)
        self.assertFalse(any("任意" in 项 for 项 in 问题), str(问题))
        self.assertGreaterEqual(len(数据["能力契约"]), 8)
        条目 = 数据["能力契约"][0]
        for 字段 in ("能力id", "版本", "说明", "参数", "返回", "错误码", "调用示例"):
            self.assertIn(字段, 条目)
        self.assertIn("行为", 条目)
        self.assertIn("提供者", 条目)
        参数字典 = {参数["名称"]: 参数 for 参数 in 条目["参数"]}
        self.assertEqual("字节集型", 参数字典["字节"]["类型"])
        self.assertEqual(60, 参数字典["超时秒"]["默认值"])

    def test_严格校验合法聚合契约通过(self):
        数据 = {
            "契约版本": "1.0.0",
            "能力契约": [{
                "能力id": "样例.合法", "版本": "1.0.0", "说明": "测试",
                "参数": [{"名称": "值", "类型": "文本型", "必填": True,
                          "默认值": None, "说明": "值"}],
                "返回": "结果型", "错误码": ["参数不合法"],
                "调用示例": {"能力id": "样例.合法", "参数": {}},
            }],
        }
        _标准, 问题 = 解析聚合契约(数据, 严格=True)
        self.assertEqual([], 问题, str(问题))

    def test_缺字段严格校验拒绝(self):
        数据 = {"契约版本": "1.0.0", "能力契约": [{"能力id": "样例.缺字段"}]}
        _标准, 问题 = 解析聚合契约(数据, 严格=True)
        文本 = "\n".join(问题)
        for 片段 in ("版本", "说明", "参数", "返回", "错误码", "调用示例"):
            self.assertIn(片段, 文本, f"缺字段校验应拒绝 {片段}")

    def test_任意类型严格拒绝与读取归一化(self):
        数据 = {
            "契约版本": "1.0.0",
            "能力契约": [{
                "能力id": "样例.任意", "版本": "1.0.0", "说明": "测试",
                "参数": [{"名称": "值", "类型": "任意"}], "返回": "结果",
                "错误码": ["参数不合法"], "调用示例": {"能力id": "样例.任意", "参数": {}},
            }],
        }
        _标准, 问题 = 解析聚合契约(数据, 严格=True)
        self.assertTrue(any("任意" in 项 for 项 in 问题), str(问题))
        标准, _问题 = 解析聚合契约(数据)
        self.assertEqual("未约束", 标准["能力契约"][0]["参数"][0]["类型"])
        self.assertEqual({"能力id": "样例.任意", "参数": {}},
                         标准["能力契约"][0]["调用示例"])


class 编译器聚合输出测试(unittest.TestCase):
    """能力定义编译器输出 S0 唯一聚合格式并复用解析器自检。"""

    def test_生成能力契约为聚合格式(self):
        契约文本 = 生成能力契约(样例定义())
        契约 = json.loads(契约文本)
        # 契约版本唯一：断言对唯一事实源，不写死版本号（写死会在升版本时误报）
        from 公共契约.版本规则.契约版本 import 契约版本
        self.assertEqual(契约版本, 契约["契约版本"])
        条目 = 契约["能力契约"][0]
        for 字段 in ("能力id", "版本", "说明", "参数", "返回", "错误码", "调用示例"):
            self.assertIn(字段, 条目)
        self.assertEqual("办公文档支持库.文字文档.解析文字文档", 条目["调用示例"]["能力id"])
        self.assertEqual({"格式": "docx"}, 条目["调用示例"]["参数"])
        数据, 问题 = 解析聚合契约(契约文本, 严格=True)
        self.assertEqual([], 问题, str(问题))

    def test_编译产物通过唯一解析器自检(self):
        临时 = Path(tempfile.mkdtemp())
        包目录 = 临时 / "python_docx提供者"
        包目录.mkdir()
        定义文件 = 包目录 / "能力定义.json"
        定义文件.write_text(json.dumps(样例定义(), ensure_ascii=False), encoding="utf-8")
        结果 = 编译能力定义(
            定义文件, 包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        self.assertTrue(结果.成功, str(结果.问题列表))
        数据, 问题 = 解析聚合契约(包目录 / "能力契约" / "参数契约.json")
        self.assertEqual([], 问题, str(问题))
        self.assertEqual(1, len(数据["能力契约"]))


class 搜索14字段测试(unittest.TestCase):
    """能力搜索器（转调）14 字段全覆盖（唯一实现腿 = 模块库.能力目录，真实 模块库.OCR 等）。"""

    def test_真实模块OCR搜索14字段全覆盖(self):
        结果 = 搜索公开能力(项目根, "OCR", 20)
        self.assertTrue(结果, "关键词 OCR 应有搜索结果")
        for 能力 in 结果:
            for 字段 in 十四字段:
                self.assertIn(字段, 能力, f"{能力['能力id']} 缺字段 {字段}")
            文本 = json.dumps(能力, ensure_ascii=False)
            for 禁用 in ("未声明", "无调用示例"):
                self.assertNotIn(禁用, 文本)
            for 参数 in 能力["参数类型"]:
                self.assertNotEqual("任意", 参数["类型"])
        self.assertTrue(any("OCR.识别图片文字" == 能力["能力id"] for 能力 in 结果))

    def test_真实Pillow契约字段完整(self):
        结果 = 搜索公开能力(项目根, "解码图像", 10)
        目标 = next((能力 for 能力 in 结果
                     if 能力["能力id"] == "图像处理支持库.图像解码.解码图像"), None)
        self.assertIsNotNone(目标)
        self.assertEqual("1.0.0", 目标["版本"])
        self.assertIn("格式未知", 目标["错误码"])
        self.assertIn("图像处理支持库.图像解码.解码图像", 目标["调用示例"])
        参数字典 = {参数["名称"]: 参数 for 参数 in 目标["参数类型"]}
        self.assertEqual("字节集型", 参数字典["字节"]["类型"])
        self.assertEqual(60, 参数字典["超时秒"]["默认值"])
        self.assertIn("字节 64MB", 目标["资源预算"])


class 说明书复用测试(unittest.TestCase):
    """说明书生成器复用唯一聚合契约解析。"""

    def test_说明书使用真实契约数据(self):
        声明 = 加载声明文件(项目根 / "支持库" / "适配层" / "Pillow提供者" / "包声明.json")
        文本 = 生成单包说明书(声明)
        self.assertIn("格式未知", 文本)
        self.assertNotIn("外部不可访问", 文本)
        self.assertIn("版本：1.0.0", 文本)
        self.assertIn("图像解码.解码图像", 文本)
        self.assertIn("调用示例", 文本)
        self.assertIn("字节集型", 文本)  # 契约真实类型

    def test_OCR说明书参数类型归一化(self):
        声明 = 加载声明文件(项目根 / "模块库" / "OCR" / "包声明.json")
        契约表 = _包契约表(声明)
        self.assertIn("OCR.识别图片文字", 契约表)
        for 参数 in 契约表["OCR.识别图片文字"]["参数"]:
            self.assertNotEqual("任意", 参数["类型"])
        文本 = 生成单包说明书(声明)
        self.assertIn("OCR.识别图片文字", 文本)
        self.assertNotIn("参数不合法、外部不可访问、内部错误", 文本)


class 重复解析删除确认测试(unittest.TestCase):
    """重复解析逻辑已删除/委托，模块复用唯一聚合契约解析。

    注：`开发工具/能力搜索/能力搜索器.py` 已随 D-4 收口改为**转调**（不再解析契约），
    故不在此文件表内；它的收口断言见 `检索唯一腿收口测试`。
    """

    文件表 = (
        "开发工具/契约编译/能力定义编译器.py",
        "开发工具/契约编译/契约编译器.py",
        "开发工具/契约编译/漂移检测.py",
        "开发工具/说明书生成/说明书生成器.py",
    )

    def test_全部复用唯一聚合契约解析器(self):
        for 相对路径 in self.文件表:
            源码 = (项目根 / 相对路径).read_text(encoding="utf-8")
            self.assertIn("聚合契约解析", 源码, f"{相对路径} 未复用唯一聚合契约解析器")

    def test_搜索器不再硬编码错误码与任意类型(self):
        源码 = (项目根 / "开发工具/能力搜索/能力搜索器.py").read_text(encoding="utf-8")
        self.assertNotIn("外部不可访问", 源码)
        self.assertNotIn("'任意'", 源码)

    def test_说明书生成器不再硬编码错误码与任意兜底(self):
        源码 = (项目根 / "开发工具/说明书生成/说明书生成器.py").read_text(encoding="utf-8")
        self.assertNotIn("外部不可访问", 源码)
        self.assertNotIn("'任意'", 源码)

    def test_契约编译器校验已委托(self):
        源码 = (项目根 / "开发工具/契约编译/契约编译器.py").read_text(encoding="utf-8")
        self.assertNotIn("缺少 能力id", 源码)


class 检索唯一腿收口测试(unittest.TestCase):
    """D-4 收口：能力检索只剩一条实现腿（模块库.能力目录），开发工具侧一律转调。

    反向可验证：把任一处改回自行扫描声明，本类必红。
    """

    转调文件表 = (
        "开发工具/能力搜索/能力搜索器.py",
        "开发工具/开发入口.py",
        "开发工具/统一能力入口/Agent查询/查询入口.py",
    )
    自建检索痕迹 = ("扫描目录(", "发现全部(", "rglob(", "解析聚合契约")

    def test_能力搜索器不再自建检索实现(self):
        from 开发工具.能力搜索 import 能力搜索器

        源码 = (项目根 / "开发工具/能力搜索/能力搜索器.py").read_text(encoding="utf-8")
        for 痕迹 in self.自建检索痕迹:
            self.assertNotIn(痕迹, 源码, f"能力搜索器 仍在自建检索（命中 {痕迹}）")
        self.assertEqual("能力目录.搜索能力", 能力搜索器.搜索能力id)

    def test_开发入口搜索能力只转调(self):
        源码 = (项目根 / "开发工具/开发入口.py").read_text(encoding="utf-8")
        搜索段 = 源码.split("def 搜索能力", 1)[1].split("def 查看契约", 1)[0]
        self.assertIn("能力搜索.能力搜索器 import", 搜索段, "开发入口.搜索能力 未转调唯一检索腿")
        for 痕迹 in self.自建检索痕迹:
            self.assertNotIn(痕迹, 搜索段, f"开发入口.搜索能力 仍自建检索（命中 {痕迹}）")

    def test_查询入口搜索能力只转调(self):
        源码 = (项目根 / "开发工具/统一能力入口/Agent查询/查询入口.py").read_text(encoding="utf-8")
        搜索段 = 源码.split("def 搜索能力", 1)[1].split("def 查看包版本", 1)[0]
        self.assertIn("能力搜索.能力搜索器 import", 搜索段, "查询入口.搜索能力 未转调唯一检索腿")
        for 痕迹 in self.自建检索痕迹:
            self.assertNotIn(痕迹, 搜索段, f"查询入口.搜索能力 仍自建检索（命中 {痕迹}）")

    def test_三处转调结果同源且字段口径一致(self):
        """三处入口拿到的记录必须同源：同一关键词的记录数与能力id完全一致。"""
        from 开发工具 import 开发入口
        from 开发工具.能力搜索.能力搜索器 import 搜索公开能力
        from 开发工具.统一能力入口.Agent查询.查询入口 import 查询入口

        关键词 = "能力目录.搜索能力"
        直接结果 = 搜索公开能力(项目根, 关键词, 5)
        开发入口结果 = 开发入口.搜索能力(关键词, 5)
        查询结果 = 查询入口().搜索能力(关键词=关键词)
        self.assertTrue(查询结果.成功, 查询结果.说明)
        self.assertEqual([记录["能力id"] for 记录 in 直接结果],
                         [记录["能力id"] for 记录 in 开发入口结果])
        self.assertEqual([记录["能力id"] for 记录 in 直接结果],
                         [记录["能力id"] for 记录 in 查询结果.数据])

    def test_唯一能力腿失败时如实上报(self):
        """能力腿失败不得静默降级成空列表：唯一腿报错 → 开发入口抛错、查询入口带原因失败。

        桩打在**依赖边界**（`后端核心.后端核心.后端核心.调用`＝唯一腿的下游调用面），
        不是被测模块自身的成员：被测对象（`能力搜索器` 的转调逻辑）保持原样不被替换，
        证明的是两处转调入口对「能力腿报错」的处理是否如实上报（fail-closed），
        而不是用假桩顶掉被测实现；签名校验由 `autospec=True` 承担。
        """
        from unittest import mock

        from 公共契约.基础类型.结果类型 import 结果
        from 后端核心.后端核心 import 后端核心 as 后端核心类
        from 开发工具 import 开发入口
        from 开发工具.能力搜索 import 能力搜索器
        from 开发工具.统一能力入口.Agent查询.查询入口 import 查询入口

        能力腿失败 = 结果.失败("内部错误", "模拟唯一腿不可用", 来源="定向测试桩")
        with mock.patch.object(后端核心类, "调用", autospec=True, return_value=能力腿失败):
            with self.assertRaises(能力搜索器.检索失败) as 捕获:
                开发入口.搜索能力("任意", 1)
            查询结果 = 查询入口().搜索能力(关键词="任意")
        self.assertIn("模拟唯一腿不可用", str(捕获.exception))
        self.assertFalse(查询结果.成功)
        self.assertIn("模拟唯一腿不可用", 查询结果.说明)


if __name__ == "__main__":
    unittest.main()
