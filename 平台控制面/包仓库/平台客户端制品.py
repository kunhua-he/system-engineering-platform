"""平台客户端制品接入正式包仓库体系：入库/签名/信任/安装/激活/稳定路径校验。

本模块是 客户端/构建平台客户端.py 与正式包仓库之间的唯一桥梁，禁止旁路：
- 入库：客户端构建产物（平台客户端-<摘要16> 目录）经 包仓库.构建制品 内容寻址
  登记到 制品根目录/<制品摘要>/（含 物料清单.json + 状态记录），再用 签名能力
  生成 Ed25519 签名，并用 可信仓库元数据 登记 根信任/目标/快照（磁盘信任元数据）。
- 安装：校验签名（重读磁盘逐一摘要，篡改拒绝）→ 临时目录完整写入 + fsync +
  os.replace 原子替换到 环境目录/平台客户端 → 经 发布管理（单调版本+栅栏令牌+
  CAS）切换激活指针 → 同步 环境目录/当前.json（保持外部调用方稳定路径契约）。
- 校验：重复安装同摘要幂等；半成品（缺文件/摘要缺失）拒绝；陈旧激活指针
  （指向不存在或摘要不符制品）拒绝并给出可诊断错误；外部调用方稳定路径可读。

全部复用 平台控制面/包仓库/ 既有内容寻址、签名与信任体系，不复制第二套仓库。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

from 平台控制面.平台状态 import 平台状态
from 平台控制面.包仓库.服务 import 包仓库
from 平台控制面.包仓库.可信仓库元数据 import 可信仓库元数据
from 平台控制面.发布管理.服务 import 发布管理
from 支持库.适配层 import 生成密钥对

默认包id = "平台客户端"
默认发布者 = "客户端构建发布者"
摘要前缀长度 = 16


def 计算目录摘要16(目录: Path) -> str:
    """内容寻址摘要（与 构建平台客户端.py 同一算法）：路径+字节 sha256 前 16 位。

    排除生成性元数据（制品摘要/制品来源/物料清单），保证构建产物、包仓库
    副本与已安装副本三处摘要一致。
    """
    哈希器 = hashlib.sha256()
    for 文件 in sorted(Path(目录).rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        if 文件.name in (
            "制品摘要.json", "制品来源.json", "制品完整性摘要.json",
            "编译清单.json", "物料清单.json",
        ):
            continue
        哈希器.update(str(文件.relative_to(目录)).encode("utf-8"))
        哈希器.update(文件.read_bytes())
    return 哈希器.hexdigest()[:摘要前缀长度]


# 二进制资产后缀（示例/验证数据 等真实二进制文件，hex 编码入库）
_二进制文件后缀表 = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                  ".woff", ".woff2", ".ttf", ".otf", ".ico", ".mp3", ".wav",
                  ".mp4", ".zip", ".xlsx", ".docx", ".pptx", ".db", ".sqlite", ".sqlite3"}
_二进制前缀 = "hexfile:"
# 构建期生成的元数据不参与制品身份（自指 + 两侧口径必须一致），见 读取制品文件表 说明。
_身份排除文件名表 = {"物料清单.json", "制品摘要.json", "制品来源.json", "编译清单.json"}


def 读取制品文件表(制品目录: Path) -> dict[str, str]:
    """把制品目录全部正式文件读为 相对路径→文本 文件表（供 包仓库.构建制品）。

    身份口径（与构建侧同名摘要**同一事实源**）：只算**内容文件**，构建期生成的元数据
    `物料清单.json`／`制品摘要.json`／`制品来源.json`／`编译清单.json` 不参与身份计算——
    它们在各自写入时互相引用（尤其 `制品摘要.json` 内含自身摘要），纳入会造成自指与两侧口径不一致，
    实测表现是"同内容重复入库被当成双摘要"（2026-09-15 踩坑）。
    """
    文件表: dict[str, str] = {}
    for 文件 in sorted(Path(制品目录).rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        if 文件.name in _身份排除文件名表:
            continue
        相对 = 文件.relative_to(制品目录).as_posix()
        if 文件.suffix.lower() in _二进制文件后缀表:
            try:
                文件表[相对] = _二进制前缀 + 文件.read_bytes().hex()
            except OSError as 错误:
                raise ValueError(f"制品文件不可读: {相对}（{错误}）") from 错误
            continue
        try:
            文件表[相对] = 文件.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                文件表[相对] = _二进制前缀 + 文件.read_bytes().hex()
            except OSError as 错误:
                raise ValueError(f"制品文件不可读: {相对}（{错误}）") from 错误
        except OSError as 错误:
            raise ValueError(f"制品文件不是可入库文本: {相对}（{错误}）") from 错误
    if not 文件表:
        raise ValueError(f"制品目录没有正式文件: {制品目录}")
    return 文件表


class 平台客户端制品接入:
    """平台客户端制品接入正式包仓库体系（入库/签名/信任/安装/激活/校验）。"""

    def __init__(
        self,
        *,
        状态目录: Path | str | None = None,
        制品根目录: Path | str | None = None,
        客户端制品目录: Path | str | None = None,
        环境目录: Path | str | None = None,
        信任目录: Path | str | None = None,
        包id: str = 默认包id,
        发布者: str = 默认发布者,
    ) -> None:
        self.包id = 包id
        self.发布者 = 发布者
        系统根 = Path(__file__).resolve().parents[2]
        缓存根 = 系统根 / "工程缓存" / "制品仓库"
        self.状态目录 = Path(状态目录) if 状态目录 is not None else 缓存根 / "平台客户端状态"
        self.制品根目录 = Path(制品根目录) if 制品根目录 is not None else 缓存根
        self.客户端制品目录 = Path(客户端制品目录) if 客户端制品目录 is not None \
            else 缓存根 / "平台客户端制品"
        self.环境目录 = Path(环境目录) if 环境目录 is not None else 缓存根 / "平台客户端环境"
        self.信任目录 = Path(信任目录) if 信任目录 is not None else 缓存根 / "平台客户端信任"
        self.状态 = 平台状态(self.状态目录, 项目id="平台控制面")
        self.仓库 = 包仓库(self.状态, 制品根目录=self.制品根目录)
        self.发布 = 发布管理(self.状态)
        self.可信元数据 = 可信仓库元数据(self.信任目录)

    def 关闭(self) -> None:
        """关闭接入对象持有的平台状态数据库连接；重复调用保持幂等。"""
        self.状态.关闭()

    # ---- 密钥（客户端构建专用；测试可注入现成密钥对） ----
    @staticmethod
    def _加固密钥权限(密钥目录: Path, 私钥文件: Path, 公钥文件: Path) -> None:
        """签名密钥受控：目录 700、私钥 600、公钥 644。"""
        try:
            密钥目录.chmod(0o700)
            私钥文件.chmod(0o600)
            公钥文件.chmod(0o644)
        except OSError:
            pass  # 平台不支持 chmod 时忽略（Windows 类）

    @staticmethod
    def 生成或读取密钥(密钥目录: Path | str | None = None) -> tuple[str, str]:
        """返回 (私钥PEM, 公钥PEM)：已有密钥复用，缺失则生成并落盘。

        签名密钥受控：密钥目录 700、私钥文件 600（仅属主可读写），
        公钥 644（可分发）；密钥只落盘 工程缓存（可重建，非源码树）。
        """
        密钥目录 = Path(密钥目录) if 密钥目录 is not None \
            else Path(__file__).resolve().parents[2] / "工程缓存" / "制品仓库" / "平台客户端密钥"
        私钥文件 = 密钥目录 / "发布者私钥.pem"
        公钥文件 = 密钥目录 / "发布者公钥.pem"
        if 私钥文件.is_file() and 公钥文件.is_file():
            平台客户端制品接入._加固密钥权限(密钥目录, 私钥文件, 公钥文件)
            return 私钥文件.read_text(encoding="utf-8"), 公钥文件.read_text(encoding="utf-8")
        私钥, 公钥 = 生成密钥对()
        密钥目录.mkdir(parents=True, exist_ok=True)
        私钥文件.write_text(私钥, encoding="utf-8")
        公钥文件.write_text(公钥, encoding="utf-8")
        平台客户端制品接入._加固密钥权限(密钥目录, 私钥文件, 公钥文件)
        return 私钥, 公钥

    # ---- 入库（内容寻址 + 签名 + 信任元数据） ----
    def 入库(self, *, 制品目录: Path | str, 构建输入: dict | None = None,
             私钥PEM: str, 公钥PEM: str) -> tuple[bool, str, str]:
        """把已构建的客户端制品登记到正式包仓库：内容寻址 + 签名 + 信任元数据。

        同内容重复入库幂等（同版同摘要复用）；返回 (成功, 消息, 制品摘要)。
        """
        制品目录 = Path(制品目录)
        if not 制品目录.is_dir():
            return False, f"制品目录不存在: {制品目录}", ""
        制品名 = 制品目录.name
        if not 制品名.startswith(f"{self.包id}-"):
            return False, f"制品目录命名不合法（应为 {self.包id}-<摘要16>）: {制品名}", ""
        摘要16 = 制品名.split("-")[-1]
        if not (len(摘要16) == 摘要前缀长度 and all(字符 in "0123456789abcdef" for 字符 in 摘要16)):
            return False, f"制品目录摘要段不合法: {制品名}", ""
        实际摘要16 = 计算目录摘要16(制品目录)
        if 实际摘要16 != 摘要16:
            return False, f"制品目录摘要不符（目录名 {摘要16}，实际 {实际摘要16}）", ""
        # 1. 内容寻址登记（复用 包仓库.构建制品：路径安全→临时目录→磁盘校验→
        #    物料清单.json→原子发布→状态记录；同包同版本同摘要幂等）
        文件表 = 读取制品文件表(制品目录)
        文件模式 = {
            文件.relative_to(制品目录).as_posix(): stat.S_IMODE(文件.stat().st_mode)
            for 文件 in 制品目录.rglob("*")
            if 文件.is_file() and 文件.name != "物料清单.json"
        }
        构建输入 = 构建输入 or {"来源": "客户端构建", "制品目录": 制品名}
        成功, 消息, 制品摘要 = self.仓库.构建制品(
            包id=self.包id, 版本=摘要16, 文件表=文件表, 构建输入=构建输入,
            文件模式=文件模式)
        if not 成功:
            return False, f"入库失败: {消息}", ""
        # 2. 签名（复用 签名能力；未签名才签，签名者不变不重签）
        记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 记录 and not 记录["签名"]:
            信任记录 = self.状态.读取记录("信任", "发布者", self.发布者)
            if 信任记录 is None:
                self.仓库.登记发布者(发布者=self.发布者, 公钥PEM=公钥PEM)
            elif 信任记录["公钥"] != 公钥PEM:
                return False, "发布者公钥与既有信任记录不一致", ""
            签名成功, 签名消息 = self.仓库.签名制品(
                制品摘要=制品摘要, 私钥PEM=私钥PEM, 发布者=self.发布者)
            if not 签名成功:
                return False, f"签名失败: {签名消息}", ""
        # 3. 磁盘信任元数据（根信任/目标/快照；根信任存在则跳过初始化）
        self._登记信任元数据(制品摘要, 摘要16)
        return True, f"已入库（内容寻址+签名+信任元数据）：{制品名}", 制品摘要

    def _登记信任元数据(self, 制品摘要: str, 版本: str) -> None:
        """可信仓库元数据：根信任（幂等）→ 目标 → 快照。

        目标登记的 制品内容 为 包仓库 制品摘要 的同源输入正文（与 内容摘要
        输入一致），使 可信仓库元数据.阻断检查 的"目标被替换"磁盘比对
        真实有效；包仓库 签名校验 另对磁盘制品逐一重算 sha256 双重防替换。
        """
        元数据目录 = self.信任目录 / "元数据"
        元数据目录.mkdir(parents=True, exist_ok=True)
        if not (元数据目录 / "根信任.json").is_file():
            self.可信元数据.初始化()
        # 重建与 包仓库.构建制品 完全同源的摘要输入正文（保证 内容摘要(正文)==制品摘要）
        记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 记录:
            文件清单 = json.loads(记录.get("文件清单") or "{}")
            构建输入 = json.loads(记录.get("构建输入") or "{}")
            正文 = json.dumps(
                {"包id": self.包id, "版本": 版本,
                 "文件清单": 文件清单, "构建输入": 构建输入},
                ensure_ascii=False, sort_keys=True,
            )
        else:
            正文 = json.dumps({"包id": self.包id, "版本": 版本}, ensure_ascii=False, sort_keys=True)
        # 幂等自检：正文摘要必须等于制品摘要，否则登记会污染信任元数据
        from 支持库.适配层 import 内容摘要 as _内容摘要
        if _内容摘要(正文.encode("utf-8")) != 制品摘要:
            return  # 正文不可复算（记录缺失/不匹配）：不登记目标，防恒真误报
        self.可信元数据.发布目标(
            包id=self.包id, 版本=版本, 制品摘要=制品摘要,
            制品内容=正文.encode("utf-8"))
        self.可信元数据.生成快照()

    def 校验制品(self, 制品摘要: str) -> tuple[bool, str]:
        """校验制品：Ed25519 签名 + 磁盘逐一摘要（篡改/半成品拒绝）。"""
        有效, 消息 = self.仓库.校验签名(制品摘要=制品摘要)
        if not 有效:
            return False, 消息
        记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 记录 is None:
            return False, "制品记录缺失（摘要缺失）"
        版本 = 记录["版本"]
        目标 = self.信任目录 / "元数据" / f"目标_{self.包id}_{版本}.json"
        if not 目标.is_file():
            return False, "信任元数据目标缺失"
        目标数据 = json.loads(目标.read_text(encoding="utf-8"))
        有效目标, 目标消息 = self.可信元数据.校验元数据("目标", 目标数据)
        if not 有效目标:
            return False, f"信任元数据校验失败: {目标消息}"
        return True, "制品签名有效且磁盘内容一致"

    # ---- 安装到环境（原子替换 + 发布管理激活） ----
    def 安装到环境(self, 制品摘要: str, 制品名: str | None = None) -> tuple[bool, str, Path | None]:
        """安装制品到 环境目录/平台客户端 并经发布管理 CAS 激活指针。

        幂等：已安装同摘要且指针一致 → 直接成功，不重复复制。
        """
        if not 制品摘要 or len(制品摘要) != 32 or not all(
                字符 in "0123456789abcdef" for 字符 in 制品摘要):
            return False, f"制品摘要不合法: {制品摘要!r}", None
        记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 记录 is None:
            return False, f"制品未入库（摘要缺失，拒绝半成品）: {制品摘要[:16]}…", None
        摘要16 = 记录["版本"]
        制品名 = 制品名 or f"{self.包id}-{摘要16}"
        # 陈旧指针拒绝：当前激活指针指向不存在或摘要不符的制品 → 可诊断错误
        陈旧原因 = self.检查激活指针()
        if 陈旧原因 is not None:
            return False, f"当前激活指针陈旧，拒绝安装: {陈旧原因}", None
        # 半成品拒绝：制品目录/物料清单缺失
        制品目录 = self.制品根目录 / 制品摘要
        if not 制品目录.is_dir():
            return False, f"制品目录缺失（半成品）: {制品目录.name}", None
        if not (制品目录 / "物料清单.json").is_file():
            return False, "制品缺少物料清单.json（半成品，拒绝安装）", None
        # 篡改拒绝：签名 + 磁盘逐一摘要
        有效, 消息 = self.校验制品(制品摘要)
        if not 有效:
            return False, f"安装被拒（制品被篡改或半成品）: {消息}", None
        # 幂等：已安装同摘要且指针一致
        if self._已安装且一致(制品摘要, 制品名, 摘要16):
            return True, "已安装（幂等复用，不重复复制）", self.环境目录 / "平台客户端"
        # 临时目录完整写入 + fsync + os.replace 原子替换（旧安装改名备份，先不删）
        目标 = self.环境目录 / "平台客户端"
        try:
            备份 = self._原子写入安装目录(制品目录, 目标, 制品名, 摘要16)
        except OSError as 错误:
            return False, f"安装写入失败: {错误}", None
        # 发布管理 CAS 激活（单调版本+栅栏令牌）
        激活成功, 激活消息 = self._发布激活(摘要16, 制品摘要)
        if not 激活成功:
            self._回滚安装目录(目标, 备份)
            return False, f"激活失败（已回滚安装目录）: {激活消息}", None
        self._清理安装备份(备份)
        # 同步 当前.json（外部调用方稳定路径契约；带版本/栅栏令牌供 CAS 诊断）
        self._写指针文件(制品摘要, 制品名, 摘要16)
        return True, "已安装并经发布管理激活", 目标

    def _已安装且一致(self, 制品摘要: str, 制品名: str, 摘要16: str) -> bool:
        """幂等判定：当前.json 指向本制品且 已安装目录 摘要一致。"""
        指针文件 = self.环境目录 / "当前.json"
        if not 指针文件.is_file():
            return False
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        目标 = self.环境目录 / "平台客户端"
        if 指针.get("摘要sha256") != 摘要16 or 指针.get("制品目录") != 制品名:
            return False
        if not 目标.is_dir():
            return False
        if 指针.get("制品摘要") != 制品摘要:
            return False
        return 计算目录摘要16(目标) == 摘要16

    def _原子写入安装目录(self, 制品目录: Path, 目标: Path, 制品名: str,
                            摘要16: str) -> Path:
        """临时目录完整写入 + 逐文件 fsync + 目录 fsync + os.replace 原子替换。

        返回旧安装的备份路径（从未安装时为不存在的路径）。备份**不在此删除**：
        由调用方在激活成功后清理、激活失败时还原；否则激活失败会同时失去新旧
        两份安装，指针却仍指旧制品（稳定路径损坏）。
        """
        self.环境目录.mkdir(parents=True, exist_ok=True)
        临时 = self.环境目录 / f".安装临时_{uuid.uuid4().hex[:8]}"
        临时.mkdir(parents=True)
        try:
            for 文件 in sorted(制品目录.rglob("*")):
                if 文件.is_dir() or "__pycache__" in 文件.parts:
                    continue
                if 文件.name == "物料清单.json":
                    continue
                相对 = 文件.relative_to(制品目录)
                目标文件 = 临时 / 相对
                目标文件.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(文件, 目标文件)
                with open(目标文件, "rb") as 句柄:
                    os.fsync(句柄.fileno())
            目录句柄 = os.open(临时, os.O_RDONLY)
            try:
                os.fsync(目录句柄)
            finally:
                os.close(目录句柄)
            # 原子替换：旧目录先改名备份 → 新目录就位 → 备份交回调用方处置
            备份 = self.环境目录 / f".平台客户端备份_{uuid.uuid4().hex[:8]}"
            if 目标.exists():
                os.rename(目标, 备份)
            try:
                os.rename(临时, 目标)
            except OSError:
                if 备份.exists() and not 目标.exists():
                    os.rename(备份, 目标)
                raise
            目录句柄 = os.open(self.环境目录, os.O_RDONLY)
            try:
                os.fsync(目录句柄)
            finally:
                os.close(目录句柄)
            return 备份
        except Exception:
            shutil.rmtree(临时, ignore_errors=True)
            raise

    def _清理安装备份(self, 备份: Path) -> None:
        """激活成功后丢弃旧安装备份（从未安装时是无操作）。"""
        if 备份.exists():
            shutil.rmtree(备份, ignore_errors=True)

    def _回滚安装目录(self, 目标: Path, 备份: Path) -> None:
        """激活失败时还原旧安装目录（指针未切，旧指针仍指旧制品）。

        有旧安装 → 删除新目录并把备份改名回稳定路径，稳定路径恢复可读；
        从未安装 → 只清理新目录（指针本就为空）。只删新目录不还原会让
        稳定路径彻底消失，与「已回滚」的报称不符。
        """
        shutil.rmtree(目标, ignore_errors=True)
        if 备份.exists() and not 目标.exists():
            os.rename(备份, 目标)

    def _发布激活(self, 版本: str, 制品摘要: str) -> tuple[bool, str]:
        """发布管理：登记期望版本（复用进行中发布）→ 灰度 → CAS 激活。"""
        发布表 = self.状态.查询记录("发布", "包id=? AND 状态 IN ('期望','灰度')", (self.包id,))
        发布id = 发布表[0]["发布id"] if 发布表 else self.发布.登记期望版本(
            包id=self.包id, 期望版本=版本)
        self.发布.开始灰度(发布id=发布id, 候选版本=版本, 比例=0.1)
        return self.发布.激活(发布id=发布id, 目标=制品摘要)

    def _写指针文件(self, 制品摘要: str, 制品名: str, 摘要16: str) -> None:
        """原子写 环境目录/当前.json（保持外部调用方稳定路径契约并携带 版本/栅栏令牌）。"""
        指针 = self.发布.当前激活(self.包id)
        数据 = {
            "摘要sha256": 摘要16,
            "制品目录": 制品名,
            "制品摘要": 制品摘要,
            "版本": int(指针["版本"]) if 指针 else 1,
            "栅栏令牌": int(指针["栅栏令牌"]) if 指针 else 1,
        }
        指针文件 = self.环境目录 / "当前.json"
        临时指针 = self.环境目录 / ".当前.json.tmp"
        临时指针.write_text(json.dumps(数据, ensure_ascii=False), encoding="utf-8")
        with open(临时指针, "rb") as 句柄:
            os.fsync(句柄.fileno())
        os.replace(临时指针, 指针文件)
        目录句柄 = os.open(self.环境目录, os.O_RDONLY)
        try:
            os.fsync(目录句柄)
        finally:
            os.close(目录句柄)

    # ---- 校验（陈旧指针拒绝 / 外部调用方稳定路径） ----
    def 检查激活指针(self) -> str | None:
        """陈旧指针检查：激活指针指向不存在或摘要不符制品 → 返回可诊断原因。"""
        指针文件 = self.环境目录 / "当前.json"
        if not 指针文件.is_file():
            return None  # 从未安装，无指针可查
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as 错误:
            return f"激活指针文件不可读: {错误}"
        摘要16 = 指针.get("摘要sha256", "")
        制品名 = 指针.get("制品目录", "")
        指向目录 = self.客户端制品目录 / 制品名 if 制品名 else None
        if 指向目录 is None or not 指向目录.is_dir():
            return f"激活指针指向的制品目录不存在: {制品名 or '<空>'}"
        if len(摘要16) != 摘要前缀长度 or 计算目录摘要16(指向目录) != 摘要16:
            return f"激活指针指向的制品摘要不符: {制品名}（期望 {摘要16}）"
        制品摘要 = 指针.get("制品摘要", "")
        if 制品摘要:
            记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
            if 记录 is None:
                return f"激活指针指向的制品未入库: {制品摘要[:16]}…"
        return None

    def 校验稳定路径(self) -> tuple[bool, str, Path | None]:
        """外部调用方稳定路径校验：环境目录/平台客户端 + 当前.json 完整且一致。

        模拟外部调用方引导读取：指针可读 → 已安装目录存在 → 摘要一致 →
        指针指向的制品目录存在且摘要一致 → 可安全读取。
        """
        指针文件 = self.环境目录 / "当前.json"
        if not 指针文件.is_file():
            return False, "缺少激活指针 当前.json（从未安装或指针丢失）", None
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as 错误:
            return False, f"激活指针不可读: {错误}", None
        摘要16 = 指针.get("摘要sha256", "")
        目标 = self.环境目录 / "平台客户端"
        if not 目标.is_dir():
            return False, "已安装目录缺失（半安装态，拒绝读取）", None
        if len(摘要16) != 摘要前缀长度:
            return False, f"激活指针摘要字段不合法: {摘要16!r}", None
        实际摘要16 = 计算目录摘要16(目标)
        if 实际摘要16 != 摘要16:
            return False, (f"已安装目录摘要不符（指针 {摘要16}，实际 {实际摘要16}），"
                           f"拒绝读取"), None
        制品名 = 指针.get("制品目录", "")
        指向目录 = self.客户端制品目录 / 制品名 if 制品名 else None
        if 指向目录 is None or not 指向目录.is_dir():
            return False, f"陈旧激活指针：指向的制品目录不存在 {制品名 or '<空>'}", None
        if 计算目录摘要16(指向目录) != 摘要16:
            return False, f"陈旧激活指针：指向的制品摘要不符 {制品名}", None
        return True, f"稳定路径可读：{目标}", 目标


__all__ = ["平台客户端制品接入", "计算目录摘要16", "读取制品文件表"]
