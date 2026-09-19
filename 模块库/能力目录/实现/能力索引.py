"""能力索引：只读构建全部公开能力记录，不加载任何能力实现。

数据源全部是被检索方的公开只读声明文件：
包声明.json / 能力契约/参数契约.json / 能力定义.json / 权限契约/权限契约.json /
资源预算.json / 能力数据/能力搜索数据.json / 验证场景引用.json /
开发文档/项目证据/验证历史.jsonl。

边界（与旧两道能力检索实现同口径）：支持库.适配层.* 是内部实现边界，
包声明 内部层=true 的支持库同样不对外暴露。本模块只用标准库，
不 import 支持库/提供者/第三方/开发工具，也不 import 任何能力实现。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假

排除包前缀 = ("支持库.适配层.",)
数据根目录名 = ("支持库", "模块库")
未约束类型 = "未约束"
暂无验证 = "暂无成功验证记录"
搜索字段表 = (
    "能力id", "中文名", "说明", "参数类型", "必填", "默认值", "返回结构",
    "错误码", "调用示例", "权限", "资源预算", "依赖", "版本", "最近成功验证",
)


def 定位数据根(项目根: Path) -> list[Path]:
    """支持库/模块库 两个正式包根；缺失的根如实剔除。"""
    return [项目根 / 名称 for 名称 in 数据根目录名 if (项目根 / 名称).is_dir()]


def 读取JSON(路径: Path) -> Any:
    """只读解析 JSON；文件缺失或非法返回 None（由调用方计入扫描问题）。"""
    if not 路径.is_file():
        return None
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def 按能力id索引(数据: Any) -> dict[str, dict]:
    """把 能力契约/能力列表/能力 数组按 能力id 建索引（缺键不伪造）。"""
    表: dict[str, dict] = {}
    if not isinstance(数据, dict):
        return 表
    for 键 in ("能力契约", "能力列表", "能力"):
        条目表 = 数据.get(键)
        if not isinstance(条目表, list):
            continue
        for 条目 in 条目表:
            if isinstance(条目, dict) and 条目.get("能力id"):
                表[str(条目["能力id"])] = 条目
    return 表


def 搜索数据索引(数据: Any) -> dict[str, dict]:
    """能力数据/能力搜索数据.json（数组）按 能力id 建索引。"""
    表: dict[str, dict] = {}
    if isinstance(数据, list):
        for 条目 in 数据:
            if isinstance(条目, dict) and 条目.get("能力id"):
                表[str(条目["能力id"])] = 条目
    return 表


def 扫描包目录(项目根: Path) -> list[Path]:
    """全部正式包目录（含 包声明.json）；包根内的缓存与字节码目录不参与检索。

    排除判据必须**相对被扫描的根**判断（2026-09-15 实测修复）：原来是
    `if "工程缓存" in 声明路径.parts: continue`（绝对路径逐段），而制品整个
    目录就落在 `<项目根>/工程缓存/制品仓库/…` 之下，于是**制品运行时会把自己
    的全部包都排除掉**，索引恒为空、两个能力恒报
    `内部错误：能力索引为空：包声明可读但未解析到任何公开能力`（HTML 黑盒 4 步全红）。
    改成相对路径判断后：制品内照常检索；包根内部确实存在的缓存目录仍被排除。
    """
    包目录表: list[Path] = []
    for 根 in 定位数据根(项目根):
        for 声明路径 in 根.rglob("包声明.json"):
            try:
                相对 = 声明路径.relative_to(根)
            except ValueError:
                相对 = 声明路径
            if "工程缓存" in 相对.parts or "__pycache__" in 相对.parts:
                continue
            包目录表.append(声明路径.parent)
    return sorted(包目录表, key=lambda 路径: 路径.as_posix())


def 是否可发现包(声明: dict) -> bool:
    """本包的能力该不该进发现面（搜索/说明书）。

    **2026-09-20 改判（华哥口述「现在就是不枚举，你都搜不到」）**：原口径是
    「适配层 + `内部层=true` 一律不对外暴露」，实测后果是**内部层 16 包 68 条能力
    「可调但搜不到」**——经网关/调用全部返回「缺少必填参数…」（＝已注册），
    经 能力目录.搜索能力 全部 0 命中（`/健康` 报 713，搜索空关键词只回 470）。
    Agent 有 id 才调得动，而 id 只能靠 `rg` 枚举源码挖 ⇒ 违反「Agent 只记两个动作：
    搜索能力 → 调用能力」。**能调得动的能力必须在发现面可见**，是否内用由调用方按
    `内部层` 标记自行取舍（原判「数差＝口径自洽」是错的，已在债务清单改判为真缺陷）。

    仍排除 `支持库.适配层.*`：那是**同一实现的第二条腿**（如 适配层 的
    `图像解码.解码图像` 与内部层 的 `图像处理支持库.图像解码.解码图像` 指向同一实现），
    放进来会让同一能力出两条重复记录（违反 1.2 不保留旧腿）。
    """
    包id = str(声明.get("包id", ""))
    if not 包id or 包id.startswith(排除包前缀):
        return 假
    return 真


def 是否内部层包(声明: dict) -> bool:
    """该包是否 `内部层=true`（进发现面，但标注「内部层」供调用方取舍）。"""
    return bool(声明.get("内部层", 假))


def 读取包数据(包目录: Path) -> dict[str, Any]:
    """按包目录聚合只读声明（每类一份，读不到即 None，不伪造）。"""
    return {
        "包声明": 读取JSON(包目录 / "包声明.json"),
        "参数契约": 按能力id索引(读取JSON(包目录 / "能力契约" / "参数契约.json")),
        "能力定义": 按能力id索引(读取JSON(包目录 / "能力定义.json")),
        "搜索数据": 搜索数据索引(读取JSON(包目录 / "能力数据" / "能力搜索数据.json")),
        "权限契约": 读取JSON(包目录 / "权限契约" / "权限契约.json"),
        "资源预算": 读取JSON(包目录 / "资源预算.json"),
        "有验证场景": (包目录 / "验证场景引用.json").is_file(),
    }


def 读取验证历史(项目根: Path) -> list[dict]:
    """开发文档/项目证据/验证历史.jsonl 中退出码为 0 的成功记录。"""
    路径 = 项目根 / "开发文档" / "项目证据" / "验证历史.jsonl"
    if not 路径.is_file():
        return []
    try:
        文本 = 路径.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    记录表: list[dict] = []
    for 行 in 文本.splitlines():
        if not 行.strip():
            continue
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if isinstance(记录, dict) and 记录.get("退出码") == 0:
            记录表.append(记录)
    return 记录表


def 匹配令牌(包id: str, 能力id: str, *, 含包名: bool = 真) -> list[str]:
    """验证历史匹配令牌：包id / 包中文名 / 能力id。

    记录里从不出现点号包id，故按包末段并查；`含包名=False` 用于「最近成功验证」
    这类**断言型**字段——包末段子串会命中同名或同词的其他工作包记录
    （实测：包末段「能力目录」命中 2026-08-24「渐进能力目录与统一网关工作包验证」），
    断言型字段必须收紧到 包id/能力id 精确令牌，宁缺勿假。
    """
    令牌表 = [包id, 能力id] + ([包id.rsplit(".", 1)[-1]] if 含包名 else [])
    return [令牌 for 令牌 in 令牌表 if 令牌]


def 最近成功验证(记录表: list[dict], 包id: str, 能力id: str) -> str:
    """最近一次成功验证的时间（只认 包id/能力id 精确令牌；无记录如实返回暂无）。"""
    最近 = ""
    令牌表 = 匹配令牌(包id, 能力id, 含包名=假)
    for 记录 in 记录表:
        文本 = json.dumps(记录, ensure_ascii=False)
        if not any(令牌 in 文本 for 令牌 in 令牌表):
            continue
        时间 = str(记录.get("时间", ""))
        if 时间 > 最近:
            最近 = 时间
    return 最近 or 暂无验证


def 验证状态(记录表: list[dict], 包id: str, 能力id: str, 有验证场景: bool) -> str:
    """验证状态文本：场景引用 + 成功记录命中情况（写明命中的令牌，不冒充强绑定）。"""
    段 = ["有验证场景引用" if 有验证场景 else "无验证场景引用"]
    令牌表 = 匹配令牌(包id, 能力id)
    命中令牌 = ""
    命中文案 = ""
    for 记录 in 记录表:
        文本 = json.dumps(记录, ensure_ascii=False)
        命中 = next((令牌 for 令牌 in 令牌表 if 令牌 in 文本), "")
        if 命中:
            命中令牌 = 命中
            命中文案 = str(记录.get("名称", "")).strip()
            break
    if 命中令牌:
        段.append(f"有验证成功记录（按「{命中令牌}」匹配：{命中文案 or '未记名称'}）")
    else:
        段.append("无验证成功记录")
    return "；".join(段)


def 转换参数表(来源列表: list[Any]) -> list[dict]:
    """参数统一为 {名称,类型,必填,默认值,说明}；类型 任意 归一为 未约束。"""
    参数表: list[dict] = []
    for 来源 in 来源列表:
        if not isinstance(来源, list):
            continue
        for 参数 in 来源:
            if not isinstance(参数, dict) or not 参数.get("名称"):
                continue
            类型 = str(参数.get("类型", ""))
            参数表.append({
                "名称": str(参数["名称"]),
                "类型": 未约束类型 if 类型 == "任意" else 类型,
                "必填": bool(参数.get("必填", 真)),
                "默认值": 参数.get("默认值"),
                "说明": str(参数.get("说明", "")),
            })
        if 参数表:
            return 参数表
    return 参数表


def 调用示例文本(示例: Any, 能力id: str, 参数表: list[dict]) -> str:
    """调用示例 → 文本；无示例时按默认值拼装（可执行，不出现“无调用示例”）。"""
    if isinstance(示例, dict):
        目标id = str(示例.get("能力id") or 能力id)
        参数 = 示例.get("参数")
        参数 = 参数 if isinstance(参数, dict) else {}
        行 = ", ".join(f"{名称}={值}" for 名称, 值 in 参数.items())
        return f"{目标id}({行})" if 行 else f"{目标id}()"
    if isinstance(示例, str) and 示例:
        return 示例
    行 = ", ".join(f"{参数['名称']}={参数.get('默认值', '值')}" for 参数 in 参数表[:3])
    return f"{能力id}({行})" if 行 else f"{能力id}()"


def 读取权限(权限契约: Any, 能力id: str) -> str:
    """权限：权限契约.json[能力id].允许用户；无声明 → 公开。"""
    条目 = 权限契约.get(能力id) if isinstance(权限契约, dict) else None
    允许用户 = 条目.get("允许用户") if isinstance(条目, dict) else None
    if isinstance(允许用户, list) and 允许用户:
        return "允许用户: " + ", ".join(str(项) for 项 in 允许用户)
    return "公开"


def 资源预算说明(契约条目: dict, 参数表: list[dict]) -> str:
    """资源预算口径：行为.输入上限 或 参数 资源预算 默认值；都没有 → 默认。"""
    行为 = 契约条目.get("行为")
    输入上限 = 行为.get("输入上限") if isinstance(行为, dict) else ""
    if 输入上限:
        return str(输入上限)
    for 参数 in 参数表:
        if 参数["名称"] == "资源预算" and 参数.get("默认值") is not None:
            return str(参数["默认值"])
    return "默认"


def 格式化能力记录(包数据: dict, 能力声明: dict, 记录表: list[dict]) -> dict:
    """一条搜索/读取结果：14 字段全覆盖，并保留旧两道检索实现读取过的键名。

    字段来源优先级：参数契约（唯一聚合契约）→ 能力定义 → 包声明能力条目 → 搜索数据。
    同名不同口径的键同时保留（如 中文名/中文名称、参数/参数名），便于调用方平滑迁移。
    """
    声明 = 包数据["包声明"] if isinstance(包数据["包声明"], dict) else {}
    包id = str(声明.get("包id", ""))
    包版本 = str(声明.get("版本", ""))
    能力id = str(能力声明.get("能力id", ""))
    契约条目 = 包数据["参数契约"].get(能力id, {})
    定义条目 = 包数据["能力定义"].get(能力id, {})
    搜索条目 = 包数据["搜索数据"].get(能力id, {})
    名称 = str(定义条目.get("中文名称") or 能力声明.get("名称") or 搜索条目.get("名称")
              or 能力id.rsplit(".", 1)[-1])
    说明 = str(契约条目.get("说明") or 定义条目.get("说明") or 能力声明.get("说明")
              or 搜索条目.get("说明") or "")
    参数表 = 转换参数表([契约条目.get("参数"), 定义条目.get("参数"),
                     能力声明.get("参数"), 搜索条目.get("参数")])
    必填参数 = [参数 for 参数 in 参数表 if 参数["必填"]]
    可选参数 = [参数 for 参数 in 参数表 if not 参数["必填"]]
    返回结构 = (契约条目.get("返回") or 定义条目.get("返回") or 能力声明.get("返回")
              or 搜索条目.get("返回") or "")
    错误码 = 契约条目.get("错误码") or 定义条目.get("错误码") or 搜索条目.get("错误码") or []
    版本 = str(定义条目.get("版本") or 契约条目.get("版本") or 搜索条目.get("版本") or 包版本)
    提供者 = 定义条目.get("提供者")
    提供者 = str(提供者.get("默认")) if isinstance(提供者, dict) and 提供者.get("默认") else 包id
    记录 = {
        "能力id": 能力id,
        "名称": 名称,
        "中文名": 名称,
        "中文名称": 名称,
        "一句话说明": 说明,
        "说明": 说明,
        "包id": 包id,
        "包名称": str(声明.get("名称", "")),
        "提供方": 包id,
        "提供者": 提供者,
        "类型": str(声明.get("类型", "")),
        "版本": 版本,
        "包版本": 包版本,
        "参数": 参数表,
        "参数类型": 参数表,
        "参数列表": 参数表,
        "参数名": [参数["名称"] for 参数 in 参数表],
        "必填": [参数["名称"] for 参数 in 必填参数],
        "必填参数": 必填参数,
        "可选参数": 可选参数,
        "默认值": {参数["名称"]: 参数["默认值"] for 参数 in 参数表
                 if 参数.get("默认值") is not None},
        "返回": 返回结构,
        "返回结构": 返回结构,
        "错误码": 错误码,
        # 冻结口径（沿用旧两道检索实现 + 覆盖率测试）：契约没写 调用示例 就**如实标"无"**，
        # 不按默认值合成一个假示例（合成值会让调用方以为存在官方示例）。
        "调用示例": 契约条目.get("调用示例") or "无",
        "调用示例文本": 调用示例文本(契约条目.get("调用示例"), 能力id, 参数表),
        "权限": 读取权限(包数据["权限契约"], 能力id),
        "资源预算": 资源预算说明(契约条目, 参数表),
        "资源预算声明": 包数据["资源预算"] if isinstance(包数据["资源预算"], dict) else {},
        "依赖": 声明.get("依赖") or [],
        "依赖能力": 声明.get("依赖") or [],
        "最近成功验证": 最近成功验证(记录表, 包id, 能力id),
        "验证状态": 验证状态(记录表, 包id, 能力id, bool(包数据["有验证场景"])),
        "行为": 定义条目.get("行为") or {},
    }
    return 记录


_索引缓存: dict[str, tuple[float, tuple, list[dict], list[str]]] = {}


def 索引缓存有效期() -> float:
    """缓存有效期（秒）：`系统底座_能力索引缓存秒` 可覆盖，`0` 关闭缓存。"""
    原文 = os.environ.get("系统底座_能力索引缓存秒", "").strip()
    if not 原文:
        return 300.0
    try:
        值 = float(原文)
    except ValueError:
        return 300.0
    return 0.0 if 值 <= 0 else 值


def 索引缓存指纹(项目根: Path) -> tuple:
    """缓存指纹：只 stat，不解析 —— 包声明/能力定义/参数契约 的 路径+大小+mtime。

    任何一条被改、增加或删除都会改变指纹，从而强制重建索引；
    缓存只省「重复解析」，不承担「数据可能已变」的风险。
    """
    条目: list[tuple[str, int, int]] = []
    for 目录 in 扫描包目录(项目根):
        for 名字 in ("包声明.json", "能力定义.json"):
            文件 = 目录 / 名字
            try:
                状态 = 文件.stat()
            except OSError:
                continue
            条目.append((文件.as_posix(), 状态.st_size, 状态.st_mtime_ns))
        契约目录 = 目录 / "能力契约"
        if 契约目录.is_dir():
            for 文件 in sorted(契约目录.glob("*.json")):
                try:
                    状态 = 文件.stat()
                except OSError:
                    continue
                条目.append((文件.as_posix(), 状态.st_size, 状态.st_mtime_ns))
    return tuple(条目)


def 构建能力索引(项目根: Path) -> tuple[list[dict], list[str]]:
    """带指纹缓存的索引入口（对外唯一口径）。

    性能口径（2026-09-15 实测）：原本每次调用都全量重建（单次 **1.39 秒**，
    一轮用例数百次调用累计到 **166 秒**）。改为「stat 指纹 + TTL」缓存后：
    指纹一致且未过期 → 直接复用；指纹一变 → 必然重建。缓存只省重复解析。
    """
    键 = str(项目根)
    有效期 = 索引缓存有效期()
    if 有效期 <= 0:
        return _构建能力索引原始(项目根)
    现在 = time.monotonic()
    已有 = _索引缓存.get(键)
    指纹 = 索引缓存指纹(项目根)
    if 已有 is not None and 已有[1] == 指纹 and (现在 - 已有[0]) < 有效期:
        return 已有[2], 已有[3]
    记录, 问题 = _构建能力索引原始(项目根)
    _索引缓存[键] = (现在, 指纹, 记录, 问题)
    return 记录, 问题


def _构建能力索引原始(项目根: Path) -> tuple[list[dict], list[str]]:
    """构建全部公开能力记录（按 能力id、包id 排序）+ 扫描问题列表。

    去重口径：同一 能力id 同时出现在聚合父包与子包声明时，保留带 能力定义.json 的
    那一份（全仓实测 166 处重复全部是「父包聚合视图 vs 子包正式定义」）。
    """
    索引: dict[str, tuple[bool, dict]] = {}
    问题列表: list[str] = []
    验证记录 = 读取验证历史(项目根)
    for 包目录 in 扫描包目录(项目根):
        包数据 = 读取包数据(包目录)
        声明 = 包数据["包声明"]
        if not isinstance(声明, dict):
            问题列表.append(f"{包目录.as_posix()} 的 包声明.json 不可读或非法")
            continue
        if not 是否可发现包(声明):
            continue
        有定义 = bool(包数据["能力定义"])
        是内部层 = 是否内部层包(声明)
        for 能力声明 in 声明.get("能力") or []:
            if not isinstance(能力声明, dict) or not 能力声明.get("能力id"):
                问题列表.append(
                    f"{包目录.as_posix()} 的能力条目缺少 能力id，已跳过")
                continue
            能力id = str(能力声明["能力id"])
            记录 = 格式化能力记录(包数据, 能力声明, 验证记录)
            # 内部层能力进发现面（能调得动就必须可见），但**标注**内部层供调用方取舍。
            记录["内部层"] = 是内部层
            已有 = 索引.get(能力id)
            if 已有 is None or (有定义 and not 已有[0]):
                索引[能力id] = (有定义, 记录)
    记录表 = [项[1] for 项 in 索引.values()]
    记录表.sort(key=lambda 记录: (记录["能力id"], 记录["包id"]))
    return 记录表, 问题列表
