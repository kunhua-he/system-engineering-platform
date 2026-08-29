"""测试中心一键运行入口（标准验收命令）。

unittest discover 的 VALID_MODULE_NAME 只认 ASCII 标识符，无法加载
中文测试文件名（测试_*.py），且默认顶层目录会与系统根同名包冲突，
因此本脚本通过 load_tests 协议直接加载全部测试。

门禁（禁止零测试成功）：
- 实际加载全部测试，测试数量为零时必须失败
- 任一测试文件导入失败时失败
- 任一测试失败时返回非零
- 连续运行结果稳定

用法：
    python3.14 测试中心/运行测试.py
    python3.14 测试中心/运行测试.py --继续
    python3.14 测试中心/运行测试.py --测试文件 测试中心/模块库/测试_文件管理模块.py
    python3.14 测试中心/运行测试.py --阶段 模块合规
    python3.14 测试中心/运行测试.py --范围 慢速
    python3.14 测试中心/运行测试.py --范围 全部
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows 无 fcntl；本平台锁仅在 POSIX 生效
    fcntl = None

系统根 = Path(__file__).resolve().parents[1]
# 无条件插到最前：系统根包名（公共契约/能力契约等）与测试中心下同名测试目录
# 冲突，若依赖 in 判断可能因 cwd/脚本目录已在 sys.path 而跳过插入，
# 导致 import 公共契约 命中测试目录而非真实包（cProfile -m 实测复现）。
sys.path.insert(0, str(系统根))

import 测试中心
from MCP工具箱 import 测试资源

验证缓存目录 = 系统根 / "工程缓存" / "验证缓存"
验证文件缓存目录 = 验证缓存目录 / "文件"  # 文件级缓存子目录（阶段缓存失效后的细化层）
断点文件路径 = 系统根 / "工程缓存" / "验证断点.json"
运行根目录 = 系统根 / "工程缓存" / "验证运行"
验证锁路径 = 系统根 / "工程缓存" / "验证锁.lock"  # 全量互斥 flock 文件锁
清理失败证据目录 = 系统根 / "工程缓存" / "清理失败证据"
保留制品目录 = 系统根 / "工程缓存" / "保留制品"
缓存结构版本 = "3.0.0"  # 缓存结构版本：完整性证明/运行证据变化时整体失效
运行证据有效秒 = 7 * 24 * 60 * 60
环境敏感缓存有效秒 = 24 * 60 * 60  # 环境敏感阶段（真实进程/网关/浏览器/发布门禁/慢速层）依赖真实环境，缓存有效期缩短到 1 天
弱依赖缓存有效秒 = 3600  # 弱依赖文件级缓存有效期：超时后强制失效重跑
目录摘要上限 = 100  # 扫描目录数超过该值时不记目录摘要表（降级弱依赖，防递归开销爆炸）
环境敏感阶段 = {"真实进程", "网关", "浏览器", "发布门禁", "慢速层"}
# 阶段级并行不是“测试越多越快”：阶段进程会共享工程缓存、SQLite、
# 发布指针和导入状态。只有已审计为纯静态、不会写共享状态的阶段允许同批
# 启动；其余阶段即使不属于环境敏感阶段，也必须按固定顺序串行。
阶段安全并行白名单 = {"静态契约", "组件合规"}
# 仅允许明确证明使用独立临时目录、不会触碰发布指针/固定端口的慢速文件并行。
# 其余慢速场景继续串行，避免强杀、共享 SQLite 或外部服务相互干扰。
慢速安全并行文件 = {
    "测试中心/慢速层/第十三阶段/测试_核心切换恢复.py",
    "测试中心/慢速层/第十三阶段/测试_资源压力.py",
    # 以下场景只使用各自的临时目录或纯计算状态；不触碰固定端口、
    # 发布指针、共享 SQLite、Docker 或强杀目标，可与上面两项并行。
    "测试中心/慢速层/第十三阶段/测试_会话恢复.py",
    "测试中心/慢速层/第十三阶段/测试_控制面对账.py",
    "测试中心/慢速层/第十三阶段/测试_注册表.py",
    "测试中心/慢速层/第十三阶段/测试_版本兼容.py",
    "测试中心/慢速层/第十三阶段/测试_超时治理.py",
    "测试中心/慢速层/第十三阶段/测试_采样器.py",
    "测试中心/慢速层/第十四阶段/测试_工作包14_直连规则.py",
    "测试中心/慢速层/第十四阶段/测试_工作包15_密钥提供者.py",
    "测试中心/慢速层/第十四阶段/测试_工作包17_构建反向审计.py",
    "测试中心/慢速层/第十四阶段/测试_工作包18_体验面对称审计.py",
    "测试中心/慢速层/第十四阶段/测试_工作包20_完整示例.py",
    "测试中心/慢速层/第十四阶段/测试_环境配置句柄.py",
}
# 慢速层的其余测试默认按文件串行是过于保守的：很多场景只创建独立
# 临时目录/子进程，彼此没有共享状态。以下仅列出必须串行的资源族；
# 通过资源族审计后，其它慢速文件可进入同一批独立工作包并行执行。
慢速强制串行文件片段 = (
    "残留审计", "发布强杀", "进程组管理", "资源硬限制", "资源压力",
    "控制面对账", "数据库提供者", "PostgreSQL提供者", "psycopg提供者",
    "HTTP提供者", "动态库提供者", "提供者故障", "进程提供者", "注册表",
    "工作包12", "工作包13", "工作包16", "工作包19", "消费者契约",
    "平台防火墙",
)


def 慢速可并行文件(文件: Path) -> bool:
    """判断慢速测试是否可放入独立工作包并行批。

    这里只按已审计的共享资源族阻断；未知文件仍默认并行，但每个文件
    运行在独立子进程和临时根中，任何异常/清理失败都会让整批失败。
    """
    return not any(片段 in 文件.name for 片段 in 慢速强制串行文件片段)
# 即使所属阶段非环境敏感，也不得并发触碰共享的外部转换器工作目录。
# 这些文件单独串行，其余同阶段文件仍可并行。
内部并行排除文件片段 = ("文档转换", "文字文档", "表格文档")


def _文件使用共享外部工具(文件: Path) -> bool:
    """外部工具通常共享 profile/临时目录，按文件内容保守判定互斥。"""
    if any(片段 in 文件.name for 片段 in 内部并行排除文件片段):
        return True
    try:
        文本 = 文件.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    return any(标记 in 文本 for 标记 in ("LibreOffice", "soffice", "textutil", "ffmpeg", "tesseract"))
# 阶段内部仅对白名单中的纯静态测试启用文件级并行；涉及固定端口、
# SQLite、发布指针或强杀目标的阶段继续由阶段级调度串行执行。
# 标准验收固定阶段顺序（静态契约→组件合规→结构迁移→权威状态→资源并发→
# 平台控制面→反向破坏→项目装配→真实进程→网关→浏览器→发布门禁）；
# 前 8 个非环境敏感阶段允许并行，后 4 个环境敏感阶段永不并行。
常规阶段顺序表 = [
    ("静态契约", ["测试_零测试门禁.py", "公共契约", "加载器", "支持库", "模块库"]),
    ("组件合规", ["测试_静态契约.py", "测试_组件合规.py"]),
    ("结构迁移", ["结构迁移"]),
    ("权威状态", ["权威状态"]),
    ("资源并发", ["资源并发"]),
    ("平台控制面", ["平台控制面"]),
    ("反向破坏", ["第九阶段/测试_反向破坏.py"]),
    ("项目装配", ["示例项目", "项目适配", "第三阶段", "第四阶段", "第十阶段", "第十一阶段"]),
    ("真实进程", ["第五阶段", "第六阶段"]),
    ("网关", ["第七阶段"]),
    ("浏览器", ["第八阶段"]),
    ("发布门禁", ["测试_门禁.py", "发布门禁"]),
]
慢速阶段顺序表 = [
    ("慢速层", ["慢速层"]),
    # 未被常规/慢速既有阶段明确收集的测试，统一进入串行治理阶段；
    # 覆盖门禁会同时阻断漏测和重复归属，不能再静默遗漏。
    ("平台治理", ["__未归属测试__"]),
]
_阶段进程登记表: dict[str, subprocess.Popen] = {}
_阶段进程锁 = threading.Lock()
顶层包目录表 = {
    目录.name for 目录 in 系统根.iterdir()
    if 目录.is_dir() and 目录.name not in ("测试中心", "工程缓存", "开发文档", ".git", "__pycache__")
}


_git指纹映射: dict[str, str] | None = None  # 仓库根相对路径 → git blob hash（惰性构建）
_git脏文件集合: set[str] | None = None      # dirty/untracked 路径集合（仓库根相对，惰性构建）


def _仓库根相对路径(路径: Path) -> str:
    """仓库根相对路径（git 路径风格：/ 分隔）；仓库外返回空串。"""
    try:
        return str(路径.resolve().relative_to(系统根.resolve())).replace(os.sep, "/")
    except ValueError:
        return ""


def _构建git指纹映射(*, 强制刷新: bool = False) -> None:
    """惰性构建 git 指纹映射：ls-files 取全部已跟踪 blob hash，status 取脏/未跟踪清单。

    构建失败（非 git 仓库、git 不可用等）时映射置空，摘要回退现场哈希，不抛异常。
    强制刷新：验证运行期间工作区可能被并行修改，缓存判定前必须刷新脏集合，
    否则已变 dirty 的文件仍返回旧 blob hash → 摘要不变 → 缓存误命中假绿。
    """
    global _git指纹映射, _git脏文件集合
    if _git指纹映射 is not None and not 强制刷新:
        return
    _git指纹映射 = {}
    _git脏文件集合 = set()
    try:
        ls结果 = subprocess.run(
            ["git", "ls-files", "-s", "-z"], cwd=系统根,
            capture_output=True, check=False,
        )
        if ls结果.returncode != 0:
            return
        for 条目 in ls结果.stdout.decode("utf-8", errors="replace").split("\0"):
            if not 条目:
                continue
            元数据, 路径 = 条目.split("\t", 1)
            _, 对象哈希, 阶段 = 元数据.split(" ", 2)
            if 阶段 == "0":
                _git指纹映射[路径] = 对象哈希
        状态结果 = subprocess.run(
            ["git", "status", "--porcelain", "-z"], cwd=系统根,
            capture_output=True, check=False,
        )
        if 状态结果.returncode != 0:
            # status 失败时不能继续使用已取得的 blob 映射，否则工作区改动
            # 会被误当作干净文件并命中阶段缓存。
            _git指纹映射 = {}
            _git脏文件集合 = set()
            return
        for 条目 in 状态结果.stdout.decode("utf-8", errors="replace").split("\0"):
            # 条目形如 "XY 路径"；重命名条目的旧路径段不以两位状态码+空格开头，跳过
            if len(条目) < 4 or 条目[2:3] != " ":
                continue
            _git脏文件集合.add(条目[3:])
    except (OSError, ValueError):
        # git 不可用或输出格式异常 → 回退现场哈希
        _git指纹映射 = {}
        _git脏文件集合 = set()


def _文件摘要(文件: Path) -> str:
    """文件内容摘要：干净已跟踪文件免读盘取 git blob hash，其余现场 sha256。

    统一截断 16 位十六进制；git 指纹映射构建失败（非 git 仓库等）时回退现场哈希。
    """
    # 缓存判定可能与编辑器/其它工作包并行发生；Git 的 blob 与脏集合
    # 只是在调用开始时的快照，不能作为现场证据。每次都读取当前内容，
    # 以确保运行期间的修改必然使缓存失效。
    return hashlib.sha256(文件.read_bytes()).hexdigest()[:16]


def _缓存完整性摘要(缓存项: dict) -> str:
    """计算缓存证据的完整性摘要；摘要字段本身不参与计算。"""
    待摘要 = {键: 值 for 键, 值 in 缓存项.items() if 键 != "完整性摘要"}
    序列化 = json.dumps(待摘要, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(序列化.encode("utf-8")).hexdigest()


def _缓存证据完整(缓存项: dict | None) -> bool:
    """缓存必须带运行 id、命令/输出证据和不可缺失的完整性摘要。"""
    if not isinstance(缓存项, dict):
        return False
    运行id = str(缓存项.get("运行id", ""))
    输出摘要 = str(缓存项.get("输出摘要", ""))
    命令摘要 = str(缓存项.get("执行命令摘要", ""))
    完整性 = str(缓存项.get("完整性摘要", ""))
    if not 运行id or not 命令摘要 or len(输出摘要) != 64 or len(完整性) != 64:
        return False
    if any(字符 not in "0123456789abcdef" for 字符 in 输出摘要.lower() + 完整性.lower() + 命令摘要.lower()):
        return False
    return 完整性 == _缓存完整性摘要(缓存项)


def _补齐缓存证据(缓存项: dict, 输出: str = "") -> dict:
    """为新缓存绑定本次运行、执行命令和实际输出摘要。"""
    缓存项 = dict(缓存项)
    缓存项.setdefault("运行id", os.environ.get("系统底座_验证运行id") or uuid.uuid4().hex)
    命令 = " ".join(sys.argv)
    缓存项.setdefault("执行命令摘要", hashlib.sha256(命令.encode("utf-8")).hexdigest())
    缓存项.setdefault("输出摘要", hashlib.sha256(str(输出).encode("utf-8")).hexdigest())
    缓存项["完整性摘要"] = _缓存完整性摘要(缓存项)
    return 缓存项


def _目录摘要(目录: Path) -> str:
    """目录内容摘要（rglob 全量枚举，逐文件 git 指纹或现场哈希；排除缓存）。"""
    摘要器 = hashlib.sha256()
    for 文件 in sorted(目录.rglob("*")):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件):
            摘要器.update(str(文件.relative_to(目录)).encode("utf-8"))
            摘要器.update(_文件摘要(文件).encode("utf-8"))
    return 摘要器.hexdigest()[:16]


def 收集阶段文件(匹配表: list[str]) -> list[Path]:
    """按阶段匹配表收集测试文件。"""
    文件列表: list[Path] = []
    for 匹配 in 匹配表:
        if 匹配 == "__未归属测试__":
            已明确归属: set[Path] = set()
            for _, 其他匹配表 in 常规阶段顺序表 + 慢速阶段顺序表:
                for 其他匹配 in 其他匹配表:
                    if 其他匹配 != "__未归属测试__":
                        已明确归属.update(收集阶段文件([其他匹配]))
            文件列表.extend(全部测试文件() - 已明确归属)
            continue
        for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
            if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                文件列表.append(路径)
            elif 路径.is_dir():
                文件列表.extend(路径.rglob("测试_*.py"))
    return sorted(文件列表)


def 全部测试文件() -> set[Path]:
    """收集测试中心内全部测试文件，作为覆盖门禁的唯一全集。"""
    return {
        路径 for 路径 in 测试中心.测试中心目录.rglob("测试_*.py")
        if 路径.is_file()
    }


def 校验测试覆盖(
    阶段文件表: dict[str, list[Path]],
    全部测试文件: list[Path],
) -> dict[str, object]:
    """校验测试文件是否全部且唯一归属阶段。

    这是纯逻辑校验，不负责扫描文件；调用方必须先给出唯一的实际文件表。
    返回原始 Path，便于测试和报告保留准确路径。
    """
    全部集合 = set(全部测试文件)
    文件归属: dict[Path, list[str]] = {}
    阶段空缺 = [阶段名 for 阶段名, 文件表 in 阶段文件表.items() if not 文件表]
    for 阶段名, 文件表 in 阶段文件表.items():
        for 文件 in 文件表:
            文件归属.setdefault(文件, []).append(阶段名)
    重复 = {
        文件: sorted(阶段名表)
        for 文件, 阶段名表 in 文件归属.items()
        if len(阶段名表) > 1
    }
    漏测 = sorted(全部集合 - set(文件归属), key=str)
    成功 = not 漏测 and not 重复 and not 阶段空缺
    return {
        "成功": 成功,
        "漏测": 漏测,
        "重复": 重复,
        "阶段空缺": sorted(阶段空缺),
    }


def 阶段依赖目录表(测试文件列表: list[Path]) -> set[str]:
    """解析测试文件的 import 依赖 → 受影响系统顶层包目录。

    覆盖三种形态：行首静态 import/from、importlib 动态导入、源码中的顶层包路径字符串。
    静态解析是保守估计（宁多失效不假绿）：动态导入与路径引用一律计入对应顶层包。
    """
    依赖表: set[str] = set()
    import模式 = re.compile(r"^\s*(?:from|import)\s+([一-龥\w.]+)")
    动态导入模式 = re.compile(r"(?:importlib\.)?import_module\s*\(\s*['\"]([一-龥\w.]+)['\"]")
    路径引用模式 = re.compile(r"['\"]([一-龥\w]+/[\w./-]+)['\"]")
    顶层包字符串模式 = re.compile(r"['\"]([一-龥\w]+)['\"]")
    for 文件 in 测试文件列表:
        try:
            for 行 in 文件.read_text(encoding="utf-8").splitlines():
                匹配 = import模式.match(行)
                if 匹配:
                    顶层包 = 匹配.group(1).split(".")[0].strip()
                    if 顶层包 in 顶层包目录表:
                        依赖表.add(顶层包)
                动态匹配 = 动态导入模式.search(行)
                if 动态匹配:
                    顶层包 = 动态匹配.group(1).split(".")[0].strip()
                    if 顶层包 in 顶层包目录表:
                        依赖表.add(顶层包)
                路径匹配 = 路径引用模式.search(行)
                if 路径匹配:
                    首段 = 路径匹配.group(1).split("/", 1)[0].strip()
                    if 首段 in 顶层包目录表:
                        依赖表.add(首段)
                # 顶层包目录名作为独立字符串出现（如 系统根 / "示例项目"）也纳入依赖
                for 字符串匹配 in 顶层包字符串模式.finditer(行):
                    候选 = 字符串匹配.group(1)
                    if 候选 in 顶层包目录表:
                        依赖表.add(候选)
        except OSError:
            continue
    return 依赖表


def 阶段摘要(测试文件列表: list[Path], 依赖目录表: set[str]) -> str:
    """阶段缓存键：测试文件摘要 + 依赖目录摘要 + 验证引擎摘要 + Python 版本。"""
    摘要器 = hashlib.sha256()
    for 文件 in 测试文件列表:
        摘要器.update(str(文件).encode("utf-8"))
        摘要器.update(_文件摘要(文件).encode("utf-8"))
    for 目录名 in sorted(依赖目录表):
        摘要器.update(目录名.encode("utf-8"))
        摘要器.update(_目录摘要(系统根 / 目录名).encode("utf-8"))
    # 验证引擎（运行测试.py 自身 + 验证器/）变化 → 全部阶段缓存失效
    摘要器.update(_文件摘要(Path(__file__)).encode("utf-8"))
    # 测试装载与资源回收也属于验证引擎；缺失其摘要会在修改后复用旧证据。
    for 引擎文件 in (系统根 / "测试中心" / "__init__.py", 系统根 / "MCP工具箱" / "测试资源.py"):
        if 引擎文件.is_file():
            摘要器.update(str(引擎文件.relative_to(系统根)).encode("utf-8"))
            摘要器.update(_文件摘要(引擎文件).encode("utf-8"))
    if (系统根 / "验证器").is_dir():
        摘要器.update(_目录摘要(系统根 / "验证器").encode("utf-8"))
    摘要器.update(缓存结构版本.encode("utf-8"))
    摘要器.update(sys.version.split()[0].encode("utf-8"))
    return 摘要器.hexdigest()[:16]


def 运行环境摘要() -> str:
    """运行时、系统、依赖锁和外部程序不变时允许复用运行证据。"""
    摘要器 = hashlib.sha256()
    摘要器.update(sys.version.encode("utf-8"))
    摘要器.update(platform.platform().encode("utf-8"))
    摘要器.update(platform.machine().encode("utf-8"))
    # 定点收集依赖锁：支持库适配层各提供者 + 示例项目适配层，避免全仓扫描
    依赖锁路径表 = sorted(系统根.glob("支持库/适配层/*/依赖锁.json"))
    示例依赖锁 = 系统根 / "示例项目" / "适配层示例" / "依赖锁定.json"
    if 示例依赖锁.is_file():
        依赖锁路径表.append(示例依赖锁)
    for 路径 in 依赖锁路径表:
        if 路径.is_file():
            摘要器.update(str(路径.relative_to(系统根)).encode("utf-8"))
            摘要器.update(_文件摘要(路径).encode("utf-8"))
    for 程序 in (
        sys.executable, shutil.which("soffice"), shutil.which("tesseract"),
        shutil.which("ffmpeg"), shutil.which("ffprobe"), shutil.which("textutil"),
        shutil.which("docker"), shutil.which("psql"), shutil.which("security"),
        shutil.which("sw_vers"), shutil.which("git"), shutil.which("ps"),
        shutil.which("sleep"),
    ):
        if not 程序:
            continue
        路径 = Path(程序)
        try:
            状态 = 路径.stat()
        except OSError:
            continue
        摘要器.update(str(路径).encode("utf-8"))
        摘要器.update(f"{状态.st_size}:{状态.st_mtime_ns}".encode("utf-8"))
    return 摘要器.hexdigest()[:16]


def 阶段缓存可复用(
    阶段名: str, 缓存项: dict | None, 摘要: str, 环境摘要: str,
    *, 强制慢速: bool = False, 当前时间: float | None = None,
) -> bool:
    if not _缓存证据完整(缓存项) or 缓存项.get("摘要") != 摘要 or not 缓存项.get("成功"):
        return False
    if not 缓存项.get("测试数") or 缓存项.get("结构版本") != 缓存结构版本:
        return False
    if 阶段名 == "慢速层" and 强制慢速:
        return False
    # 环境摘要是缓存可信度的必要证据；缺失或不匹配一律不能复用。
    if 缓存项.get("环境摘要") != 环境摘要:
        return False
    if 阶段名 in 环境敏感阶段:
        记录时间 = float(缓存项.get("时间戳", 0))
        if (当前时间 or time.time()) - 记录时间 > 环境敏感缓存有效秒:
            return False
    return True


def 阶段缓存证据(阶段列表: list[tuple[str, list[str]]], 名称: str) -> tuple[bool, str]:
    """在验证锁被外层持有时，重新计算指定阶段缓存是否仍可信。

    嵌套发布门禁不能再次启动全量测试，但也不能把锁冲突当成成功；
    只有每个常规阶段的源码/依赖/环境摘要和成功证据都匹配，才允许
    发布门禁复用这份证据。
    """
    缓存 = 读取缓存()
    环境摘要 = 运行环境摘要()
    缺失或失效: list[str] = []
    for 阶段名, 匹配表 in 阶段列表:
        测试文件列表 = 收集阶段文件(匹配表)
        if not 测试文件列表:
            缺失或失效.append(f"{阶段名}:未发现测试文件")
            continue
        依赖目录表 = 阶段依赖目录表(测试文件列表)
        摘要 = 阶段摘要(测试文件列表, 依赖目录表)
        if not 阶段缓存可复用(阶段名, 缓存.get(阶段名), 摘要, 环境摘要):
            缺失或失效.append(阶段名)
    if 缺失或失效:
        return False, f"{名称}阶段证据缺失或失效: {', '.join(缺失或失效)}"
    return True, f"{名称}阶段 {len(阶段列表)} 项缓存证据已重新核对"


def 常规阶段缓存证据() -> tuple[bool, str]:
    return 阶段缓存证据(常规阶段顺序表, "常规")


def 全部阶段缓存证据() -> tuple[bool, str]:
    return 阶段缓存证据(常规阶段顺序表 + 慢速阶段顺序表, "全部")


def _文件缓存路径(测试文件: Path) -> Path:
    """文件级缓存路径：sha256(测试文件相对路径)[:16].json，位于 验证缓存/文件/。"""
    相对路径 = _仓库根相对路径(测试文件)
    键 = 相对路径 if 相对路径 else str(测试文件.resolve())
    名称 = hashlib.sha256(键.encode("utf-8")).hexdigest()[:16]
    return 验证文件缓存目录 / f"{名称}.json"


def 文件级摘要(测试文件: Path) -> str:
    """文件级缓存键：测试文件自身摘要 + 引擎摘要 + 缓存结构版本 + Python 版本。

    依赖文件单独存依赖摘要表，不并入本摘要（依赖变化只影响对应文件）。
    """
    摘要器 = hashlib.sha256()
    摘要器.update(_文件摘要(测试文件).encode("utf-8"))
    摘要器.update(_文件摘要(Path(__file__)).encode("utf-8"))
    摘要器.update(缓存结构版本.encode("utf-8"))
    摘要器.update(sys.version.split()[0].encode("utf-8"))
    return 摘要器.hexdigest()[:16]


def 读取文件级缓存(测试文件: Path) -> dict | None:
    """读取单测试文件的文件级缓存项；缺失或损坏返回 None。"""
    路径 = _文件缓存路径(测试文件)
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return 数据 if isinstance(数据, dict) else None


def 文件级缓存可复用(
    测试文件: Path, 缓存项: dict | None, 环境摘要: str,
    *, 当前时间: float | None = None,
) -> bool:
    """文件级缓存复用判定：成功 + 结构版本 + 测试文件摘要 + 环境摘要 + 依赖逐文件核对。

    依赖文件缺失或内容变化 → 不可复用；弱依赖标记缓存有效期 ≤ 弱依赖缓存有效秒。
    """
    if not _缓存证据完整(缓存项) or not 缓存项.get("成功"):
        return False
    if 缓存项.get("结构版本") != 缓存结构版本:
        return False
    if not 缓存项.get("测试数") or 缓存项.get("测试文件摘要") != 文件级摘要(测试文件):
        return False
    if 缓存项.get("环境摘要") != 环境摘要:
        return False
    if 缓存项.get("弱依赖标记"):
        记录时间 = float(缓存项.get("时间戳", 0))
        if (当前时间 or time.time()) - 记录时间 > 弱依赖缓存有效秒:
            return False
    for 相对路径, 存储摘要 in (缓存项.get("依赖摘要表") or {}).items():
        依赖文件 = Path(相对路径)
        if not 依赖文件.is_absolute():
            依赖文件 = 系统根 / 相对路径
        if not 依赖文件.is_file():
            return False
        if _文件摘要(依赖文件) != 存储摘要:
            return False
    # 目录扫描校验：测试依赖的目录清单变化（新增/删除/重命名直接子项）时缓存必须失效，防假绿
    for 目录名, 存储摘要 in (缓存项.get("目录摘要表") or {}).items():
        目录 = Path(目录名)
        if not 目录.is_absolute():
            目录 = 系统根 / 目录名
        if not 目录.is_dir():
            return False
        if _目录清单摘要(目录) != 存储摘要:
            return False
    return True


def 写入文件级缓存(测试文件: Path, 缓存项: dict) -> None:
    """写入文件级缓存项；临时文件 + os.replace 原子写。"""
    目标路径 = _文件缓存路径(测试文件)
    临时路径 = 目标路径.with_suffix(".json.tmp")
    目标路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径.write_text(json.dumps(缓存项, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(目标路径)


def 构建文件级缓存项(测试文件: Path, 环境摘要: str, 测试数: int) -> dict:
    """构建单测试文件成功证据；依赖按测试文件分别记录，禁止阶段聚合假绿。"""
    依赖目录集合 = 阶段依赖目录表([测试文件])
    依赖摘要表: dict[str, str] = {}
    for 目录名 in sorted(依赖目录集合):
        目录 = 系统根 / 目录名
        if not 目录.is_dir():
            continue
        # 目录摘要覆盖包内新增/删除文件，内容摘要由逐文件哈希完成。
        for 文件 in 目录.rglob("*"):
            if 文件.is_file() and "工程缓存" not in str(文件) and "__pycache__" not in str(文件):
                依赖摘要表[str(文件.relative_to(系统根))] = _文件摘要(文件)
    目录摘要表 = _构建目录摘要表(sorted(依赖目录集合))
    return {
        "结构版本": 缓存结构版本,
        "成功": True,
        "测试数": int(测试数),
        "测试文件摘要": 文件级摘要(测试文件),
        "环境摘要": 环境摘要,
        "依赖摘要表": 依赖摘要表,
        "目录摘要表": 目录摘要表,
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "时间戳": time.time(),
    }


def _解析单文件测试数(输出: str) -> int:
    """解析单文件门禁输出中的测试数。"""
    匹配 = re.search(r"单文件门禁通过：共 (\d+) 个测试", 输出)
    return int(匹配.group(1)) if 匹配 else 0


def 获取验证锁() -> bool:
    """获取全量验证互斥锁（flock 非阻塞）。已持有其他验证运行 → 返回 False。

    AGENTS.md 铁律"已有全量运行时禁止重复启动"代码化：全量验证（常规/慢速/全部）
    与环境敏感阶段共享端口/数据库/发布指针，并发运行会互相干扰。
    锁文件位于工程缓存（可删除、不污染正式目录）；POSIX flock 进程退出自动释放。
    """
    if fcntl is None:
        return True  # 非 POSIX 平台不强制互斥
    try:
        验证锁路径.parent.mkdir(parents=True, exist_ok=True)
        global _验证锁文件
        _验证锁文件 = open(验证锁路径, "w")
        fcntl.flock(_验证锁文件, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _验证锁文件.write(str(os.getpid()))
        _验证锁文件.flush()
        return True
    except OSError:
        try:
            _验证锁文件.close()
        except (OSError, NameError, AttributeError):
            pass
        return False


_验证锁文件 = None


def 释放验证锁() -> None:
    """释放验证锁（正常结束或异常路径都调用）。"""
    global _验证锁文件
    if _验证锁文件 is not None:
        try:
            fcntl.flock(_验证锁文件, fcntl.LOCK_UN)
        except (OSError, ValueError):
            pass
        try:
            _验证锁文件.close()
        except OSError:
            pass
        _验证锁文件 = None


def 读取缓存() -> dict:
    """聚合读取 验证缓存/*.json：每阶段一个文件，合并为 {阶段名: 缓存项}。"""
    if not 验证缓存目录.is_dir():
        return {}
    缓存: dict = {}
    for 路径 in sorted(验证缓存目录.glob("*.json")):
        try:
            缓存[路径.stem] = json.loads(路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return 缓存


def 写入缓存(缓存: dict) -> None:
    """按阶段名写入独立缓存文件；临时文件后 os.replace 保证原子写。"""
    for 阶段名, 缓存项 in 缓存.items():
        目标路径 = 验证缓存目录 / f"{阶段名}.json"
        临时路径 = 目标路径.with_suffix(".json.tmp")
        目标路径.parent.mkdir(parents=True, exist_ok=True)
        临时路径.write_text(json.dumps(缓存项, ensure_ascii=False, indent=2), encoding="utf-8")
        临时路径.replace(目标路径)


def 写入断点(范围: str, 阶段名: str, 阶段顺序表: list[tuple[str, list[str]]], 原因: str) -> None:
    断点文件路径.parent.mkdir(parents=True, exist_ok=True)
    数据 = {
        "范围": 范围, "失败阶段": 阶段名,
        "阶段列表": [名称 for 名称, _ in 阶段顺序表],
        "原因": 原因, "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "缓存结构版本": 缓存结构版本,
    }
    临时路径 = 断点文件路径.with_suffix(".json.tmp")
    临时路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(断点文件路径)


def 读取断点() -> dict:
    if not 断点文件路径.is_file():
        return {}
    try:
        数据 = json.loads(断点文件路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return 数据 if isinstance(数据, dict) else {}


def 清除断点() -> None:
    断点文件路径.unlink(missing_ok=True)


def 判断零测试(套件: unittest.TestSuite) -> bool:
    """零测试门禁：套件没有任何测试用例时返回 True（应失败）。"""
    return 套件.countTestCases() == 0


def 判断导入失败(结果: unittest.TestResult) -> bool:
    """导入失败门禁：失败用例中存在导入失败（FunctionTestCase）时返回 True。"""
    for 失败 in 结果.failures:
        测试, 追踪 = 失败
        if type(测试).__name__ == "FunctionTestCase":
            return True
    return False


def 判断存在跳过(结果: unittest.TestResult) -> bool:
    """跳过门禁：任何未执行场景都不得计入验证成功。"""
    if not 结果.skipped:
        return False
    for 测试, 原因 in 结果.skipped:
        print(f"跳过门禁失败：{测试} 未执行，原因：{原因}")
    return True


def 执行测试套件(套件: unittest.TestSuite, 名称: str = "定向") -> int:
    """使用统一门禁执行一个明确套件。"""
    if 判断零测试(套件):
        print(f"{名称}门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）")
        return 1
    print(f"--- {名称}验证（{套件.countTestCases()} 个测试）---")
    结果 = unittest.TextTestRunner(verbosity=1).run(套件)
    if not 结果.wasSuccessful() or 判断导入失败(结果) or 判断存在跳过(结果):
        return 1
    print(f"{名称}门禁通过：共 {套件.countTestCases()} 个测试全部成功")
    return 0


def _目录清单摘要(目录: Path) -> str:
    """目录浅层清单摘要：只列直接子项的名称与类型，不做递归。

    用于文件级缓存的目录扫描校验——新增/删除/重命名直接子项即失效，
    子项内容变化由 依赖摘要表 的文件级校验捕获，避免递归 rglob 的开销。
    """
    摘要器 = hashlib.sha256()
    try:
        子项表 = sorted(目录.iterdir(), key=lambda 路径: 路径.name)
    except OSError:
        return ""
    for 子项 in 子项表:
        摘要器.update(子项.name.encode("utf-8"))
        摘要器.update(b"/" if 子项.is_dir() else b"F")
    return 摘要器.hexdigest()[:16]


def _构建目录摘要表(目录列表: list[str]) -> dict[str, str]:
    """把扫描过的目录转成 {相对路径: 浅层清单摘要}。

    目录数量超上限时降级为仅标记（返回空表），由调用方按弱依赖处理——
    全仓扫描型测试（组件合规等）扫描数百目录，逐一递归摘要开销爆炸且必然失效。
    """
    if len(目录列表) > 目录摘要上限:
        raise RuntimeError(
            f"目录摘要数量 {len(目录列表)} 超过上限 {目录摘要上限}，"
            "拒绝使用不完整摘要进入缓存"
        )
    目录摘要表: dict[str, str] = {}
    for 相对路径 in 目录列表:
        目录 = Path(相对路径)
        if not 目录.is_absolute():
            目录 = 系统根 / 相对路径
        try:
            目录.resolve().relative_to(系统根)
        except ValueError:
            continue
        if not 目录.is_dir():
            continue
        try:
            key = str(目录.relative_to(系统根))
        except ValueError:
            key = str(目录)
        目录摘要表[key] = _目录清单摘要(目录)
    return 目录摘要表


def 加载指定测试文件(路径表: list[str]) -> unittest.TestSuite:
    """工作包快速验证：只加载显式指定的测试文件。"""
    套件 = unittest.TestSuite()
    加载器 = unittest.TestLoader()
    for 序号, 原路径 in enumerate(路径表):
        路径 = Path(原路径)
        if not 路径.is_absolute():
            路径 = 系统根 / 路径
        路径 = 路径.resolve()
        if not 路径.is_relative_to(测试中心.测试中心目录.resolve()):
            raise ValueError(f"测试文件必须位于测试中心: {原路径}")
        if not 路径.is_file() or 路径.suffix != ".py" or not 路径.name.startswith("测试_"):
            raise ValueError(f"不是有效测试文件: {原路径}")
        模块 = 测试中心.加载测试模块(路径, 序号)
        套件.addTests(加载器.loadTestsFromModule(模块))
    return 套件


def 全局并发数() -> int:
    """全局并发预算：主进程唯一并发规模（None 兜底为 4）。"""
    return max(1, os.cpu_count() or 4)


def 计算并行数(文件数: int, 请求并行数: int) -> int:
    """0 表示自动；并发有界，避免测试调度反向冲垮机器。"""
    if 文件数 <= 1:
        return 1
    if 请求并行数 < 0:
        raise ValueError("并行数不能小于0")
    上限 = 全局并发数()
    return min(文件数, 请求并行数 or 上限)


def _生成任务id() -> str:
    """8位短任务id（一次工作包运行的唯一标识）。"""
    return uuid.uuid4().hex[:8]


def _生成工作区标识(任务id: str, 序号: int) -> str:
    """工作区标识：目录名含任务id与工作包序号语义。"""
    return f"工作包-{任务id}-{序号}"


def _输出文本(内容: object) -> str:
    """子进程输出统一转文本（兼容 bytes 与 str）。"""
    if isinstance(内容, bytes):
        return 内容.decode("utf-8", errors="replace")
    return 内容 or ""


def _写清理失败证据(任务id: str, 路径: str, 失败原因: str) -> Path:
    """清理失败必须留证据：工程缓存/清理失败证据/{任务id}.json。"""
    证据目录 = 清理失败证据目录
    证据目录.mkdir(parents=True, exist_ok=True)
    证据 = {
        "运行id": 任务id,
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "路径": str(路径),
        "失败原因": 失败原因,
    }
    证据路径 = 证据目录 / f"{任务id}.json"
    临时路径 = 证据路径.with_suffix(".json.tmp")
    临时路径.write_text(json.dumps(证据, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(证据路径)
    return 证据路径


def _终止进程组(进程: subprocess.Popen) -> None:
    """超时后终止子进程整个进程组（含孙进程），先温柔后强杀。"""
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        进程.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # SIGKILL 后也必须有界等待；异常子孙进程可能仍持有 stdout/stderr
        # 管道，不能让门禁在这里无限阻塞。
        try:
            进程.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 无法回收时交给调用方记录超时/清理失败证据，不再无限等待。
            pass


def _清理工作包临时根(
    任务id: str, 工作目录: Path, 资源清单路径: Path, 工作包路径: str,
) -> dict[str, object]:
    """工作包 teardown：清理登记资源、迁移保留物、删除临时根目录。

    任何一步失败都必须写证据并返回失败（门禁不允许静默忽略清理异常）。
    只清理登记且位于临时根目录内的资源；保留物迁移到
    工程缓存/保留制品/{任务id}/ 后再整体删除临时根目录。
    """
    try:
        保留路径表: list[Path] = []
        if 资源清单路径.is_file():
            for 行 in 资源清单路径.read_text(encoding="utf-8").splitlines():
                try:
                    记录 = json.loads(行)
                except json.JSONDecodeError as 错误:
                    raise ValueError(f"资源清单包含非法 JSON：{错误}") from 错误
                if not isinstance(记录, dict):
                    raise ValueError("资源清单记录必须是对象")
                if 记录.get("保留"):
                    if not 记录.get("路径"):
                        raise ValueError("保留资源记录缺少路径")
                    保留路径表.append(Path(str(记录["路径"])).resolve())
        清理结果 = 测试资源.清理资源(
            资源清单路径, 临时根目录=工作目录,
            证据目录=清理失败证据目录, work_id=任务id,
        )
        if not isinstance(清理结果, dict) or not 清理结果.get("成功"):
            失败表 = 清理结果.get("失败表", []) if isinstance(清理结果, dict) else []
            raise RuntimeError(f"工作包资源清理失败：{失败表[:5]}")
        for 保留路径 in 保留路径表:
            if not 保留路径.exists():
                continue
            保留目录 = 保留制品目录 / 任务id
            保留目录.mkdir(parents=True, exist_ok=True)
            目标 = 保留目录 / 保留路径.name
            if 目标.is_dir():
                shutil.rmtree(目标, ignore_errors=True)
            else:
                目标.unlink(missing_ok=True)
            shutil.move(str(保留路径), str(目标))
        if 工作目录.exists():
            shutil.rmtree(工作目录)
    except Exception as 异常:
        失败原因 = f"{type(异常).__name__}: {异常}"
        证据路径 = _写清理失败证据(任务id, str(工作包路径), 失败原因)
        return {
            "成功": False, "失败原因": 失败原因,
            "证据路径": str(证据路径), "保留数": 0,
        }
    return {"成功": True, "失败原因": "", "证据路径": "", "保留数": len(保留路径表)}


def _运行单文件子进程(
    路径: str, 任务id: str, 序号: int, *, 超时秒: int = 600,
) -> dict[str, object]:
    """运行单个工作包子进程；独立临时根目录与 teardown 保证。"""
    # 发布门禁可通过环境变量收紧默认工作包预算；调用方显式传入的
    # 超时（例如超时回收自检的 2 秒）必须优先，不能被外层环境覆盖。
    if 超时秒 == 600:
        try:
            超时秒 = max(1, int(os.environ.get("系统底座_工作包超时秒", str(超时秒))))
        except (TypeError, ValueError):
            超时秒 = max(1, 超时秒)
    else:
        超时秒 = max(1, 超时秒)
    工作区标识 = _生成工作区标识(任务id, 序号)
    工作目录 = 运行根目录 / 任务id / 工作区标识
    工作目录.mkdir(parents=True, exist_ok=True)
    资源清单路径 = 工作目录 / "资源清单.jsonl"
    环境 = os.environ.copy()
    环境["TMPDIR"] = str(工作目录)
    环境["系统底座_验证运行id"] = 任务id
    环境["系统底座_任务id"] = 任务id
    环境["系统底座_工作区标识"] = 工作区标识
    环境["系统底座_资源清单路径"] = str(资源清单路径)
    环境["系统底座_并行数"] = os.environ.get("系统底座_并行数", "8")
    结果: dict[str, object] = {
        "路径": 路径, "退出码": 2, "标准输出": "", "标准错误": "",
    }
    进程: subprocess.Popen | None = None
    try:
        进程 = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--内部测试文件", 路径],
            cwd=系统根, env=环境, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            标准输出, 标准错误 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired as 错误:
            _终止进程组(进程)
            try:
                进程.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                # 管道仍被异常后代持有时主动关闭父端，确保工作包返回。
                for 流 in (进程.stdout, 进程.stderr):
                    if 流 is not None:
                        try:
                            流.close()
                        except OSError:
                            pass
            结果 = {
                "路径": 路径, "退出码": 124,
                "标准输出": _输出文本(错误.stdout)[-8000:],
                "标准错误": "单文件验证超过指定时限，已终止（进程组已清理）",
            }
        else:
            结果 = {
                "路径": 路径, "退出码": 进程.returncode,
                "标准输出": _输出文本(标准输出)[-8000:],
                "标准错误": _输出文本(标准错误)[-4000:],
            }
    finally:
        # 正常结束、失败、超时中断或异常都必须执行 teardown
        清理结果 = _清理工作包临时根(任务id, 工作目录, 资源清单路径, 路径)
        结果["临时根目录"] = str(工作目录)
        结果["工作区标识"] = 工作区标识
        结果["资源清单路径"] = str(资源清单路径)
        if not 清理结果["成功"]:
            结果["清理失败"] = True
            结果["清理失败原因"] = 清理结果["失败原因"]
            结果["清理失败证据路径"] = 清理结果["证据路径"]
            if 结果.get("退出码", 0) == 0:
                结果["退出码"] = 125
    return 结果


def 并行执行指定测试文件(路径表: list[str], 并行数: int) -> int:
    """工作包多文件并行；每个文件独立进程、独立临时根与 teardown。"""
    实际并行 = 计算并行数(len(路径表), 并行数)
    if 实际并行 == 1:
        return 执行测试套件(加载指定测试文件(路径表), "工作包")
    任务id = _生成任务id()
    结果表: list[dict[str, object]] = []
    父级清理失败表: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=实际并行) as 池:
            任务表 = {
                池.submit(_运行单文件子进程, 路径, 任务id, 序号): 路径
                for 序号, 路径 in enumerate(路径表)
            }
            for 任务 in as_completed(任务表):
                结果表.append(任务.result())
    finally:
        # 工作区各自 teardown 后，兜底删除运行根目录残留
        运行根 = 运行根目录 / 任务id
        if 运行根.exists():
            try:
                shutil.rmtree(运行根)
            except Exception as 异常:
                证据路径 = _写清理失败证据(
                    任务id, str(运行根), f"{type(异常).__name__}: {异常}",
                )
                父级清理失败表.append(str(证据路径))
    失败表 = [结果 for 结果 in 结果表 if 结果["退出码"] != 0]
    清理失败项 = [结果 for 结果 in 结果表 if 结果.get("清理失败")]
    for 结果 in sorted(结果表, key=lambda 项: str(项["路径"])):
        print(f"--- 工作包文件：{结果['路径']}（退出码={结果['退出码']}）---")
        if 结果["退出码"] != 0:
            print(结果["标准输出"])
            print(结果["标准错误"], file=sys.stderr)
    for 结果 in 清理失败项:
        print(
            f"清理失败证据：{结果['清理失败证据路径']}"
            f"（原因：{结果['清理失败原因']}）",
            file=sys.stderr,
        )
    for 证据路径 in 父级清理失败表:
        print(f"清理失败证据：{证据路径}", file=sys.stderr)
    if 失败表 or 清理失败项 or 父级清理失败表:
        print(f"工作包并行门禁失败：{len(失败表)}/{len(结果表)} 个文件失败")
        return 1
    print(f"工作包并行门禁通过：{len(结果表)} 个文件，并行数 {实际并行}")
    return 0


def 筛选阶段(
    阶段顺序表: list[tuple[str, list[str]]], 指定阶段: list[str],
) -> list[tuple[str, list[str]]]:
    """波次验证：保持固定顺序，仅选择明确受影响阶段。"""
    可用阶段 = {名称 for 名称, _ in 阶段顺序表}
    未知阶段 = sorted(set(指定阶段) - 可用阶段)
    if 未知阶段:
        raise ValueError(f"未知验证阶段: {', '.join(未知阶段)}")
    目标 = set(指定阶段)
    return [阶段 for 阶段 in 阶段顺序表 if 阶段[0] in 目标]


def 计算断点续跑阶段(
    阶段顺序表: list[tuple[str, list[str]]], 断点: dict,
    缓存: dict, 环境摘要: str, 强制慢速: bool,
) -> list[tuple[str, list[str]]]:
    """从失败阶段继续；更早阶段证据失效时自动回退。"""
    记录阶段 = 断点.get("阶段列表", [])
    if 记录阶段:
        阶段顺序表 = [阶段 for 阶段 in 阶段顺序表 if 阶段[0] in 记录阶段]
    名称表 = [名称 for 名称, _ in 阶段顺序表]
    失败阶段 = str(断点.get("失败阶段", ""))
    if 失败阶段 not in 名称表:
        raise ValueError(f"断点失败阶段不存在: {失败阶段}")
    起点 = 名称表.index(失败阶段)
    for 序号, (阶段名, 匹配表) in enumerate(阶段顺序表[:起点]):
        阶段文件 = 收集阶段文件(匹配表)
        if not 阶段文件:
            起点 = 序号
            break
        依赖目录表 = 阶段依赖目录表(阶段文件)
        摘要 = 阶段摘要(阶段文件, 依赖目录表)
        if not 阶段缓存可复用(
            阶段名, 缓存.get(阶段名), 摘要, 环境摘要,
            强制慢速=强制慢速,
        ):
            起点 = 序号
            break
    return 阶段顺序表[起点:]


def 审计工程缓存正式实现引用() -> list[str]:
    """正式测试不得把工程缓存中的候选代码当作生产实现。

    本文件自身包含门禁标记定义，必须排除自身（审计逻辑不属于引用）。
    """
    违规文件: list[str] = []
    标记表 = (
        "工程缓存.第十四阶段",
        '"工程缓存" / "第十四阶段"',
        "'工程缓存' / '第十四阶段'",
    )
    for 文件 in sorted(测试中心.测试中心目录.rglob("*.py")):
        if 文件.resolve() == Path(__file__).resolve():
            continue
        try:
            文本 = 文件.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(标记 in 文本 for 标记 in 标记表):
            违规文件.append(str(文件.relative_to(系统根)))
    return 违规文件


def _阶段序号(阶段名: str) -> int:
    """阶段在常规顺序表中的固定序号（用于测试模块唯一命名）。"""
    for 序号, (名, _) in enumerate(常规阶段顺序表, start=1):
        if 名 == 阶段名:
            return 序号
    return 0


def _登记阶段进程(阶段名: str, 进程: subprocess.Popen | None) -> None:
    """登记/注销阶段子进程（供并行批失败时统一终止）。"""
    with _阶段进程锁:
        if 进程 is None:
            _阶段进程登记表.pop(阶段名, None)
        else:
            _阶段进程登记表[阶段名] = 进程


def _终止全部阶段进程() -> None:
    """终止所有 in-flight 阶段子进程（并行批失败时触发）。"""
    with _阶段进程锁:
        进程表 = list(_阶段进程登记表.values())
    for 进程 in 进程表:
        _终止进程组(进程)


def _解析文件测试数(输出: str) -> int:
    """从单文件子进程输出解析 '文件测试数：N' 标记行。"""
    for 行 in 输出.splitlines():
        if 行.startswith("文件测试数："):
            try:
                return int(行.split("：", 1)[1])
            except ValueError:
                return 0
    return 0


def _解析文件依赖摘要表(输出: str) -> dict:
    """从单文件子进程输出解析 '文件依赖摘要表：{json}' 标记行。"""
    for 行 in 输出.splitlines():
        if 行.startswith("文件依赖摘要表："):
            try:
                数据 = json.loads(行.split("：", 1)[1])
            except (json.JSONDecodeError, ValueError):
                return {}
            return 数据 if isinstance(数据, dict) else {}
    return {}


def _解析文件布尔标记(输出: str, 前缀: str) -> bool:
    """从单文件子进程输出解析 '前缀：True/False' 标记行。"""
    for 行 in 输出.splitlines():
        if 行.startswith(前缀):
            return 行.split("：", 1)[1].strip() == "True"
    return False


def _解析阶段测试数(输出: str) -> int:
    """从阶段子进程输出解析 '阶段测试数：N' 标记行。"""
    for 行 in 输出.splitlines():
        if 行.startswith("阶段测试数："):
            try:
                return int(行.split("：", 1)[1])
            except ValueError:
                return 0
    return 0


def _解析阶段失败原因(输出: str) -> str:
    """从阶段子进程输出解析 '阶段失败原因：XXX' 标记行。"""
    for 行 in 输出.splitlines():
        if 行.startswith("阶段失败原因："):
            return 行.split("：", 1)[1].strip()
    return "测试失败"


def _阶段真实失败(结果: dict[str, object]) -> bool:
    """真实失败判定：任何非零退出码都是真实失败。"""
    退出码 = int(结果.get("退出码", 0))
    return 退出码 != 0


def _运行阶段子进程(
    阶段名: str, 任务id: str, 序号: int, *, 超时秒: int = 3600,
) -> dict[str, object]:
    """运行单个阶段子进程；独立临时根目录与 teardown 保证。

    并行阶段批内每个阶段独立子进程，输出全部捕获后由父进程按
    阶段顺序统一回放；子进程只写自己的 {阶段名}.json 缓存文件，
    与其它并行子进程天然无冲突。
    """
    工作区标识 = f"阶段-{任务id}-{序号}"
    工作目录 = 运行根目录 / 任务id / 工作区标识
    工作目录.mkdir(parents=True, exist_ok=True)
    资源清单路径 = 工作目录 / "资源清单.jsonl"
    环境 = os.environ.copy()
    环境["TMPDIR"] = str(工作目录)
    环境["系统底座_验证运行id"] = 任务id
    环境["系统底座_任务id"] = 任务id
    环境["系统底座_工作区标识"] = 工作区标识
    环境["系统底座_资源清单路径"] = str(资源清单路径)
    结果: dict[str, object] = {
        "阶段名": 阶段名, "退出码": 2, "标准输出": "", "标准错误": "",
        "测试数": 0, "失败原因": "测试失败",
    }
    进程: subprocess.Popen | None = None
    try:
        进程 = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve()), "--内部阶段", 阶段名],
            cwd=系统根, env=环境, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        _登记阶段进程(阶段名, 进程)
        try:
            标准输出, 标准错误 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired as 错误:
            _终止进程组(进程)
            结果 = {
                "阶段名": 阶段名, "退出码": 124,
                "标准输出": _输出文本(错误.stdout)[-8000:],
                "标准错误": "阶段验证超过指定时限，已终止（进程组已清理）",
                "测试数": 0, "失败原因": "超时",
            }
        else:
            输出 = _输出文本(标准输出)
            结果 = {
                "阶段名": 阶段名, "退出码": 进程.returncode,
                "标准输出": 输出[-500000:],
                "标准错误": _输出文本(标准错误)[-500000:],
                "测试数": _解析阶段测试数(输出),
                "失败原因": _解析阶段失败原因(输出),
            }
    finally:
        _登记阶段进程(阶段名, None)
        # 正常结束、失败、超时中断或异常都必须执行 teardown
        清理结果 = _清理工作包临时根(任务id, 工作目录, 资源清单路径, f"阶段:{阶段名}")
        结果["临时根目录"] = str(工作目录)
        结果["工作区标识"] = 工作区标识
        结果["资源清单路径"] = str(资源清单路径)
        if not 清理结果["成功"]:
            结果["清理失败"] = True
            结果["清理失败原因"] = 清理结果["失败原因"]
            结果["清理失败证据路径"] = 清理结果["证据路径"]
            if 结果.get("退出码", 0) == 0:
                结果["退出码"] = 125
    return 结果


def _回放阶段输出(
    阶段批: list[tuple[str, list[str]]],
    结果按阶段: dict[str, dict[str, object]], 任务id: str,
) -> None:
    """每阶段独立输出文件，全部结束后按阶段顺序回放。"""
    输出目录 = 运行根目录 / 任务id
    输出目录.mkdir(parents=True, exist_ok=True)
    for 阶段名, _ in 阶段批:
        结果 = 结果按阶段[阶段名]
        输出路径 = 输出目录 / f"阶段输出-{阶段名}.txt"
        try:
            输出路径.write_text(
                str(结果["标准输出"]) + "\n" + str(结果["标准错误"]),
                encoding="utf-8",
            )
        except OSError as 异常:
            print(f"阶段输出写入失败：{阶段名}（{异常}）", file=sys.stderr)
    for 阶段名, _ in 阶段批:
        结果 = 结果按阶段[阶段名]
        退出码 = int(结果.get("退出码", 0))
        print(f"--- 阶段回放：{阶段名}（退出码={退出码}）---")
        print(str(结果["标准输出"]), end="")
        if 退出码 != 0:
            print(str(结果["标准错误"]), file=sys.stderr)


def _并行执行阶段批(
    阶段批: list[tuple[str, list[str]]], 任务id: str, 并行数: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """并行执行阶段批；任一阶段失败立即终止其余并取消未启动任务。

    返回 (结果表按阶段原顺序, 清理失败项表)。
    """
    实际并行 = 计算并行数(len(阶段批), 并行数)
    结果按阶段: dict[str, dict[str, object]] = {}
    父级清理失败表: list[str] = []
    失败触发 = False
    try:
        原并行数 = os.environ.get("系统底座_并行数")
        os.environ["系统底座_并行数"] = str(并行数)
        with ThreadPoolExecutor(max_workers=实际并行) as 池:
            任务表 = {
                池.submit(_运行阶段子进程, 阶段名, 任务id, 序号): 阶段名
                for 序号, (阶段名, _) in enumerate(阶段批)
            }
            print("阶段并行已启动：" + "、".join(任务表.values()), flush=True)
            for 任务 in as_completed(任务表):
                try:
                    结果 = 任务.result()
                except Exception as 异常:
                    阶段名 = 任务表[任务]
                    结果 = {
                        "阶段名": 阶段名, "退出码": 126,
                        "标准输出": "", "标准错误": (
                            f"阶段子进程启动异常：{type(异常).__name__}: {异常}"
                        ),
                        "测试数": 0, "失败原因": "启动异常",
                    }
                if not 失败触发 and 结果.get("退出码", 0) != 0:
                    失败触发 = True
                    _终止全部阶段进程()
                    for 其他任务 in 任务表:
                        其他任务.cancel()
                结果按阶段[结果["阶段名"]] = 结果
                print(
                    f"阶段并行已完成：{结果['阶段名']}（退出码={结果.get('退出码', 1)}）",
                    flush=True,
                )
        # 全部结束：写每阶段独立输出文件 + 按阶段顺序回放
        _回放阶段输出(阶段批, 结果按阶段, 任务id)
    finally:
        # 兜底终止残留阶段进程，再删除运行根目录残留
        _终止全部阶段进程()
        if 原并行数 is None:
            os.environ.pop("系统底座_并行数", None)
        else:
            os.environ["系统底座_并行数"] = 原并行数
        运行根 = 运行根目录 / 任务id
        if 运行根.exists():
            try:
                shutil.rmtree(运行根)
            except Exception as 异常:
                证据路径 = _写清理失败证据(
                    任务id, str(运行根), f"{type(异常).__name__}: {异常}",
                )
                父级清理失败表.append(str(证据路径))
    结果表 = [结果按阶段[阶段名] for 阶段名, _ in 阶段批]
    清理失败项表 = [结果 for 结果 in 结果表 if 结果.get("清理失败")]
    for 证据路径 in 父级清理失败表:
        print(f"清理失败证据：{证据路径}", file=sys.stderr)
    return 结果表, 清理失败项表


def _处理阶段并行批(
    阶段批: list[tuple[str, list[str]]], 任务id: str,
    缓存: dict, 环境摘要: str, 并行数: int,
    总测试数: int, 复用阶段数: int, 真实失败表: list[str],
    清理失败表: list[dict[str, object]],
) -> tuple[int, int, list[str], list[dict[str, object]]]:
    """并行批处理：缓存检查剔除命中阶段 + 并行执行 + 统计。"""
    # 1. 缓存检查，命中阶段直接从缓存计数
    待运行: list[tuple[str, list[str]]] = []
    for 阶段名, 匹配表 in 阶段批:
        阶段文件 = 收集阶段文件(匹配表)
        if not 阶段文件:
            print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试文件")
            真实失败表.append(阶段名)
            continue
        依赖目录表 = 阶段依赖目录表(阶段文件)
        摘要 = 阶段摘要(阶段文件, 依赖目录表)
        缓存项 = 缓存.get(阶段名)
        if 阶段缓存可复用(阶段名, 缓存项, 摘要, 环境摘要):
            print(
                f"--- 阶段：{阶段名}（缓存命中，复用 "
                f"{缓存项.get('测试数')} 个测试已验证证据）---",
            )
            总测试数 += 缓存项.get("测试数", 0)
            复用阶段数 += 1
        else:
            待运行.append((阶段名, 匹配表))
    # 2. 并行执行未命中阶段（失败/被终止阶段不写成功缓存）
    if not 待运行:
        return 总测试数, 复用阶段数, 真实失败表, 清理失败表
    结果表, 批清理失败表 = _并行执行阶段批(待运行, 任务id, 并行数)
    清理失败表.extend(批清理失败表)
    for 结果 in 结果表:
        if 结果.get("退出码", 0) != 0 and _阶段真实失败(结果):
            真实失败表.append(str(结果["阶段名"]))
    # 3. 统计成功阶段测试数：优先读最新缓存（子进程已写入）
    新缓存 = 读取缓存()
    缓存.update(新缓存)
    结果按阶段 = {str(结果["阶段名"]): 结果 for 结果 in 结果表}
    for 阶段名, _ in 待运行:
        缓存项 = 新缓存.get(阶段名)
        if 缓存项 and 缓存项.get("成功"):
            总测试数 += 缓存项.get("测试数", 0)
        else:
            结果 = 结果按阶段.get(阶段名)
            if 结果 and 结果.get("退出码", 0) == 0:
                总测试数 += int(结果.get("测试数", 0))
    return 总测试数, 复用阶段数, 真实失败表, 清理失败表


def _执行单个阶段串行(
    阶段名: str, 匹配表: list[str], 范围: str,
    断点阶段顺序表: list[tuple[str, list[str]]],
    缓存: dict, 环境摘要: str, 强制慢速: bool,
) -> tuple[int, int, bool, dict]:
    """逐测试文件执行阶段；未变文件复用独立证据，不再按阶段整体重跑。"""
    阶段文件 = 收集阶段文件(匹配表)
    if not 阶段文件:
        print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试文件")
        写入断点(范围, 阶段名, 断点阶段顺序表, "未发现测试文件")
        return 1, 0, False, 缓存
    任务id = _生成任务id()
    总测试数 = 0
    执行数 = 0
    复用数 = 0
    阶段失败 = False
    # 非环境敏感阶段的测试文件彼此使用独立临时根，可并行拉起，避免
    # 50 个静态契约文件逐个创建 Python 进程。敏感阶段仍严格保持串行。
    待运行文件: list[Path] = []
    for 测试文件 in 阶段文件:
        文件缓存 = 读取文件级缓存(测试文件)
        if 文件级缓存可复用(测试文件, 文件缓存, 环境摘要):
            测试数 = int(文件缓存.get("测试数", 0))
            总测试数 += 测试数
            复用数 += 1
            print(f"--- 测试文件：{测试文件}（缓存命中，复用 {测试数} 个测试）---")
            continue
        待运行文件.append(测试文件)

    if (阶段名 not in 环境敏感阶段 and len(待运行文件) > 1
            and int(os.environ.get("系统底座_并行数", "0") or 0) != 1):
        实际并行 = 计算并行数(
            len(待运行文件), int(os.environ.get("系统底座_并行数", "0") or 0)
        )
        # 共享外部工具（LibreOffice/FFmpeg/Tesseract/textutil 等）的文件必须
        # 进程级互斥：同一外部工具共享 profile/临时目录，并发会互相锁死
        # （如 LibreOffice 并发 --convert-to 出现静默退出但不出文件）。
        # 与 _执行内部阶段子进程 保持同一调度逻辑。
        并行文件 = [文件 for 文件 in 待运行文件 if not _文件使用共享外部工具(文件)]
        串行文件 = [文件 for 文件 in 待运行文件 if 文件 not in 并行文件]
        并行结果: list[dict[str, object]] = []
        if 并行文件:
            with ThreadPoolExecutor(max_workers=实际并行) as 池:
                任务表 = {
                    池.submit(_运行单文件子进程, str(文件), 任务id, 序号): 文件
                    for 序号, 文件 in enumerate(并行文件)
                }
                并行结果 = [任务.result() for 任务 in as_completed(任务表)]
        # 外部工具文件在并行批结束后按原顺序执行，保持其进程级互斥。
        for 序号, 文件 in enumerate(串行文件, start=len(并行文件)):
            并行结果.append(_运行单文件子进程(str(文件), 任务id, 序号))
        for 结果 in sorted(并行结果, key=lambda 项: str(项.get("路径", ""))):
            测试文件 = Path(str(结果["路径"]))
            输出 = str(结果.get("标准输出", ""))
            if int(结果.get("退出码", 1)) != 0 or 结果.get("清理失败"):
                print(f"阶段门禁失败：{阶段名} / {测试文件}")
                print(输出)
                if 结果.get("标准错误"):
                    print(结果["标准错误"], file=sys.stderr)
                写入断点(范围, 阶段名, 断点阶段顺序表, "测试文件失败")
                return 1, 0, False, 缓存
            测试数 = _解析单文件测试数(输出)
            if 测试数 <= 0:
                print(f"阶段门禁失败：{测试文件} 未报告有效测试数")
                写入断点(范围, 阶段名, 断点阶段顺序表, "零测试或输出不完整")
                return 1, 0, False, 缓存
            写入文件级缓存(测试文件, 构建文件级缓存项(测试文件, 环境摘要, 测试数))
            总测试数 += 测试数
            执行数 += 1
        依赖目录表 = 阶段依赖目录表(阶段文件)
        摘要 = 阶段摘要(阶段文件, 依赖目录表)
        缓存[阶段名] = _补齐缓存证据({
            "摘要": 摘要, "成功": True, "测试数": 总测试数,
            "结构版本": 缓存结构版本, "按文件缓存": True,
            "文件数": len(阶段文件), "执行文件数": 执行数, "复用文件数": 复用数,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "时间戳": time.time(), "环境摘要": 环境摘要,
        })
        写入缓存(缓存)
        print(f"--- 阶段：{阶段名}（{总测试数} 个测试，文件并行 {实际并行}）---")
        return 0, 总测试数, bool(执行数 == 0), 缓存

    for 序号, 测试文件 in enumerate(待运行文件):
        结果 = _运行单文件子进程(str(测试文件), 任务id, 序号)
        输出 = str(结果.get("标准输出", ""))
        if int(结果.get("退出码", 1)) != 0 or 结果.get("清理失败"):
            print(f"阶段门禁失败：{阶段名} / {测试文件}")
            print(输出)
            if 结果.get("标准错误"):
                print(结果["标准错误"], file=sys.stderr)
            写入断点(范围, 阶段名, 断点阶段顺序表, "测试文件失败")
            阶段失败 = True
            break
        测试数 = _解析单文件测试数(输出)
        if 测试数 <= 0:
            print(f"阶段门禁失败：{测试文件} 未报告有效测试数")
            写入断点(范围, 阶段名, 断点阶段顺序表, "零测试或输出不完整")
            阶段失败 = True
            break
        写入文件级缓存(测试文件, 构建文件级缓存项(测试文件, 环境摘要, 测试数))
        总测试数 += 测试数
        执行数 += 1
    if 阶段失败:
        return 1, 0, False, 缓存
    依赖目录表 = 阶段依赖目录表(阶段文件)
    摘要 = 阶段摘要(阶段文件, 依赖目录表)
    缓存[阶段名] = _补齐缓存证据({
        "摘要": 摘要, "成功": True, "测试数": 总测试数,
        "结构版本": 缓存结构版本, "按文件缓存": True,
        "文件数": len(阶段文件), "执行文件数": 执行数, "复用文件数": 复用数,
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "时间戳": time.time(), "环境摘要": 环境摘要,
    })
    写入缓存(缓存)
    print(f"--- 阶段：{阶段名}（{总测试数} 个测试，执行 {执行数} 个文件，复用 {复用数} 个文件）---")
    return 0, 总测试数, bool(执行数 == 0), 缓存


def 执行内部阶段子进程(阶段名: str) -> int:
    """--内部阶段 入口：子进程内只执行一个阶段（不写断点，只写自己阶段缓存）。"""
    加载器 = unittest.TestLoader()
    匹配表 = None
    for 名, 表 in 常规阶段顺序表 + 慢速阶段顺序表:
        if 名 == 阶段名:
            匹配表 = 表
            break
    if 匹配表 is None:
        return 2
    缓存 = 读取缓存()
    环境摘要 = 运行环境摘要()
    阶段文件 = 收集阶段文件(匹配表)
    if not 阶段文件:
        print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试文件")
        print("阶段失败原因：未发现测试文件")
        return 1
    依赖目录表 = 阶段依赖目录表(阶段文件)
    摘要 = 阶段摘要(阶段文件, 依赖目录表)
    缓存项 = 缓存.get(阶段名)
    if 阶段缓存可复用(阶段名, 缓存项, 摘要, 环境摘要):
        print(
            f"--- 阶段：{阶段名}（缓存命中，复用 "
            f"{缓存项.get('测试数')} 个测试已验证证据）---",
        )
        print(f"阶段测试数：{缓存项.get('测试数', 0)}")
        return 0
    # 阶段批并行时，阶段内部也必须并行消费未命中的测试文件；否则最慢
    # 的一个阶段仍会把整个发布门禁拖成串行。仅对已声明为非环境敏感的
    # 阶段启用，且每个阶段最多 8 个子进程，避免 8 个阶段叠加后无限扩张。
    请求并行 = int(os.environ.get("系统底座_并行数", "1") or 1)
    if 阶段名 not in 环境敏感阶段 and 请求并行 > 1 and len(阶段文件) > 1:
        并行度 = min(8, 请求并行, len(阶段文件))
        任务id = _生成任务id()
        结果表: list[dict[str, object]] = []
        并行文件 = [文件 for 文件 in 阶段文件 if not _文件使用共享外部工具(文件)]
        串行文件 = [文件 for 文件 in 阶段文件 if 文件 not in 并行文件]
        with ThreadPoolExecutor(max_workers=并行度) as 池:
            任务表 = {
                池.submit(_运行单文件子进程, str(文件), 任务id, 序号): 文件
                for 序号, 文件 in enumerate(并行文件)
            }
            for 任务 in as_completed(任务表):
                结果表.append(任务.result())
        # 外部工具文件在并行批结束后按原阶段顺序执行，保持其进程级互斥。
        for 序号, 文件 in enumerate(串行文件, start=len(并行文件)):
            结果表.append(_运行单文件子进程(str(文件), 任务id, 序号))
        失败结果 = [结果 for 结果 in 结果表
                    if int(结果.get("退出码", 1)) != 0 or 结果.get("清理失败")]
        if 失败结果:
            for 结果 in 失败结果:
                print(f"阶段门禁失败：{阶段名} / {结果.get('路径')}")
                print(str(结果.get("标准输出", "")))
                if 结果.get("标准错误"):
                    print(str(结果["标准错误"]), file=sys.stderr)
            print("阶段失败原因：测试文件失败")
            return 1
        总测试数 = 0
        for 结果 in sorted(结果表, key=lambda 项: str(项.get("路径", ""))):
            文件 = Path(str(结果["路径"]))
            测试数 = _解析单文件测试数(str(结果.get("标准输出", "")))
            if 测试数 <= 0:
                print(f"阶段失败原因：{文件} 未报告有效测试数")
                return 1
            写入文件级缓存(文件, 构建文件级缓存项(文件, 环境摘要, 测试数))
            总测试数 += 测试数
        缓存项 = _补齐缓存证据({
            "摘要": 摘要, "成功": True, "测试数": 总测试数,
            "结构版本": 缓存结构版本, "按文件缓存": True,
            "文件数": len(阶段文件), "执行文件数": len(结果表), "复用文件数": 0,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "时间戳": time.time(), "环境摘要": 环境摘要,
        })
        写入缓存({阶段名: 缓存项})
        print(f"--- 阶段：{阶段名}（{总测试数} 个测试，文件进程并行 {并行度}）---")
        print(f"阶段测试数：{总测试数}")
        return 0
    阶段套件 = unittest.TestSuite()
    阶段序号_当前 = _阶段序号(阶段名)
    # 慢速“平台治理”阶段使用特殊匹配符收集所有尚未归属常规阶段
    # 的测试文件。内部阶段入口也必须按同一覆盖口径展开，不能把特殊
    # 符当作普通目录名导致退出码 2 和静默漏测。
    if "__未归属测试__" in 匹配表:
        已明确归属: set[Path] = set()
        for _, 其他匹配表 in 常规阶段顺序表 + 慢速阶段顺序表:
            for 其他匹配 in 其他匹配表:
                if 其他匹配 != "__未归属测试__":
                    已明确归属.update(收集阶段文件([其他匹配]))
        展开文件 = sorted(全部测试文件() - 已明确归属)
        匹配路径表: list[Path] = 展开文件
    else:
        匹配路径表 = []
        for 匹配 in 匹配表:
            for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
                if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                    匹配路径表.append(路径)
                elif 路径.is_dir():
                    匹配路径表.extend(路径.rglob("测试_*.py"))
    for 路径 in sorted(set(匹配路径表)):
        模块 = 测试中心.加载测试模块(路径, 阶段序号_当前)
        if 模块 is not None:
            阶段套件.addTests(加载器.loadTestsFromModule(模块))
    if 判断零测试(阶段套件):
        print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试用例")
        print("阶段失败原因：未发现测试用例")
        return 1
    print(f"--- 阶段：{阶段名}（{阶段套件.countTestCases()} 个测试）---")
    阶段结果 = unittest.TextTestRunner(verbosity=1).run(阶段套件)
    失败原因 = ""
    if not 阶段结果.wasSuccessful():
        失败原因 = "测试失败"
    elif 判断导入失败(阶段结果):
        失败原因 = "导入失败"
    elif 判断存在跳过(阶段结果):
        失败原因 = "存在未执行场景"
    if 失败原因:
        print(f"阶段门禁失败：{阶段名} 阶段{失败原因}")
        print(f"阶段失败原因：{失败原因}")
        return 1
    缓存项 = _补齐缓存证据({
        "摘要": 摘要, "成功": True, "测试数": 阶段套件.countTestCases(),
        "结构版本": 缓存结构版本,
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "时间戳": time.time(), "环境摘要": 环境摘要,
    }, 标准输出 if '标准输出' in locals() else "")
    # 只写自己阶段缓存文件，避免与其它并行子进程重写彼此文件
    写入缓存({阶段名: 缓存项})
    print(f"阶段测试数：{阶段套件.countTestCases()}")
    return 0


def _执行阶段顺序表串行(
    范围: str, 阶段顺序表: list[tuple[str, list[str]]],
    断点阶段顺序表: list[tuple[str, list[str]]],
    缓存: dict, 环境摘要: str, 强制慢速: bool,
) -> int:
    """按固定阶段顺序串行执行全部阶段；前一阶段失败必须停止。"""
    总测试数 = 0
    复用阶段数 = 0
    开始时间 = time.monotonic()
    for 阶段名, 匹配表 in 阶段顺序表:
        状态码, 测试数, 复用, 缓存 = _执行单个阶段串行(
            阶段名, 匹配表, 范围, 断点阶段顺序表, 缓存, 环境摘要,
            强制慢速,
        )
        if 状态码 != 0:
            return 1
        总测试数 += 测试数
        复用阶段数 += 1 if 复用 else 0
    总耗时 = time.monotonic() - 开始时间
    清除断点()
    print(
        f"门禁通过：共 {总测试数} 个测试全部成功（复用 {复用阶段数} "
        f"个全文件证据阶段，总耗时 {总耗时:.2f} 秒）",
    )
    return 0


def _主函数并行路径(
    范围: str, 阶段顺序表: list[tuple[str, list[str]]],
    断点阶段顺序表: list[tuple[str, list[str]]],
    缓存: dict, 环境摘要: str, 强制慢速: bool, 并行数: int,
) -> int:
    """阶段并行执行路径：非敏感阶段并行批 + 敏感阶段串行保持原顺序。"""
    总测试数 = 0
    复用阶段数 = 0
    任务id = _生成任务id()
    真实失败表: list[str] = []
    清理失败表: list[dict[str, object]] = []
    开始时间 = time.monotonic()
    并行批: list[tuple[str, list[str]]] = []

    def 执行当前并行批() -> None:
        nonlocal 总测试数, 复用阶段数, 真实失败表, 清理失败表
        if not 并行批:
            return
        总测试数, 复用阶段数, 真实失败表, 清理失败表 = _处理阶段并行批(
            并行批, 任务id, 缓存, 环境摘要, 并行数,
            总测试数, 复用阶段数, 真实失败表, 清理失败表,
        )

    for 阶段名, 匹配表 in 阶段顺序表:
        if 阶段名 in 环境敏感阶段 or 阶段名 not in 阶段安全并行白名单:
            执行当前并行批()
            并行批.clear()
            if 真实失败表:
                break
            状态码, 测试数, 复用, 缓存 = _执行单个阶段串行(
                阶段名, 匹配表, 范围, 断点阶段顺序表, 缓存, 环境摘要,
                强制慢速,
            )
            if 状态码 != 0:
                真实失败表.append(阶段名)
                break
            总测试数 += 测试数
            复用阶段数 += 1 if 复用 else 0
        else:
            并行批.append((阶段名, 匹配表))
    else:
        执行当前并行批()
    if 真实失败表:
        # 断点写入首个失败者仲裁：阶段顺序表中下标最小的真实失败阶段
        下标表 = {阶段名: 序号 for 序号, (阶段名, _) in enumerate(阶段顺序表)}
        首失败 = min(真实失败表, key=lambda 名: 下标表.get(名, len(阶段顺序表)))
        写入断点(范围, 首失败, 断点阶段顺序表, "测试失败")
        for 结果 in 清理失败表:
            print(
                f"清理失败证据：{结果['清理失败证据路径']}"
                f"（原因：{结果['清理失败原因']}）",
                file=sys.stderr,
            )
        失败表显示 = "、".join(真实失败表)
        print(f"阶段并行门禁失败：{失败表显示} 阶段失败")
        return 1
    总耗时 = time.monotonic() - 开始时间
    清除断点()
    print(
        f"门禁通过：共 {总测试数} 个测试全部成功（复用 {复用阶段数} "
        f"个阶段缓存，总耗时 {总耗时:.2f} 秒）",
    )
    return 0


def 主函数(
    套件: unittest.TestSuite | None = None, 范围: str = "常规",
    指定测试文件: list[str] | None = None, 指定阶段: list[str] | None = None,
    并行数: int = 0, 强制慢速: bool = False, 继续运行: bool = False,
    并行阶段: bool = False, 并行慢速: bool = False,
) -> int:
    """按固定阶段顺序执行全部测试；前一阶段失败必须停止。"""
    # 验证运行开始前强制刷新 git 指纹映射：工作区可能在上次运行后变化，
    # 脏集合过期会导致缓存命中旧摘要 → 假绿。
    _构建git指纹映射(强制刷新=True)
    if 并行阶段:
        if 继续运行:
            print("用法错误：--并行阶段不能与--继续同时使用")
            return 2
        if 指定测试文件:
            print("用法错误：--并行阶段不能与--测试文件同时使用")
            return 2
        if 范围 not in ("常规", "全部"):
            print("用法错误：--并行阶段只能用于常规或全部范围")
            return 2
    if 并行慢速 and 范围 not in ("慢速", "全部"):
        print("用法错误：--并行慢速只能与--范围 慢速或全部使用")
        return 2
    if 套件 is not None:
        # 注入套件模式（测试门禁自测用）：单套件执行
        if 判断零测试(套件):
            print("零测试门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）")
            return 1
        # 反向验证会故意注入一个失败子套件；其诊断只应由返回码表达，
        # 不能把嵌套失败文本泄漏到外层阶段输出而触发假失败解析。
        结果 = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(套件)
        if not 结果.wasSuccessful() or 判断导入失败(结果) or 判断存在跳过(结果):
            return 1
        print(f"门禁通过：共 {套件.countTestCases()} 个测试全部成功")
        return 0
    if 指定测试文件:
        if 继续运行:
            print("用法错误：--继续不能与--测试文件同时使用")
            return 2
        if 范围 != "常规" or 指定阶段:
            print("用法错误：--测试文件不能与--阶段或非默认--范围同时使用")
            return 2
        try:
            return 并行执行指定测试文件(指定测试文件, 并行数)
        except (OSError, ValueError, ImportError) as 错误:
            print(f"工作包门禁失败：{错误}")
            return 1
    if 强制慢速 and 范围 not in ("慢速", "全部"):
        print("用法错误：--强制慢速只能与--范围 慢速或全部使用")
        return 2
    缓存实现引用 = 审计工程缓存正式实现引用()
    if 缓存实现引用:
        print("正式实现门禁失败：测试引用了工程缓存中的第十四阶段候选实现")
        for 路径 in 缓存实现引用[:20]:
            print(f"- {路径}")
        if len(缓存实现引用) > 20:
            print(f"- 其余 {len(缓存实现引用) - 20} 个文件省略")
        return 1
    # 标准验收：固定阶段顺序（模块级常量，静态契约→组件合规→结构迁移→
    # 权威状态→资源并发→平台控制面→反向破坏→项目装配→真实进程→网关→
    # 浏览器→发布门禁），前 8 个非环境敏感阶段允许并行，敏感阶段永不并行
    断点: dict = {}
    if 继续运行:
        断点 = 读取断点()
        if not 断点:
            print("续跑门禁失败：没有可恢复的验证断点")
            return 2
        if 断点.get("缓存结构版本") != 缓存结构版本:
            print("续跑门禁失败：断点结构版本已失效，请重新执行原验证命令")
            return 2
        范围 = str(断点.get("范围", 范围))
    if 范围 == "常规":
        阶段顺序表 = 常规阶段顺序表
    elif 范围 == "慢速":
        阶段顺序表 = 慢速阶段顺序表
    elif 范围 == "全部":
        阶段顺序表 = 常规阶段顺序表 + 慢速阶段顺序表
    else:
        print(f"用法错误：未知验证范围 {范围!r}")
        return 2
    if 继续运行 and 指定阶段:
        print("用法错误：--继续不能与--阶段同时使用")
        return 2
    if 指定阶段:
        if 范围 != "常规":
            print("用法错误：--阶段只能用于常规范围")
            return 2
        try:
            阶段顺序表 = 筛选阶段(阶段顺序表, 指定阶段)
        except ValueError as 错误:
            print(f"用法错误：{错误}")
            return 2
    阶段文件表 = {
        阶段名: 收集阶段文件(匹配表)
        for 阶段名, 匹配表 in 阶段顺序表
    }
    期望文件 = (
        sorted(全部测试文件(), key=str)
        if 范围 == "全部"
        else sorted({文件 for 文件表 in 阶段文件表.values() for 文件 in 文件表}, key=str)
    )
    覆盖结果 = 校验测试覆盖(阶段文件表, 期望文件)
    if not 覆盖结果["成功"]:
        print(
            f"测试覆盖门禁失败：漏测={覆盖结果['漏测']}；"
            f"重复={覆盖结果['重复']}；阶段空缺={覆盖结果['阶段空缺']}"
        )
        return 1
    print(f"测试覆盖门禁通过：{len(期望文件)} 个测试文件唯一归属")
    断点阶段顺序表 = 阶段顺序表
    if 范围 in ("慢速", "全部"):
        # 发布门禁可能由慢速综合审计反向调用。令牌必须同时匹配直接父进程，
        # 门禁才可复用当前正在执行的慢速验证事务，避免门禁与慢速层递归。
        os.environ["系统底座_慢速验证事务"] = uuid.uuid4().hex
        os.environ["系统底座_慢速验证进程"] = str(os.getpid())
    缓存 = 读取缓存()
    环境摘要 = 运行环境摘要()
    if 继续运行:
        try:
            记录阶段 = set(断点.get("阶段列表", []))
            断点阶段顺序表 = [
                阶段 for 阶段 in 阶段顺序表 if 阶段[0] in 记录阶段
            ]
            阶段顺序表 = 计算断点续跑阶段(
                断点阶段顺序表, 断点, 缓存, 环境摘要, 强制慢速,
            )
        except ValueError as 错误:
            print(f"续跑门禁失败：{错误}")
            return 2
        print(f"断点续跑：从 {阶段顺序表[0][0]} 开始，共 {len(阶段顺序表)} 个阶段")
    # 阶段并行：非敏感阶段并行；敏感阶段（真实进程/网关/浏览器/发布门禁/慢速层）保持串行。
    # 断点续跑（--继续）与未显式指定 --并行阶段 的 --阶段 波次保持串行。
    # 默认走逐测试文件缓存路径；阶段级并行会把无关包重新成批拉起，
    # 只有显式 --并行阶段 才允许使用旧的阶段并行调度。
    允许阶段并行 = (范围 in ("常规", "全部")) and not 继续运行 and 并行阶段
    # 慢速层按资源族拆分：独立工作包并行，明确触碰共享状态的文件串行。
    if 并行慢速 and 范围 in ("慢速", "全部") and not 继续运行:
        慢速全部文件 = sorted(
            路径 for 路径 in (测试中心.测试中心目录 / "慢速层").rglob("测试_*.py")
            if 路径.is_file()
        )
        安全路径 = [路径 for 路径 in 慢速全部文件 if 慢速可并行文件(路径)]
        # 旧白名单是经过验证的补充声明；即便文件名命中串行片段，也不
        # 允许其被带入并行批，确保共享资源族始终串行。
        安全文件 = [str(路径) for 路径 in 安全路径]
        if 安全文件:
            print(f"慢速安全并行：{len(安全文件)} 个文件，并行数 {max(1, 并行数 or 4)}")
            if 并行执行指定测试文件(安全文件, 并行数 or 4) != 0:
                return 1
        # 命中文件级缓存后，剩余共享资源文件仍走原串行路径；不降低
        # 覆盖率或门禁强度。
        并行慢速 = False
    if 允许阶段并行 and 阶段顺序表:
        return _主函数并行路径(
            范围, 阶段顺序表, 断点阶段顺序表, 缓存, 环境摘要,
            强制慢速, 并行数,
        )
    原并行数 = os.environ.get("系统底座_并行数")
    os.environ["系统底座_并行数"] = str(max(1, 并行数 or 全局并发数()))
    try:
        return _执行阶段顺序表串行(
            范围, 阶段顺序表, 断点阶段顺序表, 缓存, 环境摘要, 强制慢速,
        )
    finally:
        if 原并行数 is None:
            os.environ.pop("系统底座_并行数", None)
        else:
            os.environ["系统底座_并行数"] = 原并行数


if __name__ == "__main__":
    import argparse

    参数解析器 = argparse.ArgumentParser(description="系统工程底座唯一验证入口")
    参数解析器.add_argument("--范围", choices=("常规", "慢速", "全部"), default="常规")
    参数解析器.add_argument("--阶段", action="append", help="合并波次只验证指定常规阶段，可重复")
    参数解析器.add_argument("--测试文件", nargs="+", help="工作包只验证明确测试文件")
    参数解析器.add_argument("--并行数", type=int, default=0, help="工作包并行进程数，0为自动")
    参数解析器.add_argument("--强制慢速", action="store_true", help="忽略慢速证据缓存并真实执行")
    参数解析器.add_argument("--继续", dest="继续运行", action="store_true", help="从失败断点继续，证据失效时自动回退")
    参数解析器.add_argument("--并行阶段", dest="并行阶段", action="store_true", help="非敏感阶段并行执行（常规/全部；与--继续/--测试文件互斥）")
    参数解析器.add_argument("--并行慢速", dest="并行慢速", action="store_true", help="仅并行慢速安全文件白名单，其余慢速场景保持串行")
    参数解析器.add_argument("--内部测试文件", help=argparse.SUPPRESS)
    参数解析器.add_argument("--内部阶段", help=argparse.SUPPRESS)
    参数 = 参数解析器.parse_args()
    if 参数.内部测试文件:
        raise SystemExit(执行测试套件(
            加载指定测试文件([参数.内部测试文件]), "单文件",
        ))
    if 参数.内部阶段:
        raise SystemExit(执行内部阶段子进程(参数.内部阶段))
    # 全量验证互斥（AGENTS.md"已有全量运行时禁止重复启动"代码化）：
    # 常规/慢速/全部 范围持 flock 锁，防并发全量抢端口/数据库/发布指针。
    # 内部子进程与工作包（--测试文件）无冲突不锁。
    if not 参数.测试文件:
        if not 获取验证锁():
            print("验证锁门禁失败：已有全量验证正在运行（工程缓存/验证锁.lock），禁止重复启动")
            raise SystemExit(1)
    try:
        raise SystemExit(主函数(
            范围=参数.范围, 指定测试文件=参数.测试文件,
            指定阶段=参数.阶段, 并行数=参数.并行数,
            强制慢速=参数.强制慢速, 继续运行=参数.继续运行,
            并行阶段=参数.并行阶段,
            并行慢速=参数.并行慢速,
        ))
    finally:
        释放验证锁()
