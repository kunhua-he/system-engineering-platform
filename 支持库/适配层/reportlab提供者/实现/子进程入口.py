"""子进程入口：PDF 生成（reportlab）的独立进程 Worker。

本文件只在独立子进程中运行，由 实现/子进程管理器.py 通过 subprocess 启动。子进程内才
允许加载 reportlab —— 而且是调用**同包渲染器**（实现/生成PDF.py）的公开函数：reportlab
的渲染逻辑在本包只有一份实现，不在别处重复。

**本文件是「隔离子进程形态」的唯一实现**（后端腿 支持库/后端/文档转换支持库/PDF生成
的同名件已降为转调门面，两腿该模块名指向本模块对象）。

自举：入口解析 工程缓存/制品仓库/平台客户端环境/当前.json 激活指针（或 parents[5]），
把平台客户端环境目录加入 sys.path，使部署客户端（导入重写为 平台客户端. 前缀）与源码
布局（parents[4]）都可直接 import 本包实现，清空 PYTHONPATH 后最小调用仍成功。
**这段自举是部署布局下的必要能力，不得并入通用门面模板**：部署布局下入口位于
`平台客户端环境/平台客户端/支持库/适配层/reportlab提供者/实现/`，此时 `支持库` 既不
在 sys.path 上、包前缀也可能被重写成 `平台客户端.`，缺自举会
`ModuleNotFoundError: No module named '支持库'`（同仓 2026-09-20 实测过同一现象）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "生成", "内容参数": {...}}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

激活指针文件名 = "当前.json"
客户端环境环境变量名 = "reportlab提供者_客户端环境目录"
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
    if 环境目录 is not None and str(环境目录) not in sys.path:
        sys.path.insert(0, str(环境目录))
    _环境目录已注入 = True


系统根 = Path(__file__).resolve().parents[4]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))
注入平台客户端路径()

from 支持库.适配层.reportlab提供者.实现.生成PDF import 生成PDF as _唯一实现生成PDF  # noqa: E402


from 公共契约.运行时 import 子进程协议  # noqa: E402 - 单发协议唯一实现（平台根已在上方自举入 sys.path）


def _前置() -> str | None:
    """把平台客户端环境目录注入 sys.path（部署态导入前缀重写用）；本腿恒不失败。"""
    注入平台客户端路径()
    return None


def _生成(请求: dict) -> dict:
    """本腿唯一实现返回 ``结果`` 对象；转成协议信封（失败码兜底「生成失败」，与旧行为同口径）。"""
    结果值 = _唯一实现生成PDF(请求.get("内容参数"))
    if 结果值.成功:
        return {"成功": True, "值": 结果值.值}
    return {"成功": False, "错误码": str(结果值.错误码 or "生成失败"),
            "错误说明": str(结果值.错误说明 or "PDF 生成失败")}


def 主循环() -> int:
    """单发协议主循环；四类收口与信封组装唯一实现在 公共契约/运行时/子进程协议。"""
    return 子进程协议.单发主循环(
        {"生成": _生成},
        入口名="reportlab提供者",
        前置=_前置,
    )


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段（与同仓其它受管提供者子进程同一收口方式）
    os._exit(0)
