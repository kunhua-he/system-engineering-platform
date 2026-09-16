"""全量重算完整性摘要（改过包内文件后跑一次，避免漏掉聚合父包）。

为什么需要：某个包的 `完整性摘要.json` 登记了它目录下**每一个文件**，而
**聚合父包**又登记了子包里的文件 —— 所以「只重算自己改过的那几个包」必然漏父包
（本仓已因此漂移过多次）。本入口一次扫遍全部正式根，凡「磁盘 ≠ 重算」一律重算。

用法：
    python3.14 -m 开发工具.全量重算摘要          # 重算
    python3.14 -m 开发工具.全量重算摘要 --只报    # 只列不写
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

正式根表 = ("支持库", "模块库", "技能库", "平台控制面", "运行核心", "开发工具",
            "客户端", "启动监督器", "项目适配层", "公共契约")


def 全量重算(仓库根: Path, *, 只报: bool = False) -> list[str]:
    from 支持库.后端.组件规范支持库 import 生成完整性摘要, 校验完整性摘要

    结果: list[str] = []
    for 名 in 正式根表:
        基 = 仓库根 / 名
        if not 基.is_dir():
            continue
        for 摘要文件 in sorted(基.rglob("完整性摘要.json")):
            if "__pycache__" in 摘要文件.parts:
                continue
            目录 = 摘要文件.parent
            好, 问题 = 校验完整性摘要(目录)
            if 好:
                continue
            if 只报:
                结果.append(f"[待重算] {目录.relative_to(仓库根)}: {问题[:1]}")
                continue
            声明路径 = 目录 / "包声明.json"
            声明 = json.loads(声明路径.read_text(encoding="utf-8")) if 声明路径.is_file() else {}
            包id = 声明.get("包id") or 声明.get("提供者id") or 目录.name
            版本 = 声明.get("版本", "1.0.0")
            新 = 生成完整性摘要(目录, 包id=包id, 版本=版本)
            摘要文件.write_text(json.dumps(新, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            后, 问题2 = 校验完整性摘要(目录)
            结果.append(f"[已重算] {目录.relative_to(仓库根)}: 闭合={后} {问题2[:1]}")
    return 结果


def 入口() -> int:
    仓库根 = Path(__file__).resolve().parents[1]
    只报 = "--只报" in sys.argv
    结果 = 全量重算(仓库根, 只报=只报)
    if not 结果:
        print("全部闭合：无可重算项")
        return 0
    for 行 in 结果:
        print(" ", 行)
    print(f"共 {len(结果)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(入口())
