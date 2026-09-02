"""验证证据与制品前后绑定。"""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from 开发工具.HTML验证.常量 import 场景文件名, 场景契约版本
from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告
from 开发工具.HTML验证.制品事实 import _制品全文件摘要, _工作区指纹
from 开发工具.HTML验证.场景加载 import _加载场景

系统根 = Path(__file__).resolve().parents[2]


def _校验制品前后绑定(报告: 验证报告) -> None:
    前 = 报告.制品摘要前.get("制品摘要")
    后 = 报告.制品摘要后.get("制品摘要")
    if (not 前 or not 后 or 前 != 后) and not any(
        结果.场景id == "制品.摘要绑定" for 结果 in 报告.结果列表
    ):
        报告.结果列表.append(验证结果(
            场景id="制品.摘要绑定",
            能力id="",
            通过=False,
            失败原因=f"制品全文件摘要前后不一致: {前} != {后}",
            定位线索="制品绑定",
        ))
        报告.失败数 += 1

def _证据根目录(制品目录: Path) -> Path:
    del 制品目录
    return 系统根 / "工程缓存" / "HTML验证证据"

def 保存证据(报告: 验证报告, 制品目录: Path, 输出目录: Path | None = None) -> Path:
    if not 报告.制品摘要前:
        报告.制品摘要前 = _制品全文件摘要(制品目录)
    if not 报告.制品摘要后:
        报告.制品摘要后 = _制品全文件摘要(制品目录)
    制品摘要 = 报告.制品摘要前.get("制品摘要", "未知制品")
    报告.时间 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    报告.证据绑定 = {
        "制品摘要": 制品摘要,
        "制品摘要前": 报告.制品摘要前.get("制品摘要", ""),
        "制品摘要后": 报告.制品摘要后.get("制品摘要", ""),
        "场景制品摘要": 报告.场景制品摘要,
        "工作区指纹": _工作区指纹(),
    }
    输出根 = (输出目录 or _证据根目录(制品目录)) / 制品摘要
    输出根.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        名称 = f"验证证据_{time.time_ns()}_{uuid.uuid4().hex[:12]}.json"
        路径 = 输出根 / 名称
        try:
            with 路径.open("x", encoding="utf-8") as 文件:
                json.dump(报告.转字典(), 文件, ensure_ascii=False, indent=2)
                文件.write("\n")
            return 路径
        except FileExistsError:
            continue
    raise FileExistsError("无法生成唯一证据文件名")

def 生成场景文件(制品目录: Path, 输出: Path | None = None) -> Path:
    场景束 = _加载场景(制品目录, None)
    摘要 = _制品全文件摘要(制品目录)["制品摘要"]
    输出路径 = 输出 or (_证据根目录(制品目录) / 摘要 / 场景文件名)
    输出路径.parent.mkdir(parents=True, exist_ok=True)
    数据 = {
        "来源": "包级验证场景引用",
        "契约版本": 场景契约版本,
        "制品摘要": 摘要,
        "验证场景": [场景.转字典(制品目录) for 场景 in 场景束.场景列表],
    }
    输出路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 输出路径
