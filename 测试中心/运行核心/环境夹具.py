"""环境缓存测试公共夹具：**假 venv 模块**（经生产自带注入口注入，不 patch 被测本体）。

为什么需要它（`测试伪装门禁` 规则1「patch 被测对象本体」收口，2026-09-23）：
`运行核心/运行环境管理器/环境管理器.py:692` 有一处**生产自带注入口**——
`if venv is not _标准venv模块:` 时改走 `venv.create(临时目录, with_pip=True)`，
注释写明「兼容显式注入的环境创建器」。此前多份环境缓存测试用
`mock.patch("…环境管理器.校验环境")` / `…环境管理器._构建环境` / `…环境管理器.venv`
把被测逻辑整段换掉 —— 那是「patch 被测对象本体」（P1），断言对象变成夹具：
`_构建环境` 的阶段推进、pip 安装子进程、`校验环境` 的真判定、`原子落盘` 全都没跑。

本夹具只换**第三方边界**（stdlib `venv`）：注入后 `_构建环境` 与 `校验环境` 的
**真实实现照跑** —— 假 `create()` 落一个「真能被执行、退出码可控」的解释器骨架，
于是 `pip install` 与 `import` 校验都真实走一遍子进程，落盘也走真实 `原子落盘`。
夹具只负责「造出真实状态的产物」，不替换任何被测函数。

发现口径：本文件**不以 `测试_` 开头**，故不被 `测试体系门禁` 的测试发现器收集
（`开发工具/测试体系门禁实现/发现.py` 只认 `测试_*.py`；同
`测试中心/运行核心/冷启动脚本.py` 的先例）。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from 公共契约.运行时 import 平台适配

#: 假解释器脚本：`成功=真` 退出码 0（pip/import 子进程一律“成功”），
#: `成功=假` 退出码 1（真实触发 `校验环境` 的失败分支）。
成功脚本 = "#!/bin/sh\nexit 0\n"
失败脚本 = "#!/bin/sh\nexit 1\n"


def 写解释器骨架(环境目录: Path | str, *, 成功: bool = True) -> Path:
    """在 `环境目录` 下落一个**可执行**的解释器骨架，返回其路径。

    路径走生产同一口径 `平台适配.虚拟环境解释器路径`（POSIX 与 Windows 目录名不同）。
    必须 `chmod 0o755`：真实 `_构建环境` 会把它当可执行文件起子进程，
    不可执行会 `PermissionError`（旧写法把 `_构建环境` 整段换掉，从没碰到这一层）。
    """
    解释器 = 平台适配.虚拟环境解释器路径(Path(环境目录))
    解释器.parent.mkdir(parents=True, exist_ok=True)
    解释器.write_text(成功脚本 if 成功 else 失败脚本, encoding="utf-8")
    解释器.chmod(0o755)
    return 解释器


class 假venv模块:
    """替身 stdlib `venv`：`create()` 落一个真能执行的解释器骨架（+ 可选耗时）。

    `调用次数` 是**从第三方边界实测**的构建次数（真 `_构建环境` 每构建一次调一次），
    比旧写法在夹具里自增的计数器更硬：它由被测代码的真实调用产生。
    """

    def __init__(self, *, 耗时秒: float = 0.0, 成功: bool = True,
                 抛错: Exception | None = None):
        self.耗时秒 = 耗时秒
        self.成功 = 成功
        self.抛错 = 抛错
        self.调用次数 = 0

    def create(self, 环境目录, with_pip: bool = False, **_其余):
        self.调用次数 += 1
        if self.耗时秒:
            time.sleep(self.耗时秒)
        if self.抛错 is not None:
            raise self.抛错
        return 写解释器骨架(环境目录, 成功=self.成功)


@contextmanager
def 注入假venv(*, 耗时秒: float = 0.0, 成功: bool = True,
               抛错: Exception | None = None):
    """经生产自带注入口注入假 venv；退出即还原真实 stdlib `venv`。

    用法（替换旧的 `mock.patch("…环境管理器.venv", …)` /
    `mock.patch("…环境管理器._构建环境", …)` / `mock.patch("…环境管理器.校验环境", …)`）::

        with 注入假venv(耗时秒=0.4) as 假venv:
            结果 = 确保环境(提供者)
        self.assertEqual(假venv.调用次数, 1)   # 真实构建了一次
    """
    from 运行核心.运行环境管理器 import 环境管理器

    原venv = 环境管理器.venv
    假 = 假venv模块(耗时秒=耗时秒, 成功=成功, 抛错=抛错)
    环境管理器.venv = 假
    try:
        yield 假
    finally:
        环境管理器.venv = 原venv
