"""任务记忆包读写工具（命令行入口，见包 `__init__` 的说明）。"""

from __future__ import annotations

import sys
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]

#: 记忆包文件名（固定后缀，便于按 开工ID 查找与清理）。
后缀 = ".md"


def 记忆目录() -> Path:
    """任务记忆包目录：**经唯一运行缓存解析器**，禁止裸拼 `工程缓存`。

    为什么必须走解析器：制品运行时（`平台客户端` 进程）裸拼会把记忆包写进不可变制品内部；
    解析器会按「环境显式覆盖 → 制品稳定根 → 源码工程缓存」给出正确落点。
    """
    from 公共契约.运行时.运行缓存 import 解析运行缓存根

    return 解析运行缓存根(仓库根) / "任务记忆"


def 路径(开工ID: str) -> Path:
    """按 开工ID 得到记忆包绝对路径。"""
    return 记忆目录() / f"{开工ID}{后缀}"


def 写(开工ID: str, 题目: str, 正文: str) -> Path:
    """写一份记忆包，返回落盘路径。正文为空即拒绝（空记忆包等于没注入）。"""
    if not 开工ID.strip():
        raise ValueError("开工ID 不能为空")
    if not 正文.strip():
        raise ValueError("记忆正文不能为空（空记忆包等于没注入）")
    目标 = 路径(开工ID.strip())
    目标.parent.mkdir(parents=True, exist_ok=True)
    目标.write_text(f"# {开工ID} · {题目.strip()}\n\n{正文.rstrip()}\n", encoding="utf-8")
    return 目标


#: 通用开工纪律：**每次读记忆包都会附在最前**。
#:
#: 为什么放在这里（华哥 2026-09-18 要求「时不时看看开发效率，总结一下为什么慢」）：
#: `开发工具/开发效率巡检.py` 实测本批 2004 次工具调用的分布是
#: `terminal 66.5%`、其中 `cat/head/tail/sed` 读文件 232 次、一次性 python 66 次、
#: 全仓 grep 70 次、命令超时 4 次（白等 12 分钟）。这些**不是能力问题，是姿势问题** ——
#: 但任务书里逐条叮嘱会被忽略（任务书长 ≥ 反而没人读）。
#: 附在记忆包里最省事：子代理必然读记忆包，一读就看到；改一处、全批生效。
通用开工纪律 = """## 开工通用纪律（实测总结，照做省时间）

**工具用法**（本批实测：terminal 占 66.5%，大半是姿势浪费）
- 读文件用 `read_file`，**不要** `cat/head/tail/sed`（实测 232 次）。read_file 带行号、可翻页、不吃 shell 开销。
- 找文件用 `search_files`，**不要** `ls -R` / `find`。
- 查符号**先查代码地图**（已同步 19,744 节点 / 972 文件），**不要**全仓 `grep -r`（实测 70 次）：
  `代码地图支持库.代码地图.查询节点(关键词=..., 代码地图路径=...)` → 直接拿到 `文件:行号`，再定向核。
- 成组动作**落一个脚本跑一次**，别反复 `python3.14 -c`（实测 66 次，每次都付解释器冷启动）。
- **命令必须带超时**：本机无 `timeout`/`gtimeout`；全仓扫描实测 4 次 180 秒超时 = 白等 12 分钟。
  用 `subprocess.run(..., timeout=N)` 或 `timeout` 参数，超时就报错，别让它挂着。

**纪律**（违反即返工）
- **记忆包是只读输入**：不许改写、不许在本目录新增文件。回传只写在最终回答；确要落盘写
  `开发文档/分析/<任务名>_回传_20260918.md`。
- **临时脚本一律放 `/private/tmp/系统平台临时脚本_20260918/`**，禁止留在仓库内。
- **提交三件套（★ 实测踩过：别人已暂存的文件被卷进你的提交）**：
  1. `git status --short` 先看**索引里有没有别人的**（第二列是工作树，**第一列非空 = 已在索引**）；
  2. **`git commit -m "…" -- <精确路径1> <精确路径2>`** —— **commit 也必须带 pathspec**！
     只 `git add` 自己文件、却跑不带 pathspec 的 `git commit`，会把**别的会话已经 staged 的文件
     一起提交**（索引是全局共享的，不是你私有的）；
  3. 提交后 `git show --stat HEAD` 核对**文件数与你预期一致**。
- **禁止 `git add -A` / `git add .`**。
- **自述「已提交」必须附提交哈希**；只 `git add` 没 `commit` 不算完成。
- **命令环境**：项目全线用 `python3.14`（`python3` 是 3.9.6）；跑前 `unset PYTHONPATH`；
  `node` 在 `/usr/local/bin`。
- **哲学 3.1**：同一现象连续两次失败 → **停手转原理级调查**，不许「换个参数再试」。
- **反向验证必须做**：故意弄坏 → 必须变红 → 还原 → 必须恢复绿；末尾一定还原。
- 工作区卫生：并行期**不动**在途 worktree；核验前提一律 `git show HEAD:<文件>`。

"""


def 读(开工ID: str) -> str:
    """读一份记忆包原文（**前面附通用开工纪律**）；不存在即明确报错。

    为什么附纪律（而不是返回空串或不附）：不存在时报错不返回空串，是防止子代理把
    「没注入」误当成「没内容」；附纪律是因为本批实测的效率黑洞都是姿势问题，
    附在必读路径上最省事。
    """
    目标 = 路径(开工ID.strip())
    if not 目标.is_file():
        raise FileNotFoundError(f"任务记忆包不存在：{目标}（开工ID={开工ID}）")
    return 通用开工纪律 + 目标.read_text(encoding="utf-8")


def 列() -> list[tuple[str, int]]:
    """列出全部记忆包 `(开工ID, 字节数)`，按开工ID 升序。"""
    目录 = 记忆目录()
    if not 目录.is_dir():
        return []
    结果 = []
    for 文件 in sorted(目录.glob(f"*{后缀}")):
        结果.append((文件.stem, 文件.stat().st_size))
    return 结果


def 取用提示(开工ID: str) -> str:
    """**返回可直接粘进任务信的那一行**（华哥要的「返回一句提示词」形态）。

    这一行给子代理用：它按提示运行命令即可读到本次任务的全部已核实事实，
    而不必从零探索。提示里**不带记忆正文**，所以任务信长度与事实多少无关。
    """
    工具 = Path(__file__).resolve()
    return (f"开工第一步：运行 `python3.14 {工具} 读 {开工ID}` 读取本次任务记忆"
            f"（已核实事实包；先读它再动手，不要从零探索）。")


def _主函数(参数: list[str]) -> int:
    if not 参数:
        print(__doc__ or "用法：任务记忆.py 写|读|列|清 …")
        return 2
    动作 = 参数[0]
    if 动作 == "写":
        if len(参数) < 3:
            print("用法：任务记忆.py 写 <开工ID> <一句话题目>（正文从 stdin 读）")
            return 2
        正文 = sys.stdin.read()
        落点 = 写(参数[1], 参数[2], 正文)
        print(f"已写入：{落点}（{落点.stat().st_size} 字节）")
        print("── 把下面这一行粘进任务信（不含正文）──")
        print(取用提示(参数[1]))
        return 0
    if 动作 == "读":
        if len(参数) < 2:
            print("用法：任务记忆.py 读 <开工ID>")
            return 2
        try:
            print(读(参数[1]))
        except FileNotFoundError as 错误:
            print(f"读取失败：{错误}")
            return 1
        return 0
    if 动作 == "列":
        条目 = 列()
        if not 条目:
            print("（无任务记忆包）")
            return 0
        for 开工ID, 大小 in 条目:
            print(f"  {开工ID}  {大小} 字节")
        return 0
    if 动作 == "清":
        if len(参数) < 2:
            print("用法：任务记忆.py 清 <开工ID>")
            return 2
        目标 = 路径(参数[1])
        if 目标.is_file():
            目标.unlink()
            print(f"已清理：{目标}")
        else:
            print(f"（不存在，无需清理）：{目标}")
        return 0
    if 动作 == "提示":
        if len(参数) < 2:
            print("用法：任务记忆.py 提示 <开工ID>")
            return 2
        print(取用提示(参数[1]))
        return 0
    print(f"未知动作：{动作}（可用：写 / 读 / 列 / 清 / 提示）")
    return 2


if __name__ == "__main__":
    # 直接跑脚本（`python3.14 开发工具/任务记忆/任务记忆.py …`）时，sys.path[0] 是脚本所在目录，
    # 仓库根不在其中 → 导入 `公共契约.*` 会 ModuleNotFoundError。这里显式补上仓库根。
    if str(仓库根) not in sys.path:
        sys.path.insert(0, str(仓库根))
    raise SystemExit(_主函数(sys.argv[1:]))
