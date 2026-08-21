# CrewAI 架构建档

> 后续深挖与收口档案。结论来自本地源码、配置、测试与现有 `细探-crewAI.md`，不是对远程仓库或运行时服务的推断；旧细探保留为历史材料，后续只维护本文件。
>
> - **项目**：`crewAI`（GitHub：`crewAIInc/crewAI`）
> - **源码版本**：`1.15.17`（`lib/crewai/src/crewai/__init__.py:51`；本地 workspace 成员源码/构建元数据均约束到该版本）
> - **审计基线**：Git `f4731f5025f861c78e3af0487cc80bf5e7c64782`（`feat(events): record whether a run had inputs, without recording the inputs`）；`origin/main` 当前与本地一致。工作树已有未跟踪 `ARCHITECTURE.md` 与 `.codegraph/`，本次未修改、未删除。
> - **许可证**：MIT（`LICENSE:1-19`）。
> - **本次范围**：在首轮基础上深挖 Agent/Task/Crew/Flow、LLM/Tool、状态/队列/并发、资源释放、失败/取消/崩溃边界和测试真假；仍只修改本文件，不改源码、依赖、配置、测试、README、Git，也不删除旧细探。

## 1. 一句话定位

CrewAI 是一个 Python 多智能体编排框架：用 `Agent + Task + Crew` 提供角色化、自主协作，用 `Flow + state + event/listener` 提供更可控的事件驱动流程；两者可以互相嵌套，Flow 方法也可以直接启动 Crew。

README 的产品分界是：**Crews 偏自主协作，Flows 偏精确控制**（`README.md:56-63`、`README.md:163-182`）。

## 2. 总体文本流程图

```text
用户项目 / CLI / JSONC-YAML / Python 装饰器
              │
              ├─ classic project: @CrewBase + agents.yaml + tasks.yaml
              ├─ JSON project: crew.json(c) + agents/*.json(c)
              └─ Flow project: Flow subclass + @start/@listen/@router
              │
              ▼
公共领域模型（Pydantic v2）
  Agent/BaseAgent ── role / goal / backstory / tools / memory / LLM
  Task            ── description / expected_output / agent / context / guardrails
  Crew            ── agents + tasks + Process + callbacks + config
  Flow            ── state + method definition + triggers + persistence
              │
              ├─────────────────────────────┐
              ▼                             ▼
Crew 执行路径                         Flow 执行路径
Crew.kickoff()                       Flow.kickoff()
  │                                     │
  ├─ prepare_kickoff(inputs/files)      ├─ 初始化 / 恢复 state
  ├─ before callbacks                   ├─ ExecutionStart / Input hooks
  ├─ sequential                       ├─ @start 方法（并行或扩展顺序）
  │    └─ Task.execute_sync/async       ├─ MethodExecution 事件
  └─ hierarchical                       ├─ router → listener 条件分发
       └─ manager Agent + delegation    ├─ @listen / @router / and_ / or_
                                         └─ @persist / human feedback
  │                                     │
  └──────────────┬──────────────────────┘
                 ▼
Agent 执行器（默认 experimental AgentExecutor；旧 CrewAgentExecutor 仍保留）
  │
  ├─ 组装 system/task/context/memory/knowledge/skills prompt
  ├─ 注入 delegation / platform / MCP / memory / file tools
  ├─ LLM call（原生 provider 或 LiteLLM fallback）
  ├─ native function calling 或 ReAct 文本解析
  ├─ ToolUsage → BaseTool.run/arun → 结构化结果/缓存/限次
  ├─ guardrail / structured output / human input / retry
  └─ AgentFinish / TaskOutput / CrewOutput 或 Flow method output
                 │
                 ▼
横切事件与状态
  event bus（同步线程池 + 异步专用 loop + 依赖序）
  OpenTelemetry tracing / token metrics / stream frames / hooks
  RuntimeState（实体快照 + EventRecord）
    ├─ JsonProvider：目录/JSON checkpoint
    └─ SqliteProvider：SQLite JSONB checkpoint
                 │
                 ▼
结果、日志、记忆、知识、文件输出、CrewAI+ tracing/deployment API
```

## 3. 真实仓库分层

### 3.1 Workspace/package 层

根 `pyproject.toml` 定义 uv workspace（`pyproject.toml:235-253`），包含六个成员：

| 包 | 根路径 | 真实职责 |
|---|---|---|
| `crewai` | `lib/crewai/` | 主框架：领域模型、Crew/Flow 执行、LLM、memory/knowledge/RAG、tools、events、state、project loader |
| `crewai-core` | `lib/crewai-core/` | 轻量共享底座：版本、路径、设置、认证、token、telemetry、打印和 `PlusAPI` |
| `crewai-cli` | `lib/cli/` | Click CLI、项目脚手架、运行/部署/认证/训练/回放/TUI；入口 `crewai_cli.cli:crewai` |
| `crewai-tools` | `lib/crewai-tools/` | 大量可选外部工具、RAG loader、企业/MCP/云适配器；依赖主 `crewai` |
| `crewai-files` | `lib/crewai-files/` | 多模态文件抽象、解析、约束、缓存、上传与 provider-specific content formatting |
| `crewai-devtools` | `lib/devtools/` | 内部版本、发布、文档冻结/检查、Git 自动化；非运行时核心 |

这是一个可编辑安装的 Python monorepo，而不是单一 `src/` 包。根依赖和开发配置位于 `pyproject.toml`；运行包自身的依赖和 console script 位于各成员 `pyproject.toml`。

### 3.2 主框架内部层

`lib/crewai/src/crewai/` 的真实顶层目录包括：

```text
crewai/
├── agent/              Agent 公共模型、规划配置与工具/知识准备
├── agents/             BaseAgent、AgentExecutor、旧 CrewAgentExecutor、步骤执行、工具处理、规划观察与 ReAct 解析
├── crew.py             Crew 聚合模型、kickoff、过程执行、输出、恢复
├── task.py             Task 模型、同步/线程异步/native async 执行、输出与 guardrail
├── process.py          Process.sequential / Process.hierarchical
├── flow/               Flow DSL、Definition、runtime、持久化、反馈、可视化
├── llm.py / llms/      LiteLLM 适配与原生 provider（OpenAI/Anthropic/Azure/...）
├── tools/              BaseTool、StructuredTool、ToolUsage、MCP/Agent/File/Memory tools
├── knowledge/ / rag/   知识源、存储、检索、embedding/client factory
├── memory/             Unified Memory、scope/slice、recall/encoding flows
├── events/             BaseEvent、event bus、event context、事件类型、tracing listener
├── state/              RuntimeState、EventRecord、checkpoint config/listener/provider
├── hooks/              LLM/tool/crew/flow interception points
├── project/            装饰器项目、YAML 配置映射、JSON/JSONC declarative loader
├── a2a/ / mcp/         Agent-to-Agent 与 Model Context Protocol 集成
├── security/           fingerprint 与 SecurityConfig
├── skills/             Skill model/loader/registry/cache/events
├── telemetry/          OpenTelemetry 相关采集
├── types/ / utilities/ 通用结果、streaming、metrics、序列化、prompt、限流等
└── experimental/       实验性 AgentExecutor、conversational 扩展、评价等
```

**分层裁决：** `crew.py`/`task.py`/`agent/core.py` 是公共领域模型与运行入口；`agents/` 是 Agent 执行器与工具循环；`flow/runtime/__init__.py` 是 Flow 执行引擎；`events/`、`hooks/`、`state/`、`telemetry/` 是横切基础设施；`project/` 与 `cli/` 是用户项目接入边界。

## 4. 核心数据模型与所有权

### 4.1 Agent / BaseAgent

- `BaseAgent` 位于 `lib/crewai/src/crewai/agents/agent_builder/base_agent.py:200-407`，是抽象 Pydantic 模型和第三方 Agent 扩展契约。
- 核心字段：`role`、`goal`、`backstory`、`llm`、`tools`、`max_iter`、`allow_delegation`、`memory`、`knowledge`、`mcps`、`apps`、`agent_executor`、`security_config`、`checkpoint`。
- `Agent` 位于 `lib/crewai/src/crewai/agent/core.py:171-396`，负责把 LLM 配置实例化、创建执行器、设置 skills/knowledge、准备 prompt 和记忆，并在 `execute_task()` 中进入执行器（`core.py:760-894`）。
- Agent 以 `entity_type="agent"` 参与 `RuntimeState` 联合实体；Agent 属于 Crew 时由 Crew 聚合序列化，不重复作为根实体（`events/event_bus.py:338-366`）。
- 默认执行器是 `crewai.experimental.AgentExecutor`；`CrewAgentExecutor` 仍可显式选择但构造时发出弃用警告（`agent/core.py:135-168`、`crew_agent_executor.py:143-151`）。

### 4.2 Task

`lib/crewai/src/crewai/task.py:114-300` 定义 Task Pydantic 模型：

- 必需语义：`description`、`expected_output`；可绑定 `agent`、`context`、`tools`。
- 执行控制：`async_execution`、`human_input`、`guardrail/guardrails`、`guardrail_max_retries`、`max_retries`（旧字段）、`response_model`、`output_json`、`output_pydantic`、`output_file`。
- `execute_sync()` 进入 `_execute_core()`；`execute_async()` 以 contextvars + daemon thread 返回 `Future`；`aexecute_sync()` 使用 native async（`task.py:572-635`）。
- Task 执行中会发 `TaskStartedEvent`、构建 `TaskOutput`、应用 guardrail/callback/file output，成功发 `TaskCompletedEvent`，失败发 `TaskFailedEvent`（`task.py:637-789`）。
- `TaskOutput` 是任务边界结果，包含 raw/pydantic/json、agent、messages 和 output format；Crew 再将任务结果聚合为 `CrewOutput`。

### 4.3 Crew / Process

`Crew` 位于 `lib/crewai/src/crewai/crew.py:159-405`：

- 聚合 `tasks`、`agents`、`process`；默认 `Process.sequential`（`process.py:4-11`）。
- Pydantic model validators 建立并校验运行前不变量：配置可生成 agents/tasks；顺序过程任务必须有 Agent；层级过程必须有 `manager_llm` 或 `manager_agent`；首任务不能是 ConditionalTask；不能只有条件任务；future task 不可作为 context；尾部 async 任务有约束（`crew.py:709-868`）。
- `memory=True` 创建 Unified Memory，并按 Crew 名称设置 `/crew/<name>` root scope；knowledge sources 可构造 `Knowledge`（`crew.py:640-707`）。
- 支持 cache、RPM、planning、checkpoint、stream、tracing、callbacks、skills、input files、输出日志等运行配置。

### 4.4 Flow / FlowDefinition / FlowState

Flow 的实现明确拆为三个关注点（`flow/flow.py:1-13`）：

1. `crewai.flow.dsl`：`@start`、`@listen`、`@router`、`and_`、`or_` 的 authoring DSL。
2. `crewai.flow.flow_definition`：可序列化的静态定义，描述 state、method、trigger、action、persistence、human feedback；Pydantic 模型默认为 `extra="forbid"`。
3. `crewai.flow.runtime`：执行引擎与状态。

`FlowState` 在 `flow/runtime/__init__.py:360-366`，保证 state 有 UUID；`Flow` 是 `BaseModel + Generic[T]`，可接受 dict 或 Pydantic state，`FlowMeta` 在类创建时收集方法/字段（`runtime/__init__.py:375-428`）。

Runtime 私有状态包含：注册方法、pending events、条件 listener fired 集合、方法输出/调用计数、completed methods、checkpoint state、event futures、persistence backends、usage aggregation（`runtime/__init__.py:701-731`）。

### 4.5 RuntimeState / checkpoint

`RuntimeState` 是 `RootModel`，根部是 `Entity = Flow | Crew | Agent` 联合列表，由 `crewai/__init__.py` 在导入阶段完成 Pydantic `model_rebuild()`（`state/runtime.py:1-8`、`runtime.py:177-214`）。快照包括：

- `crewai_version`、`parent_id`、`branch`；
- 所有实体 JSON；
- `EventRecord` 事件记录；
- 版本迁移逻辑（至少处理旧 discriminator 和 source type）。

Provider 契约位于 `state/provider/core.py:10-111`，要求 checkpoint、async checkpoint、prune、extract_id、restore sync/async。当前真实 provider：

- `JsonProvider`：`location/branch/*.json`，文件名携带时间、短 UUID、parent ID；校验 branch 防目录穿越（`state/provider/json_provider.py:22-167`）。
- `SqliteProvider`：SQLite `checkpoints` 表，JSONB data、parent/branch lineage，location 形如 `db_path#checkpoint_id`（`state/provider/sqlite_provider.py:16-165`）。
- `detect_provider()` 由路径/SQLite magic bytes 选择 provider（`state/provider/utils.py:11-...`）。

`Crew.from_checkpoint()`、`Agent.from_checkpoint()`、`Flow.from_checkpoint()` 读取 RuntimeState，恢复 runtime objects 和 event scope；`fork()` 改变 branch 并保留父 checkpoint lineage（`crew.py:416-464`、`agent/core.py:409-451`、`runtime/__init__.py:584-666`）。Flow 还有独立 `@persist` state backend；它与 checkpoint 是两套状态系统，不能同时通过同一个 kickoff 参数使用（`runtime/__init__.py:1947-1981`）。

## 5. 关键数据流

### 5.1 Classic Python/YAML Crew

```text
用户定义 CrewBase 类
  ├─ @agent 方法 → AgentMethod（memoized）
  ├─ @task 方法  → TaskMethod（memoized）
  ├─ @crew 方法  → 主 Crew 方法
  └─ @before_kickoff/@after_kickoff/@tool/@llm/@callback
        │
        ▼
CrewBaseMeta 创建类（project/crew_base.py）
  ├─ 记录 base_directory 和 agents.yaml/tasks.yaml 路径
  ├─ 初始化实例时 load_configurations()
  ├─ map_all_agent_variables()/map_all_task_variables()
  └─ 构造 CrewMetadata
        │
        ▼
@crew wrapper（project/annotations.py:188-278）
  ├─ 调各 task/agent 方法生成 Task/Agent 对象
  ├─ 绑定 callbacks
  └─ 返回 Crew
        │
        ▼
Crew.kickoff(inputs, input_files)
  → prepare_kickoff
  → process 分支
  → Task 执行/输出聚合
```

### 5.2 JSON/JSONC Crew

```text
crew.jsonc / crew.json + agents/<name>.json(c)
        │
        ▼
parse_jsonc（保留字符串中的 URL/comment marker）
        │
        ▼
load_json_crew_project()
  ├─ 结构校验与 runtime-only 字段拒绝
  ├─ 解析 Agent/Task 类型、Python refs、tools、model refs
  ├─ validation 模式不执行自定义工具代码
  └─ 生成 JSONCrewProject
        │
        ▼
_load_crew_project()
  ├─ build_agent()
  ├─ build Task / context / output model
  └─ Crew(**crew_kwargs)
        │
        ▼
load_crew_and_kickoff() 或 CLI run
```

证据路径：`project/json_loader.py:188-209`、`project/json_loader.py:277-326`、`project/crew_loader.py:25-37`、`project/crew_loader.py:92-180`。

### 5.3 Crew Task → Agent → LLM/Tool

```text
Crew._execute_tasks()
  → prepare_task_execution()
  → task.execute_sync / execute_async / aexecute_sync
  → Agent.execute_task / aexecute_task
  → _prepare_task_execution
       date + task.prompt + schema + context + memory
  → knowledge retrieval + prepare_tools + training data
  → AgentExecutor.invoke()
       ├─ prompt/messages
       ├─ native function calling（若 LLM 支持）
       └─ ReAct 文本 Action/Action Input parser
  → BaseTool / CrewStructuredTool
       args_schema validation → run/arun → cache / usage limit / hooks
  → AgentFinish
  → TaskOutput
  → guardrail / callback / file output
  → CrewOutput(raw, pydantic, json_dict, tasks_output, token_usage)
```

Agent executor 的 native/ReAct 分流和循环见 `agents/crew_agent_executor.py:208-328`、`330-468`、`484-632`；规划观察由 `agents/planner_observer.py:39-85` 提供，单步执行边界由 `agents/step_executor.py:63-138` 提供（每次以独立消息/`StepResult` 返回，工具执行与事件一并处理），`agents/tools_handler.py:15-52` 记录最近工具调用并按条件写入 `CacheHandler`；ReAct 文本由 `agents/parser.py:25-99` 解析为 `AgentAction`/`AgentFinish`。`agents/agent_builder/` 提供 `BaseAgent` 与 `BaseAgentExecutor` 扩展契约。BaseTool 的注册、schema 推导、参数校验、usage limit、sync/async 入口见 `tools/base_tool.py:48-77`、`102-257`、`294-353`。

### 5.4 LLM 数据流

`BaseLLM` 定义统一抽象：`model`、provider、temperature、stop、stream、additional params，以及 `call/acall` 合约（`llms/base_llm.py:150-190`、`311-418`）。

当前 `LLM`（`llm.py:368`）是 LiteLLM fallback 路径；另有 `llms/providers/` 中的原生 OpenAI、Anthropic、Azure、Bedrock、Gemini、Snowflake、OpenAI-compatible provider。一次高层调用：

1. 建立唯一 call id，发 `LLMCallStartedEvent`；
2. 规范化 string/messages、校验 response format、执行 before LLM hooks；
3. 组装 completion params；
4. 选择 streaming 或 non-streaming；
5. 处理 tool calls、finish reason、usage；
6. 发 `LLMCallCompletedEvent` 或 `LLMCallFailedEvent`；
7. 对部分 provider 不支持的 `stop` 做重试降级。

证据路径：`llm.py:1820-1957`、`llm.py:1959-2089`、`llm.py:2402-2469`。

### 5.5 Flow 数据流

```text
Flow subclass
  → FlowMeta / build_flow_definition（懒构建）
  → Flow instance _flow_post_init
       definition + initial state + memory + method registry
  → kickoff_async
       ExecutionStart hook → Input hook → baggage inputs
       → 清理/恢复 completed methods、state id、persistence state
       → FlowStartedEvent
       → @start 方法（默认并行）
           → MethodExecutionStartedEvent
           → PRE_STEP hook
           → sync method 放线程池 / async method await
           → human feedback（可暂停）
           → POST_STEP hook
           → state output + persist completion
           → MethodExecutionFinishedEvent
           → router 先串行处理
           → listener 条件匹配后并行处理
           → 递归继续路由/监听，max_method_calls 防无限循环
       → OUTPUT / EXECUTION_END hooks
       → flush memory/event futures
       → FlowFinishedEvent + trace finalize
       → 最后方法输出
```

关键实现位于 `flow/runtime/__init__.py:2012-2469`、`2556-2607`、`2646-2781`、`2882-3050`；`@start/@listen/@router/and_/or_` 定义位于 `flow/dsl/`。

### 5.6 事件、观测与横切控制

- `crewai_event_bus` 是单例；首次 emit 才创建 sync `ThreadPoolExecutor(max_workers=10)` 与独立 async event loop 线程（`events/event_bus.py:95-191`）。
- Handler 可同步或异步，支持 `Depends` 依赖图；事件类型变化会使执行计划缓存失效（`events/event_bus.py:217-280`、`458-500`）。
- 事件 context 维护 parent/triggering event、scope pairing、emission sequence；Flow/Crew/Task/LLM/Tool/Memory/Checkpoint 均通过事件连接。
- tracing 使用 OpenTelemetry 与 `TraceCollectionListener`；Crew/Flow 在 kickoff 时建立 baggage/context，聚合 usage metrics。
- hooks 通过 `InterceptionPoint` 对 `EXECUTION_START`、`INPUT`、`PRE_STEP`、`POST_STEP`、`OUTPUT`、`EXECUTION_END` 等位置做前后拦截，可编辑 payload 或阻止调用。

## 6. 关键代码路径表

| 关注点 | 入口/关键实现 | 说明 |
|---|---|---|
| 公共 import API | `lib/crewai/src/crewai/__init__.py:8-20,187-205` | re-export Agent/Crew/Flow/Task/LLM/Process/outputs；Memory 懒加载；为联合 Pydantic 模型做 rebuild |
| Crew 聚合模型 | `lib/crewai/src/crewai/crew.py:159-405` | 字段、validators、memory/knowledge、checkpoint、callbacks、stream |
| Crew kickoff | `lib/crewai/src/crewai/crew.py:980-1071` | restore、stream、runtime scope、输入准备、process 分发、收尾/失败 |
| Crew task loop | `lib/crewai/src/crewai/crew.py:1540-1609` | conditional、sync/async batching、context、TaskOutput 聚合 |
| Hierarchical manager | `lib/crewai/src/crewai/crew.py:1495-1530` | 生成 manager Agent，注入 delegation tools |
| Agent 模型 | `lib/crewai/src/crewai/agent/core.py:171-396` | LLM/executor/knowledge/skills/MCP/A2A/memory 字段与 post-init |
| BaseAgent contract | `lib/crewai/src/crewai/agents/agent_builder/base_agent.py:200-797` | 第三方 Agent 扩展抽象与基础字段/方法 |
| 默认/旧执行器 | `lib/crewai/src/crewai/agents/crew_agent_executor.py:98-247` | invoke、prompt 初始化、工具循环；旧类仍兼容 |
| Task 模型与执行 | `lib/crewai/src/crewai/task.py:114-300,572-789` | 输出结构、guardrail、sync/thread/native async、事件 |
| Flow public surface | `lib/crewai/src/crewai/flow/flow.py:1-47` | DSL、Definition、runtime、conversational mixin 的兼容 re-export |
| Flow runtime | `lib/crewai/src/crewai/flow/runtime/__init__.py:428-900,1947-3050` | metaclass、state、kickoff、method/listener engine、persistence |
| Flow declarative contract | `lib/crewai/src/crewai/flow/flow_definition.py:81-...` | state/action/config/persistence/human feedback 等可序列化模型 |
| Project decorators | `lib/crewai/src/crewai/project/annotations.py:42-278` | CrewBase 项目构建和回调绑定 |
| JSON/JSONC loading | `lib/crewai/src/crewai/project/json_loader.py:188-326` | parse、校验、runtime field 防护、custom Python ref |
| Crew loader | `lib/crewai/src/crewai/project/crew_loader.py:25-180` | JSONCrewProject → Agent/Task/Crew |
| RuntimeState | `lib/crewai/src/crewai/state/runtime.py:177-508` | entity snapshot、migration、checkpoint/restore/fork |
| Checkpoint providers | `lib/crewai/src/crewai/state/provider/{core,json_provider,sqlite_provider}.py` | provider contract、JSON 文件、SQLite |
| Event bus | `lib/crewai/src/crewai/events/event_bus.py:95-500` | handler registry、线程/异步调度、runtime state、依赖计划 |
| LLM abstraction | `lib/crewai/src/crewai/llms/base_llm.py:150-418` | BaseLLM contract、stream/acall |
| LiteLLM LLM | `lib/crewai/src/crewai/llm.py:368-...` | provider fallback、call/tool/stream/usage |
| Tool contract | `lib/crewai/src/crewai/tools/base_tool.py:102-407` | schema、registry、run/arun、cache/usage |
| Shared SDK | `lib/crewai-core/src/crewai_core/plus_api.py:140-496` | authenticated HTTP client for CrewAI+ |
| CLI root | `lib/cli/src/crewai_cli/cli.py:101-...` | Click group 与 command registration |
| CLI run | `lib/cli/src/crewai_cli/run_crew.py:252-372` | JSON Crew load/input/TUI/plain run；classic path 后续在同文件 |
| CLI flow | `lib/cli/src/crewai_cli/kickoff_flow.py:87-110` | conversational Flow TUI 或 `uv run kickoff` |

## 7. Public API / CLI / SDK 面

### 7.1 Python SDK/API

主包 `crewai` 的稳定高层使用面由 `__init__.py` 暴露：

```python
from crewai import (
    Agent, Crew, Flow, LLM, Process, Task,
    BaseLLM, BaseAgent, BaseAgentExecutor,
    CrewOutput, TaskOutput, Knowledge,
)
```

典型调用面：

```python
crew.kickoff(inputs={...})
await crew.kickoff_async(inputs={...})       # sync kickoff 放线程
await crew.akickoff(inputs={...})             # native async 任务链
crew.kickoff_for_each([...])
Crew.from_checkpoint(config).kickoff()
Crew.fork(config, branch="...").kickoff()

flow.kickoff(inputs={...})
await flow.kickoff_async(inputs={...})
flow.flow_definition()
Flow.from_declaration(path=...)
Flow.from_checkpoint(config)

llm.call(messages, tools=..., response_model=...)
await llm.acall(messages, tools=...)
tool.run(...) / await tool.arun(...)
```

这是**库内 Python API**，不是 HTTP server API。源码中未见 FastAPI/Flask/Starlette 路由注册；外部控制平面访问通过 `PlusAPI` 客户端，不代表本仓库提供服务端。

### 7.2 CLI

console script 在 `lib/crewai/pyproject.toml:147-155` 与 `lib/cli/pyproject.toml:34-45` 都指向 `crewai_cli.cli:crewai`。真实命令分组包括：

- `crewai create crew <name>`：默认 JSON/JSONC crew；`--classic` 选择 Python/YAML 结构。
- `crewai create flow <name>`：Python Flow；`--declarative` 选择 declarative Flow。
- `crewai run`：运行项目 Crew（JSON/TUI/plain/classic 分支由项目配置和环境决定）。
- `crewai kickoff`：Flow 项目入口，conversational Flow 可进入 TUI，否则转 `uv run kickoff`。
- `crewai install` / `crewai uv ...` / `crewai update`：依赖与项目准备。
- `crewai train`、`crewai test`、`crewai replay`：训练、评价、按 task 回放。
- `crewai reset-memories`、`crewai memory`、`crewai log-tasks-outputs`：记忆/TUI/任务输出管理。
- `crewai deploy`、`crewai login`、组织/enterprise/trigger/skill/tool 相关命令：CrewAI+ 控制平面能力。
- `crewai version`：显示 `crewai`/`crewai-tools` 版本。

`cli.py:101-210` 展示顶层 Click/create 路由；`cli.py:233-494` 展示 train/replay/memory/test/install 等命令；其余部署/认证命令按需延迟导入。

### 7.3 CrewAI+ SDK / 外部 HTTP API 客户端

`crewai_core.plus_api.PlusAPI` 是共享的 `httpx` 客户端，不是服务端实现：

- 认证：Bearer API key、`X-Crewai-Version`、可选 `X-Crewai-Organization-Id`。
- Base URL 优先级：构造参数 → `CREWAI_PLUS_URL` → `Settings.enterprise_base_url` → 默认 enterprise URL（`plus_api.py:152-199`）。
- 资源：tools、skills、organizations、crews、agents、tracing、ephemeral tracing、integrations（`plus_api.py:143-150`）。
- Crew：list/create/delete/status/logs/deploy，支持 local ZIP multipart create/update（`plus_api.py:309-389`）。
- Tracing：batch init、events、finalize、failed（`plus_api.py:394-477`）。
- Integrations：MCP config、triggers、trigger payload（`plus_api.py:479-496`）。
- `crewai.plus_api.PlusAPI` 只是 re-export；CLI 包还有兼容性子类 `lib/cli/src/crewai_cli/plus_api.py:16-95`。

## 8. 技术栈与依赖边界

### 8.1 语言、构建与质量工具

| 分类 | 实际证据 |
|---|---|
| 语言 | Python；`requires-python >=3.10,<3.14`（根 `pyproject.toml:1-7`，`.python-version` 为 `3.13`） |
| 数据建模 | Pydantic `>=2.11.9,<2.13`，大量 `BaseModel`、validator、serializer、discriminator |
| 包管理 | uv workspace；锁文件 `uv.lock` 为 v1/revision 3，六个成员，约 476 个 `[[package]]` 记录 |
| 构建 | Hatchling（各包 `pyproject.toml` 的 `build-system`） |
| CLI | Click；TUI 使用 Textual |
| HTTP | httpx；`PlusAPI` 使用 `trust_env=False` 的短生命周期 Client |
| 异步/并发 | asyncio、contextvars、ThreadPoolExecutor、Future、aiofiles、aiosqlite |
| 观测 | OpenTelemetry API/SDK/OTLP HTTP；事件 bus、trace listener、usage metrics |
| 配置 | TOML、YAML、JSON、JSONC；`tomli/tomli-w`、PyYAML、json5/json-repair/jsonref |
| 测试 | pytest、pytest-asyncio、VCR.py/pytest-recording、pytest-subprocess、xdist、split、timeout、randomly |
| 静态/安全 | Ruff、mypy strict、Bandit、pip-audit、pre-commit、CodeQL |
| 许可证 | MIT |

### 8.2 主包关键运行依赖

来自 `lib/crewai/pyproject.toml:9-48`：

- `crewai-core`、`crewai-cli`；
- `pydantic`、`openai`、`instructor`；
- `opentelemetry-*`；
- `chromadb`、`lancedb`、`tokenizers`、`aiosqlite`、`aiofiles`；
- `mcp`、`httpx`、`click`、`pydantic-settings`、`pyyaml`、`json-repair`、`portalocker`、`cel-python` 等。

可选边界包括 `tools`、`embeddings/tiktoken`、`mem0`、`docling`、`qdrant`、AWS/Bedrock、Google GenAI、Azure、Anthropic、A2A、LiteLLM、file-processing 等（`crewai/pyproject.toml:56-118`）。这说明“核心框架”与“外部生态工具/ provider”是通过 extras 分层，而不是所有集成都必然在最小安装中可用。

### 8.3 支撑包边界

- `crewai-files` 把 `FileInput`、文件源、解析/约束、upload cache、provider-specific multimodal formatting 汇聚到公共导出面（`crewai_files/__init__.py:1-155`）。
- `crewai-tools` 将大量搜索、RAG、数据库、浏览器、sandbox、AWS、企业平台、MCP 工具集中导出；其 `pyproject.toml` 通过几十个 optional extra 控制外部依赖。
- `crewai-core` 只承载跨 `crewai`/`crewai-cli` 的轻量公共能力，避免 CLI 与主包复制设置、版本、认证/HTTP 客户端。

## 9. 测试与工程门禁

### 9.1 测试布局（静态统计）

根 `pyproject.toml:138-154` 的 pytest 配置：

- `testpaths` 覆盖 `lib/crewai/tests`、`lib/crewai-tools/tests`、`lib/crewai-files/tests`、`lib/cli/tests`、`lib/crewai-core/tests`；
- `asyncio_mode = strict`；
- 默认 `-n auto --timeout=60 --dist=loadfile --max-worker-restart=2 --block-network --import-mode=importlib`；
- 测试文件/类/函数遵循 `test_*.py`、`Test*`、`test_*`。

本地文件数统计：

| 包 | 测试文件数 |
|---|---:|
| `crewai` | 213 |
| `crewai-tools` | 27 |
| `crewai-files` | 8 |
| `crewai-cli` | 39 |
| `crewai-devtools` | 2 |
| `crewai-core` | 1 |

### 9.2 已实际阅读的测试主题

- `crewai/tests/test_crew.py`：Crew 配置校验、conditional/context 约束、sequential/hierarchical、manager delegation、memory、events、输出。
- `crewai/tests/test_flow.py`：多 start、listener、router、and/or 条件、循环、并发 listener、异步、异常、Definition 驱动运行。
- `crewai/tests/test_checkpoint.py`：checkpoint config、JSON/SQLite provider、branch/parent lineage、prune、restore、fork、initial state round-trip。
- `crewai/tests/test_llm.py`：string/message call、callbacks、tool function call、response format、provider detection、context window、native provider 与 LiteLLM 路径。
- `crewai/tests/tools/test_tool_usage.py`：工具 schema、typed output、cache callback、hook、输入修复/校验。
- `crewai/tests/project/test_json_loader.py`：JSONC、Agent/LLM/settings/tool/MCP 定义、runtime 字段拒绝、validation 不执行自定义工具。
- `crewai/tests/test_imports.py`：公共 `TaskOutput`/`CrewOutput` 导出。
- `crewai/tests/cli/test_plus_api.py`：认证 header、base URL/org 隔离、tool/crew/deploy/trace/multipart endpoint payload。
- `crewai/tests/cli/test_cli.py`：reset memory 的 Click 行为、兼容 flags、Crew/Flow/JSON Crew 分支。

### 9.3 Root conftest 的测试隔离行为

`conftest.py` 实际做了较重的测试环境治理：

- 读取 `.env.test`（文件本身未读取其 secret 内容）；
- 对 VCR aiohttp/httpx stub 做版本兼容补丁；
- 过滤请求敏感 header、规范化 Azure/Bedrock host、禁止错误响应和空 body cassette；
- 每个测试清理事件 handler、重置 event state；
- 为每个测试创建临时 CrewAI storage 并设置 `CREWAI_STORAGE_DIR`、`CREWAI_TESTING`；
- pytest 配置默认 `--block-network`，有 VCR 的 provider 测试用录制 cassette。

### 9.4 CI/门禁

- `.github/workflows/tests.yml`：Python 3.10/3.11/3.12/3.13，CrewAI 和 tools 各拆 8 组，`pytest-split`、`--maxfail=3`。
- `.github/workflows/linter.yml`：`ruff check lib/`、`ruff format --check lib/`。
- `.github/workflows/type-checker.yml`：四个 Python 版本运行 `uv run mypy lib/`。
- 根 `pyproject.toml:120-131` 开启 mypy strict；Ruff 规则覆盖错误、bugbear、安全、命名、异步、性能、导入和返回值等。
- `.pre-commit-config.yaml` 还声明 Ruff、mypy、uv-lock、pip-audit、Commitizen；文档快照由 devtools/CI 另行管控。

**本次没有运行测试、构建、安装依赖或启动服务**：任务是源码参考库的静态建档，且明确禁止安装依赖、构建和启动服务。

## 10. 设计上的关键边界与工程特征

1. **双编排面**：Crew 把自主 Agent 协作封装成角色/任务模型；Flow 把业务控制流、条件、状态、持久化和人机反馈显式化。
2. **Pydantic 作为跨边界契约**：Agent/Task/Crew/Flow/Definition/Tool/LLM/Checkpoint 都通过模型校验、序列化和 discriminator 组织运行时数据。
3. **运行时与声明式定义分离**：FlowDefinition 和 JSON loader 支持把可执行对象投影为定义/配置，但实际执行仍需解析 import ref 或 Python 类。
4. **事件总线是连接骨架**：执行、LLM、工具、状态、checkpoint、tracing、memory 的可观测关系由 event bus 和 event context 维护，而不是由单个服务对象直接调用所有横切组件。
5. **checkpoint 是实体快照 + 事件记录**：恢复不仅重建字段，还重建 executor、memory view、event scope、completed methods/outputs 和 lineage。
6. **同步/异步是多路径而非一个 wrapper**：Crew 有 `kickoff_async`（线程包 sync）和 `akickoff`（native async）；Task 有 sync、thread Future、native async；Flow sync kickoff 也以 async engine 为核心。
7. **工具是结构化能力边界**：BaseTool 自动推导 args/result schema，运行时做输入校验、cache、usage limit、hooks 和 typed output 格式化。
8. **集成以适配器/可选依赖隔离**：MCP、A2A、各 LLM provider、外部检索/数据库/浏览器/sandbox 主要通过 extras、provider、adapter 和 `crewai-tools` 接入。
9. **安全/隐私边界已显式出现**：Agent/Task/Crew 有 SecurityConfig/fingerprint；JSON validation 防 runtime-only 字段；路径/branch 做 traversal 检查；README 声明 telemetry 可禁用或 opt-in 细粒度共享。
10. **核心仓库不是控制平面服务端**：CrewAI+ 是外部 HTTP client/deployment/tracing 集成；本地仓库本身未发现 HTTP server 路由。

## 11. 未确认项与边界声明

以下内容当前核对没有凭空补齐，后续若需要应单独深挖：

- 未运行 `uv sync`、pytest、mypy、ruff、构建或 CLI；因此未声明当前环境“可运行/全绿”。
- 未读取 `.env.test` 的实际内容，避免暴露 secret；只根据 `conftest.py` 确认其被加载。
- `uv.lock` 记录了约 476 个包和多平台/多 Python resolution，但未逐一核对所有 optional extra 的最终解析图；此处只记录 workspace、锁格式和关键包。
- `crewai.experimental.AgentExecutor` 的完整实现、A2A server/client、MCP transport、Memory/LanceDB/Chroma 内部 schema、RAG factory 的 provider 细节未全部展开；本文只建档其边界和入口。
- Flow persistence 的各具体 backend、SQLite checkpoint 与 Flow `@persist` backend 的差异已确认存在，但默认 backend 的完整存储实现未在当前核对逐文件展开。
- README 中的开发者数量、性能、企业控制平面能力属于项目自述/产品说明，不是本地源码可验证指标。
- CLI 的完整命令表随 `cli.py` 后续分段和子模块变化；本文列的是从注册点与模块树实际确认的主要入口，不替代 Click `--help` 的运行时输出。
- 本仓库的 `docs/v*` 是冻结文档快照；根据 `AGENTS.md` 不应直接修改。本次没有修改任何 docs、源码、配置、依赖或测试。

## 12. 旧细探吸收与裁决（唯一维护入口）

本节是对 `细探-crewAI.md` 的逐项收口记录。旧细探保留作为历史研究材料；后续 crewAI 架构事实只维护本 `ARCHITECTURE.md`。以下裁决均以当前源码、配置、测试或 `LICENSE` 为证据，不把旧文案本身当作实现证明。

| 旧细探内容 | 裁决 | 当前文档/证据 |
|---|---|---|
| CrewAI 是 `Agent + Task + Crew` 的多智能体协作框架，另有 Flow | **吸收**，并补充 Crew 偏自主协作、Flow 偏精确控制的产品边界 | 第 1、2 节；`README.md:56-63,163-182`；`crew.py:159-239`；`flow/` |
| `Process.sequential` / `Process.hierarchical` | **吸收** | 第 2、4.3、6 节；`process.py:4-11`；`crew.py:239` |
| Crew 的 kickoff、callbacks、checkpoint 事件 id、`from_checkpoint`、`fork`、Agent 惰性解析 | **吸收并校正**：checkpoint/fork 是当前类方法；回调列表会过滤 `None`，不能泛化为所有不可解析回调均静默丢弃；恢复是 RuntimeState 恢复与运行时重建，不简化成“只恢复最后完成任务” | 第 4.3、4.5、6 节；`crew.py:153-156,407-464`；`crew.py:466-500` |
| `agents/crew_agent_executor`、`step_executor`、`tools_handler`、`planner_observer`、`agent_builder`、`parser` | **吸收**，由原先的概括补成真实模块边界：执行器分流、单步执行、规划观察、工具缓存记录、ReAct 输出解析和 Agent 扩展契约 | 第 3.2、5.3、6 节；`agents/crew_agent_executor.py`；`agents/step_executor.py:63-180`；`agents/tools_handler.py:15-52`；`agents/planner_observer.py:39-85`；`agents/parser.py:25-99`；`agents/agent_builder/base_agent.py:200` |
| memory、knowledge/RAG、security、A2A、MCP、hooks、events、skills、state、telemetry | **吸收**为横切能力与适配边界；未将它们误写成单一执行器内部组件 | 第 3.2、4.5、5.6、8.2、10 节 |
| Agent 的 `role/goal/backstory` 加 Task 提示词 | **吸收**为模型与提示词边界 | 第 4.1、4.2、10 节；`agent/core.py:174-181,1425-1427`；`task.py:114-147,572-635` |
| “Flow 中有流程编排提示词” | **部分吸收/限定**：源码确有 Flow conversational/human-feedback/skill 等 prompt 字段，但不能据此宣称所有 Flow 都以提示词编排 | 第 4.4、5.5、11 节；`flow/conversational_definition.py:18-35`；`flow/flow_definition.py` |
| “可序列化回调、坏回调不阻断”作为平台借鉴点 | **限定吸收**：保留 SerializableCallable 与 JSON ref 边界作为可借鉴模式；不把“坏回调一定不阻断”列为普遍保证，因源码证据只确认列表 `None` 过滤及 ref 校验路径 | 第 4.3、7 节；`crew.py:407-414`；`types/callback.py:1-153`；`project/json_loader.py:1861` |
| `from_checkpoint/fork`、双 Process、Crew 组合模型、A2A/MCP 作为底座借鉴点 | **吸收为研究结论，不是本仓库实现承诺**；平台是否采用须另行做边界、权限、持久化和恢复语义设计 | 第 10 节；本项目 ARCHITECTURE 仅记录 crewAI 事实 |
| `lib/crewai-core`、`crewai-tools`、`flow`、`memory`、`knowledge`、`docs`、`tests` 旁路线索 | **吸收**并纳入 workspace、目录、测试和参考索引 | 第 3、9、12、13 节 |
| 许可证“通常 MIT、需确认” | **不吸收旧的不确定表述，已用当前证据裁决为 MIT** | 文档头部；`LICENSE:1-19` |

**未吸收项汇总：** 仅保留上述两类限定结论——“`from_checkpoint` 等于只从最后完成任务续跑”以及“不可解析回调必然静默丢弃”均未按旧文案字面写入；“Flow 统一由提示词编排”也未作为普遍事实写入。旧细探中的其余有证据架构事实已吸收到正文或本节裁决中。没有因本次收口而修改源码、配置、测试或删除 `细探-crewAI.md`。

## 13. 参考文件索引

本档案的事实来源主要是：

- `README.md`
- `AGENTS.md`（未发现项目根 `CLAUDE.md`）
- `pyproject.toml`、六个 workspace 子包 `pyproject.toml`、`uv.lock`
- `lib/crewai/src/crewai/{__init__.py,crew.py,task.py,process.py,llm.py}`
- `lib/crewai/src/crewai/agent/core.py`
- `lib/crewai/src/crewai/agents/agent_builder/base_agent.py`
- `lib/crewai/src/crewai/agents/crew_agent_executor.py`
- `lib/crewai/src/crewai/agents/{step_executor.py,tools_handler.py,planner_observer.py,parser.py}`
- `lib/crewai/src/crewai/agents/agent_builder/{base_agent.py,base_agent_executor.py}`
- `lib/crewai/src/crewai/flow/{flow.py,flow_definition.py,flow_wrappers.py,runtime/__init__.py}`
- `lib/crewai/src/crewai/project/{annotations.py,crew_base.py,crew_loader.py,json_loader.py,wrappers.py}`
- `lib/crewai/src/crewai/state/{runtime.py,provider/core.py,provider/json_provider.py,provider/sqlite_provider.py}`
- `lib/crewai/src/crewai/events/event_bus.py`
- `lib/crewai/src/crewai/llms/{base_llm.py}`、`lib/crewai/src/crewai/tools/base_tool.py`
- `lib/crewai-core/src/crewai_core/plus_api.py`
- `lib/cli/src/crewai_cli/{cli.py,run_crew.py,kickoff_flow.py,plus_api.py}`
- 关键 `tests/` 与 `.github/workflows/` 文件
- 已有细探文件 `细探-crewAI.md`（本次保留原样）

## 14. 后续底座映射：通用模块与上层编排裁决

> 本节是后续映射，不是对 crewAI 生产化改造的承诺。**吸收**表示可作为公共契约/模块的输入；**隔离**表示能力有价值但必须停留在适配层或项目编排层；**待核**表示源码边界已定位但仍缺运行时/外部服务证据。任何平台落地都必须另行经过能力登记、契约确认、资源租约和真实验收。

### 14.1 映射总原则与唯一入口

crewAI 存在两个不同的公开执行入口：

```text
Python/配置/CLI 项目
      │
      ├─ Crew.kickoff / kickoff_async / akickoff
      │      → Crew 聚合校验 → Process 分支 → Task → Agent → LLM/Tool
      │
      └─ Flow.kickoff / kickoff_async
             → Flow state/恢复 → @start → @listen/@router/and_/or_
             → Flow method（可在其中调用 Crew/Agent）
      │
      └─ 横切统一经过 event bus、RuntimeState、checkpoint provider、hooks、tracing
```

后续的**唯一入口裁决**：

1. **上层业务/项目只能选择 `Crew.kickoff*` 或 `Flow.kickoff*` 作为一次运行的根入口**；不把 `Task.execute_*`、`Agent.execute_task`、`AgentExecutor.invoke` 当作平台级工作流入口。它们是被上层入口调用的内部执行节点，直接调用会绕开 Crew/Flow 的上下文、事件、恢复和清理。
2. **Crew 与 Flow 不能被压成同一个编排器**：Crew 负责团队/任务协作，Flow 负责显式控制流、状态和人机反馈；Flow 方法可以嵌入 Crew，但必须由 Flow 作为该次流程的根 owner，反之亦然。
3. **通用能力使用唯一模块入口**：工具只经 `BaseTool.run/arun`（或其结构化包装）执行；事件只经 `crewai_event_bus.on/off/emit`；快照只经 `RuntimeState` + `BaseProvider` 契约；MCP 只经 `MCPToolResolver.resolve/cleanup` 或 `MCPToolWrapper.run/arun`；A2A 只经 Agent 的 A2A wrapper/配置；遥测只经 `Telemetry`/`TraceCollectionListener`。不允许项目直接创建第二套缓存、事件总线、checkpoint 文件协议或外部协议客户端。
4. `crewai.__init__` 的 re-export 是**导入门面**，不是运行时调度器；`crewai_cli`、JSON/YAML loader、CrewBase decorator 都是接入适配层，最终必须汇入上述两个执行根入口。

### 14.2 能力分类表

|对象/能力|源码中的通用模块流程|属于上层编排的部分|后续裁决|
|---|---|---|---|
|`Agent` / `BaseAgent`|角色/目标/背景、LLM、工具、memory/knowledge、executor、输入输出契约；以 `entity_type="agent"` 进入 `RuntimeState`|具体角色 prompt、是否允许 delegation、给哪个 Task、A2A/MCP 配置、选择哪个 executor|**吸收公共 Agent 执行契约；隔离角色与项目策略**。不能把一个具体角色当平台公共组件|
|`Task`|任务描述/期望输出、Agent 绑定、context、结构化输出、guardrail、重试、文件输出、TaskStarted/Completed/Failed 事件|任务之间的业务依赖、context 拓扑、输出模型与业务验收条件|**吸收任务节点契约和失败/重试骨架；上层拥有任务图与业务语义**|
|`Crew`|Pydantic 聚合模型、kickoff 生命周期、统一输入/输出、资源/事件收尾|`agents + tasks + manager + process` 的具体组合，hierarchical manager 的业务策略，memory/knowledge/planning 开关|**上层编排对象**；公共底座只借鉴聚合/生命周期接口，不复制 Crew 领域模型|
|`Flow`|FlowDefinition、方法注册、state、触发器匹配、异步执行、暂停/恢复、checkpoint/persistence 接口、最大调用次数|`@start/@listen/@router` 所表达的业务 DAG/分叉条件、方法实现、human feedback 业务决策|**吸收通用流程运行时；Flow 类和图是上层**。路由条件不下沉成平台隐式规则|
|`Process`|`Process.sequential` / `Process.hierarchical` 两个受限策略枚举|顺序任务链、manager Agent、delegation 工具和层级协作策略|**上层策略枚举，不是独立原子能力**；平台可提供“顺序/层级”策略契约，但不能假定未来过程已实现（源码明确 consensual 尚为 TODO）|
|检查点/checkpoint|`RuntimeState` 序列化实体快照 + `EventRecord`；`BaseProvider.checkpoint/afrom_checkpoint/prune/extract_id/from_checkpoint`；JSON/SQLite provider|何时 checkpoint、保存哪些业务输入、恢复哪个实体、恢复后从哪个节点继续|**吸收公共持久化契约；恢复策略由编排 owner 声明**。checkpoint 不是“只保存最后任务结果”|
|分叉/fork|`parent_id`、`branch`、checkpoint lineage；`RuntimeState.fork()` 产生新 branch 并发 fork 事件|分叉点、分支标签、分支选择/合并/回滚业务含义|**吸收 lineage 原子能力；隔离分支业务策略**。当前源码有新分支和父链，未证明通用 merge|
|回调/guardrail/hooks|`SerializableCallable`、Task/Crew before/after/task/step callback；Flow/Task `PRE_STEP/POST_STEP` interception；guardrail 结果校验与有界重试|回调改写输入/输出的业务规则、guardrail 判定标准和 side effect|**事件/hook dispatch 可公共化；业务 callback 仍属上层**。不能把 `None` 过滤等局部行为夸大成“所有坏回调静默降级”|
|工具|`BaseTool` schema、sync/async、类型注册/反序列化、cache、usage limit、结构化结果|工具集合、何时调用、工具结果如何影响业务路由/最终答案|**吸收工具能力契约和资源/限次边界；工具编排留在 Agent/Task/Flow**|
|MCP|MCP server config/transport、resolver 将 server reference 转 `BaseTool`、wrapper 按需连接/调用/重试/清理|某 Agent 使用哪些 server/tool、工具白名单、凭证、租户和授权策略|**隔离为外部协议适配层**。MCP 不是独立编排根，也不应绕过统一工具入口直写业务状态|
|A2A|AgentCard、client/server config、消息/任务状态、轮询/推送/流式、认证、重试错误码、extension registry；Agent wrapper 注入 delegation|选择远程 Agent、最大轮次、fail-fast/trust-remote-completion、会话/上下文和结果映射|**隔离为远程 Agent provider/适配层**。A2A 的协议状态可吸收，远程 Agent 的业务协作图不能下沉|
|事件|单例 `CrewAIEventsBus`、sync executor、独立 async loop、handler 注册/依赖计划、runtime state 绑定、事件上下文|事件类型的业务含义、哪些事件触发路由、listener 的副作用|**吸收事件总线/上下文骨架；事件类型与 listener 组合按领域模块归属**|
|遥测|OpenTelemetry tracer/provider/exporter、Crew/Task/Tool/LLM/Flow/A2A span、禁用开关、安全失败和进程退出 flush|是否采集、采集字段/敏感数据策略、租户/业务标签、平台后端|**吸收可选观测契约；遥测不能成为业务成功条件**。`Telemetry` 的 exporter 失败返回空/记录 debug，不得阻断主流程|

### 14.3 建议的底座单链路落点

```text
项目适配层 / CLI / JSONC-YAML loader
  → 唯一编排根：Crew.kickoff* 或 Flow.kickoff*
  → 运行上下文 + 权限/输入验证 + RuntimeState 注册
  → 编排节点：Process / Flow trigger / Task graph
  → Agent execution contract
  → LLM provider 或 BaseTool.run/arun
       ├─ 内建工具/第三方工具 provider
       ├─ MCP resolver/wrapper → MCP transport → remote server
       └─ A2A wrapper → AgentCard/auth/transport → remote Agent task
  → TaskOutput / Flow method output
  → guardrail / callback / output adapter
  → event bus emit（状态事件、领域事件、失败事件）
  → checkpoint provider / persistence（按 owner 选择）
  → tracing/usage metrics（旁路、可禁用）
  → 统一结果 + 资源清理 + 证据
```

单链路边界：

- **一次运行只有一个 owner**：Crew 或 Flow 负责输入、运行 scope、成功/失败收尾和资源释放；嵌套调用必须继承外层 event/runtime context，不得各自声称是根运行。
- **一次工具调用只有一个工具 owner**：AgentExecutor/ToolUsage 负责选择、参数校验、限次、缓存与工具事件；MCP/A2A 只负责把远程能力转换成工具/任务响应。
- **一次状态写入只有一个状态 owner**：checkpoint provider 只持久化序列化快照，Flow `@persist` 只持久化 Flow state；二者在 Flow kickoff 中明确互斥，不能把两套状态库拼成隐式双写。
- **一次观测只有一个事件源**：执行节点发事件，Trace listener/Telemetry 消费事件；业务代码不要同时手写一套“成功日志状态机”。

## 15. 状态、资源与生命周期边界

### 15.1 状态分层

|状态层|权威内容|生命周期/恢复语义|边界风险|
|---|---|---|---|
|实体快照|`RuntimeState.root` 中的 `Flow/Crew/Agent`，版本、`parent_id`、`branch`、`EventRecord`|`from_checkpoint` 读取 provider 原始 JSON 后 Pydantic 校验；恢复实体后重建 executor、memory view、event scope|调用者不能直接改 provider 文件绕过校验；恢复成功不等于外部 LLM/工具副作用可回滚|
|Crew 运行态|Crew 输入、kickoff event id、Task 输出、Agent executor messages、memory view、训练标记|`Crew._restore_runtime()` 根据 task_started/event record 判断 resuming task，重绑 Agent/Crew/Task 和 memory；随后仍需 `kickoff()`|“最后完成任务续跑”只是调用文档简述，真实恢复包含事件、执行器、输入和记忆视图；不能宣称 exactly-once|
|Flow 运行态|state、pending events、completed methods、method outputs/counts、listener fired 集合、persistence|checkpoint 恢复这些执行字段；`@persist` 通过 state id 另行 hydrate；同一次 kickoff 禁止两套恢复参数同时传入|checkpoint 与 `@persist` 不是同一状态系统；`restore_from_state_id` 找不到时源码会回退 baseline，平台若需要强一致必须另加策略|
|Task 状态|`output`、start/end、retry count、processed agents、guardrail counters、临时 input files|成功生成 `TaskOutput` 后回调/文件输出/完成事件；异常发 `TaskFailedEvent` 并重新抛出|Task 自己直接执行若无 Agent 会失败；线程 Future 与 native async 是不同执行语义|
|工具状态|工具注册类型、args/result schema、usage count、cache callback、限次锁|`run/arun` 每次先校验和原子 claim usage；可序列化工具通过 registry 恢复|工具返回字符串/错误不自动等于业务失败；副作用工具启用 cache 可能复用旧结果，源码已在 Crew cache 字段说明此风险|
|远程任务状态|A2A `submitted/working` pending，`input_required/auth_required` actionable，`completed/failed/rejected/canceled` terminal；A2A delegation state 还含 context/task/history/card|按协议轮询、推送或流式更新，最终映射为 Agent/Task 结果或错误|远程状态不是本地 checkpoint；网络重试、重复消息、远端副作用不可由本地分支自动回滚|
|观测状态|event sequence、scope、pending futures、span、usage aggregation|运行 scope 退出、事件 future drain、span finalize/flush；telemetry disabled/failure 不应改业务状态|不能把 telemetry exporter 成功当业务成功；进程崩溃时只保证尽力 flush，需外部 collector/持久化证据才能审计完整性|

### 15.2 资源所有权表

|资源|创建/持有者|正常释放|失败/取消/崩溃边界与验证|
|---|---|---|---|
|运行 scope/contextvars|Crew/Flow kickoff 根调用|`_exit_runtime_scope`、detach baggage/context token|嵌套调用只由外层清理；异常路径必须验证 scope depth/RuntimeState 已解绑|
|事件线程池/async loop|首次 emit 的单例 event bus|bus shutdown 时 drain/关闭；异步 handler future 自动从 pending 集合移除|handler 异常不能让主流程误报成功；进程强杀时线程/loop 无法由 finally 清理，需子进程/进程退出审计|
|Task daemon thread/Future|`Task.execute_async`|Future set result/exception；任务临时文件 finally 清理|取消语义不能仅凭 Future 状态推断；必须验证线程结束、临时文件目录清空|
|Flow thread pool|`_execute_method` 为同步方法用 `asyncio.to_thread`|await 返回后由运行时释放|同步方法卡死/外部调用不受 Flow 业务超时自动治理；需外围硬截止/子进程隔离策略|
|MCP client/transport|`MCPToolResolver` 持有 `_clients`；wrapper 按次建立 streamable HTTP session|resolver `cleanup()` disconnect 全部 client 并清空列表；wrapper async context 关闭 transport/session|连接失败、timeout、CancelledError、解释器退出都要验证 session/连接关闭；当前 cleanup 记录错误后仍清空引用，不等于远端已关闭|
|A2A HTTP/stream/poll/push 会话|A2A delegation helper/handler|请求/流结束、poll/push handler 完成|认证失败、超时、远端取消、重复 update、断线需验证本地 task/delegation state 不悬挂；远端资源无法由本地 finally 全权释放|
|checkpoint 文件/SQLite|`BaseProvider` 实现|checkpoint 写入；按 branch prune|路径/branch traversal 校验；半写文件、SQLite 写失败、损坏 JSON、进程崩溃恢复需单独实测，当前当前核对只确认契约与 provider 路径|
|Memory/Knowledge/FileInput|Crew/Agent/Task 的 memory、knowledge、文件临时目录 owner|Crew/Task finally 清理临时文件；memory writes 在成功/失败收尾 drain|外部向量库/文件 provider 的连接、锁和缓存释放未在当前核对逐项展开；不得把“clear_files”当所有 provider 资源已释放的证据|
|OTel span/exporter|`Telemetry`/`TraceCollectionListener`|span close、provider force_flush/shutdown（进程退出最多 5 秒）|export 失败被安全吞掉；需用测试 exporter/collector 验证 span 完整性，不能仅凭无异常日志判定已上报|

## 16. 失败矩阵与验证边界

|场景|当前源码行为/证据|底座边界与必须验证|
|---|---|---|
|未知 Process|`Crew.kickoff` 只实现 sequential/hierarchical，其他值抛 `NotImplementedError`|策略注册必须拒绝未实现值；不能将 TODO 的 consensual 宣称为可用|
|Crew/Task 配置非法|Crew validators 拒绝缺 Agent、错误 manager、条件任务首位/全条件等组合；Task 无 Agent 执行时抛异常|装配期失败不应创建半运行；需覆盖非法参数、空 tasks、重复 id/重复 kickoff|
|任务失败|Task 发 `TaskFailedEvent`、记录结束时间、重新抛异常；Crew 发 `CrewKickoffFailedEvent` 并 finally 清理文件/内存写|失败必须保留事件/诊断，且验证 callback、事件 handler 异常不会掩盖原始错误|
|guardrail 失败|guardrail 按索引/次数重试，超过 `guardrail_max_retries` 后失败；Task/Agent 侧均有 guardrail 路径|需区分“业务拒绝”“重试中”“最终失败”；验证重试上限、输出未被错误标成成功|
|callback 异常|Task callback、Crew after callback 在执行链中直接调用；异常进入失败路径，不能泛化为静默跳过|回调是否允许改变结果、是否幂等、失败是否可重试必须由上层契约声明；序列化引用失效只按当前 loader/validator 证据处理|
|工具参数/重复/限次|BaseTool 校验 args schema；usage lock 原子计数；ToolUsage 把解析/选择/执行错误转换为 agent 可见错误字符串并发工具事件|平台若需要稳定错误码必须在适配层补齐，不能把自然语言错误当跨模块契约；验证缓存命中、副作用工具、并发超限|
|MCP 缺库/鉴权/找不到工具|wrapper 对 ImportError、authentication/unauthorized、not found 分别返回不可重试文本；timeout/network/JSON parsing 可重试，最多 3 次并指数退避|验证缺依赖、HTTP 401、404、超时、取消、响应超限/恶意 schema、cleanup 后 clients 为空；当前静态建档没有外部 MCP 实测|
|MCP AMP 配置缺失|resolver 对未连接 slug 发 `MCPConfigFetchFailedEvent` 并跳过该引用；native resolution 异常也发失败事件|“跳过并继续”是 AMP resolver 局部语义，不得直接提升为所有外部依赖默认降级；项目应声明 fail-fast/partial-success 策略|
|A2A 无 Agent/未知 id|delegation context 在没有配置或 id 不在 endpoint 集合时抛 `ValueError`|必须在入口验证 endpoint、auth、协议版本和结果模型；不能让 LLM 生成的 agent id 直接越过白名单|
|A2A 远端失败|配置含 `timeout`、`max_turns`、`fail_fast`、`trust_remote_completion_status`；错误模块区分认证、限流、超时、任务状态和传输协商|验证连接拒绝、401、限流、远端 failed/rejected/canceled、重复 polling、push 超时、最大轮次；本地不能声称远端副作用已回滚|
|checkpoint 找不到/损坏|`restore_from` 为空先报 ValueError；detect provider/read/validate 失败发 RestoreFailedEvent 后重新抛出|必须验证 provider 识别、JSON schema 迁移、损坏/部分写入、父链与 branch；不能用“文件存在”代替恢复成功|
|checkpoint fork|无 runtime state 时 `Crew.fork` 抛 RuntimeError；成功时写新 branch 并保留 parent lineage、发 fork started/completed|验证同 checkpoint 多次 fork 无碰撞、非法 branch、父快照只读、分支隔离；当前源码没有通用 merge 证据|
|Flow 人工反馈|`HumanFeedbackPending` 被识别为 paused，必要时自动启用 persistence 并发 paused event，不等同 failed|验证暂停后重启/重复回复/超时/拒绝反馈；平台不能将暂停误记为失败或成功|
|Flow 循环/分叉|`@start/@listen/@router/and_/or_` 触发；router 先串行，listener 可并行；method completion 持久化，存在 max method calls|验证无 start、条件无命中、and/or 半满足、循环上限、并行 listener 部分失败及顺序；业务分叉由 Flow 图 owner 决定|
|事件 handler 失败/关闭|bus 同步 handler 在线程池、异步 handler 在专用 loop；注册会清执行计划缓存，future 有 tracking/cleanup|验证 handler 异常、依赖环、关闭时 pending future、重复 register/off、嵌套 runtime scope；事件不能成为隐式第二状态机|
|遥测不可用/关闭|`OTEL_SDK_DISABLED`、`CREWAI_DISABLE_TELEMETRY`、`CREWAI_DISABLE_TRACKING` 可禁用；export/操作异常安全返回，退出 flush/shutdown 最多 5 秒|验证 disabled 时零外发、exporter 失败主流程仍正确、敏感字段/`share_crew` 选择、flush 超时；遥测属于旁路能力|

### 16.1 真假验证分层

|等级|能证明什么|当前核对状态|
|---|---|---|
|源码存在|类、入口、分支、异常处理和资源 finally 存在|已对 `crew.py`、`task.py`、`flow/runtime`、`state`、`event_bus`、`tools`、`mcp`、`a2a`、`telemetry` 做静态取证|
|测试源码存在|项目作者为某场景写了测试|已有测试主题已登记在第 9 节；不把测试文件存在当当前核对执行通过|
|静态文档验证|后续裁决表、流程图、证据路径和未确认项一致|当前核对应执行 `git diff --check` + 文档关键章节/旧细探仍存在检查|
|定向测试执行|当前工作树在指定 Python/依赖/环境下真实通过|当前核对未运行 pytest/uv sync/构建/服务；禁止据此写“全绿”|
|外部协议实测|MCP/A2A/OTLP 真实连接、认证、超时、资源释放|当前核对未执行；必须提供隔离 server/collector 或录制 fixture，并记录退出码、请求数和清理现场|
|崩溃/强杀验证|线程、进程、socket、临时文件、checkpoint 半写现场可恢复|当前核对未执行；CrewAI 本地库没有因此自动获得 exactly-once/回滚承诺|

## 17. 底座落地输入与剩余风险

### 17.1 复用/升级/隔离裁决

|类别|结论|落点|
|---|---|---|
|复用|事件总线的 handler 注册/依赖计划、RuntimeState entity snapshot + EventRecord、BaseProvider checkpoint/prune/restore、BaseTool schema/run/arun/usage limit|可作为平台公共契约候选；需要改写为平台统一结果、权限、证据和资源租约|
|升级|checkpoint 的 branch/parent lineage、Flow 的暂停/恢复、Task guardrail 有界重试、MCP/A2A 的超时与状态分类|先登记“状态/恢复/远程调用”能力，再补强一致性、幂等、取消和崩溃证据|
|上层保留|Crew 聚合、Process 选择、具体 Agent/Task prompt、Flow 的业务图、callback 内容、MCP/A2A 目标选择|只由项目适配层/模块编排组合，禁止沉入公共原子能力|
|隔离|MCP transport、A2A HTTP/stream/poll/push、OpenTelemetry exporter、Memory/RAG/外部工具 provider|独立 provider/适配层；主流程只依赖稳定契约，不直接持有第三方对象|
|废弃/禁止照搬|“坏 callback 一定静默丢弃”“checkpoint 等于最后任务续跑”“fork 自动回滚/merge”“遥测成功证明业务成功”|与当前源码证据或底座单 owner 原则冲突，列为禁止宣传的推断|

### 17.2 装配计划（仅研究输入，未启动实现）

1. 先登记四个候选公共契约：运行根入口、任务/工具执行结果、运行状态/检查点、事件/观测记录；每个契约指定一个 owner、版本和错误码集合。
2. 再将 Crew/Flow 作为两种上层模块适配器接入统一运行上下文；做嵌套运行、重入、恢复和失败传播测试，不复制事件总线或状态 provider。
3. 为 MCP、A2A 各自建立 provider contract：凭证来源、连接/会话 ownership、超时/取消、重试、错误映射、幂等键、清理证据；外部服务不可用时返回明确 `PROVIDER_UNAVAILABLE` 类结果而非伪成功。
4. 为 checkpoint/fork 建立状态机和 lineage 验收：创建→写入→恢复→分叉→继续→prune；另外验证损坏、重复、并发、强杀、残留，不把 JSON/SQLite 文件存在当成证据。
5. 为 callback/hook/事件/telemetry 建立旁路契约：事件 handler 和 telemetry 失败不得覆盖业务原始异常；敏感字段脱敏、关闭开关和 flush 结果必须可观察。
6. 只有上述契约、资源表、失败矩阵和真实验证命令冻结后，才进入平台能力搜索/复用裁决；本档案不产生生产代码。

### 17.3 剩余风险

- 本地源码版本基线为 `1.15.17`；MCP/A2A/Flow runtime 的外部依赖、协议版本和传输行为未在当前核对联网/实跑确认。
- event bus 使用单例与 contextvars runtime state；跨线程、跨 asyncio loop、嵌套 kickoff 的隔离正确性需要真实并发测试，静态代码不能替代。
- `Task.execute_async` 的 daemon thread、Flow 的 `to_thread`、MCP/A2A 网络会话和外部 memory provider 的崩溃清理边界仍待强杀/超时验证。
- checkpoint 能恢复本地模型/执行上下文，不等价于 LLM、工具、MCP、A2A 外部副作用可回滚；若平台要求可重放，必须另建幂等键/效果账本。
- `Telemetry` 的安全失败保护降低了观测对业务的耦合，但也可能丢失证据；生产平台需要独立可靠事件/证据账本，不可只依赖 OTel。
- 当前核对首个 `project_context` 返回的是另一项目 `华世王镞_v3` 且代码图实例为 `project_toolkit`；随后按任务给出的 crewAI 绝对路径做了人工源码取证，专属 `system_engineering_toolkit` 的开工/验证服务在当前核对调用时不可达。因此 MCP 开工 id、反馈入账和验证记录尚待服务恢复后补登记，不能伪造为已成功。

## 18. 后续证据索引

- Agent/Crew/Process：`lib/crewai/src/crewai/agent/core.py:171-396`、`agents/agent_builder/base_agent.py:200-797`、`crew.py:159-405,980-1071,1112-1200`、`process.py:4-11`
- Task/guardrail/callback：`lib/crewai/src/crewai/task.py:114-300,572-789`
- Flow DSL/runtime：`lib/crewai/src/crewai/flow/flow.py:1-47`、`flow/dsl/{_start,_listen,_router,_conditions}.py`、`flow/runtime/__init__.py:1947-2309,2646-2815`
- RuntimeState/checkpoint/provider：`lib/crewai/src/crewai/state/runtime.py:352-442`、`state/provider/core.py:10-111`、`state/provider/json_provider.py:147-167`、`state/provider/sqlite_provider.py:16-165`
- 工具：`lib/crewai/src/crewai/tools/base_tool.py:48-227,294-407`、`tools/tool_usage.py:90-269`
- MCP：`lib/crewai/src/crewai/mcp/tool_resolver.py:1-180`、`tools/mcp_tool_wrapper.py:1-203`
- A2A：`lib/crewai/src/crewai/a2a/config.py:465-644`、`a2a/wrapper.py:1-180,966-1063`、`a2a/task_helpers.py:1-140`
- 事件：`lib/crewai/src/crewai/events/event_bus.py:95-396`、`events/listeners/tracing/trace_listener.py:137-734`
- 遥测：`lib/crewai/src/crewai/telemetry/telemetry.py:90-267,269-728`、`telemetry/utils.py:19-112`
- 旧细探仍保留：`细探-crewAI.md`；本次仅修改 `ARCHITECTURE.md`。

## 19. 后续深挖：执行契约、队列与并发

> 本节是后续收口的新增证据。它把“有某个模块”推进到“谁创建、谁持有、谁等待、谁失败、谁清理”。没有运行时实测的地方明确标为静态结论，不把测试源码或方法名当成通过证明。

### 19.1 Agent / Task / Crew 的真实执行契约

|节点|进入条件与状态初始化|实际执行/排队方式|成功出口|失败、取消与重入边界|
|---|---|---|---|---|
|`Agent`|`Agent` 在 post-init 中创建/恢复 LLM、executor、tools、memory/knowledge 等运行对象；`execute_task()` 将 Task、context、tools 交给 executor（`agent/core.py:171-396,760-894`）|默认走 `experimental.AgentExecutor`；旧 `CrewAgentExecutor` 仍可显式选择，但构造时有弃用警告。executor 内部是 `Flow[AgentExecutorState]`，状态含 messages、iterations、tool calls、plan/todos、observations、execution_log（`experimental/agent_executor.py:126-235`）|executor 必须把 `state.current_answer` 变成 `AgentFinish`，再保存 memory 并返回 `{"output": ...}`（`experimental/agent_executor.py:2719-2807,2811-2897`）|同一个 experimental executor 用 `_execution_lock` + `_is_executing` 拒绝并发 invoke；异常 finally 只复位 `_is_executing`，不提供通用 `cancel()`/`close()`。外部 LLM/工具已产生的副作用不回滚。|
|`Task`|`execute_sync`/`aexecute_sync` 设置 start time、写入当前 task id、暂存 input files；无 Agent 直接抛异常（`task.py:572-655,791-809`）|同步执行直接调用 Agent；`execute_async` 启动 `daemon=True` 的独立线程并返回 `concurrent.futures.Future`；native async 才在当前 event loop 中 await（`task.py:596-635`）|构造 `TaskOutput`，执行 guardrail、POST_STEP、callback、文件输出，再发 `TaskCompletedEvent`；finally 清理 task files、重置 ContextVar（`task.py:706-789`）|异常发 `TaskFailedEvent` 后重新抛出。daemon thread 没有保存线程句柄，也没有 Future 取消协作；`Future.cancel()` 即使改变 Future 状态，也不能停止已启动线程或正在进行的 LLM/工具调用。|
|`Crew`|`kickoff` 建立 baggage 的 CrewContext、进入 event runtime scope、准备 inputs/files，并按 `Process` 分支（`crew.py:980-1071`）|sync sequential 逐项执行；标记 `async_execution` 的 Task 先放入 Future 列表，遇到同步任务或到尾部才按顺序等待；native async 使用 `asyncio.create_task` 收集 pending tasks，同样在同步边界/末尾等待（`crew.py:1540-1609,1323-1431`）。这不是全局调度队列，也没有并发度参数。|聚合 `TaskOutput` 为 `CrewOutput`，执行 after callbacks、usage metrics；finally drain memory、`clear_files`、detach baggage、退出 runtime scope（`crew.py:1046-1071,1260-1285`）|任一任务/回调/过程异常进入失败事件并重新抛出；已经启动的 async Task/Future 没有统一取消清单。`kickoff_async` 是 `asyncio.to_thread(self.kickoff)` 的线程包装，不等同 native async；`akickoff` 才使用 native async。|
|层级 Crew|校验阶段要求 manager agent 或 manager LLM；运行时创建 manager、注入 delegation tools，并把 manager 绑定 Crew（`crew.py:709-868,1495-1531`）|manager 仍服从同一个 Task 执行循环；delegation 是工具调用，不是独立 worker queue|manager 产生的 TaskOutput 仍回到 Crew 聚合|manager 自带 tools 会被拒绝并清空后抛错；远程/委派 Agent 的网络、任务状态和副作用不由本地 checkpoint 回滚。|

**结论：** CrewAI 的“并发”是三种局部机制的组合，而非一个可观测的作业队列：Task daemon thread、Crew pending Future/`asyncio.Task` 批次、Flow listener 的 `asyncio.gather`。调用者不能据 API 名称推断存在 worker 取消、排队公平性、全局 backpressure 或 exactly-once。

### 19.2 Flow 的方法队列、触发器和并行边界

Flow `kickoff_async` 每次先处理两套互斥恢复参数、ExecutionStart/Input hooks、state reset/restore、runtime scope 和 usage aggregation；之后决定入口 start 方法。多个无条件 start 默认通过 `asyncio.gather` 并行，只有 `_order_start_methods_for_kickoff` 判定需要串行时才逐个 await（`flow/runtime/__init__.py:1947-2057,2083-2305`）。

方法执行时：

1. 发 `MethodExecutionStartedEvent`，把参数/state 快照放入 `_event_futures`；
2. 同步方法通过 `asyncio.to_thread(context.run, method, ...)`，异步方法直接 await；同步方法返回 coroutine 还会再次 await（`flow/runtime/__init__.py:2646-2729`）；
3. 成功后追加 `_method_outputs`、递增 execution count、加入 `_completed_methods`，再持久化 method completion，最后发 finished event；
4. router 在 listener 前串行追踪结果；普通 listener 用 `asyncio.gather` 并行；`and_`/`or_` 由 `_pending_events` 和 `_fired_or_listeners` 记录触发条件（`flow/runtime/__init__.py:2882-3048`）；
5. 每个 listener 进入前递增 `_method_call_counts`，超过 `max_method_calls` 抛 `RecursionError`，这是循环上限而非取消机制（`flow/runtime/__init__.py:3051-3089`）。

普通异常会发 `MethodExecutionFailedEvent` 并继续向上抛；`HumanFeedbackPending` 是特殊暂停状态：自动建立默认 persistence（若尚无）、保存 pending feedback/state、发 `MethodExecutionPausedEvent`/`FlowPausedEvent`，然后把异常对象作为暂停结果返回而不是把 Flow 标成失败（`flow/runtime/__init__.py:2306-2360,2779-2821`）。

**并发收口：** `asyncio.gather` 默认在任一子任务异常时把异常传播给调用方，但源码没有在 Flow 的 finally 中遍历并显式取消/等待所有已创建的 listener task；因此“一个 listener 失败后其余 listener 一定停止并完成清理”不能作为保证。同步方法已被 `to_thread` 后，协作式取消也不能中断正在运行的 Python/外部阻塞调用。

### 19.3 LLM、工具和模型边界

|边界|源码事实|失败/重试语义|
|---|---|---|
|LLM|`BaseLLM` 统一 `call/acall`、messages、stream、stop、response format、usage；`LLM` 提供 LiteLLM 路径，`llms/providers/` 提供原生 provider（`llms/base_llm.py:150-418`、`llm.py:1820-2089`）|调用前后 hooks 和 started/completed/failed events；部分 provider 不支持 `stop` 时有降级重试。未发现一个跨 provider 的统一取消 token；async 取消取决于 provider/HTTP client。|
|Agent executor|experimental executor 支持 native tool calling 与文本工具调用降级；parser/context length 错误通过 router 增加 iteration 后回到 initialized；`max_iter` 默认为 25，`max_method_calls = max_iter * 10`（`experimental/agent_executor.py:181-230,2680-2717`）|解析错误、context 超长有内部恢复；工具/LLM 永不返回 `AgentFinish` 时最终抛 `RuntimeError`。`step_timeout` 只在 planning step 循环中检查经过时间（`agents/step_executor.py:317-367`），不是包住整个 Crew 的硬超时。|
|`BaseTool`|Pydantic args schema 从 `_run`/`_arun` 签名推导，kwargs 先校验；`run/arun` 先用锁原子 claim usage，再执行工具（`tools/base_tool.py:138-191,199-257,271-353`）|usage claim 在执行前发生；工具抛异常不会回退 usage count。`run` 遇 coroutine 会调用 `asyncio.run`，在已有 event loop 中直接使用可能冲突；native `arun` 没有统一 timeout。|
|`ToolUsage`|先查 cache，再做 usage limit，再调用 `tool.ainvoke`/工具；工具异常发 error event、递增 attempts，未超过 parsing retry 上限时递归重试；finally 尽量发 finished event（`tools/tool_usage.py:276-467,516-704`）|cache 命中会跳过真实副作用；自然语言错误结果可能被送回 Agent 而非立刻抛出。工具调用 retry 不是幂等保证，副作用工具必须由上层提供幂等键或禁用 cache/retry。|
|MCP|`MCPToolWrapper` 每次调用在 `streamablehttp_client(..., terminate_on_close=True)` 与 `ClientSession` 两层 async context 中建连，单次执行 60 秒超时，最多 3 次、退避 1/2 秒（`tools/mcp_tool_wrapper.py:10-15,85-203`）|ImportError/auth/not-found 不重试；timeout/network/json parsing 重试；`CancelledError` 被转换为 `TimeoutError`。返回的是字符串错误/超时文本，不能直接当统一错误码。每次 session 由 context manager 关闭，但重试期间已发生的远端副作用不撤销。|

## 20. 后续资源生命周期与四种终态

|资源|创建/持有者|正常完成|业务失败/主动取消|宿主崩溃/强杀|当前证据等级|
|---|---|---|---|---|---|
|Crew/Flow runtime scope、baggage、ContextVar|根 `kickoff`|`finally` detach/reset、`_exit_runtime_scope`|Crew/Flow 失败路径仍进 finally；取消若命中 Python finally 同样执行|进程被杀无法执行 finally；下次进程只会创建新 ContextVar|源码存在；跨线程/嵌套隔离有 thread-safety 测试源码但当前核对未执行|
|Task input files / 临时文件|Task/Crew file store|Task finally `clear_task_files`，Crew finally `clear_files`|异常路径同样清理；Future 取消不能保证后台 daemon 已结束后再清理外部副作用|强杀可能留下文件，源码未提供启动时全量 orphan sweep 证据|源码存在；残留现场未实测|
|Task daemon thread / Future|`Task.execute_async`|Future 设置 result，线程自然退出|异常设置 exception；Future 没有绑定线程取消，阻塞线程继续运行|宿主退出回收进程资源，线程内外部调用可能在杀前已产生副作用|源码明确无取消契约|
|Crew async tasks / Flow listener tasks|Crew `_execute_tasks`、Flow `gather`|边界 await 完成；Crew finally 做自身清理|异常传播；没有统一 task registry + cancel-and-await 的证据|强杀只由 OS 回收，外部连接/副作用需 provider 自己处理|源码存在；取消/部分失败未实测|
|事件 bus sync executor / async loop|首次 emit 懒创建；sync pool 10 workers，async 专用 daemon loop（`events/event_bus.py:95-191`）|Crew/Flow 显式 flush；进程 `atexit` 调 shutdown|handler 异常被记录，不覆盖主流程；`flush(timeout=30)` 返回 False 但调用方未统一把 False 作为业务失败|`shutdown(wait=False)` 取消 loop tasks 后 stop/join/close pool；强杀无法保证 handler 完成|shutdown 测试源码存在；当前核对未执行|
|MCP session/transport|`MCPToolWrapper._execute_tool` 的两个 async context|离开 context 关闭 session/transport|timeout/取消由 `wait_for` 退出 context；错误重试重新建 session|强杀依赖 MCP client/OS；本地无远端回滚|源码存在；无真实 MCP server 实测|
|Checkpoint 文件/SQLite|`JsonProvider` 文件写入；`SqliteProvider` 每次 `sqlite3.connect`/`aiosqlite.connect`|文件 close 或 SQLite context commit/close；WAL 模式|写失败由异常向上抛；JsonProvider 直接 `open(...,"w")`，未见临时文件+原子 rename|强杀可能留下半写 JSON；SQLite 事务/WAL 由 SQLite 恢复，但不能把这当成应用级 checkpoint 完整性|源码存在；损坏/强杀未实测|
|Memory/Telemetry/usage futures|Crew/Flow 持有；event bus/后台 handler 消费|Crew/Flow `_drain_memory_writes`、event `flush` 后再结束；Flow usage listener 在 finally detach|handler/exporter 失败被记录/安全吞掉，可能造成证据缺失而非业务失败|强杀可能丢 pending memory/trace/usage；无外部可靠账本则不可审计|源码存在；collector/强杀未实测|

**资源裁决：** CrewAI 对“正常完成”和“Python 异常”有较多 finally/上下文管理器；对主动取消、硬超时、进程崩溃只提供局部 provider 语义，没有统一运行句柄、子进程隔离、取消传播、租约或 orphan recovery。因此平台不能把 `finally` 的存在升级为“任意终态资源必清”或“外部副作用可回滚”。

## 21. 失败、取消、崩溃矩阵（后续收口）

|场景|真实行为|不能宣称|底座接入要求|
|---|---|---|---|
|非法 Agent/Task/Crew 配置|Pydantic/业务 validator 在运行前拒绝多种非法组合；Task 无 Agent 在执行入口抛异常|不能把构造成功当执行成功|装配期失败应有结构化错误，不创建半运行租约|
|LLM 空响应/解析错误/context 超长|executor 有 parser/context recovery router；达到迭代/方法上限仍失败|不能宣称任意 provider 错误都自动重试|记录 attempt、provider、是否已产生 tool side effect；上限到达终止|
|工具参数非法/工具异常|schema 校验抛 ValueError；ToolUsage 可能将异常转 Agent 可见错误并有限重试；BaseTool usage claim 可能已消耗|不能把返回的错误字符串当成功或可安全重放|错误码、attempt、cache hit、幂等键必须独立记录|
|Task/Crew callback 失败|callback 在输出/完成事件前后链路直接调用，异常进入失败路径；Crew finally 仍清 files/runtime|不能泛化为 callback 自动隔离或静默跳过|callback 是否阻断、是否可重试、是否幂等需写入契约|
|主动取消 `asyncio` Task|native async 的 `CancelledError` 可沿 await/finally 传播；同步 `to_thread`/daemon thread/外部阻塞调用不保证被停止|不能把取消请求等同实际停止或无副作用|运行 owner 必须持有 task/thread/process/HTTP handle，并验证 cancel→await→残留|
|硬超时|MCP 有局部 `wait_for(60)`；planning step 有 elapsed 检查；Crew/Flow 根入口无统一 timeout 参数|不能把局部 timeout 宣称为全链路 deadline|从根入口传递 deadline，provider 超时、取消和回收都要有证据|
|Flow listener 部分失败|`asyncio.gather` 传播异常；已启动的其他 listener 的停止/清理没有统一显式策略|不能宣称 DAG 具备事务回滚或 all-or-nothing|定义 fail-fast/继续收集/补偿策略，保存每节点终态|
|Human feedback 暂停|专门保存 pending feedback 和 state，发 paused 事件并返回异常对象|不能把 paused 标为 failed/success，也不能把恢复当重复安全|恢复 token、回复幂等、超时和拒绝必须是显式状态机|
|checkpoint 写入中断/损坏|Json 直接写目标文件；SQLite 依赖 SQLite 事务/WAL；恢复失败发事件并抛出|不能仅凭文件存在或 DB 可打开证明快照有效|原子写、schema/hash、损坏隔离、父链校验和强杀恢复验收|
|事件 handler 超时/失败|handler 错误被打印；`flush(timeout=30)` 可返回 False；事件 bus shutdown 可 wait 或 cancel|不能把 event flush 返回值遗漏后仍称观测完整|旁路错误不得覆盖原业务错误；pending/failed handler 要入证据账本|
|宿主崩溃|Python finally、event shutdown、MCP context 均可能完全不执行|不能宣称 exactly-once、外部回滚或自动 orphan 清理|用子进程/隔离 provider 做强杀实验，启动恢复时扫描租约、临时文件、端口和未完成记录|

## 22. 测试真假与验证等级

### 22.1 当前树能证明什么

|等级|现场证据|结论|
|---|---|---|
|源码存在|已逐文件核对 `crew.py`、`task.py`、`experimental/agent_executor.py`、`flow/runtime`、`event_bus.py`、`base_tool.py`、`tool_usage.py`、MCP wrapper、checkpoint provider|证明分支/异常/finally 存在，不证明时序、线程安全或外部协议行为已经通过|
|测试源码存在|`lib/crewai/tests` 有 213 个 `test_*.py`；其中明确覆盖 `test_crew_thread_safety.py`、`test_async_crew.py`、`test_flow_resumability_regression.py`、`utilities/events/test_shutdown.py`、`tools/test_tool_usage_limit.py`、`test_checkpoint.py`、MCP transport 与 LLM provider 测试|证明作者写过目标场景；fixture/mock/patch 可能隔离了真实 LLM、网络或执行器，不能当当前核对通过|
|录制/隔离测试|根 `pyproject.toml:138-154` 配置 `asyncio_mode=strict`、`--block-network`、60 秒 timeout、xdist；多处 `@pytest.mark.vcr()`，并有 `tests/cassettes/`；根 `conftest.py:190-251` 每测清事件 handler、重置事件上下文、创建临时 storage，并修补 VCR/aiohttp/httpx|VCR playback、mock、patch 和 block-network 是可重复性手段，不是当前 provider/网络真实可用性证明；临时目录清理是测试 harness 语义|
|当前核对静态验证|已完成旧细探逐项对照、补入 Agent/Task/Crew/Flow/工具/模型/状态/队列/并发/资源/失败矩阵；旧 `细探-crewAI.md` 仍存在，目标文档非空且保留文本流程图|可声明“文档收口完成”；不能声明 pytest、构建、安装依赖、MCP/A2A/OTLP 真实连接通过|
|当前核对真实执行|未运行 `uv sync`、pytest、mypy、ruff、CLI、服务或外部协议；遵守源码参考库只读研究边界|退出码、测试数、跳过数和现场残留均无当前核对运行证据；最终状态必须写“未执行”，不能写全绿|

### 22.2 反向场景覆盖判断

- **已有源码/测试证据较强：** normal success、Task failure event、guardrail retry、Flow resume/cycle、event bus shutdown、工具 usage limit/cache、JSON/SQLite checkpoint 基本路径。
- **只有静态或局部证据：** Task Future 取消、Flow listener 部分失败后的剩余任务、LLM provider 真取消、MCP 真实 timeout/断线/远端副作用、checkpoint 半写、进程强杀、Memory/Telemetry 丢失后的恢复。
- **当前未形成证据：** 全局队列公平性/backpressure、统一 deadline、跨 provider exactly-once、外部 side effect compensation、重启 orphan 扫描、所有 optional extra 的真实安装组合。

因此测试结论必须按“源码存在 / 测试源码存在 / 录制或 mock 隔离 / 当前核对真实执行 / 外部服务实测”分栏；`pass`、日志打印、VCR cassette、子代理自报和测试文件数量均不能越级为真实通过。

## 23. 后续旧细探逐条收口与最终裁决

|旧细探主张|后续裁决|收口位置与证据|
|---|---|---|
|Crew 是 Agent + Task，Process 为 sequential/hierarchical|**吸收**；补足了 validator、Task batch、manager delegation 和输出/失败路径|第 4、5、19 节；`crew.py:709-868,1495-1609`|
|`from_checkpoint` 是从最后完成任务续跑|**校正**：checkpoint 恢复 RuntimeState、事件记录、实体运行时和 task output 起点；不等于外部副作用回滚或 exactly-once|第 4.5、15、20、21 节；`state/runtime.py`、`crew.py:998-1000,1532-1539`|
|不可解析 callback 静默丢弃|**限定**：当前只确认 `None` 过滤、可序列化 callable/ref 校验和失败路径；callback 执行异常会进入失败，不能宣传“坏回调不阻断”|第 12 节原裁决；`crew.py:407-414,1046-1064`|
|Flow 是事件驱动且支持并发/恢复|**吸收并补边界**：start/listener 的并行来自 `asyncio.gather`，同步方法经 `to_thread`；暂停是 `HumanFeedbackPending` 特殊状态；失败后的 sibling cancel/回滚未证实|第 4.4、5.5、19.2、21 节；`flow/runtime/__init__.py:2297-2305,2646-2821,2882-3048`|
|Agent executor、tool handler、parser 是执行骨架|**吸收并补新 executor 状态机**：experimental executor 有单实例并发拒绝、parser/context recovery、max method calls；旧 executor 仍是兼容路径|第 3.2、5.3、19.1、19.3；`experimental/agent_executor.py:126-235,2680-2897`|
|MCP/A2A 可作为外部协议边界|**吸收为适配层**；MCP wrapper 有局部 timeout/retry/context cleanup，取消被转为 timeout；A2A/MCP 均不提供本地外部副作用回滚|第 17、19.3、20、21 节；`tools/mcp_tool_wrapper.py:85-203`；A2A 路径见第 18 节|
|可借鉴“分叉回滚”|**禁止照搬“回滚”措辞**：当前 fork 保留 parent/branch lineage，Flow state fork 会新 state id；没有通用 merge 或外部补偿证据|第 14.2、15.1、17.1、21 节|

**后续完成标准：** Agent/Task/Crew/Flow 的节点契约、工具/模型边界、状态/队列/并发模型、四终态资源表、失败/取消/崩溃矩阵、测试真假分层和旧细探裁决均已写入唯一 `ARCHITECTURE.md`；`细探-crewAI.md` 按任务要求保留，源码、依赖、配置、测试、README 和 Git 均未修改。后续只需在本文件增量维护事实，不再把旧细探作为并行事实源。

## 24. 后续补充深挖：模型、记忆与事件队列的实际调度

### 24.1 AgentExecutor 是带状态机的单实例执行器

`experimental.AgentExecutor` 继承 `Flow[AgentExecutorState]` 和 `BaseAgentExecutor`。可恢复状态不只是一段消息历史，还包括 `iterations`、当前答案、原生工具调用、plan/todos、replan 次数、逐步 observations 和 execution log（`experimental/agent_executor.py:126-235`）。构造时把 `max_method_calls` 设为 `max_iter * 10`，默认 `max_iter=25`；循环上限同时受到 Agent 迭代约束和内部 Flow 方法调用约束。

执行器私有 `_execution_lock`、`_is_executing`、`_has_been_invoked` 保护同一实例生命周期。它拒绝并发 `invoke`，但没有公开的 cancel/close 运行句柄；`invoke_async` 的取消只能作用于当前 async 等待链，不能自动撤销已经发出的 provider 请求或工具副作用。执行结束时把 `state.current_answer` 收敛为 `AgentFinish`，再保存记忆并返回输出；恢复 executor state 仍不是外部调用事务回滚。

### 24.2 工具调用有两级并行，结果顺序与执行顺序不同

原生 function calling 一次响应中的多个 tool call 会先保存为同一条 assistant message。满足 `_should_parallelize_native_tool_calls()` 时，执行器用最多 8 个线程并行执行，并通过索引恢复结果顺序；不满足时按序执行，以允许 `result_as_answer` 工具短路（`experimental/agent_executor.py:1678-1779`）。因此日志中的工具结果顺序可以稳定，但工具真实完成顺序不稳定；并行工具之间没有内置事务、取消清单或副作用隔离。

这与 Crew 层的 async Task 批次、Flow 层的 listener gather 是三套不同调度机制。它们都不是全局队列：没有统一优先级、租户公平、队列长度、backpressure 或跨层 deadline。若平台要宣称“任务取消完成”，必须同时持有 Crew/Flow task、executor、provider 和工具调用句柄，而不能只调用 `Future.cancel()`。

### 24.3 Crew 的 async 批次是遇到同步边界才排空

native `Crew.akickoff()` 把 `async_execution` Task 放进 `asyncio.create_task`，遇到同步 Task、ConditionalTask 或任务尾部才调用 `_aprocess_async_tasks()` 逐个 await（`crew.py:1343-1431`）。同步 `Crew.kickoff()` 对应地把 Task 放进 daemon thread 返回的 `Future`，也在同步边界/末尾处理。这里的 pending list 是一次 kickoff 的局部批次，不是可被外部查询的持久队列。

若某个 pending Task 失败，异常向上传播；源码没有 Crew 级统一 `cancel-and-await` registry 来遍历其余已启动任务。native async 的 `CancelledError` 能沿 await/finally 传播，但外部 provider 是否停止取决于 provider；daemon thread 不能被 `Future.cancel()` 强制中止。`Agent.max_execution_time` 也只是在线程池中等待结果超时，超时后 future 被 cancel，但线程中的实际执行不保证停止（`agent/core.py:831-864`）。

### 24.4 Memory 是有读屏障的单写线程异步管线

`UnifiedMemory` 启动一个 `ThreadPoolExecutor(max_workers=1)` 作为 `memory-save` 写池，并维护 `_pending_saves`。`remember_many()` 非阻塞提交 `EncodingFlow`，立即返回空列表；后台线程发 started/completed 事件。之后的 `recall()` 会先等待 pending saves，形成“写入异步、读取前屏障”的可见性语义（`memory/unified_memory.py:165-370,523-665`）。后台写失败只发 `MemorySaveFailedEvent`，`drain_writes()` 读取 future 异常但不重新抛给产生记忆的 Crew/Flow。

编码管线的并发上限明确：相似记忆搜索最多 8 个线程，字段解析/合并最多 10 个线程；短内容 recall 跳过 LLM 分析，复杂查询最多选择 20 个 scope，并在最多 4 个线程中搜索 embedding×scope 任务（`memory/encoding_flow.py:199-345`、`memory/recall_flow.py:87-176,178-264`）。单个 scope 搜索失败会记录 warning 并跳过，不会自动把整个 recall 标为失败；“召回成功”可能只是部分 scope 结果。

Memory 的 `close()` 顺序是 drain pending saves → close storage → shutdown 写池；它是显式 owner，而不是进程级可靠写入器。进程强杀可能丢失 pending memory/event；`read_only`、`root_scope`、`MemoryScope`/`MemorySlice` 还会改变写入和可见范围。恢复 checkpoint 后，scope view 只保存路径，必须重新 `bind(memory)` 才能使用，不能把序列化后的 view 当作独立存储。

### 24.5 Flow 的 OR 竞争是唯一明确的 sibling cancellation

普通 listener 使用并行 gather；但对互斥 `or_()`，runtime 会建立 racing group，多个候选 listener 并行启动，首个成功完成后取消其余 racing task；同批非 racing listener 仍正常并行，且异常被 `return_exceptions=True` 收集（`flow/runtime/__init__.py:1043-1165`）。这是局部的 first-wins 路由语义，不是整个 Flow 的取消策略。被取消的同步 listener 若已进入 `asyncio.to_thread`，线程中的 Python/外部阻塞调用仍不保证立即停止。

### 24.6 事件总线是异步投递队列，不是业务状态存储

事件总线首次 emit 时懒创建 10 worker 的同步线程池和 daemon async loop；每个 handler future 加入 `_pending_futures`，完成回调负责移除。`flush(timeout=30)` 等待已投递 future，并返回是否全部完成；handler 异常只打印，不改变业务结果。`shutdown(wait=True)` 先 flush、等待 loop tasks、停止 loop、join 线程并关闭 executor；`wait=False` 则取消 loop 中 pending task（`events/event_bus.py:734-769,897-950`）。

因此事件有投递与排空语义，但不是 durable queue：进程崩溃、`flush` 超时、event bus 在 shutdown 后收到 emit，都可能留下未处理或被忽略的事件。事件记录可进入 RuntimeState/checkpoint，但 handler 执行完成本身不等于 checkpoint 已写入，也不等于 tracing/telemetry 已送达。

### 24.7 后续增量裁决

1. **模型执行**：LLM provider 是可替换调用边界；AgentExecutor state、tool call、usage 和输出是本地运行态，不能包装成 provider 事务。
2. **队列定义**：Crew pending Future、Flow pending event、Memory pending save、EventBus pending future 都是局部内存集合；CrewAI 没有统一作业队列服务。
3. **取消定义**：只有 Flow `or_()` racing group 和 event bus `shutdown(wait=False)` 有明确局部取消动作；Task/Future、Agent timeout、MCP timeout 的取消都不等于底层工作已停止。
4. **记忆定义**：Memory 写入采用单线程后台提交与 recall 读屏障，失败可旁路化；这提供最终可见性，不提供 exactly-once、崩溃恢复或外部向量库事务。
5. **证据定义**：本节仍为源码静态证据。并行完成顺序、取消后的线程残留、Memory 强杀丢失、事件 flush 超时和 provider 真取消均未在当前核对运行验证。

## 25. 全项目审计收口：冲突、歧义与文档噪声

### 25.1 审计边界与分段导航

本次按以下分段完成源码、测试、文档和配置的静态审计；目标仓库存在未跟踪 `.codegraph/` 索引，但它不属于当前 Git 提交的版本化证据；结论以当前提交源码、测试和配置为准。

| 分段 | 主要事实来源 | 本文对应章节 |
|---|---|---|
| 核心领域模型 | `agent/core.py`、`task.py`、`crew.py`、`process.py` | 第 4、5、19 |
| Flow 与状态 | `flow/flow.py`、`flow/dsl/`、`flow/flow_definition.py`、`flow/runtime/`、`state/` | 第 4.4、4.5、5.5、15 |
| 工具与模型 | `tools/`、`agents/`、`llm.py`、`llms/` | 第 5.3、5.4、19.3、24.2 |
| 并发、Future 与取消 | Task daemon thread、Crew pending batch、Flow gather/racing、MCP timeout | 第 19、20、21、24 |
| Unified Memory 与 EventBus | `memory/unified_memory.py`、`memory/encoding_flow.py`、`memory/recall_flow.py`、`events/event_bus.py` | 第 5.6、15.2、20、24.4、24.5、24.6 |
| 测试 | 五个 workspace 的 `tests/`、根 `conftest.py`、`.github/workflows/` | 第 9、22 |
| 文档与配置 | `README.md`、版本化 `docs/`、根及成员 `pyproject.toml`、`uv.lock` | 第 7、8、9、25 |

### 25.2 已裁决的重复与潜在冲突

1. 第 19、20、21 已经完整描述执行契约、资源生命周期和失败/取消矩阵；第 24 又以“后续补充”重述其中的并发、Future、Memory 和 EventBus。两组内容没有发现事实级互相矛盾，但存在文档重复和维护漂移风险。当前保留两组章节以保留研究轮次证据，**第 24 节是增量细节，第 19～21 节是总览裁决**；以后新增事实应只写入本节或替换对应总览，不再复制整张矩阵。
2. “UnifiedMemory”不是源码类名。运行实现公开类是 `Memory`，文件名为 `unified_memory.py`；本文将“Unified Memory”作为架构概念，将 `Memory` 作为代码符号，避免把文件名误写成 API。
3. “事件队列”容易被理解成 durable queue。EventBus 只维护进程内 pending futures，Memory 只维护进程内 pending saves，Crew/Flow 也只有一次运行内的 pending 集合。本文统一称为“局部内存调度集合”，不称作作业队列或持久队列。
4. “取消”必须区分请求状态和底层工作状态。`Future.cancel()`、async task cancellation、MCP `wait_for`、Flow `or_()` sibling cancel 各自只覆盖局部对象；不能合并成 CrewAI 提供全链路取消。本文将 Flow `or_()` 和 EventBus `shutdown(wait=False)` 标为局部明确取消，其余标为取消请求或等待链取消。
5. `Crew.kickoff_async()` 与 `Crew.akickoff()` 不是同义 API：前者把同步 kickoff 放入线程，后者运行 native async 任务链。文中凡涉及“异步 Crew”均应保留这一区分。
6. checkpoint、Flow `@persist`、Memory storage 和 EventBus event record 都涉及状态，但不是同一个持久化系统。本文保留“checkpoint 与 `@persist` 互斥”的运行事实，并明确 Memory/EventBus 的后台状态不能升级为 checkpoint 事务。

### 25.3 语义不清项与统一用词

| 易误读表述 | 统一含义 |
|---|---|
| “恢复/续跑” | 恢复本地快照、运行态和节点起点；不代表外部 LLM、工具、MCP、A2A 副作用回滚或 exactly-once |
| “完成” | 对应本地节点/任务/流程的终态；事件 handler、trace exporter、远端副作用可能仍有独立结果 |
| “资源清理” | 只对源码明确持有的线程、Future、context、文件、session 或 storage 负责；强杀和外部服务不在 finally 保证内 |
| “并行” | 由具体线程池、`asyncio.gather`、`create_task` 或 provider 实现提供；没有全局公平、背压或统一并发度 |
| “失败后继续” | 只在具体 resolver/recall/handler 路径成立；不能推广为所有外部依赖的默认 partial success |
| “架构借鉴” | 研究输入，不是本仓库或其他平台的实现承诺 |

### 25.4 视觉噪声审计

当前根文档的主要视觉噪声不是字符颜色或终端样式，而是结构噪声：章节轮次标签重复、相同事实在表格和长段落中反复出现、研究裁决与源码事实混排、参考索引多次出现。为避免破坏证据链，本次不删除历史段落，也不改动版本化 `docs/` 快照；采用以下收口规则：

- 第 1～10 节保留快速架构地图、公共入口和工程配置。
- 第 11～18 节保留第一次裁决、映射和失败边界。
- 第 19～24 节保留后续执行/资源/取消/Memory/EventBus 深挖。
- 本节作为后续唯一的冲突和术语索引；新增事实应链接到既有章节，不再创建“第 N 轮”重复总览。
- `细探-crewAI.md` 明确是历史材料，不与 `ARCHITECTURE.md` 并列维护；它保留原样，仅用于追溯首轮判断。

### 25.5 文档、测试与配置审计结论

- 根 `README.md` 与源码边界一致地描述 Crews 偏自主协作、Flows 偏精确控制；其产品宣传语不能替代本架构文档中的资源、取消和证据限制。
- `docs/v1.10.1`、`v1.13.0`、`v1.15.4`、`v1.15.5` 是历史版本快照，不能与当前源码无条件混读；本文以当前源码版本 `1.15.17`、根配置和当前测试树为准。
- 根 `pyproject.toml` 明确是 uv workspace，pytest 默认 strict asyncio、阻断网络、60 秒超时和 xdist；这解释了测试的隔离与并行方式，但不证明真实 provider、外部协议或强杀场景通过。
- 测试覆盖面很广，尤其是 Crew、Flow、checkpoint、tool usage、事件关闭和 loader；仍不能把 mock、VCR cassette、测试文件存在或默认 pytest 配置当作当前核对实际执行证据。
- `.env.test` 只确认被测试 harness 加载，本次没有读取其 secret 内容；`uv.lock` 只作为锁定依赖事实，不在本文逐项重建 optional extras 的解析图。
- 本次没有运行安装、pytest、ruff、mypy、构建、CLI、外部 MCP/A2A/OTLP 或强杀验证，因此本文最终状态仍是“静态审计完成，运行验证未执行”。

### 25.6 最终审计结论

未发现 `ARCHITECTURE.md` 与当前已读源码之间的关键事实冲突；发现的是重复分轮、Unified Memory 命名、局部 Future/事件集合被误读为队列、以及取消/恢复/完成语义容易越界的问题，均已在本节显式裁决。文档目前保留较高篇幅是为了保存证据路径，不再增加新的平行根文档。后续维护以当前源码和本文件为准，旧 `细探-crewAI.md` 只作历史追踪。
