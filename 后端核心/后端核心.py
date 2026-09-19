"""后端核心：通用运行宿主。

后端核心负责：支持库和模块发现、包版本解析、项目适配装配、能力注册、
能力调用、服务生命周期、后台任务、外部提供者管理、请求上下文、权限
检查、超时和取消、统一错误、运行事件、诊断关联、版本切换、停止和卸载。

后端核心不实现具体业务，只提供通用运行宿主。公开入口只能是能力契约
和统一结果。
（拆分后的成员分布见下；公开面与拆分前逐字一致）

**2026-09-19 拆分（对外零变化）**：宿主本体按职责簇拆出三个混入面，`后端核心`
仍以 MRO 原样继承全部成员名 —— 子类、调用方、`mock.patch` 全部无感：

| 落点 | 职责 |
| --- | --- |
| `后端核心_资源与排空面.py` | 受管资源三转发口 + 自动排空装配 + 终止器登记 |
| `后端核心_包指纹面.py` | 内容/轻量指纹、调用前漂移校验、热接入单包一致性门禁 |
| `后端核心_能力目录面.py` | Skill 式四层渐进披露（搜索/目录/包详情/能力详情） |

留在本文件的：模块级装配模板缓存（`_装配模板` / `_装配跳过包` / `_装配锁`）、
`后端状态`、`_归一超时秒`、以及装配 → 注册 → 热接入 → 调用 → 生命周期的装配主链。
`启动()` 是**平台装配入口**（环境自检装配冒烟项），装配顺序、能力注册逻辑、
模板缓存语义保持逐字不变。
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
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 公共契约.运行时.运行缓存 import 运行缓存环境变量, 解析运行缓存根
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文, 全局上下文管理器
from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
from 运行核心.资源协调 import 资源句柄服务, 设置受管状态服务
from 公共契约.诊断.忽略记录 import 记录忽略

_装配模板: 能力注册表 | None = None
# 进程级：首次全量装配产生的「单包级跳过告警」（与 装配模板 同源缓存，
# 保证后续实例复用模板时告警不丢——跳过包对调用方必须始终可见）。
_装配跳过包: list[str] = []
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


def _归一超时秒(超时秒: Any) -> tuple[bool, float | None]:
    """校验并归一「超时秒」。

    返回 `(是否合法, 时限)`：`None` 表示「调用方未给时限」（不限时，保持修复前
    的实际语义）；非法值（布尔/非数值/<=0）→ `(False, None)`，由调用方明确拒绝。
    """
    if 超时秒 is None:
        return 真, None
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)):
        return 假, None
    if float(超时秒) <= 0:
        return 假, None
    return 真, float(超时秒)

from 后端核心.后端核心_资源与排空面 import 资源与排空面
from 后端核心.后端核心_包指纹面 import 包指纹面
from 后端核心.后端核心_能力目录面 import 能力目录面


class 后端核心(资源与排空面, 包指纹面, 能力目录面):
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
        self.停止标记 = 假
        self.事件日志 = None
        self.排空 = None  # 自动排空管理器（启动时装配）
        self.资源句柄服务 = 资源句柄服务(self.运行缓存根目录 / "权威状态")
        设置受管状态服务(self.资源句柄服务)
        self._包指纹表: dict[str, str] = {}  # 包id -> 源码指纹（热接入变更检测基线）
        self._包轻量指纹表: dict[str, str] = {}  # 包id -> 轻量指纹（调用前漂移校验基线）
        self._包目录表: dict[str, Path] = {}  # 包id -> 包根目录（校验时定位用，免重新发现）
        self.装配跳过包: list[str] = []  # 单包级跳过告警（半成品包不阻断全平台）

    @staticmethod
    def 默认系统根() -> str:
        return str(Path(__file__).resolve().parents[1])

    def 装配(self) -> 结果:
        """发现并装配系统内全部支持库与模块（装配模板缓存复用）。

        单包级问题（实现缺失/契约不可读/依赖锁内容为空或非法）只跳过该包并
        告警：装配仍成功、其余包照常装配，告警写入 装配跳过包 并打到 stderr，
        不再让一条并行开发线的半成品包阻断全平台。
        """
        global _装配模板, _装配跳过包
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
                _装配跳过包 = list(装配结果.跳过包列表)
                _装配模板 = copy.deepcopy(self.注册表)
            else:
                # 后续：模板深拷贝，避免重复全量扫描（大幅降低测试/多实例开销）
                self.注册表 = copy.deepcopy(_装配模板)
                if self.注册表 is None:
                    return 结果.失败("装配失败", "装配模板缺失", 来源="后端核心")
            self.装配跳过包 = list(_装配跳过包)
            self._唯一调用服务 = 唯一能力调用服务(self.注册表)
            设置全局唯一服务(self._唯一调用服务)
        self.打印装配告警()
        self.初始化包指纹表()  # 记录已装配包基线指纹（热接入变更检测依据）
        return 结果.成功结果(len(self.注册表.能力id列表))

    def 打印装配告警(self) -> None:
        """把单包级跳过告警打到 stderr（网关/启动日志可见），不改装配成功语义。"""
        if not self.装配跳过包:
            return
        import sys
        print(f"[装配告警] 已跳过 {len(self.装配跳过包)} 个包（其余包照常装配）:", file=sys.stderr)
        for 告警 in self.装配跳过包:
            print(f"[装配告警]   {告警}", file=sys.stderr)

    def 启动(self) -> 结果:
        """启动后端核心（装配 + 就绪）。"""
        self.停止标记 = 假
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
                              if not getattr(声明, "已废弃", 假)}

            已注册包id集合 = {实现.包id for 能力id in self.注册表.能力id列表
                              for 实现 in [self.注册表.获取(能力id)] if 实现 is not None}
            新增声明 = [声明 for 声明 in 声明列表
                       if 声明.包id not in 已注册包id集合
                       and not getattr(声明, "已废弃", 假)]
            变更声明 = []
            for 声明 in 声明列表:
                if getattr(声明, "已废弃", 假) or 声明.包id not in 已注册包id集合:
                    continue
                if self.计算包指纹(声明) != self._包指纹表.get(声明.包id):
                    变更声明.append(声明)

            # ── 卸载目标：已注册但不再被发现 / 已标记废弃 的包 ──
            # 提前返回前必须先算出卸载集合，否则整包删除永远不触发。
            活跃包id集合 = {声明.包id for 声明 in 声明列表
                           if not getattr(声明, "已废弃", 假)}
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
                        属于包 = 假
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
                活跃声明 = [声明 for 声明 in 声明列表 if not getattr(声明, "已废弃", 假)]
                提供者表 = 选择全部提供者(活跃声明)
                能力提供者 = {能力id: (选择.提供包id, 选择.提供版本)
                              for 能力id, 选择 in 提供者表.items() if 选择.成功}
                解析 = 解析依赖(活跃声明, 能力提供者)
                if 解析.成功:
                    新锁 = 构建装配锁(活跃声明, 提供者表, 解析.顺序列表)
                    记录装配状态(self.注册表, 新锁)
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
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

    def 设置权限(self, 能力id: str, 允许用户id列表: list[str]) -> None:
        self.权限表[能力id] = set(允许用户id列表)

    def 调用(self, 能力id: str, 参数: dict | None = None, *,
             上下文: 运行上下文 | None = None, 超时秒: float | None = None) -> 结果:
        """按能力契约调用；权限/超时/取消/统一错误；自动排空计数。

        **`超时秒` 是真实时限（P0 B-02 修复）**：本层不再「收下不用」，而是校验后
        透传给唯一能力调用服务，由它按真实时限执行（超时返回公开码「超时」/504，
        执行单元杀不掉时如实记账，不假装回收）。默认 None = 调用方未给时限，
        保持修复前的实际语义（HTTP 边界始终显式传入；此处若强加某个默认秒数，
        等于把该秒数强加给长耗时能力，是另一种失真）。非法值明确拒绝，不静默忽略。
        """
        合法, 时限 = _归一超时秒(超时秒)
        if not 合法:
            return 结果.失败(
                "参数不合法", f"超时秒必须是大于 0 的数值（收到 {超时秒!r}）",
                来源="后端核心")
        if self.状态.状态 != "运行中":
            return 结果.失败("外部不可访问", f"后端核心未运行（状态 {self.状态.状态}）", 来源="后端核心")
        上下文 = 上下文 or 运行上下文()
        排空活动 = 假
        if self.排空 is not None:
            if not self.排空.开始请求():
                return 结果.失败("外部不可访问", "排空中，拒绝新请求", 来源="后端核心")
            排空活动 = 真
        try:
            全局上下文管理器.进入(上下文)
            try:
                return self._调用内部(能力id, 参数, 上下文, 时限)
            finally:
                全局上下文管理器.退出()
        finally:
            if 排空活动:
                self.排空.结束请求()  # 异常路径也减计数

    def _调用内部(self, 能力id: str, 参数: dict | None,
                 上下文: 运行上下文, 超时秒: float | None = None) -> 结果:
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
                        句柄=上下文.句柄, 超时秒=超时秒,
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

    def 优雅关闭(self) -> 结果:
        """优雅关闭：等待活动请求归零后停止。"""
        if self.状态.状态 == "已停止":
            return 结果.成功结果("已停止（幂等）")
        self.停止标记 = 真
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
        self.停止标记 = 真
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
            "装配跳过包": list(self.装配跳过包),
        }
