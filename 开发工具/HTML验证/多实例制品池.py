"""多实例制品池启动、分片、执行与合并。"""
from __future__ import annotations
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 默认并发, 默认超时秒, 固定端口池, 固定端口
from 开发工具.HTML验证.多步场景 import 验证场景束
from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告
from 开发工具.HTML验证.制品事实 import _制品全文件摘要, _找启动器
from 开发工具.HTML验证.端口池 import _解析端口池, _分片场景
from 开发工具.HTML验证.制品进程 import _启动制品, _回收进程组
from 开发工具.HTML验证.单实例验证 import 验证全部
from 开发工具.HTML验证.验证证据 import _校验制品前后绑定
def _验证全部多实例(
    制品目录: Path,
    场景束: 验证场景束,
    *,
    并发: int = 默认并发,
    超时秒: float = 默认超时秒,
    端口池: str = 固定端口池,
    实例数: int = 1,
) -> tuple[验证报告, list[subprocess.Popen[Any]]]:
    """多实例制品池：一次启动 N 个制品进程，各自独立端口，场景分片后并行执行。"""
    if type(实例数) is not int or not 1 <= 实例数 <= 64:
        raise ValueError(f"实例数必须是 1 到 64 的整数")
    端口表 = _解析端口池(端口池)
    if len(端口表) < 实例数:
        raise ValueError(f"端口池 {端口池} 只有 {len(端口表)} 个端口，不足 {实例数} 个实例")
    分片表 = _分片场景(场景束, 实例数)
    报告 = 验证报告(制品路径=str(制品目录), 场景总数=len(场景束.场景列表))
    报告.制品摘要前 = _制品全文件摘要(制品目录)
    当前摘要 = 报告.制品摘要前["制品摘要"]
    if 场景束.制品摘要 != 当前摘要:
        报告.失败数 = 1
        报告.结果列表.append(验证结果(
            "场景.制品绑定", "", False, 0,
            失败原因=f"场景制品摘要未绑定当前制品: {场景束.制品摘要} != {当前摘要}",
            定位线索="制品绑定",
        ))
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        return 报告, []
    报告.场景制品摘要 = 当前摘要

    启动器 = _找启动器(制品目录)
    进程表: list[subprocess.Popen[Any]] = []
    地址表: list[str] = []
    try:
        # 多实例并行启动：实例间独立端口、零竞争，同时拉起避免串行启动叠加
        with ThreadPoolExecutor(
            max_workers=实例数, thread_name_prefix="HTML验证实例启动"
        ) as 启动执行器:
            启动任务表 = {}
            for 实例序号, 端口 in enumerate(端口表[:实例数]):
                启动任务表[启动执行器.submit(_启动制品, 启动器, 制品目录, 端口)] = 实例序号
            按序号表: list[tuple[int, subprocess.Popen[Any], int]] = []
            for 任务 in as_completed(启动任务表):
                实例序号 = 启动任务表[任务]
                进程, 实际端口, _ = 任务.result()
                进程表.append(进程)
                按序号表.append((实例序号, 进程, 实际端口))
            按序号表.sort()
            进程表.clear()
            for 实例序号, 进程, 实际端口 in 按序号表:
                进程表.append(进程)
                地址表.append(f"http://127.0.0.1:{实际端口}")
        分片报告表: list[验证报告] = []
        分片进程表: list[list[subprocess.Popen[Any]]] = []
        with ThreadPoolExecutor(
            max_workers=实例数, thread_name_prefix="HTML验证实例"
        ) as 执行器:
            任务表 = {}
            for 实例序号, (分片, 地址) in enumerate(zip(分片表, 地址表)):
                子目标能力全集 = {
                    步骤.能力id
                    for 场景 in 分片
                    for 步骤 in 场景.目标步骤
                    if 步骤.预期成功
                }
                子束 = 验证场景束(
                    场景列表=分片, 目标能力全集=子目标能力全集, 制品摘要=场景束.制品摘要,
                )
                任务表[执行器.submit(
                    验证全部, 制品目录, 子束, 并发=并发, 超时秒=超时秒,
                    端口=固定端口, 直连地址=地址, 进程接收=None,
                )] = 实例序号
            for 任务 in as_completed(任务表):
                分片报告, _, _ = 任务.result()
                分片报告表.append(分片报告)
        # 合并各实例报告
        实际成功目标: set[str] = set()
        峰值总和 = 0
        步骤总数 = 0
        for 分片报告 in 分片报告表:
            报告.结果列表.extend(分片报告.结果列表)
            报告.清理失败数 += 分片报告.清理失败数
            报告.资源残留.extend(分片报告.资源残留)
            实际成功目标.update(分片报告.实际成功目标能力全集)
            峰值总和 = max(峰值总和, 分片报告.并发峰值 or 0)
            步骤总数 += 分片报告.步骤总数 or 0
        报告.目标能力数 = len(场景束.目标能力全集)
        报告.步骤总数 = 步骤总数
        报告.并发峰值 = 峰值总和
        报告.资源残留数 = len(报告.资源残留)
        报告.实际成功目标能力全集 = sorted(实际成功目标)
        报告.正向目标能力全集 = sorted(场景束.目标能力全集)
        报告.通过数 = sum(结果.通过 for 结果 in 报告.结果列表)
        报告.失败数 = sum(not 结果.通过 for 结果 in 报告.结果列表)
        报告.正向成功数 = sum(
            结果.通过 and 结果.步骤类型 == "目标" for 结果 in 报告.结果列表
        )
        报告.负向校验数 = sum(
            结果.通过 and 结果.步骤类型 != "目标" for 结果 in 报告.结果列表
        )
        if 实际成功目标 != 场景束.目标能力全集:
            报告.结果列表.append(验证结果(
                "场景.实际覆盖", "", False,
                失败原因=f"实际成功目标能力全集不一致: 缺少={sorted(场景束.目标能力全集 - 实际成功目标)}",
                定位线索="覆盖对账",
            ))
            报告.失败数 += 1
        if 报告.资源残留数:
            报告.失败数 += 报告.资源残留数
        报告.结果列表.sort(key=lambda 结果: (
            结果.场景id, {"前置": 0, "目标": 1, "清理": 2}.get(结果.步骤类型, 3), 结果.步骤id,
        ))
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        _校验制品前后绑定(报告)
        return 报告, 进程表
    except BaseException:
        for 任务 in locals().get("启动任务表", {}):
            if not 任务.done():
                continue
            try:
                结果 = 任务.result()
                if isinstance(结果, tuple) and 结果 and 结果[0] not in 进程表:
                    进程表.append(结果[0])
            except BaseException:
                pass
        for 进程 in 进程表:
            try:
                _回收进程组(进程)
            except BaseException:
                pass
        raise
