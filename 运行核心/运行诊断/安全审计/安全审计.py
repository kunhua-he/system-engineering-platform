"""安全审计：统一审计记录（JSONL 持久化）。

至少记录：谁调用/调用了什么/调用哪个版本/什么时候调用/是否成功/
为什么失败/是否被限流/是否触发权限拒绝/是否触发回滚/是否访问敏感配置。

**落点（2026-09-17 迁移）**：默认目录从 `临时目录/系统级支持库_审计` 改为平台
**运行数据**目录——经唯一解析器 `公共契约.运行时.运行缓存.解析运行数据根` 落盘
（源码态 = `<系统根>/工程缓存/运行数据/审计`，制品态 = 平台受管缓存），环境变量
`系统库审计目录` 仍是**最高优先覆盖**（既有覆盖点不破坏）。旧临时目录里的历史
文件**不读取、也不自动迁移**：临时目录语义本就是「重启即清」，自动搬迁会在装配/首次
调用路径上引入一次不可预期的 IO 与失败面；如需保留历史，把旧文件拷进新目录即可
（命令与取舍全文见 `运行核心/运行诊断/调用流水/说明/设计说明.md`）。

**写入口径（2026-09-17 实测后保持同步，不做异步改造）**：主调用热路径确实付一次
`open + fsync`，但实测单条写入 0.10ms、网关端到端 200 次平均差约 0.18ms / p95 差约
0.39ms，量级远小于一次能力调用本身；异步/批量队列会引入丢日志、退出丢数据、顺序
错乱与线程复杂度，与「稳定优先」相冲，故保留同步写。反向验证（必须保持成立）：
审计目录不可写时 `记录()` 只吞异常并写 stderr，**主调用的返回信封一个字段都不变**。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL文件上限字节, 默认JSONL读取上限字节, 默认JSONL读取上限记录,
    追加JSONL, 读取JSONL, 重写JSONL,
)
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 运行核心.运行诊断.运行事件.脱敏工具 import 脱敏值
from 公共契约.基础类型.逻辑类型 import 真, 假

# 运行数据目录下的审计子目录名（`<解析运行数据根>/审计`）。
审计子目录名 = "审计"
# 旧落点（迁移前）：临时目录下的审计目录名，仅用于文档与人工迁移对照。
旧临时目录名 = "系统级支持库_审计"


def 审计存储根(系统根目录: Path | None = None) -> Path:
    """审计落点根目录：默认走唯一解析器，落在平台运行数据目录下。

    `系统根目录` 缺省按本文件位置推导（`<系统根>/运行核心/运行诊断/安全审计/`），
    制品态由解析器识别并改道平台受管缓存，源码态 = `<系统根>/工程缓存/运行数据`。
    """
    根 = Path(系统根目录) if 系统根目录 is not None else Path(__file__).resolve().parents[3]
    return 解析运行数据根(根) / 审计子目录名


class 安全审计:
    """安全审计：追加式 JSONL 审计日志。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = Path(存储目录) if 存储目录 is not None else Path(安全审计.默认存储目录())
        try:
            self.存储目录.mkdir(parents=True, exist_ok=True)
        except OSError as 错误:
            # 留痕通道不得反噬调用方：目录建不出来（只读/权限）时只告警，
            # 不抛出——后续 `记录()` 落盘失败仍会逐条吞异常并写 stderr，
            # 主调用的返回信封一个字段都不变（反向验证见模块说明）。
            print(f"[安全审计] 审计目录不可用（仅告警，不阻断调用）: {self.存储目录}: {错误}",
                  file=sys.stderr)
        self.审计文件 = self.存储目录 / "安全审计.jsonl"
        self.锁 = threading.Lock()

    @staticmethod
    def 默认存储目录() -> str:
        """默认审计目录：环境变量 `系统库审计目录` 最高优先，其次平台运行数据目录。"""
        覆盖 = str(os.environ.get("系统库审计目录", "") or "").strip()
        if 覆盖:
            return 覆盖
        return str(审计存储根())

    def 记录(self, *, 操作: str, 用户id: str = "", 项目id: str = "",
             能力id: str = "", 版本: str = "", 请求id: str = "",
             成功: bool = 真, 失败原因: str = "", 被限流: bool = 假,
             权限拒绝: bool = 假, 触发回滚: bool = 假,
             访问敏感配置: bool = 假, 来源地址: str = "",
             模块id: str = "", 任务id: str = "", 会话id: str = "",
             契约版本: str = "", 提供者: str = "", 错误码: str = "",
             权限范围: list[str] | None = None, 耗时毫秒: float = 0.0,
             操作id: str = "") -> str:
        """写一条审计记录；返回审计id。"""
        审计id = uuid.uuid4().hex[:16]
        记录 = {
            "审计id": 审计id,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "操作": 操作, "用户id": 用户id, "项目id": 项目id,
            "模块id": 模块id, "能力id": 能力id, "版本": 版本,
            "契约版本": 契约版本, "提供者": 提供者,
            "请求id": 请求id, "任务id": 任务id, "会话id": 会话id,
            "操作id": 操作id, "来源地址": 来源地址,
            "权限范围": list(权限范围 or []), "耗时毫秒": round(耗时毫秒, 2),
            "成功": 成功, "错误码": 错误码, "失败原因": 失败原因,
            "被限流": 被限流, "权限拒绝": 权限拒绝,
            "触发回滚": 触发回滚, "访问敏感配置": 访问敏感配置,
        }
        记录 = 脱敏值(记录)
        try:
            with self.锁:
                追加JSONL(
                    self.审计文件, 记录,
                    最大文件字节数=默认JSONL文件上限字节,
                    强制落盘=真,
                )
        except OSError as 错误:
            # 审计落盘失败必须留痕：调用方（统一网关）丢弃返回值，
            # 静默返回 "" 会让安全审计链路无声断掉，事后无从发现。
            # 返回值语义不变，仍以空审计id 表示失败。
            print(f"[安全审计] 审计记录落盘失败: {错误}", file=sys.stderr)
            return ""
        return 审计id

    def 查询(self, *, 用户id: str = "", 能力id: str = "", 操作: str = "",
             成功: bool | None = None, 限流: bool | None = None,
             权限拒绝: bool | None = None, 回滚: bool | None = None,
             敏感配置: bool | None = None, 项目id: str = "",
             请求id: str = "", 任务id: str = "", 错误码: str = "",
             最大记录数: int = 默认JSONL读取上限记录) -> list[dict[str, Any]]:
        """按任意维度查询最近有界审计记录。"""
        结果列表 = []
        记录列表, _ = 读取JSONL(
            self.审计文件, 最大字节数=默认JSONL读取上限字节,
            最大记录数=默认JSONL读取上限记录,
        )
        for 记录 in 记录列表:
            if 用户id and 记录.get("用户id") != 用户id:
                continue
            if 能力id and 记录.get("能力id") != 能力id:
                continue
            if 操作 and 记录.get("操作") != 操作:
                continue
            if 项目id and 记录.get("项目id") != 项目id:
                continue
            if 请求id and 记录.get("请求id") != 请求id:
                continue
            if 任务id and 记录.get("任务id") != 任务id:
                continue
            if 错误码 and 记录.get("错误码") != 错误码:
                continue
            if 成功 is not None and 记录.get("成功") != 成功:
                continue
            if 限流 is not None and 记录.get("被限流") != 限流:
                continue
            if 权限拒绝 is not None and 记录.get("权限拒绝") != 权限拒绝:
                continue
            if 回滚 is not None and 记录.get("触发回滚") != 回滚:
                continue
            if 敏感配置 is not None and 记录.get("访问敏感配置") != 敏感配置:
                continue
            结果列表.append(记录)
        return 结果列表[-max(1, int(最大记录数)):]

    def 统计(self) -> dict[str, int]:
        全部 = self.查询()
        return {
            "总记录数": len(全部),
            "成功数": sum(1 for 记录 in 全部 if 记录["成功"]),
            "失败数": sum(1 for 记录 in 全部 if not 记录["成功"]),
            "被限流数": sum(1 for 记录 in 全部 if 记录["被限流"]),
            "权限拒绝数": sum(1 for 记录 in 全部 if 记录["权限拒绝"]),
            "触发回滚数": sum(1 for 记录 in 全部 if 记录["触发回滚"]),
            "敏感配置访问数": sum(1 for 记录 in 全部 if 记录["访问敏感配置"]),
        }

    def _可读记录数(self) -> int:
        """流式数出主审计文件里**可解析为字典**的记录条数（内存有界，无全量载入）。"""
        if not self.审计文件.is_file():
            return 0
        import json as _json
        条数 = 0
        with self.审计文件.open("r", encoding="utf-8", errors="replace") as 输入:
            for 行 in 输入:
                try:
                    if isinstance(_json.loads(行), dict):
                        条数 += 1
                except (UnicodeDecodeError, _json.JSONDecodeError):
                    continue
        return 条数

    def 裁剪(self, *, 保留天数: int = 0, 最大条数: int = 0) -> dict[str, Any]:
        """按保留策略裁剪主审计文件（流式有界重写，幂等）。

        口径：
        - `保留天数 > 0`：删除 `时间` 早于 `现在 - 保留天数` 的记录；
        - `最大条数 > 0`：只保留**最后** N 条（按文件追加顺序，即时间升序）；
        - 两者同时给 = 两条判据都要满足；都为 0 属参数问题，由能力边界层拦（本方法不猜）。
        - 裁剪面 = 主文件 `安全审计.jsonl`，与 `查询()` 的读取面**逐字一致**；
          轮转文件（`安全审计.jsonl.1/.2`）由追加侧的轮转自然淘汰，不在本方法范围内。

        重写委托 `公共契约.运行时.有界IO.重写JSONL`：逐行流式判定、临时文件 + 原子替换，
        不把大文件读进内存，中途失败原文件保持可读。返回清理前/保留/删除条数。
        """
        保留天数 = max(0, int(保留天数))
        最大条数 = max(0, int(最大条数))
        截止 = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() - 保留天数 * 86400)) if 保留天数 else ""
        with self.锁:
            清理前 = self._可读记录数()
            起点 = max(0, 清理前 - 最大条数) if 最大条数 else 0
            序号 = 0

            def 保留判定(记录: dict[str, Any]) -> bool:
                nonlocal 序号
                当前 = 序号
                序号 += 1
                if 当前 < 起点:
                    return 假
                return not (截止 and str(记录.get("时间", "")) < 截止)

            保留条数, 删除条数 = 重写JSONL(self.审计文件, 保留判定)
        return {
            "清理前条数": 清理前, "保留条数": 保留条数, "删除条数": 删除条数,
            "保留天数": 保留天数, "最大条数": 最大条数, "时间截止": 截止,
            "审计文件": str(self.审计文件),
        }
