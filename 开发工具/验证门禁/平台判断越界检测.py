"""验证门禁四「平台判断越界检测」——只读检查器，把「平台判断只许出现在两个收口层」落成机器判据。

## 为什么需要它（未完成事项 #105）

铁律出处（华哥 2026-09-16 裁决，`AGENTS.md` 跨平台收口条 + `开发文档/项目说明.md` §4）：

> 平台差异只允许在 `公共契约/运行时/平台适配.py`（纯平台判定）和
> `公共契约/运行时/进程终止.py`（进程与进程组）两处判断。调用点一律改调收口层，
> **调用点不许自己写平台判断**（禁 `sys.platform` / `os.name` / `是Windows()` /
> `taskkill` / `os.killpg`）；某处必须加平台判断才能改通时，报回来补收口层，不许就地分叉。

**接线前的现场事实**（第一轮《审计_平台判断越界_20260919》§七 #105）：
在三个门禁目录搜 `sys.platform` 与 `os.name` 两种字面量**只有 1 处注释命中** ——
铁律写了、收口层也建了，但没有任何自动防回潮判据。
按哲学 13.1「判据在、门禁不调即纸面规则」，靠人记得 grep 不算强制点。

**为什么复用这里而不是另造第二套扫描器**（哲学 1.2 禁第二实现）：
`开发工具/验证门禁/` 已经是一套「独立只读检查器 + 门禁公共骨架 + 分桶存量基线 + 三拍自证」
的完整形态，且已由 `开发工具/开发编译口/编译口.py` 的 `门禁清单` 接进必经路径
（名字「重复腿与旁路」，角色=阻断）。本检查器**沿用同一套骨架**（`门禁公共.跑标准主流程`
/ `检查结论` / `命中` / `读基线` / `判定` / `写基线段`），只新增判据本体。

## 判据（收口层白名单 + 其余位置判红）

白名单**只有两个路径**，与铁律原文逐字对应：

| 路径 | 为什么是收口层 |
|---|---|
| `公共契约/运行时/平台适配.py` | 纯平台判定（谁能依赖它）；原语本体 |
| `公共契约/运行时/进程终止.py` | 进程与进程组（POSIX/Windows 终止语义差异） |

白名单外任何位置出现下列**取值形态**即命中（AST 判据，不做行文本正则）：

| 规则号 | 形态 | 说明 |
|---|---|---|
| 一 | 裸读 `sys.platform` / `os.name` / `platform.system()` / `platform.machine()` | 铁律点名禁的四种读法（`platform.*` 两种是第一轮审计 E-1 实测散落的同一类） |
| 二 | **在控制流条件位**调用收口层分支判定原语 `是Windows()` / `是macOS()` / `是Linux()` / `是POSIX()` | 「取值后自行分叉」：即使平台值来自收口层，**分支动作**仍决定行为 → 那是第二份实现（与 `测试中心/运行核心/测试_跨平台收口原语.py` 的「禁止取值后分叉」同口径） |

**规则二为什么限定「控制流条件位」**（判据精度，2026-09-20 接线时定）：
铁律禁的是**行为分叉**——即平台值**决定走哪条路**。判据若把「任意位置的调用」
都算违规，会把两类**观测位**误判成分叉：

- `if` / `while` / 三元 / `and`·`or` / 推导式条件 **之外的**位置调用它，只用于
  **报告与展示**（例：`开发工具/环境自检/探测_进程组.py` 把 `是POSIX()` 放进详情字典
  `{"是POSIX": 平台适配.是POSIX()}` 供人读；`自检_解释器与平台.py` 把四个判定原语
  放进台账字典）。这类位置**不改变行为路径**，是自检工具「把收口层判定结果摊开给人看」
  的正当用法。
- 把它们判红会逼出两种坏结果：要么给判据开一堆白名单口子（白名单本身就是第二个
  判据事实源），要么把观测改成「从展示值反推」（自证恒真，对账价值归零）。

故判据落点 = **控制流条件位**（`If.test` / `While.test` / `IfExp.test` / `BoolOp.values`
/ 推导式 `ifs` / `Assert.test` 内部的调用）。这是「有没有决定行为」的机器可判形式。

扫描面 = `门禁公共.正式层名表`（复用唯一事实源，**不含 `测试中心`**；`测试中心`
因此不在面内 —— 这一点由扫描层名表的来源决定，不由本文件另写一张名单）。

测试侧（`测试中心/**`）**不在扫描面内**：那是模拟另一平台所必需的
（反向验证的目的就是模拟另一个平台，必须直接换掉最底层标志 —— 先例见
`测试中心/运行核心/测试_跨平台收口原语.py` 的桩姿势说明）。

### 与既有检查器的分工（不重复判、不互相顶替）

- `调用腿唯一性检测` 判的是「模块库/技能库/运行核心的**调用腿**唯一」——
  与平台判断无交集；
- `开发工具/复用审计/能力调用图审计` 判「原子旁路/越界导入」——
  平台判断不在它的判据集内；
- `运行核心/依赖防火墙` 只看 **import 方向**：`import platform` / `import sys`
  都是标准库、方向合法 → 实测全绿，**看不见平台取值点散落**。

### 覆盖不了什么（如实声明）

- 判据是**取值形态**级，不是完整数据流级：把平台值经中间变量层层传递后再分叉
  （`标志 = 平台适配.原始平台标志()` 再 `if 标志 == "win32"`）抓不到
  —— 这类形态属语义级判据，本项目暂无；
- 能力探测类写法（`hasattr(os, "killpg")`）**不判**（铁律自己也认这种写法：
  `平台适配.当前平台()` docstring 原文「调用方应按能力探测而非按名字硬判」）；
- **`os.name` 的「探测/自检」用途**：`开发工具/环境自检/` 下的
  `os.name == "nt"` 是**自检项自己的期望值口径**（拿它与收口层判定对账，
  判「平台判定与本机布局是否矛盾」），属**观测**不是**行为分叉**——
  但它读的确实是平台标志，故一并冻结进存量基线（只报不拦），
  不额外开豁免口子（豁免口子本身就是第二个判据事实源）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

if __name__ == "__main__" or __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 假, 真  # noqa: E402
from 公共契约.运行时.平台适配 import 清只读后删除树  # noqa: E402
from 开发工具.验证门禁.门禁公共 import (  # noqa: E402
    正式层名表,
    新建夹具根,
    检查结论,
    命中,
)

检查器名 = "平台判断越界检测"

规则_裸读平台标志 = "裸读平台标志"
规则_取值后分叉 = "取值后自行分叉"

#: 收口层白名单 —— **与铁律原文逐字对应，只有两个路径**。
#: 改白名单 = 改铁律，必须同步 `AGENTS.md` 的收口条，不得只改这里。
收口层白名单: frozenset[str] = frozenset({
    "公共契约/运行时/平台适配.py",
    "公共契约/运行时/进程终止.py",
})

#: 规则一：裸读平台标志的四条形态（`模块名.属性名`）。
#: 加 `platform.machine()` 的理由：它与 `platform.system()` 是**同一类**（本机平台取值上报），
#: 第一轮审计 E-1 把两者并列点名；#103 已把 `platform.system()` 全部收口，
#: `platform.machine()` 存量冻结进基线（存量只报不拦，新增即红）。
裸读形态表: tuple[tuple[str, str], ...] = (
    ("sys.platform", "裸读 sys.platform（铁律点名，应改调 平台适配.原始平台标志() 或分支原语）"),
    ("os.name", "裸读 os.name（铁律点名，应改调 平台适配.分支原语）"),
    ("platform.system", "裸读 platform.system()（应改调 平台适配.本机系统名()，#103 唯一口径）"),
    ("platform.machine", "裸读 platform.machine()（应改调 平台适配.当前架构()）"),
)

#: 规则二：收口层分支判定原语 —— 出现在白名单外即「取值后自行分叉」。
分支判定原语表: frozenset[str] = frozenset({
    "是Windows", "是macOS", "是Linux", "是POSIX",
})

#: 扫描面 = **复用同一条源码边界**（哲学 12.1 唯一事实源），不另列层名表。
#: 本文件最初自写了一张 12 项层名表，被 `同动作双路径检测` 当场判红
#: （「表 扫描层名表 与另一处交叠 7/8 条（同一动作两处实现）」）—— 那正是本条纪律要防的
#: 第二份实现，故改为 import 共享表。来源链：`门禁公共.正式层名表`
#: ← `运行核心/依赖防火墙.py::层名称表`。
扫描层名表: tuple[str, ...] = 正式层名表

#: 变体样本表（`--自证` 第二拍用）：**必须被判红**的形态，逐条对应上面两条规则。
变异样本表: tuple[tuple[str, str, str], ...] = (
    (规则_裸读平台标志, "公共契约/夹具契约/夹具文件.py",
     "import sys\n\n\ndef 夹具():\n    return sys.platform == 'win32'\n"),
    (规则_裸读平台标志, "运行核心/夹具核心.py",
     "import os\n\n\n夹具值 = os.name\n"),
    (规则_裸读平台标志, "开发工具/夹具工具.py",
     "import platform\n\n\n夹具值 = platform.system()\n"),
    (规则_裸读平台标志, "支持库/夹具支持库.py",
     "import platform\n\n\n夹具值 = platform.machine()\n"),
    (规则_取值后分叉, "运行核心/夹具分叉.py",
     "from 公共契约.运行时 import 平台适配\n\n\ndef 夹具():\n"
     "    if 平台适配.是Windows():\n        return 'win'\n    return 'posix'\n"),
    (规则_取值后分叉, "模块库/夹具模块/实现/夹具模块.py",
     "from 公共契约.运行时.平台适配 import 是POSIX\n\n\n夹具值 = 1 if 是POSIX() else 2\n"),
    (规则_取值后分叉, "开发工具/夹具工具.py",
     "from 公共契约.运行时 import 平台适配\n\n\n"
     "def 夹具(项表):\n"
     "    return [项 for 项 in 项表 if 平台适配.是POSIX() and 项]\n"),
)

#: 拍一/拍三用的合法样本：**一条都不该报**。
#: ① 收口层本体（白名单内）自带判定 → 不报；
#: ② 调用点只调「取值型」原语、不做分支 → 不报；
#: ③ 能力探测写法（`hasattr`）→ 不报。
合法样本表: tuple[tuple[str, str], ...] = (
    ("公共契约/运行时/平台适配.py",
     "import sys\n\n\ndef 是Windows() -> bool:\n    return sys.platform.startswith('win')\n"),
    ("公共契约/运行时/进程终止.py",
     "import os\n\n\ndef 收口判定():\n    return os.name == 'nt'\n"),
    ("运行核心/夹具取样.py",
     "from 公共契约.运行时 import 平台适配\n\n\n"
     "def 夹具台账() -> dict:\n    return {'系统': 平台适配.本机系统名(), '架构': 平台适配.当前架构()}\n"),
    ("支持库/夹具探测.py",
     "from 公共契约.运行时.平台适配 import 平台稳定缓存根\n\n\n"
     "夹具根 = 平台稳定缓存根()\n"),
    # 观测位（详情字典/台账）：平台判定原语出现在**非条件位**，不决定行为路径 → 不报。
    # 这一条是「规则二限定控制流条件位」这条判据精度的边界样本：去掉限定它会变红。
    ("开发工具/夹具观测.py",
     "from 公共契约.运行时 import 平台适配\n\n\n"
     "def 夹具详情() -> dict:\n"
     "    return {'是POSIX': 平台适配.是POSIX(), '平台': 平台适配.当前平台()}\n"),
)


def _属性链(节点: ast.AST) -> str:
    """把 `a.b.c` 形式拼成点号串；其余形态返回空串（与收口原语测试同一写法）。"""
    段: list[str] = []
    while isinstance(节点, ast.Attribute):
        段.append(节点.attr)
        节点 = 节点.value
    if isinstance(节点, ast.Name):
        段.append(节点.id)
        return ".".join(reversed(段))
    return ""


def _条件位节点集(树: ast.AST) -> set[int]:
    """收集**控制流条件位**上所有节点的 `id()`（规则二的落点判据）。

    覆盖：`If.test` / `While.test` / `IfExp.test` / `BoolOp.values` / `Assert.test`
    / 推导式的 `ifs` 与 `iter`（`any(是POSIX() for …)` 这类形态的分叉同样在条件位）。

    为什么用 `id()` 集合而不是「逐节点判父」：`ast` 无法从子节点回溯父节点，
    先把条件位的整棵子树 id 收进来，再在遍历时查表 —— 一次表达式遍历，无第二份实现。
    """
    出: set[int] = set()

    def _收(表达式: ast.AST | None) -> None:
        if 表达式 is None:
            return
        for 子 in ast.walk(表达式):
            出.add(id(子))

    for 节点 in ast.walk(树):
        if isinstance(节点, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            _收(节点.test)
        elif isinstance(节点, ast.BoolOp):
            for 值 in 节点.values:
                _收(值)
        elif isinstance(节点, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            for 生成 in 节点.generators:
                _收(生成.iter)
                for 条件 in 生成.ifs:
                    _收(条件)
        elif isinstance(节点, ast.DictComp):
            for 生成 in 节点.generators:
                _收(生成.iter)
                for 条件 in 生成.ifs:
                    _收(条件)
    return 出


def 构建结论(根: Path) -> 检查结论:
    """按两条规则扫正式源码边界，命中白名单外的平台取值形态。"""
    结论 = 检查结论(名称=检查器名)
    文件表: list[Path] = []
    for 层名 in 扫描层名表:
        层目录 = 根 / 层名
        if not 层目录.is_dir():
            continue
        for 路径 in sorted(层目录.rglob("*.py")):
            if "__pycache__" in 路径.parts:
                continue
            文件表.append(路径)
    结论.扫描面["正式源码 .py"] = len(文件表)
    结论.跳过面["收口层白名单"] = len(收口层白名单)

    命中表: list[命中] = []
    for 文件 in 文件表:
        相对 = 文件.relative_to(根).as_posix()
        if 相对 in 收口层白名单:
            continue  # 白名单内就是收口层本体，自带平台判定是它的职责
        源码 = _可解析源码(文件, 结论, 根)
        if 源码 is None:
            continue
        树 = ast.parse(源码)
        条件位 = _条件位节点集(树)
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Attribute):
                链 = _属性链(节点)
                for 形态, 说明 in 裸读形态表:
                    if 链 == 形态:
                        命中表.append(命中(
                            规则=规则_裸读平台标志, 文件=相对,
                            行号=节点.lineno, 详情=说明,
                        ))
                        break
                continue
            if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute):
                名 = 节点.func.attr
                # 只认「收口层取值后分叉」：形如 `平台适配.是Windows()` 或
                # 直接 `是Windows()`（`from … import 是Windows`）。
                if 名 not in 分支判定原语表:
                    continue
                接收者链 = _属性链(节点.func.value)
                if 接收者链 not in ("平台适配", ""):
                    continue
                if id(节点) not in 条件位:
                    continue  # 观测位（详情字典/台账）：不决定行为路径，不是分叉
                命中表.append(命中(
                    规则=规则_取值后分叉, 文件=相对, 行号=节点.lineno,
                    详情=f"条件位调用 平台适配.{名}() —— 调用点自行分叉"
                         f"（平台值来自收口层，但分支动作在调用点 = 第二份实现）；"
                         f"应改调收口层的**取值型**原语（本机系统名()/当前架构()/"
                         f"子进程组启动标志()/进程内存RSS字节()/平台稳定缓存根()），"
                         f"由收口层自己判定",
                ))
    结论.命中列表 = 命中表
    return 结论


def _可解析源码(文件: Path, 结论: 检查结论, 根: Path) -> str | None:
    """读源码；读不成 / 语法错 → 记入「不可解析」（情况未知，不得当无违规，fail-closed）。"""
    try:
        return 文件.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        结论.不可解析.append(f"{文件.relative_to(根).as_posix()}: {type(错误).__name__}")
        return None
    except Exception as 错误:  # noqa: BLE001 —— 兜底也必须计入未知，不得静默跳过
        结论.不可解析.append(f"{文件.relative_to(根).as_posix()}: {type(错误).__name__}")
        return None


def _自证() -> int:
    """三拍自证：① 合法夹具根 → 绿；② 注入违规样本 → 必红；③ 撤除 → 回绿。"""
    import subprocess

    根 = 新建夹具根("验证门禁四_自证_")
    基线 = 根 / "基线.json"
    for 相对, 内容 in 合法样本表:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    (根 / "基线.json").write_text(
        '{"检查器": {"平台判断越界检测": {}}}', encoding="utf-8"
    )
    # 合法样本落在扫描层名表里，但夹具根里没有 `测试中心` —— 扫描面不为 0 即可
    结果: list[tuple[str, str]] = []

    def _跑() -> int:
        return subprocess.run(
            [sys.executable, str(Path(__file__)), "--根", str(根), "--基线", str(基线)],
            capture_output=True, text=True, timeout=240,
        ).returncode

    第一拍 = _跑()
    结果.append((f"第一拍 合法夹具根（收口层本体 + 取值型原语调用 + 能力探测）", f"退出码 {第一拍}（期望 0=绿）"))
    for _规则, 相对, 内容 in 变异样本表:
        路径 = 根 / 相对
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding="utf-8")
    第二拍 = _跑()
    结果.append((f"第二拍 注入 {len(变异样本表)} 份违规样本（两条规则各覆盖）", f"退出码 {第二拍}（期望 1=红）"))
    for _规则, 相对, _内容 in 变异样本表:
        路径 = 根 / 相对
        if 路径.is_file():
            路径.unlink()
    第三拍 = _跑()
    结果.append(("第三拍 撤除违规样本", f"退出码 {第三拍}（期望 0=绿）"))

    print(f"══ {检查器名} 自证（三拍）══")
    for 名, 值 in 结果:
        print(f"  {名}：{值}")
    通过 = 第一拍 == 0 and 第二拍 == 1 and 第三拍 == 0
    print(f"  自证结论：{'通过' if 通过 else '不通过'}")
    if not 通过:
        print(f"  ⚠ 夹具根保留供人工复核：{根}")
        return 1
    # 夹具根可能含只读条目 → 走唯一实现，不留 shutil.rmtree 裸调用
    清只读后删除树(根, 忽略失败=真)
    return 0


def main(argv: list[str] | None = None) -> int:
    实参 = list(sys.argv[1:] if argv is None else argv)
    if "--自证" in 实参:
        return _自证()
    from 开发工具.验证门禁.门禁公共 import 跑标准主流程

    return 跑标准主流程(检查器名, 构建结论, 实参)


if __name__ == "__main__":
    sys.exit(main())
