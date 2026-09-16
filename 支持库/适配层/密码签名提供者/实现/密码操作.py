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
        无加密密码 = None
        私钥 = serialization.load_pem_private_key(私钥PEM.encode("ascii"), 无加密密码)
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


# ---------------------------------------------------------------------------
# AES 对称加解密（同一提供者内扩展，不新建第二个密码学包）
#
# 与 Ed25519 非对称能力同库同进程边界：全部在本文件内 import cryptography，
# 主进程零加载。密文外壳自带随机数/初始向量前缀，解密端可自解析；调用方也能
# 显式传 初始向量b64 复用外部来源（如数据库页级加密的固定向量）。
# ---------------------------------------------------------------------------

支持模式表 = ("AES-GCM", "AES-CBC")
默认模式 = "AES-GCM"
GCM随机数字节 = 12
CBC初始向量字节 = 16
合法密钥字节表 = (16, 24, 32)


def _规范化模式(模式: str) -> str:
    """模式归一：去空格转大写；空值取默认 AES-GCM；不支持的模式直接拒绝。"""
    if 模式 is None or not str(模式).strip():
        return 默认模式
    规范化 = str(模式).strip().upper()
    if 规范化 not in 支持模式表:
        raise 提供者操作异常("参数不合法", f"模式只支持 {list(支持模式表)}，收到 {模式!r}")
    return 规范化


def _解码密钥(密钥b64: str) -> bytes:
    if not isinstance(密钥b64, str) or not 密钥b64:
        raise 提供者操作异常("参数不合法", "密钥b64 必须是非空文本")
    try:
        密钥 = base64.b64decode(密钥b64, validate=True)
    except Exception as 错误:
        raise 提供者操作异常("参数不合法", f"密钥b64 不是合法 base64: {错误}") from 错误
    if len(密钥) not in 合法密钥字节表:
        raise 提供者操作异常(
            "参数不合法",
            f"密钥长度必须是 {合法密钥字节表} 字节（AES-128/192/256），收到 {len(密钥)} 字节",
        )
    return 密钥


def _解码可选字节(值b64: str | None, 字段名: str) -> bytes | None:
    """选填 base64 字段：空文本或 None → None（由调用端按模式取默认值）。"""
    if 值b64 is None or not str(值b64).strip():
        return None
    if not isinstance(值b64, str):
        raise 提供者操作异常("参数不合法", f"{字段名} 必须是 base64 文本")
    try:
        return base64.b64decode(值b64, validate=True)
    except Exception as 错误:
        raise 提供者操作异常("参数不合法", f"{字段名} 不是合法 base64: {错误}") from 错误


def _导入AES组件():
    """按需导入 AES 组件（cryptography 只在子进程内加载）。"""
    _检查可用()
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return Cipher, algorithms, modes, padding, AESGCM


def 对称加密(明文b64: str, 密钥b64: str, 模式: str = 默认模式,
           初始向量b64: str | None = None, 附加数据b64: str | None = None) -> str:
    """AES 对称加密，返回 base64 密文包。

    AES-GCM（默认，带认证标签）：随机数(12 字节) + 密文 + 标签(16 字节)；
    AES-CBC（PKCS7 填充）：初始向量(16 字节) + 密文。
    """
    规范模式 = _规范化模式(模式)
    密钥 = _解码密钥(密钥b64)
    明文 = _解码数据(明文b64)
    附加数据 = _解码可选字节(附加数据b64, "附加数据b64")
    初始向量 = _解码可选字节(初始向量b64, "初始向量b64")
    Cipher, algorithms, modes, padding, AESGCM = _导入AES组件()
    try:
        if 规范模式 == "AES-GCM":
            随机数 = 初始向量 if 初始向量 is not None else os.urandom(GCM随机数字节)
            if len(随机数) != GCM随机数字节:
                raise 提供者操作异常(
                    "参数不合法",
                    f"AES-GCM 初始向量必须是 {GCM随机数字节} 字节，收到 {len(随机数)} 字节",
                )
            密文 = AESGCM(密钥).encrypt(随机数, 明文, 附加数据)
            return base64.b64encode(随机数 + 密文).decode("ascii")
        if 附加数据 is not None:
            raise 提供者操作异常("参数不合法", "AES-CBC 模式不支持 附加数据b64")
        向量 = 初始向量 if 初始向量 is not None else os.urandom(CBC初始向量字节)
        if len(向量) != CBC初始向量字节:
            raise 提供者操作异常(
                "参数不合法",
                f"AES-CBC 初始向量必须是 {CBC初始向量字节} 字节，收到 {len(向量)} 字节",
            )
        填充器 = padding.PKCS7(algorithms.AES.block_size).padder()
        填充后 = 填充器.update(明文) + 填充器.finalize()
        加密器 = Cipher(algorithms.AES(密钥), modes.CBC(向量)).encryptor()
        密文 = 加密器.update(填充后) + 加密器.finalize()
        return base64.b64encode(向量 + 密文).decode("ascii")
    except 提供者操作异常:
        raise
    except Exception as 错误:
        raise 提供者操作异常("加密失败", f"AES 加密失败: {错误}") from 错误


def 对称解密(密文b64: str, 密钥b64: str, 模式: str = 默认模式,
           初始向量b64: str | None = None, 附加数据b64: str | None = None) -> str:
    """AES 对称解密，返回明文 base64。

    未传 初始向量b64 时按密文包前缀自解析（GCM 取前 12 字节、CBC 取前 16 字节）；
    密钥不匹配或被篡改返回 解密失败（可诊断，不静默返回空值）。
    """
    规范模式 = _规范化模式(模式)
    密钥 = _解码密钥(密钥b64)
    密文包 = _解码数据(密文b64)
    附加数据 = _解码可选字节(附加数据b64, "附加数据b64")
    初始向量 = _解码可选字节(初始向量b64, "初始向量b64")
    Cipher, algorithms, modes, padding, AESGCM = _导入AES组件()
    try:
        if 规范模式 == "AES-GCM":
            if 初始向量 is None:
                if len(密文包) <= GCM随机数字节:
                    raise 提供者操作异常(
                        "参数不合法",
                        f"AES-GCM 密文至少 {GCM随机数字节 + 1} 字节（含随机数前缀与认证标签）",
                    )
                向量, 密文 = 密文包[:GCM随机数字节], 密文包[GCM随机数字节:]
            else:
                if len(初始向量) != GCM随机数字节:
                    raise 提供者操作异常(
                        "参数不合法",
                        f"AES-GCM 初始向量必须是 {GCM随机数字节} 字节，收到 {len(初始向量)} 字节",
                    )
                向量, 密文 = 初始向量, 密文包
            明文 = AESGCM(密钥).decrypt(向量, 密文, 附加数据)
            return base64.b64encode(明文).decode("ascii")
        if 附加数据 is not None:
            raise 提供者操作异常("参数不合法", "AES-CBC 模式不支持 附加数据b64")
        if 初始向量 is None:
            if len(密文包) <= CBC初始向量字节:
                raise 提供者操作异常(
                    "参数不合法", f"AES-CBC 密文至少 {CBC初始向量字节 + 1} 字节（含初始向量前缀）"
                )
            向量, 密文 = 密文包[:CBC初始向量字节], 密文包[CBC初始向量字节:]
        else:
            if len(初始向量) != CBC初始向量字节:
                raise 提供者操作异常(
                    "参数不合法",
                    f"AES-CBC 初始向量必须是 {CBC初始向量字节} 字节，收到 {len(初始向量)} 字节",
                )
            向量, 密文 = 初始向量, 密文包
        if not 密文 or len(密文) % CBC初始向量字节 != 0:
            raise 提供者操作异常(
                "参数不合法", f"AES-CBC 密文长度必须是 {CBC初始向量字节} 字节的整数倍"
            )
        解密器 = Cipher(algorithms.AES(密钥), modes.CBC(向量)).decryptor()
        填充后 = 解密器.update(密文) + 解密器.finalize()
        解填充器 = padding.PKCS7(algorithms.AES.block_size).unpadder()
        明文 = 解填充器.update(填充后) + 解填充器.finalize()
        return base64.b64encode(明文).decode("ascii")
    except 提供者操作异常:
        raise
    except Exception as 错误:
        raise 提供者操作异常(
            "解密失败", f"AES 解密失败（密钥不匹配或密文被篡改）: {错误}"
        ) from 错误
