"""摘要格式最终收敛测试：{组件id,摘要} 旧格式迁移到唯一完整性摘要生成器。

覆盖：旧格式（能力数格式/组件id格式）被唯一校验器拒绝/真实文件篡改失败/
自比较失败（禁止测试用生成器重新生成自比较，一律用独立校验器）/
跳过校验失败（缺摘要/缺文件清单）/
组件规范与组件合规的生成/校验全部委托唯一生成器（无第二套算法）。

禁止 mock 校验：全部用真实文件变更验证摘要变化。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.组件规范支持库 import 生成完整性摘要, 校验完整性摘要


def 建临时包(包id: str = "收敛.包", 版本: str = "1.0.0") -> tuple[Path, Path]:
    """构造一个带包声明与两个文件的临时包目录。"""
    目录 = Path(tempfile.mkdtemp(prefix="摘要格式收敛_"))
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": 包id, "版本": 版本, "类型": "支持库",
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "实现").mkdir()
    (目录 / "实现" / "能力.py").write_text("值 = 1\n", encoding="utf-8")
    (目录 / "说明.md").write_text("# 收敛测试包\n", encoding="utf-8")
    return 目录, 目录 / "实现" / "能力.py"


def 写文件清单摘要(目录: Path, 包id: str = "收敛.包", 版本: str = "1.0.0") -> None:
    """用唯一生成器生成并写入 完整性摘要.json。"""
    摘要 = 生成完整性摘要(目录, 包id=包id, 版本=版本)
    (目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False, indent=2), encoding="utf-8")


class Test旧格式被拒绝(unittest.TestCase):
    """能力数格式与 {组件id,摘要} 格式一律被唯一校验器拒绝。"""

    def test_组件id摘要格式拒绝(self):
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "组件id": "收敛.包", "摘要": "旧组件摘要值",
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表))

    def test_能力数格式拒绝(self):
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "包id": "收敛.包", "版本": "1.0.0",
            "能力数": 1, "能力清单": ["收敛.能力"],
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表))

    def test_组件id格式即使写入真实摘要值也被拒绝(self):
        """旧格式即使自算摘要值写入也不通过：校验器只认文件清单，杜绝自比较。"""
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "组件id": "收敛.包", "摘要": "真实内容摘要值",
        }, ensure_ascii=False), encoding="utf-8")
        通过, _ = 校验完整性摘要(目录)
        self.assertFalse(通过)

    def test_混合旧字段加文件清单通过_缺文件清单不通过(self):
        """文件清单存在时附加旧字段不碍事；但缺文件清单一律拒绝。"""
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="收敛.包", 版本="1.0.0")
        摘要["组件id"] = "收敛.包"  # 附加旧字段不改变权威格式
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertTrue(通过, str(问题列表))


class Test篡改与跳过校验失败(unittest.TestCase):
    """真实文件变更（不 mock）必须被唯一校验器拒绝。"""

    def _写摘要(self, 目录: Path) -> None:
        写文件清单摘要(目录)

    def test_清单条目sha256篡改失败(self):
        目录, _ = 建临时包()
        self._写摘要(目录)
        摘要路径 = 目录 / "完整性摘要.json"
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
        # 篡改值必须是**形状合法**的摘要（64 位十六进制），才能走到「与真实文件不符」
        # 这条路径。原先写 "伪造"+"0"*40 是畸形值，会被「必须为 64 位十六进制」的前置
        # 格式校验先行拒绝（校验同样失败，但证据变成格式不合法），本测试名与断言要验的
        # 是「值被换掉 → 摘要不一致」，故用全零这份合法但必错的摘要。
        摘要数据["文件清单"][0]["sha256"] = "0" * 64
        摘要路径.write_text(json.dumps(摘要数据, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件摘要不一致" in 问题 for 问题 in 问题列表))

    def test_真实文件篡改失败(self):
        目录, 能力文件 = 建临时包()
        self._写摘要(目录)
        能力文件.write_text("值 = 2\n", encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件摘要不一致" in 问题 for 问题 in 问题列表))

    def test_缺摘要文件失败(self):
        目录, _ = 建临时包()
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("缺少 完整性摘要.json" in 问题 for 问题 in 问题列表))

    def test_空文件清单失败(self):
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "包id": "收敛.包", "版本": "1.0.0",
            "摘要算法": "sha256", "文件清单": [],
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表))

    def test_非JSON摘要失败(self):
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text("不是JSON", encoding="utf-8")
        通过, _ = 校验完整性摘要(目录)
        self.assertFalse(通过)


class Test自比较禁令(unittest.TestCase):
    """禁止测试用生成器重新生成后自比；一律用独立校验器验证。"""

    def test_校验器独立于生成器返回证据(self):
        """校验失败必须带具体问题证据（不能只有布尔值，证明非自比较）。"""
        目录, 能力文件 = 建临时包()
        写文件清单摘要(目录)
        能力文件.write_text("值 = 3\n", encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(问题列表, "校验失败必须给出具体问题证据")
        self.assertTrue(any("文件摘要不一致" in 问题 for 问题 in 问题列表))

    def test_生成后经独立校验器验证通过(self):
        """正确路径：唯一生成器产出 → 独立校验器验证闭合（不经生成器自比）。"""
        目录, _ = 建临时包()
        写文件清单摘要(目录)
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertTrue(通过, str(问题列表))


class Test组件规范委托唯一生成器(unittest.TestCase):
    """组件规范.py 的生成/校验必须委托唯一生成器，不复制第二套算法。"""

    def test_组件规范生成器产出文件清单格式(self):
        from 支持库.后端.组件规范支持库 import 生成并写入完整性摘要 as 组件规范生成
        目录 = Path(tempfile.mkdtemp(prefix="摘要格式收敛规范_"))
        (目录 / "包声明.json").write_text(json.dumps({
            "包id": "收敛.规范", "版本": "2.0.0", "类型": "支持库",
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / "实现").mkdir()
        (目录 / "实现" / "能力.py").write_text("值 = 1\n", encoding="utf-8")
        摘要 = 组件规范生成(目录)
        self.assertEqual(摘要["包id"], "收敛.规范")
        self.assertEqual(摘要["版本"], "2.0.0")
        self.assertEqual(摘要["摘要算法"], "sha256")
        self.assertTrue(摘要["文件清单"])
        self.assertNotIn("摘要", 摘要)  # 旧 {组件id,摘要} 字段不得出现
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertTrue(通过, str(问题列表))

    def test_组件规范校验拒绝旧组件id格式(self):
        from 支持库.后端.组件规范支持库 import 校验组件规范
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "组件id": "收敛.包", "摘要": "旧格式",
        }, ensure_ascii=False), encoding="utf-8")
        结果 = 校验组件规范(目录)
        self.assertFalse(结果.成功)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 结果.问题列表))


class Test组件合规委托唯一校验器(unittest.TestCase):
    """组件合规 13 项中的完整性摘要场景必须经唯一校验器。"""

    def _建合规包(self) -> Path:
        目录 = Path(tempfile.mkdtemp(prefix="摘要格式收敛合规_"))
        (目录 / "包声明.json").write_text(json.dumps({
            "包id": "收敛.合规", "版本": "1.0.0", "类型": "支持库",
            "入口": "实现/入口.py",
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / "能力契约").mkdir()
        (目录 / "能力契约" / "契约.json").write_text(json.dumps({
            "能力id": "收敛.能力", "版本": "1.0.0", "错误码": ["参数不合法"],
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / "依赖契约").mkdir()
        (目录 / "依赖契约" / "依赖契约.json").write_text(
            json.dumps({"依赖": []}, ensure_ascii=False), encoding="utf-8")
        (目录 / "配置契约").mkdir()
        (目录 / "配置契约" / "配置契约.json").write_text(
            json.dumps({"默认编码": "utf-8"}, ensure_ascii=False), encoding="utf-8")
        (目录 / "权限契约").mkdir()
        (目录 / "权限契约" / "权限契约.json").write_text(
            json.dumps({"收敛.能力": ["管理员"]}, ensure_ascii=False), encoding="utf-8")
        (目录 / "实现").mkdir()
        (目录 / "实现" / "入口.py").write_text(
            'def 能力(文本: str) -> dict:\n    return {"成功": True}\n',
            encoding="utf-8")
        (目录 / "说明").mkdir()
        (目录 / "说明" / "说明书.md").write_text("# 说明书\n", encoding="utf-8")
        return 目录

    def test_合规场景经唯一校验器_旧格式拒绝(self):
        from 开发工具.组件合规.合规测试包 import 组件合规
        目录 = self._建合规包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "组件id": "收敛.合规", "摘要": "旧格式",
        }, ensure_ascii=False), encoding="utf-8")
        报告 = 组件合规(目录).执行()
        详情表 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(详情表["完整性摘要"])
        # 篡改真实文件后同样拒绝（真实变更，不 mock）
        写文件清单摘要(目录, 包id="收敛.合规")
        (目录 / "实现" / "入口.py").write_text(
            'def 能力(文本: str) -> dict:\n    return {"成功": False}\n',
            encoding="utf-8")
        报告 = 组件合规(目录).执行()
        详情表 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(详情表["完整性摘要"])

    def test_合规场景文件清单格式通过(self):
        from 开发工具.组件合规.合规测试包 import 组件合规
        目录 = self._建合规包()
        写文件清单摘要(目录, 包id="收敛.合规")
        报告 = 组件合规(目录).执行()
        详情表 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertTrue(详情表["完整性摘要"])


if __name__ == "__main__":
    unittest.main()
