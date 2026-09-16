#!/usr/bin/env python3
"""就绪轮询管道排空夹具：先向 stdout 写超管道缓冲的量，再监听就绪端口。

用途：启动进程 的就绪轮询若在等待期间不排空子进程 stdout，子进程的 write
会阻塞在管道缓冲（macOS 常见 64KB）上，端口永远不监听 → 轮询空转到超时。
本夹具把这一顺序刻意固定下来：**先写满管道，再监听端口**。

用法：大输出就绪进程.py <端口> [输出字节数] [存活秒数]
- 端口 > 0：写完输出 → 监听该端口 → 存活 存活秒数 秒；
- 端口 = 0：写完输出直接退出（用于验证「就绪前退出」路径仍能读到已排空的 stderr）。
"""
from __future__ import annotations

import socket
import sys
import time

端口 = int(sys.argv[1])
输出字节数 = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
存活秒数 = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0

sys.stderr.write("夹具错误标记\n")
sys.stderr.flush()
sys.stdout.write("x" * 输出字节数)
sys.stdout.flush()

if 端口 <= 0:
    sys.exit(0)

with socket.socket() as 监听:
    监听.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    监听.bind(("127.0.0.1", 端口))
    监听.listen(8)
    time.sleep(存活秒数)
