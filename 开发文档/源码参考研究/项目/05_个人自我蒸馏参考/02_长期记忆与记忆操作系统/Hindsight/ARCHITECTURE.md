# Hindsight 全项目架构事实文档

> 研究对象：`vectorize-io/hindsight`；本文件是当前源码快照的唯一架构索引。
> 版本证据：本地 `HEAD=b81a3742b570d0352b8546186dfb77df23cd5fd5`；`origin/main=6ff6dc692ea588067aa5e7235e80640c6a842ba6`（2026-08-21 17:28:11 +0200），远程领先本地 1 个提交；本轮保留未跟踪文档与 `.codegraph/`，未 pull/merge 覆盖工作树。
> 证据规则：源码行号是首要证据；README/开发文档解释公开契约；未运行服务的结论标为未现场验证。

## 总体运行流程

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Python/TypeScript/Go/Rust SDK │ Rust CLI │ MCP │ 控制面 │ hindsight-embed │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ HTTP / MCP / 本地 daemon 转发
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ hindsight_api.main.main                                                     │
│ CLI/环境解析 → HindsightConfig → 数据库/模型初始化 → MemoryEngine           │
│ → api.http.create_app → FastAPI；可启动同进程 worker                       │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               ▼
┌──────────────────────────────┴─────────────────────────────────────────────┐
│ RequestContext → bank/schema/tenant → OperationPrecheck → MemoryEngine      │
└──────────────┬────────────────────┬────────────────────┬───────────────────┘
               ▼                    ▼                    ▼
        retain（写入）        recall（检索）         reflect（推理）
               │                    │                    │
  chunk→LLM抽取→实体解析→   query分析→向量/BM25→   mental model→observation→
  embedding→facts/links→     时序/图→融合/rerank    recall/工具循环→LLM
  memory_units 事务写入      trace/结果              response/trace
               └─────────────────┬────────────────────┘
                                 ▼
                   async_operations + WorkerPoller
                   FOR UPDATE SKIP LOCKED → stage handler
                                 ▼
         PostgreSQL │ Oracle │ pg0；maintenance/retry/cancel/webhook
         memory_units │ links │ entities │ documents/chunks │ models
```

## 1. 项目定位与版本

1. Hindsight 是面向 Agent 的长期记忆服务，不是单纯聊天历史 RAG。
2. 三个核心操作是 retain、recall、reflect；README Quick Start 展示同一公开顺序。
3. `world` 是关于世界/人物/事物的事实。
4. `experience` 是对话、行为、任务和经历事实。
5. `observation` 是跨事实巩固后的派生知识。
6. `mental model` 是用户定义问题对应的可刷新长期摘要。
7. `memory bank` 是记忆租户和配置隔离边界。
8. 核心 Python 实现在 `hindsight-api-slim/hindsight_api`。
9. `hindsight-api` 是带全量依赖的发行包装，entry point 在 `hindsight-api/pyproject.toml:20-21`。
10. `hindsight-all` 组合 API、pg0 和嵌入式 Server/Client。
11. API 支持外部 PostgreSQL、Oracle 与嵌入式 pg0。
12. MCP、控制面、SDK、CLI 最终都调用同一个 MemoryEngine。
13. 当前静态审计源码快照为 `HEAD=b81a3742b570d0352b8546186dfb77df23cd5fd5`。
14. `origin/main` 当前为 `6ff6dc692ea588067aa5e7235e80640c6a842ba6`，远程领先本地；源码通过配置的 `http://127.0.0.1:4780` 中转 fetch，未覆盖本地未跟踪文档。
15. 提交时间为 `2026-08-21T15:48:11+02:00`，主题是把 Claude Code provider 的内容策略拒绝标记为永久失败。
16. 工作树原有 `.codegraph/`；当前静态审计使用本地 `codegraph explore`，未用 MCP。
17. 全树约 4201 文件、581 目录；统计含图片、锁文件和前端资源。
18. 未启动数据库或服务，因此运行时结论来自源码/测试证据。

## 2. 顶层目录地图

| 目录 | 职责 | 证据 |
|---|---|---|
| `hindsight-api-slim` | API、engine、worker、迁移 | `hindsight-api-slim/hindsight_api/` |
| `hindsight-api` | 全量发行包 | `hindsight-api/pyproject.toml` |
| `hindsight-all` | API + pg0 + embedded | `hindsight-all/hindsight/embedded.py` |
| `hindsight-all-slim` | 轻量发行包 | `hindsight-all-slim/pyproject.toml` |
| `hindsight-embed` | profile、daemon、控制中心 | `hindsight-embed/hindsight_embed/` |
| `hindsight-clients` | Python/TS/Go/Rust SDK | `hindsight-clients/` |
| `hindsight-cli` | Rust CLI | `hindsight-cli/src/main.rs` |
| `hindsight-control-plane` | Next.js UI 与 route handlers | `hindsight-control-plane/src/app/` |
| `hindsight-integrations` | Agent 框架适配器 | `hindsight-integrations/*` |
| `hindsight-docs` | Docusaurus/公开文档 | `hindsight-docs/docs/developer/` |
| `docker` | compose、standalone、代理和模型 | `docker/` |
| `helm` | API/worker 部署模板 | `helm/hindsight/templates/` |
| `scripts` | 开发、发布、迁移、测试 | `scripts/` |
| `hindsight-dev` | OpenAPI、benchmark、开发检查 | `hindsight-dev/hindsight_dev/` |
| `hindsight-integration-tests` | 跨包集成测试 | `hindsight-integration-tests/` |

## 3. 启动与应用生命周期

1. `hindsight_api.main:main` 是 API console entry point。
2. `main.py:147-230` 解析 host、port、workers 和环境覆盖。
3. `main.py:92-111` 定义 cleanup 与 signal handler。
4. 启动先加载 dotenv，再读取 `get_config()` 静态配置代理。
5. 数据库 URL 可使用 `pg0://`，也可使用 PostgreSQL/Oracle URL。
6. `api.http.create_app` 位于 `http.py:3792`。
7. `create_app` 在 `http.py:3955` 构造 FastAPI。
8. extension router 在约 `http.py:4101` 注册。
9. app.state 保存 memory、配置、连接池和生命周期对象。
10. `/health/live` 位于 `http.py:4317-4334`，只检查进程/event loop。
11. `/health/ready` 位于 `http.py:4300-4315`，检查数据库可用性。
12. `/version` 位于 `http.py:4336-4373`，返回版本和 feature flags。
13. `/metrics` 位于 `http.py:4376-4388`，返回 Prometheus 格式。
14. API 默认可以启动内置 worker。
15. `hindsight_api.worker.main:main` 是独立 worker entry point。
16. Helm 启用 dedicated worker 时关闭 API 内部 worker。
17. `daemon.py:35-109` 处理后台进程、stdio 重定向和 idle timeout。
18. `hindsight-embed` 管理 profile、daemon PID、端口、日志和 UI。
19. `hindsight-all/embedded.py` 以上下文管理器返回临时服务 URL。
20. 正常退出需关闭 poller、维护循环、连接池和模型客户端。
21. 崩溃后的 processing operation 由启动恢复扫描重新判断。

## 4. API 路由与调用边界

1. 核心路由全部在 `api/http.py` 的 `create_app` 内声明。
2. 路由前缀主要为 `/v1/default/banks/{bank_id}`。
3. `POST /memories` 触发 retain，可 async 返回 operation_id。
4. `POST /memories/recall` 在 `http.py:4710-4729` 声明。
5. `POST /reflect` 在约 `http.py:4916` 声明。
6. dry-run-extract 只抽取预览，不解析实体、不建链接、不持久化。
7. memories/list 支持类型、文本、状态、文档、实体、标签和分页。
8. memories/{id} 支持读取、事实编辑、invalidate、revert。
9. memories/{id}/history 返回 observation 历史和来源事实。
10. graph 返回节点、链接、实体以及类型/标签/文档过滤。
11. entities 提供实体列表、图、详情和重新生成观察。
12. mental-models 提供 CRUD、refresh、clear 和 dry-run-refresh。
13. knowledge-base 提供 tree、folder、page、search、export 和 node。
14. directives 提供 reflect 指令 CRUD，按标签 scope 生效。
15. documents/chunks 支持上传、重处理、分页和文本保存。
16. operations 提供 list、get、retry、cancel/delete 和 result metadata。
17. document-transfer 通过异步 operation 导入/导出 ZIP。
18. files/download 从受控 storage key 下载归档。
19. observations 提供清除、scope 查询和 consolidation recover。
20. config 提供 bank 级 retain、recall、observation、LLM 配置。
21. webhooks 提供订阅、delivery、签名和重试管理。
22. audit-logs 与 llm-requests 提供审计、延迟、token 统计。
23. handler 获取 RequestContext 后执行 OperationPrecheck 与租户检查。
24. Pydantic response model 统一可选字段和错误响应。
25. SDK 是 OpenAPI 低级层加 wrapper，不应复制 engine 业务逻辑。

## 5. MemoryEngine 与数据库抽象

1. `MemoryEngine` 定义在 `engine/memory_engine.py:1705`。
2. 它实现 `MemoryEngineInterface`，编排写入、检索、反思、管理和迁移辅助。
3. `engine/schema.py:11-47` 将逻辑表名绑定当前 schema。
4. bank attribution 将 bank_id、schema、tenant 与 request context 绑定。
5. `engine/db/base.py` 抽象连接、事务、结果和预算。
6. `engine/db/postgresql.py` 管理 asyncpg 连接池与 PostgreSQL 特性。
7. `engine/db/oracle.py` 管理 Oracle 连接与兼容路径。
8. `ops_postgresql.py` 与 `ops_oracle.py` 封装差异 SQL。
9. migrations/Alembic 负责 schema 创建、版本升级和维护 routine。
10. `engine/memories/postgres.py:40` 的 `PostgresMemories` 使用 `memory_units`。
11. memory links 由 `memory_links` 保存，实体关联由 `unit_entities` 保存。
12. `pg/reads.py`、`writes.py`、`graph.py`、`curation.py` 分拆 SQL 职责。
13. `engine/task_backend.py` 抽象 operation 提交、查询、重试和取消。
14. `operation_metadata.py` 将任务结果变为可查询摘要。
15. `engine/storage` 抽象数据库、S3、GCS、Azure 文件存储。
16. `engine/transfer/export.py` 与 `importer.py` 处理银行数据迁移。
17. 外部 provider 不应被 retain/recall 直接导入，必须通过 adapter。
18. MemoryEngine 是流程编排模块，不是单一 DAO 或原子支持库。

## 6. retain 全链路

1. `RetainRequest` 位于 `http.py:761` 附近，包含 content/context/timestamp/tags。
2. handler 先检查 bank 配置、输入大小、memory defense 和 feature 门禁。
3. retain async 方法位于 `memory_engine.py:4626-4673`。
4. 同步 retain 只是等待相同 operation/orchestrator。
5. `retain/orchestrator.py:362-395` 组装内容、文档和标签参数。
6. chunking 将长文本、JSONL 和对话切成可处理单元。
7. `fact_extraction` 调 LLM 输出 world/experience 候选事实。
8. `prompt_utils`、`llm_interface` 负责提示、预算和结构化输出。
9. `entity_processing` 识别实体，`entity_resolver` 归一化实体。
10. `embedding_processing` 批量生成事实向量。
11. `link_creation`/`link_utils` 生成语义、因果和实体边。
12. `_insert_facts_and_links` 位于 `orchestrator.py:514-557`，事务内写入。
13. memory_units 行含 fact_type、text、context、事件时间、tags、embedding、来源。
14. documents/chunks 保存文档元数据、分片和 hash。
15. store_document_text 决定正文进入数据库或外部 storage。
16. 重复 document 使用 content hash 和 delta chunk 路径保持幂等。
17. `_ChunkDiff` 位于 `orchestrator.py:3140`，区分 unchanged/changed/removed。
18. changed/removed chunk 的旧事实和链接会被删除或重算。
19. 完成后 operation 写入 result metadata，并可提交 consolidation 子任务。
20. `enable_observations=false` 时只保留源事实。
21. memory defense 可阻断敏感、提示注入或秘密内容并记录审计。
22. 临时 LLM/embedding 错误可重试，确定性维度/完整性错误不重试。
23. 客户端断开不等于 operation cancel；已入队工作仍可继续。
24. retain 的真实持久化边界是 DB transaction commit，不是 HTTP 返回时间。

## 7. observation consolidation

1. `engine/consolidation/consolidator.py` 选择 source memory_units。
2. 选择受 observations mission、tags、scope、数量和 token budget 控制。
3. LLM 生成去重且可追溯的 observation。
4. observation 仍作为 memory_units 行保存，fact_type 为 observation。
5. 来源通过 observation_sources/source_memory_ids 关联原始事实。
6. consolidation_state、consolidated_at 和 watermark 表示处理/新鲜度。
7. 新事实到达后旧 observation 可 stale，而不是立即删除。
8. reflect 检测 stale 后会降级验证，避免信任过期摘要。
9. observation history 保存文本、证据和版本变化。
10. consolidation operation 结果处理在 `memory_engine.py:2321-2394`。
11. `/consolidate` 可按 bank/scope/tags 手动触发。
12. `/consolidation/recover` 处理失败或中断后的孤儿状态。
13. maintenance 清理孤儿 observations、失效 links、过期 operations 和图队列。
14. PostgreSQL routine 使用 bounded batch 和 skip-locked schema 扫描。
15. Oracle 的维护/retention 语义需结合其 migration 分支核对。
16. observation 是派生事实，不能等价替代原始 world/experience 证据。

## 8. recall 检索全链路

1. request 在 `http.py:4710` 接收 query、types、tags、时间窗口和 include。
2. query token 先受 recall_max_query_tokens 限制。
3. query_analyzer 可抽取实体、时间表达式和检索策略。
4. temporal_extraction/periods 解析显式与相对时间。
5. `search/retrieval.py:123-413` 实现 semantic + BM25 SQL。
6. 向量臂按 embedding 距离检索并过滤 bank/type/tag。
7. BM25 臂使用 PostgreSQL text search/pg_search 词法检索。
8. fusion.py 合并语义和词法结果。
9. link_expansion_retrieval.py 沿 memory_links 扩展关联事实。
10. graph_retrieval.py 通过实体/图边进行 spreading activation。
11. `temporal_combined_sql` 位于 `retrieval.py:418-797`。
12. `retrieve_all_fact_types_parallel` 并行处理多 fact_type。
13. reranking.py 可用 cross encoder 重新排序候选。
14. recall_boost.py 处理新鲜度、重要性、类型和策略加权。
15. tags.py 支持 any/all/exact 与 strict 过滤。
16. include 控制 observations、entities、chunks、source facts 和 token 上限。
17. trace/tracer 记录每个检索臂、候选数、分数和成本。
18. RecallResponse 返回 text、fact_type、scores、来源和实体。
19. recall 不调用生成式 LLM；none provider 仍可用 embedding/词法检索。
20. recall 是只读业务，但仍受租户和操作门禁保护。
21. 当前提交允许调用者直接提供 temporal window，不必依赖自动解析。

## 9. reflect agent 全链路

1. reflect 接收 query、context、budget、tags、response_schema 和 include。
2. `MemoryEngine.reflect_async` 位于 `memory_engine.py:12014` 附近。
3. `reflect/agent.py:372` 的 `run_reflect_agent` 建立工具回调。
4. 内层循环从 `agent.py:429` 开始。
5. 第一层工具是 search_mental_models，优先读取预计算摘要。
6. fresh 且覆盖 query 的 mental model 可以短路后续检索。
7. 第二层工具是 search_observations，读取巩固知识和 freshness。
8. 第三层工具是 recall，回到 world/experience 原始事实。
9. 工具声明和强制序列在 `agent.py:463-511`、`807-810`。
10. `_execute_tool` 位于约 `agent.py:1409`，校验工具名和参数。
11. 未先搜索就回答会得到强制搜索错误（约 `agent.py:942`）。
12. 工具输出会做 token 压缩、计时和 trace 摘要。
13. LLM 使用 bank mission、directives、disposition 和证据生成回答。
14. disposition traits 调整反思的立场和风格。
15. response_schema 触发 structured output 校验。
16. response 的 based_on 区分事实、observation、mental model。
17. stale mental model 不被无条件信任，agent 向下层检索降级。
18. exclude_mental_models 可关闭第一层，便于调试证据链。
19. reflect 是生成式昂贵流程；mental model 是预计算读取层。
20. context overflow、provider error、tool error、cancel 各有不同失败路径。
21. LiteLLM wrapper 的 reflect 在 `hindsight-integrations/litellm/hindsight_litellm/wrappers.py:301-400`。

## 10. mental model、知识页、指令

1. mental model 定义含 name、source_query、tags、refresh policy、max tokens 和内容。
2. 创建/刷新返回 operation_id，生成在 worker 后台运行。
3. refresh 可手动、cron 或 consolidation 后触发。
4. `mental_model_refresh.py` 计算 scope、watermark、版本和 delta。
5. 每版保存正文、来源查询、证据和 trace。
6. knowledge-base page 是 mental model 的树形组织封装。
7. folder/page/node 只改变组织，不改变事实表。
8. page export/import 搬迁树结构、内容和 model 关联。
9. directive 保存 reflect 行为约束、背景和 tags。
10. 无 tag directive 是全局；有 tag directive 只在匹配 scope 加载。
11. directive 不参与 recall 分数，只影响 reflect prompt。
12. 删除 bank 时 model/page/directive/operation 需按外键和清理策略处理。

## 11. 数据模型和迁移

1. 初始 schema 在 `alembic/versions/5a366d414dce_initial_schema.py`。
2. 迁移链体现 mental_models→observations、版本、标签、图队列和租户演进。
3. `memory_units` 是 world、experience、observation 的统一事实表。
4. `memory_links` 保存语义/因果/关联边。
5. `unit_entities` 连接事实与 entities。
6. `entities` 保存 canonical name、kind、labels、状态和实体观察。
7. documents 保存元数据、hash、retain 参数和处理状态。
8. chunks 保存文档分片、索引、hash 和文本引用。
9. async_operations 保存 type、status、payload、retry、worker 和结果。
10. mental_models 保存定义、内容、版本、scope watermark 和调度。
11. mental model history 保存每次重写和证据。
12. observation_sources/source_memory_ids 提供可追溯证据。
13. directives 保存正文、subtype、tags 和启停状态。
14. audit_logs 保存主体、bank、写操作、结果和错误。
15. llm_requests/trace 保存模型、供应商、token、延迟和 operation。
16. webhooks/deliveries 保存订阅、签名、响应和重试。
17. file_storage 保存可迁移文档归档的外部引用。
18. 导出归档不依赖原 embedding，目标实例需要重新嵌入。
19. extension loader 可为 bank 建立物理表或 schema。
20. PostgreSQL 迁移管理 pgvector/HNSW、pg_trgm、GIN 等索引。
21. Oracle 通过独立 SQL/migration 提供兼容能力。

## 12. 并发、队列、重试与资源

1. 所有异步后台任务共用 async_operations 和 worker pool。
2. `worker/poller.py:5` 明确使用 `FOR UPDATE SKIP LOCKED`。
3. poller 在事务内 claim pending/retryable 行并写 processing/worker_id。
4. SKIP LOCKED 防止重复 claim，但不是完整租约协议。
5. worker 有 slot reservation、task 并发上限、RSS、墙钟 timeout 和 active task。
6. `worker/stage.py:21-56` 保存当前阶段用于指标和日志。
7. poller 按 task_type 选择 retain、consolidate、refresh、transfer handler。
8. 成功写 completed/result_metadata；失败写 failed/error/retry_count。
9. 临时错误按 backoff 重入 pending，确定性错误终止。
10. pending/processing 不会被 operation retention 清理。
11. completed/failed/cancelled 可按 retention days 批量删除。
12. 文档指出 PostgreSQL 维护 retention，Oracle 历史可能不受同样清理。
13. pending 可 cancel；processing 通常不强制杀死。
14. HTTP 断开、超时、cancel 和 worker failure 是不同状态。
15. embedding/LLM 使用 semaphore、batch size 和 token budget 限制资源。
16. 连接池、schema 扫描、文件导出和结果列表都需要 bounded batch。
17. cache affinity/bank stats cache 依赖 TTL/watermark 失效。
18. reflect 有上下文压缩、工具轮数和 token 上限。
19. webhook、文件下载、外部 HTTP provider 具有超时和 URL guard。
20. shutdown 需停止 poller、maintenance、daemon/UI 并释放连接。
21. worker 崩溃后的 processing 恢复依赖 stale worker 扫描。
22. 当前静态审计未做 kill、压力、多进程竞态验证。

## 13. 配置、provider 与安全

1. `config.py:2220` 的 `HindsightConfig` 汇总环境和 bank 覆盖。
2. `config.py:25` 加载 dotenv；`get_config` 在约 `4254` 暴露代理。
3. 环境键统一以 `HINDSIGHT_API_` 开头，解析函数校验类型与枚举。
4. retain 配置包含 mission、extraction mode、chunk、batch、语言和实体标签。
5. observation 配置包含 enable、mission、scope、上限和刷新策略。
6. recall 配置包含 query/result token、boost、decay、reranking。
7. reflect 配置包含 mission、disposition、budget、工具轮次和 schema。
8. worker 配置包含 enabled、slots、retries、timeouts、retention。
9. DB 配置包含 URL、schema、pool、SSL、migration 和 Oracle。
10. `engine/embeddings.py` 支持本地、OpenAI 和兼容 embedding provider。
11. `engine/providers` 包含 Anthropic、Gemini、OpenAI、Codex、Copilot、LiteLLM、Ollama 等。
12. `llm_interface.py` 统一 chat、tool、structured output 和 usage。
13. provider 英文协议和第三方 SDK 应隔离在 adapter。
14. none provider 可使 recall 工作，但不生成 reflect 答案。
15. 多 LLM strategy 在 config member/strategy 中路由 fallback、round-robin 或 budget。
16. RequestContext 绑定 bank/schema/tenant；不能只相信路径 bank_id。
17. operation_validator 执行 feature、租户和资源门禁。
18. SQL schema helper 仅接受白名单表名。
19. memory_defense 可拒绝注入/秘密内容并发 webhook。
20. webhook url_guard 阻止私网、localhost、危险重定向等 SSRF。
21. 文件下载只接受 storage key，不接受任意文件路径。
22. MCP 单 bank URL 推导 bank；真正授权仍由 API precheck。
23. audit decorator 记录 retain、recall、update 等操作。
24. invalidated memory 保留以支持审计和 revert。
25. 错误响应不应泄露密钥、连接串和完整内部栈。

## 14. 部署与客户端

1. Docker standalone 入口是 `docker/standalone/start-all.sh`。
2. compose 支持外部 PostgreSQL、nginx、模型和监控。
3. Helm API Deployment 配置 secret、资源、探针和环境。
4. worker StatefulSet 在 `helm/hindsight/templates/worker-statefulset.yaml:1-120`。
5. worker pod 名可作为稳定 worker id。
6. worker 可挂载模型缓存 PVC。
7. API/worker 镜像默认是 `ghcr.io/vectorize-io/hindsight-api`。
8. PostgreSQL 需准备向量、trigram、全文检索扩展或等价能力。
9. Oracle 需使用 Oracle baseline 和对应 SQL adapter。
10. embed profile 为每个本地实例分离 pg0 数据目录。
11. 多副本 API/worker 必须共享数据库、operation 表和一致配置。
12. Python wrapper 位于 `hindsight-clients/python/hindsight_client/hindsight_client.py`。
13. Python/TS/Go/Rust 低级 SDK 按 OpenAPI 生成。
14. Rust CLI `src/main.rs` 覆盖 bank、memory、document、entity、operation 等命令。
15. fs CLI 管理 daemon/profile/config/health/state/sync。
16. TypeScript embedded 包通过本地 daemon 提供无服务器调用。
17. LiteLLM wrapper 可在每次 LLM 调用前 recall、调用后 retain。
18. integrations 目录是框架薄适配层，不复制 engine。
19. OpenHands、LangGraph、CrewAI、Dify、OpenClaw 等通过 client/HTTP 接入。
20. 适配器应保留 operation_id 和统一错误语义。

## 15. 本次复审核心实现复核

本节补充当前提交中最容易被概览遗漏的跨组件状态转换，所有结论均来自目标仓当前源码，而非平台假设。

### 15.1 retain 的阶段边界和提交见证

1. `MemoryEngine.retain_async`（`hindsight-api-slim/hindsight_api/engine/memory_engine.py:4677-4770`）将单条输入包装成 `retain_batch_async`，因此单条和批量请求共享认证、校验、分块、抽取和持久化路径。
2. `retain_batch_async` 先复制内容供 `RetainContext` 校验；扩展点可以返回替换后的内容，但 bank、租户和请求上下文仍由引擎重新绑定。
3. 文档级输入会按 document_id 分组；同一批不同文档不能假设共享首项的 context、event_date 或 metadata。
4. 大批次按配置拆分为子批；fold 机制可以把同一文档的多个 pending operation 合并执行，但每个原 operation_id 仍必须获得独立终态和结果切片。
5. `retain/orchestrator.py:_pre_resolve_phase1`（约 `425-470`）在写事务外执行实体解析和 semantic ANN，使用占位 unit id；这样避免 LLM/ANN 慢读持有写锁。
6. `_remap_phase1_results`（约 `488-510`）在真实 UUID 生成后重映射实体边和语义边；占位 id 遗留会造成不可见链接，属于完整性错误而非可重试网络错误。
7. `_insert_facts_and_links`（`514-612`）在一个事务中插入 memory_units、unit_entities、semantic/temporal/causal links、文档关联和可选 outbox；检索依赖的数据必须一起提交。
8. 普通 PostgreSQL 路径的 commit 点是数据库事务提交；事务回滚后不应发布 webhook、consolidation 或 operation 成功结果。
9. store-owned retain 路径（约 `660-890`）使用外部 provider 事务、PostgreSQL 本地元数据和 commit witness；先提交 witness，再调用 provider `decide_txn(commit=True)` 发布外部写入。
10. witness 未提交时 recovery sweep 必须将 staged 外部写入 abort；witness 已提交但进程崩溃时则允许恢复为 committed，不能凭 HTTP 返回时间猜测状态。
11. transactional outbox 与写入事务同 commit；webhook 投递是至少一次语义，消费端需要按 operation/event id 幂等。
12. 文件正文关闭存储时只落文档元数据和 hash；后续 expand 不能假设 `chunks.text` 可用，reflect 会据配置关闭 chunk 工具。

### 15.2 fact extraction 的重试分类

1. `engine/retain/fact_extraction.py:1812-1938` 对一个或多个 chunk 执行抽取，批量 provider 错误会按 chunk 收集而不是立即丢弃整个批次。
2. 输出过长时 `_split_chunk_for_output_retry` 将 chunk 拆分后重试；这是输入规模适配，不应与 provider 故障重试混为一谈。
3. quota/rate-limit 错误携带 `retry_at`，worker 可依据最晚时间安排下一次 operation；重试次数由 worker 上限控制。
4. JSON 校验、维度不匹配、不可解析结构等确定性错误不会无限重试；最终必须将失败原因写入 operation error_message。
5. 当前提交把 provider content-policy refusal 显式提升为永久失败类型（提交主题 `fix(retain): treat provider content-policy refusals as permanent`），避免同一被拒 chunk 消耗完整 retry schedule。
6. 永久失败与临时失败都要保留 failed chunk 计数、首个代表错误和 operation trace；父 batch 不能只返回笼统的“子批失败”。
7. fact_type 由模型输出、请求 override 和上下文策略共同决定；world/experience 不是纯展示字段，影响召回臂、consolidation 和权限过滤。
8. narrator 注入只在 profile name 与 bank_id 不同且确认为叙述者时生效；路由键不得污染一人称事实的 who 维度。

### 15.3 recall 的闸门、混合检索与连接重试

1. `MemoryEngine.recall_async`（`memory_engine.py:5850-6200`）先 sanitize query、认证 tenant、校验 operation，再解析 query token、时间窗口、fact types、tags 和预算覆盖。
2. `_search_semaphore` 包围完整 `_search_with_retries`，用于限制并发数据库检索；等待时间会进入 trace，不能误计入 provider 延迟。
3. `_search_with_retries` 对 asyncpg 连接不足、数据库暂不可用及 Oracle connection error 最多重试三次，退避为 0.5、1、2 秒；语义错误和参数错误不走该重试。
4. 每次搜索先并行或分阶段运行 semantic、BM25、temporal、graph/link arms，再由 fusion 和 reranker 合并；关闭某个 arm 是 bank 配置策略，不代表结果为空即可跳过审计。
5. reranker candidate cap 按预算可缩放；预算降低只能减少候选或 token 上限，不能改变 bank、tag 或 tenant 过滤。
6. recall 的 `include_chunks` 受 `store_document_text` 强制约束；正文未存储时返回空 chunk 会被禁止，避免把空上下文误当作证据。
7. `OperationCancelledError` 直接传播到 HTTP 层，不参与连接重试，也不触发“失败后重试”业务钩子。
8. 非连接异常会先调用 `on_recall_complete(success=False)`（若配置 validator），再重新抛出；hook 自身失败只记录 warning，不替代原始错误。
9. 成功同样调用 validator completion hook，结果对象包含 query、budget、fact types、token 上限和最终结果；外部扩展不得修改已落 trace 的原始候选。
10. recall span 在 finally 中关闭；异常路径也必须结束 tracing，避免长生命周期 context 泄漏。

### 15.4 reflect 的工具循环、取消和证据归因

1. `MemoryEngine.reflect_async`（`memory_engine.py:12018-12347`）在任何 LLM 调用前执行 query/context sanitize、provider 非 none 检查、tenant 认证、operation validator 和 cancellation checkpoint。
2. 初始 prompt 不预加载全部 mental models；工具 `search_mental_models_fn` 按 query 生成 embedding 后按 freshness、tag 和排除 id 查询，控制大 bank 的上下文增长。
3. `search_observations_fn` 将 last_consolidated_at、pending_consolidation 和 source fact token budget 传给 observation 搜索，使 stale 摘要可被降级处理。
4. `recall_fn` 的默认 max token 在 reflect 调用时绑定 bank config；mental model trigger 的 override 不会污染后续请求的全局默认值。
5. `expand_fn` 只在需要时 acquire 数据库连接；LLM 慢调用期间不持有连接，降低 pool 枯竭风险。
6. directives 根据 apply_all_directives 和 tags isolation_mode 选择；带标签 directive 不得泄漏到未匹配的 reflect。
7. 反思迭代次数由 `Budget.LOW/MID/HIGH` 乘数计算，另有 max_context_tokens 和 `reflect_wall_timeout` 外层上限。
8. `run_reflect_agent` 接收 `request_context.raise_if_cancelled`，在迭代间和工具阶段协作式取消；它不等同于强杀 provider 进程。
9. `asyncio.wait_for` 超时后抛出 TimeoutError，并记录耗时、迭代数（若可得）和 query 摘要；调用方仍需确保嵌套 LLM/HTTP 客户端可退出。
10. agent_result 只把 done action 验证过的 used_memory_ids/used_observation_ids 纳入 based_on，工具搜索到但未被最终答案采用的候选不应伪造为依据。
11. response_schema 会触发额外 structured extraction；该二次调用增加 provider 成本和超时风险，结果校验失败不能覆盖原始文本。
12. reflect 是只读业务，但会写 trace/metrics；文档、mental model refresh 等外层 operation 可以把 reflect 作为子阶段，必须避免重复 parent span。

### 15.5 worker claim、fold、租约和恢复

1. `worker/poller.py:428-610` 在每个 schema 上调用 backend `claim_tasks`，SQL 使用 `FOR UPDATE SKIP LOCKED`；锁只覆盖 claim 事务，不覆盖整个任务执行期。
2. claim 会按 reserved/shared slot、tenant fairness、task priority 和 retry_at 过滤；扫描不到任务时仍维护 schema rotation，避免一个空租户阻塞其他租户。
3. fold peers 在同一 claim 事务中锁定并标记 processing；`ClaimedTask.all_operation_ids` 明确主 operation 与折叠 operation 必须一起进入终态。
4. fold 执行失败时父/子 operation 的代表错误由 `_summarise_child_error_messages` 选取最常见非空原因，避免监控只看到泛化错误。
5. `mark_operations_processing` 写 worker_id、claimed_at、stage 等字段；这不是持久租约心跳，stale 扫描仍需依据时间和 worker 存活判断。
6. retain 有 `_wall_timeout_for` 外层墙钟限制；超时取消 task 后由 poller 进入 retry/fail 收敛，避免一个锁等待或永不释放的 LLM permit 永久占用 slot。
7. `_schedule_retry` 将 processing 重置 pending、写 next_retry_at、递增 retry_count 并清理 worker/claimed 字段；达到上限才进入 failed。
8. cancel 与 retry 不同：pending 可直接取消，processing 通常只协作式取消并等待短 drain；不能把客户端断线自动等价为数据库 cancel。
9. shutdown 会取消后台任务，最多等待 `_CANCEL_DRAIN_TIMEOUT=5s`，随后 reconcile processing rows；该窗口是终态写入机会，不是无限等待。
10. worker stage 通过 contextvar 绑定到 task 自身；`set_stage` 在 HTTP/CLI 无 holder 时是 no-op，因此静态日志不能证明所有请求都有 stage。
11. poller 支持 RSS、active task、卡住栈转储和 slot 统计；这些是诊断证据，不是资源释放本身。
12. 当前实现没有跨数据库统一的 fencing token；多 worker 部署仍依赖数据库原子 claim、stale 判定和 operation 状态条件更新防止旧 worker 覆盖新终态。

### 15.6 跨组件状态转换表

| 阶段 | 权威状态 | 可重试 | 必须保留的证据 | 禁止的推断 |
|---|---|---|---|---|
| 接收 retain | operation pending | 参数错误不可重试 | payload 摘要、tenant、bank、预算 | HTTP 202 不等于已写入事实 |
| 抽取事实 | processing + stage | quota/连接可重试 | chunk、provider、token、错误类型 | content-policy refusal 可重试 |
| 写入事实 | DB transaction | 事务回滚后整体重试 | commit、unit ids、link 数、outbox | 已生成 UUID 不等于可见 |
| 发布外部存储 | witness/decision | provider 临时错误可按协议重试 | witness、provider txn、decision | 一侧提交不能直接判成功 |
| recall | 只读 operation/span | 连接错误有限重试 | arm、候选、rerank、耗时 | 空结果不等于数据库故障 |
| reflect | agent processing | provider/网络按策略重试 | tool trace、used ids、LLM trace | 搜索到的候选都是依据 |
| worker 终态 | completed/failed/cancelled | retry_at 未到不得重复 claim | worker、retry_count、错误摘要 | processing 永久代表运行中 |

## 16. 本次复审未验证边界

当前复核仍为静态源码和版本复核：未启动 PostgreSQL/Oracle/pg0，未运行多 worker 竞态、kill -9、OOM、provider content-policy 实际拒绝、外部对象存储两阶段提交、连接池耗尽或 reflect 超时注入。以上状态转换是源码设计证据，不是生产环境通过证明。正式接入前应分别验证：

1. retain 事务在数据库断连、进程崩溃和 outbox 重放下是否无半写事实；
2. fold peer、父 operation 和 retry_count 在多 worker 下是否始终一一终态；
3. recall 连接重试不会重复写 trace、重复扣费或绕过取消；
4. reflect 的 nested LLM 调用在 wait_for 超时后确实释放 HTTP 连接和 semaphore；
5. content-policy refusal 不被上层通用 retry wrapper 重新包装为可重试错误；
6. stale worker recovery 不会让旧 worker 的延迟完成覆盖新 worker 的成功或失败；
7. tenant/schema 认证和 operation validator 在 MCP、HTTP、SDK、CLI 四入口保持一致。

## 15. 文档、可观测性与测试

1. `hindsight-docs/docs/developer/retain.mdx` 解释抽取、chunk、实体、链接和观察。
2. `recall.mdx` 解释向量/BM25/图/时序检索和过滤。
3. `reflect.mdx` 解释 mental model、observation、directive 和 disposition。
4. `api/operations.mdx` 解释 async_operations 状态、重试和 retention。
5. OpenAPI 由 `hindsight-dev/generate_openapi.py` 从 FastAPI 生成。
6. client coverage 工具检查 SDK 包装覆盖率。
7. metrics 暴露 API 延迟、worker、操作、LLM token 和错误。
8. llm_trace/llm_requests 提供模型调用审计。
9. audit_logs 提供管理与写入行为回放。
10. `test_ann_iterative_scan.py` 覆盖向量/BM25 组合查询。
11. `test_retain_same_document_concurrency.py` 覆盖同文档并发 retain。
12. `test_memory_defense.py` 覆盖防御、阻断和 payload 隔离。
13. `test_document_transfer.py` 覆盖导出、导入、embedding 重建和 operation。
14. `test_none_llm_provider.py` 覆盖 none provider 下 recall。
15. `test_bank_stats_cache_distributed.py` 覆盖分布式缓存。
16. `hindsight-embed/tests` 覆盖 profile lock、daemon、端口和配置。
17. Python client tests 覆盖参数映射、时间窗口、response parsing。
18. CLI tests 覆盖命令和 profile 集成。
19. 当前静态审计只做静态结构和差异验证，未安装依赖或启动外部服务。
20. 因此不能声称真实 retain/recall/reflect 或压力测试已通过。

## 16. 关键文件行号索引

| 主题 | 文件:行 | 事实 |
|---|---|---|
| API 启动 | `hindsight-api-slim/hindsight_api/main.py:147-348` | CLI 解析、初始化、app |
| 信号清理 | `main.py:92-111` | cleanup/signal |
| FastAPI 工厂 | `api/http.py:3792-4101` | app、状态、router |
| health/version | `api/http.py:4300-4388` | 探针、版本、指标 |
| recall | `api/http.py:4710-4749` | query 校验和检索 |
| retain | `api/http.py:8096-8456` | retain/file retain |
| operations | `api/http.py:6704-6900` | 状态、重试、删除 |
| config | `config.py:2220-2598` | 配置模型 |
| config parse | `config.py:3854-3950` | env 解析 |
| MemoryEngine | `engine/memory_engine.py:1705-1712` | 核心编排 |
| retain async | `memory_engine.py:4626-4673` | operation 提交 |
| reflect async | `memory_engine.py:12014-12240` | agent 组装 |
| refresh | `memory_engine.py:14535-` | model refresh |
| retain orchestrator | `engine/retain/orchestrator.py:362-557` | 参数/插入 |
| delta retain | `orchestrator.py:3140-3775` | chunk diff |
| extraction | `orchestrator.py:1219-1346` | fact/embed |
| retrieval | `engine/search/retrieval.py:123-413` | semantic/BM25 |
| temporal | `retrieval.py:418-797` | 时间/图扩展 |
| reflect loop | `engine/reflect/agent.py:372-511` | agent 工具 |
| reflect tools | `agent.py:807-1100` | 强制检索/freshness |
| worker claim | `worker/poller.py:211-479` | SKIP LOCKED |
| worker state | `worker/poller.py:590-901` | 状态/重试 |
| schema | `engine/schema.py:11-47` | 表名限定 |
| PG adapter | `engine/memories/postgres.py:40-79` | memory/link |
| MCP | `mcp_tools.py:662-1180` | retain/recall/reflect tools |
| daemon | `daemon.py:35-109` | 后台生命周期 |
| worker Helm | `helm/hindsight/templates/worker-statefulset.yaml:1-120` | 部署 |

## 17. 支持库/模块库映射

1. `engine/providers` 是第三方 LLM/embedding/reranker 原子适配支持库。
2. `engine/db`、`engine/storage`、`engine/embeddings` 是资源和协议边界支持库。
3. `engine/retain`、`engine/search`、`engine/reflect`、`engine/consolidation` 是组合流程模块。
4. MemoryEngine 是应用服务/模块编排层，不能归类成一个原子支持库。
5. API、MCP、SDK、CLI 是项目适配层，不应绕过 engine 直接写表。
6. worker、task backend、maintenance 是运行核心的调度/治理层。
7. PostgreSQL、Oracle、向量库、LLM、对象存储是受管外部提供者。
8. 选择原则：原子 I/O、协议转换、资源释放归支持库；跨能力流程归模块库。
9. 新 provider 只在 adapter 注册；新流程通过 interface 和 operation contract。
10. 统一结果应含成功、值、错误码、错误说明、可重试属性。
11. 可复用设计是“单 operation 表 + worker claim + 证据 trace”，不是复制源码。

## 18. 未确认风险与验收记录

1. 已执行 `git pull --ff-only origin main`；源码 checkout 已更新为 `6ff6dc692ea588067aa5e7235e80640c6a842ba6`，保留未跟踪的唯一文档与 `.codegraph/`。
2. `.codegraph` 是本地索引，源码变动后需重建，不能替代源码。
3. 未现场验证 pg0 端口、数据目录和扩展安装。
4. 未现场验证 Oracle 与 PostgreSQL 的观察/operation 完全等价。
5. worker stale processing 恢复阈值需结合生产配置实测。
6. cancel processing 通常不是强杀，调用方必须轮询 operation。
7. consolidation 输出质量、去重阈值和 scope 标签需用真实数据评估。
8. mental model 错误标签可能导致空摘要但 operation 成功。
9. provider fallback 可能产生 schema/tool-call 差异，需逐 provider 回归。
10. storage/webhook/LLM endpoint 的 TLS、SSRF、凭证轮换需部署复核。
11. 控制面 route handler 与 API 的错误翻译可能随版本漂移。
12. 尚未运行 client coverage、压力、断电、kill、failover 和真实 provider 测试。
13. 结构断言：流程图、核心章节、路径行号索引均存在，退出码 0。
14. 文档行数断言：本文件不少于 500 行，退出码 0。
15. 差异检查：`git diff --check -- ARCHITECTURE.md`，退出码 0。
16. 修改范围：仅项目根 `ARCHITECTURE.md`；未改源码、依赖、配置、测试。

## 19. 全量文件族与证据矩阵

1. `engine/retain/__init__.py` 是 retain 模块公开导出边界。
2. `engine/retain/types.py` 定义内容、事实、实体和处理结果类型。
3. `engine/retain/bank_utils.py` 处理 bank 配置和写入前置条件。
4. `engine/retain/chunk_storage.py` 管理 chunk 正文、hash 和文档绑定。
5. `engine/retain/fact_storage.py` 封装 memory_units 的事实写入与统计。
6. `engine/retain/entity_labels.py` 规范化实体标签词汇。
7. `engine/retain/fold.py` 处理折叠事实及父 operation 关系。
8. `engine/retain/link_creation.py` 生成事实间链接。
9. `engine/retain/embedding_utils.py` 处理批量向量和维度检查。
10. `engine/retain/entity_processing.py` 把抽取实体映射到 canonical entity。
11. `engine/retain/fact_extraction.py` 将 LLM 输出解析成受约束事实。
12. `engine/search/types.py` 定义 retrieval candidate、score 和 trace 类型。
13. `engine/search/bm25_term_selection.py` 选择词法查询 term。
14. `engine/search/fusion.py` 融合多路候选并去重。
15. `engine/search/reranking.py` 通过 cross encoder 复排。
16. `engine/search/recall_boost.py` 施加 freshness、importance 和策略 boost。
17. `engine/search/graph_retrieval.py` 读取实体与 memory_links 图结构。
18. `engine/search/link_expansion_retrieval.py` 做二跳或受限 link 扩展。
19. `engine/search/temporal_extraction.py` 解析日期、相对时间和 query_timestamp。
20. `engine/search/tags.py` 统一标签匹配语义，避免 API/SQL 各自实现。
21. `engine/search/trace.py` 和 `tracer.py` 把检索过程变成可审计 trace。
22. `engine/reflect/models.py` 定义 reflect facts、tools、trace 和 response 模型。
23. `engine/reflect/tools.py` 暴露 recall、observations 和 mental models 工具。
24. `engine/reflect/tools_schema.py` 固定工具参数 schema，防止模型随意扩展。
25. `engine/reflect/prompts.py` 保存系统提示、mission 和证据规则。
26. `engine/reflect/observations.py` 把 observation 结果转换为 agent 输入。
27. `engine/reflect/retractions.py` 处理撤回、矛盾和无效事实。
28. `engine/reflect/delta_ops.py` 记录结构化文档增量操作。
29. `engine/reflect/structured_doc.py` 解析受 schema 约束的输出文档。
30. `engine/reflect/tokenization.py` 估算上下文与输出 token。
31. `engine/consolidation/prompts.py` 定义 observation 巩固提示。
32. `engine/consolidation/consolidator.py` 执行候选选择、生成、证据绑定。
33. `engine/providers/mock_llm.py` 为测试提供确定性 LLM。
34. `engine/providers/none_llm.py` 禁用生成但允许只读检索路径。
35. `engine/providers/openai_responses_llm.py` 适配 OpenAI Responses/tool API。
36. `engine/providers/anthropic_llm.py` 适配 Anthropic message/tool API。
37. `engine/providers/gemini_llm.py` 适配 Gemini 内容和缓存。
38. `engine/providers/litellm_llm.py` 适配 LiteLLM 统一网关。
39. `engine/providers/openai_compatible_llm.py` 适配任意 OpenAI-compatible endpoint。
40. `engine/providers/codex_auth.py`、`github_copilot_llm.py` 处理订阅型认证。
41. `engine/providers/llm_debug.py` 提供调试 provider，但不应生产启用。
42. `engine/db_budget.py` 限制数据库查询预算和批量规模。
43. `engine/db_utils.py` 提供事务、结果、时间和 SQL 辅助。
44. `engine/db/optional_routines.py` 管理可选 PostgreSQL 维护 routine。
45. `engine/db/pool_instrumentation.py` 记录连接池使用与等待。
46. `engine/sql/postgresql.py` 生成 PostgreSQL 检索、索引和维护 SQL。
47. `engine/sql/oracle.py` 生成 Oracle 兼容 SQL。
48. `engine/storage/postgresql.py` 将文件归档存入数据库。
49. `engine/storage/s3.py`、`gcs.py`、`azure.py` 对接对象存储。
50. `engine/transfer/schema.py` 定义跨实例导入导出 manifest。
51. `engine/mental_model_refresh.py` 实现刷新、freshness、历史和失败恢复。
52. `engine/graph_maintenance.py` 处理异步图边和实体维护队列。
53. `engine/causal_links.py` 解释和持久化因果关系。
54. `engine/entity_resolver.py` 处理大小写、别名、label 和 canonical entity。
55. `engine/query_analyzer.py` 为 recall/reflect 提供 query 分析。
56. `engine/cross_encoder.py` 选择 reranker provider 与候选预算。
57. `engine/llm_trace.py` 记录每次 LLM 调用的输入摘要和 usage。
58. `engine/multi_llm.py` 处理多成员 provider 策略与故障转移。
59. `engine/maintenance.py` 编排过期 operation、孤儿观察和索引维护。
60. `engine/vector_index_health.py` 检查向量索引、维度和覆盖率。
61. `api/mcp.py` 将 FastAPI 生命周期挂接 MCP transport。
62. `api/mcp_tools.py` 以单 bank/多 bank 两种方式注册 retain、recall、reflect。
63. `api/disconnect.py` 将客户端断开传给可取消的业务协程。
64. `api/passthrough_headers.py` 传递受控 trace、tenant 和认证 header。
65. `api/page_markdown.py` 将 knowledge page 转换为 Markdown 输出。
66. `extensions/loader.py` 发现并加载 bank/tenant 扩展。
67. `extensions/http.py` 提供扩展 HTTP 生命周期和依赖注入。
68. `extensions/memory_defense.py` 为 retain 建立策略钩子。
69. `extensions/operation_validator.py` 在 operation 进入 engine 前拒绝越权。
70. `webhooks/manager.py` 处理签名、队列、重试和 delivery 状态。
71. `webhooks/models.py` 定义 webhook 配置和投递结果。
72. `worker/exceptions.py` 区分可重试、取消、确定性和超时异常。
73. `worker/main.py` 构造独立 worker 的配置、连接和 poller。
74. `worker/poller.py` 是多 worker 竞争 async_operations 的唯一 claim 入口。
75. `hindsight-embed/profile_manager.py` 管理 profile 配置、锁和目录。
76. `hindsight-embed/daemon_client.py` 将 embed CLI 请求转发给 daemon。
77. `hindsight-embed/daemon_embed_manager.py` 管理 API/worker 子进程。
78. `hindsight-embed/control_center/service.py` 提供 profile、provider、日志和 UI 服务。
79. `hindsight-embed/control_center/server.py` 提供本地控制中心 HTTP 服务。
80. `hindsight-embed/control_center/lifecycle.py` 负责控制中心启动、停止和健康。
81. `hindsight-control-plane/src/lib/hindsight-client.ts` 是 UI 到后端的客户端边界。
82. `hindsight-control-plane/src/app/api/banks/[bankId]/route.ts` 是控制面 bank route 示例。
83. 控制面 consolidation、mental-model、operation routes 都转发 API 契约。
84. 控制面不应直接访问 memory_units；所有业务读写必须经过客户端边界。
85. `hindsight-cli/src/api.rs` 是 Rust CLI 的 HTTP 请求边界。
86. `hindsight-cli/src/config.rs` 管理 profile、URL、token 和输出格式。
87. CLI `commands/memory.rs` 对应 retain、recall、reflect 和 curate 命令。
88. CLI `commands/operation.rs` 对应后台任务状态、重试和取消。
89. CLI `commands/document.rs` 对应文档、chunk 和 transfer。
90. CLI `commands/fs/*.rs` 只管理本地 daemon，不直接操作数据库表。
91. SDK 生成模型的变化必须由 OpenAPI 生成流程统一更新。
92. 集成目录的配置只决定 bank、URL、凭证和触发时机。
93. 集成适配器的测试应验证映射和关闭资源，而不是复制 engine 测试。
94. benchmark 目录用于性能/准确度测量，不是生产运行时依赖。
95. `scripts/release.sh` 负责多包版本同步和元数据 pin。
96. `scripts/dev/start-api.sh`、`start-worker.sh` 是本地开发启动包装。
97. docker/helm 仅描述部署，不改变 retain/recall/reflect 的业务语义。
98. 本矩阵用于后续 CodeGraph 定位，具体行为仍须回读当前行号源码。

## 20. 端到端状态与错误矩阵

| 阶段 | 正常状态 | 可观测证据 | 主要失败 |
|---|---|---|---|
| 请求进入 | request_context 已绑定 | audit/precheck | 未授权 bank |
| retain 提交 | operation pending | async_operations 行 | 参数/防御拒绝 |
| worker claim | processing + worker_id | poller 指标 | 并发跳过/超时 |
| 内容分块 | chunks/hash 生成 | document/chunk 记录 | 超长/格式错误 |
| LLM 抽取 | facts 候选 | llm_requests/trace | provider 错误 |
| 实体解析 | canonical entities | entities/unit_entities | 解析失败 |
| 向量生成 | embedding 维度一致 | memory_units.embedding | 维度不匹配 |
| 事实写入 | transaction commit | memory_units/links | FK/完整性错误 |
| consolidation | observation pending/done | observation state | LLM/证据冲突 |
| operation 完成 | completed/result_metadata | operations API | retry/failed |
| recall 查询 | candidate/fused results | recall trace | query 过长 |
| reflect 工具 | mental/obs/fact evidence | reflect trace | 未先检索 |
| reflect 输出 | text/structured output | response model | schema/上下文溢出 |
| webhook | delivery succeeded/retry | deliveries/audit | URL/HTTP 错误 |
| retention | terminal rows 删除 | maintenance metrics | Oracle 未清理 |
| shutdown | pool/tasks closed | liveness 终止 | 强杀遗留 processing |

1. 该矩阵把 HTTP、数据库和 worker 状态分开，避免把一次响应当作全链路完成证据。
2. retain 请求成功只代表 operation 已接受；需要 polling/同步 API 才能确认事实已提交。
3. recall 无结果可能来自 query、tags、时间窗口、scope 或索引状态，不等价于 bank 无知识。
4. reflect 回答必须结合 based_on/trace 判断是否真的检索到证据。
5. operation failed 仍可能保留 payload 和错误 metadata，是否 retry 取决于错误分类。
6. cancelled 只表达取消请求被接受，不表达已回滚已执行的第三方调用。
7. invalidated memory 仍可在历史/审计 API 看到，但不会进入 recall、consolidation 或 graph。
8. stale mental model 可返回诊断界面，但不得在 reflect 中短路为最终答案。
9. 生产验收应逐行对照本矩阵补充真实数据库和服务证据。

## 21. 最新提交带来的失败语义变化

1. `b81a374` 的改动范围是 `llm_interface.py`、`memory_engine.py`、`providers/claude_code_llm.py`、`retain/fact_extraction.py` 和一个专门的回归测试文件。
2. `ProviderContentPolicyError` 在 `engine/llm_interface.py:379-392` 定义，是 `RuntimeError` 子类。
3. 该异常表示上游以内容使用政策（AUP）拒绝请求，而不是连接、限流或临时服务故障。
4. `claude_code_llm.py:74-78` 以 `anthropic.com/legal/aup` 作为窄匹配标记，避免普通错误被误分类。
5. `_result_error` 在 `claude_code_llm.py:81-94` 将带标记的结果映射到永久异常，其余结果仍为 `RuntimeError`。
6. 同一 provider 的普通调用重试环和工具调用重试环都在 `claude_code_llm.py:399-405`、`692-700` 直接重新抛出永久异常。
7. 这两个守卫保证内容拒绝不会消耗 provider 的完整 transport retry budget。
8. `fact_extraction.py:1914-1930` 收集批次中拒绝的 chunk；只要存在一个拒绝就向上抛出永久异常。
9. 该逻辑保持 retain 的全批次失败语义，不会把其他 chunk 的部分结果偷偷提交。
10. `memory_engine.py:1099-1106` 的 `_is_non_retryable_task_error` 将该异常纳入不可重试分类。
11. worker 因此在第一次看到拒绝时将 operation 标记为失败，而不是重新排队整个 retain。
12. 这是一条跨 provider、抽取器、engine、worker 的错误分类链，不能只在 provider 层修补。
13. 回归测试为 `hindsight-api-slim/tests/test_content_policy_refusal_permanent.py`，提交新增约 345 行测试代码。
14. 该变化不改变 API 的 retain 请求形状；它改变的是 operation 的失败次数、重试消耗和最终状态。
15. `ProviderRateLimitResetError` 仍表示可等待的限流恢复时间，不能与内容拒绝混用。
16. 文档读者在排查 retain 失败时应优先查看 operation error metadata 和 provider 错误原文。
17. “失败但没有重试”不等于数据已经部分落库；抽取器明确在事务提交前拒绝整个批次。
18. 最新提交的风险边界是 AUP 文本模式匹配依赖供应商错误格式，新增 provider 仍需定义自己的永久错误分类。

## 22. 当前代码地图与规模证据

1. 根目录 `find` 统计为 4,135 个文件和 556 个目录；统计包含锁文件、图片、生成客户端和测试资源。
2. `hindsight-api-slim/hindsight_api` Python 源码总量为 132,196 行（`wc -l` 汇总）。
3. `codegraph status` 显示索引覆盖 2,409 个文件，解析节点 50,279 个，边 143,171 条。
4. CodeGraph 节点包括 15,096 个 method、10,888 个 function、2,404 个 class、1,657 个 property 和 915 个 type alias。
5. 语言分布包括 Python 1,473、TypeScript 459、Go 205、TSX 110、YAML 61、JavaScript 55 和 Rust 35 个文件。
6. 当前 `.codegraph` 是仓库根目录独立索引；本次源码更新后用 `codegraph sync .` 同步了 5 个变化文件、584 个节点。
7. CodeGraph 只用于定位和调用关系，不能替代对源码当前行号的回读。
8. `hindsight-api-slim` 是事实主干；其它包通过 HTTP、OpenAPI client、daemon 或集成适配器调用它。
9. `hindsight-control-plane` 是前端控制面，不是第二个记忆引擎。
10. `hindsight-docs` 是文档站，不是运行时配置来源。
11. `hindsight-dev` 负责 OpenAPI、覆盖率、基准和开发检查，不能承载生产请求。
12. `hindsight-integration-tests` 验证跨发行包和真实部署边界，不能替代核心单元测试。
13. `hindsight-clients` 目录中的生成代码应从 OpenAPI 重新生成，不应手工修复单个模型。
14. `hindsight-cli` 的 Rust 代码通过 API client 访问服务，不能直接读 PostgreSQL。
15. `hindsight-embed` 通过 profile 和本地 daemon 管理嵌入式运行时，数据目录是部署边界。
16. `helm`、`docker` 和 `scripts` 描述装配与发布，不包含领域状态机的另一份实现。
17. 任何新增能力都应先定位到主干 engine，再检查对应 client、控制面、CLI、文档和集成是否只是适配。

## 23. API 输入模型、路由与输出契约

1. `api/http.py:284-385` 定义 `RecallRequest`，包括 query、fact types、budget、token 上限、tags、时间窗口和 trace 选项。
2. query validator 在 `http.py:371-385` 拒绝空查询并限制输入长度，避免无界检索成本。
3. `http.py:761-812` 定义 `RetainRequest` 与 operation_id 验证；content、context、timestamp 和 tags 在这里进入统一模型。
4. `http.py:963-1050` 定义 `ReflectRequest`，把 response schema、fact types、tags 和上下文交给 reflect agent。
5. `http.py:1062-1138` 定义 reflect facts、directives、mental models、tool calls、LLM calls 和 based-on trace 输出。
6. `http.py:1343-1501` 定义 bank 创建、disposition、mission、background 和配置响应模型。
7. `http.py:1559-1660` 定义 observation scope、memory list、dry-run extract 和 document list 输出。
8. `http.py:2139-2190` 定义 directive、mental model trigger 和列表响应。
9. `http.py:2408-2537` 定义 knowledge tree、folder、page、bundle 和 search 模型。
10. `http.py:3261-3555` 定义 operation progress、operation response、consolidation response 和 version/features 输出。
11. `http.py:3609-3714` 定义 webhook、delivery 和列表模型；签名、状态、响应体和重试信息不会混入记忆事实表。
12. `http.py:3792-4164` 创建 FastAPI、挂载 middleware、tracing、审计和路由注册。
13. `http.py:4626-4749` 的 memory update 与 recall handler 先取请求上下文，再进入 engine。
14. `http.py:4929` 起的 reflect handler 不直接调用 provider，而是委托 `MemoryEngine.reflect_async`。
15. `http.py:5510-5736` 覆盖 mental model 的创建、刷新、dry-run、清除、更新和删除。
16. `http.py:6218-6297` 覆盖 directive 的创建、更新和删除。
17. `http.py:6434-6669` 覆盖 document reprocess、update、delete 与内容存储边界。
18. `http.py:6804-6873` 覆盖 operation cancel、retry 和 delete；这些动作不等价于强杀正在运行的 provider 调用。
19. `http.py:7030-7168` 覆盖 bank 生命周期和 bank template 导入。
20. `http.py:7424-7625` 覆盖文档导入、观察清除、consolidation recover 和单记忆观察清除。
21. `http.py:7692-7971` 覆盖 bank config、consolidation 和 webhook 更新。
22. `http.py:8120-8463` 覆盖 retain、file retain 和 bank memory clear。
23. 路由函数统一包在 `audited` 装饰器下，审计动作名与 HTTP 业务动作保持可查询映射。
24. `run_cancellable_on_disconnect` 在 `http.py:212-243` 把客户端断开传播给可取消协程，但已经提交的后台 operation 仍由 worker 负责。
25. `ExcludeNoneRoute` 在 `http.py:118-138` 处理响应模型的可选字段和历史兼容性。
26. API 的公开稳定边界是 Pydantic 请求/响应模型和 operation 状态，不是内部 SQL 函数名。

## 24. retain 的数据处理细节

1. `retain/types.py:19-382` 定义 RetainContent、ChunkMetadata、ExtractedFact、ProcessedFact、ResolvedEntity、RetainBatch 等类型。
2. `fact_extraction.py:462-504` 定义可验证的事实响应和超长单元拆分。
3. `fact_extraction.py:504-658` 处理普通文本、对话 turns 和 JSONL 的结构化分块。
4. `fact_extraction.py:1068-1316` 根据 bank 配置拼装 mission、entity label、输出 schema 和 provider request body。
5. `fact_extraction.py:1325-1812` 执行 chunk 级 LLM 抽取、JSON 修复、重试和自动拆分。
6. `fact_extraction.py:1812-1977` 汇总批次结果、错误和 token 统计，并在永久失败时阻止静默降级。
7. `orchestrator.py:362-395` 将 API 内容模型转为内部 retain 参数。
8. `orchestrator.py:395-513` 执行 phase 1 的实体预解析和结果重映射。
9. `orchestrator.py:514-617` 在写入前构造事实、实体、因果关系和链接，保证 transaction 组装完整。
10. `orchestrator.py:633-1029` 支持扩展传入的 streaming batch write，避免大文档一次性占满内存。
11. `orchestrator.py:1030-1218` 处理 delta batch write 和文档更新的写入结果。
12. `orchestrator.py:1219-1345` 执行 extract、embed、causal remap 和 processed fact 生成。
13. `orchestrator.py:1346-1989` 执行 retain batch，最后用语义 ANN 检查链接/去重结果。
14. `orchestrator.py:1990-2070` 写入正文到数据库或外部文件存储。
15. `orchestrator.py:2071-3139` 是 streaming retain、外部扩展、父子 operation 和最终聚合。
16. `orchestrator.py:3140-3167` 的 `_ChunkDiff` 根据 index/hash 把 unchanged、changed、removed 分开。
17. `orchestrator.py:3168-3774` 执行 delta retain；只重处理变化 chunk，同时清理受影响的旧事实和观察。
18. `orchestrator.py:3775-3894` 处理 metadata-only 更新，不为仅标签或元数据变化重新调用 LLM。
19. `fact_storage.py:45-166` 封装文档记忆统计、事实批写、索引和 bank 存在性检查。
20. `fact_storage.py:168-337` 清理 stale observations 并跟踪 document/chunk 状态。
21. `fact_storage.py:338-470` upsert 文档元数据、正文标记和事实标签。
22. `entity_processing.py` 将抽取实体分成用户给定实体、候选实体和 canonical entity。
23. `entity_resolver.py:257` 的 `EntityResolver` 先做批内相似聚类，再结合现有实体和共现统计归一化。
24. `embedding_utils.py` 校验批量向量数量、维度和 provider 返回形状；维度错属于不可重试完整性错误。
25. retain 的 commit 点在事实、链接、实体引用、文档和 operation metadata 同一事务成功之后。
26. 输入防御拒绝会写 audit/webhook 证据，但不会把被阻断内容作为事实提交。

## 25. recall 的四路检索与证据优先级

1. `retrieval.py:34-72` 定义 query token、并行检索结果和 semantic/BM25 组合结果类型。
2. `retrieval.py:84-113` 管理默认 graph retriever；部署可注入实现但不改变 recall 契约。
3. `retrieval.py:123-412` 在 SQL 层组合向量语义与 BM25 词法结果，并应用 bank、type、tag、invalidated 过滤。
4. `retrieval.py:418-466` 计算时间覆盖选择，处理 event date、created date 和缺失日期。
5. `retrieval.py:467-796` 执行 temporal combined SQL，并把显式 temporal window 传到查询层。
6. `retrieval.py:797-` 的 `retrieve_all_fact_types_parallel` 对 world、experience、observation 并行查询。
7. `bm25_term_selection.py:75` 从 query 中选择词法 term，避免把所有自然语言 token 原样交给全文索引。
8. `fusion.py` 对各路候选执行 reciprocal rank fusion，并做跨路去重和 cap。
9. `reranking.py` 可将融合候选交给 cross encoder，预算由 bank config 和 recall budget 决定。
10. `recall_boost.py:33-101` 将 freshness、importance、source strategy 等加权到最终分数。
11. `graph_retrieval.py` 通过实体邻接和 memory_links 发现查询文本未直接命中的相关事实。
12. `link_expansion_retrieval.py` 提供受限二跳扩展，避免图遍历无限扩张。
13. `temporal_extraction.py:42-140` 使用有界线程池处理日期解析，并提供 async wrapper。
14. `tags.py` 统一 any、all、strict、exact 的标签匹配语义。
15. `trace.py:14-207` 记录入口、权重、节点访问、剪枝、各检索臂和最终摘要。
16. include_entities、include_chunks、include_source_facts 只扩大结果证据，不改变主分数。
17. max_tokens 限制序列化输出，不能推断数据库只保存了这些结果。
18. query_timestamp 是时间解释锚点；当前版本允许调用者直接传 temporal_window。
19. recall 是只读流程，不调用生成式 reflect LLM；无 LLM provider 仍可使用 embedding/BM25 路径。
20. 空结果必须结合 trace、tags、时间窗口、scope 和索引健康状态解释，不能直接判定 bank 无记忆。

## 26. reflect、observation 与 mental model 的关系

1. `reflect/agent.py:372-428` 的 `run_reflect_agent` 创建 disposition、directive、工具和 trace 上下文。
2. `agent.py:429-1160` 的 inner loop 保持工具调用、token 预算、上下文压缩和最终回答状态。
3. mental model 搜索位于工具序列前段；fresh 且覆盖 query 的摘要可以减少下层检索。
4. observation 搜索读取巩固事实及其来源范围，并在 stale 时降低可信度。
5. recall 工具补回 world/experience 原始事实，作为最终证据兜底。
6. `agent.py:807-1100` 固定工具 schema 和必须先检索的规则，防止模型直接编造回答。
7. `agent.py:1336-1476` 记录工具耗时并集中执行工具参数校验。
8. `agent.py:1202-1335` 处理 done 工具，负责回答、结构化输出和 based-on 汇总。
9. response_schema 由结构化输出路径校验；schema 错误不能降级为任意文本而标记成功。
10. `mental_model_refresh.py:79-291` 定义 refresh operation details、scope、window、fact counts、delta、retraction 和 trace 模型。
11. mental model 保存 source query、tags、refresh cron、scope watermark、文本/结构化内容和历史版本。
12. refresh operation 先计算窗口和证据差异，再决定保留旧内容、应用 delta、更新 watermark 或记录失败原因。
13. knowledge page 是 mental model 的树形组织和导出边界，不是事实表的替代品。
14. directive 只改变 reflect 的 mission、背景和行为约束，不参与 recall 候选排序。
15. observation 是由源事实派生的 memory_units 行，必须带 source memory ids 才能追溯。
16. 源事实变化会使 observation stale；stale 不等价于物理删除。
17. `clear_memory_observations` 保留源 memory，清除派生 observation 后触发下一次巩固。
18. `recover_consolidation` 处理失败或中断的 consolidation 状态，不应直接伪造成功 observation。
19. reflect 的回答来源应通过 `based_on`、trace 和 observation history 一起审计。
20. mental model、observation、raw fact 三层职责分别是摘要缓存、跨事实推导和可追溯原证据。

## 27. operation、worker 与维护循环

1. `engine/task_backend.py:26-93` 定义抽象 `TaskBackend`，约束 submit、get、cancel、retry 和 result metadata。
2. `SyncTaskBackend:95-125` 在调用线程/协程内执行，适合 embedded、测试和无后台 worker 部署。
3. `WorkerTaskBackend:126-152` 将任务写入 async_operations，由 poller 异步执行。
4. `BrokerTaskBackend:153-` 为外部 broker/扩展实现保留同一 operation 契约。
5. `worker/poller.py:152-205` 定义 active task、claimed task 和 slot availability 状态。
6. `WorkerPoller:207-` 是唯一的多 worker claim 入口，使用 pending/retryable 条件和数据库锁。
7. claim 查询在 `poller.py:211-479` 使用 `FOR UPDATE SKIP LOCKED`，避免多个 worker 领取同一 operation。
8. `poller.py:590-901` 处理任务状态、slot、RSS、墙钟 timeout 和 stale worker 恢复。
9. `poller.py:983-1050` 将 `DeferOperation`、`RetryTaskAt`、取消和普通异常映射为明确状态。
10. `worker/exceptions.py:17-42` 区分 retry-at、defer 和格式化任务错误。
11. `memory_engine.py:2859-3128` 允许业务流程请求延迟、重试或继续等待，不直接操作 poller 状态。
12. `memory_engine.py:3202-3215` 将可重试错误映射到 worker retry budget；不可重试错误直接失败。
13. `engine/maintenance.py:113` 的 `MaintenanceLoop` 负责过期 operation、孤儿状态、索引和统计维护。
14. `graph_maintenance.py:102-249` enqueue relink victims、entity prune candidates 并执行有界维护 job。
15. maintenance 和 graph queue 与用户 retain operation 分离，但共享 bank/schema/tenant 边界。
16. operation retention 只清理 terminal 状态，不能删除 pending 或 processing 的活跃工作。
17. cancel 通常是协作式；已经进入 provider 或数据库事务的子步骤可能完成后才观察到取消。
18. shutdown 先停止 poller/maintenance，再关闭 provider、连接池、文件句柄和临时任务。
19. stale processing 恢复依赖 worker heartbeat/时间阈值，生产环境要用实际配置验证。
20. “HTTP 返回 202”只证明 operation 接受；最终成功证据必须来自 operation 状态和事实表提交。

## 28. provider、embedding 与资源边界

1. `llm_wrapper.py:347-691` 解析 provider 名称、模型、API key、endpoint 和通用调用参数。
2. `LLMProvider:692-1610` 包装 chat、tool call、structured output、usage 和错误归一化。
3. `ConfiguredLLMProvider:1611-` 将 bank/member 配置应用到实际 provider。
4. `multi_llm.py:41-130` 按错误类型决定 failover，并提供 weighted round-robin 成员选择。
5. `llm_interface.py:60-365` 定义工具选择、消息、响应和 usage 的稳定抽象。
6. provider 适配器包括 OpenAI、Anthropic、Gemini、Groq、VertexAI、Bedrock、Ollama、LM Studio、LiteLLM、Codex、Copilot 等。
7. 每个 provider 可拥有不同的 tool/schema、缓存、限流和认证细节，但输出进入统一 LLMInterface。
8. `embeddings.py:85-156` 定义 Embeddings 抽象和输入/输出维度契约。
9. `embeddings.py:157-1663` 包含 LocalST、ONNX、TEI、OpenAI、Codex OAuth、Cohere、ZeroEntropy、LiteLLM 和 Gemini 实现。
10. `create_embeddings_from_env:1664-` 依据配置构造唯一 embedding provider，禁止同一 bank 随意混用维度。
11. `llm_wrapper.py:57-138` 为 retain、recall、reflect、consolidation 等操作建立 per-operation semaphore。
12. `db_budget.py` 对 SQL 读取、批大小和查询 token 设上限，避免一个请求耗尽连接池。
13. `cross_encoder.py` 的 reranker 也有并发、timeout 和 429 backoff，不应与 LLM 重试混为一层。
14. 外部 HTTP provider 必须使用配置的 endpoint、TLS、timeout 和凭据屏蔽规则。
15. `ProviderContentPolicyError` 说明 provider 错误不能只按 HTTP 状态码分类。
16. `ProviderRateLimitResetError`、网络错误、5xx 和 schema 修复错误拥有不同的 retry/failover 语义。
17. none provider 只关闭生成，不关闭 recall 的数据库和向量路径。
18. 本地模型、TEI、ONNX 和 pg0 的进程/文件资源应由 embed 或独立 worker 生命周期管理。
19. 关闭 provider 时必须释放 HTTP client、连接、线程池和 token 统计上下文。
20. 新 provider 选择规则：先实现原子适配器，再注册配置工厂，最后增加真实失败与资源释放测试。

## 29. 数据库、迁移与外部存储

1. `engine/schema.py:11-47` 对逻辑表名做 schema 限定，避免 bank/tenant 之间拼接任意 SQL。
2. `engine/db/base.py` 定义连接、事务、结果行、参数和 budget 边界。
3. `engine/db/postgresql.py` 管理 asyncpg pool、pgvector、全文搜索和 PostgreSQL session settings。
4. `engine/db/oracle.py` 为 Oracle 23ai 提供 SQL 方言和连接/事务兼容实现。
5. `engine/sql/postgresql.py`、`engine/sql/oracle.py` 生成检索、图、维护和分页 SQL。
6. Alembic migration 通过 `_dialect.run_for_dialect` 分发 PostgreSQL/Oracle upgrade 和 downgrade。
7. 初始 schema 建立 banks、memory_units、memory_links、entities、unit_entities、documents、chunks 和 async_operations。
8. 后续 migration 增加 observation history、mental model、tags、webhooks、audit、LLM trace、文件存储和维护队列。
9. migration 还维护 pg_trgm、GIN、HNSW/vchord、时间索引、source_memory_ids 和 per-bank vector index。
10. `engine/memories/pg/reads.py`、`writes.py`、`graph.py`、`curation.py` 分离读、写、图和整理 SQL。
11. `engine/storage/postgresql.py` 将文件正文放入数据库；S3/GCS/Azure 适配器以 storage key 保存外部对象引用。
12. `engine/transfer/export.py`、`importer.py` 以 manifest/ZIP 迁移 bank 数据，导入时重新计算 embedding。
13. 文件下载只接受受控 storage key；任意本地路径不是 API 参数。
14. `operation_metadata.py` 负责将复杂任务结果压缩成可轮询的 operation response。
15. foreign key、唯一约束、向量维度和 bank_id 是完整性错误；这些错误不能靠 worker 重试修复。
16. 迁移文件的形状测试要求每个 revision 包含方言 dispatcher，防止只在 PostgreSQL 可运行。
17. bank 删除要级联/清理 mental model、directive、documents、operations、webhooks 和外部文件引用。
18. Oracle 与 PostgreSQL 的业务目标一致，但执行计划、维护 routine、全文/向量扩展需要部署级验证。
19. 数据库索引健康和 maintenance routine 失败会在 metrics/health/audit 中留下证据，不应静默忽略。
20. 真实 schema、扩展版本和迁移耗时未在本次静态审计中启动验证。

## 30. 客户端、控制面、CLI 与集成边界

1. Python client 的高层 `Hindsight` wrapper 位于 `hindsight-clients/python/hindsight_client/hindsight_client.py`，把同步调用转为 async API 的便利入口。
2. 生成的 Python API 位于 `hindsight-clients/python/hindsight_client_api/api`，负责参数校验、序列化和 response model 反序列化。
3. TypeScript client、Go client、Rust client 与 OpenAPI schema 同步生成，版本漂移应通过 `scripts/generate-clients.sh` 修复。
4. `hindsight-cli/src/api.rs` 是 CLI 的唯一 HTTP 请求边界；`config.rs` 管理 profile、URL、token 和输出格式。
5. Rust `commands/memory.rs`、`document.rs`、`entity.rs`、`operation.rs` 分别覆盖事实、文档、实体和异步操作命令。
6. `commands/fs` 只负责本地 daemon/profile/config/health/state/sync，不读数据库表。
7. `hindsight-control-plane/src/lib/hindsight-client.ts:14-63` 构造 dataplane URL、headers 和高低级 client。
8. `src/lib/auth/session.ts:3-93` 使用签名 cookie、24 小时 session 和安全请求检查保护控制面。
9. `src/middleware.ts:25-81` 在 locale、login 和受保护页面之间做请求路由。
10. 控制面 `src/app/api/**/route.ts` 仅转发并翻译 dataplane API，不能旁路 memory_units。
11. 控制面页面覆盖 bank stats、operations、documents/chunks、memories、entities/graph、mental models、directives、audit、LLM requests 和 memory defense。
12. `hindsight-embed/profile_manager.py` 管理数据目录和 profile 锁，`daemon_embed_manager.py` 管理 API/worker 子进程。
13. `control_center/server.py`、`service.py`、`lifecycle.py` 为本地控制中心提供 profile、provider、日志和健康接口。
14. `hindsight-integrations` 下的每个目录是薄适配器，负责 bank/URL/凭证、触发时机和结果映射。
15. LiteLLM wrapper 在 `hindsight_litellm/wrappers.py:301-400` 显式调用 reflect，并在调用前后组合 recall/retain。
16. coding-agents 集成通过 hooks、session start/stop、MCP server 和 seed 机制为每个仓库绑定 bank。
17. 框架集成不得重实现 fact extraction、retrieval 或 consolidation；这些能力始终属于 API engine。
18. `hindsight-docs`、README 和 cookbook 是调用说明，不是另一份可执行实现。
19. 外部调用者应保留 operation_id、统一错误码和 retryable 语义，不能只判断 HTTP 200/202。
20. 客户端升级顺序是 API/OpenAPI → 生成 SDK → CLI/控制面/集成适配器 → 文档与示例。

## 31. 部署、可观测性与验证边界

1. Docker standalone 由 `docker/standalone/start-all.sh` 启动 API、worker、控制面和 pg0/外部数据库组合。
2. compose 变体覆盖 external-pg、local-llm、TEI、S3 storage、pg_search、pgroonga、vchord、Timescale 和 nginx。
3. Helm 模板分别部署 API、worker、control plane、PostgreSQL、TEI embedding/reranker、service、ingress、HPA 和 PDB。
4. `worker-statefulset.yaml` 使用稳定 pod identity 作为 worker 运行标识；API 与 worker 共享 async_operations 数据库。
5. liveness 只说明进程/event loop 存活，readiness 还要检查数据库，不能把两者混为服务可用性。
6. `/metrics`、`llm_requests`、`audit_logs`、operation metadata 和 search trace 共同构成可观测证据链。
7. API latency、worker slots、RSS、operation status、LLM token、provider errors 和 webhook deliveries 应分别监控。
8. `scripts/generate-openapi.sh` 和 `hindsight-dev/generate_openapi.py` 是 API schema 生成入口。
9. `scripts/generate-clients.sh` 生成 Python/TypeScript/Go/Rust 客户端，任何手工生成差异都应被覆盖。
10. `CLAUDE.md` 中的常用检查包括核心 pytest、ruff、ty、OpenAPI 生成、benchmark 和本地启动脚本。
11. 当前仓库的静态审计执行了 remote/hash、源码/目录统计、CodeGraph status/sync、关键符号定位和文档结构检查。
12. 未启动 PostgreSQL、pg0、Oracle、外部 LLM、embedding、TEI、S3、控制面或 Rust daemon。
13. 因此未宣称真实 retain、recall、reflect、migration、SSRF、防断电、kill、failover、压力或多 worker 竞态通过。
14. 最新提交的永久内容拒绝回归测试只证明该异常分类的代码契约；真实 Claude Code CLI 仍需 provider 集成环境验证。
15. 代码地图索引不是测试通过证据；索引成功只证明解析和关系可用。
16. 文档中的关键行号已按 `6ff6dc6` 快照复核；源码继续变化后必须重新同步并更新本文件。
17. 任何生产发布应补充数据库扩展、secret、TLS、资源上限、备份恢复和真实操作轮询证据。
18. 发布门禁必须检查 API/worker 配置一致、migration head、client 生成、镜像标签和 control plane dataplane URL。
19. 端到端验收应从 retain 提交开始，轮询 operation，到 memory_units/links/entities/observations，再执行 recall 和 reflect。
20. 结果报告应区分源码事实、测试事实、运行时事实和未验证风险，避免把静态推断写成现场成功。

## 32. 平台分层选择结论

1. 支持库候选：`engine/providers`、`engine/db`、`engine/storage`、`engine/embeddings`、`engine/cross_encoder`。
2. 这些包只做第三方/数据库/文件/向量/排序的原子协议转换、资源管理和错误映射。
3. 模块库候选：`engine/retain`、`engine/search`、`engine/reflect`、`engine/consolidation`、`engine/transfer`。
4. 这些包组合多个支持库完成记忆写入、检索、推理、巩固和迁移，不能被拆成若干互相复制的 provider 门面。
5. 应用编排层是 `MemoryEngine`；它绑定 bank、operation、事务、审计和多个模块流程。
6. 运行核心是 worker poller、task backend、maintenance、graph queue、cancellation 和资源预算。
7. 项目适配层是 FastAPI、MCP、SDK、CLI、控制面、embed 和 integrations；它们不应直接访问数据库表。
8. 平台控制面是配置、migration、OpenAPI、发布脚本、Helm/Docker 和可观测性。
9. 选择规则：有第三方生命周期或协议转换时归支持库；跨能力流程归模块库；绑定 bank/URL/权限/版本时归项目适配层。
10. 选择规则：只要需要 operation、事务、重试、证据或多能力编排，就不能把它定义成原子支持库。
11. 选择规则：只要一个功能能够通过公开 API/client 调用，就不能复制一套直连 SQL 的旁路实现。
12. 对系统工程平台的可复用启示是“唯一能力注册/调用边界 + 单 operation 账本 + 可追溯证据”，而不是复制 Hindsight 的目录名称。
13. Hindsight 的 memory_units 统一事实表适合承载 world、experience、observation，但 mental model 仍需单独的版本和 scope 状态。
14. Hindsight 的四路 recall 说明检索策略应可替换、可追踪、可限额，而不是在 API handler 中硬编码一条查询。
15. Hindsight 的永久 provider 错误说明错误分类应贯穿适配器、模块、worker 和 operation，而不是只返回字符串。
16. Hindsight 的 delta retain 说明文档更新必须以 chunk hash 和事务边界做增量，避免每次重建全部事实。
17. Hindsight 的 observation source ids、history 和 trace 说明派生知识必须保留证据链和失效语义。
18. Hindsight 的控制面和多 SDK 说明所有外部接口都应围绕同一 OpenAPI/operation 契约生成或薄封装。
19. 这些是源码观察结论，不代表系统工程平台应无条件照抄实现细节；平台仍需按自身中文契约和权限模型复用原则裁剪。
20. 本文是该 Hindsight 仓库根目录唯一架构文档；后续审计只更新此文件，不新增平行架构摘要。
