"""子进程解析逻辑：在隔离子进程内执行 Pillow（PIL）图像操作。

本模块只在子进程中导入；这里才允许 import PIL，崩溃不影响平台主进程。
成功 {"值": ...}；失败 {"错误码": ..., "错误说明": ..., "值": ...}。
错误码统一：参数不合法/超大/格式未知/文件损坏/超时/提供者崩溃/提供者不可用。
"""

from __future__ import annotations

import base64
import io
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
            pass
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
    return {"值": {"格式": 图像.format, "宽度": 宽度, "高度": 高度, "模式": 图像.mode}}


def 像素统计(字节b64: str) -> dict[str, Any]:
    """统计像素：返回 {宽度, 高度, 像素数, 平均颜色{红,绿,蓝}}。"""
    图像, 错误 = _解码字节(字节b64, 统计最大像素)
    if 错误:
        return 错误
    ImageStat = _PIL模块[4]
    try:
        统计 = ImageStat.Stat(图像.convert("RGB"))
    except Exception as 统计错误:
        return {"错误码": "文件损坏", "错误说明": f"像素统计失败: {统计错误}"}
    平均 = [int(round(值)) for 值 in 统计.mean]
    宽度, 高度 = 图像.size
    return {"值": {
        "宽度": 宽度, "高度": 高度, "像素数": 宽度 * 高度,
        "平均颜色": {"红": 平均[0], "绿": 平均[1], "蓝": 平均[2]},
    }}


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
        return {"错误码": "文件损坏", "错误说明": f"占位图编码失败: {保存错误}"}
    return {"值": {"图像b64": base64.b64encode(输出流.getvalue()).decode("ascii"),
                   "格式": "PNG", "宽度": 宽度, "高度": 高度}}
