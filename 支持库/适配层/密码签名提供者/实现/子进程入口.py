"""子进程入口：密码签名提供者的独立进程 Worker。

本文件只在独立子进程中运行，由 提供者管理器.py 通过 subprocess 启动。
子进程内才允许 import cryptography（Rust 原生扩展）；主进程、测试器与
后端绝不加载。每次调用启动一次性子进程，执行后 os._exit(0) 直接退出，
跳过解释器关闭阶段的原生模块销毁，无残留。

本文件完全自包含：不经过 支持库.适配层 包链（该链会连带导入平台旧
密码适配并提前加载 cryptography），只以同级模块方式导入 密码操作.py。
cryptography 的 import 全部发生在 密码操作._检查可用 内（先查环境变量
再导入），缺环境时返回稳定的 提供者不可用 而非崩溃。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "生成密钥对"|"签名"|"验证签名"|"公钥指纹"|"对称加密"|"对称解密"|"版本", ...参数}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import json
import os
import sys

from 密码操作 import (
    提供者操作异常,
    公钥指纹,
    对称加密,
    对称解密,
    生成密钥对,
    签名,
    验证签名,
    获取版本,
)


def _响应(成功: bool, 值=None, 错误码: str = "", 错误说明: str = "") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False)


def 主循环() -> int:
    """读一行请求，执行，写一行响应，返回退出码。"""
    请求行 = sys.stdin.readline()
    if not 请求行.strip():
        print(_响应(False, 错误码="参数不合法", 错误说明="空请求"))
        return 0
    try:
        请求 = json.loads(请求行)
    except json.JSONDecodeError as 错误:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"请求不是合法 JSON: {错误}"))
        return 0
    操作 = str(请求.get("操作") or "")
    try:
        if 操作 == "生成密钥对":
            值 = 生成密钥对()
        elif 操作 == "签名":
            值 = 签名(str(请求.get("私钥PEM") or ""), str(请求.get("数据b64") or ""))
        elif 操作 == "验证签名":
            值 = 验证签名(
                str(请求.get("公钥PEM") or ""),
                str(请求.get("数据b64") or ""),
                str(请求.get("签名hex") or ""),
            )
        elif 操作 == "公钥指纹":
            值 = 公钥指纹(str(请求.get("公钥PEM") or ""))
        elif 操作 == "对称加密":
            值 = 对称加密(
                str(请求.get("明文b64") or ""),
                str(请求.get("密钥b64") or ""),
                str(请求.get("模式") or ""),
                str(请求.get("初始向量b64") or ""),
                str(请求.get("附加数据b64") or ""),
            )
        elif 操作 == "对称解密":
            值 = 对称解密(
                str(请求.get("密文b64") or ""),
                str(请求.get("密钥b64") or ""),
                str(请求.get("模式") or ""),
                str(请求.get("初始向量b64") or ""),
                str(请求.get("附加数据b64") or ""),
            )
        elif 操作 == "版本":
            值 = 获取版本()
        else:
            print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 '{操作}'"))
            return 0
    except 提供者操作异常 as 错误:
        print(_响应(False, 错误码=错误.错误码, 错误说明=错误.错误说明))
        return 0
    except Exception as 错误:  # 任何未预期异常都转稳定响应
        print(_响应(False, 错误码="提供者崩溃", 错误说明=f"子进程执行异常: {错误}"))
        return 0
    print(_响应(True, 值=值))
    return 0


if __name__ == "__main__":
    主循环()
    sys.stdout.flush()
    # 直接退出，跳过解释器关闭阶段的 cryptography 原生模块销毁
    os._exit(0)
