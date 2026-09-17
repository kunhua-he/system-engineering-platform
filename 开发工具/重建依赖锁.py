"""按当前平台重建依赖锁：依赖锁「环境」指纹的唯一正式生成入口（禁止手改 JSON）。

背景（华哥 2026-09-16 裁决：底座做完整跨平台）
    仓库内依赖锁共 32 份，32 份全部写死生成机指纹（Python 3.14.4 / macOS / arm64）。
    换平台装配时被 `运行核心.运行环境管理器.强制校验` 规则 5 逐条拒绝：
    「环境指纹不符：锁内 操作系统 'macOS' ≠ 当前 'Windows'（请按当前环境重建依赖锁）」。
    此前**没有任何**「重建依赖锁」入口（唯一的写锁代码是 `支持库模板生成器`，写的是
    骨架空锁），所以那 32 份锁只能手改——本模块补上这个正式入口。

    本机（macOS）重建出来的仍然是 macOS 锁，这是正常的；机制建立后，别人在自己的
    平台跑同一个入口，就得到他们平台的锁。

语义边界（只刷新平台指纹，不做依赖升级）
    刷新：环境（Python / 操作系统 / CPU）、生成时间。
      环境的三个值全部由 `运行核心.环境指纹.计算环境指纹` 真实采样（锁文件从不
      写死、不猜测），操作系统名取 `公共契约.运行时.平台适配.当前平台()`——与
      `强制校验` 的口径一致：只比系统大类，不把内核 Build 号写进锁（写进去会让
      同一平台的两台机器互不匹配，与门禁自己的「忽略版本与 Build 号」相冲）。
    原样保留：包 / 直接依赖 / 依赖闭包 / 提供者id / 说明 / 辅助依赖，以及**文件原有
      排版**——环境块与生成时间按定点文本替换写回，不整体重排 JSON，避免无关字节漂移。
    第三方与外部工具**版本漂移只提示不自动改写**（升级依赖是另一件事，需单独裁决）：
      干跑会列出外部应用条目「锁内版本 → 探针版本」的漂移，写明「本批不自动改写」，落盘只动
      环境与生成时间；确认要连版本一起刷新，应另立一批（依赖升级口径）后再扩本入口。

    锁文件被包自己的 `完整性摘要.json` 登记哈希，改锁不改摘要会让
    「组件合规.完整性摘要」与「发布门禁.摘要一致」变红，故本入口在写完锁之后
    **定点**刷新登记了该锁的摘要条目（只改那一条 sha256，不扫不写别的包）。

用法
    python3.14 -m 开发工具.重建依赖锁 --干跑
    python3.14 -m 开发工具.重建依赖锁 --干跑 --包 支持库/后端/数据库连接支持库/SQLite数据库
    python3.14 -m 开发工具.重建依赖锁 --写入 --包 <包相对路径 | 包目录名 | 包id>
    python3.14 -m 开发工具.重建依赖锁 --写入 --全部        # 批量重建必须显式 --全部

    --干跑 为默认行为（只报差异，不写盘）；写盘必须显式 --写入。
    批量写盘必须同时给 --全部（防止「一个手滑改了 32 份锁」）。

幂等口径
    「需重建」== 环境与当前平台不一致。环境已一致（本机锁 + 本机平台）时本入口
    不改任何字节，重复跑不会脏 git 树/不无谓重算摘要；换平台时必然重建。只想刷新
    生成时间时用 `--刷新生成时间`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

进度前缀 = "[重建依赖锁]"
锁文件名 = "依赖锁.json"
摘要文件名 = "完整性摘要.json"
扫描根 = ("支持库", "模块库", "技能库")
环境键顺序 = ("Python", "操作系统", "CPU")


# ═══════════════════════════════════════════════════════════════════
# 定位与采样
# ═══════════════════════════════════════════════════════════════════

def 系统根() -> Path:
    """向上定位工程根（同时含 支持库 与 开发工具 的祖先）。"""
    候选 = Path(__file__).resolve()
    for 祖先 in 候选.parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "开发工具").is_dir():
            return 祖先
    raise RuntimeError("无法定位工程根（缺少 支持库／开发工具 双目录）")


def 采样环境() -> dict[str, str]:
    """真实采样当前环境指纹（唯一来源：运行核心.环境指纹）。

    采样结果不合法（Python 版本号无法判定 / 平台名未知 / CPU 为空）即抛异常，
    **绝不用占位值落盘**——写坏的锁比不写更糟。
    """
    根 = 系统根()
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    from 运行核心.环境指纹 import 计算环境指纹
    from 公共契约.运行时.平台适配 import 当前平台

    详细信息 = 计算环境指纹(含外部应用=False).详细信息
    python版本 = str(详细信息.get("python", "")).strip()
    cpu = str(详细信息.get("架构", "")).strip()
    操作系统 = 当前平台()
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", python版本):
        raise RuntimeError(f"采样到的 Python 版本号不可判定：{python版本!r}")
    if 操作系统 == "未知":
        raise RuntimeError(f"采样到的平台名未知（sys.platform={sys.platform!r}），禁止写锁")
    if not cpu:
        raise RuntimeError("采样到的 CPU 架构为空，禁止写锁")
    return {"Python": python版本, "操作系统": 操作系统, "CPU": cpu}


def 采样外部工具版本() -> dict[str, str]:
    """真实探测外部应用版本（LibreOffice / textutil），只用于「版本漂移提示」。"""
    根 = 系统根()
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    try:
        from 运行核心.环境指纹 import 探测外部应用版本
        return dict(探测外部应用版本())
    except Exception as 错误:  # 探针失败不阻断重建：只退化为「未探测」
        return {"_探针失败": str(错误)}


# ═══════════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════════

def 枚举依赖锁() -> list[Path]:
    """枚举全部依赖锁（支持库／模块库／技能库 三根，按路径排序）。"""
    根 = 系统根()
    结果: list[Path] = []
    for 目录名 in 扫描根:
        目录 = 根 / 目录名
        if 目录.is_dir():
            结果.extend(排序键 for 排序键 in 目录.rglob(锁文件名))
    return sorted(结果)


def 枚举摘要文件() -> list[Path]:
    """枚举全部完整性摘要（用于定点刷新被改锁的登记哈希）。"""
    根 = 系统根()
    结果: list[Path] = []
    for 目录名 in 扫描根:
        目录 = 根 / 目录名
        if 目录.is_dir():
            结果.extend(目录.rglob(摘要文件名))
    return sorted(结果)


def 匹配目标锁(选择: str, 全部锁: list[Path]) -> tuple[list[Path], list[str]]:
    """按 包相对路径／包目录名／包id 选中锁；未命中如实回带。"""
    根 = 系统根()
    命中: list[Path] = []
    未命中: list[str] = []
    待选 = [项.strip() for 项 in 选择.split(",") if 项.strip()]
    for 项 in 待选:
        候选 = 根 / 项
        候选锁 = 候选 / 锁文件名
        选中的 = [锁 for 锁 in 全部锁 if 锁 == 候选锁 or 锁.parent.name == 项
                 or 锁.parent == 候选]
        if not 选中的:
            # 退一步按 提供者id / 包id 精确匹配锁内声明
            选中的 = [锁 for 锁 in 全部锁 if _锁内提供者id(锁) == 项]
        if not 选中的:
            未命中.append(项)
            continue
        for 锁 in 选中的:
            if 锁 not in 命中:
                命中.append(锁)
    return 命中, 未命中


def _锁内提供者id(锁路径: Path) -> str:
    try:
        return str(json.loads(锁路径.read_text(encoding="utf-8")).get("提供者id", ""))
    except (json.JSONDecodeError, OSError):
        return ""


# ═══════════════════════════════════════════════════════════════════
# 文本定点替换（保排版）
# ═══════════════════════════════════════════════════════════════════

环境块模式 = re.compile(r'("环境"\s*:\s*)(\{[^{}]*\})')
生成时间模式 = re.compile(r'("生成时间"\s*:\s*)"([^"]*)"')


def _格式化环境块(原块: str, 环境: dict[str, str]) -> str:
    """按原块排版风格生成新的环境块（单行保持单行，多行保持多行缩进）。"""
    键表 = [(键, 环境[键]) for 键 in 环境键顺序 if 键 in 环境]
    键表 += [(键, 值) for 键, 值 in 环境.items() if 键 not in 环境键顺序]
    单行 = "{" + ", ".join(f'"{键}": {json.dumps(值, ensure_ascii=False)}'
                          for 键, 值 in 键表) + "}"
    if "\n" not in 原块:
        return 单行
    内缩 = re.search(r"\{\n([ \t]*)", 原块)
    闭缩 = re.search(r"\n([ \t]*)\}", 原块)
    if not 内缩 or not 闭缩:
        return 单行
    项目 = (",\n").join(f'{内缩.group(1)}"{键}": {json.dumps(值, ensure_ascii=False)}'
                       for 键, 值 in 键表)
    return "{\n" + 项目 + "\n" + 闭缩.group(1) + "}"


def 计算新锁文本(原文本: str, 原数据: dict[str, Any], 新环境: dict[str, str],
                新生成时间: str | None) -> tuple[str, list[str]]:
    """生成新锁文本（只动 环境／生成时间），并自检除这两者外结构未变。"""
    问题: list[str] = []
    新文本, 环境次数 = 环境块模式.subn(
        lambda 匹配: 匹配.group(1) + _格式化环境块(匹配.group(2), 新环境), 原文本, count=1)
    if 环境次数 != 1:
        问题.append(f"环境块定位失败（命中 {环境次数} 处），拒绝改写")
        return 原文本, 问题
    if 新生成时间 is not None:
        新文本, 时间次数 = 生成时间模式.subn(
            lambda 匹配: f'{匹配.group(1)}"{新生成时间}"', 新文本, count=1)
        if 时间次数 != 1:
            问题.append(f"生成时间定位失败（命中 {时间次数} 处），拒绝改写")
            return 原文本, 问题
    try:
        新数据 = json.loads(新文本)
    except json.JSONDecodeError as 错误:
        return 原文本, [f"改写后不是合法 JSON：{错误}"]
    差分键 = sorted(键 for 键 in {*原数据, *新数据}
                  if 原数据.get(键) != 新数据.get(键))
    越界 = [键 for 键 in 差分键 if 键 not in ("环境", "生成时间")]
    if 越界:
        问题.append(f"改写越界（除 环境/生成时间 外还动了 {越界}），拒绝写入")
        return 原文本, 问题
    if 新数据.get("环境") != 新环境:
        问题.append("改写后 环境 与采样值不一致，拒绝写入")
        return 原文本, 问题
    return 新文本, 问题


# ═══════════════════════════════════════════════════════════════════
# 差异评估与重建
# ═══════════════════════════════════════════════════════════════════

def _新增外部工具提示(锁数据: dict[str, Any], 探针: dict[str, str]) -> list[str]:
    """外部应用/系统工具条目的版本漂移提示（只提示，不改写）。"""
    提示: list[str] = []
    映射 = {"LibreOffice soffice": "LibreOffice", "textutil": "textutil"}
    for 项 in 锁数据.get("包", []):
        if not isinstance(项, dict):
            continue
        名称 = str(项.get("名称", ""))
        探测名 = 映射.get(名称)
        if 探测名 is None:
            continue
        探测值 = 探针.get(探测名, "")
        if not 探测值:
            提示.append(f"{名称}: 未探测到（保持锁内 {项.get('版本')!r}）")
        elif 探测值 != 项.get("版本"):
            提示.append(f"{名称}: 锁内 {项.get('版本')!r} → 探针 {探测值!r}（本批不自动改写）")
    return 提示


def 评估单锁(锁路径: Path, 新环境: dict[str, str], 新生成时间: str | None,
            探针: dict[str, str], 强制刷新时间: bool = False) -> dict[str, Any]:
    """评估一份锁的重建差异（不写盘）。

    幂等口径：**只有 环境 与当前平台不一致才需要重建**（生成时间随环境一起盖章）。
    这样同一平台上重复跑本入口不会反复改字节（不会每次都脏 git 树、不会无谓重算摘要），
    换平台时必然重建——「需重建」三个字就精确等于「这份锁不是当前平台的指纹」。
    """
    根 = 系统根()
    原文本 = 锁路径.read_text(encoding="utf-8")
    原数据 = json.loads(原文本)
    原环境 = 原数据.get("环境") if isinstance(原数据.get("环境"), dict) else {}
    环境差异 = [f"{键}: {json.dumps(原环境.get(键), ensure_ascii=False)} → "
               f"{json.dumps(新环境[键], ensure_ascii=False)}"
               for 键 in 环境键顺序
               if 原环境.get(键) != 新环境.get(键)]
    时间差异 = ""
    if 新生成时间 is not None and 原数据.get("生成时间", "") != 新生成时间:
        时间差异 = (f'生成时间: {json.dumps(原数据.get("生成时间", ""), ensure_ascii=False)} '
                  f'→ "{新生成时间}"')
    需重建 = bool(环境差异) or (强制刷新时间 and bool(时间差异))
    新文本, 问题 = 计算新锁文本(原文本, 原数据, 新环境,
                             新生成时间 if 需重建 else None)
    空锁说明 = 空锁问题(锁路径)
    if 空锁说明:
        问题 = [空锁说明, *问题]
        # 空锁一律拒绝重建：重建只会给一份注定装不上的锁盖章，让它看起来更合法。
        需重建 = False
    return {
        "锁": str(锁路径.relative_to(根)),
        "提供者id": str(原数据.get("提供者id", "")),
        "原环境": 原环境,
        "新环境": dict(新环境),
        "环境差异": 环境差异,
        "时间差异": 时间差异,
        "外部工具提示": _新增外部工具提示(原数据, 探针),
        "需重建": 需重建,
        "问题": 问题,
        "新文本": 新文本,
        "旧文本": 原文本,
    }


def 刷新摘要(锁路径: Path, 旧sha: str, 新sha: str) -> tuple[list[str], list[str]]:
    """定点刷新登记了该锁的完整性摘要条目（只改这一条 sha256）。"""
    已刷新: list[str] = []
    未刷新: list[str] = []
    根 = 系统根()
    for 摘要路径 in 枚举摘要文件():
        try:
            原文本 = 摘要路径.read_text(encoding="utf-8")
            数据 = json.loads(原文本)
        except (json.JSONDecodeError, OSError):
            未刷新.append(f"{摘要路径.relative_to(根)}: 不可读")
            continue
        命中 = [条目 for 条目 in 数据.get("文件清单", [])
                if isinstance(条目, dict)
                and (摘要路径.parent / str(条目.get("路径", ""))).resolve() == 锁路径.resolve()]
        if not 命中:
            continue
        if all(条目.get("sha256") == 新sha for 条目 in 命中):
            continue
        for 条目 in 命中:
            条目["sha256"] = 新sha
        新文本 = json.dumps(数据, ensure_ascii=False, indent=2)
        if 新文本.strip() == 原文本.strip():
            未刷新.append(f"{摘要路径.relative_to(根)}: 摘要需改但重排后文本无差异（异常）")
            continue
        摘要路径.write_text(新文本, encoding="utf-8")
        已刷新.append(str(摘要路径.relative_to(根)))
    return 已刷新, 未刷新


def 依赖锁判据():
    """取**唯一判据**（`公共契约/包声明/声明.检查依赖锁内容`），本模块不另写一份。

    本入口既可直跑也可包式调用，两种模式都要取得到 —— 与 `采样环境` 同一做法
    （临时把系统根加入 sys.path）。判据只允许有一个实现（决策记录 `0033`）。
    """
    根 = 系统根()
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    from 公共契约.包声明.声明 import 检查依赖锁内容

    return 检查依赖锁内容


def 空锁问题(锁路径: Path) -> str:
    """该锁是否「空锁」（委托唯一判据）；是则返回可读说明，否则空串。

    空锁 = 包与直接依赖均为空。它在装配期被判 `依赖锁为空` 并**禁止装配提供者**
    （整包跳过），所以本入口必须**拒绝**给它盖章重建——重建只会让一份注定装不上的锁
    看起来更合法。
    """
    错误码, 错误说明 = 依赖锁判据()(锁路径.parent)
    if 错误码 != "依赖锁为空":
        return ""
    return (f"{错误码}：{错误说明}；无第三方依赖的正确表达是**不建依赖锁.json**，"
            "请删除该文件")


def 重建单锁(锁路径: Path, *, 写入: bool, 新环境: dict[str, str],
            新生成时间: str | None, 探针: dict[str, str],
            强制刷新时间: bool = False) -> dict[str, Any]:
    """重建一份锁（写入为真时落盘并刷新摘要）。"""
    import hashlib

    报告 = 评估单锁(锁路径, 新环境, 新生成时间, 探针, 强制刷新时间=强制刷新时间)
    if 报告["问题"]:
        return 报告
    if not 报告["需重建"]:
        return 报告
    if not 写入:
        return 报告
    旧sha = hashlib.sha256(报告["旧文本"].encode("utf-8")).hexdigest()
    临时路径 = 锁路径.with_name(f".{锁文件名}.重建中")
    临时路径.write_text(报告["新文本"], encoding="utf-8")
    新sha = hashlib.sha256(报告["新文本"].encode("utf-8")).hexdigest()
    临时路径.replace(锁路径)
    已刷新, 未刷新 = 刷新摘要(锁路径, 旧sha, 新sha)
    报告["旧sha256"] = 旧sha
    报告["新sha256"] = 新sha
    报告["已刷新摘要"] = 已刷新
    报告["摘要问题"] = 未刷新
    报告.pop("新文本", None)
    报告.pop("旧文本", None)
    return 报告


# ═══════════════════════════════════════════════════════════════════
# 命令行
# ═══════════════════════════════════════════════════════════════════

def _打印单锁报告(报告: dict[str, Any]) -> None:
    print(f"\n锁: {报告['锁']}   提供者id: {报告['提供者id']}")
    if 报告["问题"]:
        print("  ✗ 拒绝重建: " + "; ".join(报告["问题"]))
        return
    if not 报告["需重建"]:
        print("  = 无需重建（环境已与当前平台一致；默认幂等，不改字节）")
        if 报告["时间差异"]:
            print("  · 若只想刷新 生成时间: 加 --刷新生成时间｜本次差异 " + 报告["时间差异"])
        for 项 in 报告["外部工具提示"]:
            print("  ! 版本漂移提示 " + 项)
        return
    for 项 in 报告["环境差异"]:
        print("  · 环境 " + 项)
    if 报告["时间差异"]:
        print("  · " + 报告["时间差异"])
    if not 报告["环境差异"]:
        print("  · 环境 无差异（Python/操作系统/CPU 与当前平台一致）")
    for 项 in 报告["外部工具提示"]:
        print("  ! 版本漂移提示 " + 项)
    if "已刷新摘要" in 报告:
        print("  ✔ 已写入；摘要刷新: " + (", ".join(报告["已刷新摘要"]) or "无"))
        for 项 in 报告.get("摘要问题", []):
            print("  ✗ 摘要问题: " + 项)


def 主(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3.14 -m 开发工具.重建依赖锁",
        description="按当前平台重建依赖锁（只刷新 环境/生成时间，依赖集合原样保留）")
    parser.add_argument("--写入", action="store_true",
                        help="真实写盘（缺省为干跑：只报差异）")
    parser.add_argument("--干跑", action="store_true", help="只报差异（默认行为，显式给出更清楚）")
    parser.add_argument("--包", default="",
                        help="要重建的包：相对路径／目录名／提供者id，逗号分隔可多选")
    parser.add_argument("--全部", action="store_true",
                        help="批量重建全部锁（批量写盘必须显式给出）")
    parser.add_argument("--保留生成时间", action="store_true",
                        help="重建时不刷新 生成时间（只改 环境）")
    parser.add_argument("--刷新生成时间", action="store_true",
                        help="环境已一致时也强制刷新 生成时间（默认幂等：不写不必要字节）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于机器判读）")
    参数 = parser.parse_args(argv)

    全部锁 = 枚举依赖锁()
    新环境 = 采样环境()
    探针 = 采样外部工具版本()
    新生成时间 = None if 参数.保留生成时间 else time.strftime("%Y-%m-%d %H:%M:%S")

    未命中: list[str] = []
    if 参数.包:
        目标锁, 未命中 = 匹配目标锁(参数.包, 全部锁)
    else:
        目标锁 = list(全部锁)

    写入 = bool(参数.写入)
    if 写入 and not 参数.包 and not 参数.全部:
        print(f"{进度前缀} 拒写：批量写盘必须显式 --全部（本次未给 --包，共 {len(目标锁)} 份锁）",
              file=sys.stderr)
        return 2
    if 未命中:
        print(f"{进度前缀} 未命中: {', '.join(未命中)}", file=sys.stderr)
        if not 目标锁:
            return 2

    if not 参数.json:
        print(f"{进度前缀} 模式: {'写入' if 写入 else '干跑'}｜"
              f"当前平台环境: {json.dumps(新环境, ensure_ascii=False)}｜"
              f"目标锁 {len(目标锁)} 份（仓库内共 {len(全部锁)} 份）")

    报告表: list[dict[str, Any]] = []
    for 锁路径 in 目标锁:
        报告 = 重建单锁(锁路径, 写入=写入, 新环境=新环境,
                       新生成时间=新生成时间, 探针=探针,
                       强制刷新时间=bool(参数.刷新生成时间))
        报告表.append(报告)
        if not 参数.json:
            _打印单锁报告(报告)

    需重建 = [报告 for 报告 in 报告表 if 报告["需重建"] and not 报告["问题"]]
    有问题 = [报告 for 报告 in 报告表 if 报告["问题"]]
    环境漂移 = [报告 for 报告 in 需重建 if 报告["环境差异"]]
    仅时间 = [报告 for 报告 in 需重建 if not 报告["环境差异"]]
    if 参数.json:
        print(json.dumps({
            "模式": "写入" if 写入 else "干跑",
            "当前环境": 新环境,
            "目标锁数": len(报告表),
            "需重建": len(需重建),
            "其中环境漂移": len(环境漂移),
            "其中仅生成时间": len(仅时间),
            "已写入": len([报告 for 报告 in 报告表 if "已刷新摘要" in 报告]),
            "拒绝": len(有问题),
            "报告": [{键: 值 for 键, 值 in 报告.items() if 键 not in ("新文本", "旧文本")}
                     for 报告 in 报告表],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n{进度前缀} 汇总: 目标 {len(报告表)} 份｜需重建 {len(需重建)} 份"
              f"（环境漂移 {len(环境漂移)} 份、仅生成时间 {len(仅时间)} 份）｜"
              f"已写入 {len([报告 for 报告 in 报告表 if '已刷新摘要' in 报告])} 份｜"
              f"拒绝 {len(有问题)} 份")
        if not 写入 and 需重建:
            print(f"{进度前缀} 未写盘。确认后加 --写入（批量加 --全部）")
    return 1 if 有问题 else 0


if __name__ == "__main__":
    raise SystemExit(主())
