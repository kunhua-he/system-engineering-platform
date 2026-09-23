"""只读属性目录树删除（**同一件事的唯一实现**，哲学第 8 条唯一性判定②）。

平台差异**不做平台名判断**，只用能力探测（`os.access(父, os.W_OK)`）与
`os.chmod(..., stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)` —— 一份实现跨平台。"""

from __future__ import annotations

import inspect
import os
import shutil
import stat
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 假
from 公共契约.诊断.忽略记录 import 记录忽略


# ── 只读属性目录树删除（**同一件事的唯一实现**，哲学第 8 条唯一性判定②）──────
#
# 起因（2026-09-19 H 路收口）：POSIX 上父目录无写位（如 `0o555` 的中间目录）时，
# `shutil.rmtree` / `shutil.move` 会抛 `PermissionError`；Windows 上只读属性
# （`pip` 自带 license 文件就是）同样阻断删除。此前**每个调用点各写一份兜底**，
# 或干脆不写 —— 前者是第二份实现（哲学第 1.2 条），后者把失败留给用户。
#
# 本节的三个原语是**全仓唯一实现**：调用点一律改走它们，不许自带 `try/except chmod`
# 分叉。平台差异**不做平台名判断**，只用能力探测（`os.access(父, os.W_OK)`）与
# `os.chmod(..., stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)` —— 后者在 POSIX
# 上同样合法（清掉只读位不改变可删除性），故一份实现跨平台。

#: `清只读后删除树` 的留痕位置前缀（`记录忽略` 的位置串以它为根，供查询与门禁识别）
清只读删除留痕前缀 = "平台适配.清只读后删除树"


def 清除只读属性(路径: str | Path) -> None:
    """清掉路径（文件或目录）的只读属性；失败**原样报错**，不降级。

    **为什么需要它**：Windows 上 `venv` 建出来的环境里，`pip` 自带的 license
    文件（`Lib/site-packages/pip-*.dist-info/licenses/**`）带**只读属性**，
    `shutil.rmtree` 内部的 `os.unlink` 会抛 `PermissionError`（POSIX 上同样的文件
    能直接删，所以这是平台差异）。

    **一份实现跨平台**：`os.chmod(路径, stat.S_IWRITE)` 在 POSIX 上同样合法
    （清掉只读位不改变可删除性），因此本函数**不含任何平台判断**。
    """
    try:
        os.chmod(路径, stat.S_IWRITE)
    except OSError as 错误:
        raise OSError(f"清除只读属性失败（{路径}）: {错误}") from 错误


def _确保目录可写(目录: Path) -> None:
    """让**目录**可读可写可执行（在其中增/删/改名条目都需要）；已齐备则不动。

    目录得同时可读可执行才谈得上遍历条目，不能只加写位 —— 这就是本函数与
    `清除只读属性`（对单个条目只清只读位）分开的原因。

    **守卫必须三查（2026-09-23 实测缺陷收口）**：原实现只查 `os.W_OK`，而
    `清除只读属性` 会把权限写成**恰好** `0o200`（`os.chmod(路径, stat.S_IWRITE)`
    是赋值不是按位加）—— 那时 `W_OK` 为真、`R_OK`/`X_OK` 全假，守卫判定「已可写、
    不必动」，于是**只写不可读的目录**被当成正常状态留在那里：`os.open` 打不开、
    条目遍历不了，删树在下一步照样失败（实测：`chmod 000` 的目录 ⇒ `0o200` ⇒ 删不掉）。
    按目录的**全部三项**判，才能同时接住「本来只读」与「被上一步写成只写」两种形态。
    """
    if not (os.access(目录, os.W_OK) and os.access(目录, os.R_OK)
            and os.access(目录, os.X_OK)):
        os.chmod(目录, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)


def 确保可删(路径: str | Path) -> None:
    """让「删除 路径」这件事可做：清掉路径自身的只读位，并确保**父目录可写**。

    两件事都需要，缺一不可：

    - **路径自身只读**（Windows 只读属性 / POSIX 无写位）→ `os.unlink` 拒绝；
    - **父目录不可写**（POSIX 删除条目要求父目录有写位，`0o555` 的目录就删不掉
      里面的东西）→ `os.unlink`/`os.rmdir` 同样拒绝。

    **目标是目录时走 `_确保目录可写`、不能走 `清除只读属性`**（2026-09-23 实测缺陷收口）：
    `清除只读属性` 做的是 `os.chmod(路径, stat.S_IWRITE)` —— 对**文件**正合适
    （只读位是唯一障碍），对**目录**却会把读/执行位一起抹掉（权限变成恰好 `0o200`），
    而目录没有读/执行位就连遍历与打开都做不到 ⇒ 「清只读」这一步反而**制造**了
    下一次 `PermissionError`。删树钩子传进来的正是「刚才失败的那个路径」，它可能
    是文件、也可能是目录，故这里按类型分流（目录要的是 R+W+X，不是只剩 W）。

    平台差异用**能力探测**（`os.access(父, os.W_OK)`）而不是平台名判断，
    所以一份实现跨平台、调用点无分叉。
    """
    目标 = Path(路径)
    父目录 = 目标.parent
    if 父目录 != 目标:
        _确保目录可写(父目录)
    if 目标.is_dir():
        _确保目录可写(目标)
    else:
        清除只读属性(目标)


def 移动并可删(源: str | Path, 目标: str | Path) -> None:
    """把 源 移动到 目标；只读属性/父目录无写位造成的 `PermissionError` 时先清只读再重试。

    **为什么需要它（`shutil.move` 与删除不是同一件事）**：改名要的是**源与落点的父目录**
    有写位，而不是「源文件自身可写」；所以这里**不清源文件自身的只读位**（对文件做
    `os.chmod(路径, stat.S_IWRITE)` 会把它的读/执行位一起抹掉，移动后权限被改，
    远超「修权限」的本意）。落点若已存在且只读（Windows 上 `MoveFileEx` 拒绝覆盖
    只读目标），则清它的只读位——它本来就要被替换掉。

    语义与 `清只读后删除树` 同款：默认**失败原样抛 `OSError`**（点名源与落点），
    不返回布尔、不吞异常；只在第一次真的抛 `PermissionError` 时才做上面两件事并重试一次。
    """
    源路径 = Path(源)
    目标路径 = Path(目标)
    落点 = (目标路径 / 源路径.name) if 目标路径.is_dir() else 目标路径

    try:
        shutil.move(str(源路径), str(目标路径))
        return
    except PermissionError as 首次错误:
        try:
            _确保目录可写(源路径.parent)
            _确保目录可写(落点.parent)
            if 落点.exists() and 落点.is_file():
                清除只读属性(落点)
            shutil.move(str(源路径), str(目标路径))
        except OSError as 重试错误:
            raise OSError(
                f"清只读后重试移动仍失败（{源路径} → {落点}）: {重试错误}") from 重试错误
        return
    except OSError as 错误:
        raise OSError(f"移动失败（{源路径} → {落点}）: {错误}") from 错误


def _需要flags(函数) -> bool:
    """该函数是否**必须**带 `flags` 才能调用（`os.open` 是唯一一个两参的）。

    判据取自函数自身的签名（`inspect.signature` 数**无默认值的必需位置参数**），
    不硬编函数名：`shutil` 内部把哪个函数交给钩子是它的事，按签名转发才是重放语义。
    签名取不到（内建/包装器）时按 `False` 处理 —— 一参调用是绝大多数情况，
    且真取不到时后续 `TypeError` 仍会如实冒出来（不静默错删）。
    """
    try:
        参 = inspect.signature(函数).parameters.values()
    except (TypeError, ValueError):
        return False
    return len([项 for 项 in 参
                if 项.kind in (项.POSITIONAL_ONLY, 项.POSITIONAL_OR_KEYWORD)
                and 项.default is 项.empty]) >= 2


def 清只读并确保可删(路径: str | Path) -> None:
    """让「删除 路径」可做（唯一实现的**薄别名**，语义与 `确保可删` 逐字相同）。

    存在的理由：`开发文档/未完成事项.md` 登记本项债务时把补口函数名写成
    `清只读并确保可删(路径) -> None`。为免「文档里的名字在实现里查不到」，
    这里按最小接口把它作为**别名**列出 —— 同一份实现，不是第二条腿。
    """
    确保可删(路径)


def _归一树权限(目录: Path) -> None:
    """把整棵树的权限归一成「可删」（自底向上：目录 R+W+X、文件非只读）。

    **为什么必须有这一轮**（2026-09-23 实测缺陷收口）：`rmtree` 的 `onexc` 钩子语义是
    「这次失败由你处理」——钩子返回后 `rmtree` **不会重试那一步，而是放弃整个子树继续走**。
    于是「目录自身不可读」时：钩子把权限改对了，`rmtree` 却早已跳过它并**正常返回**，
    结果函数报告成功、树还在（实测形状：`chmod 000` 的目录 ⇒ 返回无异常，
    `os.walk` 仍能列出全部条目）。**回调修权限 ≠ 调用方重试**，两者必须都做。

    自底向上（`topdown=False`）：先把最底层目录弄成可读，父层才走得到（否则
    `os.walk` 在不可读的父层上什么都列不出来）。
    入口先修顶目录本身 —— `os.walk` 对打不开的目录是**静默跳过**，不先修就一个条目都遍历不到。
    """
    _确保目录可写(目录)
    for 根, 子目录表, 文件表 in os.walk(目录, topdown=False):
        for 名 in 文件表:
            try:
                清除只读属性(Path(根) / 名)
            except OSError:
                pass          # 单个条目清不掉不在此处中断：留给紧随其后的 rmtree 如实报错
        for 名 in 子目录表:
            try:
                _确保目录可写(Path(根) / 名)
            except OSError:
                pass


def 清只读后删除树(目录: Path, *, 忽略失败: bool = 假) -> None:
    """删除目录树；遇只读属性造成的 `PermissionError` 时先清只读再重试删除。

    判定依据不靠注释靠真实副作用：钩子只在 `rmtree` **真的**抛 `PermissionError`
    时才动。POSIX 上通常不触发（同样的文件在 POSIX 上能直接删），Windows 上由
    `os.unlink`/`os.rmdir` 触发，正是要修的那条路径。

    语义：

    - ``忽略失败=假``（默认）：清只读后仍失败就**原样抛出**，错误说明点名路径与原因
      —— 不许宽 `except` 吞错。
    - ``忽略失败=真``：逐条经 `记录忽略` 留痕（可查询），并**额外检查目录是否真的删干净**；
      残留同样留痕。这修掉了原先 `rmtree(..., ignore_errors=True)` 的缺陷：
      它**连残留都不留痕**，事后无法判断「本来就没东西」还是「删失败了」。
    """
    目录 = Path(目录)

    def _清只读后重试(函数, 路径, 异常) -> None:
        """rmtree 的 onexc 钩子：非 PermissionError 不越权处理，其余先清只读再重试。

        **`函数` 可能是 `os.open`，重放时必须带上 `flags`**（2026-09-23 实测缺陷收口）：
        `rmtree` 在「打开目录本身失败」这条路上把 `os.open` 原样交给钩子，而
        `os.open(path, flags)` 是**两参**函数 ⇒ 只传 `路径` 会抛
        `TypeError: open() missing required argument 'flags' (pos 2)`。
        原实现写死 `函数(路径)`，只对 `os.unlink` / `os.rmdir` / `os.lstat`（都是一参）
        成立 —— 于是「目录自身不可读」（如 `chmod 000`）这条路径上，本该「清只读位再
        重试」的动作变成抛 `TypeError`；更糟的是 **`TypeError` 不是 `OSError`**，
        下面 `except OSError` 接不住，直接冒到调用方（实测复现：`chmod 000` 的目录
        调用本函数 ⇒ 上述原文异常，目录仍在、一个字节都没删）。

        重放口径：**按函数自身签名转发**（`inspect.signature` 数必需位置参数），
        不按函数名写分支 —— 钩子的契约是「重放原来那一步」，参数表由被重放的函数说了算；
        按函数名硬编一张表等于在本层再抄一份 `shutil` 的调用约定（哲学 1.2）。
        """
        if not isinstance(异常, PermissionError):
            if 忽略失败:
                记录忽略(清只读删除留痕前缀, 异常)
                return
            raise 异常
        try:
            确保可删(路径)
            # `os.open(path, flags)` 需要 flags；`os.open` 用 `O_RDONLY` 复现 rmtree 的
            # 「只读地打开目录」这一步（rmtree 自己也是这么开的）。其余函数（一参）原样转发。
            if _需要flags(函数):
                结果 = 函数(路径, os.O_RDONLY)
            else:
                结果 = 函数(路径)
            if 函数 is os.scandir and 结果 is not None:
                结果.close()  # 官方配方会漏关的迭代器，这里显式关掉
        except OSError as 重试错误:
            if 忽略失败:
                记录忽略(清只读删除留痕前缀 + ".重试", 重试错误)
                return
            raise OSError(f"清只读后重试删除仍失败（{路径}）: {重试错误}") from 重试错误

    def _记残留() -> None:
        """目录仍在就留痕（**所有出口都要走到这里**，含「先抛后忽略」的失败路径）。

        为什么做成局部函数而不是末尾一句 if：本函数有多条出口（首次 rmtree 抛错、
        重试再抛错、重试没抛但没删净），早先写成「某条出口 return 掉」会让那条路上的
        残留**连痕都没有**——那正是本函数要修的 `ignore_errors=True` 老缺陷的翻版
        （实测：改完漏了一处 return，`测试_清只读删除与落盘跨平台.忽略失败为真时残留要留痕` 判红）。
        """
        if 忽略失败 and 目录.exists():
            记录忽略(清只读删除留痕前缀 + ".残留",
                     f"删除流程已返回但目录仍在（有内容未删净）: {目录}")

    try:
        shutil.rmtree(目录, onexc=_清只读后重试)
    except OSError as 错误:
        if not 忽略失败:
            raise
        记录忽略(清只读删除留痕前缀, 错误)
    else:
        if 目录.exists():
            # 走到这里说明 rmtree **没抛异常**却留下了东西：钩子改完权限后 rmtree 不重试
            # 那一步（见 `_归一树权限` 的说明）。此时把权限归一后**再删一次**才叫「删树」；
            # 第二次仍删不掉就如实抛 OSError —— 「目录还在」绝不允许静默当成成功。
            _归一树权限(目录)
            二次失败: OSError | None = None
            try:
                shutil.rmtree(目录)
            except OSError as 错误:
                二次失败 = 错误
            if 二次失败 is not None:
                if not 忽略失败:
                    raise OSError(
                        f"清只读后仍未能删净（{目录}）: {二次失败}") from 二次失败
                记录忽略(清只读删除留痕前缀, 二次失败)
            elif 目录.exists() and not 忽略失败:
                raise OSError(f"清只读后仍未能删净（{目录}）：目录仍在")
    _记残留()
