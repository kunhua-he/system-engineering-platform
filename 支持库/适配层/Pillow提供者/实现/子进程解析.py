"""子进程解析逻辑：在隔离子进程内执行 Pillow（PIL）图像操作。

本模块只在子进程中导入；这里才允许 import PIL，崩溃不影响平台主进程。
成功返回**裸值**字典（如 `{"格式": ..., "宽度": ...}`）——`公共契约/运行时/子进程协议.组装应答`
的「其余按成功转信封」一支直接把它当 `值`；**不再自带 `{"值": ...}` 包一层**（那会让 `组装应答`
把整个 `{"值": ...}` 当裸值再包一层，调用方读到 `结果.值["值"]` ⇒ 多包一层信封）。
失败返回 `{"错误码": ..., "错误说明": ..., "值": ...}`（该支按「含错误码的字典」保留 `值`）。
错误码统一：参数不合法/超大/格式未知/文件损坏/超时/提供者崩溃/提供者不可用。
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

禁用库环境变量名 = "Pillow提供者_禁用库"
输入字节上限 = 64 * 1024 * 1024
单图最大像素 = 40_000_000
统计最大像素 = 25_000_000
_PIL模块 = None  # (Image, ImageDraw, ImageFont, ImageOps, ImageStat)


def _加载PIL(禁用库表: set[str]):
    """加载 Pillow；禁用或缺失返回 None（提供者不可用）。"""
    if "PIL" not in 禁用库表:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
            return (Image, ImageDraw, ImageFont, ImageOps, ImageStat)
        except Exception:
            return None
    return None


def 初始化(禁用库表: set[str]) -> bool:
    global _PIL模块
    _PIL模块 = _加载PIL(禁用库表)
    return _PIL模块 is not None


def _不可用() -> dict[str, Any]:
    return {"错误码": "提供者不可用", "错误说明": "Pillow 不可用，无法执行图像操作", "可重试": True}


def _解析颜色(颜色文本: Any) -> tuple[int, int, int] | None:
    """解析 #RRGGBB；非法返回 None。"""
    文本 = str(颜色文本 or "").strip()
    if len(文本) != 7 or not 文本.startswith("#"):
        return None
    try:
        return tuple(int(文本[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError:
        return None


def _解码字节(字节b64: str, 最大像素: int) -> tuple[Any, dict[str, Any] | None]:
    """b64 解码 → Pillow 打开 → 像素上限 → 完整解码；失败返回错误字典。"""
    if _PIL模块 is None:
        return None, _不可用()
    Image = _PIL模块[0]
    try:
        字节 = base64.b64decode(字节b64)
    except Exception:
        return None, {"错误码": "参数不合法", "错误说明": "字节b64 不是合法 base64"}
    if not 字节:
        return None, {"错误码": "参数不合法", "错误说明": "字节为空"}
    if len(字节) > 输入字节上限:
        return None, {"错误码": "超大", "错误说明": f"图像字节超过上限 {输入字节上限} 字节"}
    try:
        图像 = Image.open(io.BytesIO(字节))
    except Exception as 错误:
        if "cannot identify" in str(错误):
            return None, {"错误码": "格式未知", "错误说明": f"无法识别图像格式: {错误}"}
        return None, {"错误码": "文件损坏", "错误说明": f"图像打开失败: {错误}"}
    宽度, 高度 = 图像.size
    if 宽度 * 高度 > 最大像素:
        return None, {"错误码": "超大", "错误说明": f"图像像素数 {宽度 * 高度} 超过上限 {最大像素}"}
    try:
        图像.load()
    except Exception as 错误:
        return None, {"错误码": "文件损坏", "错误说明": f"图像数据损坏: {错误}"}
    return 图像, None


def 解码图像(字节b64: str) -> dict[str, Any]:
    """Pillow 打开并完整解码：返回 {格式, 宽度, 高度, 模式}。"""
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    宽度, 高度 = 图像.size
    结果 = {"格式": 图像.format, "宽度": 宽度, "高度": 高度, "模式": 图像.mode}
    图像.close()
    return 结果


def 像素统计(字节b64: str) -> dict[str, Any]:
    """统计像素：返回 {宽度, 高度, 像素数, 平均颜色{红,绿,蓝}}。"""
    图像, 错误 = _解码字节(字节b64, 统计最大像素)
    if 错误:
        return 错误
    ImageStat = _PIL模块[4]
    try:
        统计 = ImageStat.Stat(图像.convert("RGB"))
    except Exception as 统计错误:
        图像.close()
        return {"错误码": "文件损坏", "错误说明": f"像素统计失败: {统计错误}"}
    平均 = [int(round(值)) for 值 in 统计.mean]
    宽度, 高度 = 图像.size
    结果 = {
        "宽度": 宽度, "高度": 高度, "像素数": 宽度 * 高度,
        "平均颜色": {"红": 平均[0], "绿": 平均[1], "蓝": 平均[2]},
    }
    图像.close()
    return 结果


def _校验宽高(宽度: Any, 高度: Any) -> dict[str, Any] | None:
    if not isinstance(宽度, int) or isinstance(宽度, bool) or 宽度 < 1:
        return {"错误码": "参数不合法", "错误说明": f"宽度必须为正整数，收到 {宽度!r}"}
    if not isinstance(高度, int) or isinstance(高度, bool) or 高度 < 1:
        return {"错误码": "参数不合法", "错误说明": f"高度必须为正整数，收到 {高度!r}"}
    if 宽度 * 高度 > 单图最大像素:
        return {"错误码": "超大", "错误说明": f"占位图像素数 {宽度 * 高度} 超过上限 {单图最大像素}"}
    return None


def 生成占位图(宽度: Any, 高度: Any, 占位类型: Any, 背景颜色: Any,
               前景颜色: Any, 文本: Any) -> dict[str, Any]:
    """生成占位图（纯色/渐变/文本）PNG 字节 base64：返回 {图像b64, 格式, 宽度, 高度}。"""
    if _PIL模块 is None:
        return _不可用()
    Image, ImageDraw, ImageFont, ImageOps, ImageStat = _PIL模块
    错误 = _校验宽高(宽度, 高度)
    if 错误:
        return 错误
    if 占位类型 not in ("纯色", "渐变", "文本"):
        return {"错误码": "参数不合法", "错误说明": f"占位类型必须是 纯色/渐变/文本，收到 {占位类型!r}"}
    背景 = _解析颜色(背景颜色)
    if 背景 is None:
        return {"错误码": "参数不合法", "错误说明": f"背景颜色必须是 #RRGGBB，收到 {背景颜色!r}"}
    前景 = _解析颜色(前景颜色)
    if 前景 is None:
        return {"错误码": "参数不合法", "错误说明": f"前景颜色必须是 #RRGGBB，收到 {前景颜色!r}"}
    if 占位类型 == "纯色":
        图像 = Image.new("RGB", (宽度, 高度), 背景)
    elif 占位类型 == "渐变":
        图像 = ImageOps.colorize(Image.linear_gradient("L"), 前景, 背景).resize((宽度, 高度))
    else:
        图像 = Image.new("RGB", (宽度, 高度), 背景)
        画布 = ImageDraw.Draw(图像)
        文字 = str(文本 or "").strip() or f"{宽度}x{高度}"
        字体 = ImageFont.load_default(size=max(12, 高度 // 8))
        边框 = 画布.textbbox((0, 0), 文字, font=字体)
        画布.text((宽度 // 2 - (边框[2] - 边框[0]) // 2 - 边框[0],
                   高度 // 2 - (边框[3] - 边框[1]) // 2 - 边框[1]), 文字, fill=前景, font=字体)
    输出流 = io.BytesIO()
    try:
        图像.save(输出流, format="PNG")
    except Exception as 保存错误:
        图像.close()
        return {"错误码": "文件损坏", "错误说明": f"占位图编码失败: {保存错误}"}
    结果 = {"图像b64": base64.b64encode(输出流.getvalue()).decode("ascii"),
            "格式": "PNG", "宽度": 宽度, "高度": 高度}
    图像.close()
    return 结果


def _取输出格式(图像: Any) -> str:
    """输出格式：JPEG/PNG/WebP 保留原格式，其余统一 PNG。"""
    原格式 = str(getattr(图像, "format", None) or "PNG").upper()
    return 原格式 if 原格式 in ("JPEG", "PNG", "WEBP") else "PNG"


def _编码图像(图像: Any, 目标格式: str, 质量: int = 90) -> dict[str, Any]:
    """把 Pillow 图像编码为目标格式并组装成功值；编码失败返回文件损坏。"""
    保存图像 = 图像
    if 目标格式 == "JPEG" and 图像.mode not in ("RGB", "L", "CMYK"):
        保存图像 = 图像.convert("RGB")
    elif 目标格式 == "PNG" and 图像.mode == "P":
        保存图像 = 图像.convert("RGBA")
    输出流 = io.BytesIO()
    try:
        if 目标格式 == "PNG":
            保存图像.save(输出流, format="PNG")
        else:
            保存图像.save(输出流, format=目标格式, quality=质量)
    except Exception as 保存错误:
        return {"错误码": "文件损坏", "错误说明": f"图像编码失败: {保存错误}"}
    宽度, 高度 = 图像.size
    return {"图像b64": base64.b64encode(输出流.getvalue()).decode("ascii"),
            "格式": 目标格式, "宽度": 宽度, "高度": 高度}


def 生成缩略图(字节b64: str, 最大边长: Any) -> dict[str, Any]:
    """按最大边长生成等比例缩略图（只缩小不放大）：返回 {图像b64, 格式, 宽度, 高度}。"""
    if _PIL模块 is None:
        return _不可用()
    if not isinstance(最大边长, int) or isinstance(最大边长, bool) or 最大边长 < 1:
        return {"错误码": "参数不合法", "错误说明": f"最大边长必须为正整数，收到 {最大边长!r}"}
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    Image = _PIL模块[0]
    目标格式 = _取输出格式(图像)  # 先取原格式，再转置（转置后 format 丢失）
    转置后 = _PIL模块[3].exif_transpose(图像)
    转置后.thumbnail((最大边长, 最大边长), Image.Resampling.LANCZOS)
    结果 = _编码图像(转置后, 目标格式)
    图像.close()
    转置后.close()
    return 结果


def 图像EXIF转置(字节b64: str) -> dict[str, Any]:
    """按 EXIF orientation 转置图像：返回 {图像b64, 格式, 宽度, 高度}；无方向时原样返回。"""
    if _PIL模块 is None:
        return _不可用()
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    目标格式 = _取输出格式(图像)  # 先取原格式，再转置（转置后 format 丢失）
    转置后 = _PIL模块[3].exif_transpose(图像)
    结果 = _编码图像(转置后, 目标格式)
    图像.close()
    转置后.close()
    return 结果


def 透明背景合成(字节b64: str, 背景颜色: Any) -> dict[str, Any]:
    """RGBA/LA/P 透明图像与背景色合成（输出 RGB PNG）：返回 {图像b64, 格式, 宽度, 高度}。"""
    if _PIL模块 is None:
        return _不可用()
    Image = _PIL模块[0]
    背景 = _解析颜色(背景颜色)
    if 背景 is None:
        return {"错误码": "参数不合法", "错误说明": f"背景颜色必须是 #RRGGBB，收到 {背景颜色!r}"}
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    if 图像.mode in ("RGBA", "LA", "P"):
        源 = 图像.convert("RGBA") if 图像.mode != "RGBA" else 图像
        合成底 = Image.new("RGB", 源.size, 背景)
        合成底.paste(源, mask=源.getchannel("A"))
        输出图像 = 合成底
    else:
        输出图像 = 图像.convert("RGB")
    结果 = _编码图像(输出图像, "PNG")
    图像.close()
    输出图像.close()
    return 结果


def _一维DCT(数据: list[float]) -> list[float]:
    """一维 DCT-II（统一缩放系数不影响哈希位序）。"""
    尺寸 = len(数据)
    return [
        (1.0 / 2.0 ** 0.5 if 序号 == 0 else 1.0)
        * sum(数据[x] * math.cos((2 * x + 1) * 序号 * math.pi / (2 * 尺寸))
              for x in range(尺寸))
        for 序号 in range(尺寸)
    ]


def _感知哈希位串(灰度: Any, Image: Any) -> str:
    """pHash：32x32 灰度 → DCT → 8x8 低频系数 → 中值 → 64 位位串。"""
    缩 = 灰度.resize((32, 32), Image.Resampling.LANCZOS)
    数据 = [[float(缩.getpixel((x, y))) for x in range(32)] for y in range(32)]
    行变换 = [_一维DCT(行) for 行 in 数据]
    列变换 = [_一维DCT([行变换[y][列] for y in range(32)]) for 列 in range(32)]
    系数表 = [列变换[列][行] for 列 in range(8) for 行 in range(8)]
    中值 = sorted(系数表)[32]
    return "".join("1" if 系数 > 中值 else "0" for 系数 in 系数表)


def 计算感知哈希(字节b64: str, 哈希类型: Any) -> dict[str, Any]:
    """计算感知哈希 aHash/dHash/pHash：返回 {哈希, 哈希类型}（64 位十六进制）。

    确定性：同输入同哈希；差异性：不同图像哈希不同。
    """
    if _PIL模块 is None:
        return _不可用()
    Image = _PIL模块[0]
    类型 = str(哈希类型 or "")
    if 类型 not in ("aHash", "dHash", "pHash"):
        return {"错误码": "参数不合法", "错误说明": f"哈希类型必须是 aHash/dHash/pHash，收到 {哈希类型!r}"}
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    灰度 = 图像.convert("L")
    if 类型 == "aHash":
        缩 = 灰度.resize((8, 8), Image.Resampling.LANCZOS)
        像素 = list(缩.getdata())
        平均 = sum(像素) / len(像素)
        位串 = "".join("1" if 值 > 平均 else "0" for 值 in 像素)
    elif 类型 == "dHash":
        缩 = 灰度.resize((9, 8), Image.Resampling.LANCZOS)
        像素 = list(缩.getdata())
        位串 = "".join("1" if 像素[y * 9 + x] > 像素[y * 9 + x + 1] else "0"
                       for y in range(8) for x in range(8))
    else:
        位串 = _感知哈希位串(灰度, Image)
    结果 = {"哈希": format(int(位串, 2), "016x"), "哈希类型": 类型}
    图像.close()
    灰度.close()
    return 结果


def 缩放图像(字节b64: str, 宽度: Any, 高度: Any) -> dict[str, Any]:
    """精确缩放图像（一侧缺省按纵横比推算）：返回 {图像b64, 格式, 宽度, 高度}。"""
    if _PIL模块 is None:
        return _不可用()
    Image = _PIL模块[0]
    宽度空 = 宽度 is None
    高度空 = 高度 is None
    if 宽度空 and 高度空:
        return {"错误码": "参数不合法", "错误说明": "宽度与高度至少提供一个（缺省一侧按纵横比推算）"}
    for 名称, 值 in (("宽度", 宽度), ("高度", 高度)):
        if 值 is not None and (not isinstance(值, int) or isinstance(值, bool) or 值 < 1):
            return {"错误码": "参数不合法", "错误说明": f"{名称}必须为正整数，收到 {值!r}"}
    if not 宽度空 and not 高度空 and 宽度 * 高度 > 单图最大像素:
        return {"错误码": "超大", "错误说明": f"目标像素数 {宽度 * 高度} 超过上限 {单图最大像素}"}
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    目标格式 = _取输出格式(图像)
    原宽, 原高 = 图像.size
    if 宽度空:
        新宽 = max(1, round(原宽 * 高度 / 原高))
        新高 = 高度
    elif 高度空:
        新宽 = 宽度
        新高 = max(1, round(原高 * 宽度 / 原宽))
    else:
        新宽, 新高 = 宽度, 高度
    缩放后 = 图像.resize((新宽, 新高), Image.Resampling.LANCZOS)
    结果 = _编码图像(缩放后, 目标格式)
    图像.close()
    缩放后.close()
    return 结果


def 重编码图像(字节b64: str, 格式: Any, 质量: Any) -> dict[str, Any]:
    """重编码图像为 JPEG/PNG/WebP：返回 {图像b64, 格式, 宽度, 高度}。"""
    if _PIL模块 is None:
        return _不可用()
    目标格式 = str(格式 or "").strip().upper()
    if 目标格式 == "JPG":
        目标格式 = "JPEG"
    if 目标格式 not in ("JPEG", "PNG", "WEBP"):
        return {"错误码": "参数不合法", "错误说明": f"格式必须是 JPEG/PNG/WebP，收到 {格式!r}"}
    if not isinstance(质量, int) or isinstance(质量, bool) or not (1 <= 质量 <= 100):
        return {"错误码": "参数不合法", "错误说明": f"质量必须是 1-100 的整数，收到 {质量!r}"}
    图像, 错误 = _解码字节(字节b64, 单图最大像素)
    if 错误:
        return 错误
    宽度, 高度 = 图像.size
    结果 = _编码图像(图像, 目标格式, 质量)
    if 结果.get("错误码"):
        图像.close()
        return 结果
    结果["宽度"], 结果["高度"] = 宽度, 高度
    图像.close()
    return 结果
