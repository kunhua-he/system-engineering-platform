"""验证报告：验证器统一结果模型。

任何验证范围的结果使用同一结构：目标、范围、通过数、失败数、跳过数、
未执行数、问题清单、耗时。禁止零测试仍然成功。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class 验证报告:
    """一次验证执行的结果。"""

    目标: str
    验证范围: str
    通过数: int = 0
    失败数: int = 0
    跳过数: int = 0
    未执行数: int = 0
    问题清单: list[str] = field(default_factory=list)
    耗时秒: float = 0.0
    开始时间: float = field(default_factory=time.monotonic)

    @property
    def 门禁通过(self) -> bool:
        """通过 = 无失败、无未执行，且存在真实通过项。"""
        return self.失败数 == 0 and self.未执行数 == 0 and self.通过数 > 0

    def 记录通过(self, 名称: str) -> None:
        self.通过数 += 1

    def 记录失败(self, 名称: str, 原因: str = "") -> None:
        self.失败数 += 1
        self.问题清单.append(f"{名称}: {原因}" if 原因 else 名称)

    def 记录跳过(self, 名称: str, 原因: str = "") -> None:
        if not 原因:
            self.问题清单.append(f"未解释跳过: {名称}")
        self.跳过数 += 1

    def 记录未执行(self, 名称: str, 原因: str) -> None:
        self.未执行数 += 1
        self.问题清单.append(f"未执行: {名称}（{原因}）")

    def 收口(self) -> None:
        self.耗时秒 = round(time.monotonic() - self.开始时间, 3)

    def 打印(self) -> str:
        self.收口()
        行列表 = [
            "=" * 50,
            f"统一验证报告（目标: {self.目标} / 范围: {self.验证范围}）",
            "=" * 50,
            f"通过: {self.通过数}  失败: {self.失败数}  跳过: {self.跳过数}  未执行: {self.未执行数}",
            f"耗时: {self.耗时秒} 秒",
        ]
        if self.问题清单:
            行列表.append("问题清单:")
            for 问题 in self.问题清单:
                行列表.append(f"  ✗ {问题}")
        行列表.append(f"门禁: {'通过' if self.门禁通过 else '失败'}")
        return "\n".join(行列表)
