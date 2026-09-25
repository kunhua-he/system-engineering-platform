"""说明书生成器测试：真实包生成结构完整/重复生成拒绝覆盖/路径逃逸拒绝。

覆盖：能力id/参数表/返回结构/错误码表/调用示例/验证状态六要素齐全、
骨架示例如实标注、输出根目录不存在拒绝、符号链接逃逸拒绝。

★ 样例包换腿（2026-09-25，批R·R-28 的测试侧跟进）：原样例是
`支持库/适配层/Pillow提供者`。按 `开发文档/分析/批R单据_R28_T1能力面合并_20260924.md`
§一/§三判据 1（华哥裁决①「适配层孪生能力面删、保留后端腿 id」），该包 9 条 `图像解码.*`
能力面**已删**（`能力列表` → `[]`），同名能力面收归后端腿
`支持库/后端/图像处理支持库/图像解码`（对外 id 不变，生产调用点零改动）。
⇒ 样例包改指**后端腿**（同一个 `包声明.json` 的 `名称` 仍写「Pillow提供者」，9 条能力面与
参数/错误码逐条一致），**没有删用例、没有放宽断言**：只有两处随**真实渲染结果**逐字更新 ——
①「验证状态」一行按后端腿 `验证场景引用.json` 的真实登记形态（内嵌 `场景` 对象 ⇒ 渲染
`场景id（本包 验证场景引用.json，N 步）`）；②一级标题按 `生成说明书文本` 的真实口径
（`f"# {包目录.name} 使用说明"`，取**包目录名**「图像解码」，不是 `包声明.json` 的 `名称`）。
其余断言原样。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.组件规范支持库 import (
    生成说明书, 生成说明书文本, 校验输出目标,
)

系统根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真


#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)
#: 样例包 = 图像解码的**唯一腿**（后端腿）；理由见模块 docstring「样例包换腿」。
图像解码包 = 系统根 / "支持库" / "后端" / "图像处理支持库" / "图像解码"


class Test说明书生成器(unittest.TestCase):
    """说明书生成器闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        self.输出根 = self.临时 / "输出"
        self.输出根.mkdir()

    def test_真实图像解码包生成结构完整(self):
        """对真实后端腿生成说明书，六要素齐全。"""
        目标 = 生成说明书(图像解码包, self.输出根)
        self.assertTrue(目标.is_file())
        文本 = 目标.read_text(encoding="utf-8")
        for 片段 in [
            # ★ 2026-09-25：标题取自**包目录名**（`生成说明书文本` 第 158 行
            # `f"# {包目录.name} 使用说明"`），不是 `包声明.json` 的 `名称`。样例换腿后
            # 包目录名是 `图像解码`（`名称` 仍写「Pillow提供者」，只用于人读，不参与渲染）
            # ⇒ 断言按真实渲染结果逐字跟上，判据强度不变（仍是 assertIn 真标题）。
            "# 图像解码 使用说明",
            "## 能力清单",
            "图像解码.解码图像",
            "图像解码.像素统计",
            "图像解码.生成占位图",
            "**参数表**",
            "| 参数 | 类型 | 必填 | 默认值 | 说明 |",
            "**返回结构**",
            "**错误码表**",
            "**调用示例**",
            "```python",
            "**验证状态**",
            "已纳入验证场景：图像解码.真实最小图像全能力"
            "（本包 验证场景引用.json，9 步）",
        ]:
            self.assertIn(片段, 文本)

    def test_参数表含必填与默认值(self):
        文本 = 生成说明书文本(图像解码包)
        self.assertIn("| 字节 | 字节集型 | 是 | None | 图像字节内容", 文本)
        self.assertIn("| 超时秒 | 双精度数型 | 否 | 60 | 子进程超时", 文本)

    def test_骨架示例如实标注(self):
        """能力搜索数据无现成示例时按参数生成骨架并标注需验证。"""
        文本 = 生成说明书文本(图像解码包)
        self.assertIn("图像解码.解码图像(字节=值, 超时秒=值)", 文本)
        self.assertIn("示例为骨架需验证：能力搜索数据无现成示例，按参数自动生成。", 文本)

    def test_重复生成拒绝覆盖(self):
        生成说明书(图像解码包, self.输出根)
        with self.assertRaises(FileExistsError):
            生成说明书(图像解码包, self.输出根)
        with self.assertRaises(FileExistsError):
            校验输出目标(图像解码包, self.输出根)

    def test_路径逃逸拒绝(self):
        """输出根目录下说明目录为符号链接指向外部 → 拒绝。"""
        外部 = self.临时 / "外部"
        外部.mkdir()
        说明目录 = self.输出根 / "说明"
        try:
            说明目录.symlink_to(外部, target_is_directory=True)
        except OSError:
            self.skipTest("当前环境不支持符号链接")
        with self.assertRaises(ValueError):
            生成说明书(图像解码包, self.输出根)

    def test_输出根目录不存在拒绝(self):
        with self.assertRaises(ValueError):
            生成说明书(图像解码包, self.临时 / "不存在")


if __name__ == "__main__":
    unittest.main()
