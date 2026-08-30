#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys

端口 = int(sys.argv[1])
class 处理器(BaseHTTPRequestHandler):
    def do_POST(self):
        长度 = int(self.headers.get("Content-Length", "0")); json.loads(self.rfile.read(长度) or b"{}")
        if self.path.endswith("/chat/completions"):
            值 = {"choices": [{"message": {"content": "场景通过"}}], "usage": {"total_tokens": 3}}
        elif self.path.endswith("/embeddings"):
            值 = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        else:
            值 = {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]}
        数据 = json.dumps(值).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(数据)))
        self.end_headers(); self.wfile.write(数据)
    def log_message(self, format: str, *args) -> None:
        pass
HTTPServer(("127.0.0.1", 端口), 处理器).serve_forever()
