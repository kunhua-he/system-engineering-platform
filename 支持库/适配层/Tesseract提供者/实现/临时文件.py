"""临时文件：图片字节输入的临时落盘与即时清理（零残留）。

OCR 识别支持直接传入图片字节；库内先落盘到进程专属临时目录，
识别完成后无论成功/失败/超时/取消都在 finally 中整目录清理。
清理幂等：目录不存在或已清理时静默成功。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

临时目录前缀 = "Tesseract提供者_"
临时图片名 = "图片.png"


def 创建临时目录() -> Path:
    """创建进程专属临时目录（OS 临时根下，前缀标识）。"""
    return Path(tempfile.mkdtemp(prefix=临时目录前缀))


def 落盘图片(临时目录: Path, 图片字节: bytes) -> Path:
    """把图片字节写入临时目录（返回文件路径），供受管进程以相对名调用。"""
    图片路径 = 临时目录 / 临时图片名
    图片路径.write_bytes(图片字节)
    return 图片路径


def 清理临时目录(临时目录: Path | None) -> None:
    """整目录清理（含未写完的半成品），幂等；目录不存在静默成功。"""
    if 临时目录 is None:
        return
    try:
        if Path(临时目录).exists():
            shutil.rmtree(str(临时目录), ignore_errors=True)
    except OSError:
        pass
