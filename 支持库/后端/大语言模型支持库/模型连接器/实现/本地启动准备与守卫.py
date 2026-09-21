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
    # 决策权重包：RL 权重目录的原生结构是 `encoder/config.json` + 顶层 `*.safetensors`
    # （子聚合器 + 句柄头不在顶层 config.json 里），与平铺 HF 目录判据不同。
    # 按**实体文件**识别，不看目录名 —— 目录叫什么都不影响判定。
    if 路径.is_dir() and (路径 / "encoder" / "config.json").is_file() and any(路径.glob("*.safetensors")):
        return "RLCheckpoint", str(路径)
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
        格式 = _供应链校验.校验模型目录(规范路径, 系统根=系统根) if 源格式 in ("HuggingFace", "RLCheckpoint") \
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
        else "重排" if 类型 in ("排序", "重排", "rerank") \
        else "决策" if 类型 in ("判断", "决策", "decision") else "LLM"
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
    """解析真实启动器二进制并校验；HuggingFace/RLCheckpoint 目录走底座内部加载器，不涉及启动器。"""
    if 源格式 in ("HuggingFace", "RLCheckpoint"):
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
    if 格式 in ("HuggingFace", "RLCheckpoint"):
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
    # 2026-09-19（G 路·本地模型进程空闲回收）：`--sleep-idle-seconds` 不再硬编码 300。
    # 硬编码 300 就是「第二个定义点」——5 分钟这个数只能有一处：本支持库
    # `包声明.json` 的「句柄超时秒」。调用方把它经「进程空闲秒」参数带下来；
    # 调用方没给就不带该参数（不猜、不另写默认值）。
    #
    # 更要紧的事实（2026-09-19 实测）：llama-server 的 `--sleep-idle-seconds`
    # **只卸权重、不退进程** —— 进程仍攥约 6.5GB wired 显存（`ps` 里 RSS 显示 0，
    # 极易漏看），这正是网关重启后遗留孤儿债的根因。
    # 让进程真正消失的是「本地模型看守」（见 `实现/模型连接器.py::运行本地模型看守`），
    # 本参数只作为它之外的第二道软释放，保留原有行为。
    命令 = [二进制, "-m", 模型路径, "--port", str(端口)]
    # `--metrics` 是「有人用」的活动判据来源：看守靠它取累计计数（实测 2026-09-19：
    # 空闲期间计数不动，一次真实请求后 `llamacpp:n_decode_total` 立刻 +1；
    # 而健康探活 /v1/models 不计数，所以探活不会把空闲进程「养活」）。
    命令.append("--metrics")
    _空闲秒 = 参数.get("进程空闲秒")
    if not isinstance(_空闲秒, bool) and isinstance(_空闲秒, int) and _空闲秒 > 0:
        命令.extend(["--sleep-idle-seconds", str(_空闲秒)])
    # ★ 物理批大小（2026-09-21 实测缺陷修复，与上一条同源）：`-c` 只管上下文总量，
    # 单次前向还受**物理批大小**限制，而它一直是 llama.cpp 默认值 512。
    # 实测后果：语义索引的代码块（770~927 tokens）被服务端直接拒收，原文
    # `E srv send_error: input (882 tokens) is too large to process.
    #  increase the physical batch size (current batch size: 512)`，
    # 而调用方只看到「模型调用失败: 模型 HTTP 返回 500」—— 与 2026-09-17
    # 那条 `Context size has been exceeded` 是同一类：参数没收全。
    # 口径：物理批默认取上下文长度（单次输入不可能超过上下文，这类 500 整类消除）；
    # 调用方可经 启动参数列表 的 --batch-size 自行覆盖。
    物理批 = 参数.get("物理批大小")
    if isinstance(物理批, bool) or not isinstance(物理批, (int, str)):
        物理批 = _上下文
    else:
        try:
            物理批 = int(物理批)
        except (TypeError, ValueError):
            物理批 = _上下文
    if 物理批 <= 0:
        物理批 = _上下文
    命令.extend(["-c", str(_上下文), "--batch-size", str(物理批), "-ngl", "99"])
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


# ── 本地模型看守（G 路：进程级自退的唯一实现）────────────────────
# 2026-09-19（华哥口径「拉起来之后，如果 5 分钟没人用，那就自动释放」）：
# 真正拉起本地模型的**不是** llama-server 本体，而是这里的一个独立看守进程；
# 看守再拉起 llama-server，并独占它的整个生命周期。于是无论调用方（网关）是还活着
# 还是已经被 SIGTERM / kill -9 干掉，看守都能自己走到点收工 —— 这就是「孤儿自退」的落点。
#
# 为什么必须有看守（2026-09-19 现场实测，不是推断）：
#   llama-server 自带的 `--sleep-idle-seconds` **只卸权重、不退进程**：进程仍攥约
#   6.5GB wired 显存（`ps` 里 RSS 显示 0，极易漏看）。平台上没有任何一个 native 进程
#   会因为「没人用」自己消失，所以「5 分钟没人用就释放」只能由一个我们自己拥有的看守执行。

默认本地进程空闲秒 = 300          # 代码侧唯一兜底值；唯一真源见 本地进程空闲秒()
#: 就绪等待上限秒：启动期口径（加载权重的时间），与「空闲」不是一回事。
#: 原实现把就绪等待也取「有效超时」（900 秒封顶），本轮把空闲阈值下调到 300 秒后
#: 会把大模型冷启动容差一起缩掉 —— 故独立成常量，互不牵连。
就绪等待秒 = 900
看守检查间隔上限秒 = 15.0
看守账本文件名 = "本地模型看守账本.json"
_看守计数键 = ("llamacpp:n_decode_total", "llamacpp:prompt_tokens_total",
               "llamacpp:tokens_predicted_total", "llamacpp:requests_processing")

#: 看守进程的启动包装：`-c` 一行导入入口，避免 `-m` 触发 runpy 双导入告警。
#: **必须把系统根写进代码**（2026-09-19 实测教训）：看守是一个全新解释器进程，
#: 父进程往 `sys.path` 里塞的路径**不会继承**。只靠 cwd 撞运气的话，
#: 网关换个工作目录启动就会「看守 import 失败 → 模型拉起后立刻没了」。
看守包装模板 = ("import sys; sys.path.insert(0, {根!r}); "
              "from 支持库.后端.大语言模型支持库.模型连接器.实现.本地启动准备与守卫 "
              "import 看守入口; raise SystemExit(看守入口(sys.argv[1:]))")


def 看守包装代码(系统根: str | Path) -> str:
    """生成看守启动代码，把平台根绝对路径写死进去（看守不继承父进程的 sys.path）。"""
    return 看守包装模板.format(根=str(系统根))


def 本地进程空闲秒() -> int:
    """「本地模型进程空闲秒」的唯一真源：本支持库 `包声明.json` 的 `句柄超时秒`。

    5 分钟这个数只允许有一个定义点，就是本支持库（聚合包）包声明的 `句柄超时秒`；
    本函数是全仓唯一读取点，代码侧只有一处兜底常量（`默认本地进程空闲秒`）。
    启动命令、连接器、看守全部从本函数取值 —— 谁也不许再写一份 300
    （改了包声明一处，三处行为一起变，这就是「阈值来源唯一」的可验证形状）。

    与 `模型连接器.包申报超时()`（读**子包** `模型连接器/包声明.json`）不是同一轴：
    那个是云端连接/会话存储句柄的默认租约，本函数是本地模型**进程**的空闲口径。
    """
    try:
        import json
        声明路径 = Path(__file__).resolve().parents[2] / "包声明.json"
        with open(声明路径, encoding="utf-8") as 文件:
            申报 = json.load(文件).get("句柄超时秒")
        if isinstance(申报, int) and not isinstance(申报, bool) and 申报 > 0:
            return 申报
    except Exception as 错误:
        降级记录表.append(str(错误))
    return 默认本地进程空闲秒


def 看守账本路径(模型路径: str) -> str:
    """看守账本与模型启动日志同目录（`工程缓存/模型日志/`），便于一次取证取全。"""
    from pathlib import Path as _路径
    名字 = _路径(模型路径).stem or "本地模型"
    return str(_路径(_启动日志路径(模型路径)).with_name(f"{名字}.{看守账本文件名}"))


def _写看守账本(路径: str, 内容: dict) -> None:
    import json
    try:
        with open(路径, "w", encoding="utf-8") as 文件:
            json.dump(内容, 文件, ensure_ascii=False, indent=1)
    except OSError as 错误:
        降级记录表.append(f"看守账本写入失败: {错误}")


def 读取看守账本(模型路径: str) -> dict:
    import json
    try:
        with open(看守账本路径(模型路径), encoding="utf-8") as 文件:
            账本 = json.load(文件)
        return 账本 if isinstance(账本, dict) else {}
    except (OSError, ValueError):
        return {}


def _进程启动时刻(进程号: int) -> str:
    """取进程启动时刻（`ps -o lstart=`）；取不到返回空串（不猜测、不伪造）。"""
    if os.name == "nt":
        return ""
    import subprocess
    try:
        结果 = subprocess.run(["ps", "-o", "lstart=", "-p", str(进程号)],
                             capture_output=True, text=True, timeout=5)
        return 结果.stdout.strip() if 结果.returncode == 0 else ""
    except Exception as 错误:
        降级记录表.append(str(错误))
        return ""


def _进程命令行(进程号: int) -> str:
    """取进程命令行；取不到返回空串（判据宁可判「不符」也不放行）。"""
    if os.name == "nt":
        return ""
    import subprocess
    try:
        结果 = subprocess.run(["ps", "-o", "command=", "-p", str(进程号)],
                             capture_output=True, text=True, timeout=5)
        return 结果.stdout.strip() if 结果.returncode == 0 else ""
    except Exception as 错误:
        降级记录表.append(str(错误))
        return ""


def 回收看守残留(模型路径: str) -> dict:
    """按「归属 + 世代」回收看守遗留的模型进程；判据不成立一律不发信号。

    归谁所有、是哪一代，全部按证据判，**不按端口枚举、不按进程名盲杀** ——
    本机上存在合法的长驻 embedding 服务（PPID=1），按端口/名字杀会把它误杀。
    三项判据全中才动手：
      ① 账本记着模型进程号与端口；
      ② 该进程号仍存活，且启动时刻与账本逐字一致（**这就是「世代」**，防 PID 被复用）；
      ③ 该进程命令行里出现本代端口（**这就是「归属」**，防把别人的进程当成自己的）。
    """
    from 公共契约.运行时 import 进程终止
    账本 = 读取看守账本(模型路径)
    模型进程号 = 账本.get("模型进程号")
    if not isinstance(模型进程号, int) or isinstance(模型进程号, bool):
        return {"已回收": 假, "原因": "账本无模型进程号（不是本平台拉起的进程，不动手）"}
    if not 进程终止.进程存活(模型进程号):
        return {"已回收": 假, "原因": f"模型进程 {模型进程号} 已不存在"}
    启动时刻 = _进程启动时刻(模型进程号)
    账本时刻 = str(账本.get("启动时刻") or "")
    if 账本时刻 and 启动时刻 != 账本时刻:
        return {"已回收": 假,
                "原因": f"进程 {模型进程号} 启动时刻 {启动时刻!r} 与账本 {账本时刻!r} 不符"
                        "（世代不符，PID 可能已被复用），按归属纪律不动手"}
    端口 = str(账本.get("端口") or "")
    命令行 = _进程命令行(模型进程号)
    if 端口 and f"--port {端口}" not in 命令行 and f"--port={端口}" not in 命令行:
        return {"已回收": 假,
                "原因": f"进程 {模型进程号} 命令行不含本代端口 {端口}（归属不符），不动手"}
    进程终止.终止进程组(模型进程号, 信号="终止")
    消失 = 进程终止.等待进程消失(模型进程号, 超时秒=5.0)
    if not 消失:
        进程终止.终止进程组(模型进程号, 信号="强杀")
        消失 = 进程终止.等待进程消失(模型进程号, 超时秒=5.0)
    if 消失:
        _写看守账本(看守账本路径(模型路径), {**账本, "状态": "已回收"})
        return {"已回收": 真,
                "原因": f"归属与世代校验通过，已回收模型进程 {模型进程号}（端口 {端口}）"}
    降级记录表.append(f"看守残留回收失败：模型进程 {模型进程号} 强杀后仍在")
    return {"已回收": 假, "原因": f"模型进程 {模型进程号} 强杀后仍未消失"}


def _看守取样(端口: int) -> tuple[tuple[str, ...] | None, bool]:
    """取一次活动样本：返回（累计计数快照，是否有请求在处理）。

    计数快照取 `--metrics` 的**累计量**（prompt/n_decode/predicted/processing）。
    2026-09-19 实测：空闲 25 秒期间这些累计量**一个字节都不动**，而一次真实
    embedding 请求后 `llamacpp:n_decode_total` 立刻 +1 —— 所以「计数变 = 有人用」
    是可靠判据，且不会被健康探活（不计数）误判成「有人用」。
    """
    import json
    import urllib.request
    开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    快照: list[str] = []
    try:
        with 开放器.open(f"http://127.0.0.1:{端口}/metrics", timeout=3) as 响应:
            文本 = 响应.read().decode("utf-8", "ignore")
    except Exception as 错误:
        降级记录表.append(f"看守活动计数不可观测: {错误}")
        return None, 假
    for 行 in 文本.splitlines():
        if 行.startswith("#") or not 行.strip():
            continue
        段 = 行.split()
        if 段[0] in _看守计数键:
            快照.append(f"{段[0]}={段[-1]}")
    忙 = 假
    try:
        with 开放器.open(f"http://127.0.0.1:{端口}/slots", timeout=3) as 响应:
            忙 = any(bool(槽.get("is_processing"))
                     for 槽 in json.loads(响应.read().decode("utf-8", "ignore")))
    except Exception:
        忙 = 假
    快照.sort()
    return tuple(快照), 忙


def 运行本地模型看守(端口: int, 空闲秒: int, 命令: list[str], 日志路径: str,
                   世代: str, 模型路径: str = "") -> int:
    """看守主循环：拉起本地模型进程，空闲到期或模型自退即收工；退出前必收干净。

    退出路径有三条，行为一致（都保证模型进程不残留）：
      * 空闲到期（华哥口径的 5 分钟）；
      * 模型进程自己退出/崩溃（看守不该变成新的孤儿）；
      * 看守收到终止请求（调用方显式释放，或网关停机时随进程组一起收到 SIGTERM）。
    """
    import signal
    import subprocess
    from 公共契约.运行时 import 平台适配, 进程终止
    停止请求 = {"收到": 假}

    def 收信(信号号, 栈帧) -> None:  # noqa: ANN001
        停止请求["收到"] = 真

    for 信号号 in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(信号号, 收信)
        except (ValueError, OSError):
            pass
    账本 = 看守账本路径(模型路径) if 模型路径 else ""
    try:
        日志句柄 = open(日志路径, "ab", buffering=0) if 日志路径 else None
    except OSError:
        日志句柄 = None

    def 留痕(文本: str) -> None:
        if 日志句柄 is None:
            return
        try:
            日志句柄.write(f"[看守 {世代}] {文本}\n".encode("utf-8"))
        except OSError:
            pass

    进程 = None
    try:
        留痕(f"拉起模型进程：{' '.join(命令)}")
        进程 = subprocess.Popen(命令, **平台适配.子进程组启动标志(),
                               stdout=日志句柄, stderr=subprocess.STDOUT)
        if 账本:
            _写看守账本(账本, {"世代": 世代, "看守进程号": os.getpid(),
                              "模型进程号": 进程.pid, "模型进程组号": 进程.pid,
                              "端口": 端口, "空闲秒": 空闲秒, "模型路径": 模型路径,
                              "启动时刻": _进程启动时刻(进程.pid), "状态": "看守中"})
        留痕(f"模型进程 {进程.pid} 已拉起，等待就绪（端口 {端口}）")
        if not _等待本地健康(端口, 空闲秒):
            留痕("健康检查未通过，收工（启动日志即失败原因）")
            return 3
        留痕(f"就绪；空闲阈值 {空闲秒} 秒（真源：本支持库包声明 句柄超时秒）")
        间隔 = max(1.0, min(看守检查间隔上限秒, 空闲秒 / 5.0))
        最后活动 = time.monotonic()
        上次快照: tuple[str, ...] | None = None
        while not 停止请求["收到"]:
            if 进程.poll() is not None:
                留痕(f"模型进程已自行退出，退出码 {进程.returncode}")
                return 0
            快照, 忙 = _看守取样(端口)
            if 快照 is None:
                if 忙:
                    最后活动 = time.monotonic()
                    留痕("活动计数不可观测，回退 /slots 忙闲判定：有请求在处理")
            else:
                if 上次快照 is not None and 快照 != 上次快照:
                    最后活动 = time.monotonic()
                上次快照 = 快照
            空闲 = time.monotonic() - 最后活动
            if 空闲 >= 空闲秒:
                留痕(f"空闲 {空闲:.0f} 秒达到阈值 {空闲秒} 秒，回收模型进程")
                return 0
            time.sleep(间隔)
        留痕("收到终止请求，回收模型进程")
        return 0
    except Exception as 错误:
        留痕(f"看守异常：{type(错误).__name__}: {错误}")
        return 4
    finally:
        if 进程 is not None and 进程.poll() is None:
            留痕(f"收尾：终止模型进程 {进程.pid}")
            进程终止.终止进程组(进程.pid, 信号="终止")
            if not 进程终止.等待进程消失(进程.pid, 超时秒=5.0):
                进程终止.终止进程组(进程.pid, 信号="强杀")
                进程终止.等待进程消失(进程.pid, 超时秒=5.0)
            try:
                进程.wait(timeout=5)
            except Exception:
                pass
        留痕(f"看守退出；模型进程仍存活={进程 is not None and 进程.poll() is None}")
        if 账本:
            账本内容 = 读取看守账本(模型路径)
            账本内容.update({"状态": "已回收" if 进程 is not None and 进程.poll() is not None
                            else "已收工", "世代": 世代})
            _写看守账本(账本, 账本内容)
        if 日志句柄 is not None:
            try:
                日志句柄.close()
            except OSError:
                pass


def 看守入口(参数: list[str]) -> int:
    """看守进程入口：`--端口 N --空闲秒 N --日志路径 P --世代 G --模型路径 M -- <模型启动命令>`。"""
    选项: dict[str, str] = {}
    命令: list[str] = []
    游标 = 0
    while 游标 < len(参数):
        项 = 参数[游标]
        if 项 == "--":
            命令 = 参数[游标 + 1:]
            break
        if 项.startswith("--") and 游标 + 1 < len(参数):
            选项[项[2:]] = 参数[游标 + 1]
            游标 += 2
            continue
        命令.append(项)
        游标 += 1
    try:
        端口 = int(选项.get("端口", ""))
        空闲秒 = int(选项.get("空闲秒", ""))
    except (TypeError, ValueError):
        return 2
    if not 命令:
        return 2
    return 运行本地模型看守(端口, 空闲秒, 命令, 选项.get("日志路径", ""),
                          选项.get("世代", ""), 选项.get("模型路径", ""))
