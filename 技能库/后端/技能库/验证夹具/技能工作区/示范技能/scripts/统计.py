"""示范技能入口：读 stdin 的 JSON 载荷，统计字符数与词数，向 stdout 打印 JSON。"""

import json
import sys


def 主() -> None:
    载荷 = json.loads(sys.stdin.read() or "{}")
    参数 = 载荷.get("参数") or {}
    文本 = str(参数.get("文本") or "")
    print(json.dumps({"字符数": len(文本), "词数": len(文本.split())}, ensure_ascii=False))


主()
