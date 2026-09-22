"""装配期契约名序闸门：真判据（注册实现 vs 真契约）必须 fail-closed。

背景（2026-09-23 判据唯一化）：
`公共契约/能力契约/契约.py:125 能力实现.声明一致` 本就是「**注册 vs 真契约**」的真判据，
但它的唯一生产调用点在发布门禁里「只报」；装配期**从不调它**。于是 50 份各包
`__init__.py` 里的 `_校验参数名序` 各自做「**镜像 vs 名序**」的**同文件自比** ——
两份同源、一起写错即互证「一致」，从不与真契约（`能力契约/参数契约.json`）比。
本测试钉住：装配期现在**真执行**该判据，不一致即拒该包装配（fail-closed）。

三拍留证（判据在 ≠ 判据覆盖）：
1. 正向：注册名序 == 真契约名序 ⇒ 装配通过、能力可用；
2. 反向：注册名序被改乱 ⇒ 装配必须拒该包（跳过 + 不留半装配能力）；
3. 盲区：旧「同文件自比」判据对上述错序恒绿（镜像与名序同源），真判据立刻红。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.运行核心.测试_装配期契约名序闸门 -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力实现, 能力注册表, 能力声明
from 运行核心.加载器.生命周期管理.管理器 import 装配系统



def _参数表(名序: list[str]) -> list[dict]:
    return [{"名称": 名, "类型": "文本型"} for 名 in 名序]


def 写包(根: Path, 目录名: str, 能力id: str, *,
        注册名序: list[str], 契约名序: list[str]) -> None:
    """写一个包：包声明（真契约投影）/ 能力契约（真契约）/ 入口（注册实现）。

    `契约名序` 同时写进 包声明 与 能力契约（两者是同一事实源的两面）；
    `注册名序` 写进入口的 `能力实现(... 参数=...)`。两者不一致即本闸门要抓的漂移。
    """
    包id = f"闸门.{目录名}"
    目录 = 根 / "支持库" / 目录名
    目录.mkdir(parents=True, exist_ok=True)
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": 包id, "名称": 目录名, "类型": "支持库", "版本": "1.0.0",
        "入口": "入口.py", "依赖": [],
        "能力": [{"能力id": 能力id, "名称": 能力id.split(".")[-1],
                 "参数": _参数表(契约名序), "返回": "结果型"}],
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
    (目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
        "契约版本": "1.0.0",
        "能力契约": [{"能力id": 能力id, "版本": "1.0.0", "说明": 目录名,
                    "参数": _参数表(契约名序),
                    "返回": {"类型": "结果型"}, "错误码": [], "调用示例": "{}"}],
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "入口.py").write_text(
        "from 公共契约.能力契约.契约 import 能力实现\n"
        "def 注册能力(注册表):\n"
        "    注册表.注册(能力实现(\n"
        f"        能力id={能力id!r}, 包id={包id!r},\n"
        f"        实现函数=lambda: 'ok', 参数={_参数表(注册名序)!r},\n"
        "        返回='结果型'))\n",
        encoding="utf-8")


class 装配期契约名序闸门测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="闸门_"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时, ignore_errors=True)

    def _写健康包(self) -> None:
        写包(self.临时, "健康", "闸门.健康.正常",
             注册名序=["甲", "乙"], 契约名序=["甲", "乙"])

    def _装配(self, 注册表: 能力注册表 | None = None):
        return 装配系统(self.临时 / "支持库", self.临时 / "模块库", 注册表)

    def _跳过含(self, 结果, 片段: str) -> bool:
        return any(片段 in 告警 for 告警 in 结果.跳过包列表)

    def test_正向_注册名序与真契约一致_装配通过(self):
        """注册名序逐字等于真契约名序 ⇒ 装配期闸门放行、能力可用。"""
        self._写健康包()
        注册表 = 能力注册表()
        结果 = self._装配(注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.跳过包列表, [], str(结果.跳过包列表))
        self.assertEqual(注册表.能力id列表, ["闸门.健康.正常"])

    def test_反向_注册名序被改乱_装配必须拒该包(self):
        """注册名序与真契约相反 ⇒ 该包装配必须被拒（跳过 + 不留半装配能力）。

        修前：装配期从不与真契约比 ⇒ 装配**静默成功**、错序能力照常注册（本测试红）。
        修后：装配期真执行 能力实现.声明一致 ⇒ 必须红。
        """
        self._写健康包()
        写包(self.临时, "错序", "闸门.错序.能力",
             注册名序=["乙", "甲"], 契约名序=["甲", "乙"])
        注册表 = 能力注册表()
        结果 = self._装配(注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))  # 健康包照常装配
        self.assertTrue(self._跳过含(结果, "闸门.错序"),
                        f"错序包必须被跳过，实得: {结果.跳过包列表}")
        self.assertEqual(注册表.能力id列表, ["闸门.健康.正常"],
                         "被拒的包不得留下半装配能力")

    def test_反向_声明名序与注册不一致_装配必须拒该包(self):
        """真契约/包声明名序与注册实现不一致 ⇒ 该包装配必须被拒。"""
        self._写健康包()
        写包(self.临时, "声明错", "闸门.声明错.能力",
             注册名序=["甲", "乙"], 契约名序=["乙", "甲"])
        注册表 = 能力注册表()
        结果 = self._装配(注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertTrue(self._跳过含(结果, "闸门.声明错"),
                        f"不一致包必须被跳过，实得: {结果.跳过包列表}")
        self.assertEqual(注册表.能力id列表, ["闸门.健康.正常"])

    def test_盲区_旧同文件自比判据对错序恒绿而真判据判红(self):
        """钉住「静默放过」的机理：镜像与名序同源 ⇒ 旧自比判据恒绿。

        旧 `_校验参数名序(镜像, 名序)` 的两份输入都由同一次手写产生，一起写错即
        互证「一致」；而真判据 `能力实现.声明一致(真契约声明)` 立刻红。
        """
        注册名序 = ["乙", "甲"]
        契约名序 = ["甲", "乙"]
        镜像 = _参数表(注册名序)
        名序 = list(注册名序)
        # 旧判据（镜像 vs 名序，两份同源）：恒绿
        self.assertEqual([项["名称"] for 项 in 镜像], list(名序),
                         "镜像与名序同源：旧自比判据对这类漂移恒绿")
        # 真判据（注册实现 vs 真契约声明）：必须红
        实现 = 能力实现(能力id="闸门.盲区.能力", 包id="闸门.盲区",
                     实现函数=lambda: None, 参数=镜像, 返回="结果型")
        真声明 = 能力声明(能力id="闸门.盲区.能力", 参数=_参数表(契约名序),
                        返回="结果型")
        self.assertFalse(实现.声明一致(真声明),
                         "真契约的错序必须能被 能力实现.声明一致 看出")


if __name__ == "__main__":
    unittest.main()
