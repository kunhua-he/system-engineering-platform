# Letta 架构取证

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 当前工作树：letta-ai/letta @ main                                    │
│ 87fd37a  chore: archive the legacy server repository                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 项目落地页层                                                          │
│ README.md                                                             │
│   - 项目一句话定位                                                    │
│   - 安装/运行命令（指向外部 @letta-ai/letta-code）                   │
│   - 桌面端、Web、Channels、Agent SDK、Cloud 链接                     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 文档链接/使用指引
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 仓库治理与元数据层                                                    │
│ AGENTS.md / CONTRIBUTING.md / SECURITY.md / PRIVACY.md / TERMS.md     │
│ CITATION.cff / LICENSE / .github/ISSUE_TEMPLATE/config.yml             │
│   - 声明 main 不再承载运行时代码                                      │
│   - 将当前实现导向 letta-ai/letta-code                               │
│   - 将旧 V1 server 标为 archive 中的历史代码                         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 当前工作树不存在的运行时层                                            │
│ Agent 循环 / 记忆模型 / ORM / 持久化 / LLM provider / REST / WS / 测试 │
│ 不存在 letta/、src/、server/、api/、cli/、sdk/、tests/ 等实现目录      │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ README 指向外部项目
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 外部当前实现（不在本仓库，本文不推断其内部架构）                      │
│ letta-ai/letta-code                                                   │
│   npm install -g @letta-ai/letta-code → letta                         │
│   letta server                                                        │
│   桌面端 / Web / Channels / Letta Agent SDK / Letta Cloud              │
└──────────────────────────────────────────────────────────────────────┘

历史边界：archive 分支的退役 V1 Python server 只作为历史边界被记录；它不是当前工作树源码，也不作为当前 Letta 的架构或行为证据。
```

# Letta 当前仓库架构说明

## 1. 项目定位

本地检视的仓库是 `letta-ai/letta` 的 `main` 分支，当前提交为 `87fd37a`（提交信息：`chore: archive the legacy server repository (#3430)`）。根据当前 `README.md` 和 `AGENTS.md`，该仓库已经是 Letta 项目的 landing page：

- README 将产品描述为“Build stateful agents with memory that can learn and improve over time”。
- README 明确说当前源代码位于 `letta-ai/letta-code`，并说明本仓库的 `main` 仅作为项目落地页。
- AGENTS.md 明确要求不要把本仓库作为工作的 Letta 实现；旧 V1 server 仅保存在 `archive` 分支，且不受支持。
- 当前实现、终端 UI、App Server、channels 和 runtime 的工作入口均被导向 `letta-ai/letta-code`。

因此，本文件描述的“真实架构”不是一个本地 Agent runtime 的模块架构，而是一个**项目入口与治理边界仓库**：本地仓库负责定位、迁移指引、历史边界、许可证/隐私/安全/贡献说明；运行时实现已被移出本仓库。

## 2. 真实分层与职责

### 2.1 项目落地页层

- `README.md`
  - 给出产品定位。
  - 指向当前实现仓库 `letta-ai/letta-code`。
  - 给出 npm 安装命令、交互式终端 UI 命令和 App Server 命令。
  - 列出桌面应用、浏览器端、Slack/Telegram/Discord/custom channels、Agent SDK 和 Letta Cloud 等外部产品入口。
- `.github/ISSUE_TEMPLATE/config.yml`
  - 当前树中唯一的 GitHub issue 模板配置文件；没有本地业务运行代码。

### 2.2 仓库治理与项目元数据层

- `AGENTS.md`
  - 是当前仓库最强的架构边界说明：main 是 landing page；archive 是退役 V1 的历史参考；当前开发必须转到 `letta-ai/letta-code`。
  - 明确禁止将旧分支、旧 Python 包或旧 Docker 镜像用于生产、实验、基准、比较、集成或复制。
- `CONTRIBUTING.md`
  - 说明本仓库已归档，不接受退役 V1 server 的改动；当前开发转到 `letta-ai/letta-code`。
- `SECURITY.md`
  - 说明 archive 中的 legacy V1 server 无安全更新，不应投入生产；当前产品漏洞按邮件渠道报告。
- `PRIVACY.md`
  - 提供服务隐私说明，包括遥测退出配置 `telemetry_disabled = True`；它是政策文档，不是本地运行时配置实现。
- `TERMS.md`
  - 提供服务条款。
- `LICENSE`
  - 提供许可证文本。
- `CITATION.cff`
  - 提供 Letta 的引用元数据，引用标题为 `MemGPT: Towards LLMs as Operating Systems`。

## 3. 核心数据流（当前工作树可确认范围）

当前树不存在 Agent、数据库或 API 实现，因此可从源码确认的数据流只有“文档指引流”：

1. 用户阅读 `README.md`，获得 Letta 的产品定位。
2. 用户根据 README 的安装命令安装外部 npm 包 `@letta-ai/letta-code`。
3. 用户通过外部 CLI `letta` 启动交互式终端 UI，或通过 `letta server` 启动 App Server；这两个命令的实现不在当前树。
4. 用户通过 README 链接进入外部桌面端、Web、channels、Agent SDK 或 Letta Cloud；其请求、Agent 状态、长期记忆、模型调用和持久化数据流无法由当前仓库源码确认。
5. 若用户试图从旧 V1 代码推断当前行为，`AGENTS.md` 将其阻断并要求迁移到当前实现。

此前的 `细探-Letta.md` 记录了旧 archive 分支 V1 server 的历史探索，包括 Agent 循环、三层记忆、工具执行、摘要、REST/WS 等内容；这些历史内容不并入当前实现的数据流结论。当前文档仅保留这一历史边界，不保留旧 V1 的平行架构说明。

## 4. 关键类、函数、数据模型及相对路径

### 4.1 当前树中可确认的实现入口

没有可确认的运行时类、函数或数据模型。当前 HEAD 的递归文件清单只有 9 个受 Git 跟踪文件：

```text
.github/ISSUE_TEMPLATE/config.yml
AGENTS.md
CITATION.cff
CONTRIBUTING.md
LICENSE
PRIVACY.md
README.md
SECURITY.md
TERMS.md
```

因此，下列路径在当前工作树中均不存在：

- `letta/main.py` 或其他 CLI 入口
- `letta/agents/`、Agent 循环及 step 状态机
- `letta/schemas/`、Block/Memory/Message 等数据模型
- `letta/orm/`、数据库映射和迁移
- `letta/server/`、REST/WebSocket 网关
- `letta/functions/`、工具契约与工具执行器
- `tests/`、`test/` 或其他测试实现

### 4.2 已有细探文档中的历史引用（非当前实现证据）

`细探-Letta.md`（本地已有、未删除）引用了 archive 分支历史路径，例如 `letta/main.py`、`letta/agents/letta_agent_v3.py`、`letta/schemas/block.py`、`letta/schemas/memory.py`、`letta/server/rest_api/` 和 `letta/services/summarizer/`，并记录了历史 V1 的 `Block`、`Memory`、消息/步骤/运行账本等概念。

这些路径不属于当前 HEAD 的文件树，也未被本次文档当作当前源码读取结果。若要形成退役 V1 的历史架构报告，应另行明确提出“历史 archive 分支分析”并遵守 AGENTS.md 的只读与历史标注要求；本文件不把它们升级为当前 Letta 的类、函数或数据模型。

## 5. API / CLI / SDK 入口

### 当前仓库能确认的入口

当前仓库没有本地 API、CLI 或 SDK 实现。README 只提供外部入口指引：

- CLI 安装：`npm install -g @letta-ai/letta-code`
- 交互式终端 UI：`letta`
- App Server：`letta server`
- 桌面应用：README 链接到 Letta 文档中的 desktop app
- Web：`chat.letta.com`
- Channels：Slack、Telegram、Discord 和 custom channels
- SDK：Letta Agent SDK（TypeScript applications）
- Cloud：Letta Cloud

这些入口的命令解析、HTTP/WS 路由、SDK 类型和请求协议均不在当前仓库，不能从本地源码补写。

## 6. 技术栈与依赖

### 6.1 当前工作树实际情况

- 文件类型：Markdown、YAML 配置、CFF 元数据、许可证/政策文本。
- 没有 `pyproject.toml`、`setup.py`、`setup.cfg`、`requirements.txt`。
- 没有 `package.json`、`pnpm-lock.yaml`、`yarn.lock` 或 `package-lock.json`。
- 也没有 `Cargo.toml`、`go.mod`、`Makefile`、`Dockerfile`、`compose.yaml` 或 `docker-compose.yml`。
- 因而当前仓库没有可列出的本地运行时依赖清单，也不能据此声称本地项目是 Python、TypeScript 或其他语言实现。

### 6.2 README 能确认的外部技术入口

README 只明确给出 npm 包名 `@letta-ai/letta-code`，并将当前源代码和开发/部署说明指向 `letta-ai/letta-code` 与 `docs.letta.com`。这能确认“当前使用入口在外部 npm/Letta Code 项目”，但不能确认该外部项目的完整依赖版本、内部模块分层或数据模型。

## 7. 架构判断

1. **当前仓库不是运行时仓库。** HEAD 的文件树只有项目落地页和治理/元数据文件，没有 Agent、记忆、模型、存储、服务或测试代码。
2. **README 是迁移路由，不是 API 规格。** 其中的 `letta`、`letta server`、Agent SDK 等是对外部当前实现的入口说明，不能从本地代码推导具体协议。
3. **AGENTS.md 是架构安全边界。** 它明确阻止把 archive 的退役 V1 当作当前实现，并要求新开发使用 `letta-ai/letta-code`。
4. **已有细探文档是历史研究资料。** 它对 V1 机制的记录可作为后续历史阅读导航，但不应与当前 main 的真实代码结构混合。
5. **本次新增的 ARCHITECTURE.md 只能做“仓库现状架构”记录。** 在没有单独取得并读取 `letta-ai/letta-code` 工作树的前提下，不能虚构当前 runtime 的类、函数、依赖、API 或测试结论。

## 8. 未确认项与后续边界

以下问题无法由当前仓库确认：

- `letta-ai/letta-code` 的实际目录、语言版本、依赖清单和构建系统。
- 当前 Agent harness 的核心类、Agent step/turn 状态机和模型 provider 抽象。
- 当前长期记忆的数据模型、存储后端、索引/检索策略和迁移机制。
- 当前 App Server 的 REST/WebSocket 路由、鉴权、流式协议和错误模型。
- 当前 `letta` CLI 的命令注册、配置加载和 server 启动链路。
- 当前 Letta Agent SDK 的包结构、类型定义、请求协议和测试覆盖。
- 当前实现的 provider、模型路由、遥测与安全隔离细节。

若要继续分析这些内容，必须切换到并实际读取 `letta-ai/letta-code` 的本地源码（或用户明确授权的对应源码副本）；不能以本仓库的 archive 历史内容替代当前实现。

## 9. 本次审计依据

本文件结论来自以下实际读取/检查结果：

- 本仓库 `README.md`。
- 本仓库 `AGENTS.md`。
- 旧 `细探-Letta.md` 的内容已人工核对；仅保留其“退役 V1、不可代表当前实现”的边界结论。
- 本仓库 `CONTRIBUTING.md`、`SECURITY.md`、`PRIVACY.md`、`CITATION.cff`。
- 参考库根导航 `/Users/hekunhua/Documents/Agent/github 源码参考/README_先看这里.md`。
- `git ls-tree -r --name-only HEAD` 得到的当前 HEAD 9 个文件清单。
- 对依赖清单、核心入口、数据模型目录和测试目录的实际存在性检查：均未发现。

本文件已吸收此前 `细探-Letta.md` 的历史边界结论；后续只维护本文件，旧细探笔记不再作为独立事实源。本次未安装依赖、未运行服务、未修改已有源码或提交 Git。

---

# 10. 后续：当前 Letta Code 到通用底座的映射（2026-08-21）

## 10.1 证据边界与降级声明

当前核对先核对了本地目标树、`ARCHITECTURE.md`、`AGENTS.md`、Git 引用和旧细探路径，结果必须分层记录：

| 证据项 | 真实结果 | 证据等级与影响 |
|---|---|---|
| 本地目标项目 | `/Users/hekunhua/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Letta`，`main`，HEAD `87fd37a` | L0；这里只是 landing page，不能作为 Agent runtime 源码 |
| 本地运行时代码 | 不存在 `letta/`、`src/`、`server/`、`api/`、`tests/` 等实现目录；Git HEAD 只有 9 个受跟踪文件 | L0；本地目标树不能验证 Agent、数据库、队列或服务端实现 |
| 代码图 | Letta 根目录当前存在独立 `.codegraph/`；本轮用目标目录内 CodeGraph CLI 状态核对 | 图谱仅作定位辅助；当前核对没有把索引状态冒充运行验证 |
| `project_context` | 专属 MCP 返回错误绑定到华世王镞_v3，不是 Letta | MCP 身份/最近成功验证均作废，不用于 Letta 证据 |
| 旧细探 | 目标目录、上级 `02_长期记忆与记忆操作系统` 和参考库中均未找到 `细探-Letta.md`；本地 `ARCHITECTURE.md` 只能证明它曾被引用过 | 不能声称当前核对读取了不存在的旧文件；不删除、不重建、不把聊天记忆当细探 |
| 当前实现入口 | 目标 `README.md`/`AGENTS.md` 指向外部 `letta-ai/letta-code` | 仅在明确“外部当前实现证据”标签下使用 |
| 外部当前源码快照 | 只读取得 `letta-ai/letta-code` `main`，`git ls-remote` 返回 `4f2d0d13496117e8fbf584aa24bea595c464f11b`；读取了 `src/agent/`、`src/backend/`、`src/queue/`、`src/tools/`、`src/types/`、`src/app-server-client.ts` 等公开源码 | L1 源码证据，但不改变本地目标树的“非运行时仓库”结论；该外部仓库未被本地 MCP/代码图绑定 |

因此，下面的映射是“本地 Letta landing page 的边界 + 当前 `letta-code` 公开源码的只读补充”两层证据。凡是当前 `letta-code` 没有直接展示的服务端内部数据库、远端队列、租约或回滚机制，统一写为“边界外/待核”，不把 API 类型推导成服务端实现。

## 10.2 当前实现的真实分层与调用链

```text
CLI / headless / desktop / channels / Agent SDK
        │  产品入口与用户交互语义
        ▼
当前运行核心（letta-code）
  headless.ts / agent context / QueueRuntime / tool execution / backend selector
        │
        ├─ local backend
        │    ├─ LocalStore：进程内 Map + agents/*.json + conversations/*/conversation.json
        │    │              + messages.jsonl + system-prompt.json
        │    ├─ 本地模型/turn executor
        │    └─ ~/.letta 或本地 backend storageDir 下的 MemFS git 工作树
        │
        └─ API backend
             ├─ @letta-ai/letta-client / src/backend/api
             └─ HTTP REST（Agent/Conversation/Message/Run）+ 单一双向 WebSocket /ws
                    │
                    ▼
             外部 App Server / Cloud（数据库、服务端队列、运行沙箱不在 letta-code 源码边界）

通用支持库落点：协议帧、结果/错误、取消信号、文件/JSONL/路径、Git/HTTP 客户端、
                 资源清理与可观测事件。
记忆模块落点：Block、persona/human、MemFS、memory/*.md、Git 同步、提示词编译/压缩。
运行核心落点：Agent+Conversation 执行上下文、turn/run、QueueRuntime、工具监督、重试/取消。
统一网关落点：APIBackend REST 适配、AppServerClient WebSocket、channels、外部工具回调。
```

当前 `letta-code` 的 `Backend` 接口把 `Agent`、`Conversation`、`Message`、`Run`、模型列表、流式消息、取消和 fork 统一成调用面；`APIBackend` 只是客户端适配器，`LocalBackend` 才在本进程实现一套实验性本地存储/执行。不要将两者的持久化语义混写。

## 10.3 逐项通用底座映射

| 当前概念/源码证据 | 通用支持库 | 记忆模块 | 运行核心 | 统一网关 | 仅 Agent 产品语义/裁决 |
|---|---|---|---|---|---|
| `AgentState`、`agentId`、`name`、`tags`、model/tool 配置 | `AgentRef`、版本化状态读写契约、稳定 ID/错误结果 | 读取 MemFS tag、记忆开关 | 当前执行上下文绑定 agent、权限/工作目录绑定 | REST `GET/POST/PATCH /v1/agents`、SDK 映射 | `persona`、人格、模型档位、产品默认 agent 名称 |
| `src/agent/context.ts` 的 `agentId`、`agentName`、`conversationId` | 不应继续使用隐式全局；通用 `ExecutionContext` 应显式传递并可序列化 | 以 agentId 解析记忆根目录 | turn/tool/stream 的作用域、并发隔离、所有权校验 | 将上下文装入请求/事件 envelope | “当前 Agent”展示名、技能来源选择 |
| `src/agent/memory.ts` 的 `CreateBlock`、`label/value/description/read_only` | 通用 `MemoryBlock` schema、大小/路径/权限/版本契约 | Block 加载、默认块缓存、MDX frontmatter、读写工具 | 将快照版本绑定到一次 turn，避免读到半写记忆 | Agent 创建/更新时传 `memory_blocks`；远程 API 只承载契约 | 现有默认块仅 `persona`、`human`，标签和 prompt 文案是产品语义 |
| `memory-filesystem.ts` 的 `.letta/agents/<agentId>/memory`、`system/`、`.md` | 路径安全、原子文件写、Git provider、摘要/冲突结果 | MemFS 文件树、clone/pull、memory commit、system memory | 启动策略（blocking/background/skip）、同步超时、冲突隔离 | 远端 MemFS API/Git proxy；本地 backend 不经过远端 | `git-memory-enabled` tag、`/palace`、`/doctor` 等产品命令 |
| `memory-git.ts` / Git hooks/signing/locking | Git/文件 provider 和资源释放契约 | 记忆版本、提交、同步、冲突/回滚语义 | 把记忆同步作为可取消执行单元，不阻塞无关 turn | Cloud MemFS 服务边界 | “记忆会学习”“dreaming”及系统提示内容本身 |
| `src/tools/README.md` 工具结果 `{toolReturn,status,stdout,stderr}` | 能力契约、参数 schema、统一错误码/可重试、`AbortSignal` | 记忆工具是记忆模块提供的能力 | 串行执行、权限、工作目录、超时、取消、子进程组回收 | `external_tool_call_request/response`、SDK 外部工具桥 | Bash、Read/Edit、AskUserQuestion 等具体工具名称和 UI |
| `tools/manager.ts` 的 built-in/external/mod registry、`executeTool` | 唯一能力注册/调用器；禁止消费者各自翻译结果 | `memory`/MemFS 工具由模块注册 | 工具 context、toolCallId、运行时 scope、结束事件 | external tool handler 只通过网关协议穿越 | Mod 可替换 `tool_end` 的产品扩展点 |
| `MessageCreate`、`src/agent/message.ts` 流式请求 | 消息 envelope、内容部件、游标、幂等键、结果/错误 | 记忆更新消息与压缩后系统消息 | turn 输入、响应状态、approval continuation、stream 生命周期 | REST/SDK 消息、WS stream、channels | role、prompt、system reminder、summary 的 Agent 语义 |
| `MessageEnvelope`：`session_id/uuid/timestamp/event_seq/agent_id/conversation_id` | 统一事件信封、序列、关联键、脱敏与持久化事件格式 | 记忆提交/同步事件可复用同一 envelope | 运行状态投影、重放/断线补发、去重 | CLI stream-json、WS listen、SDK 消费 | 文案渲染、TUI 标签和渠道格式 |
| `Backend` 接口及 `APIBackend` | provider-neutral backend contract、能力探测、错误/超时/取消 | 只负责记忆相关 capability，不把远端 Agent API 写进记忆模块 | 选择 backend、绑定生命周期、重试和恢复 | `apiRequest`、`@letta-ai/letta-client` 是网关/provider 适配层 | Cloud/local/remote 三种产品部署体验 |
| `AppServerClient` | WebSocket client、request_id correlation、请求超时、连接状态机 | 记忆事件仅作为协议事件之一 | pending request 生命周期、断线后失败、显式 close | 单一 `/ws` 双向 socket；`control/stream` 是逻辑频道，不是两条连接 | `conversation_list`、`input`、`abort_message` 等产品命令名 |
| `src/backend/api/agents.ts`、`conversations.ts` | HTTP 方法、URL 编码、认证 header、响应解码 | `context`/MemFS endpoint 由记忆模块声明能力 | Run/Conversation 绑定、取消和恢复 | `/v1/agents`、`/v1/conversations/:id/*`、`/v1/runs/*` | API 路由名称和 Letta Cloud 资源模型 |
| `QueueRuntime` 的 `QueueItem`、soft limit 100、hard limit 默认 300、coalesce、callbacks | 通用内存队列、容量/背压/丢弃/清空/事件契约 | 记忆同步通知可作为 `task_notification`，但不应改变记忆事实 | turn 调度、阻塞原因、批量合并、取消/关闭排空 | queue lifecycle event、queue snapshot、WS/CLI 投影 | `cron_prompt`、`task_notification`、slash command 优先级 |
| `LocalStore`：Map + JSON/JSONL 文件 | 通用 JSON/JSONL 存储 provider、索引、文件锁、崩溃恢复契约 | MemFS 与本地消息/提示词分开存储 | local backend 的 Agent/Conversation/Run 状态 | LocalBackend 适配 `Backend` 接口 | 文件名、ID 前缀（`local-conv-`、`letta-msg-`）是实现细节 |
| `settings-manager.ts` 的 `~/.letta/settings.json`、项目 `.letta/settings.json`/`settings.local.json` | 配置/秘密/会话引用存储与权限边界 | 记忆开关、MemFS server key 只作为配置输入 | 启动恢复、backend/server scope 选择 | CLI/桌面/SDK 读取配置 | 最近 Agent、UI 偏好、model 最近使用列表 |
| `SessionRef={agentId,conversationId}`、`sessionsByServer` | 会话引用 schema、作用域/租约/版本校验 | 记忆目录按 agentId 隔离，不能按 UI session 混用 | 一次运行的执行单元和恢复锚点 | bootstrap/control/WS 将 session 传递给消费者 | “默认 conversation”及 TUI 会话体验 |

### 裁决摘要

1. **吸收为通用支持库**：ID/结果/错误、消息 envelope、HTTP/WS 协议包装、JSON/JSONL 文件存储、路径安全、Git provider、AbortSignal/子进程释放、队列容量和生命周期事件。
2. **吸收为记忆模块**：`MemoryBlock`、MDX frontmatter、`persona/human` 默认块、MemFS 根目录和 Git 版本、memory prompt 编译、记忆同步冲突；模块只能通过支持库公开文件/Git/协议能力，不直连第三方。
3. **吸收为运行核心**：`ExecutionContext`、Agent/Conversation/Run 作用域、turn 调度、QueueRuntime、tool execution supervisor、取消/超时/重试/恢复和资源排空。
4. **吸收为统一网关**：`APIBackend`、`AppServerClient`、channels 的 inbound/outbound、external tool request/response、鉴权和事件流；网关不拥有 Agent 事实、记忆文件或本地队列。
5. **只保留在 Agent 产品层**：persona/human 文案、技能名称、slash commands、`MessageChannel`、cron/dreaming、模型档位、TUI/桌面展示、Cloud/local 的产品开关。它们可调用底座契约，但不得成为公共库的数据模型名称。
6. **待核/不吸收**：远端 App Server 内部数据库 schema、服务端持久化事务、分布式队列、租约续期、沙箱生命周期、跨机器锁、Cloud 计费/限流和 server-side crash recovery；当前 `letta-code` 只展示客户端接口，不能凭路由或类型补写这些实现。

## 10.4 契约表：输入、输出、错误、取消和资源责任

| 契约边界 | 输入/所有权 | 输出/事件 | 失败、超时、取消 | 幂等/版本/资源释放 |
|---|---|---|---|---|
| `MemoryBlock` 创建/更新 | 调用方拥有 `label/value/description`；模块校验路径、大小和只读属性 | 规范化 Block；版本/摘要待平台补齐 | 非法 frontmatter、缺文件、冲突必须是结构化失败；当前加载器只 `console.error` 后继续，错误码待核 | block snapshot 由记忆模块持有；失败不得留下半写文件；当前源码未证明原子写/fsync |
| MemFS enable/sync | Agent ID、tag、memory dir、远端 endpoint；同步器拥有 Git 连接/临时 checkout | `action/memoryDir/pullSummary`，含冲突摘要 | blocking 失败可终止启动；background 只记录错误；skip 不拉取；Git 冲突不可伪装成功 | 目录按 agentId 隔离；clone/pull/临时锁须 finally 释放；崩溃后需工作树、锁、进程残留检查，当前仅有测试文件存在证据 |
| `executeTool(name,args,options)` | 运行核心拥有 `toolCallId`、scope、AbortSignal；工具只拥有自己的子进程/文件句柄 | `toolReturn/status/stdout/stderr` + started/finished 事件 | 未找到/权限拒绝/工具异常=error；abort 必须终止子进程组并返回可识别错误；超时要有上限 | 工具执行串行避免竞态；`toolContextId` 不存在立即失败；正常/异常/取消均清理 executor、监听器和子进程 |
| REST Agent/Conversation/Message/Run | 网关拥有 HTTP request/headers；provider 不把 client 对象泄漏给模块 | typed client response/page/stream | HTTP 4xx/5xx、网络断开、Retry-After、AbortSignal 均转统一 provider error；具体 server 错误码在边界外 | URL/游标转换只在 APIBackend 做一次；请求取消关闭 body/stream；重试必须带幂等策略，当前客户端只对部分场景有重试 |
| `AppServerClient.request` | 每个 control request 必须 `request_id`；pending map 由 client 拥有 | 匹配 request_id 的 typed/raw response | 默认 30s timeout 删除 pending 并 reject；send 异常清理 timer；socket close reject 全部 pending；显式 close 不重复通知 disconnect | request_id 是相关键但不是服务端幂等保证；一个 `/ws` socket，`control/stream` 为逻辑频道；必须限制 pending 数与输出大小 |
| `submitInput/input` | 网关接收 Agent/Conversation scope 和内容；queue runtime 接管排队 | `input_accepted` 只表示进入 dispatch/queue，不表示 turn 完成；后续 stream events | busy/approval/overlay/command/interrupt 时 blocked；cancel 要区分已接受/未接受；队列清空不能丢失关联事件 | 队列 item 有稳定 id/clientMessageId；同 scope 才能 coalesce；本地 queue 非持久，进程崩溃即丢失 |
| `cancelConversation/cancelRun/abort_message` | 调用方提供 conversation 或 agent+run/request_id | cancel ack 或 API response | 已完成、未启动、处理中要有不同结果；当前协议有 `accepted/reason/run_id`，server 取消语义仍待核 | 取消请求应幂等；AbortController、WS pending、tool subprocess、queue item 必须分别排空 |
| LocalStore JSON/JSONL | LocalBackend 拥有 storageDir；store 只在本地 backend 读写 | Agent JSON、conversation JSON、messages JSONL、compiled prompt JSON | JSON 损坏/部分写/并发写/磁盘满的恢复未由当前源码证明 | 读写路径已分层；未发现 SQLite/ORM；未证明 fsync、原子 rename、跨进程锁和 WAL，不能宣称崩溃一致 |
| 外部 Tool / `external_tool_call_*` | App Server 发 request，客户端 executor 拥有本地工具资源 | response `result` 或 `error` | handler reject 转 error response；socket 断开时 pending external call 的回收策略待核 | request_id/tool_call_id 应幂等；响应不得携带未脱敏 secrets；网关只转发，不持久化工具私有状态 |

## 10.5 执行单元、租约和会话边界

### 10.5.1 当前可确认的执行单元

当前实现实际存在多个相关但不等价的 ID：

- `agentId`：长期 Agent 资源的外部标识。
- `conversationId`：Agent 下的会话/消息上下文；`default` 是产品兼容路径，不应当作全局唯一会话。
- `runId`：后端一次运行的可取消标识，`APIBackend.cancelRun(agentId, runId)` 使用它。
- `toolCallId`：一次工具调用的关联标识。
- `queue item id`/`batchId`：本进程队列的提交单元和批次标识。
- `request_id`：WS control 请求/响应关联标识，不等于 runId。
- `session_id`/`event_seq`：wire 事件的消费/重放范围，不等于 Agent 的持久身份。

通用运行核心应把一次**执行单元**定义为：

```text
执行单元 = {execution_id, agent_id, conversation_id, run_id?, request_id?,
           owner, generation, deadline, cancel_token, state, resource_handles}
```

其中 `queue item` 进入运行核心后才获得 `execution_id/run_id`；被合并的多个消息仍须保留 item id，不能用一条合并消息覆盖审计关联。

### 10.5.2 当前缺失的租约

当前公开源码可见：队列有容量和状态事件，WS pending 有 timeout，工具有 `AbortSignal`，但未见跨进程/跨机器的**持久租约**（owner、心跳、租约截止、generation、崩溃接管、CAS fencing token）。因此不能把 QueueRuntime 或 `requestTimeoutMs=30000` 叫作租约。

底座新增租约契约应至少包含：

1. `acquire(execution_id, owner, deadline)`：原子抢占，返回不可回退的 fencing token。
2. `renew(token, heartbeat)`：只能由当前 owner/generation 续租，超过硬截止不得续租。
3. `cancel(token, reason)`：设置持久取消意图，通知队列、工具、HTTP/WS stream。
4. `release(token, outcome)`：成功、业务失败、超时、主动取消、崩溃恢复都幂等。
5. `reclaim(dead_owner)`：按 owner/generation 精确回收，禁止误杀新一代执行单元。
6. `recover(token)`：重启后读取意图、事件和资源账本，决定重试、回滚或人工介入。

Letta 当前实现只能吸收“ID 关联 + cancel/timeout 触发点”，不能直接复用成平台租约；该项裁决为**待核/需新原子能力**，不是对 Letta 缺陷的臆测。

### 10.5.3 会话与持久化不是一回事

`SessionRef` 把 `agentId` 与 `conversationId` 作为一对保存，并按 server key 分组；`src/agent/context.ts` 还使用 `globalThis` 保存当前进程上下文。这些是**会话引用/运行上下文**，不是 Agent 真相源。真正的边界应固定为：

```text
持久 Agent 事实       → remote App Server 或 local LocalStore
持久 Conversation     → remote App Server 或 local conversations/<scope>/conversation.json
持久 Message transcript→ remote App Server 或 local messages.jsonl
持久记忆              → MemFS git 工作树（remote clone/pull 或 local storageDir/memfs）
本地配置/会话引用      → ~/.letta/settings.json、项目 .letta/settings*.json
运行中队列/Abort/pending→ 进程内；只通过事件快照/回放向网关投影
```

进程重启后，Agent/Conversation/Message/Memory 可按后端恢复；QueueRuntime、pending request、AbortController、工具子进程和 `globalThis` context 不可直接恢复，必须由启动 bootstrap 重新建立。bootstrap 返回 `agent_id/conversation_id/model/tools/memfs_enabled/messages`，其职责是恢复引用和初始视图，不是替代持久化事务。

## 10.6 数据库、队列和服务端边界

### 数据库边界

当前核对读取的 `letta-code` 当前源码中没有 SQLite、PostgreSQL、ORM、迁移器或服务端数据库实现。LocalBackend 的 `LocalStore` 明确使用内存 Map 加 JSON/JSONL 文件：`agents/<agent>.json`、`conversations/<scope>/conversation.json`、消息 transcript JSONL 和 `system-prompt.json`。因此：

- “Letta 有数据库表/事务/WAL/服务端队列”不能从本目标仓库或 `letta-code` 客户端源码得出。
- 远程 API 返回的 Agent/Conversation/Message/Run 由 App Server/Cloud 负责存储；数据库 schema、事务边界、索引、迁移、备份和 server crash recovery 均是服务端边界外证据。
- 通用支持库可以提供 JSON/JSONL、SQLite/外部数据库 provider，但必须由项目适配层声明选型；不能因为平台已有数据库能力就把 Letta LocalStore 改写成数据库。
- LocalStore 当前未证明 atomic rename、fsync、文件锁、跨进程并发写和损坏恢复，后续只能裁决为“可复用数据形状/待补存储契约”，不能判定为可靠持久化实现。

### 队列边界

`QueueRuntime` 是进程内、非持久的调度缓冲：软上限达到时可丢弃最旧可合并项，硬上限达到时拒绝并发出 `buffer_limit`；阻塞原因包括 streaming、pending approvals、overlay、command、interrupt；清空原因包括 processed、error、cancelled、shutdown、stale_generation。其事件可以通过 stream-json/WS 投影，但投影不是队列本身的持久化。

底座映射应明确：

- `QueueRuntime` → 运行核心的短生命周期内存队列实现/参考契约。
- queue item schema、coalesce、backpressure、drop/clear event → 通用支持库契约。
- `task_notification`、`cron_prompt`、`approval_result`、slash command → Agent 产品适配层。
- 若需要重启可恢复队列，必须另建持久队列/事件日志/租约，不得把当前数组加一个 JSON snapshot 就声称已恢复。

### 服务端 API 与网关边界

`AppServerClient` 的公开源码可以证明客户端协议行为：URL 的 `http/https` 转 `ws/wss`，默认路径 `/ws`；单一 WebSocket 同时承载 control/stream 逻辑频道；typed/raw command 通过 `request_id` 关联；默认请求超时 30 秒；close/disconnect 会 reject pending；`input` 与 `submitInput` 的接受语义不同；`abort`、`conversationList`、external tool response 有专门包装。

这只证明**网关客户端契约**，不能证明以下服务端事实：HTTP/WS 路由内部如何鉴权、请求如何入服务端队列、Agent turn 如何抢占、数据库何时提交、消息流如何重放、取消是否杀死模型/工具进程、服务重启如何接管。上述均须取得 `letta-code` 配套 App Server 或 Cloud server 源码后再升为 L1/L2 结论。

## 10.7 资源生命周期与失败矩阵

| 资源 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主/进程崩溃 | 当前证据与剩余风险 |
|---|---|---|---|---|---|
| HTTP/WS socket | stream 结束后由调用方关闭或复用 | API error 交 provider error | request timer reject；AbortSignal 需停止 body/stream | `close` reject pending；重连/重放策略待核 | client 有 pending 清理，服务端 socket 资源未知 |
| pending request/timer | 匹配 response 后清 timer、删 Map | send error 清理 timer/Map | 30s timeout 清理并 reject | `handleDisconnect` reject 全部 | 无持久 request ledger；不能重启恢复 |
| tool 子进程/stdio | tool 返回后结束并回收 | status=error，必须回收句柄 | AbortSignal 传给 spawn/exec；归一化“User interrupted” | 独立进程组需 kill/reap；当前 README 要求但具体每个工具仍须核验 | 把“实现规范”与“所有工具已实现”分开 |
| tool context/监听器 | `runWithRuntimeContext` finally cleanup | 未知 context 立即 error | cancel 后 cleanup | 进程死由宿主回收 | `toolContextId`、mod hook 边界已有代码证据，跨进程状态未持久 |
| QueueRuntime item | dequeue/coalesce 后 callback | error 时 clear(error) | clear(cancelled)/drop(buffer_limit) | 数组全部丢失 | 事件可投影，不能当持久队列 |
| MemFS checkout/Git lock | commit/pull 后继续 | conflict/clone/pull 失败返回或阻断启动 | background/skip/blocking 三种策略；取消和子进程回收待实测 | 工作树/lock/tmp 残留、半提交恢复未在当前树验证 | 记忆模块必须补残留扫描和恢复证据 |
| LocalStore 文件 | JSON/JSONL 写入后可重新加载 | JSON 损坏/磁盘满路径未完整证明 | 无统一 store AbortSignal | 部分写、重复消息、索引与 transcript 不一致待核 | 不能宣称事务/WAL/原子提交 |
| Agent/Conversation/Run | remote/local backend 返回结果 | typed API error 或 local error | `cancelConversation`/`cancelRun`/`abort_message` | server-side 恢复边界外；local 文件重载可恢复部分事实 | run/lease/数据库提交时序待取得服务端源码 |
| session context/secrets | 会话结束清除或切换 | 未绑定 agent/conversation 失败 | session disable/persist flag | globalThis/Abort/pending 丢失 | `settings-manager` 配置存储与密钥仓库需单独审计 |

失败/超时/取消/崩溃的共同底座契约应满足：

1. 每个执行单元先落**持久意图/关联键**，再申请外部资源；不得先切换事实再补写意图。
2. 所有出口统一进入 `finally` 或等价资源治理器：正常、业务失败、timeout、cancel、异常和宿主 crash recovery 都记录释放结果。
3. 释放必须幂等；二次 cancel/release 不得把已回收资源重新激活，也不得误释放新 generation 的资源。
4. 事件至少携带 `execution_id/agent_id/conversation_id/run_id?/request_id?/item_id?`，否则断线补发和审计无法还原。
5. 队列/工具/记忆同步的错误不能静默变成成功；当前源码中个别日志后继续的路径只能标记为待补契约。

## 10.8 L0-L4 验证矩阵

| 等级 | 目标 | 当前核对真实执行/证据 | 结果 |
|---|---|---|---|
| L0 身份与边界 | 核对目标根、项目名、分支、当前文件树、MCP/代码图绑定 | `project_context` 返回了错误的华世王镞_v3，已明确废弃；`git status --short --branch`、`git branch -a`、`git ls-files`、`git log --oneline`、`git ls-tree -r --name-only HEAD`；本地搜索 `ARCHITECTURE.md`/`细探-Letta.md` | 目标树身份确认；代码图/MCP 目标证据阻断 |
| L1 源码/契约静态核验 | 读取当前实现源码和公开契约，不把声明当运行结果 | 只读取得 `letta-code` main commit；核对 `src/agent/memory.ts`、`memory-filesystem.ts`、`memory-runtime.ts`、`context.ts`、`message.ts`、`backend/backend.ts`、`backend/local/local-backend.ts`、`backend/local/local-store.ts`、`queue/queue-runtime.ts`、`queue/turn-queue-runtime.ts`、`tools/README.md`、`tools/manager.ts`、`types/protocol.ts`、`app-server-client.ts`、`settings-manager.ts` | L1 通过（外部公开源码快照）；目标本地仓库仍无 runtime |
| L2 单元/静态测试 | 验证协议/队列/记忆/工具生命周期 | 发现并读取 `headless-queueing.test.ts`、`headless-queue-lifecycle.test.ts`、`app-server-client.test.ts`、`memory-filesystem*.test.ts`、`tools/*test.ts`；未在 `letta-code` 工作树安装依赖或执行 Bun 测试 | 未执行，不能写 pass；测试存在≠测试通过 |
| L3 集成链路 | 真实 LocalBackend/App Server/WS/REST/本地 MemFS 回路 | 目标仓库无服务；未启动外部 server，未执行 `letta server`，未连接 Cloud/API，未改写环境/依赖 | 未验证；数据库、服务端队列、鉴权、stream、cancel 端到端均待核 |
| L4 故障与恢复 | 强制 timeout/cancel/disconnect/工具崩溃/Git 冲突/文件部分写/重启恢复/资源残留 | 未对外部 `letta-code` 运行故障注入；本地目标只允许改文档且没有运行时 | 未验证；不能声称租约、崩溃一致性、残留清零或恢复通过 |

当前核对 L0/L1 的“通过”只表示证据边界与静态源码映射成立，不是 Letta runtime 的功能验收。要把 L2-L4 升级为真实结果，下一工作包必须取得并固定 `letta-ai/letta-code` 本地源码/依赖许可，另行验证 LocalBackend 与 App Server；不得在本 landing-page 仓库内补造实现。

## 10.9 现有能力命中、缺口与装配计划

| 能力 | 命中/缺口 | 单链路落点 | 裁决 |
|---|---|---|---|
| 稳定 ID、事件 envelope、错误/结果 | `agentId/conversationId/runId/toolCallId/request_id/item_id` 已有分散形状 | 公共契约 → 运行核心执行单元 → 网关事件适配 | 升级现有支持库；统一命名和关联键，不复制第二套 |
| 文件/JSON/JSONL 持久化 | LocalStore 已有真实文件布局，但缺原子提交/锁/恢复证据 | 支持库存储 provider → LocalStore 适配 | 升级/待核；先补契约和故障测试，不能直接替换实现 |
| 记忆 Block/MemFS | `memory.ts`、`memory-filesystem.ts`、`memory-git.ts` 形成产品链 | 记忆模块 → Git/文件支持库 → 运行核心同步单元 | 吸收为记忆模块；Git provider 不泄漏到网关 |
| 工具调用/取消 | `tools/README.md` 与 manager 有公共形状，具体工具异构 | 能力注册表/工具支持库 → 运行核心监督 → 网关 external tool | 吸收契约，补资源监督与强杀验证 |
| 进程内 turn queue | QueueRuntime 有容量和事件，非持久无租约 | 运行核心唯一队列 → 网关事件投影 | 复用/升级；不当作分布式队列 |
| REST/WS API client | APIBackend/AppServerClient 已有单一调用面 | 统一网关唯一公开入口 | 吸收网关适配；服务端实现继续待核 |
| Agent/Conversation/Message/Run 资源 | 客户端类型和 LocalStore 形状存在 | 通用资源引用 + backend provider | 通用契约吸收；字段语义仍由 Agent 适配层保留 |
| 租约、fencing、崩溃接管 | 当前源码未发现持久租约 | 运行核心新原子能力 | 新建候选；没有服务端证据前不宣称复用 |
| 外部数据库/服务端队列/事务 | 当前源码边界外 | 统一网关/provider 或服务端项目 | 待核/隔离；禁止由 landing page 推断 |

装配顺序固定为：

```text
1. 冻结证据版本：目标 landing page 87fd37a + 外部 letta-code main 4f2d0d13
2. 先登记公共契约：ID/envelope/错误/取消/资源生命周期/持久化结果
3. 再装配支持库：JSON/JSONL、路径安全、Git、HTTP/WS、子进程、事件
4. 再装配记忆模块：Block → MemFS → Git sync → prompt compile/compaction
5. 再装配运行核心：ExecutionContext → queue → turn/run → tool supervisor → lease candidate
6. 最后装配网关：REST/APIBackend → AppServerClient /ws → channels/external tools
7. 以 L2→L4 真实测试决定“吸收/升级/新建/待核”，未验证项不得进入生产底座
```

本节是后续映射输入，不是对 `letta-ai/letta-code` 的代码迁移计划；允许修改范围仍只有本文件，旧细探不存在于现场但也未被删除。

## 10.10 当前核对新增证据路径与剩余风险

- 本地事实：`AGENTS.md`、`README.md`、`ARCHITECTURE.md`、`git ls-files`、`git ls-tree -r --name-only HEAD`、`git status --short --branch`。
- 外部当前实现只读路径：`letta-ai/letta-code` `main`，提交 `4f2d0d13496117e8fbf584aa24bea595c464f11b`；重点源码路径见 10.3、10.8。
- MCP 事实：`project_context` 曾错绑华世王镞_v3，本轮不采用该 MCP 证据；Letta 根目录当前存在独立 `.codegraph/`，仅用目标目录 CLI 作定位，不把它当运行成功证据。
- 未解决风险：旧细探缺失、外部 server 源码未取得、L2-L4 未执行、LocalStore 原子性/锁/恢复未证明、远端数据库/队列/租约边界未知、`globalThis` context 与多会话并发隔离仍需真实测试。

---

# 11. 第四轮：archive V1 源码核对与底座要素补全（2026-08-21）

## 11.1 证据层级与纠偏

当前核对没有找到此前文档提到的独立 `细探-Letta.md` 文件，因此不声称读取了该文件，也不把聊天上下文当作细探证据。为核对旧细探中提到的 Agent loop、Block/Memory、消息、REST/WS、ORM 和后台任务，当前核对只读获取并读取了同一远程仓库 `origin/archive`，提交为 `56ba9c25552605eec89de8ed3dc6394b625c1993` 的源码与迁移文件。

该分支是**退役 V1 历史实现**，不是当前 `main`，也不是当前 `letta-code`。下文所有“archive 证据”只用于补齐历史架构和通用底座映射；不能把它描述成当前产品实现，不能据此推断 `letta-code` 的服务端行为。

当前核对实际核对的代表性路径包括：

- Agent：`letta/schemas/agent.py`、`letta/agents/agent_loop.py`、`letta/agents/letta_agent_v3.py`。
- 记忆：`letta/schemas/memory.py`、`letta/orm/block.py`、`letta/services/memory_repo/git_operations.py`。
- 消息与运行账本：`letta/orm/message.py`、`letta/orm/conversation.py`、`letta/orm/run.py`、`letta/orm/step.py`。
- 工具：`letta/orm/tool.py`、`letta/services/tool_executor/tool_execution_manager.py`。
- 服务与队列：`letta/server/server.py`、`letta/server/rest_api/redis_stream_manager.py`、`letta/jobs/scheduler.py`、`letta/server/db.py`。
- 服务边界：`letta/server/rest_api/routers/v1/`、`letta/server/ws_api/server.py`、`letta/server/rest_api/streaming_response.py`。
- 持久化演进：`alembic/versions/` 中 Agent、Block、Message、Run、Step、Job、Tool、Conversation 及关联表迁移。

## 11.2 Agent state、执行循环与运行账本

### AgentState 是可重建的持久资源视图

archive 的 `AgentState` 明确写作“在某一时刻的 Agent 状态，并持久化在 DB backend；包含重建持久 Agent 所需的信息”。它不是单纯的 prompt，也不是仅存在于进程的执行对象。其主要分组如下：

| 分组 | 字段/关系 | 责任边界 |
|---|---|---|
| 身份与作用域 | `id`、`name`、`description`、`project_id`、`deployment_id`、`organization_id`、tags、identities | 资源归属、访问控制、模板/部署作用域；ID 不能由会话或 UI 名称替代 |
| 模型与生成 | `agent_type`、`system`、`llm_config`/`model`、`model_settings`、`embedding_config`、`response_format`、`compaction_settings` | 决定循环类型、模型路由、上下文压缩和输出约束 |
| 记忆与上下文 | `blocks`、兼容字段 `memory`、`message_ids`、`sources`、`message_buffer_autoclear`、`max_files_open` | core memory、消息上下文和文件上下文的装配；`memory` 已是兼容/弃用形状，不应与 `blocks` 作为两套事实 |
| 工具与权限 | `tools`、`tool_rules`、`secrets`、兼容字段 `tool_exec_environment_variables`、`pending_approval` | 工具声明、规则、秘密输入和审批暂停状态；秘密值不应进入普通消息或日志 |
| 运行观测 | `last_run_completion`、`last_run_duration_ms`、`last_stop_reason`、`enable_sleeptime`、managed group | 最近一次结果和后台记忆管理开关；不是完整运行历史，历史由 Run/Step/Message 保存 |

`letta/agents/agent_loop.py` 是按 `AgentType` 和 `enable_sleeptime` 选择 `LettaAgentV2/V3` 或 sleeptime multi-agent 实现的工厂。`LettaAgentV3.step()` 的实际循环边界包含：装配输入消息、按 conversation 应用隔离 Block、建立 LLM 请求、执行模型输出中的工具/审批分支、追加消息与 step 记录、摘要/压缩、继续下一步或返回 stop reason。`max_steps` 是单次执行上限；它不是队列容量，也不是持久租约。

一次历史执行应拆成以下账本层次：

```text
AgentState  1 ── N  Conversation  1 ── N  Run
                                  Run  1 ── N  Step
                                  Run/Step  1 ── N  Message
Agent       1 ── N  Block / Tool / Source / Identity
```

- `Conversation` 允许同一 Agent 并发消息，持有 summary、模型覆盖、隔离 Block 和最近消息时间。
- `Run` 是一次处理会话/请求的生命周期对象，具有 `created/completed/cancelled` 等状态、stop reason、完成时间、回调状态和时延指标，并可关联 Agent 与 Conversation。
- `Step` 是单次模型/工具推进的观测账本，保存 provider、model、token、stop reason、trace/request ID、状态和错误数据。
- `Message` 是可重放的事实记录，既可挂到 run/step/conversation，也可携带 tool call、tool return、approval、sender、batch item 和单调 `sequence_id`。

因此，“Agent state”不能只保存最后一轮 prompt；至少要区分资源快照、消息事实、执行账本和观测指标。

## 11.3 Memory：core block、文件、归档/召回与提示编译

archive 的 `Memory` 是 in-context memory 容器，核心事实由 `Block` 列表组成，另有 file blocks；`Block` 具有 `label`、`value`、`description`、`limit`、`read_only`、`hidden`、版本和当前 history entry。典型 `human`/`persona` 只是产品默认标签，不是底座必须固定的两个字段。

记忆装配有四个不同层次：

1. **Core memory**：Block 直接编译进 system prompt；更新由 `core_memory_append/replace` 等工具触发，并受字符上限、只读和乐观版本控制约束。
2. **文件记忆**：文件关联到 Agent/Source，打开状态和每文件视图窗口受 `max_files_open`、字符限制控制；未打开的文件不能假装已经进入上下文。
3. **Git/MemFS 记忆**：`git-memory-enabled` Agent 将 `system/*`、外部文件和 skills 映射为记忆工作树；`GitOperations` 使用临时目录执行 git，再把仓库对象上传回 StorageBackend。临时 checkout、子进程、锁和上传必须在成功、异常、取消路径清理。
4. **Archival/recall memory**：archive 的 Memory schema 还定义了 archival passage 写入/搜索和 recall/archival 摘要；这些属于外部检索存储，不等价于当前 in-context blocks，也不等价于消息 transcript。

提示编译是有预算的投影，不是事实存储：system prompt、core blocks、memory filesystem、summary、tool definitions、directories 和 messages 分别计 token。上下文超限时可执行 summarizer/compaction，但摘要消息必须可追踪，不能静默覆盖原始消息。

## 11.4 工具、审批和资源释放

archive 的 Tool 记录名称、类型、描述、JSON schema、源码/来源类型、pip/npm 需求、返回字符上限、是否默认审批和是否允许并行执行。`ToolExecutionManager` 按 `ToolType` 选择内建、core、文件、MCP 或 sandbox executor，执行结果统一为 `ToolExecutionResult`，并截断超过 `return_char_limit` 的返回。

底座边界应固定为：

- Agent 只声明工具和规则；运行核心负责 tool call 关联、顺序/并行策略、审批状态、超时和取消。
- executor 才拥有子进程、stdio、MCP 连接、sandbox、文件句柄和临时目录；调用方不得越过 executor 直接持有这些资源。
- 工具成功、业务异常、`CancelledError` 和未知异常都必须产生结构化结果并进入 `finally` 统计/清理；日志不能替代错误结果。
- 返回截断是上下文保护，不是事实删除；完整返回若需审计应存于受权限控制的运行账本，不能把秘密或任意 stderr 原样回传给用户。
- approval request/response 是消息状态的一部分；审批等待不能被误判为执行完成，重复审批和取消必须幂等。

## 11.5 消息、流和持久化边界

Message 同时承担模型上下文、用户可见 transcript、工具协议和运行关联，必须保留 `role`、content parts、tool call/return、approval、`run_id`、`step_id`、`conversation_id`、`sender_id` 和序列号。消息序列号在 SQLite 下通过数据库序列表原子分配，说明并发追加不能依靠进程内计数器。

archive 的数据库边界是 SQLAlchemy async engine + session factory + Alembic migrations：

- PostgreSQL 使用连接池、预检查、回收和异步 session；配置可禁用池化或使用 SQLite 测试路径。
- session 正常出口 commit；普通异常 rollback；`asyncio.CancelledError` 也必须 rollback 后再把连接归还池，最后 expunge/close。
- ORM 关系包含 cascade、`ondelete`、索引和唯一约束；Block 使用版本列做乐观锁；Message、Step、Run 分别有查询索引支持按 Agent、Conversation、Run、序列和时间重放。
- schema 事实只能由 ORM 与 migration 共同确认；当前 main landing page 不包含这些表，archive 迁移也不能当作当前 Letta Code 服务端 schema。

流式输出不是消息提交的替代品。archive 的 Redis SSE writer 按 run 缓冲 chunk、分配 seq_id、批量写 Redis stream、设置 TTL 和最大长度；后台 processor 用 `aclosing` 确保上游 async generator 的 finally 执行，并在错误时回填未刷出的 buffer。它提供断线读取/短期重放能力，但不是 Agent/Message 的事实源。

## 11.6 队列、后台 Job 与服务边界

应区分三类执行通道：

| 通道 | 事实与生命周期 | 崩溃语义 |
|---|---|---|
| 同步 Agent Run | HTTP/WS 请求触发，Run/Step/Message 记录结果，流向客户端 | 客户端断开不等于 Run 已取消；服务端需单独检查取消并关闭模型/工具资源 |
| 流式投影 | Redis SSE stream 按 run 暂存 chunks，带 seq/TTL/长度上限 | 可短期补发；buffer/stream 过期或进程崩溃不能恢复未提交的 Agent 事实 |
| 后台 Job/批处理 | `Job` 记录用户、类型、状态、callback、时延；scheduler 轮询 LLM batch | Job 状态必须持久化；重复轮询需幂等，不能只依赖 asyncio task |

`jobs/scheduler.py` 使用 PostgreSQL advisory lock 做 scheduler leader election；非 PostgreSQL 路径退化为不选主的启动方式。持锁 session 必须在 shutdown、启动异常和失去 leader 时释放；retry task、scheduler 和 DB session 均要取消/关闭。这个 advisory lock 是调度器单实例保护，不是每个 Agent Run 的通用 fencing lease。

服务边界应保持如下方向：

```text
REST/WS/SDK/Channels
        │ 鉴权、请求校验、request_id、流协议、错误映射
        ▼
Service managers / Agent loop
        │ 事务内读取/写入 Agent、Block、Message、Run、Step、Job
        ├── LLM provider adapter
        ├── Tool executor / sandbox / MCP
        ├── Memory repo / vector or archival backend
        └── Redis stream / scheduler / callback
```

网关拥有连接和协议，不拥有 Agent 真相；service manager 负责编排，不应把 HTTP/WS 对象泄漏到 ORM；provider、sandbox、Redis、Git 和数据库均必须通过可关闭的适配边界进入。WS 连接关闭、HTTP 客户端超时或 SSE 消费结束，不自动等于底层 Run 已经停止。

## 11.7 失败矩阵与资源责任（archive 证据 + 当前未证实项）

| 边界 | 正常 | 业务失败 | 超时/取消 | 进程崩溃/重启 | 必须核验的结果 |
|---|---|---|---|---|---|
| Agent loop / Run | 写 terminal stop reason、完成时间和指标 | 写 failed/error step，保留关联消息 | 写 cancelled 或明确 stop reason，停止后续 step | 从持久 Run/Message 判定 abandoned/retry；不能从内存 Agent 猜 | 服务端接管、重试和 lease 未由当前 main 或 letta-code 客户端证明 |
| DB session/connection | commit、expunge、close | rollback 后 close | `CancelledError` 也 rollback，避免 idle transaction | pool 重建；未提交事务回滚 | archive 有代码证据；真实断电恢复未执行 |
| Message/sequence | 原子追加、唯一 ID/序列 | 事务回滚，不留下孤儿 tool return | 取消点前后必须区分已持久化事实 | 以 DB transcript 重放 | 重复提交的幂等键和跨服务 outbox 未完整证明 |
| Tool executor/sandbox | 返回后关闭句柄/进程/连接 | 结构化 error，清理所有资源 | kill 子进程组、关闭 stdio/MCP、取消监听器 | 宿主回收或启动扫描残留 | 每种 sandbox/MCP 的强杀和残留清理需单测/故障注入 |
| Memory block/ORM | commit + version/history 更新 | rollback，冲突返回 conflict | 不提交半写 Block | 由版本/历史选择恢复或人工介入 | Git 临时目录、锁、部分上传恢复仍需实测 |
| Git/MemFS | commit、上传对象、删除 temp dir | 保留工作树诊断信息，避免伪成功 | 终止 git 子进程并清理 temp/lock | 扫描孤儿 checkout/锁，按 generation 恢复 | archive 使用 tempfile/subprocess；完整 crash recovery 未验证 |
| Redis SSE stream | 批量 xadd、刷新 TTL、写完成标记 | buffer 回填并重试，不能丢静默 | stop 时 cancel flush task 后 flush 剩余 buffer | 短期 stream 可读；内存中未 flush chunk 丢失 | Redis durability、重复 seq 和跨实例 writer 竞争待核 |
| Scheduler/advisory lock | leader 执行轮询 | 记录错误，保留 retry | 取消 retry task，shutdown scheduler | DB 连接断开释放 advisory lock；新实例可接管 | PostgreSQL 之外的多实例安全性未证明 |
| HTTP/WS/SSE | 正确结束或复用连接 | 映射 typed error/event | 关闭 body/stream/pending timer；向下传播取消 | reject pending，客户端重连需 cursor/idempotency | 服务端取消是否杀模型/工具待核 |

统一失败矩阵的裁决是：**事实提交、运行状态、流投影和资源释放必须分别记录**。任何“连接断开即成功”“日志打印即恢复”“队列清空即取消”“Redis 有 chunk 即消息已持久化”的推断均不成立。

## 11.8 对通用底座的最终增补裁决

1. **Agent state** 归入资源状态契约；必须显式区分持久字段、关系快照、兼容字段和运行时上下文。
2. **Memory** 归入记忆模块；Block 版本/只读/历史、文件窗口、Git 工作树、归档/召回和 prompt projection 不得合并为一个无版本字符串。
3. **工具** 归入能力注册与运行监督；executor、审批、返回截断、取消和资源释放必须是一条可审计链。
4. **消息** 归入持久事件/事实模型；Message、Step、Run、Conversation 的关联键不可由流事件或 UI session 替代。
5. **持久化** 归入 provider + 事务契约；SQLAlchemy/Alembic、JSON/JSONL、Redis stream、Git object store 是不同 durability 等级，不能互称数据库或事实源。
6. **队列** 归入运行核心；进程内队列、Redis 流和持久 Job 必须有不同的丢失、重放、租约和幂等语义。
7. **服务边界** 归入统一网关与 provider 适配；REST/WS/SSE 只传输和投影，不拥有 ORM 或记忆事实。
8. **资源释放** 归入生命周期治理器；DB session、HTTP/WS、stream generator、Redis buffer、scheduler lock、子进程、MCP、sandbox、Git temp/lock 都要有成功/异常/取消/crash recovery 的出口。
9. **失败矩阵** 应作为验收契约的一部分；未执行的 L2-L4 继续标为待核，archive 静态源码证据不能升级为运行通过。

## 11.9 当前核对核对结论与剩余风险

- 已补齐旧 V1 archive 中可直接确认的 AgentState、Agent loop、Memory/Block、Tool、Message/Conversation/Run/Step/Job、ORM/迁移、Redis SSE、scheduler leader、REST/WS 和 DB session 边界。
- 未修改旧 archive 分支、未修改 `README.md`、未修改 `AGENTS.md`、未安装依赖、未启动服务、未执行外部运行时测试。
- 当前 `main` 仍是 landing page；当前 `letta-code` 仍只有客户端/本地实现证据；archive V1 仍是历史证据。三者不得合并成一个“当前架构”。
- 未确认项仍包括 `letta-code` 配套 App Server/Cloud 的数据库 schema、服务端队列、租约/fencing、取消传播、事务提交时序、分布式恢复、鉴权和真实资源残留。

---

# 12. 第五轮：交互线、状态机与故障恢复审计（2026-08-21）

## 12.1 审计范围与证据等级

当前核对按用户指定主题继续只读核对 `origin/archive` 的退役 V1 源码、迁移、测试、配置和文档入口。目标 `main` 仍是 landing page；因此本节不是当前 Letta 产品行为说明，而是**退役 V1 的历史实现审计**，用于辨认状态、资源和底座契约，不能升级为 `letta-code` 或 Cloud server 的事实。

代码图复核结果：目标目录当前存在独立 `.codegraph/`，本轮仅用目标目录内 CLI 作定位，并继续用 Git 对象级 `git show`、`git grep` 和文件清单回读源码。没有安装依赖、启动服务、连接数据库/Redis、运行 pytest 或执行故障注入；所有 L2-L4 结论继续标为未验证。

## 12.2 真实交互主线：请求到 Agent loop 再到流投影

历史 V1 的可还原主线是：

```text
REST/SDK/WS 请求
  -> router 校验与创建/获取 Run
  -> AgentLoop.load(AgentState, actor)
  -> LettaAgentV3.step(..., run_id, conversation_id)
  -> build prompt / LLM call
  -> tool call、approval 或 assistant return
  -> persist Message + Step，并更新 AgentState/Run
  -> compaction（必要时）
  -> stop_reason / usage / callback
  -> 同步 JSON 或 Redis-backed SSE stream
```

关键事实和边界：

- `AgentLoop.load` 是按 `AgentType`、`enable_sleeptime` 和 multi-agent group 选择执行器的工厂；缺少 group 时会记录 warning 并降级到标准 V2/V3，不是异常终止。
- `LettaAgentV3.step` 以 `range(max_steps)` 作为单次执行上限；每轮可能包含模型请求、工具/审批处理、消息持久化、step 指标和上下文压缩。`max_steps` 是防止单次循环无限推进的预算，不是并发控制、队列容量或崩溃接管机制。
- `conversation_id` 会影响上下文消息和隔离 Block 的装配；它不是 `run_id`，不能用会话 ID 代替一次可取消执行的账本。
- 工具调用之后可能继续下一 step，也可能因工具规则、审批、取消、错误或 end turn 结束；客户端看到的最后一个流事件不必然等于数据库事实已经提交。
- `finally` 路径会尽力补写 stop reason、Run 指标和失败状态，但这仍是进程内异常处理；宿主突然退出时不能执行 finally，必须依赖持久 Run/Message 账本和另行的 abandoned/recovery 策略。

因此，真实交互线至少有四种不同的状态投影：AgentState 资源快照、Conversation 上下文、Run/Step 执行账本、Message/Redis stream 事实或投影。将它们合并为“当前 Agent 状态”会丢失并发、重放和恢复语义。

## 12.3 Memory/Block 与 ORM 一致性

`Memory` 是提示上下文的组合视图，不是单一持久化表。标准 Block 会被渲染进 `<memory_blocks>`；git-enabled 路径只渲染 `system/*` 并把文件工作树投影到提示。文件 block 去重、只读、字符上限和 `human`/`persona` 类型转换属于装配约束，不等于数据库事务。

ORM `Block` 提供 `version` 与 SQLAlchemy `version_id_col` 的乐观并发控制、`current_history_entry_id` 历史指针、组织/项目/模板作用域以及 Agent/Conversation/Group 关联。该设计能防止部分并发覆盖，但不能单独保证：

- Block 更新与 Agent/Message/Run 记录跨表原子提交；
- Git 工作树、对象存储上传、临时 checkout 和 ORM history 同步提交；
- 进程崩溃后从半写文件、半上传对象或旧 history pointer 自动恢复；
- 只读、路径安全和秘密脱敏在所有 executor/HTTP/Git 入口一致执行。

`GitOperations` 使用 `tempfile`、Git 子进程和对象存储全量/增量上传。正常与异常路径有删除临时目录的意图，但当前核对没有执行取消、SIGKILL、磁盘满、Git 冲突、上传半失败或残留扫描，因此不能把“finally/shutil.rmtree 存在”写成恢复通过。

## 12.4 Tool、审批与取消传播

`ToolExecutionManager` 通过 `ToolType` 工厂选择 core、builtin、file、MCP 或 sandbox executor，返回统一 `ToolExecutionResult`，并按 `return_char_limit` 截断结果。工具 ORM 同时保存 schema、源码/来源、依赖、审批默认值和并行执行开关。

审计得到的正确边界是：

- Tool ORM 只描述能力和策略；executor 才拥有 sandbox、MCP、stdio、子进程、临时目录或文件句柄。
- 业务异常和普通异常会被包装成 error result；`asyncio.CancelledError` 也被转换为 error result 并进入计数器 finally。它保证调用方获得结构化结果，但不等于每一种 executor 都已经证明杀死子进程组、关闭 MCP、回收 sandbox 和清理监听器。
- 返回截断是上下文预算保护，不是审计删除；若完整结果需要留存，应进入受权限控制的运行账本，不能通过普通消息或 stderr 泄露秘密。
- 审批 request/response 是消息状态，等待审批不应标记为工具完成；重复审批、拒绝、Run cancel 和客户端断连必须按 tool_call/request ID 幂等处理。

当前源码和测试显示取消检查可能发生在 step 边界、流包装层和 Redis 取消感知层。它们是多个触发点而非一个全局取消事务：Run 状态、队列 item、LLM 请求、工具 executor、SSE processor、DB session 必须分别收敛，否则会出现“Run 已 cancelled 但工具仍运行”或“流已 DONE 但事实尚未提交”的窗口。

## 12.5 ORM、Redis/SSE、Jobs/Scheduler 的持久性分层

历史 V1 的持久性应分成四级，不能混称：

| 层 | 真实职责 | 丢失/恢复语义 |
|---|---|---|
| SQLAlchemy + PostgreSQL/SQLite + Alembic | Agent、Block、Conversation、Message、Run、Step、Job、Tool 事实及索引/约束 | session 正常 commit、异常 rollback；`CancelledError` 显式 rollback；未提交事务随连接/进程失败丢失 |
| Redis Stream | 按 Run 缓冲 SSE chunk、`seq_id`、TTL、长度上限和 cursor 读取 | 可短期断线续读；TTL、trim、未 flush buffer、Redis 故障不恢复 ORM 事实 |
| APScheduler + PostgreSQL advisory lock | 轮询 LLM batch jobs 的单实例 leader 选择 | 只保护 scheduler leader；不是 Run lease、fencing token 或每个任务的崩溃接管 |
| Agent loop 内存对象/asyncio task | 当前 step、响应列表、取消检查、流 generator 和临时资源 | 进程退出即丢；不能靠重新加载 AgentState 恢复未提交的执行位置 |

`RedisSSEStreamWriter` 按大小/时间批量 `XADD`，写入 TTL，并在失败时把 batch 放回内存 buffer；`create_background_stream_processor` 用 `aclosing` 关闭上游 generator，在自然结束无 terminal event 时合成 error/DONE，在取消或异常时尝试写 terminal marker 并更新 Run。该设计改善了客户端可终止性和短期重放，但也明确暴露两个事实：

1. Redis 的 `[DONE]` 只说明流投影已终止，不证明 Message/Step/Run 的完整事务已经提交。
2. finalizer 的再次 `mark_complete` 是保护性重复写，不能替代 stream entry 幂等、跨实例 writer fencing 或 Redis durability 保证。

`DatabaseRegistry.async_session` 对取消单独 rollback、`expunge_all`、close 并归还连接，这是正确的资源责任边界；但真实连接断开、连接池耗尽、数据库 failover、提交成功后响应丢失和重复请求的端到端语义没有在当前核对运行验证。

## 12.6 状态、取消、崩溃与恢复判定

历史代码可确认的终态包括 `created`、`completed`、`cancelled`、`failed` 以及 step 层的 pending/success/failed；stop reason 还细分 end turn、max steps、tool rule、context overflow、LLM error、requires approval 等。审计裁决如下：

- **已接受不等于已完成**：请求进入 background stream、Run 创建或 Redis 写入，只表示某一层接受，不能表示 Agent loop 已完成。
- **断连不等于取消**：HTTP/WS/SSE 客户端断开可能触发 task cancellation，也可能只是消费端消失；必须由服务端明确更新 Run 并向模型/工具传播取消。
- **取消不等于回滚所有事实**：取消前已提交的 user/tool/approval/message 仍是事实；取消后的新 step、半成品 stream 和未提交 ORM 改动要有明确取舍，不能靠清空内存列表修复。
- **崩溃不等于 failed 已写入**：进程在 commit、Redis flush、callback 或状态更新之间退出，会产生不同层的部分完成；启动恢复必须扫描非终态 Run、未完成 Job、过期 stream、临时 Git/锁和外部工具残留。
- **scheduler leader 不等于执行 owner**：advisory lock 释放后可由新实例接管轮询，但代码没有因此为每个 Run/Batch item 提供 generation、heartbeat、fencing 或 CAS 防旧实例继续写入。

当前核对没有发现可把 `Run`、Redis stream 或 advisory lock直接升级为通用持久租约的证据。底座若要支持恢复，仍需单独的 execution intent、owner/generation、deadline、cancel intent、幂等 release、reclaim 和 recovery decision 账本。

## 12.7 测试、配置与文档质量审计

- 测试目录覆盖 agent tool graph、async sandbox、batch/cron、cancellation、conversation、Git push sync、HITL、MCP、summarizer、managers、SDK 和性能场景；取消测试明确检查消息与 `agent.message_ids` 不脱节，并验证取消后可继续运行。这些是良好的回归意图，但不是当前核对执行通过证据。
- 多个集成测试依赖 `LETTA_SERVER_URL`、Redis、数据库、LLM provider key 或外部 sandbox；缺少环境时通过 `skipif`、配置选择或 fixture 分支跳过/降级。测试数量因此不能直接等价于故障矩阵覆盖率。
- 测试同时混合本地 server thread、外部已运行 server、真实 provider 和 AsyncMock；若没有固定依赖版本、数据库隔离、Redis 清理、临时目录清理和进程终止报告，失败归因和资源泄漏难以稳定复现。
- `pyproject.toml` 清楚声明 Python `<3.14,>=3.11`、可选 PostgreSQL/Redis/server/provider/sandbox 依赖和 pytest 配置；但根 `main` 的 README/CONTRIBUTING/SECURITY 已把当前开发迁移到 `letta-code`，archive 的测试/配置不能作为当前产品文档。
- 根 `ARCHITECTURE.md` 的主要文档风险不是缺少概念，而是容易把 main、letta-code 客户端、archive V1 服务端三套证据混成“当前 Letta”。本文件现用 L0/L1/L2-L4、当前/外部/历史标签显式分隔；后续新增内容必须保持同一证据纪律。

## 12.8 当前核对最终裁决与未完成验证

| 审计项 | 静态源码可确认 | 当前核对真实验证 | 结论 |
|---|---|---|---|
| Agent loop 与 stop reason | `max_steps`、tool/approval、compaction、Run/Step 更新路径存在 | 未启动 LLM/服务 | L1 结构成立，行为未验 |
| Memory/Block/ORM | Block version/history、Conversation isolated blocks、Message sequence、Alembic 演进存在 | 未执行并发写/取消提交/崩溃恢复 | 一致性设计可读，恢复未证 |
| Tool executor | 工厂分发、统一结果、截断、异常/取消包装存在 | 未运行 sandbox/MCP/stdio 强杀 | 结果契约存在，资源回收未证 |
| Redis/SSE | batching、TTL、cursor、terminal/error marker、上游 generator close 存在 | 未连接 Redis/断线/重复消费 | 短期投影设计成立，durability 未证 |
| DB session | commit/rollback/CancelledError/close 路径存在 | 未连接 PostgreSQL/SQLite | 代码意图成立，池/故障恢复未证 |
| Jobs/scheduler | APScheduler、advisory lock、retry、shutdown 释放路径存在 | 未运行多实例/抢锁/进程杀死 | leader 机制可读，不是 run lease |
| tests/config/docs | 场景、环境变量、可选依赖和迁移清单广泛存在 | 未安装依赖、未执行测试 | 覆盖意图可确认，不能声称通过 |

当前核对只修改本文件；未修改 `main` 之外的源码、测试、配置、迁移、文档或 Git 分支。剩余最高风险仍是：当前 `letta-code` 配套服务端不可由本仓库验证；archive 的 DB/Redis/scheduler 静态实现没有 L2-L4 故障证据；取消、恢复、幂等、租约/fencing 和资源残留必须在取得明确运行时源码与隔离环境后另行验证。
 # Letta 架构取证
