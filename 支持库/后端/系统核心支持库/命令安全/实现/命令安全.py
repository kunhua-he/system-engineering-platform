"""命令安全原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：危险命令检测（终端执行场景的提示层 + 高风险拦截，沙箱仍是唯一边界）。

迁移自 V3 `后端服务/应用层/核心/命令安全守卫.py`（薄壳化 1-2），保持检测语义不变：
- 20+ 危险模式：提权、关机重启、磁盘操作、文件系统破坏、Fork 炸弹、管道远程到 shell、写敏感路径
- 三层绕过检测：base64/hex 解码片段、$(...) 与反引号子命令、变量赋值拼接展开
- 递归深度上限 2

只做判定，不执行任何命令，不访问外部资源。
"""

from __future__ import annotations

import base64
import re

from 公共契约.基础类型.结果类型 import 结果

来源标识 = "命令安全"

输入长度上限 = 65536

危险模式列表: list[tuple[str, str]] = [
    # 提权
    (r"\bsudo\b", "sudo命令"),
    (r"\bsu\s", "su命令"),
    (r"\bpasswd\b", "passwd命令"),
    (r"\bvisudo\b", "visudo命令"),
    # 系统关机/重启
    (r"\b(shutdown|reboot|halt|poweroff|init\s+[06])\b", "系统关机/重启"),
    # 磁盘操作
    (r"\bmkfs\b", "格式化文件系统"),
    (r"\bfdisk\b", "磁盘分区操作"),
    (r"\bparted\b", "磁盘分区操作"),
    (r"\bdd\s+if=", "磁盘克隆(dd)"),
    (r">\s*/dev/(sd|hd|nvme|mmcblk|vd|xvd)", "写入块设备"),
    (r"\bmount\b", "挂载命令"),
    (r"\bumount\b", "卸载命令"),
    # 文件系统破坏性操作
    (r"\brm\s+.*-rf\s+/", "递归删除根文件系统"),
    (r"\brm\s+-rf\s+/", "递归删除根文件系统"),
    # 家目录递归删除（报告 BUG-08 实测漏项：rm -rf ~ / rm -rf $HOME / ${HOME}）
    # 只补真正漏的家目录形态：/、/*、dd if=、chmod -R 777 / 等实测已拦，不重复加规则。
    (r"\brm\s+[^;|&\n]*?(?:--recursive|-[a-z]*r[a-z]*)[^;|&\n]*?(?:\$\{HOME\}|\$HOME|(?<![\w/])~)",
     "递归删除家目录"),
    (r"\bchmod\s+(.*\s+)?777\s+/(\s|$)", "chmod 777 /"),
    (r"\bchown\s+.*\s+/", "对根目录执行chown"),
    # Fork 炸弹
    (r":\(\)\s*\{", "Fork炸弹"),
    # 管道远程内容到 shell
    (r"\b(curl|wget)\b.*\|\s*(?:ba)?sh", "将远程内容管道到shell"),
    (r"\b(bash|sh|zsh|ksh)\s+<\s*\(\s*(curl|wget)\b", "通过进程替换执行远程脚本"),
    # 写入敏感系统路径
    (r"\btee\b.*/etc/", "通过tee覆盖/etc"),
    (r">>?\s*/etc/", "通过重定向覆盖/etc"),
]

已编译模式: list[tuple[re.Pattern, str]] = [
    (re.compile(模式, re.IGNORECASE | re.DOTALL), 描述)
    for 模式, 描述 in 危险模式列表
]

最大递归深度 = 2

Base64字面量模式 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{8,}={0,2}(?![A-Za-z0-9+/=])")
Hex转义序列模式 = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")
子命令Dollar模式 = re.compile(r"\$\(([^)]+)\)")
子命令反引号模式 = re.compile(r"`([^`]+)`")
变量赋值模式 = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"]?)([^;&|\n\r]*)\2")


def 直接匹配(内容: str) -> str | None:
    """对单层内容跑危险模式列表，命中返回描述。"""
    for 编译模式, 描述 in 已编译模式:
        if 编译模式.search(内容):
            return 描述
    return None


def 提取解码片段(命令: str) -> list[str]:
    """提取 base64 字面量 / hex 转义序列并解码，供二次检测。"""
    片段列表: list[str] = []
    for 匹配 in Base64字面量模式.finditer(命令):
        候选 = 匹配.group(0)
        try:
            解码 = base64.b64decode(候选, validate=True).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if 解码 and 解码.strip() and 解码 != 候选:
            片段列表.append(解码)
    for 匹配 in Hex转义序列模式.finditer(命令):
        原始 = 匹配.group(0)
        try:
            字节 = bytes(bytearray(int(原始[索引 + 2:索引 + 4], 16) for 索引 in range(0, len(原始), 4)))
            解码 = 字节.decode("utf-8", errors="ignore")
        except Exception:
            continue
        if 解码 and 解码.strip():
            片段列表.append(解码)
    return 片段列表


def 提取子命令片段(命令: str) -> list[str]:
    """提取 $(...) 与反引号子命令片段，供递归检测。"""
    片段列表: list[str] = []
    for 匹配 in 子命令Dollar模式.finditer(命令):
        片段列表.append(匹配.group(1).strip())
    for 匹配 in 子命令反引号模式.finditer(命令):
        片段列表.append(匹配.group(1).strip())
    return [片段 for 片段 in 片段列表 if 片段]


def 展开变量拼接(命令: str) -> list[str]:
    """提取变量赋值并用值替换 $变量 引用，检测拼接型绕过。"""
    候选列表: list[str] = []
    for 匹配 in 变量赋值模式.finditer(命令):
        变量名 = 匹配.group(1)
        值 = 匹配.group(3).strip().strip("\"'")
        if not 值 or "${" in 值 or "$" in 值:
            continue
        展开 = 命令.replace(f"${变量名}", 值)
        if 展开 != 命令:
            候选列表.append(展开)
    return 候选列表


def _检测(命令: str, 深度: int) -> str | None:
    """内部递归检测：直接命中或绕过片段命中时返回描述。"""
    if not 命令 or not isinstance(命令, str):
        return None
    if 深度 > 最大递归深度:
        return None
    命令内容 = 命令.strip()
    直接命中 = 直接匹配(命令内容)
    if 直接命中:
        return 直接命中
    for 片段 in (
        提取解码片段(命令内容)
        + 提取子命令片段(命令内容)
        + 展开变量拼接(命令内容)
    ):
        子命中 = _检测(片段, 深度 + 1)
        if 子命中:
            return 子命中
    return None


def 检测危险命令(命令: str = None, 最大长度: int = None) -> 结果:
    """检测命令是否危险。返回 {危险, 原因}。

    危险 → {危险: True, 原因: "危险命令已拦截：<规则描述>"}；
    安全 → {危险: False, 原因: ""}。
    只做判定，不执行命令。
    """
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源=来源标识)
    上限 = 输入长度上限 if 最大长度 is None else int(最大长度)
    if 上限 > 0 and len(命令) > 上限:
        return 结果.失败("参数不合法", f"命令长度超过上限 {上限}", 来源=来源标识)
    命中 = _检测(命令, 0)
    if 命中:
        return 结果.成功结果({"危险": True, "原因": f"危险命令已拦截：{命中}"})
    return 结果.成功结果({"危险": False, "原因": ""})
