"""真实密钥提供者边界：环境变量与 macOS 钥匙串提供者。

密钥值只在调用内存出现：读取后的值仅保存在本对象内存表中，绝不写入
任何文件；日志、说明书、Agent 数据、制品文本一律经 脱敏/泄漏检查
拦截。钥匙串读取为真实 security 命令子进程调用，失败如实记录
KEYCHAIN_UNAVAILABLE，禁止桩实现。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

环境变量前缀 = "环境变量:"
钥匙串前缀 = "钥匙串:"
掩码 = "***"
错误码_成功 = ""
错误码_引用不合法 = "REFERENCE_INVALID"
错误码_密钥缺失 = "SECRET_MISSING"
错误码_钥匙串不可用 = "KEYCHAIN_UNAVAILABLE"
引用模式 = re.compile(r"\{([^{}]*)\}")


@dataclass
class 环境变量句柄:
    """一次 .env 配置会话；值只存在句柄内存，关闭后立即清空。"""

    _变量表: dict[str, str]
    来源: str = ""
    _已关闭: bool = False

    def 读取(self, 变量名: str) -> tuple[bool, str, str]:
        if self._已关闭:
            return (False, "", "HANDLE_CLOSED")
        if not isinstance(变量名, str) or not 变量名 or not 变量名.isidentifier():
            return (False, "", 错误码_引用不合法)
        值 = self._变量表.get(变量名)
        return (True, 值, 错误码_成功) if 值 else (False, "", 错误码_密钥缺失)

    def 关闭(self) -> None:
        self._变量表.clear()
        self._已关闭 = True

    def __enter__(self) -> "环境变量句柄":
        return self

    def __exit__(self, _类型, _值, _回溯) -> None:
        self.关闭()

    def __del__(self) -> None:
        # 兜底释放；调用方应优先显式关闭或使用 with。
        self.关闭()


def _解析环境文件(路径: Path) -> tuple[bool, dict[str, str], str]:
    """解析 .env 的 KEY=VALUE 行，不执行表达式、不展开变量、不修改 os.environ。"""
    变量表: dict[str, str] = {}
    try:
        行列表 = 路径.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as 错误:
        return (False, {}, f"ENV_READ_FAILED:{错误.__class__.__name__}")
    for 行号, 原行 in enumerate(行列表, 1):
        行 = 原行.strip()
        if not 行 or 行.startswith("#"):
            continue
        if 行.startswith("export "):
            行 = 行[7:].lstrip()
        if "=" not in 行:
            return (False, {}, f"ENV_SYNTAX_INVALID:{行号}")
        变量名, 值 = (片段.strip() for 片段 in 行.split("=", 1))
        if not 变量名.isidentifier():
            return (False, {}, f"ENV_NAME_INVALID:{行号}")
        值 = 值.strip()
        if len(值) >= 2 and 值[0] == 值[-1] and 值[0] in ("'", '"'):
            值 = 值[1:-1]
        变量表[变量名] = 值
    return (True, 变量表, 错误码_成功)


def 打开环境配置(文件路径: str = ".env") -> tuple[bool, 环境变量句柄 | None, str]:
    """打开 .env 为内存句柄；不覆盖进程环境，不返回明文到日志。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return (False, None, 错误码_引用不合法)
    成功, 变量表, 错误码 = _解析环境文件(Path(文件路径).expanduser())
    return (成功, 环境变量句柄(变量表, 文件路径) if 成功 else None, 错误码)


def 读取环境配置(句柄: 环境变量句柄, 变量名: str) -> tuple[bool, str, str]:
    """按变量名读取句柄；同一服务商多个 key 通过不同变量名隔离。"""
    if not isinstance(句柄, 环境变量句柄):
        return (False, "", 错误码_引用不合法)
    return 句柄.读取(变量名)


def 关闭环境配置(句柄: 环境变量句柄) -> tuple[bool, None, str]:
    """关闭并清空句柄内存。"""
    if not isinstance(句柄, 环境变量句柄):
        return (False, None, 错误码_引用不合法)
    句柄.关闭()
    return (True, None, 错误码_成功)


def 拆分引用(引用: str) -> tuple[str, list[str]]:
    """按前缀拆分引用：返回 (提供者类型, 参数表)；非法返回 ("", [])。"""
    if 引用.startswith(环境变量前缀):
        键 = 引用[len(环境变量前缀):].strip()
        return ("环境变量", [键]) if 键 else ("", [])
    if 引用.startswith(钥匙串前缀):
        参数 = [段.strip() for 段 in 引用[len(钥匙串前缀):].split(":")]
        if len(参数) == 2 and all(参数):
            return ("钥匙串", 参数)
    return ("", [])


class 密钥提供者:
    """统一密钥提供者：环境变量 / macOS 钥匙串；密钥值只在内存。"""

    def __init__(self) -> None:
        self.内存值表: dict[str, str] = {}  # 引用 -> 值，只存在于内存
        self.钥匙串命令路径 = shutil.which("security")

    def 读取(self, 引用: str) -> tuple[bool, str, str]:
        """读取密钥：引用为 环境变量:键 或 钥匙串:账户:服务。

        返回 (成功, 值, 错误码)；密钥值只出现在本次返回中。
        """
        提供者类型, 参数 = 拆分引用(引用)
        if not 提供者类型:
            return (False, "", 错误码_引用不合法)
        if 提供者类型 == "环境变量":
            return self._读取环境变量(参数[0])
        return self._读取钥匙串(参数[0], 参数[1])

    def _读取环境变量(self, 键: str) -> tuple[bool, str, str]:
        """环境变量提供者：从 os.environ 真实读取。"""
        值 = os.environ.get(键)
        if not 值:  # 缺失或空值：空值密钥不安全，一律失败
            return (False, "", 错误码_密钥缺失)
        self.内存值表[f"环境变量:{键}"] = 值
        return (True, 值, 错误码_成功)

    def _读取钥匙串(self, 账户: str, 服务: str) -> tuple[bool, str, str]:
        """macOS 钥匙串提供者：真实调用 security 命令（等价 2>/dev/null）。"""
        if not self.钥匙串命令路径:
            return (False, "", 错误码_钥匙串不可用)
        try:
            执行结果 = subprocess.run(
                [self.钥匙串命令路径, "find-generic-password",
                 "-a", 账户, "-s", 服务, "-w"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return (False, "", 错误码_钥匙串不可用)
        if 执行结果.returncode != 0:  # 找不到凭据 / 权限拒绝 / 钥匙串锁定
            return (False, "", 错误码_钥匙串不可用)
        值 = 执行结果.stdout.decode("utf-8", errors="replace").rstrip("\n")
        if not 值:
            return (False, "", 错误码_钥匙串不可用)
        self.内存值表[f"钥匙串:{账户}:{服务}"] = 值
        return (True, 值, 错误码_成功)

    def 脱敏(self, 文本: str) -> str:
        """把文本中出现的密钥值替换为 ***（真实查找替换，长值优先）。"""
        for 值 in sorted(self.内存值表.values(), key=len, reverse=True):
            if 值:
                文本 = 文本.replace(值, 掩码)
        return 文本

    def 泄漏检查(self, 文本集合: dict[str, str] | list[str]) -> list[str]:
        """检查文本集合是否包含密钥值，返回泄漏项列表。

        集合为 {名称: 文本} 时返回名称；为纯文本列表时返回索引；
        存在空值密钥时全部项直接判定不安全。
        """
        有空格密钥 = any(not 值 for 值 in self.内存值表.values())
        if 有空格密钥:
            return (list(文本集合.keys()) if isinstance(文本集合, dict)
                    else [str(索引) for 索引 in range(len(文本集合))])
        if isinstance(文本集合, dict):
            return [名称 for 名称, 文本 in 文本集合.items()
                    if any(值 and 值 in 文本 for 值 in self.内存值表.values())]
        return [str(索引) for 索引, 文本 in enumerate(文本集合)
                if any(值 and 值 in 文本 for 值 in self.内存值表.values())]

    def 提取引用(self, 配置文本: str) -> list[str]:
        """从配置文本提取 {环境变量:键} / {钥匙串:账户:服务} 引用，不返回值。"""
        引用列表: list[str] = []
        for 候选 in 引用模式.findall(配置文本):
            提供者类型, 参数 = 拆分引用(候选.strip())
            if 提供者类型:
                引用列表.append(f"{提供者类型}:{':'.join(参数)}")
        return 引用列表
