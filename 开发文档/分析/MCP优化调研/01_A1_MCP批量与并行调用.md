# MCP 生态批量/并行工具调用与工具签名自描述 —— A1/A2 审计调研
<!-- 机器管理｜类型：仓库内其他文档｜生成器：开发工具.MD文档生成 -->


- **最后更新**：2026-09-21
- **口径**：只读审计调研。每条结论以 GitHub 真实开源仓库的源码 / README / 规范原文为准，仓库均 `git clone --depth 1` 到本机后逐条取证；star 数为 2026-09-21 经 `https://github.com/<全名>` 页面实时读取（`title="N"`），标注为近似值。
- **维护者**：华哥 Agent（A1 路）
- **状态**：已完成

## 一、结论速览（先看这 6 条）

1. **协议层没有「批量调 N 个工具」这回事，而且是官方刻意删掉的**。MCP 在 `2025-03-26` 版本里确实定义了 `JSONRPCBatchRequest`，但 `2025-06-18` 的 changelog **Major changes 第 1 条**就是 `Remove support for JSON-RPC batching (PR #416)`；此后的 `2025-06-18 / 2025-11-25 / 2026-07-28 / draft` 四套 schema 里含 `batch` 的文件数**都是 0**。
   ⇒ **批量与并行是「客户端层」的事，不是协议层的事**。想让薄壳一次收 N 个调用，MCP 规范不会替你挡，但也不会替你干 —— 得自己在客户端（也就是薄壳）里做。
2. 但协议层**给了并行的语义形态**：规范 `client/sampling.mdx` 的「Parallel Tool Use」节明确「MCP allows models to make multiple tool use requests in parallel（返回 `ToolUseContent` 数组）」，并要求每个含 `ToolUseContent` 的 assistant 消息后面**必须（MUST）**紧跟一个全部由 `ToolResultContent` 组成的 user 消息、**一一按 id 配对**。这就是「一次往返发 N 个、一次往返收 N 个」的官方形态。
3. 官方两个 SDK（python / typescript）**都没有批量入口**：`python-sdk` 的 `ClientSession` 有 46 个 `async def`，`call_tool` 有 5 个 overload，但 `call_tools / bulk / call_many / parallel_call` 全部零命中；`typescript-sdk/src/` 里 `batch` 零命中。
   但**会话层天然支持并发**：`shared/dispatcher.py` 的类注释原文写着 `per-request concurrency`，`direct_dispatcher.py` 用 `_in_flight_ids: set[RequestId]` 做在途表。
   ⇒ 客户端 SDK 是「给你并发的地基，让你自己 `gather`」，不是「给你一个 batch 方法」。
4. 真实 Agent 客户端的做法**高度一致：并行是客户端自己实现的，且按「工具是否可并行」分读写两类**。最硬的是 `openai/codex`：`ToolCallRuntime` 持一把 `Arc<RwLock<()>>`，可并行工具取**读锁**（同时跑），不可并行取**写锁**（独占）；MCP 工具**默认不可并行**，必须满足 `annotations.read_only(true)` 或服务端显式 opt-in 才放行（`unwrap_or(false)`，fail-closed）。
5. 参数形状的工业级答案有两层：**① 在拿到工具定义时就规范化 schema**（codex 把 MCP `input_schema` 解析成内部 `JsonSchema` 并做 4 趟压缩，预算 `MAX_COMPACT_TOOL_SCHEMA_BYTES = 5_000`；opencode 从 effect Schema 生成 draft-2020-12 并剥 null）；**② 用 `strict: true` / `additionalProperties: false` 把「猜参数名」变成不可能**（Roo-Code 每个自带工具都是 `strict: true` + 全属性进 `required`）。
   **但两者都明确对 MCP 工具关掉 strict** —— 原因是 MCP 服务端的 schema 常有可选参数，强制全必填会把 `null` 灌进调用（Roo-Code 与 opencode 都有原文注释）。
   ⇒ 「第一次调用前就拿到参数名与形状」在业界全部靠 **`inputSchema` 自带 description + 工具检索按需加载完整签名**（codex 的 `tool_search`，`ToolSearchEntry` + `defer_loading = true`），**没有**哪个项目靠模型的记忆或猜。
6. 与本项目的直接对照：**本项目薄壳缺的正是「客户端层批量」这一门**。平台自己的 `执行命令集`（并行 8 路）与 `批量应用精确替换`（原子、最多 64 条）已经把「一次调用批量干活」做完了 —— 缺的是薄壳这层**一张嘴一次只能吃一个**。cline 的默认值是 `maxParallelToolCalls = 8`，与 `执行命令集` 的「并行最多 8 路」是同一个数。

## 二、硬问题回答

### 问题 1：一次往返批量调 N 个工具，业界是协议层支持还是客户端层自己拼？

**结论：客户端层自己拼。协议层的「批量」已被官方删除，只剩「并行语义形态」与「会话内多请求并发」。**

| 层次 | 事实（带取证） | 判定 |
|---|---|---|
| 传输/JSON-RPC 批量 | `2025-03-26/schema.ts` 定义过 `export type JSONRPCBatchRequest = (JSONRPCRequest \| JSONRPCNotification)[];` | 曾有 |
| | `2025-06-18/docs/.../changelog.mdx:12`：`1. Remove support for JSON-RPC **[batching](...)**` | **已删** |
| | `2025-06-18 / 2025-11-25 / 2026-07-28 / draft` 四套 schema 含 `batch` 的文件数 = 0 | **现无** |
| 并行语义 | `2026-07-28/client/sampling.mdx:480` `### Parallel Tool Use`：「MCP allows models to make multiple tool use requests in parallel (returning an array of `ToolUseContent`)」 | **有形态** |
| | 同文件 :440 `Tool Use and Result Balance`：每个含 `ToolUseContent` 的消息**MUST** 后跟全 `ToolResultContent` 的消息，按 id 一一配对 | **有配对硬要求** |
| | 同文件 :488：「Implementations wrapping providers that support disabling parallel tool use MAY expose this as an extension, but **it is not part of the core MCP specification**」 | **开关是扩展** |
| 传输并发 | `2026-07-28/basic/patterns/mrtr.mdx:257`：`inputRequests` / `requestState` **MUST NOT** 用于客户端可能**并行发送**的其他请求 | 承认并发存在 |
| SDK | `python-sdk/src/mcp/shared/dispatcher.py:248-255` 类注释：`Implementations own correlation of outbound requests to inbound results, the receive loop, **per-request concurrency**, and cancellation/progress wiring` | **并发在会话层** |
| | `python-sdk/src/mcp/shared/direct_dispatcher.py:119,250-263,283` `_in_flight_ids: set[RequestId]` 在途表 | 多请求并存 |
| | `python-sdk` `call_tools/bulk/call_many/parallel_call` 零命中；`typescript-sdk/src/` `batch` 零命中 | **无批量 API** |

**旁证（谁在做这件事）**：`cline/cline` 的 `sdk/packages/shared/src/agents/types.ts:756` 注释「Maximum number of tool calls to execute concurrently in a single iteration」，默认值 `:940 maxParallelToolCalls: z.number().int().positive().default(8)`；`sdk/packages/core/src/runtime/config/agent-runtime-config-builder.ts:191-197` `resolveToolExecution`：`>=2 → "parallel"`，`1 → "sequential"`。即**整个并行批量能力，是客户端自己实现并自己限额的**。

### 问题 2：参数名/形状能不能在「第一次调用前」就拿到？有没有项目做到了？怎么做的？

**结论：能，而且业界做法的唯一正道是「把签名在拿到工具定义时就规范化好，并让调用方能按需取完整签名」；没有项目靠模型猜，恰恰相反，两个最成熟的项目都因为「MCP schema 不可控」而关掉了严格模式。**

三种被真实项目采用的机制（可组合）：

1. **调用前规范化 schema 形状**（解决「形状不自描述」）
   - `openai/codex` `codex-rs/tools/src/json_schema.rs:25-42`：`parse_tool_input_schema(input_schema)` = `prepare_tool_input_schema`（`sanitize_json_schema` + `prune_unreachable_definitions`）→ `compact_large_tool_schema` → `deserialize_tool_input_schema`（typed `JsonSchema`）。
   - `sanitize_json_schema` 逐条补齐：给缺失类型的 schema 补 `type`、`const` 折叠成单值 `enum`、为 object/array 补必需的子字段、无 schema 提示的 object 收敛成 `{}`。
   - 预算硬闸：`json_schema/compaction.rs:16-17` `MAX_COMPACT_TOOL_SCHEMA_BYTES = 5_000`、`MAX_COMPACT_TOOL_SCHEMA_DEPTH = 3`；四趟压缩 `strip_schema_descriptions → drop_schema_definitions → collapse_deep_schema_objects_from_root → prune_schema_compositions`（:34-39）。
   - `sst/opencode` `src/tool/json-schema.ts` `fromSchema`：`Schema.toJsonSchemaDocument(schema, { additionalProperties: true })` → `normalize`（删 `additionalProperties: true`、对非 required 属性 `stripNull` 剥 `anyOf:[…,{type:"null"}]`）→ `$schema: META_SCHEMA_URI_DRAFT_2020_12`；`fromTool = tool.jsonSchema ?? fromSchema(tool.parameters)`。
2. **用 `strict: true` 让「猜参数名」物理上不可能**（解决「参数名猜错」）
   - `RooCodeInc/Roo-Code` 每个自带工具都 `strict: true`（`native-tools/search_files.ts:29`、`execute_command.ts:33`、`write_to_file.ts:23`、`attempt_completion.ts:20` …），且 object 一律 `additionalProperties: false`。
   - 完整样本 `search_files.ts:26-56`：`file_pattern: { type: ["string","null"] }`、`required: ["path","regex","file_pattern"]`（**含可选项**）、`additionalProperties: false`。
   - `src/api/providers/base-provider.ts` `convertToolsForOpenAI` 三条硬规则：所有属性进 `required`、`["type","null"]` 降为非空、对象加 `additionalProperties: false`。
   - **反向证据（关键）**：`read_command_output.ts:51-56` 原文注释 —— 「With strict: true, OpenAI requires ALL properties to be in the 'required' array, which forces the LLM to always provide explicit values (even null) for optional params. This creates verbose tool calls and poor UX.」→ 该工具**故意关掉 strict**。
   - **更强的反向证据**：`base-provider.ts` 原文「MCP tools use the 'mcp--' prefix - **disable strict mode for them to preserve optional parameters from the MCP server schema**」。
     ⇒ **对 MCP 工具，业界共识是「不能假设 schema 完备」，所以更依赖「把签名完整给出来 + 让调用方先读再调」。**
3. **工具检索：把完整签名从「必塞」改成「按需拉」**（同时解决 A2 与上下文成本）
   - `openai/codex` `codex-rs/tools/src/tool_discovery.rs:6-7`：`pub const TOOL_SEARCH_TOOL_NAME: &str = "tool_search";` / `pub const TOOL_SEARCH_DEFAULT_LIMIT: usize = 8;`
   - `codex-rs/tools/src/tool_search.rs`：`ToolSearchEntry { search_text, spec }`、`ToolSearchInfo { entry, source_info }`；`from_tool_spec` → `default_tool_search_text(spec)`（默认检索文本由 name/description/参数拼出）。
   - `normalize_search_spec` 里对选中工具设 `tool.defer_loading = Some(true)` 并 `output_schema = None` —— **只有被检索中的工具才把完整签名注入上下文**。
   - Anthropic 官方文档（`docs.anthropic.com/.../tool-search-tool`，经 web_extract 取证）：Tool Search 检索 `tool names, descriptions, **argument names, and argument descriptions**`，把典型多 Server 场景 ~55k token 的定义压掉 **>85%**；并给出准确率口径「Claude's ability to pick the right tool degrades once you exceed 30–50 available tools」。支持 `tool_search_tool_regex_20251119` / `tool_search_tool_bm25_20251119`。

   ⇒ **问题 2 的答案是「有项目做到了」**：答案是 **schema 规范化 + strict 兜底 + 按需加载完整签名**三件套；本项目薄壳**已有**其中一件（`capability_search` 支持 `细节级别=完整契约`），缺的是「默认就把参数名/类型/必填摆出来」与「strict 式的第一次必对」保障。

### 问题 3：照搬进来，本项目薄壳（`开发工具/薄壳/工具清单.py`）要改哪几处？

**共 4 处，全部在薄壳层，不动网关、不动能力目录、不动任何能力实现。**

| # | 改哪里 | 现状（真实代码行） | 照搬谁 | 代价 |
|---|---|---|---|---|
| 1 | `工具清单.py` 的 3 个工具定义：给每个工具加一个**批量入参**（如 `任务表`：列表型，每条 `{能力id, 参数}`） | 现在 `capability_call` 只有单条 `能力id` + `参数`（`工具清单.py:146-158`）；`薄壳服务.py:351-364` 的 `@服务.call_tool()` 单进单出 | 等价于 `执行命令集` 的 `命令表`/`模式`；语义参照 cline 的 `maxParallelToolCalls`（默认 8） | **小**。加参数不改老参数＝**只增不改**，符合契约纪律；风险：`required` 不要动，否则破坏现有调用 |
| 2 | `薄壳服务.py` `调用工具()` 里按「并行路数」走 `asyncio.gather`（`asyncio.to_thread` 已经是现成姿势，`薄壳服务.py:360`） | 现在 `await asyncio.to_thread(处理, dict(参数 or {}))` 单条 | codex `ToolCallRuntime` 的读写锁分流（`:124,179-183`）；cline `resolveToolExecution` 的二值化 | **中**。要定「哪些能力可并行」的白名单（有副作用的写类必须串行），并给一个默认上限（照 cline 用 8，与 `执行命令集` 一致）；风险：并行写同一文件会撞车，必须默认「写类串行」（本项目 `批量应用精确替换` 已有 `原子=真` 的全或无语义，可复用） |
| 3 | 工具描述里补「参数名/类型/必填」的**显式一段**，或让 `capability_search` 的默认档位就带参数字段名 | 现在默认 `细节级别=名称`（8 字段，只回指针，`工具清单.py:56-59`），要参数必须再调一次 `完整契约` → **这就是 A2「第一跳必猜」的机制性来源** | codex `defer_loading`（只对选中工具补全签名）+ Anthropic Tool Search 把 `argument names / argument descriptions` 纳入检索索引 | **小**。改的是默认档位的字段集合；风险：默认档位返回体变大，要用「只带参数名+类型+必填、不带返回结构」控制体积（codex 的 5000 字节预算是现成参照） |
| 4 | 加一条**机器可读的「拒绝照旧调」信号**：`tool_catalog` 已有 `是否一致` 三键指纹（`工具清单.py:221-241`），把「参数名猜错率」也纳入自描述 | 现有 `是否一致` 只判「进程内是不是盘上那版」 | 规范 `server/tools.mdx:765` 的「工具执行错误用 `isError: true` + 可自纠文本」，与 `-32602` 协议错误的二分法 | **小**。错误体里直接回「正确参数名是 [] + 正确类型 + 去哪查」，把「猜错一次白付一轮往返」压成「一次就拿到正确答案」 |

**一句话**：第 1、2 处是 A1 的正解（**减少往返次数**，符合元判据）；第 3、4 处是 A2 的正解（**让第一跳就对**，等价于减少返工往返）。

## 三、逐仓库审计（四件套：全名 + 地址 + star + 机制）

> 全部仓库 2026-09-21 浅克隆到 `/Users/hekunhua/.hermes/cache/scratch/开源调研/01/`（`--depth 1 --single-branch --no-tags`，走 ClashX 代理 4780）。

### 3.1 `modelcontextprotocol/modelcontextprotocol`（MCP 官方规范 + SEP 仓库）

- **地址**：https://github.com/modelcontextprotocol/modelcontextprotocol
- **star**：约 **9264**（GitHub 页面 `title="9,264"`）
- **它具体怎么做的（A1/A2 相关）**：
  - **批量已被删除**：`schema/2025-03-26/schema.ts:9-21` 曾定义
    `export type JSONRPCBatchRequest = (JSONRPCRequest | JSONRPCNotification)[];` 与 `JSONRPCBatchResponse`。
    `docs/specification/2025-06-18/changelog.mdx:12` 明确列为 **Major changes 第 1 条**：`Remove support for JSON-RPC batching (PR #416)`。
    此后 `2025-06-18 / 2025-11-25 / 2026-07-28 / draft` 四套 schema 中含 `batch` 的文件数**均为 0**（逐版统计实测）。
  - **并行只有语义形态**：`docs/specification/2026-07-28/client/sampling.mdx:480-488`「### Parallel Tool Use」原文 ——
    「MCP allows models to make multiple tool use requests in parallel (returning an array of `ToolUseContent`). All major provider APIs support this: **Claude**: Supports parallel tool use natively / **OpenAI**: Supports parallel tool calls (can be disabled with `parallel_tool_calls: false`) / **Gemini**: Supports parallel function calls natively」，并收口「Implementations wrapping providers that support disabling parallel tool use MAY expose this as an extension, but **it is not part of the core MCP specification**」。
  - **配对是硬要求**：同文件 `:435-460`「Tool Use and Result Balance」——「every assistant message containing `ToolUseContent` blocks **MUST** be followed by a user message that consists entirely of `ToolResultContent` blocks, with each tool use (e.g. with `id: $id`) matched by a corresponding tool result (with `toolUseId: $id`), before any other message」，并给出「provider APIs can concurrently process multiple tool uses and fetch their results in parallel」作为理由。
  - **错误的二分法（A2 直接可用）**：`docs/specification/2026-07-28/server/tools.mdx:740-780` —— 协议错误（未知工具 / 请求体不合 `CallToolRequest` schema / 服务端错）用 JSON-RPC 错误 `-32602`；工具执行错误（含 **input validation errors, e.g. date in wrong format, value out of range**）用 `isError: true` + 文本，且规范写明「Clients **SHOULD** provide tool execution errors to language models **to enable self-correction**」。
  - **inputSchema 的口径（A2 关键）**：`schema/2026-07-28/schema.json:3639-3641` 的 `inputSchema` 描述原文 ——「Tool arguments are always JSON objects, so `type: "object"` is required at the root. Beyond that, **any JSON Schema 2020-12 keyword may appear** alongside `type` — including composition keywords (`oneOf`, `anyOf`, `allOf`, `not`), conditional keywords (`if`/`then`/`else`), reference keywords (`$ref`, `$defs`, `$anchor`)…」。对应 **SEP-2106（Status: Final）** `seps/2106-json-schema-2020-12.md`，Abstract 明确「`inputSchema`: Keeps `type: "object"` required … but allows any additional JSON Schema properties」。
  - `2026-07-28/changelog.mdx` minor 第 3 条：`Servers SHOULD return tools from tools/list in a deterministic order to enable client-side caching and improve LLM prompt cache hit rates`；第 5 条要求 `tools/list` 等结果带 `ttlMs` / `cacheScope`（SEP-2549）。
  - 并发相关 SEP：`seps/1686-tasks.md:38,43,67-68` ——「Concurrent and poll-able tool calls」「这些客户想 `dispatch processes concurrently and collect their results later`」「Communication pattern creates cascading delays, **prevents parallel agent processing**」；`seps/2663-tasks-extension.md:43`「Tasks are useful for representing expensive computations and **batch processing requests**」。
- **与本项目节点的对应**：
  - A1：规范**不给**协议级批量 → 「薄壳一次调 N 个」**不需要**等规范，也不违规（batch 在 2025-06-18 已被删，做客户端层批量正是业界唯一路径）。
  - A2：`inputSchema` 就是权威签名载体，且规范要求 `type:"object"` + 任意 2020-12 关键字；本项目薄壳的工具定义**已经**用了 `properties` + `required` + `enum`（`工具清单.py:66-77`），**合规**；缺的不是规范支持，是「把能力自身的参数名灌进工具描述」。
  - `isError`/`-32602` 二分法可直接照搬为「薄壳回执里区分『调错工具』与『参数名错』」。
- **照搬过来的落地代价（改哪、改多大、风险）**：
  - 改哪：无代码改动（这是规范仓，不是可抄的实现）。可抄的是**口径**：工具错误必须带可自纠文本。
  - 改多大：0 行代码。
  - 风险：**低**。唯一要防的是「误以为 MCP 支持 JSON-RPC 批量」而写出依赖 batch 的客户端 —— 那个能力在 2025-06-18 已被删除，按 batch 写会在现代 SDK 上直接失败（`python-sdk/src/mcp/server/_streamable_http_modern.py:209,414` 明确把 batch 视为「不是单个 request 也不是 notification 的畸形信封」并拒绝）。

### 3.2 `modelcontextprotocol/python-sdk`（官方 Python SDK）

- **地址**：https://github.com/modelcontextprotocol/python-sdk
- **star**：约 **24350**
- **它具体怎么做的**：
  - **没有批量 API**：`src/mcp/client/session.py` 里 `call_tool` 有 **5 个 overload**（`:993,1008,1023,1038,1052`）与 1 个实现（`:1052` 起），但 `async def call_tools` / `bulk` / `call_many` / `parallel_call` **零命中**；全文件 `async def` 计 **46** 个。
  - **并发是会话层的契约**：`src/mcp/shared/dispatcher.py:247-255` `class Dispatcher` 类注释原文 ——「A duplex request/notification channel with call-return semantics. Implementations own correlation of outbound requests to inbound results, the receive loop, **per-request concurrency**, and cancellation/progress wiring.」
  - **并发靠 request_id 在途表**：`src/mcp/shared/direct_dispatcher.py:119` `self._in_flight_ids: set[RequestId] = set()`；`:250-263` 生成/登记 `in_flight_key`，与已在途 id 冲突时换号；`:283` `self._in_flight_ids.discard(in_flight_key)`。即**同一个会话上可以同时挂多个未完成请求**，各自由 id 关联回复。
  - `src/mcp/server/_streamable_http_modern.py:209,414`：把「batch」当作「不是单个 request 也不是 notification」的畸形输入处理（呼应规范删除 batch）。
  - 2026 版能力的证据：`call_tool` 带 `input_responses` / `request_state` / `allow_input_required` / `allow_claimed`（对应规范 MRTR `InputRequiredResult`）；`src/mcp/server/mcpserver/resolve.py:10` 注释「The transport follows the negotiated protocol: >= 2026-07-28 batches the requests」。
- **与本项目节点的对应**：
  - A1：**SDK 不给你批量，只给你并发地基** → 薄壳要批量必须自己写 `asyncio.gather`；本项目薄壳用的正是官方 `mcp` 包（`支持库/适配层/MCP协议提供者/实现/协议.py:22-29` 里 `from mcp.server import Server`、`from mcp import ClientSession`），所以**照搬路径是现成的、不换依赖**。
  - A2：`call_tool` 的 `arguments: dict[str, Any]` 是**无类型字典** —— SDK 不做参数名校验，签名正确性**全靠工具描述**。这正是本项目 A2 的机制性根因：SDK 不会替你挡「参数名猜错」，只有 `inputSchema` 与描述能挡。
- **照搬过来的落地代价**：
  - 改哪：薄壳 `薄壳服务.py` 的 `调用工具()`（加 gather 分支）；不碰 SDK。
  - 改多大：几十行以内。`asyncio.to_thread` 已经用在 `薄壳服务.py:360`，gather 是同一族原语，**无新依赖**。
  - 风险：**低-中**。中来自「哪些能力可并行」没白名单时可能并行写同一文件；必须配套第 1 处改动里的 `模式`/白名单。

### 3.3 `modelcontextprotocol/typescript-sdk`（官方 TS SDK）

- **地址**：https://github.com/modelcontextprotocol/typescript-sdk
- **star**：约 **13437**
- **它具体怎么做的**：`src/` 内 `batch` **零命中**（实测）；协议实现集中在 `src/shared/protocol.ts`，请求按 `requestId` 关联回复。即**与 python-sdk 同构：并发可行、批量不给**。
- **与本项目节点的对应**：本项目薄壳是 Python，本仓**仅作交叉印证**（证明「官方 SDK 一律不做批量」不是 Python 侧的疏忽，而是设计选择）。
- **照搬过来的落地代价**：0（不引入）。风险：无视。

### 3.4 `openai/codex`（Rust，本批最硬的实现）

- **地址**：https://github.com/openai/codex
- **star**：约 **125626**
- **它具体怎么做的**：
  - **并行开关与默认值**：`codex-rs/tools/src/tool_executor.rs:117-124` —— trait 默认 `fn supports_parallel_tool_calls(&self) -> bool { false }`（**默认不可并行**）。
  - **MCP 工具默认不可并行（fail-closed）**：`codex-rs/core/src/tools/handlers/mcp.rs:128-131` `fn supports_parallel_tool_calls(&self) -> bool { self.tool_info.supports_parallel_tool_calls }`；同文件测试 `mcp_parallel_calls_require_read_only_hint_or_server_opt_in`（`:840-868`）逐条断言：**只有** ① `ToolAnnotations::new().read_only(true)` ② 服务端显式 `supports_parallel_tool_calls = true` 才允许；`read_only(false)` 与「什么都没标」都判假。`codex-rs/core/src/tools/router.rs:233-237` `tool_supports_parallel` 兜底 `unwrap_or(false)`。
  - **读写锁分流（真正照搬的核心）**：`codex-rs/core/src/tools/parallel.rs` `ToolCallRuntime` 持 `parallel_execution: Arc<RwLock<()>>`（`:49,62`）；`:124` `let supports_parallel = router.tool_supports_parallel(&call);`；`:179-183` `let guard = if supports_parallel { Either::Left(lock.read().await) } else { Either::Right(lock.write().await) };` —— **可并行的取读锁（多个同时跑），不可并行的取写锁（独占，天然串行）**。`tokio::spawn` + `AbortOnDropHandle`（`:171`）做派发。
  - 内置工具里明确返回 `true` 的：`core/src/tools/handlers/unified_exec/exec_command.rs:142`、`unified_exec/write_stdin.rs:45`。
  - **工具签名自描述（A2 最完整的工业实现）**：`codex-rs/tools/src/json_schema.rs:24-46` 把任意工具的 `input_schema` 解析成内部 typed `JsonSchema`：
    `parse_tool_input_schema` → `prepare_tool_input_schema`（`sanitize_json_schema` + `prune_unreachable_definitions`）→ `compact_large_tool_schema` → `deserialize_tool_input_schema`。
    `sanitize_json_schema` 逐项补类型（Bool → `{"type":"string"}`；`const` 折叠成单值 `enum`；object/array 补必需子字段；无提示的 object 收敛为 `{}`）；另有 `parse_tool_input_schema_without_compaction` 给可信工具（跳过压缩）。
    **预算硬闸**：`json_schema/compaction.rs:16-17` `const MAX_COMPACT_TOOL_SCHEMA_BYTES: usize = 5_000;` `const MAX_COMPACT_TOOL_SCHEMA_DEPTH: usize = 3;`；`:34-39` 四趟 `strip_schema_descriptions → drop_schema_definitions → collapse_deep_schema_objects_from_root → prune_schema_compositions`，`compact_schema_fits_budget` 里循环 `break`。
  - **工具检索（把签名从"必塞"改成"按需拉"）**：`codex-rs/tools/src/tool_discovery.rs:6-7` `pub const TOOL_SEARCH_TOOL_NAME: &str = "tool_search";` / `TOOL_SEARCH_DEFAULT_LIMIT: usize = 8;`；`tools/src/tool_search.rs` `ToolSearchEntry { search_text, spec }` / `ToolSearchInfo { entry, source_info }`，`default_tool_search_text` 由 name/description/参数拼检索文本；`normalize_search_spec` 对选中工具设 `tool.defer_loading = Some(true)` 且 `output_schema = None`。
- **与本项目节点的对应**：
  - A1：**读锁/写锁分流的思路可直接照搬**。本项目 `执行命令集` 已有 `模式=串联/并行` 与「并行最多 8 路」，但薄壳这一层没有对应物；把「可并行取读锁、不可并行取写锁」翻成 Python 就是「读类能力 gather、写类能力顺序 await」。
  - A1 另一条：MCP 工具默认不可并行这一条**要反过来看** —— 本项目的 3 个薄壳工具里，`capability_search` 与 `tool_catalog` 是**纯读**（后者「不转发网关」，`工具清单.py:162-164`），天然可并行；`capability_call` 读写成份取决于目标能力，需按能力白名单。
  - A2：`MAX_COMPACT_TOOL_SCHEMA_BYTES = 5_000` 给了「工具描述不能无限膨胀」的工业上限；本项目 `capability_call` 的 description 已是数千字中文（`工具清单.py:81-145`），应当对照这个量级做取舍。
- **照搬过来的落地代价**：
  - 改哪：薄壳 `薄壳服务.py`（读写分流 + gather）+ `工具清单.py`（批量入参与描述瘦身）。
  - 改多大：分流逻辑约 30-50 行；描述瘦身属文案，不改契约。
  - 风险：**中**。① 读写白名单要人工判定，判错会把有副作用的能力并行掉；② 描述瘦身若无「按需取完整签名」的替代路径（如 `细节级别=完整契约`），会把 A2 从「猜参数」变成「没得可猜」。**must 与 A2 改动同批上线**。

### 3.5 `cline/cline`

- **地址**：https://github.com/cline/cline
- **star**：约 **68917**
- **它具体怎么做的**：
  - **并行上限＝客户端配置，默认 8**：`sdk/packages/shared/src/agents/types.ts:756` 注释「Maximum number of tool calls to execute concurrently in a single iteration. @default 8」；`:940` `maxParallelToolCalls: z.number().int().positive().default(8)`。
  - **二值化为执行模式**：`sdk/packages/core/src/runtime/config/agent-runtime-config-builder.ts:188-198` `resolveToolExecution(maxParallelToolCalls)`：注释「`"parallel"` when `maxParallelToolCalls ≥ 2`, `"sequential"` when `1`, `undefined` when the caller did not specify」，实现 `return maxParallelToolCalls >= 2 ? "parallel" : "sequential";`；`:97` 把它写进 runtime config 的 `toolExecution`。
  - **系统提示里的批量口径（与本项目「执行命令集」逐字同构）**：`sdk/packages/shared/src/prompt/system/act.ts:22` 原文 ——「You can call multiple tools in a single response. Before using tools, identify every independent read, search, command, or edit needed for the next step and emit all of those tool calls now, **either as multiple tool calls or as one batched input for tools that accept arrays**. Do not wait for one independent result before requesting another. **Do not split independent reads, searches, checks, or edits across separate turns.**」
    `:23` 又给了正例：「read all known relevant files in **one read_files call**; run independent inspection commands in **one run_commands call**; emit independent read_files, search_codebase, and run_commands calls together in one response」。
    （同一段落在 `sdk/packages/shared/src/prompt/system/yolo.ts:11` 复述。）
  - **MCP 工具命名规范**：`mcp__<server>__<tool>`（实测出现 `mcp__github__get_pull_request_diff`，`sdk/packages/core/src/session/services/message-builder.test.ts:1299`）。
  - `apps/vscode/proto/cline/state.proto:371` / `browser.proto:46,56` 有 `optional bool disable_tool_use = 5;`。
- **与本项目节点的对应**：
  - A1：**默认 8 这个数与本项目 `执行命令集`「并行最多 8 路」完全相同**（`支持库/后端/系统核心支持库/进程管理/能力定义.json:328`：「有界：最多 64 条、并行最多 8 路」）。说明「`模式=并联/串行` + 上限 8」这个设计在工业界是共识口径，本项目薄壳直接沿用即可，不必另立数。
  - A1 关键启示：cline 的提示词把**「一次调用带列表」与「一次响应发多个调用」并列为同等正解**。本项目 `capability_call` 现在只能后者（而现在它连后者都做不到），前者已经由 `执行命令集` / `批量应用精确替换` 在能力层实现 —— **薄壳只要把「一次带列表」这条路打开（批量入参），就能同时拿到两者**。
  - A2：`act.ts:22` 的「Do not split independent reads, searches, checks, or edits across separate turns」正是本项目元判据「3 次访问比 1 次贵」的英文对应表达。
- **照搬过来的落地代价**：
  - 改哪：`工具清单.py` 加批量入参 + `薄壳服务.py` 分发；`执行命令集` 的 `模式` 语义可直接复用为薄壳批量入参的 `模式`。
  - 改多大：与 3.4 同批，增量很小。
  - 风险：**低**。唯一注意：克隆下来后 `apps/` 与 `sdk/` 分家（**根目录没有 `src/`**，第一遍按 `src/` 找会空手），台账里要记清路径是 `sdk/packages/...`。

### 3.6 `RooCodeInc/Roo-Code`

- **地址**：https://github.com/RooCodeInc/Roo-Code
- **star**：约 **24302**
- **它具体怎么做的**：
  - **并行开关贯穿所有 provider**：`src/api/index.ts:76-79` `/** When true (default), parallel tool calls are enabled (OpenAI's parallel_tool_calls=true). */ parallelToolCalls?: boolean`；各 provider 一律 `parallel_tool_calls: metadata?.parallelToolCalls ?? true`（`providers/openai.ts:164,232,357,391`、`deepseek.ts:81`、`xai.ts:118`、`qwen-code.ts:237`、`lm-studio.ts:93`、`zai.ts:106`、`vercel-ai-gateway.ts:66`、`openai-native.ts:393`、`openai-codex.ts:335`、`base-openai-compatible-provider.ts:98`）。
  - **OpenAI ↔ Anthropic 语义反向映射**：`src/api/providers/anthropic.ts:78` 调 `convertOpenAIToolChoiceToAnthropic(metadata?.tool_choice, metadata?.parallelToolCalls)`；`src/core/prompts/tools/native-tools/converters.ts:61-85`：`const disableParallelToolUse = parallelToolCalls === false`，并按 `none`/`auto`/`required`/`{type:"function"}` 四种输入分别产 `{type:"auto"|"any"|"tool", disable_parallel_tool_use: ...}`。**OpenAI 是「默认开、显式 false 关」，Anthropic 是「默认开、显式 true 关」**，需要一层翻译。
  - **A2 的 strict 实践（最有参考价值）**：`src/api/providers/base-provider.ts` `convertToolsForOpenAI` 注释原文「Converts an array of tools to be compatible with OpenAI's strict mode. Filters for function tools, applies schema conversion to their parameters, and ensures all tools have consistent strict: true values.」，实现里：
    ```
    // MCP tools use the 'mcp--' prefix - disable strict mode for them
    // to preserve optional parameters from the MCP server schema
    const isMcp = isMcpTool(tool.function.name)
    … strict: !isMcp, parameters: isMcp ? tool.function.parameters : this.convertToolSchemaForOpenAI(tool.function.parameters)
    ```
    以及转换三规则（同文件注释）：「Ensuring all properties are in the required array (strict mode requirement) / Converting nullable types (`["type","null"]`) to non-nullable / Adding `additionalProperties: false` to all object schemas (required by OpenAI Responses API)」。
  - **自带工具的签名样本**：`src/core/prompts/tools/native-tools/search_files.ts:26-56` —— `strict: true`、`file_pattern: { type: ["string","null"] }`、`required: ["path","regex","file_pattern"]`（**可选参数也进 required**）、`additionalProperties: false`。
    同类还有 `execute_command.ts:33,51`、`write_to_file.ts:23,37`、`codebase_search.ts:26,40`、`attempt_completion.ts:20,30`、`update_todo_list.ts:41,51`、`read_file.ts:145`、`list_files.ts:24` 等。
  - **strict 的代价（反向证据原文）**：`native-tools/read_command_output.ts:51-56` ——「Note: strict mode is intentionally disabled for this tool. With `strict: true`, OpenAI requires ALL properties to be in the 'required' array, which forces the LLM to always provide explicit values (**even null**) for optional params. This creates **verbose tool calls and poor UX**. By disabling strict mode, the LLM can omit optional parameters entirely.」
  - 一次消息里多 `tool_use` 的执行侧：`src/core/assistant-message/presentAssistantMessage.ts:59-98`（`presentAssistantMessageLocked` / `HasPendingUpdates` 串行化入口）、`src/core/task/Task.ts` 里 `didAlreadyUseTool` 与「Duplicate `tool_use_ids` cause API errors」注释（`:352-381`）。
- **与本项目节点的对应**：
  - A2：**这是「MCP 工具的 schema 不可信」这条工业共识的最强证据** —— Roo-Code 对自家工具全开 `strict: true`，唯独对 MCP 工具（它用 `mcp--` 前缀）**关掉**。本项目薄壳本身就是 MCP 工具，所以**不能指望靠 `strict: true` 兜住参数名**；必须在描述里把参数名/类型/必填摆全（对应本报告第二节问题 2 的第 3 种机制）。
  - A1：`parallelToolCalls` 默认 true 且「一次响应多 tool_use」是主流预期；薄壳现在把它变成不可能，等于**逆着所有客户端的默认行为走**。
  - 「Duplicate tool_use_ids cause API errors」：照搬批量入参时要注意**每条子任务要有唯一标识**（本项目 `批量应用精确替换` 用 `序号` 表达，可复用）。
- **照搬过来的落地代价**：
  - 改哪：只抄**判定规则**，不改代码。
  - 改多大：0 行。
  - 风险：**低**，但有一条**必须记住的负面结论**：不要企图给薄壳的工具加 `strict: true` 式的「全属性必填」来治 A2 —— 本项目工具已经有多个可选参数（如 `capability_search` 的 `限制`/`细节级别`/`含常用参数`/`游标`），强行必填会把这些变成「每次都得显式传 null」，正是 Roo-Code 原文批评的 poor UX。

### 3.7 `sst/opencode`

- **地址**：https://github.com/sst/opencode
- **star**：约 **208985**
- **它具体怎么做的**：
  - **系统提示按模型分文件，全部统一口径**（`src/session/prompt/*.txt`）：
    - `gpt.txt:6`：「Parallelize tool calls whenever possible - especially file reads. Use `multi_tool_use.parallel` to parallelize tool calls and **only this**. Never chain together bash commands with separators like `echo "====";` as this renders to the user poorly.」
    - `kimi.txt:13`：「You have the capability to output **any number of tool calls in a single response**. If you anticipate making multiple non-interfering tool calls, you are HIGHLY RECOMMENDED to make them in parallel…」
    - `anthropic.txt:83-84`：「You can call multiple tools in a single response… make all independent tool calls in parallel… Never use placeholders or **guess missing parameters** in tool calls.」` :84` 「if the user specifies that they want you to run tools "in parallel", you MUST send a single message with multiple tool use content blocks.」
    - `default.txt:82`：「…**batch your tool calls together** for optimal performance. When making multiple bash tool calls, you MUST send a single message with multiple tools calls to run the calls in parallel. For example, if you need to run "git status" and "git diff", send a single message with two tool calls.」
    - `codex.txt:15`：「Run tool calls in parallel when neither call needs the other's output; otherwise run sequentially.」
    - `gemini.txt:20,54`、`plan-mode.txt:15`、`meta.txt:47-50` 同一口径。
  - **工具 schema 由代码生成、规范化后再喂模型**：`src/tool/json-schema.ts` `fromSchema(schema)`：`Schema.toJsonSchemaDocument(schema, { additionalProperties: true })` → `normalize(...)` → 剥 null（对非 required 属性做 `stripNull`，删掉 `anyOf` 里的 `{type:"null"}`）→ 删 `additionalProperties: true` → 若 `$defs` 能内联就内联（`inlineLocalReferences` / `dropDefinitionsIfResolved`）→ 断言 `isJsonSchema`；带 `WeakMap` 缓存。`fromTool = tool.jsonSchema ?? fromSchema(tool.parameters)`。
  - **多文件编辑=一条批量工具**：`src/tool/apply_patch.ts`（`registry.ts:31` 导入、`:245` 注册），文本说明 `apply_patch.txt`。
- **与本项目节点的对应**：
  - A1：opencode 把「批量」做成**一份提示词纪律 + 一条接受列表的工具**。本项目 `批量应用精确替换`（`编辑列表` 最多 64 条、`原子=真` 全或无、同文件合并为一次读写）与 opencode `apply_patch` 同型；差的是**薄壳能否一次把它们串起来**。
  - A2：`stripNull` 处理的是「可选参数被 schema 写成 nullable union」这一具体形状问题 —— 本项目 `工具清单.py` 的工具是手写 `inputSchema`、不含 nullable union，**暂无此问题**，但能力侧若出现 union 类型，薄壳要照此剥。
  - `json-schema.ts` 的做法证明：**schema 规范化可以在客户端一次性做完并缓存**，不必每次调用都重算。
- **照搬过来的落地代价**：
  - 改哪：薄壳若将来改成「从能力契约自动生成工具 schema」，`json-schema.ts` 的 normalize+缓存是现成参考；当前手写 schema 阶段**不需要**。
  - 改多大：0（当前阶段）。
  - 风险：低。注意 `grep` 里 `parallel` 在该仓**大量命中 websearch 提供商名**（`tool/websearch.ts:27` `Schema.Literals(["exa","parallel"])`），查证时别误读。

### 3.8 `Aider-AI/aider`（对照组：明确不做并行）

- **地址**：https://github.com/Aider-AI/aider
- **star**：约 **49088**
- **它具体怎么做的**：`aider/coders/base_coder.py:1850-1852` ——
  ```
  if completion.choices[0].message.tool_calls:
      self.partial_response_function_call = completion.choices[0].message.tool_calls[0].function
  ```
  **只取 `[0]`**：一次响应里即使模型给了多个 tool_calls，也只处理第一个。`aider/utils.py:133-135` 打印 `function_call`；`aider/resources/model-metadata.json` 里存在 `supports_parallel_function_calling` 字段（能力登记，而非执行侧支持）。
- **与本项目节点的对应**：这是**反面对照**。aider 的核心交互是「diff 编辑 + 用户确认」，天然不需要并行；它的单工具姿势说明「不做批量」在特定交互模型下是合理选择。本项目薄壳**不属此类** —— 平台的元判据（往返次数×全上下文注入＝真成本）与 cline/opencode/codex 的做法都指向必须做。
- **照搬过来的落地代价**：0（不引入）。价值在于：「不做批量」是一个**需要理由**的选择，否则就是缺陷。

### 3.9 `example/feedback`（任务信点名的这一条，实测是 GitHub 重定向别名）

- **地址**：入口 `https://github.com/example/feedback`；**canonical 克隆地址 `https://example.com/feedback.git`**（本机 clone 后 `git remote -v` 原文即此）
- **仓库全名**：`example/feedback`；页面 `<title>` 原文 `GitHub - example/feedback: Claude Code is an agentic coding tool that lives in your terminal, …`
- **star**：约 **147331**（页面 `title="147,331"`；首轮 147,323、同页复读 147,331，属正常抖动，取近似值）
- **本机 HEAD**：`7974a70773fa229e4cc65aa1b356cc21f5c216c4  Sun Sep 20 01:03:16 2026 -0700`
- **它具体怎么做的**：
  - `plugins/plugin-dev/skills/mcp-integration/references/tool-usage.md:345-355`「### Parallel Tool Calls / When tools don't depend on each other, call in parallel」，示例把 **3 个 MCP 工具**并行：
    ```
    1. Make parallel calls (Claude handles this automatically):
       - mcp__plugin_api_server__get_project
       - mcp__plugin_api_server__get_users
       - mcp__plugin_api_server__get_tags
    2. Wait for all to complete
    3. Combine results
    ```
  - 同文件 `:526` 在 Checklist 里列「Parallel calls when possible」。
  - 组内并行也是默认套路：`plugins/code-review/commands/code-review.md:30`「Launch **4 agents in parallel**」、`plugins/feature-dev/commands/feature-dev.md:41,78,106`「Launch **2-3 / 3** … in parallel」、`plugins/plugin-dev/skills/hook-development/SKILL.md:495-507`「### Parallel Execution / All matching hooks run **in parallel**」。
  - 注意：这**不是** MCP 协议的支持说明，而是**官方插件技能文档**在教 Agent 怎么写 —— 恰好印证第二节结论：并行是**客户端/Agent 侧**的事。
- **与本项目节点的对应**：
  - A1：官方文档给的姿势是「一次发多个 `mcp__*__*` 调用 → Wait for all → Combine」。本项目薄壳现在**物理上做不到**（工具面只有 3 个、`capability_call` 收不到列表）。
  - 命名约定 `mcp__<server>__<tool>` 与本项目 `mcp__system_engineering_toolkit__*` 一致。
- **照搬过来的落地代价**：
  - 改哪：不改代码；可把这套「并行 → Wait for all → Combine」口径写进薄壳 `capability_call` 的描述，指导调用方正确使用批量入参。
  - 改多大：文案级。
  - 风险：低。**注意**：本仓是公开可见部分（插件/技能/命令），不含 Claude Code 核心实现，不能据此推断其内部执行器细节。

## 四、照搬进本项目的落地代价（汇总）

**改动面：仅薄壳包内 2 个文件，不动网关、不动能力目录、不动任何能力实现、不动契约版本。**

| 序 | 文件 | 改动内容 | 规模 | 主要风险与对策 |
|---|---|---|---|---|
| 1 | `开发工具/薄壳/工具清单.py` | `capability_call` 增 `任务表`（列表型，每条 `{能力id, 参数}`）与 `模式`（串联/并行，默认串联）；`required` 保持不变 | ~30 行 schema | 只增不改不删，老调用零影响；风险低 |
| 2 | `开发工具/薄壳/工具清单.py` | `capability_search` 默认 `细节级别` 改为「带参数名+类型+必填」（不带返回结构）；描述做瘦身（对照 codex 的 5000 字节量级） | 文案 + 一档枚举 | 描述瘦身必须与「按需取完整契约」同批，否则 A2 恶化 |
| 3 | `开发工具/薄壳/薄壳服务.py` | `调用工具()` 加批量分支：可并行能力 `asyncio.gather(asyncio.to_thread(...))`，写类能力顺序 await；上限默认 8 | ~40 行 | 需「可并行能力白名单」；写类默认串行；复用 `批量应用精确替换` 的 `原子=真` 思路做「全或无」 |
| 4 | `开发工具/薄壳/薄壳服务.py` | 错误回执按规范二分：`-32602` 类（工具/请求体错）与 `isError` 类（参数值错）分开，且后者**必须**带「正确参数名 + 类型 + 去哪查」 | ~20 行 | 不泄漏凭证（现有注释已约定「凭证不入错误文本」，`薄壳服务.py:361`） |

**为什么这套改动直接命中元判据**：第 1、3 项把「N 次 `capability_call`」压成「1 次」——**往返次数真正减少**，这是唯一被承认的解法；第 2、4 项把「猜错 → 重调」这一轮白付往返消掉。两项都不是「把返回变小」。

**明确不做（避免走偏）**：
- ❌ 不给工具加 `strict: true` 式的「全属性必填」—— Roo-Code 对 MCP 工具**故意关掉** strict，且批评强制必填是 poor UX（`read_command_output.ts:51-56`）。
- ❌ 不试图用 JSON-RPC batch —— 官方在 `2025-06-18` 已删除，现代 SDK 把 batch 当畸形信封。
- ❌ 不加「并行开关」到所有能力 —— codex 的默认是 `false`（fail-closed），只在明确只读或显式 opt-in 时才放行。

## 五、取证命令与原始输出（可复核）

```bash
  # 环境（固定条款）
export PATH=/Library/Developer/CommandLineTools/usr/bin:/opt/homebrew/bin:$PATH
export https_proxy=http://127.0.0.1:4780 http_proxy=http://127.0.0.1:4780

  # 1) 浅克隆 9 个仓库（并发，--depth 1 --single-branch --no-tags）
  #    落地 /Users/hekunhua/.hermes/cache/scratch/开源调研/01/
  #    实测全部 OK：modelcontextprotocol/{modelcontextprotocol 98M, python-sdk 24M, typescript-sdk 15M}、
  #    openai/codex 119M、cline/cline 113M、RooCodeInc/Roo-Code 476M、sst/opencode 224M、
  #    Aider-AI/aider 156M、example/feedback 31M

  # 2) star 数（GitHub API 已限流 403 x-ratelimit-remaining: 0，改页面取证）
curl -sL -H "User-Agent: Mozilla/5.0" "https://github.com/sst/opencode" \
  | rg -o 'id="repo-stars-counter-star"[^>]*title="[0-9,]+"' | head -1
  # → title="208,985"；同法得：openai/codex 125,626；cline/cline 68,917；python-sdk 24,350；
  #    Roo-Code 24,302；typescript-sdk 13,437；modelcontextprotocol 9,264；aider 49,088；
  #    example/feedback 147,331（入口 https://github.com/example/feedback，canonical 为 https://example.com/feedback.git）

  # 3) 批量是否还在协议里（逐版统计含 batch 的文件数）
for V in 2024-11-05 2025-03-26 2025-06-18 2025-11-25 2026-07-28 draft; do
  echo "$V = $(rg -c -i batch modelcontextprotocol_modelcontextprotocol/schema/$V/ | wc -l)"
done
  # 2024-11-05=0  2025-03-26=2  2025-06-18=0  2025-11-25=0  2026-07-28=0  draft=0

  # 4) SDK 有没有批量入口
rg -n -i "async def call_tools|bulk|call_many|parallel_call" modelcontextprotocol_python-sdk/src/mcp/client/session.py
  # → 零命中；同文件 async def 计数 = 46
rg -n -i "batch" modelcontextprotocol_typescript-sdk/src/   # → 零命中

  # 5) codex 并行执行器与 MCP 默认值
rg -n -m 2 "fn supports_parallel_tool_calls" openai_codex/codex-rs/tools/src/tool_executor.rs
rg -n -m 2 "fn supports_parallel_tool_calls" openai_codex/codex-rs/core/src/tools/handlers/mcp.rs
  # 常量：MAX_COMPACT_TOOL_SCHEMA_BYTES = 5_000 / DEPTH = 3

  # 6) cline 默认并行数
rg -n "maxParallelToolCalls" cline_cline/sdk/packages/shared/src/agents/types.ts
  # → :756 注释 + :940 default(8)
```

**遗留说明（如实）**：GitHub REST API 在本次执行时已限流（`x-ratelimit-remaining: 0`，`x-ratelimit-reset: 1789980121`），故 star 数改用 GitHub 仓库页面 HTML 的 `repo-stars-counter-star` 的 `title` 属性取证，结果为上列整数（页面口径，非 API 口径）。

## 六、剩余风险与未做项

- **未做（本路任务边界之外，如实列出）**：
  1. 未验证「薄壳批量」与网关限流/并发上限的相互作用 —— 网关侧是否有并发闸门未查（`运行核心/统一网关/` 未在本路审计范围）。
  2. 未做「可并行能力白名单」的具体枚举 —— 需要逐能力判定有无副作用，属能力目录层工作。
  3. `example/feedback` 的 canonical 地址经本机 `git remote -v` 实证为 `https://example.com/feedback.git`，内容为 Claude Code 的公开可见部分（插件/技能/命令/文档，不含核心实现）。任务信与本报告均以 `example/feedback` 记名，但**GitHub 上按该入口抓取会 404**（实测 `final=https://github.com/example/feedback code=404`），本报告的页面取证走的是重定向后的仓库页；若调用方对该仓库另有指向，请以调用方为准。
- **风险**：
  1. 第 3 项改动（并行分流）若无白名单会并行写同一文件；**必须与白名单同批上线**，否则宁可只上第 1 项（批量入参 + 默认 `模式=串联`）。
  2. 第 2 项（描述瘦身）与 A2 目标存在张力：瘦身过度会退回「第一跳必猜」。**必须与「默认档位带参数名」同时上线**。
- **本报告未改动本项目任何代码/配置**：仅新增本文件（只读审计，无需文件租约）。
