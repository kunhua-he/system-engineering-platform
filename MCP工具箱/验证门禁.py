"""定向验证与反馈门禁：命令白名单校验、验证结果判定、未反馈阻断。

供主协调接线使用。三个入口统一返回结果结构：
    {成功: bool, 错误码: str, 消息: str}

错误码集合（冻结契约）：
    命令拒绝 / 验证失败 / 零测试 / 未解释跳过 / 未反馈阻断

安全原则（冻结契约）：
- verify_and_record 只允许受控 Python/pytest 定向入口，禁止任意 shell 字符串
- 禁止 shell=True、绝对路径、../ 路径逃逸、shell 元字符、无限超时
- 退出码非零 / 收集错误 / 零测试 / 无反馈 / 未解释跳过一律失败

允许形态：
1. ["python3.14", "测试中心/运行测试.py", "--测试文件", "测试中心/…相对路径", "--并行数", "N"]
2. ["python3.14", "测试中心/运行测试.py", "--范围", "常规|慢速|全部", "--并行阶段", "--并行数", "N"]
   可选 `--并行慢速`、`--强制慢速`；范围模式由运行器自行按资源族调度。
3. ["python3.14", "-m", "pytest", "测试中心/…相对路径", "-q", "--timeout=N"]（N ≤ 1800）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from 使用反馈 import 查询反馈状态

项目根目录 = Path(__file__).resolve().parents[1]
默认反馈路径 = 项目根目录 / "开发文档" / "项目证据" / "MCP使用反馈.jsonl"

允许可执行 = {"python3.14"}
运行测试入口 = "测试中心/运行测试.py"
测试目录前缀 = "测试中心/"
HTML验证入口 = "开发工具/HTML验证/验证器.py"
唯一发布入口 = "开发工具/发布门禁/运行发布门禁.py"
唯一发布命令 = ("python3.14", 唯一发布入口)
最大超时秒 = 1800
shell元字符表 = set(";|&`$(){}<>")

错误码_命令拒绝 = "命令拒绝"
错误码_验证失败 = "验证失败"
错误码_零测试 = "零测试"
错误码_未解释跳过 = "未解释跳过"
错误码_未反馈阻断 = "未反馈阻断"
错误码集合 = (
    错误码_命令拒绝, 错误码_验证失败, 错误码_零测试,
    错误码_未解释跳过, 错误码_未反馈阻断,
)


def _结果(成功: bool, 错误码: str, 消息: str) -> dict[str, Any]:
    return {"成功": 成功, "错误码": 错误码, "消息": 消息}


def _拒绝(消息: str) -> dict[str, Any]:
    return _结果(False, 错误码_命令拒绝, 消息)


def _基础校验(命令: list[str]) -> str | None:
    """公共安全校验：返回拒绝原因；None 表示通过。"""
    if not isinstance(命令, list) or not 命令:
        return "命令必须是包含非空字符串的列表"
    for 项 in 命令:
        if not isinstance(项, str) or not 项:
            return f"命令元素必须是非空字符串，发现 {项!r}"
        if any(字符 in 项 for 字符 in shell元字符表):
            return f"禁止 shell 元字符: {项!r}"
        if "shell=" in 项.lower():
            return f"禁止 shell=True 形式参数: {项!r}"
        if 项.startswith(("/", "~")):
            return f"禁止绝对路径: {项!r}"
        if ".." in 项:
            return f"禁止路径逃逸（..）: {项!r}"
    return None


def _校验测试文件(文件: str, 工作根: Path | None) -> str | None:
    """测试文件必须是 测试中心 下的相对 .py 路径；工作根提供时校验存在性与根内包含。"""
    规范 = 文件.replace("\\", "/")
    if not 规范.startswith(测试目录前缀):
        return f"测试文件必须位于 {测试目录前缀} 下: {文件!r}"
    if not 规范.endswith(".py"):
        return f"测试文件必须是 .py 后缀: {文件!r}"
    if ".." in 规范 or 规范.startswith(("/", "~")):
        return f"非法测试文件路径: {文件!r}"
    if 工作根 is not None:
        解析 = (工作根 / 规范).resolve()
        if not 解析.is_file():
            return f"测试文件不存在: {文件!r}"
        if not 解析.is_relative_to(工作根.resolve()):
            return f"测试文件逃逸工作根: {文件!r}"
    return None


def _校验运行测试形态(命令: list[str], 工作根: Path | None) -> dict[str, Any] | None:
    """校验工作包文件形态或官方范围调度形态。"""
    尾部 = 命令[2:]
    if not 尾部:
        return _拒绝("运行测试.py 必须显式指定 --测试文件 或 --范围")
    if 尾部[0] == "--范围":
        if len(尾部) < 2 or 尾部[1] not in {"常规", "慢速", "全部"}:
            return _拒绝("--范围 必须是 常规、慢速 或 全部")
        允许选项 = {"--并行阶段", "--并行慢速", "--强制慢速", "--并行数"}
        序号 = 2
        while 序号 < len(尾部):
            选项 = 尾部[序号]
            if 选项 not in 允许选项:
                return _拒绝(f"范围验证不允许参数: {选项!r}")
            if 选项 == "--并行数":
                if 序号 + 1 >= len(尾部) or not 尾部[序号 + 1].isdigit():
                    return _拒绝("--并行数 后必须是非负整数")
                序号 += 2
            else:
                序号 += 1
        return None
    if 尾部[0] != "--测试文件":
        return _拒绝("运行测试.py 形态必须以 --测试文件 或 --范围 开头")
    文件区: list[str] = []
    序号 = 1
    while 序号 < len(尾部) and not 尾部[序号].startswith("--"):
        文件区.append(尾部[序号])
        序号 += 1
    if not 文件区:
        return _拒绝("--测试文件 后必须至少一个测试文件")
    for 文件 in 文件区:
        原因 = _校验测试文件(文件, 工作根)
        if 原因 is not None:
            return _拒绝(原因)
    if 序号 >= len(尾部):
        return _拒绝("运行测试.py 形态缺少 --并行数")
    if 尾部[序号] != "--并行数":
        return _拒绝(f"运行测试.py 形态只允许 --并行数 选项，发现 {尾部[序号]!r}")
    if 序号 + 2 != len(尾部):
        return _拒绝("--并行数 后必须恰好一个整数")
    并行值 = 尾部[序号 + 1]
    if not 并行值.isdigit():
        return _拒绝(f"--并行数 必须是整数，发现 {并行值!r}")
    return None


def _校验pytest形态(命令: list[str], 工作根: Path | None) -> dict[str, Any] | None:
    """形态2：["python3.14", "-m", "pytest", 文件*, "-q", "--timeout=N"]（N ≤ 1800）。"""
    尾部 = 命令[3:]
    if len(尾部) < 3:
        return _拒绝("pytest 形态至少需要 测试文件、-q 与 --timeout")
    超时令牌 = 尾部[-1]
    if 尾部[-2] != "-q":
        return _拒绝("pytest 形态必须包含 -q（位于 --timeout 之前）")
    if not 超时令牌.startswith("--timeout="):
        return _拒绝("pytest 形态必须以 --timeout=N 结尾")
    超时值 = 超时令牌.split("=", 1)[1]
    if not 超时值.isdigit() or not 1 <= int(超时值) <= 最大超时秒:
        return _拒绝(f"超时必须在 1..{最大超时秒} 秒，发现 {超时令牌!r}")
    文件区 = 尾部[:-2]
    if not 文件区:
        return _拒绝("pytest 形态缺少测试文件")
    for 文件 in 文件区:
        原因 = _校验测试文件(文件, 工作根)
        if 原因 is not None:
            return _拒绝(原因)
    return None


def 正式发布命令表(制品: str) -> list[list[str]]:
    """正式发布计划、白名单和证据共同使用的唯一命令源。"""
    return [
        ["python3.14", HTML验证入口, "--制品", str(制品), "--并发", "8"],
        list(唯一发布命令),
    ]


def _校验HTML形态(命令: list[str], 工作根: Path | None) -> dict[str, Any] | None:
    """只允许对根内相对制品执行 HTML 黑盒验证，禁止服务、直连和生成模式。"""
    if len(命令) != 6 or 命令[2] != "--制品" or 命令[4] != "--并发":
        return _拒绝("HTML 验证只允许 --制品 <相对目录> --并发 <整数>")
    制品 = 命令[3].replace("\\", "/")
    if not 制品 or 制品.startswith(("/", "~")) or ".." in 制品:
        return _拒绝(f"HTML 制品路径必须是根内相对目录: {命令[3]!r}")
    if not 命令[5].isdigit() or not 1 <= int(命令[5]) <= 64:
        return _拒绝("HTML 验证并发数必须在 1..64")
    if 工作根 is not None:
        解析 = (工作根 / 制品).resolve()
        if not 解析.is_dir() or not 解析.is_relative_to(工作根.resolve()):
            return _拒绝(f"HTML 制品目录不存在或逃逸工作根: {命令[3]!r}")
    return None


def 校验验证命令(命令: list[str], 工作根: Path | None = None) -> dict[str, Any]:
    """白名单判定：开发验证及正式发布的两条受控命令，其他命令一律拒绝。"""
    基础原因 = _基础校验(命令)
    if 基础原因 is not None:
        return _拒绝(基础原因)
    if 命令[0] not in 允许可执行:
        return _拒绝(f"可执行程序不在白名单: {命令[0]!r}")
    if tuple(命令) == 唯一发布命令:
        结果 = None
    elif len(命令) > 1 and 命令[1] == HTML验证入口:
        结果 = _校验HTML形态(命令, 工作根)
    elif 命令[1:3] == ["-m", "pytest"]:
        结果 = _校验pytest形态(命令, 工作根)
    elif len(命令) > 1 and 命令[1] == 运行测试入口:
        结果 = _校验运行测试形态(命令, 工作根)
    else:
        入口 = 命令[1] if len(命令) > 1 else "<缺失>"
        return _拒绝(f"验证入口不在白名单: {入口!r}")
    if 结果 is not None:
        return 结果
    return _结果(True, "", f"命令通过白名单校验: {' '.join(命令)}")


def _检出收集错误(文本: str) -> bool:
    """收集错误（ERROR）：pytest 收集失败/unittest 错误输出。"""
    低 = 文本.lower()
    return bool(re.search(r"\bERROR", 文本)) or "errors=" in 低


def _检出零测试(文本: str) -> bool:
    """零测试：Ran 0 tests / no tests ran / 未发现任何测试用例（真正没跑）。"""
    低 = 文本.lower()
    return (
        "no tests ran" in 低
        or "未发现任何测试用例" in 文本
        or "ran 0 tests" in 低
    )


def _检出未解释跳过(文本: str) -> bool:
    """未解释跳过：存在跳过标记但没有说明（skip 无原因）。"""
    有跳过 = bool(re.search(r"\bSKIPPED\b|skipped\b|跳过门禁失败|存在未执行场景", 文本))
    if not 有跳过:
        return False
    有解释 = bool(re.search(r"原因|Skipped:|reason=|已解释|skipped ['\"]|skipped \(", 文本))
    return not 有解释


def 判定验证结果(退出码: int, 标准输出: str, 标准错误: str = "") -> dict[str, Any]:
    """按 退出码非零 → 收集错误 → 零测试 → 未解释跳过 的顺序判定，全部通过才成功。"""
    文本 = f"{标准输出 or ''}\n{标准错误 or ''}"
    if 退出码 != 0:
        return _结果(False, 错误码_验证失败, f"验证退出码非零: {退出码}")
    if _检出收集错误(文本):
        return _结果(False, 错误码_验证失败, "测试收集错误（ERROR）")
    if _检出零测试(文本):
        return _结果(False, 错误码_零测试, "未运行任何测试用例（no tests ran / 零测试门禁失败）")
    if _检出未解释跳过(文本):
        return _结果(False, 错误码_未解释跳过, "存在无标记说明的跳过（SKIPPED/skip 无原因）")
    return _结果(True, "", "验证结果判定通过")


def 判定正式发布结果(退出码: int, 标准输出: str, 标准错误: str = "") -> dict[str, Any]:
    """唯一发布入口只有退出码为零且最后状态明确为“通过”才成功。"""
    基础 = 判定验证结果(退出码, 标准输出, 标准错误)
    if not 基础["成功"]:
        return 基础
    文本 = f"{标准输出 or ''}\n{标准错误 or ''}"
    状态表 = re.findall(r"发布状态[:：]\s*(通过|失败|阻断)", 文本)
    状态 = 状态表[-1] if 状态表 else "未知"
    if 状态 != "通过":
        return _结果(False, 错误码_验证失败, f"发布状态不是明确通过: {状态}")
    return _结果(True, "", "正式发布结果判定通过")


def 反馈门禁(开工id: str, 反馈路径: Path | None = None) -> dict[str, Any]:
    """反馈门禁：该开工id必须有 MCP 使用反馈记录，否则 未反馈阻断。"""
    路径 = 反馈路径 or 默认反馈路径
    状态 = 查询反馈状态(路径, 开工id)
    if 状态.get("已反馈"):
        return _结果(True, "", f"反馈门禁已满足（开工id={开工id}）")
    return _结果(
        False, 错误码_未反馈阻断,
        f"开工id={开工id} 尚无 MCP 使用反馈记录，不能记录成功验证证据",
    )
