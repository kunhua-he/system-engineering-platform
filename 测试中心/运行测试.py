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
import json
import re
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
# 无条件插到最前：系统根包名（公共契约/能力契约等）与测试中心下同名测试目录
# 冲突，若依赖 in 判断可能因 cwd/脚本目录已在 sys.path 而跳过插入，
# 导致 import 公共契约 命中测试目录而非真实包（cProfile -m 实测复现）。
sys.path.insert(0, str(系统根))

import 测试中心
from MCP工具箱 import 测试资源

验证缓存目录 = 系统根 / "工程缓存" / "验证缓存"
断点文件路径 = 系统根 / "工程缓存" / "验证断点.json"
运行根目录 = 系统根 / "工程缓存" / "验证运行"
清理失败证据目录 = 系统根 / "工程缓存" / "清理失败证据"
保留制品目录 = 系统根 / "工程缓存" / "保留制品"
缓存结构版本 = "2.0.0"  # 缓存结构版本：损坏/缺字段/引擎变化时自动失效
运行证据有效秒 = 7 * 24 * 60 * 60
环境敏感阶段 = {"真实进程", "网关", "浏览器", "发布门禁", "慢速层"}
顶层包目录表 = {
    目录.name for 目录 in 系统根.iterdir()
    if 目录.is_dir() and 目录.name not in ("测试中心", "工程缓存", "开发文档", "示例项目", ".git", "__pycache__")
}


def _文件摘要(文件: Path) -> str:
    """文件内容摘要（sha256 前 16 位）。"""
    return hashlib.sha256(文件.read_bytes()).hexdigest()[:16]


def _目录摘要(目录: Path) -> str:
    """目录内容摘要（全部文件，排除缓存）。"""
    摘要器 = hashlib.sha256()
    for 文件 in sorted(目录.rglob("*")):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件) \
                and "完整性摘要.json" != 文件.name:
            摘要器.update(str(文件.relative_to(目录)).encode("utf-8"))
            摘要器.update(文件.read_bytes())
    return 摘要器.hexdigest()[:16]


def 收集阶段文件(匹配表: list[str]) -> list[Path]:
    """按阶段匹配表收集测试文件。"""
    文件列表: list[Path] = []
    for 匹配 in 匹配表:
        for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
            if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                文件列表.append(路径)
            elif 路径.is_dir():
                文件列表.extend(路径.rglob("测试_*.py"))
    return sorted(文件列表)


def 阶段依赖目录表(测试文件列表: list[Path]) -> set[str]:
    """解析测试文件的 import 依赖 → 受影响系统顶层包目录。"""
    依赖表: set[str] = set()
    import模式 = re.compile(r"^\s*(?:from|import)\s+([一-龥\w.]+)")
    for 文件 in 测试文件列表:
        try:
            for 行 in 文件.read_text(encoding="utf-8").splitlines():
                匹配 = import模式.match(行)
                if 匹配:
                    顶层包 = 匹配.group(1).split(".")[0].strip()
                    if 顶层包 in 顶层包目录表:
                        依赖表.add(顶层包)
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
        shutil.which("sw_vers"), shutil.which("git"),
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
    if not 缓存项 or 缓存项.get("摘要") != 摘要 or not 缓存项.get("成功"):
        return False
    if not 缓存项.get("测试数") or 缓存项.get("结构版本") != 缓存结构版本:
        return False
    if 阶段名 == "慢速层" and 强制慢速:
        return False
    # 环境摘要对所有阶段生效；缺失字段（旧式缓存项）跳过比对，生产缓存恒带该字段
    if 缓存项.get("环境摘要") is not None and 缓存项.get("环境摘要") != 环境摘要:
        return False
    if 阶段名 in 环境敏感阶段:
        记录时间 = float(缓存项.get("时间戳", 0))
        if (当前时间 or time.time()) - 记录时间 > 运行证据有效秒:
            return False
    return True


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


def 计算并行数(文件数: int, 请求并行数: int) -> int:
    """0 表示自动；并发有界，避免测试调度反向冲垮机器。"""
    if 文件数 <= 1:
        return 1
    if 请求并行数 < 0:
        raise ValueError("并行数不能小于0")
    上限 = min(32, max(1, os.cpu_count() or 4))
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
        进程.wait()


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
                except json.JSONDecodeError:
                    continue
                if 记录.get("保留"):
                    保留路径表.append(Path(str(记录["路径"])).resolve())
        测试资源.清理资源(资源清单路径, 临时根目录=工作目录)
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


def 主函数(
    套件: unittest.TestSuite | None = None, 范围: str = "常规",
    指定测试文件: list[str] | None = None, 指定阶段: list[str] | None = None,
    并行数: int = 0, 强制慢速: bool = False, 继续运行: bool = False,
) -> int:
    """按固定阶段顺序执行全部测试；前一阶段失败必须停止。"""
    加载器 = unittest.TestLoader()
    if 套件 is not None:
        # 注入套件模式（测试门禁自测用）：单套件执行
        if 判断零测试(套件):
            print("零测试门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）")
            return 1
        结果 = unittest.TextTestRunner(verbosity=2).run(套件)
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
    # 标准验收：固定阶段顺序（静态契约→组件合规→反向破坏→项目装配→
    # 真实进程→网关→浏览器→发布门禁），前一阶段失败必须停止
    常规阶段顺序表 = [
        ("静态契约", ["测试_零测试门禁.py", "公共契约", "加载器", "支持库", "模块库"]),
        ("组件合规", ["测试_静态契约.py", "测试_组件合规.py"]),
        ("结构迁移", ["结构迁移"]),
        ("权威状态", ["权威状态"]),
        ("资源并发", ["资源并发"]),
        ("平台控制面", ["平台控制面"]),
        ("反向破坏", ["测试_反向破坏.py"]),
        ("项目装配", ["示例项目", "项目适配", "第三阶段", "第四阶段", "第十阶段", "第十一阶段"]),
        ("真实进程", ["第五阶段", "第六阶段"]),
        ("网关", ["第七阶段"]),
        ("浏览器", ["第八阶段"]),
        ("发布门禁", ["测试_门禁.py", "发布门禁"]),
    ]
    慢速阶段顺序表 = [("慢速层", ["慢速层"])]
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
    断点阶段顺序表 = 阶段顺序表
    if 范围 in ("慢速", "全部"):
        # 发布门禁可能由慢速综合审计反向调用。令牌必须同时匹配直接父进程，
        # 门禁才可复用当前正在执行的慢速验证事务，避免门禁与慢速层递归。
        os.environ["系统底座_慢速验证事务"] = uuid.uuid4().hex
        os.environ["系统底座_慢速验证进程"] = str(os.getpid())
    总测试数 = 0
    阶段序号 = 0
    复用阶段数 = 0
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
    开始时间 = time.monotonic()
    for 阶段名, 匹配表 in 阶段顺序表:
        阶段序号 += 1
        阶段文件 = 收集阶段文件(匹配表)
        if not 阶段文件:
            print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试文件")
            写入断点(范围, 阶段名, 断点阶段顺序表, "未发现测试文件")
            return 1
        # 增量验证：缓存键 = 测试文件 + 依赖目录摘要；无变化复用已验证证据
        依赖目录表 = 阶段依赖目录表(阶段文件)
        摘要 = 阶段摘要(阶段文件, 依赖目录表)
        缓存项 = 缓存.get(阶段名)
        if 阶段缓存可复用(
            阶段名, 缓存项, 摘要, 环境摘要, 强制慢速=强制慢速,
        ):
            print(f"--- 阶段：{阶段名}（缓存命中，复用 {缓存项.get('测试数')} 个测试已验证证据）---")
            总测试数 += 缓存项.get("测试数", 0)
            复用阶段数 += 1
            continue
        阶段套件 = unittest.TestSuite()
        阶段序号_当前 = 阶段序号
        for 匹配 in 匹配表:
            for 路径 in sorted(测试中心.测试中心目录.rglob(f"**/{匹配}")):
                if 路径.is_file() and 路径.suffix == ".py" and 路径.name.startswith("测试_"):
                    模块 = 测试中心.加载测试模块(路径, 阶段序号_当前)
                    if 模块 is not None:
                        阶段套件.addTests(加载器.loadTestsFromModule(模块))
                elif 路径.is_dir():
                    for 文件 in sorted(路径.rglob("测试_*.py")):
                        模块 = 测试中心.加载测试模块(文件, 阶段序号_当前)
                        if 模块 is not None:
                            阶段套件.addTests(加载器.loadTestsFromModule(模块))
        if 判断零测试(阶段套件):
            print(f"阶段门禁失败：{阶段名} 阶段未发现任何测试用例")
            写入断点(范围, 阶段名, 断点阶段顺序表, "未发现测试用例")
            return 1
        print(f"--- 阶段：{阶段名}（{阶段套件.countTestCases()} 个测试）---")
        阶段结果 = unittest.TextTestRunner(verbosity=1).run(阶段套件)
        if not 阶段结果.wasSuccessful():
            print(f"阶段门禁失败：{阶段名} 阶段存在失败，停止后续阶段")
            写入断点(范围, 阶段名, 断点阶段顺序表, "测试失败")
            return 1
        if 判断导入失败(阶段结果):
            print(f"阶段门禁失败：{阶段名} 阶段存在导入失败，停止后续阶段")
            写入断点(范围, 阶段名, 断点阶段顺序表, "导入失败")
            return 1
        if 判断存在跳过(阶段结果):
            print(f"阶段门禁失败：{阶段名} 阶段存在未执行场景，停止后续阶段")
            写入断点(范围, 阶段名, 断点阶段顺序表, "存在未执行场景")
            return 1
        总测试数 += 阶段套件.countTestCases()
        缓存[阶段名] = {
            "摘要": 摘要, "成功": True, "测试数": 阶段套件.countTestCases(),
            "结构版本": 缓存结构版本,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "时间戳": time.time(), "环境摘要": 环境摘要,
        }
        写入缓存(缓存)
    总耗时 = time.monotonic() - 开始时间
    清除断点()
    print(f"门禁通过：共 {总测试数} 个测试全部成功（复用 {复用阶段数} 个阶段缓存，总耗时 {总耗时:.2f} 秒）")
    return 0


if __name__ == "__main__":
    import argparse

    参数解析器 = argparse.ArgumentParser(description="系统工程底座唯一验证入口")
    参数解析器.add_argument("--范围", choices=("常规", "慢速", "全部"), default="常规")
    参数解析器.add_argument("--阶段", action="append", help="合并波次只验证指定常规阶段，可重复")
    参数解析器.add_argument("--测试文件", nargs="+", help="工作包只验证明确测试文件")
    参数解析器.add_argument("--并行数", type=int, default=0, help="工作包并行进程数，0为自动")
    参数解析器.add_argument("--强制慢速", action="store_true", help="忽略慢速证据缓存并真实执行")
    参数解析器.add_argument("--继续", dest="继续运行", action="store_true", help="从失败断点继续，证据失效时自动回退")
    参数解析器.add_argument("--内部测试文件", help=argparse.SUPPRESS)
    参数 = 参数解析器.parse_args()
    if 参数.内部测试文件:
        raise SystemExit(执行测试套件(
            加载指定测试文件([参数.内部测试文件]), "单文件",
        ))
    raise SystemExit(主函数(
        范围=参数.范围, 指定测试文件=参数.测试文件,
        指定阶段=参数.阶段, 并行数=参数.并行数,
        强制慢速=参数.强制慢速, 继续运行=参数.继续运行,
    ))
