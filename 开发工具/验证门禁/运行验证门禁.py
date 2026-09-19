"""验证门禁统一入口：依次跑三个只读检查器，汇总成**唯一 0/1 判据**。

为什么要这个入口（哲学 1.4 空转即杀 / 8.2 门禁不能只报不拦）：
编译口/发布门禁接线时只认一个模块名与一个退出码；三个检查器各自可独立跑，
但接线需要「一条命令、一个结论」。本入口不复制任何判据 —— 它只做三件事：
拼命令行、读子进程退出码、把退出码合成 0/1。**退出码不是 0 的检查器一律不改写**。

判据（唯一 0/1）：
- 三个检查器**全部**退出码 0 → 本入口 0；
- 任一个非 0（含 1=判红、2=用法错、超时/无法执行）→ 本入口 1；
- **未核验不算通过**：子进程超时或无法执行 → 记 -1 → 本入口 1（fail-closed）。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

门禁目录 = Path(__file__).resolve().parent
系统根 = 门禁目录.parents[1]

#: 三个检查器（文件 → 中文名）。顺序 = 输出顺序。
检查器表: tuple[tuple[str, str], ...] = (
    ("同动作双路径检测.py", "同动作两条路"),
    ("调用腿唯一性检测.py", "调用腿唯一性"),
    ("技能库绕网关检测.py", "技能库绕网关"),
)

单项超时秒 = 180


def _跑(脚本: Path, 参数表: list[str]) -> tuple[int, str, float]:
    开始 = time.monotonic()
    try:
        完成 = subprocess.run(
            [sys.executable, str(脚本), *参数表],
            capture_output=True, text=True, timeout=单项超时秒, cwd=str(系统根),
        )
        输出 = ((完成.stdout or "") + (完成.stderr or "")).rstrip()
        return 完成.returncode, 输出, time.monotonic() - 开始
    except subprocess.TimeoutExpired:
        return -1, f"超时（>{单项超时秒}秒，按未核验处理，绝不按通过处理）", time.monotonic() - 开始
    except (OSError, UnicodeDecodeError) as 错误:
        return -1, f"无法执行：{错误}", time.monotonic() - 开始


def main(argv: list[str] | None = None) -> int:
    实参 = list(sys.argv[1:] if argv is None else argv)
    # 透传参数（--根 / --基线 / --写基线 / --自证）给每个检查器。
    未核验: list[str] = []
    红项: list[str] = []
    print("══ 验证门禁 统一入口（三个只读检查器）══")
    for 文件名, 中文名 in 检查器表:
        脚本 = 门禁目录 / 文件名
        if not 脚本.is_file():
            未核验.append(f"{中文名}（脚本不存在：{脚本}）")
            print(f"  [{中文名}] 无法执行：脚本不存在 {脚本}")
            continue
        退出码, 输出, 耗时 = _跑(脚本, 实参)
        尾部 = " ｜ ".join(输出.splitlines()[-3:]) if 输出 else "无输出"
        print(f"  [{中文名}] 退出码={退出码} 耗时={耗时:.2f}s：{尾部}")
        if 退出码 == -1:
            未核验.append(f"{中文名}（{输出[:80]}）")
        elif 退出码 != 0:
            红项.append(f"{中文名}（退出码 {退出码}）")
    if 未核验:
        print(f"结论：未核验 —— {'、'.join(未核验)}（fail-closed，退出 1）")
        return 1
    if 红项:
        print(f"结论：红 —— {'、'.join(红项)}（退出 1）")
        return 1
    print("结论：绿 —— 三个检查器全部退出 0（新增违规 0；存量以各自基线为准）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
