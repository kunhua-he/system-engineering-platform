# Haystack 架构建档

> 文档性质：首轮全量架构建档；面向源码参考、边界提取和后续版本对照，不是 Haystack 官方开发规范。
>
> 目标仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/65_rag_frameworks/haystack`
>
> 研究基线：本地 `main`，提交 `c7cb46c0f28ad1984f60e5d3e9404b124a221437`（已与 `origin/main` 同步）；`VERSION.txt` 为 `3.2.0-rc0`。
>
> 事实优先级：当前源码与测试 > `pyproject.toml`/`AGENTS.md` > `README.md` > 已有 `细探-haystack.md` > 远程仓库元数据。
>
> 说明：本文件是本任务唯一新增/修改文件。源码、依赖、测试、配置及既有 `细探-haystack.md` 均未删除或修改。

## 1. 项目定位与边界

Haystack 是 deepset 维护的 Apache-2.0 Python 开源 AI 编排框架，用组件化执行图组织生产级 RAG、语义检索、问答、多模态处理和工具型 Agent。它的核心不是某个模型或某个向量数据库，而是把“组件契约—Pipeline 图—数据模型—DocumentStore/外部集成—生成/工具调用”组合成可检查、可序列化、可同步/异步运行的执行系统。

README 的产品定位为：

- `Haystack`：`production-ready LLM applications` 的开源 AI orchestration framework。
- 通过 modular pipelines 和 agent workflows 显式控制 retrieval、routing、memory、generation。
- 支持 RAG、multimodal applications、semantic search、question answering、autonomous agents。
- 支持同步、异步、流式执行；Agent 支持并发工具调用、生命周期 hooks、步数和 token usage 追踪。
- 模型与厂商无关，集成 OpenAI、Mistral、Anthropic、Cohere、Hugging Face、Google、Azure OpenAI、AWS Bedrock、本地模型等。

### 1.1 本仓库负责什么

1. 定义核心 Python 包 `haystack-ai`。
2. 提供 `component`、`Pipeline`、`SuperComponent`、数据类、序列化/反序列化、内置组件、工具、hooks、tracing、telemetry 和测试基础设施。
3. 通过 `DocumentStore` 协议及独立集成生态承载存储、检索和供应商扩展。
4. 通过 `docs-website/`、`pydoc/`、`examples/` 与 `e2e/` 提供文档、示例及端到端验证。
5. 通过 Hatch 管理开发、测试、类型检查、格式化和发布说明流程。

### 1.2 本仓库不负责什么

- 不把具体 LLM、向量数据库、搜索服务或文件解析器硬编码成唯一后端；大量外部能力在 `haystack-core-integrations` 等独立集成仓库中维护。
- 不提供一个固定的 RAG 业务应用；应用由使用者通过组件和 Pipeline 组合。
- 不以 Hayhooks 为本仓库的 HTTP/MCP 服务层。README 推荐使用 Hayhooks 将 Pipeline/Agent 包装为 REST API 或 MCP server。
- `docs-website/` 是文档站内容，不是运行时服务；其文件数量大，不能按业务源代码规模理解。

## 2. 版本、技术栈与工程规则

| 分类 | 当前事实 |
|---|---|
| 语言 | Python；包名 `haystack-ai` |
| Python | `requires-python = ">=3.10"`；classifier 覆盖 3.10、3.11、3.12、3.13、3.14 |
| 构建后端 | Hatchling；`[build-system]` 使用 `hatchling>=1.8.0` |
| 环境/依赖工具 | Hatch 管理环境，默认 installer 为 `uv`；目标仓库规则明确禁止直接使用 `python`/`pip` 操作项目环境 |
| 图执行 | `networkx.MultiDiGraph`；`PipelineBase` 维护组件节点、socket 和边 |
| 数据校验/模型 | Python dataclasses、类型标注、Pydantic（项目依赖）、自定义 socket 类型兼容检查 |
| 序列化 | `haystack.core.serialization`、`haystack.marshal`、`YamlMarshaller`；组件/Pipeline 提供 `to_dict`/`from_dict`/`dump`/`load` |
| 模板 | Jinja2；`PromptBuilder`/`ChatPromptBuilder` 处理 prompt 与变量声明 |
| HTTP/重试 | `httpx`、`tenacity`、OpenAI client 等 |
| 数值/检索基础 | `numpy`、`networkx`、`more-itertools`；具体 DocumentStore/集成可带额外依赖 |
| 测试 | pytest、pytest-bdd、pytest-cov、pytest-asyncio、pytest-rerunfailures；按 `unit`、`integration`、`slow` 标记 |
| 类型/质量 | Mypy；Ruff lint/format；pre-commit；release note 使用 reno |
| 发布版本 | 本地 `VERSION.txt`：`3.2.0-rc0`；README 顶部宣传语仍写 `Haystack 3.0 is out`，二者应按版本文件与源码基线分别理解 |
| 许可证 | Apache-2.0；README 还展示 license-compliance、OpenSSF Best Practices、HVTrust 等徽章 |

### 2.1 工程规则（来自 `AGENTS.md`）

- 环境管理使用 Hatch；执行项目代码前应确认 `hatch --version` 可用。
- 测试入口：`hatch run test:unit`、`hatch run test:integration`；大型套件优先定向模块或 `-k`。
- 类型检查：`hatch run test:types`。
- 格式与 lint：`hatch run fmt`。
- 面向用户的非文档/非 CI PR 需要 `hatch run release-note SHORT_DESCRIPTION` 生成 release note。
- 本次任务只读研究与写架构文档，未安装依赖、未启动服务、未构建、未运行项目测试。

## 3. 真实目录地图

以下为本地工作树核对后的主要目录；不把文档站的版本化页面全部展开为架构节点。

```text
haystack/
├── haystack/                         # 运行时 Python 包
│   ├── __init__.py                   # 顶层公开入口
│   ├── core/                         # 组件、Pipeline、序列化、安全、类型与错误
│   ├── components/                   # 内置组件目录
│   ├── dataclasses/                  # Document、ChatMessage、内容片段、快照等
│   ├── document_stores/              # DocumentStore 类型、策略、内置存储
│   ├── tools/                        # Tool、Toolset、ComponentTool、PipelineTool
│   ├── hooks/                        # Agent/组件生命周期 hooks
│   ├── data/                         # 数据相关支持类型
│   ├── evaluation/                   # 评估结果与评估支持
│   ├── marshal/                      # YAML/其他 marshaller
│   ├── tracing/                      # tracing 抽象与实现
│   ├── telemetry/                    # 匿名使用遥测
│   ├── testing/                      # DocumentStore 等测试基类/测试支持
│   ├── skill_stores/                 # Agent skill 存储抽象
│   ├── utils/                        # 序列化、请求、类型、异步等工具
│   ├── errors.py                     # 对外/兼容错误入口
│   └── version.py                    # 版本实现
├── test/                             # 单元、集成、契约与安全测试
│   ├── components/
│   ├── core/
│   ├── dataclasses/
│   ├── document_stores/
│   ├── evaluation/
│   ├── hooks/
│   ├── marshal/
│   ├── skill_stores/
│   ├── testing/
│   ├── tools/
│   ├── tracing/
│   ├── utils/
│   ├── fuzz/
│   ├── conftest.py
│   ├── test_imports.py
│   ├── test_logging.py
│   └── test_telemetry.py
├── e2e/                              # 端到端 Pipeline 样例与测试
│   ├── pipelines/
│   └── samples/
├── examples/                         # 示例入口（当前主要为 README）
├── docs-website/                     # Docusaurus 文档站与版本化文档
├── pydoc/                            # API 文档生成支持
├── docker/                           # Docker 相关说明/文件
├── scripts/                          # 开发辅助脚本
├── releasenotes/notes/               # reno release notes
├── images/                           # README/文档图片
├── pyproject.toml                    # 项目、依赖、Hatch、pytest、mypy、Ruff 配置
├── VERSION.txt                       # 当前版本：3.2.0-rc0
├── README.md                         # 产品定位、安装、功能、贡献入口
├── AGENTS.md                         # AI/开发代理规则
├── CLAUDE.md                         # 代理辅助规则
├── CONTRIBUTING.md                   # 贡献规则
├── MIGRATION.md                      # 版本迁移说明
├── SECURITY.md                       # 安全说明
└── 细探-haystack.md                  # 既有中文深探记录，本次保留
```

本地粗粒度规模核对：`haystack/` 约 269 个文件，`test/` 约 294 个文件，`e2e/` 约 10 个文件，`docs-website/` 约 8069 个文件。该统计包含文档站版本化内容，不能直接作为运行时代码规模。

## 4. 分层架构与数据流

### 4.1 总体链路

```text
用户/应用输入
    │
    ├── Document / ChatMessage / ImageContent / FileContent / ToolCall
    │
    ▼
@component 组件实例
    ├── __init__：轻量配置，记录可持久化 init parameters
    ├── warm_up() / warm_up_async()：执行前初始化重型资源
    ├── run() / run_async()：处理输入并返回 Mapping
    └── InputSocket / OutputSocket：声明输入输出契约
    │
    ▼
PipelineBase.graph = networkx.MultiDiGraph
    ├── add_component(name, instance)
    ├── connect(sender, receiver)
    ├── 类型兼容检查、mandatory/default/variadic socket 处理
    └── 序列化为 components + connections + metadata
    │
    ▼
Pipeline
    ├── run()：同步、确定性组件排序与执行
    ├── run_async()：异步执行
    ├── run_async_generator()：按组件完成产出局部结果
    ├── stream()：StreamingChunk 流式句柄
    ├── breakpoint/snapshot：暂停、保存、恢复
    └── tracing/telemetry：运行观测
    │
    ├── DocumentStore + Retriever / Ranker
    ├── Converter / Preprocessor / Embedder
    ├── PromptBuilder / Generator / AnswerBuilder
    ├── Evaluator / Writer / Router
    └── Agent + Tool / Toolset + Hooks
```

### 4.2 核心模块职责

| 模块 | 主要职责 | 关键源码标识 |
|---|---|---|
| 组件注册/契约 | 通过装饰器和元类注册组件、解析 run 签名、建立 socket、校验 async 对称性 | `haystack.core.component.component`、`component`、`ComponentMeta`、`Component` |
| 图编排 | 保存节点、边、连接类型、组件归属和执行限制 | `haystack.core.pipeline.base.PipelineBase` |
| 执行引擎 | 同步/异步/流式调度，消费输入、调用组件、传播输出、包装异常 | `haystack.core.pipeline.pipeline.Pipeline`、`PipelineStreamHandle` |
| 连接校验 | 选择兼容 output/input socket，处理类型转换、变长输入和连接错误 | `haystack.core.pipeline.component_checks`、`_types_are_compatible` |
| 序列化 | 组件、Pipeline、回调、工具和类型的中间表示及 YAML/dict 读写 | `haystack.core.serialization`、`haystack.marshal` |
| 反序列化安全 | 模块 allowlist、解析对象真实模块、危险 builtin 拒绝、unsafe 显式旁路 | `haystack.core.serialization_security` |
| 统一文档 | 文本、二进制、元数据、dense/sparse embedding、score 和稳定 id | `haystack.dataclasses.document.Document` |
| 对话数据 | 多角色、多模态 content part、tool call/result、reasoning、OpenAI 兼容转换 | `haystack.dataclasses.chat_message.ChatMessage` |
| 外部存储边界 | 规定 count/filter/write/delete 与 to/from_dict，不锁定后端实现 | `haystack.document_stores.types.protocol.DocumentStore` |
| Agent | LLM 调用—工具调用—状态更新—退出条件循环；支持 hooks、并发工具和运行元数据 | `haystack.components.agents.agent.Agent` |
| 工具系统 | 统一工具定义、工具集合、组件/ Pipeline 包装和动态选择 | `haystack.tools.Tool`、`Toolset`、`ComponentTool`、`PipelineTool` |
| 生命周期扩展 | Agent run/tool/exit 前后 hook、warm-up、close | `haystack.hooks`、`HookPoint` |
| 观测 | Pipeline/Agent span、日志、匿名组件初始化 telemetry | `haystack.tracing`、`haystack.telemetry` |

## 5. 组件契约：最小可组合单元

### 5.1 `@component` 注册机制

`haystack.core.component.component` 的模块 docstring 明确声明其为组件契约事实源。`component` 是 `_Component` 实例，装饰类时会：

1. 要求类存在 `run`。
2. 以 `ComponentMeta` 重建类，使实例创建时自动解析 I/O。
3. 以 `module.ClassName` 注册到 `component.registry`，供 Pipeline 反序列化查找。
4. 将 `run`/`run_async` 的 `@component.output_types(...)` 缓存解析为 `OutputSocket`。
5. 按 `run`/`run_async` 的签名和注解生成 `InputSocket`。
6. 标记是否支持异步，检查 `run_async` 必须是 coroutine。
7. 记录组件归属 Pipeline，阻止同一实例被多个 Pipeline 共享。

### 5.2 三段式生命周期

- `__init__(...)`：可选且必须极轻量。默认保存能被 JSON 序列化的初始化参数，用于 Pipeline save/load。模型、后端、网络客户端等重型状态不能在此阶段无控制地初始化。
- `warm_up()`/`warm_up_async()`：Pipeline 执行前调用，用于模型、连接池、外部后端等重型准备。Pipeline 不替组件去重，因此组件自身必须保证幂等或避免重复初始化。
- `run(...)`/`run_async(...)`：必选执行方法。输入来自 socket，输出必须是 `Mapping`，且键必须与声明的 output sockets 匹配；执行器将普通异常包装为 `PipelineRuntimeError`。

### 5.3 Socket 和连接规则

- 输入 socket：`InputSocket(name, type, default_value)`。
- 输出 socket：`OutputSocket(name, type)`。
- 连接可写成 `component` 或 `component.socket`；当存在多个候选连接时按名称匹配，否则要求显式指定。
- 默认启用 `connection_type_validation=True`，连接阶段调用类型兼容判断；必要时记录转换策略。
- 多个 sender 连接同一个 list 类型 receiver 时，receiver 可提升为 lazy variadic socket；同步运行按 sender 名称排序，异步运行不保证分支完成顺序。
- 组件不能连接自身；组件名不能重复、不能含 `.`，`_debug` 为保留名。
- 组件实例加入 Pipeline 后带有 `__haystack_added_to_pipeline__`，不能直接跨 Pipeline 复用。

## 6. Pipeline 图与执行语义

### 6.1 图模型

`PipelineBase.__init__` 创建 `networkx.MultiDiGraph`，节点保存：

- 组件实例 `instance`。
- `input_sockets`、`output_sockets`。
- 访问次数 `visits`。
- 边保存 sender/receiver、socket 名、连接类型、mandatory 状态、转换策略。

Pipeline 的可持久化中间表示包括：

```text
{
  "metadata": ...,
  "max_runs_per_component": 100,
  "components": {name: serialized_component},
  "connections": [{"sender": "...", "receiver": "..."}],
  "connection_type_validation": true
}
```

### 6.2 同步 `Pipeline.run`

`Pipeline.run(data, include_outputs_from=None, break_point=None, pipeline_snapshot=None, snapshot_callback=None)` 的主路径是：

1. 记录 Pipeline telemetry。
2. 校验 break point 与 snapshot 不能停在同一组件/访问次数。
3. 执行 `warm_up()`。
4. 规范化输入，执行 `validate_input`。
5. 按组件名排序形成确定性候选序列。
6. 建立 component visits、输入状态、receiver 缓存和优先级队列。
7. 反复选择 `HIGHEST`、`READY`、`DEFER`、`BLOCKED` 组件。
8. `_run_component` 深拷贝输入用于 tracing，调用 `instance.run(**inputs)`，校验返回值为 `Mapping` 及输出键。
9. 将输出写回全局输入状态并传播到下游 socket；只保留叶节点或 `include_outputs_from` 指定节点的输出。
10. 在 `BreakpointException` 或 `PipelineRuntimeError` 时生成 `PipelineSnapshot`，可通过默认文件行为或 `snapshot_callback` 保存，再把快照挂到异常上。

### 6.3 异步和流式

- `run_async` 使用 async component 原生协程；同步组件通过 `_execute_component_async` 转移到 executor。
- `run_async_generator` 以 `concurrency_limit` 控制并发，ready 分支可并行调度；greedy/`HIGHEST` 组件必须独占执行，避免下游继续产生 variadic 输入。
- 组件失败时取消并等待未完成任务；原生 async 任务可被取消，已经在线程中运行的同步组件不能被强行中断，副作用可能继续完成，但其输出不再写回 Pipeline 状态。
- `PipelineStreamHandle` 是异步迭代器；消费结束后 `result` 提供最终输出，放弃迭代时默认在有限清理窗口内取消底层任务。
- Pipeline 与 Agent 都支持 streaming callback；`StreamingChunk` 携带组件执行上下文。

### 6.4 断点、快照和回放

`haystack.dataclasses.breakpoints` 提供 `Breakpoint`、`PipelineState`、`PipelineSnapshot`。快照记录输入状态、组件访问次数、排序、已产生输出、触发组件和恢复信息。恢复时会重新校验快照与当前图一致，并对快照数据做反序列化；不允许使用相同组件/访问次数的 break point 造成原地重复触发。

## 7. 数据模型与外部 API 边界

### 7.1 `Document`

`haystack.dataclasses.document.Document` 是 RAG 数据的核心统一载体：

```text
Document(
    id: str,
    content: str | None,
    blob: ByteStream | None,
    meta: dict[str, Any],
    score: float | None,
    embedding: list[float] | None,
    sparse_embedding: SparseEmbedding | None,
)
```

关键语义：

- `id` 未显式传入时，由 content、blob、MIME、排序后的 meta、dense/sparse embedding 等值组成字符串后计算 SHA-256，保证同值文档的内容寻址标识；meta 排序避免字典顺序影响 id。
- `content` 必须是 `str | None`；旧版 NumPy embedding 会在 `__post_init__` 转为 list。
- `meta` 要求 JSON 可序列化；`blob`、`SparseEmbedding` 有专门的 `to_dict`/`from_dict`。
- `to_dict(flatten=True)` 默认保持 Haystack 1.x 兼容，会把 meta 展平；`flatten=False` 保留显式 `meta`。
- `_RemoveLegacyFields` 在构造入口丢弃 `content_type`、`id_hash_keys`、`dataframe` 等 1.x 遗留字段；`content_type` 属性仍保留部分兼容访问语义。
- 文档可携带文本、图片/音频等文件路径或二进制关联，真正的多模态 content 类型由 `haystack.dataclasses` 下的 `ImageContent`、`FileContent` 等承担。

### 7.2 `ChatMessage` 与多模态内容

`ChatMessage` 使用 `ChatRole`（`USER`、`SYSTEM`、`ASSISTANT`、`TOOL`）和 content part 序列表达对话：

- `TextContent`：文本。
- `ImageContent`：图片与 MIME/detail/base64 信息。
- `FileContent`：文件与 MIME/filename/base64 信息。
- `ToolCall`：模型准备调用的 `tool_name`、`arguments`、`id`、`extra`。
- `ToolCallResult`：工具结果、原始 ToolCall、`error` 标记。
- `ReasoningContent`：可选 reasoning 文本及 provider 扩展 metadata。

`ChatMessage.from_user/from_system/from_assistant/from_tool` 是推荐构造入口；`to_dict/from_dict` 负责当前包裹格式及旧格式兼容；`to_openai_dict_format` 和 `from_openai_dict_format` 处理 OpenAI Chat Completions 形状，并对 tool call id、空消息、多模态 tool result 等边界进行校验。

### 7.3 `DocumentStore` Protocol

`haystack.document_stores.types.protocol.DocumentStore` 只规定后端边界，不规定存储技术：

- `to_dict()` / `from_dict()`：可序列化/恢复。
- `count_documents()`。
- `filter_documents(filters)`：支持 Comparison（`==`、`!=`、`>`、`>=`、`<`、`<=`、`in`、`not in`）和 Logic（`NOT`、`OR`、`AND`）过滤结构。
- `write_documents(documents, policy)`：配合 `DuplicatePolicy.NONE/SKIP/OVERWRITE/FAIL`。
- `delete_documents(document_ids)`。

Retriever 通过具体 DocumentStore 能力实现 keyword、embedding 或 hybrid 检索；后端可在本仓库内提供 in-memory 实现，也可由独立 integration 包提供。

## 8. Agent、Tool 与 Hooks

### 8.1 `Agent`

`haystack.components.agents.agent.Agent` 本身是 `@component`，将聊天生成器、工具和状态机组合为一个可嵌入 Pipeline 的组件。初始化关键参数包括：

- `chat_generator`：必须支持工具参数（当配置 tools 时）。
- `tools`：`Tool` 列表、单个 `Toolset` 或动态 Toolset。
- `system_prompt`/`user_prompt`：可为纯文本模板或 Jinja2 message block。
- `required_variables`：控制 prompt 变量是否必需；默认 `"*"`。
- `exit_conditions`：默认 `text`，也可指定工具名。
- `state_schema`：扩展运行状态；`messages` 自动注入，运行元数据和内部状态键保留。
- `max_agent_steps`：默认 100。
- `tool_concurrency_limit`：默认 4；设为 1 可关闭并行工具执行。
- `raise_on_tool_invocation_failure`：决定工具失败是抛异常还是转为消息回传模型。
- streaming callback、hooks、tool streaming passthrough 等。

### 8.2 Agent 状态与循环

Agent 的运行状态至少包含：

- 用户/系统/助手/工具消息 `messages`。
- `step_count`。
- 聚合的 `token_usage`。
- 每个工具的 `tool_call_counts`。
- `exit_reason`：普通文本、`max_agent_steps` 或工具名。
- 内部 `continue_run`、当前工具、hook context、估算 context tokens。

执行概念链路：

```text
初始化 State
  → before_run hooks
  → before_llm hooks
  → ChatGenerator.run(..., tools=当前工具快照)
  → 记录 token usage / context tokens
  → 若存在 ToolCall：before_tool hooks
  → 重新读取最后消息并执行工具（可并发）
  → after_tool hooks
  → 检查工具退出条件或继续下一步
  → 文本退出 / on_exit hooks（可通过 continue_run 继续）
  → after_run hooks
  → 返回 last_message + 公开 state outputs
```

Toolset 在每次运行会 `spawn()` 隔离运行态，防止并发 Agent 运行共享动态发现状态；按工具名选择时也创建 selection-scoped 副本。

### 8.3 Hooks 边界

有效 hook point 包括 `before_run`、`before_llm`、`before_tool`、`after_tool`、`on_exit`、`after_run`。Hooks 接收 live `State`，可以重写消息、裁剪/脱敏工具结果、实施人工确认、强制工具调用或通过 `continue_run` 影响退出。初始化阶段会校验 hook 对象具有 `run(state)`，并校验 hook 自身允许的 hook point。

## 9. 序列化与安全边界

### 9.1 一般序列化

Pipeline 序列化以 dict 为中间表示，再由 `YamlMarshaller` 等 marshaller 转为文本；组件类型以限定名注册与恢复，初始化参数需可持久化。可调用对象、工具、hooks 和类型 schema 有专门的序列化辅助。

### 9.2 反序列化 allowlist

`haystack.core.serialization_security` 默认允许：

```text
haystack
haystack_integrations
haystack_experimental
builtins
 typing
collections
```

扩展方式：

1. 单次调用：`Pipeline.load(..., allowed_modules=["mypkg.*"])`。
2. 进程级：`allow_deserialization_module(pattern)`。
3. 环境变量：`HAYSTACK_DESERIALIZATION_ALLOWLIST="mypkg.*,otherpkg.*"`。
4. 显式 `unsafe=True`：完全绕过 allowlist，只能用于完全信任序列化来源的场景。

安全实现不是只看声明字符串：

- `_check_module_allowed` 检查模块是否命中模式。
- `_check_resolved_module_allowed` 继续检查解析对象真实 `__module__`，防止从可信模块属性重新导出不可信对象绕过边界。
- callable 反序列化拒绝 `eval`、`exec`、`compile`、`__import__`、`open`、`getattr`、`setattr`、`delattr`、`globals`、`locals`、`vars`、`breakpoint`、`__build_class__`、`type` 等危险 builtin。
- type/class 上下文要求 builtin 解析结果确实为 type。

这是可直接借鉴的安全边界，但不能把 `unsafe=True` 当成默认兼容方案；接入自定义组件时应优先精确加入 allowlist，并对来源和版本负责。

## 10. 组件能力分类

`haystack/components/` 是内置能力目录，当前源码可见的主要类别包括：

| 类别 | 代表用途/源码目录 |
|---|---|
| `builders` | `PromptBuilder`、`ChatPromptBuilder`、`AnswerBuilder`：模板渲染、变量契约、回答组装 |
| `retrievers` | in-memory、embedding、BM25、多查询等检索组件 |
| `rankers` | LLM ranker、lost-in-the-middle、meta-field grouping 等重排 |
| `embedders` | 文本/文档 embedding，含 OpenAI、Azure、mock 等 |
| `generators` | chat/text/image generator 与供应商适配 |
| `converters` | TXT、JSON、CSV、XLSX、PPTX、MSG、图片等转换到 Document/内容模型 |
| `preprocessors` | 清洗、分割、递归/层级分割、embedding-based split |
| `routers` | 文件类型、文档类型、语言、metadata、LLM message、conditional 路由 |
| `joiners`/`caching`/`writers` | 分支合并、缓存命中检查、Document 写入 |
| `evaluators` | recall、context relevance、faithfulness、LLM evaluator 等 |
| `agents` | `Agent`、state、tool calling 和运行控制 |
| `validators`/`extractors`/`samplers` | JSON schema 校验、LLM metadata/图片内容提取、Top-P 等 |
| `super_component` | 将内部 Pipeline 封装为可复用的组件边界 |

外部 integration 项目负责更多数据库、云厂商、搜索系统和模型连接器；本仓库通过稳定的组件、DocumentStore、Tool 和序列化边界吸纳它们。

## 11. 测试与验证地图

### 11.1 测试结构

已读取 `test/` 目录及关键文件名，验证覆盖面包括：

- `test/core/pipeline/`：Pipeline 基础、连接、输入输出、异步、streaming、breakpoint、snapshot、tracing、阻塞/错误。
- `test/core/`、`test/marshal/`、`test/utils/`：类型、序列化、反序列化安全、marshaller、请求和异步工具。
- `test/dataclasses/`：`test_document.py`、`test_chat_message.py` 及其他数据类。
- `test/components/agents/`：Agent、HITL、state class、工具调用相关行为。
- `test/components/retrievers/`、`rankers/`、`builders/`、`converters/`、`generators/`、`evaluators/`、`preprocessors/`、`routers/`：组件契约及能力测试。
- `test/document_stores/` 与 `haystack/testing/document_store.py`：DocumentStore 通用契约测试基类。
- `test/tools/`、`test/hooks/`、`test/tracing/`、`test/telemetry/`：扩展边界、观测与副作用测试。
- `test/fuzz/`：模糊测试支持；`e2e/`：端到端 Pipeline/样例验证。
- `test/conftest.py`、`pyproject.toml`：fixture、pytest 严格 marker、asyncio 模式和覆盖率配置。

### 11.2 测试分层

`pyproject.toml` 将 Hatch test 环境脚本定义为：

- `unit`：`pytest --cov="haystack" -m "not integration"`。
- `integration`：`pytest --maxfail=5 -m "integration"`。
- `integration-only-fast`：过滤 `slow`。
- `integration-only-slow`：只跑慢集成。
- `all`、`e2e`、`types`：全量、端到端、Mypy。

本次仅做源码/规则/测试读取，没有以未确认的环境执行测试，也没有改变测试环境。

## 12. 入口、公开 API 与使用方式

`haystack/__init__.py` 顶层公开：

```text
Answer
ComponentError
DeserializationError
Document
ExtractedAnswer
GeneratedAnswer
Pipeline
SuperComponent
super_component
component
default_from_dict
default_to_dict
```

典型构建方式：

```python
from haystack import Pipeline, Document
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.components.builders import ChatPromptBuilder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.document_stores.in_memory import InMemoryDocumentStore

store = InMemoryDocumentStore()
store.write_documents([Document(content="...")])
retriever = InMemoryBM25Retriever(document_store=store)
prompt_builder = ChatPromptBuilder(template=[...])
llm = OpenAIChatGenerator()

pipeline = Pipeline()
pipeline.add_component("retriever", retriever)
pipeline.add_component("prompt_builder", prompt_builder)
pipeline.add_component("llm", llm)
pipeline.connect("retriever", "prompt_builder.documents")
pipeline.connect("prompt_builder", "llm")
result = pipeline.run({"retriever": {"query": "..."}, "prompt_builder": {"question": "..."}})
```

生产部署边界由 README 指向 Hayhooks，可将 Pipeline/Agent 包成 HTTP/MCP；本仓库本身仍以 Python API 与 Pipeline/Agent 组件组合为核心入口。

## 13. 版本与远程新鲜度核对

- 本地 remote：`https://github.com/deepset-ai/haystack.git`。
- 本地当前分支：`main`，HEAD：`c7cb46c0f28ad1984f60e5d3e9404b124a221437`，且已与 `origin/main` 同步。
- 远程 `origin/main` 查询结果：`46169b5027a2e01a90d2b2fdb7042a0a042852f9`。
- 远程提交与本地提交不同，且远程 main 指针不是落后于本地的情形；因此没有创建“远程落后”专用 4780 独立快照，也没有 fetch、合并或改写本地仓库。
- 直连和通过 `http://127.0.0.1:4780` 的独立 `git ls-remote` 均返回同一远程指针；该结果只用于远程新鲜度核对，不作为当前源码内容证据。
- README 顶部 `Haystack 3.0 is out` 是宣传/文档文本；源码版本文件已是 `3.2.0-rc0`，后续引用 API 时必须绑定具体提交/版本，不应只引用 README 标题。

## 14. 可借鉴边界（不等于直接移植）

1. **Component 三段式契约**：将轻量配置、重型 warm-up、纯执行 run 分开，适合构造可验证的原子能力生命周期。
2. **Socket 类型与连接时校验**：在流程组合阶段提前发现输入输出不兼容，而不是运行到深处才失败。
3. **Pipeline 图调度**：用显式节点/边表达流程、分支、循环、输出保留和调试快照。
4. **内容寻址 Document id**：相同内容和字段生成稳定标识，便于去重、缓存与证据追踪；生产实现仍需明确 schema、版本和隐私边界。
5. **序列化 allowlist**：把“可恢复”与“可执行任意 import”分开，默认拒绝不可信模块；`unsafe=True` 必须是审计可见的显式选择。
6. **Agent 运行元数据**：`step_count`、`token_usage`、`tool_call_counts`、`exit_reason` 为可观测成本/终止原因提供统一契约。
7. **Hook 与运行态隔离**：每次 Toolset 运行创建隔离副本，避免并发任务共享可变发现状态。
8. **Snapshot/Breakpoint**：把失败前状态、访问计数和组件顺序保存为可恢复证据，而不是仅记录一条异常文本。

## 15. 风险、限制与未决项

- **版本漂移风险**：README 仍有 3.0 宣传语，但本地已是 `3.2.0-rc0`；任何后续实现必须以提交和源码为准。
- **外部集成风险**：`haystack_integrations` 与具体模型/数据库 connector 的版本兼容、凭据、网络和服务生命周期不在本仓库核心契约内。
- **反序列化风险**：自定义组件若未正确声明 allowlist，会在安全模式下拒绝加载；粗暴使用 `unsafe=True` 会重新打开任意 import/实例化风险。
- **同步/异步语义差异**：同步 variadic 输入有 sender 名称排序；异步分支不保证完成顺序。同步组件被转移到线程时，取消不等于终止真实副作用。
- **warm-up 幂等风险**：Pipeline 不追踪组件 warm-up 去重，组件实现必须自行控制重复初始化。
- **Document schema 演进风险**：`Document` 保留部分 1.x 兼容逻辑，但 flatten 元数据、遗留字段和自定义 content 仍需按目标版本测试。
- **遥测/隐私风险**：README 声明会收集匿名组件初始化统计；部署或二次集成前应审阅 telemetry 配置与组织合规要求。
- **文档站噪声风险**：`docs-website/` 版本化文件占绝大多数仓库文件数，做源码规模或检索时应排除构建/版本化文档噪声。
- **当前 codegraph 限制**：专属 `system_engineering_toolkit` 的 `codegraph_explore` 已按要求调用，但其代码地图固定指向系统工程平台，未覆盖 Haystack 目标仓库；本建档未把该无关地图结果当作 Haystack 证据，架构结论以目标仓库当前磁盘源码、规则、配置、测试、Git 元数据及既有细探为准。

## 16. 结论

Haystack 的核心价值是一个稳定的“组件契约 + 类型 socket + 图调度 + 可恢复序列化 + Agent 工具状态机”组合，而不是单点模型能力。它适合作为 RAG/Agent 编排边界和工程模式参考：优先提取生命周期、输入输出契约、图连接校验、状态快照与反序列化安全；不要直接复制完整组件目录、集成依赖或生产部署方式。

后续若要继续研究，应按版本提交切片深入：

1. `haystack/core/component/`：组件 socket、装饰器和动态输入输出。
2. `haystack/core/pipeline/`：同步/异步调度、循环、变长 socket、快照恢复。
3. `haystack/core/serialization*`：安全边界、组件注册和兼容策略。
4. `haystack/components/agents/`、`haystack/tools/`、`haystack/hooks/`：Agent 状态机与工具生态。
5. `haystack/dataclasses/`、`document_stores/`：多模态数据模型和外部存储契约。
6. 对应版本 `test/`：用真实测试锁定上述契约，而不是只依赖文档描述。

以上是研究结论，不启动任何 Haystack 源码改造、依赖变更、服务部署或构建工作。

## 17. 旧细探吸收记录与唯一事实源

本节将 `细探-haystack.md` 的有效事实逐条并入本文件；旧文件**按要求保留，不再作为第二份可维护架构结论**。后续版本对照、契约修订和验证结果只更新本 `ARCHITECTURE.md`。

| 旧细探结论 | 当前源码对照 | 裁决 |
|---|---|---|
| `@component` 的 `__init__` 轻量、`warm_up` 准备重型资源、`run` 执行 | `haystack/core/component/component.py:L20-L73` 的模块 docstring 明确写出该契约；`Pipeline.run` 先 `warm_up`（`pipeline.py:L343-L344`） | 吸收；作为组件生命周期契约 |
| 输入/输出 socket 与连接时类型校验 | `component.py:L208-L330` 从签名/注解建立 socket；`base.py:L497-L700` 解析连接、匹配类型并记录转换策略 | 吸收；补充 variadic/async 顺序语义 |
| Pipeline 是 `networkx.MultiDiGraph`，支持同步/异步/流式 | `base.py:L89-L113` 建图；`pipeline.py:L196-L522`、`L777-L1065`、`L1183-L1319` 分别实现三条执行入口 | 吸收；以源码函数链为准 |
| Document 内容寻址 id、JSON meta、多模态/embedding 字段、遗留字段兼容 | `dataclasses/document.py:L32-L112`、`L114-L177`；`chat_message.py:L204-L279`、`L540-L631` | 吸收；明确 flatten 冲突和输入校验边界 |
| 反序列化 allowlist 与 `unsafe=True` | `core/serialization_security.py:L5-L16`、`L137-L221`、`L285-L301`；`core/pipeline/base.py:L175-L208` | 吸收；补充真实对象模块检查和危险 builtin 拒绝 |
| 断点/快照可暂停、保存和恢复 | `core/pipeline/breakpoint.py:L43-L83`、`L131-L211`、`L214-L263`；`pipeline.py:L454-L494` | 吸收；纠正“默认保存”：文件保存需环境变量开启，callback 仍可执行 |
| Component / DocumentStore / Agent 可作为平台借鉴底座 | 源码可证明契约边界，但不能证明外部系统接入、生产吞吐或跨项目复用 | 吸收为“借鉴候选”，不当作已验收平台能力 |
| Hayhooks/MCP、外部集成和许可证线索 | 主要来自 README/仓库元数据，不是本仓库运行时调用链 | 待核/不吸收为核心实现事实 |

### 17.1 事实源优先级

1. 当前工作树源码与测试源码；
2. `pyproject.toml`、`AGENTS.md`、`CLAUDE.md`、`VERSION.txt`；
3. README、迁移文档和 release notes；
4. 旧 `细探-haystack.md` 仅作为已吸收线索。

本次工作树为 `main`、HEAD `c7cb46c0f28ad1984f60e5d3e9404b124a221437`，存在两个未跟踪研究文件：本文件和旧细探；没有修改源码、配置、测试或依赖；源码 checkout 仅执行了 `git pull --ff-only origin main` 以同步远程。

## 18. 契约总表（源码级）

表中“未声明”不是“没有该能力”，而是当前核心契约没有统一声明；不能把 provider 的实现细节外推为 Haystack 全局保证。

| 公开入口/能力 | 输入、所有权与前置条件 | 输出与错误边界 | 重试/超时/取消/幂等/版本 | 证据 |
|---|---|---|---|---|
| `@component` + `__init__` | 类必须有 `run`；初始化参数默认进入 `init_parameters`，须 JSON 可序列化；组件实例由自身持有内部状态 | 装饰器注册限定类路径；签名/注解或 `set_input_type(s)` 建 InputSocket，输出由 decorator 或 `set_output_types` 建立；非法 async 签名抛 `ComponentError` | 核心不重试、不提供统一 timeout；`warm_up` 可能被每次 Pipeline run 调用，组件须自行幂等；组件实例不能同时归属两个 Pipeline | `core/component/component.py:L20-L73`、`L208-L330`、`L572-L644` |
| `Pipeline.add_component` | 名称必须唯一、不能含 `.`、不能为 `_debug`；实例必须是 `@component` 组件；加入后实例所有权转给该 Pipeline | 写入图节点、socket 元数据和 visits=0；重复/非法实例抛 `ValueError`/`PipelineValidationError`/`PipelineError` | 不能跨 Pipeline 共享；`remove_component` 才解除归属；核心无自动重试 | `core/pipeline/base.py:L390-L444`、`L446-L495` |
| `Pipeline.connect` | sender/receiver 组件存在；可显式指定 socket；类型需兼容（可关闭校验）；同一 input 多 sender 仅 list/Optional[list]/list union 可自动 lazy variadic | 写 MultiDiGraph 边、sender/receiver 反向引用、转换策略；自连、无匹配、歧义或类型不兼容抛 `PipelineConnectError` | 连接时确定契约；同步 lazy variadic 按 sender 名排序，异步不保证分支完成顺序；无重试/超时 | `core/pipeline/base.py:L497-L700` |
| `Pipeline.run` | nested 或 flat data；输入必须命中组件和 socket，外部输入不可重复注入已连接 socket；运行前逐组件 `warm_up` | 叶节点（及 `include_outputs_from`）的 Mapping；组件异常包装为 `PipelineRuntimeError`，非法输出/阻塞/超运行次数另有错误；失败时可附 `PipelineSnapshot` | 同步调用阻塞当前线程；无统一 timeout/cancel token；重复执行不是通用幂等保证；同步组件副作用由组件负责 | `core/pipeline/pipeline.py:L196-L323`、`L324-L522`；`core/pipeline/base.py:L1012-L1050` |
| `Pipeline.run_async` / `run_async_generator` | `concurrency_limit >= 1`；async 组件原生 await，sync 组件经 `_execute_component_async` 转线程；输入同同步校验 | 异步返回最终 Mapping，generator 逐组件输出；失败时取消并 drain 未完成 task；sync 线程无法强杀 | 原生 async 任务可取消；线程中的同步函数继续跑完，结果丢弃但副作用可能完成；无全局 wall-clock timeout | `core/pipeline/pipeline.py:L524-L637`、`L777-L1065` |
| `Pipeline.stream` / `PipelineStreamHandle` | 只给支持 async 且有 `streaming_callback` socket 的组件注入 forwarder；可指定组件、并发和 abandon 策略 | `StreamingChunk` async iterator；完整消费后 `result` 可读，未完成/取消/失败会抛 `RuntimeError` 或原异常 | 放弃迭代默认取消；`aclose()` 等待清理最多 1 秒；`cancel_on_abandon=False` 则继续运行；callback 可能阻塞 event loop | `core/pipeline/pipeline.py:L44-L115`、`L1183-L1319` |
| `DocumentStore` Protocol | `Document` 列表、filter DSL、`DuplicatePolicy`；store/后端拥有持久化或索引状态 | `count/filter/write/delete` 及 `to_dict/from_dict`；重复策略决定 skip/overwrite/fail，删除缺失 id 的错误由协议声明 | 协议未声明事务、重试、超时、取消或跨后端幂等；写入计数是已写文档数，不等于业务提交证据 | `document_stores/types/protocol.py:L11-L135` |
| `ChatMessage` / `Document` | 数据类自身校验 content、role、content parts、meta；图片/文件可承载 base64，工具调用需 `ToolCall` | `to_dict/from_dict` 与 OpenAI 转换；非法 role/content/tool id/多模态 tool result 抛 `ValueError`/`TypeError` | 序列化兼容部分旧格式；不负责 provider 重试、超时和传输提交 | `dataclasses/document.py:L56-L177`；`dataclasses/chat_message.py:L216-L279`、`L583-L831` |
| `Agent.run` / `run_async` | `messages`、可选 prompt variables/state/tools；chat generator 配置需支持 tools；每次 Toolset run spawn 隔离副本 | 输出 messages/last_message、step/token/tool counters、exit_reason 和自定义 state；tool 失败默认变为 tool result error message，也可配置抛出 | `max_agent_steps` 是步数上限而非时间 timeout；工具并发上限默认 4；async 可取消但外部 tool 副作用不由 Agent 回滚 | `components/agents/agent.py:L550-L711`、`L783-L860`、`L1011-L1168`、`L1170-L1348` |
| `Pipeline.load/loads/from_dict` | 序列化数据、marshaller、可选 `allowed_modules`；默认只允许受信模块 | 通过 registry 导入并构造组件，再重建边；拒绝模块、危险 builtin、缺类型或构造失败抛 `DeserializationError`/`PipelineError` | 允许列表是模块级安全边界；`unsafe=True` 明确绕过；无版本锁或迁移事务保证 | `core/pipeline/base.py:L175-L287`、`L311-L388`；`core/serialization_security.py:L137-L221` |

## 19. 真实对接调用链

### 19.1 Pipeline 建图、运行、失败恢复

```text
应用
  → Pipeline.add_component(name, instance)
  → Pipeline.connect(sender, receiver)
      → parse_connect_string
      → _types_are_compatible
      → graph.add_edge + socket.senders/receivers
  → Pipeline.run(data)
      → warm_up()
      → _prepare_component_input_data → validate_input
      → _fill_queue → _calculate_priority
      → _consume_component_inputs / _add_missing_input_defaults
      → _run_component
          → instance.run(**inputs_copy)
          → Mapping 与 output keys 校验
      → _write_component_outputs
      → 继续调度至叶节点/include_outputs_from
```

组件异常或 breakpoint 在 `Pipeline.run` 的统一捕获点创建 `PipelineSnapshot`，再由 `snapshot_callback` 或 `_save_pipeline_snapshot` 处理；恢复路径是 `Pipeline.run(pipeline_snapshot=...)`，其首先校验 snapshot 中的组件集合、输入和 visits 是否仍属于当前图。证据：`core/pipeline/pipeline.py:L343-L522`、`core/pipeline/base.py:L1187-L1264`、`core/pipeline/breakpoint.py:L55-L83`。

### 19.2 异步、并发和流式

```text
Pipeline.run_async / run_async_generator
  → warm_up_async
  → Semaphore(concurrency_limit)
  → _schedule_component → asyncio.create_task(_runner)
      → _run_component_async
          → native run_async 或 _execute_component_async(to_thread)
      → _write_component_outputs
  → _wait_for_tasks(FIRST_COMPLETED/ALL_COMPLETED)
  → 失败/取消 → _cancel_in_flight_tasks
Pipeline.stream
  → 为 streaming socket 注入 queue forwarder
  → create_task(run_async)
  → StreamingChunk 入 queue
  → END_OF_STREAM
  → handle.result / aclose
```

`HIGHEST` greedy variadic 节点必须先 drain 其他 task、独占执行，避免下游继续产生输入；普通 READY 节点受 semaphore 限制。sync-to-thread 的取消边界是重要的真实语义：任务 await 可取消，但线程及其外部副作用不能被 Python 强制中断。

### 19.3 Agent、模型、工具和 hooks

```text
Pipeline._run_component(_async)
  → Agent.run(_async)
      → warm_up tools/hooks/chat_generator
      → _initialize_fresh_execution
          → prompt builder 渲染、State 初始化、Toolset.spawn
      → BEFORE_RUN
      → _run_step(_async) × <= max_agent_steps
          → flatten tools + duplicate-name check
          → BEFORE_LLM → chat_generator.run(_async)
          → 记录 token/context usage
          ├─ 纯文本/无工具 → exit_reason=text → ON_EXIT
          └─ BEFORE_TOOL → _run_tool(_async)（并发上限）
               → AFTER_TOOL → tool counters
               → 工具 exit condition 或下一轮
      → AFTER_RUN → _public_outputs
```

`before_tool` 之后会重新读取最后一条消息，因此 hook 可以拒绝/改写 tool calls；`on_exit` 可通过 `continue_run` 继续，但仍受 `max_agent_steps` 约束。工具失败是否抛异常由 `raise_on_tool_invocation_failure` 决定。证据：`components/agents/agent.py:L205-L239`、`L975-L1009`、`L1011-L1348`。

### 19.4 序列化与外部集成边界

```text
Pipeline.to_dict/dumps/dump
  → component_to_dict（限定类路径 + init_parameters）
  → YamlMarshaller/其他 Marshaller
  → Pipeline.load/loads/from_dict
      → _deserialization_context(allowed_modules, unsafe)
      → _check_module_allowed
      → registry/import module
      → component_from_dict
      → add_component + connect
```

DocumentStore、具体 Retriever/Generator、数据库、HTTP 和模型 SDK 通过组件/协议接入；核心 Pipeline 不替 provider 定义凭据、HTTP 重试、事务或远端取消。外部集成的可用性和清理必须单独实测，不能因 pipeline 构造成功而判定接入成功。

## 20. 关键节点明细

| 节点 | 前置/状态变更 | 读写对象与调用关系 | 并发/失败/恢复 | 证据 |
|---|---|---|---|---|
| `ComponentMeta.__call__` | 类已被 `@component` 注册且有 `run`；实例化后设置 async 标志、socket、Pipeline owner=None | 读 run 签名/注解和 output cache；写 `__haystack_input__`、`__haystack_output__`、`__haystack_added_to_pipeline__` | 构造阶段同步；run/run_async 不对称或非 coroutine 立即 `ComponentError`；无恢复 | `core/component/component.py:L294-L330` |
| `PipelineBase.add_component` | 名称未占用、实例尚未加入别的 Pipeline | 写 graph node 与 socket 元数据，同时写实例 owner/name | 非线程安全的图装配操作；失败不应留下节点；移除时清理 socket sender/receiver 与 owner | `core/pipeline/base.py:L407-L444`、`L471-L495` |
| `PipelineBase.connect` | 两端存在且存在唯一可兼容 socket | 写 edge、connection type/conversion strategy、socket 双向连接列表 | 歧义/类型/自连/多 sender 非 list 均拒绝；重复连接无操作；无运行时恢复 | `core/pipeline/base.py:L525-L700` |
| `_calculate_priority` + `component_checks` | 输入状态以 `{sender,value}` 列表表示；mandatory 与 trigger 均需满足 | 只读 socket senders/inputs/visits，输出 HIGHEST/READY/DEFER/BLOCKED | greedy 变长输入最高优先且异步独占；缺输入最终可能只警告 blocked，不等于业务成功 | `core/pipeline/base.py:L1284-L1306`；`component_checks.py:L12-L49` |
| `_run_component` / `_run_component_async` | 组件已 ready；breakpoint 的 component/visit 未先命中 | deep-copy 输入给 tracer/组件；调用 instance；校验 Mapping、输出键、visit；写 span | 普通异常包装 `PipelineRuntimeError`；async 失败由上层 cancel siblings；同步线程取消不可中断 | `core/pipeline/pipeline.py:L125-L194`、`L524-L582` |
| `_wait_for_tasks` / `_cancel_in_flight_tasks` | 有运行中的 asyncio task | 取完成结果；失败时 cancel/gather 并清空 running/scheduled | `return_exceptions=True` 防止 sibling 覆盖原异常；线程任务仍可继续副作用；没有崩溃后进程内清理机会 | `core/pipeline/pipeline.py:L584-L640` |
| `_create_pipeline_snapshot` / `_save_pipeline_snapshot` | breakpoint 或 PipelineRuntimeError，输入可按字段 fallback 序列化 | 读内部 inputs/visits/outputs，写 snapshot 对象、可选 JSON 文件或 callback 目标 | callback 失败按 `raise_on_failure` 处理；文件默认关闭，环境变量 true/1 才写；崩溃前未触发异常则无 snapshot | `core/pipeline/breakpoint.py:L131-L211`、`L214-L263` |
| `Agent._run_step(_async)` | State 已初始化、当前工具已 flatten 且无重复名 | 读写 State messages/usage/counters/tools；调用 generator、tool executor、hooks | tool 可并行；工具错误可转消息；exit hook 可续跑；LLM/工具异常无统一恢复事务 | `components/agents/agent.py:L1170-L1348` |
| `PipelineBase.from_dict` | 输入中有 components/type/connections，allowlist context 已建立 | 读 registry/模块，实例化组件后重建图；不修改原输入（deep copy） | allowlist/导入/构造/连接失败中断；`unsafe` 绕过安全门但不提供兼容性保证 | `core/pipeline/base.py:L207-L287` |

## 21. 资源生命周期与残留责任

| 资源 | 创建/持有 | 成功释放 | 业务失败/取消/超时 | 宿主崩溃与残留核对 |
|---|---|---|---|---|
| Component 内部模型、HTTP client、连接池 | 组件 `__init__` 只应保存轻量配置；`warm_up`/`warm_up_async` 建重型状态，组件实例持有 | `Pipeline.close` 调 `close`；`close_async` 优先调 `close_async`，否则 `close` | 核心不会在每次 run 失败后自动 close；调用方需在 finally/服务生命周期调用 close；没有核心统一 timeout | 进程崩溃时无 Haystack 内部 finally/回收钩子；provider 自身和 OS 负责；需现场查进程、连接和临时文件 |
| Pipeline graph/socket 元数据 | `add_component`/`connect` 写 graph 和 sender/receiver 列表 | `remove_component` 清边、清 socket 引用、重置 owner；整个 Pipeline 无专门 `dispose` | run 期间不要并发修改图；取消只清运行态 task，不回滚图结构 | 崩溃通常由进程回收内存；若组件持有外部资源仍可能残留，不能以 graph 消失替代外部清理证据 |
| 每次 run 的 inputs、visits、queue | `run`/async 入口建立局部 dict、priority queue、task set；输入会 deep-copy | 正常函数返回或 generator finally 清 task；流式 queue 以 sentinel 收尾 | async finally cancel/drain；同步异常依赖栈展开；深拷贝失败直接失败；无跨 run 共享 visits | 宿主崩溃不保证 snapshot；需查未完成 provider 请求/线程和外部副作用 |
| asyncio Task、线程 executor | async scheduler `create_task`；sync-only component 通过 `to_thread` | `_wait_for_tasks` 收割；`_cancel_in_flight_tasks` cancel+gather；stream `aclose` 最多等待 1 秒 | native async 可取消；to_thread 只能放弃 await，线程继续到函数返回；没有强制杀线程方案 | 进程崩溃由 OS 清理线程，但外部 API/写入可能已完成；不可据日志推断回滚 |
| Streaming queue/forwarder | `Pipeline.stream` 建 `asyncio.Queue`，为每个 streaming socket 注入 forwarder | runner finally 放 `END_OF_STREAM`；handle 迭代结束或 `aclose` 清理 task | abandon 默认 cancel；sync callback 在 event loop 内执行可能阻塞；超时只有 1 秒清理等待，不是 provider timeout | 崩溃不会持久化 queue；需查 provider 连接和调用方消费状态 |
| PipelineSnapshot / JSON 文件 | breakpoint/runtime error 创建内存 snapshot；callback 或环境变量开启文件保存 | 文件写入完成后由调用方管理；`load_pipeline_snapshot` 读回并校验对象 | snapshot 序列化/回调失败按配置抛出或记录；默认不写文件；恢复不执行旧图之外组件 | 崩溃前未进入 snapshot 创建点则没有文件；残留 JSON 需按目录、版本和敏感数据治理，源码不自动删除 |
| Agent State、Toolset、Hooks | 每次 Agent run 新建 State；Toolset 通过 `spawn` 隔离；hooks/chat generator 可 warm-up | Agent/组件 `close`/`close_async` 释放 hooks 与 generator；State 随 run 结束 | tool/LLM 失败不提供事务回滚；工具副作用由 tool owner 负责；max steps 只停止循环 | 崩溃不执行 Agent close；动态发现缓存和外部工具资源需 provider 自清理 |
| DocumentStore / Document blob | store 或 integration 持有索引/文档；Document 可持有 bytes/path/blob | Protocol 只规定 delete/写入接口，不规定 close/事务；后端自行负责 | `DuplicatePolicy` 处理重复，不能等价于跨文档原子提交；取消/timeout/崩溃回滚未声明 | 必须以具体后端的事务、日志和 count/filter 读回验证；核心协议没有残留判定 |
| tracing/telemetry payload | span 在 pipeline/component/agent 运行中创建；输入输出可能进入 tags | context manager 结束 span；遥测发送由实现负责 | 失败路径 span 仍依赖 context manager；敏感 image/file 只在 `ChatMessage._to_trace_dict` 做占位需按实现审计 | 崩溃可能留下未上报 span；不可把日志/telemetry 当业务提交证据 |

## 22. 失败、超时、取消、崩溃与幂等矩阵

| 场景 | 核心实际行为 | 可恢复性/假设限制 | 证据与状态 |
|---|---|---|---|
| 非法组件名、缺组件、socket 不存在、类型不兼容 | 装配/输入阶段抛 `ValueError`、`PipelineConnectError` 或 `PipelineValidationError` | 不应进入执行；调用方修正图或输入后重试；无副作用幂等问题 | `base.py:L407-L424`、`L533-L624`、`L1012-L1050` |
| 缺 mandatory input / no trigger | `validate_input` 直接拒绝外部缺参；运行中可能进入 BLOCKED 并记录最可能阻塞节点 | blocked 警告不等于成功结果；必须检查返回值/异常及输出 | `component_checks.py:L28-L49`；`base.py:L1445-L1500` |
| 组件抛异常或返回非 Mapping/未知输出键 | `_run_component` 包装为 `PipelineRuntimeError`；同步 run 创建内存 snapshot 并重抛 | snapshot 可从失败前状态恢复；不保证已发生的外部副作用回滚 | `pipeline.py:L165-L194`、`L454-L494` |
| Pipeline cycle / component visits 超限 | 图调度可处理部分 cycle，但达到 `max_runs_per_component` 抛 `PipelineMaxComponentRuns`；不支持的连接可能 blocked/runtime error | 只能调整图/预算或从 snapshot 研究；没有自动断路器/重试 | `base.py:L1344-L1351`、`L1379-L1400` |
| async sibling 失败 | `_wait_for_tasks` 取消并 gather 其余 task，再保留原异常 | native async 任务可停止；sync thread 与 API/文件副作用可能继续；不具备事务一致性 | `pipeline.py:L602-L640` |
| 主动取消 / stream abandon | generator finally cancel in-flight；`PipelineStreamHandle.aclose` cancel task 并等待 1 秒 | 取消是控制流语义，不是外部操作撤销；`handle.result` 不可在取消后读取 | `pipeline.py:L84-L115`、`L1058-L1064` |
| 超时 | 核心 Pipeline/Agent 没有统一 wall-clock timeout；stream 仅有 task cleanup wait 上限；外部 HTTP/provider 可能自带 timeout | 不能把 cleanup timeout 当远端请求 timeout；需在 provider 或宿主层显式设置和验证 | `pipeline.py:L105-L115`；`agent.py:L550-L627` |
| 宿主/子进程崩溃 | 未进入 Python 异常处理、finally 或 snapshot 创建时，核心没有崩溃恢复协议 | 外部写入、HTTP 请求、线程副作用可能已部分完成；必须由 provider/作业系统提供幂等键、日志和恢复 | 当前源码未发现统一 crash hook；本文件标为未验证 |
| DocumentStore 部分写入/重复提交 | 协议只定义 DuplicatePolicy 和写入计数；具体后端决定原子性/事务 | `OVERWRITE/SKIP/FAIL` 不是跨批次事务；业务需要以 `count/filter` 和后端事务证据核对 | `document_stores/types/protocol.py:L109-L135` |
| Agent tool failure / exit | 默认工具错误变成 `ToolCallResult(error=True)` 回模型；配置为 true 则抛异常；错误 exit tool 不满足 exit condition | tool 副作用不回滚；on_exit 的 continue 仍受 max steps 限制 | `agent.py:L1198-L1231`、`L1298-L1348` |
| 反序列化恶意/过期/缺依赖数据 | allowlist、真实 `__module__` 和危险 builtin 检查；缺 registry/依赖/构造失败中止 | `unsafe=True` 只解决信任边界，不解决版本兼容；必须绑定版本/提交并审计来源 | `serialization_security.py:L150-L221`；`base.py:L229-L277` |
| 重复 run / 重复恢复 | Pipeline 每次 run 建局部 visits；组件 warm-up 与外部副作用是否幂等由组件/provider 决定；同一 snapshot 断点组合会被拒绝以防无进展 | 不得把“同输入返回相同结果”推断成幂等；写入、工具、LLM 调用必须由上层设计幂等键/去重 | `pipeline.py:L324-L337`；`base.py:L926-L981` |

## 23. 防假绿验证分层（L0-L4）

| 等级 | 允许宣称 | 当前核对证据 | 结论 |
|---|---|---|---|
| L0 源码存在 | 文件、类、函数、配置项真实存在且路径可回读 | 已读取 `component.py`、`pipeline.py`、`base.py`、`component_checks.py`、`breakpoint.py`、`serialization_security.py`、`document.py`、`chat_message.py`、`agent.py`、DocumentStore protocol、`pyproject.toml` | 通过；本文所有核心链路至少有源码路径 |
| L1 测试源码存在 | 测试文件/测试名覆盖某行为 | 已核对 `test/core/pipeline/`、`test/core/test_serialization_security.py`、`test/dataclasses/`、`test/components/agents/`、`test/document_stores/` 等目录及关键匹配项 | 部分通过；存在测试不等于当前核对通过 |
| L2 静态/规则检查 | 按仓库规则执行 Hatch/Ruff/Mypy 并记录退出码 | `hatch --version` 退出码 127：当前环境无 `hatch`；依 AGENTS.md 未改用直接 `python`/`pip` 绕过 | 未通过/未执行；不能宣称 lint/type 通过 |
| L3 本地真实测试 | 在目标仓库环境运行定向单测并记录测试数、跳过数、退出码 | 因 `hatch` 缺失未运行项目测试；没有伪造测试输出 | 未验证；不能宣称 unit/integration/e2e 通过 |
| L4 外部依赖实测 | 真实模型、HTTP、DocumentStore 后端、MCP/Hayhooks 或生产资源联调 | 当前核对未安装依赖、未启动服务、未使用凭据、未调用外部 provider | 未验证；README/历史日志不能替代联调证据 |

因此，“源码可证明”与“可运行/可生产”严格分开；任何后续回写必须同时补命令、退出码、测试统计、外部依赖和资源清理读回。

## 24. 未验证项与吸收/不吸收裁决

### 24.1 明确未验证

- 当前环境没有 `hatch`，所以没有执行 unit、integration、e2e、mypy、Ruff 或 Hatch 构建。
- 没有验证真实 OpenAI/其他 Generator、Retriever、DocumentStore integration、HTTP retry、凭据、网络断线和 provider-specific timeout。
- 没有验证 async sync-to-thread 线程是否在真实外部副作用下按预期结束，也没有验证线程/连接池/临时文件的现场残留。
- 没有验证宿主进程 `SIGKILL`、机器崩溃、子进程崩溃后的 snapshot、外部写入回滚和重启恢复。
- 没有验证 `PipelineSnapshot` 在版本漂移、组件 schema 漂移、allowlist 变化和自定义组件 import path 变化下的兼容性。
- 没有把 README 所说 Hayhooks REST/MCP 包装、license CI、OpenSSF/HVTrust 徽章当作本仓库运行时证据。

### 24.2 对底座的裁决

| 候选模式 | 裁决 | 原因 |
|---|---|---|
| 轻量配置 → warm-up → run/close 的组件生命周期 | 吸收 | 核心源码和测试入口均存在，边界清晰；可作为原子能力生命周期参考，但不复制 Python API |
| socket 类型契约、连接时校验、lazy/greedy variadic | 吸收 | 可审计的组合前校验；需在目标底座重新定义类型/版本/错误码 |
| Pipeline 图调度、确定性同步顺序、async 并发和 snapshot | 吸收 | 适合作为流程编排/证据快照模式；线程取消与外部副作用必须保留风险标记 |
| Document 内容寻址、flatten 兼容和多模态 message parts | 吸收 | 适合通用数据模型研究；需另行裁决 schema 版本、隐私和二进制生命周期 |
| 反序列化 allowlist + 真实模块检查 + 显式 unsafe | 吸收 | 安全边界实现证据充分；禁止把 unsafe 当默认兼容方案 |
| DocumentStore Protocol 直接当统一事务存储 | 不吸收 | 只定义接口，不保证事务、超时、原子性、幂等和崩溃恢复 |
| 直接复制 Haystack integrations、模型 SDK、Hayhooks/MCP 服务层 | 不吸收 | 依赖、凭据、网络和服务生命周期不属于当前核心源码事实 |
| “外部集成可生产”“测试通过”“版本兼容” | 待核 | 需要 Hatch 环境、定向测试和真实 provider/后端证据；当前核对不能假绿 |

### 24.3 MCP/代码图证据边界

本轮严格按用户授权未使用 MCP。源码证据来自目标工作树的 Read/Search/Git 与项目本地 CodeGraph；当前索引已同步且状态为 up to date（1,929 files、13,370 nodes、42,154 edges）。其他项目的 MCP、代码图或验证记录均不属于 Haystack 证据。

## 25. 当前核对修改与验证边界

- 唯一修改文件：`ARCHITECTURE.md`。
- 保留文件：`细探-haystack.md`，未删除、未改写。
- 未修改：Haystack 源码、`pyproject.toml`、测试、依赖、Git 历史、配置和外部服务。
- 已完成的现场验证：源码路径与关键函数可读、旧细探完整读取、当前架构文档完整回读、Git 工作树记录、`hatch --version` 失败原因记录。
- 未完成且不能假称完成：项目测试、质量检查、真实 provider 联调、崩溃恢复和资源残留现场验收。

## 26. 后续：通用底座映射与裁决（Haystack → 系统工程平台）

本节是后续“基于底座的映射与裁决”，不是把 Haystack 代码直接搬进平台。映射对象是源码已经证明的边界：组件契约、显式 Pipeline 图、Document/ChatMessage 数据结构、DocumentStore Protocol、Generator/Agent 编排、序列化安全和异步调度。外部数据库、模型 SDK、HTTP 服务和具体集成仍然属于 provider 边界，不能因 Haystack 有一个 Python 类就宣称平台已经具备对应生产能力。

### 26.1 三层归属总表

| Haystack 能力 | 组件支持库（原子契约/Provider 适配） | 文档检索/问答模块（领域编排） | 运行核心（执行治理/资源/证据） | 裁决 |
|---|---|---|---|---|
| `@component`、Input/Output Socket、`run`/`run_async` | 定义组件能力 id、参数/返回/错误码、同步/异步对称契约；provider 只实现公开能力 | 组合 Retriever、Ranker、PromptBuilder、Generator 等领域步骤，不复制 socket 校验 | 装载、权限、预算、生命周期、超时/取消监督和运行证据 | 吸收为三段式原子能力，不复制 Haystack 装饰器注册机制 |
| `Pipeline` 图、连接类型检查、确定性同步调度 | 提供可组合组件的契约元数据和可序列化配置 | 文档摄取、检索、重排、上下文拼装、生成组成一条领域流程 | DAG 装配、任务状态、并发额度、快照、失败恢复和进程边界 | 吸收“显式图+连接前校验”，唯一执行入口仍归运行核心 |
| `Document`、`ChatMessage`、`ToolCall` | 归基础数据/文档支持库；负责 schema、内容寻址、脱敏、版本和二进制句柄 | 将 Document 转为检索上下文、答案引用和对话状态 | 持久化、快照、审计、句柄/临时文件/敏感数据生命周期 | 吸收统一数据结构思想；不把 provider 返回值直接穿透模块 |
| `DocumentStore` Protocol | 实现 SQLite/向量库/全文库/远端搜索等 provider，统一 `count/filter/write/delete` 契约 | 只通过文档检索模块公开入口选择检索策略，不直连 store | 连接、事务、租约、重试预算、健康检查、恢复和残留核对 | Protocol 只算接口，不算事务/幂等/崩溃保证；缺口由运行核心补齐 |
| Retriever/Ranker/Writer/Converter/Embedder | 每个原子能力一个契约 owner；嵌入、切分、过滤、重排和写入分别登记 | 编排唯一检索链路，统一 Document/引用/评分输出 | 调度资源、provider 隔离、失败证据和结果落账 | 吸收模块化，但禁止多个模块各自维护同一检索链 |
| Generator/ChatGenerator | 模型调用、消息转换、流式块、token usage、provider 错误归适配支持库 | 负责 prompt/上下文/答案生成与引用拼装 | 密钥、限流、连接池、超时、取消、重试上限和成本证据 | Generator 是 provider 能力，不是检索模块的隐藏直连 |
| `Agent`、`Tool`、`Toolset`、Hooks | 工具定义、参数 schema、工具调用适配和隔离运行态 | 仅在明确需要工具增强问答时编排 Agent；Agent 不替代检索模块 | 步数/并发预算、授权、取消、崩溃恢复、工具副作用证据 | 吸收状态/预算/hook 边界；不把任意 Agent 作为平台内核 |
| `to_dict`/`from_dict`、YAML marshaller、allowlist | 支持库声明可序列化参数、schema 版本、迁移器和安全反序列化 | 模块保存领域流程配置和版本化检索链描述 | 制品签名、版本锁、快照完整性、原子写入和恢复 | 吸收 allowlist + 真实模块检查；`unsafe` 只能作为显式隔离旁路 |
| `run_async`、`to_thread`、`Semaphore`、stream handle | provider 暴露可取消/流式/异步能力声明 | 模块决定哪些检索分支可并发以及结果合并顺序 | 统一任务、信号量、截止时间、取消传播、排空和残留验证 | 吸收取消语义，但明确同步线程无法强杀，不能伪称已回滚 |

### 26.2 组件支持库边界与组件契约

平台中的组件支持库应把 Haystack 的“可组合但不持有领域流程”原则固定成公共契约。一个组件至少声明：`能力id`、版本、输入字段/类型/是否必填、输出字段/类型、错误码、可重试性、幂等键、资源所有权、同步/异步能力、流式能力、超时预算、取消语义、Provider 路由键和序列化 schema 版本。

```text
组件构造（轻量配置，只保存可序列化 init 参数）
  → warm_up / warm_up_async（按 provider 建立模型、连接或索引句柄）
  → run / run_async（输入契约已校验，返回统一 Mapping/结果）
  → close / close_async（释放句柄、连接、线程/进程和临时资源）
```

映射约束：

1. **构造与执行分离**：`__init__` 不打开网络、不加载大模型、不建立不可控连接；重型资源只能在 `warm_up`，并且组件自己保证幂等。平台的装配器可重复调用 warm-up，不能依赖“只调用一次”的隐含事实。
2. **输入输出冻结**：Haystack 在连接阶段按 socket 做类型兼容检查，平台对应能力契约编译器在装配前冻结参数/返回 schema；运行时仍需再次校验返回键，禁止 provider 直接返回未声明对象。
3. **异步对称**：若声明 `run_async`，其参数和输出契约必须与 `run` 对称。原生异步 provider 使用 `await`；同步 provider 由运行核心放入受监督线程，不允许组件自行创建无界线程池。
4. **状态隔离**：组件实例不能跨两个 Pipeline 共享；平台以运行上下文/租约传递句柄，禁止把连接、游标、HTTP client、模型对象或 Toolset 的可变运行态写入跨任务全局缓存。
5. **结果与异常统一**：模块收到 provider 异常后转换为稳定错误码和诊断字段；错误码不能由每个消费者自行翻译。成功结果不携带伪装的错误对象，部分成功必须明确字段和证据。
6. **关闭对称**：支持库必须提供成功、失败、超时、取消和崩溃后的释放路径；没有 `close`/`close_async` 或无法验证资源释放的第三方组件，只能列为待核 provider，不能晋级生产能力。

### 26.3 Provider 路由：按能力契约选策略，不让 provider 穿透

Haystack 的具体 Generator、DocumentStore、Retriever 和外部 integration 应映射成同一能力契约下的 Provider，而不是在文档问答模块内写 `if openai / if elastic / if pgvector` 的第二套路由。

```text
文档检索/问答模块公开入口
  → 唯一能力调用器
  → 能力id + 版本 + provider 路由约束 + 预算
  → Provider 注册表/健康状态/能力声明
  → 独立环境或独立进程中的第三方 SDK/HTTP/数据库
  → 统一结果、错误码、用量、事件和释放证据
```

Provider 路由规则：

| 路由维度 | 归属与要求 |
|---|---|
| 能力 id/版本 | 由支持库契约 owner 冻结；同一能力只能有一个活跃规范 owner，兼容版本通过显式适配器，不复制能力 id |
| Provider 选择 | 运行前根据能力声明、环境指纹、配置引用、健康状态、权限和预算选择；不得根据异常偷偷切换到未审计 fallback |
| 外部依赖 | 模型 SDK、向量库、全文库、HTTP、动态库放提供者适配层/独立环境；核心只依赖标准接口和统一结果 |
| 连接复用 | 连接池由 provider/运行核心资源协调器共同治理：provider 持有实际 client，运行核心持有租约、上限、空闲/硬截止和释放证据；模块不缓存连接池 |
| 重试 | 只对契约标注可重试且无不可逆副作用的错误重试；每次重试消耗预算并写事件，不能把 timeout、取消或写入失败一律重试 |
| 路由失败 | 无 provider、健康检查失败、能力不匹配、凭据缺失、环境漂移必须返回稳定的 `PROVIDER_UNAVAILABLE`/对应错误，并保留原因；不得返回空答案假装成功 |
| 版本/回滚 | Provider 包、依赖锁、序列化 schema 和能力契约一起签名；切换失败按运行核心发布事务回滚，旧 provider 仍可读但不可产生双写 |

`Agent` 的 `chat_generator`、工具和 Toolset 也遵守同一规则：Agent 只消费 ChatGenerator/Tool 能力契约；动态工具发现通过每次运行的隔离副本，不把 provider 的动态工具列表写成全局共享状态。`tool_concurrency_limit` 是局部并发预算，不是全平台资源治理；全平台仍由运行核心的资源监督器做最终限额。

### 26.4 序列化、连接池和异步执行的三层落点

#### 序列化

- **组件支持库**：把 `init_parameters`、Provider 路由键、能力版本和 schema 版本转换为 JSON-safe 中间表示；自定义对象必须提供 `to_dict/from_dict` 或可解析的导入路径，不能把连接对象、函数闭包、线程、锁、secret 明文写入快照。
- **文档检索/问答模块**：只序列化“检索链声明”（组件名、能力 id、连接、过滤和 prompt 模板），不序列化正在运行的数据库连接、模型上下文和租约；加载时重新经唯一能力调用器装配 provider。
- **运行核心**：在反序列化前执行签名、版本、allowlist、真实模块和路径安全检查；在临时隔离目录解析，校验成功后原子发布。快照必须记录图指纹、组件版本、provider 版本、输入摘要和已执行节点，版本漂移时拒绝盲目恢复。

Haystack 的 `component_to_dict` 会检查序列化值是否为基础类型，`Pipeline.load` 经 allowlist/真实模块检查后重建组件和边；这些是可吸收的安全模式。平台不能把 `unsafe=True` 当作生产兼容选项，也不能把“能反序列化”误判成“provider 版本兼容”。

#### 连接池与资源

Haystack 核心提供 `init_http_client`，将 `limits` 字典转换为 `httpx.Limits` 后创建同步/异步 client；这证明连接池参数属于 HTTP provider 配置，但没有证明存在跨 provider 的统一连接池或事务管理。多查询/多检索器和 Agent 工具还可能使用线程池或并发执行，因此平台的统一资源治理必须在更外层完成：

```text
Provider 创建 client/DB session/模型句柄
  → 运行核心分配资源租约与并发额度
  → provider 执行请求/查询/生成
  → 成功/失败/超时/取消均归还或关闭
  → 运行核心读回活动连接、线程、进程、临时文件和事务状态
```

必须区分：HTTP keep-alive 连接池、数据库连接池、线程池、asyncio task 集合和模型上下文不是同一种资源，不能用一个“池大小”字段替代。连接池不得跨项目、租户或权限上下文泄漏；凭据、代理和 endpoint 只保存配置引用，事件和 tracing 脱敏。

#### 异步执行与取消

- 原生 `run_async`：运行核心创建 task，使用并发额度调度，取消时 `cancel` 并 `gather(return_exceptions=True)` 排空兄弟任务。
- 同步 provider：类似 Haystack `_execute_component_async` 使用线程避免阻塞事件循环，但取消只能取消等待方；正在运行的线程、HTTP 请求、文件写入或数据库副作用可能继续完成。
- 流式执行：stream handle 的 queue/sentinel/`aclose` 模式可吸收；放弃消费默认取消并在有限窗口内清理，但“清理等待超时”不是远端请求 timeout。
- 平台必须把 wall-clock deadline 传给 provider，并在 provider 层设置 HTTP/数据库/模型 timeout；运行核心另外维护任务截止、取消原因、排空结果和残留检查。
- 异步分支若结果合并有顺序要求，必须显式按 sender/检索分支序号排序；不能依赖 task 完成顺序。Haystack 已明确同步 variadic 输入可按名称排序，而异步完成顺序不保证。

### 26.5 文档检索/问答模块与唯一检索链路

文档检索/问答模块是领域编排层，负责把用户问题转换为规范检索请求，组合检索和回答步骤，统一引用与答案结构；它不持有连接池、不读 provider 私有对象、不自行实现第二个错误码表，也不绕过能力调用器。

**唯一规范链路：**

```text
用户问题/过滤/权限/截止时间
  → 文档问答模块.查询
  → 查询规范化与权限过滤（一次）
  → QueryEmbedder/QueryExpander（可选，支持库能力）
  → Retriever（keyword/vector/hybrid 仅按同一检索契约路由）
  → DocumentStore provider（filter/query，返回 Document + score + provider 证据）
  → 去重/分数归一/Ranker（一次统一排序）
  → 上下文预算与引用绑定
  → PromptBuilder/ChatGenerator provider
  → AnswerBuilder/回答契约（答案、引用、usage、诊断）
  → 运行事件、缓存/快照和审计证据
```

链路不变量：

1. **唯一检索 owner**：所有文档检索请求只从文档检索模块进入；Retriever、DocumentStore、Ranker 是链上能力，不允许 Agent、Generator 或业务调用方私自再查一次。
2. **唯一 DocumentStore 边界**：写入、删除、过滤、计数、查询只经 DocumentStore provider 契约；模块不能拿底层 client 直接执行 SQL/HTTP/向量 API。
3. **统一文档与引用**：provider 的 dict、ORM 对象、SDK hit 先转换为统一 Document；答案引用必须绑定稳定 `Document.id`、片段范围、检索链版本和查询摘要，不能只保留模型生成的文字。
4. **检索与生成分责**：Generator 只能基于模块传入的上下文生成；模型输出是候选答案/引用，不是事实写入。引用缺失、文档权限不符或 provider 返回未声明字段必须失败或降级为明确的无答案。
5. **一次路由、一次重排**：keyword/vector/hybrid 是同一 Retriever 能力的 provider 策略；不得让模块串联两个未声明的 Retriever 产生隐含重复召回。重排和上下文裁剪要记录输入/输出计数。
6. **缓存不旁路契约**：命中缓存也必须校验查询规范化摘要、权限范围、链路版本、DocumentStore/provider 版本和过期时间；缓存失效或污染不得静默回源并改变审计语义。
7. **写入链与查询链分开但同一 owner**：摄取侧 Converter→Preprocessor→Embedder→DocumentStore.write，查询侧 Retriever→Ranker→Generator；二者共享文档 schema、provider 路由和证据账本，不建立第二套索引写入服务。

### 26.6 Agent 映射与边界

`Agent` 映射为“模块可选的工具编排组件”，不是新的平台运行核心。其 `messages`、`step_count`、`token_usage`、`tool_call_counts`、`exit_reason` 可吸收为运行元数据；`max_agent_steps`、`tool_concurrency_limit` 可映射为局部预算；hooks 可映射为受契约约束的观察/审批回调。

必须补齐的底座边界：

- Agent 只能调用已经登记、授权和版本锁定的 Tool/模块能力；工具参数先过 schema，工具结果必须有统一错误/敏感数据处理。
- 工具副作用不随 Agent 状态自动回滚；写入类工具必须使用运行核心事务/幂等键，并在成功或失败后读回事实。
- `max_agent_steps` 不是 wall-clock timeout；LLM/工具/provider deadline 由运行核心传递和监督。
- `on_exit` 修改 `continue_run` 只能影响本次状态机，不能绕过权限、预算、取消或发布状态。
- Toolset 的每次 `spawn` 隔离模式可吸收；动态工具发现缓存必须有租约和失效，不得跨运行共享可变列表。
- Agent 崩溃/强杀时，运行核心至少保留任务意图、已调用工具、幂等键、provider 请求 id 和最后状态；恢复采取查询事实、补偿或人工介入，不假设模型能回滚外部副作用。

### 26.7 失败、超时、取消、崩溃与资源矩阵（后续补充）

| 场景 | 组件支持库 | 文档检索/问答模块 | 运行核心与证据 |
|---|---|---|---|
| 契约/类型/序列化参数非法 | 装配前拒绝，返回稳定错误码和字段路径 | 不启动 provider，不生成答案 | 记录拒绝事件；无资源泄漏 |
| Provider 缺失/凭据/健康检查失败 | 返回 `PROVIDER_UNAVAILABLE`/凭据错误，不返回空成功 | 按策略明确降级或失败，不能偷偷换 provider | 写健康状态、路由决策和重试预算；告警但不伪造 L4 |
| HTTP/DB/LLM 业务异常 | provider 转换错误并标记可重试性 | 只重试无副作用、契约允许的节点；答案标记不完整 | deadline、attempt、request id、错误链入账；必要时熔断 |
| 超时 | provider 真实设置请求/查询 timeout | 终止当前链路，禁止把清理等待上限当请求完成 | cancel token/deadline 传播；排空 task、归还租约、核对连接/事务 |
| 主动取消/stream abandon | 原生 async 可取消；同步线程只能放弃等待 | 取消查询/生成并释放模块级临时状态 | 记录取消原因/调用者/任务状态；对不可取消副作用启动补偿或人工核对 |
| 同步 provider 在线程中运行 | 不能强杀线程，必须声明副作用风险 | 不把“await 返回”当 provider 已停止 | 线程任务有界；进程级 provider 必要时用独立进程组强杀和回收 |
| sibling/分支失败 | 失败结果不吞，释放本组件资源 | 取消其余分支并保留原始错误；不得拼接半套引用 | `cancel + drain`，保留快照/执行图/已完成节点 |
| DocumentStore 部分写入/重复写 | 遵守 DuplicatePolicy；声明是否有事务 | 写入成功数不能等价业务提交成功 | 用 provider 事务/幂等键/读回 count/filter 对账；失败保留证据 |
| Agent 工具失败 | 按契约转 ToolCallResult(error) 或抛出 | 决定继续问答还是明确失败；不把错误工具结果当事实 | 授权、步数、工具调用计数和副作用状态入账 |
| 崩溃/SIGKILL/机器重启 | provider 需独立进程/连接恢复或标记不可用 | 链路状态进入未完成，不自动重复产生答案/写入 | 从持久意图、幂等键和 provider request id 恢复；核对进程、端口、锁、连接、临时目录、事务残留 |
| 重复 run/重放快照 | 组件/provider 必须声明幂等性，禁止默认假设 | 同一查询可复用缓存但须校验链路/权限版本 | 任务幂等键、快照图指纹、版本锁和重放证据；拒绝过期快照 |

### 26.8 L0-L4 映射验收门

后续把原项目研究等级转换为平台候选能力的晋级门槛；“源码存在”不能直接升级为“平台可用”。

| 等级 | 对 Haystack 的证据 | 平台映射后的最低验收 |
|---|---|---|
| **L0 源码事实** | 组件、Pipeline、DocumentStore、Agent、序列化和 async 源码路径已核对；测试文件路径已核对 | 完成能力命中/缺口表，固定能力 id、边界 owner 和不吸收项；不产生平台实现 |
| **L1 契约/静态** | `component.py` 明确 init/warm_up/run，Protocol 明确 store 方法，serialization security 明确 allowlist，pipeline 明确 task cancel | 平台契约编译、依赖/配置/权限/资源静态检查通过；非法参数、缺 provider、未知输出键、危险反序列化有反向用例 |
| **L2 本地真实组件** | 在受控环境定向运行组件/模块测试；同步、异步、快照、DocumentStore 通用契约分别记录测试数/skip/退出码 | 至少真实运行一条摄取→写入→检索→生成链；provider 缺失不能用 skip 伪绿；资源清理读回通过 |
| **L3 provider/运行核心联调** | 真实 HTTP/模型/存储 provider、连接池 limits、超时取消、并发和崩溃注入 | 通过唯一能力调用器和运行核心；验证路由、权限、租约、重试、deadline、取消排空、事务/幂等、快照恢复；逐项记录外部服务与退出码 |
| **L4 生产/跨版本证据** | 目标版本提交、依赖锁、序列化迁移、真实后端和故障恢复均有可复现实验 | 仅在 L0-L3 全部有证据后晋级；需签名制品、环境指纹、回滚/重启/资源残留清零和真实业务数据脱敏验证。当前 Haystack 研究没有 L4 证据 |

本仓库当前仍是 L0 已充分、L1 研究证据较充分、L2-L4 未完成的候选输入。`hatch` 不可用导致当前核对没有项目测试执行；该事实不能通过 README、测试文件存在或历史输出补齐。

### 26.9 后续能力命中、缺口与装配计划

| 能力/模式 | 现有底座命中 | 缺口 | 裁决/下一步 |
|---|---|---|---|
| 组件生命周期与输入输出契约 | 公共契约、组件规范、契约编译、支持库注册表、运行核心生命周期 | 需明确 async 对称、流式、资源所有权字段 | **升级现有组件支持库**，先补契约字段和反向破坏场景，不新建第二套 Component 注册器 |
| Pipeline/DAG 图编排与快照 | 运行核心任务/DAG/快照/发布恢复模式可复用 | 需把图指纹、节点访问次数、分支顺序纳入统一快照契约 | **升级现有运行核心/任务系统**，文档问答模块只提交领域计划 |
| Document/ChatMessage/引用 | 公共契约基础类型、文档支持库、内容寻址/脱敏候选 | 需冻结统一文档 schema、片段范围、引用和二进制句柄生命周期 | **升级现有文档支持库**，provider dict 只在模块边界转换一次 |
| DocumentStore/检索 provider | 外部 provider 注册表、资源协调、真实数据库/HTTP provider 模式 | 当前研究未证明统一事务、向量索引、混合检索和跨 provider 幂等 | **新建/升级受管文档存储支持库前先走能力需求登记**；不把 Protocol 直接视作完成 |
| Retriever/Ranker/Generator 问答编排 | 模块库领域编排、唯一能力调用器、Generator provider 边界可复用 | 尚无本项目对应的平台模块、引用证据和统一答案契约 | **新建文档检索/问答模块候选**，但必须先冻结能力 id、唯一链路和验收契约 |
| Agent/Tool/Hooks | 运行核心授权、异步任务、资源监督、控制调用、审计证据可命中 | Agent 状态持久化、工具副作用补偿和崩溃恢复需专门设计 | **升级运行核心 + 新增受限 Agent 模块候选**；禁止 Agent 直接成为网关/数据库 owner |
| 序列化/allowlist | 契约编译、制品签名、核心快照、路径安全模式可复用 | 需 schema 迁移、provider 版本锁和快照拒绝策略 | **升级现有序列化/快照支持库**；`unsafe` 永不作为默认通道 |
| 连接池/异步/取消 | 资源监督、Future/task 取消、进程组、HTTP/数据库提供者边界可命中 | 当前 Haystack 核心无统一池和 wall-clock 机制，sync-to-thread 副作用不可强杀 | **升级运行核心资源协调 + provider 契约**；不得仅复制 `asyncio.to_thread` |

装配顺序固定为：

```text
需求登记/能力搜索
  → 组件契约与文档 schema 冻结
  → 复用裁决/占用租约/Provider 能力定义
  → 文档支持库（Document/引用/序列化）
  → DocumentStore/Embedder/Retriever/Ranker/Generator provider
  → 文档检索/问答模块唯一链路
  → Agent 工具编排（如确有需求）
  → 运行核心资源、任务、快照、恢复和证据接线
  → L1 静态 → L2 本地链 → L3 provider 联调 → L4 生产门禁
```

当前核对不创建上述平台文件、不登记能力、不改系统工程平台；这是 Haystack 后续输入，正式实现必须由需求确认和装配计划启动。

### 26.10 后续裁决摘要

- **吸收**：三段式 Component 生命周期、连接前 socket 类型检查、显式 Pipeline 图、Document/ChatMessage 统一载体、序列化 allowlist/真实模块检查、Agent 运行元数据和 Toolset 运行态隔离、async cancel+drain 语义。
- **升级现有底座**：组件契约编译、文档基础类型、唯一能力调用器、运行核心任务/资源/快照/授权/证据、外部 provider 注册与健康状态；不得新增平级注册表、任务系统或网关。
- **建立候选模块**：文档检索/问答模块，前提是需求登记、能力 owner、唯一检索链路、引用契约和 L0-L4 验收契约先冻结。
- **不吸收**：把 Haystack `DocumentStore` Protocol 当作统一事务数据库，把具体 integration/SDK/连接池当作平台核心，把 `unsafe=True` 当默认兼容，把 Agent 当作可绕过权限和资源治理的新内核。
- **待核**：真实 provider 的连接池复用、事务/部分写入、超时可取消程度、进程崩溃恢复、版本迁移和生产负载；这些必须有 L2/L3/L4 现场证据。

## 27. 后续唯一事实源与验证记录

本节与前文不一致时，以当前源码/测试和本节明确的三层 owner、唯一检索链路及 L0-L4 门槛为准；旧 `细探-haystack.md` 继续保留，不再扩展为第二份事实源。后续唯一修改仍为 `ARCHITECTURE.md`，没有修改源码、配置、依赖、测试、README 或 Git。

- 开工/工具边界：本轮按用户授权**未使用任何 MCP**；证据来自目标工作树的只读源码、测试路径、Git 与项目本地 CodeGraph。不得把其他项目（包括 V3）的 MCP/代码图/验证记录当作 Haystack 证据。
- 项目本地 CodeGraph：索引位于目标根 `.codegraph/`，已在远程快进后执行 `codegraph sync`；当前 `status` 为 1,929 files、13,370 nodes、42,154 edges，SQLite WAL 39.55 MB，状态为 `Index is up to date`。该索引仅用于源码研究，不是 MCP 服务。
- 现场验证边界：修改后应只做文档差异检查；Hatch、项目测试和真实 provider 联调仍按 L0-L4 如实标记，不能因文档写入成功宣称 L2-L4 通过。

## 28. 后续检索底座映射：组件、管线与 RAG 运行边界

本节把后续范围收敛为一张可装配的检索底座地图：组件、管线、文档、存储、embedding、检索、生成、序列化、资源、失败与取消。这里的“映射”只说明职责和边界，不表示目标平台已经实现这些能力。Haystack 的事实依据是本仓库 `haystack/` 与 `test/` 当前工作树；平台侧只给出候选 owner、契约和验收要求。

### 28.1 端到端对象图

```text
文件/外部文档
  → Converter（Document / FileContent）
  → Preprocessor（clean / split / metadata）
  → DocumentEmbedder（Document.embedding / sparse_embedding）
  → DocumentWriter（DocumentStore.write_documents + DuplicatePolicy）
  → DocumentStore（count / filter / backend index）

用户 query + filters + top_k
  → TextEmbedder（query → embedding，可选）
  → TextRetriever 或 EmbeddingRetriever
  → DocumentStore provider（Document + score）
  → Joiner / Ranker / Filter / context budget
  → PromptBuilder / ChatPromptBuilder
  → ChatGenerator / Generator
  → AnswerBuilder（答案、引用、usage、诊断）
```

在 Haystack 中，上述每个方框都是可加入 `Pipeline` 的组件，连接由 socket 约束；在目标底座中，方框应分别落为公开能力契约或一个领域模块步骤，不能把整条链实现为一个不可审计的“RAG 函数”。

### 28.2 九类职责映射

| 检索底座对象 | Haystack 源码事实 | 目标平台建议 owner | 必须冻结的契约 | 明确不应外推 |
|---|---|---|---|---|
| 组件 | `@component`、`ComponentMeta`、Input/OutputSocket；`__init__`、`warm_up`、`run`/`run_async` | 组件支持库 + 运行核心装载器 | 能力 id/版本、输入输出 schema、错误码、幂等、资源所有权、async/stream/cancel | 装饰器注册本身不是平台注册表 |
| 管线 | `PipelineBase` 用 `networkx.MultiDiGraph` 保存节点、边、socket 和 visits；`Pipeline` 提供 sync/async/generator/stream | 运行核心任务图；文档问答模块只提交领域图 | 图指纹、节点版本、边类型、输入校验、并发预算、输出保留、快照格式 | 图能运行不等于任务有事务或崩溃恢复 |
| 文档 | `Document` 携带 `id/content/blob/meta/score/embedding/sparse_embedding`；id 可内容寻址；`ChatMessage` 携带多模态和 ToolCall | 文档支持库/公共契约 | schema 版本、稳定 id、片段范围、来源、权限标签、脱敏、二进制句柄生命周期 | provider hit/ORM/SDK 对象不能直接成为答案引用 |
| 存储 | `DocumentStore` Protocol 规定 `count/filter/write/delete` 和 `to_dict/from_dict`；`DuplicatePolicy` 有 NONE/SKIP/OVERWRITE/FAIL | 文档存储支持库 + 受管 provider | filter DSL、写入回执、事务级别、读回核对、删除语义、租约与连接释放 | Protocol 不保证事务、原子批量、超时、取消或崩溃回滚 |
| embedding | `TextEmbedder.run(text)` 返回 `embedding`；`DocumentEmbedder.run(documents)` 返回带 embedding 的 Documents；OpenAI/Azure 等是具体组件/provider | Embedding 支持库；query/document 两个能力面 | 模型/维度/距离/归一化、批量上限、版本、token 用量、超时取消、空输入策略 | 维度相同不代表模型语义或索引兼容 |
| 检索 | `TextRetriever.run(query, filters, top_k)` 与 `EmbeddingRetriever.run(query_embedding, filters, top_k)` 返回按相关性排序 Documents；另有 multi-query/filter/auto-merging | 文档检索模块编排 + Retriever provider | query 规范化、权限过滤时机、top_k、score 定义、去重、排序稳定性、引用绑定 | keyword/vector/hybrid 不应形成模块内隐式二次召回链 |
| 生成 | `ChatGenerator.run(messages)` 返回 dict；ChatMessage 是输入，provider 负责模型响应；PromptBuilder 负责模板变量 | 生成支持库/provider + 文档问答模块 | 上下文边界、消息 schema、模型版本、token usage、引用输出、provider request id | 生成成功不等于事实写入或引用正确 |
| 序列化 | Pipeline/组件/DocumentStore 使用 `to_dict/from_dict`；marshaller 负责文本；反序列化有模块 allowlist 和真实模块检查 | 序列化支持库 + 运行核心制品/快照 | schema/version、allowlist、签名、迁移、secret 禁止落盘、图/provider 指纹、原子发布 | `unsafe=True` 只能是审计可见的隔离旁路 |
| 资源 | `warm_up` 建立重型状态，`close`/`close_async` 释放；async scheduler 使用 task、semaphore，sync 组件可转线程 | 运行核心资源协调器 + provider | 租约、连接/线程/进程/临时文件上限、deadline、释放回执、残留检查 | HTTP pool、DB pool、线程池、task 集合和模型上下文不能共用一个池字段 |

### 28.3 摄取链、查询链和生成链的 owner

**摄取链**由文档模块发起但不拥有底层资源：`Converter → Preprocessor → DocumentEmbedder → DocumentWriter → DocumentStore`。Converter 只负责把文件或内容转换为统一文档；切分必须保留 parent/source/span 元数据；embedding 必须写入文档 schema 约定的字段；Writer 的 `documents_written` 只能作为 provider 回执，提交是否完成要由运行核心按事务/幂等键和 `count/filter` 读回确认。

**查询链**是唯一检索入口：`规范化 query → 权限/租户过滤 → TextEmbedder（可选）→ Retriever → 去重/分数归一 → Ranker → context budget`。`DocumentStore` 只提供存取和过滤边界，不能被业务调用方绕过；检索结果必须保存 stable document id、score、store/provider、链路版本和片段范围。多查询和 hybrid 只有在契约显式声明时才允许，合并结果要记录各分支输入、输出和排序规则。

**生成链**接收已经裁剪且带引用绑定的上下文：`PromptBuilder/ChatPromptBuilder → ChatGenerator → AnswerBuilder`。模板变量缺失、上下文超预算、消息转换失败和 provider 返回未声明字段都应在生成前或边界处失败；模型输出只能是候选答案，不得直接写回文档库或升级为事实。无引用、越权引用和引用无法回读时，模块应返回明确的无答案/不完整状态，而非伪造成功。

### 28.4 序列化、快照和资源的交叉约束

1. **可保存对象**只包括能力 id、版本、初始化参数、provider 路由键、schema、图连接、过滤和 prompt 模板。连接对象、数据库 session、HTTP client、线程锁、模型上下文、secret 明文和运行中 task 不进入 Pipeline 配置或快照。
2. **可恢复对象**必须同时记录图指纹、组件/能力版本、provider/索引版本、输入摘要、权限范围、已执行节点、attempt、幂等键和取消/失败状态。缺少任一关键指纹时只能重新装配，不能盲目恢复。
3. **加载顺序**为：读取 → 路径/allowlist/签名校验 → schema 迁移 → 临时隔离装配 → 图连接和类型校验 → 原子发布；任一步失败不得污染当前激活制品。
4. **资源顺序**为：provider `warm_up` → 运行核心发放租约 → 执行 → 正常/失败/取消统一进入 `finally` → cancel/drain → close → 连接、task、线程、进程、临时目录和事务状态读回。`close` 成功不能替代外部事务提交证据。
5. **并发边界**必须分别限制 embedding 批量、检索分支、生成请求、连接池、线程/进程和内存队列；Haystack 的 `tool_concurrency_limit` 或 `concurrency_limit` 只能作为局部参考，不能替代平台总预算。

### 28.5 失败与取消矩阵（检索底座版）

| 阶段 | 失败/取消事实 | 平台处置 | 禁止的假设 |
|---|---|---|---|
| 组件装配 | socket 缺失、类型不兼容、未知输出键在装配/运行边界失败 | 不启动 provider；记录能力、字段路径和图指纹 | 不能把组件存在或 import 成功当作能力可用 |
| Converter/切分 | 文件损坏、编码失败、分片超限、元数据非法 | 按文档粒度记录失败；不得把部分文档静默当完整批次 | 不把 `documents_written` 当整条摄取成功 |
| embedding | 凭据、维度、限流、模型错误或请求超时 | provider 转换稳定错误；只有无副作用且契约允许才重试；写入幂等键 | 同输入自动等于 provider 幂等；重试不一定安全 |
| DocumentStore | 重复写、部分写、删除缺失、连接断开 | 依 `DuplicatePolicy` 处理；以事务/回执/count/filter 对账；失败保留批次证据 | Protocol 不提供跨批次原子性和回滚 |
| Retriever/Ranker | provider 不可用、过滤越权、结果为空、排序失败 | 权限过滤失败必须拒绝；空结果是明确无命中；保留召回/重排计数 | 空答案不等于检索成功；不能偷偷切换未审计 provider |
| Generator | prompt 变量缺失、上下文超限、模型拒绝、流中断 | 返回稳定错误和 usage/request id；不得写入事实；流中断关闭队列和 provider 句柄 | `ChatGenerator` 返回 dict 不保证字段、引用或业务成功 |
| Pipeline sibling | async 分支任一失败时取消并 drain 其余 task；sync-to-thread 不能强杀 | 保留原始错误；取消未完成分支；对线程/外部副作用做读回或补偿 | await 已取消不等于 HTTP/DB/文件副作用停止 |
| 主动取消/stream abandon | native async task 可 cancel；stream handle `aclose` 有限等待；同步线程继续运行风险存在 | 传播取消原因和 deadline，排空 task，归还租约；不可取消副作用进入未完成/待核状态 | 清理等待上限不是远端请求 timeout，也不是事务回滚 |
| 崩溃/SIGKILL | 未进入 finally/snapshot 的执行没有核心级恢复保证 | 持久化意图、幂等键、request id 和最后状态；重启后查询事实、补偿或人工介入 | 不能自动重放整条链，不能用日志推断已提交或已回滚 |

### 28.6 后续最终裁决

- **组件与管线**：吸收生命周期、socket 校验、显式图、确定性合并和 snapshot 思路；落点是现有能力契约/运行核心，不新建平级注册表或第二套任务系统。
- **文档与存储**：吸收统一 Document、内容寻址、过滤 DSL 和 DuplicatePolicy 的接口思想；存储事务、索引一致性、权限和崩溃恢复必须由受管 provider 与运行核心补足。
- **embedding、检索、生成**：建立文档摄取与问答候选模块，但三者都必须经唯一能力调用器；模型、向量库、全文库和 HTTP SDK 不进入领域模块。
- **序列化**：吸收 allowlist、真实模块检查、版本化迁移和原子发布；不吸收默认 `unsafe`，不保存运行资源和密钥。
- **资源、失败与取消**：吸收 cancel+drain、流式 sentinel、局部并发上限和快照证据；补齐 wall-clock deadline、provider 取消、租约回收、事务读回和崩溃恢复。
- **晋级条件**：本后续映射仍是 L0/L1 候选输入。只有完成需求/能力登记、schema 与 owner 冻结、摄取→写入→检索→生成真实链、provider 超时/取消/部分写/重启演练及资源残留核对，才可进入 L2/L3；没有这些证据不得宣称“检索底座已完成”。
