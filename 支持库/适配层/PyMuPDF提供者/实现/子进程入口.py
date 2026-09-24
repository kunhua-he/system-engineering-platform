"""子进程入口：PyMuPDF（fitz，原生 SWIG 扩展）独立子进程 Worker。

只在独立子进程中运行，由 实现/提供者.py 通过 subprocess 启动。
子进程内才允许 import fitz：SWIG 绑定在解释器关闭阶段可能段错误，
子进程完成后用 os._exit(0) 直接退出，跳过模块销毁，崩溃不影响
主进程/测试器/后端。fitz 操作逻辑见 子进程解析.py。

自足性（第二十五阶段 wp7）：子进程内 import 平台客户端 必须自足。
运行前提：依赖平台客户端制品已安装（激活指针 工程缓存/制品仓库/
平台客户端环境/当前.json 存在且指向已安装制品）。入口解析激活指针，
把平台客户端环境目录加入 sys.path（幂等），使 平台客户端 包可直接
import，无需外部 PYTHONPATH 桥接。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "检测加密页数"|"渲染整页"|"提取图像"|"校验PDF", ...}
响应：{"成功": true, "值": ...} | {"成功": false, "值": ...,
      "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[4]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

客户端环境目录名 = "工程缓存/制品仓库/平台客户端环境"
激活指针文件名 = "当前.json"
_平台客户端路径已注入 = False


def 平台客户端环境目录() -> Path:
    """平台客户端环境目录：默认 系统根/工程缓存/制品仓库/平台客户端环境。

    允许环境变量 PyMuPDF提供者_客户端环境目录 覆盖（测试/部署注入）。
    """
    覆盖 = os.environ.get("PyMuPDF提供者_客户端环境目录")
    if 覆盖:
        return Path(覆盖).resolve()
    return 系统根 / 客户端环境目录名


def 注入平台客户端路径() -> str | None:
    """解析激活指针并把平台客户端环境目录加入 sys.path（幂等）。

    成功返回 None；失败返回中文错误说明（制品缺失/激活指针不可读）。
    进程内重复调用不重复注入。
    """
    global _平台客户端路径已注入
    if _平台客户端路径已注入:
        return None
    if 系统根.name == "平台客户端" and (系统根 / "__init__.py").is_file():
        _平台客户端路径已注入 = True
        return None
    环境目录 = 平台客户端环境目录()
    指针文件 = 环境目录 / 激活指针文件名
    if not 指针文件.is_file():
        return f"平台客户端制品缺失：激活指针不存在（{指针文件}）"
    try:
        指针 = json.loads(指针文件.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        return f"平台客户端制品缺失：激活指针不可读（{错误}）"
    制品名 = 指针.get("制品目录", "")
    已安装目录 = 环境目录 / "平台客户端"
    # 兼容两种安装结构：新版制品根含 平台客户端 包层（环境/平台客户端/平台客户端/__init__.py），
    # 旧版平铺包内容（环境/平台客户端/__init__.py）。
    if 已安装目录.is_dir() and (已安装目录 / "平台客户端" / "__init__.py").is_file():
        注入目录 = 已安装目录
    elif 已安装目录.is_dir() and (已安装目录 / "__init__.py").is_file():
        注入目录 = 环境目录
    else:
        return f"平台客户端制品缺失：激活指针指向的制品目录未安装（{制品名 or '<空>'}）"
    if str(注入目录) not in sys.path:
        sys.path.insert(0, str(注入目录))
    _平台客户端路径已注入 = True
    return None


from 支持库.适配层.PyMuPDF提供者.实现.子进程解析 import (  # noqa: E402
    初始化, 检测加密页数, 渲染整页, 提取图像, 校验PDF,
)
from 支持库.适配层.PyMuPDF提供者.实现.子进程解析 import 禁用库环境变量名


from 公共契约.运行时 import 子进程协议  # noqa: E402 - 单发协议唯一实现（平台根已在上方自举入 sys.path）


def _禁用库表() -> set[str]:
    return {名.strip() for 名 in os.environ.get(禁用库环境变量名, "").split(",") if 名.strip()}


def _前置() -> str | None:
    """注入平台客户端路径并初始化禁用库表；注入失败即「提供者不可用」。"""
    注入错误 = 注入平台客户端路径()
    if 注入错误:
        return 注入错误
    初始化(_禁用库表())
    return None


def 主循环() -> int:
    """单发协议主循环；四类收口与信封组装唯一实现在 公共契约/运行时/子进程协议。"""
    操作表 = {
        "检测加密页数": lambda 请求: 检测加密页数(str(请求.get("文件路径") or "")),
        "渲染整页": lambda 请求: 渲染整页(str(请求.get("文件路径") or ""), 请求.get("页序号")),
        "提取图像": lambda 请求: 提取图像(str(请求.get("文件路径") or ""), 请求.get("页序号")),
        "校验PDF": lambda 请求: 校验PDF(str(请求.get("字节b64") or "")),
    }
    return 子进程协议.单发主循环(操作表, 入口名="PyMuPDF提供者", 前置=_前置)


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段的 SWIG 模块销毁（避免 PyMuPDF 段错误）
    os._exit(0)
