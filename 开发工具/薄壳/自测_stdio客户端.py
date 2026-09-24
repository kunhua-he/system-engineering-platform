"""薄壳 stdio 自测客户端（只调薄壳自己）：initialize → tools/list → tools/call。

不经端口、不启 HTTP：用 MCP SDK 的 stdio 客户端把薄壳作为子进程拉起。
凭证从父进程环境变量继承（「系统库网关凭证」），本脚本只打印薄壳回执与返回片段，
不打印任何凭证内容。

跑法：unset PYTHONPATH; PYTHONDONTWRITEBYTECODE=1 python3.14 -u 开发工具/薄壳/自测_stdio客户端.py

★★ 必须带 `-u`（2026-09-21 批 2 实测踩到）：stdout 不是 tty 时（重定向到文件 / 走管道）Python 用块缓冲，
脚本一旦异常退出**不 flush** ⇒ 全部 print 丢失、只看得到 stderr 的 traceback，
而外面 `sh -c "… | tail"` 的退出码是 `tail` 的 **0** ⇒ 现场是「无输出但退出码 0」的假绿。
带 `-u` 后输出实时落盘，真退出码用 `echo $?` 取（别拿管道的退出码当结论）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_薄壳目录 = Path(__file__).resolve().parent
_项目根 = _薄壳目录.parents[1]


def _截断(文本: str, 上限: int = 300) -> str:
    return 文本 if len(文本) <= 上限 else 文本[:上限] + f"…(截断，共 {len(文本)} 字)"


def _读判据(正文: str) -> tuple[bool, str]:
    """从薄壳**文本口径**回包里取判据：`(成功, 错误码)`。

    形状（2026-09-24 华哥裁决「成功返回 1，有返回的直接返回内容，失败返回 -1」）：
    首行 `1`（成功无值）／`-1`（失败）／正文（成功有值）；`错误码` 是其后的一行 `键：值`。
    本函数是自测侧**唯一读点** —— 回包不再是 JSON，`json.loads` 在此已不适用。
    """
    行表 = 正文.split("\n")
    成功 = bool(行表) and 行表[0] != "-1"
    for 行 in 行表[1:]:
        if 行.startswith("错误码："):
            return 成功, 行[len("错误码："):]
    return 成功, ""


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
            # 2026-09-24 补判据：`instructions`（类型表 + 常用动作）**必须真进回包**。
            # 此前它走 `构造服务(名称, 提示)`，而 SDK 只在 `create_initialization_options()`
            # 里取服务对象的 instructions —— 薄壳走自建 `InitializationOptions` ⇒ 实测长度 0，
            # 等于那 551 字符白写。同一件事两条注入腿必然有一条死腿，故此处钉死断言。
            指令 = getattr(初始化, "instructions", None) or ""
            print("[1] initialize 成功:", 初始化.serverInfo.name, 初始化.serverInfo.version,
                  f"｜instructions = {len(指令)} 字符"
                  f"｜capabilities = {sorted(初始化.capabilities.model_dump(exclude_none=True))}")
            print("[1] 断言 instructions 非空 :", bool(指令.strip()))

            工具 = await 会话.list_tools()
            协议名表 = [工具项.name for 工具项 in 工具.tools]
            print(f"[2] tools/list 工具数 = {len(工具.tools)}；协议名 = {协议名表}")
            for 工具项 in 工具.tools:
                print(f"    - {工具项.name} | {工具项.description.split('：')[0]} | 入参键 "
                      f"{list((工具项.inputSchema or {}).get('properties', {}))}")
            print("[2] 断言 工具数 == 4 :", len(工具.tools) == 4)

            # 4 条腿各一条（2026-09-25 定稿工具面）：① 查询能力／② 调用能力（位置数组）／
            # ③ 代码地图搜索（带代码块）／④ 终端运行（默认异步腿＋有界等待）。
            # `操作`／`意图`／`参数`／`值字段`／`看键`／`项目根` 已从工具面删除，
            # 顶层 schema 是 additionalProperties=false ⇒ 多带任何一个都会在 **schema 层**
            # 被 SDK 当场拒掉（回执为空、只看得到 isError=true）。
            调用表 = [
                ("查询能力", "capability_search", {"关键词": "读取文件", "限制": 3}),
                # ② 的入参是**位置数组**：按该能力契约的参数行序对位（空位留 ''）。
                # `能力目录.搜索能力` 的行序＝[关键词, 限制, 游标, 细节级别, 含常用参数]。
                ("调用能力", "capability_call",
                 {"能力id": "能力目录.搜索能力", "数组": ["读取文件", 3]}),
                ("代码地图搜索", "code_map_search", {"关键词": "构建工具目录", "最大条数": 1}),
                ("终端运行", "run_command", {"命令": "echo 自测", "是否异步": False}),
            ]
            失败表: list[str] = []
            if not 指令.strip():
                失败表.append("initialize 未下发 instructions（类型表与常用动作等于没写）")
            for 序号, (中文名, 协议名, 入参) in enumerate(调用表, start=3):
                结果 = await 会话.call_tool(协议名, dict(入参))
                正文 = 结果.content[0].text if 结果.content else ""
                成功, 错误码 = _读判据(正文)
                print(f"[{序号}] {中文名}({协议名}) → 成功={成功} "
                      f"错误码={错误码 or '无'} isError={结果.isError}")
                print(f"    正文片段: {_截断(正文)}")
                # 自测**必须给判据**：此前这四条只打印不断言，`项目根` 也没传，
                # 四条能力调用实际全被 fail-closed 拒掉却仍打印「自测完成」——
                # 门禁文档（AGENTS.md）写的「期望三条调用 成功=True」因此长期不成立。
                if not 成功:
                    失败表.append(f"{中文名}({协议名}) 成功={成功} 错误码={错误码}")
                # L10 判据（2026-09-21 批 2）：成功路径**不得**置 isError ——
                # 否则客户端会把正常返回当错误处理。
                if 成功 and 结果.isError:
                    失败表.append(f"{中文名}({协议名}) 成功=True 却 isError=True（语义不符）")
            # ★ L10 反向判据（批 2 新增，治「改了没人知道」）：故意发一条**必失败**的调用，
            # 断言 `isError=True`。此前薄壳只回 list[TextContent]，SDK 对「返回 list」的正常路径
            # 固定 isError=False ⇒ 业务失败在 MCP 链路上完全不可见（SEP-1303 要治的正是它）。
            # ⚠️ 样本必须选**过得了 inputSchema、但在业务层失败**的那种：用 `操作="重启网关"`
            # 不行 —— L9 的 enum + additionalProperties 会让它在 **schema 层**就被 SDK 拒掉
            # （`_make_error_result` 回纯文本、不经薄壳 handler），测不到薄壳自己的 isError 语义。
            失败调用 = await 会话.call_tool("capability_call", {
                "能力id": "本能力不存在_反向样本", "数组": []})
            失败正文 = 失败调用.content[0].text if 失败调用.content else ""
            失败成功, 失败错误码 = _读判据(失败正文)
            print(f"[10] 故意失败调用 → 成功={失败成功} "
                  f"错误码={失败错误码 or '无'} isError={失败调用.isError}")
            if 失败成功 is not False:
                失败表.append("反向样本未能造成业务失败（样本失效，请换一个）")
            elif not 失败调用.isError:
                失败表.append("业务失败未置 isError=True（客户端与模型都看不见失败）")
            # 反向再拍：schema 层拦（L9）也必须是 isError=True —— 与业务层失败同一个语义。
            # 样本用**已删除的入参名** `参数`：工具面已无该键，`additionalProperties=false`
            # 会让它在 schema 层被 SDK 拒掉（这正是要验的那条语义）。
            schema调用 = await 会话.call_tool("capability_call", {
                "能力id": "某能力", "参数": {}})
            print(f"[11] schema 层拦截（表外入参名 参数）→ isError={schema调用.isError}")
            if not schema调用.isError:
                失败表.append("schema 层拦截未置 isError=True")
            if 失败表:
                print(f"[自测失败] {len(失败表)}/{len(调用表)} 条调用未成功：" + "；".join(失败表))
                return 1
            print(f"[自测通过] tools/list = {len(工具.tools)}，{len(调用表)} 条调用全部成功=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(主程序()))
