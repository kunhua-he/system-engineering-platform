# 10 顶级 Agent 工具循环对照

> **最后更新**：2026-09-21
> **口径**：本报告所有结论均来自**本机 clone 的真实源码**（`--depth 1`，2026-09-21 拉取），
> 每条附「文件路径 + 行号」，不引用记忆、不引用二手博客。star 数为 shields.io 近似值，会随时间变化，
> 只作量级参考，**不作为判据**。复现命令见文末「取证命令」。
> **维护者**：MCP 审计调研 · 第 10 路（顶级 Agent 工具循环对照）
> **状态**：已完成
<!-- 机器管理｜类型：仓库内其他文档｜生成器：开发工具.MD文档生成 -->


---

## 0. 调研范围与取证方式

clone 落盘：`/Users/hekunhua/.hermes/cache/scratch/开源调研/10/`

| 序号 | 仓库 | 本机目录 | 大小 |
|---|---|---|---|
| 1 | `openai/codex` | `openai-codex/` | 118M |
| 2 | `sst/opencode` | `sst-opencode/` | 220M |
| 3 | `cline/cline` | `cline/` | 112M |
| 4 | `RooCodeInc/Roo-Code` | `Roo-Code/` | 470M |
| 5 | `Aider-AI/aider` | `aider/` | 140M |
| 6 | `modelcontextprotocol/python-sdk` | `mcp-python-sdk/` | 23M |

**共 6 个真源码仓库**（任务要求「至少覆盖 6 个」，实际 6/6 全部 clone 成功并读到源码）。

star 数（shields.io 近似值，2026-09-21）：

| 仓库 | 地址 | 近似 star | 主语言 |
|---|---|---|---|
| openai/codex | https://github.com/openai/codex | 126k | Rust |
| sst/opencode | https://github.com/sst/opencode | 209k | TypeScript（Effect） |
| cline/cline | https://github.com/cline/cline | 69k | TypeScript |
| RooCodeInc/Roo-Code | https://github.com/RooCodeInc/Roo-Code | 24k | TypeScript |
| Aider-AI/aider | https://github.com/Aider-AI/aider | 49k | Python |
| modelcontextprotocol/python-sdk | https://github.com/modelcontextprotocol/python-sdk | 24k | Python |

**未 clone 到的（如实报告）**：`anthropics/claude-code` 仓库为闭源分发（无公开源码，只有 issue 模板与
文档），`microsoft/autogen`、`langchain-ai/langgraph` 未在本轮 clone 集合内（本轮 6 席已占满，
且这两者属「编排框架」而非「Agent 产品工具循环」，优先级低于上面 6 个）。
`anthropics/anthropic-cookbook` 的 agent 示例未取到源码，**本报告不对这三者下任何结论**。

---

## 1. 硬问题一：一次 assistant turn 发多个工具调用，各家怎么做

### 1.1 `openai/codex` —— 并行执行 + 按提交顺序回灌（FuturesOrdered）

- **仓库**：`openai/codex` · https://github.com/openai/codex · ~126k star
- **机制**（源码原文）：
  - 请求侧开关：`codex-rs/core/src/session/turn.rs:1567` → `parallel_tool_calls: true`
    （结构体定义在 `codex-rs/core/src/client_common.rs:30-31`
    `/// Whether parallel tool calls are permitted for this prompt. pub(crate) parallel_tool_calls: bool`，
    缺省 `false`，见 `client_common.rs:49`）。
  - 循环侧：`codex-rs/core/src/session/turn.rs:2503`
    `let mut in_flight: FuturesOrdered<InFlightFuture<'static>> = FuturesOrdered::new();`
    —— 一条 assistant 响应里的**每个 tool call 都变成一个 future 入队**，可同时在飞。
  - 收口：`codex-rs/core/src/session/turn.rs:2396-2424` `async fn drain_in_flight(...)`，
    `while let Some(res) = in_flight.next().await { ... sess.record_annotated_conversation_items(...) }`
    —— **并行执行，但按提交顺序（FuturesOrdered 语义）逐条写回会话历史**，顺序确定、不串味。
- **并发门闸（最可照搬的一处）**：`codex-rs/core/src/tools/parallel.rs`
  - `:44 pub(crate) struct ToolCallRuntime { ... :49 parallel_execution: Arc<RwLock<()>> }`
  - `:124 let supports_parallel = router.tool_supports_parallel(&call);`
  - `:179-183`（门闸原文）
    ```
    let guard = if supports_parallel {
        Either::Left(lock.read().await)      // 读锁：可并发
    } else {
        Either::Right(lock.write().await)    // 写锁：与所有工具互斥
    };
    ```
    → **一把全局 `RwLock<()>`，工具自带「可否并行」标记**：声明可并行的拿读锁（互相不阻塞），
    未声明的拿写锁（独占，把整批串起来）。
  - 标记来源：`codex-rs/core/src/tools/registry.rs:520-522`
    `Some(tool.exposure != ToolExposure::Hidden && tool.runtime.supports_parallel_tool_calls())`
  - **缺省值**：`codex-rs/core/src/tools/router.rs:233-237` → `.unwrap_or(false)`
    —— **默认不并行，必须显式声明才并行**。
- **与本项目节点的对应**：**A1**（薄壳 `tool_call` 一次只许调 1 个 local 工具）。
  codex 证明「一次多工具」不需要新协议，只需要：① 响应里允许多个 call；② 一把门闸决定谁能并发。
  本项目平台的 `执行命令集` 已经支持并行 8 路，**薄壳缺的只是同一套门闸**。
- **照搬落地代价**：薄壳 `tool_call` 入参从「单个工具」扩成「列表」需新增契约字段
  （按「参数/返回只增不改不删」→ **加 `工具清单` 可选字段，旧 `工具` 字段保留为单元素兼容**）；
  门闸按能力注册表加一个 `可否并行` 布尔标记（缺省假）；风险是并发下**资源租约冲突**从「串行天然规避」
  变成「必须显式声明」，需要给写类能力（改文件、重启网关）全部标成不可并行。

### 1.2 `sst/opencode` —— 每个 toolCallID 一个独立状态机

- **仓库**：`sst/opencode` · https://github.com/sst/opencode · ~209k star
- **机制**：`packages/opencode/src/session/processor.ts`
  - `:123 settleToolCall(toolCallID)` / `:129 readToolCall(toolCallID)` / `:186 failToolCall(toolCallID, error)`
  - 并发单元是 **`ctx.toolcalls[toolCallID]` 这张表**（`:151 ctx.toolcalls[toolCallID] = {...}`），
    每个调用有独立生命周期 `running → completed | error`，`settleToolCall` 里 `delete ctx.toolcalls[toolCallID]` 清理。
  - → 同一 turn 内多个 tool call 各自跑各自的，靠 **ID 索引的状态表**收口，不靠全局串行。
- **与本项目节点的对应**：**A1 / F1**。本项目「一次只调 1 个」的替代方案之一就是
  「一次收多个、每个给 ID、用表收口」，且这张表天然就是 F1 要的「调用耗时榜」的数据源
  （opencode 的 part 里带 `time: { start, end }`，见下 1.4）。
- **照搬落地代价**：中等。要在薄壳引入「调用 ID → 状态」表，返回体需带 `调用id`；
  好处是并行 + 可观测一次到位。

### 1.3 `cline/cline` 与 `RooCodeInc/Roo-Code` —— 逐工具推进 + 重复检测

- **`cline/cline`** · https://github.com/cline/cline · ~69k star
  - 仓库已重构为 `apps/`（vscode / cli / examples）+ `sdk/packages/core`，
    旧的 `src/core/task/index.ts` **在本版本已不存在**（如实报告：任务信里按老结构给的路径已失效）。
  - 现存工具循环与安全逻辑：`sdk/packages/core/src/runtime/safety/mistake-tracker.ts`、
    `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`、
    `apps/cli/src/runtime/interactive/mistakes.ts`。
- **`RooCodeInc/Roo-Code`** · https://github.com/RooCodeInc/Roo-Code · ~24k star
  - `src/core/task/Task.ts:381 didAlreadyUseTool = false` —— **同一 turn 内重复调用同一工具会被短路**。
  - `:513 this.toolRepetitionDetector = new ToolRepetitionDetector(this.consecutiveMistakeLimit)`
    —— 专门的**重复检测器**，阈值复用「连续错误上限」。
  - `:316-319` 错误计数**按维度分开**：`consecutiveMistakeCount`（总）、
    `consecutiveMistakeCountForApplyDiff: Map<string, number>`、`consecutiveMistakeCountForEditFile: Map<string, number>`
    —— 后者是 **Map，按文件分别计数**（同一个文件改错 3 次就停，换文件重新计数）。
  - `:2483 if (this.consecutiveMistakeLimit > 0 && this.consecutiveMistakeCount >= this.consecutiveMistakeLimit)`
    → `:2500 this.consecutiveMistakeCount = 0` 停手并重置。
  - `:1048` 注释：`// Tools execute during streaming via presentAssistantMessage, BEFORE the assistant...`
    —— 工具在**流式过程中就执行**，不等整条 assistant 消息收完。
- **与本项目节点的对应**：**A1 + A2 + F1**。这两家走的是「不并行，但把**重复/失败**卡死」路线：
  本项目实测「同一个能力重调 6 次才看全」（B1）正好是 Roo-Code 用
  `ToolRepetitionDetector` + 按维度计数要防的事。
- **照搬落地代价**：低。薄壳加「同 turn 同能力重复调用计数 + 按能力/按目标路径分桶」，
  改的是薄壳调度层一个文件，不动契约。

### 1.4 一次 turn 多工具：**协议字段 vs 循环控制**的分野（总结）

| 家 | 协议字段 | 循环控制 |
|---|---|---|
| codex | `parallel_tool_calls: true`（`client_common.rs:31`） | `FuturesOrdered` 在飞队列 + `RwLock<()>` 门闸（`parallel.rs:179-183`） |
| opencode | tool part 列表（`message.ts:14/23/32 toolCallId`） | `ctx.toolcalls[toolCallID]` 状态表（`processor.ts:151/183/186`） |
| Roo-Code | 无并行开关 | `didAlreadyUseTool` + `ToolRepetitionDetector`（`Task.ts:381/513`） |
| aider | **无**（一次一个 edit block 批） | `run_one` + `max_reflections = 3`（`base_coder.py:101/939-944`） |
| mcp python-sdk | 无 | **SDK 不提供**，`call_tool` 只是 async 函数，多工具靠调用方 `asyncio.gather`（`client/session.py:993-1052`；示例 `examples/mcpserver/memory.py:271`） |

**结论**：「一次 turn 多工具」在顶级产品里**不是模型能力问题，是宿主循环的调度问题**——
codex 用一把锁 + 一个有序队列就解决了，协议上只多一个布尔开关。

---

## 2. 硬问题二：怎么避免「同一份大结果重复注入上下文」

### 2.1 `cline/cline` —— **深裁结构化字段**，而不是整包丢弃（★ 直击本项目 B1）

- **仓库**：`cline/cline` · https://github.com/cline/cline · ~69k star
- **关键文件**：`sdk/packages/core/src/session/services/message-builder.ts`
- **机制**：
  - `:1087` 注释原文：`Deep-truncates string values inside structured tool outputs (e.g. ...)`
    —— **遍历结构化返回体内部的字符串值逐个裁剪**。
  - 两个原语：`:1537 truncateMiddleByChars(text, maxChars)`（`:1540` 短于预算直接返回；
    `:1549/:1553` 用 `Math.floor((maxChars - marker.length) / 2)` 算「头尾各留一半」）、
    `:1191 truncateMiddleToBytes(...)`（按字节，`:1197 totalBytes -= currentBytes - utf8ByteLength(truncated)`）。
  - **裁剪必留标记**（`:53-61` 原文）：
    - `` \n\n...[truncated ${n} chars]...\n\n ``
    - `` \n\n...[truncated ${n} chars to fit provider request budget]...\n\n ``
    - `` \n\n...[assistant text truncated: omitted ${n} chars]...\n\n ``
    - `` \n\n...[assistant text truncated: omitted ${n} chars due to repeated tool-call markup]...\n\n ``
  - **测试显式覆盖「结构化里的大字段」**（`message-builder.test.ts`）：
    `it("...a huge nested `result` string in run_commands structured output")`、
    `it("...a huge nested `query` string in run_commands structured output")`、
    `it("...a huge file payload in read_files structured output")`；
    并断言默认额度 `DEFAULT_..._MAX` = **8_000 / 50_000**（字符），
    `expect(output.length).toBeLessThanOrEqual(DEFAULT_...)`、`expect(block.content).toContain("...[truncated")`。
- **与本项目节点的对应**：**B1**（「结构化字段超限被**整段丢弃**（文本字段才是截断，规则不统一），
  实测一次返回 81874 字符被裁到 3292」）。
  cline 的规则是**统一的**：**无论文本字段还是结构化字段里的嵌套字符串，一律「保留头尾 + 中间挖掉 + 留标记」**，
  **没有任何路径会把整个结构丢掉**。
- **照搬落地代价**：**低—中**。改的是网关返回体裁剪这一个函数：
  ① 把「结构化超限 → 丢弃」的分支删掉，改成递归遍历 dict/list 的字符串叶子；
  ② 每个叶子走 `truncateMiddleByChars` 同款（头尾各半 + `...[truncated N chars]...` 标记）；
  ③ 预算按整体字节算（cline 的 `totalBytes` 递减法可照抄）。
  风险：递归裁剪会改变结构化字段的**类型稳定性**（长字符串→短字符串仍是字符串，**类型不变**，
  但下游若断言长度会变红）——需同步跑一次契约漂移检测。

### 2.2 `sst/opencode` —— 只清**最老的**工具输出，且设「值得清」下限与「永不碰」保护区

- **仓库**：`sst/opencode` · https://github.com/sst/opencode · ~209k star
- **关键文件**：`packages/opencode/src/session/compaction.ts`
- **机制**（源码原文常量）：
  - `:28 export const PRUNE_MINIMUM = 20_000`
  - `:29 export const PRUNE_PROTECT = 40_000`
  - `:271` 注释：`// goes backwards through parts until there are PRUNE_PROTECT tokens worth of tool ...`
    —— **从最新往回数，凑够 `PRUNE_PROTECT` 的最近工具输出永不清理**；
    再往前的才清，且**累计省下的量必须够 `PRUNE_MINIMUM` 才动手**（避免为省 200 token 付一次重算）。
  - `:51-52` 单条工具输出上限：
    ```
    const truncate = (value: string) =>
      value.length <= TOOL_OUTPUT_MAX_CHARS ? value : `${value.slice(0, TOOL_OUTPUT_MAX_CHARS)}\n[truncated]`
    ```
  - `:117 input.cfg.compaction?.preserve_recent_tokens ?? ...`、`:228 const limit = input.cfg.compaction?.tail_turns`
  - `:366 const previousSummary = prior.at(-1)?.summary` —— 压缩是**增量叠加摘要**（前一次摘要作为下一次的输入），
    不是每次从头重算。
- **配套溢出判定**：`packages/opencode/src/session/overflow.ts`
  `:10-18 usable()` = `model.limit.context - reserved`（有 `limit.input` 就用它）、
  `:22-32 isOverflow()` 用 `tokens.total || input + output + cache.read + cache.write` 比上限。
- **与本项目节点的对应**：**B1 + 上下文成本**。本项目元判据是「往返次数 × 每轮全上下文注入 = 真成本」，
  opencode 的 `PRUNE_MINIMUM / PRUNE_PROTECT` 正是**控制「每轮全上下文注入」那一项**的现成参数化做法。
- **照搬落地代价**：低。本项目当前没有会话级工具输出清理，若要引入，改的是会话历史组装层
  （不是网关），新增两个配置项；风险是清理后模型可能"忘了"早前读过的内容，
  需要像 opencode 一样在摘要里保留结论。

### 2.3 `Aider-AI/aider` —— 把「整仓结构」压成固定 token 预算的 repo map

- **仓库**：`Aider-AI/aider` · https://github.com/Aider-AI/aider · ~49k star
- **关键文件**：`aider/repomap.py`
- **机制**：
  - `:49 map_tokens=1024`、`:70 self.max_map_tokens = map_tokens`
  - `:103 def get_repo_map(...)`、`:120-132` 若有 `max_context_window` 则按
    `int(max_map_tokens * self.map_mul_no_files)` 重算目标
  - `:676 middle = min(int(max_map_tokens // 25), num_tags)`
  - `:689-698` 用**二分搜索**逼近预算：
    `pct_err = abs(num_tokens - max_map_tokens) / max_map_tokens`，
    `if (num_tokens <= max_map_tokens and num_tokens > best_tree_tokens) or pct_err < ok_err:` 收敛
  - `:145 self.max_map_tokens = 0`（拿不到就整体放弃，不留半截）
- **与本项目节点的对应**：**E1 + E2**（「只有单层列出目录，没有树」「发现要三跳 search → describe → call」）。
  aider 的答案是：**一次把结构压到预算内给全**（map），而不是让模型来回问。
  这正是元判据要的「一次给全」。
- **照搬落地代价**：**中**。需要在能力目录侧新增「按 token 预算生成结构树」的口
  （对应 E1 要的「树」）；收益是 E2 的三跳变一跳。风险是结构树可能与真实注册表漂移，
  必须由注册表**实时生成**而非落盘缓存。

### 2.4 `RooCodeInc/Roo-Code` —— 压缩前先把 tool_use/tool_result 配对补齐

- **仓库**：`RooCodeInc/Roo-Code` · https://github.com/RooCodeInc/Roo-Code · ~24k star
- **关键文件**：`src/core/task/Task.ts`
- **机制**：
  - `:1603 public async condenseContext()`，`:1604-1606` 注释原文：
    `// CRITICAL: Flush any pending tool results before condensing`
    `// to ensure tool_use/tool_result pairs are complete in history`
    → `await this.flushPendingToolResultsToHistory()`。
  - `:1615 const { contextTokens: prevContextTokens } = this.getTokenUsage()` —— 压缩前后记 token。
  - `:360-373 pushToolResultToUserContent` 按 `tool_use_id` **去重**：
    `block.type === "tool_result" && block.tool_use_id === toolResult.tool_use_id` →
    `"[Task#pushToolResultToUserContent] Skipping duplicate tool_result for tool_use_id: ..."`
    —— **同一份结果重复回灌在历史层就被挡掉**。
  - `:985-994` 孤立 tool_result 转成 text block（注释：`This prevents orphaned tool_results from being filtered out`）。
  - `:1043-1045` 注释：`Without this, tool_result blocks would appear BEFORE tool_use blocks in the ...`
    → `"unexpected \`tool_use_id\` found in \`tool_result\` blocks"`（防协议级报错）。
- **与本项目节点的对应**：**B1**。本项目「同一个能力重调 6 次才看全」在 Roo-Code 里对应两件事：
  ① 历史层**按 ID 去重**（同一结果不重复注入）；② 压缩**前**先补配对，避免压缩把配对撕开。
- **照搬落地代价**：低。网关返回体带 `调用id`/`能力id` + 目标路径指纹，会话层按指纹去重
  并回「本次调用与第 N 次结果相同，已去重」——**这一步直接砍掉重复往返**。

---

## 3. 硬问题三：工具调用失败怎么处理（对 A2 最直接）

### 3.1 `Aider-AI/aider` —— 回带「原文 + 最接近的正确片段 + 该改哪 + 规则原文」（★ 最强）

- **仓库**：`Aider-AI/aider` · https://github.com/Aider-AI/aider · ~49k star
- **关键文件**：`aider/coders/editblock_coder.py:84-114`（失败回带体构造原文）
  ```
  res = f"# {len(failed)} SEARCH/REPLACE {blocks} failed to match!\n"
  for edit in failed:
      ...
      res += f"""
  ## SearchReplaceNoExactMatch: This SEARCH block failed to exactly match lines in {path}
  <<<<<<< SEARCH
  {original}=======
  {updated}>>>>>>> REPLACE

  """
      did_you_mean = find_similar_lines(original, content)          # ← 关键
      if did_you_mean:
          res += f"""Did you mean to match some of these actual lines from {path}?

  {self.fence[0]}
  {did_you_mean}
  {self.fence[1]}
  """
      if updated in content and updated:
          res += f"""Are you sure you need this SEARCH/REPLACE block?
  The REPLACE lines are already in {path}!
  """
  res += ("The SEARCH section must exactly match an existing block of lines including all white ...")
  ```
- **四件套结构**：① **错误码**（`## SearchReplaceNoExactMatch`）+ ② **原文回显**（原始 SEARCH/REPLACE 块）
  + ③ **正确落点**（`find_similar_lines` 找出最接近的真实行）+ ④ **规则原文**（"The SEARCH section must
  exactly match an existing block of lines including all white..."）。
  另外还有「你其实不需要改」分支（REPLACE 已在文件里）。
- **重试机制**：`aider/coders/base_coder.py`
  - `:100-101 num_reflections = 0` / `max_reflections = 3`
  - `:924 def run_one(self, user_message, preproc)`，`:933 self.reflected_message = None`，
    `:936 if not self.reflected_message: ...`，`:939-944`
    `if self.num_reflections >= self.max_reflections:` → `tool_warning(f"Only {self.max_reflections} reflections allowed, stopping.")`；否则 `self.num_reflections += 1; message = self.reflected_message`
  - → **失败自动重试，硬上限 3 次，到顶明确停手**（对应任务信纪律「同一现象连续两次失败即停手」）。
- **与本项目节点的对应**：**A2 + B2**。
  - A2（工具描述不带参数名与列表内字段形状，第一跳必错，实测猜错 3 次）
    → aider 的做法是**失败时把「最接近的正确签名」直接摆出来**（`find_similar_lines` 的等价物）。
  - B2（门禁报红只给一行原文，不给落点/修法）
    → aider 的 `## 错误码` + 原文 + `Did you mean...` + 规则原文，**就是 B2 要的四件套**。
- **照搬落地代价**：**中**。网关错误体从「一行原文」扩成四段：
  ① 错误码（本项目已有，`公开错误码状态映射`）；
  ② **原文回显**（收到的参数原样贴回）；
  ③ **候选签名**——由能力契约算：把收到的键与契约参数名做相似度匹配
     （`difflib.get_close_matches` 等价于 `find_similar_lines`），输出「你是不是想传 `能力id`？」；
  ④ **规则原文**（参数表 + 返回结构 + 错误码表三段的权威口径）。
  风险：错误体变大 → 但按元判据「一次给全 ≫ 分三次问」，这是**净赚**。

### 3.2 `openai/codex` —— 失败也产结构化结果回灌 + 工具名纠错

- **仓库**：`openai/codex` · https://github.com/openai/codex · ~126k star
- **机制**：
  - `codex-rs/core/src/tools/parallel.rs:304-319`
    `fn aborted_response(call: &ToolCall, secs: f32) -> AnyToolResult`、
    `fn abort_message(...)` → `format!("Wall time: {secs:.1} seconds\naborted by user")` /
    `format!("aborted by user after {secs:.1}s")`
    —— **中断/失败也产一条带耗时与原因的结构化 tool 结果回灌**，不让调用悬空。
  - `codex-rs/core/src/session/turn.rs:2418-2420`（drain 里的错误分支）
    `Err(err) => { error_or_panic(format!("in-flight tool future failed during drain: {err}")); }`
    —— 单条工具 future 失败**不炸整批**，只报错继续 drain。
  - 耗时账本：`parallel.rs` 内 `ToolCallTimingGuard::capture(started, &session.thread_id, &turn.sub_id, &call, &source, ...)`
    —— **每次工具调用都记耗时**（对应本项目 F1「执行命令有耗时记录但没有调用耗时榜」）。
- **`sst/opencode` 的补强 —— 工具名纠错重试**：
  - `packages/opencode/src/session/llm.ts:297-307`
    ```
    const lower = failed.toolCall.toolName.toLowerCase()
    if (lower !== failed.toolCall.toolName && prepared.tools[lower]) {
      ... { ...failed.toolCall, toolName: lower }   // 用归一化后的名字重发
    } else {
      ... { ...failed.toolCall, toolName: failed.toolCall.toolName }
    }
    ```
    —— **工具名大小写/别名归一化后自动重试一次**。
  - `packages/opencode/src/session/processor.ts:186-198 failToolCall`：失败时保留
    `input: match.part.state.input`、`metadata: match.part.state.metadata`（注释：
    `Keep metadata streamed while running so failures retain progress detail (e.g. execute's child calls).`）、
    `time: { start, end }` —— **失败结果带原始入参 + 进度元数据 + 时间**。
- **`cline/cline` 的补强 —— 连续错误计数 + 遥测 + 明确停手文案**：
  - `sdk/packages/core/src/runtime/safety/mistake-tracker.ts`
    `:80 export class MistakeTracker { :81 private consecutiveMistakes = 0 ... }`
    `:90 const next = input.forceAtLimit && max ? max : this.consecutiveMistakes + 1`
    `:116-125` 构造 `ConsecutiveMistakeLimitContext` 并 `onLimitTelemetry?.(limitContext)`
    `:165-178 export function buildMistakeLimitStopMessage(...)` →
    `Stopped after ${consecutiveMistakes}/${maxConsecutiveMistakes} consecutive mistakes (${reason}) at iteration ${iteration}.`
    `:198 async function resolveConsecutiveMistakeDecision(...)`
    → `reason: "maximum consecutive mistakes reached (${maxConsecutiveMistakes})"`
    `:2` 文件头注释：`* Per-session consecutive-mistake tracker.`
    —— **错误计数、原因、迭代号、上限、遥测钩子**五件齐备。
- **与本项目节点的对应**：**A2 + B2 + F1**。
  - 「失败也产结构化结果 + 带耗时」→ 直接补 F1 的调用耗时账本。
  - 「工具名归一化重试」→ A2 的即时止血（本项目网关操作名写错回「操作不存在」，
    可做同款归一化重试 + 候选列表）。
  - 「连续错误上限 + 明确停手文案」→ 本项目纪律「同一现象连续两次失败即停手」的**代码化**。
- **照搬落地代价**：低—中。
  - 耗时账本：`执行命令` 已有耗时记录，扩成「按能力 id 聚合的调用耗时榜」即可（F1）。
  - 工具名/操作名归一化：网关入口加一层归一化（**必须在参数校验之前**，符合本项目
    「归一化须在校验之前」纪律），风险是误纠正——用「只在唯一候选时纠正，多候选则报错并列出候选」。
  - 连续错误停手：薄壳调度层加计数器（低）。

---

## 4. 硬问题四：上下文压缩各家怎么做

| 家 | 触发 | 做法 | 关键常量/字段 |
|---|---|---|---|
| codex | token 预算 | 按预算挑历史消息 + 生成摘要，前后 token 都记账 | `compact.rs:60 COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000`；`compact.rs:694-703` `remaining = max_tokens.saturating_sub(tokens)`；`compact.rs:429-432 active_context_tokens_before / compaction_summary_tokens / cached_input_tokens / cache_write_input_tokens` |
| opencode | `isOverflow()` | 清理最老工具输出（有下限与保护区）+ 增量摘要 | `compaction.ts:28 PRUNE_MINIMUM = 20_000`、`:29 PRUNE_PROTECT = 40_000`、`:366 previousSummary = prior.at(-1)?.summary`；`overflow.ts:10-18 usable()` |
| Roo-Code | 用户/自动 | 先补 tool_use/tool_result 配对，再用同一套 tools 发摘要请求 | `Task.ts:1603-1615 condenseContext()`、`:1606 flushPendingToolResultsToHistory()`、`:1615 prevContextTokens` |
| aider | 每轮组装 | 整仓结构压成固定预算 repo map（二分逼近） | `repomap.py:49 map_tokens=1024`、`:676 middle = min(int(max_map_tokens // 25), num_tags)`、`:689-698 pct_err` |
| cline | provider 请求预算 | 深裁结构化字段 + 中间截断，带 `...[truncated N chars to fit provider request budget]...` | `message-builder.ts:55/59`、`:1087`、`:1537/1540/1549/1553` |
| mcp python-sdk | 无 | **不做压缩**；只提供 `list_tools(params: PaginatedRequestParams \| None)` 分页（`client/session.py:1278`）与 `call_tool` 重载（`:993-1052`） | — |

**共性（可直接引用的结论）**：
1. **压缩前后都记 token 数**（codex、Roo-Code 都有 `before/after` 字段）——没有度量就没有压缩策略。
2. **压缩永远保留「最近的 N 个 token」**（opencode `PRUNE_PROTECT`、codex `preserve_recent`）——
   绝不整体清空。
3. **压缩必须保持 tool_use/tool_result 配对完整**（Roo-Code 专门 flush 一遍）。
4. **摘要增量叠加**，不是每次从头（opencode `previousSummary`）。

---

## 5. 能直接照搬到本项目的 3 条做法（写清改哪）

### 照搬 ①：结构化返回体「深裁」，永不整包丢弃 —— 直击 B1

- **来源**：`cline/cline` · https://github.com/cline/cline · ~69k star ·
  `sdk/packages/core/src/session/services/message-builder.ts:1087`（`Deep-truncates string values inside
  structured tool outputs`）、`:1537/1540/1549/1553`（`truncateMiddleByChars`：头尾各半）、
  `:53-61`（四款截断标记文案）、`:1191/1197`（`truncateMiddleToBytes` 按字节递减 `totalBytes`）。
- **改哪**：网关返回体裁剪函数**一处**。现状是「文本字段截断 / 结构化字段整段丢弃」两条不一致的规则，
  改成**一条规则**：递归遍历返回体，对每个字符串叶子按预算做「保留头尾 + 中间挖掉 + 附
  `...[truncated N chars]...`」，结构化容器本身**永不丢**。
- **改多大**：一个函数 + 它的单测；预算口径从「字段数」改成「整体字节」。
- **风险**：① 下游若断言字段长度会变红 → 需跑 `开发工具/契约编译/漂移检测 --报告` 期望判红 0 条；
  ② 递归深度需设上限（防深嵌套爆栈）。
- **为什么值**：实测一次 81874 字符被裁到 3292、同一能力重调 6 次。
  按元判据「往返次数 × 每轮全上下文注入」，**6 次往返的代价远大于一次给全 81874 字符**。

### 照搬 ②：每个能力自带「可否并行」标记 + 一把读写门闸 —— 直击 A1

- **来源**：`openai/codex` · https://github.com/openai/codex · ~126k star ·
  `codex-rs/core/src/tools/parallel.rs:44/49`（`ToolCallRuntime` / `parallel_execution: Arc<RwLock<()>>`）、
  `:124`（`supports_parallel = router.tool_supports_parallel(&call)`）、
  `:179-183`（`if supports_parallel { lock.read() } else { lock.write() }`）、
  `registry.rs:520-522`（标记来源）、`router.rs:233-237`（**`.unwrap_or(false)` 缺省不并行**）、
  `session/turn.rs:2503`（`FuturesOrdered` 在飞队列）+ `:2396-2424`（`drain_in_flight` 按序回灌）。
- **改哪**：① 薄壳 `tool_call` 契约**只增不改**地加一个可选字段 `工具清单`（旧 `工具` 字段保留为单元素兼容）；
  ② 能力注册表加 `可否并行` 布尔（缺省假）；③ 调度层加一把 `RwLock`（可并行能力拿读锁，
  其余拿写锁把整批串起来）；④ 结果按提交顺序回灌。
- **改多大**：薄壳契约 +1 可选字段、注册表 +1 布尔、调度层 +1 门闸 + 一个有序收口函数。
- **风险**：① 并发后**资源租约冲突**从「串行天然规避」变成必须显式声明 →
  所有写类能力（改文件 / 重启网关 / 编译）必须标 `可否并行=假`，否则会撞车；
  ② 顺序敏感性（能力 A 产出的资源被 B 用）需保持提交顺序，故用 `FuturesOrdered` 而非 `join_all`。
- **为什么值**：本项目平台自己的 `执行命令集` **已经支持并行 8 路**，
  薄壳却只许 1 路 —— 这是**同一系统内的不一致**，补门闸即可对齐，不需要新协议。

### 照搬 ③：失败回带「错误码 + 原文 + 最接近的正确签名 + 规则原文」，并硬上限重试 —— 直击 A2 / B2

- **来源**：`Aider-AI/aider` · https://github.com/Aider-AI/aider · ~49k star ·
  `aider/coders/editblock_coder.py:84-114`（失败体四段式 + `find_similar_lines` → `Did you mean to match
  some of these actual lines from {path}?` + 规则原文）；
  `aider/coders/base_coder.py:100-101`（`num_reflections = 0 / max_reflections = 3`）、
  `:939-944`（`Only {max_reflections} reflections allowed, stopping.`）。
  补强来源：`sst/opencode`（https://github.com/sst/opencode · ~209k star）
  `packages/opencode/src/session/llm.ts:297-307`（工具名小写归一化后自动重试一次）、
  `packages/opencode/src/session/processor.ts:186-198`（失败保留 `input` + `metadata` + `time`）。
- **改哪**：网关错误体构造**一处**，从「一行原文」扩成四段：
  ① **错误码**（复用现有 `公开错误码状态映射`，默认 400，查表不猜）；
  ② **原文回显**（收到的参数原样贴回，含写错的键名）；
  ③ **候选签名**（用能力契约的参数名做相似度匹配，等价 `find_similar_lines`，
     输出「你是不是想传 `能力id`？」，**多候选时全部列出**）；
  ④ **规则原文**（该能力的参数表 + 返回结构 + 错误码表三段）。
  另加：操作名/能力 id 的**归一化重试一次**（大小写、别名表），
  **归一化必须在参数校验之前**（本项目纪律）。
- **改多大**：错误体构造函数 + 一个相似度匹配工具函数 + 别名归一化前置层；
  重试上限做成配置项（缺省 1 次自动重试 / 连续 2 次失败停手，对齐本项目纪律）。
- **风险**：① 错误体变大 → 但按元判据这是**净赚**（一次给全 ≫ 分三次猜）；
  ② 自动重试可能掩盖真错误 → 必须在重试结果里**显式标注「本次为重试，原因为 X」**，
  且**只重试「归一化后有唯一候选」的情况**，多候选直接报错列候选，不猜。
- **为什么值**：实测 A2「第一跳必错，猜错 3 次」+ B2「门禁报红只给一行原文，不给落点/修法」，
  两处都是「模型缺信息 → 只能再问一轮」。aider 用一段文本就把这一轮省掉了。

---

## 6. 与本项目 A/B/E 三层节点的总对照表

| 本项目节点 | 现象 | 对照家 + 机制 | 落地代价 |
|---|---|---|---|
| **A1** 薄壳一次只调 1 个 local 工具 | 轮次放大器 | codex `RwLock` 门闸 + `FuturesOrdered`（`parallel.rs:179-183`、`turn.rs:2503`）；opencode `ctx.toolcalls[toolCallID]` 状态表（`processor.ts:151`） | 薄壳契约 +1 可选字段、注册表 +1 布尔、调度层 +1 门闸；**中** |
| **A2** 工具描述不带参数名与字段形状，第一跳必错 | 猜错 3 次 | aider `find_similar_lines` + `Did you mean...`（`editblock_coder.py:98-106`）；opencode 工具名归一化重试（`llm.ts:297-307`） | 错误体 + 候选签名 + 归一化前置；**中** |
| **B1** 结构化字段超限被整段丢弃 | 81874 → 3292，重调 6 次 | cline 深裁结构化字符串叶子 + 头尾各半 + 标记（`message-builder.ts:1087/1537/1549/1553/53-61`）；Roo-Code 历史层按 `tool_use_id` 去重（`Task.ts:360-373`） | 裁剪函数一处；**低—中** |
| **B2** 门禁报红只给一行原文 | 无落点/修法 | aider 四段式失败体（`editblock_coder.py:84-114`）；cline `buildMistakeLimitStopMessage`（`mistake-tracker.ts:165-178`） | 错误体构造一处；**低—中** |
| **E1** 只有单层列目录，没有树 | find 12.4s vs rg 0.07s | aider repo map 二分逼近预算（`repomap.py:49/676/689-698`） | 新增「按预算生成结构树」口；**中** |
| **E2** 发现要三跳 search → describe → call | search 90 / describe 21 次 | aider 一次给全 map；mcp python-sdk `list_tools` 分页一次拿全（`client/session.py:1278`） | 能力目录侧合并口；**中** |
| **F1** 有耗时记录但没有调用耗时榜 | 无榜 | codex `ToolCallTimingGuard`（`parallel.rs`）；opencode part `time: {start, end}`（`processor.ts:197`） | 聚合一个视图；**低** |
| 上下文成本（元判据） | 往返 × 全上下文注入 | opencode `PRUNE_MINIMUM=20_000` / `PRUNE_PROTECT=40_000`（`compaction.ts:28-29`）；codex `COMPACT_USER_MESSAGE_MAX_TOKENS=20_000`（`compact.rs:60`） | 会话历史层两配置项；**低** |

---

## 7. 三条硬结论

1. **「一次 turn 多工具」是宿主循环问题，不是协议问题**。codex 只多了一个
   `parallel_tool_calls: true` 开关（`client_common.rs:31`）+ 一把 `RwLock<()>`
   （`parallel.rs:179-183`）就实现了；本项目薄壳「一次只许 1 个」是**自己加的约束**，
   且与平台自己的 `执行命令集`（并行 8 路）**不一致**。
2. **「结果裁剪」在顶级产品里是统一规则，不存在「文本截断、结构化整包丢」的双轨**。
   cline 明确做**结构化内部深裁**（`message-builder.ts:1087`），
   codex 明确做**中间截断保留头尾**（`truncate.rs` 的 `…{removed_count} chars truncated…` +
   `assemble_*_output(prefix, suffix, marker)`）。本项目的双轨是**孤例**，不是行业常态。
3. **「失败回带」的行业标准是「把正确写法直接摆出来」，不是「报一行错」**。
   aider 的 `Did you mean to match some of these actual lines from {path}?`
   （`editblock_coder.py:98-106`）是最佳范例；配合硬上限重试
   （`max_reflections = 3`，`base_coder.py:101`）就形成闭环。本项目 B2 目前只到「报错码 + 一行原文」，
   距行业标准差**三段**（原文回显 / 候选签名 / 规则原文）。

---

## 8. 取证命令

```bash
# 代理 + 工具链
export https_proxy=http://127.0.0.1:4780 http_proxy=http://127.0.0.1:4780
export PATH=/Library/Developer/CommandLineTools/usr/bin:/opt/homebrew/bin:$PATH; unset PYTHONPATH
GIT=/Library/Developer/CommandLineTools/usr/bin/git
BASE=/Users/hekunhua/.hermes/cache/scratch/开源调研/10

# 1) 拉源码（--depth 1）
$GIT clone --depth 1 --single-branch https://github.com/openai/codex.git       $BASE/openai-codex
$GIT clone --depth 1 --single-branch https://github.com/sst/opencode.git       $BASE/sst-opencode
$GIT clone --depth 1 --single-branch https://github.com/cline/cline.git        $BASE/cline
$GIT clone --depth 1 --single-branch https://github.com/RooCodeInc/Roo-Code.git $BASE/Roo-Code
$GIT clone --depth 1 --single-branch https://github.com/Aider-AI/aider.git      $BASE/aider
$GIT clone --depth 1 --single-branch https://github.com/modelcontextprotocol/python-sdk.git $BASE/mcp-python-sdk

# 2) star 数（近似值，shields.io 端点）
curl -s "https://img.shields.io/github/stars/openai/codex.json"

# 3) 复核本报告引用的源码位置（逐条）
rg -n "parallel_execution|supports_parallel" $BASE/openai-codex/codex-rs/core/src/tools/parallel.rs
rg -n "FuturesOrdered|in_flight"             $BASE/openai-codex/codex-rs/core/src/session/turn.rs
rg -n "COMPACT_USER_MESSAGE_MAX_TOKENS"      $BASE/openai-codex/codex-rs/core/src/compact.rs
rg -n "Deep-truncates|truncateMiddleByChars" $BASE/cline/sdk/packages/core/src/session/services/message-builder.ts
rg -n "PRUNE_MINIMUM|PRUNE_PROTECT"          $BASE/sst-opencode/packages/opencode/src/session/compaction.ts
rg -n "failToolCall|toolName.toLowerCase"    $BASE/sst-opencode/packages/opencode/src/session/processor.ts $BASE/sst-opencode/packages/opencode/src/session/llm.ts
rg -n "find_similar_lines|Did you mean"      $BASE/aider/aider/coders/editblock_coder.py
rg -n "max_reflections|reflected_message"    $BASE/aider/aider/coders/base_coder.py
rg -n "condenseContext|flushPendingToolResultsToHistory" $BASE/Roo-Code/src/core/task/Task.ts
rg -n "consecutiveMistakes|buildMistakeLimitStopMessage" $BASE/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts
rg -n "async def call_tool|async def list_tools" $BASE/mcp-python-sdk/src/mcp/client/session.py
```

---

## 9. 未完成项与风险（如实）

- `anthropics/claude-code` **无公开源码**（闭源分发），本报告**未对其下任何结论**；
  `anthropics/anthropic-cookbook`、`microsoft/autogen`、`langchain-ai/langgraph`
  **本轮未 clone**（6 席已满，且优先级低于已覆盖的 6 个），**本报告不对它们下结论**。
  任务信要求「至少覆盖 6 个」，实际覆盖 **6/6**，达标。
- `cline/cline` 仓库已重构（`src/core/task/index.ts` 不复存在，现为 `apps/` + `sdk/packages/core`），
  任务信按老结构给的路径**已失效**；本报告改用现结构并已注明。
- 行号为 2026-09-21 拉取时的 `--depth 1` 快照行号，上游若改动会漂移；
  复核请用第 8 节的关键字 `rg` 命令（按符号名定位，不按行号）。
- star 数取自 shields.io 近似端点，**只作量级参考**。
