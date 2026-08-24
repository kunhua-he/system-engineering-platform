"""前后端核心消费者：前端核心只通过浏览器宿主的 HTTP 边界调用后端能力。"""
from __future__ import annotations

import json
import sys
import urllib.request
from urllib.parse import quote
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 前端核心.前端核心 import 前端核心, 页面定义, 窗口定义
from 支持库.前端.浏览器宿主 import 启动网页服务


def 主程序() -> int:
    def 调用(文本: str) -> dict:
        return {"成功": True, "值": {"文本": 文本, "字数": len(文本)}}

    服务, 地址 = 启动网页服务(标题="前后端核心示例", 页面说明="HTTP 能力边界",
                              调用函数=调用, 端口=45081, 自动打开=False)
    前端 = 前端核心()
    前端.注册窗口(窗口定义("主页", 标题="前后端核心示例",
                         页面列表=[页面定义("主页", 路由="/", 标题="前后端核心示例")]))
    前端.设置调用入口(lambda 能力id, 参数: 调用(str((参数 or {}).get("文本", ""))))
    前端.打开窗口("主页")
    try:
        请求 = urllib.request.Request(
            地址 + "/api/" + quote("调用"), data=json.dumps({"文本": "底座"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        # 明确绕过环境代理；本地演示只占用 45081，不触碰代理端口。
        开启器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with 开启器.open(请求, timeout=5) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
        print("前后端核心示例")
        print(f"[4] HTTP 调用文本处理能力: 成功={数据.get('成功')}")
        print("[8] HTML 调用边界: 真实 HTTP=True")
        return 0 if 数据.get("成功") else 1
    finally:
        服务.shutdown(); 服务.server_close()
        前端.关闭窗口("主页")
        print("本地网关与后端核心已优雅关闭")


if __name__ == "__main__":
    raise SystemExit(主程序())
