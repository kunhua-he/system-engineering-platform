"""调用参数账 · 入参样例的**凭证不落库**回归（2026-09-23 安全收口）。

背景：改前 `入参样例` 把**任何键**的真实取值都写进 SQLite，实测库里存在明文
`api_key: sk-…`、`密钥b64` 等，且 `查常用参数` 会原样读回 ⇒ 明文凭证可回放。

本文件的三拍（照仓规「每处修复必须配反向验证」）：
  ① 正向：敏感键名只落占位、普通键仍留真实值（**功能不能被顺手砍掉**）；
  ② 端到端：真写一次账，直接读库的 `样例` 列，确认无明文凭证；
  ③ 反向：把**唯一腿的表**（`公共契约/基础类型/字段名册.py::敏感键名表`）清空，同一份
     入参**必须**把凭证写进库 —— 证明「不落库」是被这条策略真正驱动的，**判据非恒真**。
     （2026-09-26：`调用账本` 已删掉自持的 18 项 `敏感键名` 表、转调**同层唯一腿**
     `公共契约.基础类型.字段名册.是敏感键名`；故反向验证的 patch 目标随之改为
     **唯一腿的表** —— 再 patch `调用账本.敏感键名` 已不存在，且即便留一个指向唯一腿的
     模块级别名也不驱动判定，只会变成假绿。）
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from 公共契约.基础类型 import 字段名册
from 公共契约.诊断 import 调用账本
from 公共契约.诊断.调用账本 import 入参样例, 调用参数账

#: 一条带明文凭证的入参（键名形态取自实测库里真实存在的那几种）。
带凭证入参 = {
    "api_key": "sk-461fc8a38e2d602f7e0c80876f6cf6a2PLAINTEXT",
    "密钥b64": "AAECAwQFBgcICQoLDA0ODw==PLAINTEXT",
    "密码": "P@ssw0rd-明文-PLAINTEXT",
    "远端": "origin",
    "超时秒": 120,
}


class 账本脱敏测试(unittest.TestCase):
    def test_敏感键只落占位且普通键保留(self) -> None:
        """① 正向：凭证键换成占位，非凭证键照旧（照抄样例这个功能不能废）。"""
        样例 = 入参样例(带凭证入参)
        for 键 in ("api_key", "密钥b64", "密码"):
            self.assertIn(键, 样例, f"{键} 应仍在键表里（只换值，不删键）")
        self.assertNotIn("PLAINTEXT", 样例, "凭证值不得出现在样例里")
        self.assertIn("已省略", 样例, "凭证键的值应替换成占位")
        self.assertIn("origin", 样例, "普通键的真实值必须保留")
        self.assertIn("120", 样例, "普通键的真实值必须保留")

    def test_改前漏项现已由唯一腿覆盖(self) -> None:
        """①b 回归：改前自持 18 项表**漏**的键名，现在必须被掩码（本批 T1 的真正判据）。

        漏项清单（逐项比对 `字段名册.敏感键名表`(24 项) 与改前 `调用账本.敏感键名`(18 项)）：
        `凭据`/`授权码`/`签名`/`连接串`/`cookie`/裸 `key` —— 改前这些键名的**真实值会
        明文入库**，且经 `查常用参数` 原样读回。缺了本用例，收口就等于没验。
        """
        漏项入参 = {
            "凭据": "cred-PLAINTEXT",
            "连接串": "postgres://u:p@h/db-PLAINTEXT",
            "签名": "sig-PLAINTEXT",
            "授权码": "code-PLAINTEXT",
            "cookie": "sess-PLAINTEXT",
            "key": "k-PLAINTEXT",
        }
        样例 = 入参样例(漏项入参)
        self.assertNotIn("PLAINTEXT", 样例, f"改前漏项仍明文入库：{样例}")
        self.assertEqual(样例.count("已省略"), len(漏项入参), "每个漏项键都应换占位")

    def test_端到端落库的样例列无明文凭证(self) -> None:
        """② 端到端：真写一次账 → 直读库的 样例 列。"""
        with tempfile.TemporaryDirectory() as 临时:
            账 = 调用参数账(库路径=Path(临时) / "账.sqlite3")
            self.assertTrue(账.记一次调用("探针.带凭证", 带凭证入参), "记一次调用应落库成功")
            库 = sqlite3.connect(str(Path(临时) / "账.sqlite3"))
            try:
                行 = 库.execute("SELECT 样例 FROM 调用参数账").fetchall()
            finally:
                库.close()
        self.assertEqual(len(行), 1, "应恰好一条账")
        落库样例 = str(行[0][0])
        self.assertNotIn("PLAINTEXT", 落库样例, f"明文凭证落库了：{落库样例}")
        self.assertIn("origin", 落库样例, "普通键应照旧落库")

    def test_反向_清空敏感键表则凭证必落库(self) -> None:
        """③ 反向（判据非恒真）：策略一撤，凭证**必须**落库。

        这一拍是「这条判据真的在起作用」的证明：若本用例也通过（凭证仍被省略），
        说明省略来自别处（例如恒真短路），本修复就是假的。

        patch 目标是**唯一腿的表**（`字段名册.敏感键名表`），不是 `调用账本` 里的名字：
        `是敏感键名` 每次调用都读该模块全局，故清空它必然让判定恒假 —— 这条路径正是
        生产路径（`_样例值` → `是敏感键名` → `敏感键名表`），比 patch 一个本地名字更强。
        """
        原表 = 字段名册.敏感键名表
        字段名册.敏感键名表 = ()
        try:
            样例 = 入参样例(带凭证入参)
        finally:
            字段名册.敏感键名表 = 原表
        self.assertIn("PLAINTEXT", 样例, "撤掉策略后凭证仍未落库 ⇒ 判据恒真，本修复无效")

    def test_空入参与非映射不炸(self) -> None:
        self.assertEqual(入参样例({}), "")
        self.assertEqual(入参样例(None), "")
        self.assertEqual(入参样例("不是映射"), "")

    def test_样例串仍有界(self) -> None:
        """长文本仍走 `_压值` 折叠，整串不超上限 —— 脱敏改动没破坏原有有界性。"""
        样例 = 入参样例({"正文": "长" * 5000, "备注": "x" * 5000})
        self.assertLessEqual(len(样例), 调用账本.样例整串上限 + 20)
        self.assertNotIn("长" * 200, 样例, "超长文本应被折叠")


if __name__ == "__main__":
    unittest.main()
