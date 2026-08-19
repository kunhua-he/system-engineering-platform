"""文件访问依赖采集器：基于 sys.addaudithook 的运行时实测依赖记录。

第 3 层文件级缓存依赖"运行时实测依赖记录"。本模块是可独立使用的采集器：
- 观测 open / os.listdir / os.scandir 事件，捕获真实读取的文件与扫描的目录；
- 观测 socket 事件，标记网络访问弱依赖；
- pyc 路径规范化为源 .py（依赖清单恒存 .py）；
- 临时目录（TMPDIR/mkdtemp/工程缓存/验证运行）内的读写全部排除；
- 纯内存收集，不写任何文件，避免递归污染与自身记录。

本模块不接入 测试中心/运行测试.py 主流程，供将来文件级缓存子进程使用。
hook 回调内只做内存追加与纯字符串处理（os.path.abspath/commonpath、正则），
不触发 open/os.stat 等会产生新审计事件的操作，避免递归污染。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

采集器版本 = "1.0.0"

# 模块级单例标记：防重复 addaudithook（hook 不可移除，只能安装一次）
_已安装采集器 = None

# pyc 规范化：__pycache__/X.cpython-*.pyc → 源 X.py
# （支持 cpython-314 / cpython-314-pypy / cpython-314-opt 等附加后缀变体）
_pyc后缀模式 = re.compile(r"__pycache__[/\\]([^/\\]+)\.cpython-\d+[^/\\]*\.pyc$")

# 存在性探测调用特征（弱依赖静态扫描）
弱依赖特征模式表 = [
    (r"\.exists\s*\(", "exists()"),
    (r"\.is_file\s*\(", "is_file()"),
    (r"\.is_dir\s*\(", "is_dir()"),
    (r"\.getsize\s*\(", "getsize()"),
    (r"\.stat\s*\(", "stat()"),
]


def _构建默认排除目录表() -> list[str]:
    """默认排除：系统临时目录（TMPDIR/mkdtemp）与项目工程缓存（含验证运行）。

    用 realpath 解析符号链接（macOS /var → /private/var），否则临时目录
    mkdtemp 产物（路径走 /private/var/.../T）无法匹配 gettempdir 的 /var/.../T。
    """
    排除表 = [os.path.realpath(tempfile.gettempdir())]
    工程缓存 = Path(__file__).resolve().parents[1] / "工程缓存"
    if 工程缓存.is_dir():
        排除表.append(str(工程缓存))
    return 排除表


def 规范化pyc路径(路径: str) -> str:
    """pyc 规范化：路径含 __pycache__/X.cpython-*.pyc 时规范化为源 X.py。"""
    匹配 = _pyc后缀模式.search(路径)
    if 匹配:
        return 路径[:匹配.start()] + 匹配.group(1) + ".py"
    return 路径


class 文件访问采集器:
    """文件访问依赖采集器（纯内存收集，不写文件）。

    采集结束用 提取依赖清单() 获取读文件列表、目录列表、弱依赖标记、
    截断标记与网络标记。
    """

    def __init__(
        self,
        排除目录表: list[str] | None = None,
        最大记录数: int = 2000,
    ) -> None:
        if 排除目录表 is None:
            排除目录表 = _构建默认排除目录表()
        self.排除目录表 = [os.path.abspath(目录) for 目录 in 排除目录表]
        self.最大记录数 = 最大记录数
        self._读文件集合: set[str] = set()
        self._目录集合: set[str] = set()
        self._写入路径集合: set[str] = set()
        self._网络标记 = False
        self._截断标记 = False

    # ---- 审计回调（只做内存操作，不触发新审计事件） ----

    def _处理审计事件(self, 事件名: str, 参数: tuple) -> None:
        """sys.addaudithook 回调入口：按事件名分发。"""
        if 事件名 == "open":
            self._处理打开事件(参数)
        elif 事件名 in ("os.listdir", "os.scandir"):
            if 参数 and isinstance(参数[0], str):
                self._记录目录(参数[0])
        elif 事件名 in ("socket.__new__", "socket.connect"):
            self._网络标记 = True

    def _处理打开事件(self, 参数: tuple) -> None:
        if len(参数) < 2:
            return
        路径, 模式 = 参数[0], 参数[1]
        if isinstance(路径, int):  # fd 型 open 事件忽略
            return
        if not isinstance(路径, str):
            return
        flags = 参数[2] if len(参数) > 2 and isinstance(参数[2], int) else None
        规范化路径 = 规范化pyc路径(路径)
        操作 = self._判定读写(模式, flags)
        if 操作 == "读":
            self._记录读取(规范化路径)
        elif 操作 == "写":
            self._记录写入(规范化路径)
        elif 操作 == "读写":
            self._记录读取(规范化路径)
            self._记录写入(规范化路径)

    def _判定读写(self, 模式: object, flags: object) -> str | None:
        """判定 open 事件读写：字符串 mode 直接判；os.open 时 mode=None 解码 flags。

        flags 低位掩码：0=只读/1=只写/2=读写（高位含 O_CLOEXEC 等附加位，需掩码）。
        """
        if isinstance(模式, str):
            首字符 = 模式[:1]
            if 首字符 == "r":
                return "读写" if "+" in 模式 else "读"
            if 首字符 in ("w", "a", "x"):
                return "写"
            return None
        if 模式 is None and isinstance(flags, int):
            低位 = flags & (getattr(os, "O_ACCMODE", 0o3) or 0o3)
            if 低位 == 0:
                return "读"
            if 低位 == 1:
                return "写"
            if 低位 == 2:
                return "读写"
        return None

    # ---- 记录（统一去重、排除、截断） ----

    def _在排除目录内(self, 绝对路径: str) -> bool:
        解析路径 = os.path.realpath(绝对路径)
        for 目录 in self.排除目录表:
            try:
                if os.path.commonpath([解析路径, 目录]) == 目录:
                    return True
            except ValueError:
                continue
        return False

    def _记录读取(self, 路径: str) -> None:
        if self._截断标记:
            return
        绝对路径 = os.path.abspath(路径)
        if self._在排除目录内(绝对路径) or 绝对路径 in self._读文件集合:
            return
        if self._记录数() >= self.最大记录数:
            self._截断标记 = True
            return
        self._读文件集合.add(绝对路径)

    def _记录目录(self, 路径: str) -> None:
        if self._截断标记:
            return
        绝对路径 = os.path.abspath(路径)
        if self._在排除目录内(绝对路径) or 绝对路径 in self._目录集合:
            return
        if self._记录数() >= self.最大记录数:
            self._截断标记 = True
            return
        self._目录集合.add(绝对路径)

    def _记录写入(self, 路径: str) -> None:
        if self._截断标记:
            return
        绝对路径 = os.path.abspath(路径)
        if self._在排除目录内(绝对路径) or 绝对路径 in self._写入路径集合:
            return
        if self._记录数() >= self.最大记录数:
            self._截断标记 = True
            return
        self._写入路径集合.add(绝对路径)

    def _记录数(self) -> int:
        return len(self._读文件集合) + len(self._目录集合) + len(self._写入路径集合)

    # ---- 对外接口 ----

    def 提取依赖清单(self) -> dict:
        """提取依赖清单：读文件列表、目录列表、弱依赖标记、截断标记、网络标记。

        弱依赖标记：存在"测试开始前已存在且被写"的文件
        （写入路径在提取时仍存在，视为采集前已存在被写）。
        """
        已存在且被写 = [
            路径 for 路径 in sorted(self._写入路径集合) if os.path.exists(路径)
        ]
        return {
            "读文件列表": sorted(self._读文件集合),
            "目录列表": sorted(self._目录集合),
            "已存在且被写列表": 已存在且被写,
            "弱依赖标记": bool(已存在且被写),
            "截断标记": self._截断标记,
            "网络标记": self._网络标记,
        }

    def 清空记录(self) -> None:
        """清空已收集记录（测试隔离辅助；不卸载 hook，hook 不可移除）。"""
        self._读文件集合.clear()
        self._目录集合.clear()
        self._写入路径集合.clear()
        self._网络标记 = False
        self._截断标记 = False


def 安装采集器(
    排除目录表: list[str] | None = None,
    最大记录数: int = 2000,
) -> 文件访问采集器:
    """安装采集器：sys.addaudithook 注册回调；防重复安装（模块级单例）。

    首次安装时的参数生效；后续调用返回同一实例（hook 不可移除，避免叠加）。
    """
    global _已安装采集器
    if _已安装采集器 is None:
        _已安装采集器 = 文件访问采集器(
            排除目录表=排除目录表,
            最大记录数=最大记录数,
        )
        sys.addaudithook(_已安装采集器._处理审计事件)
    return _已安装采集器


def 静态扫描弱依赖(源码文本: str) -> list[str]:
    """静态扫描弱依赖：正则匹配存在性探测调用，返回命中特征列表。

    命中 exists()/is_file()/is_dir()/getsize()/stat() 时，对应路径
    宜标记为弱依赖（探测结果决定分支但内容未被读取）。
    """
    命中表: list[str] = []
    for 模式, 特征 in 弱依赖特征模式表:
        if re.search(模式, 源码文本):
            命中表.append(特征)
    return 命中表
