"""多步骤场景顺序执行、资源键并发和 finally 清理。"""
from __future__ import annotations
import copy, json, tempfile, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from 开发工具.HTML验证.常量 import 默认超时秒, 默认并发
from 开发工具.HTML验证.单步场景 import 验证场景, 验证步骤
from 开发工具.HTML验证.多步场景 import 多步骤验证场景, 验证场景束
from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告
from 开发工具.HTML验证.制品事实 import _制品全文件摘要
from 开发工具.HTML验证.HTTP请求 import _发送请求
from 开发工具.HTML验证.返回判定 import _判定
from 开发工具.HTML验证.动态值 import _展开动态值
from 开发工具.HTML验证.端口池 import _场景资源键
from 开发工具.HTML验证.验证证据 import _校验制品前后绑定
def _执行场景束(制品目录: Path, 场景束: 验证场景束, 地址: str, *,
             超时秒: float = 默认超时秒, 并发: int = 默认并发) -> 验证报告:
    """按场景执行前置→目标并finally清理；每个能力步骤只经正式HTTP通道。"""
    制品目录 = Path(制品目录).resolve()
    报告 = 验证报告(制品路径=str(制品目录), 场景总数=len(场景束),
                目标能力数=len(场景束.目标能力全集), 步骤总数=场景束.步骤总数,
                目标能力全集=sorted(场景束.目标能力全集), 场景制品摘要=场景束.制品摘要)
    报告.制品摘要前 = _制品全文件摘要(制品目录)
    实际成功目标: set[str] = set()
    def 执行步骤(场景: 多步骤验证场景, 步骤: 验证步骤, 步骤类型: str,
                 临时根: Path, 返回表: dict[str, dict[str, Any]]) -> 验证结果:
        结果 = 验证结果(场景.场景id, 步骤.能力id, 步骤id=步骤.步骤id, 步骤类型=步骤类型)
        try:
            参数 = _展开动态值(
                步骤.参数, 制品目录=制品目录, 包目录=场景.包目录,
                临时目录=临时根, 步骤返回表=返回表,
            )
            请求场景 = 验证场景(
                场景id=f"{场景.场景id}.{步骤.步骤id}", 能力id=步骤.能力id,
                参数=参数, 预期状态码=步骤.预期状态码, 预期成功=步骤.预期成功,
                预期错误码=步骤.预期错误码, 预期包含=步骤.预期包含,
                预期值类型=步骤.预期值类型, 预期关键值=步骤.预期关键值,
                预期返回契约=步骤.预期返回契约, 预期值=步骤.预期值,
                校验完整值=步骤.校验完整值, 制品摘要=场景束.制品摘要,
                步骤id=步骤.步骤id,
            )
            状态码, 返回, 耗时 = _发送请求(地址, 请求场景, 超时秒)
            步骤上下文 = copy.deepcopy(返回)
            步骤上下文["参数"] = copy.deepcopy(参数)
            返回表[步骤.步骤id] = 步骤上下文
            结果.状态码, 结果.返回, 结果.耗时毫秒 = 状态码, 返回, 耗时
            结果.通过, 结果.失败原因, 结果.定位线索 = _判定(请求场景, 状态码, 返回)
        except BaseException as 错误:
            结果.失败原因 = f"步骤执行异常: {type(错误).__name__}: {错误}"
            结果.定位线索 = "场景执行器"
        return 结果

    def 执行场景(场景: 多步骤验证场景) -> tuple[list[验证结果], set[str], int, list[str]]:
        """每个场景独立临时根；场景内仍严格保持步骤顺序。"""
        临时对象 = tempfile.TemporaryDirectory(prefix="HTML黑盒场景_")
        临时根 = Path(临时对象.name).resolve()
        返回表: dict[str, dict[str, Any]] = {}
        结果表: list[验证结果] = []
        场景成功目标: set[str] = set()
        清理失败数 = 0
        try:
            前置通过 = True
            for 步骤 in 场景.前置步骤:
                结果 = 执行步骤(场景, 步骤, "前置", 临时根, 返回表)
                结果表.append(结果)
                if not 结果.通过:
                    前置通过 = False
                    break
            if 前置通过:
                for 步骤 in 场景.目标步骤:
                    结果 = 执行步骤(场景, 步骤, "目标", 临时根, 返回表)
                    结果表.append(结果)
                    if 结果.通过 and 步骤.预期成功:
                        场景成功目标.add(步骤.能力id)
        finally:
            for 步骤 in 场景.清理步骤:
                结果 = 执行步骤(场景, 步骤, "清理", 临时根, 返回表)
                结果表.append(结果)
                if not 结果.通过:
                    清理失败数 += 1
            临时对象.cleanup()
        残留 = [str(临时根)] if 临时根.exists() else []
        return 结果表, 场景成功目标, 清理失败数, 残留

    活跃 = 0
    峰值 = 0
    活跃锁 = threading.Lock()
    资源锁表: dict[str, threading.Lock] = {}
    资源锁表锁 = threading.Lock()

    def 取得资源锁(资源键表: tuple[str, ...]) -> list[threading.Lock]:
        锁表 = []
        with 资源锁表锁:
            for 资源键 in 资源键表:
                资源锁表.setdefault(资源键, threading.Lock())
                锁表.append(资源锁表[资源键])
        return 锁表

    def 运行场景(场景: 多步骤验证场景) -> tuple[list[验证结果], set[str], int, list[str]]:
        nonlocal 活跃, 峰值
        with 活跃锁:
            活跃 += 1
            峰值 = max(峰值, 活跃)
        资源锁表本地 = 取得资源锁(_场景资源键(场景))
        try:
            for 资源锁 in 资源锁表本地:
                资源锁.acquire()
            return 执行场景(场景)
        except BaseException as 错误:
            return ([验证结果(
                场景.场景id, "", False, 0,
                失败原因=f"场景执行异常: {type(错误).__name__}: {错误}", 定位线索="场景执行器",
            )], set(), 0, [])
        finally:
            for 资源锁 in reversed(资源锁表本地):
                资源锁.release()
            with 活跃锁:
                活跃 -= 1

    执行结果表: list[tuple[list[验证结果], set[str], int, list[str]]] = []
    with ThreadPoolExecutor(
        max_workers=min(并发, len(场景束.场景列表)), thread_name_prefix="HTML验证场景"
    ) as 执行器:
        任务表 = {执行器.submit(运行场景, 场景): 场景 for 场景 in 场景束.场景列表}
        for 任务 in as_completed(任务表):
            执行结果表.append(任务.result())

    for 结果表, 场景成功目标, 清理失败数, 残留 in 执行结果表:
        报告.结果列表.extend(结果表)
        实际成功目标.update(场景成功目标)
        报告.清理失败数 += 清理失败数
        报告.资源残留.extend(残留)
    报告.并发峰值 = 峰值
    报告.结果列表.sort(key=lambda 结果: (
        结果.场景id, {"前置": 0, "目标": 1, "清理": 2}.get(结果.步骤类型, 3), 结果.步骤id,
    ))
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
    报告.制品摘要后 = _制品全文件摘要(制品目录)
    _校验制品前后绑定(报告)
    return 报告
