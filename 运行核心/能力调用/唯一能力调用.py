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
    证据: 调用证据 | None = None

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id, "请求id": self.请求id, "调用方": self.调用方,
            "项目id": self.项目id, "成功": self.成功, "错误码": self.错误码,
            "错误说明": self.错误说明, "耗时秒": self.耗时秒,
        }


class 唯一能力调用服务:
    """唯一能力调用服务：注册、选择、调用、证据。

    用法（加载器装配后注入模块）：
        服务 = 唯一能力调用服务(注册表)
        模块入口.绑定唯一调用服务(服务)
    模块实现内：
        from 模块库.X import 获取唯一调用服务
        服务 = 获取唯一调用服务()
        return 服务.调用能力("表格文档.生成表格文档", {"内容参数": ...})
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

    def 调用能力(self, 能力id: str, 参数: dict[str, Any] | None = None, *,
                 调用方: str = "", 项目id: str = "", 超时秒: float | None = None) -> Any:
        """按能力 id 调用唯一注册实现，返回统一 结果。

        参数校验、证据采集在此统一完成；调用方不接触提供者。
        """
        import time as _时间模块
        开始 = _时间模块.monotonic()
        上下文 = 全局上下文管理器.当前()
        请求id = 上下文.请求id or ""
        证据 = None
        if self.证据链 is not None:
            证据 = self.证据链.开始调用(
                项目=项目id or 上下文.项目id,
                功能模块=上下文.模块id,
                支持库=能力id.split(".")[0] if "." in 能力id else "",
                能力id=能力id,
                版本=上下文.包版本,
                任务id=上下文.任务id,
            )
        try:
            实现 = self.注册表.获取(能力id)
            if 实现 is None:
                return self._失败("能力不存在", f"能力未注册: {能力id}")
            if not isinstance(参数, dict):
                return self._失败("参数不合法", f"能力 {能力id} 参数必须是字典")
            调用参数 = _展开参数(实现, 参数)
            结果 = 实现.调用(**调用参数)
            耗时 = _时间模块.monotonic() - 开始
            if 证据 is not None:
                self.证据链.记录结果(证据, 成功=True)
            self._记录历史(调用记录(能力id=能力id, 请求id=请求id, 调用方=调用方,
                                     项目id=项目id or 上下文.项目id, 成功=True, 耗时秒=耗时, 证据=证据))
            return 结果
        except Exception as 错误:
            耗时 = _时间模块.monotonic() - 开始
            if 证据 is not None:
                self.证据链.记录结果(证据, 成功=False, 错误码="调用失败")
            self._记录历史(调用记录(能力id=能力id, 请求id=请求id, 调用方=调用方,
                                     项目id=项目id or 上下文.项目id, 成功=False,
                                     错误码="调用失败", 错误说明=str(错误), 耗时秒=耗时, 证据=证据))
            raise

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

        返回 True 表示该调用与注册实现一致，可安全复用注册结果。
        """
        实现 = self.注册表.获取(能力id)
        if 实现 is None:
            return False
        try:
            参数摘要 = _参数摘要(参数)
            声明参数名 = {参数项.get("名称") for 参数项 in 实现.参数}
            return 参数摘要 in 声明参数名 or all(键 in 声明参数名 for 键 in 参数)
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


_全局服务: "唯一能力调用服务 | None" = None
_全局服务锁 = threading.Lock()


def 设置全局唯一服务(服务: "唯一能力调用服务 | None") -> None:
    """加载器装配完成后设置全局唯一服务（供模块获取注入的调用器）。"""
    global _全局服务
    from 公共契约.能力契约.调用器 import 注册能力调用器
    with _全局服务锁:
        _全局服务 = 服务
        注册能力调用器(服务)


def 获取唯一调用服务() -> "唯一能力调用服务":
    """模块实现内获取运行核心注入的唯一能力调用服务。

    经公共契约调用器层获取；未装配时触发惰性装配，禁止绕过。
    """
    from 公共契约.能力契约.调用器 import 获取能力调用器
    调用器 = 获取能力调用器()
    if not isinstance(调用器, 唯一能力调用服务):
        raise RuntimeError(f"已注册调用器类型异常: {type(调用器).__name__}")
    return 调用器


def 创建并绑定(注册表: 能力注册表) -> "唯一能力调用服务":
    """装配入口：创建唯一能力调用服务并设置为全局注入目标。"""
    服务 = 唯一能力调用服务(注册表)
    设置全局唯一服务(服务)
    return 服务


def _惰性装配() -> None:
    """首次获取调用器时执行的一次性装配（发现→注册支持库→注入调用器）。"""
    global _全局服务
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
