# Instructor 架构归档

> 本文件是本地源码参考库中 `instructor` 项目的唯一架构归档文件。
> 说明使用中文；源码路径、类名、函数名、枚举值、参数名、命令和第三方名称保留原文。
> 只读研究基线：`main` / `6754a32b1e35d57dfd94aea8099be68478f1e133`。

## 1. 项目定位

`Instructor` 是一个 Python 结构化输出中间件：用户用 Pydantic `BaseModel` 声明响应契约，库把提供者 SDK 的原始生成接口包装成带 `response_model` 的同步或异步调用，并负责请求格式化、响应解析、Pydantic 校验、有限重试、流式增量解析和观测钩子。

项目的核心边界是“schema-first 的结构化提取”，不是完整 Agent 运行时。README 明确将简单结构化提取与 PydanticAI 的 Agent 场景区分开。SDK、网络访问、密钥、模型推理和提供者配额仍由用户或对应提供者负责；Instructor 不持有统一数据库，也不启动模型服务。

## 2. 真实执行流程

```text
用户定义 Pydantic BaseModel / TypedDict / list[T] / Partial[T]
  │
  ├─ instructor.from_provider("provider/model", async_client=...)
  │    └─ instructor.v2.auto_client.from_provider
  │         ├─ 解析 provider/model
  │         ├─ 依据 ALIAS_TO_PROVIDER / _PROVIDER_BUILDERS 路由
  │         ├─ 懒导入对应 SDK，读取 api_key、base_url、环境变量
  │         └─ 调用 from_openai / from_anthropic / ... 工厂
  │
  └─ Instructor / AsyncInstructor.chat.completions.create
       │  create(response_model, messages, max_retries, strict, hooks, ...)
       ▼
  v2.core.patch.patch_v2 产生 new_create_sync / new_create_async
       │
       ├─ _validate_token_budget
       ├─ mode_registry.get_handlers(provider, mode)
       ├─ prepare_response_model：把输入模型归一为运行期模型
       ├─ handlers.request_handler：tools / response_format / 提示所需参数
       ├─ message_converter：可选的多模态消息转换与图像自动识别
       ├─ handle_templating：context 驱动的 Jinja2 模板处理
       ├─ cache 命中则 load_cached_response 并提前返回
       └─ retry_sync_v2 / retry_async_v2
            │
            ├─ hooks.emit_completion_arguments
            ├─ 真实调用提供者 SDK create 函数
            ├─ 累计 provider usage 并发出 completion:response / completion:usage
            ├─ handlers.response_parser
            │    ├─ tool call / JSON / Markdown JSON / provider 特殊格式
            │    ├─ 流式时进入 Partial / Iterable / parallel 解析
            │    └─ Pydantic model_validate_json / model_validate
            ├─ 成功：_finalize_parsed_response，附 _raw_response / _total_usage
            └─ ValidationError / JSONDecodeError / ResponseParsingError
                 ├─ 记录 FailedAttempt
                 ├─ handlers.reask_handler 将错误回写消息
                 ├─ token_budget 超限则抛 TokenBudgetError
                 └─ tenacity 再次调用，耗尽则 InstructorRetryException
```

无 `response_model` 时，`retry_sync_v2` / `retry_async_v2` 直接调用底层函数并返回原始响应；这使该包装器也能作为低侵入的 SDK 兼容层使用。

## 3. 分层与目录地图

### 3.1 公共入口与兼容层

| 路径 | 真实职责 |
|---|---|
| `instructor/__init__.py` | `__version__ = "1.16.0"`、`__all__`、`_LAZY_IMPORTS`、`__getattr__` 懒加载；依 SDK 是否可导入动态追加 provider factory 导出 |
| `instructor/v2/` | 当前权威运行时组织；公共入口仍保留 v1 兼容导入表 |
| `instructor/auto_client.py` | 兼容路径导出 `from_provider` |
| `instructor/mode.py`、`instructor/utils/providers.py` | 兼容路径导出 `Mode` / `Provider` 与旧 API 语义 |
| `instructor/hooks.py`、`instructor/exceptions.py` 等 | v1 兼容表面或转发层；新代码应优先定位 `instructor.v2.core` |

### 3.2 v2 核心

| 路径 | 关键符号 | 职责 |
|---|---|---|
| `instructor/v2/auto_client.py` | `from_provider`, `_PROVIDER_BUILDERS` | 解析 `provider/model`，构造原生 SDK client，进入 provider 工厂 |
| `instructor/v2/core/client.py` | `Instructor`, `AsyncInstructor`, `Response`, `AsyncResponse` | 同步/异步门面；`chat`、`completions`、`messages` 属性回指自身；提供 `create`、`create_partial`、`create_iterable`、`create_with_completion` |
| `instructor/v2/core/patch.py` | `patch_v2`, `patch`, `new_create_sync`, `new_create_async` | 将任意 provider create 函数包装成结构化输出调用；组织准备、模板、缓存和重试 |
| `instructor/v2/core/registry.py` | `ModeRegistry`, `ModeHandlers`, `mode_registry` | `(Provider, Mode)` 到 request/reask/response/stream/message/template handlers 的注册表；默认 handler 懒加载且用锁保护首次解析 |
| `instructor/v2/core/provider_specs.py` | `ProviderSpec`, `PROVIDER_SPECS`, `ALIAS_TO_PROVIDER`, `HANDLER_SPECS` | provider、别名、SDK、factory、支持/不支持模式、旧模式映射的单一事实源 |
| `instructor/v2/core/mode.py` | `Mode`, `DEPRECATED_TO_CORE` | 工具、JSON、并行、Responses API 及 provider 兼容模式；旧 provider 模式归一到核心模式 |
| `instructor/v2/core/providers.py` | `Provider`, `get_provider`, `provider_from_mode` | provider 标识、URL 检测与 provider-specific mode 的兼容推断 |
| `instructor/v2/core/response_model.py` | `prepare_response_model` | `TypedDict`、`list[T]`、`Iterable[T]`、简单类型、Pydantic 模型归一化 |
| `instructor/v2/core/function_calls.py` | `ResponseSchema`, `response_schema`, `openai_schema` | 动态契约包装、provider schema 属性、响应解析入口 |
| `instructor/v2/core/retry.py` | `retry_sync_v2`, `retry_async_v2`, `_validate_token_budget` | tenacity 驱动的调用→解析→reask 重试循环、usage 累计、预算和失败证据 |
| `instructor/v2/core/hooks.py` | `Hooks`, `HookName` | 六类调用生命周期事件的注册、合并、发射；hook 自身异常转 warning，不打断主调用 |
| `instructor/v2/core/errors.py` | `InstructorError`, `FailedAttempt`, `InstructorRetryException`, `TokenBudgetError` | 统一异常树；保存最后响应、创建参数、usage、失败尝试和可读诊断 |
| `instructor/v2/core/templating.py` / `messages.py` | `handle_templating`, `isolate_retry_kwargs` | provider 消息模板渲染与重试消息副本隔离 |
| `instructor/v2/core/multimodal.py` | `Image`, `Audio` | 多模态输入的公共类型边界 |

### 3.3 提供者与模式处理器

`instructor/v2/providers/` 按 provider 组织 `client.py`、`handlers.py` 以及 schema、templating、usage、multimodal 等辅助模块。当前 `PROVIDER_SPECS` 记录的 provider 包括 `OPENAI`、`ANYSCALE`、`TOGETHER`、`DATABRICKS`、`DEEPSEEK`、`OPENROUTER`、`ANTHROPIC`、`GENAI`、`GENERATIVE_AI`、`GEMINI`、`COHERE`、`PERPLEXITY`、`XAI`、`GROQ`、`MISTRAL`、`FIREWORKS`、`CEREBRAS`、`WRITER`、`BEDROCK`、`VERTEXAI`、`AZURE_OPENAI`、`OLLAMA`、`LITELLM`。

典型 provider 入口为 `instructor.v2.providers.openai.client.from_openai`、`instructor.v2.providers.anthropic.client.from_anthropic` 等。OpenAI 兼容族复用 `instructor.v2.providers.openai.handlers`，但由 `ProviderSpec` 保留各自的 provider、SDK、密钥环境变量和模式边界。缺少可选 SDK 时由入口抛 `ConfigurationError`，不是静默伪造成功。

handler 的最小职责是：

- `request_handler`：把 `response_model` 变成 provider 可接受的 `tools`、`tool_choice`、`response_format` 或提示文本；
- `response_parser`：从 provider 原始响应、tool call、JSON、Markdown code block 或流式块取出结构化数据并校验；
- `reask_handler`：把校验/解析错误和原始回答组织成下一次请求的消息；
- 可选 `stream_extractor` / `stream_extractor_async`：提取流式 JSON 增量；
- 可选 `message_converter` / `template_handler`：多模态消息和 provider 模板适配。

### 3.4 DSL、校验和扩展面

| 路径 | 能力 |
|---|---|
| `instructor/v2/dsl/partial.py`、`json_tracker.py` | `Partial[T]` 增量 JSON 与部分模型；完整 JSON 才最终严格校验，不完整片段使用构造路径 |
| `instructor/v2/dsl/iterable.py` | `Iterable[T]`、对象边界识别和多对象流式 yield |
| `instructor/v2/dsl/parallel.py` | `Iterable[Union[A, B]]` 等多 tool call 并行解析 |
| `instructor/v2/dsl/maybe.py` | `Maybe[T]` 的结果/错误/消息封装与布尔判定 |
| `instructor/v2/dsl/simple_type.py` | `str`、`int`、`bool` 等简单 response model 的 `ModelAdapter` |
| `instructor/v2/dsl/response_list.py` | 列表响应统一成 `ListResponse` 并挂原始响应、usage |
| `instructor/v2/dsl/citation.py` | 引文结构与校验辅助 |
| `instructor/v2/validation/` | `llm_validator`、`openai_moderation`、异步 validator；代码校验最终仍通过 Pydantic |
| `instructor/cache/` | `BaseCache`、线程安全 `AutoCache` LRU、可选 `DiskCache`、`make_cache_key` 及序列化读写 |
| `instructor/batch/`、`instructor/distil.py` | OpenAI Batch、蒸馏/微调相关扩展，不属于普通单次 create 主链 |

## 4. 核心数据模型与持久化边界

### 4.1 契约与响应模型

1. 用户的源契约通常是 Pydantic `BaseModel`；也支持 `TypedDict`、简单类型、`list[T]`、`Iterable[T]` 和 DSL 类型。
2. `prepare_response_model` 将 `TypedDict` 动态建成 `create_model` 结果，将可迭代输入建成 `IterableModel`，将简单类型包装成 `ModelAdapter`。
3. 普通 Pydantic 类通过 `response_schema()` 动态继承 `ResponseSchema`。`ResponseSchema.openai_schema`、`anthropic_schema`、`gemini_schema` 是 provider schema 计算入口。
4. 校验调用 `model_validate_json` / `model_validate`，传入 `context` 和 `strict`；底层字段 validator、`AfterValidator`、`BeforeValidator` 仍由 Pydantic 执行。
5. 成功模型可附加 `_raw_response` 和 `_total_usage`；`create_with_completion` 额外返回 `(model, raw_response)`。
6. 流式结果由 `PartialBase`、`IterableBase`、`ListResponse` 等运行期对象承载；不把半成品误报为最终完整模型。

### 4.2 失败证据与资源预算

`FailedAttempt` 是不可变 `NamedTuple`，保存 `attempt_number`、触发异常和该次 completion。耗尽重试时 `InstructorRetryException` 保存 `last_completion`、`messages`、`n_attempts`、`total_usage`、`create_kwargs`、`failed_attempts`。`TokenBudgetExceeded` 和 `TokenUsageUnavailableError` 将预算耗尽或 usage 不可计量区分开。

`token_budget` 必须是正整数、必须有 `response_model` 且不能与 `stream` 同时使用；每次解析失败后累计 provider usage，在再次请求前判断是否已达到预算。`IncompleteOutputException`（OpenAI `finish_reason == "length"` 或 Anthropic `stop_reason == "max_tokens"`）不属于可重试解析错误。

### 4.3 缓存持久化

核心请求链本身无数据库写入。缓存是可选的外部边界：

- `AutoCache`：进程内 `OrderedDict` LRU，`threading.Lock` 保护，超 `maxsize` 淘汰最旧项；`ttl` 对该实现忽略。
- `DiskCache`：懒导入可选 `diskcache.Cache`，目录默认为 `.instructor_cache`，支持秒级 `ttl`。
- `make_cache_key` 对 `model`、消息、模式和完整 `response_model.model_json_schema()` 做稳定 JSON 编码后 SHA-256；模型字段或描述变化会使缓存失效。
- `store_cached_response` 保存模型 JSON 和可选 raw JSON；`load_cached_response` 重建模型并尽力还原 provider raw response。缓存损坏/非标准 raw 对象会降级为字符串或普通数据，不改变核心调用成功语义。

除此之外，Batch、文件和 usage CLI 通过 OpenAI 服务端 API 读写远端资源；这不是 Instructor 自己的持久化层。

## 5. API、CLI、SDK 与协议边界

### Python API

- 推荐入口：`instructor.from_provider("provider/model")`；也保留 `from_openai`、`from_anthropic` 等 provider factory。
- 门面 API：`client.chat.completions.create(...)`、`client.create(...)`、`create_iterable(...)`、`create_partial(...)`、`create_with_completion(...)`；异步版本对应 `AsyncInstructor` 和异步生成器。
- 手工改造：`instructor.patch(client=...)` 或 `patch(create=...)`；`apatch` 是带弃用警告的兼容别名。
- 观测 API：`client.on(HookName..., handler)`、`off`、`clear`；每次调用可通过 `hooks=` 合并局部 hooks。
- 多模态 API：`Image`、`Audio` 和 provider 的 `message_converter`；`autodetect_images` 由调用参数控制。

### Provider SDK 边界

`from_provider` 仅负责解析模型字符串、构造 SDK 客户端并选择 Instructor 工厂；真正的网络请求仍由 `openai`、`anthropic`、`google.genai`、`cohere`、`mistralai`、`boto3`、`xai_sdk`、OpenAI-compatible SDK 或 LiteLLM 等执行。可选 SDK 通过懒导入和 `importlib.util.find_spec` 控制公开入口，不在 import `instructor` 时强制安装全部 provider。

### CLI 边界

`pyproject.toml` 声明：`instructor = "instructor.cli.cli:app"`。`instructor/cli/cli.py` 用 Typer 注册：

- `instructor jobs`：监控和创建 fine-tuning jobs；
- `instructor files`：管理 OpenAI 文件；
- `instructor usage`：查询 OpenAI API usage；
- `instructor batch`：管理 OpenAI Batch jobs；
- `instructor hub`：已弃用入口；
- `instructor docs [query]`：用 `typer.launch` 打开 `https://python.useinstructor.com/`，可附查询参数。

CLI 没有本地服务端口、数据库协议或独立 RPC；它直接调用对应 API/打开文档网站。

## 6. 依赖与运行环境

### 运行时依赖

`pyproject.toml` 的核心依赖是：`openai>=2.0.0,<3.0.0`、`pydantic>=2.8,<3`、`docstring-parser`、`typer`、`rich`、`aiohttp`、`tenacity`、`pydantic-core`、`jiter`、`jinja2`、`requests`、`regex`；Python 要求 `>=3.9,<4.0`。`eval-type-backport` 仅在 Python `<3.10` 条件安装。

provider 和扩展通过 optional dependency 分组提供，包括 `anthropic`、`groq`、`cohere`、`vertexai`、`cerebras_cloud_sdk`、`fireworks-ai`、`writer`、`bedrock`、`mistral`、`google-genai`、`litellm`、`xai`、`diskcache`、`datasets`、`pydub` 等。`dev` 组包括 `pytest`、`pytest-asyncio`、`pytest-xdist`、`coverage`、`ruff`、`ty`、`pre-commit` 等。

### 构建与质量工具

构建后端是 `hatchling`；项目配置位于 `pyproject.toml`，格式/静态检查使用 Ruff，类型检查使用 `ty`，文档使用 MkDocs Material、`mkdocstrings` 等。仓库内 `AGENT.md` / `CLAUDE.md` 给出的命令是参考命令，不代表本次研究已执行安装或构建。

## 7. 测试与验证结构

### 测试地图

- `tests/v2/test_client_unified.py`：统一 client factory、模式、SDK 和错误测试；
- `tests/v2/test_handler_registration_unified.py`：handler 注册、方法和 provider-mode 映射；
- `tests/v2/test_handlers_parametrized.py`：跨 provider 的 request/parse/reask 参数化；
- `tests/v2/test_mode_normalization.py`：弃用模式与核心模式归一化；
- `tests/v2/test_registry.py`、`test_routing.py`：注册表与 `from_provider` 路由；
- `tests/v2/test_retry_runtime.py`、`test_retry_budget.py`：同步/异步重试、token budget 与失败边界；
- `tests/v2/test_openai_streaming.py`、`test_iterable_streaming.py`、`test_partial` 相关测试：流式、Partial、Iterable；
- `tests/v2/test_*_client.py`、`test_*_handlers.py`：provider 特有客户端、响应格式、消息转换和边界；
- `tests/typing/`：公开 surface 和安装包类型检查；
- `tests/llm/`：需要 provider 凭证或真实模型调用的集成/eval 测试。

仓库现场统计（`git ls-files`，不是旧细探中的估算）：`instructor/**/*.py` 186 个、`tests/**/*.py` 194 个、`docs/**/*.md` 243 个。`tests/v2/README.md` 说明统一测试与 provider 专测分工，并给出 `uv run pytest tests/v2/` 命令。

### 本次验证状态

本次任务只做源码和文档归档，遵守“不安装依赖、不启动服务、不构建、不提交 Git”。因此：

- 已核对 `README.md`、`pyproject.toml`、`AGENT.md`、`CLAUDE.md`、`docs/architecture.md`、`tests/v2/README.md`，并人工吸收此前 `细探-instructor.md` 的有效结论；
- 已读取 v2 入口、client、patch、registry、provider specs、response model、retry、schema、hooks、errors、cache、DSL 和 CLI 关键实现；
- 未执行 `uv pip install`、`uv run pytest`、`ruff`、`ty`、MkDocs 构建或真实 LLM API 调用；因此不能把测试存在写成测试已通过；
- 本归档文件本身只包含 Markdown，不要求运行时导入验证；收口时应至少执行目标根目录下的 `git diff --check` 或等价 Markdown 结构检查。

## 8. 未确认项、风险与后续复核点

1. 当前本地仓库是浅历史（`git log` 仅见 grafted 的合并提交）；代码和远程 `origin/main` 的指针一致，但无法仅凭浅历史还原完整演进过程。
2. `HEAD` 的提交信息是 `1.16.0` release candidate 合并，`pyproject.toml` 与 `instructor/__init__.py` 都声明 `1.16.0`；PyPI 实际发布状态和未来远程提交未在本次任务中验证。
3. `provider_specs.py` 是模式能力声明的权威表，但具体 provider SDK 版本兼容性、API 服务端真实行为和每个模型的能力仍需真实凭证/集成测试确认。
4. `AGENT.md` 的“测试不使用 mock、测试真实 API”是仓库协作规范；同时 v2 单元/统一测试大量构造确定性 provider 响应。阅读时应按测试文件实际目标区分纯 handler 单测、确定性伪响应和真实 LLM 集成。
5. 异步 cache 路径当前直接调用同步 `BaseCache.get/set`；高并发异步场景的阻塞程度和外部 cache backend 的线程安全由使用者负责。
6. `DiskCache`、Redis/其他扩展、Batch、distil、multimodal provider 转换依赖可选包；本次没有安装或运行这些可选路径。
7. `Mode` 仍保留大量 provider-specific 旧枚举和弃用映射；新接入优先使用 `TOOLS`、`JSON`、`JSON_SCHEMA`、`MD_JSON`、`PARALLEL_TOOLS` 等核心模式，但 v3 移除时机需以后续 CHANGELOG/源码为准。
8. 前置检查阶段读取的 `细探-instructor.md` 结论已与当前源码核对并吸收；旧细探已完成单一文档收口，后续只维护本文件，不把它作为第二事实源。

## 9. 证据路径与版本基线

- 项目根：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/75_llm工具链/instructor`
- 远程：`https://github.com/jxnl/instructor.git`
- 当前分支：`main`
- 本地/`origin/main`：`6754a32b1e35d57dfd94aea8099be68478f1e133`
- 提交时间：`2026-08-09T10:55:47-04:00`
- 包版本：`pyproject.toml` 与 `instructor/__init__.py` 均为 `1.16.0`
- 主要源码证据：`instructor/__init__.py`、`instructor/v2/auto_client.py`、`instructor/v2/core/{client.py,patch.py,retry.py,registry.py,provider_specs.py,mode.py,providers.py,response_model.py,function_calls.py,hooks.py,errors.py}`、`instructor/v2/dsl/`、`instructor/v2/providers/`
- 公共设计线索：`README.md`、`docs/architecture.md`、`docs/concepts/`、`NEW_PROVIDER_AGENT_INSTRUCTIONS.md`
- 测试证据：`tests/v2/README.md`、`tests/v2/`、`tests/llm/`、`tests/typing/`
- 此前研究原始材料（已人工吸收并清理）
- 本次限制：未安装依赖、未启动服务、未构建、未提交 Git；因此本文件的“已确认”指源码静态证据，不等同于运行时全量通过。

## 10. 第三轮：结构化输出能力的底座映射

本节是基于当前源码的第三轮裁决输入，不是 Instructor 已经存在的“模型支持库/模块库/运行核心/网关”实现。Instructor 本身覆盖了**模型支持适配**和一部分**结构化输出运行时**，没有实现统一业务模块、租户网关、任务持久化或平台级资源账本。以下映射把源码事实和平台装配建议分开，避免把建议误写成项目现状。

### 10.1 唯一结构化输出链路

源码中可收敛为一条权威链路：

```text
L4 网关/调用方
  → L3 模块库：声明领域 response_model、context、strict、预算和结果语义
  → L2 运行核心：创建 run、超时/取消/重试策略、预算、事件、资源账本
  → L1 模型支持库：Provider/Mode 路由、请求 schema、消息转换、流式提取、响应解析
  → L0 provider SDK/HTTP/模型服务
  → L1 统一抽取与 Pydantic model_validate(_json)
  → L2 重试/reask、usage、错误和资源收口
  → L3 领域结果
  → L4 统一响应/错误信封
```

在 Instructor 内部，这条链的真实落点是：`v2/auto_client.py:60-163` 解析 `provider/model` 并进入 `_PROVIDER_BUILDERS`；`v2/providers/openai/client.py:32-98` 校验 client、选择 mode 并用 `patch_v2` 包装 SDK 的 `create`；`v2/core/patch.py:185-303` 依次准备模型、请求、消息、模板、缓存，再调用 `retry_sync_v2`；`v2/core/retry.py:291-409` 完成 provider 调用、usage 累计、registry parser、失败记录、reask 和下一次尝试。异步链路对应 `patch.py:308-428` 与 `retry.py:514-702`。

唯一链路规则：

1. 一个结构化输出能力只能有一个规范能力 id、一个契约 owner 和一个注册/调用路径；历史 `parse_*` 辅助方法只能归一到 `ResponseSchema.from_response`/registry，不能另建解析链。`tests/v2/test_response_schema_compat.py:57-131` 证明这些旧入口已经通过 `_parse_with_registry` 委托并发出弃用警告。
2. 一个 provider 的差异只能落在 L1 handler/factory/schema/usage/stream extractor；L3 不得直接 import `openai`、`anthropic` 等 SDK，L4 不得自行拼 `tools`、`response_format` 或错误码。
3. 一个模块只能调用 L2 的结构化执行入口；不得绕过 L2 直接调用 provider client，也不得在模块内复制 retry/reask/usage 逻辑。
4. 一个响应只能由 L2 统一封装成功、部分、失败和 usage；L1 返回 provider 原始对象只作为内部中间值，不能穿透 L3/L4 契约。

### 10.2 结构化输出、schema、client、重试和流式的归属

| 能力 | 当前源码事实 | 平台建议 owner | 明确越界 |
|---|---|---|---|
| 用户结构化契约 | `response_model` 可为 `BaseModel`、`TypedDict`、简单类型、`list[T]`、`Iterable[T]`；`prepare_response_model` 在 `v2/core/response_model.py:38-113` 统一成运行期模型 | L3 模块库声明领域模型；L1 只做 provider schema 投影 | L1 不定义业务字段含义，L4 不接收未声明的任意 schema |
| Pydantic 校验 | `ResponseSchema` 继承 `BaseModel`；`model_validate_json`/`model_validate` 传递 `context`、`strict`；`ResponseSchema` 的 provider schema 属性在 `v2/core/function_calls.py:119-187` 委托 provider schema generator | L2 持有统一校验时机和结果 envelope；L1 持有 provider JSON Schema 方言转换；L3 持有领域 validator | 不为每个 provider 复制一份领域模型；不把 provider schema 当领域契约 |
| 请求结构化格式 | `ModeHandlers.request_handler` 通过 registry 返回 `tools`、`tool_choice`、`response_format` 或提示参数；OpenAI tools 证据在 `providers/openai/handlers.py:663-712`，OpenRouter JSON schema 在 `:359-373` | L1 模型支持库 | L2/L3 不拼 provider 参数；L4 不理解 mode 细节 |
| LLM client/factory | `from_provider` 解析字符串、懒导入 SDK、取 key/base_url/timeout/http_client，并构造同步或异步原生 client；`from_openai` 再做类型和 mode 检查 | L1 提供 provider adapter；L2 持有 client 依赖注入和 run 级调用 | 网关不创建散落的 SDK client；模块不保存 provider client |
| 通用 client 门面 | `Instructor`/`AsyncInstructor` 在 `v2/core/client.py:385-566` 合并 client/per-call hooks，并暴露 `create`；`create_partial`/`create_iterable` 在 `:592-673` 将 `stream=True` 与 DSL 类型组合 | L2 运行核心的结构化执行门面；可由 L1 adapter 注入 provider callable | 不让每个模块各封装一个 `Instructor` client；不把门面当网关协议 |
| provider 重试/重问 | `retry_sync_v2`/`retry_async_v2` 用 tenacity；可重试的是 `ValidationError`、`JSONDecodeError`、`AsyncValidationError`、`ResponseParsingError`；`reask_handler` 在 `retry.py:335-409` 改写下一次请求 | L1 只提供 provider-specific `reask_handler`；L2 统一 attempt、重试上限、超时、取消、token budget 和审计 | L3 不复制 tenacity；网络错误不能被无条件当作校验错误重试 |
| usage/预算 | `retry.py:326-353` 累计 provider usage；`_validate_token_budget` 禁止无模型或 streaming 使用预算，`_budget_error` 在不可计量时 fail closed（`103-189`） | L2 统一预算、成本和停止条件；L1 只实现 provider usage 归一化 | L4 不根据 provider 原始 usage 自己计费；无 usage 不能声称已执行预算保护 |
| 流式 | L1 handler 提取 provider chunks（OpenAI 证据 `providers/openai/handlers.py:430-526`）；L1 DSL 解析器通过 `PartialBase`/`IterableBase` 增量产出，完整 JSON 才最终原模型校验（`dsl/partial.py:436-513`） | L1 处理方言和 chunk；L2 管理流的生命周期、取消、背压、完成/截断状态；L3 选择 Partial/Iterable 语义 | 不把 partial 对象当最终完整结果；L4 不直接消费 provider-specific chunk |
| 错误边界 | `InstructorError` 为根；`IncompleteOutputException`、`ResponseParsingError`、`InstructorRetryException`、`TokenBudgetError` 等保留失败尝试、最后响应、usage 和 create kwargs | L1 把 SDK 异常映射到可识别 provider error；L2 形成平台错误码、attempt 和清理结果；L4 只展示稳定信封 | 模块不吞异常、不把 retry exhaustion 伪装成成功；网关不泄露 key、完整 prompt 或 raw response |

因此，**Instructor 的 Pydantic/schema/handler/stream extractor 是 L1 候选；`patch`、`client`、`retry`、hooks 和错误上下文是 L2 候选；领域 `BaseModel`/validator 是 L3 候选；CLI 不是网关，`batch`/`distil`/cache 也不能自动升级为平台运行核心**。这也是第三轮的“复用/升级/隔离”裁决：复用 schema 和 handler 契约，升级 client 生命周期、取消和错误信封，隔离 CLI/Batch/蒸馏等旁路能力。

### 10.3 L0-L4 装配等级

L0-L4 是平台映射等级，不是 Instructor 源码中的现有枚举或目录层级。依赖方向固定为 `L4 → L3 → L2 → L1 → L0`，结果和证据沿同一调用上下文返回。

| 等级 | owner | 允许内容 | 禁止内容 | 本项目证据/可吸收项 |
|---|---|---|---|---|
| L0 | 外部 provider/SDK/HTTP/模型服务 | 生成、原始响应、原始 usage、网络连接 | 领域契约、平台重试和网关状态 | `auto_client.py` 构造 `openai`/其他 SDK；真实服务行为本轮未实测 |
| L1 | 模型支持库 | Provider/Mode 注册、factory、schema 方言、消息/多模态转换、raw response parser、stream extractor、usage/error adapter | 业务流程、租户、持久化、跨 provider 业务 fallback | `core/registry.py:46-211` 的 `ModeHandlers`/懒加载注册表；`providers/*/handlers.py` |
| L2 | 运行核心 | 一个 run 的输入快照、attempt/reask、超时/取消、预算、并发、usage、事件、资源释放、统一错误和证据 | HTTP 路由、领域字段、provider 方言 | `core/retry.py` 提供可复用的 attempt 骨架，但 client/stream 关闭和平台 run 账本仍需补齐 |
| L3 | 模块库 | 领域 response model、validator、提示/任务编排、结果投影；只调用 L2 | 直接 SDK、自己重试、自己写公共错误码/usage | `response_model.py` 可承接模型归一；领域模型本身由调用方提供，Instructor 不持有业务模块 |
| L4 | 统一网关/应用入口 | 认证授权、租户、限流、幂等键、HTTP/RPC、版本、脱敏后的响应/错误信封 | provider client、schema 方言、retry loop、raw stream 解析 | Instructor 无服务端口和 RPC；CLI `instructor/cli/cli.py` 是外部 API 命令客户端，不可视作 L4 网关 |

L2 的唯一公开原子能力建议命名为 `structured_output.execute`（名称为平台装配建议，不是当前源码 API）：输入 `provider_ref`、领域 `response_model`、messages/input、mode 能力要求、超时/取消 token、retry policy、token budget、幂等/run metadata；输出统一 `StructuredResult` 或稳定错误信封。L1 只实现 `model_provider.invoke` 与 handler 契约，L3 通过 L2 组合领域流程，L4 只暴露版本化 route。

## 11. 资源生命周期与释放责任

### 11.1 事实边界

当前 Instructor 主要接收和消费外部资源，没有形成完整的资源 owner 协议：

| 资源 | 创建/持有事实 | 正常完成 | 业务失败/重试 | 取消/超时/崩溃 | 第三轮裁决 |
|---|---|---|---|---|---|
| 同步/异步 provider client 与 HTTP transport | `auto_client.py:225-250` 等 builder 创建 `OpenAI`/`AsyncOpenAI`；`from_openai` 也接受外部 client | 当前没有 `Instructor.close()`/`aclose()`；依赖调用方/SDK | retry 只重复调用，不重建 client | 当前源码未提供宿主崩溃清理 | L1 必须声明 `created_by_adapter`；注入的 shared client 不得被模块关闭，adapter 自建 client 在 run/应用终态 `close/aclose` |
| provider streaming iterator/async generator | L1 `extract_streaming_json`/`extract_streaming_json_async` 消费 completion；DSL 以 generator/async generator 转发 | 消费到结束即自然结束 | 解析失败可进入 retry，但已消费 stream 不能复用，必须由 L2 重新发起新请求 | `PartialBase`/handler 没有通用 `finally` 关闭底层 completion | L2 在 `finally` 检测并调用 `close`/`aclose`；取消、异常、客户端断开均走同一清理钩子，记录 `stream_closed` |
| retry messages/failed attempts | `patch.py:263-275` 传 `isolate_retry_kwargs`；`FailedAttempt` 在内存保存 completion/exception | run 结束释放局部引用 | retry 过程中不能污染原始 messages；耗尽时异常携带证据 | 进程崩溃时无持久化保证 | L2 限制 attempt 数/原始响应大小并脱敏；需要跨进程审计时显式写证据 owner，不能把异常对象直接落库 |
| Pydantic 动态模型/缓存 | `prepare_response_model` 动态建模；`PartialBase.get_partial_model` 使用 `@cache`；OpenAI handler 使用 `WeakKeyDictionary` 保存 streaming flag | 进程内复用 | model/schema 变更由模型类型/schema key 隔离 | 随进程结束清理；弱引用可回收 | L1/L2 不把动态模型缓存当持久化；如加全局 schema cache，必须有上限/失效/版本键 |
| response cache | `AutoCache` 用 `threading.Lock` 的 `with` 保护 LRU；`DiskCache` 包装 `diskcache.Cache`，但 wrapper 未暴露 close | AutoCache 随进程；DiskCache 由 backend 持有目录 | cache miss/损坏会回到真实调用；写缓存只在成功后发生（`patch.py:280-301`） | 未定义进程崩溃后的半写恢复由 backend 决定 | cache 是可选旁路，不进入 L2 事实链；DiskCache backend 的关闭/目录治理由创建者负责 |
| hooks | `Hooks.emit` 对每个 handler 捕获异常并转 warning（`core/hooks.py:150-174`） | 无需释放外部资源 | hook 失败不能打断主调用 | 崩溃无 hook 保证 | L2 事件必须 best-effort 且不能替代 finally；handler 若持有 span/file 必须由注册方管理 |
| 多模态输入/临时文件 | `message_converter` 只转换消息；核心没有统一文件/临时目录持久化 | 转换后的消息随调用结束 | provider 失败不能把临时文件留给 retry | 崩溃残留未由 Instructor 统一扫描 | L1 只传输/转换；L2 统一临时资源注册表，四种终态都清理并可验收 |

### 11.2 统一释放协议（平台装配要求）

每个 L2 run 必须有一个资源作用域，记录资源 id、创建者、当前持有者、转移时间、释放动作和释放结果。四种终态必须走同一 `finally` 等价路径：

```text
正常完成       → drain stream → finalize model → close/aclose owned resources → commit evidence
业务失败       → record error/attempts → close/aclose owned resources → publish failure
主动取消/超时  → cancel provider task → close/aclose stream/client-owned transport → publish cancelled
宿主/子进程崩溃 → supervisor/reaper 扫描进程、端口、临时文件、锁 → mark orphaned/cleaned → publish recovery evidence
```

所有权规则：创建者默认持有；显式转移后由新 owner 释放；借用的外部 client/transport 不得关闭。对当前源码不能证明的 `close`、`aclose`、取消传播和崩溃回收，一律标记“待核/平台缺口”，不能从 generator 自然结束推断资源已关闭。

## 12. 失败矩阵与错误边界

| 阶段/故障 | 当前源码行为 | 重试 | 统一 owner 与终态 | 证据 |
|---|---|---|---|---|
| `response_model` 非法或 `TypedDict/list` 未参数化 | `prepare_response_model` 抛 `ValueError`；预算配置先在 `retry.py:103-119` 校验 | 否；provider 不应被调用 | L3/L2 入参错误；记录 validation stage、0 provider calls | `core/response_model.py:73-80`；`tests/v2/test_retry_budget.py:316-353` |
| provider 未支持/SDK 缺失 | `from_provider` 抛 `ConfigurationError`；factory 懒导入，不伪造 client | 否 | L1 配置错误；不创建或释放已创建资源 | `v2/auto_client.py:141-163`、`providers/*/client.py`；`test_client_unified.py:234-247` |
| mode 未注册/不兼容 | registry `get_handlers`/factory 抛 `KeyError` 或 `ModeError`；legacy mode 先归一 | 否，除非调用方更换 mode | L1 能力协商错误；L2 结束 run | `core/registry.py:183-211`；`providers/openai/client.py:39-54` |
| 网络/API/鉴权/限流异常 | provider callable 异常在 `retry.py:300-321` 记录 completion error 后向外冒泡，最终包装为 `InstructorRetryException`；非 validation 异常不按 parse retry | 不得把所有 SDK 异常默认为可重试；平台应按 provider error 分类 | L1 映射分类，L2 按 retry policy 决定；释放 stream/owned transport | `tests/v2/test_retry_runtime.py:282-348` |
| JSON 损坏/缺 tool call/响应解析失败 | `JSONDecodeError`、`ResponseParsingError` 进入 failed attempts，调用 `reask_handler` | 是，受 max_retries/timeout/budget 限制 | L1 解析，L2 attempt/reask/证据 | `providers/openai/handlers.py:594-640`；`retry.py:335-409` |
| Pydantic `ValidationError`/自定义 validator 失败 | 记录 `FailedAttempt`，将原响应和异常交给 reask | 是 | L3 定义校验，L2 执行重问；不得吞字段错误 | `providers/openai/handlers.py:766-773`；`tests/v2/test_retry_runtime.py:80-193` |
| 重试耗尽 | 抛 `InstructorRetryException`，携带最后 completion、messages/create kwargs、usage、n_attempts 和 failed attempts | 否 | L2 terminal failure；L4 只投影稳定错误码 | `retry.py:411-451`；`errors.py:188-255`；`test_retry_runtime.py:493-569` |
| token budget 达到或 usage 不可计量 | `TokenBudgetExceeded` 或 `TokenUsageUnavailableError`；在 reask 前 fail closed | 否；精确边界不再 reask | L2 budget owner；释放后发布消耗量/不可计量原因 | `retry.py:148-189`；`tests/v2/test_retry_budget.py:77-143,198-236` |
| `finish_reason=length`/Anthropic `max_tokens` | `IncompleteOutputException` 明确从 retryable parse errors 排除 | 否；需上层调高 max_tokens 或改用 Partial | L1 识别截断，L2 发布 incomplete，stream 资源仍须关闭 | `core/function_calls.py:39-49`；`retry.py:300-303,356-358` |
| 流中途断开/取消/解析失败 | DSL 逐 chunk 产出；完整 JSON 才最终校验；当前没有通用 stream close/finally 契约 | 已消费 stream 不能复用，必须新请求；取消不应盲目 reask | L2 负责 cancel/close/aclose 和 partial/final 状态 | `dsl/partial.py:436-513`；`providers/openai/handlers.py:561-575`；`test_openai_streaming.py:83-100` |
| cache 损坏/非标准 raw | `load_cached_response` 尽力解析，raw 失败降级为字符串/普通数据；cache miss 回到 provider | 不对 cache 本身重试 | cache owner 记录 hit/miss/corrupt；不得覆盖真实错误 | `cache/__init__.py:189-238`；`patch.py:246-261` |
| hook handler 自身异常 | 被捕获并 `warnings.warn`，不打断调用 | 否 | L2 观测旁路；不能阻止资源 finally | `core/hooks.py:150-174` |

失败矩阵的硬性判定是：只有“源码分支存在”不能算“已验证”；`tests/v2` 的确定性测试只能证明局部契约，真实 SDK、凭证、网络、取消、进程崩溃和资源残留仍是弱验证/未验证。任何上层复用计划必须同时记录 `provider_calls`、attempt 数、错误类别、usage 是否完整、stream/client 是否关闭和临时资源扫描结果。

## 13. 第三轮复用、升级、隔离与验收契约

| 裁决 | 内容 | 状态 |
|---|---|---|
| 复用 | Pydantic `BaseModel`/`TypeAdapter` 校验、`ResponseSchema` provider schema facade、`ModeRegistry` handler 契约、`Partial`/`Iterable` 增量语义、`FailedAttempt`/错误树、hooks 事件名 | 吸收：源码与确定性测试证据充分 |
| 升级 | 把 `retry.py` 的 attempt/reask/usage 骨架放入 L2；补 run id、幂等键、取消传播、stream `close/aclose`、client ownership、错误信封、脱敏和资源账本 | 待核：平台源码和运行证据不在本项目内 |
| 新建 | L2 `structured_output.execute` 唯一入口；L4 版本化 gateway route；统一 `StructuredResult`/failure envelope；L0-L4 能力/资源/证据契约 | 待核：仅为装配计划，不代表已实现 |
| 隔离 | `cli/`、`batch/`、`distil.py`、provider-specific legacy parser、缓存 backend 和真实 API eval 不进入普通结构化输出主链；通过 adapter/独立 job 接入 | 吸收边界：当前源码已将 Batch/distil 与普通 create 分开 |
| 废弃 | L4/L3 直连 provider；模块自建 retry/error map；provider raw response 穿透；把 partial 当 final；无 usage 仍宣称 budget enforced | 废弃：违反单链路和可审计资源规则 |

验收契约（后续平台实现必须逐项有证据）：

1. **契约**：同一 `response_model` 在 TOOLS/JSON/JSON_SCHEMA/MD_JSON 只通过一个 L2 入口；provider 差异能由 registry 查询，unsupported mode 在 provider 调用前失败。
2. **重试**：校验/JSON 解析失败只按策略 reask；API/auth/限流按错误分类；max attempts、timeout、token budget 和 usage unavailable 均有明确终态。
3. **流式**：Partial 每个增量标为 partial，结构完整时才 final validate；Iterable 每个对象单独产出；正常、错误、取消、断线均验证底层 iterator/async generator 的关闭。
4. **资源**：同步/异步 client、HTTP transport、stream、锁、缓存 backend、临时文件、子进程分别标 owner；四种终态读回无端口、进程、临时目录、锁和连接残留。外部注入 shared client 不得被误关。
5. **错误/证据**：L4 只收到稳定错误信封；raw prompt、api key、完整 provider response 按脱敏策略处理；保存 run id、attempt、错误类别、usage、释放结果和验证命令。
6. **真假验证**：当前仓库只提供静态源码和确定性测试证据；本轮未安装依赖、未运行 `pytest`、未调用真实 LLM、未验证 provider 网络/取消/崩溃回收。因此第三轮结论中“吸收”仅指契约/静态实现可吸收，不等于平台已通过。
