"""制品与工作区只读事实。"""
from __future__ import annotations
import hashlib, json
from dataclasses import replace
from pathlib import Path
from typing import Any
from 开发工具.项目编译.项目编译器 import _来源指纹 as _编译来源指纹
from 开发工具.HTML验证.常量 import 验证版本
from 开发工具.HTML验证.单步场景 import 验证场景
def _工作区指纹(排除目录: Path | None = None) -> dict[str, str]:
    """复用项目编译控制面的唯一来源指纹实现。"""
    结果 = dict(_编译来源指纹(排除目录))
    结果["验证器版本"] = 验证版本
    结果["指纹实现"] = "开发工具.项目编译.项目编译器._来源指纹"
    return 结果

def _制品全文件摘要(制品目录: Path) -> dict[str, Any]:
    """摘要制品目录内全部普通文件，路径、类型和内容共同参与绑定。"""
    if not 制品目录.is_dir():
        raise ValueError(f"制品目录不存在: {制品目录}")
    文件清单: list[dict[str, Any]] = []
    汇总 = hashlib.sha256()
    for 文件 in sorted(制品目录.rglob("*"), key=lambda 路径: 路径.relative_to(制品目录).as_posix()):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(制品目录).as_posix()
        内容摘要 = hashlib.sha256(文件.read_bytes()).hexdigest()
        项 = {"路径": 相对, "字节数": 文件.stat().st_size, "sha256": 内容摘要}
        文件清单.append(项)
        汇总.update(相对.encode("utf-8"))
        汇总.update(b"\0")
        汇总.update(str(项["字节数"]).encode("ascii"))
        汇总.update(b"\0")
        汇总.update(内容摘要.encode("ascii"))
        汇总.update(b"\0")
    return {
        "摘要算法": "sha256-全文件-v1",
        "文件数": len(文件清单),
        "文件清单": 文件清单,
        "制品摘要": 汇总.hexdigest(),
    }

def _找启动器(制品目录: Path) -> Path:
    """正式制品只允许唯一启动入口，禁止在候选入口之间猜测。"""
    路径 = Path(制品目录) / "运行入口" / "启动.py"
    if not 路径.is_file():
        raise FileNotFoundError(f"制品缺少唯一启动器: {路径}")
    return 路径

def _读取JSON严格(路径: Path, 名称: str) -> Any:
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except FileNotFoundError as 错误:
        raise ValueError(f"缺少{名称}: {路径}") from 错误
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"{名称}JSON不合法: {路径}: {错误}") from 错误

def _扫描公开能力(制品目录: Path) -> tuple[set[str], list[Path]]:
    """只消费统一正式包索引，再严格对账 owner 包的声明与能力契约。"""
    from 开发工具.项目编译.正式包索引 import 构建索引

    制品目录 = Path(制品目录)
    直接能力根 = any((制品目录 / 名称).is_dir() for 名称 in ("模块库", "支持库"))
    平台客户端根 = 制品目录 / "平台客户端"
    嵌套能力根 = any((平台客户端根 / 名称).is_dir() for 名称 in ("模块库", "支持库"))
    if 直接能力根 and 嵌套能力根:
        raise ValueError("制品同时存在顶层与平台客户端嵌套能力根，拒绝双事实源")
    扫描根 = 平台客户端根 if 嵌套能力根 else 制品目录
    索引 = 构建索引(扫描根)
    if 索引["能力冲突"]:
        raise ValueError(f"公开能力 owner 冲突: {索引['能力冲突']}")
    能力所有者: dict[str, str] = dict(索引["能力所有者"])
    if not 能力所有者:
        raise ValueError("制品无任何公开能力契约")
    全部包 = {**索引["支持库"], **索引["模块库"]}
    owner包id表 = sorted(set(能力所有者.values()))
    包目录表: list[Path] = []
    契约全集: set[str] = set()
    for 包id in owner包id表:
        if 包id.startswith("冲突:") or 包id not in 全部包:
            raise ValueError(f"公开能力 owner 不合法: {包id}")
        包目录, 声明 = 全部包[包id]
        包目录表.append(包目录)
        声明路径 = 包目录 / "包声明.json"
        if not isinstance(声明, dict) or not isinstance(声明.get("能力"), list):
            raise ValueError(f"包声明契约不合法: {声明路径}")
        本包声明: set[str] = set()
        for 条目 in 声明["能力"]:
            if not isinstance(条目, dict) or not isinstance(条目.get("能力id"), str) or not 条目["能力id"].strip():
                raise ValueError(f"包声明缺能力id: {声明路径}")
            能力id = 条目["能力id"].strip()
            if 能力id in 本包声明:
                raise ValueError(f"包内重复公开能力id: {能力id}")
            本包声明.add(能力id)
        owner能力 = {能力id for 能力id, owner in 能力所有者.items() if owner == 包id}
        if 本包声明 != owner能力:
            raise ValueError(
                f"包声明与统一 owner 索引差集: {包目录}; "
                f"仅声明={sorted(本包声明 - owner能力)} 仅owner={sorted(owner能力 - 本包声明)}"
            )
        契约路径 = 包目录 / "能力契约" / "参数契约.json"
        契约 = _读取JSON严格(契约路径, "能力契约")
        if not isinstance(契约, dict) or not isinstance(契约.get("能力契约"), list):
            raise ValueError(f"能力契约结构不合法: {契约路径}")
        本包契约: set[str] = set()
        for 条目 in 契约["能力契约"]:
            if not isinstance(条目, dict) or not isinstance(条目.get("能力id"), str) or not 条目["能力id"].strip():
                raise ValueError(f"能力契约缺能力id: {契约路径}")
            能力id = 条目["能力id"].strip()
            if 能力id in 本包契约 or 能力id in 契约全集:
                raise ValueError(f"重复能力契约id: {能力id}")
            本包契约.add(能力id)
            契约全集.add(能力id)
        if 本包声明 != 本包契约:
            raise ValueError(
                f"包声明与能力契约差集: {包目录}; "
                f"仅声明={sorted(本包声明 - 本包契约)} 仅契约={sorted(本包契约 - 本包声明)}"
            )
    公开能力 = set(能力所有者)
    if 公开能力 != 契约全集:
        raise ValueError("统一正式包索引与能力契约全集不一致")
    return 公开能力, 包目录表

def _扫描能力契约(制品目录: Path) -> list[dict[str, Any]]:
    """兼容查询入口：返回严格校验后的公开能力 id。"""
    能力, _ = _扫描公开能力(制品目录)
    return [{"能力id": 能力id} for 能力id in sorted(能力)]

def _扫描制品能力(制品目录: Path) -> list[dict[str, Any]]:
    场景束 = _加载场景(制品目录, None)
    return [场景.转字典(制品目录) for 场景 in 场景束.场景列表]
