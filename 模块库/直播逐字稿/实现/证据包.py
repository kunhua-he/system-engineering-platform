"""逐字稿证据包：把底稿行、多轮复核结果与死循环区间拼成 Markdown 证据文本。

纯字符串处理：不调用任何能力、不读写磁盘、不依赖模型或第三方库。
输出结构固定，时间统一 mm:ss.s（如 00:10.2、12:05.0）：
    # 逐段复核证据包 / ## 已确认术语 / ## 第1区间 00:10.2-00:14.8
    ### 原始底稿 / ### 第1轮识别 / ### 第2轮识别 ... / ## 死循环区间
输入缺项或非法时降级为「（无）」或按时间取不到就整批返回，绝不抛异常。
"""

from __future__ import annotations

import re

术语分隔 = re.compile(r"[、,，;；/|\s]+")
时间块 = re.compile(r"^\s*\[([^\]]*)\]")
时间项 = re.compile(r"(\d{1,3}):(\d{1,2})(?:[.．](\d))?")
时间分隔 = re.compile(r"[-—–~至到]")


def 格式化时间(秒) -> str:
    """秒 → mm:ss.s；取不到数值按 0，负数按 0，超过 60 分钟累加分钟位。"""
    try:
        数值 = float(秒)
    except (TypeError, ValueError):
        return "00:00.0"
    if 数值 != 数值 or 数值 < 0:  # NaN 与负数
        return "00:00.0"
    分, 余 = divmod(int(round(数值 * 10)), 600)
    return f"{分:02d}:{余 / 10:04.1f}"


def _解析时间项(文本) -> float | None:
    """解析 mm:ss(.s) 或纯秒；解析不到返回 None。"""
    if not isinstance(文本, str):
        return None
    文本 = 文本.strip()
    匹配 = 时间项.fullmatch(文本)
    if 匹配:
        分, 秒, 十分之一 = 匹配.groups()
        return int(分) * 60 + int(秒) + (int(十分之一) / 10 if 十分之一 else 0.0)
    try:
        return float(文本)
    except ValueError:
        return None


def 解析行时间(行) -> tuple[float, float] | None:
    """取行首 [开始-结束] 时间段；无时间戳或不可解析返回 None。"""
    if not isinstance(行, str):
        return None
    匹配 = 时间块.match(行)
    if not 匹配:
        return None
    片段 = [段 for 段 in 时间分隔.split(匹配.group(1)) if 段.strip()]
    if not 片段:
        return None
    开始 = _解析时间项(片段[0])
    结束 = _解析时间项(片段[1]) if len(片段) > 1 else 开始
    开始 = 结束 if 开始 is None else 开始
    结束 = 开始 if 结束 is None else 结束
    if 开始 is None:
        return None
    return (min(开始, 结束), max(开始, 结束))


def 底稿行匹配区间(底稿行, 开始秒, 结束秒) -> list[str]:
    """挑出与区间时间重叠的底稿行；所有行都无时间戳时整批返回。"""
    行列表 = [行 for 行 in 底稿行 if isinstance(行, str)] if isinstance(底稿行, list) else []
    带时间 = [(解析行时间(行), 行) for 行 in 行列表]
    带时间 = [(时间, 行) for 时间, 行 in 带时间 if 时间 is not None]
    if not 带时间:
        return [行.rstrip() for 行 in 行列表 if 行.strip()]
    开始, 结束 = float(开始秒 or 0), float(结束秒 or 0)
    return [行.rstrip() for (首, 尾), 行 in 带时间 if 首 <= 结束 and 尾 >= 开始 and 行.strip()]


def 拆分术语(附加术语) -> list[str]:
    """附加术语按常见分隔符逐条拆开；非文本或空串返回空列表。"""
    if not isinstance(附加术语, str):
        return []
    return [项 for 项 in 术语分隔.split(附加术语.strip()) if 项]


def _取整数(值, 默认: int) -> int:
    if isinstance(值, bool):
        return 默认
    if isinstance(值, int):
        return 值
    try:
        return int(str(值).strip())
    except (TypeError, ValueError):
        return 默认


def _取时间(区间: dict, 键: str) -> float:
    值 = 区间.get(键)
    return 值 if 值 is not None else (区间.get("开始秒") or 0)


def _渲染区间(行: list[str], 区间: dict, 序号: int, 全部底稿行) -> None:
    """渲染一个区间：标题 + 原始底稿 + 逐轮识别。"""
    开始, 结束 = _取时间(区间, "开始秒") or 0, _取时间(区间, "结束秒")
    编号 = _取整数(区间.get("区间id"), 序号)
    行.extend(["", f"## 第{编号}区间 {格式化时间(开始)}-{格式化时间(结束)}", "", "### 原始底稿"])
    # 区间自带底稿行优先；否则用总底稿行按区间时间重叠过滤。
    来源底稿 = 区间.get("底稿行") or 全部底稿行
    底稿 = 底稿行匹配区间(来源底稿, 开始, 结束)
    行.extend([f"- {条目}" for 条目 in 底稿] or ["（无匹配底稿行）"])

    轮次 = 区间.get("轮次")
    轮次 = [项 for 项 in 轮次 if isinstance(项, dict)] if isinstance(轮次, list) else []
    if not 轮次:
        行.extend(["", "### 识别轮次", "（无）"])
        return
    for 轮序号, 轮 in enumerate(轮次, 1):
        文本 = 轮.get("文本")
        行.extend(["", f"### 第{_取整数(轮.get('轮'), 轮序号)}轮识别",
                   文本.strip() if isinstance(文本, str) and 文本.strip() else "（无）"])


def _渲染死循环(行: list[str], 死循环区间) -> None:
    """死循环区间每段一行：时间段 + 重复次数 + 样例文本。"""
    行.extend(["", "## 死循环区间"])
    段列表 = [段 for 段 in 死循环区间 if isinstance(段, dict)] if isinstance(死循环区间, list) else []
    if not 段列表:
        行.append("（无）")
        return
    for 段 in 段列表:
        样例 = 段.get("样例文本")
        样例 = 样例.strip() if isinstance(样例, str) and 样例.strip() else "（无）"
        行.append(f"- {格式化时间(_取时间(段, '开始秒') or 0)}-{格式化时间(_取时间(段, '结束秒'))}"
                 f" 重复 {_取整数(段.get('重复次数'), 0)} 次 样例：{样例}")


def 生成证据包(底稿行: list[str], 复核列表: list[dict], 死循环区间: list[dict],
               附加术语: str) -> str:
    """拼装 Markdown 证据包文本（纯字符串，不调能力、不写盘）。"""
    行: list[str] = ["# 逐段复核证据包", "", "## 已确认术语"]
    术语列表 = 拆分术语(附加术语)
    行.extend([f"- {术语}" for 术语 in 术语列表] or ["（无）"])
    区间列表 = [项 for 项 in 复核列表 if isinstance(项, dict)] if isinstance(复核列表, list) else []
    for 序号, 区间 in enumerate(区间列表, 1):
        _渲染区间(行, 区间, 序号, 底稿行)
    _渲染死循环(行, 死循环区间)
    return "\n".join(行) + "\n"
