"""公共底座：结论常量、外部命令表、自检项数据类、工程根与调用辅助。

为什么单独一层：下面每个自检单元都要用 `自检项` 与三个结论常量；辅助（工程根定位、
独立进程组参数、非法入参喂入、文本截断、自检项执行兜底）也都被多于一个单元引用。
放在这里保证依赖方向单向（各单元 → 基础，基础不 import 任何单元）。"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


结论_通过 = "通过"


结论_警告 = "警告"


结论_不支持 = "不支持"


进度前缀 = "[环境自检]"


期望Python主次版本 = (3, 14)


#: 外部命令表：(候选命令名, 对应能力/提供者)。候选多于一个时"命中任一即算有"。
外部命令表: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ffmpeg",), "支持库.适配层.FFmpeg提供者（音视频转码/抽帧）"),
    (("ffprobe",), "支持库.适配层.FFmpeg提供者（媒体信息探测）"),
    (("tesseract",), "支持库.适配层.Tesseract提供者（OCR）"),
    (("soffice", "libreoffice"), "支持库.适配层.LibreOffice提供者（Office 文档转换）"),
    (("textutil",), "支持库.适配层.textutil提供者（文档转换；仅 macOS 自带）"),
    (("git",), "支持库.适配层.Git提供者"),
    (("ps",), "平台控制面/提供者/进程组管理（进程枚举）"),
    (("pgrep",), "平台控制面/提供者/进程组管理（按名查进程）"),
    # 2026-09-21 补（#98）：以下四类外部应用此前**不在表里**，于是「本机哪些能力不可用」
    # 在自检输出里看不到 —— 与表内八项同性质（pip 装不出来、缺了只影响对应提供者），
    # 故按同一口径补入；结论仍是【警告】不阻断退出码。
    (("security",), "支持库.适配层.密钥提供者（macOS 钥匙串 CLI；仅 macOS 自带）"),
    (("node",), "支持库.适配层.代码地图提供者（codegraph CLI 的运行时）"),
    (("codegraph",), "支持库.适配层.代码地图提供者（代码地图建索引/查状态）"),
    (("browser-use",), "支持库.适配层.浏览器自动化提供者（浏览器自动化；经 uvx 运行）"),
)


@dataclass
class 自检项:
    """一个自检项的结论。

    `为什么` 与 `影响` 是硬要求：自检项不允许做成「只是打印一行」，每一项都必须能回答
    「为什么需要它」和「缺了会怎样」。
    """

    序号: str
    名称: str
    结论: str
    说明: str
    为什么: str = ""
    影响: str = ""
    详情: dict[str, Any] = field(default_factory=dict)

    def 是失败(self) -> bool:
        return self.结论 == 结论_不支持

    def 转字典(self) -> dict[str, Any]:
        return {
            "序号": self.序号, "名称": self.名称, "结论": self.结论,
            "说明": self.说明, "为什么": self.为什么, "影响": self.影响,
            "详情": self.详情,
        }


def 系统根() -> Path:
    """向上定位工程根（同时含 支持库 与 开发工具 的祖先）。"""
    for 祖先 in Path(__file__).resolve().parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "开发工具").is_dir():
            return 祖先
    raise RuntimeError("无法定位工程根（缺少 支持库／开发工具 双目录）")


def _准备导入路径() -> Path:
    """把工程根放进 sys.path：`python3.14 开发工具/环境自检.py` 从别处跑也要能导入仓库包。"""
    根 = 系统根()
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    return 根


def _进程组启动参数() -> dict[str, Any]:
    """`subprocess.Popen(..., **` 展开用的独立进程组参数（唯一取值来源：平台适配）。

    单独抽一层是为了让静态检查器不逐个关键字报错，并且把「本机用哪种独立进程组语义」
    收成一个可读的调用点——取值一律走 公共契约.运行时.平台适配.子进程组启动标志()，
    自检只读不改。
    """
    from 公共契约.运行时 import 平台适配

    return dict(平台适配.子进程组启动标志())


def _喂非法入参(函数: Callable[..., Any], 入参: object) -> Any:
    """故意喂非法入参（验的是运行期收口，不是签名匹配）。

    非法入参在静态类型上必然不匹配，但**这正是自检要验的**：收口层对坏参数必须给
    失败结果而不是抛异常。所以统一走这一个入口，意图写在名字里。
    """
    return 函数(入参)


def _截断(文本: object, 上限: int = 300) -> str:
    """人读输出用的短文本；完整内容一律进 `详情`（JSON 里不丢一个字）。"""
    值 = str(文本 or "")
    return 值 if len(值) <= 上限 else 值[:上限] + f"…（完整 {len(值)} 字见 --json 详情）"


def _安全执行(序号: str, 名称: str, 函数: Callable[[], Any]) -> list[自检项]:
    """执行一个自检项；自检项自己崩了不能当通过（fail-closed：报不支持并带现场）。"""
    try:
        返回 = 函数()
    except Exception as 错误:  # noqa: BLE001
        return [自检项(
            序号, 名称, 结论_不支持,
            f"自检项执行时抛出未预期异常 {type(错误).__name__}: {错误}",
            "自检项的异常说明环境与预期不符，不能当作通过。",
            "这一项在本机**没有被验证**：先按异常现场排查，再重跑本入口。",
            {"异常类型": type(错误).__name__, "异常": str(错误),
             "回溯": traceback.format_exc()[-2000:]},
        )]
    if isinstance(返回, list):
        return [项 for 项 in 返回 if isinstance(项, 自检项)]
    return [返回] if isinstance(返回, 自检项) else []
