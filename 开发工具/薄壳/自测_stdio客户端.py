"""薄壳 stdio 自测客户端（只调薄壳自己）：initialize → tools/list → tools/call。

不经端口、不启 HTTP：用 MCP SDK 的 stdio 客户端把薄壳作为子进程拉起。
凭证从父进程环境变量继承（「系统库网关凭证」），本脚本只打印网关 HTTP 状态码与返回片段，
不打印任何凭证内容。

跑法：unset PYTHONPATH; PYTHONDONTWRITEBYTECODE=1 python3.14 开发工具/薄壳/自测_stdio客户端.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_薄壳目录 = Path(__file__).resolve().parent
_项目根 = _薄壳目录.parents[1]
技能夹具 = _项目根 / "技能库" / "后端" / "技能库" / "验证夹具" / "技能工作区"


def _截断(文本: str, 上限: int = 300) -> str:
    return 文本 if len(文本) <= 上限 else 文本[:上限] + f"…(截断，共 {len(文本)} 字)"


async def 主程序() -> int:
    if str(_项目根) not in sys.path:
        sys.path.insert(0, str(_项目根))
    from 支持库.适配层.MCP协议提供者 import (
        构造客户端会话, 构造标准输入输出参数, 标准输入输出客户端,
    )

    参数 = 构造标准输入输出参数(
        命令=sys.executable,
        参数表=[str(_薄壳目录 / "薄壳服务.py")],
        环境=dict(os.environ),
        工作目录=str(_项目根),
    )
    async with 标准输入输出客户端(参数) as (读取流, 写入流):
        async with 构造客户端会话(读取流, 写入流) as 会话:
            初始化 = await 会话.initialize()
            print("[1] initialize 成功:", 初始化.serverInfo.name, 初始化.serverInfo.version)

            工具 = await 会话.list_tools()
            协议名表 = [工具项.name for 工具项 in 工具.tools]
            print(f"[2] tools/list 工具数 = {len(工具.tools)}；协议名 = {协议名表}")
            for 工具项 in 工具.tools:
                print(f"    - {工具项.name} | {工具项.description.split('：')[0]} | 入参键 "
                      f"{list((工具项.inputSchema or {}).get('properties', {}))}")
            print("[2] 断言 工具数 == 3 :", len(工具.tools) == 3)

            调用表 = [
                ("工具目录", "tool_catalog", {}),
                ("调用能力", "capability_call",
                 {"能力id": "技能库.技能索引.扫描技能包", "参数": {"技能根目录": str(技能夹具)},
                  "项目根": str(_项目根)}),
                ("查询能力", "capability_search", {"关键词": "读取文件", "限制": 5,
                                              "项目根": str(_项目根)}),
                # 网关操作转发（2026-09-21 补）：热接入 = 新增/变更包增量装配免重启
                # （决策记录 0008：**不重启网关**）。此前薄壳把 操作 写死成 调用能力，
                # 这两条只能回终端跑 launchctl/curl；现在一次调用即得，自测必须覆盖。
                ("热接入", "capability_call", {"操作": "热接入", "项目根": str(_项目根)}),
                ("健康检查", "capability_call", {"操作": "健康检查", "项目根": str(_项目根)}),
            ]
            失败表: list[str] = []
            for 序号, (中文名, 协议名, 入参) in enumerate(调用表, start=3):
                结果 = await 会话.call_tool(协议名, dict(入参))
                正文 = 结果.content[0].text if 结果.content else ""
                数据 = json.loads(正文) if 正文.strip().startswith("{") else {}
                print(f"[{序号}] {中文名}({协议名}) → 成功={数据.get('成功')} "
                      f"HTTP状态码={数据.get('HTTP状态码')} 错误码={数据.get('错误码')}")
                print(f"    正文片段: {_截断(json.dumps(数据, ensure_ascii=False))}")
                # 自测**必须给判据**：此前这四条只打印不断言，`项目根` 也没传，
                # 四条能力调用实际全被 fail-closed 拒掉却仍打印「自测完成」——
                # 门禁文档（AGENTS.md）写的「期望三条调用 成功=True」因此长期不成立。
                if not 数据.get("成功"):
                    失败表.append(f"{中文名}({协议名}) 成功={数据.get('成功')} "
                               f"错误码={数据.get('错误码')}")
            if 失败表:
                print(f"[自测失败] {len(失败表)}/{len(调用表)} 条调用未成功：" + "；".join(失败表))
                return 1
            print(f"[自测通过] tools/list = {len(工具.tools)}，{len(调用表)} 条调用全部成功=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(主程序()))
