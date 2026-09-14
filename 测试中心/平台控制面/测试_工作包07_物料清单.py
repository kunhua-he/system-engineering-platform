"""工作包 P1-07 软件物料清单与构建来源证明测试。

覆盖：物料清单全字段 / 来源证明全字段 / 生成并保存两个 JSON /
真实重算摘要校验（篡改拒绝）/ 缺文件与多文件失败 / 制品摘要一致。
调用生产实现（平台控制面/包仓库/物料清单.py）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.包仓库.物料清单 import 物料清单与来源证明


def 样例构建结果(验证证据id: str = "证据-001") -> dict:
    """构造真实构建结果：输入文件表与输出文件表逐字节可控。"""
    return {
        "包id": "示例包",
        "版本": "1.0.0",
        "源码提交": "提交-abc123",
        "构建命令": "python3.14 构建.py --release",
        "输入文件表": {"源/主.py": "print(1)\n", "源/工具.py": "def 工具(): return 2\n"},
        "依赖锁": "依赖锁-摘要-xyz789",
        "目标平台": "darwin-arm64",
        "构建时间": "2026-08-01T12:00:00Z",
        "执行身份": "构建机器人1",
        "输出文件表": {"主.py": "print(1)\n", "工具.py": "def 工具(): return 2\n"},
        "制品摘要": "制品摘要-88位abcdef0123456789",
        "验证证据id": 验证证据id,
    }


def 写构建目录(目录: Path, 构建结果: dict) -> None:
    """按输出文件表写入构建目录，模拟真实构建产物。"""
    目录.mkdir(parents=True, exist_ok=True)
    for 路径, 内容 in 构建结果["输出文件表"].items():
        (目录 / 路径).write_text(内容, encoding="utf-8")


class 测试物料清单与来源证明(unittest.TestCase):
    """软件物料清单（SBOM）与构建来源证明。"""

    def setUp(self):
        self.服务 = 物料清单与来源证明()

    def test_生成物料清单包含全部必需字段(self):
        清单 = self.服务.生成物料清单(样例构建结果())
        self.assertEqual(清单["包id"], "示例包")
        self.assertEqual(清单["版本"], "1.0.0")
        self.assertEqual(清单["构建器版本"], "可复现构建器-1.0.0")
        self.assertEqual(清单["依赖锁"], "依赖锁-摘要-xyz789")
        self.assertEqual(清单["目标平台"], "darwin-arm64")
        self.assertEqual(清单["验证证据id"], "证据-001")
        self.assertEqual(清单["制品摘要"], "制品摘要-88位abcdef0123456789")
        源码摘要 = 清单["源码摘要"]
        self.assertEqual(源码摘要["算法"], "sha256")
        self.assertEqual(源码摘要["文件数"], 2)
        self.assertEqual(len(源码摘要["文件摘要表"]), 2)
        self.assertEqual(len(清单["正式文件"]), 2)
        self.assertEqual(清单["正式文件"][0]["路径"], "主.py")
        self.assertRegex(清单["正式文件"][0]["sha256"], r"^[0-9a-f]{64}$")
        json.dumps(清单)  # JSON 可序列化

    def test_生成来源证明包含全部必需字段(self):
        证明 = self.服务.生成来源证明(样例构建结果(), "证据-002")
        self.assertEqual(证明["源码提交"], "提交-abc123")
        self.assertEqual(证明["构建命令"], "python3.14 构建.py --release")
        self.assertEqual(证明["构建器版本"], "可复现构建器-1.0.0")
        self.assertTrue(证明["输入摘要"])
        self.assertTrue(证明["输出摘要"])
        self.assertEqual(证明["验证证据id"], "证据-002")
        self.assertEqual(证明["构建时间"], "2026-08-01T12:00:00Z")
        self.assertEqual(证明["执行身份"], "构建机器人1")
        json.dumps(证明)  # JSON 可序列化

    def test_生成并保存输出两个JSON文件且可解析(self):
        with tempfile.TemporaryDirectory(prefix="物料清单保存_") as 临时:
            输出目录 = Path(临时) / "证据输出"
            物料路径, 证明路径 = self.服务.生成并保存(
                样例构建结果(), 输出目录, "证据-003")
            self.assertTrue(物料路径.is_file())
            self.assertTrue(证明路径.is_file())
            物料内容 = json.loads(物料路径.read_text(encoding="utf-8"))
            证明内容 = json.loads(证明路径.read_text(encoding="utf-8"))
            self.assertEqual(物料内容["验证证据id"], "证据-003")
            self.assertEqual(证明内容["验证证据id"], "证据-003")

    def test_校验物料清单未篡改通过篡改必须失败(self):
        构建结果 = 样例构建结果()
        清单 = self.服务.生成物料清单(构建结果)
        with tempfile.TemporaryDirectory(prefix="物料清单校验_") as 临时:
            构建目录 = Path(临时) / "构建目录"
            写构建目录(构建目录, 构建结果)
            成功, 消息 = self.服务.校验物料清单(清单, 构建目录)
            self.assertTrue(成功, f"未篡改目录必须通过: {消息}")
            # 篡改任一正式文件内容 → 真实重算摘要必须失败
            (构建目录 / "主.py").write_text("print(999)\n", encoding="utf-8")
            成功2, 消息2 = self.服务.校验物料清单(清单, 构建目录)
            self.assertFalse(成功2, "篡改后校验必须失败")
            self.assertIn("摘要不符", 消息2)

    def test_缺文件或多文件时校验失败(self):
        构建结果 = 样例构建结果()
        清单 = self.服务.生成物料清单(构建结果)
        with tempfile.TemporaryDirectory(prefix="物料清单缺失_") as 临时:
            构建目录 = Path(临时) / "构建目录"
            写构建目录(构建目录, 构建结果)
            # 缺文件 → 必须失败
            (构建目录 / "主.py").unlink()
            缺, 消息缺 = self.服务.校验物料清单(清单, 构建目录)
            self.assertFalse(缺, "缺文件必须失败")
            self.assertIn("缺少", 消息缺)
            # 多文件 → 必须失败
            (构建目录 / "主.py").write_text("print(1)\n", encoding="utf-8")
            (构建目录 / "多余.txt").write_text("x", encoding="utf-8")
            多, 消息多 = self.服务.校验物料清单(清单, 构建目录)
            self.assertFalse(多, "多文件必须失败")
            self.assertIn("多余", 消息多)

    def test_物料清单与来源证明制品摘要一致(self):
        构建结果 = 样例构建结果()
        清单 = self.服务.生成物料清单(构建结果)
        证明 = self.服务.生成来源证明(构建结果, "证据-006")
        self.assertEqual(清单["制品摘要"], 证明["制品摘要"])
        self.assertEqual(清单["制品摘要"], 构建结果["制品摘要"])
        self.assertEqual(证明["输入摘要"], 清单["源码摘要"]["值"])


if __name__ == "__main__":
    unittest.main()
