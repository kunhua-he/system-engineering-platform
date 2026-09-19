"""逐字稿队列常驻（LaunchAgent）安装 / 卸载 / 状态。

为什么要常驻：批量队列要跑十几小时，挂在交互式会话的后台进程上会被会话变化 SIGTERM 打断；
LaunchAgent 由系统托管，异常退出自动拉起，机器重启也会回来；队列本身支持断点续跑，不重复劳动。

LaunchAgent 定义由本脚本按调用方参数渲染（包内不留某次部署的 plist 运行产物，也不带任何
品牌标签与业务绝对路径）：标签 / Python 可执行 / 队列脚本 / 配置包 / 日志路径全部传参。

用法：
    python3.14 安装或卸载队列常驻.py 安装 --配置 队列配置.json
    python3.14 安装或卸载队列常驻.py 状态 --配置 队列配置.json
    python3.14 安装或卸载队列常驻.py 卸载
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

默认标签 = "com.example.zizhugao-queue"
本目录 = Path(__file__).resolve().parent
默认队列脚本 = 本目录 / "批量精校队列.py"
用户域 = f"gui/{os.getuid()}"


def 执行(命令: list[str]) -> tuple[int, str]:
    """跑一条命令，返回 (返回码, 输出)。"""
    完成 = subprocess.run(命令, capture_output=True, text=True)
    return 完成.returncode, (完成.stdout + 完成.stderr).strip()


def 渲染plist(标签: str, Python可执行: str, 队列脚本: Path, 配置路径: str,
            工作目录: Path, 输出日志: str, 错误日志: str) -> str:
    """按参数渲染 LaunchAgent plist（KeepAlive + RunAtLoad，与历史部署键一致）。"""
    参数行 = [Python可执行, str(队列脚本)]
    if 配置路径.strip():
        参数行 += ["--配置", 配置路径.strip()]
    参数元素 = "\n".join(f"        <string>{escape(元素)}</string>" for 元素 in 参数行)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{escape(标签)}</string>
    <key>ProgramArguments</key>
    <array>
{参数元素}
    </array>
    <key>WorkingDirectory</key>
    <string>{escape(str(工作目录))}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>15</integer>
    <key>StandardOutPath</key>
    <string>{escape(输出日志)}</string>
    <key>StandardErrorPath</key>
    <string>{escape(错误日志)}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string></string>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin</string>
    </dict>
</dict>
</plist>
"""


def 目标文件(标签: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{标签}.plist"


def 安装(参数: argparse.Namespace) -> int:
    队列脚本 = Path(参数.安装源).expanduser().resolve()
    if not 队列脚本.is_file():
        print(f"缺队列脚本：{队列脚本}（用 --安装源 指定）")
        return 1
    配置路径 = str(参数.配置).strip()
    if 配置路径 and not Path(配置路径).expanduser().is_file():
        print(f"缺配置包：{配置路径}（队列要求的口径见 批量精校队列.py 头部）")
        return 1
    目标 = 目标文件(参数.标签)
    目标.parent.mkdir(parents=True, exist_ok=True)
    目标.write_text(渲染plist(
        标签=参数.标签, Python可执行=str(参数.Python可执行),
        队列脚本=队列脚本, 配置路径=配置路径, 工作目录=队列脚本.parent,
        输出日志=str(参数.输出日志), 错误日志=str(参数.错误日志)), encoding="utf-8")
    执行(["launchctl", "bootout", f"{用户域}/{参数.标签}"])
    码, 输出 = 执行(["launchctl", "bootstrap", 用户域, str(目标)])
    if 码 != 0:
        print(f"装载失败：{输出}")
        return 1
    执行(["launchctl", "kickstart", "-k", f"{用户域}/{参数.标签}"])
    print(f"已安装并启动：{参数.标签}（定义：{目标}）")
    print("  队列脚本：", 队列脚本)
    print("  配置包：", 配置路径 or "（未指定：队列需自行读到环境变量）")
    if str(参数.日志路径).strip():
        print("  业务日志：", 参数.日志路径)
    print(f"  系统输出：{参数.输出日志}   系统错误：{参数.错误日志}")
    print(f"  卸载：python3.14 {Path(__file__).name} 卸载 --标签 {参数.标签}")
    return 0


def 卸载(参数: argparse.Namespace) -> int:
    码, 输出 = 执行(["launchctl", "bootout", f"{用户域}/{参数.标签}"])
    目标 = 目标文件(参数.标签)
    if 码 != 0 and not 目标.is_file():
        # 「本来就没装」不是失败：`launchctl bootout` 对未装载的标签必然非零
        # （`Could not find service … in domain for user`）。用 2 表「未做任何动作 ——
        # 没有东西可卸」，既不假绿（原实现丢弃返回码后无条件 `return 0`），也不假红。
        print(f"未安装：{参数.标签}（launchctl：{输出 or '无输出'}）")
        return 2
    if 码 != 0:
        # 定义文件在场却退不出服务 ⇒ 卸载**没成功**，必须让调用方看到（原先被丢弃）。
        print(f"卸载失败：{输出 or '无输出'}")
        return 1
    if 目标.is_file():
        try:
            目标.unlink()
        except OSError as 错:
            print(f"卸载失败：删除定义文件出错 —— {目标}：{错}")
            return 1
    print(f"已卸载：{参数.标签}（已出的稿子与缓存都不受影响）")
    return 0


def 状态(参数: argparse.Namespace) -> int:
    码, 输出 = 执行(["launchctl", "print", f"{用户域}/{参数.标签}"])
    if 码 != 0:
        print("未安装或未运行")
        return 1
    for 行 in 输出.splitlines():
        if any(键 in 行 for 键 in ("state =", "pid =", "runs =", "last exit")):
            print(" ", 行.strip())
    业务日志 = Path(str(参数.日志路径)).expanduser() if str(参数.日志路径).strip() else None
    if 业务日志 is not None and 业务日志.is_file():
        尾部 = 业务日志.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        print("  业务日志尾部：")
        for 行 in 尾部:
            print("   ", 行)
    return 0


def 命令行入口() -> int:
    解析 = argparse.ArgumentParser(description="逐字稿队列常驻（LaunchAgent）安装 / 卸载 / 状态")
    解析.add_argument("操作", nargs="?", default="状态", choices=["安装", "卸载", "状态"])
    解析.add_argument("--标签", default=默认标签,
                    help=f"LaunchAgent 标签（默认中性占位 {默认标签}；正式部署时传自己的标签）")
    解析.add_argument("--安装源", default=str(默认队列脚本),
                    help="队列脚本绝对路径（默认：与本脚本同目录的 批量精校队列.py）")
    解析.add_argument("--配置", default="", help="队列配置包 JSON 路径（安装时写进 ProgramArguments）")
    解析.add_argument("--日志路径", default="", help="队列业务日志绝对路径（状态时打印尾部）")
    解析.add_argument("--Python可执行", default=sys.executable, help="跑队列的 Python 绝对路径")
    解析.add_argument("--输出日志", default="", help="标准输出日志路径（默认 /tmp/<标签>.log）")
    解析.add_argument("--错误日志", default="", help="标准错误日志路径（默认 /tmp/<标签>.err）")
    参数 = 解析.parse_args()
    参数.输出日志 = 参数.输出日志.strip() or f"/tmp/{参数.标签}.log"
    参数.错误日志 = 参数.错误日志.strip() or f"/tmp/{参数.标签}.err"
    参数.配置 = str(参数.配置).strip()
    表 = {"安装": 安装, "卸载": 卸载, "状态": 状态}
    return 表[参数.操作](参数)


if __name__ == "__main__":
    sys.exit(命令行入口())
