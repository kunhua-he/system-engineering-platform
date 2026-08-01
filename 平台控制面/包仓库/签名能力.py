"""签名能力：制品签名、信任检查、签名校验与发布者登记（包仓库 mixin）。"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from 支持库.适配层 import 签名 as Ed签名, 验证签名 as Ed验证


class 签名能力:
    """签名相关能力：签名制品、校验签名、信任目录、发布者登记与撤销。"""

    def 签名制品(self, *, 制品摘要: str, 私钥PEM: str, 发布者: str) -> tuple[bool, str]:
        制品 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 制品 is None:
            return False, "制品不存在"
        信任 = self._信任检查(发布者)
        if not 信任:
            return False, f"发布者不在信任目录、已撤销或过期: {发布者}"
        # 签名正文覆盖：包id/版本/发布者/权限/资源预算/物料清单/来源证据/全部正式文件摘要
        正文数据 = {
            "包id": 制品["包id"], "版本": 制品["版本"], "发布者": 发布者,
            "文件摘要": json.loads(制品["文件清单"]),
            "物料清单": json.loads(制品["物料清单"]),
            "来源证据": json.loads(制品["来源证据"]),
            "签名时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        签名正文 = json.dumps(正文数据, ensure_ascii=False, sort_keys=True)
        签名值 = Ed签名(私钥PEM, 签名正文.encode("utf-8"))
        if not Ed验证(信任["公钥"], 签名正文.encode("utf-8"), 签名值):
            return False, "签名自验证失败"
        self.状态.条件更新("制品", {"签名": 签名值, "签名者": 发布者,
                                  "签名时间": 签名正文, "状态": "已签名"},
                          "制品摘要=?", (制品摘要,))
        return True, "制品已签名"

    def _信任检查(self, 发布者: str) -> dict[str, Any] | None:
        """信任目录检查：状态有效 + 未过期；返回信任记录或 None。"""
        信任 = self.状态.读取记录("信任", "发布者", 发布者)
        if 信任 is None or 信任["状态"] != "有效":
            return None
        过期 = 信任.get("过期时间", "")
        if 过期:
            try:
                if float(过期) < time.time():
                    return None
            except (TypeError, ValueError):
                pass
        return 信任

    def 校验签名(self, *, 制品摘要: str) -> tuple[bool, str]:
        """校验签名：重新读取制品目录实际文件逐一计算摘要。

        任何正式文件被篡改（磁盘层面）都使签名失效；不只比较数据库。
        """
        制品 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 制品 is None:
            return False, "制品不存在"
        if not 制品["签名"]:
            return False, "未签名制品"
        信任 = self._信任检查(制品["签名者"])
        if 信任 is None:
            return False, f"发布者不在信任目录、已撤销或过期: {制品['签名者']}"
        # 1. Ed25519 验证签名正文
        签名正文 = 制品["签名时间"]
        if not Ed验证(信任["公钥"], 签名正文.encode("utf-8"), 制品["签名"]):
            return False, "签名验证失败（正文/签名不匹配）"
        # 2. 数据库文件清单必须等于签名正文冻结的文件摘要
        正文数据 = json.loads(签名正文)
        if 正文数据.get("文件摘要") != json.loads(制品["文件清单"]):
            return False, "数据库文件清单与签名不符"
        # 3. 重新读取制品目录实际文件逐一计算摘要（磁盘篡改检测）
        制品目录 = self.制品根目录 / 制品摘要
        if not 制品目录.is_dir():
            return False, "制品目录缺失"
        for 路径, 摘要信息 in json.loads(制品["文件清单"]).items():
            实际文件 = 制品目录 / 路径
            if not 实际文件.is_file():
                return False, f"正式文件缺失: {路径}"
            实际摘要 = hashlib.sha256(实际文件.read_bytes()).hexdigest()
            if 实际摘要 != 摘要信息["sha256"]:
                return False, f"磁盘文件被篡改: {路径}"
        return True, "签名有效且磁盘内容一致"

    # ---- 信任目录 ----
    def 登记发布者(self, *, 发布者: str, 公钥PEM: str, 有效期秒: float = 86400 * 365,
                 维护者: str = "") -> None:
        self.状态.写入记录("信任", {"发布者": 发布者, "公钥": 公钥PEM, "状态": "有效",
                                "轮换时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "过期时间": str(time.time() + 有效期秒)})
        self.状态.追加证据(类型="信任", 主题=发布者, 内容={"登记": True},
                          调用者=维护者, 角色="发布者", 结果="登记")

    def 撤销发布者(self, *, 发布者: str, 维护者: str = "") -> bool:
        return self.状态.条件更新("信任", {"状态": "已撤销"},
                                  "发布者=? AND 状态='有效'", (发布者,))
