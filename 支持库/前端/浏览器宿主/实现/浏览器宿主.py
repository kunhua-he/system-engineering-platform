"""标准库浏览器宿主原子能力；业务 demo 不需要接触 HTTP 服务器实现。"""
from __future__ import annotations
import json, threading, webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from 公共契约.运行时.端口策略 import 校验应用监听端口

def 启动网页服务(*, 标题: str = "底座网页服务", 页面说明: str = "", 调用函数: Callable[[str], Any] | None = None, 端口: int = 45080, 自动打开: bool = False) -> tuple[ThreadingHTTPServer, str]:
    """启动网页宿主；返回服务句柄和页面地址，调用方负责 shutdown/server_close。"""
    校验应用监听端口(端口)
    调用函数 = 调用函数 or (lambda 文本: {"成功": True, "值": 文本})
    页面 = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{标题}</title><style>body{{font-family:system-ui;max-width:760px;margin:48px auto;padding:0 20px;color:#223}}textarea{{width:100%;min-height:180px;padding:12px;font-size:16px}}button{{margin-top:12px;padding:10px 24px}}pre{{background:#f3f5f7;padding:16px;white-space:pre-wrap;min-height:80px}}</style><h1>{标题}</h1><p>{页面说明}</p><textarea id="文本"></textarea><br><button id="调用">调用底座</button><pre id="结果">等待调用</pre><script>document.querySelector('#调用').onclick=async()=>{{const 结果=document.querySelector('#结果');结果.textContent='调用中...';const 响应=await fetch('/api/调用',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{文本:document.querySelector('#文本').value}})}});const 数据=await 响应.json();结果.textContent=数据.成功?JSON.stringify(数据.值,null,2):数据.错误码+': '+数据.错误说明}};</script></html>'''.encode("utf-8")
    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式: str, *参数: Any) -> None: return
        def do_GET(self) -> None:
            if unquote(urlsplit(self.path).path) != "/": self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(页面))); self.end_headers(); self.wfile.write(页面)
        def do_POST(self) -> None:
            if unquote(urlsplit(self.path).path) != "/api/调用": self.send_error(404); return
            try:
                参数 = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)).decode("utf-8")); 响应 = 调用函数(str(参数.get("文本", "")))
            except Exception as 错误:  # noqa: BLE001
                响应 = {"成功": False, "错误码": "参数不合法", "错误说明": str(错误)}
            正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文)
    try:
        服务 = ThreadingHTTPServer(("127.0.0.1", 端口), 处理器)
    except OSError as 错误:
        raise OSError(f"网页宿主端口 {端口} 无法监听；不会自动改绑随机端口: {错误}") from 错误
    服务.daemon_threads = True; threading.Thread(target=服务.serve_forever, daemon=True).start(); 地址 = f"http://127.0.0.1:{服务.server_port}"
    if 自动打开: webbrowser.open_new_tab(地址)
    return 服务, 地址
