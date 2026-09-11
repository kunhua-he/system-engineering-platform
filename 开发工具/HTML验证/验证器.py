"""HTML 黑盒验证器 CLI 唯一入口。

用法：python3.14 -m 开发工具.HTML验证.验证器 [--制品 目录 | --制品指针 当前.json]
      （直接执行 python3.14 开发工具/HTML验证/验证器.py 亦可）
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# 项目根入 sys.path：本脚本既可 `-m`，也可直接执行（直接执行时项目根不在 path）。
系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "开发工具").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.HTML验证.常量 import (默认并发, 默认超时秒, 动态端口, 固定端口池)
from 开发工具.HTML验证.验证应用 import 主函数


def 解析参数() -> argparse.Namespace:
    解析器 = argparse.ArgumentParser(description="HTML 黑盒验证器：只验证包级真实场景")
    入口 = 解析器.add_mutually_exclusive_group(required=True)
    入口.add_argument("--制品", help="编译产物目录")
    入口.add_argument("--制品指针", help="编译器生成的当前.json 稳定版本指针")
    解析器.add_argument("--场景", default="", help="由包级引用生成且绑定制品摘要的场景束")
    解析器.add_argument("--并发", type=int, default=默认并发)
    解析器.add_argument("--超时秒", type=float, default=默认超时秒)
    解析器.add_argument("--端口", type=int, default=动态端口, help="制品监听端口，0=系统动态分配（默认，句柄回收即释放）；显式指定仅用于诊断")
    解析器.add_argument("--端口池", default=固定端口池, help="多实例端口池：45080-45180 区间或逗号枚举")
    解析器.add_argument("--实例数", type=int, default=1, help="制品进程实例数（>1 启用多实例制品池）")
    解析器.add_argument("--直连地址", default="", help="仅开发诊断：严格 IP 回环 HTTP 地址，带显式端口")
    解析器.add_argument("--激活到", default="", help="验证成功后原子写入当前.json 稳定指针")
    解析器.add_argument("--服务", type=int, default=0)
    解析器.add_argument("--只生成场景", action="store_true")
    return 解析器.parse_args()


if __name__ == "__main__":
    raise SystemExit(主函数(解析参数()))
