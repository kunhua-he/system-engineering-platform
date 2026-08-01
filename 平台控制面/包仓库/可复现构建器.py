"""可复现构建器：同一冻结输入在任何工作区构建，正式文件摘要完全一致。

确定性三原则：
- 时间戳占位符 {时间戳} 只替换为冻结输入提供的固定构建时刻，绝不用当前时间。
- 工作区路径占位符 {工作区路径} 只替换为固定标记“工作区”，绝对路径不进制品。
- 主机名占位符 {主机名} 只替换为固定字符串，绝不用真实主机名。
禁止依赖 time.time()/os.getpid()/tempfile 随机名/真实主机名等运行时差异。
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

默认构建时刻 = "2000-01-01 00:00:00"
默认主机名 = "可复现构建机"


def 规范化相对路径(路径: str) -> str:
    """校验并规范化制品内相对路径；非法路径抛 ValueError（与包仓库同一规则）。"""
    if not 路径 or 路径 in (".", "/", "\\"):
        raise ValueError(f"空或根路径不允许: {路径!r}")
    if 路径.startswith("/") or 路径.startswith("\\") or 路径[1:2] == ":":
        raise ValueError(f"绝对路径不允许: {路径!r}")
    if any(段 in ("..", ".") for 段 in 路径.replace("\\", "/").split("/")):
        raise ValueError(f"路径逃逸不允许: {路径!r}")
    if "\\" in 路径:
        raise ValueError(f"反斜杠分隔符不允许: {路径!r}")
    return 路径


class 可复现构建器:
    """独立可复现构建实现（S1 阶段合并进 平台控制面/包仓库.py 的 构建制品）。"""

    def __init__(self, *, 构建时刻: str = 默认构建时刻,
                 主机名: str = 默认主机名) -> None:
        self.构建时刻 = 构建时刻
        self.主机名 = 主机名

    def 确定性展开(self, 内容: str, 工作区路径: str, *,
                  构建时刻: str | None = None, 主机名: str | None = None) -> str:
        """把环境差异占位符替换为确定性值，返回不含任何运行时差异的内容。

        工作区路径只用于语义标注，占位符一律替换为固定标记，保证两个
        全新工作区展开结果逐字节一致。构建时刻/主机名可显式传入，未传时
        取实例构造值——实例状态不会被单次构建改写，杜绝历史残留污染。
        """
        return self._确定性展开本地(内容,
                                   构建时刻 or self.构建时刻,
                                   主机名 or self.主机名)

    def _确定性展开本地(self, 内容: str, 构建时刻: str, 主机名: str) -> str:
        """占位符替换的核心实现；构建时刻/主机名取本次构建的局部值。"""
        if "{时间戳}" in 内容:
            内容 = 内容.replace("{时间戳}", 构建时刻)
        if "{工作区路径}" in 内容:
            内容 = 内容.replace("{工作区路径}", "工作区")
        if "{主机名}" in 内容:
            内容 = 内容.replace("{主机名}", 主机名)
        return 内容

    def 构建(self, 冻结输入: dict, 工作区路径: str | Path) -> tuple[Path, dict[str, str]]:
        """在给定工作区从冻结输入构建正式制品。

        冻结输入: {"文件表": {相对路径: 内容, ...},
                   "构建时刻": 固定构建时刻(可选), "主机名": 固定字符串(可选)}
        返回: (构建目录, 正式文件摘要{相对路径: sha256})。
        构建目录为工作区下的固定名“构建产物”，先清空重建，只含正式文件。
        """
        文件表 = 冻结输入.get("文件表")
        if not isinstance(文件表, dict) or not 文件表:
            raise ValueError("冻结输入必须包含非空文件表")
        # 本次构建的占位符取值只取冻结输入或构造默认值，绝不写回实例状态，
        # 防止历史构建残留污染后续构建摘要（构建时刻/主机名只属单次构建）。
        本次构建时刻 = 冻结输入.get("构建时刻") or self.构建时刻
        本次主机名 = 冻结输入.get("主机名") or self.主机名
        规范化表: dict[str, str] = {}
        for 路径, 内容 in 文件表.items():
            if not isinstance(内容, str):
                raise ValueError(f"文件内容必须是字符串: {路径}")
            规范化表[规范化相对路径(路径)] = self._确定性展开本地(内容, 本次构建时刻, 本次主机名)
        构建目录 = Path(工作区路径) / "构建产物"
        if 构建目录.exists():
            shutil.rmtree(构建目录)
        构建目录.mkdir(parents=True)
        for 路径, 内容 in 规范化表.items():
            目标 = 构建目录 / 路径
            目标.parent.mkdir(parents=True, exist_ok=True)
            目标.write_text(内容, encoding="utf-8")
        return 构建目录, self.构建摘要(构建目录)

    def 构建摘要(self, 构建目录: str | Path) -> dict[str, str]:
        """对正式文件逐个计算 sha256，返回完整摘要（相对路径→内容摘要）。"""
        摘要表: dict[str, str] = {}
        for 文件 in sorted(Path(构建目录).rglob("*")):
            if 文件.is_file():
                摘要表[文件.relative_to(构建目录).as_posix()] = (
                    hashlib.sha256(文件.read_bytes()).hexdigest())
        return 摘要表

    def 双工作区验证(self, 冻结输入: dict) -> tuple[bool, dict, dict, str]:
        """两个全新临时工作区分别构建，返回(是否一致, 摘要甲, 摘要乙, 消息)。"""
        工作区甲 = Path(tempfile.mkdtemp(prefix="可复现甲_"))
        工作区乙 = Path(tempfile.mkdtemp(prefix="可复现乙_"))
        try:
            _, 摘要甲 = self.构建(冻结输入, 工作区甲)
            _, 摘要乙 = self.构建(冻结输入, 工作区乙)
        finally:
            shutil.rmtree(工作区甲, ignore_errors=True)
            shutil.rmtree(工作区乙, ignore_errors=True)
        if 摘要甲 != 摘要乙:
            差异 = next((路径 for 路径 in set(摘要甲) | set(摘要乙)
                         if 摘要甲.get(路径) != 摘要乙.get(路径)), "未知")
            return False, 摘要甲, 摘要乙, f"两个工作区摘要不一致，首个差异文件: {差异}"
        return True, 摘要甲, 摘要乙, "两个工作区摘要完全一致"
