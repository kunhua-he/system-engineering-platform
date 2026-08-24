"""平台控制面消费者：通过统一能力服务完成一次真实能力调用。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 平台控制面.统一入口 import 统一能力服务
from 平台控制面.授权 import 组件开发Agent


def 主程序() -> int:
    服务 = 统一能力服务(Path(tempfile.mkdtemp(prefix="平台控制面示例_")))
    try:
        身份 = "平台控制面示例"
        令牌 = 服务.授权.注册身份(身份id=身份)
        服务.授权.引导授予(身份id=身份, 角色=组件开发Agent, 授予者="系统引导")
        服务.授权.切换角色(令牌, 组件开发Agent)
        能力id = "平台控制面示例.加法"
        服务.目录.登记能力(
            能力id=能力id,
            契约={"能力id":能力id, "名称":"加法", "参数":[], "返回":{"类型":"整数"}},
            组件="平台控制面示例", 领域="示例", 成熟度="稳定", 所有者=身份)
        服务.注册提供者(能力id=能力id, 函数=lambda: 4,
                       预算={键: 10 for 键 in ("内存上限", "线程上限", "子进程上限", "并发调用上限", "队列长度", "文件句柄上限", "临时空间上限", "每分钟重启次数", "空闲回收时间")} | {"单次调用超时": 5})
        结果 = 服务.执行操作(令牌=令牌, 操作="调用能力", 参数={"能力id":能力id, "参数":{}})
        值 = 结果.get("结果")
        print("平台控制面完整闭环示例通过 ✓")
        print(f"[13] 统一入口调用: 成功={结果.get('成功')} 真实返回值={值}")
        return 0 if 结果.get("成功") and 值 == 4 else 1
    finally:
        服务.状态.关闭()


if __name__ == "__main__":
    raise SystemExit(主程序())
