"""软件物料清单与构建来源证明：SBOM 生成、来源证明生成、保存与真实校验。

第十四阶段工作包 P1-07。仅使用标准库；全部中文业务语义命名。
物料清单为 JSON 兼容字典；校验时对构建目录真实重算 sha256，
缺文件、多文件、摘要不符均明确失败。
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

构建器版本 = "可复现构建器-1.0.0"


def 规范化相对路径(路径: str) -> str:
    """校验并规范化清单内相对路径；非法路径抛 ValueError。"""
    if not 路径 or 路径 in (".", "/", "\\") or 路径.startswith("/") or "\\" in 路径:
        raise ValueError(f"非法相对路径: {路径!r}")
    if any(段 in ("..", ".") for 段 in 路径.split("/")):
        raise ValueError(f"路径逃逸不允许: {路径!r}")
    return 路径


def 内容摘要(内容: bytes) -> str:
    """真实 sha256 摘要。"""
    return hashlib.sha256(内容).hexdigest()


def 文件表聚合摘要(文件摘要表: dict[str, str]) -> str:
    """按路径排序聚合文件摘要，保证输入顺序无关、可复现。"""
    return hashlib.sha256(
        json.dumps(文件摘要表, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class 物料清单与来源证明:
    """生成软件物料清单（SBOM）与构建来源证明，并真实校验构建目录。"""

    @staticmethod
    def 源码摘要(输入文件表: dict[str, str]) -> dict[str, Any]:
        """输入文件表摘要：逐文件真实 sha256 + 排序聚合摘要。"""
        文件摘要表 = {路径: 内容摘要(内容.encode("utf-8"))
                     for 路径, 内容 in 输入文件表.items()}
        return {"算法": "sha256", "值": 文件表聚合摘要(文件摘要表),
                "文件数": len(文件摘要表), "文件摘要表": 文件摘要表}

    @staticmethod
    def 输出摘要(输出文件表: dict[str, str]) -> str:
        """输出文件表聚合摘要（真实计算）。"""
        文件摘要表 = {路径: 内容摘要(内容.encode("utf-8"))
                     for 路径, 内容 in 输出文件表.items()}
        return 文件表聚合摘要(文件摘要表)

    @staticmethod
    def 正式文件表(构建结果: dict[str, Any]) -> list[dict[str, str]]:
        """正式文件：输出文件表逐文件重算 sha256 → 路径+sha256 列表。"""
        return [{"路径": 规范化相对路径(路径), "sha256": 内容摘要(内容.encode("utf-8"))}
                for 路径, 内容 in 构建结果.get("输出文件表", {}).items()]

    def 生成物料清单(self, 构建结果: dict[str, Any]) -> dict[str, Any]:
        """生成软件物料清单（SBOM），JSON 可序列化。"""
        目标平台 = 构建结果.get("目标平台") or platform.platform()
        return {
            "包id": 构建结果["包id"],
            "版本": 构建结果["版本"],
            "源码摘要": self.源码摘要(构建结果.get("输入文件表", {})),
            "构建器版本": 构建器版本,
            "依赖锁": 构建结果.get("依赖锁", ""),
            "目标平台": 目标平台,
            "正式文件": self.正式文件表(构建结果),
            "制品摘要": 构建结果["制品摘要"],
            "验证证据id": 构建结果.get("验证证据id", ""),
            "构建时间": 构建结果.get("构建时间", ""),
            "执行身份": 构建结果.get("执行身份", ""),
        }

    def 生成来源证明(self, 构建结果: dict[str, Any], 验证证据id: str) -> dict[str, Any]:
        """构建来源证明：提交、命令、构建器版本、输入/输出摘要、证据、身份。"""
        return {
            "源码提交": 构建结果.get("源码提交", ""),
            "构建命令": 构建结果.get("构建命令", ""),
            "构建器版本": 构建器版本,
            "输入摘要": self.源码摘要(构建结果.get("输入文件表", {}))["值"],
            "输出摘要": self.输出摘要(构建结果.get("输出文件表", {})),
            "验证证据id": 验证证据id,
            "构建时间": 构建结果.get("构建时间", ""),
            "执行身份": 构建结果.get("执行身份", ""),
            "包id": 构建结果["包id"],
            "版本": 构建结果["版本"],
            "制品摘要": 构建结果["制品摘要"],
        }

    def 生成并保存(self, 构建结果: dict[str, Any], 输出目录: Path | str,
                  验证证据id: str) -> tuple[Path, Path]:
        """生成物料清单与来源证明并写入输出目录，返回两个文件路径。"""
        输出目录 = Path(输出目录)
        输出目录.mkdir(parents=True, exist_ok=True)
        构建结果副本 = dict(构建结果)
        构建结果副本["验证证据id"] = 验证证据id
        物料清单路径 = 输出目录 / "物料清单.json"
        来源证明路径 = 输出目录 / "来源证明.json"
        物料清单路径.write_text(json.dumps(self.生成物料清单(构建结果副本),
                                           ensure_ascii=False, indent=2), encoding="utf-8")
        来源证明路径.write_text(json.dumps(self.生成来源证明(构建结果副本, 验证证据id),
                                           ensure_ascii=False, indent=2), encoding="utf-8")
        return 物料清单路径, 来源证明路径

    def 校验物料清单(self, 物料清单: dict[str, Any],
                  构建目录: Path | str) -> tuple[bool, str]:
        """真实校验：重算构建目录每个正式文件 sha256；缺文件/多文件均失败。"""
        构建目录 = Path(构建目录)
        期望摘要表: dict[str, str] = {}
        try:
            for 条目 in 物料清单.get("正式文件", []):
                期望摘要表[规范化相对路径(条目["路径"])] = 条目["sha256"]
        except (KeyError, TypeError, ValueError) as 错误:
            return False, f"物料清单格式非法: {错误}"
        实际文件表 = {文件.relative_to(构建目录).as_posix()
                    for 文件 in 构建目录.rglob("*") if 文件.is_file()}
        if 实际文件表 != set(期望摘要表):
            缺少 = sorted(set(期望摘要表) - 实际文件表)
            多余 = sorted(实际文件表 - set(期望摘要表))
            return False, f"文件集合不一致（缺少 {缺少}，多余 {多余}）"
        for 路径, 期望摘要 in 期望摘要表.items():
            实际摘要 = 内容摘要((构建目录 / 路径).read_bytes())
            if 实际摘要 != 期望摘要:
                return False, f"文件摘要不符: {路径}（清单 {期望摘要[:12]}… 实际 {实际摘要[:12]}…）"
        return True, f"校验通过：{len(期望摘要表)} 个正式文件摘要一致"
