# starsuzi-VideoRAG 架构建档

> 本文是本仓库三轮增量架构档案，事实基线为当前工作树 `main` / `cd4faac2b6f7fa6a0e42acaf51448d57ede1c8c4`。只记录已读取源码、数据和配置能够支持的结论；“设计说明”与“未验证项”单独标注。此前 `细探-starsuzi-VideoRAG.md` 的有效结论已吸收，后续只维护本文件。

```text
视频文件 + 文本脚本                         datasets/qa/*.json
        │                                           │
        │                                           ▼
        │                                  generation/utils/data_io.py
        │                                           │
        ▼                                           ▼
retrieval/extract_features.py ──► InternVideo2 ──► query_features.pkl
        │                         interface.py      video_features.pkl
        │                                           │
        └───────────────────────────────────────────┘
                            │
                            ▼
                 retrieval/inference.py
              点积相似度 → video 排名 → Recall@1
                            │
                            ▼
       datasets/retrieval/*/query2videos.json / results/retrieval/*
                            │
                            ▼
                 generation/inference.py（实际读静态 query2videos）
       query + 检索视频 + original/ASR script + METHOD2PROMPT
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
     InternVL2_5        Qwen2.5-VL        LLaVA-Video
          └─────────────────┼──────────────────┘
                            ▼
             results/generation/<数据集>/<模型>/<方法>.json
                            │
                            ▼
                 generation/evaluation.py
             ROUGE-L + BLEU-4 + BERTScore
```

## 1. 项目定位与边界

### 1.1 已读源码事实

- 仓库名为 `VideoRAG`，根目录为 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/60_video_rag_research/starsuzi-VideoRAG`。
- 根 `README.md` 将其定位为论文 **VideoRAG: Retrieval-Augmented Generation over Video Corpus** 的官方实现，对视频语料执行动态视频检索，并把视觉与文本信息共同交给大模型生成回答；论文标识为 arXiv `2501.05874`。
- 当前源码实际形成两条主链：`retrieval/` 负责跨模态特征提取、相似度排序和检索评估；`generation/` 负责载入 LVLM、组合检索视频/脚本/问题并生成答案，再执行文本指标评估。
- 此前细探已确认：这是研究原型/论文实现，不应按生产服务或完整平台理解；该结论已并入本文件。

### 1.2 设计说明（来自 README 与目录组合）

该项目的研究设计是“视频级外部知识检索 + 多模态生成”：先用 InternVideo2 将 query 与视频编码到可比较的向量空间，得到检索结果；再按实验方法把视频、视频脚本或二者注入 InternVL/Qwen/LLaVA-Video 的生成上下文。`Naive`、`VideoRAG-V`、`VideoRAG-VT`、`Oracle-V`、`Oracle-VT` 用来区分无视频、检索视频、检索视频与脚本以及 oracle 视频条件。

### 1.3 未验证项

- 根 README 的 “Frame Selection Mechanism” 和 “Textual Information Extraction” 标为进行中；本仓库存在脚本数据读取与固定帧采样，但没有据此宣称论文全部功能已完成。
- 没有发现根目录 `AGENTS.md`、`CLAUDE.md` 或其他贡献规则文件；未读取到可覆盖本档案的仓库级贡献规范。
- 没有发现根目录统一安装入口、Web 服务、HTTP 路由或 CLI 包装器；实际可执行入口是若干 Python 脚本和 `InternVideo2` 下的 shell 训练/评估脚本。

## 2. 版本、代码地图与证据等级

### 2.1 版本基线（已读取 Git）

| 项目 | 结果 |
|---|---|
| 当前分支 | `main` |
| 当前提交 | `cd4faac2b6f7fa6a0e42acaf51448d57ede1c8c4` |
| 本地提交时间 | `2025-03-17T20:32:57+09:00` |
| 提交主题 | `Merge pull request #3 from starsuzi/kangsan/retrieval` |
| 远程 | `https://github.com/starsuzi/VideoRAG.git` |
| 远程默认分支 | `origin/main` |
| 远程最新提交（经 `127.0.0.1:4780` 查询） | `cd4faac2b6f7fa6a0e42acaf51448d57ede1c8c4` |
| 本地/远程关系 | 当前提交一致，未发现需要独立临时工作区核对的远程落后 |
| 初始工作树状态 | 建档前存在未跟踪细探材料；当前核对已吸收后清理，未修改源码、依赖、测试或配置 |

### 2.2 CodeGraph 与 MCP 证据

- 目标仓库从目标路径向上查找**没有 `.codegraph/`**，因此 `codegraph_explore` 明确返回“未建立代码地图”；本档案未采用其他仓库的地图，也没有把其他项目的代码图结果冒充本仓库证据。
- 首条 `project_context` 按要求调用，但 MCP 返回的项目名称为 `华世王镞_v3`、根目录为 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与目标仓库不一致；其返回的代码地图/最近验证属于错误绑定项目，故不采纳为本仓库证据。
- 本档案的源码证据来自目标工作树实际读取的 `README.md`、入口脚本、核心模型/工具、配置、依赖和数据文件；证据等级按“源码/数据实读 > README/历史研究材料说明 > 未执行推断”处理。

## 3. 目录分层与职责

```text
starsuzi-VideoRAG/
├── README.md                         论文实现定位与引用
├── assets/                           README 图片等静态资源
├── datasets/
│   ├── qa/                           synthetic.json / wikihow.json
│   ├── retrieval/                    query2videos.json 与运行时特征目录
│   │   ├── synthetic/
│   │   └── wikihow/
│   └── scripts/                      original/ 与 asr/ 文本脚本
├── retrieval/
│   ├── extract_features.py           InternVideo2 特征提取入口
│   ├── inference.py                  相似度排序与 Recall@1 入口
│   ├── utils/data_io.py               QA、pickle 特征和检索结果 I/O
│   └── models/InternVideo2/           视频-文本编码模型、训练和评估子仓库
├── generation/
│   ├── inference.py                  多模型视频问答生成入口
│   ├── evaluation.py                 ROUGE/BLEU/BERTScore 评估入口
│   ├── models/                       InternVL、Qwen、LLaVA-Video 适配器
│   └── utils/                        数据、提示词、文本规范化
├── results/                           检索/生成输出目录
└── ARCHITECTURE.md                   本项目唯一架构事实源
```

### 3.1 检索层 `retrieval/`

- `retrieval/extract_features.py`：解析 `--config_path`、`--model_path`、`--is_synthetic`；把 `retrieval/models/InternVideo2` 追加到 `sys.path`，调用 `interface.load_model()`，再调用 `interface.extract_query_features()` 和 `interface.extract_video_features()`，将结果保存为 query/video 两个 pickle 文件。
- `retrieval/inference.py`：调用 `get_base_data()`、`load_features()`；`preprocess_features()` 把字典转成 ID 列表和 `torch.Tensor`；`calculate_similarity_rankings()` 计算 query 与 video 特征的矩阵乘法并降序排序；`evaluate_rankings()` 以每个 query 的 `gold_rankings` 第一视频作为正确答案，计算 Recall@k，默认输出前 200 条预测。
- `retrieval/utils/data_io.py`：以 JSON 表示 QA，以 pickle 表示向量；写文件前创建父目录。默认数据集是 `wikihow`，`--is_synthetic` 切换为 `synthetic`。

### 3.2 模型层 `retrieval/models/InternVideo2/`

这是一个被当前项目直接引用的 InternVideo2 多模态编码子树，不只是文档示例：

- `interface.py::load_model()` 读取 Python 配置，设置 checkpoint，调用 `demo.utils::setup_internvideo2()` 并将模型移到 `cuda`。
- `interface.py::extract_video_features()` 用 `decord.VideoReader` 读取 `.mp4`/`.webm`，固定从视频中取最多 `fn=4` 个代表帧，经 `frames2tensor()` 后调用 `model.get_vid_feat()`；结果键为去掉扩展名的视频 ID。
- `interface.py::extract_query_features()` 从数据中的 `howto100m_query_text` 建立 query 到 `qid` 的映射，调用 `get_text_feat_dict()` 和 `model.get_txt_feat()`，得到文本特征。
- `demo/utils.py::InternVideo2_Stage2` 封装 vision encoder、BERT text encoder、投影层和归一化特征；`get_vid_feat()`、`get_txt_feat()` 是检索阶段实际消费的模型接口。
- `configs/`、`demo/`、`scripts/` 提供配置解析、预训练、zero-shot evaluation 与训练/评估脚本；这是上游模型实验能力，当前根目录 VideoRAG 主链只直接依赖其加载/特征接口。

### 3.3 生成层 `generation/`

- `generation/inference.py::get_model_package()` 根据模型名路由到三个适配器：`InternVL2_5` → `models/InternVL.py`，`Qwen2.5-VL` → `models/QwenVL.py`，`LLaVA-Video` → `models/LLaVA_NeXT.py`。
- `get_knowledge_flags()` 把方法映射为是否使用脚本/视频；`inference()` 对 QA 样本逐条规范化 query，选择 oracle 视频或 `query2videos.json` 的检索视频，读取脚本，使用 `utils/prompt.py::METHOD2PROMPT` 生成提示词，并把结果写为 `question`、`gt`、`pred` 三字段。
- `models/InternVL.py`：用 `decord` 采样最多 `max_frames=32` 个视频片段并转图像 patch，调用 `model.chat()`。
- `models/QwenVL.py`：构造 Qwen 多模态 message，使用 `qwen_vl_utils.process_vision_info()` 和 `AutoProcessor`，调用 `model.generate()`。
- `models/LLaVA_NeXT.py`：依赖外部 `LLaVA-NeXT`，读取视频帧、构造 `qwen_1_5` 对话模板，调用 `model.generate()`。
- `generation/evaluation.py`：读取生成 JSON，使用 `rouge_score`、NLTK BLEU 和 `bert_score` 计算 `ROUGE-L`、`BLEU-4`、`BERTScore`。

## 4. 核心数据模型与持久化

### 4.1 QA 样本（已从 JSON 实读）

`datasets/qa/wikihow.json` 与 `datasets/qa/synthetic.json` 都是长度为 534 的列表；样本至少包含：

- `qid`：query 标识；
- `howto100m_query_text`：InternVideo2 文本特征入口使用的 query 文本；
- `wikihow_query_text`：生成阶段展示/规范化的问题文本；
- `answer_text`：生成评估的 ground truth；
- `videos`：相关视频列表，元素使用 `video_id`，并可能携带论文数据集的其他字段；`wikihow.json` 另外出现 `wikihow_article_id`。

`retrieval/inference.py` 将每条样本转换为 `gold_rankings[qid] = [video['video_id'], ...]`。生成阶段则直接使用 `sample['videos']`（oracle）或以 `str(sample['qid'])` 查检索映射。

### 4.2 检索索引与特征

- `datasets/retrieval/{wikihow|synthetic}/query2videos.json`：字典，键是 query ID，值是按排名排列的视频 ID 数组；`generation/utils/data_io.py::get_retrieved_videos()` 将其转为 `{'video_id': ..., 'rank': ...}` 列表。
- `query_features.pkl`：`retrieval/extract_features.py` 保存的 query 特征字典；当前工作树未发现该文件。
- `video_features.pkl`：视频特征字典；当前工作树未发现该文件。
- `retrieval/inference.py` 不建立数据库或向量数据库，直接将所有特征堆叠成内存 Tensor，使用 `torch.matmul(query_features, video_features.T)` 全量排序。

### 4.3 脚本和结果

- `datasets/scripts/original/{video}.txt` 优先于 `datasets/scripts/asr/{video}.txt`：`get_scripts_for_videos()` 对每个 video 找到第一个存在的文件，读取后逐行 strip 并以空格连接；未找到时脚本为空字符串。
- `results/retrieval/{wikihow|synthetic}/predictions.json`：query 到前 `save_top_k=200` 视频 ID 的预测映射。
- `results/generation/{wikihow|synthetic}/{model}/{method}.json`：每个 `qid` 的 `question`、`gt`、`pred`；这是生成结果，不是下一步检索索引。

## 5. 端到端调用链

### 5.1 特征建立

1. 在仓库根目录执行 `python retrieval/extract_features.py --model_path <checkpoint>`。
2. `parse_arguments()` 读取默认 `retrieval/models/InternVideo2/demo/internvideo2_stage2_config.py`，并根据 `--is_synthetic` 选择 QA 数据。
3. `interface.load_model()` → `Config.from_file()` → `setup_internvideo2()`；加载 checkpoint 并将模型放到 CUDA。
4. `extract_query_features()` 对 `howto100m_query_text` 调 `get_txt_feat()`；`extract_video_features()` 扫描 `./datasets/videos`，采样 `.mp4`/`.webm`，调 `get_vid_feat()`。
5. `save_features()` 将两个字典写入 `datasets/retrieval/<数据集>/query_features.pkl` 与 `video_features.pkl`。

### 5.2 检索与评估

1. 执行 `python retrieval/inference.py [--is_synthetic]`。
2. 载入 QA、query 特征和 video 特征；对齐 ID 与 Tensor。
3. `calculate_similarity_rankings()` 以归一化特征点积作为相似度，逐 query 得到完整 video 排名。
4. `evaluate_rankings()` 使用 QA 内的第一个 gold video 判定 top-k 命中，打印 `Recall@1: <value>`。
5. `save_results()` 输出 `results/retrieval/{数据集}/predictions.json`；但当前 `generation/utils/data_io.py::get_retrieved_videos()` 读取的是 `datasets/retrieval/{数据集}/query2videos.json`，因此两个脚本之间没有由代码直接接通的运行时结果边。

### 5.3 生成与评估

1. 执行 `python generation/inference.py --model <model> --method <method> [--is_synthetic]`。
2. `get_model_package()` 下载/载入所选 LVLM 及 tokenizer/processor；随后 `inference()` 读取 QA 与检索映射。
3. 方法为 `Naive` 时不消费视频/脚本；`VideoRAG-V`/`Oracle-V` 消费视频；`VideoRAG-VT`/`Oracle-VT` 消费视频和脚本。
4. 模型适配器把 query、`prompt.METHOD2PROMPT[method]`、脚本和视频帧交给对应模型，生成文本。
5. 输出 JSON 后执行 `python generation/evaluation.py --file_path <结果文件>`，得到三项文本指标。

## 6. API、CLI、协议边界

### 6.1 公开可复用的 Python 函数边界

| 文件 | 函数/对象 | 职责 |
|---|---|---|
| `retrieval/extract_features.py` | `parse_arguments`, `load_model`, `extract_query_and_video_features`, `main` | 特征建立流程 |
| `retrieval/inference.py` | `load_data`, `preprocess_features`, `calculate_similarity_rankings`, `evaluate_rankings`, `main` | 内存检索与 Recall |
| `retrieval/models/InternVideo2/interface.py` | `load_model`, `extract_query_features`, `extract_video_features` | InternVideo2 适配边界 |
| `generation/inference.py` | `get_model_package`, `get_knowledge_flags`, `get_generation_func`, `inference` | LVLM 路由与生成编排 |
| `generation/models/*.py` | `get_model*`, `prepare_inputs`, `generate` | 各 LVLM 适配器 |
| `generation/evaluation.py` | `calculate_rouge`, `calculate_bleu`, `calculate_bert_score`, `evaluate` | 文本指标 |

### 6.2 CLI 参数

- `retrieval/extract_features.py`：`--config_path`、`--model_path`、`--is_synthetic/--no-is_synthetic`。
- `retrieval/inference.py`：`--is_synthetic/--no-is_synthetic`。
- `generation/inference.py`：`--model`（源码 choices 含 `InternVL2_5-8B`、`LLaVA-Video-7B-Qwen2`、`Qwen2.5-VL-3B-Instruct`）、`--method`、`--is_synthetic/--no-is_synthetic`。
- `generation/evaluation.py`：`--file_path`。
- `retrieval/models/InternVideo2/scripts/**/run.sh` 与 `eval_*.sh`：上游训练和 zero-shot 评估脚本，使用 `torchrun`/DeepSpeed 配置；不是根 VideoRAG 的服务接口。

### 6.3 协议判断

未读到 HTTP、REST、RPC、消息队列或数据库协议实现。跨步骤边界是本地文件协议：JSON、pickle、纯文本脚本和模型 checkpoint；模型调用边界是 Hugging Face Transformers、`decord`、LLaVA 的 Python API。

## 7. 依赖、配置与部署假设

### 7.1 依赖事实

根目录没有 `requirements.txt` 或 `pyproject.toml`。`retrieval/models/InternVideo2/requirements.txt` 固定了一套较旧的 CUDA/PyTorch 组合（如 `torch==1.13.1+cu117`、`torchvision==0.14.1+cu117`、`transformers==4.28.1`）；同目录 `pyproject.toml` 则声明 Python `>=3.10`、更新的 `torch>=2.4.1` 等范围，并包含可选 Git/CUDA 扩展依赖。两份声明存在版本口径差异，应由运行者按目标 GPU/环境裁决，不能视为当前核对已安装或已验证。

运行时从源码可确认的主要依赖包括：PyTorch、NumPy、Pillow、OpenCV、`decord`、`tqdm`、Transformers、`torchvision`、`qwen_vl_utils`、LLaVA-NeXT、`rouge_score`、NLTK、`bert_score`、InternVideo2 所需的 BERT/DeepSpeed/Flash Attention 等。

### 7.2 配置事实

- `retrieval/models/InternVideo2/demo/internvideo2_stage2_config.py` 定义 `num_frames=4`、`size_t=224`、`embed_dim=512`、BERT large 文本编码器、`device="cuda"`、`pretrained_path` 占位符、DeepSpeed stage 1 等。
- `demo/config.py::Config.from_file()` 支持 `.py`、`.yaml`、`.json`；Python 配置通过动态导入加载，`eval_string()` 支持 `${...}` 引用和 `eval(...)`。
- 根脚本的数据路径均为相对当前工作目录的 `./datasets/...` 或 `./results/...`；模型路径、视频目录和 checkpoint 并非统一配置对象。
- `InternVL.py`、`QwenVL.py`、`LLaVA_NeXT.py` 均有 `cuda`/`device_map='auto'`/`bfloat16` 或 Flash Attention 的 GPU 假设。

### 7.3 部署结论

这是离线/批处理研究代码，不是带进程管理和健康检查的部署单元。典型运行需要：本地视频目录 `datasets/videos`（当前工作树不存在）、QA/脚本数据、预生成 checkpoint、匹配 CUDA 的 Python 依赖以及足够 GPU 显存。未执行安装、启动、构建或推理，以上部署条件仅由源码和配置推导。

## 8. 测试与验证现状

### 8.1 已读测试

- 仓库仅发现 `retrieval/models/InternVideo2/tests/test_cfg.py` 与 `retrieval/models/InternVideo2/miscs/test_flops.py` 两个测试/探针文件；未发现根 VideoRAG 的检索、生成或数据 I/O 测试目录。
- `test_cfg.py` 只覆盖 InternVideo2 配置相关行为，不能证明 VideoRAG 端到端检索或生成正确。
- 未发现统一测试入口、CI 配置或服务健康检查。

### 8.2 当前核对验证边界

当前核对按任务要求不安装依赖、不启动服务、不运行模型、不构建、不修改源码/依赖/测试/配置、不提交 Git。仅对新增 `ARCHITECTURE.md` 做回读、章节关键字检查和 `git diff --check`；因此“文档验证通过”不等于“项目运行通过”。

## 9. 风险与未验证项

1. **环境/版本风险**：InternVideo2 的 `requirements.txt` 与 `pyproject.toml` 对 PyTorch、Transformers 等存在明显版本差异；Flash Attention、DeepSpeed、Apex 和 CUDA 组合尚未在本机验证。
2. **数据路径风险**：`retrieval/extract_features.py` 默认读取 `./datasets/videos`，当前仓库没有该目录；所有入口依赖从仓库根启动，换工作目录可能导致相对路径失败。
3. **特征前置风险**：`retrieval/inference.py` 需要 `query_features.pkl` 和 `video_features.pkl`，当前工作树没有；不能直接把 `query2videos.json` 当作模型特征替代品。
4. **生成依赖风险**：三个模型适配器分别依赖不同外部模型代码和权重；`LLaVA_NeXT.py` 的导入发生在模块加载时，缺包会在进入业务逻辑前失败。
5. **GPU/显存风险**：多个适配器直接调用 `.cuda()` 或把 processor 输出移到 CUDA，未提供 CPU 回退；`max_frames=32` 与多视频输入会显著放大显存和推理成本。
6. **检索规模风险**：检索不是索引化 ANN，而是将全部 query/video 特征堆叠进内存并做全量矩阵乘法，规模增大时内存和排序成本线性/超线性上升。
7. **评估口径风险**：`evaluate_rankings()` 只取每个 query gold 视频列表的第一个视频；这与多正例 Recall 的定义可能不同。`generation/evaluation.py` 在空结果、语言和 tokenizer 环境未准备时也没有显式降级策略。
8. **代码健壮性风险**：`retrieval/models/InternVideo2/demo/utils.py::get_text_feat_dict()` 使用可变默认参数 `text_feat_d={}`；配置解析使用动态 `import_module` 和 `eval()`；这些是后续安全与可复现性复核点，当前核对不修改。
9. **结果一致性风险**：检索阶段的 query ID、生成阶段的 `str(sample['qid'])`、`howto100m_query_text` 与 `wikihow_query_text` 分别承担不同键角色；数据集替换或字段清洗时容易出现空匹配。
10. **测试覆盖风险**：根主链没有对应测试，且当前核对未执行模型/数据端到端验证；当前任何 Recall 或生成指标都不能从本档案推断。
11. **远程与工作树风险**：本地 `main` 与经 `127.0.0.1:4780` 查询的 `origin/main` 当前一致；后续若远程变化，需在不覆盖本档案的独立临时工作区复核。

## 10. 结论与后续复核顺序

### 10.1 结论

starsuzi-VideoRAG 是围绕论文 VideoRAG 的离线研究原型：`InternVideo2` 将 QA query 与视频编码并进行全量点积排序，检索结果以 JSON/特征 pickle 落盘；生成侧从检索结果、视频脚本和 query 组装多模态 prompt，支持 InternVL2.5、Qwen2.5-VL、LLaVA-Video 三类模型；最终以 Recall@1、ROUGE-L、BLEU-4、BERTScore 做实验评估。仓库没有 Web/API 服务层、持久化数据库或生产部署控制面，核心契约是本地数据文件和 Python 函数/CLI。

### 10.2 建议的后续深挖顺序（不代表当前核对已执行）

1. 固定一套 CUDA/PyTorch 依赖并做最小模型加载验证，先确认 `InternVideo2` checkpoint 与配置可用。
2. 补齐/确认 `datasets/videos` 与特征 pickle 的来源，核对 query/video ID 对齐和脚本覆盖率。
3. 逐项复核 `retrieval/inference.py` 的 gold 排名与 Recall 口径，再与论文实验脚本/结果对照。
4. 在不加载完整 LVLM 的前提下为 `data_io`、方法路由、prompt 和结果 schema 增加离线单元测试。
5. 最后再做真实 GPU 生成与三项文本指标复现；将模型权重、外部仓库版本和显存要求写入可复现运行说明。

## 11. 本档案证据清单

- `README.md`
- 此前细探材料（已人工吸收并清理）
- `retrieval/extract_features.py`
- `retrieval/inference.py`
- `retrieval/utils/data_io.py`
- `retrieval/models/InternVideo2/interface.py`
- `retrieval/models/InternVideo2/demo/utils.py`
- `retrieval/models/InternVideo2/demo/config.py`
- `retrieval/models/InternVideo2/demo/internvideo2_stage2_config.py`
- `retrieval/models/InternVideo2/configs/data.py`
- `retrieval/models/InternVideo2/configs/model.py`
- `retrieval/models/InternVideo2/README.md`
- `retrieval/models/InternVideo2/requirements.txt`
- `retrieval/models/InternVideo2/pyproject.toml`
- `retrieval/models/InternVideo2/tests/test_cfg.py`
- `generation/inference.py`
- `generation/evaluation.py`
- `generation/models/InternVL.py`
- `generation/models/QwenVL.py`
- `generation/models/LLaVA_NeXT.py`
- `generation/utils/data_io.py`
- `generation/utils/prompt.py`
- `generation/utils/common.py`
- `datasets/qa/synthetic.json`、`datasets/qa/wikihow.json`
- `datasets/retrieval/synthetic/query2videos.json`、`datasets/retrieval/wikihow/query2videos.json`
- 当前 Git 状态、提交、远程默认分支及经 `127.0.0.1:4780` 的远程 HEAD 查询

## 12. 后续：媒体摄取、时序知识与底座映射

当前核对只做目标仓库静态源码取证，并把“当前项目事实”和“归入系统工程平台的候选落点”分开。后者是架构裁决输入，不表示本仓库已经具备生产能力，也不表示已经修改平台底座。

### 12.1 视频摄取与解码：实际是批处理扫描，不是摄取服务

当前视频入口是 `retrieval/models/InternVideo2/interface.py::extract_video_features()`（约 24-52 行），调用方是 `retrieval/extract_features.py::extract_query_and_video_features()`（约 24-38 行）：

1. 以 `os.listdir(video_dir)` 扫描目录，不读取 manifest、媒体元数据表或任务状态；默认目录为 `./datasets/videos`。
2. 只接受文件名以 `.mp4` 或 `.webm` 结尾的条目；其他条目打印 warning 后跳过。
3. 每个视频用 `decord.VideoReader(..., ctx=decord.cpu(), num_threads=1)` 打开；打开失败捕获 `Exception`、打印错误并继续下一个视频。
4. 读取总帧数，零帧打印错误并跳过；随后按最多 `fn=4` 个位置取代表帧，交给 `frames2tensor(..., device='cuda')` 和 `model.get_vid_feat()`。
5. 特征只在函数返回后由 `retrieval/extract_features.py` 一次性写成 `query_features.pkl`、`video_features.pkl`；循环中没有逐条 checkpoint、断点续跑、幂等键或失败清单。

这条链的边界事实如下：

| 环节 | 当前实现 | 生产含义 |
|---|---|---|
| 输入发现 | 目录枚举 + 后缀判断 | 应改为带 `asset_id`、字节摘要、媒体时长/帧率/编码器的不可变 manifest；目录枚举只能保留为研究适配器 |
| 解码 | `decord` CPU reader，单线程 | 属于媒体解码/帧采样支持库能力；模型不应直接拥有文件扫描和重试策略 |
| 采样 | 检索固定 4 帧；生成模型另行采样最多 32 帧 | 采样策略应由知识模块声明版本，结果携带采样参数和来源时间范围 |
| 产物 | Python pickle 字典 | 研究产物可保留；生产应由制品/对象存储支持库写入带 schema、摘要和版本的 artifact |
| 任务状态 | 无 | 需要运行核心拥有排队、租约、进度、重试、取消和恢复 |

### 12.2 ASR、OCR 与文本融合：ASR 是外部静态输入，OCR 缺失

- `generation/utils/data_io.py::get_scripts_for_videos()`（约 27-43 行）按 `original/{video}.txt`、`asr/{video}.txt` 顺序查找，找到第一个就逐行 `strip` 后用空格拼接；不存在时返回空字符串。
- 因而当前仓库**消费 ASR 文本，不执行 ASR**：没有音频解码、语音模型、词级/句级时间戳、语言识别、置信度、说话人或 ASR 任务状态。`datasets/scripts/asr/` 是已落盘的数据目录，不是运行时 provider。
- 当前核对对目标树按文件名和源码关键字核对，未发现 OCR provider、OCR 入口、帧文字检测/识别、文字框坐标或 OCR 结果 schema；README 中的“Textual Information Extraction”只能作为项目声明/研究方向，不能当作 OCR 已实现。
- 原始脚本优先于 ASR 脚本，且两者都被压成无定位的字符串；没有保留 `start/end`、帧号、词边界、来源模态或置信度。因此不能从当前结果反向定位回答依据到视频时间片段。

归底座时，ASR/OCR 应是两个可替换的**支持库 provider**（分别承担音频/帧输入、模型调用、结构化输出和外部依赖隔离），知识模块负责选择文本来源、去重、对齐、冲突策略和版本化融合；不得让网关或运行核心直接 import Whisper、PaddleOCR 等第三方实现。

### 12.3 时间片段与证据定位：有采样算法，没有时间知识模型

源码中“片段”仅表示一次读取的帧集合，不是可持久化的时间实体：

- `interface.py::extract_video_features()` 根据总帧数均匀取最多四帧，但不计算或保存秒级 `start/end`，特征键只有去扩展名的视频 ID（约 45-50 行）。
- `generation/models/InternVL.py::get_index()` 用 `fps` 将可选 `bound` 换算成帧索引，并默认取 32 个均匀位置；当前调用 `generate()` 没有传 `bound`，所以默认覆盖整段视频（约 98-129、143-161 行）。
- `generation/models/QwenVL.py::get_message()` 给视频输入 `fps=1`、`max_frames`，这是 processor 输入限制，不是系统时间片段记录（约 20-47 行）。
- `generation/models/LLaVA_NeXT.py::load_video()` 以 `fps=1` 采样，超出上限时 `np.linspace` 均匀抽帧，并生成局部 `frame_time` 字符串；该时间文本不被返回给上层结果，也没有落盘为引用（约 28-44 行）。

因此当前无 `segment_id`、`start_ms/end_ms`、时区/帧率基线、片段版本、片段与 ASR/OCR span 的对齐关系，也无“回答引用哪些片段”的输出契约。生产落点应是知识模块的时间轴/片段模块：支持库提供媒体时钟与采样原子能力，模块产生不可变 `VideoSegment`、`TranscriptSpan`、`OCRSpan` 和 `EvidenceRef`，运行核心负责其任务生命周期，网关只暴露查询/提交/取消后的稳定引用。

### 12.4 向量索引、图索引与检索问答实际边界

#### 向量：特征文件 + 内存全量矩阵，不是向量数据库

`retrieval/utils/data_io.py::save_features/load_features()` 用 pickle 读写 Python 字典（约 15-25 行）；`retrieval/inference.py::preprocess_features()` 将字典堆成 `torch.Tensor`，`calculate_similarity_rankings()` 执行 `torch.matmul(query_features, video_features.T)` 后全量排序（约 22-35 行）。模型侧 `InternVideo2_Stage2::get_vid_feat/get_txt_feat()` 做归一化特征（`demo/utils.py` 约 274 行以后）。当前未发现 FAISS、Milvus、Qdrant、pgvector 或其他 ANN/向量存储实现。

这意味着：

- 查询与视频向量没有独立的 schema、模型版本、维度、归一化方式、租户/数据集分区或索引版本元数据。
- 复杂度和内存随视频数增长；所有 query/video 特征先在一个 Python 进程内构成矩阵，不能提供生产级 top-k 分页、并发隔离或增量更新。
- 检索保存 `results/retrieval/.../predictions.json`，但生成入口 `generation/utils/data_io.py::get_retrieved_videos()` 默认读取静态的 `datasets/retrieval/.../query2videos.json`。所以“检索脚本产出 → 生成脚本消费”在当前代码中并非直接运行时链路，必须把它记录为研究装配的人工/外部步骤。

#### 图：当前不存在图索引

目标树没有图数据库依赖、图 schema、节点/边写入或图查询入口；视频、query、脚本、排名之间是 JSON/pickle 中的字典/列表关系，不是可遍历知识图。图索引应列为**新建支持库适配 + 新建知识模块能力**，不能把 `query2videos.json` 命名为图索引。

#### QA：研究脚本中的 prompt 组装，不是可审计问答服务

`generation/inference.py::inference()`（约 48-84 行）逐条读取 QA，按 method 选择 oracle 视频或静态 `query2videos.json`，再选择脚本，调用模型适配器并将 `question/gt/pred` 放入内存结果；所有样本结束后才由主程序写 JSON（约 97-110 行）。当前没有：

- 查询请求 ID、会话/租户、超时和取消契约；
- 检索快照、模型版本、prompt 版本、证据片段和引用坐标；
- grounded answer 与“无法回答/证据不足”的结构化结果；
- 流式输出、幂等提交、失败重试、部分结果可读或结果查询 API。

因此知识模块的生产问答应拆为“检索 → 可选重排 → 证据包 → 生成 → 引用校验/答案产物”步骤；模型只能产生候选答案，不能代替知识模块决定索引事实、证据归属或任务状态。

## 13. 研究脚本与生产链的边界

### 13.1 当前仓库的研究链

```text
本地 datasets/videos + datasets/qa/*.json + 预先准备的 scripts/*.txt
  → retrieval/extract_features.py
  → InternVideo2 / query_features.pkl + video_features.pkl
  → retrieval/inference.py（内存点积全量排序）
  → results/retrieval/.../predictions.json

datasets/retrieval/.../query2videos.json（静态输入，非上一步自动输出）
  + datasets/scripts/original|asr/*.txt
  + 本地视频
  → generation/inference.py → LVLM → results/generation/.../*.json
  → generation/evaluation.py → ROUGE-L/BLEU-4/BERTScore
```

研究脚本特征是：相对路径、单进程顺序循环、内存状态、一次性最终写盘、模型/视频路径写在函数默认值或 CLI 中、没有服务协议。`retrieval/models/InternVideo2/scripts/**` 的 `torchrun`/DeepSpeed 训练和 zero-shot 评估也属于研究/训练工具，不应直接视为生产任务执行器。

### 13.2 生产链候选（只作为底座装配目标）

```text
网关：提交摄取/索引/问答 + 查询状态/结果 + 取消
  → 运行核心：任务、租约、进程组、超时、取消、GPU预算、重启恢复
  → 知识模块：媒体登记 → ASR/OCR → 时间片段/证据对齐
  → 支持库：媒体解码、ASR/OCR、embedding、向量库/图库、模型推理、制品存储
  → 知识模块：增量索引 → 混合检索/重排 → 证据包 → 多模态生成 → 引用校验
  → 运行核心：结果/事件/指标/失败证据持久化
  → 网关：返回可追溯答案、片段引用、状态和稳定错误码
```

单链路原则：网关不直连模型或数据库；知识模块不自行创建第二套任务/超时/重试器；支持库不包含“一个视频问答业务流程”；运行核心不理解 prompt 或召回规则。每个原子能力必须有唯一能力 ID、契约 owner、输入/输出 schema、资源预算、可重试语义和释放责任。

## 14. 底座归属裁决：支持库、知识模块、运行核心、网关

| 当前项目能力/缺口 | 归属 | 裁决 | 说明 |
|---|---|---|---|
| `decord`/OpenCV/PIL 读视频、媒体探测、帧采样 | 支持库 | 复用/升级现有媒体支持库（若已有）；否则新建媒体解码原子能力 | 输入输出要带媒体摘要、帧率、时长、采样参数；不把目录扫描塞进模型模块 |
| ASR、OCR | 支持库 provider | 新建 provider 能力，知识模块只依赖公开契约 | 缺 provider 返回明确不可用；第三方/C 扩展在隔离环境或子进程，不能穿透主进程 |
| 视频资产登记、脚本/ASR/OCR 融合、文本去重 | 知识模块 | 新建“视频知识摄取/文本融合”模块 | 负责领域规则、来源优先级、版本和 provenance，不负责进程重启 |
| 片段、span、时间轴、证据引用 | 知识模块 | 新建“视频时间知识”模块 | 统一 `start/end`、帧范围、来源模态、置信度、引用指针和 schema 版本 |
| embedding、重排、LVLM 调用 | 支持库 provider | 复用统一模型/推理能力；升级为视频-文本输入契约 | provider 只返回结构化结果/错误与资源统计，不拥有 QA 流程 |
| 向量库、图库 | 支持库适配层 | 向量/图存储分别建唯一适配能力 | 事务、索引版本、维度、过滤条件、top-k 和删除语义必须显式；当前仓库没有实现可直接复用 |
| 摄取/ASR/OCR/索引/问答编排 | 知识模块 | 新建视频 RAG 知识模块 | 以 stage/run/asset/segment/evidence 为领域对象，串联支持库公开入口 |
| 线程/进程、GPU、显存、超时、取消、重试、租约、崩溃恢复 | 运行核心 | 复用运行核心任务与资源治理；升级 GPU 预算/隔离 | 运行核心拥有终态和释放证据，不把异常处理散在各 provider |
| 提交、状态、取消、结果、流式事件 | 统一网关 | 复用 HTTP 能力网关，新增契约而非新 Web 服务 | 网关做鉴权/限流/契约/调用，不保存第二份领域状态 |
| 当前 `*.py` 研究脚本 | 项目适配层/研究工具 | 隔离保留，废弃其生产入口地位 | 研究脚本可作为离线导入器、回归夹具和 benchmark runner，不直接挂生产网关 |

### 14.1 复用/升级/新建/废弃结论

| 结论 | 项目模式 | 依据 |
|---|---|---|
| 吸收 | 归一化视频/文本 embedding、固定采样和模型适配边界 | `interface.py`、`demo/utils.py`、三种 `generation/models/*.py` 已形成可识别的 provider seam，但需补契约和资源治理 |
| 升级 | 文件制品写入、任务编排、错误/结果、GPU/子进程管理 | 当前仅 `pickle/json` 最终写盘，无 checkpoint、取消、恢复或稳定错误码 |
| 新建 | ASR/OCR、时间片段、证据引用、向量存储、图存储、视频知识模块 | 本仓库没有对应实现；README 声明不能替代源码证据 |
| 隔离/废弃为生产入口 | `retrieval/extract_features.py`、`retrieval/inference.py`、`generation/inference.py` 直接作为服务入口的用法 | 相对路径、全量内存排序、静态映射、无任务状态和无故障治理；保留作为研究/回归适配器 |

## 15. 失败、超时、取消、OOM、崩溃矩阵

下表“当前行为”是源码事实；“生产要求”是平台映射要求，不能反写成当前项目已实现。

| 场景 | 当前源码行为 | 生产链必须补的契约/恢复动作 |
|---|---|---|
| 视频目录缺失 | `os.listdir(video_dir)` 直接抛 `FileNotFoundError`，无结构化错误 | 摄取任务失败并记录 `INPUT_NOT_FOUND`；不创建空索引；租约释放、错误可查询 |
| 单个视频打不开 | `VideoReader` 异常被打印后 `continue`，没有失败清单 | 记录 asset 级失败原因、可重试性和解码器版本；批次完成状态应区分成功/部分成功/失败 |
| 零帧或后缀不支持 | 打印后跳过 | manifest 标记 `UNSUPPORTED_MEDIA`/`EMPTY_MEDIA`，保留证据；禁止静默丢失 |
| 短视频少于 4 帧 | `range(..., total_frames // fn)` 可能出现步长为 0；异常不在 per-video try 内 | 采样器先做边界裁剪，返回可验证的采样计划；单资产失败不杀整批 |
| 帧读取/模型推理异常 | 主要推理调用在 `try` 外，异常会终止整次脚本；最终 pickle 可能尚未写出 | stage 级重试 + 幂等 artifact；失败事件、输入摘要、模型版本和 traceback 摘要落账 |
| pickle 缺失/损坏 | `open`/`pickle.load` 直接抛异常 | `ARTIFACT_NOT_FOUND`/`ARTIFACT_CORRUPT`，禁止把旧索引误当新索引；可从上游 stage 重建 |
| query/video ID 或维度不匹配 | 无显式 schema 校验；可能在矩阵乘法或后续索引处抛异常，或跳过 query | 建立维度/模型指纹/ID 对齐门禁；不匹配必须阻断索引激活 |
| 检索结果缺 qid | 生成侧 `query2videos[str(qid)]` 可能 `KeyError`；无单条降级 | 返回可解释的 `RETRIEVAL_MISS` 或证据不足，不生成无依据答案；记录快照版本 |
| 视频文件在生成时缺失/损坏 | 各模型 `VideoReader`/processor 异常未统一捕获，批次中断 | 资产版本锁定；失败可重试，结果不应覆盖已完成样本 |
| 外部 ASR/OCR provider 不可用 | 当前没有 provider 调用，因此没有降级契约；缺文件只返回空字符串 | provider 缺失明确错误；可配置“仅视觉/仅文本/失败”策略，不能将空文本伪装成功 |
| 超时 | 当前无 timeout 参数、deadline 或 watchdog | 运行核心持有硬截止；超时触发取消/进程组终止，返回 `TIMEOUT`、是否可重试、清理证据 |
| 主动取消 | 当前 Python for-loop 无取消 token；只能依赖外部终止 | 取消要传播到队列、provider、子进程、GPU batch；终态幂等为 `CANCELLED`，释放句柄/租约/临时目录 |
| CUDA OOM/显存不足 | 直接 `.cuda()`、`device_map='auto'`、bfloat16/Flash Attention；无 OOM 捕获、降级或 `empty_cache` | 运行核心按 GPU/显存预算调度；provider 返回 `GPU_OOM` 与峰值；可按策略减帧/减 batch/换 GPU 重试，禁止无限重试 |
| Python 进程/模型崩溃 | 主链非 subprocess；主进程退出且结果只在最终保存，部分内存结果丢失 | 高风险 C/CUDA/第三方模型放独立进程组；心跳、退出码、信号、stderr、重启次数和 artifact 对账；恢复从最近 checkpoint 继续 |
| 结果写入中断 | `save_results`/`save_features` 直接打开目标文件写，非临时文件 + 原子替换 | 支持库提供临时文件、fsync、原子 rename、摘要和版本指针；崩溃后旧版本仍可读 |
| 重复提交/重试 | 无幂等键；重复脚本可能覆盖同一 JSON/pickle | 以 `job_id + input_digest + stage_version` 去重；同摘要幂等复用，不同摘要拒绝覆盖 |
| 生成答案缺证据 | 当前只写 `question/gt/pred`，没有 citation 或 groundedness 字段 | QA 模块输出证据包、片段引用、模型/检索快照和“证据不足”状态；网关只返回已落账结果 |

## 16. L0-L4 分层与装配计划

这里的 L0-L4 是**平台落点层级**，不是本仓库已有的运行等级；当前仓库主要停留在 L0/L1 的研究脚本形态，L2-L4 是生产化缺口。

| 层级 | 平台职责 | 本项目对应事实 | 装配验收 |
|---|---|---|---|
| L0 原始材料与研究制品 | 视频、QA、原始/ASR 文本、checkpoint、JSON/pickle、benchmark 结果 | `datasets/videos`（运行时假定）、`datasets/qa`、`datasets/scripts`、`datasets/retrieval`、`results` | 每个 asset/artifact 有摘要、来源、schema、版本；禁止以目录存在代替登记 |
| L1 原子支持能力 | 媒体探测/解码/采样、ASR、OCR、embedding、模型推理、向量/图 CRUD、对象制品读写、GPU 探测 | 现有 `decord`、InternVideo2、LVLM 适配器可作为 provider 研究样本；ASR/OCR/向量库/图库未实现 | 契约、错误码、超时/取消、资源所有权、provider 可用性和真实返回值测试 |
| L2 知识模块 | 视频摄取、文本融合、时间片段、向量/图索引、检索/重排、证据包、视频 QA | 当前脚本跨层混合：扫描、采样、检索、prompt、保存均在脚本/适配器中 | 领域 schema、stage 状态、版本快照、引用坐标、单一写 owner、重放一致性 |
| L3 运行核心 | 作业/进程组/租约、GPU/显存预算、deadline、取消、重试、OOM、崩溃恢复、事件与诊断 | 当前无统一任务服务；研究脚本异常多为打印、抛异常或整进程退出 | 正常/失败/超时/取消/崩溃四终态；无残留进程、句柄、锁、临时文件；恢复后不重复写 |
| L4 统一网关与生产控制面 | 鉴权、限流、稳定 HTTP 能力、提交/状态/取消/结果/流式事件、审计与观测 | 当前无 HTTP/REST/RPC；CLI 是脚本参数 | 网关只调用模块公开入口；稳定错误码、契约版本、幂等键和可追溯 `job_id`；不直连 provider |

### 16.1 依赖与资源契约草案

| 能力 | 输入 | 输出 | 关键资源责任 |
|---|---|---|---|
| 媒体解码/采样 | asset 引用、采样策略、deadline | 帧/时间范围/媒体元数据 | 创建者释放 `VideoReader`/临时帧；取消和异常关闭解码器 |
| ASR/OCR | 媒体片段、语言/模型版本 | span 文本、时间范围、置信度、来源 | provider 子进程/模型内存/GPU 在调用结束或终止时释放 |
| 视频/文本 embedding | 规范化文本或片段帧、模型指纹 | 向量、维度、归一化和版本 | GPU 预算由运行核心授予；OOM 不得无限重试 |
| 向量/图索引 | artifact/segment/evidence、index_version | upsert、top-k、邻接/过滤结果 | 写 owner 负责事务、索引版本、幂等和回滚；模块不得旁写数据库 |
| 多模态生成 | query + 证据包 + 模型版本 | answer、引用、token/资源统计 | 模型 provider 不拥有任务状态；取消时进程组和 GPU 工作必须可回收 |

### 16.2 生产装配工作包（只列计划，不宣称已实施）

1. **W0 契约冻结**：定义 `Asset`、`MediaManifest`、`TranscriptSpan`、`OCRSpan`、`VideoSegment`、`Embedding`、`IndexVersion`、`EvidenceRef`、`RetrievalSnapshot`、`AnswerArtifact` 和统一错误码。
2. **W1 支持库**：把 `decord`/帧采样和模型调用包成 provider；补 ASR/OCR provider 能力与独立环境/子进程边界，建立可用性检测和真实失败测试。
3. **W2 知识摄取**：登记视频、媒体探测、ASR/OCR 融合、原始文本优先级、时间对齐和可重放 stage；每 stage 写不可变 artifact 与失败证据。
4. **W3 时序与索引**：建立片段/span/evidence schema；先接向量索引，再按需求接图索引；向量维度、模型指纹、分区和索引版本必须进入契约。
5. **W4 检索问答模块**：检索、重排、证据包、生成和引用校验分步实现；保留研究 `query2videos.json` 适配器，但不得让它绕过正式索引 owner。
6. **W5 运行核心接线**：统一作业、租约、deadline、取消、OOM 策略、子进程组、心跳、checkpoint、恢复和残留审计；禁止模块自建线程/重试中心。
7. **W6 网关与验收**：为提交/查询/取消/结果/流式事件编译消费者契约；做正常、部分失败、超时、取消、OOM、SIGKILL、重复提交和恢复后的真实端到端验收。

## 17. 后续真假验证表与剩余风险

| 项目 | 源码事实 | 测试/运行证据 | 当前核对结论 |
|---|---|---|---|
| 视频摄取/解码 | `interface.py` 有目录扫描、decord 打开、四帧采样 | 未安装依赖、未运行视频解码 | 部分实现；研究批处理，不是生产摄取 |
| ASR | `datasets/scripts/asr/*.txt` 被读取 | 未执行 ASR | 静态输入消费；无 ASR provider |
| OCR | 目标树无 OCR 文件/入口/依赖命中 | 未执行 OCR | 未实现/未发现 |
| 时间片段 | InternVL/LLaVA 有局部采样索引 | 无持久化 start/end/引用测试 | 采样存在，时间知识缺失 |
| 向量索引 | pickle + Tensor 全量 matmul/sort | 无 ANN/向量库实测 | 研究级内存检索 |
| 图索引 | 未发现图依赖/schema/查询 | 无图运行证据 | 未实现 |
| 检索→QA | 两个脚本均存在，但 QA 读静态 `query2videos.json` | 未做跨脚本真实重跑 | 结果边未直接接通 |
| 模型/GPU | 多处 `cuda`、`device_map='auto'`、bfloat16/Flash Attention | 未加载权重/未测显存 | 强 GPU 假设，资源治理缺失 |
| 超时/取消/OOM/崩溃 | 未发现统一治理或子进程边界 | 未做故障注入 | 生产能力全部待建 |
| 平台归属 | 可按 L0-L4 映射 | 未修改平台底座 | 只形成后续架构输入 |

当前核对没有安装依赖、下载权重、启动服务、运行模型或修改源码/依赖/配置/测试；只更新本项目根 `ARCHITECTURE.md`。因此上述“生产链候选、底座归属、装配工作包”均是基于源码缺口的裁决，不是已经通过的实现。

## 18. 后续真实源码研究补充：摄取、采样、生命周期与验证等级

本节是对前述后续结论的源码级补强。它只记录目标树中实际读到的实现，不把 `retrieval/models/InternVideo2/` 上游子树中未被根流程调用的能力，误记为 VideoRAG 主链能力。

### 18.1 摄取与采样的两套实现必须分开看

根流程 `retrieval/models/InternVideo2/interface.py::extract_video_features()` 是最窄的摄取入口：`os.listdir()` 枚举本地目录，后缀白名单只有 `.mp4`/`.webm`，`VideoReader` 使用 CPU、单线程，按 `total_frames // 4` 计算四个中心位置，随后一次性调用 `get_batch()`。它不读取时长、平均帧率、编码器、音轨、文件摘要或修改时间，也不为每个视频记录输入 manifest。

上游子树的 `dataset/video_utils.py` 另有较丰富的采样原语：

- `get_frame_indices()` 支持区间均匀随机/中点采样和 `fps0.5` 一类按帧率采样，并可限制最大帧数；
- `read_frames_decord()` 可返回帧、帧索引和由平均 FPS 推导的 duration，并对 `s3://` 输入预留 client；
- `read_frames_av()`、`read_frames_gif()`、`read_frames_img()` 支持其他媒体形态；
- 但根 `interface.py` 没有调用这些函数，因而这些是上游训练/数据集能力，不是当前 VideoRAG 摄取契约。

生成侧又是第三套采样：InternVL 默认均匀取 32 段并把所有帧拼成 patch；Qwen 通过 processor 声明 `fps=1`、`min_frames=1`、`max_frames=max(2, max_frames)`；LLaVA 先按平均 FPS 取帧，超过上限后 `np.linspace` 均匀抽样，并计算 `frame_time`，但只在适配器局部变量中存在。三套策略没有共享版本、时间坐标或统一采样产物，检索四帧也不会复用于生成。

边界异常尤其重要：根检索采样在 `total_frames < fn` 时可能出现 `total_frames // fn == 0`，`range()` 步长为零会在视频级 `try` 之外抛出；而上游 `get_frame_indices()` 对短视频有按实际长度采样并用末帧补齐的路径。生产采样器不能复刻根入口的隐含假设，必须先生成可审计的采样计划，再执行解码。

### 18.2 ASR/OCR/向量不是同一条“多模态抽取”链

当前脚本融合的文本只有文件系统中已存在的 `original` 或 `asr` 文本：原始脚本优先，读取全部行后 `strip` 并以空格拼接；不存在时返回空字符串。没有音频抽取、ASR 推理、语言/说话人/置信度、词级时间戳，也没有把文本绑定到帧或 segment。OCR 在目标树中没有入口、依赖、输出字段或结果样本，README 的“字幕缺失时文本信息提取”仍是项目目标而非实现事实。

向量流程也不是“抽取后写入向量库”：InternVideo2 的视频和文本特征在 `get_vid_feat()`/`get_txt_feat()` 中经过投影与 L2 归一化，根脚本将 NumPy 数组放入 Python 字典并 pickle；检索时 `np.stack` 成 Tensor，执行全量 `query @ video.T` 和排序。没有批次级 schema、维度/模型指纹校验、ANN、增量 upsert、删除、分区或索引激活。生成阶段消费的是预存 `query2videos.json`，不是检索脚本刚写出的 `results/retrieval/.../predictions.json`，所以检索到 QA 的接线必须视为外部装配步骤。

### 18.3 模型与资源生命周期的源码事实

| 资源 | 当前事实 | 缺口/生产约束 |
|---|---|---|
| InternVideo2 | `load_model()` 解析配置、加载 checkpoint、`model.to('cuda')`；特征函数内部 `torch.no_grad()`，但不提供 unload、显存统计或上下文管理 | 运行核心应拥有模型进程/租约/显存预算；退出时释放 CUDA、解码器和临时产物 |
| InternVL | `from_pretrained(...).eval().cuda()`，固定 bfloat16、Flash Attention、单例式常驻参数；视频张量最终 `.cuda()` | 无 CPU 回退、deadline、OOM 降级、峰值记录或显式释放 |
| Qwen-VL | `device_map='auto'` 加载；processor 输出整体 `.to('cuda')`，调用 `generate()` | 自动分片不等于预算治理；没有取消 token、批次 checkpoint 或 OOM 策略 |
| LLaVA-Video | 外部 `llava` 在模块导入时就加载符号；模型 `eval()`、`device_map='auto'`；每个视频帧张量 `.cuda().bfloat16()` | 缺包会在业务逻辑前导入失败；第三方/CUDA 风险应隔离进程 |
| 解码器/文件 | `VideoReader` 在局部函数中创建，无显式 close/finally；结果只在整个循环结束后写 pickle/JSON | 需要可回收句柄、临时文件原子替换、逐资产 checkpoint 和失败清单 |

生成 `inference()` 逐样本循环，结果保存在内存字典中，只有主程序返回后才 `save_results()`；模型异常、进程被杀或后续样本失败都会丢失此前未写盘结果。检索特征也是 query 与 video 两个完整字典全部返回后才写盘。当前没有模型池、复用租约、并发上限、超时、取消、重启恢复、心跳或资源释放证据。

### 18.4 失败矩阵细化：失败发生在哪一层

| 层级 | 已确认触发点 | 当前结果 | 需要达到的验证/运行语义 |
|---|---|---|---|
| 发现 | `datasets/videos` 不存在、目录含不支持后缀 | 缺目录直接抛异常；不支持后缀打印后跳过 | 输入错误码、manifest 状态、不可重试/可重试判定 |
| 解码 | `VideoReader` 打开失败、零帧、短视频步长为零 | 单个打开失败继续；零帧继续；短视频可能终止整批 | 资产级失败隔离，短视频边界测试，批次部分成功 |
| 抽取 | `get_batch`、CUDA、模型 forward 失败 | 主要调用在 `try` 外，可能终止进程；没有中间 artifact | stage checkpoint、模型/输入指纹、有限重试和失败证据 |
| 持久化 | pickle/JSON 打开、序列化或写入中断 | 直接写目标路径，可能留下截断文件或无结果 | 临时文件 + fsync/原子替换，artifact 校验与恢复 |
| 对齐 | qid、video_id、特征维度或静态映射缺失 | 可能矩阵报错、跳过 query 或生成 `KeyError` | 激活前 schema 门禁；单条 RETRIEVAL_MISS，不伪造答案 |
| 生成 | 视频路径缺失、processor/model 异常、显存不足 | 未统一捕获，循环中断 | 样本级状态、有限重试、降帧/减 batch 策略、GPU_OOM |
| 评估 | 空结果、依赖缺失、预测字段缺失 | 指标计算可能异常；没有零样本/跳过解释契约 | 明确输入 schema、依赖探针、零结果阻断、指标版本 |
| 进程 | SIGTERM、SIGKILL、第三方 native/CUDA 崩溃 | 内存结果丢失，无恢复或残留审计 | 独立进程组、心跳、退出证据、可恢复 checkpoint、资源回收 |

### 18.5 验证等级：从“读到源码”到“真实闭环”

为避免把静态研究结论、轻量导入和真实 GPU 复现混为一谈，本档案采用以下证据等级：

| 等级 | 证据要求 | 本仓库后续状态 |
|---|---|---|
| V0 静态存在性 | 读取源码/配置/数据目录，确认入口、字段、依赖和控制流 | 已完成；支持上述源码事实和缺口判断 |
| V1 纯函数/文件夹具 | 不加载大模型，验证采样边界、ID 对齐、prompt、JSON/pickle schema、原子写入语义 | 未建立根级测试；不能宣称通过 |
| V2 依赖与媒体烟测 | 在匹配环境中真实打开代表性 mp4/webm，执行少量帧采样、脚本读取和特征接口返回 | 未安装依赖、未读取真实视频；未通过/未执行 |
| V3 GPU 集成 | 加载真实 checkpoint，完成 query/video embedding、排序、至少一个 LVLM 生成和指标计算 | 未下载权重、未加载模型、未执行 |
| V4 故障与恢复 | 注入缺失文件、坏媒体、短视频、维度错、OOM、超时、取消、SIGKILL，核验终态、重试、checkpoint 和资源清理 | 当前实现没有治理面；未执行，且生产能力待建 |

当前核对最终判定为 **V0 已完成，V1-V4 未完成**。因此 `Recall@1`、ROUGE-L、BLEU-4、BERTScore 的源码计算路径可以描述，但不能被解释为本机真实复现结果；“模型支持”也只能表示适配器代码存在，不能表示权重、CUDA、显存和外部包已验证。

### 18.6 后续收束结论

真实源码显示，VideoRAG 当前最有价值的可复用边界是“归一化视频/文本 embedding + 多模型视频输入适配器 + 研究级静态脚本消费”，而不是完整的媒体知识摄取平台。后续若生产化，优先级应为：先冻结资产/片段/span/evidence 与错误码 schema；再把媒体解码、采样、ASR、OCR、embedding、LVLM 放入可隔离 provider；随后由知识模块接管增量索引、检索快照和证据包；最后由运行核心补齐模型生命周期、GPU 预算、超时取消、崩溃恢复和原子制品提交。任何只把当前脚本挂到网关、而不解决静态 `query2videos.json` 接线、全量内存排序和最终写盘丢失的问题，都不构成真实 VideoRAG 生产闭环。
