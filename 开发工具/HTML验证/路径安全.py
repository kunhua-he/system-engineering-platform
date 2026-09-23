"""场景和动态路径安全边界。"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from 支持库.后端.系统核心支持库.路径安全 import 校验相对路径文本


def _解码URL一次(文本: str) -> str:
    """URL 解码归一化（未完成事项 §四「路径边界有 5 份实现、口径互不一致」，2026-09-23）：**只解一次，绝不解两遍**。

    二次解码本身就是漏洞：`%252e%252e` 解一次得 `%2e%2e`、再解一次就是 `..`。故本函数
    只接受**原始入参**；任何调用点都不得把已解码结果再送进来。
    """
    return unquote(文本)


def _安全合并路径(根: Path, 相对: str, 名称: str) -> Path:
    if not isinstance(相对, str) or not 相对:
        raise ValueError(f"{名称}路径不合法: {相对!r}")
    # URL 解码归一化（未完成事项 §四「路径边界有 5 份实现、口径互不一致」）：所有判据之前先 unquote，且只解一次。
    # 此前 `..%2f逃逸` 不解码时只是一个普通目录名（`resolve()` 追不出越界）⇒ 编码穿越全放行。
    原文 = 相对
    相对 = _解码URL一次(相对)
    if not 相对 or Path(相对).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", 相对):
        raise ValueError(f"{名称}路径不合法: {相对!r}")
    路径 = (根 / 相对).resolve()
    try:
        路径.relative_to(根.resolve())
    except ValueError as 错误:
        raise ValueError(f"{名称}越出包目录或受管目录: {相对}") from 错误
    # 解码后的 `..` 段直接拒（#106）：本函数原有判据是「`resolve()` 后仍在根内即放行」，
    # 而 `a/..%2f/b` 解码后是 `a/../b` —— 它**恰好落在根内**，光靠 resolve 追不出来，
    # `..%2f` 就此整段绕过。编码穿越要真被拦住，必须在解码后的**字面段**上判
    # （段切分口径与 系统核心支持库.路径安全.校验路径 一致：只按 `/` 切）。
    # 放在 resolve 判据**之后**：越出根的那种仍走既有的「越出包目录或受管目录」分支，
    # 消息与旧行为逐字不变（`测试_HTML验证器` 的 `assertRaisesRegex(..., "越出包目录")` 钉着它）。
    # 收口（2026-09-23 S4·T3）：字面段判据不再自己写，一律转调唯一节点
    # `系统核心支持库.路径安全.校验相对路径文本`（`..` 段/段内 `.`/盘符/`~` 全由它判）。
    # 放在 resolve 判据**之后**：越出根的那种仍走上面的「越出包目录或受管目录」分支，
    # 消息与旧行为逐字不变（`测试_HTML验证器` 的 `assertRaisesRegex(..., "越出包目录")` 钉着它）。
    文本判定 = 校验相对路径文本(原文)
    判定值 = 文本判定.值 if isinstance(文本判定.值, dict) else {}
    if not 文本判定.成功 or not 判定值.get("通过"):
        raise ValueError(f"{名称}路径逃逸: {相对!r}")
    return 路径

def _校验动态声明(值: Any, 场景id: str, 已出现步骤: set[str]) -> None:
    if isinstance(值, list):
        for 项 in 值:
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    if not isinstance(值, dict):
        # 有意设计，不放宽：场景不得依赖作者本机的真实路径，也不得真的越界写。
        # 越界用例的写法口径见 `开发文档/决策记录/0016_验证场景越界用例口径.md`：
        # 用「写法上越界但字面不含 `..`、也非绝对路径」的方式触发（如 `~` 家目录写法）；
        # `..` 跳转型越界由定向 unittest + 真实网关调用取证，不进 HTML 黑盒矩阵。
        if isinstance(值, str):
            # URL 解码归一化（#106）：判据必须看**解码后**的文本 —— `..%2f逃逸` / `%2e%2e/x`
            # 字面不含 `..`、也不是绝对路径，不解码就整体绕过本守卫（只解一次）。
            解码 = _解码URL一次(值)
            if Path(解码).is_absolute() or ".." in Path(解码).parts or re.match(r"^[A-Za-z]:[\\/]", 解码):
                raise ValueError(f"场景 {场景id} 禁止静态绝对路径或路径逃逸")
        return
    if "$动态" not in 值:
        for 项 in 值.values():
            _校验动态声明(项, 场景id, 已出现步骤)
        return
    类型 = 值.get("$动态")
    允许字段 = {
        "制品根": {"$动态", "相对路径"},
        "受管临时目录": {"$动态", "相对路径"},
        "受管临时路径": {"$动态", "相对路径"},
        "夹具文件复制": {"$动态", "来源", "目标"},
        "步骤返回": {"$动态", "步骤id", "JSON路径"},
        "环境变量": {"$动态", "名称"},
    }
    if 类型 not in 允许字段 or set(值) != 允许字段[类型]:
        raise ValueError(f"场景 {场景id} 动态值声明不合法: {类型!r}")
    if 类型 == "步骤返回":
        if 值.get("步骤id") not in 已出现步骤 or not isinstance(值.get("JSON路径"), str):
            raise ValueError(f"场景 {场景id} 动态引用缺失或不是前序步骤: {值.get('步骤id')}")
    else:
        for 字段 in 允许字段[类型] - {"$动态"}:
            if not isinstance(值.get(字段), str) or not 值[字段]:
                raise ValueError(f"场景 {场景id} 动态路径字段不合法: {字段}")
