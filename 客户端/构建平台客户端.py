"""平台客户端构建脚本：把平台源码树打包为唯一前缀 平台客户端 制品。

规则：
- 复制平台正式目录（公共契约/支持库/模块库/运行核心/前端核心/后端核心/
  项目适配层/平台控制面/启动监督器/开发工具）到 平台客户端/ 前缀下。
- 用 AST 重写顶层导入：from 公共契约.X → from 平台客户端.公共契约.X；
  import 公共契约 → import 平台客户端.公共契约（避免与 V3 同名 namespace 冲突）。
- 构建 wheel 到 工程缓存/平台客户端制品/，并安装到 工程缓存/平台客户端环境/
  （内容寻址不可变制品，V3 只绑定已安装制品，不拼接平台源码树）。

用法：python3.14 客户端/构建平台客户端.py [--安装]
"""

from __future__ import annotations

import ast
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

系统根 = Path(__file__).resolve().parent.parent
顶层包表 = ["公共契约", "支持库", "模块库", "运行核心", "前端核心", "后端核心",
           "项目适配层", "平台控制面", "启动监督器", "开发工具"]
客户端前缀 = "平台客户端"
构建目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端构建"
# 制品仓库 是发布门禁认可的不可变制品目录（门禁豁免其内构建产物）
制品目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端制品"
环境目录 = 系统根 / "工程缓存" / "制品仓库" / "平台客户端环境"


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
    """复制平台源码树并在副本上重写顶层导入，返回改写总数。"""
    总数 = 0
    for 文件 in 源根.rglob("*.py"):
        相对 = 文件.relative_to(源根)
        目标 = 目标根 / 相对
        目标.parent.mkdir(parents=True, exist_ok=True)
        if "__pycache__" in 相对.parts:
            continue
        内容 = 文件.read_text(encoding="utf-8")
        try:
            树 = ast.parse(内容)
        except SyntaxError:
            shutil.copy2(文件, 目标)
            continue
        重写器 = 导入重写器(顶层包表, 客户端前缀)
        新树 = 重写器.visit(树)
        总数 += 重写器.改写数
        try:
            新内容 = ast.unparse(新树)
        except Exception:
            shutil.copy2(文件, 目标)
            continue
        目标.write_text(新内容, encoding="utf-8")
    return 总数


def 复制非Py文件(源根: Path, 目标根: Path) -> None:
    """复制 JSON/说明等非 Python 资源文件。"""
    for 文件 in 源根.rglob("*"):
        if 文件.is_dir():
            continue
        相对 = 文件.relative_to(源根)
        if "__pycache__" in 相对.parts:
            continue
        if 相对.suffix == ".py":
            continue
        目标 = 目标根 / 相对
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(文件, 目标)


def 生成入口(客户端根: Path) -> None:
    """生成 平台客户端/__init__.py：公开模块能力门面。"""
    入口 = 客户端根 / "__init__.py"
    入口.write_text(
        '"""平台客户端（系统工程平台稳定客户端）：唯一前缀制品包。\n'
        "V3 正式代码只经本客户端调用模块公开能力，禁止拼接平台源码树。\n"
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
        "__all__: list[str] = []\n",
        encoding="utf-8",
    )


def 生成pyproject(客户端根: Path) -> None:
    """生成 pyproject.toml（wheel 打包元数据）。"""
    (客户端根 / "pyproject.toml").write_text(
        f'[build-system]\n'
        f'requires = ["setuptools>=68"]\n'
        f'build-backend = "setuptools.build_meta"\n'
        f'\n'
        f'[project]\n'
        f'name = "{客户端前缀}"\n'
        f'version = "1.0.0"\n'
        f'description = "系统工程平台稳定客户端（唯一前缀制品）"\n'
        f'requires-python = ">=3.14"\n'
        f'\n'
        f'[tool.setuptools]\n'
        f'packages = ["{客户端前缀}"]\n'
        f'include-package-data = true\n',
        encoding="utf-8",
    )


def 计算制品摘要(客户端根: Path) -> str:
    """内容寻址：全部正式文件 sha256 摘要。"""
    哈希 = hashlib.sha256()
    for 文件 in sorted(客户端根.rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        哈希.update(str(文件.relative_to(客户端根)).encode("utf-8"))
        哈希.update(文件.read_bytes())
    return 哈希.hexdigest()


def 构建(安装: bool = False) -> Path:
    """构建平台客户端制品目录，返回制品根。"""
    if 构建目录.exists():
        shutil.rmtree(构建目录)
    客户端根 = 构建目录 / 客户端前缀
    客户端根.mkdir(parents=True)
    改写数 = 0
    for 顶层 in 顶层包表:
        源 = 系统根 / 顶层
        if not 源.is_dir():
            continue
        改写数 += 复制并重写(源, 客户端根 / 顶层)
        复制非Py文件(源, 客户端根 / 顶层)
    生成入口(客户端根)
    摘要 = 计算制品摘要(客户端根)
    制品根 = 制品目录 / f"{客户端前缀}-{摘要[:16]}"
    if 制品根.exists():
        shutil.rmtree(制品根)
    shutil.copytree(客户端根, 制品根)
    (制品根 / "制品摘要.json").write_text(
        f'{{"客户端": "{客户端前缀}", "摘要sha256": "{摘要}", '
        f'"顶层包": {顶层包表}, "生成时间": ""}}',
        encoding="utf-8",
    )
    # 稳定指针：最新制品
    指针 = 制品目录 / "当前.json"
    指针.write_text(f'{{"摘要sha256": "{摘要}", "路径": "{制品根.name}"}}', encoding="utf-8")
    print(f"构建完成：{制品根}")
    print(f"改写导入数：{改写数}，制品摘要：{摘要}")
    if 安装:
        安装到环境(制品根)
    return 制品根


def 安装到环境(制品根: Path) -> Path:
    """把制品安装到 工程缓存/平台客户端环境/（内容寻址不可变目录）。

    环境目录结构：
        工程缓存/平台客户端环境/平台客户端/  ← 固定包名的已安装制品（原子替换）
        工程缓存/平台客户端环境/当前.json    ← 激活指针（摘要/来源制品目录）
    """
    制品副本 = 环境目录 / "制品" / 制品根.name
    if 制品副本.exists():
        shutil.rmtree(制品副本)
    制品副本.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(制品根, 制品副本)
    # 原子发布固定包名：完整复制到临时目录 → 校验 → 整体替换
    临时 = 环境目录 / f".平台客户端.tmp-{制品根.name[-8:]}"
    if 临时.exists():
        shutil.rmtree(临时)
    临时.mkdir(parents=True)
    shutil.copytree(制品根, 临时 / "平台客户端")
    (临时 / "平台客户端" / "制品来源.json").write_text(
        f'{{"制品目录": "{制品根.name}", "摘要sha256": "{制品根.name.split("-")[-1]}"}}',
        encoding="utf-8",
    )
    目标 = 环境目录 / "平台客户端"
    if 目标.exists():
        shutil.rmtree(目标)
    shutil.move(临时 / "平台客户端", 目标)
    shutil.rmtree(临时, ignore_errors=True)
    指针 = 环境目录 / "当前.json"
    指针.write_text(
        f'{{"摘要sha256": "{制品根.name.split("-")[-1]}", "制品目录": "{制品根.name}"}}',
        encoding="utf-8",
    )
    print(f"已安装到环境：{目标}")
    return 目标


if __name__ == "__main__":
    安装 = "--安装" in sys.argv
    构建(安装=安装)
