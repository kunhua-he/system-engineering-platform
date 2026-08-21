# Ella 架构建档

> 初始全量静态建档，并在本节末追加后续源码收口。依据仓库当前工作树中的 README、依赖声明、核心入口、记忆实现、ViCo 子模块、评估脚本、测试与既有细探文件整理。
>
> 目标仓库：`~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/03_记忆研究与算法/Ella`
>
> 结论边界：本文是源码事实地图，不把论文描述、README 安装步骤或脚本命名当作已运行证明。当前核对未安装依赖、未构建 C++/Python 包、未启动模拟器或模型服务、未运行测试、未提交 Git。

## 1. 项目定位

Ella 是论文《Ella: Embodied Lifelong Learning Agents with Non-Parametric Memory》的具身社交 Agent 研究实现。它将 LLM 驱动的行为决策、视觉/空间感知、虚拟社区（Virtual Community，目录内以 `vico/` 子模块存在）和磁盘上的非参数记忆组合起来，在城市/室内场景中运行多 Agent 长时模拟，并通过 Controlled Finals 和诊断脚本评估行为与记忆识别。

项目不是一个独立 Web 服务，也没有发现面向外部消费者的稳定 REST/OpenAPI/CLI 包装层。可观察的接口主要是：

- Python 类与函数：`EllaAgent`、`SemanticMemory`、`EpisodicMemory`、`VicoEnv`、`Builder`、`ModelManager`。
- 实验 CLI：`odm.py`、`ControlledFinals/InfluenceBattle.py`、`ControlledFinals/LeadershipQuest.py`、诊断脚本和 `scripts/**/*.sh`。
- 内部模型 RPC：`tools/model_manager/server.py` 提供基于 HTTP POST + pickle 的本地模型服务协议；它是进程间实现细节，不是安全的公共 API。

## 2. 总体文本流程图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 实验/诊断入口                                                               │
│ odm.py | ControlledFinals/*.py | diagnose_*.py | scripts/**/*.sh             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ argparse 参数 + 场景/Agent 配置
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 实验编排层                                                                   │
│ 创建 output/<scene>_<config>/<agent_type>/curr_sim                           │
│ 初始化 global_model_manager → VicoEnv → AgentProcess × N                    │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ reset()/step()：obs → action → obs
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Virtual Community / ViCo 环境层                                              │
│ Genesis Scene + 城市/建筑/室内资产 + Avatar/Robot + TrafficManager           │
│ EventSystem(R-tree) + 摄像机 RGB-D/segmentation + 时间/地点/交通状态          │
└──────────────┬───────────────────────────────┬──────────────────────────────┘
               │ observation                    │ action dict
               ▼                                ▲
┌─────────────────────────────┐       ┌────────────────────────────────────────┐
│ EllaAgent / GenAgent        │       │ Agent 基类 / AgentProcess                │
│ 感知→记忆→反应/计划→动作     │──────▶│ 单进程或 multiprocessing.Queue；记录 step JSON │
│ 对话、通勤、探索、拾取、导航  │       └────────────────────────────────────────┘
└──────────────┬──────────────┘
               │
               ├──────────────────────────────────────────────────────────────┐
               ▼                                                              │
┌────────────────────────────────────────┐                                    │
│ SemanticMemory                          │                                    │
│ knowledge.json + knowledge_feature.pkl  │                                    │
│ ObjectBuilder + scene graph + voxel grid│                                    │
└──────────────────┬─────────────────────┘                                    │
                   │ RGB-D / 标签 / 几何 / CLIP 特征                          │
                   ▼                                                              │
      RAM+ → GroundingDINO → EfficientSAM → CLIP → Object/Region/VolumeGrid

               ├──────────────────────────────────────────────────────────────┐
               ▼                                                              │
┌────────────────────────────────────────┐                                    │
│ EpisodicMemory                          │                                    │
│ experience.json + FAISS text/image index│                                    │
│ EventInstance：时间/位置/地点/关键词/描述  │                                    │
└──────────────────┬─────────────────────┘                                    │
                   │ query + image + recency/proximity                          │
                   ▼                                                              │
               retrieve → prompt context → LLM Generator                        │
                                                                              │
┌─────────────────────────────────────────────────────────────────────────────┐│
│ ModelManager / ModelProcess / ProcessChannel / HTTP ModelServer              │◀┘
│ RAM、DINO、SAM、CLIP、embedding、completion；本地多进程队列或 HTTP pickle RPC  │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ provider adapter
                                ▼
                   OpenAI / Azure OpenAI / HuggingFace / local vLLM 等

模拟输出：curr_sim 配置与记忆、steps/<agent>/*.json、RGB/深度/分割/日志
                                │
                                ▼
ControlledFinals/evaluate.py → Influence Battle / Leadership Quest 指标
              + diagnose_all.py / diagnose_agent_recognition.py → 识别与诊断报告
```

## 3. 分层架构

### 3.1 入口与实验编排层

- `odm.py` 是 Ella 主实验入口。README 明确指出主实现为 `agents/ella.py`（`README.md:29-46`）。
- `ControlledFinals/InfluenceBattle.py` 和 `ControlledFinals/LeadershipQuest.py` 复用同一套参数、场景初始化和仿真循环，但在启动前注入挑战专用配置与 Agent 日常要求。
- `diagnose_all.py`、`diagnose_agent_recognition.py` 创建小范围/全量识别诊断场景，保存 RGB、深度、相机元数据和 JSON 结果。
- `scripts/ODM`、`scripts/IB`、`scripts/LQ` 是参数模板，实质调用 Python 入口，不是独立业务实现。
- 各入口会创建或续跑 `output/.../curr_sim`，并通过 `config.json`、每个 Agent 的 `scratch.json`、`seed_knowledge.json` 恢复状态。

### 3.2 Agent 编排与决策层

- `vico/vico/agents/agent.py` 的 `Agent` 负责公共状态、观察输入、`act()` 生命周期和 `scratch.json` 持久化；`AgentProcess` 提供单进程/多进程两种执行方式、观察队列、动作队列、对话队列以及 step 日志。
- `agents/__init__.py:get_agent_cls()` 将包含 `ella` 的类型映射到 `EllaAgent`，将 `generative_agent` 映射到 `GenAgent`，否则回退 ViCo 内置 Agent 工厂。
- `EllaAgent`（`agents/ella.py`）继承 ViCo `Agent`，维护小时计划、通勤计划、聊天缓冲、反应频率、室内活动和 LLM Generator。其主要循环是 `_process_obs()` → `_act()`。
- `_process_obs()`：处理新一天、动作失败、RGB-D 感知、语音事件和对象检测结果，并向情景记忆写入观察/事件。
- `_act()`：优先处理对话和记忆触发的反应，再处理计划调整、环境交互、通勤/导航、室内动作；最终回退到 `wait`。
- `GenAgent` 是另一条 Generative Agents 风格实现，使用 `gen_agent_memory.py`，提供焦点、洞察/证据、反思、日计划与情景检索逻辑；它和 Ella 的记忆实现不是同一份代码。

### 3.3 记忆与空间理解层

#### 语义记忆

`agents/memory.py:24-310` 的 `SemanticMemory` 以文件目录为对象数据库：

- 主事实：`knowledge.json`，键为地点、Agent 或检测对象名称，值包含位置、建筑、类型、边界框、对象索引等字段。
- 特征：`knowledge_feature.pkl`，用于 Agent 视觉特征和名称的相似度匹配。
- 场所索引：`places`、`transit_places`、`agents`。
- 场景图：每个地点一个 `Builder`，内部包含 `VolumeGridBuilder`；场景切换时保存旧地点的体素网格。
- 检测开关：`detect_interval != -1` 时创建 `ObjectBuilder`；`region_layer` 进一步创建 `RegionBuilder`。
- 更新路径：RGB-D → ObjectBuilder 得到标签/新对象 → 场景图加入帧 → 新对象与已有知识按 CLIP 相似度匹配；未匹配对象以 `<tag>_<idx>` 创建新知识。
- 持久化：异步线程使用 `atomic_save()` 写 JSON、pickle、对象库、体素网格和区域 JSON。

#### 视觉对象管线

`agents/sg/README.md:28-46` 和 `agents/sg/builder/object.py:128-341` 定义了主链：

1. RAM+ (`RAMWrapper`) 从 RGB 生成可见对象标签。
2. GroundingDINO (`DINOWrapper`) 按标签生成边界框。
3. EfficientSAM (`SAMWrapper`) 按框生成实例 mask。
4. CLIP (`CLIPWrapper`) 对裁剪对象提取视觉特征。
5. `ObjectBuilder` 将 mask + depth + camera extrinsics 反投影为点云，构建对象体素网格，并用视觉/空间相似度合并对象。

如果启用 GT segmentation，`add_frame_with_gt_seg()` 直接使用环境提供的分割和实体元信息，跳过运行时的开放词汇检测主链。

#### 情景记忆

`agents/memory.py:324-605` 的 `EpisodicMemory`：

- `EventInstance` 字段包括 `event_id`、`event_type`、事件时间、最后访问时间、位置、地点、关键词、图片路径、描述、重要性和过期时间。
- 事实文件：`experience.json`；文本检索使用 FAISS `IndexFlatIP`，图像检索使用 512 维 FAISS 索引。
- 新事件在 `add_memory()` 中生成文本 embedding，图片存在时生成 CLIP embedding，然后追加到内存列表、关键词倒排和 FAISS 索引并整体保存。
- `retrieve()` 将 recency、文本/图像相关性和空间 proximity 混合排序；默认权重由调用方传入。
- 另有按最近时间、精确时间、地点、关键词检索和失败动作标记逻辑。
- `retrieve_knowledge()` 当前为 `pass`，不是已完成的通用语义检索接口。

### 3.4 ViCo 环境与物理仿真层

`vico/vico/env.py:33-376` 的 `VicoEnv` 是主环境适配器：

- 读取 `config_path/config.json`、建筑/地点元数据和场景交通 JSON。
- 初始化 Genesis Scene、渲染器、碰撞/分解选项、地形与城市 GLB、Avatar/Robot、室内场景、交通管理器和共享自行车。
- 对外维护 observation/action space；单 Agent observation 包括 RGB、depth、segmentation、extrinsics、pose、accessible places、action status、current building/place、cash、held objects 等。
- `reset()` 恢复场景/交通/Agent 状态；`step()` 处理动作、推进 Genesis 帧、处理聊天、更新仿真时间和配置、重新生成观察。
- `perform_action()` 是动作语义边界，处理 `converse`、`enter`、导航移动/转向、交通工具、拾取/放下、吃喝、交易、动画和 `wait` 等动作。
- `EventSystem` 使用三维 R-tree 将语音/事件按空间半径分发给附近 Agent，并在重叠语音中按优先级保留一个。

### 3.5 模型服务与 LLM 适配层

- `tools/model_manager/__init__.py` 的 `ModelManager` 注册 `ram`、`dino`、`sam`、`clip`、`embedding`、`completion` 六种客户端。
- `local=True` 时按 CUDA 设备数划分模型进程：视觉模型/embedding 与 completion 可分开；无 CUDA 时只启用 CPU/MPS 可用的视觉子集。
- `ProcessChannel` 使用多路 `multiprocessing.Queue`、共享字典和条件变量；`/ram`、`/dino`、`/clip/text`、`/embedding`、`/completion` 支持批量取最多四个请求，`/sam`、`/clip/image` 走 unbatched 路径。
- `ModelProcess.process()` 按 URL 路由到 wrapper 或 vLLM；`ModelClient` 将 Tensor 转 CPU 后通过队列或 HTTP POST 传输，再转回目标设备。
- `tools/model_manager/server.py` 的 `ModelServerHandler` 对 POST body 做 pickle 反序列化并按 `self.path` 调模型；源码未见鉴权、签名、请求大小限制或 URL 白名单。
- `tools/generator.py` 的 `Generator` 为 LLM/embedding 统一入口：OpenAI、Azure OpenAI、HuggingFace pipeline、local vLLM 等 provider；对 OpenAI/Azure 使用 `.api_keys.json`，对 embedding 使用文本缓存 pickle，并在请求后写 `chat_raw.jsonl`。
- Ella 通过提示词模板调用 Generator，主要模板位于 `agents/prompts/ella/`；JSON 解析失败时会再发一次“只输出 JSON”的修复请求。

### 3.6 评估与诊断层

- `ControlledFinals/evaluate.py` 读取 `curr_sim/config.json` 和合并后的 Agent step JSON：
  - Influence Battle：统计 party organizer 到场率、对话次数和分组结果。
  - Leadership Quest：统计各组货物完成率、成本和对话次数。
- `ControlledFinals/InfluenceBattle.py` 在第一天配置 party organizer groups 和邀请要求，然后运行仿真并调用 `evaluate_IB()`。
- `ControlledFinals/LeadershipQuest.py` 生成组长、目标货物和每日任务，然后运行仿真并调用 `evaluate_LQ()`。
- `diagnose_agent_recognition.py` 与 `diagnose_all.py` 将观察中的视觉对象按类型分组，使用 CLIP 余弦相似度和高/低阈值产生 `LINKED`、`ABSTAIN`、`NEW`，再让 LLM 基于链接实体回答识别问题。
- 诊断脚本会产生图片、相机元数据和结果 JSON；它们是实验产物，不是持久化数据库迁移。

## 4. 数据模型与数据流

### 4.1 输入配置

典型输入位于 `vico/assets/scenes/<SCENE>/<CONFIG>/`：

- `config.json`：仿真时间、step、Agent 名称/初始 pose/信息、分组、交通工具、控制频率、视觉观察频率等。
- `seed_knowledge.json`：每个 Agent 的初始语义知识。
- `seed_knowledge_feature.pkl`：初始知识视觉特征。
- `scratch.json`：单 Agent 的计划、身份、状态、当前地点/车辆、聊天和记忆恢复字段。
- 场景级 `building_metadata.json`、`place_metadata.json`、`transit.json` 和下载/缓存的 ViCo 资产。

### 4.2 运行时观察与动作契约

观察大体为：

```text
obs[agent_id] = {
  rgb, depth, segmentation, extrinsics, pose,
  curr_time, steps, events, accessible_places,
  action_status, current_building, current_place,
  cash, held_objects, current_vehicle,
  [gt_seg_idxc_to_info], [robot_obs, robot_additional_obs]
}
```

动作是字典，核心字段为 `type`、`arg1`，部分动作带 `arg2`。典型动作包括：`wait`、`move_forward`、`turn_left`、`turn_right`、`converse`、`enter`、`enter_bus`、`exit_bus`、`enter_bike`、`exit_bike`、`pick`、`put`、`stand`、`sit`、`look_at`、`eat`、`drink`、`exchange`、`play_animation`。ViCo 的 `perform_action()` 负责校验可达地点、近距离、持有物和现金，并更新环境状态。

### 4.3 记忆落盘

```text
output/.../curr_sim/<Agent>/
├── scratch.json                    # 可变 Agent 状态/计划快照
├── seed_knowledge.json             # 初始化语义知识（源数据）
├── seed_knowledge_feature.pkl      # 初始化视觉特征（源数据）
├── semantic_memory/
│   ├── knowledge.json              # 运行时语义知识
│   ├── knowledge_feature.pkl       # 运行时知识特征
│   ├── object/objects.pkl          # 检测对象及其体素/外观
│   ├── region/region.json           # 可选区域聚类
│   └── <place>/volume_grid.pkl     # 各地点空间体素
├── episodic_memory/experience.json # 情景事件列表
└── logs.log

output/.../steps/<Agent>/<step>.json # 每步 obs 摘要、action、计划/反应/聊天等
```

图片、深度可视化、分割图、demo/third-person 相机帧和模型日志按入口参数写入 `output`。`atomic_save()` 通过临时文件替换保护已存在文件，但记忆本身仍是 JSON/pickle 文件模型，不是事务型数据库。

### 4.4 记忆闭环

```text
RGB-D/语音/动作结果
  → VicoEnv obs
  → Agent.act()
  → SemanticMemory.update(obs)
      → ObjectBuilder/Builder/VolumeGrid
      → knowledge.json / knowledge_feature.pkl
  → EpisodicMemory.add_memory(...)
      → embedding + FAISS index + experience.json
  → retrieve(query, image, time, position, k)
  → 组装提示词上下文
  → Generator.generate()
  → 结构化解析/validator/fallback
  → action dict
  → VicoEnv.perform_action()/step()
  → scratch.json + steps/*.json + config.json
```

## 5. 关键路径

| 场景 | 入口与关键调用 | 主要产物 |
|---|---|---|
| Ella 一日模拟 | `scripts/ODM/run_ella_odm_newyork.sh` → `odm.py` → `VicoEnv` → `AgentProcess` → `EllaAgent.act()` | `output/odm/...`、记忆、step 日志 |
| Ella + segmentation | `scripts/ODM/run_ella_seg_odm_*.sh` → `odm.py --enable_gt_segmentation` 等 | GT 分割驱动的语义/情景记忆 |
| Influence Battle | `scripts/IB/test_IB_ella_*.sh` → `ControlledFinals/InfluenceBattle.py` → `evaluate_IB()` | `results.json`、到场率/对话指标 |
| Leadership Quest | `scripts/LQ/test_LQ_ella_*.sh` → `ControlledFinals/LeadershipQuest.py` → `evaluate_LQ()` | `results.json`、完成率/成本/对话指标 |
| 视觉诊断 | `diagnose_agent_recognition.py` 或 `diagnose_all.py` → `EllaAgent.diagnose()` | debug RGB/depth/camera JSON、识别结果 JSON |
| 独立 ViCo 仿真 | `vico/scripts/run_env.py`、`run_simple_env.py`、`run_tour_agent.sh` | ViCo 场景和 Agent 运行产物 |
| 场景图构建 | `agents/sg/example.py` → `Builder.add_frame()` → C++ `VolumeGridBuilder` | `point_cloud.pkl`/体素网格 |
| 模型进程 | `ModelManager(local=True)` → `ModelProcess` → `ProcessChannel` 或 `ModelServer` HTTP | 模型推理结果，不直接写业务记忆 |

## 6. API / CLI / SDK 盘点

### 6.1 Python API（源码实际可调用接口）

- `agents.ella.EllaAgent(name, pose, info, sim_path, ...)`
  - 生命周期：继承 `Agent.act(obs)`。
  - 关键行为：`conversation()`、`commute()`、`navigate()`、`adjust_schedule()`、`diagnose()`、`save_scratch()`。
- `agents.memory.SemanticMemory(storage_path, detect_interval, fov, region_layer, ...)`
  - 关键方法：`update()`、`get_knowledge()`、`get_sg()`、`update_with_new_knowledge()`、`save_memory()`。
- `agents.memory.EpisodicMemory(storage_path, lm_source, ...)`
  - 关键方法：`add_memory()`、`retrieve()`、`retrieve_latest_memory()`、按时间/地点/关键词检索。
- `vico.env.VicoEnv(...)`
  - 关键方法：`reset()`、`step(agent_actions)`、`get_obs()`、`perform_action()`、`scene_step()`、`close()`。
- `agents.sg.builder.builder.Builder` / `VolumeGridBuilder`
  - 关键方法：`add_frame()`、`navigate()`、`save()`、`load()`、占据图和几何查询。
- `tools.model_manager.ModelManager`
  - 关键方法：`init()`、`get_model()`、`get_generator()`、`set_channel()`、`close()`。

### 6.2 CLI

仓库没有 `console_scripts` 或 Click/Typer 命令注册；入口均由 `python <file>.py [argparse options]` 或 shell 模板调用。已确认的参数类别包括：场景/配置、Agent 数量/类型、LLM provider/model、GPU/CPU、headless、多进程、碰撞、室内/室外物体、GT segmentation、最大仿真时间、输出目录和挑战类型。

README 中给出的最小实验入口是：

```bash
uv sync --all-packages
source .venv/bin/activate
cd agents/sg
./setup.sh
cd ../..
python odm.py --head_less --backend cpu --multi_process \
  --skip_avatar_animation --output_dir output/odm \
  --scene NY --num_agents 15 --config agents_num_15 \
  --agent_type ella --max_seconds 32400 --lm_id gpt-4o
```

上面仅记录源码 README/脚本声明的调用形态，当前核对没有执行。

### 6.3 内部 HTTP/RPC API

`tools/model_manager/server.py` 暴露的路径是：

| 路径 | 语义 | 客户端 |
|---|---|---|
| `/ram` | RGB → 标签 | `RAMClient.predict(rgb)` |
| `/dino` | RGB + 文本标签 → boxes/phrases | `DINOClient.predict(rgb, text, annotate)` |
| `/sam` | RGB + boxes → masks | `SAMClient.predict(rgb, boxes, annotate)` |
| `/clip/image` | RGB → image embedding | `CLIPClient.predict_image()` |
| `/clip/text` | 文本 → text embedding | `CLIPClient.predict_text()` |
| `/embedding` | 文本 → embedding | `EmbedClient.encode()` |
| `/completion` | chat messages → completion 文本 | `CompletionClient.complete()` |

协议是 `pickle.dumps((args, kwargs))` 的 POST body，返回 pickle；默认监听 `localhost:8000`（源码 main 的 argparse）。没有版本、鉴权、超时/大小限制和跨语言 SDK 约定，因此不应视为生产 API。

### 6.4 SDK 状态

存在可复用的 Python 模块接口，但未发现独立 `sdk/`、发布说明、稳定版本化契约或面向外部调用者的 SDK。`vico/` 是 workspace member 和可 import 的 `virtual-community` 包；根项目自身名为 `ella`，版本 `0.1.0`。根 `vico/vico/__init__.py` 当前为空，公共导出主要通过具体模块路径完成。

## 7. 技术栈与依赖边界

| 类别 | 实际证据与组件 |
|---|---|
| 语言/运行时 | Python `==3.11.*`；少量 C++ 低层空间网格/路径库。根 `pyproject.toml:1-5`。 |
| 包管理 | `uv`；根项目 workspace member 为 `vico`，本地 editable third-party 为 EfficientSAM、GroundingDINO、open_clip、RAM。`pyproject.toml:14-27`。 |
| 仿真/物理 | Genesis World（Git pinned revision）、MuJoCo、Gymnasium；ViCo 使用 Genesis Scene、Avatar/Robot、交通和渲染器。 |
| 深度学习 | PyTorch `2.0.1`、TorchVision `0.15.2`、Torchaudio `2.0.2`；CUDA 11.7 index 仅对 Linux 标记。 |
| 视觉感知 | RAM/recognize-anything、GroundingDINO、EfficientSAM；另包含 Segment Anything 2 作为第三方代码。 |
| 表征/检索 | open_clip/CLIP、FAISS CPU、NumPy、SciPy；文本和图像 embedding 分开索引。 |
| LLM/提供商 | OpenAI SDK、Azure OpenAI、Transformers pipeline、local vLLM completion/embedding；源码还保留 Gemini/LLaVA/VLA 分支。 |
| 空间/渲染 | RGB-D、OpenCV、Pillow、R-tree、pyproj、Shapely、PyVista/VTK、USD、GLB/GLTF、Blender scene-generation 工具。 |
| 存储 | JSON、JSONL、pickle、PNG/图像、日志；不存在 ORM/SQL/消息队列/对象存储层。 |
| 编译扩展 | `agents/sg/setup.sh` 执行 `agents/sg/builder/builtin/Makefile`，生成 `libbuilder.so` 和 `libregion.so`；需要 `CUDA_HOME`（`agents/sg/README.md:5-14`）。 |
| 资产 | ViCo 的 `asset_utils.py` 支持 `VICO_ASSET_PATHS` 本地覆盖，并在缺失时从 HuggingFace dataset `Virtual-Community-AI/assets` 增量下载。 |
| 操作系统假设 | `uv` 环境声明包含 Darwin 与 Linux x86_64；ViCo README 实际推荐 Ubuntu 24.04 + CUDA 11.7。macOS/MPS 全量 Genesis、C++ CUDA 扩展和模型权重兼容性未由当前核对执行确认。 |

依赖规模上，根项目只声明四个本地视觉包和 `setuptools`，而 `vico/pyproject.toml` 固定了大批仿真/渲染/科学计算依赖，并从 Git 拉取 Genesis。`uv.lock` 是锁文件；当前核对只读取声明，未解析或安装环境。

## 8. 测试与验证现状

### 已发现测试

- 根项目：`tests/test_model_manager.py`。
  - 测试 `auto_batched()` 的 tuple/dict/bool/非法输入。
  - 测试 `ProcessChannel` 的 pickle state、客户端/服务端 round-trip、批量与 unbatched 路由、model subset 过滤。
  - 测试 `ModelProcess` 设备选择、环境变量、未知模型和子集排除。
  - 测试 `ModelManager` 客户端注册、channel 传播、设备传播、关闭和本地初始化。
  - 标记为 `integration` 的 CLIP、RAM、DINO、SAM 推理测试需要真实模型权重和运行中的模型进程；根 `pyproject.toml:34-38` 注册了该 marker。
- 第三方：`agents/sg/third_party/open_clip/tests/` 有 open_clip 自己的推理、下载、训练、WDS 等测试；GroundingDINO 还有 demo 测试文件。它们不等同于 Ella 的端到端回归测试。
- 未发现覆盖 `EllaAgent` 行为决策、SemanticMemory/非参数记忆持久化、EpisodicMemory 检索排序、VicoEnv 动作语义、Controlled Finals 指标的根级单元测试。

### 当前核对验证边界

当前核对只进行了静态读取和目录/Git 状态盘点，**没有运行 pytest**。原因是用户明确禁止安装依赖、启动服务、构建；集成测试还会触发真实模型权重/模型进程。文档不声明测试通过。

## 9. 未确认项、风险与后续核查清单

以下项目是源码阅读后仍需专门运行或人工裁决的事项，不代表当前核对已验证失败：

1. **环境可运行性**：根 workspace、ViCo 子模块、Genesis pinned commit、PyTorch/CUDA 11.7、macOS/MPS 组合是否可安装和启动未验证。
2. **子模块状态**：`vico/` 是 Git submodule；当前仓库 HEAD 为一个浅 graft commit，子模块内部源码是否与锁文件/上游 commit 完全一致，需要单独核对。
3. **C++ 扩展**：`libbuilder.so`/`libregion.so` 是否已存在、ABI 是否匹配、`CUDA_HOME` 和 Makefile 是否可构建未验证；当前核对禁止构建。
4. **资产完整性**：部分资产会从 HuggingFace 懒下载，室内 GRUTopia 资产需另行准备；本地快照、网络、磁盘和权重完整性未验证。
5. **凭据与安全**：OpenAI/Azure 依赖 `.api_keys.json`，其格式、轮换和是否被 `.gitignore` 正确排除未做运行核查；HTTP pickle 模型服务无鉴权，不适合暴露到非 localhost 网络。
6. **记忆一致性**：SemanticMemory 和 EpisodicMemory 采用 JSON/pickle 全量/异步保存；并发写、进程退出时后台保存、索引与文件的一致性、版本恢复未有端到端测试证明。
7. **检索实现缺口**：`SemanticMemory.retrieve_knowledge()` 是空实现；情景记忆的 FAISS 索引在加载时重建，图片路径失效、空库检索、索引与删除后的 ID 对齐需核查。
8. **非参数语义边界**：源码体现“追加/更新文件中的知识对象”与事件列表，但 `EpisodicMemory.remove_memory()`、`clear_memory()` 和失败动作原地修改说明并非严格 append-only；需明确论文语义与工程语义的边界。
9. **LLM 输出可靠性**：多个提示词输出依靠手写 JSON 解析、二次修复请求和 fallback；不同 provider 的 JSON/图像输入/embedding 返回形状是否一致未由合同测试覆盖。
10. **入口漂移**：README 的 `./scripts/ODM/run_ella_odm_newyork.sh`、根脚本和 ViCo 子模块各自有参数默认值；例如 `lm_source` 默认值在不同入口中存在差异，需按实验复现目标锁定参数。
11. **诊断脚本状态**：诊断脚本包含相机坐标校准、硬编码场景坐标和 debug 输出；应在 GPU/资产齐备环境单独验证，不能把静态代码路径当作诊断结果。
12. **评估副作用**：`ControlledFinals/evaluate.py` 会写 `results.json`，并对从配置读取的字典做原地 `pop`；评估是否应当只读、重复运行是否幂等未验证。
13. **测试覆盖**：根测试主要覆盖模型管理通道；没有看到 Agent 状态机、跨日计划、聊天事件优先级、交通工具、拾取/交易、空间导航、记忆恢复和挑战指标的回归矩阵。
14. **许可与再分发**：Ella 根目录未发现根级 `LICENSE` 文件；许可证文件主要位于第三方子目录。论文代码、ViCo、模型和资产的许可边界需要在再使用前逐项确认。
15. **历史实现并存**：`agents/memory.py` 与 `agents/gen_agent_memory.py` 各有一套语义/情景记忆；两者字段、event id、embedding 持久化和检索算法不同，后续维护不能默认它们可互换。

## 10. 已读证据索引

- 总览与安装/实验：`README.md`
- 既有细探：`细探-Ella.md`（已完整读取并保留；吸收/未吸收裁决见第 12 节）
- 根依赖与测试标记：`pyproject.toml`
- 子模块依赖与运行说明：`vico/pyproject.toml`、`vico/README.md`
- 主入口：`odm.py`
- Ella Agent：`agents/ella.py`
- Agent 生命周期/进程：`vico/vico/agents/agent.py`
- Agent 工厂：`agents/__init__.py`、`vico/vico/agents/__init__.py`
- 语义/情景记忆：`agents/memory.py`、`agents/gen_agent_memory.py`
- 视觉对象与场景图：`agents/sg/README.md`、`agents/sg/builder/object.py`
- LLM：`tools/generator.py`
- 模型队列/HTTP：`tools/model_manager/{__init__.py,client.py,server.py}`
- ViCo 环境：`vico/vico/env.py`
- 评估：`ControlledFinals/{InfluenceBattle.py,LeadershipQuest.py,evaluate.py}`
- 诊断：`diagnose_all.py`、`diagnose_agent_recognition.py`
- 测试：`tests/test_model_manager.py`

## 11. 工作树边界

建档前 Git 状态显示：当前分支为 `master`，HEAD 为 `f29694a (update vico)`，已有未跟踪文件 `细探-Ella.md`。当前核对只维护根目录 `ARCHITECTURE.md`；未修改源码、依赖、测试、配置、子模块、既有细探文件或 Git 历史。

## 12. 旧细探吸收与未吸收裁决

本节是对 `细探-Ella.md` 的逐项收口。旧细探**保留、不删除**，但不再作为并行权威架构文档；后续架构事实只维护本 `ARCHITECTURE.md`。裁决以当前工作树源码、README、依赖声明、评估/诊断脚本和可见许可证文件为准，论文与旧细探只作为线索。

| 旧细探主张 | 裁决 | 当前源码证据与收口说明 |
|---|---|---|
| Ella 是具身社交 Agent 的非参数终身记忆研究实现，论文为 arXiv `2506.24019` | **吸收** | README 首段、论文链接、根 `pyproject.toml` 的项目描述，以及 `agents/ella.py` 的实现定位一致；已纳入第 1 节。论文表述不当作运行证明。 |
| 项目使用 Python + `uv` | **吸收并具体化** | 根 `pyproject.toml` 声明 Python `==3.11.*`、workspace 和本地 editable 视觉依赖；README 给出 `uv sync --all-packages`。已纳入第 7 节和第 6.2 节。 |
| 总体链路为 agent → tools/vico → odm → 非参数记忆 → ControlledFinals/diagnose | **吸收并校正** | 该分层已展开为入口/编排、Agent、记忆、ViCo、模型、评估诊断六层；`odm.py` 是实验入口，不是记忆对象数据库本身。已纳入第 2、3、5 节。 |
| 非参数记忆“不覆盖旧记忆”，属于终身学习 | **部分吸收（保留工程边界）** | `EpisodicMemory.add_memory()` 追加事件并持久化，支持事件检索；但源码也存在 `remove_memory()`、`clear_memory()`、失败动作更新以及语义知识更新，不能据此断言全系统严格 append-only。已纳入第 9 节第 8 项和第 4.4 节，改写为论文语义与工程语义待区分。 |
| `odm` 是对象数据库，负责记忆对象管理 | **不按原说法吸收，已纠正** | 当前 `odm.py` 解析参数、创建 `curr_sim`、初始化 `VicoEnv`/模型管理器/`AgentProcess` 并运行仿真；语义对象和情景事件实际由 `agents/memory.py` 以 JSON/pickle/FAISS 文件管理。已在第 3.1、3.3、4.3、6.2 节明确。 |
| `vico` 是 Virtual Community 集成，提供 Agent 生活场景 | **吸收** | `vico/pyproject.toml` 的包名为 `virtual-community`；`vico/vico/env.py` 提供 Genesis 场景、Agent、交通、Avatar/Robot、动作与观察。已纳入第 1、3.4、7 节。 |
| 评估由 `ControlledFinals` 与 `diagnose_agent_recognition.py`/`diagnose_all.py` 构成 | **吸收并具体化** | `ControlledFinals/evaluate.py` 的 IB/LQ 指标、配置/step 合并和 `results.json` 写入，以及两个诊断脚本的 RGB/depth/camera/debug JSON 产物，已纳入第 3.6、5、9 节。 |
| 具身 Agent 的提示词/决策逻辑位于 `agents/tools` | **部分吸收（路径校正）** | 决策实现位于 `agents/ella.py`，模型统一入口为 `tools/generator.py`，提示词模板引用位于 `agents/prompts/ella/`；`tools` 还承载模型管理、诊断和辅助脚本，不能概括为单一提示词目录。已纳入第 3.2、3.5、6 节。 |
| 可借鉴：非参数记忆、记忆对象管理、具身 Agent 工具集 | **吸收为研究启示，非实现事实** | 前者可作为“追加事件但需审查删除/纠错语义”的候选模式；后两项已拆成文件型语义记忆、空间场景图、模型/环境动作边界。它们不是本项目已提供的通用平台组件，故不写入 API/SDK 承诺。 |
| 许可证见仓库 LICENSE，但细探同时称许可证未确认 | **不吸收该许可证断言，保留风险** | 根目录当前没有 `LICENSE`；可见许可证位于 `agents/sg/third_party/*` 子目录，不能推导 Ella 根项目许可证。已纳入第 7 节和第 9 节第 14 项。 |
| 依赖 Virtual Community 与 LLM，平台只借鉴非参数机制 | **吸收并收窄边界** | README 要求先安装 Virtual Community；`EllaAgent` 通过 `Generator` 调用 OpenAI/Azure/HuggingFace/local 等 provider。当前文档保留“研究实现、非生产 Web/API 服务”边界，不把其依赖或机制直接声明为平台组件。 |

### 12.1 未吸收或被降级为待核事项

1. **“`odm` 对象数据库”**：与源码职责不符，裁决为实验编排入口；不得再作为架构层名称使用。
2. **“全量不覆盖/严格终身追加”**：源码同时存在删除、清空、失败动作原地更新和语义知识更新；只能保留为论文/设计方向，不能作为已验证工程不变量。
3. **根项目许可证已知**：没有根 `LICENSE`，第三方许可证不能替代项目级许可证判断；再使用前仍需逐项核对上游声明、子模块、模型和资产许可。
4. **仅凭脚本名推断评估已完成**：Controlled Finals 和诊断脚本的调用链已确认，但当前核对没有启动模拟器、模型服务或测试，因此没有评估数值、诊断结果或运行成功结论。
5. **“对象数据库”作为平台可直接复用组件**：未发现独立 ODM、ORM、SQL 或事务数据库层；当前可复用边界是 Python 类/函数与文件格式，详见第 6 节和第 7 节。

## 13. 后续底座映射：通用底层与必须隔离的边界

本节是后续裁决，不把“已有类”直接等同于“平台能力”。依据当前源码中的 `odm.py`、`vico/vico/agents/agent.py`、`tools/model_manager/`、`agents/memory.py`、`agents/ella.py` 与 `ControlledFinals/` 调用链，只抽取跨领域的资源治理与协议形状；仿真世界、Agent 行为、记忆语义和挑战指标仍归 Ella/ViCo 项目适配层。

### 13.1 推荐的唯一底座链与归属

```text
实验命令/项目适配层
  → 运行清单（run_id/版本/种子/配置摘要/所有者）
  → 仿真适配器（ViCoEnv，隔离 Genesis/资产/动作语义）
  → Agent 运行时（每个 agent_id 一个 AgentProcess/状态租约）
  → 带 request_id、run_id、agent_id、step、deadline 的队列信封
  → 唯一模型网关（视觉/Embedding/生成能力注册与资源调度）
  → 受管 provider/独立模型进程
  → 记忆写入者与索引构建者（语义记忆、情景记忆分域）
  → checkpoint/事件/图片/索引产物
  → 只读评估快照 → 领域评估器 → 带证据清单的结果报告
```

**唯一归属规则：**

- `run_id`、配置快照、随机种子、checkpoint 和最终状态由运行编排器拥有；入口脚本只能提交命令，不能另建一套运行状态。
- 进程生命周期由进程监督器拥有；`AgentProcess` 是 agent actor 的执行单元，不应同时成为进程重启、队列回收和最终状态的 owner。
- 队列和请求状态由队列/消息协调器拥有；Agent、模型 provider、评估器不能旁路读写对方队列，也不能用业务字段猜请求是否完成。
- 模型实例、设备上下文和模型进程由模型网关/模型 provider 拥有；消费者只持有能力客户端或短期请求租约。`EllaAgent.__init__()` 中反复调用 `global_model_manager.set_channel()`（`agents/ella.py:35-41`）不应成为通用调用约定，应由编排器一次绑定后向 Agent 注入只读客户端。
- `knowledge.json`/`experience.json` 等事实文件及其版本由对应记忆写入者拥有；FAISS/视觉索引是可重建派生物，不可反向成为事实源。
- `results.json` 由评估器拥有，且评估只读输入快照；评估器不得修改 `curr_sim/config.json` 或 Agent 记忆。

### 13.2 可抽取的通用底层、抽取方式和限制

| 能力 | 裁决 | Ella 证据 | 抽取后的稳定契约 |
|---|---|---|---|
| 运行身份与 checkpoint | **吸收为运行核心** | `odm.py:68-98`、各 Controlled Finals 入口创建/续跑 `curr_sim` | 每次运行生成不可复用的 `run_id`；记录代码/配置/模型/资产摘要、seed、所有者、状态；checkpoint 原子提交并可从最后确认 step 恢复。 |
| Agent/模型进程监督 | **吸收为通用进程底座** | `AgentProcess(mp.Process)`（`vico/vico/agents/agent.py:100-222`）、`ModelProcess`（`tools/model_manager/server.py:125-215`） | 启动、就绪、心跳、优雅停止、超时、终止进程组、`join`、退出码/信号分类、重启上限、残留扫描均由一个监督器实现；业务 worker 不得自我宣布“已恢复”。 |
| 请求队列与批处理 | **吸收为通用队列底座** | `ProcessChannel` 的按 URL 多队列、`auto_batched()`、Condition（`tools/model_manager/server.py:11-123`） | 信封必须含 `request_id`、`run_id`、`owner_id`、能力 id、序号、deadline、重试次数和 payload/文件引用；确认、超时、重试、幂等、死信和排空可观察。按能力批处理是实现策略，不是业务契约。 |
| 模型能力网关 | **吸收为通用模块/注册表** | `ModelManager` 注册 `ram/dino/sam/clip/embedding/completion`（`tools/model_manager/__init__.py:8-68`） | 统一能力 id、输入输出版本、设备/显存预算、批大小、超时、可重试错误和关闭语义；provider 通过适配器注册，禁止消费者直接 import 第三方模型。 |
| 原子文件与产物账本 | **吸收为文件资源底座** | `atomic_save()` 被 Agent、记忆、入口使用；`output/.../curr_sim`、`steps/`、图片和日志是实际产物 | 每次写入 `tmp → flush/fsync → 原子替换`；manifest 记录相对路径、内容摘要、owner、step、完成标记；失败临时文件可清理，正式文件不被半写覆盖。 |
| 记忆事件/索引分离 | **吸收机制，保留领域适配层** | `EpisodicMemory` 追加事件后更新 FAISS，`SemanticMemory` 同步 knowledge/scene graph（`agents/memory.py:24-310,381-521`） | 通用层提供事件 envelope、版本、幂等键、事实源与可重建索引分离、checkpoint/rebuild；字段、衰减、相似度、空间图和删除/纠错语义由记忆域 owner 定义。 |
| 评估运行器 | **吸收框架，不吸收指标** | `ControlledFinals/evaluate.py:14-115` 读取 step 文件并写结果 | 通用 runner 固定输入快照、版本、seed、指标清单、缺失数据处理、报告摘要和证据 hash；IB/LQ 的到场、对话、货物和成本定义必须留在挑战适配器。 |
| 统一诊断/审计证据 | **吸收为验证底座** | `diagnose_*.py` 输出 debug 图像、相机元数据和 JSON；模型测试含 unit/integration 分层 | 每一结论标注源码存在、测试存在、真实执行、外部依赖和产物校验等级；不能用打印日志、历史文件或子代理回信替代执行证据。 |

### 13.3 必须隔离的项目域和危险边界

| 域 | 必须隔离的内容 | 原因与底座边界 |
|---|---|---|
| 仿真/物理 | Genesis `Scene`、MuJoCo/Gymnasium、ViCo 资产、碰撞、渲染、交通、Avatar/Robot、`perform_action()` 的动作语义 | 这些对象持有 GPU/物理句柄和场景全局状态；平台只能提供 `SimulationAdapter.reset/step/close` 与 observation/action 契约，不能把 ViCo 世界模型抽成通用状态库。 |
| Agent 行为 | `EllaAgent` 的计划、反应频率、对话缓冲、提示词、通勤、拾取/交易和动作决策；`GenAgent` 的另一套反思/计划记忆 | 行为策略和 prompt 是实验变量，必须按 Agent 类型、模型版本和运行版本隔离；通用层只提供 actor 生命周期与消息协议。 |
| AgentProcess 状态 | 每个 Agent 的 `scratch.json`、`curr_time`、`pose`、`held_objects`、`cash`、step 日志和异常上下文 | 进程模式可复用，状态语义不能合并。每个 `agent_id` 只能有一个活动 owner；重启必须从该 Agent 最近确认 checkpoint 恢复，不能共享 Python 对象或复制另一 Agent 的 scratch。 |
| 视觉模型 | RAM → GroundingDINO → SAM → CLIP 的模型链、RGB-D/segmentation/相机外参、512 维视觉特征和对象/体素构建 | 可复用“视觉能力调用”协议，但检测阈值、标签、mask、坐标系、场景图和 `ObjectBuilder` 必须隔离；视觉失败不能伪造空对象或成功识别。 |
| Embedding | 文本维度、归一化、模型版本、FAISS index 维度与重建规则 | 可复用 embedding provider/缓存/索引生命周期，但不能把 `text-embedding-3-small`、CLIP image embedding 和其他向量当同一能力或共享 index；维度/模型摘要必须写入索引 manifest。 |
| 生成模型 | OpenAI/Azure/HuggingFace/LLaVA/VLA/Gemini/local vLLM 的凭据、prompt、图像编码、JSON 修复和 token/cost 规则 | 可复用生成网关和重试/预算/审计，不可把 provider fallback、凭据或领域 prompt 下沉为全局默认。模型输出是候选，Ella 的 JSON 解析、动作白名单和领域决策仍在项目适配层。 |
| 语义记忆与情景记忆 | `SemanticMemory` 的知识/空间图/对象索引与 `EpisodicMemory` 的事件/时间/关键词/FAISS 检索 | 两者字段、更新时机、索引维度和删除/纠错语义不同；只能共用文件事务、事件 envelope 和资源租约，不能合并成一个“通用 memory”或互相覆盖 owner。 |
| 评估指标 | Influence Battle 的 show-up/conversation 与 Leadership Quest 的 goods/cost/conversation，以及诊断的 `LINKED/ABSTAIN/NEW` 阈值 | 指标是挑战定义，不是平台事实；评估器只能消费冻结快照并生成新报告，不能改写仿真配置、scratch 或记忆。 |
| 内部 HTTP pickle | `tools/model_manager/server.py` 的 localhost POST + `pickle.loads()`/`pickle.dumps()` | 可保留为研究环境兼容适配器但必须隔离、仅 localhost、独立进程、大小/路径/版本/错误边界受控；不能进入通用公共 API，也不能让不可信输入触达反序列化。 |

### 13.4 进程、队列、模型、文件和内存资源生命周期

| 资源 | 创建/持有与转移 | 正常释放 | 失败、超时、崩溃恢复与现场验证 | 唯一 owner |
|---|---|---|---|---|
| Agent 进程 | 编排器为每个 `agent_id` 创建 `AgentProcess`；进程内创建 Agent、logger、记忆实例；不转移 Agent Python 对象 | 发送停止信号后 drain 输入/输出队列，`join`；超时按进程组终止，再确认 pid 消失 | 当前 `AgentProcess.close()` 只 `terminate()`（`agent.py:218-222`），没有 join、队列关闭、退出状态和 checkpoint 确认。底座必须记录 `started/ready/checkpointed/stopped/restarted/failed`，异常/非零退出只能标记失败或进入有界恢复；验证 `is_alive=False`、`join` 返回、无孤儿 pid、无未消费请求 | 进程监督器（Agent 只报告业务结果） |
| 模型进程与 GPU/模型内存 | `ModelManager.init(local=True)` 创建 `ProcessChannel` 和一个/多个 `ModelProcess`；worker 首次 `process()` 懒加载模型（`server.py:178-214`） | 停止接收新请求，等待/取消在途请求，释放模型/GPU/C++ 句柄，关闭 channel，`join` | 当前 manager `terminate()` 后 `join(5)`（`__init__.py:90-112`）但未验证退出码、进程组、队列残留或 provider 清理。模型崩溃不得返回空成功；按能力区分可重试/不可重试，重新加载必须绑定同一 `model_id+版本+设备租约`，并验证显存/进程归零 | 模型网关/Provider；消费者仅持有 client |
| 队列、Condition、Manager | `ProcessChannel` 创建七类 `mp.Queue`、Manager dict、两个 Condition（`server.py:38-53`）；请求以随机整数 id 放入队列 | 入口停止接收、按 run/agent 逐项 drain 或转死信，关闭 queue 并 `join_thread`，最后 shutdown Manager | 当前 `get_c()`/`get_s()` 可能无限轮询；`ModelClient` 用 `random.randint()` 作为 id（`client.py:27-37`），没有 deadline、取消、死信、容量和重复检测。底座使用 run-scoped 单调/UUID request id、有限等待、队列深度和年龄指标；验证无 pending、无 manager/feeder 进程、所有请求都有 terminal 状态 | 队列协调器 |
| 文件、临时目录、图片和日志 | 运行编排器创建独占 `output/<run_id>`；Agent/记忆/评估按 owner 写各自子目录；写入者只写自己的路径 | `atomic_save` 完成临时替换；正常结束写 manifest/完成标记；关闭日志句柄 | 后台 daemon `Thread(target=_save, daemon=True)`（`agents/memory.py:174-185`）可能在进程退出时丢写；JSON/pickle/index 多文件也没有同一事务。底座要求写入 future 可等待、tmp/正式文件摘要、checkpoint manifest；崩溃时删除未完成 tmp、从最后 manifest 重建索引，不把半写文件算成功。验证路径 owner、摘要、完成标记、无孤立 tmp/锁文件 | 文件/产物账本；每个记忆域拥有自己的正式文件 |
| Python/NumPy/Torch 内存 | observation/action、批量 payload、RGB-D、embedding、FAISS 输入在客户端、队列、worker 间复制/序列化；模型 worker 长期持有权重和设备上下文 | 请求终态后释放临时数组/引用；worker close 时释放模型上下文；索引重建使用有界批次 | 队列积压会同时放大进程间 pickle、CPU RAM、GPU 显存；超时后不能让 late result 继续写错误 run。底座需 payload 大小上限、引用/副本标识、deadline、取消后的 late-result 丢弃、内存/显存水位；验证进程退出后 RSS/GPU/context 无增长和无跨 run 引用 | 请求协调器管理 payload 租约；provider 管模型内存；索引 owner 管 index |
| FAISS/场景图等派生索引 | 由记忆 owner 按事实文件构建；索引 manifest 记录模型/维度/事实版本 | checkpoint 后原子替换索引，或关闭时不保存未完成构建 | 索引损坏、维度变化、图片路径失效时删除并从 authoritative JSON/对象文件重建；不能以旧 index 搜索新事实。验证 `ntotal`、事件/对象数量、维度、内容摘要与 manifest 一致 | 对应记忆域 owner，通用底座只提供 rebuild 协议 |

### 13.5 失败恢复矩阵与当前代码缺口

| 场景 | 当前行为/证据 | 底座要求 |
|---|---|---|
| Agent 业务异常 | `AgentProcess.run()` 捕获异常后把 action/utterance 置为 `None`（`agent.py:153-180`），外层仿真仍可能继续 | 记录结构化 `agent_error`（异常类型、step、输入摘要、进程身份）；禁止把 `None` 当“正常等待”。由策略决定重试、跳过本 step 或终止 run，且报告必须显示失败。 |
| Agent 进程死亡 | 没有父侧 heartbeat/exit-code/restart 逻辑；主循环直接 `agent.act()` | 监督器检测死亡与丢失响应，停止对应 run 或从最近 checkpoint 有界重启；重放必须幂等，禁止重复追加记忆/重复 step。 |
| 队列阻塞/请求丢失 | `Queue.get()`、Condition wait 以 1 秒轮询且没有请求级 deadline；客户端 HTTP 重试五次后只抛 `ValueError` | 每个请求有 deadline、cancel、attempt、terminal reason；超时转死信并排除 late reply；队列容量/年龄达到阈值时 fail-fast，不无限积压。 |
| 模型 provider/设备失败 | `_load_model()` 懒加载第三方模型；HTTP server 无鉴权、大小限制和异常响应边界 | provider 启动健康检查、版本/设备租约、错误分类、熔断和有界重启；输出必须经过 schema/shape/维度校验，失败返回失败状态而非空向量/空文本。 |
| 记忆保存中断 | 语义/情景记忆多文件写入；SemanticMemory 后台 daemon 保存；EpisodicMemory 的 JSON 与 FAISS/embedding 派生物不是同一事务 | 事实文件先提交，索引后提交；manifest 标记阶段；重启先校验摘要/版本，再只从事实重建派生物；保存线程必须可等待，不能以“线程已启动”算成功。 |
| evaluator 输入缺失/脏数据 | `evaluate.py` 对缺失 step 捕获异常并 `continue`（`evaluate.py:29-35,96-102`），LQ/IB 还对 config 字典 `pop` 并写 `results.json` | 缺失率、乱序、重复 step、agent 数量和 config hash 必须是硬校验；默认失败而不是静默跳过。评估先复制/冻结输入，结果写独立目录并附输入/代码/指标版本摘要。 |
| 评估/重跑重复 | `evaluate_IB/LQ` 都直接写 `results.json`；LQ 会修改从 JSON 读出的 config 字典 | 评估 idempotency key = `run_id + evaluator_version + input_manifest_hash`；相同输入复用同一结果，不同输入不能覆盖旧结果；重复运行不得改变仿真事实。 |
| 旧索引/维度不兼容 | `EpisodicMemory` 固定文本 index 维度为 generator embedding_dim、图片 index 为 512；加载时重建/追加，未见 manifest 版本校验 | 维度、归一化、模型 id/version、事件计数必须入 manifest；不兼容时明确 `INDEX_REBUILD_REQUIRED`，重建后再开放检索。 |

### 13.6 防假绿：验收等级、反向场景和硬门禁

当前 `tests/test_model_manager.py` 的大部分用例验证 `ProcessChannel`、`ModelProcess` 和 `ModelManager` 的逻辑，很多请求由线程/MagicMock 模拟；标记 `integration` 的真实 CLIP/RAM 等测试需要模型权重和运行中的模型进程（`tests/test_model_manager.py:407-520`），因此“测试文件存在”或“默认 pytest 通过”都不能证明 Ella 端到端可运行。当前没有看到 Agent 行为、记忆持久化、仿真动作或 Controlled Finals 指标的根级回归矩阵。

后续验收必须分栏记录：

| 等级 | 必须证明的事实 | 不能替代它的证据 |
|---|---|---|
| A 源码存在 | 入口、类、函数和路径存在，源码行号可回读 | README、论文、函数名、未执行脚本 |
| B 测试存在 | 测试覆盖的断言对象与边界真实存在 | 测试文件名、测试注释、`skip` |
| C 静态/逻辑通过 | 能在无外部权重环境运行的真实测试、py_compile、契约检查 | Mock 了被测 worker/provider、只测返回类型 |
| D 真实链路通过 | 独立 run 下真实进程、真实队列、真实模型/provider 或明确的受控替身，产生 manifest、checkpoint、step 和结果 | 子代理回信、历史 output、打印“started/finished” |
| E 故障恢复通过 | 强杀进程、队列超时、provider 异常、磁盘半写、索引损坏后，重启恢复且结果/证据可对账 | 只覆盖正常路径或把异常吞成 `None` |

硬门禁：

1. 运行前生成唯一 run manifest；每个 agent、队列请求、模型调用、记忆事件和评估结果都能反查到 `run_id`/owner。
2. 完成条件同时满足：所有进程 terminal、所有请求 terminal、checkpoint/manifest 校验通过、预期 Agent/step 覆盖率达标、记忆事实与派生索引对账、评估输入完整、无孤儿 pid/queue/temp 文件。
3. 任何 `skip`、缺 provider、缺权重、超时、异常被吞、评估静默缺 step、仅 mock 的路径只能标记“未验证/失败”，不能升级为“通过”。
4. 反向测试至少包含：Agent SIGKILL、模型 worker 非零退出、队列请求超时/重复/late reply、模型输出错误 shape/维度、磁盘写入中断、索引删除后重建、重复评估和错误配置 hash。
5. 真实替身也必须经过相同进程/队列/文件/内存生命周期；禁止在单元测试里把 `ModelProcess` 换成函数后宣称模型链路通过。

### 13.7 后续底座落点结论

- **吸收**：运行清单与唯一身份、进程/进程组监督、队列信封/批处理/死信、模型能力网关、provider 隔离、原子文件/manifest/checkpoint、事实与派生索引分离、通用评估 runner、分级验证与故障证据。
- **升级现有能力**：把现有通用进程/资源/异步任务底座补上进程组回收、请求 deadline/幂等/取消、退出码、队列排空、文件 manifest、索引 rebuild 和防假绿门禁；不要为 Ella 单独新建第二套模型队列或任务系统。
- **必须隔离**：Genesis/ViCo 仿真、Ella/GenAgent 策略和 prompt、Agent 状态语义、RAM/DINO/SAM/CLIP 的视觉与坐标链、Embedding 维度与 FAISS 索引、各 LLM provider 凭据/输出协议、Semantic/Episodic 两套记忆域、IB/LQ/诊断指标、HTTP pickle 兼容服务。
- **暂不抽取**：`retrieve_knowledge()` 空实现、`save_memory_incremental()` 中与当前事件 JSON 字段不一致的实验性路径、论文“严格不覆盖旧记忆”的强不变量；这些应先完成源码/测试/运行证据闭环，不能包装为通用底座。
- **唯一调用链约束**：未来接入平台时只能是“Ella 项目适配层 → 通用 Agent/模型/文件/评估底座 → 受管 provider”，禁止入口脚本直连第三方、Agent 旁路写评估结果、评估器改写仿真事实、索引反向写事实文件。

## 14. 后续证据边界与后续复核

当前核对仍为源码取证与架构映射，未安装依赖、未启动 Genesis/ViCo、未启动真实模型进程、未执行长时仿真、未强杀/恢复进程、未做磁盘损坏注入，也未把任何上述“要求”写成已实现平台能力。后续若进入底座实施，必须先冻结 run/queue/model/file/memory/evaluation 契约，再按独立资源 owner 分工作包，最后用真实子进程和故障注入验证；不得以本节的设计裁决替代运行证据。

## 15. 后续收口：记忆抽取、画像/状态、模型、调用链与验证

本节只记录对当前源码逐条回读后的后续结论；它不把提示词要求、fallback 日志、测试文件或后续底座建议升级为运行事实。旧 `细探-Ella.md` 继续保留，后续架构事实只维护本文件。

### 15.1 两套记忆实现必须分开看

| 实现 | 实际调用者 | 事实/索引形态 | 收口结论 |
|---|---|---|---|
| `agents/memory.py` | `agents/ella.py:11,67-80` 的 `EllaAgent` | `SemanticMemory`：`knowledge.json`、`knowledge_feature.pkl`、对象/区域/体素文件；`EpisodicMemory`：`experience.json` + 运行时 FAISS 文本/图像索引 | 这是当前 Ella 主链；语义事实与情景事件是两个 owner，不能合并成一个通用“记忆表”。 |
| `agents/gen_agent_memory.py` | `agents/gen_agent.py` 的 Generative Agents 风格分支 | `experience.json` + `experience_embedding.pkl`；事件 id 为 `node_<n>`，embedding 放在内存/缓存而不作为正常 JSON 字段 | 这是并存的历史/另一 Agent 实现；其 `EventInstance`、embedding 缓存、检索权重与当前实现不兼容，不能用其中一套测试替代另一套。 |

两套实现都暴露 `retrieve_knowledge()` 空实现（当前 `agents/memory.py:147-148`；旧实现 `agents/gen_agent_memory.py:126-127`）。因此“有情景检索”不能推导出“有通用语义知识检索”；当前语义知识主要靠名称精确查找 `get_knowledge()`，视觉识别另走特征相似度。

### 15.2 记忆抽取的真实链路与模型边界

```text
VicoEnv observation
  → Agent.act() 更新当前 pose/time/place/vehicle/cash/held_objects
  → EllaAgent._process_obs()
      ├─ SemanticMemory.update(obs)
      │    ├─ GT segmentation → ObjectBuilder.add_frame_with_gt_seg()
      │    ├─ 非 GT 且到 detect_interval → RAM → DINO → SAM → CLIP → ObjectBuilder
      │    ├─ Builder/VolumeGridBuilder.add_frame()
      │    └─ 新对象按 CLIP 相似度 > 0.75 复用名称，否则 `<tag>_<idx>` 新建事实
      ├─ speech/环境事件 → EpisodicMemory.add_memory()
      ├─ 新对象或 react_freq 到期 → 保存 RGB、caption/对象描述 → add_memory("observation")
      └─ action 失败 → 只把最近同一事件时刻的 action 描述追加 “But failed.”
  → EllaAgent._act()
      → latest/retrieved episode → LLM 选择反应模式
      → conversation / schedule / commute / pick 等动作
      → VicoEnv.perform_action()/step()
```

证据与边界：

1. **视觉抽取不是纯事实读取。** `SemanticMemory.update()`（`agents/memory.py:187-250`）每帧更新场景图；只有 `detect_interval > 0` 且满足帧号/图像变化才调用开放词汇检测，GT 分割则直接走 `add_frame_with_gt_seg()`。非 GT 路径只对 `AGENT_TAGS` 做 `knowledge_feature` 相似度匹配，阈值为 `0.75`（`agents/memory.py:220-240`）；未匹配对象会创建名称，但 `update_with_new_knowledge()` 只写 `object_idx` 等字段，并不会把新对象的 CLIP 特征加入 `knowledge_feature`。因此新对象进入事实文件不等于进入后续视觉 gallery。
2. **对话抽取是唯一明确的 LLM→语义事实写入路径。** `end_conversation()` 先生成一条未经结构化校验的摘要事件，再在聊天长度大于 1 时调用 `generate_new_knowledge()`（`agents/ella.py:817-825,939-960`）。提示词只要求“JSON object which is an array”，代码把结果按 `item["name"]` 建字典；字段除 `location` 的极弱类型检查外可任意写入，重复名称会在 Python 字典构造时覆盖，未做来源、置信度、冲突、版本或撤回记录。抽取失败返回 `None`，不会写入候选或失败事件。
3. **LLM 不是权威状态机。** `generate_react_mode()`、`generate_commute_plan()`、`generate_adjusted_schedule()`、`generate_hourly_schedule()` 和 `generate_motion_schedule()` 的输出均由手写 JSON 解析及各自 validator/白名单约束；没有统一 schema、版本号或错误码。反应模式仅允许四个字符串，环境交互还要求 `pick` 与对象名（`agents/ella.py:1007-1035`）。
4. **提示词要求与实际 parser 不一致。** `parse_json()` 只有看到 ```json 围栏才直接解析；即使模型返回合法裸 JSON，也会再发一次纠正请求，最多两次尝试（`agents/ella.py:1202-1243`）。调用方的失败策略各不相同：知识抽取返回 `None`，utterance 返回 `None`，反应模式回退为继续当前活动，通勤回退步行，动作计划回退等待/原计划，日计划回退随机默认模板或在占位符残留时 `exit()`。
5. **事件排序与索引有隐含前提。** `EpisodicMemory.add_memory()` 用 `str(len(self.experience))` 作 id 并把事件追加到 `index_time`（`agents/memory.py:432-454`），没有强制 `event_time` 单调；但 `retrieve_memory_by_time()` 用 `bisect_left`，因此乱序事件会破坏精确时间/最近事件语义。`event_expiration` 被持久化但检索没有过期过滤。
6. **检索会修改内存状态但不立即落盘。** `retrieve()` 更新命中事件的 `event_last_access_time`（`agents/memory.py:518-520`），没有随后 `save_memory()`；失败动作的 `update_memory_last_action()`（`agents/memory.py:572-581`）也没有保存。崩溃或未再触发保存时，recency 与失败标记会丢失。
7. **空库是未防护边界。** `retrieve()` 对空 `experience` 仍进入 `extract_recency()`，而 `vico/vico/tools/utils.py:149-162` 对空数组调用 `np.min/np.max`；因此公开调用检索空库不能标记为已恢复，必须单独测试。
8. **删除/清空不是 append-only。** `remove_memory()`、`clear_memory()` 删除事实但没有同步重建 FAISS、`keyword2index`、`index_time`、`valid_img_index`；删除后旧索引仍可能返回错误位置，且下一个 `event_id = len(experience)` 可能复用历史 id。`save_memory_incremental()` 还读取 `tojson()` 中不存在的 `event_text_ft`（`agents/memory.py:424-430`），属于未接通的实验性路径。

### 15.3 画像、可变状态与 checkpoint 边界

`scratch.json` 同时承载静态画像和运行状态。样例 `vico/vico/assets/scenes/NY/agents_num_15_robot/Zara Williams/scratch.json:1-46` 包含姓名、年龄、innate/learned/currently/lifestyle、groups、daily requirement、living place，以及 `curr_time`、schedule、held objects 等字段；`seed_knowledge.json` 则保存其他 Agent、地点、建筑与视觉外观的初始知识。`get_character_description()`（`agents/ella.py:1334-1359`）把画像字段、群组、持有物和现金拼入提示词，属于 prompt context，不是独立画像数据库。

状态流转和恢复实际如下：

| 状态类别 | 来源/写入 | 重启后结论 |
|---|---|---|
| 当前时间、地点、车辆、持有物 | `Agent.act()` 从 observation 更新；`Agent.save_scratch()` 写回 `scratch.json`（`vico/vico/agents/agent.py:51-71,89-94`） | 有原子替换写入，但没有版本/step/hash；依赖文件最后一次写成功。 |
| 小时计划、通勤计划/索引、上车时间、聊天 buffer | `EllaAgent.save_scratch()` 先扩展 scratch，再调用父类（`agents/ella.py:1400-1406`） | 这些字段可恢复；不保证与记忆事实同一时刻提交。 |
| `last_react_time`、`last_action`、`react_mode`、运动计划索引、`SemanticMemory.num_frames/explored` | 只存在 Python 对象；`last_react_time` 初始化时从最后事件时间推导 | 不能完整恢复；尤其 `explored` 未进入语义文件，重启可能重复探索；帧号恢复也没有从持久化事实重建。 |
| `physical_health`/`mental_health` 等环境配置字段 | `config.json`/`agent_infos` 可见，但 `Agent` 只保留 cash 与 held objects（`vico/vico/agents/agent.py:31-38`） | 不能称为 Ella 画像状态已被 Agent 记忆管理；需以 ViCo 环境状态为准。 |

因此当前 checkpoint 是“多份文件的 best effort 快照”，不是 `obs → 记忆事件 → scratch → step` 的事务提交；恢复只能保证部分字段可读，不能保证动作、事件、索引和画像修改具有同一 step 一致性。

### 15.4 模型与存储的实际契约

#### 模型/Provider 表

| 层 | 源码事实 | 当前失败/一致性缺口 |
|---|---|---|
| `ModelManager` | `tools/model_manager/__init__.py:8-68` 注册 `ram/dino/sam/clip/embedding/completion` 客户端；`odm.py:97-98` 以 `local=True` 启动本地进程和 `ProcessChannel` | `get_generator()` 以 `lm_id` 单键缓存（`__init__.py:85-88`），忽略 `lm_source`、temperature、top_p 等；同一 id 在不同 provider/参数下可能复用第一份 `Generator`。 |
| `Generator` | `tools/generator.py:27-169` 支持 OpenAI/Azure/HuggingFace/LLaVA/VLA/Google/local；`generate()` 分发 provider，embedding 有指数退避与 cwd 下 `cache_<lm_id>.pkl` | OpenAI/Azure 失败在 `openai_generate()` 外层捕获后返回空字符串（`generator.py:272-276`），调用方难以区分失败与有效空输出；embedding cache 跨 run/provider 共用，模型版本不入 key。源码还在日志中打印 API key（`generator.py:69-103`），属于凭据泄露风险。 |
| 进程通道 | `ProcessChannel` 按 URL 建 7 个无限容量 `mp.Queue`，批处理最多 4 个；客户端请求 id 为 `random.randint()`（`server.py:38-94`、`client.py:27-37`） | `get_c()` 无 deadline/取消；HTTP `requests.post()` 无 timeout；随机 id 无碰撞/重试幂等契约。 |
| 本地模型 worker | `ModelProcess.process()` 按路径懒加载 RAM/DINO/SAM/CLIP/vLLM（`server.py:192-215`） | worker 异常未包成失败响应；崩溃后请求留在队列且客户端无限等待。无 CUDA 时 `ModelManager.init()` 只启动 `ram/dino/sam/clip` 子集（`__init__.py:35-38`），但 `local` Generator 仍会把 embedding/completion 请求送入同一通道，CPU/MPS local LLM/embedding 路径因此没有源码级可达保证。 |
| HTTP 兼容服务 | `server.py:24-36` 使用 POST body `pickle.loads()`/返回 pickle，默认 localhost | 没有鉴权、大小/版本/路径白名单、请求 timeout 或异常 envelope；只能视为受信任本机实验适配器。 |

#### 持久化与派生索引表

| 资源 | 真实写入 | 可恢复性等级 |
|---|---|---|
| 语义事实 | `knowledge.json`、`knowledge_feature.pkl`；对象 builder、region JSON、当前地点 `volume_grid.pkl` 由 `SemanticMemory.save_memory()` 异步写（`agents/memory.py:150-185`） | `atomic_save()` 对已存在文件写 `.tmp` 后 `os.replace()`，但新文件直接写、没有 fsync/manifest；daemon thread 不 join，崩溃时多文件可能不同步。 |
| 情景事实 | `experience.json` 保存 `EventInstance.tojson()`；文本/图片 FAISS 仅在内存中，启动时根据 JSON 重新 embedding/图片推理（`agents/memory.py:402-415`） | JSON 是事实源，索引可重建；但没有模型 id/version、维度、归一化、事实版本 manifest，重建失败或图片路径失效没有明确状态码。 |
| 图片/日志/LLM 缓存 | RGB 图写入 `episodic_memory/img_*.png`；`Generator` 写 cwd `chat_raw.jsonl` 与 `cache_<lm_id>.pkl` | 不受 run owner/manifest 统一管理，跨实验目录或并发 run 可能串写；图片读取使用 `Image.open()` 但调用方没有显式上下文关闭。 |
| 增量路径 | `save_memory_incremental()` 不是当前主路径，且引用缺失字段 | 不可作为恢复方案或验证证据。 |

### 15.5 端到端调用链（实际 owner）

```text
odm.py
  → 创建/续跑 output/.../curr_sim 并读取 config.json
  → global_model_manager.init(local=True)
  → VicoEnv(...)
  → get_agent_cls("ella") → EllaAgent
  → AgentProcess × N（可单进程或 multiprocessing）
  → AgentProcess.update(obs) → AgentProcess.act()
  → Agent.act(obs)
      → EllaAgent._process_obs(obs)
          → SemanticMemory.update()
              → ObjectBuilder/Builder/VolumeGridBuilder
              → knowledge/object/region/volume 文件
          → EpisodicMemory.add_memory()
              → Generator.get_embedding()/CLIPClient
              → experience.json + 运行时 FAISS
      → EllaAgent._act(obs)
          → retrieve_latest_memory()/retrieve()
          → Generator.generate(prompt, img?, json_mode=False)
          → parse_json()/领域 validator/fallback
          → action dict
  → VicoEnv.step(agent_actions) / perform_action()
  → Agent.save_scratch() + AgentProcess.log_step_agent_info() 写 scratch/steps
  → 循环结束后 AgentProcess.close()、VicoEnv.close()
```

模型通道实际由 `odm.py:149-153` 注入 `global_model_manager._channel`，`EllaAgent.__init__()` 又在每个 Agent 中调用 `set_channel()`（`agents/ella.py:35-41`）。这说明 channel 是进程级共享实现细节，不是显式的 Agent 请求契约；多个 Agent 依赖同一个 `ProcessChannel`，但没有 run_id/agent_id/request deadline 可用于对账。模型、记忆、Agent、环境和评估的 owner 也没有统一生命周期协调器。

### 15.6 失败恢复矩阵（源码已实现 vs 当前核对未证）

| 故障 | 当前源码行为 | 后续判定 |
|---|---|---|
| LLM 网络/Provider 异常 | OpenAI/Azure 重试后返回 `""`；Gemini 重新抛出；其他 provider 多数不统一捕获 | **部分 fallback，未形成失败契约**；空字符串可能继续进入 parser 或领域默认值。 |
| JSON 围栏缺失/JSON 非法 | `parse_json()` 追加一次“只输出围栏 JSON”请求，再失败返回 `None` | **有界重试已存在**，但无 schema/字段错误码、无请求关联、未证明所有调用方都安全处理 `None`。 |
| Agent 业务异常 | `AgentProcess.run()` 捕获后把 action/utterance 置为 `None`，继续队列循环（`agent.py:148-180`） | **异常被降级为空结果**；没有结构化 error envelope、checkpoint 回滚、父侧重启或 step 失败标记。 |
| 上一步动作 FAIL | `_process_obs()` 调 `update_memory_last_action()` 后直接访问 `self.last_action["type"]`（`ella.py:114-121`） | **反向场景未安全**：`last_action is None` 时可能二次异常；“But failed.” 也未立即保存。 |
| 模型 worker 崩溃/队列无响应 | `ModelProcess.run()` 无异常边界；`get_c()`/`get_s()` 以 1 秒轮询且无终止条件 | **未恢复**；调用方可能永久阻塞，不能区分 provider failure、worker death 与慢请求。 |
| 记忆写入中断/宿主退出 | `SemanticMemory.save_memory()` 启 daemon thread；多文件分别写，只有单文件级替换；无 manifest/flush/join | **部分原子写，整体不可对账**；不能证明最后一个事件、scratch、索引同一版本。 |
| 索引损坏/维度或模型变更 | 启动从 JSON 重新计算 embedding/CLIP，固定文本维度来自 `Generator.embedding_dim`，图片固定 512 | **有重建意图，无兼容状态机**；没有 manifest、版本检查和显式 `REBUILD_REQUIRED`。 |
| 空库、乱序事件、删除后检索 | 空库触发归一化边界；`bisect` 假定有序；删除不重建辅助索引 | **未验证且存在源码级风险**。 |
| 日计划/通勤默认分支 | 日计划失败随机选择地点；占位符残留直接 `exit()`；通勤失败回退 walk，但末尾索引可能越界 | **业务 fallback 不等于恢复**；没有 run 级失败原因与可重放输入。 |
| 进程关闭 | `ModelManager.close()` terminate + `join(5)` 并 shutdown channel；`AgentProcess.close()` 只 terminate，不 join/关闭队列 | **best effort**；未验证进程组、孤儿进程、未消费消息、后台保存线程和临时文件均清零。 |

### 15.7 资源生命周期收口

| 资源 | 创建/持有者 | 正常释放 | 失败/取消/崩溃缺口与验证要求 |
|---|---|---|---|
| Agent Python 状态与 `scratch.json` | `AgentProcess` 子进程持有 `EllaAgent`；Agent 自己写 scratch | 每个 `act()` 结束调用 `save_scratch()` | 没有版本/提交确认；进程强杀不能保证最后一次 scratch 与记忆一致。需验证从最后完整 checkpoint 重启且不重复追加事件。 |
| 语义场景图、对象、体素与区域 | `SemanticMemory` 持有当前 `Builder`、`ObjectBuilder`、可选 `RegionBuilder`；地点切换时保存旧地点体素 | `save_memory()` 写当前事实/派生文件 | daemon 保存线程无 join；当前地点与其它地点写入不是同一事务；需验证崩溃后 JSON 可读、临时文件可清、体素/对象计数可重建。 |
| 情景事件与 FAISS | `EpisodicMemory` 持有 `experience`、倒排、`index_time`、文本/图像 index | JSON 保存；FAISS 关闭时无显式释放，重启重建 | 删除、过期、失败标记、检索 last-access 不同步；需验证事实计数、index `ntotal`、有效图片行映射、维度与模型摘要一致。 |
| PIL 图像、NumPy/Torch payload | Agent 写 PNG；模型客户端跨进程 pickle 并转换 CPU/device | 依赖 Python 引用/进程退出；未见统一 context/内存租约 | 图片句柄、队列复制、GPU/CPU 内存无上限/水位/取消协议；需验证大图、队列积压、late reply 不写入错误 run。 |
| ModelProcess、模型权重、GPU/MPS 上下文 | `ModelManager.init(local=True)` 启动 worker；worker 懒加载模型 | manager terminate/join；channel shutdown | worker 异常、vLLM/CUDA 初始化失败、非零退出没有父侧诊断；需验证 PID、退出码、显存/模型上下文、队列/Manager 进程均回收。 |
| HTTP pickle server、凭据与 cwd cache | `Generator`/`ModelClient` 持有 client；server 反序列化不可信 body | 依赖进程结束；无统一 close/timeout | 不能进入公共服务；需限制 localhost、尺寸/版本、请求超时、异常 envelope，并禁止日志写 API key。 |

### 15.8 后续验证等级与实际证据

| 等级 | 当前核对能证明的事实 | 当前核对不能声称的事实 |
|---|---|---|
| A 源码存在 | 已读取 `agents/memory.py`、`agents/ella.py`、`gen_agent_memory.py`、`generator.py`、`tools/model_manager/*`、`vico/vico/agents/agent.py`、`odm.py`、提示词与样例 `scratch/seed_knowledge`；路径和行号已写入本节 | 论文/README 的“终身”“不覆盖”不能替代实现证据。 |
| B 测试源码存在 | `tests/test_model_manager.py` 覆盖 `auto_batched`、`ProcessChannel`、设备选择、client 注册/关闭及标记为 integration 的真实视觉测试 | 测试文件存在、mock worker round-trip、`skip` 或 marker 不等于端到端通过；没有 Ella 记忆/画像/恢复回归矩阵。 |
| C 静态检查 | 当前核对可执行无写入的 Python AST/Markdown 结构检查；结果在第 16 节回写 | 不把 AST 通过升级为依赖可导入、真实模型可加载或语义正确。 |
| D 真实链路 | **未验证**：没有安装依赖、启动 Genesis/ViCo、模型进程、Provider、长时仿真或真实记忆恢复 | 不声称实验已跑通、指标已产生、FAISS/模型形状已在现场成立。 |
| E 故障恢复 | **未验证**：没有强杀 Agent/ModelProcess、注入网络/磁盘/索引故障、检查孤儿资源 | 代码里的 `try/except`、`terminate()`、fallback 日志不能算恢复通过。 |

当前核对收口的最小硬门禁为：先证明 `experience.json`/`knowledge.json` 是事实源，再证明索引可由同一版本事实重建；每个模型调用有有限等待和终态；每个 Agent checkpoint 带 step/run 身份；正常、业务失败、取消/超时、宿主崩溃四种终态都能读回资源现场。当前源码尚未满足这些门禁，故结论只能是“研究实现的源码链路已厘清，生产级恢复未闭环”。

### 15.9 后续裁决

- **吸收**：Ella 将语义事实、情景事件、视觉/文本派生索引分域；对话摘要与知识抽取是两类不同产物；LLM 输出必须经过领域 parser/validator/fallback；模型调用应由能力注册表和受管进程承载；`atomic_save()` 可作为单文件替换的局部模式。
- **降级**：论文/旧细探中的“非参数记忆不覆盖旧记忆”降级为研究目标，不是当前工程不变量；当前代码存在 `remove_memory()`、`clear_memory()`、失败事件原地修改和语义字段覆盖。
- **待核**：真实模型/Provider 形状、FAISS 重建、跨日恢复、空库/乱序/删除检索、强杀/超时/取消、CPU/MPS local 路径、评估重复运行，均需隔离环境实测；当前核对不生成运行结果。
- **必须隔离**：`agents/memory.py` 与 `gen_agent_memory.py` 两条记忆实现、Ella 与 GenAgent 两套画像/状态 schema、ViCo 环境状态与 Agent scratch、模型 provider/cwd cache/凭据、HTTP pickle 兼容层，不得通过“同名 Memory/Generator”合并。

## 16. 后续现场验证记录

当前核对在项目根执行了不导入第三方依赖、不启动服务、不写入 Python 字节码的静态检查：

```text
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
import ast
files = [
  'agents/memory.py', 'agents/ella.py', 'agents/gen_agent_memory.py',
  'tools/generator.py', 'tools/model_manager/__init__.py',
  'tools/model_manager/client.py', 'tools/model_manager/server.py',
  'vico/vico/agents/agent.py', 'odm.py', 'vico/vico/tools/utils.py',
]
for rel in files:
    ast.parse((Path('.') / rel).read_text(), filename=rel)
PY
```

现场结果：`AST_OK 10`；`ARCHITECTURE.md` 非空；存在文本流程图；存在“后续收口”章节；旧 `细探-Ella.md` 仍存在。该结果只证明 10 个源码文件可被 Python AST 解析及文档基本结构存在，不证明依赖导入、模型加载、真实队列、ViCo 仿真、记忆检索或故障恢复。

当前核对没有执行 `pytest`：当前核对未安装依赖、未准备模型权重、未启动服务，且任务边界是源码核对与文档收口；测试文件存在仍按 B 级记录。Git 状态在修改前后都为 `master...origin/master`，未跟踪项均为既有的 `ARCHITECTURE.md` 与 `细探-Ella.md`；未删除旧细探、未修改源码/依赖/配置/测试/README、未提交 Git。

## 17. 本轮现场收口记录（2026-08-22）

| 项目 | 现场证据 | 结果 |
|---|---|---|
| 远程同步 | `git fetch origin --prune`、`git pull --ff-only` | `Already up to date` |
| 当前提交 | `git rev-parse HEAD` | `f29694ad44ce7976ccb34c82a599803e7d325f35` |
| CodeGraph | `codegraph status`、`codegraph sync` | 416 files / 8,058 nodes / 16,910 edges；Python 382、C++ 17、YAML 15、C 2 |
| 文档行数 | `wc -l ARCHITECTURE.md` | 当前超过 500 行 |
| 差异检查 | `git diff --check -- ARCHITECTURE.md` | 本轮执行退出码 0 |

本轮严格未使用 MCP，只使用 shell、git、CodeGraph CLI 和源码静态证据。文档已覆盖事件/时间图、语义与情景记忆、混合检索、模型通道、Agent/ViCo API、进程队列、文件/FAISS/视觉资源、失败/取消/恢复矩阵、测试与部署边界；源码 checkout 未改，仅更新平台研究文档。

未验证项：依赖安装、pytest、Genesis/ViCo 启动、真实 LLM/视觉模型、FAISS 重建、HTTP pickle 服务、并发/超时/客户端断连、强杀 ModelProcess/Agent、GPU/MPS 资源回收、跨日恢复和评估 benchmark。静态 AST 或测试文件存在不等于运行通过。
