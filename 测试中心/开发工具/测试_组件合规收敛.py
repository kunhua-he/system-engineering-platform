"""第二十九阶段 G3：权威组件合规收敛测试（S0.4 唯一权威验证器）。

13 项真实覆盖：聚合契约逐能力遍历（契约/权限）、公开入口+能力注册表+
锁定提供者真实返回、缺项阻断清单（配置契约/权限契约/资源预算/复用决策/
注册能力/__all__/能力契约/验证证据）逐一检出、反向破坏一致失败。
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

from 开发工具.组件合规.合规测试包 import 组件合规, 合规场景表
from 支持库.后端.组件规范支持库 import 生成完整性摘要

能力1 = {
    "能力id": "合规.能力1", "版本": "1.0.0", "说明": "合规测试能力1",
    "参数": [{"名称": "文本", "类型": "文本", "必填": True,
              "默认值": None, "说明": "待处理文本"}],
    "返回": {"类型": "结果", "值结构": {"长度": "整数"}},
    "错误码": ["参数不合法", "内部错误"],
    "调用示例": {"能力id": "合规.能力1", "参数": {"文本": "示例"}},
}
能力2 = {
    "能力id": "合规.能力2", "版本": "1.0.0", "说明": "合规测试能力2",
    "参数": [{"名称": "路径", "类型": "文本", "必填": True,
              "默认值": None, "说明": "目标路径"}],
    "返回": {"类型": "结果", "值结构": {"路径": "文本"}},
    "错误码": ["参数不合法", "路径不存在"],
    "调用示例": {"能力id": "合规.能力2", "参数": {"路径": "/tmp/x"}},
}

入口源码 = '''"""合规收敛组件包级中文入口。"""
from __future__ import annotations

from 实现.实现 import 能力1, 能力2

__all__ = ["能力1", "能力2"]


def 注册能力(注册表) -> None:
    """由模块加载器调用。"""
    from 公共契约.能力契约.契约 import 能力实现

    for 能力id, 函数 in [("合规.能力1", 能力1), ("合规.能力2", 能力2)]:
        注册表.注册(能力实现(
            能力id=能力id, 包id="合规.收敛组件", 实现函数=函数,
            参数=[{"名称": "文本", "类型": "文本"}, {"名称": "路径", "类型": "文本"}],
            返回="结果", 说明="合规收敛能力",
        ))
'''

实现源码 = '''"""合规收敛组件实现。"""
from __future__ import annotations


def 能力1(文本: str) -> dict:
    if not 文本:
        return {"成功": False, "错误码": "参数不合法"}
    return {"成功": True, "值": {"长度": len(文本)}}


def 能力2(路径: str) -> dict:
    if not 路径:
        return {"成功": False, "错误码": "参数不合法"}
    return {"成功": True, "值": {"路径": 路径}}
'''


def 建收敛组件() -> Path:
    """构造 S0 聚合契约正式包形态的齐全组件（含全部缺项阻断要素）。"""
    目录 = Path(tempfile.mkdtemp(prefix="合规收敛_"))
    for 子目录 in ("能力契约", "依赖契约", "配置契约", "权限契约", "实现", "说明"):
        (目录 / 子目录).mkdir()
    (目录 / "能力契约" / "参数契约.json").write_text(
        json.dumps({"契约版本": "1.0.0", "能力契约": [能力1, 能力2]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (目录 / "依赖契约" / "依赖契约.json").write_text(
        json.dumps({"依赖": []}, ensure_ascii=False), encoding="utf-8")
    (目录 / "配置契约" / "配置契约.json").write_text(
        json.dumps({"默认编码": "utf-8", "默认超时秒": 10}, ensure_ascii=False),
        encoding="utf-8")
    (目录 / "权限契约" / "权限契约.json").write_text(
        json.dumps({"合规.能力1": {"允许用户": ["*"]},
                    "合规.能力2": {"允许用户": ["*"]}}, ensure_ascii=False),
        encoding="utf-8")
    (目录 / "资源预算.json").write_text(
        json.dumps({"内存上限": 50, "线程上限": 2, "子进程上限": 1,
                    "并发调用上限": 2, "队列长度": 5, "文件句柄上限": 20,
                    "临时空间上限": 50, "单次调用超时": 3,
                    "每分钟重启次数": 2, "空闲回收时间": 30}, ensure_ascii=False),
        encoding="utf-8")
    (目录 / "复用决策.json").write_text(
        json.dumps({"搜索词": "合规", "候选能力id": ["文件系统支持库.文件操作.读取文件"]},
                   ensure_ascii=False), encoding="utf-8")
    (目录 / "验证场景引用.json").write_text(
        json.dumps({"验证场景引用": [{"场景id": "模块.装配验证",
                                     "目标": "合规.收敛组件", "范围": "装配"}]},
                   ensure_ascii=False), encoding="utf-8")
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": "合规.收敛组件", "名称": "收敛组件", "类型": "基础模块",
        "版本": "1.0.0", "说明": "第二十九阶段合规收敛测试组件",
        "入口": "__init__.py", "依赖": [],
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "__init__.py").write_text(入口源码, encoding="utf-8")
    (目录 / "实现" / "实现.py").write_text(实现源码, encoding="utf-8")
    (目录 / "说明" / "使用说明.md").write_text(
        "# 收敛组件说明书\n\n能力1/能力2，错误码：参数不合法/内部错误/路径不存在。\n",
        encoding="utf-8")
    摘要 = 生成完整性摘要(目录, 包id="合规.收敛组件", 版本="1.0.0")
    (目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 目录


def _场景通过表(组件目录: Path) -> dict[str, bool]:
    报告 = 组件合规(组件目录).执行()
    return {名称: 通过 for 名称, 通过, _ in 报告.场景结果表}


class Test组件合规收敛(unittest.TestCase):
    """权威合规 13 项真实覆盖与缺项阻断清单。"""

    def test_合规场景表仍为13项权威(self) -> None:
        self.assertEqual(len(合规场景表), 13)

    def test_齐全正式包13项全过(self) -> None:
        组件目录 = 建收敛组件()
        try:
            报告 = 组件合规(组件目录).执行()
            self.assertEqual(报告.通过数, 13,
                             [f"{名称}: {详情}" for 名称, 通过, 详情 in 报告.场景结果表 if not 通过])
            self.assertTrue(报告.成功)
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_聚合契约逐能力遍历_缺一能力错误码检出(self) -> None:
        """契约场景必须逐能力遍历：能力2缺错误码 → 检出（禁整文件当一个能力）。"""
        组件目录 = 建收敛组件()
        try:
            契约路径 = 组件目录 / "能力契约" / "参数契约.json"
            契约数据 = json.loads(契约路径.read_text(encoding="utf-8"))
            契约数据["能力契约"][1]["错误码"] = []
            契约路径.write_text(json.dumps(契约数据, ensure_ascii=False), encoding="utf-8")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["契约"], "能力2缺错误码必须被契约场景检出")
            self.assertFalse(场景表["失败语义"], "能力2缺错误码必须被失败语义场景检出")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_权限逐能力遍历_缺一能力声明检出(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "权限契约" / "权限契约.json").write_text(
                json.dumps({"合规.能力1": {"允许用户": ["*"]}}, ensure_ascii=False),
                encoding="utf-8")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["权限"], "能力2无权限声明必须被检出")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺配置契约阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            shutil.rmtree(组件目录 / "配置契约")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["配置"], "缺 配置契约 必须阻断")
            self.assertFalse(场景表["结构"], "缺 配置契约 同时使九要素结构失败")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺权限契约阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            shutil.rmtree(组件目录 / "权限契约")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["权限"], "缺 权限契约 必须阻断")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺注册能力检出(self) -> None:
        """正式包入口缺 注册能力 → 公共入口阻断。"""
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "__init__.py").write_text(
                '"""无注册能力入口。"""\nfrom 实现.实现 import 能力1\n__all__ = ["能力1"]\n',
                encoding="utf-8")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["公共入口"], "缺 注册能力 必须被公共入口场景检出")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺__all__检出(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "__init__.py").write_text(
                '"""无 __all__ 入口。"""\nfrom 实现.实现 import 能力1\n\n\ndef 注册能力(注册表):\n    return None\n',
                encoding="utf-8")
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["公共入口"], "缺 __all__ 必须被公共入口场景检出")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺能力契约阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "能力契约" / "参数契约.json").unlink()
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["契约"], "缺 能力契约 必须阻断")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺资源预算阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "资源预算.json").unlink()
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["结构"], "缺 资源预算 必须阻断")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺复用决策阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "复用决策.json").unlink()
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["结构"], "缺 复用决策 必须阻断")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_缺验证证据阻断(self) -> None:
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "验证场景引用.json").unlink()
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["结构"], "缺 验证证据 必须阻断")
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)

    def test_反向破坏_删除实现一致失败(self) -> None:
        """删除 实现 → 公共入口/真实返回值 全部失败（反向破坏一致）。"""
        组件目录 = 建收敛组件()
        try:
            (组件目录 / "实现" / "实现.py").unlink()
            场景表 = _场景通过表(组件目录)
            self.assertFalse(场景表["公共入口"])
            self.assertFalse(场景表["真实返回值"])
        finally:
            shutil.rmtree(组件目录, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
