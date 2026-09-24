"""核心快照与启动监督器：不可变平台核心快照 + 签名/完整性验证 + 激活指针。

总补修边界：
- 快照文件路径拒绝逃逸（规范化相对路径）。
- 校验快照必须真正调用 Ed25519 验证公钥、签名正文与实际快照文件摘要
  （磁盘篡改检测），不允许改签名后仍校验成功。
- 快照包含三个核心版本、状态结构兼容范围、回滚许可、迁移方式、摘要和签名。
- 启动监督器位于核心外；新核心失败只恢复旧指针；引用归零前禁止删除。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from 平台控制面.包仓库 import 规范化相对路径
from 平台控制面.包仓库.路径安全 import 安全迭代文件
from 支持库.适配层 import 签名 as Ed签名, 验证签名 as Ed验证, 内容摘要
from 支持库.后端.文件系统支持库.文件操作 import 写入文件
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.运行缓存 import 解析运行缓存根


class 核心快照管理:
    """核心快照服务（唯一写入口：平台状态.核心快照）。"""

    def __init__(self, 状态, 快照根目录: Path | None = None) -> None:
        self.状态 = 状态
        # 缺省值经唯一解析器（禁止 cwd 依赖的裸相对 `工程缓存/核心快照`）：制品进程 cwd 是
        # 制品目录，裸相对值会把快照写进不可变制品；源码态回落 `<系统根>/工程缓存`（同旧值）。
        self.快照根目录 = Path(快照根目录) if 快照根目录 else \
            解析运行缓存根(Path(__file__).resolve().parents[1]) / "核心快照"
        self.快照根目录.mkdir(parents=True, exist_ok=True)

    def 创建快照(self, *, 运行核心版本: str, 前端核心版本: str, 后端核心版本: str,
                状态兼容范围: str = "1.0.0-1.3.0", 回滚许可: bool = 真,
                迁移方式: str = "扩展", 文件表: dict[str, str] | None = None) -> str:
        """创建不可变核心快照；文件路径拒绝逃逸；同内容同摘要。"""
        快照id = uuid.uuid4().hex[:16]
        核心版本 = {"运行核心": 运行核心版本, "前端核心": 前端核心版本, "后端核心": 后端核心版本}
        文件表 = 文件表 or {"核心.manifest": json.dumps({"运行核心": 运行核心版本})}
        # 路径安全校验（先于任何写入）
        规范化文件表 = {}
        for 路径, 内容 in 文件表.items():
            规范化文件表[规范化相对路径(路径)] = 内容
        文件摘要 = {路径: hashlib.sha256(内容.encode("utf-8")).hexdigest()
                    for 路径, 内容 in 规范化文件表.items()}
        摘要 = 内容摘要(json.dumps({"快照id": 快照id, "核心版本": 核心版本,
                                   "文件摘要": 文件摘要}, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        记录 = {"快照id": 快照id, "摘要": 摘要,
                "核心版本": json.dumps(核心版本, ensure_ascii=False),
                "状态兼容": 状态兼容范围, "回滚许可": str(回滚许可),
                "迁移方式": 迁移方式, "签名": "", "签名者": "", "状态": "未签名"}
        self.状态.写入记录("核心快照", 记录)
        快照目录 = self.快照根目录 / 快照id
        快照目录.mkdir(parents=True, exist_ok=True)
        for 路径, 内容 in 规范化文件表.items():
            # 落盘经**唯一写入腿**（`文件系统支持库.文件操作.写入文件`，2026-09-25 收口）：
            # 平台控制面 在 `允许依赖表` 里允许依赖 支持库；原子写与父目录创建由唯一腿提供，
            # 本文件不再裸 `write_text`。**失败仍抛 `OSError`**（调用方按原契约收口）。
            写结果 = 写入文件(str(快照目录 / 路径), 内容)
            if not 写结果.成功:
                raise OSError(f"{写结果.错误码}: {写结果.错误说明}")
        写结果 = 写入文件(str(快照目录 / "摘要.json"), json.dumps({"摘要": 摘要}, ensure_ascii=False))
        if not 写结果.成功:
            raise OSError(f"{写结果.错误码}: {写结果.错误说明}")
        return 快照id

    def 签名快照(self, *, 快照id: str, 私钥PEM: str, 发布者: str) -> tuple[bool, str]:
        记录 = self.状态.读取记录("核心快照", "快照id", 快照id)
        if 记录 is None:
            return 假, "快照不存在"
        正文 = json.dumps({"快照id": 快照id, "摘要": 记录["摘要"], "发布者": 发布者},
                          ensure_ascii=False, sort_keys=True)
        签名值 = Ed签名(私钥PEM, 正文.encode("utf-8"))
        信任 = self.状态.读取记录("信任", "发布者", 发布者)
        if 信任 is None or not Ed验证(信任["公钥"], 正文.encode("utf-8"), 签名值):
            return 假, "签名验证失败或发布者不受信"
        self.状态.条件更新("核心快照", {"签名": 签名值, "签名者": 发布者,
                                  "状态": "已签名"}, "快照id=?", (快照id,))
        return 真, "快照已签名"

    def 校验快照(self, *, 快照id: str) -> tuple[bool, str]:
        """校验：Ed25519 验证公钥+签名正文 + 实际快照文件摘要 + 信任/撤销/过期。"""
        记录 = self.状态.读取记录("核心快照", "快照id", 快照id)
        if 记录 is None:
            return 假, "快照不存在"
        if not 记录["签名"]:
            return 假, "快照未签名"
        信任 = self.状态.读取记录("信任", "发布者", 记录["签名者"])
        if 信任 is None or 信任["状态"] != "有效":
            return 假, f"发布者不受信或已撤销: {记录['签名者']}"
        # 1. Ed25519 验证签名正文（防签名伪造）
        正文 = json.dumps({"快照id": 快照id, "摘要": 记录["摘要"], "发布者": 记录["签名者"]},
                          ensure_ascii=False, sort_keys=True)
        if not Ed验证(信任["公钥"], 正文.encode("utf-8"), 记录["签名"]):
            return 假, "签名伪造或失效（Ed25519 验证失败）"
        # 2. 实际快照目录文件摘要（磁盘篡改检测）
        快照目录 = self.快照根目录 / 快照id
        核心版本 = json.loads(记录["核心版本"])
        实际文件摘要 = {}
        # #159：原 `rglob` + `is_file()` 跟随软链 —— 快照目录里的软链会把根外文件
        # 读进快照摘要（篡改检测失真）。走唯一原语，跳过符号链接。
        for 文件 in 安全迭代文件(快照目录):
            if 文件.name != "摘要.json":
                实际文件摘要[文件.relative_to(快照目录).as_posix()] = \
                    hashlib.sha256(文件.read_bytes()).hexdigest()
        if not 实际文件摘要:
            return 假, "快照目录无正式文件"
        实际摘要 = 内容摘要(json.dumps(
            {"快照id": 快照id, "核心版本": 核心版本, "文件摘要": 实际文件摘要},
            ensure_ascii=False, sort_keys=True).encode("utf-8"))
        if 实际摘要 != 记录["摘要"]:
            return 假, "快照内容被篡改（磁盘摘要与记录不符）"
        return 真, "快照完整且签名有效"

    def 健康检查(self, *, 快照id: str, 调用: Callable[[], bool]) -> tuple[bool, str]:
        """影子启动/健康检查：调用方提供真实调用函数（真实执行）。"""
        有效, 消息 = self.校验快照(快照id=快照id)
        if not 有效:
            return 假, 消息
        try:
            return (真, "健康") if 调用() else (假, "健康检查失败")
        except Exception as 错误:
            return 假, f"健康检查异常: {错误}"
