# Hermes Agent 架构建档

> 本文是基于当前磁盘源码、仓库规则、官方仓库内架构文档和已有细探的首轮架构地图。
> 源码归档基线：`细探-hermes-agent.md` 记录的提交 `a61183b56`；当前文件以磁盘现状为准。
> 本文件已吸收此前 `细探-hermes-agent.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
> 本次只新增或更新本文件，不修改源码、依赖、测试或配置。

## 1. 项目定位

Hermes Agent 是面向个人的多入口 Agent 平台：CLI、经典 TUI、Electron Desktop、消息网关、OpenAI 兼容 API、ACP 编辑器协议、批量轨迹生成和 cron 调度共享同一个 `AIAgent` 运行核心。平台的扩展边界主要是工具注册表、插件、技能、MCP 和可替换的 provider/memory/context-engine，而不是不断扩大核心 Agent 类。

两个架构约束贯穿所有入口：

- **提示词稳定性**：会话内复用稳定的 system-prompt 前缀和工具集合，避免无意中破坏上游 prompt cache；上下文压缩是主要的显式重建边界。
- **核心窄腰、能力在边缘**：工具、平台、provider、memory backend 和 UI 尽量通过 registry/ABC/plugin/MCP 接入。

## 2. 文本总流程图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 入口层                                                                      │
│  hermes CLI / 经典 cli.py                                                   │
│  hermes --tui → ui-tui(React/Ink) ⇄ tui_gateway(JSON-RPC/stdio)             │
│  Electron Desktop / web dashboard → serve/dashboard(JSON-RPC + WebSocket)   │
│  gateway/20+消息平台 · OpenAI API · ACP(stdio/JSON-RPC) · batch · cron       │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ 统一创建/恢复会话、绑定 profile/session ContextVar
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Agent 运行层                                                                │
│ AIAgent(run_agent.py) → agent.agent_init / agent.conversation_loop           │
│   ├─ prompt_builder/system_prompt：stable → context → volatile              │
│   ├─ runtime_provider：provider + model → api_mode/凭证/base_url             │
│   ├─ API transport：chat_completions / codex_responses / anthropic           │
│   ├─ tool-call loop：LLM → 批量工具调用 → 结果归并 → 下一轮/最终回复          │
│   ├─ compression/cache、interrupt、retry/fallback、usage/trajectory          │
│   └─ memory/skills/auxiliary LLM（按配置、会话和插件边界接入）               │
└───────────────────────────────┬───────────────────┬──────────────────────────┘
                                │                   │
                                ▼                   ▼
┌──────────────────────────┐  ┌────────────────────────────────────────────────┐
│ 工具暴露与安全层          │  │ 持久化与后台层                                  │
│ tools/registry.py         │  │ hermes_state.py：SQLite + FTS5                  │
│ model_tools.py            │  │ gateway/session.py：平台会话路由/持久化            │
│ toolsets.py               │  │ cron/jobs.py + scheduler.py：jobs.json 调度       │
│ check_fn/动态 schema      │  │ async delegation、kanban、trajectory              │
│ approval/file_safety      │  │ profile → HERMES_HOME 独立状态                   │
│ terminal environments     │  └────────────────────────────────────────────────┘
└──────────────┬───────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ 能力实现：tools/*.py（导入时自注册） · local/docker/ssh/modal/daytona/…       │
│ 浏览器、文件、Web、代码执行、视觉、消息、MCP、delegate_task、记忆、技能等     │
│ 插件：bundled + project/user + entry point → PluginContext.register(...)     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3. 真实分层与职责

### 3.1 入口与适配层

| 入口 | 主要路径 | 职责 |
|---|---|---|
| Python CLI/库 | `hermes_cli/main.py`、`cli.py`、`run_agent.py` | 参数/子命令、交互输入、直接调用 `AIAgent` |
| 经典 TUI | `cli.py` | `prompt_toolkit` 输入、Rich 展示、slash command、回调 |
| 新 TUI | `ui-tui/`、`tui_gateway/` | Ink/React 负责界面；Python gateway 负责会话、Agent、工具和 JSON-RPC |
| Desktop | `apps/desktop/`、`apps/shared/` | Electron + React + nanostore；通过 headless `hermes serve` 的 JSON-RPC/WebSocket 使用后端 |
| 消息网关 | `gateway/run.py`、`gateway/session.py`、`gateway/platforms/` | 平台事件、授权/配对、session key、消息投递、slash command、后台任务 |
| OpenAI API | `gateway/platforms/api_server.py` | OpenAI Chat Completions/Responses、会话 REST、runs/SSE、审批和停止 |
| ACP | `acp_adapter/` | VS Code/Zed/JetBrains 的 stdio/JSON-RPC agent 接口 |
| 调度/批处理 | `cron/`、`batch_runner.py` | 无人值守 Agent job、轨迹生成和训练数据场景 |

入口层不应各自实现 Agent 循环；它们负责把输入、身份、历史、回调和平台能力转换为统一的 `AIAgent` 调用。

### 3.2 Agent 运行核心层

- `run_agent.py` 暴露 `AIAgent`，构造参数包含 provider/model/api mode、toolsets、session、平台身份、回调、压缩、预算、fallback 和 credential pool 等上下文。
- `AIAgent.run_conversation(...)` 是统一的完整接口，委托到 `agent.conversation_loop.run_conversation`；`chat(...)` 是返回最终文本的轻量接口。
- 对话循环的关键步骤是构造消息和 system prompt、解析运行时 provider、调用模型、执行 tool calls、追加 tool result、处理中断/预算/重试/压缩，最后将响应和消息持久化。
- `agent/` 承载 prompt builder、system prompt、provider/runtime 辅助、压缩和缓存、模型元数据、memory manager、trajectory、redaction、transport adapter 等可拆分内部能力。

### 3.3 工具与安全层

- `tools/registry.py` 是工具 schema、handler、toolset、可用性、结果预算和 dispatch 的单一事实源。工具模块通过顶层 `registry.register()` 自注册；`discover_builtin_tools()` 先用 AST 预筛，再导入模块。
- `model_tools.py` 是兼容旧调用方的薄编排层：触发内置发现和插件发现，按 `toolsets.py` 展开 enabled/disabled 集，调用 registry 生成 OpenAI 格式定义并 dispatch。
- `toolsets.py` 用 `tools + includes` 递归组合基础集、复合集和平台集；`check_fn` 决定外部依赖不可用时是否暴露工具，registry 对检查结果使用约 30 秒 TTL，并对最近成功结果提供短暂失败宽限。
- handler 正常返回字符串；唯一结构化例外是多模态 envelope。dispatch 将未知工具、异常和非法返回类型统一包装为错误结果。
- `tools/approval.py`、`agent/file_safety.py`、`tools/tirith_security.py` 和执行环境共同形成危险命令、敏感路径、内容扫描、审批、环境 scrub、进程组回收和结果预算边界。容器/远程 backend 与本机 backend 的权限路径不同，不能只看工具名判断安全边界。

### 3.4 插件、技能、provider 与 memory 扩展层

- 通用插件由 `hermes_cli/plugins.py` 发现 bundled/project/user/entry-point 来源，经 manifest 和 enabled/disabled/kind 门控后加载；通过 `PluginContext` 注册工具、hooks、CLI、平台、中间件和技能。
- model-provider 插件由 `providers/` 的独立发现器按需加载，通过 `ProviderProfile` 注册；不与通用 PluginManager 重复实例化。
- memory provider 实现 `agent/memory_provider.py` 的 ABC，由 `agent/memory_manager.py` 编排 `sync_turn`、`prefetch`、`shutdown` 等生命周期；context engine/image generation 采用类似的 ABC + orchestrator 结构。
- `skills/` 是默认可用的内置技能，`optional-skills/` 是显式安装的重型/小众技能；技能命令作为普通用户消息注入，避免随意重建长期 system prompt。
- MCP 工具在显式发现/刷新时注册到 registry，动态变化由 registry generation 参与 schema cache 失效。

## 4. 数据模型与状态边界

### 4.1 SessionDB（`hermes_state.py`）

默认路径是 profile 对应的 `get_hermes_home() / state.db`，当前源码常量 `SCHEMA_VERSION = 23`。SQLite 采用 WAL（不兼容网络文件系统时有 DELETE fallback）；macOS 对 WAL checkpoint/synchronous 有额外耐久性处理。

主要表和关系：

- `schema_version`：数据库迁移版本。
- `sessions`：会话 id、source、用户/聊天身份、cwd/git repo、parent lineage、时间、模型配置、结束原因等；`parent_session_id` 支持压缩续接、branch 和子代理区分。
- `messages`：会话消息、role、content、时间、tool name/calls、active/display metadata 等，外键指向 `sessions`。
- `session_model_usage`：按 session/model/provider/base_url/mode/task 记录模型用量。
- `state_meta`：FTS 存储布局、运行状态等元数据。
- `gateway_routing`：按 scope/session key 保存网关路由。
- `compression_locks`：并发压缩租约和过期时间。
- `async_delegations`：后台委派的来源 session、状态、完成时间和投递 claim 信息。
- FTS5 `messages_fts` 与 trigram `messages_fts_trigram`：对非 tool 消息及工具相关字段提供全文/模糊检索；触发器保持索引同步。

这套数据库是**会话状态和检索存储**，不是业务领域事件库。batch/RL trajectory 按源码注释走独立系统；cron job 也不写入 SessionDB 的主会话历史。

### 4.2 Cron 与后台状态

`cron/jobs.py` 以 profile-local 的 `jobs.json` 保存 job 记录，支持 duration、every phrase、五段 cron、ISO 一次性时间等表达式；字段可包含 skills、model/provider、script、context_from、workdir、delivery targets。`cron/scheduler.py` 决定何时触发，`run_one_job()` 复用执行→保存输出→投递→标记的共享 firing body。运行时有锁、catchup/grace window 和中断约束。

委派、kanban、轨迹、浏览器/终端环境、缓存和日志各自拥有对应的状态文件或数据库边界；代码中通过 `get_hermes_home()` 进行 profile 隔离，不能用硬编码 `~/.hermes` 替代。

## 5. 核心数据流与关键路径

### 5.1 CLI / Python SDK 对话

```text
用户输入或 AIAgent.chat(message)
  → AIAgent.run_conversation(...)
  → 设置 conversation/accounting ContextVar
  → prompt_builder/system_prompt 组装 stable/context/volatile
  → runtime_provider 解析 provider/model/api_mode/凭证
  → chat_completions 或 codex_responses 或 anthropic
  → 无 tool call：最终文本
  → 有 tool call：model_tools.get_tool_definitions/handle_function_call
  → registry.check_fn + approval + backend 执行
  → 结果归一化/预算截断/追加 tool message
  → 循环至最终响应或预算/中断/失败
  → SessionDB 持久化消息、usage、lineage；可选保存 trajectory
```

Python SDK 的直接使用面是：

```python
from run_agent import AIAgent

agent = AIAgent(model="<model>", provider="<provider>")
result = agent.run_conversation("<prompt>")  # 完整 dict：final_response + messages 等
text = agent.chat("<prompt>")                 # 只取最终文本
```

上述示例表达源码接口形状；实际 provider、凭证、toolset、`HERMES_HOME` 和可选依赖须由运行配置提供。

### 5.2 消息网关

```text
平台 Adapter.on_message
  → MessageEvent / GatewayRunner._handle_message
  → 授权、配对、平台/用户/线程 session key
  → 读取或创建 SessionDB 会话 + 绑定 session ContextVar
  → 创建 AIAgent.run_conversation
  → callbacks/审批/进度事件
  → gateway delivery 适配器返回 Telegram/Discord/Slack/…
```

### 5.3 TUI 与 Desktop

```text
hermes --tui
  → Node Ink UI
  ⇄ newline-delimited JSON-RPC over stdio
  → tui_gateway/server.py / persistent slash worker
  → AIAgent、tools、SessionDB
  → message.delta / tool.* / approval.* / session.* / gateway.ready events

Electron Desktop 或 web dashboard
  → shared JsonRpcGatewayClient / WebSocket
  → headless `hermes serve` 或 dashboard backend
  → 同一 tui_gateway/API backend 能力
```

Desktop 是独立聊天表面，不是 dashboard 的 React 重写，也不直接嵌入 `hermes --tui`；dashboard 的 `/chat` 则通过 PTY 运行真正的 TUI。

### 5.4 API Server

`gateway/platforms/api_server.py` 默认监听 `127.0.0.1:8642`（可由配置解析），请求受 API key/profile/并发 run 等边界控制。OpenAI 客户端可把 base URL 指向 `http://localhost:8642/v1`。

主要 HTTP 契约：

- `POST /v1/chat/completions`：OpenAI Chat Completions；默认无状态，可用 `X-Hermes-Session-Id` 续接，会话记忆可用 `X-Hermes-Session-Key` 作用域化。
- `POST /v1/responses`、`GET/DELETE /v1/responses/{response_id}`：Responses API，支持 `previous_response_id`。
- `GET /v1/models`、`GET /v1/capabilities`、`GET /v1/skills`、`GET /v1/toolsets`：能力发现。
- `GET/POST /api/sessions`、`GET/PATCH/DELETE /api/sessions/{session_id}`、`GET /messages`、`POST /fork`、`POST /chat[/stream]`：会话管理和持久聊天。
- `POST /v1/runs`、`GET /v1/runs/{run_id}`、`GET /events`、`POST /approval`、`POST /stop`：异步 run、SSE 生命周期、审批和中断。
- `GET /api/jobs` 及 job CRUD/暂停等端点：cron 管理。
- `POST /api/platforms/{platform}/events`：平台回调入口；平台签名校验与 API server key 是不同信任边界。
- `GET /health`、`GET /health/detailed`：健康和运行时诊断。

启用 profile multiplex 时，次级 profile 通过 `/p/<profile>/...` URL 前缀路由。

### 5.5 CLI 命令面

`pyproject.toml` 声明：

- `hermes = hermes_cli.main:main`：安装后的主 CLI；覆盖 chat、`model`、`tools`、`config`、`setup`、`gateway`、`cron`、`doctor`、`sessions`、`skills`、`plugins`、`profile`、`kanban`、`acp`、`serve/dashboard` 等。
- `hermes-agent = run_agent:main`：直接运行 Agent 或列出工具/工具集，支持 query、model、toolsets、trajectory 等参数。
- `hermes-acp = acp_adapter.entry:main`：以 ACP 服务器启动。

slash command 在 `hermes_cli/commands.py` 的 `COMMAND_REGISTRY` 定义，CLI help、gateway help、Telegram menu、Slack mapping 和 autocomplete 从同一注册表派生。

## 6. 技术栈

| 层面 | 已确认技术 |
|---|---|
| 核心语言 | Python 3.11–3.13（`requires-python >=3.11,<3.14`） |
| Python 打包 | `pyproject.toml` + setuptools build backend；命令通过 `[project.scripts]` 暴露 |
| 模型协议 | OpenAI SDK；Chat Completions、Codex Responses、Anthropic Messages 适配；多 provider/profile/credential pool |
| Web/API | `aiohttp` API adapter、FastAPI/Uvicorn dashboard/backend 依赖、WebSocket/JSON-RPC |
| 经典 CLI | Rich、prompt_toolkit |
| 新 TUI | Node.js >=20、TypeScript、React、Ink、Vitest；stdio newline-delimited JSON-RPC |
| Desktop | Electron + React + nanostore，`apps/shared` 提供 JSON-RPC/WS client |
| 持久化 | SQLite、WAL、FTS5/trigram FTS；cron 使用 JSON 文件；日志为 profile-local 文件 |
| 工具执行 | local、Docker、SSH、Singularity、Modal、Daytona 等 terminal backend；PTY；浏览器/CDP/MCP |
| 扩展 | Python plugin/entry point、MemoryProvider/ContextEngine/ProviderProfile ABC、skills/optional-skills、MCP |
| 质量与安全 | pytest/pytest-asyncio/xdist runner、Vitest、ruff/ty、审批、敏感路径防护、环境 scrub、轨迹与日志 |
| 依赖策略 | 核心依赖以精确 pin 为主；provider/平台/重型能力放 optional extras 或 lazy install，`[all]` 刻意排除多数 lazy backend |

## 7. 测试与验证入口

仓库规则要求 Python 测试统一通过 `scripts/run_tests.sh`，不要直接调用 pytest；runner 负责清理凭证环境、临时 `HERMES_HOME`、UTC/C.UTF-8、并行执行和按文件重试。`pyproject.toml` 设置 `testpaths = ["tests"]`，默认排除 `integration` marker。

测试覆盖面按目录分层：

- `tests/agent/`、`tests/run_agent/`：Agent loop、provider/model、消息、压缩、会话语义。
- `tests/tools/`：registry、tool schema/dispatch、terminal、file safety、approval、web/browser、skills、MCP、delegation。
- `tests/gateway/`、`tests/tui_gateway/`：平台路由、session、JSON-RPC、审批/中断、模型和桌面/网关边界。
- `tests/hermes_cli/`、`tests/cron/`、`tests/plugins/`、`tests/providers/`：命令、调度、插件和 provider 契约。
- `ui-tui/src/**/__tests__`、`ui-tui/src/**/*.test.ts`、`web/src/**/*.test.ts`、`apps/desktop/**`：TypeScript/React/TUI/Web/Desktop 行为测试。
- `tests/test_project_metadata.py`：依赖 extras、lazy-deps 与安全 pin 关系的契约测试。

本次架构建档未启动服务、未安装依赖、未运行项目测试或构建；只做了静态读取和文档门禁验证。已有细探中记录的测试数量是历史快照，不作为当前计数断言。

## 8. 未确认项与风险

1. **代码地图**：本轮严格未使用 MCP。目标目录已有 `.codegraph/`，已执行 `codegraph status` 与 `codegraph sync`，统计为 7,343 files、160,462 nodes、504,283 edges；CodeGraph 仅用于定位，最终判断以当前源码/Git 为准。
2. **上下文边界**：不引用其他项目的 MCP 上下文、可信度或验证记录；本轮直接在 hermes-agent checkout 取证。
3. **提交漂移**：已有细探基于 `a61183b56`，README/AGENTS/website architecture 的规模数字和当前文件可能继续变化；需要后续以目标仓库当前 Git commit 重新审计。
4. **入口规模与职责仍有大文件耦合**：`run_agent.py`、`cli.py`、`gateway/run.py`、`api_server.py` 等仍是大型协调器；本文记录边界，不等于已完成模块化。
5. **API 完整字段契约未逐端点展开**：本文列出真实路由和主要语义，未逐一核对每个请求/响应 JSON schema、认证失败码、SSE event payload 和 profile multiplex 的所有边界。
6. **数据库迁移闭环未执行**：已确认表定义、schema version、FTS 布局和锁机制，但本次没有连接 state.db、跑迁移/回滚、压测 WAL 或验证并发恢复。
7. **可选依赖与外部服务未运行确认**：provider、MCP、浏览器、消息平台、Docker/SSH/Modal/Daytona、memory backend 的运行可用性依赖用户配置和环境，静态存在不代表当前机器可用。
8. **跨前端一致性风险**：CLI、TUI、Desktop、dashboard、API 和 gateway 共享核心但各自有 transport/状态边界；修改 slash command、session、模型切换、工具发现或缓存逻辑时必须分别做 Python 与 JS/E2E 契约验证。
9. **安全边界需按部署模式复核**：容器无主机挂载、带挂载 Docker、本机 terminal、cron 无人值守、API runs 和插件 override 的审批语义不同；不能只凭默认配置推断实际风险。

## 9. 证据索引

- `README.md`：项目定位、安装、CLI/gateway 快速入口与公开能力。
- `AGENTS.md`：核心原则、目录、Agent loop、工具/插件/技能/cron/测试规则。
- `pyproject.toml`：Python 版本、依赖/extras、构建和 CLI/ACP entry points。
- `package.json`、`ui-tui/package.json`、`apps/desktop/package.json`、`web/package.json`：Node workspace 与前端构建边界。
- `website/docs/developer-guide/architecture.md`：官方仓库内系统概览、目录、数据流与推荐阅读顺序。
- `run_agent.py`、`model_tools.py`、`tools/registry.py`：AIAgent、工具发现/过滤/dispatch 的真实入口。
- `hermes_state.py`：SQLite schema、FTS5、session lineage 和耐久性策略。
- `gateway/platforms/api_server.py`：API 路由与 OpenAI 兼容接口。
- `tui_gateway/server.py`、`gateway/run.py`、`cron/jobs.py`、`cron/scheduler.py`、`hermes_cli/main.py`：TUI/gateway/cron/CLI 运行面。
- `tests/` 与前端 `*.test.*`：行为、契约、工具、入口和 UI 测试组织。
- 本文件是当前项目唯一架构事实源；源码路径、类名、函数名和协议标识按原文保留，说明与裁决使用中文。

## 10. 当前 checkout 目录与入口证据

当前仓库 HEAD 为 `624723130`，分支 `main`，origin 为 `NousResearch/hermes-agent`；`git ls-files` 约 9975 个文件。目录职责如下：

| 目录/文件 | 责任 | 关键证据 |
|---|---|---|
| `run_agent.py` | CLI Agent 组装、turn 循环、provider/tool wiring | `main`, `AIAgent` |
| `agent/` | 消息、压缩、子代理生命周期、secret scope | `subagent_lifecycle.py:98-390` |
| `tools/registry.py` | 工具 schema、过滤、dispatch、审批 | `ToolRegistry` |
| `tools/terminal/` | local/docker/ssh/singularity/modal/daytona 后端、PTY、输出 | terminal backends |
| `tools/browser_*.py` | Playwright/CDP/Camofox/MCP 浏览器状态和安全边界 | browser state helpers |
| `tools/skills_hub.py` | builtin/trusted/community skills 搜索、fetch、inspect | `SkillMeta:131`, `SkillSource:482` |
| `tools/mcp_*.py` | MCP server/client、catalog、tool bridge | MCP adapters |
| `tools/environments/` | 环境能力和限制描述 | environment registry |
| `hermes_state.py` | SQLite sessions/messages/FTS/lineage、WAL | schema helpers |
| `gateway/` | aiohttp/FastAPI 风格 API、run、profile、platform adapter | `api_server.py`, `run.py` |
| `tui_gateway/` | TUI JSON-RPC、事件、terminal output、审批 | server bridge |
| `hermes_cli/` | 主 CLI、commands、auth、setup、skills、plugins | `main.py` |
| `cron/` | JSON job store、scheduler、webhook delivery | jobs/scheduler |
| `plugins/` | plugin discovery、entry points、override | plugin loader |
| `memory/` | MemoryProvider、ContextEngine、indexing | provider ABC |
| `ui-tui/` | React/Ink TUI 与 newline JSON-RPC | package scripts |
| `apps/desktop/` | Electron desktop、nanostore、WS/JSON-RPC | subagent/terminal stores |
| `web/` | dashboard/browser UI | frontend package |
| `tests/` | Python 契约、工具、gateway、security、provider | pytest paths |

## 11. Agent loop 与工具调用真实链

```text
用户/平台 transport
  → session/profile/auth 解析
  → AIAgent 初始化 provider、历史、tool registry、skills、memory
  → turn 输入规范化与上下文预算
  → provider chat/responses stream
  → tool call 解析
      ├─ registry schema/allowlist/approval
      ├─ terminal/browser/MCP/skill/subagent dispatch
      └─ tool result scrub/truncate/telemetry
  → tool result 回注 history
  → provider continuation（可多轮）
  → final assistant message
  → session DB/WAL、SSE/JSON-RPC、UI state、run event
```

`run_agent.py` 是直接 Agent 入口；`model_tools.py` 将模型能力和工具集做过滤，`tools/registry.py` 决定公开 schema 与执行函数。工具结果必须回到统一消息格式，工具异常不能直接终止宿主进程。流式 transport 与同步 CLI 共享 loop 语义，但取消、断连和审批状态由 gateway/TUI 各自承接。

关键边界：

1. provider 只负责模型协议，不直接读写 sessions 数据库。
2. registry 只负责能力发现/验证/调度，不替工具实现资源释放。
3. terminal backend 只负责命令执行和输出，不决定业务会话是否完成。
4. subagent lifecycle 只负责子代理 handle、状态、wait/cancel/reconnect，不替父代理合并语义结果。
5. gateway 保存 run/session/approval 外部状态，必须将 client disconnect 与后台 run 状态分离。

## 12. 工具、终端、浏览器与 MCP

| 能力 | 选择点 | 资源/安全边界 |
|---|---|---|
| 文件操作 | registry allowlist + file safety | 路径规范化、敏感目录拒绝、大小限制 |
| shell/terminal | environment backend | timeout、PTY、进程组、输出 tail、secret scrub |
| Docker | container backend | mount 模式改变信任边界，需显式审批 |
| SSH | remote terminal | host key、凭证、远端 cwd、断连回收 |
| browser | Playwright/CDP/Camofox | profile 持久化、cookie、域名/导航策略 |
| MCP | client/server tool bridge | server trust、tool catalog、超时和取消 |
| skill | skills_hub fetch/install | source/trust level、压缩包路径、安装隔离 |
| subagent | lifecycle + provider | depth、parent session、capability HMAC、timeout |

`SkillSource` 抽象在 `tools/skills_hub.py:482-507`，要求 `search/fetch/inspect/source_id`；`SkillMeta` 同时携带 source、identifier、trust_level、repo/path 和 tags。多源搜索由 `_search_one_source` 在线程中执行（约 4531-4539），单源异常被记录并返回空结果，因此“搜索成功”不能证明所有源可用。

子代理 handle 在 `agent/subagent_lifecycle.py:347-387` 做 contract version、字段类型、时间有限性、capability HMAC 和 active parent session 校验；父会话不匹配时返回 UNKNOWN，不允许跨会话猜测 handle。`wait` 超时返回 `completed=False,timed_out=True`，并不会自动 kill provider；调用方必须继续 cancel/reconnect 或回收资源。

桌面端 `apps/desktop/src/store/subagents.ts:117-326` 以 subagent id 去重，保留最多 `MAX_STREAM` stream，终态不再覆盖；树按 parentId 构造并排序。`agent-terminal-stream.ts:15` 将每进程 backlog 限制为 256000 字节，tab 重开可回放，但 backlog 是内存态，不是耐久日志。

MCP server 的 tests/test_mcp_serve.py 通过 sessions JSON/SQLite fixtures 验证 conversations_list、messages_read、attachments_fetch、events_poll/wait；MCP SDK 缺失时使用 `importorskip`，因此静态通过不等于真实 MCP transport 可用。

## 13. Session、run、memory 与持久化

`hermes_state.py` 维护 session key/id、messages、tool calls、response lineage、FTS/trigram 索引和迁移版本。SQLite WAL 提高并发读，但写事务仍需短、可重试；SQL 注入回归在 `tests/test_sql_injection.py` 校验列名和参数化查询。

会话语义分三层：

- session id：单一持久会话记录。
- session key：按平台/profile/用户作用域复用会话。
- response id/previous_response_id：Responses API 的模型响应链，不等于完整 session key。

run 状态通常包含 queued/running/waiting approval/completed/failed/stopped；SSE event cursor 只保证事件桥缓存窗口内可追，不能替代 DB 状态。`POST /v1/approval` 和 `/stop` 是控制意图，调用返回不证明后台 worker 已立即结束。

MemoryProvider/ContextEngine 是可插拔边界；embedding/index backend 可能为 lazy optional。记忆写入若与 session message 不在同一事务，必须向调用方暴露部分成功，不可把“模型回答成功”当作记忆持久化成功。

## 14. 权限、秘密与资源治理

- `agent/secret_scope.py` 对环境变量做 secret/non-secret 分界；terminal/backend 路由提示不得泄露 token。
- API key/JWT、平台 webhook signature、MCP server credential、provider OAuth token 是不同信任域，不应共用一个 allowlist。
- approval gate 必须覆盖危险 terminal、浏览器登录、插件 override、远端部署和持久化 skill 安装。
- 每个 terminal 命令都应有 deadline、输出上限、进程树回收和 cwd 记录；超时不能只停止读取 stdout。
- 浏览器 profile 目录属于敏感持久资产；任务结束应按 profile scope 清理或明确保留策略。
- skill 下载与解包必须防 zip-slip、符号链接逃逸和脚本自动执行；trust_level 只能影响默认策略，不能代替内容扫描。
- 插件 entry point 在宿主进程执行，必须隔离异常和声明能力；重型/原生依赖宜独立进程。
- 子代理数量、深度、总 token、总 wall time 和并发工具数必须有界；父取消时级联 cancel 并等待终态。

## 15. API、CLI、平台与部署

API server 在 `gateway/platforms/api_server.py` 组装 Chat Completions、Responses、sessions、runs、events、approval、stop、health 和 profile prefix；`tui_gateway/server.py` 负责 newline JSON-RPC 和 live terminal output；`gateway/run.py` 负责服务启动、profile 和进程生命周期。

CLI 命令由 `hermes_cli/commands.py:COMMAND_REGISTRY` 单一注册，避免 help、autocomplete、Telegram/Slack mapping 分叉。`pyproject.toml` 的 `hermes`、`hermes-agent`、`hermes-acp` 三个 entry point 共享核心但 transport 不同。

部署组合包括本地 Python、Docker、远端 SSH/Modal/Daytona、Electron desktop、TUI Node runtime 和 dashboard。每种组合都要固定 home/state/db、secret source、terminal backend、browser profile、provider endpoint 和 shutdown timeout；只验证本地 CLI 不能推断 API/desktop/cron 安全。

## 16. 测试与证据边界

| 主题 | 代表测试 | 当前状态 |
|---|---|---|
| Agent loop/provider | `tests/agent/`, `tests/run_agent/` | 文件存在，未执行 |
| tool registry/dispatch | `tests/tools/` | 文件存在，未执行 |
| terminal/file safety | `tests/tools/test_terminal*`, file safety | 文件存在，未执行 |
| approval/secret | approval、secret_scope tests | 文件存在，未执行 |
| subagent lifecycle | `tests/agent/*subagent*` | 部分覆盖，未执行 |
| MCP server | `tests/test_mcp_serve.py` | importorskip，未执行 |
| sessions/SQL | `tests/test_sql_injection.py`、gateway session tests | 未执行 |
| API runs/SSE | `tests/gateway/` | 未执行 |
| frontend/TUI/Desktop | `ui-tui`/`apps/desktop` tests | 未执行 |

本轮只做 git、rg、现有文档和静态源码证据；没有安装依赖、启动服务、运行 Python/TS 测试、建立 CodeGraph 或访问远程 provider。任何性能、并发、断电、SIGKILL、浏览器登录、真实 MCP、远端 terminal 和 token 撤销结论均为未验证。

## 17. 当前审计交付

- 唯一写入目标：本文件；源码仓库仅保留原有未跟踪 `.codegraph/` 与源码侧 `ARCHITECTURE.md`，未修改源码。
- 当前版本：HEAD `624723130`，origin `https://github.com/NousResearch/hermes-agent.git`。
- MCP：本轮按用户要求未使用。目标仓库 `.codegraph` 已由本地 CLI 索引，统计见现场收口记录；不把其他项目代码图或验证冒充 Hermes 证据。

## 本轮现场收口记录（2026-08-22）

| 项目 | 现场证据 | 结果 |
|---|---|---|
| 远程同步 | `git fetch origin --prune`、`git pull --ff-only` | fast-forward 至最新 |
| 当前提交 | `git rev-parse HEAD` | `23a64a97ec928945b49389e8dfb6d06a11cb0132` |
| CodeGraph | `codegraph status`、`codegraph sync` | 7,343 files / 160,462 nodes / 504,283 edges，索引最新 |
| 文档行数 | `wc -l ARCHITECTURE.md` | 当前超过 500 行 |
| 差异检查 | `git diff --check -- ARCHITECTURE.md` | 本轮执行退出码 0 |

本轮只修改平台研究文档，未修改 Hermes-Agent 源码、依赖、测试或配置；严格未使用 MCP，仅使用 shell、Git、CodeGraph 与静态源码证据。新提交重点涉及 browser control broker/artifacts/API、compaction、extension router、TUI gateway 与相关测试，已纳入版本和未验证边界。

未验证：Python/Node 依赖安装、完整 pytest/前端构建、真实 provider、Gateway/API/WS、浏览器 CDP/cloud、MCP/插件、并发取消、进程崩溃恢复、快照/持久化、部署和性能。源码测试文件存在不等于运行通过。
- 文档需要继续补充的高价值验证：API schema 逐端点、SQLite migration/WAL、terminal kill process-group、subagent parent cancellation、MCP真实 transport、skill zip-slip、browser profile清理和 provider credential quarantine。
- 判定：静态源码审计完成；运行态与跨 transport 契约未验证。

## 18. 风险到控制映射

| 风险 | 控制点 | 证据/缺口 |
|---|---|---|
| 未授权 shell | registry approval + environment policy | 需实测拒绝路径 |
| secret 回显 | secret_scope、tool result scrub | provider/插件组合未实测 |
| 子代理越权 | HMAC handle + parent session | 需跨会话伪造回归 |
| 子代理泄漏 | depth/count/time budget | 需压力与级联取消 |
| MCP 恶意工具 | server allowlist、schema、审批 | 真实 transport 未验证 |
| skill 恶意包 | trust/source、zip-slip 防护 | 解包/符号链接场景未验证 |
| browser cookie 泄漏 | profile scope、域策略 | 登录态清理未验证 |
| terminal 卡死 | deadline + process group kill | 强杀未验证 |
| SSE 断连 | run state 与 stream 解耦 | client disconnect 未验证 |
| SQLite 锁 | WAL、短事务、参数化 | 并发恢复未验证 |
| cron 无人值守 | job policy、secret scrub、审批 | 实际 cron 未启动 |
| provider token 失效 | credential quarantine | 仅测试源码证据 |
| plugin crash | 异常隔离/可选加载 | 原生插件未实测 |

## 19. 入口到资源释放导航

```text
hermes CLI / API / TUI / ACP
        │
        ▼
profile + auth + session resolver
        │
        ▼
AIAgent turn
        ├─ context budget / compression
        ├─ provider request / stream
        ├─ registry dispatch
        │    ├─ terminal → process group → stdout/stderr tail → cleanup
        │    ├─ browser → profile/CDP → page/context close
        │    ├─ MCP → client session → tool timeout/close
        │    ├─ skill → fetch/unpack → trust/install boundary
        │    └─ subagent → handle → wait/cancel/reconnect
        └─ persistence → SQLite transaction/WAL → event bridge → transport
```

这条链上任一局部成功都不能代表全局完成：模型生成成功不代表工具副作用成功；工具返回成功不代表 session commit 成功；SSE 发送完成不代表后台 run 已终态；subagent summary 不代表其 terminal/browser/MCP 资源已释放。平台适配时应把每个阶段的状态、error code、retryable 和 cleanup result 独立记录。

## 20. 推荐定向验证命令（本轮未执行）

```text
cd ~/Documents/Agent/github 源码参考/10_agent_platform_reference/01_成品Agent平台/hermes-agent
bash scripts/run_tests.sh tests/test_sql_injection.py tests/test_mcp_serve.py
bash scripts/run_tests.sh tests/agent tests/tools
npm --prefix ui-tui test -- --run
npm --prefix apps/desktop test -- --run
python -m run_agent --help
python -m hermes_cli.main doctor
```

运行前应为测试设置独立 `HERMES_HOME`、SQLite 临时目录、浏览器 profile、Docker/SSH mock、MCP fake server 和端口 4780；禁止把真实 token、生产 session DB 或用户浏览器 profile 注入测试。测试结束后必须清点残留进程、socket、临时文件、容器和 lock。

## 21. 终态声明

本文已把 hermes-agent 当前 checkout 的定位、目录、agent loop、工具与技能注册、MCP、terminal/browser、subagent/session/provider、权限、资源、API/CLI、部署、测试与剩余风险收敛为单一文档。源码没有被修改，文档之外没有新增旁路研究文件。MCP 错绑证据与运行态缺口均已显式保留，后续复核应继续更新本文件而不是创建第二份架构文档。

## 22. 细粒度 file:line 复核表

| 子系统 | 当前源码锚点 | 需要复核的行为 |
|---|---|---|
| 主循环 | `run_agent.py` | continuation、压缩和终态提交 |
| 工具 schema | `tools/registry.py` | 参数校验与未知工具拒绝 |
| 工具调用 | `model_tools.py` | provider tool choice、过滤和回注 |
| secrets | `agent/secret_scope.py:124-138` | 环境 scrub 与日志脱敏 |
| 子代理 handle | `agent/subagent_lifecycle.py:347-387` | parent、HMAC、contract version |
| 子代理等待 | `agent/subagent_lifecycle.py:271-345` | timeout、cancel、reconnect |
| skill 元数据 | `tools/skills_hub.py:131-141` | source/trust/identifier |
| skill source | `tools/skills_hub.py:482-507` | search/fetch/inspect |
| skill 并发 | `tools/skills_hub.py:4531-4540` | 单源异常隔离 |
| terminal backlog | `apps/desktop/src/app/right-sidebar/terminal/agent-terminal-stream.ts:15` | 内存上限 |
| terminal writer | 同文件 `19-45` | 注册、回放、注销 |
| subagent UI | `apps/desktop/src/store/subagents.ts:117-326` | 去重、树、终态 |
| MCP sessions | `tests/test_mcp_serve.py:521-765` | public API 与 cursor |
| SQL 防注入 | `tests/test_sql_injection.py:1-40` | 列名和参数化 |
| API runs | `gateway/platforms/api_server.py` | run/approval/stop/events |
| TUI events | `tui_gateway/server.py` | JSON-RPC 与输出桥 |
| cron | `cron/jobs.py`, `cron/scheduler.py` | 持久化与无人值守 |
| CLI | `hermes_cli/main.py`, `commands.py` | 单一注册表 |
| state | `hermes_state.py` | WAL、FTS、迁移 |
| provider | `providers/`, `hermes_cli/auth.py` | credential pool/quarantine |
| browser | `tools/browser_camofox_state.py` | profile scope |

以上索引绑定当前 `624723130`，远程更新后必须重新计算行号；本轮没有把历史细探中的旧 commit 行号当作当前运行证据。

## 23. 研究范围边界

- 仅修改平台研究文档目录，未修改源码、测试、锁文件、远程分支或部署环境。
- 未使用用户未授权的 MCP 作为事实来源；MCP 错绑信息仅作工具链风险记录。
- CodeGraph 目标仓库索引不可用，未自行创建共享索引；源码、git、现有文档是本轮证据。
- 结论按静态实现事实、测试意图和未验证运行态三类表达，避免把存在性当成功。
- 任何后续运行验证应在独立 home、端口 4780 和临时数据库中执行，并回填本文件。

本轮静态审计在此收口。

唯一文档继续有效。

审计完成。
