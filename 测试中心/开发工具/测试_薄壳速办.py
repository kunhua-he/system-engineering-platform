"""薄壳「速办」入口定向测试（不依赖网关，纯本地逻辑）。

为什么单独写：`操作=速办` 是 2026-09-24 批R·R-33 新增的**短话入口**，它有三件容易
悄悄坏掉的事，本文件逐件钉住：

  ① **唯一事实源**：速办表与 `公共契约/能力契约/常用意图.py` 的映射必须逐条一致
     （速办表里一个能力 id 都不写 ⇒ 只可能「查不到」，不可能「查到别的」）；
  ② **短参数翻译**：短名 → 契约真名（含 `区间` → 起始行＋结束行）与 fail-closed 拒；
  ③ **自动选腿**：撞上 `须走异步腿` 必须自己走 任务提交 ＋ 轮询 任务查询，
     **一次调用回结果**，且轮询有界（超时如实回「未在 N 秒内完成 ＋ 任务id」）。

判据口径：转发一律用桩（`壳.转发`），与 `测试_薄壳返回可控.py` 同做法 —— 本文件测的是
薄壳自己的编排，不是网关。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
薄壳目录 = 系统根 / "开发工具" / "薄壳"
for 路径 in (str(系统根), str(薄壳目录)):
    if 路径 not in sys.path:
        sys.path.insert(0, 路径)

import 薄壳服务 as 壳
import 工具清单 as 清单
from 公共契约.能力契约.常用意图 import (
    常见意图首选能力,
    渲染速办短表,
    速办条目,
    速办意图表,
    速办意图清单,
)


def _取工具(协议名: str):
    for 工具 in 清单.三个工具定义:
        if 工具.name == 协议名:
            return 工具
    raise AssertionError(f"工具清单缺少 {协议名}")


class 桩网关:
    """按 `操作` 回放信封，并记录每个请求体（判「转发到哪、参数是什么」）。

    `任务查询` 可以给一串（依次消费，用完后重复最后一条）：轮询腿必须能验
    「先 运行中、后 成功」这种序列。
    """

    def __init__(self, **回包) -> None:
        self.回包 = {键: (list(值) if isinstance(值, list) else [值]) for 键, 值 in 回包.items()}
        self.记录: list[dict] = []

    def 转发(self, 请求体: dict) -> dict:
        self.记录.append(请求体)
        操作 = str(请求体.get("操作", ""))
        队列 = self.回包.get(操作)
        if not 队列:
            return {"HTTP状态码": None, "信封": None, "错误码": "桩未覆盖",
                    "错误说明": f"桩没有为 操作={操作} 准备回包"}
        信封 = 队列[0] if len(队列) == 1 else 队列.pop(0)
        return {"HTTP状态码": 200, "信封": 信封, "错误码": "", "错误说明": ""}

    @property
    def 操作序列(self) -> list[str]:
        return [str(体.get("操作", "")) for 体 in self.记录]

    def 最后一次(self, 操作: str) -> dict:
        for 体 in reversed(self.记录):
            if str(体.get("操作", "")) == 操作:
                return 体
        return {}


@contextmanager
def _换转发(桩: 桩网关):
    """把 `壳.转发` 换成桩（与 `测试_薄壳返回可控.py` 同做法），退出时无条件还原。"""
    原 = 壳.转发
    壳.转发 = 桩.转发
    try:
        yield 桩
    finally:
        壳.转发 = 原


#: 网关对「只允许异步腿」能力的拒绝回包（文案取自 2026-09-24 实测回包）。
异步腿回包 = {"成功": False, "错误码": "须走异步腿",
            "错误说明": "超时秒=60 ≥ 10：该能力只允许走异步腿，同步腿（调用能力）已拒绝。"}


def _速办(意图: str, 短参数: dict, 桩: 桩网关) -> dict:
    with _换转发(桩):
        return 壳._速办({"意图": 意图, "参数": 短参数}, 2000)


class 唯一事实源测试(unittest.TestCase):
    """速办表**派生**自 `常见意图首选能力`：本组就是「逐条一致」的机器对照。"""

    def test_速办意图与常用意图表逐条一致(self):
        映射 = {意图: 能力id for 意图, 能力id, _限定 in 常见意图首选能力}
        self.assertEqual(4, len(速办意图表),
                         "速办意图应恰为 4 个（看文件/查文件/写文件/跑命令）；要扩张先改单据口径")
        for 速办名, 常用意图名, _短参数 in 速办意图表:
            self.assertIn(常用意图名, 映射,
                          f"速办 {速办名} 指向的常用意图 {常用意图名} 不在唯一事实源里")
            条目 = 速办条目(速办名)
            self.assertEqual(映射[常用意图名], 条目["首选能力"],
                             f"速办 {速办名} 的首选能力与 常见意图首选能力 不一致（派生断链）")

    def test_速办表里一个能力id都不写(self):
        """防「第二份映射表」：速办表内不得出现能力 id 形态的字面量（能力 id 必含 `.`）。

        ★ 判据口径（2026-09-24 批R·R-33 修）：原判据写成「区段里不许出现 `.`」，实测**假红**
        —— 区段里合法地含 `...`（Ellipsis 类型标注）、`如 *.py`、`posix、不带 ..` 三处点号，
        与「手抄能力 id」毫无关系（改前 21 用例里唯一的 FAIL 就是它）。改成两条**精确**判据：
          ① 对唯一事实源里每个能力 id 取值做 `assertNotIn` —— 照抄必被抓；
          ② 结构判据：不许出现引号包住的「标识符.标识符」形态字面量。
        """
        源 = (系统根 / "公共契约" / "能力契约" / "常用意图.py").read_text(encoding="utf-8")
        区段 = 源[源.index("速办意图表: tuple"):源.index("def 首选能力(")]
        for _意图, 能力id, _限定 in 常见意图首选能力:
            self.assertNotIn(能力id, 区段,
                             f"速办表里手抄了能力 id {能力id}：必须现查 常见意图首选能力")
        self.assertIsNone(
            re.search(r'["\'][\w]+\.[\w]+["\']', 区段),
            "速办表里出现了「标识符.标识符」形态的字面量（像是手抄了能力 id）")

    def test_每个意图的短参数不超过三个(self):
        for 速办名, _常用, 短参数 in 速办意图表:
            self.assertLessEqual(len(短参数), 3,
                                 f"意图 {速办名} 的短参数超过 3 个（华哥口径：尽量两句短话）")

    def test_渲染短表覆盖四个意图(self):
        表 = 渲染速办短表()
        for 速办名 in 速办意图清单():
            self.assertIn(速办名 + "=", 表)


class 短参数翻译测试(unittest.TestCase):
    """短名 → 契约真名：只做名字翻译与 `区间` 一处语法糖，其余一律 fail-closed 拒。"""

    def test_看文件_路径与区间(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        结果 = _速办("看文件", {"路径": "AGENTS.md", "区间": "1-5"}, 桩)
        self.assertTrue(结果["成功"])
        体 = 桩.最后一次("调用能力")
        self.assertEqual("文件系统支持库.文件操作.读取文件", 体["能力id"])
        self.assertEqual("AGENTS.md", 体["参数"]["文件路径"])
        self.assertEqual(1, 体["参数"]["起始行"])
        self.assertEqual(5, 体["参数"]["结束行"])
        self.assertEqual(str(系统根), 体["参数"]["项目根"],
                         "项目根 仍由薄壳自动补位（同一处腿，不另立第二处）")

    def test_看文件_不给区间就只传路径(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        _速办("看文件", {"路径": "AGENTS.md"}, 桩)
        参数 = 桩.最后一次("调用能力")["参数"]
        self.assertEqual({"文件路径": "AGENTS.md", "项目根": str(系统根)}, 参数)

    def test_查文件_模式范围文件模式(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        _速办("查文件", {"模式": "速办", "范围": "开发工具/薄壳", "文件模式": "*.py"}, 桩)
        体 = 桩.最后一次("调用能力")
        self.assertEqual("文件系统支持库.内容检索.正则搜索", 体["能力id"])
        self.assertEqual("速办", 体["参数"]["模式"])
        self.assertEqual("开发工具/薄壳", 体["参数"]["根目录"])
        self.assertEqual("*.py", 体["参数"]["文件模式"])

    def test_写文件_落到写入授权腿(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        _速办("写文件", {"路径": "开发文档/分析/x.md", "内容": "正文"}, 桩)
        体 = 桩.最后一次("调用能力")
        self.assertEqual("文件系统支持库.文件操作.写入文件", 体["能力id"],
                         "写文件必须落到写入授权腿（否则不受租约判据约束）")
        self.assertEqual("开发文档/分析/x.md", 体["参数"]["文件路径"])
        self.assertEqual("正文", 体["参数"]["内容"])

    def test_跑命令_经shell原样透传(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        _速办("跑命令", {"命令": "ls /tmp 2>&1 | head -3", "经shell": True}, 桩)
        体 = 桩.最后一次("调用能力")
        self.assertEqual("系统核心支持库.进程管理.执行命令", 体["能力id"])
        self.assertEqual("ls /tmp 2>&1 | head -3", 体["参数"]["命令"])
        self.assertIs(True, 体["参数"]["经shell"])

    def test_未知意图_回带可用意图与短参数表(self):
        桩 = 桩网关()
        结果 = _速办("瞎写", {}, 桩)
        self.assertFalse(结果["成功"])
        self.assertEqual("参数不合法", 结果["错误码"])
        self.assertEqual(速办意图清单(), 结果["可用意图"])
        self.assertIn("看文件=路径", 结果["短参数表"])
        self.assertEqual([], 桩.记录, "未知意图不得发起转发")

    def test_缺必填_当场拒且不转发(self):
        桩 = 桩网关()
        结果 = _速办("看文件", {}, 桩)  # 缺 路径（必填）
        self.assertFalse(结果["成功"])
        self.assertIn("路径", 结果["错误说明"])
        self.assertEqual(2, len(结果["该意图短参数"]), "拒的同时要回带该意图的短参数表")
        self.assertEqual([], 桩.记录, "参数不全不得发起转发")

    def test_查文件_不给范围就补项目根(self):
        """华哥口径「两句短话」：只给 模式 就该能查（`范围` 缺省＝项目根）。

        缺省值不是薄壳发明的：`公共契约/能力契约/常用意图.py` 的 速办意图表 里就写着 `.`，
        薄壳只照它补位（补位点只有 `_短参数到契约参数` 一处）。目标能力 `正则搜索` 的
        `根目录` 是必填 —— 补位就是为了让「只给 模式」这一句话真能跑通，而不是回一个「缺 范围」。
        """
        桩 = 桩网关(调用能力={"成功": True, "值": {"值": True}})
        _速办("查文件", {"模式": "速办"}, 桩)
        参数 = 桩.最后一次("调用能力")["参数"]
        self.assertEqual(".", 参数["根目录"], "范围 缺省＝项目根（`.`）")
        self.assertEqual("速办", 参数["模式"])
        self.assertEqual("文件系统支持库.内容检索.正则搜索", 桩.最后一次("调用能力")["能力id"])

    def test_缺省值只写在唯一事实源里(self):
        """防「薄壳自己内置一份缺省」：非必填项的缺省值全部取自 速办意图表。"""
        条目 = 速办条目("查文件")
        缺省 = {短名: 缺省 for 短名, _真名, _必填, 缺省, _说明 in 条目["短参数"]}
        self.assertEqual(".", 缺省["范围"])
        self.assertIsNone(缺省["文件模式"], "没有缺省的非必填项＝缺省就是「不传」")
        for 短名, _真名, 必填, 缺省, _说明 in 条目["短参数"]:
            if 必填:
                self.assertIsNone(缺省, f"必填短参数 {短名} 不该有缺省值（缺省只给非必填项）")

    def test_短参数名写错_当场拒且不转发(self):
        桩 = 桩网关()
        结果 = _速办("写文件", {"路径": "a.md", "正文": "x"}, 桩)  # 应为 内容
        self.assertFalse(结果["成功"])
        self.assertIn("内容", 结果["短参数表"])
        self.assertIn("正文", 结果["错误说明"])
        self.assertEqual([], 桩.记录)

    def test_区间写错_当场拒且不转发(self):
        桩 = 桩网关()
        结果 = _速办("看文件", {"路径": "a.md", "区间": "从头到尾"}, 桩)
        self.assertFalse(结果["成功"])
        self.assertIn("起始-结束", 结果["错误说明"])
        self.assertEqual([], 桩.记录)


class 自动选腿测试(unittest.TestCase):
    """最大价值点：撞上 `须走异步腿` 必须**一次调用**把答案拿回来（不抛回给调用方）。"""

    def test_须走异步腿_自动改走任务腿一次回结果(self):
        桩 = 桩网关(
            调用能力=异步腿回包,
            任务提交={"成功": True, "值": {"任务id": "t-1", "状态": "等待中"}},
            任务查询=[
                {"成功": True, "值": {"任务id": "t-1", "状态": "运行中"}},
                {"成功": True, "值": {"任务id": "t-1", "状态": "成功",
                                    "结果": {"退出码": 0, "标准输出": "ok\n", "错误输出": ""}}},
            ],
        )
        结果 = _速办("跑命令", {"命令": "ls /tmp 2>&1 | head -3", "经shell": True}, 桩)
        self.assertTrue(结果["成功"], f"速办应一次调用回结果：{结果}")
        self.assertEqual({"退出码": 0, "标准输出": "ok\n", "错误输出": ""}, 结果["值"])
        self.assertEqual("t-1", 结果["任务id"])
        self.assertEqual(["调用能力", "任务提交", "任务查询", "任务查询"], 桩.操作序列)
        self.assertNotIn("须走异步腿", json.dumps(结果, ensure_ascii=False),
                         "不得把 须走异步腿 原样抛回调用方")
        self.assertEqual("ls /tmp 2>&1 | head -3", 桩.最后一次("任务提交")["参数"]["命令"],
                         "任务提交带的入参与同步腿一字不差")
        self.assertIn("耗时秒", 结果, "要给出任务id与耗时")

    def test_轮询超时_如实回报不无限等(self):
        原上限, 原间隔 = 壳.速办轮询上限秒, 壳.速办轮询间隔秒
        壳.速办轮询上限秒, 壳.速办轮询间隔秒 = 0.05, 0.005
        try:
            桩 = 桩网关(
                调用能力=异步腿回包,
                任务提交={"成功": True, "值": {"任务id": "t-9", "状态": "等待中"}},
                任务查询={"成功": True, "值": {"任务id": "t-9", "状态": "运行中"}},
            )
            结果 = _速办("跑命令", {"命令": "sleep 600"}, 桩)
        finally:
            壳.速办轮询上限秒, 壳.速办轮询间隔秒 = 原上限, 原间隔
        self.assertFalse(结果["成功"])
        self.assertEqual("速办轮询超时", 结果["错误码"])
        self.assertEqual("t-9", 结果["任务id"], "超时也要回任务id（好让调用方续取）")
        self.assertIn("未在", 结果["错误说明"])
        self.assertIn("任务查询", 结果["错误说明"])

    def test_任务终态失败_错误码取任务自己的(self):
        桩 = 桩网关(
            调用能力=异步腿回包,
            任务提交={"成功": True, "值": {"任务id": "t-2", "状态": "等待中"}},
            任务查询={"成功": True, "值": {"任务id": "t-2", "状态": "失败",
                                       "错误码": "执行失败", "错误说明": "退出码 1"}},
        )
        结果 = _速办("跑命令", {"命令": "false"}, 桩)
        self.assertFalse(结果["成功"])
        self.assertEqual("执行失败", 结果["错误码"])
        self.assertEqual("t-2", 结果["任务id"])

    def test_任务提交失败_如实回报不掩盖(self):
        桩 = 桩网关(调用能力=异步腿回包,
                   任务提交={"成功": False, "错误码": "资源繁忙", "错误说明": "队列满"})
        结果 = _速办("跑命令", {"命令": "ls"}, 桩)
        self.assertFalse(结果["成功"])
        self.assertEqual("资源繁忙", 结果["错误码"])
        self.assertIn("任务提交", 结果["错误说明"])

    def test_终态集合与内核常量一致(self):
        try:
            from 运行核心.任务调度.任务进程_对象 import (
                任务状态_崩溃,
                任务状态_失败,
                任务状态_已取消,
                任务状态_成功,
                任务状态_超时,
            )
        except ImportError as 错误:  # pragma: no cover - 内核不可见时如实跳过
            self.skipTest(f"内核任务模块不可导入（{错误}）")
        内核终态 = {任务状态_成功, 任务状态_失败, 任务状态_已取消, 任务状态_超时, 任务状态_崩溃}
        self.assertEqual(内核终态, set(壳.速办任务终态),
                         "薄壳 `速办任务终态` 与内核状态常量漂移（轮询会停错地方）")


class 未传速办行为不变测试(unittest.TestCase):
    """判据 5：不传 `速办` 时，既有腿的转发体**逐字不变**。"""

    def test_非速办操作转发体逐字同形(self):
        桩 = 桩网关(调用能力={"成功": True, "值": {"x": 1}})
        with _换转发(桩):
            结果 = 壳._调用能力({"操作": 0,
                              "能力id": "系统核心支持库.系统信息.获取CPU信息",
                              "参数": {"项目根": str(系统根)}})
        self.assertTrue(结果["成功"])
        self.assertEqual(
            {"操作": "调用能力", "能力id": "系统核心支持库.系统信息.获取CPU信息",
             "参数": {"项目根": str(系统根)}},
            桩.最后一次("调用能力"),
            "既有腿的转发体不得因新增 速办 而变形（多键/改键都算破坏）")

    def test_工具面暴露速办与意图(self):
        工具 = _取工具("capability_call")
        属性 = 工具.inputSchema["properties"]
        # 2026-09-24：`操作` 由中文字符串枚举改成整数码 —— 速办 的码是 7，
        # 判据跟着从 enum 成员改成码表成员（工具面必须仍够得到速办，否则就是死腿）。
        self.assertEqual("速办", 壳.操作码表[7], "速办 的整数码必须是 7")
        self.assertEqual("integer", 属性["操作"]["type"])
        self.assertIn("速办", 属性["操作"]["description"])
        self.assertIn("意图", 属性,
                      "顶层 schema 是 additionalProperties=false：不声明 意图 会被当场拒")
        for 意图 in 速办意图清单():
            self.assertIn(意图, 属性["意图"]["description"],
                          f"工具面未暴露速办意图 {意图}（agent 猜不到）")

    def test_速办在操作白名单里(self):
        self.assertIn("速办", 壳.薄壳允许操作, "操作白名单是 fail-closed 的唯一闸门")


if __name__ == "__main__":
    unittest.main()
