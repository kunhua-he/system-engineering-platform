"""容错路径留痕：确实要忽略的异常必须留下证据（设计哲学第 15 条「失败要明确」）。

为什么需要它：`except Exception: pass` 会把真实故障一起吞掉（例如进程回收失败、连接关闭失败），
事后无法判断"本来就这样"还是"出过问题"。这里给全平台一个统一、**有界**、可查询的留痕点：

```python
from 公共契约.诊断.忽略记录 import 记录忽略

try:
    ...
except OSError as 错误:
    记录忽略("句柄体系.强制终止进程", 错误)   # 允许忽略，但必须留证
```

约定：
- 只记录**调用内尽力而为**的失败（清理、降级、兜底），不用于掩盖业务错误；
- 有界保留最近 200 条，避免热路径无限增长；
- `忽略快照()` 供诊断/健康检查读取。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

上限 = 200
最近忽略: deque[dict[str, Any]] = deque(maxlen=上限)


def 记录忽略(位置: str, 错误: BaseException | str) -> None:
    """记下一次性忽略的异常（位置 = 「模块.动作」，便于定位）。"""
    最近忽略.append({
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "位置": str(位置),
        "错误类型": type(错误).__name__ if isinstance(错误, BaseException) else "文本",
        "说明": str(错误)[:200],
    })


def 忽略快照() -> list[dict[str, Any]]:
    """返回最近忽略记录（最新在后）。"""
    return list(最近忽略)


def 忽略计数() -> int:
    return len(最近忽略)


__all__ = ["记录忽略", "忽略快照", "忽略计数", "最近忽略", "上限"]
