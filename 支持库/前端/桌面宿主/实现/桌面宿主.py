"""标准库桌面宿主原子能力；业务 demo 不需要接触 tkinter。"""
from __future__ import annotations
from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

def 启动桌面窗口(*, 标题: str = "底座桌面窗口", 初始文本: str = "", 调用函数: Callable[[str], Any] | None = None,
             受管验证: bool = False, 状态目录: str = "") -> int:
    """打开文本输入窗口；点击按钮时将文本交给业务回调并显示返回值。"""
    if 受管验证:
        try:
            状态根 = Path(状态目录).resolve()
            状态根.mkdir(parents=True, exist_ok=True)
            (状态根 / "桌面宿主状态.json").write_text(json.dumps({
                "标题": str(标题), "初始文本": str(初始文本), "状态": "已回收",
                "模式": "无窗口受管生命周期",
            }, ensure_ascii=False), encoding="utf-8")
            return 0
        except (OSError, ValueError) as 错误:
            return 结果.失败("宿主不可用", f"桌面宿主受管验证不可用：{错误}", 来源="桌面宿主")
    调用函数 = 调用函数 or (lambda 文本: {"成功": True, "值": 文本})
    try:
        import tkinter as tk
        根 = tk.Tk()
    except (ImportError, RuntimeError, OSError) as 错误:
        # 图形宿主不可用必须返回统一失败，而不是抛异常或伪造窗口已启动。
        # 这样无图形 Python、无 DISPLAY 的 CI 都能保留真实失败证据。
        return 结果.失败("宿主不可用", f"桌面宿主不可用：{错误}", 来源="桌面宿主")
    根.title(标题); 根.geometry("620x420"); 根.minsize(520, 340)
    tk.Label(根, text=标题, font=("Arial", 18, "bold")).pack(pady=(18, 8))
    输入框 = tk.Text(根, height=7, wrap="word"); 输入框.insert("1.0", 初始文本)
    输入框.pack(fill="both", expand=True, padx=24, pady=8)
    状态 = tk.StringVar(value="等待调用"); tk.Label(根, textvariable=状态, anchor="w", fg="#555").pack(fill="x", padx=24)
    结果框 = tk.Text(根, height=6, state="disabled", wrap="word"); 结果框.pack(fill="both", expand=True, padx=24, pady=8)
    def 调用() -> None:
        try:
            响应 = 调用函数(输入框.get("1.0", "end-1c"))
            文本 = str(响应.get("值") if isinstance(响应, dict) and 响应.get("成功") else 响应)
            状态.set("调用完成" if not isinstance(响应, dict) or 响应.get("成功") else "调用失败")
        except Exception as 错误:  # noqa: BLE001
            文本 = f"调用异常: {错误}"; 状态.set("调用失败")
        结果框.config(state="normal"); 结果框.delete("1.0", "end"); 结果框.insert("1.0", 文本); 结果框.config(state="disabled")
    tk.Button(根, text="调用底座", command=调用, width=16).pack(pady=(0, 16)); 根.protocol("WM_DELETE_WINDOW", 根.destroy)
    根.mainloop(); return 0
