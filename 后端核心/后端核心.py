"""后端核心：通用运行宿主。

后端核心负责：支持库和模块发现、包版本解析、项目适配装配、能力注册、
能力调用、服务生命周期、后台任务、外部提供者管理、请求上下文、权限
检查、超时和取消、统一错误、运行事件、诊断关联、版本切换、停止和卸载。

后端核心不实现具体业务，只提供通用运行宿主。公开入口只能是能力契约
和统一结果。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 公共契约.运行时.运行缓存 import 运行缓存环境变量, 解析运行缓存根
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文, 全局上下文管理器
from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
from 运行核心.资源协调 import 资源句柄服务, 设置受管状态服务
from 公共契约.诊断.忽略记录 import 记录忽略

_装配模板: 能力注册表 | None = None
_装配锁 = threading.Lock()


@dataclass
class 后端状态:
    """后端核心运行状态。"""

    状态: str = "未启动"  # 未启动/启动中/运行中/已停止/故障
    启动时间: str = ""
    能力数: int = 0
    请求总数: int = 0
    失败请求数: int = 0
    活动请求数: int = 0


class 后端核心:
    """后端核心宿主：装配、注册、调用、任务、生命周期。"""

    def __init__(self, 系统根目录: Path | None = None, *,
                 运行缓存根目录: Path | None = None) -> None:
        self.系统根目录 = 系统根目录 or Path(后端核心.默认系统根())
        if 运行缓存根目录 is None:
            self.运行缓存根目录 = 解析运行缓存根(self.系统根目录)
        else:
            self.运行缓存根目录 = 解析运行缓存根(
                self.系统根目录,
                环境={运行缓存环境变量: str(Path(运行缓存根目录).resolve())},
            )
        self.注册表 = 能力注册表()
        self._唯一调用服务: 唯一能力调用服务 | None = None
        self.状态 = 后端状态()
        self.权限表: dict[str, set[str]] = {}  # 能力id → 允许用户id集合
        self.请求锁 = threading.Lock()
        self.停止标记 = False
        self.事件日志 = None
        self.排空 = None  # 自动排空管理器（启动时装配）
        self.资源句柄服务 = 资源句柄服务(self.运行缓存根目录 / "权威状态")
        设置受管状态服务(self.资源句柄服务)
        self._包指纹表: dict[str, str] = {}  # 包id -> 源码指纹（热接入变更检测基线）
        self._包轻量指纹表: dict[str, str] = {}  # 包id -> 轻量指纹（调用前漂移校验基线）
        self._包目录表: dict[str, Path] = {}  # 包id -> 包根目录（校验时定位用，免重新发现）

    def 资源状态(self, 句柄: int, *, 项目id: str = "", 所有者: str = "") -> dict | None:
        return self.资源句柄服务.状态(句柄, 项目id=项目id, 所有者=所有者)

    def 资源续租(self, 句柄: int, *, 租约秒: float = 300,
                 项目id: str = "", 所有者: str = "") -> dict:
        return self.资源句柄服务.续租(句柄, 租约秒=租约秒, 项目id=项目id, 所有者=所有者)

    def 资源关闭(self, 句柄: int, *, 项目id: str = "", 所有者: str = "") -> dict:
        return self.资源句柄服务.关闭(句柄, 项目id=项目id, 所有者=所有者)

    def 启用自动排空(self, 排空超时秒: float = 3.0) -> None:
        """启用自动有状态排空：调用前后自动计数，异常路径也减。"""
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        self.排空 = 排空管理器(排空超时秒=排空超时秒)

    def 注册排空终止器(self, 名称: str, 终止函数: Callable[[], Any]) -> None:
        """登记由后端核心统一触发的真实资源终止函数。"""
        if self.排空 is None:
            self.启用自动排空()
        self.排空.注册强制终止器(名称, 终止函数)

    @staticmethod
    def 默认系统根() -> str:
        return str(Path(__file__).resolve().parents[1])

    def 装配(self) -> 结果:
        """发现并装配系统内全部支持库与模块（装配模板缓存复用）。"""
        global _装配模板
        from 运行核心.加载器.生命周期管理.管理器 import 装配系统
        with _装配锁:
            if _装配模板 is None:
                # 首次：全量装配并把纯净注册表存为模板
                装配结果 = 装配系统(
                    self.系统根目录 / "支持库", self.系统根目录 / "模块库", self.注册表,
                    self.系统根目录 / "技能库",
                )
                if not 装配结果.成功:
                    return 结果.失败("装配失败", "; ".join(装配结果.问题列表), 来源="后端核心")
                _装配模板 = copy.deepcopy(self.注册表)
            else:
                # 后续：模板深拷贝，避免重复全量扫描（大幅降低测试/多实例开销）
                self.注册表 = copy.deepcopy(_装配模板)
                if self.注册表 is None:
                    return 结果.失败("装配失败", "装配模板缺失", 来源="后端核心")
            self._唯一调用服务 = 唯一能力调用服务(self.注册表)
            设置全局唯一服务(self._唯一调用服务)
        self.初始化包指纹表()  # 记录已装配包基线指纹（热接入变更检测依据）
        return 结果.成功结果(len(self.注册表.能力id列表))

    def 启动(self) -> 结果:
        """启动后端核心（装配 + 就绪）。"""
        self.停止标记 = False
        self.状态.状态 = "启动中"
        装配结果 = self.装配()
        if not 装配结果.成功:
            self.状态.状态 = "故障"
            return 装配结果
        self.状态.状态 = "运行中"
        self.状态.启动时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.状态.能力数 = len(self.注册表.能力id列表)
        # 正式环境（环境开关开启）注入指纹校验：被改动未重新热接入即报错。
        self.启用包指纹校验()
        return 结果.成功结果(f"后端核心已就绪，{self.状态.能力数} 个能力")

    def 注册能力(self, 能力id: str, 实现函数: Callable, *, 参数: list | None = None,
                 返回: str = "结果", 说明: str = "") -> 结果:
        try:
            self.注册表.注册(能力实现(
                能力id=能力id, 包id="后端核心", 实现函数=实现函数,
                参数=参数 or [], 返回=返回, 说明=说明,
            ))
        except ValueError as 错误:
            return 结果.失败("能力重复", str(错误), 来源="后端核心")
        return 结果.成功结果(能力id)

    # ═══════════════════════════════════════════════════════════════
    # 热接入：新增/变更包免重启直接投产（增量装配）
    # 只装载「未装配的新包 + 源码指纹变化的已装配包」，不动其余包
    # （已装配包的模块级运行态、句柄、线程池全部保留，不重启网关）。
    # ═══════════════════════════════════════════════════════════════
    def 计算包指纹(self, 声明) -> str:
        """计算包源码与契约指纹：内容变化即可被发现，不依赖文件时间精度。"""
        import hashlib
        try:
            包根 = Path(声明.来源路径).parent.resolve()
        except Exception:
            包根 = Path(getattr(声明, "来源路径", "") or "").parent.resolve()
        if not 包根.is_dir():
            return ""
        摘要 = hashlib.sha256()
        for 文件 in sorted(包根.rglob("*")):
            if not 文件.is_file() or "__pycache__" in 文件.parts:
                continue
            if 文件.name == "完整性摘要.json" or 文件.name.endswith(".pyc"):
                continue
            try:
                摘要.update(str(文件.relative_to(包根)).encode("utf-8"))
                摘要.update(b"\0")
                摘要.update(文件.read_bytes())
                摘要.update(b"\0")
            except OSError:
                continue
        return 摘要.hexdigest()

    def _目录轻量指纹(self, 包根: Path) -> str:
        """按 相对路径+大小+纳秒修改时间 聚合目录轻量指纹（只 stat 不读内容）。"""
        import hashlib
        if not 包根.is_dir():
            return ""
        摘要 = hashlib.sha256()
        for 文件 in sorted(包根.rglob("*")):
            if not 文件.is_file() or "__pycache__" in 文件.parts:
                continue
            if 文件.name == "完整性摘要.json" or 文件.name.endswith(".pyc"):
                continue
            try:
                状态 = 文件.stat()
            except OSError:
                continue
            摘要.update(str(文件.relative_to(包根)).encode("utf-8"))
            摘要.update(f"|{状态.st_size}|{状态.st_mtime_ns}".encode("utf-8"))
        return 摘要.hexdigest()

    def 计算包轻量指纹(self, 声明) -> str:
        """计算包轻量指纹（校验用，代价远低于内容摘要）。"""
        try:
            包根 = Path(声明.来源路径).parent.resolve()
        except Exception:
            包根 = Path(getattr(声明, "来源路径", "") or "").parent.resolve()
        return self._目录轻量指纹(包根)

    def 校验包指纹(self, 包id: str) -> tuple[bool, str]:
        """校验包当前指纹是否与注册时一致（调用前防静默漂移）。

        返回 (是否一致, 说明)：包目录缺失或文件被改动未重新热接入即不一致；
        未登记基线的包（如核心自身注册的能力）不阻断。
        """
        基线 = self._包轻量指纹表.get(包id)
        if 基线 is None:
            return True, ""
        包根 = self._包目录表.get(包id)
        if 包根 is None:
            return True, ""
        if not 包根.is_dir():
            return False, f"包 {包id} 目录缺失（制品或源码已被删除）"
        if self._目录轻量指纹(包根) != 基线:
            return False, f"包 {包id} 指纹已变化（被改动但未重新热接入/注册指纹）"
        return True, ""

    def 启用包指纹校验(self) -> bool:
        """按环境开关把指纹校验器注入唯一调用服务（正式环境开启）。"""
        开关 = str(os.environ.get("系统底座_指纹校验", "")).strip().lower()
        if 开关 not in ("1", "true", "yes", "是"):
            return False
        if self._唯一调用服务 is None:
            return False
        self._唯一调用服务.设置包指纹校验器(self.校验包指纹)
        return True

    def 初始化包指纹表(self) -> None:
        """首次全量装配成功后，为每个已装配包记录基线指纹（内容指纹 + 轻量指纹 + 目录）。"""
        from 运行核心.加载器.包发现.发现器 import 发现全部
        发现 = 发现全部(self.系统根目录 / "支持库", self.系统根目录 / "模块库",
                       self.系统根目录 / "技能库")
        if not 发现.成功:
            return
        self._包指纹表 = {}
        self._包轻量指纹表 = {}
        self._包目录表 = {}
        for 声明 in 发现.声明列表:
            if getattr(声明, "已废弃", False):
                continue
            self._包指纹表[声明.包id] = self.计算包指纹(声明)
            self._包轻量指纹表[声明.包id] = self.计算包轻量指纹(声明)
            try:
                self._包目录表[声明.包id] = Path(声明.来源路径).parent.resolve()
            except Exception:
                continue

    def 热接入(self) -> 结果:
        """热接入：发现新增/变更包并增量装配，免重启直接投产。

        规则：
        1. 重新发现全部支持库/模块，对比注册表找出 新增包 + 源码指纹变化的变更包；
        2. 只装载这批包（先支持库后模块，按包id排序），不重跑全量装配，
           不触发装配锁漂移，已装配包运行态/句柄全部保留；
        3. 变更包重载前先弹出 sys.modules 旧入口与实现模块，保证新代码生效；
        4. 成功后更新装配模板与装配状态锁，后续全量装配不会漂移冲突。
        """
        import sys
        from 运行核心.加载器.包发现.发现器 import 发现全部
        from 运行核心.加载器.包安装.支持库安装 import 安装支持库
        from 运行核心.加载器.包安装.模块安装 import 安装模块
        global _装配模板
        with _装配锁:
            if self.状态.状态 != "运行中":
                return 结果.失败("外部不可访问",
                                   f"后端核心未运行（状态 {self.状态.状态}）", 来源="后端核心")
            发现 = 发现全部(self.系统根目录 / "支持库", self.系统根目录 / "模块库",
                       self.系统根目录 / "技能库")
            if not 发现.成功:
                return 结果.失败("热接入失败", "; ".join(发现.问题列表), 来源="后端核心")
            声明列表 = 发现.声明列表
            if not 声明列表:
                return 结果.失败("热接入失败", "未发现任何支持库或模块", 来源="后端核心")
            # 已独立发现的支持库/模块包 id：这些包的能力由它们自己的声明登记，
            # 不再算到同前缀父包的“注册未声明”账上（见 _校验热接入包）。
            已发现包id集合 = {声明.包id for 声明 in 声明列表
                              if not getattr(声明, "已废弃", False)}

            已注册包id集合 = {实现.包id for 能力id in self.注册表.能力id列表
                              for 实现 in [self.注册表.获取(能力id)] if 实现 is not None}
            新增声明 = [声明 for 声明 in 声明列表
                       if 声明.包id not in 已注册包id集合
                       and not getattr(声明, "已废弃", False)]
            变更声明 = []
            for 声明 in 声明列表:
                if getattr(声明, "已废弃", False) or 声明.包id not in 已注册包id集合:
                    continue
                if self.计算包指纹(声明) != self._包指纹表.get(声明.包id):
                    变更声明.append(声明)

            # ── 卸载目标：已注册但不再被发现 / 已标记废弃 的包 ──
            # 提前返回前必须先算出卸载集合，否则整包删除永远不触发。
            活跃包id集合 = {声明.包id for 声明 in 声明列表
                           if not getattr(声明, "已废弃", False)}
            卸载包id集合 = {
                包id for 包id in 已注册包id集合
                if 包id != "后端核心" and 包id not in 活跃包id集合
            }

            if not 新增声明 and not 变更声明 and not 卸载包id集合:
                return 结果.成功结果({"新增包": 0, "变更包": 0,
                                        "卸载包": 0, "成功包": [], "失败包": [],
                                        "已注册能力数": len(self.注册表.能力id列表)})

            def 排序键(声明):
                return (0 if 声明.类型 == "支持库" else 1, 声明.包id)
            待处理 = sorted(新增声明 + 变更声明, key=排序键)

            成功包表: list[str] = []
            失败表: list[str] = []
            # ── 卸载语义执行：移除能力、弹出模块、删除指纹 ──
            for 包id in sorted(卸载包id集合):
                try:
                    for 能力id in list(self.注册表.能力id列表):
                        旧实现 = self.注册表.获取(能力id)
                        if 旧实现 is not None and 旧实现.包id == 包id:
                            self.注册表.移除(能力id, 包id=包id)
                    模块键前缀 = (f"支持库运行时_{包id.replace('.', '_')}",
                                 f"模块运行时_{包id.replace('.', '_')}",
                                 包id + ".")
                    for 键 in [k for k in list(sys.modules)
                               if k == 模块键前缀[0] or k == 模块键前缀[1]
                               or k.startswith(模块键前缀[2])]:
                        sys.modules.pop(键, None)
                    self._包指纹表.pop(包id, None)
                    self._包轻量指纹表.pop(包id, None)
                    self._包目录表.pop(包id, None)
                    成功包表.append(f"{包id}（卸载）")
                except Exception as 错误:
                    失败表.append(f"{包id}（卸载）: {错误}")

            for 声明 in 待处理:
                try:
                    # 在临时注册表装配，避免新入口失败时破坏线上旧能力。
                    临时注册表 = 能力注册表()
                    for 能力id in self.注册表.能力id列表:
                        旧实现 = self.注册表.获取(能力id)
                        if 旧实现 is not None and 旧实现.包id != 声明.包id:
                            临时注册表.注册(旧实现)

                    # 弹出入口及包目录内实现模块，确保不会复用旧 Python 模块。
                    包根 = Path(声明.来源路径).parent.resolve()
                    模块键前缀 = (f"支持库运行时_{声明.包id.replace('.', '_')}",
                                 f"模块运行时_{声明.包id.replace('.', '_')}",
                                 声明.包id + ".")
                    for 键, 模块对象 in list(sys.modules.items()):
                        文件路径 = getattr(模块对象, "__file__", "") or ""
                        属于包 = False
                        try:
                            属于包 = bool(文件路径) and Path(文件路径).resolve().is_relative_to(包根)
                        except (OSError, ValueError):
                            pass
                        if (键 == 模块键前缀[0] or 键 == 模块键前缀[1]
                                or 键.startswith(模块键前缀[2]) or 属于包):
                            sys.modules.pop(键, None)

                    # 清除包目录下全部字节码缓存：源文件内容变化但 mtime 秒级/size
                    # 相同（如仅版本串变化）时，Python 会误用旧 .pyc，导致重载
                    # 后仍执行旧实现。重载必须强制重新编译。
                    for 缓存目录 in list(包根.rglob("__pycache__")):
                        shutil.rmtree(缓存目录, ignore_errors=True)

                    if 声明.类型 == "支持库":
                        安装支持库(声明, 临时注册表)
                    else:
                        安装模块(声明, 临时注册表)

                    # 一致性门禁（与全量装配同口径）：声明能力必须与入口注册、
                    # 参数契约三方对齐；依赖能力必须可解析。任一不一致即该包失败，
                    # 不允许“注册了但没登记”的半齐状态进入运行态。
                    校验问题 = self._校验热接入包(声明, 临时注册表, 已发现包id集合)
                    if 校验问题:
                        raise ValueError("；".join(校验问题))

                    # 临时注册成功后，在短临界区一次性替换该包能力。
                    with self.请求锁:
                        for 能力id in list(self.注册表.能力id列表):
                            旧实现 = self.注册表.获取(能力id)
                            if 旧实现 is not None and 旧实现.包id == 声明.包id:
                                self.注册表.移除(能力id, 包id=声明.包id)
                        for 能力id in 临时注册表.能力id列表:
                            新实现 = 临时注册表.获取(能力id)
                            if 新实现 is not None and 新实现.包id == 声明.包id:
                                self.注册表.注册(新实现)
                    self._包指纹表[声明.包id] = self.计算包指纹(声明)
                    self._包轻量指纹表[声明.包id] = self.计算包轻量指纹(声明)
                    # 包目录表是后续路径解析的依据：算不出来必须让外层按"包失败"上报
                    # （2026-09-15 评审：原先在此静默忽略，会让该包缺少目录映射却报成功）
                    self._包目录表[声明.包id] = Path(声明.来源路径).parent.resolve()
                    成功包表.append(f"{声明.包id}（{'新增' if 声明 in 新增声明 else '变更'}）")
                except Exception as 错误:
                    失败表.append(f"{声明.包id}: {错误}")

            # 更新装配模板，保证后续 装配() 不会用旧模板覆盖新能力
            _装配模板 = copy.deepcopy(self.注册表)
            # 重建装配状态锁：使后续全量装配与热接入后状态一致（尽力而为，失败不阻断）
            try:
                from 运行核心.加载器.依赖解析.装配锁 import 构建装配锁, 记录装配状态
                from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者
                from 运行核心.加载器.依赖解析.解析器 import 解析依赖
                活跃声明 = [声明 for 声明 in 声明列表 if not getattr(声明, "已废弃", False)]
                提供者表 = 选择全部提供者(活跃声明)
                能力提供者 = {能力id: (选择.提供包id, 选择.提供版本)
                              for 能力id, 选择 in 提供者表.items() if 选择.成功}
                解析 = 解析依赖(活跃声明, 能力提供者)
                if 解析.成功:
                    新锁 = 构建装配锁(活跃声明, 提供者表, 解析.顺序列表)
                    记录装配状态(self.注册表, 新锁)
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
                记录忽略('后端核心.热接入后重建装配锁', 错误)

            self.状态.能力数 = len(self.注册表.能力id列表)
            # 指纹基线已随本次热接入刷新，清掉校验缓存避免沿用旧判定。
            if self._唯一调用服务 is not None:
                self._唯一调用服务.清空包指纹缓存()
            # 失败必须失败：任一包装配/卸载失败，不得用成功信封掩盖（正式环境直接报错）。
            if 失败表:
                return 结果.失败(
                    "热接入失败",
                    "部分包装配或卸载失败: " + "; ".join(失败表),
                    来源="后端核心",
                )
            return 结果.成功结果({
                "新增包": len(新增声明), "变更包": len(变更声明),
                "卸载包": len(卸载包id集合),
                "成功包": 成功包表, "失败包": 失败表,
                "已注册能力数": self.状态.能力数,
            })

    def _校验热接入包(self, 声明, 临时注册表, 已发现包id集合: set[str] | None = None) -> list[str]:
        """热接入单包一致性门禁：声明 / 入口注册 / 参数契约 三方对齐 + 依赖可解析。

        注册能力按“包 id 前缀”归属，但只对**不独立成包**的子域生效：
        聚合壳目录下的纯分组子域由顶层声明覆盖（如 支持库.后端.系统核心支持库
        的声明含 系统核心支持库.工具执行.*）；已被发现器独立发现的子包
        （自身有 包声明.json，如 支持库.后端.代码解析支持库.语法索引）则由它
        自己的声明登记，父包不重复登记——否则父包必然报“注册未声明”，而把子包
        能力补进父声明又会与子包声明撞成“能力 id 重复”。
        """
        问题: list[str] = []
        独立包id集合 = set(已发现包id集合 or ())
        独立包id集合.discard(声明.包id)
        try:
            包根 = Path(声明.来源路径).parent.resolve()
        except Exception:
            包根 = Path(getattr(声明, "来源路径", "") or "").parent.resolve()
        声明能力集合 = {能力.能力id for 能力 in 声明.能力}
        注册能力集合: set[str] = set()
        for 能力id in 临时注册表.能力id列表:
            实现 = 临时注册表.获取(能力id)
            if 实现 is None:
                continue
            if 实现.包id == 声明.包id:
                注册能力集合.add(能力id)
            elif (实现.包id.startswith(声明.包id + ".")
                  and 实现.包id not in 独立包id集合):
                注册能力集合.add(能力id)
        缺失登记 = sorted(注册能力集合 - 声明能力集合)
        缺失实现 = sorted(声明能力集合 - 注册能力集合)
        if 缺失登记:
            问题.append(f"注册未声明: {缺失登记}")
        if 缺失实现:
            问题.append(f"声明未注册: {缺失实现}")
        契约路径 = 包根 / "能力契约" / "参数契约.json"
        if 契约路径.is_file():
            try:
                契约数据 = json.loads(契约路径.read_text(encoding="utf-8"))
                契约能力集合 = {项.get("能力id") for 项 in 契约数据.get("能力契约", [])}
            except (OSError, ValueError) as 错误:
                问题.append(f"参数契约不可读: {错误}")
            else:
                契约缺 = sorted(声明能力集合 - 契约能力集合)
                if 契约缺:
                    问题.append(f"参数契约缺声明能力: {契约缺}")
        elif 声明.类型 in ("基础模块", "功能模块"):
            问题.append("参数契约缺失: 缺少 能力契约/参数契约.json")
        缺失依赖 = []
        for 依赖 in 声明.依赖:
            依赖能力id = str(依赖.get("能力", ""))
            if 依赖能力id and 临时注册表.获取(依赖能力id) is None:
                缺失依赖.append(依赖能力id)
        if 缺失依赖:
            问题.append(f"依赖能力缺失: {缺失依赖}")
        return 问题

    def 设置权限(self, 能力id: str, 允许用户id列表: list[str]) -> None:
        self.权限表[能力id] = set(允许用户id列表)

    def 调用(self, 能力id: str, 参数: dict | None = None, *,
             上下文: 运行上下文 | None = None, 超时秒: float = 10.0) -> 结果:
        """按能力契约调用；权限/超时/取消/统一错误；自动排空计数。"""
        if self.状态.状态 != "运行中":
            return 结果.失败("外部不可访问", f"后端核心未运行（状态 {self.状态.状态}）", 来源="后端核心")
        上下文 = 上下文 or 运行上下文()
        排空活动 = False
        if self.排空 is not None:
            if not self.排空.开始请求():
                return 结果.失败("外部不可访问", "排空中，拒绝新请求", 来源="后端核心")
            排空活动 = True
        try:
            全局上下文管理器.进入(上下文)
            try:
                return self._调用内部(能力id, 参数, 上下文)
            finally:
                全局上下文管理器.退出()
        finally:
            if 排空活动:
                self.排空.结束请求()  # 异常路径也减计数

    def _调用内部(self, 能力id: str, 参数: dict | None,
                 上下文: 运行上下文) -> 结果:
        with self.请求锁:
            self.状态.请求总数 += 1
            self.状态.活动请求数 += 1
        try:
            允许用户 = self.权限表.get(能力id)
            if 允许用户 is not None and 上下文.用户id and 上下文.用户id not in 允许用户:
                返回结果 = 结果.失败("权限不足", f"用户 {上下文.用户id} 无权限调用 {能力id}", 来源="后端核心")
            else:
                if self._唯一调用服务 is None:
                    返回结果 = 结果.失败("能力调用器未装配", "后端核心未绑定唯一能力调用服务", 来源="后端核心")
                else:
                    返回结果 = self._唯一调用服务.调用能力(
                        能力id, 参数 or {}, 调用方="后端核心", 项目id=上下文.项目id,
                        句柄=上下文.句柄,
                    )
            if not 返回结果.成功:
                with self.请求锁:
                    self.状态.失败请求数 += 1
            return 返回结果
        finally:
            with self.请求锁:
                self.状态.活动请求数 = max(0, self.状态.活动请求数 - 1)

    def 健康检查(self) -> 结果:
        if self.状态.状态 == "运行中":
            return 结果.成功结果({"状态": "健康", "能力数": self.状态.能力数})
        return 结果.失败("外部不可访问", f"后端核心状态: {self.状态.状态}", 来源="后端核心")

    def 能力搜索(self, *, 关键词: str = "", 限制: int = 20) -> list[dict]:
        """按关键词返回紧凑候选；完整契约只能经 能力详情 按需读取。"""
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        return [
            {"能力id": 能力id, "包id": self.注册表.获取(能力id).包id,
             "简介": self._紧凑说明(self.注册表.获取(能力id).说明 or "")}
            for 能力id in self.注册表.能力id列表
            if not 关键词 or 关键词 in 能力id or 关键词 in (self.注册表.获取(能力id).说明 or "")
        ][:限制]

    @staticmethod
    def _紧凑说明(说明: str, 上限: int = 60) -> str:
        """目录简介最多 60 字；去除换行和多余空白。"""
        文本 = " ".join(str(说明 or "").split())
        return 文本 if len(文本) <= 上限 else 文本[:上限 - 1] + "…"

    def _包目录路径(self, 包id: str) -> Path | None:
        """仅允许读取已注册包自己的公开声明目录。"""
        if not isinstance(包id, str) or not 包id:
            return None
        已注册包 = {
            self.注册表.获取(能力id).包id for 能力id in self.注册表.能力id列表
        }
        if 包id not in 已注册包:
            return None
        候选 = self.系统根目录.joinpath(*包id.split(".")).resolve()
        try:
            候选.relative_to(self.系统根目录.resolve())
        except ValueError:
            return None
        return 候选 if (候选 / "包声明.json").is_file() else None

    @staticmethod
    def _读取JSON(路径: Path) -> dict:
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return 数据 if isinstance(数据, dict) else {}

    def 能力目录(self, *, 关键词: str = "", 偏移: int = 0, 限制: int = 20) -> dict:
        """Skill 式第一层：分页返回包级树和紧凑简介，不返回命令参数。

        四个桶（支持库按领域二级分组 / 模块库 / 技能库 / 其他库）恒存在，
        当前页每包只落一个桶，故 包数 与各桶条目总数相等、分页走查不漏包。
        """
        if isinstance(偏移, bool) or not isinstance(偏移, int) or 偏移 < 0:
            偏移 = 0
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        包表: dict[str, dict] = {}
        for 能力id in self.注册表.能力id列表:
            实现 = self.注册表.获取(能力id)
            if 实现.包id in 包表:
                包表[实现.包id]["能力数"] += 1
                continue
            包目录 = self._包目录路径(实现.包id)
            声明 = self._读取JSON(包目录 / "包声明.json") if 包目录 else {}
            名称 = str(声明.get("名称") or 实现.包id.rsplit(".", 1)[-1])
            简介 = self._紧凑说明(str(声明.get("说明") or 实现.说明 or ""))
            包表[实现.包id] = {
                "包id": 实现.包id, "名称": 名称, "简介": 简介, "能力数": 1,
            }
        if 关键词:
            包表 = {
                包id: 条目 for 包id, 条目 in 包表.items()
                if 关键词 in 包id or 关键词 in 条目["名称"] or 关键词 in 条目["简介"]
            }
        包条目表 = [条目 for _, 条目 in sorted(包表.items())]
        总数 = len(包条目表)
        当前页 = 包条目表[偏移:偏移 + 限制]
        下一偏移 = 偏移 + len(当前页)
        支持库树: dict[str, list[dict]] = {}
        模块库列表: list[dict] = []
        技能库列表: list[dict] = []
        其他库列表: list[dict] = []
        # 分桶必须完备：当前页每一条只能落一个桶，否则 包数 虚高、下一偏移
        # 跨过一个永远取不到的包（技能库 前缀原就如此被静默丢掉，分页走查
        # 也永远走不到它）。未知前缀一律进「其他库」，保证收纳总数守恒。
        for 条目 in 当前页:
            包id = 条目["包id"]
            根库名 = 包id.split(".", 1)[0]
            if 根库名 == "支持库":
                分段 = 包id.split(".")
                领域 = 分段[1] if len(分段) > 2 else "其他"
                支持库树.setdefault(领域, []).append(条目)
            elif 根库名 == "模块库":
                模块库列表.append(条目)
            elif 根库名 == "技能库":
                技能库列表.append(条目)
            else:
                其他库列表.append(条目)
        return {
            "使用顺序": ["选择包", "查看包详情", "查看能力详情", "调用能力"],
            "支持库": [{"领域": 领域, "包": 包列表} for 领域, 包列表 in sorted(支持库树.items())],
            "模块库": 模块库列表,
            "技能库": 技能库列表,
            "其他库": 其他库列表,
            "包数": len(当前页),
            "总包数": 总数,
            "偏移": 偏移,
            "限制": 限制,
            "下一偏移": 下一偏移 if 下一偏移 < 总数 else None,
            "是否完成": 下一偏移 >= 总数,
        }

    def 包详情(self, 包id: str) -> dict | None:
        """Skill 式第二层：只返回该包的命令目录，不展开参数正文。"""
        包目录 = self._包目录路径(包id)
        if 包目录 is None:
            return None
        声明 = self._读取JSON(包目录 / "包声明.json")
        命令表 = []
        for 能力 in 声明.get("能力", []):
            if not isinstance(能力, dict) or not 能力.get("能力id"):
                continue
            命令表.append({
                "能力id": 能力["能力id"],
                "名称": 能力.get("名称") or str(能力["能力id"]).rsplit(".", 1)[-1],
                "简介": self._紧凑说明(str(能力.get("说明") or "")),
            })
        return {
            "包id": 包id, "名称": 声明.get("名称", ""),
            "简介": self._紧凑说明(str(声明.get("说明") or "")),
            "版本": 声明.get("版本", ""), "命令": 命令表,
            "下一步": "选中能力id后调用 能力详情；此处不返回参数正文",
        }

    def 能力详情(self, 能力id: str) -> dict | None:
        """Skill 式第三层：按需读取单个能力的完整权威契约和调用方式。"""
        实现 = self.注册表.获取(能力id)
        if 实现 is None:
            return None
        包目录 = self._包目录路径(实现.包id)
        if 包目录 is None:
            return None
        契约总表 = self._读取JSON(包目录 / "能力契约" / "参数契约.json")
        能力表 = 契约总表.get("能力契约", 契约总表.get("能力列表", []))
        正文 = next((项 for 项 in 能力表
                   if isinstance(项, dict) and 项.get("能力id") == 能力id), None)
        if 正文 is None:
            正文 = {
                "能力id": 能力id, "说明": 实现.说明,
                "参数": 实现.参数, "返回": {"类型": 实现.返回},
            }
        声明 = self._读取JSON(包目录 / "包声明.json")
        返回正文 = copy.deepcopy(正文)
        返回正文["包id"] = 实现.包id
        返回正文["包版本"] = 声明.get("版本", 实现.版本)
        返回正文["契约版本"] = 契约总表.get("契约版本", "")
        返回正文["依赖"] = 声明.get("依赖", [])
        返回正文["配置契约"] = self._读取JSON(包目录 / "配置契约" / "配置契约.json")
        返回正文["资源预算"] = self._读取JSON(包目录 / "资源预算.json")
        返回正文["调用方式"] = {
            "操作": "调用能力", "目标": 能力id,
            "参数": 正文.get("调用示例", {}).get("参数", 正文.get("调用示例", {})),
        }
        return 返回正文

    def 优雅关闭(self) -> 结果:
        """优雅关闭：等待活动请求归零后停止。"""
        if self.状态.状态 == "已停止":
            return 结果.成功结果("已停止（幂等）")
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("排空超时", 排空结果.诊断记录, 来源="后端核心")
        try:
            self.资源句柄服务.关闭服务()
        except Exception as 错误:
            self.状态.状态 = "故障"
            return 结果.失败(
                "资源释放失败", f"资源句柄服务关闭失败: {错误}", 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已优雅关闭")

    def 强制关闭(self) -> 结果:
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("资源未释放", 排空结果.诊断记录, 来源="后端核心")
        try:
            self.资源句柄服务.关闭服务()
        except Exception as 错误:
            self.状态.状态 = "故障"
            return 结果.失败(
                "资源释放失败", f"资源句柄服务关闭失败: {错误}", 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已强制关闭")

    def 状态快照(self) -> dict[str, Any]:
        return {
            "状态": self.状态.状态, "启动时间": self.状态.启动时间,
            "能力数": self.状态.能力数, "请求总数": self.状态.请求总数,
            "失败请求数": self.状态.失败请求数, "活动请求数": self.状态.活动请求数,
        }
