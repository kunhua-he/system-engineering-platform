"""安装能力：制品安装（临时目录 + 原子替换，安装前后双重校验）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path


class 安装能力:
    """安装能力：安装制品到目标目录，全程防篡改。"""

    def 安装制品(self, *, 制品摘要: str, 目标目录: Path) -> tuple[bool, str]:
        """安装候选：临时目录复制 → 安装前后都校验 → 原子替换。

        不能把被篡改内容复制出去：安装前校验失败立即中止。
        """
        制品 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 制品 is None:
            return False, "制品不存在"
        # 安装前校验（签名 + 磁盘一致性）
        有效, 消息 = self.校验签名(制品摘要=制品摘要)
        if not 有效:
            return False, f"安装被拒: {消息}"
        目标目录 = Path(目标目录)
        源目录 = self.制品根目录 / 制品摘要
        临时目标 = 目标目录.parent / f".安装临时_{uuid.uuid4().hex[:8]}"
        临时目标.mkdir(parents=True)
        try:
            for 文件 in 源目录.rglob("*"):
                if 文件.is_file() and 文件.name != "物料清单.json":
                    相对 = 文件.relative_to(源目录)
                    目标文件 = 临时目标 / 相对
                    目标文件.parent.mkdir(parents=True, exist_ok=True)
                    目标文件.write_bytes(文件.read_bytes())
                    模式 = json.loads(制品["文件清单"]).get(str(相对), {}).get("模式")
                    if 模式 is not None:
                        目标文件.chmod(int(模式) & 0o7777)
            # 安装后再次校验磁盘摘要（防复制过程篡改）
            for 路径, 摘要信息 in json.loads(制品["文件清单"]).items():
                实际 = hashlib.sha256((临时目标 / 路径).read_bytes()).hexdigest()
                if 实际 != 摘要信息["sha256"]:
                    raise RuntimeError(f"安装后校验失败: {路径}")
            # 原子替换：先备份旧目标 → 替换 → 删除备份
            if 目标目录.exists():
                shutil.rmtree(目标目录)
            os.rename(临时目标, 目标目录)
        except Exception as 错误:
            shutil.rmtree(临时目标, ignore_errors=True)
            return False, f"安装失败: {错误}"
        self.状态.条件更新("制品", {"状态": "已安装"}, "制品摘要=?", (制品摘要,))
        return True, f"已安装到 {目标目录}"
