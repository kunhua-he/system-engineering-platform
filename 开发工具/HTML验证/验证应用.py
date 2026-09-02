"""HTML验证应用编排：选择单/多实例、统一回收、证据和退出码。"""
from __future__ import annotations
import argparse, subprocess
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 固定端口池
from 开发工具.HTML验证.多步场景 import 验证场景束
from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告
from 开发工具.HTML验证.制品事实 import _制品全文件摘要
from 开发工具.HTML验证.场景加载 import _加载场景
from 开发工具.HTML验证.单实例验证 import 验证全部
from 开发工具.HTML验证.多实例制品池 import _验证全部多实例
from 开发工具.HTML验证.制品进程 import _回收进程组
from 开发工具.HTML验证.验证证据 import _校验制品前后绑定, 保存证据, 生成场景文件
from 开发工具.HTML验证.验证服务 import 服务模式


def _记录流程异常(报告: 验证报告, 错误: BaseException) -> None:
    报告.失败数 += 1
    报告.结果列表.append(验证结果(
        场景id="验证流程",
        能力id="",
        通过=False,
        失败原因=f"验证流程异常: {type(错误).__name__}: {错误}",
        定位线索="验证器",
    ))

def 主函数(参数: argparse.Namespace) -> int:
    制品目录 = Path(参数.制品).resolve()
    if not 制品目录.is_dir():
        print(f"阻断: 制品目录不存在: {制品目录}")
        return 2
    if 参数.服务:
        try:
            return 服务模式(参数.直连地址 or f"http://127.0.0.1:{参数.端口}", 参数.服务, 制品目录)
        except BaseException as 错误:
            print(f"阻断: 服务模式启动失败: {错误}")
            return 2
    if 参数.只生成场景:
        try:
            路径 = 生成场景文件(制品目录, Path(参数.场景) if 参数.场景 else None)
            print(f"验证场景已生成: {路径}")
            return 0
        except BaseException as 错误:
            print(f"阻断: 场景生成失败: {错误}")
            return 2

    报告 = 验证报告(制品路径=str(制品目录))
    进程: subprocess.Popen[Any] | None = None
    进程表: list[subprocess.Popen[Any]] = []
    证据路径: Path | None = None
    def 接收进程(新进程: subprocess.Popen[Any]) -> None:
        nonlocal 进程
        进程 = 新进程

    try:
        报告.制品摘要前 = _制品全文件摘要(制品目录)
        场景列表 = _加载场景(制品目录, Path(参数.场景) if 参数.场景 else None)
        print(f"加载 {len(场景列表)} 个包级验证场景")
        if getattr(参数, "实例数", 1) > 1 and isinstance(场景列表, 验证场景束) and not 参数.直连地址:
            报告, 进程表 = _验证全部多实例(
                制品目录, 场景列表, 并发=参数.并发, 超时秒=参数.超时秒,
                端口池=getattr(参数, "端口池", 固定端口池), 实例数=getattr(参数, "实例数", 1),
            )
        else:
            报告, _, 进程 = 验证全部(
                制品目录, 场景列表, 并发=参数.并发, 超时秒=参数.超时秒,
                端口=参数.端口, 直连地址=参数.直连地址, 进程接收=接收进程,
            )
    except BaseException as 错误:
        _记录流程异常(报告, 错误)
    finally:
        try:
            全部进程 = 进程表 if 进程表 else ([进程] if 进程 else [])
            回收成功 = True
            进程组残留 = False
            for 单进程 in 全部进程:
                单回收 = _回收进程组(单进程)
                if not 单回收.get("已回收"):
                    回收成功 = False
                if 单回收.get("进程组残留"):
                    进程组残留 = True
            报告.资源回收 = {"已回收": 回收成功, "进程组残留": 进程组残留, "实例数": len(全部进程)}
            if not 回收成功:
                报告.失败数 += 1
                报告.结果列表.append(验证结果(
                    "资源回收", "", False, 0, 失败原因=f"进程组回收失败（{len(全部进程)} 实例）", 定位线索="资源回收",
                ))
        except BaseException as 错误:
            _记录流程异常(报告, 错误)
        try:
            报告.制品摘要后 = _制品全文件摘要(制品目录)
            _校验制品前后绑定(报告)
        except BaseException as 错误:
            _记录流程异常(报告, 错误)
        try:
            证据路径 = 保存证据(报告, 制品目录)
        except BaseException as 错误:
            报告.失败数 += 1
            print(f"阻断: 失败证据写入失败: {错误}")
    print(报告.汇总())
    if 证据路径:
        print(f"证据: {证据路径}")
    for 结果 in 报告.结果列表:
        if not 结果.通过:
            print(f"  ✗ [{结果.场景id}] {结果.失败原因}（{结果.定位线索}）")
    return 0 if 报告.场景总数 > 0 and 报告.失败数 == 0 and 报告.正向成功数 > 0 else 1
