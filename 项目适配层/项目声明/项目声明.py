"""项目声明：项目身份与绑定声明的解析校验。

项目声明.json 定义项目身份、所需支持库与模块绑定、验证范围。
适配层只消费声明，不读取业务项目代码。

解析层严格校验键名：未知键、绑定条目缺版本约束一律显式报错。消费侧统一用
`.get(键, "")` 读取，读不到只会拿到空串；解析层不拦，写错一个键名（例如把
`版本约束` 写成 `版本`）就会让版本约束校验恒真空跑（判据① 空跑，见
公共契约/版本规则/比较.py::满足约束）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

必填字段 = ("项目id", "项目名称", "系统版本", "支持库绑定", "模块绑定", "验证范围")
# 可选键：当前仅「可双击演示」声明在用，不参与版本约束消费面。
可选字段 = ("前端入口", "模块入口", "编译输出目录")
已知字段 = 必填字段 + 可选字段
绑定组名 = ("支持库绑定", "模块绑定")
绑定条目字段 = ("包id", "版本约束")


def 校验声明键名(数据: dict, 来源: str = "") -> None:
    """严格校验声明键名与绑定条目形状；未知键或缺失约束抛 ValueError。

    未知键必须显式报错，不能静默当空：消费侧的 `.get(键, "")` 会把拼错的
    键读成空串，把版本约束校验变成恒真门禁。
    """
    if not isinstance(数据, dict):
        raise ValueError(f"项目声明必须是 JSON 对象: {来源}")
    未知键 = sorted(set(数据) - set(已知字段))
    if 未知键:
        raise ValueError(
            f"项目声明存在未知键 {未知键}: {来源}；已知键 {list(已知字段)}"
        )
    for 组名 in 绑定组名:
        条目列表 = 数据.get(组名, [])
        if not isinstance(条目列表, list):
            raise ValueError(f"项目声明.{组名} 必须是数组: {来源}")
        for 序号, 条目 in enumerate(条目列表):
            位置 = f"{组名}[{序号}]"
            if not isinstance(条目, dict):
                raise ValueError(f"项目声明.{位置} 必须是对象: {来源}")
            条目未知键 = sorted(set(条目) - set(绑定条目字段))
            if 条目未知键:
                raise ValueError(
                    f"项目声明.{位置} 存在未知键 {条目未知键}: {来源}；"
                    f"已知键 {list(绑定条目字段)}"
                )
            if not str(条目.get("包id", "")).strip():
                raise ValueError(f"项目声明.{位置} 缺少 包id: {来源}")
            约束 = 条目.get("版本约束")
            if not isinstance(约束, str) or not 约束.strip():
                raise ValueError(
                    f"项目声明.{位置} 缺少非空 版本约束: {来源}；"
                    "空约束会让版本校验空跑，无约束须显式写 >=0.0.0"
                )


@dataclass
class 项目声明:
    """一份项目声明的解析结果。"""

    项目id: str
    项目名称: str
    系统版本: str = ">=1.0.0"
    支持库绑定: list[dict] = field(default_factory=list)
    模块绑定: list[dict] = field(default_factory=list)
    验证范围: list[str] = field(default_factory=list)
    来源路径: str = ""

    def 转字典(self) -> dict:
        return {
            "项目id": self.项目id,
            "项目名称": self.项目名称,
            "系统版本": self.系统版本,
            "支持库绑定": self.支持库绑定,
            "模块绑定": self.模块绑定,
            "验证范围": self.验证范围,
        }


def 从字典构建(数据: dict, 来源路径: str = "") -> 项目声明:
    """从字典构建项目声明；缺失必填字段或存在未知键抛 ValueError。"""
    缺失 = [字段 for 字段 in 必填字段 if 字段 not in 数据]
    if 缺失:
        raise ValueError(f"项目声明缺少必填字段: {', '.join(缺失)}")
    校验声明键名(数据, 来源=来源路径)
    return 项目声明(
        项目id=数据["项目id"],
        项目名称=数据["项目名称"],
        系统版本=数据.get("系统版本", ">=1.0.0"),
        支持库绑定=数据.get("支持库绑定", []),
        模块绑定=数据.get("模块绑定", []),
        验证范围=数据.get("验证范围", []),
        来源路径=来源路径,
    )


def 加载项目声明(声明路径: Path) -> 项目声明:
    """从文件加载项目声明；JSON 不合法抛 ValueError。"""
    try:
        数据 = json.loads(声明路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        raise ValueError(f"项目声明读取失败 {声明路径}: {错误}") from 错误
    return 从字典构建(数据, 来源路径=str(声明路径))


def 写入项目声明(声明: 项目声明, 声明路径: Path) -> None:
    """写入项目声明 JSON（原子写盘）。

    整仓内核只读锁（macOS `chflags uchg`）下，裸 `mkdir`/`write_text`/`replace` 会被内核
    以 `Operation not permitted` 拒（2026-09-23 实测）。本层**不能**转调
    `支持库.后端.文件系统支持库.文件操作.写入文件`（唯一分层方案：项目适配层不得调用
    支持库，见 `运行核心/依赖防火墙.py` 的 `允许依赖表`）⇒ 按《仓库只读锁》的既定腿
    开窗口：`临时解锁`（含父目录链）→ 临时件 + `replace` → 窗口**外**补 `对齐目标锁态`。
    窗口与对齐都用既有函数，本文件不另写「解锁→写→上锁」骨架（哲学 1.2）。
    """
    from 公共契约.运行时.仓库只读锁 import 临时解锁, 对齐目标锁态
    临时路径 = 声明路径.with_suffix(".tmp")
    with 临时解锁(声明路径, 临时路径):
        声明路径.parent.mkdir(parents=True, exist_ok=True)
        临时路径.write_text(json.dumps(声明.转字典(), ensure_ascii=False, indent=2), encoding="utf-8")
        临时路径.replace(声明路径)
    对齐目标锁态(声明路径)
