"""包指纹面：源码/轻量指纹计算、调用前漂移校验、热接入单包一致性门禁（混入类）。

**为什么独立成文件**：这是「包身份与一致性」一簇 —— ① 内容指纹与轻量指纹的
计算（`计算包指纹` / `计算包轻量指纹` / `_目录轻量指纹`）；② 调用前防静默漂移的
校验器（`校验包指纹`）与按环境开关的注入（`启用包指纹校验`）；③ 首次全量装配后
的基线登记（`初始化包指纹表`）；④ 热接入的单包一致性门禁（`_校验热接入包`）。
四块共用同一套指纹表口径，与装配/调用主链解耦，可独立审阅。

**对外零变化（2026-09-19 拆分）**：本文件成员逐字取自冻结基线
`/tmp/拆分基线/后端核心.py`（812 行，sha256 前16 = 7fa787df454402a3，对应 HEAD
干净工作区），成员名、签名、默认值、函数体一个不改。

**宿主契约**（类注解，真源＝`后端核心.py` `后端核心.__init__`）：
`系统根目录` / `_唯一调用服务` / `_包指纹表` / `_包轻量指纹表` / `_包目录表`。

**导入方向**：本文件只被 `后端核心.py` 模块级导入，**不得反向导入** `后端核心.py`；
`_校验热接入包` 的调用方是宿主 `后端核心.热接入`（仍留在主文件）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.诊断.忽略记录 import 记录忽略


class 包指纹面:
    """包指纹与热接入一致性门禁簇。

    宿主契约（类注解，真源＝`后端核心.后端核心.__init__`）：
    `系统根目录` / `_唯一调用服务` / `_包指纹表` / `_包轻量指纹表` / `_包目录表`。
    """

    系统根目录: Path
    _唯一调用服务: Any
    _包指纹表: dict
    _包轻量指纹表: dict
    _包目录表: dict

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
            return 真, ""
        包根 = self._包目录表.get(包id)
        if 包根 is None:
            return 真, ""
        if not 包根.is_dir():
            return 假, f"包 {包id} 目录缺失（制品或源码已被删除）"
        if self._目录轻量指纹(包根) != 基线:
            return 假, f"包 {包id} 指纹已变化（被改动但未重新热接入/注册指纹）"
        return 真, ""

    def 启用包指纹校验(self) -> bool:
        """按环境开关把指纹校验器注入唯一调用服务（正式环境开启）。"""
        开关 = str(os.environ.get("系统底座_指纹校验", "")).strip().lower()
        if 开关 not in ("1", "true", "yes", "是"):
            return 假
        if self._唯一调用服务 is None:
            return 假
        self._唯一调用服务.设置包指纹校验器(self.校验包指纹)
        return 真

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
            if getattr(声明, "已废弃", 假):
                continue
            self._包指纹表[声明.包id] = self.计算包指纹(声明)
            self._包轻量指纹表[声明.包id] = self.计算包轻量指纹(声明)
            try:
                self._包目录表[声明.包id] = Path(声明.来源路径).parent.resolve()
            except Exception as 错误:
                # 允许忽略，但留痕（哲学第 3 条 2 项）：目录登记失败即该包目录缺项，
                # 会让「133 个包声明.json / 127 个声明」这类统计事实源静默变少。
                记录忽略('后端核心.初始化包指纹表.目录登记', 错误)
                continue

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

