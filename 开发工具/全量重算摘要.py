"""全量重算完整性摘要（改过包内文件后跑一次，避免漏掉聚合父包）。

为什么需要：某个包的 `完整性摘要.json` 登记了它目录下**每一个文件**，而
**聚合父包**又登记了子包里的文件 —— 所以「只重算自己改过的那几个包」必然漏父包
（本仓已因此漂移过多次）。本入口一次扫遍全部正式根，凡「磁盘 ≠ 重算」一律重算。

用法：
    python3.14 -m 开发工具.全量重算摘要          # 重算
    python3.14 -m 开发工具.全量重算摘要 --只报    # 只列不写
    python3.14 开发工具/全量重算摘要.py --只报    # 直接跑也支持（入口自备工程根导入路径）

未知参数一律拒绝（退出码 2）：本入口的默认动作是**写盘**，把拼错的开关当成
「确认写入」会静默重算上百个包的摘要，属不可接受的风险（2026-09-17 实测：
`--干跑` 这类自造词此前会被当成「写」，而本入口此前直接跑还会先撞导入错误）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

正式根表 = ("支持库", "模块库", "技能库", "平台控制面", "运行核心", "开发工具",
            "客户端", "启动监督器", "项目适配层", "公共契约")


def 把工程根放进导入路径(仓库根: Path) -> None:
    """把工程根放进 sys.path：`python3.14 开发工具/全量重算摘要.py` 从别处跑也要能导入仓库包。

    与同目录 `环境自检.py`／`验证场景体检.py`／`重建依赖锁.py` 同一范式 —— 这三个入口
    早已自备导入路径，本入口此前漏了，直接跑必报 `ModuleNotFoundError: 支持库`。
    """
    根 = str(仓库根)
    if 根 not in sys.path:
        sys.path.insert(0, 根)


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
    把工程根放进导入路径(仓库根)
    开关 = [项 for 项 in sys.argv[1:] if 项.startswith("-")]
    未知 = [项 for 项 in 开关 if 项 != "--只报"]
    if 未知:
        print(f"未知参数：{' '.join(未知)}；本入口只支持 --只报（只列不写），其余一律拒绝，不做任何写入。")
        return 2
    只报 = "--只报" in 开关
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
