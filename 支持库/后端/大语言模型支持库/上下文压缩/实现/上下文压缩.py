"""上下文压缩原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：对话历史的 token 估算与压缩（借鉴 Claude Code compact + Codex auto_compact）。
额度原则：默认不限制；调用时可通过参数配置额度。
压缩策略：保留最近 N 条完整消息，更早消息合并为摘要。
数据源（华哥口径）：压缩从会话存储读历史（句柄 + 会话id），压完写回；
保留 消息列表 直传兜底（无会话存储时用）。
只做估算与压缩，不调用模型。
"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果

默认压缩阈值 = 8000


def _取正文(消息) -> str:
    """取消息正文：英文键 content / 中文键 内容（字典取 正文）都认，取不到才空串。

    跨模块消息结构在本仓有两种口径：会话存储对外是 角色/内容[正文]，模型协议侧是 role/content。
    本函数是本包的**唯一取值口径**，两键都认（B-01 同类修复）——只认单侧时，中文键入参会被
    当成「空消息」在无模型剪枝阶段整批剪掉，表现为「一压缩就静默清空历史」。
    """
    if not isinstance(消息, dict):
        return "" if 消息 is None else str(消息)
    正文 = 消息.get("content")
    if not isinstance(正文, str) or not 正文:
        候选 = 消息.get("内容")
        if isinstance(候选, dict):
            候选 = 候选.get("正文", "")
        if 候选:
            正文 = 候选
    return 正文 if isinstance(正文, str) else ("" if 正文 is None else str(正文))


def _取角色(消息) -> str:
    """取消息角色：英文键 role / 中文键 角色 都认，取不到才回落 user。"""
    if not isinstance(消息, dict):
        return "user"
    for 键 in ("role", "角色"):
        值 = 消息.get(键)
        if isinstance(值, str) and 值.strip():
            return 值.strip()
    return "user"


def _从会话存储读取(句柄: str, 会话id: str) -> tuple[list | None, str]:
    """经会话存储读历史，返回 (消息列表, 错误)。不可用时返回 (None, 原因)。"""
    try:
        from 支持库.后端.大语言模型支持库.会话存储 import 读取历史
        r = 读取历史(句柄=句柄, 会话id=会话id)
        if not r.成功:
            return None, f"读取历史失败: {r.错误说明}"
        消息列表 = []
        for 消息 in r.值.get("消息列表", []):
            内容 = 消息.get("内容", {})
            正文 = 内容.get("正文", "") if isinstance(内容, dict) else str(内容)
            消息列表.append({"role": 消息.get("角色", "用户"), "content": 正文})
        return 消息列表, ""
    except Exception as e:
        return None, f"会话存储不可用: {e}"


def _估算文本token(文本: str) -> int:
    """中文约 1 token/字（保守 0.6），英文约 4 字符/token。"""
    if not 文本:
        return 0
    中文字数 = sum(1 for c in 文本 if ord(c) > 127)
    英文字符数 = len(文本) - 中文字数
    return int(中文字数 * 0.8 + 英文字符数 / 4) + 1


def 估算token数(文本: str = None) -> 结果:
    if not isinstance(文本, str):
        return 结果.失败("参数不合法", "文本必须是非空字符串", 来源="上下文压缩")
    return 结果.成功结果({"token数": _估算文本token(文本), "字符数": len(文本)})


def 估算消息token数(消息列表: list = None) -> 结果:
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    总数 = 0
    for 消息 in 消息列表:
        if not isinstance(消息, dict):
            continue
        内容 = _取正文(消息)
        总数 += _估算文本token(内容) + 4
    return 结果.成功结果({"token数": 总数, "消息数": len(消息列表)})


def 压缩历史(消息列表: list = None, 压缩阈值: int = None,
             保留最近条数: int = None, 摘要长度上限: int = None, 摘要模式: str = None,
             句柄: str = None, 会话id: str = None) -> 结果:
    """压缩对话历史。数据源优先：传 句柄+会话id 从会话存储读取，否则用 消息列表 兜底。

    额度原则：压缩阈值/摘要长度上限 默认 None（内置 8000/不限制），调用方可配置。
    超限不是拒绝，是触发压缩的信号（由调用方决定是否压缩后重试）。
    返回 {已压缩, 压缩前token, 压缩后token, 消息列表, 摘要}。
    """
    # 从会话存储读取（华哥口径：句柄+会话id，不是请求包）
    if 句柄 and 会话id:
        消息列表, 错误 = _从会话存储读取(句柄, 会话id)
        if 消息列表 is None:
            return 结果.失败("读取历史失败", 错误, 来源="上下文压缩")
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    阈值 = 压缩阈值 if isinstance(压缩阈值, int) and 压缩阈值 > 0 else 默认压缩阈值
    保留条数 = 保留最近条数 if isinstance(保留最近条数, int) and 保留最近条数 > 0 else 10
    模式 = (摘要模式 or "拼接").strip()
    if 模式 not in ("拼接", "截断"):
        return 结果.失败("参数不合法", f"摘要模式必须是 拼接/截断: {摘要模式}", 来源="上下文压缩")

    压缩前token = sum(_估算文本token(_取正文(m)) + 4 for m in 消息列表 if isinstance(m, dict))
    if 压缩前token <= 阈值:
        return 结果.成功结果({
            "已压缩": False, "压缩前token": 压缩前token, "压缩后token": 压缩前token,
            "消息列表": 消息列表, "摘要": "", "说明": f"未超阈值 {阈值}，无需压缩",
        })

    保留列表 = 消息列表[-保留条数:]
    早期列表 = 消息列表[:-保留条数]
    # 摘要预算：早期内容必须显著压缩（默认压缩到早期 token 的 20%，可配上限）
    早期token = sum(_估算文本token(_取正文(m)) + 4 for m in 早期列表 if isinstance(m, dict))
    摘要预算 = 摘要长度上限 if isinstance(摘要长度上限, int) and 摘要长度上限 > 0 else max(200, int(早期token * 0.2))
    摘要文本 = "\n".join(
        f"{_取角色(m)}: {_取正文(m)}" for m in 早期列表 if isinstance(m, dict)
    )
    # 真正压缩：摘要必须显著小于早期原文
    摘要文本 = 摘要文本[:摘要预算]
    if len(摘要文本) >= 摘要预算:
        摘要文本 = 摘要文本 + "…"

    新消息列表 = [{"role": "system", "content": f"[历史摘要] {摘要文本}"}] + 保留列表 if 摘要文本 else list(保留列表)
    压缩后token = _估算文本token(摘要文本) + sum(_估算文本token(_取正文(m)) + 4 for m in 保留列表 if isinstance(m, dict))
    return 结果.成功结果({
        "已压缩": True, "压缩前token": 压缩前token, "压缩后token": 压缩后token,
        "消息列表": 新消息列表, "摘要": 摘要文本,
        "说明": f"超阈值 {阈值}，保留最近 {保留条数} 条，早期 {len(早期列表)} 条并入摘要",
    })


def 压缩会话(句柄: str = None, 会话id: str = None, 压缩阈值: int = None,
             保留最近条数: int = None, 摘要长度上限: int = None) -> 结果:
    """会话压缩一条龙：会话存储读历史 → 压缩 → 会话存储写回（带租约）。

    超阈值才压；未超返回原样（不写回）。写回后 压缩次数 递增。
    返回 {已压缩, 压缩前token, 压缩后token, 压缩次数, 说明}。
    """
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="上下文压缩")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="上下文压缩")
    # 1. 从会话存储读
    消息列表, 错误 = _从会话存储读取(句柄, 会话id)
    if 消息列表 is None:
        return 结果.失败("读取历史失败", 错误, 来源="上下文压缩")
    # 2. 压缩
    压缩结果 = 压缩历史(消息列表=消息列表, 压缩阈值=压缩阈值,
                       保留最近条数=保留最近条数, 摘要长度上限=摘要长度上限)
    if not 压缩结果.成功:
        return 压缩结果
    值 = 压缩结果.值
    if not 值["已压缩"]:
        return 结果.成功结果({
            "已压缩": False, "压缩前token": 值["压缩前token"], "压缩后token": 值["压缩后token"],
            "压缩次数": None, "说明": 值.get("说明", "未超阈值，无需压缩"),
        })
    # 3. 写回会话存储（带租约防并发）
    try:
        from 支持库.后端.大语言模型支持库.会话存储 import 写入压缩结果
        写回 = 写入压缩结果(句柄=句柄, 会话id=会话id, 压缩后消息列表=值["消息列表"])
        if not 写回.成功:
            return 结果.失败("写回压缩结果失败", 写回.错误说明, 来源="上下文压缩")
        return 结果.成功结果({
            "已压缩": True, "压缩前token": 值["压缩前token"], "压缩后token": 值["压缩后token"],
            "压缩次数": 写回.值.get("压缩次数"), "说明": f"已压缩并写回，压缩次数 {写回.值.get('压缩次数')}",
        })
    except Exception as e:
        return 结果.失败("写回压缩结果失败", f"会话存储不可用: {e}", 来源="上下文压缩")


# ==== 四阶段压缩（批次5新增：原子分组约束 + 确定性降级链）====

默认保留最近token = 2000


def _消息内容文本(消息) -> str:
    """取消息正文文本（非字典消息按文本处理；中英键都认，口径同 _取正文）。"""
    return _取正文(消息)


def _是否工具调用消息(消息) -> bool:
    """判定是否为「工具调用」发起消息（tool_calls/工具调用 非空）。"""
    if not isinstance(消息, dict):
        return False
    for 键 in ("tool_calls", "工具调用"):
        调用列表 = 消息.get(键)
        if isinstance(调用列表, list) and 调用列表:
            return True
    return False


def _是否工具结果消息(消息) -> bool:
    """判定是否为「工具结果」消息（role=tool 或带 tool_call_id/调用id）。"""
    if not isinstance(消息, dict):
        return False
    角色 = str(消息.get("role", 消息.get("角色", ""))).strip().lower()
    if 角色 in ("tool", "工具"):
        return True
    for 键 in ("tool_call_id", "调用id"):
        标识 = 消息.get(键)
        if isinstance(标识, str) and 标识.strip():
            return True
    return False


def _计算原子分组(消息列表: list) -> list[list[int]]:
    """把消息切成原子分组：工具调用与其后续连续的工具结果绑成一组。"""
    分组列表: list[list[int]] = []
    序号 = 0
    while 序号 < len(消息列表):
        if _是否工具调用消息(消息列表[序号]):
            分组 = [序号]
            后续 = 序号 + 1
            while 后续 < len(消息列表) and _是否工具结果消息(消息列表[后续]):
                分组.append(后续)
                后续 += 1
            分组列表.append(分组)
            序号 = 后续
        else:
            分组列表.append([序号])
            序号 += 1
    return 分组列表


def _无模型剪枝(消息列表: list, 分组列表: list[list[int]]) -> tuple[list, int]:
    """阶段①：无 LLM 剪枝——丢弃空消息与连续重复消息，原子分组整组跳过。"""
    成对索引: set[int] = set()
    for 分组 in 分组列表:
        if len(分组) > 1:
            成对索引.update(分组)
    保留列表: list = []
    剪掉条数 = 0
    for 索引, 消息 in enumerate(消息列表):
        if 索引 in 成对索引:
            保留列表.append(消息)
            continue
        正文 = _消息内容文本(消息)
        if not 正文.strip():
            剪掉条数 += 1
            continue
        # 只折叠与原文上一条完全相同的连续重复消息（不跨被剪消息连坐）
        if 索引 > 0 and 正文 == _消息内容文本(消息列表[索引 - 1]).strip():
            剪掉条数 += 1
            continue
        保留列表.append(消息)
    return 保留列表, 剪掉条数


def _消息token合计(消息列表: list) -> int:
    """按既有估算口径合计消息 token（每条加 4 结构开销）。"""
    合计 = 0
    for 消息 in 消息列表:
        合计 += _估算文本token(_消息内容文本(消息)) + 4
    return 合计


def _对齐原子边界(分组列表: list[list[int]], 边界起点: int) -> int:
    """阶段②辅助：边界不得落在分组内部；落内部则整组前移进保留区。"""
    for 分组 in 分组列表:
        if 分组[0] < 边界起点 <= 分组[-1]:
            return 分组[0]
    return 边界起点


def _分组起止(分组列表: list[list[int]], 索引: int) -> tuple[int, int]:
    """返回包含该索引的分组的起止下标（无分组时返回自身）。"""
    for 分组 in 分组列表:
        if 索引 in 分组:
            return 分组[0], 分组[-1]
    return 索引, 索引


def _确定性摘要(压缩消息列表: list, 摘要预算token: int) -> str:
    """阶段③ fallback：纯规则拼接 + 截断，不调用任何模型。"""
    行列表: list[str] = []
    已用token = 0
    for 消息 in 压缩消息列表:
        角色 = _取角色(消息)
        正文 = _消息内容文本(消息).strip().replace("\n", " ")
        首句 = 正文.split("。")[0].strip()
        if len(首句) > 120:
            首句 = 首句[:120]
        行 = f"[{角色}] {首句}"
        行token = _估算文本token(行) + 1
        if 已用token + 行token > 摘要预算token and 行列表:
            break
        行列表.append(行)
        已用token += 行token
    文本 = "\n".join(行列表)
    if len(行列表) < len(压缩消息列表):
        文本 = f"{文本}\n…（更早内容已折叠）" if 文本 else "（更早内容已折叠）"
    return 文本


def 四阶段压缩(消息列表: list = None, 可用额度token: int = None,
               保留最近token: int = None, 降级模式: str = None,
               原子分组: bool = None, 结束标记: str = None) -> 结果:
    """四阶段上下文压缩（无 LLM 剪枝 → 定边界 → 结构化摘要 → 组装）。

    ① 无 LLM 剪枝：按预算丢弃/折叠明显可省的低价值旧消息（不破坏原子分组）
    ② 定边界：结合 可用额度token 与 保留最近token 算出可压缩区间起止
    ③ 结构化摘要：严格模式无法形成摘要即失败；确定性 fallback 不做模型调用
    ④ 组装：摘要文本 + 保留消息 + 结束标记
    原子分组为真时，切分边界不得把「工具调用」与它的「结果」拆散。
    返回 {摘要文本, 保留消息, 已压缩条数, 降级, 结束标记}。
    """
    if not isinstance(消息列表, list) or not 消息列表:
        return 结果.失败("参数不合法", "消息列表必须是非空列表", 来源="上下文压缩")
    if isinstance(可用额度token, bool) or not isinstance(可用额度token, int) or 可用额度token <= 0:
        return 结果.失败("参数不合法", "可用额度token 必须是正整数", 来源="上下文压缩")
    if 保留最近token is None:
        保留额度 = 默认保留最近token
    elif isinstance(保留最近token, bool) or not isinstance(保留最近token, int) or 保留最近token < 0:
        return 结果.失败("参数不合法", "保留最近token 必须是非负整数", 来源="上下文压缩")
    else:
        保留额度 = 保留最近token
    模式 = str(降级模式).strip() if 降级模式 is not None else "2"
    if 模式 not in ("1", "2"):
        return 结果.失败("参数不合法", f"降级模式 必须是 1/2: {降级模式}", 来源="上下文压缩")
    if 原子分组 is not None and not isinstance(原子分组, bool):
        return 结果.失败("参数不合法", "原子分组 必须是逻辑值", 来源="上下文压缩")
    启用原子分组 = True if 原子分组 is None else 原子分组
    if 结束标记 is not None and not isinstance(结束标记, str):
        return 结果.失败("参数不合法", "结束标记 必须是文本", 来源="上下文压缩")
    标记 = "" if 结束标记 is None else 结束标记

    原条数 = len(消息列表)
    # 阶段① 无 LLM 剪枝
    分组列表 = _计算原子分组(消息列表) if 启用原子分组 else [[i] for i in range(原条数)]
    剪枝后列表, _剪枝条数 = _无模型剪枝(消息列表, 分组列表)
    压缩前token = _消息token合计(剪枝后列表)
    if 压缩前token <= 可用额度token:
        return 结果.成功结果({
            "摘要文本": "", "保留消息": 剪枝后列表,
            "已压缩条数": 原条数 - len(剪枝后列表),
            "降级": False, "结束标记": "",
        })

    # 阶段② 定边界（保留额度从尾部累计）
    剪枝后分组 = _计算原子分组(剪枝后列表) if 启用原子分组 else [[i] for i in range(len(剪枝后列表))]
    边界起点 = 0
    累计token = 0
    for 索引 in range(len(剪枝后列表) - 1, -1, -1):
        累计token += _估算文本token(_消息内容文本(剪枝后列表[索引])) + 4
        if 累计token > 保留额度:
            边界起点 = 索引 + 1
            break
    if 启用原子分组:
        对齐后 = _对齐原子边界(剪枝后分组, 边界起点)
        if 对齐后 != 边界起点:
            保留token = _消息token合计(剪枝后列表[对齐后:])
            if 保留token > 可用额度token:
                # 成对压缩：整组移入压缩区，绝不拆散工具调用与结果
                起, 止 = _分组起止(剪枝后分组, 对齐后)
                边界起点 = 止 + 1
            else:
                边界起点 = 对齐后
    压缩区 = 剪枝后列表[:边界起点]
    保留消息 = 剪枝后列表[边界起点:]

    if not 压缩区:
        if 模式 == "1":
            return 结果.失败("摘要生成失败", "严格模式：可压缩区间为空，无法形成结构化摘要", 来源="上下文压缩")
        return 结果.成功结果({
            "摘要文本": "", "保留消息": 保留消息,
            "已压缩条数": 原条数 - len(保留消息),
            "降级": True, "结束标记": "",
        })

    # 阶段③ 结构化摘要（确定性 fallback 不做任何模型调用）
    压缩区token = _消息token合计(压缩区)
    摘要预算token = max(64, int(压缩区token * 0.3))
    摘要文本 = _确定性摘要(压缩区, 摘要预算token)
    if not 摘要文本.strip():
        if 模式 == "1":
            return 结果.失败("摘要生成失败", "严格模式：摘要为空，无法形成结构化摘要", 来源="上下文压缩")
        摘要文本 = "（更早内容已折叠）"
    摘要token = _估算文本token(摘要文本)
    if 模式 == "1" and 摘要token >= 压缩区token:
        return 结果.失败("摘要生成失败", f"严格模式：摘要 token {摘要token} 未小于原文 {压缩区token}",
                        来源="上下文压缩")

    # 阶段④ 组装
    组装摘要 = f"{摘要文本}{标记}" if 标记 else 摘要文本
    return 结果.成功结果({
        "摘要文本": 组装摘要,
        "保留消息": 保留消息,
        "已压缩条数": 原条数 - len(保留消息),
        "降级": 模式 == "2",
        "结束标记": 标记,
    })