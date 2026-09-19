"""受控文件读写面：路径边界、符号链接拒绝与无跟随的受控读写/复制（构建平台客户端拆分件）。

2026-09-19 从 `客户端/构建平台客户端.py` 原样搬出（对外零变化）：成员名、签名、默认值、
注释与文档串与拆分前**逐字一致**，只搬位置；冻结基线 `/tmp/拆分基线/构建平台客户端.py`
（sha256 前16 = `a632e3398f121f5b`，对应提交 a5e9dcc1）。

**入口仍是 `客户端/构建平台客户端.py`**：本模块不对外，入口模块按名回导本模块的全部成员
（`客户端构建错误` + 十四个 `_` 前缀原语），`构建模块.<名>` 与拆分前是**同一对象** ——
测试的 `mock.patch.object(构建模块, "_解析受控源文件", …)` / `构建模块._受控目标路径`
在**入口模块内**的调用点（`复制并重写` / `复制非Py文件`）因此照旧生效。

职责边界（**不要在这里加第二套实现**）：

- 本模块 = 「构建器怎么**安全地碰文件系统**」的唯一落点：源根必须存在且是真目录、源文件
  是否越界、目标路径是否越界、目录链是否被符号链接替换（`dir_fd` 逐级无跟随）、写目标是否
  原子替换。判据只有一条：**任何一步都不跟随链接、不越过允许根**。
- 平台判断在 `公共契约/运行时/平台适配.py`（本模块不含任何 `sys.platform` 判断）；
  POSIX 专有的 `dir_fd=` 系列参数可用性由入口模块的 `脚本入口准入` 把关，本模块只如实使用。
- 制品目录口径（摘要怎么算、哪些文件算正式文件）在 `平台控制面/包仓库/制品布局.py`；
  本模块**不**参与制品身份计算（见 `客户端/制品生成与自校验.py`）。
- 构建配置常量（`顶层包表` / `客户端前缀` / 三个目录）**留在入口模块**：它们是
  `mock.patch.multiple(构建模块, 顶层包表=…)` 的打补丁目标，本模块不持第二份。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class 客户端构建错误(RuntimeError):
    """客户端构建遇到不可安全恢复的问题。"""


def _拒绝符号链接(根: Path, 阶段: str) -> None:
    """拒绝根及其全部后代中的符号链接；目录链接也不得静默跳过。"""
    根 = Path(根)
    if 根.is_symlink():
        raise 客户端构建错误(f"{阶段}发现符号链接: {根}")
    if not 根.exists():
        return
    for 路径 in 根.rglob("*"):
        if 路径.is_symlink():
            raise 客户端构建错误(f"{阶段}发现符号链接: {路径}")


def _解析源码根(源根: Path) -> Path:
    """返回真实源码根；源码根必须是存在的普通目录。"""
    源根 = Path(源根)
    if 源根.is_symlink():
        raise 客户端构建错误(f"源码根是符号链接: {源根}")
    try:
        真实根 = 源根.resolve(strict=True)
    except OSError as 错误:
        raise 客户端构建错误(f"源码根无法解析: {源根}: {错误}") from 错误
    if not 真实根.is_dir():
        raise 客户端构建错误(f"源码根不是目录: {源根}")
    return 真实根


def _解析受控源文件(文件: Path, 源根: Path, 真实源根: Path) -> Path:
    """逐文件解析并确认真实位置仍位于允许源码根。"""
    if 文件.is_symlink():
        raise 客户端构建错误(f"源文件是符号链接: {文件}")
    try:
        真实文件 = 文件.resolve(strict=True)
        真实文件.relative_to(真实源根)
    except (OSError, ValueError) as 错误:
        raise 客户端构建错误(f"源文件越过允许源码根 {源根}: {文件}") from 错误
    if not 真实文件.is_file():
        raise 客户端构建错误(f"源路径不是普通文件: {文件}")
    return 真实文件


def _准备目标根(目标根: Path) -> Path:
    """创建普通目标根并返回其真实路径。"""
    目标根 = Path(目标根)
    if 目标根.is_symlink():
        raise 客户端构建错误(f"目标根是符号链接: {目标根}")
    _拒绝符号链接(目标根, "复制前目标检查")
    目标根.mkdir(parents=True, exist_ok=True)
    if 目标根.is_symlink():
        raise 客户端构建错误(f"目标根是符号链接: {目标根}")
    return 目标根.resolve(strict=True)


def _受控目标路径(目标根: Path, 真实目标根: Path, 相对: Path) -> Path:
    """生成不得越过目标根的目标路径，并拒绝既有链接祖先。"""
    if 相对.is_absolute() or ".." in 相对.parts:
        raise 客户端构建错误(f"目标相对路径非法: {相对}")
    目标 = 目标根 / 相对
    try:
        目标.resolve(strict=False).relative_to(真实目标根)
    except ValueError as 错误:
        raise 客户端构建错误(f"目标路径越界: {目标}") from 错误
    当前 = 目标.parent
    while 当前 != 目标根 and 当前 != 当前.parent:
        if 当前.is_symlink():
            raise 客户端构建错误(f"目标路径包含符号链接: {当前}")
        当前 = 当前.parent
    return 目标


_目录打开标志 = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_文件无跟随标志 = getattr(os, "O_NOFOLLOW", 0)


def _打开根目录(根: Path, 用途: str) -> int:
    """以不跟随链接方式打开根目录，返回调用者负责关闭的目录描述符。"""
    try:
        return os.open(根, _目录打开标志)
    except OSError as 错误:
        raise 客户端构建错误(f"{用途}根目录无法安全打开: {根}: {错误}") from 错误


def _打开目录链(根描述符: int, 部件表: tuple[str, ...], 创建: bool) -> int:
    """从已锚定根描述符逐级无跟随打开目录，杜绝祖先目录链接竞态。"""
    当前 = os.dup(根描述符)
    try:
        for 部件 in 部件表:
            if not 部件 or 部件 in {".", ".."} or "/" in 部件:
                raise 客户端构建错误(f"目录部件非法: {部件}")
            if 创建:
                try:
                    os.mkdir(部件, mode=0o755, dir_fd=当前)
                except FileExistsError:
                    pass
            下一层 = os.open(部件, _目录打开标志, dir_fd=当前)
            os.close(当前)
            当前 = 下一层
        return 当前
    except Exception:
        os.close(当前)
        raise


def _读取受控文件(根描述符: int, 显示根: Path, 相对: Path) -> tuple[bytes, int]:
    """从锚定源码根无跟随读取普通文件，返回内容与权限位。"""
    路径 = 显示根 / 相对
    父描述符 = -1
    文件描述符 = -1
    try:
        父描述符 = _打开目录链(根描述符, tuple(相对.parts[:-1]), 创建=False)
        文件描述符 = os.open(
            相对.name, os.O_RDONLY | _文件无跟随标志, dir_fd=父描述符)
        状态 = os.fstat(文件描述符)
        if not stat.S_ISREG(状态.st_mode):
            raise 客户端构建错误(f"源路径不是普通文件: {路径}")
        数据块表: list[bytes] = []
        while True:
            数据块 = os.read(文件描述符, 1024 * 1024)
            if not 数据块:
                break
            数据块表.append(数据块)
        return b"".join(数据块表), stat.S_IMODE(状态.st_mode)
    except OSError as 错误:
        raise 客户端构建错误(f"读取受控源文件失败: {路径}: {错误}") from 错误
    finally:
        if 文件描述符 >= 0:
            os.close(文件描述符)
        if 父描述符 >= 0:
            os.close(父描述符)


def _写入受控目标(
    根描述符: int, 显示根: Path, 相对: Path, 数据: bytes, 权限位: int = 0o644
) -> None:
    """经锚定目标根写临时普通文件并原子替换，不跟随目标或祖先链接。"""
    路径 = 显示根 / 相对
    父描述符 = -1
    临时描述符 = -1
    临时名 = f".{相对.name}.构建中-{os.urandom(8).hex()}"
    try:
        父描述符 = _打开目录链(根描述符, tuple(相对.parts[:-1]), 创建=True)
        try:
            既有状态 = os.stat(相对.name, dir_fd=父描述符, follow_symlinks=False)
        except FileNotFoundError:
            既有状态 = None
        if 既有状态 is not None and stat.S_ISLNK(既有状态.st_mode):
            raise 客户端构建错误(f"目标文件是符号链接: {路径}")
        临时描述符 = os.open(
            临时名,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _文件无跟随标志,
            权限位,
            dir_fd=父描述符,
        )
        os.fchmod(临时描述符, 权限位)
        视图 = memoryview(数据)
        while 视图:
            已写 = os.write(临时描述符, 视图)
            视图 = 视图[已写:]
        os.fsync(临时描述符)
        os.close(临时描述符)
        临时描述符 = -1
        os.replace(
            临时名, 相对.name, src_dir_fd=父描述符, dst_dir_fd=父描述符)
    except OSError as 错误:
        raise 客户端构建错误(f"写入受控目标失败: {路径}: {错误}") from 错误
    finally:
        if 临时描述符 >= 0:
            os.close(临时描述符)
        if 父描述符 >= 0:
            try:
                os.unlink(临时名, dir_fd=父描述符)
            except FileNotFoundError:
                pass
            os.close(父描述符)


def _创建受控目标目录(根描述符: int, 显示根: Path, 相对: Path) -> None:
    """经锚定目标根创建目录链。"""
    try:
        描述符 = _打开目录链(根描述符, tuple(相对.parts), 创建=True)
    except OSError as 错误:
        raise 客户端构建错误(
            f"创建受控目标目录失败: {显示根 / 相对}: {错误}") from 错误
    else:
        os.close(描述符)


def _安全复制目录树(源根: Path, 目标根: Path) -> None:
    """不跟随链接地复制完整目录树，逐文件执行源/目标边界校验。"""
    源根 = Path(源根)
    目标根 = Path(目标根)
    _拒绝符号链接(源根, "目录复制前源码检查")
    真实源根 = _解析源码根(源根)
    真实目标根 = _准备目标根(目标根)
    源描述符 = _打开根目录(源根, "目录复制源码")
    目标描述符 = _打开根目录(目标根, "目录复制目标")
    try:
        for 路径 in sorted(源根.rglob("*")):
            if 路径.is_symlink():
                raise 客户端构建错误(f"目录复制发现符号链接: {路径}")
            相对 = 路径.relative_to(源根)
            _受控目标路径(目标根, 真实目标根, 相对)
            if 路径.is_dir():
                _创建受控目标目录(目标描述符, 目标根, 相对)
                continue
            _解析受控源文件(路径, 源根, 真实源根)
            数据, 权限位 = _读取受控文件(源描述符, 源根, 相对)
            _写入受控目标(目标描述符, 目标根, 相对, 数据, 权限位)
    finally:
        os.close(源描述符)
        os.close(目标描述符)
    _拒绝符号链接(源根, "目录复制后源码检查")
    _拒绝符号链接(目标根, "目录复制后目标检查")
