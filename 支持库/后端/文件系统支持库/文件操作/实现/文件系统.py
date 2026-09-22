"""文件系统原子能力实现（不对外暴露，只经包级中文入口调用）。

全部公开能力返回统一结果（成功/值/错误/错误码）；参数缺失或类型非法
返回 参数不合法，文件系统异常转换为稳定错误码，不吞异常、不以成功形状
伪装失败。文件读取一律显式关闭句柄（with/close 闭合）。
判断存在 为平台既有契约：直接返回布尔（统一验证器直接消费），
非法参数按不存在处理。
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.错误结构 import 错误结构
from 支持库.后端.文件系统支持库.文件操作.实现.危险路径 import (
    拦截危险路径,
    放行标注,
    汇总放行标注,
)
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配 import 清只读后删除树, 移动并可删


默认最大字符 = 2000


def _精炼行(原文行: list) -> tuple[list, list]:
    """结构性精炼：折叠连续空行、去行尾空白、去首尾空行。

    返回（精炼后的行、行映射）；行映射[k] = 精炼后第 k 行在原文行里的下标，
    调用方据此把「已回到第几行」换算回原文行号，续取才接得上。

    **只做结构性处理，不做语义删减**：注释、代码、正文一个字都不删 ——
    「哪句是废话」是语义判断，底座不做（删错即丢信息，且不可逆）。
    """
    精炼: list = []
    映射: list = []
    上一个空 = False
    for 下标, 行 in enumerate(原文行):
        是空 = not 行.strip()
        if 是空:
            if 上一个空:
                continue
            精炼.append("\n")
        else:
            精炼.append(行.rstrip() + "\n" if 行.endswith("\n") else 行.rstrip())
        映射.append(下标)
        上一个空 = 是空
    while 精炼 and 精炼[0] == "\n":
        精炼.pop(0)
        映射.pop(0)
    while 精炼 and 精炼[-1] == "\n":
        精炼.pop()
        映射.pop()
    return 精炼, 映射


def 读取文件(文件路径: str = None, 编码: str = "utf-8",
             起始行: int = 0, 结束行: int = 0,
             最大字符: int = 默认最大字符, 精简: bool = 真,
             允许大文件: bool = 假) -> 结果:
    """按文本方式读取文件内容；默认精炼限长，显式分段则不限量。

    ``起始行`` / ``结束行`` 是 1 起的行号、闭区间；两者都为 0（默认）时取全文，
    与改前逐字一致。只传 起始行 取到文件末；只传 结束行 从首行起。区间超出文件
    实际范围时按存在的行返回（不报错），空区间返回空串。

    **默认路径（2026-09-22 华哥定）**：未显式分段时，先做**结构性精炼**
    （折叠连续空行 / 去行尾空白 / 去首尾空行，``精简=假`` 可关），再按 ``最大字符``
    （默认 2000）限长；超出则回**前 2000 字符 + 一行续取提示**（带续取的原文起始行），
    **不是失败、也不静默** —— 先看核心，要更多再按偏移取。

    **分段读取不限量**：显式传 ``起始行`` / ``结束行`` 即视为调用方自己控量，
    不做精炼、不限长（偏移值查询可以无限）；``允许大文件=真`` 或 ``最大字符=0``
    同样放行全量（用户绝对自主权不被剥夺）。

    为什么要它（#197）：全文读取在大文件上会打爆调用方上下文，而「读取文件头部字节」
    只给字节、拿不到指定行；中间段（例如某能力的契约定义）此前只能整份读进来。
    """
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    if not isinstance(编码, str):
        return 结果.失败("参数不合法", "编码必须是文本", 来源="文件系统")
    for 名称, 值 in (("起始行", 起始行), ("结束行", 结束行), ("最大字符", 最大字符)):
        if not isinstance(值, int) or isinstance(值, bool) or 值 < 0:
            return 结果.失败("参数不合法", f"{名称} 必须是非负整数（0 = 不限）", 来源="文件系统")
    for 名称, 值 in (("精简", 精简), ("允许大文件", 允许大文件)):
        if not isinstance(值, bool):
            return 结果.失败("参数不合法", f"{名称} 必须是逻辑型（真/假）", 来源="文件系统")
    if 起始行 and 结束行 and 起始行 > 结束行:
        return 结果.失败("参数不合法", f"起始行({起始行}) 不能大于 结束行({结束行})", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        文本 = 路径.read_text(encoding=编码)
    except LookupError as 错误:
        return 结果.失败("参数不合法", f"未知编码: {错误}", 来源="文件系统")
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")
    行表 = 文本.splitlines(keepends=True)
    起 = (起始行 - 1) if 起始行 else 0
    止 = 结束行 if 结束行 else len(行表)
    原文行 = 行表[起:止]
    分段读 = bool(起始行 or 结束行)
    if 允许大文件 or 最大字符 == 0 or 分段读:
        return 结果.成功结果("".join(原文行))
    精炼行, 行映射 = _精炼行(原文行) if 精简 else (list(原文行), list(range(len(原文行))))
    已回: list = []
    累计 = 0
    停在哪 = len(精炼行)
    for 序号, 行 in enumerate(精炼行):
        if 累计 + len(行) > 最大字符:
            停在哪 = 序号
            break
        已回.append(行)
        累计 += len(行)
    if 停在哪 >= len(精炼行):
        return 结果.成功结果("".join(已回))
    续行 = 起 + 行映射[停在哪] + 1
    return 结果.成功结果(
        "".join(已回)
        + f"\n…[已精炼限长：全文 {len(行表)} 行 / {len(文本)} 字符，本次回 {累计} 字符；"
          f"续取：起始行={续行}（显式分段读取不限量）]"
    )


def 写入文件(文件路径: str = None, 内容: str = None, 编码: str = "utf-8",
             允许危险路径: bool = 假) -> 结果:
    """按文本方式写入文件（自动创建父目录）。

    危险路径护栏（相对安全底线，见 实现/危险路径.py 判据全文）：默认拒绝命中
    危险路径判据的目标（系统目录 / 用户凭据与 shell 启动配置 / 指向它们的软链接父路径）；
    调用方传 允许危险路径=真 可显式放行并如实标注（用户绝对自主权不被剥夺）。
    """
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    if 内容 is None or not isinstance(内容, str):
        return 结果.失败("参数不合法", "内容必须为文本", 来源="文件系统")
    if not isinstance(编码, str):
        return 结果.失败("参数不合法", "编码必须是文本", 来源="文件系统")
    拦截 = 拦截危险路径(文件路径, 允许危险路径, "写入文件")
    if 拦截 is not None:
        return 拦截
    路径 = Path(文件路径)
    try:
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(内容, encoding=编码)
        return 结果.成功结果(真)
    except LookupError as 错误:
        return 结果.失败("参数不合法", f"未知编码: {错误}", 来源="文件系统")
    except OSError as 错误:
        return 结果.失败("文件不可写", str(错误), 来源="文件系统")


def 判断存在(文件路径: str = None) -> bool:
    """判断路径是否存在（平台既有契约：直接返回布尔；非法参数视为不存在）。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return 假
    return Path(文件路径).exists()


def 列出目录(目录路径: str = None) -> 结果:
    """列出目录下条目名称（排序稳定）。"""
    if 目录路径 is None or not isinstance(目录路径, str) or not 目录路径.strip():
        return 结果.失败("参数不合法", "目录路径必须为非空文本", 来源="文件系统")
    路径 = Path(目录路径)
    if not 路径.is_dir():
        return 结果.失败("目录不存在", f"目录不存在: {目录路径}", 来源="文件系统")
    try:
        return 结果.成功结果(sorted(条目.name for 条目 in 路径.iterdir()))
    except OSError as 错误:
        return 结果.失败("目录读取失败", str(错误), 来源="文件系统")


def 删除文件(文件路径: str = None, 允许危险路径: bool = 假) -> 结果:
    """删除文件或空目录（不存在视为幂等成功）。

    危险路径护栏：默认拒绝命中危险路径判据的目标；允许危险路径=真 显式放行并如实标注。
    """
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    拦截 = 拦截危险路径(文件路径, 允许危险路径, "删除文件")
    if 拦截 is not None:
        return 拦截
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.成功结果(真)
    try:
        if 路径.is_dir():
            路径.rmdir()
        else:
            路径.unlink()
        return 结果.成功结果(真)
    except OSError as 错误:
        return 结果.失败("文件删除失败", str(错误), 来源="文件系统")


def 复制文件(源路径: str = None, 目标路径: str = None,
             允许危险路径: bool = 假) -> 结果:
    """复制文件到目标路径（自动创建父目录）。

    危险路径护栏只判**目标路径**（源路径只读，不构成系统性破坏）；
    允许危险路径=真 显式放行并如实标注。
    """
    if 源路径 is None or not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须为非空文本", 来源="文件系统")
    if 目标路径 is None or not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须为非空文本", 来源="文件系统")
    源 = Path(源路径)
    if not 源.is_file():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    拦截 = 拦截危险路径(目标路径, 允许危险路径, "复制文件目标路径")
    if 拦截 is not None:
        return 拦截
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(源, 目标)
        return 结果.成功结果(真)
    except OSError as 错误:
        return 结果.失败("文件复制失败", str(错误), 来源="文件系统")


def 移动文件(源路径: str = None, 目标路径: str = None,
             允许危险路径: bool = 假) -> 结果:
    """移动文件或目录到目标路径（自动创建父目录）。

    危险路径护栏同时判**源路径与目标路径**（移动=源处删除+目标处写入，两端都可能
    造成系统性破坏）；允许危险路径=真 显式放行并如实标注。
    """
    if 源路径 is None or not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须为非空文本", 来源="文件系统")
    if 目标路径 is None or not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须为非空文本", 来源="文件系统")
    源 = Path(源路径)
    if not 源.exists():
        return 结果.失败("文件不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    拦截 = 拦截危险路径(源路径, 允许危险路径, "移动文件源路径") \
        or 拦截危险路径(目标路径, 允许危险路径, "移动文件目标路径")
    if 拦截 is not None:
        return 拦截
    try:
        目标 = Path(目标路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        # 唯一实现：只读属性/父目录无写位造成的 PermissionError 由它清只读后重试
        移动并可删(源, 目标)
        移动标注 = 汇总放行标注([源路径, 目标路径])
        if 移动标注:
            return 结果.成功结果({"成功": 真, "危险路径放行": 移动标注,
                                 "路径": 目标路径})
        return 结果.成功结果(真)
    except OSError as 错误:
        return 结果.失败("文件移动失败", str(错误), 来源="文件系统")


def 获取大小(文件路径: str = None) -> 结果:
    """获取文件大小（字节）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_size)
    except OSError as 错误:
        return 结果.失败("文件大小读取失败", str(错误), 来源="文件系统")


def 获取修改时间(文件路径: str = None) -> 结果:
    """获取文件修改时间戳（秒）。"""
    if 文件路径 is None or not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="文件系统")
    路径 = Path(文件路径)
    if not 路径.exists():
        return 结果.失败("文件不存在", f"文件不存在: {文件路径}", 来源="文件系统")
    try:
        return 结果.成功结果(路径.stat().st_mtime)
    except OSError as 错误:
        return 结果.失败("修改时间读取失败", str(错误), 来源="文件系统")


def 创建目录(目录路径: str = None, 递归: bool = 真,
             允许危险路径: bool = 假) -> 结果:
    """创建目录（递归创建父目录；已存在视为幂等成功）。

    危险路径护栏：默认拒绝命中危险路径判据的目标；允许危险路径=真 显式放行并如实标注。
    """
    if 目录路径 is None or not isinstance(目录路径, str) or not 目录路径.strip():
        return 结果.失败("参数不合法", "目录路径必须为非空文本", 来源="文件系统")
    拦截 = 拦截危险路径(目录路径, 允许危险路径, "创建目录")
    if 拦截 is not None:
        return 拦截
    路径 = Path(目录路径)
    if 路径.is_dir():
        return 结果.成功结果(真)
    try:
        if 递归:
            路径.mkdir(parents=True, exist_ok=True)
        else:
            路径.mkdir(exist_ok=True)
        return 结果.成功结果(真)
    except OSError as 错误:
        return 结果.失败("目录创建失败", str(错误), 来源="文件系统")


def 读取二进制文件(受控根目录: str = None, 相对路径: str = None,
                    最大字节数: int = 0) -> 结果:
    """在受控根目录内按相对路径读取二进制文件（路径边界校验 + 大小上限）。

    相对路径不得越出受控根目录（防路径逃逸）；最大字节数>0 时超限拒绝
    （防一次性无界读入内存）。供文件资产主链路经项目适配层调用。
    """
    if 受控根目录 is None or not isinstance(受控根目录, str) or not 受控根目录.strip():
        return 结果.失败("参数不合法", "受控根目录必须为非空文本", 来源="文件系统")
    if 相对路径 is None or not isinstance(相对路径, str):
        return 结果.失败("参数不合法", "相对路径必须为文本", 来源="文件系统")
    根目录 = Path(受控根目录).resolve()
    if not 根目录.is_dir():
        return 结果.失败("目录不存在", f"受控根目录不存在: {受控根目录}", 来源="文件系统")
    目标 = (根目录 / 相对路径).resolve()
    try:
        if os.path.commonpath([str(根目录), str(目标)]) != str(根目录):
            return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    except ValueError:
        return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    if not 目标.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {相对路径}", 来源="文件系统")
    try:
        文件大小 = 目标.stat().st_size
        if 最大字节数 and 文件大小 > 最大字节数:
            return 结果.失败("文件超限", f"文件 {文件大小} 字节超过上限 {最大字节数}", 来源="文件系统")
        return 结果.成功结果(目标.read_bytes())
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


def 读取文件头部字节(受控根目录: str = None, 相对路径: str = None,
                     字节数: int = 4096) -> 结果:
    """在受控根目录内按相对路径只读文件头部 N 字节（不加载全文件）。

    受控根 + 相对路径 双重路径边界校验（防路径逃逸）；只读头部字节数，
    大文件也不会整体载入内存。供文件头嗅探/预览等只读场景调用。
    """
    if 受控根目录 is None or not isinstance(受控根目录, str) or not 受控根目录.strip():
        return 结果.失败("参数不合法", "受控根目录必须为非空文本", 来源="文件系统")
    if 相对路径 is None or not isinstance(相对路径, str):
        return 结果.失败("参数不合法", "相对路径必须为文本", 来源="文件系统")
    根目录 = Path(受控根目录).resolve()
    if not 根目录.is_dir():
        return 结果.失败("目录不存在", f"受控根目录不存在: {受控根目录}", 来源="文件系统")
    目标 = (根目录 / 相对路径).resolve()
    try:
        if os.path.commonpath([str(根目录), str(目标)]) != str(根目录):
            return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    except ValueError:
        return 结果.失败("路径越界", f"路径越出受控根目录: {相对路径}", 来源="文件系统")
    if not 目标.is_file():
        return 结果.失败("文件不存在", f"文件不存在: {相对路径}", 来源="文件系统")
    try:
        with open(目标, "rb") as 文件流:
            return 结果.成功结果(文件流.read(max(int(字节数), 0)))
    except OSError as 错误:
        return 结果.失败("文件读取失败", str(错误), 来源="文件系统")


_临时资源登记表: set[str] = set()
_临时资源锁 = threading.Lock()


def 登记临时资源(路径: str = None) -> 结果:
    """登记一个临时资源（文件或目录），由 清理全部临时资源 统一释放。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须为非空文本", 来源="文件系统")
    with _临时资源锁:
        _临时资源登记表.add(路径)
        return 结果.成功结果(len(_临时资源登记表))


def 清理全部临时资源(路径前缀: str = "", 允许危险路径: bool = 假) -> 结果:
    """清理已登记临时资源（文件删除/目录递归删除，不存在视为幂等成功）。

    路径前缀 非空时只清理以此前缀开头的登记资源；无匹配登记资源时返回
    资源不存在（避免静默什么都不做）。登记表变更全部在锁内完成。

    危险路径护栏：清理=删除动作，逐条登记资源默认拒绝命中危险路径判据的目标
    （护栏在任何删除发生之前完成判定，命中即整批不改动）；允许危险路径=真 显式放行并如实标注。
    """
    if 路径前缀 is None or not isinstance(路径前缀, str):
        return 结果.失败("参数不合法", "路径前缀必须为文本", 来源="文件系统")
    with _临时资源锁:
        # 前缀匹配必须按**路径段边界**（缺陷 #151，2026-09-20）：
        # 裸 `startswith` 是字符串级匹配，前缀 `工程缓存/tmp/abc` 会连
        # `工程缓存/tmp/abcxxx`（相邻但不同的登记项）一起匹配并 `rmtree` —— 误删。
        # 加 `os.sep` 边界后只匹配「就是它本身」或「它在某段之下」。
        待清理 = _临时资源登记表 if not 路径前缀 else {
            路径 for 路径 in _临时资源登记表
            if 路径 == 路径前缀 or 路径.startswith(路径前缀 + os.sep)
        }
        if 路径前缀 and not 待清理:
            return 结果.失败("资源不存在", f"无匹配前缀 {路径前缀} 的登记资源", 来源="文件系统")
        for 路径 in sorted(待清理):
            拦截 = 拦截危险路径(路径, 允许危险路径, "清理全部临时资源")
            if 拦截 is not None:
                return 拦截
        清理失败表 = []
        清理数量 = 0
        for 路径 in list(待清理):
            try:
                目标 = Path(路径)
                if 目标.is_dir():
                    清只读后删除树(目标)
                else:
                    目标.unlink(missing_ok=True)
                清理数量 += 1
                _临时资源登记表.discard(路径)
            except OSError as 错误:
                清理失败表.append(f"{路径}: {错误}")
        清理标注 = 汇总放行标注(sorted(待清理))
    if 清理失败表:
        return 结果.失败("清理失败", "；".join(清理失败表), 来源="文件系统")
    if 清理标注:
        return 结果.成功结果({"清理数量": 清理数量, "危险路径放行": 清理标注})
    return 结果.成功结果(清理数量)
