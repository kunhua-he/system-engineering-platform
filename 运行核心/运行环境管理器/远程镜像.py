"""远程镜像契约与校验器：环境缓存的可选加速来源（默认关闭）。

原则：
- 远程镜像只作为"已构建环境制品"的来源：本机无 pip 网络时，从镜像
  拉取与本地期望完全一致的环境制品，经全部条件匹配才允许命中。
- 匹配条件：制品摘要 + 依赖锁 + Python 版本 + 系统版本 + 架构 全部一致；
  任一不匹配 → 拒绝（镜像摘要不匹配），不得静默使用不可信环境。
- 错误码三态：镜像不可用（镜像服务不可访问）、镜像摘要不匹配（任一
  匹配条件不符）、镜像下载失败（下载/解压/复校验失败）。
- 默认关闭：启用=false 时本模块不参与 确保环境 流程，本地缓存行为零变化。
- 制品摘要 = 环境目录稳定摘要（sha256 文件路径+内容，排除易变文件），
  用于下载后防篡改比对：下载内容与镜像声明不符 → 拒绝。
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

镜像不可用 = "镜像不可用"
镜像摘要不匹配 = "镜像摘要不匹配"
镜像下载失败 = "镜像下载失败"

最大清单字节数 = 8 * 1024 * 1024  # 8 MiB
默认最大制品字节数 = 1024 * 1024 * 1024  # 1 GiB
默认清单超时秒 = 30
默认下载超时秒 = 300

清单文件名 = "镜像清单.json"
制品文件名 = "制品.tar.gz"


@dataclass
class 远程镜像配置:
    """远程镜像配置契约：镜像地址 + 启用开关 + 信任指纹（默认关闭）。"""

    启用: bool = False
    镜像地址: str = ""
    信任指纹: str = ""


@dataclass
class 镜像校验请求:
    """本地期望侧匹配条件（校验器比对基准）。"""

    依赖锁摘要: str
    python版本: str
    系统版本: str
    架构: str


@dataclass
class 镜像校验结果:
    """校验器结论：全部匹配才允许命中。"""

    允许命中: bool
    制品摘要: str = ""
    错误码: str = ""
    错误说明: str = ""


@dataclass
class 镜像操作结果:
    """镜像清单/制品下载操作结果。"""

    成功: bool
    错误码: str = ""
    错误说明: str = ""
    清单: dict[str, Any] | None = None


def 读取远程镜像配置(配置文件: Path | None = None) -> 远程镜像配置:
    """读取远程镜像配置；缺省或文件无效/缺失 → 默认关闭（启用=false）。

    配置结构：{"启用": true, "镜像地址": "...", "信任指纹": "..."}。
    未启用时 确保环境 完全走现有本地缓存路径（行为零变化）。
    """
    if 配置文件 is None or not Path(配置文件).is_file():
        return 远程镜像配置()
    try:
        数据 = json.loads(Path(配置文件).read_text(encoding="utf-8"))
        if not isinstance(数据, dict):
            return 远程镜像配置()
        启用 = bool(数据.get("启用", False))
        镜像地址 = str(数据.get("镜像地址", "") or "")
        信任指纹 = str(数据.get("信任指纹", "") or "")
    except (OSError, ValueError):
        return 远程镜像配置()
    return 远程镜像配置(启用=启用, 镜像地址=镜像地址, 信任指纹=信任指纹)


def 计算制品摘要(制品目录: Path) -> str:
    """制品摘要：环境目录稳定摘要（sha256 文件路径+内容，排除易变文件）。

    排除 __pycache__/.pyc/.pyo/构建中 临时目录，保证跨次、跨机稳定；
    用于镜像制品下载后的防篡改比对（与镜像清单声明的制品摘要一致）。
    """
    哈希器 = hashlib.sha256()
    制品根 = Path(制品目录).resolve()
    计入文件表: list[tuple[Path, Path]] = []
    for 文件 in 制品根.rglob("*"):
        if 文件.is_file():
            相对路径 = 文件.relative_to(制品根)
            if _计入制品摘要(相对路径):
                计入文件表.append((相对路径, 文件))
    for 相对路径, 文件 in sorted(计入文件表, key=lambda 项: 项[0].as_posix()):
        哈希器.update(相对路径.as_posix().encode("utf-8"))
        哈希器.update(b"\x00")
        哈希器.update(文件.read_bytes())
        哈希器.update(b"\x00")
    return 哈希器.hexdigest()[:16]


def _计入制品摘要(相对路径: Path) -> bool:
    """是否计入制品摘要（按制品根内相对路径判定易变/临时文件）。"""
    路径文本 = 相对路径.as_posix()
    if "__pycache__" in 路径文本:
        return False
    if 路径文本.endswith(".pyc") or 路径文本.endswith(".pyo"):
        return False
    if 路径文本.startswith(".构建中_") or 路径文本.startswith(".镜像中_"):
        return False
    if 路径文本.startswith(".制品下载_"):
        return False
    return True


def 远程镜像校验器(请求: 镜像校验请求, 清单: dict, 信任指纹: str,
                  实际制品摘要: str | None = None) -> 镜像校验结果:
    """校验器：制品摘要 + 依赖锁 + Python版本 + 系统版本 + 架构 全部一致才允许命中。

    - 清单缺失任一匹配字段 → 拒绝（镜像摘要不匹配）。
    - 信任指纹与配置不符 → 拒绝（镜像不可信）。
    - 依赖锁摘要/Python版本/系统版本/架构 任一与本地期望不符 → 拒绝。
    - 下载后实际制品摘要与清单声明不符（防篡改）→ 拒绝。
    拒绝均返回 错误码=镜像摘要不匹配；允许命中返回清单声明的制品摘要。
    """
    必填字段 = ["制品摘要", "依赖锁摘要", "python版本", "系统版本", "架构", "信任指纹"]
    缺失字段 = [字段 for 字段 in 必填字段
                if not str(清单.get(字段, "") or "").strip()]
    if 缺失字段:
        return 镜像校验结果(False, 错误码=镜像摘要不匹配,
                             错误说明=f"镜像清单不完整，缺失字段: {','.join(缺失字段)}")
    if str(清单["信任指纹"]) != str(信任指纹):
        return 镜像校验结果(False, 错误码=镜像摘要不匹配,
                             错误说明="信任指纹不匹配，镜像不可信")
    比对表 = [
        ("依赖锁", 请求.依赖锁摘要, str(清单["依赖锁摘要"])),
        ("Python版本", 请求.python版本, str(清单["python版本"])),
        ("系统版本", 请求.系统版本, str(清单["系统版本"])),
        ("架构", 请求.架构, str(清单["架构"])),
    ]
    for 名称, 期望值, 声明值 in 比对表:
        if str(期望值) != str(声明值):
            return 镜像校验结果(False, 错误码=镜像摘要不匹配,
                                 错误说明=f"{名称}不匹配（本地期望 {期望值}，镜像声明 {声明值}）")
    if 实际制品摘要 is not None and str(实际制品摘要) != str(清单["制品摘要"]):
        return 镜像校验结果(False, 错误码=镜像摘要不匹配,
                             错误说明=f"制品摘要不匹配（下载内容与镜像声明不符）")
    return 镜像校验结果(True, 制品摘要=str(清单["制品摘要"]))


def _拼接镜像地址(镜像地址: str, 提供者id: str, 环境摘要: str, 文件名: str) -> str:
    """拼接镜像制品地址：{镜像地址}/{提供者id}/{环境摘要}/{文件名}。"""
    段表 = [提供者id, 环境摘要, 文件名]
    编码段表 = [urllib.parse.quote(段, safe="") for 段 in 段表]
    return str(镜像地址).rstrip("/") + "/" + "/".join(编码段表)


def 获取镜像清单(镜像地址: str, 提供者id: str, 环境摘要: str,
                 *, 超时秒: int = 默认清单超时秒) -> 镜像操作结果:
    """拉取镜像清单（镜像不可用 → 错误码 镜像不可用）。"""
    清单地址 = _拼接镜像地址(镜像地址, 提供者id, 环境摘要, 清单文件名)
    try:
        with urllib.request.urlopen(清单地址, timeout=超时秒) as 响应:
            响应字节 = 响应.read(最大清单字节数 + 1)
            if len(响应字节) > 最大清单字节数:
                raise ValueError("镜像清单超过大小上限")
            清单 = json.loads(响应字节.decode("utf-8", errors="replace"))
        if not isinstance(清单, dict):
            raise ValueError("镜像清单必须是对象")
    except (OSError, ValueError, json.JSONDecodeError) as 错误:
        return 镜像操作结果(False, 错误码=镜像不可用,
                             错误说明=f"镜像清单获取失败: {错误}")
    return 镜像操作结果(True, 清单=清单)


def 下载镜像制品(镜像地址: str, 提供者id: str, 环境摘要: str, 目标目录: Path,
                 *, 超时秒: int = 默认下载超时秒,
                 最大字节数: int = 默认最大制品字节数) -> 镜像操作结果:
    """下载镜像制品并安全解压到 目标目录（失败 → 错误码 镜像下载失败）。

    - 下载写入临时 .tar.gz 后解压，控制大小上限，杜绝无界读入。
    - tar 成员路径安全校验（拒绝绝对路径与 .. 穿越）。
    - 制品解压后 目标目录 即环境目录内容根（bin/ 等直接在目标下）。
    """
    制品地址 = _拼接镜像地址(镜像地址, 提供者id, 环境摘要, 制品文件名)
    目标目录 = Path(目标目录)
    目标目录.mkdir(parents=True, exist_ok=True)
    临时制品文件 = 目标目录.parent / f".制品下载_{环境摘要[:8]}.tar.gz"
    try:
        with urllib.request.urlopen(制品地址, timeout=超时秒) as 响应:
            声明长度 = 响应.headers.get("Content-Length")
            if 声明长度:
                try:
                    if int(声明长度) > 最大字节数:
                        raise ValueError(f"制品超过大小上限 {最大字节数} 字节")
                except ValueError as 错误:
                    if str(错误).startswith("制品超过"):
                        raise
            with 临时制品文件.open("wb") as 写入:
                已读字节 = 0
                while True:
                    数据块 = 响应.read(1024 * 1024)
                    if not 数据块:
                        break
                    已读字节 += len(数据块)
                    if 已读字节 > 最大字节数:
                        raise ValueError(f"制品超过大小上限 {最大字节数} 字节")
                    写入.write(数据块)
        with tarfile.open(临时制品文件, "r:gz") as 压缩包:
            for 成员 in 压缩包.getmembers():
                成员路径 = Path(成员.name)
                if 成员.path.startswith("/") or ".." in 成员路径.parts:
                    raise ValueError(f"制品包含非法路径: {成员.name}")
            压缩包.extractall(目标目录)
    except (OSError, ValueError, tarfile.TarError) as 错误:
        return 镜像操作结果(False, 错误码=镜像下载失败,
                             错误说明=f"制品下载或解压失败: {错误}")
    finally:
        临时制品文件.unlink(missing_ok=True)
    return 镜像操作结果(True)
