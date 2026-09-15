"""测试资产发现：`测试中心/**/测试_*.py` 的唯一发现口径。

发现口径取自 `AGENTS.md:161/185`（测试统一放 `测试中心/`），用
`rglob("测试_*.py")` 而不是 `unittest discover`：discover 的
`VALID_MODULE_NAME` 只认 ASCII 标识符，加载不了中文测试文件名，而
`AGENTS.md:138` 明确禁用 discover。

发现阶段只解析路径，不导入任何文件；无法点号导入的文件（连字符、
关键字、非法标识符段落）带 `跳过原因` 单独报出，不静默丢失。

本模块只做发现：不导入、不判定、不打印。
"""
from __future__ import annotations

import keyword
from dataclasses import dataclass
from pathlib import Path

测试文件名模式 = "测试_*.py"
测试中心目录名 = "测试中心"


@dataclass(frozen=True)
class 测试资产:
    """一个测试文件的发现结果；`跳过原因` 非空表示不进入可导入性检查。"""

    文件: Path
    相对路径: str
    模块名: str
    跳过原因: str = ""


def _是可忽略目录(名字: str) -> bool:
    """隐藏目录与字节码缓存不属于测试资产。"""
    return 名字.startswith(".") or 名字 == "__pycache__"


def 判定跳过原因(相对路径: Path) -> str:
    """连字符/关键字/非法标识符段落 → 跳过原因；可点号导入 → 空字符串。

    判定覆盖目录名与文件名两处：只要任一段落含 `-`，点号模块名就不再是
    合法标识符，`importlib.import_module` 必然失败——这类文件按约定跳过
    并单独报出，而不是伪装成「导入失败」。
    """
    段落 = [*相对路径.parent.parts, 相对路径.stem]
    for 名 in 段落:
        if "-" in 名:
            位置 = "文件名" if 名 == 相对路径.stem else "目录名"
            return f"连字符命名（{位置} {名} 含 -，无法点号导入）"
    for 名 in 段落:
        if keyword.iskeyword(名):
            return f"非法模块名（{名} 是 Python 关键字）"
        if not 名.isidentifier():
            return f"非法模块名（{名} 不是合法标识符）"
    return ""


def 发现测试文件(根: Path) -> list[测试资产]:
    """发现 `根/测试中心` 下全部 `测试_*.py`，按相对路径排序。

    测试中心目录不存在时返回空列表；「一个文件都没有」由零测试检查判定为
    违规（`AGENTS.md:135` 零测试不得成功）。
    """
    测试中心 = 根 / 测试中心目录名
    if not 测试中心.is_dir():
        return []
    资产列表: list[测试资产] = []
    for 文件 in sorted(测试中心.rglob(测试文件名模式)):
        相对 = 文件.relative_to(根)
        if any(_是可忽略目录(片段) for 片段 in 相对.parts):
            continue
        跳过原因 = 判定跳过原因(相对)
        模块名 = "" if 跳过原因 else ".".join(相对.with_suffix("").parts)
        资产列表.append(测试资产(
            文件=文件, 相对路径=相对.as_posix(), 模块名=模块名, 跳过原因=跳过原因,
        ))
    return 资产列表
