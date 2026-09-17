"""可信仓库元数据：根信任、目标制品、仓库快照、新鲜度四类元数据。

真实 Ed25519（经 支持库.适配层 公开入口 → 密码签名提供者 隔离子进程）签名与验证；阻断替换、回退、冻结、过期。
根私钥绝不写入任何元数据正文；轮换需旧根+新根共同签名或离线恢复密钥。

根私钥落位口径（本平台是「相对安全、面向本地私有部署」，底线是不造成系统性破坏）：
1. **优先引用外部密钥**：构造时给 `根私钥引用`（`钥匙串:账户:服务` 或 `环境变量:键`），
   私钥经 支持库.适配层 包级入口（创建密钥提供者）读进内存，盘上不留任何私钥文件；
2. 未配置引用时按本地文件方式保存（兼容既有仓库），但落盘一律 0600 权限 + 原子替换，
   `密钥目录` 可指向受控目录把私钥挪出元数据目录；
3. 初始化时校验磁盘私钥与 根信任.json 公钥是否配对：不配对（轮换半途崩溃等）就明确
   报错，而不是继续用错钥匙签出一堆「签名无效」。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from 支持库.适配层 import 生成密钥对, 内容摘要, 签名 as 真实签名, 验证签名 as 真实验签
from 支持库.适配层 import 创建密钥提供者
from 公共契约.基础类型.逻辑类型 import 真, 假


def _签名正文(元数据: dict) -> bytes:
    """签名正文：去掉全部签名字段后的规范化 JSON。"""
    干净 = {键: 值 for 键, 值 in 元数据.items() if not 键.endswith("签名")}
    return json.dumps(干净, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _原子写文本(路径: Path, 文本: str, 权限位: int = 0o600) -> None:
    """tmp + fsync + os.replace 原子落盘，落盘权限显式收紧（私钥必须 0600）。

    与 客户端/构建平台客户端._原子写入 同口径：进程中断不会留下半截 JSON/PEM。
    """
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时 = 路径.parent / f".{路径.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    描述符 = -1
    try:
        描述符 = os.open(临时, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 权限位)
        os.fchmod(描述符, 权限位)
        视图 = memoryview(文本.encode("utf-8"))
        while 视图:
            已写 = os.write(描述符, 视图)
            视图 = 视图[已写:]
        os.fsync(描述符)
        os.close(描述符)
        描述符 = -1
        os.replace(临时, 路径)
    except BaseException:
        # 任何失败都清掉临时文件：既有私钥/元数据在别处，不受影响
        if 描述符 >= 0:
            os.close(描述符)
        try:
            os.unlink(临时)
        except FileNotFoundError:
            pass
        raise
    try:
        目录描述符 = os.open(路径.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(目录描述符)
    except OSError:
        pass
    finally:
        os.close(目录描述符)


class 可信仓库元数据:
    """可信仓库四类元数据服务；存储目录保存元数据与（未用外部密钥时的）本地私钥。"""

    def __init__(self, 存储目录: Path | str, 根密钥对: tuple | None = None,
                 有效期秒: float = 2592000, 根私钥引用: str = "",
                 密钥目录: Path | str | None = None) -> None:
        self.目录 = Path(存储目录)
        self.元数据目录 = self.目录 / "元数据"
        self.制品目录 = self.目录 / "制品"
        self.有效期秒 = 有效期秒
        # 私钥目录独立可配：默认与 存储目录 同根（兼容既有仓库布局），
        # 配置后私钥可挪到受控目录，不与元数据混在一起。
        self.密钥目录 = Path(密钥目录) if 密钥目录 else self.目录
        self.根私钥引用 = str(根私钥引用 or "").strip()
        self.密钥提供者 = 创建密钥提供者()
        self.当前根私钥 = 根密钥对[0] if 根密钥对 else None
        self.当前根公钥 = 根密钥对[1] if 根密钥对 else None
        # 私钥来源优先级：显式密钥对 > 外部密钥引用（盘上无文件） > 本地私钥文件
        if self.当前根私钥 is None and self.根私钥引用:
            self.当前根私钥 = self._从密钥提供者读根私钥()
        if self.当前根私钥 is None:
            本地私钥 = self._读取私钥文件(self._私钥路径("根私钥"))
            if 本地私钥 is not None:
                self.当前根私钥 = 本地私钥
        if self.当前根公钥 is None:
            根信任 = self._读取("根信任")
            if 根信任:
                self.当前根公钥 = 根信任.get("公钥", "")
        self._校验私钥公钥配对()

    # ---- 密钥落位 ----
    def _私钥路径(self, 名字: str) -> Path:
        """私钥路径：优先密钥目录；不存在时回退历史位置（存储目录根）。"""
        主路径 = self.密钥目录 / f"{名字}.pem"
        if 主路径.is_file() or self.密钥目录 == self.目录:
            return 主路径
        历史路径 = self.目录 / f"{名字}.pem"
        return 历史路径 if 历史路径.is_file() else 主路径

    def _读取私钥文件(self, 路径: Path) -> str | None:
        try:
            return 路径.read_text(encoding="utf-8")
        except OSError:
            return None

    def _从密钥提供者读根私钥(self) -> str:
        """经 支持库.适配层.创建密钥提供者 读根私钥（钥匙串/环境变量），值只在内存。"""
        成功, 值, 错误码 = self.密钥提供者.读取(self.根私钥引用)
        if not 成功:
            raise ValueError(f"根私钥引用读取失败: {self.根私钥引用}（{错误码}）")
        return 值

    def _写私钥(self, 名字: str, 私钥: str) -> Path:
        """私钥落盘：0600 + 原子替换；配置了外部引用时不落盘（返回空路径占位）。"""
        路径 = self._私钥路径(名字)
        if self.根私钥引用 and 名字 == "根私钥":
            # 外部引用模式：根私钥由钥匙串/环境变量持有，盘上不写
            return 路径
        _原子写文本(路径, 私钥, 0o600)
        return 路径

    def _校验私钥公钥配对(self) -> None:
        """磁盘/内存私钥必须与根信任公钥配对；不配对即明确报错（不静默签出无效签名）。

        为什么要检：轮换过程中断会让 根私钥.pem 与 根信任.json 各是新旧一半，
        旧实现下新进程会一路用错钥匙签出「签名无效」，故障被埋成静默瘫痪。
        """
        if not self.当前根私钥 or not self.当前根公钥:
            return
        探针 = "根私钥配对探针".encode("utf-8")
        try:
            签名值 = 真实签名(self.当前根私钥, 探针)
        except (ValueError, RuntimeError):
            raise ValueError("根私钥不可用：无法解析为合法 Ed25519 私钥") from None
        if not 真实验签(self.当前根公钥, 探针, 签名值):
            raise ValueError(
                "根私钥与根信任公钥不配对（疑似轮换未完成）："
                "请用离线恢复私钥重新轮换，或修正 根私钥.pem 后再启动")

    # ---- 存储基础 ----
    def _写入(self, 文件名: str, 元数据: dict) -> None:
        self.元数据目录.mkdir(parents=True, exist_ok=True)
        _原子写文本(self.元数据目录 / f"{文件名}.json",
                   json.dumps(元数据, ensure_ascii=False, indent=2), 0o644)

    def _读取(self, 文件名: str) -> dict | None:
        try:
            return json.loads((self.元数据目录 / f"{文件名}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _最新版本(self, 类型: str) -> int:
        if 类型 == "根信任":
            根 = self._读取("根信任")
            return int(根["元数据版本"]) if 根 else 0
        return max((int(json.loads(文件.read_text(encoding="utf-8"))["元数据版本"])
                    for 文件 in self.元数据目录.glob(f"{类型}_*.json")), default=0)

    # ---- 根信任 ----
    def 初始化(self) -> dict:
        """生成根密钥、写入根信任元数据；根私钥/恢复私钥按落位口径保存。"""
        self.目录.mkdir(parents=True, exist_ok=True)
        if self.当前根公钥 is None and self.当前根私钥 is None:
            self.当前根私钥, self.当前根公钥 = 生成密钥对()
        if self.当前根私钥 is None:
            raise ValueError(
                "已有根信任公钥但取不到根私钥：请提供 根私钥引用 或恢复 根私钥.pem 后再初始化")
        if self.当前根公钥 is None:
            raise ValueError(
                f"根私钥来自外部引用（{self.根私钥引用}）但没有对应公钥，新仓库无法自证："
                "请改传 根密钥对，或先在本地文件模式初始化后再切到密钥引用模式")
        恢复私钥, 恢复公钥 = 生成密钥对()
        # 私钥先落位（0600 + 原子替换）；外部引用模式下根私钥不落盘
        self._写私钥("根私钥", self.当前根私钥)
        self._写私钥("恢复私钥", 恢复私钥)
        正文 = {"类型": "根信任", "元数据版本": 1, "公钥": self.当前根公钥,
                "恢复公钥": 恢复公钥, "签名时间": time.time(),
                "过期时间": time.time() + self.有效期秒}
        元数据 = {**正文, "签名": 真实签名(self.当前根私钥, _签名正文(正文))}
        self._写入("根信任", 元数据)
        return 元数据

    def 轮换根信任(self, 新私钥: str, 新公钥: str, 旧根私钥: str | None = None,
                   恢复私钥: str | None = None) -> dict:
        """轮换根信任：旧根+新根共同签名，或离线恢复密钥替代旧根。

        落盘顺序（旧实现的坑：先覆盖恢复私钥再校验，校验失败就把旧钥毁掉；成功后
        磁盘 根私钥.pem 还是旧钥，新进程一律签出「签名无效」）：
        1. 全部校验在内存完成，**校验不通过前磁盘一个字节都不动**，失败即抛错；
        2. 校验通过后按「恢复私钥 → 根私钥 → 历史根信任 → 新根信任」顺序原子替换；
        3. 中途 OSError 用内存里的旧私钥回滚，避免半新半旧。

        配了 `根私钥引用` 时：根私钥由钥匙串/环境变量持有，本方法**不写私钥文件**，
        因此要求引用里的值已经是新私钥（先更新外部密钥，再轮换）；否则明确报错，
        避免出现「元数据指向新公钥、盘上/钥匙串还是旧私钥」的静默瘫痪。
        """
        if self.根私钥引用:
            引用私钥 = self._从密钥提供者读根私钥()
            if str(引用私钥).strip() != str(新私钥).strip():
                raise ValueError(
                    f"密钥引用模式下根私钥由外部持有（{self.根私钥引用}）："
                    "请先把新根私钥写入钥匙串/环境变量再轮换；本次未改动任何文件")
        旧根 = self._读取("根信任")
        if not 旧根:
            raise ValueError("尚未初始化，无法轮换根信任")
        版本号 = int(旧根["元数据版本"]) + 1
        恢复新私钥, 恢复新公钥 = 生成密钥对()
        正文 = {"类型": "根信任", "元数据版本": 版本号, "公钥": 新公钥,
                "恢复公钥": 恢复新公钥, "签名时间": time.time(),
                "过期时间": time.time() + self.有效期秒}
        元数据 = {**正文,
                  "旧根签名": 真实签名(旧根私钥 or 恢复私钥, _签名正文(正文)),
                  "新根签名": 真实签名(新私钥, _签名正文(正文))}
        成功, 原因 = self.校验元数据("根信任", 元数据)
        if not 成功:
            raise ValueError(f"轮换根信任校验未通过，已放弃轮换（磁盘未改动）: {原因}")
        # 以下才开始落盘：先备份旧私钥内容，供回滚
        旧根私钥内容 = self._读取私钥文件(self._私钥路径("根私钥"))
        旧恢复私钥内容 = self._读取私钥文件(self._私钥路径("恢复私钥"))
        try:
            self._写私钥("恢复私钥", 恢复新私钥)
            self._写私钥("根私钥", 新私钥)
            self._写入(f"根信任_历史_{版本号 - 1}", 旧根)
            self._写入("根信任", 元数据)
        except OSError as 错误:
            for 名字, 内容 in (("恢复私钥", 旧恢复私钥内容), ("根私钥", 旧根私钥内容)):
                if 内容 is None:
                    continue
                try:
                    _原子写文本(self._私钥路径(名字), 内容, 0o600)
                except OSError:
                    pass
            raise OSError(f"根信任轮换落盘失败，已回滚私钥（磁盘保持旧根）: {错误}") from 错误
        self.当前根私钥, self.当前根公钥 = 新私钥, 新公钥
        return 元数据

    # ---- 目标制品 ----
    def 发布目标(self, 包id: str, 版本: str, 制品摘要: str,
                 制品内容: bytes | None = None) -> dict:
        """生成并签名目标元数据；制品内容保存供重算摘要比对。"""
        if 制品内容 is not None:
            self.制品目录.mkdir(parents=True, exist_ok=True)
            (self.制品目录 / f"{包id}_{版本}.bin").write_bytes(制品内容)
        正文 = {"类型": "目标", "包id": 包id, "版本": 版本, "制品摘要": 制品摘要,
                "签名者": "根信任", "签名时间": time.time(),
                "过期时间": time.time() + self.有效期秒}
        元数据 = {**正文, "签名": 真实签名(self.当前根私钥, _签名正文(正文))}
        self._写入(f"目标_{包id}_{版本}", 元数据)
        return 元数据

    # ---- 仓库快照 ----
    def 生成快照(self) -> dict:
        """汇总全部当前目标生成仓库快照（版本单调递增、带时间、签名）。"""
        目标表 = {}
        for 文件 in sorted(self.元数据目录.glob("目标_*.json")):
            目标 = json.loads(文件.read_text(encoding="utf-8"))
            目标表[f"{目标['包id']}@{目标['版本']}"] = 目标["制品摘要"]
        正文 = {"类型": "快照", "元数据版本": self._最新版本("快照") + 1,
                "时间": time.time(), "过期时间": time.time() + self.有效期秒,
                "目标表": 目标表}
        元数据 = {**正文, "签名": 真实签名(self.当前根私钥, _签名正文(正文))}
        self._写入(f"快照_{正文['元数据版本']}", 元数据)
        return 元数据

    # ---- 校验与阻断 ----
    def 校验元数据(self, 元数据类型: str, 元数据: dict) -> tuple[bool, str]:
        """真实验签+摘要比对+过期检查+版本回退检查；任一失败返回明确原因。"""
        原因 = self.阻断检查(元数据类型, 元数据)
        return (假, 原因[0]) if 原因 else (真, "成功")

    def _历史根公钥(self, 目标版本: int) -> str:
        候选 = [self._读取("根信任")]
        候选 += [json.loads(文件.read_text(encoding="utf-8"))
                 for 文件 in sorted(self.元数据目录.glob("根信任_历史_*.json"))]
        旧代 = [根 for 根 in 候选 if 根 and int(根["元数据版本"]) < 目标版本]
        if 旧代:
            return max(旧代, key=lambda 根: 根["元数据版本"])["公钥"]
        return self.当前根公钥

    def 阻断检查(self, 元数据类型: str, 元数据: dict) -> list[str]:
        """返回阻断原因列表；空列表表示全部检查通过。"""
        原因: list[str] = []
        if time.time() > float(元数据.get("过期时间", 0)):
            原因.append("元数据冻结(过期)")
        if 元数据类型 in ("快照", "根信任") and \
                int(元数据.get("元数据版本", 0)) < self._最新版本(元数据类型):
            原因.append("版本回退" if 元数据类型 == "快照" else "版本倒退")
        if 元数据类型 == "目标":
            制品文件 = self.制品目录 / f"{元数据.get('包id', '')}_{元数据.get('版本', '')}.bin"
            if 制品文件.is_file() and 内容摘要(制品文件.read_bytes()) != 元数据.get("制品摘要", ""):
                原因.append("目标被替换")
        elif 元数据类型 == "快照":
            for 键, 摘要 in 元数据.get("目标表", {}).items():
                包id, 版本 = 键.split("@")
                磁盘目标 = self._读取(f"目标_{包id}_{版本}")
                if not 磁盘目标 or 磁盘目标["制品摘要"] != 摘要:
                    原因.append("快照回退")
                    break
        if 元数据类型 == "根信任" and "新根签名" in 元数据:
            旧公钥 = self._历史根公钥(int(元数据.get("元数据版本", 0)))
            if not 真实验签(旧公钥, _签名正文(元数据), 元数据.get("旧根签名", "")):
                原因.append("签名无效")
            if not 真实验签(元数据.get("公钥", ""), _签名正文(元数据),
                             元数据.get("新根签名", "")):
                原因.append("签名无效")
        elif not 真实验签(self.当前根公钥 or "", _签名正文(元数据), 元数据.get("签名", "")):
            原因.append("签名无效")
        return 原因
