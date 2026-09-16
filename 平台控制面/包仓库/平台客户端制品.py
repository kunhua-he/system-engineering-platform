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
import time
import uuid
from pathlib import Path
from typing import Any

from 平台控制面.平台状态 import 平台状态
from 平台控制面.包仓库.服务 import 包仓库
# 生成性元数据的两张排除表：唯一事实源在 签名能力（本模块与签名侧共用同一对象，
# 不得各维护一份——2026-09-17 缺陷一：两套表不一致使 校验签名 对任何制品恒 False）。
from 平台控制面.包仓库.签名能力 import 身份排除文件名表, 清单排除文件名表
from 平台控制面.包仓库.可信仓库元数据 import 可信仓库元数据
from 平台控制面.发布管理.服务 import 发布管理
from 支持库.适配层 import 生成密钥对

默认包id = "平台客户端"
默认发布者 = "客户端构建发布者"
摘要前缀长度 = 16

# 制品目录内的**运行时数据段名**（D-17 ② 口径的唯一事实源）。
# 制品进程若把运行时缓存根算进制品目录，会写出 `<制品>/工程缓存/…`（实测形态一）
# 或 `<制品>/平台客户端/工程缓存/…`（实测形态二，2026-09-16 现场两种都在）：
# 两处路径里都有 `工程缓存` 段，一个判据同时覆盖。运行时数据**不是构建产物**，
# 一律不参与制品身份、不进包仓库 —— 这是「源制品目录被写脏就永久判陈旧」的根因收口。
运行时数据段名 = "工程缓存"


def _是运行时数据(相对: Path) -> bool:
    """制品目录内**运行时数据**判定（摘要与入库同调这一个判定点，不复制规则）。

    判据只有一条：相对路径含 `工程缓存` 段。
    **不按 `.db`/`.log` 后缀排除**——`夹具/`、`验证夹具/` 下的 `.db` 是构建期
    合法复制的验证数据（干净制品里本来就有），按后缀排除会把它们从制品身份里
    剔除，等于改变「已安装制品 ↔ 目录名摘要」的对应关系。
    """
    return 运行时数据段名 in 相对.parts


def 计算目录摘要16(目录: Path) -> str:
    """内容寻址摘要（与 构建平台客户端.py 同一算法）：路径+字节 sha256 前 16 位。

    排除**制品身份口径**的生成性元数据（= `身份排除文件名表`，从 签名能力 导入：
    制品摘要/制品来源/制品完整性摘要/编译清单/物料清单）与**运行时数据**
    （`工程缓存` 段，见 `_是运行时数据`），保证构建产物、包仓库副本与已安装副本
    三处摘要一致——制品进程把运行数据库写回目录内部时，也不会再把制品判成「摘要不符」。
    `制品完整性摘要.json` 必须排除在身份口径外：构建器写完它之后才回读算摘要，
    纳入即自指（见 客户端/构建平台客户端.py::计算制品摘要 与 写盘后自校验）。
    """
    哈希器 = hashlib.sha256()
    for 文件 in sorted(Path(目录).rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        if _是运行时数据(文件.relative_to(目录)):
            continue
        if 文件.name in 身份排除文件名表:
            continue
        哈希器.update(str(文件.relative_to(目录)).encode("utf-8"))
        哈希器.update(文件.read_bytes())
    return 哈希器.hexdigest()[:摘要前缀长度]


# 二进制资产后缀（示例/验证数据 等真实二进制文件，hex 编码入库）
_二进制文件后缀表 = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                  ".woff", ".woff2", ".ttf", ".otf", ".ico", ".mp3", ".wav",
                  ".mp4", ".zip", ".xlsx", ".docx", ".pptx", ".db", ".sqlite", ".sqlite3"}
_二进制前缀 = "hexfile:"
# 生成性元数据的两张排除表**不在本模块再维护一份**：统一从 签名能力 导入（唯一事实源，
# 见文件头部 import）。二者分属两个口径（见 签名能力 顶部注释）：
# - 读取制品文件表 用 `清单排除文件名表`（决定 文件清单 = 内容寻址与签名覆盖面）；
# - 计算目录摘要16 用 `身份排除文件名表`（决定 制品身份/目录名摘要，比清单口径多排
#   `制品完整性摘要.json`，因为构建器是写完它之后才回读算摘要）。


def 读取制品文件表(制品目录: Path) -> dict[str, str]:
    """把制品目录全部正式文件读为 相对路径→文本 文件表（供 包仓库.构建制品）。

    身份口径（与构建侧同名摘要**同一事实源**）：只算**内容文件**，入库后处理写入的元数据
    `物料清单.json`／`制品摘要.json`／`制品来源.json`／`编译清单.json`（= `清单排除文件名表`，
    从 签名能力 导入，本模块不再维护第二份）不参与：它们在各自写入时互相引用
    （尤其 `制品摘要.json` 内含自身摘要），纳入会造成自指与两侧口径不一致，
    实测表现是"同内容重复入库被当成双摘要"（2026-09-15 踩坑）。
    注意：`制品完整性摘要.json` **不在**本口径排除表内——它随内容寻址落盘、进文件清单、
    被签名覆盖（签名侧 `制品正式文件集` 同调同一张表）；只在**身份摘要**口径里排除。

    **运行时数据**（`_是运行时数据`，路径含 `工程缓存` 段）同样不参与：它们连正式
    文件都不算，不入库、不进物料清单（D-17 ②；与 `计算目录摘要16` 共用同一判定点）。
    """
    文件表: dict[str, str] = {}
    for 文件 in sorted(Path(制品目录).rglob("*")):
        if 文件.is_dir() or "__pycache__" in 文件.parts:
            continue
        if _是运行时数据(文件.relative_to(制品目录)):
            continue
        if 文件.name in 清单排除文件名表:
            # 生成性元数据不参与**内容寻址与身份**（它们随构建变化：制品来源含工作区指纹、
            # 制品摘要含自身摘要）。登记完成后由 入库 落到该制品目录，供安装与溯源——
            # 见 入库 的"元数据落盘"（2026-09-15 修：参与摘要会导致同身份双摘要）
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
        # 1b. 生成元数据落盘：它们不参与内容寻址（见 读取制品文件表），但要随制品进入
        #     内容寻址目录，安装后才带溯源（发布门禁读 制品来源.json；2026-09-15 修）
        self._落盘生成元数据(制品目录, 制品摘要)
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
        # 4. 入库自检（消除「假成功」）：入库即验，验不过就不许报成功。
        #    为什么必须有：签名侧 `制品正式文件集` 与入库侧 `读取制品文件表` 曾各维护一份
        #    排除表（签名侧多排 `制品完整性摘要.json`），使 校验签名/校验制品 对**任何**
        #    制品恒 False，而 入库 依然返回 True —— 现场 35/35 条记录都是这种「入库成功、
        #    校验必失败」的假成功（2026-09-17 实测）。自检把这条静默失联变成当场失败。
        自检通过, 自检消息 = self.校验制品(制品摘要)
        if not 自检通过:
            return False, (f"入库自检失败（内容寻址与信任元数据已写入，但校验不通过，"
                           f"拒绝报成功）: {自检消息}"), 制品摘要
        return True, f"已入库（内容寻址+签名+信任元数据）：{制品名}", 制品摘要

    def _落盘生成元数据(self, 制品目录: Path, 制品摘要: str) -> None:
        """把构建期生成的溯源元数据复制进内容寻址制品目录（幂等；物料清单由仓库自己生成，不覆盖）。

        为什么需要：这些文件不参与内容寻址与身份（否则"同身份双摘要"），但安装后的稳定路径
        必须带溯源，发布门禁会读 `制品来源.json`。
        """
        目标目录 = self.制品根目录 / 制品摘要
        if not 目标目录.is_dir():
            return
        for 文件名 in ("制品摘要.json", "制品来源.json", "制品完整性摘要.json", "编译清单.json"):
            源 = 制品目录 / 文件名
            if 源.is_file():
                shutil.copy2(源, 目标目录 / 文件名)

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
        # 陈旧指针拒绝：只拒**真陈旧**（源与已安装都不可信）；源制品目录单边被写脏时
        # 放行并由下面的重装覆盖修复（D-17 ①；错误说明带诊断级别与修复出口，可诊断可修）
        指针诊断 = self.诊断激活指针()
        if not 指针诊断["可继续"]:
            return False, (f"当前激活指针陈旧（{指针诊断['陈旧级别']}），拒绝安装: "
                           f"{指针诊断['原因']}；修复出口："
                           f"平台客户端制品接入.重建激活指针() 或 .重置激活指针()"), None
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
        if 计算目录摘要16(目标) != 摘要16:
            return False
        # 溯源元数据也要一致：它们不参与内容摘要（见 读取制品文件表），若只按内容摘要判"已安装"，
        # 安装目录会留着**旧提交号/旧工作区指纹**的 制品来源.json → 发布门禁报
        # 「来源提交与当前 HEAD 不一致」（2026-09-15 实测踩坑）。
        来源目录 = self.制品根目录 / 制品摘要
        for 文件名 in ("制品来源.json", "编译清单.json"):
            源 = 来源目录 / 文件名
            现状 = 目标 / 文件名
            if 源.is_file() and (not 现状.is_file() or 源.read_bytes() != 现状.read_bytes()):
                return False
        return True

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
        # 落盘统一走 `_写指针文件原始`（D-17 ①：重建/重置与安装必须同一处原子写，不复制）
        self._写指针文件原始(数据)

    # ---- 校验（陈旧指针拒绝 / 外部调用方稳定路径） ----
    def 诊断激活指针(self) -> dict[str, Any]:
        """可诊断的陈旧指针判定（D-17 ①）：只读，不改任何文件。

        判定**源制品目录**与**已安装副本**两处，`陈旧` 只在两处都对不上时报真：
        - `源符合`：制品仓库里的源制品目录（`工程缓存/制品仓库/平台客户端制品/<名>`）
          的实算摘要与指针一致。源目录是二次构建的中间产物，会被制品进程写脏，
          **不该单独决定安装是否被拒**（这是 2026-09-16 实测踩到的设计缺陷）。
        - `已安装符合`：已安装副本（`环境目录/平台客户端`）的实算摘要与指针一致；
          外部调用方真正读到的是它，它才是指针许诺的落点。
        - `陈旧`：源与已安装**都不符合**或指针本身不可读/指向不存在 → 真陈旧，必须重置；
          单边不符只记 `陈旧级别`（`源目录被写脏（已安装副本正常）` / `已安装副本被改`）并可继续安装修复。
        返回键：`陈旧/可继续/原因/陈旧级别/源符合/已安装符合/摘要16/制品名/制品摘要`。
        """
        指针文件 = self.环境目录 / "当前.json"
        结论: dict[str, Any] = {
            "陈旧": False, "可继续": True, "原因": "", "陈旧级别": "无",
            "源符合": False, "已安装符合": False,
            "摘要16": "", "制品名": "", "制品摘要": "",
        }
        if not 指针文件.is_file():
            结论["原因"] = "从未安装（无 当前.json），无指针可查"
            return 结论
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as 错误:
            结论.update({"陈旧": True, "可继续": False,
                         "陈旧级别": "指针文件不可读", "原因": f"激活指针文件不可读: {错误}"})
            return 结论
        摘要16 = str(指针.get("摘要sha256", ""))
        制品名 = str(指针.get("制品目录", ""))
        制品摘要 = str(指针.get("制品摘要", ""))
        结论.update({"摘要16": 摘要16, "制品名": 制品名, "制品摘要": 制品摘要})
        源目录 = self.客户端制品目录 / 制品名 if 制品名 else None
        源存在 = bool(源目录 is not None and 源目录.is_dir())
        已安装 = self.环境目录 / "平台客户端"
        已安装存在 = 已安装.is_dir()
        摘要合法 = len(摘要16) == 摘要前缀长度
        结论["源符合"] = bool(源存在 and 摘要合法 and 计算目录摘要16(源目录) == 摘要16)
        结论["已安装符合"] = bool(已安装存在 and 摘要合法 and 计算目录摘要16(已安装) == 摘要16)
        if 结论["源符合"] or 结论["已安装符合"]:
            if not 结论["源符合"]:
                结论["陈旧级别"] = "源目录被写脏（已安装副本正常）"
                结论["原因"] = (f"源制品目录 {制品名 or '<空>'} 与指针摘要不符，已安装副本正常；"
                               f"按已安装副本判定，可继续安装（安装会重建源制品目录）")
            elif not 结论["已安装符合"]:
                结论["陈旧级别"] = "已安装副本被改（源制品正常）"
                结论["原因"] = ("已安装副本摘要与指针不符（源制品正常）；重装同摘要可修复，"
                               "或重置激活指针回「从未安装」")
            elif not 摘要合法:
                结论["陈旧级别"] = "指针摘要字段不合法"
                结论["原因"] = f"激活指针摘要字段不合法: {摘要16!r}"
            if 制品摘要:
                记录 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
                if 记录 is None:
                    结论["陈旧级别"] = "指向制品未入库（摘要缺失）"
                    结论["原因"] = f"激活指针指向的制品未入库: {制品摘要[:16]}…"
            return 结论
        if not 源存在 and not 已安装存在:
            结论.update({"陈旧": True, "可继续": False,
                         "陈旧级别": "指向制品目录不存在",
                         "原因": f"激活指针指向的制品目录不存在: {制品名 or '<空>'}"})
            return 结论
        if not 摘要合法:
            结论.update({"陈旧": True, "可继续": False,
                         "陈旧级别": "指针摘要字段不合法",
                         "原因": f"激活指针摘要字段不合法: {摘要16!r}"})
            return 结论
        结论.update({"陈旧": True, "可继续": False, "陈旧级别": "源与已安装摘要均不符",
                     "原因": (f"源制品目录与已安装副本摘要都与指针不符: {制品名}"
                             f"（期望 {摘要16}）")})
        return 结论

    def 检查激活指针(self) -> str | None:
        """陈旧指针检查：**真陈旧**（源与已安装都不可信）→ 返回可诊断原因；否则 None。

        D-17 ①：口径按 `诊断激活指针` 判定，源制品目录单边被写脏**不再**永久拒绝安装
        （源目录是二次构建中间产物，已安装副本才是对外落点）。真陈旧时的修复出口是
        `重建激活指针`（按已安装副本重建）或 `重置激活指针`（清回「从未安装」）。
        """
        结论 = self.诊断激活指针()
        return None if 结论["可继续"] else str(结论["原因"])

    # ---- 修复出口（D-17 ① 的另一半：陈旧必须可修，不能只有「永久拒绝」） ----
    def 重建激活指针(self) -> tuple[bool, str]:
        """按**已安装副本**重建激活指针（D-17 ① 修复出口，不重复安装、不碰制品仓库）。

        适用：源制品目录被写脏/已被清理，而 `环境目录/平台客户端` 完好——
        只把指针的摘要字段改回已安装副本的实算摘要（内容寻址字段不变），
        使稳定路径立刻恢复可读。
        拒绝：已安装副本不存在或摘要非 16 位十六进制（半安装态不可信 → 走 `重置激活指针`）。
        """
        指针文件 = self.环境目录 / "当前.json"
        已安装 = self.环境目录 / "平台客户端"
        if not 已安装.is_dir():
            return False, f"已安装副本不存在，无法重建指针（请先安装或重置）: {已安装}"
        摘要16 = 计算目录摘要16(已安装)
        if len(摘要16) != 摘要前缀长度:
            return False, f"已安装副本摘要不合法，拒绝写入指针: {摘要16!r}"
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8")) if 指针文件.is_file() else {}
        except (OSError, json.JSONDecodeError) as 错误:
            return False, f"激活指针不可读，拒绝覆盖（请人工确认后重置）: {错误}"
        原摘要 = str(指针.get("摘要sha256", ""))
        指针["摘要sha256"] = 摘要16
        指针.setdefault("制品目录", 已安装.name)
        指针.setdefault("制品摘要", "")
        指针.setdefault("版本", 0)
        指针.setdefault("栅栏令牌", 0)
        self._写指针文件原始(指针)
        return True, (f"激活指针已按已安装副本重建：{原摘要 or '<空>'} → {摘要16}"
                     f"（已安装副本 {已安装}）")

    def 重置激活指针(self) -> tuple[bool, str]:
        """清掉激活指针，回到「从未安装」状态（D-17 ① 修复出口）。

        只动 `环境目录/当前.json`：改名保存为 `当前.json.陈旧指针备份_<时间戳>`（**不删除**，
        留痕可回溯），不碰制品仓库、不碰已安装副本。发布管理的激活指针同批清空，
        避免留下「文件说没装、账本说已激活」的第二事实源。
        """
        指针文件 = self.环境目录 / "当前.json"
        步骤: list[str] = []
        if 指针文件.is_file():
            备份 = 指针文件.with_name(f"当前.json.陈旧指针备份_{time.strftime('%Y%m%d%H%M%S')}")
            os.replace(指针文件, 备份)
            步骤.append(f"指针已备份: {备份}")
        else:
            步骤.append("无 当前.json（已是未安装态）")
        激活 = self.发布.当前激活(self.包id)
        if 激活:
            self.状态.写入记录("激活指针", {
                "指针id": self.包id, "目标": "", "版本": int(激活.get("版本", 0)) + 1,
                "栅栏令牌": int(激活.get("栅栏令牌", 0)) + 1, "状态": "已清空"})
            步骤.append("发布管理激活指针已清空（版本+1、栅栏令牌+1，防陈旧写者覆盖）")
        else:
            步骤.append("发布管理侧无激活记录")
        步骤.append("当前状态：从未安装（下次安装走首次安装分支）")
        return True, "；".join(步骤)

    def _写指针文件原始(self, 指针: dict[str, Any]) -> None:
        """原子写指针字典到 环境目录/当前.json（`_写指针文件` 的底层落盘步骤，唯一落盘点）。"""
        指针文件 = self.环境目录 / "当前.json"
        临时指针 = self.环境目录 / ".当前.json.tmp"
        临时指针.write_text(json.dumps(指针, ensure_ascii=False), encoding="utf-8")
        with open(临时指针, "rb") as 句柄:
            os.fsync(句柄.fileno())
        os.replace(临时指针, 指针文件)
        目录句柄 = os.open(self.环境目录, os.O_RDONLY)
        try:
            os.fsync(目录句柄)
        finally:
            os.close(目录句柄)

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


__all__ = ["平台客户端制品接入", "计算目录摘要16", "读取制品文件表", "运行时数据段名"]
