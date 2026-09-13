"""包仓库服务：内容寻址制品、版本、摘要、签名、安装和保留策略。

防篡改边界（总补修）：
- 文件路径必须规范化相对路径：拒绝绝对路径、空路径、`..`、符号链接、目录覆盖、分隔符逃逸。
- 构建使用临时目录，文件清单校验完成后原子发布；同一包id+版本只能绑定一个内容摘要。
- 签名正文覆盖：包id/版本/发布者/权限/资源预算/物料清单/来源证据/全部正式文件摘要。
- 签名校验重新读取制品目录实际文件逐一计算摘要，不能只比较数据库文件清单。
- 安装前后都校验摘要；安装采用临时目录+原子替换。
- 信任目录检查发布者状态、有效期和撤销；签名私钥不进日志/证据/说明书。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from 平台控制面.包仓库.路径安全 import 规范化相对路径
from 平台控制面.包仓库.签名能力 import 签名能力
from 平台控制面.包仓库.安装能力 import 安装能力
from 支持库.适配层 import 内容摘要

# 二进制资产 hex 前缀（与 平台客户端制品/_二进制前缀、可复现构建器 一致）
_二进制前缀 = "hexfile:"


class 包仓库(签名能力, 安装能力):
    """包仓库服务（唯一写入口：平台状态.制品/信任）。"""

    def __init__(self, 状态, 制品根目录: Path | None = None) -> None:
        self.状态 = 状态
        self.制品根目录 = Path(制品根目录) if 制品根目录 else Path("工程缓存/制品仓库")
        self.制品根目录.mkdir(parents=True, exist_ok=True)

    # ---- 构建与内容寻址 ----
    def 构建制品(self, *, 包id: str, 版本: str, 文件表: dict[str, str],
                构建输入: dict[str, Any], 文件模式: dict[str, int] | None = None) -> tuple[bool, str, str]:
        """冻结候选包：临时目录构建 → 路径安全校验 → 摘要 → 原子发布。

        同一包id+版本只能绑定一个内容摘要；不同摘要必须换版本或拒绝。
        """
        # 路径安全校验（先于任何写入）
        规范化文件表: dict[str, str] = {}
        for 路径, 内容 in 文件表.items():
            规范化 = 规范化相对路径(路径)
            规范化文件表[规范化] = 内容
        # 同包同版本唯一性：已存在同版本制品时摘要必须一致
        已有表 = self.状态.查询记录("制品", "包id=? AND 版本=?", (包id, 版本))
        def _文件摘要(内容: str) -> tuple[str, int]:
            """二进制资产按解码后字节计算摘要（与安装还原一致，避免 hex 文本旧制品复用）。"""
            if 内容.startswith(_二进制前缀):
                字节 = bytes.fromhex(内容[len(_二进制前缀):])
                return hashlib.sha256(字节).hexdigest(), len(字节)
            return hashlib.sha256(内容.encode("utf-8")).hexdigest(), len(内容.encode("utf-8"))

        文件清单 = {}
        for 路径, 内容 in 规范化文件表.items():
            摘要, 大小 = _文件摘要(内容)
            信息 = {"sha256": 摘要, "大小": 大小}
            if 文件模式 is not None and 路径 in 文件模式:
                信息["模式"] = int(文件模式[路径]) & 0o7777
            文件清单[路径] = 信息
        正文 = json.dumps({"包id": 包id, "版本": 版本, "文件清单": 文件清单,
                           "构建输入": 构建输入}, ensure_ascii=False, sort_keys=True)
        制品摘要 = 内容摘要(正文.encode("utf-8"))
        if 已有表:
            if 已有表[0]["制品摘要"] != 制品摘要:
                return False, f"同一包同一版本禁止双摘要（已存在 {已有表[0]['制品摘要'][:12]}…）", 制品摘要
            return True, "同版同摘要（幂等复用）", 制品摘要
        # 临时目录构建 → 校验 → 原子发布
        临时目录 = self.制品根目录 / f".临时_{uuid.uuid4().hex[:8]}"
        临时目录.mkdir(parents=True)
        try:
            for 路径, 内容 in 规范化文件表.items():
                目标 = 临时目录 / 路径
                目标.parent.mkdir(parents=True, exist_ok=True)
                if 内容.startswith(_二进制前缀):
                    目标.write_bytes(bytes.fromhex(内容[len(_二进制前缀):]))
                else:
                    目标.write_text(内容, encoding="utf-8")
                if 文件模式 is not None and 路径 in 文件模式:
                    目标.chmod(int(文件模式[路径]) & 0o7777)
            # 逐一核对磁盘实际文件摘要（防写入前已存在文件干扰）
            for 路径, 内容 in 规范化文件表.items():
                实际 = hashlib.sha256((临时目录 / 路径).read_bytes()).hexdigest()
                if 实际 != 文件清单[路径]["sha256"]:
                    raise RuntimeError(
                        f"临时构建校验失败: {路径}（实际 {实际[:12]} ≠ 期望 {文件清单[路径]['sha256'][:12]}）"
                    )
            物料清单 = {"包id": 包id, "版本": 版本, "文件清单": 文件清单, "构建输入": 构建输入}
            (临时目录 / "物料清单.json").write_text(
                json.dumps(物料清单, ensure_ascii=False, indent=2), encoding="utf-8")
            # 原子发布：临时目录改名到内容寻址目录（同摘要已存在则跳过）
            最终目录 = self.制品根目录 / 制品摘要
            if not 最终目录.exists():
                os.rename(临时目录, 最终目录)
            else:
                shutil.rmtree(临时目录)
        except Exception as 错误:
            shutil.rmtree(临时目录, ignore_errors=True)
            return False, f"构建失败: {错误}", ""
        self.状态.写入记录("制品", {
            "制品摘要": 制品摘要, "包id": 包id, "版本": 版本,
            "文件清单": json.dumps(文件清单, ensure_ascii=False),
            "物料清单": json.dumps(物料清单, ensure_ascii=False),
            "来源证据": json.dumps(构建输入, ensure_ascii=False),
            "签名": "", "签名者": "", "签名时间": "", "状态": "未签名",
            "构建输入": json.dumps(构建输入, ensure_ascii=False),
        })
        return True, "制品已构建", 制品摘要

    def 可复现校验(self, *, 包id: str, 版本: str, 文件表: dict[str, str],
                  构建输入: dict[str, Any]) -> tuple[bool, str]:
        """同源码同输入在独立仓库重新构建摘要一致；输入变化摘要变化。

        第二次构建必须在**独立制品根目录 + 独立状态库**的第二个仓库实例上
        真实重跑完整构建流程。同实例第二次调用会命中「同版同摘要幂等复用」
        分支直接返回既有摘要，比摘要恒等（假绿），证明不了可复现性。
        """
        成功1, 消息1, 摘要1 = self.构建制品(
            包id=包id, 版本=版本, 文件表=文件表, 构建输入=构建输入)
        if not 成功1:
            return False, f"首次构建失败: {消息1}"
        独立仓库, 独立根 = self._新建独立仓库()
        try:
            成功2, 消息2, 摘要2 = 独立仓库.构建制品(
                包id=包id, 版本=版本, 文件表=文件表, 构建输入=构建输入)
            if not 成功2:
                return False, f"独立复现构建失败: {消息2}"
            if 摘要1 != 摘要2:
                return False, f"同输入独立构建摘要不一致: {摘要1} vs {摘要2}"
            文件表2 = dict(文件表)
            文件表2["新增文件.txt"] = "x"
            成功3, 消息3, 摘要3 = 独立仓库.构建制品(
                包id=包id, 版本=版本 + "b", 文件表=文件表2, 构建输入=构建输入)
            if not 成功3:
                return False, f"输入变化构建失败: {消息3}"
        finally:
            独立仓库.状态.关闭()
            shutil.rmtree(独立根, ignore_errors=True)
        if 摘要3 == 摘要1:
            return False, "输入变化但摘要未变化"
        return True, "可复现构建验证通过"

    def _新建独立仓库(self) -> tuple["包仓库", Path]:
        """全新制品根目录 + 全新状态库的第二个仓库实例（含临时根，供调用方清理）。"""
        import tempfile

        from 平台控制面.平台状态 import 平台状态

        临时根 = Path(tempfile.mkdtemp(prefix="可复现校验_"))
        状态 = 平台状态(临时根 / "状态", 项目id="平台控制面")
        return 包仓库(状态, 制品根目录=临时根 / "制品"), 临时根


__all__ = ["包仓库", "规范化相对路径"]
