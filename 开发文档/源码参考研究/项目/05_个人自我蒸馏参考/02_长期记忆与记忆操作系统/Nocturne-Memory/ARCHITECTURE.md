# Nocturne-Memory 架构建档

> 本文是本仓库唯一正式架构文档，按当前源码建立，不把 README 或设计宣传当作实现证明。
> 本文已吸收此前 `细探-Nocturne-Memory.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 1. 项目定位

Nocturne Memory 是一个**独立于 LLM 的 MCP 长期记忆服务器**：通过标准 Model Context Protocol 为 MCP 客户端提供跨会话、跨模型的记忆读写；通过 URI 路由把记忆组织成树状入口，并在后端以 Node–Memory–Edge–Path 图拓扑保存别名、版本与关系；通过 React Dashboard 供人类浏览、审核、回滚和维护。

仓库 README 的三组件定位与源码一致：

- **Backend**：Python/FastAPI/SQLAlchemy，负责数据库、图业务、REST API、快照与迁移。
- **AI Interface**：`backend/mcp_server.py` 暴露 MCP 工具，支持 stdio；`backend/run_sse.py` 组装 SSE 与 Streamable HTTP。
- **Human Interface**：`frontend/` 的 React/Vite/Tailwind SPA，由同一 Web 应用托管或由 Nginx 提供静态文件。

系统不是向量语义检索服务：当前检索是 SQLite FTS5 或 PostgreSQL `tsvector` 的词法全文检索，中文查询在应用层经 `jieba` 分词；Glossary 使用 Aho–Corasick 做关键词命中与跨节点链接。

## 2. 文本流程图

### 2.1 运行时总链路

```text
MCP 客户端
  ├─ stdio: python backend/mcp_server.py
  ├─ SSE:   GET /sse + POST /messages/
  └─ HTTP:  /mcp (Streamable HTTP)
          │
          ▼
  FastMCP 工具层: backend/mcp_server.py
  ├─ URI 解析 / system:// 特殊视图
  ├─ Namespace 当前上下文
  ├─ read_memory / search_memory
  └─ create / update / delete / alias / trigger（PUBLIC_READONLY_MCP 时不注册写工具）
          │
          ├────────────── stdio lifespan ───────────────┐
          │                                               │
          ▼                                               ▼
  system_views.py                                      web_app.py
  boot/index/recent/glossary/diagnostic                 FastAPI + Starlette SPA
                                                          │
                     ┌────────────────────────────────────┘
                     ▼
  中间件链（请求进入顺序）: CORS → Namespace → Locale → BearerTokenAuth
          │
          ▼
  REST Router (/api)
  browse / review / maintenance / settings / presets / health
          │
          ▼
  DB 服务门面 backend/db/__init__.py（懒加载、共享一个 DatabaseManager）
  ├─ GraphService       图拓扑、记忆 CRUD、版本链、别名、GC
  ├─ SearchIndexer      派生搜索文档、FTS 查询
  ├─ GlossaryService    关键词绑定、Aho–Corasick 扫描
  └─ PresetService      Boot URI preset
          │
          ▼
  DatabaseManager（Async SQLAlchemy）
  ├─ SQLite + aiosqlite（本地默认，WAL/外键/忙等待）
  └─ PostgreSQL + asyncpg（Docker/远程）
          │
          ├─ 业务表: nodes / memories / edges / paths / glossary_keywords
          ├─ 派生表: search_documents (+ SQLite search_documents_fts)
          ├─ 运维表: memory_access_logs / presets / schema_migrations
          └─ 文件状态: snapshots/changeset.json（AI 变更审核池）
```

### 2.2 写入与审核链

```text
MCP 写工具
  → GraphService / GlossaryService 事务
  → 业务表变更 + 搜索索引刷新
  → mcp_server._record_rows(before, after)
  → ChangesetStore（文件锁 + changeset.json，冻结 before、覆盖 after）
  → REST /review/groups
       ├─ DELETE /review/groups/{node_uuid}: 接受并清除审核记录，不改数据库
       └─ POST   /review/groups/{node_uuid}/rollback: 逆序恢复路径/边/旧 Memory/关键词，再重建索引

Dashboard 直接编辑（browse/settings/maintenance）
  → 直接调用服务
  → 源码明确标注为 human-facing direct edit，通常绕过 AI changeset 审核池
```

## 3. 真实分层与目录地图

```text
Nocturne-Memory/
├── backend/                         Python 后端
│   ├── mcp_server.py                FastMCP 定义、工具、stdio lifespan
│   ├── mcp_wrapper.py               Windows/Antigravity 子进程转发包装
│   ├── run_sse.py                   SSE + Streamable HTTP + REST + SPA 统一入口
│   ├── main.py                      REST/API + SPA 的 uvicorn 入口
│   ├── web_app.py                   ASGI 构造、路由挂载、中间件与静态回退
│   ├── config.py                    config.json 单一配置源、首次迁移与默认值
│   ├── auth.py                      Bearer、CORS、网络暴露保护
│   ├── namespace_middleware.py      HTTP/SSE namespace 提取与 session 传递
│   ├── system_views.py              system:// 文本视图
│   ├── text_patch.py                update_memory 的安全/模糊补丁匹配
│   ├── api/                         REST 路由层
│   ├── db/                          数据库、领域服务、迁移与快照
│   ├── models/                      REST 请求/响应 Pydantic schema
│   ├── locales/                     中英文后端消息与 Locale middleware
│   ├── health.py                    健康检查
│   └── tests/                       pytest 分层测试
├── frontend/                        React 管理 Dashboard
│   ├── src/App.jsx                  路由、认证探测、namespace 选择器、布局
│   ├── src/lib/api.js               Axios API client、Bearer/X-Namespace 拦截器
│   ├── src/features/memory/         Memory Browser
│   ├── src/features/review/         审核/回滚页面
│   ├── src/features/maintenance/    孤儿、日志、bloat 维护页面
│   ├── src/features/settings/       配置、数据库、Boot URI、preset UI
│   └── vite.config.js               Vite dev proxy 与 Vitest jsdom 配置
├── scripts/setup_docker.py          生成 .env/config.json 的 Docker 初始化 CLI
├── backend/scripts/                 Neo4j → SQLite 旧版迁移 CLI
├── desktop_pet/                     独立桌面宠物/heartbeat 辅助程序，不是记忆核心链路
├── docs/                            testing、MCP 工具、system prompt、审计 skill、图片
├── docker-compose.yml                postgres + backend + nginx 编排
└── ARCHITECTURE.md                   本正式架构文档
```

## 4. 核心入口与启动方式

### 4.1 MCP stdio

- `backend/mcp_server.py`：导入 FastMCP，定义 `lifespan` 与工具；启动时确保 `config.json`、初始化数据库、自动把旧配置 Boot URI 晋升到 `presets`，后台触发前端构建；stdio 模式还嵌入一个本地 Web 管理服务。
- 末尾 `mcp.run()` 是直接运行入口。
- `backend/mcp_wrapper.py`：启动真正的 `mcp_server.py` 子进程，按字节双向转发 stdin/stdout，并过滤 stdout 中的 `\r`；面向 Antigravity/Windows 兼容场景。

典型配置指向 `backend/mcp_server.py`；若客户端需要包装器，则指向 `backend/mcp_wrapper.py`。当前仓库没有独立打包的 Python/TypeScript SDK。

### 4.2 网络服务

- `backend/run_sse.py`：设置 `_NOCTURNE_SSE_MODE`，创建 FastMCP 的 SSE 与 Streamable HTTP ASGI routes，和 REST/SPA 组合为一个 uvicorn 应用。有效路径为 `/sse`、`/messages/`、`/mcp`、`/api/*`、`/`。
- `backend/main.py`：只构建统一 REST + SPA 应用；`python backend/main.py` 运行 uvicorn。`uvicorn main:app` 也可通过模块导入使用。
- `backend/web_app.py:build_web_app()`：FastAPI 实际挂在 Starlette 的 `/api` Mount 下，所以 FastAPI 文档实际地址为 `/api/docs`，OpenAPI 为 `/api/openapi.json`；`/health` 单独暴露且免鉴权。
- `frontend/` 开发模式：`npm run dev` 默认 `3000`，`/api` 代理到 `http://127.0.0.1:8233`，可用 `VITE_API_TARGET` 覆盖。

### 4.3 Docker

`docker-compose.yml` 定义三个服务：PostgreSQL 16、运行 `python run_sse.py` 的 backend、监听 80 的 Nginx frontend。Nginx 将 `/api/`、`/health`、`/mcp`、`/sse`、`/messages/` 反向代理到 backend，并关闭长连接流式响应缓冲。

## 5. 核心数据模型

### 5.1 图拓扑实体（`backend/db/models.py`）

| 模型/表 | 关键字段 | 真实职责 |
|---|---|---|
| `Node` / `nodes` | `uuid` PK、`created_at`、`last_accessed_at` | 概念身份锚点；内容更新不换 UUID。固定 `ROOT_NODE_UUID` 作为顶层父节点。 |
| `Memory` / `memories` | `id` PK、`node_uuid`、`content`、`deprecated`、`migrated_to` | 同一 Node 的内容版本。更新插入新行，旧行 deprecated，并用 `migrated_to` 链接新版本。 |
| `Edge` / `edges` | `parent_uuid`、`child_uuid`、`name`、`priority`、`disclosure` | 有向父子关系及路径级元数据；父子 UUID 唯一。 |
| `Path` / `paths` | `(namespace, domain, path)` 复合 PK、`edge_id`、`node_uuid` | URI 路由/物化缓存；多个 Path 可指向同一 Node，构成 alias。源结构关系仍在 Edge。 |
| `GlossaryKeyword` / `glossary_keywords` | `keyword`、`node_uuid`、`namespace` | 关键词到 Node 的触发/链接绑定；三列组合唯一。 |
| `SearchDocument` / `search_documents` | `(namespace, domain, path)`、Node/Memory 引用、content、`search_terms`、priority | 从活动图状态派生的搜索文档，不是内容主存储。 |
| `MemoryAccessLog` / `memory_access_logs` | `node_uuid`、namespace、`accessed_at`、context | 记录 `read_memory` 访问并支撑 stale 诊断。 |
| `Preset` / `presets` | name、JSON `boot_uris`、`is_active`、`path_masks` | Boot URI 配置集合；数据库部分唯一索引保证最多一个活动 preset。 |

### 5.2 版本、别名与 GC 语义

1. `GraphService.create_memory()` 在一个事务中创建 Node、Memory、Edge、Path，并刷新搜索文档。
2. `update_memory()` 内容变化时在同一 `node_uuid` 下插入新 Memory；旧活动版本变为 `deprecated=True` 并指向新版本，Edge 元数据则直接更新。
3. `add_path()` 复用目标 Node，创建新的 Edge/Path，并递归级联后代路径；会做环检测。
4. `remove_path()` 删除指定 URI 子树前检查子节点是否会失去所有可达路径；有 surviving alias 时自动修复子路径，无可达路径时软 GC（保留 deprecated Memory）。
5. 人类维护接口可恢复孤儿、永久删除 deprecated Memory，并修复 `migrated_to` 链；活动 Memory 不允许直接永久删除。
6. `ChangeCollector`/`ChangesetStore` 对 Node、Memory（只保存指针，不保存正文）、Edge、Path、GlossaryKeyword 记录行级 before/after；磁盘文件使用 `filelock`。

### 5.3 Namespace 隔离

- stdio：`backend/db/namespace.py` 从 `NAMESPACE` 环境变量初始化 contextvar。
- HTTP：`NamespaceMiddleware` 优先读取 `X-Namespace`，其次读取 `?namespace=`；SSE 连接会把 namespace 与 `session_id` 暂存到临时目录，供 `/messages/` 恢复。
- `Path`、`SearchDocument`、`GlossaryKeyword` 的主键/查询包含 namespace；Graph/Search/Glossary 的正常调用均以 namespace 过滤。
- Dashboard 在 `frontend/src/App.jsx` 选择 namespace，`frontend/src/lib/api.js` 自动发送 `X-Namespace`。审核接口故意不附带当前 namespace，因为审核视图从全局 changeset 汇总。
- `_RESERVED_NAMESPACES` 中的 `_ns_default_0x7f3a9e` 是前端空 namespace URL 的哨兵值，不可作为用户 namespace。

## 6. 核心服务与数据流

### 6.1 服务装配

`backend/db/__init__.py:_ensure_initialized()` 按以下顺序懒加载单例服务：

```text
config.get(database_url)
  → DatabaseManager(engine/session/migration)
  → SearchIndexer(db)
  → GlossaryService(db, search)
  → GraphService(db, search)
  → PresetService(db)
```

`DatabaseManager.session()` 负责 commit；异常 rollback。SQLite 连接启用 foreign keys、WAL、busy timeout、NORMAL synchronous；PostgreSQL 配置 pool、pre-ping、远端默认 SSL require（显式 disable 除外）。

### 6.2 读记忆

`mcp_server.read_memory(uri)` 先拦截特殊 URI：

- `system://boot`：从活动 preset 获取当前 namespace 的 Boot URIs，逐条经 `system_views.generate_boot_memory_view()` 读取。
- `system://index/<domain>`：`generate_memory_index_view()` 按域生成每个 Node 的主路径索引，并提醒 alias/trigger 可能被折叠。
- `system://recent[/N]`：按活动 Memory 的 `created_at` 倒序返回最近记录。
- `system://glossary`：输出关键词与节点 URI 映射。
- `system://diagnostic/<domain>`：生成 stale、crowded、orphan、duplicate alias、bloated memory 报告。
- 普通 URI：`parse_uri()` → `GraphService.get_memory_by_path()` → 子节点、priority、disclosure、alias 数、Glossary 命中格式化；`track_access=True` 时异步写访问日志。

### 6.3 写记忆

- `create_memory(parent_uri, content, priority, disclosure, title?)`：校验 URI/domain/title/disclosure，调用 `GraphService.create_memory()`。
- `update_memory(uri, old_string/new_string | append, priority, disclosure)`：只允许精确替换、`...` 块替换或追加，不允许全量覆盖；`text_patch.py` 提供 Unicode/空白归一化回退，但多匹配会拒绝。
- `delete_memory(uri)`：删除 URI 路径，不直接等同于删除 Node 内容；GraphService 负责子树、孤儿保护与软 GC。
- `add_alias(new_uri, target_uri, priority, disclosure)`：复用同一 Node，级联后代 Path。
- `manage_triggers(uri, add, remove)`：写 GlossaryKeyword；同一 Node 的 alias 共享节点级 trigger。
- 每个 MCP 写入口把服务返回的行状态送入 `_record_rows()`，进入审核池；`PUBLIC_READONLY_MCP=true` 时 `write_tool()` 不向 FastMCP 注册写工具。

### 6.4 搜索与 Glossary

`GraphService` 的每次创建/更新/别名/路径变化会调用 `SearchIndexer.refresh_search_documents_for_node()`，先从活动 Graph 重建派生行，再写 SQLite FTS5 或 PostgreSQL 查询所需字段。

`SearchIndexer.search()`：

- `expand_query_terms()` 用 `SearchTokenizer`、`jieba` 处理中文和 URI 分隔符；
- SQLite 生成保守的 FTS5 `MATCH`，以 `bm25`、priority、路径长度排序；
- PostgreSQL 使用 `websearch_to_tsquery('simple', ...)` 与 `ts_rank_cd`；
- 结果按 `node_uuid` 去重，再生成 snippet。

`GlossaryService` 使用行数/max id/max created_at 指纹懒重建 Aho–Corasick 自动机；扫描正文命中关键词后，仅返回当前 namespace 可见的目标 Node/URI。

### 6.5 Boot preset 与配置

`backend/config.py` 的正式配置源是根目录 `config.json`；首次启动可从旧 `.env` 或相关环境变量构建，之后读取 config。`PresetService.auto_promote_from_config()` 在 `presets` 为空时将旧 `boot_uris` 写成活动 `default` preset。Settings API 后续优先修改活动 preset 中的 Boot URI，其他设置仍写 config.json。

## 7. REST API / MCP / CLI / SDK

### 7.1 REST API（统一前缀 `/api`）

FastAPI 路由在 `backend/web_app.py` 注册；实际公开前缀为 `/api`。主要资源如下：

| 路由组 | 代表端点 | 用途 |
|---|---|---|
| health | `GET /health`（不在 `/api`） | DB `SELECT 1` 健康状态；连通为 200，否则 503。 |
| browse | `GET /api/browse/node`、`PUT/POST/DELETE /api/browse/node` | 树浏览、直接编辑、创建、删除。 |
| browse | `POST /api/browse/node/alias`、`POST /api/browse/node/rename` | 别名和重命名；重命名是 add-path 后 remove-path，并有尽力回滚。 |
| browse | `GET /api/browse/search`、`GET /api/browse/glossary` | FTS 搜索、Glossary 管理。 |
| browse | `GET /api/browse/domains`、`POST/DELETE /api/browse/domains`、`GET /api/browse/namespaces` | 域和 namespace 管理。 |
| review | `GET /api/review/groups`、`GET /api/review/groups/{node_uuid}/diff` | 行级变更按因果锚点分组并计算 before/current diff。 |
| review | `POST /api/review/groups/{node_uuid}/rollback`、`DELETE /api/review/groups/{node_uuid}`、`DELETE /api/review` | 回滚、接受单组、接受全部。另有 deprecated 列表/永久删除和文本 diff。 |
| maintenance | `GET/DELETE /api/maintenance/orphans[/{memory_id}]`、`POST .../restore` | 孤儿/历史版本查看、恢复、永久删除。 |
| maintenance | `GET /api/maintenance/access-logs/stats`、`DELETE /api/maintenance/access-logs` | 访问日志统计与清理。 |
| settings | `GET/PUT /api/settings` | config.json 设置读写、鉴权与网络暴露校验。 |
| settings | `/api/settings/boot-uris*`、`/api/settings/database/*` | Boot URI、namespace 覆盖、数据库测试/创建/状态/打开目录。 |
| presets | `GET/POST /api/presets`、`GET/PUT/DELETE /api/presets/{id}` | preset CRUD。 |
| presets | `POST /api/presets/{id}/activate`、`/duplicate` | 切换活动 preset、复制 preset。 |

鉴权由 `BearerTokenAuthMiddleware` 统一执行：未设置 token 时允许访问；设置 token 后除 `/health` 外要求 `Authorization: Bearer ...`。非 localhost host 在无 token 时启动即拒绝；token 少于 32 字符也拒绝。

### 7.2 MCP 工具

实际定义在 `backend/mcp_server.py`，共 7 个核心工具：

1. `read_memory(uri)`
2. `create_memory(parent_uri, content, priority, disclosure, title?)`
3. `update_memory(uri, old_string?, new_string?, append?, priority?, disclosure?)`
4. `delete_memory(uri)`
5. `add_alias(new_uri, target_uri, priority, disclosure)`
6. `manage_triggers(uri, add?, remove?)`
7. `search_memory(query, domain?, limit?)`

参数和示例的对外说明位于 `docs/TOOLS.md`；工具 docstring 是客户端发现参数语义的运行时来源。

### 7.3 CLI 与运维脚本

源码中可确认的命令入口：

```text
python backend/mcp_server.py                 stdio MCP + 本地嵌入 Dashboard
python backend/run_sse.py                   SSE/Streamable HTTP + REST + Dashboard
python backend/main.py                       REST + Dashboard
python backend/mcp_wrapper.py               Windows/Antigravity MCP 转发
python scripts/setup_docker.py [--port N]    生成 Docker .env/config.json
python -m scripts.migrate_neo4j_to_sqlite    旧 Neo4j → SQLite（需额外 neo4j 驱动、人工确认）
cd frontend && npm run dev|build|test:run    前端开发、构建、Vitest
pytest backend/tests                      后端测试（由 pytest.ini 指定）
```

`desktop_pet/` 下的 heartbeat 脚本属于旁路桌面自动化：`heartbeat_engine.py` 组装提示词、可选截图、邮件探测和 `[speak]` TTS，不被 Backend/MCP/REST 核心入口导入。

### 7.4 SDK 状态

未发现独立发布包、客户端 SDK 目录或稳定的 Python/TypeScript SDK API。对外集成面是：

- MCP stdio 配置；
- MCP SSE `/sse` + `/messages/`；
- Streamable HTTP `/mcp`；
- REST/OpenAPI `/api/docs` 与 `/api/openapi.json`。

## 8. 技术栈与依赖

| 层 | 实际技术 |
|---|---|
| 语言/运行时 | Python 3.10+；Node.js（前端构建） |
| MCP | `mcp`、FastMCP；stdio、SSE、Streamable HTTP |
| Web | FastAPI、Starlette、Uvicorn、CORS middleware |
| 数据访问 | SQLAlchemy 2 async、`aiosqlite`、`asyncpg` |
| 数据库 | SQLite（默认/本地）或 PostgreSQL（远程/Docker） |
| 搜索/文本 | SQLite FTS5、PostgreSQL tsvector/Gin、`jieba`、`pyahocorasick`、`diff_match_patch` |
| 状态/并发 | `filelock` 保护 changeset JSON；SQLite WAL/busy timeout |
| 配置/校验 | config.json、python-dotenv、Pydantic、pydantic-settings |
| 前端 | React 18、React Router 6、Axios、Vite 7、TailwindCSS 3、i18next、React Markdown、Vitest、Testing Library、jsdom |
| 部署 | Docker Compose、PostgreSQL 16 Alpine、Nginx |
| 可选旁路 | desktop_pet：edge-tts、pyttsx3、mss、websockets、python-dotenv |

后端依赖清单：`backend/requirements.txt`、`backend/requirements-dev.txt`；前端锁定清单：`frontend/package.json`、`frontend/package-lock.json`。

## 9. 数据库迁移与持久化边界

- `DatabaseManager.init_db()`：若无 `memories` 表，先 `Base.metadata.create_all`，再调用 `db/migrations/runner.py:run_migrations()`。
- 迁移 runner 按文件名排序发现 `001_...` 至 `014_...`，在 `schema_migrations` 记录已执行文件名；SQLite 待迁移前复制 `.bak`，PostgreSQL 优先 `pg_dump`，缺失时降级为 JSON 数据导出并警告结构无法自动恢复。
- 迁移重点包括 `migrated_to`、图字段、SQLite/Postgres FTS、namespace、Glossary namespace、access logs、Path node UUID、Preset 表。现有迁移文件是运行时 schema 事实的一部分，不能只看 ORM。
- `snapshots/changeset.json` 是审核工作状态，不是数据库历史事件表；内容正文通过 Memory ID 在 review 时回查数据库。
- 根目录 `config.json`、`.env`、前端 `dist/` 在当前归档中未找到；它们由首次启动/Docker setup/前端构建生成或由运行环境提供，未在当前核对生成。

## 10. 测试与验证面

### 10.1 后端

测试入口由 `pytest.ini` 指定为 `backend/tests`，asyncio mode 为 auto；测试依赖为 pytest、pytest-asyncio、pytest-cov。

- `backend/tests/unit/`：鉴权、快照 before/after、搜索词、locale。
- `backend/tests/service/`：GraphService CRUD/版本链/别名/GC、SearchIndexer、Glossary、namespace 隔离。
- `backend/tests/api/`：health、browse、review diff/rollback、maintenance、settings、preset API。
- `backend/tests/mcp/`：7 工具流、system views、触发词、patch/block match、namespace。
- `backend/tests/conftest.py`：默认 SQLite 临时库；设置 `TEST_DATABASE_URL` 时可切 PostgreSQL；每个 fixture 重建 DB 与 snapshot 目录，清空 API_TOKEN，并用 `ASGITransport` 测试 FastAPI。
- `.github/workflows/backend-tests.yml`：Python 3.10/3.12 SQLite 全套覆盖率；另用 PostgreSQL 16 跑 service/API smoke。

### 10.2 前端

- `frontend/src/i18n/i18n.test.js`：英文默认文案和中英文切换。
- `frontend/src/features/settings/MaintenanceSection.test.jsx`：bloat 阈值显示、校验、preset 选择与保存。
- `frontend/vite.config.js` 使用 jsdom、globals、`src/test/setup.js`；package scripts 提供 `vitest` 与 `vitest run`。

当前核对按用户约束**没有安装依赖、没有启动服务、没有运行测试或构建**，因此本文只记录源码声明与已有测试结构，不声称当前环境测试通过。

## 11. 未确认项与风险边界

1. **仓库规则文件缺失**：在项目根及项目内扫描未发现 `AGENTS.md`、`CLAUDE.md` 或 `GEMINI.md`；本建档依据 README、源码、依赖清单、测试与已有 `细探-Nocturne-Memory.md`。
2. **运行配置未落盘**：当前仓库没有 `config.json`、`.env`、`frontend/dist`；真实数据库 URL、token、Boot preset、构建产物和生产端口需在运行时确认。
3. **未做运行验证**：未安装 Python/Node 依赖，未连接 SQLite/PostgreSQL，未启动 uvicorn/MCP/Docker，未执行 pytest/Vitest；依赖可安装性、当前版本兼容性和迁移可执行性未被当前核对证明。
4. **声明与代码的集成边界需回归验证**：README 宣称 stdio/SSE/Streamable HTTP、SQLite/PostgreSQL 和前端自动构建，入口源码均存在，但不同 `mcp` 版本通过 `IS_MCP_V2` 分支选择 FastMCP API，真实环境仍需对应版本实测。
5. **审核池是文件状态**：`ChangesetStore` 使用共享的 `snapshots/changeset.json`，源码注释说明各 namespace 共享一个池；并发多进程、跨实例部署、文件卷权限和进程异常中断恢复未在当前核对实测。
6. **REST 直接编辑与 AI 审核语义不同**：`browse.py` 多处明确绕过 changeset/review，不能把所有 Dashboard 修改都理解为可在 Review 页面回滚的 AI 变更。
7. **迁移文件与 ORM 的最终一致性未实测**：源码同时存在 14 个历史迁移、SQLite/PostgreSQL 分支和当前 ORM；当前核对未执行迁移 round-trip，也未对空库/旧库/跨数据库结果做 schema 对账。
8. **旧 Neo4j 兼容链是旁路能力**：`backend/db/neo4j_client.py` 与 `backend/scripts/migrate_neo4j_to_sqlite.py` 仍存在，但 Neo4j 驱动不在正式 requirements，是否仍需维护取决于升级场景。
9. **桌面宠物不是核心服务依赖**：`desktop_pet/` 有独立环境和外部邮件/TTS/桌面截图依赖；当前核对只确认了共享 heartbeat 逻辑，未把它视为 Nocturne Memory 核心运行时的一部分。
10. **README 的“高可用/云同步”属于定位描述**：源码确认 SQLite/PostgreSQL 双后端和连接池，但没有在当前核对证明 HA、跨设备冲突处理、备份恢复演练或公网生产安全性。

## 12. 当前核对读取与修改边界

### 实际读取的代表性文件

- `README.md`、`README_EN.md`
- `backend/requirements.txt`、`backend/requirements-dev.txt`、`frontend/package.json`
- `backend/mcp_server.py`、`mcp_wrapper.py`、`run_sse.py`、`main.py`、`web_app.py`
- `backend/config.py`、`auth.py`、`namespace_middleware.py`、`system_views.py`、`text_patch.py`
- `backend/db/__init__.py`、`database.py`、`models.py`、`graph.py`、`search.py`、`search_terms.py`、`glossary.py`、`presets.py`、`snapshot.py`、`namespace.py`
- `backend/db/migrations/runner.py` 及 001–014 迁移清单中的关键迁移（009、010、014）
- `backend/api/__init__.py`、`browse.py`、`review.py`、`maintenance.py`、`settings.py`、`presets.py`、`health.py`
- `backend/models/__init__.py`、`schemas.py`
- `backend/tests/conftest.py`、Graph/MCP/API/namespace/snapshot 代表测试及全部测试文件清单
- `frontend/src/App.jsx`、`main.jsx`、`lib/api.js`、代表前端测试、`vite.config.js`、`nginx.conf`
- `docs/testing.md`、`docs/TOOLS.md`、`docker-compose.yml`、`.github/workflows/backend-tests.yml`
- `desktop_pet/requirements.txt`、`desktop_pet/heartbeat_engine.py`、`scripts/setup_docker.py`、旧 Neo4j 迁移脚本

### 当前核对修改文件

- 新增：`ARCHITECTURE.md`

- 未修改任何已有源码、依赖清单、测试、配置、数据库、构建产物或 Git 提交。

---

## 13. 后续：通用底座映射与治理裁决

### 13.1 证据边界与当前核对结论性质

本节是基于当前源码的后续映射，不是对 Nocturne-Memory 的改造方案，也不表示本项目已经接入任何外部支持库、记忆模块、运行核心或制品治理平台。源码参考库的固定边界仍然是：项目源码只读，跨项目结论只能作为底座升级输入，不能直接改生产底座。

- 项目身份现场核对：目标源码根为 `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Nocturne-Memory`。
- `project_context` 首次返回的是错误项目 `华世王镞_v3`，根目录为 `~/Documents/Agent/PHP/华世王镞_v3`，开工 id 为空；该 MCP 结果不作为 Nocturne-Memory 的项目证据。
- 随后对目标根调用代码图，返回“无 `.codegraph/` 目录，不能查询”；当前核对没有把代码图摘要冒充为源码证据，以下路径和行为均来自目标项目现场文件。
- 项目内未找到旧 `细探-*.md` 文件；现有本文第 4 行声明此前 `细探-Nocturne-Memory.md` 已吸收，但该旧文件当前不在目标目录，因而当前核对只能复核正式文档和当前源码，不能声称重新读取不存在的旧细探。
- 本节结论分为：**吸收**（可直接抽象为底座边界）、**升级候选**（有价值但需先登记需求/契约/租约/验收）、**待核**（当前缺运行或反向故障证据）、**隔离**（不能进入通用底座）。除“吸收”外均不构成生产改造授权。

### 13.2 唯一链路：内容、路径、版本、索引和审核各有唯一 owner

当前项目存在 MCP 写入口和 REST Dashboard 直接编辑两类入口；其中 `backend/api/browse.py` 明确把人类编辑标为绕过 changeset/review，MCP 写工具则在 GraphService 返回并完成数据库事务后调用 `_record_rows()`。因此，当前实现不是“所有写入天然走一条审核链”，而是**按入口分叉**。通用底座若吸收，必须在项目适配层收敛入口，不得把两条旁路照搬为第二套内核。

```text
MCP/REST/系统视图调用方
  → 项目适配层（解析 URI、namespace、权限、来源与版本绑定）
  → 记忆模块唯一公开能力入口
       ├─ memory.view / memory.search       → 视图编排、词法检索、Glossary
       ├─ memory.mutate                    → GraphService 事务内 CRUD/路径/版本
       └─ memory.review.rollback           → 变更集读取、审核、回滚、索引重建
  → 运行核心唯一资源边界
       ├─ AsyncSession：提交或 rollback
       ├─ 数据库连接池/SQLite WAL/锁等待
       ├─ FileLock：变更集互斥读写
       ├─ namespace/session/task 上下文
       └─ HTTP/SSE/子进程/后台任务生命周期
  → 支持库提供者
       ├─ SQLite/aiosqlite 或 PostgreSQL/asyncpg
       ├─ FTS5 或 PostgreSQL tsvector
       ├─ jieba / Aho–Corasick / 文本 patch
       └─ 文件锁与 JSON/快照存储
  → 制品治理
       ├─ before/after 变更集（待审核制品）
       ├─ 差异、审核接受、回滚证据
       └─ 派生 SearchDocument 重建与一致性检查
```

唯一 owner 裁决：

| 事实/资源 | 当前源码 owner | 通用底座归属 | 后续裁决 |
|---|---|---|---|
| 记忆正文和版本 | `GraphService` + `Memory`；同一 `node_uuid` 下以新 `Memory` 行版本化，旧行 `deprecated` 并用 `migrated_to` 指向后继 | 记忆模块的领域模型，底层存储由支持库承载 | **吸收**；只抽象版本契约，不把 `Memory` ORM 直接外泄给消费者 |
| 父子结构 | `Edge` 是真实结构，`Path` 是 URI 物化路由；`add_path()` 复用 Node 并级联子路径 | 记忆模块；路径物化可由支持库提供原子能力 | **吸收**；Edge 是权威写 owner，Path/SearchDocument 不能反向成为主事实 |
| 访问入口 | `Path(namespace, domain, path)` 复合主键；同一 Node 可有多个 alias | 记忆模块的 URI/namespace 适配层 | **吸收**；alias 是引用，不得复制正文或生成第二 Node |
| 检索索引 | `SearchIndexer` 维护 `search_documents` 和 SQLite FTS5；正文、Path、disclosure、Glossary 共同生成派生行 | 支持库检索 provider + 记忆模块查询语义 | **吸收但升级契约**；明确“派生、可重建、不可作为事实源” |
| 关键词横向召回 | `GlossaryService` 的 DB 指纹 + Aho–Corasick 自动机 | 支持库文本索引/匹配原子能力，绑定语义仍归记忆模块 | **升级候选**；当前自动机是进程内缓存，不是跨实例共享句柄 |
| 变更集 | `ChangesetStore` 单个 `snapshots/changeset.json`，`ChangeCollector` 收集行级 before/after | 制品治理的 pending changeset；FileLock/JSON 属支持库 | **升级候选**；不是数据库事件表，不能当审计历史或发布制品 |
| 审核/回滚 | `backend/api/review.py` 按因果锚点按 Node 分组；接受只清变更集，回滚恢复路径/边/旧 Memory/关键词并重建索引 | 制品治理编排器调用记忆模块恢复能力 | **吸收模式，待补证据**；需要操作 id、操作者、幂等键、版本冲突和回滚证据 |
| namespace/session | `contextvars`、`X-Namespace`/query、SSE 临时文件映射 `session_id→namespace` | 运行核心上下文边界 | **升级候选**；当前只有 namespace，没有通用 task/resource handle 或租约 |
| 数据库事务/连接 | `DatabaseManager.session()` 成功 commit、异常 rollback；`close()` 调 `engine.dispose()` | 运行核心资源协调 + 存储支持库 | **吸收**；事务必须成为唯一公开资源边界，不允许服务自行开第二会话语义 |
| 前端构建、访问日志等后台任务 | `asyncio.create_task()`；只有 `web_task` 被保留并在 lifespan 退出等待，构建、浏览器打开、`log_access` task 未统一登记 | 运行核心任务监督/取消/资源回收 | **升级候选**；不能把无句柄后台 task 当可靠任务系统 |

### 13.3 记忆视图、变更集、审核/回滚的底座落点

#### 13.3.1 记忆视图：领域编排留在记忆模块，通用格式化能力下沉支持库

`backend/system_views.py` 已形成五类真实视图：`system://boot` 读取活动 preset 的 Boot URIs 并逐条加载；`system://index/<domain>` 按 `(domain, node_uuid)` 折叠 alias 后只显示一条 primary path；`system://recent[/N]` 读取活动且有 Path 的最新 Memory；`system://glossary` 输出关键词绑定；`system://diagnostic/<domain>` 聚合 stale/crowded/orphan/duplicate alias/bloated 报告。普通 URI 则由 `fetch_and_format_memory()` 读取当前 Memory、子节点、priority、disclosure、alias 数、Glossary 命中，并可异步记访问日志。

映射规则：

1. `memory.view` 是唯一语义入口；Boot/index/recent/glossary/diagnostic 是同一入口下的 view type，不应在支持库和各消费者分别复制查询逻辑。
2. “一个 Node 多 Path、内容只有一份、Path 有自己的 priority/disclosure、子结构绑定 Edge”是应吸收的记忆模块契约；格式化标题、Markdown 文本拼接、snippet 截断属于可复用支持库能力，但不能携带 Nocturne 的业务判断。
3. `system://index` 明确只展示一条 primary path 并警告 alias/trigger/隐藏子节点，不能把 index 视为完整快照；通用上下文装配器必须声明“摘要视图/完整视图”级别，不能静默把摘要当事实全集。
4. `system://boot` 对单 URI 失败会收集失败文本并继续其他 URI，结果仍返回 `Loaded: N/M`；这是**部分成功视图**，应在通用契约中保留逐项错误，而不是把整个 Boot 伪装成全成功。
5. `fetch_and_format_memory()` 对 Glossary 扫描异常直接 `except Exception: pass`，源码没有把该失败显式投影到结果。该行为可作为“展示增强失败不阻塞正文”的降级策略，但需在底座诊断中记录被抑制的异常，不能当作无故障。

#### 13.3.2 变更集：before 冻结、after 覆盖、净零清理

`ChangeCollector` 在 GraphService 删除路径、边、节点、Memory 和 Glossary 行前收集序列化状态；Memory 只存指针字段，不存正文。MCP 工具在 `create/update/delete/add_alias/manage_triggers` 完成后把 `rows_before/rows_after` 送入 `ChangesetStore`。`ChangesetStore.record_many()` 对同一主键第一次保存完整 before/after，后续只覆盖 after，保留最初 before；`_changed_rows()` 过滤 before==after；创建后删除的净零路径和关联新建行由 `_gc_noop_creates()` 清除。`get_snapshot_view()` 在同一 FileLock 内同时读全量行和 changed rows，避免两次读取之间被其他进程修改。

这部分应映射为：

- **记忆模块**只产生领域变更事实：哪些 Node/Memory/Edge/Path/Glossary 变化、哪些索引需要刷新。
- **支持库**提供序列化、主键规范化、JSON 编解码、文件锁、必要时的临时文件原子替换和摘要校验。
- **制品治理**持有不可变 `before`、当前 `after`、来源入口、namespace、操作/请求标识、schema 版本和状态（pending/approved/rolled_back/failed）。
- **运行核心**负责变更集写入与数据库提交之间的资源/事务编排，不能让工具函数自己决定“写库后是否记账”。

当前实现的关键边界必须保留：`snapshots/changeset.json` 是单池文件，源码注释明确所有 namespace 共享一个池；`_record_rows()` 的 docstring 虽称 namespace-specific store，但实际 `ChangesetStore` 没有 namespace 分池参数，且行键只把 namespace 纳入 Path/Glossary 复合主键。该不一致是后续需要登记的契约漂移，不能照搬为“审核隔离已完成”。

#### 13.3.3 审核/回滚：因果分组不是事件溯源

`review.py` 的 `_get_causal_anchors()` 从 row-level changeset 逆向追踪 paths→edges→nodes、GC Memory 和级联删除，把一个高层变更折叠为 Node group；`get_group_diff()` 通过 Memory ID 回查 live DB 正文，把 before 与当前数据库状态组成 diff。`approve_group()` 和 `clear_all()` 只删除变更集记录，不修改业务库；`rollback_group()` 则按“新路径先删、旧路径先恢复、边元数据恢复、旧 Memory 复活、Glossary 恢复、全量重建搜索索引”的顺序执行。

应吸收的通用模式：

- 以领域因果锚点把多表物理变化收敛成一个可审核组，避免只回滚一半造成图断裂。
- 恢复操作必须复用记忆模块的公开恢复能力（如 `restore_path()`、`rollback_to_memory()`），而不是在审核层直接构造第二套图规则。
- 回滚成功后才移除该 Node 的变更集键；任一恢复异常返回失败并保留 pending 记录。测试已覆盖旧 Memory 被永久 purge 后回滚失败且变更集仍存在。
- 回滚后必须重建派生搜索索引；SearchDocument 不是回滚的独立事实源。

必须升级或待核的边界：

1. 变更集只保存 Memory 指针，正文从 live DB 回查；旧版本一旦被 `permanently_delete_memory()` 清除，回滚不可完成，已有测试明确证明该失败语义。
2. 回滚没有显式 revision/CAS 条件；审核期间若有人再次直接编辑，回滚可能基于变化后的 live DB 做恢复。通用底座必须加“读取版本/变更集版本 → 回滚前 CAS → 冲突拒绝”。
3. `approve_group()` 是删除待审记录，非不可变审计事件；没有 actor、时间、请求 id、结果摘要、失败证据和保留策略。它只能映射为“接受 pending artifact”，不能当合规审计日志。
4. REST Dashboard 的 create/update/delete/alias/Glossary 操作不进入 AI changeset，故“人类直接编辑”和“AI 可回滚变更”是两个明确来源；平台若需要统一治理，必须用入口来源字段和显式策略选择，不得把人工操作默默塞进 AI 审核池。
5. `rollback_group()` 的异常处理返回 `success=False`，但没有独立 rollback failure artifact；生产底座需要把“拒绝/失败/部分恢复/索引重建失败”全部写入证据账本。

### 13.4 存储、检索、上下文与任务资源映射

#### 13.4.1 存储与检索

当前的事实/派生边界清晰：

```text
Memory.content + Node + Edge + Path + GlossaryKeyword
  └─ 权威业务事实（GraphService/GlossaryService 写入）
       → SearchIndexer._build_search_documents_for_node()
       → search_documents（派生关系行）
       → SQLite search_documents_fts 或 PostgreSQL tsvector 查询
       → node_uuid 去重、score/priority/path 长度排序、snippet 输出
```

- SQLite 默认打开 foreign keys、WAL、busy timeout=5000、NORMAL synchronous；PostgreSQL 使用 pool、pre-ping、pool recycle，并对远端连接默认要求 SSL（显式 disable 除外）。这些属于**存储支持库提供者契约**，不是记忆模块的业务规则。
- `DatabaseManager.session()` 是事务边界：正常退出 commit，异常 rollback；Graph/Glossary/Search 通过依赖注入共享同一 manager，但公开服务方法通常自行取得 session。
- `SearchIndexer.refresh_search_documents_for_node()` 先删指定 namespace 或全 namespace 的派生行，再插入当前可达 Path 的活动 Memory 文档；删除/更新/alias/Glossary 改动都触发刷新。
- SQLite FTS5 查询和 PostgreSQL `websearch_to_tsquery('simple')` 均为词法全文检索；`expand_query_terms()` 做中文/URI 词项扩展，当前没有向量 embedding、语义召回或跨索引一致性证明。
- `GlossaryService` 的 Aho–Corasick 自动机按 count/max id/max created_at 指纹懒重建，能观察到跨进程写入，但自动机本体仍是进程内缓存；这适合“可重建派生缓存”，不适合作为持久权威状态。

底座裁决：**吸收“权威事实→可重建索引→统一查询结果”的分层，升级为支持库检索 provider 契约**。契约至少要固定 namespace/domain 过滤、去重 key、排序稳定性、snippet 截断、空查询、索引缺失时的重建/降级、提供者不可用、超时和取消结果。Nocturne 当前没有这些超时/取消/提供者错误的统一协议，标为待核，不宣称已满足。

#### 13.4.2 上下文资源

当前上下文只有两类：

- `db.namespace` 用 `contextvars.ContextVar` 传递 namespace；stdio 从 `NAMESPACE` 环境变量初始化，HTTP/SSE 由 `NamespaceMiddleware` 从 `X-Namespace` 或 query 参数设置。
- SSE 旧传输的 GET `/sse` 会截获 FastMCP endpoint event，写入临时目录 `nocturne_sse_sessions/<session_id>`；POST `/messages/` 通过 session id 取回 namespace，流关闭时在 `more_body=False` 删除文件。

它们映射到运行核心的“请求上下文”而不是记忆模块的数据模型。唯一链路必须把 namespace 作为不可篡改的调用上下文传到 Graph/Search/Glossary/Changeset 分组，禁止消费者自行拼接过滤条件。需要注意：`review` 故意不附带当前 namespace，读取全局变更集并按 group 汇总；这不是普通 namespace 查询漏过滤，而是审核池的全局语义，底座契约需显式标注。

当前没有以下通用资源语义，均不能从源码推断为已实现：任务 id、调用句柄、资源 owner、租约截止、心跳续租、硬截止时间、幂等键、取消令牌、崩溃恢复 token、跨服务 trace id。若平台要承接“上下文和任务资源”，这些应由运行核心统一提供，记忆模块只消费只读上下文对象和受控资源句柄。

#### 13.4.3 任务与后台资源

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消/崩溃事实 | 归属裁决 |
|---|---|---|---|---|
| `AsyncSession`/连接池 | `DatabaseManager.session()`、SQLAlchemy engine | context manager commit/rollback；`close_db()` → `engine.dispose()` | 业务异常有 rollback；源码没有统一应用超时、取消统计或连接泄漏反向验证 | 运行核心资源边界 + 存储支持库 |
| SQLite WAL/忙等待 | engine connect event 设置 PRAGMA | 连接由 pool/engine 管理 | 只有 `busy_timeout=5000`；未见锁超时错误码、重试预算或崩溃残留对账 | 支持库 provider，待补运行核心监督 |
| `FileLock` | `ChangesetStore` 构造 `changeset.json.lock`，record/get/remove 在 `with self._lock` 内 | 离开 with 释放进程锁；JSON 文件按 pending 状态保留或删除 | 未见超时参数、锁持有者、租约或损坏 JSON 恢复；进程崩溃后只依赖 OS/库释放锁，不能证明文件内容完整 | 支持库锁 + 制品治理，升级候选 |
| `changeset.json` | `_save()` 直接 `open(..., 'w')` 写 JSON | 净零/clear 时删除；否则保留 | 没有临时文件+原子 rename、checksum、schema 校验；写入中崩溃可能留下截断 JSON，启动 `_load()` 可能 JSON 解码失败 | 制品治理制品，必须补原子写/恢复 |
| SSE namespace 文件 | `FileSSESessionStore.__setitem__()` 写 temp 文件 | stream `more_body=False` 时 `pop()` 删除 | 断线/worker kill/宿主崩溃未见 TTL、扫描清理或 owner 校验；临时文件可能残留 | 运行核心上下文租约，当前仅部分实现 |
| FastMCP embedded web task | lifespan 创建 `web_task`，保存引用 | `finally` 设 `should_exit=True` 后 await | 启动异常有提示；没有显式超时/强杀，若 server 不退出，lifespan 收口可能等待无界 | 运行核心任务监督，升级候选 |
| 前端构建/自动开浏览器 task | `asyncio.create_task(_ensure_frontend_built())`、`create_task(_open_browser())`，不保存句柄 | 无统一 await/cancel/finally | 异常在后台 task 中不成为主启动失败；宿主取消/崩溃清理未定义 | 隔离为非核心旁路，或纳入任务监督后再吸收 |
| 访问日志 task | `fetch_and_format_memory(track_access=True)` 调 `asyncio.create_task(graph.log_access(...))` | 任务完成后 session context 结束 | 日志写入失败可能被后台任务吞掉；读取主响应不等待日志落账，不可作为强审计 | 记忆模块的 best-effort 派生 telemetry，不能当事务事实 |
| MCP wrapper 子进程/管道 | `subprocess.Popen` + stdin/stdout daemon threads | EOF 关闭 stdin，父进程 `wait()`，stdout thread 最多 join 1 秒 | 没有 wait timeout、进程组 kill、子进程崩溃证据或残留 pid 校验；仅 Windows/Antigravity 兼容旁路 | 隔离适配器；若生产化需运行核心监督 |

### 13.5 L0–L4 分层映射

源码 `backend/db/graph.py` 已用注释给出 Layer 0（Row-Level Primitives）、Layer 1（Table-Scoped Operations）、Layer 2（Cross-Table Cascades）、Layer 3（GC / Conditional Logic），再往后是 Public Write API。后续将其明确映射为 L0–L4；这不是新增代码层，而是把既有调用边界用于底座治理。

| 层级 | 当前真实职责与证据 | 建议底座归属 | 允许的输入/输出与边界 | 裁决 |
|---|---|---|---|---|
| **L0 原子事实** | `_ensure_node`、`_insert_memory`、`_get_or_create_edge`、`_insert_path`、`_resolve_path`、`serialize_row`、`serialize_memory_ref`；单行/单表，依赖传入 session，源码注释明确“不自行开启事务” | 支持库原子存储/序列化能力；少量 Node/Memory/Edge/Path 类型由记忆模块定义 | 输入显式 session/namespace/主键；输出领域行或稳定错误；不做 GC、审核、索引副作用 | **吸收**，但 ORM 不应穿透公共网关 |
| **L1 局部事务** | `_deprecate_node_memories`、`_safely_delete_memory`、`_get_subtree_path_rows`、`_cascade_create_paths` 等同表或紧邻表操作 | 记忆模块内部服务；事务仍由运行核心提供 | 在一个已持有 session 中执行；只能声明变更事实，不自行写 changeset；成功/异常由外层统一提交/回滚 | **吸收**，冻结“无第二事务”规则 |
| **L2 结构级联** | `_delete_subtree_paths`、`_cascade_delete_edge`、`cascade_delete_node`、`_create_edge_with_paths`；跨 Node/Memory/Edge/Path 多表确定性变更 | 记忆模块编排 + 运行核心事务监督；ChangeCollector 为制品治理输入 | 必须给出 affected rows、before/after 和派生索引影响；顺序必须支持回滚（删子后父、恢复父后子） | **吸收模式，待故障验证** |
| **L3 条件治理** | `_would_create_cycle`、`_gc_edge_if_pathless`、`_gc_node_soft`、`remove_path` 的子节点可达性预检/repair/soft GC、`restore_path`、`rollback_to_memory` | 记忆模块策略 + 制品治理恢复编排；运行核心提供 CAS/锁/截止时间 | 条件拒绝也要有稳定错误和证据；回滚/GC 必须幂等、版本受保护、禁止跨 namespace 意外暴露 | **升级候选**；当前无 CAS/租约/冲突令牌 |
| **L4 公共能力与治理闭环** | MCP/REST 入口、URI special views、namespace middleware、DatabaseManager 生命周期、SearchIndexer、ChangesetStore、review API、前端展示 | 运行核心唯一入口 + 记忆模块 + 支持库 provider + 制品治理 | 一个能力 id/一个 owner/一条注册调用链；请求上下文、资源句柄、审核状态、索引重建、失败证据必须完整贯通 | **待底座契约确认**；当前实现入口分叉、审核池单文件、任务监督不完整 |

L0–L4 不等于“越高层越能直接访问数据库”：L4 只能编排 L3/L2/L1/L0，不能越过唯一入口旁路写 DB；SearchDocument、system view 和 changeset 都不能反向成为 L0 事实源。

### 13.6 失败、超时、取消、崩溃与释放矩阵

| 场景 | 当前可确认行为 | 当前不能确认/缺口 | 底座验收要求 |
|---|---|---|---|
| 正常完成 | Graph/Glossary/Search 在 `DatabaseManager.session()` 中完成并 commit；MCP 返回后才记录 changeset；FileLock 离开上下文释放；lifespan 退出等待 `web_task` 并关闭 DB | 没有真实运行当前核对证据 | 读回 DB、派生索引、变更集和资源现场；确认句柄/连接/task 数归零或有明确 owner |
| 业务失败/非法参数 | MCP 捕获 `ValueError/Exception` 返回 `Error:`；REST 多数转 422；session context 对 `Exception` rollback；删除会在子节点不可达时预检拒绝 | MCP 写入后 `_record_rows()` 失败的补偿未实现；REST 直接编辑失败/成功都不进入 AI changeset | 失败码稳定、拒绝写证据、数据库与审核制品不出现半状态；测试 record 失败、索引刷新失败、唯一键冲突 |
| 存储锁/慢操作 | SQLite 配置 busy timeout 5000ms；迁移前 SQLite 备份，PostgreSQL 缺 `pg_dump` 时等待 10 秒再 JSON 数据导出 | 没有统一 `TIMEOUT` 结果、重试预算、取消 token；PostgreSQL JSON 备份明确不含 schema 且没有自动 restore | 每个 provider 声明软超时/硬截止/可重试；超时后 rollback/interrupt/关闭连接并验证无锁残留 |
| 主动取消 | 源码没有 memory/changeset/API 取消接口，也没有取消令牌或 Future 状态 | 未定义取消时 session、FileLock、后台 task、SSE namespace 文件、子进程如何收口；`asyncio.create_task` 的取消不受统一监督 | 取消必须是可观测终态：停止后不提交新事实、释放句柄/租约、保留取消证据、重复取消幂等 |
| HTTP/SSE 断线 | SSE 在正常 `more_body=False` 时删除 session namespace 文件；messages 取不到映射时回退 header/query/空 namespace | 断线、worker kill、客户端异常关闭的文件清理未证；无 TTL/租约/owner，可能把错误请求落入默认 namespace | session handle 绑定 namespace/owner/过期时间；映射缺失应返回明确会话错误，不能静默降级到空 namespace |
| 进程崩溃/强杀 | DB 未提交事务通常由数据库/连接关闭处理，但源码未提供 Nocturne 级崩溃恢复；FileLock 不应永久持有 OS 锁 | `changeset.json` 直接覆盖写可能截断；SSE 临时文件、后台 task、wrapper 子进程无启动恢复/残留扫描；没有崩溃注入测试 | 通过独立进程强杀验证：数据库事务、changeset JSON、索引、session 文件、锁/子进程均可恢复或明确进入 failed artifact；禁止半激活/半审核 |
| 回滚中失败 | 旧 Memory 被 purge 时返回 `success=False`，数据库保持新版本，pending changeset 保留；回滚末尾才重建全量索引 | 回滚过程若在路径恢复一半后进程崩溃，未见事务级恢复标记/二阶恢复；搜索重建失败没有独立证据 | 回滚必须一个可恢复事务或持久状态机；每一步有 intent/commit marker，重启可继续或反向补偿，失败证据不可被 rollback 一起抹掉 |

当前源码中没有 `handle`、`lease`、`heartbeat`、`resource owner` 等定义；因此“句柄/租约”只能作为运行核心升级接口，不应在架构文档里把 `session_id`、Memory ID 或 FileLock 路径误称为通用租约。建议的最小语义是：

```text
资源申请 → 返回 (resource_handle, owner, namespace, expires_at, cancel_token)
  → 每次使用校验 owner/namespace/版本/租约
  → 成功提交或失败/取消/超时进入唯一终态
  → finally 释放；租约过期只可回收，不可复活
  → 崩溃恢复扫描死亡 owner，写回收证据并重建派生索引
```

### 13.7 复用、升级、隔离裁决与装配前置

| 能力 | 裁决 | 允许的底座动作 | 禁止动作/剩余风险 |
|---|---|---|---|
| Node/Memory/Edge/Path 的内容-路径分离、版本链、alias cascade、cycle/orphan 防护 | **吸收** | 进入记忆模块领域契约；保留 Memory ID/Node ID 与 Path 引用分离 | 不把 Nocturne ORM/SQLAlchemy model 直接当公共契约；跨项目字段需另行映射 |
| `system://` 五类视图、Boot preset、diagnostic | **升级现有模块** | 统一 `memory.view` 的 view type、摘要/完整级别和部分成功错误 | 不复制多个项目各自的 boot/index 查询器；Boot preset 与用户任务上下文仍需权限/租约契约 |
| FTS5/PostgreSQL lexical search、jieba、Aho–Corasick | **升级支持库 provider** | 定义词法检索、派生索引、可重建缓存和 provider unavailable/timeout 契约 | 不宣称语义搜索；不把进程内 automaton 当持久索引；中文分词版本兼容待实测 |
| `ChangesetStore` 行级 before/after、净零 GC、FileLock | **升级制品治理** | 先登记变更集 schema、原子写、摘要、恢复和审计状态机 | 当前单 JSON 池、无 actor/time/request/revision；不能直接用于跨实例生产审核 |
| review causal anchors、diff、rollback | **吸收模式并升级记忆模块/治理对接** | 用唯一 `memory.review.rollback` 编排能力；回滚调用领域恢复接口并写失败证据 | 当前 live DB 回查、无 CAS、旧 Memory 可被 purge、回滚中崩溃未验证 |
| namespace context 与 SSE session mapping | **升级运行核心上下文** | 统一 request context、owner、租约、TTL、取消和跨进程安全存储 | 当前映射缺失静默回退空 namespace；临时文件残留/错绑风险未解决 |
| AsyncSession、engine.dispose、web_task、后台 create_task | **升级运行核心资源监督** | 登记 task/connection/lock/child-process 句柄；正常/失败/取消/超时/崩溃四态收口 | 不把 untracked task 当完成；不把 wrapper wait 当强杀回收；不在记忆模块另建任务中心 |
| 人类 REST direct edit 旁路 | **隔离并显式标记来源** | 作为 human mutation 入口，通过统一能力网关选择“直写”或“纳入审核”策略 | 不能与 AI changeset 混为一谈；不能让消费者绕过唯一 owner 直接 DB 写入 |
| `desktop_pet/`、Neo4j 迁移脚本 | **隔离/待核** | 仅在另有需求和外部依赖契约时单独登记 | 不纳入记忆核心、上下文任务资源或通用底座主链；当前核对没有运行证据 |

装配前必须补齐的契约/工作包：

1. **需求登记**：明确要复用“内容-路径分离”“变更审核”“词法检索”中的哪一个能力，不以整个仓库为复用单元。
2. **能力搜索与唯一 owner**：搜索现有 `memory.view`、`memory.mutate`、`memory.search`、`memory.changeset`、`memory.rollback`、`runtime.resource` 能力；若命中，优先复用/升级，不新建同名链路。
3. **消费者契约**：固定 namespace、domain、URI、版本、错误码、可重试、超时、取消、幂等键、返回摘要/完整视图级别和资源释放责任。
4. **租约/占用**：对数据库会话、变更集、回滚组、SSE session、后台任务、索引重建声明 owner、expires_at、取消方式和死亡 owner 回收方式。
5. **验收契约**：正常写读、连续更新、alias cascade、跨 namespace、索引重建、审核接受、回滚、旧版本 purge 后失败、锁冲突、超时、取消、强杀恢复和 JSON 损坏恢复。
6. **装配计划**：顺序应为支持库存储/检索 provider → 运行核心 session/handle/lease → 记忆模块 Graph/View/Mutation → 制品治理 Changeset/Review/Rollback → 项目适配层 → MCP/REST 消费者；禁止先接 UI 再补底座。
7. **证据留存**：源码存在、测试存在、真实执行、故障注入、外部 PostgreSQL、跨进程/强杀、资源残留扫描必须分栏，不能用测试文件存在或历史 CI 声明替代。

当前核对最终裁决：Nocturne-Memory 最有价值的可吸收底座不是“一个 MCP 服务器”，而是**Node/Memory/Edge/Path 的内容-路径分离 + 版本化 Memory + 可重建检索派生物 + 行级 before/after 变更集 + 因果分组回滚**。但其审核池、后台 task、SSE 临时 session、直接 JSON 覆盖写和入口分叉仍缺统一句柄/租约、CAS、超时/取消、崩溃恢复与证据账本；在这些缺口补齐前只能作为“升级现有能力的源码证据”，不能直接升级生产底座。