"""受管动态值展开。"""
from __future__ import annotations
import copy
import os
from pathlib import Path
from typing import Any
from 公共契约.运行时.平台适配 import 复制文件不传标志
from 开发工具.HTML验证.常量 import 未指定
from 开发工具.HTML验证.返回判定 import _取路径
from 开发工具.HTML验证.路径安全 import _安全合并路径
def _展开动态值(
    值: Any, *, 制品目录: Path, 包目录: Path, 临时目录: Path,
    步骤返回表: dict[str, dict[str, Any]],
) -> Any:
    """只展开冻结的五类动态值；文件写入只能落受管临时目录。"""
    if isinstance(值, list):
        return [_展开动态值(项, 制品目录=制品目录, 包目录=包目录,
                           临时目录=临时目录, 步骤返回表=步骤返回表) for 项 in 值]
    if not isinstance(值, dict):
        return 值
    if "$动态" not in 值:
        return {键: _展开动态值(项, 制品目录=制品目录, 包目录=包目录,
                              临时目录=临时目录, 步骤返回表=步骤返回表)
                for 键, 项 in 值.items()}
    类型 = 值["$动态"]
    if 类型 == "制品根":
        代码根 = 制品目录 / "平台客户端"
        if not (代码根 / "__init__.py").is_file():
            代码根 = 制品目录
        return str(_安全合并路径(代码根, 值["相对路径"], "制品动态路径"))
    if 类型 == "受管临时目录":
        路径 = _安全合并路径(临时目录, 值["相对路径"], "临时动态路径")
        路径.mkdir(parents=True, exist_ok=True)
        return str(路径)
    if 类型 == "受管临时路径":
        路径 = _安全合并路径(临时目录, 值["相对路径"], "临时动态路径")
        路径.parent.mkdir(parents=True, exist_ok=True)
        return str(路径)
    if 类型 == "夹具文件复制":
        来源 = _安全合并路径(包目录, 值["来源"], "夹具来源")
        if not 来源.is_file():
            raise ValueError(f"夹具文件不存在: {来源}")
        目标 = _安全合并路径(临时目录, 值["目标"], "夹具目标")
        目标.parent.mkdir(parents=True, exist_ok=True)
        # ★ 复制原语走**全仓唯一实现** `平台适配.复制文件不传标志`（2026-09-25 收口）。
        #
        # 原先此处用 `shutil.copy2`：`copy2` = `copy` + `copystat`，而 `copystat` 会把源的
        # `st_flags` 一并复制（`os.chflags`）。本仓整仓置了内核只读锁（`uchg`），**验证夹具
        # 全是被跟踪文件 ⇒ 全带 `uchg`** ⇒ 副本也带 ⇒ 清理时 `清只读后删除树` 删不掉
        # （`uchg` 存在时 `os.chmod` 本身被内核拒）⇒ **每个用到夹具复制的正向场景都留下
        # 删不掉的受管临时根**，而「资源残留数」是验证报告的判定项 ⇒ 报告恒定 `失败数 ≥ 1`，
        # 把「验证腿自己没打扫干净」长期伪装成场景结果（实测影响面：36 个场景 / 73 处）。
        #
        # 为什么不是「复制后复用 `仓库只读锁.对齐目标锁态(目标)`」：该腿对**落在仓库内豁免区
        # （`工程缓存/`）的副本不生效**（实测回「改动 0 条」、副本仍 `uchg`：`_上下文锁态`
        # 规则①「目标自身已锁」先于规则③「遇豁免前缀即停」命中，且递归候选被 `_在豁免区`
        # 过滤）。⇒ 正确落点是**从源头不传播标志**。
        #
        # **实现只有一份**：判据、理由与边界（不保留 mtime 等）全在
        # `公共契约/运行时/平台适配/复制.py`；本处只调用，不在此再写一遍复制原语。
        复制文件不传标志(来源, 目标)
        return str(目标)
    if 类型 == "步骤返回":
        步骤id = 值["步骤id"]
        if 步骤id not in 步骤返回表:
            raise ValueError(f"动态引用缺失: {步骤id}")
        结果值 = _取路径(步骤返回表[步骤id], 值["JSON路径"])
        if 结果值 is 未指定:
            raise ValueError(f"动态JSON路径不存在: {步骤id} {值['JSON路径']}")
        return copy.deepcopy(结果值)
    if 类型 == "环境变量":
        # 本地环境依赖（哲学第 1 条 1 项）：模型文件、外部应用这类**环境依赖**不进场景静态路径，
        # 由运行环境提供环境变量；场景只声明「读哪个环境变量」，缺变量即明确失败。
        名称 = str(值.get("名称") or "")
        取值 = os.environ.get(名称, "")
        if not 名称 or not 取值:
            raise ValueError(f"环境依赖未就绪：环境变量 {名称 or '(未命名)'} 未设置或为空")
        return 取值
    raise ValueError(f"未知动态值类型: {类型}")
