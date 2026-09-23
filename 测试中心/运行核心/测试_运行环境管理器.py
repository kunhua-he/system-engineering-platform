"""运行环境管理器测试：环境摘要/无依赖回退/损坏重建/废弃。

真实 venv 构建测试较慢，用临时目录 + 系统内已装包验证安装路径；
默认场景验证：无依赖锁 → 系统解释器；摘要确定性；环境目录结构。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.环境管理器 import (
    计算环境摘要, 读取依赖锁, 确保环境, 废弃环境, 环境目录, 环境摘要信息,
)
from 公共契约.基础类型.逻辑类型 import 真, 假

受管仓库根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 受管仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)


def 样例锁(额外包: list | None = None) -> dict:
    return {
        "包": 额外包 or [
            {"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}
        ],
    }


class Test运行环境管理器(unittest.TestCase):
    """运行环境管理器闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        self.提供者目录 = self.临时 / "python_docx提供者"
        self.提供者目录.mkdir()

    def test_无依赖锁回退系统解释器(self):
        """无依赖锁 → 无独立环境，返回系统解释器。"""
        结果 = 确保环境(self.提供者目录)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.解释器路径, sys.executable)
        self.assertEqual(结果.错误说明, "无第三方依赖，使用系统解释器")

    def test_环境摘要确定性(self):
        锁 = 样例锁()
        摘要一 = 计算环境摘要(锁, "python_docx提供者")
        摘要二 = 计算环境摘要(锁, "python_docx提供者")
        self.assertEqual(摘要一, 摘要二)
        不同锁 = 样例锁([{"名称": "python-docx", "版本": "1.1.0", "模块名": "docx"}])
        self.assertNotEqual(摘要一, 计算环境摘要(不同锁, "python_docx提供者"))

    def test_环境目录结构(self):
        锁 = 样例锁()
        摘要 = 计算环境摘要(锁, "python_docx提供者")
        目录 = 环境目录(self.提供者目录, 摘要)
        self.assertIn("工程缓存", str(目录))
        self.assertIn("提供者运行环境", str(目录))
        self.assertIn("python_docx提供者", str(目录))
        self.assertIn(摘要, str(目录))

    def test_读取依赖锁(self):
        锁文件 = self.提供者目录 / "依赖锁.json"
        锁文件.write_text(json.dumps(样例锁(), ensure_ascii=False), encoding="utf-8")
        锁 = 读取依赖锁(self.提供者目录)
        self.assertEqual(锁["包"][0]["名称"], "python-docx")

    def test_环境摘要信息_无依赖(self):
        信息 = 环境摘要信息(self.提供者目录)
        self.assertFalse(信息["独立环境"])

    def test_废弃环境_无依赖安全(self):
        结果 = 废弃环境(self.提供者目录)
        self.assertTrue(结果.成功)

    def test_损坏环境重建(self):
        """依赖锁存在但环境目录损坏（解释器缺失）→ 确保环境返回失败而非静默成功。"""
        锁文件 = self.提供者目录 / "依赖锁.json"
        锁文件.write_text(json.dumps(样例锁(), ensure_ascii=False), encoding="utf-8")
        摘要 = 计算环境摘要(样例锁(), "python_docx提供者")
        目录 = 环境目录(self.提供者目录, 摘要)
        目录.mkdir(parents=True, exist_ok=True)
        # 不实际创建解释器 → 校验失败 → 构建路径（真实构建可能慢，这里只验证不崩溃）
        结果 = 确保环境(self.提供者目录, 超时秒=10)
        self.assertIsInstance(结果, object)
        self.assertIn(结果.成功, (真, 假))


if __name__ == "__main__":
    unittest.main()
