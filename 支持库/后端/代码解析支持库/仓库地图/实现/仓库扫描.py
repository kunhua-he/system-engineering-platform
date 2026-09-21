"""仓库源码扫描：定语言、定语法集、定排除，产有序文件清单与跳过清单。

只做文件系统层的事（递归/排除/读取/解码），不解析语法 —— 解析一律交给
`代码解析支持库.语法索引`，本包不自写解析器。
"""

from __future__ import annotations

from pathlib import Path

#: 平台默认排除目录（与 代码解析支持库 其余能力同一口径）。
默认排除目录 = (".git", "__pycache__", "工程缓存", "node_modules", ".venv", "dist", "build")
扩展名语言 = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".vue": "vue"}
最大文件字节 = 4 * 1024 * 1024


def 扫描(仓库根: Path, 排除目录: list[str], 语言集: list[str]) -> tuple[list[dict], list[dict]]:
    """递归扫描源码；返回 (文件清单, 跳过清单)。

    文件清单元素：{绝对路径, 相对路径, 语言, 语法集, 代码文本}
    跳过清单元素：{路径, 原因}
    两项均按相对路径字典序稳定排序（保证同一仓重复扫描结果一致）。
    """
    排除 = set(排除目录) if 排除目录 else set(默认排除目录)
    收窄 = set(语言集)
    文件表: list[dict] = []
    跳过清单: list[dict] = []
    for 路径 in sorted(仓库根.rglob("*")):
        if not 路径.is_file():
            continue
        相对 = 路径.relative_to(仓库根)
        语言 = 扩展名语言.get(路径.suffix.lower())
        if 语言 is None or (收窄 and 语言 not in 收窄):
            continue
        if 命中排除(相对, 排除):
            continue
        try:
            原字节 = 路径.read_bytes()
        except OSError as 错误:
            跳过清单.append({"路径": 相对.as_posix(), "原因": f"读取失败: {错误}"})
            continue
        if len(原字节) > 最大文件字节:
            跳过清单.append({"路径": 相对.as_posix(),
                          "原因": f"超过单文件上限 {最大文件字节} 字节"})
            continue
        文件表.append({
            "绝对路径": str(路径),
            "相对路径": 相对.as_posix(),
            "语言": 语言,
            "语法集": 语言,
            "代码文本": 原字节.decode("utf-8", "replace"),
        })
    return 文件表, 跳过清单


def 命中排除(相对路径: Path, 排除: set[str]) -> bool:
    """任一目录片段命中排除表即跳过（文件名本身不参与命中）。"""
    return any(片段 in 排除 for 片段 in 相对路径.parts[:-1])
