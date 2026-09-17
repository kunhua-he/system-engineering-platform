"""能力定义编译器测试：唯一事实源 → 契约派生物自动生成。

覆盖：编译产物齐全/生成标记/两次编译摘要一致/篡改生成物阻断/
行为字段缺失阻断/提供者缺失阻断/漂移检测一致性/JSON 结构向后兼容。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.契约编译.能力定义编译器 import (
    编译能力定义, 编译结果, 生成Agent数据, 生成包声明, 生成能力契约,
    生成注册入口, 生成搜索数据, 读取能力定义, 校验能力定义,
    从现有包生成能力定义,
)
from 开发工具.契约编译.漂移检测 import 检测能力定义漂移

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"


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
                    {"名称": "文件路径", "类型": "文本", "必填": 真, "说明": "文件绝对路径"},
                    {"名称": "格式", "类型": "文本", "必填": 假, "默认值": "docx", "说明": "doc/docx"},
                ],
                "返回": "结果",
                "错误码": ["文件不存在", "参数不合法", "提供者不可用", "文件损坏"],
                "行为": {
                    "修改输入": 假, "幂等": 真, "副作用": "只读", "排序稳定": 真,
                    "时区": "Asia/Shanghai", "编码": "utf-8", "精度": "高",
                    "空值": "返回空文档", "输入上限": "200MB", "超时可重试": 真,
                    "取消": "支持", "重试条件": "超时/提供者不可用",
                    "事务边界": "无", "补偿动作": "无", "线程安全": 真, "进程安全": 真,
                    "资源释放": "自动", "错误码": "统一", "可重试性": "超时可重试",
                },
                "提供者": {"默认": "支持库.适配层.python_docx提供者", "版本": ">=1.0.0"},
            }
        ],
    }


class Test能力定义编译器(unittest.TestCase):
    """能力定义编译器闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        self.包目录 = self.临时 / "python_docx提供者"
        self.包目录.mkdir()
        self.定义文件 = self.包目录 / "能力定义.json"
        self.定义文件.write_text(json.dumps(样例定义(), ensure_ascii=False), encoding="utf-8")

    def test_编译产物齐全(self):
        结果 = 编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="支持库.适配层.python_docx提供者.实现.文字文档",
        )
        self.assertTrue(结果.成功, str(结果.问题列表))
        名称表 = {产物["类型"] for 产物 in 结果.产物列表}
        self.assertIn("参数契约.json", 名称表)
        self.assertIn("包声明.json", 名称表)
        self.assertIn("__init__.py", 名称表)
        self.assertIn("能力搜索数据.json", 名称表)
        self.assertIn("Agent查询数据.json", 名称表)
        # 验证场景引用.json 由能力作者手写，编译器一律不生成、不覆盖；
        # 旧编译器生成的 {场景id,目标,范围} 三键格式不是合法 v1 引用。
        self.assertNotIn("验证场景引用.json", 名称表)
        self.assertIn("完整性摘要.json", 名称表)

    def test_生成标记存在(self):
        编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        入口 = (self.包目录 / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(生成标记, 入口)
        self.assertIn("def 注册能力", 入口)

    def test_两次编译摘要一致(self):
        """从干净输入连续生成两次，内容摘要一致（P3 要求 2）。"""
        第一次 = 编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        摘要一 = {产物["路径"]: 产物["摘要"] for 产物 in 第一次.产物列表}
        第二次 = 编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        摘要二 = {产物["路径"]: 产物["摘要"] for 产物 in 第二次.产物列表}
        self.assertEqual(摘要一, 摘要二)

    def test_篡改生成物阻断(self):
        """手工篡改生成物（删生成标记）→ 重新编译拒绝覆盖（P3 要求 4）。"""
        编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        入口 = self.包目录 / "__init__.py"
        入口.write_text("# 手工篡改\n", encoding="utf-8")
        结果 = 编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        self.assertFalse(结果.成功)
        self.assertTrue(any("手工修改" in 问题 for 问题 in 结果.问题列表))

    def test_漂移检测一致(self):
        编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        问题列表 = 检测能力定义漂移(self.包目录)
        self.assertEqual([], 问题列表, str(问题列表))

    def test_篡改能力契约漂移阻断(self):
        编译能力定义(
            self.定义文件, self.包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        契约 = self.包目录 / "能力契约" / "参数契约.json"
        数据 = json.loads(契约.read_text(encoding="utf-8"))
        数据["能力契约"][0]["参数"] = [{"名称": "被篡改"}]
        契约.write_text(json.dumps(数据, ensure_ascii=False), encoding="utf-8")
        问题列表 = 检测能力定义漂移(self.包目录)
        self.assertTrue(any("不一致" in 问题 for 问题 in 问题列表))

    def test_行为字段缺失阻断(self):
        定义 = 样例定义()
        定义["能力列表"][0]["行为"].pop("副作用")
        校验结果 = 校验能力定义(定义)
        self.assertTrue(any("行为" in 问题 and "副作用" in 问题 for 问题 in 校验结果))

    def test_提供者缺失阻断(self):
        定义 = 样例定义()
        定义["能力列表"][0]["提供者"] = {}
        校验结果 = 校验能力定义(定义)
        self.assertTrue(any("默认" in 问题 for 问题 in 校验结果))

    def test_错误码空阻断(self):
        定义 = 样例定义()
        定义["能力列表"][0]["错误码"] = []
        校验结果 = 校验能力定义(定义)
        self.assertTrue(any("错误码" in 问题 for 问题 in 校验结果))

    def test_JSON结构向后兼容(self):
        """生成的能力契约与既有参数契约.json 结构一致（能力契约 列表）。"""
        契约文本 = 生成能力契约(样例定义())
        契约 = json.loads(契约文本)
        self.assertIn("能力契约", 契约)
        条目 = 契约["能力契约"][0]
        self.assertEqual(条目["能力id"], "办公文档支持库.文字文档.解析文字文档")
        self.assertIn("参数", 条目)
        self.assertIn("错误码", 条目)

    def test_从现有契约迁移唯一能力定义(self):
        """历史包只提供声明与参数契约时，迁移结果可被编译器校验。"""
        包目录 = self.临时 / "迁移包"
        (包目录 / "能力契约").mkdir(parents=True)
        (包目录 / "包声明.json").write_text(json.dumps({
            "包id": "测试.迁移包", "名称": "迁移包", "类型": "支持库",
            "版本": "1.0.0", "说明": "迁移测试", "依赖": [],
            "能力": [{"能力id": "迁移.执行", "名称": "执行"}],
        }, ensure_ascii=False), encoding="utf-8")
        (包目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
            "契约版本": "1.0.0", "能力契约": [{
                "能力id": "迁移.执行", "版本": "1.0.0", "说明": "执行测试",
                "参数": [{"名称": "输入", "类型": "文本型", "必填": 真}],
                "返回": {"类型": "结果型"}, "错误码": ["参数不合法"],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        路径, 问题 = 从现有包生成能力定义(包目录)
        self.assertEqual([], 问题)
        self.assertIsNotNone(路径)
        定义 = 读取能力定义(路径)
        self.assertEqual([], 校验能力定义(定义), 定义)
        self.assertEqual(["迁移.执行"], [x["能力id"] for x in 定义["能力列表"]])
        self.assertEqual({"类型": "结果型"}, 定义["能力列表"][0]["返回"])

    def test_已有能力定义不覆盖(self):
        """迁移入口不得覆盖作者已经维护的唯一事实源。"""
        包目录 = self.包目录
        (包目录 / "能力契约").mkdir(exist_ok=True)
        (包目录 / "包声明.json").write_text(json.dumps({
            "包id": "支持库.适配层.python_docx提供者", "版本": "1.0.0",
        }, ensure_ascii=False), encoding="utf-8")
        (包目录 / "能力契约" / "参数契约.json").write_text(
            json.dumps({"能力契约": []}, ensure_ascii=False), encoding="utf-8")
        路径, 问题 = 从现有包生成能力定义(包目录)
        self.assertEqual(路径, self.定义文件)
        self.assertTrue(any("已有能力定义" in x for x in 问题))

    def test_值结构类型使用易语言标准类型(self):
        """迁移只转换值结构中的类型词，不改字段名等业务语义。"""
        from 开发工具.契约编译.能力定义编译器 import 标准化易语言类型
        数据 = {"值结构": {"标题": "文本", "宽度": "整数", "块列表": "列表"}}
        结果 = 标准化易语言类型(数据)
        self.assertEqual({"标题": "文本型", "宽度": "整数型", "块列表": "列表型"}, 结果["值结构"])


if __name__ == "__main__":
    unittest.main()
