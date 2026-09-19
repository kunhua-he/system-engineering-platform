"""本地启动的准备与守卫：模型源识别、供应链校验、内存守卫、启动命令与就绪等待。

2026-09-19 从 `实现/模型连接器.py` 原样搬出（对外零变化，成员名一个不改）。
本模块只做**可独立验证的准备与判定**，不含启动副作用（不建句柄、不拉进程）：

- `_识别模型源` / `_计算模型大小` / `_分配端口`：路径与端口的纯计算。
  `_识别模型源` 是「格式 + 规范化绝对路径」的唯一判据，供应链与启动命令共用；
- **供应链层**（审计报告 §B9）：`_供应链守卫` / `_启动器守卫` / `_供应链判定` /
  `校验模型完整性` / `_解析启动器二进制` / `_启动器校验`。判定顺序固定
  「存在性 → 字节数 → sha256」，任一层不符即 fail-closed、给中文原因。
  **判据的唯一实现在 `实现/模型供应链校验.py`**，本模块只接线，不复制第二套；
- **内存守卫**：`_系统内存快照` / `_预计占用` / `_内存守卫`。第三方 psutil 只在适配层出现，
  本模块经「支持库.适配层.系统探针」的汉化原子能力《读取系统内存》取真值；
  探针不可用一律 fail-closed（绝不在「未知」时放行）；
- `_构建本地启动命令` / `_启动日志路径` / `_读启动日志尾部` / `_等待本地健康`：
  启动命令装配与日志、健康判据。`_解析启动器二进制` 的候选顺序（latest 优先）此处共用
  —— 校验的必须是**真正会被执行的那个二进制**。

**为什么这几段能独立成文件（2026-09-19 实测）**：搬出段按名引用的外部符号只有
`降级记录表` / `_失败` / `内存安全阈值`（三个都在 `模型连接基元`）+ 模块自带的
`_供应链校验` / `结果` / `Any`，**对启动器段（`_启动本地模型` 等）的引用数为 0** ——
与上一轮实测「会形成双向依赖的『本地模型启动器』整段」不同：本次搬的是它**下面的准备层**，
栈仍是单向向下依赖，`_启动本地模型` 留在主文件、向上引用本模块。

栈的接口：`_启动本地模型`（主文件）拿到 `_启动前供应链阻断` 的判定、
`_构建本地启动命令` 的命令、`_等待本地健康` 的就绪结论后，才创建句柄与进程。

⚠️ 保真说明（本文件唯一一处非逐字节改写）：`_等待本地健康` 的两行返回值随本段搬来后，
会以「新文件里的裸布尔」被发布门禁的防回潮分桶基线判成**新增违规**
（实测：本文件 2 条 vs 基线 0）；故按 `公共契约/基础类型/逻辑类型.py` 的口径
落成正式类型名 `真` / `假`（`真 = True` / `假 = False`，**取值与身份都不变**，
`is True` 仍成立）。累计存量随之 8 → 6，分桶基线已同步下调。除这两行以外，本文件逐字节来自基线。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 假, 真
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型供应链校验 as _供应链校验

from 支持库.后端.大语言模型支持库.模型连接器.实现.模型连接基元 import (
    降级记录表,
    _失败,
    内存安全阈值,
)


def _识别模型源(模型路径: str) -> tuple[str, str]:
    """按实体文件判断模型源格式，返回（格式, 规范化绝对路径）。"""
    from pathlib import Path
    路径 = Path(模型路径).expanduser().resolve()
    if 路径.is_file() and 路径.suffix.lower() == ".gguf":
        return "GGUF", str(路径)
    if 路径.is_dir() and (路径 / "config.json").is_file():
        if any(路径.glob("*.safetensors")) or any(路径.glob("*.bin")):
            return "HuggingFace", str(路径)
    return "不支持", str(路径)


def _供应链系统根() -> Path:
    """本包所在系统根（源码态 = 仓库根；制品态 = 平台客户端根）。"""
    return Path(__file__).resolve().parents[5]


def _供应链守卫(规范路径: str, 源格式: str) -> 结果 | None:
    """启动前的模型二进制供应链校验（版本固定 + 哈希校验 + fail-closed）。

    审计报告 §B9：模型权重与启动器原先完全没有校验，被替换/截断/换版本都不会有人发现。
    本层把校验挂在**启动动作之前**（不是「检查可用性」这种只读探针上），
    判定顺序 = 存在性 → 字节数 → sha256，任一层不符即拒绝启动并返回中文原因。

    判定语义（与 实现/模型供应链校验.py 同一份实现，不另写第二套）：
      * 权重文件：受管模型库内未登记 → 拒绝；调用方自备路径未登记 → 放行并如实标注；
      * 启动器二进制：必须已登记（版本固定），未登记一律拒绝；
      * 清单自身读不成（丢失/损坏）→ 拒绝启动，绝不「校验不了就放行」。
    逃生口是显式的：环境变量 `系统工程平台_模型校验=关闭` 只报不拦（留痕，不做默认）。
    """
    系统根 = _供应链系统根()
    try:
        格式 = _供应链校验.校验模型目录(规范路径, 系统根=系统根) if 源格式 == "HuggingFace" \
            else _供应链校验.校验模型文件(规范路径, 系统根=系统根)
    except Exception as 错误:  # 校验层自身异常同样 fail-closed，不让「校验不了」变成「放行」
        return _失败("模型完整性校验失败", f"模型二进制供应链校验执行失败: {错误}")
    if not 格式.get("通过"):
        return _失败(str(格式.get("错误码") or "模型完整性校验失败"),
                     str(格式.get("错误说明") or "模型二进制供应链校验未通过"),
                     详情={k: v for k, v in 格式.items() if k != "错误说明"})
    return None


def _启动器守卫(二进制: str) -> 结果 | None:
    """启动器二进制的版本固定校验（未登记即拒绝）。"""
    try:
        判定 = _供应链校验.校验模型启动器(二进制, 系统根=_供应链系统根())
    except Exception as 错误:
        return _失败("模型完整性校验失败", f"模型启动器供应链校验执行失败: {错误}")
    if not 判定.get("通过"):
        return _失败(str(判定.get("错误码") or "模型完整性校验失败"),
                     str(判定.get("错误说明") or "模型启动器供应链校验未通过"),
                     详情={k: v for k, v in 判定.items() if k != "错误说明"})
    return None


def _启动前供应链阻断(规范路径: str, 模型类型: str, 启动器: str) -> 结果 | None:
    """启动前的唯一阻断判定：**通过返回 None，不通过返回失败结果**。

    ⚠️ 形状铁律：本函数是「谓词」，通过必须返回 None。绝不能让「校验通过」的
    **成功结果**漏出去 —— 调用点写的是 `if 阻断 is not None: return 阻断`，
    一个成功结果会被当成阻断返回，把「校验通过」变成「启动被取消」。
    （实测踩过：反向验证第三拍报「启动本地模型必须失败」而实际它返回了成功结果，
    句柄却是 None —— 正是这个形状病。）

    对外仍提供结果型入口 `校验模型完整性`（成功/失败都是结果），
    两者共用 `_供应链判定`，判定逻辑只有一份。
    """
    判定 = _供应链判定(规范路径, 模型类型, 启动器)
    return None if 判定.get("通过") else 判定["失败结果"]


def _供应链判定(规范路径: str, 模型类型: str, 启动器: str) -> dict[str, Any]:
    """三层校验的公共内核：返回 {"通过": bool, "失败结果": 结果, "值": dict}。"""
    类型 = (模型类型 or "LLM").lower()
    类型 = "LLM" if 类型 in ("对话", "llm") else "向量" if 类型 in ("嵌入", "向量", "embedding") \
        else "重排" if 类型 in ("排序", "重排", "rerank") else "LLM"
    源格式, 规范 = _识别模型源(规范路径)
    if 源格式 == "不支持":
        return {"通过": False, "值": {},
                "失败结果": _失败("参数不合法",
                                  "底座不支持该模型源；本地模型应为 GGUF 文件或含 config.json 的权重目录")}
    权重 = _供应链守卫(规范, 源格式)
    if 权重 is not None:
        return {"通过": False, "失败结果": 权重, "值": {}}
    启动器错误 = _启动器校验(启动器, 源格式)
    if 启动器错误 is not None:
        return {"通过": False, "失败结果": 启动器错误, "值": {}}
    return {"通过": True, "失败结果": None,
            "值": {"模型类型": 类型, "模型路径": 规范, "模型源格式": 源格式,
                   "校验模式": _供应链校验.解析校验模式(),
                   "说明": "模型源通过供应链校验（存在性 → 字节数 → sha256；受管外未登记为如实标注放行）"}}


def 校验模型完整性(模型路径: str, 模型类型: str = None, 启动器: str = None) -> 结果:
    """校验单个模型源（权重 + 启动器）的供应链完整性，供装载前自检与巡检复用。

    与启动路径**同一份判据**（都走 `_供应链判定`）。返回统一结果：
    通过 → `结果.成功结果({模型类型, 模型路径, 模型源格式, 校验模式, 说明})`；
    不通过 → 供应链类失败结果（错误码 `未登记` / `文件摘要不符`，中文原因可直接读）。
    """
    if not isinstance(模型路径, str) or not 模型路径.strip():
        return _失败("参数不合法", "模型路径必须是非空文本")
    判定 = _供应链判定(模型路径, 模型类型 or "LLM", str(启动器 or ""))
    return 结果.成功结果(判定["值"]) if 判定.get("通过") else 判定["失败结果"]


def _解析启动器二进制(启动器: str = "") -> str:
    """按唯一候选顺序解析真实启动器二进制（`latest` 优先）；找不到返回空串。

    `_构建本地启动命令` 与 `_启动器校验` 共用本函数 —— 校验的必须是**真正会被执行的那个二进制**，
    否则「校验通过」与「实际运行」就不是同一个对象（供应链治理最典型的假绿）。
    """
    import shutil
    候选二进制 = [启动器 or "", os.environ.get("LLAMA_CPP_SERVER_BIN", ""), shutil.which("llama-server")]
    候选二进制.extend(str(Path.home() / 路径) for 路径 in (
        # 2026-09-16 实测修正：原顺序把 llama.cpp-old 排在 latest 前面。
        # 旧版二进制不支持新架构（实测 Qwen3.6-27B 的 SSM 张量
        # blk.64.ssm_conv1d.weight 缺失直接加载失败，报 missing tensor），
        # 而报错里看不出用了哪个二进制，极难定位——同一文件手动用 latest
        # 跑得好好的，经底座就失败，会被误判成权限或文件损坏。
        # 因此 latest 优先；需要走旧版时用 启动器 显式传绝对路径或设
        # 环境变量 LLAMA_CPP_SERVER_BIN。
        "llama.cpp-latest/build/bin/llama-server",
        "llama.cpp-old/build/bin/llama-server"))
    return next((路径 for 路径 in 候选二进制
                 if 路径 and os.path.isfile(路径) and os.access(路径, os.X_OK)), "")


def _启动器校验(启动器: str = "", 源格式: str = "GGUF") -> 结果 | None:
    """解析真实启动器二进制并校验；HuggingFace 目录走底座内部加载器，不涉及启动器。"""
    if 源格式 == "HuggingFace":
        return None
    二进制 = _解析启动器二进制(启动器)
    if not 二进制:
        return _失败("提供者不可用", "未找到 llama-server；请配置 LLAMA_CPP_SERVER_BIN")
    return _启动器守卫(二进制)

# 本地模型内存估算系数（2026-09-16 实测修正）：
#   Qwen3.6-27B-Q5_K_M.gguf 文件 18.5GB，加载完成（-c 8192 -ngl 99）后实测 RSS 19.7GB，
#   倍率 1.06。原实现按「文件大小 × 2」估算得 36.9GB，会把本机明明能跑的模型判成内存不足，
#   用户会误读成硬件不够。取 1.15 保留安全余量（覆盖 KV cache 与量化反量化缓冲）。


本地模型估算系数 = 1.15


def _系统内存快照() -> dict[str, Any]:
    """返回系统内存快照：总量/已用/可用/占用率（失败返回 可用=假，不伪造数字）。

    第三方只在适配层出现：本处经「支持库.适配层.系统探针」的汉化原子能力
    《读取系统内存》取真值，本实现不 import 任何第三方。探针不可用（未安装/
    适配层不可导入/取用异常）一律返回 可用=假，由 _内存守卫 fail-closed 拒绝新连接。
    """
    try:
        from 支持库.适配层.系统探针 import 读取系统内存
        快照 = 读取系统内存()
    except Exception as 错误:  # 适配层不可导入：与「探针不可用」同一语义，绝不静默放行
        降级记录表.append(f"系统内存探针不可用: {错误}")
        return {"可用": False, "说明": f"系统内存探针不可用，无法做系统内存检查: {错误}"}
    if not 快照.可用:
        return {"可用": False,
                "说明": 快照.不可用原因 or "系统内存探针不可用，无法做系统内存检查"}
    return {
        "可用": True,
        "总量字节": 快照.总量字节, "可用字节": 快照.可用字节, "已用字节": 快照.已用字节,
        "占用率": 快照.占用率,
        "说明": 快照.说明,
    }


def _预计占用(连接类型: str, 配置: dict) -> int:
    """估算一个新连接的内存占用（字节）。本地大模型按模型大小估算；云端按小头估算。"""
    部署形态 = 配置.get("部署形态") or "本地"
    if 部署形态 == "云端":
        return 512 * 1024 * 1024  # 云端连接占用小（512MB 预算）
    # 本地：优先按 模型大小 估算，否则按类型默认
    大小 = 配置.get("模型大小字节")
    if isinstance(大小, (int, float)) and 大小 > 0:
        # 估算系数可被调用方覆盖（内存估算系数），缺省用实测标定值
        系数 = 配置.get("内存估算系数")
        try:
            系数 = float(系数) if 系数 is not None else 本地模型估算系数
        except (TypeError, ValueError):
            系数 = 本地模型估算系数
        if 系数 <= 0:
            系数 = 本地模型估算系数
        return int(大小 * 系数)
    默认表 = {"LLM": 8 * 1024**3, "向量": 2 * 1024**3, "重排": 2 * 1024**3}  # LLM 8GB/向量 2GB/重排 2GB
    return 默认表.get(连接类型, 2 * 1024**3)


def _内存守卫(连接类型: str, 配置: dict) -> 结果 | None:
    """系统内存安全检查：预计占用超安全阈值或探针不可用时拒绝。"""
    快照 = _系统内存快照()
    if not 快照.get("可用"):
        return _失败("资源预算未验证", "系统内存探针不可用，拒绝启动新模型以避免突破内存预算")
    预计 = _预计占用(连接类型, 配置)
    总量 = 快照["总量字节"]
    当前已用 = 快照["已用字节"]
    新占用率 = (当前已用 + 预计) / 总量
    阈值 = 配置.get("内存安全阈值") or 内存安全阈值
    if 新占用率 > 阈值:
        return _失败("资源不足",
                     f"系统内存压力：当前占用 {快照['占用率']}%，新连接预计 +{预计/1024**3:.1f}GB "
                     f"将达 {新占用率*100:.0f}%（安全阈值 {阈值*100:.0f}%），拒绝启动新模型以防撑爆内存。"
                     f"请释放不用的模型连接（{快照['说明']}）")
    return None


def _分配端口(端口: int | None) -> int:
    if isinstance(端口, int) and 端口 > 0:
        return 端口
    import socket
    with socket.socket() as 套接字:
        套接字.bind(("127.0.0.1", 0))
        return int(套接字.getsockname()[1])


def _计算模型大小(模型路径: str) -> int:
    """计算模型文件总大小，供内存守卫使用；目录读取失败时返回 0。"""
    from pathlib import Path
    try:
        if os.path.isfile(模型路径):
            return os.path.getsize(模型路径)
        return sum(文件.stat().st_size for 文件 in Path(模型路径).rglob("*") if 文件.is_file())
    except OSError:
        return 0


def _构建本地启动命令(模型路径: str, 模型类型: str, 启动器: str, 端口: int, 参数: dict) -> list[str]:
    from pathlib import Path
    格式, 规范路径 = _识别模型源(模型路径)
    if 格式 == "HuggingFace":
        import sys
        服务脚本 = Path(__file__).resolve().parents[5] / "支持库" / "适配层" / "模型服务.py"
        if not 服务脚本.is_file():
            raise FileNotFoundError(f"底座内部模型加载器不存在: {服务脚本}")
        return [sys.executable, str(服务脚本), "--model-path", 规范路径, "--model-type", 模型类型, "--port", str(端口)]
    if 格式 != "GGUF":
        raise ValueError("底座不支持该模型源；本地模型应为 GGUF 文件或含 config.json 的权重目录")
    # 候选顺序唯一实现在 `_解析启动器二进制`（latest 优先，理由见该函数），
    # 供应链校验与真实启动共用它 —— 校验的与执行的是同一个二进制。
    二进制 = _解析启动器二进制(启动器)
    if not 二进制:
        raise FileNotFoundError("未找到 llama-server；请配置 LLAMA_CPP_SERVER_BIN")
    # 2026-09-17 修复（P0·阻塞生产）：「上下文长度」参数原来收了不用 —— 启动命令里
    # -c 是硬编码 8192。实测后果：直播逐字稿精校的裁决窗口输入（证据包 + 提示词 +
    # 底稿，实测单个窗口底稿 2400+ 字符）远超 8192 tokens，llama-server 直接回
    # 500 `Context size has been exceeded.`，而调用方只看到
    # 「模型调用失败: 模型 HTTP 返回 500」—— 极易误判成提示词或模型能力问题
    # （实测绕了两轮：先怀疑思考模式、再怀疑参数没透传）。
    # 现在按调用方给的 上下文长度 启动；未给或非法则保持原默认 8192（行为不变）。
    _上下文 = 参数.get("上下文长度")
    if isinstance(_上下文, bool) or not isinstance(_上下文, (int, str)):
        _上下文 = 8192
    else:
        try:
            _上下文 = int(_上下文)
        except (TypeError, ValueError):
            _上下文 = 8192
    if _上下文 <= 0:
        _上下文 = 8192
    命令 = [二进制, "-m", 模型路径, "--port", str(端口), "--sleep-idle-seconds", "300",
            "-c", str(_上下文), "-ngl", "99"]
    if 模型类型 == "向量":
        命令.extend(["--pooling", "cls", "--embeddings"])
    elif 模型类型 == "重排":
        命令.append("--rerank")
    额外参数 = 参数.get("启动参数列表")
    if isinstance(额外参数, list):
        命令.extend(str(值) for 值 in 额外参数)
    return 命令


def _启动日志路径(模型路径: str) -> str:
    """本地模型启动日志路径：工程缓存/模型日志/<模型名>.log。

    2026-09-16 实测背景：原来把 stdout/stderr 丢 DEVNULL，模型启动即退出时
    任务只能空转健康检查（上限 900 秒）后报一句「健康检查超时」，
    没有任何可用线索，必须人工用同款命令复现才拿得到日志。
    """
    from pathlib import Path
    from 公共契约.运行时.运行缓存 import 解析运行缓存根
    名字 = Path(模型路径).stem or "本地模型"
    # 2026-09-17 实测修复：原来直接拼 `<系统根>/工程缓存/模型日志`，制品态就是往不可变
    # 制品里写运行态（发布门禁「制品.摘要绑定」实测由绿转红，落点
    # `<制品>/平台客户端/工程缓存/模型日志/验证模型.log`）。改经唯一解析器：源码态仍是
    # `<系统根>/工程缓存/模型日志`（行为不变），制品态改道平台受管缓存。
    目录 = 解析运行缓存根(Path(__file__).resolve().parents[5]) / "模型日志"
    try:
        目录.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return str(目录 / f"{名字}.log")


def _读启动日志尾部(模型路径: str, 行数: int = 12) -> str:
    """读启动日志尾部，供启动失败时随错误说明一并返回。"""
    try:
        with open(_启动日志路径(模型路径), "rb") as 文件:
            文件.seek(0, 2)
            大小 = 文件.tell()
            文件.seek(max(0, 大小 - 8192))
            文本 = 文件.read().decode("utf-8", "ignore")
        有效行 = [行.strip() for 行 in 文本.splitlines() if 行.strip()]
        if not 有效行:
            return ""
        return " | ".join(有效行[-行数:])[:1200]
    except OSError:
        return ""


def _等待本地健康(端口: int, 超时秒: int) -> bool:
    import urllib.request
    网址 = f"http://127.0.0.1:{端口}/v1/models"
    # 必须绕开系统代理探测：本函数在任务子进程（fork 出来）里 **循环** 调用，
    # 而 macOS 的 urllib 默认经 _scproxy 读系统代理（_scproxy → SCDynamicStoreCopyProxies
    # → CFPreferences），该路径在「fork 子进程 + 多线程」下非线程安全 ——
    # 实测段错误 SIGSEGV（栈顶 _os_log_preferences_refresh），整场任务崩溃退出 -11。
    # 本机模型端点本就不该走代理，ProxyHandler({}) 语义等价。
    开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    截止时间 = time.monotonic() + min(max(10, 超时秒), 900)
    while time.monotonic() < 截止时间:
        try:
            with 开放器.open(网址, timeout=3) as 响应:
                if 200 <= 响应.status < 300:
                    return 真
        except Exception as 错误:
            降级记录表.append(str(错误))
        time.sleep(0.5)
    return 假
