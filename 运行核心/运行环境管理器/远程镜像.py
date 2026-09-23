"""远程镜像契约与校验器：环境缓存的可选加速来源（默认关闭）。

原则：
- 远程镜像只作为"已构建环境制品"的来源：本机无 pip 网络时，从镜像
  拉取与本地期望完全一致的环境制品，经全部条件匹配才允许命中。
- 信任依据（双保险）：镜像清单必须经发布者 Ed25519 私钥签名（验证方用
  配置的发布者公钥验证，失败 → 镜像签名无效），且清单信任指纹与本地
  配置一致（失败 → 镜像摘要不匹配）。信任指纹不再作为唯一信任依据。
- 匹配条件：制品摘要 + 依赖锁 + Python 版本 + 系统版本 + 架构 全部一致；
  任一不匹配 → 拒绝（镜像摘要不匹配），不得静默使用不可信环境。
- 签名密钥角色边界：签名私钥只由发布角色持有并使用（发布工具/测试内
  生成临时密钥对）；运行核心与普通开发角色不生成密钥、不自签名，只
  读取配置提供的发布者公钥做验证，也不得修改信任目录。
- 错误码四态：镜像不可用（镜像服务不可访问）、镜像签名无效（签名
  验证失败/公钥缺失/签名缺失）、镜像摘要不匹配（任一匹配条件不符）、
  镜像下载失败（下载/解压/复校验失败）。
- 代理：远程镜像配置 可选 代理地址 字段；配置了则清单/制品请求走代理，
  未配置则显式直连（禁用环境代理变量），地址一律来自配置、不硬编码。
- 下载防篡改全程：下载（大小上限）→ 解包（拒绝 绝对路径/../符号链接
  逃逸，解包后复核落盘边界）→ 复校验（制品摘要/文件清单 sha256）→
  原子落盘（fsync + 旧环境改名让位 + os.replace 顶位 + 清理让位）。
  任一失败 → 镜像下载失败，不落半成品；顶位失败一律回滚，任一时刻磁盘上
  至少有一个可用环境（上一代环境不会与新环境同时消失）。
- 默认关闭：启用=false 时本模块不参与 确保环境 流程，本地缓存行为零变化。
- 制品摘要 = 环境目录稳定摘要（sha256 文件路径+内容，排除易变文件），
  用于下载后防篡改比对：下载内容与镜像声明不符 → 拒绝。
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import tarfile
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.诊断.忽略记录 import 记录忽略
from 支持库.适配层.密码签名提供者 import 签名, 验证签名
from 公共契约.基础类型.逻辑类型 import 真, 假

镜像不可用 = "镜像不可用"
镜像签名无效 = "镜像签名无效"
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
    """远程镜像配置契约：镜像地址 + 启用开关 + 信任指纹 + 发布者公钥（默认关闭）。

    公钥PEM：发布者公钥（验证镜像清单签名的信任根），只读信任输入；
    签名私钥只由发布角色持有，运行核心不得持有或生成私钥。
    代理地址：可选 http(s) 代理（下载/清单请求走代理），留空则直连。
    """

    启用: bool = 假
    镜像地址: str = ""
    信任指纹: str = ""
    公钥PEM: str = ""
    代理地址: str = ""


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

    配置结构：{"启用": true, "镜像地址": "...", "信任指纹": "...",
    "公钥PEM": "发布者公钥文本", "代理地址": "http(s)://..."}。
    代理地址 可选：配置了则清单/制品请求走代理，未配置则直连（不硬编码）。
    未启用时 确保环境 完全走现有本地缓存路径（行为零变化）。
    """
    if 配置文件 is None or not Path(配置文件).is_file():
        return 远程镜像配置()
    try:
        数据 = json.loads(Path(配置文件).read_text(encoding="utf-8"))
        if not isinstance(数据, dict):
            return 远程镜像配置()
        启用 = bool(数据.get("启用", 假))
        镜像地址 = str(数据.get("镜像地址", "") or "")
        信任指纹 = str(数据.get("信任指纹", "") or "")
        公钥PEM = str(数据.get("公钥PEM", "") or "")
        代理地址 = str(数据.get("代理地址", "") or "")
    except (OSError, ValueError):
        return 远程镜像配置()
    return 远程镜像配置(启用=启用, 镜像地址=镜像地址,
                        信任指纹=信任指纹, 公钥PEM=公钥PEM,
                        代理地址=代理地址)


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
        return 假
    if 路径文本.endswith(".pyc") or 路径文本.endswith(".pyo"):
        return 假
    if 路径文本.startswith(".构建中_") or 路径文本.startswith(".镜像中_"):
        return 假
    if 路径文本.startswith(".制品下载_"):
        return 假
    return 真


def _清单稳定序列化(清单: dict) -> bytes:
    """清单稳定序列化（签名正文）：去 签名 键 + 确定序 + UTF-8 紧凑字节。

    任何字段顺序/空白差异都不影响序列化结果，保证签名跨端一致。
    """
    待签名 = {键: 值 for 键, 值 in 清单.items() if 键 != "签名"}
    return json.dumps(待签名, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def 签名清单(清单: dict, 私钥PEM: str) -> 结果:
    """镜像清单签名（Ed25519，经 支持库.适配层 签名 公开入口）。

    签名正文 = 清单稳定序列化（不含 签名 字段自身），避免自引用；
    成功返回带 签名 字段（hex）的新清单；失败错误码 镜像签名无效。
    私钥只由发布角色持有；本函数不在运行核心流程内调用。
    """
    if not isinstance(清单, dict) or not 清单:
        return 结果.失败(镜像签名无效, "镜像清单必须是非空对象")
    if not isinstance(私钥PEM, str) or not 私钥PEM.strip():
        return 结果.失败(镜像签名无效, "私钥PEM 必须是非空文本")
    try:
        数据b64 = base64.b64encode(_清单稳定序列化(清单)).decode("ascii")
    except (TypeError, ValueError) as 错误:
        return 结果.失败(镜像签名无效, f"清单序列化失败: {错误}")
    签名结果 = 签名(私钥PEM, 数据b64)
    if not 签名结果.成功:
        return 结果.失败(镜像签名无效,
                          f"清单签名失败: {签名结果.错误码}: {签名结果.错误说明}")
    新清单 = dict(清单)
    新清单["签名"] = 签名结果.值
    return 结果.成功结果(新清单)


def 验证清单签名(清单: dict, 公钥PEM: str) -> 结果:
    """镜像清单公钥验证（Ed25519，经 支持库.适配层 验证签名 公开入口）。

    签名缺失/公钥缺失/签名与正文不符/公钥不匹配 → 错误码 镜像签名无效。
    成功值=True：清单确由与 公钥PEM 配对的私钥签名（未被篡改）。
    """
    if not isinstance(清单, dict) or not 清单:
        return 结果.失败(镜像签名无效, "镜像清单必须是非空对象")
    签名值 = 清单.get("签名")
    if not isinstance(签名值, str) or not 签名值.strip():
        return 结果.失败(镜像签名无效, "镜像清单缺少签名字段")
    if not isinstance(公钥PEM, str) or not 公钥PEM.strip():
        return 结果.失败(镜像签名无效, "公钥PEM 必须是非空文本")
    try:
        数据b64 = base64.b64encode(_清单稳定序列化(清单)).decode("ascii")
    except (TypeError, ValueError) as 错误:
        return 结果.失败(镜像签名无效, f"清单序列化失败: {错误}")
    验证结果 = 验证签名(公钥PEM, 数据b64, 签名值)
    if not 验证结果.成功:
        return 结果.失败(镜像签名无效,
                          f"镜像签名验证失败: {验证结果.错误码}: {验证结果.错误说明}")
    if not 验证结果.值:
        return 结果.失败(镜像签名无效, "镜像签名验证不通过，镜像不可信")
    return 结果.成功结果(真)


def 远程镜像校验器(请求: 镜像校验请求, 清单: dict, 信任指纹: str,
                  公钥PEM: str = "",
                  实际制品摘要: str | None = None) -> 镜像校验结果:
    """校验器：公钥签名验证 + 信任指纹双保险 + 五条件匹配。

    - 清单缺失任一匹配字段 → 拒绝（镜像摘要不匹配）。
    - 清单必须经发布者公钥验证（公钥PEM 缺失或验证失败 → 镜像签名无效，
      信任指纹不再是唯一信任依据）。
    - 信任指纹与配置不符 → 拒绝（镜像摘要不匹配，双保险仍生效）。
    - 依赖锁摘要/Python版本/系统版本/架构 任一与本地期望不符 → 拒绝。
    - 下载后实际制品摘要与清单声明不符（防篡改）→ 拒绝。
    拒绝均不允许命中；允许命中返回清单声明的制品摘要。
    """
    必填字段 = ["制品摘要", "依赖锁摘要", "python版本", "系统版本", "架构", "信任指纹"]
    缺失字段 = [字段 for 字段 in 必填字段
                if not str(清单.get(字段, "") or "").strip()]
    if 缺失字段:
        return 镜像校验结果(假, 错误码=镜像摘要不匹配,
                             错误说明=f"镜像清单不完整，缺失字段: {','.join(缺失字段)}")
    签名验证 = 验证清单签名(清单, 公钥PEM)
    if not 签名验证.成功:
        return 镜像校验结果(假, 错误码=镜像签名无效,
                             错误说明=签名验证.错误说明)
    if str(清单["信任指纹"]) != str(信任指纹):
        return 镜像校验结果(假, 错误码=镜像摘要不匹配,
                             错误说明="信任指纹不匹配，镜像不可信")
    比对表 = [
        ("依赖锁", 请求.依赖锁摘要, str(清单["依赖锁摘要"])),
        ("Python版本", 请求.python版本, str(清单["python版本"])),
        ("系统版本", 请求.系统版本, str(清单["系统版本"])),
        ("架构", 请求.架构, str(清单["架构"])),
    ]
    for 名称, 期望值, 声明值 in 比对表:
        if str(期望值) != str(声明值):
            return 镜像校验结果(假, 错误码=镜像摘要不匹配,
                                 错误说明=f"{名称}不匹配（本地期望 {期望值}，镜像声明 {声明值}）")
    if 实际制品摘要 is not None and str(实际制品摘要) != str(清单["制品摘要"]):
        return 镜像校验结果(假, 错误码=镜像摘要不匹配,
                             错误说明=f"制品摘要不匹配（下载内容与镜像声明不符）")
    return 镜像校验结果(真, 制品摘要=str(清单["制品摘要"]))


def _拼接镜像地址(镜像地址: str, 提供者id: str, 环境摘要: str, 文件名: str) -> str:
    """拼接镜像制品地址：{镜像地址}/{提供者id}/{环境摘要}/{文件名}。"""
    段表 = [提供者id, 环境摘要, 文件名]
    编码段表 = [urllib.parse.quote(段, safe="") for 段 in 段表]
    return str(镜像地址).rstrip("/") + "/" + "/".join(编码段表)


def _请求地址(地址: str, 超时秒: int, 代理地址: str = ""):
    """按代理配置发起请求；返回响应对象（可用 with 上下文关闭）。

    - 配置了代理地址 → http/https 请求走该代理（地址一律来自配置）。
    - 未配置代理 → 显式直连（禁用环境代理变量，不硬编码任何地址）。
    - file:// 等本地地址不受代理影响，直连处理。
    - 代理请求自实现：系统代理绕过规则（如 macOS 对 127.0.0.1 绕过）
      不得静默绕过显式配置的代理。
    """
    地址解析 = urllib.parse.urlsplit(地址)
    代理 = str(代理地址 or "").strip()
    if not 代理 or 地址解析.scheme in ("file",):
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({})).open(地址, timeout=超时秒)
    代理解析 = urllib.parse.urlsplit(
        代理 if "://" in 代理 else "http://" + 代理)
    if 代理解析.scheme != "http":
        raise ValueError(f"仅支持 http 代理地址: {代理}")
    连接 = http.client.HTTPConnection(代理解析.netloc, timeout=超时秒)
    try:
        连接.request("GET", 地址, headers={"Host": 地址解析.netloc})
        响应 = 连接.getresponse()
        return _代理响应包装(响应, 连接)
    except BaseException:
        连接.close()
        raise


class _代理响应包装:
    """代理响应包装：with 退出/close 时关闭自持连接（HTTPResponse 不关连接）。"""

    def __init__(self, 响应, 连接):
        self._响应 = 响应
        self._连接 = 连接

    def __enter__(self):
        return self

    def __exit__(self, *异常):
        self._连接.close()
        return 假

    def __getattr__(self, 名称):
        return getattr(self._响应, 名称)

    def read(self, *参数):
        return self._响应.read(*参数)

    def close(self):
        self._连接.close()

    @property
    def headers(self):
        return self._响应.headers

    @property
    def status(self):
        return self._响应.status


def 获取镜像清单(镜像地址: str, 提供者id: str, 环境摘要: str,
                 *, 超时秒: int = 默认清单超时秒,
                 代理地址: str = "") -> 镜像操作结果:
    """拉取镜像清单（镜像不可用 → 错误码 镜像不可用）。

    代理地址 可选：配置了则经代理请求，未配置则显式直连。
    """
    清单地址 = _拼接镜像地址(镜像地址, 提供者id, 环境摘要, 清单文件名)
    try:
        with _请求地址(清单地址, 超时秒, 代理地址) as 响应:
            响应字节 = 响应.read(最大清单字节数 + 1)
            if len(响应字节) > 最大清单字节数:
                raise ValueError("镜像清单超过大小上限")
            清单 = json.loads(响应字节.decode("utf-8", errors="replace"))
        if not isinstance(清单, dict):
            raise ValueError("镜像清单必须是对象")
    except (OSError, ValueError, json.JSONDecodeError) as 错误:
        return 镜像操作结果(假, 错误码=镜像不可用,
                             错误说明=f"镜像清单获取失败: {错误}")
    return 镜像操作结果(真, 清单=清单)


def 计算文件清单摘要(制品目录: Path) -> str:
    """文件清单 sha256：逐文件 {相对路径: sha256} 稳定清单的哈希。

    排除易变文件（与 计算制品摘要 一致），用于解包后复校验：
    镜像清单声明 文件清单摘要 时，解包内容必须一致（防半成品/缺失文件）。
    """
    制品根 = Path(制品目录).resolve()
    文件清单: dict[str, str] = {}
    for 文件 in 制品根.rglob("*"):
        if 文件.is_file():
            相对路径 = 文件.relative_to(制品根)
            if _计入制品摘要(相对路径):
                文件清单[相对路径.as_posix()] = hashlib.sha256(
                    文件.read_bytes()).hexdigest()
    规范文本 = json.dumps(文件清单, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(规范文本.encode("utf-8")).hexdigest()[:16]


def _校验解包成员(成员: tarfile.TarInfo, 目标目录: Path) -> None:
    """tar 成员安全校验：拒绝 绝对路径/.. 穿越/符号链接逃逸。"""
    成员路径 = Path(成员.name)
    if 成员.path.startswith("/") or ".." in 成员路径.parts:
        raise ValueError(f"制品包含非法路径: {成员.name}")
    if 成员.issym() or 成员.islnk():
        链接目标 = Path(成员.linkname)
        if 成员.linkname.startswith("/") or ".." in 链接目标.parts:
            raise ValueError(f"制品包含逃逸链接: {成员.name} -> {成员.linkname}")
        解析目标 = (目标目录.resolve() / 链接目标).resolve()
        if not 解析目标.is_relative_to(目标目录.resolve()):
            raise ValueError(f"制品链接目标逃逸解包根: {成员.name} -> {成员.linkname}")


def _复核落盘边界(目标目录: Path) -> None:
    """解包后落盘复核：每个条目解析后必须仍在解包根内（拒绝链接逃逸）。"""
    解包根 = Path(目标目录).resolve()
    for 条目 in 解包根.rglob("*"):
        if not 条目.resolve().is_relative_to(解包根):
            raise ValueError(f"制品落盘路径逃逸解包根: {条目}")


def _复校验文件清单(镜像清单: dict, 目标目录: Path) -> None:
    """镜像清单声明 文件清单摘要 时，解包内容必须一致（防半成品）。"""
    声明摘要 = str(镜像清单.get("文件清单摘要", "") or "")
    if not 声明摘要:
        return
    实际摘要 = 计算文件清单摘要(目标目录)
    if 实际摘要 != 声明摘要:
        raise ValueError(
            f"制品文件清单摘要复校验失败（半成品/缺失文件）: "
            f"声明 {声明摘要} 实际 {实际摘要}")


def 下载镜像制品(镜像地址: str, 提供者id: str, 环境摘要: str, 目标目录: Path,
                 *, 超时秒: int = 默认下载超时秒,
                 最大字节数: int = 默认最大制品字节数,
                 代理地址: str = "",
                 镜像清单: dict[str, Any] | None = None) -> 镜像操作结果:
    """下载镜像制品并安全解包到 目标目录（失败 → 错误码 镜像下载失败）。

    - 代理地址 可选：配置了则经代理下载，未配置则显式直连（不硬编码）。
    - 下载写入临时 .tar.gz 后解压，控制大小上限，杜绝无界读入。
    - tar 成员安全校验：拒绝 绝对路径/.. 穿越/符号链接逃逸，解包后复核。
    - 镜像清单 提供时做文件清单复校验（声明 文件清单摘要 → 必须一致）。
    - 失败不落半成品：临时 .tar.gz 与解包产物一律清理。
    - 制品解压后 目标目录 即环境目录内容根（bin/ 等直接在目标下）。
    """
    制品地址 = _拼接镜像地址(镜像地址, 提供者id, 环境摘要, 制品文件名)
    目标目录 = Path(目标目录)
    目标目录.mkdir(parents=True, exist_ok=True)
    临时制品文件 = 目标目录.parent / f".制品下载_{环境摘要[:8]}.tar.gz"
    临时制品文件.unlink(missing_ok=True)
    try:
        with _请求地址(制品地址, 超时秒, 代理地址) as 响应:
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
                _校验解包成员(成员, 目标目录)
            压缩包.extractall(目标目录, filter="data")
        _复核落盘边界(目标目录)
        if 镜像清单 is not None:
            _复校验文件清单(镜像清单, 目标目录)
    except (OSError, ValueError, tarfile.TarError) as 错误:
        清只读后删除树(目标目录, 忽略失败=真)
        return 镜像操作结果(假, 错误码=镜像下载失败,
                             错误说明=f"制品下载或解压失败: {错误}")
    finally:
        临时制品文件.unlink(missing_ok=True)
    return 镜像操作结果(真)


def 清除只读属性(路径: str | Path) -> None:
    """清掉路径（文件或目录）的只读属性；失败**原样报错**，不降级。

    **薄委托**（2026-09-19 H 路收口）：唯一实现已迁到 `公共契约/运行时/平台适配/`
    （跨平台收口层），本函数只**转发**，不再自带第二份实现。迁移理由：`支持库`
    按依赖防火墙只准依赖 `公共契约` 与它自身，若实现留在 `运行核心`，支持库侧
    调用点在源码态就导入不了（唯一实现必须落在所有层都够得着的地方）。
    """
    from 公共契约.运行时.平台适配 import 清除只读属性 as _唯一实现

    _唯一实现(路径)


def 确保可删(路径: str | Path) -> None:
    """让「删除 路径」这件事可做：清掉路径自身的只读位，并确保**父目录可写**。

    语义、平台判据（能力探测而非平台名）与失败口径**全部以唯一实现为准**，
    见 `公共契约/运行时/平台适配/确保可删` 的 docstring。
    """
    from 公共契约.运行时.平台适配 import 确保可删 as _唯一实现

    _唯一实现(路径)


def 清只读后删除树(目录: Path, *, 忽略失败: bool = 假) -> None:
    """删除目录树；遇只读属性造成的 `PermissionError` 时先清只读再重试删除。

    语义、`onexc` 钩子行为、`忽略失败=真` 的留痕口径**全部以唯一实现为准**，
    见 `公共契约/运行时/平台适配/删除树.py::清只读后删除树` 的 docstring。
    """
    from 公共契约.运行时.平台适配 import 清只读后删除树 as _唯一实现

    _唯一实现(目录, 忽略失败=忽略失败)


def _同步目录项(目录: Path) -> None:
    """fsync 单个目录项；本平台拿不到目录句柄/不支持目录 fsync 时**如实留痕**。

    Windows 上 `os.open(目录, os.O_RDONLY)` **必然**抛
    `PermissionError: [Errno 13] Permission denied: '<目录>'`——CPython 的 `os.open()`
    对目录走 `CreateFileW` 且不带 `FILE_FLAG_BACKUP_SEMANTICS`，这**不是权限不足**，
    是「Windows 不允许把目录当文件打开」；POSIX 上同一调用合法（本机实测成功）。
    """
    try:
        目录句柄 = os.open(目录, os.O_RDONLY)
    except OSError as 错误:
        记录忽略("远程镜像.同步落盘.目录", 错误)
        return
    try:
        os.fsync(目录句柄)
    except OSError as 错误:
        记录忽略("远程镜像.同步落盘.目录", 错误)
    finally:
        try:
            os.close(目录句柄)
        except OSError as 错误:
            记录忽略("远程镜像.同步落盘.目录关闭", 错误)


def _同步文件项(文件: Path) -> None:
    """fsync 单个文件；拿不到可 fsync 的句柄时**如实留痕**，不升级为落盘失败。

    Windows 的 `FlushFileBuffers` 要求句柄带写权限，`open("rb")` 的只读句柄会失败；
    而 venv 里 pip 的 license 文件本就是只读的 → 拿不到写句柄。POSIX 上 `rb` 句柄
    可直接 fsync（本机实测成功）。
    """
    try:
        文件句柄 = 文件.open("rb")
    except OSError as 错误:
        记录忽略("远程镜像.同步落盘.文件", 错误)
        return
    try:
        os.fsync(文件句柄.fileno())
    except OSError as 错误:
        记录忽略("远程镜像.同步落盘.文件", 错误)
    finally:
        文件句柄.close()


def 同步落盘(制品目录: Path) -> None:
    """fsync 制品目录下全部文件与目录（自底向上），保证改名前数据落盘。

    **跨平台口径（2026-09-19 修 Windows 专有「提交环境缓存失败: [Errno 13]
    Permission denied」）**：目录 fsync 与只读句柄 fsync 在 Windows 上**做不到**
    （机制见 `_同步目录项`、`_同步文件项`）。这**不是降级**：数据本身已在上一阶段
    写出（pip/venv 写文件时已落盘，`原子落盘` 之后也不再改写），本函数是「改名前
    可见性」的加固，不是「数据是否写出」的判据 —— 拿不到句柄的项经 `记录忽略`
    **如实留痕（可查询）**，不上报成落盘失败把整轮装配带偏。

    这与 `运行核心/任务调度/任务进程.py::_同步目录` 的既有口径一致（原文：
    「非 POSIX 平台可能拒绝目录 fsync —— 此时快照文件**已经写出**（数据没丢），
    不能把『目录 fsync 不可用』升级成『落盘失败』…因此如实记进任务日志，不静默」）。
    """
    制品根 = Path(制品目录).resolve()
    if not 制品根.is_dir():
        raise OSError(f"制品目录不存在: {制品根}")
    目录表 = [目录 for 目录 in 制品根.rglob("*") if 目录.is_dir()]
    目录表.append(制品根)
    for 目录 in sorted(目录表, key=lambda 项: len(项.parts), reverse=True):
        _同步目录项(目录)
    for 文件 in 制品根.rglob("*"):
        if 文件.is_file():
            _同步文件项(文件)


def 原子落盘(临时目录: Path, 目标目录: Path) -> None:
    """临时目录 fsync 落盘 → 旧环境改名让位 → 新环境顶位 → 清理让位目录。

    口径：**任一时刻磁盘上至少有一个可用环境**。

    - 旧环境不删除，只改名到同级「让位目录」（``.<目标名>.让位_<进程号>_<随机>``）；
      新环境 ``os.replace`` 顶位失败时把让位目录改回原名（回滚），旧环境原样可用。
    - 回滚本身失败（父目录不可写等）时**不删除让位目录**：旧环境数据仍在磁盘上，
      并在抛出的错误说明里点明实际位置，同时经 ``记录忽略`` 留痕（第 3 条）。
    - 只在「新环境已顶位成功」之后才清理让位目录；清理失败不影响新环境可用，只留痕。
    - 半成品（未 fsync/未顶位成功）不会以 目标目录 名义出现；失败时清理临时目录。
    """
    临时目录 = Path(临时目录)
    目标目录 = Path(目标目录)
    try:
        同步落盘(临时目录)
    except OSError:
        清只读后删除树(临时目录, 忽略失败=真)
        raise
    目标目录.parent.mkdir(parents=True, exist_ok=True)
    让位目录: Path | None = None
    if 目标目录.exists():
        让位目录 = 目标目录.parent / (
            f".{目标目录.name}.让位_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            os.replace(目标目录, 让位目录)  # 旧环境改名让位：不删除，可回滚
        except OSError as 错误:
            清只读后删除树(临时目录, 忽略失败=真)
            raise OSError(
                f"旧环境让位失败（旧环境原样保留在 {目标目录}）: {错误}") from 错误
    try:
        os.replace(临时目录, 目标目录)
    except OSError as 错误:
        清只读后删除树(临时目录, 忽略失败=真)
        回滚说明 = _回滚让位(让位目录, 目标目录) if 让位目录 is not None else "无旧环境需要回滚"
        raise OSError(f"新环境顶位失败: {错误}；{回滚说明}") from 错误
    if 让位目录 is not None:
        _清理让位(让位目录)


def _回滚让位(让位目录: Path, 目标目录: Path) -> str:
    """把让位目录改回 目标目录；失败则保留让位目录并把位置写进说明与忽略记录。"""
    try:
        目标目录.parent.mkdir(parents=True, exist_ok=True)
        os.replace(让位目录, 目标目录)
    except OSError as 错误:
        记录忽略("远程镜像.原子落盘.回滚让位", 错误)
        return (f"回滚失败（旧环境仍在 {让位目录}，请人工改回 {目标目录}）: {错误}")
    return "已回滚，旧环境已复位到目标路径"


def _清理让位(让位目录: Path) -> None:
    """新环境顶位成功后清理让位目录；失败只留痕，不影响新环境可用。"""
    try:
        清只读后删除树(让位目录)
    except OSError as 错误:
        记录忽略("远程镜像.原子落盘.清理让位", 错误)
