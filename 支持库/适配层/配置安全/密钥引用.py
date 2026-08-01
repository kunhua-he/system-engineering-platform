"""配置密钥引用边界：环境变量引用与运行时解析。

规则：配置文件不得保存明文密钥；搜索器/说明书/日志/错误信息不得显示
密钥值；进程启动参数不得直接暴露敏感值；敏感配置读取后只允许传给
声明需要它的提供者；不允许任意模块读取全部环境变量；配置访问必须有
来源和权限记录；缺少环境变量时必须明确失败。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# 敏感配置关键词表（适配层自持，避免反向依赖项目适配层）
敏感关键词表 = ("密码", "口令", "令牌", "私钥", "密钥", "token", "secret", "password", "private_key")


@dataclass
class 密钥解析结果:
    """一次密钥解析的结果。"""

    成功: bool = False
    值: str = ""
    错误码: str = ""
    错误说明: str = ""
    来源: str = ""


@dataclass
class 访问记录:
    """一次敏感配置访问记录。"""

    配置名: str
    请求方: str
    时间: str
    结果: str  # 允许/拒绝


class 密钥引用解析器:
    """密钥引用解析器：环境变量名 → 运行时值（敏感值只在内存）。"""

    def __init__(self) -> None:
        self.访问记录表: list[访问记录] = []
        self.内存值表: dict[str, str] = {}

    def 解析(self, 配置名: str, 引用值: str, *, 请求方: str) -> 密钥解析结果:
        """解析敏感配置：引用值必须是环境变量名（或 环境变量名:引用 格式）。

        缺少环境变量时必须明确失败；访问记录来源与权限。
        """
        import time as _时间

        # 疑似明文密钥直接拒绝（不允许明文配置）
        from 支持库.适配层.脱敏模式 import 密钥片段模式
        if 密钥片段模式.search(引用值) or len(引用值) >= 20:
            self.访问记录表.append(访问记录(配置名, 请求方, _时间.strftime("%H:%M:%S"), "拒绝（疑似明文）"))
            return 密钥解析结果(成功=False, 错误码="敏感配置不合法", 错误说明=f"{配置名} 疑似明文密钥，只允许环境变量名")

        # 允许格式：环境变量名 或 前缀:环境变量名
        环境变量名 = 引用值.split(":", 1)[-1].strip()
        if not 环境变量名 or not 环境变量名.isidentifier():
            self.访问记录表.append(访问记录(配置名, 请求方, _时间.strftime("%H:%M:%S"), "拒绝（非法引用）"))
            return 密钥解析结果(成功=False, 错误码="敏感配置不合法", 错误说明=f"{配置名} 引用必须是非空环境变量名")

        # 运行时解析：环境变量 → 内存
        if 环境变量名 in os.environ:
            值 = os.environ[环境变量名]
            if not 值:
                self.访问记录表.append(访问记录(配置名, 请求方, _时间.strftime("%H:%M:%S"), "拒绝（环境变量为空）"))
                return 密钥解析结果(成功=False, 错误码="敏感配置缺失", 错误说明=f"环境变量 {环境变量名} 为空")
            self.内存值表[环境变量名] = 值  # 敏感值只在内存
            self.访问记录表.append(访问记录(配置名, 请求方, _时间.strftime("%H:%M:%S"), "允许"))
            return 密钥解析结果(成功=True, 值=值, 来源=f"环境变量:{环境变量名}")

        self.访问记录表.append(访问记录(配置名, 请求方, _时间.strftime("%H:%M:%S"), "拒绝（环境变量缺失）"))
        return 密钥解析结果(成功=False, 错误码="敏感配置缺失", 错误说明=f"缺少环境变量: {环境变量名}", 来源=f"环境变量:{环境变量名}")

    def 提供值给(self, 环境变量名: str, 接收方: str, 允许接收方表: set[str] | None = None) -> bool:
        """敏感值只允许传给声明需要它的提供者（接收方白名单）。"""
        if 环境变量名 not in self.内存值表:
            return False
        if 允许接收方表 is not None and 接收方 not in 允许接收方表:
            return False
        return True

    def 查询访问记录(self) -> list[dict[str, str]]:
        return [{"配置名": 记录.配置名, "请求方": 记录.请求方, "时间": 记录.时间, "结果": 记录.结果}
                for 记录 in self.访问记录表]


def 校验引用完整性(配置: dict[str, Any]) -> list[str]:
    """校验敏感配置全部为合法引用（禁止明文）；返回问题列表。"""
    问题列表 = []
    from 支持库.适配层.脱敏模式 import 密钥片段模式
    for 名称, 值 in 配置.items():
        if any(关键词 in 名称.lower() for 关键词 in 敏感关键词表):
            if not isinstance(值, str):
                问题列表.append(f"{名称} 必须是文本引用")
                continue
            if 密钥片段模式.search(值):
                问题列表.append(f"{名称} 疑似明文密钥（应使用环境变量名）")
            elif not 值.split(":", 1)[-1].strip().isidentifier():
                问题列表.append(f"{名称} 引用不是合法环境变量名: {值}")
    return 问题列表
