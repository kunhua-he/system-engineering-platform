"""密码操作：cryptography 原子操作，只在隔离子进程内执行。

本文件内才允许 import cryptography（Rust 原生扩展）。主进程、测试器与
后端绝不加载本文件；子进程入口.py 启动后按需调用，执行完由 os._exit(0)
直接退出，跳过解释器关闭阶段的原生模块销毁，无残留。

禁用注入：环境变量 密码签名提供者_禁用库=cryptography 时全部操作返回
提供者不可用（测试用依赖注入，禁止修改 sys.modules）。cryptography 的
import 一律在 _检查可用 内按需执行，先查环境变量再导入，保证缺环境时
返回稳定的 提供者不可用 而非崩溃。
"""

from __future__ import annotations

import base64
import hashlib
import os

禁用环境变量名 = "密码签名提供者_禁用库"


class 提供者操作异常(Exception):
    """子进程内业务异常：携带稳定错误码与错误说明。"""

    def __init__(self, 错误码: str, 错误说明: str) -> None:
        super().__init__(错误说明)
        self.错误码 = 错误码
        self.错误说明 = 错误说明


def _读取禁用库表() -> set[str]:
    return {库名.strip() for 库名 in os.environ.get(禁用环境变量名, "").split(",") if 库名.strip()}


def _检查可用() -> None:
    """cryptography 不可用或被禁用 → 提供者不可用。"""
    if "cryptography" in _读取禁用库表():
        raise 提供者操作异常("提供者不可用", "cryptography 已被环境变量禁用")
    try:
        import cryptography  # noqa: F401
    except ImportError as 错误:
        raise 提供者操作异常("提供者不可用", f"cryptography 未安装: {错误}") from 错误


def _解码数据(数据b64: str) -> bytes:
    if not isinstance(数据b64, str) or not 数据b64:
        raise 提供者操作异常("参数不合法", "数据b64 必须是非空文本")
    try:
        return base64.b64decode(数据b64, validate=True)
    except Exception as 错误:
        raise 提供者操作异常("参数不合法", f"数据b64 不是合法 base64: {错误}") from 错误


def 生成密钥对() -> dict[str, str]:
    """生成 Ed25519 密钥对，返回 {私钥PEM, 公钥PEM}。"""
    _检查可用()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        私钥 = Ed25519PrivateKey.generate()
        私钥PEM = 私钥.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        公钥PEM = 私钥.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
    except Exception as 错误:
        raise 提供者操作异常("生成失败", f"Ed25519 密钥生成失败: {错误}") from 错误
    return {"私钥PEM": 私钥PEM, "公钥PEM": 公钥PEM}


def 签名(私钥PEM: str, 数据b64: str) -> str:
    """Ed25519 签名，返回十六进制签名。"""
    _检查可用()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not isinstance(私钥PEM, str) or not 私钥PEM.strip():
        raise 提供者操作异常("参数不合法", "私钥PEM 必须是非空文本")
    try:
        私钥 = serialization.load_pem_private_key(私钥PEM.encode("ascii"), password=None)
    except Exception as 错误:
        raise 提供者操作异常("参数不合法", f"私钥PEM 无法解析: {错误}") from 错误
    if not isinstance(私钥, Ed25519PrivateKey):
        raise 提供者操作异常("参数不合法", "私钥PEM 不是 Ed25519 私钥")
    return 私钥.sign(_解码数据(数据b64)).hex()


def 验证签名(公钥PEM: str, 数据b64: str, 签名hex: str) -> bool:
    """验证 Ed25519 签名；签名不匹配返回 False（不抛异常）。"""
    _检查可用()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(公钥PEM, str) or not 公钥PEM.strip():
        raise 提供者操作异常("参数不合法", "公钥PEM 必须是非空文本")
    try:
        公钥 = serialization.load_pem_public_key(公钥PEM.encode("ascii"))
    except Exception as 错误:
        raise 提供者操作异常("参数不合法", f"公钥PEM 无法解析: {错误}") from 错误
    if not isinstance(公钥, Ed25519PublicKey):
        raise 提供者操作异常("参数不合法", "公钥PEM 不是 Ed25519 公钥")
    if not isinstance(签名hex, str) or not 签名hex:
        raise 提供者操作异常("参数不合法", "签名hex 必须是非空文本")
    try:
        签名字节 = bytes.fromhex(签名hex)
    except ValueError as 错误:
        raise 提供者操作异常("参数不合法", f"签名hex 不是合法十六进制: {错误}") from 错误
    try:
        公钥.verify(签名字节, _解码数据(数据b64))
        return True
    except Exception:
        return False


def 公钥指纹(公钥PEM: str) -> str:
    """公钥指纹：sha256(公钥PEM) 前 16 位（纯标准库 hashlib）。"""
    _检查可用()  # 保持提供者语义一致：提供者不可用时统一返回 提供者不可用
    if not isinstance(公钥PEM, str) or not 公钥PEM.strip():
        raise 提供者操作异常("参数不合法", "公钥PEM 必须是非空文本")
    return hashlib.sha256(公钥PEM.encode("utf-8")).hexdigest()[:16]


def 获取版本() -> dict[str, str]:
    """探测 cryptography 版本（诊断与测试的真实证据）。"""
    _检查可用()
    import cryptography

    return {"cryptography": cryptography.__version__}
