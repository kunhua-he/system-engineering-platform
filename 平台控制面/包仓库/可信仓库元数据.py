"""可信仓库元数据：根信任、目标制品、仓库快照、新鲜度四类元数据。

真实 Ed25519（经 支持库.适配层 公开入口 → 密码签名提供者 隔离子进程）签名与验证；阻断替换、回退、冻结、过期。
根私钥离线保存，绝不写入任何元数据正文；轮换需旧根+新根共同签名或离线恢复密钥。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from 支持库.适配层 import 生成密钥对, 内容摘要, 签名 as 真实签名, 验证签名 as 真实验签


def _签名正文(元数据: dict) -> bytes:
    """签名正文：去掉全部签名字段后的规范化 JSON。"""
    干净 = {键: 值 for 键, 值 in 元数据.items() if not 键.endswith("签名")}
    return json.dumps(干净, ensure_ascii=False, sort_keys=True).encode("utf-8")


class 可信仓库元数据:
    """可信仓库四类元数据服务；存储目录保存元数据与离线密钥。"""

    def __init__(self, 存储目录: Path | str, 根密钥对: tuple | None = None,
                 有效期秒: float = 2592000) -> None:
        self.目录 = Path(存储目录)
        self.元数据目录 = self.目录 / "元数据"
        self.制品目录 = self.目录 / "制品"
        self.有效期秒 = 有效期秒
        self.当前根私钥 = 根密钥对[0] if 根密钥对 else None
        self.当前根公钥 = 根密钥对[1] if 根密钥对 else None

    # ---- 存储基础 ----
    def _写入(self, 文件名: str, 元数据: dict) -> None:
        self.元数据目录.mkdir(parents=True, exist_ok=True)
        (self.元数据目录 / f"{文件名}.json").write_text(
            json.dumps(元数据, ensure_ascii=False, indent=2), encoding="utf-8")

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
        """生成根密钥、写入根信任元数据；根私钥/恢复私钥离线保存。"""
        self.目录.mkdir(parents=True, exist_ok=True)
        if self.当前根公钥 is None:
            self.当前根私钥, self.当前根公钥 = 生成密钥对()
        恢复私钥, 恢复公钥 = 生成密钥对()
        (self.目录 / "根私钥.pem").write_text(self.当前根私钥, encoding="utf-8")
        (self.目录 / "恢复私钥.pem").write_text(恢复私钥, encoding="utf-8")
        正文 = {"类型": "根信任", "元数据版本": 1, "公钥": self.当前根公钥,
                "恢复公钥": 恢复公钥, "签名时间": time.time(),
                "过期时间": time.time() + self.有效期秒}
        元数据 = {**正文, "签名": 真实签名(self.当前根私钥, _签名正文(正文))}
        self._写入("根信任", 元数据)
        return 元数据

    def 轮换根信任(self, 新私钥: str, 新公钥: str, 旧根私钥: str | None = None,
                   恢复私钥: str | None = None) -> dict:
        """轮换根信任：旧根+新根共同签名，或离线恢复密钥替代旧根。"""
        旧根 = self._读取("根信任")
        if not 旧根:
            raise ValueError("尚未初始化，无法轮换根信任")
        版本号 = int(旧根["元数据版本"]) + 1
        恢复新私钥, 恢复新公钥 = 生成密钥对()
        (self.目录 / "恢复私钥.pem").write_text(恢复新私钥, encoding="utf-8")
        正文 = {"类型": "根信任", "元数据版本": 版本号, "公钥": 新公钥,
                "恢复公钥": 恢复新公钥, "签名时间": time.time(),
                "过期时间": time.time() + self.有效期秒}
        元数据 = {**正文,
                  "旧根签名": 真实签名(旧根私钥 or 恢复私钥, _签名正文(正文)),
                  "新根签名": 真实签名(新私钥, _签名正文(正文))}
        if self.校验元数据("根信任", 元数据)[0]:
            self._写入(f"根信任_历史_{版本号 - 1}", 旧根)
            self._写入("根信任", 元数据)
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
        return (False, 原因[0]) if 原因 else (True, "成功")

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
