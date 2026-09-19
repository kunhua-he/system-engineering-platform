"""依赖分两段派生：反向验证（故意弄坏必红 / 还原必绿）。

覆盖口径（`支持库/适配层/说明/依赖分两段.md` 的「五、判定依据汇总」）：
  ① 服务型环境依赖（现场出现 postgresql:// 等 ⇒ 必须在 服务型环境依赖.json 声明六要素）；
  ② 内部件依赖（内部件不建 依赖锁.json ⇒ 依赖登记在 内部件依赖声明.json）；
  ③ 该建声明没建声明（现场有外部依赖证据却两侧都无）；
  ④ 逐项类别（锁项无 import 现场 ⇒ 无法现场证实 ⇒ 判红）。

为什么必须带这一组：审计 S0-1/S0-3/S1-2 的共同形态是「判据缺位或判据不判红」——
本测试对每条新判据都给「故意弄坏 → 必红」与「还原 → 必绿」两拍，
判据链一旦被改回沉默放行，本测试当场红。

全部夹具建在临时目录，**不写仓库任何文件**（不含 适配层根 的真实路径）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 开发工具.依赖派生 import 生成依赖分两段 as 派生


class 依赖派生夹具:
    """在临时目录里搭一个假的 适配层根，只放本用例要判的件。"""

    def __init__(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.根 = Path(self._临时.name)
        self.原件 = (派生.适配层根, 派生.登记路径, 派生.清单路径)

    def 装(self) -> None:
        派生.适配层根 = self.根
        派生.登记路径 = self.根 / "依赖登记.json"
        派生.清单路径 = self.根 / "说明" / "依赖分两段.md"

    def 卸(self) -> None:
        派生.适配层根, 派生.登记路径, 派生.清单路径 = self.原件
        self._临时.cleanup()

    def 写件(self, 相对: str, 内容: str) -> Path:
        路径 = self.根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
        return 路径

    def 写声明(self, 文件名: str, 内容: dict) -> None:
        self.写件(文件名, json.dumps(内容, ensure_ascii=False, indent=2))

    def 报警(self) -> list[str]:
        return 派生.汇总()["报警"]


def 六要素服务(**覆盖) -> dict:
    项 = {
        "名称": "PostgreSQL",
        "版本": "14.24",
        "入口": "/opt/homebrew/bin/postgres",
        "端口": 5432,
        "健康探针": "pg_isready -h 127.0.0.1 -p 5432",
        "启停": "brew services start postgresql@14",
        "降级语义": "服务不可达 → 错误码「连接失败」，fail-closed",
    }
    项.update(覆盖)
    return 项


class 服务型环境依赖判据(unittest.TestCase):
    """口径 ①：现场有连接远端服务的证据 ⇒ 必须有六要素声明；两侧都不许单边存在。"""

    def setUp(self) -> None:
        self.夹具 = 依赖派生夹具()
        self.夹具.装()
        # 件内出现 postgresql:// 字面量 ⇒ 现场证据成立
        self.夹具.写件("psycopg提供者/实现/提供者.py",
                    "连接串格式说明 = \"仅支持 postgresql:// 或 postgres:// 格式连接串\"\n")

    def tearDown(self) -> None:
        self.夹具.卸()

    def test_无声明必红(self) -> None:
        """弄坏：现场有连接证据、声明件缺失 ⇒ 必须报警（原缺口正是这里的沉默放行）。"""
        警 = self.夹具.报警()
        self.assertTrue(any("服务连接字面量" in 条 and "没有该件的声明" in 条 for 条 in 警),
                        f"缺声明未判红，实际报警={警}")

    def test_补声明后转绿(self) -> None:
        """还原：补上六要素齐的声明 ⇒ 该条报警消失。"""
        self.夹具.写声明(派生.服务型声明名, {"psycopg提供者": {"服务": [六要素服务()]}})
        警 = self.夹具.报警()
        self.assertEqual([条 for 条 in 警 if "服务连接字面量" in 条], [],
                         f"补声明后仍判红，实际报警={警}")

    def test_六要素缺一必红(self) -> None:
        """弄坏：声明在、但缺「端口」这一要素 ⇒ 必须报警（2.3 每一项都必须带声明）。"""
        self.夹具.写声明(派生.服务型声明名,
                     {"psycopg提供者": {"服务": [六要素服务(端口=None)]}})
        警 = self.夹具.报警()
        self.assertTrue(any("缺六要素" in 条 and "端口" in 条 for 条 in 警),
                        f"缺端口未判红，实际报警={警}")

    def test_声明了现场没证据也必红(self) -> None:
        """弄坏另一侧：声明在、实现里没有连接字面量 ⇒ 同判红（不许单边存在）。"""
        self.夹具.写件("psycopg提供者/实现/提供者.py", "没有连接字面量的实现\n")
        self.夹具.写声明(派生.服务型声明名, {"psycopg提供者": {"服务": [六要素服务()]}})
        警 = self.夹具.报警()
        self.assertTrue(any("没有任何服务连接字面量" in 条 for 条 in 警),
                        f"声明单边存在未判红，实际报警={警}")

    def test_服务声明回填进登记条目(self) -> None:
        """登记件里必须落「端口 5432」与六要素——这是 S0-1 的交付本体。"""
        self.夹具.写声明(派生.服务型声明名, {"psycopg提供者": {"服务": [六要素服务()]}})
        件 = next(j for j in 派生.汇总()["件表"] if j["名称"] == "psycopg提供者")
        self.assertEqual(件["端口"], 5432)
        self.assertIn("pg_isready", str(件["健康探针"]))
        self.assertIn("brew services", str(件["启停语义"]))
        self.assertIn("连接失败", str(件["降级语义"]))


class 内部件依赖判据(unittest.TestCase):
    """口径 ②③：内部件的依赖必须登记在 内部件依赖声明.json；有证据却没登记必红。"""

    def setUp(self) -> None:
        self.夹具 = 依赖派生夹具()
        self.夹具.装()

    def tearDown(self) -> None:
        self.夹具.卸()

    def test_根下平铺件有第三方import_无声明必红(self) -> None:
        """弄坏：根下平铺 .py 有 import torch、声明件里没有它 ⇒ 必红。"""
        self.夹具.写件("模型服务.py", "import torch\nimport uvicorn\n")
        警 = self.夹具.报警()
        self.assertTrue(any("import torch" in 条 and "没有该件该模块的条段" in 条 for 条 in 警),
                        f"未判红，实际报警={警}")

    def test_补声明后该条转绿(self) -> None:
        """还原：把 torch/uvicorn 登记进声明件 ⇒ 该条报警消失。"""
        self.夹具.写件("模型服务.py", "import torch\nimport uvicorn\n")
        self.夹具.写声明(派生.内部件声明名, {"模型服务": [
            {"名称": "torch", "模块名": "torch", "版本": "2.13.0", "来源": "PyPI", "类别": "第三方库"},
            {"名称": "uvicorn", "模块名": "uvicorn", "版本": "0.46.0", "来源": "PyPI", "类别": "第三方库"},
        ]})
        警 = self.夹具.报警()
        self.assertEqual([条 for 条 in 警 if "没有该件该模块的条段" in 条], [],
                         f"补声明后仍判红，实际报警={警}")

    def test_声明与现场不符必红(self) -> None:
        """弄坏：声明里写了 psutil、实现里没有 import ⇒ 必红（不许猜）。"""
        self.夹具.写件("系统探针.py", "import os\n")
        self.夹具.写声明(派生.内部件声明名, {"系统探针": [
            {"名称": "psutil", "模块名": "psutil", "版本": "7.2.2", "来源": "PyPI", "类别": "第三方库"},
        ]})
        警 = self.夹具.报警()
        self.assertTrue(any("没有 import 现场" in 条 for 条 in 警),
                        f"声明与现场不符未判红，实际报警={警}")

    def test_有目录内部件环境依赖声明后不再判红(self) -> None:
        """口径 ③：有目录的内部件（无锁、无包声明）在声明件里登记后，不判「该建声明没建」。"""
        self.夹具.写件("密钥提供者/密钥提供者.py",
                    "import shutil\nimport subprocess\n"
                    "路径 = shutil.which(\"security\")\n")
        self.夹具.写声明(派生.内部件声明名, {"密钥提供者": [
            {"名称": "security", "模块名": "security", "版本": "macOS 自带",
             "来源": "系统工具", "类别": "环境依赖",
             "健康探针": "which(\"security\") 非 None", "降级语义": "错误码「钥匙串不可用」",
             "启停": "无常驻"},
        ]})
        警 = self.夹具.报警()
        self.assertEqual([条 for 条 in 警 if "有外部依赖证据" in 条], [],
                         f"登记后仍报「该建声明没建」，实际报警={警}")
        件 = next(j for j in 派生.汇总()["件表"] if j["名称"] == "密钥提供者")
        self.assertIn("钥匙串不可用", str(件["降级语义"]))

    def test_有目录内部件未登记必红(self) -> None:
        """弄坏：同样的件、声明件里删掉它 ⇒ 必须回到「有外部依赖证据却两侧都无」判红。"""
        self.夹具.写件("密钥提供者/密钥提供者.py",
                    "import shutil\n路径 = shutil.which(\"security\")\n")
        警 = self.夹具.报警()
        self.assertTrue(any("既无 依赖锁.json 也不在" in 条 for 条 in 警),
                        f"未登记未判红，实际报警={警}")


class 逐项类别判据(unittest.TestCase):
    """口径 ④（既有规则的反向验证，确认没被本轮改动削弱）。"""

    def setUp(self) -> None:
        self.夹具 = 依赖派生夹具()
        self.夹具.装()

    def tearDown(self) -> None:
        self.夹具.卸()

    def _写正式包(self, 锁项: list[dict], 实现: str) -> None:
        self.夹具.写件("某提供者/包声明.json", json.dumps(
            {"包id": "支持库.适配层.某提供者", "名称": "某提供者", "类型": "支持库",
             "依赖类别": "第三方库", "版本": "1.0.0", "入口": "__init__.py", "依赖": [], "能力": []},
            ensure_ascii=False))
        self.夹具.写件("某提供者/依赖锁.json", json.dumps({"包": 锁项}, ensure_ascii=False))
        self.夹具.写件("某提供者/实现/提供者.py", 实现)

    def test_锁项无import现场必红(self) -> None:
        """弄坏：锁里写了 PyPI 包、实现没 import ⇒ 无法现场证实 ⇒ 必红。"""
        self._写正式包([{"名称": "somepkg", "模块名": "somepkg", "版本": "1.0.0",
                     "来源": "PyPI"}], "没有 import 的实现\n")
        警 = self.夹具.报警()
        self.assertTrue(any("锁内为第三方却无 import 现场" in 条 for 条 in 警),
                        f"未判红，实际报警={警}")

    def test_有import现场转绿(self) -> None:
        """还原：实现里 import 同名模块 ⇒ 该条报警消失。"""
        self._写正式包([{"名称": "somepkg", "模块名": "somepkg", "版本": "1.0.0",
                     "来源": "PyPI"}], "import somepkg\n")
        警 = self.夹具.报警()
        self.assertEqual([条 for 条 in 警 if "无 import 现场" in 条], [],
                         f"有现场仍判红，实际报警={警}")

    def test_来源外部应用直接判环境依赖(self) -> None:
        """外部命令依赖锁（来源=外部应用/系统工具）⇒ 直接环境依赖，不要求 import。"""
        self._写正式包([{"名称": "somectl", "模块名": "somectl", "版本": "2.0.0",
                     "来源": "系统工具"}], "路径 = shutil.which(\"somectl\")\n")
        件 = next(j for j in 派生.汇总()["件表"] if j["名称"] == "某提供者")
        self.assertEqual(件["依赖类别"], "环境依赖")


class 输入指纹判据(unittest.TestCase):
    """手写声明件必须进输入指纹：否则「改了声明、登记没重跑」会被读成「输入没变」。"""

    def setUp(self) -> None:
        self.夹具 = 依赖派生夹具()
        self.夹具.装()

    def tearDown(self) -> None:
        self.夹具.卸()

    def test_改声明件即改输入指纹(self) -> None:
        self.夹具.写件("密钥提供者/密钥提供者.py", "路径 = shutil.which(\"security\")\n")
        self.夹具.写声明(派生.内部件声明名, {"密钥提供者": [
            {"名称": "security", "模块名": "security", "版本": "v1", "来源": "系统工具",
             "类别": "环境依赖"},
        ]})
        前 = 派生.输入指纹(派生.汇总())
        self.夹具.写声明(派生.内部件声明名, {"密钥提供者": [
            {"名称": "security", "模块名": "security", "版本": "v2", "来源": "系统工具",
             "类别": "环境依赖"},
        ]})
        后 = 派生.输入指纹(派生.汇总())
        self.assertNotEqual(前, 后, "改手写声明件后输入指纹没变 ⇒ 生成物漂移检测失效")


if __name__ == "__main__":
    unittest.main()
