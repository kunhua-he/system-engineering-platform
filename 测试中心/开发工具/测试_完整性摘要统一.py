"""完整性摘要统一测试：文件清单为唯一权威格式。

覆盖：生成器格式唯一（含文件清单）/校验通过/文件篡改失败/
缺文件清单格式拒绝/编译器派生物为文件清单格式/门禁校验调唯一生成器/
旧格式迁移后全仓无"能力数"格式残留（扫描断言）。

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

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.后端.组件规范支持库 import (
    生成完整性摘要,
    迁移旧格式摘要,
    校验完整性摘要,
)
from 公共契约.运行时.平台适配 import 清只读后删除树


#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 模块级临时夹具登记：本模块的夹具**在模块级 helper 里**造（helper 拿不到 TestCase 实例，
#: 用不了 `self.addCleanup`）⇒ 走 unittest 的**模块级收尾钩子** `tearDownModule` 登记清理
#: （同样「用例失败也跑」）。拿得到用例实例的站点一律用 `self.addCleanup`。
_临时夹具登记: list[Path] = []


def tearDownModule() -> None:
    """模块收尾：清理本模块造在 `受管临时根` 下的全部夹具（**用例失败也跑**）。"""
    for 夹具 in _临时夹具登记:
        清只读后删除树(夹具, 忽略失败=真)
    _临时夹具登记.clear()



def 建临时包(包id: str = "测试.包", 版本: str = "1.0.0") -> tuple[Path, Path]:
    """构造一个带包声明与两个文件的临时包目录。"""
    目录 = Path(tempfile.mkdtemp(prefix="完整性摘要_", dir=受管临时根))
    _临时夹具登记.append(目录)
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": 包id, "版本": 版本, "类型": "支持库",
    }, ensure_ascii=False), encoding="utf-8")
    (目录 / "实现").mkdir()
    (目录 / "实现" / "能力.py").write_text("值 = 1\n", encoding="utf-8")
    (目录 / "说明.md").write_text("# 测试包\n", encoding="utf-8")
    return 目录, 目录 / "实现" / "能力.py"


class Test生成器格式(unittest.TestCase):
    """唯一生成器：文件清单格式，排除自身与缓存。"""

    def test_生成器输出文件清单权威格式(self):
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        self.assertEqual(摘要["包id"], "测试.包")
        self.assertEqual(摘要["版本"], "1.0.0")
        self.assertEqual(摘要["摘要算法"], "sha256")
        文件清单 = 摘要["文件清单"]
        self.assertIsInstance(文件清单, list)
        self.assertTrue(文件清单, "文件清单不得为空")
        for 条目 in 文件清单:
            self.assertIn("路径", 条目)
            self.assertIn("sha256", 条目)
            self.assertGreaterEqual(len(条目["sha256"]), 16)

    def test_生成器排除自身与缓存(self):
        目录, _ = 建临时包()
        (目录 / "__pycache__").mkdir()
        (目录 / "__pycache__" / "缓存.pyc").write_bytes(b"x")
        (目录 / "完整性摘要.json").write_text("旧内容", encoding="utf-8")
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        清单路径 = {条目["路径"] for 条目 in 摘要["文件清单"]}
        self.assertNotIn("完整性摘要.json", 清单路径)
        self.assertFalse(any("__pycache__" in 路径 for 路径 in 清单路径))

    def test_生成器确定性可重复(self):
        目录, _ = 建临时包()
        第一次 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        第二次 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        self.assertEqual(第一次, 第二次)

    def test_无文件包拒绝生成(self):
        目录 = Path(tempfile.mkdtemp(prefix="完整性摘要空_", dir=受管临时根))
        self.addCleanup(清只读后删除树, 目录, 忽略失败=真)
        with self.assertRaises(ValueError):
            生成完整性摘要(目录, 包id="测试.空", 版本="1.0.0")


class Test校验完整性摘要(unittest.TestCase):
    """校验：真实文件变更验证摘要变化（禁止 mock）。"""

    def _写摘要(self, 目录: Path) -> None:
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_生成后校验通过(self):
        目录, _ = 建临时包()
        self._写摘要(目录)
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertTrue(通过, str(问题列表))

    def test_文件篡改校验失败(self):
        目录, 能力文件 = 建临时包()
        self._写摘要(目录)
        能力文件.write_text("值 = 2\n", encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件摘要不一致" in 问题 for 问题 in 问题列表))

    def test_新增文件校验失败(self):
        目录, _ = 建临时包()
        self._写摘要(目录)
        (目录 / "实现" / "新文件.py").write_text("x = 1\n", encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("清单不闭合" in 问题 for 问题 in 问题列表))

    def test_删除文件校验失败(self):
        目录, 能力文件 = 建临时包()
        self._写摘要(目录)
        能力文件.unlink()
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("清单文件不存在" in 问题 for 问题 in 问题列表))

    def test_缺文件清单格式拒绝(self):
        """旧'能力数'格式必须被拒绝（拒绝漂移）。"""
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "包id": "测试.包", "版本": "1.0.0",
            "能力数": 1, "能力清单": ["测试.能力"],
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表))

    def test_空文件清单拒绝(self):
        """空 `文件清单` 必须被拒绝，且**给出原因**（与兄弟用例同形状）。"""
        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "包id": "测试.包", "版本": "1.0.0",
            "摘要算法": "sha256", "文件清单": [],
        }, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        # 只 `assertFalse` 是「负面断言强度不足」——门禁要求**同时断言拒绝原因**，
        # 否则实现改坏成「一律拒绝」也能骗过本条（测试伪装门禁 规则3 真判定）。
        self.assertFalse(通过)
        self.assertTrue(any("文件清单缺失或为空" in 问题 for 问题 in 问题列表),
                        f"拒绝原因须指明文件清单为空，实得: {问题列表}")

    def test_摘要算法不合法拒绝(self):
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        摘要["摘要算法"] = "md5"
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("摘要算法不合法" in 问题 for 问题 in 问题列表))

    def test_摘要算法缺省拒绝(self):
        """缺 摘要算法 字段不得被当成 sha256 放行（唯一格式必须显式声明）。"""
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        摘要.pop("摘要算法")
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("摘要算法不合法" in 问题 for 问题 in 问题列表))

    def test_截断摘要拒绝(self):
        """截断到 16 位的 sha256 不得被 startswith 当成「一致」。"""
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        摘要["文件清单"][0]["sha256"] = 摘要["文件清单"][0]["sha256"][:16]
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("64 位十六进制" in 问题 for 问题 in 问题列表))

    def test_包id与声明不一致拒绝(self):
        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        摘要["包id"] = "伪造.包id"
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertFalse(通过)
        self.assertTrue(any("包id或版本与包声明不一致" in 问题 for 问题 in 问题列表))


class Test编译器派生物(unittest.TestCase):
    """能力定义编译器产物必须为文件清单格式。"""

    def test_编译器派生物为文件清单格式(self):
        from 开发工具.契约编译.能力定义编译器 import 编译能力定义

        目录 = Path(tempfile.mkdtemp(prefix="完整性摘要编译_", dir=受管临时根))
        self.addCleanup(清只读后删除树, 目录, 忽略失败=真)
        包目录 = 目录 / "python_docx提供者"
        包目录.mkdir()
        定义文件 = 包目录 / "能力定义.json"
        定义文件.write_text(json.dumps({
            "包id": "支持库.适配层.python_docx提供者",
            "能力列表": [{
                "能力id": "办公文档支持库.文字文档.解析文字文档",
                "版本": "1.0.0",
                "中文名称": "解析文字文档",
                "说明": "解析 DOC/DOCX 为平台通用文档",
                "参数": [{"名称": "文件路径", "类型": "文本", "必填": 真,
                          "说明": "文件绝对路径"}],
                "返回": "结果",
                "错误码": ["文件不存在", "参数不合法"],
                "行为": {
                    "修改输入": 假, "幂等": 真, "副作用": "只读",
                    "排序稳定": 真, "时区": "Asia/Shanghai", "编码": "utf-8",
                    "精度": "高", "空值": "返回空文档", "输入上限": "200MB",
                    "超时可重试": 真, "取消": "支持", "重试条件": "超时",
                    "事务边界": "无", "补偿动作": "无", "线程安全": 真,
                    "进程安全": 真, "资源释放": "自动", "错误码": "统一",
                    "可重试性": "超时可重试",
                },
                "提供者": {"默认": "支持库.适配层.python_docx提供者", "版本": ">=1.0.0"},
            }],
        }, ensure_ascii=False), encoding="utf-8")
        结果 = 编译能力定义(
            定义文件, 包目录,
            包id="支持库.适配层.python_docx提供者", 包名称="python_docx提供者",
            包类型="支持库", 依赖=[], 实现模块="x",
        )
        self.assertTrue(结果.成功, str(结果.问题列表))
        摘要数据 = json.loads((包目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], "支持库.适配层.python_docx提供者")
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        self.assertTrue(摘要数据["文件清单"], "文件清单不得为空")
        清单路径 = {条目["路径"] for 条目 in 摘要数据["文件清单"]}
        self.assertIn("能力定义.json", 清单路径)
        self.assertIn("包声明.json", 清单路径)
        self.assertIn("__init__.py", 清单路径)
        # 能力数允许作为附加字段保留，但文件清单必须存在且权威
        self.assertIn("能力数", 摘要数据)
        通过, 问题列表 = 校验完整性摘要(包目录)
        self.assertTrue(通过, str(问题列表))


class Test门禁委托(unittest.TestCase):
    """发布门禁完整性摘要校验必须委托唯一生成器/校验器。"""

    def test_门禁校验调唯一校验器(self):
        from 开发工具.发布门禁.运行发布门禁 import _校验文件清单摘要

        目录, _ = 建临时包()
        摘要 = 生成完整性摘要(目录, 包id="测试.包", 版本="1.0.0")
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False, indent=2), encoding="utf-8")
        通过, 证据 = _校验文件清单摘要(目录)
        self.assertTrue(通过, 证据)
        # 篡改真实文件后必须拒绝（不 mock）
        (目录 / "实现" / "能力.py").write_text("值 = 9\n", encoding="utf-8")
        通过, 证据 = _校验文件清单摘要(目录)
        self.assertFalse(通过)
        self.assertIn("文件摘要不一致", 证据)

    def test_门禁拒绝能力数格式(self):
        from 开发工具.发布门禁.运行发布门禁 import _校验文件清单摘要

        目录, _ = 建临时包()
        (目录 / "完整性摘要.json").write_text(json.dumps({
            "包id": "测试.包", "版本": "1.0.0", "能力数": 1,
        }, ensure_ascii=False), encoding="utf-8")
        通过, 证据 = _校验文件清单摘要(目录)
        self.assertFalse(通过)
        self.assertIn("文件清单缺失或为空", 证据)


class Test说明书生成器委托(unittest.TestCase):
    """说明书生成器必须委托唯一生成器（同一文件清单格式）。"""

    def test_说明书生成器产出文件清单格式(self):
        from 开发工具.MD文档生成.说明书.完整性摘要生成器 import 生成单包摘要

        目录, _ = 建临时包(包id="测试.说明书", 版本="2.0.0")
        摘要 = 生成单包摘要(目录)
        self.assertEqual(摘要["包id"], "测试.说明书")
        self.assertEqual(摘要["版本"], "2.0.0")
        self.assertEqual(摘要["摘要算法"], "sha256")
        self.assertTrue(摘要["文件清单"])


class Test迁移与全仓扫描(unittest.TestCase):
    """迁移：全仓 支持库/模块库 无'能力数'格式残留（扫描断言）。"""

    def test_全仓无能力数格式残留(self):
        残留表 = []
        格式错误表 = []
        for 根目录名 in ("支持库", "模块库", "技能库"):
            根目录 = 系统根 / 根目录名
            if not 根目录.is_dir():
                continue
            for 摘要路径 in 根目录.rglob("完整性摘要.json"):
                if "__pycache__" in 摘要路径.parts:
                    continue
                try:
                    摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    格式错误表.append(str(摘要路径.relative_to(系统根)))
                    continue
                文件清单 = 摘要数据.get("文件清单")
                if not isinstance(文件清单, list) or not 文件清单:
                    残留表.append(str(摘要路径.relative_to(系统根)))
        self.assertEqual(残留表, [], f"存在旧格式（能力数/缺文件清单）摘要: {残留表}")
        self.assertEqual(格式错误表, [], f"存在非法 JSON 摘要: {格式错误表}")

    def test_迁移可重算漂移包(self):
        """对临时漂移包执行迁移必须用唯一生成器重算（内容为当前文件）。"""
        目录, 能力文件 = 建临时包(包id="测试.迁移", 版本="1.0.0")
        摘要 = 生成完整性摘要(目录, 包id="测试.迁移", 版本="1.0.0")
        (目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        能力文件.write_text("值 = 5\n", encoding="utf-8")
        通过, _ = 校验完整性摘要(目录)
        self.assertFalse(通过, "篡改后必须先失败")
        # 用唯一生成器重算 → 校验通过
        新摘要 = 生成完整性摘要(目录, 包id="测试.迁移", 版本="1.0.0")
        (目录 / "完整性摘要.json").write_text(
            json.dumps(新摘要, ensure_ascii=False), encoding="utf-8")
        通过, 问题列表 = 校验完整性摘要(目录)
        self.assertTrue(通过, str(问题列表))


if __name__ == "__main__":
    unittest.main()
