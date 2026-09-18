"""实测：纯 Python 标准库能否做 mDNS/DNS-SD 发现（底座只允许标准库）。

若可行 → 自动发现能力可以零第三方依赖落底座；
若不可行 → 必须走适配层提供者封装第三方，是成本判断的关键依据。
"""
import socket
import struct
import time

组播地址 = "224.0.0.251"
端口 = 5353


def 构造查询(名称: str, 记录类型: int = 12) -> bytes:
    """构造 DNS 查询报文（PTR=12 用于服务枚举）。"""
    事务id = 0x0000
    标志 = 0x0000  # 标准查询
    报文 = struct.pack(">HHHHHH", 事务id, 标志, 1, 0, 0, 0)
    for 标签 in 名称.split("."):
        if 标签:
            报文 += bytes([len(标签)]) + 标签.encode("ascii")
    报文 += b"\x00" + struct.pack(">HH", 记录类型, 1)  # IN 类
    return 报文


def 解析应答(数据: bytes) -> list:
    """粗解析应答中的名称标签（只取可见字符串，足够判断是否有人应答）。"""
    找到 = []
    游标 = 0
    while 游标 < len(数据):
        长度 = 数据[游标]
        if 0 < 长度 < 64 and 游标 + 1 + 长度 <= len(数据):
            段 = 数据[游标 + 1 : 游标 + 1 + 长度]
            try:
                文本 = 段.decode("ascii")
                if 文本.isprintable() and len(文本) > 1:
                    找到.append(文本)
                游标 += 1 + 长度
                continue
            except UnicodeDecodeError:
                pass
        游标 += 1
    return 找到


def 探测(服务名: str, 超时: float = 4.0) -> dict:
    结果 = {"服务": 服务名, "收到应答": False, "应答字节数": 0, "可读标签": []}
    套接字 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    套接字.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    套接字.settimeout(超时)
    try:
        套接字.sendto(构造查询(服务名), (组播地址, 端口))
        截止 = time.time() + 超时
        while time.time() < 截止:
            try:
                数据, 来源 = 套接字.recvfrom(4096)
            except socket.timeout:
                break
            if len(数据) > 12:
                结果["收到应答"] = True
                结果["应答字节数"] += len(数据)
                标签 = 解析应答(数据[12:])
                for 项 in 标签:
                    if 项 not in 结果["可读标签"]:
                        结果["可读标签"].append(项)
                if len(结果["可读标签"]) > 40:
                    break
    except Exception as 异常:
        结果["异常"] = f"{type(异常).__name__}: {异常}"
    finally:
        套接字.close()
    return 结果


print("=== 纯标准库 mDNS 探测实测 ===")
print(f"Python 标准库 socket，组播 {组播地址}:{端口}\n")

for 名称 in [
    "_services._dns-sd._udp.local",   # 服务类型枚举（DNS-SD 总入口）
    "_http._tcp.local",                # HTTP 服务
    "_ipp._tcp.local",                 # 打印机（视频里举的例子）
    "_ollama._tcp.local",              # 假设的 AI 服务类型
    "_localai._tcp.local",             # 视频里的 LocalAI 声明
]:
    r = 探测(名称)
    标记 = "✅ 有应答" if r["收到应答"] else "❌ 无应答"
    print(f"{标记}  {名称}")
    print(f"        字节={r['应答字节数']}  标签数={len(r['可读标签'])}")
    if r["可读标签"]:
        print(f"        样本: {r['可读标签'][:8]}")
    if "异常" in r:
        print(f"        异常: {r['异常']}")
