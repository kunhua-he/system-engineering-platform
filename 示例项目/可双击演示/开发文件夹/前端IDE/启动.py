"""当前 demo 的轻代码前端 IDE 启动器。

编辑器实现复用平台开发工具；页面源文件固定落在本 demo 的前端目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

开发文件夹 = Path(__file__).resolve().parents[1]
项目根 = 开发文件夹.parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 开发工具.轻代码前端编辑器.启动编辑器 import 主函数


if __name__ == "__main__":
    raise SystemExit(主函数(
        端口=45081,
        文件=开发文件夹 / "前端" / "页面" / "主页.json",
    ))
