"""项目文档 模块 · 入库后台线程（进程内实现，不对外暴露）。

口径（华哥明确要求「后台单独拉一个线程去处理入库」）：

- **有界**：非守护线程、单次执行、硬超时（默认 30 秒），完成即退出；
  不做常驻线程池、不用跨调用存活的队列。
- **不阻塞落盘**：`写文档` 的文件已落盘即返回成功，入库在后台上做；
  线程内异常**只记录不抛给调用方**，并登记待补入库清单。
- **文件是权威、索引是派生**：入库失败不回滚文件（索引丢了可从文件重建）。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Callable

# 待补入库清单：入库线程失败的记录落在这里，供后续重建索引时补做。
待补清单文件名 = "项目文档待补入库.jsonl"
入库超时秒 = 30


def 线程状态目录() -> str:
    """入库线程状态目录（系统临时目录下的固定子目录，随系统清理，不写项目目录）。"""
    目录 = os.path.join(tempfile.gettempdir(), "项目文档入库")
    os.makedirs(目录, exist_ok=True)
    return 目录


def 登记待补(记录: dict[str, Any]) -> None:
    """把一条入库失败记录追加进待补清单；写清单本身失败也不抛（不反向影响主流程）。"""
    路径 = os.path.join(线程状态目录(), 待补清单文件名)
    try:
        with open(路径, "a", encoding="utf-8") as 文件:
            文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
    except OSError:
        pass


def 读待补清单() -> list[dict[str, Any]]:
    """读待补清单（每行一条 JSON；坏行跳过，不用坏行拖垮整个清单）。"""
    路径 = os.path.join(线程状态目录(), 待补清单文件名)
    if not os.path.isfile(路径):
        return []
    记录列表: list[dict[str, Any]] = []
    try:
        with open(路径, encoding="utf-8") as 文件:
            for 行 in 文件:
                行 = 行.strip()
                if not 行:
                    continue
                try:
                    记录 = json.loads(行)
                except json.JSONDecodeError:
                    continue
                if isinstance(记录, dict):
                    记录列表.append(记录)
    except OSError:
        return []
    return 记录列表


def 清空待补清单() -> None:
    """清空待补清单（重建索引全部补做成功后调用）。"""
    路径 = os.path.join(线程状态目录(), 待补清单文件名)
    if os.path.isfile(路径):
        try:
            os.remove(路径)
        except OSError:
            pass


def 起入库线程(任务: Callable[[], Any], 记录: dict[str, Any]) -> dict[str, Any]:
    """起一个**非守护、单次执行、带硬超时**的入库线程，立刻返回受理信息。

    `任务` 内部异常与超时都只登记进待补清单，**不向调用方抛**——
    调用方此时已拿到落盘成功的文件，不该因为派生数据失败被判失败。
    """
    异常盒: list[str] = []

    def 包一层() -> None:
        try:
            任务()
        except BaseException as 错误:  # noqa: BLE001 — 后台线程不向外抛，全部落待补
            异常盒.append(f"{type(错误).__name__}: {错误}")
            登记待补({**记录, "失败原因": 异常盒[-1]})

    线程 = threading.Thread(target=包一层, name="项目文档入库", daemon=False)
    线程.start()
    线程.join(入库超时秒)
    if 线程.is_alive():
        登记待补({**记录, "失败原因": f"入库超时（>{入库超时秒} 秒）"})
        return {"已受理": True, "是否完成": False, "说明": f"入库超过 {入库超时秒} 秒，已登记待补"}
    if 异常盒:
        return {"已受理": True, "是否完成": False, "说明": f"入库失败已登记待补：{异常盒[0]}"}
    return {"已受理": True, "是否完成": True, "说明": "入库完成"}
