```text
LangMem
├── 对外 Python API（src/langmem/__init__.py）
│   ├── create_manage_memory_tool / create_search_memory_tool
│   ├── create_memory_manager / create_memory_store_manager
│   ├── create_memory_searcher / create_thread_extractor
│   ├── create_prompt_optimizer / create_multi_prompt_optimizer
│   ├── ReflectionExecutor
│   └── Prompt 类型
│
├── LangGraph 集成层
│   ├── knowledge/tools.py
│   │   └── Agent 工具：manage_memory、search_memory
│   ├── knowledge/extraction.py
│   │   ├── 无存储的 MemoryManager：对话 + 现有记忆 → 结构化记忆变更
│   │   ├── MemoryStoreManager：搜索 → 提取/合并 → put/delete
│   │   └── MemoryPhase：可选的多阶段记忆处理
│   ├── reflection.py
│   │   ├── LocalReflectionExecutor：延迟队列、按 thread_id 取消/去重
│   │   └── RemoteReflectionExecutor：LangGraph SDK 远程 run + Store search
│   └── utils.py
│       └── NamespaceTemplate：RunnableConfig → 分层 namespace
│
├── 上下文压缩层（short_term/summarization.py）
│   ├── summarize_messages / asummarize_messages
│   ├── token budget 检查、系统消息保留、工具调用消息成组
│   └── RunningSummary + SummarizationNode → LangGraph state update
│
├── Prompt 优化层（prompts/）
│   ├── prompt_memory：对话轨迹/反馈 → 新 prompt
│   ├── metaprompt：反思循环 → 结构化优化 prompt
│   ├── gradient：think/critique → hypotheses/recommendations → 更新 prompt
│   └── MultiPromptOptimizer：先判断需更新的 prompt，再并发/顺序调用单 prompt 优化器
│
├── 可部署 LangGraph 图（graphs/）
│   ├── prompts.py: optimize_prompts
│   ├── semantic.py: graph（示例性的 PreferenceMemory + Store manager）
│   └── auth.py: LangSmith/LangGraph 身份、thread、store 过滤
│
└── 外部边界
    ├── LangChain Runnable / BaseChatModel / StructuredTool
    ├── trustcall.create_extractor：结构化记忆与 prompt 输出
    ├── LangGraph BaseStore：namespace/key/value 记忆存取与语义搜索
    ├── LangGraph checkpoint：由调用方负责会话状态持久化
    ├── LangGraph SDK：远程 ReflectionExecutor
    └── LangSmith tracing / auth：观测与部署鉴权

主要数据流：
对话消息
  ├─ 热点路径 → Agent 调用 manage_memory/search_memory → BaseStore
  ├─ 后台路径 → MemoryStoreManager 搜索相关记忆
  │            → LLM/trustcall 提取、更新、删除、合并
  │            → optional MemoryPhase → BaseStore put/delete
  ├─ 短期路径 → token counter → summarize_messages
  │            → RunningSummary + 摘要系统消息 + 最近消息 → Agent LLM
  └─ 经验路径 → AnnotatedTrajectory + Prompt
               → prompt_memory/metaprompt/gradient
               → 更新后的 Prompt
```

# LangMem 架构文档

## 1. 项目定位

LangMem 是一个面向 LangChain/LangGraph Agent 的 Python 记忆工具库。根目录 `README.md` 将其定位为：从交互中学习和适应，提供对话信息提取、Agent 行为的 prompt refinement、长期记忆维护，并同时提供与任意存储系统配合的功能原语和 LangGraph Store 原生集成（`README.md:3-9`）。项目许可证为 MIT；其实现和 API 设计依赖 LangChain/LangGraph 生态，而不是独立的 Agent 运行时。

源码实际形成三条主要能力线：

1. **长期记忆管理**：将对话转换为结构化记忆，或直接把记忆写入/搜索 LangGraph `BaseStore`。
2. **短期上下文压缩**：在 token 阈值触发时把旧消息替换成运行摘要，同时保留最近消息和必要的工具调用链。
3. **程序性记忆 / Prompt 优化**：根据带反馈的轨迹，用 prompt-memory、metaprompt 或 gradient 策略更新 prompt。

它不是一个独立数据库或完整 Agent 运行时：持久化由调用方提供的 `BaseStore` 承担，Agent 图、checkpointer、模型和部署服务也由 LangGraph/LangChain 应用侧组装。`docs/docs/concepts/conceptual_guide.md:322-338` 明确区分了不依赖特定数据库的 functional core 与依赖 LangGraph Store 的 stateful integration。

源码归档目录清单记录的远程仓库是 `langchain-ai/langmem`；本轮已从远程 `origin/main` 快进核对，目标 checkout 当前 HEAD 为 `29cbe41`（完整提交 `29cbe41e58528f92e9efa773c12e15c47be3808c`）。

## 2. 真实分层与职责

### 2.1 对外 API 与包装层

`src/langmem/__init__.py` 重新导出主要工厂和类型：

- 记忆：`create_memory_manager`、`create_memory_store_manager`、`create_memory_searcher`、`create_thread_extractor`。
- 工具：`create_manage_memory_tool`、`create_search_memory_tool`。
- Prompt：`Prompt`、`create_prompt_optimizer`、`create_multi_prompt_optimizer`。
- 后台/远程执行：`ReflectionExecutor`。

因此，常规 SDK 使用入口是 `from langmem import ...`，而不是直接实例化内部类。具体 API 分组也在 `docs/docs/reference/index.md`、`docs/docs/reference/memory.md`、`tools.md`、`prompt_optimization.md`、`short_term.md` 和 `utils.md` 中声明。

### 2.2 长期记忆工具层：`knowledge/tools.py`

`create_manage_memory_tool(namespace, ...)` 在 `knowledge/tools.py:25-356` 中生成一个同时支持同步和异步的 `StructuredTool`。其闭包函数 `manage_memory`/`amanage_memory`：

- 通过 `NamespaceTemplate` 解析 namespace；
- 校验 `create/update/delete` 动作与 ID 组合；
- `create/update` 用 UUID（或已有 ID）调用 `BaseStore.put/aput`，值形如 `{"content": ...}`；
- `delete` 调用 `BaseStore.delete/adelete`；
- `schema` 可把内容限制为字符串或 Pydantic 模型，并在写入前转换为 JSON 可序列化值。

`create_search_memory_tool(namespace, ...)` 位于 `knowledge/tools.py:362-486`，生成 `search_memory`/`asearch_memory` 工具，接受 `query`、`limit`、`offset`、`filter`，调用 `BaseStore.search/asearch`。`response_format="content_and_artifact"` 时返回序列化内容和原始 Store item，否则仅返回序列化内容。

`_get_store`（`knowledge/tools.py:489-497`）优先使用工厂显式传入的 Store，否则从 LangGraph runtime 取 Store；无法取得时抛出 `errors.ConfigurationError`。该错误类型在 `src/langmem/errors.py:1-6` 中特意继承 `BaseException`，源码注释说明目的是避免被 `ToolNode` 默认异常处理器捕获。

### 2.3 记忆提取与 Store 管理：`knowledge/extraction.py`

这是长期记忆的核心实现，职责由三个组件分开：

#### 无存储的功能原语：`MemoryManager`

- `create_thread_extractor`（`knowledge/extraction.py:96-182`）把消息格式化为会话文本，通过 `trustcall.create_extractor` 按给定 schema 输出结构化线程摘要；缺省 schema 是 `SummarizeThread(title, summary)`。
- `MemoryManager`（`knowledge/extraction.py:217-533`）接收 `MemoryState`：`messages`、可选 `existing`、可选 `max_steps`。它使用 `trustcall.create_extractor` 对 `Memory` 或调用方给出的 Pydantic schema 做插入、更新、可选删除。
- 每一轮把 extractor 输出按 ID 合并，保留未变更的已有记忆；`Done` 作为多步模式的结束标记；`_filter_response` 区分内部删除对象和调用方传入的外部记忆。
- `create_memory_manager`（`knowledge/extraction.py:536-692`）只是返回配置好的 `MemoryManager`。它本身返回 `list[ExtractedMemory]`，不负责把结果写入 Store，符合 functional core 的设计。

#### 有存储的管理器：`MemoryStoreManager`

`MemoryStoreManager`（`knowledge/extraction.py:832-1665`）把检索、抽取、阶段处理和最终 Store 变更串起来：

1. `namespace = NamespaceTemplate(namespace)(config)` 解析当前运行域。
2. 若配置 `query_model`，先让模型以工具调用方式生成多个检索 query；否则用 `utils.get_dialated_windows` 对最近消息生成指数扩大窗口。异步分支用 `asyncio.gather` 并行 `asearch`，同步分支用 LangChain executor 并行 `search`。
3. `_sort_results` 去重并按 `SearchItem.score` 降序截取 `query_limit`，再通过 `_stable_id` 将 `(namespace, key)` 稳定映射为 UUID5 风格 ID。
4. 没有命中且配置了 `default/default_factory` 时，按 schema 生成 `default` item 写入 Store（异步路径）；同步路径也执行对应写入。
5. 调用 `MemoryManager` 对对话和现有记忆做抽取/合并，再通过 `_apply_manager_output` 归并 Store-backed 与 ephemeral 结果，收集更新和删除。
6. 按 `phases` 顺序构造额外的 `MemoryManager`，可控制是否把原始消息带入下一阶段。
7. 仅对真正变化的 item 调用 `put/aput`，对被移除的 Store item 调用 `delete/adelete`，返回最终写入列表。

`create_memory_store_manager`（`knowledge/extraction.py:1666-1723`）公开该管理器的配置：schema、默认值、插入/删除开关、query model、检索上限、namespace、显式 Store 和 phases。`MemoryStoreManager` 还提供 `get/search/put/delete` 及异步对应方法（`knowledge/extraction.py:1318-1665`），将 Store item 的 `kind/content` 重新按已注册 schema 转换为 Pydantic 对象。

#### 自动查询封装：`create_memory_searcher`

`create_memory_searcher`（`knowledge/extraction.py:695-815`）把当前消息交给模型，让模型通过绑定的 `search_memory` 工具产生查询，再批量执行查询并按 score 去重排序，返回 `SearchItem` 列表。它是“对话上下文 → 自动查询 → 相关长期记忆”的独立 Runnable，不负责记忆写入。

### 2.4 运行时 namespace 与序列化：`utils.py`

`NamespaceTemplate`（`src/langmem/utils.py:15-91`）把固定 tuple/string 或含 `{variable}` 的 namespace 模板转换为运行时 tuple。变量从 `RunnableConfig["configurable"]` 读取，缺失时抛 `ConfigurationError`。这同时承担用户、组织、项目等记忆域隔离的边界。

其他关键函数：

- `get_conversation`（`utils.py:98-100`）：合并连续消息运行并转成可供 prompt 使用的文本。
- `get_dialated_windows`（`utils.py:103-119`）：生成最近 1、2、4… 条消息的检索窗口。
- `format_sessions`（`utils.py:125-162`）：把多条轨迹和反馈包装成 `<session_...>` 文本。
- `get_var_healer`、`get_prompt_extraction_schema`（`utils.py:165-248`）：优化 prompt 时遮罩/还原 f-string 变量，并通过 Pydantic schema 约束变量必须保留。
- `dumps`（`utils.py:251-252`）：用 `orjson` 序列化工具响应。

### 2.5 反思与延迟执行层：`reflection.py`

`ReflectionExecutor`（`src/langmem/reflection.py:89-140`）根据 `reflector` 类型选择实现：

- **远程**：字符串 reflector 必须同时提供 namespace，构造 `RemoteReflectionExecutor`。`submit` 通过 `langgraph_sdk` 的 `runs.create` 把 payload、thread_id、namespace 和 `after_seconds` 发到远程 graph；`search/asearch` 通过 SDK Store API 搜索 `MemoryItem`。
- **本地**：Runnable reflector 构造 `LocalReflectionExecutor`，要求 reflector 具有 `namespace` 属性。它使用一个非 daemon worker 线程和 `PriorityQueue`；`submit` 按执行时间入队，同一 `thread_id` 的旧任务会设置取消事件并取消 Future；worker 到时通过 `Runtime(store=...)` 调用 reflector。

`Executor` Protocol（`reflection.py:53-86`）统一规定 `submit`、`search`、`asearch`、`enter`/`exit` 上下文管理器和 Future 语义。`PendingTask`（`reflection.py:389-399`）保存 thread_id、payload、延迟、Future、取消事件和运行配置。

### 2.6 短期记忆与上下文压缩：`short_term/summarization.py`

`short_term/summarization.py` 提供同步/异步函数和 LangGraph 节点：

- `RunningSummary`（`summarization.py:52-67`）保存 `summary`、已摘要的 `summarized_message_ids` 和 `last_summarized_message_id`。
- `SummarizationResult`（`summarization.py:69-79`）返回替换后的消息和新的运行摘要。
- `PreprocessedMessages`（`summarization.py:82-100`）保存待摘要消息、token 计数、预算、历史摘要计数和原系统消息。
- `_preprocess_messages`（`summarization.py:102-222`）保留首个系统消息，跳过已摘要消息，要求新增消息有 ID，处理 token 阈值，并将 AI tool calls 对应的 ToolMessage 一并纳入摘要。
- `_adjust_messages_before_summarization`（`summarization.py:225-256`）超出摘要模型预算时从后向前 trim，并优先保留从 human 消息开始的完整上下文。
- `_prepare_input_to_summarization_model` 负责把历史运行摘要、待处理消息和 token 预算整理成摘要模型输入；它与前述预处理/调整步骤共同构成“先保留必要上下文、再压缩”的边界，而不是简单截断消息列表。
- `summarize_messages`（`summarization.py:337-496`）调用初次或增量摘要 prompt；新摘要由模型返回，随后用 final prompt 组合“摘要系统消息 + 未摘要消息”。`asummarize_messages`（`summarization.py:499-657`）是异步等价实现。
- `SummarizationNode`（`summarization.py:660-860`）是 `RunnableCallable`，可通过 `input_messages_key/output_messages_key` 将摘要结果写入独立 state key，或在两者相同时用 `RemoveMessage(REMOVE_ALL_MESSAGES)` 覆盖消息历史，并把摘要放入 `context.running_summary`。

测试明确覆盖空输入、无需摘要、首次摘要、增量摘要、系统消息、工具调用、缺失/重复消息 ID、同步/异步节点以及消息 key 相同/不同的 state update（`tests/short_term/test_summarization.py`、`tests/short_term/test_summarization_async.py`）。

### 2.7 Prompt 优化层：`prompts/`

`src/langmem/prompts/types.py` 定义优化协议：

- `Prompt`：必需 `name`、`prompt`；可选 `update_instructions`、`when_to_update`。
- `AnnotatedTrajectory`：`messages` + 可选 feedback。
- `OptimizerInput`：`trajectories` + 单个 prompt。
- `MultiPromptOptimizerInput`：`trajectories` + 多个 prompts。

`create_prompt_optimizer`（`prompts/optimization.py:27-269`）支持三种策略：

1. `prompt_memory` → `PromptMemoryMultiple`（`prompts/stateless.py:149-259`）：整理多条轨迹和反馈，调用结构化输出模型生成 `new_prompt`，再用 `get_var_healer` 保留原 prompt 的模板变量。
2. `metaprompt` → `MetaPromptOptimizer`（`prompts/metaprompt.py:59-271`）：先做若干 think/critique 反思，最后用 `OptimizedPromptOutput` 结构化生成新 prompt；若没有轨迹或结果是“No recommendation”，返回原 prompt。
3. `gradient` → `GradientPromptOptimizer`（`prompts/gradient.py:105-419`）：先反思/批评并形成 `warrants_adjustment`、hypotheses、recommendations，再在确有必要时生成更新 prompt；配置包含 `max_reflection_steps`、`min_reflection_steps`、gradient prompt 和 metaprompt。

`MultiPromptOptimizer`（`prompts/optimization.py:272-456`）在多个 prompt 场景先用 `Classify` schema 判断哪些 prompt 需要更新，再调用单 prompt optimizer；异步分支用 `asyncio.gather` 并发更新，最后按原顺序合并结果。

`src/langmem/graphs/prompts.py:9-67` 将这一层包装成 `optimize_prompts` LangGraph 图：输入是 `prompts` 与 `threads`，通过 `configurable.model/kind` 选择模型和策略，单 prompt 且 `when_to_update` 为空时走单 prompt optimizer，否则走 multi-prompt optimizer。

`prompts/stateful.py` 提供另一个基于 `MessagesState` 和 Store 的 `general_reflection_graph`，其 `update_general` 从 Store 读取 prompt、根据轨迹生成更新并写回；该图使用固定的 Anthropic 模型配置，属于可部署示例/集成路径，不是 `__init__.py` 的主工厂。

### 2.8 部署图与鉴权层：`graphs/`

`langgraph.json` 注册了两个 LangGraph 图：

- `optimize_prompts` → `src/langmem/graphs/prompts.py:optimize_prompts`。
- `extract_memories` → `src/langmem/graphs/semantic.py:graph`。

同时声明 `./src` 包依赖、`.env`、`graphs/auth.py:auth` 鉴权入口，以及默认 Store 索引 `openai:text-embedding-3-small` / `dims=1536` / `fields=["$"]`。

`graphs/semantic.py:1-47` 建立 `InMemoryStore`、`PreferenceMemory(category, preference, context)` 和 `create_memory_store_manager`，然后以 `@entrypoint(store=store)` 暴露 `graph(message)`；当前源码中的 namespace 是固定的 `("project", "team_1")`，应视为归档内的示例图配置。

`graphs/auth.py:10-80` 使用 `langgraph_sdk.Auth` 和 `langgraph_api.auth.langsmith.client.auth_client`：API key 认证返回 organization/tenant/user 信息；Studio 用户放行，普通用户的 thread metadata 与 Store namespace 会被按 `ctx.user.identity` 过滤/前置。该模块依赖 LangGraph/LangSmith 部署环境。

`graph_rag.py` 当前全部是注释形式的概念草稿（`src/langmem/graph_rag.py:1-182`），描述 session/entity/edge 的实体抽取、近重复搜索、边解析和写入流程，但没有可执行的类、函数或运行入口；不能把它视为当前有效的图 RAG 实现。

## 3. 核心数据流

### 3.1 热点路径：Agent 主动管理记忆

1. 调用方创建 LangGraph Agent，并把 `create_manage_memory_tool` / `create_search_memory_tool` 放入 tools。
2. Agent 在对话中决定调用工具。
3. 工具从显式 Store 或 LangGraph runtime 取得 `BaseStore`，用 namespace 模板绑定当前用户/组织/项目。
4. 写操作把 `{content: ...}` 以 UUID/key 写入，更新/删除要求提供 ID；搜索支持自然语言 query、filter、limit、offset。
5. 搜索结果直接作为工具内容或 artifact 返回 Agent。

依据：`README.md:30-86`、`src/langmem/knowledge/tools.py:25-486`、`docs/docs/guides/memory_tools.md:10-159`。

### 3.2 后台路径：提取、合并与持久化

1. 应用将当前对话整理为 LangChain message 列表，调用 `MemoryStoreManager.invoke/ainvoke`。
2. 管理器按 query model 或消息膨胀窗口从当前 namespace 搜索候选记忆。
3. `MemoryManager` 把对话和候选记忆交给 `trustcall.create_extractor`，生成新增、更新或删除对象。
4. 管理器按 stable ID 把 Store-backed 和 ephemeral 记忆合并；可继续运行配置的 phases。
5. 仅将差异写回 `BaseStore`，并执行对应删除。
6. 若需要避开交互延迟，可用 `ReflectionExecutor` 延迟提交；同一 thread 的新任务会取消旧任务，远程部署则把任务交给 LangGraph graph。

依据：`src/langmem/knowledge/extraction.py:217-533`、`832-1280`、`src/langmem/reflection.py:110-474`、`docs/docs/guides/delayed_processing.md:6-78`。

### 3.3 短期路径：摘要后再调用 Agent 模型

1. LangGraph state 保存完整 `messages` 与可选 `summary/context`。
2. `summarize_messages` 检查 token 预算；未超限时不调用摘要模型。
3. 超限时从旧消息开始选择摘要范围，保留系统消息；工具调用的 AIMessage 与对应 ToolMessage 同组处理。
4. 摘要模型生成文本，形成新的 `RunningSummary`，只把摘要系统消息和最近未摘要消息交给主模型。
5. `SummarizationNode` 可把结果写入独立 `summarized_messages`，避免破坏 UI/完整历史；若主动覆盖输入 key，则先发 `RemoveMessage(REMOVE_ALL_MESSAGES)`。

依据：`src/langmem/short_term/summarization.py:102-860`、`docs/docs/guides/summarization.md:7-229`。

### 3.4 Prompt 经验路径

1. 调用方传入 `AnnotatedTrajectory`（消息和反馈）及 `Prompt`。
2. 单 prompt 直接选择一种策略；多 prompt 先分类判断哪些模块需要更新。
3. 优化器通过结构化输出约束结果，按策略执行一次或多次 LLM 反思。
4. 生成新 prompt 时保留原有 f-string 变量，并返回更新后的 prompt；没有轨迹或没有必要调整时保留原值。

依据：`src/langmem/prompts/types.py:7-135`、`prompts/optimization.py:50-269`、`272-456`、`utils.py:165-248`。

## 4. 关键类、函数、数据模型及相对路径

| 类/函数/模型 | 相对路径 | 职责 |
|---|---|---|
| `create_manage_memory_tool` | `src/langmem/knowledge/tools.py` | 生成 create/update/delete 记忆工具 |
| `create_search_memory_tool` | `src/langmem/knowledge/tools.py` | 生成 Store 搜索工具 |
| `MemoryManager` / `create_memory_manager` | `src/langmem/knowledge/extraction.py` | 无存储的结构化记忆提取、合并、删除 |
| `MemoryStoreManager` / `create_memory_store_manager` | `src/langmem/knowledge/extraction.py` | 搜索、抽取、阶段处理和 Store 差异写入 |
| `create_memory_searcher` | `src/langmem/knowledge/extraction.py` | LLM 自动生成 query 并排序搜索结果 |
| `create_thread_extractor` | `src/langmem/knowledge/extraction.py` | 对话线程摘要/自定义 schema 提取 |
| `Memory`, `SummarizeThread` | `src/langmem/knowledge/extraction.py` | 默认记忆 schema、线程摘要 schema |
| `MemoryState`, `MemoryStoreManagerInput`, `MemoryPhase` | `src/langmem/knowledge/extraction.py` | 记忆处理输入与阶段配置 TypedDict |
| `Item`, `SearchItem` | `src/langmem/knowledge/extraction.py` | LangGraph Store item 的 Pydantic 内容适配与 JSON 转换 |
| `NamespaceTemplate` | `src/langmem/utils.py` | 从运行配置生成 namespace |
| `ReflectionExecutor` | `src/langmem/reflection.py` | 本地/远程反思执行器工厂 |
| `LocalReflectionExecutor`, `RemoteReflectionExecutor` | `src/langmem/reflection.py` | 延迟队列或 LangGraph SDK 远程执行 |
| `MemoryItem`, `Executor`, `PendingTask` | `src/langmem/reflection.py` | Store item、执行协议、排队任务模型 |
| `RunningSummary` | `src/langmem/short_term/summarization.py` | 增量摘要的文本和已处理消息 ID |
| `SummarizationResult`, `PreprocessedMessages` | `src/langmem/short_term/summarization.py` | 摘要输出和摘要前 bookkeeping |
| `summarize_messages` / `asummarize_messages` | `src/langmem/short_term/summarization.py` | 同步/异步消息压缩原语 |
| `SummarizationNode` | `src/langmem/short_term/summarization.py` | LangGraph Runnable 摘要节点 |
| `Prompt` / `AnnotatedTrajectory` | `src/langmem/prompts/types.py` | Prompt 与带反馈轨迹的数据契约 |
| `OptimizerInput` / `MultiPromptOptimizerInput` | `src/langmem/prompts/types.py` | 单/多 prompt 优化输入契约 |
| `create_prompt_optimizer` | `src/langmem/prompts/optimization.py` | 选择 gradient/metaprompt/prompt_memory |
| `MultiPromptOptimizer` / `create_multi_prompt_optimizer` | `src/langmem/prompts/optimization.py` | 多 prompt 归因、更新和结果合并 |
| `PromptMemoryMultiple` | `src/langmem/prompts/stateless.py` | 轨迹驱动的单次 prompt 反思更新 |
| `MetaPromptOptimizer` | `src/langmem/prompts/metaprompt.py` | 元提示反思循环和结构化 prompt 更新 |
| `GradientPromptOptimizer` | `src/langmem/prompts/gradient.py` | think/critique/recommend 梯度式 prompt 更新 |
| `optimize_prompts` | `src/langmem/graphs/prompts.py` | LangGraph Prompt 优化部署图 |
| `graph` / `PreferenceMemory` | `src/langmem/graphs/semantic.py` | 示例性的 Store 记忆图和偏好 schema |
| `auth` / `filter_store_requests` | `src/langmem/graphs/auth.py` | LangGraph/LangSmith 鉴权与 namespace 过滤 |
| `ConfigurationError` | `src/langmem/errors.py` | 配置缺失的显式异常边界 |

## 5. API、CLI、SDK 与部署入口

### Python API / SDK

推荐入口是根包导出的工厂：

```python
from langmem import (
    create_manage_memory_tool,
    create_search_memory_tool,
    create_memory_manager,
    create_memory_store_manager,
    create_memory_searcher,
    create_thread_extractor,
    create_prompt_optimizer,
    create_multi_prompt_optimizer,
    ReflectionExecutor,
)
```

短期摘要从 `langmem.short_term` 导入：`summarize_messages`、`asummarize_messages`、`SummarizationNode`、`RunningSummary`。Prompt 数据契约从 `langmem.prompts.types` 导入。源码同时支持 LangChain Runnable 的 `.invoke/.ainvoke`，若组件实现了 `__call__`，也支持便捷调用。

### LangGraph 部署入口

`langgraph.json` 是项目声明的部署图入口：

- `optimize_prompts`：`src/langmem/graphs/prompts.py:optimize_prompts`。
- `extract_memories`：`src/langmem/graphs/semantic.py:graph`。
- `auth.path`：`src/langmem/graphs/auth.py:auth`。

这些图由 LangGraph CLI/Platform 解释和部署；源码没有自行实现 HTTP 路由服务器。

### CLI / 开发入口

`pyproject.toml` 没有 `[project.scripts]`，因此没有从该项目声明的独立 `langmem` CLI。`Makefile` 提供开发辅助目标：

- `lint`、`format`：对 `src/` 使用 Ruff；
- `build-docs`、`serve-docs`、`lint-docs`：MkDocs 文档；
- `doctest`、`doctest-watch`：启动 LangGraph in-memory 服务后执行文档示例测试。

本次任务未执行这些命令，也未启动服务。

## 6. 技术栈和依赖

### 运行时与构建

- Python `>=3.10`，项目名 `langmem`，版本 `0.0.30`（`pyproject.toml:1-7`）。
- `src/` 布局，Hatchling 构建（`pyproject.toml:19-24`）。
- Ruff 负责格式化/静态检查，行宽 88（`pyproject.toml:58-70`）。
- `uv.lock` 锁定完整解析结果；本次只读取，未执行安装或同步。

### 核心运行依赖（`pyproject.toml:8-17`）

- `langchain>=0.3.15`、`langchain-core>=0.3.46`：Runnable、消息、prompt、工具和模型抽象。
- `langchain-openai>=0.3.1`、`langchain-anthropic>=0.3.3`：示例和模型提供商集成。
- `langgraph>=0.6.0,<2`、`langgraph-checkpoint>=2.0.12`：图运行时、`BaseStore`、state/checkpoint 集成。
- `trustcall>=0.0.39`：基于工具/schema 的结构化提取、记忆变更和 prompt 输出。
- `langsmith>=0.3.8`：trace、LangGraph 远程/部署相关能力。

源码还直接导入 `orjson`、`pydantic`、`typing_extensions`、`langgraph_sdk` 等；这些由锁文件/上游依赖解析提供，具体版本以 `uv.lock` 当前解析为准。

### 开发依赖

`pyproject.toml:26-53` 声明测试/开发组：`pytest`、`anyio`、`pytest-xdist`、`pytest-watch`、`ruff`、`langgraph-cli[inmem]`、`langgraph-prebuilt`；文档组包含 MkDocs Material、mkdocstrings、nbconvert、nbformat 等。

### 模型和存储边界

模型参数可接受模型字符串或 `BaseChatModel` 实例，实际初始化通过 LangChain `init_chat_model` 或调用方传入的模型完成。源码/文档示例主要使用 `anthropic:claude-3-5-sonnet-latest`、`openai:gpt-4o-mini`，Store 的向量示例使用 `openai:text-embedding-3-small`、1536 维。模型供应商、密钥、Store 后端不是 LangMem 内部固定实现。

## 7. 测试与验证覆盖（基于实际文件读取）

当前测试目录实际包含：

- `tests/short_term/test_summarization.py`：同步摘要原语和 `SummarizationNode`。
- `tests/short_term/test_summarization_async.py`：异步等价覆盖。
- `tests/short_term/utils.py`：基于 `FakeMessagesListChatModel` 的假模型，记录 `invoke_calls`。
- `tests/test_docstring_examples.py`：扫描 `src/`、README 和 `docs/docs/` 中的 Python 代码块，动态导入并执行；标记为 `langsmith`，需要按 Makefile 先提供 LangGraph 服务才是完整 doctest 流程。
- `tests/conftest.py`：将 AnyIO backend 固定为 asyncio。

已读测试验证的行为包括：

- token 未超限时不调用摘要模型；
- 首次摘要只压缩旧消息，并保留最后若干消息；
- 后续摘要只处理新消息，并把旧摘要放入增量摘要 prompt；
- 系统消息不被摘要；AI tool calls 与 ToolMessage 配对处理；
- 缺失消息 ID、重复已摘要 ID 会抛 `ValueError`；
- `SummarizationNode` 可使用独立输出 key，或用 remove 消息覆盖同一 key；
- 同步与异步行为都被测试。

从实际目录和已读文件看，没有专门的 `knowledge`、`reflection`、`prompts`、`graphs` 单元测试文件；它们的部分文档示例由 `tests/test_docstring_examples.py` 机制收集，但本次没有运行测试。`tests/cassettes/ed2e87ca-f890-4900-9a09-dfbc12b51964.yaml` 是测试录制数据，不等同于业务单元测试。

## 8. 架构判断与未确认项

### 已由源码确认的判断

1. **功能核心与存储适配明确分层**：`MemoryManager`、线程提取器和 prompt 优化器主要返回转换结果；`MemoryStoreManager` 和 memory tools 才执行 Store I/O。
2. **LangGraph Store 是长期记忆的实际边界**：namespace/key/value、语义搜索、filter、score 和同步/异步 Store API 都直接来自 `BaseStore` 适配。
3. **会话状态与长期记忆是两套机制**：文档区分 checkpointer 的 thread state 与 Store 的跨 thread memory；`SummarizationNode` 还建议通过不同 state key 保留完整历史和压缩输入。
4. **记忆更新是 LLM 驱动的结构化变更**：`trustcall.create_extractor` 负责 schema/tool 输出，代码再按 ID 合并、比较并产生 put/delete 差异。
5. **namespace 是多租户/多用户隔离的核心契约**：模板变量由 `RunnableConfig.configurable` 解析；远程反思还要求显式 namespace。
6. **背景处理是“延迟/去重执行”，不是另一个存储系统**：`ReflectionExecutor` 只负责把已有 Runnable 延迟提交、取消同 thread 旧任务，最终仍由 reflector/Store 完成记忆处理。
7. **Prompt 被当作可演进的程序性记忆**：三类优化器都以轨迹/反馈为输入，并通过 schema 和变量修复逻辑返回 prompt 文本。
8. **图 RAG 尚未成为有效实现**：`graph_rag.py` 是全注释草稿，不能当作运行模块。

### 未确认或需要后续验证的项

1. 本文未安装依赖、未启动 LangGraph 服务、未调用外部 LLM/embedding，因此没有验证当前锁定依赖在本机的可导入性、API 兼容性、实际模型返回格式或向量检索效果。
2. `langgraph.json` 的 `auth` 与 `store` 行为依赖 LangGraph Platform/CLI 运行环境；仅凭仓库源码无法确认线上部署配置、数据库后端和鉴权服务的实际地址。
3. `graphs/semantic.py` 使用 `InMemoryStore`、固定 namespace 和硬编码模型，是示例图；不能据此确认生产环境的用户隔离、持久化和并发策略。
4. `prompts/stateful.py` 与 `graphs/auth.py` 依赖额外的 LangGraph/LangSmith 服务对象，未在本地测试中看到专门覆盖；其部署可用性需要真实环境验证。
5. `uv.lock` 是解析快照，不等于本机已安装环境；本文件未依据 lockfile 推断运行成功。
6. 目标 checkout 当前未发现独立 `细探-LangMem.md`；本文对类、函数和数据流的判断以实际源码、项目 README、项目 docs、依赖声明和 tests 为准。未发现 `AGENTS.md`；源码侧未跟踪 `ARCHITECTURE.md` 不属于平台文档事实源。

## 9. 本次分析范围与只读约束

本次仅更新平台侧唯一 `ARCHITECTURE.md`。已执行 `git fetch origin --prune && git pull --ff-only origin main`，确认源码已是远程最新；未安装依赖、未运行服务、未修改源码/测试/docs/配置/锁文件，也未删除源码侧未跟踪文件。

## 10. 旧细探收口裁决

当前 checkout 未发现项目根 `细探-LangMem.md`，因此没有可合并或删除的独立细探文档；后续架构事实只维护本平台侧 `ARCHITECTURE.md`。

### 已吸收或确认已覆盖的内容

1. **记忆工具是 Agent 热点路径**：`manage_memory` / `search_memory` 可由 Agent 在交互中直接调用；这与后台的 `MemoryStoreManager` 路径分开，已在 2.2、3.1 和 3.2 说明。
2. **namespace 分域隔离**：包括 `{langgraph_user_id}` 一类运行时模板、用户/组织/项目层级，以及远程反思的 namespace 前置条件，已在 2.4、2.5 和架构判断中落到源码路径。
3. **配置错误显式暴露**：`ConfigurationError` 继承 `BaseException`，用于避免被 `ToolNode` 默认异常处理器吞掉，已在 2.2 和关键数据模型中记录。
4. **本地/远程反思执行器与统一协议**：本地 callable、远程 graph 字符串、延迟提交、按 `thread_id` 取消/去重，以及 `submit`/`search`/`asearch`/`enter`/`exit` 协议，已在 2.5 和 3.2 记录。
5. **摘要前预处理**：系统消息保留、工具调用成组、token 预算调整、历史摘要合并和 `_prepare_input_to_summarization_model`，已在 2.6 和 3.3 记录。
6. **Prompt 优化的完整范围**：`stateless`、`stateful`、`metaprompt`、`gradient` 与多 prompt optimization 已分别映射到实现；并保留“Prompt 是可演进的程序性记忆”这一源码支持的架构判断。
7. **MIT 许可证与 LangChain/LangGraph 生态边界**：已补入项目定位；不把 LangMem 误写成独立存储或运行时。

### 未重复写入或未采纳的内容

- 旧细探中的流程图、行为边界表和“对底座可借鉴点”大多已被本文件更细的源码调用链、数据流和架构判断覆盖，因此没有再复制一份平行描述。
- “LangGraph Store 默认在所有平台部署可用”属于旧细探引用的概括性/部署宣传表述；本文件只保留能由当前仓库确认的 `BaseStore` 集成和 `langgraph.json` 部署边界，未把“所有平台默认可用”作为无条件事实，以避免超出源码证据。
- `graph_rag.py` 作为可运行图 RAG 的暗示未采纳：当前文件已根据源码确认它是全注释概念草稿，没有可执行入口。
- “平台只标准库”“平台全中文命名”“引入 prompt gradient 需要预算”等属于目标平台的设计建议或成本提醒，不是 LangMem 当前架构事实，未写入项目架构结论。
- `examples/`、`docs/`、`tests/` 等旁路线索没有单独新增章节：现有文档已经给出实际目录、文档路径、测试覆盖和未执行事项；没有新的可验证架构事实可增加。

## 11. 后续：通用底座映射（源码事实与平台建议分开）

> 当前核对是基于当前源码的底座映射，不是对 LangMem 做生产改造。源码事实以本项目文件为证据；“支持库/记忆模块/运行核心/统一网关”是目标平台的归属建议，不能反写成 LangMem 已实现能力。
>
> **验证等级：弱验证。** 开工 `project_context` 返回了错误项目 `华世王镞_v3`，MCP 实例为 `project_toolkit`，开工 id 为空；当前核对不使用其代码图、记忆或验证结果。以下结论来自目标目录本地静态读取，未安装依赖、未运行测试、未启动服务、未调用外部模型或 Store。

### 11.1 后续裁决摘要

| 能力/对象 | 当前源码事实 | 底座落点建议 | 裁决 | 当前证据等级 |
|---|---|---|---|---|
| 记忆 `create/update/delete` | `knowledge/tools.py` 直接调用 `BaseStore.put/aput/delete/adelete`，namespace 由配置解析 | 记忆模块编排 + 支持库的 Store 原子写能力；只有一个写入 owner | 吸收为契约模式，不复制 LangMem 实现 | L0/L1 |
| 记忆语义提取、合并、删除决策 | `MemoryManager` 调 `trustcall.create_extractor`，输出 `ExtractedMemory`，不直接写 Store | 记忆模块；LLM/结构化输出属于受管 provider | 吸收分层，升级为显式命令/结果契约 | L0 |
| 后台检索→提取→差异写入 | `MemoryStoreManager` 串起搜索、`MemoryManager`、phases、`put/delete` | 记忆模块唯一流程；Store/embedding 仍在支持库 | 吸收唯一链路，不复制热点链 | L0 |
| namespace/scope | `NamespaceTemplate` 从 `RunnableConfig.configurable` 取模板变量；`graphs/auth.py` 另做身份前置/过滤 | 运行核心提供租户/项目 scope 解析与授权；记忆模块只消费已解析 scope | 升级为统一 scope 契约 | L0/L1 |
| LLM/chat model | 字符串由 `init_chat_model` 初始化，也可传 `BaseChatModel`；可分主模型和 `query_model` | LLM provider 支持库/受管执行单元；记忆模块不拥有连接和密钥 | 吸收 provider 抽象 | L0 |
| embedding/vector index | LangMem 不直接生成 embedding；示例/`langgraph.json` 将 `embed`、`dims`、`fields` 交给 LangGraph Store | 向量/embedding 支持库；Store provider 负责索引生命周期 | 吸收边界，禁止把向量库塞入记忆模块 | L0 |
| 延迟反思任务 | `LocalReflectionExecutor` 自建非 daemon 线程和 `PriorityQueue`；Remote 通过 SDK `runs.create` | 运行核心统一任务/队列/取消/截止/崩溃治理；记忆模块只提交工作 | 废弃各模块自建任务治理，保留业务 payload | L0 |
| HTTP/MCP/统一入口 | LangMem 没有 HTTP server；`langgraph.json` 只声明图、auth、store，平台负责部署 | 统一网关只做请求/鉴权/路由/结果；MCP 若存在只能是薄适配 | 待核/平台新建，不归 LangMem | L0 |
| `graph_rag.py` | 全部为注释草稿，无可执行入口 | 不进入底座能力目录 | 废弃作为当前实现依据 | L0 |

### 11.2 记忆写入、检索、更新的唯一链路

底座必须把“语义决策”和“持久化写入”分开，并规定每个原子能力只有一个契约 owner。建议唯一链路如下：

```text
调用方/Agent/统一网关
  → 记忆模块公开命令（memory.write/search/enrich/delete）
  → scope/namespace 解析与授权
  → 唯一记忆流程编排器
  → LLM/结构化提取 provider（只产候选变更）
  → 唯一 Store/向量 provider 路由
  → 数据库/向量索引/缓存
  → 统一结果、事件、资源释放与证据
```

#### A. 热点写入链（当前源码已实现的事实）

```text
Agent tool call
  → create_manage_memory_tool
  → _get_store(initial_store 或 LangGraph runtime store)
  → NamespaceTemplate(config)
  → 校验 action 与 id
  → _ensure_json_serializable(content)
  → UUID/既有 id
  → BaseStore.put/aput(namespace, key, {"content": ...})
  → 返回“created/updated/deleted memory <id>”文本
```

- `create` 禁止传 id；`update/delete` 必须传 id；`update` 实际也是对相同 `namespace + key` 的 `put`，源码没有独立的版本号、CAS、幂等键或审计事件。
- `delete` 直接调用 `BaseStore.delete/adelete`；没有软删除、撤销记录或回滚事务的 LangMem 自有实现。
- Store 未显式传入且不在 LangGraph runtime 时，`_get_store` 将 `RuntimeError` 转为 `ConfigurationError(BaseException)`；该异常不应被工具节点吞掉。

#### B. 后台检索与差异写入链（当前源码已实现的事实）

```text
MemoryStoreManager.invoke/ainvoke
  → NamespaceTemplate(config)
  → query_model 生成多个 search_memory tool call
      或 get_dialated_windows 生成 1/2/4/... 消息窗口
  → BaseStore.search/asearch（并行）
  → 按 (namespace,key) 去重、score 降序、query_limit 截断
  → _stable_id(namespace,key) 生成 UUID5 风格临时稳定 id
  → MemoryManager.invoke/ainvoke
      → trustcall.create_extractor
      → 插入/更新/RemoveDoc 结果
  → _apply_manager_output：区分 store_based、ephemeral、removed_ids
  → phases 顺序执行额外 MemoryManager
  → 仅比较真正变化项
  → BaseStore.put/aput + delete/adelete
  → 返回 final_puts
```

- `MemoryManager` 是 functional core：输入消息与 `existing`，输出 `list[ExtractedMemory(id, content)]`；它不负责 Store 写入。
- `MemoryStoreManager` 才是当前源码的 Store 写 owner。新对象的 key 使用提取结果的稳定 id；已有对象沿用原始 Store key；删除只对命中的 Store item 执行。
- `kind/content` 是后台管理器写入的值形状；`Item`/`SearchItem` 会按 `kind` 映射回已注册的 Pydantic schema，未知 kind 保留原字典。
- 异步路径用 `asyncio.gather` 并行搜索和最终写入；同步路径使用 `get_executor_for_config`。当前同步 `invoke` 在构造 `search_results_lists` 后又为同一批 query 提交 futures，静态上存在重复搜索调用风险（`extraction.py:1149-1183`），当前核对不改代码，仅列为待核缺口。
- 源码 docstring 宣称“versioned history”，但本地实现只看到 Store item 的 `created_at/updated_at` 适配，未看到 LangMem 自有历史表、版本链、事件表或回放 API；不能把该宣传当作已实现版本历史。

#### C. 只读检索链

```text
create_search_memory_tool
  → _get_store
  → NamespaceTemplate
  → BaseStore.search/asearch(query, filter, limit, offset)
  → utils.dumps(Store items)
  → content 或 (content, raw artifact)
```

`create_memory_searcher` 在此之上增加“消息→LLM tool call→批量搜索→按 score 去重排序”；它只检索，不写入。`MemoryStoreManager.get/search` 是有 schema 反序列化的读门面，并有 `default_factory` 的默认值分支；默认值是否持久化取决于调用路径，不能统一假定为已写入。

### 11.3 scope、namespace、key 与权限边界

| 层次 | 当前实现 | 事实边界 | 底座归属建议 |
|---|---|---|---|
| 运行 scope | `RunnableConfig["configurable"]` 中的任意键 | 只做模板替换，不验证键的来源、格式、租户存在性或权限 | 运行核心的 scope 解析/租约/授权上下文 |
| namespace | 固定 tuple 或含 `{variable}` 的 tuple/string | `NamespaceTemplate` 缺键抛 `ConfigurationError`；固定 namespace 可直接使用 | 支持库提供纯解析原子能力，运行核心提供已验证 scope |
| Store 路径 | `namespace + key` | key 只需在 namespace 内唯一；源码没有全局唯一保证 | Store provider 负责唯一约束和并发语义 |
| thread_id | Local/Remote `ReflectionExecutor.submit` 的去重/远程 run 关联键 | 与 namespace 不是同一概念；没有自动把 thread_id 加入 namespace | 运行核心任务关联/幂等上下文 |
| 身份隔离 | `graphs/auth.py` 对 thread metadata 加 owner，对 Store namespace 前置 user identity | 只在 LangGraph 部署 auth 路径执行；核心 tool/manager 不自带授权 | 统一网关/控制面授权，记忆模块禁止自行绕过 |
| 记忆类型 | `kind` 或 schema 名称，常见 `Memory`/自定义 Pydantic 类型 | 仅用于反序列化和提取工具选择，不是权限边界 | 记忆模块 schema registry，版本化契约待建 |

因此，`("memories", "{langgraph_user_id}")` 只能作为 scope 模板示例，不等于平台已经完成多租户隔离。平台接入时必须先把身份、组织、项目、会话、记忆类型组成规范 scope，再由唯一授权入口校验，禁止调用方自由拼接跨租户 namespace。

### 11.4 LLM、embedding、provider 与资源归属

| 资源/能力 | LangMem 当前事实 | 不应归属 | 推荐 owner |
|---|---|---|---|
| Chat LLM | `str` 经 `init_chat_model`，或直接传 `BaseChatModel`；MemoryManager、query_model、摘要、prompt optimizer 各自使用模型对象 | 记忆模块内部长期持有未治理的 provider 客户端 | LLM provider 支持库 + 运行核心执行监督 |
| 结构化输出 | `trustcall.create_extractor` 以 Pydantic schema/tool 约束插入、更新、删除 | Store provider 不应理解 LLM tool call | 记忆模块定义语义命令，LLM provider 只返回候选结果 |
| embedding | 由 LangGraph `BaseStore` 的 `index` 配置驱动；示例用 `openai:text-embedding-3-small`、1536 维 | LangMem 代码没有独立 embedding client/缓存 owner | embedding 支持库/向量 Store provider |
| 数据库/持久 Store | `BaseStore` 抽象；README 建议生产使用 `AsyncPostgresStore` 等 DB-backed Store | LangMem 不应直接拥有数据库连接池 | 数据库/Store 支持库；连接、事务、游标只在 provider 内部 |
| 向量索引 | Store adapter 根据 `index`、`fields` 决定是否索引；`put(index=False/list)` 可控制单项 | 记忆模块不应维护第二套向量索引 | 向量 provider，索引摘要须绑定 provider/模型/维度/版本 |
| 缓存 | 当前源码未实现独立缓存；只有 Store 可能自带 TTL/缓存语义 | 不得从 `InMemoryStore` 推断生产缓存 | 运行核心缓存治理或 Store provider，必须有上限/失效/owner |
| schema/序列化 | Pydantic `model_dump(mode="json")`、`orjson`、`kind/content` | 不能让每个调用方各自转换 | 支持库通用序列化 + 记忆模块 schema 适配 |
| 远程 SDK | `RemoteReflectionExecutor` 创建 LangGraph sync/async client，提交 run 或搜索 Store | 不能让模块各自持有远程会话和重试逻辑 | 远程 graph/HTTP provider，由运行核心托管连接生命周期 |

### 11.5 现有能力命中、缺口与单链路落点

| 能力 id（建议规范名） | 现有命中 | 缺口/禁止事项 | 复用/升级/新建/废弃 |
|---|---|---|---|
| `memory.write` | `create_manage_memory_tool`、`MemoryStoreManager` 最终 `put` | 缺幂等键、写版本、事务证据、统一错误码 | 升级现有 Store 原子能力，记忆模块只保留一个公开写命令 |
| `memory.update` | 热点 update 与后台差异 put | update 与 create 共用 put，无法表达冲突/条件更新 | 升级为 Store provider 的条件写/CAS；不复制第二 update 实现 |
| `memory.delete` | tool 与 manager 都有 delete | 无软删/审计/恢复契约 | 升级为可审计删除能力；是否物理删除待业务裁决 |
| `memory.search` | tool、manager、searcher、ReflectionExecutor 都可 search | 多个门面，过滤/排序/默认值语义未完全统一 | 记忆模块归一化为一个 search contract；其他入口只做适配 |
| `memory.enrich` | `MemoryManager` + `trustcall` | LLM 输出仍可能受 provider 返回、schema、并发影响；无持久命令事件 | 吸收为记忆模块流程，新增候选变更→校验→提交边界 |
| `scope.resolve` | `NamespaceTemplate` | 没有统一身份、项目、授权、格式校验 | 升级为运行核心/统一网关能力；保留模板作为纯函数 |
| `llm.generate_structured` | `init_chat_model` + `trustcall` | provider、密钥、超时、重试、成本、取消未由 LangMem 统一治理 | 新建受管 LLM provider 原子能力 |
| `embedding.index/search` | 由 `BaseStore` 配置间接提供 | LangMem 不声明 embedding 契约、维度漂移或重建策略 | 新建/复用向量 Store provider，记忆模块禁止直连 SDK |
| `task.submit/cancel/status` | Local/Remote ReflectionExecutor 部分实现 | 任务状态、截止时间、强制取消、崩溃恢复和资源证据不统一 | 废弃模块内任务治理，升级运行核心唯一任务系统 |
| `gateway.memory.*` | LangMem 无 HTTP 路由；只有 Python API/LangGraph 图声明 | 无 request_id、统一错误、权限、版本、流式/大对象契约 | 新建统一网关薄适配，MCP 不能成为第二网关 |

### 11.6 依赖与资源契约（平台装配输入）

跨边界只传值和受管引用，不传 `BaseStore` 实例、LLM client、连接池、Future、线程对象或 SDK client。建议统一请求包：

```text
request_id + capability_id + contract_version
+ scope + arguments + deadline + idempotency_key + resource_budget
```

建议统一返回包：

```text
success + value + error_code + error_message
+ retryable + request_id + evidence + resource_release
```

记忆模块的 `value` 仍可使用 `kind/content`，但跨网关必须定义稳定 schema 版本、大小上限、敏感字段策略和制品引用规则。LLM 输出只能是候选记忆变更；最终写入由唯一 Store owner 执行。Provider 路由至少要声明 provider id、版本、契约版本、能力、健康检查、超时/取消、并发/队列/内存预算、外部依赖和释放责任。

### 11.7 资源生命周期表

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 超时/取消 | Provider/宿主崩溃 | 当前证据/缺口 |
|---|---|---|---|---|---|---|
| Store 连接/事务/游标 | 由具体 `BaseStore` provider 创建，LangMem 只持有抽象对象 | provider 提交/关闭或进入有界池 | provider 应回滚并释放 | 应中断请求、回滚/归还连接 | 应检测连接失效、回收锁/连接 | LangMem 无连接生命周期实现，待 provider 实测 |
| 向量索引/embedding | Store 根据 `index`、`embed`、`dims`、`fields` 配置 | 返回带 score 的 `SearchItem` | 明确索引失败与数据写入是否分离 | 取消 embedding/索引任务，避免半成品 | 重建或标记索引不一致 | 仅配置事实，未验证真实 embedding |
| LLM 会话/请求 | `init_chat_model` 或调用方传 `BaseChatModel` | 返回结构化 extractor/文本结果 | 转统一 provider 错误，不能部分提交记忆 | 需要真实 request cancel/deadline | provider 客户端/进程需回收 | LangMem 无 timeout/cancel 参数和统一 client 生命周期 |
| Store item 数据 | `put/aput` 写 `namespace/key/value`，可带 TTL/index | 返回写结果，TTL 由 Store 维护 | 不应留下部分写入或需有证据 | 需定义写入原子性；当前无事务协调 | 重启后依赖 Store durability | `created_at/updated_at` 是 Store item 字段；无自有审计 |
| 本地反思线程/队列 | `LocalReflectionExecutor` 创建非 daemon worker、PriorityQueue、pending map | worker 调 reflector，Future 完成 | 异常写入 Future；队列 finally 移除 pending | 排队任务可 `future.cancel` + cancel_event；运行中无强制终止 | 宿主崩溃时源码无持久队列/恢复 | 静态源码确认；需真实线程/强杀验证 |
| 远程 run/HTTP client | Remote executor 创建 sync/async LangGraph client 与线程池 | `runs.create` 成功只表示提交成功 | 网络/SDK 异常进 Future | Future 取消不等于远端 run 已取消；依赖 `rollback` 策略 | 远端 run 状态需外部查询 | 未连接真实 LangGraph 服务 |
| 临时 payload/config | Future/queue/PendingTask 与 `RunnableConfig` 持有消息、scope、runtime | Future 完成后应可释放 | 异常路径应释放 config/contextvar | 取消后应从 pending map/queue 清理 | 进程崩溃只能由宿主回收内存 | Local worker 在 shutdown drain 路径仍会处理队列，取消语义待核 |
| 缓存/TTL | Store provider 可按 TTL 刷新/机会式删除 | 返回仍有效 item | 过期/删除应不影响其他 namespace | 需避免刷新 TTL 与取消冲突 | 重启后 TTL 语义依赖 provider | LangMem 只透传 `refresh_ttl/ttl`，未实现缓存治理 |

### 11.8 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码行为 | 应归属的统一契约 | 当前判断 |
|---|---|---|---|
| Store 未配置 | `_get_store` 抛 `ConfigurationError`；manager store 属性抛 `ValueError` | `STORE_UNAVAILABLE/CONFIGURATION_ERROR`，不可把配置错伪装成业务成功 | 已有显式边界，但错误形状不统一，升级 |
| namespace 模板缺键 | `NamespaceTemplate` 抛 `ConfigurationError` | `SCOPE_INVALID`，不允许跨域回退默认 namespace | 吸收并统一错误码 |
| action/id 非法 | tool 抛 `ValueError` | `INVALID_ARGUMENT`，调用前拒绝，不写 Store | 已实现局部校验，缺统一结果 |
| LLM/structured output 失败 | extractor 异常向上冒泡；MemoryStoreManager 未提交前通常不进入 final writes | `LLM_PROVIDER_ERROR`，标可重试性，保证无部分提交 | 需 provider/事务实测 |
| schema 不匹配/未知 kind | `_coerce_value` 对未知 kind 原样返回；Pydantic 校验异常可冒泡 | `SCHEMA_INVALID` 或版本降级策略 | 待核，不能默认兼容 |
| search provider 单项失败 | async `gather` 任一异常可能使整批失败；无部分结果契约 | `SEARCH_FAILED`，明确 all-or-nothing 或 partial | 缺口 |
| 写入部分失败 | final writes 用 `gather` 或 executor 提交，源码无统一事务/补偿 | `WRITE_PARTIAL` + 幂等重试/补偿记录 | 阻断生产底座复用，待升级 |
| 读取空结果/default | 可能调用 `default_factory`；不同 `get/search/ainvoke` 路径持久化语义不同 | `NOT_FOUND` 与 `DEFAULT_MATERIALIZED` 分离 | 待核，不能把默认值当真实记忆 |
| 排队任务被取消 | pending Future 可 cancel，cancel_event 使未开始任务返回 `None` | `CANCELLED`，释放队列引用并记录原因 | 部分实现 |
| 已运行本地任务取消 | `Future.cancel()` 无法停止已运行 reflector；无独立进程强杀 | 运行核心发取消令牌；不可协作时转受管进程 | 当前不满足平台取消契约 |
| `shutdown(cancel_futures=True)` | 设取消标志后 worker 的 drain 逻辑仍可能执行队列任务，源码上存在取消/排空语义冲突 | `DRAINING/CANCELLED/CLEANED` 状态机与零残留核验 | 待核/重要风险 |
| Remote 提交失败 | SDK `runs.create` 异常由本地 Future 表达；远端已接受时本地取消不保证回滚 | `REMOTE_SUBMIT_FAILED` 与 `REMOTE_CANCEL_UNCONFIRMED` 分开 | 未验证 |
| Remote/Store 网络超时 | LangMem API 没有 deadline/timeout 参数；由 SDK/provider 默认决定 | 运行核心统一 deadline、重试、断路与资源回收 | 缺口 |
| LLM/线程宿主崩溃 | Local 队列不持久化；进程退出即丢任务，Store 已提交部分取决于 provider | `CRASHED` + 事务/幂等恢复 | 未实现/未验证 |
| embedding 不可用或维度漂移 | LangMem 不检查 `embed/dims`；由 Store 初始化/查询失败 | `EMBEDDING_UNAVAILABLE`、`INDEX_SCHEMA_MISMATCH` | 未验证 |
| auth/namespace 越权 | `graphs/auth.py` 可前置 identity；核心 tools 不自带 auth | 网关/运行核心拒绝并留审计证据 | 部署路径部分实现，库级不保证 |

### 11.9 L0-L4 验证分级

| 等级 | 含义 | 本项目当前核对状态 | 证据/不能宣称的内容 |
|---|---|---|---|
| L0 | 目标源码/配置/文档静态路径存在且调用关系可复述 | **已完成** | 已读取 `src/langmem/knowledge/{tools,extraction}.py`、`reflection.py`、`utils.py`、`graphs/*`、README、docs、tests、`pyproject.toml`；只能证明源码形态 |
| L1 | 契约/边界静态核对：参数、返回、scope、错误、资源责任 | **部分完成** | 已列热点/后台链、scope、provider、资源与失败矩阵；缺 schema 漂移、幂等、事务、统一错误码的可执行契约测试 |
| L2 | 本地组件测试/静态检查真实通过 | **未运行** | 仓库有短期摘要同步/异步测试和 docstring 收集器；没有专门 memory/reflection/provider 测试文件，不能把测试存在算通过 |
| L3 | 真实 Store、LLM、embedding、异步/远程集成验证 | **未运行** | 未安装/同步 `uv.lock`，未配置 API key，未启动 LangGraph in-memory/远程服务，未连接 DB/向量 Store，未验证并发、超时、取消、崩溃 |
| L4 | 生产部署、网关、租户隔离、长期运行与灾备证据 | **未证明** | `langgraph.json` 仅是部署声明；没有当前项目自有 HTTP 网关、生产数据库、指标、审计、恢复演练或残留对账证据 |

### 11.10 复用裁决、验收契约与装配计划

#### 复用/升级/新建/废弃裁决

1. **吸收**：`MemoryManager` 的“LLM 只产结构化候选、代码按稳定 id 合并、Store 层最终写入”的三层分离；`NamespaceTemplate` 的纯模板解析；热点工具与后台管理分离；`kind/content` 的 schema 适配思路。
2. **升级**：Store 写入/更新/删除契约补齐 `request_id`、scope、schema version、幂等键、条件版本、统一错误、审计事件、资源释放结论；检索契约统一 filter/limit/offset/score/partial 语义；默认值与 TTL 语义分开。
3. **新建**：统一 LLM/embedding/数据库/向量 provider 注册与监督；运行核心唯一任务系统（有界队列、deadline、取消、排空、崩溃恢复）；统一网关 `memory.*` 能力入口；生产级证据账本。
4. **废弃/隔离**：模块内自建无界或不可强杀的任务治理；任何绕过能力注册表的 Store/LLM/SDK 直连；把 `graph_rag.py` 注释草稿、固定示例 namespace 或 `InMemoryStore` 当作生产实现。
5. **待核**：底层 `BaseStore` 具体 DB/向量实现的事务、TTL、并发、索引重建、连接池、崩溃恢复；LangGraph Remote run 的取消与 rollback 实际语义；`trustcall` 对 RemoveDoc/多步 extractor 的错误边界。

#### 建议的装配顺序（仅平台计划，当前核对未执行）

```text
A. 冻结 memory.* / scope.* / task.* 契约和错误矩阵
  → B. 登记唯一 Store/向量/LLM provider 与资源预算
  → C. 在记忆模块接入唯一 write/search/enrich/delete 编排器
  → D. 由运行核心承接 task.submit/cancel/status、deadline、重试、崩溃回收
  → E. 统一网关暴露 memory 能力；MCP 仅作薄适配
  → F. 先做本地契约测试，再做独立 Store/LLM/embedding 集成、故障注入和生产演练
```

验收最低条件：同一 scope 下重复写入具备明确幂等语义；update/delete 不可越界；检索的 score/filter/分页稳定；LLM 候选未通过 schema/权限/版本检查不得写入；超时/取消/崩溃四终态均有真实资源释放证据；网关、模块、provider 不存在第二条旁路链。

## 12. 后续当前核对未运行项与现场边界

当前核对实际只完成目标项目本地静态读取和目标架构文档写入。**明确未运行**：

- 未执行 `pytest`、`pytest -m`、`pytest-xdist`、`ruff`、`doctest` 或任何测试入口；
- 未执行 `uv sync`、`pip install`、构建、打包或依赖导入验证；
- 未启动 LangGraph in-memory/远程服务、HTTP 服务、Agent 图或 `ReflectionExecutor`；
- 未提供 LLM API key，未调用 Anthropic/OpenAI/其他 LLM，未验证 `trustcall` 的真实 tool/schema 输出；
- 未创建或连接 PostgreSQL/AsyncPostgresStore、向量数据库、embedding provider，未测 TTL、索引、事务、并发或重启恢复；
- 未做超时、取消、断线、远程 rollback、进程/宿主崩溃、资源残留、租户越权或故障注入；
- 未读取或使用错绑 `project_toolkit` 返回的代码图、记忆、验证证据；未运行其任何验证工具；
- 未修改 `src/`、`tests/`、`docs/`、README、配置、依赖或 Git；未删除源码侧未跟踪文件。

因此，当前核对交付是**弱验证的后续底座映射输入**，不是 LangMem 或平台生产能力已通过验收的证明。

## 13. 后续深挖收口：MemoryManager、Store、scope 与 ReflectionExecutor

本节是后续内部实现收口，补充前文的模块概览和后续映射。以下结论均来自当前归档提交 `29cbe41e58528f92e9efa773c12e15c47be3808c` 的源码静态核对；“源码缺少”表示在已读取的实现路径中没有对应状态/分支/资源治理代码，不等于底层 LangGraph provider 一定没有该能力。

### 13.1 `MemoryManager`：无 Store 的结构化变更计算器

`MemoryManager`（`src/langmem/knowledge/extraction.py:217-533`）是一个 `Runnable[MemoryState, list[ExtractedMemory]]`，其边界比 docstring 所说的“自动持久化”更窄：

| 项目 | 实际契约 |
|---|---|
| 输入 | `messages` 必填；`existing` 可省略；`max_steps` 运行时缺省为 `1`。`_prepare_existing` 实际接受字符串列表、二元 `(id, value)`、三元 `(id, kind, value)`，比 `MemoryState` 注解更宽。 |
| 模型 | 构造时把字符串模型交给 `init_chat_model`；传入的 `BaseChatModel` 被直接复用。每次 `invoke/ainvoke` 又按步骤创建 `trustcall.create_extractor`，没有在管理器内持有 Store、连接池或事务。 |
| schema 与开关 | `schemas` 为空时回退到 `(Memory,)`；`enable_inserts`、`enable_updates`、`enable_deletes` 原样传给 extractor。默认记忆只有 `content: str`。 |
| 输出 | `ExtractedMemory(id, content)` 列表。模型对象会被 `model_dump`/后续 Store 管理器转换；`RemoveDoc` 作为内部删除对象继续存在的条件是其 ID 属于外部输入记忆。 |
| scope | 不解析 `RunnableConfig`、不解析 namespace、不授权、不读写 Store；同一管理器可以被不同 scope 的调用方复用，因为 scope 不在本组件内建立。 |
| 失败/取消 | extractor、schema 校验和模型异常直接向上冒泡；没有本地 deadline、重试、幂等、事务回滚或主动取消状态。异步 `ainvoke` 只是等待 `extractor.ainvoke`，不另建任务池。 |

单次执行的真实步骤是：

```text
MemoryState
  → _prepare_messages：生成随机 session id、合并消息文本、拼接 instructions
  → _prepare_existing：补 kind，字符串记忆生成随机 uuid
  → create_extractor(tools=schemas, inserts/updates/deletes 开关)
  → 最多 max_steps 次 extractor.invoke/ainvoke
  → 按 json_doc_id 或随机 uuid 归并 results（同 ID 后结果覆盖先结果）
  → 把未改变的初始 existing 补回
  → _filter_response：下一轮丢弃 RemoveDoc，最终只保留外部记忆删除
  → list[ExtractedMemory]
```

有三个必须保留的边界：

1. `Done` 只在 `i == 1` 时才加入 extractor tools（`extraction.py:266-275`、`369-378`）。因此 `max_steps=1` 时没有 `Done` 工具；`max_steps<=0` 时循环不执行且静默返回空列表，源码没有参数校验。
2. 下一轮通过人工追加 AI tool-call 消息和“Memory ... inserted/updated/deleted”工具消息继续反思；`step_results` 不包含 `Done`，但 `actions` 是按全部 `responses` 生成的，若同一响应混合 `Done` 与其他工具调用，源码没有专门的对齐校验。这是未覆盖的多工具边界，不应宣称多步合并在所有 tool-call 组合下已验证。
3. 删除对象只有在最终 ID 属于 `external_ids` 时才返回；Store 管理器的 stable ID 属于 external，因此可删除已检索 Store item；纯新建的 ephemeral 删除不会被上层当作物理删除命令。这是“候选变更计算”和“实际删除”之间的责任切分。

### 13.2 `MemoryStoreManager`：检索、语义决策、差异写入的真实 owner

`MemoryStoreManager`（`extraction.py:832-1665`）才是当前源码中串起 Store I/O 的组件。其构造阶段建立主模型、可选 `query_model`、schema 名称映射、`NamespaceTemplate`、主 `MemoryManager`、可选 phases 和可选 Store。

#### 13.2.1 Store 获取与缓存边界

- 显式 `store` 直接保存到 `self._store`。
- 未显式传入时，第一次访问 `store` 属性调用 `get_store()`，随后执行 `self._store = get_store()`；这意味着管理器会缓存第一次运行上下文的 Store。若同一 manager 实例跨多个 LangGraph runtime/不同 Store 复用，后续调用不会重新读取 runtime Store，存在跨上下文复用风险。源码没有按请求释放或清空该引用。
- 若第一次解析不到 Store，属性抛 `ValueError`，与 memory tool 的 `ConfigurationError(BaseException)` 不是同一错误契约。
- `MemoryStoreManager.put/delete/get/search` 只把 namespace、key、value、TTL/index 等参数转发给 Store；这些门面没有额外的 CAS、版本、审计或事务层。

#### 13.2.2 `ainvoke` / `invoke` 链路与同步/异步差异

```text
MemoryStoreManager.ainvoke/invoke
  → self.store（可能首次缓存 runtime Store）
  → NamespaceTemplate(config)
  → query_model 生成多个 search_memory tool call
      或 get_dialated_windows(messages, query_limit // 4)
  → Store search/asearch 并行或同步检索
  → _sort_results：按(namespace,key)去重、score降序、query_limit截断
  → _stable_id：uuid5(namespace + key) 作为内部 stable id
  → 无命中且有 default_factory：默认值路径
  → MemoryManager：LLM 只产生候选插入/更新/RemoveDoc
  → _apply_manager_output：分 store_based / ephemeral / removed_ids
  → phases 顺序合并
  → 只构造发生变化的 final_puts 与 final_deletes
  → Store put/aput + delete/adelete
  → 返回 final_puts（不返回删除结果、旧值或逐项状态）
```

具体差异和缺口如下：

| 节点 | 实际行为与边界 |
|---|---|
| 默认查询 | 没有 `query_model` 时，`get_dialated_windows(messages, self.query_limit // 4)` 生成指数窗口；`query_limit` 为 `1~3` 时 `N=0`，因此不发起默认检索。源码未校验 `query_limit` 为正数。 |
| LLM 查询 | 有 `query_model` 时，工具调用数量由模型决定；每个调用只强制覆盖 `limit=query_limit`，没有独立的 query 数量上限或 token 预算。异步用 `asyncio.gather`；任一搜索异常会使整个 gather 抛错，源码没有 partial-result 返回契约。 |
| 去重/身份 | `_sort_results` 以 `(tuple(namespace), key)` 去重，stable id 只由 namespace/key 决定，不含 schema、kind、版本或内容哈希。相同 item 多次命中时，后遍历的对象覆盖字典值。 |
| Store item 形状 | `ainvoke/invoke` 直接读取 `item.value["kind"]` 和 `item.value["content"]`；因此检索到不符合该形状的普通 Store item 会触发 `KeyError`，不能把它当作任意 `BaseStore` 内容的通用合并器。 |
| 差异写入 | 更新沿用原 Store item 的 `namespace/key`；新 ephemeral 以 stable/生成 ID 作为 key；相同 kind/content 不写回。源码没有条件写、版本比较、幂等键或写前读锁。 |
| 异步写入 | 用一个 `asyncio.gather` 同时提交所有 `aput/adelete`；任一失败会向上抛出，但已完成的其他操作不会自动回滚，调用方拿不到逐项成功/失败清单。 |
| 同步检索 | 无 `query_model` 分支先同步执行一次 `store.search`（`extraction.py:1165-1172`），随后又为同一 queries 提交一次 executor search（`1173-1183`），存在确定的重复搜索调用；有 `query_model` 分支没有这段第一次同步搜索。 |
| 同步写入 | `executor.submit(store.put/delete)` 后只依靠 executor 退出等待，没有逐个调用 `Future.result()`；Store 写入异常不会按调用链返回，也没有统一 partial-write 结果。 |
| phases | 每个 phase 新建一个 `MemoryManager`，按顺序运行；`include_messages` 缺省为 false，只拿已有记忆做整理；phase 没有 `enable_updates` 或 `max_steps` 开关，且 `_build_phase_manager` 的 `enable_deletes` 缺省为 true，即使主 manager 禁止删除，phase 仍可能删除。 |

#### 13.2.3 默认值、直接 Store 门面与持久化语义

`default` 在构造时被转成 `default_factory`。不同路径不能混为同一语义：

| 路径 | 无命中时行为 |
|---|---|
| `ainvoke/invoke` | 调 factory，按 `key="default"` 写入 Store，再把合成的 `SearchItem` 放入当前处理；这是唯一明确物化默认值的路径。 |
| `search/asearch` | 调 factory 返回内存中的 `SearchItem`，不写 Store；`asearch` 源码 `extraction.py:1568-1577` 明确注释“不实际 put”。 |
| `get/aget` | 期望在 `key="default"` 且未命中时返回合成 item，但代码没有先判断 `self.default_factory`；没有配置默认值时直接取 `None(...)`，这是已确认的异常边界。 |
| `put/aput` | 直接写调用方提供的字典，不自动包成 `{"kind", "content"}`，也不按 manager schemas 校验。 |

`_coerce_value` 只对 `kind` 命中 `schema_name_map` 的值调用 `model_validate`；未知 kind 原样保留。因此“已注册 schema 的强校验”只覆盖读适配路径，不能推导为所有写入口都经过 schema 校验。

### 13.3 写入、检索、更新、删除的责任矩阵

| 能力 | 当前真实实现 | 明确未实现/未验证 |
|---|---|---|
| 热点 create/update/delete | `knowledge/tools.py:271-337` 校验 action/id，create 生成 UUID，update 用同 key `put`，delete 直接物理 `delete`；异步函数实际使用 `aput/adelete`，同步函数使用 `put/delete`。 | 没有读后确认、CAS、幂等键、软删除、恢复、审计事件或事务补偿；工具只返回文本状态。 |
| Store manager enrich | 搜索候选 → `MemoryManager` → 按 stable id 合并 → 差异 put/delete。 | LLM 候选与 Store 最终提交之间没有版本快照或条件更新；并发调用可能互相覆盖，源码没有 scope 级锁。 |
| 只读 search | tool、`create_memory_searcher`、manager `search/asearch`、ReflectionExecutor search 都可查 Store；参数有 query/filter/limit/offset，排序/score 主要由 Store 返回或 manager 再排序。 | 没有一个统一的跨门面错误、分页稳定性、partial result、score 归一化或权限契约。 |
| 默认/TTL/index | manager 转发 `ttl`、`refresh_ttl`、`index`；实际语义由 BaseStore adapter 决定。 | LangMem 没有自己的 TTL 清理线程、索引重建、过期事件、embedding 版本迁移或连接池治理。 |

### 13.4 scope / namespace / key：隔离是模板替换，不是授权

`NamespaceTemplate`（`utils.py:15-91`）的实现非常窄：固定字符串会变为单元素 tuple；只有形如完整 segment `"{name}"` 的片段才从 `config["configurable"][name]` 取值；缺 key 抛 `ConfigurationError`。它不验证值类型、租户是否存在、调用方身份、组织/项目关系、权限或 namespace 是否允许访问；也不解析一个 segment 内的部分插值。

因此当前概念边界是：

```text
RunnableConfig.configurable
  → NamespaceTemplate 纯模板替换
  → (namespace tuple, key)
  → BaseStore
```

而不是：

```text
身份/租户认证 → scope 授权与租约 → namespace 解析 → Store 读写
```

- `MemoryManager` 完全不接触 scope。
- `MemoryStoreManager`、memory tools 依赖当前 Runnable/LangGraph context 获取 config；tool 闭包本身没有一个显式 `config` 参数。
- `key` 只在 namespace 内构成标识；manager 的 stable id 使用 namespace+key 做 UUID5，热点 tool 的 key 是随机 UUID。两套 ID 策略没有统一到同一个业务幂等键。
- `thread_id` 只用于 ReflectionExecutor 的任务关联/远程 run 关联，不会自动追加进 namespace，也不等于用户或租户 scope。
- `graphs/auth.py` 的 identity 前置和 namespace/thread 过滤属于部署鉴权路径，不会自动覆盖裸 Python API、MemoryManager 或 BaseStore。

### 13.5 ReflectionExecutor：队列、并发、取消和资源释放的源码事实

#### 13.5.1 工厂与统一协议

`ReflectionExecutor`（`reflection.py:89-140`）按 reflector 类型分支：字符串必须显式给 `namespace`，返回 `RemoteReflectionExecutor`；Runnable 必须具有 `.namespace` 属性，返回 `LocalReflectionExecutor`。`Executor` Protocol 只有 `submit/search/asearch/__enter__/__exit__`，没有 status、cancel、deadline、健康检查、shutdown 或资源统计方法；`Future` 是唯一的提交结果通道。

#### 13.5.2 Local：单 worker、协作取消、非持久队列

`LocalReflectionExecutor`（`reflection.py:254-386`）的真实资源和状态是：

| 方面 | 源码行为 |
|---|---|
| 队列/并发 | 一个 `queue.PriorityQueue`、一个 `daemon=False` worker thread；所有 reflector 调用在该单 worker 串行执行，没有 worker 数量配置、最大队列长度、背压或持久化队列。 |
| 延迟 | `time.time() + after_seconds` 入队，worker 每次从头部取任务，延迟期间最多每秒重排一次；源码没有 deadline/时钟抽象。 |
| 去重 | 只有 `thread_id` 非空才写入 `_pending_tasks` 并按 thread_id 替换；thread_id 为 `None` 的任务不去重。旧 Future `cancel()` 和旧 `cancel_event.set()` 后仍留在 PriorityQueue，待 worker 取出时跳过。 |
| 取消 | 排队未开始任务可被 `Future.cancel()` 标记，worker 看到 `cancel_event` 后以 `None` 完成（若 Future 已取消则跳过）；已进入 `_reflector.invoke` 的任务没有强制终止，Future 取消不回收模型、Store 或线程中的调用。 |
| Store | 显式 `store` 时 worker 用 `Runtime(store=self._store)` 覆盖 reflector runtime。未显式 Store 时，`submit` 只从 `config[CONF][CONFIG_KEY_RUNTIME].store` 读取并检查存在，却没有把 `existing_store` 赋给 `self._store`（`reflection.py:295-306`）；随后 worker 仍以 `self._store` 构造 Runtime（`429-434`），因此该隐含 Store 传递路径存在源码级缺陷。 |
| 共享状态 | `_pending_tasks` 的读写没有锁；`_store_lock` 只保护 Store 解析检查，不保护任务 map。并发 submit 可能同时替换同一 thread 的任务；旧任务 finally 的 `pop(thread_id, None)` 还可能移除新任务映射。 |
| 配置/context | worker 原地修改 `task.config`，注入 runtime，并在成功的 `invoke` 后恢复 `var_child_runnable_config`；若 reflector 抛异常，恢复语句不会执行，worker 线程 contextvar 可能残留上一个任务的配置。源码也没有复制/冻结 payload/config。 |
| 关闭 | `shutdown(wait=True)` 先令主循环停止，再等待 pending Future，最后 join；退出主循环后会无视原定延迟 drain 队列并执行剩余任务。`cancel_futures=True` 只设置事件和取消 Future，但 drain 仍取任务，源码未在 drain 入口检查取消，存在“已取消 Future 仍被执行”的冲突。异常 Future 在 `shutdown` 的 `future.result()` 处可直接中断关闭，源码没有 finally 保证 worker join。 |
| 资源所有权 | executor 不创建/关闭 BaseStore、LLM client 或模型会话；只持有引用。非 daemon 线程要求调用方显式 `shutdown` 或离开上下文，否则进程退出和资源回收边界不清。 |

因此文档/指南中“新消息取消旧任务”只能解释为排队阶段的协作去重；不能扩展为运行中强制取消、远程撤销、崩溃恢复或零残留保证。

#### 13.5.3 Remote：提交成功不等于执行完成

`RemoteReflectionExecutor`（`reflection.py:143-251`）构造时立即创建异步/同步 LangGraph client 和 `ContextThreadPoolExecutor`。`submit` 在线程池中调用一次同步 `runs.create`，把 `payload`、`thread_id`、固定 `namespace`、`after_seconds` 和 `multitask_strategy="rollback"` 发送给远端，然后 Future 只表示本地提交函数是否返回；它不等待远端 graph 完成、不读取远端结果，也没有远程任务 ID 回传给调用方。

- `Future.cancel()` 只能取消本地提交线程，不能证明远端 run 被取消或 Store 写入回滚；`rollback` 是发送给 LangGraph SDK 的策略，不是 LangMem 自己实现的补偿事务。
- Remote 没有本地 `_pending_tasks`，同一 thread 的去重/回滚依赖远端 API 语义；没有真实服务时不能把它算作已验证。
- `search/asearch` 通过 SDK Store API 读 namespace；它们不是本地 reflection queue 的读写快照。
- `shutdown` 只关闭 ContextThreadPoolExecutor；源码没有显式关闭 LangGraph client 的方法，也没有请求/连接泄漏验证。`__exit__` 会等待本地提交线程完成，但不会等待远端 graph。

### 13.6 真实测试边界与未实现矩阵

静态扫描 `tests/` 实际只有 `test_docstring_examples.py`、`short_term/test_summarization.py`、`short_term/test_summarization_async.py`、测试工具、fixture 和 `__init__`；在测试源码中没有 `MemoryManager`、`MemoryStoreManager`、`ReflectionExecutor`、`NamespaceTemplate` 或 memory tools 的专门测试命中。短期摘要测试确实覆盖同步/异步、空输入、token 阈值、系统消息、tool-call 成组、ID 缺失/重复和 `SummarizationNode` state update，但不能外推到长期记忆链。

`test_docstring_examples.py` 扫描 README、`docs/docs/` 和 `src/` docstring 中的 Python 块，测试标记为 `langsmith`、模块级标记为 `anyio`，执行可能需要 LangGraph in-memory 服务、外部模型/embedding 和凭据；它是示例执行器，不是 MemoryStore/ReflectionExecutor 的确定性单元测试。**当前核对未运行 pytest、ruff、uv sync、LangGraph 服务、LLM、Store 或远程 SDK。**

| 未实现或未由 LangMem 证明的边界 | 结论 |
|---|---|
| 并发写冲突、CAS、版本历史、幂等键、事务/补偿 | Store manager 以普通 put/delete 完成差异提交；API 没有对应参数或本地协调。docstring 的“versioned history”不能当作 LangMem 自有历史实现。 |
| 请求 deadline、LLM/Store 超时、重试、断路、主动取消 | MemoryManager 和 Store manager 没有统一 deadline/cancel 参数；Local 仅有 Future/事件协作取消，Remote 仅提交 run。 |
| 队列上限、持久化、重启恢复、崩溃重放 | Local 队列只在内存；Remote 依赖远端服务；源码没有 LangMem 任务账本或恢复扫描。 |
| 正常、业务失败、取消/超时、宿主崩溃四终态的资源核验 | 没有资源账本、残留扫描、线程/远端 run 对账或 Store 事务证据；仅能静态描述引用关系。 |
| 统一 scope 授权、跨门面错误码、审计 | NamespaceTemplate 只替换配置值；auth 在可部署图路径；工具、manager、executor 错误类型和返回形状不一致。 |
| schema/Store 版本迁移与任意 item 兼容 | manager enrich 假定 `kind/content`；未知 kind 的读适配是原样保留，不是迁移或验证策略。 |

### 13.7 后续收口裁决

1. **吸收**：保留 `MemoryManager` 的 functional core、`MemoryStoreManager` 的“检索→候选变更→差异写入”分层、`NamespaceTemplate` 的纯函数性质、热点工具与后台路径分离，以及 stable identity 由 namespace+key 派生的可追踪思路。
2. **必须升级**：把 Store 写入统一成可观测的条件写/幂等/版本/审计契约；把 search、default、schema 校验和 partial failure 统一成明确结果；把 scope 授权从模板替换中分离出来。
3. **必须隔离/废弃**：不得复用 LocalReflectionExecutor 的模块内任务治理作为生产任务系统；不得把普通 Future cancel 当作 LLM/Store/远端 run 的强制取消；不得把 `InMemoryStore`、固定 namespace 或 `graph_rag.py` 注释草稿当作生产持久化/图 RAG 证据。
4. **待实测**：具体 BaseStore adapter 的事务、并发、TTL、索引、连接池与崩溃恢复；trustcall 的真实 RemoveDoc/多步 tool-call 组合；Local 隐含 runtime Store 缺陷在当前依赖版本的表现；Remote `rollback` 与取消语义；同步重复搜索和未读取 Future 异常的运行影响。

本节完成后，未发现独立 `细探-LangMem.md`；后续架构事实只维护本平台侧 `ARCHITECTURE.md`。

## 14. 后续源码收口补遗：工具、反思、摘要、Prompt 与存储契约

本节是对现有架构正文的逐项收口，不替代前文。新增内容只记录当前源码可直接确认的实现边界；涉及 LangGraph Store、LLM、embedding 或远程服务的行为仍标为外部契约，不能从 LangMem 静态代码推导为已验证事实。

### 14.1 记忆工具与 namespace：工具是薄的热点入口

`create_manage_memory_tool` 和 `create_search_memory_tool` 都在工厂创建闭包，再包装成 `StructuredTool`（前者使用 `_ToolWithRequired`）。因此工具层的职责是参数/动作校验、namespace 解析、序列化和 Store 方法转发，而不是记忆语义合并：

- `manage_memory` 的 `create` 禁止传 `id`，`update/delete` 必须传 `id`；create/update 生成或复用 UUID，并以 `{"content": ...}` 写入；delete 是物理 `delete/adelete`。`actions_permitted` 可裁剪工具动作，空元组在创建时即拒绝。
- `schema` 只影响工具参数 schema 和写前的 Pydantic `model_dump(mode="json")`；`_ensure_json_serializable` 对不支持的对象并不保证严格失败，某些模型转换异常会记录后退回字符串。这不是通用 schema registry 或写入校验事务。
- `search_memory` 将 `query/filter/limit/offset` 原样交给 `search/asearch`；`content_and_artifact` 才返回序列化内容和原始 Store item，普通模式只返回序列化内容。工具本身不承诺 score 归一化、分页稳定性或 partial result。
- 工厂显式传 Store 时优先使用它，否则从 LangGraph runtime 取 Store；runtime 缺失被转换为 `ConfigurationError(BaseException)`，意图是避免 `ToolNode` 把配置故障当普通工具失败吞掉。
- `NamespaceTemplate` 只把固定 tuple/string 和完整 segment 形式的 `{key}` 替换为 `RunnableConfig.configurable[key]`。缺键抛 `ConfigurationError`，但不校验值类型、身份、租户归属、权限或 namespace 合法性；因此 namespace 是寻址/分域模板，不是授权。

该边界解释了为什么热点工具和 `MemoryStoreManager` 必须共享同一 Store 写 owner：工具可以直接写，但不能绕过统一 scope 授权、幂等/版本条件写、审计和资源治理。

### 14.2 反思执行器：延迟、按 thread 去重，但不是可靠任务系统

`ReflectionExecutor` 是按 reflector 类型选择 Local/Remote 实现的工厂，`Executor` Protocol 只规定 `submit/search/asearch` 和上下文管理器，Future 是提交结果通道；没有 status、显式 cancel、deadline、重试、持久任务 ID 或资源统计契约。

**LocalReflectionExecutor** 的关键事实：

1. 构造一个非 daemon 单 worker、`PriorityQueue` 和 pending map；`after_seconds` 通过 `time.time()` 排定执行时间。队列无容量上限、背压、持久化或恢复扫描。
2. 只有非空 `thread_id` 才进入 pending map并去重；新任务会给旧任务设置 `cancel_event` 并调用旧 Future.cancel，但旧任务对象仍在队列中，取出时才跳过。`thread_id=None` 不去重。
3. 排队阶段取消是协作式的；已进入 `reflector.invoke` 后，Future.cancel 不能中止模型、Store 或线程调用。不能把它描述为强制取消。
4. 显式 Store 会被 worker 注入 `Runtime(store=...)`。未显式传 Store 的分支只检查 runtime 中存在 Store，却没有把该 Store 赋给 `self._store`，随后仍用 `self._store` 构造 Runtime；这是源码级隐含 Store 传递缺陷。
5. `_pending_tasks` 没有锁；并发 submit 可能竞态替换，同一 thread 的旧任务 finally 也可能 pop 掉新任务。worker 原地修改 config；异常路径中 contextvar 恢复语句可能不执行。
6. shutdown 停止主循环后仍 drain 队列；`cancel_futures=True` 设置取消标志并取消 Future，但 drain 分支没有同等取消检查，存在已取消任务仍被执行的冲突。异常 Future 还可能在等待阶段中断 shutdown，不能宣称零残留。

**RemoteReflectionExecutor** 创建 LangGraph sync/async client 和线程池；submit 只在线程池中调用一次 `runs.create`，Future 表示本地提交是否完成，不表示远端 graph 完成。`multitask_strategy="rollback"` 是发送给远端 API 的策略，不是本地事务补偿；本地 Future.cancel 不证明远端取消或 Store 回滚。远程 namespace 必填，远程同 thread 的去重、取消和运行状态依赖外部服务，当前源码没有远端 run id、状态回读或客户端关闭契约。

结论：LangMem 的反思执行器可作为功能示例或受限延迟适配器，不能直接充当平台级队列。生产底座应将 payload、scope、deadline、幂等键和取消令牌交给唯一运行核心，由运行核心负责有界队列、状态机、恢复、强杀边界和资源对账。

### 14.3 摘要：以消息 ID 和 token 预算维护增量运行摘要

`RunningSummary` 不是单纯的摘要字符串，还保存已处理消息 ID 集合和最后一个已摘要 ID；这使增量摘要能够跳过旧消息，并在缺失 ID、重复摘要 ID 时显式失败。`PreprocessedMessages` 同时记录待摘要消息、token 计数、摘要预算、历史摘要计数和首个系统消息。

摘要执行顺序必须按以下边界理解：

1. `_preprocess_messages` 保留首个 `SystemMessage`，从待摘要内容中排除已有摘要；新增消息必须有 ID；摘要预算要预留给运行摘要和系统消息。
2. 达到 `max_tokens_before_summary` 后才触发摘要；若待摘要内容超过摘要模型预算，`trim_messages` 从后向前裁剪，并优先以 human 消息开头；裁剪失败只警告并回退原列表，可能再次超出模型上下文窗口。
3. 若截止消息为带 tool calls 的 AIMessage，会把对应 ToolMessage 一并加入，避免切断工具调用链。摘要 prompt 分首次摘要和增量摘要两种；final prompt 再组合系统消息、运行摘要和未摘要消息。
4. `SummarizationNode` 默认写入不同的 `summarized_messages` key，以保留完整历史；只有输入/输出 key 相同时才用 `RemoveMessage(REMOVE_ALL_MESSAGES)` 覆盖历史。摘要状态放在 `context.running_summary`，不是自动写入长期 Store。
5. `max_summary_tokens` 主要是预算计算，不会自动限制摘要模型输出；调用方需要自行 bind 模型参数。同步/异步实现语义对应，但都没有 LangMem 自有 deadline、取消、摘要版本迁移或持久化资源账本。

### 14.4 Prompt 优化与 prompt 变量保护

Prompt 契约由 `Prompt(name,prompt,update_instructions,when_to_update)`、带反馈的 `AnnotatedTrajectory`、单/多 prompt 输入组成。轨迹由 `format_sessions` 包成带随机 session 标识的 `<session_...>` 区块；这只是 prompt 输入标记，不是持久会话 ID。

- `prompt_memory` 是一次结构化输出更新；`metaprompt` 在 `min_reflection_steps` 到 `max_reflection_steps` 范围内先执行 think/critique，再要求 `OptimizedPromptOutput` 输出；空轨迹或 “No recommendation” 保留原 prompt。
- `gradient` 先通过 think/critique/recommend 判断 `warrants_adjustment`，只有明确需要调整时才执行最终更新；每个反思步可能产生多次 LLM 调用，实际成本由配置步数决定，不是固定一次调用。
- `MultiPromptOptimizer` 多 prompt 时先用 `Classify` 严格校验返回名称属于输入 prompt，再只更新被选中的项；异步分支对选中项 `asyncio.gather` 并发，最终按原列表顺序合并，未选中项原样保留。同步分支顺序更新。
- `get_prompt_extraction_schema` 从原 prompt 提取 f-string 变量，`get_var_healer` 在模型输出前遮罩、转义和还原变量，并可要求全部变量存在；因此优化器的关键不变量是“只改 prompt 文本，不丢模板变量”。该保护不是 prompt 语义正确性、版本控制或发布审批。
- `prompts/stateful.py` 另有依赖 Store 的部署式反思路径；它与 stateless、metaprompt、gradient 工厂并列存在，但不应误认为所有优化器都会持久化 prompt。

### 14.5 Store 存储契约与失败语义

LangMem 依赖 LangGraph `BaseStore` 的 `namespace/key/value`、`get/put/delete/search` 及异步对应方法。管理器 enrich 进一步约定候选记忆值通常为 `{"kind": <schema name>, "content": <JSON>}`，读取时按注册 schema 反序列化；未知 `kind` 原样保留。直接 `MemoryStoreManager.put/aput` 则把调用方字典直接转发，不自动补 `kind/content`，因此“读适配 schema”不等于“所有写入都经过 schema 校验”。

默认值有三种不可混淆的语义：`ainvoke/invoke` 无命中时会写入 `key="default"`；`search/asearch` 的 default factory 可返回内存中的合成 item，其中异步路径明确不 put；`get/aget` 对 default 的 fallback 依赖 factory，未配置时存在空调用异常边界。TTL、`refresh_ttl`、index、embedding、过期删除和索引重建均由具体 Store provider 决定，LangMem 没有自己的 TTL 清理器、事务、版本历史、CAS、软删除或补偿日志。

失败与资源边界如下：

| 失败/资源 | 当前源码事实 | 不能宣称 | 平台收口要求 |
|---|---|---|---|
| Store 未配置、namespace 缺键、action/id 非法 | 在局部入口抛 `ConfigurationError` 或 `ValueError` | 各入口已有统一错误码/返回包 | 统一为配置、scope、参数错误，并阻止写入 |
| LLM/trustcall/schema 失败 | 通常在最终 Store 写入前向上冒泡 | 自动重试、deadline、部分结果安全 | provider 统一超时/取消/重试；候选未过 schema/权限不得提交 |
| async 搜索/写入单项失败 | `gather` 任一异常可使整批失败，已完成操作不自动回滚 | all-or-nothing 或 partial 结果 | 返回逐项状态、幂等重试和补偿证据 |
| sync 搜索/写入失败 | 默认查询分支静态存在重复 search；写入只提交 Future，未逐项读取 result | 已确认无重复或异常可见 | 修复/核对唯一查询链，并读取每个写入结果 |
| 本地排队/运行中取消 | 排队任务协作取消；运行中 Future.cancel 不强杀 | 任务已停止、模型请求已取消、Store 已回滚 | 运行核心提供取消令牌、强杀边界和终态对账 |
| shutdown/宿主崩溃 | drain 可能执行取消任务；内存队列丢失，context/config 和线程由宿主回收 | 零残留、可恢复、可重放 | 有界持久任务账本、DRAINING/CANCELLED/CLEANED 状态和资源扫描 |
| Store/embedding/远端 client | 由外部 provider/SDK 持有或创建 | LangMem 自己关闭连接、索引、远端 run | 明确 owner、关闭顺序、超时、健康和 provider 崩溃恢复 |

统一底座适配时，建议把跨边界输入固定为 `request_id + capability_id + contract_version + scope + arguments + deadline + idempotency_key + resource_budget`，输出固定为 `success + value + error_code + error_message + retryable + evidence + resource_release`。LangMem 当前 API 没有这些字段，因此本文件只把它们列为平台装配契约，不能回填成 LangMem 已有能力。

### 14.6 后续最终裁决与范围核对

1. **吸收**：记忆工具的热点入口、namespace 模板解析、`MemoryManager` functional core、`MemoryStoreManager` 唯一差异写 owner、摘要的 ID/token 账本、Prompt 的变量保护和多 prompt 归因。
2. **保留为历史事实但不升级**：Local/Remote ReflectionExecutor 的延迟和 thread 去重；它们没有可靠队列、强制取消、崩溃恢复或远端完成语义。
3. **必须补到底座而非 LangMem 模块**：统一 scope 授权、Store 条件写/幂等/版本/审计、LLM/embedding provider 治理、任务状态机、deadline/取消、资源释放和 partial failure 契约。
4. **明确排除**：`graph_rag.py` 注释草稿、固定示例 namespace、`InMemoryStore`、文档宣传的 “versioned history” 和旧细探中的“默认所有平台可用”均不是当前可验证的生产实现。
5. 本次只改平台侧 `ARCHITECTURE.md`；未改源码、测试、配置、依赖或锁文件。未安装依赖、未运行测试/服务、未调用 LLM/Store/远程 SDK，故证据等级仍为静态源码核对，异常不作成功推断。

## 15. 完整源码深度研究附录（静态核对）

本附录记录当前核对对当前工作树的完整静态研究。读取范围包括全部 `src/**/*.py`、`examples/**/*.py`、两个示例 notebook、全部 `tests/**/*.py`、`README.md`、`pyproject.toml`、`uv.lock`、`langgraph.json`、Makefile、`docs/docs/**/*.md` 和文档配置。这里只记录源码事实与未验证项，不把文档示例输出、notebook 已保存输出或 docstring 宣传当作运行证据。

### 15.1 逐模块事实清单

| 模块 | 源码事实 | 未验证项 |
|---|---|---|
| `__init__.py`、各包 `__init__.py` | 根包公开 memory 工具、三个 memory 工厂、两个 prompt optimizer、`ReflectionExecutor` 和 `Prompt`；短期摘要从 `langmem.short_term` 暴露；`graphs/__init__.py` 为空。 | 未在安装环境验证所有 re-export 的导入和版本兼容性。 |
| `knowledge/tools.py` | `manage_memory`/`amanage_memory` 是 `StructuredTool` 闭包；create 禁止 id，update/delete 要求 id，写值包装为 `{"content": ...}`，delete 是物理删除；search 原样转发 query/filter/limit/offset，`content_and_artifact` 才返回原始 item。`_get_store` 缺 runtime store 时转成继承 `BaseException` 的 `ConfigurationError`。 | 未实测 Pydantic schema、工具 schema 的必填字段、同步/异步 Store 返回值和 `ToolNode` 对 `BaseException` 的实际处理。 |
| `knowledge/extraction.py:217-533` | `MemoryManager` 是无 Store 的 functional core；按 `max_steps` 调 `trustcall` extractor，按 `json_doc_id`/随机 id 归并，保留未变更 existing；`Done` 仅后续加入；`RemoveDoc` 只对外部 id 在最终结果中保留。`max_steps<=0` 没有显式校验。 | 未真实调用 trustcall，未验证混合 `Done`/普通 tool call 的 response metadata 对齐、schema 失败、删除候选和模型异常边界。 |
| `knowledge/extraction.py:832-1665` | `MemoryStoreManager` 才是 Store I/O owner：namespace 解析、搜索、stable id、默认值、MemoryManager、phases、差异 put/delete。enrich 假定命中的 value 具有 `kind/content`；未知 kind 读适配时原样保留。manager 的 `store` 首次从 runtime 取得后缓存。 | 未验证跨 runtime 复用缓存 Store 的实际影响、并发更新覆盖、phase 删除策略和任意外部 Store item 的 KeyError/校验行为。 |
| `knowledge/extraction.py:1015-1137,1139-1280` | 异步搜索使用 `asyncio.gather`，异步最终 put/delete 也使用一个 `gather`，任一异常可使整体抛出且不会回滚已完成操作。同步默认查询分支先直接 `store.search`，再提交同一批 query 的 executor futures，存在确定的重复搜索；同步写入只 `executor.submit`，未逐项 `Future.result()`。 | 未执行同步/异步 manager，未确认依赖版本下 executor 是否在退出时传播提交任务异常，未测部分成功写入后的 Store 状态。 |
| `knowledge/extraction.py:1318-1665` | 直接 `get/search/put/delete` 与异步门面转发 `refresh_ttl`、`index`、`ttl`。`put` 的 `index=None/False/list[str]` 和 `ttl` 只是 BaseStore 参数；`search/get` 可传 `refresh_ttl`。default 的 `ainvoke/invoke` 会物化写入，`search/asearch` 可返回未物化合成 item，`get/aget` 在无 factory 时存在 default fallback 空调用边界。 | 未连接具体 BaseStore，未测 TTL 单位、过期删除、refresh_ttl、嵌套 index path、embedding 维度、事务和并发。 |
| `utils.py` | `NamespaceTemplate` 只替换完整 segment 形式的 `{key}`，从 `RunnableConfig.configurable` 取值；缺 key 抛 `ConfigurationError`，不做身份或权限校验。`get_dialated_windows` 产生 1/2/4/... 消息窗口；`get_var_healer` 遮罩、转义、还原 prompt 变量并可强制保留全部变量。 | 未测缺 key、非字符串 namespace、部分插值、变量冲突和实际 Runnable contextvar 行为。 |
| `reflection.py` Local | 一个非 daemon worker + `PriorityQueue` + pending map；延迟按 `time.time()+after_seconds`；非空 `thread_id` 才去重，新任务设置旧 cancel event 并调用旧 Future.cancel。排队任务可协作取消，运行中 Future.cancel 不能终止 reflector。未显式 Store 的路径只检查 runtime Store，没有赋给 `self._store`，worker 仍使用 `self._store`。 | 未启动 worker，未测并发 submit、旧任务 finally 删除新 map、异常 contextvar 未恢复、shutdown drain 和 `cancel_futures=True` 的实际表现。 |
| `reflection.py` Remote | 字符串 reflector 必须有 namespace；`submit` 在线程池中调用一次 SDK `runs.create`，发送 payload/thread/namespace/after_seconds/`multitask_strategy="rollback"`，本地 Future 只代表提交函数；search/asearch 走 SDK Store API。 | 未连接 LangGraph 服务，未验证远端去重、rollback、取消、远端 run 完成状态、client 生命周期和网络异常。 |
| `short_term/summarization.py` | `RunningSummary` 保存 summary、已摘要 id 集合、最后 id；预处理保留首个系统消息，预算扣除系统消息和历史 summary，要求新消息有 id；AI tool calls 与对应 ToolMessage 成组。超预算用 `trim_messages(start_on="human", strategy="last")`，失败只 warning 并回退原消息。`max_summary_tokens` 只参加预算，不自动限制模型输出。 | 已读同步/异步测试但当前核对未运行；未测真实 token counter、trim warning、模型超长输出、状态持久化和跨版本消息。 |
| `short_term/summarization.py:660-860` | `SummarizationNode` 默认把结果写到 `summarized_messages`，摘要放 `context.running_summary`；输入输出 key 相同才发 `RemoveMessage(REMOVE_ALL_MESSAGES)` 覆盖历史；同步/异步分别调用 `invoke/ainvoke`。 | 未运行 LangGraph state graph，未验证 RemoveMessage reducer、checkpointer 恢复和 UI 完整历史行为。 |
| `prompts/` | `prompt_memory` 单次结构化更新；`metaprompt` 在反思步后输出 `OptimizedPromptOutput`；`gradient` 先判断 `warrants_adjustment` 再更新；无轨迹/无需更新通常返回原 prompt。`MultiPromptOptimizer` 多 prompt 先分类，异步对选中 prompt `asyncio.gather`，同步顺序更新，最终保留原顺序。 | 未调用真实模型，未测分类无效名称、结构化输出形状、反思步数边界、并发限额、LangSmith trace 和 prompt 变量恢复。 |
| `prompts/stateful.py`、`_layers.py` | stateful 反思图直接用硬编码 Anthropic 模型和 Store 读写 prompt；`MemoryLayer` 有 single/multi 两种检索，multi 异步并发、同步串行，single 固定 key=`memory`。`_layers.py` 明确不是当前 public API。 | 未验证这些辅助/部署路径的导入、Store schema、并发和生产可用性。 |
| `graphs/*`、`graph_rag.py` | `graphs/prompts.py` 是部署图包装；`semantic.py` 重复初始化后使用固定 `("project", "team_1")` namespace、`InMemoryStore` 和硬编码模型；`auth.py` 是 LangGraph/LangSmith 鉴权钩子；`graph_rag.py` 全是注释草稿，无可执行入口。 | 未通过 LangGraph CLI/Platform 导入和运行图，未验证 auth 过滤、Store 后端和部署配置。 |

### 15.2 Store、TTL、index 与 namespace 的精确边界

1. LangMem 只依赖 LangGraph `BaseStore` 的 `namespace/key/value` 和同步/异步 get、put、delete、search。`MemoryStoreManager` 的 enrich 值通常是 `{"kind": schema_name, "content": JSON}`，但直接 `put/aput` 不补形状、不校验 schema。
2. `index=None` 使用具体 Store 初始化时的默认 `fields`；`index=False` 禁止该 item 索引；`index=list[str]` 选择字段路径，异步 docstring 还列出嵌套字段、数组通配和指定数组下标。没有 LangMem 自己的 embedding、索引重建或维度迁移逻辑。
3. `ttl` 的源码 docstring 说明单位是分钟，过期和机会式删除由 adapter 决定；默认 refresh 行为可能发生在 get/search/put/update。`refresh_ttl` 由 get/search/aput/put 转发。LangMem 没有 TTL 清理线程、过期事件或缓存 owner。
4. `NamespaceTemplate` 负责寻址模板，不负责授权：模板变量来自 `configurable`，没有租户存在性、类型、身份关系或允许 namespace 校验。`thread_id` 只服务于 ReflectionExecutor 去重/远程 run 关联，不会自动进入 namespace。
5. `graphs/auth.py` 的 identity 前置只存在于部署 auth 钩子；不能把它外推到裸工具、MemoryManager、MemoryStoreManager 或直接 BaseStore API。

上述 5 点是源码事实；TTL 实际过期时点、索引后端、向量质量、事务和多租户安全仍属于外部 adapter/deployment，当前研究没有实测。

### 15.3 同步/异步、异常和 Future 矩阵

| 路径 | 成功/异常事实 | 当前未验证 |
|---|---|---|
| memory tool sync/async | 分别调用 `put/delete/search` 与 `aput/adelete/asearch`；参数错误立即 `ValueError`；runtime Store 缺失为 `ConfigurationError`。 | 未测真实 StructuredTool 包装和底层异常透传。 |
| MemoryManager invoke/ainvoke | 分别调用 extractor 的同步/异步方法；模型、trustcall、schema 异常向上冒泡；无统一 timeout/retry/cancel。 | 未测真实 provider 异常和多步 tool response。 |
| MemoryStoreManager async | 搜索和最终写入用 `asyncio.gather`；单项失败不提供 partial 结果或自动回滚。 | 未测 gather 中取消、已完成任务和 Store 事务交互。 |
| MemoryStoreManager sync | 默认搜索分支存在重复 `store.search`；写入通过 executor submit，未逐项读取 Future。 | 未测具体 executor 是否等待并传播异常，重复调用的性能/副作用。 |
| Local Reflection Future | Future 表示本地 reflector 调用结果；排队取消可能是 cancelled 或 worker 看到 cancel event 后 set_result(None)；运行中不能强杀。 | 未做线程、强杀、取消竞态、异常和 shutdown 实验。 |
| Remote Reflection Future | Future 只表示本地 `runs.create` 提交调用；不表示远端 graph 完成。 | 未验证远端 rollback、取消、状态和提交后断线。 |
| Prompt optimizer sync/async | 单 prompt 分别同步/异步调用模型；多 prompt 异步并发选中项，同步顺序处理；异常未统一转换。 | 未测 provider 限流、并发资源和结构化输出失败。 |
| Summarizer sync/async | 分别调用 model.invoke/ainvoke；输入 ID、预算和 tool-call 处理逻辑对应；摘要输出长度不由 `max_summary_tokens` 自动约束。 | 未运行测试和真实模型。 |

### 15.4 Examples、notebook、docs 与测试的证据分级

- `examples/standalone_examples/custom_store_example.py` 演示显式传入 `InMemoryStore`，使用 Pydantic `PreferenceMemory`，异步 `manager.ainvoke` 后同步 `store.search`；这证明 API 设计支持脱离 LangGraph runtime 的显式 Store，不证明 OpenAI embedding 或模型调用成功。
- 两个 intro notebook 分别演示 semantic memory 的 checkpointer/Store/thread/user namespace、热点工具和 eager retrieval，以及 procedural memory 的 Store prompt、单/多 prompt optimizer 和多 agent 共享 Store。notebook 含保存的历史输出和网络/凭据依赖提示，不能作为当前工作树运行证据。
- docs 明确区分 functional core 与 Stateful Integration，区分 checkpointer 的 thread state 与 Store 的跨 thread memory，并建议生产使用 Postgres 类 Store；这些是文档设计说明，不是当前核对部署验证。
- `tests/short_term/test_summarization.py` 与 async 对应文件覆盖空输入、阈值、首次/增量摘要、系统消息、tool calls、缺失/重复 ID、node 独立/相同 state key。`tests/test_docstring_examples.py` 会扫描 README、`docs/docs` 和 `src` docstring 的 Python 块并动态执行，标记 `langsmith`/`anyio`，可能依赖服务、凭据和外部模型。
- `tests/` 没有 memory tools、MemoryManager、MemoryStoreManager、NamespaceTemplate、ReflectionExecutor、prompt optimizer 或 BaseStore TTL/index 的专门确定性测试文件。`tests/cassettes/*.yaml` 是录制数据，不等于单元测试。
- `pyproject.toml` 声明 Python `>=3.10`、Hatchling、LangChain/LangGraph/trustcall/LangSmith 运行依赖和 pytest/anyio/xdist/ruff/MkDocs 文档组；`uv.lock` 是解析快照，不证明本机已安装或导入成功；没有 `[project.scripts]`，不存在项目声明的独立 CLI。

### 15.5 当前核对未验证项总表

以下项目均未运行或未有当前工作树的动态证据：

1. 未执行 `pytest`、docstring 测试、Ruff、构建、`uv sync`、安装或完整导入检查；用户要求的当前核对验证仅为 `git diff --check`。
2. 未提供 LLM/embedding 凭据，未调用 Anthropic、OpenAI、trustcall 或真实结构化 tool output；未验证 prompt optimizer、MemoryManager 多步、RemoveDoc、schema 校验和 token counter 的真实返回。
3. 未连接或运行 InMemoryStore/AsyncPostgresStore/其他 BaseStore 做 TTL、refresh_ttl、index、embedding dims、filter、score、分页、事务、并发、重启和崩溃测试。
4. 未启动 Local/Remote ReflectionExecutor；未验证隐含 runtime Store 缺陷、thread 去重竞态、Future 取消、异常传播、contextvar 恢复、shutdown drain、非 daemon 线程和远端 rollback/取消。
5. 未运行 LangGraph graph、checkpointer、LangGraph CLI/Platform、auth 钩子或 HTTP/远程服务；未证明生产租户隔离、部署 Store、连接池和灾备恢复。
6. 未把示例 notebook 的保存输出、README/docs 的示例输出或 `langgraph.json` 的声明解释为成功证据；`graph_rag.py` 仍明确归类为不可执行草稿。

本附录的证据等级为：源码/配置/文档静态事实 L0，局部契约和调用链静态核对 L1；动态运行、真实 provider、集成和生产部署均未验证。目标 checkout 未发现独立 `细探-LangMem.md`，本文件是平台侧唯一维护的架构事实源。

## 16. 当前核对完整分段审计收口（源码、示例、测试、文档、配置）

### 16.1 审计范围与关系图

当前核对以 Git 提交 `29cbe41e58528f92e9efa773c12e15c47be3808c` 为源码基线；目标工作树存在未跟踪的源码侧 `ARCHITECTURE.md` 与 `.codegraph/`，本平台文档是当前唯一更新对象。目标仓库 CodeGraph 可用，本轮已运行 `codegraph explore` 查询；以下关系仍由完整文件清单、导入关系、公开 re-export、配置入口和文档链接静态重建。

```text
README / docs / examples / notebooks
              │ 说明与调用样例
              ▼
langmem.__init__ ───────────────┐
              │                 │
              ├─ knowledge.tools│── StructuredTool ── BaseStore
              │                 │       └─ NamespaceTemplate
              ├─ knowledge.extraction ─ trustcall ─ LLM
              │       └─ MemoryStoreManager ──────── BaseStore
              ├─ reflection ─ Local queue/Future 或 Remote SDK run
              ├─ short_term.summarization ─ LangGraph state/checkpointer
              └─ prompts ─ stateless/metaprompt/gradient ─ LLM/trustcall

langgraph.json ── graphs/prompts.py, graphs/semantic.py, graphs/auth.py
tests ─────────── short_term 的确定性覆盖 + 外部依赖型 docstring 执行器
```

这张图表达的是依赖方向，不表示 LangMem 自己拥有 Store、checkpoint、LLM、embedding、HTTP 服务或任务调度器；这些均是外部边界或调用方装配项。

### 16.2 分段读取结论

| 分段 | 已读取内容 | 当前确定事实 | 证据边界 |
|---|---|---|---|
| `src/langmem` 公共入口与类型 | 根包、各子包 `__init__.py`、errors、utils、所有公开实现 | 公开入口集中在 memory tools/manager/searcher、ReflectionExecutor、prompt optimizer；短期摘要从子包导出 | 未安装依赖，未做真实 import |
| `knowledge` | tools 全文、extraction 全文 | 热点工具是薄 Store 转发层；MemoryManager 是无 Store functional core；MemoryStoreManager 是 enrich 与差异写入 owner | trustcall 返回形状、并发写与 provider 事务未动态验证 |
| `reflection` | Local/Remote 全文 | Local 是单 worker、无界内存队列、协作取消；Remote Future 只代表本地提交，不代表远端完成 | 未启动线程/远端服务 |
| `short_term` | summarization 全文、同步/异步测试 | 消息 ID、预算、系统消息和 tool-call 成组构成增量摘要账本；`max_summary_tokens` 不限制模型输出 | 测试当前核对未执行，真实模型未调用 |
| `prompts` | optimization、gradient、metaprompt、stateless、stateful、types、layers、utils | 三种策略；多 prompt 先分类，异步选中项并发；变量遮罩器保护 f-string 变量 | 未验证 provider 限流、模型结构化输出和发布审批 |
| `graphs` 与部署配置 | graphs 全部源码、`langgraph.json`、MkDocs 配置 | 两个图和 auth 是 LangGraph 部署声明；semantic 图固定示例 Store/namespace/model；graph_rag 是注释草稿 | 未运行 LangGraph CLI/Platform |
| `examples` 与 notebooks | standalone 示例、README、两个 intro notebook | 显式 Store 支持脱离 runtime；notebook/示例依赖模型、embedding、凭据，保存输出不是运行证据 | 未执行示例和 notebook |
| `tests` | 全部 Python 测试与 fixture | 确定性测试集中在短期摘要；docstring 测试会扫描 README/docs/src 并动态执行，依赖外部环境 | 没有 memory/reflection/store/prompt 专门单元测试 |
| `docs`、README、配置 | 全部 Markdown、MkDocs、pyproject、Makefile、lock、langgraph.json | 文档以 functional core/stateful integration、hot path/background、checkpointer/Store 分层；配置声明外部部署能力 | 文档声明不等于部署或 provider 成功 |

### 16.3 高优先级源码审计发现

以下是从源码控制流直接推出的风险，不是 provider 推测：

1. **同步默认检索重复执行**：`MemoryStoreManager.invoke` 在无 `query_model` 分支先直接执行 `store.search`，随后又把相同 queries 提交到 executor；这会重复检索并放大延迟/费用，位置为 `knowledge/extraction.py:1165-1183`。
2. **同步写入异常不可见**：同步最终写入只调用 `executor.submit(store.put/delete)`，没有逐个读取 Future；调用链不能可靠报告某个写入失败或部分成功，位置为 `knowledge/extraction.py:1274-1280`。
3. **Local 隐式 Store 没有落到实例**：`LocalReflectionExecutor.submit` 检查 runtime 中的 Store，却未赋值给 `self._store`；worker 后续用 `Runtime(store=self._store)`，隐式 Store 路径可能以 `None` 执行，位置为 `reflection.py:295-306, 429-434`。
4. **Local pending map 竞态**：`_pending_tasks` 没有锁；旧任务 finally 的 `pop(thread_id, None)` 可能删除新任务映射。thread_id 去重只在非空时生效，`None` 任务无限制累积。
5. **Local contextvar 恢复不在 finally**：worker 只在 reflector 成功返回后恢复 `var_child_runnable_config`；异常路径可能留下错误上下文。
6. **shutdown 与取消语义冲突**：`cancel_futures=True` 取消 pending Future 后，退出主循环的 drain 分支仍未检查取消状态，可能继续执行已取消任务；异常 Future 也可能中断 shutdown 的等待/连接收尾。
7. **Store manager 缓存运行时 Store**：未显式传 Store 时，第一次 `get_store()` 的结果写入 `self._store` 并长期持有；同一 manager 跨 runtime 复用可能读写第一个 runtime 的 Store。
8. **默认值路径不一致**：`ainvoke/invoke` 会把 default 写入 `key="default"`；`search/asearch` 可只返回未物化的合成 item；`get/aget` 在没有 `default_factory` 时对 default fallback 存在空调用边界。
9. **enrich 假定 Store item 形状**：`ainvoke/invoke` 直接读取 `item.value["kind"]` 和 `item.value["content"]`；普通合法 BaseStore item 若不符合该形状会触发 `KeyError`，不能视为任意 Store 内容管理器。
10. **多步 MemoryManager 边界未校验**：`max_steps<=0` 静默返回空列表；`Done` 仅第二步加入；混合 `Done` 与其他 tool call 时，response metadata 与 `step_results` 的对齐没有显式保护。

这些发现应优先进入回归测试或修复计划；当前核对按用户要求不修改实现。

### 16.4 记忆、namespace、TTL/index、异常与资源生命周期裁决

| 主题 | 当前实现 | 不应误读为 | 审计裁决 |
|---|---|---|---|
| memory tools | 校验 action/id，解析 namespace，写 `{"content": ...}`，直接 Store I/O | 语义合并、CAS、审计、软删或权限系统 | 薄热点适配器 |
| namespace | 完整 segment 模板替换 `RunnableConfig.configurable` | 身份认证、租户授权、跨域防护 | 纯寻址模板；授权必须在外层 |
| manager/store | LLM 候选 → stable id 合并 → put/delete | 事务、版本历史、幂等写、并发冲突解决 | 单次流程 owner，但写语义不足 |
| reflection | Local PriorityQueue/Future；Remote SDK `runs.create` | 可靠队列、强取消、远端完成、崩溃恢复 | 受限延迟适配器，不是任务系统 |
| TTL | 仅透传 Store 的 `ttl`/`refresh_ttl`；单位与过期由 adapter 负责 | LangMem 自带 TTL 清理、过期事件、缓存 | 外部 Store 契约，需实测 |
| index/embedding | `index=None/False/list` 转发；配置声明 embed/dims/fields | LangMem 管理向量索引、迁移、维度一致性 | 外部 provider 责任 |
| Future | Local 反映本地 reflector；Remote 反映本地提交线程 | 远端 run 已完成或取消已生效 | Future 语义必须在调用方文档中收窄 |
| 异常 | 局部 `ConfigurationError(BaseException)` 与 `ValueError`/底层异常并存 | 统一错误码、retryable、partial result | 需要统一结果/错误契约 |
| 资源 | 模块持有 Store、模型、SDK client 引用；Local 持有非 daemon 线程 | 自动关闭连接、队列持久化、资源对账 | owner、关闭顺序、取消和残留证据均缺失 |

### 16.5 文档冲突、重复与可维护性

#### 冲突或易误导表述

1. `knowledge/extraction.py` 的 `create_memory_store_manager` docstring 写“maintains a versioned history”，但实现只有 Store item 的 `created_at/updated_at`，没有历史表、版本链、事件或回放 API。
2. `README.md` 和多个 quickstart 使用固定 `("memories",)`；其他 guides/API 以 `("memories", "{user_id}")` 为主。前者会把不同用户共享到同一 namespace，虽可作为 demo，但必须醒目标注“不适用于多租户”。
3. `README.md` 的“native integration ... available by default in all LangGraph Platform deployments”和历史细探的“默认所有平台可用”是部署宣传，不由本仓库源码证明；`langgraph.json` 只声明配置入口。
4. standalone 示例标题强调“independently of LangGraph context”，但运行仍直接依赖 `langgraph.store.memory.InMemoryStore`，其含义应限定为“脱离 LangGraph runtime context”，不是脱离 LangGraph 依赖。
5. docs/示例中的 `store.search`、模型、embedding、固定输出和 notebook 保存结果容易被读成可重复验证；实际 docstring 测试是动态执行器，依赖凭据/服务/外部模型。

#### 重复与事实源问题

1. 当前 `ARCHITECTURE.md` 已接近千行，前轮章节 11、13、14、15 对相同的 Store、Reflection、TTL、取消和测试缺口多次复述；内容有用，但新增审计应优先维护“源码事实表 + 风险矩阵 + 验证状态”，避免继续复制长叙述。
2. 源码侧未发现独立 `细探-LangMem.md`；本平台侧仅维护这一份 `ARCHITECTURE.md`，不创建平行事实源。
3. docs reference 由 mkdocstrings 自动生成，README、源码 docstring、guides 三套示例同时存在；API 改动时容易只改一处。应把根 README 保持最小 quickstart，把参数细节归 reference，把行为边界归 guides。
4. 测试与文档的命名不完全对齐：项目使用 pytest/anyio，根 Makefile 还提供 doctest 目标；`tests/test_docstring_examples.py` 不是普通无外部依赖的 doctest，而是带 `langsmith` 标记的动态集成式样例执行器。

#### 视觉结构评价

1. `docs/mkdocs.yml` 视觉层是完整的 Material 文档站：导航分为 Introduction、Quickstart、Concepts、How-to、API Reference，使用浅/深色主题、代码复制、目录跟随、Mermaid、自动 API reference；这适合作为读者入口。
2. `ARCHITECTURE.md` 目前更像累积式审计日志而不是单一架构说明：顶层树、数据流、API 表、平台映射、资源矩阵和多轮附录并列，读者需要穿过重复章节才能找到最终裁决。
3. 建议后续仅在本文件顶部维护“当前摘要/风险等级/验证等级/事实源”，正文按 `边界 → 数据流 → 失败与资源 → 文档裁决 → 验证缺口` 排列；历史轮次保留为附录但不再扩写同一主题。
4. Mermaid/ASCII 图应只保留一套主图；现有多套局部图分别解释相同流程，视觉上增加信息密度但降低定位速度。

### 16.6 当前核对最终验证边界

- 静态读取覆盖 `src/**/*.py`、`examples/**/*`、两个 notebook、`tests/**/*.py`、`docs/**/*`、README、ARCHITECTURE、历史细探、`pyproject.toml`、`uv.lock`、`langgraph.json`、Makefile 和 Git 状态。
- 目标仓库含 `.codegraph/`，本轮已使用目标仓库 CodeGraph 定位关键符号；未借用其他项目代码图，关系图仍以源码复核。
- 未使用其他项目 MCP、Hermes、外部记忆或外部验证证据；MCP 仅用于平台开工上下文、反馈和验证记录。
- 未安装依赖、未执行 pytest/ruff/build/docstring、未启动 LangGraph、未调用 LLM/embedding/Store/远程 SDK，故所有结论最高为 L0/L1 静态证据。
- 当前核对只修改平台侧 `ARCHITECTURE.md`；源码 checkout 的 `src/`、`examples/`、`tests/`、`docs/`、README、配置、锁文件及未跟踪文件均未修改。

## 17. 2026-08-22 远程同步与 CodeGraph 复核记录

- 目标源码：`/Users/hekunhua/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/LangMem`。
- 远程核对：`origin` 为 `https://github.com/langchain-ai/langmem.git`；执行 `git fetch origin --prune && git pull --ff-only origin main`，结果为 `Already up to date`；当前 `main` HEAD 为 `29cbe41e58528f92e9efa773c12e15c47be3808c`。
- 工作树边界：源码侧仅有未跟踪 `.codegraph/` 与 `ARCHITECTURE.md`，未跟踪内容均未删除；平台侧唯一事实源仍是本文件。
- CodeGraph：目标仓库索引可用；本轮 `codegraph explore` 定位了 `MemoryStoreManager`、`MemoryManager`、memory tools、`create_prompt_optimizer`、`MultiPromptOptimizer` 等关键符号。CodeGraph 用于定位，不替代源码逐行证据。
- 本轮复核重点：确认 MemoryStoreManager 的异步 `gather` 与同步查询/写入差异、namespace 与 Store 缓存边界、Local/Remote ReflectionExecutor 的 Future/取消模型、SummarizationNode 状态更新、三种 prompt optimizer 及 LangGraph graphs/auth 部署边界。
- 运行证据：未安装依赖、未执行 pytest/ruff/build、未启动 LangGraph 或外部 LLM/embedding/Store；所有新增结论仍为静态源码与配置证据，不能宣称运行态通过。
