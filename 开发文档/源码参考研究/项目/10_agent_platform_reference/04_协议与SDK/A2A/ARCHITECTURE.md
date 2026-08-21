# A2A Protocol 架构建档

> 建档范围：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/04_协议与SDK/A2A`
>
> 定位：A2A（Agent2Agent）是面向不透明 Agent 应用的开放互操作协议。本仓库是“规范与文档仓库”，不是某一语言的 Agent 运行时实现；SDK 位于独立仓库。
>
> 证据范围：本档基于目标目录当前文件的实际读取，以及对 `细探-A2A协议.md` 的逐项对照。旧细探仍保留作历史参考；自本次收口后，架构事实只维护本文件。未运行构建、安装、启动或测试命令。

## 1. 架构总览

仓库的单一事实源是 `specification/a2a.proto`。协议数据模型、服务操作和 HTTP 注解从 proto 出发；规范正文位于 `docs/specification.md`，教程与主题文档位于 `docs/`；JSON Schema 是非规范、可再生构建产物；SDK 不在本仓库实现。

```text
                 ┌─────────────────────────────────────────────┐
                 │ Agent Discovery                             │
                 │ /.well-known/agent-card.json                │
                 │ 或注册中心/直接配置 → AgentCard              │
                 └──────────────────┬──────────────────────────┘
                                    │ 选择有序 supportedInterfaces
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Protocol bindings                                                   │
│ JSON-RPC 2.0 over HTTP(S) + SSE │ gRPC │ HTTP+JSON/REST + SSE        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ 抽象操作
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Task-centric data model                                            │
│ Message/Part → Task(status/history/artifacts)                      │
│ Part = text | raw | url | data                                     │
│ Artifact = task output                                             │
└───────────────┬──────────────────────┬─────────────────────────────┘
                │                      │
                ▼                      ▼
        GetTask 轮询              SSE 流 / Webhook 推送
        （状态快照）              （状态、消息、Artifact 增量）
                │                      │
                └──────────────┬───────┘
                               ▼
                    客户端消费结果/继续交互
```

### 1.1 四层分解

1. **规范数据模型层**：`Task`、`Message`、`Part`、`Artifact`、`AgentCard`、扩展和安全方案等，全部由 proto 定义。
2. **抽象操作层**：发送消息、流式发送、查询/列出/取消任务、订阅任务、推送配置管理、获取扩展 Agent Card。
3. **协议绑定层**：JSON-RPC、gRPC、HTTP+JSON，以及可由 URI 标识的自定义绑定。
4. **派生与发布层**：ProtoJSON 语义、JSON Schema 生成、MkDocs 站点、SDK API 文档与 CI 校验；派生文件不反向成为规范事实源。

## 2. 目录与职责

| 路径 | 职责 | 权威性/产物性质 |
|---|---|---|
| `specification/a2a.proto` | `lf.a2a.v1` 包；`A2AService`、消息、枚举、安全和 Agent Card 定义 | **规范数据模型唯一事实源** |
| `specification/json/README.md` | 说明 `a2a.json` 生成和禁止手工编辑 | 生成规则说明；`a2a.json` 为非规范产物 |
| `specification/buf.yaml`、`buf.lock`、`buf.gen.yaml` | Buf 模块依赖/锁定与多语言 protobuf/gRPC 生成配置 | 工具链配置 |
| `specification/.api-linter.yaml` | API linter 规则 | 校验配置 |
| `docs/specification.md`、`docs/definitions.md` | 协议解释、定义、工作流和约束 | 面向实现者的规范文档 |
| `docs/topics/` | 发现、任务生命周期、流式/异步、多租户、扩展、安全、A2A/MCP 等主题 | 概念与实现指导 |
| `docs/tutorials/python/` | Python SDK 服务端/客户端教程 | SDK 使用示例 |
| `docs/sdk/python/` | Python SDK API 文档源与生成结果承载目录 | 外部 SDK 文档集成 |
| `scripts/` | schema 生成、文档构建、SDK 文档构建、格式/拼写/lint | 构建与质量入口 |
| `adrs/` | 架构决策记录；当前可见 ADR-001 为 ProtoJSON 选择 | 决策证据 |
| `.github/workflows/` | 文档、链接、拼写、格式和 API linter 等 CI | 自动质量门禁 |
| `细探-A2A协议.md` | 已有的协议级细探报告 | 参考资料；不是规范源 |

## 3. 核心数据模型与状态机

### 3.1 AgentCard 与发现

`AgentCard` 是机器可读的 Agent 能力声明，包含名称、描述、提供者、版本、有序的 `supported_interfaces`、能力集合、安全方案/要求、默认输入输出 MIME 类型、技能、签名和可选图标/文档 URL。

`AgentInterface` 声明 URL、`protocol_binding`、可选不透明 `tenant` 和 `protocol_version`。接口列表有顺序，首项为偏好接口。发现方式包括 Well-Known URI、注册中心/目录或直接配置。认证后可通过 `GetExtendedAgentCard` 获取扩展卡片。

### 3.2 Task、Message、Part、Artifact

- `Task` 是核心工作单元：服务端生成 `id`，关联 `context_id`，持有 `status`、`artifacts`、`history` 和 `metadata`。
- `Message` 表示一轮客户端/Agent 通信，含创建方生成的 `message_id`、角色、可选任务/上下文引用、必需 `parts` 和扩展 URI。
- `Part` 通过 oneof 表示 `text`、`raw`（JSON 中 base64）、`url` 或结构化 `data`，并可附 `filename`、`media_type`、metadata。
- `Artifact` 是任务输出，与沟通用的 Message 分离；Artifact 可在流中按同一 ID 追加分块。

`TaskState` 在 proto 中包括：`UNSPECIFIED`、`SUBMITTED`、`WORKING`、`COMPLETED`、`FAILED`、`CANCELED`、`INPUT_REQUIRED`、`REJECTED`、`AUTH_REQUIRED`。其中 Completed/Failed/Canceled/Rejected 是终态，InputRequired/AuthRequired 是可恢复中断态。proto 注释和规范 `3.2.2` 将 `return_immediately=false`（默认）定义为等待终态/中断态，`true` 定义为创建后立即返回；但规范 `3.1.1` 的通用行为段又写成操作必须立即返回，存在文档内冲突，不能把两者同时宣称为无条件事实，见第 14.1 节。终态任务不可重启，后续交互应在同一上下文中新建任务；取消操作在规范语义上幂等，但不等于保证任务已停止。

## 4. 关键数据流与调用路径

### 4.1 规范到派生产物

```text
specification/a2a.proto
        │
        ├─ Buf / protoc → 多语言 protobuf/gRPC 源码（按配置输出到 src/*）
        │
        ├─ proto_to_json_schema.sh
        │     ├─ 清理特定注释
        │     ├─ protoc + bufbuild protoc-gen-jsonschema
        │     ├─ jq 合并 JSON Schema bundle
        │     └─ clean_schema_names.py 清理定义名/引用
        │              ↓
        │       specification/json/a2a.json（非规范、默认不提交）
        │
        └─ build_docs.sh
              ├─ 按 proto/schema 时间戳判断是否再生成
              ├─ 复制 schema/proto 到 docs/spec/
              ├─ 调用 build_sdk_docs.sh
              └─ mkdocs build 或 mike deploy → site/
```

`build_sdk_docs.sh` 的设计是创建 `.doc-venv`、安装文档依赖和 PyPI `a2a-sdk[all]`、用 `sphinx-apidoc` 生成 RST、分别生成 HTML/Text，再复制 HTML 到 `docs/sdk/python/api/`。该脚本是文档构建入口，不代表本仓库包含 Python SDK 源码。

### 4.2 任务交互

```text
Client
  │ 读取 AgentCard，选择 binding/version/tenant，准备 Message
  │
  ├─ POST /message:send ───────────────► A2A Server
  │                                      │ 创建/恢复 Task
  │                                      │ 处理并更新 status/artifacts
  │  ◄─ SendMessageResponse(task|message)┘
  │
  ├─ GET /tasks/{id}（轮询）────────────► Task 快照
  ├─ POST /message:stream ──────────────► SSE StreamResponse
  ├─ GET /tasks/{id}:subscribe ─────────► Task 快照 + 更新事件 SSE
  └─ 配置 webhook ──────────────────────► Server POST StreamResponse
```

流事件采用 `StreamResponse` oneof：Task、Message、`TaskStatusUpdateEvent`、`TaskArtifactUpdateEvent`。事件必须保持生成顺序；Artifact 更新支持 `append` 与 `last_chunk`。Webhook 使用任务推送配置中的 URL、token 和认证信息，实际投递/重试/SSRF 防护由服务端实现负责。

## 5. API / CLI / SDK 表面

### 5.1 A2AService API

`specification/a2a.proto` 的 `A2AService` 暴露以下 RPC 与 HTTP 映射：

| RPC | HTTP 映射 |
|---|---|
| `SendMessage` | `POST /message:send` |
| `SendStreamingMessage` | `POST /message:stream` |
| `GetTask` | `GET /tasks/{id=*}` |
| `ListTasks` | `GET /tasks` |
| `CancelTask` | `POST /tasks/{id=*}:cancel` |
| `SubscribeToTask` | `GET /tasks/{id=*}:subscribe` |
| `CreateTaskPushNotificationConfig` | `POST /tasks/{task_id=*}/pushNotificationConfigs` |
| `GetTaskPushNotificationConfig` | `GET /tasks/{task_id=*}/pushNotificationConfigs/{id=*}` |
| `ListTaskPushNotificationConfigs` | `GET /tasks/{task_id=*}/pushNotificationConfigs` |
| `DeleteTaskPushNotificationConfig` | `DELETE /tasks/{task_id=*}/pushNotificationConfigs/{id=*}` |
| `GetExtendedAgentCard` | `GET /extendedAgentCard` |

`specification/a2a.proto` 的 HTTP 注解当前将 `SubscribeToTask` 映射为 `GET /tasks/{id=*}:subscribe`；但 `docs/specification.md` 的方法映射表和 HTTP+JSON/REST 路径段仍写成 `POST /tasks/{id}:subscribe`。这是当前源码与规范正文的绑定冲突，不能在适配器中静默选择，见第 14.1 节。其余端点均有带 `/{tenant}` 的 additional binding（适用时）；JSON-RPC 方法名采用 PascalCase；gRPC 为 proto 生成的 server-streaming RPC；SSE 用于流式/订阅绑定。

### 5.2 CLI 与构建命令

本仓库未发现协议运行时 CLI 或 Agent 服务端命令。可见的是工程脚本入口：

- `./scripts/build_docs.sh [deploy]`：生成/发布 schema、构建 SDK 文档和 MkDocs；`deploy` 分支调用 mike。
- `./scripts/proto_to_json_schema.sh <output.json>`：从 proto 生成非规范 JSON Schema，需要 `protoc`、正确的 `protoc-gen-jsonschema`、`jq` 和 googleapis 注解依赖。
- `./scripts/build_sdk_docs.sh`：重建 Python SDK API 文档，需要 `uv`、文档依赖与 PyPI SDK。
- `./scripts/lint.sh`、`./scripts/format.sh`、`./scripts/sort_spelling.sh`：质量检查/格式/拼写相关入口。

### 5.3 SDK

README 声明 SDK 分属独立仓库：Python `a2aproject/a2a-python`（包名 `a2a-sdk`）、Go、JS、Java、.NET、Rust。当前仓库只承载协议源、文档和 SDK 文档构建集成；不存在可在本仓库内直接 import 的 SDK 实现目录。

## 6. 技术栈与协议决策

- **协议定义**：Protocol Buffers proto3，包名 `lf.a2a.v1`。
- **绑定/编码**：JSON-RPC 2.0、ProtoJSON、HTTP(S)、SSE、gRPC、HTTP+JSON。
- **文档**：MkDocs Material、Sphinx/Furo、MyST、mike；Python 文档构建通过 `uv` 管理环境。
- **生成工具**：Buf（含锁文件与远程插件配置）、`protoc`、bufbuild `protoc-gen-jsonschema`、`jq`、Python 清理脚本。
- **质量工具**：GitHub Actions、Super Linter、API Linter、markdownlint/格式脚本、链接检查与拼写检查。
- **治理/许可证**：Apache License 2.0；README 指向 Linux Foundation 治理与 TSC 决策。
- **ProtoJSON 决策**：`adrs/adr-001-protojson-serialization.md` 记录 ProtoJSON 为 JSON 序列化规范依据，接受枚举大写、未知字段无法 round-trip 等代价。

## 7. 测试、CI 与验证边界

本仓库的可见自动化重点是规范/文档质量，而不是运行时单元测试：

- PR linter workflow 执行 Super Linter。
- API linter workflow 使用 Buf 准备 googleapis 依赖，并对 `specification/a2a.proto` 执行 `api-linter --set-exit-status`。
- 另有 docs、links、spelling、conventional commits 等 workflow。
- 当前目录未发现 `tests/`、`test/` 或运行时 SDK 实现目录；协议兼容性测试/生态 TCK 属于外部项目线索，不应当假定包含在本仓库。
- 文档构建会产生 `site/`、`docs/spec/` 中的复制物和 SDK API 文档；这些是构建副作用，未在本次建档中执行。

## 8. 关键风险与安全边界

1. **规范源漂移**：手工修改 JSON Schema 或文档而不更新 proto，可能造成绑定和实现不一致；应以 proto 为先，并重新生成/校验派生物。
2. **多绑定等价性**：JSON-RPC、gRPC、HTTP+JSON 必须表达同一抽象操作；错误、认证、版本和 tenant 语义不能因绑定而分叉。
3. **任务数据可靠性**：Message 不等同于可靠结果存储；关键结果应放入 Artifact。SSE 断线恢复依赖重新订阅/查询，需由实现设计幂等和重放策略。
4. **授权与资源泄露**：Get/List/订阅/推送配置必须按调用者、租户和任务权限收口，错误响应不得泄露“资源不存在/无权限”的差异。
5. **Webhook SSRF 与凭据**：服务端必须校验 webhook URL，拒绝回环、私网和链路本地目标；认证信息/推送 token 必须按秘密处理，日志不得泄露。
6. **版本/生成工具链风险**：schema 生成依赖外部 protoc 插件和 googleapis；脚本检测插件实现，但本次未安装或执行工具链，环境可用性未确认。
7. **仓库边界风险**：SDK、样例、Inspector、TCK 在独立仓库；不能把外部仓库的实现细节误写成本仓库事实。

## 9. 未确认项

- 已读取当前 Git 基线：`main`、`16ba526`、`origin/main`，远端为 `https://github.com/google/A2A.git`；本次没有对 Git 做变更，发布版本仍需结合 `CHANGELOG.md` 与规范页理解，见第 11.1 节。
- 未执行 `buf generate`、`protoc`、schema 生成、MkDocs/Sphinx 构建、lint、链接检查或任何测试，因此工具链安装状态、当前构建是否通过、生成产物是否最新均未确认。
- README 列出的六语言 SDK 只通过外部仓库链接确认；各 SDK 的具体 API、版本和实现差异未纳入本仓库架构结论。
- `specification/a2a.proto` 的 HTTP 注解是当前可见的绑定依据；HTTP 运行时、鉴权中间件、重试策略、持久化和任务调度均由各实现决定，本仓库不提供实现。
- 专属 MCP 实例 `system_engineering_toolkit` 的 `project_context` 当前返回的是其固定项目“系统工程平台”，代码地图也未切换到目标 A2A 根目录；因此代码地图结果只能作为“已调用但上下文不匹配”的工具证据，目标架构结论以目标目录实际读取和已有细探文档为准。

## 10. 本次建档变更

本文件是目标根唯一持续维护的架构文档。旧细探 `细探-A2A协议.md` 未删除、未修改，仅作为本次吸收裁决的输入和历史线索；源码、依赖、测试、配置均未修改，未安装、启动、构建或提交任何内容。

## 11. 旧细探吸收后的补充架构事实

以下内容是旧细探中经当前源码、`docs/specification.md`、主题文档、ADR 和脚本交叉核对后，正式吸收到本文件的事实。协议约束优先以 `specification/a2a.proto` 和规范正文为准。

### 11.1 版本基线与事实层级

- 当前检出为 `main`，`HEAD` 为 `16ba526`；`origin` 指向 `https://github.com/google/A2A.git`。工作树包含本架构文档和旧细探两个未跟踪文档，未见源码改动。
- `CHANGELOG.md` 已记录 `1.0.1`（2026-05-26），其中包含 HTTP 绑定优先 `application/a2a+json` 等修订；`docs/specification.md` 顶部仍标注 latest released version 为 `1.0.0`。因此本档将其表述为“仓库变更记录已到 1.0.1、规范页标注仍为 1.0.0”，不把两者混写成同一个发布事实。
- 协议协商只使用 `Major.Minor`，patch 不参与兼容性协商。请求应带 `A2A-Version`；空值按 0.3 客户端兼容规则处理；接口不支持请求版本时返回 `VersionNotSupportedError`。HTTP 绑定使用头字段，其他绑定按各自的 service-parameter 规则传递。

### 11.2 任务交互语义的完整边界

- A2A 允许无状态 `Message` 直接响应，也允许创建有生命周期的 `Task`；实现可以是 message-only、task-generating 或 hybrid。`context_id` 把多个任务和独立消息归入同一逻辑交互上下文，`reference_task_ids` 用于表达后续任务对既有任务的引用。
- 终态任务不可重启。细化、并行跟进或基于既有结果的新请求，都应在同一 `context_id` 下创建新任务；客户端负责维护不同 Artifact 版本/变体的可接受关系，协议不替客户端追踪 Artifact 变异谱系。
- `Message` 是沟通回合，`Artifact` 是任务结果；关键结果不能只依赖瞬时消息或流事件。`Artifact` 具有任务内唯一 `artifact_id`，流式更新通过同 ID 配合 `append`、`last_chunk` 增量组装。
- `SendMessageConfiguration.return_immediately` 默认关闭：服务端应等待任务进入终态或 `INPUT_REQUIRED`/`AUTH_REQUIRED` 中断态；开启后创建任务即返回，由客户端通过 `GetTask`、`SubscribeToTask` 或推送配置继续获取进展。

### 11.3 发现、选择、签名与缓存

- `AgentCard.supported_interfaces` 是有序列表，客户端选择自己支持的第一条接口，并使用该项的 `url`、`protocol_binding`、`protocol_version`；若该项设置了不透明 `tenant`，客户端必须在每个请求消息回填完全相同的值，否则省略该字段。
- 标准发现位置是 `https://{domain}/.well-known/agent-card.json`；注册中心/目录和直接配置也属于规范允许的发现策略，但注册中心 API 不由本仓库规定。
- Agent Card 可使用 JWS 签名。签名前须按 RFC 8785 JCS 规范化，遵守 proto 字段 presence/默认值规则并排除 `signatures` 字段；多签名可支持密钥轮换。服务端/客户端应使用 `Cache-Control`、`ETag` 和条件请求降低重复拉取。
- `GetExtendedAgentCard` 是认证后的扩展卡片入口；能力字段位于 `AgentCapabilities.extended_agent_card`。未声明能力与“已声明但未配置扩展卡片”应区分为不同的能力/配置错误。

### 11.4 传输与异步送达

- 三种标准 binding 均映射同一抽象操作和数据模型：JSON-RPC 2.0 over HTTP(S)、gRPC server-streaming、HTTP+JSON/REST；自定义 binding 必须保持全部核心操作、数据模型、语义、错误映射和认证边界等价。
- `SendStreamingMessage` 与 `SubscribeToTask` 使用 `text/event-stream`/server streaming。流可以先返回一个 `Task` 或单个 `Message`，随后发送有序的状态/Artifact 更新；消息流必须在唯一 Message 后关闭，任务流的关闭条件在当前文档中存在“仅终态”与“终态或中断态”两种表述，见第 14.1 节。
- SSE 连接中断时，客户端可重新 `SubscribeToTask` 或 `GetTask`；协议没有额外的自动重连/事件 ID 机制，可靠重放、幂等和持久化由实现负责。
- 断连场景可配置任务推送 webhook，载荷复用 `StreamResponse`。服务端应进行 URL/SSRF 校验、认证发送、超时与重试；接收方应校验来源和任务 ID、幂等处理并返回 2xx。文档中的重试和 10–30 秒超时是实现建议，不写成 proto 层强制语义。

### 11.5 扩展、错误与安全

- 扩展由 URI 标识，能力在 `AgentCapabilities.extensions` 声明，请求可用 `A2A-Extensions` 激活。扩展可以增加 metadata/profile 约束、方法或状态机，但不得通过扩展修改核心结构定义或直接新增核心 enum 值；扩展默认非激活，`required=true` 才形成客户端必须遵循的硬要求。
- 统一错误模型是 code/message/details；details 使用 ProtoJSON `Any` 形态并带 `@type`，可用 `google.rpc.ErrorInfo`/`BadRequest` 提供结构化原因与字段错误。JSON-RPC、gRPC、HTTP 分别映射到各自的原生错误容器，但语义应一致。
- 所有任务/推送配置/列表/订阅操作都必须按已认证调用者权限、项目/组织或租户边界收口；授权失败不得泄露资源是否存在。生产 HTTP/gRPC 必须使用加密传输；凭据不放入协议业务 payload，按 Agent Card 声明的标准方案在传输层/HTTP metadata 中携带。
- 协议不定义提示词模板或 LLM 内部上下文实现；`AgentSkill.description`、`tags`、`examples` 是能力描述和发现素材，`context_id` 只是协议侧关联标识，具体 LLM 记忆/上下文由 Agent 实现决定。

### 11.6 单一事实源与构建管线细节

```text
specification/a2a.proto
        │
        ├─ buf/protoc 配置 → protobuf/gRPC 派生代码（由 SDK/外部仓库消费）
        ├─ proto_to_json_schema.sh
        │     ├─ 检查 protoc、bufbuild/protoschema-plugins、jq、googleapis
        │     ├─ 临时清理注释并生成 bundle
        │     └─ clean_schema_names.py → specification/json/a2a.json
        └─ build_docs.sh
              ├─ 按 proto/schema mtime 判断是否再生成 JSON Schema
              ├─ 复制 proto/schema 到 docs/spec/
              ├─ 调用 build_sdk_docs.sh
              └─ mkdocs build 或 mike deploy → site/
```

`specification/json/a2a.json` 是非规范、可再生产物，不能反向覆盖 proto。`build_sdk_docs.sh` 会删除并重建 `.doc-venv`，从 PyPI 安装 `a2a-sdk` 和文档依赖，经 `sphinx-apidoc`/`sphinx-build` 生成 Python API 文档，再复制到 `docs/sdk/python/api/`；这证明文档构建集成了外部 SDK，并不证明本仓库包含 SDK 运行时源码。

## 12. 旧细探吸收/未吸收裁决

### 12.1 已吸收

| 旧细探结论 | 裁决与证据 |
|---|---|
| A2A 是 Agent-to-Agent 的不透明协作协议，并与 MCP 形成 agent-to-agent / agent-to-tool 边界 | **吸收**。README、`docs/topics/a2a-and-mcp.md`、规范 Appendix B 一致；本仓库不提供 Agent 运行时。 |
| proto 为数据模型、服务和 HTTP 注解的主源，JSON Schema/文档/SDK 文档为派生或集成产物 | **吸收**。`specification/a2a.proto`、`specification/json/README.md`、三个构建脚本和 ADR-001 交叉证明。 |
| AgentCard、三种发现策略、有序接口、多租户 tenant、签名和缓存 | **吸收**。proto、规范第 8 节、`agent-discovery.md`、`multi-tenancy.md` 已写入第 11.3 节。 |
| Task 九态、阻塞/立即返回、终态不可重启、context/reference 编排 | **吸收**。proto、`life-of-a-task.md` 和规范第 3/4 节已写入第 11.2 节。 |
| Message/Part/Artifact 分工，Part 的 text/raw/url/data oneof 与流式 Artifact 增量 | **吸收**。proto 字段和流式规范已写入第 11.2/11.4 节。 |
| 11 个 RPC 及 JSON-RPC/gRPC/HTTP+JSON/SSE/Webhook 边界 | **吸收**。proto service 定义和规范绑定章节已写入第 11.4 节，现有 API 表保留。 |
| 结构化错误、能力门禁、授权作用域、Webhook SSRF 和凭据边界 | **吸收**。规范错误映射、安全章节及 `enterprise-ready.md`/`streaming-and-async.md` 支撑。 |
| 扩展 URI/required/激活、custom binding 等价性和治理边界 | **吸收**。`extensions.md`、`custom-protocol-bindings.md`、`extension-and-binding-governance.md` 支撑。 |
| ProtoJSON ADR 的标准化取舍与 v1.0 的破坏性变更线索 | **吸收为决策背景**。只保留可由 ADR/CHANGELOG 证明的序列化与迁移边界，不把历史名称当当前 API。 |

### 12.2 有证据但已修正措辞

1. 旧细探把仓库版本直接写成“当前 1.0.1”。现改为区分 `CHANGELOG.md` 的 1.0.1 修订记录与规范页的 1.0.0 latest 标注，避免发布标签、规范页和工作树状态混淆。
2. 旧细探在表格备注中提到 `SubscribeToTask` 存在 POST/GET 文档差异。本次以当前 `a2a.proto` 的 `GET /tasks/{id=*}:subscribe` 和规范正文为准，未吸收 POST 说法。
3. 旧细探把 webhook “至少一次投递、指数退避”写得接近强制协议语义。本次改为实现侧安全/可靠性建议；proto 只定义配置、URL、token 和 authentication 字段。
4. 旧细探把 TLS 1.3+ 写成建议基线。当前规范安全章节建议 TLS 1.3+，`enterprise-ready.md` 仍写 TLS 1.2 或更高；本档统一表述为生产必须加密、现代 TLS，具体最低版本由部署安全基线决定。

### 12.3 未吸收为本项目架构事实

- 旧细探提出的“映射到底座平台能力目录/任务状态机/审批流”等 10 条借鉴建议：它们是跨项目设计启发，不是 A2A 仓库的架构事实；未写入本项目事实章节。
- 外部 SDK、samples、Inspector、TCK、课程和未来路线图：仅保留 README/规范明确的外部边界或线索，不把外部仓库实现、测试通过情况或路线图承诺写成本仓库已有能力。
- “零运行时依赖”“平台不得引入 A2A 运行时依赖”“只允许 Python 标准库”等结论：不是本仓库源码/规范对自身的事实，且属于目标底座的另一个项目约束，未吸收。
- 旧细探中对 Message 历史持久化、流断连丢失、webhook 重试次数/投递次数等实现行为：协议仓库没有实现或持久化代码，保留为实现风险提示，不写成当前仓库已经验证的运行时行为。
- 旧细探列出的具体未来功能（如 `QuerySkill()`、动态 UX 协商、客户端发起方法、流可靠性增强）：仅作为 README 的路线图线索，不纳入当前能力清单。

旧细探文件本次未删除、未修改；后续如需继续研究，应先更新本文件的对应事实或裁决章节，避免重新形成第二个权威来源。

## 13. 第三轮底座映射：A2A 能力进入单链路底座的边界

> 本节是第三轮“基于底座的映射与裁决”，不是 A2A 仓库已有运行时实现的宣称。A2A 仓库只有 `specification/a2a.proto`、规范文档和生成/文档脚本；下述“公共协议契约、薄网关、运行核心、模块”是目标平台的落点设计。凡没有目标平台源码、注册表、调用器或运行验证支撑的内容，均标为**待核/装配计划**，不计为已实现。
>
> 事实依据：`specification/a2a.proto:19-140`（服务与 HTTP 注解）、`:142-208`（发送配置、任务和状态）、`:221-355`（Part/Message/Artifact/事件/接口）、`:358-453`（AgentCard、能力、扩展和技能）、`:469-515`（推送与安全方案）、`:648-812`（请求/响应和分页）；`docs/topics/agent-discovery.md`、`life-of-a-task.md`、`streaming-and-async.md`、`custom-protocol-bindings.md`、`enterprise-ready.md`。

### 13.1 落点总图：协议适配，不复制执行链

```text
外部 A2A Client / Agent
        │ 发现 AgentCard、选择 binding/version/tenant、带外获得凭据
        ▼
┌──────────────────────────────────────────────────────────────────┐
│ 薄网关 / A2A Adapter                                              │
│ Well-Known/目录/直配发现；缓存/ETag/签名校验；绑定选择与路由      │
│ JSON-RPC/HTTP+JSON/gRPC/SSE/Webhook 编解码；认证/授权前置；SSRF门 │
│ 只把请求转换成一个公共命令，把核心事件转换成多个协议送达形态     │
└──────────────────────────────┬───────────────────────────────────┘
                               │ 唯一公开调用入口
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ 公共协议契约 / 能力注册表                                          │
│ AgentCard/接口/扩展/安全声明；Message/Part；Task/状态；            │
│ Context/引用；Artifact/事件；错误、版本、幂等与资源责任契约        │
│ A2A 只是一个外部协议映射，不另立能力 id、任务表或执行入口          │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ 运行核心（唯一执行与状态权威）                                     │
│ 任务创建/状态迁移/取消/恢复；上下文与引用校验；事件顺序与重放；    │
│ Artifact 组装/制品索引；租约、超时、资源释放；统一错误与证据      │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ 领域模块 / provider 适配层                                         │
│ 只实现 skill/领域流程；提交受管命令、产出结果/候选事件/制品；      │
│ 不直写任务状态，不持有第二调度器，不绕过公共契约与运行核心         │
└──────────────────────────────────────────────────────────────────┘
```

**单链路结论**：AgentCard 是远端能力与接入方式的声明，不是本平台能力注册表的第二份权威；SSE/Webhook 是事件投影和送达方式，不是第二个任务状态机；协议 binding 是薄适配器，不是第二套业务流程；领域模块是执行策略，不是第二个执行权威。一个平台原子能力仍只有一个能力 id、一个契约 owner、一个公开入口和一条注册/调用路径。

### 13.2 现有能力命中表与落点裁决

| A2A 能力/事实 | 公共协议契约 | 薄网关 | 运行核心 | 领域模块 | 第三轮裁决 |
|---|---|---|---|---|---|
| AgentCard 身份、版本、skills、输入/输出 MIME | 保留规范化 `AgentCard`、接口、能力声明、扩展 URI、安全要求和签名摘要；映射到平台能力 id 时必须显式绑定 | 实现 Well-Known/目录/直配读取、缓存、ETag/签名校验、接口优选 | 只消费已验证的能力快照和版本，不把卡片描述当执行结果 | 提供技能实现与 MIME 支持声明 | **吸收为契约输入；待核平台注册表对接** |
| `supported_interfaces`、`protocol_binding`、`protocol_version`、`tenant` | 统一 binding/version/tenant 选择字段与兼容错误 | 选择首个本地支持接口，映射 PascalCase/HTTP/gRPC/SSE，回填不透明 tenant；拒绝版本不兼容 | 接收已经归一化的命令，不感知 HTTP 路径和 JSON-RPC id | 不得按 binding 复制领域流程 | **吸收为适配边界** |
| `Task`、九态 `TaskState`、`TaskStatus` | 任务 id、context id、状态、时间、历史/制品和状态事件成为公共任务契约 | 将请求/响应编解码为契约对象 | 唯一创建任务、分配状态、校验状态迁移、持久化/投影、发布事件 | 只申请执行/返回领域结果或阻塞原因 | **吸收；状态权威落运行核心** |
| `Message`、`Part`（text/raw/url/data） | 统一输入消息和多模态 Part；`message_id` 是请求幂等输入，`task_id/context_id` 关系需校验 | 解析绑定、大小/MIME/URL 形式检查，不擅自下载外部 URL | 校验上下文/任务归属、保留必要证据、把输入交给模块 | 只消费公共 Message/Part，不自定义平行消息协议 | **吸收；URL 引用不等于核心自动抓取** |
| `Artifact`、`artifact_id`、append/last_chunk | 统一制品、分块、完成标记、媒体类型和引用关系 | 将增量转换为 SSE/Webhook/轮询响应 | 唯一组装、去重、索引、完成和读取权限；结果不可只放瞬时 Message | 产出制品或制品片段，不自行决定版本谱系 | **吸收；制品 owner 待与平台制品库对接** |
| `context_id`、`reference_task_ids`、Artifact 引用 | 公共上下文/引用契约只表达关联、依赖和输入范围，不定义 LLM 私有记忆 | 透传并做格式/租户边界检查 | 校验引用任务可见、上下文一致、依赖是否满足；保留引用证据 | 通过公开查询消费引用结果，不跨任务表直读 | **吸收；上下文不是第二记忆系统** |
| `AUTH_REQUIRED`、`INPUT_REQUIRED` | 统一中断原因、继续所需输入/授权的结构化错误或事件 | 将带外授权/用户输入结果安全转发，禁止把凭据写进普通 payload/日志 | 唯一判断阻塞、恢复条件和状态迁移 | 只声明缺少的领域输入/权限，不自行恢复任务 | **吸收；授权链仍由核心编排** |
| `SendMessage`/`GetTask`/`ListTasks`/`CancelTask`/订阅/推送配置 | 抽象操作、错误、幂等、分页、权限和版本语义统一 | 路由、限流、认证、协议映射和响应投影 | 公开命令进入唯一调用器；查询/取消/配置变更走核心 owner | 不暴露额外旁路端点 | **吸收；禁止模块自建 A2A 端点** |
| JSON-RPC、HTTP+JSON、gRPC、SSE/custom binding | 同一逻辑请求/响应/错误/事件等价性契约 | 每个 binding 一个薄 adapter；自定义 binding 需声明 URI/version | 只接收/发布绑定无关的规范对象 | 不感知 binding | **吸收；custom binding 需单独兼容验收** |
| Webhook、token、AuthenticationInfo | 推送配置、投递事件、认证和幂等接收约束 | URL 校验、出站策略、认证头、超时/重试、回调隔离 | 产生待投递事件、记录投递结果和重试状态，但不由推送改变任务事实 | 不直接发 HTTP callback | **吸收为送达模块；任务事实仍由核心写入** |
| `security_schemes`/requirements、TLS、OAuth/OIDC/mTLS | 安全声明、认证挑战、授权失败语义和最小权限契约 | 传输加密、凭据解析/转发、身份认证、租户/能力授权前置 | 再做任务/制品/skill 资源级授权，统一 404/403 防枚举并记审计证据 | 不保管或打印长期凭据 | **吸收；凭据管理依赖平台安全支持库** |
| SSRF、外部 URL、资源限制 | 契约记录“引用/目标”与安全策略版本，不将任意 URL 视为可信资源 | 出站解析、DNS/IP、scheme/端口/重定向、私网/回环/链路本地拒绝、域名 allowlist 和 egress policy | 只有通过策略的受管资源句柄才可进入执行；取消/超时释放句柄 | 不能自行 `requests.get`/socket 访问任意地址 | **吸收安全边界；具体网络策略待平台核定** |

### 13.3 公共协议契约：字段、错误与版本的唯一 owner

公共契约只保留与跨 binding、跨模块稳定相关的语义，至少固定以下对象及不变量：

1. **发现契约**：`AgentCard`、`AgentInterface`、`AgentCapabilities`、`AgentSkill`、安全方案/要求、扩展和签名摘要。发现来源（Well-Known、注册中心、直配）是来源类型，不改变卡片结构；注册中心 API 不被 A2A 假定为标准能力。
2. **任务命令/结果契约**：`SendMessage`、查询、取消、订阅和推送配置均归一化成平台公共命令/查询。`return_immediately` 只改变等待策略，不改变任务 owner；`message_id`、任务 id、幂等键不能由网关重写成另一套 id。
3. **生命周期契约**：`SUBMITTED`/`WORKING` 为进行态；`INPUT_REQUIRED`/`AUTH_REQUIRED` 为可恢复中断态；`COMPLETED`/`FAILED`/`CANCELED`/`REJECTED` 为终态。`UNSPECIFIED` 只能表示未确定/非法落地态，不能作为已接受执行态。
4. **引用契约**：`context_id` 是逻辑交互分组，`reference_task_ids` 是显式引用/依赖，`task_id` 是具体任务关联；三者必须做权限、租户和上下文一致性校验。协议不规定内部 LLM memory，不能借 `context_id` 绕过持久化、授权或数据最小化。
5. **制品契约**：关键结果进入 `Artifact`；同一任务内 `artifact_id` 唯一，分块按生成顺序追加并以 `last_chunk` 收口。客户端负责跨任务变体/可接受版本谱系，平台若需要制品谱系必须在平台制品契约中另行显式建模，不能假设 A2A 已提供。
6. **错误契约**：绑定可使用各自原生错误容器，但必须保持 A2A 错误语义、结构化 details 和可重试判断一致。授权失败不得泄露资源是否存在；能力未声明、版本不支持、任务不可取消、终态订阅等必须映射为稳定错误码。
7. **版本/扩展契约**：`Major.Minor` 协商和 `A2A-Version` 进入适配器与契约校验；patch 不被当作协商版本。扩展 URI 默认不激活，`required=true` 才形成硬门禁；扩展不得偷偷增加核心 enum 或另建任务状态机。

**契约 owner 规则**：上述对象只能在公共协议契约/注册表定义一次；绑定 adapter 只做序列化与传输映射，模块只做领域映射，运行核心只做状态与执行事实。任何消费者不得复制一份 A2A DTO、错误码、状态转换表或 AgentCard 能力注册表。

### 13.4 薄网关职责：发现、绑定、送达与安全前置

薄网关允许拥有网络和协议职责，但不拥有业务执行事实：

- **发现**：按配置允许的来源读取 Agent Card；限制重定向和响应大小；校验 HTTPS/证书、签名（如使用 JWS/JCS）和有效期；缓存必须带版本/ETag/来源/校验结果，失效时不得悄悄回退到未验证旧卡。
- **接口选择**：按 `supported_interfaces` 顺序挑选本地支持的 binding/version；校验 `tenant` 与请求回填值完全一致；不兼容时返回统一版本错误，不让模块自行“试一圈”形成隐藏 fallback。
- **绑定映射**：JSON-RPC/HTTP+JSON/gRPC/SSE/custom binding 都转成同一个公共命令和同一个公共结果/事件；transport request id、HTTP status、gRPC status 只在边界映射，不进入领域状态。
- **SSE**：建立/关闭连接，发送首个 Task 快照、状态/制品更新并保持顺序；断线由客户端重新订阅或查询，网关不得凭连接存活推断任务状态；终态/中断态到达后关闭流。
- **Webhook**：接收推送配置后执行 SSRF/出站策略、认证头注入、连接/响应超时、有限重试和投递审计；投递失败只产生送达失败证据，不回写为任务 `FAILED`，除非运行核心有明确的领域命令决定该语义。
- **认证与授权前置**：按卡片声明的 scheme 获取/使用带外凭据，拒绝把 token、cookie、Authorization 值写入任务 metadata、普通日志或制品；网关的授权是前置过滤，核心仍须做资源级授权。

网关禁止：直接调用 provider、直接写任务/制品/状态库、自己生成“完成”状态、为每种 binding 复制编排流程、把 `Part.url` 当作无条件下载命令、用 webhook 回调作为第二执行入口。

### 13.5 运行核心职责：唯一状态、执行、取消与恢复权威

运行核心以命令和事件为边界，负责以下可验证不变量：

| 场景 | 核心动作 | 允许的外部表现 | 禁止的旁路 |
|---|---|---|---|
| 新消息 | 校验 message/context/task/reference、幂等接收、创建任务或返回无状态 Message | 阻塞返回或 `return_immediately` 快照；SSE/轮询/Webhook 读取同一事实 | 网关或模块各建任务 |
| 正常执行 | `SUBMITTED → WORKING → ...`，按事件顺序写入状态/制品/证据 | `TaskStatusUpdateEvent`、`TaskArtifactUpdateEvent`、GetTask 看到同一投影 | 以流事件顺序替代持久化事实 |
| `INPUT_REQUIRED` | 保存阻塞原因、所需输入、租户/调用者和恢复令牌/关联信息 | 同 task/context 的继续消息恢复；不新建隐藏执行者 | 模块自行改成 WORKING 或接受任意恢复 id |
| `AUTH_REQUIRED` | 保存所需权限/挑战引用，不保存长期秘密；等待外部授权完成 | 带外完成授权后由合法调用者继续同 task/context | 把凭据塞进 Message/metadata 或由 webhook 自动授权 |
| 取消 | 接收幂等取消命令，校验可取消窗口，与完成/失败竞态由核心裁决 | 成功则 `CANCELED`；已终态/不可取消返回统一错误或当前事实 | 关闭 SSE 就算取消、网关直接杀 provider、模块自行写 CANCELED |
| 终态 | 一次性收口 `COMPLETED`/`FAILED`/`CANCELED`/`REJECTED`，冻结任务状态 | 后续细化在同 `context_id` 新建任务并用 `reference_task_ids` 引用 | 重启终态任务、覆盖旧状态、以新 binding 复活任务 |
| 断线/重启 | 依据核心保存的任务/事件/制品恢复查询与订阅，未完成任务按租约/恢复策略重新调度 | GetTask/Subscribe/Webhook 重新投影同一任务事实 | 把客户端重连、SSE 重连当作新执行 |

取消必须是“请求取消”而非“保证已停止”：A2A 明确取消成功不保证，任务可能已完成/失败或当前阶段不支持取消；因此核心必须记录取消请求、裁决时点和最终状态。重复取消不应产生第二次业务效果。若取消与终态竞争，按核心的原子状态迁移/版本条件选择唯一结果，并保留未获胜命令的审计记录。

恢复只适用于中断态。`INPUT_REQUIRED` 恢复输入，`AUTH_REQUIRED` 恢复授权；恢复请求必须重新通过身份、租户、任务可见性、上下文和幂等校验。终态任务不可重启；相关细化、并行跟进或制品变体必须新建任务并显式引用旧任务/制品。这样既保留 A2A 生命周期语义，也避免“恢复”成为第二执行权威。

### 13.6 SSE、Webhook 与制品的资源生命周期

协议仓库没有运行时资源管理，目标底座装配时必须把以下资源写进统一资源契约；四类终态（正常、业务失败、主动取消/超时、宿主/子进程崩溃）都要有释放证据：

| 资源 | 创建/持有者 | 正常路径 | 失败/取消/崩溃路径 | 验收证据 |
|---|---|---|---|---|
| Agent Card HTTP 会话/缓存 | 网关 | 响应完整校验后更新缓存并释放连接 | 超时、超大响应、签名失败、断网均关闭连接；不写半卡片 | 连接/缓存条目、TTL/ETag、失败原因 |
| SSE 长连接与订阅句柄 | 网关持有连接，核心拥有订阅事实 | 事件按序发送，终态/中断态关闭 | 客户端断开、超时、取消、进程崩溃关闭 socket/取消监听；任务不因连接关闭而取消 | 活跃连接/订阅计数归零，任务状态不漂移 |
| Webhook 出站请求、重试队列 | 网关负责投递，核心负责投递事实/租约 | 2xx 记录成功并释放响应体/连接 | DNS/IP 拒绝、连接/响应超时、非 2xx、取消、重试耗尽释放 body/socket/队列租约；不无限重试 | 出站策略命中、投递记录、队列无界增长检查 |
| raw/url/data Part 缓冲 | 核心/模块按契约借用或转移 | 大小/MIME 校验后流式写制品或受管存储 | 超限、解析失败、取消、崩溃删除临时文件/释放缓冲；`url` 仅保留引用或经策略后读取 | 临时目录、句柄、制品 hash/大小、残留扫描 |
| Artifact 分块组装 | 核心拥有 artifact 聚合 | 校验 task/artifact id，按序 append，`last_chunk` 收口 | 重复/乱序/断流/取消保留不完整标记或清理临时版本，不伪造完成 | 分块序号/事件 hash、最终可读性、未完成标记 |
| 凭据、授权挑战、租约/锁 | 安全支持库/核心 | 只保存引用、短期令牌或加密句柄，按 TTL 释放 | 超时、拒绝、取消、崩溃立即撤销/擦除临时秘密并释放租约 | 日志脱敏、TTL/撤销记录、锁无残留 |

资源所有权必须随命令/事件显式传递：网关创建网络资源并释放；核心持有任务、事件、制品索引和订阅事实；模块只持有运行时输入/输出句柄。模块若需外部资源，必须通过受管 provider/支持库取得句柄，不能以 A2A `url`、metadata 或 webhook URL 直接打开任意网络。

### 13.7 安全授权与 SSRF 边界

1. **AgentCard 不是信任根**：卡片中的安全方案、scope、endpoint 和 skill 是声明；生产部署仍需配置的可信发行方、证书/签名信任链和租户策略。公开卡片与认证后的 Extended Agent Card 必须分别缓存、授权和审计。
2. **凭据带外传递**：A2A 规范建议 OAuth/OIDC/API key/mTLS 等通过传输层或 HTTP metadata 携带；公共契约只记录 scheme、scope、挑战引用和凭据来源，不接收长期秘密作为业务字段。
3. **双层授权**：网关验证调用者能否调用 binding/能力，运行核心再验证 task/context/artifact/tenant 的资源级权限；模块在实际敏感动作前继续做最小权限检查。任何一层拒绝都不得让另一层旁路执行。
4. **SSRF 适用于所有服务端主动出站**：至少覆盖 Agent Card 发现、Part URL（若实现选择抓取）、Webhook、OAuth/OIDC 元数据/JWKS 和 provider 请求。默认只允许 `https`（按协议 binding 明确的 gRPC 地址另行配置），拒绝回环、localhost、RFC1918 私网、链路本地、解析后落入禁止网段的域名、非允许端口和跨域重定向；DNS 解析必须在连接前后都校验，不能只校验原始 hostname。
5. **出站策略不可由请求者自带**：请求中的 webhook URL、Part URL、metadata、skill 参数只能成为待审查输入；allowlist、egress、防火墙、解析器和超时由平台安全配置/支持库拥有。失败返回结构化策略错误并记审计证据，不能静默降级到直连。
6. **回调接收方也要验证**：Webhook receiver 校验 A2A server 身份、token/签名、时间窗/nonce 或幂等事件标识、task_id/tenant 关联；重复回调只确认已处理，不能重复执行。服务端投递认证与接收方认证是两条边界，不能互相替代。
7. **资源枚举防护**：Get/List/Subscribe/推送配置和制品读取都按调用者/租户过滤；无权资源统一返回 not-found 语义或等价错误，不泄露存在性。分页、历史长度、制品包含开关、消息/文件大小和速率限制进入网关与核心的共同契约。

### 13.8 吸收、升级、隔离与待核清单

| 裁决 | 内容 | 进入位置 | 前置验收 |
|---|---|---|---|
| 吸收 | AgentCard/接口优选/版本/tenant、Task 生命周期、Message/Part/Artifact、Context/引用、统一错误、SSE/Webhook 送达语义 | 公共协议契约；网关 adapter 负责 binding | 跨 binding 同语义契约测试；非法上下文/终态/版本/能力调用拒绝 |
| 升级现有支持库 | HTTP/TLS、JWS/JCS、缓存/ETag、DNS/IP SSRF、OAuth/OIDC/mTLS、脱敏、重试/退避、连接/临时资源关闭 | 网络与安全支持库 | 私网/重定向/解析竞态/超时/取消/崩溃资源探针；凭据不进日志 |
| 升级现有模块 | 领域 skill 的 A2A Message → 公共命令、领域结果 → Artifact、缺输入/授权 → 中断事件 | 单一领域模块公开入口 | 模块不直写任务状态；结果 hash、制品 owner、授权链可追溯 |
| 隔离 | A2A binding 专有 JSON-RPC/SSE/Webhook 细节、远端 AgentCard 原始缓存、外部回调投递实现 | A2A 薄网关/适配层 | 禁止公共契约向上泄露 transport 对象；适配层可替换 |
| 待核 | 目标平台现有能力注册表、任务/制品 owner、事件存储、租约、统一 HTTP 客户端、出站 allowlist、TCK/兼容测试 | 装配计划，不宣称已实现 | 先能力搜索/占用租约/验收契约，再决定复用或新建 |

### 13.9 验收契约与装配计划（不等于本仓库已实现）

装配 A2A 适配器前必须形成以下最小证据，任何一项缺失只能标记“待核”：

1. **契约验收**：从 `a2a.proto` 生成/读取的字段、oneof、枚举、RPC/HTTP 映射与公共契约逐项对照；三种标准 binding 至少用同一组请求验证结果、错误、权限和版本语义等价。
2. **生命周期验收**：覆盖 message-only、task-generating、hybrid；所有进行态→中断态/终态边；终态拒绝追加消息；同 context 新任务+reference；重复 message/cancel；取消与完成竞态。
3. **恢复/重放验收**：SSE 断线后 GetTask/Subscribe 恢复同一事实；Webhook 重复/乱序/非 2xx 不重复执行；进程重启后任务、事件、制品和投递租约无第二执行者。
4. **引用/制品验收**：跨租户、错误 context、不可见 reference、缺失 artifact、分块重复/乱序/未收口均拒绝或显式标记；客户端/平台制品变体谱系不被协议字段冒充。
5. **安全验收**：AgentCard 签名/缓存、带外凭据、scope/租户授权、资源枚举、Part URL/Webhook/OIDC/JWKS SSRF、重定向、DNS rebinding、超时/限速和日志脱敏。
6. **资源验收**：正常完成、业务失败、主动取消/超时、宿主崩溃后检查 socket、SSE listener、队列租约、临时文件、缓冲区、锁、token 和 provider 进程无界残留。
7. **唯一权威验收**：调用链必须为 `A2A binding → 公共命令 → 唯一能力调用器/任务核心 → 模块/provider → 核心事件/制品 → binding 投影`；静态搜索和运行探针证明不存在网关写库、模块直发 callback、binding 自建状态机或第二调度器。

**装配顺序**：先做目标平台能力搜索与 owner/租约确认；再复用或升级公共契约、HTTP/安全支持库；然后实现一个不带 Webhook 的轮询纵切（发现→发送→任务终态→Artifact）；再接入 SSE 重订阅；最后接入 Webhook/SSRF/制品大对象和跨 binding 兼容门禁。每一步只增加一个公开入口，不为兼容旧入口复制执行核心。

### 13.10 第三轮结论

- **吸收**：A2A 对 AgentCard 发现、任务终态/中断态、上下文与引用、统一 Artifact、协议 binding 等价性、SSE/Webhook 送达、授权声明和 SSRF 防护提供了可复用的公共契约样本。
- **升级**：平台需要把网络安全、资源生命周期、缓存/签名、幂等/重放、投递审计和跨 binding 兼容测试纳入已有支持库/发布门禁，而不是放到每个模块自行实现。
- **隔离**：A2A 的原始卡片、JSON-RPC/SSE/Webhook 载荷和远端 binding 细节留在薄网关；A2A 不成为平台运行时依赖，也不取代平台能力注册表、任务核心、制品库或安全 owner。
- **待核**：本仓库不含实现，且本工作包尚未取得目标平台 `system_engineering_toolkit` 的正确代码地图、能力搜索和运行验证；因此本节是有源码证据的底座输入与装配门禁，不是“已接入 A2A”的完成证明。

## 14. 第二轮协议契约收口：任务、消息、流式、身份、错误、取消、幂等与资源

本节是第二轮逐条核对的正式收口。证据优先级为：当前 `specification/a2a.proto` 的字段、RPC 和 HTTP 注解 > 当前 `docs/specification.md` 的绑定无关语义 > 主题文档/README/旧细探。A2A 仓库没有任务运行时、数据库、HTTP 客户端或 webhook worker，因此本节把“协议强制语义”“规范建议”“实现尚未定义”明确分栏，不把目标平台装配设计冒充仓库实现。

### 14.1 逐条核对后的冲突与裁决

| 主题 | 当前源码/规范证据 | 第二轮裁决 |
|---|---|---|
| `SendMessage` 返回时机 | `specification/a2a.proto:155-160` 与 `docs/specification.md:442-448`：`return_immediately=false` 默认等待终态/中断态，`true` 创建后立即返回；但 `docs/specification.md:178-180` 的通用行为又写“必须立即返回” | **文档内冲突，未静默裁决**。适配器必须绑定一个明确版本/实现策略并写兼容测试；不能同时宣称默认阻塞和所有操作立即返回都无条件成立。以 `SendMessageConfiguration` 及 proto 注释为任务等待实现的首选证据，但仍标注该冲突。 |
| `SubscribeToTask` HTTP 方法 | `specification/a2a.proto:76-81` 当前注解为 `GET /tasks/{id=*}:subscribe`；`docs/specification.md:1162-1174` 方法映射表、`:2800-2805` REST 路径段写为 `POST` | **绑定冲突，不能隐藏**。当前源码生成链按 proto 取 `GET`；若兼容规范文档的 `POST`，必须作为显式兼容入口并验证两者语义等价，不能让不同 binding 形成两套订阅流程。 |
| 流的结束条件 | `docs/specification.md:206-212` 任务流写终态关闭；`:309-311` 订阅流写终态关闭；`docs/topics/streaming-and-async.md:23-25` 又把 `INPUT_REQUIRED` 列为关闭条件 | **规范文本冲突**。Message-only 流“恰好一个 Message 后关闭”是明确的；Task 流必须至少在终态关闭，遇到中断态是否关闭需按选定版本/实现明示，不能用 SSE 连接关闭推断任务已取消。 |
| SendMessage 幂等 | `docs/specification.md:492-496`：Get 类操作天然幂等，SendMessage **MAY** 用 `messageId` 去重 | `message_id` 是消息创建者生成且必填的消息标识，不是规范强制的 `Idempotency-Key`。协议未定义去重窗口、指纹、冲突处理或重复请求返回形态；实现若启用去重必须补齐这些边界。 |
| CancelTask 幂等 | `docs/specification.md:264-283`：取消只是尝试，成功不保证；`:492-496`：操作幂等，任务已清理时重复请求 MAY 返回 `TaskNotFoundError` | 幂等表示重复请求不产生第二次取消业务效果，不表示每次返回相同快照，也不表示 provider 已经停止。取消与完成/失败竞态必须由唯一任务 owner 原子裁决；连接断开不是取消。 |

### 14.2 身份、路由和授权契约

| 对象/边界 | 强制或已定义语义 | 未定义/实现责任 |
|---|---|---|
| Agent 身份声明 | `AgentCard` 的 `name`、`provider`、`version`、`supported_interfaces`、skills、security schemes 是机器可读声明；`AgentInterface` 的 `url`、binding、version 和可选 `tenant` 决定接入选择（`a2a.proto:334-355,358-453`） | AgentCard 不是自动信任根，也不是调用者身份凭证。签名字段存在并可按 JWS/JCS 规则使用，但信任锚、密钥轮换、撤销和卡片缓存隔离由部署负责。 |
| 调用者身份 | `docs/topics/enterprise-ready.md:30-62` 明确身份在 TLS/HTTP metadata/标准认证层建立，业务 payload 不承载用户或客户端身份；凭据带外获取并放入标准 header | A2A 不规定用户、agent、组织或服务账号的统一 principal schema；适配器必须把认证 principal、授权结果和审计上下文安全传给核心，但不得把 Authorization/token/cookie 塞入 Message metadata 或日志。 |
| `tenant` | 每个请求消息有可选 opaque `tenant`；选中的 `AgentInterface.tenant` 非空时，客户端必须在每个请求原样回填；接口未设置时请求必须省略（`docs/topics/multi-tenancy.md:73-107`） | `tenant` 只是路由/租户分区键，不是身份验证、权限授予或资源 owner。格式、生命周期、跨租户授权和与 URL/header 的组合由服务端定义；task/context/artifact/config 的查询、订阅、取消和推送配置仍须做 principal + tenant 双重授权。 |
| ID 语义 | `task.id` 服务端生成且新任务唯一；`context_id` 逻辑聚合任务/消息；`message_id` 由创建消息的一方生成；`artifact_id` 在任务内唯一（`a2a.proto:167-183,260-293`） | 这些 ID 都不是调用者身份，也没有协议级全局 UUID 格式、可见性、保留期或跨租户唯一性保证。资源查找不得仅凭 ID 放行；先认证、再授权、再查询，未授权资源统一按不可见/NotFound 语义处理。 |
| Extended Agent Card | `GetExtendedAgentCard` 必须认证；公开卡声明 `extended_agent_card` 能力后才可调用；未配置区分 `ExtendedAgentCardNotConfiguredError`（`docs/specification.md:404-428,3146-3177`） | 扩展卡片可按认证等级返回不同内容，缓存、版本、敏感字段过滤和会话替换由实现负责；不能把扩展卡片中的 quota/skill 描述当作已授予的执行权限。 |

**身份结论**：A2A 的“身份”是三段式边界——AgentCard 的被发现声明、传输层认证的调用者 principal、资源层的 task/context/tenant 授权。`name`、`provider`、`context_id`、`tenant` 及 token 各自职责不同，不能互相替代。

### 14.3 任务、消息、制品的可验收契约

1. **创建与关联**：客户端发送 `Message` 可得到无状态 `Message`，也可得到有生命周期的 `Task`；message-only、task-generating、hybrid 都是规范允许模式（`docs/topics/life-of-a-task.md:35-69`）。新 `Task.id` 由服务端生成；客户端给出 `task_id` 时只能引用既有任务，不能借此创建指定 ID 的新任务。
2. **上下文规则**：客户端可以只给 `context_id` 创建同一逻辑上下文中的新任务，也可以只给 `task_id`，此时服务端必须从任务推断 context；同时给出二者且不匹配必须拒绝（`docs/specification.md:584-628`）。服务端不能接受不了的 client context 后又悄悄生成另一个 context。
3. **终态不可变**：`COMPLETED`、`FAILED`、`CANCELED`、`REJECTED` 是终态，终态任务不再接受消息；细化、并行跟进和变体必须在相同 `context_id` 下新建 task，并可用 `reference_task_ids` 指向旧任务。`INPUT_REQUIRED`、`AUTH_REQUIRED` 是中断态，恢复请求必须再次通过身份、租户、任务可见性和幂等校验。
4. **Message 契约**：`message_id`、`role`、`parts` 是必需核心字段；服务端消息需要 `context_id`，客户端消息若同时带 task/context 必须一致；`ROLE_USER`/`ROLE_AGENT` 表示通信方向，不表示权限。`parts` 至少一个，Part 的 `oneof content` 只能是 `text`、`raw`、`url`、`data` 之一，JSON 中 `raw` 为 base64；`filename`/`media_type`/metadata 是附加描述。
5. **Artifact 契约**：Artifact 是任务输出，不是 Message 的别名；`artifact_id` 在任务内唯一，`parts` 至少一个。关键结果应进入 Artifact；历史消息可能未持久化，流断线后重连也可能错过瞬时 status message，因此 Message/流事件不能作为关键结果的唯一可靠存储（`docs/specification.md:747-764`）。
6. **引用与变体**：`reference_task_ids` 表达相关任务引用，但协议不提供 artifact 变异谱系或“最新版本”权威字段；旧细探所称的客户端 artifact 版本管理是实现/编排建议，不是 A2A 运行时事实。服务端对引用任务/制品必须校验可见性、context/tenant 关系和依赖是否满足。

### 14.4 流式、订阅和 Webhook 的送达契约

| 机制 | 首事件/载荷 | 顺序与断线 | 终止、重复和资源边界 |
|---|---|---|---|
| `SendStreamingMessage` | 若返回 Message，必须恰好一个 Message 后关闭；若返回 Task，首个事件是 Task，之后是 `TaskStatusUpdateEvent`/`TaskArtifactUpdateEvent` | 事件按生成顺序发送；同一 task 可有多个并发流，每条流收到同序事件，关闭一条不得影响任务或其他流 | `streaming` 未声明必须返回 `UnsupportedOperationError`；协议没有事件 ID、游标、Last-Event-ID 或重放窗口；断线后只能重新订阅/查询，消息可能丢失 |
| `SubscribeToTask` | 必须先返回订阅时刻的 Task 快照，避免 GetTask 与订阅之间的窗口丢失 | 任务生命周期独立于单条连接；订阅终态任务规范上不支持并返回 `UnsupportedOperationError` | 当前 proto 是 GET、规范 REST 文本是 POST；必须在 binding 适配器层固定/兼容。连接关闭不等于 CancelTask |
| Polling `GetTask` | 返回当前 Task，`history_length` 控制最多返回最近消息；0 请求不返回 history | 只保证当前快照，不提供事件序列/增量游标；`include_artifacts=false` 时列表响应必须省略 artifacts 字段 | 资源已过期/清理或调用者无权时可按 `TaskNotFoundError`/不可见处理；返回 payload 大小与历史保留由实现限额 |
| Push Notification | webhook POST 的 body 复用 `StreamResponse`，四选一：task/message/statusUpdate/artifactUpdate；认证信息放 HTTP header | 服务端对每个配置至少尝试投递一次；失败重试、退避、超时和停止条件是实现建议/策略，不是 proto 字段；接收端必须校验来源、task ID 并幂等处理 | 接收端以 2xx 确认；重复投递可能发生。配置应持续到任务完成或显式删除；删除操作必须幂等。URL、token、authentication 是出站资源和秘密，不能旁路进入领域执行 |

**Artifact 分块不变量**：`TaskArtifactUpdateEvent` 用同一 `artifact_id`、`append` 和 `last_chunk` 组装增量；proto 没有 chunk sequence、事件 ID 或 hash 字段，因此乱序/重复检测、临时版本、断流重放和最终一致性不是协议已给出的机制，必须由实现补强，不能把“按流顺序”扩大解释为跨重连全局顺序。

### 14.5 错误、能力门禁和可重试边界

协议错误的公共形状是 machine-readable code + message + 可选 details；details 中的 ProtoJSON `Any` 必须带 `@type`，binding 只映射容器、不改变语义（`docs/specification.md:498-563`）。当前 A2A 专属映射如下：

| A2A 错误 | JSON-RPC | gRPC | HTTP | 典型触发 |
|---|---:|---|---|---|
| `TaskNotFoundError` | -32001 | `NOT_FOUND` | 404 | task/config 不存在、过期清理或调用者不可见 |
| `TaskNotCancelableError` | -32002 | `FAILED_PRECONDITION` | 400 | 任务已终态或当前阶段不可取消 |
| `PushNotificationNotSupportedError` | -32003 | `FAILED_PRECONDITION` | 400 | 未声明 push 能力却操作配置 |
| `UnsupportedOperationError` | -32004 | `FAILED_PRECONDITION` | 400 | 未声明 streaming、终态订阅、终态任务追加消息等 |
| `ContentTypeNotSupportedError` | -32005 | `INVALID_ARGUMENT` | 400 | Part/artifact MIME 不支持 |
| `InvalidAgentResponseError` | -32006 | `INTERNAL` | 500 | Agent 返回不符合当前方法的响应 |
| `ExtendedAgentCardNotConfiguredError` | -32007 | `FAILED_PRECONDITION` | 400 | 声明扩展卡能力但没有配置 |
| `ExtensionSupportRequiredError` | -32008 | `FAILED_PRECONDITION` | 400 | required extension 未被客户端声明支持 |
| `VersionNotSupportedError` | -32009 | `FAILED_PRECONDITION` | 400 | `A2A-Version` 的 Major.Minor 不支持 |

错误分类还必须覆盖：认证失败（HTTP 401/gRPC `UNAUTHENTICATED`，应带 challenge）、授权不足（HTTP 403/gRPC `PERMISSION_DENIED`）、非法参数（HTTP 400/gRPC `INVALID_ARGUMENT`）、资源不存在/不可见（HTTP 404/gRPC `NOT_FOUND`）和系统临时错误（例如 503/`UNAVAILABLE`）。授权检查必须发生在可能泄露资源存在性的查询前（`docs/specification.md:3083-3109`）。

**可重试边界**：A2A 没有统一 `retryable` 字段、`Retry-After` 强制语义或通用 `Idempotency-Key`。客户端只能按 binding 状态、A2A 错误类型、认证/授权结果和实现提供的 retry guidance 决定重试；SendMessage 重试在服务端未启用 `message_id` 去重时可能创建多个任务，不能默认安全重试。Webhook 发送端可重试，接收端必须按事件/任务事实幂等。

### 14.6 取消、幂等与并发竞态

| 操作 | 协议性质 | 第二轮实现验收要求 |
|---|---|---|
| Get/List/Get Extended Card | 天然幂等 | 同 principal/tenant 重复读取不改变任务事实；分页 cursor、history/artifact 裁剪只影响投影，不另建任务 |
| SendMessage/SendStreamingMessage | 幂等 MAY，非 MUST；可用 `message_id` 检测重复 | 明确 dedupe key 的作用域（至少 principal/tenant + message_id）、保留窗口、payload 冲突行为和原始结果复用；重复请求不能在未裁决时产生两个执行者。Streaming 重试不得把连接重建当新消息，除非实现明确新 message_id |
| CancelTask | 幂等；成功不保证已停止；重复时任务可能已被清理 | 取消命令与终态写入必须原子竞争；返回任务快照或稳定错误；provider 停止、队列撤销、子进程回收必须另有资源证据；关闭流只释放连接，不写 CANCELED |
| Delete push config | 规范明确幂等 | 删除与投递并发时定义线性化点；线性化后不再产生新投递，已发出的请求仍需由接收端幂等处理；凭据/队列租约释放可验证 |

proto 只有 `message_id`、task ID 和 Cancel metadata，没有 deadline、取消 token、版本号或条件更新字段。因而“重复取消只一次”“取消与完成谁赢”“消息去重后返回原响应”都不是仅凭 proto 能实现的结论，必须落在唯一任务核心并以审计/版本条件写入证据。

### 14.7 资源边界与四类终态

| 资源 | 协议给出的边界 | 实现必须补齐的边界/释放证据 |
|---|---|---|
| Message/Part/metadata | Part oneof；raw 在 JSON 为 base64；Artifact/Message parts 必须非空；MIME 必须验证 | 协议没有消息、raw、metadata、嵌套复杂度的数值上限；必须在网关限尺寸、限深度、限 MIME，超限在进入模块前返回结构化验证错误，并释放临时 buffer |
| `Part.url` / Artifact URL | URL 是内容引用；HTTP binding 要求验证文件引用防 SSRF（`docs/specification.md:3234-3257`） | 不得默认下载任意 URL；若实现抓取，要做 scheme/端口/DNS/IP/重定向/响应大小/超时策略，成功与失败都关闭连接并清理临时文件；否则仅保存受管引用 |
| Task/history/artifacts | `history_length` 可限制返回消息；List 默认 `include_artifacts=false` 且省略字段；Task 可过期/清理后变为不可见 | 保留期、归档、删除、Artifact 大小和制品存储不由协议规定；不能把 GetTask 当前快照当永久事实源，必须记录 purge/retention 对 NotFound、审计和重放的影响 |
| SSE/gRPC stream | 事件有序、多个流互不影响、任务不依附于连接 | 每条 socket/listener/subscription 必须在正常结束、客户端断开、超时、取消、服务崩溃后释放；连接数、缓冲区、慢消费者和事件积压必须有上限；不因连接断开修改任务状态 |
| Webhook 出站 | 至少一次尝试；认证 header；接收端 2xx；重复投递可能发生；10–30 秒超时、指数退避等是建议 | SSRF/allowlist/egress、DNS rebinding、响应体上限、连接池、重试次数/退避、队列租约、token 擦除和投递审计必须显式配置；失败只记录送达失败，不自动伪造任务 FAILED |
| 认证秘密 | AgentCard 声明 scheme；`AuthenticationInfo.credentials`、push token 用于出站认证 | 凭据只放安全存储/短期句柄，日志、异常、Task metadata、Artifact 和普通 tracing 均脱敏；超时、取消、拒绝、崩溃后撤销/擦除或释放租约 |
| provider/子进程/外部连接 | 本协议仓库不创建这些运行时资源 | 运行核心必须将 provider 取消、超时、崩溃映射到唯一任务事实，并验证无孤儿进程、端口、锁、文件、连接、队列租约；不能由 binding adapter 直接杀 provider 或写 CANCELED |

四类终态验收必须分别覆盖：正常完成、业务失败、主动取消/超时、宿主/子进程崩溃。每类都要读回 Task 状态、Artifact 完成标志、事件/投递记录以及 socket、临时文件、锁、token、provider 进程等资源现场；仅看到日志或流关闭不算释放证明。

### 14.8 旧细探逐条吸收与未吸收项

| 旧细探主题 | 第二轮收口 |
|---|---|
| AgentCard/有序接口/tenant/认证与签名 | **吸收并收紧**：补上“声明不等于信任/权限”“tenant 不等于身份”的边界；证据为 `a2a.proto:334-453`、`docs/topics/multi-tenancy.md`、`docs/topics/enterprise-ready.md`。 |
| Task 九态、终态不可重启、context/reference | **吸收**：补上 task/context/message ID 各自作用域、不可接受 client task ID、恢复重新授权和 purge 后 NotFound。 |
| Message/Part/Artifact | **吸收并收紧**：补上 parts 非空、oneof、Message 历史不可靠、Artifact 变体谱系不属于协议。 |
| SSE/订阅/Webhook | **吸收并修正**：补上首快照、多流广播、无事件 ID/重放游标、断线不等于取消、至少一次投递与接收端幂等；记录终止条件和 Subscribe HTTP 方法冲突。 |
| 错误/能力门禁 | **吸收**：补齐 9 个 A2A 错误的 JSON-RPC/gRPC/HTTP 映射，以及 401/403/404 防枚举边界。 |
| 幂等/取消/重试 | **吸收并降级措辞**：SendMessage 去重是 MAY，不是 MUST；CancelTask 幂等但非停止保证；没有协议级 Idempotency-Key、deadline、retryable 字段。 |
| 资源与 SSRF | **吸收为实现边界**：规范只给安全要求和“应限制大小/复杂度”的建议，没有数值上限、资源 owner、崩溃清理或重放实现；具体资源表仍是目标适配器的验收契约。 |
| 旧细探的底座映射建议、外部 SDK/TCK 和路线图 | **不吸收为 A2A 仓库事实**：继续保留在第 13 节的“底座输入/旁路线索”边界，不改写成当前仓库已实现能力。 |

### 14.9 第二轮验证等级与剩余风险

| 验证项 | 等级 | 证据/结果 |
|---|---|---|
| RPC、TaskState、oneof 数量 | **源码静态已核对** | 对 `specification/a2a.proto` 解析得到 11 个 RPC、9 个 `TaskState`、5 个 oneof；与文档 API 表交叉核对。 |
| 任务/消息/流式/错误/安全语义 | **源码 + 规范文本已核对** | 逐段读取 `a2a.proto`、`docs/specification.md`、`life-of-a-task.md`、`streaming-and-async.md`、`multi-tenancy.md`、`enterprise-ready.md`；冲突已列入第 14.1 节。 |
| SendMessage、CancelTask、SSE、Webhook 实际行为 | **未验证** | 当前仓库无运行时实现、SDK 源码或本地服务；未安装依赖、未启动服务、未运行外部 SDK/TCK。 |
| 幂等窗口、事件重放、取消竞态、崩溃清理 | **协议未定义/待实现验证** | proto 没有幂等键、事件序号、取消 token、deadline 或资源生命周期字段；必须由实现与兼容测试补足。 |
| 数值资源上限与保留策略 | **规范建议，未实现验证** | 规范要求实现设置消息/文件/复杂度/速率限制，但没有统一数值；禁止把旧细探中的具体超时/重试/容量当 A2A 强制值。 |

**第二轮结论**：A2A 可直接吸收的是跨 binding 的任务/消息/Artifact 数据契约、能力门禁、身份声明与传输认证分层、三类送达模型、结构化错误和资源安全原则；必须由实现补足的是幂等去重、事件重放、取消竞态、Webhook 投递状态、大小/速率/保留限额与四类终态的释放证据。当前唯一权威事实仍是本文件与源码/规范路径，`细探-A2A协议.md` 保留为旧细探输入，不删除、不修改，不再作为独立事实源。

### 14.10 第二轮跨边界收口：绑定、认证、事件与跨进程

本小节把“协议对象离开进程以后如何保持同一事实”单独收口。A2A 规定的是远端 Agent 之间的应用协议，不规定 Agent 内部使用线程、进程、队列、数据库还是容器；因此下列跨进程内容是**实现必须满足的边界契约**，不是 A2A 新增的传输绑定。

#### 14.10.1 绑定边界与线协议

| 边界 | 线上形态 | 必须保持的语义 | 不得外泄的实现细节 |
|---|---|---|---|
| JSON-RPC | HTTP(S) 请求体为 JSON-RPC 2.0；方法名使用 `SendMessage` 等 PascalCase；普通响应为单个 `result` 或 `error` | `id` 只关联请求/响应；A2A-Version、A2A-Extensions、Authorization 等 service parameter 走 HTTP header；流式响应为 `text/event-stream`，每条 `data` 是 JSON-RPC response | 内部队列 id、worker pid、数据库主键、重试次数不能成为 Task/Message 的替代 id |
| HTTP+JSON/REST | `POST /message:send`、`POST /message:stream`、任务查询/取消/订阅及推送配置路径按 proto HTTP 注解映射；HTTP JSON 优先使用 `application/a2a+json` | ProtoJSON 字段语义、camelCase、枚举名、Timestamp 字符串、base64 raw 和 oneof presence 必须一致；GET/DELETE 的参数走 path/query | HTTP status、反向代理 request id 只在适配器边界转换，不写入任务状态机 |
| gRPC | `lf.a2a.v1.A2AService`，protobuf over HTTP/2；流式 RPC 为 server-streaming | Service parameter 走 metadata；`google.rpc.Status`/`Any` 承载与其他 binding 等价的错误；同一 `StreamResponse` 顺序不变 | channel、stream、server interceptor 和进程内 cancellation token 不成为公共业务字段 |
| Webhook | 服务端向客户端配置的 URL 发 HTTP POST，body 是单个 `StreamResponse` | 至少尝试投递一次；接收端以 2xx 确认并幂等处理；认证放 header；投递失败是送达事实，不自动改写 Task 状态 | callback worker、签名私钥、出站连接池和队列 lease 不得进入 Message metadata/Artifact |

`SubscribeToTask` 当前以 `specification/a2a.proto` 的 `GET /tasks/{id=*}:subscribe` 为生成依据；规范正文仍出现 POST。两者不是可由客户端猜测的“等价细节”：实现必须选定版本策略，若同时兼容，必须在同一订阅核心上提供显式兼容映射，并保证错误、首快照、事件顺序和关闭条件完全相同。JSON-RPC 的 `application/json` 与 HTTP+JSON 的 `application/a2a+json` 是绑定层媒体类型差异，不得导致对象或错误语义分叉。

#### 14.10.2 认证、授权与跨进程上下文传递

跨进程调用应传递**受限的认证上下文**而不是原始凭据。最小上下文包括：已验证的 principal 标识、认证方案/强度、授权 scope、tenant、请求版本、扩展集合、关联/追踪标识和审计引用；Authorization、cookie、API key、OAuth refresh token、Webhook token 等秘密只在安全边界内以短期句柄或受保护的凭据引用传递。

```text
HTTP/gRPC ingress
  └─ TLS/证书/认证 scheme/版本/扩展解析
       └─ principal + scope + tenant + policy decision（不可变请求上下文）
            └─ 公共命令队列 / RPC
                 └─ 任务核心再次做 task/context/artifact 资源授权
                      └─ provider 仅获最小能力句柄与截止时间
```

- 网关必须先认证，再解析可能暴露资源存在性的 task/config/artifact；核心必须再次校验资源权限，不能信任网关传入的“已授权”布尔值。
- `tenant` 必须与选定 `AgentInterface.tenant` 精确匹配；它是路由/隔离键，不是 principal、scope 或凭据。
- `AUTH_REQUIRED` 只保存挑战引用、需要的权限和恢复关联，不保存长期秘密；授权完成后必须重新做 principal、tenant、context、task 可见性和幂等检查。
- 跨进程日志、指标和 tracing 只允许记录脱敏后的 task/context/message/artifact 标识与审计引用；禁止记录 Authorization 值、完整 webhook URL 中的秘密 query、raw 内容和凭据 payload。

#### 14.10.3 状态、事件与跨进程一致性

任务核心是唯一状态 owner。进程间传递的命令和事件必须带 `task_id`、`context_id`、事件类型、产生时间、来源/版本和可验证的关联信息；`TaskStatusUpdateEvent` 与 `TaskArtifactUpdateEvent` 是对同一任务事实的投影，不是可独立提交的第二状态机。

1. **命令入口**：网关将 `SendMessage`、查询、取消、订阅和推送配置变更归一化为公共命令；命令需有边界内的去重键/请求关联。重复投递不得在核心未裁决前产生两个执行者。
2. **线性化点**：任务状态、Artifact 分块、取消请求和推送配置删除各自必须有明确提交点。状态迁移与终态收口以条件更新或等价原子操作裁决；先赢者写入唯一事实，落败命令保留审计结果。
3. **事件发布**：状态/制品事实提交成功后才能发布事件；事件投递失败不能回滚已提交任务。跨进程消费者必须按 task/artifact 作用域保持生成顺序，重复消费安全，未知事件安全拒绝或隔离。
4. **断线与重启**：连接、订阅或 worker 消失只代表送达/执行者失效，不代表取消。重启后核心从持久任务事实、事件/制品记录和租约恢复；不能依靠内存队列、SSE 缓冲或 webhook 记录重建“已完成”。
5. **终态屏障**：`COMPLETED`、`FAILED`、`CANCELED`、`REJECTED` 写入后拒绝新的任务消息和状态覆盖；迟到事件只能丢弃、标记过期或进入隔离记录，不得复活任务。`INPUT_REQUIRED`/`AUTH_REQUIRED` 是可恢复屏障，不是成功或失败。

协议没有 event id、sequence、cursor、Last-Event-ID、取消 token、deadline 或通用 Idempotency-Key。实现若需要跨进程可靠重放，必须在内部事件/命令信封中补充这些字段，并明确它们与外部 A2A 字段的映射；不得把内部补强字段伪称为 A2A 标准字段。

#### 14.10.4 资源与故障收口

跨进程资源采用“创建者释放，事实 owner 裁决”的原则：网关负责 HTTP/gRPC/SSE socket、DNS 解析、缓存响应体和 webhook 出站连接；核心负责任务、事件、Artifact、订阅事实和租约；provider/worker 只持有受管句柄。正常完成、业务失败、取消/超时、宿主或子进程崩溃四条路径均必须释放：

- 请求体、raw 缓冲、临时文件、Artifact 分块缓存和大响应 body 有大小/时间/数量上限；拒绝或取消时立即清理。
- SSE/gRPC listener、慢消费者缓冲、订阅注册和 webhook 重试 lease 有界；客户端断开只释放送达资源，不改变任务状态。
- provider 取消必须由核心发出并等待可观察的退出/超时结果；网关不得直接杀 provider，worker 崩溃不得直接伪造 `FAILED` 或 `CANCELED`。
- 进程间消息至少区分确认、重试、过期、拒绝和死信；重试必须有上限和退避，不能用无限队列掩盖资源泄漏。
- 凭据句柄、锁、端口、子进程、连接池、订阅和队列租约在四类终态后都要有可查询的释放证据；日志“已关闭”不等于资源现场已清零。

#### 14.10.5 第二轮最终收口判据

只有同时满足以下条件，目标平台的 A2A 接入才能标记为“已接入”，否则保持“协议输入/待核”：

1. 三种标准 binding 对同一组 Message/Task/Artifact 请求给出等价的状态、错误、权限、版本和能力门禁结果；HTTP 方法冲突已显式版本化或兼容化。
2. AgentCard 声明、TLS/HTTP metadata 认证、principal/scope/tenant 授权和 Extended Agent Card 访问在网关与核心之间可追踪且无秘密泄漏。
3. 同一任务只有一个状态 owner；重复消息、重复取消、迟到事件、取消竞态、终态屏障和进程重启均有可验证的线性化/幂等证据。
4. SSE、gRPC stream、Webhook 与轮询都从同一任务事实投影；断线/重复/乱序投递不产生第二次业务执行，关键结果可从 Artifact/Task 读回。
5. 正常、失败、取消/超时、崩溃四类终态均完成 socket、缓冲、临时文件、租约、凭据句柄、provider 进程和队列资源回收检查。

上述判据属于第二轮源码收口后的装配门禁；本仓库当前仍只有规范、文档和构建脚本，未因此获得 A2A 运行时、跨进程实现或测试通过证明。
