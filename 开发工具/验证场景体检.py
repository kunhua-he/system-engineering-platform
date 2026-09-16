"""验证场景格式体检：并行扫描源码与编译制品，一次性报出全部不合格场景（精确到文件与序号）。

用途：HTML 黑盒验证器报「验证场景字段不完整或为旧格式」时，直接跑本脚本即可拿到全部落点，
不必再逐个试。判据与 `开发工具/HTML验证/常量.py::场景契约版本`、
`场景加载.py::_解析多步骤场景` 保持一致，本文件只读不写。

用法：
    python3.14 开发工具/验证场景体检.py                  # 扫源码侧
    python3.14 开发工具/验证场景体检.py --制品 <制品目录>   # 额外扫制品侧
    python3.14 开发工具/验证场景体检.py --修             # 给缺失的「清理步骤」补空列表（需配合 --制品 则只报不修）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

场景键集 = {"场景id", "前置步骤", "目标步骤", "清理步骤"}


def _读常量(根: Path) -> str:
    """从常量.py 读场景契约版本（唯一权威，不硬编码）。"""
    for 行 in (根 / "开发工具" / "HTML验证" / "常量.py").read_text(encoding="utf-8").splitlines():
        行 = 行.strip()
        if 行.startswith("场景契约版本") and "=" in 行:
            return 行.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("未能从 开发工具/HTML验证/常量.py 读到场景契约版本")


def _收集(基: Path, 含缓存: bool = False) -> list[Path]:
    出: list[Path] = []
    for 底, 目录表, 文件表 in os.walk(基):
        if not 含缓存 and "工程缓存" in Path(底).parts:
            目录表[:] = []
            continue
        for f in 文件表:
            if f.endswith(".json") and "验证场景" in f:
                出.append(Path(底) / f)
    return 出


def _查一项(路径: Path, 场景契约版本: str) -> tuple[Path, list[str]]:
    问题: list[str] = []
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except Exception as 异常:
        return 路径, [f"JSON 读取失败 {type(异常).__name__}: {异常}"]
    if not isinstance(数据, dict):
        return 路径, ["顶层不是对象"]
    if 数据.get("契约版本") != 场景契约版本:
        问题.append(f"契约版本={数据.get('契约版本')!r} 期望 {场景契约版本!r}")
    if 路径.name == "验证场景引用.json":
        引用表 = 数据.get("验证场景引用")
        if not isinstance(引用表, list) or not 引用表:
            return 路径, 问题 + ["验证场景引用缺失或为空"]
        for 序, 引用 in enumerate(引用表):
            if not isinstance(引用, dict):
                问题.append(f"引用#{序} 不是对象")
                continue
            if "场景" in 引用:
                if set(引用) != {"场景"}:
                    问题.append(f"引用#{序} 内联键集={sorted(引用)} 期望 ['场景']")
                    continue
                内联 = 引用["场景"]
                if not isinstance(内联, dict):
                    问题.append(f"引用#{序} 内联场景不是对象")
                    continue
                if set(内联) != 场景键集:
                    缺 = sorted(场景键集 - set(内联))
                    多 = sorted(set(内联) - 场景键集)
                    问题.append(f"引用#{序} 内联场景键集 缺={缺} 多={多} (场景id={内联.get('场景id')!r})")
            elif "场景文件" in 引用:
                if set(引用) - {"场景文件", "场景id", "范围"}:
                    问题.append(f"引用#{序} 含未知字段={sorted(set(引用) - {'场景文件','场景id','范围'})}")
            else:
                问题.append(f"引用#{序} 既无「场景」也无「场景文件」")
    elif set(数据) == {"契约版本", "验证场景"}:
        # 老格式的场景文件（v1 之前的「一文件多场景」），当前引用已全部内联，不再被加载
        for 序, 项 in enumerate(数据.get("验证场景") or []):
            if not isinstance(项, dict) or set(项) != 场景键集:
                问题.append(f"场景#{序} 键集异常（老格式残留文件，未被引用）")
    return 路径, 问题


def 体检(基: Path, 场景契约版本: str, 并发: int = 32, 含缓存: bool = False) -> list[tuple[Path, list[str]]]:
    文件表 = _收集(基, 含缓存)
    起 = time.time()
    with ThreadPoolExecutor(并发) as 池:
        结果 = list(池.map(lambda p: _查一项(p, 场景契约版本), 文件表))
    坏 = [(p, q) for p, q in 结果 if q]
    print(f"[{基.name}] 扫描 {len(结果)} 个场景类文件，耗时 {time.time() - 起:.2f}s，不合格 {len(坏)} 个")
    return 坏


def 补清理步骤(根: Path, 坏表: list[tuple[Path, list[str]]]) -> int:
    """给内联场景缺失的「清理步骤」补空列表。只补这一种确定的旧格式缺陷。"""
    改动 = 0
    for 路径, 问题 in 坏表:
        if not any("内联场景键集" in x and "缺=['清理步骤']" in x for x in 问题):
            continue
        数据 = json.loads(路径.read_text(encoding="utf-8"))
        for 引用 in 数据.get("验证场景引用", []):
            内联 = 引用.get("场景") if isinstance(引用, dict) else None
            if isinstance(内联, dict) and "清理步骤" not in 内联:
                内联["清理步骤"] = []
        if 数据.get("验证场景引用"):
            for 引用 in 数据["验证场景引用"]:
                内联 = 引用.get("场景") if isinstance(引用, dict) else None
                if isinstance(内联, dict):
                    重排 = {k: 内联[k] for k in ("场景id", "前置步骤", "目标步骤", "清理步骤") if k in 内联}
                    内联.clear()
                    内联.update(重排)
            路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            改动 += 1
            print(f"  已补: {路径.relative_to(根)}")
    return 改动


def 主() -> int:
    解析 = argparse.ArgumentParser(description="验证场景格式体检")
    解析.add_argument("--根", default=str(Path(__file__).resolve().parent.parent))
    解析.add_argument("--制品", default="", help="额外扫描的编译制品目录（绝对路径或相对根）")
    解析.add_argument("--含缓存", action="store_true", help="源码侧也扫 工程缓存/（默认跳过：缓存里是历史制品副本，不可修）")
    解析.add_argument("--修", action="store_true", help="给缺失「清理步骤」的内联场景补空列表（只对源码侧）")
    参数 = 解析.parse_args()
    根 = Path(参数.根).resolve()
    场景契约版本 = _读常量(根)
    print(f"场景契约版本（读自常量.py）= {场景契约版本!r}\n")

    总坏: list[tuple[Path, list[str]]] = []
    for 标签, 基 in [("源码", 根)] + ([("制品", (根 / 参数.制品) if not os.path.isabs(参数.制品) else Path(参数.制品))] if 参数.制品 else []):
        if not 基.is_dir():
            print(f"[{标签}] 目录不存在，跳过: {基}")
            continue
        坏 = 体检(基, 场景契约版本, 含缓存=(标签 == "制品") or 参数.含缓存)
        总坏 += 坏
        for 路径, 问题 in 坏[:40]:
            try:
                显示 = 路径.relative_to(基)
            except ValueError:
                显示 = 路径
            print(f"  ✗ {显示}")
            for 一条 in 问题[:3]:
                print(f"      {一条}")

    if 参数.修:
        源码坏 = [(p, q) for p, q in 总坏 if 根 in p.parents]
        print(f"\n补「清理步骤」（源码侧）…")
        数 = 补清理步骤(根, 源码坏)
        print(f"补完 {数} 个文件；请重跑本脚本确认不合格归零。")
    return 1 if 总坏 else 0


if __name__ == "__main__":
    sys.exit(主())
