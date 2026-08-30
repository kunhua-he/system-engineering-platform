#!/usr/bin/env python3
"""网络请求正向场景专用的本地可控HTTP夹具。"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
端口=int(sys.argv[1])
class 处理器(BaseHTTPRequestHandler):
    def log_message(self, *args): return
    def do_GET(self):
        正文=b"group8-local-payload" if self.path=="/text" else b"not-found"
        self.send_response(200 if self.path=="/text" else 404)
        self.send_header("Content-Type","text/plain; charset=utf-8")
        self.send_header("Content-Length",str(len(正文))); self.end_headers(); self.wfile.write(正文)
    def do_POST(self):
        长度=int(self.headers.get("Content-Length","0")); 数据=self.rfile.read(长度)
        正文=json.dumps({"收到":True,"字节数":len(数据)},ensure_ascii=False).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(正文))); self.end_headers(); self.wfile.write(正文)
服务=ThreadingHTTPServer(("127.0.0.1",45138),处理器)
print("g8-http-ready",flush=True)
try: 服务.serve_forever()
finally: 服务.server_close()
