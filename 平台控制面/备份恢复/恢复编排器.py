"""新机器恢复编排器（P1-10）：从源码快照、内容寻址制品、依赖锁与备份恢复期望状态；
真实复制、逐文件 sha256 与来源比对、subprocess 真实运行最小能力，禁止桩实现。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .恢复工具 import 计算摘要, 内容寻址名, 收集文件, 清空目录, 复制核对

最小能力样板文件名 = "最小能力.py"
制品仓库目录名 = "制品仓库"
依赖锁定文件名 = "项目依赖锁定.json"
备份清单文件名 = "备份清单.json"
备份内容目录名 = "内容"


class 新机器恢复编排器:
    """编排恢复 → 恢复后最小调用 → 期望状态校验 三阶段编排器。"""

    def __init__(self) -> None:
        self.期望清单: dict[str, str] = {}
        self.来源路径表: dict[str, Path] = {}

    def 校验依赖锁定(self, 依赖锁路径: Path) -> dict:
        if not 依赖锁路径.is_file():
            raise ValueError(f"依赖锁定文件不存在: {依赖锁路径}")
        try:
            锁对象 = json.loads(依赖锁路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as 错误:
            raise ValueError(f"依赖锁定文件不是合法 JSON: {错误}") from 错误
        if not isinstance(锁对象, dict) or not isinstance(锁对象.get("包列表"), list) \
                or not 锁对象["包列表"]:
            raise ValueError("依赖锁定文件缺少非空包列表")
        return 锁对象

    def 编排恢复(self, 恢复输入: dict) -> dict:
        """按固定顺序执行六步恢复，返回每步结果与最终期望状态（已恢复/部分失败）。"""
        空目录 = Path(恢复输入["空目录路径"])
        源码快照 = Path(恢复输入["源码快照目录"])
        制品目录 = Path(恢复输入["制品目录"])
        依赖锁路径 = Path(恢复输入["依赖锁定文件路径"])
        备份目录 = Path(恢复输入["备份目录"]) if 恢复输入.get("备份目录") else None
        失败原因: list[str] = []
        步骤结果: dict = {}
        self.期望清单, self.来源路径表 = {}, {}
        锁对象 = self.校验依赖锁定(依赖锁路径)
        步骤结果["校验依赖锁定"] = {"成功": True, "包数": len(锁对象["包列表"])}
        清空目录(空目录)
        快照文件表 = 收集文件(源码快照) if 源码快照.is_dir() else {}
        步骤失败: list[str] = []
        for 相对 in sorted(快照文件表):
            来源, 目标 = 源码快照 / 相对, 空目录 / 相对
            if not 复制核对(来源, 目标):
                步骤失败.append(f"源码快照复制后摘要不一致: {相对}")
                continue
            self.期望清单[相对], self.来源路径表[相对] = 快照文件表[相对], 来源
        if not 源码快照.is_dir():
            步骤失败.append(f"源码快照目录不存在: {源码快照}")
        elif 最小能力样板文件名 not in 快照文件表:
            步骤失败.append(f"源码快照缺少最小能力样板文件: {最小能力样板文件名}")
        步骤结果["复制源码快照"] = {"成功": not 步骤失败, "文件数": len(快照文件表)}
        失败原因.extend(步骤失败)
        步骤失败 = []
        制品文件表 = 收集文件(制品目录) if 制品目录.is_dir() else {}
        for 相对 in sorted(制品文件表):
            来源, 目标 = 制品目录 / 相对, 空目录 / 制品仓库目录名 / 相对
            基名 = Path(相对).stem
            if 内容寻址名(基名) and 计算摘要(来源) != 基名:
                步骤失败.append(f"制品内容寻址不一致: {相对}")
                continue
            if not 复制核对(来源, 目标):
                步骤失败.append(f"制品复制后摘要不一致: {相对}")
                continue
            制品相对 = f"{制品仓库目录名}/{相对}"
            self.期望清单[制品相对], self.来源路径表[制品相对] = 制品文件表[相对], 来源
        if not 制品目录.is_dir():
            步骤失败.append(f"制品目录不存在: {制品目录}")
        步骤结果["复制制品"] = {"成功": not 步骤失败, "文件数": len(制品文件表)}
        失败原因.extend(步骤失败)
        锁目标 = 空目录 / 依赖锁定文件名
        shutil.copyfile(依赖锁路径, 锁目标)
        self.期望清单[依赖锁定文件名] = 计算摘要(锁目标)
        self.来源路径表[依赖锁定文件名] = 依赖锁路径
        步骤结果["写入依赖锁定"] = {"成功": True, "相对路径": 依赖锁定文件名}
        步骤结果["恢复备份"] = self._恢复备份(备份目录, 空目录) if 备份目录 is not None \
            else {"成功": True, "是否执行": False, "文件数": 0}
        失败原因.extend(步骤结果["恢复备份"]["失败原因"])
        步骤结果["真实性校验"] = self.真实性校验(空目录)
        失败原因.extend(步骤结果["真实性校验"]["失败原因"])
        return {"状态": "部分失败" if 失败原因 else "已恢复",
                "步骤结果": 步骤结果, "失败原因": 失败原因}

    def 真实性校验(self, 恢复目录: Path) -> dict:
        失败原因: list[str] = []
        for 相对, 来源 in self.来源路径表.items():
            目标 = 恢复目录 / 相对
            if not 目标.is_file():
                失败原因.append(f"恢复文件缺失: {相对}")
            elif 计算摘要(目标) != 计算摘要(来源):
                失败原因.append(f"恢复文件摘要与来源不一致: {相对}")
        return {"成功": not 失败原因, "全部一致": not 失败原因, "失败原因": 失败原因}

    def 恢复后最小调用(self, 恢复目录: str | Path) -> str:
        """在恢复目录以 subprocess 真实运行最小能力样板并取回真实输出。"""
        恢复目录 = Path(恢复目录)
        脚本 = 恢复目录 / 最小能力样板文件名
        if not 脚本.is_file():
            raise FileNotFoundError(f"恢复目录缺少最小能力样板: {脚本}")
        解释器 = "python3.14" if shutil.which("python3.14") else sys.executable
        执行 = subprocess.run([解释器, str(脚本)], cwd=str(恢复目录),
                             capture_output=True, text=True, timeout=30)
        if 执行.returncode != 0:
            raise RuntimeError(f"最小能力执行失败: {执行.stderr.strip() or 执行.stdout.strip()}")
        return 执行.stdout.strip()

    def 期望状态校验(self, 恢复目录: str | Path, 期望清单: dict | None = None) -> dict:
        期望清单 = 期望清单 if 期望清单 is not None else self.期望清单
        磁盘清单 = 收集文件(Path(恢复目录), 排除缓存=True)
        缺失 = sorted(set(期望清单) - set(磁盘清单))
        多余 = sorted(set(磁盘清单) - set(期望清单))
        摘要不一致 = sorted(路径 for 路径 in set(磁盘清单) & set(期望清单)
                          if 磁盘清单[路径] != 期望清单[路径])
        return {"缺失": 缺失, "多余": 多余, "摘要不一致": 摘要不一致,
                "差异数": len(缺失) + len(多余) + len(摘要不一致)}

    def _恢复备份(self, 备份目录: Path, 恢复目录: Path) -> dict:
        """按备份清单恢复权威状态；清单缺项或摘要不符均计失败。"""
        清单路径 = 备份目录 / 备份清单文件名
        if not 清单路径.is_file():
            return {"成功": False, "是否执行": True, "文件数": 0, "失败原因": [f"备份缺少清单文件: {备份清单文件名}"]}
        try:
            条目表 = json.loads(清单路径.read_text(encoding="utf-8")).get("条目", [])
        except json.JSONDecodeError as 错误:
            return {"成功": False, "是否执行": True, "文件数": 0, "失败原因": [f"备份清单不是合法 JSON: {错误}"]}
        文件数 = 0
        失败原因: list[str] = []
        for 条目 in 条目表:
            相对 = 条目["相对路径"]
            来源 = 备份目录 / 备份内容目录名 / 相对
            if not 来源.is_file():
                失败原因.append(f"备份内容缺失: {相对}")
                continue
            目标 = 恢复目录 / 相对
            目标.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(来源, 目标)
            if 计算摘要(目标) != 条目["摘要"]:
                失败原因.append(f"备份恢复摘要不符: {相对}")
                continue
            self.期望清单[相对], self.来源路径表[相对] = 条目["摘要"], 来源
            文件数 += 1
        return {"成功": not 失败原因, "是否执行": True, "文件数": 文件数,
                "失败原因": 失败原因}
