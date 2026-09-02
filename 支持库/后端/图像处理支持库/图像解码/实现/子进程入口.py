"""子进程入口：Pillow（PIL，C 原生扩展）独立子进程 Worker。

只在独立子进程中运行，由 实现/提供者.py 通过 subprocess 启动。
子进程内才允许 import PIL；子进程完成后用 os._exit(0) 直接退出，
跳过解释器关闭阶段的模块销毁，崩溃不影响主进程/测试器/后端。
Pillow 操作逻辑见 子进程解析.py。

自举（第二十八阶段 wp1）：入口解析 工程缓存/制品仓库/平台客户端环境/
当前.json 激活指针（或 parents[5]），把平台客户端环境目录加入 sys.path，
使部署客户端（导入重写为 平台客户端. 前缀）与源码布局（parents[4]）都
可直接 import 子进程解析，清空 PYTHONPATH 后最小调用仍成功。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "解码图像"|"像素统计"|"生成占位图"|"生成缩略图"|
      "图像EXIF转置"|"透明背景合成"|"计算感知哈希"|"缩放图像"|
      "重编码图像", ...}
响应：{"成功": true, "值": ...} | {"成功": false, "值": ...,
      "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

激活指针文件名 = "当前.json"
客户端环境环境变量名 = "Pillow提供者_客户端环境目录"
_环境目录已注入 = False


def 解析平台客户端环境目录() -> Path | None:
    """解析平台客户端环境目录（部署自举）：环境变量覆盖 → parents[5] → 系统根相对路径。

    仅当 当前.json 激活指针可读且指向已安装 平台客户端 制品时返回该目录；
    否则返回 None（源码布局，parents[4] 即可自举，无需激活指针）。
    """
    候选表: list[Path] = []
    覆盖 = os.environ.get(客户端环境环境变量名)
    if 覆盖:
        候选表.append(Path(覆盖).resolve())
    else:
        入口文件 = Path(__file__).resolve()
        候选表.append(入口文件.parents[5])
        候选表.append(Path(__file__).resolve().parents[4]
                       / "工程缓存" / "制品仓库" / "平台客户端环境")
    for 环境目录 in 候选表:
        指针文件 = 环境目录 / 激活指针文件名
        if not 指针文件.is_file():
            continue
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if 指针.get("制品目录") and (环境目录 / "平台客户端" / "__init__.py").is_file():
            return 环境目录
    return None


def 注入平台客户端路径() -> None:
    """把平台客户端环境目录加入 sys.path（幂等），支撑部署后重写导入前缀的入口。"""
    global _环境目录已注入
    if _环境目录已注入:
        return
    环境目录 = 解析平台客户端环境目录()
    if 环境目录 is not None:
        for 导入路径 in (环境目录, 环境目录 / "平台客户端"):
            if 导入路径.is_dir() and str(导入路径) not in sys.path:
                sys.path.insert(0, str(导入路径))
    _环境目录已注入 = True


系统根 = Path(__file__).resolve().parents[5]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))
注入平台客户端路径()

from 支持库.后端.图像处理支持库.图像解码.实现.子进程解析 import (  # noqa: E402
    初始化, 解码图像, 像素统计, 生成占位图, 生成缩略图, 图像EXIF转置,
    透明背景合成, 计算感知哈希, 缩放图像, 重编码图像, 禁用库环境变量名,
)


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False)


def _禁用库表() -> set[str]:
    return {名.strip() for 名 in os.environ.get(禁用库环境变量名, "").split(",") if 名.strip()}


def _输出(结果: dict) -> int:
    """输出结果；错误字典（含 错误码）转失败响应并保留 值。"""
    if 结果.get("错误码"):
        print(_响应(False, 值=结果.get("值"), 错误码=str(结果["错误码"]),
                     错误说明=str(结果.get("错误说明") or "子进程执行失败")))
        return 0
    print(_响应(True, 值=结果.get("值")))
    return 0


def 主循环() -> int:
    初始化(_禁用库表())
    请求行 = sys.stdin.readline()
    if not 请求行.strip():
        print(_响应(False, 错误码="参数不合法", 错误说明="空请求"))
        return 0
    try:
        请求 = json.loads(请求行)
    except json.JSONDecodeError as 错误:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"请求不是合法 JSON: {错误}"))
        return 0
    操作表 = {
        "解码图像": lambda 请求: 解码图像(str(请求.get("字节b64") or "")),
        "像素统计": lambda 请求: 像素统计(str(请求.get("字节b64") or "")),
        "生成占位图": lambda 请求: 生成占位图(
            请求.get("宽度"), 请求.get("高度"), 请求.get("占位类型"),
            请求.get("背景颜色"), 请求.get("前景颜色"), 请求.get("文本")),
        "生成缩略图": lambda 请求: 生成缩略图(
            str(请求.get("字节b64") or ""), 请求.get("最大边长")),
        "图像EXIF转置": lambda 请求: 图像EXIF转置(str(请求.get("字节b64") or "")),
        "透明背景合成": lambda 请求: 透明背景合成(
            str(请求.get("字节b64") or ""), 请求.get("背景颜色")),
        "计算感知哈希": lambda 请求: 计算感知哈希(
            str(请求.get("字节b64") or ""), 请求.get("哈希类型")),
        "缩放图像": lambda 请求: 缩放图像(
            str(请求.get("字节b64") or ""), 请求.get("宽度"), 请求.get("高度")),
        "重编码图像": lambda 请求: 重编码图像(
            str(请求.get("字节b64") or ""), 请求.get("格式"), 请求.get("质量")),
    }
    处理函数 = 操作表.get(str(请求.get("操作") or ""))
    if 处理函数 is None:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{请求.get('操作')}'"))
        return 0
    try:
        return _输出(处理函数(请求))
    except Exception as 错误:
        print(_响应(False, 错误码="提供者崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段的模块销毁
    os._exit(0)
