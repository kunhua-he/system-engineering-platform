# MiniCPM-V 架构归档

> 本文是本项目根目录唯一的架构事实文档。源码参考仓库默认只读；本轮只新增本文件，未修改源码、依赖、测试、配置、权重或启动脚本。
>
> 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_multimodal_models/MiniCPM-V`

## 1. 项目定位

MiniCPM-V 是 OpenBMB 的端侧友好多模态模型系列代码与配套资料，覆盖图像、视频、文本理解，并在同一仓库中保留 MiniCPM-o 的实时音视频全模态 Demo。当前 README 的宣传/使用入口已经推进到 **MiniCPM-V 4.6** 与 **MiniCPM-o 4.5**；仓库内可直接阅读和运行的自有 Python 代码主要是 MiniCPM-V 2.0/2.5/2.6、OmniLMM-12B、MiniCPM-o 2.6 以及评测/微调工具。4.5/4.6 的模型主体通过 Hugging Face `transformers` 的 `trust_remote_code=True` 从模型仓库加载，模型权重不在本仓库内。

项目的核心边界是“模型加载与多模态推理适配”，不是通用服务平台：

- 图像路径：图像解码、尺寸/分片处理、视觉编码、视觉 token/hidden states 注入语言模型、文本生成。
- 视频路径：视频帧抽取后复用图像消息；新版文档推荐 `torchcodec` 或 `PyAV`，旧 Demo 使用 `decord`。
- 全模态路径：MiniCPM-o 2.6 通过 `streaming_prefill`/`streaming_generate` 处理连续音频、视频和语音输出。
- 训练路径：JSON 样本 + 图像占位符 → tokenizer/视觉预处理 → `Trainer`/DeepSpeed 或 LoRA。
- 评测路径：本地 `vlmevalkit` 与 `vqaeval` 适配器调用 Hugging Face 模型。

## 2. 真实调用流程

```text
图像/视频/文本/音频
        │
        ├─ Transformers 模型仓库（AutoModel/AutoProcessor，trust_remote_code）
        │       │
        │       ├─ apply_chat_template / 视觉预处理 / 视频帧采样
        │       └─ model.chat 或 model.generate
        │                │
        │                └─ 文本结果（或 MiniCPM-o 的文本+音频流）
        │
        ├─ 本地 OmniLMM 旧路径（chat.py）
        │       └─ OmniLMMForCausalLM
        │             └─ OmniLMMModel
        │                   ├─ timm EVA02 视觉塔
        │                   ├─ Resampler（视觉特征→固定查询 token）
        │                   └─ Mistral 语言模型/`lm_head`
        │
        ├─ 训练
        │       └─ JSON → `SupervisedDataset` → `preprocess`
        │            → `conversation_to_ids`/图像切片 → `data_collator`
        │            → `CPMTrainer`/DeepSpeed/LoRA → checkpoint
        │
        ├─ 评测
        │       └─ `vlmevalkit/run.py`
        │            → `vlmeval.config.supported_VLM`
        │            → `MiniCPM_V` 等适配器 → benchmark 输出
        │
        └─ MiniCPM-o 2.6 Web Demo
                └─ FastAPI `StreamManager`
                      ├─ `/stream` 或 WebSocket 接收流式消息
                      ├─ `streaming_prefill`
                      ├─ `/completions` → SSE `streaming_generate`
                      └─ `/stop`、`/feedback`、`/init_options`、`/health`
```

## 3. 目录地图与分层

```text
MiniCPM-V/
├── chat.py                         # 旧版 OmniLMM/MiniCPM-V 本地推理封装
├── omnilmm/                        # OmniLMM-12B 本地模型实现
│   ├── model/omnilmm.py            # Mistral + EVA02 + Resampler + generation
│   ├── model/resampler.py          # 2D Perceiver-Resampler
│   ├── model/utils.py              # 图像变换、切片、占位符、停止条件
│   ├── train/train_utils.py        # OmniLMM 训练预处理
│   ├── conversation.py             # Conversation 数据对象和图片转换
│   └── constants.py
├── finetune/                       # 监督微调/LoRA/DeepSpeed
│   ├── finetune.py                 # HfArgumentParser、模型与 Trainer 装配
│   ├── dataset.py                  # 样本、token、视觉输入与 collator
│   ├── trainer.py                  # CPMTrainer（继承 transformers.Trainer）
│   └── ds_config_zero{2,3}.json
├── web_demos/                      # Gradio/Streamlit/实时全模态 Demo
│   ├── web_demo*.py                # MiniCPM-V 2.0/2.5/2.6
│   ├── web_demo_streamlit*.py      # Streamlit 版本
│   └── minicpm-o_2.6/
│       ├── model_server.py         # FastAPI + SSE/WebSocket + StreamManager
│       ├── chatbot_web_demo_o2.6.py
│       └── web_server/              # Vue/Vite 前端、音视频交互组件
├── eval_mm/
│   ├── vlmevalkit/                 # 多 benchmark 评测框架及 MiniCPM 适配器
│   └── vqaeval/                   # TextVQA/DocVQA 类评测
├── docs/                           # 各版本模型、部署、API、训练说明
├── assets/                         # 图片、视频、音频、模型示例素材
├── requirements.txt                # 旧/通用 Python 依赖锁定集
├── requirements_o2.6.txt           # MiniCPM-o 2.6/实时 Demo 依赖
└── README.md / README_zh.md         # 当前系列总入口
```

仓库现场盘点（不含 `.git`）：本地工作树约 396 个文件、118 个 Python 文件；没有独立 `tests/` 或 `test_*.py` 单元测试树。评测脚本、数据集脚本和 Demo 是验证入口，不等同于自动化单元测试。

## 4. 核心模型与数据模型

### 4.1 本地 OmniLMM 模型图

`omnilmm/model/omnilmm.py` 注册 `OmniLMMConfig`（`model_type = "omnilmm"`）和 `OmniLMMForCausalLM`。其实际结构为：

1. `OmniLMMModel(MistralModel)` 持有语言模型 embedding、`vision_tower` 与 `resampler`。
2. `create_vision_module()` 用 `timm.create_model('eva02_enormous_patch14_clip_224.laion2b_plus', ...)` 创建 EVA02 视觉塔，并取倒数第二层特征。
3. `Resampler` 用固定可学习 query 对视觉 token 做 cross-attention，输出 `grid_size**2` 个 `embed_dim` token。
4. `forward()` 将 `<im_start>`/`<im_patch>`/`<im_end>` 区间替换为视觉特征；纯文本样本通过零值 dummy feature 保持图结构可导。
5. `OmniLMMForCausalLM.forward()` 调父模型得到 hidden states，经 `lm_head` 得到 logits；有 `labels` 时计算 `CrossEntropyLoss`。
6. `generate_vllm()` 可先计算 `vision_hidden_states`，再把视觉状态与文本 embedding 送入通用 `generate()`；支持返回视觉 hidden states 以供缓存/复用。

源码证据：`omnilmm/model/omnilmm.py::create_vision_module`、`OmniLMMModel.forward`、`OmniLMMForCausalLM.forward`、`generate_vllm`、`initialize_vision_tokenizer`；`omnilmm/model/resampler.py::Resampler.forward`。

### 4.2 会话对象

`omnilmm/conversation.py::Conversation` 是 `dataclasses.dataclass`，字段包括 `system`、`roles`、`messages`、`offset`、`sep_style`、`sep`、`sep2`、`version`、`skip_next`。它负责：

- `get_prompt()`：按 `SeparatorStyle.SINGLE/TWO` 拼接系统提示词和角色消息。
- `append_message()`：追加 `[role, message]`。
- `get_images()`：读取消息 tuple 中的 PIL 图片，支持 `Pad`、`Resize` 等处理并可返回 PIL 或 JPEG Base64。
- `to_gradio_chatbot()`：把图片转为 data URL HTML，映射为 Gradio 对话格式。
- `copy()`/`dict()`：会话复制和序列化；图片消息序列化时只保留文本部分。

### 4.3 训练样本、占位符与批数据

`finetune/readme.md` 规定每条 JSON 样本至少包含 `id`、`image`（单路径或占位符到路径的字典）和 `conversations`。消息使用 `role=user/assistant` 与 `content`；单图使用 `<image>`，多图使用 `<image_00>`、`<image_01>` 等。

`finetune/dataset.py` 的真实数据流：

- `SupervisedDataset.__getitem__()` 打开单图/多图，调用 `preprocess()`。
- `preprocess()` 深拷贝会话，依据 `llm_type` 选择 `minicpm`、`llama3`、`qwen` token 方案；根据 `slice_config` 调 `slice_image()`，生成源图、patch、网格和图像占位符。
- `conversation_to_ids()` 生成 `input_ids`、`context`、`target`、`image_bound`、`position_ids`；assistant 内容作为 loss 目标，用户和角色控制 token 被屏蔽为 `-100`，并检查 `<im_start>`/`<im_end>` 配对。
- `batch_vision=True` 时将图像重排为 patch 序列并产生 `tgt_sizes`；否则保留变换后的图像列表。
- `data_collator()` 截断并 padding `input_ids`、`position_ids`、`labels`、`attention_mask`，同时保留 `image_bound`、`tgt_sizes`、`pixel_values` 列表。

`slice_image()` 先按面积、宽高比和 `max_slice_nums` 选择网格，再用 `find_best_resize()` 保证尺寸对齐 `patch_size`，最后 `split_to_patches()` 裁成图块。高分辨率图像因此以源图+网格 patch 的形式注入文本序列，而不是被简单压成一张固定尺寸图片。

## 5. 推理、API、CLI 与适配边界

### 5.1 Transformers chat 入口

当前推荐入口由 README 和 `docs/api.md` 给出：

```python
from transformers import AutoModelForImageTextToText, AutoProcessor
processor = AutoProcessor.from_pretrained("openbmb/MiniCPM-V-4.6")
model = AutoModelForImageTextToText.from_pretrained(
    "openbmb/MiniCPM-V-4.6", torch_dtype="auto", device_map="auto"
)
inputs = processor.apply_chat_template(
    messages, tokenize=True, add_generation_prompt=True,
    return_dict=True, return_tensors="pt", downsample_mode="16x"
).to(model.device)
generated_ids = model.generate(**inputs, downsample_mode="16x", max_new_tokens=512)
```

README 明确要求 `downsample_mode` 同时传给 `apply_chat_template()` 和 `generate()`；图像常用 `max_slice_nums=36`，视频常用 `max_num_frames=128`、`max_slice_nums=1`、`use_image_id=False`。这段 v4.6 代码属于 Transformers/模型仓库提供的运行时契约，不是本仓库内的模型类实现。

旧系列和评测适配器使用 `model.chat(image=..., msgs=..., context=..., tokenizer=..., **kwargs)`；返回值因版本而异，旧 MiniCPM-V 常见为 `(answer, context, ...)`，适配器会取首项。`chat.py` 将外部输入统一成 `{"image": Base64, "question": JSON messages}`，再按模型路径选择 `OmniLMM12B`、`MiniCPMV2_5`、`MiniCPMV2_6` 或 `MiniCPMV`。

### 5.2 本地 `chat.py` CLI/SDK 形态

`chat.py` 没有独立 argparse CLI；它是可导入的 Python 封装，同时在 `__main__` 中以 `openbmb/OmniLMM-12B` 和 `assets/worldmap_ck.jpg` 做双轮对话示例。公开类/方法包括：

- `init_omni_lmm(model_path)`：加载 `OmniLMMForCausalLM`、tokenizer、图像 transform，并注册视觉特殊 token。
- `OmniLMM12B.chat(input)`：Base64 图像解码、`wrap_question_for_omni_lmm()`、`generate_vllm()`。
- `MiniCPMV.chat(input)`：调用外部模型 `model.chat()`，使用 `torch.bfloat16`。
- `MiniCPMV2_5.chat(input)`：调用外部模型 `model.chat()`，使用 `torch.float16`。
- `MiniCPMV2_6.chat(input)`：支持普通 CUDA 和 `accelerate.infer_auto_device_map` 多 GPU，输入消息支持文本和图像。
- `MiniCPMVChat.chat(input)`：按模型路径分派。

### 5.3 实时 MiniCPM-o 2.6 HTTP/WebSocket

`web_demos/minicpm-o_2.6/model_server.py` 在模块导入时构造全局 `StreamManager`，默认模型 `openbmb/MiniCPM-o-2_6`、默认端口 `32550`，可用 `--port`、`--model` 覆盖。主要状态包括 `uid`、`session_id`、音视频输入缓冲、`customized_options`、活动时间、生成停止标志以及落盘日志目录。

路由（每项另有 `/api/v1/` 前缀别名）：

| 路由 | 方式 | 作用 |
|---|---|---|
| `/stream` | POST | 接收带 `messages` 的流式输入，要求 `uid` Header |
| `/ws/stream` | WebSocket | JSON 文本流输入，`uid` Query 参数 |
| `/completions` | POST | 启动 SSE `StreamingResponse`，消费 `streaming_generate()` |
| `/stop` | POST | 设置 `stop_response`，终止当前生成 |
| `/feedback` | POST | 写入 `feedback_log/<response_id>.<rating>`，rating 为 `like/dislike` |
| `/init_options` | POST | 接收 `input_audio`/`options`，配置音频克隆/助手选项 |
| `/health` | GET | 返回 `{"status": "OK"}` |

`StreamManager.process_message()` 将输入音频用 `librosa` 解码为 16 kHz，图片和音频组合成消息后调用 `streaming_prefill()`；`generate()` 合并 WAV、逐块调用 `streaming_generate(generate_audio=True)`，把音频写为 WAV 并通过 SSE 返回 Base64 音频与文本。后台 `check_activity()` 每秒检查 900 秒请求超时和 3 秒无流活动。该服务是单个全局 `StreamManager`，不是多租户/多模型并发服务；UID 变化会重置或拒绝请求。

### 5.4 评测入口

`eval_mm/vlmevalkit/vlmeval/config.py` 将 `MiniCPM_V`、`MiniCPM_Llama3_V`、`MiniCPM_V_2_6`、`MiniCPM_o_2_6` 注册到 `supported_VLM`。`run.py` 根据 `--data`、`--model` 或配置 JSON 创建模型和数据集，进入 `infer_data_job`、`infer_data_job_video` 或 `infer_data_job_mt`，再输出 benchmark 结果。`vlmeval/vlm/minicpm_v.py` 负责模型加载、数据集 prompt、图片消息构造和 `model.chat()` 调用；`vqaeval/models/MiniCPM/minicpmv.py` 负责 TextVQA/DocVQA 风格单图与交错图文生成。

评测 shell 入口 `eval_mm/vlmevalkit/scripts/run_inference.sh` 以 `MODELNAME`、`DATALIST` 为参数，默认示例使用 `torchrun --nproc_per_node=8`，随后以 `python run.py` 评估。`eval_mm/vqaeval/shell/run_inference.sh`/`run_transform.sh` 面向 VQA 数据下载、推理和 DocVQATest 格式转换。

## 6. 技术栈与依赖边界

| 层 | 真实依赖/作用 |
|---|---|
| 张量与视觉 | `torch==2.1.2`、`torchvision==0.16.2`、`timm==0.9.10`、`Pillow`、`numpy`、`opencv_python_headless` |
| Transformers 运行时 | `transformers==4.40.0`（通用依赖；新版 README 另要求 `transformers[torch]>=5.7.0`）、`accelerate`、`sentencepiece` |
| 视频/音频 | `decord`；MiniCPM-o 路径的 `torchaudio`、`librosa`、`soundfile`、`moviepy`；新版文档可选 `torchcodec`/`PyAV` |
| Demo 服务 | `gradio`、`streamlit`；o2.6 服务器使用 `fastapi`、`uvicorn`、`aiofiles`、`onnxruntime` |
| 训练 | `transformers.Trainer`、`deepspeed`、`peft`、`accelerate`、DeepSpeed ZeRO-2/3 配置 |
| 评测 | `vlmevalkit` 自带框架、`vqaeval`、`jsonlines`、`openpyxl`、`sacrebleu` 等 |
| 外部模型/服务 | Hugging Face `openbmb/*` 权重与 `trust_remote_code`；README/API 还记录 Modelbest OpenAI-compatible API `https://api.modelbest.cn/v1` |

依赖边界有明显版本分层：根 `requirements.txt` 是较早 MiniCPM-V/评测环境；`requirements_o2.6.txt` 是实时全模态 Demo；`finetune/requirements.txt`、`eval_mm/*/requirements.txt` 又各自追加/锁定依赖。不能把这些文件理解成一份可无条件合并安装的单一环境。

## 7. 测试、验证与未执行事项

- 现场未发现独立单元测试目录或 `test_*.py` 测试套件；项目验证主要由评测脚本、Demo 手工运行、README 示例和模型服务接口组成。
- 本轮只做源码、README、依赖、入口、API、评测/训练脚本和远程版本的只读核对；未安装依赖、未下载权重、未启动 CUDA/HTTP/WebSocket/Demo、未运行 benchmark、未启动训练或构建前端。
- 可执行验证入口（仅记录，不代表本轮已执行）：`python chat.py`、`python web_demos/web_demo_2.6.py --device cuda|mps`、`python web_demos/minicpm-o_2.6/model_server.py --port 32550`、`python eval_mm/vlmevalkit/run.py --data <DATASET> --model <MODEL>`、`torchrun ... finetune/finetune.py`。
- 运行前置条件包括匹配的 PyTorch/CUDA 或 Apple MPS 环境、模型权重、视频/音频编解码依赖、评测数据集；这些条件在当前 macOS 工作树中未作可用性假设。

## 8. 版本基线与远程复核

- 本地工作树分支：`main`。
- 本地 HEAD：`a3f312907152d4a2aa2d4560648d43050d7daab1`，提交时间 `2026-07-23T16:44:30+08:00`，主题 `update api key & add video describe case`。
- 远程 `origin`：`https://github.com/OpenBMB/MiniCPM-V.git`。
- 远程 `origin/main` 现场查询：`8e7209ccf1ce28d94a9fd841a673b3b9d6caae72`，独立快照时间 `2026-08-12T22:16:54+08:00`，主题 `update readme, add MiniCPM Wiki link`。
- 远程版本晚于本地版本，因此未在工作树上 `pull` 或覆盖任何内容；已通过本机代理 `127.0.0.1:4780` 建立只读独立快照 `/tmp/MiniCPM-V-latest` 进行 README/API/目录和关键源码复核。远程与本地关键运行文件 `docs/api.md`、`requirements*.txt`、`omnilmm/model/omnilmm.py`、`web_demos/minicpm-o_2.6/model_server.py` 内容一致；远程主要新增/更新 README 与资料。
- `细探-MiniCPM-V.md` 已逐条与源码核对并吸收进本文件；后续只维护本 `ARCHITECTURE.md`，旧细探不再作为独立事实源。

## 9. 风险、未确认项与后续复核点

1. **README 与源码版本错位**：README 已描述 4.6/4.5，而本仓库自有 `omnilmm/`、`chat.py` 和多数 Demo 仍是旧版本/旧协议；4.6 的 `AutoModelForImageTextToText`、`AutoProcessor` 契约需要以对应 Hugging Face 模型仓库和 Transformers 版本进一步复核。
2. **`trust_remote_code=True` 是外部代码边界**：实际 `model.chat`、视觉处理器、模型配置和生成返回值来自模型权重仓库，不应仅凭本地适配器推断全部实现。
3. **实时服务全局状态**：`model_server.py` 在模块级构造单一 `StreamManager`，输入音频、会话、UID、日志目录和模型均为共享状态；并发、多用户隔离、异常后清理未由自动化测试证明。
4. **依赖环境分裂**：根依赖锁定的 `transformers==4.40.0` 与 README 4.6 推荐的 `transformers>=5.7.0` 不是同一验证基线；CUDA、`torchcodec`、`decord`、`flash_attention_2` 的组合兼容性需按目标设备单独锁定。
5. **训练数据异常恢复**：`SupervisedDataset.__getitem__()` 捕获所有异常后随机递归取样，坏样本可能被掩盖，并可能在数据普遍损坏时递归耗尽；未有测试覆盖。
6. **API 文档凭证处理**：`docs/api.md` 的凭证已由读取层脱敏；实际调用不得把 API key 写入源码、日志或架构文档。
7. **旧代码路径可维护性**：`omnilmm/model/omnilmm.py` 含硬编码视觉权重路径 `/tt/data/public/...` 的初始化分支；该分支是否仍是支持路径、如何提供 EVA02 权重尚未在本机验证。
8. **评测依赖数据外置**：`vlmevalkit`/`vqaeval` 需要外部 benchmark 数据、GPU、多进程和可能的 GPT 评审服务；本轮没有把“脚本存在”误记为“评测通过”。

## 10. 证据路径

- 定位与总览：`README.md`、`README_zh.md`、`docs/api.md`
- 本地模型实现：`omnilmm/model/omnilmm.py`、`omnilmm/model/resampler.py`、`omnilmm/model/utils.py`、`omnilmm/conversation.py`
- 旧推理封装：`chat.py`
- 训练与数据模型：`finetune/finetune.py`、`finetune/dataset.py`、`finetune/trainer.py`、`finetune/readme.md`
- 实时服务：`web_demos/minicpm-o_2.6/model_server.py`、`web_demos/minicpm-o_2.6/chatbot_web_demo_o2.6.py`
- 评测：`eval_mm/vlmevalkit/run.py`、`eval_mm/vlmevalkit/vlmeval/config.py`、`eval_mm/vlmevalkit/vlmeval/vlm/minicpm_v.py`、`eval_mm/vqaeval/models/MiniCPM/minicpmv.py`
- 依赖：`requirements.txt`、`requirements_o2.6.txt`、`finetune/requirements.txt`、`eval_mm/vlmevalkit/requirements.txt`、`eval_mm/vqaeval/requirements.txt`
- 此前细探材料（已人工吸收并清理）
- 远程只读复核快照：`/tmp/MiniCPM-V-latest`，基线 `8e7209ccf1ce28d94a9fd841a673b3b9d6caae72`

## 11. 第三轮：通用底座映射与裁决（2026-08-21）

本节是第二轮项目事实之后的底座输入，不是对 MiniCPM-V 生产化改造的承诺。它只把源码中已经存在的视觉输入、处理器、模型推理、权重/量化、设备、批处理和入口映射到平台的四类职责：**图像/多模态支持库、模型模块、提供者、运行核心**。平台若要吸收，必须按本节的单链路和验收契约重新实现；不能把 `trust_remote_code=True`、Demo 全局变量或模型对象直接搬进平台核心。

### 11.1 证据边界与归图总图

```text
外部图像/视频/音频/文本请求
  → 图像/多模态支持库：格式解码、尺寸/帧/音频采样、消息结构校验、Processor/Tokenizer适配
  → 模型模块：模型族选择、视觉 token/hidden state 注入、chat/generate/streaming 编排
  → 提供者：Hugging Face 权重与 remote code、PyTorch/timm/Transformers、Pillow/decord/PyAV/torchcodec、CUDA/MPS/CPU、Modelbest API
  → 运行核心：预算、队列、并发租约、超时、取消、进程/显存隔离、崩溃回收、统一结果和证据
  → 服务/CLI/评测适配器：HTTP/SSE/WebSocket、transformers serve、评测 worker、训练 launcher
```

归图的关键判断：

- **图像/多模态支持库**应拥有“输入是什么、如何变成受控的视觉/音频张量”的职责。源码中的 `PIL.Image.open().convert("RGB")`、`slice_image()`、`find_best_resize()`、`split_to_patches()`、`decord.VideoReader`、`librosa.load()`、`soundfile`、新版 `AutoProcessor.apply_chat_template()` 都属于这一边界；不同第三方解码器是提供者，不应让每个模型模块重复实现格式和上限检查。
- **模型模块**应拥有模型族差异：视觉塔/Resampler/LLM 组合、图像占位符与 token 对齐、`model.chat()`/`model.generate()` 参数、版本返回值归一化、视频与全模态的模型专用提示策略。`omnilmm/model/omnilmm.py` 是仓库内模型模块的真实例子；4.6/4.5 主体在 Hugging Face remote code 中，仓库本地只有适配边界。
- **提供者**应拥有外部重量、第三方运行库、硬件后端和外部 API。权重下载/缓存、`trust_remote_code`、CUDA/MPS/CPU、`decord`/`torchcodec`/`PyAV`、`Modelbest`、vLLM/SGLang/llama.cpp/Ollama 都不能成为运行核心的内嵌实现。
- **运行核心**应拥有可观测和可回收的执行生命周期。现有仓库没有统一预算、租约、取消、OOM 恢复、崩溃隔离或结果证据层；`StreamManager`、`torch.cuda.empty_cache()`、评测循环中的临时文件和 `uid` 判断均不足以替代它。
- **证据分层**：本仓库源码是“本地实现”证据；README/API 中的 4.5/4.6、GGUF/BNB/AWQ/GPTQ、`transformers serve` 和外部模型服务是“声明/外部契约”证据，除非本地有实现或本轮实跑，否则只能记为待核。

### 11.2 七类能力的单链路映射

| 能力 | 本仓库真实事实 | 归图像/多模态支持库 | 归模型模块 | 归提供者 | 归运行核心 |
|---|---|---|---|---|---|
| 视觉输入 | `chat.py` 接收 Base64；`SupervisedDataset` 从路径打开单图/多图；旧 Demo 用 `PIL` 和 `decord` 抽帧；o2.6 还接收音频和图片 | Base64/路径/URL/媒体类型校验；RGB 解码；像素、帧数、尺寸、采样率上限；统一 `消息内容` | 只消费规范化图片/帧/音频，不再解析各式 Base64 | Pillow、decord、PyAV/torchcodec、librosa/soundfile、VAD | 输入大小预算、临时文件、取消时清理、错误码/证据 |
| Processor | 4.6 README 用 `AutoProcessor.apply_chat_template(... return_dict=True)`；旧路径用 `build_transform`、tokenizer 和手工 `<im_start>/<im_patch>/<im_end>` | Processor 适配器、模板参数、视觉 token 预算、返回张量设备迁移 | 模型模块声明所需 Processor 版本、模板/占位符契约 | Transformers `AutoProcessor`/`AutoTokenizer` 和 remote code | Processor 初始化缓存、版本/环境指纹、调用超时与失败回收 |
| 模型推理 | 旧 OmniLMM 是 EVA02→Resampler→Mistral；`OmniLMMForCausalLM.forward/generate_vllm` 注入视觉 embedding；旧/评测适配器调用 `model.chat`; 4.6 示例调用 `generate`；o2.6 调 streaming prefill/generate | 不拥有生成逻辑，只做输入、输出和流事件结构 | 模型族路由、chat/generate、视觉注入、结果归一化、模型专用限制 | PyTorch、Transformers、timm、remote code、可选 vLLM/SGLang/llama.cpp/Ollama | 单任务提交、KV/显存租约、停止、超时、OOM/崩溃隔离、结果落证 |
| 量化/权重 | 本地代码实际使用 `torch_dtype=bfloat16/float16`、`from_pretrained`、Accelerate checkpoint dispatch；训练含 `q_lora`/`prepare_model_for_kbit_training`；README 声明 int4/GGUF/BNB/AWQ/GPTQ | 只记录权重元数据、精度和输入输出契约 | 模型模块声明允许的权重格式和精度组合 | HF Hub/本地 checkpoint、Accelerate、bitsandbytes/llama.cpp 等外部后端（本地未逐一实现） | 权重缓存配额、校验、加载失败释放、版本和摘要；禁止静默 fallback |
| GPU/CPU | 默认旧推理 `.cuda()`；o2.6 服务固定 `cuda:0`；2.6 多 GPU `infer_auto_device_map` 并设每卡 `10GB`；训练 DeepSpeed 可把 optimizer/参数 offload 到 CPU；README 另称 CPU/Mobile、MPS、端侧支持 | 设备无关的张量/媒体契约；不直接选择设备 | 模型模块声明设备能力、不可拆分模块、精度约束 | CUDA/MPS/CPU、Accelerate、DeepSpeed、端侧运行时 | 设备探测、资源租约、显存/内存预算、设备失败降级或拒绝；禁止把 CUDA 假设带入核心 |
| 批处理 | 训练 `data_collator` padding/truncate 文本但保留 `pixel_values` 列表；评测逐条推理，API worker 默认 `api_nproc=4`；`torchrun` 示例 8 进程；README 的 `continuous-batching` 是外部服务能力 | 可批量整理媒体和输入边界，但不负责无限队列 | 模型模块声明是否支持 batch、交错图像、视频帧和 KV 复用 | Transformers serving/vLLM/SGLang 等批处理后端 | 有界队列、背压、公平性、批次取消、单项失败隔离、总预算和结果顺序 |
| 服务/CLI 入口 | `chat.py` 是可导入封装+`__main__` 示例，不是 argparse CLI；o2.6 `model_server.py` 是 FastAPI/SSE/WebSocket，模块导入时构造全局模型；Streamlit/Gradio 是交互 Demo；评测/训练有 shell、`run.py`、`torchrun` | 统一请求/响应/流事件与媒体上传契约 | 暴露模型能力门面，不直接持有端口、全局会话和文件日志 | FastAPI/uvicorn/Streamlit/Gradio、HF `transformers serve`、外部 Modelbest API | 认证、限流、端口/进程组、生命周期、取消断开、日志脱敏、健康检查和优雅停止 |

### 11.3 真实调用链与职责落点

#### A. 图像/视频离线推理链

```text
路径/Base64/URL
  → PIL/decord/Processor 提供者
  → 规范化消息（text + image/video frames）
  → 模型模块的 Processor/Tokenizer 适配
  → image/video 参数（max_slice_nums、max_num_frames、stack_frames、use_image_id）
  → remote-code `model.chat()` 或 `model.generate()`
  → output token 截断
  → Processor `batch_decode()`/模型返回值归一化
  → 运行核心统一结果（成功/输入非法/提供者不可用/超时/OOM/崩溃）
```

证据：4.6 README `README_zh.md:194-243,246-279,281-293`；旧版 `eval_mm/vlmevalkit/vlmeval/vlm/minicpm_v.py:67-91,419-473,670-727`；旧本地视觉链 `omnilmm/model/omnilmm.py:108-121,184-267,372-397`。

#### B. 训练链

```text
JSON 数据集
  → `SupervisedDataset.__getitem__`
  → PIL 多图 + `preprocess`/`slice_image`
  → `conversation_to_ids`（input_ids/labels/image_bound/position_ids）
  → `data_collator`（文本 padding；视觉列表保留）
  → `CPMTrainer.compute_loss`
  → AutoModel.forward / CrossEntropyLoss
  → DeepSpeed/LoRA/QLoRA checkpoint
```

证据：`finetune/dataset.py:23-85,88-123,126-197,321-435`；`finetune/trainer.py:12-43,173-212`；`finetune/finetune.py:167-246`。训练的 `except: return self.__getitem__(random.randint(...))` 是隐式重试，不是可审计的失败/隔离策略，应在底座迁移时改为有限重试并保留坏样本证据。

#### C. 实时服务链

```text
HTTP `/stream` 或 WebSocket `/ws/stream`
  → uid/消息结构检查
  → Base64 音频/图片解码 + 16 kHz 音频 + VAD
  → `StreamManager.prefill`
  → remote-code `streaming_prefill(session_id=...)`
  → `/completions` 等待 Event
  → `streaming_generate(generate_audio=True)`
  → WAV 文件 + SSE Base64 音频/文本
  → `/stop` 设置 `stop_response`，finally `generate_end/reset`
```

证据：`web_demos/minicpm-o_2.6/model_server.py:53-100,162-181,312-374,416-480,489-561,562-570,613-841`。这条链可作为“实时全模态模块+提供者”的事实样本，但不能作为运行核心的并发实现：模型、session、缓冲区、日志目录都在一个全局 `StreamManager` 中。

### 11.4 资源预算、隔离与所有权契约

#### 资源预算表

| 资源 | 源码/声明中的当前边界 | 底座应冻结的契约 | 当前证据等级 |
|---|---|---|---|
| 图片视觉 token/分片 | 4.6：`downsample_mode=16x`（可切 `4x`）、图片推荐 `max_slice_nums=36`；旧 2.6 单图 64 token，`slice=9` 近似 `64*(9+1)` token | 每请求最大像素、最大分片、视觉 token 预算；Processor 在生成前拒绝超限而不是等 CUDA OOM | README/外部模型契约，4.6 本地模型实现待核 |
| 视频输入 | 4.6 `max_num_frames=128`、`stack_frames=1`、`max_slice_nums=1`、`use_image_id=False`；旧 Streamlit `MAX_NUM_FRAMES=64`，模型参数 `max_inp_length=4352` | 帧数、采样 FPS、堆叠网格、视频 token 和临时文件总量有界；超限返回可重试/不可重试明确错误 | README + Demo 源码 |
| 文本/输出 | 4.6 图片 `max_new_tokens=512`、视频 `2048`；旧模型 `max_inp_length=8192` 或视频 `2048*10`，旧 OmniLMM 生成 `1024` | 输入 token、输出 token、KV cache 和单请求 wall-clock deadline 分开计量 | README/本地适配器源码 |
| GPU/CPU 内存 | `chat.py` 多 GPU 显式 `max_memory={0:"10GB",1:"10GB"}`；训练报告在 A100 80GiB、batch=1、ZeRO-3+checkpoint/offload 下 LoRA 2/4/8 卡为 14.4/13.6/13.1 GiB，全参为 16.0/15.8/15.63 GiB | 加载峰值、推理峰值、CPU offload、显存碎片、权重缓存和并发份额分别记账；报告数字不能外推到 4.6 或本机 | README + `chat.py`，仅参考预算 |
| 批次/并发 | 训练 batch 由外部参数；评测 `api_nproc=4`，shell 示例 `torchrun --nproc_per_node=8`；实时服务只有一个全局 manager；`transformers serve --continuous-batching` 仅 README | 每 provider 有最大并发、队列长度、单批项数、背压和公平策略；单项失败不能污染整批 | 本地评测/服务源码；continuous batching 待实跑 |
| 文件/日志 | o2.6 按端口和时间创建 `log_data/<port>/<timestamp>`，下建音频/VAD/图片/输出/feedback 目录；视频 Demo 写入 `uploads` | 临时输入、输出音频、反馈、缓存和权重下载目录须带 operation/session owner、大小上限、TTL 和 finally 清理 | 本地源码；无残留审计 |

#### 隔离和所有权

1. **输入隔离**：支持库只接收受控媒体对象或临时文件句柄，拒绝任意路径逃逸、无限 Base64、异常图片尺寸、无界视频帧和无界音频；URL 下载若被支持，下载器必须是独立 provider，并有 scheme/域名/大小/超时白名单。
2. **权重/remote code 隔离**：`AutoModel.from_pretrained(... trust_remote_code=True)` 既加载权重又可能加载模型仓库代码。它是高风险 provider 边界；底座应在独立环境/进程中运行、记录模型 revision 和权重摘要，不允许 remote code 进入运行核心或支持库公共代码。
3. **设备隔离**：模型实例独占声明的 CUDA/MPS/CPU 预算。多 GPU `device_map` 只能由设备 provider 生成并校验，模型模块只声明不可拆分单元；不能在公共入口无条件 `.cuda()`。CPU/MPS/无 CUDA 应返回能力不可用或选定回退，而不是初始化阶段崩溃。
4. **会话隔离**：o2.6 当前以单一 `StreamManager` 保存 `uid`、`session_id`、音频/图片/KV 状态，uid 变化时拒绝或重置；这不是多租户隔离。平台必须为每个 operation/session 使用独立状态、日志根和取消令牌，KV/音频/反馈不能跨用户复用。
5. **批次隔离**：`data_collator` 的 `pixel_values` 是列表，模型侧并非天然等长 batch；批处理器应逐项记录输入索引、资源预算、返回值和失败，禁止用一个 batch 的 `torch.cuda.empty_cache()` 代替释放责任。
6. **进程隔离**：仓库服务和评测脚本没有把 C/CUDA/remote code 放进受监督子进程；底座若接入第三方解码器、量化库或模型服务，应使用独立进程组，超时/取消/崩溃时回收整个进程树，并验证端口、临时目录和句柄不存在残留。

### 11.5 失败、超时、取消、OOM、崩溃矩阵

| 场景 | 源码当前行为 | 底座统一语义/恢复动作 | 判定 |
|---|---|---|---|
| 图片/音频解码失败 | `chat.py` 返回字符串 `Image decode error`；o2.6 包装成 `ValueError("Audio processing error...")`/HTTP 500；异常细节可能进日志 | `INPUT_DECODE_ERROR`，不重试同一字节；脱敏记录媒体摘要和 provider，不返回异常堆栈给调用方 | 本地实现存在，返回契约不统一 |
| 消息/schema 非法 | o2.6 HTTP 400 检查 `uid/messages/role/content`；WebSocket 发 error 后继续；旧 `chat.py` 对 `question` JSON/内容类型校验不完整 | `INVALID_REQUEST`，在进入模型和分配 GPU 前拒绝；WebSocket 单请求失败不污染 session | 部分实现 |
| 权重/依赖/remote code 不可用 | `from_pretrained`/`AutoTokenizer` 初始化异常直接阻断服务；服务模型在模块导入时加载 | `PROVIDER_UNAVAILABLE`，记录 revision/环境/缺失库；不伪造 CPU fallback；仅在能力声明允许时可重试加载 | 本地无统一错误包装 |
| Processor/token 对齐错误 | OmniLMM 对 start/end 数量和位置不匹配抛 `ValueError`；非 start/end 分支 `NotImplementedError`；训练同样抛异常后可能递归换样本 | `INPUT_CONTRACT_ERROR`；不重试同一输入；保留 token/image_bound 摘要，训练坏样本入隔离队列 | 实现有局部检查，训练会掩盖错误 |
| 单请求超时/无流 | o2.6 `timeout=900s`，无流 `stream_timeout=3s`；后台每秒检查，设置 Event 或 reset；SSE 等待循环没有真正 deadline 注入 | 软超时先取消生成、关闭流、释放 batch/KV；硬 deadline kill provider 进程；返回 `TIMEOUT` 并注明是否可重试 | 局部实现，SSE 等待未闭环 |
| 主动取消/断开 | `/stop` 设置 `stop_response`；生成循环检查并 `generate_end/reset`；WebSocket 断开捕获，但共享状态清理不完整 | operation cancel token 贯穿 Processor/provider/stream；finally 回收音频、临时文件、GPU lease 和子进程；取消不算成功 | 局部实现 |
| CUDA OOM/CPU 内存不足 | README 建议减少 `max_slice_nums`/`max_model_length`/`batch_size`；Streamlit 也提示降低帧数；代码没有统一捕获和重试；`empty_cache()` 只释放缓存 | `RESOURCE_EXHAUSTED`，记录预算/峰值/设备；先取消当前请求并回收，再按明确策略降低分辨率/帧数或拒绝；禁止透明改变语义后宣称成功 | 有规避建议，无统一治理 |
| provider/CUDA/解码器崩溃 | 当前服务进程内加载所有库，崩溃可拖垮整个 HTTP 进程；`trust_remote_code` 边界无监督 | provider 子进程非零/信号退出→`PROVIDER_CRASHED`；killpg、回收、健康标记、有限重启和证据；禁止无限重启 | 架构缺口 |
| 生成中途异常/部分流 | o2.6 内层 `streaming_generate` 异常只记录并 yield `\n<end>`；外层错误字符串引用了未定义 `exc`；finally reset | 流协议必须有唯一 terminal event（完成/失败/取消/超时），部分音频标记不可继续；错误不再触发二次异常；结果记录已发 chunk 数 | 本地存在潜在二次异常风险 |
| 训练坏样本/递归耗尽 | `SupervisedDataset.__getitem__` 捕获裸异常并随机递归 `self.__getitem__(random.randint(0,len(self)))`，上界还可能取到 `len(self)`；无最大重试/坏样本账本 | `DATA_ITEM_INVALID` 隔离到坏样本清单，有限重试后终止或按策略跳过；不递归吞掉全量数据损坏 | 明确缺口 |
| 服务优雅停止/重启 | shutdown hook 只写日志；没有显式停止模型 provider、后台 task、文件句柄和 CUDA context | 先拒绝新请求→停止队列→取消 active operation→回收子进程/文件/设备 lease→读回残留→退出 | 未实现/未验证 |

### 11.6 L0-L4 交付分级

| 等级 | 底座必须证明什么 | MiniCPM-V 当前证据 | 第三轮裁决 |
|---|---|---|---|
| **L0 输入与契约** | 媒体格式、大小/帧/像素/Token 上限；文本+视觉消息结构；错误码和返回形状稳定 | README/API、旧 Demo、`chat.py` 有多套输入形状；缺统一 schema、长度和错误码 | **升级图像/多模态支持库**；先统一输入和 Processor 契约，不能直接复用 `chat.py` 字典 |
| **L1 Processor 与模型适配** | Processor/Tokenizer 版本锁定；模板、占位符、视觉 token、`batch_decode` 对齐；4x/16x 等参数不漂移 | 4.6 `AutoProcessor` 是外部 remote code；旧路径手工 transform/token；OmniLMM 对 token 边界有局部校验 | **新建/升级模型模块适配层**，把 remote Processor 留在 provider；必须有版本兼容和契约测试 |
| **L2 单任务推理** | 单请求设备选择、权重加载、视觉编码、LLM generate/chat、结果/资源释放真实闭环 | 本地 OmniLMM 链真实可读；旧适配器实际 `.cuda()`；权重不在仓库，4.6 未本地执行 | **模型模块 + 权重/运行时 provider 隔离**；不把“源码存在”记为推理通过 |
| **L3 批处理与服务运行** | 有界队列/连续批处理、背压、并发租约、SSE/WebSocket terminal event、取消/超时/OOM/断线清理 | 评测逐条循环、API worker=4；o2.6 单全局 manager；`transformers serve --continuous-batching` 仅声明 | **运行核心新建通用执行监督**；服务/评测/训练只能做薄适配，连续批处理待独立 provider 验证 |
| **L4 生产治理** | 权重/环境摘要、权限、租约、指标、失败证据、崩溃隔离、有限重启、回滚、真实验收 | 无独立生产门禁、单元测试、OOM/崩溃/残留审计；外部 API/4.6/量化路径未实跑 | **待核/隔离，不得宣称生产就绪**；以平台运行核心和统一网关验收后才可吸收 |

### 11.7 现有能力命中、缺口与单链路裁决

| 底座能力 | 命中/证据 | 裁决 | 单链路落点 |
|---|---|---|---|
| 图片读取、RGB 规范化、尺寸调整 | `chat.py`、`finetune/dataset.py`、各评测适配器重复出现 | **升级现有图像输入支持库**，吸收边界检查；不复制模型版本实现 | 请求 → 图像支持库公开入口 → 模型模块 |
| 视频解码/抽帧 | `decord` Demo；README 4.6 推荐 `torchcodec`/`PyAV` | **提供者隔离 + 支持库统一契约**；不同 decoder 是策略，不是三套业务流程 | 视频支持库 → decoder provider → 模型模块 |
| Processor/Tokenizer | 4.6 `AutoProcessor`；旧版 tokenizer/手工 token | **新建 Processor 适配原子能力或升级现有支持库**；版本和模板必须由一个契约 owner 管理 | 模型模块 → Processor provider/适配器 |
| 视觉编码与 token 注入 | `OmniLMMModel.get_vision_embedding/forward/get_vllm_embedding` | **升级模型模块**，不能下沉到通用图像库；保留模型族差异 | 模型模块 → 视觉/LLM provider |
| 权重加载/精度/多 GPU | `from_pretrained`、Accelerate map、bf16/fp16、LoRA/QLoRA | **provider 能力**；建立权重摘要、设备预算和格式矩阵，GGUF/BNB/AWQ/GPTQ 先待核 | 模型模块 → 权重/设备 provider |
| 批处理/评测并发 | `data_collator`、`api_nproc=4`、torchrun、外部 continuous batching | **运行核心新建有界执行器**；仅复用数据整理逻辑，不复用全局 manager | 服务/评测 → 运行核心调度 → provider |
| 服务/CLI | FastAPI、Streamlit、Gradio、shell、`__main__` 示例、外部 `transformers serve` | **统一网关/服务适配层**；入口不能各自直连模型和日志 | CLI/HTTP → 统一能力入口 → 模型模块 |
| 失败/超时/取消/OOM/崩溃 | 仅局部 try/stop/reset/empty_cache | **运行核心必须新建统一监督与证据** | 所有 provider 共用一套监督契约 |

### 11.8 依赖、资源和验收契约

底座接入 MiniCPM-V 类能力时，最低公开契约应固定为：

```text
能力id: multimodal.understand
输入:
  messages: 规范化 text/image/video/audio 内容列表
  model_ref: 模型标识 + revision/权重摘要（不得只传展示名）
  processor_ref: Processor/Tokenizer 版本指纹
  limits: max_pixels/max_slices/max_frames/max_input_tokens/max_new_tokens/deadline
  device_policy: auto|cuda|mps|cpu + 可用设备预算
  stream: false|sse|websocket
返回:
  成功: text + 可选 chunks + usage(输入/视觉/输出 token、峰值显存、耗时)
  失败: error_code + retryable + stage + provider + evidence_id
资源责任:
  创建者持有媒体临时文件、Processor、模型请求、KV/stream、GPU lease；
  成功/失败/取消/超时/崩溃都必须释放；provider 崩溃由运行核心回收进程组。
```

验收不是“能 import”或“README 有命令”，而是至少以下闭环：

1. **L0**：单图、多图、视频、文本和非法媒体分别通过统一入口；校验最大像素/切片/帧/输入 token，返回稳定错误码。
2. **L1**：同一 Processor 版本在 `apply_chat_template` 与 `generate` 使用同一 `downsample_mode`；验证 image id、start/end、batch decode 和输出截断一致。
3. **L2**：在明确声明的 CUDA/CPU/MPS/多 GPU provider 上真实加载指定 revision 权重，完成一次单图和一次视频/多图推理；记录实际设备、精度、峰值资源和返回形状。
4. **L3**：真实 HTTP/SSE/WebSocket 或 CLI 入口覆盖并发有界、队列背压、断开、主动取消、单请求超时、单项失败和批次结果顺序；读取回进程、端口、临时文件和 GPU lease 无残留。
5. **L4**：注入缺权重、缺 decoder、非法模板、OOM、provider SIGKILL、模型异常和主进程重启；每个场景有可读 evidence_id、有限重试/回滚和退出码，不以打印日志或“自动重试成功”代替证据。

### 11.9 装配计划与第三轮结论

```text
波次 A：冻结 multimodal 输入/Processor/错误码/资源上限契约
  → 盘点已有图像、文档、音视频支持库，选择唯一能力 owner
波次 B：建立 MiniCPM 模型模块适配器
  → 只依赖支持库公开入口；模型族差异和 remote Processor 留在适配层
波次 C：接入权重/解码器/设备 provider
  → 独立环境与进程；记录 revision、摘要、精度、设备和依赖版本
波次 D：接入运行核心监督
  → 有界队列、预算租约、超时、取消、OOM、崩溃回收、统一结果/证据
波次 E：接入统一 HTTP/CLI/评测入口
  → 入口只调用能力 id；禁止服务脚本直持模型全局状态
波次 F：L0→L4 真实验收与残留审计
  → 单图/视频/批处理/服务/失败注入/重启恢复，未通过项保持待核
```

第三轮裁决：

- **吸收**：`slice_image` 的“尺寸—分片—占位符”思想、Processor/Tokenizer 参数契约、模型模块的视觉 hidden state 注入边界、评测结果逐条持久化模式，可作为候选设计输入；吸收的是契约和证据，不是复制源码。
- **升级**：现有图像/视频/音频输入支持库需加入统一媒体 schema、上限、解码错误、临时文件和 provider 选择；模型模块需统一 chat/generate 返回形状和版本兼容。
- **新建**：运行核心的预算租约、批处理/背压、取消/超时、OOM 处置、provider 进程隔离、崩溃回收和证据账本；仓库没有可直接复用的统一实现。
- **隔离**：Hugging Face `trust_remote_code`、权重缓存、CUDA/C 扩展解码器、量化后端、Modelbest API、FastAPI 全局实时 Demo；它们是 provider/服务适配边界，不能进入公共核心。
- **废弃/禁止复用**：o2.6 单全局 `StreamManager` 作为多租户运行核心、`chat.py` 的版本分派字典作为统一注册表、裸 `except` 随机递归取样、`torch.cuda.empty_cache()` 作为 OOM 治理、仅 `stop_response` 布尔值作为跨层取消协议。
- **待核**：4.6/4.5 remote code 的真实 Processor/模型返回、GGUF/BNB/AWQ/GPTQ 各格式的加载路径、Transformers continuous batching、vLLM/SGLang/端侧 CPU/MPS 实测资源、量化精度与多模态视觉塔兼容性。

本节完成“现有能力命中表、缺口表、单链路落点、复用/升级/新建/隔离裁决、资源/失败契约、验收契约和装配计划”。它没有改变仓库源码事实，也没有把外部 README 声明提升为已验证实现。
