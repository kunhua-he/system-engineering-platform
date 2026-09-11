"""批量逐字稿队列：逐场出「还原稿 + 总结稿」，全部落唯一权威落点。

规则（华哥 2026-09-10 定）：
- 每场两份，各自唯一：模式1 = 还原稿，模式9 = 总结稿
- 落点：录音分析/直播逐字稿/<主播目录>/<场次>/<场次>_还原稿.md | _总结稿.md
- 中间产物：同场次 缓存/ 目录
- 断点续跑：已有稿子且质检通过则跳过（可 --强制 重跑）
- 单场失败不影响其它场，进度写 00_批量进度.json，日志追加 00_批量日志.log

用法：
  python3.14 批量精校队列.py --场次数 3            # 先跑 3 场（试跑）
  python3.14 批量精校队列.py                      # 全量
  python3.14 批量精校队列.py --仅主播 03_河北      # 只跑某主播目录
  python3.14 批量精校队列.py --强制               # 忽略已有稿子
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

网关 = "http://127.0.0.1:40007/" + urllib.parse.quote("网关/调用")
凭证 = os.environ.get("系统库网关凭证", "html-blackbox-verifier")
密钥 = os.environ.get("HERMES_CUSTOM_CUSTOM_API_KEY", "").strip()

老项目根 = Path("~/Documents/Hermes工作区/录音分析/免费祛斑免费敷面膜直播精校项目")
权威根 = Path("~/Documents/Hermes工作区/录音分析/直播逐字稿")
进度文件 = 权威根 / "00_批量进度.json"
日志文件 = 权威根 / "00_批量日志.log"

# 消费者侧业务参数（底座通用，业务细节由调用方传）
业务参数 = {
    "附加术语": "华世王镞、免费祛斑、免费去斑、合作店、免费敷面膜、抖音、河北邢台、任泽区",
    "输出结构": "核心卖点 / 活动政策 / 门店与位置 / 观众高频问题 / 可复用话术",
    "附加要求": ("「斑」不能写成「班」、「美业」不能写成「每夜」、「沾水」不能写成「抓水」、"
             "「忌嘴」不能写成「记嘴」、「尴尬期」不能写成「尴尬气」；品牌词华世王镞必须原样保留"),
}
模式名 = {1: "还原稿", 9: "总结稿"}


_日志锁 = threading.Lock()


def 日志(文本: str) -> None:
    with _日志锁:
        with 日志文件.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {文本}\n")
    print(f"[{time.strftime('%H:%M:%S')}] {文本}", flush=True)


def 连接模型句柄() -> int | None:
    """消费者先打通自己的模型，拿一个句柄复用整批（借用不释放）。"""
    体 = json.dumps({"操作": "调用能力",
                   "能力id": "大语言模型支持库.模型连接器.连接LLM",
                   "参数": {"模型": "deepseek-v4-flash", "部署形态": "云端", "提供者": "本地",
                          "url": "http://127.0.0.1:8328/hermes-chat/v1", "api_key": 密钥,
                          "协议": "chat_completions", "上下文长度": 32768, "超时秒": 1800}},
                  ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(网关, data=体, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {凭证}"})
    try:
        with urllib.request.urlopen(请求, timeout=120) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
        return (数据.get("值") or {}).get("句柄")
    except Exception as 错误:
        日志(f"连接模型失败（将退回传配置）：{type(错误).__name__} {错误}")
        return None


def 跑一场(源文件: Path, 场次目录名: str, 主播目录: str, 模式: int, 句柄: int | None,
          超时秒: float = 7200.0) -> tuple[bool, str]:
    场次目录 = 权威根 / 主播目录 / 场次目录名
    场次目录.mkdir(parents=True, exist_ok=True)
    导出 = 场次目录 / f"{场次目录名}_{模式名[模式]}.md"
    参数 = {
        "源文件路径": str(源文件),
        "导出路径": str(导出),
        "缓存目录": str(场次目录 / "缓存" / f"模式{模式}"),
        "模式": 模式,
        "分片秒数": 300,
        "超时秒": 超时秒,
        **业务参数,
    }
    if 句柄:
        参数["裁决模型句柄"] = 句柄
    else:
        参数["裁决模型配置"] = {"模型": "deepseek-v4-flash", "部署形态": "云端",
                           "url": "http://127.0.0.1:8328/hermes-chat/v1", "api_key": 密钥,
                           "协议": "chat_completions", "上下文长度": 32768, "超时秒": 1800}
    体 = json.dumps({"操作": "调用能力", "能力id": "直播逐字稿.全自动精校", "参数": 参数},
                  ensure_ascii=False).encode("utf-8")
    请求 = urllib.request.Request(网关, data=体, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {凭证}"})
    开始 = time.time()
    try:
        with urllib.request.urlopen(请求, timeout=超时秒 + 600) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
    except Exception as 错误:
        return False, f"{type(错误).__name__} {错误}"
    值 = 数据.get("值") or {}
    报告 = 值.get("质检") or {}
    用时 = time.time() - 开始
    if 数据.get("成功") and 报告.get("通过") and 导出.is_file():
        return True, f"{用时:.0f}秒 | {值.get('字数')}字 | 裁决失败窗口 {报告.get('裁决失败窗口')}"
    return False, (f"{用时:.0f}秒 | 错误码 {数据.get('错误码')} {str(数据.get('错误说明'))[:60]}"
                   f" | 质检通过={报告.get('通过')} 异常残句={报告.get('异常残句')}")


def 读进度() -> dict:
    if 进度文件.is_file():
        try:
            return json.loads(进度文件.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"场次": {}}


def 按视频时长排序(视频表: list[Path]) -> list[Path]:
    """按视频时长升序（ffprobe；时长取不到的排最后）。试跑用小场次快速验证流程。"""
    from concurrent.futures import ThreadPoolExecutor

    def 时长(p: Path) -> float:
        try:
            出 = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(p)], capture_output=True, text=True, timeout=60)
            return float(出.stdout.strip() or 0)
        except Exception:
            return 0.0

    with ThreadPoolExecutor(max_workers=8) as 池:
        对 = list(zip(视频表, 池.map(时长, 视频表)))
    return [p for p, s in sorted(对, key=lambda x: x[1] if x[1] > 0 else 1e9)]


def 写进度(进度: dict) -> None:
    进度["更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    进度文件.write_text(json.dumps(进度, ensure_ascii=False, indent=2), encoding="utf-8")


def 主() -> int:
    解析 = argparse.ArgumentParser()
    解析.add_argument("--场次数", type=int, default=0, help="只跑前 N 场（0=全部）")
    解析.add_argument("--最短场次", type=int, default=0, help="取最短的 N 场试跑（按视频时长升序）")
    解析.add_argument("--仅主播", default="", help="只跑指定主播目录名，如 03_河北")
    解析.add_argument("--强制", action="store_true", help="忽略已有稿子重跑")
    解析.add_argument("--重试次数", type=int, default=3,
                    help="单场失败自动重试次数（网关重启/瞬时故障自动补跑）")
    解析.add_argument("--并发场次", type=int, default=1,
                    help="同时处理几场。实测并发 2 反而更慢（两场同时转写争 GPU、同时调模型更易撞 503）："
                         "场内已有裁决窗口并发，场间默认保持串行")
    参数 = 解析.parse_args()

    视频表 = sorted(老项目根.rglob("合并视频.mp4"))
    if 参数.仅主播:
        视频表 = [p for p in 视频表 if p.parent.parent.name == 参数.仅主播]
    if 参数.最短场次 > 0:
        视频表 = 按视频时长排序(视频表)[:参数.最短场次]
    if 参数.场次数 > 0:
        视频表 = 视频表[:参数.场次数]
    权威根.mkdir(parents=True, exist_ok=True)
    并发 = max(1, int(参数.并发场次 or 1))
    日志(f"队列启动：{len(视频表)} 场 × 2 模式（还原 + 总结），并发场次 {并发}")

    进度 = 读进度()
    统计 = {"成功": 0, "失败": 0, "跳过": 0}
    统计锁 = threading.Lock()
    开始总 = time.time()

    def 处理一场(序号: int, 源: Path) -> None:
        """一场的两个模式串行；句柄每场独立（句柄 30 分钟空闲会被回收，不跨场复用）。"""
        场次目录名 = 源.parent.name
        主播目录 = 源.parent.parent.name
        局部句柄 = 连接模型句柄()
        try:
            for 模式 in (1, 9):
                键 = f"{主播目录}/{场次目录名}/模式{模式}"
                导出 = 权威根 / 主播目录 / 场次目录名 / f"{场次目录名}_{模式名[模式]}.md"
                if 导出.is_file() and not 参数.强制:
                    with 统计锁:
                        统计["跳过"] += 1
                    continue
                日志(f"[{序号}/{len(视频表)}] {场次目录名} 模式{模式}({模式名[模式]}) 开始")
                成功, 说明 = False, ""
                for 尝试 in range(1, max(1, 参数.重试次数) + 1):
                    成功, 说明 = 跑一场(源, 场次目录名, 主播目录, 模式, 局部句柄)
                    if 成功:
                        break
                    日志(f"    {场次目录名} 模式{模式} 第{尝试}次失败：{说明}")
                    if 尝试 < max(1, 参数.重试次数):
                        time.sleep(20)   # 上游抖动给一点恢复时间；缓存续跑只补缺
                        局部句柄 = 连接模型句柄() or 局部句柄
                with 统计锁:
                    统计["成功" if 成功 else "失败"] += 1
                    进度["场次"][键] = {"成功": 成功, "说明": 说明,
                                  "时间": time.strftime("%Y-%m-%d %H:%M:%S")}
                    写进度(进度)
                日志(f"    {'✓' if 成功 else '✗'} {场次目录名} 模式{模式} {说明}")
        finally:
            if 局部句柄:
                try:
                    体 = json.dumps({"操作": "调用能力",
                                 "能力id": "大语言模型支持库.模型连接器.释放句柄",
                                 "参数": {"句柄": 局部句柄}}, ensure_ascii=False).encode("utf-8")
                    urllib.request.urlopen(urllib.request.Request(网关, data=体, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {凭证}"}), timeout=60).read()
                except Exception:
                    pass

    任务表 = list(enumerate(视频表, start=1))
    if 并发 > 1:
        with ThreadPoolExecutor(max_workers=并发) as 池:
            list(池.map(lambda 项: 处理一场(*项), 任务表))
    else:
        for 项 in 任务表:
            处理一场(*项)

    总用时 = (time.time() - 开始总) / 60
    日志(f"队列结束：成功 {统计['成功']} / 失败 {统计['失败']} / 跳过 {统计['跳过']}，"
        f"总耗时 {总用时:.1f} 分钟")
    return 0 if 统计["失败"] == 0 else 1


if __name__ == "__main__":
    sys.exit(主())
