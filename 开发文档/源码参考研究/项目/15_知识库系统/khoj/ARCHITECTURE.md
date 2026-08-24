# Khoj 架构建档

> 本文是对本地源码参考快照的前序研究全量架构建档。说明、备注、风险与结论使用中文；源码标识、包名、类名、函数名、路由与配置键保留原文。
>
> 目标目录：`/Users/hekunhua/Documents/Agent/github 源码参考/15_知识库系统/khoj`
>
> 建档范围：README、历史研究文件、构建与依赖清单、Python/TypeScript/JavaScript 入口、Django 数据模型与迁移、FastAPI 路由、处理器、检索链、客户端、文档、测试与 Docker 编排。没有安装依赖、启动服务、构建或修改源码/测试/配置。

## 1. 项目身份与版本基线

- 项目名：`khoj`；产品定位：`Your AI second brain`。
- 许可证：根 `pyproject.toml` 声明 `AGPL-3.0-or-later`；`src/interface/obsidian/package.json` 与 `src/interface/desktop/package.json` 各自声明 `GPL-3.0-or-later`，分发时应按组件边界核对许可证。
- 本地 Git：分支 `master`，HEAD `ae229ca894c0b80ad84664afcfdde523b5e87057`，提交时间 `2026-08-01T18:55:40-07:00`，提交说明 `Make chat export robust and fix export truncation (#1314)`。
- 远程 Git：`origin=https://github.com/khoj-ai/khoj.git`；远程 `HEAD`/`master` 与本地均为 `ae229ca894c0b80ad84664afcfdde523b5e87057`，`git rev-list --left-right --count HEAD...origin/master` 为 `0 0`。
- 远程独立快照：通过 `127.0.0.1:4780` 对远程提交的 `README.md`、`pyproject.toml`、`src/khoj/main.py`、`src/khoj/configure.py`、`src/khoj/database/models/__init__.py` 做了只读快照比对；这些抽查文件与本地内容相同。未把远程快照写回工作树，也未覆盖本地版本。
- 工作树基线：已有未跟踪文件 `历史研究-khoj.md`；该文件不是当前审计创建或修改。根目录未发现可作为仓库级开发指令的 `AGENTS.md`/`CLAUDE.md`；`documentation/docs/features/AGENTS.md` 实际是 Agents 文档页，不是额外工程规则文件。
- 本地历史研究：`历史研究-khoj.md` 已提供处理器、检索、Agent、自动化和客户端的初步导航；本文在源码核验后补充入口、数据关系、API、异步边界和风险。

### MCP 证据备注

本轮未调用任何 MCP；目标目录现有独立 `.codegraph/`，当前 `codegraph status` 报告索引 `up to date`。代码地图只用于目标仓库导航，本文事实以目标目录的只读文件、Git 版本信息、远程只读快照与现有 `历史研究-khoj.md` 为准。

```text
客户端(Web/Obsidian/Desktop/Emacs/Android)
  -> FastAPI/Starlette认证、HTTP/WebSocket与Django ASGI
  -> content processor读取/分块/嵌入
  -> PostgreSQL/Django ORM + pgvector索引
  -> bi-encoder召回 + cross-encoder重排
  -> Chat/Agent/工具/自动化调度
  -> 流式响应、会话持久化、遥测与失败清理
```

## 2. 一句话架构结论

Khoj 是一个以 **FastAPI/Starlette HTTP+WebSocket 接入层 + Django ORM/Admin/Session 数据层 + PostgreSQL/pgvector 向量存储 + processor 处理器链 + bi-encoder/cross-encoder 检索链 + 多模型对话/Agent/工具执行 + APScheduler 自动化** 为核心的单体应用，同时提供 Web、Obsidian、Desktop、Emacs、Android 等客户端，并通过 Docker Compose 组合数据库、沙箱、搜索引擎和计算机操作容器。

## 3. 总体数据与调用流

```text
客户端
  ├─ Web Next.js/React 静态产物
  ├─ Obsidian TypeScript 插件
  ├─ Desktop Electron
  ├─ Emacs 客户端
  └─ Android/TWA 外壳
        │ HTTP / WebSocket / Bearer / Session
        ▼
FastAPI app（khoj.main.app）
  ├─ AuthenticationMiddleware + SessionMiddleware + CORS/错误/断连/连接清理
  ├─ /api、/api/chat、/api/agents、/api/content、/api/memories、/api/model、/api/automation
  ├─ /auth（非 anonymous mode）与 Web 页面
  ├─ /server → Django ASGI application
  └─ /static → Web 编译产物与静态资源
        │
        ├─ 内容同步/转换
        │    configure_content → TextToEntries → 文档解析/分块/哈希
        │    → EmbeddingsModel → Entry/FileObject/EntryDates
        │
        ├─ 搜索/问答
        │    query → EmbeddingsModel.embed_query → EntryAdapters.search_with_embeddings
        │    → PostgreSQL CosineDistance → filters → CrossEncoderModel（可选重排）
        │    → SearchResponse / 对话上下文
        │
        ├─ 对话/Agent
        │    prompts + OpenAI/Anthropic/Google 对话处理器
        │    → tools（online_search/run_code/mcp）/operator（browser/computer）
        │    → HTTP 流式事件或 WebSocket 事件
        │
        └─ APScheduler/DjangoJobStore
             → automation、内容定期更新、telemetry、限流记录清理

Django ORM / PostgreSQL + pgvector
  ├─ 用户、会话、Agent、模型配置、订阅
  ├─ FileObject、Entry、UserMemory、EntryDates
  ├─ Notion/GitHub/MCP/WebScraper 配置
  ├─ ProcessLock、DjangoJob/DjangoJobExecution、限流记录
  └─ 迁移链（当前可见至 0099_usermemory）
```

## 4. 启动、装配与生命周期

### 4.1 Python 入口

- 包入口：`pyproject.toml` 的 `[project.scripts]`：`khoj = "khoj.main:run"`。
- 脚本入口：`src/khoj/main.py`，也支持 `python3 src/khoj/main.py --anonymous-mode`。
- Django 管理入口：`src/khoj/manage.py`，用于 `makemigrations`、`migrate`、`collectstatic` 等管理操作。
- ASGI 入口：`src/khoj/app/asgi.py`，Django 设置指向 `app.asgi.application`；FastAPI 进程在 `khoj.main` 内生成。

### 4.2 `khoj.main` 的启动顺序

`main.py` 在模块加载阶段即执行若干有副作用的初始化：

1. 设置 `DJANGO_SETTINGS_MODULE=khoj.app.settings` 并调用 `django.setup()`。
2. 建立 `RichHandler` 日志。
3. 调用 Django `migrate --noinput`。
4. 调用 Django `collectstatic --noinput`。
5. 按 `KHOJ_DEBUG` 选择 `FastAPI(debug=True)` 或关闭生产 Swagger 的 `FastAPI(docs_url=None)`。
6. 取得 Django ASGI application，挂载 CORS。
7. `run()` 解析 CLI，设置 `khoj.utils.state`，执行 `initialization()`。
8. 启动 `schedule` 轮询和 `BackgroundScheduler + DjangoJobStore`。
9. 通过 `ProcessLock.Operation.SCHEDULE_LEADER` 选举唯一调度领导者；非领导进程以 paused scheduler 运行。
10. `configure_routes(app)` 注册 API/Web 路由；挂载 `/server`、`/static`；配置认证、Session、HTTPS、断连、数据库连接清理和错误处理中间件。
11. `initialize_server()` 加载聊天客户端、搜索模型、默认 Agent 与内容初始化依赖。
12. 根据 CLI `host`、`port` 或 Unix socket 调用 `uvicorn.run`；退出时释放调度领导锁并关闭 scheduler。

这意味着命令行启动、Gunicorn 导入、测试中导入 `khoj.main` 都可能触发数据库迁移和静态文件收集；这是部署与测试隔离的关键注意事项。

### 4.3 `configure.py` 的装配职责

`src/khoj/configure.py` 是运行时装配中心，主要负责：

- `configure_routes`：延迟导入各 router，避免过早依赖未初始化的搜索类型。
- `configure_middleware`：安装 `SessionMiddleware`、`AuthenticationMiddleware`、`ServerErrorMiddleware`、`NextJsMiddleware`、`AsyncCloseConnectionsMiddleware`、`SuppressClientDisconnectMiddleware`，可选 `HTTPSRedirectMiddleware`。
- `UserAuthenticationBackend`：支持 Django Session、`Authorization: Bearer` 的 `KhojApiUser`、WhatsApp `client_id/client_secret + phone_number`、`anonymous_mode` 默认用户四类认证路径；已订阅用户额外获得 `premium` scope。
- `initialize_server`：读取/创建 `SearchModelConfig`，构造 `EmbeddingsModel` 与 `CrossEncoderModel`，设置动态 `SearchType`，建立默认 Agent。
- `initialize_content`：调用 `routers.api_content.configure_content` 更新用户知识库。
- 定时任务：内容更新、telemetry 上传、旧限流记录清理、scheduler 唤醒和领导锁续接。

## 5. 目录与模块地图

本地实际扫描到：`src` 约 505 个文件，`tests` 约 61 个文件，`documentation` 约 99 个文件。重点目录如下：

```text
khoj/
├── README.md                         # 产品定位、能力概览和入口链接
├── pyproject.toml                    # Python 包、依赖、脚本、pytest/ruff/mypy 配置
├── docker-compose.yml                # database/sandbox/search/computer/server 编排
├── prod.Dockerfile                   # 生产镜像
├── computer.Dockerfile               # computer operator 相关镜像
├── manifest.json / versions.json     # 项目与客户端版本元数据
├── 历史研究-khoj.md                       # 已有源码历史研究导航（非当前审计修改）
├── src/
│   ├── khoj/
│   │   ├── main.py                   # FastAPI + Django + scheduler 进程入口
│   │   ├── manage.py                 # Django 管理入口
│   │   ├── configure.py               # 路由/中间件/模型/内容/调度装配
│   │   ├── app/                      # Django settings/urls/asgi/admin 界面说明
│   │   ├── database/                 # Django app、models、adapters、migrations
│   │   ├── routers/                  # API、Web、auth、content、chat、Agent、automation
│   │   ├── processor/                # content/conversation/embeddings/image/speech/operator/tools
│   │   ├── search_type/              # text_search、检索排序与索引更新
│   │   ├── search_filter/            # date/file/word/base 过滤器
│   │   ├── interface/web/            # Django/FastAPI 服务的静态页面入口与资源
│   │   └── utils/                    # state、config、rawconfig、models、CLI、辅助函数
│   └── interface/
│       ├── web/                      # Next.js 15 + React 18 + TypeScript Web 客户端
│       ├── obsidian/                 # Obsidian TypeScript 插件
│       ├── desktop/                  # Electron/ToDesktop 桌面壳
│       ├── emacs/                    # Emacs 客户端（无 package.json，按源码/文档维护）
│       └── android/                  # Android/TWA 客户端外壳
├── tests/                            # pytest-django 测试、夹具、样例数据、评测
└── documentation/                    # Docusaurus 文档站点
```

### 各层边界

| 层 | 主要职责 | 关键文件/目录 |
|---|---|---|
| `app` | Django 项目配置、admin、ASGI、静态模板 | `src/khoj/app/settings.py`、`urls.py`、`asgi.py` |
| `database` | ORM 模型、查询适配器、事务/异步 ORM 包装、迁移 | `database/models/__init__.py`、`database/adapters/__init__.py`、`migrations/` |
| `routers` | HTTP/WebSocket 接口、认证 scope、输入/输出 DTO、调用处理器 | `api.py`、`api_chat.py`、`api_content.py`、`api_agents.py` 等 |
| `processor/content` | 多源文件解析、清洗、分块、转换为 `Entry` | `TextToEntries` 与 `*ToEntries` |
| `processor/conversation` | OpenAI/Anthropic/Google 对话、提示词、语音转写、流式输出 | `conversation/*`、`prompts.py` |
| `processor/operator` | Browser/Computer 操作环境与 Agent operator | `operator_environment_*`、`operator_agent_*` |
| `processor/tools` | 在线搜索、沙箱代码执行、MCP 工具 | `online_search.py`、`run_code.py`、`mcp.py` |
| `processor/embeddings` | 本地 SentenceTransformer、HuggingFace/OpenAI embedding、CrossEncoder | `embeddings.py` |
| `search_type` | 向量检索、过滤、重排、响应拼装、索引更新 | `text_search.py` |
| `search_filter` | 查询表达式中的日期、文件名、单词过滤 | `date_filter.py`、`file_filter.py`、`word_filter.py` |
| `utils` | 全局运行状态、CLI、配置、Pydantic 数据结构、序列化 | `state.py`、`rawconfig.py`、`models.py` |

## 6. 数据模型与持久化

### 6.1 数据库基础

`src/khoj/app/settings.py` 将默认数据库配置为 PostgreSQL：

- `POSTGRES_DB` 默认 `khoj`；`POSTGRES_HOST` 默认 `localhost`；`POSTGRES_PORT` 默认 `5432`。
- `AUTH_USER_MODEL = "database.KhojUser"`。
- `pgvector.django.VectorField` 承载 `Entry.embeddings` 与 `UserMemory.embeddings`。
- `USE_EMBEDDED_DB=True` 时尝试使用 `pgserver`，并创建 `vector` 扩展；失败时记录错误并回到标准 PostgreSQL 配置。
- `CONN_MAX_AGE=0`、`CONN_HEALTH_CHECKS=True`，请求前后由 `AsyncCloseConnectionsMiddleware` 清理连接。
- 迁移文件编号已到 `0099_usermemory.py`，并存在多个 merge migration 分支，迁移历史是生产升级的重要边界。

### 6.2 模型分组

| 分组 | 模型 | 关系/用途 |
|---|---|---|
| 身份与客户端 | `KhojUser`、`GoogleUser`、`KhojApiUser`、`ClientApplication` | Django 用户、Google 身份、客户端 Bearer token、WhatsApp/一方客户端凭证 |
| 订阅与模型 | `Subscription`、`AiModelApi`、`ChatModel`、`VoiceModelOption`、`TextToImageModelConfig`、`SpeechToTextModelOptions` | 订阅状态、模型提供商凭证、聊天/语音/图像模型配置 |
| Agent 与对话 | `Agent`、`Conversation`、`PublicConversation`、`UserConversationConfig`、`UserVoiceModelConfig`、`UserTextToImageModelConfig` | Agent 人设/权限/模型/工具，私有与公开对话，用户模型选择 |
| 知识库 | `FileObject`、`Entry`、`EntryDates`、`UserMemory` | 原文件全文、分块文本与向量、日期倒排辅助、长期记忆向量 |
| 搜索配置 | `SearchModelConfig` | bi-encoder、cross-encoder、推理端点、编码配置、置信度阈值 |
| 外部数据源 | `NotionConfig`、`GithubConfig`、`GithubRepoConfig`、`WebScraper`、`McpServer` | Notion/GitHub 同步、网页抓取提供者、MCP server 配置 |
| 运行控制 | `ProcessLock`、`UserRequests`、`RateLimitRecord`、`DataStore` | 内容索引/定时领导锁、限流记录、通用 JSON KV |
| 管理/任务 | `ServerChatSettings`、Django APScheduler 模型 | 服务级模型槽位/记忆模式、自动化任务持久化 |

关键完整性规则：

- `Entry` 不能同时关联 `user` 与 `agent`；Agent 知识是从用户已有 `FileObject`/`Entry` 复制到 Agent 侧。
- `Conversation` 的 `conversation_log` 是 JSON，保存前通过 `ChatMessageModel`/`Context`/`Intent` 等 Pydantic 模型校验；`messages` 属性会清洗无效消息并跳过校验失败项。
- `Agent` 通过 `privacy_level`（`public`/`private`/`protected`）、`creator`、`managed_by_admin`、`is_hidden` 控制可见性；`verify_agent` 防止同一作用域的重复名称。
- `Entry` 的 `hashed_value` 用于增量索引；`corpus_id` 用于同源分块去重；`EntryDates` 支持日期过滤。
- `ProcessLock` 以唯一 `name` 防止多 worker 同时索引内容或运行调度任务，超时后可清理过期锁。
- `UserMemory` 按用户/Agent 持久化长期记忆，API 更新采用删除旧记录后重新保存的替换语义。

## 7. 内容摄取、解析与索引

### 7.1 输入类型

`api_content.IndexerInput` 明确支持：`org`、`markdown`、`pdf`、`plaintext`、`image`、`docx`。`Entry.EntryType` 还包括 `notion`、`github`、`conversation`；`EntrySource` 包括 `computer`、`notion`、`github`。

对应解析器位于 `processor/content/`：

- `plaintext/plaintext_to_entries.py`
- `markdown/markdown_to_entries.py`
- `org_mode/org_to_entries.py` 与 `orgnode.py`
- `pdf/pdf_to_entries.py`
- `docx/docx_to_entries.py`
- `images/image_to_entries.py`
- `notion/notion_to_entries.py`
- `github/github_to_entries.py`

### 7.2 索引主链

1. `PUT/PATCH /api/content` 接收 `UploadFile`，按扩展名/MIME 识别文件；`PUT` 表示重建，`PATCH` 表示增量同步。
2. `indexer()` 将文件分发到 `IndexerInput`，通过 event loop executor 调用 `configure_content`，避免阻塞 HTTP 事件循环。
3. 具体 `*ToEntries.process()` 读取内容并产生统一 `utils.rawconfig.Entry`。
4. `TextToEntries.split_entries_by_max_tokens()` 使用 `RecursiveCharacterTextSplitter`，优先按段落、换行、句子、单词、字符切分；清理长词、空字符，保留 heading 和 `file://#line=` 定位信息。
5. `update_embeddings()` 对编译文本计算 MD5 哈希，与数据库现有 `Entry.hashed_value` 对账；只为新增内容编码，并删除已不存在或明确删除的文件。
6. `EmbeddingsModel.embed_documents()` 使用本地 `SentenceTransformer` 或远程 HuggingFace/OpenAI endpoint 生成向量。
7. 批量写入 `Entry`，同时维护 `FileObject` 全文和 `EntryDates` 日期索引；成功后返回新增/删除统计。
8. Notion/GitHub 配置由 API 保存后异步触发对应内容同步；定时任务可对全部用户执行更新。

限制与行为：

- `/api/content` 入口使用 `ApiIndexedDataLimiter`；当前源码中普通用户单次/总量与订阅用户限额不同。
- `/api/content/convert` 单文件转换上限为 10 MB；索引接口的文件数量/大小限流由依赖组件处理，测试覆盖 1000 文件和大文件限流。
- 更换 bi-encoder 后需要重新索引全部文档；`SearchModelConfig.bi_encoder_confidence_threshold` 影响召回边界。
- PDF/DOCX 转换会先提取每页文本，再添加 `Page ...` 标注；这是转换 API 的文本协议，不等于保存原始二进制。

## 8. 检索、过滤与排序

### 8.1 召回

`search_type/text_search.py::query()` 的主路径为：

1. 将动态 `SearchType` 映射为 `Entry.EntryType`；支持 `all`、`org`、`markdown`、`plaintext`、`pdf`、`github`、`notion` 等。
2. 取得 `get_default_search_model()`，使用 `state.embeddings_model[model.name].embed_query()` 编码查询。
3. 调用 `EntryAdapters.search_with_embeddings()`，以 PostgreSQL `CosineDistance` 查找最多 10 个候选，并按用户/Agent、类型、`max_distance` 过滤。
4. `search_filter` 解析查询文本中的日期、文件、单词条件；过滤链与向量召回组合使用。
5. 如果调用方请求 rerank，或配置了 cross-encoder 推理端点且候选多于一个，则调用 `CrossEncoderModel.predict()` 重排。
6. `collate_results()` 按 `hashed_value`/`corpus_id` 去重，生成 `SearchResponse`，返回 `entry`、`score`、`corpus_id` 与 `additional.source/file/uri/compiled/heading`。

### 8.2 Embedding 提供者

- 本地：`SentenceTransformer`，默认 bi-encoder `thenlper/gte-small`，默认 cross-encoder `mixedbread-ai/mxbai-rerank-xsmall-v1`。
- HuggingFace：HTTP JSON endpoint，Bearer API key，带 `tenacity` 重试。
- OpenAI/兼容 API：`openai.OpenAI` embeddings endpoint。
- 运行设备由 `utils.helpers.get_device()` 决定并写入全局 `state.device`；模型实例放在全局 `state.embeddings_model`/`state.cross_encoder_model` 字典中。

## 9. 对话、Agent、工具与 Operator

### 9.1 对话

`routers/api_chat.py` 是规模最大的 API 模块之一，同时提供：

- `POST /api/chat`：普通请求/事件式响应。
- `GET /api/chat/ws`：WebSocket 对话通道。
- 对话历史、导出、会话、标题、消息删除、文件过滤器、公开分享/分叉、反馈、语音合成、聊天 starters 与统计。
- `MessageBuffer`、`event_generator`、`send_event`、`send_llm_response`、断连监控等流式/增量输出机制。

对话 processor 按提供商拆分：

- `processor/conversation/openai/`：GPT、Whisper 与 OpenAI 工具调用。
- `processor/conversation/anthropic/`：Anthropic chat。
- `processor/conversation/google/`：Gemini chat。
- `processor/conversation/prompts.py`：系统提示词、人设模板与操作模式相关提示词。
- `processor/conversation/utils.py`：消息清理、JSON 清理和共享辅助逻辑。

对话通常组合：用户查询 → 意图/命令解析 → 搜索上下文/在线上下文/代码上下文/Operator 上下文 → 选定 ChatModel/Agent → 供应商对话 API → 流式结果写回 `Conversation.conversation_log`。

`processor/conversation/prompts.py` 是提示词装配的集中位置：除默认 `personality`、`custom_personality`、`notes_conversation` 外，还定义图像/图表、代码执行、Operator、自动化调度与自动化结果格式化提示词。自动化链还使用 `crontime_prompt` 从自然语言推导 cron/query/subject，使用 `to_notify_or_not` 判断是否满足通知条件，再由 `automation_format_prompt` 生成适合邮件正文的 Markdown；这说明“Agent 人设/工具”与“自动化通知”都是对话层提示词契约，不是独立的模型微服务。

### 9.2 Agent

`Agent` 是配置而不是独立微服务，核心组成是：

- `personality`：系统提示/人设。
- `chat_model`：固定模型或默认动态模型。
- `input_tools`：`general`、`online`、`notes`、`webpage`、`code`。
- `output_modes`：`image`、`diagram`。
- `privacy_level`、`creator`、`managed_by_admin`、`is_hidden`：访问边界。
- 文件集合：从用户知识库复制 `FileObject`/`Entry`，形成 Agent 专属索引。

`api_agents` 在创建/更新 Agent 时通过 `acheck_if_safe_prompt` 检查人设安全性，并根据用户是否拥有 `premium` scope 选择允许的 ChatModel。默认 Agent 由 `AgentAdapters.create_default_agent()` 管理，默认 slug 为 `khoj`。

### 9.3 Tools 与 Operator

- `processor/tools/online_search.py`：在线搜索/网页读取能力，底层可对接 SearxNG、Firecrawl、Exa、Olostep 等。
- `processor/tools/run_code.py`：将代码执行交给 Terrarium 或 E2B；Docker Compose 默认提供 `sandbox`。
- `processor/tools/mcp.py`：MCP server 配置/调用边界，数据库模型为 `McpServer`。
- `processor/operator/`：实验性 Computer/Browser 操作环境、Anthropic VLM operator、研究模式；Docker Compose 中的 `computer` 容器提供可控桌面，并可选挂载 Docker socket。

Operator 是高风险边界：它具备截图、点击、输入、文件操作、终端和网页浏览能力，生产部署应显式启用并隔离其容器、凭证和 Docker socket。

### 9.4 自动化、Newsletter 与通知

自动化不是单独的进程，而是 `APScheduler`/`DjangoJobStore` 中的用户任务：`routers/api_automation.py` 提供创建、编辑、删除、查询和手动触发接口，创建时校验 cron、补齐 `/automated_task` 查询前缀、创建关联 `Conversation`，并通过 `schedule_automation` 注册任务；手动触发会在独立线程中执行任务函数。仓库文档将执行结果定义为发往用户收件箱的邮件，并举例说明 custom newsletters、新闻摘要和事件通知（`documentation/docs/features/automations.md`）。因此历史研究所称“自动化 = newsletter/通知”可以吸收为产品行为描述，但邮件服务配置、真实投递、失败重试和端到端送达当前审计未运行验证。

## 10. API 与客户端契约地图

### 10.1 路由装配

`configure_routes(app)` 当前注册：

| FastAPI prefix | Router | 主要能力 |
|---|---|---|
| `/api` | `api` | search、update、transcribe、settings、user、health、token 生命周期相关通用 API |
| `/api/chat` | `api_chat` | POST chat、WebSocket `/ws`、历史、会话、分享、标题、反馈、语音 |
| `/api/agents` | `api_agents` | Agent 查询、创建、更新、删除、隐藏 Agent |
| `/api/automation` | `api_automation` | APScheduler 自动化 CRUD、手动触发 |
| `/api/model` | `api_model` | Chat/Voice/Paint 模型选择与选项 |
| `/api/memories` | `api_memories` | UserMemory 查询、删除、更新 |
| `/api/content` | `api_content` | 文件索引、转换、配置、文件列表与删除 |
| `/api/notion` | `notion_router` | Notion 相关客户端流程 |
| `/` 等 | `web_client` | Web 首页、home/search/chat/login/agents/settings/automations/share/error |
| `/auth` | `auth_router` | 非 anonymous mode 下的登录、magic link、Google OAuth、token、logout、OAuth metadata |
| `/api/subscription` | `subscription_router` | 仅 billing 条件满足时启用 |
| `/api/phone` | `api_phone` | 仅 Twilio 配置启用时注册 |

### 10.2 关键 API

- 搜索：`GET /api/search?q=...&n=...&t=...&r=...&max_distance=...&dedupe=...`。
- 索引：`PUT/PATCH /api/content`，上传多个文件；`GET /api/update` 触发用户内容更新。
- 转换：`POST /api/content/convert`，支持 `org`/`markdown`/`pdf`/`plaintext`/`docx`。
- 对话：`POST /api/chat`、`GET /api/chat/ws`。
- Agent：`GET/POST/PATCH/DELETE /api/agents` 与 `/{agent_slug}`。
- 自动化：`GET/POST/PUT/DELETE /api/automation`，`POST /api/automation/trigger`。
- 记忆：`GET /api/memories`、`DELETE/PUT /api/memories/{memory_id}`。
- 模型：`/api/model/chat`、`/api/model/voice`、`/api/model/paint`。
- 内容管理：`/api/content/files`、`/api/content/file`、`/api/content/types`、`/api/content/source/{content_source}`。
- 健康/身份：`GET /api/health`、`GET /api/v1/user`。

### 10.3 客户端

| 客户端 | 技术栈/入口 | 构建与服务关系 |
|---|---|---|
| Web | `src/interface/web`，Next.js 15.5.18、React 18、TypeScript、Tailwind/Radix | `bun run build` 后由 `export` 复制到 `src/khoj/interface/built`，再由 Django/FastAPI 静态服务；开发端默认 `localhost:3000`，重写到 API `localhost:42110` |
| Obsidian | TypeScript、esbuild、Obsidian API | `yarn install && yarn build`；编译后的插件目录链接到 Vault 的 `.obsidian/plugins` |
| Desktop | Electron + ToDesktop runtime | `yarn start`；生产由 ToDesktop CLI 构建，入口为 `main.js` |
| Emacs | Emacs Lisp 客户端 | 文档以 `M-x khoj <user-query>` 说明，走 HTTP API |
| Android | Android/TWA 包装层 | `twa-manifest.json` 与 Web App Manifest 指向 Web 应用 |
| Documentation | Docusaurus 3.9、React 19、MDX | `documentation/` 单独 `yarn start/build/deploy` |

## 11. 外部依赖与部署拓扑

### 11.1 Python 关键依赖

`pyproject.toml` 要求 Python `>=3.10, <3.13`，构建后端为 `hatchling + hatch-vcs`。主要依赖分组：

| 领域 | 依赖 |
|---|---|
| Web/API | `fastapi`、`uvicorn`、`django`、`django-unfold`、`python-multipart`、`starlette` 间接依赖 |
| 数据库 | `psycopg2-binary`、`pgvector`、PostgreSQL 服务 |
| 检索/ML | `torch==2.6.0`、`sentence-transformers==3.4.1`、`transformers`、`tiktoken`、`einops`、`huggingface-hub` |
| 文本/文件 | `beautifulsoup4`、`langchain-text-splitters`、`pymupdf`、`docx2txt`、`lxml`、`markdownify`、`rapidocr-onnxruntime`、`pillow` |
| 模型提供商 | `openai`、`anthropic`、`google-genai`、`google-auth`、`openai-whisper` |
| 调度/网络 | `apscheduler`、`django-apscheduler`、`schedule`、`aiohttp`、`requests`、`websockets` |
| 安全/认证 | `authlib`、`itsdangerous`、`django-phonenumber-field`、`phonenumbers`、`email-validator` |
| 工具/运行 | `e2b-code-interpreter`、`mcp`、`rich`、`click`、`pyyaml`、`tenacity` |

开发额外依赖包括 `pytest`、`pytest-django`、`pytest-asyncio`、`pytest-xdist`、`freezegun`、`factory-boy`、`mypy`、`ruff`、`pre-commit`、`datasets`、`pandas`。

### 11.2 Docker Compose

`docker-compose.yml` 定义：

- `database`：`pgvector/pgvector:pg15`，持久卷 `khoj_db`。
- `sandbox`：`ghcr.io/khoj-ai/terrarium:latest`，代码执行沙箱。
- `search`：`searxng/searxng:latest`，在线搜索服务。
- `computer`：`ghcr.io/khoj-ai/khoj-computer:latest`，Operator 桌面，端口 `5900`，持久卷 `khoj_computer`。
- `server`：`ghcr.io/khoj-ai/khoj:latest`，端口 `42110`，挂载配置/模型缓存；默认连 database、sandbox、search。
- 重要环境变量：`POSTGRES_*`、`KHOJ_DJANGO_SECRET_KEY`、`KHOJ_TERRARIUM_URL`、`KHOJ_SEARXNG_URL`、模型 API keys、`KHOJ_OPERATOR_ENABLED`、`KHOJ_NO_HTTPS`、`KHOJ_DOMAIN`、`KHOJ_ALLOWED_DOMAIN`、`KHOJ_TELEMETRY_DISABLE`。

## 12. 测试与质量门

### 12.1 测试结构

- 测试框架：`pytest + pytest-django + pytest-asyncio`；`pyproject.toml` 开启 `--strict-markers`，定义 `chatquality` marker。
- 测试入口：根 `tests/`，当前约 27 个测试 Python 文件，另有 `tests/evals/eval.py` 与 `tests/data/` 夹具。
- `tests/conftest.py` 负责 Django DB 解锁、默认用户/订阅/API token/模型/Agent/ProcessLock 工厂、FastAPI `TestClient`、搜索模型初始化、知识库索引夹具。
- 测试重点覆盖：文本/Markdown/Org/PDF/DOCX/图像解析，日期/文件/单词过滤，文本搜索，API 认证与限流，Agent，Conversation，Automation，Memory，多用户隔离，DB lock。
- 许多测试通过 `FastAPI()` + `configure_routes()` + `configure_middleware()` 构造应用，而不是启动真实 Uvicorn；需要 PostgreSQL/pgvector 和模型初始化条件。
- 外部 API 测试依赖环境变量并以 `skipif` 控制，例如 `GEMINI_API_KEY`、`OPENAI_API_KEY`；因此“测试收集成功”不等于所有外部链路被实跑。

### 12.2 已见质量配置

- `ruff`：行宽 120，启用 `E/F/I`，忽略 `E501/F405/E402`，`src/khoj/main.py` 另有 import 顺序豁免。
- `mypy`：扫描 `src/khoj`，`strict_optional=false`，忽略缺失第三方类型。
- `hatch-vcs`：Python 版本动态来自 Git。
- Web：Next.js `lint`、TypeScript 编译、Prettier、Husky/lint-staged。
- Obsidian：TypeScript `tsc` + esbuild。
- 当前审计按用户边界未安装依赖、未构建、未启动、未执行 pytest/ruff/mypy；本文中的测试结论只描述源码中已有测试布局和契约，不宣称当前环境测试通过。

## 13. 关键风险与维护注意

### P0/P1：架构级风险

1. **代码地图边界**：目标 `.codegraph/` 仅用于导航，不能代替逐段源码读取或运行验证。
2. **远程版本**：当前 HEAD 与远程 `master` 对齐；后续远程指针变化时，仍须建立隔离快照并逐文件核对，不能仅凭分支名推断实现。
3. **启动阶段副作用过重**：`khoj.main` 导入即 `django.setup()`、迁移和 `collectstatic`；对多 worker、Gunicorn preload、测试导入和故障恢复都有耦合。迁移/静态收集失败会阻止 API 进程建立。
4. **数据库是硬依赖**：默认 PostgreSQL + pgvector；`Entry`/`UserMemory` 的向量字段使 SQLite 不能作为等价替代。`pgserver` 只是显式开启时的可选本地路径。
5. **全局可变状态**：模型、OpenAI/Whisper client、scheduler、认证模式、缓存、telemetry 都位于 `khoj.utils.state` 模块级变量；同进程多租户、多测试和热更新时需要严格重置状态。

### P1：复杂度与可靠性风险

6. **超大聚合模块**：`database/adapters/__init__.py` 约 2374 行，`database/models/__init__.py` 约 864 行，`api_chat.py` 超过 1700 行；模型、适配器、业务规则和并发语义集中，修改影响面大。
7. **索引是同步重活**：API 通过 `ThreadPoolExecutor`/event loop executor 执行内容索引，但 embeddings、PDF/DOCX 解析、批量 ORM 写入仍可能占用大量 CPU/内存；`ProcessLock` 仅约束部分操作，需关注多 worker 重复负载。
8. **模型与外部服务失败面广**：本地模型下载/加载、HuggingFace/OpenAI/Anthropic/Google、Whisper、SearxNG、Firecrawl/Exa/Olostep、Terrarium/E2B、MCP 和 computer operator 均可能独立失败；错误降级策略并不统一。
9. **认证分支复杂**：Session、Bearer、WhatsApp、anonymous mode、subscription scope 并行存在；`KHOJ_NO_HTTPS`、`KHOJ_DOMAIN`、Cookie/CSRF/代理头配置错误会表现为登录循环或跨客户端失败。
10. **自动化单领导者语义**：APScheduler 使用数据库 JobStore，但只有持有 `schedule_leader` 的 worker 执行任务；锁过期、worker 崩溃、时区和多实例唤醒需要专项验证。
11. **数据删除/重建语义需谨慎**：`regenerate` 会删除对应 file type 的旧 Entry；Agent 更新会删除并重建 Agent 文件/Entry；Memory 更新是删除后新建。调用方重试或中断时应确认幂等性与中间状态。
12. **敏感配置与日志边界**：数据库模型存储 API key、PAT、MCP key 等字段；`telemetry`、错误日志、远程 scraper 和模型请求均可能携带用户/文档元数据，应持续核对脱敏和最小化记录。
13. **多客户端静态产物同步**：Web 构建结果复制到 `src/khoj/interface/built`/`compiled` 后由 Django 收集；客户端版本、Next rewrites、静态目录和后端路由必须同步，不能只改前端页面。
14. **动态版本与依赖漂移**：Python 版本由 `hatch-vcs` 动态计算，根包要求 `<3.13`，而部分文档/本机工具链可能使用更高版本；远程提交更新也可能改变依赖锁定与客户端版本。

## 14. 后续阅读与演进建议

1. **先冻结版本基线**：当前以本地与远程共同指向的 `ae229ca...` 为基线；后续若指针变化，不得混合未核对的两套结构结论。
2. **代码地图边界**：目标仓库已有独立只读代码地图；后续“影响面/验证证据”仍必须回读 Khoj 源码并执行受控验证，不能依赖其他项目 MCP。
3. **按调用链拆分大型聚合文件**：优先将 `database/adapters` 按用户/Agent/Conversation/Entry/Automation/ProcessLock 分域，将 `api_chat` 拆分为 HTTP、WebSocket、事件流、会话管理；拆分前先锁定公开 import 与 API 契约。
4. **隔离启动副作用**：把迁移、静态收集、模型加载、scheduler 启动从模块导入路径中分离，区分“构造 app”“数据库准备”“worker 启动”；这会显著改善测试和多进程部署。
5. **建立索引任务边界**：将内容解析/embedding/数据库写入的状态、重试、取消、幂等键和进度显式化；继续使用 `ProcessLock` 时应补充崩溃恢复和跨 worker 验证。
6. **保持统一检索契约**：为 local/HuggingFace/OpenAI embedding 与 cross-encoder 定义统一的向量维度、错误、超时、重试和降级结果；更换模型必须显式触发 re-index。
7. **补齐外部依赖矩阵测试**：区分“无 key”“服务不可达”“返回格式错误”“超时”“部分成功”与“真实成功”，避免 `skipif` 让关键路径长期不被覆盖。
8. **把安全边界作为独立审计对象**：认证 scope、Prompt 安全检查、用户/Agent 数据隔离、Operator 容器、Docker socket、MCP 凭证、遥测和公开分享应分别形成可执行门禁。

## 15. 未确认项与证据分级

### 已由源码确认

- `khoj.main:run`、`configure_routes`、`configure_middleware`、`initialize_server` 的入口与调用顺序。
- `Entry`、`FileObject`、`UserMemory`、`Agent`、`Conversation`、`SearchModelConfig`、`ProcessLock` 等模型及其关键字段/关系。
- `/api`、`/api/chat`、`/api/agents`、`/api/content`、`/api/memories`、`/api/model`、`/api/automation`、`/auth` 等路由装配与主要端点。
- 内容解析→分块/哈希→embedding→ORM 写入，以及查询 embedding→向量召回→过滤/重排→`SearchResponse` 的关键调用链。
- `pyproject.toml`、客户端 `package.json`、`docker-compose.yml`、现有 pytest fixtures 与测试文件布局。

### 项目自述或文档说明，未在当前审计端到端实跑确认

- README 中“可扩展到云规模企业 AI”“在现代检索与推理基准上表现优秀”等产品/性能表述，仅作为项目自述，不作为本架构事实或性能证据。
- 文档中关于“super fast search”、支持的全部客户端/模型、Operator 可执行任务范围和线上服务可用性的说明，未在当前审计启动服务或调用外部服务验证。
- Docker Compose 中的镜像、健康检查、SearxNG/Terrarium/Computer 互通、真实 PostgreSQL+pgvector 迁移和多 worker 调度领导选举，未在当前审计启动验证。
- HuggingFace/OpenAI/Anthropic/Google、Whisper、Firecrawl/Exa/Olostep、E2B、MCP 等外部 provider 的真实成功、超时、重试、错误和降级语义，未在当前审计调用验证。
- Web/Obsidian/Desktop/Android 的实际构建产物、静态复制、客户端登录和版本兼容，未在当前审计安装或构建验证。
- 当前本地与 `origin/master` 提交一致；本轮未运行服务或完整测试，因此版本对齐不等于行为通过。

### 未解决的基础设施问题

- 本轮未使用 `system_engineering_toolkit`；目标仓库独立 `.codegraph/` 仅作导航，不能替代 Khoj 源码和运行验证。
- 本地存在未跟踪的 `历史研究-khoj.md`，当前审计只读引用，未删除、覆盖或迁移。

## 16. 结论

Khoj 的核心价值在于把个人知识摄取、向量检索、可配置 Agent、多模型对话、工具调用和定时自动化整合到一个 Django/FastAPI 单体中，并通过多客户端复用同一 API。其最重要的架构事实不是某一个模型，而是以下组合：

- `FileObject` 保存全文，`Entry` 保存分块、来源、哈希和 pgvector embedding，`UserMemory` 保存长期记忆；
- `TextToEntries` 统一不同文档源，`EmbeddingsModel + CrossEncoderModel` 组成召回/重排两阶段检索；
- `configure.py` 将 FastAPI、Django、认证、中间件、模型和 scheduler 装配在同一进程；
- `Agent` 通过人设、知识文件、ChatModel、输入工具和输出模式定义可复用的行为边界；
- Web/Obsidian/Desktop/Emacs/Android 都是 API 客户端，Web 和 Django 静态系统共享构建产物；
- PostgreSQL/pgvector、外部模型 API、搜索服务、代码沙箱与 Operator 容器共同构成运行时依赖面。

前序研究建档完成；当前本地与远程提交对齐，本文是基于该固定提交的权威导航，但仍不是运行验证或未来远程提交的替代品。

## 17. 历史研究吸收与裁决

本节收口 `历史研究-khoj.md` 的全部有价值信息；旧文件保留作为历史历史研究，不再与本文并列维护。以下裁决均以目标目录当前源码、仓库文档或本文已记录的版本基线为依据。

| 历史研究结论 | 裁决 | 吸收位置与证据 |
|---|---|---|
| Khoj 是 `Your AI second brain`，提供搜索、Agent、自动化和文档检索 | **吸收** | 项目身份、总体架构与结论；`README.md` 的产品定位和功能清单，`src/khoj/main.py`/`configure.py`/`routers/`/`processor/` 的实现边界 |
| `processor` 分为 content、conversation、embeddings、image、speech、operator、tools 七类 | **吸收** | 目录地图与各层边界；`src/khoj/processor/` 下对应目录/文件。这里的“七类”是处理器能力域，不把它误写成七种统一的内容入库格式；实际 `IndexerInput` 由 `api_content.py` 明确支持 `org`、`markdown`、`pdf`、`plaintext`、`image`、`docx` |
| `search_type + search_filter` 构成语义检索链 | **吸收并细化** | 检索章节；`search_type/text_search.py`、`search_filter/{base,date,file,word}_filter.py`、`database/adapters` 给出向量召回、过滤、去重和可选重排的真实调用链 |
| Agent = 知识 + 人设 + 聊天模型 + 工具 | **吸收并细化** | Agent 章节；`database/models/__init__.py::Agent`、`routers/api_agents.py`、`database/adapters` 记录知识文件复制、`personality`、`chat_model`、`input_tools`、`output_modes` 与隐私边界 |
| 自动化提供个性化 newsletter/智能通知 | **吸收但降级为“文档声明 + 源码可见调度契约”** | 新增“自动化、Newsletter 与通知”小节；`routers/api_automation.py` 证实 cron 任务 CRUD/手动触发，`processor/conversation/prompts.py` 证实通知判断和邮件格式化提示词，`documentation/docs/features/automations.md` 说明邮件投递；真实 Resend/邮件送达未验证 |
| 对话/Agent 人设提示词位于 `processor/conversation` 与 Agent 配置 | **吸收并细化** | 对话章节新增 `prompts.py` 的默认/自定义 personality、自动化和工具上下文提示词；Agent 配置字段见模型与 `api_agents.py` |
| 部署边界为 Docker | **吸收并细化** | Docker Compose 章节；`docker-compose.yml` 明确 `database`、`sandbox`、`search`、`computer`、`server` 五类服务及其卷、端口和环境变量。Operator 的 Docker socket 与隔离风险另列为高风险边界 |
| 许可证“通常 AGPL，需确认” | **吸收并完成确认** | 项目身份章节已以 `pyproject.toml` 确认根包为 `AGPL-3.0-or-later`，并记录 Obsidian/Desktop 子包的 `GPL-3.0-or-later`；不再保留“通常”这一不确定措辞 |
| 可借鉴：七类处理器、Agent 组合、自动化推送、检索过滤链 | **吸收为研究裁决，不当作 Khoj 生产改造要求** | 本表对应的架构边界已写入本文；这些“对底座可借鉴点”不扩展为本项目源码/配置/测试修改，也不构成性能或安全保证 |

### 收口状态

- 已完整读取并逐项对照 `历史研究-khoj.md`（92 行）；历史研究未删除、未修改。
- 有源码或项目文档证据的内容已并入本文件；仅有宣传性质的结论没有升级为源码事实。
- 本文件仍是目标根唯一权威架构文档；后续 Khoj 架构事实只更新 `ARCHITECTURE.md`，不在历史研究中追加新结论。

## 18. 当前裁决：面向系统底座的能力域映射

本节不是把 Khoj 源码搬进平台，而是把已由源码确认的能力拆成“通用模块契约”和“Khoj 项目适配”。判断基线是本地与远程共同指向的 `ae229ca894c0b80ad84664afcfdde523b5e87057`；当前审计没有修改 Khoj 源码、配置、依赖、测试或历史研究。以下“通用”表示可由平台公开能力承载，“适配”表示必须由 Khoj 绑定 Django/数据库/HTTP/第三方服务/产品语义，不能泄漏进通用底座。

### 18.1 处理器能力域映射表

| Khoj 事实域 | 真实实现证据 | 可抽取的通用模块 | 必须保留在 Khoj 项目适配层 | 当前裁决裁决 |
|---|---|---|---|---|
| `processor/content` | `processor/content/*_to_entries.py`、`text_to_entries.py`；`api_content.IndexerInput` 支持 `org/markdown/pdf/plaintext/image/docx`，并把内容切块、哈希、写入 `FileObject/Entry` | `ContentSource`、格式解析、统一文档块、分块策略、内容摘要/幂等、索引任务状态 | `IndexerInput` 类型枚举、Django `FileObject/Entry/EntryDates`、`EntryType`、文件来源权限、Notion/GitHub 同步 | **吸收为内容摄取能力域；升级为“解析→规范文档→分块→摘要→索引提交”唯一链，不复制每种格式的入库流程** |
| `processor/conversation` | `conversation/openai`、`anthropic`、`google`、`prompts.py`、`routers/helpers.py::send_message_to_model_wrapper` | 对话请求、上下文装配、模型路由、流式事件、结构化输出、模型失败回退 | `ChatModel/ AiModelApi`、订阅/fast model 选择、Khoj `Conversation` 日志格式、供应商参数和提示词产品文案 | **吸收为对话编排模块；各 provider 只是策略适配，不允许路由或 Agent 再实现第二套模型回退链** |
| `processor/embeddings` | `EmbeddingsModel`/`CrossEncoderModel`、`state.embeddings_model`/`state.cross_encoder_model`、`text_search.compute_embeddings/query` | `embed_documents`、`embed_query`、rerank、模型版本/维度/设备/超时契约、重建索引命令 | `SearchModelConfig`、SentenceTransformer/HuggingFace/OpenAI 具体构造、PostgreSQL `VectorField` 维度、模型切换后的全量重建策略 | **吸收为检索支持能力；升级为模型版本与向量维度显式绑定，禁止只改配置而继续读旧向量** |
| `processor/image`、`processor/speech` | `image/generate.py`、`speech/text_to_speech.py` 与语音/图像路由、`UserTextToImageModelConfig/UserVoiceModelConfig` | 图像生成、语音转写/合成、媒体资产结果、大小/格式/超时/清理契约 | Khoj 用户模型配置、媒体 URL/静态资产、订阅限制、响应事件名称 | **吸收为媒体原子能力，但与文本检索/对话编排解耦；媒体 provider 缺失只返回明确不可用，不伪造成功** |
| `processor/operator` | `operator_environment_browser.py`、`operator_environment_computer.py`、`operator_agent_*`，Docker Compose `computer` | 受监督的浏览器/桌面操作、截图/输入/文件与终端工具、权限/预算/取消/进程组清理 | `KHOJ_OPERATOR_ENABLED`、computer 容器、VNC 端口、Operator prompt、Docker socket 是否挂载、Agent `input_tools` 授权 | **隔离，不作为普通通用工具默认开放；只有项目适配声明权限、容器和凭证后才能装配** |
| `processor/tools` | `tools/online_search.py`、`tools/run_code.py`、`tools/mcp.py` | 工具注册/调用、工具参数校验、provider fallback、网络/沙箱/MCP 会话、输出截断、审计 | SearxNG/Serper/Exa/Firecrawl/Google 配置，Terrarium/E2B 地址，`McpServer` 表和 Khoj 工具提示词 | **吸收工具执行契约；升级为“工具调用器→受管 provider”单链，禁止 `api_chat`、Agent、自动化各自直连第三方** |

处理器域不是七条各自独立的业务流水线。通用底座应把它们归并为四类公开能力：**内容摄取**、**模型推理**、**媒体处理**、**受监督工具执行**；`conversation` 是编排模块而非一个可被任意调用的 provider。Khoj 的 `processor` 目录只在项目适配层实现产品所需组合和路由。

### 18.2 检索类型、过滤和排序的拆分

源码当前有 `SearchType`：`all/org/markdown/image/pdf/github/notion/plaintext/docx`（`utils/config.py`），但 `routers/helpers.py::search` 的文本检索分支实际只调度 `all/org/markdown/github/notion/plaintext/pdf`，`text_search.search_type_to_embeddings_type` 也只映射 `org/markdown/plaintext/pdf/github/notion/all`；`image`、`docx` 的完整向量检索接线不能仅凭枚举存在而判定已闭环。这是当前裁决必须保留的**实现/声明差异**。

现有唯一检索事实链应抽象为：

```text
SearchRequest(q, type, n, max_distance, rerank, dedupe, scope)
  → 过滤语法解析（DateFilter/FileFilter/WordFilter）
  → defiltered_query（只把自然语言部分送 embedding）
  → EmbeddingsModel.embed_query
  → EntryAdapters.search_with_embeddings（用户/Agent/类型/距离/向量过滤）
  → collate_results（hashed_value/corpus_id 去重与来源投影）
  → 可选 CrossEncoderModel 重排
  → SearchResponse（entry/score/corpus_id/additional）
```

过滤器的通用契约是 `BaseFilter.get_filter_terms/can_filter/defilter`；当前三类实现分别为：

- `DateFilter`：解析 `dt:"..."`、`dt>=`、`dt<` 等自然日期，合并为时间区间，再映射 `EntryDates`；非法日期会被忽略并记录日志，调用方必须区分“没有日期条件”和“日期解析失败”。
- `FileFilter`：支持 `file:"pattern"` 与 `-file:"pattern"`，通配符转正则；`defilter()` 只删除正向表达式，负向过滤的落库应用由适配查询层承担，不能把“去掉查询词”误当作“已经过滤”。
- `WordFilter`：支持 `+"word"` 与 `-"word"`；`defilter()` 从向量文本移除结构化词条件，实际包含/排除仍由 `EntryAdapters` 查询适配器负责。

**通用模块**应拥有 `SearchRequest`、过滤 AST/规范化、结果排序/去重和错误码；**Khoj 适配层**拥有 `Entry` 字段、`EntryDates` 连接、用户/Agent scope、PostgreSQL `CosineDistance` 和动态 `SearchType` 插件枚举。不得由每个客户端自行实现 date/file/word 语法，也不得让向量 provider 知道 Django ORM。

检索缺口裁决：

1. **升级**：把 `type`、过滤条件、embedding model/version、rerank 参数、scope 和 dedupe 组成可记录的 `SearchRequest`，使缓存键不再只依赖字符串拼接；当前 `state.query_cache` 是进程内、无版本失效的项目实现，只能由 Khoj 适配层暂存。
2. **升级**：显式记录召回阶段、过滤阶段、重排阶段的候选数和失败原因；`cross_encoder_score()` 只捕获 HTTPError 并以全 0 分继续，通用契约应把“未重排”作为可观测降级，而不是静默成功。
3. **待核**：`image/docx` 是否应有独立检索 provider、`EntryAdapters.search_with_embeddings` 对所有过滤器的精确 SQL 语义及插件 search type 的完整注册，需要在下一轮源码/测试/运行证据中确认，当前不扩平台能力。
4. **废弃/隔离**：不要复制 `database/adapters/__init__.py` 的聚合查询类；它是 Khoj 适配器，不是平台通用检索中心。平台只暴露能力契约，项目适配器负责把 ORM 查询映射进去。

### 18.3 知识、人设、模型、工具的组合契约

Khoj `Agent` 的真实组合字段是 `personality`、`chat_model`、`input_tools`、`output_modes`、`privacy_level`、`creator/managed_by_admin/is_hidden`；其知识并非字段内嵌，而是从用户 `FileObject/Entry` 复制到 Agent 侧，且 `Entry` 禁止同时拥有 `user` 与 `agent`。`UserMemory` 又是按用户/Agent 的长期记忆向量，不能与知识文件混为一类。

通用底座应固定一个不可变的 `AgentSpec` 形状：

```text
AgentSpec
  = identity/版本
  + knowledge_refs（只读知识集引用，不复制底层数据）
  + memory_policy（是否读写长期记忆、范围、保留策略）
  + personality（系统指令/风格，带安全校验）
  + model_ref（模型能力 id + provider/version + fallback policy）
  + tool_allowlist（工具能力 id、参数/权限/预算）
  + output_modes
  + visibility/owner
```

一次对话的唯一组合链应为：

```text
项目 API/客户端
  → 项目适配层解析 Agent/用户/订阅
  → AgentSpec 装配器（知识、记忆、人设、模型、工具权限）
  → context builder（SearchRequest/历史/在线上下文/文件）
  → 唯一模型调用器（primary→fallback）
  → 工具调用器（如模型请求工具）
  → 统一流式事件/Conversation 持久化
```

其中：

- **通用**：AgentSpec 校验、上下文大小预算、提示词模板参数边界、模型 fallback 状态、工具 allowlist、流式事件和取消语义。
- **Khoj 适配**：`AgentAdapters` 的可见性查询、默认 Agent `khoj` 的动态模型选择、Django `Conversation.conversation_log`、`FileObject/Entry/UserMemory` 查询、`premium` scope 和 `api_agents` 的安全 prompt 检查。
- **模型适配**：OpenAI/Anthropic/Google 的请求格式、API key、vision、`fast_model` 槽位和具体 tokenizer；不能把 provider 对象泄漏给 AgentSpec。
- **工具适配**：在线搜索 provider、Terrarium/E2B、MCP、Computer/Browser 必须各自声明资源和权限；`input_tools` 只是产品配置，不能代替运行时授权。

组合失败必须可区分：Agent 不可见/无权限、知识为空、记忆不可用、模型未配置、primary 超时后 fallback 成功、全部模型失败、工具未授权、工具 provider 不可用。不能把所有情况都转成“无相关笔记”或空字符串。

### 18.4 定时自动化、通知和邮件边界

源码有两套不同责任的时间机制，不能混写：

1. `APScheduler + DjangoJobStore` 是用户自动化的权威任务存储。`api_automation.py` 提供 CRUD/手动 trigger，`schedule_automation()` 用 `CronTrigger`、用户时区、60 秒 jitter、确定性 `job_id` 注册 `scheduled_chat`，并通过 `ProcessLock.Operation.SCHEDULED_JOB` 运行。
2. Python `schedule` 库由 `main.py::poll_task_scheduler()` 每 60 秒轮询，承载内容定期更新、telemetry、限流记录清理和 `wakeup_scheduler`；`wakeup_scheduler` 负责续领导锁、pause/resume APScheduler 和 wakeup。它不是第二套用户自动化存储。

通用底座的 `ScheduledTask` 契约必须包含：任务 id/所有者、输入查询或命令、时区、cron/下一次运行时间、幂等键、最大并发、misfire/coalesce、超时/取消、重试策略、状态/执行证据、通知策略和输出目标。邮件不是调度器职责，而是：

```text
任务触发
  → ProcessLock/幂等执行
  → scheduled_chat（唯一对话执行入口）
  → should_notify（通知策略）
  → format_automation_response（输出格式化）
  → NotificationProvider.send（邮件/站内/其他）
```

Khoj 适配层的边界为：`AutomationAdapters`/`api_automation.py` 的 HTTP 参数和权限、`schedule_query/aschedule_query` 用模型生成 `crontime/query/subject`、`Conversation` 关联、`DjangoJobStore`、`ProcessLock`、`routers/email.py::send_task_email` 和 Resend 环境变量。`prompts.py` 的 `crontime_prompt/to_notify_or_not/automation_format_prompt` 是产品提示词，不应被当作通用 scheduler 规则。

明确的失败与资源语义：

- 空 query/cron、cron 描述非法、分钟级频率、未知时区、重复 job id 必须在创建/编辑阶段拒绝或明确降级（当前未知时区回退 UTC，分钟级非数字分钟会被拒绝/在底层随机分钟化，需记录为项目兼容行为）。
- leader 丢失时 worker 必须 pause；锁过期后只能一个 worker 重新取得 `SCHEDULE_LEADER`，任务执行用 `SCHEDULED_JOB` 防重；scheduler shutdown 要释放领导锁并停止后台线程。
- misfire/coalesce/jitter 影响“漏跑、合并、延迟”，必须进入执行证据；`max_instances=2` 允许第二次实例处理陈旧锁，不能直接等同于业务可并发两次。
- `scheduled_chat` HTTP/model 失败、非 200、结果为空和通知条件不满足必须分别记录；当前失败多为日志/`None` 返回，不具备统一持久化失败重试契约。
- `send_task_email()` 只在 `RESEND_API_KEY` 存在时发送；缺 key 是禁用而不是送达成功，Resend 异常当前没有统一重试/死信/送达回执。通用通知模块必须返回 `accepted/failed/disabled` 与 provider request id，并由项目适配选择 Resend。
- 手动 trigger 在独立 `threading.Thread` 中 fire-and-forget，API 立即返回；通用模块必须能查询执行状态、回收异常线程/连接，并定义客户端取消，不可把“已启动线程”当作“任务成功”。

因此裁决为：**吸收调度/通知的分层契约，升级唯一任务执行入口和失败账本，Resend 仅作项目通知 provider 适配；不把 Khoj 的 prompt 推导 cron 或具体邮件模板写进通用底座。**

## 19. 资源生命周期与失败矩阵

### 19.1 关键资源表

| 资源 | 创建/持有 | 正常释放 | 失败、超时、取消、崩溃要求 | 当前 Khoj 证据/风险 |
|---|---|---|---|---|
| Django/PostgreSQL 连接、事务 | ORM 查询、`DjangoJobStore`、middleware | `AsyncCloseConnectionsMiddleware`/Django 连接管理 | 请求断连、job 异常、进程退出均 close；迁移失败不能半初始化 | 源码有连接清理 middleware；真实 DB/锁/断连未当前审计实跑 |
| embedding/cross-encoder 模型与 GPU/CPU 内存 | `initialize_server` 装入 `state.embeddings_model/cross_encoder_model`，由 `state.device` 持有 | 进程退出或显式重载 | provider 缺失、维度不符、OOM、模型下载失败要返回明确错误；重建索引前锁定版本 | 模块级全局状态；无统一 close/版本失效契约 |
| 查询缓存 | `state.query_cache[user.uuid]` 的 LRU | 淘汰/进程退出 | 过滤、模型、权限、知识更新后必须失效；不能跨租户复用 | 当前 key 是字符串拼接且进程内，项目适配遗留 |
| 文件/临时内容/向量文件 | 内容解析、上传、embedding 保存、sandbox 输入输出 | `finally` 删除临时文件/关闭文件句柄；数据库提交后保留权威制品 | 解析异常/部分写入/取消时删除临时产物，不能留下半条 Entry；索引重建可恢复 | `TextToEntries`/各解析器和 sandbox 有局部清理，统一残留审计未验证 |
| APScheduler、`schedule` 轮询、Timer 线程 | `main.run` 创建 scheduler；`poll_task_scheduler` 每 60 秒创建 daemon Timer | `shutdown_scheduler`、释放 `SCHEDULE_LEADER` | 进程崩溃靠锁超时接管；禁止多个 leader 执行；Timer 不得无限递归泄漏 | 代码有 shutdown/leader/pause；多 worker 与崩溃恢复未实跑 |
| `ProcessLock` | `INDEX_CONTENT/SCHEDULED_JOB/SCHEDULE_LEADER` | 完成/异常 finally、过期清理、shutdown | 任务异常/强杀要清 stale lock；锁 owner/租约/最大时长应入证据 | 有数据库锁和 12 小时领导锁；缺当前审计强杀验证 |
| HTTP sessions / 外部 provider | `aiohttp.ClientSession`、`requests`、模型 SDK、Resend SDK | async context 或调用结束 | 超时取消必须关闭 session；重试有界；provider 不可达不可返回空成功 | 在线搜索逐 provider新建 session并局部捕获；Resend 无统一重试/回执 |
| E2B/Terrarium 沙箱 | `AsyncSandbox.create` 或 `aiohttp` `/` 调用；输入文件 base64 上传 | E2B sandbox 关闭/超时 stop；输出截断 | 代码超时调用 `/stop`，stop 失败也要保留原故障；进程/容器不得残留 | `run_code.py` 有 tenacity 三次重试、超时 stop；真实沙箱未验证 |
| MCP 会话/stdio 子进程 | `MCPClient.exit_stack`、SSE/stdio `ClientSession` | `MCPClient.close()` 退出栈、session/stream close | connect/list/call 失败和客户端取消均 close；stdio 子进程不得孤儿 | `close()` 路径存在；调用异常、进程残留和重连未验证 |
| 流式响应/客户端连接 | `MessageProcessor`、event generator、WebSocket/HTTP stream | 断连 middleware、排空 buffer、保存 Conversation | 客户端断连、半个 JSON 事件、模型超时不能重复写/丢失终止事件 | 代码有断连与 chunk 解析；完整断连回收未实跑 |

### 19.2 失败矩阵与统一错误语义

| 场景 | 应归属的错误码/结果 | 是否可重试 | 恢复/验证要求 |
|---|---|---|---|
| 不支持格式、空文件、解析器损坏 | `INPUT_UNSUPPORTED`/`CONTENT_INVALID` | 通常否 | 不写 Entry；保留文件级失败证据，重新上传可重试 |
| embedding provider 缺失、下载失败、维度/模型版本不匹配 | `EMBEDDING_PROVIDER_UNAVAILABLE`/`EMBEDDING_SCHEMA_MISMATCH` | 缺 provider 可在 provider 修复后重试；维度不应盲重试 | 重新初始化模型并锁定搜索模型；确认数据库旧向量未被错误读取 |
| PostgreSQL/pgvector 不可达、事务失败、ProcessLock 冲突 | `STORAGE_UNAVAILABLE`/`LOCK_BUSY` | 有界重试 | 回滚事务、释放锁、确认没有半条 Entry/Job；再由唯一任务入口重试 |
| 日期/文件/单词过滤非法或结果为空 | `FILTER_INVALID` 或合法的 `NO_RESULTS` | 非法条件不重试；空结果不重试 | 返回过滤解析状态，不能把空结果伪装成 provider 失败 |
| CrossEncoder HTTP/超时 | `RERANK_DEGRADED` | 可按 provider 策略一次重试 | 返回 bi-encoder 顺序和降级标记；不能丢掉候选 |
| Agent 不可见、知识为空、记忆读取失败 | `AGENT_FORBIDDEN`/`KNOWLEDGE_EMPTY`/`MEMORY_UNAVAILABLE` | 权限否；外部存储失败可重试 | 用户/Agent scope 再校验；知识和记忆分开计数 |
| Chat primary 失败、fallback 成功/全部失败 | `MODEL_FALLBACK_USED`/`MODEL_UNAVAILABLE` | 按 provider/预算有界 | 记录每个模型尝试、耗时和最终 owner；Conversation 只写一次最终语义 |
| 在线搜索无网络、无启用 engine、抓取全部失败 | `ONLINE_UNAVAILABLE`/`WEBPAGE_UNAVAILABLE` | 有界且按 engine fallback | `online_search.py` 的空 dict 只能表示无结果/失败，底座必须带状态和 provider |
| 沙箱超时、代码错误、stop 失败 | `SANDBOX_TIMEOUT`/`SANDBOX_EXECUTION_FAILED` | 网络错误最多有界重试；用户代码错误否 | stop/kill 后验证沙箱无残留；保留代码、stdout/stderr、输出文件清单但脱敏 |
| MCP 连接/工具错误、Operator 未授权 | `TOOL_UNAVAILABLE`/`TOOL_FORBIDDEN` | 连接可有界重连；动作不可盲重放 | close session/进程；高风险动作要求显式授权和幂等键 |
| cron/时区/重复任务/leader 丢失 | `SCHEDULE_INVALID`/`JOB_CONFLICT`/`LEADER_LOST` | 规则错误否，leader 可重新选举 | job metadata、锁、next_run_time 和执行记录对账 |
| Resend 未配置/发送失败/返回未接受 | `NOTIFY_DISABLED`/`NOTIFY_FAILED` | provider 明确可重试才重试 | 记录 `accepted/failed/disabled`，不能以格式化 Markdown 成功替代邮件送达 |

通用结果必须至少带 `success/status`、稳定错误码、可重试性、provider/能力 id、操作 id、租约/资源清理结果和证据引用；Khoj 适配层再把它映射为 HTTP 状态码、旧 JSON、日志或流式事件。不能让每个 router 自己翻译错误。

## 20. 现有能力命中、缺口与底座落点

| 能力/模式 | 当前实现命中 | 底座落点 | 决策 |
|---|---|---|---|
| 多格式内容解析、分块、摘要、向量索引 | `processor/content` + `TextToEntries` + `text_search.setup` | 内容摄取模块 + 文档解析/分块/embedding 支持能力 | **吸收/升级**：统一文档结构、摘要、版本/幂等；格式 provider 不复制流程 |
| 语义检索、类型映射、date/file/word 过滤、去重、rerank | `search_type/text_search.py`、`search_filter/*`、`routers/helpers.py::search` | 唯一 `SearchRequest`/过滤器/检索调用器 | **吸收/升级**：过滤 AST 和降级结果统一；Khoj ORM 查询留适配 |
| Agent 知识/人设/模型/工具组合 | `Agent`、`AgentAdapters`、`prompts.py`、`api_agents` | `AgentSpec` + context builder + model/tool caller | **吸收**：配置组合通用化；隐私、Django 关系和产品 prompt 适配化 |
| 多 provider 对话和 fallback | `send_message_to_model_wrapper` 与 OpenAI/Anthropic/Google | 唯一模型调用器/模型注册表 | **升级**：记录每次尝试和最终模型；禁止 router 另造 fallback |
| 定时任务、单 leader、ProcessLock | `APScheduler/DjangoJobStore`、`schedule`、`ProcessLock` | 唯一 `ScheduledTask`/执行账本/租约协调 | **吸收/升级**：APScheduler 是用户任务 owner；`schedule` 只保留维护轮询适配 |
| 通知/邮件 | `should_notify`、`format_automation_response`、`send_task_email`/Resend | NotificationProvider + 投递状态/死信 | **吸收/适配**：通知策略通用，Resend/模板/收件人适配；补失败回执契约 |
| 在线搜索/抓取 fallback | `online_search.py`、`WebScraper` | OnlineSearch/WebFetch provider 组 | **吸收/升级**：provider registry、统一状态和资源释放；避免空 dict 丢失失败原因 |
| 代码执行、MCP、Computer/Browser | `run_code.py`、`mcp.py`、`operator/*` | 受监督 ToolRunner/Sandbox/MCP session | **隔离/有条件吸收**：高风险能力默认不装配，项目声明权限和容器边界 |
| Docker Compose 部署 | `database/sandbox/search/computer/server` 与卷/环境变量 | 项目运行环境适配器、服务依赖/健康检查契约 | **吸收边界，不复制服务**：通用底座不拥有 Khoj 镜像、Django 迁移和第三方凭证 |
| 全局 `state`、超大 `database/adapters`、router 内业务编排 | `utils/state.py`、`database/adapters/__init__.py`、`api_chat.py` | 仅作为适配层现状；平台用公开能力契约 | **废弃为底座模式**：不得复制为第二套全局状态/适配器聚合中心 |

### 20.1 当前明确缺口

- 没有发现一个独立、稳定、可审计的通用 `SearchRequest`/`FilterPlan`/`AgentSpec`/`ScheduledTask` 契约；当前对象分散在函数参数、Django 模型、提示词和全局 state 中。
- 没有统一的 provider 能力目录：模型、搜索、抓取、沙箱、MCP、邮件的错误/超时/资源结果形状不一致。
- 调度执行与邮件通知缺少持久化的“尝试→结果→回执→重试/死信”链；当前自动化 metadata 和 DjangoJobExecution 不能直接替代统一通知证据。
- 全局模型/cache/scheduler 生命周期与租约没有统一重启、强杀、资源残留验证；多 worker 领导选举只由源码和局部测试可见。
- 测试中的外部 API `skipif`（例如 `tests/test_api_automation.py` 的 `GEMINI_API_KEY`）使“收集成功”与“真实外部成功”必须分级报告。
- 本轮未调用 MCP；目标 `.codegraph/` 已存在且状态为 `up to date`，仍不能把代码图导航结果冒充运行验证证据。

## 21. 唯一链路裁决与装配计划

### 21.1 唯一权威链路

```text
Khoj client/router
  → Khoj 项目适配层（认证、Django DTO、Agent/模型/环境配置、旧 API 兼容）
  → 领域模块（content ingest / search / conversation / automation）
  → 唯一能力调用器与注册表
  → 通用支持能力（parse/chunk/embed/rerank/model/tool/schedule/notify）
  → provider 适配（PostgreSQL/pgvector、OpenAI/Anthropic/Google、SearXNG/Exa/Firecrawl、Terrarium/E2B、MCP、Resend）
  → 数据库/文件/容器/外部 HTTP
  → 统一结果、事件、执行证据与资源清理
```

裁决规则：

1. 一个原子能力只允许一个能力 id、一个契约 owner、一个注册/调用入口；历史函数名只能在项目适配入口归一化，不能让各 router 各维护别名。
2. `processor` 目录是 Khoj 项目组合层，不得被平台消费者直接 import provider 私有实现；所有模型/搜索/工具/邮件调用经唯一调用器。
3. `Entry/FileObject/UserMemory/Agent/Conversation/DjangoJob` 的读写 owner 仍是 Khoj 数据适配层；通用模块不得直接读 Khoj ORM 表，Khoj router 不得绕过适配器写平台状态。
4. 定时任务 owner 是 `ScheduledTask`/APScheduler 适配；`schedule` 的维护轮询只调用调度协调能力，不创建第二份用户 job 状态。通知 owner 是 `NotificationProvider`，不由 scheduler 直接调用 Resend SDK。
5. Provider fallback 只能发生在能力调用器内部并产生一次调用证据；不能出现“在线搜索 fallback 一份、自动化再 fallback 一份、Agent 再 fallback 一份”的隐式叠加。
6. 任何外部资源的创建者、持有者、转移者和释放者必须在请求/任务上下文显式记录；正常完成、业务失败、超时/取消、宿主崩溃四种终态都要有验证。

### 21.2 装配计划（只作为底座输入，不是当前审计生产改造）

| 波次 | 工作包 | 依赖/验收契约 | 项目适配输出 |
|---|---|---|---|
| A | 冻结 `SearchRequest/FilterPlan/SearchResponse` 与错误码 | 过滤语法、scope、n、距离、rerank、dedupe、降级标记可序列化；非法与空结果可区分 | Khoj `SearchType`/`Entry`/`EntryDates` 映射表，确认 `image/docx` 缺口 |
| B | 冻结 `AgentSpec/ContextPlan/ModelCall` | 知识/记忆/人设/模型/工具权限分离；primary/fallback 记录；不可见与 provider 不可用不同码 | `AgentAdapters`、Django Conversation、premium/默认 Agent 适配 |
| C | 内容与模型支持能力 | 解析、分块、embedding、rerank 的版本/维度/超时/资源释放和索引幂等 | `TextToEntries`、FileObject/Entry、SearchModelConfig、具体模型 provider |
| D | `ScheduledTask/ExecutionRecord/NotificationResult` | cron/timezone/leader/lock/misfire/coalesce/取消/回执/死信可读回 | `APScheduler/DjangoJobStore`、ProcessLock、`scheduled_chat`、Resend |
| E | ToolRunner/Sandbox/MCP | 参数/权限/预算/进程组/session close/输出上限/重试状态 | `online_search`、Terrarium/E2B、MCPServer、Operator computer |
| F | 真实装配与部署探针 | 不依赖外部 key 的契约测试 + 有 key 的真实 provider 分层；健康检查和清理证据 | Compose 服务、环境变量、卷、迁移/静态收集、端口和容器健康 |

没有需求登记、能力命中/缺口确认、复用或新建裁决、资源租约、消费者验收契约和装配计划前，不应修改系统工程平台生产底座；当前审计只形成映射输入。

## 22. 当前裁决验证等级、失败证据与剩余风险

### 22.1 当前审计已验证的静态事实

- `ARCHITECTURE.md`、`历史研究-khoj.md`、关键 processor/search/filter/router/model/main/configure/docker/test 文件均来自目标路径的只读读取。
- 已核对处理器目录、`SearchType` 枚举、三种过滤器、`text_search.query`/`routers/helpers.py::search` 链、Agent 字段和知识隔离、APScheduler/`schedule`/ProcessLock、Resend 邮件入口、Compose 服务及测试外部依赖门槛。
- 旧 `历史研究-khoj.md` 仍存在且未修改；当前审计只追加本文件。

### 22.2 未宣称通过的验证

当前审计没有安装依赖、启动 PostgreSQL/pgvector、启动 Compose、调用模型/搜索/沙箱/MCP/Resend、运行 pytest、构建客户端或执行多 worker 强杀。因而以下均为“源码存在/测试存在”而非“真实通过”：邮件送达、scheduler leader 故障接管、任务幂等、模型 fallback、向量维度兼容、外部 provider 超时/重试、沙箱 stop 后无残留、MCP stdio 无孤儿进程和 Operator 容器隔离。

### 22.3 推荐的分级验收命令

在依赖与独立 PostgreSQL/pgvector 测试环境准备后，建议按以下顺序执行并记录退出码、跳过数、外部服务和残留：

```bash
cd "/Users/hekunhua/Documents/Agent/github 源码参考/15_知识库系统/khoj"
pytest -q tests/test_word_filter.py tests/test_file_filter.py tests/test_date_filter.py tests/test_text_search.py
pytest -q tests/test_agents.py tests/test_memory_settings.py tests/test_multiple_users.py
pytest -q tests/test_api_automation.py
ruff check src/khoj tests
python -m compileall -q src/khoj
```

外部依赖测试必须单独列出：无 key/服务不可达/返回畸形/超时/部分成功/真实成功；不能把 `skipif` 的退出码 0 写成 provider 通过。真实自动化验收至少需：创建→读回 job metadata→手动 trigger→读执行结果→通知 accepted/failed/disabled→删除→确认 job/lock/线程/连接无残留；真实多 worker 验收需确认只有一个 `SCHEDULE_LEADER` 执行 scheduled job。

### 22.4 当前审计专属 MCP 阻断

任务要求的 `project_context` 两次均返回错误根目录 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`（MCP 实例 `project_toolkit`），不是目标 Khoj；随后对目标路径调用 `codegraph_explore` 返回“未发现 `.codegraph/`，不要再次调用”。因此当前审计没有有效的 Khoj 开工 id、代码图或 MCP 验证入账；后续若要自动影响分析，必须先给 Khoj 建立独立 CodeGraph/正确项目绑定。此阻断不影响当前审计目标目录只读源码取证，但会降低自动化影响分析和验证证据等级。

## 23. 当前裁决最终裁决

- **吸收**：处理器能力域分类、内容解析/分块/embedding/rerank 两阶段检索、date/file/word 过滤 DSL、Agent 的知识+人设+模型+工具组合、APScheduler 任务与单 leader、通知策略与邮件 provider 分离、Compose 的服务/数据/高风险 Operator 边界。
- **升级现有能力**：统一 SearchRequest/FilterPlan、AgentSpec/ContextPlan、ModelCall fallback、ScheduledTask/ExecutionRecord/NotificationResult、ToolRunner/Sandbox/MCP session 和资源生命周期/错误契约；并为 Khoj 保留映射适配器。
- **新建候选原子能力**：仅在底座能力目录确认不存在时登记“文档解析、内容分块、embedding、rerank、模型调用、检索过滤、任务调度、通知投递、沙箱执行、MCP 会话”能力；每项走能力 id/契约/资源/验证登记，不直接复制 Khoj 类。
- **废弃/隔离**：不复制 Khoj 的 Django ORM、`database/adapters` 巨型聚合、模块级 `state`、产品 prompt、Resend SDK、Compose 具体镜像和 Operator Docker socket；不把 `schedule` 维护轮询误扩成第二个用户任务系统。
- **待核**：`image/docx` 检索闭环、EntryAdapters 的全部过滤 SQL、自动化邮件真实送达/重试、ProcessLock 崩溃接管、外部 provider 真实资源回收，以及正确 Khoj CodeGraph/MCP 绑定。

当前审计当前裁决底座映射完成的定义是：事实仍归 Khoj `ARCHITECTURE.md`，通用能力与项目适配有明确边界，资源/失败/调度/通知/部署有可验收契约，并且所有复用、新建、升级、隔离结论都收敛到上述唯一链路；不等同于系统工程平台已经实施这些能力。

## 24. 本次复审源码收口：摄取、检索、Agent、调度、模型、数据库、API 与恢复

本节是对旧 `历史研究-khoj.md` 的本次复审逐项收口，不是新的产品宣传摘要。事实基线为本地 `HEAD=1e30154d1070c7b132f389638c008b490be1481b`；路径后的行号按当前审计读取的源码记录，后续版本变动时必须重新核对。历史研究只给出“七类 processor、语义检索、Agent 四元组合、自动化通知、Docker”五类结论，以下把它们收敛为可追踪的调用链和失败语义。

### 24.1 内容摄取与索引：真实契约

#### 入口、输入和调度

| 节点 | 真实行为 | 证据 |
|---|---|---|
| 客户端上传 | `PUT /api/content` 传 `regenerate=True`，`PATCH /api/content` 传 `regenerate=False`；`UploadFile` 依据内容类型归入 `org/markdown/pdf/plaintext/image/docx`，不支持类型只记录 debug 并跳过 | `src/khoj/routers/api_content.py:75-116,544-582` |
| 执行边界 | `indexer()` 使用默认 `ThreadPoolExecutor` 的 `run_in_executor` 调用同步 `configure_content`，HTTP 请求等待索引完成；异常统一返回纯文本 `Failed`/HTTP 500，无任务 id、进度或可恢复 checkpoint | `src/khoj/routers/api_content.py:49,70-72,584-602` |
| 外部源 | `POST /api/content/notion` 保存配置后用 `BackgroundTasks` 派发 executor；GitHub 配置保存后不在该请求中显式触发；服务端定期更新由 `configure.update_content_index_regularly` 承担 | `src/khoj/routers/api_content.py:171-232`、`src/khoj/configure.py:409-422` |
| 删除 | 文件删除先删 `Entry` 再删 `FileObject`；按类型/来源删除另走批量 ORM，配置对象（Notion/GitHub）在来源删除时一并删除 | `src/khoj/routers/api_content.py:235-282,379-462` |
| 转换 | `POST /api/content/convert` 只做提取，不落库；单文件超过 10 MB 或类型不支持时跳过但仍返回 HTTP 200，响应没有 per-file error 状态 | `src/khoj/routers/api_content.py:465-541` |

#### 解析→规范 Entry→数据库的链

```text
UploadFile / NotionConfig / GithubConfig
  → get_file_content 或外部源 provider
  → *ToEntries.extract_* / process
  → utils.rawconfig.Entry(raw, compiled, heading, file, uri)
  → split_entries_by_max_tokens(max_tokens=256)
  → MD5(compiled) 哈希对账
  → EmbeddingsModel.embed_documents
  → Entry.bulk_create + FileObject.raw_text + EntryDates
  → 按文件现有 hash 删除陈旧 Entry、按删除文件名清理 FileObject
```

- `MarkdownToEntries` 按标题递归拆分并保存 `file://...#line=N`；`OrgToEntries` 按星号标题递归拆分并保留起始行；纯文本以“文件名+正文”形成一个初始 Entry；PDF/DOCX 按页提取；图片先写当前工作目录临时文件，用 `RapidOCR` 识别后在 `finally` 删除。证据分别为 `processor/content/markdown/markdown_to_entries.py:52-180`、`org_mode/org_to_entries.py:51-169`、`plaintext/plaintext_to_entries.py:61-116`、`pdf/pdf_to_entries.py:54-120`、`docx/docx_to_entries.py:16-111`、`images/image_to_entries.py:50-119`。
- 所有格式最终进入 `TextToEntries.split_entries_by_max_tokens()`：`RecursiveCharacterTextSplitter` 优先按段落、换行、标点、空白切分，`chunk_overlap=0`；同一原始 Entry 的块共享新 `corpus_id`，块会补 heading，超长单词（默认 500 字符）被删除，` ` 被清除，文件 URI 的行号尽量回算。证据：`processor/content/text_to_entries.py:61-140`。
- `update_embeddings()` 以 `MD5(compiled)` 作为 `hashed_value`，按 `user + hashed_value + file_type` 查现有数据，只对新 hash 调当前默认搜索模型的 `embed_documents()`；修改文件的全文写入/更新 `FileObject`，向量按最多 200 条 `bulk_create`，新增 Entry 再抽取日期写 `EntryDates`，最后按每个文件的“旧 hash−当前 hash”删除。证据：`processor/content/text_to_entries.py:142-263`。
- GitHub 用 API tree + raw blob 下载，遇到 `X-RateLimit-Remaining=0` 抛 `ConnectionAbortedError`，仓库级异常会让整个 GitHub 类型失败；Notion 分页调用 `/v1/search`，逐 page 拉 children，单 block children 异常只记日志并返回空对象。证据：`processor/content/github/github_to_entries.py:42-194`、`processor/content/notion/notion_to_entries.py:82-116,205-245`。

#### 索引失败语义与数据一致性边界

`configure_content()` 对 org、markdown、PDF、plaintext、GitHub、Notion、image、docx 逐段 `try/except`；某类型失败只把 `success=False`，仍继续处理其他类型，最后清空该用户的进程内查询缓存并返回总成功标志。因而这是“类型级部分成功”，不是跨类型事务。证据：`src/khoj/routers/helpers.py:3010-3182`。

需要特别保留的实现事实和风险：

1. 解析器通常按文件捕获异常并跳过坏文件，HTTP 层看不到坏文件清单；`update_embeddings()` 的 `bulk_create` 失败只记录批次内容并继续下一批，也没有事务回滚或索引失败表。一次请求可能返回 200/成功文件名，但数据库只写入部分批次。
2. `regenerate=True` 先按 `file_type` 删除全部 Entry，再重建；进程在删除后崩溃会留下空类型索引。重试可重建，但没有任务状态或 checkpoint 证明“删除后尚未重建”。
3. 同一用户、同一类型的相同 `compiled` 在 hash 对账中可被视为已有内容；hash 不含文件路径，跨文件重复内容的归属和 `FileObject` 更新不能当作独立版本系统。
4. `configure_content()` 在 `files is None` 判断前执行 `files.get(...)`；当前 API 始终传字典所以通常不触发，但直接调用该函数传 `None` 会先抛异常。`initialize_content()`/`/api/update` 是同步调用，和上传入口的 executor 语义不同。
5. 图片临时文件使用相对路径和时间戳文件名，正常/异常路径有 `finally` 删除证据，但宿主被强杀时没有残留扫描；PDF/DOCX 使用 `NamedTemporaryFile`，外部解析器异常按文件跳过。

**本次复审裁决：** 吸收“多格式内容处理”作为内容摄取能力域，但不能把各 `*ToEntries` 类当作独立入库流程；通用契约必须补充 `source_file_id/hash、chunk_id/corpus_id、model/version、attempt、partial-success、checkpoint、rebuild 状态`。当前 Khoj 只实现了 hash 增量和局部清理，未实现可读回的索引任务账本。

### 24.2 索引/检索：召回、过滤、缓存和重排

当前普通搜索的完整调用链是：

```text
GET /api/search
  → routers.api.search(n,t,r,max_distance,dedupe)
  → helpers.execute_search
  → defilter DateFilter + WordFilter + FileFilter
  → 默认 embedding model.embed_query(defiltered_query)
  → EntryAdapters.search_with_embeddings
  → PostgreSQL CosineDistance + owner/type/distance/filter
  → collate_results(hashed_value/corpus_id 去重)
  → 可选 CrossEncoderModel 重排
  → SearchResponse(entry, score, corpus_id, additional)
```

证据：`src/khoj/routers/api.py:46-77`、`src/khoj/routers/helpers.py:1500-1575`、`src/khoj/search_type/text_search.py:99-138,141-206`、`src/khoj/database/adapters/__init__.py:2084-2172`。

- `execute_search()` 的过滤词从向量查询中剥离，但原始 query 仍传给 ORM `apply_filters()`；正负单词使用 `raw__icontains`，文件 glob 转 PostgreSQL regex，日期条件连接 `EntryDates`，owner 条件是 `Q(user=user) OR Q(agent=agent)`。没有 user/agent 时直接返回空 QuerySet。
- `/api/search` 默认把 `max_distance` 传成 `math.inf`；因此 `text_search.query()` 内按模型 `bi_encoder_confidence_threshold` 设置默认距离的分支不会生效于该 API 默认调用。调用方显式传有限距离时才按距离截断。
- `SearchType` 枚举声明包含 `image`、`docx`，但 `search_type_to_embeddings_type` 没有这两个映射，`execute_search()` 的可执行分支也只列 `all/org/markdown/github/notion/plaintext/pdf`；不能把“枚举存在”写成 image/docx 已闭环语义。
- 结果最多先取 10 个候选，再按 `n` 截断；`collate_results()` 同时用 `hashed_value` 和 `corpus_id` 去重，输出原文、距离、来源、文件、URI、compiled 和 heading。rerank 只捕获 `requests.exceptions.HTTPError`，超时/网络异常可能直接上抛；HTTP cross-encoder 失败时用全 0 cross score 继续排序，属于静默降级。
- 查询缓存位于 `state.query_cache[user.uuid]`，key 只有 `query-n-type-r-max_distance-dedupe`，不含 agent、过滤规范化结果、embedding/cross-encoder 模型版本或知识库版本；索引完成时仅按用户重置整个 LRU。相同用户切换 Agent 或模型后可能命中旧结果，这是项目适配层的 P1 缓存失效风险。

**本次复审裁决：** 吸收过滤 DSL、向量召回和可选重排，但把 `SearchRequest/FilterPlan/SearchResponse` 定为唯一检索契约；当前 Khoj 适配层必须补 scope、agent、模型版本、知识库版本和阶段性降级标记，不能由客户端各自复刻过滤语法。

### 24.3 Agent、记忆和模型组合

#### Agent 写入、可见性和知识复制

- `Agent` 数据模型的可配置字段为 `personality/chat_model/input_tools/output_modes/privacy_level/creator/managed_by_admin/is_hidden/slug`；API 创建/修改先调用 `acheck_if_safe_prompt`，再按 `premium` scope 过滤所选 ChatModel。证据：`src/khoj/database/models/__init__.py:248-345`、`src/khoj/routers/api_agents.py:366-510`。
- `AgentAdapters.atomic_update_agent()` 在 `transaction.atomic` 中先 `update_or_create` Agent，再删除该 Agent 的全部 `FileObject/Entry`，从用户同名文件和 Entry 复制快照；Agent Entry 复制 embeddings/raw/compiled/来源/路径/hash，但没有复制 `file_object`、`search_model`、原 `corpus_id`。这是“复制索引快照”而不是共享知识引用。证据：`database/adapters/__init__.py:845-910`。
- 可见性查询对 `public/protected/creator` 的语义并不完全一致：`aget_readonly_agent_by_slug()` 把 protected 对所有用户可读；`get_all_accessible_agents()` 还要求公开 Agent `managed_by_admin=True`；private 仅 creator 可见。`ais_agent_accessible()` 也将 protected 直接视为可访问，调用方必须不要把 protected 当作“需额外授权”的实现。
- 默认 Agent `khoj` 是数据库中的公开、admin-managed Agent，不是纯代码常量；启动时 `create_default_agent()` 会更新其 personality/model，并把无 Agent 的 Conversation 迁移到它。证据：`database/adapters/__init__.py:672-815`。

#### 记忆和对话持久化

`UserMemory` 是独立向量表：最近窗口由 `pull_memories(window=7,limit=10)` 读取，长期查询用默认 search model 的 `CosineDistance`，默认阈值为 `bi_encoder_confidence_threshold`；非默认 Agent 按 `user+agent` 隔离，默认 Agent 的记忆按用户汇总。证据：`database/adapters/__init__.py:2286-2374`。

`PUT /api/memories/{memory_id}` 不是原地更新，而是先按 user 删除旧记录，再用默认搜索模型重新 embed 后创建新记录；删除和重建之间无事务。空 `raw` 返回 400，找不到或跨用户返回 404。证据：`routers/api_memories.py:43-114`。

`Conversation.conversation_log` 是 JSON；`save()` 通过 `ChatMessageModel` 校验 `chat` 数组，`messages` 读取时会清理 inferred queries、把 message 转字符串并跳过坏消息；`pop_message(interrupted=True)` 会删除最后一个“by=khoj 且 message 为空”的部分消息并持久化。证据：`database/models/__init__.py:658-729`。

#### 模型选择与 fallback

```text
Agent/用户/订阅/fast-deep/vision
  → ConversationAdapters.aget_default_chat_model
  → aget_chat_model_slot + aget_chat_models_with_fallbacks
  → primary + 按 ServerChatSettings.priority 去重的 fallback models
  → 生成受 max_prompt_size 限制的 ChatMessage
  → provider adapter(OpenAI/Anthropic/Google)
  → ResponseWithThought/结构化输出/工具调用
```

证据：`src/khoj/routers/helpers.py:1578-1729`、`src/khoj/database/adapters/__init__.py:1266-1477`、`src/khoj/processor/conversation/utils.py:101-158`。

- `send_message_to_model_wrapper()` 先选主模型；带图片且主模型无 vision 时切换到第一个 vision-enabled 模型；再根据订阅和 `fast` 三态选择 slot，把主模型从 fallback 列表剔除。
- 每个模型独立按其 `max_prompt_size/subscribed_max_prompt_size` 重新构造上下文；模型 provider 由 `ChatModel.model_type` 分发。可重试异常包括 OpenAI timeout/rate-limit/server error、Anthropic rate/API error、Google 429/500/502/503/504、httpx timeout/network 和空响应 `ValueError`；全部候选失败才抛 `RetryableModelError`。
- OpenAI 的底层 completion/responses 还有 tenacity 的 provider 内重试（源码可见 `processor/conversation/openai/utils.py:83-94,275-...`），外层再做 model fallback；这不是“每个错误都 fallback”，非 retryable 异常立即抛出。
- `send_message_to_model_wrapper_sync()` 只选一个默认模型，没有异步 wrapper 的 fallback 链；自动化的 `should_notify()`、`format_automation_response()` 走该同步路径，模型失败时通知判断反而默认返回 `True`。
- `ChatModel.ai_model_api` 在模型调用前被直接解引用；配置缺失时可能在 fallback 之前抛属性错误。模型列表、key/base URL 和本地 embedding/cross-encoder 初始化失败主要靠日志，未形成统一 provider 状态。

**本次复审裁决：** 吸收 `Agent = persona + knowledge snapshot + model + tools + output modes` 的组合思想；平台契约必须把知识引用/快照、memory scope、model attempt、fallback reason、tool permission 分开。不能把 Khoj 复制索引和同步通知 fallback 当作无损的通用实现。

### 24.4 调度、自动化与通知：执行证据并不完整

```text
POST /api/automation 或对话中的 schedule_query
  → cron/query/subject 规范化
  → Conversation + APScheduler DjangoJobStore Job
  → 唯一 job_id=automation_{user.uuid}_{md5(query_to_run_crontime)}
  → run_with_process_lock(SCHEDULED_JOB_...)
  → scheduled_chat 的 HTTP POST /api/chat
  → should_notify(model) → format_automation_response(model)
  → Resend send_task_email（可选）
```

证据：`src/khoj/routers/api_automation.py:25-243`、`src/khoj/routers/helpers.py:2525-2750`、`src/khoj/database/adapters/__init__.py:2185-2271`。

- `main.run()` 建立 `BackgroundScheduler + DjangoJobStore`，默认 UTC、`misfire_grace_time=60`、`coalesce=true`；只有取得 `ProcessLock(Operation.SCHEDULE_LEADER)` 的进程启动非 paused scheduler，其他 worker paused。`wakeup_scheduler()` 每 17 分钟检查/重建最长 12 小时的 leader lock，并 pause/resume/wakeup。
- HTTP automation POST 先拒绝空 query/cron、非法 cron、分钟字段非数字（即每 X 分钟），最多取五段并把 `?` 改为 `*`；同步 `schedule_automation()` 对未知 timezone 回退 UTC，但 `aschedule_automation()` 直接 `pytz.timezone()`，两条路径失败语义不同。jitter=60，`max_instances=2`，job 元数据写 JSON 的 `name`，执行历史只通过 `DjangoJobExecution(status="Executed")` 查询最近成功时间。
- `scheduled_chat()` 通过 `requests.post()` 回调本机 `/api/chat`，没有 timeout 或 tenacity retry；非 200 只记日志并返回 `None`。它再调用模型判断是否通知，判断失败时默认通知；Resend 未配置时只返回格式化文本，调度器没有把该文本写入执行账本。`send_task_email()` 的 provider accepted/failed/disabled 结果未形成 API 可读记录。
- 手动 `POST /api/automation/trigger` 直接在新的裸 `threading.Thread` 中执行 job 函数，HTTP 200 只代表线程启动；线程不 join、不返回 execution id，也没有客户端取消/状态查询。job 内的 `run_with_process_lock` 仍会防止同一 `SCHEDULED_JOB` 并发，但锁竞争/异常只写日志。
- `ProcessLockAdapters.run_with_lock()` 是“先查询锁→再 create”的竞态保护，依靠唯一约束的 `IntegrityError` 兜底；函数异常 finally 删除本进程锁。锁超时由 `is_process_locked()` 直接删除旧记录，没有 fencing token/owner 代次，长任务超过 lease 后存在旧 worker 与新 worker 重叠风险。

**本次复审裁决：** 吸收“APScheduler + DB JobStore + leader lock + notification provider”分层，不吸收裸线程 fire-and-forget。通用 `ScheduledTask/ExecutionRecord/NotificationResult` 必须可读回 job、尝试、结果、回执、重试/死信和取消状态；当前 Khoj 只具备 Job/部分 DjangoJobExecution 和日志证据。

### 24.5 数据库、认证和 API 边界

#### 数据库事实

- `Entry` 与 `UserMemory` 使用 `pgvector.django.VectorField(dimensions=None)`；`Entry` 还保存 raw/compiled/heading/source/type/path/url/hash/corpus/search_model/file_object。`FileObject` 保存全文；`EntryDates` 有 date 索引；`Conversation` 以 UUID 主键保存 JSON 日志；`ProcessLock.name` 唯一。证据：`src/khoj/database/models/__init__.py:658-864`。
- PostgreSQL/pgvector 是默认硬依赖；`CONN_MAX_AGE=0`、健康检查和连接清理 middleware 是混合同步/异步 ORM 的补偿机制。`AsyncCloseConnectionsMiddleware` 在请求前后跨两种线程调用 `close_old_connections()`，关闭连接配置打开时 finally 再 close_all。证据：`src/khoj/configure.py:69-95`。
- `Entry.save()` 只做 user/agent 互斥校验而没有调用 `super().save()`；批量写入绕过该方法。这个源码事实必须作为数据库写入风险保留，不能假设普通 `save()` 会持久化。
- `Entry`、`FileObject`、`UserMemory` 没有由模型字段表达完整的“索引任务版本/状态/失败原因/幂等键”；`Entry.hashed_value` 也不是声明为唯一。删除、重建、复制和 memory 更新都是多步操作，部分成功只能靠现存日志推断。

#### 认证和路由契约

`configure_routes()` 按 `/api`、`/api/chat`、`/api/agents`、`/api/automation`、`/api/model`、`/api/memories`、`/api/content`、`/api/notion` 挂载 router；非 anonymous mode 才挂 `/auth`，billing/Twilio 按配置挂载。认证 backend 依次处理 Django session、Bearer `KhojApiUser` token、WhatsApp `client_id/client_secret/phone_number`，anonymous mode 使用 default user；数据库异常在认证阶段返回 503。证据：`src/khoj/configure.py:98-230,319-357`。

| API 族 | 写入/执行 | 真实失败语义 |
|---|---|---|
| `/api/search` | 同步 query embedding + ORM cosine search | 空 query 返回空列表；模型/DB/重排异常可上抛；默认 distance 为 `inf` |
| `/api/content` | 上传解析、线程池索引、ORM bulk write | 不支持类型跳过；解析/批次失败可能部分成功；总异常返回 500 `Failed` |
| `/api/chat` | HTTP `StreamingResponse` 或非流式 `read_chat_stream` | 文档/在线/网页/代码/Operator 各自失败时尽量降级到无该上下文；模型非 retryable 错误中止；WebSocket 断连保存空响应部分消息 |
| `/api/agents` | prompt 安全检查、订阅模型选择、atomic update 与知识快照复制 | 安全/权限/验证失败 400；找不到 404；复制删除重建无独立任务状态 |
| `/api/automation` | DB JobStore + scheduler；手动 trigger 裸线程 | cron/所有权错误 400/403；运行失败日志化；HTTP 200 不等于任务成功 |
| `/api/memories` | 删除旧 memory 后重新 embedding 创建 | 空内容 400、跨用户/不存在 404；embedding/DB 异常可能留下已删除旧 memory |
| `/api/transcribe` | 临时文件 + Whisper/OpenAI | >10 MB 为 422；未配置模型为 501；`finally` close/remove 临时文件 |

API 层还存在几个不能被“路由已注册”掩盖的边界：

- `/api/content/file` 先取 `aget_file_objects_by_name(...)[0]`，再判断对象是否为空；不存在文件时空列表会先触发 `IndexError`，源码中的 404 分支并不能覆盖这个情况。证据：`src/khoj/routers/api_content.py:346-376`。
- `/api/content/type/{content_type}` 与 `/api/content/source/{content_source}` 对非法值直接 `raise ValueError`，不是统一的 4xx 错误；`/api/update` 同步执行 `initialize_content`，没有为该手动更新入口显式包 `INDEX_CONTENT` 锁，可能与定时更新并发。
- `/api/chat` 的 HTTP 流由 `event_generator` 生成；正常完成在发出结束事件前把 `save_to_conversation_log` 放入 `asyncio.create_task`，WebSocket 会限制每用户并发连接并在 finally 注销；断连监视器则用 `asyncio.shield` 保存空响应和已收集上下文。证据：`src/khoj/routers/api_chat.py:742-833,1440-1478,1481-1582`。
- API 认证不是单一 Bearer：session、Khoj token、WhatsApp client credential 和 anonymous default user 共享同一 `AuthenticatedKhojUser` 包装；DB 异常在认证阶段映射 503，但认证成功后的各 router 对 provider/ORM 异常映射并不统一。

### 24.6 失败恢复矩阵（源码实现 vs 待补契约）

| 故障 | 当前源码动作 | 当前是否可恢复/可读回 |
|---|---|---|
| 单文件解析失败 | 记录日志，跳过文件，继续同类型 | 可通过重试请求恢复；无 per-file 结果/失败表 |
| 内容类型失败 | `configure_content` 标记 `success=False`，继续其他类型 | 调用方收到总体失败，但无 checkpoint；已写类型不回滚 |
| embedding HTTP 失败 | HuggingFace/OpenAI embedding 对 HTTPError 最多 5 次 tenacity；其他异常不统一 | 有界重试但无 provider attempt 记录，局部批次可能已写 |
| DB bulk 写入失败 | 记录该批并继续后续批次 | 部分索引可能存在；无事务级重建标记 |
| 查询 cross-encoder HTTPError | cross score 全 0，继续 bi-encoder 结果排序 | 有降级结果但无响应字段说明“未重排”；超时/网络异常不一定降级 |
| 文档/在线/网页工具失败 | chat generator 发送状态并去掉该上下文继续生成 | 对话可继续；结果中没有统一 provider error code |
| 模型 retryable 失败 | 当前模型 tenacity 后切 fallback；全部失败抛 `RetryableModelError` | fallback 可发生；无持久化每次尝试/最终模型记录（tracer 仅局部） |
| 模型 non-retryable/配置空 | 立即抛异常或属性错误 | 请求失败；没有统一 `MODEL_UNAVAILABLE` 映射 |
| Chat HTTP 断连/WS 中断 | `cancellation_event`，shield 保存空响应和已收集上下文；恢复下一轮时 `pop_message(interrupted=True)` | 有部分恢复链；仅“空响应 by=khoj”可识别 |
| Chat 正常完成 | `asyncio.create_task(save_to_conversation_log(...))` 后发送结束事件 | 响应先完成，保存任务崩溃可能静默丢最终消息 |
| scheduler worker 崩溃/leader 过期 | 12 小时锁过期后 `wakeup_scheduler` 重新取得并 resume | 有接管机制；无 fencing/执行账本，可能重复或重叠 |
| automation callback 超时/非 200 | `requests.post` 无 timeout；非 200 日志后返回 None | 线程/任务看似执行结束；无重试、死信或用户可查状态 |
| memory 更新中断 | 先 delete 后 embed/create | 旧 memory 已丢失；没有事务或补偿任务 |
| 图片/音频临时文件 | 正常/异常走 finally remove | 强杀残留未验证；没有启动时清扫 |

### 24.7 资源生命周期、契约和验证等级

| 资源 | 创建/持有 | 正常释放 | 取消/崩溃缺口 |
|---|---|---|---|
| PostgreSQL 连接 | Django ORM、JobStore、sync/async bridge | middleware/decorator `close_old_connections` | 真实 DB 重启、锁和半事务未实跑 |
| 上传/解析临时文件 | PDF/DOCX `NamedTemporaryFile`；image/audio 相对路径文件 | parser/audio finally remove | 宿主强杀后的残留扫描未实现/未验证 |
| embedding/LLM 客户端和模型 | `initialize_server` 写全局 `state`，OpenAI client 字典缓存 | 进程退出；无统一 close/reload | OOM、模型版本切换、热重载和多 worker 状态隔离未验证 |
| ThreadPool / 手动 automation thread | content executor、裸 trigger thread | 线程自然结束 | 无任务句柄、取消、join、崩溃回收或状态投影 |
| APScheduler/ProcessLock | `BackgroundScheduler`、DB lock | shutdown + finally 删除锁 | lease 过期重叠、fencing 和强杀接管未实跑 |
| HTTP/WebSocket stream | generator、disconnect monitor、interrupt queue | END event/取消 monitor/连接注销 | 正常保存是 fire-and-forget，buffer 延迟任务存在取消竞态 |
| MCP/sandbox/operator | `processor/tools` 与 `processor/operator` 创建外部会话/容器 | 各模块局部 close/stop | 未实跑连接失败、子进程孤儿、容器残留和权限回收 |

**真假验证分级：** 当前审计只做了目标源码静态读取和历史研究逐条核对；没有安装依赖、启动 PostgreSQL/pgvector、启动 Compose、调用任何模型/Notion/GitHub/搜索/沙箱/MCP/Resend、执行 pytest/ruff/mypy、构建客户端或做多 worker 强杀。因此上表的“当前动作”是源码存在证据，不是运行通过证据。现有测试文件存在不等于外部 provider 通过；`skipif`、日志、HTTP 200、线程已启动和历史二进制都不能升级为成功。

### 24.8 本次复审最终裁决与待核清单

- **吸收**：多格式解析→统一 Entry→hash 增量→pgvector 召回；过滤 DSL→ORM 过滤→可选 cross-encoder；Agent 的人设/知识快照/模型/工具；APScheduler/DjangoJobStore/leader lock；多 provider model fallback；HTTP/WS 流式事件和断连部分保存。
- **升级候选**：内容索引任务账本与 checkpoint、统一 SearchRequest/FilterPlan/结果降级状态、AgentSpec 与知识引用/快照版本、ModelCall attempt/fallback 证据、ScheduledTask/ExecutionRecord/NotificationResult、统一 error code/retry/timeout/cancel/cleanup。
- **隔离/废弃为底座模式**：模块级全局 state、`database/adapters/__init__.py` 聚合巨型适配器、Entry/Agent 的复制式知识同步、裸 automation thread、无 timeout 的本机 HTTP callback、具体 Resend/Compose/第三方 SDK 直连。
- **待核**：正确的远程最新版本差异、`image/docx` 检索闭环、Agent protected 权限是否产品期望、Entry `bulk_create`/`save()` 的生产行为、索引删除/重建的事务边界、leader fencing、scheduler 执行重复、chat 最终保存失败、外部工具子进程/容器残留以及真实 provider 错误/重试/送达回执。

本节完成“本次复审收口”的定义：历史研究的每条结论都有吸收、细化或降级位置；内容摄取、检索、Agent、调度、模型、数据库、API 和失败恢复均有源码调用链、资源边界和未验证项；没有把静态源码证据冒充真实运行通过，也没有修改 Khoj 源码、依赖、配置、测试、README 或 Git。
