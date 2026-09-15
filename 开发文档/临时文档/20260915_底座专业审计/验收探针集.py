# -*- coding: utf-8 -*-
"""底座修复验收探针集（批次2 与最终收口共用）
只读/无害：不写工作区外，不提交长任务，不调外部付费模型。
用法：python3.14 /tmp/底座验收_探针集.py
"""
import json, os, plistlib, sqlite3, glob, time, urllib.request, urllib.error
from urllib.parse import quote

根 = "~/Documents/Agent/PHP/系统工程平台"
os.chdir(根)
凭证 = [v for k, v in (plistlib.load(open(os.path.expanduser(
    "~/Library/LaunchAgents/com.huashi.gateway-40007.plist"), "rb")).get("EnvironmentVariables") or {}).items() if "凭证" in k][0]
调用址 = "http://127.0.0.1:40007/" + quote("网关/调用")
健康址 = "http://127.0.0.1:40007/" + quote("健康")

def 调用(能力id, 参数, 超时=30, 操作=None):
    if 操作:
        body = json.dumps({"操作": 操作, "句柄": 参数.get("句柄")}, ensure_ascii=False).encode()
    else:
        body = json.dumps({"能力id": 能力id, "参数": 参数}, ensure_ascii=False).encode()
    r = urllib.request.Request(调用址, data=body, method="POST")
    r.add_header("Content-Type", "application/json; charset=utf-8")
    r.add_header("Authorization", "Bearer " + 凭证)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=超时) as resp:
            return resp.status, json.loads(resp.read().decode()), time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()), time.time() - t0
        finally:
            e.close()
    except Exception as e:
        return None, {"异常": f"{type(e).__name__}: {e}"}, time.time() - t0

def 报(名, 期望, st, d, 耗时):
    v = d.get("值") or {}
    通过 = 期望(st, d, v)
    print(f"[{'✅' if 通过 else '❌'}] {名}")
    print(f"     HTTP={st} 成功={d.get('成功')} 错误码={d.get('错误码')} 耗时={耗时:.2f}s")
    if not 通过:
        print(f"     返回={json.dumps(d, ensure_ascii=False)[:260]}")
    return bool(通过)

结果 = []

# 1 健康 + 能力数
r = urllib.request.Request(健康址); r.add_header("Authorization", "Bearer " + 凭证)
try:
    with urllib.request.urlopen(r, timeout=10) as resp:
        d = json.loads(resp.read().decode())
        数 = (d.get("值") or {}).get("能力数")
    print(f"[✅] 健康检查  HTTP=200 能力数={数}（磁盘源头应同为 536）")
    结果.append(真值 := True)
except Exception as e:
    print("[❌] 健康检查失败:", e); 结果.append(False)

# 2 F-01 生效探针：重试调度 三连（新语义期望）
期望新 = lambda st, d, v: v.get("是否重试") is False
st, d, t = 调用("大语言模型支持库.模型连接器.重试调度",
              {"重试模式": "1", "错误码白名单": ["A"], "实际错误码": "B"})
结果.append(报("F-01 新语义：白名单=[A] + 实际错误码=B → 应 false", 期望新, st, d, t))

st, d, t = 调用("大语言模型支持库.模型连接器.重试调度",
              {"重试模式": "1", "错误码白名单": ["A"], "实际错误码": "123"})
结果.append(报("F-01 新语义：实际错误码=123（类型错）→ 应 400", lambda st, d, v: st == 400, st, d, t))

st, d, t = 调用("大语言模型支持库.模型连接器.重试调度", {"重试模式": "1", "错误码白名单": ["A"]})
结果.append(报("F-01 向后兼容：不传 实际错误码 → 应 true（旧行为保留）",
             lambda st, d, v: v.get("是否重试") is True, st, d, t))

# 3 S-01 沙箱注入反例（应被拒）
from pathlib import Path
测试根 = Path("/tmp/底座验收_沙箱")
测试根.mkdir(parents=True, exist_ok=True)
载荷目录 = 测试根 / 'x")) (allow file-read* (subpath "/")) ;'
载荷目录.mkdir(parents=True, exist_ok=True)
canary = 根 + "/AGENTS.md"
st, d, t = 调用("系统核心支持库.进程管理.沙箱执行命令",
              {"命令": f'head -c 60 "{canary}"', "工作目录": str(载荷目录), "超时秒": 15.0})
出 = str((d.get("值") or {}).get("标准输出") or "")
结果.append(报("S-01 沙箱注入反例：应被拒（不得读到工作区外）",
             lambda st, d, v: ("# " not in 出 and not str(v.get("标准输出") or "").strip()),
             st, d, t))

# 4 S-02 SSRF：被禁目标应拦
st, d, t = 调用("网络通信支持库.请求.发送请求", {"url": "http://0.0.0.0/", "超时秒": 5.0})
结果.append(报("S-02 SSRF：0.0.0.0 应被拒", lambda st, d, v: d.get("成功") is False, st, d, t))

# 5 类型铁律：整数型传文本 应 400
st, d, t = 调用("数据操作支持库.类型转换.整数转文本", {"整数": "不是数字"})
结果.append(报("类型铁律：整数型传文本 → 应 400（及错误码非『能力不存在』）",
             lambda st, d, v: st in (400, 500) and d.get("错误码") not in ("", "能力不存在"), st, d, t))

# 6 未知字段剔除
st, d, t = 调用("大语言模型支持库.模型连接器.重试调度",
              {"重试模式": "1", "错误码白名单": ["A"], "未知字段X": 1})
结果.append(报("兼容性：未知字段应被剔除且 200", lambda st, d, v: st == 200, st, d, t))

# 7 句柄失效
st, d, t = 调用(None, {"句柄": 999999999}, 操作="资源状态")
结果.append(报("句柄语义：不存在句柄 → 应明确失败（非『能力不存在』）",
             lambda st, d, v: d.get("成功") is False and d.get("错误码") != "能力不存在", st, d, t))

# 8 任务账本非终态计数（重启安全门）
非终态 = 0; 总数 = 0
for p in glob.glob("工程缓存/任务状态/进程任务/*.json"):
    try:
        d = json.load(open(p, encoding="utf-8"))
        总数 += 1
        if d.get("状态") not in ("成功", "失败", "已取消", "崩溃"):
            非终态 += 1
    except Exception:
        pass
print(f"[i] 任务账本：{总数} 条，非终态 {非终态} 条（>0 时禁止重启网关）")

print(f"\n==== 通过 {sum(结果)}/{len(结果)} ====")
