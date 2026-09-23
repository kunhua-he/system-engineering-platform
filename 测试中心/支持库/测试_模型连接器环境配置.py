"""模型连接器环境配置：**非数值环境值**必须退回平台默认阈值（不是抛 NameError）。

背景（2026-09-23 潜伏缺陷复核）：
`支持库/后端/大语言模型支持库/模型连接器/实现/环境配置.py` 的 2026-09-19 搬运
（「从 `实现/模型连接器.py` 原样搬出」）只搬了函数体，`内存安全阈值`（= 0.80，
系统内存占用安全阈值的唯一事实源，现居 `实现/模型连接基元.py`）没随函数搬出：

    except ValueError:
        配置[规范键] = 内存安全阈值   # ← NameError

该分支的本意是「环境值写坏（`MODEL_MEMORY_SAFE_RATIO=abc`）时退回平台默认 0.80」，
一被触发就 NameError ⇒ 整个 `加载环境配置` 失败（连默认向量/重排模型等无关默认值
也一起拿不到）。既有用例从未喂过非数值环境值，故长期潜伏。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.支持库.测试_模型连接器环境配置 -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.大语言模型支持库.模型连接器.实现 import 环境配置 as 环境配置模块
from 支持库.后端.大语言模型支持库.模型连接器.实现.模型连接基元 import 内存安全阈值
from 支持库.后端.大语言模型支持库.模型连接器.实现.环境配置 import (
    加载环境配置,
    查询环境配置,
)
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


class 环境值非数值兜底(unittest.TestCase):
    def setUp(self) -> None:
        # `环境配置` 是全局账本（唯一写入点 = 加载环境配置），用例之间必须还原，
        # 否则本用例读到的环境值会污染同进程其它用例。
        self.原账本 = dict(环境配置模块.环境配置)

    def tearDown(self) -> None:
        环境配置模块.环境配置.clear()
        环境配置模块.环境配置.update(self.原账本)

    def test_内存安全阈值非数值退回默认阈值(self):
        with patch.dict(os.environ, {"MODEL_MEMORY_SAFE_RATIO": "abc"}, clear=False):
            结果 = 加载环境配置()
        self.assertTrue(结果.成功, 结果)
        self.assertEqual(内存安全阈值, 结果.值["配置摘要"]["内存安全阈值"])
        self.assertIsInstance(结果.值["配置摘要"]["内存安全阈值"], float)
        # 兜底不得连累无关默认值：默认向量/重排模型照旧补齐。
        self.assertEqual("Qwen3-Embedding-8B", 结果.值["配置摘要"]["默认向量模型"])
        self.assertEqual(0.8, 查询环境配置().值["内存安全阈值"])

    def test_内存安全阈值合法数值照旧生效(self):
        with patch.dict(os.environ, {"MODEL_MEMORY_SAFE_RATIO": "0.55"}, clear=False):
            结果 = 加载环境配置()
        self.assertEqual(0.55, 结果.值["配置摘要"]["内存安全阈值"])

    def test_环境文件里的非数值同样兜底(self):
        环境根 = tempfile.mkdtemp(prefix="环境配置_", dir=受管临时根)
        环境文件 = Path(环境根) / "本机.env"
        self.addCleanup(清只读后删除树, 环境根, 忽略失败=真)
        环境文件.write_text("MODEL_MEMORY_SAFE_RATIO=不是数\nDEFAULT_CONTEXT_LENGTH=也不是数\n",
                       encoding="utf-8")
        结果 = 加载环境配置(str(环境文件))
        self.assertTrue(结果.成功, 结果)
        self.assertEqual(内存安全阈值, 结果.值["配置摘要"]["内存安全阈值"])
        # 整数键走各自分支（非数值 → None），不得受阈值分支影响。
        self.assertIsNone(结果.值["配置摘要"]["默认上下文长度"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
