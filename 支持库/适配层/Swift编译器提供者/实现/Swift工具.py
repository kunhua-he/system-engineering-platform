"""swiftc / codesign 独立提供者：macOS Xcode 命令行工具受控调用。

只封装三件事：**编译 Swift 源码**、**adhoc 签名应用包**、**校验签名**。
安全与稳定性口径（照 `支持库/适配层/textutil提供者` 同款）：
- 结构化参数列表，**禁 shell=True**；
- 独立进程组 + 超时强制终止（经 `公共契约/运行时`，不在包内写平台判断）；
- 输出大小上限、临时目录由调用方持有；
- 缺 swiftc/codesign → `外部提供者不可用`，不猜、不用环境变量兜底。

## 只做 adhoc 一档（哲学：不需要的腿不留）
现网网关实测就是 adhoc 自签名（`Signature=adhoc`、`TeamIdentifier=not set`、
`security find-identity` 0 个身份）。故本提供者**不预留**开发者证书与公证档位，
`notarytool` 不进依赖。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 假, 真
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.有界IO import 受限通信

默认超时秒 = 300
默认最大输出字节 = 16 * 1024 * 1024
来源 = "Swift编译器提供者"

_工具缓存: dict[str, str | None] = {}


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def _查找工具(名: str) -> str | None:
    """查找可执行工具（缓存）。Xcode 命令行工具的固定位置优先，其次 PATH。"""
    if 名 in _工具缓存:
        return _工具缓存[名]
    候选 = {
        "swiftc": ["/usr/bin/swiftc", "/usr/local/bin/swiftc", "swiftc"],
        "codesign": ["/usr/bin/codesign", "codesign"],
    }.get(名, [名])
    路径 = next((c for c in 候选 if shutil.which(c)), None)
    _工具缓存[名] = 路径
    return 路径


def _跑(命令行: list[str], *, 超时秒: float, 最大输出字节: int = 默认最大输出字节):
    """受控执行外部命令：独立进程组、超时强杀、输出上限；返回 (退出码, 标准输出, 标准错误)。"""
    try:
        进程 = subprocess.Popen(
            命令行, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **平台适配.子进程组启动标志(), env=dict(os.environ))
    except OSError as 错误:
        raise OSError(f"无法启动 {命令行[0]}: {错误}") from 错误
    输出, 错误输出, 已超时, 已超限 = 受限通信(
        进程, 超时秒=超时秒, 输出上限字节=最大输出字节,
        终止回调=lambda: 进程终止.强制结束子进程(进程, 宽限秒=2.0, 等待秒=2.0))
    if 已超时:
        raise TimeoutError(f"执行超过 {超时秒} 秒：{命令行[0]}")
    if 已超限:
        raise ValueError(f"输出超过上限 {最大输出字节} 字节：{命令行[0]}")
    return (进程.returncode or 0,
            输出.decode("utf-8", errors="replace") if 输出 else "",
            错误输出.decode("utf-8", errors="replace") if 错误输出 else "")


_编译错误模式 = re.compile(r"^(?P<文件>[^:]+):(?P<行>\d+):(?P<列>\d+):\s*(?P<级别>error|warning):\s*(?P<信息>.*)$")


def _解析诊断(文本: str) -> list[dict[str, Any]]:
    """把 swiftc 的诊断文本解析成结构化条目（文件/行/列/级别/信息）。"""
    条目: list[dict[str, Any]] = []
    for 行 in (文本 or "").splitlines():
        m = _编译错误模式.match(行.strip())
        if m:
            条目.append({"文件": m.group("文件"), "行": int(m.group("行")),
                       "列": int(m.group("列")), "级别": m.group("级别"),
                       "信息": m.group("信息").strip()})
    return 条目


# ────────────────────────── 能力实现 ──────────────────────────

def 检查提供者(超时秒: float = 30.0) -> 结果:
    """真实探针 swiftc --version 与 codesign 可用性。

    不返回「看起来可用」：两个工具都要真跑一次 `--version`，任一缺失/超时 →
    `外部提供者不可用`，并把实际诊断带上。
    """
    swiftc = _查找工具("swiftc")
    codesign = _查找工具("codesign")
    缺失 = [n for n, p in (("swiftc", swiftc), ("codesign", codesign)) if not p]
    if 缺失:
        return _失败("提供者不可用",
                     f"缺少工具 {('、'.join(缺失))}（需 Xcode 命令行工具）")
    版本信息: dict[str, str] = {}
    # 探针参数按工具真实支持来：swiftc 认 --version，codesign **不认** --version
    # （实测 `codesign: unrecognized option '--version'`，退出码 2）——
    # 给它一个真实支持的查询参数，否则会把「可用」误报成「不可用」。
    探针参数 = {"swiftc": ["--version"], "codesign": ["--help"]}
    for 名, 路径 in (("swiftc", swiftc), ("codesign", codesign)):
        try:
            码, 出, 错 = _跑([路径, *探针参数[名]], 超时秒=float(超时秒 or 30))
        except TimeoutError as 错误:
            # 顺序有意：`TimeoutError` 是 `OSError` 的子类，放在后面会被 OSError 抢先吞掉，
            # 超时就会被误报成「提供者不可用」（实测踩过）——异常从具体到宽泛。
            return _失败("超时", f"{名} 探针超时: {错误}", 可重试=真)
        except OSError as 错误:
            return _失败("提供者不可用", f"{名} 探针失败: {错误}")
        except ValueError as 错误:
            return _失败("参数不合法", f"{名} 探针参数不合法: {错误}")
        原文 = ((出 or "") + (错 or "")).strip()
        if 码 != 0 and not 原文:
            return _失败("提供者不可用",
                         f"{名} 探针退出码 {码} 且无任何输出（工具不可用）")
        首行 = 原文.splitlines()[0].strip() if 原文 else ""
        版本信息[名] = 首行 or f"（退出码 {码}，工具存在）"
    return 结果.成功结果({"提供者可用": 真, "工具版本": 版本信息,
                     "swiftc 路径": swiftc, "codesign 路径": codesign})


def 编译源代码(*, 源文件清单: list = None, 输出路径: str = None,
             目标架构: str = None, 优化级别: str = None, 附加参数: list = None,
             超时秒: float = 默认超时秒) -> 结果:
    """调 swiftc 把若干 Swift 源文件编译为可执行文件；编译错误逐条结构化回传。"""
    if not isinstance(源文件清单, list) or not 源文件清单:
        return _失败("参数不合法", "源文件清单 必须是非空列表型")
    if not isinstance(输出路径, str) or not 输出路径.strip():
        return _失败("参数不合法", "输出路径 必须是非空文本")
    if not Path(str(输出路径).strip()).is_absolute():
        # 相对输出路径会随调用方工作目录漂移（产物落到不可预期的地方），
        # 与「源文件清单必须是绝对路径」同口径：一律要求绝对路径。
        return _失败("参数不合法", f"输出路径 必须是绝对路径: {输出路径}")
    源表 = [str(p) for p in 源文件清单]
    非绝对 = [p for p in 源表 if not Path(p).is_absolute()]
    if 非绝对:
        return _失败("参数不合法", f"源文件清单必须是绝对路径: {'、'.join(非绝对[:5])}")
    不存在 = [p for p in 源表 if not Path(p).is_file()]
    if 不存在:
        return _失败("参数不合法", f"源文件不存在: {'、'.join(不存在[:5])}")
    swiftc = _查找工具("swiftc")
    if not swiftc:
        return _失败("提供者不可用", "swiftc 未找到（需 Xcode 命令行工具）")

    输出 = Path(str(输出路径).strip())
    输出.parent.mkdir(parents=True, exist_ok=True)
    命令行 = [swiftc] + 源表 + ["-o", str(输出)]
    if isinstance(目标架构, str) and 目标架构.strip():
        命令行 += ["-target", f"{目标架构.strip()}-apple-macosx"]
    if isinstance(优化级别, str) and 优化级别.strip():
        命令行.append(优化级别.strip())
    if isinstance(附加参数, list):
        命令行 += [str(x) for x in 附加参数]

    try:
        码, 出, 错 = _跑(命令行, 超时秒=float(超时秒 or 默认超时秒))
    except TimeoutError as 异常:
        return _失败("超时", str(异常), 可重试=真)
    except OSError as 异常:
        return _失败("提供者不可用", str(异常))
    except ValueError as 异常:
        return _失败("参数不合法", str(异常))

    诊断 = _解析诊断(错 or 出)
    错误项 = [d for d in 诊断 if d["级别"] == "error"]
    if 码 != 0 or 错误项:
        return _失败("编译失败",
                     f"swiftc 退出码 {码}；错误 {len(错误项)} 条："
                     + "；".join(f"{d['文件']}:{d['行']} {d['信息']}" for d in 错误项[:5]),
                     可重试=假)
    if not 输出.is_file():
        return _失败("编译失败", f"swiftc 报告成功但未产出可执行文件: {输出}")
    return 结果.成功结果({
        "可执行文件": str(输出), "字节数": 输出.stat().st_size,
        "诊断": 诊断, "警告数": len([d for d in 诊断 if d["级别"] == "warning"]),
        "swiftc 输出": (出 or "").strip()[:2000],
    })


def 签名制品(*, 应用路径: str = None, 超时秒: float = 120.0) -> 结果:
    """adhoc 签名应用包（codesign -s - --force --deep）。只做这一档。"""
    if not isinstance(应用路径, str) or not 应用路径.strip():
        return _失败("参数不合法", "应用路径 必须是非空文本")
    目标 = Path(str(应用路径).strip())
    if not 目标.exists():
        return _失败("参数不合法", f"应用路径不存在: {目标}")
    codesign = _查找工具("codesign")
    if not codesign:
        return _失败("提供者不可用", "codesign 未找到（需 macOS 系统工具）")
    try:
        码, 出, 错 = _跑([codesign, "--force", "--deep", "--sign", "-", str(目标)],
                        超时秒=float(超时秒 or 120))
    except TimeoutError as 异常:
        return _失败("超时", str(异常), 可重试=真)
    except OSError as 异常:
        return _失败("提供者不可用", str(异常))
    except ValueError as 异常:
        return _失败("参数不合法", str(异常))
    if 码 != 0:
        return _失败("签名失败", f"codesign 退出码 {码}: {(错 or 出).strip()[:300]}")
    return _结果_已完成(目标, 档位="adhoc")


def _结果_已完成(目标: Path, *, 档位: str) -> 结果:
    校验 = 校验签名(应用路径=str(目标))
    return 结果.成功结果({
        "应用路径": str(目标), "签名档位": 档位, "已签名": 真,
        "校验通过": bool(校验.成功),
        "校验详情": (校验.值 or {}) if 校验.成功 else {"错误码": 校验.错误码,
                                                "错误说明": 校验.错误说明},
    })


def 校验签名(*, 应用路径: str = None, 超时秒: float = 60.0) -> 结果:
    """codesign --verify --deep --strict 校验签名；不过如实回诊断。"""
    if not isinstance(应用路径, str) or not 应用路径.strip():
        return _失败("参数不合法", "应用路径 必须是非空文本")
    目标 = Path(str(应用路径).strip())
    if not 目标.exists():
        return _失败("参数不合法", f"应用路径不存在: {目标}")
    codesign = _查找工具("codesign")
    if not codesign:
        return _失败("提供者不可用", "codesign 未找到（需 macOS 系统工具）")
    try:
        码, 出, 错 = _跑([codesign, "--verify", "--deep", "--strict", "--verbose=2",
                        str(目标)], 超时秒=float(超时秒 or 60))
    except TimeoutError as 异常:
        return _失败("超时", str(异常), 可重试=真)
    except OSError as 异常:
        return _失败("提供者不可用", str(异常))
    except ValueError as 异常:
        return _失败("参数不合法", str(异常))
    诊断 = (错 or 出).strip()
    if 码 != 0:
        return _失败("校验失败", f"codesign --verify 退出码 {码}: {诊断[:300]}")
    return 结果.成功结果({"应用路径": str(目标), "校验通过": 真, "退出码": 码,
                     "诊断": 诊断[:500]})
