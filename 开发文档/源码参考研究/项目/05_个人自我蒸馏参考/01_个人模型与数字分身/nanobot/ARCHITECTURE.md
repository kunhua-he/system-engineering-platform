# nanobot 架构档案

> 本文件是仓库根目录的正式架构文档。内容按当前工作树的 README、仓库规则、依赖清单、源码、测试与现有 `细探-nanobot.md` 交叉核对；`细探-nanobot.md` 仅作为施工材料，不是本文件的事实源。
>
> 项目根目录：`nanobot/`
> 版本声明：`pyproject.toml` 中为 `0.3.0`
> 许可证：MIT

## 1. 项目定位

nanobot 是一个 Python 编写的轻量、自托管个人 AI Agent 运行时/框架。它把多种聊天入口（WebUI、终端 TUI、Telegram、Discord、Slack、飞书、微信/企微、邮件等）统一成消息，再通过一个小型异步 Agent Loop 调用可配置的 LLM，按需执行工具，并把会话、长期记忆、自动化任务和运行状态持久化到本地文件系统。

它不是数据库驱动的业务系统，也不是把所有能力塞进一个大型编排层的平台。真实设计是：**核心 Agent Loop/Runner 保持较小，渠道、工具、Provider、Skill、MCP 和 WebUI/Gateway 在边缘扩展**。

主要使用方式：

- 个人在浏览器中使用持久话题、工作区、Skills、Apps 和 Automations；
- 个人在终端使用 native TUI 或经典 Python CLI；
- 将聊天渠道接入同一个 Agent 运行时；
- 用 OpenAI-compatible HTTP API 或 Python SDK 集成到其他程序；
- 以本地/服务器 Gateway 进程长期运行 Agent、渠道和定时任务。

## 2. 总体文本流程图

```text
┌────────────────────────────── 外部入口层 ──────────────────────────────┐
│ WebUI 浏览器      native TUI/CLI       聊天渠道        HTTP API       SDK │
│ React/TS          tui/ + Typer        channels/*      aiohttp         │
└──────────────┬───────────┬─────────────┬──────────────┬───────────────┘
               │           │             │              │
               │ WebSocket │             │ InboundMessage│ process_direct()
               └───────────┴──────┬──────┴──────────────┴───────────────┘
                                  ▼
                    MessageBus.inbound / outbound
                    nanobot/bus/events.py + queue.py
                                  │
                                  ▼
┌──────────────────────────── Agent 编排层 ──────────────────────────────┐
│ AgentLoop                                                               │
│  session key / 并发锁 / turn 生命周期 / command / hooks / delivery      │
│  process_direct() 与 run() 共用 _process_message()                       │
└────────────────────────────────┬───────────────────────────────────────┘
                                 ▼
                    SessionManager → Session.get_history()
                                 │
                                 ▼
┌────────────────────────────上下文与状态层───────────────────────────────┐
│ ContextBuilder                                                         │
│  project AGENTS.md + agent SOUL/USER + MEMORY.md + Skills + history     │
│  runtime context / session summary / media / token budget               │
│                                                                        │
│ Session JSONL（短期对话） ←→ AutoCompact / Consolidator                 │
│ memory/history.jsonl（归档） ←→ Dream → SOUL/USER/MEMORY.md             │
│ GitStore（Dream durable 文件版本记录）                                  │
└────────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌────────────────────────────模型执行层─────────────────────────────────┐
│ AgentRunner                                                             │
│  LLM request → streaming/reasoning → ToolRegistry.execute()             │
│  工具结果回填 messages → 继续迭代，直到 final/error/limit                │
└───────────────┬──────────────────────────────┬────────────────────────┘
                │                              │
                ▼                              ▼
       ProviderFactory/Registry               ToolLoader/ToolRegistry
       LLMProvider.chat*()                    built-in tools + MCP + plugins
                │                              │
                ▼                              ▼
   Anthropic / OpenAI-compatible /       files / shell / web / MCP / cron /
   Azure / Bedrock / Codex / OAuth       subagent / image / memory 等能力
                │                              │
                └──────────────┬───────────────┘
                               ▼
                   AgentRunResult / OutboundMessage
                               │
               ┌───────────────┴────────────────┐
               ▼                                ▼
       outbound MessageBus → 渠道发送       SDK RunResult/StreamEvent
               │
               ▼
      WebSocket/WebUI 活动流、聊天回复、TUI 渲染

并行后台支路：
Gateway → ChannelManager + AgentLoop + CronService + Dream/Heartbeat + WebUI services
Cron/本地 trigger → InboundMessage 或 bound session turn → 同一 AgentLoop
```

## 3. 真实分层与边界

仓库没有强制的 Clean Architecture 目录；以下是按真实调用关系归纳的分层，而不是理想化分层。

| 层 | 真实职责 | 主要路径 |
|---|---|---|
| 入口与适配 | CLI、TUI、浏览器、HTTP、聊天平台将外部输入变成 Agent 请求 | `nanobot/cli/`, `tui/`, `webui/`, `nanobot/channels/`, `nanobot/api/` |
| 消息与事件 | 异步解耦 inbound/outbound；另有 runtime/outbound UI 事件 | `nanobot/bus/events.py`, `queue.py`, `runtime_events.py`, `outbound_events.py` |
| 应用编排 | session 选择、turn 锁、hooks、命令、delivery、运行时选择、生命周期 | `nanobot/agent/loop.py`, `turn_delivery/`, `turn_hooks.py` |
| 模型执行 | 多轮 LLM 调用、streaming/reasoning、tool call、重试、注入、迭代限制 | `nanobot/agent/runner.py` |
| 上下文 | system prompt、项目指令、身份、用户、长期记忆、Skills、历史和媒体 | `nanobot/agent/context.py`, `skills.py`, `templates/` |
| 会话与记忆 | JSONL 会话、缓存、分片/replay、压缩；历史归档、Dream、Git 版本记录 | `nanobot/session/`, `nanobot/agent/memory.py`, `nanobot/utils/gitstore.py` |
| Provider | Provider 元数据、配置匹配、客户端构造、不同 API 协议适配 | `nanobot/providers/registry.py`, `factory.py`, `base.py`, 各 provider |
| Tool 能力 | JSON Schema、参数校验、动态发现、工具执行和错误标准化 | `nanobot/agent/tools/base.py`, `schema.py`, `loader.py`, `registry.py` |
| 渠道插件 | 每渠道配置、依赖声明、runtime 懒加载、收发消息和平台特性 | `nanobot/channels/plugin.py`, `registry.py`, `manager.py`, `channels/<name>/` |
| Gateway/自动化 | 进程生命周期、WebUI HTTP/WS 服务组合、Cron、Heartbeat、本地 trigger | `nanobot/gateway/`, `nanobot/webui/`, `nanobot/cron/`, `nanobot/triggers/` |
| 安全与配置 | Pydantic 配置、工作区边界、SSRF、shell sandbox、配对授权 | `nanobot/config/`, `nanobot/security/`, `nanobot/pairing/` |

### 核心边界

1. `AgentLoop` 面向渠道和会话；`AgentRunner` 面向 Provider 和工具。前者不应吞入渠道/Provider 的特定实现。
2. MCP 连接由应用组合根持有：调用方创建 `MCPProvider`，与 `ToolRegistry` 共享，负责 `connect()`/`aclose()`；AgentLoop 不拥有 MCP 生命周期。
3. 渠道由 `ChannelPlugin` manifest 描述，先依赖无关地发现，只有启用时才加载实际平台 SDK 和 `BaseChannel` runtime。
4. Tool 的名称、描述、JSON Schema 和错误文本是模型契约；`ToolRegistry.prepare_call()` 负责查找、参数 coercion、校验，`execute()` 负责统一错误包装。
5. 配置工作区与有效项目工作区可不同：Agent workspace 持有 `SOUL.md`、`USER.md`、session namespace、memory 和自定义 Skills；项目 workspace 提供 `AGENTS.md`、相对路径和 shell cwd。
6. WebUI 不是独立后端应用：WebSocket channel 同时承担 WS server 和 HTTP route 组合，`GatewayHTTPHandler` 分发 `/api/...`，Gateway services 持有具体状态服务。

## 4. 核心数据流

### 4.1 普通聊天/CLI turn

1. 渠道收到外部消息，构造 `InboundMessage(channel, sender_id, chat_id, content, media, metadata)`。
2. 渠道调用 `MessageBus.publish_inbound()`；CLI/SDK/API 也可直接调用 `AgentLoop.process_direct()`。
3. `AgentLoop.run()` 消费 bus；按 unified-session 或显式 override 计算 effective session key，优先处理 runtime control/斜杠命令，再按 session 建立异步锁。
4. 恢复 `Session`，必要时提前持久化用户消息；`ContextBuilder` 读取项目 `AGENTS.md`、Agent 的 `SOUL.md`/`USER.md`、`memory/MEMORY.md`、近期 `history.jsonl`、归档摘要、Skills、媒体和 runtime context，生成 system + history + current message。
5. `ModelRuntimeResolver`/Provider snapshot 确定本轮不可变的 provider、model、context window 和 generation settings。
6. `AgentRunner` 把 `AgentRunSpec.initial_messages` 发给 Provider。Provider 返回文本、reasoning、tool calls 或错误；streaming delta 通过回调传给 `TurnDelivery`。
7. 对 tool call，Runner 调 `ToolRegistry.execute()`；工具结果追加到会话消息，继续下一轮。可配置并发安全的只读工具，但 exclusive/有副作用工具不能随意并行。
8. 最终结果经 `TurnDelivery` 变成 `OutboundMessage`，写入 outbound bus，由 `ChannelManager` 投递到原渠道；WebUI/TUI 还可消费结构化 runtime/UI 事件。
9. turn 状态、usage、provider continuation、checkpoint 和消息按策略写入 session JSONL/metadata；完成后触发自动压缩、延迟自动化 turn 等后台动作。

`AgentLoop.process_direct()`（`agent/loop.py:2347`）与 bus 路径共用 `_process_message()` 和 session lock，但不会自己向 inbound bus 排队；这是 HTTP API、SDK 和一次性 CLI 请求的直接入口。

### 4.2 会话、上下文和压缩

```text
Session.messages（短期、可重放）
        │ token/replay 窗口超限、idle TTL 或文件上限
        ▼
Consolidator.pick_consolidation_boundary()
        │ 选择合法 user-turn 边界，避免从 tool/assistant 中间切断
        ▼
Provider 生成摘要；失败则 raw_archive()
        ▼
memory/history.jsonl 追加 {cursor,timestamp,content,session_key}
        │ .cursor 单调递增，append lock 串行 cursor+append
        ▼
Session.last_consolidated / metadata._last_summary 更新
        │
        └── ContextBuilder 下次只重放合法近期尾部 + 摘要 + recent history
```

- `Session.get_history()` 先按消息窗口切片，再按 token 预算从尾部保留，并修正 user/tool 合法边界。
- `JsonlSessionStore` 将 sessions 放在 Agent workspace 外的 runtime data root，并用 workspace-id 隔离命名空间；写入使用临时文件、fsync、rename 和目录 fsync。
- `AutoCompact` 负责 idle TTL 检查；`Consolidator` 负责 token/replay-window 和 idle archive。

### 4.3 Dream 长期记忆流

```text
history.jsonl 中 cursor > .dream_cursor 的条目
        + 当前真实 SOUL.md / USER.md / memory/MEMORY.md
        + templates/agent/dream.md 或 workspace prompts/dream.md
        ▼
Dream 受限 ToolRegistry（只允许读/编辑指定长期文件）
        ▼
真实 durable 文件最小修改
        ▼
GitStore 对 SOUL/USER/MEMORY/.dream_cursor 做版本记录
        ▼
成功且无 tool error 才推进 .dream_cursor
```

`MemoryStore` 位于 `agent/memory.py:73`；`build_dream_prompt()` 位于约 `:582`，`DreamRunProgress` 将工具错误记录为不安全状态；`Consolidator` 从约 `:805` 开始。`history.jsonl` 是结构化运行归档，长期 Markdown 文件表达 durable 语义，GitStore 提供 `/dream-log`、`/dream-restore` 所需的审计/恢复基础。

### 4.4 Gateway、WebUI 和自动化

`nanobot gateway` 的组合根启动并管理：启用渠道、WebSocket/WebUI、AgentLoop、SessionManager、CronService、Dream/Heartbeat 任务、运行时配置刷新和 health endpoint。默认：Gateway health 为 `127.0.0.1:18790/health`，WebUI/WebSocket 为 `127.0.0.1:8765`；OpenAI API 是独立的 `nanobot serve`，默认 `127.0.0.1:8900`。

- `GatewayRuntime` 管理背景进程、PID/state/log 文件、on-demand client lease 和 foreground/background 生命周期。
- `GatewayServiceInstaller` 在 macOS 生成 LaunchAgent，在 Linux 生成 systemd user service。
- `CronService` 使用 JSON store、action journal、file lock 和 run records；bound agent-turn job 回到具体 session，而不是凭空创建 delivery target。
- WebUI 浏览器通过 WebSocket envelope 发送用户 turn、控制命令和媒体；HTTP handler 提供会话、线程、文件预览、设置、Skills、MCP、Automations、workspace 和 token routes。

## 5. 关键类、函数、数据模型与路径

| 名称 | 作用 | 相对路径 |
|---|---|---|
| `InboundMessage` / `OutboundMessage` | 渠道与 Agent 之间的输入/输出消息值对象；`InboundMessage.session_key` 默认是 `channel:chat_id` | `nanobot/bus/events.py:24-60` |
| `MessageBus` | 两个 `asyncio.Queue`，隔离渠道和 Agent | `nanobot/bus/queue.py:8-44` |
| `AgentLoop` | 核心应用编排、bus 消费、turn dispatch、直接处理、资源关闭 | `nanobot/agent/loop.py:181-2417`；`from_config():462`、`run():1227`、`process_direct():2347` |
| `TurnContext` / `TurnKind` | 单轮内部状态、session/runtime/provider state、hooks、stream callbacks | `nanobot/agent/loop.py:112-179` |
| `AgentRunner` | Provider ↔ tool 的多轮执行循环 | `nanobot/agent/runner.py:91-139` |
| `AgentRunSpec` / `AgentRunResult` | 一次 runner 执行的输入约束与结果 | `nanobot/agent/runner.py:91-135` |
| `ContextBuilder` | 组装 identity、bootstrap、memory、Skills、history、current message | `nanobot/agent/context.py:52-127,206-315` |
| `Tool` / `ToolResult` / `Schema` | 工具能力、结构化错误、JSON Schema 片段与校验 | `nanobot/agent/tools/base.py:30-35,144-228` |
| `ToolRegistry` | 注册、稳定排序 schema、名称解析、参数校验和执行 | `nanobot/agent/tools/registry.py:19-212` |
| `ToolLoader` | `pkgutil` 扫描内置工具，`importlib.metadata` 加载 `nanobot.tools` entry points | `nanobot/agent/tools/loader.py:26-124` |
| `ToolCallRequest` | Provider 产生的工具调用请求 | `nanobot/providers/base.py:53-97` |
| `LLMResponse` | Provider 返回文本、tool calls、usage、reasoning、错误和 continuation | `nanobot/providers/base.py:254-280` |
| `ProviderConversationState` | Provider 私有 continuation state，写入 session sidecar，不进入公共历史 | `nanobot/providers/base.py:156-239` |
| `ProviderSpec` / `ProviderModelSpec` | Provider 识别、backend、API base、模型目录、thinking/OAuth/gateway 元数据 | `nanobot/providers/registry.py:21-136` |
| `ProviderSnapshot` / `make_provider` | 从配置解析 provider、fallback 和 model runtime | `nanobot/providers/factory.py:14-22` 及其构造函数 |
| `Config` | 根 Pydantic settings；含 agents/channels/providers/api/gateway/tools/presets | `nanobot/config/schema.py:431-476` |
| `AgentDefaults` / `ModelPresetConfig` | 默认模型、上下文、token、tool iterations、压缩、Dream、timezone | `nanobot/config/schema.py:97-166` |
| `ProviderConfig` / `MCPServerConfig` | Provider API/OAuth/proxy/extra fields 与 MCP stdio/HTTP 配置 | `nanobot/config/schema.py:202-240,372-384` |
| `Session` / `SessionPolicy` | 对话消息、metadata、consolidation offset、provider state 和持久化策略 | `nanobot/session/manager.py:155-181` |
| `JsonlSessionStore` / `SessionManager` | 文件会话读写、workspace namespace、cache、锁、list/export/restore | `nanobot/session/manager.py:563` 起；`SessionManager` 在同文件后段 |
| `MemoryStore` | Markdown durable memory、JSONL archive、双 cursor、GitStore | `nanobot/agent/memory.py:73-115` |
| `Consolidator` | token/replay-window/idle 归档、摘要、raw fallback | `nanobot/agent/memory.py:805-1218` |
| `ChannelPlugin` | 渠道 manifest；描述 runtime、setup、依赖、能力和可选 webui | `nanobot/channels/plugin.py:22-94` |
| `discover_plugins` / `ChannelManager` | manifest 懒发现、启用渠道实例化、in/out dispatch 和重试 | `nanobot/channels/registry.py:20-104`；`manager.py:79-280` |
| `WebSocketConfig` / `WebSocketChannel` | WebUI/WS auth、token、路径、媒体、streaming 和 envelope 协议 | `nanobot/channels/websocket/runtime.py:123-340` 及后续；`manifest.py:7-21` |
| `GatewayHTTPHandler` | 与 WebSocket 同进程提供 WebUI HTTP routes | `nanobot/webui/ws_http.py:1-6,290-320` |
| `GatewayRuntime` / `GatewayServiceInstaller` | 背景进程 lease/status/stop/restart 与 launchd/systemd | `nanobot/gateway/runtime.py:45-274`；`gateway/service.py:20-202` |
| `CronService` | 定时 job 的加载、迁移、锁、执行和 run record | `nanobot/cron/service.py:149-320` |
| `Nanobot` | Python SDK facade；组合 loop/MCP，暴露 run、stream、sessions、memory、runtime | `nanobot/nanobot.py:66-357` |
| `RunResult` / `StreamEvent` / `SessionSnapshot` | SDK 的公共结果、事件和快照协议 | `nanobot/sdk/types.py:11-174` |

## 6. 入口、API、CLI 与 SDK

### 6.1 Python 入口与 CLI

`pyproject.toml:109-110` 声明 console script：

```text
nanobot → nanobot.cli.entry:main
```

`cli/entry.py` 对无需 classic/message 参数的 `nanobot agent` 走轻量 TUI 路径，否则转到 `cli.commands.app`。已核对的命令面：

- `nanobot onboard`：创建/刷新 config 和 workspace，写入模板；
- `nanobot agent`：native TUI；`nanobot agent -m "..."` 为一次性 direct turn；`--classic` 走经典终端路径；
- `nanobot gateway`：前台 Gateway；`--background`、`status`、`logs`、`stop`、`restart`、`install-service`、`uninstall-service`；
- `nanobot webui`：准备/启动 WebUI 与共享本地 Gateway（产品入口，README 记录）；
- `nanobot serve`：独立 OpenAI-compatible HTTP API；
- `nanobot trigger <trigger_id> [message]`：投递本地 trigger；
- `nanobot status`：只检查本地 config/workspace/provider 配置，不验证真实网络调用；
- `nanobot sessions ...`、`nanobot channels ...`、`nanobot plugins ...`、`nanobot provider ...`：会话、渠道、可选特性和 Provider/OAuth 管理子命令。

源码入口：`nanobot/cli/entry.py`、`nanobot/cli/commands.py`、`nanobot/cli/agent.py`、`nanobot/cli/gateway.py`；命令注册位置可由 `commands.py` 的 `@app.command`、`add_typer` 和 `gateway.py` 的 `@gateway_app.command` 复核。

### 6.2 OpenAI-compatible HTTP API

实现：`nanobot/api/server.py`；`create_app()` 注册：

| 方法 | 路径 | 行为 |
|---|---|---|
| `POST` | `/v1/chat/completions` | JSON 或 multipart；单个 user message；支持 `session_id`、固定已配置 model、媒体附件、`stream=true` SSE |
| `GET` | `/v1/models` | 返回当前配置的一个模型名 |
| `GET` | `/health` | 返回 `{"status":"ok"}`，不要求 API key |

重要契约：默认只绑定 `127.0.0.1:8900`；配置非 loopback host 时必须设置 `api.api_key`。配置了 key 后除 `/health` 外使用 `Authorization: Bearer <api_key>`；每个 `session_id` 有 asyncio lock；API 请求最终调用 `AgentLoop.process_direct(channel="api")`。

### 6.3 WebUI/WebSocket API

前端入口在 `webui/src/main.tsx`，HTTP 客户端和类型在 `webui/src/lib/api.ts`、`types.ts`，Vite 代理在 `webui/vite.config.ts`。WebUI 后端由 `WebSocketChannel` + `GatewayHTTPHandler` 提供：

- WebSocket：用户 turn、streaming delta、reasoning、tool/activity、runtime control、媒体和 session scope；
- `/api/sessions`、`/api/sessions/<key>/webui-thread`、file preview、session automations；
- `/api/webui/automations/*`、`/api/webui/skills/*`、marketplace；
- `/api/settings/*`：model/provider/channel/MCP/OAuth/API service/network safety/CLI Apps/transcription 等设置；
- `/api/workspaces/*`、pairing、gateway token 和静态 WebUI 资源。

具体 route 由 `ws_http.py` 与 WebSocket runtime 的 request dispatcher 共同维护；前端 `api.ts` 的 mutation action（例如 `automation.enable`、`settings.provider.update`）映射到后端 mutation paths，不能只根据前端函数名臆测一个独立 REST 服务。

### 6.4 Python SDK

公共 facade：

```python
from nanobot import Nanobot

bot = Nanobot.from_config("~/.nanobot/config.json", workspace="/path/to/project")
result = await bot.run("Summarize this repo", session_key="sdk:default")
async for event in bot.stream("Continue"):
    ...
await bot.aclose()
```

实际接口：

- `Nanobot.from_config(config_path=None, workspace=None, model=None, model_preset=None)`：读取配置、创建 `ToolRegistry`/MCPProvider/AgentLoop；`model` 与 `model_preset` 互斥；
- `run()`：返回 `RunResult`；支持 session key、channel/chat/sender、media、ephemeral、attributes、hooks、per-run model/preset；
- `run_streamed()` / `stream()`：返回/迭代 `StreamEvent`，事件包括 `run.started`、text/reasoning delta/completed、tool started/completed/failed、run completed/failed；
- `bot.sessions`：ingest/get/list/export/restore/clear/delete/flush；
- `bot.memory`：读写 `MEMORY.md`、追加/读取 `history.jsonl`；
- `bot.runtime`：当前 model/workspace、runtime context provider、turn persisted callback、session compaction；
- async context manager 和 `aclose()`：关闭 AgentLoop 及 MCP provider。

## 7. 技术栈与依赖边界

| 部分 | 技术/事实 |
|---|---|
| Python runtime | Python `>=3.11`；asyncio；MIT；包名 `nanobot-ai` |
| CLI | Typer、Rich、Questionary、Prompt Toolkit、Loguru |
| 配置/模型 | Pydantic 2、pydantic-settings；camelCase alias 与 snake_case 输入兼容 |
| LLM/API | Anthropic SDK、OpenAI SDK、httpx；OpenAI Chat Completions/Responses 兼容；Azure、Bedrock、Codex/OAuth、GitHub Copilot、xAI 等专用 backend |
| Provider 路由 | `ProviderSpec` registry；关键词、key prefix、apiBase、local/gateway/OAuth 标记、fallback |
| 工具协议 | 自定义 Tool + JSON Schema；MCP `>=1.26,<2.0`；entry point group `nanobot.tools` |
| 网络与解析 | websockets 15/16、websocket-client、aiohttp（API extra）、ddgs、readability-lxml、lxml-html-clean |
| 自动化 | croniter、filelock、JSON store/action journal、run records |
| 持久化 | 本地 JSONL/JSON/Markdown；GitStore 使用 dulwich；没有项目自有 SQL 数据库层 |
| 文档/附件 | pypdf、python-docx、openpyxl、python-pptx、defusedxml、chardet；文档读取已纳入 core/兼容 extra |
| WebUI | React 18、TypeScript、Vite、Vitest、Tailwind CSS、Radix UI、i18next、React Testing Library |
| TUI | Bun、TypeScript、`@opentui/core`；源码在 `tui/`，由 Python CLI launcher 启动/连接 |
| 构建/发布 | Hatchling；`hatch_build.py`；WebUI 产物目标 `nanobot/web/dist/` 并随 wheel 打包；Bun 负责 WebUI build |
| 质量 | Ruff（E/F/I/N/W，100 列，E501 忽略）；BasedPyright strict；pytest/pytest-asyncio；Python coverage 门槛 75% |

核心依赖和构建声明以 `pyproject.toml` 为准；WebUI/TUI 的独立依赖以 `webui/package.json`、`tui/package.json` 为准。

## 8. 目录与持久化布局

### 8.1 代码目录

```text
nanobot/
├── nanobot/                 Python 包
│   ├── agent/               Loop、Runner、Context、Memory、Tools、Skills、hooks
│   ├── api/                 aiohttp OpenAI-compatible API
│   ├── apps/                CLI Apps 与应用辅助
│   ├── audio/               音频转写
│   ├── bus/                 消息和运行时事件总线
│   ├── channels/            18 个 manifest/runtime 渠道包（含 websocket）
│   ├── cli/                 Typer 命令、TUI/WebUI/Gateway launcher
│   ├── command/             slash command router/builtin
│   ├── config/              schema、loader、paths、watcher、timezone
│   ├── cron/                定时任务、session-bound turns、run records
│   ├── gateway/             共享 Gateway 进程 runtime/service
│   ├── pairing/             渠道 DM pairing store
│   ├── providers/           Provider base/registry/factory/实现
│   ├── sdk/                 public types、clients、streaming、runtime helpers
│   ├── security/             workspace/network/sandbox boundary
│   ├── session/              session manager、goal、automation、WebUI turn state
│   ├── skills/               内置 SKILL.md 与 skill-creator
│   ├── templates/            prompt/bootstrap/template files
│   ├── triggers/             local trigger store/runner/turns
│   ├── utils/                file/git/runtime/prompt/media/helper 基础设施
│   ├── web/                  bundled WebUI package/dist 入口
│   └── webui/                WebUI HTTP/settings/session/media services
├── webui/                    React SPA 源码、Vite、Vitest
├── tui/                      Bun/OpenTUI native terminal client
├── tests/                    Python 主测试集
├── docs/                     用户/开发/协议/部署文档
├── scripts/                  安装、渠道依赖等脚本
├── .agent/                   design/security/gotchas 约束
├── pyproject.toml            Python 包、依赖、entrypoint、质量配置
├── hatch_build.py            Hatch 构建 hook
└── ARCHITECTURE.md           本正式架构档案
```

当前工作树还存在 `细探-nanobot.md`，它是分析施工材料，不属于正式架构入口。

### 8.2 默认运行数据

以 `docs/architecture.md`、`config/paths.py`、`session/manager.py` 和 `agent/memory.py` 实现为准：

```text
~/.nanobot/config.json                 配置（可通过 --config 指定）
~/.nanobot/workspace/                  Agent workspace 默认位置
<config-dir>/sessions/<workspace-id>/  Session JSONL（workspace 外）
<workspace>/SOUL.md                    Agent 声音/身份
<workspace>/USER.md                    用户档案
<workspace>/memory/MEMORY.md           长期事实
<workspace>/memory/history.jsonl       归档历史
<workspace>/memory/.cursor              Consolidator/archive cursor
<workspace>/memory/.dream_cursor       Dream 消费 cursor
<workspace>/cron/jobs.json             Cron jobs
<workspace>/cron/action.jsonl          Cron action journal
<workspace>/cron/runs/                 Automation run records
<config-dir>/run/、logs/               Gateway 状态和日志
<config-dir>/webui/、media/            WebUI/media runtime data
```

`MemoryStore` 初始化时只用 GitStore 跟踪 `SOUL.md`、`USER.md`、`memory/MEMORY.md` 和 `.dream_cursor`；普通会话文件不进入该 durable 记忆 Git 历史。

## 9. 安全架构

- 文件系统工具经 `security/workspace_access.py`/`workspace_policy.py` 解析并检查 active workspace containment；额外目录按 read/write capability 区分，不能把整个 Agent workspace 作为任意工具根目录。
- Shell 的 `restrict_to_workspace` 是应用层边界，不等于进程隔离；可选 sandbox backend 在 `agent/tools/sandbox.py`，当前 shipped backend 是 bwrap。
- Web 工具、HTTP/SSE MCP 和重定向请求必须经过 `security/network.py` 的 URL/SSRF 检查；loopback、私网、link-local、云 metadata 默认阻断，显式 whitelist 才是例外。
- API 非 loopback bind 必须有 `api.api_key`；WebSocket wildcard host 必须配置 static/issued token 或 trusted proxy auth。
- 渠道通过 `allow_from`、pairing store 和 token/connector 控制来访者；`BaseChannel.is_allowed()` 的优先级是 `*`、精确 allowlist、pairing、deny。
- Prompt、tool descriptions、Skills、session replay 和 memory 都会重新进入 LLM 上下文；模板泄漏、tool-call echo、时间/本地路径等污染由 `strip_think()`、history sanitization 和上下文上限处理。
- Dream 只能编辑限定 durable 文件；工具错误时不推进 Dream cursor，避免把不完整运行标为成功。

安全规则的权威施工约束是 `.agent/security.md`；本节仅记录架构边界。

## 10. 测试与验证面

### 10.1 配置声明

`pyproject.toml:176-185`：

- `asyncio_mode = "auto"`；
- `testpaths = ["tests", "nanobot/channels"]`；
- coverage source 是 `nanobot`，报告门槛 `fail_under = 75`。

根 `conftest.py` 提供跨套件 fixture：隔离日志激活、把 session runtime root 重定向到 `tmp_path`，并在 Windows 上处理证书 context，避免测试写入真实 home/config 数据。

### 10.2 当前工作树的测试分布

按文件名静态清点（未执行）：

- `tests/test_*.py`：11 个 Python 主测试文件；
- `nanobot/channels/**/tests/test_*.py`：47 个渠道测试文件；
- `webui/src/tests/*.test.*`：70 个 Vitest 测试文件；
- `tui/src/*.test.ts`：14 个 Bun 测试文件。

代表性已读取测试：

| 测试面 | 实际文件 | 覆盖重点 |
|---|---|---|
| SDK facade | `tests/test_nanobot_facade.py` | `Nanobot.from_config`、model/preset 互斥、MCP 组合、`run()`、hooks、session/workspace |
| HTTP API | `tests/test_openai_api.py` | JSON 校验、Bearer auth、health、模型不匹配、SSE、timeout、single-user-message contract |
| API stream/附件 | `tests/test_api_stream.py`, `tests/test_api_attachment.py` | stream 和媒体路径 |
| Session | `tests/session/test_session_store.py`, `test_session_fsync.py`, `test_session_cache.py` | JSONL persistence、fsync、缓存和隔离 |
| Memory/GitStore | `tests/utils/test_gitstore.py`, `tests/utils/test_strip_think.py` | durable 文件版本和历史清洗 |
| Tools | `tests/tools/test_tool_registry.py`, `test_tool_loader.py`, `test_tool_validation.py`, `test_exec_security.py` | discovery、schema、执行和 shell boundary |
| Security | `tests/security/test_workspace_sandbox.py` | workspace/sandbox 约束 |
| WebSocket | `nanobot/channels/websocket/tests/` 多个测试 | protocol boundary、HTTP routes、media、reconnect、integration |
| WebUI | `webui/src/tests/` 的 settings/thread/session/network 等测试 | React UI、API client、事件投影、设置与 WebSocket 状态 |
| TUI | `tui/src/app.test.ts`、protocol/session/menu 等 `*.test.ts` | native TUI 状态、协议、会话、渲染和输入队列 |

### 10.3 项目规定的验证命令（本轮未执行）

```bash
pytest tests/test_openai_api.py::test_function -v
ruff check nanobot/
uv run --no-sync basedpyright
cd webui && bun run test
cd webui && bun run build
cd tui && bun test
```

本轮按任务要求没有安装依赖、启动服务、运行构建或测试；以上是仓库规则/manifest 中的验证入口，不是本轮执行结果。

## 11. 未确认项与风险

以下事项本轮只做静态读取，不能据此宣称已运行或完全验证：

1. **依赖与运行时状态未验证**：没有执行 `uv sync`、pip/Bun 安装、Provider 网络调用、MCP 连接、Gateway 启动或 WebUI 浏览器验收；本机环境是否满足 manifest 版本约束未确认。
2. **当前分支/提交语义未做远程对照**：本档案依据当前工作树；README 的发布说明和源码可能随上游继续变化，不能把 README 版本信息当作运行时探针结果。
3. **完整 API route 清单未逐条展开**：`ws_http.py` 规模较大，本文记录 route 家族和 mutation 映射；若需要契约级 OpenAPI/HTTP 清单，应继续从 dispatcher 和前端 types 逐条生成/核验。
4. **渠道的可用性依赖额外包和配置**：manifest 能被发现不等于对应平台 runtime、凭据、网络或可选依赖已安装；`ChannelManager` 会延迟加载并记录 dependency/runtime errors。
5. **Provider 兼容性是元数据+实现组合**：registry 中的模型/关键词/Thinking/Responses 声明不是每个上游 API 的在线保证；具体模型参数和错误/重试行为需 provider mock 或真实安全配置验证。
6. **持久化并发范围**：Session 和 Memory 有 file lock/async lock/fsync，但本档案未进行跨进程故障注入、断电恢复、共享 workspace 争用或损坏文件演练。
7. **WebUI 构建产物状态未确认**：`pyproject.toml` 声明 `nanobot/web/dist/` 为打包 artifact，但本轮未运行 Bun build，也未把构建产物写入工作树。
8. **TUI 与 Python Gateway 协议细节未完全展开**：已确认 `tui/` 是独立 Bun/OpenTUI 客户端并有 protocol tests；跨进程/跨版本协商仍应以 `tui/src/protocol.ts`、host 和 WebSocket tests 做专项契约审计。
9. **Dream 的长期记忆语义仍有模型参与**：代码提供真实文件嵌入、限定工具、GitStore 和错误安全阀，但 durable 内容本身仍来自模型编辑；生产借鉴时必须保留审计、diff-grounded commit 和 restore 能力。
10. **文档与源码漂移风险**：根 `docs/architecture.md`、README、AGENTS 和本文件都描述架构；本文件是本轮正式档案，但新增入口、渠道、Provider、WebUI route 时需要同步更新。

## 12. 本轮范围说明

- 新增本文件：`ARCHITECTURE.md`。
- 已吸收此前 `细探-nanobot.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
- 未修改任何已有源码、依赖清单、测试、配置、README 或其他源码文档。
- 未安装依赖、未启动服务、未生成构建产物、未提交 Git。

## 13. 第三轮：通用底座映射裁决

本节不是把 nanobot 的 Agent 策略直接搬进平台，而是把当前源码中可复用的契约、资源边界和运行时机制映射到四个职责面。`codegraph_explore` 已按目标根目录尝试，但该仓库没有 `.codegraph/` 索引；以下证据因此全部来自本地当前工作树源码、测试/规则文件和本档案，不能把代码图缺失冒充为图谱证据。

### 13.1 四层职责

```text
L0 通用支持库：值对象/错误契约/Schema/原子文件/锁/取消/进程组/安全边界
        ↓
L1 模块库：会话记忆、Provider 适配、Tool 注册、Channel 插件、任务调度、配置域
        ↓
L2 运行核心：AgentLoop + AgentRunner + Turn 状态机 + 任务监督 + checkpoint/恢复
        ↓
L3 统一网关：Gateway 组合根、HTTP/WS、渠道管理、Cron、配置 watcher、进程 lease/health
        ↓
L4 产品策略：prompt、Skill、Dream、Goal、fallback、工具并发策略、模型选择和用户体验
```

| nanobot 事实 | 通用支持库 | 模块库 | 运行核心 | 统一网关 | 第三轮裁决 |
|---|---|---|---|---|---|
| `AgentLoop` 的 bus 消费、session lock、turn scope、checkpoint、取消和关闭 | `InboundMessage`/`OutboundMessage`、任务句柄、取消/结果契约、资源注册接口 | Context/Session/Memory/Command 等领域模块 | **主落点**：跨会话并发、单会话串行、turn 编排和 teardown | 只负责启动、注入依赖和存活监督 | 吸收“监督与生命周期”，不吸收 prompt/Agent 人设；路径 `nanobot/agent/loop.py` |
| `AgentRunner` 的 Provider→工具→Provider 多轮执行 | `ToolCallRequest`、`LLMResponse`、结构化错误、超时包装 | Provider continuation、Context governance、ToolRegistry | **主落点**：迭代预算、checkpoint、流式事件、取消传播 | 只提供运行配置、日志和 shutdown deadline | 吸收执行骨架；重试、空回复、length recovery 等作为可插拔策略；路径 `agent/runner.py` |
| `ChannelPlugin` manifest、懒导入、`BaseChannel` 收发 | 消息/事件协议、重试/退避、授权和发送结果 | 每个平台的 runtime、connector、依赖和配置 | 不持有第三方 SDK 的业务实现 | **主落点**：`ChannelManager`、outbound dispatcher、启停、状态和 WebSocket/HTTP 组合 | 吸收 manifest/懒加载/统一收发；不把渠道平台语义写进核心；路径 `channels/plugin.py`, `registry.py`, `manager.py` |
| Tool Schema、注册、发现、校验、执行 | JSON Schema 校验、ToolResult、能力注册契约 | 内置工具、MCP 工具、entry-point 插件和各自配置 | 工具调用批次、并发安全门、失败分类和执行上下文 | 网关只暴露管理/调用入口，不直接执行工具 | 吸收“契约先于执行”和 `read_only`/`concurrency_safe` 元数据；不照搬工具集合和模型提示文本；路径 `agent/tools/` |
| Provider 元数据、工厂、fallback、Responses continuation | Provider/Model/Response/usage/timeout 抽象 | 具体 Anthropic/OpenAI/Azure/Bedrock/OAuth/兼容端点适配 | 一次 turn 固定 `ProviderSnapshot`，执行和取消其调用 | 网关负责配置刷新、健康/状态展示、MCP 生命周期 | 吸收 provider contract、snapshot 和错误分类；fallback 顺序、模型目录和推理提示是策略；路径 `providers/base.py`, `registry.py`, `factory.py` |
| asyncio task、subagent、exec session、Cron timer、`to_thread`、子进程 | 任务句柄、取消令牌、进程组、超时和资源 ownership | Subagent/Cron/CLI App 等任务模块 | **主落点**：活跃任务索引、会话级取消、后台任务排空、恢复 checkpoint | Gateway 组合多组长期 task，并在 deadline 内关闭 | 吸收“任务可追踪、可取消、可等待、可回收”；不把 `goal` 当通用任务模型；路径 `agent/loop.py`, `process_runtime.py`, `cron/service.py` |
| Pydantic Config、JSON 文件、环境变量引用、watcher | 原子 JSON 写、校验错误、secret 引用、变更事件 | Agent/Channel/Provider/Tool/Gateway 配置 schema | turn admission 时生成不可变 runtime snapshot | **主落点**：watch/reload、配置路径、服务重启和健康反映 | 吸收原子写和验证边界；不把 nanobot 字段或 camelCase 兼容别名变成平台公共契约；路径 `config/schema.py`, `loader.py`, `watcher.py` |
| Session JSONL、Memory Markdown/history、Cron JSON/action/run records、Gateway state/log | FileLock、临时文件、`fsync`、`os.replace`、目录 fsync、损坏备份 | Session/Memory/Cron/Gateway 各自的存储模块 | checkpoint 和提交边界；取消时部分上下文恢复 | 进程 state/lease/log、跨进程状态和进程身份 | 吸收写入原语和恢复原则；不合并为一个“万能 Agent 数据库”，不同 owner 继续分开；路径 `session/manager.py`, `agent/memory.py`, `cron/service.py`, `gateway/runtime.py` |

### 13.2 单链路装配

目标平台的复用链应保持一条 owner 清晰的调用链，而不是复制四份 Agent：

```text
入口/渠道/SDK/API
  → 网关把输入归一化为 InboundMessage 或 direct request
  → 运行核心建立 TurnContext、session lock、runtime snapshot
  → 模块库提供 Context/Session/Provider/Tool/Delivery 能力
  → 通用支持库提供校验、超时、取消、原子持久化和资源回收
  → Runner 执行 Provider↔Tool 多轮循环
  → 运行核心 checkpoint、保存会话、生成 OutboundMessage/StreamEvent
  → 网关 dispatcher/渠道发送，并记录可观察状态
```

必须保持的 owner 规则：

- 消息 owner 是 `MessageBus`；渠道不能直接调用 AgentRunner，Runner 不能反向持有渠道 SDK。
- turn/session 并发 owner 是 `AgentLoop`；同一 session 的锁和 pending injection queue 不能由每个渠道各维护一份。
- LLM 协议 owner 是 `LLMProvider`/`ProviderSnapshot`；工具调用结果 owner 是 `ToolRegistry`/`ToolResult`；错误不要由每个 Provider 或渠道重新翻译。
- MCP 是应用组合根持有的资源：`Nanobot.from_config()` 创建 `MCPProvider`，SDK/Gateway 连接和 `aclose()`；源码明确指出 AgentLoop 不拥有 MCP 生命周期（`nanobot/nanobot.py:132-140,193-199`；Gateway 的 `_run_agent()` 在 `cli/gateway_runtime.py:863-868` 关闭它）。
- 持久化按事实域分 owner：Session 文件保存会话/私有 Provider state，Memory 保存 durable 文件和 archive，Cron 保存 job/action/run，Gateway 保存进程 state/log；禁止跨域旁路写。

## 14. AgentLoop/Runner 的可复用内核与不可照搬策略

### 14.1 可复用内核

1. **Admission snapshot**：`ModelRuntimeResolver` 在 turn admission 时解析不可变 runtime；运行期间不因配置文件变化而半途切换 Provider/model。配置 watcher 只使后续 admission 失效并重建（`cli/gateway_runtime.py:860-883`）。
2. **会话级串行、会话间并发**：`AgentLoop._dispatch()` 以 session lock 保证同一会话串行，同时用 `_active_tasks[session_key]` 追踪跨会话任务（`agent/loop.py:1323-1345,1316-1319`）。这是通用运行核心能力。
3. **显式阶段依赖**：`TurnContext.require_runtime()` 要求 BUILD 已完成，`require_session()` 要求 RESTORE 已完成（`agent/loop.py:168-179`）。底座可把这种前置条件转为状态机/契约门，而不必复制 nanobot 的上下文字段。
4. **checkpoint-first**：工具执行前记录 `awaiting_tools`，工具完成后记录 `tools_completed`，取消时从 runtime checkpoint 恢复部分上下文并保存（`agent/runner.py:527-537,599-613`; `agent/loop.py:1359-1396`）。可复用为“意图/中间结果先落账，恢复再决定完成或回滚”的通用原则。
5. **边界内失败不等于宿主失败**：普通工具异常可包装成 `ToolResult.error`；SSRF/工作区越界作为不可绕过的安全边界反馈给模型但不拖垮整个 Agent 进程（`agent/runner.py:1507-1553,1617-1651`）。公共底座应统一错误码/可重试性，不应统一所有业务提示。
6. **流式边界可观测**：Provider 返回 `LLMResponse`，Runner 负责 delta、reasoning、tool event、TTFT/generation telemetry，渠道只消费 `StreamDeltaEvent`/`StreamEndEvent`。这适合抽成事件契约，不能把某平台卡片更新逻辑放进 Runner。
7. **失败安全的关闭**：AgentLoop 的 `aclose()` 用 close lock 串行化，取消 active tasks、等待 background tasks，再关闭 subagents 和 exec sessions，且每个 cleanup 独立收集错误（`agent/loop.py:1439-1494`）。这是通用资源监督模板。

### 14.2 不应照搬的 Agent 策略

| nanobot 策略 | 为什么不应成为公共底座 | 迁移方式 |
|---|---|---|
| `max_tool_iterations=200`、空回复重试 2 次、length recovery 3 次、注入循环 5 次 | 是当前产品对个人 Agent 成本/体验的选择，不能假定所有工作流相同 | 作为 `RunPolicy`/策略模块字段，由产品或租户显式配置 |
| Provider transient marker、429/配额判断、retry-after 文本解析 | 上游协议和业务计费语义不稳定，文本 marker 会漂移 | 保留 Provider 适配层错误结构，公共层只认 `retryable/deadline/cancelled` 等稳定字段 |
| sustained Goal 使 `llm_timeout_s=0` | `goal_state` 是 nanobot 特有的长期任务语义；关闭 wall timeout 可能造成资源无限占用（`session/goal_state.py:119-136`） | 通用底座仍强制硬截止/租约；Goal 只能申请更长预算并接受宿主上限 |
| Dream 让模型编辑 `SOUL.md`/`USER.md`/`MEMORY.md`，成功才推进 cursor | 这是个人 Agent 的记忆产品策略，模型写 durable 事实有语义和审计风险 | 只复用 cursor、原子写、diff/restore、错误不推进等治理；内容策略留在模块/产品层 |
| unified session、`channel:chat_id`、`cron` 的 session-bound turn | 是个人多设备/渠道路由模型，其他系统可能按 tenant/job/thread 分区 | 抽象 `SessionKey`/route policy 接口，不固定字符串拼接规则 |
| Tool 名称、prompt 模板、Skills、subagent announce 文本 | 直接决定 Agent 行为和提示注入面，复制会把上层人设带入底座 | 仅复用 schema、权限、执行、审计和资源治理；提示材料版本化为产品制品 |
| `concurrent_tools` 仅依据 `read_only`/`exclusive` | 只读并不自动代表线程安全、幂等或外部限流安全 | 公共能力需声明并由 provider/工具契约验证 `concurrency`, `idempotency`, `side_effects`, `rate_limit` |
| “模型错误占位消息”“SSRF 给模型的英文说明”等文案 | 属于对话体验和安全教育文案，不是底座错误协议 | 公共层输出结构化错误和证据；渠道/Agent 策略决定展示文本 |

## 15. 状态机、资源释放与失败矩阵

### 15.1 Turn/Runner 状态机

nanobot 现有源码以 `TurnKind`、`stop_reason`、checkpoint `phase` 和任务集合表达状态，尚未提供一个独立的公共状态枚举。下面是**基于真实字段的底座映射**，不是声称源码已经实现了同名状态机：

```text
ADMITTED
  → BUILD（runtime/context/turn scope 建立）
  → RESTORE（session/history/provider state 恢复）
  → EXECUTING（Runner 请求模型）
  → AWAITING_TOOLS（assistant tool calls 已 checkpoint）
  → TOOLS_COMPLETED（工具结果已 checkpoint）
  → EXECUTING（继续下一轮）
  → FINALIZING（final/length/empty/error 处理）
  → COMMITTING（session/delivery/checkpoint 保存）
  → COMPLETED

任意可取消阶段 → CANCELLING → CANCELLED（保存可恢复部分上下文，排空并重投 pending）
任意业务异常 → FAILED（delivery.fail；按策略保留错误占位/重试）
宿主崩溃 → UNKNOWN/ORPHANED（由下次启动读取 checkpoint、session、进程身份后恢复或标记）
```

源码对应关系：

- `checkpoint.phase` 至少有 `awaiting_tools`、`tools_completed`、`final_response`；`AgentRunResult.stop_reason` 有 `completed`、`max_iterations`、`error`、`tool_error`、`empty_final_response`，取消通过 `asyncio.CancelledError` 传播。
- 取消不是静默丢弃：`_dispatch()` 先 abort stream，再尝试恢复 runtime checkpoint、清理 pending user turn、`sessions.save()`，随后 `finally` 从 pending queue 取出消息重新 publish 到 bus（`agent/loop.py:1359-1433`）。
- `AgentRunner.run()` 对取消设置 hook context 的 `stop_reason="cancelled"` 后重新抛出；普通异常执行 `on_error`，最终无论成功/失败都执行 `on_finally`（`agent/runner.py:372-418`）。

### 15.2 资源 ownership 与释放表

| 资源 | 创建/持有者 | 正常释放 | 失败/超时/取消 | 崩溃后处理与风险 |
|---|---|---|---|---|
| `asyncio.Task`：turn/后台/dispatch | AgentLoop/Gateway | `gather` 或 done callback 移除 | cancel 后 await；Gateway 有 15s 等待和二次 cancel | 进程退出由 event loop 回收；若第三方吞取消只能 bounded abandon，需进程级兜底 |
| session lock/pending queue | AgentLoop 每 session | `_dispatch` finally 移除 queue、重投余量 | 取消/异常同一 finally；队列满时降级为新 bus task | 宿主崩溃不保留内存队列；checkpoint 可恢复已完成工具，未落账消息可能丢失 |
| turn scopes/ContextVar/file state | AgentLoop | `ExitStack.close` + reset token | `_run_agent_loop` finally 和命令执行 finally | 崩溃由进程隔离；不得把 ContextVar 当跨线程/跨进程状态 |
| Provider client/MCP connection | 组合根/SKD/Gateway；Runner 借用 | MCP `aclose()`；Provider 由 owner 关闭（具体 SDK 是否有 close 需逐实现核验） | close 阶段 bounded wait，取消仍进入 finally | 外部 socket/SDK 残留是未充分验证风险；需 provider-specific `AsyncExitStack`/连接探针 |
| subprocess：shell/exec/Gateway | ExecSessionManager/ManagedProcessRuntime | `stop`/`close_all`；进程组 terminate | `SIGTERM` 等待，超时 `SIGKILL`；独立 session/进程组 | state file 带 pid+identity；PID 复用/陈旧状态检测，不能仅凭 pid 杀进程（`process_runtime.py:158-194,205-242,334-358`） |
| session JSONL | JsonlSessionStore | FileLock；临时文件写完后 `os.replace`；可选 fsync+目录 fsync | 写失败删除 tmp，不替换旧文件；读坏行走 repair | workspace namespace、`.workspace` marker、`.corrupt`/repair 需专项注入验证；公共底座可复用原子写，不复用路径命名 |
| Cron jobs/action/runs | CronService | timer cancel；`jobs.json` 原子写；action journal 合并 | `_store_dirty` 保留内存快照；解析坏文件改名 `.corrupt-*` 且拒绝以空列表覆盖 | 可恢复但跨进程/重复副作用仍需幂等 key；`CronService.stop()` 是同步取消 timer，不等待其 task，属于待核清理缺口 |
| Channel runtime/dispatcher | ChannelManager | dispatcher cancel/await；各 channel `stop()`，再 cancel start task | start 错误记录为 failed；send 使用可配置有限退避且传播取消 | 第三方 SDK 吞取消时由 Gateway 15s deadline 兜底；各渠道内部 task 是否全部挂到 stop contract 需逐渠道复核 |
| 文件/媒体临时对象 | 具体 Tool/Channel | 由创建模块 finally 关闭/替换 | 取消必须执行 `finally`；共享支持库应提供 temp scope | 静态档案未证明所有附件/上传临时文件 crash cleanup；不得宣称无泄漏 |

### 15.3 失败、超时、取消、崩溃矩阵

| 场景 | 当前真实语义 | 通用底座可吸收 | 不能直接外推/待核 |
|---|---|---|---|
| Provider 瞬态 429/5xx/连接/timeout | `LLMProvider._run_with_retry()` 依据结构化字段/marker、retry-after 和模式退避；流式已有内容后有特殊 segment recovery | retry policy 接口、deadline、attempt evidence、取消传播 | 具体 marker、持久 retry 上限和配额文案是 Provider/产品策略 |
| LLM wall timeout/stream idle | Runner 默认 `NANOBOT_LLM_TIMEOUT_S=300`，流式 outer timeout 至少 300 或普通 timeout×2；Provider 有 `NANOBOT_STREAM_IDLE_TIMEOUT_S` 默认 90（`runner.py:907-1075`, `providers/base.py:29-49`） | 分层 deadline：请求/流空闲/turn/宿主 shutdown | Goal 可以把 wall timeout 设 0；公共底座不应允许无限无租约执行 |
| 工具参数错/工具异常 | Schema cast+validate；ToolRegistry 统一错误；`fail_on_tool_error` 决定 turn 是否终止 | schema、结构化错误、可重试性、调用证据 | `Error: ...` 文本和模型 hint 属 Agent 策略 |
| SSRF/工作区越界 | SSRF 不可绕过但转为非致命 tool error；工作区重复违规会升级提示 | 安全边界必须在能力调用前检查，错误不可伪造成成功 | 越界次数、提示文本、是否继续是产品策略 |
| 用户 `/stop`/任务取消 | cancel session active tasks、subagents、exec sessions；保存 checkpoint/部分历史；重投 pending | cancellation token、owner-index、checkpoint、cancel→await→release | `Future`/子进程/第三方 SDK 是否真正终止需能力实现证明；Python 线程不能被强杀 |
| Channel 启动/发送失败 | start 记录 channel error/status；send 默认 1+配置次数、1/2/4s 退避；非 retryable error 直接返回 | delivery result、退避、失败状态、幂等/去重 | 各平台错误是否可重试由 channel override；不能强行统一 |
| Session/Cron 文件损坏 | Session 尝试逐行 repair；Cron 备份 corrupt 文件并拒绝空写；两者均有原子写 | 原子提交、旧快照保留、损坏不覆盖、repair evidence | 断电/跨进程强杀、重复副作用尚未本轮真实注入 |
| Gateway/宿主崩溃 | Gateway state 记录 pid/identity；stale state 清理；POSIX 进程组 TERM→KILL；启动任务失败被 `gather(return_exceptions=True)` 收集；外层打印 crashed | 进程身份、租约、进程组、启动/停止状态机、bounded shutdown | 自动重启策略和“未完成 turn”跨进程恢复不是完整事实；不能把 checkpoint 等同于 exactly-once |
| 配置 JSON 错误/热改 | `load_config` 区分 JSON/UTF-8/schema/env 错误；`save_config` 临时文件+原子替换；watcher 只通知刷新 | 配置版本、原子写、错误分层、变更事件 | watcher 回调不是事务；正在运行 turn 使用 snapshot，后续 turn 才可见 |

## 16. 任务/线程模型映射

nanobot 主要是 asyncio 单事件循环，不是一个通用线程池 Agent：

- 常驻 Gateway 以命名 asyncio tasks 组合 AgentLoop、ChannelManager、Cron、local trigger、config watcher、health server、client monitor；`_close_gateway_runtime()` 先停渠道，再取消/等待 runtime tasks，最后 bounded close Agent 和 MCP（`cli/gateway_runtime.py:237-287,878-965`）。
- AgentLoop 为每条消息创建 `_dispatch(msg)` task；`_active_tasks` 按有效 session key索引，session lock 串行同一会话；`schedule_background()` 另有可排空的 `_background_tasks` 集合。
- `AgentRunner` 内工具可按 batch 并发，但只有 `Tool.concurrency_safe` 才能进入并发 batch；否则串行。该判断是“允许并发”的提示，不是底层线程安全证明。
- `asyncio.to_thread` 用于阻塞文件/SDK/HTTP 调用；取消 awaiter 不等于杀掉底层线程。需要硬取消的 shell/Gateway/外部任务应走独立 process group，而不是把 `to_thread` 当强制终止机制。
- `subprocess.Popen` 的 Gateway 使用 `start_new_session=True`（Windows 用新进程组），停止按 PID identity 校验后杀整个进程组；这是可复用的硬资源边界。

通用支持库应提供：`TaskHandle(owner, parent, deadline, cancel, wait, release)`、session/tenant 级 owner index、shutdown barrier、process-group supervisor、状态/证据记录和 bounded wait。模块库再定义 Cron、Subagent、长期目标等任务语义；运行核心只编排，不把每一种任务写成独立全局线程系统；网关只负责常驻任务的装配和退出顺序。

## 17. 复用资源治理清单与缺口

### 17.1 可直接吸收的治理模式

- **原子文件提交**：临时文件→flush/fsync→`os.replace`→父目录 fsync；配置、Session、Cron 三处已有同类实现，可下沉一份实现但保留各域 serializer/owner。
- **文件锁分层**：Session migration lock 与 session-files lock 分开；Cron action lock 与内存 execution 计数分开；Gateway transition/lifecycle lock 分开。锁的作用域和超时必须写在契约里，禁止一个全局锁包住外部网络调用。
- **资源释放在 finally**：turn scopes、ContextVar token、cron context、channel send/stream abort、MCP close 都应有 finally；清理步骤互相独立，先释放可阻塞/外部资源，再释放索引和临时状态。
- **取消可见且可等待**：取消必须记录 terminal outcome，调用 `cancel()` 后 await；不能只删除 task 引用。对于无法硬取消的线程标记 `abandoned`，由宿主/进程隔离兜底。
- **失败不覆盖好快照**：Cron `_store_dirty` 和 corrupt backup 说明“内存已有副作用但落盘失败”时应保留 exact snapshot，不能 reload 旧状态再重复执行；Session 写失败保留旧目标文件。
- **进程身份而非 PID**：state file 必须包含 pid、启动时间和平台 identity；停止前核对 identity，陈旧 state 只清理记录不杀不相干进程。
- **单一 cleanup owner**：AgentLoop close lock 防 `run()` finally 与应用 shutdown 并发清理；Gateway 作为宿主拥有最终 close deadline；模块不自行关闭不属于它的 Provider/MCP/Channel。

### 17.2 不足与后续验证输入

1. 当前静态研究没有做断电、SIGKILL、跨进程 session/Cron 争用、第三方 SDK 吞取消、外部 Provider socket 泄漏或所有渠道 runtime 的资源审计；这些只能标为待核。
2. `CronService.stop()` 直接 cancel timer task 且没有 async await；若 tick 已进入 job 执行，停止语义依赖外部调用者，不应把它当作完整 graceful stop。
3. `asyncio.gather(*tasks, return_exceptions=True)` 收集常驻任务异常，但没有统一把每个 task 的异常投影到持久状态；网关打印 crash 不等于任务级恢复完成。
4. Runner 的 `asyncio.wait_for()` 能取消当前 awaitable，但不能保证第三方 SDK 已关闭底层连接；Provider contract 需要增加 `aclose`/abort 或隔离进程能力。
5. Session repair 会跳过坏行并继续读，适合尽量保数据，但没有本轮证明 repair 后是否自动重写/留审计记录；公共库应把“修复读取”与“覆盖写回”分开。
6. `ToolRegistry` 的注册冲突是覆盖并记录 warning，外部插件与内置工具的优先级带兼容包装；平台公共注册表不应默认允许静默覆盖，应要求 owner/version/replace policy。

## 18. L0-L4 交付边界与迁移顺序

| 等级 | 应交付的公共能力 | nanobot 可吸收事实 | 明确不迁移 |
|---|---|---|---|
| **L0 原子支持库** | `Result/Error`、JSON Schema 校验、消息值对象、取消/超时值对象、原子文件写、目录 fsync、FileLock、进程组、路径/SSRF 基础检查、资源 owner/lease 接口 | `ToolResult`、`LLMResponse` 字段、`InboundMessage`/`OutboundMessage`、Session/Cron 原子写模式、PID identity | Prompt、模型重试 marker、具体工具/渠道、Agent 人设 |
| **L1 模块库** | Session/Memory、Provider adapter/registry、Tool registry/loader、Channel manifest/runtime adapter、Cron/job/run record、Config schema/loader、Delivery/event projection | 当前目录边界和各自持久化 owner；Provider continuation sidecar；channel lazy import | 把所有模块压成一个 AgentService；把 Memory/Dream/Goal 当数据库内核 |
| **L2 运行核心** | TurnContext、session lock、admission snapshot、AgentRunner protocol、task supervisor、checkpoint/recovery、bounded teardown、跨模块错误映射 | `AgentLoop`、`AgentRunner` 的骨架，取消/恢复/stream lifecycle | nanobot 的 max iteration、Goal 无限 timeout、Dream prompt、工具提示和 fallback 具体值 |
| **L3 网关** | 组合根、HTTP/WS/API、渠道启停/dispatcher、Cron/trigger 常驻任务、config watcher、health、process lease/state/log、shutdown barrier | `GatewayRuntime`/`ChannelManager`/CLI gateway 任务编排和进程组管理 | 让网关直接写 Session/Memory，或让渠道直调模型/工具 |
| **L4 产品 Agent 策略** | 产品/租户可配置的 prompts、Skills、记忆提炼、Goal、subagent、模型路由、预算、用户交互文案、合规策略 | 只作为待迁移策略样例和风险样本 | **不进入通用底座**；不可因 nanobot 已实现就判定平台应复制 |

推荐装配顺序：先冻结 L0 资源/错误/持久化契约，再以 L1 模块适配一个 Provider、一个 Tool、一个 Channel 和一种 Session；随后在 L2 做真实取消/超时/checkpoint；L3 只做一个网关组合根和单一 shutdown owner；最后把 L4 策略以版本化模块接入。没有资源 owner、取消、超时和验收契约时，不应从 nanobot 复制 AgentLoop。

## 19. 第三轮现有能力命中、缺口与裁决

| 能力 | 证据命中 | 底座落点 | 裁决 |
|---|---|---|---|
| 消息值对象、bus 解耦、stream event | `bus/events.py`, `bus/queue.py`, `channels/manager.py` | L0 消息/事件契约 + L3 dispatcher | **吸收**：先统一事件 schema，再接渠道 |
| Session JSONL 的 namespace、FileLock、atomic/fsync、repair | `session/manager.py:563-630,1050-1269` | L0 文件原语 + L1 Session 模块 | **吸收**：吸收原子写/锁/repair 原则，不复用文件布局 |
| Provider response/continuation/retry/timeout | `providers/base.py:156-280,860-1199`, `agent/runner.py:900-1134` | L0 response/error + L1 provider adapter + L2 request supervisor | **吸收/升级**：结构化错误可复用；retry marker 和 fallback 策略待核 |
| Tool schema/registry/lazy discovery/concurrency metadata | `agent/tools/base.py:159-228`, `registry.py:19-201`, `loader.py:26-124` | L0 Schema/Result + L1 capability module + L2 execution supervisor | **吸收**：禁止静默覆盖、必须声明副作用/幂等/资源 |
| Channel manifest/lazy runtime/启停/发送退避 | `channels/plugin.py:22-179`, `registry.py:30-94`, `manager.py:360-406,577-976` | L1 channel adapter + L3 channel manager | **吸收**：manifest 懒加载和统一重试；平台 SDK 只在适配层 |
| AgentLoop session lock、checkpoint、cancel、close | `agent/loop.py:866-887,1323-1494` | L2 runtime core | **升级后吸收**：补统一状态/任务证据和 hard deadline |
| Cron JSON/action journal/dirty snapshot/腐坏备份 | `cron/service.py:216-256,351-565` | L1 Cron module + L3 scheduler | **吸收/待核**：保留不覆盖原则；补 async stop、幂等副作用和 crash 注入 |
| Gateway process identity/lease/TERM→KILL | `process_runtime.py:115-194,205-242,334-358`; `gateway/runtime.py` | L0 process supervisor + L3 gateway | **吸收**：进程身份和进程组；补跨平台实测 |
| Dream/Goal/subagent/模型 fallback/提示模板 | `agent/memory.py`, `session/goal_state.py`, `agent/subagent.py`, `providers/factory.py` | L4 策略模块 | **隔离**：只借鉴治理接口，不进公共底座 |
| 代码图证据 | 目标仓没有 `.codegraph/`，`codegraph_explore` 明确返回未索引 | 不作为架构事实证据 | **待核**：若需要图谱，用户另行初始化；本轮不伪造图证据 |

## 20. 本轮证据、验证边界与剩余风险

- 本轮实际修改范围只允许且只修改根 `ARCHITECTURE.md`；未修改 nanobot 源码、依赖、配置、测试、README、旧细探或 Git。
- 已读取正式 `ARCHITECTURE.md`、根 `AGENTS.md` 及 AgentLoop/Runner、ChannelPlugin/Registry/Manager/BaseChannel、Tool Base/Registry/Loader、Provider Base/Registry/Factory、Session Store、Config loader/schema/watcher、Cron、Gateway/process runtime、SDK facade 等源码。
- 当前工作树搜索不到 `细探-nanobot.md`；正式文档仍有三处旧引用并称其存在/已吸收。本轮不删除任何文件；该文档引用与现场文件不一致，列为文档漂移风险，不能声称本轮读取了不存在的旧细探。
- 本轮没有安装依赖、启动服务、调用真实 Provider/渠道/MCP、做跨进程故障注入或运行全量测试；因此“源码存在”与“运行通过”严格分开。
- 预期验证命令仍以第 10 节为准；本轮至少使用 `git diff --check` 检查 Markdown 空白，并检查工作树只有 `ARCHITECTURE.md` 变化。未执行的 Python/WebUI/TUI 命令不能写成通过。
- 剩余风险：第三方 SDK 的 close/abort 语义、所有渠道子任务的 stop 完整性、Cron timer stop race、线程取消、Provider socket 泄漏、强杀后 exactly-once、Session repair 重写审计、配置 watcher 回调事务性均未被本轮真实运行证明。
