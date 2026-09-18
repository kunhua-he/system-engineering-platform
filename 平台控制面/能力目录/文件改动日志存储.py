"""文件改动日志存储：单 JSON 的 append-only 事件流（唯一写入口）。

归属：文件改动流水是**多会话并发改同一文件**的审计面，属平台治理，落
`平台控制面.能力目录`。事实唯一落 `存储目录/文件改动日志.json`。

与同包 `文件租约存储.py` 的分工（第 2 条 1 项「分层与归属固定」）：
- **租约存储** = **状态**：每个路径一条当前记录，会被覆盖（重新认领会改写它）；
- **本条存储** = **事件**：只增不改的流水，一次动作一行，永不覆盖。

两者**不能合并**：状态要的是「此刻谁占着」，流水要的是「中途发生过什么」；
把事件塞进状态会让「当前记录」被历史撑爆，而状态的覆盖语义会吃掉历史。

并发机制**不自带**，一律走同包 `单文件互斥存储.py` 的唯一底座（类级实例缓存 +
RLock + 跨进程 flock + 锁内重读 + 唯一临时名 + fsync + `os.replace`）——与租约、
消费者契约两个存储共用同一套锁，本文件只留**流水自己的数据语义**。

流水上限：单路径保留最近 `单路径上限` 条（超出丢最旧的），因为 append-only 不设上限
会把存储撑爆；裁剪只丢日志行，不影响任何租约状态（流水不是锁）。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from 平台控制面.能力目录.单文件互斥存储 import 单文件互斥存储

存储文件名 = "文件改动日志.json"
锁文件名 = ".文件改动日志.lock"
# 单路径保留最近条数（超出丢最旧的）。留足排查一次并发撞车所需的视野，又不无限膨胀。
单路径上限 = 200
# 全局事件上限（多路径合计）；同样只影响日志，不影响锁。
全局上限 = 20000

# 事件类型（常量住这里，调用方引用常量、不写字面量）。
事件_登记 = "登记"
事件_上锁 = "上锁"
事件_解锁 = "解锁"
事件_留言 = "留言"
事件_过期回收 = "过期回收"


def 时间文本(时间戳: object) -> str:
    """时间戳 → 人读文本（本地时区 `%Y-%m-%d %H:%M:%S`，平台统一口径）。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(时间戳)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OSError):
        return ""


class 文件改动日志存储(单文件互斥存储):
    """文件改动流水的存储；键为 `路径`，值为**事件列表**（按时间升序）。"""

    存储标签 = "文件改动日志存储"
    存储文件名 = 存储文件名
    锁文件名 = 锁文件名
    最长等锁秒 = 单文件互斥存储.最长等锁秒
    等锁重试间隔秒 = 单文件互斥存储.等锁重试间隔秒
    实例上限 = 单文件互斥存储.实例上限

    def 读取(self) -> tuple[dict, str]:
        """读取流水；文件缺失视为空库；**损坏即报错**（不按空库继续，避免静默丢审计）。"""
        锁问题 = self.锁问题()
        if 锁问题:
            return {}, 锁问题
        if not self.存储文件.is_file():
            return {}, ""
        try:
            正文 = self.存储文件.read_text(encoding="utf-8")
        except OSError as 错误:
            return {}, f"文件改动日志不可读: {错误}"
        except UnicodeDecodeError as 错误:
            return {}, f"文件改动日志编码损坏: {错误}"
        import json

        try:
            数据 = json.loads(正文)
        except json.JSONDecodeError as 错误:
            return {}, f"文件改动日志损坏（拒绝按空库继续）: {错误}"
        return (数据 if isinstance(数据, dict) else {}), ""

    def 写入(self, 数据: dict) -> str:
        """临时文件（唯一名、fsync）+ `os.replace` 原子替换；返回问题说明（成功为空串）。"""
        import json

        锁问题 = self.锁问题()
        if 锁问题:
            return 锁问题
        正文 = json.dumps(数据, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            self.原子写文本(正文, 权限=0o644)
        except OSError as 错误:
            return f"文件改动日志原子替换失败: {错误}"
        return ""

    @staticmethod
    def 新事件(类型: str, 路径: str, 所有者: str, 任务: str,
               内容指纹: str = "", 已声明指纹: str = "", 详情: str = "",
               现在: float | None = None) -> dict:
        """构造一条流水事件（不可变；写进去就不再改）。"""
        时刻 = time.time() if 现在 is None else 现在
        return {
            "事件id": uuid.uuid4().hex[:16], "时刻": 时刻, "时间": 时间文本(时刻),
            "类型": 类型, "路径": 路径, "所有者": 所有者, "任务": 任务,
            "内容指纹": 内容指纹, "已声明指纹": 已声明指纹, "详情": 详情,
        }

    @staticmethod
    def 追加(快照: dict, 事件: dict) -> None:
        """把一条事件追加进快照（就地修改）；超上限即丢最旧的（只丢日志，不动锁）。"""
        路径 = str(事件.get("路径") or "")
        列表 = list(快照.get(路径) or [])
        列表.append(事件)
        if len(列表) > 单路径上限:
            列表 = 列表[-单路径上限:]
        快照[路径] = 列表
        总数 = sum(len(v) for v in 快照.values() if isinstance(v, list))
        if 总数 > 全局上限:
            # 丢全局最旧：按各路径首条的时刻排序，逐条丢，直到降到上限内。
            候选 = sorted(
                ((str(v[0].get("时刻") or 0), k) for k, v in 快照.items()
                 if isinstance(v, list) and v),
            )
            for _时刻, 键 in 候选:
                余量 = sum(len(v) for v in 快照.values() if isinstance(v, list)) - 全局上限
                if 余量 <= 0:
                    break
                列表 = list(快照.get(键) or [])
                if 列表:
                    快照[键] = 列表[1:] or []

    @staticmethod
    def 对外事件(事件: dict) -> dict:
        """对外读数（原样 + 人读时间已在构造时写入，不再派生）。"""
        return dict(事件)


__all__ = [
    "文件改动日志存储", "时间文本",
    "存储文件名", "单路径上限", "全局上限",
    "事件_登记", "事件_上锁", "事件_解锁", "事件_留言", "事件_过期回收",
]
