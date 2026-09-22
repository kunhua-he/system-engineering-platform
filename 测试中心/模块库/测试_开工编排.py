"""开工编排 模块定向测试骨架（模块模板生成器产出，按需补充真实场景）。"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.开工编排 import 开工准备, 注册能力

class Test开工编排模块(unittest.TestCase):
    """装配冒烟：公开入口可导入、注册能力齐全、调用返回统一结果。"""

    def test_公开入口可导入(self):
        for 能力名 in ['开工准备']:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ['开工编排.开工准备']:
            self.assertIn(能力id, 注册表.能力id列表)

    def test_开工准备_返回统一结果(self):
        返回值 = 开工准备("", "", [], 0, "")
        self.assertIsInstance(返回值, 结果)


#: 外平台（驱动方 Agent）的工具类名 —— 本平台 MCP 薄壳只有三个工具，这些名字一个都不存在。
#: 判据里把它们当「违规词」：工具姿势要么写本平台能力 id，要么按类别描述。
外平台工具名 = re.compile(r"(?<![一-鿿])(read_file|execute_code|terminal|delegate_task|search_files)")

#: 裸命令判据 —— 让 Agent 直接敲 shell 的写法（华哥 2026-09-22：「那把裸命令给删了……只保留一条腿」）。
#: 只禁「写法」、不禁「提到」：禁令式表述（如「禁止 cat/head/tail/sed 读文件」）不在此列。
裸命令判据 = ("rg -n", "| rg", "ls 开发工具/", "grep -r")
源头规范路径 = 系统根 / "开发文档" / "规范" / "任务类型规范.json"
验证夹具路径 = 系统根 / "模块库" / "开工编排" / "验证夹具" / "任务类型规范.json"


class 通用纪律规范与夹具(unittest.TestCase):
    """通用纪律的源头、副本、用词三条判据（2026-09-21 新增）。

    为什么要有这组：`验证夹具/任务类型规范.json` 是源头 `开发文档/规范/任务类型规范.json`
    的副本，实测它**已落后源头一个版本（夹具 1.3.1 / 源头 1.4.0）而无人发现** ——
    没有机器判据的「两份必须一致」等于没有，副本漂移后测试就在断言一份作废的纪律文本。
    另一条是外平台工具名：送达点里写 `read_file` 会让新会话去「找」一个本平台不存在的工具。
    """

    def test_验证夹具与源头逐字一致(self):
        self.assertTrue(源头规范路径.is_file(), f"源头规范缺失：{源头规范路径}")
        self.assertTrue(验证夹具路径.is_file(), f"验证夹具缺失：{验证夹具路径}")
        self.assertEqual(
            验证夹具路径.read_text(encoding="utf-8"),
            源头规范路径.read_text(encoding="utf-8"),
            "验证夹具已与源头漂移；同步命令：cp 开发文档/规范/任务类型规范.json "
            "模块库/开工编排/验证夹具/任务类型规范.json")

    def test_工具姿势不直接写外平台工具名(self):
        """除首条「工具名口径」（它就是来解释这些名字的）外，不得直接写。"""
        数据 = json.loads(源头规范路径.read_text(encoding="utf-8"))
        姿势 = 数据["通用纪律"]["工具姿势"]
        违规 = [行 for 行 in 姿势
               if 外平台工具名.search(行) and not 行.startswith("★ 工具名口径")]
        self.assertEqual(
            违规, [],
            "这些条仍直接写外平台工具名（应换成本平台能力 id 或按类别描述）：" + str(违规))

    def test_工具名口径条存在且给了映射(self):
        """反向：上面的「不得直接写」必须配一条映射说明，否则规则无从执行。"""
        数据 = json.loads(源头规范路径.read_text(encoding="utf-8"))
        姿势 = 数据["通用纪律"]["工具姿势"]
        口径 = [行 for 行 in 姿势 if 行.startswith("★ 工具名口径")]
        self.assertEqual(len(口径), 1, "必须恰有一条「工具名口径」说明")
        for 应含 in ("文件管理.读取文件", "执行命令"):
            self.assertIn(应含, 口径[0], f"工具名口径必须给出「{应含}」的落点")

    def test_工具姿势不写裸命令(self):
        """华哥 2026-09-22：「那把裸命令给删了……只保留一条腿」—— 扫描/找文件必须给能力 id。

        裸命令（rg/ls 之类）是**工具内部实现**，调用方只说「搜什么」；且裸 rg 的输出无界，
        会原样灌进上下文（实测同一搜索：裸 rg 4,481 字符 vs 能力腿只取结论 37 字符）。
        """
        数据 = json.loads(源头规范路径.read_text(encoding="utf-8"))
        姿势 = 数据["通用纪律"]["工具姿势"]
        违规 = [行 for 行 in 姿势 if any(词 in 行 for 词 in 裸命令判据)]
        self.assertEqual(
            违规, [],
            "这些条仍让 Agent 去敲裸命令（应换成本平台能力 id）：" + str(违规))

    def test_扫描与找文件条点名了能力id(self):
        """反向：上面禁掉裸命令，必须同时给出替代能力，否则规则无从执行。"""
        数据 = json.loads(源头规范路径.read_text(encoding="utf-8"))
        全文 = "\n".join(数据["通用纪律"]["工具姿势"])
        for 能力id in ("文件系统支持库.内容检索.正则搜索", "文件系统支持库.文件操作.搜索文件"):
            self.assertIn(能力id, 全文, f"工具姿势必须点名「{能力id}」作为裸命令的替代")


if __name__ == "__main__":
    unittest.main()
