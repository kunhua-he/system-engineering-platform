"""依赖与生命周期审计核心：只读审计第三方支持库提供者（依赖锁独立版本声明/
完整性摘要重算比对/健康探针能力/停止释放入口），不写被审计文件、不 import 其实现。"""

from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from 支持库.后端.组件规范支持库 import 生成完整性摘要

适配层目录名 = "支持库/适配层"
后端目录名 = "支持库/后端"
依赖锁文件名 = "依赖锁.json"
包声明文件名 = "包声明.json"
完整性摘要文件名 = "完整性摘要.json"
能力定义文件名 = "能力定义.json"
生命周期契约文件名 = "生命周期契约.json"
# 提供者现有公开能力中，“检查提供者/检查可用性”与“版本探针”都是
# 同一健康契约的合法中文命名；不能只认“探针/健康”两个词而误报。
探针关键词 = ("探针", "健康", "检查提供者", "检查可用性", "检查提供者版本")
停止关键词 = ("停止", "关闭", "释放", "终结", "终止")


@dataclass
class 提供者审计结果:
    提供者名: str
    目录: Path
    违规列表: list[str] = field(default_factory=list)

    @property
    def 是否通过(self) -> bool:
        return not self.违规列表


def _读包声明(目录: Path) -> dict:
    """读取包声明.json；缺失或损坏返回空字典（调用方按缺失处理）。"""
    路径 = 目录 / 包声明文件名
    if not 路径.is_file():
        return {}
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return 数据 if isinstance(数据, dict) else {}


def 平台自有顶层名(根目录: Path) -> frozenset[str]:
    """平台自有顶层名集合：从被审计根**现场推导**，不硬编码清单。

    为什么要推导而不是写死一份：制品编译副本会把全部平台导入改写成
    ``平台客户端.<原顶层包>``（见 ``客户端/构建平台客户端.py::顶层包表``），
    而**制品层根本身就是 ``…/平台客户端``** —— 也就是制品里多出一层平台自有
    前缀。任何一份手写清单漏掉它，制品内的平台导入就会被当成第三方模块，
    纯标准库包（`SQLite数据库`：只 import sqlite3、包声明 依赖=[]）会被误拉进
    「第三方提供者」并被索要 `依赖锁.json`，在发布门禁上造成假红。

    推导口径（源码树与制品树同一份逻辑，两处都成立）：
    **根目录自身的名字 ∪ 根下每个顶层目录名 ∪ 根下每个顶层 .py 模块名**。
    源码树根 = `系统工程平台`（顶层含 公共契约/支持库/模块库/运行核心/平台控制面/
    开发工具/测试中心/工程缓存…），制品层根 = `…/平台客户端`（顶层含 公共契约/
    支持库/模块库/…，且自身名字就是 `平台客户端`）—— 两者都无需任何手写常量。
    真实第三方包（psycopg/PIL/reportlab/pdfplumber…）不是顶层目录名，照旧被识别。
    """
    名表: set[str] = {根目录.name}
    try:
        条目表 = list(根目录.iterdir())
    except OSError:
        条目表 = []
    for 条目 in 条目表:
        if 条目.is_dir():
            名表.add(条目.name)
        elif 条目.suffix == ".py":
            名表.add(条目.stem)
    return frozenset(名表)


def _平台自有顶层名附近(目录: Path) -> frozenset[str]:
    """从提供者目录向上找「含 模块库 的平台根」，取其平台自有顶层名集合。

    找不到这样的祖先（例如测试在临时目录里构造的孤立提供者）时，退化为以
    该目录自身为根 —— 退化结果只会多排除个别目录名，不会把真实第三方包放过。
    """
    for 祖先 in 目录.parents:
        if (祖先 / "模块库").is_dir():
            return 平台自有顶层名(祖先)
    return 平台自有顶层名(目录)


def _系统根(目录: Path) -> Path:
    """从提供者目录向上找「含 模块库 的平台根」（与 `_平台自有顶层名附近` 同一判据）。

    找不到（测试在临时目录里构造的孤立提供者）时退化为该目录自身：转调壳解析
    自然落空、不产生假绿。
    """
    for 祖先 in 目录.parents:
        if (祖先 / "模块库").is_dir():
            return 祖先
    return 目录


#: 转调壳里「唯一实现名」的字面量形态：`支持库.适配层.X.实现.Y`（D-1 收口）。
_转调实现名句式 = re.compile(r"^支持库\.[A-Za-z0-9_.\u4e00-\u9fff]+\.实现\.[A-Za-z0-9_\u4e00-\u9fff]+$")


def _转调壳目标文件(目录: Path) -> list[Path]:
    """解析 实现/ 下的**转调壳**，返回被转调的唯一实现文件（2026-09-23 补判据覆盖）。

    平台把「同一份逻辑只能有一个实现」收口成转调壳：后端包 ``实现/X.py`` 里写
    ``sys.modules[__name__] = sys.modules[唯一实现名]``，**真正带函数定义的是适配层腿**
    的同名文件。静态 AST 扫描只看壳文件 ⇒「实现里没有停止函数 / 没有释放资源证据」
    全是假红 —— 实测 22 条违规里 17 条由这一条造成（OCR识别/FFmpeg媒体/PDF隔离提供者/
    textutil转换/Git操作/转写/图像解码/PDF渲染 八个提供者）。

    解析口径：只在**含 ``sys.modules[__name__]`` 赋值**的文件里，取形如
    ``支持库.适配层.X.实现.Y`` 的字符串字面量（转调壳的「唯一实现名」），按
    「点 → 目录分隔」还原成仓库内相对路径。解析不出返回空表（不猜、不放宽）。
    """
    根 = _系统根(目录)
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return []
    结果: list[Path] = []
    for 文件 in sorted(实现目录.rglob("*.py")):
        try:
            源 = 文件.read_text(encoding="utf-8")
        except OSError:
            continue
        if "sys.modules[__name__]" not in 源:
            continue
        try:
            树 = ast.parse(源)
        except SyntaxError:
            continue
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Constant) or not isinstance(节点.value, str):
                continue
            文本 = 节点.value.strip()
            if not _转调实现名句式.match(文本):
                continue
            候选 = 根.joinpath(*文本.split(".")).with_suffix(".py")
            if 候选.is_file() and 候选 not in 结果:
                结果.append(候选)
    return 结果


def _实现扫描文件(目录: Path) -> list[Path]:
    """判据要扫的实现源码文件：本包 ``实现/**/*.py`` ∪ 转调壳指向的适配层腿 ``实现/*.py``。

    为什么连腿的**整目录**一起扫：唯一实现常拆成兄弟文件（``_终止进程组`` 在
    ``提供者.py``，壳却指向 ``子进程入口.py``）。腿就是本提供者的实现（同一模块
    对象，见 `_转调壳目标文件`），故腿里的停止函数与资源证据都算本提供者的证据。
    """
    文件表: list[Path] = []
    if (目录 / "实现").is_dir():
        文件表.extend(sorted((目录 / "实现").rglob("*.py")))
    for 目标 in _转调壳目标文件(目录):
        文件表.extend(sorted(目标.parent.glob("*.py")))
    去重: list[Path] = []
    见: set[Path] = set()
    for 文件 in 文件表:
        if 文件 not in 见:
            见.add(文件)
            去重.append(文件)
    return 去重


def _实现第三方导入(目录: Path) -> set[str]:
    """列出 实现/**/*.py 里真实 import 的第三方顶层模块（AST 解析，不执行代码）。

    用 sys.stdlib_module_names 排除标准库；平台自有顶层名（现场推导，见
    平台自有顶层名()）与 公共契约 等不算第三方。
    这是「该包是不是第三方提供者」最硬的现场证据：它真的在 import 别人的库。
    """
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return set()
    标准库 = set(sys.stdlib_module_names)
    平台前缀 = _平台自有顶层名附近(目录)
    第三方: set[str] = set()
    for 文件 in sorted(实现目录.rglob("*.py")):
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                名列表 = [别名.name.split(".")[0] for 别名 in 节点.names]
            elif isinstance(节点, ast.ImportFrom) and 节点.level == 0 and 节点.module:
                名列表 = [节点.module.split(".")[0]]
            else:
                continue
            第三方.update(名 for 名 in 名列表
                      if 名 and 名 not in 标准库 and 名 not in 平台前缀)
    return 第三方


def _第三方依赖证据(目录: Path, 声明: dict) -> str:
    """返回「该包确实是第三方支持库提供者」的现场证据描述；没有证据返回空串。

    三条证据任一成立即可（写清楚是哪一条，避免用模糊的「有依赖」冒充第三方依赖）：
    1. 有 依赖锁.json；
    2. 包声明.依赖 里有真正的第三方包条目（带 名称/发行包 字段）——
       注意 包声明.依赖 里大量是**能力依赖**（只带 能力/包id），不算第三方依赖；
    3. 实现/**/*.py 真的 import 了非标准库、非平台内的第三方模块。
    """
    有锁 = (目录 / 依赖锁文件名).is_file()
    声明第三方 = sorted({
        str(条目.get("发行包") or 条目.get("名称"))
        for 条目 in (声明.get("依赖") or [])
        if isinstance(条目, dict) and (条目.get("发行包") or 条目.get("名称"))
    })
    导入第三方 = sorted(_实现第三方导入(目录))
    证据: list[str] = []
    if 有锁:
        证据.append(f"有 {依赖锁文件名}")
    if 声明第三方:
        证据.append(f"包声明声明第三方包 {'、'.join(声明第三方)}")
    if 导入第三方:
        证据.append(f"实现 import 第三方模块 {'、'.join(导入第三方)}")
    return "；".join(证据)


def _读内部件声明(适配层: Path) -> dict[str, list]:
    """读 `支持库/适配层/内部件依赖声明.json`（根级平铺内部件的唯一手写源）。

    缺失或损坏一律返回空表（调用方按「无声明条段」处理），不抛异常。
    """
    try:
        路径 = 适配层 / "内部件依赖声明.json"
        if not 路径.is_file():
            return {}
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return {str(键): list(值) for 键, 值 in 数据.items() if isinstance(值, list)}


def 扫描根级平铺内部件(系统根: Path) -> list[str]:
    """把 `支持库/适配层/*.py` 这类**根级平铺内部件**纳入可见性（#96，2026-09-21）。

    **为什么单列一段**：平铺 .py 内部件（`模型服务.py`／`系统探针.py` 等）**没有自己的
    目录**，`依赖锁.json` 的既有落点（件自身目录）对它不存在；`扫描提供者目录` 的
    `*提供者` glob 也永远看不见它 —— 于是「直连第三方、无锁、不进审计」的件在审计输出里
    **完全不可见**，看着像「不存在这类件」。

    **判据同源不复制**：`开发工具/依赖派生/生成依赖分两段.py` 口径 5 已把这类件的第三方
    依赖登记在 `支持库/适配层/内部件依赖声明.json`（唯一手写源），并由 `--校验` 对
    「现场有第三方 import 却没登记」判红。本段**只做可见性上报**（逐件列出其声明状态），
    判定仍归 `生成依赖分两段.py --校验` 一处口径 —— 不在审计里再造第二条腿。

    返回逐件说明（供运行入口打印）；空列表表示根下没有平铺 .py 内部件。
    """
    适配层 = 系统根 / 适配层目录名
    if not 适配层.is_dir():
        return []
    声明表 = _读内部件声明(适配层)
    说明列表: list[str] = []
    for 文件 in sorted(适配层.glob("*.py")):
        if 文件.name == "__init__.py":
            continue
        条目 = 声明表.get(文件.stem) or []
        模块名 = sorted({str(项.get("模块名") or 项.get("名称"))
                       for 项 in 条目
                       if isinstance(项, dict) and (项.get("模块名") or 项.get("名称"))})
        if 模块名:
            说明列表.append(
                f"{文件.name}: 平铺内部件（无目录 ⇒ 依赖锁无落点，由 内部件依赖声明.json 承载）；"
                f"已声明外部依赖 {'、'.join(模块名)}"
            )
        else:
            说明列表.append(
                f"{文件.name}: 平铺内部件（无目录 ⇒ 依赖锁无落点）；"
                f"内部件依赖声明.json 无条段 —— 若现场确有第三方 import，"
                f"`生成依赖分两段.py --校验` 会判「该建声明没建」"
            )
    return 说明列表


def 扫描提供者目录(系统根: Path) -> tuple[list[Path], list[str]]:
    """扫描适配层与后端聚合包下的第三方支持库提供者目录。

    覆盖判据（2026-09-17 扩覆盖，修 F-5「后端提供者审不到」缺口）：
    - 适配层 ``支持库/适配层/<包>``：沿用既有判据（目录名以 提供者 结尾 + 有 包声明.json），
      不动这 17 个既有提供者的结论；
    - 后端聚合包 ``支持库/后端/<支持库>/<包>``：改用**单一判据「有 生命周期契约.json」**
      —— 后端提供者包名并不统一（`PDF文本表格`/`PDF生成`/`psycopg数据库` 都没有「提供者」后缀），
      按名字 glob 必漏，而「有生命周期契约」正好等价于「有可核对的释放文案」，
      正是本审计要审的对象；
    - 后端候选仍要求声明第三方依赖（有 依赖锁.json 或 包声明.依赖 非空）：
      纯标准库实现的包（如 SQLite数据库）不是第三方提供者，列入跳过清单而不是静默丢弃；
    - 其余不满足判据的目录一律进跳过清单并写明原因，保证覆盖变化可追溯。

    返回 (标准提供者目录, 跳过说明)。
    """
    提供者列表: list[Path] = []
    跳过列表: list[str] = []
    适配层 = 系统根 / 适配层目录名
    if 适配层.is_dir():
        for 目录 in sorted(适配层.glob("*提供者")):
            if not 目录.is_dir():
                continue
            if (目录 / 包声明文件名).is_file():
                提供者列表.append(目录)
            else:
                # 无 包声明.json 的两种形态必须分开定性（#95/#101，2026-09-21）：
                # 判据 = 与后端分支**同一套**「第三方依赖证据」（依赖锁／包声明第三方条目／
                # 实现 import 第三方模块），一处口径不复制第二套。
                #   ① 有证据 ⇒ 该建包声明没建，属**缺口**（可见性缺口）；
                #   ② 无证据 ⇒ 纯标准库／系统工具内部适配器，属 `AGENTS.md`
                #      「系统适配器豁免」（`支持库/适配层/说明/README.md` §二 逐项登记），
                #      **非第三方提供者，跳过是正确结论**。
                # 旧文案一律写「非标准第三方支持库提供者」：对 ② 是**误述**（它根本不是第三方
                # 提供者，只是没包声明），对 ① 又漏掉了「这是缺口」—— 两种形态共用一句话，
                # 等于把缺口和豁免抹平成同一个结论。
                证据 = _第三方依赖证据(目录, _读包声明(目录))
                if 证据:
                    跳过列表.append(
                        f"{目录.name}: 无 包声明.json，但现场有第三方依赖证据（{证据}）"
                        f"——该建包声明没建，属**缺口**（可见性缺口），跳过"
                    )
                else:
                    跳过列表.append(
                        f"{目录.name}: 无 包声明.json，且无第三方依赖证据"
                        f"（无 依赖锁.json、包声明无第三方包条目、实现未 import 第三方模块）"
                        f"——纯标准库／系统工具内部适配器，属 AGENTS.md「系统适配器豁免」，"
                        f"非第三方提供者，跳过"
                    )
    后端 = 系统根 / 后端目录名
    if 后端.is_dir():
        for 聚合包 in sorted(路径 for 路径 in 后端.iterdir() if 路径.is_dir()):
            for 目录 in sorted(路径 for 路径 in 聚合包.iterdir() if 路径.is_dir()):
                标记 = f"后端/{聚合包.name}/{目录.name}"
                声明 = _读包声明(目录)
                证据 = _第三方依赖证据(目录, 声明)
                有契约 = (目录 / 生命周期契约文件名).is_file()
                if not 有契约:
                    if 证据:
                        跳过列表.append(
                            f"{标记}: 第三方证据（{证据}）但无 {生命周期契约文件名}，"
                            f"无释放文案可核对，未纳入生命周期审计")
                    continue
                if not (目录 / 包声明文件名).is_file():
                    跳过列表.append(f"{标记}: 有 {生命周期契约文件名} 但无 包声明.json，跳过")
                    continue
                if not 证据:
                    跳过列表.append(
                        f"{标记}: 有 {生命周期契约文件名} 但无第三方依赖证据"
                        f"（无 依赖锁.json、包声明无第三方包条目、实现未 import 第三方模块），"
                        f"非第三方支持库提供者，跳过")
                    continue
                提供者列表.append(目录)
    return 提供者列表, 跳过列表


def _身份匹配(契约: dict, 目录名: str) -> bool:
    """契约的 提供者id 必须指向本目录自身（扩覆盖后的统一身份判据）。

    平台里提供者id有两种书写：适配层 ``支持库.适配层.Pillow提供者``、
    后端聚合包 ``支持库.后端.文档转换支持库.python_docx提供者``
    （历史也写作 ``支持库.后端/文档转换支持库.x提供者``）。
    旧判据只认「目录名」与「支持库.适配层.目录名」两种字面量，后端id永远匹配不上，
    导致后端提供者的契约形同废纸 —— 故改为结构化判据：
    把 ``/`` 归一成 ``.`` 后，首段必须是 ``支持库``，**末段必须等于本目录名**。
    它既覆盖两种书写，又拦得住「抄了别的提供者id」（末段对不上）和「随便编一个id」。
    """
    提供者id = str(契约.get("提供者id") or "").replace("/", ".").strip()
    段列表 = [段 for 段 in 提供者id.split(".") if 段]
    return len(段列表) >= 2 and 段列表[0] == "支持库" and 段列表[-1] == 目录名


def 收集第三方名称(目录: Path, 声明: dict) -> tuple[set[str], list[str]]:
    """收集发行包归属，而非把同一发行包的命令/模块误判为混装。

    依赖锁条目可用 ``发行包`` 声明实际归属（例如 ffmpeg 与 ffprobe
    都属于 FFmpeg发行包）。旧条目没有该字段时退回名称，保持严格审计：
    未明确归属的不同名称仍然会被判为混装。
    """
    依赖锁路径 = 目录 / 依赖锁文件名
    if not 依赖锁路径.is_file():
        return set(), [f"缺依赖锁: {依赖锁文件名} 不存在，无独立版本声明"]
    try:
        数据 = json.loads(依赖锁路径.read_text(encoding="utf-8"))
        包列表 = 数据.get("包") or 数据.get("直接依赖") or []
    except (json.JSONDecodeError, OSError) as 错误:
        return set(), [f"依赖锁损坏: {错误}"]
    名称集合 = {
        str(条目.get("发行包") or 条目["名称"])
        if isinstance(条目, dict) else 条目
        for 条目 in (包列表 + (声明.get("依赖") or []))
        if (isinstance(条目, dict) and 条目.get("名称")) or isinstance(条目, str)
    }
    return 名称集合, []


def 检查依赖锁(目录: Path, 声明: dict) -> list[str]:
    """依赖锁.json 独立版本声明与混装检查（一个提供者只锁一个第三方）。"""
    名称集合, 违规列表 = 收集第三方名称(目录, 声明)
    if 违规列表:
        return 违规列表
    if not 名称集合:
        return ["依赖锁空: 未声明任何第三方包"]
    if len(名称集合) > 1:
        return [f"混装: 一个提供者声明多个第三方 {sorted(名称集合)}"]
    return []


def 检查完整性摘要(目录: Path, 声明: dict) -> list[str]:
    """完整性摘要.json 存在且与唯一生成器重算结果一致（检出漂移）。"""
    摘要路径 = 目录 / 完整性摘要文件名
    if not 摘要路径.is_file():
        return [f"缺完整性摘要: {完整性摘要文件名} 不存在"]
    包id = str(声明.get("包id") or 目录.name)
    版本 = str(声明.get("版本") or "1.0.0")
    try:
        磁盘摘要 = json.loads(摘要路径.read_text(encoding="utf-8"))
        重算摘要 = 生成完整性摘要(目录, 包id=包id, 版本=版本)
    except (json.JSONDecodeError, OSError, ValueError) as 错误:
        return [f"摘要漂移: 重算失败 {错误}"]
    if 磁盘摘要 == 重算摘要:
        return []
    磁盘条数 = len(磁盘摘要.get("文件清单", [])) if isinstance(磁盘摘要, dict) else -1
    重算条数 = len(重算摘要.get("文件清单", []))
    return [f"摘要漂移: 磁盘文件清单 {磁盘条数} 条 ≠ 唯一生成器重算 {重算条数} 条"
            f"（包id/版本/文件内容/清单不一致）"]


def 检查健康探针(目录: Path) -> list[str]:
    """健康探针能力存在性：能力定义或生命周期契约必须可审计。"""
    能力路径 = 目录 / 能力定义文件名
    if not 能力路径.is_file():
        return [f"缺健康探针: {能力定义文件名} 不存在，无法声明探针能力"]
    try:
        数据 = json.loads(能力路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return [f"缺健康探针: 能力定义损坏 {错误}"]
    for 能力 in 数据.get("能力列表") or []:
        if not isinstance(能力, dict):
            continue
        名称文本 = f"{能力.get('能力id', '')} {能力.get('中文名称', '')}"
        if any(词 in 名称文本 for 词 in 探针关键词):
            return []
    契约路径 = 目录 / 生命周期契约文件名
    if 契约路径.is_file():
        try:
            契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as 错误:
            return [f"缺健康探针: 生命周期契约损坏 {错误}"]
        探针 = 契约.get("健康探针")
        入口 = str(探针.get("入口") or "") if isinstance(探针, dict) else ""
        入口路径 = 入口.split(":", 1)[0].strip()
        入口存在 = bool(入口路径) and (目录 / 入口路径).is_file()
        身份一致 = _身份匹配(契约, 目录.name)
        if (isinstance(探针, dict) and 探针.get("方式")
                and 探针.get("成功条件") and 探针.get("失败码")
                and 入口存在 and 身份一致):
            return []
    return ["缺健康探针: 能力定义.json 未声明探针且生命周期契约无效"]


def _停止入口真实存在(目录: Path, 停止入口文本: str) -> bool:
    """契约里的「停止入口」必须指向实现里**真实存在**的函数。

    为什么要这一步：光有「停止入口」这个字段可能是空话（契约写了、实现里没有）。
    本函数从文本里抓出函数名（形如 ``实现/进程管理.py 的 终止进程组()``），
    再到 ``实现/**/*.py`` 的 AST 里核对确实存在同名函数。
    """
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return 假
    候选 = re.findall(r"([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{1,40})\s*\(\)", 停止入口文本)
    if not 候选:
        # 兜底也要认中文名（原正则只认 ASCII ⇒ `实现/子进程入口.py:进程组终止` 这类
        # 不带 `()` 的中文写法一个候选都抓不到，判据恒假）。
        候选 = re.findall(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{2,40}", 停止入口文本)
    if not 候选:
        return 假
    实际函数名: set[str] = set()
    for 文件 in _实现扫描文件(目录):
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                实际函数名.add(节点.name)
    return any(名 in 实际函数名 for 名 in 候选)


def 检查停止入口(目录: Path) -> list[str]:
    """停止与资源释放证据：实现函数或生命周期契约必须明确释放语义。"""
    实现目录 = 目录 / "实现"
    if not 实现目录.is_dir():
        return ["缺停止入口: 实现/ 目录不存在"]
    # 扫本包 实现/ ∪ 转调壳指向的适配层腿（D-1 收口后函数定义都在腿里，见 _实现扫描文件）。
    for 文件 in _实现扫描文件(目录):
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(词 in 节点.name for 词 in 停止关键词):
                    return []
    契约路径 = 目录 / 生命周期契约文件名
    if 契约路径.is_file():
        try:
            契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            契约 = {}
        身份一致 = _身份匹配(契约, 目录.name)
        # 主判据（2026-09-16 收紧）：契约必须**显式声明停止入口**，且该入口**真实存在**。
        # 旧判据只认「资源模型 == 调用内临时资源」这个精确字符串，写别的合法措辞会被误判成缺入口；
        # 而"契约写了停止入口但实现里没有"这类名不副实又拦不住 —— 故改为按停止入口字段 + AST 核对。
        停止入口 = str(契约.get("停止入口") or "")
        if 身份一致 and len(停止入口) >= 6 and _停止入口真实存在(目录, 停止入口):
            return []
        # 兼容路径：契约没有停止入口字段，但资源模型自述为"调用内临时资源"且释放策略明确
        资源模型 = 契约.get("资源模型")
        释放策略 = 契约.get("释放策略")
        释放文本 = str(释放策略 or "")
        释放证据词 = ("finally", "关闭", "释放", "终止", "回收", "无跨调用状态")
        if (资源模型 == "调用内临时资源" and 身份一致
                and any(词 in 释放文本 for 词 in 释放证据词)
                and len(释放文本) >= 12):
            return []
    return ["缺停止入口: 实现/ 下无停止函数，且契约未声明可核对的停止入口"]


# ── 释放策略文案 vs 实现（2026-09-17 补 F-5 缺口）─────────────────────────────
# F-5 的形态是「契约里写的释放策略与实现不符」，而旧判据只核 停止入口 字段是否存在、
# 函数是否真实存在 —— 文案本身写错（例如纯 Python 库却声称「关闭连接、游标、工作簿」）
# 照样全绿。本判据的做法：从 释放策略 文本里抽出「动作词 + 资源类型」的**声称**
# （关闭连接、回收进程组……），逐个到 实现/**/*.py 里核对同类型资源是否真的存在；
# 声称了实现里根本没有的资源类型 → 报「释放策略不符」。
# 为什么这样判而不是判文风：文字层面核不出「写得好不好」，但能核出
# 「文案声称的资源在实现里到底有没有」—— 这正是名不副实唯一可客观验证的一面。
释放动作词 = ("关闭", "释放", "回收", "终止", "清空", "清理", "删除", "close", "rmtree")
否定词 = ("不", "未", "无", "没", "绝", "避免")
# 资源类型 → 实现里可接受的证据关键词（第三方/系统资源的真实 API 或对象名）
资源证据表: dict[str, tuple[str, ...]] = {
    "数据库连接": ("connect(", "Connection(", "psycopg", "sqlite3", "连接对象", "连接池"),
    "连接": ("connect(", "Connection(", "psycopg", "sqlite3", "连接对象", "连接池", "连接串"),
    "游标": ("cursor(", "游标"),
    "工作簿": ("Workbook", "工作簿", "openpyxl"),
    "压缩包句柄": ("ZipFile", "压缩包", "zipfile"),
    "文件句柄": ("open(", "ZipFile", "read_bytes", "read_text", "write_bytes", ".close()"),
    "文档句柄": ("Document(", "pdfplumber", "pdf.close", "文档对象"),
    "演示对象": ("Presentation", "演示文稿"),
    "临时目录": ("rmtree", "mkdtemp", "TemporaryDirectory", "临时目录"),
    "临时文件": ("rmtree", "mkdtemp", "unlink", "NamedTemporaryFile", "临时文件"),
    "会话目录": ("会话目录", "rmtree", "会话"),
    "进程组": ("killpg", "start_new_session", "进程组", "terminate(", "kill("),
    "管道": ("PIPE", "管道", "stdout", "stderr"),
    "子进程": ("Popen", "subprocess", "子进程"),
}


def _实现源码(目录: Path) -> str:
    """拼接实现源码文本，供「文案 vs 实现」核对（只读，不 import）。

    范围＝本包 ``实现/**/*.py`` ∪ 转调壳指向的适配层腿（见 `_实现扫描文件`）：
    释放动作（``killpg`` / ``进程组`` / ``子进程`` 等）常写在腿里，只看壳文件会假红。
    """
    片段列表: list[str] = []
    for 文件 in _实现扫描文件(目录):
        try:
            片段列表.append(文件.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(片段列表)


def 检查释放策略与实现(目录: Path) -> list[str]:
    """释放策略文案必须能被实现证据支撑；声称了实现里没有的资源即违规。

    否定语境不算声称（「不涉及数据库连接、游标与工作簿」「无文件句柄」
    「不显式关闭文档」），所以只认「动作词 + 资源名」相邻的写法，且动作词前
    6 个字内出现否定词就跳过 —— 避免把「如实声明不持有该资源」误判成假话。
    """
    契约路径 = 目录 / 生命周期契约文件名
    if not 契约路径.is_file():
        return []  # 无契约的情况由 缺健康探针/缺停止入口 报，不重复计入
    try:
        契约 = json.loads(契约路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return [f"释放策略不符: 生命周期契约损坏 {错误}"]
    释放文本 = str(契约.get("释放策略") or "")
    if len(释放文本) < 12:
        return ["释放策略不符: 契约未声明可核对的释放策略文本"]
    源码 = _实现源码(目录)
    if not 源码:
        return []  # 无实现源码的情况由 缺停止入口 报
    声称: list[tuple[str, str, tuple[str, ...]]] = []
    for 资源名, 证据词列表 in 资源证据表.items():
        if any(证据词 in 源码 for 证据词 in 证据词列表):
            continue  # 实现里确有该资源，文案声称它属正常
        for 动作词 in 释放动作词:
            模式 = re.compile(re.escape(动作词) + r"[^，。；：,;]{0,2}" + re.escape(资源名))
            for 匹配 in 模式.finditer(释放文本):
                前缀 = 释放文本[max(0, 匹配.start() - 6):匹配.start()]
                if any(词 in 前缀 for 词 in 否定词):
                    continue
                声称.append((动作词, 资源名, 证据词列表))
                break
            else:
                continue
            break
    # 同一句话里「关闭数据库连接」会同时命中「数据库连接」与「连接」，只报最长的一个
    精简后 = [条目 for 条目 in 声称
              if not any(条目[1] != 其他[1] and 条目[1] in 其他[1] for 其他 in 声称)]
    return [f"释放策略不符: 文案声称「{动作词}{资源名}」，但 实现/ 中无该资源证据"
            f"（实现里应出现 {'、'.join(证据词列表)} 之一）"
            for 动作词, 资源名, 证据词列表 in 精简后]


def 审计单个提供者(目录: Path) -> 提供者审计结果:
    """审计一个标准提供者目录，返回违规清单。"""
    结果 = 提供者审计结果(提供者名=目录.name, 目录=目录)
    声明路径 = 目录 / 包声明文件名
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8")) if 声明路径.is_file() else {}
    except (json.JSONDecodeError, OSError) as 错误:
        结果.违规列表.append(f"包声明损坏: {错误}")
        声明 = {}
    if not 声明:
        结果.违规列表.append("包声明缺失: 包声明.json 不存在或为空")
        return 结果
    结果.违规列表.extend(检查依赖锁(目录, 声明))
    结果.违规列表.extend(检查完整性摘要(目录, 声明))
    结果.违规列表.extend(检查健康探针(目录))
    结果.违规列表.extend(检查停止入口(目录))
    结果.违规列表.extend(检查释放策略与实现(目录))
    return 结果


def 审计全部(系统根: Path) -> tuple[list[提供者审计结果], list[str]]:
    """审计全部标准提供者目录；返回 (结果列表, 跳过说明列表)。"""
    提供者列表, 跳过列表 = 扫描提供者目录(系统根)
    return [审计单个提供者(目录) for 目录 in 提供者列表], 跳过列表
