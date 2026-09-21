"""测试写入边界门禁：**测试不得假绿**三条判据（债务 #106 + 2026-09-22 实测现场）。

本件名里的「写入边界」是**判据一**的落点；判据二、三同属「测试不得假绿」一族，
按父任务要求**同件增项**（不另开第二个判据件，避免同类判据散成多条腿），
故件名保留历史、判据面在件内如实列全 —— 读本件先读这张表：

| 判据 | 防的是什么 | 缺口类型常量 | 存量口径 |
|---|---|---|---|
| 一 写仓库内相对路径 | 测试把夹具造进仓库正式根（污染共享状态） | `测试写入-写仓库内相对路径` | 基线内 1 条（只减不增） |
| 二 只断言「成功」 | 未装配空转 ⇒ `成功=True` 而**什么都没测** | `测试断言-只断言成功` | 基线内 18 条（只减不增） |
| 三 mock 空转 | mock 的环境变量键**在实现里零读取点** | `测试mock-环境变量零读点` | 基线内 0 条 |

## 判据一：测试只许写 `tempfile` / `工程缓存/` 下的受管目录，禁止写仓库正式根

**现场证据**：2026-09-20 实证一次真实污染 —— `测试中心/开发工具/测试_退出码诚实口径.py`
的**早期版本**把夹具造在仓库里（`支持库/适配层/未生成丙提供者/`、`真实甲提供者/`
两个目录各含一个 `依赖锁.json`，**未跟踪、全仓零引用**），违反 `AGENTS.md`
「测试不得破坏共享状态」。当时已手工清除夹具，但**没有留下机器判据**。

对 `测试中心/**.py` 里每个**写动作**调用，解析其**目标路径表达式的左端基**：

| 左端基 | 判定 |
|---|---|
| 仓库相对字面量（`"支持库/适配层/未生成丙提供者"`、`"模块库"`…） | **判红** |
| `__file__` 派生且表达式里出现仓库内相对字面量（`Path(__file__).parents[2] / "支持库"`） | **判红** |
| `工程缓存` 开头的相对字面量（`"工程缓存/xxx"`） | **放行**（受管目录） |
| `tempfile.mkdtemp()` / `TemporaryDirectory()` 派生的表达式 | **放行**（左端基解析不到字面量） |
| 绝对路径 / 环境变量 / 解析不出的名字 | **放行**（本判据管的是「仓库相对路径」） |

**写动作面**（必须两个位置都看，否则漏掉真实形态）：

- **接收者位**（`X.mkdir()` / `X.write_text(...)`）—— 历史污染正是这一形态
  （`夹具根.mkdir(parents=True, exist_ok=True)`），只看位置实参的判据对它**全盲**；
- **位置实参位**（`os.mkdir(路径)` / `shutil.rmtree(路径)` / `open(路径, "w")` /
  `shutil.copy2(源, 目标)`）。

`str.replace` **不在**写动作面里：`原文.replace("…", "…")` 是字符串方法，
把它当 `Path.replace` 会产出假红（2026-09-21 实测：`测试中心/运行核心/
测试_跨平台收口原语.py:556` 被误报）。`pathlib.Path` 的改名走 `rename`。

## 判据二：测试断言必须看**业务字段**，不能只看 `成功`（防「未装配空转假绿」）

**现场证据（2026-09-22 实测，已提交 dd1123a0）**：
`测试中心/支持库/测试_语义索引.py` 的 `test_合法调用` 在 `python3.14 -m unittest` 下
`成功=True`，但**什么都没测** —— `建代码索引` 内部 `收集代码块` 要经 `能力调用器`，
而本仓 unittest 环境**没有装配**（`[E未装配] 能力调用器未注入且无惰性装配钩子`）
⇒ 每个文件都被跳过 ⇒ 块列表为空 ⇒ 在
`支持库/后端/代码解析支持库/语义索引/实现/语义索引.py:62` **早退**返回「成功（块数 0）」。
返回值里 `块数=0` / `文件数=0` / `跳过清单` 全是被跳的文件 ——
**只看 `成功` 的断言与「真的索引出了东西」在这一刻长得一模一样**。

口径：逐**用例**（`def test_*`）收它全部断言调用；若**每一条**断言的判定表达式
都只由 `X.成功` 构成（出现下标 / 比较 / 别的字段 / 断言里再调用 ⇒ 不算），
该用例进**待核清单**。真源说明：`成功` 只回答「流程没抛异常」，不回答
「产出物里有东西」；业务字段（`块数` / `文件数` / `错误码` / `值` / `跳过清单`…）
才是那条断言真正想看的东西。

## 判据三：mock 的环境变量键必须在**实现面**有读取点（防 mock 空转）

**同族陷阱（同一批修掉的）**：mock 一个**实现里不存在**的环境变量开关也是空转 ——
原 `test_提供者不可用` mock 了 `语义索引_禁用库`，而 `git grep` 证明该变量
**全仓只出现在测试自己**，实现里零命中；且实现里根本没有 `提供者不可用` 这个错误码。

口径：取 `mock.patch.dict(os.environ, {键: …})` 的**字符串键**，反查该键在
**实现面**（`公共契约.正式根.遍历源码` 的 `.py` + `.json`，**排除 `测试中心/`**）
有没有出现点。零命中时**再排除「测试内自洽」**：若该键在测试中心里还出现在
**别的位置**（不是那个 mock 字典的键），说明测试自己造了消费者（例：
`测试_LibreOffice双腿行为差异.py` 往临时目录写一个假 `soffice` 脚本，脚本里
`os.environ.get("FAKE_LO_COUNTER")` 读它）⇒ 不算空转。两者都零命中 ⇒ **空转**。

## 口径边界（如实声明，不假装扫到了）

- **裸文件名**（`open("结果.json", "w")`）判不出是「仓库根」还是「cwd」——
  它既不匹配任何仓库内相对路径、也无法静态判定运行期 cwd，故判据一**放行**；
- 目标路径由**运行期拼装**（读配置/环境变量后再拼）的写法解析不出字面量 ⇒ 放行；
- 未知函数的**返回值**静态解析不出来（`环境目录(真实提供者目录, 摘要)` 的实参是
  本仓路径、返回值却是 `工程缓存/提供者运行环境/…`）⇒ 归入「解析不出」放行，**不猜**；
- 判据一/二只覆盖 `测试中心/`；判据三的**反查面**是「除 `测试中心/` 外的全仓源码」；
- 判据二按**用例**判（不是按断言）：一条用例里只要有一处业务断言，整条用例就不进待核
  —— 「有业务断言」是它真的看过产出的证据；这会漏掉「一行业务断言 + 九行只看成功」的
  用例，属**如实声明的漏报**，不假装是全覆盖。

## fail-closed（本项目核心纪律）

- 扫描面为空（`测试中心` 不存在，或一个 `.py` 都没扫到）→ 判红（空集不是通过）；
- 某个 `.py` **解析不了**（语法错/读不成/解码错）→ 判红，**不静默跳过**
  —— 跳过等于把「这份测试写了什么未知」压成「它没写仓库」；
- 存量基线**缺失 / 读不成 / 形状非法 / 缺桶** → 判红（「存量已登记」的唯一凭据没了，
  不许静默按空基线判绿）。

## 存量与阻断（13.2 五态：基线内只报不拦，基线外新增判红，只减不增）

三条判据各有自己的存量桶，逐条**具名登记**在
`开发工具/测试写入边界门禁存量基线.json`（桶键 = 判据面里的唯一标识，
**不含行号** —— 行号一改基线就失效，那是把基线做成易碎品）：

- 判据一桶键 = `文件::动作::目标`；判据二桶键 = `文件::类名.用例名`；判据三桶键 = `文件::键`。
  判据二的桶键**带类名**：同一文件里两个类各有一个同名用例是实际存在的
  （`测试中心/支持库/测试_文档生成.py` 的 DOCX 类与 XLSX 类各有一个
  `test_最小有效文件与签名`），只用「文件::用例名」会让两条并成一条 ——
  存量数不清、收敛判定跟着错。
- 当前（2026-09-22 现场实测）存量 **19** 条：判据一 **1** 条
  （`测试中心/平台控制面/测试_文件租约.py` 往**真实** `模块库/开工编排/实现/开工编排.py`
  写一个字节再在 `finally` 里还原 —— 并行维修期这会把**别人刚改的内容回滚成旧内容**，
  故如实登记为存量、不许它增长；修好该测试后须**下调**基线）、
  判据二 **18** 条、判据三 **0** 条。
- 基线里多于现场的条目 = **收敛**，只留痕（提示下调基线），不判红。
- 判据二的已知**假红形态**（如实声明，不假装精确）：用例里用**非断言语句**做验证的写法
  会被列进待核 —— 例：`测试中心/开发工具/测试_支持库模板生成器.py::test_生成文件可编译`
  在 `assertTrue(结果.成功)` 之后用 `py_compile.compile(..., doraise=True)` 真编译产物。
  这类条目是「待核」不是「判红」，人工核完把桶键留在基线里即可。

## 用法

    python3.14 -m 开发工具.测试写入边界门禁              # 跑门禁（三条判据）
    python3.14 -m 开发工具.测试写入边界门禁 --根 <目录>    # 覆盖扫描根（反向验证用）
    python3.14 -m 开发工具.测试写入边界门禁 --只报        # 只打印不判红（排查用）

退出码：0 = 通过（含「基线内 N 条存量」）；1 = 判红；2 = 用法错误。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

仓库根 = Path(__file__).resolve().parents[1]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.正式根 import 遍历源码
from 公共契约.基础类型.逻辑类型 import 真, 假

#: 扫描根（相对仓库根）。
扫描根名 = "测试中心"

#: 唯一受管落点：仓库内相对路径只许落在这里（`工程缓存/` 是生成式缓存区）。
受管目录名 = "工程缓存"

#: 缺口类型常量（报告逐条打印；反向验证按这些字符串断言）。
缺扫描面 = "测试写入-扫描面为空"
缺源码不可解析 = "测试写入-源码不可解析"
写仓库内相对路径 = "测试写入-写仓库内相对路径"
只断言成功 = "测试断言-只断言成功"
mock空转 = "测试mock-环境变量零读点"
缺存量基线 = "测试写入-存量基线不可用"

#: 存量基线的三个桶名（**顺序即报告顺序**；缺桶 = 形状非法 ⇒ 判红）。
存量桶名 = (写仓库内相对路径, 只断言成功, mock空转)

#: 桶名 → 统计里的判据键（报告打印用，避免在打印处再写一遍 if 链）。
判据键 = {写仓库内相对路径: "判据一", 只断言成功: "判据二", mock空转: "判据三"}

#: 存量基线落点。
存量基线路径 = 仓库根 / "开发工具" / "测试写入边界门禁存量基线.json"

#: 接收者位写动作（路径在 `节点.func.value`）。
接收者写动作 = frozenset({
    "mkdir", "makedirs", "touch", "write_text", "write_bytes", "unlink", "rmdir",
    "rmtree", "rename", "chmod", "symlink_to", "link_to", "truncate",
})
#: 位置实参位写动作（路径在 `节点.args`）。
实参写动作 = frozenset({
    "mkdir", "makedirs", "remove", "unlink", "rmdir", "rmtree", "rename",
    "open", "copy", "copy2", "copyfile", "copytree", "move",
})
#: 两个位置实参都是路径的写动作（源、目标）—— **只判目标**（末位实参）。
#: 判源会假红：`shutil.copytree(系统根 / "开发工具" / "发布门禁", 隔离根 / …)`
#: 的源是本仓路径（**读**），把它当写入目标会当场判红（2026-09-22 实测：
#: `测试中心/第一批维修/测试_发布门禁.py:219` 被误报）。
双路径写动作 = frozenset({"copy", "copy2", "copyfile", "copytree", "move"})

#: 左端基回溯时**只认**这些路径构造器：别的调用返回值解析不出来（见 `左端基`）。
#: `join` 另走 `_是os_path` 判定 —— `str.join` 与 `os.path.join` 同名不同义。
路径构造器名 = frozenset({"Path", "PosixPath", "WindowsPath", "PurePath",
                     "PurePosixPath", "PureWindowsPath", "str"})

#: 路径方法（接收者是路径、返回值仍是路径）：基随**接收者**。
路径方法名 = frozenset({"resolve", "absolute", "expanduser", "joinpath",
                    "with_name", "with_suffix"})

#: 判据二：业务字段的反面 —— 这个字段名单独成立时说明不了「测到了东西」。
成功字段名 = "成功"
#: 判据二：单值断言的**判定表达式只取首位实参**（`assertTrue(expr, msg=None)`）。
单值断言名 = frozenset({"assertTrue", "assertFalse"})
#: 判据二：双值断言的判定表达式取前两位（第三位起是 `msg`）。
双值断言名 = frozenset({
    "assertEqual", "assertNotEqual", "assertIs", "assertIsNot", "assertIn",
    "assertNotIn", "assertGreater", "assertGreaterEqual", "assertLess",
    "assertLessEqual", "assertIsNone", "assertIsNotNone", "assertRegex",
    "assertNotRegex", "assertCountEqual", "assertAlmostEqual", "assertIsInstance",
})


def _是os_path(被调: ast.AST) -> bool:
    """``os.path.join`` / ``path.join`` 形态（**排除** `"sep".join(...)` 这类字符串方法）。"""
    if not isinstance(被调, ast.Attribute) or 被调.attr != "join":
        return 假
    接收 = 被调.value
    if isinstance(接收, ast.Name):
        return 接收.id in ("path", "os")
    return (isinstance(接收, ast.Attribute) and 接收.attr == "path"
            and isinstance(接收.value, ast.Name) and 接收.value.id == "os")


def _仓库内顶层目录名() -> set[str]:
    """仓库内相对路径的**首段白名单**：仓库根下实际存在的目录 ∪ 正式根 ∪ 源码层。

    用「实际存在的顶层目录」而不是写死清单：新增正式根时判据自动跟上
    （写死清单会让新根下的写入漏检，且属第二事实源）。
    """
    from 公共契约.正式根 import 正式根名表, 源码层名表
    名 = {p.name for p in 仓库根.iterdir() if p.is_dir()}
    名 |= set(正式根名表) | set(源码层名表)
    return 名


def 像仓库内相对路径(文本: str) -> bool:
    """该字面量是否形如「仓库内相对路径」（首段是仓库顶层目录名，且不是绝对路径）。"""
    净 = 文本.strip().lstrip("./")
    if not 净 or 净.startswith(("/", "~")):
        return 假
    return 净.split("/")[0] in _仓库内顶层目录名()


def 是受管路径(文本: str) -> bool:
    """该字面量是否指向受管目录（`工程缓存/…` 或 `工程缓存` 本身）。"""
    净 = 文本.strip().lstrip("./")
    return 净 == 受管目录名 or 净.startswith(受管目录名 + "/")


# ---------------------------------------------------------------------------
# 判据一：写动作目标的左端基
# ---------------------------------------------------------------------------

def 左端基(节点: ast.AST, 变量表: dict[str, ast.AST], 深度: int = 0
        ) -> tuple[str, str, list[ast.AST]] | None:
    """路径表达式的**左端基**：``("字面量", 文本, 沿途表达式)`` / ``("__file__", "", …)`` / ``None``。

    只有「最左端那个字面量」能说明这条路径**从哪生根**：
    `临时根 / "支持库"` 的左端基是 `临时根`（不是 `"支持库"`），
    而 `"支持库/适配层/x"` 的左端基就是它自己 —— 前者是受管临时目录下的
    合法夹具，后者是写进仓库。按「调用实参里出现过仓库路径字面量」判会把
    前者全判红（2026-09-21 实测：`测试中心` 里 23 条候选**全部**是这种假红）。

    第三个元素是**沿途表达式**（含回溯到的变量值）：`__file__` 派生时
    `Path(__file__).parents[2] / "支持库" / "适配层"` 的仓库内字面量散落在
    整条表达式与变量值里，只看调用实参本身（可能只是一个名字 `根`）会漏判
    —— 反向验证实测过这一条漏判。

    `None` = 解析不出（外部名字、`tempfile.mkdtemp()`、绝对路径等）⇒ 放行。
    """
    if 深度 > 24:
        return None
    if isinstance(节点, ast.Constant) and isinstance(节点.value, str):
        return ("字面量", 节点.value, [节点])
    if isinstance(节点, ast.Name):
        if 节点.id == "__file__":
            return ("__file__", "", [节点])
        if 节点.id in 变量表:
            值 = 变量表[节点.id]
            内 = 左端基(值, 变量表, 深度 + 1)
            if 内 is None:
                return None
            return (内[0], 内[1], [值, *内[2]])
        return None
    if isinstance(节点, ast.BinOp) and isinstance(节点.op, ast.Div):
        左 = 左端基(节点.left, 变量表, 深度 + 1)
        if 左 is None:
            return None
        右 = 左端基(节点.right, 变量表, 深度 + 1)
        return (左[0], 左[1], [*左[2], *(右[2] if 右 else [])])
    if isinstance(节点, ast.Attribute):
        return 左端基(节点.value, 变量表, 深度 + 1)
    if isinstance(节点, ast.Call):
        # **只认路径构造器与路径方法**，别的调用一律解析不出 ⇒ 放行。
        # 为什么不能取「args[0] 当基」：`环境目录(真实提供者目录, 摘要)` 的
        # args[0] 是本仓路径，但**返回值是 `工程缓存/提供者运行环境/…`**
        # （`运行核心/运行环境管理器/环境管理器.py:198`）⇒ 按 args[0] 判会把
        # 受管写入报成仓库写入（2026-09-22 实测：`测试中心/运行核心/
        # 测试_强制校验.py:191` 被误报）。未知函数的返回值静态解析不出来，
        # 如实归入「解析不出」这一档，不猜。
        #
        # 两类必须认：
        #   · 构造器（`Path(...)` / `os.path.join(...)`）—— 基是 args[0]；
        #   · 路径方法（`Path(__file__).resolve()` / `.joinpath(x)`）—— 基是**接收者**。
        #     漏掉第二类会连 `Path(__file__).resolve().parents[2] / "支持库"`
        #     这一整条最典型的形态都解析不出（反向验证实测过这条漏判）。
        被调 = 节点.func
        if isinstance(被调, ast.Attribute):
            名 = 被调.attr
        elif isinstance(被调, ast.Name):
            名 = 被调.id
        else:
            名 = None
        if 名 in 路径方法名 and isinstance(被调, ast.Attribute):
            return 左端基(被调.value, 变量表, 深度 + 1)
        if 名 in 路径构造器名 and 节点.args:
            return 左端基(节点.args[0], 变量表, 深度 + 1)
        if 名 == "join" and _是os_path(被调) and 节点.args:
            return 左端基(节点.args[0], 变量表, 深度 + 1)
        return None
    if isinstance(节点, ast.Subscript):
        return 左端基(节点.value, 变量表, 深度 + 1)
    if isinstance(节点, (ast.List, ast.Tuple)) and 节点.elts:
        return 左端基(节点.elts[0], 变量表, 深度 + 1)
    return None


def 判目标(目标: ast.AST, 变量表: dict[str, ast.AST]) -> tuple[str, str]:
    """``(结论, 证据)``：结论 ∈ ``{"仓库内写", "受管写", "放行"}``。"""
    基 = 左端基(目标, 变量表)
    if 基 is None:
        return "放行", ""
    类, 值, 沿途 = 基
    if 类 == "字面量":
        if 是受管路径(值):
            return "受管写", 值
        if 像仓库内相对路径(值):
            return "仓库内写", 值
        return "放行", ""
    # `__file__` 派生：**整条表达式链**里的字面量都要看
    # （`Path(__file__).parents[2] / "支持库"`，可能还经过一层变量）。
    字面量们 = [子.value for 表达式 in [目标, *沿途] for 子 in ast.walk(表达式)
             if isinstance(子, ast.Constant) and isinstance(子.value, str)]
    for 文 in 字面量们:
        if 是受管路径(文):
            return "受管写", 文
    for 文 in 字面量们:
        if 像仓库内相对路径(文):
            return "仓库内写", 文
    return "放行", ""


def _赋值收集(节点: ast.AST, 表: dict[str, ast.AST]) -> None:
    """把 `节点` 下**本层作用域**的 `名字 = 表达式` 收进 `表`（不进嵌套函数/类）。

    不进嵌套定义是必须的：同名变量在不同方法里可以指完全不同的东西
    （`目标 = 环境目录(self.提供者目录, …)` 与 `目标 = 环境目录(真实提供者目录, …)`
    在同一份测试里各出现一次），把两层压成一张表会让判据按**另一个方法**的绑定
    去判当前这一处 —— 那正是「用 A 处的证据判 B 处」的假红。
    """
    for 子 in ast.iter_child_nodes(节点):
        if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(子, ast.Assign) and len(子.targets) == 1 \
                and isinstance(子.targets[0], ast.Name):
            表.setdefault(子.targets[0].id, 子.value)
        elif isinstance(子, ast.AnnAssign) and isinstance(子.target, ast.Name) \
                and 子.value is not None:
            表.setdefault(子.target.id, 子.value)
        _赋值收集(子, 表)


def _带作用域(节点: ast.AST, 表: dict[str, ast.AST]):
    """逐节点产出 ``(节点, 该节点所属作用域的表)``；函数/类体用自己的表（叠加外层）。"""
    for 子 in ast.iter_child_nodes(节点):
        if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            内层 = dict(表)
            _赋值收集(子, 内层)
            yield 子, 内层
            yield from _带作用域(子, 内层)
        else:
            yield 子, 表
            yield from _带作用域(子, 表)


def _写动作目标(节点: ast.Call) -> tuple[str, list[ast.expr]]:
    """``(动作名, 目标表达式列表)``；不是写动作时动作名为空串。"""
    if isinstance(节点.func, ast.Attribute):
        名 = 节点.func.attr
        if 名 in 接收者写动作:
            # 接收者位就是路径（`夹具根.mkdir()`）；rename 的第二位置实参也是路径。
            目标们: list[ast.expr] = [节点.func.value]
            if 名 == "rename":
                目标们 += list(节点.args)
            return 名, 目标们
        if 名 in 双路径写动作:
            return 名, _取写入目标(节点.args)
        return "", []
    if not isinstance(节点.func, ast.Name):
        return "", []
    名 = 节点.func.id
    if 名 not in 实参写动作:
        return "", []
    if 名 == "open":
        模式 = ""
        if len(节点.args) > 1 and isinstance(节点.args[1], ast.Constant) \
                and isinstance(节点.args[1].value, str):
            模式 = 节点.args[1].value
        if not any(旗标 in 模式 for 旗标 in ("w", "a", "x", "+")):
            return "", []
    if 名 in 双路径写动作 or 名 == "rename":
        return 名, _取写入目标(节点.args)
    return 名, list(节点.args[:1])


def _取写入目标(实参们: list[ast.expr]) -> list[ast.expr]:
    """源/目标双参形态里**只取目标**（末位实参）；只有一位时它就是目标。"""
    return [实参们[-1]] if len(实参们) >= 2 else list(实参们[:1])


# ---------------------------------------------------------------------------
# 判据二：只断言「成功」的用例
# ---------------------------------------------------------------------------

def _是断言调用(节点: ast.AST) -> bool:
    """`self.assertTrue(...)` / `assertEqual(...)` 形态（`assert*` 一族）。"""
    return isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute) \
        and 节点.func.attr.startswith("assert")


def _断言判定表达式(调用: ast.Call) -> list[ast.expr]:
    """断言里**参与判定**的表达式（把 `msg` 那一位摘掉，避免消息文本被当业务字段）。"""
    参数 = list(调用.args)
    名 = 调用.func.attr if isinstance(调用.func, ast.Attribute) else ""
    if 名 in 单值断言名:
        return 参数[:1]
    if 名 in 双值断言名:
        return 参数[:2]
    return 参数


def 只看成功字段(参数们: list[ast.expr]) -> bool:
    """这些判定表达式是否**只**由 `X.成功` 构成。

    出现下标 / 比较 / 别的字段名 / 断言里再调用函数 ⇒ 判定它真的看了业务字段。
    """
    有成功 = False
    for 参数 in 参数们:
        for 子 in ast.walk(参数):
            if isinstance(子, ast.Attribute):
                if 子.attr != 成功字段名:
                    return 假
                有成功 = True
            elif isinstance(子, (ast.Subscript, ast.Compare, ast.Call, ast.BinOp)):
                return 假
            elif isinstance(子, ast.UnaryOp) and not isinstance(子.op, ast.Not):
                return 假
    return 有成功


#: 判据二：**辅助断言方法**名里的标记 —— `self.断言OOXML签名(...)` / `self.校验XX(...)`
#: 这类调用本身就是业务验证（实测假红样本：`测试中心/支持库/测试_文档生成.py`
#: 的 `self.断言OOXML签名("xlsx", 结果.值.字节)`），不把它们算业务验证会假红。
辅助断言标记 = ("断言", "校验", "核对", "验证")


def _是辅助断言(节点: ast.Call) -> bool:
    return isinstance(节点.func, ast.Attribute) \
        and any(标记 in 节点.func.attr for 标记 in 辅助断言标记)


def _收集用例(树: ast.AST) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """``(用例节点, 限定名)`` —— 限定名 = `类名.用例名`（模块级用例只有用例名）。

    为什么带类名：同一文件里**两个类各有一个同名用例**是实际存在的
    （`测试中心/支持库/测试_文档生成.py` 的 DOCX 类与 XLSX 类各有一个
    `test_最小有效文件与签名`），只用「文件::用例名」当桶键会让两条并成一条
    —— 存量基线于是数不清，收敛判定也跟着错。
    """
    出: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = []

    def 走(节点: ast.AST, 前缀: str) -> None:
        for 子 in ast.iter_child_nodes(节点):
            if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if 子.name.startswith("test"):
                    出.append((子, f"{前缀}{子.name}"))
            elif isinstance(子, ast.ClassDef):
                走(子, f"{前缀}{子.name}.")

    for 顶层 in getattr(树, "body", []):
        if isinstance(顶层, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if 顶层.name.startswith("test"):
                出.append((顶层, 顶层.name))
        elif isinstance(顶层, ast.ClassDef):
            走(顶层, f"{顶层.name}.")
    return 出


# ---------------------------------------------------------------------------
# 判据三：mock 环境变量键零读点
# ---------------------------------------------------------------------------

def _是mock字典调用(节点: ast.AST) -> bool:
    """`mock.patch.dict(...)` / `patch.dict(...)` 形态。"""
    return (isinstance(节点, ast.Call)
            and isinstance(节点.func, ast.Attribute) and 节点.func.attr == "dict"
            and isinstance(节点.func.value, ast.Attribute)
            and 节点.func.value.attr == "patch")


def _mock字典键(树: ast.AST) -> tuple[list[tuple[str, int]], set[int]]:
    """``(键们, 键节点 id 集)`` —— 键节点 id 集用于把「mock 自己那一处」排除在「其他出现」外。"""
    键们: list[tuple[str, int]] = []
    键节点: set[int] = set()
    for 节点 in ast.walk(树):
        if not _是mock字典调用(节点) or not isinstance(节点, ast.Call):
            continue
        for 参 in 节点.args:
            if not isinstance(参, ast.Dict):
                continue
            for 键 in 参.keys:
                if isinstance(键, ast.Constant) and isinstance(键.value, str):
                    键们.append((键.value, 键.lineno))
                    键节点.add(id(键))
    return 键们, 键节点


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------

def _测试文件表(根: Path) -> list[Path]:
    测试根 = 根 / 扫描根名
    if not 测试根.is_dir():
        return []
    return sorted(p for p in 测试根.rglob("*.py") if "__pycache__" not in p.parts)


def _读并解析(文件: Path) -> tuple[ast.AST | None, str]:
    """``(树, 错误说明)``；读不成/语法错时树为 None、错误说明非空（调用方判红）。"""
    try:
        源码 = 文件.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        return None, f"读不成（{type(错误).__name__}）"
    try:
        return ast.parse(源码), ""
    except SyntaxError as 错误:
        return None, f"语法错（{错误.msg}）"


def 扫描写入(根: Path) -> tuple[list[dict], dict]:
    """判据一：``(违规, 统计)``；统计里含「受管写」「放行」计数 —— 证明判据确实看过了写动作。

    为什么要有统计：只报「违规 0 条」的判据无法自证它看过任何东西
    （扫描面为空与真的干净长得一模一样，正是 A-3 那类自证恒绿）。
    """
    根 = Path(根)
    违规: list[dict] = []
    统计 = {"文件数": 0, "写动作数": 0, "受管写": 0, "放行写": 0, "仓库内写": 0,
           "不可解析": 0}
    文件表 = _测试文件表(根)
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            违规.append({"文件": 相对, "行": 0, "动作": "-", "目标": "-",
                         "缺口类型": 缺源码不可解析, "桶键": f"{相对}::-::-",
                         "详情": f"{错误} ⇒ 这份测试写了什么未知，不静默跳过"})
            continue
        变量表: dict[str, ast.AST] = {}
        _赋值收集(树, 变量表)
        for 节点, 作用域表 in _带作用域(树, 变量表):
            if not isinstance(节点, ast.Call):
                continue
            动作, 目标们 = _写动作目标(节点)
            if not 动作:
                continue
            for 目标 in 目标们:
                统计["写动作数"] += 1
                结论, 证据 = 判目标(目标, 作用域表)
                if 结论 == "仓库内写":
                    统计["仓库内写"] += 1
                    违规.append({
                        "文件": 相对, "行": 节点.lineno, "动作": 动作, "目标": 证据,
                        "缺口类型": 写仓库内相对路径, "桶键": f"{相对}::{动作}::{证据}",
                        "详情": (f"写动作 {动作} 的目标是**仓库内相对路径** `{证据}` ⇒ "
                                 "违反「测试只许写 tempfile / 工程缓存 下的受管目录」；"
                                 "夹具应建在 tempfile.mkdtemp()/TemporaryDirectory() 里"
                                 "并 addCleanup 清理"),
                    })
                elif 结论 == "受管写":
                    统计["受管写"] += 1
                else:
                    统计["放行写"] += 1
    if not 文件表:
        违规.append({"文件": 扫描根名, "行": 0, "动作": "-", "目标": "-",
                     "缺口类型": 缺扫描面, "桶键": f"{扫描根名}::-::-",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
    return 违规, 统计


def 扫描只断言成功(根: Path) -> tuple[list[dict], dict]:
    """判据二：``(待核清单, 统计)``。"""
    根 = Path(根)
    待核: list[dict] = []
    统计 = {"文件数": 0, "用例数": 0, "有断言用例": 0, "只成功断言用例": 0, "不可解析": 0}
    文件表 = _测试文件表(根)
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            待核.append({"文件": 相对, "行": 0, "用例": "-", "缺口类型": 缺源码不可解析,
                         "桶键": f"{相对}::<不可解析>",
                         "详情": f"{错误} ⇒ 这份测试断言了什么未知，不静默跳过"})
            continue
        for 用例节点, 限定名 in _收集用例(树):
            统计["用例数"] += 1
            断言们 = [子 for 子 in ast.walk(用例节点)
                   if isinstance(子, ast.Call) and _是断言调用(子)]
            辅助 = [子 for 子 in ast.walk(用例节点)
                  if isinstance(子, ast.Call) and _是辅助断言(子)]
            if not 断言们 and not 辅助:
                continue
            统计["有断言用例"] += 1
            if 辅助:
                continue
            if not all(只看成功字段(_断言判定表达式(子)) for 子 in 断言们):
                continue
            统计["只成功断言用例"] += 1
            待核.append({
                "文件": 相对, "行": 用例节点.lineno, "用例": 限定名,
                "缺口类型": 只断言成功, "桶键": f"{相对}::{限定名}",
                "详情": (f"用例 {限定名} 的断言**全部**只看 `成功` 字段 ⇒ "
                         "流程没抛异常就等于通过（未装配空转也是 `成功=True`）；"
                         "必须补一条业务字段断言（产出物计数 / 错误码 / 内容字段），"
                         "否则这条用例证明不了它测到了东西"),
            })
    if not 文件表:
        待核.append({"文件": 扫描根名, "行": 0, "用例": "-", "缺口类型": 缺扫描面,
                     "桶键": f"{扫描根名}::<扫描面为空>",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
    return 待核, 统计


def 扫描mock空转(根: Path) -> tuple[list[dict], dict]:
    """判据三：``(空转清单, 统计)``。

    反查面 = `公共契约.正式根.遍历源码` 的 `.py` + `.json`，**排除 `测试中心/`**；
    零命中时再看该键在测试中心里有没有「其他出现」（测试自造的假件消费者）。
    """
    根 = Path(根)
    空转: list[dict] = []
    统计 = {"文件数": 0, "mock键数": 0, "实现面文件数": 0, "有读点": 0,
           "测试内自洽": 0, "空转": 0, "不可解析": 0}
    文件表 = _测试文件表(根)
    if not 文件表:
        空转.append({"文件": 扫描根名, "行": 0, "键": "-", "缺口类型": 缺扫描面,
                     "桶键": f"{扫描根名}::<扫描面为空>",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
        return 空转, 统计
    键表: dict[str, dict] = {}
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            空转.append({"文件": 相对, "行": 0, "键": "-", "缺口类型": 缺源码不可解析,
                         "桶键": f"{相对}::<不可解析>",
                         "详情": f"{错误} ⇒ 这份测试 mock 了什么未知，不静默跳过"})
            continue
        键们, 键节点 = _mock字典键(树)
        if not 键们:
            continue
        # 「其他出现」= 该键在**本份测试里、mock 字典之外**还出现过（**子串**口径）：
        # 测试自造的假件常常把键写在**一整块多行字符串**里（`测试_LibreOffice双腿行为差异.py`
        # 往临时目录写一个假 `soffice` 脚本，脚本正文里 `os.environ.get("FAKE_LO_COUNTER")`），
        # 那种形态下键不是独立的字符串常量、而是大字符串的一部分 ⇒ 按「常量相等」数会
        # 全数漏掉，把 6 个有真实消费者的键全报成空转（2026-09-22 实测过这一版假红）。
        其他出现 = [子.value for 子 in ast.walk(树)
                if isinstance(子, ast.Constant) and isinstance(子.value, str)
                and id(子) not in 键节点]
        for 键值, 行 in 键们:
            条目 = 键表.setdefault(键值, {"文件": 相对, "行": 行, "其他出现": 0})
            if any(键值 in 文本 for 文本 in 其他出现):
                条目["其他出现"] += 1
    # 实现面反查：文本包含即可（键是环境变量名，出现即说明有读取/声明点）。
    # **排除本件自身**：判据件的正文里会举例提到这些键（本模块 docstring 就写了
    # `语义索引_禁用库` 与 `FAKE_LO_COUNTER`）—— 判据件不是实现，把自己算进反查面
    # 会让「被写进文档的键」自动获得一个假读点（2026-09-22 实测：`FAKE_LO_COUNTER`
    # 只因被本件 docstring 提到就漏判成「有读点」）。这是判据污染自己的反查面。
    本件 = Path(__file__).resolve()
    实现面: list[tuple[Path, str]] = []
    for 路径 in 遍历源码(根, 后缀=(".py", ".json")):
        if 扫描根名 in 路径.relative_to(根).parts:
            continue
        try:
            if 路径.resolve() == 本件:
                continue
            实现面.append((路径, 路径.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    统计["实现面文件数"] = len(实现面)
    for 键值, 条目 in sorted(键表.items()):
        统计["mock键数"] += 1
        读点 = [路径 for 路径, 文本 in 实现面 if 键值 in 文本]
        if 读点:
            统计["有读点"] += 1
            continue
        if 条目["其他出现"]:
            统计["测试内自洽"] += 1
            continue
        统计["空转"] += 1
        空转.append({
            "文件": 条目["文件"], "行": 条目["行"], "键": 键值,
            "缺口类型": mock空转, "桶键": f"{条目['文件']}::{键值}",
            "详情": (f"mock 的环境变量键 `{键值}` 在**实现面零读取点**、"
                     f"且在本仓其他位置也零出现 ⇒ mock 空转（开关没人读，"
                     "断言必然与「没 mock」同结果）；实现里真有这个开关，"
                     "或删掉这条 mock"),
        })
    return 空转, 统计


# ---------------------------------------------------------------------------
# 存量基线
# ---------------------------------------------------------------------------

def 读存量基线(路径: Path | None = None) -> tuple[dict[str, set[str]], list[str]]:
    """``(基线, 问题)``；问题非空 ⇒ fail-closed（调用方判红）。"""
    路径 = Path(路径 or 存量基线路径)
    空 = {名: set() for 名 in 存量桶名}
    if not 路径.is_file():
        return 空, [f"存量基线不存在：{路径}（「存量已登记」的唯一凭据没了，"
                    "不许静默按空基线判绿）"]
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        return 空, [f"存量基线读不成（{type(错误).__name__}）：{路径}"]
    if not isinstance(数据, dict):
        return 空, [f"存量基线形状非法（顶层不是对象）：{路径}"]
    基线: dict[str, set[str]] = {}
    问题: list[str] = []
    for 名 in 存量桶名:
        值 = 数据.get(名)
        if 值 is None:
            问题.append(f"存量基线缺桶 `{名}`：{路径}")
            基线[名] = set()
        elif not isinstance(值, list) or not all(isinstance(项, str) for 项 in 值):
            问题.append(f"存量基线桶 `{名}` 形状非法（须是字符串数组）：{路径}")
            基线[名] = set()
        else:
            基线[名] = set(值)
    return 基线, 问题


def 应用存量基线(当前: set[str], 基线: set[str]) -> tuple[list[str], list[str], list[str]]:
    """``(基线外新增, 基线内存量, 收敛项)`` —— 只减不增：新增判红、收敛只留痕。"""
    新增 = sorted(当前 - 基线)
    存量 = sorted(当前 & 基线)
    收敛 = sorted(基线 - 当前)
    return 新增, 存量, 收敛


# ---------------------------------------------------------------------------
# 门禁入口
# ---------------------------------------------------------------------------

def 运行门禁(根: Path | None = None, *, 基线路径: Path | None = None
          ) -> tuple[list[dict], dict[str, list[dict]], dict]:
    """``(违规, 存量报告, 统计)`` —— 发布门禁与编译口消费的入口。

    - `违规` = 全部**判红**项：基线外新增 + 判据自身缺口（扫描面空 / 源码不可解析 /
      存量基线不可用）；
    - `存量报告` = 各桶「基线内、只报不拦」的条目（含收敛留痕在 `统计` 里）。
    """
    根 = Path(根 or 仓库根).resolve()
    违规: list[dict] = []
    存量报告: dict[str, list[dict]] = {名: [] for 名 in 存量桶名}
    基线, 基线问题 = 读存量基线(基线路径)
    for 说明 in 基线问题:
        违规.append({"文件": 存量基线路径.name, "行": 0, "动作": "-", "目标": "-",
                     "缺口类型": 缺存量基线, "桶键": "存量基线::<不可用>", "详情": 说明})

    判据一, 统计一 = 扫描写入(根)
    判据二, 统计二 = 扫描只断言成功(根)
    判据三, 统计三 = 扫描mock空转(根)

    统计: dict[str, Any] = {"判据一": 统计一, "判据二": 统计二, "判据三": 统计三}

    for 桶名, 清单 in ((写仓库内相对路径, 判据一), (只断言成功, 判据二),
                    (mock空转, 判据三)):
        当前 = {条["桶键"] for 条 in 清单}
        新增, 存量, 收敛 = 应用存量基线(当前, 基线[桶名])
        清单表 = {条["桶键"]: 条 for 条 in 清单}
        for 键 in 存量:
            存量报告[桶名].append(清单表[键])
        for 键 in 新增:
            违规.append(清单表[键])
        统计桶 = {"当前": len(当前), "存量": len(存量), "新增": len(新增), "收敛": 收敛}
        统计[判据键[桶名]]["存量基线"] = 统计桶

    统计["存量总数"] = sum(len(项) for 项 in 存量报告.values())
    return 违规, 存量报告, 统计


def _打印判据(标号: str, 统计: dict) -> None:
    if 标号 == "判据一":
        print(f"  [{标号} 写仓库内相对路径] 扫描 {统计['文件数']} 个 .py；"
              f"写动作 {统计['写动作数']} 处（受管目录内 {统计['受管写']}／"
              f"解析不出而放行 {统计['放行写']}／仓库内写 {统计['仓库内写']}）")
    elif 标号 == "判据二":
        print(f"  [{标号} 只断言成功] 扫描 {统计['文件数']} 个 .py；"
              f"用例 {统计['用例数']} 个（有断言 {统计['有断言用例']}）⇒ "
              f"只成功断言 {统计['只成功断言用例']} 条")
    else:
        print(f"  [{标号} mock空转] 扫描 {统计['文件数']} 个 .py；"
              f"mock 环境变量键 {统计['mock键数']} 个；"
              f"实现面 {统计['实现面文件数']} 文件 ⇒ 有读点 {统计['有读点']}／"
              f"测试内自洽 {统计['测试内自洽']}／空转 {统计['空转']}")


def 主程序(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="测试写入边界门禁（债务 #106，三条判据）")
    解析.add_argument("--根", default=None, help="覆盖扫描根（反向验证用）")
    解析.add_argument("--只报", action="store_true", help="只打印不判红（排查用）")
    参数 = 解析.parse_args(argv)
    根 = Path(参数.根).expanduser() if 参数.根 else 仓库根
    违规, 存量报告, 统计 = 运行门禁(根)
    print(f"测试写入边界门禁：根={根}／扫描面={扫描根名}/")
    for 标号 in ("判据一", "判据二", "判据三"):
        _打印判据(标号, 统计[标号])
    for 桶名 in 存量桶名:
        统计桶 = 统计[判据键[桶名]]["存量基线"]
        if 统计桶["收敛"]:
            print(f"  [{桶名}] 基线比现场多 {len(统计桶['收敛'])} 条 ⇒ 已收敛，"
                  f"请下调 `{存量基线路径.name}` 该桶：{统计桶['收敛'][:3]}")
    for 桶名, 条目们 in 存量报告.items():
        for 条 in 条目们:
            print(f"  [存量·只报不拦·{桶名}] {条['文件']}:{条['行']} "
                  f"{条.get('用例', 条.get('目标', 条.get('键', '')))}")
    if not 违规:
        if 统计["存量总数"]:
            print(f"测试写入边界门禁结论：绿 —— 基线内 {统计['存量总数']} 条存量"
                  "（只报不拦，只减不增）")
        else:
            print("测试写入边界门禁通过：三条判据零违规、零存量"
                  "（受管落点 = tempfile / 工程缓存）")
        return 0
    头 = "测试写入边界门禁失败（只报态，不判红）" if 参数.只报 else "测试写入边界门禁失败"
    print(f"{头}：共 {len(违规)} 项违规")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] {条['文件']}:{条['行']} "
              f"动作={条.get('动作', '-')} 目标={条.get('目标', 条.get('用例', 条.get('键', '-')))} "
              f"详情={条['详情']}")
    return 0 if 参数.只报 else 1


if __name__ == "__main__":
    sys.exit(主程序())
