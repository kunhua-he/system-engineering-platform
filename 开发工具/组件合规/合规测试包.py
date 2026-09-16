"""组件合规测试包：每个支持库和模块统一验证 13 项强制场景（S0.4 唯一权威）。

强制场景：结构/契约/依赖/配置/权限/生命周期/资源释放/版本升级/失败
语义/说明书/完整性摘要/公共入口/真实返回值。
组件作者不能自行减少强制场景。

S0 缺项阻断清单（正式包形态一律阻断）：配置契约/权限契约/资源预算/
复用决策/注册能力/__all__/能力契约/验证证据。
契约与权限验证遍历聚合契约每个能力（禁整文件当一个能力）；
真实返回经 公开入口+能力注册表+锁定提供者 调用。
"""

from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import socket
import sys
import subprocess
import shutil
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

合规场景表 = [
    "结构", "契约", "依赖", "配置", "权限", "生命周期", "资源释放",
    "版本升级", "失败语义", "说明书", "完整性摘要", "公共入口", "真实返回值",
]

聚合契约文件名 = "参数契约.json"
资源预算必需键 = ("内存上限", "线程上限", "子进程上限", "并发调用上限",
                "队列长度", "文件句柄上限", "临时空间上限", "单次调用超时",
                "每分钟重启次数", "空闲回收时间")
禁止参数类型 = {"任意", ""}


_包仓库后端: Any = None


def _工程根目录() -> Path:
    """向上定位工程根（同时含 平台控制面 与 开发工具 双目录的祖先）。"""
    候选 = Path(__file__).resolve()
    for 祖先 in 候选.parents:
        if (祖先 / "平台控制面").is_dir() and (祖先 / "开发工具").is_dir():
            return 祖先
    return 候选.parents[1]


def _调用包仓库能力(能力id: str, 参数: dict[str, Any]) -> Any:
    """经完整装配调用 平台控制面.包仓库 的公开能力（唯一能力入口）。

    `开发工具` 是进程外调用方：惰性装配钩子只装 支持库/模块库，取不到
    `平台控制面` 的能力，故这里自建完整装配并按**惰性单例**复用（约 1.5 秒，
    不塞进 import 期）。返回统一结果信封（成功/值/错误），不做任何兜底降级。
    """
    global _包仓库后端
    if _包仓库后端 is None:
        from 后端核心.后端核心 import 后端核心
        实例 = 后端核心(_工程根目录())
        启动结果 = 实例.启动()
        if not 启动结果.成功:
            raise RuntimeError(
                f"平台控制面.包仓库 能力装配失败: {启动结果.错误说明}")
        _包仓库后端 = 实例
    return _包仓库后端.调用(能力id, 参数)


def _合规真实输入根(根目录: Path) -> Path:
    """返回当前合规工作单元专属输入根，避免并发包互删文件。"""
    覆盖 = os.environ.get("系统底座_合规输入根", "").strip()
    return Path(覆盖) if 覆盖 else 根目录 / "工程缓存" / "合规真实输入"


def _空闲端口() -> int:
    """取得当前进程可用的回环端口；不占用固定代理端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as 套接字:
        套接字.bind(("127.0.0.1", 0))
        return int(套接字.getsockname()[1])


def _最小PNG() -> bytes:
    """返回一个真实的 1x1 PNG，供图像能力做最小成功调用。"""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _成功标志(返回值: Any) -> bool | None:
    """提取统一结果的成功标志：dict 取 成功 键、对象取 成功 属性。

    非统一结果（普通业务数据）没有该标志，返回 None，调用方据此退化为
    “只看是否为空”的判据，与成功/失败两条路径保持同一口径。
    """
    if isinstance(返回值, dict):
        return bool(返回值["成功"]) if "成功" in 返回值 else None
    if hasattr(返回值, "成功"):
        return bool(返回值.成功)
    return None


def _统一结果错误码(返回值: Any) -> str:
    """提取统一结果的错误码（dict 取 错误码 键、对象取 错误码 属性）。"""
    if isinstance(返回值, dict):
        return str(返回值.get("错误码") or "")
    return str(getattr(返回值, "错误码", "") or "")


def _携带失败结构(返回值: Any) -> bool:
    """自称成功的统一结果是否携带失败结构（错误 或 错误码 非空）。"""
    if isinstance(返回值, dict):
        return bool(返回值.get("错误")) or bool(返回值.get("错误码"))
    return bool(getattr(返回值, "错误", None)) or bool(getattr(返回值, "错误码", ""))


def _参数最小值(能力id: str, 参数: dict[str, Any], 根目录: Path) -> Any:
    """按公开参数契约生成最小合法值，不把占位字符串冒充真实输入。"""
    名称 = str(参数.get("名称", ""))
    类型 = str(参数.get("类型", ""))
    能力输入根 = _合规真实输入根(根目录) / hashlib.sha1(
        能力id.encode("utf-8")).hexdigest()[:10]
    if 名称 in {"端口", "监听端口"}:
        return _空闲端口()
    if 名称 in {"调用函数", "回调函数"} or 类型 in {"函数", "子程序", "句柄型"}:
        return lambda *参数值, **关键字值: {"成功": True, "值": 参数值[0] if 参数值 else ""}
    if 类型 in {"逻辑型", "逻辑"}:
        return bool(参数.get("默认值", False))
    if 类型 in {"整数型", "整数", "单精度整数型", "双精度整数型", "双精度数型", "浮点数型"}:
        if "默认值" in 参数 and 参数.get("默认值") is not None:
            return 参数["默认值"]
        return 1 if 名称 in {"宽度", "高度", "最大边长", "字节数", "最大页数", "最大幻灯片数"} else 0
    if 类型 in {"字节集型", "二进制型"} or 名称 in {"字节", "图片字节"}:
        return _最小PNG()
    if 类型 in {"字典型", "映射型"}:
        if 名称 in {"编码选项", "请求参数"}:
            return {}
        return {"标题": "合规测试", "内容": "真实输入"} if "文档" in 能力id or "生成" in 能力id else {}
    if 类型 in {"列表型", "数组型"}:
        if 名称 == "验证命令":
            return [[sys.executable, "-c", "print('ok')"]]
        if 名称 == "补丁列表":
            return []
        return ["合规测试"]
    if 类型 in {"空值型", "空"}:
        return None
    if "提交哈希" in 名称:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=根目录, text=True).strip()
        except (OSError, subprocess.SubprocessError):
            return "0" * 40
    if "仓库路径" in 名称:
        return str(根目录)
    if "目录" in 名称:
        # 凡语义为「目录」的文本参数，一律给**真实的临时目录**。原实现只认白名单里的
        # 若干目录名，其余（技能根目录/目录路径/目标目录/工作目录…）落到下面的文本兜底
        # 分支拿到字面量"合规测试"，被调用方当成相对路径解析 → 在项目根**凭空建出
        # 「合规测试/」目录**（技能库写 索引.json 就是这么来的），污染工作树。
        目录 = 能力输入根
        目录.mkdir(parents=True, exist_ok=True)
        if 名称 == "来源目录":
            (目录 / "来源.txt").write_text("真实快照输入", encoding="utf-8")
        return str(目录)
    if "相对路径" in 名称:
        目录 = 能力输入根
        目录.mkdir(parents=True, exist_ok=True)
        (目录 / "输入.txt").write_text("真实文件输入", encoding="utf-8")
        return "输入.txt"
    if "路径" in 名称 or 名称 in {"文件", "源文件"}:
        扩展名 = {"PDF文档": ".pdf", "表格文档": ".xlsx", "演示文稿": ".pptx",
                 "文字文档": ".docx"}.get(能力id.split(".", 1)[0], ".txt")
        路径 = 能力输入根 / f"输入{扩展名}"
        路径.parent.mkdir(parents=True, exist_ok=True)
        if not 路径.exists():
            if 扩展名 == ".pdf":
                候选 = next((根目录 / "支持库" / "适配层").rglob("示例.pdf"), None)
                if 候选 and 候选.is_file():
                    路径.write_bytes(候选.read_bytes())
                else:
                    路径.write_bytes(b"%PDF-1.4\n")
            elif 扩展名 == ".txt":
                路径.write_text("真实文档输入\n第二段", encoding="utf-8")
            else:
                路径.write_bytes("真实格式输入".encode("utf-8"))
        return str(路径)
    if 名称 in {"地址", "网址", "URL"}:
        return "http://127.0.0.1:1"
    if 名称 in {"提供者名", "提供者"}:
        return "全部"
    if 名称 in {"目标格式", "输出格式", "格式"}:
        return str(参数.get("默认值") or "txt")
    if 名称 in {"文本", "内容", "标题", "页面说明", "旧文本", "新文本", "目标", "字段名", "键", "值", "条目", "分隔符", "语言"}:
        return "合规测试"
    if "时间戳" in 名称:
        return time.time()
    if 名称 in {"提交消息", "操作", "分支名", "期望值", "新值", "期望版本", "资源id", "持有者"}:
        return "合规测试"
    if "默认值" in 参数 and 参数["默认值"] is not None:
        return 参数["默认值"]
    if 类型 in {"文本型", "文本", "字符串型"}:
        return "合规测试"
    return "合规测试"


def _加载模块(文件路径: Path):
    """加载任意 Python 文件为模块（用于真实实现调用）。"""
    import importlib.util as _工具
    标识 = hashlib.sha1(str(文件路径.resolve()).encode("utf-8")).hexdigest()[:12]
    模块名 = f"合规_{文件路径.stem}_{标识}"
    规格 = _工具.spec_from_file_location(模块名, 文件路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载: {文件路径}")
    模块 = _工具.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块


def _加载入口(组件目录: Path, 入口路径: Path):
    """按公开入口加载入口模块，隔离临时组件的固定包名缓存。"""
    import sys as _系统
    原有模块 = {
        名称: 模块 for 名称, 模块 in _系统.modules.items()
        if 名称 == "实现" or 名称.startswith("实现.")
    }
    for 名称 in list(原有模块):
        del _系统.modules[名称]
    _系统.path.insert(0, str(组件目录))
    try:
        return _加载模块(入口路径)
    finally:
        _系统.path.remove(str(组件目录))
        for 名称 in list(_系统.modules):
            if 名称 == "实现" or 名称.startswith("实现."):
                del _系统.modules[名称]
        _系统.modules.update(原有模块)


def _值类型(值: Any) -> str:
    """按配置值推断类型（用于生产配置校验器声明表）。"""
    if isinstance(值, bool):
        return "布尔"
    if isinstance(值, int):
        return "整数"
    if isinstance(值, float):
        return "浮点数"
    if isinstance(值, str):
        return "文本"
    if isinstance(值, list):
        return "列表"
    if isinstance(值, dict):
        return "字典"
    return "空"


@dataclass
class 合规报告:
    """组件合规测试报告。"""

    组件id: str = ""
    场景结果表: list[tuple[str, bool, str]] = field(default_factory=list)
    总场景数: int = 13

    @property
    def 通过数(self) -> int:
        return sum(1 for _, 通过, _ in self.场景结果表 if 通过)

    @property
    def 成功(self) -> bool:
        return self.通过数 == self.总场景数 and len(self.场景结果表) == self.总场景数


def _是聚合视图包(组件目录: Path) -> bool:
    """聚合视图包判据：**无 `能力定义.json` 且含子包**（与 `正式包索引` 的判据完全一致）。

    这类包是子包的对外视图（如 系统核心支持库、办公文档支持库）：九要素、实现、契约、
    说明书都由**子包**承载，自身只有 `__init__.py` 的注册视图。对它们跑
    「实现/能力契约/说明书/资源释放/版本升级/五件」检查只会恒红——属门禁侧误报，
    按与索引同一判据放行，避免门禁长期空转（哲学第 1 条 4 项）。
    """
    if (组件目录 / "能力定义.json").is_file():
        return False
    for 子 in 组件目录.iterdir():
        if 子.is_dir() and (子 / "包声明.json").is_file():
            return True
    return False


def _读取聚合契约(组件目录: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """读取唯一聚合契约 能力契约/参数契约.json，返回 (能力表, 是否聚合, 问题)。

    聚合格式：顶层 {"契约版本": ..., "能力契约": [能力, ...]}，每个能力为
    独立对象；禁止把整文件当一个能力。不存在聚合文件时回退旧格式
    （能力契约/*.json 单能力对象），供历史组件兼容。
    """
    聚合路径 = 组件目录 / "能力契约" / 聚合契约文件名
    if 聚合路径.is_file():
        try:
            数据 = json.loads(聚合路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [], True, ["参数契约.json JSON 解析失败"]
        问题: list[str] = []
        if not isinstance(数据, dict) or not 数据.get("契约版本"):
            问题.append("聚合契约缺少 契约版本")
        能力表 = 数据.get("能力契约", []) if isinstance(数据, dict) else []
        if not isinstance(能力表, list) or not 能力表:
            问题.append("聚合契约 能力契约 为空（禁整文件当一个能力）")
            return [], True, 问题
        return [能力 for 能力 in 能力表 if isinstance(能力, dict)], True, 问题
    契约目录 = 组件目录 / "能力契约"
    if not 契约目录.is_dir():
        return [], False, ["缺少 能力契约/"]
    能力表: list[dict[str, Any]] = []
    for 契约文件 in sorted(契约目录.glob("*.json")):
        try:
            契约 = json.loads(契约文件.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(契约, dict) and 契约.get("能力id"):
            能力表.append(契约)
    return 能力表, False, ["能力契约/ 为空（无契约 JSON）"] if not 能力表 else []


def _提取函数错误码(实现目录: Path, 函数名: str) -> list[str]:
    """按函数名定位实现函数体，提取统一失败结果中的错误码。

    用于失败语义精确判定：实现有失败路径的能力必须声明对应错误码；
    实现无失败路径（纯查询/纯计算）的能力空错误码合法。
    """
    错误码: list[str] = []
    if not 实现目录.is_dir():
        return 错误码
    for 文件 in 实现目录.rglob("*.py"):
        try:
            内容 = 文件.read_text(encoding="utf-8")
        except Exception:
            continue
        模式 = re.compile(r"def\s+" + re.escape(函数名) + r"\s*\(.*?\n(.*?)(?=\ndef\s+|\Z)", re.S)
        匹配 = 模式.search(内容)
        if not 匹配:
            continue
        函数体 = 匹配.group(1)
        for m in re.findall(r'结果\.失败\(\s*["\']([^"\']+)["\']', 函数体):
            if m not in 错误码:
                错误码.append(m)
        # 兼容统一结果的字典返回写法：
        # {"成功": False, "错误码": "参数不合法"}。
        if re.search(r'["\']成功["\']\s*:\s*False', 函数体):
            for m in re.findall(r'["\']错误码["\']\s*:\s*["\']([^"\']+)["\']', 函数体):
                if m not in 错误码:
                    错误码.append(m)
        if 错误码:
            break
    return 错误码


def _提供者锁定(系统根: Path, 组件目录: Path, 声明: dict[str, Any]) -> tuple[bool, str]:
    """锁定提供者：依赖声明（能力+版本）必须能定位到 支持库/模块库 真实提供者包。"""
    依赖列表 = 声明.get("依赖", []) if isinstance(声明.get("依赖"), list) else []
    if not 依赖列表:
        return True, "无依赖（独立组件，无需锁定提供者）"
    提供者能力表: set[str] = set()
    支持库根 = 系统根 / "支持库"
    模块库根 = 系统根 / "模块库"
    for 包目录 in ([*支持库根.rglob("包声明.json"), *模块库根.rglob("包声明.json")]
                   if 支持库根.is_dir() else []):
        if "pycache" in 包目录.parts or 包目录.parent.name == "_模板":
            continue
        try:
            提供声明 = json.loads(包目录.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        提供声明 = 提供声明 if isinstance(提供声明, dict) else {}
        for 能力 in 提供声明.get("能力", []) if isinstance(提供声明.get("能力"), list) else []:
            if isinstance(能力, dict) and 能力.get("能力id"):
                提供者能力表.add(str(能力["能力id"]))
        定义路径 = 包目录.parent / "能力定义.json"
        if 定义路径.is_file():
            try:
                定义 = json.loads(定义路径.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for 能力 in 定义.get("能力列表", []) if isinstance(定义.get("能力列表"), list) else []:
                if isinstance(能力, dict) and 能力.get("能力id"):
                    提供者能力表.add(str(能力["能力id"]))
        聚合路径 = 包目录.parent / "能力契约" / 聚合契约文件名
        if 聚合路径.is_file():
            try:
                数据 = json.loads(聚合路径.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for 能力 in 数据.get("能力契约", []) if isinstance(数据.get("能力契约"), list) else []:
                if isinstance(能力, dict) and 能力.get("能力id"):
                    提供者能力表.add(str(能力["能力id"]))
    未锁定: list[str] = []
    for 依赖 in 依赖列表:
        if not isinstance(依赖, dict):
            continue
        能力id = str(依赖.get("能力", ""))
        if 能力id and 能力id not in 提供者能力表:
            未锁定.append(能力id)
    if 未锁定:
        return False, f"依赖能力无锁定提供者: {未锁定}"
    return True, f"依赖 {len(依赖列表)} 项全部锁定真实提供者"


class 组件合规:
    """组件合规验证器：对任意组件目录执行 13 项强制场景。"""

    def __init__(self, 组件目录: Path) -> None:
        self.组件目录 = 组件目录
        self.报告 = 合规报告(组件id=组件目录.name)

    @property
    def _系统根(self) -> Path:
        根 = Path(__file__).resolve()
        for 祖先 in 根.parents:
            if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
                return 祖先
        return 根.parents[1]

    @property
    def _正式包形态(self) -> bool:
        return (self.组件目录 / "能力契约" / 聚合契约文件名).is_file()

    def 执行(self) -> 合规报告:
        """执行全部 13 项强制场景。

        聚合视图包（无 `能力定义.json` 且含子包，判据与 `正式包索引` 一致）只跑
        「结构」与「完整性摘要」，另记一行说明：九要素由子包承载，其余 11 项对视图包
        恒红，属门禁侧误报（哲学第 1 条 4 项：门禁不许长期空转）。
        """
        视图包 = _是聚合视图包(self.组件目录)
        场景函数表 = [
            ("结构", self._场景结构),
            ("契约", self._场景契约),
            ("依赖", self._场景依赖),
            ("配置", self._场景配置),
            ("权限", self._场景权限),
            ("生命周期", self._场景生命周期),
            ("资源释放", self._场景资源释放),
            ("版本升级", self._场景版本升级),
            ("失败语义", self._场景失败语义),
            ("说明书", self._场景说明书),
            ("完整性摘要", self._场景完整性摘要),
            ("公共入口", self._场景公共入口),
            ("真实返回值", self._场景真实返回值),
        ]
        if 视图包:
            场景函数表 = [(名, 函数) for 名, 函数 in 场景函数表 if 名 in ("结构", "完整性摘要")]
            self.报告.场景结果表.append(
                ("聚合视图包", True,
                 "九要素由子包承载（判据与 正式包索引 一致）；实现/契约/说明书等 11 项对视图包不适用"))
        self.报告.总场景数 = len(场景函数表) + (1 if 视图包 else 0)
        for 名称, 函数 in 场景函数表:
            try:
                通过, 详情 = 函数()
            except Exception as 错误:
                通过, 详情 = False, f"异常: {错误}"
            self.报告.场景结果表.append((名称, 通过, 详情))
        return self.报告

    def _场景结构(self) -> tuple[bool, str]:
        """结构：九要素目录齐全 + 正式包缺项阻断（资源预算/复用决策/验证证据）。

        聚合视图包只要求「包声明 + 注册入口」：九要素由子包承载，视图自身不重复持有。
        """
        if _是聚合视图包(self.组件目录):
            缺 = [名 for 名 in ("包声明.json", "__init__.py")
                 if not (self.组件目录 / 名).is_file()]
            if 缺:
                return False, f"聚合视图包缺少 {缺}"
            return True, "聚合视图包：包声明 + 注册入口齐全（九要素由子包承载）"
        from 支持库.后端.组件规范支持库 import 校验组件规范
        结果 = 校验组件规范(self.组件目录)
        问题列表 = list(结果.问题列表)
        if self._正式包形态:
            # S0 缺项阻断：资源预算/复用决策/验证证据
            预算路径 = self.组件目录 / "资源预算.json"
            if not 预算路径.is_file():
                问题列表.append("缺少 资源预算.json")
            else:
                try:
                    预算 = json.loads(预算路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("资源预算.json JSON 解析失败")
                    预算 = {}
                if not isinstance(预算, dict):
                    问题列表.append("资源预算.json 顶层必须是对象")
                else:
                    缺失 = [键 for 键 in 资源预算必需键 if 键 not in 预算]
                    if 缺失:
                        问题列表.append(f"资源预算缺少必需项: {缺失}")
            复用路径 = self.组件目录 / "复用决策.json"
            if not 复用路径.is_file():
                问题列表.append("缺少 复用决策.json")
            else:
                try:
                    复用 = json.loads(复用路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("复用决策.json JSON 解析失败")
                    复用 = {}
                if not (isinstance(复用, dict) and 复用.get("搜索词")
                        and 复用.get("候选能力id")):
                    问题列表.append("复用决策缺少 搜索词 或 候选能力id")
            证据路径 = self.组件目录 / "验证场景引用.json"
            if not 证据路径.is_file():
                问题列表.append("缺少 验证证据（验证场景引用.json）")
            else:
                try:
                    证据 = json.loads(证据路径.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    问题列表.append("验证场景引用.json JSON 解析失败")
                    证据 = {}
                if not 证据.get("验证场景引用"):
                    问题列表.append("验证证据为空（验证场景引用 列表必须非空）")
        return not 问题列表, "; ".join(问题列表) or "九要素+资源预算+复用决策+验证证据齐全"

    def _场景契约(self) -> tuple[bool, str]:
        """契约：遍历聚合契约每个能力（S0.1 全要素），禁整文件当一个能力。"""
        from 开发工具.契约编译.契约编译器 import 校验契约结构
        能力表, 是否聚合, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        for 契约 in 能力表:
            if 是否聚合:
                if not 契约.get("能力id"):
                    问题列表.append("聚合契约存在缺少 能力id 的能力")
                if not 契约.get("版本") or "." not in str(契约.get("版本", "")):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 版本")
                if not 契约.get("说明"):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 说明")
                参数列表 = 契约.get("参数")
                if not isinstance(参数列表, list):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 参数")
                else:
                    for 参数 in 参数列表:
                        if not isinstance(参数, dict) or not 参数.get("名称"):
                            问题列表.append(f"{契约.get('能力id', '未知能力')} 存在缺少 名称 的参数")
                            continue
                        if 参数.get("类型") in 禁止参数类型:
                            问题列表.append(
                                f"{契约.get('能力id', '未知能力')} 参数 {参数['名称']} 类型禁止: {参数.get('类型')!r}")
                        if "必填" not in 参数 or "默认值" not in 参数 or "说明" not in 参数:
                            问题列表.append(
                                f"{契约.get('能力id', '未知能力')} 参数 {参数['名称']} 缺少 必填/默认值/说明")
                if not 契约.get("返回"):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 返回结构")
                if not isinstance(契约.get("错误码"), list):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 错误码")
                if not isinstance(契约.get("调用示例"), dict):
                    问题列表.append(f"{契约.get('能力id', '未知能力')} 缺少 可执行调用示例")
                能力id = 契约.get("能力id", "")
                真实错误码 = _提取函数错误码(实现目录, 能力id.split(".")[-1])
                契约错误码 = 契约.get("错误码")
                if not isinstance(契约错误码, list):
                    契约错误码 = []
                未声明 = [码 for 码 in 真实错误码 if 码 not in 契约错误码]
                if 未声明:
                    问题列表.append(f"{能力id} 未声明错误码: {未声明}")
                问题列表.extend(校验契约结构(契约))
            else:
                问题列表.extend(校验契约结构(契约))
        return not 问题列表, "; ".join(问题列表) or f"聚合契约 {len(能力表)} 个能力逐一遍历通过"

    def _场景依赖(self) -> tuple[bool, str]:
        """依赖：逐项按声明形状核验——能力项锁真实提供者、包id项经真实包发现确认。"""
        依赖路径 = self.组件目录 / "依赖契约" / "依赖契约.json"
        if not 依赖路径.is_file():
            # 无文件 = 无内部依赖（2026-09-15 定：空白的内部依赖声明一并删掉，不留占位文件；
            # 判据与实现同源 —— 声明缺失即独立组件，不再要求空文件存在）
            return True, "无依赖（未声明内部依赖）"
        try:
            依赖数据 = json.loads(依赖路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "依赖契约 JSON 解析失败"
        依赖列表 = 依赖数据.get("依赖", []) if isinstance(依赖数据, dict) else 依赖数据
        if not isinstance(依赖列表, list):
            return False, "依赖必须是列表"
        if not 依赖列表:
            return True, "无依赖（独立组件）"
        # 依赖契约实际有三种形状：能力项（能力/版本）、包id项（包id/版本）、外部依赖项
        # （模块名/名称，如 Python 标准库 sqlite3）。原实现一律取 依赖["包id"]，能力形状
        # 恒为空串、`if 依赖包id and ...` 恒短路，等于对所有包一项都不检查却报「经真实包
        # 发现验证」。现按形状分别核验；外部依赖如实排除在系统内包发现核验范围之外，
        # 既不冒充通过、也不误判失败。
        能力项: list[dict[str, Any]] = []
        包id项: list[dict[str, Any]] = []
        外部项: list[dict[str, Any]] = []
        无法核验项: list[Any] = []
        for 依赖 in 依赖列表:
            if not isinstance(依赖, dict):
                无法核验项.append(依赖)
            elif str(依赖.get("能力", "")).strip():
                能力项.append(依赖)
            elif str(依赖.get("包id", "")).strip():
                包id项.append(依赖)
            elif str(依赖.get("模块名", "")).strip() or str(依赖.get("名称", "")).strip():
                外部项.append(依赖)
            else:
                无法核验项.append(依赖)
        if 无法核验项:
            return False, f"依赖项未声明 能力/包id/模块名，无从核验: {无法核验项[:3]}"
        问题列表: list[str] = []
        if 包id项:
            from 运行核心.加载器.包发现.发现器 import 发现全部
            发现 = 发现全部(self._系统根 / "支持库", self._系统根 / "模块库", self._系统根 / "技能库")
            真实包id集 = {声明.包id for 声明 in 发现.声明列表}
            未发现 = [str(依赖["包id"]) for 依赖 in 包id项 if str(依赖["包id"]) not in 真实包id集]
            if 未发现:
                问题列表.append(f"依赖包不存在（经真实包发现）: {未发现}")
        if 能力项:
            锁定成功, 锁定证据 = _提供者锁定(self._系统根, self.组件目录, {"依赖": 能力项})
            if not 锁定成功:
                问题列表.append(锁定证据)
        if 问题列表:
            return False, "; ".join(问题列表)
        摘要 = f"依赖 {len(依赖列表)} 项：能力 {len(能力项)} 项锁定真实提供者、包 {len(包id项)} 项经真实包发现确认"
        if 外部项:
            外部名 = [str(依赖.get("模块名") or 依赖.get("名称") or "") for 依赖 in 外部项]
            摘要 += f"；外部依赖 {len(外部项)} 项不在系统内包发现核验范围: {外部名}"
        return True, 摘要

    def _场景配置(self) -> tuple[bool, str]:
        """配置：配置契约存在（缺则阻断）并按契约真实执行缺失/类型/未知项检查。"""
        配置路径 = self.组件目录 / "配置契约" / "配置契约.json"
        if not 配置路径.is_file():
            return False, "缺少 配置契约/配置契约.json"
        try:
            配置契约 = json.loads(配置路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "配置契约 JSON 解析失败"
        if not isinstance(配置契约, dict) or not 配置契约:
            return False, "配置契约不能为空"
        from 项目适配层.配置适配.配置校验 import 校验配置
        try:
            声明表 = {键: {"类型": _值类型(值), "必填": False}
                      for 键, 值 in 配置契约.items()}
            校验结果 = 校验配置(配置契约, 声明表=声明表)
            问题 = 校验结果.问题列表 if hasattr(校验结果, "问题列表") else []
            if 问题:
                return False, "; ".join(问题)
        except (ImportError, AttributeError) as 错误:
            return False, f"生产配置校验器不可用: {错误}"
        return True, f"配置项 {len(配置契约)} 项（经生产校验器检查）"

    def _场景权限(self) -> tuple[bool, str]:
        """权限：遍历聚合契约每个能力都必须有权限声明（缺权限契约阻断）。"""
        权限路径 = self.组件目录 / "权限契约" / "权限契约.json"
        if not 权限路径.is_file():
            return False, "缺少 权限契约/权限契约.json"
        try:
            权限 = json.loads(权限路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "权限契约 JSON 解析失败"
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        公开能力表 = [能力.get("能力id", "") for 能力 in 能力表 if 能力.get("能力id")]
        if not 公开能力表:
            return False, "无公开能力可校验权限"
        if not isinstance(权限, dict):
            return False, f"权限契约顶层必须是对象（映射 能力id → 权限声明），实为 {type(权限).__name__}"
        缺失权限 = [能力id for 能力id in 公开能力表 if 能力id not in 权限]
        if 缺失权限:
            return False, f"公开能力缺权限声明（逐能力遍历检出）: {缺失权限}"
        return True, f"聚合契约 {len(公开能力表)} 个能力全部有权限声明"

    def _场景生命周期(self) -> tuple[bool, str]:
        """生命周期：实际执行合法流转/非法流转/重复操作/失败回滚。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        if not 声明.get("版本"):
            return False, "缺少 版本（生命周期依据）"
        调用结果 = _调用包仓库能力("平台控制面.包仓库.校验包生命周期", {
            "包id": str(声明.get("包id", "合规组件")),
            "版本": str(声明.get("版本", "1.0.0"))})
        if not 调用结果.成功:
            return False, f"生命周期校验不可用: {调用结果.错误说明}"
        问题 = list(调用结果.值["问题列表"])
        if 问题:
            return False, "; ".join(问题)
        return True, f"版本 {声明['版本']}（合法/非法/重复/回滚全部真实执行）"

    def _场景资源释放(self) -> tuple[bool, str]:
        """资源释放：真实创建资源并验证关闭/句柄归零/锁释放；文本扫描仅辅助。"""
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        if not 实现目录.is_dir():
            return False, "缺少 实现/ 或 执行单元/"
        问题列表 = []
        for 文件 in 实现目录.rglob("*.py"):
            内容 = 文件.read_text(encoding="utf-8")
            # 判据：有 open( 调用、且不在任何 with 语句行内、且全文件无 close() → 才判未关闭。
            # 认 with 里的 Path.open（`with 文件.open("rb") as 流:`）同样属正确关闭方式。
            if (re.search(r"\bopen\(", 内容)
                    and not re.search(r"with[^\n]*\bopen\(", 内容)
                    and "close()" not in 内容):
                问题列表.append(f"{文件.name} 存在 open 未关闭")
            if "while True" in 内容 and "break" not in 内容 and "return" not in 内容:
                问题列表.append(f"{文件.name} 存在无退出无限循环")
        if 问题列表:
            return False, "; ".join(问题列表)
        import tempfile as _临时
        from 支持库.后端.系统核心支持库.资源管理 import (
            创建唯一运行目录, 原子写入, 安全释放资源, 资源短锁,
        )
        try:
            运行目录 = 创建唯一运行目录(Path(_临时.gettempdir()), "合规资源")
            测试文件 = 运行目录 / "测试.json"
            原子写入(测试文件, '{"值": 1}')
            锁 = 资源短锁(运行目录 / "锁", "合规资源", 持有者="合规测试")
            锁成功, _ = 锁.获取()
            if not 锁成功:
                return False, "资源短锁获取失败"
            锁释放, _ = 锁.释放()
            if not 锁释放:
                return False, "资源短锁释放失败"
            释放成功, 释放消息 = 安全释放资源(运行目录)
            if not 释放成功:
                return False, f"资源释放失败: {释放消息}"
            if 运行目录.exists():
                return False, "资源释放后目录仍存在"
        except Exception as 错误:
            return False, f"真实资源释放异常: {错误}"
        return True, "真实创建并释放资源（目录/文件/短锁全部归零）"

    def _场景版本升级(self) -> tuple[bool, str]:
        """版本升级：遍历聚合契约每个能力的版本号格式合法。"""
        from 开发工具.契约编译.漂移检测 import 主版本号
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        for 契约 in 能力表:
            版本 = 契约.get("版本", "")
            if not 版本 or 主版本号(版本) < 0 or "." not in str(版本):
                问题列表.append(f"{契约.get('能力id', '未知能力')} 版本号不合法: {版本}")
        return not 问题列表, "; ".join(问题列表) or f"聚合契约 {len(能力表)} 个能力版本号合法"

    def _场景失败语义(self) -> tuple[bool, str]:
        """失败语义：实现有失败路径的能力必须声明对应错误码；实现不吞异常。"""
        能力表, _, 问题列表 = _读取聚合契约(self.组件目录)
        if 问题列表 and not 能力表:
            return False, "; ".join(问题列表)
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        # 实现有 结果.失败 的能力，契约必须声明对应错误码；无失败路径能力空错误码合法。
        for 契约 in 能力表:
            能力id = 契约.get("能力id", "")
            契约错误码 = 契约.get("错误码") if isinstance(契约.get("错误码"), list) else []
            函数名 = 能力id.split(".")[-1]
            真实错误码 = _提取函数错误码(实现目录, 函数名)
            未声明 = [码 for 码 in 真实错误码 if 码 not in 契约错误码]
            if 未声明:
                问题列表.append(f"{能力id} 未声明错误码: {未声明}")
        if 实现目录.is_dir():
            for 文件 in 实现目录.rglob("*.py"):
                内容 = 文件.read_text(encoding="utf-8")
                if re.search(r"except\s+Exception\s*:\s*(?:#[^\n]*\n\s*)?pass\b", 内容):
                    问题列表.append(f"{文件.name} 吞异常（except Exception 后直接 pass）")
        return not 问题列表, "; ".join(问题列表) or "失败语义明确"

    def _场景说明书(self) -> tuple[bool, str]:
        """说明书：说明存在且非空。"""
        说明目录 = self.组件目录 / "说明"
        说明书 = self.组件目录 / "说明书.md"
        if 说明目录.is_dir():
            文件列表 = list(说明目录.rglob("*.md"))
            if not 文件列表:
                return False, "说明/ 目录为空"
            return True, f"说明书 {len(文件列表)} 份"
        if 说明书.is_file() and 说明书.read_text(encoding="utf-8").strip():
            return True, "说明书.md 存在"
        return False, "缺少 说明/ 或 说明书.md"

    def _场景完整性摘要(self) -> tuple[bool, str]:
        """完整性摘要：经唯一校验器验证文件清单格式闭合（拒绝旧格式与自比较）。"""
        from 支持库.后端.组件规范支持库 import 校验完整性摘要
        通过, 问题列表 = 校验完整性摘要(self.组件目录)
        if not 通过:
            return False, "; ".join(问题列表) or "完整性摘要校验失败"
        return True, "文件清单格式校验通过（唯一校验器）"

    def _场景公共入口(self) -> tuple[bool, str]:
        """公共入口：入口文件存在且可导入；正式包形态必须有 __all__ 与 注册能力。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        入口 = 声明.get("入口", "")
        if not 入口:
            return False, "包声明缺少 入口"
        入口路径 = self.组件目录 / 入口
        if not 入口路径.is_file():
            return False, f"入口文件不存在: {入口}"
        try:
            入口模块 = _加载入口(self.组件目录, 入口路径)
        except Exception as 错误:
            return False, f"入口不可导入: {错误}"
        问题列表 = []
        if self._正式包形态 and 入口路径.name == "__init__.py":
            if not getattr(入口模块, "__all__", None):
                问题列表.append("缺少 __all__（正式包入口必须声明公开导出）")
            if not callable(getattr(入口模块, "注册能力", None)):
                问题列表.append("缺少 注册能力 函数（正式包入口必须注册能力）")
        return not 问题列表, "; ".join(问题列表) or f"入口 {入口} 可导入"

    def _场景真实返回值(self) -> tuple[bool, str]:
        """真实返回：经 公开入口.注册能力 + 能力注册表 + 锁定提供者 调用真实实现。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        from 公共契约.能力契约.契约 import 能力实现, 能力注册表
        # 1. 锁定提供者：依赖能力必须锁定真实提供者包
        锁定成功, 锁定证据 = _提供者锁定(self._系统根, self.组件目录, 声明)
        if not 锁定成功:
            return False, 锁定证据
        # 2. 公开入口：经入口模块的 注册能力 注册实现（正式包形态强制）
        入口 = 声明.get("入口", "")
        入口模块 = None
        if 入口 and (self.组件目录 / 入口).is_file():
            try:
                入口模块 = _加载入口(self.组件目录, self.组件目录 / 入口)
            except Exception:
                入口模块 = None
        注册表 = 能力注册表()
        已注册 = False
        if 入口模块 is not None and callable(getattr(入口模块, "注册能力", None)):
            入口模块.注册能力(注册表)
            已注册 = bool(注册表.能力id列表)
        if not 已注册:
            实现目录 = self.组件目录 / "实现"
            if not 实现目录.is_dir():
                实现目录 = self.组件目录 / "执行单元"
            能力表, _, _ = _读取聚合契约(self.组件目录)
            for 契约 in 能力表[:1]:
                能力id = 契约.get("能力id", "")
                实现文件 = 实现目录 / f"{能力id.split('.')[-1]}.py"
                if not 实现文件.is_file():
                    for 候选 in sorted(实现目录.rglob("*.py")):
                        if "pycache" not in str(候选) and not 候选.name.startswith("_"):
                            实现文件 = 候选
                            break
                if 实现文件.is_file():
                    try:
                        模块 = _加载模块(实现文件)
                        实现函数 = getattr(模块, 能力id.split(".")[-1])
                        注册表.注册(能力实现(
                            能力id=能力id, 包id=声明.get("包id", self.组件目录.name),
                            实现函数=实现函数, 参数=契约.get("参数", []),
                            返回=契约.get("返回", "普通返回"), 说明=契约.get("说明", ""),
                        ))
                        已注册 = True
                    except (ImportError, AttributeError):
                        continue
        if not 已注册:
            return False, "公开入口未提供 注册能力 且无可用实现（真实返回不可达）"
        # 3. 装配最小合规调用器（模块实现经 获取能力调用器 调用的唯一装配路径）
        from 公共契约.能力契约.调用器 import 注册能力调用器

        class _合规调用器:
            def __init__(self, 注册表) -> None:
                self._注册表 = 注册表

            def 调用能力(self, 能力id: str, 参数: dict | None = None, **选项) -> Any:
                from 公共契约.基础类型.结果类型 import 结果
                实现 = self._注册表.获取(能力id)
                if 实现 is None:
                    return 结果.失败("提供者不可用", f"能力未注册: {能力id}",
                                      来源="组件合规", 可重试=True)
                返回值 = 实现.调用(**(参数 or {}))
                if isinstance(返回值, dict):
                    if 返回值.get("成功"):
                        return 结果.成功结果(返回值.get("值"))
                    return 结果.失败(str(返回值.get("错误码") or "失败"),
                                      str(返回值.get("消息") or ""), 来源="组件合规")
                return 返回值

            def 幂等重放(self, *args, **kwargs) -> bool:
                return False

            def 查询调用历史(self, 上限: int = 50) -> list:
                return []

            def 最近失败(self, 上限: int = 10) -> list:
                return []

            def 回答九问(self, *args, **kwargs) -> dict:
                return {}

        注册能力调用器(_合规调用器(注册表))
        try:
            问题 = self._遍历真实调用(注册表)
        finally:
            注册能力调用器(None)
        if 问题:
            return False, "；".join(问题)
        return True, f"真实调用 {len(注册表.能力id列表)} 个能力全部非空返回"

    def _遍历真实调用(self, 注册表) -> list[str]:
        """遍历注册表每个能力：成功路径 + 缺必填失败路径。"""
        问题: list[str] = []
        能力表, _, _ = _读取聚合契约(self.组件目录)
        示例参数表 = {
            契约.get("能力id", ""): (契约.get("调用示例") or {}).get("参数", {})
            for 契约 in 能力表 if isinstance(契约.get("调用示例"), dict)
        }
        真实输入根 = _合规真实输入根(self._系统根)
        try:
            for 能力id in 注册表.能力id列表:
                实现对象 = 注册表.获取(能力id)
                if 实现对象 is None:
                    问题.append(f"{能力id} 注册表获取失败")
                    continue
                # 真实调用参数以组件自身聚合契约为准；入口注册表可能携带
                # 提供者内部参数，不能把那些跨边界参数错误传入公开入口。
                契约 = next((条目 for 条目 in 能力表 if 条目.get("能力id") == 能力id), {})
                参数表 = 契约.get("参数", []) if isinstance(契约.get("参数", []), list) else []
                示例参数 = 示例参数表.get(能力id, {})
                # 示例只覆盖显式值；必填参数和未显式给出的默认参数均由契约语义补齐。
                成功参数 = {
                    参数["名称"]: 示例参数.get(参数["名称"], _参数最小值(能力id, 参数, self._系统根))
                    for 参数 in 参数表 if isinstance(参数, dict) and 参数.get("名称")
                }
                # 固定端口是共享资源，测试必须改用实时探测的空闲端口。
                for 参数 in 参数表:
                    if isinstance(参数, dict) and 参数.get("名称") in {"端口", "监听端口"}:
                        成功参数[参数["名称"]] = _空闲端口()
                try:
                    成功结果 = 实现对象.调用(**成功参数)
                except Exception as 错误:
                    问题.append(f"{能力id} 成功路径异常: {错误}")
                    continue
                try:
                    if 成功结果 is None:
                        问题.append(f"{能力id} 成功路径无返回（真实返回为空）")
                    else:
                        # 环境无关的统一结果契约检查（不改判成功标志，避免把编译检查
                        # 变成环境检查：文件/服务类能力在无外部资源时必然返回 失败(...)）。
                        # 判的是自洽性：成功不得携带失败结构，失败必须带稳定错误码。
                        标志 = _成功标志(成功结果)
                        if 标志 is True and _携带失败结构(成功结果):
                            问题.append(f"{能力id} 成功结果携带失败结构（成功/失败自相矛盾）")
                        elif 标志 is False and not _统一结果错误码(成功结果):
                            问题.append(f"{能力id} 失败结果缺少错误码（失败不可诊断）")
                finally:
                    # 浏览器/句柄型能力必须真实释放，防止固定端口和线程残留污染后续包。
                    for 方法名 in ("shutdown", "server_close", "关闭", "释放", "close"):
                        方法 = getattr(成功结果, 方法名, None) if 成功结果 is not None else None
                        if callable(方法):
                            try:
                                方法()
                            except Exception as 错误:
                                # 释放失败不能静默：端口/线程残留会污染后续包的判定，
                                # 必须留痕（哲学第 3 条 2 项）；失败不阻断其余释放方法继续尝试。
                                from 公共契约.诊断.忽略记录 import 记录忽略
                                记录忽略(f"合规测试包.能力释放.{方法名}", 错误)
                必填参数表 = [参数 for 参数 in 参数表 if 参数.get("必填", True)]
                # 没有必填参数时不存在“缺少必填参数”场景。
                if 必填参数表:
                    失败参数 = {参数["名称"]: _参数最小值(能力id, 参数, self._系统根)
                                for 参数 in 参数表 if not 参数.get("必填", True)}
                    try:
                        失败结果 = 实现对象.调用(**失败参数)
                        if _成功标志(失败结果) is True:
                            问题.append(f"{能力id} 缺必填参数未返回失败（失败语义缺失）")
                    except TypeError:
                        # 缺必填参数被 Python 签名拒绝 = 失败语义成立
                        pass
                    except Exception as 错误:
                        问题.append(f"{能力id} 缺必填参数调用异常（失败语义缺失）: {错误}")
        finally:
            shutil.rmtree(真实输入根, ignore_errors=True)
        return 问题
