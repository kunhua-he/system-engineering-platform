"""装配锁：装配前一次性完成的依赖拓扑、版本锁、能力锁与提供者锁。

装配锁在装配动作之前由声明与解析结果生成并校验完成；后续装配只按锁
执行，不再重新推导。同一注册表上重复装配时，装配锁完全一致才可重放
（严格幂等）；任一不同（版本漂移/提供者漂移/顺序漂移）必须冲突失败，
且不得留下半装配状态。
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field

from 公共契约.包声明.声明 import 包声明

装配状态锁 = threading.Lock()
# 装配状态按注册表实例隔离：同一注册表上的重复装配才做幂等/漂移校验；
# 每次装配新建的注册表互不影响，不同注册表各自独立。
装配状态表: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class 装配锁:
    """一次确定性装配的锁。

    顺序列表: 依赖拓扑顺序（提供者在先，支持库先于模块），可复现。
    版本锁:   包id -> 版本。
    能力锁:   能力id -> 提供包id。
    提供者锁: 能力id -> 提供版本。
    """

    顺序列表: tuple[str, ...] = ()
    版本锁: dict[str, str] = field(default_factory=dict)
    能力锁: dict[str, str] = field(default_factory=dict)
    提供者锁: dict[str, str] = field(default_factory=dict)

    def 差异说明(self, 新锁: "装配锁") -> list[str]:
        """与另一装配锁比较，返回冲突说明；完全一致时为空列表。"""
        差异: list[str] = []
        for 包id in sorted(set(self.版本锁) | set(新锁.版本锁)):
            旧版本 = self.版本锁.get(包id)
            新版本 = 新锁.版本锁.get(包id)
            if 旧版本 != 新版本:
                差异.append(f"包 {包id} 版本漂移: {旧版本 or '无'} → {新版本 or '无'}")
        for 能力id in sorted(set(self.能力锁) | set(新锁.能力锁)):
            旧提供方 = self.能力锁.get(能力id)
            新提供方 = 新锁.能力锁.get(能力id)
            if 旧提供方 != 新提供方:
                差异.append(f"能力 {能力id} 提供者漂移: {旧提供方 or '无'} → {新提供方 or '无'}")
        if list(self.顺序列表) != list(新锁.顺序列表):
            差异.append(f"装配顺序漂移: {list(self.顺序列表)} → {list(新锁.顺序列表)}")
        return 差异


def 构建装配锁(
    活跃声明列表: list[包声明],
    提供者表: dict,
    顺序列表: list[str],
) -> 装配锁:
    """装配前构建装配锁（只读声明与解析结果，不加载任何实现）。"""
    版本锁 = {声明.包id: 声明.版本 for 声明 in 活跃声明列表}
    能力锁 = {
        能力id: 选择.提供包id
        for 能力id, 选择 in 提供者表.items()
        if 选择.成功
    }
    提供者锁 = {
        能力id: 选择.提供版本
        for 能力id, 选择 in 提供者表.items()
        if 选择.成功
    }
    return 装配锁(
        顺序列表=tuple(顺序列表),
        版本锁=版本锁,
        能力锁=能力锁,
        提供者锁=提供者锁,
    )


def 读取装配状态(注册表) -> 装配锁 | None:
    """读取注册表对应的上次成功装配锁；未装配过返回 None。"""
    with 装配状态锁:
        return 装配状态表.get(注册表)


def 记录装配状态(注册表, 装配锁: 装配锁) -> None:
    """装配成功后记录注册表对应的装配锁（重复装配幂等校验依据）。"""
    with 装配状态锁:
        装配状态表[注册表] = 装配锁


def 清除装配状态(注册表) -> None:
    """卸载后清除装配状态：注册表清空时装配锁一并失效。"""
    with 装配状态锁:
        if 注册表 in 装配状态表:
            del 装配状态表[注册表]
