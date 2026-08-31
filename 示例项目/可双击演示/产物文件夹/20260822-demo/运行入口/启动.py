"""独立 HTML 启动器；不依赖开发网关。"""
from __future__ import annotations
import os, sys
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import argparse, json, threading, urllib.error, urllib.request, webbrowser
from urllib.parse import quote, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
项目id = "示例项目.可双击演示"
包前缀 = ""
根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path: sys.path.insert(0, str(根))
源码根 = 根 / 包前缀 if 包前缀 else 根
from 公共契约.运行时.运行缓存 import 解析运行缓存根
运行缓存根 = 解析运行缓存根(源码根, 制品运行=True)
os.environ["系统底座_工程缓存根"] = str(运行缓存根)
os.environ.setdefault("系统底座_环境阶段输出", "1")
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
def 主函数(端口=45080, 自动打开=True):
    from 公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    后端 = 后端核心(系统根目录=源码根, 运行缓存根目录=运行缓存根); 启动 = 后端.启动()
    if not 启动.成功: raise RuntimeError(f"独立运行时装配失败: {启动.错误说明}")
    网关 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0); 成功, 说明 = 网关.启动()
    if not 成功: 后端.优雅关闭(); raise RuntimeError(说明)
    页面目录 = 根 / "前端" / "编译页面"
    路由数据 = json.loads((页面目录 / "路由表.json").read_text(encoding="utf-8"))
    if not isinstance(路由数据, dict) or not 路由数据: raise RuntimeError("页面路由表为空或不合法")
    页面表 = {}
    for 路由, 文件名 in 路由数据.items():
        if not isinstance(路由, str) or not 路由.startswith("/") or not isinstance(文件名, str): raise RuntimeError("页面路由表条目不合法")
        页面文件 = (页面目录 / 文件名).resolve()
        try: 页面文件.relative_to(页面目录.resolve())
        except ValueError as 错误: raise RuntimeError("页面路由逃逸") from 错误
        if not 页面文件.is_file(): raise RuntimeError(f"页面路由制品不存在: {文件名}")
        页面表[路由] = 页面文件.read_bytes()
    网关地址 = f"http://127.0.0.1:{网关.端口}"
    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式, *参数): return
        def _CORS头(self):
            # 允许本地验证页/HTML 黑盒验证器跨域直连（file:// 来源为 null，
            # 本地 HTTP 服务来源为 http://127.0.0.1:*）。黑盒验证必须走浏览器真实路径。
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        def do_OPTIONS(self):
            self.send_response(204); self._CORS头(); self.end_headers()
        def do_GET(self):
            路由 = unquote(self.path.split("?", 1)[0]); 页面 = 页面表.get(路由)
            if 页面 is None: self.send_error(404); return
            self.send_response(200); self._CORS头(); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(页面))); self.end_headers(); self.wfile.write(页面)
        def do_POST(self):
            # 浏览器/curl 会把中文路径编码（/网关/调用 → /%E7%BD%91...），
            # 必须 unquote 后再比较，否则收到编码路径直接 404。
            if unquote(self.path) != "/网关/调用": self.send_error(404); return
            try:
                长度 = int(self.headers.get("Content-Length", "-1"))
                if 长度 < 0 or 长度 > 1024 * 1024: raise ValueError("请求体超过上限")
                if "application/json" not in self.headers.get("Content-Type", "").lower(): raise ValueError("请求正文必须使用 JSON")
                请求数据 = json.loads(self.rfile.read(长度).decode("utf-8"))
                if not isinstance(请求数据, dict): raise ValueError("请求必须是对象")
                请求正文 = json.dumps(请求数据, ensure_ascii=False).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as 错误:
                正文 = json.dumps({"成功":False,"错误码":"参数不合法","错误说明":str(错误)}, ensure_ascii=False).encode()
                self.send_response(400); self._CORS头(); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
            # urllib 不能直接发原始中文路径（UnicodeEncodeError），必须 quote 编码；
            # quote 输出的 %XX 是合法 ASCII，urllib 不会二次转义（实测 200 成功）。
            请求头 = {"Content-Type":"application/json"}
            凭证 = os.environ.get("系统库网关凭证", "")
            if 凭证: 请求头["Authorization"] = f"Bearer {凭证}"
            请求 = urllib.request.Request(网关地址 + quote("/网关/调用"), data=请求正文, headers=请求头)
            try:
                with urllib.request.urlopen(请求, timeout=10) as 响应: 状态码, 正文 = 响应.status, 响应.read()
            except urllib.error.HTTPError as 错误:
                try: 状态码, 正文 = 错误.code, 错误.read()
                finally: 错误.close()
            except (urllib.error.URLError, TimeoutError, OSError):
                状态码 = 502; 正文 = json.dumps({"成功":False,"错误码":"网关断开","错误说明":"网关不可访问"}, ensure_ascii=False).encode()
            self.send_response(状态码); self._CORS头(); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文)
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
