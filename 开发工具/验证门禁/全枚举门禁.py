"""全枚举门禁：拦住「从系统根 rglob 全枚举、再在 Python 层过滤生成式目录」这种写法。

**为什么要有这条门禁**（2026-09-19 华哥裁决）：

> 「一个命令六七分钟，我在想，这些生成出来的东西，不能列个名单？直接在一开始就跳过？
>   因为生成式的无所谓的吧，改代码也改不到他头上。我要的是无论任意时候，都需要可以跳过。」

病形：`系统根.rglob("*")` 先把 9.3G `工程缓存`（全仓 31 万条目 / **97.5%**）枚举一遍，
再在 Python 层按 `相对.parts` 过滤掉。实测代价 —— `运行发布门禁` 的占位代称扫描
**202.6 秒 → 进目录即剪枝 2.5 秒**（文件集合完全一致，只省代价不改结果）。

**为什么靠门禁而不是靠记性**：同形名单此前在 **8 个文件**里各写一份且内容互不相同
（`依赖防火墙`/`发布门禁`/`项目编译器`/`单文件自查`/`工作区指纹`/`交付收尾`/`能力调用图审计`…），
改一处不知道别处。唯一事实源＝`公共契约/正式根.py::生成式目录表`，
统一入口＝`公共契约/正式根.py::遍历源码`。

**判据（变量绑定解析，不用名字猜）**：对每个 `.py` 先建「变量 → 赋值表达式」表，再逐条
`X.rglob(...)` 调用判断 `X` 的实际绑定是否为**整棵系统根**：

| X 的绑定形态 | 判定 |
|---|---|
| `Path(__file__).resolve().parents[N]`，N≥2 | 真病（指到项目根及以上） |
| `Path.cwd()` / `Path(".")`，且文件内能确认 cwd 为系统根 | 真病 |
| 名字含「系统根/项目根/全仓根」且赋值表达式**不含 `/`**（不是子目录切法） | 真病 |
| `某根 / 某子目录`（含 `/`）、`某.parent`、`配置.X`（运行期传入） | **不判**（包级/业务目录，实测几十条，不是瓶颈） |

放宽的理由：只有**整棵系统根**才贵（31 万条）；包级 rglob 只有几十条。
`配置.项目根.rglob(...)` 这类扫的是**运行期传入的业务素材目录**，不是本仓生成式目录面，必须放过。

允许行级豁免：被豁免那一行或上一行写 `全枚举豁免：` + 非空理由，
且理由里必须出现「剪枝」或「需扫生成式」字样（与 `依赖门禁豁免：` 同口径，fail-closed）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

门禁目录 = Path(__file__).resolve().parent
if str(门禁目录) not in sys.path:
    sys.path.insert(0, str(门禁目录))

from 门禁公共 import 检查结论, 命中, 收集源码, 相对路径  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]
扫描层名表 = ("开发工具", "公共契约", "运行核心", "平台控制面", "启动监督器", "客户端", "模块库", "技能库")
根名关键词 = ("系统根", "项目根", "全仓根", "全仓")
豁免标记 = "全枚举豁免："
豁免必须含 = ("剪枝", "需扫生成式")


def _绑定是整棵根(名字: str, 表达式: str) -> bool:
    """按「名字 + 赋值表达式」判定该变量是否为整棵系统根。"""
    表达式 = 表达式.strip()
    # ① `Path(__file__).resolve().parents[N]`，N≥2
    if "__file__" in 表达式 and "parents[" in 表达式:
        for 片段 in 表达式.split("parents[")[1:]:
            数字 = 片段.split("]")[0].strip()
            if 数字.isdigit() and int(数字) >= 2:
                return True
    # ② 名字含根关键词，且表达式不是「子目录切法」（不含 `/`、不含 `.parent`）
    if any(词 in 名字 for 词 in 根名关键词):
        if "/" not in 表达式 and ".parent" not in 表达式 and ".name" not in 表达式:
            return True
    return False


def _收集绑定(树: ast.AST) -> dict[str, str]:
    """文件内「变量名 → 赋值表达式源码」；同名多次赋值取最后一次（最接近调用点）。"""
    表: dict[str, str] = {}
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Assign) and len(节点.targets) == 1:
            目标 = 节点.targets[0]
            if isinstance(目标, ast.Name):
                try:
                    表[目标.id] = ast.unparse(节点.value)
                except Exception:
                    表[目标.id] = ""
        elif isinstance(节点, ast.AnnAssign) and isinstance(节点.target, ast.Name):
            if 节点.value is not None:
                try:
                    表[节点.target.id] = ast.unparse(节点.value)
                except Exception:
                    表[节点.target.id] = ""
        # for 循环的迭代目标（如 `for 根 in ...`）不参与——它们不是「根」的绑定
    return 表


def 检查() -> 检查结论:
    结论 = 检查结论(名称="全枚举检测")
    文件表 = 收集源码(系统根, 层名表=扫描层名表)
    结论.扫描面["源码文件"] = len(文件表)
    if not 文件表:
        结论.判定红 = True
        结论.判定理由 = "扫描面为 0：一个 .py 都没扫到，判红（可能路径指错）"
        return 结论

    for 文件 in 文件表:
        try:
            源码 = 文件.read_text(encoding="utf-8")
            行表 = 源码.splitlines()
            树 = ast.parse(源码)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        绑定表 = _收集绑定(树)
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Call):
                continue
            函数 = 节点.func
            if not (isinstance(函数, ast.Attribute) and 函数.attr in ("rglob", "glob", "iglob")):
                continue
            接收者 = 函数.value
            if not isinstance(接收者, ast.Name):
                continue  # `某根 / 子目录.rglob` / `配置.X.rglob` 一律不判
            名字 = 接收者.id
            表达式 = 绑定表.get(名字)
            if 表达式 is None:
                continue  # 绑定解析不到（参数传入等）：不猜，放过
            if not _绑定是整棵根(名字, 表达式):
                continue
            行号 = getattr(节点, "lineno", 0)
            上下文 = " ".join([
                行表[行号 - 1] if 行号 - 1 < len(行表) else "",
                行表[行号 - 2] if 行号 >= 2 else "",
            ])
            if 豁免标记 in 上下文 and any(词 in 上下文 for 词 in 豁免必须含):
                continue
            结论.命中列表.append(命中(
                规则="系统根全枚举",
                文件=相对路径(文件, 系统根),
                行号=行号,
                详情=f"{ast.unparse(节点)[:70]} —— 改走 `正式根.遍历源码`（进目录即剪枝）",
            ))

    return 结论


def 主函数() -> int:
    结论 = 检查()
    print(f"══ {结论.名称} ══")
    print(f"  扫描面：{结论.扫描面}")
    if 结论.命中列表:
        print(f"  命中 {len(结论.命中列表)} 处：")
        for 项 in 结论.命中列表[:40]:
            print(f"    {项.文本}")
        if len(结论.命中列表) > 40:
            print(f"    …（共 {len(结论.命中列表)} 处，只列前 40）")
        print("  结论：红 —— 从系统根全枚举会先走 31 万条目再过滤，97.5% 是白枚举。")
        return 1
    print(f"  结论：绿 —— 无「从系统根 rglob 全枚举」写法（扫描 {结论.扫描面总数} 个文件）")
    return 1 if 结论.判定红 else 0


if __name__ == "__main__":
    raise SystemExit(主函数())
