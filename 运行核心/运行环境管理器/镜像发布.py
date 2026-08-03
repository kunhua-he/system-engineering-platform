"""镜像发布工具（发布者角色专属）：环境目录 → 文件清单 → 制品摘要 →
远程镜像清单 → Ed25519 签名 → 防路径穿越打包 → 可验证元数据输出。

发布流程（发布环境镜像）：
1. 收集：遍历环境目录全部正式文件（排除 __pycache__/.pyc/.pyo/
   .构建中_/.镜像中_/.制品下载_ 易变文件），生成 文件清单
   （相对路径 → sha256 + 大小）。
2. 摘要：制品摘要 = 环境目录稳定摘要（复用 远程镜像.计算制品摘要）；
   文件清单摘要 = 逐文件 sha256 稳定清单摘要（复用 远程镜像.计算文件清单摘要，
   与下载侧解包后复校验衔接）。
3. 清单：生成 远程镜像清单（制品摘要/依赖锁摘要/python版本/系统版本/
   架构/信任指纹/文件清单/文件清单摘要/元数据），字段与 远程镜像校验器
   匹配契约一致。
4. 签名：复用 远程镜像.签名清单（Ed25519 经 支持库.适配层.密码签名提供者
   公开入口），签名正文 = 清单稳定序列化（不含签名键，跨端一致）；
   得到 清单摘要 + 签名hex + 公钥指纹；公钥PEM 提供时经 验证清单签名 自验。
5. 打包：制品.tar.gz 防路径穿越（拒绝绝对路径/../符号链接逃逸）。
6. 输出：制品.tar.gz + 镜像清单.json + 镜像签名.txt + 制品摘要.txt
   + 发布元数据.json（可验证：清单摘要重算 + 公钥验签）。

验证约定（供镜像校验器/代理下载侧使用）：
- 清单摘要 = sha256(剔除"签名"字段后的镜像清单稳定序列化字节)。
- 签名原文 b64 = 同一稳定序列化的 base64；验证方持公钥即可验签
  （与 远程镜像.验证清单签名 完全同源，无第二套签名框架）。
- 发布元数据.json 已携带 清单摘要 与 签名原文b64，验证零歧义。

发布者角色边界：
- 签名私钥仅发布者角色（发布者视图/角色等级 5）持有与使用；本工具
  只接收私钥，绝不把私钥写入任何输出文件、结果或元数据。
- 发布环境镜像 强制校验 私钥PEM 非空，缺失即拒绝发布。
- 产物可验证性只依赖 公钥指纹 + 签名hex + 清单摘要；验证方持公钥即可。

镜像站不可用说明：本工具不访问网络，只生成本地产物（可独立验证）；
端到端上线由镜像站配置与下载侧（远程镜像.下载镜像制品）负责。
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 运行核心.运行环境管理器.远程镜像 import (
    _计入制品摘要,
    _清单稳定序列化,
    计算制品摘要,
    计算文件清单摘要,
    签名清单,
    验证清单签名,
)
from 支持库.适配层.密码签名提供者 import 公钥指纹

发布清单文件名 = "镜像清单.json"
发布制品文件名 = "制品.tar.gz"
发布签名文件名 = "镜像签名.txt"
发布摘要文件名 = "制品摘要.txt"
发布元数据文件名 = "发布元数据.json"

发布私钥缺失 = "私钥缺失"
发布非法路径 = "非法路径"
发布签名失败 = "签名失败"
发布失败 = "发布失败"

签名算法 = "Ed25519"


@dataclass
class 发布结果:
    """发布工具结论：产物路径 + 可验证摘要/签名元数据。"""

    成功: bool
    错误码: str = ""
    错误说明: str = ""
    制品摘要: str = ""
    清单摘要: str = ""
    签名hex: str = ""
    公钥指纹: str = ""
    文件数: int = 0
    输出目录: str = ""
    产物表: dict[str, str] = field(default_factory=dict)


def _系统版本详情() -> str:
    """真实系统版本（与镜像匹配契约一致：macOS 走 sw_vers，其余回退）。"""
    import subprocess

    try:
        结果 = subprocess.run(["sw_vers"], capture_output=True, timeout=10)
        if 结果.returncode == 0:
            return 结果.stdout.decode("utf-8", "ignore").strip()
    except Exception:
        pass
    return f"{platform.system()} {platform.release()}"


def _收集正式文件(制品根: Path) -> list[tuple[str, Path]]:
    """收集环境目录正式文件（相对路径文本, 文件路径）。

    排除易变文件；符号链接一律解析真实目标：
    - 目标逃逸出环境目录 → 抛 ValueError（发布非法路径）；
    - 目录符号链接 → 抛 ValueError（不支持发布）。
    打包/解包全程拒绝符号链接逃逸。
    """
    根 = Path(制品根).resolve()
    结果: list[tuple[str, Path]] = []
    for 候选 in 根.rglob("*"):
        if 候选.is_symlink():
            try:
                真实 = 候选.resolve(strict=True)
            except (OSError, RuntimeError) as 错误:
                raise ValueError(f"符号链接无法解析: {候选.name}") from 错误
            if 根 not in 真实.parents:
                raise ValueError(f"符号链接逃逸出环境目录: {候选.name}")
            if not 真实.is_file():
                raise ValueError(f"目录符号链接不支持发布: {候选.name}")
            相对 = 候选.relative_to(根)
            if _计入制品摘要(相对):
                结果.append((相对.as_posix(), 候选))
            continue
        if 候选.is_file():
            相对 = 候选.relative_to(根)
            if _计入制品摘要(相对):
                结果.append((相对.as_posix(), 候选))
    return 结果


def _安全打包(文件表: list[tuple[str, Path]], 输出路径: Path, *,
              根: Path | None = None) -> None:
    """防路径穿越打包：拒绝绝对路径/../符号链接逃逸成员，拒绝重复路径。"""
    已见: set[str] = set()
    with tarfile.open(输出路径, "w:gz") as 压缩包:
        for 相对文本, 文件 in sorted(文件表, key=lambda 项: 项[0]):
            if (not 相对文本 or 相对文本.startswith("/")
                    or ".." in Path(相对文本).parts):
                raise ValueError(f"非法成员路径: {相对文本}")
            if 相对文本 in 已见:
                raise ValueError(f"重复成员路径: {相对文本}")
            已见.add(相对文本)
            if 根 is not None:
                真实 = Path(文件).resolve()
                if 真实 != 根 and 根 not in 真实.parents:
                    raise ValueError(f"成员逃逸出环境目录: {相对文本}")
            压缩包.add(文件, arcname=相对文本, recursive=False)


def 发布环境镜像(环境目录, 输出目录, 私钥PEM, *, 元数据: dict[str, Any],
                公钥PEM: str = "") -> 发布结果:
    """发布环境镜像：收集 → 清单 → 摘要 → 签名 → 打包 → 输出可验证元数据。

    参数：
    - 环境目录：环境制品根目录（bin/ 等直接在其下）。
    - 输出目录：发布产物输出目录（不存在则创建）。
    - 私钥PEM：发布者签名私钥（Ed25519，经 远程镜像.签名清单 → 支持库.
      适配层 公开入口签名），仅发布者角色持有；空值直接拒绝发布。
    - 元数据：发布元数据（信任指纹/发布者/版本等业务字段），原样写入清单。
    - 公钥PEM：可选验证公钥；提供时计算 公钥指纹 并经 验证清单签名 自验。

    返回 发布结果：成功时携带 制品摘要/清单摘要/签名hex/公钥指纹/
    文件数/输出目录/产物表；失败返回稳定错误码（私钥缺失/非法路径/
    签名失败/发布失败）。
    """
    私钥文本 = str(私钥PEM or "")
    if not 私钥文本.strip():
        return 发布结果(False, 错误码=发布私钥缺失,
                         错误说明="签名私钥必须非空（仅发布者角色持有）")
    try:
        制品根 = Path(环境目录).resolve()
        if not 制品根.is_dir():
            return 发布结果(False, 错误码=发布失败, 错误说明="环境目录不存在")
        输出根 = Path(输出目录)
        输出根.mkdir(parents=True, exist_ok=True)
        文件表 = _收集正式文件(制品根)
        if not 文件表:
            return 发布结果(False, 错误码=发布失败,
                             错误说明="环境目录没有可发布文件")
        文件清单: dict[str, dict[str, Any]] = {}
        for 相对文本, 文件 in 文件表:
            文件清单[相对文本] = {
                "sha256": hashlib.sha256(文件.read_bytes()).hexdigest(),
                "大小": 文件.stat().st_size,
            }
        制品摘要 = 计算制品摘要(制品根)
        文件清单摘要 = 计算文件清单摘要(制品根)
        依赖锁路径 = 制品根 / "依赖锁.json"
        依赖锁摘要 = (hashlib.sha256(依赖锁路径.read_bytes()).hexdigest()
                      if 依赖锁路径.is_file() else "")
        清单 = {
            "制品摘要": 制品摘要,
            "依赖锁摘要": 依赖锁摘要,
            "python版本": sys.version.split()[0],
            "系统版本": _系统版本详情(),
            "架构": platform.machine(),
            "信任指纹": str(元数据.get("信任指纹", "") or ""),
            "文件清单": 文件清单,
            "文件清单摘要": 文件清单摘要,
            "元数据": dict(元数据),
        }
        签名正文 = _清单稳定序列化(清单)
        清单摘要 = hashlib.sha256(签名正文).hexdigest()
        签名原文b64 = base64.b64encode(签名正文).decode("ascii")
        签名结果 = 签名清单(清单, 私钥文本)
        if not 签名结果.成功:
            return 发布结果(False, 错误码=发布签名失败,
                             错误说明=f"镜像清单签名失败: {签名结果.错误码}: "
                                      f"{签名结果.错误说明}")
        签名后清单 = 签名结果.值
        指纹 = ""
        if 公钥PEM:
            指纹结果 = 公钥指纹(str(公钥PEM))
            if not 指纹结果.成功:
                return 发布结果(False, 错误码=发布签名失败,
                                 错误说明=f"公钥指纹计算失败: {指纹结果.错误说明}")
            指纹 = str(指纹结果.值)
            自验结果 = 验证清单签名(签名后清单, str(公钥PEM))
            if not 自验结果.成功 or not 自验结果.值:
                return 发布结果(False, 错误码=发布签名失败,
                                 错误说明="私钥与公钥不匹配（自验签名失败）")
        制品包路径 = 输出根 / 发布制品文件名
        _安全打包(文件表, 制品包路径, 根=制品根)
        (输出根 / 发布清单文件名).write_text(
            json.dumps(签名后清单, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")), encoding="utf-8")
        (输出根 / 发布签名文件名).write_text(
            str(签名后清单["签名"]) + "\n", encoding="utf-8")
        (输出根 / 发布摘要文件名).write_text(制品摘要 + "\n", encoding="utf-8")
        (输出根 / 发布元数据文件名).write_text(json.dumps({
            "制品摘要": 制品摘要,
            "清单摘要": 清单摘要,
            "签名hex": str(签名后清单["签名"]),
            "算法": 签名算法,
            "公钥指纹": 指纹,
            "签名原文b64": 签名原文b64,
            "文件清单摘要": 文件清单摘要,
            "文件数": len(文件表),
            "生成时间": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "生成环境": {
                "python版本": sys.version.split()[0],
                "系统版本": _系统版本详情(),
                "架构": platform.machine(),
            },
            "产物": {
                "镜像清单": 发布清单文件名,
                "制品包": 发布制品文件名,
                "签名": 发布签名文件名,
                "制品摘要": 发布摘要文件名,
                "发布元数据": 发布元数据文件名,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except ValueError as 错误:
        return 发布结果(False, 错误码=发布非法路径, 错误说明=str(错误))
    except (OSError, tarfile.TarError) as 错误:
        return 发布结果(False, 错误码=发布失败,
                         错误说明=f"发布失败: {错误}")
    return 发布结果(True, 制品摘要=制品摘要, 清单摘要=清单摘要,
                     签名hex=str(签名后清单["签名"]), 公钥指纹=指纹,
                     文件数=len(文件表), 输出目录=str(输出根),
                     产物表={"镜像清单": 发布清单文件名,
                             "制品包": 发布制品文件名,
                             "签名": 发布签名文件名,
                             "制品摘要": 发布摘要文件名,
                             "发布元数据": 发布元数据文件名})
