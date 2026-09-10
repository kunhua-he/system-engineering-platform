# PlugMem 架构建档

> 本文是基于当前工作树源码、README、设计文档、依赖声明、入口、数据模型和测试文件的首轮静态架构建档。
>
> 证据基线：仓库当前提交 `3b2ce75`。项目根未发现 `AGENTS.md` 或 `CLAUDE.md`；`plugmem-coding-claude-code/` 自带 README/ONBOARDING，`design_docs/` 是设计与阶段记录，不等同于运行时实现证明。

## 1. 项目定位

PlugMem 是面向 LLM Agent 的即插即用长期记忆服务。它不以原始交互历史作为主要检索单元，而是把轨迹结构化为可复用的语义、程序性、情景知识，并用向量相似度、标签投票、价值函数和 LLM 规划/推理生成回忆提示。

当前仓库同时包含三条代码面：

1. **Python 记忆服务/研究实现**：`plugmem/`，FastAPI + ChromaDB，是主运行时。
2. **编码 Agent 接入层**：`plugmem-coding-core/` 和 `plugmem-coding-claude-code/`，TypeScript harness-agnostic 核心及 Claude Code Hook 适配器。
3. **OpenClaw 插件**：`openclaw-plugmem-plugin/`，提供 `plugmem.remember` / `plugmem.recall`，并在 reset/compaction 生命周期自动存储轨迹。

`src/` 下仍保留 WebArena、LongMemEval、HotpotQA 等研究评测适配代码；它们不是当前 FastAPI 服务的包入口。

## 2. 总体文本流程图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 外部 Agent / 评测脚本 / HTTP 客户端                                            │
│  Python 调用、curl、@plugmem/coding-core、Claude Code Hook、OpenClaw Plugin    │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ REST /api/v1 + X-API-Key
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ FastAPI 应用：plugmem.api.app:app                                             │
│ middleware(request context + JSONL request log) → auth → routes               │
└───────────────┬─────────────────────┬──────────────────────┬─────────────────┘
                │                     │                      │
                │ /memories          │ /retrieve /reason    │ /extract
                ▼                     ▼                      ▼
┌───────────────────────┐  ┌────────────────────────┐  ┌───────────────────────┐
│ Memory / insert       │  │ MemoryGraph             │  │ promotion extractor   │
│ trajectory structuring│  │ planner → candidates   │  │ candidates → LLM JSON  │
└──────────┬────────────┘  │ similarity + tag vote   │  │ (不写 graph)           │
           │               │ value function → prompt│  └──────────┬────────────┘
           │               └─────────────┬──────────┘             │
           │                             │ /reason 再调用 LLM       │
           ▼                             ▼                         │
┌──────────────────────────────────────────────────────────────────────────────┐
│ 图内存模型（进程内）                                                          │
│ EpisodicNode ↔ SemanticNode ↔ TagNode                                        │
│        └────────────── ProceduralNode ↔ SubgoalNode                           │
│ graph_id 隔离；session_id 用于会话审计/时间线；source/confidence 用于过滤      │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ load / add / update / query
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ChromaStorage                                                                 │
│ 每个 graph_id 建 5 个 collection：semantic / procedural / tag / subgoal /    │
│ episodic；recall audit 另建 {graph_id}_recall_audit                            │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ PersistentClient / HttpClient / EphemeralClient
                               ▼
                     ChromaDB（本地持久、HTTP 或内存）

LLM 路径：OpenAI-compatible / Azure 客户端 → LLMRouter（default、structuring、
retrieval、reasoning、consolidation 角色）。
Embedding 路径：HTTP embedding → ChromaDB EmbeddingFunction；无服务时可使用
sha256 确定性本地 embedding（仅演示/测试，不具备语义质量）。

编码 Agent 旁路：
Claude native hook → normalize → abstract CoreCallbacks → promotion/recall → REST。
OpenClaw hook/tool → plugin client → REST；共享图只读 fan-in，默认图承担写入。
```

## 3. 分层与模块职责

### 3.1 接入层

| 模块 | 实际职责 |
|---|---|
| `plugmem/api/app.py` | 创建 FastAPI app，注册 `/api/v1` 路由、请求日志 middleware 和 `/inspector` 静态 SPA；根路径重定向到 inspector。 |
| `plugmem/api/routes/` | 图 CRUD、记忆写入、检索/推理、抽取、健康检查、Inspector、demo seed。 |
| `plugmem-coding-core/src/` | 把 Claude Code/OpenCode/OpenClaw 的原生事件统一成 `CoreCallbacks`，负责 graph-id、促成门、召回策略和 REST client。 |
| `plugmem-coding-claude-code/` | Claude Code stdin hook dispatcher；把 hook 输出转换为 `hookSpecificOutput.additionalContext`。 |
| `openclaw-plugmem-plugin/` | OpenClaw plugin SDK 形状的工具和生命周期 hook，提供 remember/recall。 |

### 3.2 应用编排层

- `plugmem/api/dependencies.py`：读取环境变量、构造单例配置、LLM、Embedding、Chroma client、`GraphManager`；测试可通过 `reset_singletons()` 重置。
- `plugmem/graph_manager.py`：按 `graph_id` 创建、缓存、加载、删除和列出 `MemoryGraph`；首次访问已有图时从 Chroma 加载节点和边。
- `plugmem/api/auth.py`：若设置 `PLUGMEM_API_KEY`，所有受保护路由要求 `X-API-Key`；未设置时认证关闭。
- `plugmem/api/logging_ctx.py` 与 `RequestLoggingMiddleware`：以 contextvar 聚合 LLM、检索、consolidation、资源和响应信息，并写 `logs/request_logs.jsonl`。

### 3.3 领域/内存层

- `plugmem/core/memory.py`：轨迹构造器；持有 `goal`、episodic/procedural/semantic 结构和 embedding。
- `plugmem/core/memory_graph.py`：图生命周期、加载/重建关联、插入、检索、trace、reason、语义合并和信誉衰减。
- `plugmem/core/graph_node.py`：五种实际节点：`EpisodicNode`、`SemanticNode`、`TagNode`、`SubgoalNode`、`ProceduralNode`。已有 `细探-PlugMem.md` 概括为“四类节点”，但源码明确存在 `SubgoalNode`，建档以源码为准。
- `plugmem/core/value_base.py`、`value_functions.py`：相似度、时效、重要性、可信度、回报等输入的可插拔价值评估和 top-k/阈值。
- `plugmem/core/normalize.py`：插入前的内存归一化。

### 3.4 推理与提示词层

- `plugmem/inference/structuring.py`：从 LLM 标记文本解析 subgoal/reward/state/facts/procedural/return。
- `plugmem/inference/retrieving.py`：解析 mode、plan、标签和语义合并 JSON 决策。
- `plugmem/inference/promotion.py`：编码 Agent promotion gate 的 LLM 抽取；解析失败或输出不合法时返回空列表。
- `plugmem/prompts/`：structuring、retrieving、reasoning 的模板和 `PromptRegistry`；可按 graph 覆盖。

### 3.5 基础设施层

- `plugmem/clients/llm.py`：OpenAI/Azure/OpenAI-compatible completion，支持多 base URL 轮询、重试、token JSONL、phase 标记。
- `plugmem/clients/llm_router.py`：按 `default`、`structuring`、`retrieval`、`reasoning`、`consolidation` 角色继承/覆盖 YAML 配置。
- `plugmem/clients/embedding.py`：HTTP embedding、确定性本地 embedding、ChromaDB adapter、cosine similarity。
- `plugmem/storage/chroma.py`：collection 生命周期、节点 metadata/embedding 序列化、分页加载、检索、recall audit。

## 4. 核心数据模型

### 4.1 节点与边

| 节点 | 主要字段/关系 | 用途 |
|---|---|---|
| `EpisodicNode` | `episodic_id`、observation、action、time、session_id、subgoal、state、reward；反向关联 semantic | 单步情景/轨迹证据，按 session 重组成历史。 |
| `SemanticNode` | `semantic_id`、文本、embedding、tags、`Credibility`、`is_active`、source、confidence、time；关联 tags、episodic、兄弟/子语义 | 事实、偏好、规则等高复用知识。 |
| `TagNode` | tag、tag_id、embedding、importance、semantic_nodes | 标签索引和 tag-vote。 |
| `SubgoalNode` | subgoal、subgoal_id、embedding、importance、activate、procedural_nodes | 程序性经验的子目标分组。 |
| `ProceduralNode` | procedural_id、文本、embedding、Return/return_value、source、confidence、session_id；关联 subgoal/episodic | 工作流、经验、步骤及回报值。 |

一个 `graph_id` 使用五个 Chroma collection：`{graph_id}_semantic`、`_procedural`、`_tag`、`_subgoal`、`_episodic`。列表型关联（tag IDs、episodic IDs、兄弟/子节点 IDs）以 JSON 字符串存入 metadata；embedding 作为 Chroma 向量存储。

另外，`{graph_id}_recall_audit` 记录 `/retrieve`、`/reason`、`/recall_trace` 的 endpoint、时间、查询、mode、plan、选中的 semantic/procedural IDs、session_id 和消息数。Inspector 的 sessions API 将节点插入与 recall 记录合并成时间线。

### 4.2 API 输入中的重要契约

- `MemoryInsertRequest.mode`：`trajectory` 或 `structured`。
- trajectory：`goal + steps[{observation, action}]`，服务端用 LLM 结构化。
- structured：可直接提供 episodic/semantic/procedural；semantic/procedural 支持 `source` 和 `confidence`，也支持预计算 embedding。
- `source` 枚举：`failure_delta`、`correction`、`merged`、`repeated_lookup`、`explicit`。
- `confidence`：0–1，默认 0.5。
- retrieve/reason 支持 `min_confidence`、`source_in`，过滤在候选收集阶段生效，而不是最终 top-k 后才过滤。

## 5. 核心数据流与关键路径

### 5.1 服务启动与依赖装配

1. `uvicorn plugmem.api.app:app` 导入 app factory。
2. 第一次请求通过 `get_config()` 读取 `LLM_*`、`EMBEDDING_*`、`CHROMA_*`、`PLUGMEM_API_KEY` 等环境变量。
3. `get_embedder()` 优先使用 `EMBEDDING_BASE_URL`；其次在有 `OPENAI_API_KEY` 时调用 OpenAI embedding；否则使用本地 sha256 embedder。默认配置仍声称 `nvidia/NV-Embed-v2`，在没有对应 URL 时会拒绝，以避免维度错配。
4. `get_graph_manager()` 按 `CHROMA_MODE` 选择 Persistent/HTTP/Ephemeral client，创建 `ChromaStorage`、LLM 和 `GraphManager`。
5. 图创建由 `GraphManager.create_graph()` 创建五个 collection；已有图被首次取用时 `MemoryGraph.load()` 读取所有节点、重建 lookup、恢复跨节点引用。

### 5.2 轨迹结构化写入

```text
(goal, first_observation, ordered steps)
        │
        ▼
Memory.append(action, next_observation)
        ├─ LLM: get_subgoal
        ├─ LLM: get_reward
        ├─ embedding: 相邻 subgoal 相似度；低于 0.75 切分 episodic trajectory
        └─ LLM: get_state，推进当前状态
        │
        ▼ Memory.close()
        ├─ 每个 step → LLM get_semantic → facts + tags + semantic embeddings
        └─ 每段 trajectory → LLM get_procedural → subgoal + insight
                                            + subgoal embedding
        │
        ▼ MemoryGraph.insert()
        ├─ 依次写 episodic
        ├─ 新建/关联 tag，写 semantic 与语义关联
        ├─ 新建/合并 subgoal，写 procedural
        └─ 更新进程内 lists/lookups 与 Chroma metadata
```

这是顺序写入路径，代码中未看到跨 collection 的事务抽象；发生中途异常时的跨 collection 一致性需要后续验证。

### 5.3 结构化写入与编码 Agent promotion

结构化写入由 `POST /api/v1/graphs/{graph_id}/memories` 直接组装一个 Memory-like 对象，跳过轨迹 LLM 结构化，只对缺失 embedding 的文本调用 embedder，然后进入同一个 `MemoryGraph.insert()`。

编码 Agent 的 promotion gate 是另一条前置筛选路径：

```text
Claude/OpenCode/OpenClaw abstract event
  ├─ user_prompt: correction regex → Candidate(correction)
  ├─ pre_tool: 记录 pending call
  └─ post_tool:
       failure → recent_failures（最多 20 个）
       success + 同 tool + 10 分钟内 failure → Candidate(failure_delta)

session_end / pre_compact
  → drainCandidates（取出并清空候选）
  → POST /api/v1/extract
  → LLM 保守地产生 0..N semantic/procedural + source/confidence
  → adapter 计算 repo graph_id
  → POST /api/v1/graphs/{id}/memories（structured）
```

`/extract` 只做抽取，不选择 graph、不写入图；graph 路由权属于适配器。Claude Code hook 是多进程的，所以 `DiskSessionState` 将 pending/failures/candidates 写入 `~/.cache/plugmem/sessions/<sessionId>/<key>.json`，session end 默认清理。

### 5.4 检索、trace 与推理

1. `POST /retrieve` 或 `/reason` 进入 `MemoryGraph.retrieve_with_trace(..., auto_plan=True)`。
2. 未显式指定 mode 时，retrieval LLM 用 `get_mode` 选择 semantic/episodic/procedural；`get_plan` 产生 next subgoal 和 query tags。
3. semantic 路径先做 embedding top-5，再做 TagNode 投票，合并候选并计算 relevance/recency/importance/credibility；procedural 路径先找最相近 SubgoalNode，再按 relevance/return/recency 评分。
4. `min_confidence`/`source_in` 在候选收集和 tag-vote 合并后都应用；value function 决定 top-k 和阈值。
5. 按 mode 生成事实、经验或情景文本，交给 reasoning prompt template 形成 `reasoning_prompt` 和 `variables`。
6. `/retrieve` 返回 prompt/variables，不额外调用最终推理 LLM；`/reason` 使用 graph 的 reasoning role 再调用一次 completion 并返回 `reasoning`。
7. `/recall_trace` 可在不自动规划时用默认 mode/tags/subgoal，返回 plan、逐节点 trace、selected IDs 和 rendered prompt，且尽力写 audit。

编码 Agent 的 recall 三个触发器均调用 `/retrieve` 而不是 `/reason`：session start 默认字符上限 2000，substantial user prompt 默认至少 30 字且上限 1000，tool-family recall 默认关闭且上限 800。返回形如 `<plugmem-recall trigger="..." graph="...">` 的 system context block。

### 5.5 Consolidation 与 Inspector

`POST /api/v1/graphs/{id}/consolidate` 调用 `update_semantic_subgraph()`：按时间范围扫描 active semantic nodes，可做 credibility decay；通过 tags 收集候选、embedding/value 函数评分，再由 consolidation LLM 生成 merged statement；合并节点保留旧节点的 episodic/tag 关联，并可软停用旧节点。

Inspector 提供：

- substring search、分页浏览节点；
- 单节点及一跳 edges；
- Cytoscape-shaped topology；
- recall trace；
- 只允许修改 semantic `is_active` 的 PATCH；
- recalls 列表、session 列表、插入+recall 时间线；
- demo graph seed。

## 6. API、CLI 与 SDK

### 6.1 HTTP API

除 `/health` 外，路由由 `app.py` 统一挂在 `/api/v1`；受保护路由使用 `X-API-Key`。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 返回服务版本及 LLM、embedding、Chroma 可用性。 |
| POST/GET | `/api/v1/graphs` | 创建图 / 列出 graph IDs。 |
| GET/DELETE | `/api/v1/graphs/{graph_id}` | 查看图统计 / 删除图及其 collections。 |
| GET | `/api/v1/graphs/{graph_id}/stats` | 节点计数。 |
| GET | `/api/v1/graphs/{graph_id}/nodes` | 基础节点浏览，支持 node_type、limit、offset。 |
| POST | `/api/v1/graphs/{graph_id}/memories` | trajectory 或 structured 写入。 |
| POST | `/api/v1/graphs/{graph_id}/retrieve` | 检索并返回 reasoning prompt/variables。 |
| POST | `/api/v1/graphs/{graph_id}/reason` | 检索后调用 LLM 生成推理答案。 |
| POST | `/api/v1/graphs/{graph_id}/consolidate` | 语义合并、信誉衰减、软停用。 |
| POST | `/api/v1/extract` | promotion candidate → 结构化 memory；不写图。 |
| GET | `/api/v1/graphs/{id}/search` | Inspector 文本搜索。 |
| GET | `/api/v1/graphs/{id}/node/{type}/{node_id}` | 节点详情和一跳边。 |
| POST | `/api/v1/graphs/{id}/recall_trace` | 带逐节点评分和计划的检索 trace。 |
| GET | `/api/v1/graphs/{id}/topology` | 图拓扑节点/边。 |
| PATCH | `/api/v1/graphs/{id}/semantic/{semantic_id}` | 修改 semantic 的 `is_active`。 |
| GET | `/api/v1/graphs/{id}/recalls` | recall audit，可按 session 过滤。 |
| GET | `/api/v1/graphs/{id}/sessions` | distinct session IDs。 |
| GET | `/api/v1/graphs/{id}/sessions/{session_id}` | 插入和 recall 的合并时间线。 |
| POST | `/api/v1/demo/seed` | 幂等地写入 demo graph。 |

### 6.2 Python 入口与 CLI 状态

当前可确认的运行入口是：

```bash
uv run uvicorn plugmem.api.app:app --host 0.0.0.0 --port 8080
```

`pyproject.toml` 声明了 Python 包和 dev extras，但没有 `[project.scripts]`。`design_docs/plugmem_cli.md` 里的 `plugmem init/start/stop/status/graphs/...` 是 **draft、pre-implementation** 设计，不是当前已落地 CLI；Typer、Rich、python-daemon 也未出现在现有项目依赖声明中。

### 6.3 TypeScript SDK 与适配器

- `@plugmem/coding-core`：导出 `PlugMemClient`、`createCore`、抽象事件类型、promotion、recall、repo-id、transcript parser；`PlugMemClient` 封装 graph CRUD、stats、memories、retrieve/reason、health、extract，并对网络错误及 408/429/502/503/504 做退避重试。
- `@plugmem/coding-claude-code`：`plugmem-cc-hook` 单一 dispatcher 从 stdin JSON 的 `hook_event_name` 分发 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PreCompact`、`SessionEnd`；注入响应写到 Claude Code hook stdout。Hook 出错仍返回 exit 0，避免阻塞 Agent。
- `@plugmem/openclaw-plugin`：导出 `createPlugMemPlugin`、client 和类型；注册 `plugmem.remember`（文本或轨迹）与 `plugmem.recall`（raw 或 reasoning），支持 `sharedReadGraphIds` 并行只读 fan-in。`before_reset`/`before_compaction` 可自动把 OpenClaw session JSONL 转成轨迹写入默认图。
- OpenCode coding adapter：设计文档列为 Stage 6 待做；当前目标目录未发现 `plugmem-coding-opencode/`。

## 7. 技术栈与依赖

### Python 服务

- Python `>=3.10`，setuptools build backend，包版本 `plugmem 0.1.0`。
- FastAPI `>=0.100`、Uvicorn `>=0.20`：HTTP/ASGI。
- ChromaDB `>=0.5`：向量和 metadata 存储，支持 persistent/http/ephemeral client。
- OpenAI `>=1.0`：OpenAI-compatible completion/Azure client。
- NumPy、Requests、PyYAML、Pydantic v2：向量计算、HTTP embedding、LLMRouter YAML、API schema。
- 测试 extras：pytest、pytest-asyncio、httpx。
- `uv.lock` 存在，包含完整解析依赖；本次只读取，没有执行同步或安装。

### TypeScript 适配器

- Node `>=18`、TypeScript `^5.4`、Vitest `^1.6`。
- `@plugmem/coding-claude-code` 以本地 `file:../plugmem-coding-core` 依赖 core。
- OpenClaw 插件使用 `@sinclair/typebox`，对 `@openclaw/plugin-sdk >=0.1.0` 为可选 peer dependency。
- 模块类型为 ESM；包入口为 `dist/index.js`，源码构建由 `tsc` 完成。

### 外部运行依赖

真正的轨迹结构化、规划、推理需要 OpenAI-compatible LLM；高质量检索需要 embedding endpoint。README 中还提供 Qwen/vLLM 和 NV-Embed-v2 的本地推理部署脚本，但本仓库不在服务启动时自动安装或启动模型。

## 8. 测试地图（仅静态读取，未执行）

本次按要求没有安装依赖、启动服务、构建或运行测试。测试文件本身显示了以下覆盖面：

### Python `tests/`

- API：`test_api_health.py`、`test_api_graphs.py`、`test_api_memories.py`、`test_api_retrieval.py`、`test_api_extract.py`、`test_api_source_confidence.py`。
- 核心/存储：`test_graph_manager.py`、`test_chroma_batch.py`、`test_retrieve_mode.py`。
- 客户端/配置：`test_embedding_client.py`、`test_embedding_get_embedding.py`、`test_llm_router.py`。
- 可观测性：`test_llm_logging.py`、`test_phase_tagging.py`、`test_logging_middleware.py`、`test_logging_helpers.py`、`test_graph_logging.py`。
- 适配器：`test_plugmem_client.py`。
- `conftest.py` 使用 fake LLM/fake embedder 与 `chromadb.EphemeralClient`，并通过 FastAPI `TestClient` 覆盖依赖，避免测试默认连接正式服务。
- 已读取的 API 测试覆盖图 CRUD、三种写入形态、session_id 传播、mode 选择/规范化、检索/推理/consolidate、audit、sessions timeline、promotion JSON 解析、source/confidence 合法性及过滤。

### TypeScript `plugmem-coding-core/tests/`

- `promotion.test.ts`：correction regex、同工具 failure→success、unknown 保守忽略、候选 drain。
- `core.test.ts`：session-start recall、空图不注入、session-end promotion 调 `/extract` 后 structured insert、无候选/空抽取不写入、client 注入。
- `recall.test.ts`：触发器、字符上限、工具族 regex。
- `repo_id.test.ts`：git URL 解析和 graph-id。
- `transcript.test.ts`：Claude JSONL 轨迹解析。
- `eval.test.ts`：评测 fixture/runner/metrics。

### Claude Code 与 OpenClaw 测试

- Claude：`state.test.ts`、`respond.test.ts`、`normalize.test.ts`、`cc-hook.test.ts`，覆盖磁盘 session state、stdout 注入、hook payload 归一化、dispatcher。
- OpenClaw：`plugin.test.ts`、`client.test.ts`，覆盖工具注册/消息转轨迹/auto-remember/shared-read 和 REST client。
- 各 TypeScript package 的 `package.json` 都声明 `npm test`/Vitest；本次没有运行这些命令。

## 9. 当前实现边界与设计漂移

### 已有实现

- FastAPI + ChromaDB 服务、graph 生命周期和五类节点。
- trajectory/structured 两种写入。
- LLM/embedding 注入、按角色 LLMRouter、PromptRegistry。
- semantic/procedural/episodic 检索、value function、source/confidence 过滤。
- `/extract` promotion gate 服务端、Claude Code hook core、OpenClaw 工具与生命周期存储。
- recall audit、Inspector、topology、session timeline、consolidation。

### 设计中但当前不可当作已实现

- `design_docs/plugmem_cli.md` 的 Typer CLI、TOML 配置、daemon、launchd/systemd、doctor/config 子命令：文档明示 draft/pre-implementation，当前 `pyproject.toml` 没有 script entry。
- OpenCode adapter 和 OpenClaw coding adapter：设计文档列为后续阶段；现有 OpenClaw 包是聊天/通用 agent 插件，不等同于设计中的 coding adapter。
- post-merge confirmation、repeated lookup、explicit remember promotion signals：coding 设计中标为 deferred；OpenClaw 的显式 remember 工具是直接写入，不是同一套 promotion signal。
- 评测 harness 目前是合成事件 + live service 的循环验证，不是完整真实 Agent 任务成功率或 CLAUDE.md crossover 评测。

## 10. 未确认项与后续核查清单

1. **根指导文件**：目标项目根没有 `AGENTS.md`/`CLAUDE.md`；需要确认是否存在仓库外或分支特有的协作规则。
2. **依赖锁定一致性**：`pyproject.toml` 是宽版本约束，`uv.lock` 有解析结果；尚未在本机环境验证锁定版本与当前 Python/平台可安装性。
3. **运行时健康语义**：`/health` 主要通过客户端构造和 Chroma `list_graphs()` 判断可用性，未在此静态建档中确认它是否实际探测 LLM completion 或 embedding 请求。
4. **Chroma 版本兼容性**：设计文档记录过 Chroma 0.6 `list_collections()` 返回值变化；当前 `storage/chroma.py` 已对字符串/collection 两种形态做兼容，但尚未运行针对当前锁定版本的真实探针。
5. **跨 collection 一致性**：`MemoryGraph.insert()` 顺序写 episodic、tag、semantic、subgoal、procedural，源码未显示事务或补偿机制；中途失败时是否会留下部分图，需要专门故障注入测试。
6. **并发与 ID 分配**：节点 ID 使用进程内列表长度，recall ID 使用 collection count；服务级并发、多个进程/实例写同一个 graph 时的冲突策略尚未确认。
7. **配置单例刷新**：依赖层有全局单例和 `lru_cache`；生产环境修改环境变量后是否需要显式进程重启，及多个 app/test client 的隔离方式需继续核查。
8. **API schema 同步**：TypeScript core 的 `types.ts` 与 Python `schemas.py` 都声称镜像 API，但字段覆盖并非完全相同（例如 Python API 有 Inspector/trace/阈值等扩展）；尚未建立自动 schema diff 门禁。
9. **可观测性文件写入**：请求日志和 token usage 是本地 JSONL append；日志轮转、敏感提示内容脱敏、并发追加可靠性没有在当前核对确认。
10. **数据撤回/过期**：当前支持 semantic `is_active` 软停用和 credibility decay；跨图撤回、source 级删除、嵌入重算、旧事实失效传播策略仍需确认。
11. **许可证**：README 未给出许可证结论；已有细探文件也标记为“见仓库 LICENSE，未确认徽章”，使用或抽取前应直接核对 `LICENSE`。
12. **模型输出契约**：structuring 仍依赖标记文本正则，retrieval plan/semantic merge 依赖解析约定；异常输出有 fallback，但真实模型的边界、重试和成本尚未在当前核对验证。

## 11. 关键证据索引

- 项目定位、安装、Quick Start、插件概览：`README.md`
- Python 依赖：`pyproject.toml`、`uv.lock`
- 服务入口与装配：`plugmem/api/app.py`、`plugmem/api/dependencies.py`
- API 契约：`plugmem/api/schemas.py`、`plugmem/api/routes/*.py`
- 节点与图：`plugmem/core/graph_node.py`、`plugmem/core/memory.py`、`plugmem/core/memory_graph.py`、`plugmem/graph_manager.py`
- 存储与客户端：`plugmem/storage/chroma.py`、`plugmem/clients/llm.py`、`plugmem/clients/llm_router.py`、`plugmem/clients/embedding.py`
- coding 设计：`design_docs/plugmem_for_coding.md`
- CLI 设计（未实现草案）：`design_docs/plugmem_cli.md`
- coding core API：`plugmem-coding-core/src/index.ts`、`client.ts`、`core.ts`、`adapter.ts`、`promotion.ts`、`recall.ts`
- Claude Code 入口：`plugmem-coding-claude-code/src/bin/cc-hook.ts`、`normalize.ts`、`state.ts`
- OpenClaw 入口：`openclaw-plugmem-plugin/src/index.ts`、`client.ts`、`config.ts`
- 测试：`tests/`、`plugmem-coding-core/tests/`、`plugmem-coding-claude-code/tests/`、`openclaw-plugmem-plugin/tests/`

## 12. 当前核对操作边界

本文件已吸收此前 `细探-PlugMem.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
当前核对只读取了项目资料并在项目根新增本文件 `ARCHITECTURE.md`。未修改源码、依赖、测试或配置；未安装依赖、启动服务、构建、运行测试、提交 Git。

## 13. 后续：通用底座映射、唯一链路与状态治理

本节是基于当前 PlugMem 源码的后续裁决输入，不是把 PlugMem 目录复制进系统工程平台，也不是把 PlugMem 的策略参数写成平台事实。当前源码事实与平台目标落点分开记录：带“源码事实”的内容来自本仓库；“平台映射/裁决”是后续需求登记、能力搜索、复用决策、占用租约、消费者验收契约和装配计划的输入，**不表示平台已经实现或本项目已经通过 L1-L4 验证**。

### 13.1 三条代码面先归并为一条记忆能力链

PlugMem 当前有 Python FastAPI 记忆服务、TypeScript coding core/Claude Code hook、OpenClaw plugin 三个接入面。它们不能在平台上各自变成一套记忆内核、检索器、LLM 路由、状态账本或网关；应按“适配层—记忆模块—运行核心—支持库—唯一 HTTP 网关”归并。

```text
外部 Agent / Claude Code Hook / OpenClaw Plugin / Python、TypeScript SDK
  → L4 项目适配层：事件归一化、repo graph_id、权限/配置、兼容别名、响应投影
  → L4 唯一 HTTP 网关：请求 id、能力 id、契约版本、参数大小/基础 schema 校验
  → L3 运行核心：能力调用、任务/执行单元、队列、并发、deadline、取消、租约、重试预算、崩溃恢复、证据
  → L2 记忆模块：轨迹结构化、promotion gate、记忆图编排、检索计划、候选合并、价值排序、prompt 视图、consolidation
  → L1 支持库/受管 provider：文本/JSON/图节点契约、向量/嵌入、Chroma 或其他存储、LLM/模型、HTTP/进程/文件资源原子能力
  → L0 公共契约：Memory、Episodic、Semantic、Procedural、Tag、Subgoal、Graph、Recall、Candidate、Task、Result、Error、Resource、Evidence
  → 受管 Chroma/数据库、LLM/embedding endpoint、文件系统、第三方库或独立执行单元
```

**单链路不变式：**一个原子能力只有一个能力 id、一个契约 owner、一个注册/调用入口和一条证据链。PlugMem 自己的 FastAPI `plugmem.api.app:app` 是当前项目的 HTTP 表面，不应在平台内复制为第二个网关；后续接入只把它变成 L4 薄适配，平台对外仍只有 `MCP工具箱/能力网关.py` 的 HTTP 网关三类动作（搜索/契约/执行），MCP 只能是该 HTTP 网关的可选适配。

### 13.2 PlugMem 能力到支持库、记忆模块、运行核心和网关的裁决

| PlugMem 能力/对象 | 当前源码证据 | L0/L1 支持库 | L2 记忆模块 | L3 运行核心 | L4 网关/适配 | 后续裁决 |
|---|---|---|---|---|---|---|
| 轨迹/结构化记忆入口 | `plugmem/api/routes/memories.py:22-148`；`Memory.close()` 后进入 `MemoryGraph.insert()`；structured 入口构造 Memory-like 对象后同样汇合 | L0 冻结输入/输出/错误；L1 提供 embedding、持久化原子写 | 负责 trajectory→episodic/semantic/procedural 的领域编排和节点关联 | 负责准入、deadline、资源预算、失败/部分写入对账 | coding core/OpenClaw/Python 客户端只做参数和结果映射 | **吸收为唯一写入模块**；禁止各 adapter 自建写链 |
| 编码 Agent promotion gate | `plugmem-coding-core/src/promotion.ts:73-189`；`plugmem/inference/promotion.py:63-146`；`POST /extract` 只抽取、不选 graph、不写图 | L0 定义 Candidate/ExtractedMemory/source/confidence/幂等与审计字段；L1 只提供模型调用和 JSON 校验原子能力 | 保留 correction/failure_delta 的领域判定、保守抽取和“抽取后写入”的流程 | 管理候选任务、超时、重试、取消、失败账本和执行资源 | 事件归一化、session state、graph_id、`/extract`/`/memories` 调用 | **吸收为模块策略**；`/extract` 不能成为第二写 owner |
| `Candidate`、pending call、recent failure | `promotion.ts:30-54,73-137`；recent failures 上限 20、匹配窗口 10 分钟 | L0 定义上限、时间和状态字段；L1 可提供受管 KV/文件原子读写 | 只解释 candidate 是否足以进入 promotion 流程 | 任务状态、并发、过期清理、崩溃后对账 | `DiskSessionState` 是 Claude 适配器私有状态，不向平台泄漏真实文件路径 | **L4 适配层保留，L3 治理资源**；不把插件 state 文件当长期记忆事实 |
| 五类节点与边 | `plugmem/core/graph_node.py`、`memory_graph.py:168-357,363-592`；`EpisodicNode`/`SemanticNode`/`TagNode`/`SubgoalNode`/`ProceduralNode` | L0 固化最小字段、版本、来源、溯源、活跃状态、引用关系和错误 | 负责图内关联、轨迹重组、语义/程序/情景视图及 consolidation 语义 | 负责图实例句柄、并发、版本/租约、恢复和资源回收 | 只投影节点/统计/trace，不持有节点对象 | **吸收为记忆模块数据模型**；不把内存列表当平台权威状态 |
| `ValueBase` 与具体 value function | `plugmem/core/value_base.py:7-50`；`value_functions.py:7-193`；当前实现主要返回 Relevance，`ValueBase.evaluate()` 的 Credibility 未计入最终和式 | L0 只定义 ValueBreakdown/排序/阈值字段和数值范围，不冻结具体权重 | 负责召回候选、tag vote、relevance/recency/importance/return/credibility 组合与 top-k | 负责价值计算任务的预算、模型/缓存版本和失败语义 | 只能接受明确策略参数，不能把策略参数写成平台默认事实 | **吸收策略接口，不吸收具体权重/默认阈值**；源码中 `Credibility` 未参与最终求和必须保留为事实/风险 |
| 检索计划、mode 与 prompt | `memory_graph.py:988-1108,1110-1272`；`get_mode/get_plan`；`PromptRegistry` | L0 固化 Query/Recall/RenderedPrompt/Trace 的结构，不固化“必须由 LLM 选 mode” | 负责 semantic/procedural/episodic 选择、tag vote、候选过滤、prompt 视图和 trace | 负责查询 deadline、并发、取消、重试和 audit 写入 | coding recall 只调用 `/retrieve`，OpenClaw 可选择 `/retrieve` 或 `/reason` | **吸收为一个检索模块**；策略模型是可替换策略，不是平台事实 |
| Chroma 五 collection 与 recall audit | `plugmem/storage/chroma.py:17-190,195-765,771-875`；每图 semantic/procedural/tag/subgoal/episodic，audit 延迟创建 | L0 定义 MemoryStore/Vector/Metadata/Audit 结果、批量、分页、版本和部分成功语义 | 只提交“写什么/按什么语义检索/如何解释结果” | 管理连接/执行单元、存储租约、超时、取消、崩溃恢复和残留 | 网关不暴露 Chroma client、collection 名或内部 metadata JSON | **候选升级/新建记忆存储支持库**；不把 Chroma collection 布局当公共契约 |
| embedding | `plugmem/clients/embedding.py:22-175`；HTTP 单条/批量、重试、60 秒单条 timeout/120 秒批量 timeout、本地 sha256 fallback | L0 固化输入长度、维度、模型摘要、结果/错误/可重试、批量顺序 | 只请求 embedding，不拥有模型或连接 | 监督模型执行单元、GPU/内存/并发、deadline、取消、崩溃回收 | 适配层只绑定 endpoint、密钥引用、模型版本 | **复用/升级模型支持库**；本地 sha256 只能是明确 demo/test provider，不能静默作为生产降级 |
| LLM structuring/retrieval/reasoning/consolidation | `plugmem/clients/llm.py:56-151`；`llm_router.py:44-154`；按角色 YAML 继承 default | L0 固化 completion 请求/响应、模型版本、token、错误和资源字段 | 负责提示词、结构化、计划、合并、最终 reasoning 业务语义 | 负责调用预算、超时/取消、重试、限流、模型进程/连接生命周期 | 适配层绑定配置与权限，不暴露 provider 对象 | **复用/升级唯一模型支持库**；角色路由是策略配置，不是多个模型执行核心 |
| graph cache / singleton | `graph_manager.py:17-97`；`dependencies.py:30-193` 的 `lru_cache` 和全局 client | L0 定义 graph/运行实例句柄及失效语义 | 记忆模块可使用 graph cache 作为性能优化，但不能把它当事实源 | 负责缓存上限、隔离、失效、关闭、重启恢复 | 只传 graph_id/不透明句柄 | **升级运行核心缓存治理**；禁止项目适配器共享全局单例 |
| API / SDK / hooks | `plugmem/api/app.py:20-151`；`plugmem-coding-core/src/client.ts:25-195`；OpenClaw `src/index.ts:364-669` | L0 冻结 HTTP/JSON/错误/请求 id/幂等/生命周期字段 | 只暴露 memory/retrieve/reason/consolidate 领域命令 | 处理执行单元和任务状态，不把 HTTP 200/Promise resolve 当业务成功 | L4 负责 hook/工具/SDK 归一化和输出投影 | **吸收协议边界，废弃第二网关**；MCP/插件只做薄适配 |
| 异步/并发/重试 | `PlugMemClient.request()` 使用 `AbortController`、指数退避；OpenClaw 多图使用 `Promise.allSettled`；Python `/extract` 是 async 外壳但内部同步调用 | L0 定义 task/run/deadline/cancel/terminal/resource release | L2 只能提交领域任务，不能自建任务账本或线程池 | L3 唯一拥有队列、线程/进程、任务持久化、超时、取消、崩溃恢复 | L4 只投影 accepted/running/terminal 状态 | **复用平台任务系统/资源监督**；当前 PlugMem 没有闭合的持久异步任务系统，不能宣称已有 |

### 13.3 不把策略模型当平台事实

PlugMem 中“模型输出”和“策略对象”必须与平台事实分离：

1. `get_mode()` 的 semantic/episodic/procedural 选择、`get_plan()` 的 `next_subgoal/query_tags`、prompt 模板和 `PromptRegistry` 是**运行时策略**；即使同一模型重复输出，也不能写成 L0 的事实字段或稳定平台默认。
2. `ValueBase` 及 `TagRelevant(k=1, threshold=0.8)`、`SemanticRelevant(k=10)` 等是**召回策略**；`k`、阈值、Relevance/Recency 权重、tag vote 的 `5.0/2.0` 系数应进入可版本化策略配置和 trace，不进入公共事实模型。当前 `ValueBase.evaluate()` 计算了 `v_credibility` 却只返回 importance+relevance+recency+return，不能把“可信度已参与价值”宣称为平台事实。
3. promotion LLM 的 `confidence` 是抽取模型对候选的判断，不是经验证据的事实可信度；`source` 是来源/生成方式标签。平台必须额外区分 `derivation_method`、evidence、review/activation 状态和写入版本，不能只因 `confidence >= 0.9` 就晋升为稳定知识。
4. `LocalDeterministicEmbeddingClient` 的 sha256 向量仅保证确定性，不具语义质量；不能在生产无提示地替代真实 embedding。HTTP LLM/embedding 的模型名称、endpoint、角色分配也都是 provider 策略，不是平台唯一模型。
5. `/reason` 的最终文本、`reasoning_prompt`、consolidation LLM 的 merged statement 是派生视图；它们不能覆盖原始 episodic 证据，也不能不经版本/溯源直接成为事实。
6. “空列表”“No relevant fact”“No relevant experiences”必须与 provider 失败、超时、取消、审计失败分开；当前部分代码把抽取失败降成 `[]`，这是当前实现语义，不是平台应继承的成功语义。

平台事实只应是：契约版本、输入/输出结构、来源证据、存储提交状态、任务状态、资源释放结论、请求/运行/版本坐标和稳定错误码。策略模型可以更换，但不能改变这些公共事实和终态语义。

### 13.4 记忆状态、资源生命周期与唯一事实 owner

#### 13.4.1 记忆操作状态

当前 PlugMem 主要以函数返回、HTTP 状态和日志表达状态，没有统一持久任务状态机。下面是**目标公共契约**，不是当前源码已实现状态：

```text
created
  → admitted
  → queued
  → running
  ├─→ succeeded
  ├─→ failed
  ├─→ cancel_requested → cancelled
  ├─→ deadline_exceeded → timed_out
  └─→ provider_lost/host_exception → crashed

succeeded/failed/cancelled/timed_out/crashed
  → draining
  → cleaned
  └─→ cleanup_failed（告警/残留治理，禁止伪报成功）
```

域内还需区分以下事实：

- **候选**：`detected → buffered → drained → extracted/rejected → routed`。当前 `drainCandidates()` 先读取再删除候选；若 extract 或后续 insert 失败，源码没有恢复队列的持久化语义，平台必须用幂等键/失败账本避免“已删除但未写入”静默丢失。
- **记忆写入**：`validated → writing → committed`，或 `writing → partially_persisted/failed`。`MemoryGraph.insert()` 按 episodic、tag、semantic、subgoal、procedural 顺序逐次写 Chroma，源码没有跨 collection 事务或补偿；因此当前不能把 `MemoryInsertResponse(status="ok")` 解释为跨 collection 原子提交。
- **召回**：`requested → planned → candidate_scored → rendered → audited`；audit 是 best-effort，`_write_audit()` 失败会被吞掉，故“召回返回成功”与“审计已落账”必须是两个字段。
- **合并/停用**：`consolidation_started → scanned → merged/soft_deactivated → persisted`。源码对合并和 `is_active` 更新也没有全图事务；旧节点保留和新节点写入必须在平台契约中明确提交/补偿/恢复。
- **图实例**：`declared → collections_created → loaded/cache_warm → invalidated → deleted`。`GraphManager` 只在进程内缓存 graph，Persistent Chroma 可在新进程重新 load；Ephemeral Chroma 则随进程丢失，这是存储 provider 的部署语义而非记忆模块可隐藏的差异。

#### 13.4.2 资源生命周期表

| 资源 | 当前创建/持有者 | 正常释放 | 失败/超时/取消/崩溃要求 | 目标 owner |
|---|---|---|---|---|
| `MemoryGraph` 节点列表、lookup、session map | `GraphManager` 创建/缓存；`MemoryGraph.load()` 从 Chroma 重建 | `invalidate_cache`/进程退出；当前无显式 close | 并发写、进程崩溃、缓存失效后不得把旧列表当权威；重启必须从持久存储重建并检查 ID/关联 | L3 运行实例缓存，L2 只读/提交领域对象 |
| Chroma client/collection | `dependencies.get_graph_manager()` 创建 `PersistentClient`/`HttpClient`/`EphemeralClient`；`ChromaStorage` 持有 | provider close/执行单元释放；当前未见统一 close | 连接断开、collection 半写、删除失败、进程崩溃要有 provider 错误和恢复/对账；不能吞异常伪造删除成功 | L1 存储 provider + L3 执行单元 |
| LLM OpenAI/Azure client 与 URL cycle | `get_llm()` 单例或 `LLMRouter` 持有；`complete()` 轮询 URL、重试并 sleep | provider/进程关闭 | 当前 `OpenAICompatibleLLMClient` 未显式 timeout/cancel；达到重试上限返回空字符串。平台必须有硬 deadline、可重试分类、取消传播和模型资源释放 | L1 模型 provider，L3 监督 |
| embedding HTTP 会话/本地向量 | `HTTPEmbeddingClient` 每次 `requests.post`；本地 sha256 无外部句柄 | HTTP response 结束；requests session 由库管理 | 单条/批量 timeout、维度错误、服务断线、取消和 provider 崩溃必须统一；batch 输出顺序和维度要读回校验 | L1 embedding provider，L3 预算/取消 |
| candidate/session JSON 文件 | Claude `DiskSessionState` 写 `~/.cache/plugmem/sessions/<session>/<key>.json`；每 hook 进程独立 | `clear()` 由 session_end 调用；文档明确无周期 prune | crash/kill/缺 session_end 会留 stale dirs；`writeFile` 非原子且无锁，跨 hook 竞态/部分 JSON 要被发现；不能当长期事实库 | L4 适配层短期 state；L1 文件原子能力可复用；L3 清理治理 |
| request context、token usage、JSONL logs | `RequestLoggingMiddleware`/`RequestContextLog`；LLM `_log_usage()` append；本地 `logs/request_logs.jsonl` | request finally；文件 handler 进程内持有 | 脱敏、并发 append、磁盘满、日志句柄、客户端断开和异常写入必须有界；audit/log 失败不能反写业务成功 | L3 运行证据/日志支持库，L4 只查投影 |
| `fetch` `AbortController`/timer/Promise | TypeScript clients 每请求创建 controller+timer；OpenClaw 多图 `Promise.allSettled` | response/error 后 clear timer；fan-out 等待 settle | abort 只停止客户端等待，不证明服务端停止；fan-out 单图失败可部分成功，不能把全部成功；需 request/operation id 和服务端终态 | L3 任务/HTTP provider；L4 仅投影 |
| 临时模型/外部 endpoint/GPU | 本项目只持 endpoint client；本地推理脚本和外部服务不由 FastAPI 启动 | provider 负责退出/租约到期释放 | endpoint 崩溃、GPU OOM、连接池、重试重复副作用需独立进程/租约/残留检查；当前仓库未闭合 | L1 provider + L3 运行核心 |

所有资源必须在“正常完成、业务失败、主动取消/超时、宿主/子进程崩溃”四种终态给出释放结论。`Future.cancel()`、`AbortController.abort()`、日志“已停止”、HTTP 200 或进程退出等待都不能单独证明底层资源已释放。

### 13.5 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码语义 | 当前缺口/风险 | 平台验收与落点 |
|---|---|---|---|
| 候选为空/模型返回空 | `extract_coding_memories()` 返回 `[]`；`/extract` 也返回空 memories | 空候选、抽取失败、模型超时和非法 JSON 不可区分 | L2 保留 `NO_CANDIDATE`/`EXTRACT_EMPTY`/`MODEL_FAILED`；L3 记录 attempt/deadline/模型版本 |
| LLM 异常/非法 JSON | `LLMClient.complete()` 重试后返回空字符串；promotion parser 非法 JSON 返回 None 后空列表 | 失败被降级成“无值得记忆”，可能丢候选；没有稳定错误码 | L1 返回模型错误；L2 决定是否降级/拒绝；L3 失败账本/幂等重试；不得伪报 promotion 成功 |
| embedding 失败/维度不一致 | HTTP client 重试上限后抛 `RuntimeError`；Chroma 缺 embedding function 时批量写抛 `ValueError` | route 没有统一映射；可能中断写入且前序 collection 已写 | L1 `PROVIDER_UNAVAILABLE`/`VECTOR_DIMENSION_MISMATCH`；L2 部分写入可读；L3 对账/补偿/拒绝重复写 |
| Chroma 单 collection/跨 collection 部分失败 | `MemoryGraph.insert()` 多次 `add/update` 顺序执行，未见事务 | episodic 已写但 semantic/procedural 未写；内存与 Chroma 可能不同步 | L1 批量写和存储错误；L2 提交意图/写入计划；L3 `commit_unknown`、读回、补偿和资源释放 |
| 重复 graph/node/recall id | node id 基于进程内 list 长度；recall id 用 collection `count()`；多进程并发未定义 | 同一 graph 多实例可能 ID 冲突或 add 失败；重试 POST 可能重复写 | L0 幂等键/请求 id；L3 串行化/CAS/唯一约束；重复请求读回而不是再写 |
| 检索空结果 | `No relevant fact`/`No relevant experiences` 或空 selected | 空结果与 provider 失败、过滤全排除、模型计划失败混淆 | L2 分离 `NO_RESULT`/`FILTERED_EMPTY`/`RETRIEVAL_FAILED`；L4 正确投影 |
| 检索 audit 失败 | `_write_audit()` 捕获全部异常并 `pass` | 业务成功但证据缺失，recall count 与事实不一致 | L3 audit 独立状态、失败告警；返回应含 `audit_status`，不能吞后仍称完整证据 |
| HTTP 408/429/502/503/504 或网络错误 | TS clients 对部分状态和网络错误指数退避；`AbortController` 按 timeout abort | POST insert/reason 重试的幂等性未证明；服务端可能已提交而响应丢失 | L3 只对契约允许的操作重试；带幂等键；响应丢失先读回状态 |
| 主动取消/客户端断开 | TypeScript 只中止 fetch 等待；Python route/LLM/MemoryGraph 未见取消 token | 服务端可能继续写 Chroma/调用模型；调用方误以为已取消 | L0 区分 cancel request 与 cancelled；L3 真实传播/排空；不能用客户端 abort 伪装服务端终止 |
| 超时 | embedding requests 有 timeout；LLM OpenAI client 未在本项目显式设置硬 timeout；Python `/extract` async 壳不等于后台任务 | timeout 边界不统一，线程/请求可能仍运行 | L3 统一 deadline；不可协作取消的 provider 用独立进程组；返回 `TIMED_OUT`/`CANCELLED`/`STILL_RUNNING` 明确语义 |
| Hook state 写入失败/JSON 损坏 | core 捕获 record 错误并 log；DiskState 读到非 ENOENT 错误会抛 | promotion detector 可能无状态静默 no-op；stale dirs 没有 prune | L4 适配器显式降级；L3/文件支持库原子写、锁、恢复、清理审计 |
| OpenClaw 多图 fan-out 部分失败 | `Promise.allSettled` 保留成功图并把失败图格式化到文本 | partial 结果没有结构化失败字段；reasoning/raw 两条调用都可能部分成功 | L2 返回 graph-level result/partial；L3 子任务终态和取消/资源结论；L4 只投影 |
| 进程崩溃/重启 | Persistent Chroma 可由新 `GraphManager` load；Ephemeral 丢失；session JSON 文件可能残留；没有 PlugMem 任务账本 | 未完成写入、cache、候选 drain 后丢失、外部模型进程 orphan 未闭合 | L3 持久化意图/幂等键/租约；新进程读回 graph/写状态，清理文件/进程/连接；不能因 `load()` 成功宣称事务恢复 |
| consolidation 中途失败 | 逐节点 decay/merge/update，旧/新节点可能已部分落盘 | 软停用与新节点可能不一致，`updated` 主要是进程内标记 | L2 生成合并计划和来源；L3 任务状态/CAS/恢复；L1 存储提交与回读 |

### 13.6 L0-L4 平台验收等级

以下 L0-L4 是系统工程平台的验收分层，不是 PlugMem 官方分层，也不是当前源码已经具备的等级。

| 等级 | 平台允许承载 | PlugMem 映射 | 当前状态/禁止伪装 |
|---|---|---|---|
| **L0 公共契约** | 记忆节点、候选、图、召回、策略版本、任务、错误、资源、证据字段；输入/输出/版本/幂等/超时/取消语义 | Python `schemas.py`、TS `types.ts`、`GraphNode` 和 `RecallResponse` 可作为字段线索 | **静态可吸收，待平台冻结**；不能把 Pydantic/TS 类型存在当平台契约已登记 |
| **L1 支持库/受管 provider** | Chroma/向量存储、embedding、LLM、HTTP、文件/JSON、serializer 的原子能力和资源边界 | `ChromaStorage`、`HTTPEmbeddingClient`、`OpenAICompatibleLLMClient`、`DiskSessionState` | **源码边界明确，真实 provider 未执行**；缺服务应记 `HOST_UNAVAILABLE/UNVERIFIED`，不能 skip 伪绿 |
| **L2 记忆模块** | trajectory structuring、promotion、memory graph、value/retrieval、consolidation、reasoning prompt、引用/trace | `Memory`、`MemoryGraph`、`inference/*`、`prompts/*` | **领域语义可吸收**；策略模型、阈值、具体 prompt 只能版本化配置，不能成为 L0 事实 |
| **L3 运行核心** | 唯一调用器、任务/DAG、队列、并发、租约、deadline、取消、重试预算、崩溃恢复、资源/证据 | 当前只有 client retry、FastAPI middleware、`api_lock`、进程内 singleton；无统一持久任务账本 | **主要缺口，未验证**；不能用 Promise、日志、HTTP 200、Chroma load 或 Future abort 代替 L3 证据 |
| **L4 接入/适配/网关** | repo graph_id、hook/tool/SDK、权限/配置、HTTP/MCP/CLI、请求/结果投影、兼容别名 | `plugmem-coding-core`、Claude/OpenClaw adapter、FastAPI routes | **边界可吸收，未完成冷启动接入**；不得复制第二网关、第二注册表或第二任务系统 |

最低验收必须分层：L0 做 schema/错误/版本/幂等/资源字段静态检查；L1 做每个存储、embedding、LLM、文件 provider 的真实成功/空输入/非法参数/断线/超时/取消/崩溃/释放；L2 做 trajectory/promotion/write/retrieve/reason/consolidate 的固定 fixture、过滤、引用、部分失败和结果对称；L3 做并发、重复 POST、队列满、deadline、取消、强杀、重启恢复和零残留；L4 做冷启动装配、HTTP/SDK/hook/OpenClaw 结果对称、认证/graph 隔离、版本锁和发布门禁。任何 `skip`、测试文件存在、mock LLM、导入成功、日志、历史评测分数、HTTP 200 或子代理回执都不能越级算通过。

### 13.7 命中、缺口、唯一落点与装配计划

| 能力域 | 已有底座命中 | 缺口 | 裁决 |
|---|---|---|---|
| 记忆节点/候选/召回/任务公共字段 | 公共契约基础类型、结果/错误/证据模式、平台任务系统方向 | 尚无 Memory/Recall/Promotion/Provenance 字段统一契约 | **新建 L0 记忆契约候选**，先登记和搜索，不能直接写生产底座 |
| Chroma/向量/metadata 存储 | 平台资源管理、文件/数据集合、第三方 provider/唯一调用器模式可复用 | 无记忆图节点、向量维度、collection/索引、批量/部分提交/读回契约 | **新建或升级 L1 记忆存储支持库候选**，不复制 Chroma 全部 API |
| LLM/embedding | 平台已有本地 LLM/模型 provider、环境/资源监督、唯一能力调用 | 需要角色、模型摘要、token、维度、批量顺序、失败/取消/成本字段 | **升级模型支持库**，角色路由保留为 L2 策略配置 |
| promotion/记忆图/价值检索 | 模块库组合模式、结果/证据、任务监督可复用 | 需要 provenance、策略版本、候选幂等、部分写、引用和矛盾语义 | **新建唯一记忆模块候选**；不把 `MemoryGraph` 直接变平台运行核心 |
| hook/SDK/OpenClaw/FastAPI | HTTP 网关、项目适配层和客户端协议模式 | PlugMem 现有 FastAPI 不能作为平台第二网关；TS/插件状态需清理契约 | **L4 兼容适配**；历史入口只在唯一入口归一化 |
| 异步/资源/崩溃 | `运行核心/任务调度/任务系统.py`、`平台控制面/资源监督.py`、提供者隔离/租约方向 | PlugMem 具体操作尚未接入统一 task/evidence/cancel/recovery | **复用 L3，禁止新增 PlugMem 任务系统** |

装配顺序固定为：

```text
需求登记/能力搜索/现有能力命中核对
  → 冻结 L0 Memory/Candidate/Recall/Task/Resource/Evidence 契约
  → 记忆存储支持库：Chroma/向量/metadata/批量/分页/读回/失败语义
  → 模型支持库：LLM/embedding provider、版本/额度/超时/取消/资源
  → L2 唯一记忆模块：structuring → promotion → write；retrieve → value → render；consolidate
  → L3 运行核心：唯一调用器、任务/租约、deadline、取消、崩溃恢复、证据和残留审计
  → L4 项目适配：Claude/OpenClaw/TypeScript/Python/HTTP 参数和结果映射
  → 唯一 HTTP 网关；MCP 仅薄包装
  → L0 静态 → L1 provider → L2 固定记忆链 → L3 故障/并发/恢复 → L4 冷启动/发布门禁
```

当前核对**不创建平台文件、不登记能力、不安装依赖、不启动 Chroma/LLM、不修改 PlugMem 源码/配置/测试/README、不删除旧细探、不提交 Git**。当前目标仓库未找到名为 `细探-*.md` 的旧细探文件；现有 `ARCHITECTURE.md:93,369-370` 已记录此前 `细探-PlugMem.md` 的吸收声明，本文不把该缺失文件冒充为当前核对新证据，也不删除任何旧细探。后续若从仓库外或 Git 历史找回旧稿，必须逐条与当前源码核对后再更新本文件。

### 13.8 后续证据、MCP 状态与剩余风险

| 证据项 | 当前核对事实 | 结论 |
|---|---|---|
| 开工 id | 首次 `project_context` 返回 `开工id` 为空 | 开工记录不完整；不能编造 id |
| MCP 实例 | 返回 `project_toolkit`，不是任务指定的 `system_engineering_toolkit` | 错绑事实保留；未将错绑上下文当 PlugMem 证据 |
| project_context 项目 | 返回“华世王镞_v3”，根目录 `~/Documents/Agent/PHP/华世王镞_v3` | 与目标 PlugMem 不一致，按阻断处理 |
| 代码图 | PlugMem 根目录当前存在独立 `.codegraph/`，本轮用目标目录内 CLI 状态核对 | 图谱只作定位辅助；源码事实来自目标路径只读核对，未冒充运行验证 |
| 目标根 | `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/PlugMem` | 已按绝对路径核对 |
| 修改范围 | 仅追加本文件后续章节 | 未改源码、依赖、配置、测试、README、旧细探或 Git |
| 运行验证 | 当前核对未安装依赖、未启动服务、未执行 Python/TypeScript 测试或真实 provider | L1-L4 均未验证；文档写入成功不等于实现完成 |

剩余风险集中在：跨五 collection 原子提交/补偿、进程内 ID 并发冲突、LLM 硬超时和取消、embedding 维度/模型漂移、候选 drain 后失败恢复、Chroma/HTTP provider 崩溃回收、审计失败可见性、GraphManager singleton 隔离、跨适配器 schema 对称性，以及当前 `ValueBase` 忽略 Credibility 的实现语义。以上均保持 `待核/未验证`，不因平台映射章节存在而升级为“已接入”。

后续完成定义：PlugMem 的插件化记忆、promotion、价值评估、存储、检索、模型和异步资源已经明确映射到 L0-L4 的唯一 owner；策略模型与平台事实已分离；状态、资源生命周期、失败/超时/取消/崩溃、唯一链路和 L0-L4 验收门已冻结为候选输入；这不等同于系统工程平台已完成 PlugMem 能力生产化。
