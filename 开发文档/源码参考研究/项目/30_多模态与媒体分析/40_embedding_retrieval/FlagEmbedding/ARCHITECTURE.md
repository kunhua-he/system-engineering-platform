# FlagEmbedding 架构建档

> 本文是本地源码归档 `FlagEmbedding` 的首轮全量架构记录。说明、备注、风险与结论使用中文；源码路径、类名、函数名、字段名、模型名和命令保留原文。
>
> **研究边界**：只读分析源码、README、依赖、入口、数据结构、API、测试和远程版本；本次仅新增本文件，没有修改源码、依赖、测试、配置、模型权重或运行环境。

## 1. 项目身份与版本边界

| 项目 | 事实 |
|---|---|
| 项目名 | `FlagEmbedding`（BAAI/FlagOpen） |
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/40_embedding_retrieval/FlagEmbedding` |
| 上游仓库 | `https://github.com/FlagOpen/FlagEmbedding.git` |
| 许可证 | 仓库代码标注 MIT；模型权重、Hugging Face 远程代码和数据集须按各自许可证另行核对 |
| 本地基线 | `7ed43d67ec03fbe5c31c0992dbfa941fb1860549`，`2026-04-22T23:57:32+08:00`，`Merge pull request #1575 from hanhainebula/master` |
| 远程基线 | `292ad785dea715f8cd509b8177f6e48618e6b137`，`2026-08-14T14:16:02+08:00`，`Update README.md` |
| 新鲜度 | 本地 `HEAD...origin/master` 为 `0/2`：远程领先 2 个提交；已通过 `127.0.0.1:4780` 在 `/tmp/FlagEmbedding-remote-snapshot` 建立独立快照核对 |
| 远程差异 | `git diff HEAD..origin/master --stat` 显示仅 `README.md`、`README_zh.md` 发生文档变更；抽查 `setup.py`、两个 `model_mapping.py` 与独立快照一致。远程 `README.md` 新增资助说明，不改变运行时架构。 |
| 归档留痕 | 已存在的 `细探-FlagEmbedding.md` 作为前置细探输入，本轮不删除、不改写；有效结论已吸收进本文件。 |

## 2. 项目定位

FlagEmbedding 是 BGE（BAAI General Embedding）面向 Search 和 RAG 的一站式检索工具箱。它不是数据库、HTTP 服务或完整 RAG 编排平台，而是以 Python API、Hugging Face 模型加载、训练脚本和评测脚本为中心的模型能力库，覆盖：

- **嵌入**：将 query/corpus 编码为 dense 向量；支持 encoder-only、decoder-only、ICL、pseudo-MoE 等模型族。
- **多功能嵌入**：`BGEM3FlagModel` 同时产出 dense、sparse/lexical 和 ColBERT multi-vector 表征。
- **重排**：将 query-passage 对输入 cross-encoder 或 decoder-only reranker，直接产生相关性分数，并可 sigmoid 归一化。
- **自动分发**：`FlagAutoModel`、`FlagAutoReranker` 根据模型名或显式 `model_class` 选择实现。
- **训练与评测**：统一的抽象参数、数据集、collator、runner/trainer，以及 BEIR、MTEB、MIRACL、MKQA、MLDR、MS MARCO、AIR-Bench 等评测入口。
- **研究实验**：BGE-M3、Visualized-BGE、BGE-VL、LLM Embedder、LLM Reranker、Long LLM、LM-Cocktail、C-MTEB 等研究代码并置在 `research/`，与稳定推理包边界不同。

## 3. 总体流程图

```text
文本 query / corpus                         query-passage 对
        │                                          │
        ▼                                          ▼
FlagAutoModel.from_finetuned()          FlagAutoReranker.from_finetuned()
        │                                          │
        ├─ model_mapping.py                       ├─ model_mapping.py
        │  ├─ encoder-only-base                    │  ├─ encoder-only-base
        │  ├─ encoder-only-m3                      │  ├─ decoder-only-base
        │  ├─ decoder-only-base                    │  ├─ decoder-only-layerwise
        │  ├─ decoder-only-icl                     │  └─ decoder-only-lightweight
        │  └─ decoder-only-pseudo_moe                       │
        ▼                                          ▼
AbsEmbedder → tokenizer + Transformer      AbsReranker → tokenizer + Transformer
        │                                          │
        ├─ encode_queries()                        ├─ get_detailed_inputs()
        ├─ encode_corpus()                         ├─ compute_score()
        ├─ encode()                                └─ normalize(sigmoid，可选)
        └─ 单设备 / multiprocessing spawn                  │
        │                                          relevance scores
        ├─ dense_vecs: ndarray                     │
        ├─ lexical_weights: List[Dict]             ▼
        └─ colbert_vecs: List[ndarray]       top-k 重排结果 / RAG 后续消费
        │
        ▼
向量相似度、稀疏匹配、ColBERT 匹配 → 检索 / RAG

训练数据 JSON/JSONL
        │
        ▼
Abs*TrainDataset → datasets.load_dataset → collator → Runner/Trainer
        │
        ├─ hard negatives: scripts/hn_mine.py
        └─ teacher scores: scripts/add_reranker_score.py

评测 corpus.jsonl + *_queries.jsonl + *_qrels.jsonl
        │
        ▼
AbsEvalDataLoader → Searcher → Evaluator/metrics → 各评测报告
```

## 4. 代码分层与职责

### 4.1 稳定包入口与抽象契约

- `FlagEmbedding/__init__.py`：从 `FlagEmbedding.abc.inference` 和 `FlagEmbedding.inference` 汇总公共推理 API。
- `FlagEmbedding/abc/inference/AbsEmbedder.py`：嵌入抽象。统一设备发现、dtype（fp16/bf16/fp32）、query instruction、`encode_queries`、`encode_corpus`、`encode`、单设备/多进程编码、输出转换和 Matryoshka `truncate_dim`。
- `FlagEmbedding/abc/inference/AbsReranker.py`：重排抽象。统一 query/passage instruction、`compute_score`、单设备/多进程评分、批处理和可选 `normalize`。
- `FlagEmbedding/abc/finetune/`：训练的 `AbsArguments`、`AbsDataset`、`AbsModeling`、`AbsRunner`、`AbsTrainer` 等边界。
- `FlagEmbedding/abc/evaluation/`：评测的参数、数据加载、检索、评估器、runner 和工具契约。

### 4.2 推理工厂与映射

- `FlagEmbedding/inference/auto_embedder.py`：`FlagAutoModel.from_finetuned(model_name_or_path, model_class=None, ...)`。
  - 先取路径 basename；`checkpoint-*` 会回退到父目录名。
  - 显式 `model_class` 时查 `EMBEDDER_CLASS_MAPPING`，否则查 `AUTO_EMBEDDER_MAPPING`。
  - `EmbedderConfig` 同时携带实现类、`PoolingMethod`、`trust_remote_code` 和 query instruction 模板。
  - 最终返回 `FlagModel`、`BGEM3FlagModel`、`FlagLLMModel`、`FlagICLModel` 或 `FlagPseudoMoEModel` 的实例。
- `FlagEmbedding/inference/reranker/auto_reranker.py`：`FlagAutoReranker.from_finetuned(...)` 使用 `RERANKER_CLASS_MAPPING`、`AUTO_RERANKER_MAPPING`，最终返回 `FlagReranker`、`FlagLLMReranker`、`LayerWiseFlagLLMReranker` 或 `LightWeightFlagLLMReranker`。
- `FlagEmbedding/inference/embedder/model_mapping.py`：模型族、`EmbedderModelClass`、`PoolingMethod`、`EmbedderConfig` 和 `support_model_list()`；当前映射包含 BGE、Qwen3 Embedding、E5、GTE、SFR、Linq、BCE，并明确 TODO 仍可扩展 Jina、Stella_v5、NV-Embed 等。
- `FlagEmbedding/inference/reranker/model_mapping.py`：BGE reranker 以及 Jina、GTE、BCE 等外部模型的自动映射。

### 4.3 嵌入实现

- `FlagEmbedding/inference/embedder/encoder_only/base.py`：`BaseEmbedder` 使用 `AutoTokenizer`、`AutoModel`；默认 `cls` pooling，兼容 `mean`，可归一化、截断维度、自动降低 batch size 以应对运行时显存错误。
- `FlagEmbedding/inference/embedder/encoder_only/m3.py`：`M3Embedder` 包装 `EncoderOnlyEmbedderM3ModelForInference`；`encode_single_device()` 返回 `dense_vecs`、`lexical_weights`、`colbert_vecs` 三类结果，并提供 `convert_id_to_token()`、`compute_lexical_matching_score()`、`colbert_score()` 和多模式 `compute_score()`。
- `FlagEmbedding/inference/embedder/decoder_only/`：面向 decoder-only 基座的普通、ICL、pseudo-MoE 表征；主要依赖 last-token pooling、instruction 模板和可选 few-shot examples。
- 单设备流程通常为：分词（不 padding）→ 按输入长度排序减少 padding → tokenizer.pad → Transformer 前向 → pooling/归一化/截断 → 恢复原顺序 → ndarray 或 Tensor。
- 多设备流程由 `AbsEmbedder.start_multi_process_pool()` 建立 `spawn` 进程、输入/输出队列，每个进程调用 `encode_single_device()`，最后按 chunk id 排序拼接。

### 4.4 重排实现

- `FlagEmbedding/inference/reranker/encoder_only/base.py`：encoder-only cross-encoder，输入 query-passage pair，读取分类 logits 作为分数。
- `FlagEmbedding/inference/reranker/decoder_only/base.py`：decoder-only 模型以提示词和 `Yes` 等目标 token 的 logits 产生分数。
- `decoder_only/layerwise.py`：允许 `cutoff_layers` 选择输出层，减少推理成本或获得多层结果。
- `decoder_only/lightweight.py`：在 layerwise 之外支持 `compress_ratio`、`compress_layers` 等轻量化参数。
- `AbsReranker.compute_score()` 接受单个 pair 或 pair 列表，统一应用 query/passage instruction，单设备直接评分，多设备走进程池；`normalize=True` 时将分数映射到 0–1。

### 4.5 微调、研究与评测

- `FlagEmbedding/finetune/embedder/`：encoder-only base/M3、decoder-only base/ICL 的 `arguments.py`、`dataset.py`/`modeling.py`、`runner.py`、`trainer.py` 和 `__main__.py`。
- `FlagEmbedding/finetune/reranker/`：encoder-only base、decoder-only base、layerwise 等训练实现，支持 LoRA、PEFT、DeepSpeed、flash-attn 等可选能力。
- 训练命令入口是 `python -m FlagEmbedding.finetune....`，脚本先用 `HfArgumentParser` 解析三类 dataclass，再由 Runner 组织模型、数据和 Trainer。
- `FlagEmbedding/evaluation/`：按评测集拆分 `beir`、`mteb`、`miracl`、`mkqa`、`mldr`、`msmarco`、`bright`、`air_bench`、`custom` 等，统一从 `AbsEvalDataLoader` 获得 corpus、queries、qrels，再连接 searcher/evaluator。
- `research/` 是论文/实验集合，不等同于 `FlagEmbedding/` 稳定公共 API。重点包括 `BGE_M3`、`visual_bge`、`BGE_VL`、`BGE_VL_Screenshot`、`llm_embedder`、`llm_reranker`、`Long_LLM`、`LM_Cocktail`、`C_MTEB`、`Reinforced_IR`、`Matroyshka_reranker`、`MLVU` 等。

## 5. 真实目录结构

以下为当前本地工作树的实际结构摘要（源码约 540 个 `.py`、49 个 `.md`、112 个 `.json`、72 个 `.jsonl`、23 个 `.sh`；不计 `.git`）：

```text
FlagEmbedding/
├── FlagEmbedding/                         # 可安装 Python 包
│   ├── __init__.py
│   ├── abc/                               # inference / finetune / evaluation 抽象契约
│   ├── inference/                         # embedder、reranker、auto factory、mapping
│   ├── finetune/                          # 训练实现与命令模块
│   ├── evaluation/                        # 各基准评测实现
│   └── utils/                             # transformers 兼容层等
├── examples/
│   ├── inference/                         # embedder/reranker 单设备与多设备示例
│   ├── finetune/                          # embedder/reranker 数据、配置与训练示例
│   └── evaluation/                        # 评测示例
├── dataset/                               # 训练/评测数据说明与数据入口
├── Tutorials/                             # 从安装到检索/RAG 的教程与图片
├── research/                              # 研究项目、论文复现、实验代码
├── scripts/                               # hard negative、teacher score、长度切分
├── tests/                                 # 推理基础测试与 Transformers 兼容性测试
├── docs/                                  # 文档站点依赖与静态网页材料
├── imgs/                                  # README/教程图片
├── README.md / README_zh.md               # 项目入口与模型列表
├── setup.py                               # 包元数据、依赖和 finetune extra
├── Manifest.in / LICENSE / .gitignore
└── 细探-FlagEmbedding.md                  # 既有人工细探输入（本轮保留）
```

## 6. 数据模型与接口契约

### 6.1 推理数据

| 场景 | 输入 | 输出/语义 |
|---|---|---|
| 普通嵌入 | `str` 或 `List[str]` | `np.ndarray`/`torch.Tensor`；单字符串为一维向量，批量为二维矩阵 |
| query 嵌入 | `encode_queries(queries, batch_size, max_length, ...)` | 在 `query_instruction_for_retrieval` 与 `query_instruction_format` 下编码 |
| corpus 嵌入 | `encode_corpus(corpus, ...)` | 通常不自动加入 query instruction；支持独立 passage instruction |
| BGE-M3 | `return_dense`、`return_sparse`、`return_colbert_vecs` | 字典键固定为 `dense_vecs`、`lexical_weights`、`colbert_vecs`；未请求的值为 `None` |
| 重排 | `Tuple[str,str]` 或 `List[Tuple[str,str]]` | `compute_score()` 返回单个 float 或分数列表；`normalize=True` 时 sigmoid 到 0–1 |
| 设备 | `None`、字符串、整数或列表 | 自动选择 CUDA/NPU/MUSA/MPS/CPU；多设备使用 `spawn` worker |

### 6.2 微调 JSON/JSONL

嵌入训练的常用行结构为：

```json
{"query": "...", "pos": ["..."], "neg": ["..."], "pos_scores": [1.0], "neg_scores": [0.1], "prompt": "...", "type": "..."}
```

- `query` 为查询；`pos`、`neg` 必须是文本列表。
- `pos_scores`、`neg_scores` 在 `knowledge_distillation=True` 时必须存在且为数值列表；关闭蒸馏时会被移除/忽略。
- `prompt` 可覆盖 query instruction；`type` 用于 ICL、对称分类/聚类等数据分支；`batch_size`、`train_group_size` 也可作为数据列参与组 batch。
- `AbsEmbedderTrainDataset` 从文件或目录加载 JSON/JSONL，通过 `datasets.load_dataset('json', ...)` 拼接数据，随机选择一个正例并抽取负例，输出 `(query, passages, teacher_scores)`；`AbsEmbedderCollator` 再产出 `queries`、`passages`、`teacher_scores`、`no_in_batch_neg_flag`。
- 重排训练复用 `query`、`pos`、`neg`、可选 `pos_scores`、`neg_scores`、`prompt`；其模型输入语义为 `query [sep] passage [sep] prompt`。

### 6.3 评测数据

`AbsEvalDataLoader` 约定：

- `corpus.jsonl`：每行至少含 `id`、`text`，可选 `title`；加载后形成以文档 id 为键、以 `{title, text}` 为值的 `DatasetDict`。
- `<split>_queries.jsonl`：每行含 `id`、`text`，形成 query id 到文本的映射。
- `<split>_qrels.jsonl`：每行含 `qid`、`docid`、`relevance`，形成 query id 到文档相关性表的映射。
- 数据可从 `dataset_dir` 读取，也可通过具体评测子类从远程 Hugging Face/数据源下载并缓存；默认 split 为 `test`，支持 `force_redownload`。

## 7. 依赖、运行资源与入口

`setup.py` 当前版本为 `1.4.0`，核心依赖为：

- `torch>=1.6.0`
- `transformers>=4.44.2,<6.0.0`
- `datasets>=2.19.0`
- `accelerate>=0.20.1`
- `sentence_transformers`、`peft`、`ir-datasets`、`sentencepiece`、`protobuf`
- `finetune` extra：`deepspeed`、`flash-attn`

主要入口：

```text
pip install -U FlagEmbedding
pip install -U 'FlagEmbedding[finetune]'

from FlagEmbedding import FlagAutoModel, FlagAutoReranker
model = FlagAutoModel.from_finetuned('BAAI/bge-base-en-v1.5')
reranker = FlagAutoReranker.from_finetuned('BAAI/bge-reranker-v2-m3')

python -m FlagEmbedding.finetune.embedder.encoder_only.base ...
python -m FlagEmbedding.finetune.embedder.encoder_only.m3 ...
python -m FlagEmbedding.finetune.reranker.encoder_only.base ...
python scripts/hn_mine.py ...
python scripts/add_reranker_score.py ...
python scripts/split_data_by_length.py ...
```

模型默认从本地路径或 Hugging Face Hub 加载；推理通常需要较大的 CPU 内存或 GPU 显存，训练还需要分布式 `torchrun`、DeepSpeed/flash-attn/LoRA 等资源。库本身没有 HTTP 路由、数据库 schema 或常驻服务入口。

## 8. 测试与当前可验证范围

`tests/README.md` 与实际测试文件显示：

- `tests/test_imports_v5.py`：验证 Transformers 5.0 移除 `is_torch_fx_available` 后，`FlagEmbedding/utils/transformers_compat.py` 的兼容导入，以及 inference/finetune 的 MiniCPM reranker 模块可导入。
- `tests/test_infer_embedder_basic.py`：下载 `BAAI/bge-base-en-v1.5`，验证单条/批量 embedding 类型、维度、非 NaN 和相关文本 cosine similarity。
- `tests/test_infer_reranker_basic.py`：下载 `BAAI/bge-reranker-base`，验证单条/批量分数类型、长度、范围和相关段落排序。
- `tests/conftest.py`：根据 `torch.cuda.is_available()` 在 CUDA 或 CPU 选择设备，并提供 Transformers 版本 fixture。

本轮未安装依赖、未下载模型、未启动推理/训练/评测，故没有把未执行的模型测试冒充为通过。可按仓库说明在隔离虚拟环境执行 `pytest tests/`；重型模型测试受网络、缓存、显存和上游模型可用性影响。

## 9. 风险、边界与备注

1. **模型/代码信任边界**：`trust_remote_code` 可从模型仓库加载远程实现；生产接入前必须 allowlist 模型、固定 revision 并审查代码。
2. **资源边界**：PyTorch、Transformers 和大模型是硬依赖；多设备路径会创建 `spawn` 进程并共享模型内存，不适合未经隔离地塞进轻量 Web 进程。
3. **输出兼容性**：普通 embedder 输出 ndarray/Tensor，BGE-M3 输出多模态字典；下游必须明确 dense、lexical、ColBERT 三种索引和分数融合的存储契约。
4. **指令与 pooling**：query instruction、`query_instruction_format`、`pooling_method`、`normalize_embeddings` 会改变向量语义；query 与 corpus 的预处理必须成对固定。
5. **自动映射覆盖**：未知模型名会抛 `ValueError`；自定义模型应显式传 `model_class` 或补充 mapping，不应依赖名称猜测。
6. **训练数据质量**：负例、教师分数、`type`、batch 标志等字段影响采样和蒸馏；必须在进入训练前做 schema、长度、数值和数据集版本校验。
7. **研究代码隔离**：`research/` 中实验实现、旧示例和模型代码不能直接视为稳定 API；接入前需单独验证依赖、许可证、权重和测试覆盖。
8. **版本漂移**：本地归档落后远程 2 个提交，但差异目前为 README 文案；后续若远程改动 `FlagEmbedding/`、`setup.py` 或示例契约，应重新做版本快照和架构复核。
9. **没有服务层**：仓库只提供库和脚本，不负责向量数据库、检索编排、权限、租户隔离、模型生命周期或 HTTP API；这些应由上层平台承担。

## 10. 可借鉴结论（仅架构裁决，不启动实现）

- **吸收**：以 `AbsEmbedder`/`AbsReranker` 为边界的能力契约；以 `FlagAutoModel`/`FlagAutoReranker` 为参考的能力注册表和提供者路由；query/corpus 分离编码；BGE-M3 的 dense + lexical + multi-vector 多粒度输出；训练/评测数据的显式 JSONL 契约。
- **废弃**：不直接复制其重型 PyTorch/GPU 训练栈到业务 API 进程；不把 `research/` 实验目录当作生产稳定组件；不把模型权重或远程代码的 MIT 代码许可扩大解释为全链路许可。
- **待核**：若要进入真实平台，需要继续确认目标模型 revision、量化/显存预算、向量库对多向量与稀疏权重的支持、分数融合策略、服务化进程边界、数据集和权重许可证，以及在目标环境的最小推理回归集。

**首轮结论**：FlagEmbedding 的核心价值是“模型推理抽象 + 自动模型路由 + 多粒度表征 + 可复用训练/评测流水线”，不是完整检索产品。可把稳定 `FlagEmbedding/inference/` 的抽象和数据契约作为上层嵌入/重排适配器的参考；任何生产化接入都必须将模型进程、缓存、索引和安全边界独立治理。

## 11. 旧细探吸收裁决与本轮深挖边界

### 11.1 唯一事实源声明

本轮已完整读取 `细探-FlagEmbedding.md`（68 行）并逐条对照当前源码；旧文件**保留、不删除、不改写**，只作为历史输入。自本节起，FlagEmbedding 的架构事实、契约、风险和验证状态只维护本 `ARCHITECTURE.md`；旧细探中的“BGE-M3 三合一、FlagAutoModel、bge-reranker、PyTorch/GPU、MIT 与权重许可分离”等结论均已吸收，未再把旧文件当作当前实现证据。

旧细探内容的吸收映射如下：

| 旧细探结论 | 当前源码对照 | 裁决 |
|---|---|---|
| BGE 一站式 Search/RAG 工具箱 | `setup.py:6-30`、`FlagEmbedding/__init__.py`、`inference/`、`evaluation/` | 吸收；定位准确，但不是数据库/HTTP/RAG 服务 |
| BGE-M3 dense + lexical + ColBERT | `inference/embedder/encoder_only/m3.py:310-486`、`:625-732` | 吸收；返回键和分数融合的真实约束补入本文件 |
| `FlagAutoModel` 自动分发 | `inference/auto_embedder.py:22-115`、`inference/embedder/model_mapping.py:10-274` | 吸收；补充 basename/checkpoint 回退、未知模型 `ValueError` 和 `trust_remote_code` |
| reranker/cross-encoder | `inference/auto_reranker.py:23-81`、`inference/reranker/encoder_only/base.py:77-195` | 吸收；补充 pair 预处理、sigmoid 可选及多进程失败语义 |
| “无 LLM 提示词” | 稳定推理不做生成，但 `FlagLLMModel`/`FlagLLMReranker` 使用 decoder-only 模型和 instruction | 修正为“不是聊天式 LLM 编排；存在 decoder-only embedding/rerank prompt” |
| 重型 PyTorch/GPU 需隔离 | `abc/inference/AbsEmbedder.py:319-355`、`AbsReranker.py:250-281` | 吸收；补入进程池无超时/错误回传的真实风险 |

### 11.2 版本与源码证据边界

- 代码事实以本地 `HEAD=7ed43d67ec03fbe5c31c0992dbfa941fb1860549` 为准；远程领先 2 个提交且已知仅 README 文档差异的结论沿用第 1 节，未把远程声明当作本地实现。
- 细探中出现的 `flag_embedding/` 是非当前目录名的旁路线索；当前可安装包实际为 `FlagEmbedding/`，已以 `setup.py:14` 的 `find_packages()` 和真实目录为准。
- 本轮只修改本文件；未修改源码、测试、配置、依赖、权重、缓存或 Git 记录。

## 12. 深层契约表：输入、输出、所有权和失败语义

下表是从实现读取的契约，不是 README 宣称；“未提供”表示代码没有对应机制，不能由调用方自行假定。

| 公开入口/证据 | 输入与默认值 | 输出契约 | 错误/重试/超时/取消/幂等 | 资源责任 |
|---|---|---|---|---|
| `FlagAutoModel.from_finetuned()` (`inference/auto_embedder.py:22-115`) | `model_name_or_path`；可选 `model_class`、pooling、dtype、设备、instruction、`truncate_dim` | 返回具体 `AbsEmbedder` 子类；映射模型名取 basename，`checkpoint-*` 取父目录名 | 未知映射抛 `ValueError`；无自动重试、超时、取消或幂等键；HF 下载/模型初始化异常向上传播 | 子类创建 tokenizer/model；调用方持有实例并需调用 `stop_self_pool()`，析构函数仅尽力清理 |
| `AbsEmbedder.encode_queries/encode_corpus()` (`abc/inference/AbsEmbedder.py:172-241`) | `str` 或 `List[str]`；query 使用 query instruction，corpus 从 `kwargs` 取 passage instruction；batch/max length 可覆盖 | 普通模型为一维/二维 `np.ndarray` 或 `torch.Tensor`；M3 为 `{dense_vecs, lexical_weights, colbert_vecs}`，未请求项为 `None` | 空列表未在抽象层拒绝；具体实现可能在 `np.concatenate` 处失败；无调用级 deadline/cancel/idempotency | 单设备模型移动到目标 device；多设备使用共享模型和 spawn worker |
| `AbsEmbedder.encode()` (`abc/inference/AbsEmbedder.py:243-298`) | 可选 instruction；单字符串强制单设备路径；多元素且多设备才建 pool | 保持输入顺序；多进程按 `chunk_id` 排序后拼接 | worker 异常没有错误消息回传；父进程 `output_queue.get()` 无 timeout，可能永久等待；无取消协议 | `self.pool` 长驻实例，`stop_self_pool()` 才终止；`__del__` 非确定性 |
| `BaseEmbedder.encode_single_device()` (`inference/embedder/encoder_only/base.py:174-282`) | tokenizer 截断至 `max_length`，按 token 长度排序；默认 `cls`，可 `mean`；可归一化/截断 | `convert_to_numpy=True` 时 `np.ndarray`，否则 Tensor；恢复原顺序；单字符串返回一维 | 试算批次捕获 `RuntimeError`/OOM 后把 batch 缩为 `3//4`，没有重试上限或最小值保护；空输入没有显式结果契约 | forward 使用 `torch.no_grad()`；CPU 触发 `model.float()`；返回 numpy 时移回 CPU |
| `M3Embedder.encode_single_device()` (`inference/embedder/encoder_only/m3.py:310-486`) | 可选择 dense/sparse/ColBERT；token 权重过滤特殊 token 和非正权重；ColBERT 去掉 padding/CLS | 三键字典；sparse 是 token-id→权重列表，ColBERT 是变长 token 向量列表；单字符串各值退化为单项 | 同样存在无界 batch 缩减；`return_dense=False` 时不能交给只接受 dense 的 `EvalDenseRetriever`；没有融合配置持久化 | dense 转 numpy；sparse/ColBERT 变长结果由调用方存储/释放 |
| `M3Embedder.compute_score()` (`m3.py:488-538`) | pair 或 pair 列表；可选 `weights_for_different_modes` | 单 pair 返回各模式标量，多 pair 返回五个列表：`colbert`、`sparse`、`dense`、两种融合 | 权重只用 `assert len==3`；两模态融合分母可能为 0；多进程等待无 timeout；无取消/幂等 | 多设备临时 pool 在正常返回后显式停止；异常路径没有 `finally` 保证停止 |
| `AbsReranker.compute_score()` (`abc/inference/AbsReranker.py:157-229`) | tuple 或 pair 列表；query/passage instruction 预处理；单设备直接算，多设备队列 | 单 pair 由具体实现决定；`BaseReranker` 返回 `float`/`List[float]`；可 sigmoid 到 0–1 | 空输入先访问 `[0]`；reranker worker 捕获所有异常后直接退出，父进程仍无 timeout，可能假死；无取消/幂等 | pool 挂在 `self.pool`；`stop_self_pool()` 终止并回收进程，析构仅尽力 |
| `BaseReranker.compute_score_single_gpu()` (`inference/reranker/encoder_only/base.py:77-195`) | pair tokenization；query 默认 `3/4 * max_length`；cross-encoder `AutoModelForSequenceClassification` | logits 展平为 float，按原顺序；`normalize=True` 对 logits 做 sigmoid | 与 embedder 同样无界 batch 缩减；非法 pair/空 list 为断言或索引异常；没有推理 deadline | `no_grad`；模型 `.to(device).eval()`；CPU 时禁用 fp16 |
| `AbsEmbedderTrainDataset`/`AbsEmbedderCollator` (`abc/finetune/embedder/AbsDataset.py:23-242`) | JSON/JSONL；`query`、`pos[]`、`neg[]`；蒸馏时必须有数值 `pos_scores`/`neg_scores`；随机正例和负例采样 | collator 输出 `queries`、`passages`、`teacher_scores`、`no_in_batch_neg_flag` | 字段缺失、类型不符、空正/负列表可能由 `KeyError`/`AssertionError`/随机采样异常暴露；无 schema 版本、幂等或取消语义 | HF datasets cache、Python 随机状态、tokenizer batch 由训练进程持有 |
| `AbsEvalDataLoader` (`abc/evaluation/data_loader.py:97-169,232-423`) | 本地 `corpus.jsonl`、`<split>_queries.jsonl`、`<split>_qrels.jsonl`，或远程子类下载；默认 split `test` | `DatasetDict`/字典式 id 映射；缺 split 时 `ValueError`，缺本地文件可回退远程下载 | `wget/gzip/unzip` 用 `subprocess.run(check=True)`，失败后检查文件并抛 `FileNotFoundError`；没有 subprocess timeout、下载取消或断点事务 | cache/save_dir 写文件和目录；失败可能留下部分文件/解压目录，未见回滚清理 |
| `EvalDenseRetriever`/`EvalReranker` (`abc/evaluation/searcher.py:71-248`) | corpus/query 字典；FAISS top-k；reranker 截断 top-k | dense 返回 `{qid:{docid:score}}`；rerank 返回重排 score 字典 | corpus embedding 复用只按 `doc.npy` 存在性和 `overwrite` 判断；无模型/参数 hash；缺 docid 可能 KeyError；无超时/取消 | FAISS index 内存、可选 `doc.npy`、模型 pool；正常路径由 evaluator 调 `stop_multi_process_pool()` |
| `AbsEvalRunner.run()`/`AbsEvaluator.__call__()` (`abc/evaluation/runner.py:186-229`, `evaluator.py:102-260`) | 参数解析后的模型、数据集、split、输出目录 | 搜索 JSON、`EVAL/eval_results.json`、可选 Markdown/JSON 汇总 | 已有结果按 `overwrite` 复用并校验 eval/model/split/dataset 元数据；过程失败无统一事务/回滚；空/无效 split 可能跳过而日志仍显完整 | 写输出目录、HF cache、corpus embedding；检索完成后停 pool，但异常中断缺少统一 finally |

**契约裁决**：这是批处理库接口，不是可取消的服务 RPC。调用方必须自行提供请求级超时、进程隔离、模型/参数版本、输入校验、失败重试策略、结果原子落盘和幂等键；不能把“函数返回”解释成有服务级交付保证。

## 13. 真实对接调用链

### 13.1 普通嵌入/重排链

```text
调用方
  → FlagAutoModel.from_finetuned(model_name_or_path, model_class?, devices?, trust_remote_code?)
  → AUTO_EMBEDDER_MAPPING / EMBEDDER_CLASS_MAPPING
  → FlagModel / BGEM3FlagModel / FlagLLMModel / FlagICLModel / FlagPseudoMoEModel
  → AutoTokenizer.from_pretrained + AutoModel/自定义 M3 model
  → AbsEmbedder.encode_queries() / encode_corpus()
  → AbsEmbedder.encode()
  → BaseEmbedder/M3Embedder.encode_single_device()
  → tokenize(no padding) → length sort → pad → model forward
  → pooling/last-token 或 M3 dense+sparse+ColBERT → truncate/normalize
  → 恢复输入顺序 → numpy/Tensor/三键字典

调用方
  → FlagAutoReranker.from_finetuned()
  → AUTO_RERANKER_MAPPING / RERANKER_CLASS_MAPPING
  → FlagReranker / FlagLLMReranker / LayerWiseFlagLLMReranker / LightWeightFlagLLMReranker
  → AbsReranker.get_detailed_inputs()
  → AbsReranker.compute_score()
  → BaseReranker.compute_score_single_gpu() 或 decoder-only/layerwise/lightweight 实现
  → pair tokenize → model logits/目标 token logits → 可选 sigmoid
  → float 或 score list
```

### 13.2 多设备链

```text
encode()/compute_score()
  → target_devices = get_target_devices(None|显式设备)
  → len(devices)>1 时 start_multi_process_pool()
  → model.to("cpu") + model.share_memory()
  → multiprocessing.get_context("spawn") 创建每设备 daemon worker
  → encode_multi_process()/AbsReranker.encode_multi_process()
  → input Queue: [chunk_id, chunk, kwargs]
  → worker 调单设备实现并向 output Queue 写 [chunk_id, result]
  → 父进程按 chunk_id 排序、拼接、返回
  → 调用方显式 stop_self_pool()/stop_multi_process_pool()
```

这条链没有协议级错误队列、任务取消标记、输出 queue 超时、worker heartbeat 或崩溃检测；因此“多设备调用没有异常返回”不能证明成功，可能只是父进程阻塞在 `Queue.get()`。

### 13.3 训练链

```text
python -m FlagEmbedding.finetune.<family>.<mode>
  → HfArgumentParser(model_args, data_args, training_args)
  → Abs*Runner.__init__()
  → 检查 output_dir 非空与 overwrite_output_dir
  → set_seed()
  → load tokenizer + base/custom model
  → AbsEmbedderTrainDataset 或 SameDatasetTrainDataset
  → datasets.load_dataset('json') + 随机正/负例/蒸馏分数
  → AbsEmbedderCollator（tokenize/pad/sub_batch）
  → Hugging Face Trainer（可选 LoRA/DeepSpeed/flash-attn/gradient checkpoint）
  → train(resume_from_checkpoint) → save_model()
```

训练 runner 只在 `run()` 正常返回后保存模型；异常/取消/宿主崩溃的 checkpoint 一致性、恢复点和临时文件清理由 Transformers/外层运行器承担，本仓库没有统一事务或作业状态存储。

### 13.4 评测链

```text
评测 __main__ / AbsEvalRunner
  → FlagAutoModel + 可选 FlagAutoReranker
  → 具体 AbsEvalDataLoader：本地文件优先，缺失时远程下载并 cache
  → AbsEvaluator.__call__()
  → load corpus/queries/qrels
  → EvalDenseRetriever：encode_corpus/query → FAISS index/search → NoReranker/*.json
  → 可选 EvalReranker：截断 top-k → pair → compute_score → reranker/*.json
  → evaluate_metrics()/evaluate_mrr()/evaluate_recall_cap()
  → EVAL/eval_results.json + 可选 markdown/json 汇总
```

## 14. 关键节点明细表

| 节点 | 前置条件 | 状态/读写对象 | 调用者→被调用者 | 并发与失败分支 | 恢复动作 |
|---|---|---|---|---|---|
| 自动映射 | 模型 basename 必须在 mapping，或显式 `model_class` | 读映射；创建模型对象，无持久化状态 | `AbsEvalRunner`/业务调用方 → `FlagAutoModel`/`FlagAutoReranker` | 未知名 `ValueError`；远程代码/权重下载异常直接上抛 | 显式类、固定本地路径/revision；外层记录失败，不隐式换模型 |
| 单设备预处理 | tokenizer 可用；输入可迭代 | 临时 `all_inputs`、排序索引、batch tensors | `AbsEmbedder.encode_single_device` → tokenizer | 长文本按 max length 截断；空输入、非法字段未统一校验 | 调用方先校验非空、字符串类型和最大长度；外层限制 batch |
| 单设备 forward | model 已初始化；device 可用 | model device/eval 状态；GPU/CPU tensors | Base/M3/Reranker 单设备实现 → Transformers/PyTorch | Runtime/OOM 自动降 batch，但无上限；其他异常上抛 | 外层捕获、重建隔离进程；不能把降 batch 当无限可靠重试 |
| M3 输出转换 | 输出包含模型要求的 dense/sparse/ColBERT 字段 | token 权重字典、变长向量、dense ndarray | M3 forward → `_process_token_weights`/`_process_colbert_vecs` | 特殊 token 被丢弃；不同模态开关产生 `None`；融合权重 assert/零分母风险 | 固定三模态配置和版本；存储层分别声明维度/词表/变长策略 |
| 多设备调度 | `model` 非空；每设备一个 worker | 共享 model、input/output Queue、daemon 进程 | 抽象层 → `spawn` worker → 单设备实现 | worker 崩溃/异常不入错误队列；父 `get()` 无 timeout | 外层 watchdog/进程级 timeout；超时终止整个 pool 并丢弃批次，禁止复用未知状态 |
| 训练数据采样 | JSON/JSONL 含 query/pos/neg；KD 时含分数 | HF Dataset cache；随机采样结果 | Runner → Dataset → `datasets.load_dataset` | 空 neg、字段类型错、缓存/网络失败；同批同数据策略会改变 batch size/worker | 数据 schema 预检；数据版本、seed、采样配置随作业记录 |
| FAISS 检索 | dense embedding 为二维 float 可转换数组；k 合法 | 内存 FAISS index；可选 `doc.npy` | Evaluator → EvalDenseRetriever → `index`/`search` | GPU FAISS fallback 仅打印；空 corpus/query 会在 FAISS/concatenate 处失败 | 外层检查维度/数量；指定 CPU/GPU 构建；结果写入前校验行数 |
| 评测持久化 | 输出目录可写；输入元数据一致 | corpus cache、search JSON、EVAL JSON | Evaluator → `save_search_results`/metric output | `overwrite` 不是事务；多 split/多阶段中途失败可有部分输出 | 临时目录+原子 rename 由外层提供；读回 JSON 元数据与结果数量 |

## 15. 资源生命周期与清理证据

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消 | 崩溃/残留风险与验证 |
|---|---|---|---|---|
| tokenizer/model | 子类构造 `from_pretrained`；实例持有 | `stop_self_pool()` 将 model 移 CPU，`gc.collect()`；对象析构尽力 | 初始化失败由 HF/PyTorch 上抛；无统一 rollback | 进程被 kill 时 GPU 显存由 OS 回收，但缓存/下载目录可能残留；需外层查询子进程与 GPU |
| GPU/CPU tensors | 单设备 forward、padding、M3 输出 | numpy 转换时移 CPU；函数局部引用释放 | OOM 路径只缩 batch，未显式 `empty_cache()`；异常时局部对象生命周期不确定 | 外层进程隔离并读回显存/进程；不能用日志代替资源检查 |
| multiprocessing pool | `start_multi_process_pool()` 建 `spawn` daemon、两条 Queue | `stop_multi_process_pool()` `terminate`→`join`→`close`；M3 正常 compute 路径显式停 | 父等待无 timeout；异常路径没有 `finally`，池可能留在 `self.pool` | worker 崩溃、僵尸、Queue feeder 残留需 `ps`/进程组检查；仓库无自动 watchdog |
| input/output Queue | pool 创建；批次写入 input，worker 写 output | pool 停止时 close | 无 cancel sentinel；父 `get()` 无 timeout；缺结果永久阻塞 | 超时后必须终止进程组、关闭 Queue、确认无残留；不能只捕获 Python 异常 |
| HF cache/下载文件 | `datasets`/Transformers cache；评测 `wget` 写 save_dir | 成功后长期保留以复用 | 下载/解压失败可能留下零字节或部分目录；无回滚/清理 | 需检查零字节、临时压缩包和目录；缓存 key 不等于模型 revision 证明 |
| corpus embedding / FAISS | `EvalDenseRetriever` 生成 `doc.npy`，FAISS 在内存建立 | 进程退出/引用释放；pool 单独 stop | 写 `doc.npy` 非原子；失败可能半文件；FAISS build 失败无事务 | 对 `.npy` 用 `np.load`、shape、dtype、行数和 corpus 数量读回；验证无半成品 |
| 评测 JSON/报告 | `os.makedirs` + `open(...,"w")` 直接写 | 文件关闭由上下文/函数结束保证 | 中断可能产生部分 JSON；overwrite 可能覆盖旧结果 | 用 JSON parse、元数据、query 数量和模型名回读；外层应采用临时文件原子替换 |
| 训练输出/checkpoint | `Path(output_dir).mkdir`、Trainer 写 checkpoint | `save_model()` 正常完成 | 训练中断可能留下不完整 checkpoint；resume 语义由 Trainer 决定 | 需检查 config/tokenizer/权重文件完整性和可重新加载；本轮未运行训练 |
| 远程代码/权重许可 | `trust_remote_code`、HF model/revision | 无库级撤销；由进程/缓存持有 | 代码执行、下载断线和权限错误向上抛 | 生产侧必须 allowlist revision、隔离执行、审计缓存和许可证；未在本地实测 |

**四终态结论**：正常完成有显式 stop/close 的主要路径；业务失败可上抛但清理不全；主动取消/超时没有库内协议；宿主/worker 崩溃没有统一恢复。资源清理只能标记“代码存在/正常路径可见”，不能标记“所有异常终态已验证”。

## 16. 失败、超时、取消与崩溃矩阵

| 场景 | 代码行为 | 是否有库内可靠恢复 | 防止误判的外层动作 |
|---|---|---|---|
| 未知模型名/错误显式类 | auto factory 抛 `ValueError` | 有明确失败，但无候选回退 | 记录 model path/class，禁止自动换模型 |
| 空 query/corpus/pair | 多处先访问 `[0]` 或最终 `concatenate([])` | 否，异常类型不统一 | API 入口拒绝空批，测试空输入契约 |
| 非法输入字段/坏 JSON | `KeyError`、`AssertionError`、`ValueError` 或 datasets 异常 | 部分，未统一 schema | 预校验字段、类型、数组长度和数值 |
| 单设备 OOM/RuntimeError | 试算批次捕获后 `batch_size *= 3//4` | 无界重试；可能降到 0 或永不成功 | 设置外层 deadline、最小 batch=1、失败后销毁进程 |
| 多设备 worker 异常 | embedder/M3 worker 不回传异常；reranker worker `except:` 直接退出 | 否；父进程可能永久阻塞 `output_queue.get()` | watchdog 监控 worker exitcode/heartbeat；超时杀池并整批重放 |
| 下载/解压失败 | subprocess 检查失败后检查路径，最终 `FileNotFoundError` | 有错误返回，无清理/超时 | subprocess 外层 timeout；删除或隔离部分文件，校验 hash |
| FAISS GPU 不可用 | broad `except` 打印后继续 CPU/GPU 原 index | 有 fallback，但只靠日志，不是结构化状态 | 读取 FAISS 实际 index 类型/device，校验检索结果 |
| 评测 split 不存在 | warning 后移除；无 split 时 evaluator 直接 return | “跳过”是合法路径，易被误当成功 | 把有效 split 数、写出文件数纳入验收；0 split 必须失败作业 |
| 重复评测/已有 cache | `overwrite=False` 复用文件，元数据校验有限 | 有复用，无全参数 hash/幂等协议 | 将模型 revision、instruction、pooling、dtype、dataset hash 纳入外层键 |
| 主动取消/请求超时 | 没有取消 token/sentinel/deadline API | 否 | 外层进程组 kill、Queue close、结果目录临时化、现场读回 |
| 宿主/子进程崩溃 | OS 回收进程资源；业务输出可能半写/缺 chunk | 无业务恢复/补偿 | 只接受完整结果；检查 exitcode、文件 parse、数量和无残留 |

## 17. 防假绿验证等级（L0-L4）

| 等级 | 能证明什么 | 本仓库证据 | 本轮状态与不能宣称 |
|---|---|---|---|
| L0 源码/结构存在 | 路径、符号、入口和文档存在 | `search_files` 盘点 154 个包 `.py`、4 个测试 `.py`；关键路径见第 3/12 节 | 已完成静态盘点；不证明可导入/可运行 |
| L1 语法/静态一致 | Python AST 可解析，ARCHITECTURE 结构/旧细探保留 | 本轮验证命令见第 18 节 | 只证明语法和文档约束，不证明依赖、模型或设备 |
| L2 依赖/导入/单元边界 | 在隔离环境能 import、mock 边界行为 | `tests/test_imports_v5.py` 存在，但本轮未把“文件存在”算通过 | 未验证；没有现成 mock 测试覆盖空输入、OOM、worker 崩溃、取消 |
| L3 真实模型推理/训练 | 下载真实权重，完成 embedding/rerank 或训练最小步 | 现有 `test_infer_embedder_basic.py`、`test_infer_reranker_basic.py` 会联网加载 BGE | 未验证；本轮未安装依赖、下载权重、占 GPU、训练或启动评测 |
| L4 外部闭环/生产条件 | revision/许可证、网络、GPU、多进程、FAISS、评测数据、重启恢复均实测 | 仓库没有服务/部署/生产闭环测试 | 未验证；不能把 README、pytest 名称、日志或历史快照当 L4 |

验收规则：L0/L1 通过只能写“源码存在/可解析”；L2 通过也只能写“边界可导入/单测通过”；只有 L3/L4 的实际命令、退出码、测试数、外部依赖和资源清理证据齐全，才能写对应级别通过。

## 18. 本轮验证记录与可复现命令

### 18.1 已执行

以下命令均为只读或不写源码的检查；退出码以本轮实际执行结果为准，模型推理未被假装执行：

| 命令 | 目的 | 退出码/结果 |
|---|---|---|
| `git status --short --branch && git rev-parse HEAD && git log -1 --format='%H%n%cI%n%s' && git diff --stat` | 记录版本与工作树边界 | `0`；`master...origin/master [behind 2]`；仅 `ARCHITECTURE.md`、`细探-FlagEmbedding.md` 为未跟踪输入 |
| `shasum -a 256 '细探-FlagEmbedding.md'` | 固定旧细探基线，防止误改 | `0`；基线 `17ce0e238c0a2b58e1afab870130256ffa494aef996f8f360b572e4c32d65a04` |
| `codegraph_explore`（专属 MCP） | 读取代码图可信度与最近证据 | MCP 返回：项目无 `.codegraph/`，未建立代码图；不能据此声称有图证据 |
| `project_context`（专属 MCP） | 核对项目绑定 | 首次连续 3 次不可达；恢复后返回 `MCP实例=project_toolkit`，但错误绑定 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是目标根；按错绑如实记录，未冒充成功绑定 |
| `verify_and_record`（专属 MCP） | 收口验证门禁 | `git diff --check` 返回退出码 `0`、判定“通过”、验证类型“弱”；但元数据仍是错绑项目且提示 `MCP_WORK_CONTEXT_MISMATCH`，故只能记录为 MCP 弱验证，不能作为 FlagEmbedding 目标证据 |
| `AST` 静态解析 | 解析包源码和测试源码 | 退出码 `0`；输出 `AST_OK files=158` |
| 文档/旧细探保留断言 | 检查新增章节、流程图和旧文件非空 | 退出码 `0`；输出 `DOC_OK old_detail_preserved` |
| `pytest --collect-only -q -p no:cacheprovider tests/test_imports_v5.py` | 尝试测试收集 | 环境无 `pytest`，shell 报 `/bin/bash: pytest: command not found`；该项未通过、未计入成功 |
| 旧细探 SHA-256 | 确认写入后未改旧细探 | 退出码 `0`；仍为 `17ce0e238c0a2b58e1afab870130256ffa494aef996f8f360b572e4c32d65a04` |

### 18.2 复核命令（本轮结果已记录）

```bash
cd "/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/40_embedding_retrieval/FlagEmbedding"
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast, pathlib; files=list(pathlib.Path("FlagEmbedding").rglob("*.py"))+list(pathlib.Path("tests").rglob("*.py")); [ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in files]; print(f"AST_OK files={len(files)}")'
python3 -c 'from pathlib import Path; p=Path("ARCHITECTURE.md").read_text(); old=Path("细探-FlagEmbedding.md"); assert "## 12. 深层契约表" in p and "## 17. 防假绿验证等级（L0-L4）" in p and (chr(96)*3+"text") in p and old.exists() and old.stat().st_size > 0; print("DOC_OK old_detail_preserved")'
PYTHONDONTWRITEBYTECODE=1 pytest --collect-only -q -p no:cacheprovider tests/test_imports_v5.py
shasum -a 256 "细探-FlagEmbedding.md"
git diff --name-only -- ARCHITECTURE.md "细探-FlagEmbedding.md"
```

模型测试命令（`pytest tests/test_infer_*.py`）未列为本轮通过：它们会联网下载 `BAAI/*` 权重，且当前任务禁止安装依赖/生成缓存/占用模型资源；需要独立隔离环境和资源清理证据后才能升级到 L3。

## 19. 吸收/不吸收裁决

| 类别 | 结论 |
|---|---|
| **吸收** | `AbsEmbedder`/`AbsReranker` 作为统一推理边界；auto mapping 作为“显式版本化能力注册表”参考；query/corpus 与 query/passage 指令分离；M3 三种表征分开输出；训练 JSONL 和评测 corpus/query/qrels 显式契约；按输入长度排序降低 padding 的批处理策略；评测结果带模型/数据元信息的复用思路 |
| **废弃/不直接吸收** | 将重型 PyTorch/HF 模型直接放入业务 API 进程；把 `research/` 或远程代码当稳定插件；把 `doc.npy` 存在即视为参数一致；把无 timeout 的多进程队列直接当服务 RPC；把 broad `except`、warning、输出文件或 pytest 名称当成功证据 |
| **待核** | 目标模型 revision/hash 与许可证；生产设备/量化/显存预算；M3 sparse/ColBERT 的索引和融合契约；进程/服务边界；外层超时取消/watchdog/原子写入/幂等协议；训练恢复与评测缓存一致性；Transformers 4/5、FAISS CPU/GPU、MPS/多进程组合 |

## 20. 未验证项与剩余风险清单

1. 未在当前环境下载或加载任何模型，不能确认具体 BGE/Qwen/GTE checkpoint 与本地 Transformers 版本的运行兼容性。
2. 未执行 GPU/NPU/MUSA/MPS 多设备路径；`AbsEmbedder.get_target_devices()` 与 `AbsReranker.get_target_devices()` 对 MPS 多卡和显式整数设备的差异需单独实测。
3. 未验证空输入、超长输入、batch 自动缩减到 0、零融合权重、坏 JSON、缺失字段、重复 docid/query id 和 `k > corpus` 的行为契约。
4. 未验证 worker 抛异常、worker 被 kill、父进程超时、Queue 关闭、模型 forward OOM 后的进程组和 GPU 残留。
5. 未验证 `trust_remote_code=True` 的远程代码审计、revision pin、模型/数据权重许可和缓存污染边界。
6. 未验证训练 `resume_from_checkpoint` 在中断 checkpoint、LoRA merge fallback、DeepSpeed/flash-attn 下的一致性。
7. 未验证评测下载工具在断线、超时、磁盘满、部分文件、重复运行下的原子性和清理。
8. `evaluate_recall_cap()` 在相关文档数为 0 时存在除零风险（`abc/evaluation/utils.py:73-88`）；`search()` 对空 query 结果的 `np.concatenate` 也没有显式空集契约（`:214-228`）。这些是源码风险记录，不是本轮修改项。
9. `FlagAutoModel` 的 `model_name` 依赖 basename；同名本地目录或 checkpoint 可能路由到同一实现，外层必须记录完整 path/revision。
10. 本轮专属 MCP `system_engineering_toolkit` 的 `project_context` 未成功返回，代码图明确报告无索引；因此本文件的代码事实证据来自直接读取当前源码，不能声称 MCP 绑定或代码图验证成功。

## 21. 证据索引与维护规则

核心证据入口：

- 推理抽象和 pool：`FlagEmbedding/abc/inference/AbsEmbedder.py`、`AbsReranker.py`；
- 自动路由：`FlagEmbedding/inference/auto_embedder.py`、`auto_reranker.py`、两份 `model_mapping.py`；
- 具体实现：`inference/embedder/encoder_only/base.py`、`m3.py`、`inference/reranker/encoder_only/base.py` 及 decoder-only 同目录；
- 训练：`FlagEmbedding/abc/finetune/embedder/AbsRunner.py`、`AbsDataset.py`、各 `finetune/**/__main__.py`/`runner.py`；
- 评测：`FlagEmbedding/abc/evaluation/data_loader.py`、`searcher.py`、`evaluator.py`、`runner.py`、`utils.py`；
- 真假验证：`tests/test_imports_v5.py`、`test_infer_embedder_basic.py`、`test_infer_reranker_basic.py`、`conftest.py`；
- 依赖边界：`setup.py`；
- 历史输入（保留）：`细探-FlagEmbedding.md`。

后续维护只更新本文件：源码路径变更时重做第 12-18 节；旧细探只保留为历史输入，不再建立第二份架构事实源。任何未来“已通过”结论都必须给出命令、退出码、测试数、外部依赖、输入/输出校验和资源清理现场。

## 22. 第三轮：通用底座映射总览

本节不是把 FlagEmbedding 直接搬进平台，而是把当前源码已经稳定表达的能力拆成“文本支持库、向量支持库、检索模块、模型提供者、运行核心、统一网关”六个边界，逐项给出吸收、升级、隔离或待核裁决。事实基线仍为本地源码；前一轮 `project_context` 返回的是 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3` 的错误绑定，本轮不采用其代码图、任务记忆或验证结论，以下仅使用目标目录的本地静态读取，验证等级按弱验证处理。

### 22.1 目标单链路

```text
统一网关（HTTP/MCP可选适配：鉴权、请求契约、租户、deadline、取消、限流、统一错误）
  → 检索模块（query/corpus 编排、top-k、候选集、重排与结果排序）
  → 文本支持库（字符串/文档字段归一、query/corpus 或 query/passage 指令、长度预算）
  → 向量支持库（dense、lexical、ColBERT multi-vector 的契约、校验、序列化）
  → 模型提供者（FlagAutoModel/FlagAutoReranker 映射 + Hugging Face tokenizer/model）
  → 运行核心（设备选择、批预算、进程隔离、deadline/watchdog、OOM/崩溃回收）
  → GPU/CPU/NPU/MUSA/MPS、HF cache、FAISS 或其他受管后端
```

FlagEmbedding 在这条链中实际覆盖的是“模型提供者的参考实现”和“检索模块的离线评测实现”：`FlagEmbedding/inference/` 提供模型加载和编码/打分；`FlagEmbedding/abc/evaluation/searcher.py` 与 `abc/evaluation/utils.py` 提供 FAISS 检索和评测编排。它没有实现上图的统一网关、租户、认证、请求级取消、资源租约、结果事务或常驻服务。

### 22.2 现有能力命中表

| 源码事实 | 底座归属 | 映射方式 | 裁决 |
|---|---|---|---|
| `AbsEmbedder.encode_queries()`、`encode_corpus()`、`encode()`；`get_detailed_instruct()`；`BaseEmbedder.pooling()` 与 decoder-only `last_token_pool()` | 文本支持库 + 向量支持库公开契约 | 文本支持库只负责输入角色、指令模板、长度/类型预检；向量支持库负责输出维度、dtype、归一化、截断和批次对齐；模型提供者执行 tokenizer/forward/pooling | **吸收接口语义，升级契约**；不复制其无界 batch 和隐式 instruction 状态 |
| `BaseEmbedder.encode_single_device()` 的长度排序、padding、恢复原顺序 | 运行核心的批处理策略 | 作为可复用的“按 token 长度分桶/排序”策略；批大小由运行核心预算器决定，结果必须带请求/输入序号 | **吸收算法，升级治理** |
| `M3Embedder.encode_single_device()` 的 `dense_vecs`、`lexical_weights`、`colbert_vecs` | 向量支持库 | 三种表示分别建字段和版本；不能只按 dense 处理后丢失其他模态 | **吸收多表征契约，待核索引后端** |
| `FlagAutoModel.from_finetuned()`、`FlagAutoReranker.from_finetuned()` 与两份 `model_mapping.py` | 模型提供者注册/选择 | 将 basename/别名映射改为唯一能力注册表；完整 model path、revision、class、pooling、instruction、dtype 必须进入模型身份 | **吸收路由思想，禁止名称猜测成为生产唯一依据** |
| `BaseReranker.compute_score_single_gpu()`、decoder-only `Yes` token logits、layerwise/lightweight 的 `cutoff_layers`/压缩参数 | 模型提供者 + 检索模块重排阶段 | provider 输出原始/归一化分数及 score space 元数据；检索模块只负责候选 top-k、调用重排和显式排序 | **吸收 reranker 边界；分数校准待核** |
| `EvalDenseRetriever`、`EvalReranker` | 检索模块 | 拆出在线/离线两种执行策略；FAISS 仅作为 provider，不让评测类成为网关业务 | **吸收离线链路，升级在线契约** |
| `start_multi_process_pool()`、`encode_multi_process()`、`stop_multi_process_pool()` | 运行核心资源协调 | 进程、队列、worker exitcode、心跳、取消 sentinel、超时和 killpg 必须由运行核心统一管理 | **不直接复用实现；以其风险为治理输入** |
| `cache_dir`、`HF_HUB_CACHE`、`datasets` cache、`doc.npy` | 模型/数据/向量缓存支持 | 模型缓存与结果缓存分层；缓存键必须含 revision、契约版本、pooling/instruction、dtype、truncate、模态和数据摘要 | **吸收可配置目录，废弃“文件存在即可复用”** |
| `examples/**`、`finetune/**/__main__.py`、`evaluation/**/__main__.py`、`scripts/*.py` | CLI/批处理边界 | 作为离线作业入口；由统一网关提交作业时需转成受管任务，不让 CLI 反向成为 HTTP 服务 | **保留 CLI 边界，不当服务入口** |
| 稳定包无 FastAPI/Flask/HTTP 路由；`setup.py` 仅声明 Python 依赖 | 统一网关 | 网关由平台拥有，FlagEmbedding 只作为受管 provider/worker | **不从该仓库创建第二网关** |

### 22.3 单链路落点与禁止穿透

```text
平台请求/CLI作业
  → 统一网关公开能力 id：文本编码 / 批量embedding / reranker / dense检索 / 多向量重排
  → 检索模块：校验请求、确定候选集、维护 qid/docid 顺序、组合检索与重排
  → 向量支持库：校验/转换/持久化向量和分数
  → 模型提供者注册表：选择具体 FlagEmbedding adapter + model revision
  → 运行核心：分配 CPU/GPU、批预算、子进程/队列、超时/取消/OOM/崩溃治理
  → 第三方/硬件 provider：Transformers、PyTorch、HF Hub、FAISS、GPU
```

- 文本支持库不得 import `AutoModel`、FAISS 或 GPU 驱动；它只生产规范化文本和编码参数。
- 向量支持库不得猜测模型或直接下载权重；它只接受 provider 返回的声明型向量结果，并拒绝维度、dtype、行数、NaN、模态缺失和版本不匹配。
- 检索模块不得从 `doc.npy` 存在性推断参数一致，也不得把 reranker 原始 logits 与另一模型的 sigmoid 分数无标记混排。
- 模型提供者不得把 `torch.Tensor`、tokenizer、HF config 或 provider 对象穿透到网关；必须转成平台结果契约。
- 运行核心是唯一的资源监督 owner；不得由每个模型类再造线程池、超时器、重启器或 GPU 清理中心。
- 统一网关是唯一对外入口；HTTP/MCP/CLI 都是入口适配，不得各自维护一份能力映射、错误码和参数默认值。

## 23. 第三轮：文本编码、批 embedding 与 reranker 契约

### 23.1 文本到向量契约

源码依据：`abc/inference/AbsEmbedder.py:172-298`、`inference/embedder/encoder_only/base.py:174-282`、`inference/embedder/decoder_only/base.py:193-301`。

| 字段 | 规范化要求 | 来源事实/风险 |
|---|---|---|
| 输入角色 | `query` 与 `corpus/passage` 分开声明；不可把 query instruction 默认套到 corpus | `encode_queries()` 使用 query instruction；`encode_corpus()` 从 `passage_instruction_for_retrieval` 读取 |
| 输入集合 | 单字符串返回单条一维结果；列表返回与输入顺序一致的二维结果；空集合必须在平台入口拒绝 | 当前实现多处对空列表无统一契约，可能在 `np.concatenate` 或 `[0]` 处失败 |
| 预处理 | 固定 tokenizer 名称、revision、instruction/template、max length、截断策略；按 token 长度排序只优化 padding，不得改变序号 | encoder-only 和 decoder-only 都先 tokenize、按长度排序、完成后按 `length_sorted_idx` 恢复 |
| 表征 | dense 向量必须声明 `维度、dtype、归一化、pooling、truncate_dim、模型身份、契约版本` | `normalize_embeddings` 默认 True；`cls`/`mean`/`last_token` 由 mapping/参数决定 |
| 输出承载 | 对外用不可变结果对象或明确 JSON/二进制 schema；Tensor 只能停留在 provider/运行核心边界 | 当前默认 `convert_to_numpy=True`，否则返回 Tensor；平台不应把 PyTorch 类型外泄 |
| 数值质量 | 校验二维行数等于输入数、维度一致、dtype 可接受、无 NaN/Inf；归一化向量才能把内积解释为 cosine | 现有测试只检查 ndarray、维度、非 NaN 和余弦相似度；未固定跨模型的数值范围 |

### 23.2 BGE-M3 多模态表征契约

`M3Embedder.encode_single_device()`（`inference/embedder/encoder_only/m3.py:310-486`）返回固定三键对象：

```text
{
  "dense_vecs": np.ndarray | None,             # [N, D] 或单输入 [D]
  "lexical_weights": List[Dict[str, float]] | None,
  "colbert_vecs": List[np.ndarray] | None      # 每条长度可变
}
```

- `return_dense`、`return_sparse`、`return_colbert_vecs` 决定值是否为 `None`；平台必须记录请求的模态集合，不能把 `None` 当“模型没有该能力”。
- `lexical_weights` 的 key 是 token id 的字符串，特殊 token 和非正权重被过滤；这不是通用词面字符串倒排格式，必须由向量支持库显式标注 `tokenizer/vocabulary identity`。
- `colbert_vecs` 删除 padding 和 CLS 后按 token 长度变长；不能塞进固定维度 dense 表，也不能在 JSON 中无界展开而不设大小预算。
- `compute_score_single_device()` 返回 `colbert`、`sparse`、`dense`、`sparse+dense`、`colbert+sparse+dense` 五组分数。默认权重 `[1.,1.,1.]`；两模态和三模态融合分别除以权重和。零权重和、模态缺失和分数校准必须由平台前置校验。
- `EvalDenseRetriever` 当前只取 M3 返回的 `dense_vecs`（`searcher.py:131-135`），因此它不是 M3 全模态检索；多向量/稀疏链需要单独检索模块和索引 provider。

### 23.3 Reranker 分数契约

源码依据：`abc/inference/AbsReranker.py:157-229`、`inference/reranker/encoder_only/base.py:77-195`、`inference/reranker/decoder_only/base.py`、`m3.py:488-538`。

- 输入是 `(query, passage)` pair 或 pair 列表；query/passage instruction 是独立可选项，输入顺序必须与输出 score 顺序一一对应。
- encoder-only `BaseReranker` 取 `SequenceClassification` logits，默认返回 `float` 列表；`normalize=True` 才做 sigmoid。decoder-only reranker 从目标 token（默认 `Yes`）logits 取分数；layerwise 可能返回每个 cutoff layer 的结果。原始 logits、sigmoid 概率、M3 融合分数必须用 `score_space` 明确区分，不能只用一个 `score` 字段裸传。
- 标准结果形状为 `scores[N]`，`N == pairs[N]`；单 pair 的具体实现可能返回标量，平台入口应归一为一元素列表并在响应中保留 `input_count=1`。
- `EvalReranker` 将初始候选裁到 `rerank_top_k`，构造 pair，调用 `compute_score()` 并生成 `{qid: {docid: score}}`。源码没有统一的最终显式排序步骤，平台检索模块必须按 score 降序、稳定 tie-break（如 docid）后再输出 top-k。
- 训练/评测 `relevance`、teacher scores 与推理 logits 不是同一个分数契约；训练 JSONL 的 `pos_scores`/`neg_scores` 只有在蒸馏开关下才有意义，不能直接当线上相关性分数。

### 23.4 检索结果契约

`EvalDenseRetriever.__call__()` 的实际结果是 `{qid: {docid: float}}`；其 FAISS index 使用 `METRIC_INNER_PRODUCT`，输入被转为 `float32`。统一模块应扩展为：

```text
RetrievalResult {
  request_id,
  qid,
  hits: [{docid, score, rank, stage, score_space}],
  model_identity,
  vector_contract,
  index_identity,
  complete,
  diagnostics
}
```

`stage` 至少区分 `dense_retrieval`、`sparse_retrieval`、`colbert_retrieval`、`rerank`；`complete=false` 或部分 chunk 不得被当成成功结果。`score` 的高低方向、是否归一化、是否融合、top-k 截断点必须在 `score_space` 和 `stage` 中固定。

## 24. 第三轮：模型加载、设备、量化与缓存边界

### 24.1 模型提供者加载事实

- `FlagAutoModel.from_finetuned()`（`inference/auto_embedder.py:23-115`）和 `FlagAutoReranker.from_finetuned()`（`auto_reranker.py:24-81`）先取 basename；`checkpoint-*` 回退父目录名，然后查静态 `AUTO_*_MAPPING`。未知模型名直接 `ValueError`，没有候选模型自动回退。
- `AUTO_RERANKER_MAPPING` 中仍有 `"jinaai/jina-reranker-v2-base-multilingual"`、`"Alibaba-NLP/gte-multilingual-reranker-base"` 等带组织前缀的 key，但 auto 入口先取 `os.path.basename()`；这类 key 与实际查找值不一致，不能把“已列在 mapping”当成“自动路由可用”，应在 provider 注册阶段做 key 可达性检查并优先使用显式 model identity/class。
- `EmbedderConfig` 绑定实现类、pooling、`trust_remote_code`、instruction format；`RerankerConfig` 绑定实现类和 `trust_remote_code`。这些是模型选择配置，不是完整生产模型身份，仍缺 revision/hash、权重摘要、tokenizer 摘要和硬件/精度声明。
- 稳定推理配置主要来自构造器参数与 `**kwargs`：`AbsEmbedder`/`AbsReranker` 会把任意 kwargs 写入实例，具体 provider 再消费 `cache_dir`、pooling、batch、长度、instruction、PEFT 等字段；没有一个统一 YAML/JSON 配置 schema 或跨入口默认值校验。训练/评测 CLI 则通过 `HfArgumentParser` 解析各自 dataclass，不能直接视为在线请求配置。
- encoder-only 使用 `AutoTokenizer` + `AutoModel`；reranker 使用 `AutoModelForSequenceClassification`；decoder-only 使用 `AutoModel`/`AutoModelForCausalLM`，部分 reranker 还可加载 `PeftModel` 后 `merge_and_unload()`。
- `trust_remote_code` 允许模型仓库代码参与加载；生产 provider 必须 allowlist、固定 revision、隔离加载进程并把代码/权重许可写入诊断。该仓库没有这样的治理层。

### 24.2 GPU/CPU 与精度

`AbsEmbedder.get_target_devices()` 和 `AbsReranker.get_target_devices()` 的自动顺序是 CUDA → NPU → MUSA → MPS → CPU；整数设备通常映射到 `cuda:<n>`（MUSA 环境除外），空列表会在访问第一个元素时出错。单设备路径中 CPU 会执行 `model.float()`；encoder embedder 默认 `use_fp16=True`，reranker 默认 False 且 CPU 会关闭 fp16；embedder 还支持 `use_bf16`，并在转 NumPy 时处理 bfloat16。

映射到底座时：

1. 设备探测属于运行核心，必须返回结构化的 `selected_device、available_devices、precision、fallback_reason`，不能只靠日志。
2. `use_fp16/use_bf16` 是精度选择，不等于量化；dtype、硬件能力、模型 config 与输出向量 dtype 必须共同校验。
3. FAISS 的 `index()` 在 CUDA 可用时尝试 `index_cpu_to_all_gpus` 和 `useFloat16=True`，异常后仅打印并继续；平台必须把 CPU fallback 作为状态返回，不能把日志视为 GPU 成功。
4. MPS/多卡、MUSA/NPU 和 `spawn` 组合未在本地实测；统一网关不得把“自动发现设备”作为可审计生产配置，需显式允许的设备集合。

### 24.3 量化裁决

稳定 `FlagEmbedding/inference/` 的加载调用只显式传 `dtype`/`torch_dtype`，没有 `BitsAndBytesConfig`、`load_in_4bit`、`load_in_8bit`、GPTQ/AWQ 或统一量化配置入口；当前源码中可检出的 4-bit NF4 + double quant 位于 `research/Long_LLM/longllm_qlora/src/__init__.py:115-118`，属于研究/训练路径，不得宣称为稳定推理 API。

因此：

- **模型提供者**负责声明“原始权重/半精度/量化后端/量化配置/兼容硬件”，但不在网关内随意拼装量化参数。
- **运行核心**负责显存预算、加载前探测和 OOM 隔离；量化失败必须是明确 provider error，不得静默退回另一精度模型。
- **向量支持库**必须把量化模型身份纳入 `model_identity`，并以实际输出 dtype/维度做契约校验；不能只记录“use_fp16=true”。
- 4/8-bit 的支持范围、分数/向量漂移和 CPU fallback 当前均为**待核**，要以目标模型、Transformers、bitsandbytes/后端和硬件实测后再吸收。

### 24.4 缓存分层

源码存在三类不同缓存，不能合成一个“cache”：

| 缓存 | 代码证据 | 当前语义 | 平台要求 |
|---|---|---|---|
| 模型/tokenizer cache | `BaseEmbedder`、`BaseReranker`、decoder-only 构造器传 `cache_dir`；示例从 `HF_HUB_CACHE` 读取 | HF/Transformers 复用本地文件；没有本仓库级 revision/权限治理 | 以 model id + revision + tokenizer/config/权重摘要寻址，下载临时目录完成后原子激活，记录许可和来源 |
| 数据集 cache | `datasets.load_dataset(..., cache_dir=...)`、评测 data loader 与 `scripts/split_data_by_length.py` | 复用 datasets 缓存；网络/解压失败可能留部分目录 | 数据集版本/文件摘要/分片状态可回读，失败清理或隔离，不能把目录存在当完整 |
| 语料向量/评测结果 | `EvalDenseRetriever` 只检查 `corpus_embd_save_dir/doc.npy`；`AbsEvaluator` 检查结果 JSON 元数据和 `overwrite` | `doc.npy` 无模型参数 hash，保存非原子；结果 JSON 也没有统一事务 | 缓存键至少包括 model identity、vector contract、instruction、pooling、dtype、truncate、dataset hash、index config；写临时文件后原子替换并读回校验 |

`doc.npy` 只存在即复用是当前实现缺口：同目录更换模型、instruction、pooling、dtype 或 corpus 顺序可能静默错配。该模式**废弃**为平台缓存策略，仅可作为历史评测实现记录。

## 25. 第三轮：资源生命周期与故障治理映射

### 25.1 资源生命周期裁决表

| 资源 | FlagEmbedding 当前创建/持有 | 正常释放 | 失败/超时/取消/崩溃事实 | 底座责任 |
|---|---|---|---|---|
| tokenizer/model | provider 构造器调用 `from_pretrained`，实例持有 | `stop_self_pool()` 将 model 移 CPU、`torch.cuda.empty_cache()`、`gc.collect()`；析构 `__del__` 尽力调用 | 初始化异常向上抛；无统一回滚；宿主崩溃由 OS 回收但 cache/部分下载可能残留 | provider session 句柄 + 运行核心租约；加载失败删除/隔离临时制品，记录 revision/exitcode |
| GPU/CPU tensor | 单设备 forward、padding、pooling；numpy 转换移 CPU | 函数引用释放，显式 stop 时移 CPU/empty cache | OOM 仅缩 batch；没有最小 batch/deadline；异常路径没有统一显存核对 | 预算、峰值采样、OOM 分类、进程级销毁；结果只在完整 batch 集合时提交 |
| multi-device process | `spawn` daemon；model `share_memory()`；input/output Queue | `terminate`→`join`→`close`，Queue close | 父 `Queue.get()` 无 timeout；worker 异常可能没有错误消息；取消没有 sentinel | 统一 supervisor、heartbeat、exitcode、killpg、超时/取消状态和无残留验证 |
| ICL query pool | `ICLLLMEmbedder` 额外维护 `query_pool`，query/corpus 会相互停止池 | `stop_self_query_pool()` + `stop_self_pool()` | 双池切换异常时可能有引用/设备状态不一致 | 统一任务池，不允许 provider 私有第二套监督器 |
| HF/datasets cache | 模型和数据下载写入 cache/save_dir | 成功长期复用 | 断线、解压失败可能留部分文件/目录；无下载 deadline/事务 | 内容寻址、临时目录、原子 rename、损坏隔离、清理证据 |
| `doc.npy`/FAISS | `np.save` 直接写；FAISS index 在内存构造并可上 GPU | 进程退出/引用释放 | `.npy` 非原子；FAISS GPU fallback 只打印；空集/维度错可能在底层失败 | 索引 provider 统一关闭/落盘/校验；提交前检查 shape/dtype/count/index identity |
| JSON 评测结果 | `open(...,"w")` 直接写结果和 EVAL | context manager 关闭文件 | 中断可能形成部分 JSON；`overwrite` 可能覆盖已有结果 | 临时文件+fsync+原子替换；读回 schema、数量、元数据和完整标记 |
| 外部远程代码/权重 | `trust_remote_code` 与 HF cache 持有 | 库无撤销机制 | 代码执行、许可不符、下载错误无隔离治理 | provider sandbox/allowlist/revision pin/审计；统一网关拒绝未批准模型 |

### 25.2 失败、超时、取消、OOM、崩溃分层

| 场景 | 源码行为 | 可靠性裁决 | 平台统一动作 |
|---|---|---|---|
| 未知模型/非法 `model_class` | auto factory `ValueError` 或 Enum/key error | 明确失败；无自动回退 | 网关在提交前校验能力/模型身份，错误码稳定化，不换模型重试 |
| 空 query/corpus/pair | 多处 `[0]`、`np.concatenate([])` 或 FAISS 空输入暴露原生异常；M3 score 对空 list 有特殊返回 | 契约不一致 | 文本支持库统一空输入/部分空批策略；空作业拒绝，保留 request_id |
| 非法字段、坏 JSON、长度超限 | `KeyError`/`AssertionError`/`ValueError`/datasets 异常 | 不是稳定 API 错误 | 网关 schema 校验、长度预算和输入大小上限；provider 不直接把 traceback 外泄 |
| 单设备 RuntimeError/OOM | 试算批次捕获异常，`batch_size = batch_size * 3 // 4`，无上限/最小值保护 | 可能无界循环或降到 0；不区分普通 RuntimeError 与 OOM | 运行核心固定重试次数、最小 batch=1、释放/重建 session；超过预算返回 OOM，不悄悄换模型 |
| multi-device worker 异常 | embedder worker 未把异常写 error queue；reranker worker `except:` 直接退出；父进程仍 `output_queue.get()` | 可能永久阻塞，不能视为失败已返回 | watchdog 检查队列、心跳、exitcode、deadline；kill 整个 pool，丢弃不完整 chunk |
| 主动取消/请求超时 | 没有 token、sentinel 或 deadline 参数 | 库内不支持取消 | 网关/运行核心持有取消令牌；超时 killpg/关闭队列/回收 GPU，结果标记 CANCELLED/TIMEOUT |
| HF 下载/解压/数据源断线 | `subprocess.run(check=True)` 或下载异常上抛，缺统一 timeout/回滚 | 失败可见但残留不可靠 | 外部命令 deadline、临时下载目录、hash/大小校验、失败清理 |
| FAISS GPU 不可用 | broad `except` 打印后继续 | fallback 不结构化 | 返回 `index_device=cpu` 和 fallback reason；指标与告警不能依赖 print |
| 评测 split 不存在 | warning 后返回；0 split 可能被当成正常结束 | 易假绿 | 运行核心/网关要求有效 split 数>0，完成标志与输出文件数一致 |
| 宿主/子进程崩溃 | OS 回收进程资源；结果/cache 可能半写 | 无业务恢复/补偿 | 新进程重建 provider；只接受原子完整制品；校验进程组、GPU、临时目录和锁残留 |
| 重复调用/重复作业 | embed/score 本身无幂等键；评测 `overwrite` 只是文件存在/元数据有限 | 不是服务幂等 | 网关生成 idempotency key；运行核心以请求参数摘要去重/续作，缓存提交 CAS |

### 25.3 L0-L4 第三轮验证等级

| 等级 | 第三轮要证明什么 | 当前目标源码证据 | 当前状态 |
|---|---|---|---|
| L0 结构/符号存在 | 六层映射的入口、实现、测试、CLI/评测路径真实存在 | `auto_embedder.py`、`auto_reranker.py`、`AbsEmbedder.py`、`AbsReranker.py`、`encoder_only/base.py`、`m3.py`、`searcher.py`、`utils.py`、`tests/`、`examples/`、`setup.py` | **已完成静态读取**；不证明可导入和运行 |
| L1 语法/契约静态一致 | 源码 AST 可解析；输入输出形状、映射、失败分支、缓存与资源路径能对应源码 | 既有文档第 18 节记录 `AST_OK files=158`；本轮补充路径和行号静态对照 | **弱验证**；未运行目标依赖，未验证动态分支 |
| L2 依赖/导入/边界 | Transformers/PyTorch/FAISS/pytest 环境可导入；mock provider 能验证设备、空输入、OOM、worker、缓存 schema | `tests/test_imports_v5.py`、`conftest.py` 存在；测试依赖 `pytest`/模型包 | **未通过/未验证**；既有记录显示当前 shell 无 `pytest`，且本轮禁止安装依赖 |
| L3 真实模型链 | 固定 revision 的真实 embedding、M3 模态、reranker、GPU/CPU、量化方案、FAISS top-k 真实运行，结果/shape/score 可回读 | `test_infer_embedder_basic.py` 下载 `BAAI/bge-base-en-v1.5`；`test_infer_reranker_basic.py` 下载 `BAAI/bge-reranker-base`；examples 覆盖多设备 | **未验证**；未下载权重、未占设备、未加载量化模型 |
| L4 外部闭环/生产条件 | 网关→任务→隔离 provider→索引/结果→重启恢复；deadline/cancel/OOM/crash、缓存原子性、许可证和资源无残留 | FlagEmbedding 没有 HTTP 服务、租约、watchdog、统一结果事务或生产部署测试 | **未验证且不是该仓库能力**；必须在平台侧另建真实验收，不能由本项目 README/pytest 名称替代 |

L0/L1 仅支持“源码存在、静态映射成立”；L2 需要真实 import/边界测试；L3 需要真实模型和设备；L4 必须包括统一网关及资源/重启闭环。任何子代理回信、日志、测试文件存在、HF cache 目录存在、FAISS fallback 打印都不能单独升级等级。

## 26. 第三轮裁决、缺口与装配计划（不启动实现）

### 26.1 吸收/升级/新建/废弃/待核

| 能力 | 裁决 | 具体边界 |
|---|---|---|
| 文本编码角色与 instruction 模板 | **吸收并升级** | 作为文本支持库契约；固定 query/corpus 角色、模板、token budget、版本；不复制 tokenizer/model |
| 批 embedding 的长度排序、顺序恢复 | **吸收并升级** | 算法进入运行核心批调度；加最小 batch、deadline、取消、chunk 完整性和错误回传 |
| dense 向量输出 | **吸收并升级** | 向量支持库提供统一结果、维度/dtype/归一化/模型身份校验和原子持久化 |
| M3 lexical/ColBERT 多表征 | **吸收，索引待核** | 保留三模态语义；建立独立 sparse/multi-vector index provider；未确认后端前不得伪装成 dense |
| reranker pair→score | **吸收并升级** | provider 输出 score list + score_space；检索模块排序、top-k 和 stage 编排；不得混合未校准分数 |
| `FlagAuto*` basename 自动映射 | **吸收思想，废弃直接生产复用** | 改为唯一能力注册表 + 显式模型 identity/revision；未知模型不隐式 fallback |
| `torch`/Transformers/HF Hub | **模型提供者隔离** | 第三方库运行在受管 provider/独立环境；主网关不加载重型模型和远程代码 |
| 多设备 pool/Queue 实现 | **废弃直接复用，升级为运行核心能力** | 统一 supervisor、资源租约、watchdog、cancel、killpg、exitcode 和残留验证 |
| `doc.npy` 文件存在即复用 | **废弃** | 用参数/数据摘要缓存键、临时文件、原子提交和读回校验替代 |
| 量化研究代码 | **待核/隔离** | 只登记 4-bit NF4 等研究事实；生产量化需单独 provider、硬件矩阵和 L3 实测 |
| `evaluation/**` + FAISS | **吸收为检索模块/索引 provider参考** | 评测类不进入统一网关；FAISS GPU fallback 和空集/维度错误需结构化治理 |
| examples/scripts/finetune CLI | **保留离线边界** | 统一网关可提交受管批作业；不把脚本直接包装为无状态 HTTP handler |
| HTTP/MCP 服务 | **平台统一网关拥有** | FlagEmbedding 侧无实现，不创建第二网关、不让 provider 处理认证/租户/幂等 |

### 26.2 缺口表

1. **缺统一模型身份**：当前映射以 basename 为主，缺 revision、权重摘要、tokenizer/config 摘要、许可和实际加载 dtype。
2. **缺统一向量 schema**：普通 dense、M3 三模态、Tensor/NumPy、单条/批量没有平台级版本化结果对象。
3. **缺 score space**：raw logits、sigmoid、M3 融合值和 FAISS inner product 未统一标识，不能安全跨模型比较。
4. **缺在线服务语义**：无请求 id、幂等、deadline、取消、鉴权、限流、租户、流式事件和结构化错误。
5. **缺资源监督**：pool 的队列阻塞、worker 崩溃、OOM 重试、进程残留和 GPU 回收没有统一 owner。
6. **缺缓存事务**：`doc.npy` 和 JSON 直接写，缓存没有完整参数键、CAS、原子提交或失败清理。
7. **缺量化生产证据**：稳定推理 API 未提供统一量化入口，研究 QLoRA 不能算生产能力。
8. **缺 M3 索引落点**：现有 `EvalDenseRetriever` 丢弃 sparse/ColBERT；需确认向量库对 token 权重和变长多向量的支持。
9. **缺真实 L2-L4 证据**：当前环境无 pytest 命令且未下载模型，本轮不能升级验证等级。

### 26.3 装配计划与验收契约

在平台正式开发前，建议按以下顺序登记需求、搜索现有能力并取得占用租约；本轮只形成装配输入，不修改平台生产底座：

1. **契约冻结**：登记 `文本编码.v1`、`批量Embedding.v1`、`Reranker.v1`、`向量校验与持久化.v1`、`检索与重排.v1` 五个能力族；明确请求/响应、错误码、deadline、cancel、幂等和资源释放责任。
2. **provider 适配**：实现/复用一个 HF FlagEmbedding provider 适配层，能力内部再选择 encoder-only、M3、decoder-only、reranker；禁止每个模型复制一套网关路径。
3. **运行核心接线**：模型加载、batch budget、设备探测、独立进程、超时/取消、OOM 重建、崩溃有界重启和资源残留审计统一由运行核心承接。
4. **向量/索引接线**：先落 dense + FAISS CPU 最小闭环；再以独立 provider 验证 sparse/ColBERT；索引制品必须绑定 vector contract、model identity、dataset digest、index config。
5. **网关接线**：统一网关只接收文本、模型身份、模态、top-k、超时和幂等参数；返回统一结果对象和诊断，不返回 Tensor、HF model 或异常 traceback。
6. **CLI 接线**：将 `finetune`、`evaluation`、`scripts` 标记为离线作业能力；由任务系统执行并持久化状态，不能让 CLI 自行监听端口。
7. **逐级验收**：L0/L1 静态结构 → L2 mock/导入/故障边界 → L3 固定模型真实推理和索引 → L4 网关、取消、OOM、崩溃重启、缓存原子性和清理闭环。每一级均需记录命令、退出码、测试数、外部依赖、模型 revision、设备、输出校验和残留现场。

### 26.4 本轮修改与验证边界

- 本轮只追加目标根 `ARCHITECTURE.md`；未修改 FlagEmbedding 源码、配置、依赖、测试、README、权重、缓存、Git 或平台生产底座。
- 已读取并以源码为证据覆盖：auto embedding/reranker 入口与 mapping、`AbsEmbedder`/`AbsReranker`、encoder-only base、M3、多种 decoder-only/reranker 构造器、评测 searcher/utils/evaluator、setup、推理测试、conftest、examples/CLI 入口和 quantization/cache 相关命中。
- 未运行模型加载、训练、评测、FAISS、GPU/CPU、多设备、量化或服务闭环；因此第三轮结论是“吸收/升级裁决输入”，不是底座已实现或 L3/L4 已通过。

## 27. 第二轮内部收口：模型、批处理、分数与资源逐项核对

本节是对前置 `细探-FlagEmbedding.md` 和本文件第一轮事实的第二轮收口，不改变源码结论的证据边界。已逐条回到当前本地源码核对：`FlagEmbedding/abc/inference/AbsEmbedder.py`、`AbsReranker.py`，`inference/auto_embedder.py`、`auto_reranker.py`、两份 `model_mapping.py`，encoder-only/M3/decoder-only 推理实现、评测 `searcher.py` 以及现有推理测试。旧细探继续保留，不删除、不改写。

### 27.1 旧细探逐条裁决

| 旧细探说法 | 当前源码核对 | 第二轮裁决 |
|---|---|---|
| BGE-M3 是 dense + lexical + ColBERT 三合一 | `inference/embedder/encoder_only/m3.py:310-486` 的 `encode_single_device()` 按 `return_dense`、`return_sparse`、`return_colbert_vecs` 产出三类结果；`compute_score_single_device():645-732` 另算五类分数 | **吸收**；对外必须保留三键结果和模态开关，不能把 lexical/ColBERT 降成 dense 的别名 |
| `FlagAutoModel` 工厂自动分发 | `auto_embedder.py:62-115` 先 basename，再查 `AUTO_EMBEDDER_MAPPING`；显式 `model_class` 时查 `EMBEDDER_CLASS_MAPPING` | **吸收但加限制**；basename 是路由线索，不是完整模型身份；未知 key 直接 `ValueError`，没有自动回退 |
| bge-reranker 是交叉编码重排 | `inference/reranker/encoder_only/base.py:66-75` 加载 `AutoModelForSequenceClassification`，`compute_score_single_gpu():119-195` 取 logits | **吸收**；默认是 raw logits，只有 `normalize=True` 才 sigmoid，不能把所有 score 都称为 0–1 概率 |
| “嵌入模型无 LLM 提示词” | `decoder_only/base.py` 使用 last-token pooling；ICL 有 few-shot prefix/suffix；decoder-only reranker 使用 prompt 和 `Yes` token | **修正**：稳定包不是聊天生成编排，但确实存在 decoder-only embedding/rerank 的 instruction、few-shot 和判别 prompt |
| 依赖是 PyTorch/GPU | `AbsEmbedder/AbsReranker.get_target_devices()` 支持 CUDA、NPU、MUSA、MPS、CPU；单设备 CPU 会转 float | **修正**：GPU 是常见加速路径，不是唯一运行设备；模型、dtype、设备组合仍需真实环境验证 |
| `flag_embedding/` 是核心目录 | 当前可安装包是 `FlagEmbedding/`，`setup.py:14` 使用 `find_packages()` | **废弃旁路线索**；文档和接入路径一律使用当前真实包名 |
| MIT 可直接覆盖模型权重 | `setup.py`/源码许可与 Hugging Face 模型仓库、远程代码、数据集是不同来源 | **保留边界**：代码许可证、权重许可证、远程代码信任与数据许可分别审计 |

### 27.2 模型族与加载契约

| 模型/入口 | 加载事实 | 关键参数与输出 | 失败边界 |
|---|---|---|---|
| encoder-only embedder | `encoder_only/base.py:78-88`：`AutoTokenizer.from_pretrained()` + `AutoModel.from_pretrained()` | pooling 默认 `cls`，可 `mean`；默认 `normalize_embeddings=True`、`use_fp16=True`；`dtype=self.get_model_torch_dtype()` | tokenizer/model/HF 下载异常直接向上传播；没有库级 rollback 或备用模型 |
| BGE-M3 | `m3.py:93-109`：tokenizer + `EncoderOnlyEmbedderM3Runner.get_model()`，包装 `EncoderOnlyEmbedderM3ModelForInference` | 默认仅 dense；可选 lexical 权重和 ColBERT multi-vector；`colbert_dim`、`truncate_dim` 影响输出 | 模态开关与下游索引必须一致；M3 全模态不是 `EvalDenseRetriever` 的默认路径，后者只取 `dense_vecs` |
| decoder-only embedder | `decoder_only/base.py:94-107` 使用 `AutoTokenizer` + `AutoModel`，强制 pooling 为 `last_token` | last-token 取决于 attention mask 的左/右 padding；支持 fp16/bf16，归一化和截断在 forward 后执行 | 非 `last_token` pooling 抛 `ValueError`；模型加载错误直接上抛 |
| ICL embedder | `decoder_only/icl.py:107-125` 加载模型后由 `set_examples()` 生成 `prefix`；query 另有 `query_pool` | few-shot example 按 `examples_instruction_format` 拼接，query 有 suffix；query/corpus 切换会停不同 pool | 两套 pool 不是统一监督器；切换/异常时库内没有 deadline、heartbeat 或统一 finally |
| pseudo-MoE embedder | `decoder_only/pseudo_moe.py:41-77,79-117` 默认 `trust_remote_code=True`、bf16，并可设置 domain | `domain_for_pseudo_moe`/`domain` 可触发 `model.set_domain()` 并传给 forward；对输出做 `nan_to_num` | 远程代码默认信任面更大；模型不接受 domain 时只回退普通 forward，域路由是否生效需外部实测 |
| encoder-only reranker | `reranker/encoder_only/base.py:66-75` 加载 tokenizer + `AutoModelForSequenceClassification` | query 默认 max length 为 `max_length*3//4`；pair 用 `prepare_for_model(... truncation='only_second')`；输出 logits | 加载阶段未显式传 dtype；fp16 是加载后调用 `model.half()`，CPU 会关闭 fp16 |
| decoder-only reranker | `reranker/decoder_only/base.py:238-254` 加载 tokenizer + `AutoModelForCausalLM`；可选 `PeftModel.from_pretrained()` 后 `merge_and_unload()` | `Yes` 的第一个 token id (`yes_loc`) 对最后位置 logits 取分；可选 sigmoid | prompt、separator、tokenizer 共同决定分数；`PeftModel` 合并失败直接上抛 |
| layerwise/lightweight reranker | `layerwise.py:107-133` 先尝试自定义 MiniCPM，异常后 broad fallback 到 `AutoModelForCausalLM`；`lightweight.py:146-203` 类似 Gemma fallback | layerwise 返回 cutoff layer 分数；lightweight 还接收 `compress_layers`/`compress_ratio` | 自定义加载失败与模型真的不可用被同一 broad `except` 混淆；lightweight 依赖导入失败时直接 `sys.exit()`，不是结构化异常 |

`FlagAutoModel.from_finetuned()`（`auto_embedder.py:62-115`）和 `FlagAutoReranker.from_finetuned()`（`auto_reranker.py:49-81`）的共同契约是：先用路径 basename（`checkpoint-*` 再取父目录名），再查静态映射；显式 `model_class` 才绕过名称映射。`AUTO_RERANKER_MAPPING` 中带组织前缀的 key（例如 `jinaai/jina-reranker-v2-base-multilingual`）在当前 basename 查找逻辑下不可达，这是源码级可达性缺口，不应把“出现在表中”写成“自动路由已可用”。

### 27.3 embedding 单设备批处理与输出

源码共同采用以下真实顺序：

```text
输入 str/List[str]
  → query/corpus instruction（若有）
  → tokenizer 分批预处理（不 padding，truncation=True）
  → all_inputs 全量保存在内存
  → 按 input_ids 长度降序排序，减少 batch padding
  → 首批 forward 探测可用 batch
  → RuntimeError/OOM 时 batch_size = batch_size * 3 // 4
  → 全量分批 forward（torch.no_grad + eval）
  → pooling / last-token pooling
  → truncate_dim → 可选 normalize
  → 恢复原输入顺序
  → NumPy（默认）或 Torch Tensor；单字符串退化为一维结果
```

| 项目 | 当前实现事实 | 契约/风险 |
|---|---|---|
| query/corpus 角色 | `AbsEmbedder.encode_queries():172-204` 使用 query instruction；`encode_corpus():206-241` 从 `kwargs` 取 `passage_instruction_for_retrieval` 与 format | query 与 corpus 的 instruction、模板和 max length 必须成对版本化；默认 corpus 不自动复用 query instruction |
| 顺序 | encoder-only、decoder-only、M3 都用 `length_sorted_idx` 排序后按逆索引恢复 | 批处理优化不应改变业务顺序；平台应额外校验输出行数等于输入数 |
| 输出形状 | 单字符串先包成一元素列表，最后返回 `[0]`；列表返回二维 dense；M3 三键结果按输入顺序对齐 | 空列表没有统一返回：普通路径可能在 `np.concatenate`/首批探测处失败；M3 的 `compute_score_single_device()` 对空 list 返回 `[]`，形状不再是五键 dict |
| dtype | `AbsEmbedder.get_model_torch_dtype()` 中 bf16 优先于 fp16；NumPy 转换通过 `_convert_to_numpy()`，非 CPU bf16 先转 float | `use_fp16/use_bf16` 不是量化声明；输出 dtype、模型身份和精度必须一起记录 |
| OOM 降批 | `BaseEmbedder:231-248`、`BaseLLMEmbedder:250-266`、`M3:395-415` 捕获运行时错误并按 3/4 缩小 | 无最小 batch=1、最大重试次数、deadline、错误分类或显式 `empty_cache()`；极端错误可能一直重试或缩到 0 |
| M3 sparse | `m3.py:353-368` 删除特殊 token、过滤 `w<=0`，key 是 token id 的字符串；`convert_id_to_token()` 才可解码为 token | 这是 tokenizer/vocabulary 绑定的 lexical 权重，不是通用字符串倒排；tokenizer 身份必须跟索引绑定 |
| M3 ColBERT | `m3.py:370-373` 去除 padding 和 CLS，长度可变 | 不能存进固定维度 dense 字段；需独立 multi-vector 预算和索引契约 |
| M3 模态计算 | `m3.py:693-728` 默认权重 `[1,1,1]`；输出 `colbert`、`sparse`、`dense`、`sparse+dense`、`colbert+sparse+dense` | 只 `assert len(weights)==3`；两模态或三模态权重和为 0 会除零；缺失模态和权重语义没有统一校验 |

需要特别记录一个实现细节：M3 的首批 batch 探测（`m3.py:397-415`）没有把 `truncate_dim` 传给模型，而正式循环（`m3.py:428-434`）会传；因此 `truncate_dim` 相关显存/形状行为不能仅凭探测批通过来判断。

### 27.4 reranker 输入、批处理与分数空间

1. `AbsReranker.compute_score()`（`AbsReranker.py:200-229`）先访问 `sentence_pairs[0]` 判断单 pair，再由 `get_detailed_inputs()` 按 query/passage instruction 生成输入；空列表在抽象层就会索引失败。
2. encoder-only reranker（`encoder_only/base.py:119-190`）分别 tokenize query/passage，按 query+passage token 长度排序，调用 `prepare_for_model()`，只对第二段截断；首批 forward 探测后再批量计算，恢复原顺序。
3. decoder-only reranker（`decoder_only/base.py:309-506`）在 query、换行、passage 后追加 prompt；`last_logit_pool()` 取最后有效位置，选择 tokenizer 对 `Yes` 的第一个 token id。layerwise 会为每个 cutoff layer 保留一组结果；只有一层时再压平为 list。
4. encoder-only 默认 `normalize=False`，raw `SequenceClassification` logits 可为负；decoder-only 同样返回 raw `Yes` logits；`normalize=True` 才逐项 sigmoid 到 `(0,1)`。`sigmoid` 实现在 `encoder_only/base.py:10-11`，没有跨模型校准。
5. `EvalReranker`（`abc/evaluation/searcher.py:210-248`）先把候选截到 `rerank_top_k`，再构造 pairs 和重排分数；返回 `{qid: {docid: score}}`，不携带 `score_space`、模型 revision 或是否 sigmoid。平台不能直接混排 raw logits、sigmoid、M3 融合分数、FAISS inner product；必须声明 `score_space`、stage、higher-is-better 和模型身份。
6. `EvalDenseRetriever` 的 FAISS `index()`/`search()` 以 dense 向量为输入，M3 字典只取 `dense_vecs`；索引参数、向量归一化与模型变更未写入 `doc.npy` 的复用契约。

### 27.5 GPU/CPU、设备池与资源释放

| 生命周期阶段 | 真实实现 | 未覆盖/需外层承接 |
|---|---|---|
| 设备选择 | `AbsEmbedder.py:122-154` 顺序为 CUDA→NPU→MUSA→MPS→CPU；`AbsReranker.py:111-140` 同类但 MPS 直接 `mps`；显式 int/list[int] 通常转 `cuda:<n>`（MUSA 可用时转 `musa:<n>`） | 空 list 访问 `[0]` 失败；不校验设备存在、显存预算、MPS 多卡或 CUDA/NPU/MUSA 混合组合 |
| 单设备模型 | encode/score 前 `.to(device).eval()`；CPU 路径对 embedder `model.float()`，reranker 关闭 fp16；forward 有 `torch.no_grad()` | 多次在 CPU/GPU 间切换的并发安全、显存峰值、设备 fallback reason 没有结构化状态 |
| 多设备启动 | `start_multi_process_pool()` 把 model `.to("cpu")`、`share_memory()`，用 multiprocessing `spawn` 为每个 target device 建 daemon worker、input/output Queue | 没有 error queue、heartbeat、任务 cancel sentinel 或 queue get timeout；模型对象和 kwargs 通过进程边界传递，worker 崩溃可能只表现为父进程等待 |
| 多设备结果 | chunk 按设备数均分，父进程按 chunk id 排序后 concatenate；Tensor 结果移到 `target_devices[0]` | `output_queue.get()` 无 timeout；缺一个 chunk 可能永久阻塞。reranker worker `except:` 后直接退出，embedder/M3 worker 也没有业务错误响应 |
| 正常释放 | `stop_multi_process_pool()` 对进程 `terminate→join→close`，再 close 两个 Queue；`stop_self_pool()` 还会将 model 移 CPU、`torch.cuda.empty_cache()`、`gc.collect()`；`__del__` 尝试调用 | `stop_multi_process_pool()` 内部把局部变量置 None，不会替换调用方持有的 dict；异常/超时路径不保证自动调用。`__del__` 是非确定性清理，不能当服务级 finally |
| ICL 双池 | `ICLLLMEmbedder` 额外维护 `query_pool`，query 编码前停普通 pool，corpus 编码前停 query pool | 私有双池增加切换状态和残留风险；没有统一监督/取消协议 |
| M3 评分池 | `M3Embedder.compute_score()` 多设备时新建局部 pool，正常返回后才 `stop_multi_process_pool()` | 没有 `try/finally`；评分异常时池可能残留，需外层进程组回收和现场核对 |
| 评测释放 | `EvalRetriever.stop_multi_process_pool()`/`EvalReranker.stop_multi_process_pool()` 委托给 embedder/reranker 的 `stop_self_pool()`；`EvalDenseRetriever` 中另有 `gc.collect()` 与 `torch.cuda.empty_cache()` | 评测 `__call__()` 异常退出无统一 finally；GPU index、临时 tensor、部分文件和 worker 需要外层验证 |

### 27.6 缓存与持久化事实

| 缓存/制品 | 当前源码语义 | 收口结论 |
|---|---|---|
| HF tokenizer/model cache | encoder、M3、decoder embedder/reranker 都把 `cache_dir` 传给 `from_pretrained()`；默认由 Transformers/HF 管理 | 只能说明“依赖层可复用”，不证明 revision、权重完整性、远程代码和许可证已锁定 |
| dataset/cache | 评测 data loader 和训练 dataset 将 `cache_dir` 传给 `datasets.load_dataset` 或下载/解压工具 | 失败时缺统一超时、临时目录回滚、hash/大小校验；部分目录不能被当成完整数据集 |
| corpus embedding | `abc/evaluation/searcher.py:121-140` 只按 `corpus_embd_save_dir/doc.npy` 是否存在和 `overwrite` 决定读/重算；`np.save()` 直接写目标 | 没有模型、revision、instruction、pooling、dtype、truncate、模态、corpus digest 或 index config hash；`.npy` 非原子，当前实现不能作为生产缓存契约 |
| 评测结果 | 评测 runner/evaluator 写 JSON 并以 metadata/overwrite 做部分复用 | 不等于统一事务；中断可能有半写 JSON，必须由外层临时文件、原子替换、读回 parse 和数量校验治理 |
| decoder reranker DataLoader | `decoder_only/base.py:418-435` 与 `layerwise.py:288-305` 在 `use_dataloader=True` 时传 `cache_dir=self.cache_dir`，但各自构造器只接收 `cache_dir`，未见 `self.cache_dir = cache_dir` 赋值 | 这是源码级潜在 `AttributeError` 分支，不能宣称 DataLoader/cache 路径已验证；需在独立依赖环境复现后再决定是否修源码（本轮禁止修改） |

### 27.7 失败、超时、取消与释放矩阵

| 场景 | 源码行为 | 库内是否可靠闭环 | 必须外置的验收动作 |
|---|---|---|---|
| 未知模型/非法 model class | auto factory 抛 `ValueError` 或 Enum/key 异常 | **明确失败，无回退** | 记录完整 path、model class、revision，禁止换模型重试 |
| 空输入/空 pair | 多处 `[0]`、`np.concatenate([])`、FAISS 空数组失败；M3 score 空 list 特殊返回 `[]` | **形状不统一** | 入口拒绝空批并固定错误码；单条/批量输出行数回读 |
| 非法 pair/字段/坏数据 | `AssertionError`、`KeyError`、`ValueError` 或底层 tokenizer/datasets 异常 | **无稳定错误契约** | schema、类型、长度、数值、docid/qid 唯一性预检 |
| RuntimeError/OOM | 多个单设备实现捕获后按 3/4 降 batch | **无界且不分类** | 固定最大尝试数、batch 下限 1、deadline；失败后销毁 session/进程，不能无限重试 |
| worker 异常/被 kill | 无 error queue；reranker worker 直接退出；父进程按预期 chunk 数阻塞 get | **可能永久等待** | watchdog 轮询 exitcode/心跳；超时 kill 整个进程组、关 Queue、丢弃未完整结果 |
| 主动取消/请求超时 | 没有 cancellation token、sentinel 或 deadline 参数 | **库内不支持** | 运行核心负责 deadline、killpg、队列关闭、GPU/临时目录回收和 `CANCELLED/TIMEOUT` 状态 |
| HF 下载/解压/模型加载失败 | 异常向上传播；评测下载使用 `subprocess.run(check=True)`，未统一 timeout/事务 | **错误可见但残留不可靠** | 临时目录、hash/size、零字节/部分文件扫描、失败隔离和重试上限 |
| FAISS GPU 不可用 | `abc/evaluation/utils.py` 的 GPU 尝试 broad `except` 后打印并继续 | **fallback 非结构化** | 读回实际 index/device 与 fallback reason，不以日志判成功 |
| 评测 split 缺失/0 split | loader 可能 warning、删除 split 或 evaluator 直接 return | **易假绿** | 要求有效 split 数>0、输出文件数与 query 数一致、完成标志显式落盘 |
| 宿主/子进程崩溃 | OS 回收进程资源，但结果、`.npy`、JSON、HF 临时文件可能半成品 | **无业务恢复** | 检查 exitcode、parse、shape/count、GPU 进程、worker、Queue、临时目录和锁残留 |
| 重复调用/缓存复用 | encode/score 无幂等键；评测 `overwrite=False` 主要依赖文件存在和有限 metadata | **非服务幂等** | 外层以请求参数摘要、模型身份、数据 digest 建 key，并采用原子提交/CAS |

**第二轮最终判断**：FlagEmbedding 已经形成清晰的“模型工厂 → tokenizer/model → 单设备批处理 → embedding/reranker 输出”的源码级边界，BGE-M3 也确实把 dense、lexical、ColBERT 分开表达；但多设备队列、OOM 降批、缓存复用、score space、取消、异常清理和 DataLoader cache 分支都不是可直接交付的服务契约。可吸收的是接口语义、批处理算法和多粒度输出，不能吸收其无界重试、无 timeout 队列、文件存在即复用、broad fallback 或析构式清理。

### 27.8 第二轮核对后的验证等级

| 项目 | 本轮证据 | 等级/结论 |
|---|---|---|
| 旧细探吸收 | `细探-FlagEmbedding.md` 68 行已读取；旧文件仍存在且未修改 | **L1 静态确认** |
| 模型映射、加载参数、输出形状、失败分支 | 直接读取当前源码并记录路径/行段 | **L1 静态确认**，不等于可导入 |
| GPU/CPU、MPS/NPU/MUSA、多设备 pool | 代码分支存在；没有目标环境执行 | **L1；L2/L3 未验证** |
| OOM、worker 崩溃、取消、资源回收 | 仅确认源码缺少统一闭环 | **风险确认，不是通过** |
| HF/数据/`doc.npy` 缓存 | 读到实际 cache_dir、`np.load/np.save` 路径；未下载/重算/断线 | **L1；完整性/原子性未验证** |
| 现有推理测试 | `tests/test_infer_embedder_basic.py` 与 `test_infer_reranker_basic.py` 会联网下载 `BAAI/*`；当前未安装依赖、未运行 | **测试存在，L3 未通过/未宣称** |

本节不启动实现、不修改源码、不安装依赖、不下载权重、不启动服务、不删除旧细探；后续若要生产化，必须在独立 provider/运行核心中补请求级超时、取消、监督、缓存事务、分数版本和资源残留验证。
- 复核时应保持“目标目录本地静态读取、错误 project_context 只记环境问题”的证据边界；不能引用错绑项目的代码图或 MCP 验证作为 FlagEmbedding 证据。
