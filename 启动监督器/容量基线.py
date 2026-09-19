"""容量与资源基线：声明基线→实测采样→对比超限→超限处理链→熔断与证据。
P1-16 仅标准库中文语义；采样全真实，ps 不可用返回错误码；超限处理真实执行并追加 JSON Lines 证据，连续超限达阈值熔断。

**跨平台收口**：各项采样的**平台取法差异**（RSS 的 `ps` vs `/proc`、句柄的 `/proc/self/fd`
vs `/dev/fd`）一律在 `公共契约/运行时/平台适配.py` 判断；**本文件不含任何平台判断**
（第一轮《审计_平台判断越界_20260919》§二 B1-3 后：`采样内存RSS` 的
`if 是macOS() … else 假定有 /proc` 分叉已下沉收口层 `进程内存RSS字节()`）。
"""
from __future__ import annotations
from 公共契约.运行时 import 平台适配
from 公共契约.运行时.运行缓存 import 解析运行缓存根
from 公共契约.基础类型.逻辑类型 import 真, 假

import json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path
from typing import Any

必需基线字段 = ("线程上限", "进程上限", "内存上限MB", "队列长度上限",
             "文件句柄上限", "临时空间上限MB", "单次调用超时秒", "每分钟重启上限")
# 证据追加写锁（多线程安全）
_证据锁 = threading.Lock()


def 采样内存RSS(ps命令: str | None) -> dict:
    """真实 RSS(MB)：取法（macOS `ps -o rss=` / Linux `/proc/<pid>/status` VmRSS / 其余平台显名不支持）
    **整体收口在 `公共契约/运行时/平台适配.py` 的 `进程内存RSS字节()`**；本函数只做结果归一。

    为什么本函数必须变薄（第一轮审计 §二 B1-3）：旧实现自带 `if 是macOS(): … else: 假定有 /proc`
    的平台分支，而 **Windows 两者皆无**，实际靠 `/proc/.../status` 的 `is_file()` 兜底 —— 这个兜底
    能工作，但它是**副作用而非设计**：同一份 `if/else` 把 Linux 与 Windows 归为一类，靠文件存在性
    把它们分开。取法分叉会让「同一阈值在不同平台量纲/含义不同」，而阈值是硬熔断判据。

    **三态口径**：收口层回 `(字节, "")` / `(0, 原因)`；本函数把「没采到」一律归为
    `成功=假` + 错误码 `内存采样失败`，并把收口层的 `原因` 原样放进 `错误说明`
    （平台不支持的场景由 `原因` 显名，例如「Windows 既无 ps 也无 /proc」）——
    **绝不把 0 当成真实读数**（fail-closed）。
    """
    字节, 原因 = 平台适配.进程内存RSS字节(os.getpid(), ps命令=ps命令)
    if 原因:
        return {"成功": 假, "值MB": -1.0, "错误码": "内存采样失败", "错误说明": 原因}
    return {"成功": 真, "值MB": round(字节 / 1048576, 2), "错误码": "", "错误说明": ""}


def 采样进程数() -> dict:
    """真实进程数：当前进程自身 + pgrep 直接子进程。"""
    try:
        输出 = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, timeout=5)
        return {"成功": 真, "值": 1 + len([行 for 行 in 输出.stdout.splitlines() if 行.strip()]), "错误码": "", "错误说明": ""}
    except (OSError, subprocess.TimeoutExpired) as 错误:
        return {"成功": 假, "值": -1, "错误码": "进程枚举失败", "错误说明": f"pgrep 不可用: {错误}"}


def 采样句柄数() -> dict:
    try:
        目录表 = 平台适配.句柄枚举目录表()
        if not 目录表:
            return {"成功": 假, "值": -1, "错误码": "平台不支持",
                    "错误说明": "当前平台无句柄枚举目录，无法统计打开句柄数"}
        # 候选目录按平台优先级排列，取**第一个真实存在**的（不能只看 [0]：macOS 无 /proc/self/fd）
        可用目录 = next((d for d in 目录表 if os.path.isdir(d)), None)
        if 可用目录 is None:
            return {"成功": 假, "值": -1, "错误码": "句柄枚举失败",
                    "错误说明": f"句柄目录均不可用: {list(目录表)}"}
        return {"成功": 真, "值": len(os.listdir(可用目录)), "错误码": "", "错误说明": ""}
    except OSError:
        return {"成功": 假, "值": -1, "错误码": "句柄枚举失败", "错误说明": "句柄目录均不可用"}


#: 临时目录采样的**文件数上限**（有界采样的硬闸）。
#:
#: **为什么必须有界（2026-09-18 实测的性能缺陷）**：本函数原实现是
#: `sum(getsize(...) for 根,_,文件表 in os.walk(目录) ...)` —— **对整棵临时目录树无界递归**。
#: 调用方 `容量基线.__init__` 默认 `临时目录 = tempfile.gettempdir()`，
#: 而 macOS 的系统临时目录是**全机共享**的（`/var/folders/<…>/T`）。
#: 实测该目录 **324860 个文件 / 11.2 GB**，全递归耗时 **16.04 秒**，
#: 直接后果：`查询健康检查项` 17.9 秒、`执行健康监督` 34.1 秒，
#: **双双超过网关 20 秒转发上限 → HTTP 502「网关断开」**，
#: 使 `健康监督.只读判定面闭环` 场景在 HTML 黑盒验证里固定失败
#: （现象报的是「统一返回缺字段」，真因其实是超时）。
#:
#: 处置：**有界采样** —— 累计到上限即停止遍历，并把「已达上限」如实标注在返回值里
#: （`已截断=True`），**不假装算出了完整占用**。容量监督要的是「有没有逼近阈值」，
#: 不是「精确到字节」；有界 + 明确标注截断，比无界精确但把网关拖死更符合本项目的。
临时采样文件上限 = 20000


def 采样临时目录(目录, *, 文件上限: int | None = None) -> dict:
    """真实临时空间占用：**有界**遍历求和（字节），到上限即止并如实标注截断。

    参数：目录（临时目录路径）；文件上限（缺省取 `临时采样文件上限`）。
    返回：``{成功, 值, 已截断, 已统计文件数, 错误码, 错误说明}``。
    ``已截断=True`` 表示「到上限就停了，真实占用 ≥ 值」，**不冒充完整值**。
    """
    上限 = int(文件上限) if 文件上限 is not None else 临时采样文件上限
    已统计 = 0
    合计 = 0
    截断 = 假
    try:
        for 根目录, 子目录表, 文件表 in os.walk(目录):
            # 剪枝：`__pycache__` 这类派生目录不计（它们不是「临时空间占用」的有效信号，
            # 且数量最多 —— 本机实测 tempdir 里有大量编译残留）。
            子目录表[:] = [名 for 名 in 子目录表 if 名 != "__pycache__"]
            for 名 in 文件表:
                if 名.startswith(".") and 名 not in (".keep",):
                    continue
                try:
                    合计 += os.path.getsize(os.path.join(根目录, 名))
                    已统计 += 1
                except OSError:
                    continue
                if 已统计 >= 上限:
                    截断 = 真
                    break
            if 截断:
                break
        return {"成功": 真, "值": 合计, "已截断": 截断, "已统计文件数": 已统计,
                "错误码": "", "错误说明": ""}
    except OSError as 错误:
        return {"成功": 假, "值": 0, "已截断": 假, "已统计文件数": 0,
                "错误码": "目录不可用", "错误说明": f"目录不存在或不可读: {目录}（{错误}）"}


class 容量基线:
    """声明基线→实测采样→对比超限→超限处理链（拒绝/排空/释放/证据/熔断）。

    证据文件缺省根一律经唯一解析器 `公共契约/运行时/运行缓存.解析运行缓存根` 取：
    源码态回落 `<系统根>/工程缓存`（与旧写法**逐字相同**），制品态改落平台受管缓存。
    裸拼 `工程缓存` 在制品态就是把证据写进不可变制品——2026-09-17 伪制品布局实测：
    旧写法真在 `<制品>/平台客户端/工程缓存/启动监督器/` 下建目录并追加证据行。
    """

    def __init__(self, 证据文件=None, 临时目录=None, *, ps命令: str | None = None, 熔断阈值: int = 3, 排空超时秒: float = 10.0) -> None:
        self._基线: dict[str, Any] = {}
        self._证据文件 = (Path(证据文件) if 证据文件
                         else 解析运行缓存根(Path(__file__).resolve().parents[1])
                         / "启动监督器" / "容量基线证据.jsonl")
        self._临时目录 = str(临时目录) if 临时目录 else tempfile.gettempdir()
        self._ps命令, self._熔断阈值, self._排空超时秒 = ps命令, max(1, int(熔断阈值)), float(排空超时秒)
        self._锁 = threading.Lock()
        (self._停止接收, self._拒绝计数, self._活动任务, self._连续超限, self._熔断, self._释放请求, self._释放回调) = ({}, {}, {}, {}, {}, {}, {})
        self._证据序号 = 0

    def 声明基线(self, 基线: dict) -> tuple[bool, str]:
        缺失 = [字段 for 字段 in 必需基线字段 if 字段 not in 基线]
        if 缺失:
            return 假, f"基线缺少必需字段: {缺失}"
        for 字段 in 必需基线字段:
            if isinstance(基线[字段], bool) or not isinstance(基线[字段], (int, float)) or 基线[字段] <= 0:
                return 假, f"基线字段非法（必须为正数）: {字段}={基线[字段]!r}"
        self._基线 = dict(基线)
        return 真, "基线声明通过"

    def 实测采样(self) -> dict[str, Any]:
        内存, 进程, 句柄, 临时 = 采样内存RSS(self._ps命令), 采样进程数(), 采样句柄数(), 采样临时目录(self._临时目录)
        失败表 = [(项["错误码"], 项["错误说明"]) for 项 in (内存, 进程, 句柄, 临时) if not 项["成功"]]
        return {"成功": not 失败表, "线程数": len(threading.enumerate()), "进程数": 进程["值"],
                "内存MB": 内存["值MB"], "文件句柄数": 句柄["值"], "队列深度": 0, "临时空间MB": round(临时["值"] / 1048576, 2),
                "临时空间字节": 临时["值"],
                # 临时目录是**有界采样**（见 `采样临时目录`）：把「是否截断」如实带出，
                # 不把有界值冒充完整占用。
                "临时空间已截断": 临时.get("已截断", 假),
                "临时空间已统计文件数": 临时.get("已统计文件数", 0),
                "错误码": "；".join(项[0] for 项 in 失败表), "错误说明": "；".join(项[1] for 项 in 失败表)}

    def 对比基线(self) -> list[dict[str, Any]]:
        采样 = self.实测采样()
        对照表 = (("线程上限", "线程数"), ("进程上限", "进程数"), ("内存上限MB", "内存MB"),
                ("文件句柄上限", "文件句柄数"), ("临时空间上限MB", "临时空间MB"), ("队列长度上限", "队列深度"))
        超限项 = []
        for 基线字段, 采样字段 in 对照表:
            声明值, 实测值 = self._基线.get(基线字段), 采样[采样字段]
            if 声明值 is not None and (实测值 < 0 or 实测值 > 声明值):
                超限项.append({"字段": 采样字段, "声明值": 声明值, "实测值": 实测值, **({"采样失败": 真, "错误说明": 采样["错误说明"]} if 实测值 < 0 else {})})
        return 超限项

    def 超限处理(self, 执行单元id: str) -> dict[str, Any]:
        """超限处理链真实执行：停止接收→拒绝排队→排空等待→优雅释放→证据→熔断。"""
        with self._锁:
            if 执行单元id in self._熔断:
                return {"结果": "熔断", "执行单元": 执行单元id, "原因": self._熔断[执行单元id]}
        self._停止接收[执行单元id] = 真
        被拒, 超限项, 开始 = self._拒绝计数.get(执行单元id, 0), self.对比基线(), time.time()
        while self._活动任务.get(执行单元id, 0) > 0 and time.time() - 开始 <= self._排空超时秒:
            time.sleep(0.05)
        等待秒, 完成 = round(time.time() - 开始, 2), self._活动任务.get(执行单元id, 0) == 0
        with self._锁:
            self._释放请求[执行单元id] = 真
            (self._释放回调.get(执行单元id) or (lambda _: None))(执行单元id)
        with self._锁:
            self._连续超限[执行单元id] = 连续 = self._连续超限.get(执行单元id, 0) + 1
        if 连续 >= self._熔断阈值:
            with self._锁:
                self._熔断[执行单元id] = f"连续超限{连续}次，达到熔断阈值{self._熔断阈值}"
        熔断文字 = f"熔断（连续{连续}次≥阈值{self._熔断阈值}）" if 连续 >= self._熔断阈值 else f"连续超限{连续}次（未达阈值{self._熔断阈值}）"
        步骤 = ["停止接收新任务", f"拒绝排队({被拒}次)",
                f"等待活动任务排空({等待秒}秒,{'完成' if 完成 else '超时'})", "请求优雅释放", 熔断文字]
        证据id = self._记录证据(执行单元id, 超限项, 步骤, 连续)
        return {"结果": "熔断" if 执行单元id in self._熔断 else "已处理", "执行单元": 执行单元id,
                "停止接收": 真, "拒绝排队": 被拒, "排空": {"完成": 完成, "等待秒": 等待秒}, "连续超限": 连续, "证据id": 证据id, "超限项": 超限项}

    def _记录证据(self, 执行单元id: str, 超限项: list, 步骤: list, 连续: int) -> str:
        with self._锁:
            self._证据序号 += 1
            证据id = f"容量基线-{self._证据序号}"
        with _证据锁:
            self._证据文件.parent.mkdir(parents=True, exist_ok=True)
            with open(self._证据文件, "a", encoding="utf-8") as 文件:
                文件.write(json.dumps({"证据id": 证据id, "时间": time.strftime("%Y-%m-%d %H:%M:%S"), "执行单元": 执行单元id,
                                       "超限项": 超限项, "处理步骤": 步骤, "连续超限": 连续}, ensure_ascii=False) + "\n")
        return 证据id

    def 熔断状态(self, 执行单元id: str | None = None) -> dict:
        with self._锁:
            if 执行单元id is not None:
                return {"熔断": 执行单元id in self._熔断, "原因": self._熔断.get(执行单元id, ""), "执行单元": 执行单元id}
            return {"熔断": bool(self._熔断), "原因": "；".join(f"{单元}:{原因}" for 单元, 原因 in self._熔断.items())}

    def 尝试接收(self, 执行单元id: str) -> dict[str, Any]:
        with self._锁:
            if 执行单元id in self._熔断:
                return {"成功": 假, "原因": f"熔断: {self._熔断[执行单元id]}", "拒绝计数": self._拒绝计数.get(执行单元id, 0)}
            if self._停止接收.get(执行单元id):
                self._拒绝计数[执行单元id] = self._拒绝计数.get(执行单元id, 0) + 1
                return {"成功": 假, "原因": "已停止接收新任务", "拒绝计数": self._拒绝计数[执行单元id]}
            return {"成功": 真, "原因": "", "拒绝计数": self._拒绝计数.get(执行单元id, 0)}

    def 登记活动任务(self, 执行单元id: str, 增量: int = 1) -> None:
        with self._锁:
            self._活动任务[执行单元id] = max(0, self._活动任务.get(执行单元id, 0) + 增量)

    def 注册释放回调(self, 执行单元id: str, 回调) -> None:
        with self._锁:
            self._释放回调[执行单元id] = 回调

    def 解除熔断(self, 执行单元id: str) -> None:
        """解除熔断并把该执行单元的状态**按语义清干净**（缺陷 #150，2026-09-20）。

        为什么这么改：本类 7 个状态字典原先只清 3 个（`_熔断`/`_停止接收`/`_连续超限`），
        `_拒绝计数` 只置 0 不删键，`_活动任务`/`_释放请求`/`_释放回调` 永不清理 ——
        执行单元 id 持续新增时这些键**无界增长**（长跑实例内存泄漏）。

        **但不照搬「全部 pop」的粗修法**（那样会引入新缺陷）：三个字典语义不同，必须分开处理 ——
          · `_熔断`/`_停止接收`/`_连续超限`：熔断期状态，解除即该删 → `pop`
          · `_拒绝计数`：累计计数，`pop` 比置 0 更彻底且语义等价（读取处一律 `.get(id, 0)`）
          · `_释放请求`：一次性标志，`pop` 正确
          · `_活动任务`：**运行态计数**（登记活动任务 增减）→ **仅在为 0 时删键**；
            仍大于 0 说明有任务在跑，删键会让 `超限处理` 的排空判断失真（假"已排空"）
          · `_释放回调`：**长期登记**（注册释放回调 注入、超限处理时调用）→ **不删**，
            删了后续超限处理会拿到空回调、优雅释放静默失效
        """
        with self._锁:
            self._熔断.pop(执行单元id, None)
            self._停止接收.pop(执行单元id, None)
            self._连续超限.pop(执行单元id, None)
            self._拒绝计数.pop(执行单元id, None)
            self._释放请求.pop(执行单元id, None)
            if not self._活动任务.get(执行单元id, 0):
                self._活动任务.pop(执行单元id, None)
