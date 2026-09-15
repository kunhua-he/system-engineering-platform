"""文件系统补充原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：文件搜索/压缩解压/权限/追加写入（参考易语言文件读写类模块）。
纯标准库，不做业务逻辑。
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import shutil
import zipfile

from 公共契约.基础类型.结果类型 import 结果


def 搜索文件(目录: str = None, 通配符: str = None, 递归: bool = None) -> 结果:
    """按通配符搜索文件。返回 {文件数, 文件列表}。"""
    if not isinstance(目录, str) or not 目录.strip():
        return 结果.失败("参数不合法", "目录必须是非空字符串", 来源="文件系统")
    if not isinstance(通配符, str) or not 通配符.strip():
        return 结果.失败("参数不合法", "通配符必须是非空字符串", 来源="文件系统")
    if not os.path.isdir(目录):
        return 结果.失败("目录不存在", f"目录不存在: {目录}", 来源="文件系统")
    文件列表 = []
    if 递归:
        for 根, 子目录, 文件 in os.walk(目录):
            for f in 文件:
                if fnmatch.fnmatch(f, 通配符):
                    文件列表.append(os.path.join(根, f))
    else:
        try:
            for f in os.listdir(目录):
                if fnmatch.fnmatch(f, 通配符):
                    完整路径 = os.path.join(目录, f)
                    if os.path.isfile(完整路径):
                        文件列表.append(完整路径)
        except OSError as 错误:
            return 结果.失败("读取失败", str(错误), 来源="文件系统")
    return 结果.成功结果({"文件数": len(文件列表), "文件列表": sorted(文件列表)})


def 追加写入(路径: str = None, 内容: str = None) -> 结果:
    """追加文本到文件末尾。返回 {路径, 追加字节数}。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须是非空字符串", 来源="文件系统")
    if 内容 is None:
        return 结果.失败("参数不合法", "内容不能为空", 来源="文件系统")
    try:
        with open(路径, "a", encoding="utf-8") as f:
            字节数 = f.write(str(内容))
        return 结果.成功结果({"路径": 路径, "追加字节数": 字节数})
    except OSError as 错误:
        return 结果.失败("写入失败", str(错误), 来源="文件系统")


def 压缩文件(源路径: str = None, 目标路径: str = None) -> 结果:
    """压缩文件/目录为 zip。返回 {目标路径, 条目数}。"""
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须是非空字符串", 来源="文件系统")
    if not os.path.exists(源路径):
        return 结果.失败("源不存在", f"源不存在: {源路径}", 来源="文件系统")
    try:
        条目数 = 0
        with zipfile.ZipFile(目标路径, "w", zipfile.ZIP_DEFLATED) as 压缩包:
            if os.path.isfile(源路径):
                压缩包.write(源路径, os.path.basename(源路径))
                条目数 = 1
            else:
                for 根, 子目录, 文件 in os.walk(源路径):
                    for f in 文件:
                        完整路径 = os.path.join(根, f)
                        相对路径 = os.path.relpath(完整路径, os.path.dirname(源路径))
                        压缩包.write(完整路径, 相对路径)
                        条目数 += 1
        return 结果.成功结果({"目标路径": 目标路径, "条目数": 条目数})
    except Exception as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")


# 解压入参上限默认值（口径与 运行核心/运行环境管理器/远程镜像.py 的
# 默认最大制品字节数 一致：解包必须有界，不许无上限落盘）。
默认解压上限字节 = 1024 * 1024 * 1024   # 1 GiB
默认解压条目上限 = 10000
默认解压压缩比上限 = 100.0              # 100 : 1（防 zip 炸弹）
解压分块字节 = 1024 * 1024


class _超过上限(Exception):
    """落盘中途实际字节数超过入参上限（内部信号，只转成 超过解压上限 错误码）。"""


def _解压上限(值, 默认值: float, 名称: str) -> float:
    """上限入参归一：None → 包默认上限；逻辑型/非数值/非正值一律拒绝。

    不做「0 = 不限制」的隐式放大：上限只能显式给正数，避免调用方一个 0 就把
    防护关掉（与本包 读取二进制文件.最大字节数 的 0=不限制 口径不同，此处
    取 fail-closed；默认值本身已有界）。
    """
    if 值 is None:
        return 默认值
    if isinstance(值, bool) or not isinstance(值, (int, float)):
        raise ValueError(f"{名称} 必须是数值型")
    if 值 <= 0:
        raise ValueError(f"{名称} 必须为正数（0/负数不表示不限制）")
    return 值


def _清理解压半成品(目标根: pathlib.Path, 新建目标目录: bool, 已写路径列表: list) -> None:
    """解压失败回滚：本次新建的目录整棵删除，否则只删本次写入的文件与空目录。

    只删「自己这一次写的」东西：目标目录是调用方既有目录时，删除范围不越出
    本次写入路径的父链，且仅删空目录，不碰调用方的既有内容。
    """
    if 新建目标目录:
        shutil.rmtree(目标根, ignore_errors=True)
        return
    for 路径 in sorted(已写路径列表, key=lambda 项: len(项.parts), reverse=True):
        try:
            路径.unlink()
        except OSError:
            continue
        上级 = 路径.parent
        while 上级 != 目标根 and 目标根 in 上级.parents:
            try:
                上级.rmdir()
            except OSError:
                break
            上级 = 上级.parent


def 解压文件(源路径: str = None, 目标目录: str = None,
             最大字节数: int = None, 最大条目数: int = None,
             最大压缩比: float = None) -> 结果:
    """解压 zip 到目录（防 zip 炸弹 + 防路径穿越）。返回 {目标目录, 条目数}。

    三道入参上限，全部 fail-fast：先校验、后落盘，超限一个字节都不写。
    - 最大字节数：解压后总字节上限，默认 默认解压上限字节（1 GiB）；
    - 最大条目数：归档条目数上限，默认 默认解压条目上限（10000）；
    - 最大压缩比：解压总字节 ÷ 源压缩包磁盘字节，默认 默认解压压缩比上限（100 : 1）。
    三者 None = 用默认上限；正数 = 收紧或放宽；0/负数/非数值 = 参数不合法。

    路径安全：逐成员以 目标根.resolve() 做 is_relative_to 判定（不再用字符串
    前缀比较，杜绝 out / outx 这类兄弟目录绕过），绝对路径与含 `..` 段的成员
    一律拒绝。落盘按成员分块写入并累计实写字节，实写字节越上限即中断回滚
    （zipfile 自身也按声明大小与 CRC 校验解码，本检查是第二道兜底，实测由
    归档声明/CRC 不一致先触发）。

    失败不留半成品：上限与路径校验全部在落盘之前完成；落盘中途失败（含归档
    声明、CRC 与实际不符）会回滚本次写入的文件与空目录。
    """
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标目录, str) or not 目标目录.strip():
        return 结果.失败("参数不合法", "目标目录必须是非空字符串", 来源="文件系统")
    if not os.path.isfile(源路径):
        return 结果.失败("源不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        上限字节 = _解压上限(最大字节数, 默认解压上限字节, "最大字节数")
        上限条目 = int(_解压上限(最大条目数, 默认解压条目上限, "最大条目数"))
        上限压缩比 = _解压上限(最大压缩比, 默认解压压缩比上限, "最大压缩比")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="文件系统")
    try:
        源包字节 = os.path.getsize(源路径)
    except OSError as 错误:
        return 结果.失败("解压失败", str(错误), 来源="文件系统")
    目标根 = pathlib.Path(目标目录).resolve()
    新建目标目录 = False
    已写路径列表 = []
    try:
        with zipfile.ZipFile(源路径, "r") as 压缩包:
            成员列表 = 压缩包.infolist()
            if len(成员列表) > 上限条目:
                return 结果.失败("超过条目上限",
                                f"归档条目数 {len(成员列表)} 超过上限 {上限条目}",
                                来源="文件系统")
            解压总字节 = sum(int(成员.file_size) for 成员 in 成员列表)
            压缩比 = 解压总字节 / max(源包字节, 1)
            if 解压总字节 > 上限字节:
                return 结果.失败("超过解压上限",
                                f"解压总字节 {解压总字节} 超过上限 {上限字节}",
                                来源="文件系统")
            if 压缩比 > 上限压缩比:
                return 结果.失败("超过压缩比上限",
                                f"压缩比 {压缩比:.1f}:1 超过上限 {上限压缩比:g}:1"
                                f"（解压 {解压总字节} 字节 / 压缩包 {源包字节} 字节）",
                                来源="文件系统")
            # 防 zip 炸弹 + 防路径穿越：绝对路径与 `..` 段直接拒绝；其余解析后
            # 必须仍在目标根内（is_relative_to，替代原字符串前缀比较）。
            计划列表 = []
            for 成员 in 成员列表:
                纯路径 = pathlib.PurePosixPath(成员.filename)
                if not 纯路径.parts or 纯路径.is_absolute() or ".." in 纯路径.parts:
                    return 结果.失败("路径越界",
                                    f"归档成员路径非法: {成员.filename}",
                                    来源="文件系统")
                目标 = (目标根 / 纯路径).resolve()
                if not 目标.is_relative_to(目标根):
                    return 结果.失败("路径越界",
                                    f"归档成员路径逃出目标目录: {成员.filename}",
                                    来源="文件系统")
                计划列表.append((成员, 目标))
            if not 目标根.exists():
                目标根.mkdir(parents=True)
                新建目标目录 = True
            写入总字节 = 0
            for 成员, 目标 in 计划列表:
                if 成员.is_dir():
                    目标.mkdir(parents=True, exist_ok=True)
                    continue
                目标.parent.mkdir(parents=True, exist_ok=True)
                本次字节 = 0
                with 压缩包.open(成员, "r") as 读入, open(目标, "wb") as 写出:
                    while True:
                        数据块 = 读入.read(解压分块字节)
                        if not 数据块:
                            break
                        本次字节 += len(数据块)
                        if 写入总字节 + 本次字节 > 上限字节:
                            raise _超过上限(
                                f"实际解压 {写入总字节 + 本次字节} 字节超过上限 {上限字节}"
                                f"（归档声明与实写不符）")
                        写出.write(数据块)
                已写路径列表.append(目标)
                写入总字节 += 本次字节
        return 结果.成功结果({"目标目录": 目标目录, "条目数": len(成员列表)})
    except _超过上限 as 错误:
        _清理解压半成品(目标根, 新建目标目录, 已写路径列表)
        return 结果.失败("超过解压上限", str(错误), 来源="文件系统")
    except Exception as 错误:
        _清理解压半成品(目标根, 新建目标目录, 已写路径列表)
        return 结果.失败("解压失败", str(错误), 来源="文件系统")


def 获取文件权限(路径: str = None) -> 结果:
    """获取文件权限。返回 {路径, 权限, 可读, 可写, 可执行}。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须是非空字符串", 来源="文件系统")
    if not os.path.exists(路径):
        return 结果.失败("路径不存在", f"路径不存在: {路径}", 来源="文件系统")
    try:
        权限 = oct(os.stat(路径).st_mode & 0o777)
        return 结果.成功结果({"路径": 路径, "权限": 权限,
                                "可读": os.access(路径, os.R_OK),
                                "可写": os.access(路径, os.W_OK),
                                "可执行": os.access(路径, os.X_OK)})
    except OSError as 错误:
        return 结果.失败("读取失败", str(错误), 来源="文件系统")

def 查找祖先目录(起点: str, 标记: str, 匹配起点名: bool = True, 最大层数: int = 64) -> 结果:
    """从起点向上查找包含指定标记（子目录或文件）的最近祖先目录。

    标记可以是目录名（如 MCP工具箱）或文件名（如 .git、pyproject.toml）。
    匹配起点名=真 时，若起点自身的名字等于标记，直接返回其父目录（兼容「起点就在
    标记目录内」的调用形态）。找不到任何命中时返回起点本身并置 命中=假。
    """
    from pathlib import Path as _Path

    if not isinstance(起点, str) or not 起点.strip():
        return 结果.失败("参数不合法", "起点必须是非空字符串", 来源="文件操作")
    if not isinstance(标记, str) or not 标记.strip():
        return 结果.失败("参数不合法", "标记必须是非空字符串", 来源="文件操作")
    if not isinstance(匹配起点名, bool):
        return 结果.失败("参数不合法", "匹配起点名必须是逻辑型", 来源="文件操作")

    路径 = _Path(起点).expanduser()
    try:
        路径 = 路径.resolve()
    except OSError as 错误:
        return 结果.失败("路径无效", f"起点无法解析: {错误}", 来源="文件操作")

    起点文本 = str(路径)
    if 匹配起点名 and 路径.name == 标记:
        return 结果.成功结果({"根目录": str(路径.parent), "命中": True, "层级": 0,
                            "命中路径": 起点文本, "起点": 起点文本})
    if (路径 / 标记).exists():
        return 结果.成功结果({"根目录": 起点文本, "命中": True, "层级": 0,
                            "命中路径": 起点文本, "起点": 起点文本})

    层数 = 0
    for 上级 in 路径.parents:
        层数 += 1
        if 层数 > 最大层数:
            break
        if (上级 / 标记).exists():
            return 结果.成功结果({"根目录": str(上级), "命中": True, "层级": 层数,
                                "命中路径": str(上级 / 标记), "起点": 起点文本})
    return 结果.成功结果({"根目录": 起点文本, "命中": False, "层级": 层数,
                        "命中路径": "", "起点": 起点文本})
