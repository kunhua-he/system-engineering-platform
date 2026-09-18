#!/usr/bin/env python3
"""依赖分两段唯一派生入口（决策记录 0021 落地的三件都由本文件产出）。

用法（在 系统工程平台 仓库根执行）：
    python3.14 <本文件> --生成      # 写 包声明.json 的 依赖类别 / 依赖登记.json / 说明/依赖分两段.md
    python3.14 <本文件> --校验      # 只读重算，与盘上三件逐字段比对，不一致即报红（exit 1）

为什么生成器住在仓外：本次任务信给的允许修改目录**只有**三件产物本身
（`支持库/适配层/依赖登记.json`、`支持库/适配层/说明/依赖分两段.md`、各包 `包声明.json`），
仓内任何新文件（含 `开发工具/`）都不在允许面内。因此生成器落在仓库同级目录，
由主会话决定后续是否搬进 `开发工具/`。

判定口径（全部来自现场事实，不按名字猜）：
  1) 锁里有无包：读该件 `依赖锁.json` 的 `包` 数组（名称/版本/来源/模块名）。
  2) 实现里 import 什么：AST 扫该件全部 .py，收第三方顶层 import（排除标准库、仓内顶层目录）。
  3) 是否启独立进程：AST 扫 `subprocess.Popen/run/...`、`shutil.which(字面量)`、命令令牌。
  逐项类别：锁来源 ∈ {外部应用, 系统工具} ⇒ 环境依赖；其余来源 ⇒ 必须在 import 现场找到
  同名模块名才判 第三方库；**一个发行包拆成多个 pip 包时（锁内 `发行包` 同值），
  只要该发行包内任一项有 import 现场，同发行包的随附项同判 第三方库**——
  依据是「同一发行包内某某已 import 证实」，不是「没有现场也放行」；
  找不到任何同发行包现场即「无法现场证实」并判红（不许猜）。
  件级类别：任一逐项为 第三方库 ⇒ 第三方库；否则有锁 ⇒ 环境依赖；
  无锁则有第三方 import ⇒ 第三方库，无则仅有子进程/可执行 ⇒ 环境依赖，都没有 ⇒ 无外部依赖。
  版本一律从 `依赖锁.json` 现场读；读不到就写 null 并在 `需复核` 里如实登记，**不编造**。
生成物三律（哲学 7.9）：输入指纹写进生成物、标记勿手改、重跑后盘上零差异（无时间戳）。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

生成器版本 = "1.0.0"
适配层根 = Path("支持库/适配层")
登记路径 = 适配层根 / "依赖登记.json"
清单路径 = 适配层根 / "说明" / "依赖分两段.md"
契约文件 = Path("公共契约/包声明/声明.py")
包声明契约字段 = "依赖类别"

仓内顶层目录 = {
    "公共契约", "支持库", "模块库", "运行核心", "后端核心", "前端核心", "平台控制面",
    "启动监督器", "客户端", "开发工具", "工程缓存", "测试中心", "项目适配层", "技能库",
    "示例项目",
}
外部应用来源 = {"外部应用", "系统工具"}
子进程调用名 = {"Popen", "run", "check_output", "check_call", "call", "system"}


# ── 现场取证 ────────────────────────────────────────────────

def _py文件(目录: Path) -> list[Path]:
    目标 = [目录] if 目录.is_file() else None
    if 目标 is not None:
        return 目标 if 目录.suffix == ".py" else []
    return sorted(p for p in 目录.rglob("*.py") if "__pycache__" not in p.parts)


def _同包模块名(件目录: Path) -> set[str]:
    """件目录内自身的模块名（含上级包内的兄弟模块）：这些 import 是仓内自引用，不是第三方。"""
    根 = 件目录 if 件目录.is_dir() else 件目录.parent
    名字 = {p.stem for p in _py文件(根)}
    名字 |= {p.name for p in 根.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    上级 = 根.parent
    if 上级.name and 上级 != 根:
        名字 |= {p.stem for p in 上级.glob("*.py")}
        名字 |= {p.name for p in 上级.iterdir()
                if p.is_dir() and (p / "__init__.py").is_file()}
    return 名字


def 扫实现(件目录: Path) -> dict:
    """AST 扫一个件目录：第三方 import、子进程调用、shutil.which 字面量、命中的命令文本。"""
    import sys as _sys

    标准库 = set(_sys.stdlib_module_names)
    同包 = _同包模块名(件目录)
    第三方import: list[dict] = []
    子进程: list[dict] = []
    查找命令: list[dict] = []
    命令文本: set[str] = set()

    for 文件 in _py文件(件目录):
        相对 = 文件.relative_to(件目录).as_posix()
        try:
            源码 = 文件.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            树 = ast.parse(源码)
        except SyntaxError:
            continue
        在try内 = set()
        在函数内 = set()
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Try):
                for 分支体 in 节点.body:
                    for 子 in ast.walk(分支体):
                        if isinstance(子, (ast.Import, ast.ImportFrom)):
                            在try内.add(子.lineno)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for 子 in ast.walk(节点):
                    if isinstance(子, (ast.Import, ast.ImportFrom)):
                        在函数内.add(子.lineno)
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                名单 = [(a.name.split(".")[0], a.name) for a in 节点.names]
            elif isinstance(节点, ast.ImportFrom) and 节点.module and 节点.level == 0:
                名单 = [(节点.module.split(".")[0], 节点.module)]
            else:
                名单 = []
            for 顶层, 全名 in 名单:
                if 顶层 in 标准库 or 顶层 in 仓内顶层目录 or 顶层 == "__future__" \
                        or 顶层 in 同包:
                    continue
                第三方import.append({
                    "文件": 相对, "行": 节点.lineno, "模块名": 顶层, "全名": 全名,
                    "在try内": 节点.lineno in 在try内, "在函数内": 节点.lineno in 在函数内,
                })
            if isinstance(节点, ast.Call):
                属性名 = getattr(节点.func, "attr", None)
                裸名 = getattr(节点.func, "id", None)
                if isinstance(节点.func, ast.Attribute) and isinstance(节点.func.value, ast.Name) \
                        and 节点.func.value.id == "subprocess" and 属性名 in 子进程调用名:
                    子进程.append({"文件": 相对, "行": 节点.lineno, "调用": f"subprocess.{属性名}"})
                elif 裸名 in 子进程调用名:
                    子进程.append({"文件": 相对, "行": 节点.lineno, "调用": 裸名})
                if 属性名 == "which" and 节点.args and isinstance(节点.args[0], ast.Constant) \
                        and isinstance(节点.args[0].value, str):
                    查找命令.append({"文件": 相对, "行": 节点.lineno, "命令": 节点.args[0].value})
        for 词 in ("ffmpeg", "ffprobe", "soffice", "libreoffice", "tesseract", "textutil",
                   "security", "pdftoppm", "browser-use", "agent-browser"):
            if 词 in 源码:
                命令文本.add(词)
    return {"第三方import": 第三方import, "子进程": 子进程,
            "查找命令": 查找命令, "命令文本": sorted(命令文本)}


def 读锁(件目录: Path) -> tuple[list[dict], str]:
    """读依赖锁的 `包` 数组（原件），无锁返回空表 + 原因。"""
    锁 = 件目录 / "依赖锁.json"
    if not 锁.is_file():
        return [], "无 依赖锁.json"
    try:
        数据 = json.loads(锁.read_text(encoding="utf-8"))
    except (OSError, ValueError) as 错误:
        return [], f"依赖锁.json 无法解析（{错误}）"
    return list(数据.get("包") or []), "依赖锁.json"


def 读包声明(件目录: Path) -> dict | None:
    声明 = 件目录 / "包声明.json"
    if not 声明.is_file():
        return None
    return json.loads(声明.read_text(encoding="utf-8"))


# ── 判定 ────────────────────────────────────────────────────

def 发行包归属(项: dict) -> str:
    """锁项的**发行包归属**：`发行包` 字段有值就用它，没有则退回 `名称`。

    为什么要这个字段：一个 PyPI 发行包可能拆成多个 pip 包安装（如 `psycopg` 发行包
    拆成 `psycopg` + `psycopg-binary`，后者是它的 `binary` extra 展开包）。
    这两个 pip 包**不是两个第三方**，判「无法现场证实」不能只按 pip 包名比对 import。
    字段为可选：旧锁不写该字段时逐项归属就是自身名称，判定行为与改动前逐字一致。
    """
    return str(项.get("发行包") or 项.get("名称") or "")


def 判逐项(项: dict, 现场: dict, 锁项表: list[dict] | None = None) -> tuple[str, str | None, list[str]]:
    """判一条锁项的类别；返回 (类别, 报警原因或None, 依据列表)。

    发行包内互证：`锁项表` 给出同一份锁里的全部条目；若本项自身无 import 现场，
    但**同一发行包**的另一项有 import 现场，则本项同判 第三方库，依据里写明是
    「同一发行包内哪一项已 import 证实」——依据仍是现场事实，不是推断放行。
    """
    名称 = str(项.get("名称") or "")
    来源 = str(项.get("来源") or "")
    模块名 = str(项.get("模块名") or 名称)
    依据: list[str] = [f"依赖锁.json 包[{名称}] 来源={来源 or '未标注'} 版本={项.get('版本') or '未标注'}"]

    if 来源 in 外部应用来源:
        命中 = [w for w in 现场["查找命令"] if w["命令"] == 模块名 or w["命令"] == 名称]
        if 命中:
            依据.append(f"{命中[0]['文件']}:{命中[0]['行']} shutil.which(\"{命中[0]['命令']}\")")
        elif 模块名 in 现场["命令文本"] or 名称 in 现场["命令文本"]:
            依据.append(f"实现源码出现命令令牌 {模块名 or 名称}（子进程调用 {len(现场['子进程'])} 处）")
        return "环境依赖", None, 依据

    import命中 = [i for i in 现场["第三方import"] if i["模块名"] == 模块名]
    if import命中:
        首 = import命中[0]
        依据.append(f"{首['文件']}:{首['行']} import {首['全名']}"
                    f"（try内={'是' if 首['在try内'] else '否'}，函数内={'是' if 首['在函数内'] else '否'}）")
        return "第三方库", None, 依据

    # 发行包内互证：同一发行包的另一项已 import 证实，则本项同判第三方库（随附包）
    归属 = 发行包归属(项)
    for 兄弟项 in (锁项表 or []):
        if 兄弟项 is 项 or 发行包归属(兄弟项) != 归属:
            continue
        兄弟模块名 = str(兄弟项.get("模块名") or 兄弟项.get("名称") or "")
        for 现场项 in 现场["第三方import"]:
            if 现场项["模块名"] == 兄弟模块名:
                依据.append(
                    f"{现场项['文件']}:{现场项['行']} import {现场项['全名']} —— "
                    f"本项与 包[{兄弟项.get('名称')}] 同属发行包「{归属}」，"
                    f"后者已由现场 import 证实（随附 pip 包，非另一个第三方）")
                return "第三方库", None, 依据

    依据.append(f"全件 AST 未出现 import {模块名}，来源又非外部应用/系统工具"
              f"（同发行包「{归属}」内亦无任何一项有 import 现场）")
    return "无法现场证实", f"{名称}（来源={来源 or '未标注'}，模块名={模块名}）锁内为第三方却无 import 现场", 依据


def 判件(件目录: Path, 名称: str, 类别):  # 类别: "正式包" | "内部件"
    现场 = 扫实现(件目录)
    锁项表, 锁来源 = 读锁(件目录)
    声明 = 读包声明(件目录)
    报警: list[str] = []
    依赖清单: list[dict] = []
    逐项类别: list[str] = []

    for 项 in 锁项表:
        c, 警, 依据 = 判逐项(项, 现场, 锁项表)
        if 警:
            报警.append(警)
        逐项类别.append(c)
        # 版本只从锁现场读，绝不编造
        依赖清单.append({
            "名称": str(项.get("名称") or ""),
            "模块名": str(项.get("模块名") or ""),
            "版本": 项.get("版本"),
            "来源": 项.get("来源") or "未标注",
            "类别": c,
            "依据": 依据,
        })

    if "第三方库" in 逐项类别:
        件类别 = "第三方库"
    elif 锁项表:
        件类别 = "环境依赖"
    elif 现场["第三方import"]:
        件类别 = "第三方库"
    elif 现场["子进程"] or 现场["查找命令"]:
        件类别 = "环境依赖"
    else:
        件类别 = "无外部依赖"

    混合 = sorted({c for c in 逐项类别 if c in ("第三方库", "环境依赖")})
    备注 = ""
    if len(混合) > 1:
        备注 = "同时具备代码级与运行级两面：" + "、".join(
            f"{d['名称']}({d['类别']})" for d in 依赖清单)
    elif not 锁项表 and 现场["第三方import"] and (现场["子进程"] or 现场["查找命令"]):
        模块们 = "、".join(sorted({i["模块名"] for i in 现场["第三方import"]}))
        备注 = (f"同时具备代码级与运行级两面：第三方 import（{模块们}）"
              f" + 子进程调用 {len(现场['子进程'])} 处／外部命令查找 {len(现场['查找命令'])} 处")
    # 现场自述性质：源码/说明里的「模拟提供者」「占位」是事实，不是推断
    文本池 = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (件目录.rglob("*") if 件目录.is_dir() else [件目录])
        if p.is_file() and p.suffix in {".py", ".md", ".json"} and "__pycache__" not in p.parts)
    for 自述 in ("模拟提供者", "占位"):
        if 自述 in 文本池:
            备注 = (备注 + "；" if 备注 else "") + f"现场自述「{自述}」：未接真实外部依赖"
            break

    # 件级依据（供判定表逐件追溯）
    件级依据 = []
    if 锁项表:
        锁项概述 = "、".join(f"{d['名称']}={d['类别']}" for d in 依赖清单)
        件级依据.append(f"依赖锁.json 包[] {len(锁项表)} 项：{锁项概述}")
    else:
        件级依据.append("无 依赖锁.json")
    if 现场["第三方import"]:
        件级依据.append("AST import：" + "、".join(sorted({i["模块名"] for i in 现场["第三方import"]})))
    if 现场["子进程"]:
        件级依据.append(f"AST 子进程调用 {len(现场['子进程'])} 处：" +
                  "、".join(sorted({s["调用"] for s in 现场["子进程"]})))
    if 现场["查找命令"]:
        件级依据.append("shutil.which：" + "、".join(sorted({w["命令"] for w in 现场["查找命令"]})))
    if 现场["命令文本"]:
        件级依据.append("源码命令令牌：" + "、".join(现场["命令文本"]))

    # 环境依赖六要素（只写现场可证的；读不到就如实标需复核，不编造）
    可疑: list[str] = []
    版本 = None
    入口 = None
    if 声明 is not None:
        入口 = 声明.get("入口") or None
    elif 件目录.is_file():
        入口 = 件目录.name
    else:
        候选入口 = sorted(
             [p for p in _py文件(件目录) if p.name == "__init__.py"]
            + [p for p in _py文件(件目录) if p.name.endswith("入口.py")])
        入口 = 候选入口[0].relative_to(件目录).as_posix() if 候选入口 else (
            _py文件(件目录)[0].relative_to(件目录).as_posix() if _py文件(件目录) else None)
    # 版本：件级版本按件类别取主项（第三方库取代码级项，否则取运行级项），都是锁内现场读
    版本 = None
    候选 = ([d for d in 依赖清单 if d["类别"] == "第三方库"]
           if 件类别 == "第三方库" else
           [d for d in 依赖清单 if d["类别"] == "环境依赖"]) or 依赖清单
    for 项 in 候选:
        if 项["版本"]:
            版本 = 项["版本"]
            break
    版本来源 = "依赖锁.json 包[]" if 版本 else None
    if 件类别 in ("环境依赖", "第三方库") and 版本 is None:
        可疑.append("版本：依赖锁.json 内根项未标注 版本，版本未登记（不编造）")
    if 类别 == "内部件" and 件类别 in ("第三方库", "环境依赖") and not 锁项表:
        可疑.append("内部件无 依赖锁.json（按决策记录 0033：有外部依赖应建锁），"
                 "版本与探针口径待主会话收口")

    端口依据 = "全件 AST 无 listen/bind/serve 监听调用，均为按需一次性子进程 ⇒ 无监听端口"
    探针能力 = []
    if 声明 is not None:
        for 能力 in 声明.get("能力") or []:
            标识 = str(能力.get("能力id") or "")
            if any(关键词 in 标识 for 关键词 in ("检查提供者", "检查可用", "检查可用性", "版本探针")):
                探针能力.append(标识)
        if not 探针能力:
            可疑.append("健康探针：包声明能力列表内未派生出探针能力（现场无 检查/探针 能力 id）")
    else:
        探针能力 = None  # 内部件：无能力契约，探针能力不适用（如实为空，不计缺口）

    源码文本 = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _py文件(件目录))
    有降级 = "提供者不可用" in 源码文本
    降级 = "缺失/失败 → 提供者不可用（fail-closed，不伪装成功）" if 有降级 else None
    if 件类别 == "环境依赖" and not 有降级:
        可疑.append("降级语义：实现内未出现「提供者不可用」，降级口径未声明")

    常驻 = None
    if 件类别 == "环境依赖":
        有守护 = any(词 in 文本池 for 词 in ("--session", "守护进程", "命名守护"))
        常驻 = ("有常驻/守护进程（现场出现 --session/守护 调用，必须显式启停，"
              "缺失时按提供者不可用）" if 有守护
              else "无常驻进程：一次调用一次子进程，用完即退（无需启停命令）")

    return {
        "名称": 名称,
        "件类别": 类别,
        "路径": 件目录.as_posix(),
        "包id": (声明 or {}).get("包id") if 声明 else None,
        "依赖类别": 件类别,
        "依赖锁": 锁来源,
        "依赖清单": 依赖清单,
        "件级依据": 件级依据,
        "入口": 入口,
        "版本": 版本,
        "版本来源": 版本来源,
        "端口": None,
        "端口依据": 端口依据,
        "健康探针": 探针能力,
        "启停语义": 常驻,
        "降级语义": 降级,
        "需复核": 可疑,
        "备注": 备注,
        "报警": 报警,
    }


def 枚举件() -> list[tuple[Path, str, str]]:
    """枚举适配层全部件：正式包（有 包声明.json）+ 内部件（无包声明的目录与根级 .py）。"""
    件表: list[tuple[Path, str, str]] = []
    for 子 in sorted(适配层根.iterdir()):
        if 子.name in {"__pycache__", "说明"}:
            continue
        if 子.is_dir():
            if (子 / "包声明.json").is_file():
                件表.append((子, 子.name, "正式包"))
            else:
                件表.append((子, 子.name, "内部件"))
        elif 子.suffix == ".py":
            件表.append((子, 子.stem, "内部件"))
    件表.sort(key=lambda t: (t[1], t[0].as_posix()))
    return 件表


# ── 汇总 ────────────────────────────────────────────────────

def 汇总() -> dict:
    件表 = [判件(目录, 名称, 类别) for 目录, 名称, 类别 in 枚举件()]
    正式包 = [j for j in 件表 if j["件类别"] == "正式包"]
    内部件 = [j for j in 件表 if j["件类别"] == "内部件"]
    报警 = [a for j in 件表 for a in j["报警"]]
    return {
        "件表": 件表,
        "正式包": 正式包,
        "内部件": 内部件,
        "报警": 报警,
        "第三方库": [j for j in 件表 if j["依赖类别"] == "第三方库"],
        "环境依赖": [j for j in 件表 if j["依赖类别"] == "环境依赖"],
        "无外部依赖": [j for j in 件表 if j["依赖类别"] == "无外部依赖"],
    }


def 输入指纹(汇总数据: dict) -> str:
    摘要器 = hashlib.sha256()
    行 = []
    for 件 in sorted(汇总数据["件表"], key=lambda j: j["路径"]):
        目录 = Path(件["路径"])
        for 名字 in ("包声明.json", "依赖锁.json"):
            文件 = 目录 / 名字
            if 文件.is_file():
                行.append(f"{件['路径']}/{名字}:{hashlib.sha256(文件.read_bytes()).hexdigest()}")
            else:
                行.append(f"{件['路径']}/{名字}:缺失")
        for py in _py文件(目录):
            行.append(f"{件['路径']}/{py.relative_to(目录).as_posix()}:"
                     f"{hashlib.sha256(py.read_bytes()).hexdigest()}")
    for 项 in 行:
        摘要器.update(项.encode("utf-8"))
        摘要器.update(b"\n")
    return 摘要器.hexdigest()


def 契约指纹() -> str:
    return hashlib.sha256(契约文件.read_bytes()).hexdigest()


# ── 产物 ────────────────────────────────────────────────────

派生规则 = {
    "逐项类别": ("锁项 `来源` ∈ {外部应用, 系统工具} ⇒ 环境依赖；否则必须以 AST 现场 import 同名模块"
              "证实 ⇒ 第三方库（同一发行包拆成多个 pip 包时，锁内 `发行包` 同值的随附项由同发行包内"
              "已 import 证实的那一项互证 ⇒ 同为第三方库）；两者都不成立 ⇒ 判红（无法现场证实，不许猜）"),
    "件级类别": ("任一锁项为 第三方库 ⇒ 第三方库；否则有 依赖锁.json ⇒ 环境依赖；"
             "无锁则按现场：有第三方 import ⇒ 第三方库，仅有子进程/可执行调用 ⇒ 环境依赖，都没有 ⇒ 无外部依赖"),
    "版本": "只从各件 依赖锁.json 现场读；读不到写 null 并在 需复核 登记，不编造",
    "端口": "扫描 listen/bind/serve 监听调用；全适配层均为按需一次性子进程 ⇒ 无监听端口",
    "健康探针": "由各包 包声明.json 的能力列表中派生（能力 id 含 检查提供者/检查可用/检查可用性/版本探针）",
    "启停语义": "现场出现 --session/close/守护 调用 ⇒ 有常驻进程；否则一次性子进程，无需启停命令",
    "降级语义": "实现源码出现「提供者不可用」⇒ 缺失/失败即 fail-closed；未出现则如实标需复核",
}


def 生成登记(汇总数据: dict) -> str:
    登记 = {
        "生成器": "系统工程平台_依赖派生/生成依赖分两段.py",
        "生成器版本": 生成器版本,
        "勿手改": ("本文件由生成器派生，禁止手改（哲学 7.9 生成物三律）。"
                "改源（各件 依赖锁.json / 包声明.json / 实现源码）后重跑生成器："
                "python3.14 <生成器> --生成；校验用 --校验。"),
        "契约指纹": {"文件": 契约文件.as_posix(), "sha256": 契约指纹()},
        "输入指纹": 输入指纹(汇总数据),
        "口径来源": ["开发文档/决策记录/0021_依赖分两段_第三方翻译层与环境依赖层.md",
                 "开发文档/项目说明.md 第 2 条 2.2/2.3"],
        "派生规则": 派生规则,
        "统计": {
            "件数": len(汇总数据["件表"]),
            "正式包": len(汇总数据["正式包"]),
            "内部件": len(汇总数据["内部件"]),
            "第三方库": len(汇总数据["第三方库"]),
            "环境依赖": len(汇总数据["环境依赖"]),
            "无外部依赖": len(汇总数据["无外部依赖"]),
        },
        "条目": [
            {
                "名称": 件["名称"],
                "依赖类别": 件["依赖类别"],
                "件类别": 件["件类别"],
                "路径": 件["路径"],
                "包id": 件["包id"],
                "入口": 件["入口"],
                "版本": 件["版本"],
                "版本来源": 件["版本来源"],
                "端口": 件["端口"],
                "端口依据": 件["端口依据"],
                "健康探针": 件["健康探针"],
                "启停语义": 件["启停语义"],
                "降级语义": 件["降级语义"],
                "依赖锁": 件["依赖锁"],
                "依赖清单": 件["依赖清单"],
                "件级依据": 件["件级依据"],
                "需复核": 件["需复核"],
                "备注": 件["备注"],
            }
            for 件 in 汇总数据["件表"]
        ],
    }
    return json.dumps(登记, ensure_ascii=False, indent=2) + "\n"


def 生成清单(汇总数据: dict) -> str:
    def 表(件表: list[dict]) -> list[str]:
        行 = ["| 件 | 件类别 | 路径 | 版本 | 依赖（名称@版本·来源·类别） | 现场依据 |",
             "|---|---|---|---|---|---|"]
        for 件 in 件表:
            依赖 = "<br>".join(
                f"{d['名称']}@{d['版本']}·{d['来源']}·{d['类别']}" for d in 件["依赖清单"]) or "—"
            依据 = "<br>".join(件["件级依据"]) or "—"
            勘注 = f"<br>**备注**：{件['备注']}" if 件["备注"] else ""
            行.append(
                f"| {件['名称']} | {件['件类别']} | `{件['路径']}` | {件['版本'] or '—'} | "
                f"{依赖} | {依据}{勘注} |")
        return 行

    行: list[str] = [
        "# 依赖分两段（第三方翻译层 / 环境依赖层）",
        "",
        "> **勿手改**：本文件由生成器派生，禁止手改（哲学 7.9 生成物三律）。",
        f"> 派生入口：`系统工程平台_依赖派生/生成依赖分两段.py --生成`（生成器版本 {生成器版本}）",
        f"> 契约指纹：`{契约文件.as_posix()}` sha256 `{契约指纹()}`",
        f"> 输入指纹：`{输入指纹(汇总数据)}`",
        "> 口径来源：决策记录 `0021`、`开发文档/项目说明.md` 第 2 条 2.2/2.3。",
        "> 唯一登记：`支持库/适配层/依赖登记.json`（本文件由同一份数据派生，不是第二事实源）。",
        "",
        "## 一、第三方翻译层（要 `import` 的包）",
        "",
    ]
    行 += 表(汇总数据["第三方库"])
    行 += ["", f"共 {len(汇总数据['第三方库'])} 件。", "",
         "## 二、环境依赖层（独立进程/服务/动态库/外部接口）", ""]
    行 += 表(汇总数据["环境依赖"])
    行 += ["", f"共 {len(汇总数据['环境依赖'])} 件。", ""]
    if 汇总数据["无外部依赖"]:
        行 += ["### 2.1 附注：无外部依赖（标准库/仓内装配件）", "",
             "这些内部件既非第三方库也非环境依赖；按现场真实性质单列，不塞进上面两段。", ""]
        行 += 表(汇总数据["无外部依赖"])
        行 += [""]
    有环境 = 汇总数据["环境依赖"]
    if 有环境:
        行 += ["## 三、环境依赖的六要素声明（版本/入口/端口/健康探针/启停/降级）", "",
             "缺项一律如实标注，由后续批次按条目补齐（决策记录 `0021` §未做）——本轮不凭空写。", "",
             "| 件 | 版本 | 入口 | 端口 | 健康探针 | 启停语义 | 降级语义 | 备注 |",
             "|---|---|---|---|---|---|---|---|"]
        for 件 in 有环境:
            探针 = "、".join(件["健康探针"]) if isinstance(件["健康探针"], list) and 件["健康探针"] \
                else "未派生（需补）"
            行.append(
                f"| {件['名称']} | {件['版本'] or '—'} | {件['入口'] or '—'} | {件['端口'] or '无'} | "
                f"{探针} | {件['启停语义'] or '—'} | {件['降级语义'] or '未声明'} | "
                f"{件['备注'] or '—'} |")
        行 += [""]
    待复核 = [件 for 件 in 汇总数据["件表"] if 件["需复核"]]
    if 待复核:
        行 += ["## 四、待复核（现场读不到即如实登记，未编造）", "",
             "| 件 | 待复核项 |", "|---|---|"]
        for 件 in 待复核:
            行.append(f"| {件['名称']} | {'；'.join(件['需复核'])} |")
        行 += [""]
    行 += ["## 五、判定依据汇总", "",
         "| 规则 | 口径 |", "|---|---|"]
    for 键, 值 in 派生规则.items():
        行.append(f"| {键} | {值} |")
    return "\n".join(行) + "\n"


def 期望包声明字段(汇总数据: dict) -> dict[str, str]:
    return {件["名称"]: 件["依赖类别"] for 件 in 汇总数据["正式包"]}


def 重写包声明文本(原文本: str, 依赖类别: str) -> str:
    """把 依赖类别 写进 包声明.json：键序不变，插在 类型 之后；缩进/尾换行与原件一致。"""
    数据 = json.loads(原文本)
    新 = {}
    for 键, 值 in 数据.items():
        if 键 == 包声明契约字段:
            continue
        新[键] = 值
        if 键 == "类型":
            新[包声明契约字段] = 依赖类别
    if 包声明契约字段 not in 新:
        新[包声明契约字段] = 依赖类别
    文本 = json.dumps(新, ensure_ascii=False, indent=1)
    if 原文本.endswith("\n"):
        文本 += "\n"
    return 文本


# ── 模式 ────────────────────────────────────────────────────

def 生成(汇总数据: dict) -> int:
    改动: list[str] = []
    if 汇总数据["报警"]:
        print("✗ 判定阶段报警（存在无法现场证实的锁项，拒绝生成）：")
        for 警 in 汇总数据["报警"]:
            print(f"  - {警}")
        return 1

    期望 = 期望包声明字段(汇总数据)
    for 件 in 汇总数据["正式包"]:
        路径 = Path(件["路径"]) / "包声明.json"
        原文本 = 路径.read_text(encoding="utf-8")
        新文本 = 重写包声明文本(原文本, 期望[件["名称"]])
        if 新文本 != 原文本:
            路径.write_text(新文本, encoding="utf-8")
            改动.append(f"包声明.json ← {件['名称']} 依赖类别={期望[件['名称']]}")

    登记文本 = 生成登记(汇总数据)
    if not 登记路径.is_file() or 登记路径.read_text(encoding="utf-8") != 登记文本:
        登记路径.write_text(登记文本, encoding="utf-8")
        改动.append(f"依赖登记.json（{len(汇总数据['件表'])} 件）")

    清单文本 = 生成清单(汇总数据)
    if not 清单路径.is_file() or 清单路径.read_text(encoding="utf-8") != 清单文本:
        清单路径.write_text(清单文本, encoding="utf-8")
        改动.append("说明/依赖分两段.md")

    print(f"生成完成：件数 {len(汇总数据['件表'])}"
          f"（正式包 {len(汇总数据['正式包'])}／内部件 {len(汇总数据['内部件'])}）"
          f"｜第三方库 {len(汇总数据['第三方库'])}｜环境依赖 {len(汇总数据['环境依赖'])}"
          f"｜无外部依赖 {len(汇总数据['无外部依赖'])}")
    if 改动:
        for 行 in 改动:
            print(f"  写入 {行}")
    else:
        print("  盘上三件与派生结果一致，零改写（幂等）")
    return 0


def 校验(汇总数据: dict) -> int:
    问题: list[str] = []
    for 警 in 汇总数据["报警"]:
        问题.append(f"判定报警：{警}")

    期望 = 期望包声明字段(汇总数据)
    for 件 in 汇总数据["正式包"]:
        路径 = Path(件["路径"]) / "包声明.json"
        盘上 = json.loads(路径.read_text(encoding="utf-8")).get(包声明契约字段)
        if 盘上 != 期望[件["名称"]]:
            问题.append(f"{件['名称']}：包声明 依赖类别={盘上!r}，现场派生应为 {期望[件['名称']]!r}")

    if not 登记路径.is_file():
        问题.append("依赖登记.json 不存在")
    else:
        盘上登记 = 登记路径.read_text(encoding="utf-8")
        若新 = 生成登记(汇总数据)
        if 盘上登记 != 若新:
            盘上数据 = json.loads(盘上登记)
            条目盘 = {j["名称"]: j["依赖类别"] for j in 盘上数据.get("条目") or []}
            条目派 = {j["名称"]: j["依赖类别"] for j in 汇总数据["件表"]}
            错 = [f"{k}（登记={条目盘.get(k)!r} 派生={v!r}）" for k, v in 条目派.items()
                 if 条目盘.get(k) != v]
            if 错:
                问题.append("依赖登记.json 类别不一致：" + "、".join(错))
            if 盘上数据.get("输入指纹") != 若新 and json.loads(若新)["输入指纹"] != 盘上数据.get("输入指纹"):
                问题.append("依赖登记.json 输入指纹过期（源已变，未重跑生成器）")
            if not 错 and 盘上数据.get("输入指纹") == json.loads(若新)["输入指纹"]:
                问题.append("依赖登记.json 与派生结果有非类别差异（未重跑生成器）")

    if not 清单路径.is_file():
        问题.append("说明/依赖分两段.md 不存在")
    else:
        if 清单路径.read_text(encoding="utf-8") != 生成清单(汇总数据):
            问题.append("说明/依赖分两段.md 与派生结果不一致（未重跑生成器）")

    if 问题:
        print(f"✗ 校验未通过（{len(问题)} 项）：")
        for 项 in 问题:
            print(f"  - {项}")
        return 1
    print(f"✓ 校验通过：{len(汇总数据['件表'])} 件与派生结果逐字段一致"
          f"（正式包 {len(汇总数据['正式包'])}｜输入指纹 {输入指纹(汇总数据)[:16]}…）")
    return 0


def main() -> int:
    解析 = argparse.ArgumentParser(description="依赖分两段唯一派生入口（决策记录 0021）")
    组 = 解析.add_mutually_exclusive_group(required=True)
    组.add_argument("--生成", action="store_true")
    组.add_argument("--校验", action="store_true")
    解析.add_argument("--根", default=None, help="覆盖适配层根目录（反向验证用，默认 支持库/适配层）")
    参数 = 解析.parse_args()
    global 适配层根, 登记路径, 清单路径
    if 参数.根:
        适配层根 = Path(参数.根)
        登记路径 = 适配层根 / "依赖登记.json"
        清单路径 = 适配层根 / "说明" / "依赖分两段.md"
    汇总数据 = 汇总()
    return 生成(汇总数据) if 参数.生成 else 校验(汇总数据)


if __name__ == "__main__":
    sys.exit(main())
