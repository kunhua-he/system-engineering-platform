"""第九阶段：组件合规测试包测试（组件合规阶段）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.组件合规.合规测试包 import 组件合规, 合规场景表
from 开发工具.组件规范.完整性摘要 import 生成完整性摘要, 校验完整性摘要


def 建合规组件() -> Path:
    """构造一个九要素齐全的合规组件。"""
    目录 = Path(tempfile.mkdtemp(prefix="第九阶段合规_"))
    (目录 / "能力契约").mkdir()
    (目录 / "依赖契约").mkdir()
    (目录 / "配置契约").mkdir()
    (目录 / "权限契约").mkdir()
    (目录 / "实现").mkdir()
    (目录 / "说明").mkdir()
    (目录 / "验证场景").mkdir()
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": "合规.组件", "名称": "合规组件", "类型": "基础模块",
        "版本": "1.0.0", "说明": "合规测试组件", "入口": "实现/入口.py",
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "能力契约" / "能力契约.json").write_text(json.dumps({
        "能力id": "合规.能力", "版本": "1.0.0", "说明": "合规能力",
        "参数": [{"名称": "文本", "类型": "文本", "必填": True}],
        "返回": "普通返回", "错误码": ["参数不合法", "内部错误"],
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "依赖契约" / "依赖契约.json").write_text(
        json.dumps({"依赖": [{"包id": "支持库.后端.文件系统支持库", "版本": "1.0.0"}]}, ensure_ascii=False), encoding="utf-8")
    (目录 / "配置契约" / "配置契约.json").write_text(
        json.dumps({"默认编码": "utf-8"}, ensure_ascii=False), encoding="utf-8")
    (目录 / "权限契约" / "权限契约.json").write_text(
        json.dumps({"合规.能力": ["管理员"]}, ensure_ascii=False), encoding="utf-8")
    (目录 / "实现" / "入口.py").write_text(
        '"""合规组件入口"""\n\ndef 能力(文本: str) -> dict:\n    if not 文本:\n        return {"成功": False, "错误码": "参数不合法"}\n    return {"成功": True, "值": {"长度": len(文本)}}\n',
        encoding="utf-8")
    (目录 / "说明" / "说明书.md").write_text(
        "# 合规组件说明书\n\n参数: 文本\n错误码: 参数不合法\n内部错误\n版本 1.0.0\n",
        encoding="utf-8")
    # 完整性摘要（唯一生成器：文件清单 sha256 唯一权威格式，最后生成避免自引用）
    摘要 = 生成完整性摘要(目录, 包id="合规.组件", 版本="1.0.0")
    (目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 目录


class Test组件合规(unittest.TestCase):
    """组件合规：13 项强制场景。"""

    def test_合规场景表完整(self):
        """13 项强制场景，组件作者不能减少。"""
        self.assertEqual(len(合规场景表), 13)
        self.assertIn("结构", 合规场景表)
        self.assertIn("真实返回值", 合规场景表)

    def test_合规组件13项全过(self):
        组件目录 = 建合规组件()
        报告 = 组件合规(组件目录).执行()
        self.assertEqual(报告.通过数, 13, [f"{名称}: {详情}" for 名称, 通过, 详情 in 报告.场景结果表 if not 通过])
        self.assertTrue(报告.成功)

    def test_缺能力契约拒绝(self):
        组件目录 = 建合规组件()
        (组件目录 / "能力契约" / "能力契约.json").unlink()
        报告 = 组件合规(组件目录).执行()
        self.assertLess(报告.通过数, 13)
        场景详情 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(场景详情["契约"])

    def test_缺完整性摘要拒绝(self):
        组件目录 = 建合规组件()
        (组件目录 / "完整性摘要.json").unlink()
        报告 = 组件合规(组件目录).执行()
        场景详情 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(场景详情["完整性摘要"])

    def test_摘要篡改拒绝(self):
        """篡改 完整性摘要.json 中清单条目 sha256 → 唯一校验器拒绝。"""
        组件目录 = 建合规组件()
        摘要路径 = 组件目录 / "完整性摘要.json"
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
        摘要数据["文件清单"][0]["sha256"] = "伪造摘要" + "0" * 40
        摘要路径.write_text(json.dumps(摘要数据, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(组件目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件摘要不一致" in 问题 for 问题 in 问题列表))

    def test_旧组件id摘要格式拒绝(self):
        """旧 {组件id,摘要} 格式必须被唯一校验器拒绝（拒绝漂移）。"""
        组件目录 = 建合规组件()
        (组件目录 / "完整性摘要.json").write_text(json.dumps({
            "组件id": "合规.组件", "摘要": "旧格式摘要",
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(组件目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表))

    def test_实现文件删除拒绝(self):
        组件目录 = 建合规组件()
        (组件目录 / "实现" / "入口.py").unlink()
        报告 = 组件合规(组件目录).执行()
        场景详情 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(场景详情["公共入口"])
        self.assertFalse(场景详情["真实返回值"])

    def test_吞异常拒绝(self):
        组件目录 = 建合规组件()
        (组件目录 / "实现" / "入口.py").write_text(
            'def 能力(文本):\n    try:\n        return {}\n    except Exception:\n        pass\n',
            encoding="utf-8")
        # 实现被改 → 摘要也漂移
        报告 = 组件合规(组件目录).执行()
        场景详情 = dict((名称, 通过) for 名称, 通过, _ in 报告.场景结果表)
        self.assertFalse(场景详情["失败语义"])


if __name__ == "__main__":
    unittest.main()
