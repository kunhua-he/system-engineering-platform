"""配置校验：结构校验与敏感配置检测。

校验：必填配置缺失报告、配置类型错误报告、未知配置项报告、
疑似明文密钥检测（警告或失败）。禁止未知字段静默接受；
禁止缺失必填配置自动伪造默认值。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 敏感键名判定走唯一腿（`公共契约/基础类型/字段名册.py`）：本模块**不自持关键词表**
# —— 2026-09-23 收口前它是三份相同 `敏感关键词表` 之一（漏 `凭证`/`api_key`/`credential`）。
# 唯一腿只能落 `公共契约`：项目适配层按分层**不许**依赖 `支持库`
# （见 `运行核心/依赖防火墙.py` 允许依赖表），而 `公共契约` 是它本来就允许的层。
from 公共契约.基础类型.字段名册 import 是敏感键名

# 疑似明文密钥值特征：长度 >= 12 且含字母数字混合（如 ghp_xxx / sk-xxx）
明文值模式 = re.compile(r"^(gh[pous]_|sk-|eyJ|AKIA|-----BEGIN)", re.IGNORECASE)


@dataclass
class 配置校验结果:
    """一次配置校验的结果。"""

    成功: bool = False
    问题列表: list[str] = field(default_factory=list)
    警告列表: list[str] = field(default_factory=list)
    敏感配置名列表: list[str] = field(default_factory=list)


def 校验配置(
    配置: dict[str, Any],
    *,
    声明表: dict[str, dict] | None = None,
    拒绝明文密钥: bool = True,
) -> 配置校验结果:
    """校验配置。

    声明表：{配置名: {"类型": "文本/整数/布尔/列表/字典", "必填": bool}}。
    未提供声明表时只做敏感检测与基本类型检查。
    """
    结果 = 配置校验结果()
    声明表 = 声明表 or {}

    # 1. 未知配置项报告
    if 声明表:
        for 名称 in 配置:
            if 名称 not in 声明表:
                结果.问题列表.append(f"未知配置项: {名称}")

    # 2. 必填缺失报告
    for 名称, 声明 in 声明表.items():
        if 声明.get("必填") and 名称 not in 配置:
            结果.问题列表.append(f"必填配置缺失: {名称}")

    # 3. 类型错误报告
    类型映射 = {
        "文本": str, "整数": int, "布尔": bool, "列表": list, "字典": dict,
        "数字": (int, float),
    }
    for 名称, 声明 in 声明表.items():
        if 名称 not in 配置:
            continue
        期望类型 = 声明.get("类型", "")
        期望类 = 类型映射.get(期望类型)
        if 期望类 is None:
            continue
        if 期望类型 == "数字":
            # 数字：整数或浮点，排除布尔
            类型通过 = (isinstance(配置[名称], (int, float))
                        and not isinstance(配置[名称], bool))
        else:
            类型通过 = isinstance(配置[名称], 期望类)
        if not 类型通过:
            结果.问题列表.append(
                f"配置类型错误: {名称} 期望 {期望类型}，实际 {type(配置[名称]).__name__}"
            )

    # 4. 敏感配置检测（配置名关键词 + 明文值特征）
    for 名称, 值 in 配置.items():
        是敏感名 = 是敏感键名(名称)
        if 是敏感名:
            结果.敏感配置名列表.append(名称)
        if 是敏感名 and isinstance(值, str) and 明文值模式.match(值):
            消息 = f"疑似明文密钥: {名称} 的值疑似真实密钥（应改为环境变量名或外部密钥引用）"
            if 拒绝明文密钥:
                结果.问题列表.append(消息)
            else:
                结果.警告列表.append(消息)
        elif 是敏感名 and isinstance(值, str) and len(值) >= 20 and any(c.isdigit() for c in 值) and any(c.isalpha() for c in 值):
            消息 = f"疑似明文密钥: {名称} 的值过长且混合字符（应使用环境变量名）"
            if 拒绝明文密钥:
                结果.问题列表.append(消息)
            else:
                结果.警告列表.append(消息)

    结果.成功 = not 结果.问题列表
    return 结果
