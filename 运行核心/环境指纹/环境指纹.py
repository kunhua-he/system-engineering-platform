"""环境指纹与稳定证据失效：运行时/OS/架构/第三方变化 → 稳定证据自动失效。

P5 规则：环境指纹变化时，基于旧环境的稳定证据（验证记录/门禁结果）
自动失效，组件降为候选；重新验证后才能恢复稳定。

环境指纹至少包含：
- Python 版本 / 操作系统 / CPU 架构
- 第三方发行包精确版本
- 外部应用版本（LibreOffice/textutil）
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配

第三方版本探测 = {
    "cryptography": "cryptography",
    "python-docx": "docx",
    "PyMuPDF": "fitz",
    "openpyxl": "openpyxl",
    "pdfplumber": "pdfplumber",
    "python-pptx": "pptx",
    "psycopg": "psycopg",
    "reportlab": "reportlab",
}


@dataclass
class 环境指纹结果:
    """环境指纹计算/比较结果。"""

    成功: bool = 真
    指纹: str = ""
    详细信息: dict[str, Any] = field(default_factory=dict)
    问题列表: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 成功 由问题列表决定（append 后自动失效）
        if self.问题列表:
            self.成功 = 假


def _包版本(模块名: str) -> str:
    """取第三方包版本；未安装 → '未安装'。

    只读发行包元数据（importlib.metadata），**不 import 模块本体**：
    原生扩展（如 fitz/PyMuPDF）禁止在主进程加载，版本探测必须在
    主进程内安全完成（隔离铁律）。
    """
    try:
        from importlib import metadata as _元数据
        import sys as _sys

        # 模块名 → 发行包名映射（fitz 属于 PyMuPDF 发行包）
        发行包名 = {"fitz": "PyMuPDF"}.get(模块名, 模块名)
        return _元数据.version(发行包名)
    except Exception:
        return "未安装"


外部应用探针清单 = (
    ("LibreOffice", "LibreOffice soffice", ("soffice", "libreoffice"), "--version"),
    ("textutil", "textutil", ("textutil",), "-help"),
)


def 探测外部应用版本() -> dict[str, str]:
    """探测外部应用版本（LibreOffice/textutil），统一经 系统探针。

    版本来源与 健康监督/提供者检查提供者 完全一致：
    支持库.适配层.系统探针.检查系统工具（独立子进程，超时强杀，
    超时/退出码非0 收敛为明确失败），不再独立 subprocess 逻辑。

    失败语义：工具缺失/探针超时/退出码非零 → "失败:<错误码>" 明确失败
    标记，绝不返回伪造版本（如"未知"或路径冒充）；
    textutil 无独立版本号，版本取 macOS 系统版本（探针成功为前提）。
    """
    from 支持库.适配层.系统探针 import 检查系统工具
    结果: dict[str, str] = {}
    for 工具, 探针名, 候选列表, 版本参数 in 外部应用探针清单:
        路径 = next((c for c in 候选列表 if shutil.which(c)), None)
        if not 路径:
            结果[工具] = "失败:工具缺失"
            continue
        探针 = 检查系统工具(探针名, [路径], 版本参数=版本参数)
        if not 探针.成功:
            结果[工具] = f"失败:{探针.错误码}"
            continue
        if 工具 == "textutil":
            结果[工具] = platform.mac_ver()[0] or platform.release()
        else:
            结果[工具] = 探针.版本 or "可用"
    return 结果


def 计算环境指纹(*, 含外部应用: bool = 真) -> 环境指纹结果:
    """计算当前环境指纹。"""
    详细信息: dict[str, Any] = {
        "python": sys.version.split()[0],
        "os": 平台适配.本机系统名(),
        "os版本": platform.release(),
        "架构": 平台适配.当前架构(),
        "第三方": {名称: _包版本(模块) for 名称, 模块 in 第三方版本探测.items()},
    }
    if 含外部应用:
        详细信息["外部应用"] = 探测外部应用版本()
    指纹 = hashlib.sha256(
        json.dumps(详细信息, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return 环境指纹结果(真, 指纹=指纹, 详细信息=详细信息)


def 读取证据环境指纹(证据文件: Path) -> str:
    """读取稳定证据记录中的环境指纹；无记录 → 空。"""
    if not 证据文件.is_file():
        return ""
    try:
        数据 = json.loads(证据文件.read_text(encoding="utf-8"))
        return 数据.get("环境指纹", "")
    except (json.JSONDecodeError, OSError):
        return ""


def 校验证据有效(证据文件: Path, *, 含外部应用: bool = 真) -> 环境指纹结果:
    """校验稳定证据是否仍有效：当前指纹 == 记录指纹。"""
    当前 = 计算环境指纹(含外部应用=含外部应用)
    if not 当前.成功:
        return 当前
    记录指纹 = 读取证据环境指纹(证据文件)
    if not 记录指纹:
        当前.问题列表.append("无证据环境指纹记录（证据失效：无法验证）")
        当前.成功 = 假
        return 当前
    if 记录指纹 != 当前.指纹:
        当前.问题列表.append(
            f"环境指纹漂移（证据失效）：记录 {记录指纹} ≠ 当前 {当前.指纹}"
        )
        当前.成功 = 假
    return 当前


def 生成证据记录(证据文件: Path, 附加: dict | None = None) -> 环境指纹结果:
    """生成带环境指纹的稳定证据记录。"""
    当前 = 计算环境指纹()
    if not 当前.成功:
        return 当前
    记录 = {"环境指纹": 当前.指纹, "指纹详情": 当前.详细信息}
    if 附加:
        记录.update(附加)
    证据文件.parent.mkdir(parents=True, exist_ok=True)
    证据文件.write_text(json.dumps(记录, ensure_ascii=False, indent=2), encoding="utf-8")
    return 当前
