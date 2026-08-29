"""标准库浏览器宿主原子能力；页面执行统一转发到唯一 HTTP 网关。"""
from __future__ import annotations

import html
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from 公共契约.运行时.端口策略 import 校验应用监听端口


def 启动网页服务(*, 标题: str = "底座网页服务", 页面说明: str = "",
               网关地址: str = "", 能力id: str = "", 端口: int = 45080,
               自动打开: bool = False) -> tuple[ThreadingHTTPServer, str]:
    """启动静态浏览器宿主；页面调用只能转发 POST /网关/调用。"""
    校验应用监听端口(端口)
    标题文本 = html.escape(str(标题), quote=True)
    说明文本 = html.escape(str(页面说明), quote=True)
    网关值 = json.dumps(str(网关地址).rstrip("/"), ensure_ascii=False)
    能力值 = json.dumps(str(能力id), ensure_ascii=False)
    页面 = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{标题文本}</title><style>body{{font-family:system-ui;max-width:760px;margin:48px auto;padding:0 20px;color:#223}}textarea{{width:100%;min-height:180px;padding:12px;font-size:16px}}button{{margin-top:12px;padding:10px 24px}}pre{{background:#f3f5f7;padding:16px;white-space:pre-wrap;min-height:80px}}</style><h1>{标题文本}</h1><p>{说明文本}</p><textarea id="文本"></textarea><br><button id="调用">调用网关</button><pre id="结果">等待调用</pre><script>const 网关地址={网关值},能力id={能力值};document.querySelector('#调用').onclick=async()=>{{const 结果=document.querySelector('#结果');if(!网关地址||!能力id){{结果.textContent='未配置统一网关地址或能力 id';return}}结果.textContent='调用中...';try{{const 响应=await fetch(网关地址+'/网关/调用',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{能力id,参数:{{文本:document.querySelector('#文本').value}}}})}});const 数据=await 响应.json();结果.textContent=数据.成功?JSON.stringify(数据.值??数据.结果,null,2):(数据.错误码||'调用失败')+': '+(数据.错误说明||'')}}catch(错误){{结果.textContent='网关不可访问'}}}};</script></html>'''.encode("utf-8")

    class 处理器(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10.0)

        def log_message(self, format: str, *参数: Any) -> None:
            return

        def do_GET(self) -> None:
            if unquote(urlsplit(self.path).path) != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(页面)))
            self.end_headers()
            self.wfile.write(页面)

        def do_POST(self) -> None:
            # 浏览器宿主不执行能力，不保留第二套业务 POST 协议。
            self.send_error(404)

    try:
        服务 = ThreadingHTTPServer(("127.0.0.1", 端口), 处理器)
    except OSError as 错误:
        raise OSError(f"网页宿主端口 {端口} 无法监听；不会自动改绑随机端口: {错误}") from 错误
    服务.daemon_threads = True
    threading.Thread(target=服务.serve_forever, daemon=True).start()
    地址 = f"http://127.0.0.1:{服务.server_port}"
    if 自动打开:
        webbrowser.open_new_tab(地址)
    return 服务, 地址
