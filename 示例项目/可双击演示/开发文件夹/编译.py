"""把本 demo 的开发文件夹编译到日期命名的产物文件夹。"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import sys

根 = Path(__file__).resolve().parents[3]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))
from 开发工具.项目编译.项目编译器 import 编译项目

if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="编译可双击演示")
    解析器.add_argument("--名称", default="demo")
    解析器.add_argument("--输出", type=Path, default=None)
    参数 = 解析器.parse_args()
    开发目录 = Path(__file__).resolve().parent
    输出 = 参数.输出 or 开发目录.parent / "产物文件夹" / f"{datetime.now():%Y%m%d}-{参数.名称}"
    # 编译器读取项目根，因此把开发文件夹作为独立项目输入。
    结果 = 编译项目(开发目录, 输出)
    print(f"编译完成：{输出.resolve()}")
    print(f"支持库 {len(结果['支持库引用'])} 个，模块 {len(结果['模块引用'])} 个")
