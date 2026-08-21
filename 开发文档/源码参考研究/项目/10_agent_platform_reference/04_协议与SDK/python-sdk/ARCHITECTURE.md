# MCP Python SDK 架构

> 首轮架构建档（只读细探后新增）。目标项目：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/04_协议与SDK/python-sdk`。
> 本文描述当前工作树所见的 v2 主线；没有运行安装、构建、服务器或测试命令。

## 1. 项目定位与边界

这是 Model Context Protocol 的官方 Python SDK v2 稳定主线：同一发行体系同时提供 MCP 服务端框架、MCP 客户端、协议线缆类型、stdio/Streamable HTTP/SSE 传输，以及开发 CLI。README 明确说明 v2 支持服务端、客户端和三类标准传输（`README.md:16-35`）；Python 要求为 3.10+（`README.md:37-47`）。v1.x 保留在独立分支，当前仓库的公开 API 兼容性是 2.x 契约（`AGENTS.md:12-24`）。

仓库不是单包平铺结构，而是 uv workspace：根包 `mcp` 依赖独立的 `mcp-types` workspace 包，并把 examples 的 clients/servers/snippets 作为成员（`pyproject.toml:245-252`）。发布时根 wheel 的包目标为 `src/mcp`，运行时依赖以动态版本钩子声明并精确绑定 `mcp-types=={{ version }}`（`pyproject.toml:126-147`、`155-156`）。

## 2. 文本流程图

### 2.1 典型 legacy/双时代请求路径

```text
调用方
  │
  ├─ 高层 Client(server=URL | StdioServerParameters | Server/MCPServer | Transport)
  │     └─ __post_init__ 选择连接器、缓存、扩展与目标传输
  │
  ├─ Client.__aenter__
  │     ├─ URL           → streamable_http_client → StreamableHTTPTransport
  │     ├─ stdio 参数     → stdio_client → 子进程 stdin/stdout
  │     ├─ 自定义 Transport → 进入其读写流
  │     └─ 进程内 Server    → InMemoryTransport 或 DirectDispatcher
  │
  └─ ClientSession / JSONRPCDispatcher
        ├─ typed 请求 → model_dump → 版本/头/现代 _meta stamp
        ├─ request id → _pending 关联 → 写入 transport
        ├─ response/error → 按 (method, version) TypeAdapter 解析
        └─ timeout/cancel/EOF → MCPError、取消帧或 CONNECTION_CLOSED
                                      │
                                      ▼
服务端传输入口
  ├─ stdio_server：stdin 行 JSON → SessionMessage；stdout 行 JSON
  ├─ SseServerTransport：GET 建 SSE 会话 + POST 消息端点
  └─ StreamableHTTPSessionManager（Starlette ASGI）
        ├─ body limit（默认 4 MiB）
        ├─ legacy stateful：Mcp-Session-Id → transport/session owner
        ├─ legacy stateless：每请求新 transport
        └─ 非握手版本头 → modern 单次请求入口
                                      │
                                      ▼
JSONRPCDispatcher / ServerRunner
  ├─ initialize inline（防握手管道死锁）
  ├─ request → 版本方法表校验 → params model_validate → handler
  ├─ notification → cancelled/progress/订阅等专门分发
  ├─ response/error → 唤醒对应 pending request
  └─ EOF → fan-out 所有 pending 的 CONNECTION_CLOSED
                                      │
                                      ▼
低层 Server
  ├─ _request_handlers：method → HandlerEntry(params_type, handler)
  ├─ middleware：OpenTelemetry → requestState → 用户 middleware
  ├─ capability：由已注册 handler 推导
  └─ runner 序列化：cache hint、版本 sieve、现代 resultType/serverInfo stamp
                                      │
                                      ▼
高层 MCPServer
  ├─ ToolManager：@server.tool → Tool → 动态参数/输出 schema
  ├─ ResourceManager：资源函数、模板、读取与安全边界
  ├─ PromptManager：prompt 注册与参数渲染
  ├─ Extension：扩展能力、方法、result claim、拦截器
  └─ handler 结果：文本/content block/structured_content/InputRequiredResult
```

### 2.2 2026-07-28 modern 时代路径

```text
Client(mode="auto" 或 "2026-07-28")
  → server/discover 探测（失败可回落 initialize）或直接 adopt
  → 每个请求 params._meta 注入 protocolVersion/clientInfo/clientCapabilities
  → MCP-Protocol-Version + MCP-Method + MCP-Name 头
  → Streamable HTTP 服务端按头路由 modern
  → 每请求独立 Connection / Dispatcher（无 legacy session handshake）
  → resultType 解析与服务器 serverInfo _meta 盖章
  → 取消通过关闭该 POST 的请求级 CancelScope，不发送 legacy cancelled 通知
```

版本注册表的事实来源是 `src/mcp-types/mcp_types/version.py:24-60`：当前已知版本为 `2024-11-05`、`2025-03-26`、`2025-06-18`、`2025-11-25`、`2026-07-28`；前四个属于 handshake，最后一个属于 modern。`methods.py` 以 `(method, version)` 为键维护 client/server requests、notifications、results 的版本表（`src/mcp-types/mcp_types/methods.py:55-126`、`157-180`、`231-250`）。未知版本不按字符串排序，而由枚举表保守处理（`version.py:63-74`）。

## 3. 分层与职责

### 3.1 协议类型层：`src/mcp-types/mcp_types/`

- `__init__.py`、`_types.py`、`jsonrpc.py`、`methods.py`、`version.py`：公共 wire model、JSON-RPC model、MCP 方法/版本映射、序列化/解析/校验接口。
- `_v2025_11_25/` 与 `_v2026_07_28/`：按协议时代生成/维护的表面类型与版本校验器；`methods.py` 负责把版本无关的用户模型映射到版本相关表面。
- 基础技术是 Pydantic v2；`TypeAdapter` 用于联合结果、按版本解析和输出 schema 校验。
- 根 `mcp` 包通过 `from mcp_types import ...` 暴露常用协议类型，并将 `mcp.types` 绑定为兼容别名（`src/mcp/__init__.py:1-73`）。

### 3.2 共享协议内核：`src/mcp/shared/`

- `jsonrpc_dispatcher.py`：双向 JSON-RPC 会话状态机，维护 request id/pending、入站分发、取消、进度、EOF 收尾和异常到 wire error 的边界。
- `dispatcher.py`、`direct_dispatcher.py`：抽象 Dispatcher 与进程内 modern 直连通道。
- `message.py`、`_context_streams.py`、`_stream_protocols.py`：SessionMessage、上下文读写流及传输元数据。
- `inbound.py`、`auth.py`、`auth_utils.py`、`transport_context.py`：现代头/信封、认证辅助和传输上下文。
- `exceptions.py`：`MCPError`、`MCPDeprecationWarning`、URL elicitation 等 SDK 错误边界。
- `uri_template.py`、`subscriptions.py`、`tool_name_validation.py`、`path_security.py`：协议公共能力与安全/命名校验。

### 3.3 服务端层：`src/mcp/server/`

- `lowlevel/server.py`：低层 `Server`。构造器将规范方法与已传入 handler 装入 `_request_handlers`，`add_request_handler` 在调用 handler 前绑定 params model 校验；`initialize` 保留给 runner（`server/lowlevel/server.py:91-104`、`446-495`）。
- `runner.py`、`connection.py`、`session.py`、`context.py`、`request_state.py`：初始化门、版本路由、连接上下文、生命周期状态和请求状态密封。
- `mcpserver/server.py`：高层 `MCPServer`，组合 Tool/Resource/Prompt 管理器，创建低层 Server，并提供 `run("stdio"|"sse"|"streamable-http")`（`server/mcpserver/server.py:147-234`、`356-400`）。
- `mcpserver/tools/`：装饰器/工具注册、参数模型与输出模型生成；`utilities/func_metadata.py` 根据 Python 签名和注解动态生成 Pydantic schema。
- `mcpserver/resources/`、`mcpserver/prompts/`、`resolve.py`：资源/模板、提示词和 2026 多轮解析参数。
- `streamable_http.py`、`streamable_http_manager.py`、`_streamable_http_modern.py`：Streamable HTTP server transport、session manager、SSE/JSON 响应、事件恢复和 modern 路径。
- `sse.py`、`stdio.py`：历史 SSE 与 stdio server transport；stdio 在必要时夺取标准 fd，阻止 handler/子进程污染 stdout wire（`server/stdio.py:34-43`、`161-217`）。
- `transport_security.py`：Host/Origin/DNS rebinding 保护；`auth/`：Bearer/OAuth 授权服务器路由、token verifier、认证上下文。
- `caching.py`、`subscriptions.py`、`extension.py`、`apps.py`：结果缓存提示、订阅总线、扩展机制和应用装配。

### 3.4 客户端层：`src/mcp/client/`

- `client.py` 的 `Client` 是统一高层入口：URL、stdio 参数、自定义 Transport、低层 Server/MCPServer 都在 `__post_init__` 选择 connector（`client/client.py:261-403`）。
- `session.py` 的 `ClientSession` 负责 typed MCP 请求、握手/adopt、头与 `_meta` stamp、结果 TypeAdapter、回调、扩展 claims、订阅和 output schema 校验。
- `streamable_http.py`：httpx2 客户端、POST JSON/SSE 响应、GET SSE、session id、Last-Event-ID 恢复、请求取消翻译（`client/streamable_http.py:89-131`、`198-241`）。
- `stdio.py`：安全环境继承、跨平台子进程启动、newline-delimited JSON、flush/close/wait/SIGTERM/SIGKILL 有界回收（`client/stdio.py:1-8`、`93-131`、`184-215`）。
- `sse.py`：旧 SSE endpoint 发现、事件读取和 POST writer（`client/sse.py:30-61`、`65-161`）。
- `_memory.py`、`_transport.py`、`_probe.py`：进程内流、传输协议和 modern discover 探测。
- `caching.py`、`subscriptions.py`、`auth/`、`extension.py`、`session_group.py`：客户端缓存、订阅、OAuth 扩展和会话分组。

### 3.5 CLI、文档与示例层

- `src/mcp/cli/`：入口 `mcp = "mcp.cli:app [cli]"`（`pyproject.toml:27-32`）；`mcp dev` 通过 Inspector/uv 运行，`mcp run` 导入 `MCPServer` 并运行，`mcp install` 修改 Claude Desktop 配置，另有 `mcp version`（`src/mcp/cli/cli.py:34-85`、`209-357`、`360-486`）。
- `docs_src/`：文档中的可运行 Python 示例；文档测试通过 `tests/docs_src/` 执行，形成“文档即测试”链。
- `examples/stories/`：按能力故事组织 server/client/lowlevel 例子，覆盖 tools、resources、prompts、streaming、subscriptions、pagination、OAuth、middleware、lifespan、reconnect、stateless 等。
- `examples/servers/`、`examples/clients/`、`examples/snippets/`：可独立安装/运行的服务、客户端和片段 workspace 包。
- `scripts/`：`scripts/test` 是完整覆盖率入口；`scripts/docs/` 负责文档配置、API 页面和翻译构建；`gen_surface_types.py`、`update_readme_snippets.py` 等负责生成/同步。

## 4. 数据流与状态所有权

### 4.1 Legacy typed JSON-RPC

1. 调用方构造 `ClientRequest` 或调用高层方法。
2. `ClientSession` 依据已协商版本，从 `mcp-types.methods` 选择版本 surface model，序列化为 JSON-RPC。
3. `JSONRPCDispatcher` 分配/关联 request id，将 `SessionMessage` 写入传输流；响应沿相同 id 唤醒 pending 请求。
4. Server transport 将 HTTP/stdio/SSE 字节或行转换为 `SessionMessage`；Dispatcher 解析 JSON-RPC，ServerRunner 执行版本方法门、params 校验和 handler。
5. handler 返回 typed result；Runner 应用 cache hints、版本字段 sieve、modern `resultType`/`serverInfo` stamp，再序列化回传。
6. 客户端 `ClientSession` 使用结果 TypeAdapter、输出 JSON Schema 和缓存策略完成最终 `CallToolResult`/资源/提示词结果。

### 4.2 工具调用数据流

```text
Python 函数签名/注解/docstring
  → @server.tool()
  → ToolManager / Tool.from_function
  → 参数模型 + inputSchema / outputSchema
  → tools/list
  → ClientSession.call_tool(name, arguments)
  → pre_parse_json（兼容字符串化 JSON）
  → 参数 model_validate
  → handler（同步函数必要时 anyio.to_thread）
  → convert_result
       ├─ 文本/内容块 → content
       ├─ BaseModel/TypedDict/泛型 → structured_content
       └─ 异常 → MCPError 或 is_error ToolResult
```

### 4.3 Streamable HTTP 状态

状态化 manager 持有 `session_id → StreamableHTTPServerTransport`，同时持有创建会话的认证上下文；后续请求必须携带同一凭证，否则按 404/session not found 处理。新会话在创建锁内生成 `uuid4().hex`；`stateless=True` 不保存 session/event state，每个请求建立独立 transport。可选 `EventStore` 保存 SSE event id，使客户端以 `Last-Event-ID` 重连恢复。body limit middleware 在解析和建会话前执行，默认 4 MiB（`server/streamable_http_manager.py:37-103`、`251-303`）。

## 5. 关键路径索引

| 场景 | 入口 | 关键路径 |
|---|---|---|
| 高层服务端 | `MCPServer(...)` | `mcp/server/mcpserver/server.py` → `lowlevel/server.py` → `runner.py` |
| 低层服务端 | `Server(...)` | `server/lowlevel/server.py` → `runner.py` |
| URL 客户端 | `Client("http://...")` | `client/client.py` → `client/streamable_http.py` → `client/session.py` |
| stdio 客户端 | `Client(StdioServerParameters(...))` | `client/stdio.py` → `JSONRPCDispatcher` → `ClientSession` |
| 进程内客户端 | `Client(server)` | `client/_memory.py`（legacy）或 `shared/direct_dispatcher.py`（modern） |
| Streamable HTTP 服务 | `server.streamable_http_app()` / `MCPServer.run(...)` | `server/streamable_http_manager.py` → `server/streamable_http.py` |
| 旧 SSE | `sse_client` / `SseServerTransport` | `client/sse.py` ↔ `server/sse.py` |
| 工具注册 | `@mcp.tool()` | `mcpserver/tools/base.py` → `func_metadata.py` → `ToolManager` |
| 资源/提示词 | `@mcp.resource()` / `@mcp.prompt()` | `mcpserver/resources/` / `mcpserver/prompts/` |
| 认证 | `AuthSettings` + provider/verifier | `server/auth/` + bearer middleware + routes |
| CLI | `mcp dev/run/install/version` | `src/mcp/cli/cli.py` → uv/Inspector/Claude config |
| 协议表面 | typed request/result | `src/mcp-types/mcp_types/methods.py` + `_v2025_11_25`/`_v2026_07_28` |

## 6. API / CLI / SDK 使用面

### 6.1 Python SDK 公开面

根 `src/mcp/__init__.py` 的 `__all__` 明确公开 `Client`、`ClientSession`、`ClientSessionGroup`、`ServerSession`、`MCPError`、`MCPDeprecationWarning`、`stdio_client`、`stdio_server`、`StdioServerParameters`、`UriTemplate` 以及常用协议类型（`__init__.py:61-145`）。

服务端高层典型用法：

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

mcp.run("stdio")
```

客户端典型用法：

```python
from mcp import Client

async with Client("http://localhost:8000/mcp") as client:
    result = await client.call_tool("add", {"a": 1, "b": 2})
```

以上两条路径与 README 的示例一致（`README.md:49-83`、`87-112`）。低层使用者可以直接构造 `Server(on_list_tools=..., on_call_tool=...)`，再用 stdio/SSE/Streamable HTTP transport 驱动。

### 6.2 CLI

- `uv run mcp dev server.py`：使用 Inspector 调试；可附 `server.py:object`、`--with-editable`、`--with package`。
- `uv run mcp run server.py --transport streamable-http`：导入 `MCPServer` 对象并直接运行；transport 可为 `stdio`、`sse`、`streamable-http`。
- `uv run mcp install server.py --name ... --with ... --env-var KEY=VALUE --env-file .env`：写入 Claude Desktop 配置。
- `uv run mcp version`：显示已安装版本。

`mcp dev` 会经 `uv run --with ... mcp run` 组装依赖并启动 Inspector；`mcp install` 通过 `mcp.cli.claude` 维护主机配置。CLI 依赖位于 `[project.optional-dependencies].cli`。

## 7. 技术栈与运行约束

| 类别 | 当前实现 |
|---|---|
| 语言/版本 | Python >=3.10，CI/分类器覆盖 3.10–3.14 |
| 包管理/构建 | uv workspace、Hatchling、uv-dynamic-versioning、锁文件 `uv.lock` |
| 数据模型 | Pydantic >=2.12、Pydantic TypeAdapter、生成的 `mcp-types` surface types |
| 异步/并发 | anyio task group、CancelScope、memory streams；支持 asyncio/trio 运行模型 |
| HTTP 服务端 | Starlette ASGI、sse-starlette、可选 uvicorn |
| HTTP 客户端 | `httpx2` 与项目自有 MCP HTTP client factory |
| 协议 | JSON-RPC 2.0 + MCP 版本 surface；legacy handshake 与 2026 modern envelope 双时代 |
| 可观测性 | OpenTelemetry API/SDK；服务端默认挂 no-op middleware，配置 exporter 后输出 span |
| CLI | Typer、可选 python-dotenv、Node npx Inspector |
| 校验/质量 | pytest、pytest-xdist、coverage、strict-no-cover、ruff、pyright、markdown lint |
| 发布 | PyPI workflow；文档由 Zensical/mkdocstrings 系列工具构建；conformance workflow 单独执行 |

运行和修改纪律：只用 `uv`，命令使用 `uv run --frozen` 以避免意外改写 `uv.lock`（`AGENTS.md:26-44`）；代码要求类型标注、公共 API docstring、文本 IO 显式 encoding、避免宽泛 `except Exception`（`AGENTS.md:46-66`、`158-167`）。

## 8. 测试与验证结构

### 8.1 测试目录

当前工作树统计（仅文件系统读取）：`src` 约 130 个 Python 文件；`tests` 约 273 个 Python 文件；`examples` 约 225 个 Python 文件；`docs_src` 约 195 个 Python 文件。测试顶层按功能分为：

- `tests/client/`：Client/ClientSession、缓存、订阅、所有客户端传输、OAuth 扩展。
- `tests/server/`：低层 server、MCPServer、生命周期、请求状态、auth、Streamable HTTP/SSE/stdio、安全、资源/提示词/工具。
- `tests/shared/`：dispatcher、上下文流、auth、URI template、路径/工具名安全、OTel。
- `tests/interaction/`：跨传输、端到端协议交互、legacy/modern、auth、MCPServer 资源/工具/提示词/扩展；`tests/interaction/README.md` 是该套件的说明入口。
- `tests/types/`：wire frame、版本、方法表、协议 parity、请求 name 参数。
- `tests/transport/`、`tests/issues/`、`tests/examples/`、`tests/docs_src/`、`tests/docs/`、`tests/cli/`：平台 transport、回归 issue、故事示例、可执行文档、文档构建和 CLI。

### 8.2 门禁与覆盖率

`AGENTS.md:66-96` 规定测试用 anyio、不新增 `Test` 前缀类、端到端优先进程内 `Client(server)`，并要求新规范特性有 conformance suite 对应测试。覆盖率要求 branch=True、100%（`AGENTS.md:98-125`；`pyproject.toml:298-323`）。

完整入口 `scripts/test`：

```text
coverage erase
→ PYTHONWARNDEFAULTENCODING=1 uv run --frozen coverage run -m pytest -n auto
→ coverage combine
→ coverage report
→ UV_FROZEN=1 uv run --frozen strict-no-cover
```

`pyproject.toml` 的 pytest 配置启用 anyio、examples 插件、严格 warning 过滤和 docs script 的 pythonpath（`pyproject.toml:254-285`）。代码质量命令为 `uv run --frozen ruff format .`、`ruff check . --fix`、`pyright`；本次任务按要求未执行这些命令。

## 9. 安全、错误与资源边界

- HTTP transport 默认提供 DNS rebinding 防护；本机服务重点校验 Host/Origin，非法请求在进入 handler 前拒绝。
- Streamable HTTP 请求 body 默认 4 MiB；会话 ID 只允许可见 ASCII；session owner 与认证上下文绑定。
- 工具名遵守 MCP 工具名规则；参数校验发生在 handler 之前；服务端错误不应泄漏 traceback。
- stdio 客户端只继承受控环境变量，并在取消/退出时有界地关闭 stdin、等待、终止进程树；stdio server 保护 fd 0/1，避免业务输出污染协议。
- Dispatcher 将 `MCPError`、Pydantic `ValidationError`、handler 异常归一化为 JSON-RPC error 或工具级 `is_error` 结果；EOF 会唤醒全部 pending，避免悬挂。
- 典型 JSON-RPC/MCP 错误码包括 `PARSE_ERROR`、`INVALID_REQUEST`、`METHOD_NOT_FOUND`、`INVALID_PARAMS`、`INTERNAL_ERROR`、`CONNECTION_CLOSED`、`REQUEST_TIMEOUT`、`UNSUPPORTED_PROTOCOL_VERSION`、`URL_ELICITATION_REQUIRED`。
- Server middleware 顺序是 OpenTelemetry、requestState boundary、用户 middleware；现代 requestState 带 audience 约束，防止跨服务重放。

## 10. 未确认项与风险

以下项目在当前核对没有运行时验证，不能仅凭静态阅读宣称已闭环：

1. **目标代码地图未建立**：对目标目录的 codegraph 查询返回“未发现 `.codegraph/`”；专属 `system_engineering_toolkit` 当前自身根目录是系统工程平台，无法为该外部仓库提供同仓库地图。本文因此以本地源码/目录/已有细探文档为依据，没有采用其他仓库地图结果。
2. **MCP 开工上下文根目录不匹配**：专属 MCP 返回的项目根是 `/Users/hekunhua/Documents/Agent/PHP/系统工程平台`，不是本目标目录，因而不能为外部目标仓库建立受控 worktree/文件账本。架构文档仍只写入目标根的 `ARCHITECTURE.md`；该隔离差异需后续将专属 MCP 配置到目标仓库或提供跨仓库只读模式。
3. **未跑测试/覆盖率/conformance**：当前核对没有安装、启动、构建或执行测试；测试数量、100% coverage、跨 Python 3.10–3.14、Windows/POSIX 行为均只是配置和静态结构事实。
4. **现代协议仍在演进**：当前版本表已含 2026-07-28，但 Tasks 等扩展在 methods surface 中存在按版本缺失/延后情况；后续扩展应同时核对规范、wire models、methods map、runner、client parser 与 conformance。
5. **CLI 外部依赖边界**：`mcp dev` 需要 Node/npx Inspector，`mcp install` 依赖 Claude Desktop 配置；当前核对未探测宿主工具是否存在。
6. **可选依赖/平台路径**：uv dynamic dependencies、Windows fd/process 实现、OAuth provider、OTel exporter、事件存储后端等未做实际启动探针；第三方库版本与运行时兼容性需按锁文件和 CI 重新验证。
7. **根目录细探文档的时效性**：`细探-MCP官方SDK.md` 标注了细粒度探索和若干未实现项，但它是已有调研文档，不替代当前源码、测试或规范；当其结论与源码/版本表不一致时以源码为准。

## 11. 当前核对变更与证据边界

- 允许修改范围：仅目标项目根目录。
- 实际修改：新增本文件 `ARCHITECTURE.md`；未修改源码、依赖、测试、配置、锁文件或 Git 提交。
- 未删除或改写既有 `细探-MCP官方SDK.md`。
- 代码地图查询：专属 MCP `system_engineering_toolkit` 的 `codegraph_explore` 已调用，但其地图指向系统工程平台；目标仓库未建立 `.codegraph/`，所以未使用该错误根下的任何源码/地图证据。

## 12. 旧细探吸收与裁决

本节把 `细探-MCP官方SDK.md` 中仍能由当前工作树源码支撑、且对理解架构有用的事实收口到本文件。旧细探保留为历史研究材料，但不再作为第二个权威架构文档；后续架构事实只维护本文件，并以当前源码、测试和锁定版本为准。

### 12.1 已吸收的协议与运行时事实

1. **双时代不是简单的版本号兼容。** `HANDSHAKE_PROTOCOL_VERSIONS` 走 `initialize`/`notifications/initialized` 状态提交；`MODERN_PROTOCOL_VERSIONS` 走每请求 `_meta` 信封和请求头，不建立 legacy 会话握手。客户端 `discover()` 首次探测失败且错误码为 `UNSUPPORTED_PROTOCOL_VERSION` 时，只按服务端 `supported` 与本地 modern 版本求交集后重试一次；其他错误交由上层决定是否回落 `initialize`（`src/mcp/client/session.py:764-800`、`src/mcp/server/runner.py:420-444`）。因此第 2 节的 modern 路径不能改写成“所有版本都先握手”。
2. **时代选择发生在传输/入口边界。** 服务端存在 `serve_dual_era_loop` 与 `serve_one` 两类驱动；Streamable HTTP 先按 `Mcp-Protocol-Version` 等头路由 modern，modern 请求是单次交换、每请求独立连接上下文，而 stateful legacy 请求由 `Mcp-Session-Id` 关联已有 transport。旧细探中的“首个请求决定连接时代、跨时代请求拒绝”作为架构约束保留；具体拒绝码仍以 `runner.py`/`inbound.py` 当前实现为准。
3. **Dispatcher 是传输之上的唯一并发内核。** `JSONRPCDispatcher` 对出站请求执行 id 分配、`_pending` 等待、超时/调用者取消处理和关闭清理；入站 request 默认生成独立任务，`inline_methods`（握手时为 `initialize`）才暂停读循环等待结果（`src/mcp/shared/jsonrpc_dispatcher.py:476-606`）。EOF 或读流关闭会把全部 pending 唤醒为 `CONNECTION_CLOSED`，随后取消 in-flight handler，避免调用方永久悬挂（同文件 `510-524`）。
4. **取消是分层语义，不等同于“立刻回一个错误”。** 对端 `notifications/cancelled` 先按 request id 找到 in-flight；`peer_cancel_mode="interrupt"` 取消 handler 作用域，`"signal"` 只设置 `cancel_requested` 让 handler 自行收尾；两种模式下该请求结果都不再写回（`src/mcp/shared/jsonrpc_dispatcher.py:608-628`，类/字段说明同文件 `81-85`）。本地超时或调用者取消在已开始写出请求时会以有界 5 秒礼让取消帧，再传播异常（同文件 `420-436`）。现代 Streamable HTTP 把该语义翻译为关闭对应 POST 的 request-level `CancelScope`，而 2025 时代 transport 为结束 SSE 请求会合成 `REQUEST_CANCELLED` 响应（`src/mcp/client/streamable_http.py:591-599`、`src/mcp/server/streamable_http.py:431-443`）。
5. **服务端响应有单一的出站整形边界。** `ServerRunner._serialize` 统一处理 cache hints、按 `(method, version)` 的 result surface 校验/裁剪、modern 缺省 `resultType="complete"` 补全和 `_meta.serverInfo` 盖章；不合法的规范结果转为不泄漏细节的 `INTERNAL_ERROR`（`src/mcp/server/runner.py:341-418`）。这比只描述“handler 返回 typed result”更准确，已补入第 4 节数据流的所有权边界。

### 12.2 已吸收的传输、安全与高层框架事实

1. **Streamable HTTP 的状态所有权是 session manager。** 有状态请求把 `session_id → StreamableHTTPServerTransport` 和创建者授权上下文一起保存；凭证不匹配和未知/过期 session 都按“Session not found”返回 404，创建在锁内生成 `uuid4().hex`；可选 idle deadline 活动续期并回收。无状态模式不保存 session/event state，每请求创建并终止 transport（`src/mcp/server/streamable_http_manager.py:251-371`）。
2. **请求体上限先于解析和建会话。** `RequestBodyLimitMiddleware` 同时检查声明的 `Content-Length` 和实际分块累计大小，超限返回 413（`src/mcp/server/streamable_http_manager.py:374-415`）；第 9 节的 4 MiB 结论因此是入口约束，不是 handler 自己负责的业务校验。
3. **SSE 恢复依赖可插拔 EventStore。** 服务端为事件生成 id，并用 priming event 保证恢复游标先于该 stream 的消息；客户端携带 `Last-Event-ID` 重连，受最大次数和 `retry` 退避约束（`src/mcp/server/streamable_http.py:323-339`、`src/mcp/client/streamable_http.py:482-534`）。没有配置 `EventStore` 时只能使用普通 SSE 流，不能把“支持 SSE”写成“必然支持恢复”。
4. **安全边界包括协议头和多轮状态。** `TransportSecurityMiddleware` 可校验 POST 的 `Content-Type`、请求 `Host` 与 `Origin`，失败分别为 400/421/403（`src/mcp/server/transport_security.py:91-116`）。2026 `requestState` 由 `RequestStateBoundary` 在出站密封、入站验签，并可绑定 TTL、请求、audience 和认证 principal；handler 只看到已验证明文（`src/mcp/server/request_state.py:1-6`、`94-109`）。因此第 9 节将 DNS rebinding 与 requestState 作为不同层次的防护保留。
5. **高层工具与 prompt 均是注册表驱动的协议适配器。** `Tool.from_function` 先校验名字、剔除 Context/Resolve 参数，再由 `func_metadata` 生成参数模型和 JSON Schema；同步函数通过 `anyio.to_thread` 调用，输出按 output schema 转换为 `CallToolResult`/structured content，`MCPError` 保持为协议错误，其他执行异常包装为工具级错误（`src/mcp/server/mcpserver/tools/base.py:57-121`、`123-180`；`src/mcp/server/mcpserver/utilities/func_metadata.py:91-127`、`129-160`）。`Prompt.render` 将字符串、content block、`Message` 或字典归一化成消息列表，并原样传递 `InputRequiredResult`，所以 prompt 是协议消息资源，不是 SDK 内部的字符串模板引擎（`src/mcp/server/mcpserver/prompts/base.py:107-115`、`158-213`）。
6. **注册信息推导能力清单，动态 schema 在注册期暴露风险。** 工具名规则、签名/类型注解到参数与输出 schema 的推导、`StrictJsonSchema` 对不可序列化类型把 schema warning 升级为异常，均属于注册边界行为（`src/mcp/server/mcpserver/utilities/func_metadata.py:55-63`、`395-494`）。这使第 5 节“能力由已注册 handler 推导”和“函数签名自动生成契约”的结论有源码依据。

### 12.3 对平台底座的吸收裁决

以下只吸收可迁移的边界思想，不把官方 SDK 的第三方依赖或 JSON-RPC 协议误写成目标平台必须采用的实现：

| 旧细探建议 | 裁决 | 归档位置/依据 |
|---|---|---|
| 以 JSON-RPC/MCP 替换平台自定义能力网关 | **不吸收**：两个项目定位不同；平台现有标准库 HTTP 网关不因参考 SDK 而引入 MCP 线缆 | 旧细探第 5 节；本项目只记录 SDK 自身协议边界 |
| 由注册表推导公开能力清单 | **吸收为设计借鉴**：减少重复声明，并在重复注册处失败/告警 | `src/mcp/server/lowlevel/server.py` 注册表与能力推导；本文件第 3.3 节 |
| 入参先做字符串化 JSON 兼容预解析，再做模型校验 | **吸收为设计借鉴**：兼容客户端传入的 JSON 字符串，但不放宽最终类型校验 | `src/mcp/server/mcpserver/utilities/func_metadata.py:91-127` |
| 限体、Host/Origin、会话归属、取消分层 | **吸收为边界模式**：先于业务 handler 执行；平台是否实现由其自身安全契约决定 | 本文件第 12.2 节及 `streamable_http_manager.py`、`transport_security.py` |
| 直接引入 anyio/starlette/httpx/pydantic 全套 | **不吸收**：这是官方 SDK 的运行依赖，不是平台标准库约束下的可直接依赖 | `pyproject.toml`、`AGENTS.md`；旧细探第 7 节 |

### 12.4 未吸收、保留为待核的旧细探内容

- 旧细探中的 `src ~38k`、`tests ~84k`、单文件行数等规模数字没有并入架构事实；它们是随 checkout 漂移的统计，不是稳定契约。
- 旧细探列出的 Inspector、规范仓库、SEP 编号、跨 SDK 看板和 issue 只作为旁路线索，不在当前核对当作当前源码实现证据；正式判断仍需逐项对规范、`mcp-types.methods`、runner、client parser 和 conformance 复核。
- “Tasks、DPoP、jwt-bearer workload identity 未实现”等负面结论未直接升级为当前架构结论；未实现判断必须以当前方法表、导出面、运行路径和 conformance 结果共同证明。当前核对没有运行 conformance，也没有对外部规范仓库做版本复核。
- 旧细探中关于 `mcp dev`、`mcp install` 是否能调用宿主 Inspector/Claude Desktop 的运行时结论未吸收；第 10 节仍诚实标为未探测。
- 旧细探与当前源码不一致之处，以当前源码为准；例如传输安全 middleware 本身为兼容性默认关闭，但应用装配可传入安全设置，不能笼统写成“任何构造路径都自动开启”（`transport_security.py:39-41`）。

## 13. 唯一架构文档声明

- 权威架构文档只有目标根的 `ARCHITECTURE.md`。
- `细探-MCP官方SDK.md` 已完整读取并保留，不删除、不改写；其已吸收内容见本文件第 12 节，未吸收内容及原因也在第 12.4 节明确记录。
- 当前核对仍只修改 `ARCHITECTURE.md`；未修改源码、配置、依赖、锁文件、测试或旧细探。

## 14. 后续：MCP 底座映射与薄网关裁决（2026-07-28 modern 时代）

本节不是把 MCP SDK 当作平台实现方案，而是把源码已经证明的协议边界，逐项映射到平台的公共契约、运行核心和 HTTP 能力网关。平台的权威执行链仍是：

```text
调用方
  → 公共契约（能力 id / 参数 / 结果 / 错误 / 超时 / 取消 / 资源）
  → 唯一能力调用器与注册表
  → 运行核心监督（授权、预算、超时、取消、证据、资源回收）
  → 唯一 provider / 模块公开入口
  → 真实执行与权威状态写入
```

如需 MCP，只允许在边界加一层薄适配：

```text
MCP Client / Host
  ↔ MCP 线缆（JSON-RPC、legacy 或 modern、stdio/SSE/Streamable HTTP）
  ↔ MCP 薄网关（协议翻译、会话/传输、安全、限体、结果整形）
  ↔ 公共契约与唯一能力调用器
  ↔ 平台唯一执行权威
```

MCP 的 `tools/list`、`tools/call`、JSON-RPC request id、session id、SSE event id、protocol version 和 `resultType` 都是**对接面元数据**，不是平台新的能力 id、状态库、任务调度器、授权根或事实写入 owner。MCP 网关不能直接调用 provider、旁路写权威状态、重新实现超时/取消/发布/证据，亦不能因某个 MCP server 暴露了 tool 就自动获得平台执行权。

### 14.1 双时代协议 → 公共契约版本适配，不复制平台版本权威

| SDK 事实 | 对公共契约的映射 | 薄网关职责 | 明确不归 MCP |
|---|---|---|---|
| `2024-11-05`、`2025-03-26`、`2025-06-18`、`2025-11-25` 属 handshake；`2026-07-28` 属 modern（`src/mcp-types/mcp_types/version.py`、`methods.py`）。 | 公共契约继续以平台能力契约版本/兼容范围为准；MCP 版本只记录为 transport adapter 的 `协议版本`。 | legacy 进入 `initialize`/`notifications/initialized`；modern 走 `_meta` 与 MCP 头；把两者转换为同一个内部调用请求。 | 不让 MCP protocol version 决定能力契约版本、发布版本、状态迁移或回滚指针。 |
| legacy 有会话握手；modern 是每请求独立 exchange，无握手、无跨请求 server request。 | 内部命令必须携带平台已有的调用者、能力 id、契约指纹、请求/幂等标识和资源预算；这些不能由协议时代隐式生成。 | 按 `Mcp-Protocol-Version`/请求信封选择 parser；拒绝跨时代混用，返回稳定的协议适配错误。 | 不用 modern 的“无 session”假设替代平台授权会话、任务租约或审计关联。 |
| 当前 SDK 通过 `(method, version)` 表面映射与 TypeAdapter 解析。 | 平台公共契约应有一次“外部请求 → 内部契约”映射，内部契约是唯一事实源；旧 MCP 方法/字段只能作为输入别名。 | 版本化解析、字段裁剪、默认值与错误转换集中在适配层；兼容别名只放这一处。 | 不在每个 tool、消费者或模块中各维护 MCP 字段/英文别名映射。 |

**落地约束：** modern 与 legacy 都必须先得到同一个已验证的内部调用对象，再进入平台能力调用器；协议协商成功不等于授权成功，`initialize`/`discover` 成功不等于能力执行成功。能力契约版本兼容失败、授权失败、资源预算不足和 provider 不可用必须由公共契约/运行核心决定，不由 MCP server 自定义一套判定。

### 14.2 JSON-RPC 分发 → 公共契约前的线缆内核，不能成为业务路由器

`JSONRPCDispatcher`（`src/mcp/shared/jsonrpc_dispatcher.py`）的可迁移价值是边界位置而不是 JSON-RPC 本身：

1. **id 关联**：维护 outbound request id 与 pending 结果，响应/error 按 id 唤醒等待者；映射为公共契约的 `请求 id/调用 id` 关联，但不能替代平台的幂等键、事务 id 或证据 id。
2. **入站隔离**：非 `inline_methods` 的 request 进入独立任务；`initialize` 可 inline 以避免握手死锁。映射为网关的“协议读循环与业务执行解耦”；真正的并发额度、任务租约和资源监督仍由运行核心统一提供。
3. **唯一异常到线缆边界**：`MCPError` 保留 `ErrorData`，Pydantic `ValidationError` 转 `INVALID_PARAMS`，其他异常在 modern HTTP 入口泛化为 `INTERNAL_ERROR`。映射为公共契约的稳定错误码/消息/可重试/来源；原始异常只进服务端诊断与证据，不穿透 MCP 响应。
4. **notification 与 progress**：notification 无响应；progress 只能更新调用观测，不改变权威结果。网关必须区分“无响应协议事件”“业务结果”“进度事件”，不能把进度当成功或状态提交。
5. **EOF/关闭**：SDK 在 EOF 时 fan-out 全部 pending 为 `CONNECTION_CLOSED`，并取消 in-flight handler。平台映射为连接级失败 + 统一资源回收；不能把断线误报成能力执行成功，也不能留下 pending、线程、进程、租约或临时目录。

因此网关的 JSON-RPC 路由表只应做 `method → 公共契约操作` 的协议映射，例如 `tools/list → 能力搜索/公开契约投影`、`tools/call → 能力调用提交`。它不应增加第二套 `method → 函数` 业务注册表；真正的能力查找、授权、参数契约校验、provider 选择和执行必须经过平台唯一注册表/调用器。

### 14.3 并发、取消、超时、EOF → 运行核心监督契约

| SDK 行为 | 平台公共契约字段/语义 | 网关必须做 | 网关禁止做 |
|---|---|---|---|
| 出站 timeout 后有界写 courtesy `notifications/cancelled`（5 秒）；关闭写有更短上限。 | `超时预算`、`取消原因`、`可重试`、`调用 id`、`资源释放状态`。 | 把 HTTP 客户端断开/网关 deadline 翻译成一次公共取消命令；记录“调用方视角已取消/超时”，等待底层收尾并回收。 | 只 `future.cancel()` 就声称真实执行已停止；或在 MCP 层另建一套超时线程池。 |
| 对端取消支持 `peer_cancel_mode=interrupt|signal`；被取消 request 永不回复，结果丢弃。 | `取消策略` 必须由平台能力契约声明：可中断、协作收尾或不可取消；最终状态由运行核心确认。 | `interrupt` 只适用于底层明确支持的 CancelScope/进程组；`signal` 转为协作取消标记，并禁止把晚到结果写回调用面。 | 把“收到 cancelled”当作已经杀死真实进程/事务；或把晚到结果覆盖权威状态。 |
| EOF 会唤醒 pending 并取消 in-flight。 | 统一 `CONNECTION_CLOSED`/`网关断开` 与内部 `执行未确认/执行失败` 分离。 | 关闭传输、排空队列、释放 session/租约/句柄；必要时由运行核心查询/恢复真实执行状态。 | 把连接恢复、SSE 重连或 MCP session 恢复当作业务执行重试。 |

**取消的单一权威：** MCP 只表达协议侧意图（取消哪个 request）；运行核心才有权决定如何中止任务、回收进程组/连接/锁、写入取消证据以及是否可安全重试。MCP 网关不能直接承诺“取消已完成”，只能返回公共契约定义的 `已请求取消/已确认取消/执行状态未知` 等事实。

### 14.4 Streamable HTTP 会话 → 网关会话投影，不越权为平台状态

源码中的 `StreamableHTTPSessionManager`（`src/mcp/server/streamable_http_manager.py`）维护：

- `session_id → StreamableHTTPServerTransport`；
- 创建者 `AuthorizationContext` 与 session owner 绑定；
- session creation lock、idle deadline、崩溃/退出清理；
- `stateless=True` 时每请求新 transport，无 session/event state；
- stateful 未知、过期或凭证不匹配均按 404 `Session not found`；
- `2026` 入口由 `_streamable_http_modern.py` 执行 single-exchange，无 `Mcp-Session-Id`，无 back-channel。

映射到平台时分成两类：

1. **MCP transport session（非权威）**：只保存协议连接、认证上下文、SSE 游标和传输清理句柄；可映射到网关连接表或短期会话缓存。
2. **平台 execution session（权威）**：身份、角色、项目范围、任务租约、调用预算、幂等键、事务/发布状态和证据链；必须由平台授权/任务/权威状态服务保存，不能塞进 MCP `Mcp-Session-Id`。

首个 legacy 初始化请求创建 MCP session 不得自动创建平台任务或授予权限；modern 每请求无 session 也不得绕过平台身份与授权。若 MCP session 与平台调用 id 绑定，绑定关系应是只读关联/证据字段，不能让客户端通过修改 session id 选中另一项执行状态。

### 14.5 限体、SSE 与恢复 → 入口保护和事件投影

- `RequestBodyLimitMiddleware` 在解析和 session creation 前检查 `Content-Length` 与分块累计大小，默认 4 MiB，超限 413。平台网关应在 JSON 解析、能力搜索和任务创建前执行请求体/头/事件预算；能力契约还应声明参数深度、数组/字符串、响应体和累计事件上限。限体失败不应创建任务、不应写业务状态。
- Streamable HTTP 的 JSON response 与 SSE response 是**同一请求结果的两种传输表现**。网关把内部 `统一结果` 投影为 JSON 或 `event: message/data`，不在 SSE 层定义第二个业务结果模型。
- `EventStore` 存在时，服务端事件带 id，客户端用 `Last-Event-ID` 和 resumption token 恢复；没有 `EventStore` 只能提供 SSE，不能宣称可恢复。平台应把“事件重放/恢复”限制为已持久化、可验证的通知/进度/结果投影。
- SSE 恢复只补发未确认的协议事件，不重放 `tools/call` 的执行权。重连不得重新执行能力；若结果是否已提交不确定，调用方必须以平台幂等键/调用状态查询为准。
- 客户端默认有限重连次数和退避。网关必须设连接、重连、事件积压、并发 session 和总发送字节上限，并在达到上限后有界关闭与留痕，不能无限重连或无限缓存。

### 14.6 安全边界 → 公共契约的前置验证与最小授权

SDK 源码提供了可直接吸收的边界顺序，但不是把 SDK 的安全默认值照搬：

1. **Content-Type / Host / Origin**：`TransportSecurityMiddleware` 在 handler 前校验 JSON Content-Type，并按显式 allowed hosts/origins 返回 400/421/403。平台薄网关应把这些作为 HTTP 入口门禁；生产是否开启、允许哪些来源必须由平台部署安全配置明确，不能假设“localhost 默认安全”可用于公网。
2. **requestState**：`RequestStateBoundary` 将 client echo 视为攻击者输入，对 sealed token 校验 TTL、request binding、audience 和 principal；失败不把内部原因回给线缆。平台公共契约应有不可伪造的调用上下文/授权凭证和证据关联，客户端提交的角色、owner、项目范围、结果、分数、状态、签名摘要都只能作为候选输入，不能当权威字段。
3. **session owner / bearer principal**：MCP session 与创建者凭证绑定的模式可映射为传输会话归属校验；真正角色、项目范围和提权仍由平台授权服务判定。session id、tool name、progress token、resumption token 都是不可信输入。
4. **工具名和参数 schema**：名字校验、参数模型校验、输出 schema 校验均应发生在执行前/结果出站前；平台要把 MCP name 映射到唯一能力 id，并拒绝未公开能力、参数漂移和越权能力。
5. **错误脱敏**：MCP wire 只返回稳定错误码和可安全展示消息；堆栈、凭证、内部路径、provider 细节进入平台诊断/证据，不进入 MCP `data`。

### 14.7 工具注册与结果整形 → 能力契约与统一结果

官方 SDK 的 `Tool.from_function`/`ToolManager` 是“注册表驱动的协议适配器”，其边界可映射为：

```text
平台能力契约/注册表（唯一）
  → MCP tools/list 投影（name/title/description/inputSchema/outputSchema/annotations）
  → MCP tools/call 入参预解析 + schema 校验
  → 平台唯一能力调用器（授权→预算→provider→真实执行）
  → 公共统一结果
  → MCP result/content/structuredContent/isError 投影
```

具体规则：

- `tools/list` 只能从平台已公开、已授权可见的能力注册表生成；MCP `ToolManager` 的本地 dict 不能成为平台能力目录。重名/别名必须在平台注册阶段裁决，不能以“后注册覆盖”改变权威能力。
- `func_metadata` 从 Python 签名生成 JSON Schema 的思路可作为**适配器校验**，但公共参数契约仍是唯一事实源。若函数签名、MCP schema、平台契约不一致，拒绝注册/装配并写漂移证据；不能以运行时自动推导掩盖契约不一致。
- MCP 对字符串化 JSON 做兼容预解析后仍执行最终类型校验；平台可吸收这一兼容性，但不得放宽严格类型、范围、路径、权限和资源预算检查。
- `Tool.run` 将 `MCPError` 作为协议错误、普通异常包装为 `ToolError`；平台对应为稳定 `错误码/消息/可重试/来源`。普通工具失败可以投影为 `isError=true`，但平台权威调用结果必须保留失败事实和证据，不能让 `isError` 变成唯一记录。
- 文本、content block、BaseModel/TypedDict/泛型结构化结果由 SDK 的 `convert_result` 统一为 `content` 与 `structured_content`；平台应先得到统一结果对象，再按 MCP 客户端能力选择文本、内容块或结构化投影。MCP `structuredContent` 不是新的平台数据模型，不能绕过公共契约。
- `InputRequiredResult`、progress、URL elicitation 等是交互/补充输入协议。它们只能生成待用户确认或待补参的公共事件/状态，不应直接执行隐含动作；补参后仍从同一能力调用器重新校验与授权。

### 14.8 薄网关公共契约草案（只定义边界，不新增第二内核）

MCP 适配层至少需要把下列字段映射到已有公共契约；字段名可按平台中文命名规范实现，但语义不能丢：

| 外部 MCP 语义 | 内部公共契约最小字段 | 权威 owner |
|---|---|---|
| `method/name/arguments` | `能力id`、`参数`、`契约版本/指纹` | 能力目录 + 唯一调用器 |
| JSON-RPC `id` | `调用id`（仅关联，不当幂等键） | 网关关联层；执行状态由任务/调用服务 |
| caller/session/auth | `调用者`、`身份`、`项目范围`、`授权上下文` | 授权服务 |
| timeout/cancel/connection close | `预算`、`取消请求`、`取消确认`、`执行状态`、`可重试` | 运行核心/任务系统 |
| SSE `id`/`Last-Event-ID` | `事件游标`、`投影版本`、`恢复结果` | 运行事件/事件存储；不得触发重做 |
| `content/structuredContent/isError` | `值`、`诊断`、`错误码`、`成功`、`可重试`、`来源` | 公共结果类型 + 诊断/证据 |
| protocol/session headers | `协议适配版本`、`传输会话关联` | MCP 薄网关；不是能力/状态 owner |

网关公开的内部调用接口建议只有两条语义路径：

- **查询/投影**：`tools/list` 或等价发现请求 → 能力搜索/契约读取，只读、按调用者过滤，不创建执行状态。
- **执行提交**：`tools/call` → 构造公共调用命令 → 经过授权、契约校验、监督提交和唯一 provider 执行；返回统一结果或“已提交/处理中”的可查询调用状态。任何同步/流式返回都只是这个公共结果的投影。

不得增加 `mcp_execute_directly`、MCP 私有任务表、MCP 私有授权角色、MCP 私有 provider 注册表或 MCP 私有“成功状态”。如果必须保留 MCP 原生 method/tool 名，必须有一张可审计的 `MCP 名称 → 公共能力 id` 映射，并由装配/契约门禁验证一对一、版本、授权范围和撤销状态。

### 14.9 复用、升级、新建、隔离裁决

| MCP 能力 | 底座裁决 | 原因与验收 |
|---|---|---|
| 双时代 parser、JSON-RPC id/pending、EOF fan-out | **隔离复用为协议适配器** | 可复用边界语义；不可复制到平台任务/事务内核。验收覆盖跨时代拒绝、id 关联、EOF pending 全收口。 |
| 请求体/响应体/事件预算、Host/Origin、session owner | **升级现有 HTTP 网关/运行核心边界** | 现有网关已有真实 HTTP/SSE/取消雏形；补统一上限、归属、脱敏和证据，不新建 MCP 安全中心。 |
| SSE event store/resumption | **升级运行事件/事件存储投影** | 只恢复未确认事件，不重放能力执行；验证断线、重复 event id、末游标、无 store 时明确不可恢复。 |
| 工具注册、schema、结果 content/structuredContent | **复用公共契约 + 新增薄 MCP 映射** | 注册表/契约/统一结果继续唯一；MCP 只做投影和反序列化。验证声明漂移、未知能力、参数错误、结构化结果和工具失败。 |
| MCP session、initialize/discover、Mcp-Session-Id | **隔离为 transport session** | 不进入平台权威状态；验证重启、凭证不匹配、idle cleanup、stateless/modern 差异。 |
| 完整 MCP server runtime、独立任务/授权/状态/发布流 | **不吸收/废弃为平台底座方案** | 会产生第二执行权威、第二授权根和第二错误/证据链；平台只接入其协议边界。 |

### 14.10 后续验收契约与剩余风险

后续若进入平台实现，最小验收不是“能连上 MCP”，而是以下闭环：

1. `tools/list` 只返回公共能力目录中已公开且调用者有权看到的条目；未知/撤销/契约漂移不进入列表。
2. legacy 与 modern 同一能力调用得到同一内部命令、授权判定、执行 owner 和结果语义；只允许协议投影不同。
3. `tools/call` 的 malformed JSON、schema 错误、超限 body、Host/Origin/session owner 错误均在 handler/provider 之前拒绝，且不创建任务、不写权威业务状态。
4. 超时、主动取消、对端取消、EOF、进程崩溃分别有可区分的公共结果和资源清理证据；晚到结果不得覆盖已取消/已超时调用。
5. SSE 断线恢复只补发事件；重复恢复不会重复执行能力；未知执行状态走调用状态查询/幂等路径。
6. MCP 错误、工具级 `isError`、平台统一失败结果三者有固定转换表；内部堆栈和凭证不出线。
7. MCP 适配层源码只能调用公共契约/模块公开入口，静态依赖审计不得出现直连 provider、绕过授权、旁路写状态或重复注册表。

后续映射阶段仅完成架构映射，未在目标仓库实现 MCP 网关；后续已补做下述 SDK 针对性测试，但未运行完整套件、conformance 或平台验收。剩余风险：专属 `system_engineering_toolkit` 的 `project_context` 错绑到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，而目标项目是外部源码参考仓；目标无 `.codegraph/`，`codegraph_explore` 返回未索引，因此本节证据仍来自目标工作树的源码、测试和既有细探，不能把错误项目的代码图当作目标证据。

## 15. 后续收口：传输、能力、session、错误、取消与生命周期

本节是对旧细探逐项回到当前源码后的后续收口，不是新的平台设计。证据基线为当前工作树 `HEAD 0d92192765fa7d6a20fbfe7e62e242e44933574f`（2026-08-18），源码路径以仓库真实布局为准：协议实现包在 `src/mcp-types/mcp_types/`，`src/mcp/types/` 是向 `mcp_types` 的兼容镜像；服务端/客户端 SDK 在 `src/mcp/`。旧细探未删除，后续事实只维护本文。

### 15.1 传输契约与真实调用链

| 传输 | 创建与持有者 | 入站/出站转换 | 正常释放 | 失败、取消、崩溃路径 |
|---|---|---|---|---|
| `stdio_client` | `client/stdio.py:113-136` 创建子进程、四端 memory stream；`Client` 的外层 async context 持有 transport | 子进程 stdout 按换行解析为 `SessionMessage` 或异常值；出站 JSON 每条追加换行写 stdin（`stdio.py:141-182`） | 关闭 read/write stream，等待 writer flush，关闭 stdin；进程在 `2s` grace 后升级终止，POSIX 还给 `SIGTERM→SIGKILL` 窗口，最后关闭 stdout/transport（`stdio.py:184-215`、`248-317`） | stdout 非法 JSON 不直接炸读循环，而作为 `Exception` 交给 dispatcher/session；stdin/stdout 管道异常关闭读端。调用者取消由 shielded shutdown 接管，避免留下子进程或子进程树；但同步工具函数在线程中的真实中止仍未被此 transport 保证。 |
| `stdio_server` | `server/stdio.py:161-182` 建立两个 context stream；默认接管 fd 0/1，`_claims` 锁保护进程内唯一 owner | stdin 逐行 `jsonrpc_message_adapter`，解析失败作为异常项；stdout 只写 JSON 行并 flush（`stdio.py:184-212`） | 退出时先恢复 fd 1，再恢复 fd 0；`_claim_fd` 只有 wire duplicate 已建立并成功 `dup2` 恢复后才注销 claim（`stdio.py:106-158`、`213-217`） | 同进程重复 claim 直接 `RuntimeError`；恢复失败保留 claim，拒绝后继者，避免把业务输出误写入协议管道。默认 fd 0 指向 null、fd 1 指向 stderr，降低 handler/子进程污染 wire 的风险。 |
| Streamable HTTP（状态化） | `StreamableHTTPSessionManager` 是唯一 session owner；`session_id → StreamableHTTPServerTransport` 与创建凭证并存（`streamable_http_manager.py:41-110`） | POST body 解析 JSON-RPC；SSE 模式按 request id 建 per-request stream，JSON 模式只允许响应 body；GET 作为唯一 standalone SSE 通道；`message_router` 按 response id/`related_request_id` 投递（`streamable_http.py:459-685`、`983-1065`） | manager `run()` 只允许一次，统一进入 app lifespan；退出取消 task group、清空 transports/owners；transport `terminate()` 关闭每个 request stream 和四个底层 stream（`streamable_http_manager.py:119-163`、`streamable_http.py:807-836`） | body 限制在解析/建 session 前执行，超限 413（`streamable_http_manager.py:374-431`）；未知、过期或凭证不匹配 session 返回 404 + `INVALID_REQUEST`；idle deadline 取消 serve loop 并从两个 owner 表移除；崩溃 finally 清理 session。`event_store` 缺失时仍可 SSE，但不能宣称可恢复。 |
| Streamable HTTP（无状态/modern） | `stateless=True` 每个 POST 新建 transport，不保存 session/event state；modern `serve_one` 每请求新建 `Connection`（`streamable_http_manager.py:195-249`、`runner.py:755-838`） | modern 由 `Mcp-Protocol-Version` 头和 `_meta` envelope 进入 `handle_modern_request`；每次 single exchange，不建立 legacy `Mcp-Session-Id` handshake | POST 完成后 `terminate()`；每请求 `Connection.exit_stack` 在 `serve_one` 的 finally 中 shielded、最多 5 秒关闭（`runner.py:127-145`、815-838） | JSON response 的 request-scoped channel `can_send_request=False`，服务器只能返回结果/通知，不能发 server→client request；modern dispatcher 收到 `initialize` 返回 `UNSUPPORTED_PROTOCOL_VERSION`，server-side request 统一 `NoBackChannelError`。 |

**传输边界结论：** transport 只负责字节/HTTP/SSE/进程和 stream ownership；`JSONRPCDispatcher` 才是跨 transport 的 request id、pending、读循环、取消、progress 和异常到 wire 的并发内核；`ServerRunner` 才负责 MCP method/version surface、参数模型、handler 与结果整形。任何 transport-specific fallback 都不能越过这三层重新实现工具执行。

**SSE 恢复的精确语义：** `EventStore.store_event()` 在 priming event 之前建立游标，随后 `message_router` 给 response/notification 存 event id；客户端携带 `Last-Event-ID` 走 GET replay。恢复只重放已存协议事件，不重新执行原 request；请求是否已经落到业务 handler 只能由调用 id/幂等状态确认。`_replay_events` 还留有 replay→live-tail 注册窗口，源码注释明确把它作为待解决边界，不能把“有 EventStore”写成无条件强一致恢复。

### 15.2 工具、资源与提示的契约分界

| 能力 | 注册/发现 | 执行与结果 | 失败边界与安全事实 |
|---|---|---|---|
| Tool | `MCPServer.tool()` → `ToolManager.add_tool()` → `Tool.from_function()`；从签名/注解生成 `inputSchema`，输出类型生成可选 `outputSchema`（`mcpserver/tools/base.py:57-121`）；`list_tools()` 将内部 `Tool` 映射为 wire `mcp_types.Tool`（`server.py:481-496`） | `tools/call` → `ToolManager.call_tool` → `Tool.run`；先 resolver/参数校验，再 Context 注入，async 直接 await、sync 经 `anyio.to_thread.run_sync`；`convert_result=True` 将文本/content/结构化值转为 `CallToolResult`（`base.py:123-172`） | `MCPError`（含 URL elicitation）原样上升为 JSON-RPC error；普通异常包装 `ToolError`，高层 `_handle_call_tool` 转 `CallToolResult(is_error=True)`（`base.py:173-181`、`server.py:415-424`）。字符串化数组/对象会先 JSON 预解析再做最终模型校验；工具名违规当前是 warning 而非拒绝，lambda 无显式名字才拒绝。 |
| Resource | 静态资源存 `_resources[uri]`；模板存 `_templates[uri_template]`；查找 concrete first，再按 RFC 6570 template 匹配（`resources/resource_manager.py:28-58`、89-127） | `resources/read` → `MCPServer.read_resource` → `ResourceManager.get_resource` → `Resource.read()` 或模板 `create_resource()`；文本直接 `TextResourceContents`，bytes 做 base64 `BlobResourceContents`（`server.py:540-568`、431-463） | 默认 `ResourceSecurity` 拒绝 `..` path component、绝对路径、NUL；匹配后安全拒绝抛 `ResourceSecurityError`，manager 转 `ResourceNotFoundError`，不会回退到后续宽松模板（`resources/templates.py:31-103`、180-204）。模板创建异常统一 `ResourceError`；高层映射为 `INVALID_PARAMS`（not found）或 `INTERNAL_ERROR`（read/create error）。静态资源不注入 Context；模板才可拿 Context。 |
| Prompt | `MCPServer.prompt()` → `Prompt.from_function()` → `PromptManager`；参数 schema 转为 `PromptArgument`，required 信息由签名模型产生（`prompts/base.py:97-156`、`manager.py:19-67`） | `prompts/get` → `Prompt.render()`；缺 required 参数先拒绝；sync 经 worker thread，async 直接 await；字符串变 `UserMessage(TextContent)`，dict 经 message validator，Image/Audio 可触发文件读取，现成 `Message`/content block 保留；最终 `GetPromptResult.messages` 用 JSONable conversion（`prompts/base.py:158-209`、`server.py:1268-1297`） | `InputRequiredResult` 原样返回；`MCPError` 原样上升；其他 render 异常变为 `ValueError`，再由 runner 的通用异常边界转 wire error。Prompt 是消息资源/动态交互入口，不是 SDK 内部字符串插值引擎。 |

**注册表所有权与重复项：** `ToolManager.add_tool`、`ResourceManager.add_resource`、`PromptManager.add_prompt` 在增量注册时遇重复均返回已有对象并可 warning，不执行后注册覆盖；但 `ToolManager.__init__(tools=[...])` 的初始化列表是 warning 后直接赋最后一个，不能把两种路径概括为统一的“重复即失败”。`remove_tool`/`remove_prompt` 对未知名称抛工具/值错误。注册信息推导 capabilities 的事实在 `lowlevel/server.py:446-462`、`522-625`：有 handler 才声明能力；modern 的 list-changed/subscription 位由 `subscriptions/listen` 是否注册推导。

**分页边界：** client API 会携带 `PaginatedRequestParams` 与 cursor，但 `MCPServer._handle_list_tools/_resources/_prompts` 当前直接返回 manager 的全量列表（`server.py:410-479`），manager 本身没有游标切片。分页是低层自定义 handler 的责任，不能仅因方法参数存在就宣称高层注册表已实现持久分页。

### 15.3 ClientSession、Server Connection 与 session 生命周期

1. **ClientSession 进入：** `ClientSession.__aenter__` 先创建 task group 和每个 vendor notification binding 的 bounded FIFO（容量 `_NOTIFICATION_QUEUE_SIZE=256`），再启动 dispatcher；退出时取消整个 task group，关闭 binding queues，所有未结束 `subscriptions/listen` route settle 为 `CONNECTION_CLOSED`（`client/session.py:395-525`、1391-1406）。transport context 的 four stream ends 由外层 `stdio_client`/`streamable_http_client` 持有和关闭，不能把 `ClientSession.__aexit__` 当成所有底层连接的 owner。
2. **握手/modern 状态：** `initialize()` 发送 legacy handshake，收到结果后 `adopt()`、记录 `_negotiated_version`、client/server capabilities 并发送 `notifications/initialized`；`discover()` 只在 `UNSUPPORTED_PROTOCOL_VERSION` 时按服务端 supported 与本地 modern 版本求交集重试一次，其他错误直接上升（`client/session.py:658-800`）。`adopt()` 清空另一时代状态，重建 extension result-claim adapter；因此一个 session 同时只有一个 active protocol era。
3. **调用状态：** `send_request()` 负责 typed model dump、版本/头/`_meta` stamp、dispatcher correlation、wire result validation；`list_tools()` 还缓存 output schema 与 `x-mcp-header` 映射，schema 改变会淘汰 compiled validator，完整无 cursor 列表会淘汰已删除工具的旧缓存（`client/session.py:547-608`、1279-1331）。调用 `tools/call` 成功结果会按已缓存 output schema 二次校验；`InputRequiredResult` 与扩展 claimed result 默认不静默吞掉，必须显式允许。
4. **Server Connection：** legacy `Connection.for_loop()` 以 handshake version hint 创建，未收到 `notifications/initialized` 前 gate 不开放；modern `Connection.from_envelope()` 每请求 born-ready、把 capability 与可选 client info 绑定，并默认无 back-channel。`Connection.state` 是每连接 scratch，`exit_stack` 按 LIFO 清理；`send_raw_request` 没有通道或 modern 禁止 server request 时抛 `NoBackChannelError`，`notify` 是 best-effort 丢弃（`server/connection.py:185-337`）。
5. **Server lifespan：** 普通 `Server.run()` 在 `self.lifespan` 外层进入一次，再驱动 `serve_dual_era_loop`；Streamable HTTP manager 自己进入一次 app lifespan，并将 state 传给每个 loop/`serve_one`，避免每个 HTTP request 重进 lifespan（`lowlevel/server.py:691-718`、`streamable_http_manager.py:145-163`）。连接级 cleanup 用 `aclose_shielded`，最多 5 秒且 cleanup 异常只记录不覆盖 driver 原异常；manager 是单次使用对象，run 完成后不得复用。

### 15.4 错误与取消矩阵（按真实边界，不把异常名当结果）

| 场景 | 线缆/调用方事实 | 是否进入 handler | 收尾与可重试判断 |
|---|---|---|---|
| malformed JSON / JSON-RPC frame | transport 解析失败产生 `Exception` 或直接返回 `PARSE_ERROR`/`INVALID_PARAMS` | 否 | dispatcher 保持读循环；transport/session fault 可交 `message_handler`，不能当业务失败结果。 |
| unknown method | runner lookup 前/后返回 `METHOD_NOT_FOUND`；spec surface malformed 可能先被版本表拒绝 | 否 | 不创建能力执行；可重新 list/探测。 |
| invalid params | 版本 surface 或 `HandlerEntry.params_type.model_validate` 失败，统一 `INVALID_PARAMS` | 否 | 不调用 handler；客户端修正输入后可重试。 |
| handler `MCPError` | 保留自带 `ErrorData`；`NoBackChannelError` 是 `INVALID_REQUEST`；URL elicitation 为 `URL_ELICITATION_REQUIRED` | 已进入 | 结果是 JSON-RPC error，不是工具 `is_error`；调用方必须按 code/data 决定补参/授权/重试。 |
| 普通工具异常 | `Tool.run` → `ToolError` → `MCPServer._handle_call_tool` 返回 `is_error=true` 文本 | 已进入 | 这是工具级业务失败，仍有 wire result；不应被平台适配器当作 transport success 或丢掉失败证据。 |
| 资源未找到/读取异常 | `ResourceNotFoundError` → `INVALID_PARAMS`；`ResourceError` → `INTERNAL_ERROR` | 查找/读取 handler 已进入，高层资源函数视场景可能已执行 | 未找到通常修 URI；读取/模板内部错误不可向客户端泄漏 traceback。 |
| prompt 普通异常 | `Prompt.render` 包装为 `ValueError`；runner 的 legacy dispatcher 当前 generic fallback 是 `code=0`（兼容旧实现），modern entry 是 `INTERNAL_ERROR` | 已进入 | 这是当前 SDK 的跨时代错误码差异，适配层不能假设所有 generic handler error 都是 `-32603`。 |
| dispatcher/transport EOF | `_fan_out_closed` 给所有 pending `CONNECTION_CLOSED`，取消 in-flight handlers；晚到 response 按未知 id 丢弃 | 可能已进入 | 连接失败与业务结果分开；调用方需查询真实执行状态后再决定重试。 |

**异常边界的收口结论：** `handler_exception_to_error_data()` 只把 `MCPError` 和 Pydantic `ValidationError` 统一化；其他异常在 `JSONRPCDispatcher._handle_request` 为历史兼容保留 `code=0`，modern `modern_error_data()` 才泛化为 `INTERNAL_ERROR`。现有第 9 节的“归一化”应理解为“到 wire 的边界统一”，不是“所有时代错误码一致”。

**取消三层语义：**

- 调用方 timeout 或 task cancellation：dispatcher 先清除本地 `_pending`，若请求写已开始且策略允许，最多 5 秒发送 courtesy `notifications/cancelled`；`initialize`/`server/discover` 明确不发送取消。
- 对端 `notifications/cancelled`：按 request id 查 `_in_flight`；`peer_cancel_mode="interrupt"` 取消 handler `CancelScope`，`"signal"` 只设置 `ctx.cancel_requested` 让 handler 协作收尾。两者都不再写该请求结果，晚到结果不得覆盖；`_settle_unanswered` 交给 transport 决定是否需要结束 HTTP response。
- 2025-era Streamable HTTP 为结束必须有 response 的 SSE 请求，由 `on_request_unanswered` 合成 `REQUEST_CANCELLED=-32800`；2026 Streamable HTTP 不回答被取消请求，而是取消对应 POST 的 request-level `CancelScope`。因此“收到 cancelled”“handler 已停止”“调用已确认取消”是三个不同事实。

### 15.5 资源生命周期表与反向场景

| 资源 | 创建 | 持有/转移 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主/子进程崩溃后的证据 |
|---|---|---|---|---|---|---|
| `_pending` waiter / `_in_flight` handler | dispatcher 发请求或收到 request | dispatcher dict；request id 是关联键，不是幂等键 | response/error 唤醒并 finally pop；handler finally identity-check pop | error response；普通异常不使读循环退出 | pending pop + courtesy cancel；handler scope cancel，结果丢弃 | EOF fan-out `CONNECTION_CLOSED`，task group cancel；未知 late id 丢弃。 |
| AnyIO memory streams | transport/session context 建立 | 成对 send/receive 端分散在 client/transport/router | 每个 context manager 关闭四端；request stream writer/reader 单独清理 | 解析/HTTP error 仍关闭；cleanup 不依赖成功结果 | outer task group cancel 后 finally 逐端 close | `test_transport_stream_cleanup.py` 强制 GC 检查 `ResourceWarning`；当前核对三项通过。 |
| stdio 子进程与管道 | `_create_platform_compatible_process` 新 session/process group | stdio client 持有 process、pipe bridge、reader/writer tasks | close stdin → poll returncode → reap，保留子进程自有 exit code | pipe error 关闭 read side，避免 pending 永久等待 | shielded flush、SIGTERM/SIGKILL、kill tree、close pipes | 生命周期测试覆盖自愿退出、mid-session exit code、取消杀全树；当前核对未执行该 real-subprocess 文件，源码与已有测试证据分开记录。 |
| stateful HTTP session | manager lock 内生成 id，登记 transport/owner | manager dict + transport task + app lifespan state | DELETE/transport terminate/manager shutdown 清 stream、删 owner | task exception finally 删除 registry | idle deadline cancel，remove maps，terminate | manager shutdown 清 maps；run 单次不可重启，需新 manager。 |
| per-connection `exit_stack` / lifespan state | `Connection` factory 或 server lifespan | runner/handler/middleware 可 push cleanup | LIFO，shielded，5 秒有界 | callback 异常记录并吞掉，不遮蔽 driver | cancellation 下仍尝试清理，超时 abandons remaining callbacks | transport/session finally 统一调用；无运行时探针证明任意用户 cleanup 都幂等。 |
| sync tool/resource/prompt worker | `anyio.to_thread.run_sync` | AnyIO worker thread | 返回后转换结果 | 异常包装 Tool/Resource/ValueError | 源码未显式配置 `abandon_on_cancel=True`；不能把取消 wire 语义等同于同步 Python 函数已停止 | 没有线程残留专项现场验证；需调用方保证函数本身幂等/可恢复。 |

**反向场景核对：** 当前源码和测试已覆盖 malformed/unknown/invalid params、重复 tool、资源路径穿越/绝对路径/NUL、未知取消 id、取消后继续服务、EOF 取消 handler、pending server→client request 的关闭、HTTP stream 端泄漏；仍未由当前核对运行证实的是完整跨 transport cancellation matrix、EventStore replay/live-tail、session idle timeout、manager restart rejection、Windows process tree、provider/OAuth 外部服务和完整 conformance。

### 15.6 后续验证等级与现场结果

| 结论项 | 源码存在 | 测试源码存在 | 当前核对真实执行 | 等级 |
|---|---|---|---|---|
| dispatcher 取消后 server 存活、EOF 取消 handler/pending server request | `shared/jsonrpc_dispatcher.py:315-445,476-837`、`server/runner.py:447-468` | `tests/server/test_cancel_handling.py`、`tests/interaction/lowlevel/test_cancellation.py` | `PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest -q tests/server/test_cancel_handling.py`：3 passed | **已执行通过（局部）** |
| ToolManager schema/async/sync/JSON 字符串预解析/structured output/重复项 | `mcpserver/tools/base.py`、`utilities/func_metadata.py`、`tools/tool_manager.py` | `tests/server/mcpserver/test_tool_manager.py` | 同命令：50 项全部 passed | **已执行通过（局部）** |
| ResourceTemplate RFC6570 与 traversal/NUL/模板创建/bytes/InputRequired | `resources/templates.py`、`resource_manager.py` | `tests/server/mcpserver/resources/test_resource_template.py` | 同命令：34 项全部 passed | **已执行通过（局部）** |
| memory stream 四端清理 | `client/streamable_http.py:639-710`、`client/sse.py` | `tests/client/test_transport_stream_cleanup.py` | 首次 2 passed、1 项因本机代理把 localhost 连接变为 502；设置 `NO_PROXY=127.0.0.1,localhost` 重跑该项 1 passed；合计 3 passed | **已执行通过（环境修正后）** |
| stdio real process tree/lifecycle | `client/stdio.py:184-317`、`server/stdio.py:161-217` | `tests/transports/stdio/test_lifecycle.py` | 当前核对未执行 | **源码+测试存在，未执行** |
| prompts/resources/tools 跨传输交互、modern/legacy、SSE/EventStore、完整覆盖率/conformance | 入口与测试目录均存在 | `tests/interaction/`、`.github/workflows/conformance.yml` | 当前核对未执行 | **未验证** |

当前核对现场没有修改源码、依赖、配置、测试、README 或 Git；`git status --short --branch` 仍只有任务开始前的 `?? ARCHITECTURE.md` 与 `?? 细探-MCP官方SDK.md`。`uv run --frozen` 首次创建的 `.venv` 属本地忽略运行环境，不是提交内容；没有写回 `uv.lock`。

### 15.7 后续裁决：已吸收、待核、不可宣称

**已吸收为 SDK 事实：**

- transport/dispatcher/runner 三段式 ownership；pending 与 in-flight 的 identity-guard cleanup；EOF fan-out；取消 request 不回复与 2025 HTTP 终止器的时代差异。
- stdio 的受控环境、newline framing、fd claim/restore、进程组终止；Streamable HTTP 的 session owner、body limit、JSON/SSE channel 差异、EventStore 仅恢复事件。
- Tool 的“注册期 schema + 调用期最终校验 + 结果出站校验”；Resource template 的 decoded-parameter security gate；Prompt 的消息归一化和 InputRequired passthrough。
- ClientSession 的 protocol-era 单一 active state、bounded notification queue、output-schema cache invalidation；Server Connection 的 scratch state、exit stack、modern no-back-channel。

**待核：** 完整 conformance 对 2026-07-28 特性的覆盖、EventStore replay 与 live-tail 的竞态、全 transport/全 backend 的取消差异、同步 worker 在取消下的实际停机、idle cleanup 的实时现场、Windows job object、OAuth/OTel/外部 HTTP 服务。

**不可宣称：** 不能把存在测试文件当作测试通过；不能把 `InputRequiredResult` 当成自动多轮完成（除非显式启用 client driver/提供 input responses）；不能把 `Mcp-Session-Id` 当平台执行 session；不能把 SSE reconnect 当能力重试；不能把 `is_error=true` 当 JSON-RPC error；不能把 `CONNECTION_CLOSED` 当 provider 已停止；不能把 handler 返回的 typed result 当作已通过版本 surface/output schema。

后续结论：MCP Python SDK 已形成可审计的“传输 → dispatcher → runner → registry/handler → wire result”单链路；取消、错误、session 和生命周期的正常/失败/关闭边界均有明确 owner，且关键局部测试已真实通过。仍需把跨 transport、真实外部依赖、EventStore race、sync worker cancellation 与 conformance 留为未验证项；这些不能由本架构文档替代运行证据。

## 16. 网络/协议专项审计：连接、收发、超时、取消、断连、重试与资源

### 16.1 审计范围与证据

本节选择此前未出现在平台根档案中的网络/协议项目：

`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/04_协议与SDK/python-sdk`

当前核对先用平台 CodeGraph 盘点候选项目与既有审计条目；目标仓库自身没有 `.codegraph/` 索引，因此没有把其他仓库的代码地图冒充目标证据。随后完整分段读取了目标根 `ARCHITECTURE.md`、`README.md`、`SECURITY.md`、`pyproject.toml`、`docs/client/transports.md`、`docs/run/deploy.md`，并按网络链路读取：

- 客户端 `src/mcp/client/streamable_http.py`、`stdio.py`，包括 HTTP POST/SSE、GET 重连、取消翻译、子进程和管道收尾；
- 服务端 `src/mcp/server/streamable_http_manager.py`，包括 body limit、session owner、stateful/stateless、idle cleanup、lifespan 和终止；
- 共享 dispatcher、runner、connection、request state 的既有架构定位和错误/取消矩阵；
- `tests/client/test_streamable_http.py`、`tests/client/test_stdio.py`、`tests/interaction/lowlevel/test_cancellation.py`、`tests/interaction/transports/test_client_transport_http.py`、`test_hosting_resume.py`、`test_hosting_http_modern.py`、`test_bridge.py` 及相关 requirement 目录；
- `docs/client/transports.md`、`docs/client/subscriptions.md`、`docs/run/deploy.md`、`docs/run/legacy-clients.md`、`docs/handlers/multi-round-trip.md`、`docs/troubleshooting.md` 等连接、重连、部署和取消文档。

未安装依赖、未启动服务、未访问外部网络、未运行目标项目测试；以下“测试覆盖”只表示测试源码和 requirement 映射存在，不表示当前核对运行通过。

### 16.2 总体连接与收发链

```text
Client / ClientSession
  → Client.__post_init__ 按输入类型选择 transport
  → stdio_client / streamable_http_client / sse_client / in-memory
  → TransportStreams（read/write）
  → JSONRPCDispatcher（request id、pending、in-flight、EOF、取消）
  → ClientSession（版本 surface、_meta、schema、结果）
  ↔ HTTP/SSE/stdio wire
  → StreamableHTTPSessionManager / stdio server / SSE server
  → Connection / ServerRunner
  → handler registry / Tool、Resource、Prompt
  → typed result → JSON-RPC/SSE/JSON response
```

所有 transport 都被压缩成异步 `(read, write)` 流协议，协议分发不被某一种网络实现复制。HTTP 的状态化 session 由 `StreamableHTTPSessionManager` 独占，modern `2026-07-28` 请求由请求级连接承载且不创建 `Mcp-Session-Id`；stdio 的进程和管道由 `stdio_client` 独占。这个 owner 分界是本项目最强的架构事实：断线是 transport 事实，业务结果和执行状态仍由 dispatcher/handler 或外部应用持有。

### 16.3 连接、超时与收发边界

| 场景 | 源码事实 | 审计结论 |
|---|---|---|
| HTTP 客户端连接 | 默认 `httpx2.AsyncClient` 使用 `follow_redirects=True`；连接、写入、连接池 30 秒，读取 300 秒，以允许长 SSE 响应 | 连接/读超时是 transport 预算，不是 handler 或 provider 的总 deadline；业务层仍需传递自己的预算 |
| 自定义 HTTP client | 调用方自行创建并进入/退出 `AsyncClient`；SDK 不关闭外部传入 client | 所有权清楚，但误把外部 client 交给长期 transport 而不自行退出会泄漏，文档已明确责任在调用方 |
| SSE GET | `handle_get_stream` 记录 `Last-Event-ID` 和服务端 `retry`，最多 `MAX_RECONNECTION_ATTEMPTS=2` 次；正常结束会清零 attempt | 这是有限的事件流恢复，不是请求业务重试；attempt 只对 GET 流有效，不能保证 POST 调用重做 |
| 请求 POST | POST 流在对应 `CancelScope` 内运行；HTTP >=400 优先解析 JSON-RPC error，否则生成稳定的错误映射；202 对 request 生成 `INVALID_REQUEST` | 非 2xx 不被简单当成 HTTP 成功；但 transport 没有通用幂等重试策略，避免了未知提交状态下重复执行 |
| body 上限 | 服务端 `RequestBodyLimitMiddleware` 在解析和 session 创建前检查 `Content-Length` 与实际分块，默认 4 MiB，超限 413 | 入口限体位置正确，不会因超限创建会话或进入 handler；响应/事件仍需应用层声明独立预算 |
| 请求级超时 | dispatcher 处理 caller timeout/cancellation，清理 pending，并在允许时有界发送 courtesy cancellation；HTTP modern 将取消翻译为关闭对应 POST response stream | 能保证调用方不永久等待；不能单凭 timeout 证明远端 handler、线程或外部 IO 已停止 |

### 16.4 取消、断连与重试审计

1. **取消分层正确。** legacy 通过 `notifications/cancelled` 按 request id 找到 in-flight handler；`interrupt` 取消 handler scope，`signal` 只设置协作取消标志。两者都禁止晚到结果写回。modern 没有 client-to-server cancellation notification，关闭请求自身 response stream 才是取消信号。
2. **HTTP 断连可传播到服务端。** ASGI bridge 测试覆盖客户端提前关闭响应后应用收到 `http.disconnect`；服务端 transport/manager 在 request stream、session 和 lifespan 的 finally 中清理。stateful session 还可按 `session_idle_timeout` 取消 loop、删除两个 owner 表并终止 transport。
3. **stdio 关闭是有界升级链。** 先关闭 stdin，等待 `PROCESS_TERMINATION_TIMEOUT=2s`；仍存活则 POSIX 对进程组执行 SIGTERM 后最多再等 `FORCE_KILL_TIMEOUT=2s`，Windows 使用 Job Object；最后关闭 stdout、子进程 transport 和所有 memory streams。shutdown 被 shield，避免 caller cancellation 留下活进程。
4. **SSE 重连不等于业务重试。** `Last-Event-ID` 只重放 EventStore 中已经存储的协议事件；它不重新执行原 request。POST 在响应已到达后不重连；响应尚未到达且可恢复时，测试覆盖有限重连路径。未知执行状态必须由调用方凭 request/idempotency 状态查询决定，不能因重连成功就再次调用。
5. **取消后的同步函数是主要资源风险。** 工具同步函数经 `anyio.to_thread.run_sync` 执行，源码没有把线程设置为可强制终止；取消可停止等待和线缆响应，但已进入的 Python/C 扩展阻塞函数可能继续运行。文档和现有架构档案已承认该边界，平台接入不能把 `CancelledError` 当作 provider 已停止。
6. **重试边界需要显式写进调用契约。** SDK 只对 transport/SSE 恢复提供有限次数与退避提示；它没有针对非幂等 `tools/call` 的统一 retry、幂等键或提交确认协议。认证、未知 session、协议版本、handler 已开始但连接断开等错误不可由外层无条件重试。

### 16.5 资源所有权与泄漏风险

| 资源 | owner 与正常释放 | 取消/崩溃收尾 | 剩余风险 |
|---|---|---|---|
| HTTP client | SDK 创建的 client 随 transport context 退出；外部传入 client 由调用方退出 | task group/transport finally 关闭流；client 本身不由 SDK 代管 | 外部 client 生命周期若跨 session，连接池预算、close 时机和代理行为由应用负责 |
| HTTP session/transport | manager 字典保存 transport 与 credential owner；terminate 删除/清理；manager 只允许运行一次 | lifespan shutdown 取消 task group、清空 registry；idle/crash finally 删除 session | manager 不能复用，重启必须新建；跨进程 session、订阅和事件存储不是 SDK 内建能力 |
| SSE event | EventStore 保存 event id，客户端带 `Last-Event-ID` 恢复 | 断连后有限重连/重放；无 EventStore 不能宣称恢复 | replay 到 live-tail 的竞态在既有架构记录中仍标为待验证；事件重放不提供业务执行幂等 |
| stdio process/tree | stdio transport 独占 process、stdin/stdout、bridge task 和 memory streams | shielded close、等待、SIGTERM/SIGKILL/Job Object、pipe close；测试含 ResourceWarning 检查 | 当前核对未运行真实子进程测试；Windows Job Object、继承孙进程和平台差异仍需 CI 现场证据 |
| dispatcher pending/in-flight | request id map 由 dispatcher identity-check pop；response/error 唤醒 pending | EOF fan-out `CONNECTION_CLOSED`，取消 in-flight，未知 late response 丢弃 | request id 只是关联键，不是跨重连幂等键；应用必须另设调用状态/幂等键 |

### 16.6 文档质量与事实漂移

文档质量总体较高：`docs/client/transports.md` 明确说构造 `Client` 不连接、`async with` 才建立连接；明确自有 HTTP client 的关闭责任；说明 stdio 的环境白名单和进程关闭。`docs/run/deploy.md` 也准确区分 modern 无 session、legacy sticky session、requestState 的跨 worker key/audience 要求、共享订阅总线和 SDK 不提供的生产设置。

仍需保持以下文档护栏：

- `README.md` 的“production client”示例不能被理解为包含生产级业务 deadline、幂等重试、TLS/代理策略或服务端 shutdown 配置；这些属于部署方和调用方。
- “支持 SSE/自动重连”必须注明版本、EventStore、最大次数和恢复对象；当前 modern 版本删除了旧式 `Last-Event-ID` resumability，不能用跨时代总称描述。
- `pyproject.toml` 的 100% branch coverage、3.10–3.14 分类器和 production/stable 元数据是项目门槛与声明，不是当前核对运行证据；架构文档已有“未运行测试”边界，后续更新不能删掉。
- `SECURITY.md` 只描述漏洞报告流程，没有替代部署文档中的 Host/Origin、认证、body limit、requestState 和外部 client 资源责任。安全声明必须继续引用源码和专项测试，而非只引用 README。
- 目标仓库已有根 `ARCHITECTURE.md` 与 `细探-MCP官方SDK.md`；本次没有修改旧细探，根架构档案继续作为唯一收口文档，避免两份网络语义产生漂移。

### 16.7 最终审计结论

**已确认：** transport → dispatcher → runner 的单链路；HTTP/stdio/SSE 连接与收发 owner；HTTP body limit；版本化 modern/legacy 路由；pending/in-flight EOF 收口；分层取消；stdio 进程树有限关闭；SSE 恢复不重做业务执行；stateful session owner 与 idle/crash cleanup。

**条件成立：** HTTP 自动恢复只适用于协议事件流且次数有限；跨多 worker 的 legacy session、requestState 和订阅需要外部 sticky/shared key/shared bus；外部 `AsyncClient` 的关闭由调用方负责；同步工具取消只保证调用方和协议层收口，不保证底层函数立刻终止。

**不可宣称：** SDK 提供通用业务重试、幂等提交、远端执行确认、跨进程 session store、生产级连接限制、强制停止任意同步/第三方函数，或当前核对已完成真实网络、Windows、外部 OAuth/代理和完整 conformance 验证。

当前核对唯一修改为目标项目根 `ARCHITECTURE.md`；未修改源码、测试、配置、依赖、锁文件、README 或其他参考库文件。
