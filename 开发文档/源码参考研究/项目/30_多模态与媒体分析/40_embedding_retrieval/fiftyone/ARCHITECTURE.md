# FiftyOne 架构建档

> 项目：FiftyOne（Voxel51）
>
> 本文是本地源码参考库的架构事实档案，不是生产接入方案。结论以当前工作树源码、README、依赖声明、测试与远程版本探针为准；源码标识保留原文。

## 1. 项目定位

FiftyOne 是一个 Python 视觉 AI 数据集工具，围绕“数据集组织 → 标签/媒体管理 → 可视化探索 → 模型推理与 embedding → 相似度检索/可视化 → 评估与数据质量改进”形成闭环。核心使用方式是：在 Python 中创建或加载 `Dataset`，通过 `Sample`、字段和 `Label` 建模数据，再由 `Session` 启动 FiftyOne App；App 通过 Starlette/GraphQL/HTTP 路由读取和变更数据。

- 上游项目：`https://github.com/voxel51/fiftyone`
- 许可证：Apache-2.0（根 `LICENSE`；README 徽章与 `setup.py` 均声明 Apache）
- 当前本地版本声明：`setup.py:13` 的 `VERSION = "1.21.0"`
- Python：`setup.py:124` 要求 `>=3.10`；README 声明支持 Python 3.10–3.13
- 入口：`setup.py:123` 注册 `fiftyone=fiftyone.core.cli:main`
- 主数据库：MongoDB，通过 `mongoengine`/`pymongo`/`motor` 访问；本地发布包 `fiftyone-db` 携带平台相关 `mongod`
- Web 服务：Python Starlette 服务，GraphQL 使用 Strawberry；App 是 `app/` 下的 Yarn workspace monorepo

## 2. 总体架构

```text
用户 Python / Notebook / fiftyone CLI
              │
              ▼
      fiftyone.__public__ 公共 API
              │
       ┌──────┴─────────────────────────┐
       ▼                                ▼
 Dataset / Sample / Label / View     Session / Client
       │                                │
       ├─ SampleCollection + ViewStage  └─ App 状态与事件
       ├─ ODM Document / Field                │
       ├─ MongoDB collections                  ▼
       ├─ Model inference / embeddings   Starlette App Server
       ├─ Evaluation / Brain runs        ├─ HTTP routes
       └─ Dataset Zoo / import-export    ├─ GraphQL Query/Mutation
                                         ├─ media/static/plugins
                                         └─ notification lifecycle
              │
              ▼
      app/packages/* React + TypeScript UI
              │
              ├─ state / relay / operators / plugins
              ├─ looker / looker-3d / video-annotation
              ├─ embeddings / embeddings-v2 / similarity-search
              └─ annotation / spaces / spotlight / tiling
```

### 2.1 分层职责

| 层 | 主要目录/符号 | 职责 |
|---|---|---|
| 公共 Python API | `fiftyone/__init__.py`、`fiftyone/__public__.py` | 加载配置、初始化日志与 user agent，并集中导出 `Dataset`、`Sample`、字段、标签、模型、评估、`launch_app` 等稳定入口 |
| 数据集领域层 | `fiftyone/core/dataset.py`、`core/collections.py`、`core/view.py` | 管理数据集、样本集合、视图和视图操作；`Dataset` 继承 `SampleCollection` |
| 数据模型层 | `fiftyone/core/sample.py`、`core/labels.py`、`core/fields.py`、`core/frame.py`、`core/groups.py` | 媒体样本、视频帧、标签、字段 schema、分组媒体与动态字段 |
| ODM/持久化层 | `fiftyone/core/odm/*`、`core/odm/database.py`、`core/migrations/*` | MongoEngine 文档、字段映射、数据库连接、集合命名、迁移与兼容 |
| 处理/检索层 | `core/models.py`、`core/stages.py`、FiftyOne Brain 依赖、`plugins/panels/similarity_search` | 模型推理、embedding 生成、Mongo 聚合视图、相似度查询与可视化运行记录 |
| 服务层 | `fiftyone/server/app.py`、`server/query.py`、`server/mutation.py`、`server/routes/*` | Starlette 生命周期、GraphQL schema、HTTP API、静态资源与插件资源 |
| 前端层 | `app/package.json`、`app/packages/*` | React/TypeScript/Vite/Vitest App；通过 Relay、state、事件和专用组件消费后端协议 |
| 扩展层 | `plugins/*`、`fiftyone/operators/*`、`fiftyone/utils/*`、`fiftyone/zoo/*` | 插件/Operator、模型与数据集集成、导入导出、Dataset Zoo/Model Zoo |

## 3. 关键运行流程

### 3.1 初始化与公共 API

`fiftyone/__init__.py:25` 使用 `pkgutil.extend_path`，允许多个 `fiftyone.XXX` 包在同一环境中共存；随后 `__public__` 负责加载 `config`、`annotation_config`、`evaluation_config`、`app_config`，再导出领域对象。导入结束时 `fiftyone.core.logging.init_logging()` 初始化日志，并尝试注册 Execution Store clone hook。

公共接口集中在 `fiftyone/__public__.py`：

- 数据集：`Dataset`、`load_dataset`、`list_datasets`、`dataset_exists`、删除与默认名称工具
- 数据结构：`Sample`、`Frame`、`Group`、`Field` 及 `VectorField`
- 标签：`Classification`、`Detection`、`Segmentation`、`Keypoint`、`TemporalDetection`、地理标签等
- 处理：`apply_model`、`compute_embeddings`、`compute_patch_embeddings`
- 评估：分类、检测、回归、分割 evaluation config/results
- 视图：`DatasetView`、`ViewField`、`SortBySimilarity` 等 stages
- App：`launch_app`、`close_app`、`Session`

### 3.2 Dataset、Sample 与 View

`fiftyone/core/dataset.py:274` 的 `Dataset` 继承 `fiftyone.core.collections.SampleCollection`，并使用 `DatasetSingleton`；数据集按名称单例化。文档说明：原始媒体通常保存在文件系统，数据库保存样本、标签、字段和媒体路径。

`Dataset.__init__`（`core/dataset.py:309-351`）通过 `_create_dataset` 或 `_load_dataset` 获取 ODM 文档与 sample/frame document class，然后建立 annotation、brain、evaluation、run 等 LRU cache。`media_type` 决定媒体配置，视频数据另外初始化 frames 结构。

`Dataset`/`SampleCollection` 负责：

1. 创建/加载/删除和列出数据集；
2. 添加、更新、删除样本与帧；
3. 动态扩展或校验 sample/frame schema；
4. 通过 `ViewStage` 组合 `DatasetView`；
5. 聚合、分页、排序、过滤、标签选择、patch/frame/clip/trajectory 转换；
6. 保存 Brain/evaluation/run/saved view 等运行元数据。

`fiftyone/core/sample.py:44` 的 `_SampleMixin` 对视频的 `frames`、frame number 访问以及字段写入做专门处理；`Sample.add_labels`（`sample.py:150` 起）支持单个 Label、多字段 dict、sample-level labels 和 frame-level labels，并可应用 `confidence_thresh`、`classes`、schema expand/validate/dynamic 策略。

### 3.3 ODM 与 MongoDB

`fiftyone/core/odm/dataset.py` 保存 Dataset 的 schema 和 App 配置；`SampleFieldDocument`（`dataset.py:58`）把字段名、`ftype`、embedded document、subfield、嵌套 fields、数据库字段名、描述、只读状态和创建时间持久化。

`DatasetDocument` 位于 `fiftyone/core/odm/dataset.py:909`；sample/frame 文档在 `core/odm/sample.py`、`core/odm/frame.py`。字段实现集中在 `core/fields.py`，除标量字段外包括：

- `EmbeddedDocumentField`、`EmbeddedDocumentListField`
- `ReferenceField`
- `VectorField`（`fields.py:1428`）和 `ArrayField`
- 地理字段、mask、keypoints、frame number/support 等媒体专用字段

数据库连接由 `fiftyone/core/odm/database.py` 维护：`get_db_client()`（`database.py:485`）返回 Mongo client，`get_db_conn()`（`database.py:495-503`）按 `fo.config.database_name` 取得数据库，并按时区应用 codec options；异步 GraphQL context 通过 `get_async_db_conn()` 使用 Motor。集合名包含 `datasets`、`samples.*`、`frames.*`、`patches.*`、`clips.*` 等，生成数据集和孤儿集合清理逻辑也在该层。

### 3.4 模型推理与 embedding

`fiftyone/core/models.py:1019` 的 `compute_embeddings` 是 embedding 计算核心：

1. 将 Transformers、Ultralytics、SuperGradients 等模型转换为 FiftyOne `Model`；
2. 要求 `model.has_embeddings` 为真；
3. 校验 image/video/group 媒体类型与模型 `media_type`；
4. 根据模型能力选择单样本、批处理、Torch `DataLoader`、视频或视频帧路径；
5. 若给出 `embeddings_field`，自动在 sample 或 frame schema 中创建 `VectorField` 并保存；否则返回数组、带 `None` 的列表或按 sample ID 映射的帧 embedding；
6. `skip_failures` 控制单样本失败是抛错还是记录警告并继续。

`SampleCollection.compute_embeddings`（`core/collections.py:3965`）是公共对象方法，转发到 `fiftyone.core.models.compute_embeddings`。`compute_patch_embeddings`（`collections.py:4043`）针对 `Detection`、`Detections`、`Polyline`、`Polylines` 的 patch 计算 embedding，可写入 label attribute。

embedding 的“生成”和“检索索引”是两条边界：本仓库核心负责模型适配、embedding 存储和 view API；相似度索引由 `fiftyone-brain`（`setup.py:99`）及其 run config/results 承担。`sort_by_similarity`（`core/collections.py:8043`）要求先用 `fiftyone.brain.compute_similarity` 建立索引，查询可以是 sample/label ID、向量或 prompt，并返回 `DatasetView`。

### 3.5 App 会话与服务

`fiftyone/core/session/session.py:136` 的 `launch_app` 创建全局 `_session`；`Session.__init__`（`session.py:347` 起）初始化 context、解析 dataset/view、选择端口和地址、建立 `StateDescription`，再由 `fiftyone.core.session.client.Client.open` 启动或连接服务并注册事件监听器。一个进程只允许一个全局 App session；`close_app` 负责关闭它。

`fiftyone/server/app.py`：

- 以 `Starlette` 创建 `app`（`app.py:205`）；
- `schema = strawberry.Schema(mutation=Mutation, query=Query, ...)`（`app.py:112-117`）；
- 通过 `routes` 注册 HTTP endpoints；
- `/graphql` 使用 `GraphQL(schema)`；
- `/plugins` 与 `/` 使用静态文件挂载；
- `lifespan` 管理 Mongo change-stream notification service；
- 根据 `FIFTYONE_ALLOWED_ORIGINS` 配置 CORS，并设置 COOP/COEP headers 以支持多线程 WASM。

路由聚合在 `fiftyone/server/routes/__init__.py:43-75`，包括 `/aggregate`、`/events`、`/fiftyone`、`/frames`、`/media`、`/sort`、`/values`、`/sample`、`/groups`、`/plugins`、`/video-labels/*` 等，以及 legacy `/embeddings` 和 `/embeddings/v2`。

## 4. Embeddings v2 协议与检索数据流

`fiftyone/server/routes/embeddings_v2.py` 是前端高效探索 embedding visualization runs 的二进制协议。其关键契约在文件头注释与实现中：

- wire order 是 Brain run points 数组的规范顺序；点在该顺序中的位置作为 key；
- 二进制 header 为 16 字节 little-endian：`u32 magic "FOE1" | u16 version | u8 dtype | u8 width | u32 n | u32 flags`；
- geometry 使用 Float32 列；mask 使用 little bit-order packed bitmask；ID 使用 12-byte ObjectId；color 可追加 UTF-8 JSON meta tail；
- `/embeddings/v2/runs`：列出 visualization brain runs 及 ready、method、dims、fields、model、timestamp；
- `/embeddings/v2/run-info`：返回点数、维度、patch/points 字段和 timestamp；
- `/embeddings/v2/geometry`：按 wire order 分页返回坐标列；
- `/embeddings/v2/ids`：返回 point/sample identity，patch run 可区分 label IDs 与 sample IDs；
- `/embeddings/v2/color`：将 categorical/continuous color-by 数据一次聚合并用小型 LRU cache 复用；
- `/embeddings/v2/masks`：分别表达 view visibility 和 filter match，使用 flags 标记全可见/全匹配；
- `/embeddings/v2/lasso-stage`：将 polygon 或 wire-order indices 编译为 `$geoWithin`、`Select`、`MatchLabels` 或 `SelectBy` view stage；
- `/embeddings/v2/sample-info`：按 wire-order index 解析 hover card，样本已删除时返回 null media/field，而不是错误。

该协议的核心设计是“几何一次加载、过滤/视图变化只传 bitmask、身份按需解析”，适合大规模向量可视化；不能把它误当作通用向量数据库 API。

## 5. 前端架构

`app/package.json` 声明 Yarn 4.9.1 workspace，Node README 推荐 v22。主要脚本：`build`、`dev`、`dev:py`、`dev:wpy`、`typecheck`、`test`、`test:coverage`、`storybook`、`gen:schema`。

`app/packages/` 的实际子包包括：

- 基础状态与协议：`state`、`relay`、`events`、`command-bus`、`commands`、`core`、`utilities`；
- 主界面与渲染：`app`、`components`、`looker`、`looker-3d`、`lighter`、`flashlight`、`map`、`spaces`、`spotlight`、`tiling`；
- 数据与视觉功能：`embeddings`、`embeddings-v2`、`similarity-search`、`annotation`、`video-annotation`、`playback`、`aggregations`、`multimodal`；
- 扩展与集成：`plugins`、`operators`、`analytics`、`feature-flags`。

`app/README.md` 说明 App 使用 React/TypeScript 逐步迁移，状态主要经 Recoil/Recoil Relay selectors/hooks 流动；测试使用 Vitest，新增模块应有对应 test 文件并尽量达到完整覆盖。`app/packages/embeddings-v2/src/renderer/README.md`、`app/packages/embeddings/README.md` 和 `app/packages/similarity-search` 是继续研究前端向量体验的首要入口。

## 6. CLI、插件与扩展边界

### CLI

`fiftyone/core/cli.py:85-107` 注册命令：`quickstart`、`annotation`、`brain`、`evaluation`、`app`、`config`、`constants`、`convert`、`datasets`、`migrate`、`operators`、`skills`、`delegated`、`plugins`、`utils`、`zoo`、`labs`。CLI 复用公共 Dataset/App/Brain/Plugin 能力，不是另一套数据访问层。

### Operators 与 plugins

- `fiftyone/operators/*` 提供操作定义、类型、执行、delegated operation、store 和服务端 Operator routes；
- `plugins/operators/*`、`plugins/panels/*` 是仓库内示例/内置插件；`similarity_search` panel 以正负样本 embedding 的均值组合查询向量，并通过 delegated operation 执行；
- 插件静态资源通过服务端 `/plugins` 挂载，业务实现仍需遵守 FiftyOne 的 Dataset/View/Operator 边界；
- `fiftyone/utils/*` 和 `fiftyone/zoo/*` 负责外部模型、数据集格式、媒体、annotation 工具等适配，不应被误认为核心持久化模型。

### 包拆分

`package/README.md` 说明当前发行拆分为核心 `fiftyone` 与平台相关 `fiftyone-db`。顶层 `setup.py` 生成主 wheel；`package/db/setup.py` 按 Darwin/Linux/Windows 和机器架构选择 MongoDB 下载地址，构建平台 wheel。构建 `fiftyone-db` 可能下载 MongoDB，属于有外部副作用的发布步骤，本次未执行。

## 7. 测试与工程验证

测试说明见 `tests/README.md`：同时使用 `unittest` 与 `pytest`。

- `tests/unittests/`：行为单元测试，覆盖 Dataset、ODM、server routes、multimodal、视频、3D、operators 等；
- `tests/benchmarking/`：性能基准；
- `tests/intensive/`：模型、导入导出、视频/深度学习等重测试；
- `tests/isolated/`：必须独立 pytest 进程执行的测试；
- `tests/misc/`、`tests/no_wrapper/`、`tests/utils/`：兼容性、工具及特殊执行路径；
- `e2e-pw/`：Playwright 端到端测试，包含 App 多媒体、标签、sidebar、selection、3D 与截图快照。

CI 事实：`.github/workflows/test.yml` 使用 Node 22/Yarn workspace 测试 App，并使用 `tests/utils/pytest_wrapper.py` 执行 Python 测试及 isolated tests；`.github/workflows/build.yml` 组合 Python 3.10、Node 22、Yarn 4.9.1 构建 App 与 Python package。

本次仅做静态架构建档和版本/工作树检查，没有安装依赖、启动 MongoDB/App、运行构建或跑完整测试，避免改变只读源码参考库环境。

## 8. 依赖与配置事实

顶层 `setup.py:48-102` 的关键依赖分组：

- 基础/服务：`aiofiles`、`argcomplete`、`boto3`、`Jinja2`、`hypercorn`、`starlette`、`strawberry-graphql`、`sse-starlette`、`PyYAML`；
- Mongo：`mongoengine~=0.29.1`、`motor~=3.6.0`、`pymongo~=4.9.2`、`fiftyone-db>=0.4,<2.0`；
- 数据/数值：`numpy<3`、`pandas<4`、`scipy<2`、`scikit-learn<2`、`scikit-image<1`、`opencv-python-headless<5`、`Pillow>=12.2`、`matplotlib<4`；
- 内部包：`fiftyone-brain>=0.22.0,<0.23`、`voxel51-eta>=0.16.0,<0.17`；
- 多模态 extra：`multimodal-mcap` 固定 `protobuf==6.33.6`，`multimodal` 依赖该 extra。

配置由 `fiftyone.core.config` 加载，公共 API 在导入时生成 `fo.config`、`fo.app_config` 等对象。部署/集成时需重点审查 database name/address、App port/address、allowed origins、plugins dir、timezone、Mongo 版本和媒体文件路径；这些配置不是向量检索索引本身的替代品。

## 9. 目录地图（真实当前工作树）

```text
fiftyone/
├── fiftyone/       Python 核心库、ODM、模型、Zoo、服务端、插件与 CLI
├── app/            React/TypeScript App；Yarn workspace 与 packages/*
├── package/        fiftyone-db 打包支持与 MongoDB 平台 wheel
├── docs/           Sphinx/Napoleon 文档、API 生成和文档构建脚本
├── tests/          Python unit/intensive/isolated/benchmarking 等测试
├── e2e-pw/         Playwright 端到端测试与快照
├── plugins/        仓库内 Operators/Panels 插件
├── schemas/        GraphQL/multimodal 等 schema 相关资源
├── requirements/   test/docs/e2e/github 等依赖集合
├── tools/          开发辅助工具
├── .github/        CI、构建、发布与安全工作流
├── setup.py        核心 Python package 声明、版本、依赖、CLI entry point
├── pyproject.toml  setuptools build-system、Black、isort 配置
├── install.sh      Unix 源码安装/App 构建编排
├── install.bat     Windows 源码安装编排
└── README.md       定位、安装、quickstart、特性和官方文档导航
```

本地统计（排除 `.git`、`node_modules`、`__pycache__`、构建缓存）：根下约 5,449 个文件；其中 `app` 约 3,370、`docs` 约 1,030、`fiftyone` 约 394、`e2e-pw` 约 374、`tests` 约 181。该统计是当前磁盘快照，不是发行包文件数。

## 10. 版本与远程新鲜度

- 本地工作树：分支 `develop`，HEAD `893842038c7663af5bd4c0ba647a68a1386bb62f`，提交信息 `Merge pull request #8111 from voxel51/fix/all-tests-ghost-red-on-noop-runs`。
- 本地 `origin/develop` tracking ref 与 HEAD 一致；直接 `git ls-remote origin refs/heads/develop` 得到远程 `44fc620c07555cf8740b79a0309a5fc809a45961`，其提交信息为 `Merge pull request #8312 from voxel51/release-notes-1.21.1`，因此本地源码落后远程 develop，不能把本地 `VERSION = 1.21.0` 当作远程最新版本。
- 通过 `http://127.0.0.1:4780` 独立代理快照读取 `https://raw.githubusercontent.com/voxel51/fiftyone/develop/setup.py`，远程 `VERSION` 为 `1.22.0`；GitHub API 同代理因 rate limit 返回 403，未将 API 缺失字段写入结论。
- 远程 tag `v1.21.0` 指向 `50a17766561eb7d1379ff0de8d5d84654265737e`。
- 版本写作原则：后续引用必须明确区分“本地源码事实”“远程 develop 快照”和“release tag”，不要混写。

## 11. 可借鉴点、边界与风险

### 可借鉴点

1. `Dataset`/`SampleCollection`/`DatasetView` 将原始媒体、结构化标签、可组合查询阶段分开，适合作为媒体数据治理与检索平台的参考边界。
2. `compute_embeddings` 把模型适配、媒体类型校验、batch/DataLoader、失败策略和落库字段统一到一条可测试管线。
3. Embeddings v2 的 wire order、Float32 columns、bitmask 和 lazy identity 适合大规模可视化，不强迫每次交互传输完整 JSON 样本。
4. App 状态经 GraphQL/事件/前端 state 分层，后端路由、查询、mutation 与前端 package 有明确协议边界。
5. Brain/evaluation/run 元数据挂在 Dataset 上，便于追踪一次计算与其 view、模型、字段和结果。

### 重要边界/风险

- MongoDB 是核心运行前提；不能直接把 FiftyOne 的 ODM 当作关系型数据库模型迁移到平台。
- FiftyOne Brain、`fiftyone-db`、`voxel51-eta` 是紧版本耦合的内部依赖，不能只复制顶层 `fiftyone` 代码。
- `sort_by_similarity` 依赖 Brain 索引；embedding 字段本身不等于可检索索引。
- App/GraphQL/HTTP 协议、Python API、Mongo 文档和前端 Relay state 必须成套演进，单独复用某个 route 容易产生版本漂移。
- 模型推理可能触发 GPU/大内存/文件读取，`skip_failures=True` 会把失败变为 warning 与缺失项，调用方需保留可观测性。
- `package/db/setup.py` 构建可能下载 MongoDB 二进制；源码参考库不应在分析阶段执行安装或构建。
- 远程 develop 已明显领先本地快照；任何基于当前目录的结论都应绑定本地 commit。

## 12. 研究结论

FiftyOne 的核心不是单一 embedding 数据库，而是以 MongoDB 为持久化底座、以 Dataset/Sample/Label/View 为数据模型、以 Brain 为相似度/分析运行层、以 Starlette + GraphQL + React App 为交互层的视觉数据质量平台。对本地媒体/embedding retrieval 平台最值得抽取的是：数据集与视图边界、可扩展字段/标签模型、模型推理到 VectorField 的落库契约、Brain run 元数据、以及 v2 二进制可视化协议；不应直接照搬 MongoDB 绑定、完整 App 或其所有第三方模型适配。

当前核对允许的改动仅为本项目根 `ARCHITECTURE.md`；未修改源码、README、依赖、测试、配置或 `细探-fiftyone.md`，未安装、启动、构建、提交或生成数据/权重/数据库。

## 13. 证据边界

- 本地事实来源：`README.md`、`setup.py`、`pyproject.toml`、`app/package.json`、`package/README.md`、`tests/README.md`、`docs/README.md`、`fiftyone/__public__.py`、`core/dataset.py`、`core/models.py`、`core/collections.py`、`core/odm/*`、`server/app.py`、`server/query.py`、`server/mutation.py`、`server/routes/*` 及当前目录清单。
- 已有摘要：`细探-fiftyone.md` 仅作为背景线索；本文件对核心入口、数据模型、API、embedding 协议、测试和版本进行了源码复核。
- 任务指定的专属 MCP 为 `system_engineering_toolkit`（HTTP `127.0.0.1:8766/mcp/`）；本次实际工具信封标注的 MCP 实例为 `project_toolkit`，其 `project_context` 绑定到系统工程平台自身地图而不是本目标仓库。因此未把 MCP 输出作为 FiftyOne 源码证据。目标仓库未发现 `.codegraph/`，目标项目的代码关系结论均来自本地文件读取、精确检索和 git/远程探针。

## 14. 旧细探吸收对照与唯一事实源

旧文档 `细探-fiftyone.md` 已完整读取（64 行），结论逐项对照当前源码后处理如下。旧文档保留为历史线索，不删除、不再作为长期事实源；后续只维护本 `ARCHITECTURE.md`。

| 旧细探结论 | 当前源码对应 | 裁决 |
|---|---|---|
| 定位为高质量数据集与视觉模型工具 | `setup.py:32-41` 的包描述；`__public__.py:40-51,158-172` 的 Dataset、模型、embedding 公共入口 | 吸收；补充为数据集、模型推理、检索可视化与评估闭环 |
| Dataset 管理大规模视觉数据 | `core/dataset.py:274-295,309-351`：Dataset 是有序媒体样本集合，原始媒体在磁盘，标签/字段在数据库 | 吸收；补充持久化、单例、视频 frames 与动态 schema |
| App 可视化探索 | `core/session/session.py:136-233,347-451`；`server/app.py:168-235` | 吸收；补充 Session→Client→Starlette/GraphQL/静态资源链 |
| Evaluation/基准 | `__public__.py` 暴露 evaluation；`core/dataset.py` 有 evaluation cache/run 关联 | 吸收为能力边界；当前核对未单独深挖各 evaluator 的执行契约，保留待核 |
| Model integration | `core/models.py:1019-1216`：模型转换、媒体类型校验、分支执行、VectorField、SaveContext | 吸收；补充错误策略与资源边界 |
| MongoDB 依赖 | `setup.py:68-75,99-101`；`core/odm/database.py:485-535` | 吸收；明确 Mongo 是运行前提，不是可直接替换的抽象 |
| 数据质量闭环可借鉴 | Dataset/View、embedding、Brain run、evaluation/run 元数据和 App 交互的源码证据 | 吸收为架构启示，不裁决为生产接入方案 |
| “无 LLM 提示词” | 当前依赖/公开入口未显示 LLM prompt 层 | 吸收为边界；不把模型适配误写成提示词编排 |

## 15. 公开契约表（源码事实）

“未声明”表示在当前核对读取的实现和 docstring 中没有看到该契约，不表示运行时绝对不存在。除明确写出的返回/异常外，不臆测 HTTP 错误码、幂等语义或事务语义。

| 入口/能力 | 输入与所有权 | 输出/状态变化 | 错误、可重试、超时、取消、幂等 | 证据 |
|---|---|---|---|---|
| `fiftyone.Dataset(...)` / `load_dataset` | 名称、`persistent`、`overwrite` 等；Dataset 对象持有 ODM 文档和 collection 引用，原始媒体仍由调用方路径指向的文件持有 | 新建或加载 Dataset；初始化 sample/frame document class、四类 LRU cache、媒体类型；`persistent=False` 的清理由数据库退出治理参与 | 同名 `overwrite` 会先删除；已删除 Dataset 访问会抛 `ValueError`；无显式超时/取消/幂等键，名称是主要寻址键 | `fiftyone/core/dataset.py:274-351,397-425`；`fiftyone/core/odm/database.py:307-330` |
| `SampleCollection.compute_embeddings` → `core.models.compute_embeddings` | `samples`、可转换为 `Model` 的模型、`embeddings_field`、batch/worker/`skip_failures`；写入字段由 Dataset 的 SaveContext 持有 | 无字段时返回 ndarray/list/dict；有字段时在 sample/frame schema 创建 `VectorField` 并逐条/批量保存，返回 `None` | 不支持模型/embedding/media type 抛 `ValueError` 或媒体异常；`skip_failures=True` 记录 warning 并保留 `None`；无业务超时/取消/幂等键/事务回滚声明 | `fiftyone/core/models.py:1019-1124,1133-1216`；`1219-1260` |
| `Dataset.sort_by_similarity` / Brain visualization | 需要既有 Brain similarity/visualization run；查询可为 ID、向量或 prompt（prompt 能力依赖 Brain/provider） | 返回 `DatasetView`；run 结果和配置保存到 Dataset 关联的 Brain/run 元数据 | 前置索引缺失属于调用前提失败；当前核对未执行 Brain/provider；未见统一超时/取消/幂等键 | `fiftyone/core/collections.py:8043`（已有文档复核）；`fiftyone-brain` 依赖 `setup.py:99` |
| `fo.launch_app` / `Session` | Dataset/View、sample/group、port/address、remote、browser、config；Session 建立并持有 Client、state 与事件监听器 | 生成全局 `_session`，`Client.open(state)`，非 notebook 打开 App；状态更新通过事件回写 | 仅允许一个 App；remote notebook 抛 `ValueError`；`close()` 断开 plots 并关闭 client；等待期间 `KeyboardInterrupt` 可中断；无请求幂等键 | `fiftyone/core/session/session.py:136-233,347-451,1279-1308` |
| `/embeddings/v2/*` POST 路由 | JSON `datasetName`、`brainKey`，各路由再接 view/filter/slices/field/offset/limit 等；`run_sync_task` 把同步计算置于 async endpoint | runs/info 为 JSON；geometry/ids/color/masks 为 16 字节 header + 二进制列；lasso 返回可序列化 view stage；color 有小 LRU cache | ready 只代表 results pointer 存在；缺字段/不存在 run 的异常转换未在当前核对形成统一错误码；未见服务端重试、超时、取消或幂等契约 | `fiftyone/server/routes/embeddings_v2.py:1-19,78-143,146-232,235-259` |
| `fiftyone` CLI | setuptools 注册 `fiftyone=fiftyone.core.cli:main`；子命令由 `FiftyOneCommand.setup` 注册 | 复用 Dataset/App/Brain/Plugin 等公共能力，不另建数据访问层 | argparse 参数校验；各子命令失败语义分散；quickstart 的 `--wait` 控制连接丢失后的等待，非全局任务超时 | `setup.py:123-124`；`fiftyone/core/cli.py:85-181` |

## 16. 真实对接调用链

### 16.1 数据集与持久化链

```text
用户 Python/Notebook/CLI
  → fiftyone.__public__.Dataset/load_dataset
  → core.dataset.Dataset.__init__
  → _create_dataset 或 _load_dataset
  → core.odm.dataset 的 DatasetDocument / SampleDocument / FrameDocument
  → core.odm.database._connect/get_db_conn
  → mongoengine + pymongo → MongoDB collections
  → 原始媒体 filepath（文件系统，不由 Mongo 持有）
```

`Dataset.__init__` 先按名称创建或加载文档，再建立 sample/frame 类型和 annotation、brain、evaluation、run LRU cache；媒体类型为 video 时额外初始化 frames。数据库连接入口 `_connect()` 在 client 关闭或缺失时重建，`get_db_conn()` 按 `fo.config.database_name` 取库。该链路的写 owner 是 ODM/collection 层，不是 App 前端。

### 16.2 embedding 生成与落库链

```text
SampleCollection.compute_embeddings
  → core.models.compute_embeddings
  → _convert_model_if_necessary / Model.has_embeddings / media type validation
  → ExitStack：设置 model 属性 + model context
  → 选择 video / frame / DataLoader / batch / single 分支
  → model.embed 或 model.embed_all
  → SaveContext(samples)（仅 embeddings_field 路径）
  → sample[field] = embedding
  → ctx.save(sample)
  → Dataset VectorField / Mongo sample 或 frame 文档
```

有 `embeddings_field` 时，函数先调用 `_handle_frame_field`，缺字段即添加 `VectorField`；视频 image model 写 frame field，其他情况写 sample field。单样本分支在每个 sample 上读 `sample.filepath`、调用 `model.embed`、再逐样本 `ctx.save`。失败且 `skip_failures=True` 时不抛出而写 warning/`None`；这意味着调用方必须另行保存失败计数和输入清单，不能只检查返回值是否为 `None`。

### 16.3 Brain run 与 embeddings v2 UI 链

```text
Brain visualization/similarity 计算
  → Dataset 的 brain_methods / run results（结果 blob pointer）
  → /embeddings/v2/runs
  → /run-info → /geometry、/ids、/color、/masks
  → wire order 对齐的前端 embeddings-v2 renderer
  → lasso-stage 反向编译为 Dataset/View stage
  → /sample-info 按索引惰性取 media/field
```

`EmbeddingsV2Runs` 只检查 visualization config 和 `Dataset._doc.brain_methods[brain_key].results` 指针；`run-info` 读取结果 points 形状；geometry 按 wire-order 返回 contiguous little-endian Float32 columns；ids 对 patch run 默认返回 label IDs；masks 表达当前 view 的 visible 与 filter 的 match；lasso 将 polygon/indices 编译为 Select/MatchLabels 等 stage。`ready` 不是成功终态或完整状态机。

### 16.4 App/事件链

```text
fo.launch_app
  → Session.__init__ / StateDescription
  → fosc.Client.open(state)
  → Server routes + /graphql + /plugins + static root
  → React/TypeScript app/packages/*（Relay/state/events/operators）
  → Client event listener
  → Session._state / Dataset/View 更新
```

服务端 `lifespan` 启动 Execution Store Mongo change-stream notification service 的专用线程；退出时 `stop()` 最多等待 5 秒。服务端 CORS 读取 `allowed_origins`，插件目录与静态前端分别挂载，不能把 `/embeddings/v2` 当作脱离 Dataset/Brain/App 的通用向量库 API。

## 17. 关键节点明细

| 节点 | 前置条件与状态变更 | 读写对象 | 调用者/被调用者与并发 | 失败分支与恢复 | 证据 |
|---|---|---|---|---|---|
| `Dataset.__init__` | 名称可为空（创建时生成默认名）；create/load 后写 `_doc`、sample/frame class、四类 LRU cache、`_deleted=False` | 读/写 Dataset ODM 文档、sample/frame collection、媒体类型 | Python API/CLI 调用；数据库 client 为全局/异步 client | 同名 overwrite 先 delete；删除对象的其他属性访问抛 `ValueError`；client 关闭时 `_connect()` 重建 | `core/dataset.py:309-351,408-425`；`core/odm/database.py:259-304` |
| `compute_embeddings` 校验/分派 | 模型必须是 `Model` 且 `has_embeddings`；仅 image/video（group 会抛 SelectGroupSlicesError） | 读样本媒体、模型能力；可能新增 `VectorField` schema | 单线程、批处理或 Torch DataLoader；`num_workers` 只对支持 DataLoader 的模型有效 | 不支持模型/媒体/视频模型错配抛异常；不支持的 `num_workers` 仅 warning；恢复由调用方重跑 | `core/models.py:1096-1125,1133-1216` |
| `_compute_image_embeddings_single` | 逐样本读取 filepath，embedding 初始为 `None` | 读文件；有字段时写 sample 和 SaveContext | Python for-loop；进度条上下文 | `skip_failures=False` 原样抛错；否则 warning、保留 `None` 并继续；无批次事务回滚 | `core/models.py:1219-1260` |
| `Session.__init__` | 初始化 context、验证 Dataset/View/配置、构造 StateDescription | 读 config，持有 state/Client/plots；可能启动服务/浏览器 | 一个全局 session，Client 事件监听器接收 App 事件 | remote notebook 被拒绝；非 notebook 自动 `open`; 析构兜底关闭 client，但析构异常被吞掉 | `core/session/session.py:365-451,504-517` |
| `server.lifespan` | notification service 未禁用时创建 lifecycle manager 并启动专用线程 | Mongo change stream、app.state lifecycle manager | async lifespan + dedicated thread | stop 最多 5 秒；超时只 warning，异常只 log，不保证线程已清空 | `server/app.py:168-203` |
| `EmbeddingsV2Runs` | datasetName 可加载 Dataset；run config 必须是 visualization 类 | 读 brain methods/run result pointer | async endpoint 经 `run_sync_task` 调同步 `_post_sync` | 中途计算/死亡无 results pointer 时 ready=false；运行终态需旁路 status sidecar | `server/routes/embeddings_v2.py:78-116` |
| `EmbeddingsV2Color` | dataset/run/field 可解析；按 run timestamp + field 组成 cache key | 读 Dataset values/results；写进程内小 LRU body cache | async endpoint；cache 竞争由模块锁/缓存实现承担（锁细节当前核对未完全展开） | 字段/结果异常未统一转协议错误；cache 不是持久化正确性来源 | `server/routes/embeddings_v2.py:195-232,465-479` |
| `EmbeddingsV2LassoStage` | polygon 或 wire-order indices 合法；selection 不超过显式 stage 阈值时可转 Select | 读 points/IDs/view；返回 view stage 描述，不直接写 Dataset | async endpoint→sync task | 大选择集可改用表达式/索引路径；具体非法 polygon 错误契约待核 | `server/routes/embeddings_v2.py:304-390` |

## 18. 资源生命周期表

| 资源 | 创建/取得 | 正常释放 | 业务失败 | 超时/主动取消 | 宿主崩溃/残留验证 |
|---|---|---|---|---|---|
| 原始媒体文件 | `Sample.filepath` 被读取；FiftyOne 不拥有文件内容 | Python 文件读取函数返回后由底层关闭 | 读取异常按 `skip_failures` 分支；不会删除原文件 | 无显式取消接口；中断由宿主/Python 控制 | 崩溃不应改变原文件，但当前核对未做文件句柄实测 |
| Mongo `pymongo.MongoClient` / `Motor` | `core.odm.database._connect/_async_connect` 建立/复用全局 client | `_disconnect()` 显式 close 两类 client、清空引用并 `mongoengine.disconnect_all()` | 连接/版本/类型不符会断开并抛 `ConnectionError`；连接重建由 `_connect` 完成 | 无全局 DB 请求超时/取消契约在当前核对证据中确认；配置 timeout 未纳入本表 | `atexit` 与数据库清理逻辑存在；未启动 Mongo 做现场残留检查 |
| Dataset ODM 文档/collections | create/load 时取得；schema 增加时写字段 | Dataset 删除或进程退出清理非持久数据（需连接条件） | 单样本 SaveContext 可能在失败前已有部分写入；未发现跨样本事务/回滚 | 无批处理取消/回滚协议；KeyboardInterrupt 可让 Python 路径中断 | 重启恢复依赖 Mongo 文档/运行元数据，当前核对未实测 |
| `SaveContext` | `embeddings_field` 路径进入 `ExitStack` | 上下文退出；每个 sample 的 `ctx.save` 写入 | 模型失败时仍写入 `None`（skip 模式）；非 skip 异常提前退出 | 无显式 cancel hook；中断时由上下文退出，已写数据不自动回滚的事实待专项验证 | 需用 Mongo 读回确认部分写入与锁；当前核对未执行 |
| Torch DataLoader/workers | 支持模型且非 video-frame 单样本时创建；`persistent_workers=False` | iterator/上下文结束后 workers 可退出 | collate/读取失败由 `ErrorHandlingCollate` 与 skip 策略处理 | 无 API 级取消；宿主中断可能留下短暂 worker，需进程组检查 | 当前核对未加载 Torch/未验收 worker 进程残留 |
| App `Session`/Client/端口 | `Session.__init__`→`Client.open`；全局 `_session` | `Session.close`→plots.disconnect→`Client.close`；`__del__` 兜底 | Client 启动/连接异常路径未在当前核对运行验证；析构异常被吞 | notebook `freeze`；等待可 `KeyboardInterrupt`；无统一 graceful timeout | 进程崩溃后的端口/子进程未检查；需 OS 级实测 |
| notification service 专用线程 | Starlette lifespan start 时创建 lifecycle manager/thread | shutdown `stop()`，最多等待 5 秒 | stop 异常仅 log；超时仅 warning | 明确有 5 秒 shutdown wait，但不是服务任务取消保证 | 需读取线程/连接状态确认无残留；源码未提供强制 kill 证据 |
| embeddings-v2 color LRU cache | 首次 `(dataset,brain,run timestamp,field)` 请求生成 body | LRU 淘汰/进程退出自然释放 | 生成失败不应将错误 body 当成功缓存（实现细节待核） | 无 TTL/取消契约 | 非持久内存缓存，崩溃丢失可重建；未做压力/并发验证 |
| Brain results/GridFS pointer | Brain 计算保存 run config/results 后 routes 读取 | 由 Dataset/Brain run 管理 | 仅有 pointer 不代表计算成功，死亡中途可无 pointer | 无运行 cancel/status 统一契约在当前核对证据中确认 | 结果完整性/孤儿 blob 清理未实测 |

## 19. 失败、超时、取消与崩溃矩阵

| 场景 | 源码可确认行为 | 恢复/验收要求 | 当前结论 |
|---|---|---|---|
| provider/model 缺失或模型不能输出 embedding | `_convert_model_if_necessary` 后 `Model`/`has_embeddings` 校验失败 | 调用方应在运行前探测模型能力；不得以全空结果当成功 | 已实现输入门禁；集成 provider 未实测 |
| 非法参数/媒体类型不符 | `ValueError`、`MediaTypeError`、`SelectGroupSlicesError` 等明确异常 | 验收需断言异常类型和没有伪写入 | 静态已证；运行未证 |
| 空输入 | 单分支无 embedding 时返回 shape `(0,0)`；字段路径仍可能建 schema | 验收区分“空任务完成”与“没有样本” | 源码已证；未运行 |
| 单样本/批次失败 | `skip_failures=True` warning + `None`；false 原样抛出；字段路径可能保存 `None` | 结果必须带失败明细/输入 ID；不能只看函数返回 `None` | 实现是部分成功语义，无独立任务状态 |
| 重复调用/重复事件 | Dataset 名称单例化、run/cache 有复用点；未见统一幂等键或去重状态机 | 需专项验证同名 Dataset、重复 embedding、重复 event 的最终状态 | 未确认，不能宣称幂等 |
| HTTP 请求超时/客户端取消 | v2 endpoint 使用 `run_sync_task`；当前核对未见每请求 timeout/cancel handler | 应压测断开客户端后同步任务、线程、DB cursor 是否终止 | 未实现证据不足/未验证 |
| App 断线/关闭 | Client 事件有 `close_session` listener；`Session.close` 关闭 client；CLI wait 可被 KeyboardInterrupt 中断 | 需查端口、Client 子进程、Mongo connection 是否收口 | 部分实现；现场未测 |
| Mongo/第三方异常 | `_disconnect` 尝试 close 并清空全局 client；数据库类型不符抛 ConnectionError | 重建连接后读回 Dataset/run；避免把重连当写入成功 | 源码有连接治理，恢复链未实测 |
| 部分写入/回滚 | SaveContext 每个 sample 调 `ctx.save`；未见跨样本事务 | 故障注入后读回已写 sample、schema、run pointer，明确补偿策略 | 不能宣称原子批处理 |
| 进程崩溃/重启 | v2 `ready` 仅看 results pointer；Session 析构无法覆盖硬崩溃 | 重启后检查端口、worker、Mongo 锁、孤儿 run/blob | 未验证；`ready` 不能作为成功状态 |
| 高基数字段/大选择集 | color 有 `MAX_CATEGORIES=100`、missing sentinel；lasso 有 `SELECT_STAGE_MAX=10000` | 验收 payload header、截断元数据、内存峰值与慢请求 | 源码和单测存在；未执行测试 |

## 20. 防假绿验证等级（L0-L4）

| 等级 | 只能证明什么 | 当前核对证据 | 不能冒充什么 |
|---|---|---|---|
| L0 源码存在 | 路径、符号、实现片段真实存在 | `read_file`/`search_files` 复核 `setup.py`、`__public__.py`、Dataset、models、session、ODM、server、tests | 不能证明可安装、可运行 |
| L1 测试源码存在 | 测试文件和断言覆盖某些协议 | `tests/unittests/server_embeddings_v2_tests.py:24-120` 等；`tests/README.md:1-37` | 不能证明测试已通过 |
| L2 静态结构/版本检查 | 文档、路径、Git 状态和关键文本可复核 | 当前核对只读文件核对、目录/旧文档存在性和 Git 只读检查 | 不能证明 Mongo、Brain、Torch、Node 可用 |
| L3 当前核对真实执行 | 仅限当前核对明确执行且有退出码的命令 | 当前核对未安装依赖、未启动服务、未运行 Python/App/Playwright 测试；后续回信列出实际静态验证命令和退出码 | 不得把历史 CI、测试源码、日志或“应该能跑”写成通过 |
| L4 外部依赖/生产链路 | MongoDB、`fiftyone-brain`、模型 provider、Node/Yarn、浏览器和真实媒体协同工作 | 当前核对没有外部服务实测 | 明确未验证；不得宣称端到端成功 |

## 21. 当前核对验证、未验证项与剩余风险

### 已核对

- 旧 `细探-fiftyone.md` 64 行已完整读取；本文件原有 276 行已完整读取后增量补写。
- 关键源码入口和路径已逐段读取：`setup.py`、`__public__.py`、`core/dataset.py`、`core/models.py`、`core/session/session.py`、`core/odm/database.py`、`server/app.py`、`server/routes/embeddings_v2.py`、`tests/README.md`、v2 单测和 `app/package.json`。
- 旧细探的四个核心点（Dataset、App、Evaluation、Model integration）和 Mongo 依赖均能在当前工作树找到对应证据；“无 LLM prompt”只保留为边界描述。

### 未验证/剩余风险

1. 未安装依赖、未连接 MongoDB、未加载 `fiftyone-brain`/Torch/模型 provider、未启动 App、未运行 Python/Node/Playwright 测试；因此所有结论属于静态源码建档。
2. `project_context` 返回的 MCP 项目是 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是目标 FiftyOne 根；随后 `codeexplore` 明确返回目标目录无 `.codegraph/`。这是工具错绑/目标无代码图，不能伪造为代码图成功；本文件的代码关系证据完全改用本地源码读取。
3. Brain run 写入、GridFS blob 完整性、run status sidecar、重复任务、事务回滚、断线取消、线程/worker/端口残留尚未被故障注入或 OS 读回验证。
4. 远程 `develop` 已领先本地快照；本文件的实现结论绑定本地 `HEAD 893842038c7663af5bd4c0ba647a68a1386bb62f` 与 `VERSION 1.21.0`，不得套用远程 `1.22.0`。
5. `fiftyone-db` 构建可能下载 MongoDB；当前核对遵守只读边界，未执行构建/安装。

## 22. 吸收/不吸收裁决

- **吸收**：旧细探关于项目定位、Dataset/App/Evaluation/Model integration、Mongo 依赖、数据质量闭环和可借鉴点的有效内容，已转写为源码绑定的定位、契约、调用链、资源和验证章节。
- **不吸收为实现事实**：旧文档中“高质量”“大规模”“数据质量闭环”等概括性宣传语；仅作为定位语并由源码能力约束；没有把 Mongo 适配、完整 App 或所有视觉模型适配裁决为平台直接接入。
- **待核**：evaluation 各 evaluator 的细粒度调用链、Brain provider 的索引构建/删除/取消、跨样本事务、HTTP 取消、崩溃清理、真实外部依赖协同。
- **唯一源声明**：本 `ARCHITECTURE.md` 是 FiftyOne 项目架构事实的唯一维护文件；`细探-fiftyone.md` 保留但不再扩写、不作为并行权威文档。只允许修改本文件，未改源码、配置、测试、依赖、Git 或旧细探。

## 23. 后续：通用底座映射与单链路裁决

### 23.1 当前核对范围与裁决口径

当前核对不把 FiftyOne 直接迁入系统工程平台，而是把当前源码中已经分开的对象、资源和生命周期映射到四个平台职责边界：**数据集支持库、数据质量模块、检索/视觉模块、运行核心**。以下“吸收/升级/新建/废弃/待核”是后续架构输入，不是生产底座已经存在的能力，也不授权修改平台代码。

证据以本地工作树 `HEAD 893842038c` 为准。关键事实包括：sample 文档以 `filepath`、`metadata`、`_dataset_id` 保存媒体引用和关系（`fiftyone/core/odm/sample.py:73-93`）；Dataset 初始化四个容量为 5 的进程内 LRU cache（`core/dataset.py:309-351`）；embedding 计算按媒体类型和模型能力分派到单样本、批处理、视频帧或 Torch `DataLoader`（`core/models.py:1019-1216`）；run 结果使用 MongoEngine `FileField`/GridFS（`core/odm/runs.py:21-33`、`core/runs.py:623-665`）；App notification service 在线程中运行并在 shutdown 最多等待 5 秒（`server/app.py:168-203`）；同步 HTTP 工作在全局 `ThreadPoolExecutor` 中执行（`core/utils.py:3206-3230`）。

### 23.2 对象到平台职责的映射表

| FiftyOne对象/能力 | 数据集支持库（权威数据边界） | 数据质量模块（质量事实） | 检索/视觉模块（领域流程） | 运行核心（资源与状态） | 后续裁决 |
|---|---|---|---|---|---|
| `Dataset`、`DatasetDocument`、sample/frame collection | 持有 `dataset_ref`、schema、sample/frame 集合访问器、view 构造入口；只经公开支持库读写 | 检查名称/媒体类型/schema、样本计数、孤儿集合和字段完整性；输出质量观察，不接管 Dataset 写入 | 接收已解析的 `DatasetView`/样本集合，不自己建第二套样本库 | 为每次访问绑定数据库句柄、超时、租约和失败证据 | **吸收**数据集/视图边界；**废弃**模块直连 ODM/集合 |
| `Sample`/`Frame`、标签和字段 | 保存 `sample_ref`、`frame_ref`、字段描述、`media_ref`；`filepath` 是引用而非媒体所有权 | 做路径可达性、媒体类型/扩展、标签 schema、帧范围、缺失 embedding 等检查 | 读取样本/帧作为模型和检索输入；patch/clip/trajectory 仍是 view 变换 | 管理打开的文件、视频解码器、批次和错误回收 | **吸收**引用式媒体模型；**升级**质量检查契约 |
| `filepath`、媒体类型和 `metadata` | 规范化路径/URI、媒体摘要、外部存储版本、访问凭证引用；不复制源文件 | 记录不可读、类型不符、媒体缺失、元数据不一致 | 通过支持库流式读取或分片读取，不能从模块私有路径读 | 为文件句柄、HTTP/object-store stream、FFmpeg reader 设截止时间和释放动作 | **吸收**引用/句柄；**废弃**把媒体二进制默认写入平台数据库 |
| `VectorField`、sample/frame embedding | 只保存字段 schema、维度/模型/版本和向量引用的持久化接口 | 检查维度、NaN/Inf、覆盖率、样本/帧对应关系、模型版本漂移 | 负责模型适配、embedding 生成、相似度查询和可视化；`compute_embeddings` 是流程入口 | 负责模型/显存/CPU/worker/批次、超时、取消和失败重试边界 | **吸收**生成与落库分层；**升级**失败明细和任务状态 |
| Brain similarity/visualization run | 持有 `run_ref`、config、view snapshot、provider/version 和结果 artifact pointer | 检查 run 是否引用存在 Dataset/view/field、结果 blob 是否完整、孤儿 run/blob | 负责 Brain provider、索引构建/查询、`sort_by_similarity`、embeddings-v2 wire order | 负责 run 状态、后台任务、资源预算、重启恢复；不能用 `ready` 代替终态 | **吸收**run 元数据与结果指针；**待核**Brain provider 的真实取消/重建 |
| MongoDB、MongoEngine、Motor | 封装同步/异步数据库适配器、连接串、数据库名、查询/事务能力 | 只读审计集合、引用完整性、孤儿 `runs`/`fs.files`，质量报告不旁路修复 | 通过支持库获得样本、向量和 run 数据，不持有数据库 client | 连接池、断开/重连、请求 `maxTimeMS`、shutdown、泄漏和凭证边界 | **升级**为外部数据库支持库 provider；**废弃**公共模块直连 Mongo |
| GridFS `FileField`/`fs.files`/`fs.chunks` | 作为结果 artifact provider；记录 content type、大小、摘要、pointer，不暴露 Mongo 文件对象 | 检查 pointer→blob、blob→run 的双向一致性和孤儿清理 | 读取 Brain/run 结果；不得把 GridFS 当通用原始媒体仓库 | 读写 stream、删除、断线、超时、残留和崩溃恢复 | **吸收**生成结果 blob 模式；**新建**统一 artifact manifest；**待核**跨存储迁移 |
| `Session`、`Client`、App state/events | 只把 Dataset/View/sample/selection 作为 typed refs 传输，不持久化为第二数据模型 | 检查 session 引用的数据集/view/样本是否仍存在 | 负责 embeddings、similarity-search、looker 等视觉交互协议 | 负责 session、端口、客户端、事件监听器、通知线程和优雅关闭 | **升级**为运行核心 session/句柄管理；**废弃**全局 session 作为跨任务状态源 |
| Torch `DataLoader`、`FiftyOneTorchDataset` | 提供按 sample/frame ref 的只读迭代器和 media reader | 记录读取/解码/批次失败及样本 ID | 负责 transform、collate、batch inference、embedding 输出顺序 | 负责 worker、pin memory、CPU/GPU 预算、取消、进程组清理 | **吸收**数据读取与视觉推理分层；**待核**worker 强杀后的残留语义 |
| Dataset 的 annotation/brain/evaluation/run LRU cache 与 embeddings-v2 color LRU | 可提供 cache key/serialization 适配，但不能作为权威数据 | 检查 cache 命中结果与持久化结果的一致性 | 允许领域层复用只读计算结果 | 统一 TTL/容量/失效/线程安全/崩溃丢失和重建；cache 不能承载任务状态 | **吸收**“缓存只加速”；**升级**统一缓存生命周期，**废弃**缓存即事实 |
| delegated operation、Execution Store、operator worker | 只保存任务引用、输入/输出 schema、dataset/view/sample refs | 检查任务→run→artifact→Dataset 的关联和终态完整性 | 负责 Operator/视觉任务的领域执行 | 负责排队、租约、状态 CAS、取消、子进程组、日志和重启恢复 | **吸收**任务与数据引用分离；**升级**平台统一任务资源治理 |

### 23.3 唯一权威链路（不复制数据管理）

```text
调用方/Notebook/CLI/App operator
  → 运行核心创建 request/task + resource lease
  → 数据集支持库解析 dataset_ref/view_ref/sample_ref/media_ref
  → 外部数据库/媒体 provider 只读取得 Dataset/Sample/Frame/媒体句柄
  → 数据质量模块校验 schema、媒体可达性、样本-标签-向量-运行关联
  → 检索/视觉模块读取句柄并调用模型/Brain provider
  → 数据集支持库写 VectorField、run config、artifact manifest/pointer
  → 运行核心提交 task/run 状态与证据
  → App session/HTTP/GraphQL 只投影 refs、view stages、wire payload 和状态
```

固定所有权：

1. **Dataset/Sample/Frame/字段的写 owner 是数据集支持库**。质量模块只能提交质量观察或门禁结果；检索/视觉模块只能提交其声明的 vector/run/artifact 命令；App 只能提交公开 mutation/operator。
2. **原始媒体的写 owner 仍是外部媒体系统/用户文件系统**。`Sample.filepath` 和媒体 URI 只作为稳定引用、访问策略、版本/摘要和可选范围信息；默认不把原始图像、视频、点云或多模态文件复制到 Mongo/GridFS。
3. **embedding 的语义 owner 是检索/视觉模块，存储 owner 是数据集支持库**。模型版本、维度、字段、sample/frame identity 和失败明细必须随运行记录提交，不能让前端或缓存推断成功。
4. **Brain index/run 的语义 owner 是检索/视觉模块，artifact/pointer 的持久化 owner 是数据集支持库**。`GridFS FileField` 不是独立索引服务；`ready=bool(pointer)` 不是完成、失败、取消或崩溃状态（`server/routes/embeddings_v2.py:95-101`）。
5. **任务、线程、进程、端口、连接和缓存的生命周期 owner 是运行核心**。领域模块声明资源需求和释放回调，不自行创建第二套任务/超时/重启/清理器。
6. **App session 是临时投影，不是数据源**。session 只持有 Dataset/View/sample/selection 的引用和事件状态；重启后必须从权威 Dataset、run/task 状态恢复。

“不复制数据”不是禁止所有内部复制：FiftyOne 的 dataset clone 明确会复制 Dataset extras，并且复制 GridFS 结果只能 read→write（`core/dataset.py:10677-10686`）；Execution Store clone 也只复制 allowlisted、按 `dataset_id` 重映射的任务记录（`operators/store/clone.py:113-165`）。平台默认不复刻这条全量 clone 链，而采用**引用 + manifest + 可重建派生物**；只有用户明确要求且通过资源/权限/成本验收时才执行显式复制。

## 24. 外部数据库、媒体与任务资源契约

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主崩溃/恢复验收 |
|---|---|---|---|---|---|
| Mongo `MongoClient`/Motor client、数据库/游标 | 数据集支持库创建；运行核心登记 lease | 关闭 cursor/client，解除 lease；异步 client 等待任务结束 | 将异常映射为数据库 provider 错误；不得把重连后的空查询当成功 | 设置查询截止时间（Mongo 聚合支持 `maxTimeMS`，`database.py:364-400`）；取消后排空/关闭 cursor | 重启重新建 client；读回 Dataset/run/task；确认无连接/锁/后台线程残留 |
| GridFS `FileField` stream、`fs.files`/`fs.chunks` | 数据集支持库 artifact provider 创建；run owner 持有 pointer | `save_run_results` 覆盖前显式删除旧 blob，删除 run 时显式删除 result（`core/runs.py:642-665,836-857`） | pointer 未提交或 blob 写失败必须返回失败；不得留下“成功 pointer” | 中止写入关闭 stream，记录 `cancelled/partial`，不把半 blob 标记 ready | 对账 pointer、`fs.files`、`fs.chunks`、run；执行 orphan run/result 清理（`database.py:732-776`） |
| 外部原始媒体文件、HTTP/object-store stream、FFmpeg reader | 外部媒体 owner；支持库只借用句柄 | 读取/解码器关闭；原始文件不删除 | 记录 URI、sample ID、媒体错误；`skip_failures` 只能形成显式部分成功 | 截止读取、关闭 response/reader；不能让 worker 继续无界读取 | 重启只验证 URI/摘要/可达性，不重建副本；核对文件句柄与下载临时物 |
| embedding 模型、GPU/CPU 内存、Torch DataLoader worker | 检索/视觉声明需求；运行核心分配预算 | 退出 `ExitStack`、drain iterator、释放 worker/显存；`persistent_workers=False`（`models.py:1008-1016`） | batch/sample 失败按 `skip_failures` 记录样本级失败；任务不得只返回 `None` | 取消必须停止迭代、关闭 reader、回收 worker/进程组；pin memory 受预算约束 | 强杀后检查 worker、GPU/临时文件；重启以未完成 sample 清单补偿，不重复覆盖成功项 |
| App `Session`/Client、端口、事件监听器 | 运行核心 session owner；`launch_app` 创建全局 session | `Session.close`/`close_app` 关闭 client、注销监听器和 plots | 启动/连接异常返回 session failure；不得把析构吞异常当干净关闭 | 客户端断开、KeyboardInterrupt、shutdown deadline 都要触发 close；通知线程最多 5 秒只是现状 | 重启检查端口、client 子进程、notification thread；从 Dataset/run/task 重建 state |
| `run_sync_task` 线程池、SaveContext async writer | 运行核心创建；领域模块提交 callable | 等待 future、关闭 executor；SaveContext `__exit__` 会 drain futures（`collections.py:169-209`） | future 首个异常向上返回；已提交 bulk write 的部分结果必须可对账 | 线程取消不是自动停止同步函数；必须记录“请求已取消/后台仍运行”并在边界排空 | 线程崩溃/解释器退出后读回样本与 run；线程数归零，禁止把进程内 future 作为 durable state |
| delegated operation 子进程、日志队列、外部 orchestrator | 运行核心/任务支持库；任务文档存 Mongo | `set_completed` CAS 更新；子进程 flush/关 queue 后退出 | 捕获 traceback，`set_failed`；外部状态变化时不得覆盖新状态 | cancel 通过状态 CAS + terminate whole process group；不能只 cancel Python coroutine | child `setsid`，终态 finally 杀 descendant 并 `os._exit(0)`（`operators/delegated.py:96-105,108-184`）；重启扫描 running/queued lease 并恢复/标失败 |
| Dataset/Brain/annotation/evaluation/run LRU cache | 运行核心统一 cache owner；Dataset 持有引用 | 按容量/TTL 失效，正常 reload/close 清空 | cache decode 错误丢弃并从权威存储重建 | 取消不写 cache；超时结果不能入 cache | 崩溃直接丢弃并重建；对账禁止用 cache 数量代替 Mongo/GridFS 数量 |

以上资源必须有四种终态记录：`completed`、`failed`、`cancelled/timeout`、`crashed/recovered`。当前 FiftyOne 已有的 `skip_failures`、warning、`ready`、线程 stop 或 `set_failed` 只能证明局部行为；平台验收必须补齐 task/run 状态、失败 sample IDs、artifact pointer、资源释放证据和恢复后的读回结果。

## 25. 失败、取消、崩溃的后续缺口

| 反向场景 | 当前源码事实 | 底座要求 | 裁决 |
|---|---|---|---|
| provider 缺失、模型无 embedding、媒体类型错 | `compute_embeddings` 在模型能力和 image/video/group 类型处抛明确异常（`models.py:1096-1125`） | 统一 `PROVIDER_UNAVAILABLE`/`CONTRACT_INVALID` 映射，拒绝建假 run/artifact | **吸收**输入门禁，**升级**跨模块错误码 |
| 空 Dataset/空 batch | 空 embedding 返回空矩阵；字段路径可能先创建 schema | 明确 `empty_completed` 与 `no_input`，不得当作全量成功 | **升级**任务终态与计数 |
| 单样本/batch 失败 | `skip_failures=True` 写 warning/`None`，字段路径仍逐条 `ctx.save`（`models.py:1219-1260,1315-1409`） | 输出成功数、失败 sample/frame IDs、错误摘要和可补偿 cursor；部分写入必须可读回 | **吸收**部分成功语义，**升级**失败账本 |
| SaveContext 中途异常 | async writer 只用单线程避免保存状态竞态，退出时 drain future（`collections.py:164-209`） | 成功/失败都要明确已提交批次数；取消不假装回滚已提交 bulk write | **升级**批次提交证据，**待核**真实故障注入 |
| HTTP 请求超时/断开 | `run_sync_task` 把同步函数丢入线程池；没有从该接口证明同步函数可被取消（`utils.py:3219-3230`） | 请求取消与后台任务解耦：任务有独立 ID、lease、取消状态和 drain；禁止只断 socket | **重要缺口** |
| Brain 计算中止 | GridFS pointer 只在结果保存后存在；中途死亡会 `ready=false`，但 ready 不表达失败/取消（`embeddings_v2.py:95-101`） | run sidecar/任务状态必须有 `pending/running/completed/failed/cancelled/crashed`，并关联 artifact | **重要缺口** |
| Mongo 断连/重连 | `_connect` 检测 closed client 后重建；`_disconnect` close 并清空同步/异步 client（`database.py:259-304`） | 重连后必须重新验证数据库、dataset、写入结果，不能重放非幂等写；记录 connection epoch | **升级**连接 provider |
| App/notification thread 停止超时 | lifespan 等待 stop 5 秒，超时仅 warning（`server/app.py:185-202`） | 超时后必须登记残留并由运行核心回收/隔离；不能仅 log | **重要缺口** |
| delegated worker 异常/强杀 | 子进程捕获异常写 failed；finally 清 descendant 并 `_exit(0)`（`delegated.py:131-184`） | 父进程必须回收、读回状态 CAS、校验进程组消失；外部 orchestrator 不得覆盖新状态 | **吸收**进程组治理，**升级**恢复对账 |
| GridFS orphan/run orphan | 提供 `drop_orphan_runs`，按 Dataset 引用集合与 `fs.files` 差集清理（`database.py:732-776`） | 只读审计先行，删除需 dry-run/授权/证据；禁止质量模块直接删 blob | **吸收**审计模式，**升级**删除门禁 |

## 26. L0-L4 防假绿分层（后续）

| 等级 | 当前核对允许的结论 | 证据/验收动作 | 明确不能宣称 |
|---|---|---|---|
| **L0 源码存在** | 可以确认对象、符号、路径和局部分支真实存在 | `Dataset` cache、sample `filepath`、embedding 分派、GridFS run、Session、DataLoader、线程池、delegated worker 的源码行已核对 | 不能证明平台已有对应支持库/模块，也不能证明可运行 |
| **L1 测试存在** | 可以确认测试树覆盖 Dataset/ODM/server/embedding/worker 等主题 | `tests/unittests/*`、`tests/isolated/*`、`e2e-pw/*` 和相关 README 的覆盖说明 | 不能把测试文件、历史 CI 或测试名称当作通过 |
| **L2 静态映射通过** | 本文映射表、所有权、单链路、资源四终态和不复制规则可审阅；未新增生产接口 | 回读本文件后续章节，检查路径/符号引用与本地 `HEAD` 一致；`git status` 只允许目标 `ARCHITECTURE.md` 与既有旧细探未纳入当前核对修改 | 不能证明 Mongo/GridFS/Torch/Brain/Node/浏览器可用 |
| **L3 当前核对真实执行** | 仅能报告当前核对实际执行并有退出码的命令 | 当前核对只执行了目标仓库 `git status --short`、`git rev-parse --short HEAD` 和文档结构核对；未安装依赖、未启动服务、未运行 FiftyOne/App/测试 | 不能把静态读取或当前核对文档写入说成端到端通过 |
| **L4 外部依赖/生产链路** | 需要真实 Mongo、GridFS、媒体、Brain provider、Torch worker、App client 和 delegated worker 联动 | 应在隔离环境执行 dataset→media→embedding→Brain artifact→App projection→cancel/crash/recovery，并读回 DB、blob、进程、端口和任务终态 | 当前**未验证**；不得宣称生产可用或崩溃安全 |

## 27. 复用、升级、新建、废弃与待核裁决

### 吸收（有源码证据且边界清晰）

- Dataset/Sample/Frame 的引用式数据模型、动态 schema、View stage 组合和媒体类型门禁，作为数据集支持库的建模参考。
- `compute_embeddings` 的“模型能力校验 → 媒体校验 → DataLoader/批处理/单样本 → VectorField/SaveContext”分层，作为检索/视觉模块流程参考。
- Brain/run config 与 GridFS 结果 pointer 分离、按 Dataset 清理 orphan run/blob，作为 artifact 管理参考。
- App `Session` 的 Dataset/View/sample/selection 引用和 GraphQL/HTTP 事件投影，作为视觉交互模块与运行核心的协议参考。
- delegated worker 的独立进程组、异常转 failed、finally 回收 descendant，作为运行核心崩溃治理参考。

### 升级现有底座（不复制 FiftyOne 业务链）

- **数据集支持库**：补统一 `dataset_ref/sample_ref/frame_ref/media_ref/view_ref`，Mongo/其他数据库和文件/object-store 只作为 provider；补 GridFS/对象存储 artifact pointer + manifest；禁止上层获取 MongoEngine document 作为跨层契约。
- **数据质量模块**：补媒体可达性、媒体类型、schema/标签/帧范围、embedding 维度/覆盖率、run/artifact 双向引用、孤儿资源和部分写入对账；质量结果写观察/报告，不旁路修改 Dataset。
- **检索/视觉模块**：收敛模型/Brain provider、embedding/index/run 语义、wire-order/lazy identity、相似度 View 和失败样本清单；不在 provider 内复制数据库连接、任务状态或 App session。
- **运行核心**：补统一 resource lease、task/run 状态、cancel/timeout/crash/recovery、进程组和线程池回收、端口/session 句柄、缓存 TTL/容量/失效；把“线程池 future 完成”与“持久任务完成”分开。

### 新建原子能力候选（必须先登记/搜索/复用裁决）

1. `数据引用解析`：把 Dataset/View/Sample/Media/Vector/Run 引用解析为受控句柄，输出 owner、版本、权限和释放责任。
2. `外部媒体流`：按 URI/路径/范围借用媒体流，统一可达性、摘要、超时、取消和临时文件清理。
3. `运行制品清单`：把 run config、输入 view、模型/provider 版本、向量字段、artifact pointer、摘要和状态绑定为可审计 manifest。
4. `任务资源回收`：统一线程、DataLoader worker、子进程组、数据库游标、GridFS stream、端口和 cache 的四终态回收。

这些只是候选能力，不是当前核对生产底座实现；没有能力需求登记、契约 owner、占用租约、验收契约和装配计划，不得落代码。

### 废弃/隔离（不作为平台公共接口）

- 直接暴露 `mongoengine.Document`、`pymongo.Collection`、Motor client、GridFS `FileField` 的跨模块调用。
- 把 `Dataset` 的四个 LRU cache、embeddings-v2 color cache 或 session state 当权威任务/数据状态。
- 把 `ready=bool(GridFS pointer)` 当作 Brain 运行成功；把 `skip_failures=True` 当作无失败。
- 把 FiftyOne 的完整 Dataset clone、App 全局 singleton 或各自 operator/worker 链复制成平台第二套数据管理、任务管理或会话管理。

### 待核（必须有下一轮源码/运行证据）

- `fiftyone-brain` provider 的索引创建、增量更新、删除、取消、版本兼容和外部向量库边界。
- GridFS 写入中断、blob 摘要/长度校验、Mongo 事务边界和 orphan 清理的真实故障注入。
- Torch/DataLoader worker 在解码异常、KeyboardInterrupt、父进程强杀后的进程/文件/显存残留。
- `run_sync_task`、notification thread、App client 和 delegated operation 的跨平台取消、端口回收及重启恢复。
- 原始媒体 URI/对象存储、访问凭证、租约和跨项目权限的正式平台契约。

## 28. 验收契约与装配计划

### 28.1 最小公共契约

平台候选公共结果必须至少携带：`request_id`、`task_id`（若异步）、`dataset_ref`、`view_ref`、`sample_refs`/失败 refs、`media_refs`、`run_ref`、`artifact_ref`、`status`、`error_code`、`retryable`、`cancel_requested`、`resource_evidence`。其中 `artifact_ref` 只引用可验证 manifest/pointer，不内嵌大媒体或随意透传 provider 对象；成功、失败、取消、崩溃恢复必须使用互斥终态。

embedding/Brain 结果还必须携带：模型/provider/version、media type、field、dimension、sample/frame/label identity 规则、输入 view 快照、成功/失败计数、失败 ID、artifact 摘要和索引状态。App/HTTP 只能消费该契约和 view stage，不从 cache 或 GridFS pointer 猜状态。

### 28.2 四波装配计划

1. **S0 事实冻结（当前轮）**：登记现有能力搜索结果；确认四个职责 owner；冻结“不复制原始媒体、不直连 Mongo、不以 cache/ready 作事实”的门禁；保留本项目源码和本 `ARCHITECTURE.md`，不改平台生产代码。
2. **S1 数据边界**：先复用现有数据/资源/任务支持库；若无命中，再分别登记 `数据引用解析`、`外部媒体流`、`运行制品清单`，定义 provider、错误、超时、取消、权限和释放契约；禁止一次性做 FiftyOne 全量适配。
3. **S2 领域接线**：检索/视觉模块经数据集支持库读取 media refs、写 vector/run/artifact 命令；数据质量模块只读/观察/对账；App session 只走运行核心句柄和公开投影；所有异步任务走唯一任务注册表/监督器。
4. **F 验收与反向破坏**：在独立 Mongo/GridFS、媒体目录、Brain/provider、Torch、浏览器和任务 worker 环境，逐项执行成功/失败/取消/超时/断线/强杀/重启；读回 Dataset/Sample/Vector/Run/GridFS/Task/Session/进程/端口/cache；任何残留、重复写、伪成功或旁路直连都阻断发布。

### 28.3 本项目当前核对验收边界

当前核对已把后续映射、单链路、不复制规则、资源契约、失败矩阵、L0-L4 和候选装配计划增量写入唯一 `ARCHITECTURE.md`。未修改源码、配置、依赖、测试、README、旧细探或 Git；未安装依赖、启动 Mongo/App、执行 Brain/Torch/Node/浏览器/任务 worker，也未复制任何媒体、数据库或结果 blob。

## 29. 后续深挖收口：数据集、媒体、索引、存储、可视化与 worker

本节是对前述摘要的后续源码收口，专门补齐“对象到底写到哪里、谁持有资源、请求怎样进入、队列怎样推进、失败怎样落态”的实现事实。证据基线仍为本地 `HEAD 893842038c7663af5bd4c0ba647a68a1386bb62f`；本节不把测试源码或远程版本当作实现证据。

### 29.1 Dataset/Sample/Frame 的真实数据边界

1. **样本文档是引用式媒体记录，不是媒体仓库。** `DatasetSampleDocument` 的 `filepath` 是必填字符串，`metadata` 是嵌入文档，`_media_type`、随机排序辅助字段 `_rand` 和归属 `_dataset_id` 同样存于样本文档（`fiftyone/core/odm/sample.py:73-97`）。无数据集的 `Sample` 构造时会先 `normalize_path(filepath)`，根据路径推断 `_media_type`，并将 `_dataset_id` 置空（`sample.py:104-138`）。因此路径规范化和媒体类型推断发生在进入 Dataset 前，数据库只保存引用及结构化字段。
2. **Dataset 是进程内 singleton + Mongo 文档/collection 句柄。** `Dataset.__init__` 在 `overwrite=True` 时先按名称删除，随后走 `_create_dataset` 或 `_load_dataset`；创建四个容量为 5 的进程内 LRU cache（annotation/brain/evaluation/run），视频媒体再配置 frames（`core/dataset.py:309-351`）。`__copy__`/`__deepcopy__` 直接返回自身，不能把 Dataset 当作可独立复制的事务会话。
3. **新增样本先转换，再写数据库。** `add_sample(s)` 通过 `_transform_sample` 按 `expand_schema`、`dynamic`、`validate` 扩展/校验 schema，生成带 `_dataset_id` 和时间戳的 backing dict（`dataset.py:4098-4197,4341-4455`）；新增批次调用 `insert_many`，写入后为每个 Sample 绑定 backing document，视频 Sample 另外执行 `sample.frames.save()`（`dataset.py:4271-4299`）。已有 ID 的 upsert 使用 `ReplaceOne(..., upsert=True)`，无 ID 的项使用 `InsertOne`，批量 `bulk_write(..., ordered=False)`，视频 frames 随后独立保存（`dataset.py:4405-4431`）。这说明批量写不是跨 sample/frame 的单一事务。
4. **视频 frame 是独立的持久化维度。** Sample 对视频使用 `Frames`/`FramesView`，frame schema 与 sample schema 分开；删除样本会先删 sample collection，再清理 frame collection 和关联 extras（`dataset.py:6327-6354`）。按样本清空时，`_clear` 先批量删 sample，并清理 annotation 等按 Dataset/Sample ID 关联的数据，再按视频条件进入 `_clear_frames`（`dataset.py:5997-6045`）。不能只对账 samples collection 而遗漏 frames、run、annotation 或 generated dataset。
5. **修改是单文档/批次级写入，保存后刷新内存引用。** `Sample._save` 对视频先收集 frame ops，再收集 sample ops；未入库 Sample 直接抛 `ValueError`（`core/sample.py:567-587`）。`SaveContext` 的批量写使用 `ThreadPoolExecutor(max_workers=1)`（多 worker 会造成跨批状态竞态），退出时先提交尾批，再逐个 drain future；future 异常在没有外部异常时重新抛出，但已提交的 Mongo 写不会自动回滚（`core/collections.py:108-209,270-328`）。
6. **游标超时有“按已产出数量重开”的补偿，而非快照。** `_iter_samples` 捕获 `CursorNotFound` 后用已产出数量生成 `$skip` 并递归打开新游标（`dataset.py:3873-3891`）；这避免直接丢失遍历，但源码没有证明跨游标的一致性快照，数据在遍历中变化时不能宣称严格 repeatable read。

### 29.2 原始媒体、媒体字段与文件句柄

| 入口 | 源码行为 | 所有权/失败事实 |
|---|---|---|
| `GET /media?filepath=...` | 缺 `filepath` 返回 400；异步线程执行 `os.stat`，仅普通文件返回 `MediaFileResponse`，支持 Range/256 KiB chunk；不存在、权限、非目录、超长路径、符号链环等返回 404（`server/routes/media.py:51-92`） | 服务端直接按请求路径读本地文件，源码未见根目录 allowlist、签名 URL 或路径租约；媒体文件仍由外部文件系统持有，App 只借用响应流 |
| GraphQL sample serialization | `paginate_samples` 先聚合样本文档，再按 `filepath` 推断媒体类型，并异步生成 metadata/URL（`server/samples.py:90-174,177-190`） | `urls` 返回 `filepath` 及 `app_config.media_fields`/标签附属媒体字段路径；这些 URL 仍是路径引用，不是数据库 blob |
| metadata | 优先使用样本已有 metadata；缺失时图片由 `aiofiles.open` 读取尺寸，视频启动 `ffprobe` 子进程；读取失败时非 FFmpeg 错误回退为 `aspect_ratio=1`（视频另给 `frame_rate=30`），FFmpeg 缺失直接抛出（`server/metadata.py:55-161,190-228`） | `metadata_cache`/`url_cache` 是一次请求内的普通 dict；`ffprobe` 通过 `communicate()` 收口 stdout/stderr，源码未提供外部任务取消钩子 |
| 附属媒体 | `_create_media_urls` 扫描 `media_fields`、点云/3D 的正射投影路径、检测 mask_path 等，并把每个路径作为 `{field,url}` 返回（`server/metadata.py:399-465`） | mask/投影/备用媒体也没有自动复制或删除；删除样本不会替调用方删除其外部文件 |

结论：FiftyOne 的“媒体生命周期”主要是**路径引用 → stat/读取/ffprobe → HTTP/FileResponse 结束释放**；它不负责原始文件创建、版本、删除或对象存储凭证。平台适配时必须把路径/URI、访问权限、临时下载文件和 reader 的释放责任显式补到支持库契约，不能只复用 `filepath` 字段名。

### 29.3 Mongo 连接、聚合、Dataset 删除与孤儿清理

- `establish_db_conn` 创建 `pymongo.MongoClient`，注册 `atexit` 的非持久 Dataset 清理，并通过 `mongoengine.connect` 连接；连接类型/版本不符会断开并抛错。`_connect` 检测 closed client 后重建，`_disconnect` 显式关闭同步/异步 client、清空全局引用并 `mongoengine.disconnect_all()`（`core/odm/database.py:218-240,259-304`）。这是进程级连接治理，不是每个 Dataset 独占一个 client。
- `aggregate` 默认 `allowDiskUse=True`，可接受 `hint` 与 `maxTimeMS`；单 pipeline 返回 cursor，多 pipeline 在同步侧用 `multiprocessing.dummy.ThreadPool` 并行收集列表，异步侧用 `asyncio.gather`（`database.py:364-477`）。多 pipeline 结果没有源码级统一快照，且线程池/游标不是持久任务。
- `Dataset.delete()` 先 drop sample/frame collections，再删除 Dataset extras 与 backing document（`dataset.py:6327-6354`）；数据库层提供 dry-run 的 `drop_orphan_collections`、`drop_orphan_saved_views`、`drop_orphan_generated_datasets`、`drop_orphan_runs`、`drop_orphan_delegated_ops`、`drop_orphan_stores` 等清理器。`drop_orphan_runs` 对比 Dataset 中引用的 run/result ID 与 `runs`、`fs.files`，再分别删除 run 文档以及 GridFS `fs.files`/`fs.chunks`（`core/odm/database.py:586-839,732-776,2211-2225`）。清理是显式维护/审计能力，不等于每次写失败都会自动补偿。
- 非持久 Dataset 的自动清理只有在 `atexit` 能读取 admin `$currentOp` 且确认 FiftyOne 连接数不超过 1 时才执行（`database.py:307-342`）。多进程/共享数据库中不能假设解释器退出一定删除非持久数据。

### 29.4 索引：sample/frame Mongo 索引与 Brain index 的边界

1. **Mongo 索引由 SampleCollection 统一映射。** `get_index_information(include_stats=True)` 分别读取 sample/frame collection 的 `index_information()`，可附加 `collstats.indexSizes/indexBuilds` 和 `$indexStats` accesses；frame 索引在 API 名称前加 `frames.`（`core/collections.py:10821-10896`）。
2. **创建索引前会验证字段层级并处理现有索引。** `create_index` 将单字段映射为 `(field,1)`，`frames.` 前缀切换到 frame collection；compound index 不允许 sample/frame 混合。`unique`、`force` 决定升级 unique、替换顺序或降级；`wait=False` 用 `WriteConcern(w=0)` 发起不等待确认的创建，返回索引名不等于构建完成（`collections.py:10898-11117`）。默认索引（如 `id`、`filepath`、时间字段、视频 frame 的 `_sample_id_1_frame_number_1`）禁止任意删除；`drop_index` 会拒绝 default index（`collections.py:11119-11215`）。
3. **GraphQL 索引投影不是完整 Mongo 索引协议。** `server/indexes.py` 将 sample/frame 索引分组，跳过 `in_progress`；`2dsphere`/`text` key 在 GraphQL 投影中被忽略，wildcard projection 单独表达（`server/indexes.py:47-105`）。因此 UI 返回的 `Index` 列表不是 Mongo `index_information()` 的无损镜像。
4. **排序/地理阶段可按需建 Mongo 索引；Brain 相似度索引在另一条边界。** `GeoNear`/sort 等 ViewStage 可设置 `create_index=True`（`core/stages.py:3097-3126,3518-3593`）；`sort_by_similarity` 需要 `fiftyone-brain` 的 similarity run。VectorField 只表达向量字段 schema/值，不能据此推断已有可查询的 Brain/外部向量索引。

### 29.5 可视化与 API 的真实入口/返回/并发

```text
GraphQL / HTTP request
  → Starlette route/decorator（解析 JSON、异常映射）
  → server.view.get_view / DatasetView stages
  → async Motor aggregate + run_sync_task（同步段进入全局线程池）
  → sample/metadata/media 或 Brain run 结果
  → GraphQL JSON / FileResponse / SSE / embeddings-v2 二进制
```

- 路由表在 `server/routes/__init__.py:43-75`，包含 `/aggregate`、`/event(s)`、`/frames`、`/media`、`/sample`、`/embeddings`、`/embeddings/v2`、`/values`、`/sort`、`/geo`、`/video-labels`、Operator routes，以及 `/graphql`、`/plugins` 和静态根挂载（`server/app.py:205-235`）。POST/PUT/PATCH 默认 JSON 解析；Malformed JSON 返回 400；`HTTPException` 原样抛出；`DbVersionMismatchError` 返回 412 + ETag；其余异常返回 500 且 body 含 stack（`server/decorators.py:27-87`）。
- GraphQL samples 使用 `first` + numeric `after`，以 `skip(after+1)` 进入 view，再 `$limit(first+1)` 判定 `has_next_page`；可传 `hint` 和 `max_query_time`，后者换算为 `maxTimeMS`，Mongo `ExecutionTimeout` 转为 `QueryTimeout` 联合类型（`server/samples.py:90-131`、`server/query.py:442-479`）。这不是 cursor token/快照分页。
- `/frames` 先解析 dataset/view/extended stages，再用 `make_optimized_select_view` 选 sample；没有完整 stages 时用 frame range 过滤，可用 `fields` 做 `$project`，最后经 Motor aggregate 返回 `frames` 和 `range`（`server/routes/frames.py:23-82`）。
- Sample PATCH 读取 `If-Match`，其值可以是 base64 编码时间、ISO 时间或 Unix timestamp；不匹配返回 412 + 新 ETag。字段 patch 成功写源 sample 后，generated dataset 同步失败只记录日志，因为源样本已经是事实源（`server/routes/sample.py:65-167,468-507,575-685`）。这是一种“源写成功、派生同步可降级”的部分成功契约。
- App Client 使用后台 daemon thread 连接 `/events` SSE；网络异常后最多每 10 秒重连。`Client.close()` 只设置事件并以 `join(timeout=0)` 不等待线程真正结束（`core/session/client.py:66-141`）。服务端 listener 每 0.2 秒轮询订阅队列，断开时移除 listener；最后一个 App listener 消失且非 notebook context 时派发 `CloseSession`（`server/events/listener.py:37-118`）。
- `/embeddings/v2` 的 geometry/ids/color/masks 通过全局 `run_sync_task` 在线程池执行同步 Brain 结果读取；几何是 wire-order Float32 columns，mask 是 bitmask，lasso 小于等于 `SELECT_STAGE_MAX=10000` 时可生成显式选择 stage（`server/routes/embeddings_v2.py:1-18,50-66,78-180`）。`ready` 仍只检查 GridFS results pointer，不表示 completed/failed/cancelled。

### 29.6 Execution Store、队列与 delegated worker

#### 29.6.1 Execution Store 是持久键值/通知层，不是通用任务队列

- `ExecutionStore.create()` 创建带 Dataset scope、Mongo collection 和 notification service 的 `ExecutionStoreService`；`set()` 默认 `persist`，`set_cache()` 使用 `evict`，TTL 会使 key 进入可淘汰语义；`get/list/delete/clear/update_ttl/update_policy` 均转发到 repo（`operators/store/store.py:20-184`）。
- store 支持回调订阅/取消订阅；本地 registry 用 `threading.Lock` 保护 `store → subscription_id → (callback,dataset_id)` 映射（`operators/store/subscription_registry.py:72-124`）。Mongo change stream/polling notification service 将 change 转成消息后投递到 SSE notifier；App lifespan 在专用 daemon thread 创建 event loop，关闭时最多等待两次 5 秒（`operators/store/notification_service.py:562-635`、`server/app.py:168-203`）。
- `SseNotifier` 为每个 `(store_name,dataset_id)` 建 `asyncio.Queue()`，广播使用 `put_nowait`，队列满则丢消息、异常队列注销；但默认 `asyncio.Queue()` 没有显式 `maxsize`，所以源码没有证明慢客户端存在有界背压。客户端断开时 generator 的 `finally` 注销队列（`operators/remote_notifier.py:38-166`）。

#### 29.6.2 delegated operation 才是本地队列/worker API

| 阶段 | 当前实现 | 证据/风险 |
|---|---|---|
| 创建 | `DelegatedOperationService.queue_operation` 写入 `delegated_ops`，保存 operator、context、metadata、pipeline、dataset_id、rerunnable 等；Mongo repo 初始化 operator/updated_at/run_state/parent/dataset+schedule 索引（`operators/delegated.py:196-235`；`factory/repos/delegated_operation.py:160-222`） | 入队是持久 Mongo 文档；没有独立 broker |
| 状态 | `scheduled → queued → running → completed/failed`，另有 `processing` 常量；没有 `cancelled`/`timeout`/`crashed` 终态（`operators/executor.py:48-58`） | 不能把异常、进程消失或客户端断开自动称为取消 |
| 领取 | `execute_operation` 先用 `required_state=QUEUED` 的 `find_one_and_update` CAS 改 `RUNNING`；更新失败表示已被其他执行者领取/状态已改变，直接跳过（`delegated.py:669-728`；`factory/repos/delegated_operation.py:389-403`） | 具备基本重复领取保护，但 `execute_queued_operations` 先 list 后逐个 claim，列表本身不是租约 |
| 同进程执行 | `monitor=False` 时 `asyncio.run(self._execute_operator(operation))`；完成/失败用 `required_state=RUNNING` 再写回，外部已改状态时不覆盖并返回状态变化错误（`delegated.py:744-789`） | 同步执行无独立可中断句柄 |
| 子进程执行 | `monitor=True` 使用 multiprocessing `spawn`、Queue/QueueListener；child `setsid`，加载 operation 后执行，写 `COMPLETED/FAILED`，finally drain log queue、杀 descendants、`os._exit(0)`（`delegated.py:66-184,791-878`） | 正常终态资源回收路径明确；硬崩溃若未写终态由父进程识别 exit code，但当前核对源码未见随后统一写 `FAILED` 的补偿 |
| 监控/外部失败 | 父进程按间隔 join；仍存活时读取 operation，外部变 `FAILED` 则终止进程树，否则 `ping` 更新时间（`delegated.py:880-935`）。终止树先 terminate、最多等待 10 秒，再 kill，父进程再 terminate/kill（`delegated.py:937-981`） | 监控失败会返回错误，但取消/超时和资源残留需要上层另记状态 |
| 重跑/清理 | `rerun_operation` 仅允许 `rerunnable` 且不允许 pipeline child；数据库提供按 Dataset 删除 delegated ops 与 orphan 清理（`delegated.py:482-502`；`core/odm/database.py:779-806`） | 重跑是重新插入文档，不是同一 operation 的幂等重置 |

**后续收口判断：** FiftyOne 已有“Mongo 持久 operation + 状态 CAS + 可选 spawn worker + 进程树回收”的局部队列能力，但它不是完整任务监督器。缺少取消/超时/崩溃恢复状态、明确 lease/owner、统一补偿写回、持久日志完成标志和重启扫描协议；`ExecutionStore` 的 TTL/通知也不能替代这些语义。

### 29.7 资源生命周期与反向场景收口表

| 资源 | 正常完成 | 业务失败 | 取消/超时 | 崩溃/恢复 |
|---|---|---|---|---|
| Sample/frame Mongo 写入 | `insert_many`/`bulk_write` 后绑定/reload backing docs；视频 frame 单独写 | BulkWriteError 转 `ValueError`；SaveContext future 异常可上抛 | 无写 API 级取消；已提交批次不回滚 | 读回 sample/frame/last_modified_at；源码未给跨集合事务 |
| 原始媒体/ffprobe/reader | FileResponse、aiofiles、subprocess `communicate` 返回 | 缺失媒体给 404 或 metadata 占位；FFmpeg 缺失抛错 | 无统一 deadline/cancel；需宿主关闭 response/process | 原文件不由 FiftyOne 恢复；需 OS 读回 ffprobe/文件句柄/临时物 |
| Mongo client/cursor | 连接复用，显式 `_disconnect` close | 重建连接或抛 `ConnectionError`；aggregate 可 `maxTimeMS` | maxTimeMS 是 DB 查询上限，不是业务任务取消 | `atexit` 只条件清理非持久 Dataset；需读回连接/锁/孤儿集合 |
| GridFS run result | 先删旧 result（overwrite），`put` JSON bytes，再保存 run doc；读取时 `seek/read` 并反序列化 | 写入或版本不兼容抛错；pointer/blob 需对账 | 未见写流取消/partial 标志 | `drop_orphan_runs` 可审计/删除孤儿，但非自动崩溃补偿 |
| App Client/SSE/listener | Client daemon thread、SSE listener、Session.close/CloseSession | 网络异常重连；HTTP 事件错误按 route 契约返回 | close 只 `join(0)`；服务通知 shutdown 有 5 秒等待 | 未确认端口/线程必然清空；需 ps/端口读回 |
| ExecutionStore/SSE queue | subscriber generator `finally` 注销；notification thread stop | 队列异常注销，QueueFull 丢消息 | 未见 per-subscriber cancel/TTL；Queue 默认无界 | daemon thread/内存队列丢失；重启应从 store 当前状态重建，不能补发历史全部事件 |
| delegated child/descendants | terminal state 写回后 drain queue、kill descendants、`os._exit(0)` | child 捕获 traceback 写 FAILED；父 CAS 防止覆盖外部状态 | 外部 FAILED 可触发杀树；无一等 CANCELLED/TIMEOUT | 无终态的 exit code 被识别为错误，但状态补偿/重启恢复未闭合 |

### 29.8 后续真假验证表与剩余待核

| 级别 | 当前核对能够确认 | 不能宣称 |
|---|---|---|
| L0 源码事实 | Dataset/Sample/Frame 写入、filepath/metadata、Mongo/GridFS、索引创建/删除、Starlette/GraphQL/HTTP/SSE、ExecutionStore、delegated CAS/worker 路径真实存在 | 不能证明外部依赖可用或行为覆盖所有 provider |
| L1 测试存在 | `tests/unittests/index_tests.py`、`execution_store_unit_tests.py`、`tests/unittests/server_*`、`tests/intensive/import_export_tests.py` 等覆盖相关主题 | 不能把测试源码/历史 CI 当通过 |
| L2 静态收口 | 本节所有调用链、资源 owner、失败分支和未闭合状态已绑定本地路径/行号；旧 `细探-fiftyone.md` 仍未改 | 不能宣称 Mongo/GridFS/Brain/Torch/FFmpeg/Node/浏览器端到端成功 |
| L3 当前核对真实执行 | 只读执行了目标仓库 `git status --short`、`git rev-parse HEAD`、源码/文档检索；未安装依赖、未启动服务、未改源码 | 不能把文档写入或静态读取说成运行通过 |
| L4 外部链路 | 尚无真实数据库、媒体、Brain、worker、SSE 客户端和崩溃注入联合证据 | 不能宣称取消安全、崩溃可恢复、无句柄/进程/端口残留 |

当前核对明确保留以下待核：`fiftyone-brain` provider 的索引创建/增量/删除/取消与外部向量库；Mongo/GridFS 写入中断和跨 collection 事务；`ffprobe`/DataLoader/视频解码在断开与强杀时的资源收口；delegated operation 的 lease、重启恢复、取消/超时状态补偿；`/media` 路径安全边界和对象存储适配；GraphQL 数字分页在并发写入下的一致性；SSE 队列的慢客户端背压与消息丢失语义。

## 30. 后续唯一事实源声明

后续有效结论已吸收到本 `ARCHITECTURE.md`。`细探-fiftyone.md` 仅保留为历史细探线索，不再扩写；当前核对未修改源码、依赖、配置、测试、README、旧细探或 Git，未安装依赖、启动服务、生成数据库/媒体/权重/构建物。后续若继续深挖，只增量维护本文件并重新绑定源码版本。

## 31. 后续：通用底座映射最终稿

### 31.1 一句话结论

FiftyOne 可以抽象为“**引用式媒体 + Dataset/Sample/Frame 领域模型 + Mongo 文档存储 + 独立索引/Brain run + Session/API 投影 + delegated worker**”。其中只有 Dataset/Sample/Frame 和其字段具有数据域语义；原始媒体、Mongo client、GridFS stream、线程、进程、端口、缓存和队列都是被借用或被运行时管理的资源，不能越层晋升为公共领域状态。

### 31.2 通用对象映射

| 通用底座对象 | FiftyOne 对应物 | 实际职责 | 可吸收的底座契约 | 不应照搬的部分 |
|---|---|---|---|---|
| 数据集 | `Dataset`、`DatasetDocument`、`SampleCollection` | 按名称定位 Dataset，持有 schema、sample/frame collection、view 和运行记录缓存 | `dataset_ref`、版本/媒体类型/schema 快照、Dataset 生命周期 | `DatasetSingleton` 和进程内对象不能作为跨进程身份 |
| 样本 | `Sample`、`DatasetSampleDocument` | 保存 `filepath`、metadata、标签、字段、`_dataset_id` 和 sample ID | `sample_ref`、媒体引用、字段变更版本、样本级失败明细 | `Sample` 对象不是媒体所有者，也不是跨模块传输的 ODM 文档 |
| 视频帧/切片 | `Frame`、`FramesView`、`SampleSliceBatch` | 将视频 frame 作为独立持久化维度或批次切片 | `frame_ref`、sample-frame 关系、范围和顺序契约 | 不能只统计 sample 而忽略 frames、patches、clips 和派生记录 |
| 媒体 | `filepath`、`metadata`、`/media`、`ffprobe`、文件/HTTP reader | 解析、读取和投影媒体；原始文件仍在外部文件系统或对象存储 | `media_ref`、URI/版本/摘要、可达性、reader 截止时间和释放责任 | 不把原始媒体默认复制到 Mongo/GridFS；不能把任意 filepath 直接当安全 URL |
| 字段/向量 | `Field`、`VectorField`、sample/frame embedding | 保存 schema 和向量值；embedding 由模型流程产生 | 字段契约、维度/模型版本、sample/frame identity、覆盖率 | `VectorField` 不等于 ANN/Brain 索引，缓存也不等于向量事实 |
| 数据集视图 | `DatasetView`、`ViewStage`、`Select`/过滤/排序阶段 | 以可组合阶段表达查询、分页、patch/clip/trajectory 和 selection | 不可变 `view_ref` 或 view snapshot、可审计 stage 描述 | 不把前端 selection 或分页游标误认为 Dataset 写入 |
| 索引 | Mongo sample/frame index、Brain similarity/visualization run | 前者服务字段查询，后者服务 embedding 相似度/可视化 | `index_ref`、构建状态、provider/version、输入 view、结果摘要 | Mongo index、VectorField、Brain index 三者不能合并为一个“索引”概念 |
| 存储制品 | Mongo 文档、GridFS `FileField`、`fs.files`/`fs.chunks` | 保存结构化记录或 run 结果 blob，并通过 pointer 关联 | `artifact_ref` + manifest、摘要/大小/content type、孤儿对账 | GridFS 不是通用原始媒体仓库；pointer 存在不代表 run 成功 |
| 会话 | `Session`、`Client`、App state/events | 把 Dataset/View/selection 投影到 App，并接收事件 | 短生命周期 `session_ref`、句柄、连接/端口、关闭状态 | 全局 `_session` 不能承载任务状态、权威数据或重启恢复信息 |
| worker/批次 | `DataLoader`、`SampleBatch`、delegated operation child | 批量读媒体、模型推理或执行 Operator | `task_id`、batch cursor、worker lease、进程组、资源预算 | DataLoader iterator、线程池 future 和本地队列不是 durable task |
| 队列/状态 | `delegated_ops` Mongo 文档、Execution Store、SSE queue | 前者持久化操作并 CAS 领取；后两者保存/通知状态 | 持久 task record、owner/lease、状态 CAS、事件背压、重启扫描 | Execution Store 不是通用 broker；SSE 不是可靠事件日志；当前状态缺少完整取消/超时终态 |
| API | Python public API、Starlette route、GraphQL、SSE、embeddings-v2 | 将领域查询、mutation、媒体和二进制可视化协议暴露给调用方 | 输入校验、ETag/版本、`request_id`、超时、错误映射、分页/流响应 | HTTP socket 断开不能自动取消已在线程池执行的同步函数 |

### 31.3 单一调用链与所有权

```text
Python/Notebook/CLI/App
  → API 校验 request + dataset_ref/view_ref/sample_ref
  → 运行核心创建 task、resource lease 和终态记录
  → 数据集支持库解析 Dataset/Sample/Frame/Media 句柄
  → 数据库/媒体 provider 借用文档、游标、文件或对象存储 stream
  → 数据质量模块执行 schema、可达性、引用和结果对账
  → 检索/视觉模块分批读取并执行模型、embedding、Brain/index
  → 数据集支持库写字段、run、artifact manifest/pointer
  → 运行核心写入成功/失败/取消/超时/崩溃恢复证据
  → GraphQL/HTTP/SSE/App 只投影 ref、view stage、结果和状态
```

所有权固定为：

1. 数据集支持库是 Dataset/Sample/Frame/字段以及结构化 run/artifact pointer 的写 owner。
2. 外部媒体系统是原始文件和对象存储内容的写 owner；媒体支持库只借用 reader/stream。
3. 检索/视觉模块是 embedding/index/run 的语义 owner，但不能自己创建数据库连接、任务队列或 App session。
4. 运行核心是 task、lease、线程、进程组、游标、端口、缓存和关闭流程的生命周期 owner。
5. 数据质量模块只产出观察、门禁和对账报告，不旁路修复 Dataset、blob 或索引。
6. API 和 Session 是投影层；前端 state、`ready`、cache 命中和 socket 存活都不能成为权威成功信号。

### 31.4 资源生命周期与失败闭环

每个异步运行至少要落下 `pending → running → completed|failed|cancelled|timeout|crashed/recovered` 的互斥终态，并关联输入 refs、成功/失败 ID、artifact manifest、错误码、是否可重试和资源释放证据。FiftyOne 当前实现只覆盖其中的局部状态，底座映射不得把局部行为扩大解释为完整状态机。

| 资源 | 正常完成 | 失败 | 取消/超时 | 崩溃后验收 |
|---|---|---|---|---|
| Sample/Frame 写入 | `insert_many`/`bulk_write` 或 `SaveContext` 完成，回读 backing document | 记录 batch/sample/frame 错误；已提交写入保留并可对账 | 不宣称回滚；停止后记录已提交批次 | 回读 sample、frame、schema 和 Dataset 关联；检查跨 collection 部分写入 |
| 原始媒体/reader/ffprobe | `FileResponse`、文件句柄、response、子进程正常关闭 | 记录 URI、sample ID、媒体错误；不删除源文件 | deadline 到期关闭 reader/response/process，清理临时物 | 检查文件句柄、ffprobe/解码子进程、临时文件；不重建媒体副本 |
| Mongo client/cursor | 关闭 cursor，复用或显式关闭 client | 映射 provider 错误；重连不是原操作成功 | 使用 `maxTimeMS`/业务 deadline，关闭 cursor；不能仅取消 coroutine | 重建连接并读回 Dataset/task/run；检查连接、锁和后台线程 |
| GridFS/artifact | 写 blob、校验摘要/大小、再提交 manifest/pointer | pointer/blob 任一失败即失败；不得留下成功假象 | 关闭 stream，标记 partial/cancelled，未完成 blob 进入审计 | 对账 manifest、run、`fs.files`/`fs.chunks`，dry-run 后清理孤儿 |
| embedding 模型/DataLoader worker | drain iterator，释放模型上下文、worker、显存/内存 | 记录失败 sample/frame ID；`skip_failures` 只能是部分成功 | 停止迭代并回收进程组；线程取消不等于函数停止 | 检查 worker、GPU、reader、临时文件；以未完成清单补偿，不覆盖成功项 |
| Session/Client/SSE/端口 | 注销 listener，关闭 Client、plots、端口和通知资源 | 记录 session failure；析构吞异常不能当干净关闭 | 触发 close 并遵守 shutdown deadline；断线与取消分开记账 | 检查端口、daemon thread、client 子进程和 listener；从权威状态重建 UI |
| delegated worker/队列 | CAS 写 completed，flush 日志，关闭 queue，回收 descendant | 捕获 traceback 写 failed，禁止旧 worker 覆盖新状态 | 通过状态 CAS + 进程组终止；必须有 cancel/timeout 终态 | 扫描 queued/running lease，判断 exit code，补写 crashed/recovered 或 failed |
| LRU/cache/线程池 future | 受容量/TTL 约束并只缓存可重建结果 | 丢弃坏 cache，从权威存储重建 | 取消结果不得入 cache；future 不作为 durable 状态 | 可直接丢弃并重建；对账不能拿 cache 统计代替持久存储统计 |

### 31.5 API、队列和验证等级的底座要求

- API 必须区分同步查询、异步 task 提交、状态查询、取消请求和结果读取；响应至少包含 `request_id`、`task_id`（若适用）、refs、`status`、`error_code`、`retryable` 和资源证据。
- GraphQL/HTTP 的 `max_query_time`/`maxTimeMS` 只约束数据库查询；它不是 worker、模型推理、ffprobe 或线程池同步函数的业务取消协议。
- delegated operation 的 CAS 领取可作为防重复领取参考，但必须补 owner/lease expiry、重启接管、cancelled/timeout/crashed 状态、日志完成标志和补偿写回。
- Execution Store 适合作为持久键值/通知层；SSE 适合作为实时投影。需要可靠投递、重放、背压和顺序时，必须另有明确事件日志或 broker 契约。
- `ready=bool(results pointer)`、`skip_failures=True`、HTTP 200、future 完成和 Session 存活都不能单独判定任务成功。

| 等级 | 可确认内容 | 当前核对结论 |
|---|---|---|
| L0 源码事实 | 对象、函数、路由、存储和局部分支存在 | 已由本文件引用的本地源码路径支持；不代表可运行 |
| L1 测试存在 | 测试树覆盖某主题、存在断言 | 只能证明测试意图，不能证明通过 |
| L2 静态映射 | 对象/所有权/生命周期/失败/验证层级能够闭合审阅 | 当前核对新增映射属于 L2；未产生平台代码或外部运行证据 |
| L3 真实执行 | 指定命令当前核对真实运行且退出码为 0 | 当前核对未安装依赖、未启动 Mongo/App、未运行 FiftyOne 测试；不得宣称 L3 |
| L4 联合链路 | 真实媒体、Mongo/GridFS、Brain、worker、API、客户端和故障注入协同 | 未验证；发布前必须在隔离环境覆盖成功、部分失败、取消、超时、强杀、重启和残留对账 |

### 31.6 后续最终裁决

**吸收**：引用式 Dataset/Sample/Frame 模型、View stage、媒体句柄、字段/向量与索引分层、artifact manifest、Session 投影、CAS 领取和进程组回收。

**升级**：统一 refs、task/run/artifact 状态、失败账本、resource lease、取消/超时/崩溃恢复、API deadline、队列背压、索引构建状态和资源残留验收。

**隔离/废弃**：跨模块暴露 MongoEngine/pymongo/Motor/GridFS 对象；把原始媒体复制进结构化数据库；把 Dataset singleton、LRU、SSE、`ready` 或前端 state 当事实；把 FiftyOne 全量 clone 当平台同步机制。

**待核**：Brain provider 的增量/删除/取消，GridFS 中断和事务边界，DataLoader/ffprobe 强杀残留，delegated lease 重启恢复，`/media` 路径安全与 object-store 适配，SSE 背压和 GraphQL 数字分页一致性。上述待核项没有 L3/L4 证据，不得写成平台已具备能力。

本节仍只修改本项目根 `ARCHITECTURE.md`；未修改源码、依赖、配置、测试、README 或 `细探-fiftyone.md`，未安装依赖、启动服务、生成数据库/媒体/权重/构建物。
