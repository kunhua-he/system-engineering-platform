"""密码适配层：Ed25519 签名/验证/密钥生成。

成熟实现 cryptography（第三方强制英文接口全部集中在适配层），
正式代码只调用中文外壳；不自行发明密码算法。
"""
from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def 生成密钥对() -> tuple[str, str]:
    """生成 Ed25519 密钥对；返回 (私钥PEM, 公钥PEM)。"""
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
    return 私钥PEM, 公钥PEM


def 签名(私钥PEM: str, 数据: bytes) -> str:
    """Ed25519 签名；返回十六进制签名。"""
    私钥 = serialization.load_pem_private_key(私钥PEM.encode("ascii"), password=None)
    assert isinstance(私钥, Ed25519PrivateKey)
    return 私钥.sign(数据).hex()


def 验证签名(公钥PEM: str, 数据: bytes, 签名hex: str) -> bool:
    """验证 Ed25519 签名；签名不合法返回 False（不抛异常）。"""
    try:
        公钥 = serialization.load_pem_public_key(公钥PEM.encode("ascii"))
        assert isinstance(公钥, Ed25519PublicKey)
        公钥.verify(bytes.fromhex(签名hex), 数据)
        return True
    except Exception:
        return False


def 公钥指纹(公钥PEM: str) -> str:
    """公钥指纹（sha256 前 16 位，信任目录标识）。"""
    return hashlib.sha256(公钥PEM.encode("utf-8")).hexdigest()[:16]


def 内容摘要(数据: bytes) -> str:
    """内容寻址摘要（sha256 前 32 位）。"""
    return hashlib.sha256(数据).hexdigest()[:32]
