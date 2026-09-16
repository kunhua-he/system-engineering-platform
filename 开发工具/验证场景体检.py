"""验证场景体检：并行扫描源码与编译制品，一次性报出全部不合格场景（精确到包目录与原因）。

判据**不复制、不猜**：直接调用验证器自己的解析链
（`开发工具.HTML验证.场景加载._解析场景引用` + `_解析多步骤场景`），
验证器将来加任何新规则，本体检器自动跟上，永不漂移。

> 血泪教训（2026-09-17，两次踩坑，别重蹈）：
> ① **判据不能猜**：先前按 `契约版本 == "2.0.0"` 猜，把 133 个合法的「引用文件」全误报成不合格；
>    真判据是 `开发工具/HTML验证/常量.py::场景契约版本 = "验证场景/v1"`。
> ② **只调 `_解析场景引用` 不够**：它只读文件、不校验步骤断言；断言判据在下一层
>    `_解析多步骤场景`（它才调 `验证步骤.从字典` → `_解析断言`）。只调第一层会得到
>    「0 不合格」的假绿，而验证器照样阻断。两层都调才算跑完判据。

用法：
    python3.14 开发工具/验证场景体检.py                    # 扫源码侧
    python3.14 开发工具/验证场景体检.py --制品 <制品目录>     # 额外扫制品侧
    python3.14 开发工具/验证场景体检.py --含缓存              # 源码侧也扫 工程缓存/
    python3.14 开发工具/验证场景体检.py --修                  # 批量修两类确定缺陷（只动源码侧）
    python3.14 开发工具/验证场景体检.py --覆盖 <制品目录>      # 覆盖率预检：公开能力取自制品 + 场景取自源码，**不重编译**就能报出还缺谁
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _载入判据(根: Path):
    """载入验证器自己的解析链，保证判据零漂移。"""
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    from 开发工具.HTML验证 import 场景加载

    return 场景加载


def _收集包目录(基: Path, 含缓存: bool = False) -> list[Path]:
    """找出所有含 `验证场景引用.json` 的包目录（验证器也是按包目录加载的）。"""
    出: list[Path] = []
    for 底, 目录表, 文件表 in os.walk(基):
        if not 含缓存 and "工程缓存" in Path(底).parts:
            目录表[:] = []
            continue
        if "验证场景引用.json" in 文件表:
            出.append(Path(底))
    return 出


def 查一包(目录: Path, 场景加载) -> tuple[Path, str]:
    """跑完整解析链：引用解析 + 每个场景的步骤/断言解析。"""
    try:
        场景表 = 场景加载._解析场景引用(目录)
    except Exception as 异常:
        return 目录, f"{type(异常).__name__}: {异常}"
    for 原始, 包目录 in 场景表:
        try:
            场景加载._解析多步骤场景(原始, 包目录, "体检")
        except Exception as 异常:
            return 目录, f"{type(异常).__name__}: {异常}"
    return 目录, ""


def 体检(基: Path, 场景加载, 含缓存: bool = False, 并发: int = 32) -> list[tuple[Path, str]]:
    包目录表 = _收集包目录(基, 含缓存)
    起 = time.time()
    with ThreadPoolExecutor(并发) as 池:
        结果 = list(池.map(lambda p: 查一包(p, 场景加载), 包目录表))
    坏 = [(d, q) for d, q in 结果 if q]
    print(f"[{基.name}] 扫描 {len(结果)} 个含场景的包目录，耗时 {time.time() - 起:.2f}s，不合格 {len(坏)} 个")
    return 坏


def 批量修(根: Path) -> int:
    """只修**判据明确**的两类确定缺陷，其余一律不碰、只报：
    ① 内联场景缺「清理步骤」→ 补空列表（验证器要求严格四键）；
    ② 负向断言（预期.成功=false）在 `返回断言` 里缺顶层「错误码」，而 `关键值.错误码` 有值
       → 提到顶层（照 `平台控制面/需求登记` 的既有正确写法：顶层与关键值同时存在）。
    """
    改动 = 0
    for 目录 in _收集包目录(根, 含缓存=False):
        引用文件 = 目录 / "验证场景引用.json"
        数据 = json.loads(引用文件.read_text(encoding="utf-8"))
        变了 = False
        for 引用 in 数据.get("验证场景引用", []):
            内联 = 引用.get("场景") if isinstance(引用, dict) else None
            if not isinstance(内联, dict):
                continue
            if "清理步骤" not in 内联:
                内联["清理步骤"] = []
                变了 = True
            for 阶段 in ("前置步骤", "目标步骤", "清理步骤"):
                for 步骤 in 内联.get(阶段) or []:
                    if not isinstance(步骤, dict):
                        continue
                    预期 = 步骤.get("预期")
                    if not isinstance(预期, dict) or 预期.get("成功") is not False:
                        continue
                    断言 = 预期.get("返回断言")
                    if not isinstance(断言, dict) or 断言.get("错误码"):
                        continue
                    候选 = (断言.get("关键值") or {}).get("错误码")
                    if isinstance(候选, str) and 候选:
                        断言["错误码"] = 候选
                        变了 = True
            重排 = {k: 内联[k] for k in ("场景id", "前置步骤", "目标步骤", "清理步骤") if k in 内联}
            for k in list(内联):
                if k not in 重排:
                    重排[k] = 内联[k]
            内联.clear()
            内联.update(重排)
        if 变了:
            引用文件.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            改动 += 1
            print(f"  已修: {引用文件.relative_to(根)}")
    return 改动


def 覆盖预检(根: Path, 制品: Path) -> tuple[bool, str]:
    """用**制品的公开能力** + **源码的场景**跑验证器自己的全集判据，无需重编译。

    为什么单独做：验证器只能对**已编译制品**跑，于是常见工作循环是「改场景 → 重编译（~20 秒）
    → 跑验证器 → 才发现还缺谁」。本函数把「公开能力」与「场景」两个来源拆开取值
    （能力集不受场景改动影响，取自现存制品；场景取自当前源码），一次调用就能拿到
    「还缺哪些能力没有正向目标步骤」的确定答案。

    依赖：制品目录必须已存在（只用它读公开能力，不校验其场景）。
    """
    from 开发工具.HTML验证.制品事实 import _扫描公开能力
    from 开发工具.HTML验证.场景加载 import _解析场景引用, _校验场景全集

    公开能力 = _扫描公开能力(Path(制品))[0]
    场景原始表: list = []
    for 目录 in _收集包目录(根, 含缓存=False):
        场景原始表 += _解析场景引用(目录)
    try:
        _校验场景全集(公开能力, 场景原始表, "预检")
        return True, f"公开能力 {len(公开能力)} 个全部有正向目标步骤（源码场景 {len(场景原始表)} 条）"
    except Exception as 异常:
        return False, f"{type(异常).__name__}: {异常}"


def 主() -> int:
    解析 = argparse.ArgumentParser(description="验证场景格式体检（判据直连验证器解析链）")
    解析.add_argument("--根", default=str(Path(__file__).resolve().parent.parent))
    解析.add_argument("--制品", default="", help="额外扫描的编译制品目录（绝对路径或相对根）")
    解析.add_argument("--覆盖", default="", help="覆盖率预检：用该制品（或相对根的路径）的公开能力 + 源码场景跑全集判据，不重编译")
    解析.add_argument("--含缓存", action="store_true", help="源码侧也扫 工程缓存/（默认跳过：缓存里是历史制品副本，不可修）")
    解析.add_argument("--修", action="store_true", help="批量修两类确定缺陷（只动源码侧）")
    参数 = 解析.parse_args()
    根 = Path(参数.根).resolve()
    场景加载 = _载入判据(根)

    if 参数.覆盖:
        制品 = Path(参数.覆盖) if os.path.isabs(参数.覆盖) else 根 / 参数.覆盖
        if not 制品.is_dir():
            print(f"[覆盖预检] 制品目录不存在: {制品}")
            return 1
        print(f"[覆盖预检] 公开能力取自: {制品}")
        通过, 详情 = 覆盖预检(根, 制品)
        print(("  ✅ " if 通过 else "  ❌ ") + 详情)
        if not 通过:
            return 1

    if 参数.修:
        print("批量修（只动源码侧，只修判据明确的两类）…")
        数 = 批量修(根)
        print(f"修完 {数} 个文件。\n")

    总坏: list[tuple[Path, str]] = []
    目标表 = [("源码", 根, 参数.含缓存)]
    if 参数.制品:
        制品基 = Path(参数.制品) if os.path.isabs(参数.制品) else 根 / 参数.制品
        目标表.append(("制品", 制品基, True))
    for 标签, 基, 含缓存 in 目标表:
        if not 基.is_dir():
            print(f"[{标签}] 目录不存在，跳过: {基}")
            continue
        坏 = 体检(基, 场景加载, 含缓存)
        总坏 += 坏
        for 目录, 问题 in 坏[:40]:
            try:
                显示 = 目录.relative_to(基)
            except ValueError:
                显示 = 目录
            print(f"  ✗ {显示}")
            print(f"      {问题}")
    if 总坏:
        print(f"\n合计不合格 {len(总坏)} 个包目录。")
    else:
        print("\n全部通过：0 个不合格。")
    return 1 if 总坏 else 0


if __name__ == "__main__":
    sys.exit(主())
