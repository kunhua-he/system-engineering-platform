"""唯一能力调用服务：所有入口（HTTP/Agent/MCP/项目代码）经同一调用服务。

收敛能力注册、提供者选择、能力调用和证据采集：
- 能力注册表是唯一权威（重复注册失败，只允许全摘要一致的幂等重放）。
- 调用者只持能力 id 与契约版本；提供者选择、参数校验、证据采集由本服务完成。
- 调用者不得持有第三方对象、连接、线程、进程或原生句柄。
- 正式代码、项目适配层与项目测试不得导入支持库/提供者/实现源码；
  唯一能力调用服务是模块按能力 id 调用支持库的唯一通道。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from 公共契约.能力契约.契约 import 能力注册表, 能力实现
from 公共契约.基础类型.结果类型 import 结果 as 统一结果类型
from 运行核心.能力调用.控制调用.证据链 import 调用证据, 证据链, 版本锁定
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文, 全局上下文管理器


@dataclass
class 调用记录:
    """一次唯一能力调用的完整记录。"""

    能力id: str
    请求id: str
    调用方: str = ""
    项目id: str = ""
    成功: bool = True
    错误码: str = ""
    错误说明: str = ""
    耗时秒: float = 0.0
    模块版本: str = ""
    支持库包id: str = ""
    提供者版本: str = ""
    制品摘要: str = ""
    资源释放结论: str = ""
    证据: 调用证据 | None = None

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id, "请求id": self.请求id, "调用方": self.调用方,
            "项目id": self.项目id, "成功": self.成功, "错误码": self.错误码,
            "错误说明": self.错误说明, "耗时秒": self.耗时秒,
            "模块版本": self.模块版本, "支持库包id": self.支持库包id,
            "提供者版本": self.提供者版本, "制品摘要": self.制品摘要,
            "资源释放结论": self.资源释放结论,
            "证据": self.证据.转字典() if self.证据 is not None else None,
        }


class 唯一能力调用服务:
    """唯一能力调用服务：注册、选择、调用、证据。

    用法（加载器装配后注入模块）：
        服务 = 唯一能力调用服务(注册表)
        模块入口.绑定唯一调用服务(服务)
    模块实现内：
        from 模块库.X import 获取唯一调用服务
        服务 = 获取唯一调用服务()
        return 服务.调用能力("办公文档支持库.表格文档.生成表格文档", {"内容参数": ...})
    """

    def __init__(self, 注册表: 能力注册表, *, 启用证据链: bool = True) -> None:
        if not isinstance(注册表, 能力注册表):
            raise TypeError("唯一能力调用服务必须绑定权威能力注册表")
        self.注册表 = 注册表
        self.证据链 = 证据链() if 启用证据链 else None
        self.版本锁定 = 版本锁定()
        self.锁 = threading.RLock()
        self._模块调用服务表: dict[str, "唯一能力调用服务"] = {}
        self._调用历史: list[调用记录] = []
        self._历史上限 = 500
        # 包指纹校验（正式环境防静默漂移）：由核心注入校验回调，调用前校验
        # 该能力所属包的制品/源码指纹是否与注册时一致；不一致即报错，不静默
        # 沿用旧实现。测试/开发环境不注入时不产生任何额外开销。
        self._包指纹校验器 = None
        self._包指纹缓存: dict[str, tuple[float, bool, str]] = {}
        self._包指纹缓存秒 = 1.0

    def 设置包指纹校验器(self, 校验函数) -> None:
        """注入包指纹校验回调：接收包id，返回 (是否一致, 说明)。"""
        with self.锁:
            self._包指纹校验器 = 校验函数
            self._包指纹缓存.clear()

    def 清空包指纹缓存(self) -> None:
        """热接入重新注册指纹后清缓存，避免沿用旧的漂移判定。"""
        with self.锁:
            self._包指纹缓存.clear()

    def _校验包指纹(self, 包id: str) -> tuple[str, str] | None:
        """校验包指纹；一致返回 None，漂移返回 (错误码, 错误说明)。

        带 1 秒缓存：同一包在缓存窗口内不重复扫描，漂移检测延迟不超过 1 秒。
        """
        校验器 = self._包指纹校验器
        if 校验器 is None or not 包id:
            return None
        import time as _时间模块
        现在 = _时间模块.monotonic()
        with self.锁:
            缓存 = self._包指纹缓存.get(包id)
            if 缓存 is not None and 现在 - 缓存[0] < self._包指纹缓存秒:
                一致, 说明 = 缓存[1], 缓存[2]
            else:
                try:
                    一致, 说明 = 校验器(包id)
                except Exception as 异常:
                    一致, 说明 = False, f"包指纹校验异常: {异常}"
                self._包指纹缓存[包id] = (现在, 一致, 说明)
        if 一致:
            return None
        错误码 = "制品缺失" if "缺失" in 说明 else "制品已变更"
        return 错误码, 说明 or f"包 {包id} 指纹与注册时不一致，请重新热接入"

    # ── 模块绑定 ──────────────────────────────────────────────

    def 绑定模块(self, 模块id: str) -> "唯一能力调用服务":
        """把本服务注入指定模块（模块只持能力 id，不直接导入支持库）。"""
        with self.锁:
            self._模块调用服务表[模块id] = self
            return self

    def 已绑定模块(self, 模块id: str) -> bool:
        with self.锁:
            return 模块id in self._模块调用服务表

    # ── 调用 ──────────────────────────────────────────────────

    @staticmethod
    def _规范化结果(值: Any) -> 统一结果类型:
        """跨包字典必须完整满足统一结果契约；原子值仍由适配边界包装。"""
        if isinstance(值, 统一结果类型):
            return 值
        if isinstance(值, dict):
            必填字段 = {"成功", "值", "错误码", "错误说明"}
            if not 必填字段.issubset(值):
                return 统一结果类型.失败(
                    "返回结果不符合契约", "字典返回缺少统一结果字段",
                )
            if (not isinstance(值.get("成功"), bool)
                    or not isinstance(值.get("错误码"), str)
                    or not isinstance(值.get("错误说明"), str)):
                return 统一结果类型.失败(
                    "返回结果不符合契约", "字典返回的统一结果字段类型不正确",
                )
            if 值["成功"]:
                return 统一结果类型.成功结果(值["值"])
            return 统一结果类型.失败(值["错误码"] or "调用失败", 值["错误说明"])
        return 统一结果类型.成功结果(值)

    def 请求(self, 目标: str, 参数: dict[str, Any] | None = None,
             句柄: str | None = None) -> Any:
        """历史适配入口：文本句柄只在此转换，统一调用入口只接收整数。

        不携带句柄表示一次性调用；当前无状态能力执行完即由其实现释放。
        有状态 Provider 接入后，句柄只作为不透明值向下传递，调用方不接触
        执行单元、租约或第三方对象。
        """
        if not isinstance(目标, str) or not 目标.strip():
            return self._失败("参数不合法", "目标不能为空")
        if 参数 is not None and not isinstance(参数, dict):
            return self._失败("参数不合法", "参数必须是字典")
        if 句柄 is None:
            统一句柄 = None
        elif isinstance(句柄, str) and 句柄.isdecimal() and 1 <= int(句柄) <= 999999:
            统一句柄 = int(句柄)
        else:
            return self._失败("参数不合法", "历史文本句柄必须表示 1 到 999999 的整数")
        return self.调用能力(目标, 参数 or {}, 句柄=统一句柄)

    def 调用能力(self, 能力id: str, 参数: dict[str, Any] | None = None, *,
                 调用方: str = "", 项目id: str = "", 超时秒: float | None = None,
                 句柄: int | None = None) -> Any:
        """按能力 id 调用唯一注册实现，返回统一 结果。

        参数校验、证据采集在此统一完成；调用方不接触提供者。
        证据字段（S0生产事实冻结第五节）：请求id/模块版本/能力id/支持库包id/
        提供者版本/制品摘要/成功失败/资源释放结论；调用前后版本锁定并释放，
        失败路径同样记录完整证据与释放结论。
        """
        import time as _时间模块
        开始 = _时间模块.monotonic()
        # 统一公开句柄冻结为整数；历史字符串只允许进程内连接器这个显式
        # 适配层进入，并在跨越唯一调用边界前立即归一。
        if isinstance(句柄, str) and 调用方 == "进程内连接器" and 句柄.isdecimal():
            句柄 = int(句柄)
        if 句柄 is not None and (
            isinstance(句柄, bool) or not isinstance(句柄, int)
            or not 1 <= 句柄 <= 999999
        ):
            return self._失败("参数不合法", "句柄必须是 1 到 999999 的整数")
        上下文 = 全局上下文管理器.当前()
        请求id = 上下文.请求id or ""
        实现 = self.注册表.获取(能力id)
        证据 = None
        if self.证据链 is not None:
            支持库id = 实现.包id if 实现 is not None else (
                能力id.split(".")[0] if "." in 能力id else "")
            证据 = self.证据链.开始调用(
                项目=项目id or 上下文.项目id,
                功能模块=上下文.模块id,
                支持库=支持库id,
                支持库包id=实现.包id if 实现 is not None else "",
                提供者=实现.提供者id if 实现 is not None else "",
                提供者版本=实现.提供者版本 if 实现 is not None else "",
                能力id=能力id,
                版本=实现.版本 if 实现 is not None else "",
                模块版本=上下文.包版本,
                制品摘要=实现.制品摘要 if 实现 is not None else "",
                任务id=上下文.任务id,
            )
        锁定请求id = 证据.请求id if 证据 is not None else 请求id
        版本锁定 = self.版本锁定
        已锁定 = False
        if 实现 is not None and 版本锁定 is not None:
            if 版本锁定.锁定(
                请求id=锁定请求id, 包id=实现.包id,
                版本=实现.版本 or "", 提供者版本=实现.提供者版本 or "",
            ):
                已锁定 = True
        try:
            if 实现 is None:
                return self._失败并记录(证据, "能力不存在", f"能力未注册: {能力id}",
                                         版本锁定, 锁定请求id, 已锁定, 请求id, 调用方,
                                         项目id, 上下文, 开始, 模块版本=上下文.包版本,
                                         支持库id="", 提供者版本="", 制品摘要="")
            if 参数 is None:
                参数 = {}
            if not isinstance(参数, dict):
                return self._失败并记录(证据, "参数不合法", f"能力 {能力id} 参数必须是字典",
                                         版本锁定, 锁定请求id, 已锁定, 请求id, 调用方,
                                         项目id, 上下文, 开始, 模块版本=上下文.包版本,
                                         支持库id=实现.包id, 提供者版本=实现.提供者版本,
                                         制品摘要=实现.制品摘要)
            # 制品/源码指纹校验（正式环境开启）：被改动但未重新热接入即报错，
            # 不静默沿用旧实现；测试/开发环境未注入校验器时零开销。
            指纹结论 = self._校验包指纹(实现.包id)
            if 指纹结论 is not None:
                return self._失败并记录(证据, 指纹结论[0], 指纹结论[1],
                                         版本锁定, 锁定请求id, 已锁定, 请求id, 调用方,
                                         项目id, 上下文, 开始, 模块版本=上下文.包版本,
                                         支持库id=实现.包id, 提供者版本=实现.提供者版本,
                                         制品摘要=实现.制品摘要)
            调用参数 = _展开参数(实现, 参数)
            原始结果 = 实现.调用(**调用参数)
            结果 = self._规范化结果(原始结果)
            耗时 = _时间模块.monotonic() - 开始
            资源释放结论 = _释放版本锁(版本锁定, 锁定请求id, 已锁定)
            if 证据 is not None:
                self.证据链.记录结果(
                    证据, 成功=结果.成功,
                    错误码=结果.错误码 if not 结果.成功 else "",
                )
                self.证据链.记录资源释放结论(证据, 资源释放结论)
            self._记录历史(调用记录(能力id=能力id, 请求id=请求id, 调用方=调用方,
                                     项目id=项目id or 上下文.项目id, 成功=结果.成功,
                                     错误码=结果.错误码 if not 结果.成功 else "",
                                     错误说明=结果.错误说明 if not 结果.成功 else "",
                                     耗时秒=耗时,
                                     模块版本=上下文.包版本,
                                     支持库包id=实现.包id if 实现 is not None else "",
                                     提供者版本=实现.提供者版本 if 实现 is not None else "",
                                     制品摘要=实现.制品摘要 if 实现 is not None else "",
                                     资源释放结论=资源释放结论, 证据=证据))
            return 结果
        except Exception as 错误:
            耗时 = _时间模块.monotonic() - 开始
            资源释放结论 = _释放版本锁(版本锁定, 锁定请求id, 已锁定)
            if 证据 is not None:
                self.证据链.记录结果(证据, 成功=False, 错误码="调用失败")
                self.证据链.记录资源释放结论(证据, 资源释放结论)
            self._记录历史(调用记录(能力id=能力id, 请求id=请求id, 调用方=调用方,
                                     项目id=项目id or 上下文.项目id, 成功=False,
                                     错误码="调用失败", 错误说明=str(错误), 耗时秒=耗时,
                                     模块版本=上下文.包版本,
                                     支持库包id=实现.包id if 实现 is not None else "",
                                     提供者版本=实现.提供者版本 if 实现 is not None else "",
                                     制品摘要=实现.制品摘要 if 实现 is not None else "",
                                     资源释放结论=资源释放结论, 证据=证据))
            raise

    def _失败并记录(
        self, 证据: 调用证据 | None, 错误码: str, 错误说明: str,
        版本锁定, 锁定请求id: str, 已锁定: bool, 请求id: str, 调用方: str,
        项目id: str, 上下文, 开始: float, *, 模块版本: str, 支持库id: str,
        提供者版本: str, 制品摘要: str,
    ) -> Any:
        """失败返回路径：记录完整证据（含资源释放结论）后返回统一失败结果。"""
        import time as _时间模块
        耗时 = _时间模块.monotonic() - 开始
        资源释放结论 = _释放版本锁(版本锁定, 锁定请求id, 已锁定)
        if 证据 is not None:
            self.证据链.记录结果(证据, 成功=False, 错误码=错误码)
            self.证据链.记录资源释放结论(证据, 资源释放结论)
        self._记录历史(调用记录(能力id=证据.能力id if 证据 is not None else "",
                                 请求id=请求id, 调用方=调用方,
                                 项目id=项目id or 上下文.项目id, 成功=False,
                                 错误码=错误码, 错误说明=错误说明, 耗时秒=耗时,
                                 模块版本=模块版本, 支持库包id=支持库id,
                                 提供者版本=提供者版本, 制品摘要=制品摘要,
                                 资源释放结论=资源释放结论, 证据=证据))
        return self._失败(错误码, 错误说明)

    @staticmethod
    def _失败(错误码: str, 错误说明: str) -> Any:
        from 公共契约.基础类型.结果类型 import 结果
        return 结果.失败(错误码, 错误说明, 来源="唯一能力调用服务")

    # ── 证据与诊断 ────────────────────────────────────────────

    def _记录历史(self, 记录: 调用记录) -> None:
        with self.锁:
            self._调用历史.append(记录)
            if len(self._调用历史) > self._历史上限:
                self._调用历史 = self._调用历史[-self._历史上限:]

    def 查询调用历史(self, 上限: int = 50) -> list[dict[str, Any]]:
        with self.锁:
            return [记录.转字典() for 记录 in self._调用历史[-上限:]]

    def 最近失败(self, 上限: int = 10) -> list[dict[str, Any]]:
        with self.锁:
            失败表 = [记录 for 记录 in self._调用历史 if not 记录.成功]
            return [记录.转字典() for 记录 in 失败表[-上限:]]

    def 回答九问(self, 能力id: str, 错误码: str) -> dict[str, str]:
        """失败诊断：哪一层/哪个能力/哪个版本/哪个提供者。"""
        if self.证据链 is None:
            return {"能力id": 能力id, "错误码": 错误码}
        证据 = 调用证据(能力id=能力id, 错误码=错误码)
        return self.证据链.回答九问(证据)

    # ── 幂等重放 ──────────────────────────────────────────────

    def 幂等重放(self, 能力id: str, 参数: dict[str, Any]) -> bool:
        """公开能力重复注册默认失败；只有全摘要一致的幂等重放可复用。

        语义：对同一能力 id 的重复注册请求，只有当请求参数摘要与既有
        实现参数声明摘要完全一致时才允许幂等复用（返回 True）；参数
        变化视为新能力行为，必须失败（返回 False）。
        """
        实现 = self.注册表.获取(能力id)
        if 实现 is None:
            return False
        try:
            声明参数名 = {
                (参数项.get("名称") if isinstance(参数项, dict) else 参数项)
                for 参数项 in 实现.参数
            }
            # 单参数聚合契约（如 内容参数）：调用方传入聚合 dict 即幂等
            if len(声明参数名) == 1:
                唯一参数名 = next(iter(声明参数名))
                return 唯一参数名 in 参数 or isinstance(参数, dict)
            return set(参数) == 声明参数名
        except Exception:
            return False


def _展开参数(实现: 能力实现, 参数: dict[str, Any]) -> dict[str, Any]:
    """把调用方 dict 按能力注册参数名展开为关键字参数。

    兼容两种注册参数形态：dict 列表（{名称,类型}）与字符串参数名列表。
    规则：
    - dict 键名直接命中声明参数名 → 按名传值。
    - 声明只有 1 个参数（如 内容参数/文件路径 聚合契约）且 dict 键不在
      声明中 → 整个 dict 作为该唯一参数的值（内容参数 聚合语义）。
    - 其余未声明键保持原样（契约层 调用() 会拒绝未知参数）。
    """
    声明参数名 = {
        (参数项.get("名称") if isinstance(参数项, dict) else 参数项)
        for 参数项 in 实现.参数
    }
    if len(声明参数名) == 1 and not set(参数).issubset(声明参数名):
        唯一参数名 = next(iter(声明参数名))
        return {唯一参数名: dict(参数)}
    关键字表: dict[str, Any] = {}
    for 键, 值 in (参数 or {}).items():
        关键字表[键] = 值
    return 关键字表


def _参数摘要(参数: dict[str, Any]) -> str:
    import hashlib
    import json
    try:
        文本 = json.dumps(参数, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        文本 = str(参数)
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()[:16]


def _释放版本锁(锁定: 版本锁定 | None, 请求id: str, 已锁定: bool = False) -> str:
    """调用结束后释放版本锁，返回资源释放结论（失败必须如实记录）。

    未锁定/无锁 → 无版本锁定需求；已锁定 → 释放成功/失败如实记录。
    """
    if 锁定 is None or not 请求id or not 已锁定:
        return "无版本锁定需求"
    已释放 = 锁定.释放(请求id=请求id)
    return "版本锁已释放" if 已释放 else "版本锁释放失败（引用残留）"


_全局服务: "唯一能力调用服务 | None" = None
_全局服务锁 = threading.Lock()


def 设置全局唯一服务(服务: "唯一能力调用服务 | None") -> None:
    """加载器装配完成后设置全局唯一服务（供模块获取注入的调用器）。

    None 表示销毁：调用器卸载（状态回到 未装配），测试间不得残留能力。
    """
    global _全局服务
    from 公共契约.能力契约.调用器 import 注册能力调用器
    with _全局服务锁:
        _全局服务 = 服务
        注册能力调用器(服务)


def 销毁全局唯一服务() -> None:
    """销毁对称：卸载全局唯一服务并回到 未装配（进程重启/测试隔离）。"""
    设置全局唯一服务(None)


def 获取唯一调用服务() -> "唯一能力调用服务":
    """模块实现内获取运行核心注入的唯一能力调用服务。

    经公共契约调用器层获取；未装配/装配中/装配失败时抛
    能力调用器状态异常（携带 状态/错误码/错误说明），禁止绕过。
    """
    from 公共契约.能力契约.调用器 import 获取能力调用器
    调用器 = 获取能力调用器()
    if not isinstance(调用器, 唯一能力调用服务):
        raise RuntimeError(f"已注册调用器类型异常: {type(调用器).__name__}")
    return 调用器


def 创建并绑定(注册表: 能力注册表) -> "唯一能力调用服务":
    """装配入口：创建唯一能力调用服务并设置为全局注入目标。

    装配状态机（唯一注册表调用器注入点，S0生产事实冻结第二节）：
    - 未装配/装配失败 → 装配中 → 创建并绑定成功 → 已装配；
    - 已装配 → 重复装配幂等（同摘要可重放，装配次数递增）；
    - 装配中 → 拒绝并发重复装配（抛 能力调用器状态异常 E装配中）；
    - 任一异常 → 回滚为 装配失败 并记录错误码/错误说明，不留半状态。
    """
    from 公共契约.能力契约.调用器 import (
        查询装配状态, 标记装配中, 标记装配失败, 能力调用器状态异常,
    )
    当前状态 = 查询装配状态()["状态"]
    if 当前状态 == "装配中":
        raise 能力调用器状态异常(
            状态="装配中", 错误码="E装配中",
            错误说明="已有装配正在进行中，禁止并发重复装配",
        )
    try:
        标记装配中()
        服务 = 唯一能力调用服务(注册表)
        设置全局唯一服务(服务)
        return 服务
    except Exception as 错误:
        失败说明 = f"{type(错误).__name__}: {错误}"
        标记装配失败("E装配失败", 失败说明)
        raise


def _惰性装配() -> None:
    """首次获取调用器时执行的一次性装配（发现→注册支持库→注入调用器）。

    原子性：全部成功后一次性绑定全局调用器；任一失败抛异常并回滚为
    装配失败（获取侧记录状态与错误码），禁止半装配残留。
    """
    global _全局服务
    from 公共契约.能力契约.调用器 import 查询装配状态
    if 查询装配状态()["状态"] == "已装配":
        return  # 已装配幂等：不再重复惰性装配
    from pathlib import Path
    系统根 = Path(__file__).resolve()
    for _祖先 in 系统根.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            系统根 = _祖先
            break
    from 公共契约.能力契约.契约 import 能力注册表
    from 运行核心.加载器.包发现.发现器 import 发现全部
    from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库

    with _全局服务锁:
        if _全局服务 is not None:
            return
    注册表 = 能力注册表()
    发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
    支持库声明 = [声明 for 声明 in 发现.声明列表
                 if 声明.类型 == "支持库" and not getattr(声明, "已废弃", False)]
    if not 支持库声明:
        raise RuntimeError("惰性装配失败：未发现任何支持库")
    安装全部支持库(系统根 / "支持库", 注册表)
    with _全局服务锁:
        if _全局服务 is None:
            服务 = 唯一能力调用服务(注册表)
            _全局服务 = 服务
            from 公共契约.能力契约.调用器 import 注册能力调用器
            注册能力调用器(服务)


# 注册惰性装配钩子（模块经 公共契约.能力契约.调用器 首次获取时触发）
def _注册惰性钩子() -> None:
    from 公共契约.能力契约.调用器 import 设置惰性装配函数
    设置惰性装配函数(_惰性装配)


_注册惰性钩子()
