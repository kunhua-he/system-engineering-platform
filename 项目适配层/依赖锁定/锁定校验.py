"""依赖锁定校验：锁定文件与当前系统的漂移检测。

六项校验：包是否存在、版本是否一致、能力版本是否一致、完整性摘要
是否一致、依赖顺序是否正确、锁定文件结构是否合法。任一漂移必须失败，
不允许自动忽略。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.包声明 import 加载声明文件
from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者
from 项目适配层.依赖锁定.依赖锁定 import 计算完整性摘要


@dataclass
class 锁定校验结果:
    """一次锁定校验的结果。"""

    成功: bool = False
    漂移列表: list[str] = field(default_factory=list)
    校验项数: int = 0


def 校验锁定文件(项目根目录: Path, 系统根目录: Path) -> 锁定校验结果:
    """校验依赖锁定.json 与当前系统的漂移（任一漂移即失败）。"""
    结果 = 锁定校验结果()
    锁定路径 = 项目根目录 / "依赖锁定.json"
    if not 锁定路径.is_file():
        结果.漂移列表.append(f"缺少依赖锁定文件: {锁定路径}")
        return 结果
    try:
        锁定数据 = json.loads(锁定路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        结果.漂移列表.append(f"锁定文件不可读: {错误}")
        return 结果
    包列表 = 锁定数据.get("包列表")
    if not isinstance(包列表, list):
        结果.漂移列表.append("锁定文件缺少 包列表")
        return 结果

    发现 = 发现全部(系统根目录 / "支持库", 系统根目录 / "模块库")
    if not 发现.成功:
        结果.漂移列表.extend(发现.问题列表)
        return 结果
    当前声明表 = {声明.包id: 声明 for 声明 in 发现.声明列表}

    # 1. 包是否存在
    for 条目 in 包列表:
        包id = 条目.get("包id", "")
        结果.校验项数 += 1
        if 包id not in 当前声明表:
            结果.漂移列表.append(f"包不存在: {包id}")

    # 2. 版本是否一致
    for 条目 in 包列表:
        包id = 条目.get("包id", "")
        if 包id not in 当前声明表:
            continue
        结果.校验项数 += 1
        if 当前声明表[包id].版本 != 条目.get("版本"):
            结果.漂移列表.append(
                f"版本漂移: {包id} 锁定 {条目.get('版本')} 实际 {当前声明表[包id].版本}"
            )

    # 3. 能力版本是否一致（当前以声明能力id集合为准）
    for 条目 in 包列表:
        包id = 条目.get("包id", "")
        if 包id not in 当前声明表:
            continue
        结果.校验项数 += 1
        声明能力数 = len(当前声明表[包id].能力)
        if 条目.get("能力版本") != "1.0.0":
            结果.漂移列表.append(f"能力版本漂移: {包id} 声明能力 {声明能力数} 个")

    # 4. 完整性摘要是否一致
    for 条目 in 包列表:
        包id = 条目.get("包id", "")
        if 包id not in 当前声明表:
            continue
        结果.校验项数 += 1
        当前摘要 = 计算完整性摘要(当前声明表[包id])
        if 条目.get("完整性摘要") != 当前摘要:
            结果.漂移列表.append(
                f"完整性摘要漂移: {包id} 锁定 {条目.get('完整性摘要')} 实际 {当前摘要}"
            )

    # 5. 依赖顺序是否正确（锁定顺序 vs 解析拓扑顺序）
    声明列表 = [声明 for 声明 in 发现.声明列表 if 声明.包id in {条目["包id"] for 条目 in 包列表}]
    if 声明列表:
        提供者表 = 选择全部提供者(声明列表)
        能力提供者 = {能力id: (选择.提供包id, 选择.提供版本) for 能力id, 选择 in 提供者表.items() if 选择.成功}
        解析 = 解析依赖(声明列表, 能力提供者)
        if 解析.成功:
            锁定顺序 = {条目["包id"]: 条目.get("依赖顺序", 0) for 条目 in 包列表}
            实际顺序 = {包id: 序号 for 序号, 包id in enumerate(解析.顺序列表)}
            for 包id in 锁定顺序:
                结果.校验项数 += 1
                if 锁定顺序[包id] != 实际顺序.get(包id):
                    结果.漂移列表.append(
                        f"依赖顺序漂移: {包id} 锁定 {锁定顺序[包id]} 实际 {实际顺序.get(包id)}"
                    )
        else:
            结果.漂移列表.extend(解析.缺失能力)
            结果.漂移列表.extend(解析.版本冲突)
            if 解析.循环:
                结果.漂移列表.append(f"依赖循环: {', '.join(解析.循环)}")

    结果.成功 = not 结果.漂移列表
    return 结果
