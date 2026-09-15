# -*- coding: utf-8 -*-
"""验证编排：技能桥接脚本（stdin JSON 进，stdout JSON 出）。

契约：技能.验证编排

把一次验证做完整（六步有序工作流）：
    ① 反馈门禁 → ② 命令白名单校验 → ③ 受控执行验证命令（底座能力做，非本脚本）
    → ④ 统一判定（退出码 / 收集错误 / 零测试 / 未解释跳过；唯一发布命令改走正式发布判定）
    → ⑤ 通过才记账 → ⑥ 唯一发布命令且通过则返回发布证据请求

边界（受控执行沙箱 AST 审计约束，缺一即 `脚本审计未通过`）：
- 只依赖标准库（json / sys / re / datetime / pathlib）与平台注入的合成模块 `技能底座能力`；
- **不自己起进程、不 shell 拼接、不 eval/exec**：验证命令的真实执行由调用方
  经底座原子能力 `系统核心支持库.进程管理.沙箱执行命令`（或 `执行命令`）完成，
  再把 退出码 / 标准输出 / 标准错误 回传给本技能做判定与记账；
- 白名单与判定口径**不在本技能维护**：改调 `支持库/后端/测试支持库` 的
  `测试支持库.验证命令白名单` 与 `测试支持库.验证结果判定`（一处口径，脚本不再照抄副本）；
  「发布状态: 通过」这一 MCP 会话约定的末行判定仍留在技能侧（能力不感知发布门禁文案）；
- **调用方必须传 `可调能力白名单`**（含 `必须授权能力` 两个能力 id）：否则脚本导入
  `技能底座能力` 会被 AST 审计拦为 `脚本审计未通过` —— fail-closed，不降级、不静默。

参数经 stdin 传入，形如 {"参数": {...}}；输出必须是单个 JSON 对象。
失败时输出 {"成功": false, "错误码": "...", "错误说明": "..."}。
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from 技能底座能力 import 调用底座能力

技能标识 = "技能.验证编排"

# ── 底座原子能力：白名单与判定的唯一口径来源（本技能只编排，不复制口径） ──
能力_验证命令白名单 = "测试支持库.验证命令白名单"
能力_验证结果判定 = "测试支持库.验证结果判定"
必须授权能力 = (能力_验证命令白名单, 能力_验证结果判定)

# ── 本技能自己用到的冻结常量（白名单三形态与判定链口径见测试支持库） ──────
唯一发布命令 = ["python3.14", "开发工具/发布门禁/运行发布门禁.py"]
默认反馈相对路径 = "开发文档/项目证据/MCP使用反馈.jsonl"
最大超时秒 = 1800

错误码_能力调用失败 = "能力调用失败"
错误码_验证失败 = "验证失败"
错误码_未反馈阻断 = "未反馈阻断"

# 与 公共契约.运行时.有界IO 的 JSONL 读取上限同口径。
JSONL读取上限字节 = 4 * 1024 * 1024
JSONL读取上限记录 = 2000

未校验_白名单 = {"成功": False, "错误码": "", "消息": "反馈门禁未通过，未进入白名单校验"}
未校验_判定 = {"成功": False, "错误码": "", "消息": "前置步骤未通过，未做统一判定"}


def _判定(成功: bool, 错误码: str, 消息: str) -> dict:
    return {"成功": 成功, "错误码": 错误码, "消息": 消息}


# ── 底座能力调用腿（经平台注入的合成模块走唯一网关，唯一通道、不降级） ──────

def 调底座能力(能力id: str, 参数: dict) -> tuple[dict, dict | None]:
    """调底座能力；返回 (值, 失败判定)。失败判定非 None 时调用方直接返回它。"""
    回执 = 调用底座能力(能力id, 参数)
    if not isinstance(回执, dict):
        return {}, _判定(False, 错误码_能力调用失败, f"{能力id} 调用回执不是对象: {回执!r}")
    if not 回执.get("成功"):
        说明 = str(回执.get("错误说明") or "").strip()
        return {}, _判定(
            False,
            str(回执.get("错误码") or 错误码_能力调用失败),
            f"{能力id} 调用失败: {说明}" if 说明 else f"{能力id} 调用失败",
        )
    值 = 回执.get("值")
    return (dict(值) if isinstance(值, dict) else {}), None


# ── ② 命令白名单校验（口径：测试支持库.验证命令白名单） ────────────────────

def 校验命令(命令: list, 工作根: Path) -> dict:
    """白名单判定：三种受控形态由底座能力判；本技能只把结果装进自己的返回形状。"""
    入参 = {
        "仓库根目录": str(工作根),
        "校验存在": True,
    }
    if isinstance(命令, list):
        入参["命令"] = [str(项) for 项 in 命令]
    值, 失败 = 调底座能力(能力_验证命令白名单, 入参)
    if 失败 is not None:
        return 失败
    return _判定(
        bool(值.get("允许")),
        str(值.get("错误码") or ""),
        str(值.get("消息") or ""),
    )


# ── ④ 统一判定（口径：测试支持库.验证结果判定） ───────────────────────────

def 判定验证结果(退出码: int, 标准输出: str, 标准错误: str = "", 命令: list | None = None) -> dict:
    """统一判定：退出码 → 收集错误 → 跳过 → 零测试/缓存假绿/导入失败当跳过，全由能力判。"""
    入参 = {
        "退出码": 退出码,
        "标准输出": 标准输出 or "",
        "标准错误": 标准错误 or "",
    }
    if isinstance(命令, list):
        入参["命令"] = [str(项) for 项 in 命令]
    值, 失败 = 调底座能力(能力_验证结果判定, 入参)
    if 失败 is not None:
        return 失败
    return _判定(
        str(值.get("判定") or "") == "通过",
        str(值.get("阻断码") or ""),
        str(值.get("理由") or ""),
    )


def 判定正式发布结果(退出码: int, 标准输出: str, 标准错误: str = "", 命令: list | None = None) -> dict:
    """唯一发布入口只有退出码为零且最后状态明确为「通过」才成功。

    首个判定链走底座能力；末行「发布状态: 通过」是 MCP 会话约定，留在技能侧判。
    """
    基础 = 判定验证结果(退出码, 标准输出, 标准错误, 命令)
    if not 基础["成功"]:
        return 基础
    文本 = f"{标准输出 or ''}\n{标准错误 or ''}"
    状态表 = re.findall(r"发布状态[:：]\s*(通过|失败|阻断)", 文本)
    状态 = 状态表[-1] if 状态表 else "未知"
    if 状态 != "通过":
        return _判定(False, 错误码_验证失败, f"发布状态不是明确通过: {状态}")
    return _判定(True, "", "正式发布结果判定通过")


# ── ① 反馈门禁 ────────────────────────────────────────────────────────

def 读取反馈记录(路径: Path) -> list:
    """按 JSONL 有界读取（尾 4MB / 最多 2000 条），返回记录列表。"""
    try:
        原始 = 路径.read_bytes()
    except OSError:
        return []
    if len(原始) > JSONL读取上限字节:
        原始 = 原始[-JSONL读取上限字节:]
        换行 = 原始.find(b"\n")
        if 换行 >= 0:
            原始 = 原始[换行 + 1:]
    记录表 = []
    for 行 in 原始.decode("utf-8", "replace").splitlines():
        行 = 行.strip()
        if not 行:
            continue
        try:
            项 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if isinstance(项, dict):
            记录表.append(项)
    return 记录表[-JSONL读取上限记录:]


def 查询反馈状态(路径: Path, 开工id: str) -> dict:
    if not 开工id:
        return {"已反馈": False, "开工id": 开工id}
    for 记录 in reversed(读取反馈记录(路径)):
        if 记录.get("开工id") == 开工id:
            return {"已反馈": True, "开工id": 开工id, "反馈": 记录}
    return {"已反馈": False, "开工id": 开工id}


def 反馈门禁(开工id: str, 反馈路径: Path) -> dict:
    状态 = 查询反馈状态(反馈路径, 开工id)
    if 状态.get("已反馈"):
        return _判定(True, "", f"反馈门禁已满足（开工id={开工id}）")
    return _判定(
        False, 错误码_未反馈阻断,
        f"开工id={开工id} 尚无 MCP 使用反馈记录，不能记录成功验证证据",
    )


# ── 参数与路径 ────────────────────────────────────────────────────────

def _文本(参数: dict, 键: str, 默认: str = "") -> str:
    值 = 参数.get(键)
    return 默认 if 值 is None else str(值).strip()


def _字典(参数: dict, 键: str) -> dict:
    值 = 参数.get(键)
    return dict(值) if isinstance(值, dict) else {}


def _绝对路径(文本: str, 项目根: Path) -> Path:
    路径 = Path(文本)
    return 路径 if 路径.is_absolute() else (项目根 / 路径)


# ── 主流程（六步编排） ────────────────────────────────────────────────

def 主流程(参数: dict) -> dict:
    名称 = _文本(参数, "名称")
    命令 = 参数.get("命令")
    退出码 = 参数.get("退出码")
    项目根文本 = _文本(参数, "项目根目录")
    开工id = _文本(参数, "开工id")
    if not 名称:
        raise ValueError("名称 必填")
    if not isinstance(命令, list) or not 命令:
        raise ValueError("命令 必填且必须是数组")
    if not isinstance(退出码, int) or isinstance(退出码, bool):
        raise ValueError("退出码 必填且必须是整数")
    if not 项目根文本:
        raise ValueError("项目根目录 必填")
    if not 开工id:
        raise ValueError("开工id 必填（不能记录无开工上下文的验证证据）")

    项目根 = Path(项目根文本).expanduser().resolve()
    if not 项目根.is_dir():
        raise ValueError(f"项目根目录不存在: {项目根}")

    标准输出 = str(参数.get("标准输出") or "")
    标准错误 = str(参数.get("标准错误") or "")
    反馈路径 = _绝对路径(_文本(参数, "反馈路径") or 默认反馈相对路径, 项目根)
    账本参数 = _文本(参数, "账本路径")
    账本路径 = _绝对路径(账本参数, 项目根) if 账本参数 else None
    超时秒数 = int(参数.get("超时秒数") or 300)
    指纹参数 = _字典(参数, "指纹参数")
    发布参数 = _字典(参数, "发布参数")
    记账时间 = _文本(参数, "记账时间") or datetime.now(timezone.utc).isoformat()

    是唯一发布命令 = list(命令) == list(唯一发布命令)
    值 = {
        "技能标识": 技能标识,
        "名称": 名称,
        "命令": [str(项) for 项 in 命令],
        "阻断": False,
        "阻断原因": "",
        "门禁": None,
        "白名单": None,
        "判定": None,
        "账本": {"已落盘": False, "路径": ""},
        "账本记录": None,
        "发布证据": {
            "需要": False,
            "唯一发布命令": 是唯一发布命令,
            "请求": None,
            "说明": "非唯一发布命令，不生成正式发布证据",
        },
    }

    # ① 反馈门禁
    值["门禁"] = 反馈门禁(开工id, 反馈路径)
    if not 值["门禁"]["成功"]:
        值["白名单"] = dict(未校验_白名单)
        值["判定"] = dict(未校验_判定)
        值["阻断"] = True
        值["阻断原因"] = f"{错误码_未反馈阻断}: {值['门禁']['消息']}"
        return 值

    # ② 白名单校验（经底座能力 测试支持库.验证命令白名单）
    值["白名单"] = 校验命令(命令, 项目根)
    if not 值["白名单"]["成功"]:
        值["判定"] = dict(未校验_判定)
        值["阻断"] = True
        值["阻断原因"] = f"{值['白名单']['错误码']}: {值['白名单']['消息']}"
        return 值

    # ④ 统一判定（经底座能力 测试支持库.验证结果判定；唯一发布命令加判发布状态末行）
    判定器 = 判定正式发布结果 if 是唯一发布命令 else 判定验证结果
    值["判定"] = 判定器(退出码, 标准输出, 标准错误, list(命令))

    # ⑤ 通过才记账
    if 值["判定"]["成功"]:
        记录 = {
            "名称": 名称,
            "命令": [str(项) for 项 in 命令],
            "退出码": 退出码,
            "开工id": 开工id,
            "时间": 记账时间,
            "提交": str(指纹参数.get("提交") or ""),
            "工作区指纹": str(指纹参数.get("工作区指纹") or ""),
            "指纹": str(指纹参数.get("指纹") or ""),
            "输出末尾": 标准输出[-2000:],
            "错误末尾": 标准错误[-1000:],
            "判定": dict(值["判定"]),
            "超时秒数": max(1, min(超时秒数, 最大超时秒)),
            "项目根目录": str(项目根),
            "记账人": 技能标识,
        }
        值["账本记录"] = 记录
        if 账本路径 is not None:
            账本路径.parent.mkdir(parents=True, exist_ok=True)
            with 账本路径.open("a", encoding="utf-8") as 文件:
                文件.write(json.dumps(记录, ensure_ascii=False) + "\n")
            值["账本"] = {"已落盘": True, "路径": str(账本路径)}
    else:
        值["阻断"] = True
        值["阻断原因"] = f"{值['判定']['错误码']}: {值['判定']['消息']}"

    # ⑥ 正式发布证据分支（写入方是底座唯一发布证据能力，技能只出请求）
    if 是唯一发布命令 and 值["判定"]["成功"]:
        提交 = str(发布参数.get("提交") or 指纹参数.get("提交") or "")
        核验工作区指纹 = str(
            发布参数.get("工作区指纹") or 指纹参数.get("工作区指纹") or ""
        )
        值["发布证据"] = {
            "需要": True,
            "唯一发布命令": True,
            "请求": {
                "提交": 提交,
                "名称": 名称,
                "退出码": 退出码,
                "指纹": 核验工作区指纹,
                "证据类型": "正式发布证据",
                "命令": [str(项) for 项 in 命令],
                "制品摘要": str(发布参数.get("制品摘要") or ""),
                "来源指纹": str(发布参数.get("来源指纹") or ""),
                "能力覆盖": list(发布参数.get("能力覆盖") or []),
                "场景覆盖": dict(发布参数.get("场景覆盖") or {}),
                "真实结果": dict(发布参数.get("真实结果") or {}),
                "状态": "通过",
                "核验工作区指纹": 核验工作区指纹,
            },
            "说明": "命令为唯一发布入口且判定通过；请由调用方交底座唯一发布证据写入方落账（需 40 位提交）",
        }
    return 值


def 主函数() -> int:
    原文 = sys.stdin.read()
    try:
        载荷 = json.loads(原文) if 原文.strip() else {}
    except json.JSONDecodeError as 错误:
        print(json.dumps({"成功": False, "错误码": "参数不合法",
                          "错误说明": f"stdin 不是合法 JSON: {错误}"}, ensure_ascii=False))
        return 0
    参数 = 载荷.get("参数") or {}
    if not isinstance(参数, dict):
        print(json.dumps({"成功": False, "错误码": "参数不合法",
                          "错误说明": "参数必须是 JSON 对象"}, ensure_ascii=False))
        return 0
    try:
        值 = 主流程(参数)
    except Exception as 错误:  # 失败要明确，不吞
        print(json.dumps({"成功": False, "错误码": "脚本执行失败",
                          "错误说明": f"{type(错误).__name__}: {错误}"}, ensure_ascii=False))
        return 0
    print(json.dumps({"成功": True, "值": 值}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
