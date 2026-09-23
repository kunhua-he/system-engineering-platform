# -*- coding: utf-8 -*-
"""交付收尾技能「网关腿」守护测试：静态腿断言 + 经 40007 真实调用。

背景（缺陷 I-4）：本技能原形态 `import sqlite3` 自己 `sqlite3.connect()` 直改
底座运行库 `协作状态`/`能力占用` 与平台控制面 `占用租约` 三张表，绕过唯一网关，
撞平台 7.4 / 7.8 / 8.2 条。修法 = 全部动作改经注入模块 `技能底座能力` 走唯一网关。

两条判据：
- **静态腿**：脚本源码里不得出现 `sqlite3`/直连库/SQL 关键字，必须有 `调用底座能力` 与
  `技能底座能力` 导入；`依赖.json` 的 `可调能力` 四条与脚本内常量逐字一致。
- **网关真实腿**：经 40007 真实调用 `技能库.受控执行.运行技能包`（夹具复制到临时目录，
  不碰仓库内任何真实库与真实租约），正向放行 + 四类门禁阻断 + 白名单缺项反向断言。

网关不可达（未常驻/凭证缺失）时按有理由跳过（reason 明确），不伪装通过。
"""

from __future__ import annotations

import json
import plistlib
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

技能包目录 = 系统根 / "技能库" / "技能" / "交付收尾"
脚本路径 = 技能包目录 / "scripts" / "交付收尾.py"
依赖路径 = 技能包目录 / "依赖.json"
技能根目录 = 系统根 / "技能库" / "技能"
网关地址 = "http://127.0.0.1:40007"
凭证变量名 = "系统库网关凭证"
凭证来源 = Path.home() / "Library" / "LaunchAgents" / "com.huashi.gateway-40007.plist"

必须白名单 = [
    "数据库连接支持库.SQLite数据库.查询运行态",
    "数据库连接支持库.SQLite数据库.写入运行态",
    "平台控制面.平台状态.查询记录",
    "平台控制面.能力目录.释放文件租约",
]


def _读凭证() -> str:
    """从 launchd plist 读网关凭证；读不到返回空串（调用方按跳过处理）。"""
    try:
        with 凭证来源.open("rb") as 句柄:
            配置 = plistlib.load(句柄)
    except (OSError, plistlib.InvalidFileException):
        return ""
    环境 = 配置.get("EnvironmentVariables") or {}
    return str(环境.get(凭证变量名) or "").strip()


class 交付收尾静态腿测试(unittest.TestCase):
    """脚本源码级判据：唯一调用腿是网关，没有第二执行腿。"""

    def setUp(self) -> None:
        self.源码 = 脚本路径.read_text(encoding="utf-8")

    def test_脚本不含直连库与SQL(self):
        """回归 I-4：`import sqlite3` / `connect(` / 表名 SQL 一律不得再出现。"""
        for 禁词 in ("sqlite3", "sqlite", "connect(", "INSERT INTO", "UPDATE ", "SELECT "):
            self.assertNotIn(禁词, self.源码, f"脚本仍含直连库/裸 SQL 片段：{禁词}")

    def test_脚本只经注入模块调能力(self):
        """唯一调用腿：`from 技能底座能力 import 调用底座能力`，且真的在调。"""
        self.assertIn("from 技能底座能力 import 调用底座能力", self.源码)
        self.assertIn("调用底座能力(", self.源码)

    def test_脚本不导入项目模块(self):
        """平台 7.8 条：正式代码只处理统一结果，不导入任何实现源码。"""
        for 前缀 in ("import 支持库", "import 模块库", "import 平台控制面",
                   "import 运行核心", "import 后端核心", "from 支持库", "from 模块库",
                   "from 平台控制面", "from 运行核心", "from 后端核心"):
            self.assertNotIn(前缀, self.源码)

    def test_静态审计器放行本脚本(self):
        """用底座自己的受控执行 AST 审计器复验：手工跑一遍也得过。"""
        from 技能库.后端.技能库.实现.技能库 import 审计脚本源码

        违规 = 审计脚本源码(self.源码, (), frozenset({"技能底座能力"}))
        self.assertEqual(list(违规), [], f"AST 审计未通过：{违规}")

    def test_依赖声明与脚本常量逐字一致(self):
        """`依赖.json` 的可调能力四条 = 脚本内 必须授权能力 四条（不做漂移）。"""
        依赖 = json.loads(依赖路径.read_text(encoding="utf-8"))
        self.assertEqual(依赖.get("标准库", []).count("sqlite3"), 0, "依赖.json 不该再声明 sqlite3")
        self.assertEqual(依赖.get("项目模块"), [])
        self.assertEqual(依赖.get("第三方"), [])
        self.assertEqual(依赖.get("可调能力"), 必须白名单)
        self.assertEqual(依赖.get("注入模块"), ["技能底座能力"])
        for 能力id in 必须白名单:
            self.assertIn(f'"{能力id}"', self.源码, f"脚本内缺能力 id 常量：{能力id}")


class 交付收尾网关腿测试(unittest.TestCase):
    """经 40007 真实调用；夹具复制到临时目录，绝不碰真实库与真实租约。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.凭证 = _读凭证()
        cls.临时目录 = tempfile.mkdtemp(prefix="交付收尾网关腿_")
        夹具源 = 技能包目录 / "验证夹具"
        夹具目标 = Path(cls.临时目录) / "验证夹具"
        shutil.copytree(夹具源, 夹具目标)
        # ★ 夹具副本要能改，先解掉复制过来的**内核只读标志**（`copytree` 默认 `copy2`
        #   会连 `st_flags` 一起复制）：否则下面删残留锁文件与重建租约存储都被内核拒
        #   （实测 `Operation not permitted`）。唯一实现见锁模块。
        from 公共契约.运行时.仓库只读锁 import 对齐目标锁态
        对齐目标锁态(夹具目标)
        for 残留 in (".文件租约.lock", ".文件改动日志.lock"):
            (夹具目标 / 残留).unlink(missing_ok=True)
        cls.夹具 = 夹具目标
        # 原始夹具里可能没有文件租约存储：按 HEAD 布局补一份（只装夹具行）。
        cls._重建文件租约存储()

    @classmethod
    def _重建文件租约存储(cls) -> None:
        def 租约(号: str, 路径: str, 所有者: str, 任务: str, 状态: str = "活跃") -> dict:
            return {"租约id": 号, "键": f"文件::{路径}", "路径": 路径, "所有者": 所有者,
                    "任务": 任务, "存储标签": "", "心跳": 1768000000.0,
                    "申请时间": "2026-09-15 10:00:00", "过期时间": 1768003000.0,
                    "状态": 状态, "释放时间": "", "释放原因": "",
                    "内容指纹": "sha256:夹具", "已声明指纹": "", "留言": []}

        存储 = {
            "文件::技能库/技能/交付收尾/SKILL.md": 租约(
                "b2c10de0-文件-0001", "技能库/技能/交付收尾/SKILL.md", "b2c10de000000001", "批次B2"),
            "文件::技能库/技能/验证编排/SKILL.md": 租约(
                "b2c10de0-他人-文件", "技能库/技能/验证编排/SKILL.md", "a1a1a1a1a1a1a1a1", "别人的包"),
        }
        (cls.夹具 / "文件租约.json").write_text(
            json.dumps(存储, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.临时目录, ignore_errors=True)

    def _网关(self, 体: dict) -> dict:
        地址 = f"{网关地址}/" + urllib.parse.quote("网关/调用")
        请求 = urllib.request.Request(
            地址, data=json.dumps(体, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.凭证}, method="POST")
        with urllib.request.urlopen(请求, timeout=60) as 响应:
            return json.loads(响应.read().decode("utf-8"))

    def _跑技能(self, 技能参数: dict, 白名单: list[str] | None = None) -> dict:
        """真实调用 技能库.受控执行.运行技能包；网关不可达/凭证缺失即跳过。"""
        if not self.凭证:
            self.skipTest(f"未读到网关凭证（{凭证来源} 的 EnvironmentVariables.{凭证变量名}）")
        夹具参数 = {"运行库路径": str(self.夹具 / "底座运行.db"),
                 "控制面库路径": str(self.夹具 / "权威状态.db"),
                 "反馈文件": str(self.夹具 / "反馈.jsonl"),
                 "验证历史文件": str(self.夹具 / "验证历史.jsonl")}
        参数 = dict(夹具参数)
        参数.update(技能参数)
        try:
            return self._网关({
                "操作": "调用能力", "能力id": "技能库.受控执行.运行技能包",
                "参数": {"技能根目录": str(技能根目录), "能力标识": "技能.交付收尾",
                       "可调能力白名单": 白名单 if 白名单 is not None else 必须白名单,
                       "项目根目录": str(技能根目录), "参数": 参数}})
        except (urllib.error.URLError, ConnectionError, OSError) as 错误:
            self.skipTest(f"40007 网关不可达，无法做真实网关腿验证：{错误}")

    def _内层(self, 回执: dict) -> dict:
        """受控执行把脚本回执摊平进 值 且强制外层成功=true；统一取出内层判据。"""
        self.assertTrue(回执.get("成功"), f"外层调用失败：{回执.get('错误码')} {回执.get('错误说明')}")
        值 = 回执.get("值") or {}
        内层 = 值.get("值")
        return 内层 if isinstance(内层, dict) else 值

    def _断言成功(self, 内层: dict) -> None:
        """成功判据：成功回执里没有 `错误码` 键（失败回执才有）；有即失败并回带原文。"""
        self.assertNotIn("错误码", 内层, f"脚本拒绝了本次收口：{内层}")

    def test_正向_写终态并释放文件租约(self):
        """正向：生命周期置完成，本开工id 的文件租约由活跃转已释放，账本标终态。"""
        回执 = self._跑技能({"开工id": "b2c10de000000001",
                     "五件套路径": "工程缓存/交付证据/b2c10de000000001",
                     "结论": "交付收尾网关腿正向验收"})
        内层 = self._内层(回执)
        self._断言成功(内层)
        self.assertEqual(内层.get("生命周期"), "完成")
        self.assertEqual(内层.get("反馈门禁"), "通过")
        self.assertEqual(内层.get("证据指纹"), "匹配")
        self.assertEqual(内层["资源释放"]["文件租约"]["释放数量"], 1)
        self.assertIn("能力面缺口", 内层["资源释放"])

        存储 = json.loads((self.夹具 / "文件租约.json").read_text(encoding="utf-8"))
        self.assertEqual(存储["文件::技能库/技能/交付收尾/SKILL.md"]["状态"], "已释放")
        self.assertTrue(存储["文件::技能库/技能/交付收尾/SKILL.md"]["释放原因"].startswith("收口："))
        # 反向断言：别人的活跃租约不许被碰。
        self.assertEqual(存储["文件::技能库/技能/验证编排/SKILL.md"]["状态"], "活跃")

        记录 = self._查协作状态("b2c10de000000001")
        self.assertEqual(记录["生命周期"], "完成")
        self.assertEqual(记录["状态"], "完成")
        self.assertEqual(记录["收口结论"], "交付收尾网关腿正向验收")
        self.assertEqual(记录["worktree路径"], "交付收尾/验证夹具/工作区/已通过")
        self.assertEqual(self._查账本("文件系统支持库.文本读取.读取文本"), "已释放")

    def test_未反馈阻断不写终态(self):
        内层 = self._内层(self._跑技能({"开工id": "b2c10de000000002",
                          "五件套路径": "工程缓存/交付证据/b2c10de000000002",
                          "结论": "未反馈阻断验收"}))
        self.assertFalse(内层.get("成功"))
        self.assertEqual(内层.get("错误码"), "未反馈阻断")
        self.assertEqual(内层.get("阻断标记"), ["未反馈"])
        self.assertEqual(self._查协作状态("b2c10de000000002")["生命周期"], "创建")

    def test_证据指纹不匹配阻断(self):
        内层 = self._内层(self._跑技能({"开工id": "b2c10de000000003",
                          "五件套路径": "工程缓存/交付证据/b2c10de000000003",
                          "结论": "证据不匹配验收"}))
        self.assertFalse(内层.get("成功"))
        self.assertEqual(内层.get("错误码"), "证据不匹配")
        self.assertEqual(内层.get("证据指纹"), "deadbeefdeadbeef")
        self.assertEqual(self._查协作状态("b2c10de000000003")["生命周期"], "创建")

    def test_未登记阻断(self):
        内层 = self._内层(self._跑技能({"开工id": "b2c10de000000004",
                          "五件套路径": "工程缓存/交付证据/b2c10de000000004",
                          "结论": "未登记验收"}))
        self.assertFalse(内层.get("成功"))
        self.assertEqual(内层.get("错误码"), "任务不存在")
        self.assertEqual(内层.get("阻断标记"), ["未登记"])

    def test_释放开关关闭只写终态(self):
        内层 = self._内层(self._跑技能({"开工id": "b2c10de000000005",
                          "五件套路径": "工程缓存/交付证据/b2c10de000000005",
                          "结论": "释放开关关闭验收", "释放资源": False}))
        self._断言成功(内层)
        self.assertEqual(内层.get("生命周期"), "完成")
        self.assertEqual(内层["资源释放"].get("跳过"), "释放资源=false，未释放占用租约")
        self.assertEqual(self._查协作状态("b2c10de000000005")["生命周期"], "完成")

    def test_非法开工id读库前拒绝(self):
        内层 = self._内层(self._跑技能({"开工id": "XYZ", "五件套路径": "工程缓存/交付证据/坏id",
                          "结论": "非法id验收"}))
        self.assertFalse(内层.get("成功"))
        self.assertEqual(内层.get("错误码"), "开工id无效")

    def test_白名单缺项反向验证_只剩网关一条腿(self):
        """把网关腿拆掉（白名单缺两条）→ 动作必须失败，不得回落到任何旁路。

        旧直连形态读表不经过网关，**不会**产生 `能力不在白名单`；这条反验证明
        技能侧除唯一网关外没有第二条腿。
        """
        内层 = self._内层(self._跑技能(
            {"开工id": "b2c10de000000001", "五件套路径": "工程缓存/交付证据/白名单缺项反向验证",
             "结论": "白名单缺项反向验证"},
            白名单=["数据库连接支持库.SQLite数据库.查询运行态",
                 "数据库连接支持库.SQLite数据库.写入运行态"]))
        释放 = 内层["资源释放"]
        self.assertFalse(释放.get("成功"))
        self.assertIn("能力不在白名单", 释放.get("错误说明", ""))
        self.assertIn("平台控制面.平台状态.查询记录", 释放.get("错误说明", ""))

    # ---- 只读核对工具（直接读夹具库，属测试侧取证，不是生产调用腿） ----

    def _查协作状态(self, 开工id: str) -> dict:
        import sqlite3

        连接 = sqlite3.connect(str(self.夹具 / "底座运行.db"))
        连接.row_factory = sqlite3.Row
        try:
            行 = 连接.execute("SELECT * FROM 协作状态 WHERE work_id = ?", (开工id,)).fetchone()
            return dict(行) if 行 is not None else {}
        finally:
            连接.close()

    def _查账本(self, 能力id: str) -> str:
        import sqlite3

        连接 = sqlite3.connect(str(self.夹具 / "底座运行.db"))
        try:
            行 = 连接.execute("SELECT 状态 FROM 能力占用 WHERE 能力id = ?", (能力id,)).fetchone()
            return str(行[0]) if 行 else ""
        finally:
            连接.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
