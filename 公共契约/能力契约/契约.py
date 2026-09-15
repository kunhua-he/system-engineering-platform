"""能力契约：支持库与模块之间唯一的公开调用边界。

模块不得导入支持库实现，只能按能力契约调用；契约校验保证调用方
声明的参数与提供方实现一致，防止同名不同义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from 公共契约.包声明 import 能力声明


def _参数名(参数: Any) -> str:
    """参数表项取参数名：兼容 dict（{名称,类型}）与字符串参数名两种形态。

    声明一致 与 调用 必须用同一口径取名，否则字符串形态下 声明一致 读到空名、
    把不一致的声明判成一致（判据③ 非期望类型静默通过）。
    """
    if isinstance(参数, dict):
        return str(参数.get("名称", ""))
    return str(参数)


# 注册口径别名表：历史注册写法 → 正式契约类型名。
# 只登记「同一语义、仅写法不同」的项（`结果` 与 `结果型` 是同一种统一结果，
# 不是两种返回结构）；语义确实不同的历史短名（布尔/文本/字典/数值…）**不进本表**，
# 它们属批次4「注册元数据-类型名非正式」的治理范围，混进来会把真问题淹掉。
# 背景（落点清单_03 重要-10）：注册写 `结果`、契约写 `结果型`，全仓首报约 300 条
# 噪声；归一后只剩真实口径差异。
注册口径别名表 = {"结果": "结果型"}


def 归一注册口径(名称: str) -> str:
    """把注册/声明里的写法归一为正式口径名（当前仅 `结果` → `结果型`）。"""
    return 注册口径别名表.get(str(名称 or "").strip(), str(名称 or "").strip())


def 返回口径一致(声明返回: str, 实现返回: str) -> bool:
    """返回口径比较：两边归一后相等即视为一致。

    `声明一致`（:45）与 `校验声明一致`（:113）共用本函数；开发工具.契约编译.
    漂移检测 的「注册口径」子检测也用它，保证运行期校验与编译期门禁同口径，
    否则会出现「门禁过了、运行期判不一致」的第二套判据。
    """
    return 归一注册口径(声明返回) == 归一注册口径(实现返回)


@dataclass(frozen=True)
class 能力实现:
    """能力提供方注册的实现句柄。

    元数据字段（版本/提供者id/提供者版本/制品摘要）供调用证据采集：
    由生产装配注册方提供，缺省为空串；不得伪造，未知即空。
    """

    能力id: str
    包id: str
    实现函数: Callable[..., Any]
    参数: list[dict[str, str]] = field(default_factory=list)
    返回: str = ""
    说明: str = ""
    版本: str = ""
    提供者id: str = ""
    提供者版本: str = ""
    制品摘要: str = ""

    def 声明一致(self, 声明: 能力声明) -> bool:
        """实现句柄与声明的参数/返回是否一致（取名口径与 调用 相同）。

        返回按 `返回口径一致` 归一后比较：注册写 `结果`、契约写 `结果型` 属同一
        口径，不能判成不一致（否则全仓约 300 条噪声）。
        """
        声明参数名 = [_参数名(参数) for 参数 in 声明.参数]
        实现参数名 = [_参数名(参数) for 参数 in self.参数]
        return 声明参数名 == 实现参数名 and 返回口径一致(声明.返回, self.返回)

    def 调用(self, *参数值: Any, **关键字值: Any) -> Any:
        """按契约调用实现；参数名与声明不符时拒绝调用。

        参数表兼容两种形态：dict 列表（{名称,类型}）与字符串参数名列表。
        """
        声明参数名 = {_参数名(参数) for 参数 in self.参数}
        未知关键字 = set(关键字值) - 声明参数名
        if 未知关键字:
            raise TypeError(f"能力 {self.能力id} 收到未知参数: {sorted(未知关键字)}")
        return self.实现函数(*参数值, **关键字值)


class 能力注册表:
    """包级能力注册表：同一能力 id 只允许一个提供方。"""

    def __init__(self) -> None:
        self._实现表: dict[str, 能力实现] = {}

    @property
    def 能力id列表(self) -> list[str]:
        return sorted(self._实现表)

    def 注册(self, 实现: 能力实现) -> None:
        已有 = self._实现表.get(实现.能力id)
        if 已有 is not None and 已有.包id != 实现.包id:
            raise ValueError(
                f"能力 {实现.能力id} 已被 {已有.包id} 注册，禁止 {实现.包id} 重复注册"
            )
        self._实现表[实现.能力id] = 实现

    def 移除(self, 能力id: str, 包id: str = "") -> bool:
        """移除指定能力（热接入回滚/删除场景）。

        传 包id 时只允许移除该包已注册的能力（跨包保护）；
        能力不存在返回 False。
        """
        已有 = self._实现表.get(能力id)
        if 已有 is None:
            return False
        if 包id and 已有.包id != 包id:
            return False
        del self._实现表[能力id]
        return True

    def 获取(self, 能力id: str) -> 能力实现 | None:
        return self._实现表.get(能力id)

    def 清空(self) -> None:
        """卸载时清空全部注册能力（卸载后不得残留提供者）。"""
        self._实现表.clear()

    def 搜索(self, *, 关键词: str = "", 返回类型: str = "") -> list[能力实现]:
        """按关键词与返回类型搜索能力实现。"""
        结果列表 = []
        for 实现 in self._实现表.values():
            if 返回类型 and 实现.返回 != 返回类型:
                continue
            if 关键词 and 关键词 not in 实现.能力id and 关键词 not in 实现.说明:
                continue
            结果列表.append(实现)
        return 结果列表

    def 校验声明一致(self, 包id: str, 声明列表: list[能力声明]) -> list[str]:
        """校验某包声明的能力与注册实现是否一致，返回不一致清单。

        返回口径经 `返回口径一致` 归一后比较（注册 `结果` ≡ 契约 `结果型`），
        与 `声明一致` 同口径；不一致时把两侧口径与参数名一并回带，便于直接定位。
        """
        问题列表: list[str] = []
        for 声明 in 声明列表:
            实现 = self._实现表.get(声明.能力id)
            if 实现 is None:
                问题列表.append(f"{声明.能力id}: 声明了但未注册实现")
            elif 实现.包id != 包id:
                问题列表.append(f"{声明.能力id}: 声明方 {包id} 与实现方 {实现.包id} 不一致")
            elif not 实现.声明一致(声明):
                问题列表.append(
                    f"{声明.能力id}: 声明参数/返回与实现不一致"
                    f"（返回 声明={归一注册口径(声明.返回)} 实现={归一注册口径(实现.返回)}；"
                    f"参数 声明={[_参数名(参数) for 参数 in 声明.参数]}"
                    f" 实现={[_参数名(参数) for 参数 in 实现.参数]}）"
                )
        for 实现 in self._实现表.values():
            if 实现.包id == 包id and not any(声明.能力id == 实现.能力id for 声明 in 声明列表):
                问题列表.append(f"{实现.能力id}: 已注册实现但未在声明中列出")
        return 问题列表
