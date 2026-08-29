"""示例项目.可双击演示 独立 HTML 启动器；不依赖开发网关。"""
from __future__ import annotations
import os, sys
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import argparse, json, threading, urllib.error, urllib.request, webbrowser
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path: sys.path.insert(0, str(根))
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
def 主函数(端口=45080, 自动打开=True):
    from 公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    后端 = 后端核心(系统根目录=根); 启动 = 后端.启动()
    if not 启动.成功: raise RuntimeError(f"独立运行时装配失败: {启动.错误说明}")
    网关 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0); 成功, 说明 = 网关.启动()
    if not 成功: 后端.优雅关闭(); raise RuntimeError(说明)
    页面 = (根 / "前端" / "编译页面" / "index.html").read_bytes(); 网关地址 = f"http://127.0.0.1:{网关.端口}"
    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式, *参数): return
        def do_GET(self):
            if self.path != "/": self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(页面))); self.end_headers(); self.wfile.write(页面)
        def do_POST(self):
            if self.path != "/网关/调用": self.send_error(404); return
            try:
                长度 = int(self.headers.get("Content-Length", "-1"))
                if 长度 < 0 or 长度 > 1024 * 1024: raise ValueError("请求体超过上限")
                if "application/json" not in self.headers.get("Content-Type", "").lower(): raise ValueError("请求正文必须使用 JSON")
                请求数据 = json.loads(self.rfile.read(长度).decode("utf-8"))
                if not isinstance(请求数据, dict): raise ValueError("请求必须是对象")
                请求正文 = json.dumps(请求数据, ensure_ascii=False).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as 错误:
                正文 = json.dumps({"成功":False,"错误码":"参数不合法","错误说明":str(错误)}, ensure_ascii=False).encode()
                self.send_response(400); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
            请求 = urllib.request.Request(网关地址 + quote("/网关/调用"), data=请求正文, headers={"Content-Type":"application/json"})
            try:
                with urllib.request.urlopen(请求, timeout=10) as 响应: 状态码, 正文 = 响应.status, 响应.read()
            except urllib.error.HTTPError as 错误:
                状态码, 正文 = 错误.code, 错误.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                状态码 = 502; 正文 = json.dumps({"成功":False,"错误码":"网关断开","错误说明":"网关不可访问"}, ensure_ascii=False).encode()
            self.send_response(状态码); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文)
    服务 = ThreadingHTTPServer(("127.0.0.1", 端口), 处理器); 地址 = f"http://127.0.0.1:{服务.server_port}"
    try:
        threading.Thread(target=服务.serve_forever, daemon=True).start(); print(f"独立项目已启动: {地址}")
        if 自动打开: webbrowser.open(地址)
        threading.Event().wait()
    except KeyboardInterrupt: return 0
    finally:
        服务.shutdown(); 服务.server_close(); 网关.优雅停止(); 后端.优雅关闭()
    return 0
if __name__ == "__main__":
    解析器=argparse.ArgumentParser(); 解析器.add_argument("--端口", type=int, default=45080); 解析器.add_argument("--不自动打开", action="store_true"); 参数=解析器.parse_args(); raise SystemExit(主函数(参数.端口, not 参数.不自动打开))
