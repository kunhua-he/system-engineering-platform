"""开工编排 模块定向测试骨架（模块模板生成器产出，按需补充真实场景）。"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 真
from 模块库.开工编排 import 开工准备, 注册能力
import 模块库.开工编排.实现.开工编排 as 开工实现

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


#: 认领一次必须恰好调用一次的能力 id（判据锚**调用入参**，不锚任何注释文字）。
能力_申请文件租约 = "平台控制面.能力目录.申请文件租约"
目标路径 = "模块库/开工编排/实现/开工编排.py"


class 开工即占转发项目根测试(unittest.TestCase):
    """★ 反向验证（未完成事项 #134 ①）：`开工即占` 必须把 `项目根` 转发给 `申请文件租约`。

    修前它不转发 ⇒ 租约层按进程 cwd 解析基准根（网关跑激活制品时 = 制品根），登记的内容
    指纹来自制品副本、未随制品打包的路径（如 `测试中心/…`）恒「不存在」—— 乐观锁的
    「内容」那一半失效，想开门就得申报错那棵树的指纹（实测：本包认领 6 条路径时，
    `测试中心/…` 两条回「不存在」、其余四条回制品副本的 sha256）。

    这里把 `开工准备` 与 `_调用` 换成夹具，直接断言**认领入参里那一项**：
    去掉转发（或转发空串）时本判据立刻变红，不会因为「指纹读数的形状看着正常」而假绿。
    """

    仓库根 = str(系统根)

    def _夹具(self, 捕获: dict):
        def 假开工准备(任务=None, 项目根=None, 修改路径=None, 开工ID=None):
            return 结果.成功结果({
                "开工ID": 开工ID or "",
                "路径校验": {"项目根": self.仓库根, "通过清单": [{"路径": 目标路径}]},
            })

        def 假调用(能力id, 参数):
            捕获.setdefault(能力id, []).append(参数)
            return 结果.成功结果({"租约清单": [], "租约id清单": [], "申请数": 1,
                            "认领数": 1, "冲突清单": []})

        return 假开工准备, 假调用

    def _认领参数(self, 捕获: dict, **开工即占入参) -> dict:
        假开工准备, 假调用 = self._夹具(捕获)
        with mock.patch.object(开工实现, "开工准备", 假开工准备), \
             mock.patch.object(开工实现, "_调用", 假调用):
            出 = 开工实现.开工即占(**开工即占入参)
        self.assertTrue(出.成功, 出.错误说明)
        参数表 = 捕获.get(能力_申请文件租约) or []
        self.assertEqual(len(参数表), 1, "必须恰好发起一次认领")
        return 参数表[0]

    def test_认领入参必须带项目根(self) -> None:
        参数 = self._认领参数({}, 任务="转发项目根用例", 项目根=self.仓库根,
                          修改路径=[目标路径])
        self.assertIn("项目根", 参数,
                      "开工即占 必须把 项目根 转发给 申请文件租约（否则现场指纹按 cwd 解析）")
        self.assertEqual(参数["项目根"], self.仓库根,
                         "转发的基准根必须与 开工准备 的边界校验是同一棵树")

    def test_入参项目根为空时也绝不许转发空串(self) -> None:
        """反向：空串 = 让租约层按 cwd 猜根 —— 这正是本缺陷，必须落到同一棵树而不是空串。"""
        参数 = self._认领参数({}, 任务="空项目根用例", 项目根=None, 修改路径=[目标路径])
        self.assertNotEqual(str(参数.get("项目根") or "").strip(), "",
                            "绝不许把空串转发下去（空串 = 按 cwd 猜根）")
        self.assertEqual(参数["项目根"], self.仓库根)


class 开工准备撞车查询转发项目根测试(unittest.TestCase):
    """★ 兄弟调用点（未完成事项 #134 ①）：`开工准备` 查撞车时的 `查询文件租约` 也必须带 `项目根`。

    同根因、同一处修复：不转发它，网关跑激活制品时「现场指纹」恒「不存在」——
    撞车方看到的指纹读数全是假的（「只修一处、兄弟漏改」在本仓已复发五次，故单独立判据）。
    """

    仓库根 = str(系统根)

    def test_撞车查询必须带项目根(self) -> None:
        捕获: dict = {}

        def 假调用(能力id, 参数):
            捕获.setdefault(能力id, []).append(参数)
            if 能力id == "文件系统支持库.文件操作.判断存在":
                return 结果.成功结果(真)
            if 能力id == "系统核心支持库.路径安全.校验路径":
                return 结果.成功结果({"通过": 真,
                                 "绝对路径": str(系统根 / str(参数.get("相对路径") or ""))})
            if 能力id == "文件系统支持库.文件操作.读取文件":
                return 结果.成功结果("")
            if 能力id == "数据操作支持库.文本处理.按行分割":
                return 结果.成功结果([])
            return 结果.成功结果({})

        with mock.patch.object(开工实现, "_调用", 假调用):
            出 = 开工实现.开工准备(任务="撞车查询转发项目根", 项目根=self.仓库根,
                            修改路径=[目标路径])
        self.assertTrue(出.成功, 出.错误说明)
        查询参数表 = 捕获.get("平台控制面.能力目录.查询文件租约") or []
        self.assertEqual(len(查询参数表), 1, "必须恰好查一次撞车")
        self.assertEqual(查询参数表[0].get("项目根"), str(系统根),
                         "撞车查询必须与边界校验用同一个项目根（否则现场指纹按 cwd 解析）")


#: 外平台（驱动方 Agent）的工具类名 —— 本平台 MCP 薄壳只有三个工具，这些名字一个都不存在。
#: 判据里把它们当「违规词」：工具姿势要么写本平台能力 id，要么按类别描述。
外平台工具名 = re.compile(r"(?<![一-鿿])(read_file|execute_code|terminal|delegate_task|search_files)")

#: 裸命令判据 —— 让 Agent 直接敲 shell 的写法（华哥 2026-09-22：「那把裸命令给删了……只保留一条腿」）。
#: 只禁「写法」、不禁「提到」：禁令式表述（如「禁止 cat/head/tail/sed 读文件」）不在此列。
裸命令判据 = ("rg -n", "| rg", "ls 开发工具/", "grep -r", "curl ", "python3.14 -m", "python3.14 -c", "cat/head/tail/sed")
#: 例外：含**禁令标记**的行是在讲清禁什么，不是在叫人去敲（与 外平台工具名 的例外同理）。
#: 实测踩过（2026-09-22，第一次加宽判据就翻红）：禁令式表述被误报成违规 ——
#: 「**禁止** cat/head/tail/sed 读文件」「**不要自己敲 rg/grep**」两条都被当成「在教裸命令」。
禁令标记 = ("禁止", "不许", "不要", "不得", "别用", "不敲", "一律不")
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
        违规 = [行 for 行 in 姿势
               if any(词 in 行 for 词 in 裸命令判据)
               and not any(标记 in 行 for 标记 in 禁令标记)]
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
