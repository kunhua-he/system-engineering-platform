"""HTML验证应用编排：选择单/多实例、统一回收、证据和退出码。"""
from __future__ import annotations
import argparse
import json
import subprocess
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


def _解析制品目录(参数: argparse.Namespace) -> Path:
    """正式验证只接受制品目录或编译器写入的当前指针。"""
    制品路径 = str(getattr(参数, "制品", "") or "").strip()
    指针路径 = str(getattr(参数, "制品指针", "") or "").strip()
    if bool(制品路径) == bool(指针路径):
        raise ValueError("必须且只能提供 --制品 或 --制品指针")
    if not 指针路径:
        return Path(制品路径).resolve()
    指针 = Path(指针路径).resolve()
    if 指针.name != "当前.json" or not 指针.is_file():
        raise ValueError(f"稳定制品指针不存在或文件名不合法: {指针}")
    try:
        数据 = json.loads(指针.read_text(encoding="utf-8"))
        目录 = Path(str(数据["制品版本目录"])).resolve()
        指纹 = str(数据["当前制品指纹"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as 错误:
        raise ValueError(f"稳定制品指针不合法: {指针}") from 错误
    if not 指纹 or not 目录.name == 指纹:
        raise ValueError(f"稳定制品指针与制品目录不一致: {指针}")
    if not 目录.is_dir():
        raise ValueError(f"稳定制品版本目录不存在: {目录}")
    return 目录


def _激活稳定指针(目标路径: str | Path, 制品目录: Path) -> Path:
    """仅在验证成功后原子写入稳定版本指针。"""
    目标 = Path(目标路径).resolve()
    if 目标.name != "当前.json":
        raise ValueError("稳定指针文件名必须是 当前.json")
    清单路径 = Path(制品目录) / "编译清单.json"
    候选路径 = Path(制品目录) / "候选.json"
    try:
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
        制品指纹 = str(清单["制品指纹"])
        项目id = str(清单["项目id"])
        候选 = json.loads(候选路径.read_text(encoding="utf-8")) if 候选路径.is_file() else {}
        版本目录 = Path(str(候选.get("制品版本目录") or 制品目录)).resolve()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as 错误:
        raise ValueError(f"制品编译清单不合法: {清单路径}") from 错误
    if not 制品指纹 or 版本目录.name != 制品指纹 or not 版本目录.is_dir():
        raise ValueError("制品版本目录与编译清单指纹不一致")
    目标.parent.mkdir(parents=True, exist_ok=True)
    临时 = 目标.with_name(f".{目标.name}.{制品指纹}.tmp")
    临时.write_text(json.dumps({
        "项目id": 项目id, "当前制品指纹": 制品指纹,
        "制品版本目录": str(版本目录), "状态": "已验收",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    临时.replace(目标)
    return 目标


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
    try:
        制品目录 = _解析制品目录(参数)
    except (OSError, ValueError) as 错误:
        print(f"阻断: 制品入口不合法: {错误}")
        return 2
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
    验证通过 = 报告.场景总数 > 0 and 报告.失败数 == 0 and 报告.正向成功数 > 0
    if 验证通过 and getattr(参数, "激活到", ""):
        try:
            指针 = _激活稳定指针(参数.激活到, 制品目录)
            print(f"稳定版本已激活: {指针}")
        except (OSError, ValueError) as 错误:
            print(f"阻断: 稳定版本激活失败: {错误}")
            return 1
    return 0 if 验证通过 else 1
