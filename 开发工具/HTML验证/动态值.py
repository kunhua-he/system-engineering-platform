"""受管动态值展开。"""
from __future__ import annotations
import copy
import os, shutil
from pathlib import Path
from typing import Any
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
        shutil.copy2(来源, 目标)
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
        # 本地环境依赖（哲学第 7 条）：模型文件、外部应用这类**环境依赖**不进场景静态路径，
        # 由运行环境提供环境变量；场景只声明「读哪个环境变量」，缺变量即明确失败。
        名称 = str(值.get("名称") or "")
        取值 = os.environ.get(名称, "")
        if not 名称 or not 取值:
            raise ValueError(f"环境依赖未就绪：环境变量 {名称 or '(未命名)'} 未设置或为空")
        return 取值
    raise ValueError(f"未知动态值类型: {类型}")
