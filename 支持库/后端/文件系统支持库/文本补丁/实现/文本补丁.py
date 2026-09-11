"""文本补丁原子能力：精确文本替换的唯一匹配定位与差异预览。

迁移自 V3 快速修复内核，保持三条硬约束：
① SHA256 防漂移（预期旧文本摘要、预期文件摘要不一致即失败）；
② 行窗口限定（起始行/结束行必须成对给，且不得越界）；
③ 唯一匹配强校验（0 处失败、多处失败并回传候选行区间）。

本模块只做「定位与替换」，不参与业务账本、权限或工作区治理。
"""

from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

最大候选数 = 20
来源标记 = "文本补丁"


def 计算文本摘要(文本: str) -> str:
    """返回文本的 SHA256 十六进制摘要。"""
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()


def _行区间表(文本: str) -> list[tuple[int, int]]:
    """每行的 (起始偏移, 结束偏移)，保留行尾换行。"""
    行列表 = 文本.splitlines(keepends=True)
    if not 行列表:
        return [(0, 0)]
    区间表: list[tuple[int, int]] = []
    偏移 = 0
    for 行 in 行列表:
        下一偏移 = 偏移 + len(行)
        区间表.append((偏移, 下一偏移))
        偏移 = 下一偏移
    return 区间表


def _全部出现位置(文本: str, 目标: str) -> list[tuple[int, int]]:
    """目标字符串在文本中的全部出现位置（不重叠）。"""
    位置列表: list[tuple[int, int]] = []
    起点 = 0
    while True:
        索引 = 文本.find(目标, 起点)
        if 索引 < 0:
            break
        位置列表.append((索引, 索引 + len(目标)))
        起点 = 索引 + max(1, len(目标))
    return 位置列表


def _偏移对应行号(文本: str, 偏移: int) -> int:
    if 偏移 <= 0:
        return 1
    return 文本.count("\n", 0, 偏移) + 1


def _转换行号(值: Any, 名称: str) -> int:
    if isinstance(值, bool) or not isinstance(值, (int, float)):
        raise ValueError(f"{名称}必须是整数")
    if isinstance(值, float) and not 值.is_integer():
        raise ValueError(f"{名称}必须是整数")
    return int(值)


def _标准化行窗口(区间表: list[tuple[int, int]], 起始行: Any, 结束行: Any):
    if 起始行 is None and 结束行 is None:
        return None
    if 起始行 is None or 结束行 is None:
        raise ValueError("起始行与结束行必须同时提供")
    起始 = _转换行号(起始行, "起始行")
    结束 = _转换行号(结束行, "结束行")
    if 起始 < 1 or 结束 < 起始:
        raise ValueError("行范围不合法")
    if 结束 > len(区间表):
        raise ValueError(f"行范围超出文件长度（共 {len(区间表)} 行）")
    return 区间表[起始 - 1][0], 区间表[结束 - 1][1]


def _定位唯一匹配(文本: str, 旧文本: str, 起始行: Any = None, 结束行: Any = None,
                  预期旧文本摘要: str = "") -> dict[str, Any]:
    """定位唯一匹配；失败时抛 ValueError（消息即中文原因）。"""
    if not isinstance(旧文本, str) or not 旧文本:
        raise ValueError("旧文本不能为空")

    旧摘要 = 计算文本摘要(旧文本)
    预期 = (预期旧文本摘要 or "").strip().lower()
    if 预期 and 预期 != 旧摘要:
        raise ValueError(f"旧文本摘要不符：预期 {预期}，实际 {旧摘要}")

    区间表 = _行区间表(文本)
    行窗口 = _标准化行窗口(区间表, 起始行, 结束行)
    位置列表 = _全部出现位置(文本, 旧文本)
    if 行窗口:
        范围起, 范围止 = 行窗口
        位置列表 = [项 for 项 in 位置列表 if 项[0] >= 范围起 and 项[1] <= 范围止]

    if not 位置列表:
        详情 = {"匹配数": 0, "旧文本摘要": 旧摘要}
        if 行窗口:
            详情["选中文本摘要"] = 计算文本摘要(文本[行窗口[0]:行窗口[1]])
            详情["选中文本预览"] = 文本[行窗口[0]:行窗口[1]][:500]
        raise ValueError("未找到匹配：" + repr(详情))

    if len(位置列表) > 1:
        候选 = [
            {"起始行": _偏移对应行号(文本, 起), "结束行": _偏移对应行号(文本, max(起, 止 - 1))}
            for 起, 止 in 位置列表[:最大候选数]
        ]
        raise ValueError("匹配不唯一，请提供起始行/结束行：" +
                         repr({"匹配数": len(位置列表), "候选": 候选}))

    起点, 终点 = 位置列表[0]
    return {
        "起始偏移": 起点,
        "结束偏移": 终点,
        "起始行": _偏移对应行号(文本, 起点),
        "结束行": _偏移对应行号(文本, max(起点, 终点 - 1)),
        "旧文本摘要": 旧摘要,
        "匹配数": 1,
    }


def _归类错误(原因: str) -> str:
    """把内部 ValueError 的中文原因归类为统一错误码。"""
    if 原因.startswith("匹配不唯一"):
        return "匹配不唯一"
    if 原因.startswith("未找到匹配"):
        return "未找到匹配"
    if "摘要不符" in 原因:
        return "摘要不符"
    if 原因.startswith("行范围") or 原因.startswith("起始行") or 原因.startswith("结束行") \
            or "行范围" in 原因 or "必须是整数" in 原因:
        return "行范围非法"
    return "参数不合法"


def 查找唯一匹配(文本: str, 旧文本: str, 起始行: Any = None, 结束行: Any = None,
                预期旧文本摘要: str = "") -> 结果:
    """在文本中定位旧文本的唯一位置（只读，不写文件）。

    返回 {起始偏移, 结束偏移, 起始行, 结束行, 旧文本摘要, 匹配数}。
    未找到、不唯一、摘要不符、行范围非法均返回失败并带中文原因。
    """
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是字符串", 来源=来源标记)
    if not isinstance(旧文本, str) or not 旧文本:
        return 结果.失败("参数不合法", "旧文本不能为空", 来源=来源标记)
    try:
        定位 = _定位唯一匹配(文本, 旧文本, 起始行, 结束行, 预期旧文本摘要)
    except ValueError as 错误:
        原因 = str(错误)
        return 结果.失败(_归类错误(原因), 原因, 来源=来源标记)
    return 结果.成功结果(定位)


def 应用精确替换(
    文件路径: str,
    旧文本: str,
    新文本: str,
    根目录: str = "",
    起始行: Any = None,
    结束行: Any = None,
    预期旧文本摘要: str = "",
    预期文件摘要: str = "",
    写入: bool = True,
) -> 结果:
    """读取文件 → 唯一匹配校验 → 生成新文本 →（可选）原子写入。

    写入=False 时只做差异预览（不落盘）。返回
    {文件路径, 相对路径, 已写入, 起始行, 结束行, 旧文本摘要,
     旧文件摘要, 新文件摘要, 差异, 差异行数, 新增行数, 删除行数}。
    """
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须是非空字符串", 来源=来源标记)
    if not isinstance(旧文本, str) or not 旧文本:
        return 结果.失败("参数不合法", "旧文本不能为空", 来源=来源标记)
    if not isinstance(新文本, str):
        return 结果.失败("参数不合法", "新文本必须是字符串", 来源=来源标记)
    if not isinstance(写入, bool):
        return 结果.失败("参数不合法", "写入必须是逻辑型", 来源=来源标记)

    目标 = Path(文件路径).expanduser()
    if not 目标.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {目标}", 来源=来源标记)

    try:
        原文本 = 目标.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        return 结果.失败("读取失败", f"无法按 UTF-8 读取文件: {错误}", 来源=来源标记)

    旧文件摘要 = 计算文本摘要(原文本)
    预期文件 = (预期文件摘要 or "").strip().lower()
    if 预期文件 and 预期文件 != 旧文件摘要:
        return 结果.失败(
            "文件摘要不符",
            f"文件已被改动：预期 {预期文件}，实际 {旧文件摘要}",
            来源=来源标记,
            详情={"当前文件摘要": 旧文件摘要},
        )

    try:
        定位 = _定位唯一匹配(原文本, 旧文本, 起始行, 结束行, 预期旧文本摘要)
    except ValueError as 错误:
        原因 = str(错误)
        return 结果.失败(_归类错误(原因), 原因, 来源=来源标记)

    新文本内容 = 原文本[:定位["起始偏移"]] + 新文本 + 原文本[定位["结束偏移"]:]
    新文件摘要 = 计算文本摘要(新文本内容)

    if isinstance(根目录, str) and 根目录.strip():
        基准 = Path(根目录).expanduser().resolve()
    else:
        基准 = 目标.resolve().parent
    try:
        相对路径 = str(目标.resolve().relative_to(基准))
    except ValueError:
        相对路径 = 目标.name

    差异行列表 = list(difflib.unified_diff(
        原文本.splitlines(keepends=True),
        新文本内容.splitlines(keepends=True),
        fromfile=f"a/{相对路径}",
        tofile=f"b/{相对路径}",
    ))
    新增行数 = sum(1 for 行 in 差异行列表[2:] if 行.startswith("+"))
    删除行数 = sum(1 for 行 in 差异行列表[2:] if 行.startswith("-"))

    已写入 = False
    if 写入:
        目录 = 目标.parent
        try:
            句柄 = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(目录), delete=False,
                prefix=".__补丁_", suffix=".tmp")
            try:
                句柄.write(新文本内容)
                句柄.flush()
                os.fsync(句柄.fileno())
            finally:
                句柄.close()
            os.replace(句柄.name, 目标)
            已写入 = True
        except OSError as 错误:
            try:
                os.unlink(句柄.name)  # type: ignore[possibly-undefined]
            except (OSError, UnboundLocalError):
                pass
            return 结果.失败("写入失败", f"原子写入失败: {错误}", 来源=来源标记)

    return 结果.成功结果({
        "文件路径": str(目标),
        "相对路径": 相对路径,
        "已写入": 已写入,
        "起始偏移": 定位["起始偏移"],
        "结束偏移": 定位["结束偏移"],
        "起始行": 定位["起始行"],
        "结束行": 定位["结束行"],
        "旧文本摘要": 定位["旧文本摘要"],
        "旧文件摘要": 旧文件摘要,
        "新文件摘要": 新文件摘要,
        "差异": "".join(差异行列表),
        "差异行数": len(差异行列表),
        "新增行数": 新增行数,
        "删除行数": 删除行数,
    })

补丁标记开始 = "*** Begin Patch ***"
补丁标记结束 = "*** End Patch ***"
更新标记 = "*** Update File:"
创建标记 = "*** Add File:"
删除标记 = "*** Delete File:"
改名标记 = "*** Rename File:"
节标记前缀 = "***"


def _字节摘要(数据: bytes) -> str:
    """字节级 SHA256（与文本摘要对 UTF-8 内容等价）。"""
    return hashlib.sha256(数据).hexdigest()


def _是节标记(行: str) -> bool:
    """判断是否为 *** 开头的节标记（更新/创建/删除/改名/结束）。"""
    去空 = 行.strip()
    return (去空.startswith(更新标记) or 去空.startswith(创建标记)
            or 去空.startswith(删除标记) or 去空.startswith(改名标记)
            or 去空 == 补丁标记结束)


def _解析补丁路径(根: Path, 原始路径: str):
    """把补丁里的路径解析为根目录内的绝对路径；越界返回 (None, 错误说明)。"""
    候选 = Path(原始路径.strip())
    绝对 = 候选 if 候选.is_absolute() else (根 / 候选)
    try:
        绝对 = 绝对.resolve()
        相对 = str(绝对.relative_to(根))
    except ValueError:
        return None, f"补丁路径必须在根目录内: {原始路径.strip()}"
    return (绝对, 相对), ""


def 解析代码补丁(根目录: str, 补丁文本: str) -> 结果:
    """解析 Codex 风格补丁并计算各文件新内容（只计算，不落盘）。

    支持 *** Update File ***（@@ 上下文块：前缀 - 为旧行、+ 为新行、空格为共同行）、
    *** Add File ***、*** Delete File ***、*** Rename File: 旧 -> 新。
    返回 {操作列表, 变更数, 操作数}；每项含 文件路径/相对路径/已变更/旧文件摘要/新文件摘要/新内容。
    写盘与权限治理由调用方负责。
    """
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空字符串", 来源=来源标记)
    if not isinstance(补丁文本, str) or not 补丁文本.strip():
        return 结果.失败("参数不合法", "补丁文本不能为空", 来源=来源标记)

    根 = Path(根目录).expanduser().resolve()
    if not 根.is_dir():
        return 结果.失败("目录不存在", f"根目录不存在: {根}", 来源=来源标记)

    行列表 = 补丁文本.replace("\r\n", "\n").split("\n")
    if not 行列表 or 行列表[0].strip() != 补丁标记开始:
        return 结果.失败("补丁格式错误", f"补丁首行必须是 {补丁标记开始}", 来源=来源标记)
    if 补丁标记结束 not in [行.strip() for 行 in 行列表]:
        return 结果.失败("补丁格式错误", f"补丁缺少 {补丁标记结束}", 来源=来源标记)

    操作列表: list[dict[str, Any]] = []
    序号 = 1
    while 序号 < len(行列表):
        当前行 = 行列表[序号].strip()
        if 当前行 == 补丁标记结束:
            break
        if not 当前行:
            序号 += 1
            continue

        if 当前行.startswith(更新标记):
            解析结果, 错误 = _解析补丁路径(根, 当前行.split(":", 1)[1])
            if 解析结果 is None:
                return 结果.失败("路径越界", 错误, 来源=来源标记)
            路径, 相对路径 = 解析结果
            if not 路径.is_file():
                return 结果.失败("文件不存在", f"更新目标不存在: {相对路径}", 来源=来源标记)
            原始字节 = 路径.read_bytes()
            try:
                原文本 = 原始字节.decode("utf-8")
            except UnicodeDecodeError:
                return 结果.失败("编码错误", f"更新目标不是有效 UTF-8: {相对路径}", 来源=来源标记)
            当前文本 = 原文本
            序号 += 1
            while 序号 < len(行列表):
                头 = 行列表[序号].strip()
                if _是节标记(头):
                    break
                if 头 == "@@" or 头.startswith("@@ "):
                    序号 += 1
                    旧行集: list[str] = []
                    新行集: list[str] = []
                    while 序号 < len(行列表):
                        行 = 行列表[序号]
                        去空 = 行.strip()
                        if 去空 == "@@" or 去空.startswith("@@ ") or _是节标记(去空):
                            break
                        if 行.startswith("-"):
                            旧行集.append(行[1:])
                        elif 行.startswith("+"):
                            新行集.append(行[1:])
                        elif 行.startswith(" "):
                            旧行集.append(行[1:])
                            新行集.append(行[1:])
                        else:
                            旧行集.append(行)
                            新行集.append(行)
                        序号 += 1
                    旧块 = "\n".join(旧行集)
                    新块 = "\n".join(新行集)
                    if not 旧块:
                        return 结果.失败(
                            "补丁格式错误", f"上下文块无旧文本，无法唯一匹配: {相对路径}", 来源=来源标记)
                    # 旧块可能到文件尾（无尾换行）：裸命中与带换行命中是同一位置的不同表示，
                    # 不能重复计数；先各自判定唯一，再决定用哪个。
                    裸命中 = 当前文本.count(旧块)
                    带换行命中 = 当前文本.count(旧块 + "\n")
                    if 裸命中 == 1:
                        命中块 = 旧块
                    elif 带换行命中 == 1:
                        命中块 = 旧块 + "\n"
                    else:
                        return 结果.失败(
                            "匹配不唯一",
                            f"上下文块必须唯一命中，实际 裸={裸命中} 带换行={带换行命中}: {相对路径}",
                            来源=来源标记)
                    当前文本 = 当前文本.replace(
                        命中块, (新块 + "\n") if 命中块.endswith("\n") else 新块, 1)
                    continue
                序号 += 1
            已变更 = 当前文本 != 原文本
            操作列表.append({
                "操作": "更新", "相对路径": 相对路径, "文件路径": str(路径),
                "已变更": 已变更, "旧文件摘要": _字节摘要(原始字节),
                "新文件摘要": _字节摘要(当前文本.encode("utf-8")) if 已变更 else "",
                "新内容": 当前文本 if 已变更 else "",
            })
            continue

        if 当前行.startswith(创建标记):
            解析结果, 错误 = _解析补丁路径(根, 当前行.split(":", 1)[1])
            if 解析结果 is None:
                return 结果.失败("路径越界", 错误, 来源=来源标记)
            路径, 相对路径 = 解析结果
            if 路径.exists():
                return 结果.失败("文件已存在", f"创建目标已存在: {相对路径}", 来源=来源标记)
            新内容行: list[str] = []
            序号 += 1
            while 序号 < len(行列表) and not 行列表[序号].strip().startswith(节标记前缀):
                新内容行.append(行列表[序号])
                序号 += 1
            新内容 = "\n".join(新内容行)
            操作列表.append({
                "操作": "创建", "相对路径": 相对路径, "文件路径": str(路径),
                "已变更": True, "旧文件摘要": "", "旧内容": "",
                "新文件摘要": _字节摘要(新内容.encode("utf-8")), "新内容": 新内容,
            })
            continue

        if 当前行.startswith(删除标记):
            解析结果, 错误 = _解析补丁路径(根, 当前行.split(":", 1)[1])
            if 解析结果 is None:
                return 结果.失败("路径越界", 错误, 来源=来源标记)
            路径, 相对路径 = 解析结果
            if not 路径.is_file():
                return 结果.失败("文件不存在", f"删除目标不存在: {相对路径}", 来源=来源标记)
            操作列表.append({
                "操作": "删除", "相对路径": 相对路径, "文件路径": str(路径),
                "已变更": True, "旧文件摘要": _字节摘要(路径.read_bytes()),
            })
            序号 += 1
            continue

        if 当前行.startswith(改名标记):
            参数文本 = 当前行.split(":", 1)[1].strip()
            if "->" not in 参数文本:
                return 结果.失败("补丁格式错误", "改名需要「旧路径 -> 新路径」格式", 来源=来源标记)
            旧相对, _, 新相对 = 参数文本.partition("->")
            旧解析, 错误 = _解析补丁路径(根, 旧相对)
            if 旧解析 is None:
                return 结果.失败("路径越界", 错误, 来源=来源标记)
            新解析, 错误 = _解析补丁路径(根, 新相对)
            if 新解析 is None:
                return 结果.失败("路径越界", 错误, 来源=来源标记)
            旧路径, 旧相对路径 = 旧解析
            新路径, 新相对路径 = 新解析
            if not 旧路径.is_file():
                return 结果.失败("文件不存在", f"改名源不存在: {旧相对路径}", 来源=来源标记)
            操作列表.append({
                "操作": "改名", "相对路径": 旧相对路径, "新相对路径": 新相对路径,
                "文件路径": str(旧路径), "新文件路径": str(新路径),
                "已变更": True, "旧文件摘要": _字节摘要(旧路径.read_bytes()),
            })
            序号 += 1
            continue

        return 结果.失败("不支持的补丁操作", f"无法识别的补丁指令: {当前行}", 来源=来源标记)

    return 结果.成功结果({
        "操作列表": 操作列表,
        "操作数": len(操作列表),
        "变更数": sum(1 for 项 in 操作列表 if 项.get("已变更")),
    })
