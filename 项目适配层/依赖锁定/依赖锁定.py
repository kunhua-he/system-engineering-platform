"""依赖锁定：为项目生成可重复的依赖锁定文件。

依赖锁定.json 记录：包id、版本、契约版本、能力版本、提供者、
完整性摘要、依赖顺序。同一项目重复装配必须得到相同结果。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from 公共契约.包声明 import 包声明, 加载声明文件
from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者


@dataclass
class 锁定结果:
    """一次依赖锁定的结果。"""

    成功: bool = False
    锁定路径: str = ""
    包数量: int = 0
    问题列表: list[str] = field(default_factory=list)


def 计算完整性摘要(声明: 包声明) -> str:
    """根据声明字段计算完整性摘要（内容寻址，可重复）。"""
    关键字段 = (声明.包id, 声明.类型, 声明.版本, str(sorted(依赖.get("能力", "") for 依赖 in 声明.依赖)))
    摘要 = hashlib.sha256("|".join(关键字段).encode("utf-8")).hexdigest()
    return 摘要[:16]


def _提供者锁定信息(声明: 包声明, 系统根目录: Path) -> dict:
    """从能力定义读取默认提供者；环境摘要从运行环境管理器获取。

    选择证据 = 能力定义.提供者.默认（唯一权威提供者，非主观选择）。
    """
    提供者id = ""
    提供者版本 = ""
    环境摘要 = ""
    # 能力定义.json 是唯一事实源：找声明包目录
    # 包id 形如 支持库.后端.支持库名.子包 或 支持库.适配层.提供者名：
    # 去掉 支持库./模块库. 前缀后，剩余段即为相对根目录的路径
    包目录 = None
    for 根 in ("支持库", "模块库"):
        候选 = 系统根目录 / 根 / Path(*声明.包id.split(".")[1:])
        if (候选 / "能力定义.json").is_file():
            包目录 = 候选
            break
    if 包目录 is not None:
        try:
            定义 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
            提供者 = 定义.get("提供者", {})
            提供者id = 提供者.get("默认", "")
            提供者版本 = 提供者.get("版本", "")
            from 运行核心.运行环境管理器 import 环境摘要信息
            信息 = 环境摘要信息(包目录)
            环境摘要 = 信息.get("环境摘要", "")
        except (json.JSONDecodeError, OSError):
            pass
    选择证据 = f"能力定义.提供者.默认 = {提供者id}@{提供者版本}" if 提供者id else "无第三方依赖（系统实现）"
    return {
        "提供者id": 提供者id,
        "提供者版本": 提供者版本,
        "环境摘要": 环境摘要,
        "选择证据": 选择证据,
    }


def 生成依赖锁定(项目根目录: Path, 系统根目录: Path) -> 锁定结果:
    """生成依赖锁定.json；同一输入必然产生同一输出。"""
    结果 = 锁定结果()
    项目声明路径 = 项目根目录 / "项目声明.json"
    if not 项目声明路径.is_file():
        结果.问题列表.append(f"缺少项目声明: {项目声明路径}")
        return 结果
    项目数据 = json.loads(项目声明路径.read_text(encoding="utf-8"))

    发现 = 发现全部(系统根目录 / "支持库", 系统根目录 / "模块库")
    if not 发现.成功:
        结果.问题列表.extend(发现.问题列表)
        return 结果

    # 绑定集合（支持库 + 模块）
    绑定包id集合: set[str] = set()
    for 绑定 in 项目数据.get("支持库绑定", []):
        绑定包id集合.add(绑定["包id"])
    for 绑定 in 项目数据.get("模块绑定", []):
        绑定包id集合.add(绑定["包id"])
    if not 绑定包id集合:
        结果.问题列表.append("项目声明未绑定任何支持库或模块")
        return 结果

    声明列表 = [声明 for 声明 in 发现.声明列表 if 声明.包id in 绑定包id集合]
    缺失 = 绑定包id集合 - {声明.包id for 声明 in 声明列表}
    if 缺失:
        结果.问题列表.append(f"绑定的包不存在: {', '.join(sorted(缺失))}")
        return 结果

    # 依赖解析（得到依赖顺序）
    提供者表 = 选择全部提供者(声明列表)
    能力提供者 = {能力id: (选择.提供包id, 选择.提供版本) for 能力id, 选择 in 提供者表.items() if 选择.成功}
    解析 = 解析依赖(声明列表, 能力提供者)
    结果.问题列表.extend(解析.缺失能力)
    结果.问题列表.extend(解析.版本冲突)
    if 解析.循环:
        结果.问题列表.append(f"依赖循环: {', '.join(解析.循环)}")
    if 结果.问题列表:
        return 结果

    顺序索引 = {包id: 序号 for 序号, 包id in enumerate(解析.顺序列表)}
    包列表 = []
    for 声明 in sorted(声明列表, key=lambda 条目: 条目.包id):
        提供者信息 = _提供者锁定信息(声明, 系统根目录)
        包列表.append(
            {
                "包id": 声明.包id,
                "版本": 声明.版本,
                "类型": 声明.类型,
                "契约版本": "1.0.0",
                "能力版本": "1.0.0",
                "提供者": 声明.包id,
                "完整性摘要": 计算完整性摘要(声明),
                "依赖顺序": 顺序索引.get(声明.包id, 0),
                # P4 项目锁：固定提供者id/版本/环境摘要/选择证据
                "提供者id": 提供者信息["提供者id"],
                "提供者版本": 提供者信息["提供者版本"],
                "环境摘要": 提供者信息["环境摘要"],
                "选择证据": 提供者信息["选择证据"],
            }
        )

    锁定数据 = {
        "锁定版本": "1.0.0",
        "项目id": 项目数据["项目id"],
        "生成时间": "",  # 时间不入锁（保证可重复性），以内容为准
        "包列表": 包列表,
    }
    锁定路径 = 项目根目录 / "依赖锁定.json"
    临时路径 = 锁定路径.with_suffix(".tmp")
    临时路径.write_text(json.dumps(锁定数据, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(锁定路径)

    结果.成功 = True
    结果.锁定路径 = str(锁定路径)
    结果.包数量 = len(包列表)
    return 结果
