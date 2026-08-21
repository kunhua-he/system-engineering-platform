# uniapp-learn 架构档案

## 1. 项目定位

`uniapp-learn` 是精易官方（Gitee 用户/组织 `JYtechnology`）维护的中文 uni-app 入门课程与示例源码仓库，不是一个面向生产环境的单一业务应用。仓库把课程讲义和多个相互独立的 HBuilderX/uni-app 示例工程放在同一 Git 根目录，内容从 Vue 单文件组件基础逐步扩展到条件/列表渲染、页面路由、原生 tabBar、组件封装、静态资源与 npm、生命周期，以及一个接近官方 `hello-uniapp` 的大型多端 API/组件展示工程。

课程文档声称的教学基线是 HBuilderX `v3.2.9`、Vue `2`（`README.md:19-25`、`第一课.md:3-9`）。大型示例 `第七课2` 的 `manifest.json` 也明确声明 `vueVersion: "2"`（`第七课2/manifest.json:123-140`），但仓库包含多端条件编译和部分 Vue 3 兼容代码；不能据此推断所有页面都已在所有平台验证。

**范围判断：** 本档案描述当前本地源码、工程配置、课程说明和 Git 基线；课程文字属于学习材料，不等同于运行契约。`第七课2` 是唯一具有完整大型示例工程形态的目录，其余课程目录主要是单课演示工程。

## 2. 总体流程图

```text
课程讲义（README.md、第一课.md～第九课.md）
        │ 解释 Vue / uni-app 概念与操作
        ▼
独立课程工程（第一课～第六课、 第七课3、 第八课）
        │ 每个工程各自拥有 App.vue / pages.json / manifest.json
        │ 页面数据在组件本地 data() 中维护
        ▼
HBuilderX / uni-app 编译器
        │ 条件编译（APP-PLUS、H5、MP-*、VUE3 等）
        ├──────────────► H5
        ├──────────────► App（Vue / nvue；部分能力依赖 plus）
        ├──────────────► 微信/支付宝/百度/字节/QQ 等小程序
        └──────────────► 快应用（配置声明，未在本地验证）

第七课2 大型示例：
App.vue + store/index.js + pages.json
        │
        ├── 顶部/左侧窗口与路由同步（windows/）
        ├── tabBar：内置组件 / API / 扩展组件 / 模板
        ├── pages/component：uni-app 基础组件示例
        ├── pages/API：登录、请求、存储、媒体、位置、设备等 API 示例
        ├── pages/extUI：uni-ui 扩展组件示例
        ├── pages/template：导航、列表详情、通讯、图表等模板
        ├── components/：uni-* 可复用组件
        ├── common/：公共样式、权限、工具、校验、HTML 解析
        └── platforms/app-plus/：App 专属语音、传感器、推送等示例
```

## 3. 真实目录地图

当前 Git 基线扫描到根目录课程文档 12 个、课程/示例目录 9 个；另有 `第七课2/README.md`、`第七课2/changelog.md` 两个工程内说明文件。排除 `node_modules` 后有 564 个已跟踪文件，其中 `.vue` 258 个、`.nvue` 23 个、`.js` 80 个、`.json` 62 个、`.md` 14 个。第八课还跟踪了 1,054 个 `node_modules` 文件（均位于 `第八课/node_modules`，主要为 lodash 依赖快照）。

| 路径 | 职责与事实状态 |
|---|---|
| `README.md` | 课程总说明、uni-app 多端定位、HBuilderX/CLI 建工程说明；是说明材料，不是应用入口。 |
| `第一课/` | Vue 插值与响应式数据最小示例；`pages/index/index.vue` 点击轮换 `Hello`/`Vue`/`uni-app`。 |
| `第二课/` | `v-bind`、class/style 绑定、`v-on/@click` 示例；页面点击修改样式状态。 |
| `第三课/` | `v-if`、`v-else`、`template v-if` 条件渲染示例。 |
| `第四课/` | `v-for` 数组/对象渲染、`:key` 与删除数组项示例。 |
| `第五课/` | `uni.navigateTo` URL 参数和 `eventChannel` 页面事件通信；包含 `index2`、`index3` 目标页。 |
| `第六课/` | 原生 `tabBar` 配置示例，`pages/index` 与 `pages/user` 两个 tab 页及图标资源。 |
| `第七课1.md` | 仅课程讲义，讲组件基本概念、属性、事件；没有对应同名源码目录。 |
| `第七课2/` | 大型 `hello-uniapp` 风格工程；完整页面注册、子包、tabBar、windows、components、store、App 专属能力和多端资源。 |
| `第七课3/` | 自定义 `extern-inputbox` 组件示例，演示 props、事件、`ref` 和子组件公开方法。 |
| `第八课/` | 静态资源、公共 JS、文件引入和 npm 讲义配套最小工程；带 `package-lock.json` 与已跟踪 lodash 文件，但未发现同目录顶层 `package.json`。 |
| `第九课.md` | 生命周期讲义，区分 App、页面、组件生命周期；无对应同名源码目录。 |
| `*.md` | 中文课件；内容引用 DCloud/uni-app 文档与论坛，部分代码块是教学片段，不能直接当作可执行代码。 |

### 3.1 小型课程工程的共同形态

`第一课`～`第六课`、`第七课3`、`第八课` 多数目录均有 `App.vue`、`pages/index/index.vue`、`pages.json`、`manifest.json`、`main.js`、`index.html`、`uni.scss`、`.hbuilderx/launch.json` 和静态 logo。课程目录之间是复制/演进式的独立工程，不存在根级 workspace、统一 `package.json` 或跨目录模块导入。

这些 `pages.json`/`manifest.json` 含 uni-app 预处理注释（如 `// #ifdef`），按标准 JSON 解析会失败；这是 HBuilderX/uni-app 工程配置格式的实际特征，不应把“普通 JSON 解析失败”误判成已确认的编译失败。未使用 HBuilderX/uni-app 编译器实际构建验证。

### 3.2 `第七课2` 大型工程分层

- **应用壳层：** `App.vue` 监听 `onLaunch/onShow/onHide`，在 `APP-PLUS` 下进行版本更新请求和 `uni.preLogin`；`main.js` 负责应用启动与 `store` 注入（路径：`第七课2/App.vue`、`第七课2/main.js`）。
- **路由/布局层：** `pages.json` 注册首屏、主页面、`subPackages`、`leftWindow`、`topWindow`、全局样式和 tabBar；`windows/top-window.vue` 同步顶部 tab；`windows/left-window.vue` 按路由切换左侧栏目组件。
- **示例页面层：** `pages/component` 展示内置组件，`pages/API` 展示 uni API，`pages/extUI` 展示 uni-ui，`pages/template` 展示可复用页面模板；每个页面通常自持 `data()`、事件处理和示例状态。
- **组件层：** `components/uni-*` 提供表单、列表、表格、弹窗、导航、日期、数据选择器、图标等组件；组件之间通过 props、事件、slot 和少数父子实例引用协作。
- **状态层：** `store/index.js` 同时兼容 Vue 2 `new Vuex.Store` 和 Vue 3 `createStore` 分支；持有登录、openid、颜色、左窗口路由和 univerify 状态，并提供 mutations/getters/actions。
- **公共支撑层：** `common/permission.js` 处理 App 权限请求，`common/graceChecker.js` 做表单规则校验，`common/util.js`、`airport.js`、`html-parser.js` 提供工具，`uni.css/uni-nvue.css` 提供通用样式。
- **平台适配层：** `platforms/app-plus/` 提供语音识别、方向/距离传感器、推送、摇一摇、反馈等 App 示例；`wxcomponents/vant` 提供微信自定义组件静态资源；`.nvue/.ts/.wxml/.wxs/.wxss` 体现多端示例和组件资产。

## 4. 模块职责与已实现范围

### 4.1 课程序列

| 课程 | 源码证据 | 当前结论 |
|---|---|---|
| 1 | `第一课/pages/index/index.vue:1-29`、`第一课/App.vue:1-12` | **已实现源码示例**：SFC、`data()`、插值、点击事件与数组状态变更。 |
| 2 | `第二课/pages/index/index.vue:1-31` | **已实现源码示例**：`v-bind` class/style、`@click` 修改响应式数据。 |
| 3 | `第三课/pages/index/index.vue:10-32` | **已实现源码示例**：`template v-if` 和布尔状态切换；`v-show` 仅在讲义中说明。 |
| 4 | `第四课/pages/index/index.vue:22-61` | **已实现源码示例**：对象数组循环、`:key="item.id"`、`splice` 删除；其它循环写法保留为注释。 |
| 5 | `第五课/pages/index/index.vue:18-39`、`index2/index2.vue:9-20`、`index3/index3.vue:9-29` | **已实现源码示例**：URL 参数和 eventChannel；页面必须由 `pages.json` 注册是讲义约束。 |
| 6 | `第六课/pages.json`、`第六课/pages/index/index.vue`、`第六课/pages/user/user.vue` | **声明与源码均存在**：tabBar 配置和两页源码存在；未跨端运行确认。 |
| 7.1 | `第七课1.md:1-149` | **仅声明/讲义**：组件概念、属性、事件。无对应工程目录。 |
| 7.2 | `第七课2/pages.json:1-1318`、`第七课2/components/`、`第七课2/pages/` | **已实现示例源码**：大量页面、组件和多端配置存在；每个演示能力是否在目标平台可用仍需单独运行验证。 |
| 7.3 | `第七课3/pages/index/index.vue:1-34`、`components/extern-inputbox/extern-inputbox.vue:1-57` | **已实现源码示例**：props、`$emit('oncheckbox')`、`ref`、`getState()`。但组件中 `checkbox` 的 `checked` 未在事件处理器中翻转，演示的“选中状态”行为不能仅凭静态源码确认完整。 |
| 8 | `第八课.md:1-105`、`第八课/` | **混合状态**：静态资源和 npm 讲义明确；目录有 `package-lock.json`/lodash 快照，但未确认一个可独立安装构建的顶层 npm 工程。 |
| 9 | `第九课.md:1-74` | **仅声明/讲义**：生命周期表格和平台说明；源码中只有各工程分散的 `App.vue`/页面钩子示例。 |

### 4.2 `第七课2` 的页面功能域

`第七课2/pages.json` 明确注册四个 tabBar 入口：

- `pages/tabBar/component/component`：内置组件示例；
- `pages/tabBar/API/API`：接口示例；
- `pages/tabBar/extUI/extUI`：扩展组件示例；
- `pages/tabBar/template/template`：页面模板示例。

API 子包 `pages/API` 的源码覆盖登录/用户信息、支付、分享、请求、上传/下载、文件、图片、音视频、位置、存储、SQLite、蓝牙、生物认证、震动、WebSocket、传感器等；典型证据包括 `pages/API/request/request.vue:45-151`、`storage/storage.vue:59-108`、`get-location/get-location.vue:80-94`、`websocket-global/websocket-global.vue:57-75`。这些是“调用演示”，不是稳定的后端 API 层：请求地址、登录和支付依赖外部 DCloud 云函数/平台账号与平台运行时。

扩展组件子包 `pages/extUI` 使用 `components/uni-*`，演示 `uni-badge`、`uni-grid`、`uni-forms`、`uni-table`、`uni-popup`、`uni-datetime-picker`、`uni-data-*` 等；`components/uni-table/uni-table.vue:40-80` 显示其 props/事件契约，`selection-change` 是多选变化事件，表格内部维护行实例、选择数据和索引。

模板子包 `pages/template` 覆盖导航栏、组件通信、列表到详情、tabbar、swiper、外部 scheme、Vant 微信自定义组件、全局数据/Vuex 等；`windows/top-window.vue:18-83` 与 `windows/left-window.vue:11-99` 共同构成 H5/大屏布局的顶部 tab 和左侧动态菜单。

## 5. 关键数据模型与状态

本仓库没有数据库、后端模型或持久化表；“数据模型”主要是页面局部状态、组件 props 和 Vuex 状态。

### 5.1 小型课件状态模型

- 第一课：`title: string[]`、`current: number`；按钮使 `current` 自增并循环归零（`第一课/pages/index/index.vue:14-28`）。
- 第二课：`isActive/isred: boolean`、`fontSize: number`、`activeColor: string`；点击事件直接修改四个字段（`第二课/pages/index/index.vue:13-31`）。
- 第三课：`seen: boolean`；点击取反驱动条件渲染（`第三课/pages/index/index.vue:23-32`）。
- 第四课：`array: {id:number,name:string,score:number}[]`、`object: {title:string,type:string}`；`splice` 改变数组（`第四课/pages/index/index.vue:31-61`）。
- 第五课：目标页 `id/name` 接收 URL 或 eventChannel 数据（`第五课/pages/index2/index2.vue:9-20`、`index3/index3.vue:9-29`）。
- 第七课3：组件 `value: string`、`checked: boolean`；props 为 `label/placeholder`，公开 `getState()` 返回 `{value,checked}`（`第七课3/components/extern-inputbox/extern-inputbox.vue:9-39`）。

### 5.2 `第七课2` Vuex 状态模型

`第七课2/store/index.js:12-25` 定义：

- 登录：`hasLogin`、`isUniverifyLogin`、`loginProvider`、`openid`、`univerifyErrorMsg`；
- 演示状态：`testvuex`、`colorIndex`、`colorList`；
- 大屏布局：`noMatchLeftWindow`、`active`、`leftWinActive`、`activeOpen`、`menu`。

mutations 负责登录/登出、openid、颜色索引、左窗口匹配、活动页面和 univerify 状态；getter `currentColor` 通过 `colorIndex` 选颜色；action `getUserOpenId` 调用 `uni.login` 后用定时器模拟服务器返回 openid（`store/index.js:71-100`）。该 action 的“123456789”是明确的 mock/教学数据，不是已接通的身份服务。

### 5.3 外部存储与数据边界

`pages/API/storage/storage.vue` 演示 `uni.getStorage`、`uni.setStorage` 和 `uni.clearStorageSync`；`file/file.vue` 将保存文件路径写入 storage；登录/支付示例写入 `openid`、`apple_nickname` 等键。它们是设备端/小程序端运行时存储，不是仓库内的数据库。`sqlite/sqlite.vue` 仅为平台 API 演示，当前档案未将其认定为仓库自有数据层。

## 6. 真实调用链与接口边界

### 6.1 页面跳转

```text
用户点击 pages/index/index.vue
    ├─ uni.navigateTo({url: '../index2/index2?id=1&name=张三'})
    │      └─ index2.onLoad(option) 读取 option.id / option.name
    └─ uni.navigateTo({url:'../index3/index3', events, success})
           ├─ success 回调 eventChannel.emit('page_index3_receive', data)
           └─ index3.getOpenerEventChannel().on(...) 接收并更新 id/name
```

证据：`第五课/pages/index/index.vue:18-39`、`第五课/pages/index2/index2.vue:9-20`、`第五课/pages/index3/index3.vue:9-29`。`pages.json` 的页面注册由工程配置负责；跳转到 tabBar 页、外部 URL 等平台规则主要在 `第五课.md:126-131` 中声明。

### 6.2 大型工程路由与窗口同步

```text
$route 变化
  ├─ windows/top-window.vue.watch($route)
  │    ├─ 计算 component/API/extUI/template 当前索引
  │    └─ tabBar 路由命中时 redirectTo 到对应首页
  └─ windows/left-window.vue.handlerRoute()
       ├─ setLeftWinActive(newRoute.path)
       ├─ 根据路径选择 componentPage/API/extUI/templatePage
       └─ 未匹配路由 redirectTo('pages/error/404')
```

证据：`第七课2/windows/top-window.vue:52-82`、`第七课2/windows/left-window.vue:73-97`、`第七课2/store/index.js:48-61`。

### 6.3 App 更新与一键登录

```text
App.vue.onLaunch（仅 APP-PLUS 分支）
  ├─ plus.runtime.appid != 'HBuilder'
  │    └─ uni.request(外部 update URL，携带 appid/version/imei)
  │         └─ isUpdate=true → uni.showModal → plus.runtime.openURL(url)
  └─ uni.preLogin({provider:'univerify'})
       ├─ success → Vuex setUniverifyErrorMsg()
       └─ fail → Vuex setUniverifyLogin(false) / 记录错误
```

证据：`第七课2/App.vue:1-61`。外部 update/user-center/pay URL 是示例依赖，不能视为本地服务接口；未在当前环境执行网络调用。

### 6.4 API/平台边界

仓库没有自建 HTTP 路由、服务端控制器或统一 SDK。接口边界分为：

1. **uni-app 运行时 API：** `uni.request`、`uni.login`、`uni.getStorage`、`uni.navigateTo`、`uni.connectSocket` 等，由目标平台提供。
2. **App Plus 原生 API：** `plus.runtime`、`plus.speech`、`plus.device` 等，受 `APP-PLUS` 条件编译和 App 权限/模块影响（`第七课2/platforms/app-plus/speech/speech.vue:28-97`）。
3. **组件接口：** props、slot、事件、`ref` 方法；例如 `uniTable` 的 `data/border/stripe/type/emptyText/loading/rowKey` 和 `selection-change`（`components/uni-table/uni-table.vue:40-80`）。
4. **外部云函数/服务：** `App.vue` 更新地址、登录/支付页面中的 `bspapp.com` 地址；依赖远端服务与平台凭据，当前仅静态确认地址存在。

## 7. 配置、依赖与构建边界

- **开发工具：** 课程 README 指定 HBuilderX `v3.2.9`；HBuilderX 内置 uni-app 环境，课程不要求单独安装 uni-app（`README.md:3-15`）。
- **框架：** Vue 2 教学基线；`第七课2/manifest.json` 声明 `vueVersion: "2"`，`package.json` 的工程名为 `hello-uniapp`、版本 `3.2.6`、依赖字段为空（`第七课2/package.json:1-24`）。
- **构建配置：** 每个小工程有 `main.js`、`manifest.json`、`pages.json`、`index.html`、`uni.scss`；`第七课2` 另外有大量条件编译和 App/H5/小程序配置。
- **平台声明：** `第七课2/manifest.json` 声明 App-plus OAuth/Payment/Push/Share/Speech/VideoPlayer 模块、Android 权限、iOS 音频后台模式、微信/支付宝/百度/头条组件开关、H5 history 路由和 QQ 地图 key（`第七课2/manifest.json:8-140`）。这些是配置声明，不是权限已获批、密钥有效或平台构建成功的证据。
- **公共组件/资源：** `第七课2/components/`、`static/`、`wxcomponents/`、`common/`、`platforms/`；`第八课.md:38-92` 说明 `@` 根路径、`static`、公共 JS 和 npm 约束。
- **npm：** 仅 `第七课2/package.json` 提供工程元数据，依赖为空；`第八课/package-lock.json` 与 `第八课/node_modules` 存在，但当前扫描未发现第八课顶层 `package.json`，不能宣称其为可复现 npm 安装工程。仓库还跟踪依赖目录文件，增加了版本与跨平台复现风险。
- **外部密钥/权限：** manifest 中存在 QQ 地图 key 字段和多项 Android 权限声明；未做有效性、最小权限或线上安全审计，后续使用前应重新核查。

## 8. 测试与验证现状

### 8.1 已确认的测试结构

- 仓库没有 `tests/`、`test/` 或 CI 配置的证据。
- `第七课2/package.json:7-9` 的唯一 npm script 是：`test: echo "Error: no test specified" && exit 1`，因此它明确不是有效自动化测试入口。
- 课程源码以人工演示页面为主，页面内 `console.log`、定时器 mock 和示例外部 URL 不构成测试。

### 8.2 本轮实际验证

本轮仅做只读静态取证，没有安装依赖、没有启动 HBuilderX/uni-app 编译器、没有调用外部接口、没有触碰数据库或平台运行环境。执行/读取证据包括：

- `git status --short --branch`：建档前工作树干净，分支 `master`；
- `git remote -v`、`git log`：记录版本基线；
- `git ls-files`：统计目录、文件类型与跟踪的 `node_modules`；
- 人工读取 `README.md`、全部课程 Markdown、关键 `App.vue`/页面/组件/`pages.json`/`manifest.json`/`package.json`/store/common 文件。

**未验证项：** HBuilderX 实际编译、H5/App/各类小程序运行、条件编译后的页面完整性、平台权限弹窗、外部云函数、登录/支付/地图/语音/WebSocket 服务，以及 `第七课2` 约 1,300 行 `pages.json` 所列全部页面逐项可达性。

## 9. 已知风险与后续复核点

1. **非标准 JSON 不能脱离 uni-app 解析器处理：** 多个 `pages.json`/`manifest.json` 含注释或 HBuilderX 特殊格式；普通 JSON 工具报错并不等价于 uni-app 构建失败，反之也不能证明编译成功。
2. **课程工程彼此独立且重复：** 根目录没有统一构建编排；修改公共教学约定不会自动传播到各课工程。
3. **大型工程外部依赖多：** `App.vue`、登录、支付、地图、语音、推送等均有平台或远程依赖，静态源码不能证明服务可用。
4. **演示代码含 mock/教学简化：** `store/index.js` action 产生固定 mock openid；多处 `setTimeout` 模拟异步；不能作为生产认证、数据一致性或错误恢复实现。
5. **跨平台条件路径复杂：** `pages.json` 使用 `APP-PLUS/H5/MP-* /VUE3` 条件；不同目标平台实际生效页面集合不同，需按平台分别编译。
6. **依赖快照混入仓库：** `第八课/node_modules` 已跟踪 1,054 文件，且顶层 package 元数据不完整；后续若要复现应先核对 lockfile、Node/npm 版本及忽略规则。
7. **示例组件存在行为待核对点：** `第七课3/components/extern-inputbox/extern-inputbox.vue` 的 checkbox 事件只 emit 当前 `checked`，未见显式翻转 `checked`；应运行确认平台是否自动同步，不能仅凭课件描述下结论。
8. **课程文档与代码存在版本/平台漂移可能：** README 链接和 HBuilderX 版本是历史资料（Git 仅有 2021-10-28 单个 grafted 提交）；应将当前 DCloud 文档与实际编译器版本作为后续验证依据。

## 10. Git 基线与证据索引

### 10.1 基线

- 本地仓库：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/uniapp-learn`
- 远程：`origin https://gitee.com/JYtechnology/uniapp-learn.git`
- 本地分支：`master`
- 建档前 HEAD：`abc26a6221cfa3189266b2dd1a76dc53ed9ed118`
- 建档前 HEAD 时间：`2021-10-28 09:48:24 +0800`
- 建档前提交信息：`更新第九课内容。`
- Git 历史：本地浅克隆/移植状态显示 `git rev-list --count HEAD = 1`，`HEAD`、`origin/master`、`origin/HEAD` 同指上述提交；本轮未对远程服务做新的 fetch，因此不把它表述为远程当前最新提交。
- 本轮允许的变更：仅新增/更新本文件 `ARCHITECTURE.md`；未修改源码、依赖、测试、配置或 Git 历史，未删除任何旧细探/课件文件。

### 10.2 关键证据路径

- 项目定位与版本说明：`README.md:1-30`
- 课程入门与 Vue 2/HBuilderX：`第一课.md:1-82`
- 指令：`第二课.md:1-120`、`第二课/pages/index/index.vue:1-48`
- 条件渲染：`第三课.md:1-67`、`第三课/pages/index/index.vue:10-32`
- 列表与 key：`第四课.md:1-195`、`第四课/pages/index/index.vue:22-61`
- 路由与 eventChannel：`第五课.md:1-203`、`第五课/pages/index/index.vue:18-39`
- tabBar：`第六课.md:1-96`、`第六课/pages.json`、`第六课/pages/index/index.vue`、`第六课/pages/user/user.vue`
- 组件库/封装：`第七课2.md:1-83`、`第七课3.md:1-71`、`第七课3/components/extern-inputbox/extern-inputbox.vue:1-57`
- 静态资源/npm：`第八课.md:1-105`、`第八课/package-lock.json`
- 生命周期：`第九课.md:1-74`
- 大型工程入口：`第七课2/App.vue:1-136`、`第七课2/main.js:1-39`、`第七课2/manifest.json:1-140`、`第七课2/package.json:1-105`
- 大型工程路由/窗口：`第七课2/pages.json:1-1318`、`第七课2/windows/top-window.vue:1-140`、`第七课2/windows/left-window.vue:1-119`
- 大型工程状态：`第七课2/store/index.js:1-130`
- 公共能力：`第七课2/common/permission.js`、`graceChecker.js`、`util.js`、`html-parser.js`、`airport.js`
- API 示例：`第七课2/pages/API/request/request.vue`、`storage/storage.vue`、`login/login.vue`、`request-payment/request-payment.vue`、`websocket-global/websocket-global.vue`
- 组件实现：`第七课2/components/uni-table/uni-table.vue:1-452`、`第七课2/components/uni-forms/uni-forms.vue`、`第七课2/components/uni-popup/uni-popup.vue`
- App 专属能力：`第七课2/platforms/app-plus/speech/speech.vue:1-105`、同目录 `orientation/`、`proximity/`、`push/`、`shake/`、`feedback/`

## 11. 维护边界

本文件是本项目首轮架构事实的唯一收口位置。后续深挖应直接更新本文件并保留“已实现/仅声明/未验证”的区分；不要另建平行架构报告。后续若进行运行验证，应至少按 H5、App Vue、App nvue、微信小程序四类目标记录编译命令、平台版本、结果和失败页面；若新增课程源码或重构大型示例，应重新计算目录/依赖/Git 基线并更新对应证据路径。
