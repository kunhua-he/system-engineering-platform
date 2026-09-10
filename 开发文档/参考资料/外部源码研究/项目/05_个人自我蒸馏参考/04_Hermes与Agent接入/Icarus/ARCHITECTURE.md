# Icarus 架构建档

## 1. 文档范围与证据边界

- **项目**：Icarus Hermes 插件，版本 `0.3.0`。
- **定位**：把 Hermes 会话中的高价值工作写入共享 Markdown fabric，再提取训练对、训练/评估替换模型，并提供模型切换与回滚。
- **非定位**：不是独立应用、HTTP 服务、编排框架、Agent 路由器或 Obsidian 社区插件；Obsidian 只是可选的 Markdown 查看器。
- **盘点基线**：当前仓库 `main` 分支，HEAD `e46cba3 fix install and profile paths in README`。
- **规则文件**：项目及其上级接入目录未发现 `AGENTS.md` 或 `CLAUDE.md`。
- **证据写法**：下文的 `文件:行号` 均指本仓库当前源码/文档；设计文档和 README 只作为意图说明，运行行为以源码和测试结果为准。

## 2. 总体架构与文本流程图

Icarus 是一个由 Hermes 宿主注入上下文、调用工具、触发生命周期钩子的插件。插件内部没有数据库和常驻进程，主要以文件系统作为状态边界；训练与评估阶段通过标准库 HTTP 客户端调用 Together AI。

```text
┌──────────────────────── Hermes Agent 宿主 ────────────────────────┐
│  plugin loader                                                        │
│       │                                                               │
│       ▼                                                               │
│  icarus.register(ctx)                                                 │
│       ├── register_tool(schema + handler) × 16                       │
│       └── register_hook(callback) × 4                                │
│                                                                       │
│  会话开始 ──► on_session_start                                       │
│       │             ├─ SOUL.md / 待办 / review / ticket / 最近记录     │
│       │             └─ creative 状态                                   │
│       ▼                                                               │
│  每次 LLM 调用 ─► pre_llm_call ─► ranked recall ─► prompt context     │
│       │                                                               │
│       └──────────► post_llm_call ─► 决策捕获 + creative tracking       │
│  会话结束 ──────► on_session_end ─► session score ─► session note     │
└──────────────────────────────────────┬────────────────────────────────┘
                                       │ read/write
                                       ▼
┌────────────────────────── FABRIC_DIR ────────────────────────────────┐
│ Markdown + YAML frontmatter                                           │
│  hot entries (*.md) ───┐                                              │
│  cold/*.md 归档        ├─► fabric_recall / fabric_search / pending    │
│  daily/*.md (可选)     ┘                                              │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ scan + quality filter + linked refs
                               ▼
┌────────────────────── 训练数据流水线 ────────────────────────────────┐
│ export-training.py                                                     │
│   ├─ high-precision / normal / high-volume                             │
│   ├─ review-correction / cross-platform / basic 等 pair               │
│   └─ openai.jsonl / together.jsonl / hf-dataset.jsonl / raw-pairs.json│
│                               │                                       │
│                               ▼                                       │
│   Together AI: upload ─► fine-tunes ─► job status                     │
│                               │                                       │
│                               ▼                                       │
│   ~/.hermes*/.icarus-models.json (model registry)                     │
│                               │                                       │
│   eval-replacement.py ─► chat/completions ─► eval score               │
│                               │                                       │
│              score ≥ 0.7 ─► .env 备份 ─► 原子替换模型配置              │
│              .env.backup ─► fabric_rollback_model                    │
└──────────────────────────────────────────────────────────────────────┘
```

## 3. 分层与职责

| 层 | 主要文件 | 职责与边界 |
|---|---|---|
| Hermes 插件适配层 | `__init__.py` | 暴露 `register(ctx)`；把工具 schema、处理器和四个 hook 注册到 Hermes；不直接实现业务。 |
| LLM 可见契约层 | `schemas.py` | 以字典声明工具名称、描述、参数、必填项和枚举；这些描述是 LLM 的调用契约，但不是强类型运行时校验器。 |
| 工具门面层 | `tools.py` | 读取参数、做轻量校验、调用 `state`/`obsidian`，把成功和异常统一序列化为 JSON 字符串；处理器按约定不向 Hermes 抛异常。 |
| 生命周期层 | `hooks.py` | 会话开始注入上下文；主题变化时检索记忆；会话中捕获决策/创意；会话结束评分并写 session 条目。 |
| 状态与持久化层 | `state.py` | 全部 fabric 文件 I/O、侧车状态、遥测、会话评分、模型 registry、Together AI 请求、模型切换/回滚。 |
| 检索算法层 | `fabric-retrieve.py` | 扫描 hot/cold Markdown，解析 frontmatter，按关键词、摘要、短语、标签、项目、agent、新鲜度、tier、类型、链接链打分、去重并施加 token 预算。 |
| 训练提取层 | `export-training.py` | 解析条目、按质量模式过滤、解析 `review_of`/`revises`/`refs`，生成基础、结果、自纠正、跨平台训练对和四种文件输出。 |
| 可选展示层 | `obsidian.py` | 在 fabric 条目追加 wikilink、维护 daily note、初始化 vault 的 `.obsidian/app.json`。 |
| 运维/验证脚本层 | `scripts/smoke-handoff.sh`、`scripts/test-plugin.sh`、`scripts/eval-replacement.py` | 临时目录端到端 handoff、66 项 fixture 测试、Together AI 候选/基线模型对比。 |

模块之间的依赖方向是 `__init__ → schemas/tools/hooks → state`，`state` 动态加载 `fabric-retrieve.py`，并在开启 `ICARUS_OBSIDIAN` 时调用 `obsidian.py`。训练和评估脚本既可独立运行，也由 `state` 以 `subprocess` 调用（`state.py:618-665`、`839-880`）。

## 4. 目录与核心入口

```text
Icarus/
├── plugin.yaml             Hermes 清单：名称、版本、16 tools、4 hooks
├── __init__.py              插件入口：register(ctx)
├── schemas.py               LLM 可见工具 schema
├── tools.py                 工具处理器/JSON 门面
├── hooks.py                 四个生命周期 hook
├── state.py                 fabric、遥测、训练、registry、切换/回滚
├── fabric-retrieve.py       ranked retrieval；同时提供 CLI
├── export-training.py       训练对导出；同时提供 CLI
├── obsidian.py              可选 Obsidian 集成
├── scripts/
│   ├── eval-replacement.py  候选模型评估 CLI
│   ├── smoke-handoff.sh     handoff 冒烟脚本
│   └── test-plugin.sh       fixture 驱动测试脚本
├── README.md                安装、使用、架构意图、工具表、验证说明
├── CONTRIBUTING.md          贡献、编码风格、测试入口
├── 细探-Icarus.md            已有的人工细探资料（本次保留不改）
└── ARCHITECTURE.md          本次新增的唯一架构建档
```

入口证据：`plugin.yaml:1-26` 声明插件清单；`__init__.py:42-89` 实际完成 16 个工具和 4 个 hook 的注册。README 的文件说明见 `README.md:336-352`。

## 5. 数据模型与状态存储

### 5.1 Fabric 条目

fabric 不是关系数据库，而是 `FABRIC_DIR` 下的 Markdown 文件。`state.write_entry` 在 `state.py:303-378` 生成文件名、frontmatter 和正文：

```text
<agent>-<entry_type>-<summary-slug>-<random-4-hex>.md
```

固定元数据字段：

- `id`：随机 8 hex 字符的逻辑条目 ID。
- `agent`、`platform`、`timestamp`：来源身份和 UTC 时间。
- `type`：`task`、`decision`、`review`、`resolution`、`research`、`code-session`、`session`、`note` 等。
- `tier`：默认 `hot`；读取时 `read_recent` 只取 hot，检索和导出同时扫描根目录与 `cold/`。
- `summary`、`project_id`、`session_id`：展示/检索及会话关联字段。

可选工作流、训练和证据字段：

- 工作流：`status`、`assigned_to`、`customer_id`、`review_of`、`revises`、`outcome`。
- 训练质量：`training_value`（`high`/`normal`/`low`）、`verified`。
- 证据来源：`evidence`、`source_tool`、`artifact_paths`、`tags`。

`fabric_write` 会强制检查必需的 `type/content/summary`，开放任务必须带 `assigned_to`，review 必须带可解析的 `review_of`，引用目标必须存在（`tools.py:27-85`）。`fabric_curate` 则会原地更新既有 Markdown 的 `training_value`（`state.py:458-480`），因此 fabric 条目并非严格 append-only。

### 5.2 侧车状态

路径由 `HERMES_HOME` 决定；若未设置则落在用户 home（`state.py:18-21`、`41-56`、`79-83`、`259-275`）：

| 路径 | 内容 | 写入者 |
|---|---|---|
| `${HERMES_HOME}/.icarus-state.json` | 创意状态：`cycle`、`themes`、`questions`、`learnings` | session start、post LLM |
| `${HERMES_HOME}/.icarus-models.json` | 模型 registry、训练任务元数据、eval 分数、active model | train status、eval、switch、rollback |
| `${HERMES_HOME}/.icarus-training-job.txt` | 最近一次 Together fine-tune job ID | train |
| `${HERMES_HOME}/.icarus-telemetry.jsonl` | recall/usage 事件、查询、结果 ID、session/agent | recall、linked write |
| `${HERMES_HOME}/SOUL.md` | 宿主 agent 的 soul 文本 | 只读加载 |
| `${HERMES_HOME}/memories/MEMORY.md` | 由 creative 状态生成的简化记忆 | session end |
| `${HERMES_HOME}/.env` | Hermes 模型/API 配置 | 模型切换读取/写入 |
| `${HERMES_HOME}/.env.backup` | 切换前的配置备份 | 模型切换/回滚 |

### 5.3 Obsidian 产物

`ICARUS_OBSIDIAN` 非空时，写入条目后追加 `## Links` 区块并维护 `FABRIC_DIR/daily/YYYY-MM-DD.md`（`state.py:369-376`、`obsidian.py:47-104`）。`fabric_init_obsidian` 会创建 fabric `daily/`，并在 `OBSIDIAN_VAULT_PATH`（未配置时为 fabric 根目录）创建 `.obsidian/app.json`（`obsidian.py:107-148`）。

### 5.4 模型 registry 记录

训练完成前，registry 条目包含 `job_id`、`base_model`、`output_model`、`suffix`、创建时间、pair 数、token 估计、pair 类型、导出模式、状态、eval 分数和 active 标志（`state.py:774-790`）。它是 JSON 文件，没有迁移、锁或数据库事务。

## 6. 关键数据流

### 6.1 插件加载与注册

1. Hermes 加载插件包并调用 `register(ctx)`。
2. `__init__.py` 依次把 memory、training、replacement-model、daily-driver 四组工具注册到 `toolset="fabric"`。
3. 同一入口注册 `on_session_start`、`pre_llm_call`、`post_llm_call`、`on_session_end`。
4. 工具的 LLM 描述来自 `schemas.py`，实际执行函数来自 `tools.py`；schema 本身不在 `tools.py` 外形成独立版本协商。

### 6.2 会话记忆闭环

```text
Hermes session start
  → reset session buffers / load creative / increment cycle
  → load SOUL.md
  → read_pending: assigned open tasks + reviews + customer tickets
  → read_cross_agent (无待办时) + read_recent
  → return {"context": ...}

每次 user message
  → tokenize 英文小写词
  → 与上一查询重叠率 > 0.6 则跳过
  → state.recall(query, agent)
  → log_recall 到内存及 .icarus-telemetry.jsonl
  → return relevant summaries as prompt context

每次 assistant response
  → append 截断后的 exchange
  → decision + outcome + response > 200 字符 + user > 50 字符
       → 写 high training_value 的 decision 条目
  → 识别主题 / learning / question，更新 .icarus-state.json

session end
  → 把 creative 状态写入 HERMES_HOME/memories/MEMORY.md
  → score_session
  → total < 0.2 跳过 session note
  → 生成 Task/Decision/Result/Entries created
  → 按总分映射 high/normal/low，写 completed session 条目
```

实现证据：`hooks.py:54-124`、`127-158`、`161-214`、`216-276`；评分权重见 `state.py:1056-1080`。

### 6.3 Builder → reviewer → fix handoff

```text
fabric_write(status=open, assigned_to=reviewer)
  → FABRIC_DIR/<entry>.md
  → reviewer on_session_start/read_pending 看见 entry id
  → fabric_write(type=review, review_of=agent:id)
  → 原作者 session start 看见 reviews_of_my_work
  → fabric_write(revises=agent:id, status=completed)
  → export-training 解析 review_of/revises
  → review-correction pair（可附 cross-platform pair）
```

引用检查与 telemetry 记账见 `tools.py:39-52`、`74-81`；待办分类见 `state.py:483-521`。README 的使用示例见 `README.md:209-223`。

### 6.4 Ranked recall

`state.recall` 首次调用时动态加载仓库内 `fabric-retrieve.py`，失败时回退 `read_recent`（`state.py:547-587`）。检索器执行：

1. 扫描 `FABRIC_DIR/*.md` 和 `FABRIC_DIR/cold/*.md`。
2. 解析 YAML frontmatter；有 `yaml` 时使用 `yaml.safe_load`，否则使用简化解析器。
3. 第一遍按关键词/摘要/短语/二三元组/标签、项目、agent、时间、tier、类型和工作流字段打分。
4. 从前 10 条收集引用链，第二遍加 ref-chain 分数。
5. 过滤零分、按 `(agent,type,body 前 50 字符)` 去重，截断 `max_results`，再按约 4 字符/token 扣除 `max_tokens`。

完整评分与预算实现见 `fabric-retrieve.py:119-258`、`261-355`。

### 6.5 训练数据导出

```text
FABRIC_DIR hot/cold Markdown
  → scan_all + parse_entry
  → _entry_quality
       high-precision: high / verified / linked review / structured session / completed+evidence
       normal: 非 low，且 session 需结构化/verified/high/evidence
       high-volume: 全量
  → extract_pairs
       outcome、basic、dialogue、decision、session-structured、review、review-correction、cross-platform
  → 按 verified/evidence/high value/跨 agent 自纠正加权复制
  → openai.jsonl / together.jsonl / hf-dataset.jsonl / raw-pairs.json
```

质量判定见 `export-training.py:22-66`；条目扫描与配对见 `118-375`；输出与加权见 `442-517`。`state.export_training` 在临时目录执行该脚本、读取 `together.jsonl` 和 `raw-pairs.json`，再返回统计与训练内容（`state.py:618-665`）。

### 6.6 训练、评估、切换、回滚

1. `fabric_train` 检查 `TOGETHER_API_KEY`，自动选择满足 `min_pairs` 的最高质量导出模式。
2. 将 Together 格式 JSONL 上传至 `https://api.together.xyz/v1/files/upload`。
3. 调用 `POST https://api.together.xyz/v1/fine-tunes` 创建任务，保存 job ID 和 pending registry。
4. `fabric_train_status` 调用 `GET /v1/fine-tunes/{job_id}`，完成时写入 output model。
5. `fabric_eval` 启动 `scripts/eval-replacement.py`，从高价值/已完成条目抽样；对 base/candidate 分别调用 Together OpenAI-compatible `POST /v1/chat/completions`，计算任务完成、格式符合、风格相似度。
6. `fabric_switch_model` 只接受 registry 中有 eval 分数且平均分达到阈值（默认 `0.7`）的模型；复制 `.env` 为 `.env.backup`，用临时文件 rename 更新 `LLM_MODEL`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`，然后更新 registry（`state.py:883-965`）。
7. `fabric_rollback_model` 恢复 `.env.backup`，并按恢复后的 `LLM_MODEL` 更新 active 状态（`state.py:968-1011`）。

## 7. API、CLI 与 SDK 接口

### 7.1 Hermes Plugin SDK

唯一宿主 SDK 入口是 `register(ctx)`：

```text
ctx.register_tool(name=<tool>, toolset="fabric", schema=<SCHEMA>, handler=<HANDLER>)
ctx.register_hook(<hook_name>, <CALLBACK>)
```

该调用约定由 `__init__.py:42-87` 使用；仓库不包含 Hermes SDK 的类型定义、版本适配层或独立 API server。

### 7.2 Hermes 工具 API

所有工具处理器均接受 `args: dict, **kwargs`，成功/失败均返回 JSON 字符串；异常在 `tools.py:7-9` 和各 handler 的 try/except 中转为 `{"error": ...}`。

| 类别 | 工具 | 主要输入/输出 |
|---|---|---|
| 记忆 | `fabric_recall` | `query` 必填；可传 `max_results`、`agent`、`project`；返回带 score 的 entries。 |
| 记忆 | `fabric_write` | `type`、`content`、`summary` 必填；可传状态、结果、证据、客户、handoff 引用；返回写入 path。 |
| 记忆 | `fabric_search` | `query` 必填；返回文件、agent、摘要和匹配行。 |
| 记忆 | `fabric_pending` | 可按 `customer_id` 过滤；返回 open tasks、reviews、tickets、total。 |
| 记忆 | `fabric_curate` | `entry_id` + `training_value`；原地更新条目质量标签。 |
| 训练 | `fabric_export` | `mode`：三种质量模式；返回 pair/token/type 统计。 |
| 训练 | `fabric_train` | model、suffix、epochs、mode、min_pairs、batch/lr/checkpoints；返回 job/file/pair 信息或 error。 |
| 训练 | `fabric_train_status` | 可选 `job_id`；返回 Together job 状态和完成后的 model ID。 |
| 替换模型 | `fabric_models` | 无输入；返回 registry。 |
| 替换模型 | `fabric_eval` | `candidate_model` 必填，可传 base/sample_count；返回逐 prompt 与聚合分数。 |
| 替换模型 | `fabric_switch_model` | `model_id` 必填，可传 `min_eval_score`；通过门禁后修改 Hermes `.env`。 |
| 替换模型 | `fabric_rollback_model` | 无输入；恢复 `.env.backup`。 |
| 运维 | `fabric_brief` | 无输入；返回待办、最近工作、他人活动、建议动作及可用遥测。 |
| 运维 | `fabric_telemetry` | 可传 `last_n`；返回 recall/usage 事件和汇总。 |
| 运维 | `fabric_init_obsidian` | 无输入；初始化 daily 目录与 vault 配置。 |
| 运维 | `fabric_report` | 无输入；返回条目类型/训练值、verified、使用率、可训练估计。 |

schema 的完整参数描述在 `schemas.py:3-420`；注册总表在 `plugin.yaml:5-26`。

### 7.3 CLI

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `python3 fabric-retrieve.py "billing issue"` | 独立 ranked recall | `--max-results`、`--max-tokens`、`--agent`、`--project`、`--fabric-dir`；定义见 `fabric-retrieve.py:367-391`。 |
| `python3 export-training.py --output ./training-data/` | 导出训练数据 | `--output`、`--fabric-dir`、`--mode`；定义见 `export-training.py:404-521`。 |
| `python3 scripts/eval-replacement.py ...` | Together base/candidate 评估 | `--candidate-model`、`--base-model`、`--together-api-key`、`--fabric-dir`、`--sample-count`；定义见 `scripts/eval-replacement.py:143-213`。 |
| `bash scripts/smoke-handoff.sh` | 临时目录 handoff 冒烟 | 无参数；脚本创建并清理临时 fabric/Hermes home。 |
| `bash scripts/test-plugin.sh` | fixture 驱动核心测试 | 无参数；脚本创建并清理临时 fabric/Hermes home。 |

仓库没有 Makefile、Dockerfile、`pyproject.toml`、`setup.py`、`requirements.txt` 或其他包构建入口；`search_files` 未发现这些依赖/构建清单。

### 7.4 外部 API / 无独立服务

Icarus 自己不监听端口，也没有对外 HTTP 路由。唯一外部网络边界是 Together AI：文件上传、fine-tune 创建/查询、OpenAI-compatible chat completions。API key 从 `TOGETHER_API_KEY` 环境变量或 `${HERMES_HOME}/.env` 读取（`state.py:590-615`）；评估脚本也接受命令行 key（`scripts/eval-replacement.py:143-149`）。

## 8. 技术栈与配置

| 类别 | 实际情况 |
|---|---|
| 语言 | Python 3.10+（README/CONTRIBUTING 声明；源码使用类型注解、`pathlib`、标准库）。 |
| 依赖 | 运行主路径使用 Python 标准库：`json`、`re`、`pathlib`、`urllib.request`、`subprocess` 等。源码在 `state.py:286-301`、`fabric-retrieve.py:51-83`、`export-training.py:79-115` 尝试导入 `yaml`，失败后使用简化 frontmatter 解析器；因此 PyYAML 是可选运行时依赖，但其存在与否会改变解析能力。 |
| 宿主 | Hermes Agent v0.6.0+（README:329-334）；插件清单版本为 0.3.0。 |
| 存储 | 本地 Markdown/YAML、JSON、JSONL、`.env` 文件；无 SQL/ORM/消息队列。 |
| 检索 | 纯 Python 启发式加权排序，无向量库。 |
| 外部训练 | Together AI fine-tune 与 OpenAI-compatible inference API。 |
| 可选查看 | Obsidian vault 配置、daily notes、wikilinks。 |
| 进程模型 | Hermes 调用时同步执行 handler；训练查询和评估通过标准库 HTTP/子进程同步等待，虽训练任务本身由 Together 异步执行。 |

环境变量和默认值：

| 变量 | 用途/默认 |
|---|---|
| `FABRIC_DIR` | fabric 根目录；未设置默认为 `~/fabric`。 |
| `HERMES_HOME` | profile/home 及侧车状态根；未设置时侧车文件落到 `Path.home()`。 |
| `HERMES_AGENT_NAME` | agent 标识；未设置时尝试从 `.hermes-<profile>` 推导，否则为 `agent`。 |
| `FABRIC_SESSION_ID` | 写条目时的会话 ID 覆盖；默认使用当前 hook session 或时间+进程号。 |
| `FABRIC_PROJECT_ID` | 写条目的项目标识覆盖；默认当前工作目录名。 |
| `ICARUS_OBSIDIAN` | 非空启用 wikilink 和 daily note。 |
| `OBSIDIAN_VAULT_PATH` | Obsidian vault 根；未设置时使用 `FABRIC_DIR`。 |
| `TOGETHER_API_KEY` | 训练/评估 API key；也可从 `${HERMES_HOME}/.env` 读取。 |
| `TOGETHER_MODEL`、`TOGETHER_SUFFIX` | fine-tune 基础模型和后缀默认值。 |
| `TOGETHER_BATCH_SIZE`、`TOGETHER_LR`、`TOGETHER_CHECKPOINTS` | 训练参数默认值：8、`1e-5`、1。 |
| `LLM_MODEL` | 当前 Hermes 模型；切换时被替换。 |

README 的安装和环境变量意图见 `README.md:69-116`、`259-281`；实际默认值和文件路径以 `state.py:18-24`、`303-365`、`685-805` 为准。

## 9. 测试与验证现状

### 9.1 测试资产

- **`scripts/test-plugin.sh`**：自包含 Python fixture suite，复制插件到临时 Hermes home，在临时 fabric 上覆盖 handoff 引用链、跨平台 pair、重复抑制、决策捕获阈值、模型切换/回滚、端到端导出、检索排序、证据字段、训练模式自动选择、YAML 安全 round-trip、会话评分、corpus report、Obsidian 集成等场景。测试主体见 `scripts/test-plugin.sh:26-1082`。
- **`scripts/smoke-handoff.sh`**：两个临时 profile 模拟 builder/reviewer，验证写入 handoff、session-start、pending、review、fix、recall，见 `scripts/smoke-handoff.sh:32-165`。
- 仓库没有 pytest/unittest 测试目录，也没有 CI 配置或覆盖率配置。

### 9.2 本次只读验证结果

命令均设置 `PYTHONDONTWRITEBYTECODE=1`，未安装依赖、未启动服务，脚本临时数据在退出时清理：

- `bash scripts/test-plugin.sh`：**66 passed, 0 failed**。
- `bash scripts/smoke-handoff.sh`：**失败**；builder 写入、ID 生成、reviewer session-start 看见 handoff 均通过，但在“reviewer session-start includes source id”断言处退出。
- 该冒烟失败需区分测试夹具与运行逻辑：`state.write_entry` 用 JSON/YAML 安全标量写出带引号的 `id`（`state.py:327-330`），冒烟脚本 `parse_id` 只去空白、不去外层引号（`scripts/smoke-handoff.sh:63-67`），而 `on_session_start` 输出的 ID 来自 frontmatter 解析结果（`hooks.py:73-81`）。当前证据指向**冒烟脚本的 ID 解析与写入格式不一致**，但本次范围禁止修改测试或源码，故只记录不修复。

## 10. 关键风险与未确认项

### 10.1 已从源码确认的风险

1. **共享目录没有并发协调**：`write_entry` 直接 `mkdir`/`write_text`，`curate_entry` 直接覆盖原文件（`state.py:303-378`、`458-480`）；多 profile/agent 同时写、策展与读取并发时没有文件锁、版本号或冲突解决机制。
2. **侧车 JSON 更新不是原子写**：creative state、registry、job ID、telemetry 均使用直接写入/append；进程中断或多 profile 同写可能留下半文件或丢更新。
3. **训练参数校验时机**：`start_training` 在 `state.py:711-739` 先上传训练文件，之后才在 `748-753` 校验 batch size、learning rate、checkpoint 数；无效参数可能已经产生无用的外部上传。
4. **模型切换具有强副作用**：切换直接改写 Hermes `.env` 并切换 Together provider（`state.py:925-947`）；虽 `.env` 使用临时文件 rename，但 registry 随后普通写入，二者不是一个事务。
5. **回滚语义依赖单份备份**：每次切换覆盖 `.env.backup`；回滚只恢复最近备份，不能表达多代模型链。恢复后的模型若未出现在 registry，则 `active_model` 置为 null（`state.py:994-1005`）。
6. **外部 API 容错有限**：Together 请求为同步 urllib，超时固定 30/60/300 秒；训练上传可能成功而 fine-tune 创建失败，缺少远端文件清理和幂等键（`state.py:603-615`、`731-766`）。
7. **schema 与运行时校验存在双轨**：`schemas.py` 仅描述参数，运行时校验由各 handler 手写；schema 中有些边界（例如数值范围）主要在训练流程后段才校验。
8. **解析结果受 PyYAML 影响**：有 PyYAML 时使用完整 YAML，缺失时回退简化解析；`tags`、引号、复杂值等兼容性应视为部署环境变量，而不是固定保证。
9. **质量门禁是启发式**：训练质量依赖字段存在和正则/长度规则；评估的任务完成度主要按响应长度，格式按正则，风格按词频余弦相似度（`scripts/eval-replacement.py:106-140`），不能证明真实任务等价或安全。

### 10.2 当前核对未确认项

- Hermes v0.6.0+ 实际插件加载器是否要求特定返回类型、异步 handler、schema 校验或 manifest 额外字段；仓库只有调用方假设，没有宿主 SDK 源码/锁定版本。
- `HERMES_HOME` 在不同 Hermes profile 的真实注入方式，以及 profile-specific `.env` 的加载顺序；README 描述了 profile 用法，但未在真实 Hermes 进程中验证。
- Together AI 当前 API 的字段、模型兼容性、fine-tune endpoint 版本及实际返回结构；本仓库只实现 urllib 请求，测试使用 fake response，不访问网络。
- 是否存在外部生产 fabric 数据、旧版 frontmatter、`refs`/`cycle` 字段的完整历史兼容要求；仓库仅能从解析/导出代码推断兼容路径。
- 同一 fabric 目录跨平台/跨进程并发下的文件系统语义、备份恢复一致性、权限和敏感信息保护；未进行压力或故障注入。
- 模型切换后 Hermes 是否立即重新读取 `.env`，还是必须重启；README 写有重启配置提示，但运行时宿主行为未被本仓库验证。
- 真实 Obsidian 对 generated links 区块、daily note 和 vault root 的显示行为；当前核对只读源码并执行临时 fixture 测试。

## 11. 架构结论

Icarus 已形成一条清晰的纵向闭环：`Hermes plugin SDK → hooks/tools → 文件型 fabric memory → 启发式 recall → 训练对导出 → Together fine-tune/eval → .env 模型切换/回滚`。核心能力集中在 `state.py`，工具门面与生命周期层较薄，测试对主要离线行为覆盖较广（本次 `test-plugin.sh` 66/66 通过）。

当前它更准确地是“单机/低并发、文件型自记忆和模型替换原型”，而不是具备多进程一致性、严格 schema 契约、可审计发布事务和生产级训练评估的服务平台。若进入生产化阶段，优先需要补齐：共享 fabric 的锁与版本/冲突策略、侧车状态原子更新、训练前参数校验与幂等、模型配置与 registry 的一致性协议、宿主 SDK 版本契约，以及修正 smoke handoff 的 ID 解析断言。

## 12. 后续底座映射：可复用模块与治理缺口

当前核对不是把 Icarus 的文件直接搬进平台，而是把“插件注册、生命周期钩子、质量门、训练导出、模型注册、配置原子替换、回滚”逐项映射到平台已有的公共契约、支持库、模块库、运行核心和统一网关。结论分为：**吸收**（可作为通用能力输入）、**升级**（模式有价值但必须补一致性/证据/宿主验证）、**隔离**（第三方或宿主特定实现留在适配层）、**待核**（缺少真实宿主或线上证据）。

### 12.1 现有能力命中表

| Icarus 能力 | 当前真实实现 | 底座裁决 | 可复用的通用模块边界 | 不能直接吸收的部分 |
|---|---|---|---|---|
| 插件注册 | `plugin.yaml:1-26` 声明 16 tools/4 hooks；`__init__.py:42-89` 逐项调用 `ctx.register_tool`、`ctx.register_hook` | **升级后吸收** | 插件清单解析、能力注册表、版本/依赖/指纹校验、幂等注册、卸载/回滚、宿主适配器 | 不能把 Icarus 的英文工具名、Hermes SDK 假定或重复注册顺序当成平台公共契约 |
| 生命周期钩子 | `hooks.py:54-276` 实现 start、pre-call、post-call、end；通过模块全局 `session_id`、`exchanges`、`_last_query_tokens` 维持状态 | **升级后吸收** | 有序生命周期编排器、事件 envelope、超时/取消/异常隔离、钩子回执、幂等事件键、资源清理 | 全局可变状态、英文正则阈值、钩子直接写 fabric/记忆文件不能作为通用内核 |
| 质量门 | `export-training.py:35-66` 按 `training_value`、`verified`、证据、review 链、session 结构筛选；`eval-replacement.py:106-140` 用长度/正则/词频余弦评分 | **升级后吸收** | 质量门契约、证据完整性检查、独立评估集、阈值策略、拒绝证据、可重放评分 | 现有启发式可用于候选信号，不能作为生产发布的充分质量证明 |
| 训练导出 | `export-training.py:118-375、404-517` 扫描 hot/cold Markdown、解析引用、去重、加权，写四种 JSON/JSONL | **吸收为支持库+模块** | 不可变输入快照、确定性导出、数据集 manifest/摘要、模式契约、原子产物发布、可重放报告 | `high-volume` 明确保留全量；不能宣称所有噪声已过滤；临时目录和 stdout 统计不是持久事务 |
| 模型注册 | `state.py:55-72、774-790、820-834` 直接读写 `.icarus-models.json`，记录 job/output/eval/active | **升级后吸收** | 模型/训练任务注册表、唯一键、状态机、版本链、证据关联、CAS 激活指针、重启恢复 | JSON 直接覆盖、无迁移/锁/并发合并、按 `output_model` 查找不足以成为权威 registry |
| 配置原子替换 | `state.py:918-947` `copy2(.env.backup)` 后写 `.tmp` 并 `rename`；保留未改键并重写三项 provider 配置 | **升级为配置事务模块** | 配置快照、敏感值保留、临时文件权限、fsync+原子替换、解析校验、读回验证、意图/恢复记录 | 单文件 rename 只保证一个文件的替换，不保证 `.env` 与 registry 状态一致；当前 `tmp` 固定命名也未处理并发 |
| 回滚 | `state.py:968-1011` 只恢复单份 `.env.backup`，然后按恢复模型更新 registry | **升级为多代发布/回滚模块** | 代际快照、回滚目标选择、引用保护、CAS 指针、强杀恢复、幂等回滚、回滚证据 | 现有“最近一次备份”不能表达多代链；回滚不重新走 eval 门禁，但必须走完整性/宿主健康门禁 |

**可成为通用模块的最小集合**：

1. **插件注册与能力注册模块**：把 manifest、公开入口、能力 id、版本、依赖、提供者、契约摘要组成可验证声明；注册结果必须记录“新增/幂等复用/冲突/拒绝”，不能只打印 registered。
2. **生命周期编排模块**：以 `事件 id + 会话/调用 id + hook 名 + 序号` 形成事件 envelope，统一顺序、超时、取消、异常隔离、资源释放和回执；业务 hook 只能提交命令，不得绕过权威写 owner。
3. **质量门模块**：把“输入快照、规则版本、评估集摘要、样本数、每项分数、阈值、结论、拒绝原因、证据路径”固化成可重放记录，默认 fail-closed。
4. **确定性训练导出模块**：从不可变数据集快照生成确定性 JSONL/manifest，按内容摘要幂等复用；导出成功必须能读回文件、校验行数/摘要/模式契约，而不是信任命令 stdout。
5. **模型注册与发布模块**：训练任务、制品、评估、激活代、配置快照、宿主验证结果统一登记；一个模型版本一个权威记录，激活通过 CAS 指针切换。
6. **配置事务模块**：临时文件写入、权限、flush/fsync、原子 rename、解析校验、读回 hash、恢复意图和对账；跨 `.env`、registry、激活指针时必须由发布事务编排，不能由调用方拼接多个普通写入。
7. **多代回滚模块**：保留有序不可变快照和代际元数据，回滚是一次新的受审计发布事务；恢复后要重读实际宿主配置、检查激活指针、确认旧代可用，并可重复执行而不产生漂移。

### 12.2 锁、幂等、事务与多代回滚的目标契约

| 场景 | 锁/并发规则 | 幂等键 | 事务边界与失败恢复 | 必须留下的证据 |
|---|---|---|---|---|
| 插件注册 | 同一注册表/宿主作用域串行；锁覆盖“检查+写入”，不能只锁写入 | `宿主实例 + 插件 id + 版本 + manifest 摘要` | 声明校验、依赖解析、注册、回执为一个装配事务；部分注册必须反向卸载 | 声明摘要、注册前后版本、冲突项、卸载/回滚结果 |
| hook 分发 | 同一会话同一序号有序；跨会话可并行；共享状态写入用短锁 | `会话 id + 调用 id + hook + 序号` | hook 失败隔离；主流程不因非关键 hook 假成功，超时/取消进入统一清理 | 事件接收、开始/结束、耗时、结果、异常、是否重试 |
| 质量门 | 评估集/规则版本只读快照；同一候选评估避免并发覆盖 | `候选制品摘要 + 基线摘要 + 规则版本 + 评估集摘要` | 评分结果先写临时证据，完整后原子提交；缺样本/解析异常/宿主不可用必须拒绝 | 每样本结果、聚合方式、阈值、缺失项、最终结论 |
| 训练导出 | 输入快照锁定；同一数据集摘要不重复生成；不同摘要不可覆盖旧制品 | `fabric 快照摘要 + 模式 + 导出器版本` | 扫描→生成→校验→rename；中断只留下临时目录，恢复可复用或清理 | 快照清单、文件摘要、行数、pair 类型、token 估计、排除原因 |
| 模型注册/激活 | registry 和激活指针的 CAS/短锁；禁止两个 active 代 | `job id`、`output model`、制品摘要分别唯一 | 注册 pending→完成→评估→准备→激活→完成；任一步失败按状态机恢复 | 训练/评估/激活事务 id、旧/新代、版本指针、宿主验证 |
| 配置替换 | 每个 profile 的配置锁；临时文件名必须含事务 id，避免固定 `.tmp` 互踩 | `配置目标 + 事务 id + 目标代`；同一目标代重复提交返回原结果 | 写意图→备份/快照→临时写+fsync→原子替换→读回校验→更新 registry/指针；崩溃由恢复器对账 | 原配置摘要、新配置摘要、备份代、权限、读回结果、对账结果 |
| 回滚 | 回滚目标选择与激活切换 CAS；不能回滚到已删除或摘要不匹配代 | `发布事务 id + 目标代` | 回滚是新事务；切换前持久化意图，切换后写完成；强杀后按“指针是否已切+意图”恢复，重复恢复必须幂等 | 回滚原因、目标代、实际指针、健康检查、恢复/拒绝原因 |

Icarus 当前只实现了“单文件临时 rename + 单份备份”的局部原子性：`state.py:925-955` 与 `968-1005` 之间没有跨文件事务、锁、意图日志或多代快照。因此本节的锁、幂等、事务和多代回滚均是**底座映射契约**，不能回写成“Icarus 已具备”。

### 12.3 真实宿主验证与防假绿

现有 `scripts/test-plugin.sh` 是临时目录 fixture 测试，源码中还使用 fake Together 响应（`scripts/test-plugin.sh:773-805`），它能证明离线文件逻辑的一部分，但不能证明真实 Hermes 宿主契约、真实 provider、跨进程并发或远端 API。`scripts/smoke-handoff.sh` 当前还失败，且失败证据指向 `parse_id` 未去掉 frontmatter 引号（本文件第 9.2 节）。因此后续验收必须分层，不允许以“66 passed”覆盖宿主未验证和 smoke 失败：

| 验证层 | 通过标准 | 不能替代的证据 |
|---|---|---|
| 静态/离线 | manifest 与实际注册数一致；schema、入口、导出格式和失败形状可解析；测试进程退出码为 0 | 不能证明 Hermes 真加载、真实 provider 或并发安全 |
| 独立进程宿主冒烟 | 用真实 Hermes 版本/实际 profile 加载插件，读回注册表，实际触发四个 hook；检查插件退出、stdout/stderr、临时文件和 profile 状态 | 不能把手写 fake `ctx` 当宿主验证 |
| 真实写入回读 | 写 fabric、registry、配置、快照后由**新进程**重新解析；比较摘要、行数、active 指针和宿主实际读取值 | 不能只断言函数返回 `status=switched` |
| 质量门反向验证 | 缺证据、低分、空评估集、伪造 eval、样本不足、解析异常、宿主不可用均拒绝；删掉关键校验后测试必须变红 | 不能只测“好样本通过” |
| 崩溃/恢复 | 在写意图、原子替换前后、registry 更新前后强杀；新进程恢复；重复恢复、旧代/新代指针和残留临时文件均可判定 | 不能用同一进程内存状态模拟重启 |
| 外部 provider | Together API 采用真实隔离凭据/测试项目，记录 HTTP 状态、远端 id、超时和清理；无凭据时明确 `未验证` 而非 skip 伪绿 | fake response 只能测协议分支 |

**防假绿硬规则**：

- 测试命名必须与断言一致；“切换成功”至少包含配置读回、registry 读回、唯一 active 和新宿主进程读取四项。
- `skip`、打印 `pass`、历史 66/66、fake HTTP 返回、同进程 monkeypatch、存在备份文件，都只能记作局部证据，不能升级为真实通过。
- 任何线程/子进程测试结束都要扫描 stderr、回收进程组、确认端口/临时目录/锁不存在；线程异常被吞或只统计主线程结果属于假绿。
- 验证命令必须检查严格退出码；测试脚本应在失败时退出非零。当前 `smoke-handoff.sh` 的失败必须保留，直到重新运行得到退出码 0 并定位修复来源。
- 质量门本身要做恒真破坏：移除阈值、把错误响应当成功、跳过宿主读回、强制 active=true 后，独立测试必须失败；否则门禁不可证明。
- 训练导出要比较输入快照摘要和输出 manifest，不能只看 `total pairs` 文本；模型切换要比较 `.env` 与 registry 的旧/新代，不能只看返回 JSON。

### 12.4 后续落点与装配顺序

```text
插件 manifest/真实宿主适配器
  → 能力注册表（声明校验、版本、幂等、卸载）
  → 生命周期编排器（事件键、顺序、超时、回执）
  → 质量门（快照、规则、评估、拒绝证据）
  → 确定性训练导出（manifest、摘要、原子产物）
  → 模型注册表（任务/制品/评估/代际）
  → 发布事务（配置快照、CAS 激活、fsync、对账）
  → 多代回滚（恢复、健康检查、宿主读回）
```

建议装配顺序为：

1. 先冻结注册、hook、质量门、导出、registry、配置、回滚七项的公共结果/错误/证据契约，再登记能力和依赖，避免各模块自行维护错误码。
2. 先建设运行核心的文件锁、原子写、快照摘要、事务意图和恢复器；Icarus 适配层只负责把 Hermes/Together 字段映射到公共契约。
3. 再实现确定性导出和质量门；质量门必须依赖不可变输入快照，不直接扫描会继续变化的 `FABRIC_DIR`。
4. 再实现模型注册与发布事务；配置文件和 registry 不允许由两个普通 `write_text` 组成“伪事务”。
5. 最后接真实 Hermes 宿主、真实 profile、真实进程重启和可控 Together 验证；所有未执行外部验证保留为“未验证”，不得用 fixture 绿灯替代。

当前核对裁决：**插件注册、生命周期编排、质量门、训练导出、模型注册、配置原子替换、多代回滚都值得成为通用模块，但只有“注册/编排/证据/原子文件操作”的抽象可吸收；Icarus 的英文业务字段、正则评分、Together 直连、全局状态和单备份回滚必须留在项目适配层或被隔离。**

## 13. 旧细探吸收裁决与维护边界

### 13.1 吸收原则

本节是对 `细探-Icarus.md` 的逐项收口记录。旧细探已经完整阅读，并与当前 `main`/`e46cba3` 的源码、`README.md` 和 `LICENSE` 对照；能够由当前仓库证实的事实已写入本文件，并补上源码路径和边界条件。自本节之后，架构事实只维护本 `ARCHITECTURE.md`；`细探-Icarus.md` 保留为历史研究记录，不删除、不作为第二个持续维护的架构文档。

| 旧细探内容 | 裁决 | 在本文件中的落点与证据 |
|---|---|---|
| Icarus 是 Hermes 插件，不是独立应用；`register(ctx)` 注册 16 个工具和 4 个 hooks | 吸收 | 第 1、2、3、6.1、7.1 节；`plugin.yaml:1-26`、`__init__.py:42-89`。 |
| `FABRIC_DIR` 文件型记忆：Markdown + YAML frontmatter，支持跨 agent/跨实例共享 | 吸收并校准 | 第 2、5.1、6.2、8 节；`state.py:18-24`、`303-378`。共享目录是部署约定，不代表有并发一致性。 |
| 检索按关键词、项目、agent、新鲜度、tier、类型和引用链启发式排序，分两遍打分；无向量库也可运行 | 吸收 | 第 3、6.4、8 节；`fabric-retrieve.py:119-258`、`279-355`；`state.py:547-587`。 |
| 训练质量字段 `training_value`/`verified`/`evidence`/`outcome`，以及 `review_of`/`revises` 链路 | 吸收并补充 | 第 5.1、6.3、6.5、7.2 节；`tools.py:27-85`、`export-training.py:35-66`、`321-373`。当前源码还支持 `refs`，且引用目标会校验。 |
| 训练导出有 high-precision、normal、high-volume 三种模式 | 吸收并纠正输出清单 | 第 6.5、7.2、7.3 节；`export-training.py:425-472`。实际写出四个文件：`openai.jsonl`、`together.jsonl`、`hf-dataset.jsonl`、`raw-pairs.json`；旧细探遗漏了 `together.jsonl`。high-volume 明确不做质量过滤，不能笼统写成“噪声不会进入训练”。 |
| 记忆 → 训练数据 → Together AI 微调/评估 → 模型替换的纵向闭环 | 吸收 | 第 2、6.5、6.6、7.4 节；`state.py:590-615`、`618-665`、`685-805`、`839-880`、`scripts/eval-replacement.py:55-209`。 |
| 模型替换为 registry → eval 默认阈值 0.7 → `.env` 备份和临时文件 rename → 回滚 | 吸收并保留限制 | 第 6.6、10.1 节；`state.py:883-1011`。回滚不经过评估门禁，但不是“无条件成功”：依赖单份 `.env.backup`。 |
| `schemas.py`/`tools.py`/`hooks.py`/`state.py` 分层，`obsidian.py` 为可选 Markdown 浏览/格式化 | 吸收 | 第 3、4、8 节；对应模块源码和 `obsidian.py:47-148`。 |
| 会话开始注入上下文、主题变化时 recall、会话中捕获决策、会话结束评分并写 session note | 吸收并补足触发条件 | 第 6.2、9.1 节；`hooks.py:54-276`。决策捕获受 response/user 长度及 decision/outcome 正则约束，session 总分低于 0.2 时跳过。 |
| MIT 许可证、Python 纯标准库、英文正则/提示硬编码 | MIT 吸收；其余校准 | MIT 见 `LICENSE:1-21`；Python 运行主路径以标准库为主，但 `yaml` 存在时会改变 frontmatter 解析能力（第 8、10.1 节）；英文检测词、提示词和格式模式是当前实现风险（第 10.1 节）。 |
| 无锁共享目录写入、正则阈值未校准 | 吸收为风险 | 第 10.1 节第 1、2、9 项；`state.py:303-378`、`1056-1080`。 |
| “与另一平台的 CAS 激活指针同构”“平台应保留 CAS 语义”等底座建议 | 不吸收到 Icarus 事实 | 这是旧细探面向其他平台的迁移建议，不是 Icarus 当前源码事实；本文件只保留 Icarus 的 `.env`/`.env.backup` 行为及其风险。 |

### 13.2 未吸收或降级为待核事项

- 旧细探中“纯标准库”“噪声不污染训练数据”“无门槛回滚”均已按上表收窄：分别改为“主路径标准库但 PyYAML 可选”“仅质量模式过滤，高容量模式保留全量”“无 eval gate 但依赖备份”。
- 旧细探把 `openai.jsonl`、`hf-dataset.jsonl`、`raw-pairs.json` 概括为三格式；当前源码还输出 `together.jsonl`，故以源码为准。
- 旧细探提出的 Together AI 适配层、平台锁、CAS 指针、全中文命名等属于借鉴建议或外部底座裁决，当前项目没有对应实现，不冒充 Icarus 已有能力。
- 真实 Hermes 宿主 SDK 契约、Together AI 线上 API、跨进程并发语义和生产数据兼容性仍按第 10.2 节列为未确认项。

## 14. 本次变更边界

仅修改项目根目录唯一架构文档 `ARCHITECTURE.md`，将旧细探中仍有源码证据的事实吸收并追加后续底座映射、治理契约和防假绿规则。未修改源码、依赖、测试、配置或 `细探-Icarus.md`；未安装依赖、启动服务、构建项目、提交 Git，也未删除任何已有文件。当前 Icarus 根目录已存在独立 `.codegraph/`，本轮仅用目标目录内 `codegraph status`/`codegraph explore`；图谱只作定位辅助，源码事实仍以现场文件为准，不把错误项目（华世王镞_v3）上下文或其他项目图谱混入本项目结论。

## 15. 后续收口：入口、抽取、事件/存储/协议、资源与失败恢复

本节是针对“后续深挖”要求的收口，不把设计建议写成当前实现。证据基线仍为 `main/e46cba30fb95a0b54b7c4d6c26169a424283d72b`；本节引用的路径均为当前源码。Icarus 的核心事实是：它没有独立事件总线、数据库、守护进程或插件卸载 API，而是同步 Python 回调 + 共享文件 + Together AI HTTP 的单机插件。

### 15.1 Hermes 插件入口与真实宿主契约

| 契约面 | 当前实现 | 资源/错误/恢复边界 | 证据 |
|---|---|---|---|
| 清单 | `plugin.yaml` 声明 `name=icarus`、版本 `0.3.0`、16 个 `provides_tools`、4 个 `provides_hooks` | 清单本身没有 schema 版本、依赖版本、卸载动作、能力冲突策略或校验摘要；Hermes loader 不在本仓库，不能由清单证明真实宿主兼容 | `plugin.yaml:1-26` |
| Python 入口 | `register(ctx)` 按 memory → training → replacement → daily driver 的顺序调用 16 次 `ctx.register_tool`，随后注册 4 个 hook；无返回值 | 没有 `try/except`、重复注册幂等键、部分注册回滚或 teardown；第 N 次注册抛错时，前 N-1 项可能已经留在宿主上下文 | `__init__.py:42-89` |
| 工具 schema | `schemas.py` 只提供 LLM 可见的字典：`type/properties/required/enum/description` | schema 不是运行时校验器；没有超时、取消、重试、幂等键、错误码、版本协商或资源所有权字段 | `schemas.py:3-420` |
| handler 形状 | 所有 handler 接收 `args: dict, **kwargs`，成功和异常都序列化成字符串；工具层手写必填/枚举/引用校验 | 统一失败形状只有 `{"error": <str>}`，没有稳定 code、retryable、partial、request id；非字符串参数在 `.strip()`/数值转换处可能变成普通错误 | `tools.py:7-24`、`27-85`、`88-236` |
| hook 形状 | `on_session_start`/`pre_llm_call` 返回 `{"context": ...}` 或 `None`；`post_llm_call`/`on_session_end` 只产生副作用并返回 `None` | 没有宿主事件 envelope、顺序号、回执、取消 token、超时隔离或清理回调；`session_id`、exchange 缓冲和最近查询 token 放在模块全局 | `hooks.py:54-124`、`127-158`、`161-214`、`216-276`；`state.py:37-40` |

入口的真实调用链是：

```text
Hermes loader（源码外，未验证）
  → import Icarus package
  → register(ctx)
  → ctx.register_tool(name, toolset="fabric", schema, handler)
  → ctx.register_hook(name, callback)
  → 宿主在调用/会话生命周期时传入 dict/关键字参数
  → tools.py 或 hooks.py
  → state.py / fabric-retrieve.py / export-training.py / Together API
```

因此“16 tools + 4 hooks”是清单与注册代码事实，不等于“已被真实 Hermes 进程加载”。当前仓库没有 Hermes SDK 类型定义、loader 源码、版本锁定、真实宿主冒烟或插件卸载路径；这项仍是**宿主协议待核**，不可用 fixture `ctx` 代替。

### 15.2 记忆写入、检索和训练数据抽取的逐节点事实

#### 15.2.1 Fabric 记忆写入与读取

```text
tool args
  → tools.fabric_write 的必填/引用/枚举检查
  → state.write_entry
  → FABRIC_DIR.mkdir + 生成随机文件名/id + 直接 write_text
  → （可选）obsidian.format_entry + ensure_daily_note
  → 返回 path；工具再包装为 {status: written, path}
```

- `write_entry` 每次生成随机 8-hex `id`、随机 4-hex 文件后缀，并把 `agent/platform/timestamp/type/tier/summary/project_id/session_id` 写入 YAML frontmatter；可选字段包括 `tags/status/outcome/review_of/revises/customer_id/assigned_to/training_value/verified/evidence/source_tool/artifact_paths`（`state.py:303-378`）。这是一种“新文件追加式”写入，但不是严格 append-only：`curate_entry` 会直接改写既有 Markdown 的 `training_value`（`state.py:458-480`）。
- 工具层只强制 `type/content/summary`；`status=open` 要 `assigned_to`，`review` 要 `review_of`，`review_of/revises` 要满足 `agent:id` 且通过 `has_entry_ref`；没有对 `type/status/agent/tags/artifact_paths` 做完整枚举、长度、路径或权限校验（`tools.py:27-73`）。
- `read_recent`、`read_cross_agent`、`read_pending` 只扫描根目录 `FABRIC_DIR/*.md`，且 recent 要 `tier=hot`；`search_entries`、retriever、exporter 会扫描根目录和 `cold/*.md`。因此“共享 fabric 全量可见”不是所有 API 的同一读取语义（`state.py:381-419`、`483-544`；`fabric-retrieve.py:279-291`；`export-training.py:118-128`）。
- frontmatter 解析优先 `yaml.safe_load`，缺失/异常时使用简化 `key: value` 解析；同一文件在不同模块可能得到不同的复杂字段结果。写入的 `tags: [...]`、`artifact_paths: [...]` 仍是逗号字符串拼接，不是由统一 typed serializer 管理（`state.py:281-301`、`339-362`；`export-training.py:79-115`）。
- 检索为两遍启发式排序：扫描→关键词/摘要/短语/ngram/标签/项目/agent/新鲜度/tier/类型/工作流字段打分→取前 10 条的 refs/id 做第二遍 ref-chain 加分→过滤零分→按 `(agent,type,body 前 50 字符)` 去重→应用 `max_results` 和约 4 字符/token 预算；导入或执行失败回退 `read_recent`（`fabric-retrieve.py:119-258`、`261-355`；`state.py:552-587`）。

#### 15.2.2 训练数据抽取与模型评估

| 节点 | 实际输入/规则 | 实际产物与边界 |
|---|---|---|
| 扫描 | `FABRIC_DIR/*.md` + `cold/*.md`，逐文件 `parse_entry`；缺少起始 `---` 或 frontmatter 不完整的文件被跳过 | 读的是调用时正在变化的目录，没有快照摘要、锁、版本或一致性水位 | `export-training.py:79-128` |
| 质量选择 | `high-precision` 保留 `training_value=high`、verified、带 `review_of` 的 review、结构化 session、completed+evidence；`normal` 排除 low 且 session 需结构化/verified/high/evidence；`high-volume` 不过滤 | “质量门”是字段/正则启发式；`high-volume` 明确保留全量，不能写成噪声已阻断 | `export-training.py:22-66`、`425-436` |
| 基础 pair | outcome、`code-session/task/resolution/research`、dialogue、decision、结构化/普通 session、review 等按类型生成 input/output | body 少于 20 字符跳过；普通 session 只有 verified/high/evidence 才保留 generic pair | `export-training.py:183-272` |
| 关联 pair | `review_of` 找原条目，`revises` 找改进条目；旧 `refs` 支持 cycle/timestamp/filename 多级解析；显式 dedupe 后产生 `review-correction`；跨 platform 产生 `cross-platform` | writer 的当前 schema 没有 `refs` 字段，但 exporter 仍兼容历史 `refs`；引用解析找不到目标时静默跳过，不产生拒绝报告 | `export-training.py:131-162`、`274-373`；`schemas.py:35-116` |
| 加权与输出 | verified/evidence/high/review-correction/cross-agent/structured session 按 2–5 倍复制 pair | `total pairs` 是加权后的行数；同一语义 pair 可能多行，且没有数据集 manifest/内容 hash | `export-training.py:442-472`、`478-517` |
| 插件导出 | `state.export_training` 启动 `python3 export-training.py`，读取 stdout 统计、`together.jsonl` 和 `raw-pairs.json` | 输出在 `TemporaryDirectory` 中，函数返回后目录被清理；`fabric_export` 还删除 `_training_data`/`training_data_path` 后才返回工具结果，因此导出工具不留下可审计制品 | `state.py:618-665`；`tools.py:126-133` |
| 训练 | 先导出/自动选模式，再上传 multipart `/v1/files/upload`，然后 POST `/v1/fine-tunes`；成功后才写 pending registry | 上传成功但参数非法或创建任务失败时无远端文件删除；训练参数在上传后才校验；job id 侧车和 registry 不是一个事务 | `state.py:685-805` |
| 评估 | 从 high/training-completed 条目抽样，逐条顺序调用 base/candidate `/v1/chat/completions`；长度、正则、词频余弦得到三类分数 | API 异常被转成 `ERROR: ...` 文本，仍会进入评分；没有独立评估集快照、人工标签、统计置信度或候选制品摘要 | `scripts/eval-replacement.py:55-140`、`156-209` |

### 15.3 事件、存储和协议边界

Icarus 没有独立事件总线；源码中的“事件”是三种不同性质的记录，不能混称：

1. **生命周期回调**：Hermes 调用四个 Python callback；它们没有持久化事件 envelope。`hooks.py` 依赖进程内的 `state.session_id`、`state.exchanges`、`hooks._last_query_tokens`，进程退出即丢失未写入部分（`hooks.py:27-29`、`54-60`、`166-169`）。
2. **Telemetry JSONL**：`log_recall` 写 `event=recall`，记录 UTC 时间、query 截断、结果 id/summary、session/agent；`log_usage` 写 `event=usage`，只在被 recall 的 `review_of/revises` 引用时记账。两者均 append 一行，写失败直接吞掉；没有事件 id、schema version、顺序号、去重键、消费确认或重放器（`state.py:79-157`）。
3. **Fabric 条目/模型 registry**：Markdown 条目、`.icarus-state.json`、`.icarus-models.json`、job id 文本和 `.env` 是状态文件，不是事件流。registry 的 `pending/completed/failed/cancelled/error` 是外部任务状态投影，直接普通 JSON 覆盖，无迁移、锁、版本或 CAS（`state.py:55-76`、`808-836`）。

| 协议 | 线上的真实形状 | 失败语义 |
|---|---|---|
| Hermes 插件协议 | `ctx.register_tool(name, toolset="fabric", schema=dict, handler=callable)`；`ctx.register_hook(name, callback)` | 注册异常向宿主传播；handler 内异常被转换为 JSON 字符串；hook 异常未统一包裹，可能向宿主传播或中断生命周期，真实行为待宿主核验 |
| 本地 Markdown 协议 | `---` frontmatter + body；引用为 `agent:id`；文件名含 agent/type/slug/random suffix | 解析失败通常跳过或 fallback；没有 schema version、迁移、冲突解决、校验和或写入锁 |
| JSON/JSONL 侧车协议 | registry 是 `{"models": [], "active_model": ...}`；state 是 cycle/themes/questions/learnings；telemetry 是一行一个 JSON | corrupt JSON 回退空 registry/state；telemetry 单行坏数据跳过；普通写入中断可能留下截断文件，历史不会自动恢复 |
| Together HTTP 协议 | Bearer key；上传 `POST /v1/files/upload`；fine-tune `POST /v1/fine-tunes`；状态 `GET /v1/fine-tunes/{job_id}`；评估 `POST /v1/chat/completions` | `_together_request` 固定 30 秒；上传 60 秒；评估子进程总上限 300 秒、单请求 30 秒；无重试、退避、幂等 header、远端清理或响应 schema 校验，仅取预期 JSON 字段 |
| 模型激活协议 | 读取 Hermes `${HERMES_HOME}/.env`，过滤并追加 `LLM_MODEL/OPENAI_BASE_URL/OPENAI_API_KEY`，临时文件 rename，再写 registry | `.env` 单文件替换具有局部原子性；`.env` 与 registry 更新不是同一事务；宿主是否立即重读 `.env` 未验证 |

### 15.4 资源生命周期与释放责任

| 资源 | 创建/持有 | 正常释放 | 业务失败/超时 | 崩溃/残留风险 |
|---|---|---|---|---|
| Fabric/Obsidian 文件 | `Path.mkdir`、`write_text`；可选 format/daily 二次写 | Python 文件调用结束后句柄关闭；无显式 fsync | Obsidian 二次写失败只 debug 日志，原 fabric 条目保留；直接写失败由工具转 error 或部分文件风险 | fabric、daily、`.obsidian/app.json` 均无临时文件/恢复意图；并发写可能互相覆盖 |
| JSON/JSONL 侧车 | registry/state/job 使用 `write_text`，telemetry 使用 `open(...,"a")` | `with open` 的 telemetry 正常关闭；普通 `write_text` 依赖调用返回 | registry 保存异常只 warning；state/telemetry 写异常部分被吞；无校验后重写 | 中断可留下半 JSON；下一次 `_load_registry/load_creative` 退回空结构，造成静默丢历史 |
| 导出临时目录 | `state.export_training` 使用 `tempfile.TemporaryDirectory`，子进程在其中写 4 个输出 | `with` 正常退出/异常退出都会清理目录 | 子进程非零返回错误；`TimeoutExpired` 未在 `export_training` 内单独转换，但会被上层 handler 捕获；目录上下文仍负责清理 | 子进程默认不建立独立进程组；超时/强杀时孙进程残留未被扫描 |
| Together HTTP response | `urllib.request.urlopen` 返回 response，读取 JSON | 代码只 `read()`，没有 `with`/显式 close 责任 | HTTP、JSON、超时统一进入少量 error 分支；无重试/断点 | 连接/远端任务不由本地恢复器管理；上传文件可能成为孤儿 |
| 评估子进程 | `subprocess.run(..., timeout=300)` 启动 `eval-replacement.py` | 正常返回后进程结束；超时由 `subprocess.run` 处理 | 捕获 `TimeoutExpired` 返回 `eval timed out`；非零和非法 JSON 返回 error | 未设置 `start_new_session`/进程组；子进程的网络请求或孙进程不保证随树清理，未读回残留 |
| `.env` 与备份 | `shutil.copy2` 覆盖单份 `.env.backup`；固定 `.tmp` 写入后 rename | rename 后临时名通常消失 | 缺 key 检查发生在备份之后；写失败不主动删除 `.tmp`；registry 保存失败会留下已切配置 | 无 fsync、权限显式设置、意图日志或多代备份；并发切换会争用同一 `.tmp/.backup` |
| 内存态 session | hook 维护全局 exchanges、recall log、last query tokens | 新 session 重置部分 buffer；end 写 session/memory | 低分 session 跳过 session 条目，但仍先写 `memories/MEMORY.md`；中途异常无 checkpoint | 宿主进程崩溃丢失未落盘 exchange、creative 变更和未追加 telemetry |

结论是：Icarus 的“释放”主要依靠 Python `with` 和 shell `trap` 的正常/异常退出清理，资源治理并未形成统一 owner。`test-plugin.sh`/`smoke-handoff.sh` 对测试临时根目录使用 `trap 'rm -rf ...' EXIT`（`scripts/test-plugin.sh:5-8`、`scripts/smoke-handoff.sh:5-8`），这只能证明测试夹具清理，不证明生产路径的文件、进程、连接和远端制品可恢复。

### 15.5 失败与恢复矩阵

| 场景 | 当前行为 | 可证明的恢复程度 | 未实现/风险 |
|---|---|---|---|
| 空 query、缺必填、非法 training value、缺引用 | handler 直接返回 `{"error": ...}`；引用缺失时不写新条目 | 单次调用 fail-closed，未发现半写入 | 没有错误码/可重试标记；调用方只能解析字符串 |
| retriever import/解析/排序异常 | `state.recall` 回退 `read_recent`；无结果返回空 | 有降级读路径 | fallback 只看 hot 根目录，结果语义改变且没有降级事件证据 |
| corrupt registry/state/telemetry 行 | registry/state 解析异常回退默认空对象；telemetry 坏行跳过 | 进程能继续 | 静默丢失历史；没有 quarantine、备份选择、告警门禁 |
| 导出脚本缺失/非零/超时 | 缺文件或非零转 error；超时由工具外层捕获 | 临时目录上下文清理 | 不返回输入快照/已生成文件摘要；可能无法区分子进程残留 |
| 上传失败/无 file id | 返回 `upload failed` 或 no file ID | 不写本地 pending registry | 无远端幂等/删除；网络重试可能重复上传 |
| 上传成功但参数非法/创建 fine-tune 失败/无 job id | 参数在上传后校验；创建失败或无 id 直接返回 | 本地不登记无 job 的任务 | Together 已上传文件可能孤儿；固定参数错误的失败路径不是事务回滚 |
| status 请求失败/远端 failed | 返回 error；若有 registry 且状态为 failed/cancelled/error 才更新状态 | 已登记任务能留下失败状态 | 状态更新普通覆盖；无轮询调度、重试、取消 API、远端任务补偿 |
| eval 网络错误/超时/非零/非法 JSON | 子进程返回 error，不更新 registry；单请求异常会生成 `ERROR:` 文本并继续评分 | 调用层不把坏 stdout 写成 registry 分数 | 异常响应可能污染分数；无 per-sample failure manifest；无 process-group 清理 |
| switch 无 home/env/registry/eval/达标分数 | 在各前置检查处返回 error；低分和无分数拒绝 | 发布前门禁存在 | key 检查在备份之后，可能留下新 `.env.backup`；无宿主健康检查 |
| `.env` 已 rename、registry 写失败/进程崩溃 | `.env` 可能已切到新模型，registry 仍旧 active 或损坏 | 单文件 rename 可避免半个 `.env` | 两文件 split-brain；无意图日志、对账恢复或 CAS；固定 `.tmp` 残留风险 |
| rollback 无 backup/复制成功后 registry 失败 | 无备份返回 error；复制后按恢复模型更新 registry | 能恢复最近一份 `.env` | 只有一份备份；恢复模型不在 registry 时 `active_model=null`；registry 失败仍会 split-brain |
| session/hook 中途崩溃 | 未写入的 exchanges/creative/telemetry 丢失；已写 fabric 文件保留 | 已完成的独立文件仍可被下次读取 | 无 checkpoint、幂等 hook key、重放或清理协议；全局状态不适合并发 session |
| Obsidian format/daily 写失败 | `state.write_entry` 保留主条目，异常只 debug | 主写与可选展示解耦 | daily/link 不一致不会进入错误结果；无补偿队列 |

### 15.6 后续验证等级与剩余待核

| 验证项 | 当前核对证据 | 等级/结论 |
|---|---|---|
| Python 语法 | `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile __init__.py schemas.py tools.py hooks.py state.py obsidian.py fabric-retrieve.py export-training.py scripts/eval-replacement.py`，退出码 0 | **静态通过**；不证明宿主/网络 |
| 离线 fixture | `PYTHONDONTWRITEBYTECODE=1 bash scripts/test-plugin.sh`，退出码 0，`66 passed, 0 failed` | **局部通过**；覆盖文件逻辑、训练 pair、模型切换 fixture、Obsidian fixture；未证明真实 Hermes/Together/并发/崩溃恢复 |
| handoff 冒烟 | `PYTHONDONTWRITEBYTECODE=1 bash scripts/smoke-handoff.sh`，退出码 1；在 `reviewer session-start includes source id` 处失败 | **未通过，必须保留**；`state.write_entry` 用 `_yaml_scalar` 将 id 写成带引号标量（`state.py:281-283`、`327-330`），而脚本 `parse_id` 仅 `.strip()` 不去引号（`scripts/smoke-handoff.sh:63-67`）；`hooks.on_session_start` 读回 frontmatter 后把带引号值放入上下文（`hooks.py:72-90`）。这是当前测试夹具与生产写入格式的契约漂移证据，不在当前核对范围内修复 |
| 真实宿主加载 | 仓库无 Hermes loader/SDK 类型/实际 profile 进程验证 | **未验证** |
| Together 线上 API | 仅 fixture fake response；当前核对无凭据、无网络写入 | **未验证**；不能把 fake response 当外部协议通过 |
| 多进程/并发 | 无锁、无 CAS、无压力或故障注入测试 | **未验证且有明确风险** |
| 进程崩溃/恢复 | 无意图日志、恢复器、进程组扫描、远端补偿测试 | **未验证且当前没有实现证据** |

后续收口结论：**Hermes 入口和工具/hook 的源码链路已闭合；记忆与训练抽取规则、文件/JSON/JSONL/HTTP 协议边界已闭合；资源释放与失败恢复的“有实现/只有局部/没有实现”边界已明确。**当前能称为已实现的是同步单进程、临时目录清理、检索降级、工具错误字符串、单文件 `.env` rename 和单份备份；不能称为已实现的是宿主版本契约、事件总线、持久事件重放、跨文件事务、并发一致性、远端幂等/清理、进程树回收、崩溃恢复和多代回滚。后续只维护本文件，旧 `细探-Icarus.md` 仍为历史记录，不构成第二事实源。
