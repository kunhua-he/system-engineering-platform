"""实测：纯标准库扫本机推理端点的可行性与耗时（方案性能数字必须真实）。

两条路线对比：
  路线甲：socket.connect_ex 逐端口探测（平台无关，无需平台判断）
  路线乙：外部命令取监听端口列表（依赖平台，需走收口层）

判据：单次发现调用必须远低于华哥的「单步 2 分钟 = bug」红线，目标 < 3 秒。
"""
import socket
import time
import urllib.request
import json

# 候选端口：本机实测在跑的 + 常见推理服务默认端口
候选端口 = [
    1234, 5000, 5001, 6006, 8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007,
    8008, 8009, 8010, 8011, 8012, 8013, 8014, 8015, 8016, 8017, 8018, 8020,
    8080, 8081, 8085, 8090, 8888, 9000, 9001, 30000, 30001, 30002,
    11434, 11435, 45139, 40007, 8328,
]

print("=== 路线甲：socket.connect_ex 逐端口探测 ===")
print(f"候选端口数：{len(候选端口)}")
开始 = time.perf_counter()
存活 = []
for 端口 in 候选端口:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as 套接字:
        套接字.settimeout(0.25)
        if 套接字.connect_ex(("127.0.0.1", 端口)) == 0:
            存活.append(端口)
甲耗时 = time.perf_counter() - 开始
print(f"  存活端口：{存活}")
print(f"  耗时：{甲耗时:.2f} 秒（平均 {甲耗时 * 1000 / len(候选端口):.1f} ms/端口）")

print()
print("=== 路线甲·并发版（线程池）===")
from concurrent.futures import ThreadPoolExecutor


def 探端口(端口):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as 套接字:
        套接字.settimeout(0.25)
        return 端口 if 套接字.connect_ex(("127.0.0.1", 端口)) == 0 else None


开始 = time.perf_counter()
with ThreadPoolExecutor(max_workers=16) as 池:
    存活2 = [r for r in 池.map(探端口, 候选端口) if r]
甲并耗时 = time.perf_counter() - 开始
print(f"  存活端口：{存活2}")
print(f"  耗时：{甲并耗时:.2f} 秒")

print()
print("=== 探活：对存活端口请求 /v1/models（判定是否真推理端点）===")
开始 = time.perf_counter()
识别 = []
for 端口 in 存活2:
    网址 = f"http://127.0.0.1:{端口}/v1/models"
    try:
        with urllib.request.urlopen(网址, timeout=2) as 响应:
            if 200 <= 响应.status < 300:
                数据 = 响应.read().decode("utf-8", "replace")
                尝试 = json.loads(数据)
                模型名 = []
                if isinstance(尝试, dict):
                    for 项 in (尝试.get("data") or 尝试.get("models") or []):
                        if isinstance(项, dict):
                            模型名.append(项.get("id") or 项.get("name") or "")
                识别.append((端口, [m for m in 模型名 if m][:4]))
    except Exception as 错误:
        pass
探活耗时 = time.perf_counter() - 开始
for 端口, 模型 in 识别:
    print(f"  ✅ {端口}: {模型}")
print(f"  耗时：{探活耗时:.2f} 秒")

print()
print("=== 合计 ===")
print(f"  串行探测 + 探活：{甲耗时 + 探活耗时:.2f} 秒")
print(f"  并发探测 + 探活：{甲并耗时 + 探活耗时:.2f} 秒")
print(f"  华哥红线（单步 2 分钟）：{'✅ 远低于' if 甲并耗时 + 探活耗时 < 10 else '❌ 超标'}")

print()
print("=== 路线乙：外部命令取监听端口（对比用）===")
import subprocess

开始 = time.perf_counter()
try:
    输出 = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
        capture_output=True, text=True, timeout=5,
    ).stdout
    行数 = len(输出.splitlines())
    耗时 = time.perf_counter() - 开始
    print(f"  lsof 可用：{行数} 行，耗时 {耗时:.2f} 秒（依赖平台，macOS/Linux 行为不同）")
except Exception as 错误:
    print(f"  lsof 失败：{错误}")
