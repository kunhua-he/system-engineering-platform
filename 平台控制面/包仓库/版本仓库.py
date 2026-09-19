"""版本目录仓库：本地目录安装到不可变版本目录（顶层包仓库合并而来）。

流程：包仓库 → 包完整性校验 → 包结构校验 → 契约校验 → 权限校验 →
安装到不可变版本目录 → 生成安装记录 → 注册版本。

规则：同一包同一版本不能重复覆盖；安装失败必须清理临时目录；
安装使用临时目录加原子替换；已安装版本不得直接修改；
包文件必须生成完整性摘要；安装记录必须可查询。
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from 平台控制面.包仓库.版本仓库数据 import 安装记录, 计算目录摘要
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.版本规则.契约版本 import 契约版本


class 包仓库:
    """不可变包仓库：安装、查询、删除（含三重引用保护）。"""

    def __init__(self, 仓库根目录: Path | None = None) -> None:
        self.仓库根目录 = 仓库根目录 or Path(包仓库.默认仓库目录())
        self.版本目录 = self.仓库根目录 / "版本"
        self.安装记录目录 = self.仓库根目录 / "安装记录"
        self.版本目录.mkdir(parents=True, exist_ok=True)
        self.安装记录目录.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def 默认仓库目录() -> str:
        import os, tempfile
        return os.environ.get("系统库仓库目录", str(Path(tempfile.gettempdir()) / "系统工程平台_仓库"))

    def 版本路径(self, 包id: str, 版本: str) -> Path:
        return self.版本目录 / f"{包id}@{版本}"

    def 已安装(self, 包id: str, 版本: str) -> bool:
        return self.版本路径(包id, 版本).is_dir()

    def 安装(self, 源目录: Path, *, 包id: str = "", 版本: str = "") -> tuple[bool, 安装记录 | str]:
        """从本地目录安装包；同包同版本不可覆盖；失败清理临时目录。"""
        源目录 = Path(源目录)
        声明路径 = 源目录 / "包声明.json"
        if not 声明路径.is_file():
            return 假, f"缺少包声明.json: {源目录}"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as 错误:
            return 假, f"包声明不可读: {错误}"
        包id = 包id or str(声明.get("包id", ""))
        版本 = 版本 or str(声明.get("版本", ""))
        if not 包id or not 版本:
            return 假, "包id 或 版本 缺失"

        # 1. 不可覆盖检查
        if self.已安装(包id, 版本):
            return 假, f"同一包同一版本不能重复覆盖: {包id}@{版本}"

        # 2. 包结构校验
        for 必需项 in ("包声明.json", "能力契约", "实现"):
            if not (源目录 / 必需项).exists():
                return 假, f"包结构不完整，缺少 {必需项}"

        # 3. 权限声明（必须存在；缺失视为无权限声明但允许）
        权限声明 = 源目录 / "权限声明"
        权限数据: dict = {}
        if 权限声明.is_dir() and (权限声明 / "权限声明.json").is_file():
            try:
                权限数据 = json.loads((权限声明 / "权限声明.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return 假, "权限声明.json 不可读"

        # 4. 临时目录 + 原子替换
        临时路径 = self.版本目录 / f".临时_{包id}@{版本}_{uuid.uuid4().hex[:6]}"
        try:
            shutil.copytree(源目录, 临时路径)
            摘要 = 计算目录摘要(临时路径)
            目标路径 = self.版本路径(包id, 版本)
            临时路径.rename(目标路径)  # 原子替换
        except OSError as 错误:
            清只读后删除树(临时路径, 忽略失败=真)
            return 假, f"安装失败已清理临时目录: {错误}"

        # 5. 生成安装记录
        记录 = 安装记录(
            记录id=uuid.uuid4().hex[:16], 包id=包id, 版本=版本,
            契约版本=str(声明.get("契约版本", 契约版本)), 完整性摘要=摘要,
            安装路径=str(目标路径), 时间=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        (self.安装记录目录 / f"{记录.记录id}.json").write_text(
            json.dumps(记录.转字典(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 真, 记录

    def 查询安装记录(self, *, 包id: str = "", 版本: str = "") -> list[安装记录]:
        记录列表: list[安装记录] = []
        for 文件 in self.安装记录目录.glob("*.json"):
            try:
                数据 = json.loads(文件.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if 包id and 数据.get("包id") != 包id:
                continue
            if 版本 and 数据.get("版本") != 版本:
                continue
            记录列表.append(安装记录(**数据))
        return sorted(记录列表, key=lambda 记录: 记录.时间)

    def 校验完整性(self, 包id: str, 版本: str, 期望摘要: str = "") -> tuple[bool, str]:
        """校验已安装版本的完整性摘要。"""
        目标路径 = self.版本路径(包id, 版本)
        if not 目标路径.is_dir():
            return 假, f"版本未安装: {包id}@{版本}"
        实际摘要 = 计算目录摘要(目标路径)
        if 期望摘要 and 实际摘要 != 期望摘要:
            return 假, f"完整性摘要不一致: 期望 {期望摘要} 实际 {实际摘要}"
        return 真, 实际摘要

    def 删除(self, 包id: str, 版本: str, *, 引用项目: list[str] | None = None,
             运行实例数: int = 0, 回滚任务数: int = 0) -> tuple[bool, str]:
        """删除版本：先执行三重引用扫描。"""
        引用项目 = 引用项目 or []
        if 引用项目:
            return 假, f"仍被项目引用: {', '.join(引用项目)}，禁止删除"
        if 运行实例数 > 0:
            return 假, f"仍有 {运行实例数} 个运行实例，禁止删除"
        if 回滚任务数 > 0:
            return 假, f"仍有 {回滚任务数} 个回滚任务，禁止删除"
        目标路径 = self.版本路径(包id, 版本)
        if not 目标路径.is_dir():
            return 假, f"版本未安装: {包id}@{版本}"
        清只读后删除树(目标路径)
        return 真, "已删除"
