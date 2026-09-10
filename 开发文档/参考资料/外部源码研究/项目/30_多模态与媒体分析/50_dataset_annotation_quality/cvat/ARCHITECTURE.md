# CVAT 架构建档

> 文档类型：首轮全量架构事实档案（只读源码建档）
>
> 目标项目：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/50_dataset_annotation_quality/cvat`
>
> 许可证：仓库根 `LICENSE` 为主依据；README 声明 CVAT Community 核心为 MIT。`serverless/` 中的模型及其第三方资产需逐项复核许可证，FFmpeg 相关组件受 LGPL/GPL 约束。
>
> 事实口径：本文把本地工作树与远程独立快照分开记录。远程快照不是本地工作树已经合入的代码，不能把远程新增能力当成本地基线。

## 1. 建档结论

CVAT（Computer Vision Annotation Tool）是一个以 Django/DRF 为后端、React/TypeScript 为前端、PostgreSQL 为主数据存储、Redis/Kvrocks + RQ 为异步任务基础设施、Traefik 为入口代理的计算机视觉数据标注平台。核心业务链为：

```text
组织/用户/权限
      ↓
项目 Project → 任务 Task → 数据 Data → 分段 Segment → 作业 Job
      ↓                         ↓             ↓
标签/属性 Label/Attribute      媒体文件       标注 Annotation
      ↓                                       ↓
质量控制 quality_control ← 共识 consensus ← 审核/验收
      ↓
REST API / Python SDK / CLI / React UI / Webhooks / Analytics
```

系统不是单体 HTTP 进程：Web API、前端、RQ worker、PostgreSQL、Redis（内存队列/缓存）、Kvrocks（持久缓存）、OPA、ClickHouse、Vector、Grafana 通过 Docker Compose 组成默认部署；Nuclio/serverless、外部对象存储、Helm/Kubernetes 属于可选扩展面。

**当前核对可复用的架构认识：**

1. `Project → Task → Job` 是协作和分工的主骨架；`Data`、`Segment`、标注对象和文件系统目录负责承载媒体与标注状态。
2. REST API 是后端唯一稳定边界；`cvat-core` 是前端/浏览器侧领域对象与 API 适配层，`cvat-sdk` 是 Python 客户端，`cvat-cli` 复用 SDK 做命令行操作。
3.质量控制不是单一分数函数，而是“设置/需求继承 → 数据提供 → 标注匹配 → 冲突/报告持久化 → API/UI 展示”的完整链路；共识是与质量控制并列、共享 `Task` 和标注数据的能力域。
4. 队列名和 worker 进程是业务能力的运行时分片：`import`、`export`、`annotation`、`webhooks`、`notifications`、`quality_reports`、`cleaning`、`chunks`、`consensus` 各自拥有 RQ 队列。
5. 远程 `develop` 明显领先本地副本，尤其是质量需求、音频工作区、Growth、新用户模型、OpenAPI 和测试资产；继续开发前应先裁决是否同步远程，不应在两套版本间混用接口。

## 2. 快照、版本与边界

### 2.1 本地工作树基线

- Git 分支：`develop`，跟踪 `origin/develop`。
- 本地 `HEAD`：`4aa0be3df5e888180d0d70004e9471423e540eae`。
- 本地最新提交：`Prevent source files from being modified by the Django user (#10575)`，时间 `2026-07-23T13:22:24+03:00`。
- `cvat/__init__.py:7-9`：`VERSION = (2, 71, 1, "alpha", 0)`，通过 `get_version` 生成 `__version__`。
- 本地源码盘点（排除 `.git`、`node_modules`、前端 `dist`）：约 2927 个文件，其中 Python 583、TypeScript 272、TSX 376、JavaScript 284、YAML 86、Markdown 195；`cvat/apps/` 有 14 个业务 app，Django migration Python 文件约 94 个。
- 建档开始时工作树除既有未跟踪的 `细探-cvat.md` 外无已知修改；该文件是调研留痕，不在当前核对修改范围。

### 2.2 远程独立快照

本地远程引用落后：

- `git ls-remote origin develop`：远程 `develop` 为 `c6a827cb3cc2a47d36c2c75197f2266ea5202d79`。
- 远程最新提交：`As/add new user model (#11023)`，时间 `2026-08-20T14:15:58+04:00`。
- 本地 `HEAD` 与远程快照之间为 452 个文件变更，统计约 `58970 insertions(+), 11227 deletions(-)`；该数字用于说明版本漂移，不表示当前核对修改。
- 已通过独立代理 `http(s)_proxy=http://127.0.0.1:4780` 创建远程快照：`/tmp/cvat-remote-snapshot`。
- 远程快照 `cvat/__init__.py:5-9` 为 `VERSION = (2, 73, 1, "alpha", 0)`。
- 远程快照源码盘点约 3021 个文件，其中 Python 620、TypeScript 292、TSX 383、JavaScript 292、YAML 87、Markdown 205；`cvat/apps/` 增至 15 个 app，migration Python 文件约 100 个。
- 远程快照 `cvat/schema.yml` 约 101 个 API path；本地同文件约 94 个 path。

**采用规则：**本文的“本地实现”引用目标目录当前代码；“远程现状/后续变化”引用 `/tmp/cvat-remote-snapshot` 对应 commit。远程快照只用于版本核对和架构细探，未复制回项目、未切换分支、未修改源码。

## 3. 真实目录结构与职责

```text
cvat/
├── cvat/                         # Django 项目与后端业务
│   ├── apps/                     # Django app：engine、IAM、组织、质量、事件等
│   ├── settings/                 # development/testing/production 基础配置
│   ├── requirements/             # base/development/production/testing 锁定依赖
│   ├── schema.yml                # 生成/维护的 REST OpenAPI Schema
│   ├── urls.py                   # 根路由和可选 app 路由装配
│   ├── asgi.py                   # ASGI 入口
│   ├── rqworker.py               # RQ worker 入口
│   ├── rq_patching.py            # RQ 行为补丁
│   └── nginx.conf                # 容器内 Nginx 配置
├── cvat-ui/                      # React + Redux + TypeScript 单页应用
├── cvat-core/                    # 前端领域对象、API facade、插件和请求管理
├── cvat-data/                    # 前端数据/解析/通用数据结构包
├── cvat-canvas/                  # 2D 标注画布
├── cvat-canvas3d/                # 3D/点云标注画布
├── cvat-sdk/                     # Python SDK；含生成的 API client 和高层 proxies
├── cvat-cli/                     # Python CLI；入口 cvat_cli.__main__:main
├── serverless/                   # Nuclio 模型函数（pytorch/onnx/openvino/tensorflow）
├── ai-models/                    # AI 模型说明/辅助资产
├── components/                   # analytics、serverless 的 Compose/配置/资产
├── helm-chart/                   # Kubernetes Helm 部署模板
├── supervisord/                  # server/worker/nginx 进程配置
├── backend_entrypoint.d/         # backend entrypoint 组件声明
├── backend_entrypoint.sh         # 容器 init/run/bash 调度入口
├── tests/python/                 # 真实服务 REST API、SDK、CLI 测试
├── tests/cypress/                # 浏览器端 E2E 测试
├── tests/docker-compose*.yml     # 测试依赖服务编排
├── utils/                        # dataset_manifest、DICOM、FFmpeg 等工具
├── site/                         # MkDocs/文档站内容与构建脚本
├── Dockerfile*                   # server、UI、CI 镜像构建
├── docker-compose*.yml           # 默认、开发、CI、HTTPS、外部 DB 编排
├── package.json                  # Yarn 4 workspace、前端构建/检查命令
├── yarn.lock                     # 前端锁定依赖
└── pyproject.toml                # Black/isort Python 工具约束
```

### 3.1 后端业务 app 清单（本地基线）

| app | 主要职责 | 主要持久化/接口特征 |
|---|---|---|
| `engine` | 核心领域模型、任务/项目/作业、媒体、标签、标注、文件、云存储、REST ViewSet | 最大业务 app；`models.py`、`views.py`、`serializers.py`、`urls.py`、大量 migration |
| `dataset_manager` | 标注 IR、导入/导出、任务数据读写、Datumaro/媒体处理、缓存和临时文件 | 主要是 service/binding/格式适配；无独立 `models.py` |
| `dataset_repo` | 已移除的 Git annotation storage 的迁移兼容壳 | README 明确仅保留 migration，未来 squash migrations 后可删除 |
| `iam` | 登录、注册、密码、认证、角色、OPA 规则、组织过滤 | `models.py`、认证/权限/序列化、`auth/` 路由 |
| `organizations` | 组织、成员、邀请、组织级权限和隔离 | `Organization`、`Membership`、`Invitation` |
| `quality_control` | 质量设置、质量需求、标注匹配、冲突、报告、质量指标 | `QualityReport`、`AnnotationConflict`、`QualitySettings`；通过 RQ 异步计算 |
| `consensus` | 多标注者共识设置与合并 | `ConsensusSettings`；提供 `merges`、`settings` 路由 |
| `events` | 事件记录、异常处理、事件导出、审计/分析输入 | `api/events` 及信号/处理器 |
| `webhooks` | Webhook 定义、事件分发、投递记录、重试和异步任务 | `Webhook`、`WebhookDelivery`；独立 RQ 队列 |
| `lambda_manager` | Nuclio/模型函数注册、调用、异步请求 | `functions`、`requests`、`api/lambda` |
| `access_tokens` | Personal Access Token、读写权限、Token 认证 | `auth/access_tokens` 路由 |
| `redis_handler` | RQ 请求状态、Redis migration、周期任务、请求 API | `requests`、`migrateredis`、`syncperiodicjobs` |
| `log_viewer` | 可选 analytics 日志/事件查看接口 | `CVAT_ANALYTICS=1` 时加入 installed apps |
| `health` | DB/cache/磁盘等健康检查和 worker probe | `api/server/health/`，无核心业务模型 |

远程快照额外加入 `growth` app，根路由把 `cvat.apps.growth.urls` 挂在 `api/` 下，暴露 `growth`，并把新用户模型接到 `AUTH_USER_MODEL` 体系；这属于远程 `2.73.1` 变化，不是本地 `2.71.1` 能力。

## 4. 分层架构

### 4.1 部署/进程层

默认 `docker-compose.yml` 定义以下运行单元：

- `cvat_db`：`postgres:15-alpine`，主业务数据库，卷 `cvat_db`。
- `cvat_redis_inmem`：`redis:7.2.11-alpine`，RQ 和默认缓存，6379。
- `cvat_redis_ondisk`：`apache/kvrocks:2.15.0`，持久化 chunk/preview 媒体缓存，6666。
- `cvat_server`：`cvat/server:${CVAT_VERSION:-dev}`，执行 `init run server nginx`，挂载 data/keys/logs。
- `cvat_worker_utils`：通知、清理等通用队列。
- `cvat_worker_import` / `cvat_worker_export`：数据导入、导出。
- `cvat_worker_annotation`：自动标注/annotation 队列。
- `cvat_worker_webhooks`：Webhook 发送和调度。
- `cvat_worker_quality_reports`：质量报告计算。
- `cvat_worker_chunks`：chunk/媒体缓存处理。
- `cvat_worker_consensus`：共识计算。
- `cvat_ui`：`cvat/ui:${CVAT_VERSION:-dev}`，前端容器，内部端口 8000。
- `traefik`：外部端口 8080，按 Host/PathPrefix 路由 UI 与 API。
- `cvat_opa`：`openpolicyagent/opa:1.12.2`，提供 IAM policy 数据服务。
- `cvat_clickhouse`：`clickhouse/clickhouse-server:23.11-alpine`，事件/analytics 存储。
- `cvat_vector`：`timberio/vector:0.26.0-alpine`，日志/事件转发。
- `cvat_grafana`：`grafana/grafana-oss:10.1.2`，analytics 仪表盘。

`Dockerfile` 的生产镜像基于 `ubuntu:24.04`，构建 OpenH264/FFmpeg/PyAV，安装 Python wheel 和运行时依赖，以非 root `django`（UID 1000）运行，入口为 `/opt/cvat/backend_entrypoint.sh`，容器暴露 8080。镜像还包含 Nginx、Supervisor、PostgreSQL client 依赖、对象存储/LDAP/XML/媒体处理所需系统库。

### 4.2 Django 初始化与进程入口

- `manage.py:10-20`：默认 `DJANGO_SETTINGS_MODULE=cvat.settings.development`，将命令交给 Django `execute_from_command_line`。
- `backend_entrypoint.sh:40-52` 的 `cmd_init`：等待 PostgreSQL → `django-admin migrate`；等待 Redis → `migrateredis`、`syncperiodicjobs`；analytics 开启时初始化 ClickHouse。
- `backend_entrypoint.sh:105-180` 的 `cmd_run`：校验 `server|worker|worker-pool|nginx`，server 先 `collectstatic`，所有进程等待数据库/Django migration/Redis migration 完成，再生成 Supervisor include 并启动对应进程。
- worker 队列由 `cvat/settings/base.py:326-406` 的 `CVAT_QUEUES`、`RQ_QUEUES` 声明；不同 worker 通过 Compose command 选择队列。
- Supervisor 配置位于 `supervisord/`，可复用配置位于 `supervisord/reusable/`；`backend_entrypoint.d/*.conf` 负责运行组件声明。

### 4.3 配置与基础设施层

`cvat/settings/base.py` 是后端架构的集中配置事实源：

- `BASE_DIR`、`DATA_ROOT`、`MEDIA_DATA_ROOT`、`TASKS_ROOT`、`PROJECTS_ROOT`、`JOBS_ROOT`、`CLOUD_STORAGE_ROOT`、`TMP_FILES_ROOT` 统一定义文件存储边界（约 `:34-35`、`:492-545`）。
- `INSTALLED_APPS` 注册 Django/DRF、RQ、allauth、health、`iam`、`dataset_manager`、`organizations`、`engine`、`dataset_repo`、`lambda_manager`、`webhooks`、`events`、`quality_control`、`redis_handler`、`consensus`、`access_tokens`（`:110-150`）。
- `REST_FRAMEWORK` 设定 JSON parser、CVAT renderer、登录/Token/Session/Basic authentication、Accept Header API versioning（默认 `2.0`）、分页、过滤、限流、`CustomAutoSchema` 和统一异常处理器（`:173-220`）。
- PostgreSQL 通过 `CVAT_POSTGRES_*` 环境变量配置；Redis 内存/持久缓存分别绑定默认缓存和媒体缓存；ClickHouse 通过 `CLICKHOUSE_*` 配置。
- 关键安全面：`SECRET_KEY` 从环境变量或 `keys/secret_key.py` 读取；`load_secret_key` 使用 AST + `ast.literal_eval`，只允许单一 `SECRET_KEY` 赋值，拒绝执行任意代码（`:72-108`）。
- `ALLOWED_HOSTS`、`CVAT_NUM_PROXIES`、CSRF/CORS、上传大小、TUS 最大文件、Forwarded Proto、`SMOKESCREEN_ENABLED` 均由 settings 控制。

## 5. 核心领域模型与数据流

### 5.1 主业务实体

`cvat/apps/engine/models.py` 是本地基线的核心模型集合：

```text
User / Organization
       │
       ├── Project ── Label ── AttributeSpec
       │       │
       │       └── Task ── Data ── Image / Video / Audio / RelatedFile
       │                    │
       │                    └── Segment ── Job
       │                                  │
       │                                  ├── LabeledImage (tag)
       │                                  ├── LabeledShape / TrackedShape
       │                                  ├── LabeledTrack
       │                                  └── LabeledInterval
       │                                         └── AttributeVal
       └── CloudStorage / Storage / Issue / Comment / AnnotationGuide / Asset
```

关键事实：

- `Project`：项目名称、owner、状态、组织、source/target `Storage`，通过 `get_dirname()` 映射到 `PROJECTS_ROOT/<id>`。
- `Task`：可隶属于 `Project`，绑定 `Data`、owner/assignee、维度（`1d/2d/3d`）、模式（`annotation/interpolation`）、媒体类型（`image/point_cloud/audio`）、segment size、组织和存储。
- `Data`：媒体元数据、帧范围、过滤器、删除帧、chunk 类型/质量、缓存/文件系统/云存储策略；以 `MEDIA_DATA_ROOT/<id>` 管理 raw/original/compressed 缓存。
- `Segment`：把 Task 的帧区间切分为作业边界。
- `Job`：标注、验证、验收的工作单元，有 `stage`、`state`、`type`、assignee、parent job；`TaskQuerySet.with_job_summary()` 提供作业聚合。
- `Label`、`Skeleton`、`AttributeSpec`：描述可标注对象和属性约束；skeleton 通过 parent/sublabel 形成层次。
- 标注分为 tag（`LabeledImage`）、shape（`LabeledShape`）、track（`LabeledTrack` + `TrackedShape`）和 interval（`LabeledInterval`），各类 attribute value 单独持久化。
- `AnnotationIR` + `AnnotationManager` 是导入/导出/写回数据库的中间表示；`JobAnnotation` 负责数据库与 IR 之间的批量读写、校验、层级/轨迹修正和更新事件。
- `CloudStorage` 支持 AWS S3、Azure Blob Storage、Google Cloud Storage；`Storage` 选择 local/share/cloud_storage，任务可将本地文件迁移到 backing cloud storage。

### 5.2 质量控制与共识

本地基线：

- `QualitySettings`：以 Task 或 Project 为粒度的 OneToOne 设置，包含 `iou_threshold`、`oks_sigma`、线/组/遮挡/属性比较、`target_metric`、阈值、job filter 等，并有 `task_or_project` check constraint。
- `QualityReport`：目标只能是 Job/Task/Project 之一（`job_or_task_or_project` check constraint），保存目标更新时间、GT 更新时间、assignee、JSON `data`，可通过 self M2M 组织父子报告。
- `AnnotationConflict`：按 frame、冲突类型、严重级别记录差异；`AnnotationId` 指向具体 job/object/type/shape。
- `quality_control` 的计算入口由 `quality_reports.py`、`quality_calculators.py`、`annotation_matching.py`、`comparison_report.py`、`data_providers.py` 和 RQ 队列协作，输出 accuracy/precision/recall 等质量指标及冲突详情。
- `consensus.ConsensusSettings` 以 Task 为粒度保存 IoU 阈值；共识合并通过 `merges` 接口与 `cvat_worker_consensus` 处理。

远程 `c6a827c` 已把质量域明显扩展为质量需求树：`QualityRequirement` 支持 parent/child、字段继承、JSON Logic filter 合并、需求排序和目标 metric；`quality_handlers.py` 中的 `resolve_effective_requirement(s)` 负责检测父链、环、缺失父节点并生成 `EffectiveQualityRequirement`。远程还将质量 API/UI/测试资产大幅扩展。此部分必须以远程版本为基线后再迁移，不能直接把远程新文件拷贝进本地 2.71.1。

### 5.3 事件、Webhook 与异步请求

- 标注/任务/用户等变更通过 signals/handlers 进入 `events`，可导出到 analytics。
- Webhook 由 `Webhook` 配置目标 URL、事件、内容类型、secret、owner/project/organization；`WebhookDelivery` 记录 status code、attempt、duration、request/response/changed fields。
- 异步 API 在 Redis/RQ 中生成 Request 状态，客户端通过 `/api/requests` 查询、监听或取消；`cvat-sdk.core.client.Client.wait_for_completion()` 轮询至 `FINISHED`/`FAILED`。
- 长任务一般不在 HTTP 请求内完成：导入/导出、自动标注、质量报告、共识、webhook 发送和 chunk 处理由不同队列的 worker 完成。

## 6. API、契约与入口

### 6.1 后端路由装配

`cvat/urls.py:25-57` 是根路由：

- `/admin/`：Django admin。
- 根路径包含 `cvat.apps.engine.urls` 和 `cvat.apps.redis_handler.urls`。
- `/django-rq/`：RQ 管理界面。
- 可选地挂载 `log_viewer`、`events`、`lambda_manager`、`webhooks`、`quality_control`、`consensus`、`access_tokens`、health check。

`cvat/apps/engine/urls.py` 注册本地主 REST Router：`projects`、`tasks`、`jobs`、`users`、`server`、`issues`、`comments`、`labels`、`cloudstorages`、`assets`、`guides`，并公开 `/api/schema/`、`/api/swagger/`、`/api/docs/`。

各业务路由：

| 路由模块 | 主要前缀/资源 |
|---|---|
| `iam/urls.py` | `login`、`logout`、`register`、`auth/`、密码 reset/change、`rules` |
| `organizations/urls.py` | `organizations`、`invitations`、`memberships` |
| `quality_control/urls.py` | `/api/quality/reports`、`conflicts`、`settings` |
| `consensus/urls.py` | `/api/consensus/merges`、`settings` |
| `events/urls.py` | `/api/events` |
| `webhooks/urls.py` | `/api/webhooks` |
| `lambda_manager/urls.py` | `/api/lambda/functions`、`requests` |
| `access_tokens/urls.py` | `/api/auth/access_tokens` |
| `redis_handler/urls.py` | `/api/requests` |

### 6.2 OpenAPI

- 本地 `cvat/schema.yml` 是 REST contract 的静态快照，约 12014 行、94 个 path。
- 远程快照为约 13616 行、101 个 path，增加 Growth 和质量需求等远程演进内容。
- `drf-spectacular` 在运行时通过 `/api/schema/` 生成 schema，并通过 `/api/swagger/` 和 `/api/docs/` 提供可视化文档。
- 修改 serializer/view/model 后必须把 schema、SDK 生成代码、UI/client 适配和测试一起视为同一契约面；只改其中一个层会造成接口漂移。

### 6.3 典型请求链

```text
Browser / SDK / CLI
  → Traefik :8080
  → cvat_ui 或 cvat_server(Nginx)
  → Django middleware
  → DRF authentication + PolicyEnforcer + organization filter
  → ViewSet / serializer
  → engine/service/quality domain logic
  → PostgreSQL transaction + file/cloud storage
  → event signal / webhook / RQ Request
  → JSON response 或异步 request id
```

权限边界位于 DRF 默认 permission（`IsAuthenticated` + `PolicyEnforcer`）、IAM/organization filter、每个 app 的 permissions、OPA policy 多层；不要把 serializer 校验当作完整授权。

## 7. 客户端与开发者接口

### 7.1 `cvat-core`

`cvat-core/src/api.ts` 定义前端领域 facade：server、projects、tasks、jobs、frames、users、apiTokens、plugins、actions、lambda、organizations、webhooks、consensus、analytics、requests 等。`api-implementation.ts` 将 facade 方法绑定到 `server-proxy`、`lambda-manager`、`requests-manager`，做过滤字段校验、snake/camel 转换、分页资源包装、服务器 schema 描述转换和领域对象实例化。

`cvat-core/package.json`：ES module，TypeScript，依赖 `axios`/`axios-retry`/`tus-js-client`/`dompurify`/`quickhull` 等，主入口 `src/api.ts`。

### 7.2 `cvat-ui`

`cvat-ui/src/index.tsx:41-161`：创建 Redux store/root reducer，初始化 dayjs，加载 about、auth、formats、models、plugins、organizations、invitations、requests、API schema，挂载 `BrowserRouter`、`PluginsEntrypoint`、`CVATApplication` 和 `LayoutGrid`。

`cvat-ui/package.json`：React 18、Redux/Thunk、Ant Design、React Router、Webpack、TypeScript、Cypress 生态；通过 Yarn workspace 依赖 `cvat-core`、`cvat-canvas`、`cvat-canvas3d`。

### 7.3 画布与数据包

- `cvat-canvas`：2D SVG/annotation canvas、绘制/交互/掩码/多边形工具。
- `cvat-canvas3d`：Three.js、camera-controls、点云/3D 场景。
- `cvat-data`：前端数据和压缩/归档工具，使用 `async-mutex`、`jszip`。
- UI 不直接拼接后端 REST 细节，通常经 `cvat-core`/`cvat-store`/actions/reducers；画布消费 `cvat-core` 的领域对象和 annotation states。

### 7.4 `cvat-sdk` 与 `cvat-cli`

- `cvat-sdk`：Python `>=3.10`；生成代码位于 `cvat_sdk/api_client`、`models`，高层客户端在 `cvat_sdk/core/client.py`，资源代理包括 `TasksRepo`、`ProjectsRepo`、`JobsRepo`、`UsersRepo`、`OrganizationsRepo`、`IssuesRepo`、`CommentsRepo`。`Client` 支持 session/password、PAT、organization context、服务器版本检查和异步 request 等待。
- 自动标注契约位于 `cvat_sdk/auto_annotation/interface.py`：detection/interaction/tracking/function spec/context/result，要求 label/attribute id、shape 类型、confidence 和 prompt 约束；模型实现不能绕过这些契约直接写数据库。
- `cvat-cli/pyproject.toml` 暴露 `cvat-cli = "cvat_cli.__main__:main"`；`cvat_cli.__main__.main()` 解析命令、建立 client、执行 `COMMANDS`，将 API/HTTP/认证错误转成退出码 1。
- SDK/CLI 版本要与 server API major/minor 兼容；远程 SDK 的 `Client.SUPPORTED_SERVER_VERSIONS` 已围绕远程版本变化，本地升级前应重新生成并跑兼容性测试。

## 8. AI/模型与外部集成

- `lambda_manager` 通过 Nuclio 访问模型函数；`settings.NUCLIO` 支持 direct/dashboard invoke，默认超时 120 秒。
- `serverless/` 提供 PyTorch、ONNX、OpenVINO、TensorFlow 模型函数样例，例如 SAM、IOG、RetinaNet、HRNet、TransT、YOLO、Mask R-CNN/Faster R-CNN。
- `cvat/apps/engine/cloud_provider.py` 抽象云存储，当前 README/配置覆盖 AWS S3、Azure Blob、Google Cloud。
- `events → Vector → ClickHouse → Grafana` 是可选 analytics 链；`CVAT_ANALYTICS=1` 时后端加入 `log_viewer`。
- OPA 通过 `/api/auth/rules` bundle 与后端服务关联；授权策略代码在 app 的 `rules/*.rego`。
- Webhooks 为外部系统反向通知出口；REST API、SDK、CLI 为主动调用出口。

## 9. 测试、验证与质量门

### 9.1 Python 真实服务测试

`tests/python/README.md` 明确测试不是单进程 fake server：CVAT、OPA、Redis、PostgreSQL、Nuclio 等通过 Docker 组成测试环境，测试直接调用 REST API，运行：

```bash
pip install -r ./tests/python/requirements.txt
pytest ./tests/python
```

`tests/python/pytest.ini`：严格 pytest 配置，必须有 `pytest-timeout`、`pytest-cases`，默认单测试超时 15 秒，支持 `with_external_services` marker。`conftest.py` 强制导入 `shared.fixtures`；测试资产包括 JSON fixture、数据库 dump/restore SQL、`cvat_data.tar.bz2` 和对象存储数据。

本地盘点约 85 个 Python 测试文件，覆盖 `rest_api`、`sdk`、`cli`、app 单元测试和 shared fixtures。测试数据库通常在测试函数间恢复以避免状态污染；新增对象应同步更新 JSON/DB/data volume 资产。

### 9.2 Cypress/E2E 与前端检查

本地约 271 个 Cypress JavaScript 测试文件，覆盖 task/project/user/organization、标注工具、音频、3D、webhook、质量控制等；配置分散在 `tests/cypress*.config.js`。前端根 `package.json` 提供：

```bash
yarn lint
yarn type-check
yarn build:cvat-ui
yarn build:cvat-core
yarn build:cvat-canvas
yarn build:cvat-canvas3d
yarn build:cvat-data
```

### 9.3 文档/代码门

- Python 格式：根 `pyproject.toml` 的 Black/isort，行宽 100，serverless 排除 import 排序。
- JavaScript/TypeScript：ESLint、Stylelint、Prettier、TypeScript `tsc`。
- Markdown/site：remark 配置及 `site/` 构建。
- GitHub workflows：`main.yml`、`full.yml`、`linters.yml`、`docs.yml` 等；CI 依赖 Docker、浏览器/Node/Python、外部服务或服务容器。
- 未经需求授权不应在本类源码参考库启动完整 Docker stack、安装第三方依赖、生成数据库/模型产物或修改测试资产；架构建档当前核对不做运行时验收。

## 10. 关键风险、漂移与后续裁决点

### 阻断/高风险

1. **版本漂移阻断继续开发**：本地 2.71.1 与远程 2.73.1 相差数百文件；质量需求、Growth、新用户模型、OpenAPI、SDK/UI contract 已发生变化。必须先决定“按本地锁定版本建模”还是“先同步远程再建档”，禁止选择性复制远程文件。
2. **多进程依赖面大**：数据库、两个 Redis 语义、RQ、OPA、Nuclio、ClickHouse、Vector、Grafana 共同决定运行行为；单元测试通过不等于部署可用。
3. **大型 `engine` 聚合**：核心模型、序列化、视图、缓存、媒体、云存储和标注逻辑集中在 `cvat/apps/engine`，领域边界通过模块约定而非独立服务强隔离。改动 engine 需同步 migration、schema、SDK、UI 和 REST tests。
4. **数据与文件双写一致性**：Task/Data/Job 元数据在 PostgreSQL，媒体/chunk/cache/exports 在文件系统、share 或 cloud storage；需关注事务提交与 `transaction.on_commit` 文件清理顺序、重试和孤儿文件。
5. **质量计算资源和结果可追溯性**：质量报告存 JSON + 冲突明细，计算依赖 Datumaro/numpy 等数据处理库和 RQ worker；修改指标/需求继承时必须保持旧报告可解释、异步失败可追踪。

### 重要风险

- `dataset_repo` 名称容易误导：当前不是 Git 同步功能，只是删除旧表的迁移兼容 app。
- `schema.yml`、DRF 自动 schema、生成 SDK、`cvat-core` server response types 多处描述同一接口，存在重复事实源，接口变更必须进行契约联检。
- 本地 `cvat/apps/quality_control` 与远程新质量需求结构差异很大；远程删除/拆分 `quality_reports.py`、新建 handler/requirement 相关模块时需先做迁移设计。
- 生产镜像编译 FFmpeg/PyAV、lxml/xmlsec 等本地 C 扩展，跨平台构建和依赖缓存是高成本点。
- 密钥、云存储 credentials、JWT/session、OPA policy、Webhook secret 是不同安全边界；不能只靠 `SECRET_KEY` 保护所有外部集成。

### 建议/可复用模式

- 以 `Project → Task → Segment → Job` 建立任务分解和交付审核的领域模板。
- 借鉴 `AnnotationIR`：输入/输出采用稳定中间表示，格式适配器与数据库模型隔离。
- 借鉴 RQ queue + Request 状态：长任务返回 request id，客户端统一轮询/取消/失败呈现。
- 借鉴质量域的“设置继承 + 数据提供 + 匹配 + 冲突 + 报告”分层，而不是把质量分数直接塞进任务模型。
- 借鉴 `cvat-core` 的 facade + `server-proxy`：前端领域对象不直接散落 REST 字段转换。
- 借鉴 `Client.check_server_version()`：客户端在运行前主动检查 server/API 兼容性。
- 借鉴 `backend_entrypoint.sh` 的 migration barrier：server/worker 都必须等待 DB/Redis migration 完成后再服务。

## 11. 常用入口与排查路径

| 问题 | 首查文件 |
|---|---|
| 服务如何启动 | `backend_entrypoint.sh`、`supervisord/*.conf`、`docker-compose.yml` |
| Django app 是否启用 | `cvat/settings/base.py:110-150` |
| API 总路由 | `cvat/urls.py`、`cvat/apps/engine/urls.py`、各 app `urls.py` |
| API 精确契约 | `cvat/schema.yml`、DRF serializer/view、`cvat-sdk` 生成 models |
| 项目/任务/作业/标注数据模型 | `cvat/apps/engine/models.py`、`cvat/apps/dataset_manager/` |
| 质量与共识 | `cvat/apps/quality_control/`、`cvat/apps/consensus/` |
| 权限和组织隔离 | `cvat/apps/iam/`、`cvat/apps/organizations/`、`rules/*.rego`、`PolicyEnforcer` |
| 异步任务/请求 | `cvat/settings/base.py` 的 `CVAT_QUEUES/RQ_QUEUES`、`rqworker.py`、`redis_handler/`、`apps/*/rq.py` |
| 前端 API/领域对象 | `cvat-core/src/api.ts`、`api-implementation.ts`、`server-proxy.ts` |
| 前端启动与状态 | `cvat-ui/src/index.tsx`、`reducers/`、`actions/` |
| Python 自动标注插件契约 | `cvat-sdk/cvat_sdk/auto_annotation/interface.py` |
| 测试环境与资产恢复 | `tests/python/README.md`、`tests/python/conftest.py`、`tests/docker-compose*.yml` |
| 版本/发布变化 | `cvat/__init__.py`、`CHANGELOG.md`、`changelog.d/`、远程 commit |

## 12. 当前核对执行记录

- 已读取：根 README、既有 `细探-cvat.md`、规则文件检索结果、根目录布局、Django settings、根 URL、Dockerfile、Compose、入口脚本、engine/quality/consensus 模型、dataset manager、SDK/CLI/UI/core/data/canvas 包配置、Python/Cypress 测试说明与配置、依赖锁定文件、OpenAPI schema 统计。
- 已核对：本地 Git 基线、远程 `origin/develop`、远程提交差异；远程领先时使用 4780 代理建立了独立快照 `/tmp/cvat-remote-snapshot`。
- 未做：未安装依赖，未启动 Docker/服务，未构建前端/镜像，未执行数据库迁移，未改源码/依赖/测试/配置，未提交 Git。
- 当前核对唯一目标文件：`ARCHITECTURE.md`。
- MCP 状态：`project_context` 当前绑定的是另一个工程 `华世王镞_v3`；对目标路径调用 `codegraph_explore` 返回“目标项目没有 `.codegraph/` 索引”；`development_start` 因当前 MCP 仓库根与目标仓库不一致被拒。故本文事实来自目标目录本地只读工具与 4780 独立快照，不引用其他仓库的地图或证据。

## 13. 版本化维护规则

1. 先记录本地 `HEAD`、远程 commit、`cvat/__init__.py` 版本，再更新本档。
2. 后端模型/serializer/view/URL 变化必须联动 migration、`schema.yml`、SDK 生成物、`cvat-core` response types、UI actions/reducers 和相关测试。
3. 队列名、Request 状态、文件根目录、云存储策略属于运行时契约；不要只改 settings 或 Compose 的一侧。
4. `ARCHITECTURE.md` 只记录已由源码/配置/测试证明的事实；推测、未合入远程功能和建议必须明确标注。
5. 参考库用途是提取边界、契约和可验证模式，不把 CVAT 直接复制成生产底座，也不建立第二套任务/记忆/知识中心。

## 14. 旧细探吸收对照（本文件为唯一长期事实源）

`细探-cvat.md` 已完整读取，但按任务要求保留在仓库中作为原始调研留痕；后续维护只更新本 `ARCHITECTURE.md`，不把旧细探当作第二个架构事实源。对照结论如下：

| 旧细探内容 | 本档吸收位置 | 裁决 | 证据/边界 |
|---|---|---|---|
| Project → Task → Job 主骨架 | §1、§5.1、§15 | 吸收 | `cvat/apps/engine/models.py:918-1056,1178-1230` |
| `quality_control` 质量控制 | §5.2、§15.2、§16 | 吸收并加深 | `cvat/apps/quality_control/views.py:323-413`、`quality_reports.py:2586-2653` |
| `consensus` 多标注者共识 | §5.2、§15.3、§16 | 吸收并加深 | `cvat/apps/consensus/merging_manager.py:37-149` |
| `iam` + `organizations` 权限/组织 | §4.3、§6、§15.1 | 吸收 | `cvat/settings/base.py:173-220`、`cvat/urls.py:25-57`；策略细节仍需运行环境验证 |
| `events` + `webhooks` 集成 | §5.3、§8、§15.4、§16 | 吸收并加深 | `cvat/apps/webhooks/dispatch.py:14-24`、`tasks.py:14-38`、`utils.py:68-102` |
| `lambda`/serverless ML 预标注 | §8、§15.5 | 吸收为可选边界 | `cvat/settings/base.py:408-420`；未启动 Nuclio，端到端未验证 |
| “高质量标注数据”目标 | §1、§5.2 | 吸收为产品定位，不当作运行结果 | 质量报告需 Ground Truth 与异步计算条件；不存在当前核对实测指标 |
| 仅列目录、旁路线索、平台借鉴点 | §3、§10、§17 | 吸收为路径索引/裁决 | 未把 README 或宣传性描述当实现证据 |
| “社区 MIT / Enterprise 商业”概括 | §2、§17 | 部分吸收 | 许可证以根 `LICENSE` 和各第三方资产逐项复核为准，不能由旧细探概括推出全部资产许可 |

**不吸收为事实的内容：**旧细探中的“实时进度追踪”“审核流”“多租户隔离”“共识=证据可信”等表述只有在对应源码契约、权限、状态和测试证据支持的范围内成立；它们不证明部署成功、质量指标正确或失败恢复完整。旧细探没有独立覆盖的版本漂移、RQ request id/队列路由、取消限制、文件与数据库双写、测试外部服务门禁，均已在本档补齐。

## 15. 真实契约、对接链与关键节点

### 15.1 HTTP/API 入口契约

| 入口/能力 | 输入与前置 | 输出/状态 | 错误、重试、取消、幂等 | 真实 owner |
|---|---|---|---|---|
| REST 资源 API | HTTP JSON；默认需认证、Token/PAT/Session/Basic 之一；Accept API version `2.0` | DRF serializer JSON、分页；默认 page size 10 | serializer/permission/组织过滤/限流/统一异常共同决定失败；当前核对未运行服务，HTTP 码未实测 | `cvat/settings/base.py:173-220`、`cvat/urls.py:25-57`、`cvat/apps/engine/urls.py` |
| `POST` 质量报告创建 | `task_id` 或 `project_id`；Task 必须 2D 且有 acceptance/completed GT；Project 无此前置 | `202` + `rq_id`；查询完成后 `201` + report；非法输入 `400` | 同一 request id 的现有 queued/started/deferred 返回 `409`；RQ failed 转 `500` 并删除 job；取消走 `/api/requests/{id}/cancel`，已启动作业通常不可取消 | `quality_control/views.py:323-413`、`quality_reports.py:2586-2653` |
| `/api/requests/{rq_id}` | 合法新格式或兼容 legacy request id；需通过 owner 权限 | `200` request 状态/消息/进度；取消/停止态读回为 `404` | Redis 不可用 `503`；缺失 id `404`；状态机由 RQ 实际状态驱动 | `redis_handler/views.py:200-271` |
| `POST /api/requests/{id}/cancel` | 作业存在且调用者有权限 | queued/deferred 直接取消并 `200`；生产 worker 中可停止的 export 可发 stop command | started 仅允许非变更 export 且 worker 标记可停；其他 started、finished、failed、scheduled 返回 `400`；代码标注 queued 取消存在竞态 | `redis_handler/views.py:289-349` |
| Webhook 投递 | active Webhook、事件 payload；可选 secret 签名 | `WebhookDelivery` 持久化 status/request/response/attempt/duration | HTTP 连接异常→502、超时→504；5xx/408/429 抛 `WebhookDeliveryError` 交给 RQ Retry；单次 timeout `(3,10)`、响应体上限 1MiB；无端到端回放证据 | `webhooks/utils.py:22-23,68-102`、`tasks.py:14-38`、`dispatch.py:14-24` |
| SDK `Client.wait_for_completion` | `rq_id`；轮询周期默认 5 秒 | `FINISHED` 返回 request/HTTP response | `FAILED` 抛 `BackgroundRequestException`；当前实现对未知/取消/停止状态没有显式终态分支，会继续轮询，需运行探针确认实际行为 | `cvat-sdk/cvat_sdk/core/client.py:220-248` |
| CLI | argparse 命令树；需要远端的命令通过 `build_client` 建立 SDK client | 成功返回 0 | API/HTTP/Critical/AuthStore 异常记录 critical 并返回 1；上下文管理器关闭 client | `cvat-cli/src/cvat_cli/__main__.py:26-57` |

### 15.2 质量报告真实对接链

```text
POST /api/quality/reports
  → QualityReportViewSet.create
  → QualityReportCreateSerializer 校验 task/project
  → QualityReportRQJobManager.enqueue_job
  → AbstractRequestManager：POST 校验 → target 校验 → QualityRequestId → job lock/同 ID 去重
  → RQ queue `quality_reports`
  → QualityReportManager._check_task_quality / _check_project_quality
  → TaskQualityCalculator/ProjectQualityCalculator.compute_report
  → QualityReport + AnnotationConflict 数据库记录
  → `/api/requests/{rq_id}` 查询 RQ 状态或按 rq_id 回读 report
  → QualityReportSerializer / `/data` 导出
```

关键事实：Task 质量报告的前置条件写在 `quality_reports.py:2610-2627`；任务/项目报告的计算结果由 `QualityReportManager:2640-2653` 返回 report id；质量报告的权限在创建、按 id 查询和冲突列表各自检查，不能把“有 endpoint”当作绕过 IAM 的证据。

### 15.3 共识合并真实对接链

```text
POST consensus merge
  → MergingManager.validate_request
  → _TaskMerger.check_merging_available
  → RQ queue `consensus`（ConsensusRequestId）
  → _TaskMerger._merge_consensus_jobs
  → JobDataProvider → Datumaro Dataset
  → IntersectMerge（IoU/OKS/属性忽略规则）
  → transaction.atomic：清空 parent annotations
  → import_dm_annotations → patch_job_data
  → parent annotation job state = completed
```

`_TaskMerger` 只允许开启 consensus、2D task、存在已非 new 的 replica；合并前会清空 parent job 原标注，随后导入并 patch，故“合并失败/崩溃发生在清空之后”的中间状态必须依赖事务与现场数据库测试确认，不能仅凭函数名宣称安全回滚。源码证据：`consensus/merging_manager.py:37-61,95-149`。

### 15.4 Webhook 真实对接链

```text
事件/导出状态变化
  → select_webhooks / batch_add_to_queue
  → `django_rq.get_queue(webhooks)`
  → RQ Retry(max=len(SEND_WEBHOOK_TASK_RETRIES), interval=...)
  → tasks.send_webhook
  → active webhook lookup
  → services.send_webhook
  → perform_webhook_request(timeout=(3,10), stream=True, 1MiB cap)
  → WebhookDelivery.objects.create
  → 5xx/408/429 抛异常触发 RQ 重试
```

Webhook 投递记录是结果账本，但不是 exactly-once 保证：队列重试、对端已收到但本地写 Delivery 前崩溃、重复 redelivery 都可能产生重复外部副作用；本地源码未证明下游幂等键存在。`webhooks/dispatch.py:14-24` 的 failure TTL 为 7 天，不能等同于业务数据永久保留。

### 15.5 启动与部署对接链

```text
docker compose
  → cvat_server: `init run server nginx`
       init: wait DB → django migrate → wait Redis → migrateredis/syncperiodicjobs
       run server: collectstatic → wait DB/migration/Redis migration → Supervisor server config
       nginx: Supervisor nginx config
  → cvat_worker_*: wait DB/migration/Redis migration → Supervisor worker config
  → queue-specific worker consumes RQ
```

`backend_entrypoint.sh:40-52,105-180` 是 migration barrier 的实现证据；Compose 的 `depends_on: service_started` 只说明容器启动顺序，不等于数据库可用或 migration 完成。worker 队列和默认超时来自 `cvat/settings/base.py:326-406`。

### 15.6 关键小节点表

| 节点 | 前置/状态变更 | 读写与并发 | 失败/恢复 | 证据 |
|---|---|---|---|---|
| `AbstractRequestManager.enqueue_job` | 只接受 POST；生成 request id；同 id 现有运行态返回 409；成功后返回 202 | 读 RQ；job id lock + user lock；写 RQ job/meta/dependency | scheduled 旧 job 取消后删除；started 不会被重新排队 | `redis_handler/background.py:119-200` |
| `BaseRQMeta.build` | 从 request/db object 派生 user/request/org/project/task/job 元数据 | 写入 RQ meta；部分 queue job 没有 user/request 信息 | 元数据字段 optional；不能把缺少 owner 当权限证明 | `engine/rq.py:205-293` |
| `QualityReportRQJobManager.validate_request` | Project 放行；Task 必须 2D + GT acceptance/completed | 读 Task/Job；不在 HTTP 线程算质量 | 不满足条件抛 serializer ValidationError | `quality_reports.py:2610-2627` |
| `_TaskMerger._merge_consensus_jobs` | 已启用 consensus/2D/replica 非 new | 读多个 JobDataProvider/Datumaro；事务中清 parent 标注、写回 merged 标注、更新 parent state | `MergingNotAvailable` 在执行前阻断；执行中异常回滚需 DB 现场验证 | `consensus/merging_manager.py:95-149` |
| `perform_webhook_request` | webhook target/secret/SSL 配置 | 建立 requests session；读外部响应流；随后保存截断后的 body | ConnectionError/Timeout 映射 502/504；其他 requests 异常未在此函数显式映射 | `webhooks/utils.py:68-102` |
| Task/Data 删除 handler | Django delete 已提交后才做文件清理；Data 先抓媒体相对路径 | DB 行与本地/云文件是两个资源域 | `transaction.on_commit` + `ignore_errors=True`；文件清理失败可能静默留下孤儿 | `engine/signals.py:96-155` |

## 16. 资源生命周期与失败矩阵

### 16.1 资源生命周期表

| 资源 | 创建/持有 | 成功释放 | 失败/超时/取消/崩溃风险 | 当前核对状态 |
|---|---|---|---|---|
| PostgreSQL 行/事务 | Django ORM、`transaction.atomic`；Task/Job/QualityReport/Delivery 写入 | commit 后持久化；rollback 由事务边界处理 | 进程崩溃可回滚 DB 未提交部分，但已提交文件/外部请求不随 DB 回滚；未做真实 DB 探针 | 源码存在，运行未验证 |
| Task/Job/Data 文件目录 | `TASKS_ROOT`、Data upload dir、Job/Project dir | post-delete `on_commit` `shutil.rmtree`；云存储搬迁在 commit 后清理本地 | `ignore_errors=True` 隐藏清理失败；commit 前崩溃与孤儿文件对账未验证 | 源码存在，失败清理未验证 |
| 云存储对象 | `bulk_upload_from_dir`/`bulk_download_to_dir` | commit 后 `bulk_delete` 或本地文件删除 | 外部对象存储成功而 DB 保存失败、反向失败、重试幂等未证明 | 源码存在，外部服务未验证 |
| RQ job/队列/依赖 | `enqueue_call` 写入 Redis，job meta 含用户/对象/request | finish/failure TTL 或显式 delete；queued cancel delete | Redis 宕机→API 503；worker 崩溃、过期、重复投递和依赖唤醒需运行验证；质量失败回读会 delete job | 源码存在，未实测 |
| Webhook HTTP session/response | `make_requests_session` + `stream=True`；读取最多 1MiB | `with` 退出 session；响应流读完/关闭由 requests 管理 | 对端已收到后本地崩溃可重复发送；DNS/SSL/非 timeout 异常分类不完整 | 源码存在，未实测 |
| Datumaro/annotation 中间数据 | `JobDataProvider.dm_dataset`、`AnnotationIR`/patch | 函数返回后由 Python 引用释放；数据库标注在事务提交后保留 | 大数据内存峰值、清空后计算失败、worker crash 的恢复与磁盘临时目录未对账 | 源码存在，未实测 |
| Supervisor/worker 进程 | entrypoint 生成 include，Supervisor 持有 | 正常退出/容器 restart | worker kill、僵尸、队列重试与半成品产物未做现场检查；Compose `restart: always` 不是业务恢复证明 | 部署声明，未实测 |
| OPA/ClickHouse/Vector/Nuclio | Compose 外部服务或可选扩展 | 由各自容器/客户端管理 | 未启动；不可将 service_started 或配置项当可用证据 | 仅声明/配置 |

### 16.2 失败/超时/取消/崩溃矩阵

| 场景 | 源码已有行为 | 未证明/剩余风险 |
|---|---|---|
| 非法参数/错误目标 | serializer、目标类型和 2D/GT 前置校验；无效 request id 返回 404/ValidationError | 各 API 错误 payload 的稳定 schema、全路由覆盖未运行验证 |
| 重复提交同一后台操作 | request id 由 action/target/target_id 等字段渲染；job lock + 已运行 job 409 | 不同 payload 是否语义等价、旧 finished job 的删除再重算是否符合业务预期需探针 |
| Redis 不可用 | `/api/requests` 装饰器返回 503 | enqueue 路径及 worker 恢复、丢 job/重连行为未实测 |
| worker/第三方失败 | RQ failure metadata/异常 handler；Webhook 5xx/408/429 重试；质量 failed→500 | 每队列重试策略、失败后副作用回滚/孤儿文件、重启续跑未形成实测证据 |
| 超时 | 队列默认 timeout：import/export 4h、annotation 24h、webhooks 25s、quality/consensus 1h、chunks 5m；Nuclio 120s；Webhook connect/read `(3,10)` | 质量计算/导入导出超时后 DB/文件一致性和 SDK 终态行为未验证 |
| 排队取消 | queued/deferred 可 cancel 并删除；依赖可按设置继续 | 代码明确标注竞态；取消与 worker 同时取 job 的竞态未验证 |
| 运行中取消 | 仅生产 worker 的可停止 export 发 stop command | 非 export 不能取消；worker 标记缺失时默认“可停止”，线上兼容语义需实测 |
| 进程崩溃 | 容器 restart；RQ 可能留下 failed/stopped job；DB 未提交事务可回滚 | 进程组、锁、临时目录、部分导出/媒体/云对象、重复 webhook 未做现场对账 |
| 外部 webhook 已收到但本地失败 | Delivery 在 HTTP 后创建；RQ 可重试 | exactly-once 不成立；下游必须自行幂等，源码未发现统一幂等键 |
| 共识清空后合并失败 | `_merge_consensus_jobs` 在 `transaction.atomic` 中执行 | 事务是否覆盖 Datumaro 导入、数据库批量写和所有副作用需真实测试；不能由静态阅读升级为通过 |

## 17. 防假绿验证分级（L0-L4）

本档不把“源码存在”、测试文件、历史日志或子代理自报当作运行通过。CVAT 当前核对没有安装依赖、启动 Docker 或连接外部服务，所有高等级均明确为未执行。

| 等级 | 允许声称 | 本地证据 | 当前核对结论 |
|---|---|---|---|
| L0 | 源码/配置/文档存在 | 目标路径文件读取、函数/类/路由和 Compose/settings 静态证据 | 已达到：本档引用了源码路径与行号 |
| L1 | 静态结构/语法可解析 | `git diff --check`、`python3 -m py_compile` 等当前核对命令 | ARCHITECTURE.md 当前核对待执行针对性验证；未声称 Python 全库通过 |
| L2 | 单元/契约测试通过 | 实际测试命令、退出码、测试数/跳过数 | 未执行；`tests/python/pytest.ini` 仅声明 15s timeout 和插件要求 |
| L3 | 多服务集成通过 | `pytest ./tests/python` 自动启动 CVAT/OPA/Redis/DB/Nuclio 等真实容器 | 未执行；README 的运行说明不是当前核对证据 |
| L4 | 生产类故障/恢复通过 | 注入 Redis/worker/外部 HTTP/数据库/进程故障并读回资源现场 | 未执行；不能据此声称取消、重试、回滚、崩溃清理已闭环 |

**建议的最小真实验证（不在当前核对执行）：**在隔离测试环境执行 `pytest ./tests/python` 的窄目标；增加质量/共识/Webhook/RQ cancel 的失败注入，记录 PostgreSQL 行、RQ job、任务目录、云对象、临时文件和容器进程前后对账；再分别测试 SDK 对 `FAILED/CANCELED/STOPPED` 的终态行为。测试环境必须使用 `tests/python/README.md` 规定的独立容器与资产恢复流程，避免触碰正式数据。

## 18. 未验证项、证据可信度与吸收裁决

### 18.1 未验证项

- 未在本机运行 Django、RQ worker、PostgreSQL、Redis/Kvrocks、OPA、ClickHouse、Vector、Grafana、Nuclio、UI 或 Traefik；因此没有健康检查、端口、迁移、登录、上传、质量、共识、Webhook、SDK 或 CLI 的端到端结果。
- 未安装 Python/Node 依赖，未构建镜像和前端，未生成或对比运行时 OpenAPI；`schema.yml` 与源码的契约一致性仍是静态风险。
- 未验证数据库 migration 的真实约束、事务回滚、文件/对象存储补偿、RQ 重启续跑、锁释放、worker 进程回收、外部 webhook 幂等和 Nuclio timeout。
- 未验证远程 `develop` 快照是否应合并；远程能力只能作为版本漂移线索，不是本地实现。
- 目标仓库没有 `.codegraph/`，故没有代码图调用链证据；本档调用链来自目标路径的只读文件证据，可信度低于可执行集成验证但高于 README 推断。

### 18.2 旧细探吸收/不吸收裁决

- **吸收：**项目定位、Project/Task/Job 协作骨架、`quality_control`、`consensus`、`iam`/`organizations`、`events`/`webhooks`、`lambda_manager` 及其对底座的借鉴方向；已转成当前源码路径、契约、对接链和风险章节。
- **不吸收为已实现：**“实时”“高质量”“审核闭环”“多租户隔离”“共识即可信”等结果性或强保证措辞；仅保留为设计目标/可借鉴模式，并以未验证边界约束。
- **不吸收为本地基线：**远程 `c6a827c` 新增的质量需求、Growth、新用户模型及其 API/UI/测试资产；没有复制远程文件，也没有改本地源码。
- **保留旧细探：**`细探-cvat.md` 不删除，作为历史原始证据；唯一长期架构维护入口是本 `ARCHITECTURE.md`。

## 19. 当前核对收口证据

- 目标项目根：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/50_dataset_annotation_quality/cvat`。
- 当前核对唯一修改文件：目标根 `ARCHITECTURE.md`；未改源码、配置、测试、依赖、Git；未删除 `细探-cvat.md`。
- MCP 开工上下文实际返回的实例为 `project_toolkit`，但 `project_context` 绑定根目录为 `~/Documents/Agent/PHP/华世王镞_v3`，不是目标 CVAT；已如实保留该错绑事实。
- 对目标路径调用 `codegraph_explore` 的结果：未找到 `.codegraph/`，代码图不可用；没有冒充代码图成功。
- 源码事实基线：本地 `develop` / `4aa0be3df5e888180d0d70004e9471423e540eae` / CVAT `2.71.1`；远程 `develop` 的 `c6a827cb3cc2a47d36c2c75197f2266ea5202d79` 仅作为独立快照和漂移线索。

## 19A. 领域对象、存储、队列与生命周期补充核对

本节把前文分散的事实收束成可用于对接和故障排查的领域对象与运行时清单；以下仍以本地 `2.71.1` 工作树为准。

### 19A.1 领域对象边界

| 对象 | 领域含义 | 关键关系/约束 | 主要源码证据 |
|---|---|---|---|
| `Project` | 一组任务共享的标签、状态和源/目标存储边界 | 可属于组织；删除前先删子标签，目录由项目 id 派生 | `cvat/apps/engine/models.py:803-875` |
| `Task` | 具体媒体标注任务及其分段、作业和标注配置 | 可挂项目；绑定 `Data`；限制 `MAX_JOBS_PER_TASK`；可配置维度、模式、媒体类型、overlap、共识副本 | `models.py:918-1056`、`signals.py:49-67` |
| `Data` | 媒体集合的帧范围、过滤、删除帧、媒体描述和验证布局 | 关联 image/video/audio/related files；决定 raw/original/compressed chunk 与缓存策略 | `models.py:453-469` 及其后的 `Data` 方法 |
| `Segment` | 从任务帧空间切出的作业分配单元 | 支持连续 range 和 specific frames；`save()` 强制校验帧类型及起止顺序 | `models.py:1166-1237` |
| `Job` | 标注、验证、验收或 Ground Truth 的最小协作单元 | 绑定 Segment；有 `stage/state/type`、assignee、parent/child；每任务最多一个 Ground Truth job | `models.py:1245-1346` |
| 标注对象 | tag、shape、track、interval 及属性值 | 以 Job 为归属，`AnnotationIR`/`JobAnnotation` 负责批量导入、导出和校验 | `models.py:1318-1328`、前文 §5.1 |
| 质量/共识对象 | `QualitySettings`、`QualityReport`、`AnnotationConflict`、`ConsensusSettings` | 质量报告目标是 Job/Task/Project 之一；共识针对 Task 及其 replica jobs | `quality_control/models.py:91-288`、`consensus/models.py:13-45` |
| 外部交付对象 | `Webhook`、`WebhookDelivery`、`CloudStorage`、`Asset` | 分别承载事件投递账本、云端凭据/路径和标注指南附件 | `webhooks/models.py:40-126`、`models.py:291-380,1784-1806` |

对象关系不是单一数据库事务边界：Project/Task/Job/Data 的 ORM 行、媒体文件/chunk、云对象、RQ job 和外部 HTTP 副作用分别属于不同资源域。只有 ORM 事务能直接提供数据库回滚；其他域依赖 `on_commit`、重试、清理任务或下游幂等。

### 19A.2 存储分层和媒体路径

`cvat/settings/base.py:499-545` 创建并声明以下本地边界：

```text
DATA_ROOT
├── data/       MEDIA_DATA_ROOT：Data 媒体、manifest、raw/original/compressed 数据
├── cache/      CACHE_ROOT
│   └── export/ EXPORT_CACHE_ROOT：导入/导出中间产物
├── jobs/       JOBS_ROOT：Job 目录
├── tasks/      TASKS_ROOT：Task 目录
├── projects/   PROJECTS_ROOT：Project 目录
├── assets/     ASSETS_ROOT：AnnotationGuide Asset 目录
└── storages/   CLOUD_STORAGE_ROOT：CloudStorage 本地工作目录/凭据文件
```

`Storage` 不是文件实体，而是 `local` 或 `cloud_storage` 的位置选择器，并可指向 `CloudStorage`。Data 的输入可以来自客户端上传、挂载 share 或远端 URL；CloudStorage 适配 AWS S3、Azure Blob、Google Cloud。媒体缓存还使用独立的持久缓存 Redis/Kvrocks，并由 `chunks` 队列准备 chunk/preview。因而“数据库删除成功”不等于媒体、缓存、导出文件和云对象已经全部释放。

删除链路的源码事实是：Project/Task/Job/Asset/CloudStorage 的 `post_delete` 注册 `transaction.on_commit(shutil.rmtree(..., ignore_errors=True))`；Data 在 `pre_delete` 先保存媒体相对路径，`post_delete` 提交后删除本地目录，并在有 backing cloud storage 时提交后调用 `bulk_delete`（`cvat/apps/engine/signals.py:96-163`）。`ignore_errors=True` 会把文件系统清理失败降级为静默残留，必须依靠周期清理或外部对账发现，不能宣称删除具备跨存储原子性。

### 19A.3 请求、会话和后台队列

#### HTTP 会话

- Django 启用 `django.contrib.sessions`、`SessionMiddleware` 和 Session authentication；`SessionRefreshMiddleware` 在会话仍有效且响应不是 5xx 时，最多每天刷新一次会话，并通过 `sessionfresh` HttpOnly cookie 避免每次请求都额外写库（`cvat/settings/base.py:111-150,185-190`、`cvat/apps/iam/middleware.py:80-138`）。
- `clean_up_sessions` 由 `cleaning` 队列的每日周期任务调用 `SessionStore.clear_expired()`；它清理过期会话，不是 worker 心跳或业务 Request 清理（`settings/base.py:428-455`、`iam/utils.py:73-75`）。
- API 认证还包括 Token、Personal Access Token 和 Basic authentication；会话存活不等于资源授权，资源访问仍须经过 DRF `IsAuthenticated`、`PolicyEnforcer`、组织过滤和具体对象 permission。

#### Request 与 RQ job

后台 Request 没有独立的业务数据库表，主要由 Redis 中的 RQ job/meta 投影为 API 资源。公开状态为 `queued`、`started`、`failed`、`finished`，序列化结果包含操作、创建/开始/结束时间、过期时间、owner、progress 及 result url/id（`redis_handler/serializers.py:30-35,90-114`）。`AbstractRequestManager` 的标准流程是：POST-only 校验 → 构造稳定 request id → 用户锁与 job 锁 → 检查同 id 运行中任务并返回 `409` → 写入 meta、依赖、TTL、成功/失败 callback → 返回 `202 rq_id`（`redis_handler/background.py:34-200`）。

请求 meta 会携带 user/request/org/project/task/job 等上下文，供权限、进度、事件和结果读取使用；因此 request id 不是授权凭证，查询接口仍执行 owner/对象权限检查。RQ job 过期或被删除后，历史 Request 不保证永久可读；API 对 Redis 不可用返回 `503`，不存在的 id 返回 `404`。

队列及默认超时由 `CVAT_QUEUES`/`RQ_QUEUES` 单一声明：`import`/`export` 4h、`annotation` 24h、`webhooks` 25s、`notifications` 1h、`quality_reports` 1h、`cleaning` 2h、`chunks` 5m、`consensus` 1h（`settings/base.py:326-406`）。`ONE_RUNNING_JOB_IN_QUEUE_PER_USER` 可通过依赖关系把同一用户任务串行化；这不是全局 exactly-once，也不消除外部副作用重复执行。

### 19A.4 Worker、媒体处理和资源释放

- Compose 将共享的 `cvat_data`、`cvat_keys`、`cvat_logs` 挂载到 server 和各 worker；worker 按队列拆分为 utils、import、export、annotation、webhooks、quality_reports、chunks、consensus，`restart: always` 只提供容器级重启保障（`docker-compose.yml:122-249`）。
- `rqworker.py` 的生产默认仍是 RQ `Worker`；测试/调试 `SimpleWorker` 在同一进程执行 job，并在执行前关闭 Django DB 连接，且明确禁止停止已启动 job。此调试行为不能外推为生产 worker 的取消语义（`rqworker.py:12-54`）。
- 质量报告和共识使用专用 request id、队列、锁及 callback；导入/导出/自动标注使用对应的 target/action 元数据。媒体 chunk/preview 通过 `MediaCache` 事件记录创建、读取和大小，生命周期由缓存实现与 cleaning/chunks 任务共同维护。
- Webhook 用短连接/读取超时和受限响应体的 requests session；函数返回后 session/response 句柄由上下文管理器释放，但“远端已收到而本地 Delivery 尚未写入”仍可导致重试副作用。
- Nuclio/lambda 调用在 `lambda_manager` 中使用 `with make_requests_session()`，默认超时 120 秒；TensorFlow serverless 示例显式在 `close()` 中关闭 TensorFlow session。模型函数的进程/显存回收属于 Nuclio/模型实现边界，不能仅由 Django worker 的退出保证。

### 19A.5 权限、失败恢复和资源释放矩阵

| 资源/场景 | 已有机制 | 不能从源码推出的保证 |
|---|---|---|
| Session | Django session、刷新中间件、每日过期清理 | 不能把 session cookie 当对象权限；过期清理运行时成功未验证 |
| RQ Request | request id 去重、用户/job 锁、依赖、状态查询、失败 callback | Redis 丢失、锁 TTL、worker 崩溃后的续跑和历史可读性未实测 |
| queued/deferred 取消 | 取消并删除 job；必要时取消依赖 | 与 worker 同时取 job 存在竞态 |
| started 取消 | 仅特定可停止的 export worker 支持 stop command；调试 SimpleWorker 明确不可停 | 非 export 不可取消；停止后的部分文件、DB 行和云对象未自动补偿 |
| 文件/云对象 | `on_commit` 后清理本地目录；Data backing cloud 触发 bulk delete | `ignore_errors` 隐藏失败；跨 DB/文件/云存储没有原子事务或统一补偿账本 |
| Webhook | Delivery 记录、5xx/408/429 RQ retry、失败 TTL | 不是 exactly-once；下游幂等键未由本地源码统一提供 |
| worker/外部服务 | Compose restart、队列隔离、启动 migration barrier | 重启不等于任务恢复；OPA、Nuclio、对象存储、Redis 故障恢复未形成 L3/L4 证据 |
| 媒体/模型资源 | cache 事件、周期清理、session/context manager、模型 `close()` 示例 | 大媒体内存峰值、显存、临时目录、孤儿 chunk/preview 的上限与回收未现场验证 |

**对接结论：**任何新媒体或长任务能力都必须同时定义 `(1)` ORM 领域对象及权限 owner，`(2)` 本地/共享/云存储位置和清理责任，`(3)` Request action/target/idempotency key，`(4)` 队列、超时、重试与取消边界，`(5)` worker 崩溃后的状态修复和孤儿资源对账，`(6)` session/Token 与对象权限的分离。缺少其中任一项，只能算“能入队或能写文件”，不能算完成的业务闭环。
- 验证边界：当前核对只做只读源码取证和文档编辑；验证命令及退出码见最终回信，未把未执行的服务/测试写成通过。

## 20. 后续：通用底座映射总裁决

本节是后续增量，不是把 CVAT 代码直接搬进系统工程平台。映射对象是“能力契约、领域模块、支持库、运行核心”的职责边界；CVAT 当前实现仍以本档前文的本地 `2.71.1` 工作树为事实源，远程 `develop` 只作漂移提示。

### 20.1 映射总表

| CVAT事实/组件 | 底座归属 | 裁决 | 不能直接复用的部分 |
|---|---|---|---|
| `Project → Task → Data → Segment → Job`、媒体切分、标注作业 | **数据集模块** | 吸收为数据集领域模型与任务编排入口；Task 是数据集作业容器，Job 是唯一可分配标注单元 | 不把 Django Model、权限查询和文件路径直接暴露给平台；Project/Task 的 CVAT 业务字段不是公共契约 |
| `AnnotationIR`、`AnnotationManager`、`JobDataProvider`、`patch_job_data` | **数据集模块**（调用公共标注结构） | 升级为“标注中间表示 + 单一写回服务”；格式导入/导出只经模块入口 | 不让各格式 provider 直接写 PostgreSQL；`AnnotationIR` 的 CVAT 字段需转换为平台统一标注结构 |
| Datumaro Dataset、CVAT 格式适配器、`utils/dataset_manifest` | **数据集支持库** | 复用为受管格式/数据集交换 provider；manifest 是数据集索引能力，不是任务状态库 | Datumaro 版本、插件、临时目录、ZIP/媒体解析必须隔离；不能以 Datumaro 对象作为跨模块长期句柄 |
| `quality_control` 的 QualitySettings/Report/Conflict/Calculator | **质量模块** | 吸收“设置继承 → 数据提供 → 匹配 → 冲突 → 报告”的领域流程 | 质量分数、报告 JSON、冲突类型不是通用底座结果类型；质量模块不得旁路写任务标注 |
| `consensus`、`ConsensusSettings`、`IntersectMerge` | **质量模块**（共识子域） | 升级为质量模块的共识/合并能力；输入输出都引用数据集模块的标注快照 | 不能把“清空 parent 后导入”当作跨系统通用事务；合并策略必须有版本和快照证据 |
| PostgreSQL/Django ORM/migrations/`transaction.atomic` | **数据库支持库** | 新建/升级受管 PostgreSQL provider；模块只依赖数据库公开事务、查询、批量写和迁移契约 | 不复制 CVAT Model/migration；不能由质量或数据集模块自行创建连接池、执行任意 SQL 或旁路写表 |
| local/share/S3/Azure/GCS、`CloudStorage`、`cloud_provider.py` | **对象存储支持库** | 统一对象/文件 provider，提供内容寻址、分片、流式读写、删除、存在性、对账能力 | provider 不拥有 Task/Job 业务状态；云厂商 SDK、凭证、重试和临时下载目录都在适配边界内 |
| Redis/RQ、`CVAT_QUEUES`、`AbstractRequestManager` | **运行核心**（队列/任务执行） | 建议复用统一任务系统：请求 ID、队列路由、状态投影、取消、超时、重试、恢复 | 不把 RQ Job 当平台权威任务实体；不让每个业务 app 维护一套 request 状态机 |
| Webhook `WebhookDelivery`、HTTP session、RQ retry | **运行核心**（事件投递）+ **质量/数据集事件源** | 运行核心提供可靠投递、租约、幂等和投递账本；业务模块只发布领域事件 | CVAT 现有 delivery 记录和 RQ Retry 不能证明 exactly-once；外部副作用必须由幂等键保护 |
| `cvat-core`/`server-proxy`/`requests-manager`、React Redux UI | **前端核心**（API facade） | 吸收 facade、snake/camel 转换、分页资源、异步请求观察和取消适配 | UI/reducer 不得直接拼接数据库/队列字段；前端状态不能成为后端权威状态 |
| `cvat-sdk`/`cvat-cli` | **前端/客户端适配层** | 作为 API 消费者适配层；统一调用公开模块 API/网关，保留版本探测 | SDK 的 generated models、legacy request id 和 CLI 参数不能成为底座内部契约 |

**映射结论：**数据集模块拥有“数据集、媒体、任务、分段、作业和标注事实”；质量模块拥有“质量设置、比较、共识、冲突和质量报告”；数据库/对象存储支持库只拥有外部资源适配；运行核心拥有“异步任务、队列、租约、重试、取消、崩溃恢复和事件投递”；前端核心只拥有客户端领域 facade 和状态呈现。四者之间不得互相越权。

### 20.2 能力复用、升级、新建、隔离清单

| 能力 | 动作 | 目标落点与理由 |
|---|---|---|
| 标注任务/作业状态 | **新建数据集模块能力，复用运行核心任务机制** | 任务是领域事实，RQ 只执行异步工作；需一个 `数据集标注任务` 契约和一个写 owner |
| 标注 IR/快照读写 | **升级数据集支持库/模块** | 把 `AnnotationIR` 与 Dataset snapshot、schema/version、来源作业、校验结果绑定，避免格式 provider 直写 |
| Datumaro 转换 | **新建受管数据集格式支持库** | Datumaro 是 provider/交换层；大数据转换应可在独立进程执行，输出对象清单和摘要 |
| 质量报告/冲突 | **新建质量模块能力** | 复用统一结果、任务提交、数据库事务和对象存储；质量报告必须记录输入标注快照与算法/参数版本 |
| 共识合并 | **升级质量模块** | 合并前生成父/副本快照，成功后一次性发布新标注版本；失败不得留下“父作业已清空”的不可解释状态 |
| PostgreSQL | **新建数据库支持库 provider** | 统一连接、事务、查询超时、批量、迁移检查、故障码和资源释放；业务模块不感知驱动 |
| 对象存储 | **新建对象存储支持库 provider** | 统一 local/share/S3/Azure/GCS 的流、分片、摘要、删除和对账；不把路径字符串当资源所有权 |
| RQ/Redis | **隔离 CVAT 实现，复用运行核心语义** | RQ 可作为 provider，但队列/状态/租约/取消语义必须由运行核心统一，不能复制 CVAT `AbstractRequestManager` |
| Webhook | **新建运行核心事件投递能力** | 统一签名、幂等键、delivery 状态、退避、死信和对账；业务 app 只提交事件 |
| 前端 API | **升级前端核心** | 保留 facade + server-proxy + request observer 形态；映射后只新增领域适配，不复制请求轮询器 |
| CVAT Django/IAM/OPA/Nuclio/ClickHouse/Grafana | **隔离/待核** | 是 CVAT 部署或产品边界，不是当前核对通用底座；需单独能力需求和外部依赖审查 |

## 21. 唯一标注链路与调用契约

### 21.1 唯一权威链路

```text
前端/SDK/CLI/自动化调用方
  → 前端核心或客户端适配层
  → 统一 API/网关（认证、权限、版本、幂等键）
  → 数据集模块/质量模块公开入口
  → 统一任务提交器（请求 ID、队列、租约、预算）
  → 运行核心 worker
  → 数据集模块读取标注快照
  → 数据集支持库（Datumaro/格式 provider）
  → 数据库支持库（PostgreSQL 事务） + 对象存储支持库（媒体/产物）
  → 统一结果、事件、Webhook 投递与证据
  → 前端核心按 request/资源版本刷新
```

**唯一标注写链路：**`API/客户端 → 数据集模块标注入口 → 标注快照/版本校验 → 数据集支持库 AnnotationIR 转换 → 数据库支持库事务写入 → 事务提交后的事件与对象存储清理/发布 → 运行核心事件投影`。质量报告、共识、导入导出都只能调用这条链；禁止 `Datumaro → Django ORM`、`前端 → RQ`、`Webhook → 任务表` 等旁路。

### 21.2 边界契约

| 边界 | 必备输入 | 必备输出 | 失败/资源要求 |
|---|---|---|---|
| 数据集模块 → 标注任务 | dataset/task id、标注 schema 版本、媒体/帧选择、幂等键 | task/job/version、状态查询地址 | 非法范围、schema 漂移、重复请求稳定失败；创建的快照/临时目录必须归还 |
| 数据集模块 → 标注写回 | 任务版本/快照版本、Job、AnnotationIR、写入模式 | 新标注版本、摘要、变更事件 id | CAS/版本冲突不得覆盖；事务失败回滚数据库，待发布对象可对账 |
| 质量模块 → 数据集模块 | 任务/项目目标、已完成 GT、输入快照、质量参数 | immutable report、冲突明细、指标摘要 | 不锁长事务读全库；报告注明“非绝对一致”或使用稳定快照；报告失败不修改标注 |
| 共识 → 数据集/质量 | parent job、replica jobs、共识参数、快照版本 | 合并后的新标注版本、参与者/策略证据 | merge 必须原子发布；不能先永久清空 parent；取消/崩溃后可重放或恢复 |
| 运行核心 → 业务模块 | task kind、owner、payload 摘要、队列、timeout、重试策略 | request id、状态/进度/错误、取消结果 | worker 只能凭租约执行；租约过期拒绝提交；重试需区分安全重试与副作用重试 |
| 事件 → Webhook | event id、aggregate/version、payload schema、幂等键 | delivery id、attempt、响应摘要、最终状态 | HTTP 发送不是事务一部分；重试不得改变 event id；接收端按幂等键去重 |
| 前端核心 → API | 领域命令、API version、request id | typed resource/request、分页、终态错误 | 只观察 queued/started/finished/failed/canceled/stopped；404 不能无限轮询；取消后停止 timer |

## 22. 任务状态、队列、租约与失败治理

### 22.1 领域状态与执行状态分离

CVAT 当前 `Job` 同时有历史 `status` 以及 `stage/state`：`stage` 表示 annotation/validation/acceptance，`state` 至少包含 `new/in progress/completed/rejected`（`cvat/apps/engine/models.py:121-125,1297-1308`）。映射到通用底座时必须拆成两条轴：

```text
领域轴：草稿 → 可标注 → 标注中 → 待验收 → 已完成/已拒绝
执行轴：已登记 → 排队 → 已领取 → 运行中 → 成功/失败/取消/停止/过期
```

领域完成不能由 RQ `finished` 直接推断；RQ 失败也不等于标注事实回滚。每个异步作业至少持久化：`任务id、领域对象、操作类型、输入快照、期望版本、request_id、attempt、worker、租约截止、领域状态、执行状态、错误码、可重试、取消原因、产物摘要、事件序号`。所有状态变更由运行核心投影并由数据集/质量模块确认领域结果。

### 22.2 队列与任务路由

CVAT 的 `CVAT_QUEUES` 将 `import/export/annotation/webhooks/notifications/quality_reports/cleaning/chunks/consensus` 分开，并为 import/export 设 4h、annotation 24h、webhooks 25s、quality/consensus 1h 等默认超时（`cvat/settings/base.py:326-405`）。该模式可吸收为**队列选择策略**，但不能让队列名成为业务状态：

1. 任务提交器依据能力 id 和资源预算选择队列；队列配置记录最大运行时、并发上限、重试策略和可取消性。
2. `request_id` 是外部查询/幂等入口；内部 job id、attempt id、delivery id 分开，不能用同一字符串承担三种身份。
3. RQ 的 `depends_on`、按用户锁和 `handle_existing_job` 可作为实现线索；真正的互斥、租约和状态 owner 必须在运行核心。
4. 超时后由运行核心回收租约、标记 attempt，不把“进程还活着”当作完成；需要再次执行时生成新 attempt 并保留前次失败证据。

### 22.3 租约而不是永久锁

当前 `AbstractRequestManager.enqueue_job` 在 job id 和 user 维度加锁、以 `job_id=request_id` 入队，并把元数据写入 RQ（`cvat/apps/redis_handler/background.py:127-200`）；源码没有形成平台级租约/心跳/崩溃清理契约。通用底座应补：

- 领取时原子写 `lease_id、owner、attempt、issued_at、expires_at、heartbeat_at`；只有持有未过期 lease 的 worker 能更新进度、提交结果和发送完成事件。
- 心跳续租必须有上限和硬截止；worker 进程退出、心跳超时或 token 不匹配时，租约进入 expired，旧 worker 的迟到写入一律拒绝。
- 重新领取前扫描 `queued/leased/running` 的过期项，生成恢复 attempt；不得无条件重复执行不可幂等的外部写操作。
- 租约释放与临时目录、数据库连接、子进程组、对象上传 session 绑定，正常、失败、取消、超时、崩溃都要有释放证据。

### 22.4 失败分类与重试

| 失败类 | 例子 | 默认动作 |
|---|---|---|
| 参数/权限/schema | Task 不存在、非 2D 质量报告、缺 GT、版本冲突 | 不重试；稳定错误码；不创建半成品 |
| 临时基础设施 | Redis/DB 连接短断、对象存储 502、Webhook 408/429/5xx | 有界指数退避；attempt 递增；操作必须具备幂等键 |
| provider 可恢复 | Datumaro 输入暂时不可读、worker 被回收 | 租约失效后新 attempt；对临时目录和已上传对象做对账 |
| provider 永久错误 | 格式损坏、标签不兼容、算法参数非法 | 失败终态；保留输入快照、错误、provider 版本和现场摘要 |
| 宿主崩溃/超时/取消 | worker SIGKILL、硬超时、用户取消 | kill 进程组/关闭连接/清临时资源；读回 DB、队列、文件和对象现场，再决定恢复或失败 |

CVAT Webhook 当前对连接异常返回 502、超时返回 504，5xx/408/429 由 `WebhookDeliveryError` 触发 RQ `Retry`（`webhooks/utils.py:68-102`、`webhooks/tasks.py:14-38`、`webhooks/dispatch.py:14-24`）。这只能作为“有界重试”的源码事实，不能升级为投递 exactly-once。

## 23. Webhook 幂等、取消与崩溃资源

### 23.1 Webhook 幂等契约

CVAT payload 已包含 `event/status/target/target_id/rq_id/message`，batch 入队还附加 `webhook_id`；Delivery 保存状态码、attempt 等结果，但本地源码未发现跨重试固定的消费幂等键。通用底座必须显式定义：

```text
idempotency_key = event_id + webhook_id + aggregate_version
```

- `event_id` 在业务事件创建时生成并持久化，重试、redelivery、worker 重启、Webhook URL 重试都沿用同一个 id。
- 发送前写 delivery attempt；发送后写 HTTP 结果。若“对端已收到、落账前崩溃”，下一次仍可重复发送，但只能重复同一个幂等键；平台不宣称网络层 exactly-once。
- 业务接收端必须按 key 去重并返回可接受的 2xx；平台 delivery 账本保存 `first_sent_at/last_sent_at/attempts/final_status/response_digest`，不把响应正文无限保存。
- secret 签名覆盖规范化 payload 与 event id；payload schema/version 变化要显式升级，不能让接收端猜字段。
- 失败超过重试上限进入死信/人工重放，重放不新建 event id；Webhook 删除、停用和 secret 变更不应篡改历史 delivery。

### 23.2 取消语义

`/api/requests/{id}/cancel` 当前对 queued/deferred 直接 cancel+delete；started 仅允许生产 worker 中可停止的非变更 export，其他 started/finished/failed/scheduled 返回错误（`cvat/apps/redis_handler/views.py:304-349`）。前端 `requests-manager.ts:93-153,178-181` 将 404 的 queued/started 请求投影为 canceled 并停止监听。映射后的统一语义必须更严格：

1. **请求取消**只改变执行意图，不伪造领域结果；取消响应为“已请求/已确认/不允许”，三者分开。
2. queued/deferred 在 worker 领取前可安全取消；领取竞态用 lease CAS 决胜，不能只依赖 Redis 删除。
3. running 取消需要能力声明：只读/导出可停止，标注写回、共识发布、数据库迁移等不可中断临界区必须先完成或进入补偿；取消令牌传给 worker，worker 最终写 canceled/stopped 证据。
4. finished/failed/canceled/stopped/expired 为终态，重复取消幂等返回同一终态；前端不得因 404 无限轮询或把对象删除当作成功。
5. SDK `Client.wait_for_completion` 当前只显式处理 FINISHED/FAILED（`cvat-sdk/cvat_sdk/core/client.py:220-248`），底座适配器必须补齐 canceled/stopped/expired，避免客户端永远等待。

### 23.3 取消/崩溃资源清单

| 资源 | 正常完成 | 失败/取消 | 崩溃后必须读回/对账 |
|---|---|---|---|
| PostgreSQL 事务/连接/游标 | commit 后关闭 | rollback、归还连接；错误码持久化 | 未提交行不可见；锁/连接无残留；已提交状态与对象清单一致 |
| RQ job/Redis lock/lease | 终态投影、删除或按 TTL 保留 | 取消 job、释放 lease、保留 attempt 证据 | orphan job、expired lease、依赖 job 是否错误唤醒 |
| worker/子进程/线程 | 正常退出，回收进程组 | 软停→宽限→强杀；join/reap | PID、进程组、端口、管道、僵尸均不存在 |
| 临时目录/导入导出文件 | 原子发布后清理 | finally 清理；失败现场保留受控摘要 | `TMP_FILES_ROOT`、task/job/export 目录无孤儿或有可解释保留标记 |
| 对象存储 multipart/session/产物 | complete 后记录摘要 | abort multipart；未发布对象进入垃圾清单 | 孤儿对象、ETag/sha256、数据库引用、清理重试账一致 |
| Datumaro dataset/缓存 | 释放迭代器/内存/临时文件 | 关闭 provider，丢弃未发布快照 | 内存峰值不可直接读回；需 worker 退出、临时树和快照清单证据 |
| Webhook session/Delivery | response 关闭，写结果 | 退避/死信；不把网络副作用回滚成未发生 | 对端可能已收到；依幂等 key 重放并核对 delivery |

CVAT `Data.move_to_backing_cloud_storage` / `move_from_backing_cs` 通过 `transaction.on_commit` 做原文件/云对象清理（`cvat/apps/engine/models.py:601-679`），删除 handler 也存在“数据库提交后清文件、`ignore_errors=True`”语义。该模式可吸收为提交后副作用，但必须加对象清单、失败重试和孤儿对账；`on_commit` 不是跨数据库/对象存储事务。

## 24. L0-L4 验证契约与后续验收

当前核对把 L0-L4 从“项目验证等级”细化成底座映射的准入门槛。低等级只能证明结构，不得替代高等级资源/故障证据。

| 等级 | 必须证明 | 针对 CVAT 映射的最小证据 | 允许结论 |
|---|---|---|---|
| **L0 源码事实** | 路径、符号、配置、调用关系存在 | `models.py`、`quality_reports.py`、`merging_manager.py`、`webhooks/*`、`settings/base.py`、`dataset_manager/*`、`cloud_provider.py`、`cvat-core`/SDK 路径读取 | “源码实现/声明存在”，不代表可运行 |
| **L1 静态契约** | 文档/接口/配置可解析且无明显漂移 | schema 与 View/serializer 路由对照；队列/状态/错误/幂等字段表；Markdown 结构检查；本档限定文件变更检查 | “契约和映射可审查”，不代表 provider 可用 |
| **L2 单组件真实测试** | 单元/契约在实际解释器和依赖下通过 | 质量计算、共识合并、AnnotationIR round-trip、RQ request 状态/取消、Webhook retry/签名/1MiB 上限、对象 provider mock-free contract；记录退出码/测试数/skip | “单组件行为通过”；不得把 skip 当通过 |
| **L3 多服务集成** | DB、Redis/RQ、对象存储、Web/API、前端/SDK 真实联通 | 隔离 Docker/测试环境：创建 Task→上传媒体→创建 Job→写标注→生成 GT→质量报告/共识→导出→查询 request→Webhook 接收；读回 PostgreSQL、队列、对象和 UI/API 终态 | “真实跨服务链路通过”；需列出外部依赖版本和残留对账 |
| **L4 故障/恢复与审计** | 取消竞态、租约过期、worker 崩溃、DB/Redis/对象存储断开、Webhook 已收后本地崩溃、重试/重放均可恢复且无半成品 | 强杀 worker/进程组，注入 408/429/5xx、SIGKILL、连接断开、超时；重启后核对领域状态、attempt、lease、DB 行、文件/对象、delivery 幂等和证据链 | “生产级治理成立”；没有现场读回只能是 L0-L3 |

### 24.1 后续最小验收矩阵

| 场景 | 需要的断言 |
|---|---|
| 重复创建相同标注任务 | 一个领域任务/一个 request 语义；重复调用返回既有 id 或稳定冲突，不生成第二条隐形链 |
| 同一标注快照并发写回 | 只有一个版本 CAS 成功；失败者得到版本冲突，数据库/对象均无半发布 |
| 质量报告重复提交 | 同一目标/快照/参数生成可识别 request；运行中返回已存在状态，不重复算或报告可明确区分 attempt |
| 共识合并中断 | parent 标注不处于“已清空但未发布”；重试从输入快照重放，不能追加重复对象 |
| Webhook 对端 500 后恢复 | 有界退避、固定 event/idempotency key、delivery attempt 递增；成功后不再无限重试 |
| Webhook 已收到后 worker SIGKILL | 重启可重放同一 key；接收端去重，delivery 账本最终可解释 |
| queued/running 取消竞态 | lease 只有一个胜者；取消与领取不会产生“双终态/幽灵 worker”；running 非可停止任务明确拒绝 |
| worker 崩溃/租约过期 | 旧 worker 迟到提交被拒；新 attempt 有界恢复；进程组、锁、临时目录和对象 multipart 不残留 |
| 数据库提交成功、对象清理失败 | 领域状态仍可解释；清理任务进入待处理账，不静默丢失；重试幂等 |
| SDK/UI 读到 404/停止态 | 终止轮询、展示取消/停止/失败，不把“找不到 request”误报为成功 |

## 25. 后续吸收裁决、实施顺序与剩余风险

### 25.1 吸收/升级/新建/隔离

- **吸收：**`Project → Task → Segment → Job` 的数据集骨架；AnnotationIR 与 Datumaro 的交换边界；质量“设置/数据/匹配/冲突/报告”分层；`cvat-core` facade；RQ 队列分片与 request id；对象存储 `on_commit` 延后清理的方向。
- **升级：**把 Task/Job 领域状态与 RQ 执行状态分离；把 RQ lock 升级为带心跳/截止时间/持有者的租约；把质量和共识输入固定为标注快照；把前端/SDK 终态补全为 canceled/stopped/expired。
- **新建：**数据集标注任务公开契约、质量报告/共识模块契约、PostgreSQL 支持库、对象存储支持库、统一 Webhook 投递/幂等能力，以及数据库/对象/队列/事件对账能力。
- **隔离/待核：**CVAT Django ORM/迁移、CVAT RQ 具体实现、Datumaro 插件生态、Nuclio/OPA/ClickHouse/Vector/Grafana、厂商 SDK、CVAT legacy request id 与远程 `2.73.1` 新质量需求。它们不能在没有能力需求登记、复用裁决和真实验证前进入平台核心。

### 25.2 建议装配顺序

```text
1. 公共契约：标注快照、任务命令、质量报告、事件、request/attempt/lease/delivery
2. 数据库支持库 + 对象存储支持库：事务/摘要/流/删除/对账/故障码
3. 运行核心：任务提交、队列路由、租约、心跳、重试、取消、进程组回收、事件投递
4. 数据集模块：Task/Segment/Job/AnnotationIR/唯一写回链
5. 质量模块：QualityReport/Conflict/Consensus，输入只读标注快照，结果只经公开写 owner
6. 前端核心/SDK/CLI：facade、request observer、版本兼容、取消和终态适配
7. L2 → L3 → L4：先组件契约，再隔离多服务，最后故障注入与资源对账
```

### 25.3 后续剩余风险

1. 本地 CVAT 未安装依赖、未启动 PostgreSQL/Redis/RQ/对象存储/前端，因此 L2-L4 仍是验收计划，不是当前核对通过结果。
2. `QualityReport` 计算代码明确写出“不能保证绝对一致”（`quality_reports.py:2684-2690`）；平台若需要可复现质量报告，必须先落稳定标注快照和算法/参数版本。
3. 共识实现当前在 `transaction.atomic` 内先 `clear_annotations_in_jobs` 再导入（`merging_manager.py:120-145`）；是否覆盖所有 Datumaro/文件副作用必须实测，不能只凭数据库事务宣称全回滚。
4. RQ `Retry` 和失败 TTL 只能治理队列任务，不回滚外部 HTTP、对象上传或已提交标注；必须由幂等键、补偿/对账和 evidence owner 补足。
5. Webhook `perform_webhook_request` 只限制响应读取 1 MiB、timeout `(3,10)`；DNS/SSL/其他 requests 异常分类、接收端幂等和长期 delivery 保留仍待 L2/L4。
6. CVAT 的数据库、对象、缓存、队列、事件有多个事实面；迁移到平台前必须先冻结唯一写 owner 和 schema/version，不得仅按目录名搬运。

## 26. 后续收口证据补记

- **修改文件：**仅目标项目根 `~/Documents/Agent/github 源码参考/30_多模态与媒体分析/50_dataset_annotation_quality/cvat/ARCHITECTURE.md`；未修改源码、配置、依赖、测试、README、Git，未删除 `细探-cvat.md`。
- **源码取证：**补读 `cvat/apps/engine/models.py`、`quality_control/quality_reports.py`、`quality_control/models.py`、`consensus/merging_manager.py`、`webhooks/utils.py`/`tasks.py`/`dispatch.py`、`redis_handler/background.py`/`views.py`、`settings/base.py`、`dataset_manager/task.py`、`engine/cloud_provider.py`、`cvat-core/src/requests-manager.ts`、`cvat-sdk/cvat_sdk/core/client.py`；当前核对结论均标注为源码事实、映射裁决或未验证建议。
- **MCP 开工 id：**`project_context` 实际返回 `开工id=""`；**MCP 实例：**`project_toolkit`；其上下文错绑 `~/Documents/Agent/PHP/华世王镞_v3`，没有将目标 CVAT 作为工作根。
- **代码图：**按要求随后调用 `codeexplore`（目标路径限定 CVAT），返回退出码语义为失败：目标项目没有 `.codegraph/` 索引；未运行 `codegraph init`，未伪造代码图证据。
- **验证边界：**当前核对只进行了只读源码取证和 Markdown 定向编辑；未安装依赖、未启动服务、未运行 Django/pytest/Cypress/Yarn/Docker，因此 L2-L4 不宣称通过。后续复核应使用目标仓库隔离测试环境，并按 §24 记录退出码、测试数、skip 数和资源对账。

---

## 27. 第四轮：分段审计补记（锁、取消、重试、资源与文档）

本节是对本地 `develop` / `2.71.1` 工作树的追加审计，不改变前文版本边界。读取范围按领域分段完成：
`Project/Task/Data/Segment/Job/annotation`、`quality_control/consensus`、`events/webhooks`、`CloudStorage/media`、Django/RQ/worker、IAM/organizations/permissions、Python REST tests 与 `site/content/en/docs`。目标仓库没有 `.codegraph/`，已尝试 `codegraph explore`，工具明确返回索引不存在；以下调用链均是文件级静态证据，不冒充 CodeGraph 结果。

### 27.1 锁与并发裁决

- 领域写路径不是无锁：`engine/task.py` 使用 `transaction.atomic` + `select_for_update(of=("self", "data"))`，`engine/views.py`、`serializers.py`、`quality_reports.py`、`consensus/merging_manager.py` 等还有事务边界；数据库锁超时通过 `engine`/`events` 的错误转换处理。
- RQ request 去重依赖 request/job/user 维度的 Redis 锁和稳定 request id，但 `rq_patching.py` 的 job cancel 只在 Redis pipeline 内移除队列、依赖关系和 registry；`redis_handler/views.py` 明确标注 queued/deferred 取消与 worker 同时领取存在 race condition。
- `StartedJobRegistry.cleanup` 对过期 job 先执行 failure callback，再按 `retries_left` 重新入队或进入 FailedJobRegistry，并唤醒依赖 job。该机制治理 abandoned RQ job，不等于领域事务、文件产物或外部副作用已回滚。
- 因而锁的准确结论是“局部数据库行锁 + RQ 去重/注册表清理”，不是全链路租约。不能从当前代码推出 worker 崩溃后旧 worker 迟到写入必然被拒绝，也不能推出跨 PostgreSQL、Redis、文件和对象存储的原子互斥。

### 27.2 取消与终态

| 场景 | 本地源码行为 | 审计结论 |
|---|---|---|
| queued/deferred | `rq_job.cancel()`、删除 job，可按配置唤醒 dependents | 有明确入口，但存在领取竞态；删除 Redis job 不是 lease CAS |
| started export | 仅生产风格 worker 的非变更 export 发送 `send_stop_job_command` | 取消范围窄；停止后的部分导出文件、云对象和领域状态需现场对账 |
| started 非 export | HTTP 层返回不支持取消 | 这是显式拒绝，不应在客户端伪装成已取消 |
| finished/failed/scheduled | 返回错误；cancelled/stopped 查询会被删除并返回 404 | Request 历史不持久；404 不能被 SDK/UI 当作成功 |
| SDK 等待 | `Client.wait_for_completion()` 主要显式处理 FINISHED/FAILED | canceled/stopped/expired 等终态必须在适配层补全，否则存在无限等待或错误分类风险 |

取消只表示执行意图，不表示标注事实回滚。任何写标注、共识发布、对象提交或数据库临界区都需要可中断边界、补偿路径和终态证据；当前 CVAT 源码没有统一的平台级取消令牌和租约提交门禁。

### 27.3 重试、Webhook 与幂等

- Webhook worker 在 `dispatch.py` 使用 RQ `Retry(max=len(SEND_WEBHOOK_TASK_RETRIES), interval=...)`，失败 TTL 为 7 天；`tasks.py` 对 5xx、408、429 抛出 `WebhookDeliveryError`。
- `WebhookDelivery` 记录 webhook、event、status code、redelivery、attempt、duration、request/response 和 changed fields；模型约束 project/organization 归属，但没有看到跨重试固定的全局 `event_id + aggregate_version` 幂等键约束。
- `services.send_webhook` 完成 HTTP 请求后才形成 Delivery 记录。对端已收到而 worker 在落账前崩溃时，RQ 可能再次发送；因此这是“有界重试 + Delivery 账本”，不是 exactly-once。接收端必须自行去重，平台迁移时应固定 event id、delivery id 与幂等 key 的不同身份。
- RQ abandoned cleanup 的 retry 只针对队列任务本身；它不能撤销已发出的 HTTP、已提交的 PostgreSQL 事务、已上传的 multipart 或已发布的文件。重试策略必须按参数/权限错误、临时基础设施、provider 永久错误、超时/崩溃分别分类。

### 27.4 媒体、CloudStorage 与资源释放

- `engine/signals.py` 的 Project/Task/Job/Asset/CloudStorage 删除路径使用 `transaction.on_commit` 后 `shutil.rmtree(..., ignore_errors=True)`；Data 在 `pre_delete` 保存媒体相对路径，提交后删除本地目录，并对 backing CloudStorage 调 `bulk_delete`。
- `engine/cloud_provider.py` 提供 AWS S3、Azure、Google Cloud 等 provider 的批量删除和传输边界；这些外部对象不参加 Django 数据库事务。对象删除失败在当前 handler 中可被 `robust=True`/`ignore_errors=True` 降级，存在静默孤儿风险。
- `engine/cache.py` 的 `MediaCache` 管理 chunk/preview/raw media 缓存，`frame_provider.py`、`audio_provider.py` 和 dataset bindings 会读写缓存；缓存、媒体目录、导出临时产物和对象存储是独立资源域，数据库删除成功不代表全部资源已释放。
- worker 由 Compose 按 import/export/annotation/webhooks/quality/chunks/consensus 等队列分片，`restart: always` 只提供容器级重启，不证明任务恢复、临时目录清理、子进程回收、GPU/模型释放或 orphan 对账。

### 27.5 权限、Django 与测试证据

- 资源权限是多层组合：Django/DRF authentication、`IsAuthenticated`、`PolicyEnforcer`、IAM/organization filters、app permissions 和 `rules/*.rego`。Webhook 的公开 ping 等少数 endpoint 显式设置空 permission class，不能据此推断同 app 其他路由公开。
- Django 事务只覆盖 ORM 行和数据库提交；`on_commit` 回调、RQ 入队、文件系统、CloudStorage、外部 webhook 是提交后的副作用，必须用清理任务、补偿/重试和资源账本对账。
- `tests/python/README.md` 说明 REST 测试依赖真实 CVAT、OPA、Redis、PostgreSQL、Nuclio 容器，测试函数后恢复数据库；需要 Docker、依赖和测试资产，不能在当前核对静态审计中宣称通过。
- 已定位的重点测试包括 `test_requests.py`、`test_webhooks.py`、`test_webhooks_sender.py`、`test_quality_control.py`、`test_cloud_storages.py`、`test_jobs.py`，以及 `redis_handler/tests/test_views.py`。测试文件存在只证明测试意图存在，不能证明取消竞态、worker 崩溃、跨资源清理和 exactly-once 已通过。
- site 文档与源码的职责描述大体一致：架构文档列出 PostgreSQL、Redis、Kvrocks、OPA、RQ worker 和质量/Webhook worker；Webhook 文档描述 project/organization、secret、SSL 和事件 payload；质量文档要求 Ground Truth job 进入 acceptance/completed 后计算指标。文档是使用说明，不替代源码状态机和故障证据。

### 27.6 当前核对质量裁决与必须补强项

1. **高风险：跨资源一致性不足。** DB、RQ、文件、缓存、对象存储和外部 HTTP 没有共同事务；`on_commit` + 静默清理失败会留下不可见孤儿。应增加删除/迁移/导出产物账本、失败重试和周期对账。
2. **高风险：取消不是租约。** queued cancel 与领取存在竞态，started cancel 只覆盖 export；应引入 lease id、owner、attempt、expiry、heartbeat 和提交 CAS，拒绝过期 worker 的迟到写入。
3. **高风险：Webhook 不是 exactly-once。** RQ Retry 只提供任务重试；应固定 event/idempotency key、delivery attempt、死信和安全重放契约，并要求接收端去重。
4. **中风险：终态投影不完整。** Request 的 canceled/stopped 可能被删除为 404，SDK 主要识别 FINISHED/FAILED；客户端必须把 canceled/stopped/expired 作为终态停止轮询。
5. **中风险：架构聚合度高。** `engine` 同时承载模型、REST、媒体、缓存、云存储和标注写回；改动需联检 migration、schema、SDK、UI、队列和测试，不能只看单个 ViewSet。
6. **验证缺口：** 当前核对未安装依赖、未启动 Docker、未运行 pytest/Cypress/Yarn/Django/RQ 或真实对象存储；上述问题是 L0 静态审计结论，L2-L4 仍需隔离环境故障注入和资源前后对账。

### 27.7 分段读取与收口记录

- **代码段：** `cvat/apps/engine/models.py`、`task.py`、`views.py`、`serializers.py`、`signals.py`、`cache.py`、`media_io/*`、`cloud_provider.py`、`dataset_manager/*`。
- **异步段：** `cvat/rqworker.py`、`rq_patching.py`、`settings/base.py`、`redis_handler/background.py`、`redis_handler/views.py`、各 app `rq.py`、`quality_control/quality_reports.py`、`consensus/merging_manager.py`。
- **集成段：** `webhooks/models.py`、`dispatch.py`、`tasks.py`、`utils.py`、`events/*`、IAM/organizations/OPA rules、lambda/worker 配置。
- **证据段：** `tests/python/README.md`、requests/jobs/quality/webhook/cloud storage REST tests、site architecture/webhooks/quality/cloud storage docs。
- **CodeGraph：** 已尝试，目标仓库没有 `.codegraph/`，未运行 `codegraph init`，未伪造调用图证据。
- **修改范围：** 仅本文件追加本节；未改 CVAT 源码、配置、依赖或测试，也未删除原始 `细探-cvat.md`。

## 代码地图现状复核（2026-08-22）

文中“目标仓库没有 `.codegraph`”属于早期核对记录，现已过期。当前目标根 `~/Documents/Agent/github 源码参考/30_多模态与媒体分析/50_dataset_annotation_quality/cvat` 存在独立 `.codegraph/`；`codegraph status` 退出码为 0，返回 1,686 files、28,581 nodes、72,755 edges。错绑 MCP 仍不作为 CVAT 证据；CodeGraph 可用不代表 Django/RQ、对象存储或 webhook 已运行验证。
