# Second-Me 架构取证

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 用户界面 / 外部调用                                                          │
│  Next.js + React 页面                                                       │
│  lpm_frontend/src/app、src/service、src/store                               │
│  MCP stdio：mcp/mcp_local.py、mcp/mcp_public.py                             │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ HTTP/JSON、SSE、MCP 工具调用
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Flask API 入口与业务域                                                       │
│  lpm_kernel/app.py → lpm_kernel/api/__init__.py → Flask Blueprints           │
│  documents / memories / upload / loads / trainprocess                       │
│  kernel(L1) / kernel2(本地模型与角色) / talk(聊天) / space / user_llm_config│
└──────────────┬───────────────────────┬───────────────────────┬───────────────┘
               │                       │                       │
               ▼                       ▼                       ▼
┌──────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ 记忆摄入与 L0         │  │ L1 画像与版本化          │  │ 推理与协作               │
│ file_data             │  │ L1 + kernel/l1          │  │ kernel2/services         │
│ processor_factory     │  │ TopicsGenerator         │  │ ChatService             │
│ DocumentService       │  │ ShadeGenerator/Merger   │  │ Prompt strategies       │
│ DocumentChunker       │  │ L1Generator             │  │ L1/L0 retrievers        │
│ InsightKernel         │  │ StatusBioGenerator      │  │ SpaceService            │
│ SummaryKernel         │  │ l1_manager              │  │ DiscussionService       │
└──────────┬───────────┘  └──────────┬─────────────┘  └───────────┬────────────┘
           │                         │                            │
           │ Document/Chunk + L0     │ L1GenerationResult          │ OpenAI-compatible
           │ insight/summary         │                            │ local/external LLM
           ▼                         ▼                            ▼
┌──────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ 持久化与检索          │  │ L2 数据合成与训练        │  │ 本地模型服务            │
│ SQLite + SQLAlchemy  │  │ L2Generator             │  │ llama.cpp/build/bin/    │
│ data/sqlite/lpm.db   │  │ L2DataProcessor         │  │ llama-server            │
│ ChromaDB collections │  │ GraphRAG 索引           │  │ LocalLLMService         │
│ documents            │  │ preference/diversity   │  │ OpenAI SDK client       │
│ document_chunks      │  │ selfqa/context          │  │ SSE 流式适配            │
│ DatabaseSession      │  │ LoRA/Transformers/TRL  │  └────────────────────────┘
│ BaseRepository       │  │ merge → GGUF → Ollama   │
│ migration_manager    │  │ MLX 可选分支            │
└──────────┬───────────┘  └──────────┬─────────────┘
           │                         │ 文件制品/模型制品
           └──────────────┬──────────┘
                          ▼
        原始文件 → Document → chunks/embeddings → L0 → L1 Bio/Shades
          → L2 训练 JSON → LoRA/合并模型 → GGUF/llama-server 推理
          → Chat/Role/Space/MCP 对外返回
```

# 项目定位

Second-Me 是一个本地训练、本地托管、可通过网络或应用连接的个人 AI self 原型。README 将其定位为以用户自己的 memories 训练个性化 AI self，并提供 Second Me Network、Roleplay、AI Space 和本地隐私控制。源码实现的主线是：用户文件/记忆进入后端，经过文档解析、切块、向量化和 L0 单文档分析，再生成 L1 全局画像，随后合成 L2 训练数据并执行微调、权重合并和 GGUF 转换，最终由本地 llama.cpp 服务承载对话。

源码事实与文档口径有一处需要特别区分：后端实际入口是 Flask（`lpm_kernel/app.py`、`lpm_kernel/api/__init__.py`），不是 FastAPI；前端实际是 Next.js/React（`lpm_frontend/package.json`）。

# 真实目录/分层与职责

以下目录来自当前仓库实际文件；首次分析时项目根未发现 `AGENTS.md`，也未发现已有 `ARCHITECTURE.md`（本文件即当前核对建立并持续维护的唯一架构文档）。

- `lpm_kernel/`：Python 后端包。
  - `lpm_kernel/app.py`：创建 Flask app，初始化 `DatabaseSession`，挂载 `/raw_content/` 文件服务，并调用 `init_routes` 注册业务蓝图；模块执行时创建全局 `app`。
  - `lpm_kernel/api/`：HTTP API 层。
    - `api/__init__.py`：集中导入并注册 health、documents、kernel、kernel2、loads、memories、roles、trainprocess、upload、space、talk、user_llm_config 蓝图。
    - `api/domains/documents/`：文档扫描、分析、L0、chunk 和 embedding 管理。
    - `api/domains/memories/`：上传及删除记忆文件。
    - `api/domains/upload/`：上传实例注册、连接、状态和列表，并使用 `RegistryClient`。
    - `api/domains/loads/`：当前个人 load、描述、avatar 和实例信息。
    - `api/domains/trainprocess/`：训练步骤编排、停止、重训、日志、进度和步骤输出。
    - `api/domains/kernel/`：L1 global bio、版本、status bio、notes 相关接口。
    - `api/domains/kernel2/`：本地 llama-server 管理、基础聊天和角色管理；`services/` 负责消息、提示词、知识检索、聊天和高级聊天。
    - `api/domains/space/`：多 Second Me 协作空间；包含 DTO、repository、service、context 和 discussion strategies。
    - `api/domains/user_llm_config/`：聊天、embedding、thinking 模型配置的读取和更新。
    - `api/services/`：本地 LLM、专家 LLM、用户 LLM 配置等跨域服务。
    - `api/common/`：API response/error、脚本执行和脚本运行封装。
  - `lpm_kernel/file_data/`：文件到 Document/Chunk 的摄入和检索基础设施。
    - `processors/` 和 `process_factory.py`：按 text、markdown、pdf、image 等类型解析。
    - `document.py`、`document_service.py`、`document_repository.py`：Document 持久化和文档业务编排。
    - `chunker.py`：使用 LangChain `RecursiveCharacterTextSplitter` 切块，默认 `chunk_size=1000`、`overlap=200`。
    - `embedding_service.py`、`chroma_utils.py`：调用 `LLMClient` 获取向量，写入 ChromaDB 的 `documents` 与 `document_chunks` 集合，并检查向量维度。
    - `models.py`、`dto/`：ChunkModel、DocumentModel、ChunkDTO 等持久化/传输结构。
  - `lpm_kernel/L0/`：L0 生成层。`l0_generator.py` 的 `L0Generator` 按 DOCUMENT/IMAGE/AUDIO 分派 insight，并生成 summary/title/keywords；`models.py` 定义 `FileInfo`、`BioInfo`、`InsighterInput`、`SummarizerInput`。
  - `lpm_kernel/kernel/`：旧/基础 kernel 编排层。
    - `kernel/l0_base.py`：将 `L0Generator` 和 summarizer 接入文件数据流程。
    - `kernel/chunk_service.py`、`kernel/note_service.py`：chunk 和 Note 的服务编排。
    - `kernel/l1/l1_manager.py`：从文档及其 L0、Document/Chunk embedding 构造 `Note`，调用 L1 生成并保存结果，也负责读取最新 Bio/status bio。
  - `lpm_kernel/L1/`：L1 算法和领域对象。
    - `bio.py`：`Note`、`Chunk`、`Memory`、`Cluster`、`Bio`、`ShadeInfo` 等领域对象。
    - `topics_generator.py`：层次聚类、离群点、邻近簇合并及 chunk topic 生成。
    - `shade_generator.py`、`status_bio_generator.py`：兴趣域 Shade 与状态传记。
    - `l1_generator.py`：组合 topics、shade、global biography、视角转换、置信度和 status bio。
    - `prompt.py`、`serializers.py`、`utils.py`：提示词、序列化和 L1 辅助函数。
  - `lpm_kernel/L2/`：训练数据和模型制品流水线。
    - `l2_generator.py`、`data.py`：L2 数据预处理和三类主观数据生成/合并。
    - `data_pipeline/data_prep/`：preference、diversity、selfqa、context 等生成器和 prompt。
    - `data_pipeline/graphrag_indexing/`：GraphRAG 配置、prompt、输入输出制品。
    - `train.py`、`train_for_user.sh`：训练入口；`merge_lora_weights.py`、`merge_weights_for_user.sh`：合并入口；`convert_hf_to_gguf.py`：GGUF 转换。
    - `dpo/`：DPO 训练分支。
    - `mlx_training/`：Apple Silicon 的 MLX 数据转换、LoRA 训练、转换/服务和测试脚本。
    - `gguf-py/`：随仓库保留的 GGUF Python 工具子包及其 `tests/`。
  - `lpm_kernel/models/`：SQLAlchemy 持久化模型，包含 `Memory`、L1 版本/Bio/Shade/Cluster/ChunkTopic、`StatusBiography`、`Space`/`SpaceMessage` 等。
  - `lpm_kernel/common/`：配置无关的公共能力。
    - `common/repository/database_session.py`：SQLite engine、session factory、事务上下文。
    - `common/repository/base_repository.py`：通用 CRUD repository。
    - `common/repository/vector_repository.py`、`vector_store_factory.py`：向量仓储抽象/工厂。
    - `common/llm.py`、`common/strategy/`：LLM 客户端和 provider strategy。
  - `lpm_kernel/configs/`：从 `.env` 读取单例 `Config`、SQLite 路径、Chroma 路径和服务 URL。
  - `lpm_kernel/database/`：SQLite 迁移管理器及迁移脚本。
- `lpm_frontend/`：Next.js 14 + React 18 前端。
  - `src/app/`：App Router 页面，包含 dashboard、train、playground、applications 和 standalone role/space/room。
  - `src/service/`：Axios API service，按 upload、memory、train、space、role、modelConfig、model、info 等领域调用后端。
  - `src/store/`：Zustand 状态（upload、training、space、model config、load info）。
  - `src/utils/request.ts`：Axios 包装、JSON 序列化、upload 本地登录态检查和响应状态处理。
- `resources/`：运行时数据和模型制品目录；包括 L1 GraphRAG 输出、L2 data pipeline/raw data、个人/合并模型输出等占位目录。
- `scripts/`：setup/start/stop/restart/status、迁移和平台辅助脚本；`start_local.sh` 会加载 `.env`、初始化 SQLite/ChromaDB、运行迁移并通过 Flask 启动后端。
- `docker/`：SQLite 初始化 SQL、Chroma 初始化、GPU 检测和容器辅助文件。
- `Dockerfile.backend*`、`Dockerfile.frontend`、`docker-compose*.yml`：后端/前端容器及 CPU、CUDA、Apple Silicon 选择。
- `mcp/`：两个 FastMCP stdio server；local 通过本地 API 对话，public 通过 `app.secondme.io` 对话并查询 online instances。
- `integrate/wechat_bot.py`：独立的微信集成脚本。

# 核心数据流

1. **记忆文件摄入**：前端 `src/service/memory.ts` 调用 `/api/memories/file`；后端由 memories route 和 storage service 保存文件，并与 `memories` 表关联。
2. **文件解析为 Document**：`DocumentService.scan_directory()` 调用 `ProcessorFactory.auto_detect_and_process()`，构造 `CreateDocumentRequest` 后通过 `DocumentRepository` 写入 `document` 表。`Document` 的 `raw_content`、解析状态、URL、文件类型和分析字段是主数据。
3. **切块与向量化**：`TrainProcessService.process_chunks()` 使用 `DocumentChunker` 将 `raw_content` 转成 Chunk；`EmbeddingService` 调用 `LLMClient.get_embedding()`，分别写入 SQLite `chunk` 表和 ChromaDB `document_chunks` 集合。文档级 embedding 写入 ChromaDB `documents` 集合。
4. **L0 单文档分析**：`DocumentService.analyze_all_documents()` 找出未分析文档，调用 `InsightKernel`/`L0Generator.insighter()` 生成 insight/title，再由 summarizer 生成 summary/keywords，最后由 `DocumentRepository.update_document_analysis()` 写回 Document JSON 字段。
5. **L1 全局画像**：`lpm_kernel/kernel/l1/l1_manager.py:generate_l1_from_l0()` 读取所有带 L0 的文档、文档 embedding、chunk 和 chunk embedding，构造 `Note`/`Memory`；`L1Generator` 先调用 `TopicsGenerator` 聚类和 chunk topic，再为 cluster 生成 Shade、合并 Shade，生成 Bio 的第三人称与第二人称内容，并返回 `L1GenerationResult`。API/kernel route 再将其写入 `l1_versions`、`l1_bios`、`l1_shades`、`l1_clusters`、`l1_chunk_topics`。
6. **状态传记**：`generate_status_bio()` 当前从带 L0 的 notes 生成 status bio，`store_status_bio()` 在写入前删除旧 `status_biography` 行，因此当前实现是单表覆盖式最新状态，而非与 global bio 相同的版本链。
7. **L2 数据合成**：`TrainProcessService._prepare_l2_data()` 准备 topics、notes、global/status bio 和 GraphRAG 路径；`L2Generator` 调用 preference、diversity、selfqa 生成器，写入 `resources/L2/data/*.json`，再合并为 `merged.json`。README/L2 源码还声明可选 DeepSeek-R1 CoT 格式和 MLX 分支；具体 CoT 开关由 `is_cot`/训练参数控制。
8. **微调与模型制品**：训练步骤由 `ProcessStep.get_ordered_steps()` 定义。`TrainProcessService.start_process()` 从进度文件中最后成功步骤之后继续；训练、合并、GGUF 转换通过 shell/subprocess 或 `ScriptExecutor` 执行，并把制品放到 `resources/model/output/` 下的 personal/merged/gguf 目录。
9. **推理**：`LocalLLMService` 管理 `llama.cpp/build/bin/llama-server`，默认监听 8080；`ChatService.chat()` 使用 OpenAI-compatible client 发送 messages。`KnowledgeEnhancedStrategy` 可按 metadata 或 role 配置注入 L0 chunk 检索结果和 L1 shade 检索结果，随后通过 `/api/talk/chat` 或 `/api/kernel2/chat` 输出 JSON/SSE。
10. **协作与外部网络**：`SpaceService` 将 host 和 participant endpoint 保存为 `Space`，启动后台线程执行 `DiscussionService` 多轮讨论，将消息和结论写回 `space_messages`/`spaces`；share 操作再向配置的 registry URL 发 HTTP 请求。MCP server 以 stdio 工具协议分别转发本地或 public chat。

# 关键类/函数/数据模型及相对路径

## 入口与编排

- `create_app()`、全局 `app`：`lpm_kernel/app.py`
- `init_routes()`：`lpm_kernel/api/__init__.py`
- `DocumentService.create_document()`、`scan_directory()`、`analyze_all_documents()`、`process_document_embedding()`：`lpm_kernel/file_data/document_service.py`
- `DocumentChunker.split()`：`lpm_kernel/file_data/chunker.py`
- `EmbeddingService.generate_document_embedding()`、`generate_chunk_embeddings()`、`search_similar_chunks()`：`lpm_kernel/file_data/embedding_service.py`
- `L0Generator.insighter()`、`summarizer()`：`lpm_kernel/L0/l0_generator.py`
- `generate_l1_from_l0()`、`extract_notes_from_documents()`、`get_latest_global_bio()`：`lpm_kernel/kernel/l1/l1_manager.py`
- `L1Generator.gen_topics_for_shades()`、`gen_shade_for_cluster()`、`gen_global_biography()`、`gen_status_biography()`：`lpm_kernel/L1/l1_generator.py`
- `TrainProcessService.start_process()`、`_prepare_l2_data()`、`train()`、`merge_weights()`、`convert_model()`：`lpm_kernel/api/domains/trainprocess/trainprocess_service.py`
- `L2Generator.data_preprocess()`、`gen_preference_data()`、`gen_diversity_data()`、`gen_selfqa_data()`、`merge_json_files()`：`lpm_kernel/L2/l2_generator.py`
- `ChatService.chat()`、`collect_stream_response()`：`lpm_kernel/api/domains/kernel2/services/chat_service.py`
- `SystemPromptBuilder`、`BasePromptStrategy`、`RoleBasedStrategy`、`KnowledgeEnhancedStrategy`：`lpm_kernel/api/domains/kernel2/services/prompt_builder.py`
- `L0KnowledgeRetriever.retrieve()`、`L1KnowledgeRetriever.retrieve()`：`lpm_kernel/api/domains/kernel2/services/knowledge_service.py`
- `LocalLLMService.start_server()`、`stop_server()`、`handle_stream_response()`：`lpm_kernel/api/services/local_llm_service.py`
- `SpaceService.create_space()`、`start_discussion()`、`share_space()`：`lpm_kernel/api/domains/space/space_service.py`

## 核心数据模型

- `Document`：`lpm_kernel/file_data/document.py`；主字段包括 id/name/title、三类处理状态、raw_content、mime_type、insight、summary。
- `DocumentModel`、`ChunkModel`：`lpm_kernel/file_data/models.py`；对应 `document`/`chunk` 表的另一组 ORM 声明，并提供 relationship/DTO 转换。
- `ChunkDTO`：`lpm_kernel/file_data/dto/chunk_dto.py`；携带 document_id、content、embedding 状态、tags、topic 和 length。
- `Memory`：`lpm_kernel/models/memory.py`；保存上传文件元信息、物理路径、关联 document_id 和 active/deleted 状态。
- `L1Version`、`L1Bio`、`L1Shade`、`L1Cluster`、`L1ChunkTopic`：`lpm_kernel/models/l1.py`；以 version 外键组织 L1 画像、兴趣域、聚类和 chunk topic。
- `StatusBiography`：`lpm_kernel/models/status_biography.py`；独立的当前状态传记表。
- `Space`、`SpaceMessage`：`lpm_kernel/models/space.py`；保存协作空间、参与者 endpoint、讨论轮次、消息和结论。
- `ChatRequest`、`AdvancedChatRequest`、`ValidationResult`、`AdvancedChatResponse`：`lpm_kernel/api/domains/kernel2/dto/chat_dto.py` 与 `advanced_chat_dto.py`。
- `ProcessStep`、`Status`、`TrainProgressHolder`：`lpm_kernel/api/domains/trainprocess/process_step.py`、`progress_enum.py`、`progress_holder.py`；训练进度落盘为 `data/progress/trainprocess_progress_<model>.json`。
- SQLite 表定义：`docker/sqlite/init.sql`；包括 document/chunk、L1 表、status_biography、loads、memories、roles、user_llm_configs、spaces 和 space_messages。

# API/CLI/SDK入口

## HTTP API

- Flask 应用：`lpm_kernel.app:app`；本地脚本以 `python -m flask run --host=0.0.0.0 --port=${LOCAL_APP_PORT}` 启动，Docker 默认使用 8002。
- 健康与原始内容：`/health`、`/raw_content/<path>`，实现于 `lpm_kernel/app.py` 和 `api/domains/health/routes.py`。
- 文档与向量：`/api/documents/*`，实现于 `api/domains/documents/routes.py`。
- 记忆文件：`/api/memories/file`，实现于 `api/domains/memories/routes.py`。
- 上传实例：`/api/upload/*`，实现于 `api/domains/upload/routes.py`。
- loads：`/api/loads/*`，实现于 `api/domains/loads/routes.py`。
- L1：`/api/kernel/l1/*`，实现于 `api/domains/kernel/routes.py`。
- 本地 llama-server 与基础 chat：`/api/kernel2/health`、`/api/kernel2/llama/*`、`/api/kernel2/chat`，实现于 `api/domains/kernel2/routes_l2.py`。
- 角色：`/api/kernel2/roles/*`，实现于 `api/domains/kernel2/routes/role_routes.py`。
- 高级聊天：`/api/talk/chat`、`/api/talk/chat_json`、`/api/talk/advanced_chat`，实现于 `api/domains/kernel2/routes_talk.py`。
- 训练：`/api/trainprocess/*`，实现于 `api/domains/trainprocess/routes.py`。
- AI Space：`/api/space/*`，实现于 `api/domains/space/space_routes.py`。
- 用户模型配置：`/api/user-llm-configs/*`，实现于 `api/domains/user_llm_config/routes.py`。

## CLI/脚本

- Make 入口：`Makefile` 的 `setup/start/stop/restart/status`、`docker-build/docker-up/docker-down`、`install/test/format/lint`。
- 本地启动：`scripts/start.sh` → `scripts/start_local.sh` 与前端 `npm run dev`。
- 迁移：`scripts/run_migrations.py`；支持默认执行和 `create` 子命令，底层为 `lpm_kernel/database/migration_manager.py`。
- 训练/转换：`lpm_kernel/L2/train_for_user.sh`、`merge_weights_for_user.sh`、`convert_hf_to_gguf.py`；MLX 入口见 `lpm_kernel/L2/mlx_training/README.md`。
- `pyproject.toml` 没有声明 `[tool.poetry.scripts]`，因此没有单独注册的 Poetry Python CLI 名称。

## MCP/SDK

- `mcp/mcp_local.py`：`FastMCP("mindverse")`，以 stdio 启动，工具 `get_response(query)` 转发本地 `/api/kernel2/chat`。
- `mcp/mcp_public.py`：`FastMCP("mindverse_public")`，以 stdio 启动，工具 `get_response(query, instance_id)` 和 `get_online_instances()` 调用 public 服务。
- 仓库未发现独立 Python/TypeScript SDK 包；前端的 HTTP client 是 `lpm_frontend/src/utils/request.ts`，领域调用封装位于 `lpm_frontend/src/service/`。

# 技术栈和依赖

- 后端语言/运行时：Python `>=3.12,<3.13`，Poetry；Flask 3、Flask-Sock、flask-pydantic、Pydantic 2、SQLAlchemy 2、SQLite。
- LLM/推理：OpenAI Python SDK 的 OpenAI-compatible client、`llama.cpp` 的 `llama-server`；`lpm_kernel/api/services/local_llm_service.py` 将本地服务适配为流式 API。
- 记忆检索：ChromaDB 持久化客户端；`numpy`、`scikit-learn`、`sentence-transformers`、`tiktoken`；LangChain 的 `RecursiveCharacterTextSplitter`。
- 文件处理：PyMuPDF、pdfplumber、pytesseract、requests、aiohttp、charset-normalizer。
- L1 算法：SciPy hierarchical clustering、NumPy；OpenAI-compatible LLM 用于主题、Shade 和 Bio 文本生成。
- L2 训练/数据：GraphRAG 归档依赖、Transformers、Torch、PEFT、TRL、datasets、pandas、gguf；`pyproject.toml` 将这些列在 dev 组中，GraphRAG tar 包由 `Dockerfile.backend` 在镜像构建时安装。
- Apple Silicon：`lpm_kernel/L2/mlx_training/` 采用 MLX-LLM 脚本分支；其 README 给出独立的 `mlx-lm` 前置依赖和数据转换/训练/转换流程。
- 前端：Node 23 容器、Next.js 14.2、React 18、TypeScript 5、Axios、Ant Design、Zustand、Tailwind CSS、styled-components、Three.js、Framer Motion。
- 集成：FastMCP、微信集成依赖见 `integrate/requirements.txt`（wxpy、python-dotenv、torch、transformers、numpy）。
- 部署：CPU/CUDA/Apple 后端 Dockerfile，`docker-compose.yml`/`docker-compose-gpu.yml`；后端端口 8002，前端端口 3000，llama-server 端口 8080。

# 架构判断与未确认项

## 已确认的架构特征

- 实现是 Flask 单体后端 + Next.js 前端 + 本地 SQLite/ChromaDB + 本地 llama.cpp 的分层单体，而不是微服务。训练和模型服务通过 subprocess/独立进程边界与 Web 进程解耦。
- L0/L1/L2 是实际代码中的处理层：L0 产生单文档 insight/summary，L1 产生 clusters/shades/Bio，L2 产生训练 JSON 和模型制品；训练步骤把三层串为可恢复流程。
- L1 版本表让 global bio、shade、cluster、chunk topic 以同一 version 组织；但 status biography 的实现会先删除旧记录，因此两类画像的历史语义不同。
- 推理提示词采用策略链：基础 system prompt → role prompt → 可选 L0/L1 检索，且 role 的检索开关优先于请求 metadata。
- 训练进度是文件状态机而非数据库任务队列；`TrainProgressHolder` 读取上次进度、将遗留 `in_progress` 改为 `failed`，并从最后成功步骤继续。

## 需要谨慎对待的实现风险

- ORM 声明存在多套来源：`common/repository/database_session.py` 提供 `DeclarativeBase`，`file_data/document.py` 和 `lpm_kernel/models/*` 使用它；但 `file_data/models.py` 又单独调用 `declarative_base()` 定义 `DocumentModel`/`ChunkModel`。仅凭文件存在不能证明所有模型都被同一 metadata 注册或在运行时一致。
- `BaseRepository.create/list` 会调用 `model.from_dict()` 和 `to_dict()`；这是通用约定，但不同 ORM/domain 模型的转换实现并不完全一致，实际覆盖范围未通过运行时验证。
- `EmbeddingService` 在发现 ChromaDB 向量维度变化时调用重建逻辑；`file_data/chroma_utils.py` 的重建行为及已有向量保留策略需要运行时/数据级验证，文档不把它视为无损迁移。
- L1 生成依赖用户 LLM 配置和现存 document/chunk embeddings；没有配置、向量或有效 notes 时，代码会返回空/None 或记录 warning，不能把 L1 视为独立离线纯函数。
- `LocalLLMService.start_server()` 当前源码在 GPU 检测后又将 `cuda_available` 设为 `False`，因此实际代码路径会落到 CPU 参数；CUDA Docker 构建和运行配置的完整效果未通过服务启动验证。
- `SpaceService` 使用线程执行讨论并通过 HTTP 访问参与者 endpoint；没有在本次只读检查中验证线程生命周期、远端协议和失败重试的一致性。

## 未确认项

- 未安装依赖、未运行服务、未执行迁移、未启动 llama-server、未调用外部 LLM/GraphRAG，也未执行测试；因此本文是源码结构分析，不是运行就绪性结论。
- `Makefile` 声明 `poetry run pytest tests`，但仓库实际检索到的测试文件只有 `lpm_kernel/L2/gguf-py/tests/test_metadata.py`、`test_quants.py` 和 `lpm_kernel/L2/mlx_training/test_mlx.py`；未发现覆盖 Flask API、DocumentService、L0/L1、L2 主流程或 Space 的核心行为测试。
- `.env` 中的实际 `LOCAL_APP_PORT`、`LOCAL_LLM_SERVICE_URL`、数据库和 registry URL 未在本文展开；`Config.from_env()` 是运行时配置来源，且 `.env` 内容不作为架构结论。
- GraphRAG tar 包、llama.cpp 压缩包和模型文件来自 `dependencies/`/运行时目录；本次只核对了 Dockerfile 的使用关系，没有安装或验证其版本内容。
- README 提到的网络产品和云端能力只能确认其文档定位；本地仓库实际可执行边界以 Flask routes、MCP scripts 和现有前端 service 为准。

## 本次分析边界

本文件已吸收此前 `细探-Second-Me.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本文件是本项目根目录唯一新增/更新的交付文件。除本文件外，没有修改已有源码、配置、测试或 Git 历史。

# 后续：通用底座映射与生命周期裁决

## 1. 当前核对边界、证据和层级解释

当前核对不是把 Second-Me 的产品名、提示词或训练流程搬进系统工程平台，而是从当前源码抽取可复用的**原子能力、契约边界、状态转移和资源治理要求**。源码证据主要来自：

- 摄取与向量：`lpm_kernel/file_data/document_service.py`、`process_factory.py`、`chunker.py`、`embedding_service.py`、`common/llm.py`；
- 身份/状态/记忆：`lpm_kernel/models/memory.py`、`models/l1.py`、`models/status_biography.py`、`L1/`、`kernel/l1/l1_manager.py`；
- 任务/制品：`api/domains/trainprocess/process_step.py`、`progress_holder.py`、`trainprocess_service.py`、`api/common/script_executor.py`；
- 模型与流式服务：`api/services/local_llm_service.py`、`api/domains/kernel2/services/knowledge_service.py`、`prompt_builder.py`、`chat_service.py`；
- 对外与协作：`api/__init__.py`、各 `api/domains/*/routes.py`、`mcp/mcp_local.py`、`mcp/mcp_public.py`、`api/domains/space/space_service.py`、`space/context/context_manager.py`；
- 资源边界：`common/repository/database_session.py`、`local_llm_service.py`、`trainprocess_service.py`。

此前旧细探已读：`~/Documents/Agent/PHP/系统工程平台/开发文档/临时文档/细探/细探-Second-Me.md`。目标仓库内没有同名旧细探文件；旧细探仍保留在原位置，当前核对没有删除或修改它。

**重要区分**：Second-Me 自己的 `L0/L1/L2` 是产品数据蒸馏/训练阶段；本文件以下另定义平台 `L0-L4`，只是通用底座映射坐标，不声称源码已有这五层，也不把产品的 `L0/L1/L2` 当作平台包名。

```text
平台 L0  公共契约与生命周期原语
  ↓
平台 L1  支持库：单一能力 id、provider 适配、错误/资源转换
  ↓
平台 L2  模块库：只组合公开能力的领域流程
  ↓
平台 L3  运行核心：装载、注册、调度、租约、资源、取消、恢复、证据
  ↓
平台 L4  统一网关：HTTP/MCP/SSE/CLI 等协议适配、认证、限流、背压
```

当前目标源码根目录存在独立 `.codegraph/`，本轮只用目标目录内 CodeGraph CLI 作定位；专属 MCP 首次返回的是错误项目 `~/Documents/Agent/PHP/华世王镞_v3`，切换目标后不采用该 MCP 证据。因此当前核对源码事实仍只采用本地文件读取结果和已读旧细探，不把错误项目的代码图或 MCP 摘要当作 Second-Me 证据；运行验证也未被冒充为通过。

## 2. 平台 L0-L4 的可复用原子能力定义

| 平台层 | 只保留什么 | Second-Me 对应证据 | 明确不搬什么 |
|---|---|---|---|
| L0 公共契约 | `身份/状态/记忆/文档/向量/模型/任务/制品/句柄/租约`的稳定字段；统一 `成功/值/错误码/错误说明/可重试/详情`；幂等键、截止时间、取消和释放结果 | `Memory.status`、`L1Version`、`ProcessStep/Status`、`APIResponse`、`DatabaseSession.session()` | `Second Me`、`Shade`、`Bio` 等产品语义；任何 prompt 原文不能成为公共契约 |
| L1 支持库 | 文件解析、规范化、切块、embedding、向量查询、LLM 调用、结构化解析、数据库事务、HTTP、受管进程、日志流等**单原子能力**；provider 差异在此转换 | `ProcessorFactory`、`DocumentChunker`、`EmbeddingService`、`LLMClient`、`ScriptExecutor`、`DatabaseSession` | 不允许支持库编排训练流程、直接暴露第三方对象或把 Chroma/llama.cpp 类型穿透给上层 |
| L2 模块库 | 记忆摄取、身份/状态重建、上下文检索、模型制品流水线、协作讨论等组合流程；每步只持有能力 id/契约版本 | `DocumentService`、`L1Generator`、`KnowledgeEnhancedStrategy`、`TrainProcessService`、`SpaceService` | 不复制 provider；不让模块直接 `subprocess`、直连 Chroma、直连远端注册表 |
| L3 运行核心 | 唯一注册表/调用器，任务队列与背压，句柄和租约，超时/取消/崩溃恢复，进程组/线程/队列/临时文件/模型上下文的配额和清理，证据记录 | 现有源码只提供局部材料：进度 JSON、stop flag、`psutil` 子进程处理、SSE `completion_event` | 不能把单例、daemon thread、全局环境变量、扫描进程名当作运行核心契约 |
| L4 统一网关 | 路由、MCP tool、SSE、认证、输入校验、协议转换、幂等/限流/背压、统一错误；不包含领域编排 | Flask Blueprints、`mcp_local.py`/`mcp_public.py`、`handle_stream_response()` | 网关不直接写模型/记忆表，不在 HTTP handler 里偷偷启动第二条任务链 |

## 3. 六类能力的命中表与单链路落点

### 3.1 身份、状态和记忆

| 源码事实 | 可抽取的原子能力 | 底座落点 | 裁决 |
|---|---|---|---|
| `Memory` 有文件路径、`document_id`、时间和 `active/deleted`；删除是状态而不是立即抹掉所有引用 | 记忆记录登记、软删除、文档关联、来源元数据读取 | L1「记忆记录/来源登记」支持库；L2「记忆摄入」模块 | **吸收**生命周期和来源关联；不复制 `Memory` 产品字段名 |
| `L1Version` 作为父版本，bio/shade/cluster/topic 挂版本；`get_latest_global_bio()` 读取最新版本 | 不可变画像版本、子对象挂载、激活/读取指针、版本比较 | L0 版本/激活契约 + L1 版本存储；L2 身份重建模块 | **吸收**“生成新版本再切激活指针”；禁止复用 status bio 的覆盖写 |
| `StatusBiography` 生成前删除旧行，再写当前状态；旧状态不形成版本链 | 当前状态快照写入/读取 | L1 状态快照能力，但必须补历史/来源/过期时间 | **升级**：保留“快状态”和慢身份分开，拒绝无审计覆盖写 |
| L1 `Bio/Shade/Cluster` 同时有第二/第三人称投影、聚类中心、时间线和置信度 | 身份声明投影、主题聚类、置信度和时间线 | L1「身份声明/聚类/投影」原子能力；L2 身份模型模块 | **吸收**双投影、版本挂载、来源引用；不把人格推断当无条件事实 |
| `TrainProgressHolder` 保存 stage/step 状态，启动时把遗留 `in_progress` 改为 `failed` | 可持久化任务状态、崩溃后恢复判定、从最后成功步骤继续 | L0 任务状态契约；L3 任务状态存储/恢复器 | **吸收但升级**：加 `run_id`、租约世代、心跳、原因和制品指纹，不能只按 model name 复用文件 |

身份能力的规范输入应是“主体 id + 版本/激活指针 + 声明集合 + 来源证据 + 置信度 + 生命周期状态”，而不是一段名为 `globalBio` 的提示词。`active/retired/disputed/expired` 等状态必须能阻止陈旧或争议声明进入稳定上下文；Second-Me 的 `status_biography` 覆盖写只能作为风险样本。

### 3.2 数据摄取

真实链路是 `Memory/file upload → DocumentService → ProcessorFactory → Document → DocumentChunker → Chunk → EmbeddingService → SQLite/ChromaDB`，再由 L0 分析写回文档字段。可复用原子能力应拆为：

1. `读取对象`：受控路径/流句柄、大小与 MIME 上限、来源标识、内容摘要和幂等键；
2. `识别与解析`：按文件类型发现 provider，输出统一文档结构和解析警告；
3. `规范化与切块`：有界 token/字符、overlap、确定性 chunk id、父文档引用；
4. `向量生成`：embedding provider、模型指纹、维度和批量预算；
5. `索引写入`：事务性元数据写入 + 可重建索引写入，记录部分成功和重试；
6. `洞察生成`：单文档结构化抽取，失败不污染原文，输出 `insight/summary/keywords` 作为派生制品。

Second-Me 已有长度切分、空输入校验、向量维度检查和缺字段跳过，但没有完整的内容寻址幂等、摄取租约、批次回滚和“原文不可变 + 派生制品可重建”契约。Chroma 维度变化触发重建且可能清空数据，必须在平台 L1 provider 中变成显式迁移/备份能力，不能作为隐藏 fallback。

**落点**：解析、切块、embedding、索引、原文存储分别是 L1 支持库；“一批来源文件到可检索记忆”的编排是 L2 模块；批次并发、租约、重试、回滚、残留扫描是 L3；上传 API/MCP 是 L4。

### 3.3 模型、检索和上下文

- `LLMClient.get_embedding()` 会按最大文本长度切分，调用用户配置的 embedding strategy，再平均合并；无配置抛 `EmbeddingError`。这可抽取为“embedding 调用 + 模型指纹 + 维度契约”，不应让模块依赖 `numpy` 数组或 provider 配置对象。
- `L0KnowledgeRetriever` 的 chunk 检索与 `L1KnowledgeRetriever` 的 shade 检索分轨，再由 `KnowledgeEnhancedStrategy` 注入提示词；这可抽取为“检索轨道、阈值、top-k、来源标签、预算”和“上下文组装”能力。不要照搬 `Reference knowledge`/`Reference shades` 文案。
- `ChatService`/`LocalLLMService` 把 OpenAI-compatible client、llama-server 和 SSE 适配在服务层；平台应拆成 L1 的模型调用/流适配能力、L2 的上下文问答模块、L3 的受管模型进程与并发配额、L4 的 HTTP/MCP/SSE 门面。
- `LocalLLMService.start_server()` 启动本地进程并以固定等待后轮询，`stop_server()` 扫描命令行并强杀所有匹配进程；这是“受管进程能力”的输入，不是可直接复用的所有权模型。必须按 `provider_id + instance_id + process_group` 精确管理，禁止按进程名误杀。

推荐单链路：

```text
L4 请求/工具
  → L2「上下文问答」模块
  → L3 唯一能力调用器（按能力 id 选模型/检索 provider）
  → L1「聊天」「embedding」「向量检索」「重排」「结构化输出」支持库
  → 受管模型进程/HTTP provider/向量索引
  → 统一结果 + 来源 + 延迟 + 资源释放证据
```

### 3.4 服务/API 与网关

Flask route 当前同时承担参数校验、创建线程、返回响应、读进度和轮询停止；MCP 脚本直接转发本地或 public chat。可复用的只有：

- L0：请求、响应、错误码、流事件、幂等和取消契约；
- L1：HTTP client、MCP transport、SSE 编解码、认证材料引用；
- L2：领域命令（摄取、重建身份、启动训练、查询上下文）；
- L3：把命令转成可追踪 `task_id/run_id`，提供状态、取消、重试和恢复；
- L4：路由和工具描述、鉴权、限流、背压、版本兼容、统一错误转换。

`APIResponse`/`APIError` 只有粗粒度 code/message/data，底层异常仍可能被拼入 message；平台应把 provider 错误转换到统一错误码，并把敏感细节放受控诊断字段。`/logs` 和 `handle_stream_response()` 不能只靠客户端断开作为清理信号，网关必须有明确的流句柄关闭和任务取消回执。

### 3.5 任务、制品和资源

训练链是 `ProcessStep` 顺序执行；`/start` 在 Flask handler 中创建 daemon thread；训练/合并/转换使用 `subprocess`/`ScriptExecutor`；模型制品落到多个目录；进度落 JSON。可抽取能力：

- 任务定义：步骤 id、输入制品、输出制品、版本约束、重试策略；
- 任务实例：`task_id/run_id`、状态、当前步骤、尝试次数、开始/截止时间、取消原因；
- 制品登记：内容摘要、生产任务、provider、状态、激活指针；
- 执行器：受管进程/容器、日志流、退出码、信号、进程组和子进程回收；
- 恢复器：租约过期判定、崩溃恢复、幂等重放、部分制品隔离；
- 资源协调：CPU/GPU/内存/磁盘/端口/并发 token 和临时目录配额。

`_cleanup_resources()` 只清空 `l2_data`、`gc.collect()` 并记录 RSS，且不是所有步骤都保证调用；这可以作为“显式释放并记录”提示，但不能当作资源治理已完成的证据。`ScriptExecutor` 在正常路径关闭 stdout 管道并返回退出码，却没有统一超时、取消令牌、进程组、临时文件和崩溃回收契约。

## 4. 句柄、租约和资源生命周期补充

### 4.1 平台统一句柄/租约契约（Second-Me 未完整实现，作为底座缺口）

所有可能跨线程、跨请求、跨进程或跨 provider 持有的对象都不得以 Python 对象、PID、路径或 URL 单独代表。统一句柄至少包含：

```text
handle_id / kind / owner / scope / generation
created_at / deadline / last_heartbeat
state(open|closing|closed|expired|orphaned)
provider_id / underlying_ref(受控、不对外泄漏)
cancel_token / release_policy / cleanup_evidence
```

租约用于“允许某个任务在一段时间内持有资源”，不是永久锁：创建者取得租约，转移必须记账，持有者按心跳续租；截止时间、宿主崩溃或心跳停止后由 L3 回收器标记 `expired/orphaned`，执行终止、关闭、删除临时物并记录结果。重复 `release` 必须幂等；旧世代句柄不得释放新世代资源；续租不能掩盖已取消任务。

### 4.2 当前源码的资源表

| 资源 | 源码创建/持有 | 已有释放或终态 | 失败/超时/取消/崩溃缺口 | 平台落点 |
|---|---|---|---|---|
| SQLite session/连接池 | `DatabaseSession.session()` 创建 session | 成功 commit，异常 rollback，`finally session.close()`；应用关闭可 `engine.dispose()` | 进程崩溃由数据库自身处理，未见统一租约/锁残留审计 | L1 数据库支持库 + L3 事务/健康治理 |
| 文档/日志文件句柄 | Document/训练服务用 `open()`；`_start_training()` 打开日志 | 训练正常路径 `log_file.close()`；多数读取使用上下文管理器 | 启动异常、daemon 监视器、无限日志流的退出和临时文件清理不统一 | L1 文件流支持库 + L3 句柄回收 |
| 训练子进程及子进程树 | `subprocess.Popen`，保存 `self.process/current_pid`；`ScriptExecutor` 另建 process | `wait()`；`stop_process()` 对当前 PID 的 children 先 terminate，3 秒后 kill | 训练 `Popen` 未设进程组；ScriptExecutor 无 cancel/timeout；宿主崩溃后的孤儿需扫描；不同执行器所有权不统一 | L1 进程 provider + L3 进程组/租约 |
| llama-server | `start_server()` 创建 `Popen` 但未保存到服务对象 | `stop_server()` 按命令行扫描并 kill，0.2 秒等待后可 SIGKILL | 无启动句柄、固定 3/5 秒等待、按名字误杀、失败分支没有统一回收；崩溃后只能重新扫描 | L1 受管模型进程 + L3 instance lease |
| SSE 响应、队列和线程 | `handle_stream_response()` 创建 queue/Event 与两个 daemon thread | `[DONE]`/异常/`GeneratorExit` 设置 event，最后 join 1 秒 | join 超时后线程可能残留；模型迭代器没有统一 close；客户端断开不一定能取消底层推理 | L1 流适配 + L3 流句柄/取消传播 |
| Space 讨论线程 | `SpaceService.start_discussion()` 创建非 daemon thread | 结果写 finished，失败/异常写 interrupted | 没有 thread handle、join、deadline、cancel 或崩溃租约；多次进程重启可能留下不可见讨论 | L2 协作模块 + L3 任务租约 |
| L2 大对象/模型内存 | `l2_data` 缓存、GraphRAG/训练对象、模型/GPU 依赖 | 部分路径 `_cleanup_resources()` 清空并 `gc.collect()`；旧细探记录 `_release_ollama_models()` | 并非所有异常/取消/进程崩溃路径都覆盖；GPU/外部模型释放证据不足 | L1 模型/内存 provider + L3 资源配额/回收 |
| Chroma collection/向量 | `EmbeddingService`/`chroma_utils.py` 持久化 collection | 维度不匹配时重建 | 重建可能清空旧向量；没有迁移租约、备份指针、双写校验和回滚证据 | L1 向量 provider + L3 迁移任务 |
| 目录、模型制品、临时输出 | `_get_model_paths()`/`_prepare_l2_data()` `makedirs` 并写制品 | 成功后以文件存在作为检查；没有统一制品登记 | 失败可能留下半成品，重跑可能复用不完整目录；缺少内容摘要和原子激活 | L1 制品存储 + L3 制品事务/垃圾回收 |

### 4.3 四种终态要求

每个 L2 流程和 L3 任务都必须记录以下四种终态，而不是只记录“函数返回 bool”：

1. **正常完成**：输出制品通过结构/摘要校验，句柄关闭，租约释放，日志和退出码入账；
2. **业务失败**：保留输入和错误分类，隔离部分输出，释放全部资源，标记可否重试；
3. **主动取消/超时**：先传播 cancel token，再终止进程组/流/线程，等待有界时间，记录 `cancelled` 或 `timed_out`，禁止伪装成 `failed`；
4. **宿主/子进程崩溃**：启动时扫描未完成租约，按 generation/heartbeat 判孤儿，清理残留，进度转 `orphaned/recoverable`，从最后经校验的制品继续，而不是只看“最后成功步骤”。

## 5. 失败、超时、取消和崩溃矩阵

| 场景 | Second-Me 现有行为 | 可复用点 | 必须在平台补齐 |
|---|---|---|---|
| 非法输入/空输入 | API 缺参数返回错误；检索校验 query/limit；短文本可降级；Space 空内容替换为不可访问文本 | 入口校验、优雅降级、错误分类 | 统一错误码、字段路径、不可猜测的 `no_match`/`empty` 结果 |
| provider/LLM 失败 | `EmbeddingError` 包装请求/JSON/结构异常；L0/L1 多处 timeout 与 fallback；部分任务标记 failed | provider 错误转换、单项失败不拖垮批次 | 可重试分类、退避上限、attempt id、原始错误受控保存 |
| 业务步骤失败 | `TrainProcessService` 标记 step `FAILED` 并返回 False；进度 JSON 可从最后成功步骤继续 | 步骤状态机、断点续跑 | 事务化状态、输入/输出指纹、并发租约、部分制品隔离 |
| 远端超时/网络断开 | `share_space()` HTTP timeout=10；upload 有 heartbeat timeout；Space 失败变 interrupted | 外部请求明确 timeout、失败状态 | 所有 provider 必须 deadline；取消传播、重试幂等、连接关闭和结果可回读 |
| 长任务超时 | 训练/日志监视存在无限循环；模型启动固定 sleep；SSE 只对 queue 使用短 timeout | 心跳和短轮询可减少阻塞 | 任务级 deadline、租约过期回收，不能让 daemon thread 无限活着 |
| 主动停止 | `/stop` 置 `is_stopped`，尝试终止 children，等待最多 3 秒；路由轮询 suspended/failed | 取消意图、子进程先终止后 kill、状态回读 | cancel token 贯穿模块/provider；主进程、线程、迭代器、临时文件全部收口；路由不能无限等待 |
| 客户端断流 | SSE 捕获 `GeneratorExit` 并设置完成事件，线程 join 1 秒 | 断流可观测、结束标记 | 将断流绑定任务取消/模型请求关闭，并确认无残留线程/连接 |
| 宿主崩溃/重启 | `TrainProgressHolder` 将遗留 `in_progress` 改为 `failed`；Space 线程无恢复记录 | 启动时识别未完成状态 | 租约+心跳+generation、孤儿扫描、恢复/放弃策略、残留 PID/端口/文件验证 |
| 重复启动/并发 | `/start` 检查已有 in_progress 返回 409；singleton 按 model name 复用状态 | 显式冲突而非静默排队 | 以任务租约和唯一幂等键替代进程内 singleton；跨进程仍需原子占用 |
| 输出损坏/部分写入 | 多处只检查文件是否存在；GGUF/merged model 用存在性检查 | 输出存在性是最低门槛 | 临时文件→fsync→原子 rename→摘要/结构校验→激活指针；失败制品隔离 |
| 资源二次释放 | 数据库 session close 在 finally；流 event 可重复 set | 局部释放幂等 | 所有 handle 的 `release` 必须幂等并记录首次/重复释放，不可依赖 GC |

## 6. 后续裁决：命中、缺口、复用与隔离

### 6.1 现有能力命中表

| 能力 | 现有源码命中 | 目标权威 owner | 决策 |
|---|---|---|---|
| 统一数据库事务上下文 | `DatabaseSession.session()` | L1 数据库支持库 | **复用模式，升级证据** |
| 文件类型发现、解析、切块 | `ProcessorFactory`、各 processor、`DocumentChunker` | L1 文档摄取支持库 | **复用边界，不复制实现** |
| embedding/向量查询 | `EmbeddingService`、`LLMClient`、Chroma 工具 | L1 embedding/向量 provider | **升级 provider 隔离、指纹和迁移** |
| L0 单对象派生抽取 | `L0Generator` | L1 结构化抽取支持库 + L2 摄取后处理模块 | **吸收原子契约，废弃产品提示词语义** |
| L1 版本化身份投影 | `L1Generator`、`L1Version`、`L1Bio`/`L1Shade` | L1 身份版本/声明支持库 + L2 身份重建模块 | **吸收版本和双投影，补证据状态** |
| 检索轨道组合 | `L0KnowledgeRetriever`、`L1KnowledgeRetriever`、strategy chain | L1 检索/重排支持库 + L2 上下文模块 | **吸收双轨和预算，升级意图/冲突/来源** |
| 本地模型进程 | `LocalLLMService` | L1 受管模型 provider + L3 进程资源治理 | **隔离，不直接复用进程扫描** |
| 步骤状态与断点 | `ProcessStep`、`TrainProgressHolder` | L0 任务契约 + L3 任务恢复器 | **吸收状态机，升级租约/指纹/并发** |
| 脚本/子进程执行 | `ScriptExecutor`、`Popen` | L1 进程执行支持库 + L3 任务执行器 | **隔离并重写资源契约** |
| HTTP/MCP/SSE 对外 | Flask routes、MCP、SSE | L1 transport + L4 统一网关 | **吸收协议适配，不吸收 handler 编排** |
| Space 多方讨论 | `SpaceService`、`DiscussionService`、context manager | L2 协作编排模块 + L3 远端调用租约 | **仅吸收轮次/增量上下文；外部 endpoint 受管** |

### 6.2 缺口表

- 缺少跨请求/跨进程的统一 `task_id/run_id`、资源 `handle_id` 和租约模型；
- 缺少任务输入/输出/模型/embedding/provider 的完整指纹与不可变制品登记；
- 缺少进程组、线程、流迭代器、端口、临时目录的统一回收器和残留验证；
- 缺少 timeout/cancel/crash 的统一传播协议，现有 timeout 分散在 LLM、HTTP、heartbeat 和 wait；
- 缺少状态快照与身份版本的统一证据来源、冲突/撤回/过期状态；
- 缺少索引重建前的备份/双写/校验/原子切换，Chroma 维度变化有静默数据损失风险；
- 缺少网关到任务的异步命令协议，当前路由直接创建 daemon thread；
- 缺少跨模块调用审计，singleton、环境变量和全局路径可能造成模型/用户/并发任务串扰；
- 未有当前核对真实运行、第三方 provider、迁移、训练、llama-server、Space 远端协议和资源清场验证。

### 6.3 复用/升级/新建/废弃总裁决

- **复用**：数据库事务上下文、统一结果/错误的方向、解析→规范化→切块→embedding 的边界、L1 版本父子表、检索分轨和进度状态机的抽象。
- **升级**：身份声明必须带证据/状态/版本；向量必须带 embedding 指纹；任务必须带 run/lease/heartbeat；模型和脚本必须由受管 provider 执行；制品必须原子提交并可回滚；SSE/MCP 必须传播取消。
- **新建**：句柄/租约注册表、任务执行器、进程组回收器、流关闭器、制品登记器、索引迁移器、残留资源审计器、跨轨检索意图/冲突检测能力。
- **废弃/隔离**：按进程名全局 kill、只用 singleton 与 model name 识别任务、无截止时间的 daemon thread/日志循环、StatusBiography 删除旧行、运行时改写共享 GraphRAG 配置、仅凭文件存在判断模型制品完成。
- **待核**：`Space` 远端 endpoint 的认证/重试/幂等、GraphRAG 并发互斥、真实停止训练时主/子进程关系、模型/GPU释放效果、Chroma 重建的数据保留策略；这些没有运行证据，不进入正式底座实现。

## 7. 依赖与资源契约（装配前置）

若未来把上述能力装配进平台，必须先有能力搜索、复用决策和独立工作包，不能直接把 Second-Me 依赖加入平台主进程：

1. `PyMuPDF/pdfplumber/pytesseract/LangChain` 归文档 provider；`ChromaDB/sentence-transformers/numpy/scikit-learn` 归 embedding/向量 provider；`OpenAI SDK/requests/aiohttp` 归模型/HTTP provider；`llama.cpp/MLX/Transformers/TRL/GraphRAG` 归受管模型/训练 provider；
2. 原生扩展、GPU、训练框架和 GraphRAG 必须在 L1 适配层或独立受管执行单元，正式业务和 L2 模块不得导入第三方实现；
3. 每个 provider 必须声明输入上限、并发上限、超时、取消、重试、句柄类型、租约策略、释放动作、崩溃恢复和验证场景；
4. L2 模块只保存能力 id、契约版本和业务参数，不保存 provider 对象、连接、线程、PID、Chroma collection 或模型路径的隐式全局状态；
5. L3 装配时为每个任务预留 CPU/GPU/内存/磁盘/端口/临时目录/模型上下文预算，超过预算返回明确背压错误，不无限排队；
6. L4 只接收可序列化 DTO/事件，返回 `task_id`、`run_id`、状态查询和取消结果，不把 ORM、Pydantic、OpenAI 或 subprocess 对象穿过网关。

## 8. 验收契约与后续装配计划

当前核对只交付研究映射，不启动平台生产改造。未来任何装配工作必须按下列顺序形成独立工作包：

1. **契约编译**：先定义 L0 的身份/状态/记忆/摄取/检索/模型/任务/句柄/租约/制品字段和错误码；
2. **能力搜索与复用决策**：逐项搜索现有支持库，写明复用、升级、新建或废弃，禁止凭项目名称新增重复能力；
3. **provider 隔离**：为文档、embedding、向量、LLM、进程、HTTP、训练分别定义 provider 适配和受管执行单元；
4. **模块装配**：先做“来源到可检索记忆”“身份版本重建”“检索上下文组装”三个最小模块，训练和 Space 作为后续可选模块；
5. **L3 资源/任务门禁**：加入租约、心跳、取消、超时、崩溃恢复、进程组和残留扫描；所有 handle 的正常/失败/取消/崩溃释放都要有证据；
6. **L4 网关验收**：HTTP/MCP/SSE 只走统一调用器，验证鉴权、幂等、背压、断流取消和错误转换；
7. **真假验证表**：分别记录源码存在、测试存在、静态检查、当前核对真实执行、外部 provider 实测；零测试、跳过、历史日志和子代理回信不能算通过。

建议的最小验收场景：空输入/非法路径/重复摄取；embedding 维度变更；provider 超时/断开；任务重复启动；任务主动取消；子进程非零退出；宿主重启后孤儿租约回收；客户端断开 SSE；部分制品残留；重复 `release`；索引迁移回滚；身份声明撤回后不再进入稳定上下文。每个场景都必须读回状态、句柄、进程、端口、文件、临时目录和制品指针。

**当前核对结论**：Second-Me 最值得进入通用底座的不是“个人 AI self”产品语义，也不是重量训练链，而是“原文到派生记忆的分段边界、版本化身份投影、分轨检索与上下文预算、步骤状态机、受管进程边界和显式资源清理要求”。这些模式只有在 L0 契约、L1 原子能力、L2 组合模块、L3 生命周期治理、L4 统一网关五层各归其位后，才可复用；当前缺失的句柄/租约/崩溃回收能力仍是**待底座实现和真实验证**，不能宣称已从 Second-Me 直接得到。
 # Second-Me 架构取证

## 9. 源码证据索引与增量维护规则

为避免后续调研重复遍历整个仓库，本节固定记录“先读哪里、验证什么、结论能到哪一级”。行号以本次审计 checkout 为准；源码提交变化后必须重新运行代码地图同步并更新行号。

| 关注问题 | 首选入口（源码） | 需要联读的实现 | 当前可下结论 |
|---|---|---|---|
| HTTP 应用如何启动 | `lpm_kernel/app.py`、`lpm_kernel/api/__init__.py` | 各 domain `routes.py`、`api/common/response.py` | Flask app 与蓝图注册链存在（L0/L1） |
| 文档如何变成记忆 | `file_data/process_factory.py`、`document_service.py`、`chunker.py` | processors、`embedding_service.py`、`chroma_utils.py` | 解析→切块→embedding→向量写入顺序可读（L1） |
| L0/L1 如何生成 | `L0/l0_generator.py`、`kernel/l1/l1_manager.py` | `L1/l1_generator.py`、topics/shade/status 生成器 | 两级派生及版本对象存在；一致性仍待运行验证 |
| L2 训练如何编排 | `L2/l2_generator.py`、`L2/train.py`、`api/domains/trainprocess` | data_pipeline、merge、GGUF、MLX 分支 | 步骤状态和制品路径可定位；取消/恢复不闭环 |
| 模型服务如何接入 | `api/domains/kernel2`、`api/services/local_llm_service.py` | SSE handler、OpenAI client、llama-server 脚本 | 本地/外部模型适配存在；进程 owner 与关闭需补证据 |
| MCP/Space 对外边界 | `mcp/mcp_local.py`、`mcp/mcp_public.py`、`api/domains/space` | DTO、repository、discussion strategies | transport 与协作流程可定位；远端认证/幂等待核 |
| 持久化与迁移 | `common/repository/database_session.py`、`models/`、`database/` | BaseRepository、vector repository、migration scripts | SQLite/Chroma 双存储事实成立；跨存储事务不成立 |

### 9.1 每次增量审计的固定步骤

1. 读取远程分支与当前提交，记录 `git rev-parse HEAD`、远程地址和工作树状态；源码 checkout 只读。
2. 若存在 `.codegraph/`，先执行 `codegraph status`，再对“入口 + 状态 + 资源 owner”组合查询；索引不可用时改用 `rg --files` 与定向源码读取，并在文档中标明。
3. 先复核本节入口表，再读取受影响符号上下游各一跳；不得只依据 README、历史细探或测试文件名推断实现。
4. 任何“持久化、幂等、恢复、实时、事务”措辞必须同时给出源码路径和运行证据；只有源码存在时写 L0/L1，未运行不得写 L2-L4 通过。
5. 将新增结论写回本文件对应章节；禁止新增同项目第二份架构摘要。
6. 文档变更后执行 `git diff --check`、行号/路径存在性扫描，并把未执行的 provider、数据库、压力、强杀和发布验证列入剩余风险。

### 9.2 本次审计边界

本次只修改平台侧本文件；未修改 Second-Me 源码、依赖、配置、测试或 README，未安装重量训练依赖，未启动 Flask、Next.js、Chroma、llama-server、MCP 或 Space 远端。文中所有运行相关内容均明确标记为待验证，后续代理可直接从上表入口继续，不需要重新扫描目录。

## 10. 2026-08-22 增量复核

- 本地与 `origin/HEAD` 均为 `d0e40251d9de61b3340b8d0d7d83150669f1885a`，经 `http://127.0.0.1:4780` 复核无版本漂移；未覆盖未跟踪 `ARCHITECTURE.md` 与 `.codegraph/`。
- `codegraph status`：357 files、4,663 nodes；查询 `DocumentService L1Generator ChatService` 成功，定位 `document_service.py:24`、`chat_service.py:24` 及调用方。
- L0/L1 已复核；L2 测试源码存在但本轮未运行；L3/L4 真实模型、数据库、网络、训练和故障恢复均未验证。
- 仅使用 shell/git/codegraph CLI，未调用任何 MCP；本轮只修改平台侧本文件。
