"""单实例制品验证应用服务。"""
from __future__ import annotations
import subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 默认并发, 默认超时秒, 固定端口, 动态端口, 并发上限
from 开发工具.HTML验证.单步场景 import 验证场景
from 开发工具.HTML验证.多步场景 import 验证场景束
from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告
from 开发工具.HTML验证.制品事实 import _制品全文件摘要, _找启动器
from 开发工具.HTML验证.端口池 import _检查端口可用
from 开发工具.HTML验证.制品进程 import _启动制品
from 开发工具.HTML验证.HTTP请求 import _校验直连地址, _发送请求
from 开发工具.HTML验证.返回判定 import 验证单个
from 开发工具.HTML验证.场景执行器 import _执行场景束
from 开发工具.HTML验证.验证证据 import _校验制品前后绑定
def 验证全部(
    制品目录: Path,
    场景列表: list[验证场景] | 验证场景束,
    并发: int = 默认并发,
    超时秒: float = 默认超时秒,
    端口: int = 固定端口,
    自动打开: bool = False,
    直连地址: str = "",
    进程接收: Any = None,
) -> tuple[验证报告, int | None, Any]:
    del 自动打开
    if not 场景列表:
        raise ValueError("无任何有效验证场景")
    if type(并发) is not int or not 1 <= 并发 <= 并发上限:
        raise ValueError(f"并发必须是 1 到 {并发上限} 的整数")
    报告 = 验证报告(制品路径=str(制品目录), 场景总数=len(场景列表))
    报告.制品摘要前 = _制品全文件摘要(制品目录)
    当前摘要 = 报告.制品摘要前["制品摘要"]
    场景摘要集合 = ({场景列表.制品摘要} if isinstance(场景列表, 验证场景束)
                  else {场景.制品摘要 for 场景 in 场景列表})
    if 场景摘要集合 != {当前摘要}:
        报告.失败数 = 1
        报告.结果列表.append(验证结果(
            "场景.制品绑定", "", False, 0,
            失败原因=f"场景制品摘要未绑定当前制品: {sorted(场景摘要集合)} != {当前摘要}",
            定位线索="制品绑定",
        ))
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        return 报告, None, None
    报告.场景制品摘要 = 当前摘要
    进程: subprocess.Popen[Any] | None = None
    实际端口: int | None = None
    if 直连地址:
        地址 = _校验直连地址(直连地址)
    else:
        启动器 = _找启动器(制品目录)
        # 动态端口（0）由操作系统分配，先启动再从制品自报地址解析真实端口；
        # 句柄回收（进程组终止）即释放端口，无固定端口占用竞态。显式固定端口
        # 仅用于诊断，保留端口独占检查避免覆盖正在运行的服务。
        if 端口 == 动态端口:
            try:
                进程, 实际端口, _ = _启动制品(启动器, 制品目录, 动态端口)
                if 进程接收 is not None:
                    进程接收(进程)
            except BaseException as 错误:
                报告.失败数 = 1
                报告.结果列表.append(验证结果(
                    "制品启动", "", False, 0,
                    失败原因=f"制品启动异常: {type(错误).__name__}: {错误}", 定位线索="编译",
                ))
                报告.资源回收 = {"已回收": True, "原因": "启动助手已回收"}
                return 报告, None, None
        else:
            可用, 消息 = _检查端口可用(端口)
            if not 可用:
                报告.失败数 = 1
                报告.结果列表.append(验证结果("制品启动", "", False, 0, 失败原因=消息, 定位线索="端口"))
                return 报告, None, None
            try:
                进程, 实际端口, _ = _启动制品(启动器, 制品目录, 端口)
                if 进程接收 is not None:
                    进程接收(进程)
            except BaseException as 错误:
                报告.失败数 = 1
                报告.结果列表.append(验证结果(
                    "制品启动", "", False, 0,
                    失败原因=f"制品启动异常: {type(错误).__name__}: {错误}", 定位线索="编译",
                ))
                报告.资源回收 = {"已回收": True, "原因": "启动助手已回收"}
                return 报告, None, None
        地址 = f"http://127.0.0.1:{实际端口}"
    健康 = 验证场景(
        场景id="制品.健康", 能力id="制品.健康", 方法="GET", 路径="/",
        预期状态码=200, 预期成功=True, 预期值类型="字典型",
    )
    状态码, _, 耗时 = _发送请求(地址, 健康, 超时秒)
    if 状态码 != 200:
        报告.失败数 = 1
        报告.结果列表.append(验证结果(
            "制品.健康", "", False, 状态码, 耗时毫秒=耗时,
            失败原因=f"制品健康检查状态码 {状态码} != 200", 定位线索="编译",
        ))
        if 直连地址:
            报告.制品摘要后 = _制品全文件摘要(制品目录)
            _校验制品前后绑定(报告)
        return 报告, 实际端口, 进程

    if isinstance(场景列表, 验证场景束):
        场景报告 = _执行场景束(
            制品目录, 场景列表, 地址, 超时秒=超时秒, 并发=并发)
        if 直连地址:
            场景报告.资源回收 = {"已回收": True, "模式": "直连"}
        return 场景报告, 实际端口, 进程

    活跃 = 0
    峰值 = 0
    锁 = threading.Lock()

    def 运行(场景: 验证场景) -> 验证结果:
        nonlocal 活跃, 峰值
        with 锁:
            活跃 += 1
            峰值 = max(峰值, 活跃)
        try:
            return 验证单个(地址, 场景, 超时秒)
        except BaseException as 错误:
            return 验证结果(
                场景.场景id, 场景.能力id, False, 0,
                失败原因=f"验证任务异常: {type(错误).__name__}: {错误}", 定位线索="验证器",
            )
        finally:
            with 锁:
                活跃 -= 1

    结果表: list[验证结果] = []
    with ThreadPoolExecutor(max_workers=min(并发, len(场景列表)), thread_name_prefix="HTML验证") as 执行器:
        任务表 = {执行器.submit(运行, 场景): 场景 for 场景 in 场景列表}
        for 任务 in as_completed(任务表):
            场景 = 任务表[任务]
            try:
                结果表.append(任务.result())
            except BaseException as 错误:
                结果表.append(验证结果(
                    场景.场景id, 场景.能力id, False, 0,
                    失败原因=f"验证任务异常: {type(错误).__name__}: {错误}", 定位线索="验证器",
                ))
    结果表.sort(key=lambda 结果: 结果.场景id)
    报告.结果列表.extend(结果表)
    报告.通过数 = sum(结果.通过 for 结果 in 结果表)
    报告.失败数 += len(结果表) - 报告.通过数
    报告.正向成功数 = sum(结果.通过 and 场景.预期成功 for 结果 in 结果表 for 场景 in 场景列表 if 场景.场景id == 结果.场景id)
    报告.负向校验数 = sum(结果.通过 and not 场景.预期成功 for 结果 in 结果表 for 场景 in 场景列表 if 场景.场景id == 结果.场景id)
    报告.并发峰值 = 峰值
    if 直连地址:
        报告.资源回收 = {"已回收": True, "模式": "直连"}
        报告.制品摘要后 = _制品全文件摘要(制品目录)
        _校验制品前后绑定(报告)
    return 报告, 实际端口, 进程
