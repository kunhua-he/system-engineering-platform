```text
[MCP 宿主：Claude Code / Codex / Cursor / Hermes / 其他 MCP-over-stdio 客户端]
                                  │ stdio MCP
                                  ▼
                 [mcp-wrapper/：Node.js + TypeScript]
                 ├─ src/index.ts：MCP Server、stdio transport、工具注册
                 ├─ src/tools.ts：14 个 hot tool 的 schema 与调用分发
                 ├─ src/bridge.ts：PythonCoreBridge、NDJSON JSON-RPC、重连
                 └─ src/ipc.ts：POSIX Unix socket；Windows 127.0.0.1+token
                                  │ JSON-RPC over local IPC
                                  ▼
                 [Python 本地引擎：iai_mcp.daemon]
                 ├─ daemon/__init__.py：启动、生命周期、warm-up、后台调度
                 ├─ socket_server.py：请求校验、core.dispatch、错误码
                 ├─ core/__init__.py：MCP/RPC 方法门面与序列化
                 └─ SleepPipeline：空闲时执行 NREM/REM 巩固周期
                         │                         ▲
        ┌────────────────┘                         │ 生命周期/空闲/唤醒
        │                                          │
        ▼                                          │
[Ambient hooks：_deploy/hooks/*.sh]                │
  SessionStart → session-start payload             │
  UserPromptSubmit → live/deferred capture         │
  UserPromptSubmit → per-turn foresight             │
  Stop → transcript rollover / deferred capture     │
        │                                          │
        ▼                                          │
[捕获写入管道：capture.py / store buffers]
  JSONL/session buffer → shield → document embed
  → idem SHA-256 + cosine near-dup gate
  → encrypted MemoryStore insert + graph/event writes
        │
        ▼
[Hippo 本地存储：~/.iai-mcp/]
  records（MemoryRecord + encrypted literal/provenance）
  edges（Hebbian / contradicts / consolidated_from / schema 等）
  events、budget/rate-limit ledger、_hippo_meta、record_tags
  SQLite-compatible HippoDB + HNSW/exact index + optional Lilli driver
        │
        ├─────────────────────────────────────────────────────────────┐
        │                                                             │
        ▼                                                             ▼
[召回热路径：core → pipeline/retrieve]                         [睡眠巩固：SleepPipeline]
  cue embed → ANN + exact authority → graph pool/cache          17 个有序步骤，含：
  → community/centrality/AAAK/recency/lexical fusion             schema mine、decay、replay、
  → bounded 2-hop spread → temporal validity                     reconsolidation、summary、
  → hits + anti_hits + stale/supersede ranking                    entity/link、index rebuild 等
        │                                                             │
        └───────────────┬─────────────────────────────────────────────┘
                        ▼
             [session.py：L0/L1/L2/rich-club 注入]
             [MCP 工具返回 / CLI 返回 / brainview dashboard]

[原生 Rust 扩展：iai_mcp_native 单一 PyO3 cdylib]
  embed / graph / vec / hd / store / engine 五个 Python 子模块
  candle/BERT 嵌入、图/向量核、Lilli HD、lillibrain pager+B-tree+WAL、
  lilliengine SQL-shaped engine；Python 层通过 src/iai_mcp/*.py 组合业务语义。
```

# 项目定位

`iai-pme`（源码中的 Python 包名为 `iai_mcp`）是面向个人 AI 编码助手的本地长期记忆引擎。它通过 MCP-over-stdio 向宿主提供记忆工具，通过本地 hook 自动捕获会话，并在新会话/下一轮模型调用前注入相关记忆。设计中心是：

- 对话情景记录保留 `literal_surface` 原文，写入后不以摘要覆盖；
- 记忆同时有 episodic、semantic、procedural 等 tier，并以边和社区组织；
- 召回优先走本地向量/图/词法组合，不依赖热路径 LLM；
- 后台 daemon 在空闲窗口执行衰减、聚类、摘要、schema、索引和用户模型更新；
- 存储默认在 `~/.iai-mcp/`，记录敏感字段使用 AES-GCM 加密，MCP daemon 只暴露本机 IPC；
- 运行时由 Python 负责业务编排，Rust/PyO3 负责嵌入、图/向量核及 Lilli 存储引擎。

以上定位来自 `README.md`、`README_zh-CN.md`、`pyproject.toml`、`src/iai_mcp/`、`mcp-wrapper/` 和 `rust/` 的实际内容；此前的 `细探-iai.md` 分析结论已吸收进本文，不再作为独立事实源。

# 真实目录/分层与职责

根目录实际目录包括：`.claude-plugin/`、`.github/`、`bench/`、`crates/`、`desktop/`、`docs/`、`fixtures/`、`mcp-wrapper/`、`plugin/`、`rust/`、`scripts/`、`src/`、`tests/`。

## Python 业务层：`src/iai_mcp/`

- `src/iai_mcp/__init__.py`：包元数据、版本读取，以及 `MemoryRecord`、`MemoryHit`、`RecallResponse`、`EdgeUpdate`、`ReconsolidationReceipt`、`TIER_ENUM` 的公共导出。
- `src/iai_mcp/core/`：RPC 方法门面。`core/__init__.py` 的 `dispatch(store, method, params)` 把 `memory_recall`、`memory_capture`、`memory_contradict`、`memory_consolidate`、`memory_search`、`memory_temporal_recall`、`session_start_payload`、`brain_view`、profile、topology、events 等方法映射到业务实现；`core/_query_dispatch.py` 处理 schema/events 等只读查询。
- `src/iai_mcp/daemon/`：本地后台引擎。`daemon/__init__.py` 的 `main()` 打开独占 `MemoryStore`、进行 native/embedder warm-up、创建 `SocketServer` 并调度生命周期/睡眠任务；`daemon/__main__.py` 以 `asyncio.run(main())` 作为模块入口；`daemon/_watchdog.py`、`daemon/_boot_warmup.py` 提供资源和启动期控制。
- `src/iai_mcp/socket_server.py`：Python 侧 JSON-RPC 服务。校验 JSON-RPC 2.0 envelope，调用 `core.dispatch`，把未知方法、缺参、解析错误、embedder refusal 和内部错误转换为明确错误码；POSIX 使用 Unix socket，Windows 路径由 `src/iai_mcp/_ipc.py` 处理。
- `src/iai_mcp/cli/`：`iai-mcp` 运维/安装 CLI。包含 daemon、crypto、capture hooks、迁移、doctor、maintenance、topology、audit 等子命令的 parser 和实现。
- `src/iai_mcp/iai_cli.py`：`iai` 用户 CLI，源码 parser 实际注册 `recall`、`temporal-recall`、`upload`、`teach`、`search`、`watch`、`brain`、`capture`、`ask`、`status`、`last`、`lang`、`reflect` 等命令。
- `src/iai_mcp/capture.py`、`write.py`、`direct_write.py`、`capture_queue.py`、`deferred_drain*.py`、`write_queue.py`：捕获、去重、缓冲、异步/延期写入。`capture_turn()` 先做长度与 shield 检查，再嵌入正文，生成 idem/entity/tag/provenance，最后写入 store。
- `src/iai_mcp/retrieve.py`、`pipeline.py`、`semantic_recall.py`、`cue_router.py`、`runtime_graph_cache*.py`、`centrality_approx.py`、`richclub.py`、`graph.py`：召回候选、图构建/缓存、社区/中心度、2-hop spread、rank fusion、反命中和降级路径。
- `src/iai_mcp/session.py`、`foresight.py`、`handle.py`：会话启动包、按轮 delta、前摄包和紧凑句柄。`session.py` 定义 L0/L1/L2/rich-club 预算及 `assemble_session_start()`。
- `src/iai_mcp/types.py`：核心领域数据类和 schema/tier/HV 常量。
- `src/iai_mcp/store/`：`MemoryStore`、record/edge/event buffer、recency/exact/lexical index、读一致性和批处理。
- `src/iai_mcp/hippo/`：HippoDB/表/查询/加密列/事务/只读 ANN/降级直读的 SQLite-compatible 存储后端。`hippo/_table.py` 的 DDL 真实定义 `records`、`edges`、`events`、`budget_ledger`、`ratelimit_ledger`、`_hippo_meta`、`record_tags`。
- `src/iai_mcp/lillibrain/`：Python 镜像的 pager、B-tree、WAL、SQL lexer/parser/planner/executor 等存储实现。
- `src/iai_mcp/lilli/`：超维记忆与睡眠周期。`lilli/core/`、`lilli/tiers/`、`lilli/ops/` 提供 HV 运算、BSC/FHRR/sparse VSA、decay/Hebbian/consolidation；`lilli/cycle/sleep_pipeline/` 把各睡眠步骤拆成 sibling module。
- `src/iai_mcp/sleep.py`、`src/iai_mcp/lilli/cycle/sleep_pipeline/__init__.py`：睡眠巩固逻辑。前者包含连接图聚类、semantic summary 和 Tier-1 schema 持久化；后者的 `SleepPipeline` 负责顺序、WAL/进度、重试、interrupt、quarantine、事件与步骤绑定。
- `src/iai_mcp/mosaic.py`、`community.py`、`mosaic_policy.py`、`mosaic_lineage.py`：MOSAIC/社区检测及稳定社区身份策略。
- `src/iai_mcp/embed.py`：embedder registry、native/http provider、模型身份 stamp、维度/向量 generation guard；默认 `bge-small-en-v1.5` 384 维，HTTP 仅接受 loopback URL。
- `src/iai_mcp/crypto.py`、`shield.py`、`guard.py`、`identity_audit.py`：静态加密、输入注入风险门、预算/速率限制、身份/安全审计。
- `src/iai_mcp/ingest/`、`study.py`：文件解析、分块、`upload`/`teach` 入口；读取支持面和可选解析器由 `ingest/_parsers.py` 与 `pyproject.toml` 共同决定。
- `src/iai_mcp/doctor/`、`maintenance.py`、`migrate/`：健康检查、维护、schema/加密/re-embed/旧存储迁移。
- `src/iai_mcp/brainview.py`、`_deploy/brainview/`：本地 loopback dashboard 数据层和页面资源；读操作支持 daemon relay/只读快照，写操作走 capture spine。
- `src/iai_mcp/user_model.py`、`profile.py`、`lilli/profile/`：用户模型聚合、持久化、prefetch 和 profile knobs。

## Node/TypeScript MCP 层：`mcp-wrapper/`

- `mcp-wrapper/src/index.ts`：创建 MCP `Server`、绑定 `StdioServerTransport`，在 initialized 时请求 `session_start_payload`，注册 heartbeat/lifecycle，并暴露 `buildServer()`。
- `mcp-wrapper/src/tools.ts`：`TOOL_NAMES` 当前实际为 14 个：`memory_recall`、`memory_search`、`memory_recall_structural`、`memory_reinforce`、`memory_contradict`、`memory_capture`、`memory_consolidate`、`profile_get_set`、`curiosity_pending`、`schema_list`、`events_query`、`topology`、`episodes_recent`、`memory_temporal_recall`。同时实现 daemon down 时的 CLI/direct-store/bank fallback。
- `mcp-wrapper/src/bridge.ts`：`PythonCoreBridge` 维护 socket、pending RPC map、NDJSON framing、连接重试、解析错误阈值和 typed error code。
- `mcp-wrapper/src/ipc.ts`：POSIX socket 与 Windows loopback port/token handshake 的平台抽象。
- `mcp-wrapper/src/registry.ts`：hot tool 列表和 `clear_tool_uses_20250919` / `input_tokens=30000` context-editing 配置。
- `mcp-wrapper/src/caching.ts`、`lifecycle.ts`、`sickWarning.ts`：注入缓存断点、wrapper 生命周期、自愈/doctor 警告。
- `mcp-wrapper/test/`：Node test runner 下的 bridge、direct store、lifecycle、bank fallback、server instruction 等测试。

## Rust/native 层：`rust/` 与 `crates/`

- `rust/iai_mcp_native/`：唯一对 Python 发布的 `cdylib`/PyO3 wrapper。`src/lib.rs` 注册 `iai_mcp_native.embed`、`graph`、`vec`、`hd`、`store`、`engine` 六个属性/子模块，并写入 `sys.modules` 以支持 dotted import。
- `rust/iai_mcp_embed_core/`：candle、tokenizers、safetensors、hf-hub 等组成的本地 BERT/embed 核；macOS 可启用 Accelerate。
- `rust/iai_mcp_graph_core/`：纯 Rust 图算法层，依赖 petgraph、rustworkx-core、rayon、fixedbitset 等，不引入 embedder ML 栈。
- `rust/iai_mcp_vec_core/`：PyO3/NumPy 结合的向量索引核。
- `crates/lilli-hd/`：超维向量内核；`crates/lillibrain/`：pager/B-tree/WAL 存储；`crates/lilliengine/`：SQLite-shaped SQL engine；`crates/lilli-parity/`：跨实现 parity 支持。
- 根 `Cargo.toml` 是 Rust workspace；根 `deny.toml`、`rust-toolchain.toml` 及各 crate Cargo manifest 负责许可/工具链/feature/dependency 边界。

## 外围产品与验证层

- `plugin/`：Claude Code plugin wiring；`plugin/.mcp.json` 注册 `${CLAUDE_PLUGIN_ROOT}/bin/iai-pme-mcp`，`plugin/hooks/hooks.json` 将 SessionStart、UserPromptSubmit、Stop 接到四个 hook 脚本。
- `desktop/`：Tauri 原生窗口，启动/显示 `iai brain` dashboard；`desktop/src-tauri/Cargo.toml` 明确是独立 workspace，不加入根 PyO3 workspace。
- `bench/`：LongMemEval、矛盾纵向、token、延迟、内存、embedder 等基准入口与结果。
- `fixtures/`：golden/parity/HDC 等固定输入。
- `tests/`：Python 单元、集成、daemon/socket、schema、store、recall、sleep、迁移、安全、资源和 live/bench 门禁。
- `docs/`：`DEPLOYMENT.md`、`EMBEDDERS.md` 等运行部署/协议说明；`CONTRIBUTING.md` 规定源码构建、pytest、ruff 和相关 benchmark 规范。

# 核心数据流

## 1. 会话捕获与写入

1. 宿主触发 `SessionStart`/`UserPromptSubmit`/`Stop`，hook 脚本把转录或增量事件写入 session buffer/deferred capture 文件；会话内 capture hook 设计为文件 IO，不直接做 engine RPC。
2. daemon wake/drowsy 边或周期 drain 读取 buffer；`capture.capture_turn()` 做长度限制、`shield` verdict、正文 embed、entity anchor 提取。
3. 对会话型 episodic 记录先按 `idem:<sha256(...)>` 精确去重，再按 cosine near-duplicate gate（默认阈值由 capture 配置，README/工具描述明确为约 `cos>=0.95`）决定 reinforce 或 insert；`never_merge` 记录不被折叠。
4. 新的 `MemoryRecord` 写入 `records`，`literal_surface`、provenance 等敏感列由 `MemoryStore`/Hippo 加密；同步/异步 buffer 再把边和事件写入 `edges`/`events`。
5. 记录写入会刷新 recency/exact/lexical feed、runtime graph dirty state，并保留 `role`、`language`、tags、schema version、HV payload 等派生字段。

## 2. 召回与会话注入

1. MCP `memory_recall` 通过 `core.dispatch()` 进入 cue router；cue mode 可为 `concept` 或 `verbatim`，后者在 `retrieve.py`/`pipeline.py` 过滤非 episodic/pattern 记录。
2. cue vector 经过 `_valid_cue_vec()` 校验；缺失、零向量、错误维度或非 finite 时由服务端重新 embed。embedder identity mismatch/config refusal 不被伪装成普通降级。
3. 正常热路径由 runtime graph cache、ANN/HNSW 候选、exact cosine authority、AAAK/社区/centrality/recency 和可选 warm lexical BM25 lane 联合生成候选；低置信只做一次、上限 2000 的 ANN widening，不做无界全库扫描。
4. graph 通过 seed、bounded 2-hop neighborhood、rich-club 和 lexical candidates 扩展；最终 rank 组合 cosine、AAAK、degree、age、community、结构 HV、profile gain 等信号。
5. 通过 contradiction edges 计算 `valid_from`/`valid_to`；过期记录默认 stale downweight，supersede cap 保证当前纠正版本在 served window 中不被旧版本压过；`anti_hits` 同时承载低相似度基线和 contradicts-edge 邻居。
6. `session.assemble_session_start()` 以 L0 identity、L1 pinned/high-detail、L2 community、rich-club 组成 payload，并记录 `session_started` event。minimal/standard/deep `wake_depth` 改变内容密度，per-turn 通过 `render_session_delta()` 限制增量而非重发完整简报。
7. daemon 不可达时，Python CLI 与 TypeScript wrapper 对 recall/temporal/search/recency/capture 走 direct-store 或 bank fallback；`README.md` 和 `src/iai_mcp/hippo/_recall.py` 明确 recall 不以 daemon 在线为前提。

## 3. 矛盾与纵向修订

`retrieve.contradict()` 读取原记录，若新 fact 的 embedding 缺失则现场生成；构造新 `MemoryRecord`，写入后用实际 survivor id 建立 `contradicts` edge，失效 temporal cache。旧记录不删除，查询既可发现当前事实，也可在 historical-verbatim 意图下找回旧 wording。`tests/test_contradict_dedup_interplay.py` 进一步验证：纠正文本若被 dedup 到已有 survivor，edge 必须指向 survivor；若折叠回被纠正原记录，则拒绝形成自矛盾环。

## 4. 空闲睡眠巩固

`daemon.main()` 启动 `SocketServer` 与后台调度。`SleepPipeline` 在 lifecycle state 中保存 `last_completed_index`、attempt 和 last error，按 `_STEP_ORDER` 执行 17 个步骤。每步有 started/completed event、RSS snapshot 和 interrupt check；失败按 attempt 累加，连续三次进入 quarantine；中断或重启后从持久进度恢复。

巩固相关步骤从 records/edges 读取活跃数据，进行 Hebbian/连接图聚类、MOSAIC/社区划分、semantic summary、schema mine、FSRS 风格 decay、replay/reconsolidation、entity link、user model、recall index rebuild 等。`sleep.py` 对 oversize cluster、summary coverage、per-cycle summary cap 和边批量写入做边界控制。需要 LLM 的步骤通过 budget/rate ledger 和 `should_call_llm()` 门控；README/代码描述为最多一次 `claude -p` 路径，不是独立 API-key SDK 热路径。

# 关键类/函数/数据模型及相对路径

## 数据模型

- `src/iai_mcp/types.py:MemoryRecord`：UUID、tier、原文 `literal_surface`、AAAK index、embedding、community/centrality、detail/pinned、stability/difficulty/review、decay/merge flags、provenance、timestamps、language/tags、`s5_trust_score`、profile modulation、schema version、10000-dimension packed `structure_hv`/payload、HV tier、pending flag、role。`__post_init__()` 强制 tier、language、trust range、schema version、HV byte shape，并把 `detail_level >= 3` 转成 `never_decay=True`。
- `src/iai_mcp/types.py:MemoryHit`：记录 id、score、reason、原文、adjacent suggestions、`valid_from`/`valid_to`、session/captured/community metadata。
- `src/iai_mcp/types.py:RecallResponse`：`hits`、`anti_hits`、activation trace、budget、hints、cue mode、patterns、ANN-used flag。
- `src/iai_mcp/types.py:EdgeUpdate`：Hebbian boost 的 pair 与新权重。
- `src/iai_mcp/types.py:ReconsolidationReceipt`：矛盾修订的 original/new id、edge type 和 timestamp。
- `src/iai_mcp/store/__init__.py`：`records`、`edges`、`events`、budget/rate ledger 表名；`EDGE_TYPES` 允许 `hebbian`、`contradicts`、`consolidated_from`、`schema_instance_of`、`temporal_next`、`invariant_anchor`、`curiosity_bridge`、`profile_modulates`、`hebbian_structure`、`pattern_separation_seed`、`hebbian_cluster_replay`、`entity_shared`。
- `src/iai_mcp/hippo/_table.py`：真实 records/edges/events DDL。records 还含 `tombstoned_at`、`live`、`embedding_pending`、HV/role/room/drawer/wing、schema/identity 支持字段；edges 以 `(src,dst,edge_type)` 为主键；events 按 kind/ts/session 建索引。

## 关键入口与算法

- `src/iai_mcp/capture.py:capture_turn()`：共享 capture spine、shield、正文 embed、精确/近重复去重、tag/provenance、insert。
- `src/iai_mcp/retrieve.py:recall()`：基础 cosine recall、provenance、anti-hit 基线、temporal validity、stale downweight；`retrieve.contradict()`：新记录+矛盾边修订。
- `src/iai_mcp/pipeline.py:recall_for_response()` 与 `_recall_core()`：图/社区/中心度/AAAK/lexical/结构 HV 混合排序，候选 widening 与 2-hop spread。
- `src/iai_mcp/store/_store.py:MemoryStore`：存储门面、加密 key、HippoDB、迁移、缓存、recency/exact/lexical feed、record/edge API。
- `src/iai_mcp/hippo/_db.py:HippoDB` 与 `src/iai_mcp/hippo/_table.py`：事务、锁、只读池、表/SQL 兼容层、加密字段编解码。
- `src/iai_mcp/core/__init__.py:dispatch()`：Python RPC 方法分发、profile hydration、recall/authority/fallback 组合和 wire serialization。
- `src/iai_mcp/socket_server.py:SocketServer.handle()/serve()`：IPC server、JSON-RPC envelope、并发 to-thread dispatch 和错误码。
- `src/iai_mcp/session.py:assemble_session_start()`、`render_session_delta()`：预算约束的 session context composer。
- `src/iai_mcp/lilli/cycle/sleep_pipeline/__init__.py:SleepPipeline.run()/force_run()`：睡眠步骤顺序、进度、恢复、quarantine 和事件。
- `src/iai_mcp/sleep.py:run_heavy_consolidation()`、`_process_cluster_summaries()`：decay、cluster、semantic summary 和 schema persistence。
- `src/iai_mcp/embed.py:Embedder`、`embedder_for_store()`、`effective_model_identity()`：native/http provider、模型 registry、维度与向量 generation guard。
- `rust/iai_mcp_native/src/lib.rs:iai_mcp_native()`：PyO3 子模块注册；`setup.py:_BuildWithWrapper`：wheel 构建时编译/打包 TS wrapper 和 Rust extension/stubs。
- `mcp-wrapper/src/index.ts:buildServer()/main()`、`mcp-wrapper/src/tools.ts:handleToolCall()`、`mcp-wrapper/src/bridge.ts:PythonCoreBridge`：MCP/SDK/IPC 的 TypeScript 入口。

# API/CLI/SDK入口

## MCP API

当前源码 `mcp-wrapper/src/tools.ts` 定义 14 个 hot MCP tools，参数/返回 schema 与 `src/iai_mcp/core/__init__.py` 的 dispatch 分支共同构成 wire contract。主要工具是：

- 读：`memory_recall`、`memory_search`、`memory_recall_structural`、`memory_temporal_recall`、`curiosity_pending`、`schema_list`、`events_query`、`topology`、`episodes_recent`；
- 写/控制：`memory_capture`、`memory_contradict`、`memory_reinforce`、`memory_consolidate`、`profile_get_set`。

MCP server 是 `mcp-wrapper/src/index.ts` 的 `buildServer()`；默认通过 `StdioServerTransport` 启动。当前工具 schema 与 Python 参数的静态一致性由 `tests/test_tool_schema_python_parity.py` 检查。

## Python RPC/daemon API

- `src/iai_mcp/socket_server.py`：JSON-RPC 2.0 over local IPC；服务端调用 `core.dispatch()`。
- `src/iai_mcp/core/__init__.py`：除 MCP tools 外还承载 `brain_view`、`status_light`、`session_start_payload`、`session_refresh_if_stale`、`profile_get/set`、`audit_query`、`detect_drift`、`shield_check`、`rss_stats` 等内部/诊断方法。
- POSIX endpoint 默认 `~/.iai-mcp/.daemon.sock`；`mcp-wrapper/src/ipc.ts` 与 `src/iai_mcp/_ipc.py` 对 Windows 使用 loopback port 和 token 文件。

## CLI

`pyproject.toml` 的 `[project.scripts]` 真实入口为：

- `iai-mcp-core = iai_mcp.core:main`；
- `iai-mcp = iai_mcp.cli:main`，维护/部署/诊断/迁移/crypto/daemon/capture-hooks 等；
- `iai = iai_mcp.iai_cli:main`，用户侧 recall/search/capture/teach/upload/ask/status/last/brain 等。

`src/iai_mcp/brainview.py` 提供 loopback HTTP dashboard 的数据服务；`desktop/src-tauri` 的 Tauri app 是它的原生窗口，而不是另一个记忆后端。

## Plugin/desktop

- `plugin/.mcp.json`：Claude Code plugin 的 MCP command wiring。
- `plugin/hooks/hooks.json`：SessionStart、UserPromptSubmit、Stop 的 hook wiring。
- `desktop/README.md` 与 `desktop/src-tauri/`：启动 `iai brain`、展示 dashboard；窗口关闭只停止由 app 启动的 dashboard，不停止 sleep daemon。

## SDK边界

仓库没有独立的 Python/TypeScript“客户端 SDK”目录。可复用编程入口是 Python `iai_mcp` 导出模型、`MemoryStore`/`core.dispatch`，以及 TypeScript `buildServer`、`PythonCoreBridge`、tool schemas。外部宿主应优先使用 MCP stdio contract，而不是直接依赖内部 Python 模块。

# 技术栈和依赖

## Python

- Python `>=3.11,<3.13`；setuptools/setuptools-rust 构建。
- 运行依赖（`pyproject.toml`）：`numpy`、`scipy`、`numba`、`tiktoken`、`cryptography`、`keyring`、`cachetools`、`psutil`、`pandas`、`zstandard`、`pypdf`、`setproctitle`。
- `pypdf` 在 `ingest/_parsers.py` 的 PDF 分支惰性导入，但当前项目 metadata 将其列在主 dependencies；不能把它当作未声明依赖。
- dev 依赖：pytest、pytest-timeout、pytest-xdist、reportlab、defusedxml、ruff、`networkx==3.3`、hypothesis-networkx、scikit-learn；`networkx` 是开发/测试 oracle 和 legacy backend，不是主安装的社区检测依赖。
- migration extra：`lancedb`，只用于旧 LanceDB → Hippo 迁移。

## TypeScript/Node

`mcp-wrapper/package.json` 要求 Node `>=18`；生产依赖是 `@modelcontextprotocol/sdk` 和 `zod`；构建/测试依赖是 TypeScript、esbuild、tsx、Node types。`npm run build` 生成 `dist`，`npm run bundle` 生成 self-contained `dist-bundle/index.js`。`setup.py` 在 wheel 构建阶段将 bundle staged 到 `iai_mcp/_wrapper/`，不应假设 wheel 用户另行拥有 npm modules。

## Rust

根 `Cargo.toml` workspace 使用 edition 2021；workspace 依赖包括 `candle-core`/`candle-nn`、`safetensors`、`tokenizers`、`hf-hub`、PyO3、NumPy、serde、serde_json、thiserror、可选 Accelerate。图 crate 还使用 petgraph、rustworkx-core、rayon、fixedbitset、rand；vec crate 使用 rayon、crc32fast。根 `setup.py` 通过 `setuptools_rust.RustExtension` 编译 release `iai_mcp_native`，macOS 添加 `accelerate` feature。

## Desktop

`desktop/src-tauri/Cargo.toml` 是独立 Tauri 2 crate，使用 `tauri`/`tauri-build`，不加入根 PyO3 workspace；其角色是 dashboard UI shell，不是核心存储层。

# 架构判断与未确认项

## 架构判断

1. **这是三进程/多层职责分离，而不是单一 MCP 脚本。** Node wrapper 隔离宿主协议，Python daemon 负责业务和生命周期，Rust extension 负责性能关键核；dashboard/CLI 又能在 daemon down 时 direct-read，形成 availability fallback。
2. **存储采用“单写者 + 只读旁路 + 派生索引”的 CQRS 倾向。** daemon 以 EXCLUSIVE `MemoryStore` 持有主写路径；CLI/brainview 使用 SHARED/read-only、非持久 index 或 direct SQL；HNSW、exact/lexical、runtime graph 都是可重建派生数据。
3. **数据正确性优先于摘要压缩。** `MemoryRecord.literal_surface` 是事实载体；纠错通过新 record + `contradicts` edge，temporal validity、stale downweight 和 supersede cap 共同处理“现在”和“历史”两个检索意图。
4. **召回是混合检索，不是纯向量检索。** 当前路径将 ANN/exact cosine 与图邻域、community/centrality、AAAK、recency、条件式 BM25、结构 HV 和 profile modulation 组合，并把 anti-hit/trace/degraded/source 信息显式返回。
5. **后台任务具备可恢复工作流特征。** `SleepPipeline` 的 17 个 step、持久进度、三击 quarantine、interrupt/defer、step event 和 memory relief 使巩固更像可恢复 job，而非一次性 cron。
6. **资源和错误边界是设计的一部分。** graph/community 重计算可放 spawn child；recall concurrency、widening、socket line、上传大小、dashboard node/edge、sleep chunk 等均有硬上限；embedder identity mismatch 选择 fail-loud，普通热路径故障多数选择 degrade/fallback。
7. **协议契约有自动 parity 防线。** Python dispatch、TypeScript tool schemas、wrapper bundle 由专门测试做静态或运行时检查；`tests/test_wrapper_bundle_self_contained.py` 明确防止发布一个依赖裸 npm import 的不可运行 wheel wrapper。

## 未确认项/需继续核实

- 本项目内没有 `AGENTS.md` 或明确架构设计文档，因此本文件的分层判断来自源码、manifest、README/docs 和测试；没有隐藏的维护规则可交叉验证。
- 本次按要求没有安装依赖、启动服务或运行 pytest/npm/cargo 测试；测试结论只记录“实际阅读了测试”，不宣称当前 checkout 全绿。
- `README.md` 多处历史文案称 MCP 工具为 15 个，但当前 `mcp-wrapper/src/tools.ts:TOOL_NAMES` 实际列出 14 个；`tests/test_tool_schema_python_parity.py` 的工具清单也较旧，发布时应由维护者确认哪一个才是正式版本契约。
- `README_zh-CN.md` 仍描述“三个钩子”，而英文 README、`plugin/hooks/hooks.json` 和 `_deploy/hooks/` 已包含 per-turn recall 等四类 hook；中文文档同步状态未确认。
- `README.md` 对默认存储/引擎、Rust native 和 benchmark 的叙述与当前源码总体一致，但其 benchmark 数值是历史结果，本文件未执行 benchmark，不能把这些数字当作本次环境测量。
- `rust/iai_mcp_graph_core` manifest 的注释称算法层当前是 wiring probe；Python 侧 `community.py`/`mosaic.py`/`retrieve.py` 同时存在成熟的业务图逻辑，Rust graph crate 到 Python recall 主路径的实际覆盖边界需要通过构建/调用图进一步确认，本任务未运行 native build。
- `dist/`/`dist-bundle/` 是否为当前源码重新构建产物未作构建验证；`tests/test_wrapper_bundle_self_contained.py` 对 bundle 不存在时会 skip，因此“发布 bundle 自包含”不能仅凭该测试文件推断本 checkout 已满足。
- 当前 `pyproject.toml` 同时允许 `IAI_MCP_EMBED_PROVIDER=http` 和 native model registry；HTTP provider 的服务端实现不在本仓库内，只有协议/校验客户端，因此外部 provider 的可用性和模型质量不属于本源码架构已验证范围。

# 实际阅读范围与验证边界

本次实际读取了：`README.md`、`README_zh-CN.md`、`CONTRIBUTING.md`、`BENCHMARKS.md`、`docs/DEPLOYMENT.md`、`docs/EMBEDDERS.md`、`plugin/README.md`、`plugin/.mcp.json`、`plugin/hooks/hooks.json`、`desktop/README.md`、`pyproject.toml`、`setup.py`、根 `Cargo.toml`、native/graph/embed/vec Cargo manifests、`rust/iai_mcp_native/src/lib.rs`；核心入口/数据模型/存储/召回/捕获/睡眠/session/embedder/IPC 等源码；以及 `tests/test_store.py`、`test_schema_v2.py`、`test_recall_verbatim_mode.py`、`test_recall_rank_fusion.py`、`test_contradict_dedup_interplay.py`、`test_socket_server_dispatch.py`、`test_tool_schema_python_parity.py`、`test_sleep_pipeline.py`、`test_user_model.py`、`test_wrapper_bundle_self_contained.py`、`mcp-wrapper/test/bridge.test.ts` 等测试。

本文件已吸收此前 `细探-iai.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

只读目录盘点得到：`src/` 下 252 个 Python 文件、`mcp-wrapper/` 下 14 个 TypeScript 文件、`tests/` 下 744 个 Python 测试文件、`mcp-wrapper/test/` 下 6 个 TypeScript 测试文件。未安装依赖、未运行服务或测试、未修改已有源码、未提交 Git；本次唯一写入文件是项目根的 `ARCHITECTURE.md`。

---

# 第三轮：通用底座映射与归属裁决

本轮不是把本项目改造成平台代码，而是把当前 checkout 已经实现的证据链、投影链、召回链、上下文链、模型调用链和资源/任务边界映射到“支持库—记忆模块—运行核心—统一网关”的通用底座。下面的“应归”是底座归属建议，不等于本项目已经接入该底座；“现状”只引用本项目源码事实。

## 1. 研究现场与证据等级

- 目标根目录：`~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/01_个人模型与数字分身/iai-personal-memory-engine`。
- 项目身份：`iai-personal-memory-engine`，源码 Python 包为 `iai_mcp`；下载目录记录的基线为仓库 `CodeAbra/iai-personal-memory-engine`、`main`、提交 `91887e085964dda17edbff4ad77854b82da82062`。
- 旧细探：目标目录内本轮未发现独立 `细探-*.md` 文件；现有 `ARCHITECTURE.md` 已声明此前 `细探-iai.md` 的结论已吸收。本轮不删除、不重建旧细探，也不把聊天回执当事实源。
- MCP 开工核对：首次 `project_context` 返回的是**错误绑定**的项目 `华世王镞_v3`、根目录 `~/Documents/Agent/PHP/华世王镞_v3`，不是本目标；该返回没有提供本目标的开工 id，不能冒充本项目开工证据。
- 代码图：对目标根目录调用 `codegraph_explore` 的真实结果是“未索引，未找到 `.codegraph/`，不能查询”；以下源码路径、函数和行号均来自本地只读读取，不来自代码图。不能把错误项目的代码图摘要迁移到本项目。
- 本轮验证边界：只修改本文件；未安装依赖、未启动 daemon、未调用外部模型、未运行 pytest/npm/cargo，因此下面的“已实现”是静态源码事实，“已验证”仍须按最后的验证表区分。

## 2. 一条真实的端到端链路

```text
宿主 hook / MCP 客户端 / CLI
  → L3 统一网关：mcp-wrapper/src/index.ts + tools.ts
  → L3 Python IPC 网关：mcp-wrapper/src/bridge.ts
  → L2 运行核心：socket_server.py → core.dispatch() → daemon 生命周期/前台优先级
  → L1 记忆模块：capture / retrieve / pipeline / session / lilli sleep steps
  → L0 支持库：embed.py + iai_mcp_native、MemoryStore/HippoDB、crypto、原子文件/队列、图/向量核
  → 原始事实库：records.literal_surface/provenance、edges、events、capture pending 文件
  → 派生投影：embedding/AAAK/tags、community/centrality/HV、ANN/exact/lexical/runtime graph、profile、user model、session payload
  → L2 任务与资源治理：SleepPipeline、生命周期状态、进度/WAL、预算、锁、取消/恢复
  → L3 统一结果/JSON-RPC/MCP 返回
```

捕获 hook 的正常路径不是 hook 直接 RPC：`plugin/hooks/hooks.json` 将 SessionStart、UserPromptSubmit、Stop 接到脚本；脚本落盘 session/deferred 文件，由 `capture.py:drain_deferred_captures()` 认领后调用 `capture_turn()`。这是一条“文件先行、daemon 后排空”的链。daemon 不可用时，`direct_write.py:write_turn_direct()` 直接以 `HippoDB(AccessMode.SHARED)` 写入，这保证可用性但形成了第二个写入口，属于本轮明确的底座缺口，不应在平台复制为第二套写内核。

## 3. 原始证据、派生状态与唯一 owner

“原始证据不可被派生结果覆盖”是本项目最值得吸收的原则；“每一类数据只有一个权威写 owner”是接入通用底座时必须补强的原则。

| 数据/动作 | 本项目真实 owner 与写法 | 性质 | 通用底座归属裁决 |
|---|---|---|---|
| hook 原始转录/增量 | `_deploy/hooks/*.sh`、`capture_queue.py:CaptureQueue.append()`、deferred/live JSONL 文件；原子临时文件写入后 `os.replace`，队列有 ULID、`.lock`、overflow audit | 原始证据入口 | **支持库**提供原子文件/队列和锁；**记忆模块**拥有证据 envelope 语义；网关只接收，不拥有原文 |
| 会话原文 | `capture.py:capture_turn()` 构造 `MemoryRecord.literal_surface`；长度截断前后、`never_merge`、role/session/source_uuid/provenance 进入记录 | 原始事实 | **记忆模块**唯一规范写 owner；`MemoryStore.insert()`/record buffer 是唯一正式持久入口 |
| 事实来源链 | `MemoryRecord.provenance`；`events.write_event(... source_ids=...)`；`insight.py` 要求 source id 能从 store 读回才允许铸造 insight | 原始证据关联/审计证据 | **记忆模块**定义 provenance/lineage 契约；**支持库**只负责加密事务与原子写入；禁止模型输出自行声明来源 |
| 事件审计 | `events.py:write_event()` 写 `events`，data/source_ids 可加密；可 buffered，`flush_event_buffer()` 后落库 | 运行事实/审计事实 | **运行核心**拥有运行事件/任务事件；记忆业务事件仍由记忆模块提交，不能由网关私写表 |
| 记录去重/合并 | `capture.py` 的 `idem:<sha256>` 精确去重、`_CAPTURE_DEDUP_LOCK` 串行 check-then-insert、cosine gate；`never_merge` 绕过折叠 | 派生判定，但改变持久写结果 | **记忆模块** owner；支持库只提供 hash/cosine/事务原子能力 |
| embedding | `embed.py:Embedder` 选择 native/http、校验维度/finite/model identity；capture 写入 embedding，pending row 可延期 | 派生投影 | **支持库** owner（模型适配、维度、identity、错误码）；记忆模块只请求 document/query embedding |
| AAAK、tags、role/live | `capture.py`/`MemoryStore._derive_role()`/`_derive_live()`；`tags_json`、`aaak_index` 等随记录写入 | 可重算派生列 | **记忆模块**定义投影；单一派生函数；支持库只存储，不能另造字段推导 |
| edges | `retrieve.contradict()` 写新 record 后以 survivor id 写 `contradicts`；reinforce/coactivation/consolidation 写 Hebbian/derived edges；`_buffers.flush_edge_buffer()` 批量 merge | 关系事实+派生关系 | **记忆模块**拥有 edge 语义/lineage；**支持库**拥有批量 merge、事务和恢复 |
| ANN/exact/lexical/runtime graph | `MemoryStore` 写入后 feed/invalidate；`_exact_index`、recency buffer、lexical index、runtime graph cache 可重建，RO pool 有 generation/staleness | 派生索引/缓存 | **记忆模块**定义一致性与可接受滞后；**支持库**提供向量索引、只读连接池、缓存 primitive；运行核心负责后台 rebuild 调度 |
| temporal validity/stale/supersede | `retrieve` 从 `contradicts` edges 和时间戳构造 weak-key cache，并在写入后 invalidate；serve 时 downweight | 派生检索状态 | **记忆模块** owner；不得回写原始 literal 或删除旧事实 |
| profile knobs/posterior/pins | `lilli/profile/persistence.py` 将加密 blob 写 `_hippo_meta(profile_state)`；`profile_set()` 用户设置后持久化，`bayesian_update()` 改 live state/posterior | 用户声明+派生状态混合 | 用户显式 knob 是受保护事实；posterior/modulation 是派生状态。**记忆模块**定义，**支持库**加密 KV/事务；只有 daemon 可写 profile blob，读取者不写默认值 |
| user model | `user_model.py:UserModelAggregator.aggregate()` 从 records/events 聚合；`_user_model.py` 睡眠步骤调用 `save(model)`，另写 `~/.iai-mcp` JSON，使用 temp+fsync+replace | 派生画像 | **记忆模块**拥有画像投影；现状的独立 JSON owner 分裂，底座应升级为统一加密 projection store，原始 records/events 永不被画像覆盖 |
| session payload/L0-L2 | `session.py:assemble_session_start()` 从记录、community assignment、rich-club、pending live events 组装；`render_session_delta()` 依据 watermark 只发增量 | 请求时派生上下文 | **记忆模块**拥有语义/预算；**运行核心**拥有缓存、watermark 生命周期；网关只传输 |
| sleep progress/lifecycle/quarantine | `lifecycle_state.py`、`daemon_state.py` 原子 JSON；`SleepPipeline._save_progress()` 记录 step/attempt/error，三次失败 quarantine，完成清 progress | 运行状态 | **运行核心**唯一 owner；不应由记忆模块直接管理进程/调度状态 |
| MCP/RPC wire result | `socket_server.py` 校验 envelope、`core.dispatch()` 序列化；`bridge.ts` pending map/reconnect；`tools.ts` schemas | 对外契约/传输状态 | **网关**唯一 owner；网关不做第二次召回、写库、模型调用或错误码翻译 |

明确规则：`literal_surface`、输入 provenance、source UUID、原始事件和失败证据是 L0/L1 的事实面；embedding、AAAK、社区、画像、摘要、session payload、索引、cache、预算统计和健康状态是派生面。派生面失败时可以降级、重建或标记 stale，不能反向覆盖原始事实；模型/摘要没有可验证 source ids 时不得成为新的语义事实。

## 4. 六类能力的底座映射

### 4.1 证据写入：归“记忆模块 + 支持库”，不归网关

**当前链：** `capture_turn()` → shield/长度校验 → document embedding → idem/near-dup → `MemoryStore.insert()` → record/edge/event buffer → `HippoDB`。`events.write_event()` 可以同步或 buffered；`MemoryStore.close()` 先尽力 flush event/record/edge，再停 async/provenance/reinforce queue，最后关 DB。

**应归属：**

1. 支持库提供 `EvidenceEnvelope` 所需的原子文件、hash/idempotency、加密字段、批量事务、fsync/atomic replace、dead-letter/quarantine。
2. 记忆模块拥有 `MemoryRecord`、tier、literal/provenance、dedup、contradiction、edge/event 语义和写入顺序。
3. 运行核心只负责在何时排空、预算/资源/重试/恢复，以及崩溃后的未认领文件回收。
4. 网关只调用 `memory_capture`/RPC，不得直接拼 SQL、直接生成 record 或自行解释 `idem`。

**现状缺口：** `direct_write.py` 在 daemon down 时直接打开 HippoDB、自己实现 SQL insert、sidecar 和 working-tier feed；它是可用性 fallback 的真实证据，但破坏“一个写 owner、一条写链”。底座候选是把它收敛为支持库的离线 spool writer，之后仍由同一个记忆模块 commit adapter 消费；在未完成迁移前必须标记为隔离兼容入口，不能再新增同类旁路。

### 4.2 画像/状态投影：归“记忆模块”，运行状态另归“运行核心”

- 画像语义：`UserModelAggregator` 用 records/community/events 生成 topics/tool/hour；`profile` 用 knob registry、Bayesian posterior、record modulation 影响召回/上下文。它们都依赖证据，但都不是原始证据 owner。
- 画像持久化：profile 已在 `_hippo_meta` 加密 blob 中由 daemon 单写；user model 仍是独立 JSON。平台应把画像投影注册为可重算 projection，记录 `source_watermark`、算法/模型 identity、更新时间和失败原因。
- 状态语义：`daemon_state` 的 scheduler pause/force-rem/pending digest、`lifecycle_state` 的 WAKE/DROWSY/SLEEP/HIBERNATION、sleep progress/quarantine、wrapper seq 属于运行核心，不能混进画像。
- 网关的 `profile_get_set` 是契约入口，不是 owner；`core.ensure_profile_hydrated()` 是读取 hydration，不应在读请求中隐式写默认 blob。

### 4.3 检索：归“记忆模块”，索引实现归支持库，重建调度归运行核心

`retrieve.recall()` 先校验 cue vector，缺失/零/错维/非 finite 时按条件 server-side re-embed；`pipeline.recall_for_response()` 组合 ANN、exact authority、graph hops、community/centrality/AAAK/recency/lexical/structure-HV、temporal validity、stale/supersede 和 profile modulation。`core` 在 crisis/sleep/boot-window 下选择正常、fallback 或 consolidation-independent degraded lane；`socket_server` 只把异常转 wire error。

- 记忆模块拥有召回意图（verbatim/concept）、候选集合语义、排序、anti_hits、activation trace、provenance-used、temporal/contradiction 规则和预算内结果。
- 支持库拥有 ANN/HNSW、exact cosine、lexical postings、vector math、RO snapshot pool、加密读、SQL 参数化和有限重试。
- 运行核心拥有 warm-up、单飞锁、后台 graph/index rebuild、前台优先级、sleep/crisis gate、资源预算；不得重写一套“运行核心召回”。
- 网关只暴露一个 `memory_recall` 规范入口；CLI/direct-store/bank fallback 必须调用同一记忆模块契约，不能各自排序一套答案。

### 4.4 上下文：归“记忆模块的 composer”，生命周期/缓存归运行核心

`session.py` 的 L0 identity、L1 pinned/high-detail、L2 community、rich-club、recent thread、pending live events 和 `render_session_delta()` 是语义装配；`SESSION_START_CACHE_MAX_CHARS=10000`、L0/L1/L2/rich-club/token ceilings 是上下文契约。`mcp-wrapper/src/index.ts` 在 initialized 后调用 `session_start_payload`，`caching.ts` 才把它变成宿主 system prompt/cache breakpoint。

唯一链应为：`记忆模块 assemble → 运行核心按会话/watermark/TTL 管理 → 网关一次注入`。wrapper 可以做 transport/context-editing 适配，但不得自行从文件/DB 重建第二份 L0-L2。跨项目/跨 session 的 recent thread 必须保留 provenance origin label，避免把其他 session 当当前身份。

### 4.5 模型调用：归“支持库 provider adapter + 运行核心监督”，不归记忆模块算法

当前热路径 embedding 不是 LLM：`Embedder` native Rust 或 loopback HTTP，带 model/dim/prefix/identity guard。睡眠 DMN/overnight insight 才通过 `reflection_provider.py` 选择 `claude`/`codex`/`gemini`，以受限子进程、allow-list 环境、scratch cwd、stdin prompt、输出上限调用；Claude 另有 `claude_cli.py` 的 credentials、budget、`--bare`/禁 hooks、JSON 解析和 billing tripwire。

归属裁决：

- 支持库：模型/embedding provider 的配置解析、身份 stamp、输入输出 schema、provider CLI/HTTP/native adapter、敏感环境隔离、token/cost 计量和稳定错误码。
- 记忆模块：只定义“为何调用、输入哪些证据、source_ids 如何形成、输出何时可铸造成 semantic/procedural record”；`insight.py` 已经执行“无可读 source_ids 不 mint、无 embedding 不存”的正确门禁。
- 运行核心：给模型调用分配任务、deadline、并发槽、取消/超时、子进程组回收、重试/熔断、预算和证据事件；不能把 `asyncio.create_subprocess_exec` 散落到各业务步骤。
- 网关：只传递用户命令/结果和 provider refusal，不持有 API key，不直接调用 vendor CLI。

### 4.6 任务与存储资源：任务归运行核心，存储 primitive 归支持库

本项目没有独立通用 task registry；任务由 daemon tick、`asyncio.to_thread`、SleepPipeline 17 step、queue drain、background index worker 和外部 CLI 子进程组合出来。`SleepPipeline` 以 `_STEP_ORDER`、持久 progress、attempt、last_error、interrupt check、三击 quarantine、heavy-step memory relief 构成可恢复工作流，但还不是平台统一任务契约。

- 支持库：`HippoDB`/`MemoryStore` 事务、WAL、加密列、RO pool、连接/游标、索引、文件锁、临时文件、进程组、stdio/socket、向量/图/native handles。
- 记忆模块：声明每个 job 的业务读写集，例如 capture 写 records/events，consolidation 写 edges/profile/index projection，recall 只读并可追加 retrieval-used/provenance event。
- 运行核心：任务 id/attempt/deadline/cancel token/lease/heartbeat、队列、优先级、前台让行、资源预算、进程崩溃恢复、任务事件和结果持久化。
- 网关：把 MCP/RPC 请求转换成命令或查询；长任务返回规范 task receipt/status，不在 socket handler 内隐式启动不可追踪线程。

## 5. 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码行为 | 事实是否保留 | 底座要求/剩余风险 |
|---|---|---|---|
| 非法 tier、过短、过长、shield `HARD_BLOCK` | `capture_turn()` 返回 skipped；过长截断；shield 不可用返回 `UNAVAILABLE` 并写 telemetry | 原始输入未必进入 records；hook 文件仍可留待审计 | 网关要区分 rejected/skipped/unavailable；不得把 skip 伪装成成功；保留拒绝事件与原始文件策略 |
| capture embed/native 失败 | 写 `TELEMETRY_EMBED_NATIVE_FAILURE` 后抛 `NativeError` | pending/deferred 文件不应被成功删除；direct path 可写 `embedding_pending` | 运行核心必须以 ack 后删除 spool；失败可重试且有上限；provider refusal 与 transient failure 分码 |
| record buffer 瞬态写错 | `flush_record_buffer()` 保留 buffer，下一次重试；完整性错误逐行隔离，写 `.record-quarantine` 和 `record_quarantined` | 可恢复 JSONL 保留完整 row/bytes | 吸收“clear-after-terminal”；补统一 dead-letter owner/恢复任务；检查 event flush 失败当前是否会丢 pending |
| capture 文件 crash loop | `.processing-{pid}`/`.crash-*`/`.failed-*` 递增；超限移 `.quarantine` 并写事件/日志 | 文件保留，超过上限进入 quarantine | 运行核心回收死亡 pid marker；任务 receipt 要能指向文件/attempt；不能无界重试 |
| 队列溢出 | `CaptureQueue.prune_oldest()` 删除最老 pending，写 `.overflow-audit.log` | 只保留丢弃审计，不保留正文 | 这是明确数据损失策略；平台应要求容量预算、背压或人工确认，不能默认宣称无损 |
| 召回向量缺失/零/错维 | `retrieve.recall()` 可重新 embed；identity/config refusal fail-loud；普通异常多数降级为 caller vector/备用 lane | 不写坏 record；retrieval event 尽力写 | 统一 `EMBEDDER_REFUSAL`/degraded result；不得把零向量召回当正常答案 |
| 存储完整性/连接故障 | buffer 重试或 quarantine；close 尽力 flush 后 `db.close()`；RO pool fence 有界 reopen，耗尽才回 writer path | 视路径而定，quarantine 可恢复 | 运行核心要有存储健康/残留检查；任何“已写”必须读回确认 |
| sleep step 失败 | 保存 `last_completed_index/attempt/last_error`；三次失败进入 TTL quarantine；之后自动恢复或 force_run | records 已写部分可能存在，进度和事件留存 | step 必须幂等或有 transaction boundary；重启从 step 恢复，不能重跑不可逆 side effect |
| sleep 主动取消/用户唤醒 | 每步/分块 `interrupt_check`；保存 deferred progress，返回 `interrupted=True` | 已提交步骤保留；当前未完成步骤不应宣称完成 | 这是合作式取消，不是统一 cancellation token；需平台 task owner 统一取消、排空、join |
| 模型调用超时 | Claude/reflection 子进程 `wait_for` 后 terminate→kill；返回 `timeout`，不 mint insight | prompt 证据仍在，模型结果不写 | 运行核心要记录 pid/attempt/deadline；重试要有 budget/幂等键，避免重复铸造 |
| 模型调用被取消 | `CancelledError` 触发 terminate/kill；Claude 返回 force-wake 结果，其他 provider 重新抛取消 | 不写模型结果 | 统一取消语义；调用者不能吞掉取消而把任务标成成功 |
| 模型非零、空输出、无法解析、输出超限、billing | 明确失败，不 mint；Claude cost>0 触发禁用；非 Claude 输出超过 8192B 拒绝 | 失败原因应进入任务/事件账本 | provider adapter 统一错误；失败证据与花费计量不能只在日志 |
| socket client 断开/daemon 崩溃 | `SocketServer` finally 关闭 writer、连接计数回收；wrapper reject pending、只尝试一次 reconnect；daemon down 时工具有 direct-store/bank fallback | pending RPC 结果不重放 | 重连必须带 request id/幂等语义；写请求不可盲重试；daemon 崩溃后需恢复进度、清理 socket/marker |
| daemon/宿主强杀 | 临时状态文件 `fsync+replace`；sleep progress/lifecycle 可重读；hook 文件留盘；部分 native/worker 资源由 OS 回收 | 已原子提交数据保留，处理中输入依赖 marker/quarantine | 尚未看到一个统一崩溃事务/任务 receipt；直接写 Hippo 与 daemon 写并行时仍有 owner/锁边界风险 |

## 6. 资源生命周期与释放责任

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消/崩溃治理 | 底座归属 |
|---|---|---|---|---|
| `MemoryStore`/Hippo writer | daemon `main()` 独占打开；`MemoryStore.__init__` 建 root、DB、buffers/index/cache/callback | `MemoryStore.close()` flush event/record/edge，停 async/provenance/reinforce，关 DB；weak callback 避免 store↔db cycle | close 是 best-effort 且吞异常；宿主崩溃依赖 WAL/重启检查；需读回 buffer/lock/DB 状态 | 支持库实现，运行核心持有租约 |
| RO pool/reader slot | recall 借用固定池 slot；snapshot generation 绑定 commit | context manager release；slot refresh/close/reopen | snapshot fence 最多 8 次 reopen，耗尽回 writer path；pool close 需清所有 slot | 支持库；运行核心监测 writer fallback |
| record/edge/event buffers | process-local dict，flush 前持有明文/row | terminal success/confirmed dup/hard failure 后移除；transient 保留；store close flush | record hard error 进入 `.record-quarantine`；event flush 当前代码 pop 后写失败，需补“失败 rebuffer”核验 | 支持库 primitive + 记忆模块 payload |
| pending capture files | hook/CaptureQueue 原子写 `pending-*`；ingest 用 `.lock` claim | handler 成功后 unlink，再清 lock | schema error/handler failure 保留；processing/crash/failed/quarantine 由 drain 恢复；overflow 会丢最老文件 | 支持库队列 + 运行核心 drain |
| user model/profile temp files | `user_model.save()`/state save 建 temp、写、flush、fsync、chmod 600、replace | replace 后 temp 消失 | write error unlink temp；旧目标保留；profile 不可解密保存 orphan/event | 支持库原子文件/加密 KV；记忆模块 owner |
| model child process/pipes | `create_subprocess_exec`，Claude stdin DEVNULL，其他 provider stdin prompt，cwd scratch，allow-list env | communicate 完成，进程退出，pipe 被 asyncio 收回 | timeout/cancel terminate→kill，bounded wait；需保证 pgid/descendants 与 pipe closure 可验证 | 运行核心监督 + 支持库 provider adapter |
| native Rust/PyO3 embed/graph/store | Python 进程内加载 `iai_mcp_native`；Embedder/graph/index 持有 native allocations | Python/DB close 或进程退出 | 进程崩溃由 OS 回收；本项目没有统一 native handle lease，第三方扩展不隔离 | 支持库；高风险 native provider 建议独立进程隔离 |
| Unix socket/listener/connection | `SocketServer.serve()` 建 socket、chmod 0600；每 connection active++ | writer close/wait_closed；server close；旧 socket cleanup | client reset/broken pipe 被吞后 finally 回收；强杀残留依赖 `cleanup_stale_socket` | 网关/运行核心边界 |
| caches/indexes/graph | exact/lexical/recency/RGC lazy build，写入回调 invalidation | TTL/weak-key/close 清理；重建替换 | cache stale 可降级；generation/fence 防旧 snapshot；需验证 crashed child temp/index 是否残留 | 支持库存储索引 + 记忆模块一致性 + 运行核心调度 |

## 7. L0-L4 分层落点

本轮采用“L0 最小可复用原子能力、L4 外部宿主/供应者”的定义；L4 不是本项目内部新一层，而是必须被网关/支持库包住的外部边界。

| 层 | 目标职责 | 本项目命中 | 不应放入 |
|---|---|---|---|
| **L0 支持库原子底座** | 加密/解密、hash/idempotency、原子文件、队列/锁、WAL/事务、RO pool、向量/图算子、embedding/provider protocol、进程组、统一错误/结果 | `crypto.py`、`hippo/`、`lillibrain/`、`embed.py` 的 adapter 部分、`capture_queue.py`、native/Rust | capture 语义、社区/画像业务规则、MCP tool 路由 |
| **L1 记忆模块** | 原始证据契约、MemoryRecord/Edge/Event、capture/dedup/contradict、recall/rank/temporal、projection、session composer、user model/profile 语义 | `capture.py`、`retrieve.py`、`pipeline.py`、`session.py`、`user_model.py`、`lilli/profile`、`insight.py`、schema/consolidation 业务步骤 | socket 生命周期、进程 kill、全局资源配额、外部 MCP wire |
| **L2 运行核心** | daemon 生命周期、任务 registry/lease/deadline/cancel、SleepPipeline 调度与恢复、foreground priority、资源监督、crash recovery、状态/事件、provider worker 管理 | `daemon/`、`lifecycle_state.py`、`daemon_state.py`、`SleepPipeline`、`concurrency.py`、watchdog、部分 `claude_cli` 监督逻辑 | 记忆排序规则、直接 SQL 业务写、对外 tool schema |
| **L3 统一网关** | MCP stdio、JSON-RPC/Unix socket、schema、认证/本地权限、重连、统一错误码、结果序列化、CLI/dashboard adapter | `mcp-wrapper/src/index.ts`、`tools.ts`、`bridge.ts`、`socket_server.py`、`core.dispatch()`、CLI/brainview | 自己读库并重做 recall/capture；隐藏 fallback；持有 vendor secret |
| **L4 外部边界** | 宿主 hook、Claude/Codex/Gemini CLI、HTTP embed service、OS filesystem/socket/process、Rust/C/PyO3/第三方依赖 | `_deploy/hooks`、provider child、loopback HTTP、macOS launchd/systemd、`iai_mcp_native` 与第三方库 | 未经 L0/L2 adapter 直接进入 L1/L3；外部返回不能直接成为事实 |

## 8. 唯一链路与复用/升级/隔离裁决

### 8.1 目标唯一链路

```text
L4 宿主/Provider
  → L3 网关：一个 capability/tool id、一个 wire schema、一个错误码转换点
  → L2 运行核心：一个 task receipt、一个 deadline/cancel/lease、一个资源监督点
  → L1 记忆模块：一个 evidence/capture、一个 projection、一个 recall/context 入口
  → L0 支持库：一个 provider/transaction/index/file/process primitive
  → L4 资源
```

- `memory_capture`、`memory_recall`、`memory_consolidate`、`profile_get_set` 各只有一个规范入口；历史 CLI、direct-store、MCP aliases 只能在网关/模块入口归一化，不能复制业务流程。
- 所有写入按 `提交命令 → 记忆模块校验/组装 → 支持库原子提交 → 读回/事件确认 → 派生投影 invalidate/rebuild`；禁止网关直写表，禁止画像或索引反向写原文。
- 所有长任务按 `submit → persisted task state → worker → progress/event → result receipt → release`；睡眠步骤、reflection、index rebuild 和 capture drain 都应纳入同一 task owner，而不是各自维护超时和取消。
- Fallback 不是第二事实源：daemon down 时只允许离线 spool/只读 bank 作为可声明的 degraded path；重新上线必须由同一 memory module 做 reconcile，不能让 direct writer 与 daemon writer 各自定义 schema/去重/投影。

### 8.2 命中表与裁决

| 现有能力 | 映射 | 裁决 | 理由/验收契约 |
|---|---|---|---|
| 加密字段、profile blob、event data | L0 支持库 | **复用** | AES-GCM/AAD/密钥隔离已有源码；验收为 decrypt/read-back、错误留痕、密钥错误不覆盖旧值 |
| `MemoryStore`/Hippo 事务、WAL、RO pool | L0 支持库 | **升级后复用** | 已有 writer/reader/索引边界；需统一结果、事务/读回、崩溃恢复和 close 残留验证 |
| capture record/edge/event | L1 记忆模块 | **复用语义，升级唯一写 owner** | `literal_surface`/provenance/contradict/edge lineage 成熟；收敛 `direct_write` 和 raw hook drain |
| profile/user model | L1 记忆模块 | **升级 projection registry** | profile 已加密单写；user model JSON 与 `_hippo_meta` 双 owner 风险，需 source watermark/version |
| ANN/exact/lexical/graph recall | L1 + L0 | **复用算法，升级统一 capability** | 当前 fallback/normal/crisis 多路径必须共用 rank/trace/错误契约；索引可重建不是真实事实 |
| session L0-L2/context editing | L1 + L2 | **复用 composer，升级缓存 owner** | 预算和 delta 已清楚；cache/watermark/TTL 要由运行核心托管 |
| Claude/Codex/Gemini reflection | L0 provider + L2 supervisor | **升级集中 provider supervisor** | 当前有 allow-list/timeout/cancel/output cap；`claude_cli` 与 reflection adapter 仍有监督逻辑分散 |
| SleepPipeline 17 steps | L2 任务 | **升级为统一任务系统** | 已有 progress/attempt/quarantine/interrupt；缺 task id、lease、统一 cancel、结果/资源清单 |
| hook 文件/CaptureQueue | L0 文件队列 + L2 drain | **复用 primitive，升级 reconcile** | 原子写/lock/审计好；overflow 默认删除和 crash marker 需要统一 backpressure/恢复 |
| MCP wrapper/socket/core | L3 网关 | **复用并收敛 fallback** | wire schema/parity/reconnect 已存在；禁止 gateway direct-store 变第二业务入口 |
| native Rust / 第三方扩展 | L0/L4 | **隔离高风险 provider** | 当前 PyO3 与 daemon 同进程；宿主崩溃会连带记忆网关，平台应为 crash-prone provider 设独立进程边界 |

### 8.3 待建立的原子能力（不在本轮修改底座）

1. `evidence.append`：统一 envelope、source/session/project、idem key、原文加密、ack、dead-letter、read-back。
2. `projection.refresh`：投影名、source watermark、算法/模型 identity、generation、失败/重试/过期状态，原始事实只读。
3. `memory.recall`：统一 cue、mode、budget、hits/anti_hits/trace/degraded/error 形状，正常/危机/daemon-down 只换 provider lane。
4. `context.assemble`：L0-L4 预算、session/watermark、cache breakpoint、origin label、最大字符/token 的单一契约。
5. `model.invoke`：provider、prompt evidence refs、deadline、cancel token、cost/token、output cap、子进程组、幂等 receipt。
6. `task.submit/status/cancel`：任务状态机、lease、heartbeat、attempt、deadline、cancel reason、crash recovery、资源释放证明。
7. `resource.acquire/release/reconcile`：DB/文件/索引/进程/socket/native handle 的 owner、borrow/transfer、终态和残留扫描。

## 9. L0-L4 验收契约与证据缺口

| 层 | 必须可读回的证据 | 本轮源码状态 |
|---|---|---|
| L0 | 原子写前后文件/DB 读回；事务回滚；加密不可读；provider schema/identity；进程/连接/锁释放 | 代码已有多处单测目标，但本轮未执行；`events.flush_event_buffer()` 写失败后的 pending 是否 rebuffer 需复核 |
| L1 | record literal/provenance 不变；projection source ids/watermark；recall trace 与 mode/预算；context hash/delta | 主要路径已实现；`direct_write`、user-model JSON 和多 fallback 仍存在 owner 分裂 |
| L2 | task id/progress/lease/cancel/crash recovery；sleep step attempt/quarantine；资源残留为零 | SleepPipeline 有 progress/quarantine/interrupt，但没有统一 task receipt/lease/cancel registry |
| L3 | MCP schema↔Python parity；未知方法/缺参/断线/重连；写请求不重复提交 | wrapper/socket 有真实处理；pending RPC 重连的写幂等仍需统一契约 |
| L4 | hook/provider/OS 真实故障：断电/kill、CLI timeout、HTTP refusal、native crash、文件权限/磁盘满 | 源码和测试覆盖不少反向场景；本轮未启动外部服务或运行故障注入，不能宣称端到端通过 |

### 本轮剩余风险

- MCP `project_context` 错绑且 `codegraph` 未索引目标，无法给出本项目的可信开工 id/代码图摘要；后续应在正确项目上下文中重新绑定并由维护者决定是否 `codegraph init`。
- `direct_write.py`、CLI/bank fallback、brainview/direct-store 与 daemon `MemoryStore` 形成多个访问面；虽然目标是可用性和只读降级，但写 owner/幂等/投影边界仍需平台级收敛。
- `user_model.py` 把派生画像写成独立 JSON，而 profile 写 `_hippo_meta`；两者的加密、版本、水位、恢复契约不同，不能直接合并为一个“画像已持久化”结论。
- `SleepPipeline` 的中断是 cooperative，模型 provider 有子进程终止，但整个系统还没有统一任务取消、租约、强杀后资源对账和单一 task receipt。
- `MemoryStore.close()` 对多数 flush 失败采用日志吞掉；record buffer 有可恢复 quarantine，而 event buffer 的失败重放语义仍需实测确认。源码存在 `catch` 不等于失败恢复已经验证。
- `Queue.prune_oldest()` 真实删除超限 pending；这应作为容量/数据保留策略单独合规裁决，不可被包装成“无损持久队列”。
- native Rust/PyO3、Numba、NumPy 与存储引擎在 daemon 进程内组合；本项目有 watchdog/内存门，但通用平台仍应把高风险 provider 的崩溃域隔离到受监督子进程。
- 本轮未运行测试，不能把 `tests/` 中存在的测试当作当前 checkout 全绿；正式接入前必须按 L0-L4 逐层执行真实验证并读回资源现场。

## 10. 第三轮结论

**吸收：** 原文 `literal_surface` 不被摘要覆盖；provenance/source_ids 先验核验；record/edge/event 分离；召回的 ANN+exact authority+graph/lexical/temporal 多路降级；上下文 L0/L1/L2 预算与 per-turn delta；SleepPipeline 的持久 progress/attempt/quarantine/interrupt；模型子进程的 allow-list/timeout/cancel/output cap；原子 temp+fsync+replace 和 RO snapshot fence。

**升级：** 把 evidence、projection、recall、context、model.invoke、task、resource 各自固化为一个公共契约和一个 owner；把 `direct_write`/fallback/user model JSON/分散 subprocess supervision 收敛到唯一链路；把失败事件、任务 receipt、source watermark、resource release proof 纳入统一结果。

**隔离：** 网关不得直写存储；模型/第三方/native 高风险 provider 不得穿透 L1/L3；daemon-down fallback 只能作为可审计 degraded adapter，不能成为第二事实源。

**待核：** 正确 MCP 项目上下文/开工 id；目标代码图是否建立；event buffer 写失败重放；native crash 后句柄/临时文件残留；强杀 SleepPipeline/模型/索引 worker 后的真实恢复；队列溢出策略是否符合平台数据保留要求。

本第三轮内容继续只维护本 `ARCHITECTURE.md`；未修改源码、依赖、配置、测试、README 或 Git，也未删除旧细探。
