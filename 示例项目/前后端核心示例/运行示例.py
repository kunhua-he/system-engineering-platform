"""前后端核心消费者：浏览器宿主只展示页面，能力执行统一交给 HTTP 网关。"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 前端核心.前端核心 import 前端核心, 页面定义, 窗口定义
from 支持库.前端.浏览器宿主 import 启动网页服务


def 主程序() -> int:
    服务, 地址 = 启动网页服务(
        标题="前后端核心示例", 页面说明="能力执行统一转发到 /网关/调用",
        网关地址="http://127.0.0.1:45082", 能力id="数据操作支持库.文本处理.分割文本",
        端口=45081, 自动打开=False,
    )
    前端 = 前端核心()
    前端.注册窗口(窗口定义("主页", 标题="前后端核心示例",
                         页面列表=[页面定义("主页", 路由="/", 标题="前后端核心示例")]))
    前端.打开窗口("主页")
    try:
        with urllib.request.urlopen(地址 + "/", timeout=5) as 响应:
            页面 = 响应.read().decode("utf-8")
        if "前后端核心示例" not in 页面 or "/网关/调用" not in 页面:
            print("[4] HTML 宿主边界校验失败")
            return 1
        print("前后端核心示例")
        print("[4] HTML 页面宿主: 成功=True")
        print("[8] HTML 调用边界: 统一网关=True")
        return 0
    finally:
        服务.shutdown()
        服务.server_close()
        前端.关闭窗口("主页")
        print("本地页面宿主已优雅关闭")


if __name__ == "__main__":
    raise SystemExit(主程序())
