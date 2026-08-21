# LangGraph 架构建档

> 本文是本仓库首轮、证据驱动的架构说明。分析边界为当前工作区源码，不把上游文档或设计意图当作已实现事实。
>
> 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/02_核心Agent框架/langgraph`
>
> 当前基线提交：`f09cfe8ffc1eeffd68f4b628ed69c30f7cad229f`（目标仓库 `main...origin/main`，工作区仅有未跟踪的 `.codegraph/` 与根 `ARCHITECTURE.md`；本平台文档不属于目标源码仓库）。本轮按用户授权未使用 MCP。
>
> 许可证：MIT（根 `LICENSE`）。旧细探：`细探-langgraph.md`；该文件已完整读取并逐条与当前源码对照。可证实的事实已吸收到本文；旧文件保留为历史证据，不删除。后续架构事实只维护本文件。

## 1. 项目定位

LangGraph 是一个低层 Agent/工作流编排框架：开发者以状态 schema、节点、边和 reducer 描述有向状态图，编译后由 Pregel 风格运行时执行；可选 Checkpoint 保存每个 superstep 的状态，从而支持多轮线程、恢复、中断、人机协同和时间旅行。仓库同时维护 checkpoint 接口及 SQLite/Postgres 后端、常用 Agent/工具预构件、官方 CLI、Python SDK，以及已迁出的 JS SDK 占位包。

根 `README.md` 将其定位为“building, managing, and deploying long-running, stateful agents”的 low-level orchestration framework；`AGENTS.md` 明确这是 `libs/` 下多库 monorepo。

## 2. 文本流程图

```text
用户代码 / LangGraph API Server 配置
        │
        ├─ Graph API: StateGraph(state_schema)
        │      ├─ add_node(name, action)
        │      ├─ add_edge / add_conditional_edges
        │      ├─ state schema → channels / managed values
        │      └─ compile(checkpointer, store, cache, policies)
        │
        └─ Functional API: entrypoint / task（libs/langgraph/langgraph/func）
                         │
                         ▼
              CompiledStateGraph / Pregel
                         │
          ┌──────────────┼────────────────┐
          │              │                │
       Plan          Execute           Update
   触发器/版本      并行 actors       批量应用 writes
   选择任务        Runnable 节点       reducer/channel
          └──────────────┼────────────────┘
                         │ 反复执行 superstep，直至无后续任务/达到限制
                         ▼
                 channels / graph state
                         │
          ┌──────────────┴────────────────┐
          │                               │
   Checkpoint（可选）                 Store（可选）
   thread/checkpoint 链               跨 thread 共享记忆
   pending writes / serde             namespace + key/value + search
          │                               │
          └──────────────┬────────────────┘
                         ▼
               invoke / stream / interrupt / state history
                         │
          ┌──────────────┴────────────────┐
          │                               │
      本地 Python 调用                 远程 LangGraph API
                                      ▲          │
                           langgraph CLI       │
                           new/dev/up/build    │
                                      │          │
                              Python SDK（HTTP/SSE/WebSocket）
```

## 3. 真实分层与仓库结构

### 3.1 根目录与工程规则

```text
langgraph/
├── README.md                         项目定位、能力和文档入口
├── AGENTS.md / CLAUDE.md             monorepo 规则与依赖关系图
├── LICENSE                           MIT
├── Makefile                          根级开发命令入口（未在当前核对执行）
├── docs/                             概念/指南/参考文档
├── examples/                         示例
├── libs/
│   ├── langgraph/                    核心 Graph API、Pregel runtime、channels
│   ├── checkpoint/                   Checkpoint/Store/serde 基础契约与内存实现
│   ├── checkpoint-sqlite/             SQLite checkpoint/store 后端
│   ├── checkpoint-postgres/           Postgres checkpoint/store 后端
│   ├── checkpoint-conformance/        Checkpointer 一致性测试套件
│   ├── prebuilt/                     ToolNode、ReAct agent、Validation/Interrupt
│   ├── cli/                          langgraph CLI、配置、Docker/部署流程
│   ├── sdk-py/                       Python 远程 API SDK（同步/异步）
│   └── sdk-js/                       JS SDK 已迁移至独立 langgraphjs 仓库的占位包
└── 细探-langgraph.md                 既有细粒度探索记录
```

`AGENTS.md` 给出的生产依赖关系为：`checkpoint` 被 `checkpoint-postgres`、`checkpoint-sqlite`、`prebuilt`、`langgraph` 使用；`prebuilt` 被 `langgraph` 使用；`sdk-py` 依赖 `langgraph` 与 `cli`；`sdk-js` standalone。各库的 `pyproject.toml` 是依赖与打包事实源。

### 3.2 核心执行层：`libs/langgraph`

- **图构建**：`langgraph/graph/state.py:131` 的 `StateGraph` 保存 `nodes`、普通边、等待多前驱的边、条件分支、channels 和 managed values。节点动作接受状态并返回部分状态更新；Annotated reducer 定义同一键收到多次更新时的合并语义。
- **编译边界**：`StateGraph` 是 builder，不能直接执行；`compile()` 产生可运行的 `CompiledStateGraph`（Pregel 派生运行时）。编译阶段装配 schema/channel、节点 runnable、分支、checkpointer/store/cache 与中断/重试/超时策略，并执行图校验。
- **运行时**：`langgraph/pregel/main.py:450` 的 `Pregel` 将 actors（`PregelNode`）和 channels 组合起来，按 Bulk Synchronous Parallel/Pregel 三阶段执行：Plan 选出订阅已更新 channel 的 actors；Execute 并行执行本 step 任务；Update 对任务 writes 做 channel 更新。当前 step 的更新对同 step 的其他 actor 不可见，下一 step 才生效。
- **channels**：`langgraph/channels/` 提供 `LastValue`、`Topic`、`EphemeralValue`、`AnyValue`、`NamedBarrierValue`、`BinaryOperatorAggregate`、`DeltaChannel`、`UntrackedValue` 等状态传播/聚合语义；`Pregel` 文档还把 `Context` 作为管理外部资源生命周期的高级 channel 语义说明。具体 channel 是否参与 checkpoint 由运行时/配置决定，不能简化为所有 channel 写入都即时落盘。
- **运行契约**：`langgraph/types.py` 定义 `StreamMode`（values、updates、messages、custom、checkpoints、tasks、debug）、`Command`（update/resume/goto）、`Send`（动态 fan-out/map-reduce）、`interrupt`、`RetryPolicy`、`TimeoutPolicy`、`CachePolicy`、`StateSnapshot` 和 `GraphOutput`。
- **辅助层**：`_internal/` 负责 runnable、配置、序列化、重试、队列、超时等内部装配；`pregel/_algo.py`、`_loop.py`、`_runner.py`、`_retry.py`、`_validate.py` 分别承担算法、循环、任务运行、失败重试和图校验。

### 3.3 持久化与共享记忆层：`libs/checkpoint*`

- `libs/checkpoint/langgraph/checkpoint/base/__init__.py` 定义 `Checkpoint`、`CheckpointMetadata`、`CheckpointTuple` 和 `BaseCheckpointSaver`。checkpoint 保存 channel values、channel versions、versions seen、父 checkpoint 关系和 pending writes；配置中的 `thread_id` 是线程主键，`checkpoint_id` 可指定从线程中某个历史点恢复/分叉。
- `BaseCheckpointSaver` 的主要契约是 `put`、`put_writes`、`get_tuple`、`list`、`delete_thread`、`get_next_version`，并提供异步对应方法；扩展能力包括 `delete_for_runs`、`copy_thread`、`prune` 和 delta channel history。
- `libs/checkpoint/langgraph/checkpoint/serde/` 提供 JsonPlus、ormsgpack/msgpack 和加密 serializer。`JsonPlusSerializer` 默认允许 msgpack 类型并发出警告；设置 `LANGGRAPH_STRICT_MSGPACK=true` 或传入显式 `allowed_msgpack_modules` 后才收紧到 allowlist。`EncryptedSerializer.from_pycryptodome_aes()` 实际使用 PyCryptodome AES，默认模式是 `AES.MODE_EAX`，密钥来自 `LANGGRAPH_AES_KEY`（或显式 `key`），长度必须为 16/24/32 字节；源码未证明旧细探所写的 Fernet/AES-GCM 实现。
- `libs/checkpoint/langgraph/checkpoint/memory/` 提供内存 saver，适合测试/示例。
- `libs/checkpoint/langgraph/store/base/` 定义跨线程共享 Store 契约（`BaseStore`、`Item`、namespace/key/value、搜索与 embedding 相关协议）；`store/memory/` 提供内存实现。它与 checkpoint 是不同边界：checkpoint 保存单线程图执行链，store 用于跨 thread/用户共享数据。
- `libs/checkpoint-sqlite` 的 `SqliteSaver`/`AsyncSqliteSaver` 将 checkpoints、writes 等数据落到 SQLite；同步 saver 明确定位为轻量同步场景，异步实现使用 `aiosqlite`。SQLite 代码还实现 delta channel 历史链读取。
- `libs/checkpoint-postgres` 提供 `PostgresSaver`/`AsyncPostgresSaver` 及 Store 后端，首次使用需 `.setup()` 创建表；连接要求 `autocommit=True` 和 `row_factory=dict_row`，否则表创建或字典式行读取会失败。
- 当前 `libs/checkpoint/langgraph/cache/redis/` 是 cache 实现；在本工作区没有与之对应的 `store/redis/` 实现。旧细探的“Store Redis 后端”因此不作为当前仓库已交付事实。
- `libs/checkpoint-conformance` 是契约验证层，不是生产存储：对实现自动检测并验证基础能力以及可选扩展能力，输出报告并支持 pytest/异步 fixture。

### 3.4 Agent 预构件层：`libs/prebuilt`


`langgraph/prebuilt/` 在核心 Graph API 上提供可复用节点和工厂：

- `chat_agent_executor.py` 的公开工厂 `create_react_agent` 用 `StateGraph` 组装 agent ↔ tools 循环；LLM 产生带 `tool_calls` 的 `AIMessage` 后，`ToolNode` 执行工具并写回 `ToolMessage`，循环直到没有工具调用或步数耗尽。旧细探中的 `ChatAgentExecutor` 作为概念描述可对应此文件，但当前 README/API 证据支持的公开入口是 `create_react_agent`，不把它单列为独立公开组件。
- `tool_node.py` 将工具调用映射为节点执行，支持工具注入、并发调用、结果消息和错误处理。
- `tool_validator.py` 以 Pydantic/schema 校验工具调用参数。
- `interrupt.py` 提供 Agent Inbox 的 `HumanInterrupt`/`HumanResponse` 数据结构，和核心 `interrupt`/`Command(resume=...)` 配合实现人工确认。
- 当前源码已标记 `create_react_agent` 与旧 AgentState API 向 `langchain.agents` 迁移；因此它是兼容/便捷层，不应被误写成核心框架唯一入口。

### 3.5 交付与部署层：`libs/cli`

`langgraph_cli.cli:cli` 是 Click 命令入口，`pyproject.toml` 注册脚本 `langgraph = "langgraph_cli.cli:cli"`。CLI 读取 `langgraph.json`，根据 `dependencies`、`graphs`、`env`、`python_version` 等字段定位应用和编译图：

- `langgraph new`：从模板创建项目。
- `langgraph dev`：本地开发 API server，支持热加载。
- `langgraph up`：通过 Docker Compose 启动 API server/相关服务。
- `langgraph build`：构建 LangGraph API Docker image。
- `langgraph dockerfile`：生成自定义 Dockerfile。
- `langgraph deploy` 相关命令：由 `deploy.py` 接入部署流程。

CLI 本身负责应用发现、依赖追踪、Docker/Compose 参数和开发运行封装；真正的 API server/runtime 不是本仓库 `libs/cli` 内完整实现，部分能力由 `langgraph-api`、`langgraph-runtime-inmem` 等可选依赖/外部服务提供。

### 3.6 远程访问层：`libs/sdk-py` 与 `libs/sdk-js`

- Python SDK 的 `langgraph_sdk.get_client`/`get_sync_client` 导出异步和同步客户端。
- 顶层 `LangGraphClient` 组合 `assistants`、`threads`、`runs`、`crons`、`store` 五类资源客户端，底层使用 `httpx`。
- `runs` 支持等待、取消、后台执行和流式执行；`threads.stream()` 将一个线程的 SSE 连接共享给 values/message/tool-call/custom 等投影；异步客户端还提供 WebSocket transport，README 明确同步流式仅使用 SSE。
- `schema.py` 定义 API 对象与协议类型：Assistant、Thread、Run、Cron、Checkpoint、Interrupt、Store Item、`StreamMode`、`RunStatus`、`ThreadStatus`、`MultitaskStrategy` 等。
- `sdk-js/README.md` 明确包已迁移到独立 `langchain-ai/langgraphjs` 仓库；当前目录不能视为 JS SDK 实现。

## 4. 数据模型与数据流

### 4.1 图内状态

1. 应用定义 `TypedDict`、Pydantic、dataclass 或其他受支持 schema。
2. `StateGraph` 将每个状态键解析为 channel；Annotated reducer 为并发/多节点更新提供合并函数。
3. 节点读取本 step 开始时的 channel 快照，返回部分更新；`ChannelWrite` 将更新写入任务 writes。运行时 channel 读写不等于每次都直接落盘，checkpoint 在运行时边界保存 channel 快照、版本和 pending writes。
4. Pregel Update 阶段按 channel 规则应用 writes，生成新的 channel versions；状态成为下一 superstep 的输入。
5. 终止后，`invoke` 返回最终 state；`stream` 可按 values/updates/messages/checkpoints/tasks/debug/custom 输出中间数据。

### 4.2 Checkpoint 链

```text
invoke/stream 输入
  → input checkpoint（source=input，step=-1）
  → Pregel superstep
  → task writes / pending writes
  → loop checkpoint（channel_values + versions + metadata）
  → parent_config 指向上一个 checkpoint
  → 下一 superstep / interrupt / resume
```

`thread_id` 将一系列 checkpoint 归为一条线程；`checkpoint_id` 锁定历史位置。节点失败时，同一 superstep 中已成功节点的 pending writes 可被保存，恢复时避免重复执行。`get_state_history`/`list` 沿 checkpoint 链读取历史，`update_state`/`Command` 可从某个点更新或恢复，形成时间旅行/分叉路径。

### 4.3 Store 共享记忆

```text
节点 / Runtime context
  → BaseStore.put(namespace, key, value)
  → memory / SQLite / Postgres Store 实现
  → BaseStore.get / search / list_namespaces / delete
  → 跨 graph、thread 或用户的共享数据
```

Store 的结构化 API 与远程 SDK 的 `client.store` 对齐；SDK `Item` 使用 `namespace: list[str]`、`key`、`value`、时间戳及可选相似度分数。

### 4.4 远程 API 数据流

```text
应用 langgraph.json
  → CLI 解析 graph_id -> Python module:compiled_graph
  → API server 注册 assistant/graph
  → SDK create/search assistant
  → create thread
  → create/start run(input, config, context, checkpoint_id)
  → server 执行 CompiledStateGraph/Pregel
  → SSE/WebSocket stream（values/messages/updates/tasks/checkpoints/...）
  → thread state / checkpoint / store 查询
```

## 5. 关键路径

### 5.1 最小 Graph API 路径

```text
StateGraph(State)
  → add_node("name", fn)
  → add_edge(START, "name") / add_conditional_edges
  → compile(checkpointer=..., store=...)
  → compiled.invoke(input, config)
  → Pregel plan → execute node → update channels
  → output state
```

证据入口：`libs/langgraph/langgraph/graph/state.py` 的 `StateGraph`；`libs/langgraph/langgraph/pregel/main.py` 的 `Pregel`；`libs/langgraph/langgraph/types.py` 的 `Command`/`Send`/`StateSnapshot`。

### 5.2 中断与恢复路径

```text
node
  → interrupt(value)
  → GraphInterrupt
  → checkpoint 保存中断状态（要求启用 checkpointer）
  → 客户端读取 Interrupt(value, id)
  → Command(resume=value)
  → 从 node 开始重执行并继续写状态
```

恢复时节点中断前的代码会重新执行；业务必须保证该段代码可重复执行或将外部副作用置于中断之后/做幂等控制。

### 5.3 ReAct 工具循环路径

```text
messages
  → create_react_agent / CompiledStateGraph
  → agent 节点调用 ChatModel
  → AIMessage.tool_calls?
      ├─ 否：结束，返回 messages
      └─ 是：ToolNode 并发/逐调用工具
                 → ToolMessage 写回 messages
                 → 回到 agent
```

`version="v2"` 使用 `Send` 将工具调用分发为独立任务；`pre_model_hook`、`post_model_hook`、response format、checkpointer、store 和 interrupt 是扩展点。

### 5.4 Checkpointer 实现路径

```text
BaseCheckpointSaver
  ├─ InMemorySaver
  ├─ SqliteSaver / AsyncSqliteSaver
  └─ PostgresSaver / AsyncPostgresSaver
        ↕ put / put_writes / get_tuple / list / delete / async variants
  JsonPlus/msgpack/Encrypted serializer
        ↕ typed bytes
  storage backend
```

## 6. API、CLI、SDK 对外表面

### 6.1 核心 Python API

| 表面 | 位置 | 作用 |
|---|---|---|
| `StateGraph` / `CompiledStateGraph` | `libs/langgraph/langgraph/graph/state.py` | 声明、编译并执行状态图 |
| `MessageGraph` / `add_messages` | `libs/langgraph/langgraph/graph/message.py` | 面向消息列表的图状态便捷层 |
| `Pregel` / `NodeBuilder` | `libs/langgraph/langgraph/pregel/main.py` | 直接使用 Pregel actor/channel runtime |
| `Command` / `Send` / `interrupt` | `libs/langgraph/langgraph/types.py` | 状态更新、动态路由、恢复和人机中断 |
| `BaseCheckpointSaver` | `libs/checkpoint/langgraph/checkpoint/base/__init__.py` | checkpoint 后端契约 |
| `ToolNode` / `create_react_agent` | `libs/prebuilt/langgraph/prebuilt/` | 工具执行和 ReAct agent 预构件 |

### 6.2 CLI

| 命令 | 作用 | 主要实现 |
|---|---|---|
| `langgraph new` | 创建模板项目 | `libs/cli/langgraph_cli/templates.py` |
| `langgraph dev` | 本地开发/热加载 API | `libs/cli/langgraph_cli/cli.py`、`exec.py` |
| `langgraph up` | Docker Compose 启动 | `cli.py`、`docker.py` |
| `langgraph build` | 构建 API Docker image | `cli.py`、`docker.py` |
| `langgraph dockerfile` | 生成 Dockerfile | `cli.py` |
| `langgraph deploy ...` | 部署相关操作 | `deploy.py` |

### 6.3 Python SDK

```python
from langgraph_sdk import get_client, get_sync_client

client = get_client(url="http://localhost:8123")
# client.assistants / threads / runs / crons / store
```

SDK 默认远程连接使用 `httpx`，支持 API key/header/timeout；未给 URL 时尝试 in-process ASGI transport。资源操作的请求/响应类型集中在 `langgraph_sdk/schema.py`，流式 transport 在 `langgraph_sdk/stream/transport/` 与各 async/sync client 中。

## 7. 技术栈与依赖

| 层/库 | 实际技术栈与证据 |
|---|---|
| 语言/运行时 | Python `>=3.10`；核心包声明兼容 CPython/PyPy、3.10–3.13（各 `pyproject.toml`） |
| 构建/依赖 | Hatchling；开发依赖与本地 editable 依赖由 `uv` lock/`pyproject.toml` 管理 |
| 核心 | `langchain-core>=1.4.7,<2`、Pydantic 2、`xxhash`、`langgraph-checkpoint`、`langgraph-prebuilt`、`langgraph-sdk` |
| 图执行 | 自研 Pregel/BSP runtime、Runnable 抽象、channel/reducer、asyncio/并发执行 |
| 持久化 | Checkpoint 基础契约；内存；SQLite（`sqlite3`/`aiosqlite`）；Postgres（Psycopg 3） |
| 序列化/安全 | JsonPlus、ormsgpack/msgpack、可选加密 serializer；严格 msgpack allowlist |
| Agent/工具 | `langchain-core` message/tool/chat model/runnable；Pydantic 工具参数校验 |
| CLI | Click、httpx、pathspec、python-dotenv；Docker/Compose 封装 |
| Python SDK | httpx、orjson、websockets、langchain-protocol、langchain-core；SSE + async WebSocket |
| JS/TS | 本仓库仅保留 `sdk-js` 迁移说明与 CLI 示例；完整 LangGraph.js 在独立仓库 |
| 可观测性 | LangChain/LangSmith tracing 协议及 SDK tracing 配置；服务部署与完整 API server 依赖外部 LangGraph API/Deployment 组件 |

## 8. 测试与质量门

### 8.1 已发现的测试面

- 核心 `libs/langgraph/tests/`：`test_state.py`、`test_pregel.py`/`test_pregel_async.py`、`test_channels.py`、`test_algo.py`、`test_retry.py`、`test_interruption.py`、`test_time_travel.py`、`test_subgraph_persistence.py`、`test_stream_*`、`test_serde_allowlist.py`、`test_remote_graph*.py` 等。
- Checkpoint：内存、JsonPlus、加密、Store、delta channel、conformance 测试。
- SQLite/Postgres：同步/异步 saver、Store、delta channel、conformance、迁移/历史读取测试。
- Prebuilt：ToolNode、工具调用、验证错误过滤、React agent、interrupt 相关测试。
- CLI：archive、deploy helpers 等单元测试；examples 包含 `langgraph.json` 与可运行样例。
- SDK：assistants/threads/runs/crons/store、HTTP/SSE/WebSocket、同步/异步 stream、序列化、加密、API parity、integration tests。

### 8.2 仓库声明的命令

`AGENTS.md` 规定修改某个库后，在该库目录运行：

```text
make format
make lint
make test
```

可用 `TEST=path/to/test.py make test` 缩小测试范围。各库 `pyproject.toml` 还配置 pytest strict markers/strict config；SDK 默认通过 marker 排除需要运行 API server 的 integration 测试。由于本任务只允许文档修改，未安装依赖、未启动服务、未构建、未运行测试套件；本次验证仅对新增 Markdown 做 `git diff --check`（见交付记录）。

## 9. 配置、部署与边界

- 应用配置文件是 `langgraph.json`，核心字段是 `dependencies`、`graphs`、可选 `env`、`python_version`、`pip_config_file`、`dockerfile_lines`。
- CLI 的默认本地 API 端口在 README 中为 `8123`；开发命令的开发服务端口默认为 `2024`。两者属于 CLI/运行模式参数，不应混写。
- checkpoint 使用 config 的 `configurable.thread_id`；时间旅行还需要 checkpoint id。
- Postgres saver 首次使用要 `.setup()`，且连接参数必须满足 README 的 autocommit/dict row 约束。
- 严格反序列化不是默认状态：`JsonPlusSerializer` 默认允许 msgpack 类型并告警；部署时应显式启用 `LANGGRAPH_STRICT_MSGPACK=true` 或配置 allowlist。加密 serializer 的当前源码证据是 PyCryptodome AES-EAX，不应沿用旧细探的 Fernet/AES-GCM 表述。
- 核心库本身不绑定具体 LLM provider；模型、工具和 prompt 由应用或 `prebuilt`/LangChain 生态注入。
- CLI 可调用 Docker、外部 API server/runtime、LangSmith Deployment；这些外部组件不等于当前仓库源码已包含。

## 10. 未确认项与后续细探入口

1. **代码地图边界**：目标根目录存在独立 `.codegraph/`；本轮 shell `codegraph status` 显示索引正常（490 files、14,352 nodes、47,223 edges），并以 `codegraph explore` 辅助定位。代码图只用于导航，结论仍以当前源码回读为准。
2. **MCP 未使用**：本轮按用户授权跳过 MCP，不生成 MCP 开工、反馈或验证记录；目标项目根目录以本文首部绝对路径为准。
3. **完整 API server 未在本仓库闭合**：CLI 的 `dev/up` 所依赖的 `langgraph-api`、`langgraph-runtime-inmem` 等组件没有在当前 `libs/` 清单中完整呈现；需另行确认服务端路由、数据库表、认证和部署运行时。
4. **Store 的全部后端覆盖面**：当前仓库确认了 `checkpoint` 的 Store 基础/内存、SQLite Store、Postgres Store及 SDK Store 资源；Redis 或其他 Store 后端未作为当前 `libs/` 独立库完整核实，不应在本档案中当作已交付组件。
5. **`CompiledStateGraph` 的完整编译细节**：已确认 builder→Pregel 关系，但当前核对没有逐段覆盖 `compile()` 后所有子图、缓存、远程图、durability 和 stream transformer 的实现路径；后续应以 `state.py` 的 compile 方法、`pregel/_loop.py`、`_checkpoint.py` 和 stream transformer 测试为细探入口。
6. **版本与工作区状态**：核心 `langgraph` pyproject 当前声明 `1.2.11`，checkpoint `4.2.0`，prebuilt `1.1.0`；其他动态版本以各包实际 metadata/release 流程为准。工作区原有未跟踪文件 `细探-langgraph.md` 被保留，未纳入本次新增文档以外的修改。
7. **运行验证未执行**：当前核对遵守“禁止安装依赖、启动服务、构建”的约束；没有对已安装环境的 import、CLI、SDK 端到端或数据库后端做运行时结论。

## 11. 旧细探吸收与未吸收裁决

旧文件 `细探-langgraph.md` 已完整读取（123 行），并与当前提交 `644815f9e5bc52ad8f7a5227a456227e9c3e639b` 的源码、README、测试和目录清单逐条对照。裁决如下：

| 旧细探内容 | 裁决 | 当前权威表述/证据 |
|---|---|---|
| `StateGraph`、节点/边/条件边、reducer、`compile()` → `CompiledStateGraph` | 吸收 | §3.2、§5.1；`libs/langgraph/langgraph/graph/state.py` |
| Pregel 的 `invoke/stream/ainvoke/astream`、actor/channel、Plan→Execute→Update、step 内更新不可见 | 吸收并校正 | §3.2、§4.1；`libs/langgraph/langgraph/pregel/main.py:450` 明确是 Pregel/BSP 三阶段，不写成旧细探的“BFS + BEFORE/AFTER 依赖”。 |
| `LastValue`、`Topic`、`NamedBarrierValue`、`AnyValue`、`BinaryOperatorAggregate` 等 channel | 吸收并补充 | §3.2；当前目录另有 `EphemeralValue`、`DeltaChannel`、`UntrackedValue`，`Context` 由 Pregel 文档说明为生命周期管理语义。 |
| Checkpoint 数据结构、`put/get_tuple/put_writes/list`、线程/历史/分叉/中断恢复、内存/SQLite/Postgres 后端 | 吸收 | §3.3、§4.2、§5.4；`libs/checkpoint*/`。保留“配置 checkpointer 后才有持久化”边界。 |
| JsonPlus/msgpack、strict allowlist、防止不受信任 checkpoint 触发执行 | 吸收并校正 | §3.3、§9；当前默认是 permissive + warning，strict 需环境变量或显式 allowlist；不存在可证明的 `_apply_checkpointer_allowlist` 旧函数名。 |
| 加密序列化、`LANGGRAPH_AES_KEY`、16/24/32 字节密钥 | 吸收并校正 | §3.3、§7、§9；当前源码是 PyCryptodome AES，默认 `AES.MODE_EAX`，未证明 Fernet/AES-GCM。 |
| Store 的 namespace/key/value、`get/put/search/delete/list_namespaces`、embedding 注入和向量搜索 | 吸收 | §3.3、§4.3、§7；`libs/checkpoint/langgraph/store/base/`、`store/base/embed.py`。 |
| “Store 后端包含 Redis” | 不吸收 | 当前仅发现 `libs/checkpoint/langgraph/cache/redis/` cache；没有 `store/redis/` 生产实现，已在 §3.3 和 §10 明确边界。 |
| `ToolNode`、`create_react_agent`、工具参数验证、Agent Inbox 中断 | 吸收并校正 | §3.4、§5.3；当前 README/API 的公开入口是 `create_react_agent`，不把 `ChatAgentExecutor` 当作独立公开组件。 |
| 本体没有系统提示词，模型/工具/prompt 由应用或 LangChain 生态注入 | 吸收 | §9；这属于依赖边界而非核心 runtime 内建能力。 |
| CLI、Python SDK、JS SDK 迁移说明、旁路线索 | 吸收 | §3.5、§3.6、§6；JS 仅为迁移占位包，完整实现不在本仓库。 |
| “Channel 读写统一走 checkpoint”“每次 superstep 必然持久化” | 不吸收原文，按源码校正 | §4.1、§9：channel 是运行时内存语义；启用 checkpointer 后在运行时边界保存 checkpoint，不能把可选持久化写成强制事实。 |
| “对底座可借鉴点”、平台同构建议、命名转写建议 | 不吸收 | 这些是面向其他平台的设计建议，不是 LangGraph 当前源码架构事实；避免污染本项目唯一架构档案。 |

旧细探不删除、不作为后续维护入口；其余未列入上表的描述仅在已被当前正文覆盖时视为吸收，未覆盖部分保留为历史线索而非当前事实。

## 12. 首轮结论

LangGraph 的真实核心不是“LLM 调用链”，而是：**图构建 API + Pregel/BSP 状态执行 + 可插拔 channel/reducer + checkpoint/store 持久化契约**。`prebuilt`、CLI 和 SDK 分别把核心能力包装为 Agent 组件、应用交付工具和远程资源客户端。最重要的架构边界是：

- 图 schema/channel 决定状态如何合并，节点只产生更新；
- Pregel 的 step 边界决定并发可见性、重试与终止；
- Checkpoint 负责线程内可恢复执行与历史链，Store 负责跨线程共享记忆；
- CLI/SDK 面向外部 API server，不能据此推断 server/runtime 已包含在当前 monorepo；
- `serde` allowlist、pending writes、父 checkpoint 链和 conformance tests 是持久化正确性与安全性的关键验证点。

## 13. 后续：面向系统工程平台的底座映射

本节不是把 LangGraph 源码直接搬进平台，而是基于当前提交 `644815f9e5bc52ad8f7a5227a456227e9c3e639b` 的后续裁决输入：哪些能力可吸收为公共契约/支持库/模块库，哪些只能由运行核心治理，哪些仍属于外部交付面。`StateGraph`、`CompiledStateGraph`、Pregel/BSP、channels、checkpoint、store、CLI、SDK 的名称和语义保留原文；下文的 L0-L4 是平台映射边界，不是 LangGraph 自身的官方分层。

### 13.1 单链路总图与三类职责

```text
L4 项目适配层 / HTTP 网关 / CLI / Python SDK / 外部部署服务
  → L3 运行核心：运行实例、superstep 调度、并发、取消、超时、恢复、资源监督、运行事件
  → L2 模块库：状态工作流模块、图定义与编译装配、Agent/工具流程、checkpoint/store 编排
  → L1 支持库：channel/reducer、serde/加密、checkpoint/store 后端、原子文件/数据库/网络能力
  → L0 公共契约：状态快照、更新、版本、线程、运行、错误、取消、恢复、资源和证据类型
  → SQLite/Postgres/文件系统/外部 API/模型与工具 provider
```

**三类职责裁决：**

| LangGraph 能力 | 平台落点 | 不能越界做什么 | 裁决 |
|---|---|---|---|
| `StateGraph`、`add_node`、边/条件边、schema/reducer | L2 状态工作流模块；L0 固化状态 schema、更新和分支契约 | 不直接创建线程池、数据库连接、进程或外部 API 会话 | 吸收为模块模式，不吸收为运行核心 |
| `CompiledStateGraph`（用户常称 `CompiledGraph`） | L2 编译产物/工作流计划；由 L3 执行 | 不把编译对象当资源治理器或持久化 owner | 吸收为“编译计划 → 运行实例”桥接 |
| `Pregel`、`PregelNode`、Plan/Execute/Update、BSP barrier | L3 运行核心的 step 调度、可见性和失败传播契约 | 不让模块各自复制一套调度器、Future、取消和重试 | 吸收其边界语义；实现待平台能力登记 |
| `channels`、reducer、`Send`/fan-out | L1 原子状态聚合支持库 + L2 工作流模块装配 | 不把 channel 写入等同于已持久化或已提交 | 吸收其数据流/合并语义，持久化另走 checkpoint |
| `BaseCheckpointSaver`、内存/SQLite/Postgres saver | L0 checkpoint 契约 + L1 存储提供者；L3 在 step/任务边界调用 | 不由每个模块旁路写状态库，不把测试内存实现当生产可靠性 | 吸收契约和后端适配边界 |
| `BaseStore`、memory/SQLite/Postgres Store | L0 共享记忆契约 + L1 Store 提供者；L2 通过 `Runtime.store` 使用 | 不与线程内 checkpoint 合并成一个表或一个 owner | 吸收；与 checkpoint 永久分责 |
| `langgraph` CLI | L4 开发/打包/部署适配工具；部分配置解析可进 L1 | 不成为图执行核心、状态库或凭证 owner | 吸收“配置→应用发现→部署”的边界，不复制 Docker/API server |
| `sdk-py`、SDK 流式 transport | L4 远程客户端/协议适配；HTTP/SSE/WebSocket 是 L1/L4 传输边界 | 不在客户端实现第二个运行时、checkpoint 或取消真相 | 吸收协议和资源关闭契约 |
| `prebuilt` | L2 Agent/工具流程模块 | 不把 ReAct/ToolNode 当平台通用运行核心 | 吸收为可选模块，能力经统一入口调用 |
| `checkpoint-conformance`、现有测试 | 验证与合规证据，不是生产能力 | 不作为运行时依赖或存储后端 | 吸收验证方法，不纳入运行链 |

结论是**单一能力 owner**：L2 只能通过 L1 公开能力和 L3 运行核心提交任务；L4 只能通过统一网关/SDK 契约访问。不得让 CLI 直连 checkpoint 表、SDK 自己重放 Pregel、模块自建线程池，或让不同 provider 各自翻译状态/错误码。

### 13.2 术语到状态与工作流模块的逐项映射

#### 13.2.1 `StateGraph`：状态工作流模块的声明面

源码 `libs/langgraph/langgraph/graph/state.py:131` 明确 `StateGraph` 是 builder，节点签名是 `State -> Partial[State]`；schema 被解析为 channels/managed values，`Annotated` reducer 定义多个节点对同一键的聚合。平台对应关系如下：

1. L0 只定义 `StateSchema`、`PartialStateUpdate`、`ReducerContract`、`BranchDecision`、`InputSchema`、`OutputSchema` 和错误码；schema 不携带连接、线程、锁或 provider 对象。
2. L2 `状态工作流模块` 保存节点、普通边、等待多前驱边、条件分支、输入/输出 schema 和 reducer 声明；它是纯装配/校验对象，不负责实际执行。
3. L1 `channel/reducer` 支持库提供 `LastValue`、`Topic`、`BinaryOperatorAggregate`、barrier、ephemeral 等原子更新语义；模块只选择和组合，不复制实现。
4. `context_schema` 对应运行时只读依赖/上下文，不应混入可持久化 State；例如 `user_id`、数据库客户端、模型配置属于 L3/L4 传入的 run context，资源所有权由运行时声明。
5. 空图、缺边、错误 reducer、输入/输出含非法 managed value 等应在模块校验阶段失败；不能把编译期错误推迟到 provider 或数据库。

**吸收边界：**“声明状态图 + reducer + 分支”可作为模块库模式；LangGraph 的具体 Python 泛型、LangChain Runnable 绑定和兼容弃用 API 不作为平台公共契约原样复制。

#### 13.2.2 `CompiledStateGraph` / `CompiledGraph`：工作流编译产物

`StateGraph.compile()` 在 `state.py:1177-1401` 接收 `checkpointer`、`store`、`cache`、中断点、debug、transformer 等，校验后创建 `CompiledStateGraph`；后者继承 `Pregel`，将 schema/channel 映射成节点和写入器。平台应把它拆成两个对象而不是一个“大运行器”：

```text
状态工作流模块：StateGraph + 编译校验
  → 工作流计划/编译制品：节点表、边表、channel 表、reducer、策略、版本、摘要
  → 运行核心：按运行实例加载计划，创建句柄/租约/任务，执行并提交状态
```

- 编译制品必须内容寻址、版本化、可审计，且绑定能力契约和依赖闭包；编译不应隐式激活第三方 provider。
- L3 每次运行只读取一个不可变计划版本；热切换/回滚由平台发布事务和激活指针治理，不由 `CompiledStateGraph` 自行改变。
- `checkpointer=False` 的语义应保留为“明确无状态且不继承”；`None` 在子图场景可继承父 checkpointer，但平台不能把“默认继承”扩展成全局隐式持久化。
- `cache` 与 checkpoint/store 分开：cache 是结果复用，checkpoint 是执行链恢复，store 是共享记忆；三者不可合表、不可共用一个写 owner。

#### 13.2.3 `Pregel`/BSP：运行核心的可见性和调度契约

`libs/langgraph/langgraph/pregel/main.py:450-477` 给出可直接吸收的三阶段语义：Plan 选择订阅上一轮更新的 actors；Execute 并行运行当前核对 actors；Update 批量应用 writes 到 channels；当前核对更新对当前核对其他 actor 不可见，直到下一 superstep。平台映射为：

| BSP 阶段 | L3 运行核心职责 | L0/L1 依赖 | 必须留证 |
|---|---|---|---|
| Plan | 读取运行快照和触发器，生成有序 task 集合；检查步数/预算/取消 | 图计划、channel 版本、资源预算 | `run_id`、`step`、计划摘要、输入版本 |
| Execute | 监督并发节点，处理成功、异常、重试、超时、取消和中断 | 任务执行器、资源租约、provider 调用器 | task id、attempt、开始/结束、错误/取消原因 |
| Update | 收集 writes，按 reducer/channel 原子生成下一状态 | channel 支持库、版本/CAS、checkpoint 适配 | writes 摘要、channel 版本、提交结果 |

Plan→Execute→Update 是运行核心唯一 owner。L2 不得以“节点循环”绕开 step barrier；L1 不得决定工作流拓扑；L4 不得根据流事件自行推断提交成功。循环终止条件包括无后续 actors、最大步数、取消、超时、失败或人工中断；“返回了部分 stream”不等于工作流成功。

#### 13.2.4 `channels`：状态传播、聚合与动态 fan-out

`Pregel` 文档说明 channel 有 value type、update type、update function；当前源码另有 `LastValue`、`Topic`、`EphemeralValue`、`AnyValue`、`NamedBarrierValue`、`BinaryOperatorAggregate`、`DeltaChannel`、`UntrackedValue`。映射规则：

- `LastValue`：单值状态/输入输出，适合 L1 原子能力，不默认提供历史。
- `Topic`：多写入/发布订阅/累积，必须明确去重、累积周期和上限；不能无界累积。
- `BinaryOperatorAggregate`/reducer：并发 writes 的确定性合并；平台契约必须固定输入顺序、结合性要求、异常语义和超限行为。
- `NamedBarrierValue`：多前驱 join/barrier，是 L3 step 同步语义的输入，不是数据库锁的替代品。
- `EphemeralValue`/`UntrackedValue`：运行期或非持久化状态，必须显式标记；不应在恢复时假定仍存在。
- `DeltaChannel`：增量历史依赖父链与 `_DeltaSnapshot`；其删、复制、裁剪不能按普通 KV 处理，见 §13.4。
- `Context`/managed value：外部资源生命周期上下文，不等于业务 State；创建者、借用者、释放者必须在 L3 记录。

`Send` 的动态 fan-out/map-reduce 对应“一个逻辑节点 → 多个受监督 task → reducer 聚合”的模块契约；并发度、单任务大小、总 fan-out 和失败策略由 L3 预算治理，不能由输入数据无限放大。

### 13.3 持久化、共享 Store 与加密边界

#### 13.3.1 Checkpoint：线程内执行链的权威状态

`libs/checkpoint/langgraph/checkpoint/base/__init__.py` 的 `Checkpoint`/`CheckpointTuple`/`BaseCheckpointSaver` 以及 `put`、`put_writes`、`get_tuple`、`list`、`delete_thread`、异步变体构成可复用契约。checkpoint 至少承载 channel values、channel versions、versions seen、metadata、父 checkpoint 关系和 pending writes；`configurable.thread_id` 是线程主键，`checkpoint_id` 定位历史点。

```text
L3 step/task
  → put_writes(task_id, writes/error/interrupt/resume)
  → Update 应用 channel + 生成新版本
  → put(checkpoint, metadata, new_versions)
  → parent_config 指向前一 checkpoint
  → get/list/history/update_state/Command(resume)
```

- **持久化时机不是“每个 channel write 立即落盘”**：channel 是内存执行语义；是否在每步、异步或退出时写 checkpoint 由运行配置/服务协议决定。
- **部分失败可见性**：pending writes 用于保留节点已产生的中间写入、错误、interrupt/resume 信息；恢复能否避免重复执行取决于 saver、运行时和节点副作用的幂等设计，不能宣称 exactly-once。
- **线程与运行分责**：thread 是状态链容器，run 是一次执行；删除 run 可能破坏仍存活 thread 的 delta 历史，必须由 L3 先做引用/祖先检查。
- **复制和裁剪**：`copy_thread` 必须复制完整父链或足够回溯到每个 DeltaChannel 的 snapshot；`keep_latest` 不能直接删除中间 writes，否则可能静默重建为空。裁剪前要做引用分析、快照重写或拒绝。
- **后端**：内存 saver 仅测试/示例；SQLite/Postgres 是 L1 provider，连接、事务、迁移、并发和故障语义要各自验证；`checkpoint-conformance` 只证明契约一致性，不证明生产可靠性。

#### 13.3.2 Store：跨线程/用户共享记忆

`BaseStore` (`libs/checkpoint/langgraph/store/base/__init__.py:708`) 明确是可持久化、可按 namespace 共享的 key/value store，核心操作为 `get`、`put`、`search`、`delete`、`list_namespaces` 和 batch/async 变体。其 namespace/key/value 不能与 checkpoint 的 thread/checkpoint 主键混淆：

| 维度 | Checkpoint | Store |
|---|---|---|
| 事实 | 一条图运行链的状态快照与 pending writes | 跨 graph/thread/user 的共享记忆/数据 |
| 主键 | `thread_id` + checkpoint namespace/id | `namespace` + `key` |
| 读取 | 恢复/历史/时间旅行 | `get`/过滤搜索/可选语义搜索 |
| 写 owner | L3 step 提交 + L1 saver | 节点经 `Runtime.store` 提交 + L1 store |
| 失败影响 | 可能阻断恢复或破坏父链 | 可能造成共享记忆缺失/脏写 |
| TTL/索引 | 不是 checkpoint 基础契约 | Store provider 可选；默认 TTL/语义索引可能关闭 |

Store 的 TTL、embedding/semantic search 和 batch 语义必须在 provider 契约中显式声明，不能从接口存在推断后端一定支持。L2 模块只能使用公共 `Runtime.store`/Store 入口；不得直接 import SQLite/Postgres 客户端或旁路写数据库。

#### 13.3.3 序列化与加密

`JsonPlusSerializer` 当前默认 msgpack 兼容模式是 permissive 并告警；`LANGGRAPH_STRICT_MSGPACK=true` 或显式 allowlist 才收紧。其源码明确警告：不受信任的 checkpoint 数据若能写入存储，反序列化可能触发危险构造。因此平台映射为：

1. L0 把序列化格式、版本、类型标签、allowlist 命中/拒绝和错误码列入持久化契约。
2. L1 提供纯数据 JSON/受限 msgpack serializer；默认生产策略应是显式 allowlist，禁止“任意模块导入”作为正常路径。
3. L3 在加载 checkpoint 前校验来源、摘要、版本和 allowlist；失败要拒绝恢复并写证据，而不是降级成成功的空状态。
4. `EncryptedSerializer.from_pycryptodome_aes()` 使用 PyCryptodome AES，默认 `AES.MODE_EAX`，`LANGGRAPH_AES_KEY` 或显式 key，key 长度 16/24/32 字节；EAX 结果包含 nonce/tag/ciphertext。源码没有证明 Fernet/AES-GCM，也没有提供 KMS、轮换、密钥托管或访问审计。
5. 加密 serializer 只是 L1 数据保护适配器：启用才加密，不能宣称所有 SQLite/Postgres 文件、日志、stream、Store 或 SDK 传输自动加密；密钥不得写入 checkpoint、配置归档或日志，密钥生命周期由 L4 部署/密钥 provider 管理。

### 13.4 并发、取消、超时、恢复和资源生命周期

#### 13.4.1 并发与一致性

- **BSP 并发**：同一 superstep 的 actor 可并行，但读取的是 step 开始的快照；writes 在 Update 阶段集中合并。并发安全来自 channel/reducer + step barrier，不是 Python dict 的偶然线程安全。
- **异步执行**：`AsyncBackgroundExecutor` 使用当前 event loop；若 `RunnableConfig.max_concurrency` 存在则用 semaphore 限制并发。平台应把 max concurrency、fan-out、队列长度、单步和全运行预算作为 L3 资源契约。
- **同步执行**：`BackgroundExecutor` 使用 thread pool；退出时等待任务完成，只能取消尚未开始的 Future。源码和 functional API 文档明确同步任务不能安全地在进程内取消；不能把 `Future.cancel()` 写成强杀。
- **持久化并发**：SQLite/Postgres saver 的事务/锁/连接池语义属于各 L1 provider；跨运行写冲突必须返回明确版本冲突/重试错误。checkpoint parent/version/CAS 不能由 L2 模块手写。
- **远程并发**：SDK `multitask_strategy` 支持 reject/interrupt/rollback/enqueue 等策略；它是服务端运行协调契约，客户端只提交明确策略，不自行修改线程状态。

#### 13.4.2 取消与超时

- async 节点收到 `asyncio.CancelledError` 时，Pregel 会取消同一步的相关任务；超时 watchdog 取消后台 task 并抛 `NodeTimeoutError`，同时清理 writes。取消、超时、业务错误必须在 L0 使用不同状态/错误码。
- `TimeoutPolicy` 可区分 hard run timeout 与 heartbeat 刷新的 idle timeout；`Runtime.heartbeat()` 只表示进度，不能延长硬截止时间。
- sync 节点不支持安全的进程内 timeout cancellation；若必须硬截止，应由 L3 独立进程/进程组提供者执行并回收，而非在线程里假杀。
- SDK `runs.cancel(thread_id, run_id, wait, action)` 的 action 是 `interrupt` 或 `rollback`；`on_disconnect` 可选择 `cancel`/`continue`。`interrupt` 是可恢复的运行控制，不等价 SIGKILL；`rollback` 的实际状态效果由外部 API server 决定，本仓库 SDK 不证明其内部实现。
- 取消/超时验收必须验证：调用返回、运行终态、checkpoint 是否保留、pending writes 是否可解释、子任务是否停止、HTTP/SSE/WebSocket 是否关闭、线程/连接/临时资源是否无残留。

#### 13.4.3 中断、恢复与崩溃

```text
node → interrupt(value) / interrupt_before/after
  → GraphInterrupt + put_writes(INTERRUPT[, RESUME])
  → checkpoint 链保存可恢复位置
  → 客户端取得 Interrupt
  → Command(resume=value)
  → 节点从中断点所在调用重新执行
  → 后续 Plan/Execute/Update
```

当前文档和测试已证明中断需要 checkpointer；恢复时中断前代码会重新执行。因此：

- 中断前的外部副作用必须幂等、可检测或移到中断之后；不能把“恢复成功”写成 exactly-once。
- 父 checkpoint、pending writes 和 `versions_seen` 是恢复输入；只恢复最终 channel_values 而丢 task writes/父链是不完整恢复。
- 进程崩溃恢复需要 L3 重新读取持久化意图和最后完整 checkpoint，并对运行状态、锁、租约、子进程和未提交 writes 对账；当前 LangGraph OSS 源码没有提供平台级崩溃恢复/锁清理服务，不能越界宣称具备。
- SDK `durability=sync|async|exit` 仅表达远程运行的 checkpoint 持久化时机：`sync` 步后同步、`async` 后台写、`exit` 退出时写。`exit` 模式不能用于要求中途恢复的长运行；断线可恢复流还需 `stream_resumable=true`。

#### 13.4.4 资源生命周期表

| 资源 | 创建/持有者 | 正常释放 | 失败/取消/崩溃要求 | 平台落点 |
|---|---|---|---|---|
| actor task / Future | L3 executor/runner | step 完成或退出时 await/wait | async cancel；sync 只能取消未启动且仍等待；异常写入 task evidence | L3 资源监督 |
| channel/state 内存 | Pregel run | run 结束释放/交给 checkpoint | 不把 ephemeral/context 当持久状态；限制 Topic/fan-out 大小 | L1 + L3 |
| checkpoint DB 连接/事务 | SQLite/Postgres saver | provider close/commit/rollback | 超时回滚、连接断开重连、迁移/锁残留检查 | L1 provider |
| Store 连接、索引/TTL worker | Store provider | close/flush | 取消不得半写；批量写需明确部分成功语义 | L1 provider |
| `Runtime.context` 外部客户端 | 运行上下文创建者 | context manager/ExitStack teardown | 失败、取消、子图退出均释放；借用不得误关 | L3 运行上下文 |
| SSE/WebSocket/httpx 流 | SDK/transport 客户端 | 读到 end 或显式 close | disconnect 按 cancel/continue；重连次数/重复事件可界定 | L4 + L1 transport |
| Docker/Compose/API server | CLI/外部部署系统 | CLI/部署 owner 停止/回收 | 本仓库不证明 server 内部资源清理；必须外部验收 | L4 |
| 模型、工具、文件和临时目录 | provider/节点声明 owner | provider finally/平台资源协调 | 不允许节点把裸 provider 对象穿透 L0；失败和超时仍回收 | L1 provider + L3 |

`Context` 的价值是把外部资源 setup/teardown 作为显式生命周期；它不是“自动解决所有资源泄漏”。平台验收必须覆盖正常完成、业务失败、主动取消/超时、宿主崩溃四种终态，并读回进程、连接、锁、临时目录和文件句柄现场。

### 13.5 CLI、SDK 与远程服务边界

#### 13.5.1 CLI

`libs/cli/langgraph_cli/cli.py` 的 `new`、`dev`、`up`、`build`、`dockerfile`、`deploy` 及 `validate` 读取 `langgraph.json` 的 `dependencies`、`graphs`、`env`、`python_version` 等字段。CLI 的真实职责是应用发现、依赖归档、热加载/开发启动、Docker/Compose 参数装配和部署调用：

```text
langgraph.json
  → CLI validate / dependency tracking / graph path resolution
  → graph_id: module:compiled_graph
  → Dockerfile/Compose/API server 外部运行环境
  → 远程服务注册 assistant/graph
```

平台映射到 L4 `项目适配/开发交付工具`；配置解析中可复用的安全校验才下沉 L1。CLI 不拥有 graph state、checkpoint 表、运行锁或凭证；`langgraph-api`、`langgraph-runtime-inmem` 等服务端/部署组件不在当前仓库 `libs/cli` 内闭合，不能把 `langgraph up` 当作本地运行核心证据。

#### 13.5.2 SDK

`sdk-py` 的 `LangGraphClient` 组合 `assistants`、`threads`、`runs`、`crons`、`store`；同步/异步 runs 支持 `stream`、`wait`、`cancel`，transport 使用 HTTP/SSE，异步场景另有 WebSocket。`runs.stream` 的参数已经暴露 `thread_id`、`checkpoint_id`、`interrupt_before/after`、`stream_resumable`、`durability`、`multitask_strategy` 等运行契约；`schema.py` 将 `RunStatus` 区分 pending/running/error/success/timeout/interrupted。

映射为 L4 远程资源客户端 + L1 transport 支持库：

- SDK 只编码/解码、鉴权头、超时、重连、流事件和资源关闭；不把本地 `StateGraph`/Pregel 复制到客户端。
- `stream` 事件是投影（values/updates/messages/tasks/checkpoints/debug/custom），不是数据库提交回执；客户端需以 run status/服务端终态作为成功判据。
- 同步流是 SSE iterator，异步可用 WebSocket；断开处理必须显式选 `cancel` 或 `continue`，可恢复 stream 必须保存事件游标/服务端支持证据。
- `client.store` 只是远程 Store API，不改变 Store 与 checkpoint 的职责分离。
- `sdk-js` 当前目录只有迁移说明/占位，完整 JS SDK 在独立仓库；不可把占位包列入当前实现能力。

### 13.6 L0-L4 边界与装配计划

#### 13.6.1 边界定义

| 层级 | 允许承载 | 禁止承载 | LangGraph 映射 |
|---|---|---|---|
| **L0 公共契约** | State/Update/Snapshot/Version/Thread/Run/Interrupt/Cancel/Resource/Evidence 类型，稳定错误码和版本字段 | I/O、线程、数据库、第三方 import、隐藏 fallback | State schema、CheckpointTuple、Store Item、RunStatus、stream 事件的语义抽象 |
| **L1 支持库** | channel/reducer、序列化/allowlist/加密、checkpoint/store 后端、HTTP/SSE/WebSocket、原子存储 | 工作流拓扑、跨 provider 业务编排、第二套注册表/任务系统 | `libs/checkpoint*`、channels、serde、SDK transport |
| **L2 模块库** | 状态图声明、编译校验、Agent/Tool 流程、provider 策略组合、工作流计划 | 自建调度/资源监督/旁路写库/直接第三方直连 | `StateGraph`、`CompiledStateGraph` bridge、`prebuilt` |
| **L3 运行核心** | Plan/Execute/Update、superstep、并发预算、重试/超时/取消、checkpoint 时机、恢复、租约、资源和证据 | 具体业务节点、CLI 模板、远程客户端 UI | `Pregel`/runner/loop/retry/executor 的运行语义 |
| **L4 交付与适配** | CLI、项目适配、API server 接入、SDK、认证/部署/网关、外部 provider 配置 | 重新定义 State/Checkpoint/Run 语义，直接改 L3 内存/数据库 | `langgraph_cli`、`sdk-py`、外部 `langgraph-api`/Deployment |

L0-L4 不是按目录机械搬运：`libs/langgraph` 同时包含 L2 Graph API 与 L3 Pregel runtime；迁移时按职责拆分，保持一个公开入口和一个运行核心 owner，而不是照抄仓库目录。

#### 13.6.2 现有能力命中、缺口和裁决

| 能力类别 | 目标单链路落点 | 当前 LangGraph 证据 | 平台缺口/风险 | 裁决 |
|---|---|---|---|---|
| 状态 schema/reducer/channel | L0 + L1 + L2 | `StateGraph` schema/channel；channel 测试丰富 | 需统一状态版本、上限和错误契约 | 吸收 |
| 图编译/计划制品 | L2 → L3 | `compile()` 生成 `CompiledStateGraph` | 需接内容摘要、依赖、激活指针和发布门禁 | 吸收并升级 |
| BSP 调度/barrier | L3 唯一运行核心 | `Pregel` Plan/Execute/Update | 平台需统一任务/资源/证据 owner | 吸收语义，待平台登记 |
| checkpoint/thread/history | L0/L1/L3 | saver + SQLite/Postgres + pending writes | 需统一事务、CAS、崩溃对账、保留策略 | 吸收契约并升级 |
| Store/共享记忆 | L0/L1/L2 | BaseStore + memory/SQLite/Postgres | 需明确 TTL/索引/并发/权限和 owner | 吸收并升级 |
| serde allowlist/AES | L1/L3 安全边界 | strict msgpack 可选；AES-EAX 可选 | 默认 permissive；无 KMS/轮换/全链路加密 | 吸收安全约束，升级为平台密钥能力 |
| async 并发/取消/超时 | L3 | semaphore、task.cancel、timeout watchdog | sync 不可安全取消；进程崩溃治理不闭合 | 吸收边界，复用平台运行核心 |
| CLI/SDK/流式协议 | L4 + transport | CLI 配置/部署；SDK HTTP/SSE/WS | API server 不在仓库闭合；远程终态需外部证据 | 吸收协议，隔离服务实现 |
| Redis Store、完整 JS SDK、API server 内核 | L1/L4 | 当前仓库没有对应闭合实现 | 不得按 README/旧细探补写为已实现 | 废弃为当前事实，待核 |

#### 13.6.3 依赖、资源和验收契约

任何后续平台工作包若要吸收 LangGraph 模式，至少冻结以下契约：

1. **能力契约**：能力 id、版本、输入/输出、reducer 合并语义、可重试/不可重试错误、幂等键、超时、取消、资源释放责任。
2. **调用链**：项目适配/模块 → 唯一能力调用器 → 支持库 → provider/外部服务；禁止 L2/L4 直连具体数据库、HTTP、Docker 或模型。
3. **持久化契约**：thread/run/checkpoint/store 主键、父链、版本、pending writes、durability、删除/复制/裁剪安全条件；明确成功写入与事件投影不等价。
4. **安全契约**：serializer allowlist 默认策略、加密启用标志、密钥来源/轮换/权限、日志脱敏、恶意 checkpoint 拒绝证据；不能只检查“字段非空”。
5. **并发契约**：superstep 可见性、最大并发/fan-out、reducer 确定性、数据库事务/锁、冲突重试；测试必须检查线程异常未被吞、无界队列和重复提交。
6. **取消/恢复契约**：区分 interrupt、timeout、cancel、rollback、crash；记录 run 终态、checkpoint 选择、子任务和资源现场；恢复必须在全新进程验证，不以同进程变量仍在作为重启证据。
7. **资源契约**：正常、业务失败、主动取消/超时、宿主崩溃四种终态均关闭 task、连接、流、进程、锁、临时目录和上下文资源；所有权和转移写进调用链。
8. **验证契约**：源码事实、测试存在、定向真实执行、外部依赖实测、故障注入、残留审计分栏；conformance 通过不能替代 SQLite/Postgres/远程 API 的实测。

#### 13.6.4 装配计划（不表示已启动生产改造）

```text
波次 A：冻结 L0 状态/运行/checkpoint/store/取消/资源契约
  → 只读核对现有公共契约、能力目录、唯一调用器
波次 B：登记并搜索既有 L1 支持库能力
  → channel/reducer、serde/allowlist、加密、checkpoint/store、transport
  → 命中则复用；缺口才申请升级/新建，建立占用租约
波次 C：设计 L2 状态工作流模块与不可变编译计划
  → StateGraph builder / validate / compile / provider 绑定
  → 不在模块中新增 executor、数据库写入或资源中心
波次 D：由 L3 运行核心接入 BSP step
  → Plan/Execute/Update、并发预算、重试、超时、取消、checkpoint 时机
  → 加入租约、资源回收、崩溃恢复和证据
波次 E：L4 CLI/SDK/网关适配
  → 配置/部署/HTTP/SSE/WS/终态查询；不复制运行核心
波次 F：反向破坏与发布门禁
  → provider 缺失、非法 reducer、重复写、断线、取消、超时、进程崩溃、坏密文、坏 checkpoint、DeltaChannel 裁剪/复制
```

当前结论是：**StateGraph/CompiledStateGraph 的声明与编译模式、Pregel/BSP 的可见性语义、channel/reducer、checkpoint/store 契约和 SDK/CLI 边界可作为后续底座输入；运行核心实现、平台级密钥治理、崩溃恢复、资源监督、完整 API server 与 Redis/JS 实现仍需平台能力登记和独立验证。** 本节没有修改平台生产代码，也没有把 LangGraph 外部服务声明成当前源码事实。

## 14. 后续证据与剩余风险

- **源码证据**：`libs/langgraph/langgraph/graph/state.py:131,1177-1401`；`libs/langgraph/langgraph/pregel/main.py:450-477,487-512,708-828`；`libs/langgraph/langgraph/pregel/_retry.py:460-515,573-684`；`libs/langgraph/langgraph/pregel/_executor.py:40-217`；`libs/langgraph/langgraph/runtime.py:124-240`。
- **持久化/安全证据**：`libs/checkpoint/langgraph/checkpoint/base/__init__.py:176-415,468-589`；`libs/checkpoint/langgraph/checkpoint/serde/jsonplus.py:82-254`；`libs/checkpoint/langgraph/checkpoint/serde/encrypted.py:8-80`；`libs/checkpoint/langgraph/store/base/__init__.py:708-944`；SQLite/Postgres 后端及其 tests。
- **交付/远程证据**：`libs/cli/langgraph_cli/cli.py:276-465,758-922`；`libs/sdk-py/langgraph_sdk/_sync/runs.py:195-346,925-1037`；`libs/sdk-py/langgraph_sdk/schema.py:23-31,374-380,607-611`；`AGENTS.md` 依赖关系图。
- **代码图与 MCP 绑定风险**：按任务要求先调用 `system_engineering_toolkit` 的 `project_context`，但该 MCP 返回的根目录是 `/Users/hekunhua/Documents/Agent/PHP/系统工程平台`，随后 `codegraph_explore` 也只查询该平台并明确未命中 LangGraph；它不是目标仓库的代码图证据，已按“错绑阻断”处理，不能写成 LangGraph 事实。此前通过 deferred `project_toolkit` 的查询同样显示目标 LangGraph 没有 `.codegraph/` 索引。本文后续结论因此只采用目标仓库现场源码/测试/AGENTS 证据。
- **当前核对未执行**：未安装依赖、未启动 API server、未运行 CLI/SDK/SQLite/Postgres 端到端，也未修改源码；故无法把外部服务认证、远程取消、数据库事务隔离、密钥轮换和崩溃恢复列为“真实执行通过”。
- **剩余风险**：`CompiledStateGraph` 与 stream transformer/durability 的所有内部调用路径仍需后续按具体工作包取证；CLI 所依赖的 API server/runtime、完整远程权限模型、provider 连接池/锁语义和生产密钥管理不在当前仓库闭合；`DeltaChannel` 的复制/裁剪若实现者忽略祖先链会产生静默状态损坏。

## 15. 后续深挖收口：StateGraph、节点执行、checkpoint、interrupt、stream 与恢复

本节是后续源码收口，不是新的平台设计。它把旧细探中“每步怎么执行、何时写 checkpoint、如何中断/恢复、stream 到底暴露什么”逐条落到当前提交的实现；源码事实、测试证据和当前核对未执行事项分开记录。旧 `细探-langgraph.md` 继续保留，不再作为后续维护入口。

### 15.1 `StateGraph` 的真实声明面和编译产物

| 阶段 | 实现事实 | 证据 |
|---|---|---|
| 声明 | `StateGraph` 是 builder，内部维护 `nodes`、普通边、等待多前驱的 `waiting_edges`、条件 `branches`、schema 对应的 `channels`/`managed`；节点契约是 `State -> Partial[State]`，reducer 签名是 `(Value, Value) -> Value`。 | `libs/langgraph/langgraph/graph/state.py:131-208` |
| schema | `state_schema`、`input_schema`、`output_schema` 分别解析为普通 channel 或 managed value；`input_schema`/`output_schema` 不允许 managed value。`context_schema` 只描述运行期只读上下文，如 `user_id`、数据库客户端等，不是业务 State。 | `state.py:216-270`、`state.py:1444-1547` |
| 校验 | `validate()` 检查 START 入口、边源/目标、条件分支目标和显式 interrupt 节点；没有入口或悬空节点时编译前失败。它不执行节点，也不验证外部 provider 是否可用。 | `state.py:1129-1175` |
| 编译 | `compile()` 先规范化 checkpointer；strict msgpack 开启时从 schema/channel 构建 allowlist；应用默认节点策略；创建 `CompiledStateGraph`（继承 `Pregel`），再 attach START、节点、边、等待边和分支，最后 `validate()`。 | `state.py:1177-1401` |
| 节点绑定 | `attach_node()` 把节点输入 mapper、读取 channel、`ChannelWrite` 更新器和控制分支 writer 组装为 `PregelNode`；普通边写入目标的 branch channel，多前驱边创建 `NamedBarrierValue`，条件边可写普通目标或 `Send`。 | `state.py:1444-1624` |

因此，`StateGraph` 不能直接 `invoke()`；可执行边界是 `compile()` 生成的 `CompiledStateGraph`。编译产物包含拓扑、channel、reducer、节点 runnable、重试/缓存/超时及 checkpointer/store 引用，但它不是持久化数据库、线程池或 provider 连接的 owner。`checkpointer=None` 在根图表示不启用 saver；在子图场景可继承父图，`checkpointer=False` 明确禁止使用/继承，`checkpointer=True` 只用于子图状态化配置，根图使用会报错（`main.py:2579-2588`）。

### 15.2 一次节点执行的可追溯调用链

```text
invoke/stream
  → SyncPregelLoop/AsyncPregelLoop.__enter__
  → _first：装载/创建 checkpoint，应用 input 或 Command writes
  → tick：prepare_next_tasks（PULL 节点 + PUSH/Send 任务）
  → PregelRunner.tick/atick：并发执行 runnable，提交 writes、重试、错误处理
  → after_tick：apply_writes（Update），发 values/updates/tasks/debug，写 loop checkpoint
  → 下一 tick：按 channel version / versions_seen 触发下一批节点
  → 无任务、interrupt、drain 或递归上限 → loop exit，输出最终 channel values
```

1. **Plan / 任务选择**：`prepare_next_tasks()` 先消费 `TASKS` channel 中的 `Send`/PUSH 任务；然后根据上一轮 `updated_channels` 和 `trigger_to_nodes` 缩小候选节点，或退化扫描全部 process。`prepare_single_task()` 只有当触发 channel 的当前版本大于该节点 `versions_seen` 时才创建 PULL task，并为 task 生成稳定 id、task checkpoint namespace、scratchpad、`Runtime.execution_info` 和输入快照。证据：`libs/langgraph/langgraph/pregel/_algo.py:392-513,524-700`。
2. **输入快照**：节点从 step 开始的 channel 副本读取；`local_read(..., fresh=True)` 只在条件路由需要时把该节点自己的 writes 合并进临时副本。节点在同一 step 不能看到其他并行节点刚产生的 writes；这些 writes 只在 `after_tick()` 的 Update 阶段进入 channel。
3. **Execute / 失败传播**：`PregelRunner` 对同 step tasks 使用后台执行器并等待 Future；单任务、无 timeout/waiter 有同步快速路径。一个未被 graph error handler 接管的异常触发 panic，其他任务不再作为成功路径；`GraphBubbleUp`（含 interrupt/parent command）沿图边界传播而非按普通业务异常重试。证据：`_runner.py:135-358`。
4. **Retry**：`run_with_retry()`/`arun_with_retry()` 每次 attempt 前清空 `task.writes`；按首个匹配 `RetryPolicy.retry_on` 决定是否重试，`max_attempts` 包含首次执行，重试时给子图设置 `CONFIG_KEY_RESUMING`。这只重做节点 runnable，不提供外部副作用 exactly-once。证据：`_retry.py:573-684,685-790`。
5. **Update / 确定性**：`apply_writes()` 按 task path 排序，先更新 `versions_seen`，消费被读取的 channel，再按 channel 分组调用 `channel.update(vals)`；可用 channel 的版本推进后才触发下一步。保留 channel/control 写入（`RESUME`、`INTERRUPT`、`ERROR`、`PUSH` 等）不会被当作普通业务 channel 更新。证据：`_algo.py:232-345`。
6. **分支和 fan-out**：`Send` 不是立即递归调用，而是写入 `TASKS`，下一轮变成独立 PUSH task；多个 task 的结果由目标 channel/reducer 汇合。输入 fan-out、单任务 timeout 和总并发没有在该 API 层自动形成无限资源，生产使用必须另设预算。

### 15.3 Checkpoint 的结构、写入时序和可恢复边界

`Checkpoint` 不是只存一个最终 dict，而是由以下字段共同决定下一步：

| 字段/对象 | 语义 | 证据 |
|---|---|---|
| `channel_values` | 可序列化 channel 快照；`DeltaChannel` 非快照点可能省略值，依赖祖先 writes 重建。 | `libs/checkpoint/langgraph/checkpoint/base/__init__.py:92-123`；`pregel/_checkpoint.py:149-214` |
| `channel_versions` | 每个 channel 的单调版本；用于判断触发和新版本。 | 同上 |
| `versions_seen` | 每个节点已看到的 channel 版本；决定下一轮是否触发。 | `checkpoint/base/__init__.py:109-119` |
| `metadata` | `source=input|loop|update|fork`、step、parents、run_id，以及 DeltaChannel snapshot 计数。 | `checkpoint/base/__init__.py:38-86` |
| `parent_config` | 父 checkpoint 的 thread/namespace/id，用于历史链、回放和分叉。 | `checkpoint/base/__init__.py:139-146` |
| `pending_writes` | `(task_id, channel, value)` 中间写入，另含 `ERROR`、`INTERRUPT`、`RESUME` 等控制事实；节点失败/中断后恢复是否重跑由这些写入和 task 状态共同决定。 | `checkpoint/base/__init__.py:31,300-318`；`pregel/_loop.py:415-505` |

实际时序如下：

1. `SyncPregelLoop.__enter__`/`AsyncPregelLoop.__aenter__` 按优先级读取明确 `checkpoint_id`、子图 `ReplayState` 指定的 checkpoint，或线程最新 checkpoint；首次运行没有 saver 记录时使用内存中的 synthetic empty checkpoint（metadata step `-2`），并不等于已经持久化。证据：`_loop.py:1629-1709`。
2. `_first()` 区分 fresh input、`Command`、`input=None` 的 resume/time-travel；fresh input 经过 `apply_writes()` 后写 `source=input` checkpoint，已有 checkpoint 的继续执行会保留 pending writes 和 resume map。没有 checkpointer 时 `Command(resume=...)` 明确报错。证据：`_loop.py:848-1079`。
3. 每次 `after_tick()` 先收集 task writes，再 `apply_writes()`，然后 `_put_checkpoint({"source": "loop"})`；因此普通 `sync`/`async` 模式下 checkpoint 是 step 边界的状态快照，不是每一次 channel write 的即时数据库提交。证据：`_loop.py:683-724`。
4. `_put_checkpoint()` 计算 delta snapshot、更新 metadata counter、计算 `new_versions`，通过 saver `put()` 写入；写入 future 按前一 checkpoint 串行化。涉及 `DeltaChannel` 的 `put_writes()` future 会先 drain，避免 checkpoint 先可见而它依赖的 writes 尚未落盘。证据：`_loop.py:1081-1219,1530-1547`。
5. 三种 durability 只改变 checkpoint 提交时机：`sync` 在下一步前等待 checkpoint future；`async` 后台提交并与下一步执行重叠；`exit` 中间步骤不写完整 checkpoint，在退出/中断/错误路径收集并落盘。没有 checkpointer 时 durability 不生效并发 warning。证据：`types.py:89-94`、`main.py:2602-2613,2984-2988`、`_loop.py:1321-1335`。
6. saver 的最小可替换契约是 `get_tuple/list/put/put_writes` 及 async 版本；`get_tuple()` 返回 checkpoint、metadata、parent_config、pending_writes 的组合。`thread_id` 是必要主键；没有 `thread_id`/`checkpoint_ns`/`checkpoint_id` 等 configurable 键时，启用 saver 的根图在 `_defaults()` 阶段拒绝。证据：`checkpoint/base/__init__.py:176-318,429-509`、`main.py:2579-2593`。

**恢复不是“读取最终 state 后从头跑”**：运行时要同时恢复 channel versions、versions seen、父链和 pending writes；`tick()` 会先用 pending writes 标记已成功 task、恢复 error handler，再只执行需要重做的任务。因而恢复语义是“从 checkpoint 的下一执行边界继续”，不是 exactly-once 事务。外部写文件、发请求、扣费等副作用必须幂等或有去重键。

### 15.4 `interrupt`、节点级 interrupt 和 `Command(resume=...)`

| 机制 | 发生位置 | 当前实现 |
|---|---|---|
| `interrupt(value)` | 节点函数内部 | 从 task scratchpad 取得当前 interrupt 序号；若已有对应 resume 值则返回它，否则抛 `GraphInterrupt`，interrupt id 由 checkpoint namespace hash 得到。 | `libs/langgraph/langgraph/types.py:851-974` |
| `interrupt_before` | `tick()` 执行前 | `should_interrupt()` 检查自上次 interrupt 后是否有 channel 更新，再匹配 task 名；命中则状态为 `interrupt_before`，不运行该 task。 | `_loop.py:666-672`；`_algo.py:155-185` |
| `interrupt_after` | `after_tick()` 完成并写 loop checkpoint 后 | 命中后状态为 `interrupt_after`，因此节点 writes 已进入当前 checkpoint，再暂停后续节点。 | `_loop.py:683-724` |
| `Command(resume=value)` | 下一次 `invoke/stream` 输入 | `_first()` 将 resume 写入对应 task；单个未决 interrupt 可给单值，多未决 interrupt 必须按 id 提供 map；没有 checkpointer 直接报错。 | `_loop.py:902-931` |

`interrupt()` 的 resume 值按**同一 task 内调用顺序**匹配，不按全图节点名匹配；多次 interrupt 不能在恢复时重排。节点从函数开头重执行，interrupt 之前的日志、随机数、外部副作用都会再次发生。测试明确断言：第一次暂停后 `Command(resume=...)` 会使 interrupt 节点执行次数加一；从历史点 replay 会重新触发 interrupt，而历史点之前的节点不重跑。证据：`types.py:858-870`；`libs/langgraph/tests/test_time_travel.py:226-281`。

根图会在 context manager 退出时抑制 `GraphInterrupt`，将中断事实写入 pending writes/stream，并把当前 channel 输出交给调用方；嵌套图的 interrupt 先在子图边界传播，父图负责最终暂停/恢复。`GraphLifecycleEvent` 还为 interrupt/resume 提供 callback 事件，但 callback 是观测面，不替代 checkpoint。证据：`_loop.py:1317-1375`、`callbacks.py:42-110`。

### 15.5 `stream` 是运行事件投影，不是提交回执

当前 `StreamMode` 有七种：`values`、`updates`、`messages`、`custom`、`checkpoints`、`tasks`、`debug`（`types.py:122-124`）。

| 模式 | 负载 | 生成时机/注意点 |
|---|---|---|
| `values` | 每 step 后的完整输出 channel 值；可带 interrupts | `after_tick()` 或中断收尾时生成；不是每个节点 token，也不是数据库 commit ack。 |
| `updates` | 节点名/任务名到本次返回更新的映射；同 step 多节点可分开 | task 完成或 cached writes 输出；interrupt 以 `__interrupt__` 控制键投影。 |
| `messages` | `(message_chunk, metadata)`，可 token 级 | 通过 callback handler 观察 LLM runnable，metadata 含 step/node/triggers 等；不等价于 state update。 |
| `custom` | 节点 `StreamWriter` 主动写入的任意值 | 需要 `custom` handler；业务必须自行定义事件 schema、顺序与重放语义。 |
| `checkpoints` | checkpoint/debug payload | 在 checkpoint 观察点发出，包含 state/checkpoint metadata 等；事件到达客户端不证明远端 durable 写已成功。 |
| `tasks` | task start/result、error、interrupt | 适合诊断执行边界；task event 不是最终 run status。 |
| `debug` | 对 checkpoint/task 的包装诊断事件 | 信息最丰富，不能当稳定业务 API。 |

`stream()` 通过 `SyncQueue`/`AsyncQueue` 接收 loop 的 `_emit()`，节点执行期间按需 yield；`subgraphs=True` 时事件增加 namespace 路径（含父节点和 task id）。同步流使用 runner waiter 让节点完成/流事件交错产出；异步流使用 event loop 的 thread-safe queue。证据：`main.py:2748-2999,3156-3330`、`_loop.py:1380-1459`。

v1/v2 的关键差异不是“执行两次”：v1 在 `invoke(stream_mode="values")` 内部同时收集 `updates` 和 `values`，从 updates 的 `__interrupt__` 提取中断；v2 的 values part 直接携带 `interrupts`，非 values 模式返回带 `type/ns/data` 的 typed `StreamPart`。证据：`main.py:3836-3957`、`types.py:264-367`。因此客户端不能用“收到最后一个 values chunk”替代 run 终态，也不能把 stream 断线自动推断成取消或成功。

### 15.6 持久化后端、DeltaChannel 和历史分叉的限制

- **Memory saver**：源码位置和测试存在，适合测试/示例；不能作为跨进程可靠持久化证据。
- **SQLite saver**：`SqliteSaver` 建立 `checkpoints` 与 `writes` 表，以 `(thread_id, checkpoint_ns, checkpoint_id)` 标识 checkpoint，以 task/index 保存 writes；默认是轻量同步场景，源码文档明确“不适合多线程扩展”，异步要用 `AsyncSqliteSaver`。`get_tuple()` 无 checkpoint id 时取线程/namespace 最新项，有 id 时取精确项，再读取该 checkpoint 的 pending writes。证据：`libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py:45-95,129-166,191-293`。
- **Postgres saver**：当前库提供同步/异步 saver 与 Store；首次使用需要 setup，连接约束和事务语义仍需外部数据库实测，当前核对没有连接真实 Postgres。
- **DeltaChannel**：非每个 checkpoint 都保存完整值，而是按 `snapshot_frequency` 或全局 superstep 上限生成 `_DeltaSnapshot`；恢复若当前 `channel_values` 缺失该键，saver 必须沿父链取 seed 并累积 `checkpoint_writes`。因此 `copy_thread` 必须复制足够完整的父链；朴素 `keep_latest` 删除中间 checkpoint/writes 可能静默把恢复值重建为空。证据：`pregel/_checkpoint.py:50-71,149-277`、`checkpoint/base/__init__.py:350-415`。
- **时间旅行/replay**：指定历史 `checkpoint_id` 时读取精确 checkpoint；`_first()` 在真正 replay 且来源不是 `update/fork` 时先写 `source=fork` checkpoint，避免新分支继续覆盖旧 head；`update_state()` 以 `source=update` 生成状态更新 checkpoint，随后从该分支继续。测试覆盖“历史点之前节点不重跑、之后节点重跑、多个 fork 互不污染、interrupt replay 会再次触发”。证据：`_loop.py:874-971`、`main.py:1640-2047`、`tests/test_time_travel.py:69-219,226-380`。

### 15.7 后续失败/恢复矩阵与验证等级

| 场景 | 源码行为 | 测试/外部验证状态 |
|---|---|---|
| 无 graph 入口、悬空边、非法 interrupt 节点 | `StateGraph.validate()` 编译前拒绝 | 测试文件存在；当前核对未执行 |
| 多节点同 step 写同一 key | 按 task path 排序后交给 reducer；无 reducer 或非法多写由 channel 抛更新错误 | `test_state.py`/`test_pregel.py` 存在；当前核对未执行 |
| 节点业务异常 | retry policy 匹配则重试；否则 runner panic；配置 error handler 时可转 handler | `test_retry.py` 等存在；当前核对未执行 |
| async node timeout / cancellation | watchdog 取消 async task，清空 writes，抛 `NodeTimeoutError`；同步节点 timeout 在运行时安全性上不支持 | `test_pregel_async.py`/timeout 相关测试存在；当前核对未执行 |
| `interrupt()` | 保存中断信息并暂停；必须有 checkpointer；resume 后从节点开头重跑 | `test_interruption.py`、`test_time_travel.py` 存在；当前核对未执行 |
| 断点恢复 | 读取 checkpoint + parent + pending writes + versions；成功 writes 可复用，未完成/控制 writes 按状态处理 | checkpoint/time-travel/subgraph persistence 测试存在；当前核对未执行 |
| 历史 replay/fork | 精确 checkpoint 重放，必要时先产生 fork；旧分支保持独立 | `test_time_travel.py` 明确覆盖；当前核对未执行 |
| saver 序列化坏数据/不受信类型 | JsonPlus 默认 permissive 并告警；strict msgpack/allowlist 可拒绝；加密 serializer 可选 AES-EAX | `test_serde_allowlist.py` 等存在；当前核对未执行 |
| stream 断线/客户端取消 | 本地 loop/SDK 可观察流和控制参数，但远程 server 的断线策略、run rollback 语义不在此仓库闭合 | SDK/stream 测试存在；真实 API server 未启动 |
| SQLite/Postgres 故障、事务隔离、跨进程崩溃恢复 | saver 提供接口/部分实现；平台级锁清理、进程重启对账、exactly-once 副作用恢复未由当前 OSS core 提供 | conformance/后端测试存在；当前核对未连接真实数据库 |

**验证口径：**当前核对只读当前源码、测试源码、README/AGENTS 和旧细探，未安装依赖、未启动服务、未执行 `make test`、未连接 SQLite/Postgres 做端到端或故障注入。因此上表“测试文件存在”不等于“当前核对通过”，没有把静态证据冒充真实执行。

### 15.8 旧细探逐条收口（后续补充）

| 旧细探说法 | 当前裁决 | 收口后的准确表述 |
|---|---|---|
| “BFS superstep、BEFORE/AFTER 依赖” | 不吸收原词 | 当前实现是 Pregel/BSP 的 Plan→Execute→Update；由 channel version/`versions_seen` 和 branch/join channel 决定触发，不能写成通用 BFS。 |
| “Channel 读写统一走 checkpoint” | 不吸收原词 | channel 是运行期对象；checkpoint 在输入、loop、update/fork 或退出 durability 边界保存快照及 pending writes。 |
| “每 superstep 必然持久化” | 不吸收原词 | 只有配置 saver 才持久化；`sync`/`async`/`exit` 决定时机，且 `exit` 中间步骤不保存完整 checkpoint。 |
| “AES = Fernet/AES-GCM” | 不吸收原词 | 当前 `EncryptedSerializer` 证据为 PyCryptodome AES，默认 EAX；不把旧算法名当事实。 |
| “Store 有 Redis 后端” | 不吸收原词 | 当前工作区确认 Store base/memory 与 SQLite/Postgres 相关实现；`cache/redis` 不能推导出 `store/redis` 已交付。 |
| “恢复就是从 checkpoint state 继续” | 校正 | 恢复还需要 versions_seen、父 checkpoint、pending writes、resume map 和 task 状态；节点外部副作用仍需幂等。 |
| “stream 是状态结果” | 校正 | stream 是 values/updates/messages/custom/checkpoints/tasks/debug 的事件投影；客户端成功判据应结合最终输出/运行终态和 durable checkpoint，而不是单个事件。 |
| “对平台的同构建议” | 不属于当前核对项目事实 | 平台 L0-L4 映射只保留在现有后续章节；本节只维护 LangGraph 当前源码实现。 |

当前核对后续结论：LangGraph 的可恢复性来自 **版本化 channel 状态 + `versions_seen` 触发判定 + task pending writes + 父 checkpoint 链 + 可选 serializer/saver** 的组合，而不是一个“状态 dict 自动保存”开关；`interrupt` 是在 task scratchpad 上按调用顺序匹配的可恢复控制流；`stream` 是从 runner/loop 投影出的观测协议；节点执行、重试、超时、取消和外部副作用的 exactly-once 语义并未由 OSS core 自动保证。上述边界已吸收到本文件，旧细探保留但不再维护。

## 16. 源码核对补录：从图声明到资源回收的完整运行链

本节是对根 `ARCHITECTURE.md` 与旧 `细探-langgraph.md` 的再次源码核对，专门收口图状态、节点、边、checkpoint、线程、流式、任务、Store、取消、恢复和资源生命周期。证据以当前工作区源码为准；旧细探中与源码不符的 “BFS/BEFORE-AFTER”“channel 读写统一即时 checkpoint”“每步必然持久化”“同步任务可强制取消”等说法不再采用。

### 16.1 图、状态、节点和边：声明对象不是运行对象

```text
StateGraph(state_schema, input_schema, output_schema, context_schema)
  ├─ channels / managed values       状态键的读写与生命周期语义
  ├─ nodes[name]                     节点 runnable、输入 mapper、写入器
  ├─ edges                           普通边与多前驱 waiting edge
  └─ branches                        条件路径、path_map、Send fan-out
          │ validate()
          ▼
  compile(checkpointer, store, cache, retry, interrupt, durability)
          │
          ▼
  CompiledStateGraph (Pregel)
          │
          ▼
  Sync/AsyncPregelLoop → PregelRunner → superstep task writes
```

- `StateGraph` 是 builder；节点的事实契约是读取 State/Runtime 并返回部分状态更新，不是直接修改共享状态。`Annotated` reducer 决定同一 channel 在并发 writes 下如何聚合；没有 reducer 的单值 channel 不能被假定为无冲突合并。
- 普通边通过 branch channel 触发目标节点；多前驱边由 `NamedBarrierValue` 等等待语义汇合；条件边的返回值可映射到固定目标，也可通过 `Send` 产生独立 PUSH task。边描述触发拓扑，不是函数调用栈。
- `compile()` 才装配节点输入读取、`ChannelWrite`、branch writer、retry/cache/timeout 策略及 checkpointer/store 引用，并再次执行图校验。编译产物不是线程池、数据库连接或 provider 资源的 owner。
- `context_schema` 描述一次运行的只读依赖（例如用户标识、数据库连接或配置），不应混入可持久化 State。`Runtime` 还暴露 `store`、`stream_writer`、`heartbeat`、`execution_info` 和协作式 `control`，这些是运行上下文，不是图状态字段。

### 16.2 节点任务和 superstep：Plan → Execute → Update

```text
tick()
  → prepare_next_tasks()
      消费 TASKS 中的 PUSH/Send；按 channel version 与 versions_seen 生成 PULL tasks
  → PregelRunner.tick/atick()
      并发运行 runnable；每个 task 拥有 id、attempt、scratchpad、输入快照和 writes
  → after_tick()
      apply_writes()；推进 channel/version；发事件；提交 loop checkpoint
  → 下一 tick 或 done / interrupt / draining / error
```

- 一个 superstep 的节点读取 step 开始的 channel 快照；并行节点当前核对产生的 writes 在 `after_tick()` 的 Update 阶段前对其他节点不可见。`versions_seen` 与 channel version 的比较决定下一轮是否重新触发。
- `Send` 是写入 `TASKS` 的动态 fan-out，不是节点内部递归调用。下一轮会为每个分支建立独立 PUSH task，再由目标 channel/reducer 汇合；fan-out 数、并发数、单任务大小和总运行预算必须由外部运行治理限制。
- `PregelRunner` 对 task 进行并发提交、逐个收集完成结果并提交 writes；未被节点/图级 error handler 接管的异常会触发 panic，其他任务被停止或不再作为成功路径。错误 handler 会标记原 task 的错误写入并调度 handler task，而不是无条件重跑原节点。
- retry policy 作用于 runnable attempt：每次 attempt 前清理该 task 的 writes，匹配策略后重试；它不为外部副作用提供 exactly-once。节点应使用幂等键或将不可逆副作用放在可恢复边界之后。

### 16.3 Checkpoint、thread、run 与恢复边界

```text
configurable.thread_id
  └─ checkpoint namespace
       ├─ checkpoint_id / parent_config  历史链与分叉
       ├─ channel_values                  当前可恢复值
       ├─ channel_versions                触发版本
       ├─ versions_seen                   各节点已消费版本
       ├─ metadata                        source、step、run 等
       └─ pending_writes                  task 写入及 ERROR/INTERRUPT/RESUME 控制事实
```

- `thread_id` 是一条状态链的容器标识；`run_id` 是一次执行，不应与 thread 混为同一生命周期。启用 saver 的根图需要有效的 `thread_id` 等 configurable 字段；没有 checkpointer 时，首次运行可使用内存 synthetic checkpoint，但不表示已经持久化。
- 一般 loop 在 `after_tick()` 中先 `apply_writes()`，再按 durability 写入 checkpoint。`sync` 在继续下一步前等待写入，`async` 允许后台写入与下一步重叠，`exit` 主要在退出/中断/错误路径保存，不可用来宣称中途可恢复。
- `pending_writes` 不是可忽略的日志：恢复时已成功 task 的普通 writes 会被重新应用，`ERROR`/`INTERRUPT`/`RESUME` 等控制写入会影响哪些 task 重跑或进入 error handler。只读取最终 `channel_values` 会丢失执行边界信息。
- `interrupt()` 保存 task scratchpad 的中断序号和 resume 信息；`Command(resume=...)` 按同一 task 内调用顺序恢复，多中断时需按 id 提供映射。恢复会从中断节点函数开头重新执行，因此中断前的副作用、日志和随机操作必须可重复或幂等。
- 指定历史 `checkpoint_id` 的 replay 会从历史点建立 fork/update 分支，父链保持可追溯；`get_state_history`、`update_state` 和 bulk update 是历史/分叉 API，不是对旧 checkpoint 的原地覆盖。`DeltaChannel` 还依赖父链 writes 重建值，复制或裁剪前必须保留足够祖先链。

### 16.4 流式：事件投影，不是提交回执

核心 stream/astream 通过同步或异步队列接收 loop 的 `_emit()`；可组合的模式包括 `values`、`updates`、`messages`、`custom`、`checkpoints`、`tasks` 和 `debug`。

| 模式 | 主要事实 | 不应推断 |
|---|---|---|
| `values` | step 后输出 channel 值，可能携带 interrupt | 不是数据库提交确认，也不是每个 token |
| `updates` | 节点/task 的部分状态更新 | 不等于最终 run 成功 |
| `messages` | LLM callback 的消息/token chunk 与 metadata | 不等于 state 已写入 |
| `custom` | 节点通过 `stream_writer` 主动发出的业务事件 | 顺序、幂等和重放需应用定义 |
| `checkpoints` | checkpoint 观察/诊断 payload | 客户端收到事件不证明远端 durable 写已成功 |
| `tasks` | task start/result/error/interrupt | 不是最终运行状态 |
| `debug` | task/checkpoint 的详细诊断包装 | 不应直接当稳定业务 API |

`subgraphs=True` 时事件带 namespace 路径，通常包含父节点和 task id。同步执行的线程任务不能被安全地在线程内强杀，因此含 `messages`/`custom` 等流的同步路径会采用 waiter/队列交错输出；客户端断流必须显式决定取消还是继续，不能从“最后收到一个 chunk”推断成功、取消或持久化完成。

### 16.5 线程、任务、取消和超时

- 同步 `BackgroundExecutor` 使用 thread pool；退出时可调用 `Future.cancel()`，但这只取消尚未开始的任务，随后仍等待已提交任务结束。已运行的同步 Python 节点不能被安全地在线程内抢占；硬截止应交给独立进程/进程组和外部回收器。
- 异步 `AsyncBackgroundExecutor` 使用当前 event loop；`max_concurrency` 通过 semaphore 限制并发。退出时对标记任务调用 `task.cancel()` 并等待所有任务收尾，`CancelledError` 与 `GraphBubbleUp` 不应被当成普通业务成功。
- runner 级 timeout 会取消仍在途的 async task、清理相应 writes 并报告 timeout；heartbeat 只能刷新 idle timeout，不得延长硬 run deadline。取消、超时、业务异常、人工 interrupt 和 draining 必须保持不同的终态/错误语义。
- `Runtime.control` 的 drain 是协作式排空：loop 在下一调度边界看到 `drain_requested` 后进入 `draining`，不是强杀当前节点。SDK 的 `cancel`、`interrupt`、`rollback`、断线 `cancel_on_disconnect` 等是远程服务控制协议；当前仓库 SDK 只编码参数和请求，不能反推外部 API server 内部的 rollback 或锁清理实现。

### 16.6 Store 与 checkpoint 的双存储边界

```text
线程内执行链：task → channel update → checkpoint saver
跨线程共享记忆：node/runtime.store → namespace + key + value → Store
```

- checkpoint 保存一条 graph thread 的恢复链、版本、父关系和 pending writes；Store 的 `namespace/key/value` 用于跨 graph、thread 或 user 的共享数据。两者不能共用主键、表语义或写入 owner。
- 节点经 `Runtime.store` 使用 `get/put/search/delete/list_namespaces` 及 batch/async 变体；embedding、语义搜索、TTL、索引、批量部分成功语义属于具体 provider 契约，接口存在不代表所有后端都启用这些能力。
- 当前仓库确认 memory、SQLite、Postgres 相关 Store/checkpoint 实现；`cache/redis` 不能推导出 `store/redis` 已交付。Store/数据库连接、事务、索引和 TTL worker 由 provider 持有并关闭，模块不得旁路直连数据库。

### 16.7 资源生命周期闭环

| 资源 | 创建/持有者 | 正常结束 | 失败、取消、崩溃要求 |
|---|---|---|---|
| Pregel task/Future | loop、runner、executor | task 完成后回调移除；step 结束等待 | async cancel；sync 只能取消未启动 Future；记录 attempt/error |
| channel、scratchpad、临时状态 | 当前 Pregel loop | loop context 退出释放 | 不把 ephemeral/context 当持久化值；限制 Topic、TASKS 和 fan-out |
| checkpoint saver 连接/事务 | SQLite/Postgres provider | commit/rollback 后 close | 超时回滚、连接断开重连、锁/迁移残留审计 |
| Store 连接、索引、TTL worker | Store provider | flush/close | 批量写部分成功语义明确；取消不得遗留半写资源 |
| `Runtime.context` 外部客户端 | 运行上下文创建者 | context manager/ExitStack teardown | 失败、取消、子图退出均释放；借用资源不得误关 |
| SSE/WebSocket/httpx stream | SDK transport | end 或显式 close | 断线按 cancel/continue；重连、游标、重复事件可界定 |
| 模型、工具、文件、临时目录 | provider/节点声明 owner | provider `finally` 或资源协调器 | timeout/cancel/crash 后仍须回收；不得把裸 provider 穿透公共状态 |

核心 loop 使用 `ExitStack`/`AsyncExitStack` 管理同步/异步 executor，并在退出时等待任务；这保证的是进程内上下文收尾，不是宿主崩溃后的自动清理。要证明崩溃恢复，必须在全新进程中重读 checkpoint、核对 run 状态、租约、子任务、数据库连接、文件句柄、临时目录和未提交 writes；当前 OSS core 没有提供平台级崩溃协调器，也没有为外部副作用提供 exactly-once 保证。

### 16.8 本次核对结论

当前源码可闭合的主链是：**StateGraph 声明 schema/节点/边 → compile 装配 CompiledStateGraph → Pregel loop 按 channel version 规划 task → runner 执行并提交 writes → Update 产生新状态 → 按 durability 写 checkpoint → stream 投影事件 → thread/history/store 提供恢复与共享读取**。旧细探可作为历史线索，但以下说法必须视为已纠正：

1. 调度是 Pregel/BSP 的 Plan→Execute→Update，不是泛化 BFS 或固定 BEFORE/AFTER 依赖。
2. channel 是运行期状态对象；checkpoint 是可选、按运行边界持久化的快照，不是每次写入的即时落盘。
3. 线程是 checkpoint 链容器，run 是一次执行；恢复依赖 versions、父链、pending writes 和 task 控制事实。
4. stream 是观测/业务事件投影，最终成功必须结合 run 终态和 durable checkpoint 判定。
5. 同步线程任务不能安全抢占；取消、timeout、interrupt、draining 和 rollback 的语义不同。
6. Store 是跨线程共享记忆，不是 checkpoint 的别名；Redis、完整 API server、JS SDK 和平台级崩溃恢复不能由当前仓库源码推断为已实现。

## 17. 当前核对完整审计补录：调用关系、测试面与文档质量

本节记录当前核对按用户指定范围进行的分段读取结果。目标仓库没有 `.codegraph/` 索引；已先尝试 `codegraph explore "StateGraph Pregel ..."`，工具明确返回索引不存在，因此没有自行初始化索引，也没有把代码图结果冒充为调用链证据。以下调用关系来自当前源码逐段核对，范围包括 `libs/langgraph/langgraph`、`libs/checkpoint*`、核心测试、包配置、根 README、`docs/` 和本文件。

### 17.1 StateGraph → Pregel 的实际调用关系

```text
StateGraph.__init__
  → _add_schema(state/input/output)
  → channels + managed values + nodes/edges/branches
  → validate()
  → compile()
      → ensure_valid_checkpointer()
      → strict msgpack 时构建 schema/channel allowlist
      → 解析 output_channels/stream_channels
      → 注入 builder node defaults
      → 创建 CompiledStateGraph(Pregel)
      → attach START/nodes/edges/waiting_edges/branches
      → CompiledStateGraph.validate()
  → invoke()/stream()/ainvoke()/astream()
      → SyncPregelLoop/AsyncPregelLoop
      → prepare_next_tasks()
          → TASKS channel 中的 Send → PUSH task
          → channel version + versions_seen → PULL task
      → PregelRunner.tick()/atick()
          → runnable / retry / cache / timeout / error handler
      → apply_writes()
          → task path 稳定排序
          → reducer/channel.update()
          → channel versions + versions_seen
      → _put_checkpoint()（由 durability 决定等待时机）
      → values/updates/messages/custom/checkpoints/tasks/debug stream
```

关键裁决：`StateGraph` 只保存声明和装配数据，`compile()` 才将图变成可执行对象；`CompiledStateGraph` 继承 `Pregel`，但不拥有线程池、数据库连接或外部 provider。`validate()` 检查入口、边目标和显式 interrupt 节点，不会验证模型、数据库或 API server 是否可用。

`compile()` 的具体装配事实是：

- `None` checkpointer 可在子图场景继承父图，`False` 禁止使用或继承，启用 saver 时调用方应提供 `configurable.thread_id`；根图使用 `True` 不成立。
- 开启 strict msgpack 时，状态/输入/输出/context schema、节点输入 schema、分支输入 schema 与 channels 被用于生成 allowlist，并通过 `apply_checkpointer_allowlist()` 注入 saver。
- 默认 retry、cache、error handler、timeout 在 compile 阶段应用；error handler 不处理自身，retry/timeout 可作用于 handler，cache 不作用于 handler。
- START 使用输入 schema 的 `EphemeralValue`；普通边、等待多前驱边和条件分支分别 attach 为 branch channel、barrier 语义和 branch writer。条件分支返回的 `Send` 不在当前节点内递归执行。

### 17.2 channels、Send、checkpoint 与 Store 审计

`apply_writes()` 对 task path 做稳定排序，然后先更新 `versions_seen`、消费触发 channel，再按 channel 分组调用 `update(vals)`。`RESUME`、`INTERRUPT`、`ERROR`、`PUSH` 等保留 channel 不会被当作普通业务 channel 更新；可用 channel 的新版本才会触发下一轮。由此可以确认 reducer/channel 是并发合并和可见性边界，而不是 Python 容器偶然提供的并发安全。

`Send(node, arg, timeout=...)` 允许条件边将不同输入动态发往同一节点。发送结果先进入 `TASKS`，下一轮由 `prepare_next_tasks()` 建立 PUSH task；目标节点的 reducer/channel 再负责汇合。接口本身没有替调用方建立总 fan-out、单任务大小、队列长度或资源预算，输入规模必须由上层运行治理限制。`Command.goto` 也可以承载单个或多个 `Send`，因此动态路由不能只审计 `add_conditional_edges()`。

Checkpoint 不是最终 state 的单一字典：`channel_values`、`channel_versions`、`versions_seen`、metadata、`parent_config` 和 pending writes 共同决定恢复边界。每个 loop step 在 `after_tick()` 中先 `apply_writes()`，再按 durability 写 loop checkpoint；`sync` 等待写入，`async` 与下一步重叠，`exit` 主要在退出/中断/错误路径落盘。DeltaChannel 在非快照点依赖父链 writes 重建值，复制、删除和裁剪必须保留足够祖先证据。

Store 与 checkpoint 分责：Store 的 `namespace + key + value` 面向跨 graph/thread/user 的共享记忆，提供 `get/put/search/delete/list_namespaces` 及 batch/async 变体；embedding、TTL、索引和部分成功语义属于具体 provider，不能由基础接口推断。当前源码与目录确认 memory、SQLite、Postgres 相关实现；`cache/redis` 不等于 `store/redis`。

### 17.3 retry、interrupt/resume、stream、取消与资源

- **Retry**：`run_with_retry()` / `arun_with_retry()` 在每次 attempt 前清空 task writes，按首个匹配的 `RetryPolicy.retry_on` 决定是否重试，支持 backoff/jitter；async timeout watchdog 会取消后台 task、清空 writes 并抛 `NodeTimeoutError`。重试只重做 runnable，不保证节点外部副作用 exactly-once。
- **Interrupt/resume**：`interrupt()` 使用 task scratchpad 的调用序号匹配 resume 值，首次调用抛 `GraphInterrupt`；`Command(resume=...)` 在下一次运行中提供单值或 interrupt id 映射。恢复从节点函数开头重新执行，必须有 checkpointer；中断前的写文件、网络请求、扣费和随机操作需要幂等或去重。
- **Stream**：`values` 是 step 后状态投影，`updates` 是节点/任务部分更新，`messages` 是模型 callback 流，`custom` 是节点主动写入，`checkpoints/tasks/debug` 是观察与诊断投影。任一 chunk 都不是 durable commit ack 或最终成功判据；客户端应结合 run 终态和持久化事实判断结果。v3 `stream_events` 还要求 transformer factory 可按 subgraph scope 创建，预构造实例会被拒绝。
- **取消/资源**：async task 可协作取消，runner 会等待清理；同步 thread pool 只能取消尚未开始的 Future，不能安全抢占已运行节点。`Runtime.control` 的 drain 是在调度边界排空，不是强杀。SQLite/Postgres 连接、Store 后台批处理任务、SSE/WebSocket、Runtime context、工具/模型和临时目录都必须由各自 owner 在正常、异常、取消/超时路径关闭；宿主崩溃后的租约、锁、子进程和外部副作用不由 OSS core 自动治理。

### 17.4 测试、配置与 docs 覆盖审计

测试源码覆盖面较完整但当前核对未执行：

- `libs/langgraph/tests/test_state.py`、`test_pregel.py`、`test_pregel_async.py`、`test_algo.py`、`test_channels.py` 覆盖图校验、BSP 执行、async/sync、channel/reducer、版本和大量边界场景。
- `test_retry.py` 覆盖异常匹配、backoff、同步/异步重试、timeout、CancelledError 转换、Send/Command 相关路径；`test_interruption.py`、`test_time_travel.py`、`test_interrupt_migration.py` 覆盖 interrupt、durability、resume、历史 replay/fork。
- `test_stream_*` 与 `test_stream_events_v3*` 覆盖 values/updates/messages/custom/checkpoints/tasks/debug、subgraph namespace、transformer、同步/异步 stream 和中断投影。
- `libs/checkpoint/tests/test_store.py` 覆盖 async batch、单查询取消后后台任务恢复、namespace/search；`test_jsonplus.py`、`test_serde_allowlist.py` 覆盖序列化类型与 allowlist；SQLite/Postgres 测试覆盖后端契约、迁移、delta 和同步/异步 API，但真实数据库仍需环境验证。

配置事实：核心包 `langgraph` 当前为 `1.2.11`、要求 Python `>=3.10`，依赖 `langchain-core`、`langgraph-checkpoint`、`langgraph-sdk`、`langgraph-prebuilt`、`xxhash` 和 Pydantic；checkpoint 包当前为 `4.2.0`，依赖 `langchain-core` 与 `ormsgpack`。pytest 使用 strict markers/config；测试依赖另含 SQLite/Postgres、PyCryptodome、Redis、uvloop 等可选环境。根 `Makefile` 只是逐库转发 install/lint/format/lock/test，不是 API server 或完整生产运行时。

文档质量结论：根 README 的定位、能力入口和外部文档链接清晰，但对 `Send` 的 fan-out 预算、checkpoint durability、pending writes、同步取消限制、stream 非提交回执和 Store/checkpoint 分责没有实现级说明。`docs/` 当前仅有 `llms.txt`、`redirects.json`、redirect 生成器和 `.gitignore`，内容明确说明正式文档已迁移到 `docs.langchain.com`；因此本仓库没有本地完整的实现设计文档，核心细节实际分散在源码 docstring、测试和外部站点。`ARCHITECTURE.md` 现作为本地源码事实档案，明确区分“源码存在”“测试存在”“当前核对真实执行通过”和“外部服务未闭合”。

### 17.5 当前核对审计结论与限制

1. 未发现需要修改的源码、测试、配置或 docs 文件；遵守“禁止其他修改”，当前核对只更新根 `ARCHITECTURE.md`。
2. 没有安装依赖、启动服务、连接 SQLite/Postgres、调用远程 API、运行 pytest 或构建 CLI，因此测试文件存在不等于当前核对验证通过。
3. CodeGraph 不可用是目标仓库的索引状态，不是源码缺陷；调用关系以逐段源码和测试证据为准。

## 18. 本轮源码复核补录（2026-08-22）

### 18.1 Pregel loop 的可执行边界

本轮以目标仓库 `f09cfe8ffc1eeffd68f4b628ed69c30f7cad229f` 的当前源码为准，补核 `libs/langgraph/langgraph/pregel/main.py`、`pregel/_loop.py`、`pregel/_runner.py`、`types.py` 与 `errors.py`：

```text
Pregel.stream()/astream()
  → _defaults()：解析 stream modes、interrupt 前后点、checkpointer、store、cache、durability
  → SyncPregelLoop/AsyncPregelLoop（上下文管理器）
  → PregelRunner.tick()/atick()
      → submit runnable tasks（同一 superstep 并发）
      → 收集 task writes / GraphInterrupt / error
  → loop.after_tick()
      → apply_writes()：更新 channel versions/versions_seen
      → 按 durability 写入 checkpoint
  → 下一 tick，或 done / out_of_steps / draining / interrupt / error
```

`main.py:2655-3018` 明确说明：`stream()` 在 loop 退出后才调用 `run_manager.on_chain_end(loop.output)`；因此“收到流事件”不能等价于运行成功。`stream_mode` 可以是单值或序列；`messages`、`custom`、`subgraphs` 会安装回调/写入器，`subgraphs=True` 时事件带 namespace。`durability` 默认 `async`，`sync` 在下一步前等待 `_put_checkpoint_fut`，`exit` 只在退出边界持久化；无 checkpointer 时源码发出“durability has no effect”警告（`main.py:2802-2805`）。

`_loop.py:599-724` 将 `tick()` 与 `after_tick()` 分离：前者检查输入、interrupt_before/after、drain 和任务状态，后者应用 writes、更新版本并提交 checkpoint。`_runner.py:176-358,360-596` 显示同步/异步 runner 均按 task attempt 收集结果；`GraphInterrupt` 是控制流而不是普通失败，多个 task 的 interrupt 会汇总后再抛出。重试只清理该 attempt 的 writes 并重新执行 runnable，不能把外部副作用变成 exactly-once。

### 18.2 interrupt/resume 的实际恢复语义

`types.py:858-967` 的 `interrupt(value)` 首次调用通过当前 task scratchpad 的调用序号抛出 `GraphInterrupt`，恢复时按相同调用顺序消费 resume 值；多个中断可以用 interrupt id 映射。`errors.py:102-114` 将 `GraphInterrupt` 定义为 `GraphBubbleUp` 分支，故它不会被 runner 的普通异常重试路径当作业务失败。恢复从节点函数开头重新运行，节点在第一次 interrupt 之前的网络、文件、扣费或随机副作用必须由应用自行幂等化。

### 18.3 并发、取消与清理边界

`_runner.py` 的 async 路径通过 executor/semaphore 限制并发并等待任务收尾；loop 退出时释放 stream waiter。同步路径只能取消尚未开始的 Future，无法安全抢占已经运行的同步节点。`Runtime.control` 的 drain 在调度边界把 loop 置为 `draining`，不是强杀当前节点；`GraphDrained`、timeout、取消、interrupt 和普通异常应分别记录。`SyncPregelLoop`/`AsyncPregelLoop` 使用 `ExitStack`/`AsyncExitStack` 管理 executor、队列和回调，但这只覆盖正常进程内退出，不覆盖宿主崩溃后的租约、子进程、数据库事务或外部副作用清理。

### 18.4 测试证据清单与未执行边界

当前源码树存在下列直接相关测试文件（本轮未安装依赖、未执行 pytest）：

| 主题 | 主要文件 | 可确认范围 |
|---|---|---|
| Pregel/BSP、版本、并发 | `libs/langgraph/tests/test_pregel.py`, `test_pregel_async.py` | 同步/异步 loop、step、并发任务与错误路径 |
| interrupt/resume、迁移 | `test_interruption.py`, `test_interrupt_migration.py` | 中断值、resume、durability 与兼容迁移 |
| replay/fork | `test_time_travel.py`, `test_time_travel_async.py` | 历史 checkpoint、fork、分支隔离 |
| stream 投影 | `test_stream_*`, `test_pregel_stream_events_v3.py`, `test_stream_events_v3_e2e.py` | values/updates/messages/custom/checkpoints/tasks/debug、subgraph namespace、v3 事件 |
| retry/timeout | `test_retry.py` | 异常匹配、重试、backoff、timeout、CancelledError |
| checkpoint/store | `libs/checkpoint/tests/test_store.py`, `libs/checkpoint-sqlite/tests/test_sqlite.py`, `libs/checkpoint-postgres/tests/test_async.py` | 基础契约、SQLite/Postgres 同步异步实现（真实数据库依赖环境） |
| SDK 流 | `libs/sdk-py/tests/streaming/` | SSE/WebSocket、共享流、游标与 replay（假服务/测试传输） |

这些文件只能证明“测试源码覆盖了该路径”，不能证明本机当前通过。要把它们升级为成功证据，必须在目标仓库安装依赖后运行该仓库规定的测试命令，并单独启动所需 SQLite/Postgres/远程假服务；本平台文档不把未执行的测试写成通过。

### 18.5 唯一文档边界

平台侧本文件是该源码参考项目在 `系统工程平台/开发文档/源码参考研究/项目/.../langgraph/` 下的唯一持续维护架构文档。目标源码仓库根目录当前还有一个未跟踪的 `ARCHITECTURE.md`，它不在本工作包允许修改范围内，故未删除或改写；后续发布前应由维护者决定是否清理该源码树内的重复文档，避免把源码参考仓库的临时产物误当平台权威文档。
4. API server、远程 rollback、认证/权限、生产数据库事务隔离、密钥轮换、宿主崩溃恢复和外部副作用 exactly-once 仍属于仓库外或未闭合能力，不能由当前核对静态审计升级为已实现事实。
