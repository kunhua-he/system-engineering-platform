"""测试支持库原子能力：验证计划 / 验证命令白名单 / 验证结果判定。

三个能力共同把「一次验证」中**非执行**的部分做成原子能力：

1. `测试支持库.验证计划`——只读计算该跑哪些精确 unittest 模块入口与命令，
   级别为阶段收口/正式发布时给出 HTML 黑盒与唯一发布命令；**绝不执行**。
2. `测试支持库.验证命令白名单`——纯函数准入判定：命令是否落在本仓允许的
   三种验证形态内，其余一律拒绝并把错误码放进返回值。
3. `测试支持库.验证结果判定`——按真实执行输出判定 通过/阻断；零测试成功、
   导入失败当跳过、未解释跳过、缓存假绿一律阻断。

只用 Python 标准库；不做 shell 拼接、不起子进程、不写盘。
口径来源：`MCP工具箱/验证门禁.py`（命令白名单与判定）、
`技能库/技能/验证编排/scripts/验证编排.py`（同源副本）、
`开发工具/测试体系门禁实现/跳过检查.py`（静态未解释跳过）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

# ── 冻结契约常量（与 MCP工具箱/验证门禁.py 同源，不另立一套口径） ──────────
允许可执行 = ("python3.14",)
测试模块前缀 = "测试中心."
HTML验证入口 = "开发工具.HTML验证.验证器"
唯一发布命令 = ["python3.14", "开发工具/发布门禁/运行发布门禁.py"]
默认制品并发 = "32"
shell元字符表 = frozenset(";|&`$(){}<>")

默认最大条目数 = 50
硬上限条目数 = 500
默认级别 = "工作包"
合法级别表 = ("工作包", "合并波次", "阶段收口", "正式发布")

错误码_命令拒绝 = "命令拒绝"
阻断码_验证失败 = "验证失败"
阻断码_零测试 = "零测试"
阻断码_缓存假绿 = "缓存假绿"
阻断码_导入失败当跳过 = "导入失败当跳过"
阻断码_未解释跳过 = "未解释跳过"

# 首段目录 → 对应测试目录（测试目录名恰好等于首段名时直接用 测试中心/<首段>）
顶层段表 = (
    "支持库", "模块库", "运行核心", "后端核心", "前端核心", "平台控制面",
    "公共契约", "开发工具", "项目适配层", "示例项目",
    "启动监督器", "客户端", "技能库", "测试中心",
)

只读说明 = "只生成计划，不执行任何测试或命令；执行请走统一网关或系统核心支持库的进程能力。"


def _定位仓库根() -> Path:
    """按包自身位置向上定位仓库根：含 支持库 与 模块库 的那一层。"""
    当前目录 = Path(__file__).resolve().parent
    for 祖先 in (当前目录, *当前目录.parents):
        if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
            return 祖先
    祖先表 = Path(__file__).resolve().parents
    return 祖先表[4] if len(祖先表) > 4 else 当前目录


仓库根 = _定位仓库根()


def _解析根目录(根目录: str) -> Path | None:
    """规范化仓库根目录参数；空串取包自身定位出的仓库根。"""
    文本 = str(根目录 or "").strip()
    根 = Path(文本).expanduser() if 文本 else 仓库根
    try:
        根 = 根.resolve()
    except OSError:
        return None
    return 根 if 根.is_dir() else None


def _规范化目标(根: Path, 目标路径: str) -> tuple[list[Path], str]:
    """把目标路径规范成待扫描目录/文件候选清单，同时返回规范化文本。"""
    规范 = str(目标路径 or "").strip().replace("\\", "/").lstrip("./")
    候选: list[Path] = []
    条目 = 根 / 规范
    if 条目.is_file():
        候选.append(条目)
    elif 条目.is_dir():
        候选.append(条目)
    elif "/" not in 规范 and "." in 规范:
        点分 = (根 / Path(*规范.split("."))).with_suffix(".py")
        if 点分.is_file():
            候选.append(点分)
    return 候选, 规范


def _回退测试目录(根: Path, 规范: str) -> list[Path]:
    """目标本身不是测试目录时，按首段回退到 测试中心/<首段>。"""
    首段 = 规范.split("/")[0]
    if 首段 not in 顶层段表:
        return []
    测试目录 = (根 / "测试中心" / 首段) if 首段 != "测试中心" else (根 / "测试中心")
    return [测试目录] if 测试目录.is_dir() else []



def _收集测试文件(目录表: list[Path]) -> list[Path]:
    """从目录/文件清单里收集 测试_*.py，路径有序。"""
    文件表: set[Path] = set()
    for 条目 in 目录表:
        if 条目.is_file():
            if 条目.suffix == ".py" and 条目.name.startswith("测试_"):
                文件表.add(条目)
            continue
        文件表.update(文件 for 文件 in 条目.rglob("测试_*.py") if 文件.is_file())
    return sorted(文件表)


def _转模块名(根: Path, 文件: Path) -> tuple[str, str]:
    """把测试文件转成精确点分模块名；失败返回 (\"\", 原因)。"""
    try:
        相对 = 文件.relative_to(根).with_suffix("")
    except ValueError:
        return "", "不在仓库根内，无法转成精确模块"
    段表 = 相对.parts
    if not 段表 or any(not 段.isidentifier() for 段 in 段表):
        return "", "路径含非标识符段，无法转成精确 unittest 模块入口"
    return ".".join(段表), ""


def _制品相对路径(根: Path, 制品目录: str) -> tuple[str, str]:
    """制品目录必须是仓库根内相对目录；失败返回 (\"\", 原因)。"""
    文本 = str(制品目录 or "").strip().replace("\\", "/")
    if not 文本:
        return "", "阶段收口/正式发布必须声明 制品目录"
    if 文本.startswith(("/", "~")) or ".." in Path(文本).parts:
        return "", "制品目录必须是仓库根内相对目录（禁止绝对路径与路径逃逸）"
    解析 = (根 / 文本).resolve()
    try:
        解析.relative_to(根)
    except ValueError:
        return "", "制品目录越出仓库根"
    if not 解析.is_dir():
        return "", f"制品目录不存在: {文本}"
    return 文本.rstrip("/"), ""


def 验证计划(目标路径: str, 关键词: str = "", 级别: str = 默认级别,
           仓库根目录: str = "", 制品目录: str = "", 最大条目数: int = 默认最大条目数) -> 结果:
    """只读计算验证计划：目标范围内的精确 unittest 模块入口与命令。"""
    if 目标路径 is None or not str(目标路径).strip():
        return 结果.失败("参数不合法", "目标路径 不能为空", 来源="测试支持库.验证计划")
    级别文本 = str(级别 or 默认级别).strip() or 默认级别
    if 级别文本 not in 合法级别表:
        return 结果.失败("参数不合法", f"级别 必须是 {'/'.join(合法级别表)} 之一", 来源="测试支持库.验证计划")
    根 = _解析根目录(仓库根目录)
    if 根 is None:
        return 结果.失败("目录不存在", f"仓库根目录不存在: {仓库根目录!r}", 来源="测试支持库.验证计划")
    try:
        上限 = int(最大条目数)
    except (TypeError, ValueError):
        return 结果.失败("参数不合法", "最大条目数 必须是整数", 来源="测试支持库.验证计划")
    if 上限 < 1:
        return 结果.失败("参数不合法", "最大条目数 必须大于 0", 来源="测试支持库.验证计划")
    上限 = min(上限, 硬上限条目数)

    目录表, 规范目标 = _规范化目标(根, str(目标路径))
    目录命中 = bool(目录表)
    文件表 = _收集测试文件(目录表)
    if not 文件表:
        回退 = _回退测试目录(根, 规范目标)
        新增 = [目录 for 目录 in 回退 if 目录 not in 目录表]
        if 新增:
            目录表 = 目录表 + 新增
            目录命中 = True
            文件表 = _收集测试文件(目录表)

    说明 = 只读说明
    命令列表: list[list[str]] = []
    模块列表: list[str] = []
    跳过清单: list[dict[str, Any]] = []

    if 级别文本 in ("阶段收口", "正式发布"):
        制品, 原因 = _制品相对路径(根, 制品目录)
        if 原因:
            命令列表 = []
            说明 = f"拒绝生成验证命令：{原因}；{只读说明}"
        else:
            命令列表.append(["python3.14", "-m", HTML验证入口, "--制品", 制品, "--并发", 默认制品并发])
            模块列表.append(HTML验证入口)
            if 级别文本 == "正式发布":
                命令列表.append(list(唯一发布命令))
                模块列表.append("开发工具/发布门禁/运行发布门禁.py")
    else:
        if not 目录命中 or not 文件表:
            return 结果.失败("目标不存在", f"目标路径不存在或不属于可扫描范围: {目标路径!r}", 来源="测试支持库.验证计划")
        关键词文本 = str(关键词 or "").strip()
        for 文件 in 文件表:
            模块, 原因 = _转模块名(根, 文件)
            if 原因:
                跳过清单.append({"路径": str(文件), "原因": 原因})
                continue
            if 关键词文本 and 关键词文本 not in 模块:
                continue
            模块列表.append(模块)
            if len(命令列表) < 上限:
                命令列表.append(["python3.14", "-m", 模块])
        if 关键词文本 and not 命令列表:
            说明 = f"目标范围内没有匹配关键词 {关键词文本!r} 的测试模块；{只读说明}"

    值 = {
        "仓库根": str(根),
        "目标路径": 规范目标,
        "级别": 级别文本,
        "测试模块列表": 模块列表,
        "命令列表": 命令列表,
        "命令数": len(命令列表),
        "跳过清单": 跳过清单,
        "只读": True,
        "说明": 说明,
    }
    return 结果.成功结果(值)


# ── 验证命令白名单 ────────────────────────────────────────────────────────

def _判定(允许: bool, 形态: str, 错误码: str, 消息: str, 命令: list[Any] | None = None,
         存在性校验: bool = False) -> dict[str, Any]:
    return {
        "允许": 允许,
        "形态": 形态,
        "错误码": 错误码,
        "消息": 消息,
        "规范化命令": [str(项) for 项 in (命令 or [])],
        "存在性校验": 存在性校验,
    }


def _拒绝(消息: str) -> dict[str, Any]:
    return _判定(False, "拒绝", 错误码_命令拒绝, 消息)


def _基础校验(命令: list[Any]) -> str:
    """公共安全校验：返回拒绝原因；空串表示通过。"""
    if not isinstance(命令, list) or not 命令:
        return "命令必须是包含非空字符串的列表"
    for 项 in 命令:
        if not isinstance(项, str) or not 项:
            return f"命令元素必须是非空字符串，发现 {项!r}"
        if any(字符 in 项 for 字符 in shell元字符表):
            return f"禁止 shell 元字符: {项!r}"
        if "shell=" in 项.lower():
            return f"禁止 shell=True 形式参数: {项!r}"
        if 项.startswith(("/", "~")):
            return f"禁止绝对路径: {项!r}"
        if ".." in 项:
            return f"禁止路径逃逸（..）: {项!r}"
    return ""


def _校验unittest形态(命令: list[Any], 根: Path | None, 校验存在: bool) -> dict[str, Any] | None:
    """只允许一个精确 unittest 模块，不接受额外参数。"""
    if len(命令) != 3 or 命令[1] != "-m":
        return _拒绝("开发期回归只允许 python3.14 -m <精确模块>")
    模块 = 命令[2]
    段表 = 模块.split(".")
    if any(not 段.isidentifier() for 段 in 段表):
        return _拒绝(f"测试模块包含非法标识符: {模块!r}")
    if not 段表[-1].startswith("测试_"):
        return _拒绝(f"只允许精确测试模块，末段必须以 测试_ 开头: {模块!r}")
    if 校验存在 and 根 is not None:
        解析 = (根 / Path(*段表)).with_suffix(".py").resolve()
        if not 解析.is_file() or not 解析.is_relative_to(根.resolve()):
            return _拒绝(f"测试模块不存在或逃逸工作根: {模块!r}")
    return None


def _校验HTML形态(命令: list[Any], 根: Path | None, 校验存在: bool) -> dict[str, Any] | None:
    """只允许对根内相对制品执行 HTML 黑盒验证，禁止服务、直连与生成模式。"""
    if len(命令) != 7 or 命令[1:3] != ["-m", HTML验证入口] or 命令[3] != "--制品" or 命令[5] != "--并发":
        return _拒绝("HTML 验证只允许 --制品 <相对目录> --并发 <整数>")
    制品 = str(命令[4]).replace("\\", "/")
    if not 制品 or 制品.startswith(("/", "~")) or ".." in Path(制品).parts:
        return _拒绝(f"HTML 制品路径必须是根内相对目录: {命令[4]!r}")
    if not str(命令[6]).isdigit() or not 1 <= int(命令[6]) <= 64:
        return _拒绝("HTML 验证并发数必须在 1..64")
    if 校验存在 and 根 is not None:
        解析 = (根 / 制品).resolve()
        if not 解析.is_dir() or not 解析.is_relative_to(根.resolve()):
            return _拒绝(f"HTML 制品目录不存在或逃逸工作根: {制品!r}")
    return None


def 验证命令白名单(命令: list[Any], 仓库根目录: str = "", 校验存在: bool = True) -> 结果:
    """白名单准入判定：三种受控形态，其余一律拒绝。"""
    if not isinstance(命令, list):
        return 结果.失败("参数不合法", "命令 必须是列表（每项非空字符串）", 来源="测试支持库.验证命令白名单")
    接口 = 结果.成功结果
    if isinstance(校验存在, str):
        校验存在 = str(校验存在).strip().lower() in ("true", "1", "真", "是")
    校验存在 = bool(校验存在)
    根 = _解析根目录(仓库根目录) if 校验存在 else None
    if 校验存在 and 根 is None:
        return 结果.失败("参数不合法", f"仓库根目录不存在: {仓库根目录!r}", 来源="测试支持库.验证命令白名单")

    基础原因 = _基础校验(命令)
    if 基础原因:
        return 接口(_拒绝(基础原因))
    if 命令[0] not in 允许可执行:
        return 接口(_拒绝(f"可执行程序不在白名单: {命令[0]!r}"))

    形态 = "拒绝"
    问题: dict[str, Any] | None = None
    if list(命令) == list(唯一发布命令):
        形态 = "正式发布"
    elif len(命令) > 2 and 命令[1:3] == ["-m", HTML验证入口]:
        形态 = "HTML验证"
        问题 = _校验HTML形态(命令, 根, 校验存在)
    elif len(命令) > 1 and 命令[1] == "-m":
        形态 = "unittest"
        问题 = _校验unittest形态(命令, 根, 校验存在)
    else:
        入口 = 命令[1] if len(命令) > 1 else "<缺失>"
        return 接口(_拒绝(f"验证入口不在白名单: {入口!r}"))

    if 问题 is not None:
        return 接口(问题)
    return 接口(_判定(True, 形态, "", f"命令通过白名单校验: {' '.join(str(项) for 项 in 命令)}",
                     命令, 校验存在))


# ── 验证结果判定 ──────────────────────────────────────────────────────────

收集错误模式 = re.compile(r"\bERROR\b")
零测试模式 = re.compile(r"no tests ran|ran 0 tests|未发现任何测试用例|零测试门禁失败", re.IGNORECASE)
真实执行证据模式 = re.compile(r"\bRan\s+[1-9]\d*\s+tests?\b|\b[1-9]\d*\s+passed\b|\bOK\b")
跳过标记模式 = re.compile(r"\bSKIPPED\b|skipped\b|跳过门禁失败|存在未执行场景")
跳过解释模式 = re.compile(r"原因|Skipped:|reason=|已解释|skipped ['\"]|skipped \(|skipped\(")
导入失败模式 = re.compile(
    r"ImportError|ModuleNotFoundError|ImportWarning|导入失败|加载失败|cannot import|No module named",
    re.IGNORECASE,
)
缓存假绿模式 = re.compile(r"缓存|cache|cached|__pycache__|命中缓存|来自缓存", re.IGNORECASE)


def _是精确模块命令(命令: list[Any] | None) -> bool:
    if not isinstance(命令, list) or len(命令) < 3 or not isinstance(命令[1], str):
        return False
    if 命令[1] != "-m" or not isinstance(命令[2], str):
        return False
    return 命令[2].split(".")[-1].startswith("测试_")


def _跳过列表未解释(跳过列表: list[Any] | None) -> list[str]:
    """结构化跳过记录里原因缺失/为空的用例。"""
    if not isinstance(跳过列表, list):
        return []
    未解释: list[str] = []
    for 项 in 跳过列表:
        if not isinstance(项, dict):
            未解释.append(str(项))
            continue
        用例 = str(项.get("用例") or 项.get("名称") or "<未命名用例>")
        原因 = 项.get("原因")
        if not isinstance(原因, str) or not 原因.strip():
            未解释.append(用例)
    return 未解释


def 验证结果判定(退出码: int, 标准输出: str = "", 标准错误: str = "",
               命令: list[Any] | None = None, 跳过列表: list[Any] | None = None) -> 结果:
    """真实执行输出 → 通过/阻断；零测试成功、导入失败当跳过、未解释跳过、缓存假绿一律阻断。"""
    if isinstance(退出码, bool) or not isinstance(退出码, int):
        return 结果.失败("参数不合法", "退出码 必须是整数（逻辑型不算整数）", 来源="测试支持库.验证结果判定")
    if 命令 is not None and not isinstance(命令, list):
        return 结果.失败("参数不合法", "命令 必须是列表", 来源="测试支持库.验证结果判定")
    if 跳过列表 is not None and not isinstance(跳过列表, list):
        return 结果.失败("参数不合法", "跳过列表 必须是列表", 来源="测试支持库.验证结果判定")

    文本 = f"{标准输出 or ''}\n{标准错误 or ''}"
    精确模块命令 = _是精确模块命令(命令)
    有真实执行证据 = bool(真实执行证据模式.search(文本))
    检出名: list[str] = []

    def 值(判定: str, 阻断码: str, 理由: str) -> dict[str, Any]:
        return {
            "判定": 判定,
            "阻断码": 阻断码,
            "理由": 理由,
            "检出": 检出名,
            "真实执行证据": 有真实执行证据,
            "退出码": 退出码,
        }

    def 阻断(阻断码: str, 理由: str) -> 结果:
        return 结果.成功结果(值("阻断", 阻断码, 理由))

    if 退出码 != 0:
        检出名.append("退出码非零")
        return 阻断(阻断码_验证失败, f"验证退出码非零: {退出码}")

    if 收集错误模式.search(文本) or "errors=" in 文本.lower():
        检出名.append("收集错误")
        return 阻断(阻断码_验证失败, "测试收集错误（ERROR / errors=）")

    没解释的跳过 = _跳过列表未解释(跳过列表)
    if 没解释的跳过:
        检出名.append("跳过列表未解释")
        return 阻断(阻断码_未解释跳过, f"跳过记录缺原因: {没解释的跳过[:5]}")

    if 跳过标记模式.search(文本) and 导入失败模式.search(文本):
        检出名.append("导入失败当跳过")
        return 阻断(阻断码_导入失败当跳过, "跳过标记伴随导入失败（ImportError/ModuleNotFoundError），不得当作已解释跳过")

    if 精确模块命令 and 缓存假绿模式.search(文本) and not 有真实执行证据:
        检出名.append("缓存假绿")
        return 阻断(阻断码_缓存假绿, "输出含缓存标记且无真实执行证据（Ran N tests / N passed），判定为缓存假绿")

    if 零测试模式.search(文本):
        检出名.append("零测试")
        return 阻断(阻断码_零测试, "未运行任何测试用例（no tests ran / ran 0 tests / 零测试门禁失败）")
    if 精确模块命令 and not 有真实执行证据:
        检出名.append("缺真实执行证据")
        return 阻断(阻断码_零测试, "精确测试模块执行完却没有 Ran N tests / N passed 真实执行证据，按零测试阻断")

    if 跳过标记模式.search(文本) and not 跳过解释模式.search(文本):
        检出名.append("未解释跳过")
        return 阻断(阻断码_未解释跳过, "存在无标记说明的跳过（SKIPPED/skip 无原因）")

    检出名.append("退出码为零且判定链全部通过")
    return 结果.成功结果(值("通过", "", "验证结果判定通过"))
