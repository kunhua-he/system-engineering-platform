# MaxKB 架构建档

> 本文件是 MaxKB 项目的唯一权威架构文档。`细探-MaxKB.md` 保留为历史细探和证据线索；已核实内容已吸收到本文，后续架构维护只更新本文，不把旧细探作为第二事实源。

## 1. 文档定位与证据边界

本文是对本地 `MaxKB` 仓库的首轮全量架构建档，基线为本地 `v2` 工作树，而不是远端最新代码。

- 项目：`1Panel-dev/MaxKB`
- 本地根目录：`~/Documents/Agent/github 源码参考/15_知识库系统/MaxKB`
- 本地分支：`v2`
- 本地 `HEAD`：`5084a37a372fd7b2a4f5ea7c6643b743a50b415a`（`fix: Knowledge base zip upload file authorization error (#6507)`）
- 许可证：GPLv3，见 `LICENSE` 与 `README.md:61-67`；`README_CN.md:82-90` 亦声明 GPLv3。
- 直接证据优先级：`CLAUDE.md`、源码/路由/模型/配置、`pyproject.toml`、`ui/package.json`、安装脚本；`README*` 与 `细探-MaxKB.md` 用作定位说明，不能替代源码事实。

### 证据限制

- 专属 `project_context` 返回的是另一项目“华世王镞_v3”及其根目录，不是本项目；不能将该上下文中的项目代码地图或状态作为 MaxKB 证据。
- 对 MaxKB 执行 `codegraph_explore` 时，服务明确返回：目标目录没有 `.codegraph/`，项目未建立 CodeGraph 索引；因此本文未使用代码地图结论，改用仓库文件直接读取。
- 仓库已有 `细探-MaxKB.md`，本文吸收其中有效架构线索，但以当前源码复核结果为准。
- 当前核对禁止安装、启动、构建和运行测试；“测试”章节记录的是仓库中可见的测试形态，不是运行结果。

## 2. 项目定位

MaxKB（Max Knowledge Brain）是一个面向企业的智能体平台：以知识库 RAG 为基础，向上提供可视化工作流、工具/MCP 调用、模型供应商接入、多模态能力和第三方嵌入式聊天入口。仓库是一个 Python/Django 单仓库，前端 `ui/` 是 Vue 3/Vite 双 SPA，后端和前端共同由容器镜像交付。

README 宣称的能力包括：

- 文档上传/在线文档抓取、文本拆分、向量化和知识库问答；
- 应用级 Agentic Workflow、工具库、MCP；
- OpenAI、Claude、Gemini、DeepSeek、Qwen、Ollama、vLLM 等多供应商模型；
- 文本、图像、音频、视频输入输出；
- `/admin` 管理端和 `/chat` 对话端，可嵌入第三方系统。

## 3. 总体架构

```text
浏览器 / 第三方业务系统 / OpenAI-compatible client / MCP client
                         │
                         ▼
              Django + DRF HTTP 入口（端口 8080）
             ┌──────────────────────┬──────────────────────┐
             │ /admin/api/*          │ /chat/api/*          │
             │ 管理面 API             │ 对话/嵌入/API 调用     │
             └──────────┬───────────┴──────────┬───────────┘
                        │                      │
                        ▼                      ▼
           users / knowledge / application / tools / trigger / ...
                        │                      │
                        ├── PipelineManage（旧线性流水线）
                        └── WorkflowManage（图工作流，异步节点并行）
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        knowledge RAG     models_provider     tool/MCP/多模态
        拆分/Embedding     供应商路由           节点与外部服务
              │                │                │
              └───────────────┼────────────────┘
                              ▼
                 PostgreSQL 17 + pgvector + Redis
                              │
                  Celery worker / local_model runtime
```

运行时有两个 Django 设置集合：

1. `SERVER_NAME=web`（默认）：完整管理端、对话端、知识库、应用、工具、模型供应商和异步任务。
2. `SERVER_NAME=local_model`：最小化本地模型服务，只加载 `local_model`，提供 embedding/reranker 相关内部 API。

选择发生在 `apps/maxkb/urls/__init__.py:9-14` 和 `apps/maxkb/settings/__init__.py:9-13`：当 `SERVER_NAME=local_model` 时分别导入 `model` URL/settings，否则导入 `web`。

## 4. 目录与模块边界

```text
MaxKB/
├── main.py                         # 统一启动/迁移/静态资源入口
├── pyproject.toml                  # Python 依赖、uv/PyTorch 源、ruff
├── CLAUDE.md                       # 开发命令与架构说明
├── README.md / README_CN.md        # 项目定位、Docker 快速启动、技术栈
├── apps/
│   ├── maxkb/                      # Django settings、URL、常量、配置
│   ├── common/                     # 公共认证、异常、结果、数据库、文件、事件、响应
│   ├── users/                      # 用户、登录、验证码、成员管理
│   ├── application/                # 应用、版本、聊天记录、Agent 执行
│   ├── knowledge/                  # 知识库、文档、段落、问题、术语、向量和异步任务
│   ├── models_provider/            # 模型数据库实体、供应商抽象和供应商实现
│   ├── local_model/                # 本地 embedding/reranker 服务端 API
│   ├── chat/                       # 对话、OpenAI 兼容接口、MCP、匿名认证
│   ├── tools/                      # 工具、工具工作流、代码/技能文件
│   ├── trigger/                    # Webhook/触发器/任务记录
│   ├── system_manage/              # 工作空间资源权限、系统配置
│   ├── folders/                    # 应用/知识库/工具目录树
│   ├── homepage/                   # 首页聚合、统计、排行
│   ├── oss/                        # 文件上传、下载、公开访问
│   ├── ops/                        # Celery app 和任务运行支撑
│   └── locales/                    # `en_US`、`zh_CN`、`zh_Hant` 翻译
├── ui/
│   ├── src/                        # Vue 3 管理端与聊天端共享源码
│   ├── env/                        # Vite 环境文件
│   ├── vite.config.ts              # 双模式入口、代理、输出目录
│   └── package.json                # 前端依赖和脚本
├── installer/
│   ├── Dockerfile                  # 前端构建 + Python 运行镜像
│   ├── Dockerfile-base             # PostgreSQL/Redis/pgvector 基础镜像
│   ├── Dockerfile-vector-model     # 向量模型镜像构建链
│   ├── start-all.sh                # 容器内 PostgreSQL、Redis、MaxKB 编排
│   ├── start-maxkb.sh              # 初始化目录后执行 `main.py start`
│   ├── start-postgres.sh / start-redis.sh
│   ├── init.sql                    # 创建 `maxkb` 数据库和 vector 扩展
│   └── sandbox.c                   # 沙箱动态库源码
└── 细探-MaxKB.md                   # 既有人工细探记录
```

本地源码规模（排除 `.git`、`node_modules`、`dist` 的目录扫描）：约 2,189 个文件，其中约 1,047 个 `.py`、505 个 `.vue`、327 个 `.ts`；`apps/` 下 16 个业务/支撑目录。规模用于定位，不是发布构建产物统计。

## 5. 启动、运行时与部署

### 5.1 统一入口

`main.py` 是后端唯一主入口，不直接以 `manage.py` 作为服务启动入口：

- `main.py:10-15` 计算项目目录、切换工作目录、把 `apps/` 放入 `sys.path`，并设置 `DJANGO_SETTINGS_MODULE=maxkb.settings`。
- `main.py:18-29` 的 `collect_static()` 执行 Django `collectstatic`，异常被忽略。
- `main.py:32-63` 的 `perform_db_migrate()` 执行 `migrate`，数据库启动恢复阶段最多重试 10 次，每次间隔 5 秒，最终失败退出码为 11。
- `main.py:89-99` 的 `dev()` 分别运行 Django web、Celery 管理命令或本地模型服务。
- `main.py:113-147` 支持 `start`、`dev`、`upgrade_db`、`collect_static`；`start` 和 `dev` 都会先收集静态文件并迁移数据库。

`CLAUDE.md` 中列出的常用命令：

```bash
python main.py dev                 # web，0.0.0.0:8080
python main.py dev celery          # Celery worker
python main.py dev local_model     # 本地模型，默认 127.0.0.1:11636
python main.py start all -d
python main.py upgrade_db
python main.py collect_static
```

### 5.2 容器编排

- `installer/Dockerfile:1-7` 以 `node:24-alpine` 构建 `ui` 的管理端和 chat 端，再复制到 Python 运行阶段。
- `installer/Dockerfile:9-25` 在 `ghcr.io/1panel-dev/maxkb-base:python3.11-pg17.10-20260525` 上安装 Python 依赖、编译 `sandbox.so`、编译翻译文件，并清理源码/安装器。
- `installer/Dockerfile:27-57` 设置数据库、Redis、本地 embedding 模型、沙箱路径，暴露 8080，入口为 `/usr/bin/start-all.sh`。
- `installer/Dockerfile-base:4-36` 引入 PostgreSQL 17、pgvector、Redis、本地模型，写入 `init.sql`，设置 `MAXKB_CONFIG_TYPE=ENV` 和沙箱环境。
- `installer/start-all.sh:12-36`：当数据库/Redis 地址为 `127.0.0.1` 时在容器内启动 PostgreSQL/Redis，随后启动 MaxKB，并以 `wait -n` 维持容器生命周期；不支持从 v1 数据目录直接升级（第 5-9 行）。
- `installer/start-maxkb.sh:15-26` 执行用户初始化 shell 后运行 `python /opt/maxkb-app/main.py start`。
- `installer/init.sql:1-4` 只创建数据库和 `vector` 扩展，业务表由 Django migrations 管理。

### 5.3 运行时配置

`apps/maxkb/const.py:11-23` 定义 `BASE_DIR`、`PROJECT_DIR`、版本 `2.0.0` 和 `CONFIG`；`apps/maxkb/conf.py:22-140` 提供默认值和配置映射：

- 数据库：`DB_*`，引擎默认 `dj_db_conn_pool.backends.postgresql`，连接池 `POOL_SIZE=20`、`MAX_OVERFLOW=DB_MAX_OVERFLOW`；
- 缓存：Redis `REDIS_*`，支持 Redis Sentinel；
- 服务路径：`ADMIN_PATH` 默认 `/admin`，`CHAT_PATH` 默认 `/chat`；
- 本地模型：`LOCAL_MODEL_HOST` 默认 `127.0.0.1`、`LOCAL_MODEL_PORT` 默认 `11636`；
- 沙箱：`SANDBOX_*`；
- 语言：`LANGUAGE_CODE`、外置语言包路径等。

`ConfigManager` 在 `apps/maxkb/conf.py:244-257` 依据 `MAXKB_CONFIG_TYPE` 选择配置文件或环境变量；`MAXKB_CONFIG_TYPE=ENV` 时，将所有 `MAXKB_*` 环境变量去掉前缀后进入配置。`apps/maxkb/settings/base/web.py:30-49` 加载完整应用，`settings/base/model.py:31-37` 只加载 `local_model`。

## 6. HTTP/API 架构

### 6.1 根路由

`apps/maxkb/urls/web.py:32-52` 根据 `CONFIG.get_admin_path()` 与 `CONFIG.get_chat_path()` 生成两组 API 前缀：

- 管理面：`/admin/api/`，包含 `users`、`tools`、`models_provider`、`folders`、`knowledge`、`system_manage`、`application`、`trigger`、`oss`、`homepage`；
- 对话面：`/chat/api/`，包含 `oss`、`chat`；
- UI：`/admin/`、`/chat/`，由 `oss.retrieval_urls` 和静态资源/404 回退提供；
- 生产模式附加 API 文档静态资源，见 `web.py:55-80`。

`apps/maxkb/urls/model.py:22-28` 在 `local_model` 运行时只挂载 `local_model.urls`。

### 6.2 主要 API 分区

| 分区 | 代表路径（相对于 `/admin/api/` 或 `/chat/api/`） | 作用 |
|---|---|---|
| 用户 | `user/login`、`user/profile`、`user_manage/*` | 登录、验证码、用户及成员管理，见 `apps/users/urls.py:8-30` |
| 应用 | `workspace/<workspace_id>/application/*`、`chat_message/<chat_id>` | 应用配置、发布、版本、密钥、统计、聊天，见 `apps/application/urls.py:8-47` |
| 知识库 | `workspace/<workspace_id>/knowledge/*` | 知识库、工作流、文档、段落、问题、术语、标签、导入导出、命中测试，见 `apps/knowledge/urls.py:8-103` |
| 对话 | `embed`、`mcp`、`<application_id>/chat/completions`、`chat_message/<chat_id>` | 嵌入端、JSON-RPC MCP、OpenAI-compatible Chat Completions、普通对话，见 `apps/chat/urls.py:10-32` |
| 模型 | `provider/*`、`workspace/<workspace_id>/model/*` | 供应商元数据、模型 CRUD、参数、下载/暂停，见 `apps/models_provider/urls.py:10-23` |
| 工具 | `workspace/<workspace_id>/tool/*` | 工具、工具工作流、调试、导入导出、技能文件、版本，见 `apps/tools/urls.py:8-41` |
| 触发器 | `workspace/.../trigger/*`、`trigger/v1/webhook/<trigger_id>` | 事件触发、任务记录、Webhook，见 `apps/trigger/urls.py:18-30` |
| 文件 | `oss/file`、`oss/get_url/<application_id>` | 文件上传和访问授权，见 `apps/oss/urls.py:7-11` |
| 本地模型 | `model/<model_id>/embed_documents`、`embed_query`、`compress_documents` | 本地 embedding/reranker 内部调用，见 `apps/local_model/urls.py:10-16` |

### 6.3 对话与响应协议

- `apps/chat/views/chat.py:70-90` 以 `ChatTokenAuth` 校验应用 API 调用，并交给 `OpenAIChatSerializer`。
- `apps/chat/views/chat.py:167-191` 的 `ChatView.post()` 将认证身份、应用、聊天、来源和 IP 交给 `ChatSerializers.chat()`。
- `apps/chat/views/chat.py:230-265` 提供 STT/TTS 接口；文件上传使用 `MultiPartParser`，见 `chat.py:268-290`。
- `apps/common/handle/base_to_response.py:14-30` 抽象阻塞响应和流式 chunk，默认流式格式为 `data: <json>\n\n`。
- `apps/application/flow/workflow_manage.py:296-302` 将工作流输出包装为流式响应；`workflow_manage.py:450-477` 为节点输出附带 `node_type`、`runtime_node_id`、`node_status` 等执行详情。

### 6.4 MCP

MaxKB 同时具备 MCP 服务端暴露能力和工作流内 MCP 客户端节点：

- 服务端入口：`apps/chat/urls.py:11-12` 的 `mcp` 路由；`apps/chat/views/mcp.py:9-59` 读取 JSON-RPC `initialize`、`tools/list`、`tools/call`，使用 `Authorization: Bearer ...` 创建 `MCPToolHandler`。
- 应用模型保存 `mcp_enable`、`mcp_tool_ids`、`mcp_servers`、`mcp_source` 等配置，见 `apps/application/models/application.py:97-106`。
- 工作流前端包含 `mcp-node`，后端在 `application/flow/step_node/` 中提供相应节点；Python 依赖包含 `langchain-mcp-adapters`。

## 7. 应用与工作流执行

### 7.1 应用域

`apps/application/models/application.py` 的核心实体：

- `ApplicationFolder`：基于 `MPTTModel` 的工作空间目录树，`application.py:20-33`；
- `Application`：应用名称、发布状态、模型、知识库设置、模型参数、工作流 JSON、工具/MCP/子应用、语音模型、文件上传和长期记忆开关，`application.py:59-113`；
- `ApplicationKnowledgeMapping`：应用与知识库关联，`application.py:133-139`；
- `ApplicationVersion`：发布快照，保存工作流、模型/知识库相关设置和发布者，`application.py:142-197`；
- `Chat`、`ChatRecord`：会话、问题、答案、节点详情、token/费用、投票、来源和 IP，见 `apps/application/models/application_chat.py:33-128`；
- `ApplicationLongTermMemory`：按应用和 `chat_user_id` 唯一的长期记忆，见 `application_chat.py:159-170`。

### 7.2 两套执行引擎

1. **旧线性流水线**：`apps/application/chat_pipeline/pipeline_manage.py:18-66`。通过 builder 按顺序注册 `IBaseChatPipelineStep`，共享 `context`，依次 `step.run()`，最后合并各步骤详情。
2. **图工作流**：
   - 默认定义位于 `apps/application/flow/default_workflow*.json`（默认、英文、简体中文、繁体中文）；
   - `apps/application/flow/common.py:107-194` 将节点/边 JSON 转成 `Workflow`，建立前驱/后继映射并支持工作流模式 `APPLICATION`、`APPLICATION_LOOP`、`KNOWLEDGE`、`KNOWLEDGE_LOOP`、`TOOL`、`TOOL_LOOP`；
   - `common.py:202-250` 校验起始节点、终止节点、模型参数和边；
   - `apps/application/flow/workflow_manage.py:92-145` 初始化上下文、字段和输入资源；
   - `workflow_manage.py:352-377` 通过共享 `ThreadPoolExecutor(max_workers=200)` 运行节点，分支/汇聚依据边和依赖判断；
   - `workflow_manage.py:675-732` 根据断言分支、`AND`/其他条件和依赖节点决定后继；
   - 节点通过 `application/flow/step_node/get_node` 按类型和 workflow mode 工厂化创建。前端节点类型在 `ui/src/workflow/nodes/`，包括 `ai-chat-node`、`search-knowledge-node`、`reranker-node`、`condition-node`、`mcp-node`、`loop-*`、多模态、变量、知识写入等。

### 7.3 工作流上下文与流式结果

工作流维护 `global`、`chat` 和各节点上下文；`workflow_manage.py:734-788` 将节点字段替换为上下文引用并用 `PromptTemplate` 生成提示词。每个节点生成 `NodeChunk`，执行结果被写入 `ChatRecord.details`，同时通过 `BaseToResponse` 输出 SSE chunk。异常可按节点 `enableException` 转为异常分支，或输出错误状态。

### 7.4 节点契约与应用级长期记忆

旧细探提到的 `apps/application/flow/i_step_node.py` 在当前工作树中存在，是节点运行时契约而不是独立的 `backend/` 子系统：`INode` 负责参数校验、上下文、运行计时、`NodeChunk` 和 `Answer`，节点通过 `execute()` 返回 `NodeResult`；同文件的 `WorkFlowPostHandler` 在应用工作流完成后把 `ChatRecord` 写回，并以 `countdown=1` 异步触发 `extract_long_term_memory`。

- `apps/application/long_term_memory/__init__.py` 以 `ApplicationLongTermMemory` 为持久化对象，按 `(application, chat_user_id)` 聚合跨会话记忆；`_run_extract()` 读取 `ChatRecord` 的问题/答案，调用配置的模型流式生成融合后的记忆并覆盖或创建记录。
- 长期记忆配置包含启用开关、模型、模型参数和触发设置。普通应用读取 `Application` 字段，工作流应用读取 `base-node.properties.node_data`；未启用时会删除该用户的已有记忆。
- 触发既支持按对话轮数提取，也支持 APScheduler 的定时任务（daily/weekly/monthly/interval/cron 设置，具体解析逻辑见 `long_term_memory/__init__.py`）。这不是独立的向量记忆库，当前实现是应用+用户维度的文本记忆表。

## 8. 知识库、RAG 与数据模型

### 8.1 领域模型

`apps/knowledge/models/knowledge.py` 的主要表：

| Django 模型 | `db_table` | 作用 |
|---|---|---|
| `KnowledgeFolder` | `knowledge_folder` | 工作空间知识库目录树 |
| `Knowledge` | `knowledge` | 知识库元数据、类型、范围、embedding model、限额 |
| `KnowledgeWorkflow` / `KnowledgeWorkflowVersion` | `knowledge_workflow` / `knowledge_workflow_version` | 知识库工作流及发布版本 |
| `Document` | `document` | 文档、状态、字符数、命中策略 |
| `Tag` / `DocumentTag` | `tag` / `document_tag` | 文档标签 |
| `Paragraph` | `paragraph` | 文档切分后的段落、顺序、状态、chunks |
| `Problem` / `ProblemParagraphMapping` | `problem` / `problem_paragraph_mapping` | 生成问题与段落关联 |
| `Termbase` | `termbase` | 知识库术语 |
| `Embedding` | `embedding` | 向量、全文检索字段、知识库/文档/段落来源 |
| `File` | `file` | 压缩文件内容、PostgreSQL large object、来源授权元数据 |
| `PublicFileAccess` | `public_file_access` | 文件/应用/知识库公开访问授权 |

关键定义证据：`knowledge.py:103-145`、`knowledge.py:148-180`、`knowledge.py:187-214`、`knowledge.py:217-267`、`knowledge.py:270-305`、`knowledge.py:342-383`、`knowledge.py:480-513`。

### 8.2 文档处理与异步任务

- 文档状态是由 `TaskType`（`EMBEDDING`、`GENERATE_PROBLEM`、`SYNC`、`TOKENIZE`）和 `State`（pending/started/success/failure/revoke/revoked/ignored）编码管理，见 `knowledge.py:29-55`、`knowledge.py:67-97`。
- `apps/knowledge/task/embedding.py:43-137` 将段落/文档/知识库向量化任务注册为 Celery task，并通过 `QueueOnce` 避免重复任务；模型由 `ModelManage` 缓存获取。
- `apps/knowledge/task/generate.py:64-107` 将段落内容交给 LLM 生成问题，保存问题后更新任务状态。
- `apps/knowledge/vector/pg_vector.py:29-110` 负责写入、批量写入、删除和启停 embedding；`Embedding` 的 `VectorField.db_type()` 返回 PostgreSQL `vector`，见 `knowledge.py:342-345`。

### 8.3 检索模式

`PGVector.hit_test()` 和 `PGVector.query()`（`apps/knowledge/vector/pg_vector.py:112-193`）按知识库逐库查询并取 top-N，支持：

- `embedding`：pgvector 相似度检索，SQL 位于 `apps/knowledge/sql/embedding_search.sql`；
- `keywords`：PostgreSQL 全文检索，SQL 位于 `keywords_search.sql`；
- `blend`：向量+关键词混合，SQL 位于 `blend_search.sql`。

检索会先按知识库、文档、段落、启用状态过滤，再由 `EmbeddingSearch`、`KeywordsSearch`、`BlendSearch` 实现具体 SQL 参数拼装，见 `pg_vector.py:249-349`。术语表通过 `Termbase` 参与 `tsvector`/查询词处理。

文件内容在 `File.save()` 中压缩写入 PostgreSQL large object（`knowledge.py:385-432`），读取时流式 `lo_get` 并解压（`knowledge.py:434-470`）；删除最后一个引用时用 `lo_unlink` 清理，见 `knowledge.py:473-477`。

## 9. 模型供应商与本地模型

### 9.1 抽象层

`apps/models_provider/base_model_provider.py` 定义三层抽象：

- `IModelProvider`：列出模型类型、模型、凭据，校验凭据，并创建模型实例，见 `base_model_provider.py:46-92`；
- `MaxKBBaseModel`：供应商具体模型的实例化接口，见 `base_model_provider.py:95-112`；
- `BaseModelCredential`：凭据校验、加密和参数表单，见 `base_model_provider.py:114-143`。

`ModelInfoManage`（`base_model_provider.py:198-251`）以 `model_type -> model_name -> ModelInfo` 注册模型；`ModelTypeConst` 支持 `LLM`、`EMBEDDING`、`STT`、`TTS`、`IMAGE`、`TTI`、`RERANKER`、`TTV`、`ITV`（`base_model_provider.py:146-157`）。旧细探列出的基类职责可在当前源码中进一步落到：`impl/base_chat_open_ai.py` 的 OpenAI 兼容聊天基类、`impl/base_stt.py` 的语音转文字、`impl/base_tts.py` 的文字转语音、`impl/base_tti.py` 的文生图，以及 `base_ttv.py` 的文生视频接口；旧文档把 TTV 解读成“文本-工具-视觉”不准确。

当前 `apps/models_provider/impl/` 下可直接核实 22 个 provider 模块（包括 `aliyun_bai_lian`、`anthropic`、`aws_bedrock`、`azure`、`deepseek`、`docker_ai`、`gemini`、`kimi`、`local`、`minimax`、`ollama`、`openai`、`regolo`、`siliconCloud`、`tencent`、`tencent_cloud`、`vllm`、`volcanic_engine`、`wenxin`、`xf`、`xinference`、`zhipu`）。因此“15+ 提供者”只能作为旧版本的概略说法，本文以当前目录和注册常量为准。

### 9.2 供应商注册与持久化

- `Model` 表位于 `apps/models_provider/models/model_management.py:21-49`，保存供应商、模型类型/名称、RSA 加密后的 credential、参数表单、状态、工作空间。
- `ModelProvideConstants` 在 `apps/models_provider/constants/model_provider_constants.py:30-52` 实例化约 22 个供应商，包括 OpenAI、Anthropic、Gemini、DeepSeek、Qwen/阿里云、Ollama、vLLM、Xinference、Azure、AWS Bedrock、腾讯、智谱、MiniMax、本地等。
- `apps/models_provider/tools.py:25-61` 通过 `get_provider()` 路由供应商，解密 credential 后调用 `IModelProvider.get_model()`；`tools.py:120-156` 合并数据库默认参数和调用参数，并由 `ModelManage` 缓存实例。
- 依赖层采用 LangChain 及各供应商适配包，实际模型实现位于 `apps/models_provider/impl/<vendor>_model_provider/`。

### 9.3 local_model 双运行时

`SERVER_NAME=local_model` 使用 `settings/base/model.py` 的最小 `INSTALLED_APPS`，路由只暴露 `local_model`；主 web 运行时通过 `main.py dev local_model` 或容器内独立服务访问 `127.0.0.1:11636`。这使 embedding/reranker 等本地模型进程与完整 web/Celery 进程隔离，但两者共享 PostgreSQL/Redis 配置。

## 10. 异步、调度与任务幂等

- `apps/ops/__init__.py:9` 导出 `ops.celery.app` 为 `celery_app`。
- `apps/common/management/commands/celery.py:17-46` 启动 Celery worker，使用 `-P threads`、并发度 10、队列参数 `celery` 或 `model`，心跳 10 秒且关闭 mingle。
- `CLAUDE.md` 记载 `celery` 通用队列与 `model` 模型/长任务队列；依赖包含 `celery`、`django-celery-beat`、`django-apscheduler`、`celery-once`。
- 知识库 embedding、问题生成等长任务通过 `@celery_app.task` 和 `QueueOnce` 注册；任务状态写回文档 status/status_meta，并支持撤销检查。
- 工作流执行不等同于 Celery：应用请求内由进程级 `ThreadPoolExecutor(max_workers=200)` 并行调度节点；模型/知识库后台任务则走 Celery。

## 11. 前端架构

### 11.1 构建与入口

- `ui/package.json:6-16`：`dev` 启动管理端，`chat` 使用 Vite `chat` mode，`build` 同时执行类型检查和管理端构建，`build-chat` 构建聊天端，另有 `lint` 和 `type-check`。
- `ui/src/main.ts:1-117` 创建 Vue app，接入 Pinia、Vue Router、Vue I18n、Element Plus、公共组件/指令，并配置 Markdown/XSS、KaTeX、Mermaid、highlight.js、Cropper 等。
- `ui/src/router/routes.ts:4-7` 使用 `import.meta.glob('./modules/*.ts', { eager: true })` 加载权限路由；同时定义首页、应用/知识库/工具工作流、聊天、登录、错误页面等路由。
- `ui/vite.config.ts:34-115` 依据 `VITE_ENTRY`、`VITE_BASE_PATH`、`VITE_APP_PORT` 选择入口和输出路径，开发端口代理 `/admin/api`、`/chat/api`、`/doc`、`/schema`、`/static` 到 `127.0.0.1:8080`。

### 11.2 管理端、聊天端与工作流画布

前端源码是一套共享依赖、两种 Vite mode 的 SPA：

- 管理端路由模块覆盖应用、知识库、文档、模型、工具、系统、触发器和权限；
- `/chat/:accessToken` 与 `/user-login/:accessToken` 是嵌入式聊天入口；
- `ui/src/workflow/index.vue` 和 `ui/src/workflow/nodes/` 提供可视化节点编辑，节点类型与后端 `step_node` 工厂需保持字符串契约一致；
- LogicFlow 负责工作流图编辑，Element Plus 负责管理界面，Pinia stores 管理 application/knowledge/model/tool/user 等状态。

## 12. 数据库、迁移与持久化边界

- 数据库是 PostgreSQL，向量扩展为 `pgvector`；`installer/init.sql` 只做数据库和扩展初始化。
- 业务模型集中在各 app 的 `models/`，迁移集中在各 app 的 `migrations/`；本地已见 application、knowledge、tools、system_manage、trigger、users、models_provider 等迁移。
- `settings/base/web.py:133-138` 将 `CONFIG.get_db_setting()` 和 `CONFIG.get_cache_setting()` 注入 Django；数据库连接使用连接池后端，Redis 使用 `django-redis`。
- 重要持久化对象包括：应用配置/版本、知识库文档/段落/问题/向量、聊天/聊天记录、模型供应商配置、工具/触发器/权限、文件 large object。
- 业务标识主要使用 UUID/UUIDv7；目录树使用 `django-mptt`；JSONField 承担工作流、模型参数、元数据和节点详情等可变结构。

## 13. 安全与权限边界

- DRF 默认认证类为 `common.auth.authenticate.AnonymousAuthentication`，聊天 API 额外使用 `ChatTokenAuth`；用户/工作空间/资源权限由 `users`、`system_manage` 和公共权限常量协同处理。
- 模型 credential 在 `models_provider.tools.get_model_()` 中先用 `rsa_long_decrypt` 解密后交给供应商；前端展示使用 credential 的掩码/参数表单机制。
- 文件访问通过 `oss` 和 `PublicFileAccess` 约束；chat 端认证 token 通过 cookie/Authorization 等方式传递。
- 工具节点可能执行用户提供的 Python/脚本代码；`installer/sandbox.c` 编译为 `sandbox.so`，Docker 环境设置 sandbox 用户、包路径、禁用关键字/主机，配置来源见 `Dockerfile-base:46-52` 与 `CLAUDE.md`。
- `ALLOWED_HOSTS=['*']` 位于 `settings/base/web.py:21-27`，生产部署应依赖外层网络/反向代理与实际配置进行收敛；本文不做安全整改。

## 14. 测试、质量门与当前可验证性

- `CLAUDE.md` 明确说明没有配置独立测试运行器，各 app 的 `tests.py` 是空模板。
- 已读取 `apps/application/tests.py`、`apps/knowledge/tests.py`、`apps/chat/tests.py`、`apps/users/tests.py`：均只有 `django.test.TestCase` 导入和注释，没有行为测试。
- 本地未发现 `test_*.py`；本地根目录也未发现 `uv.lock`，虽然 `CLAUDE.md` 将依赖管理描述为 `uv` 并提到 `uv.lock`，这是文档与当前工作树的可见漂移。
- `pyproject.toml:89-90` 只配置 Ruff 行长 120；`ui/package.json:14-16` 提供 `vue-tsc`、ESLint、Prettier 命令，但当前核对未执行。
- 因任务约束，当前核对未安装依赖、未启动 PostgreSQL/Redis/Django/Celery/Vite、未构建镜像或前端、未执行迁移和测试；本文结论为静态源码建档，不是运行时验收。

## 15. 远端版本漂移

远端 `origin` 为 `https://github.com/1Panel-dev/MaxKB.git`。本地缓存的 `origin/v2` 与本地 `HEAD` 显示 0/0 差异，但通过 `git ls-remote origin refs/heads/v2` 读取到远端最新提交为：

```text
b10105d2677ddb829480ac37c8ee96fa5829a816
```

因此本地工作树相对远端实际 `v2` 落后。按要求，仅通过 `127.0.0.1:4780` 下载了远端提交的独立 tar 快照到 `/tmp/MaxKB-remote-v2`，未覆盖工作树、未合并远端文件。远端快照约 2,191 个文件，且存在以下与架构文档相关的漂移：

- 新增 `apps/application/migrations/0014_applicationversion_knowledge_ids.py`，把应用版本与 `system_manage.ResourceMapping` 的知识库映射迁移到 `ApplicationVersion.knowledge_ids`；本地基线没有该迁移。
- `pyproject.toml`：远端升级 `django` 5.2.16、`torch` 2.13.0、`pypdf` 6.15.0、`cryptography` 50.0.0，并新增 `mcp==1.28.1`；本地仍以 `pyproject.toml` 当前内容为准。
- `ui/package.json`：远端将 `pdfjs-dist` 更新到 `^6.2.108`。
- `apps/maxkb/urls/web.py`：远端为两组 `oss` 和 retrieval URL 加 namespace，说明文件路由命名隔离正在演进。
- 远端还修改了若干聊天、工作流、文件解析、共享资源授权及安全校验文件；未将这些未合入工作树的实现写成本地当前事实。

## 16. 架构结论、风险与后续阅读顺序

### 结论

MaxKB 的核心是“Django 多 app 业务层 + PostgreSQL/pgvector 知识层 + Redis/Celery 异步层 + LangChain 多供应商模型层 + Vue/LogicFlow 前端编排层”。`Application` 是 Agent 配置和运行聚合根，`Knowledge` 是 RAG 资源聚合根，`Workflow` 是跨应用/知识库/工具复用的图执行协议；`models_provider` 将外部模型差异隔离在供应商适配层。

### 主要风险/注意事项

1. **基线风险**：本地落后远端实际 `v2`；实现、依赖和路由命名不能直接代表最新版本。
2. **上下文工具风险**：专属 MCP 的项目上下文绑定到了其他项目，CodeGraph 对目标未索引；后续分析必须继续以目标绝对路径的直接文件为准。
3. **配置风险**：`SERVER_NAME` 决定加载完整 web 还是最小 local_model；错误设置会让进程加载错误的应用集。
4. **执行并发风险**：工作流使用进程级 `ThreadPoolExecutor(max_workers=200)`，节点又可能调用外部模型和数据库；需在运行时评估连接池、线程数和请求生命周期。
5. **数据边界风险**：`JSONField` 承载工作流、参数、节点详情等大量契约；前后端节点类型、字段名和版本迁移必须同步。
6. **测试缺口**：仓库可见 app 测试为空模板，静态建档不能证明 API、RAG、MCP、迁移、权限或工作流运行正确。
7. **安全配置风险**：默认/基础镜像包含默认数据库密码，`ALLOWED_HOSTS=['*']`；生产必须核对环境覆盖和外部入口防护。
8. **远端合并风险**：远端已有 `ApplicationVersion.knowledge_ids` 数据迁移和 MCP/文件安全相关变更；若以后更新本地，需单独审查迁移顺序、数据回填和 URL namespace 兼容性。

### 推荐细探顺序（不代表当前核对已执行）

1. `apps/application/flow/step_node/`：节点协议、节点工厂、分支/循环/异常语义；
2. `apps/chat/serializers/` 与 `application` 聊天 API：请求、认证、ChatRecord 落盘和 SSE 协议；
3. `apps/knowledge/task/`、`common/event/listener_manage.py`、`knowledge/vector/`：拆分、问题生成、Embedding、状态回写；
4. `apps/models_provider/impl/`：供应商注册、credential 校验、LangChain 模型实例化；
5. `apps/tools/`、`apps/trigger/`、`apps/chat/mcp/`：代码执行、MCP、Webhook 与权限边界；
6. 各 app migrations 与 `installer/`：数据升级、容器进程编排和版本兼容。

## 17. 旧细探吸收裁决

旧细探全文已读取，并逐条与当前工作树核对。裁决如下：

| 旧细探内容 | 裁决 | 当前源码证据与处理 |
|---|---|---|
| MaxKB 是 Django 多 app 知识库/Agent 平台，包含 `application`、`chat`、`knowledge`、`models_provider`、`tools`、`trigger`、`oss` 等边界 | 吸收 | 已进入本文第 2、4、6 节；证据为当前 `apps/` 目录、URL 和模型/任务实现 |
| `application/flow` 是工作流核心，存在 `i_step_node.py` 与多语言 `default_workflow*.json` | 吸收并校正 | 已进入第 7 节；当前实际文件为 `default_workflow.json`、`default_workflow_en.json`、`default_workflow_zh.json`、`default_workflow_zh_Hant.json`，并无旧细探写法中的 `default_workflow_zh_CN.json` |
| `chat_pipeline` 是独立的检索→组装→生成线性流水线 | 吸收 | 已进入第 7.2 节，源码为 `apps/application/chat_pipeline/pipeline_manage.py` |
| `models_provider` 采用基类+`impl/` 可插拔供应商，并覆盖 OpenAI/Anthropic/DeepSeek/Gemini/Kimi/local 等 | 吸收并更新 | 已进入第 9 节；当前源码能核实 22 个 provider 模块和 `ModelInfoManage` 注册表，不再沿用“15+”旧数量 |
| `base_stt`、`base_tti`、`base_tts` 提供语音/图像能力；存在 `base_ttv.py` | 吸收并校正术语 | 已进入第 9.1 节；`TTV` 当前源码明确是 Text to Video，不是旧细探所写的“文本-工具-视觉” |
| `application/long_term_memory` 提供应用级跨会话记忆 | 吸收并补全 | 已进入第 7.4 节：当前目录、`ApplicationLongTermMemory`、按用户聚合、模型提炼、轮数/定时触发和关闭时清理均有源码证据 |
| `application/flow/backend/`、`application/flow/compare/` 是工作流子目录 | 不吸收 | 当前工作树目录扫描均无这两个目录，不能把旧细探或其他版本线索写成当前事实 |
| “许可证需确认，GPL/商业双轨可能” | 不吸收旧表述 | 当前 `LICENSE`、`README.md` 和 `README_CN.md` 已明确 GPLv3，本文第 1 节以当前文件证据为准 |
| “Django 生态重，仅作架构借鉴”及若干平台借鉴建议 | 不吸收为 MaxKB 架构事实 | 这是面向其他平台的评价/建议，不属于本项目当前实现；保留在旧细探中作为历史研究语境，不复制到唯一架构事实源 |

旧细探文件本身按任务要求保留，未删除、未改写；后续如需维护 MaxKB 架构，只更新本文件。

## 18. 当前核对变更清单

- 更新：根目录唯一权威 `ARCHITECTURE.md`，吸收并裁决 `细探-MaxKB.md` 的有效内容。
- 保留：`细探-MaxKB.md`，未删除、未修改。
- 未修改源码、依赖、测试、配置或 Git 提交。
- 未安装、启动、构建、迁移或运行测试。

## 19. 后续底座映射：节点运行契约与唯一链路

本节是后续底座输入，不把 MaxKB 的目录直接复制成平台目录；只把当前源码中已经存在的契约、编排点、资源边界和失败语义映射到“公共契约 → 支持库 → 模块库 → 运行核心”。结论基于本地 `v2` 工作树，未把远端快照实现混入当前事实。

### 19.1 节点真实调用链

```text
/chat/api 或 /admin/api 或 Celery 知识任务
  → Application/Knowledge/Tool 领域入口
  → WorkflowManage / PipelineManage
  → step_node.get_node(节点类型, workflow_mode)
  → INode 子类（节点参数校验 + execute）
  → models_provider.tools / knowledge.vector / tools / MCP 外部边界
  → NodeResult(node_variable, workflow_variable)
  → write_context（节点/全局上下文）+ NodeChunk（流式块）
  → Answer / runtime_details
  → SSE 或阻塞响应 + ChatRecord.details
  → WorkFlowPostHandler
  → extract_long_term_memory（Celery countdown=1）
  → ApplicationLongTermMemory（应用 + chat_user_id 唯一记录）
```

这条链中 `WorkflowManage` 是当前工作流运行编排器，`get_node` 是节点类型工厂，`INode` 是节点运行基类；模型供应商不是节点的替代入口，而是节点内部经 `models_provider.tools` 到供应商注册表的下游依赖。知识库 embedding/问题生成走另一条 Celery 任务链，但同样应通过模型供应商公开入口获取模型，不能由每个节点维护一份 provider 映射。

### 19.2 节点输入、输出和状态契约

| 契约面 | 当前源码事实 | 底座映射与必须固定的边界 |
|---|---|---|
| 节点身份 | `INode.__init__` 从 `Node` 读取 `id/type/properties.node_data`；由前置节点 id 列表、节点 id 和可选 `salt` 计算 `runtime_node_id` | 运行核心应把 `node_id`（设计节点）与 `runtime_node_id`（一次运行/循环实例）分开，二者均进入追踪、幂等和恢复键；不能用显示名称代替身份 |
| 工作流输入 | `FlowParamsSerializer` 要求 `history_chat_record/question/chat_id/chat_record_id/stream/workspace_id/application_id/re_chat/debug`，用户类型/id 为可选；知识/工具流另有各自 serializer | 公共契约应定义入口版本、必填字段、资源列表和取消信号；项目适配层只做字段映射，不能让每个节点猜测缺省值 |
| 节点输入 | `node_params` 来自 `properties.node_data`，节点自行返回 `get_node_params_serializer_class()`；`valid_args()` 先校验流程参数、节点参数，再拒绝 `properties.status != 200` | 模块层保留节点专属 schema；运行核心在调用前统一执行校验并记录失败，不得把“构造成功”当“可执行” |
| 上下文输入 | `global`、`chat`、节点上下文由 `get_reference_field()`/`get_field()` 逐层取值；`reset_prompt()` 把节点、全局和 chat 引用替换进提示词 | 引用解析应是唯一能力入口，失败要返回“引用缺失/类型不符”，不能静默当空字符串掩盖错误 |
| 执行输出 | 节点 `execute()` 返回 `NodeResult`；其 `node_variable` 写入节点上下文，`workflow_variable` 写入全局上下文；`branch_id` 表示条件分支，`is_interrupt_exec()` 支持表单未提交中断 | 公共契约固定 `成功/失败/中断/分支` 四类结果和可重试语义；`NodeResult` 不能只靠字典键约定，分支值、错误和取消要可判定 |
| 流式输出 | `NodeChunk` 累积 chunk，`end()` 把 `status` 置 200；`Answer` 携带 `content/view_type/runtime_node_id/child_node/reasoning_content`；`WorkflowManage` 转为 SSE | `NodeChunk.status=200` 实际表示“块流结束”，不是业务成功；底座必须把 `stream_closed` 与 `business_status` 分开，防止结束帧被当作成功帧 |
| 运行详情 | `get_details(index)` 产生节点详情；编排器补 `node_id/up_node_id_list/runtime_node_id`，最终写 `ChatRecord.details` | 详情是审计/恢复输入，不是仅供前端展示；应包含输入摘要、输出摘要、状态、错误码、开始/结束、资源和重试信息，敏感字段脱敏 |
| 终态 | `get_workflow_state()` 对工具/知识工作流检查中断、`status=500` 且未启用异常分支、以及知识写入节点；普通应用主要以 `WorkflowManage.status` 和 `ChatRecord` 为结果载体 | 统一验收必须检查“所有必需节点完成 + 无未处理异常 + post-handler 持久化成功 + 外部资源释放”；HTTP 200、ChatRecord 已写或流结束均不能单独证明业务成功 |

### 19.3 节点资源、调度和失败恢复

| 节点阶段 | 资源与调度 | 当前失败/恢复语义 | 防假绿要求 |
|---|---|---|---|
| 装配 | `Workflow.new_instance()` 从 JSON 建 `Node/Edge` 和前驱/后继映射；`is_valid_*` 检查 start/base、模型、函数库和边 | 配置校验失败抛 `AppApiException/ValidationError`，不是运行时降级 | 装配结果必须带校验报告和工作流版本；不能只因 JSON 能解析就入运行 |
| 节点启动 | `run_node_future()` 调 `valid_args()`、发送进度、执行 `node.run()`；共享进程级 `ThreadPoolExecutor(max_workers=200)` | 校验/执行异常包装进 `NodeResultFuture(status=500)`，随后由结果处理器设置节点 500 或进入异常分支 | 每个 future 必须有显式状态和超时/取消归属；当前没有统一节点超时契约，不能声称具备超时恢复 |
| DAG 调度 | `run_chain_manage()` 按边推进；多后继提交 executor；`dependent_node_been_executed()` 实现 AND 汇聚，条件节点按 `branch_id` 选择边，禁用节点被过滤 | 表单未提交可中断；任务中断时节点状态设 201；依赖未完成则不调度 | 分支/汇聚需落账已选择边、未选择边和依赖快照；仅看到下游未运行不能判为成功 |
| 结果处理 | `hand_node_result/hand_event_node_result` 将结果写上下文、构造 SSE、结束 NodeChunk；异常可按 `enableException` 写 `exception` 分支 | 非流式路径捕获异常并设置编排器 500；流式路径可发 ERROR 或异常分支；`run_chain()` 仍会记录日志并返回 None | `enableException` 是业务分支而非成功；必须区分“异常已处理并按设计继续”和“异常被吞掉后继续” |
| 数据库连接 | 节点运行前 `close_old_connections()`；流式结果处理 finally 调 `connection.close()` | 依赖 Django 连接池/线程隔离；源码未提供节点级事务回滚协议 | 资源表要记录连接获得/归还；异常、客户端断开、进程崩溃后的连接/线程残留必须实测清零 |
| 编排收尾 | 阻塞和流式都在 post-handler 后 `_cleanup()`；清空 future、字段、上下文、输入列表并断开对象引用 | `await_result()` 等待运行完成后写 ChatRecord；但 `_cleanup()` 清引用不等于取消或回收已运行任务 | 恢复不能依赖内存中的 `node_context`；必须从 ChatRecord/任务账本重建，并验证不存在悬挂 future |

当前实现最重要的恢复缺口是：`WorkflowManage` 使用线程池和内存上下文，未见持久化的节点执行租约、统一取消令牌、节点级重试账本或进程崩溃恢复协议。因此后续裁决为“吸收节点接口与 DAG 语义，待核运行核心的超时/取消/崩溃恢复”，不能把现有线程池当作可靠任务系统。

## 20. 长期记忆、模型提炼与定时触发

### 20.1 记忆写入链

```text
WorkflowManage 完成
  → WorkFlowPostHandler.handler
  → ChatRecord.problem_text/answer_text/details/token/run_time 持久化
  → extract_long_term_memory.apply_async(countdown=1)
  → _get_long_term_config（普通 Application 或 WORK_FLOW 的 base-node）
  → ROUND：ChatRecord 计数达到 rounds 才 _run_extract
     SCHEDULED：schedule_extract_long_term_memory 清旧 job 后部署 APScheduler
  → _run_extract 查询历史对话
  → get_model_instance_by_model_workspace_id
  → chat_model.stream(long_term_prompt)
  → 清除 <think> 后覆盖/创建 ApplicationLongTermMemory.memory
```

`ApplicationLongTermMemory` 是 `application + chat_user_id` 唯一的单行文本记忆（`db_table=application_long_term_memory`），不是向量记忆或事件图谱。`long_term_prompt` 规定偏好、背景、约定、目标四类内容、证据门槛、融合和输出格式；融合决策由模型完成，数据库层没有版本号、来源 ChatRecord 列表或人工确认状态。

### 20.2 触发与调度事实

- 对话完成后始终异步投递 `extract_long_term_memory`；任务读取配置，关闭长期记忆时删除该用户记忆。`ROUND` 模式按该用户 ChatRecord 总数 `% rounds == 0` 触发；非 `ROUND` 模式由定时任务处理。
- `schedule_extract_long_term_memory` 先按 `long_term:application:<id>:` 前缀删除旧 job，再按 `daily/weekly/monthly/interval/cron` 部署 `common.job.scheduler` 的 APScheduler 任务。任务 `replace_existing=True`、`misfire_grace_time=60`、`max_instances=1`。
- `_execute_scheduled_extract` 查询应用下 distinct `chat_user_id`，逐用户按时间窗口或 rounds 读取对话；应用不存在会删除该应用 job，单用户异常只记录 warning 并继续其他用户。
- `common.job.scheduler` 使用 `BackgroundScheduler + DjangoJobStore`，模块导入时启动；启动异常仅记录日志。长期记忆调度与 `trigger/handler/impl/trigger/scheduled_trigger.py` 的 Webhook/应用/工具定时触发是两套 job 命名和部署链，均复用同一 scheduler。
- 触发器 `ScheduledTrigger.execute()` 以 RedisLock（`trigger_id:source_id`）串行执行应用/工具任务；长期记忆提炼没有同等的分布式锁或“已消费窗口”标记。

### 20.3 记忆资源与失败矩阵

| 场景 | 输入/资源 | 当前行为 | 不能当作成功的证据 |
|---|---|---|---|
| 配置关闭 | Application 或 workflow base-node 的长期记忆开关 | 删除该应用/用户旧记忆并返回 | 任务返回 None；需核对删除计数与最终数据库状态 |
| 对话轮数触发 | `rounds`、ChatRecord 查询、Celery 任务 | 非整轮直接返回；整轮取最近 rounds 条 | Celery accepted 或日志出现；需读回记忆内容和更新时间 |
| 定时触发 | APScheduler job + DjangoJobStore + Redis/DB | 以时间窗口/cron 间隔选取对话，逐用户调用提炼 | job 存在不等于提炼成功；必须记录每个用户结果 |
| 模型不存在/无历史 | model_id、workspace 授权查询、ChatRecord | `_run_extract` 静默返回 | 无异常不代表有新记忆；应产生明确 skipped 原因 |
| 模型流/数据库异常 | 外部模型流、PostgreSQL 写入 | 调用方可能抛出；定时回调捕获后 warning 并继续 | warning 不是失败入账；需要重试/死信/任务记录 |
| 并发或重复触发 | Celery countdown、APScheduler、同一用户记忆行 | `max_instances=1` 只约束同一个 APScheduler job；没有记忆行 CAS/版本校验 | 行最终存在不代表没有后写覆盖；需唯一 job、幂等键、版本冲突检测 |

### 20.4 底座裁决

- **吸收**：`ApplicationLongTermMemory` 的应用/用户聚合键、四类记忆提炼提示词、ROUND 与 SCHEDULED 两种策略、应用关闭时清理语义。
- **升级支持库**：记忆仓储公开能力（读取快照、追加提炼结果、版本/CAS、来源对话窗口、软删除/恢复）、模型调用适配器（统一流式/非流式结果和错误码）、调度器适配器（Celery/APScheduler 只是 provider）。
- **升级模块库**：长期记忆策略模块负责配置解析、窗口选择、提示词构造、提炼结果校验和业务幂等；不让 ORM、Celery 或 APScheduler API 穿透到节点/HTTP 消费者。
- **新增运行核心能力**：持久任务账本、租约、取消/超时、重启恢复、提炼窗口 watermark、按 `(application_id, chat_user_id, window_fingerprint)` 去重；模型成功返回但记忆落盘失败时必须可重放。
- **待核**：当前 `long_term_prompt` 的结构化文本并无 schema 校验，`_run_extract` 未保留模型输出来源/提示词版本/输入窗口摘要，也未见提炼任务专用状态表；是否由平台统一审计需继续跨项目裁决。

## 21. 模型供应商基类与注册表映射

### 21.1 当前四层事实

1. **供应商抽象**：`IModelProvider` 定义模型类型/模型列表/凭据/凭据校验/模型实例化/下载入口；缺省 `get_dialogue_number()` 返回 3，下载默认抛“不支持”。
2. **模型实例抽象**：`MaxKBBaseModel.new_instance()` 是供应商模型类的构造入口；`filter_optional_params()` 排除 `model_id/use_local/streaming/show_ref_label/stream` 后透传其余参数。
3. **凭据抽象**：`BaseModelCredential` 负责校验、加密字典、参数表单；敏感值展示走掩码加密。
4. **模型注册表**：`ModelInfoManage` 以 `model_type → model_name → ModelInfo` 保存模型信息，并另外维护 default model；`ModelProvideConstants` 用 Enum 静态实例化约 22 个供应商。`models_provider.tools.get_provider()` 直接按 Enum key 查供应商，`get_model_()` 解密 credential 后调用 provider.get_model()；`ModelManage` 再缓存模型实例。

### 21.2 输入、输出、资源与失败语义

| 组件 | 输入 | 输出/资源 | 失败与恢复事实 |
|---|---|---|---|
| `get_provider` | provider 字符串 | Enum 中的 `IModelProvider` 实例 | 未知 key 直接查找失败；没有统一 `PROVIDER_NOT_FOUND` 结果或版本协商 |
| `get_model` | model type/name、credential、model kwargs | `MaxKBBaseModel`/LangChain 模型实例，可能被 `ModelManage` 缓存 | credential 解密、第三方 SDK 初始化异常沿调用链传播；基类未统一 timeout/retry/cancel/close |
| `ModelInfoManage` | provider 启动时追加 `ModelInfo` | 类型/名称列表、默认模型、credential/model class 映射 | 同类型同名追加会覆盖字典但保留 `model_list` 旧项，存在列表与索引不一致风险；无重复注册拒绝/版本冲突记录 |
| `BaseModelCredential` | model type/name、凭据、参数、provider | 校验结果、加密字典、参数表单 | 校验可返回 bool 或按参数抛异常；没有统一错误码、重试性和密钥生命周期协议 |
| 模型实例缓存 | model id、构造 lambda、默认参数 | 复用模型实例/连接 | 缓存命中掩盖 credential/模型配置变化；未在本层证明外部连接、线程安全或进程崩溃清理 |
| provider 下游 | API key/endpoint、提示词/媒体、stream 参数 | 文本/embedding/rerank/STT/TTS/图像/视频等 LangChain 结果 | 各 provider 自己决定 SDK 异常与返回形状，节点若直连会复制错误翻译和 fallback |

### 21.3 单一 provider 链路与落点

```text
节点/知识任务/长期记忆模块
  → 唯一模型调用门面（当前应收敛 tools.get_model*）
  → ProviderRegistry（provider id + capability/model id + 版本）
  → IModelProvider
  → ModelInfoManage（类型/名称/credential/model class）
  → BaseModelCredential + MaxKBBaseModel
  → LangChain/供应商 SDK/本地模型进程
  → 统一模型结果、错误码、重试/超时、用量与资源证据
```

映射裁决：`IModelProvider/MaxKBBaseModel/BaseModelCredential/ModelInfoManage` 可**吸收为支持库的 provider 契约与注册表基础**；`impl/<vendor>_model_provider` 是 provider 适配层；节点和业务模块只能通过唯一模型调用门面取模型。`ModelProvideConstants` 与 `ModelInfoManage` 当前分别承担供应商注册和模型能力注册，后续不把它们复制成第三套注册表，而是规划为“外层 provider registry + 内层 model capability registry”，由一个公开门面负责归一化查找、健康检查、版本选择和调用审计。

必须补齐的底座契约：provider/model 唯一 id、能力类型、凭据所有权、实例/连接释放责任、超时/取消/重试、限流和用量、错误码/可重试性、健康检查、版本兼容、默认模型选择、注册冲突和禁用/恢复。当前源码尚未证明这些字段在同一注册表中具备，结论为“基类与分层注册模式吸收；统一治理能力待升级”。

## 22. 后续能力命中、缺口与装配计划

| 目标能力 | 当前源码命中 | 底座归属 | 裁决 | 装配/验收契约 |
|---|---|---|---|---|
| 节点运行契约 | `application/flow/i_step_node.py` 的 `INode/NodeResult/FlowParamsSerializer` | 公共契约 + 模块库 | 吸收接口，升级状态/错误/取消字段 | 输入 schema、输出 schema、分支/中断、资源清单、节点级状态均可读回 |
| DAG/循环调度 | `Workflow/common.py`、`workflow_manage.py`、`get_node` | 模块库 + 运行核心 | 吸收拓扑/分支语义，线程池不直接复用为底座任务系统 | 依赖快照、并发上限、超时、取消、重启恢复和无悬挂任务 |
| 长期记忆聚合 | `ApplicationLongTermMemory` | 支持库仓储 + 记忆模块 | 吸收聚合键和清理语义；升级版本/CAS/来源 | 同用户同窗口幂等，冲突不可静默覆盖，失败可重放 |
| 模型提炼 | `long_term_memory._run_extract`、`long_term_prompt` | 记忆模块 + 模型调用支持库 | 吸收策略，升级结构化输出校验和证据 | 模型输出 schema、窗口摘要、提示词版本、持久化成功才算成功 |
| 定时触发 | Celery `@task`、APScheduler `scheduler.add_job`、trigger scheduled handler | 调度支持库 + 运行核心 | 两套 provider 适配到一个调度门面，业务模块不直连 scheduler | job 唯一键、租约、misfire、重试/死信、逐用户结果和恢复对账 |
| 供应商基类 | `IModelProvider/MaxKBBaseModel/BaseModelCredential` | 模型支持库 | 吸收抽象；补统一生命周期、错误和资源契约 | provider 能力注册、健康/禁用、超时取消、凭据隔离、版本兼容 |
| 供应商注册表 | `ModelProvideConstants + ModelInfoManage + tools.get_provider` | 支持库注册表 | 现有两级信息可保留，但公开查找必须唯一 | 注册冲突拒绝或留证，未知 provider 有稳定错误码，模型选择可审计 |
| 任务状态与反假绿 | `ChatRecord.details`、部分 `status=500/201`、trigger task record | 运行核心 + 证据支持库 | 缺口，不能以日志/HTTP 200/流结束代替 | 真实执行、结果读回、失败/取消/崩溃四终态，验证命令和退出码入账 |

### 22.1 唯一链路铁律

- 一个节点能力只有一个 `node_type → factory → INode` 入口；历史节点别名在工厂入口一次归一化，不能由前端、后端和模块各维护映射。
- 一个模型调用只有一个公开门面；节点、知识任务、长期记忆不得直接读取 `ModelProvideConstants`、第三方 SDK 或 provider 内部 credential。
- 一个提炼任务只有一个权威 job key：建议为 `memory:application:<application_id>:user:<chat_user_id>:window:<fingerprint>`；ROUND 与 SCHEDULED 只是触发策略，不是两套提炼内核。
- 一个长期记忆只有一个写 owner；模块提交命令，仓储负责版本/CAS 和来源；禁止节点直接写 `ApplicationLongTermMemory`。
- Celery、APScheduler、RedisLock 是受管调度/锁 provider，不构成第二个业务执行核心；调度器只投递命令，运行核心记录执行和恢复。
- `ModelProvideConstants`、`ModelInfoManage` 的历史兼容键只能在 provider registry 门面归一化；消费者不得旁路查 Enum 或复制模型表。

### 22.2 失败恢复和防假绿验收

1. **节点**：构造非法参数、缺模型、依赖未完成、分支无出口、外部模型超时、客户端断开、线程异常、进程强杀；验收要求节点/工作流状态、错误码、取消和资源清理均可读回。
2. **记忆**：关闭开关、空窗口、模型不存在、模型流失败、重复触发、并发覆盖、写库失败、重启中断；验收要求任务账本明确 `success/skipped/failed/cancelled/retryable`，读回 memory、版本和窗口 watermark。
3. **调度**：非法 cron/时间、job 重复、misfire、scheduler 重启、Redis/数据库不可用、任务执行超时；验收要求唯一 job、重建结果、失败重试/死信和无旧 job 残留。
4. **provider**：未知 provider/model、凭据无效、SDK 缺失、endpoint 断线、限流、流式半途断开、缓存旧实例；验收要求稳定错误码、可重试标记、资源释放和缓存失效证据。
5. **禁止假绿**：`warning`、打印“完成”、Celery 接收、APS job 存在、SSE 结束帧、ChatRecord 已落盘或 HTTP 200 都只能算中间证据；只有真实调用返回、权威状态读回、失败路径验证和资源现场清零齐全，才能记为通过。

### 22.3 证据等级与剩余风险

| 证据等级 | 当前核对事实 | 结论 |
|---|---|---|
| 源码存在 | 上述路径、类、函数和分支已直接读取 | 可用于架构映射 |
| 测试源码存在 | 当前 `apps/*/tests.py` 仍为空模板，未发现独立行为测试 | 不得写“测试通过” |
| 当前核对静态验证 | 仅文档变更和差异检查；未启动依赖服务 | 只能证明文档落盘/格式，不证明运行链 |
| 外部依赖实测 | PostgreSQL、Redis、Celery、APScheduler、供应商 SDK 未启动 | 全部标记未验证 |
| 运行恢复 | 未见持久节点租约、提炼 watermark、统一 provider 生命周期的当前实现证据 | 运行核心接入为待核/缺口 |

剩余风险：当前 MaxKB 的“节点完成、记忆提炼完成、模型调用成功、定时任务成功”分别由不同的内存状态、数据库记录、Celery/APScheduler 状态和日志表达，尚未形成统一可审计状态机。任何平台化接入必须先冻结公共契约、唯一写 owner、任务账本和验收门禁，再做模块/支持库装配；当前核对不修改 MaxKB 源码、不声称已有能力已满足底座生产门槛。

## 23. 后续修改清单

- 仅追加本文件第 19—22 节：节点运行契约、资源/调度/失败恢复、长期记忆与定时触发、模型供应商基类/注册表、底座命中/缺口/唯一链路和反假绿验收。
- 未修改 MaxKB 源码、配置、依赖、测试、README 或 Git。
- `细探-MaxKB.md` 继续保留为历史细探，未删除、未改写；后续只维护本 `ARCHITECTURE.md`。
- 由于目标项目未建立 `.codegraph/`，当前核对代码证据来自目标仓库直接读取；错误绑定的 `project_context` 结果未作为 MaxKB 证据使用。

## 24. 后续收口：研究范围与证据规则

本节是后续内部深挖的收口，不创建第二份细探文档。重点逐条核对 `细探-MaxKB.md` 中涉及的文档入库、RAG、工作流、模型、任务、数据库、缓存和接口边界；旧细探中的 `backend/`、`compare/` 等不存在目录仍不作为当前事实。以下路径均来自当前本地 `v2` 工作树，源码事实优先于 `CLAUDE.md` 的概览。

当前核对明确区分四种证据：

| 等级 | 含义 | 当前核对结果 |
|---|---|---|
| 源码存在 | 类、函数、路由、SQL 或模型文件可直接读取 | 已覆盖下述链路 |
| 声明存在 | README/CLAUDE/注释声称具备能力 | 只能作索引，不能证明执行 |
| 静态链路 | 调用方、事务、状态更新和异常分支可从源码串起来 | 已完成主要链路 |
| 真实运行 | PostgreSQL/Redis/Celery/模型供应商/HTTP 被真实启动并读回 | 本任务未执行，全部保留为未验证 |

## 25. 文档入库：四条入口链路和真实写入顺序

### 25.1 对外入口和契约边界

`apps/knowledge/urls.py` 把文档能力拆成管理面 REST 路由；`apps/knowledge/views/document.py` 的每个 View 先走 `TokenAuth`、`has_permissions`，再把请求转给 `DocumentSerializers`。因此前端不是直接写模型，正式写入 owner 是 serializer/service 逻辑。

| 入口 | 请求边界 | 实际调用 | 是否立即入库 | 后续任务 |
|---|---|---|---|---|
| `POST .../document` | JSON：`name`、可选 `paragraphs`、`source_file_id` | `DocumentView.post` → `Create.save` | 是，`transaction.atomic` | 装饰器回调调用 `Operate.refresh`，投递 embedding |
| `POST .../document/split` | multipart `file[]`、`patterns`、`limit`、`with_filter` | `Split.parse` → `file_to_paragraph` | 保存原文件 `File`，但不建 `Document/Paragraph` | 返回段落草稿，后续仍需 Create/BatchCreate |
| `PUT .../document/batch_create` | 文档数组 | `Batch.batch_save` | 是，批量事务 | 回调逐文档 refresh，投递 embedding |
| `POST .../document/web` | URL 列表、selector | `Create.save_web` → `sync_web_document.delay` | 任务中每个 URL 成功后 Create | `Fork` 抓取、`web.md` 拆分、入库、embedding |
| `POST .../document/qa` | multipart QA 文件 | `parse_qa_file` → QA handler → `Batch.batch_save` | 是 | 原文件和解析出的文档一并进入批量入库 |
| `POST .../document/table` | multipart 表格文件 | `parse_table_file` → table handler → `Batch.batch_save` | 是 | 同上，支持图片落 `File` |
| `PUT .../document/<id>/sync` | 仅网站文档 | `Sync.sync` | 在事务内删旧段落/问题/向量后重建 | 重新投递 embedding |
| `PUT .../document/<id>/refresh` | `state_list` | 状态置 pending → `embedding_by_document.delay` | 不改文本 | Celery 重做向量 |
| `PUT .../document/<id>/tokenize` | `state_list` | 状态置 pending → `tokenize_by_document.delay` | 不改向量数值 | 重建 `search_vector` |
| `PUT .../document/<id>/cancel_task` | `type`=`TaskType` | DB 状态置 `REVOKE` | 不删除数据 | worker 在分页/批次边界检查后转 `REVOKED` |

路由的完整当前清单见 `apps/knowledge/urls.py:38-77`；`DocumentInstanceSerializer`、`DocumentSplitRequest`、`DocumentInstanceQASerializer` 和 `DocumentInstanceTableSerializer` 位于 `apps/knowledge/serializers/document.py:136-223`。接口返回由 `common.result.result.success` 包装；底层 serializer 抛出的 `AppApiException` 交给全局异常处理器，未在文档领域单独形成稳定错误码表。

### 25.2 手工文件/文本入库真实调用链

```text
multipart 文件
  → DocumentView.Split / 前端先取得段落草稿
  → Split.file_to_paragraph
  → File.save(raw bytes): sha256 → zip 压缩 → PostgreSQL large object
  → split handle（HTML/Doc/PDF/XLSX/XLS/CSV/ZIP/Text）
  → {name, paragraphs, source_file_id}
  → DocumentView.post 或 BatchCreate
  → Create.get_document_paragraph_model
  → ParagraphSerializers.Create.get_paragraph_problem_model
  → Document.save + Paragraph.bulk_create
  → ProblemParagraphManage：按 knowledge_id + content 去重 Problem
  → ProblemParagraphMapping.bulk_create
  → Operate.refresh
  → Document/Paragraph embedding 状态 PENDING
  → Celery embedding_by_document
```

`Create.save`（`document.py:1011-1053`）是单文档权威写入：先由 `get_document_paragraph_model` 计算字符数、元数据和段落模型，再保存文档、按 `position` 批量保存段落、批量保存问题及映射。`@post(post_embedding)`（`common/utils/common.py:334-342`）要求被装饰函数返回三元组；回调立即把向量任务投递。也就是说，HTTP 成功只代表关系数据事务已提交并且任务已提交给 Celery，不代表向量已经产生。

分段的实际策略不是一个“RAG splitter”类，而是 `document.py:95-110` 中按文件类型顺序选择的 `split_handle`；文本兜底是 `TextSplitHandle`。`file_to_paragraph` 在尝试解析器之前就把原始字节保存进 `File`，解析器得到的每个结果附加 `source_file_id`。因此：

- `/document/split` 是“保存源文件 + 返回草稿”，不是纯只读预览；前端取消后可能留下没有 `Document` 引用的知识库源文件，当前源码未见该场景的清理账本。
- `Create` 的 `meta` 强制补 `allow_download=True`；源文件关系在 `Document.meta.source_file_id` 中保存。
- `Paragraph.chunks` 若调用方未传，`knowledge_write_node` 使用 `text_to_chunk`；普通文档的各 split handle 也可以返回 chunks。Embedding 层会再次把段落按 chunks 展开，不能把“段落数”当作“向量行数”。

### 25.3 QA、表格、网页和工作流写入差异

1. **QA/表格文件**：`Create.parse_qa_file`/`parse_table_file` 先将上传文件保存为 `FileSourceType.KNOWLEDGE`，再用 handler 生成一个或多个文档草稿；图片由 `save_image` 将临时内容转为知识库 `File`。随后 `Batch.batch_save` 为每个文档 `link_file`，把源文件按相同内容复制成 `FileSourceType.DOCUMENT`，再批量写 `Document/Paragraph/Problem/Mapping`。`link_file` 通过 `File.get_bytes()` 读回 large object，所以源文件和文档文件共享 sha256/loid 但拥有不同关系行。
2. **网页**：`knowledge/task/sync.py` 的 `sync_web_document` 和 `sync_web_knowledge` 都是 Celery `QueueOnce` 任务；`task/handler.py:17-42` 用 `Fork` 响应内容经 `web.md` 拆分后调用 `Create.save`。全量同步用 `ForkManage` 深度 2 抓取，已有 URL 走 `get_sync_handler`；单文档 `Sync.sync`（`document.py:597-673`）先删段落、问题映射、向量，再 bulk insert 新段落/问题，最后按知识库 embedding model 重投任务。
3. **知识库工作流写入**：知识库工作流的 `knowledge-write-node` 不复用 HTTP Create，而在 `application/flow/step_node/knowledge_write_node/impl/base_knowledge_write_node.py:223-331` 直接校验 `KnowledgeWriteParamSerializer`，批量构造文档/段落/标签/问题映射，然后 `post_embedding` 对每个文档调用 `Operate.refresh`。它的 `Document.type` 默认是 `WORKFLOW`，普通 Create 默认是 `BASE`，二者是同一张 `document` 表而不是两套文档库。
4. **删除/替换**：`Operate.delete` 和 `Batch.batch_delete` 显式删除源文件、标签、问题映射、段落、向量和文档；`File` 的 `pre_delete` 只有在同一 `loid` 没有其他 `File` 行时才 `lo_unlink`。替换源文件会按原 sha256 找到知识库/文档关联行并重写内容，但源码未在 replace 内自动重新拆分段落或自动刷新向量；调用方必须另行触发 refresh。

### 25.4 文件持久化和资源生命周期

`knowledge.models.File.save`（`knowledge.py:385-404`）不是 Django 默认文件字段：它要求 `bytea`，计算 sha256；若已有同 hash 文件，复用既有 `loid` 和压缩后大小；否则在 PostgreSQL 中 `lo_creat(-1)`，用 64 KiB `lo_put` 分块写入 zip 压缩内容。`get_bytes_stream` 用 `lo_get` 流式读取，`get_bytes` 解压唯一 zip entry；删除信号负责最后引用的 `lo_unlink`。

| 资源 | 创建 | 持有者/读者 | 正常释放 | 失败/取消现状 |
|---|---|---|---|---|
| 上传临时内存 | DRF `UploadedFile`、split handle | serializer/parser | `seek(0)` 后由调用栈释放 | 不支持格式在 `File.save` 后抛错，未见源文件补偿删除 |
| PostgreSQL large object | `File.save` | `File` 行及其 `source_id` | 最后一行删除时 `lo_unlink` | 事务回滚与 large object 创建/写入的一致性依赖 Django 连接事务，未实测崩溃窗口 |
| 解析临时目录 | `TemporaryDirectory`（导出） | export serializer | 上下文退出 | 导出异常由 Python finally 清理；解析器内部临时资源需逐 provider 核对 |
| embedding 模型实例 | `ModelManage` | Celery/HTTP worker 进程 | 8 小时 cache TTL 或显式 delete key | 没有统一 close；SDK/HTTP 连接由 provider 决定 |
| embedding RedisLock | `embedding:<document_id>` | `ListenerManagement.embedding_by_document` | finally `un_lock` | 进程崩溃依靠 3600 秒 key TTL，非即时恢复 |

## 26. RAG：索引写入、检索、重排和直接返回边界

### 26.1 存储关系和向量行语义

`Knowledge` 通过 `embedding_model` 指向一个 `models_provider.Model`；`Document` 属于知识库；`Paragraph` 同时保留 `document_id`、`knowledge_id`、`content`、`title`、`chunks`、`position`、`is_active` 和 compact `status`；`Problem` 与 `ProblemParagraphMapping` 是可选的生成问题倒排入口；`Embedding` 是真正检索行，含 `source_id/source_type`、三层外键、vector `embedding`、PostgreSQL `search_vector` 和 `meta`（`knowledge/models/knowledge.py:249-359`）。

向量写入链为：

```text
embedding_by_document
  → RedisLock("embedding:<document_id>")
  → page_desc(每批 5 个段落)
  → list_embedding_text.sql（段落 + 问题文本）
  → BaseVectorStore.chunk_data_list（段落 chunks 展开）
  → normalize_for_embedding（去 emoji、压缩空白、strip）
  → Embeddings.embed_documents
  → PGVector._batch_save
  → Embedding.bulk_create（向量 + simple tsvector）
  → create_knowledge_index（每知识库 HNSW，维度 < 2000）
  → post_update_document_status + status_meta aggs
```

`PGVector._batch_save` 为每个 chunk 建一行 `Embedding`，使用知识库 `Termbase` 作为 `to_ts_vector` 的 user words；在真正 bulk insert 前再次调用中断判断，所以取消可以阻止当前批次落库，但已经写入的前批不会自动回滚。单段落重算先删该段旧向量，再 batch save；批量向量化失败更新段落为 `FAILURE`。文档级 finally 会把文档任务从 `REVOKE` 转 `REVOKED`，否则置 `SUCCESS`，但只在状态聚合逻辑内判断失败子段。

HNSW 索引是知识库局部索引，索引名 `embedding_hnsw_idx_<knowledge_id>`；`create_knowledge_index` 从首行读取维度，维度 >= 2000 不建索引。`PGVector.hit_test/query` 对多个知识库逐库查询，再在 Python 中按 `similarity` 或 `comprehensive_score` 降序截断，避免 `knowledge_id__in` 让局部 HNSW 失效。

### 26.2 三种检索 SQL 的真实分数

| `SearchMode` | SQL | 候选/分数 | 过滤 |
|---|---|---|---|
| `embedding` | `knowledge/sql/embedding_search.sql` | 先取 `LEAST(top_n*10,500)` 个 cosine distance，`similarity=1-distance` | `comprehensive_score > similarity`，再 LIMIT `top_n` |
| `keywords` | `knowledge/sql/keywords_search.sql` | `ts_rank_cd(search_vector, websearch_to_tsquery('simple', query),32)` | `search_vector @@ query` 且分数阈值 |
| `blend` | `knowledge/sql/blend_search.sql` | `1-distance + ts_rank_cd(...)`，不是归一化加权平均 | 综合分数阈值后 LIMIT |

所有模式先按 `knowledge_id`、`is_active`、可选文档集合和排除文档/段落过滤。`SearchMode` 只接受 `embedding|keywords|blend`；`DatasetSettingSerializer` 约束 `top_n`、`similarity(0..2)`、最大引用字符数，但没有在 serializer 层约束 `top_n` 正数或最大值。

### 26.3 应用 RAG 节点和重排节点

```text
search-knowledge-node
  → 解析 question/reference
  → chat user / workspace 授权过滤
  → 校验所有 Knowledge 使用同一 embedding_model
  → get_model_instance_by_model_workspace_id
  → embed_query(question)
  → VectorStore.query（embedding/keywords/blend）
  → list_paragraph（脏向量对应不到段落则删除该向量）
  → reset_paragraph（similarity、直接返回标志、allow_download 脱敏）
  → NodeResult.paragraph_list/data/directly_return
  → 可选 reranker-node
  → compress_documents → top_n/阈值/字符上限
```

`BaseSearchKnowledgeNode.execute`（`.../search_knowledge_node/impl/base_search_knowledge_node.py:76-136`）有三个不能越过的边界：

- `filter_authorized_ids` 和可选 `get_knowledge_list_of_authorized` 在向量检索前执行；知识库 ID 不能只由工作流 JSON 直接信任。
- 多知识库 embedding model 不一致直接抛异常；这是调用模型前的硬前置条件，不是检索时自动切换 provider。
- `re_chat` 从历史 `ChatRecord.details` 找相同问题的同一 runtime node 段落并排除，避免换答案重复返回同一段。

直接返回判断为 `similarity > Document.directly_return_similarity` 且 `hit_handling_method == directly_return`；`data` 和 `directly_return` 又分别按 `max_paragraph_char_number` 截断。`BaseRerankerNode` 把字典/列表递归转换为 LangChain `Document`，调用 provider 的 `compress_documents`，再按 reranker 分数和 `top_n`、总字符数过滤。Reranker 不是向量库的替代写入路径，只是查询后处理；reranker model 通过同一个 `get_model_instance_by_model_workspace_id` 门面取得。

## 27. 工作流：应用流、知识库流与任务流的边界

### 27.1 图和节点契约

`Workflow.new_instance`（`application/flow/common.py:107-194`）仅把 JSON `nodes/edges` 转为内存图，构造 `node_map/up_node_map/next_node_map`；`is_valid` 递归验证 start/base、模型参数、函数库、分支出口和终止节点。它不持久化运行实例，也不提供版本锁；应用发布快照和知识库 `KnowledgeWorkflowVersion` 是调用方的版本选择责任。

`INode` 的真实节点契约（`i_step_node.py:273-380`）是：构造时从 `properties.node_data` 取参数；`valid_args` 先校验 flow serializer、node serializer，再拒绝 `properties.status != 200`；`run` 记录 `start_time/run_time` 并调用 `_run → execute`；输出为 `NodeResult(node_variable, workflow_variable)`。`NodeResult` 只按字典的 `branch_id` 判定分支，表单节点通过 `_is_interrupt` 产生中断；当前不是强类型跨进程协议。

### 27.2 应用工作流执行

```text
Chat API / debug
  → ChatInfo 获取 Application 或已发布 ApplicationVersion
  → Workflow.new_instance(..., APPLICATION)
  → WorkflowManage
  → 进程级 ThreadPoolExecutor(max_workers=200)
  → get_node(node.type, workflow_mode)
  → run_node_future → INode.valid_args → INode.run
  → NodeResult.write_context（node/global context）
  → 分支/AND 汇聚计算后继续提交 future
  → NodeChunk / BaseToResponse SSE
  → WorkFlowPostHandler.handler
  → ChatRecord.update_or_create + ChatInfo.set_cache
```

`WorkflowManage` 的 `future_list`、`context`、`node_context`、`NodeChunk` 全是当前进程对象；分支使用 edge anchor `${source}_${branch_id}_right`，AND 汇聚等待所有前驱 `NodeChunk.is_end()`。流式 finally 关闭 Django `connection`，但执行器 future 不带统一 deadline；`_cleanup` 只是清空引用，不能取消已运行的 provider 调用。

应用流的错误有三种不同语义：节点异常且 `enableException` 为 false → workflow status=500/错误 SSE；`enableException` 为 true → 写 `exception` 上下文并沿 exception edge 继续；`is_the_task_interrupted()` 为 true → 当前节点 status=201 且停止后继。`NodeChunk.status=200` 只代表 chunk 结束，不等于业务成功。

### 27.3 知识库工作流执行和持久任务记录

知识库工作流是另一条显式任务链，不应与 Celery 文档 embedding 混为一谈：

```text
POST .../knowledge/<id>/debug 或 .../upload_document
  → KnowledgeWorkflowActionSerializer.action/upload_document
  → 创建 KnowledgeAction(state=STARTED, meta=user)
  → 选择 draft work_flow 或最新 KnowledgeWorkflowVersion
  → KnowledgeWorkflowManage(..., KNOWLEDGE)
  → executor(max_workers=200).submit(_run)
  → KnowledgeAction.state=STARTED
  → 节点阻塞执行、每节点更新 details
  → knowledge-write-node 写 Document/Paragraph/Problem/Tag
  → KnowledgeWorkflowPostHandler.get_workflow_state
  → KnowledgeAction SUCCESS/FAILURE/REVOKED + run_time
```

`KnowledgeAction` 是数据库表 `knowledge_action`，字段为 `state/details/run_time/meta`；HTTP action 返回 `STARTED` 的任务摘要，不等待执行完成。`upload_document` 要求 `KnowledgeWorkflow.is_publish`，并固定读取最新版本；debug 直接读取当前 `KnowledgeWorkflow.work_flow`。取消写入 Redis `KNOWLEDGE_WORKFLOW_INTERRUPTED:<action_id>` 并把 DB 状态改为 `REVOKE`，运行中的节点通过 callback 检查缓存，最终 `get_workflow_state` 将其映射成 `REVOKED`。

当前持久边界的不足必须保留：没有 workflow execution lease、future ID、节点级 retry/deadline、进程崩溃恢复或“提交了 Document 但未投递 refresh”的事务 outbox。`KnowledgeAction.details` 是运行快照，不是可重放日志；`KnowledgeWorkflowManage.run` 返回后，调用者只能通过 action API 轮询数据库。

## 28. 模型、缓存和 provider 的后续收口

### 28.1 模型数据库与供应商入口

`models_provider.models.Model`（`model_management.py:21-50`）是持久化配置 owner：`workspace_id + name` 唯一，`provider/model_type/model_name` 决定适配器，`credential` 是 RSA 长密文，`model_params_form` 是 JSON 参数表，`status` 记录 SUCCESS/DOWNLOAD/PAUSE_DOWNLOAD 等状态。模型 CRUD 在 `model_serializer.py` 通过 `ModelProvideConstants[provider]` 做 provider lookup；新增和编辑先取 credential schema、校验参数，再加密写库；编辑会 `ModelManage.delete_key(model.id)`，避免旧实例继续复用。

唯一模型调用门面当前是 `models_provider.tools` 的组合，而不是单一类：

```text
业务节点/知识任务/长期记忆
  → get_model_instance_by_model_workspace_id(model_id, workspace_id, overrides)
  → get_model_by_id（workspace/共享授权）
  → get_model_default_params + reset_model_params
  → ModelManage.get_model（按 id 缓存/建实例）
  → get_model → get_provider(provider)
  → ModelProvideConstants Enum
  → IModelProvider.get_model
  → ModelInfoManage.get_model_info(model_type, model_name)
  → MaxKBBaseModel.new_instance
  → LangChain/SDK/local_model
```

`ModelInfoManage` 在 `model_type → model_name` 字典查找，找不到时回退 `default_model_dict[model_type]`，找不到能力则抛 `AppApiException("The model does not support")`；它同时保留 `model_list` 数组，重复 name 会覆盖字典但不清理旧列表项，存在声明列表与查找字典不完全一致的风险。`ModelProvideConstants` 当前静态实例化 22 个 provider，provider 名称是 Enum key（如 `model_openai_provider`），不是数据库中的自由 URL。

### 28.2 三种缓存不是一个缓存系统

| 缓存 | 实现/键 | 用途 | 生命周期和失效 |
|---|---|---|---|
| Django default | `django_redis.cache.RedisCache`，配置见 `maxkb/conf.py:76-106` | token、权限、chat/debug context、工具执行记录、工作流取消、Celery ready | Redis TTL/显式删除；可切 Sentinel |
| 模型实例缓存 | `ModelManage.cache = MemCache('model', {})` | 当前 Python 进程的模型实例 | 8 小时 TTL；按 model id 加线程锁；编辑/本地模型 apply 显式 delete |
| 矢量 store | `VectorStore.instance` 单例 | `PGVector` 实例 | 进程生命周期，无 TTL/热切换；`VECTOR_STORE_NAME` 只在首次获取时选择 |
| 正则/JSONPath/tokenizer | Django cache 或模块级 cache | workflow compare、JSONPath、分词器 | 各自 TTL/键，无统一清单 |

`MemCache`（`common/cache/mem_cache.py`）是 `LocMemCache` 的未 pickle 包装，`ModelManage.get_model` 用 per-id `threading.Lock` 避免同进程重复建模；它不能跨 Gunicorn/Celery worker 共享。Django Redis cache 才承担跨进程语义。`RedisLock` 用 `SET NX EX` 生成 UUID token，Lua 脚本只在 token 相等时删除，默认 TTL 3600 秒；锁丢失/进程崩溃只能等待 TTL。

工作流 debug 的 `ChatInfo` 缓存最近 20 条 `ChatRecord`、有效期 30 分钟；非 debug 会话记录直接 `update_or_create` 到 PostgreSQL，debug 的 chat variable 写 Redis。知识库 action cancel 的 Redis key 是协作停止信号而非任务结果；DB `KnowledgeAction.state/details` 才是查询 owner。

### 28.3 local_model 接口边界

`SERVER_NAME=local_model` 时 `settings/base/model.py` 的 `INSTALLED_APPS` 只有 `local_model`（加 Django 基础 app），`maxkb/urls/model.py` 只挂载 `local_model.urls`，不加载 knowledge/application/models_provider 全套；默认端口 `127.0.0.1:11636`。web 侧仍通过 `ModelProvideConstants.model_local_provider` 和 provider 实现访问它。故 local_model 是独立运行时/HTTP 边界，不是 web 进程内的一个普通模型类；其数据库和 Redis 配置仍来自同一个 `CONFIG`。

## 29. 数据库、Redis、Celery 和接口边界矩阵

| 边界 | 公开调用者 | 权威写入 | 传输/锁 | 成功判据 | 当前未覆盖 |
|---|---|---|---|---|---|
| 文档 HTTP | Vue/管理端、带 Token 的 API client | `Document/Paragraph/Problem/Mapping/File` serializer | Django transaction + PostgreSQL | 事务提交且响应成功；向量另算 | API 200 不代表 embedding 完成 |
| RAG 查询 | Workflow 节点、Knowledge hit test | 无（查询；脏向量清理例外） | PostgreSQL QuerySet/raw SQL | 结果段落读回并有分数 | provider timeout/cancel 未统一 |
| Embedding Celery | refresh/Create/Sync/迁移 | `Embedding`、compact status、status_meta | RedisLock + Celery queue | task finally 状态聚合、向量可读回 | outbox、重启恢复、失败重放 |
| 问题生成 Celery | generate-related API | `Problem`、mapping、状态 | QueueOnce + DB revoke flag | paragraph 状态 SUCCESS/FAILURE | 单个模型空输出会无状态成功路径风险 |
| 知识工作流 | debug/upload action API | `KnowledgeAction` + write node 业务表 | 进程 executor + Redis cancel | action 状态读回 | future/lease/crash recovery |
| 模型 | 节点/任务/记忆 | `Model` 配置 | RSA credential + MemCache | provider 实例真实返回 | provider 统一错误/资源协议 |
| 应用聊天 | chat API/MCP/OpenAI client | `Chat/ChatRecord` | ThreadPoolExecutor + Redis debug cache | ChatRecord + final response | 请求断开后的 worker 取消 |
| 配置 | 进程启动 | 无（env/YAML） | `CONFIG` singleton | settings 正确加载 | 错误 `SERVER_NAME` 会选错运行时 |

Celery 事实需以源码分开记录：`apps/ops/celery/__init__.py:16-35` 建立 `Celery('MaxKB')`、两条 queue（`celery`、`model`）、HMAC serializer 注册和按 `INSTALLED_APPS` autodiscover；`common/management/commands/celery.py:33-44` 实际启动命令又固定 `-P threads -c 10 -Q <service> --heartbeat-interval 10 --without-mingle`。因此不能把 `app.conf` 的 `worker_concurrency=5` 和管理命令的有效 `-c 10` 混写成一个并发基线。

数据库配置是连接池后端（`DB_ENGINE` 默认 `dj_db_conn_pool.backends.postgresql`），`CONN_MAX_AGE=0`，pool `POOL_SIZE=20`、`MAX_OVERFLOW` 默认 80、`PRE_PING=True`、`TIMEOUT=30`；Django ORM 和 `common.db.sql_execute` 共用 `django.db.connection`。原生 SQL helper 在 `with connection.cursor()` 中执行并主动 close cursor；它不是独立 repository，也没有跨操作的统一事务抽象。`Document/Create`、`Sync`、`Migrate`、工作流写入使用 `transaction.atomic`，Celery 投递通常发生在 atomic 函数内部/装饰器回调中，未见 `transaction.on_commit` outbox，因此存在“数据库回滚但 broker 已收到任务”的边界风险。

## 30. 失败、取消、重复和部分写入矩阵

| 场景 | 当前源码行为 | 证据等级 | 收口结论 |
|---|---|---|---|
| 不支持文件格式 | 先 `File.save`，遍历 parser 无命中后抛 `Unsupported file format` | 源码 | 可能遗留知识库源文件；需运行验证事务/补偿行为 |
| 重复 refresh/embedding | `QueueOnce` keys 按 paragraph/document/knowledge；`AlreadyQueued` 被 API 转成“任务执行中” | 源码 | 任务去重有 provider，但无统一任务账本 |
| 同文档并发 embedding | RedisLock `embedding:<id>`，抢不到直接 return | 源码 | 静默跳过而非返回可查询的冲突状态 |
| 取消 embedding/tokenize | DB compact status 置 `REVOKE`，worker 分页和批次检查；finally 置 `REVOKED` | 源码 | 已完成批次不回滚，取消是协作式 |
| embedding provider 异常 | 段落/文档日志 + FAILURE 状态；知识库任务对 enqueue 异常 `pass` | 源码 | 部分失败可能只在日志，不能视为知识库全失败 |
| 模型不存在/凭据失败 | provider/model lookup 或解密/SDK 异常向上抛；节点结果转 500/exception branch | 源码 | 缺统一稳定错误码和 retryable 字段 |
| workflow 节点异常 | `enableException` 决定异常分支，否则 status 500；future 无 deadline | 源码 | “异常被分支处理”不等于业务成功 |
| action 取消 | Redis flag + DB REVOKE，节点下一检查点停止 | 源码 | 进程崩溃/卡死 provider 时无强制取消证据 |
| 数据库/Redis 断线 | Django pool/Redis client 抛异常；部分外围任务只记录日志 | 静态 | 未实测重连、重放和残留 |
| 进程崩溃 | 内存 future/context 丢失，Redis lock 靠 TTL；DB 已提交业务数据保留 | 源码推断 | 没有节点/任务恢复扫描器 |

后续不把以下内容写成“已具备”：超时取消、Celery 可靠投递、向量写入事务与任务状态原子性、provider 统一重试、工作流崩溃恢复、缓存跨 worker 一致失效。当前能确认的是局部锁、局部状态字段和局部 finally 清理。

## 31. 后续底座裁决：吸收、升级、待核

### 吸收

- 文档入库的“原文 File → split handle → Document/Paragraph → Problem mapping → 异步 embedding”分阶段边界；格式 provider 可替换，但统一输出必须是文档/段落/块结构。
- RAG 三模式 SQL、按知识库分区检索、Termbase 注入全文索引、向量/关键词/混合分数和 reranker 后处理的明确层次。
- `INode → NodeResult → context/NodeChunk → workflow details` 节点运行契约；`node_id` 与 `runtime_node_id` 分离、分支/中断语义值得保留。
- `Model` 配置 owner、provider/model capability 两级注册、模型实例按 ID 缓存和 local_model 独立运行时边界。
- `KnowledgeAction` 对知识工作流的持久状态/详情投影，以及 `TaskType + State` 对文档任务的 compact status 编码。

### 升级现有底座

- **文档仓储/对象存储支持库**：将 File large object、sha256 去重、引用计数、源文件→文档关联和失败补偿做成显式能力；禁止业务模块直接拼 lo SQL。
- **解析与拆分模块库**：provider 输出统一 `Document/Paragraph/Chunk` schema，保留 QA/table/web/office 差异；解析成功前不应把孤儿源文件当作成功资源。
- **向量检索支持库**：统一 embed/batch/query/rerank 结果、阈值、top_n、租约/取消和 stale vector 清理；HNSW/pgvector 只是 provider。
- **模型支持库**：合并 provider registry、model capability registry、credential owner、实例缓存、健康/禁用/重试/超时/用量和版本字段为一个公开门面；消费者禁止绕过 `tools.get_model*` 查 Enum。
- **调度支持库**：Celery、APScheduler、线程池和 RedisLock 都只能是 provider；统一 job key、提交后状态、幂等、取消、重试/死信和恢复扫描。

### 新增运行核心能力

- 入库/embedding/知识工作流统一任务账本：`accepted/running/success/failed/cancelled/retryable`，带 owner、输入 fingerprint、attempt、lease、started/finished、错误和资源清单。
- 事务 outbox 或等价提交协议：数据库事实提交与 Celery 投递不可出现无账本任务；worker 启动时可扫描 pending/running 超时任务并重放/补偿。
- 文档与向量版本/CAS：新解析版本先写 staging，向量全部成功后原子激活；失败/取消不可把部分新向量默认为可检索。
- 工作流节点 deadline/cancellation token/进程重启恢复；`_cleanup`、HTTP 连接 close、Redis TTL 不能替代任务生命周期治理。

### 待核

- 当前默认 split handle 的 `sub_array` 实际批量大小、各 office/PDF parser 的临时文件释放，以及 `list_embedding_text.sql` 是否始终为每个 chunk 生成唯一 source 语义，需在 provider 级继续取证。
- `File.save` large object 在事务回滚、进程中断和重复 sha256 并发写入下的 PostgreSQL 行/loid 一致性未实测。
- Redis Sentinel、连接池耗尽、模型 SDK 流中断、Celery worker 强杀、知识工作流 action 重启后的实际表现未验证。
- 旧版本/远端 `v2` 已有迁移漂移；本节只描述本地 `HEAD 5084a37...`，不把 `/tmp/MaxKB-remote-v2` 的实现混入。

## 32. 后续验收与修改清单

| 项目 | 结果 |
|---|---|
| 旧细探逐条核对 | 已核对；不存在目录、许可证误述、provider 数量和 TTV 术语以当前源码为准 |
| 文档入库 | 已补手工/批量/QA/表格/web/sync/workflow write 调用链、事务和文件 large object 边界 |
| RAG | 已补 embedding 写入、三种 SQL 分数、授权过滤、重排、直接返回和 stale vector 清理 |
| 工作流 | 已补应用流与知识库流差异、节点契约、KnowledgeAction、取消和 executor 边界 |
| 模型 | 已补 Model 持久化、RSA credential、22 provider、ModelInfoManage、ModelManage/VectorStore 缓存 |
| 任务/数据库/缓存 | 已补 Celery queue/autodiscover、RedisLock、Django Redis、MemCache、连接池和事务 outbox 风险 |
| 失败/资源/接口 | 已补失败矩阵、资源生命周期、HTTP/Celery/内部调用边界和未验证项 |
| 实际执行 | 未执行服务、迁移、依赖安装或测试；不能声称运行通过 |

当前核对只修改目标根 `ARCHITECTURE.md`；`细探-MaxKB.md` 保留且未改，源码、依赖、配置、测试和 Git 均未修改。后续 MaxKB 架构事实只维护本文件，旧细探仅作历史线索。
