"""执行器_闸门面：`超时执行器` 的**闸门面职责**混入类（无状态方法）。

方法名与实现逐字沿用原件：拆混入类不改签名、不改默认值、不改行为，只改「归属」，
故对外面（`超时执行器` 的成员名与签名）零变化。
源：`运行核心/能力调用/超时执行.py`（20260919 拆分，开工-20260919-225500-e4a1）。
"""

from __future__ import annotations

import 运行核心.能力调用.超时执行.基础 as 基础常量


class 执行器闸门面:

    @property
    def 全局闸门名(self) -> str:
        return f"{self._闸门基名}.全局"

    @property
    def 兜底闸门名(self) -> str:
        return f"{self._闸门基名}.能力{基础常量.兜底闸门后缀}"

    def 能力闸门名(self, 能力id: str) -> str | None:
        """每能力闸门名（未过登记上限时的规范名）；能力id 为空则不做每能力准入。"""
        return f"{self._闸门基名}.能力.{能力id}" if 能力id else None

    def _路由能力闸门(self, 能力id: str) -> str | None:
        """把 能力id 路由到闸门名：独立闸门（≤ 登记上限）或共享兜底闸门。

        闸门名按 能力id 生成 ⇒ 调用方传任意字符串都会新增一个闸门；若不设登记
        上限，闸门表会被无界撑大（等于把无界从线程搬到闸门表）。超限后统一走
        兜底闸门并计数，有界性与可观测性都在。
        """
        if not 能力id:
            return None
        with self._锁:
            if 能力id in self._已登记能力id:
                return f"{self._闸门基名}.能力.{能力id}"
            if len(self._已登记能力id) >= 基础常量.每能力闸门数上限:
                self._兜底次数 += 1
                return self.兜底闸门名
            self._已登记能力id.add(能力id)
        return f"{self._闸门基名}.能力.{能力id}"
