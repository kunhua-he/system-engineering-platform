"""HTML 黑盒验证器：对编译产物发真实 HTTP GET/POST，只看返回值判断功能。

职责（华哥裁决 2026-08-29）：
- 启动编译产物（独立 HTML 启动器），得到真实 HTTP 地址
- 按验证场景对产物发 GET / POST 请求
- 只看 HTTP 状态码 + 返回的 成功/值/错误码/错误说明/请求id/耗时
- 功能正常/异常直接判定；异常按 编译/路由/参数/能力/Provider 定位线索输出
- 每次验证落证据（请求、返回、状态、耗时、资源释放），绑定工作区指纹

本验证器不导入源码、不调用内部实现、不猜后端状态；后端怎么实现它不需要知道。
编译器只编译小单元 + 检查合规，禁止跑全量；HTML 验证器可以全量、多线程并发。

用法：
    python3.14 开发工具/HTML验证/验证器.py --制品 示例项目/可双击演示/产物文件夹/20260822-demo
    python3.14 开发工具/HTML验证/验证器.py --制品 <路径> --场景 验证场景.json
    python3.14 开发工具/HTML验证/验证器.py --制品 <路径> --并发 32
    python3.14 开发工具/HTML验证/验证器.py --制品 <路径> --只生成场景   # 只生成场景不验证
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

验证版本 = "1.0.0"
默认并发 = 8
默认超时秒 = 15
固定端口 = 45080  # 华哥裁决：HTML 黑盒验证器固定端口，不静默换随机端口
请求上限字节 = 1024 * 1024
证据目录名 = "验证证据"
场景文件名 = "验证场景.json"


# ---------- 数据结构 ----------

@dataclass
class 验证场景:
    """一个能力的验证场景：怎么请求、预期什么。"""

    场景id: str
    能力id: str = ""
    方法: str = "POST"  # GET / POST
    路径: str = "/网关/调用"
    参数: dict[str, Any] = field(default_factory=dict)
    预期状态码: int = 200
    预期错误码: str = ""  # 空 = 期望成功；非空 = 期望该错误码
    预期包含: str = ""  # 返回正文应包含的子串
    说明: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "场景id": self.场景id, "能力id": self.能力id, "方法": self.方法,
            "路径": self.路径, "参数": self.参数, "预期状态码": self.预期状态码,
            "预期错误码": self.预期错误码, "预期包含": self.预期包含, "说明": self.说明,
        }

    @classmethod
    def 从字典(cls, 数据: dict[str, Any]) -> "验证场景":
        return cls(
            场景id=str(数据.get("场景id", "")),
            能力id=str(数据.get("能力id", "")),
            方法=str(数据.get("方法", "POST")).upper(),
            路径=str(数据.get("路径", "/网关/调用")),
            参数=数据.get("参数", {}) or {},
            预期状态码=int(数据.get("预期状态码", 200)),
            预期错误码=str(数据.get("预期错误码", "")),
            预期包含=str(数据.get("预期包含", "")),
            说明=str(数据.get("说明", "")),
        )


@dataclass
class 验证结果:
    """一次验证的结果。"""

    场景id: str
    能力id: str
    通过: bool = False
    状态码: int = 0
    返回: dict[str, Any] = field(default_factory=dict)
    耗时毫秒: float = 0
    失败原因: str = ""
    定位线索: str = ""  # 编译/路由/参数/能力/Provider

    def 转字典(self) -> dict[str, Any]:
        return {
            "场景id": self.场景id, "能力id": self.能力id, "通过": self.通过,
            "状态码": self.状态码, "返回": self.返回, "耗时毫秒": self.耗时毫秒,
            "失败原因": self.失败原因, "定位线索": self.定位线索,
        }


@dataclass
class 验证报告:
    """一次验证运行的完整报告。"""

    制品路径: str = ""
    制品指纹: dict[str, str] = field(default_factory=dict)
    场景总数: int = 0
    通过数: int = 0
    失败数: int = 0
    结果列表: list[验证结果] = field(default_factory=list)
    时间: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "制品路径": self.制品路径, "制品指纹": self.制品指纹,
            "场景总数": self.场景总数, "通过数": self.通过数, "失败数": self.失败数,
            "结果列表": [项.转字典() for 项 in self.结果列表], "时间": self.时间,
        }

    def 汇总(self) -> str:
        self.时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        if self.场景总数 == 0:
            return "阻断: 无任何验证场景（禁止零验证成功）"
        if self.失败数 > 0:
            return f"失败: {self.失败数}/{self.场景总数} 个场景未通过"
        return f"通过: {self.通过数}/{self.场景总数} 个场景全部通过"


# ---------- 工作区指纹 ----------

def _工作区指纹(排除目录: Path | None = None) -> dict[str, str]:
    """记录验证输入的 Git 提交和工作区指纹，避免旧证据冒充当前源码。"""

    def 执行(命令: list[str]) -> str:
        try:
            结果 = subprocess.run(
                命令, cwd=系统根, capture_output=True, text=True, timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return 结果.stdout.strip() if 结果.returncode == 0 else ""

    提交 = 执行(["git", "rev-parse", "HEAD"])
    状态 = 执行(["git", "status", "--porcelain=v1", "-z"])
    if 排除目录 is not None:
        try:
            排除相对 = 排除目录.resolve().relative_to(系统根.resolve()).as_posix().rstrip("/") + "/"
            条目 = []
            for 项 in 状态.split("\0"):
                if not 项:
                    continue
                路径 = 项[3:] if len(项) >= 4 and 项[2] == " " else 项
                if not 路径.startswith(排除相对):
                    条目.append(项)
            状态 = "\0".join(条目)
        except ValueError:
            pass
    return {
        "提交": 提交 or "未知",
        "工作区摘要": hashlib.sha256(状态.encode("utf-8")).hexdigest(),
        "工作区状态": "干净" if not 状态 else "含未提交变更",
        "验证器版本": 验证版本,
    }


# ---------- 制品发现 ----------

def _找启动器(制品目录: Path) -> Path:
    """在制品目录里找独立启动器（运行入口/启动.py 或 独立HTML启动器.py）。"""
    候选 = [
        制品目录 / "运行入口" / "启动.py",
        制品目录 / "运行入口" / "独立HTML启动器.py",
        制品目录 / "运行入口" / "启动器.py",
    ]
    for 路径 in 候选:
        if 路径.is_file():
            return 路径
    # 兜底：递归找 运行入口 下的 py
    for 路径 in sorted((制品目录 / "运行入口").rglob("*.py")):
        if "启动" in 路径.name or "入口" in 路径.name:
            return 路径
    raise FileNotFoundError(f"制品目录找不到启动器: {制品目录}")


def _制品指纹(制品目录: Path) -> dict[str, str]:
    """对制品关键元数据做摘要：来源、完整性、编译清单。"""
    指纹: dict[str, str] = {}
    for 文件名 in ("制品来源.json", "制品完整性摘要.json", "编译清单.json", "依赖锁.json"):
        路径 = 制品目录 / 文件名
        if 路径.is_file():
            指纹[文件名] = hashlib.sha256(路径.read_bytes()).hexdigest()[:16]
    return 指纹


def _扫描能力契约(制品目录: Path) -> list[dict[str, Any]]:
    """扫描制品内 模块库/ 与 支持库/ 的 能力契约/参数契约.json，生成真实场景。

    规则：每个能力契约条目生成一个 POST /网关/调用 场景；
    参数用契约里的 默认值/调用示例/示例 填充；无法填满必填参数的场景标为
    「缺参数」预期错误码（验证参数校验本身），不再凭空造值。
    """
    场景列表: list[dict[str, Any]] = []
    候选目录 = [
        制品目录 / "模块库",
        制品目录 / "支持库",
    ]
    for 根目录 in 候选目录:
        if not 根目录.is_dir():
            continue
        for 契约路径 in sorted(根目录.rglob("能力契约")):
            if not 契约路径.is_dir():
                continue
            for 参数文件 in sorted(契约路径.rglob("参数契约.json")):
                try:
                    数据 = json.loads(参数文件.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                能力列表 = 数据.get("能力契约", []) if isinstance(数据, dict) else []
                for 条目 in 能力列表:
                    if not isinstance(条目, dict):
                        continue
                    能力id = str(条目.get("能力id") or "").strip()
                    if not 能力id:
                        continue
                    参数声明 = 条目.get("参数", []) or []
                    示例参数: dict[str, Any] = {}
                    缺失必填: list[str] = []
                    for 声明 in 参数声明:
                        if not isinstance(声明, dict):
                            continue
                        名称 = str(声明.get("名称") or "").strip()
                        if not 名称:
                            continue
                        默认值 = 声明.get("默认值")
                        示例值 = 声明.get("示例")
                        if 示例值 is not None:
                            示例参数[名称] = 示例值
                        elif 默认值 is not None:
                            示例参数[名称] = 默认值
                        elif 声明.get("必填"):
                            缺失必填.append(名称)
                    # 调用示例 兜底
                    调用示例 = 条目.get("调用示例") or {}
                    if isinstance(调用示例, dict) and isinstance(调用示例.get("参数"), dict):
                        for 键, 值 in 调用示例["参数"].items():
                            if 键 not in 示例参数:
                                示例参数[键] = 值
                    场景列表.append({
                        "场景id": f"能力.{能力id}", "能力id": 能力id, "方法": "POST",
                        "路径": "/网关/调用", "参数": 示例参数,
                        "预期状态码": 200,
                        # 缺必填参数且无默认值/示例值时，验证器无法凭空构造参数；
                        # 该场景验证「参数校验」本身：期望网关返回 参数不合法。
                        "预期错误码": "参数不合法" if 缺失必填 else "",
                        "预期包含": "", "说明": f"由能力契约自动生成（缺必填: {','.join(缺失必填)}，参数校验场景）"
                        if 缺失必填 else "由能力契约自动生成",
                    })
    return 场景列表


def _扫描制品能力(制品目录: Path) -> list[dict[str, Any]]:
    """兼容旧名：扫描制品生成场景。"""
    return _扫描能力契约(制品目录)


def _加载场景(制品目录: Path, 场景路径: Path | None) -> list[验证场景]:
    """加载验证场景：优先显式场景文件，否则扫描制品自动生成。"""
    if 场景路径 is not None and 场景路径.is_file():
        数据 = json.loads(场景路径.read_text(encoding="utf-8"))
        列表 = 数据.get("验证场景", []) if isinstance(数据, dict) else 数据
        return [验证场景.从字典(项) for 项 in 列表 if isinstance(项, dict) and 项.get("场景id")]
    自动场景 = _扫描制品能力(制品目录)
    if not 自动场景:
        raise ValueError(f"找不到验证场景: {场景路径} 且制品内无可自动生成场景")
    return [验证场景.从字典(项) for 项 in 自动场景]


# ---------- 验证执行 ----------

def _检查端口可用(端口: int) -> tuple[bool, str]:
    """探测端口是否可监听（固定端口策略：冲突明确报错，不静默换随机端口）。"""
    import socket as _套接字
    测试 = _套接字.socket(_套接字.AF_INET, _套接字.SOCK_STREAM)
    try:
        测试.bind(("127.0.0.1", 端口))
        return True, ""
    except OSError as 错误:
        return False, f"端口 {端口} 已被占用: {错误}"
    finally:
        测试.close()


def _发送请求(地址: str, 场景: 验证场景, 超时秒: float) -> tuple[int, dict, float]:
    """发送真实 HTTP 请求，返回 (状态码, JSON, 耗时毫秒)。

    只通过 HTTP 访问编译产物，不导入任何源码。
    路径必须 quote 成 ASCII（urllib 的 putrequest 要求 ASCII，中文路径直接报错）。
    quote 输出的 %XX 不会二次转义（urllib 只对未编码的非 ASCII 做 quote）。
    """
    开始 = time.monotonic()
    # 只编码路径部分，保留协议+主机+端口前缀原样（urlsplit 正确拆分，不能用 partition）
    拆分 = urllib.parse.urlsplit(地址)
    完整地址 = f"{拆分.scheme}://{拆分.netloc}"
    场景路径 = 场景.路径
    if not 场景路径.startswith("/"):
        场景路径 = "/" + 场景路径
    if 场景.方法 == "GET":
        请求 = urllib.request.Request(完整地址 + urllib.parse.quote(场景路径, safe="/:@._-"), method="GET")
    else:
        请求体 = {"能力id": 场景.能力id, "参数": 场景.参数 or {}}
        请求 = urllib.request.Request(
            完整地址 + urllib.parse.quote(场景路径, safe="/:@._-"),
            data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
            耗时 = (time.monotonic() - 开始) * 1000
            正文 = 响应.read(请求上限字节).decode("utf-8")
            try:
                return 响应.status, json.loads(正文), 耗时
            except json.JSONDecodeError:
                return 响应.status, {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200]}, 耗时
    except urllib.error.HTTPError as 错误:
        耗时 = (time.monotonic() - 开始) * 1000
        正文 = 错误.read(请求上限字节).decode("utf-8", errors="replace")
        try:
            return 错误.code, json.loads(正文), 耗时
        except json.JSONDecodeError:
            return 错误.code, {"成功": False, "错误码": "返回非JSON", "错误说明": 正文[:200]}, 耗时
    except (urllib.error.URLError, TimeoutError, OSError) as 错误:
        耗时 = (time.monotonic() - 开始) * 1000
        return 502, {"成功": False, "错误码": "网关断开", "错误说明": str(错误)}, 耗时


def _判定(场景: 验证场景, 状态码: int, 返回: dict[str, Any]) -> tuple[bool, str, str]:
    """按场景预期判定结果，返回 (通过, 失败原因, 定位线索)。

    优先级：错误码预期 > 状态码预期 > 成功预期 > 包含预期。
    预期错误码非空时（如 参数不合法），状态码不必是 200（网关对错误码
    返回 400/403/404/503 等），只看错误码是否命中。
    """
    返回 = 返回 or {}
    # 1. 错误码预期（非空 = 期望特定失败；状态码按错误码映射，不要求 200）
    if 场景.预期错误码:
        if 返回.get("错误码") == 场景.预期错误码:
            return True, "", ""
        return False, f"错误码 {返回.get('错误码')!r} != 预期 {场景.预期错误码!r}", "能力"
    # 2. 状态码预期
    if 场景.预期状态码 and 状态码 != 场景.预期状态码:
        线索 = "路由" if 状态码 in (404, 405) else "网关"
        return False, f"状态码 {状态码} != 预期 {场景.预期状态码}", 线索
    # 3. 默认期望成功
    if 状态码 >= 400:
        线索 = {
            "参数不合法": "参数", "能力不存在": "能力", "句柄失效": "句柄",
            "权限不足": "权限", "提供者不可用": "Provider", "限流": "限流",
        }.get(str(返回.get("错误码")), "网关")
        return False, f"{返回.get('错误码', 'HTTP错误')}: {返回.get('错误说明', '')}", 线索
    if not 返回.get("成功"):
        线索 = {
            "参数不合法": "参数", "能力不存在": "能力", "句柄失效": "句柄",
            "权限不足": "权限", "提供者不可用": "Provider", "限流": "限流",
        }.get(str(返回.get("错误码")), "能力")
        return False, f"{返回.get('错误码', '失败')}: {返回.get('错误说明', '')}", 线索
    # 4. 预期包含（可选）
    if 场景.预期包含:
        正文 = json.dumps(返回, ensure_ascii=False)
        if 场景.预期包含 not in 正文:
            return False, f"返回未包含预期子串: {场景.预期包含}", "值"
    return True, "", ""


def 验证单个(地址: str, 场景: 验证场景, 超时秒: float = 默认超时秒) -> 验证结果:
    """验证一个场景。"""
    结果 = 验证结果(场景id=场景.场景id, 能力id=场景.能力id)
    状态码, 返回, 耗时 = _发送请求(地址, 场景, 超时秒)
    结果.状态码 = 状态码
    结果.返回 = 返回
    结果.耗时毫秒 = 耗时
    通过, 原因, 线索 = _判定(场景, 状态码, 返回)
    结果.通过 = 通过
    结果.失败原因 = 原因
    结果.定位线索 = 线索
    return 结果


def 验证全部(
    制品目录: Path,
    场景列表: list[验证场景],
    并发: int = 默认并发,
    超时秒: float = 默认超时秒,
    端口: int = 0,
    自动打开: bool = False,
    直连地址: str = "",
) -> tuple[验证报告, int | None, Any]:
    """启动制品 → 并发验证 → 返回报告 + 制品端口 + 制品进程句柄。

    直连地址 非空时跳过启动，直接对已运行制品地址验证（返回端口=0、进程=None）。
    返回 (报告, 端口, 进程句柄)。进程句柄由调用方负责最终回收。
    """
    启动器 = _找启动器(制品目录)
    报告 = 验证报告(制品路径=str(制品目录))
    报告.制品指纹 = _制品指纹(制品目录)

    地址 = 直连地址
    进程: Any = None
    实际端口: int | None = None
    启动输出: list[str] = []
    if 直连地址:
        # 直连模式：不启动制品，直接用已运行地址
        地址 = 直连地址
    else:
        # 自启动模式：先检查固定端口是否可用（冲突明确报错，不静默换随机端口）
        端口可用, 端口消息 = _检查端口可用(端口)
        if not 端口可用:
            报告.结果列表.append(验证结果(
                场景id="制品启动", 能力id="",
                通过=False, 失败原因=端口消息, 定位线索="端口",
            ))
            报告.失败数 = 1
            return 报告, None, None
        # 启动制品（独立 HTML 启动器），等待就绪
        进程 = subprocess.Popen(
            [sys.executable, "-u", str(启动器), "--端口", str(端口), "--不自动打开"],
            cwd=str(制品目录),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        实际端口 = 端口
        就绪 = False
        截止 = time.time() + 20
        启动输出: list[str] = []
        while time.time() < 截止:
            if 进程.poll() is not None:
                输出, 错误 = 进程.communicate(timeout=3)
                报告.结果列表.append(验证结果(
                    场景id="制品启动", 能力id="",
                    通过=False, 失败原因=f"制品启动失败: {输出} {错误}", 定位线索="编译",
                ))
                报告.失败数 = 1
                return 报告, None, 进程
            行 = 进程.stdout.readline() if 进程.stdout else ""
            if 行:
                启动输出.append(行.strip())
                if "已启动" in 行 or "127.0.0.1" in 行:
                    import re
                    匹配 = re.search(r"127\.0\.0\.1:(\d+)", 行)
                    if 匹配:
                        实际端口 = int(匹配.group(1))
                        就绪 = True
                        break
            time.sleep(0.05)
        if not 就绪:
            报告.结果列表.append(验证结果(
                场景id="制品启动", 能力id="",
                通过=False, 失败原因=f"制品启动超时，输出: {'; '.join(启动输出)}", 定位线索="编译",
            ))
            报告.失败数 = 1
            return 报告, None, 进程
        地址 = f"http://127.0.0.1:{实际端口}"
    报告.场景总数 = len(场景列表)

    # 先验证健康/首页（制品是否真的能服务）
    # 自启动/直连都统一走页面宿主入口：GET / 返回 HTML 页面（200）。
    # 能力调用统一走页面宿主 POST /网关/调用（页面宿主转发到内部网关），
    # 不绕过页面宿主直连内部网关——黑盒验证必须走用户真实路径。
    健康路径 = "/"
    健康场景 = 验证场景(场景id="制品.健康", 能力id="", 方法="GET", 路径=健康路径,
                      预期状态码=200, 预期包含="", 说明="制品可用性检查（只认状态码）")
    健康结果 = 验证单个(地址, 健康场景, 超时秒)
    if 健康结果.状态码 != 200:
        健康结果.通过 = False
        健康结果.失败原因 = f"制品健康检查状态码 {健康结果.状态码} != 200"
        健康结果.定位线索 = "编译"
        报告.结果列表.append(健康结果)
        报告.失败数 += 1
        return 报告, 实际端口, 进程
    # 健康检查通过但返回非 JSON（页面 HTML）时仍算通过
    健康结果.通过 = True
    健康结果.失败原因 = ""
    报告.结果列表.append(健康结果)

    # 并发验证全部场景
    结果表: list[验证结果] = []
    with ThreadPoolExecutor(max_workers=并发) as 执行器:
        任务表 = {执行器.submit(验证单个, 地址, 场景, 超时秒): 场景 for 场景 in 场景列表}
        for 任务 in as_completed(任务表):
            结果表.append(任务.result())
    报告.结果列表 = 结果表
    报告.通过数 = sum(1 for 项 in 结果表 if 项.通过)
    报告.失败数 = len(结果表) - 报告.通过数
    return 报告, 实际端口, 进程


# ---------- 证据落盘 ----------

def _证据根目录(制品目录: Path) -> Path:
    """证据根目录：默认写到 工程缓存/HTML验证证据/，绝不写进制品目录
    （避免污染 制品完整性摘要.json，导致发布门禁「示例制品来源与摘要」失败）。"""
    return 系统根 / "工程缓存" / "HTML验证证据"


def 保存证据(报告: 验证报告, 制品目录: Path, 输出目录: Path | None = None) -> Path:
    """把验证报告写成证据文件，绑定工作区指纹。

    默认输出到 工程缓存/HTML验证证据/（不污染制品目录）；显式传 输出目录 时用指定路径。
    """
    输出 = 输出目录 or _证据根目录(制品目录)
    输出.mkdir(parents=True, exist_ok=True)
    报告.制品指纹.update(_工作区指纹())
    时间戳 = time.strftime("%Y%m%d_%H%M%S")
    路径 = 输出 / f"验证证据_{时间戳}.json"
    路径.write_text(
        json.dumps(报告.转字典(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 路径


# ---------- 场景文件生成 ----------

def 生成场景文件(制品目录: Path, 输出: Path | None = None) -> Path:
    """扫描制品自动生成 验证场景.json。

    默认输出到 工程缓存/HTML验证证据/（不污染制品目录）；显式传 输出 时用指定路径。
    """
    自动 = _扫描制品能力(制品目录)
    输出路径 = 输出 or (_证据根目录(制品目录) / 场景文件名)
    输出路径.parent.mkdir(parents=True, exist_ok=True)
    输出路径.write_text(
        json.dumps({"验证场景": 自动}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 输出路径


# ---------- 服务模式（托管验证页 + 反向代理） ----------

def 服务模式(制品地址: str, 服务端口: int = 45081, 制品目录: Path | None = None) -> int:
    """托管验证页 + 反向代理请求到制品（浏览器同源，无跨域）。

    浏览器打开 http://127.0.0.1:45081/ 使用验证页；
    页面所有请求走相对路径 /代理/*，本服务转发到制品地址；
    /验证场景.json 返回制品的验证场景清单（供验证页加载）。
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    验证页目录 = Path(__file__).resolve().parent
    页面字节 = (验证页目录 / "验证页.html").read_bytes()
    # 场景文件：从 工程缓存/HTML验证证据/ 读（不污染制品目录），否则扫描生成
    场景字节 = json.dumps({"验证场景": []}, ensure_ascii=False).encode("utf-8")
    if 制品目录 is not None:
        try:
            场景路径 = _证据根目录(制品目录) / 场景文件名
            if not 场景路径.is_file():
                生成场景文件(制品目录)
            场景字节 = 场景路径.read_bytes()
        except (OSError, ValueError):
            场景字节 = json.dumps({"验证场景": []}, ensure_ascii=False).encode("utf-8")

    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式, *参数): return
        def _CORS头(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        def do_OPTIONS(self):
            self.send_response(204); self._CORS头(); self.end_headers()
        def do_GET(self):
            if self.path == "/" or self.path == "/验证页.html":
                self.send_response(200); self._CORS头()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(页面字节)))
                self.end_headers(); self.wfile.write(页面字节); return
            if urllib.parse.unquote(self.path) == "/验证场景.json":
                self.send_response(200); self._CORS头()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(场景字节)))
                self.end_headers(); self.wfile.write(场景字节); return
            # 浏览器/curl 会把中文路径编码，必须 unquote 后再转发，否则二次编码 404
            if urllib.parse.unquote(self.path).startswith("/代理/"):
                目标 = 制品地址 + urllib.parse.unquote(self.path)[len("/代理"):]
                self._转发("GET", 目标); return
            self.send_error(404)
        def do_POST(self):
            if urllib.parse.unquote(self.path).startswith("/代理/"):
                目标 = 制品地址 + urllib.parse.unquote(self.path)[len("/代理"):]
                长度 = int(self.headers.get("Content-Length", "0") or 0)
                正文 = self.rfile.read(长度) if 长度 else b""
                self._转发("POST", 目标, 正文); return
            self.send_error(404)
        def _转发(self, 方法: str, 目标: str, 正文: bytes = b"") -> None:
            import urllib.request as _请求
            # urllib 不能直接发原始中文路径，必须 quote 编码路径部分
            拆分 = urllib.parse.urlsplit(目标)
            编码路径 = urllib.parse.quote(拆分.path, safe="/:@._-")
            编码目标 = f"{拆分.scheme}://{拆分.netloc}{编码路径}"
            if 拆分.query:
                编码目标 += "?" + 拆分.query
            try:
                请求对象 = _请求.Request(编码目标, data=正文 or None, method=方法,
                                     headers={"Content-Type": "application/json"})
                with _请求.urlopen(请求对象, timeout=15) as 响应:
                    状态码, 返回 = 响应.status, 响应.read()
            except urllib.error.HTTPError as 错误:
                状态码, 返回 = 错误.code, 错误.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                状态码 = 502; 返回 = json.dumps(
                    {"成功": False, "错误码": "网关断开", "错误说明": "制品不可访问"},
                    ensure_ascii=False).encode()
            self.send_response(状态码); self._CORS头()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(返回)))
            self.end_headers(); self.wfile.write(返回)

    服务 = ThreadingHTTPServer(("127.0.0.1", 服务端口), 处理器)
    print(f"验证页已启动: http://127.0.0.1:{服务.server_port}/ （代理到 {制品地址}）")
    try:
        服务.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        服务.server_close()
    return 0


# ---------- 主入口 ----------

def 主函数(参数: argparse.Namespace) -> int:
    制品目录 = Path(参数.制品).resolve()
    if not 制品目录.is_dir():
        print(f"阻断: 制品目录不存在: {制品目录}")
        return 2

    if 参数.只生成场景:
        路径 = 生成场景文件(制品目录, Path(参数.场景) if 参数.场景 else None)
        print(f"验证场景已生成: {路径}")
        return 0

    if 参数.服务:
        # 服务模式：托管验证页 + 反向代理到制品
        return 服务模式(参数.直连地址 or f"http://127.0.0.1:{参数.端口}", 参数.服务, 制品目录)

    场景列表 = _加载场景(制品目录, Path(参数.场景) if 参数.场景 else None)
    print(f"加载 {len(场景列表)} 个验证场景")
    报告, 端口, 进程 = 验证全部(
        制品目录, 场景列表, 并发=参数.并发, 超时秒=参数.超时秒, 端口=参数.端口,
        直连地址=参数.直连地址,
    )
    证据路径 = 保存证据(报告, 制品目录)
    print(报告.汇总())
    print(f"证据: {证据路径}")
    for 结果 in 报告.结果列表:
        if not 结果.通过:
            print(f"  ✗ [{结果.场景id}] {结果.失败原因}（{结果.定位线索}）")
    # 回收制品进程
    if 进程 is not None and 进程.poll() is None:
        进程.terminate()
        try:
            进程.wait(timeout=5)
        except subprocess.TimeoutExpired:
            进程.kill()
            进程.wait(timeout=5)
    return 0 if 报告.失败数 == 0 else 1


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="HTML 黑盒验证器：对编译产物发真实 HTTP 请求")
    解析器.add_argument("--制品", required=True, help="编译产物目录（含 运行入口/启动.py）")
    解析器.add_argument("--场景", default="", help="验证场景.json 路径（缺省扫描制品自动生成）")
    解析器.add_argument("--并发", type=int, default=默认并发, help=f"并发线程数（默认 {默认并发}）")
    解析器.add_argument("--超时秒", type=float, default=默认超时秒, help=f"单请求超时秒（默认 {默认超时秒}）")
    解析器.add_argument("--端口", type=int, default=固定端口, help=f"制品启动端口（默认 {固定端口}，固定；冲突报错，不静默换随机端口）")
    解析器.add_argument("--直连地址", default="", help="直连已运行制品地址（如 http://127.0.0.1:65485，跳过启动）")
    解析器.add_argument("--服务", type=int, default=0, help="服务模式：托管验证页+反向代理到制品（如 45081）")
    解析器.add_argument("--只生成场景", action="store_true", help="只生成验证场景文件，不验证")
    raise SystemExit(主函数(解析器.parse_args()))
