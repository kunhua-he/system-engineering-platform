"""批量逐字稿队列：逐场出「还原稿 + 总结稿」，全部落唯一权威落点。

规则：
- 每场两份，各自唯一：模式1 = 还原稿，模式9 = 总结稿
- 落点：<权威根>/<主播目录>/<场次>/<场次>_还原稿.md | _总结稿.md
- 中间产物：同场次 缓存/ 目录
- 断点续跑：已有稿子且质检通过则跳过（可 --强制 重跑）
- 单场失败不影响其它场，进度写 00_批量进度.json，日志追加 00_批量日志.log

本脚本是消费者侧工具：素材根目录、权威落点、网关、凭证、模型端点/模型名、以及行业词
（附加术语/输出结构/附加要求）**一律由调用方传参**，底座不写死任何业务路径与品牌/行业词。

用法：
  python3.14 批量精校队列.py --配置 队列配置.json --场次数 3     # 先跑 3 场（试跑）
  python3.14 批量精校队列.py --配置 队列配置.json               # 全量
  python3.14 批量精校队列.py --配置 队列配置.json --仅主播 03_示例主播
  python3.14 批量精校队列.py --配置 队列配置.json --强制        # 忽略已有稿子

配置包（JSON 对象；同名环境变量优先，路径也可用 --项目根/--权威根 传）：
  项目根      素材根目录（rglob 合并视频.mp4 的起点）     必填
  权威根      成稿与进度/日志的落点根目录                 必填
  网关凭证    平台网关凭证                              必填
  模型密钥    模型服务 api_key                          必填
  模型端点    模型服务地址（如 http://<主机>:<端口>/v1）  必填
  模型名      模型名                                    必填
  网关        平台网关地址      非必填，默认平台本机网关
  附加术语    必须原样保留的词   非必填，缺省即不传（不猜任何行业词）
  输出结构    分节结构          非必填，缺省即不传
  附加要求    易错词校正/行业口径 非必填，缺省即不传

环境变量回退名：逐字稿项目根 / 逐字稿权威根 / 逐字稿网关 / 系统库网关凭证 /
HERMES_CUSTOM_CUSTOM_API_KEY / 逐字稿模型端点 / 逐字稿模型名 /
逐字稿附加术语 / 逐字稿输出结构 / 逐字稿附加要求 / 逐字稿队列配置（配置包路径）。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# 唯一一条 HTTP 腿（#85 收口）：本文件不再自建 urllib 客户端，收发一律走它。
from 开发工具.薄壳.网关转发 import 发送

# 平台本机网关：平台自身入口（不是业务端口），可被配置包 网关 覆盖
默认网关 = "http://127.0.0.1:40007/" + urllib.parse.quote("网关/调用")
必填键 = ("项目根", "权威根", "网关凭证", "模型密钥", "模型端点", "模型名")
# 行业键：非必填，缺省即不传 —— 底座绝不内置默认业务词
行业键 = ("附加术语", "输出结构", "附加要求")
环境变量表 = {
    "项目根": "逐字稿项目根",
    "权威根": "逐字稿权威根",
    "网关": "逐字稿网关",
    "网关凭证": "系统库网关凭证",
    "模型密钥": "HERMES_CUSTOM_CUSTOM_API_KEY",
    "模型端点": "逐字稿模型端点",
    "模型名": "逐字稿模型名",
    "附加术语": "逐字稿附加术语",
    "输出结构": "逐字稿输出结构",
    "附加要求": "逐字稿附加要求",
}
# 容错路径留痕（哲学第 3 条 2 项：不许 except: pass 吞掉；句柄释放失败要能查到）
释放问题: list[str] = []
模式名 = {1: "还原稿", 9: "总结稿"}
_日志锁 = threading.Lock()


@dataclass
class 运行配置:
    """一次批量运行的全部外部参数（全部由调用方传参，底座零写死）。"""

    项目根: Path
    权威根: Path
    网关: str
    网关凭证: str
    模型密钥: str
    模型端点: str
    模型名: str
    业务参数: dict[str, str] = field(default_factory=dict)

    @property
    def 进度文件(self) -> Path:
        return self.权威根 / "00_批量进度.json"

    @property
    def 日志文件(self) -> Path:
        return self.权威根 / "00_批量日志.log"

    def 模型参数(self) -> dict:
        """模型连接参数：端点/模型名来自调用方，不写死本机业务端口。"""
        return {"模型": self.模型名, "部署形态": "云端", "提供者": "本地",
                "url": self.模型端点, "api_key": self.模型密钥,
                "协议": "chat_completions", "上下文长度": 32768, "超时秒": 1800}


def 读配置(配置路径: Path | None) -> dict:
    """读配置包（JSON）并叠加同名环境变量；环境变量优先。"""
    if 配置路径 is not None and not 配置路径.is_file():
        raise ValueError(f"配置文件不存在: {配置路径}")
    数据: dict = {}
    if 配置路径 is not None:
        try:
            读入 = json.loads(配置路径.read_text(encoding="utf-8"))
        except (OSError, ValueError) as 错误:
            raise ValueError(f"配置文件不可读: {配置路径}: {错误}") from 错误
        if not isinstance(读入, dict):
            raise ValueError(f"配置文件必须是 JSON 对象（键值对）: {配置路径}")
        数据 = dict(读入)
    for 键, 环境名 in 环境变量表.items():
        值 = os.environ.get(环境名, "").strip()
        if 值:
            数据[键] = 值
    return 数据


def 装配配置(原始: dict, *, 项目根覆盖: str = "", 权威根覆盖: str = "") -> 运行配置:
    """把原始键值装配成 运行配置；缺必填项直接报错退出（不猜业务路径）。"""
    补齐 = dict(原始)
    if 项目根覆盖.strip():
        补齐["项目根"] = 项目根覆盖.strip()
    if 权威根覆盖.strip():
        补齐["权威根"] = 权威根覆盖.strip()
    缺失 = [键 for 键 in 必填键 if not str(补齐.get(键) or "").strip()]
    if 缺失:
        raise ValueError(
            "缺必填配置项：" + "、".join(缺失)
            + "（用 --配置 <json> 传配置包，或设置同名环境变量；"
              "底座不猜业务路径、不内置默认凭证、不写死模型端点）")
    业务参数 = {键: str(补齐[键]) for 键 in 行业键 if str(补齐.get(键) or "").strip()}
    return 运行配置(
        项目根=Path(str(补齐["项目根"])).expanduser(),
        权威根=Path(str(补齐["权威根"])).expanduser(),
        网关=str(补齐.get("网关") or "").strip() or 默认网关,
        网关凭证=str(补齐["网关凭证"]),
        模型密钥=str(补齐["模型密钥"]),
        模型端点=str(补齐["模型端点"]),
        模型名=str(补齐["模型名"]),
        业务参数=业务参数,
    )


def 日志(配置: 运行配置, 文本: str) -> None:
    with _日志锁:
        with 配置.日志文件.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {文本}\n")
    print(f"[{time.strftime('%H:%M:%S')}] {文本}", flush=True)


def 连接模型句柄(配置: 运行配置) -> int | None:
    """消费者先打通自己的模型，拿一个句柄复用整批（借用不释放）。"""
    结果 = 发送(配置.网关, {"操作": "调用能力",
                        "能力id": "大语言模型支持库.模型连接器.连接LLM",
                        "参数": 配置.模型参数()},
                凭证=配置.网关凭证, 超时秒=120)
    if 结果["错误码"]:
        日志(配置, f"连接模型失败（将退回传配置）：{结果['错误码']} {结果['错误说明']}")
        return None
    return ((结果["信封"] or {}).get("值") or {}).get("句柄")


def 跑一场(配置: 运行配置, 源文件: Path, 场次目录名: str, 主播目录: str, 模式: int,
          句柄: int | None, 超时秒: float = 7200.0) -> tuple[bool, str]:
    场次目录 = 配置.权威根 / 主播目录 / 场次目录名
    场次目录.mkdir(parents=True, exist_ok=True)
    导出 = 场次目录 / f"{场次目录名}_{模式名[模式]}.md"
    参数 = {
        "源文件路径": str(源文件),
        "导出路径": str(导出),
        "缓存目录": str(场次目录 / "缓存" / f"模式{模式}"),
        "模式": 模式,
        "分片秒数": 300,
        "超时秒": 超时秒,
    }
    # 行业词只在调用方给了才传；没给就不传，底座不填默认业务词
    参数.update(配置.业务参数)
    if 句柄:
        参数["裁决模型句柄"] = 句柄
    else:
        参数["裁决模型配置"] = 配置.模型参数()
    开始 = time.time()
    结果 = 发送(配置.网关, {"操作": "调用能力", "能力id": "直播逐字稿.全自动精校",
                        "参数": 参数},
                凭证=配置.网关凭证, 超时秒=超时秒 + 600)
    if 结果["错误码"]:
        return 假, f"{结果['错误码']} {结果['错误说明']}"
    数据 = 结果["信封"] or {}
    值 = 数据.get("值") or {}
    报告 = 值.get("质检") or {}
    用时 = time.time() - 开始
    if 数据.get("成功") and 报告.get("通过") and 导出.is_file():
        return 真, f"{用时:.0f}秒 | {值.get('字数')}字 | 裁决失败窗口 {报告.get('裁决失败窗口')}"
    return 假, (f"{用时:.0f}秒 | 错误码 {数据.get('错误码')} {str(数据.get('错误说明'))[:60]}"
                   f" | 质检通过={报告.get('通过')} 异常残句={报告.get('异常残句')}")


def 读进度(配置: 运行配置) -> dict:
    if 配置.进度文件.is_file():
        try:
            return json.loads(配置.进度文件.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"场次": {}}


def 按视频时长排序(视频表: list[Path]) -> list[Path]:
    """按视频时长升序（ffprobe；时长取不到的排最后）。试跑用小场次快速验证流程。"""

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


def 写进度(配置: 运行配置, 进度: dict) -> None:
    进度["更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    配置.进度文件.write_text(json.dumps(进度, ensure_ascii=False, indent=2), encoding="utf-8")


def 主() -> int:
    解析 = argparse.ArgumentParser(description="批量逐字稿队列（消费者侧工具，参数全部由调用方传）")
    解析.add_argument("--配置", default=os.environ.get("逐字稿队列配置", ""),
                    help="配置包 JSON 路径（键见脚本头部说明；同名环境变量优先）")
    解析.add_argument("--项目根", default="", help="素材根目录（覆盖配置包 项目根）")
    解析.add_argument("--权威根", default="", help="成稿落点根目录（覆盖配置包 权威根）")
    解析.add_argument("--场次数", type=int, default=0, help="只跑前 N 场（0=全部）")
    解析.add_argument("--最短场次", type=int, default=0, help="取最短的 N 场试跑（按视频时长升序）")
    解析.add_argument("--仅主播", default="", help="只跑指定主播目录名，如 03_示例主播")
    解析.add_argument("--强制", action="store_true", help="忽略已有稿子重跑")
    解析.add_argument("--重试次数", type=int, default=3,
                    help="单场失败自动重试次数（网关重启/瞬时故障自动补跑）")
    解析.add_argument("--并发场次", type=int, default=1,
                    help="同时处理几场。实测并发 2 反而更慢（两场同时转写争 GPU、同时调模型更易撞 503）："
                         "场内已有裁决窗口并发，场间默认保持串行")
    参数 = 解析.parse_args()

    配置路径 = Path(参数.配置).expanduser() if 参数.配置.strip() else None
    try:
        配置 = 装配配置(读配置(配置路径), 项目根覆盖=参数.项目根, 权威根覆盖=参数.权威根)
    except ValueError as 错误:
        print(f"配置不完整：{错误}")
        print("用法：python3.14 批量精校队列.py --配置 队列配置.json "
              "[--项目根 路径] [--权威根 路径] [--场次数 N] [--仅主播 目录名] [--强制]")
        return 2

    视频表 = sorted(配置.项目根.rglob("合并视频.mp4"))
    if 参数.仅主播:
        视频表 = [p for p in 视频表 if p.parent.parent.name == 参数.仅主播]
    if 参数.最短场次 > 0:
        视频表 = 按视频时长排序(视频表)[:参数.最短场次]
    if 参数.场次数 > 0:
        视频表 = 视频表[:参数.场次数]
    配置.权威根.mkdir(parents=True, exist_ok=True)
    并发 = max(1, int(参数.并发场次 or 1))
    日志(配置, f"队列启动：{len(视频表)} 场 × 2 模式（还原 + 总结），并发场次 {并发}")

    进度 = 读进度(配置)
    统计 = {"成功": 0, "失败": 0, "跳过": 0}
    统计锁 = threading.Lock()
    开始总 = time.time()

    def 处理一场(序号: int, 源: Path) -> None:
        """一场的两个模式串行；句柄每场独立（句柄 30 分钟空闲会被回收，不跨场复用）。"""
        场次目录名 = 源.parent.name
        主播目录 = 源.parent.parent.name
        局部句柄 = 连接模型句柄(配置)
        try:
            for 模式 in (1, 9):
                键 = f"{主播目录}/{场次目录名}/模式{模式}"
                导出 = 配置.权威根 / 主播目录 / 场次目录名 / f"{场次目录名}_{模式名[模式]}.md"
                if 导出.is_file() and not 参数.强制:
                    with 统计锁:
                        统计["跳过"] += 1
                    continue
                日志(配置, f"[{序号}/{len(视频表)}] {场次目录名} 模式{模式}({模式名[模式]}) 开始")
                成功, 说明 = False, ""
                for 尝试 in range(1, max(1, 参数.重试次数) + 1):
                    成功, 说明 = 跑一场(配置, 源, 场次目录名, 主播目录, 模式, 局部句柄)
                    if 成功:
                        break
                    日志(配置, f"    {场次目录名} 模式{模式} 第{尝试}次失败：{说明}")
                    if 尝试 < max(1, 参数.重试次数):
                        time.sleep(20)   # 上游抖动给一点恢复时间；缓存续跑只补缺
                        局部句柄 = 连接模型句柄(配置) or 局部句柄
                with 统计锁:
                    统计["成功" if 成功 else "失败"] += 1
                    进度["场次"][键] = {"成功": 成功, "说明": 说明,
                                  "时间": time.strftime("%Y-%m-%d %H:%M:%S")}
                    写进度(配置, 进度)
                日志(配置, f"    {'✓' if 成功 else '✗'} {场次目录名} 模式{模式} {说明}")
        finally:
            if 局部句柄:
                try:
                    释放结果 = 发送(配置.网关,
                                {"操作": "调用能力",
                                 "能力id": "大语言模型支持库.模型连接器.释放句柄",
                                 "参数": {"句柄": 局部句柄}},
                                凭证=配置.网关凭证, 超时秒=60)
                    if 释放结果["错误码"]:
                        raise RuntimeError(
                            f"{释放结果['错误码']} {释放结果['错误说明']}")
                except Exception as 释放错误:
                    # 句柄释放失败必须留痕（哲学第 3 条 2 项：失败要明确，不许 except: pass）
                    释放问题.append(f"句柄 {局部句柄} 释放失败: {释放错误}")

    任务表 = list(enumerate(视频表, start=1))
    if 并发 > 1:
        with ThreadPoolExecutor(max_workers=并发) as 池:
            list(池.map(lambda 项: 处理一场(*项), 任务表))
    else:
        for 项 in 任务表:
            处理一场(*项)

    总用时 = (time.time() - 开始总) / 60
    日志(配置, f"队列结束：成功 {统计['成功']} / 失败 {统计['失败']} / 跳过 {统计['跳过']}，"
        f"总耗时 {总用时:.1f} 分钟")
    return 0 if 统计["失败"] == 0 else 1


if __name__ == "__main__":
    sys.exit(主())
