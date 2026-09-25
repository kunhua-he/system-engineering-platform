"""开工id 有效性校验：格式 + 登记事实，默认 fail-closed。

背景（B5 缺口①）：旧 `mcp_feedback` 直接用原始 `work_id` 写反馈账本
（`MCP工具箱/项目服务.py:659`），而同一个文件里的 `_有效开工id`
（`:292-304`）只让「当前开工id / 已登记子任务」通过 —— 于是任意 16 位十六进制
字符串都能提交反馈，**反馈门禁可被自证绕过**。

本模块把「有效开工id」判定收成一份可复用判定器（第 1 条 3 项「结果唯一即收口」：
判定口径只允许一份），供开发反馈服务强制调用：

- 判据与旧 `_有效开工id` 同口径：**运行库 `协作状态` 域已登记**（旧目录
  `工程缓存/协作状态/` 现场已不存在，无需旧文件回退；一次性搬迁由
  `MCP工具箱/协作状态.py` 负责，本模块只认运行库）。
- **fail-closed**：未装配登记源、登记源报错、运行库不可用 → 一律拒绝，
  绝不静默放行（旧实现正是「不判定即放行」才出缺口）。
- 依赖方向：本模块**只接受注入的查询调用**（经唯一调用入口的
  `数据库连接支持库.SQLite数据库.查询运行态`），不 import 支持库实现、
  不直连别人的数据库文件 —— 守住「平台控制面只依赖 平台控制面/* + 公共契约」
  的现状（第 2 条 1 项分层：控制面不下放到支持库，也不旁路别人的事实源）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from 公共契约.基础类型.逻辑类型 import 真, 假

#: 开工id 的**唯一格式口径**（2026-09-25 口径统一）：`开工-YYYYMMDD-HHMMSS-短随机`。
#:
#: 与本仓**发放侧**（`模块库/开工编排/实现/开工编排.py::开工ID句式`）与**提交强制点**
#: （`支持库/适配层/Git提供者/实现/提交回滚.py::提交开工ID句式`、
#: `开发工具/git钩子/commit-msg`）**同一句式**。
#:
#: **为什么改（2026-09-25 实测缺口，不是推测）**：改前本件钉的是「16 位裸十六进制」
#: （旧 `MCP工具箱/项目服务.py` 的 `work_id` 口径，该文件已删），而开工入口 `开工即占`
#: 发的是 `开工-20260925-161955-849f` 句式 ⇒ 两侧互不兼容、且**没有任何地方报出来**：
#: 真开工ID 进不了本门，本门放行的 ID 又进不了提交强制点。现全仓只留一套句式。
#: 说明面随之收口：`归一化` 仍小写化，故格式门的字符集**只收小写十六进制**
#: （消费侧扫提交消息原文、不做大小写归一 —— 若本门放大写，就会出现
#: 「本门放行、提交被拒」的新分叉）。
开工id模式 = re.compile(r"^开工-\d{8}-\d{6}-[0-9a-f]{4,}$")

错误_格式不合法 = "开工id无效"
错误_未登记 = "开工id未登记"
错误_校验不可用 = "开工id校验不可用"

默认协作状态域 = "协作状态"
默认查询限制 = 1000
默认查询超时秒 = 10.0
项目根 = Path(__file__).resolve().parents[2]


def 默认运行库路径(*, 系统根: Path | None = None) -> str:
    """底座运行库路径：环境变量 `系统库运行库` 优先，否则项目根下 `工程缓存/运行数据/底座运行.db`。

    与 `MCP工具箱/协作状态.py:43-49` 同口径（运行态唯一落点）；本模块**只读**这一个库，
    且只经 `数据库连接支持库.SQLite数据库.查询运行态` 读，不直连 sqlite。
    """
    环境 = os.environ.get("系统库运行库", "").strip()
    if 环境:
        return 环境
    根 = Path(系统根) if 系统根 else 项目根
    # 落点经唯一解析器（禁止裸拼 `工程缓存`）：制品进程里 `项目根` = 制品内 `平台客户端`，
    # 裸拼会把运行库建进不可变制品；源码态回落 `<项目根>/工程缓存/运行数据`（与旧值逐字一致）。
    from 公共契约.运行时.运行缓存 import 解析运行数据根

    return str(解析运行数据根(根) / "底座运行.db")


def 归一化(候选: Any) -> str:
    """归一化开工id：去空白 + 小写（运行库主键口径）。"""
    return str(候选 or "").strip().lower()


def 格式合法(候选: Any) -> bool:
    """格式校验：`开工-YYYYMMDD-HHMMSS-短随机`（短随机 = 4 位以上小写十六进制）。

    与发放侧（`开工编排.开工即占`）和提交强制点**同一句式**，见 `开工id模式` 的注释。
    """
    return bool(开工id模式.fullmatch(归一化(候选)))


def 默认查询运行态() -> Callable[[dict[str, Any]], Any] | None:
    """默认运行库查询入口：惰性装配，不可用返回 None（由调用方 fail-closed）。

    只走唯一调用入口（`获取能力调用器().调用能力(能力id, 参数)`），不 import
    支持库实现——与 `MCP工具箱/协作状态.py:68-80` 同一调用口径。
    """
    try:
        import 运行核心.能力调用.唯一能力调用  # noqa: F401 —— 注册惰性装配钩子
        from 公共契约.能力契约.调用器 import 获取能力调用器
    except Exception:  # noqa: BLE001 —— 运行库不可用必须 fail-closed，不向上抛
        return None

    def 查询(参数: dict[str, Any]) -> Any:
        try:
            return 获取能力调用器().调用能力(
                "数据库连接支持库.SQLite数据库.查询运行态", 参数)
        except Exception:  # noqa: BLE001 —— 同上，拒绝优先于抛出
            return None

    return 查询


class 协作状态登记源:
    """登记源：该开工id是否已在运行库 `协作状态` 域登记。

    `查询运行态` 为空时使用 `默认查询运行态()`；运行库不可用、返回空、
    载荷不可解析 → 判为「未登记」，并把原因写进 `最近说明`（诊断可见，不进返回值）。
    """

    def __init__(self, 查询运行态: Callable[[dict[str, Any]], Any] | None = None,
                 运行库路径: str = "") -> None:
        self.查询运行态 = 查询运行态
        self.运行库路径 = str(运行库路径 or "")
        self.最近说明 = ""

    def __call__(self, 候选: Any) -> bool:
        开工id = 归一化(候选)
        if not 格式合法(开工id):
            self.最近说明 = "格式不合法"
            return 假
        查询 = self.查询运行态 or 默认查询运行态()
        if 查询 is None:
            self.最近说明 = "运行库查询不可用（唯一调用入口未装配）"
            return 假
        参数: dict[str, Any] = {"域": 默认协作状态域, "限制": 默认查询限制,
                              "超时秒": 默认查询超时秒,
                              "数据库路径": self.运行库路径 or 默认运行库路径()}
        结果对象 = 查询(参数)
        if 结果对象 is None or not getattr(结果对象, "成功", 假):
            self.最近说明 = "运行库不可用或查询失败"
            return 假
        值 = getattr(结果对象, "值", None)
        行列表 = (值 or {}).get("行列表") if isinstance(值, dict) else None
        for 行 in 行列表 or []:
            if not isinstance(行, dict):
                continue
            载荷 = 行.get("载荷")
            记录: dict[str, Any] = {}
            if isinstance(载荷, str) and 载荷:
                try:
                    记录 = json.loads(载荷)
                except json.JSONDecodeError:
                    记录 = {}
            if not isinstance(记录, dict):
                记录 = {}
            键 = 归一化(记录.get("work_id") or 记录.get("开工id") or 行.get("id"))
            if 键 and 键 == 开工id:
                self.最近说明 = "运行库已登记"
                return 真
        self.最近说明 = "运行库内无该开工id"
        return 假


class 开工id校验器:
    """开工id 校验器：格式门 + 登记门（多个登记源取「任一已登记」）。

    参数：一个或多个登记源（可调用对象，入参归一化后的开工id，返回是否为已登记）。
    **不传登记源 = fail-closed**（拒绝一切，错误码 `开工id未登记`），
    这是刻意设计：调用方忘了装配判定器时，宁可拒绝，也不能退回「不判定即放行」。
    """

    def __init__(self, *登记源: Callable[[str], bool]) -> None:
        self.登记源 = tuple(源 for 源 in 登记源 if 源 is not None)
        self.最近说明 = ""

    def 校验(self, 候选: Any) -> tuple[bool, str, str]:
        """返回 (是否有效, 错误码, 错误说明)；有效时错误码与说明均为空串。"""
        开工id = 归一化(候选)
        if not 格式合法(开工id):
            self.最近说明 = f"开工id 格式不合法：{str(候选 or '')[:32]}"
            return 假, 错误_格式不合法, (
                "开工id 必须为 开工-YYYYMMDD-HHMMSS-短随机 句式"
                "（短随机为 4 位以上小写十六进制，如 开工-20260925-161955-849f）；"
                "不传该参数由 开工编排.开工即占 当场生成一个合规的")
        if not self.登记源:
            self.最近说明 = "未装配开工登记源（fail-closed）"
            return 假, 错误_未登记, "未装配开工登记源，按 fail-closed 拒绝"
        异常表: list[str] = []
        for 源 in self.登记源:
            try:
                if 源(开工id):
                    self.最近说明 = f"{type(源).__name__}：{getattr(源, '最近说明', '') or '已登记'}"
                    return 真, "", ""
            except Exception as 错误:  # noqa: BLE001 —— 登记源异常不得放行
                异常表.append(str(错误))
        if len(异常表) == len(self.登记源):
            self.最近说明 = "全部登记源异常：" + "; ".join(异常表)[:200]
            return 假, 错误_校验不可用, "开工id 校验源不可用"
        self.最近说明 = "所有登记源均判为未登记"
        return 假, 错误_未登记, "该开工id未在运行库登记"

    def __call__(self, 候选: Any) -> bool:
        return self.校验(候选)[0]


def 默认校验器(*, 查询运行态: Callable[[dict[str, Any]], Any] | None = None,
             运行库路径: str = "") -> 开工id校验器:
    """默认装配：格式门 + 运行库 `协作状态` 域登记门（与旧 `_有效开工id` 同判据）。"""
    return 开工id校验器(协作状态登记源(查询运行态, 运行库路径))
