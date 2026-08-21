# OpenClaw 架构建档

> 建档范围：仅基于当前源码、根/相关目录规则、依赖清单、已有细探和静态目录证据；不把设计文档当作运行时证明。
> 
> 源码快照：`1fc81c20548e3323c2f5ab05cd41338b5647c726`。

## 1. 定位与总体架构

OpenClaw 是运行在用户自有设备上的 local-first 个人 AI 助手。Gateway 是控制面，不是产品本身；产品能力由 Agent、会话、工具、技能、模型和多消息通道共同组成。README 将其定位为个人助手，并列出多渠道、模型路由、工具、技能和伴随设备能力（`README.md:17-31`, `README.md:156-172`）。

### 文本流程图

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 用户与设备                                                           │
│ WebChat / Control UI / TUI / macOS / iOS / Android / 消息渠道         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ WebSocket Gateway protocol v4
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Gateway 控制面                                                       │
│ 启动预检 → 配置/Secret → 握手认证/配对 → RPC 方法注册表               │
│ 角色/Scope/限流/挂起与重启准入 → Core handler + Plugin handler         │
└───────────────┬──────────────────────┬────────────────────────────────┘
                │                      │
                │ 会话/Agent 请求      │ 控制面数据/事件/设备
                ▼                      ▼
┌────────────────────────┐   ┌─────────────────────────────────────────┐
│ Agent 运行时            │   │ Channels / Nodes / Cron / Approvals      │
│ 路由 → 会话 → Prompt    │   │ outbound delivery / pairing / broadcasts  │
│ → Model/LLM → Tools     │   └─────────────────────────────────────────┘
│ → streaming → transcript│
└───────────────┬────────┘
                │
                ├──────────────► Provider/Plugin runtime（经 Plugin SDK）
                ├──────────────► Skills / Browser / Canvas / Terminal / MCP
                └──────────────► Session/Agent state + usage + audit events

┌──────────────────────────────────────────────────────────────────────┐
│ 持久化与可靠性底座                                                   │
│ shared state SQLite + per-agent SQLite                               │
│ node:sqlite/Kysely → schema preflight → migrations → WAL/permissions │
│ snapshot repository → manifest(SHA-256) → verify → safe publish/restore│
└──────────────────────────────────────────────────────────────────────┘
```

## 2. 真实分层与目录职责

| 层 | 目录/入口 | 真实职责与边界 |
|---|---|---|
| 启动与 CLI | `openclaw.mjs`, `src/entry.ts`, `src/index.ts`, `src/cli/` | 校验 Node 版本、编译缓存重启/信号转发、解析命令、注册子 CLI、统一错误与退出码。`openclaw.mjs:11-72`、`openclaw.mjs:130-236`、`src/index.ts:48-60`。 |
| Gateway 传输/控制面 | `src/gateway/`, `src/gateway/server/` | WebSocket 服务、握手、认证、连接生命周期、请求准入、方法分发、事件广播、节点与控制 UI。公共 facade 延迟加载 `server.impl`（`src/gateway/server.ts:1-42`）。 |
| Gateway 方法层 | `src/gateway/server-methods.ts`, `src/gateway/server-methods/*.ts`, `src/gateway/methods/` | 按领域拆分 RPC handler；通过 lazy handler 按需导入，合并 core、active plugin、测试/本地 extra handler；在执行前统一做授权、session mutation 检查、节点配对状态、启动不可用、限流和挂起/重启准入（`src/gateway/server-methods.ts:52-300`, `src/gateway/server-methods.ts:889-1111`）。 |
| Agent/会话运行时 | `src/agents/`, `src/agents/sessions/`, `src/agents/embedded-agent-runner/`, `src/sessions/`, `src/transcripts/` | Agent workspace、session key/session id、Prompt 与模型执行、工具调用、流式结果、transcript DAG、压缩/重放/用量与投递。`src/gateway/server-methods/AGENTS.md:1-3` 明确 transcript 必须通过 `SessionManager.appendMessage` 保持 `parentId` 链。 |
| 配置/路由/模型 | `src/config/`, `src/routing/`, `src/model-catalog/`, `src/llm/` | 读取 canonical 配置、agent/channel/provider 路由、模型目录、认证 profile、failover 与传输准备；启动时配置快照先于运行时激活。 |
| 插件控制平面 | `src/plugins/`、`extensions/*/*.plugin.json` | manifest 发现、校验、配置 schema、安装/更新/卸载、能力目录、激活计划、轻量 public artifact。规则要求 discovery/config/setup 尽量不加载插件重运行时（`src/plugins/AGENTS.md:22-47`）。 |
| 插件运行平面 | `extensions/`, `src/plugins/runtime/`, `src/plugin-sdk/`, `packages/plugin-sdk/` | channel、provider、memory、media、browser、MCP 等插件实现；插件只经 `openclaw/plugin-sdk/*`、manifest、注入 helper 和公开 barrel 跨入核心（`AGENTS.md:55-65`）。 |
| 协议/共享包 | `packages/`，重点为 `gateway-protocol`, `gateway-client`, `plugin-sdk`, `ai`, `llm-core`, `memory-host-sdk`, `net-policy` 等 | 可复用契约、运行时类型、协议 schema/validators、客户端和安全/媒体/重试等窄 SDK。已有细探记录为 23 个共享 SDK 包，实际包目录以当前 checkout 为准。 |
| 安全与执行 | `packages/plugin-sdk/src/security-runtime.ts`、`packages/net-policy/`、`src/security/audit/`、`src/process/`、`src/infra/` | 路径/符号链接/原子写/secret 比较/SSRF/网络策略、命令审批、进程超时、审计和系统能力边界。 |
| 持久化 | `src/state/`, `src/infra/sqlite-*`, `src/agents/*db*` | shared state DB、per-agent DB、SQLite schema/migrations、WAL、strict schema、quarantine、lease、Kysely 访问和权限。根规则规定运行时状态使用 SQLite，不新增 JSON/JSONL sidecar（`AGENTS.md:77-88`）。 |
| 快照与恢复 | `src/snapshot/`, `src/infra/sqlite-snapshot.ts` | 受信目录、私有权限、SQLite artifact、manifest、SHA-256、文件身份/硬链接/符号链接检查、发布和恢复验证。 |
| UI/原生应用 | `ui/`, `apps/macos/`, `apps/ios/`, `apps/android/`, `apps/linux/`, `apps/swabble/` | Control UI、WebChat/工作台以及可选原生 companion/node；通过 Gateway 协议消费控制面，不是 Gateway 核心的插件实现。 |
| 测试/构建/文档 | `test/`, `src/**/*.test.ts`, `packages/**/src/**/*.test.ts`, `scripts/`, `docs/` | Vitest 项目矩阵、行为/协议/边界/E2E/live/Docker 测试，tsgo、lint、架构检查、构建、文档和发布辅助。 |

## 3. 启动与关键路径

### 3.1 CLI/启动路径

```text
openclaw.mjs
  → Node 版本/Bun 拒绝与编译缓存策略
  → source checkout 下 respawn（必要时关闭编译缓存）
  → src/index.ts
  → runLegacyCliEntry() → src/cli/run-main.ts
  → Commander 子命令注册与 lazy command group
  → gateway 子命令
  → startGatewayServer(port=18789, options)
```

`package.json` 将二进制指向 `openclaw.mjs`，模块入口为 `dist/index.js`（`package.json:1-24`, `package.json:353-355`）。源码 CLI 通过 `src/index.ts` 延迟加载 `run-main.js`（`src/index.ts:48-60`）；Gateway facade 再动态加载完整 server implementation（`src/gateway/server.ts:19-35`）。

Gateway 启动首先做 state/agent SQLite schema preflight；发现新版本不兼容 schema 时记录数据库身份、已发现版本、支持版本和文档 URL 后拒绝启动（`src/gateway/server.impl.ts:600-647`）。之后初始化网络运行时，读取配置快照，处理 Control UI origin seed、runtime secrets、auth bootstrap 和插件 metadata snapshot（`src/gateway/server.impl.ts:647-751`）。

### 3.2 Gateway 请求路径

```text
WS client connect
  → handshake + auth/pairing
  → GatewayClient（role/scopes/device/user/pairing state）
  → handleGatewayRequest()
  → method registry（core + active plugin + extra）
  → authorize scope/role
  → session mutation authorization
  → node pairing freshness / startup availability
  → control-plane write rate limit
  → suspend/restart root-work admission
  → plugin request scope
  → domain handler
  → respond(ok,payload,error) + broadcast/events
```

方法 registry 在每次请求路径上可使用连接附带的 registry；若其不拥有方法，则从活动插件注册表重建，以覆盖启动快照后注册的插件方法（`src/gateway/server-methods.ts:889-941`）。请求分发器先授权，再处理 session mutation、节点配对变化、启动不可用、未知方法、控制面写限流和挂起/重启准入（`src/gateway/server-methods.ts:942-1071`），最终在插件 runtime request scope 中运行 handler（`src/gateway/server-methods.ts:1073-1111`）。

### 3.3 Agent 与会话数据流

```text
channel / UI / CLI message
  → Gateway send/chat/agent method
  → session key 解析与 session ownership
  → agent workspace + session manager
  → prompt/context/skills/tool policy
  → provider/model transport
  → streaming chunks / tool calls / approvals
  → transcript append（parentId 链）
  → usage/status/events
  → channel delivery / UI broadcast / Gateway response
```

这是“架构路径”而非单一函数调用：具体 provider、channel、tool 和 worker 由 plugin/runtime registry 与配置选择。请求上下文明确持有 cron、model catalog、node registry、approval manager、broadcast、session observer、worker placement、terminal session 等运行服务（`src/gateway/server-methods/shared-types.ts:152-259`）。

### 3.4 插件生命周期路径

```text
插件安装目录/扩展目录
  → manifest-first discovery
  → manifest/config schema/依赖/边界校验
  → public/light artifact 与 CLI/setup metadata
  → activation plan / runtime registry
  → plugin API + SDK hooks/provider/channel/tool registration
  → Gateway method/channel/provider/tool execution
```

插件定义和注册类型集中在 `src/plugins/types.ts`，公共 facade 导出 Agent tool、hook、provider、worker、MCP connection、gateway discovery 等窄类型（`src/plugins/types.ts:7-119`, `src/plugins/types.ts:152-254`）。manifest 类型当前至少包含 `openclaw`/`bundle` 格式和诊断码（`src/plugins/manifest-types.ts:14-36`）。

### 3.5 SQLite 状态路径

```text
Gateway start / feature use
  → schema preflight
  → shared state DB: state/openclaw.sqlite
  → per-agent DB: agents/<agentId>/agent/openclaw-agent.sqlite
  → node:sqlite + Kysely synchronous transaction
  → WAL/foreign keys/strict schema/permissions
  → migration/quarantine/audit rows
```

shared state DB 负责共享持久状态、schema creation、additive migration、私有权限和迁移/备份审计（`src/state/openclaw-state-db.ts:1-93`）；其维护逻辑使用 immediate transaction、schema version、strict typing 和 canonical schema（`src/state/openclaw-state-db.ts:144-209`）。每个 agent DB 按 normalized agent id 归属、缓存 pathname、加私有权限，并向 shared state registry 注册（`src/state/openclaw-agent-db.ts:78-83`）；正常打开会校验 schema/owner/quarantine，incognito 路径使用内存 SQLite 且禁止落盘（`src/state/openclaw-agent-db.ts:179-231`）。

### 3.6 SQLite 快照路径

```text
source SQLite
  → private staging dir
  → copy/hash artifact（拒绝 hardlink/symlink）
  → manifest.json（schemaVersion/snapshotId/database/artifact SHA-256）
  → publish with identity and exact-content checks
  → verify(ref)
  → restore/copy only after verification
```

manifest 只接受严格键集合、schemaVersion=1、安全 snapshot id、SQLite database identity、`database.sqlite` artifact、64 位十六进制 SHA-256 和正整数 size（`src/snapshot/manifest.ts:15-20`, `src/snapshot/manifest.ts:156-220`）。artifact hash 通过受信 root 打开并拒绝 hardlink/symlink；复制使用独占创建、0600 权限和多次 file identity 检查（`src/snapshot/manifest.ts:39-89`）。本地 provider 在 staging/publish/verify 阶段检查目录身份、pending marker、manifest、artifact hash 和精确目录内容（`src/snapshot/local-repository.ts:222-389`）。

## 4. API、CLI、SDK 与协议面

### 4.1 Gateway WebSocket RPC

`@openclaw/gateway-protocol` 是 TypeBox-backed schema、推导 TypeScript 类型和运行时 validator 的协议包；当前 wire protocol 为 v4，一般客户端必须 v4，认证 node/probe 在滚动升级窗口可使用 N-1（`packages/gateway-protocol/README.md:1-21`）。版本常量真实值为 `PROTOCOL_VERSION=4`、general client minimum=4、node/probe minimum=3（`packages/gateway-protocol/src/version.ts:1-8`）。

协议入口包括：

- 根入口：runtime validators、selected schemas、错误格式化和类型；
- `schema`：完整 TypeBox schema graph 与 `ProtocolSchemas`；
- `frame-guards`：无 TypeBox 的事件/响应 envelope guard；
- `client-info`、`connect-error-details`、`gateway-error-details`、`startup-unavailable`、`version`：轻量握手与恢复契约（`packages/gateway-protocol/README.md:24-53`）。

主要 RPC 领域由 server-methods lazy modules 实现，实际清单覆盖 agent、agents/workspace、artifacts、audit、board、channels/pairing、chat、config、cron、devices/nodes、doctor、environments/worktrees、exec approvals、fs、health、logs/terminal、models、plugins/migrations、restart/suspend/send、sessions、skills、system/talk/tasks/tools、TTS、update、usage、voicewake、web 等（`src/gateway/server-methods.ts:52-300`）。方法发现列表是保守广告，不等于所有合法 schema 方法；插件提供、角色专属和未广告方法仍可能有效（`packages/gateway-protocol/README.md:145-158`）。

### 4.2 CLI

README 记录的公开操作路径包括：

- `openclaw onboard --install-daemon`：初始化 Gateway、workspace、channels、skills 和用户服务；
- `openclaw gateway status|start|stop`，前台 `openclaw gateway --port 18789 --verbose`；
- `openclaw message send --target ... --message ...`；
- `openclaw agent --message ... --thinking high`；
- `openclaw pairing approve <channel> <code>`、`openclaw doctor`、`openclaw nodes ...`、`openclaw devices ...`。

这些不是独立 HTTP API，而是 CLI → Gateway/本地服务/状态库的运维入口，示例见 `README.md:94-137`、`README.md:141-154`、`README.md:221-255`。CLI 子命令支持 eager/lazy 注册策略，`completion` 通过动态 import 注册（`src/cli/program/register.subclis.ts:1-76`）。

### 4.3 Plugin SDK 与共享包

`package.json` 将根包导出为 `dist/index.js`，并公开大量 `./plugin-sdk/*` 子路径；这些子路径按 core、runtime、routing、health、setup、channel、approval、config、provider、memory、MCP 等职责拆分（`package.json:353-480`）。插件公共 facade 以类型与注册契约为主，避免让插件依赖核心内部实现（`src/plugins/types.ts:1-6`, `src/plugins/types.ts:111-152`）。

插件可以注册 provider/channel/tool/hook、Gateway discovery/HTTP route、node command、service、migration、auth/catalog/replay/transport 等；跨边界依赖应使用 plugin SDK 和公开 barrel，而不是 `src/**` 或其他插件内部（`AGENTS.md:55-65`, `src/plugins/AGENTS.md:6-20`）。

### 4.4 HTTP/MCP/节点边界

依赖清单包含 `@modelcontextprotocol/sdk`、`express`、`ws`、`playwright-core` 等；Gateway 协议源码存在 `mcp-http.schema.ts`，插件类型也包含 MCP connection 与 HTTP route surface。它们证明仓库具备这些边界，但本建档未启动 Gateway、未发真实请求，因此具体启用条件、认证模式和部署拓扑列为未确认项。

## 5. 技术栈与依赖结构

| 类别 | 实际证据 |
|---|---|
| 主语言 | TypeScript ESM，根 `package.json` `type=module`；根/Scoped AGENTS 要求 TS strict。 |
| 运行时 | Node.js 22.22.3+、24.15+（推荐）、25.9+；`openclaw.mjs:11-72` 做运行时拒绝；Bun 被拒绝，因为依赖 `node:sqlite`。 |
| 包管理 | pnpm workspace；README 明确 source checkout 用 pnpm，根目录不支持直接 `npm install`（`README.md:221-255`）。锁文件为 `pnpm-lock.yaml`。 |
| CLI | Commander 15，`openclaw.mjs` 二进制 launcher，`src/cli/` command groups。 |
| Gateway/网络 | WebSocket `ws`、Express 5、undici、TypeBox gateway protocol、MCP SDK；Gateway protocol 独立包。 |
| Schema/验证 | TypeBox 1.3.6、Zod 4.4.3；gateway protocol 提供运行时 validators。 |
| 数据库 | Node `node:sqlite`、Kysely 0.29；shared state 与 per-agent SQLite，WAL、foreign keys、strict schema、同步短事务。 |
| Agent/AI | OpenAI/Anthropic/Google/Mistral SDK、内部 `packages/ai`/`llm-core`、多 provider plugin、媒体/语音/视频包。 |
| 前端 | `ui/` Vite 8 + Lit 3 + Vitest；原生 companion 位于 `apps/`，另有 Swift/Kotlin/Android/iOS 工具链。 |
| 测试 | Vitest 4，多个 `test/vitest/vitest.*.config.ts` 项目配置；colocated `*.test.ts`、`*.e2e.test.ts`。 |
| 安全/工具 | `@openclaw/fs-safe`、`proper-lockfile`、`tar`、`jszip`、`semver`、`playwright-core`、`quickjs-wasi` 等。 |

依赖清单的根生产依赖和开发依赖以 `package.json` 的 `dependencies`/`devDependencies` 为准；本次未安装或解析 lockfile，未对第三方版本做运行时兼容性判断。

## 6. 测试、质量门禁与验证方式

### 测试布局

- 单元/行为测试：生产模块同目录 `*.test.ts`；
- 协议测试：`packages/gateway-protocol/src/**`；
- Gateway 测试：`src/gateway/**` 与 `test/gateway*.test.ts`；
- 插件/边界测试：`src/plugins/**`、`extensions/**`、`test/vitest/vitest.contracts-*`；
- UI 测试：`ui/src/**/*.test.ts`、browser/e2e tests；
- E2E/live/Docker：`test/e2e/`、`test/scripts/`、`scripts/e2e/`，需要更重的运行环境；
- 类型与静态检查：`tsgo:*`、`check:architecture`、import-cycle/madge、Kysely guardrail、plugin boundary、dependency ownership、docs/format/lint checks。

根测试规则明确 Vitest 项目隔离、fake timers 必须进入专用配置，并要求清理 timers/env/globals/mocks/sockets/temp dirs（`test/AGENTS.md:1-3`, `AGENTS.md:296-312`）。Gateway scoped rules要求共享 suite server/client、手动 RPC 默认关闭 scheduler/poller，并在 lazy-loading 或 bundled plugin artifact 变更时构建（`src/gateway/AGENTS.md:17-30`）。

### 本次验证边界

本次只新增/更新根 `ARCHITECTURE.md`，没有安装依赖、启动服务、构建、运行项目测试或提交 Git。仅应使用文档/差异检查验证该建档文件；源码快照与现有未跟踪 `细探-openclaw.md` 均未改动。

## 7. 未确认项与剩余风险

1. **代码地图不可用**：目标项目未发现 `.codegraph/`，`codegraph_explore` 明确返回无法索引；本建档的代码地图查询记录为“目标项目无 `.codegraph/`，未取得目标项目 CodeGraph 符号/调用图”，因此分层与调用链均以人工静态读取为依据。
2. **MCP 项目身份不匹配**：首轮 `project_context` 返回的项目名称/根目录是另一个项目（`华世王镞_v3`），不是本目标 `openclaw`；其代码地图和最近成功验证不能作为 OpenClaw 的代码证据，已明确排除，不在本文中冒充目标项目验证。
3. **运行态未确认**：未启动 Gateway、未连接 WebSocket、未验证端口、握手认证、pairing、RPC 响应、事件广播、plugin HTTP/MCP 或 channel delivery。
4. **完整 RPC 表未冻结**：server-methods 是持续扩展的领域注册表；本文列出真实领域和关键机制，不承诺完整 method 名单。以协议 schema 与当前 handler registry 生成结果为准。
5. **Provider/Plugin 实现规模未逐一审计**：extensions 数量和各插件依赖/启用条件来自目录与已有细探；没有逐插件验证依赖、manifest hash、启动性能和运行时兼容性。
6. **数据库表级模型未全文展开**：已确认 shared/per-agent SQLite、schema preflight、Kysely、WAL、strict schema、迁移和 quarantine；具体表字段/索引/迁移版本应继续读取 generated schema 与各迁移 owner 后再形成表级数据字典。
7. **快照“激活”调用方未完全闭合**：已确认 create/publish/verify/restore 安全实现；不同业务 owner 如何选择 active snapshot、切换指针及恢复后的上层重启策略，需进一步从调用方和运行态验证。
8. **当前依赖安装状态未确认**：仅读取 `package.json` 和仓库内配置，没有读取 `node_modules` 版本或运行安装检查；不据此声称源码可立即构建。

## 8. 证据索引

- 产品定位与开发入口：`README.md:17-31`, `README.md:94-172`, `README.md:221-284`。
- 仓库边界、架构与测试政策：`AGENTS.md:43-120`, `AGENTS.md:257-312`。
- 启动器与 CLI：`openclaw.mjs:11-72`, `openclaw.mjs:130-236`, `src/index.ts:48-140`, `src/cli/program/register.subclis.ts:31-76`。
- Gateway facade/startup：`src/gateway/server.ts:1-42`, `src/gateway/server.impl.ts:600-751`。
- Gateway RPC registry/authorization/dispatch：`src/gateway/server-methods.ts:52-300`, `src/gateway/server-methods.ts:889-1111`, `src/gateway/server-methods/shared-types.ts:61-112`, `src/gateway/server-methods/shared-types.ts:152-259`。
- Protocol v4 与 schema entrypoints：`packages/gateway-protocol/README.md:1-21`, `packages/gateway-protocol/README.md:24-74`, `packages/gateway-protocol/README.md:111-158`, `packages/gateway-protocol/src/version.ts:1-8`。
- SQLite state ownership：`src/state/openclaw-state-db.ts:1-93`, `src/state/openclaw-state-db.ts:144-209`, `src/state/openclaw-agent-db.ts:78-83`, `src/state/openclaw-agent-db.ts:179-231`。
- Snapshot integrity：`src/snapshot/manifest.ts:15-20`, `src/snapshot/manifest.ts:39-89`, `src/snapshot/manifest.ts:156-220`, `src/snapshot/local-repository.ts:222-389`。
- Plugin contracts/boundaries：`src/plugins/types.ts:1-6`, `src/plugins/types.ts:111-152`, `src/plugins/manifest-types.ts:14-36`, `src/plugins/AGENTS.md:22-86`。
- 本文件已吸收此前 `细探-openclaw.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 9. 第三轮：通用底座映射与唯一链路裁决

### 9.1 映射口径

本轮不是把 OpenClaw 的目录直接复制为平台目录，而是把源码中已经出现的**契约、所有权、生命周期和故障围栏**映射为四种可复用边界：

- **支持库**：无业务路由的原子能力、类型/协议、规范化、安全、资源句柄和可测试基础设施。它可以被多个模块复用，但不能持有某个渠道的业务状态。对应当前源码的 `packages/*`、`src/infra/*`、`src/process/*`、`src/plugin-sdk/*` 等窄边界。
- **模块库**：一个领域流程的组合器，负责把支持库拼成 Channel turn、模型解析、插件注册、文件/终端/浏览器、队列投递等可复用流程；不对外承担连接认证和不复制 Gateway 方法。对应 `src/channels/turn/*`、`src/agents/*`、`src/plugins/*`、`src/infra/outbound/*`、`src/gateway/worker-environments/*` 等。
- **运行核心**：跨渠道必须一致的执行所有权和状态机：`sessionId/runId/turnId`、epoch/generation fence、模型/工具执行、transcript parentId、事件 seq、资源 claim、取消/超时和崩溃恢复。它只能通过公开契约调用插件和 provider，不反向知道具体渠道。
- **网关**：控制面和适配面：WebSocket/HTTP/CLI 入口、握手认证、role/scope、RPC registry、事件广播、节点/插件/渠道接入与运维 admission。网关编排核心能力，但不另造一套 Agent turn、模型调用、工具执行或持久投递链。

第三轮固定原则：一个原子能力只有一个规范 id、一个契约 owner、一个注册/调用路径；provider/channel/plugin 是策略或适配，不得成为第二个运行核心。以下“吸收/升级/新建/废弃/待核”是平台映射裁决，不代表对 OpenClaw 源码实施改造。

### 9.2 能力命中与四层落点表

| 能力 | 源码事实与证据 | 支持库落点 | 模块库/运行核心落点 | 网关落点 | 第三轮裁决 |
|---|---|---|---|---|---|
| Gateway | `src/gateway/server.ts` 延迟加载实现；`src/gateway/server-methods.ts:52-220` 建立领域 lazy handlers，`src/gateway/server-methods.ts:889-1111` 进行 registry、角色/scope、session mutation、限流、挂起/重启准入和 plugin request scope。 | `packages/gateway-protocol` 的 TypeBox schema、validator、错误/版本；`packages/gateway-client` 的客户端契约。 | 运行核心只暴露 command/query/event facade；方法 handler 只能调用核心 owner。 | WS 握手、auth/pairing、RPC registry、scope/role、broadcast、节点和控制 UI。 | **吸收** Gateway 作为唯一控制面；**废弃** 每个渠道或模块自建 RPC/鉴权链；协议 v4 和方法名以当前源码为基线。 |
| Channel | `src/channels/plugins/types.plugin.ts:48-118` 的 `ChannelPlugin` 拆 config/setup/security/pairing/outbound/gateway/streaming/threading/actions；`src/channels/turn/kernel.ts:43-57` 统一 dispatch；`src/channels/turn/lifecycle.ts:47-73` 从 route 解析 agent/session/store。 | 渠道 id、目标/账号/消息、能力矩阵、reply payload、错误和 delivery outcome 类型；消息规范化与媒体访问应保持窄 SDK。 | `src/channels/message/ingress-queue.ts` 接收/claim/去重；`src/channels/turn/*` 做 preflight→admission→turn→delivery；路由只产出统一 `agentId/sessionKey`。 | 只负责 webhook/WS/CLI 接入、渠道账户状态、pairing、消息 RPC 和最终事件/投递可见性。 | **吸收** 多渠道适配器 + 单一 turn kernel；**升级** 统一 ingress/outbound queue 和 receipt；**废弃** 渠道插件直接启动独立 Agent 链。 |
| Session | 现有 `src/state/openclaw-agent-db.ts`、`src/agents/sessions/SessionManager`、`src/config/sessions/*`；`src/gateway/server-methods/AGENTS.md` 明确 transcript 必须由 `SessionManager.appendMessage` 保持 `parentId` 链；`src/gateway/worker-environments/*` 用 placement/owner epoch。 | session key/id、agent scope、transcript entry、parentId、lease/claim、幂等与版本化记录类型；SQLite/Kysely/迁移是持久化支持。 | 运行核心拥有 session admission、turn claim、session reset、transcript append、model/tool context 和恢复；`channel/turn` 只提供 route/session 输入。 | `sessions.*` RPC、session mutation authorization、Control UI session events；不能绕过核心写 transcript。 | **吸收** session 作为跨渠道唯一执行归属；**升级** 将 `sessionId + runId + turnId + epoch/generation` 固化为资源句柄；**废弃** 以 channel/account 独立 session 表示同一会话。 |
| Plugin | `src/plugins/AGENTS.md` 要求 control-plane/runtime-plane 分离、manifest-first、light artifact、lazy activation；`src/plugins/types.ts:111-152` 导出 provider/worker/migration/command 等公共契约；`src/plugins/runtime/gateway-request-scope.ts:10-92` 以 `AsyncLocalStorage` 保存 request/plugin identity。 | manifest/schema、SDK entrypoint、能力描述、版本和权限声明；`src/plugin-sdk/AGENTS.md` 要求窄、稳定、懒加载的公开子路径。 | loader/activation plan/registry；运行时以 request-scoped plugin handle 调用 hook/provider/channel/tool，不依赖可变全局 registry 作为 request 真相。 | 插件发现、配置、安装/更新/卸载、Gateway method/HTTP route descriptor、runtime scope 和审计。 | **吸收** manifest-first + light/heavy 双面；**升级** 插件能力必须绑定 owner/权限/资源预算；**废弃** plugin 直接 import `src/**` 或以私有 backdoor 穿透核心。 |
| Tool | `src/agents/tools/*` 由 Agent runtime 组装；`src/plugins/tool-grant-allowlist.ts:10-31` 将 pluginId+toolName 归一化为 grant key；`src/agents/tools/terminal-tool.ts:142-220` 校验 agent session、launch policy、signal 和迟到 terminal cleanup。 | 工具 schema、参数/结果/错误、名称规范化、SSRF/path/approval primitives；`packages/tool-call-repair`、`packages/net-policy` 和 `plugin-sdk` 是候选窄支持库。 | tool registry/policy、工具执行 context、审批、工具结果写 transcript/event；终端、web、message、MCP 分别是模块，不得把宿主句柄放进模型 payload。 | tool discovery、权限可见性、operator approval、节点 command allowlist；不能因“工具可见”就绕过 execute-time policy。 | **吸收** schema 与执行分离、grant 绑定插件 owner；**升级** 每次执行显式传 `run/session/plugin/tool` 句柄；**废弃** 全局 tool allowlist 作为唯一授权依据或插件自报身份。 |
| Model | `src/gateway/worker-environments/inference-runtime.ts:377-475` 解析 agent/config/catalog/alias/visibility policy 并取得 prepared runtime lease；`inference.ts:234-385` 做 fence、AbortSignal、流事件 seq、大小上限和 terminal store；`packages/llm-core`/`packages/ai` 提供共享 AI/transport。 | model ref、catalog、provider transport、stream event、usage/cost、retry/timeout 和 auth profile 类型/工具；`packages/model-catalog-core`、`packages/llm-core`、`packages/retry`。 | 运行核心拥有 approved-model admission、prepared runtime lease、provider stream、tool-call stream、usage、terminal outcome 和 transcript commit。 | `models.*` 查询/探针/配置、auth status；网关不能直接持有 provider SDK 会话。 | **吸收** catalog→policy→prepared lease→stream→terminal；**升级** provider 统一 transport 和终态；**废弃** 各渠道/插件自建模型 fallback 或把 provider 对象穿透层边界。 |
| Browser | `src/plugin-sdk/browser-types.ts:1-73` 定义 profile/CDP/userDataDir/driver/attachOnly/cleanup/SSRF；`src/agents/sandbox/browser.ts`、`src/plugin-sdk/browser-*`、`src/browser-lifecycle-cleanup.ts:21-43` 管理 profile/session/tab；`src/infra/browser-open.ts:34-124` 仅允许 HTTP(S) 并以 5s 命令超时打开系统浏览器。 | URL/SSRF policy、CDP/profile/tab 句柄、action timeout、path/credential redaction、cleanup primitive。 | browser module 按 session 取得 profile/tab handle，动作执行受 session/agent policy，结束、取消、超时和崩溃均进入 cleanup；宿主不把 CDP socket/Playwright Page 放入持久状态。 | browser control/inspect/open、node browser proxy policy、权限与 profile 选择；只暴露 descriptor/结果。 | **吸收** profile+CDP handle+best-effort cleanup；**升级** 为 session-owned lease、逐 tab 释放和 orphan sweep；**待核** 远程 CDP/Playwright 的每个 provider 在运行态的断线重连与跨重启行为。 |
| 文件 | `src/infra/fs-safe.ts:12-60` 重导出 root/read/write/walk/symlink/hardlink/size/timeout 安全能力；`src/gateway/server-methods/fs.ts:26-100` 对节点命令、connId、pairing generation 和结果 schema 做检查；state/snapshot 另有 hash/manifest/原子发布。 | `@openclaw/fs-safe`、path root、atomic sibling temp、hash/manifest、secure file handle；文件句柄只允许在 owner scope 内借用。 | file module 负责 workspace/artifact/snapshot/transcript 的读写事务、临时文件和 cleanup；核心记录 `artifactRef`/manifest，而非裸绝对路径。 | `fs.listDir`、artifacts、workspace RPC；任意宿主路径是 operator.admin 风险面，节点路径必须经 command allowlist。 | **吸收** root-scoped、安全读写、manifest/hash、节点能力核验；**升级** 所有跨层文件传递改为受限 `FileRef` + owner/expiry；**废弃** JSON/JSONL sidecar、裸路径跨插件传递、临时文件无 manifest。 |
| 进程 | `src/process/child-process-tree.ts:8-24` 进程树 SIGTERM/SIGKILL；`src/process/child-process.ts:14-80` 处理继承 pipe 的迟到输出释放；`src/agents/bash-process-registry.ts:112-180,193-282` 维护 running/finished、输出上限、TTL、stdio/listener 清理；worker launcher 通过独立 worker 环境和 tunnel 运行。 | spawn plan、signal/timeout、process tree、output cap、supervisor、PTY/stdio handle；`packages/terminal-core` 和 `src/process/supervisor/*`。 | process/worker module 持有 process group/worker placement/credential epoch；核心负责 admission、cancel、terminal outcome、reclaim/redispatch 和残留检查。 | terminal/process RPC、exec approval、worker placement 运维；网关只下发受 policy 的命令，不在 handler 中直接长期持有 child。 | **吸收** 子进程隔离 + process tree kill + bounded output + finished TTL；**升级** 每个 process handle 绑定 run/session/owner epoch；**废弃** 仅 kill 直接 child、无 TTL 的后台 session 和取消后放任 orphan。 |
| 事件 | `src/infra/agent-events.ts:35-167` 以 stream/runId/seq/ts/session/agent 标记事件并用 lifecycle generation/AsyncLocalStorage；`live-events.ts:36-75,153-213` 管理 pending bytes、ACK、active/terminal runs、credential rotation；worker inference frame 带 seq/terminal。 | event envelope、seq/epoch、error/terminal、redaction、listener、bounded buffer；协议 schema 是唯一 wire contract。 | 运行核心拥有事件生成、顺序、幂等、terminal fence、transcript projection 和 audit；事件是状态投影，不是第二事实库。 | gateway broadcast、Control UI/node/plugin hook、连接断线后的重放窗口/ACK；只转发已验证事件。 | **吸收** typed event + seq + lifecycle fence + bounded replay；**升级** 事件必须带唯一 owner/run/session 并区分 durable fact 与 ephemeral projection；**废弃** 无序全局 EventEmitter、无上限 pending buffer、断线后无 cursor 的“尽力推送”。 |
| 队列 | ingress queue 提供 durable enqueue/claim/token/complete/release/fail/dead-letter/duplicate tombstone；outbound recovery 支持 claim、backoff、unknown-after-send reconciliation、max retries；`src/process/command-queue.ts:74-119` 有 lane、并发、generation、timeout/abort/release signal。 | queue record/claim token、backoff、idempotency、dead-letter、lane、retry/lease primitives。 | 模块库分别持有 ingress、turn/command、delivery、task queue；运行核心规定 queue→claim→execute→commit/ack 的唯一状态推进和恢复。 | queue health/retry/replay/admin RPC；网关不能把一个 UI 请求直接当作队列事实。 | **吸收** durable claim + token + dead-letter + unknown-send reconciliation；**升级** 所有队列统一 owner/lease/expiry/幂等与恢复契约；**废弃** 仅内存 FIFO 承担跨崩溃消息、无 claim fence 的重复消费。 |

### 9.3 多渠道接入与单一执行链

多渠道的差异只应停留在“接入、身份、能力和投递适配”四个位置；从进入统一 turn 之后，必须走同一条可审计链。当前源码已经提供了这个收敛点：`ChannelPlugin` 拆出渠道专属 adapter，而 `src/channels/turn/kernel.ts` 通过 `dispatchAssembledChannelTurn`/`runPreparedInboundReply` 暴露统一 dispatch，`lifecycle.ts` 将 route 变换为 agent/session/store。

```text
Telegram/Discord/Feishu/Slack/WebChat/CLI/Node
  → channel plugin inbound adapter
  → normalize + security/pairing/allowlist + channel ingress queue
  → claim(eventId, channelId, accountId, laneKey)
  → resolve route(agentId, sessionKey, sessionId)
  → channel/turn preflight + admission
  → 唯一 turn kernel
  → session admission/turn claim
  → prompt/context/skills/tool policy
  → approved model + prepared runtime lease
  → provider stream (event seq) ↔ tool calls (approval/grant)
  → SessionManager.appendMessage(parentId) + usage/audit facts
  → unified ReplyPayload / delivery outcome
  → durable outbound delivery queue claim
  → channel outbound adapter + receipt/unknown-send reconciliation
  → channel-visible reply + gateway/UI event projection
```

**唯一链路约束：**

1. 渠道插件只能产生 `NormalizedTurnInput`、route、能力描述和 outbound adapter；不能在 inbound callback 中另调模型、另写 transcript 或另投递。
2. `eventId` 是 ingress 幂等键，`sessionId/runId/turnId` 是运行句柄，`deliveryQueueId` 是发送事实；它们不能互相替代，也不能由渠道自行重生。
3. 模型流和工具流可多次产生 ephemeral event，但只有核心负责 terminal outcome、transcript parentId、usage 和 delivery commit；UI/Gateway 只能订阅投影。
4. 通道切换不应切换 Agent 执行链：同一 `sessionKey` 的 Telegram 与 WebChat 消息必须经过同一 route/session/turn/model/tool 核心；不同 channel 的差异只能进入 adapter policy。
5. fallback 只能是同一 provider/model 契约下的显式策略；禁止 plugin、channel、gateway 各自隐藏 retry/fallback，避免一次用户消息产生多个事实链。

### 9.4 插件权限与资源句柄

| 资源/权限 | 授权来源 | 句柄形态 | 必须的边界与撤销 |
|---|---|---|---|
| Gateway RPC | `role-policy`、`method-scopes`、client scopes、session mutation authorization | `client.connId + role + scopes + actor + lifecycleGeneration` | handler 入口统一校验；restart/suspend 时关闭 root-work admission；连接断开不得继续写该连接。 |
| Plugin runtime | manifest/activation plan + `withPluginRuntimeGatewayRequestScope` 的 plugin identity | `pluginId + pluginSource/origin + request scope` | 只允许 SDK public surface；请求结束不把 AsyncLocalStorage scope 延长为全局句柄；plugin disable/reload 必须 fence 旧请求。 |
| Tool | agent/tool policy + runtime grant allowlist + operator approval | `runId + sessionKey + pluginId + normalized toolName + toolCallId` | grant 只扩展特定可信 run；参数仍需 schema/execute-time 检查；deny/timeout 后释放子句柄。 |
| Node command | node declared commands + config allowlist + conn/pairing generation + optional approval | `nodeId + expectedConnId + pairingGeneration + command` | 节点重连/配对变化立即使旧句柄失效；未知/危险命令 fail closed；结果必须 schema validate。 |
| MCP | plugin resolver 的 `requesterSenderId`、channel/account | `serverName + requester identity + resolved URL/headers` | requester 缺失直接失败；credentials 不由 core 日志/持久化；每次请求重新解析或使用有界短期 scope。 |
| 文件 | `rootDir`、fs-safe path/symlink/hardlink policy | `FileRef(root, relativePath, hash, size, owner, expiresAt)` | 禁止裸绝对路径和跨 root；成功/失败/取消/崩溃都清理 temp/spool；发布前 hash/identity 校验。 |
| 浏览器 | agent/session browser policy、SSRF policy、profile config、attachOnly | `sessionKey + profile + cdp endpoint + tabId + lease` | 只允许声明的 profile；action timeout/abort；生命周期结束关闭 tracked tabs，残留由 sweep/doctor 发现。 |
| 进程/worker | terminal launch policy、exec approval、worker tool authority | `sessionId + runId + pid/processGroup + ownerEpoch + credentialHash` | SIGTERM→有限宽限→SIGKILL 进程树；父进程退出仍释放 stdio；owner epoch 不匹配禁止 teardown 新 owner。 |
| 队列 | queue owner、claim token、lease/stale TTL、幂等 id | `queueId + claimToken + ownerId + attempt` | 只允许 claim owner ack/fail；过期 claim 可恢复但不能覆盖新 owner；dead-letter/unknown send 保留证据并可人工重放。 |
| 事件流 | run context claim、lifecycle generation、ACK cursor | `runId + seq + generation + session binding` | seq 单调、payload 有界；terminal 后 fence run；断线按 ACK replay，重启只恢复经持久 binding 证明的 cursor。 |

**权限结论：** OpenClaw 已将 Gateway scope、plugin identity、tool grant、node command allowlist 和 MCP requester identity 分开；平台底座应保持这五种权限不可互相“升级”。例如“插件已启用”不等于“工具允许”，“工具可见”不等于“节点命令可执行”，“Gateway admin”也不等于“可读取任意 agent 文件”。

### 9.5 资源生命周期与终态责任

| 资源 | 创建/取得 | 持有者与转移 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主/子进程崩溃 |
|---|---|---|---|---|---|---|
| Ingress event | channel adapter enqueue `eventId` | ingress queue claim token；turn owner 接管 | append/dispatch 完成后 complete/tombstone | fail + attempts/lastError，达到策略进入 dead-letter | release 或 stale claim recovery，不得丢原 event | startup/recovery 扫 claimed rows，按 token/TTL 重领；corrupt payload 留诊断 claim。 |
| Session/turn | route 解析 session、核心创建 `runId/turnId` | session placement/turn claim；owner epoch fence | SessionManager append + terminal + release claim | append error/failed terminal，保留 transcript/错误事实 | AbortSignal + terminal cancelled + release claim；晚到 provider event 丢弃 | generation/epoch 使旧事件无效，draining/reconcile/redispatch；不拆新 owner 的环境。 |
| Model runtime lease | `acquireAgentRunPreparedModelRuntime` | inference runtime 持有 `release` | provider stream 终止后 release | provider error 后 release | signal abort、credential expiry fence 后 release | worker/gateway 重启由 durable store `recoverPending` 变为 provider-error/可恢复状态；无 lease 残留证明时标待核。 |
| Tool/approval | tool call + plugin grant/approval | 一个 `toolCallId` 与 run scope | result 写回核心事件/transcript | `isError`/拒绝结果写回，不能静默丢失 | approval timeout/abort，子进程/浏览器句柄级联取消 | run fence 丢弃晚到 result；外部副作用需 idempotency/reconciliation。 |
| 文件/temp/spool | fs-safe root、sibling temp、media spool | FileRef + owner/expiry | atomic publish/hash verified，删除 temp | rollback/failed artifact，记录路径与错误 | cleanup best-effort 但必须告警，保留可诊断 residue | 启动 doctor/recovery 扫 pending marker/spool；manifest 不完整不得激活。 |
| Browser profile/CDP/tab | profile resolve/launch或attach | session-owned profile/tab lease | close tracked tabs 或按 idle cleanup | 单 tab 失败不污染其他 session；释放 action lock | action timeout/AbortSignal，close tab/profile | browser lifecycle cleanup + orphan sweep；远程 CDP 断线重连策略当前仅部分静态确认。 |
| Child process/worker | spawn plan/worker placement | process group、pid、owner epoch、credential | terminal result 后关 stdin/stdout/stderr/listeners，finished TTL | supervisor 记录 exit code/signal/reason | cancel process tree SIGTERM/SIGKILL；晚到 output bounded drain | parent exit 不代表 descendant 已死；kill tree、destroy environment、reconcile placement/workspace，失败保留 draining/reconciling row。 |
| Event stream | register run context/window | lifecycle generation + seq + ACK/pending bytes | terminal event 后 release context/fence run | error terminal，审计事件保留 | release run、clear pending、发送 cancelled/timeout terminal | 恢复只采用 binding+owner epoch 证明的 cursor；未匹配 owner 从 seq 0，避免旧事件污染新 run。 |
| Queue claim | enqueue/claim token | ownerId + token + lease | ack/complete + retention prune | fail/retry/backoff/dead-letter | release/expiry；worker 不得无界占 lane | reclaim stale claim，unknown-after-send 走 reconcile，而不是盲重发。 |

`runBestEffortCleanup` 只能降低清理异常对主结果的影响，不能替代残留验证。平台验收必须把“清理函数返回”与“现场不存在进程/端口/临时文件/锁/浏览器 tab/queue claim”分栏记录；当前源码有大量单测和恢复测试，但本轮未启动服务，不能把静态 cleanup 分支写成运行态已证明。

### 9.6 失败、超时、取消、崩溃矩阵

| 阶段 | 失败/边界 | 源码已有围栏 | 统一结果与恢复 | 当前证据等级 |
|---|---|---|---|---|
| Gateway 握手 | 版本、auth、pairing、scope 不符 | gateway protocol validators、role/scope、startup unavailable、pairing | fail closed；不创建 Agent run；客户端按 retry-after/重新配对处理 | 源码/协议与 Gateway 测试存在；未做真实 WS 连接 |
| RPC 准入 | unknown method、session mutation 变化、限流、suspend/restart | `server-methods.ts` 统一 admission、rate limit、generation | 明确 error shape；queued root work 不再接收；不执行 handler 副作用 | 静态已证；运行态未证 |
| Channel ingress | 重复 event、非法 payload、渠道断线 | ingress duplicate tombstone、claim token、dead-letter；plugin schema/allowlist | duplicate 返回已有状态；非法/不可恢复进入 failed/dead-letter；可重放 | ingress queue 源码和 dead-letter tests 存在 |
| Route/session | agent 不存在、session ownership/generation 变化 | route session key、session mutation authorization、placement claim | reject 或建立明确新 session；旧 run fence；不写错 session | 静态/colocated tests，未跨渠道运行 |
| Model admission | model 未批准、alias/provider 不符、context/工具超限 | `inference-runtime` policy/catalog/lease；worker schema 最大消息/工具/字节数 | `model-not-approved`/`invalid-context`；不启动 provider；release lease | 源码、worker schema/test 存在 |
| Provider stream | provider error、无视 abort、凭证过期、旧 owner | inference `durableFence`、AbortSignal、credential timer、active key、max provider ops | terminal error/cancelled；store complete；seq terminal；旧事件丢弃 | inference tests 存在；未真实调用外部 provider |
| Tool | schema 非法、grant 缺失、approval deny/timeout、节点不支持 | tool schema、plugin grant、operator approval、node command allowlist/connId/pairing | tool error 或 denial 写回；外部进程/节点/浏览器句柄释放 | 多个 tool/plugin/node tests；未全量执行 |
| File | 越 root、symlink/hardlink、部分写入、hash 不符 | fs-safe root、atomic sibling temp、snapshot manifest/identity/hash | fail closed；temp 清理；manifest 不发布；恢复扫描 pending | fs-safe/snapshot tests 存在 |
| Browser | CDP 不可达、attachOnly 不符、动作超时、tab 泄漏 | profile config、SSRF、action/open timeout、tracked tab cleanup | 当前动作失败；session cleanup/best effort；doctor/sweep 处理孤儿 | browser unit/integration tests 存在，远程 CDP 未证 |
| Process/worker | command timeout、无输出超时、SIGTERM 不收敛、父进程退出 | supervisor、process-tree kill、output caps、finished TTL、worker draining/reconcile | cancel/kill tree；terminal failed/cancelled；残留进入 reconcile，不重复 teardown 新 owner | process/worker tests 存在，未启动真实 worker |
| Event stream | sink throw、payload 超限、seq/epoch 过期、断线 | frame validator、25MiB/窗口/bytes caps、ACK cursor、generation fence | 发送失败以 terminal/provider error 收口；断线按 ACK 恢复；旧 run 不可见 | live-events/inference tests 存在 |
| Outbound delivery | 发送前失败、发送后未知、平台部分发送、重启 | delivery queue claim、backoff、max retry、unknown-send reconciliation、receipt/partial result | before-send 可重试；after-send 不盲重试；未知进入 reconcile；ACK 后清理 spool | recovery/queue/crash tests 存在，未实平台发送 |
| Gateway/宿主崩溃 | process restart、SQLite lock、worker orphan、半写 artifact | schema preflight、WAL/transactions、startup recovery、placement journal、snapshot manifest | 以 durable rows/leases 重建状态；不可证明的事实进入 quarantine/unknown | 静态和恢复测试；未做 crash injection 本轮执行 |

### 9.7 L0-L4 通用底座分级

| 等级 | 定义 | OpenClaw 对应 | 平台允许的依赖方向 | 验收门槛 |
|---|---|---|---|---|
| **L0 原子支持库** | 纯协议、规范化、安全、句柄、超时、重试、文件/进程/队列基础算法；不识别渠道业务和 Agent 业务。 | `packages/gateway-protocol`、`llm-core`、`model-catalog-core`、`retry`、`net-policy`、`terminal-core`、`@openclaw/fs-safe`、`src/process/*` 窄 facade。 | L0 不依赖 L1-L4；可被单测、模块和核心复用。 | schema/property/边界测试；资源句柄和错误码稳定；无隐藏 global mutable state。 |
| **L1 领域模块库** | 一个领域流程：channel turn、plugin loader、model resolution、tool runtime、browser、terminal、ingress/outbound/task queue。 | `src/channels/turn/*`、`src/plugins/*`、`src/agents/tools/*`、`src/gateway/worker-environments/*`、`src/infra/outbound/*`。 | L1 只调用 L0 与注入的 L2 owner；插件/provider 是可替换策略。 | contract + lifecycle + retry/timeout/cancel/dead-letter tests；不能复制另一条链。 |
| **L2 运行核心** | session/run/turn 所有权、模型/工具执行、transcript、event sequencing、placement/worker、持久状态和恢复。 | `SessionManager`、embedded/worker inference、agent events、state DB、placement stores、gateway work admission。 | L2 不知道具体 channel/plugin id；只能通过公开 adapter/registry/SDK 访问 L1 能力。 | 单一执行链、幂等、generation/epoch fence、崩溃恢复、残留现场验证。 |
| **L3 统一网关/适配面** | 外部认证、RPC/HTTP/WS、节点、控制 UI、CLI、事件投影和运维动作。 | `src/gateway/*`、`server-methods`、protocol/client、node registry。 | L3 调用 L2/L1 facade；不得把 provider/child/browser 句柄暴露给客户端或重复业务流程。 | 握手/scope/协议兼容、限流、挂起/重启、事件 backpressure、实际端到端连接。 |
| **L4 产品插件/渠道策略** | 具体 Telegram/Discord/Feishu/provider/browser integration/MCP/skill 的配置、认证、平台语义。 | `extensions/*`、bundled channel/provider plugin、skills。 | L4 只能经 `openclaw/plugin-sdk/*` 与 manifest/runtime hook 接入；不能反向 import core internals。 | manifest-first cold path、权限最小化、对同一 L2 chain 的 contract tests、第三方 live test（若可行）。 |

**分级结论：** 现有仓库已经接近 L0-L4 的边界形态，但仍存在大量 `src/*` 内部模块而非可直接发布的支持库；因此平台落地应先抽取契约和 owner，再决定是否升格为 package。不得因目录名字包含 `core` 就自动判定为 L0，也不得因代码在 Gateway 下就把它当网关能力。

### 9.8 复用/升级/新建/废弃裁决与装配计划

| 结论 | 具体项 | 原因/限制 |
|---|---|---|
| **复用** | `gateway-protocol` 的 typed envelope/validator；`plugin-sdk` 的窄 entrypoints；`fs-safe` root/file policy；`normalization-core`；`net-policy`；worker inference 的 seq/terminal/fence 思路；ingress/outbound claim/recovery 语义。 | 已有明确 owner、源码和测试，重复实现会造成错误码/事件/资源责任漂移。 |
| **升级** | 统一 `ExecutionHandle`（session/run/turn/owner epoch/generation）、`ResourceHandle`（owner/expiry/release）、`DeliveryReceipt`（before/after/unknown）；模型、工具、浏览器、进程、队列都接入相同的 terminal/cancel/recovery contract。 | 当前事实分散在多个类型和模块；可先加适配 facade，不改变既有源码。 |
| **升级** | 把多渠道的 ingress→turn→delivery 接口冻结为一套 contract test matrix，所有 channel plugin 只填 adapter capability。 | 当前 `ChannelPlugin` 已有类型组合，但完整多渠道运行一致性和所有 provider 的运行态仍未全部验证。 |
| **新建（平台层，不在本仓库实施）** | 资源句柄登记/泄漏审计器、跨进程残留探针、统一 failure ledger 和可查询 evidence record。 | OpenClaw 有分散的 cleanup/recovery/test hooks，但本轮未发现覆盖所有 browser/file/process/queue 的统一现场账本。 |
| **新建（平台层，不在本仓库实施）** | provider/channel/plugin capability registry 的静态 descriptor schema，区分 discovery/light artifact 与 heavy runtime。 | 现有 manifest-first/light artifact 是事实模式，平台需要把它提升为跨项目公共契约。 |
| **废弃** | 每渠道独立 Agent loop、每插件独立 transcript、以 `EventEmitter`/内存 FIFO 作为 durable fact、裸路径/裸 child pid/裸 CDP page 跨层传递、隐藏 fallback、无 owner 的全局 mutable registry。 | 与单链路、最小权限、崩溃恢复和资源生命周期铁律冲突。 |
| **待核** | 远程 CDP/Playwright 断线重连、所有第三方渠道的 after-send unknown reconciliation、worker crash 后真实 orphan 进程/端口清理、跨重启 session transcript 与事件 replay 的端到端行为。 | 目前仅有静态代码和针对性测试证据；未启动 Gateway、worker、真实渠道或 provider。 |

**装配顺序（仅研究结论，不启动生产改造）：**

1. 先冻结 L0 的 envelope/error/handle/lease/receipt/queue primitives 与测试；禁止带渠道名。
2. 再将 L1 的 turn/model/tool/browser/process/delivery 模块改为依赖注入，明确创建者、持有者、转移者和释放者。
3. 在 L2 建立唯一 `ExecutionHandle` 和 state/event/transcript owner，补齐四种终态和 generation/epoch fence。
4. 在 L3 只装配 auth/RPC/events/node/CLI，所有业务调用落到 L2；为每类连接做 backpressure 和断线恢复测试。
5. 最后按 L4 plugin/channel/provider 逐个接入，先 light descriptor 再 heavy runtime，使用同一 contract/lifecycle/failure matrix 验收。

### 9.9 本轮测试与真假验证表

| 事实/能力 | 源码或测试存在 | 本轮静态读取 | 本轮真实执行 | 结论 |
|---|---|---|---|---|
| Gateway lazy registry、scope、request plugin scope | `src/gateway/server-methods.ts`、`src/gateway/AGENTS.md`、Gateway tests | 已读关键实现和规则 | 未启动 WS/Gateway | **部分实现/静态确认** |
| Channel plugin + turn kernel + durable ingress/outbound | `src/channels/plugins/*`、`src/channels/turn/*`、`src/channels/message/ingress-queue.ts`、`src/infra/outbound/*` tests | 已读类型、kernel、lifecycle、queue contract | 未跑跨渠道端到端 | **部分实现/静态确认** |
| Session/transcript/placement/worker inference | `SessionManager` 引用、`src/gateway/worker-environments/*`、`packages/gateway-protocol` worker schema/tests | 已读 claim/fence/seq/recovery 关键段 | 未启动 worker、未做 crash injection | **部分实现/静态确认** |
| Plugin permission/tool grant/MCP requester | `src/plugins/tool-grant-allowlist.ts`、`runtime/tool-grant.ts`、`types.mcp-connection.ts`、plugin contract tests | 已读 grant key 和 requester-scoped type | 未装载第三方插件做 live invoke | **部分实现/静态确认** |
| Browser/file/process lifecycle | `src/plugin-sdk/browser-types.ts`、`src/browser-lifecycle-cleanup.ts`、`src/infra/fs-safe.ts`、`src/process/*`、对应 tests | 已读 handle/cleanup/kill tree/output cap | 未连接 CDP、未拉起真实 worker/process 树 | **部分实现/静态确认** |
| Event/stream backpressure and terminal | `src/infra/agent-events.ts`、`live-events.ts`、`worker-environments/inference.ts` tests | 已读 seq/window/bytes/generation/terminal | 未做断线、sink throw、超限实测 | **部分实现/静态确认** |
| Queue timeout/retry/crash recovery | ingress、outbound recovery、command queue 及 recovery/crash tests | 已读 claim/backoff/unknown-send/lane timeout | 未执行 Vitest、未注入进程崩溃 | **部分实现/静态确认** |
| 项目身份/代码图 | 目标仓库 `git rev-parse HEAD` 为 `1fc81c20548e3323c2f5ab05cd41338b5647c726`；`project_context` 错绑华世王镞_v3 | 已排除错绑代码图与提交指纹 | 未建立目标 CodeGraph | **弱验证，不能用错绑图作证据** |

本轮遵守只改根 `ARCHITECTURE.md` 的边界；没有执行 `pnpm install`、Gateway/worker 启动、真实渠道/provider/browser 请求或项目测试，因此“测试文件存在”不等于“本轮通过”。后续若要把映射升级为平台实现，必须另立实施任务并先完成需求、能力搜索、复用决策、文件占用和验收契约。

## 10. 第二轮源码收口：Gateway/Channel/Session/Plugin/Tool/Model/Browser/文件/进程/事件/队列

本节是对前述架构映射的源码级收口。收口口径不是“目录存在”，而是确认每个边界的入口、状态事实、资源持有者、终态写入和失败恢复方式。结论仍只适用于本文档顶部记录的源码快照；未启动服务或第三方运行时的项目，不把静态测试存在写成运行态通过。

### 10.1 一条可恢复的执行链

```text
Gateway connect/handshake
  → RPC admission (role/scope/pairing/rate-limit/generation)
  → Channel normalize + durable ingress enqueue(eventId)
  → claim(queueId, claimToken, ownerId, lane)
  → resolve route(agentId, sessionKey, sessionId)
  → Session turn claim(runId, turnId, ownerEpoch)
  → Plugin/Tool policy and approval
  → Model catalog/policy → prepared runtime lease → provider stream
  → typed events(seq, generation) + transcript append(parentId)
  → terminal outcome/usage/audit
  → durable outbound delivery claim
  → Channel adapter send → receipt or unknown-send reconciliation
  → Gateway/UI/channel projection
```

该链有三个不可互换的事实键：`eventId` 只负责入站幂等，`sessionId/runId/turnId` 只负责一次执行归属，`deliveryQueueId` 只负责外部投递事实。重试、断线和进程重启只能恢复原事实，不能在适配器层重新生成一条隐式链。

### 10.2 组件收口表

| 边界 | 源码收口事实 | 资源/状态 owner | 正常终态 | 失败与恢复裁决 |
|---|---|---|---|---|
| Gateway | `src/gateway/server.ts` 只做 facade/lazy load；`server-methods.ts` 将 core、plugin、extra handler 合并后统一执行授权、session mutation、限流、挂起/重启准入和 request scope。 | Gateway connection、`connId`、client role/scope、pairing generation、lifecycle generation。 | RPC response 或 broadcast event 完成；连接关闭后不得继续写连接。 | 握手/授权/版本不符 fail closed；重启/挂起关闭 root-work admission；旧 generation 的请求和事件丢弃。 |
| Channel | `ChannelPlugin` 负责 config/setup/security/pairing/inbound/outbound/streaming；`channels/turn` 负责统一 turn dispatch；`message/ingress-queue` 持久化入站事件并支持 duplicate、claim、release、complete、fail、dead-letter、resubmit、prune。 | channel/account adapter；ingress queue claim token；turn kernel。 | 统一 `ReplyPayload` 进入 outbound queue，并以 receipt 完成。 | 重复事件返回既有状态；断线或 worker 崩溃由 stale claim recovery 重领；不可恢复事件进入 dead-letter，不在 callback 内另跑 Agent。 |
| Session | SessionManager 维护 transcript `parentId` 链；routing/session key 解析归属；worker placement 与 owner epoch 防止旧 owner 写入。 | session placement/lease、`sessionId/runId/turnId`、owner epoch、agent DB。 | terminal outcome、usage、transcript append 和 claim release 一起收口。 | 取消写 cancelled terminal；崩溃按 durable row 重建 pending/reconciling；旧事件因 generation/epoch fence 被拒绝。 |
| Plugin | manifest-first discovery 与 control-plane/runtime-plane 分离；light artifact 可用于发现、配置和诊断，heavy runtime 仅在 activation 后加载；request scope 通过 plugin identity 隔离。 | manifest/activation plan、plugin runtime scope、能力/权限 descriptor。 | activation registry 注册完成；请求结束释放 scope。 | manifest/schema/依赖/权限失败不激活；disable/reload 使旧 request fence 失效；插件不能 import `src/**` 绕过 SDK。 |
| Tool | Agent runtime 组装工具；schema、grant、operator approval、execute-time policy 分层；terminal tool 另有 session/launch/signal/cleanup 检查。 | `runId + session + pluginId + normalized toolName + toolCallId`，外加子进程/浏览器/节点句柄。 | 结果以成功或 `isError` 写回 event/transcript，释放所有子句柄。 | schema/grant/approval/节点能力失败显式写 denial/error；超时和取消级联释放；外部副作用必须幂等或进入 reconciliation。 |
| Model | `worker-environments/inference-runtime.ts` 做 catalog/alias/visibility/policy admission 并取得 prepared runtime lease；`inference.ts` 负责 AbortSignal、fence、seq、大小上限和 terminal store。 | model runtime lease、provider/auth profile、stream context。 | provider terminal、usage/cost、stream terminal event、lease release。 | 未批准模型不启动 provider；凭证过期/旧 owner/abort 生成 error 或 cancelled terminal；重启只恢复可证明的 durable pending。 |
| Browser | browser SDK 定义 profile、CDP、userDataDir、driver、attachOnly 和 SSRF 边界；`browser-lifecycle-cleanup.ts` 按 session 关闭 tracked tabs，并将 cleanup 异常降级为可诊断错误。 | session-owned profile/tab lease；CDP endpoint 不进入持久业务 payload。 | action 完成后释放 action lock；生命周期结束关闭 tracked tabs。 | 连接/导航/动作超时只结束当前 action；取消、session end、进程退出触发 best-effort cleanup，doctor/sweep 发现孤儿；远程 CDP 重连仍待运行态核验。 |
| 文件 | fs-safe 提供 root、symlink/hardlink、大小/超时、原子写；snapshot 使用 staging、manifest、SHA-256、identity 校验后 publish。 | `FileRef(root, relativePath, hash, size, owner, expiresAt)`；temp/spool owner。 | 原子 publish 后只持有 artifact/manifest 引用。 | 越 root、链接、部分写入或 hash 不符 fail closed；启动扫描 pending marker/spool；不能用裸绝对路径跨插件传递。 |
| 进程 | child-process/tree 负责 SIGTERM→SIGKILL；bash process registry 维护 running/finished、输出上限、TTL、stdio/listener 清理；worker 在独立环境/tunnel 中运行。 | process group、pid、worker placement、owner epoch、credential epoch、bounded output buffer。 | terminal result 后关闭 stdio/listener，finished entry 按 TTL 回收。 | timeout/abort 杀进程树而非只杀 child；父进程退出后仍 sweep descendant；残留进入 draining/reconciling，不对新 owner 重复 teardown。 |
| 事件 | agent/live events 使用 stream/run/session/agent、seq、timestamp、generation、ACK、pending bytes/window 和 terminal fence；worker frame 同样带 seq。 | run event context、ACK cursor、bounded pending buffer。 | terminal event 后 fence run 并释放 context；durable fact 投影到 transcript/audit。 | sink throw、超限、断线和旧 seq 不污染新 run；断线仅从已 ACK cursor 重放；无 owner/cursor 证明不得恢复。 |
| 队列 | ingress 与 outbound queue 都支持 durable row、claim/release、attempt/backoff、complete/fail/dead-letter、prune；outbound recovery 特别区分 send 前失败与 send 后 unknown。 | queue row、claim token、lease/stale TTL、attempt、lane、idempotency key。 | 只有 claim owner 能 ack/complete；完成后按 retention prune。 | stale claim 可重领；达到 max retry dead-letter；send 已开始但结果未知必须 reconciliation，禁止盲重发；恢复 drain 有并发、期限和 replay pacer。 |

### 10.3 终态与恢复不变量

1. **终态唯一**：每个 `run`、tool call、model lease、queue claim、delivery attempt 都必须落入 `success`、`failed`、`cancelled` 或 `unknown/reconciling` 四类之一；`unknown` 不能伪装成失败后自动重试。
2. **先记录事实，再做外部副作用**：发送前可安全重试；发送已经开始但没有 receipt 时先写 `send_attempt_started/unknown_after_send`，由平台或渠道 reconciliation 决定，不由普通 retry 路径猜测。
3. **claim 是写权限**：`token + owner + attempt` 校验失败时，旧 worker 只能放弃；过期 claim 的恢复不能覆盖新 owner 的 ack、fail 或 terminal。
4. **generation 是生命周期围栏**：Gateway 重启、worker 替换、session reset、plugin reload、channel reconnect 都递增相应 generation/epoch；晚到的 stream、tool、event、cleanup 只能被丢弃或记录为 stale。
5. **清理必须可观察**：best-effort cleanup 不是完成证明。browser tab、child process、端口、temp/spool、锁、SQLite claim 和 queue row 必须有残留探针、TTL 或 doctor/recovery 记录。
6. **内存结构不是跨崩溃事实**：`Map`/`Set`/EventEmitter 只能做进程内去重、并发闸门或缓存；跨进程消息、投递、重放和恢复必须由 SQLite/durable queue/manifest 承载。
7. **权限不可升级**：Gateway admin、plugin enabled、tool visible、node paired、MCP requester 和文件 root 是不同授权；上层身份不能自动获得下层句柄。

### 10.4 本轮收口后的实现/验证分界

| 项目 | 已从源码收口 | 仍不能声称已验证 |
|---|---|---|
| Gateway/Channel/Session | lazy registry、统一 admission、ingress claim/dead-letter、turn/session owner、transcript parent 链 | 真实 WS 握手、跨渠道同 session、重启后端到端 replay |
| Plugin/Tool/Model | manifest-first、request scope、grant/approval、catalog/policy/runtime lease、stream terminal fence | 第三方插件 live activation、真实 provider failover、所有工具的副作用 reconciliation |
| Browser/文件/进程 | session cleanup、root/manifest/hash、进程树终止、输出上限、finished TTL | 真实 CDP 断线、worker orphan/端口回收、跨重启文件残留现场 |
| 事件/队列/恢复 | seq/ACK/window/generation、durable claim、backoff、dead-letter、unknown-send reconciliation 代码路径 | crash injection、真实平台 after-send unknown、实际 pending buffer/资源上限压测 |

因此第二轮源码收口结论是：**OpenClaw 已形成“Gateway 控制面 + 单一 Channel turn + Session/Model/Tool 核心 + durable delivery + 有围栏的资源清理/恢复”主链；未闭合项集中在真实运行态和第三方边界，而不是再增加平行架构层。**

## 11. 第三轮风险与后续复核

1. **目标项目上下文绑定错误**：`project_context` 返回 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是目标 openclaw；本轮已完全排除其代码图、最近验证和工作区指纹，所有事实来自目标仓库本地静态读取，因此映射证据等级为弱验证/静态确认。
2. **旧细探事实源**：当前目标根和其父级参考库用文件搜索未找到 `细探-openclaw.md`；现有 `ARCHITECTURE.md` 已声明此前细探结论已吸收，本轮未删除任何旧文件，也未把找不到旧文件解释为不存在历史内容。
3. **源码快照新鲜度**：目标 HEAD 为 `1fc81c20548e3323c2f5ab05cd41338b5647c726`，本轮没有 fetch/pull 或远程对照；结论仅适用于该 checkout，不能宣称 upstream 最新行为。
4. **运行态缺口**：没有启动 Gateway、worker、CDP、真实渠道、provider 或节点，无法证明端口、握手、跨进程清理、真实投递、unknown-send reconciliation 和恢复后的现场无残留。
5. **抽象升格风险**：`src/*` 的内部模块有全局 singleton、插件 registry、AsyncLocalStorage 和同步 SQLite 等运行约束；平台抽取时若只复制类型不复制 owner/生命周期/测试，会产生“同名支持库、两条执行链”的伪复用。
6. **流式状态边界**：当前 inference/live-events 已有 seq、ACK、bytes/window、epoch/generation，但不同 Gateway event、channel streaming、delivery queue 的统一 envelope/重放语义仍需跨模块实测和契约测试。
7. **资源残留风险**：浏览器、子进程、worker tunnel、媒体 spool、SQLite claim、临时文件和队列 dead-letter 的清理 owner 分散；后续必须加现场探针和 crash-child tests，不能以 best-effort 日志代替验收。
8. **权限组合风险**：plugin grant、tool policy、operator scope、node command allowlist、MCP requester identity 分层清晰，但跨层组合仍需逐工具/逐渠道测试；任何“启用即允许”或“可见即可执行”的捷径都应判为 L4 不合格。

本节及第 9 节是本项目根文档的第三轮增量；后续只维护本 `ARCHITECTURE.md`，不恢复平行细探事实源。

## 12. 深度源码核对：耐久队列、围栏、事件与资源回收

本轮对当前 checkout 的 Gateway、channel、session、plugin、tool、model、browser、process、event、queue 相关实现、共址测试、配置类型和架构文档做了定向全文核对。结论只描述源码确实实现的语义；测试文件存在不等于本轮已执行测试。未找到独立的 `细探*` 文件，因此不删除、不重建旧细探；本文只吸收当前 checkout 可复核的证据。

### 12.1 Durable queue 的真实状态机

入站队列不是内存 FIFO。`src/channels/message/ingress-queue.ts:23-247` 将事件、元数据、lane、attempt、last error 和 claim 写入 shared SQLite；状态至少包括 pending、claimed、completed、failed。`enqueue(eventId, ...)` 以 event id 做重复判定并返回 pending/claimed/completed/failed 的既有状态；成功与失败都保留 tombstone，失败记录还保留 payload、metadata、attempt history，可通过 `resubmit` 恢复一次。`src/channels/message/ingress-queue.ts:849-1070` 的 SQL 更新以 status、event id 和 claim token 保护 claim/release/recover；`src/channels/message/ingress-queue.dead-letters.test.ts:25-121` 覆盖失败资料保留、一次性重投、完成 tombstone 拒绝重投和按 channel/account 统计。

出站队列在发送前持久化完整的 replayable intent，而不是发送失败后临时拼装：`src/infra/outbound/delivery-queue-storage.ts:55-108,153-220` 保存原始 payload、渲染计划、reply/thread、session、Gateway scopes、prepared message id、completion owner、retry budget 和 `recoveryState`。`enqueueDeliveryOnce` 用稳定 id 的 insert-only 语义避免 producer 重放覆盖已存在的 ownership；`ackDelivery` 先删除/完成 SQLite row，再释放 media spool，避免先删附件造成可重放行丢失（同文件 `238-260`）。`src/infra/outbound/delivery-queue-recovery.ts:1-20,194-207,1089-1210` 对恢复执行有界期限、指数 backoff、最大重试、内存中的同进程 active-entry 去重和失败转存；SQLite row 是跨崩溃事实，`Map/Set` 只承担本进程并发闸门。

媒体有独立的崩溃窗口保护。`src/infra/outbound/delivery-queue-media-spool.ts:76-176` 先创建 SQLite stage row，再写 `.part`，完整复制后原子改名；enqueue 与 stage 以同一持久状态完成消费，否则 fail closed 并清理。`224-289` 用 pending/staged 引用集保留文件，24 小时 orphan grace 清扫没有队列引用的最终/部分 artifact。该设计证明了“先写事实、再做外部副作用”和“row 删除后才释放 spool”，但不证明所有外部渠道附件均能跨重启复现。

### 12.2 Claim、token、lease 与 generation fencing

入站 queue claim 返回 `{token, ownerId, claimedAt}`；`complete/release/fail` 接受 claim ref 时必须以 token 作为写权限，过期 claim 只可由 stale recovery 在仍满足 token/status/时间条件时释放。旧 worker 的 token 不匹配时 SQL 影响行数为零，不能 ack、fail 或覆盖新 owner。队列接口显式暴露 `recoverStaleClaims(staleMs, shouldRecover...)` 和 corrupt-payload claim，说明 payload 解码失败也不会绕过 claim 保护（`ingress-queue.ts:39-72,199-247,420-456,981-1070`）。

出站恢复的 `withActiveDeliveryClaim` 是进程内 entry id claim；真正的跨重启 ownership 由 SQLite attempt reservation 和状态迁移承担。`reserveDeliveryAttempt` 在调用 provider 前预留 attempt；发送前失败清除 `platformSendStartedAt/recoveryState`，发送已开始的失败写入 `unknown_after_send`，绝不把“可能已对用户可见”伪装成普通 retry（`delivery-queue-storage.ts:263-361`）。这套 claim 不是通用分布式 lease：本轮未找到一个跨所有 outbound adapter 的统一 claim-token schema；因此文档第 9 节的“所有队列统一 token/lease”应视为平台映射要求，而非 OpenClaw 已完全统一的事实。

generation/epoch 是多处独立的生命周期围栏，而非一个全局 fencing token：

- Gateway/agent event 在 `src/infra/agent-events.ts:51-68,99-117,169-222,296-320` 保存每个 run 的 seq、session binding、lifecycle generation 和 claim owner；重启先 `rotateAgentEventLifecycleGeneration()`，旧 run 由 `assertAgentRunLifecycleGenerationCurrent` 拒绝。
- Worker live event 在 `src/gateway/worker-environments/live-events.ts:101-187,215-329,331-360` 同时校验 session binding、environment id、run epoch、credential hash；不匹配返回 `epoch-mismatch`，配置/身份变化会清 window、释放 run claim、丢弃旧 cursor。
- Worker 测试验证 admission 或推理中 owner epoch 被替换时返回 fenced，并验证 fenced 后 worker-scoped background process 数量最终为零（`src/worker/worker.runtime.test.ts:921-937,1081-1099`）。
- command lane 仍是独立的进程内 generation：`src/process/command-queue.ts:79-118,237-243,625-684` 在 clear/recovery 时递增 generation、清 active ids，迟到 completion 被忽略；timeout 会释放 lane，但底层 task 可能仍在 unwind，因此不能把 lane release 当作进程终止证明。
- plugin artifact/config/install-index mutations 用 shared SQLite lease 串行化，默认 lease 5 分钟、等待 10 分钟，并在嵌套调用中 `assertOwned()`（`src/plugins/plugin-lifecycle-lease.ts:12-15,46-93`）。这保证插件生命周期互斥，不等价于请求级 runtime scope 或 provider execution fencing。

### 12.3 Unknown send reconciliation 的精确边界

`src/channels/turn/durable-delivery.ts:134-236` 明确区分两种最终回复路径：默认只要求 `best_effort` durable delivery；只有 capability/调用方显式要求 `reconcileUnknownSend` 才升级为 `required` 并在发送前检查 adapter 能力。对应测试 `src/channels/turn/durable-delivery.test.ts:112-157` 证明默认路径不会设置 `requireUnknownSendReconciliation`，显式要求才会设置。

出站 recovery 看到 `send_attempt_started` 或 `unknown_after_send` 时先调用 adapter 的 `durableFinal.reconcileUnknownSend`，而不是普通重发（`src/infra/outbound/delivery-queue-recovery.ts:168-191,284-329,625-640`）。reconcile 返回 sent 时构造 receipt 并运行 afterCommit；unresolved 会保留 unknown 和 retryable 诊断。`src/infra/outbound/delivery-queue.recovery.test.ts` 覆盖 simulated crash、恢复重放、owner-completed/suppressed/rejected operation、backoff 和 unknown-send 分支；`src/infra/outbound/outbound-audit.test.ts:112-160` 明确要求未知状态不能被发明成 failure。

因此“unknown send 不盲重发”是出站队列的真实实现；但它不是所有 channel 的事实保证：adapter 必须声明 capability 和支持的 unknown-send kinds，且默认 final path 可以不要求该能力。真实第三方平台在请求已到达但 receipt 丢失时能否可靠查询、平台消息 id 是否可稳定关联，本轮未通过 live channel 验证。

### 12.4 事件顺序、断线重连与恢复

Gateway 概念文档 `docs/concepts/architecture.md:75-93,141-145` 给出 WS frame、request/response/event 和 side-effect idempotency，但其“不重放，客户端自行 refresh”是高层摘要，不能覆盖 worker live-event 的更窄恢复协议。实际 `src/gateway/worker-environments/live-events.ts:64-75,318-329,384-418,620-698` 为每个 session 维护 `ackedSeq`、pending map、pending bytes、run epoch、terminal run 和窗口大小；默认 window 128、默认 pending 上限 512 KiB。乱序事件进入 pending，连续前缀才推进 ACK；序号越窗或 pending 超限返回 `resync-required` 并清 speculative pending。

重启恢复只接受“同一 environment binding + 同一 runEpoch”证明过的 startup owner；源码明确写明不匹配的 owner row 从 zero 开始，不能伪造 post-restart ACK（`live-events.ts:107-121`）。credential rotation 可保留 durable ACK cursor，但 `newProcessTurn` 会释放旧 run claims、清 transient pending/terminal state（`153-185`）。session identity mutation 会重新绑定并在失败时清 window、撤销 startup owner（`289-315`）。worker runtime 测试还验证 lifecycle end、cancel、fenced、live failure、burst coalescing 和每帧字节上限（`src/worker/worker.runtime.test.ts:939-1043`）。

事件结论应精确表述为：普通 Gateway 文档事件没有全局 replay contract；worker live stream 有基于 ACK/cursor、binding 和 epoch 的有限未确认后缀重放/resync contract。两者不能合并成“所有事件可重放”，也不能简化为“所有事件永不重放”。本轮未建立真实断开 WS、重连、丢包、重复帧和跨进程网络故障的端到端证据。

### 12.5 Browser、PTY/子进程、临时文件与崩溃清理

- Browser config 将 CDP endpoint、profile/userDataDir、driver、attachOnly、remote/local timeout、action timeout、tab cleanup、SSRF policy 分开建模（`src/plugin-sdk/browser-types.ts:1-73`）。`src/browser-lifecycle-cleanup.ts:21-43` 对 session key 去重后关闭 tracked tabs，并通过 `runBestEffortCleanup` 吞并报告 cleanup 异常；browser 单测覆盖 disabled、空 session 和 cleanup failure，但不证明远程 CDP 已断开或孤儿 tab 已从外部浏览器消失。
- Child process tree 通过 `src/process/child-process-tree.ts:8-24` 对 detached Unix child 使用 process-tree SIGTERM/SIGKILL，不只杀直接 child。`src/process/child-process.ts:14-80` 在 direct child exit 后允许 100 ms idle drain，最长 1 s 后销毁 stdout/stderr，处理 descendants 继承 pipe 的迟到输出。该函数只释放 pipe/listener，不负责证明 descendant 已终止；必须结合 supervisor/worker cleanup。
- command queue 有 lane timeout、abort grace、release signal、draining 和 generation；这能解除队头阻塞并忽略迟到 completion，但注释和实现都承认底层 task 可能继续 unwind。PTY/terminal、browser、worker tunnel 的跨模块级联清理不能由 command queue 单独推出。
- delivery media spool 使用受限 root、0600 文件、`.part` 原子发布、SQLite stage row 和 orphan grace；snapshot/local repository 另有 staging、manifest/hash/identity 和 pending marker。两者都能在恢复时保留“可证明的引用”并清理无引用残留，但未运行 crash-child、强杀、端口占用或真实文件系统异常场景。

### 12.6 与既有细探/架构条目的逐条裁决

| 既有结论 | 当前源码核对 | 裁决 |
|---|---|---|
| ingress/outbound 是 durable queue，支持 claim、retry、dead-letter | ingress SQLite row/tombstone/claim token；outbound SQLite intent、attempt、backoff、failed retention | **保留**，并补充入站 token guard、出站 attempt reservation 和 media stage |
| claim/token/lease/generation 防止旧 owner 写入 | ingress token guarded SQL、agent lifecycle generation、worker runEpoch/credential binding、command lane generation、plugin SQLite lease | **保留但拆分**；它们是不同 owner 域的围栏，不是一个全局 token |
| unknown-after-send 必须 reconciliation | recovery 对已开始发送的 row 先调用 adapter reconcile；但 durable final 默认 best-effort，能力需显式声明 | **修正为有条件成立**，不能宣称所有渠道/所有最终回复强制可靠 reconciliation |
| 事件按 seq/ACK/generation 有界发送并可恢复 | worker live-events 有窗口、ACK、pending bytes、resync 和 startup binding 校验；普通 Gateway 文档仍写不重放 | **保留并澄清范围**，仅 worker live stream 有有限 replay/resync |
| browser/process/temp 在结束、取消、崩溃后清理 | 有 tracked tab cleanup、process-tree kill、stdio drain、spool orphan sweep、snapshot pending marker | **保留为静态代码路径**，不升级为现场无残留保证 |
| 单一 Gateway + Channel turn + Session/Model/Tool 主链 | 当前目录、类型、测试和 docs 均与该主链一致；durable delivery 由 channel adapter capability 参与 | **保留**，但 platform mapping 中的“统一所有队列/统一所有 event envelope”仍是目标设计，不是当前完全实现 |

### 12.7 本轮新增未验证边界

1. 未启动 Gateway 或真实 WS client；握手、断线、重连、重复/丢失 frame、普通 Gateway event 的 replay 行为仍未做 live 验证。
2. 未连接任一真实 channel/provider；unknown-send reconciliation 的平台查询可靠性、第三方 receipt 丢失和 afterCommit 幂等性仍未证实。
3. 未执行 Vitest；本轮只读取测试源码和测试设计，不能报告测试通过、覆盖率或运行时性能。
4. 未做 crash injection、SIGTERM/SIGKILL、父进程退出、worker orphan、PTY pipe 继承、CDP 断开、临时目录权限/磁盘满和 SQLite 锁竞争实测。
5. 未逐一审计所有 plugin/channel/tool/model provider；当前结论适用于已读取的公共 facade、核心 queue/recovery、worker event 和代表性测试，不代表每个扩展均实现相同能力。
6. `ARCHITECTURE.md` 顶部源码快照仍是目标 checkout 的静态记录；本轮没有 fetch/pull，也没有修改或删除任何旧细探文件。

## 13. 第四轮分段审计：恢复、未知发送与资源边界

本轮先在目标 checkout 建立并查询 CodeGraph，再按 gateway、channel、session、plugin、tool、model、browser、process、event、queue、sqlite、claim/lease/epoch、live stream、media、tests、docs 分段核对。CodeGraph 索引覆盖当前 checkout 的 TypeScript、Swift、Kotlin、Go、Rust 和配置文件；本文只引用目标仓库自身源码、测试和文档，不使用其他项目的 MCP、记忆或验证证据。

### 13.1 Gateway、channel 与 session

Gateway 仍是唯一控制面：连接请求经过握手、认证/配对、scope/role、session mutation、限流和 suspend/restart admission 后才进入 handler。restart handler 对 targeted restart 还校验 active lock 的 `pid/ownerId/port`，并只接受严格的 restart intent；因此“请求已收到”不等于“重启已执行”。Gateway 的普通事件向客户端广播，但当前文档契约没有承诺全局事件 replay。

Channel 的 ingress 与 outbound 是两条不同事实链。入站以 `eventId` 去重并持久化 claim；turn kernel 将输入归一化到 agent/session 后进入统一执行链。出站先保存 durable delivery intent，再由 adapter 发送并写入 receipt/完成事实。渠道插件不能在 webhook callback 中另起 Agent loop、另写 transcript 或绕过核心 delivery queue。

SessionManager 的 transcript 同时支持 SQLite 持久化和兼容的文件快照/重写路径；entry 通过 `parentId` 形成可分支树，opaque leaf control 用于保持追加游标。Session、turn、worker placement 的 owner 不是同一个全局 lease：旧 owner 是否能继续写入，要由相应的 session/worker generation、run epoch 或 claim token 单独判断。

### 13.2 Claim、lease、epoch 与恢复

| 机制 | 当前源码事实 | 不能过度推断的结论 |
|---|---|---|
| Ingress claim | SQLite row 保存 token、owner、attempt；complete/release/fail 受 token/status 条件保护；stale claim 可恢复。 | 不能把进程内 worker 退出自动等同于消息已安全完成。 |
| Outbound attempt | 发送前 reserve attempt；发送未开始失败可重试，发送已开始但无 receipt 写 `unknown_after_send`。 | 出站并没有跨所有 adapter 自动统一的分布式 lease schema。 |
| Plugin lifecycle lease | SQLite lease 串行化安装、配置和 index mutation，并支持 owned assertion。 | 生命周期互斥不等于请求级 runtime scope，也不等于 provider 执行 fencing。 |
| Agent event generation | run 绑定 session、owner 和 lifecycle generation；重启旋转 generation，使旧事件失效。 | 这是 Agent event 域的围栏，不是所有队列、插件和连接共用的全局 epoch。 |
| Worker live epoch | live event 校验 environment、session、run epoch、credential binding；不匹配时返回 fenced/epoch mismatch。 | 仅凭重新连接不能恢复旧 cursor，必须有同一 binding 的证明。 |
| Command generation | command queue 在 clear/recovery 时递增 generation 并忽略迟到 completion。 | lane release 只解除队头阻塞，不证明底层 task 或子进程已经终止。 |

恢复的统一不变量是：先读取 durable row 和 owner 条件，再决定 release、retry、reconcile 或 quarantine；恢复操作不能覆盖新 owner 的 ack/terminal。内存 `Map`/`Set` 只做同进程并发闸门和缓存，不能承担跨崩溃事实。

### 13.3 Unknown-send 的真实边界

`unknown_after_send` 不是普通失败。recovery 会优先调用 channel adapter 的 `durableFinal.reconcileUnknownSend`；只有确认已发送才构造 receipt 并执行 after-commit，未解决则保留 unknown/retryable 诊断，避免因 receipt 丢失而盲重发造成重复消息。

但该保证是 capability-gated，而不是所有渠道的全局保证。`durable-delivery` 默认可以使用 `best_effort`，只有调用方显式要求 `reconcileUnknownSend` 且 adapter 声明能力时才升级为 `required`。因此架构结论必须写成“具备能力的 adapter 不盲重发”，不能写成“所有渠道都能可靠查询第三方平台”。IRC 等没有可重放服务端 delivery id 的渠道尤其只能保证本地 accept-to-dispatch 窗口；第三方 receipt 丢失后的实际查询可靠性仍需 live channel 验证。

### 13.4 Live stream 与普通事件

worker live stream 是窄恢复协议，不代表 Gateway 所有事件都可重放。它维护 `ackedSeq`、pending map、pending bytes、run epoch 和 terminal state；乱序事件只推进连续前缀，超窗或超字节预算返回 `resync-required` 并清理 speculative pending。startup recovery 只有在 environment binding 和 run epoch 都匹配时才接受旧 ACK/cursor；credential rotation 或 session identity mutation 会清除 transient pending，并释放旧 run claim。

普通 Gateway event 仍是连接投影，客户端通常自行 refresh；它与 worker live stream 的 ACK/cursor contract 不应在文档中合并成一个“全局事件总线 replay”能力。断线、丢包、重复帧和真实 WS 重连本轮未运行验证。

### 13.5 Browser、process、media 与 SQLite 释放

- Browser：session tab registry 记录 profile、target、ownership 和 fingerprint；tracking 失败时会尝试关闭刚创建的 tab，生命周期结束和 sweep 关闭 tracked tabs。`best-effort cleanup` 只能产生诊断，不能证明远程 CDP 中不存在孤儿 tab；缺失 profile 证明时 durable ownership 会降级为 volatile。
- Process：stdio transport 在正常 close 后等待、杀进程树并最终 SIGKILL；child-process 还要处理 descendant 继承 pipe 的迟到输出。command queue 的 timeout/generation 只处理调度事实，supervisor/worker cleanup 才负责确认进程树和 tunnel 残留。
- Media：delivery media spool 先写 SQLite stage row，再写 `.part` 并原子改名；队列引用存在时保留最终文件，24 小时 orphan grace 扫描无引用 artifact。ack/row 完成后才释放 spool，避免先删附件导致恢复不可重放。
- SQLite：shared state、agent/session transcript、queue、plugin lifecycle 和 media stage 各自有明确 owner；WAL、短事务、schema preflight、迁移/quarantine 和权限约束是持久化底座。它们是多个 SQLite store/事务域，不应在文档中简化成一个全局事务。

### 13.6 测试与文档结构审计

测试结构按共址单测、Gateway/协议 contract、worker/runtime、channel/outbound recovery、browser/media/process，以及更重的 E2E/live/Docker 项目分层。代表性测试覆盖 dead-letter、claim token、simulated crash、unknown-send、ACK window、epoch fencing、browser tracking compensation、media spool durability 和 process cleanup；这些文件证明回归意图和静态分支存在，本轮没有执行 Vitest、真实 Gateway、真实 provider/channel、CDP 或 crash injection。

文档结构以根 README、根/目录级 `AGENTS.md`、`docs/concepts` 架构概念、`docs/channels` 渠道操作说明、包/插件 README 和本根 `ARCHITECTURE.md` 为主。渠道文档会记录各平台能力差异，例如 streaming、media cap、pairing 和 delivery replay 限制；这些产品文档不能替代核心协议或源码证据。根 `ARCHITECTURE.md` 作为本次静态审计的唯一汇总事实源，后续分段应继续追加到本文件，而不是恢复平行的细探笔记。

### 13.7 本轮结论与剩余风险

1. OpenClaw 的主链仍是 Gateway 控制面 → durable channel ingress → session/turn → model/tool → transcript/event → durable outbound delivery；没有发现需要增加第二条 Agent 执行链的源码证据。
2. unknown-send、claim、lease、generation 和 live ACK 都已出现实际实现，但分属不同 owner 域；平台抽象可以统一它们的术语和验收矩阵，不能声称源码已经拥有一个全局 lease/epoch。
3. 资源释放覆盖 browser tab、进程树、stdio、media spool、SQLite row 和 queue claim，但 owner 分散；现场无残留必须用进程、端口、文件、锁、tab 和数据库 row 探针单独验收。
4. 文档中应始终区分“源码路径存在”“测试设计覆盖”“本轮测试通过”和“真实第三方运行态已证实”四个证据等级。
5. CodeGraph 建图目录是本轮目标仓库的工程辅助产物；本轮只改根 `ARCHITECTURE.md`，不把 CodeGraph 数据库当作产品运行时依赖，也不据此替代测试。
