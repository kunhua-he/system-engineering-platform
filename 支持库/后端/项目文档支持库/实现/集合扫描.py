"""项目文档支持库 · 集合扫描原子能力（进程内实现，不对外暴露）。

按根目录 + 文件名模式扫出一批文档，供**集合级判据**使用：只读、无状态、稳定排序。

为什么单列一条能力：扫描与校验分开。扫描可被其它能力复用（例如索引入库前取文档清单），
校验则不自带隐式扫描 —— 读哪些文件由判据文件显式决定，调用方能预知 IO 面。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果


def _归一豁免(豁免目录, 根名: str = "") -> list[tuple[str, ...]]:
    """把豁免目录归一为「路径片段元组」列表；非法类型返回空表（不猜）。

    **口径**（修过一处真实 bug）：豁免片段按**相对扫描根**解释。为方便调用方，
    允许写成「相对仓库根」的完整路径（如扫描根是 `开发文档` 时写 `开发文档/归档`）——
    此时**剥掉与扫描根同名的首段**再比较。2026-09-18 实测：不剥首段时
    `开发文档/归档` 永远匹配不上（扫描根内相对路径是 `归档/…`），豁免静默失效。
    """
    if isinstance(豁免目录, str):
        片段列表 = [x for x in 豁免目录.replace(";", ",").split(",") if x.strip()]
    elif isinstance(豁免目录, list):
        片段列表 = [str(x) for x in 豁免目录 if str(x).strip()]
    else:
        return []
    结果表: list[tuple[str, ...]] = []
    for 片段 in 片段列表:
        部分 = tuple(x for x in 片段.strip().strip("/").split("/") if x)
        if not 部分:
            continue
        if 根名 and 部分[0] == 根名 and len(部分) > 1:
            部分 = 部分[1:]
        结果表.append(部分)
    return 结果表


def _被豁免(相对部分: tuple[str, ...], 豁免表: list[tuple[str, ...]]) -> bool:
    """相对路径的**前若干段**与任一豁免片段逐段相等即豁免（用逐段比较，不用子串，防误伤）。"""
    return any(相对部分[:len(豁免)] == 豁免 for 豁免 in 豁免表 if len(豁免) <= len(相对部分))


def 扫描文档集合(根目录: str = None, 文件名模式: str = "*.md", 豁免目录=None,
                是否读正文: bool = False, 最大文档数: int = 5000) -> 结果:
    """扫描一批文档（只读）。

    参数：根目录（绝对路径）/ 文件名模式（如 ``*.md``）/ 豁免目录（片段列表，
    如 ``["工程缓存", "开发文档/归档"]``）/ 是否读正文 / 最大文档数（超出**明确失败**，
    不静默截断）。
    返回：``{根目录, 文档列表, 文档数, 豁免片段数}``；每份文档含
    ``相对路径 / 行数 / 字节数 / 修改时间（秒）``，``是否读正文`` 为真时另含 ``正文``。
    """
    if not isinstance(根目录, str) or not 根目录.strip():
        return 结果.失败("参数不合法", "根目录必须是非空文本", 来源="项目文档支持库")
    if not isinstance(文件名模式, str) or not 文件名模式.strip():
        return 结果.失败("参数不合法", "文件名模式必须是非空文本", 来源="项目文档支持库")
    根 = Path(根目录.strip())
    if not 根.is_dir():
        return 结果.失败("根目录不存在", f"根目录不是已存在的目录: {根}", 来源="项目文档支持库")
    try:
        上限 = int(最大文档数)
    except (TypeError, ValueError):
        return 结果.失败("参数不合法", "最大文档数必须是整数", 来源="项目文档支持库")
    豁免表 = _归一豁免(豁免目录, 根.name)

    文档列表: list[dict] = []
    命中路径 = sorted(路径 for 路径 in 根.rglob(文件名模式.strip()) if 路径.is_file())
    for 路径 in 命中路径:
        相对部分 = 路径.relative_to(根).parts
        if _被豁免(相对部分, 豁免表):
            continue
        if len(文档列表) >= 上限:
            return 结果.失败(
                "文档数超出上限",
                f"命中文档数超出上限 {上限}，请缩小根目录或加豁免目录（不静默截断）",
                来源="项目文档支持库")
        try:
            原始字节 = 路径.read_bytes()
        except OSError as 错误:
            return 结果.失败("文档不可读", f"读取失败 {路径}: {错误}", 来源="项目文档支持库")
        try:
            文本 = 原始字节.decode("utf-8")
        except UnicodeDecodeError:
            文本 = None
        条目 = {
            "相对路径": "/".join(相对部分),
            "行数": len(文本.split("\n")) if 文本 is not None else 0,
            "字节数": len(原始字节),
            "修改时间": 路径.stat().st_mtime,
            "可解析文本": 文本 is not None,
        }
        if 是否读正文:
            条目["正文"] = 文本 or ""
        文档列表.append(条目)
    return 结果.成功结果({
        "根目录": str(根),
        "文档列表": 文档列表,
        "文档数": len(文档列表),
        "豁免片段数": len(豁免表),
    })
