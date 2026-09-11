"""反面夹具入口：刻意导入项目层模块，用于验证导入审计在沙箱之前拦截。"""

import json
import sys

from 功能模块.订单 import 查询订单


def 主() -> None:
    载荷 = json.loads(sys.stdin.read() or "{}")
    参数 = 载荷.get("参数") or {}
    print(json.dumps({"订单": 查询订单(参数.get("订单号"))}, ensure_ascii=False))


主()
