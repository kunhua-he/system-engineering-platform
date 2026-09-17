"""文档转换支持库.PDF生成.生成PDF：把 reportlab 下沉到隔离子进程执行。

主进程（本文件）只做三件事：参数预校验、拉起一次性子进程、把子进程响应映射成
统一结果 —— **本进程绝不 import reportlab**（D-3 收口：对齐同仓 PIL/fitz/mlx_whisper
已验证的 子进程解析.py 形态，第三方库只在子进程内加载）。

渲染逻辑不在本包重复实现：reportlab 的唯一实现在 支持库.适配层.reportlab提供者，
子进程内经其**公开入口**调用（D-2 收口：同一份逻辑只有一个实现；本包原
实现/渲染表格.py 与适配层腿逐字节相同，已删除）。

错误码严格保持契约声明的三项（参数不合法 / 提供者不可用 / 生成失败）：子进程
超时与崩溃按「生成失败」返回、真实原因写进 错误说明，不新增未声明的错误码。
释放语义：子进程独占进程组启动，调用返回前一律回收（终止 → 宽限 → 强杀 → 复查），
不留残留进程；不落盘、不持跨调用状态。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.有界IO import 受限通信

能力名 = "文档转换支持库.PDF生成.生成PDF"
媒体类型PDF = "application/pdf"
包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 90.0
默认最大输出字节 = 64 * 1024 * 1024
# 只有契约声明的错误码可以外泄；子进程的其余错误码（超时/提供者崩溃/…）一律
# 归并到 生成失败，并把真实原因写进 错误说明（不新增未声明的错误码）。
可透传错误码 = ("参数不合法", "提供者不可用")


def 生成PDF(内容参数: dict) -> 结果:
    """按 内容参数（标题/段落列表/表格列表）生成 PDF，返回 结果[生成产物字典]。"""
    错误 = _预校验(内容参数)
    if 错误 is not None:
        return 错误
    return _执行任务({"操作": "生成", "内容参数": 内容参数}, 超时秒=默认超时秒)


def _预校验(内容参数: Any) -> 结果 | None:
    """主进程预校验：形态不对时直接返回，不起子进程（与渲染层同一口径）。"""
    if not isinstance(内容参数, dict):
        return 结果.失败("参数不合法", "内容参数必须是字典", 来源=能力名)
    标题 = 内容参数.get("标题") or ""
    段落列表 = 内容参数.get("段落列表") or []
    表格列表 = 内容参数.get("表格列表") or []
    if not isinstance(标题, str):
        return 结果.失败("参数不合法", "标题必须是文本", 来源=能力名)
    if not isinstance(段落列表, list):
        return 结果.失败("参数不合法", "段落列表必须是列表", 来源=能力名)
    if not isinstance(表格列表, list):
        return 结果.失败("参数不合法", "表格列表必须是列表", 来源=能力名)
    if not 标题 and not 段落列表 and not 表格列表:
        return 结果.失败("参数不合法", "内容不能为空：标题/段落列表/表格列表至少提供一项", 来源=能力名)
    return None


def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    系统根 = next(祖先 for 祖先 in 包目录.parents if (祖先 / "支持库").is_dir())
    return subprocess.Popen(
        [sys.executable, str(子进程入口路径)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(系统根),
        **平台适配.子进程组启动标志(),
        env=dict(os.environ),
    )


def _终止子进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """回收子进程（唯一实现在 公共契约.运行时.进程终止，本处只做同签名的薄委托）。"""
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


def _执行任务(请求: dict[str, Any], 超时秒: float = 默认超时秒) -> 结果:
    """执行一次子进程任务，返回统一结果（错误码归并到契约声明的三项）。"""
    进程 = None
    try:
        进程 = _启动子进程()
    except (OSError, ValueError) as 错误:
        return 结果.失败("提供者不可用", f"无法启动 PDF 生成子进程: {错误}", 来源=能力名, 可重试=True)
    请求行 = (json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        标准输出, _标准错误, 已超时, 输出超限 = 受限通信(
            进程, 输入=请求行, 超时秒=超时秒,
            输出上限字节=默认最大输出字节,
            终止回调=lambda: _终止子进程组(进程),
        )
    finally:
        try:
            if 进程.poll() is None:
                _终止子进程组(进程)
        except (OSError, ValueError):
            pass
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            try:
                if 流 is not None:
                    流.close()
            except (OSError, ValueError):
                pass
    if 已超时:
        return 结果.失败("生成失败", f"PDF 生成子进程执行超过 {超时秒} 秒（进程组已回收）", 来源=能力名)
    if 输出超限:
        return 结果.失败("生成失败", f"PDF 生成子进程输出超过上限 {默认最大输出字节} 字节", 来源=能力名)
    退出码 = 进程.returncode or 0
    if 退出码 != 0:
        return 结果.失败("生成失败", f"PDF 生成子进程异常退出（退出码 {退出码}）", 来源=能力名)
    try:
        响应 = json.loads(标准输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return 结果.失败("生成失败", "PDF 生成子进程返回了无效响应", 来源=能力名)
    if 响应.get("成功"):
        return 结果.成功结果(响应.get("值"))
    错误码 = str(响应.get("错误码") or "生成失败")
    错误说明 = str(响应.get("错误说明") or "PDF 生成子进程执行失败")
    if 错误码 in 可透传错误码:
        return 结果.失败(错误码, 错误说明, 来源=能力名, 可重试=错误码 == "提供者不可用")
    return 结果.失败("生成失败", f"子进程返回 {错误码}：{错误说明}", 来源=能力名)
