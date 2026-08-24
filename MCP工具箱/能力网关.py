"""系统工程平台 HTTP 能力网关（对外核心底座）。

面向开发（Agent 开发业务项目、开发者写业务代码）：搜索能力、查看契约、
执行能力。任何语言、任何工具可直接用 HTTP 调用，不依赖 MCP 协议。

本地场景：直接把支持库/模块库复制到本地，用本地绝对路径 import，不绕本网关。

接口（全中文，客户端 UTF-8 百分号编码传输）：
- GET  /能力/搜索?关键词=读取文件&限制=20   搜索能力（使用声明）
- GET  /能力/契约/{能力id}                   查看能力契约（参数/返回/错误码）
- POST /能力/执行                            执行能力，body {"能力id","参数"}

统一返回格式：{"成功", "值", "错误码", "错误说明"}（执行另附证据链）。

只允许 Python 标准库（http.server）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.开发入口 import 搜索能力, 查看契约, 真实调用能力
from 公共契约.运行时.端口策略 import 校验应用监听端口


class 能力网关请求处理器(BaseHTTPRequestHandler):
    """HTTP 能力网关：搜索/契约/执行 三个路由。"""

    # ---- 基础 ----
    def log_message(self, 格式: str, *参数) -> None:
        sys.stderr.write(f"[能力网关] {self.address_string()} {格式 % 参数}\n")

    def _发送JSON(self, 状态码: int, 数据: dict) -> None:
        字节 = json.dumps(数据, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(状态码)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(字节)))
        self.end_headers()
        self.wfile.write(字节)

    # ---- 路由分发 ----
    def _解析URL(self) -> tuple[str, dict[str, list[str]]]:
        """把请求 URL 统一解码成可读形式：百分号编码 → 中文路径与查询参数。

        客户端以标准 UTF-8 百分号编码传输；这里统一 unquote，之后路由匹配
        直接用中文（如 /能力/搜索、关键词=读取文件）。
        """
        解析 = urllib.parse.urlparse(self.path)
        路径 = urllib.parse.unquote(解析.path, encoding="utf-8")
        查询 = urllib.parse.parse_qs(解析.query, encoding="utf-8")
        return 路径, 查询

    def do_GET(self) -> None:
        路径, 查询 = self._解析URL()
        try:
            if 路径 == "/能力/搜索":
                self._处理搜索(查询)
            elif 路径.startswith("/能力/契约/"):
                能力id = 路径[len("/能力/契约/"):]
                self._处理契约(能力id)
            else:
                self._发送JSON(404, {"成功": False, "错误码": "路由不存在", "错误说明": f"未定义路由: {路径}"})
        except Exception as 异常:
            self._发送JSON(500, {"成功": False, "错误码": "网关内部错误", "错误说明": f"{type(异常).__name__}: {异常}"})

    def do_POST(self) -> None:
        路径, _ = self._解析URL()
        try:
            if 路径 == "/能力/执行":
                self._处理执行()
            else:
                self._发送JSON(404, {"成功": False, "错误码": "路由不存在", "错误说明": f"未定义路由: {路径}"})
        except Exception as 异常:
            self._发送JSON(500, {"成功": False, "错误码": "网关内部错误", "错误说明": f"{type(异常).__name__}: {异常}"})

    # ---- 具体处理 ----
    def _处理搜索(self, 查询: dict) -> None:
        关键词 = (查询.get("关键词") or [""])[0]
        限制 = int((查询.get("限制") or ["20"])[0])
        结果表 = 搜索能力(关键词=关键词, 限制=限制)
        self._发送JSON(200, {"成功": True, "数量": len(结果表), "能力表": 结果表})

    def _处理契约(self, 能力id: str) -> None:
        if not 能力id:
            self._发送JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": "能力id不能为空"})
            return
        契约 = 查看契约(能力id)
        if not 契约.get("找到"):
            self._发送JSON(404, {"成功": False, "错误码": "能力不存在", "错误说明": f"未找到能力: {能力id}"})
            return
        self._发送JSON(200, {"成功": True, "契约": 契约})

    def _处理执行(self) -> None:
        长度 = int(self.headers.get("Content-Length", 0))
        if 长度 <= 0 or 长度 > 10_000_000:
            self._发送JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": "请求体为空或过大"})
            return
        try:
            body = json.loads(self.rfile.read(长度).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as 异常:
            self._发送JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": f"请求体不是合法JSON: {异常}"})
            return
        能力id = body.get("能力id")
        参数 = body.get("参数") or {}
        if not 能力id:
            self._发送JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": "缺少 能力id"})
            return
        if not isinstance(参数, dict):
            self._发送JSON(400, {"成功": False, "错误码": "参数不合法", "错误说明": "参数必须是对象"})
            return
        结果 = 真实调用能力(能力id, 参数)
        self._发送JSON(200, 结果)


def 启动网关(*, 端口: int, 地址: str = "127.0.0.1") -> None:
    """启动 HTTP 能力网关。"""
    校验应用监听端口(端口)
    httpd = ThreadingHTTPServer((地址, 端口), 能力网关请求处理器)
    print(f"能力网关已启动: http://{地址}:{端口}")
    print("接口: GET /能力/搜索  GET /能力/契约/{能力id}  POST /能力/执行")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n能力网关已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="系统工程平台 HTTP 能力网关")
    解析器.add_argument("--端口", type=int, default=8866, help="网关端口（默认 8866）")
    解析器.add_argument("--地址", default="127.0.0.1", help="监听地址（默认本机）")
    参数 = 解析器.parse_args()
    启动网关(端口=参数.端口, 地址=参数.地址)
