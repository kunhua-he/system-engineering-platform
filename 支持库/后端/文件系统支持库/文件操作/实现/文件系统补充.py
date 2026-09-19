"""文件系统补充原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：文件搜索/压缩解压/权限/追加写入（参考易语言文件读写类模块）。
纯标准库，不做业务逻辑。
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import pathlib
import shutil
import tempfile
import zipfile

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时.平台适配 import 清只读后删除树, 移动并可删
from 支持库.后端.文件系统支持库.文件操作.实现.危险路径 import (
    拦截危险路径,
    放行标注,
)


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


def 追加写入(路径: str = None, 内容: str = None,
             允许危险路径: bool = False) -> 结果:
    """追加文本到文件末尾。返回 {路径, 追加字节数, 追加字符数}（显式放行危险路径时加 危险路径放行 标注）。

    危险路径护栏：追加=改变文件内容，默认拒绝命中危险路径判据的目标；
    允许危险路径=真 显式放行并如实标注。

    计数口径：`追加字节数` **实写字节数**（按 utf-8 编码后的长度），
    `追加字符数` 为 `str` 字符个数 —— 修掉「字段名叫字节、值其实是字符」的
    名实不符（中文时旧实现 报2 实际6）。两个字段取同一份字节缓冲的
    len(buf) 与 len(str)，不依赖 `write()` 返回值（文本流返回字符数，不是字节数）。
    """
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须是非空字符串", 来源="文件系统")
    if 内容 is None:
        return 结果.失败("参数不合法", "内容不能为空", 来源="文件系统")
    拦截 = 拦截危险路径(路径, 允许危险路径, "追加写入")
    if 拦截 is not None:
        return 拦截
    文本 = str(内容)
    try:
        字节缓冲 = 文本.encode("utf-8")
        with open(路径, "ab") as f:
            f.write(字节缓冲)
        结果值: dict = {"路径": 路径,
                      "追加字节数": len(字节缓冲),
                      "追加字符数": len(文本)}
        标注 = 放行标注(路径)
        if 标注:
            结果值["危险路径放行"] = 标注
        return 结果.成功结果(结果值)
    except UnicodeEncodeError as 错误:
        return 结果.失败("写入失败", f"内容无法按 utf-8 编码: {错误}", 来源="文件系统")
    except OSError as 错误:
        return 结果.失败("写入失败", str(错误), 来源="文件系统")


def 压缩文件(源路径: str = None, 目标路径: str = None,
             允许危险路径: bool = False) -> 结果:
    """压缩文件/目录为 zip。返回 {目标路径, 条目数}（显式放行时加 危险路径放行 标注）。

    危险路径护栏只判**目标路径**（源路径只读，不构成系统性破坏）；
    允许危险路径=真 显式放行并如实标注。

    不静默截断既有目标（与 解压文件 同一口径）：写入前先备份既有目标 → 写临时 zip
    → `os.replace` 原子替换；失败时删临时件并**还原既有目标**（旧内容逐字不变，
    既不截断也不丢失）。自包含防护：目标路径在源目录内时，从挑选出的源文件清单里
    剔除目标自身（按 resolve 后的真实路径比对），避免归档把自己写进自己。失败不留半截 zip。

    两条 fail-closed 拒绝（目录不是「可被覆盖的文件」，写上去必然毁整棵目录树）：
    - **源与目标同一个位置**：按 resolve 后的真实路径判等，文件与目录形态都拦
      （旧实现只判文件形态，源=目录且目标=该目录自身时会把目录压成一个 zip 覆盖掉、
      还返回成功）；
    - **目标是既有目录**：旧实现 `ZipFile(目标路径,"w")` 直写 + 成功后删备份 =
      静默毁目录且报成功。`is_dir()` 跟随软链接，故指向目录的软链接同样拦下。
    """
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须是非空字符串", 来源="文件系统")
    if not os.path.exists(源路径):
        return 结果.失败("源不存在", f"源不存在: {源路径}", 来源="文件系统")
    拦截 = 拦截危险路径(目标路径, 允许危险路径, "压缩文件目标路径")
    if 拦截 is not None:
        return 拦截
    目标 = pathlib.Path(目标路径).expanduser()
    try:
        目标真实 = 目标.resolve()
    except OSError as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")
    try:
        源真实 = pathlib.Path(源路径).resolve()
    except OSError as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")
    if 源真实 == 目标真实:
        # 源与目标同一位置：文件形态会自毁，目录形态会「把自己压成一个 zip 文件」
        # 覆盖掉原目录（旧实现只判 isfile，源=目录且目标=该目录自身时直接毁目录还报成功）。
        return 结果.失败("参数不合法", "源路径与目标路径是同一个位置，压缩会自包含/自毁",
                        来源="文件系统")
    # 目标是既有目录：zip 是普通文件，写上去必然把整棵目录树换掉。
    # 旧实现 `ZipFile(目标路径,"w")` 直写 + 成功后删备份 = 静默毁目录且报成功（数据丢失）。
    # 目录不是「可被覆盖的文件」，fail-closed 拒绝（is_dir() 跟随软链接，指向目录的软链接同样拦下）。
    if 目标.is_dir():
        return 结果.失败("参数不合法",
                        f"目标路径是既有目录，压缩不会用 zip 覆盖整棵目录树: {目标路径}",
                        来源="文件系统")

    # 先挑源文件清单（含自包含排除），再动目标路径上的任何东西。
    # 遍历基用 abspath（不解析符号链接）：保证 os.walk 产出的路径与「父目录」
    # 同形态，成员名与旧行为逐字一致（解析过的那份只在做自包含比对时用）。
    待压缩列表: list[tuple[str, str]] = []
    try:
        if os.path.isfile(源路径):
            待压缩列表.append((源路径, os.path.basename(源路径)))
        else:
            遍历基 = os.path.abspath(源路径)
            父目录 = os.path.dirname(遍历基)
            for 根, 子目录, 文件 in os.walk(遍历基):
                子目录[:] = [
                    名 for 名 in 子目录
                    if not (pathlib.Path(根) / 名).resolve().is_relative_to(目标真实)
                ]
                for 名 in 文件:
                    完整路径 = os.path.join(根, 名)
                    try:
                        真实路径 = pathlib.Path(完整路径).resolve()
                    except OSError:
                        continue
                    if 真实路径 == 目标真实:
                        continue  # 不把目标 zip 自己写进自己（写入途中边写边读）
                    相对路径 = os.path.relpath(完整路径, 父目录)
                    待压缩列表.append((完整路径, 相对路径))
    except OSError as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")

    try:
        目标.parent.mkdir(parents=True, exist_ok=True)
    except OSError as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")

    临时目录 = None
    临时压缩件 = None
    既有目标备份件 = None
    try:
        文本目标 = str(目标)
        句柄, 临时压缩件 = tempfile.mkstemp(
            dir=str(目标.parent), prefix=".__压缩_", suffix=".tmp")
        os.close(句柄)
        条目数 = 0
        with zipfile.ZipFile(临时压缩件, "w", zipfile.ZIP_DEFLATED) as 压缩包:
            for 完整路径, 相对路径 in 待压缩列表:
                压缩包.write(完整路径, 相对路径)
                条目数 += 1
        if 目标.is_symlink():
            目标.unlink()
        if 目标.exists():
            # 与 解压文件 同一口径：绝不静默截断既有目标 —— 先备份再原子替换。
            临时目录 = pathlib.Path(tempfile.mkdtemp(
                dir=str(目标.parent), prefix=".__压缩备份_"))
            既有目标备份件 = 临时目录 / "旧目标.zip"
            移动并可删(文本目标, 既有目标备份件)
        os.replace(临时压缩件, 文本目标)
        临时压缩件 = None
        压缩结果: dict = {"目标路径": 目标路径, "条目数": 条目数}
        压缩标注 = 放行标注(目标路径)
        if 压缩标注:
            压缩结果["危险路径放行"] = 压缩标注
        return 结果.成功结果(压缩结果)
    except Exception as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")
    finally:
        # 失败路径清理 + 既有目标还原（成功路径下 临时压缩件 已换成 None，不动成品）。
        if 临时压缩件 is not None:
            with contextlib.suppress(OSError):
                os.unlink(临时压缩件)
        if 既有目标备份件 is not None:
            try:
                if 既有目标备份件.exists() and not 目标.exists():
                    移动并可删(既有目标备份件, 目标)
            except OSError:
                pass
        if 临时目录 is not None:
            清只读后删除树(临时目录, 忽略失败=真)


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
        raise ValueError(f"{名称} 必须是数值（正式类型：整数型 或 双精度数型；布尔不算）")
    if 值 <= 0:
        raise ValueError(f"{名称} 必须为正数（0/负数不表示不限制）")
    return 值


def _清理解压落盘中转件(目标根: pathlib.Path, 新建目标目录: bool,
                    已有文件备份表: dict, 已写文件列表: list,
                    已建目录列表: list) -> bool:
    """解压失败回滚：绝不删除/截断调用方原有文件。返回 是否还原成功。

    - 目标目录本次新建：整棵删除（清完不留空壳）；
    - 目标目录是调用方既有目录：范围限定在「本次新建的」东西 —— 本次新建的文件
      `unlink`、本次新建的空目录 `rmdir`（自底向上，非空即停）；
    - **覆盖过调用方既有文件成员**：按写前备份表逐字还原（`os.replace` 回原路径）；
    - 每次删/还原后剔除同路径的既有空目录记录，避免把调用方原目录压成空壳。

    关键：删/还原的口径来自「写前是否已存在」的实测快照，不来自「已写路径列表」——
    后者在旧实现里既混着调用方原有文件，又只在写完后才登记，失败即把原文件删掉。
    """

    def 剔除空目录记录(路径: pathlib.Path) -> None:
        try:
            已建目录列表.remove(路径)
        except ValueError:
            pass

    if 新建目标目录:
        清只读后删除树(目标根, 忽略失败=真)
        return True
    还原成功 = True
    for 备份路径, 原路径 in 已有文件备份表.items():
        try:
            if 备份路径.exists():
                os.replace(str(备份路径), str(原路径))
            else:
                还原成功 = False
        except OSError:
            还原成功 = False
        else:
            剔除空目录记录(原路径.parent)
    for 路径 in sorted(已写文件列表, key=lambda 项: len(项.parts), reverse=True):
        try:
            路径.unlink()
        except OSError:
            continue
        剔除空目录记录(路径.parent)
    for 目录 in sorted(已建目录列表, key=lambda 项: len(项.parts), reverse=True):
        try:
            目录.rmdir()
        except OSError:
            continue
        try:
            已建目录列表.remove(目录)
        except ValueError:
            pass
    for 备份路径 in 已有文件备份表:
        保留目录 = 备份路径.parent
        if 保留目录.exists() and any(保留目录.iterdir()):
            continue
        清只读后删除树(保留目录, 忽略失败=真)
    return 还原成功


def 解压文件(源路径: str = None, 目标目录: str = None,
             最大字节数: int = None, 最大条目数: int = None,
             最大压缩比: float = None, 允许危险路径: bool = False) -> 结果:
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

    失败不留落盘中转件：上限与路径校验全部在落盘之前完成；落盘中途失败（含归档
    声明、CRC 与实际不符）会回滚本次写入的文件与空目录。

    绝不丢失调用方原有内容（本包统一口径，与 压缩文件 一致「不静默截断既有文件」）：
    落盘前先记「写前是否已存在」的实测快照 —— 新文件写同目录临时件再 `os.replace`
    原子落位；**覆盖既有文件**则先把既有内容整体搬进本次备份目录（同卷 rename），
    失败按备份表逐字还原回原路径。因此「本次写入的」与「原本就在的」严格可分，
    回滚只删/只还原自己这一趟动过的东西，调用方原文件与既有目录都不会被删或被截断。

    另一条 fail-closed 拒绝（落盘之前，零改动）：**归档成员是文件、目标位置却是调用方
    既有目录** —— 落盘口径会把整棵目录树换成单文件（旧实现备份后原子替换、成功即删备份，
    静默毁树且返回成功）。目录不是「可被覆盖的文件」，与 压缩文件 同一口径拒绝。
    """
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标目录, str) or not 目标目录.strip():
        return 结果.失败("参数不合法", "目标目录必须是非空字符串", 来源="文件系统")
    拦截 = 拦截危险路径(目标目录, 允许危险路径, "解压文件目标目录")
    if 拦截 is not None:
        return 拦截
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
        源包真实 = pathlib.Path(源路径).resolve()
    except OSError as 错误:
        return 结果.失败("解压失败", str(错误), 来源="文件系统")
    目标根 = pathlib.Path(目标目录).resolve()
    新建目标目录 = False
    已写文件列表 = []          # 本次新建（写前不存在）的文件，回滚只删这些
    已建目录列表 = []          # 本次新建的目录，回滚只删这些
    已有文件备份表: dict = {}   # 目标路径 → 备份路径：写前就存在、被本次覆盖的调用方文件
    临时备份目录 = None        # 本次备份目录（成功即删；回滚不成功时保留，供取证还原）

    def 建目录并登记(目录: pathlib.Path) -> None:
        """mkdir(parents=True) 并登记「本次新建」的目录，回滚时只删登记过的。"""
        待登记 = []
        当前 = 目录
        while 当前 != 目标根 and 目标根 in 当前.parents:
            待登记.append(当前)
            当前 = 当前.parent
        for 项 in reversed(待登记):
            if not 项.exists():
                项.mkdir(parents=True, exist_ok=True)
                已建目录列表.append(项)

    def 备份既有目标(目标: pathlib.Path) -> None:
        """写前把调用方既有目标（文件或软链接）整体搬进本次备份目录（同卷 rename）。

        搬走而不是复制：既有字节原样保留在备份里，回滚时 `os.replace` 搬回原路径
        即为逐字还原；成功路径下整个备份目录删除，不留残留。搬不动就直接抛错交给
        回滚口径 —— 绝不静默截断既有文件（等价 `原子写入` 的「先写临时再替换」，
        这里受制于分块落盘，改为「先搬备份再替换」）。
        """
        nonlocal 临时备份目录
        if 目标 in 已有文件备份表.values():
            return   # 同一目标本趟已备份过（归档里同名成员重复）→ 真原件已在备份里，不再搬
        if 临时备份目录 is None:
            临时备份目录 = pathlib.Path(tempfile.mkdtemp(
                dir=str(目标根), prefix=".__解压备份_"))
        备份路径 = 临时备份目录 / f"{len(已有文件备份表)}__.bak"
        移动并可删(目标, 备份路径)
        已有文件备份表[备份路径] = 目标   # 键＝备份件，值＝原路径（回滚按此还原）

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
                # 源包自己落在目标根内时，成员命中源包 = 解压会把源包自己删掉
                # （源包被当成既有文件备份、成功后再随备份目录删除）→ 先拦下。
                if 目标 == 源包真实:
                    return 结果.失败(
                        "参数不合法",
                        f"解压源包位于目标目录内且归档成员会覆盖源包自身: {成员.filename}",
                        来源="文件系统")
                # 成员是文件、目标位置却是调用方既有目录：落盘口径会把整棵目录树
                # 换成单文件（旧实现搬备份 → 原子替换 → 成功后连备份目录一起删 =
                # 静默毁树且返回成功，属数据丢失）。目录不是「可被覆盖的文件」，
                # 与 压缩文件 同一口径 fail-closed 拒绝（在落盘之前拦下，零改动）。
                if not 成员.is_dir() and 目标.is_dir():
                    return 结果.失败(
                        "参数不合法",
                        f"归档成员是文件但目标位置是既有目录，解压不会用文件覆盖"
                        f"整棵目录树: {成员.filename}",
                        来源="文件系统")
                计划列表.append((成员, 目标))
            if not 目标根.exists():
                目标根.mkdir(parents=True)
                新建目标目录 = True
            写入总字节 = 0
            for 成员, 目标 in 计划列表:
                if 成员.is_dir():
                    建目录并登记(目标)
                    continue
                if 目标.parent != 目标根:
                    建目录并登记(目标.parent)
                本次字节 = 0
                已存在 = 目标.is_symlink() or 目标.exists()
                已有目标文件 = 已存在 and not 目标.is_dir()
                if 已存在:
                    备份既有目标(目标)   # 先搬走调用方既有内容，绝不原地截断
                # 新文件写同目录临时件再原子落位（口径同 本包 原子写入）：
                # 落盘中途失败不会有半截正式产物，回滚只删登记过的临时件。
                落盘中转件 = 目标.parent / f".__解压_{len(已写文件列表)}_{目标.name}.tmp"
                已写文件列表.append(落盘中转件)
                with 压缩包.open(成员, "r") as 读入:
                    with open(落盘中转件, "wb") as 写出:
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
                os.replace(str(落盘中转件), str(目标))
                已写文件列表.remove(落盘中转件)
                if not 已有目标文件:
                    已写文件列表.append(目标)   # 本次新建的文件：回滚只删这些
                写入总字节 += 本次字节
        解压结果: dict = {"目标目录": 目标目录, "条目数": len(成员列表)}
        解压标注 = 放行标注(目标目录)
        if 解压标注:
            解压结果["危险路径放行"] = 解压标注
        if 临时备份目录 is not None:
            清只读后删除树(临时备份目录, 忽略失败=真)  # 成功：备份盘随用随删
        return 结果.成功结果(解压结果)
    except _超过上限 as 错误:
        _清理解压落盘中转件(目标根, 新建目标目录, 已有文件备份表,
                        已写文件列表, 已建目录列表)
        return 结果.失败("超过解压上限", str(错误), 来源="文件系统")
    except Exception as 错误:
        还原成功 = _清理解压落盘中转件(目标根, 新建目标目录, 已有文件备份表,
                                   已写文件列表, 已建目录列表)
        提示 = "" if 还原成功 else "（被覆盖的既有文件未能全部还原，备份保留在目标目录下 .__解压备份_* 内）"
        return 结果.失败("解压失败", f"{错误}{提示}", 来源="文件系统")


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
