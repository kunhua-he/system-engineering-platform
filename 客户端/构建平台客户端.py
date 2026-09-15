"""平台客户端构建脚本：把平台源码树打包为唯一前缀 平台客户端 制品。

规则：
- 复制平台正式目录（公共契约/支持库/模块库/运行核心/前端核心/后端核心/
  项目适配层/平台控制面/启动监督器/开发工具）到 平台客户端/ 前缀下。
- 用 AST 重写顶层导入：from 公共契约.X → from 平台客户端.公共契约.X；
  import 公共契约 → import 平台客户端.公共契约（避免与外部调用方同名 namespace 冲突）。
- 构建 wheel 到 工程缓存/平台客户端制品/，并安装到 工程缓存/平台客户端环境/
  （内容寻址不可变制品，外部调用方只绑定已安装制品，不拼接平台源码树）。

用法：python3.14 客户端/构建平台客户端.py [--安装]
"""

from __future__ import annotations

import ast
import json
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

系统根 = Path(__file__).resolve().parent.parent
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
顶层包表 = ["公共契约", "支持库", "模块库", "技能库", "运行核心", "前端核心", "后端核心",
           "项目适配层", "平台控制面", "启动监督器", "开发工具"]
客户端前缀 = "平台客户端"
构建目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端构建"
# 制品仓库 是发布门禁认可的不可变制品目录（门禁豁免其内构建产物）
制品目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端制品"
环境目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端环境"


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


def _异常行号(错误: BaseException, 树: ast.AST | None = None) -> int:
    """为 AST 解析/反解析失败提供稳定、非零的源码行号。"""
    行号 = getattr(错误, "lineno", None)
    if isinstance(行号, int) and 行号 > 0:
        return 行号
    if 树 is not None:
        for 节点 in ast.walk(树):
            节点行号 = getattr(节点, "lineno", None)
            if isinstance(节点行号, int) and 节点行号 > 0:
                return 节点行号
    return 1


class 导入重写器(ast.NodeTransformer):
    """把顶层平台导入改写为 平台客户端. 前缀（from/import 两种形态）。"""

    def __init__(self, 顶层包表: list[str], 前缀: str) -> None:
        self.顶层包表 = tuple(顶层包表)
        self.前缀 = 前缀
        self.改写数 = 0

    def _改写模块名(self, 模块名: str) -> str:
        if 模块名 == "__future__" or not 模块名:
            return 模块名
        顶层 = 模块名.split(".")[0]
        if 顶层 in self.顶层包表:
            self.改写数 += 1
            return f"{self.前缀}.{模块名}"
        return 模块名

    def visit_Import(self, 节点: ast.Import) -> ast.Import:
        for 别名 in 节点.names:
            别名.name = self._改写模块名(别名.name)
        return 节点

    def visit_ImportFrom(self, 节点: ast.ImportFrom) -> ast.ImportFrom:
        if 节点.module:
            节点.module = self._改写模块名(节点.module)
        return 节点


def 复制并重写(源根: Path, 目标根: Path) -> int:
    """安全复制 Python 源码并重写导入；任一 AST 失败立即阻断。"""
    源根 = Path(源根)
    目标根 = Path(目标根)
    _拒绝符号链接(源根, "复制前源码检查")
    真实源根 = _解析源码根(源根)
    真实目标根 = _准备目标根(目标根)
    源描述符 = _打开根目录(源根, "Python源码")
    目标描述符 = _打开根目录(目标根, "Python目标")
    总数 = 0
    try:
        for 文件 in sorted(源根.rglob("*.py")):
            相对 = 文件.relative_to(源根)
            if "__pycache__" in 相对.parts:
                continue
            _解析受控源文件(文件, 源根, 真实源根)
            _受控目标路径(目标根, 真实目标根, 相对)
            原始字节, 权限位 = _读取受控文件(源描述符, 源根, 相对)
            内容 = 原始字节.decode("utf-8")
            try:
                树 = ast.parse(内容, filename=str(文件))
            except Exception as 错误:
                行号 = _异常行号(错误)
                详情 = 错误.msg if isinstance(错误, SyntaxError) else str(错误)
                raise 客户端构建错误(
                    f"Python AST解析失败: {文件}:{行号}: {详情}") from 错误
            重写器 = 导入重写器(顶层包表, 客户端前缀)
            新树 = 重写器.visit(树)
            总数 += 重写器.改写数
            try:
                新内容 = ast.unparse(新树)
            except Exception as 错误:
                行号 = _异常行号(错误, 新树)
                raise 客户端构建错误(
                    f"Python AST反解析失败: {文件}:{行号}: {错误}") from 错误
            _写入受控目标(
                目标描述符, 目标根, 相对, 新内容.encode("utf-8"), 权限位)
    finally:
        os.close(源描述符)
        os.close(目标描述符)
    _拒绝符号链接(源根, "复制后源码检查")
    _拒绝符号链接(目标根, "复制后目标检查")
    return 总数


def 复制非Py文件(源根: Path, 目标根: Path) -> None:
    """安全复制非 Python 资源；逐文件校验源码根与目标边界。"""
    源根 = Path(源根)
    目标根 = Path(目标根)
    _拒绝符号链接(源根, "复制前资源检查")
    真实源根 = _解析源码根(源根)
    真实目标根 = _准备目标根(目标根)
    源描述符 = _打开根目录(源根, "资源源码")
    目标描述符 = _打开根目录(目标根, "资源目标")
    try:
        for 文件 in sorted(源根.rglob("*")):
            if 文件.is_symlink():
                raise 客户端构建错误(f"源资源是符号链接: {文件}")
            if 文件.is_dir():
                continue
            相对 = 文件.relative_to(源根)
            if "__pycache__" in 相对.parts:
                continue
            if "工程缓存" in 相对.parts:
                continue
            if 相对.suffix == ".py":
                continue
            是夹具 = any(部分 in {"夹具", "验证夹具"} for 部分 in 相对.parts)
            if 相对.suffix.lower() in {".db", ".sqlite", ".sqlite3"} and not 是夹具:
                continue
            if 相对.suffix.lower() in {".log", ".tmp", ".pyc"}:
                continue
            _解析受控源文件(文件, 源根, 真实源根)
            _受控目标路径(目标根, 真实目标根, 相对)
            数据, 权限位 = _读取受控文件(源描述符, 源根, 相对)
            _写入受控目标(目标描述符, 目标根, 相对, 数据, 权限位)
    finally:
        os.close(源描述符)
        os.close(目标描述符)
    _拒绝符号链接(源根, "复制后资源检查")
    _拒绝符号链接(目标根, "复制后目标检查")


def 生成入口(客户端根: Path) -> None:
    """生成 平台客户端/__init__.py：公开模块能力门面。"""
    内容 = (
        '"""平台客户端（系统工程平台稳定客户端）：唯一前缀制品包。\n'
        "外部调用方正式代码只经本客户端调用模块公开能力，禁止拼接平台源码树。\n"
        "用法：from 平台客户端.模块库.文档解析 import 解析文档\n"
        "\n"
        "本包由 客户端/构建平台客户端.py 生成，禁止手工编辑。\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "# 注册平台唯一能力调用服务的惰性装配钩子（模块首次调用时自动装配）\n"
        "import 平台客户端.运行核心.能力调用.唯一能力调用 as _唯一调用  # noqa: F401\n"
        "\n"
        "__all__: list[str] = []\n"
    )
    客户端根 = Path(客户端根)
    真实根 = _准备目标根(客户端根)
    相对 = Path("__init__.py")
    _受控目标路径(客户端根, 真实根, 相对)
    根描述符 = _打开根目录(客户端根, "客户端入口目标")
    try:
        _写入受控目标(根描述符, 客户端根, 相对, 内容.encode("utf-8"))
    finally:
        os.close(根描述符)


def 生成可运行制品壳(制品根: Path) -> None:
    """调用统一编译器模板生成平台客户端页面与运行入口。"""
    from 开发工具.项目编译.项目编译器 import _生成HTML, _生成启动器, _写入并编译Python
    页面目录 = 制品根 / "前端" / "编译页面"
    页面目录.mkdir(parents=True, exist_ok=True)
    页面 = {"页面id": "主页", "标题": "系统工程平台客户端", "路由": "/", "组件列表": []}
    (页面目录 / "index.html").write_text(_生成HTML(页面), encoding="utf-8")
    (页面目录 / "路由表.json").write_text(
        json.dumps({"/": "index.html"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    入口目录 = 制品根 / "运行入口"
    入口目录.mkdir(parents=True, exist_ok=True)
    _写入并编译Python(
        入口目录 / "启动.py", _生成启动器("系统工程平台客户端", 包前缀=客户端前缀))
    (入口目录 / "__init__.py").write_text('"""平台客户端运行入口。"""\n', encoding="utf-8")


def 计算制品摘要(客户端根: Path) -> str:
    """内容寻址：拒绝链接后对全部正式普通文件计算 sha256 摘要。"""
    客户端根 = Path(客户端根)
    _拒绝符号链接(客户端根, "摘要前检查")
    真实根 = _解析源码根(客户端根)
    根描述符 = _打开根目录(客户端根, "摘要源码")
    哈希 = hashlib.sha256()
    try:
        for 文件 in sorted(客户端根.rglob("*")):
            if 文件.is_symlink():
                raise 客户端构建错误(f"摘要阶段发现符号链接: {文件}")
            if 文件.is_dir():
                continue
            相对 = 文件.relative_to(客户端根)
            if "__pycache__" in 相对.parts or "工程缓存" in 相对.parts:
                continue
            是夹具 = any(部分 in {"夹具", "验证夹具"} for 部分 in 相对.parts)
            if 相对.suffix.lower() in {".db", ".sqlite", ".sqlite3"} and not 是夹具:
                continue
            if 相对.suffix.lower() in {".log", ".tmp", ".pyc"}:
                continue
            _解析受控源文件(文件, 客户端根, 真实根)
            数据, _ = _读取受控文件(根描述符, 客户端根, 相对)
            哈希.update(str(相对).encode("utf-8"))
            哈希.update(数据)
    finally:
        os.close(根描述符)
    _拒绝符号链接(客户端根, "摘要后检查")
    return 哈希.hexdigest()


def 生成来源元数据(制品根: Path) -> None:
    """生成发布门禁消费的唯一来源绑定、编译清单与全文件摘要。"""
    from 开发工具.项目编译.项目编译器 import 读取工作区字节指纹, _制品文件摘要
    来源 = 读取工作区字节指纹()
    (制品根 / "制品来源.json").write_text(json.dumps({
        "格式": "平台客户端制品来源绑定", "编译器版本": "平台客户端构建器/1.0.0",
        "项目id": "平台客户端", **来源,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (制品根 / "编译清单.json").write_text(json.dumps({
        "制品类型": "平台客户端", "编译器版本": "平台客户端构建器/1.0.0",
        "项目id": "平台客户端", "来源提交": 来源["提交"],
        "来源工作区字节指纹": 来源["工作区字节指纹"],
        "来源工作区状态": 来源["工作区状态"],
        "来源绑定文件": "制品来源.json", "制品摘要文件": "制品完整性摘要.json",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (制品根 / "制品完整性摘要.json").write_text(
        json.dumps(_制品文件摘要(制品根), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def 清理过期制品(仓库根: Path, 当前摘要: str, 当前身份: str) -> None:
    """只留当前制品：过期就删（内容寻址目录/身份目录/信任链历史各留一份）。

    为什么放进构建脚本：每次重编都会落一份新制品（约 30MB），不自动清理会越堆越多；
    源码与历史都在 git，删错可取回，因此不需要本地保留历史副本。
    """
    删目录数 = 0
    释放 = 0
    for 目录 in 仓库根.iterdir():
        if not 目录.is_dir():
            continue
        是内容寻址 = len(目录.name) == 32 and all(c in '0123456789abcdef' for c in 目录.name)
        是身份目录 = 目录.name.startswith(f"{客户端前缀}-")
        if not (是内容寻址 or 是身份目录):
            continue
        是当前 = 目录.name == 当前摘要 or 目录.name == f"{客户端前缀}-{当前身份}"
        if 是当前:
            continue
        大小 = sum(p.stat().st_size for p in 目录.rglob('*') if p.is_file())
        shutil.rmtree(目录)
        删目录数 += 1
        释放 += 大小
    # 信任链：快照/目标/签名制品包各留最新一份
    信任根 = 仓库根 / "平台客户端信任"
    for 目录, 模式 in ((信任根 / "元数据", "快照_*.json"), (信任根 / "元数据", "目标_*.json"),
                     (信任根 / "制品", "*.bin")):
        if not 目录.is_dir():
            continue
        文件 = sorted(目录.glob(模式), key=lambda p: p.stat().st_mtime)
        for 过期 in 文件[:-1]:
            释放 += 过期.stat().st_size
            过期.unlink()
            删目录数 += 1
    print(f"过期制品清理：删 {删目录数} 项，释放 {释放 / 1024 / 1024:.1f} MB")


def 构建(安装: bool = False) -> Path:
    """构建平台客户端制品目录；构建前后都拒绝任何符号链接。"""
    源根列表: list[tuple[str, Path]] = []
    for 顶层 in 顶层包表:
        源 = 系统根 / 顶层
        if not 源.exists():
            continue
        if 源.is_symlink() or not 源.is_dir():
            raise 客户端构建错误(f"正式源码根非法: {源}")
        _拒绝符号链接(源, "构建前源码检查")
        源根列表.append((顶层, 源))
    _拒绝符号链接(构建目录, "构建前旧构建目录检查")
    _拒绝符号链接(制品目录, "构建前制品目录检查")
    if 安装:
        _拒绝符号链接(环境目录, "构建前安装环境检查")
    if 构建目录.exists():
        shutil.rmtree(构建目录)
    客户端根 = 构建目录 / 客户端前缀
    客户端根.mkdir(parents=True)
    改写数 = 0
    for 顶层, 源 in 源根列表:
        改写数 += 复制并重写(源, 客户端根 / 顶层)
        复制非Py文件(源, 客户端根 / 顶层)
    生成入口(客户端根)
    _拒绝符号链接(客户端根, "构建副本完成检查")
    # 制品根含 平台客户端 包层（激活指针→不可变制品→制品内 平台客户端 包可导入）
    制品根 = 制品目录 / f"{客户端前缀}-临时"
    _拒绝符号链接(制品根, "临时制品覆盖前检查")
    if 制品根.exists():
        shutil.rmtree(制品根)
    制品根.mkdir(parents=True)
    _安全复制目录树(客户端根, 制品根 / 客户端前缀)
    生成可运行制品壳(制品根)
    _拒绝符号链接(制品根, "临时制品复制后检查")
    # 摘要口径=制品根内容（含 平台客户端 包层）；安全摘要逐文件无跟随读取。
    摘要 = 计算制品摘要(制品根)[:16]
    _拒绝符号链接(制品根, "正式摘要后检查")
    摘要制品根 = 制品目录 / f"{客户端前缀}-{摘要[:16]}"
    _拒绝符号链接(摘要制品根, "摘要制品覆盖前检查")
    if 摘要制品根.exists():
        shutil.rmtree(摘要制品根)
    _安全复制目录树(制品根, 摘要制品根)
    _拒绝符号链接(摘要制品根, "摘要制品复制后检查")
    shutil.rmtree(制品根)
    制品根 = 摘要制品根
    摘要内容 = json.dumps({
        "客户端": 客户端前缀,
        "摘要sha256": 摘要,
        "顶层包": 顶层包表,
        "生成时间": "",
    }, ensure_ascii=False).encode("utf-8")
    制品根描述符 = _打开根目录(制品根, "制品摘要目标")
    try:
        _写入受控目标(
            制品根描述符, 制品根, Path("制品摘要.json"), 摘要内容)
    finally:
        os.close(制品根描述符)
    生成来源元数据(制品根)
    _拒绝符号链接(制品根, "构建完成检查")
    # 稳定指针：最新制品
    指针 = 制品目录 / "当前.json"
    if 指针.is_symlink():
        raise 客户端构建错误(f"稳定指针是符号链接: {指针}")
    真实制品目录 = _准备目标根(制品目录)
    _受控目标路径(制品目录, 真实制品目录, Path("当前.json"))
    制品目录描述符 = _打开根目录(制品目录, "稳定指针目标")
    try:
        _写入受控目标(
            制品目录描述符,
            制品目录,
            Path("当前.json"),
            f'{{"摘要sha256": "{摘要}", "路径": "{制品根.name}"}}'.encode("utf-8"),
        )
    finally:
        os.close(制品目录描述符)
    _拒绝符号链接(制品目录, "构建后制品目录检查")
    print(f"构建完成：{制品根}")
    print(f"改写导入数：{改写数}，制品摘要：{摘要}")
    if 安装:
        安装到环境(制品根)
        _拒绝符号链接(环境目录, "正式安装后环境检查")
    return 制品根


def 安装到环境(制品根: Path) -> Path:
    """把制品经正式包仓库机制安装到 平台客户端环境/（不 bypass）。

    链路（全部复用 平台控制面/包仓库 既有内容寻址、签名与信任体系）：
    入库（内容寻址 + 物料清单 + Ed25519 签名 + 信任元数据）→
    校验（签名 + 磁盘逐一摘要）→ 临时目录完整写入 + fsync + os.replace
    原子替换 → 发布管理（单调版本+栅栏令牌+CAS）激活指针 →
    同步 当前.json（外部调用方稳定路径契约）→ 校验稳定路径可读。

    环境目录契约不变：
        工程缓存/制品仓库/平台客户端环境/平台客户端/  ← 固定包名的已安装制品
        工程缓存/制品仓库/平台客户端环境/当前.json    ← 激活指针（摘要/制品目录）
    """
    from 平台控制面.包仓库.平台客户端制品 import 平台客户端制品接入
    接入 = 平台客户端制品接入()
    try:
        私钥, 公钥 = 平台客户端制品接入.生成或读取密钥()
        入库成功, 入库消息, 制品摘要 = 接入.入库(
            制品目录=制品根, 构建输入={"来源": "客户端构建", "命令": " ".join(sys.argv)},
            私钥PEM=私钥, 公钥PEM=公钥)
        if not 入库成功:
            raise RuntimeError(f"入库失败: {入库消息}")
        安装成功, 安装消息, 目标 = 接入.安装到环境(制品摘要)
        if not 安装成功 or 目标 is None:
            raise RuntimeError(f"安装失败: {安装消息 or '未返回安装目标'}")
        有效, 校验消息, _ = 接入.校验稳定路径()
        if not 有效:
            raise RuntimeError(f"稳定路径校验失败: {校验消息}")
        记录 = 接入.状态.读取记录("制品", "制品摘要", 制品摘要)
        清理过期制品(接入.制品根目录, 制品摘要, (记录 or {}).get("版本", ""))
        print(f"已经包仓库安装并激活：{目标}")
        print(f"入库：{入库消息}")
        return 目标
    finally:
        接入.关闭()


if __name__ == "__main__":
    安装 = "--安装" in sys.argv
    构建(安装=安装)
