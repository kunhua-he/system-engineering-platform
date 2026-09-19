"""隔离腿唯一化收口回归：适配层腿为唯一实现，后端成对包降为转调门面（结构债 D-1/D-2）。

锁死的判据（改坏必红）：
1. 两组「逐字节相同」的业务代码已被收口 —— 后端腿实现文件不再是第二份实现
   （sha256 与适配层腿不同、且不是 360 行 / 38 行的原始实现体）；
2. 后端腿那个模块名与适配层腿那唯一实现**是同一个模块对象**（`sys.modules[__name__]` 同一化），
   且 `__name__` 指向适配层腿（证明"谁承载实现"没有漂移回去）；
3. 门面必须"文件缺失即明确报错"，不得静默降级；
4. 后端腿能力仍然真实可用（真实调用，非 import 假绿）。

为什么必须有本测试：收口前那两份是**逐字节相同**的完整实现，任何一次"顺手粘贴回来"都会
让两条腿重新分叉且**不报任何错**（同名文件、行为可能不同）。本测试是那个静默漂移的唯一机器判据。
"""

from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

系统根 = Path(__file__).resolve().parents[2]

# 已收口的「逐字节相同」两组（后端腿实现文件 → 适配层腿唯一实现）
收口对 = (
    {
        "名": "Pillow/图像解码",
        "后端文件": 系统根 / "支持库" / "后端" / "图像处理支持库" / "图像解码" / "实现" / "子进程解析.py",
        "适配层文件": 系统根 / "支持库" / "适配层" / "Pillow提供者" / "实现" / "子进程解析.py",
        "后端模块名": "支持库.后端.图像处理支持库.图像解码.实现.子进程解析",
        "唯一实现名": "支持库.适配层.Pillow提供者.实现.子进程解析",
        "适配层包": "支持库.适配层.Pillow提供者",
        "原实现行数": 360,
        "原实现特征串": "def 解码图像(字节b64",
    },
    {
        "名": "Tesseract/OCR识别",
        "后端文件": 系统根 / "支持库" / "后端" / "OCR识别支持库" / "OCR识别" / "实现" / "临时文件.py",
        "适配层文件": 系统根 / "支持库" / "适配层" / "Tesseract提供者" / "实现" / "临时文件.py",
        "后端模块名": "支持库.后端.OCR识别支持库.OCR识别.实现.临时文件",
        "唯一实现名": "支持库.适配层.Tesseract提供者.实现.临时文件",
        "适配层包": "支持库.适配层.Tesseract提供者",
        "原实现行数": 38,
        "原实现特征串": "def 落盘图片(",
    },
)

最小PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _sha256(路径: Path) -> str:
    return hashlib.sha256(路径.read_bytes()).hexdigest()


class Test隔离腿唯一化收口(unittest.TestCase):
    """逐字节相同组必须只剩一份实现，另一条腿只是转调门面。"""

    def test_两组都已收口_后端腿不再是第二份实现(self):
        for 对 in 收口对:
            后端 = 对["后端文件"]
            适配层 = 对["适配层文件"]
            self.assertTrue(后端.is_file(), f"{对['名']}：后端腿实现文件缺失 {后端}")
            self.assertTrue(适配层.is_file(), f"{对['名']}：适配层唯一实现缺失 {适配层}")
            self.assertNotEqual(
                _sha256(后端), _sha256(适配层),
                f"{对['名']}：后端腿与适配层腿又变成逐字节相同 —— 第二份实现回来了",
            )
            行数 = len(后端.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(
                行数, 45,
                f"{对['名']}：后端腿实现文件 {行数} 行，疑似把完整实现粘贴回来（收口后应为薄门面）",
            )
            # 最硬的判据：原实现的特征函数体不得再出现在后端腿
            self.assertNotIn(
                对["原实现特征串"], 后端.read_text(encoding="utf-8"),
                f"{对['名']}：后端腿重新出现原实现特征「{对['原实现特征串']}」—— 第二份实现回来了",
            )

    def test_门面指向适配层腿且缺失即报错(self):
        for 对 in 收口对:
            源 = 对["后端文件"].read_text(encoding="utf-8")
            self.assertIn(对["唯一实现名"], 源, f"{对['名']}：门面未指向适配层唯一实现名")
            self.assertIn(
                "sys.modules[__name__] = sys.modules[唯一实现名]", 源,
                f"{对['名']}：门面缺少「同一模块对象」收口语句",
            )
            self.assertIn(
                "raise ImportError", 源,
                f"{对['名']}：门面缺少「唯一实现缺失即明确报错」，有静默降级风险",
            )

    def test_模块对象同一化_实现承载方是适配层腿(self):
        for 对 in 收口对:
            __import__(对["后端模块名"])
            后端模块 = sys.modules[对["后端模块名"]]
            适配层模块 = sys.modules[对["唯一实现名"]]
            self.assertIs(
                后端模块, 适配层模块,
                f"{对['名']}：后端腿模块名与适配层唯一实现不是同一个模块对象（又分叉了）",
            )
            self.assertEqual(
                后端模块.__name__, 对["唯一实现名"],
                f"{对['名']}：模块对象归属漂移，实现在「{后端模块.__name__}」而不在适配层腿",
            )

    def test_后端腿能力真实可用_非import假绿(self):
        from 支持库.后端.图像处理支持库.图像解码 import 解码图像, 像素统计

        解码 = 解码图像(最小PNG)
        self.assertTrue(解码.成功, 解码.错误说明)
        self.assertEqual(解码.值["格式"], "PNG")
        统计 = 像素统计(最小PNG)
        self.assertTrue(统计.成功, 统计.错误说明)
        self.assertEqual(统计.值["像素数"], 1)

    def test_临时文件门面四个公开名齐全(self):
        from 支持库.后端.OCR识别支持库.OCR识别.实现 import 临时文件 as 后

        for 名 in ("临时目录前缀", "创建临时目录", "落盘图片", "清理临时目录"):
            self.assertTrue(hasattr(后, 名), f"临时文件门面缺公开名 {名}")
        self.assertEqual(后.临时目录前缀, "Tesseract提供者_")


if __name__ == "__main__":
    unittest.main()
