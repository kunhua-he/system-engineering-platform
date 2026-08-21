# AutoLinker 架构归档

> 本文是 AutoLinker 项目根目录唯一的架构事实文档。说明、结论、风险和验证记录使用中文；源码路径、类名、函数名、字段名、路由、命令、协议名和第三方名称保留原文。后续架构细探应归并到本文件，不再创建平行架构报告。

## 1. 项目定位

AutoLinker 是加载到易语言 IDE 进程内的支持库插件：构建产物为 `AutoLinker.fne`（动态库形态），通过易语言支持库接口接收 IDE 通知、安装窗口/编辑器 Hook、注册菜单，并提供 AI Agent 对话与本地 MCP Streamable HTTP 服务。它解决的核心问题是：`.e` 源码由 IDE 管理且不能按普通文本直接编辑，因此要从 IDE 内存导出当前工程快照，经 `e-packager` 解包成文本镜像供 AI 读取，再把修改映射回 IDE 的真实程序项。

项目同时包含：

- AI 多协议客户端：OpenAI Chat、OpenAI Responses、Gemini、Claude；支持流式响应、重试、取消和工具调用循环。
- IDE 内 AI 对话页、计划模式、会话持久化、主题配置与工程级 `.AGENTS.md` 规范注入。
- 外部 Agent MCP：源码内实现 JSON-RPC/HTTP 服务以及公开工具目录。
- 易语言工程镜像、文件搜索/读取、真实页读取、CAS 哈希保护的编辑、差异预览和快照恢复。
- `.ec` 模块依赖目录、`.fne` 支持库目录检索，以及模块/支持库导入管理。
- 链接器 `link.ini` 切换、动态/静态 `.ec` 自动切换、核心库 `.lib` 强制链接。
- 无头编译启动器 `AutoLinkerTest`、GameAnalytics 自检、版本/链接命令字符串测试。
- 基于 Win32、MFC、WebView2、Detours 和易语言私有接口的逆向适配层。

## 2. 版本基线与研究范围

| 项目 | 事实 |
|---|---|
| 目标根目录 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/AutoLinker` |
| 本地分支/提交 | `master` / `b3a1358a1ca80f201c14327cd082c65914c9a7e0` |
| 本地提交时间 | `2026-08-04T21:14:26+08:00` |
| 远程地址 | `https://github.com/aiqinxuancai/AutoLinker.git` |
| 远程 `master` | `3f5f2a95b0a175697dc2883d2b906ee6481f6184`，`2026-08-17T10:48:48+08:00` |
| 远程复核方式 | 经 `127.0.0.1:4780` 克隆独立快照 `/tmp/AutoLinker-remote-v4ltrI`；未在目标工作树执行 fetch/pull |
| 远程与本地差异 | 远程只比本地新增文档/技能内容：`README.md`、`CONFIG.md`、`skills/autolinker-usage/SKILL.md` 和 `.claude/skills/autolinker-usage/SKILL.md`；未发现 `src/`、项目文件或测试实现差异 |
| 当前版本常量 | `src/AutoLinkerVersion.h:5` 为 `AUTOLINKER_VERSION "0.0.0"`；`src/AutoLinker.h:75-87` 的支持库版本/描述仍为固定宏 |
| 代码图 | 目标根没有 `.codegraph/`，`codegraph_explore` 明确返回未索引；本次源码证据采用直接读取、路径检索、静态调用链和项目文件分析 |
| 旧细探 | 目标根没有 `细探-*.md`；本文件为首次根架构归档 |

本次只允许、也只修改了目标根 `ARCHITECTURE.md`；没有修改源码、依赖、测试、配置、Git 元数据、远程仓库，没有安装依赖、启动 IDE 或构建工程。

## 3. 总体流程图

```text
易语言 IDE 加载 AutoLinker.fne
        │
        ▼
AutoLinker_MessageNotify(NL_SYS_NOTIFY_FUNCTION / NL_IDE_READY)
        │
        ▼
FneInit
  ├─ 获取主窗口、安装 MainWindowSubclassProc
  ├─ 注册 IDE 菜单/编辑器子类化巡检/文件与编译 Hook
  ├─ AIChatFeature::Initialize
  │    ├─ WebView2 AI 对话页
  │    ├─ AIJsonConfig / ConfigManager 加载配置
  │    ├─ AIChatSessionStore 恢复当前 .e 会话
  │    └─ AIService::ExecuteChatWithTools
  │          ├─ OpenAI/Gemini/Claude HTTP 流式协议适配
  │          └─ ExecuteToolCall → 主线程 SendMessage → IDEFacade/WorkspaceMirror
  ├─ LocalMcpServer::Initialize
  │    └─ 127.0.0.1:19207 起逐端口 bind → JSON-RPC → AIChatFeature::ExecutePublicTool
  ├─ DependencyCatalogCache 异步刷新
  ├─ GameAnalyticsClient（无头编译模式跳过）
  └─ 后台版本检查
        │
        ▼
当前源码路径变化 / 编译调试通知 / MCP 工具请求
        │
        ├─ 读取：IDE 内存快照 → e-packager unpack → WorkspaceMirror
        │        → list/search/read 或 IDEFacade 真实页读取
        ├─ 编辑：read_real_file → code_hash → edit/write/diff/restore
        │        → IDEFacade/真实页写回 → 编译前校验 → 镜像更新或失效
        ├─ 编译：HeadlessCompileRunner 或 compile_with_output_path
        │        → IDEFacade → 产物路径/时间戳/输出窗口/错误光标验证
        └─ 依赖/设置：ModelManager、LinkerManager、ForceLinkLibManager、WebView2 设置页
```

## 4. 真实分层与目录地图

### 4.1 工程入口与宿主适配层

- `src/main.cpp`：DLL 入口文件。
- `src/AutoLinker.cpp`：支持库元信息 `LibInfo`、`GetNewInf()`、`AutoLinker_MessageNotify()`、`FneInit()`、主窗口子类过程和 9 项插件菜单；`FneInit()` 在 `src/AutoLinker.cpp:355-451` 串起主要生命周期。
- `src/AutoLinker.h`、`src/AutoLinkerInternal.h`：易语言支持库 ABI、`LIB_INFOX` 宏、全局状态、通知入口和 AI/菜单函数边界。
- `elib/`：易语言 ABI 与内部公开声明，包括 `PublicIDEFunctions.h`、`lib2.h`、`fnshare.h`、`mtypes.h`、`lang.h` 等。
- `detours/`：Detours 及其 x86/x64 反汇编/导入辅助实现，服务于文件/编译/内部函数 Hook。
- `src/EideInternalTextBridge.*`、`src/EideProjectBinarySerializer.*`、`src/direct_global_search.*`、`src/MemFind.*`：按版本特征、RVA/签名和内存布局定位易语言私有内部对象和函数；这些实现是版本敏感的宿主适配边界。

### 4.2 IDE 交互与源码编辑层

- `src/IDEFacade.h/.cpp`：把 `NotifySys(NES_RUN_FUNC, ...)` 和 `FN_*` 功能号封装为高层操作，覆盖当前页读取、光标/函数块定位、剪贴板读写、行范围/函数/整页替换、菜单、ECOM、编译和输出窗口。
- `src/RealPageCodeToolSupport.*`：真实页文本规范化和结构化差异候选生成。
- `src/PageCodeCacheManager.*`：真实页读取结果的哈希/快照缓存。
- `src/WorkspaceMirror.h/.cpp`：会话级解包镜像和路径到 `ProgramItemRef` 的映射；`ProgramItemRef` 记录 `relativePathUtf8`、`pageNameLocal`、`kind`、`editable`、`fixedTable`、`formXml`（`src/WorkspaceMirror.h:16-24`）。
- `src/WorkspaceFileTools.*`：镜像文件的 list/search/read/read_files/read_code_item 等文本工具。
- `src/PathHelper.*`、`src/WindowHelper.*`、`src/StringHelper.*`、`src/Logger.*`：路径、窗口识别、字符串、日志和诊断共用设施。

### 4.3 AI 应用层

- `src/AIService.h/.cpp`：AI 配置解析、必填项检查、上下文窗口计算、协议/思考等级转换、连接测试、普通任务、对话流式请求、工具循环、模型输出规范化和公开工具目录。
- `src/AIJsonConfig.h/.cpp`：UTF-8 `AIConfig.json` 配置组与全局值；支持 active profile、批量写入和从旧 INI 迁移。
- `src/ConfigManager.h/.cpp`：旧/通用键值 INI 持久化，带 `std::mutex`。
- `src/AIChatFeature.h/.cpp`：AI 对话页宿主、会话状态、异步请求、取消、计划模式、自动写入开关、消息窗口协议、WebView2 交互、当前源码切换和 `ExecutePublicTool`。
- `src/AIChatTooling.h/.cpp`、`src/AIChatToolingX86.cpp`、`src/AIChatToolingInternal.h`：工具分发；非主线程工具通过 `RequestToolExecutionFromMainThread`/窗口消息转到 IDE 主线程，x86 文件实现真实页、依赖、编译和 IDE 操作。
- `src/AIChatSessionStore.h/.cpp`：按当前 `.e` 源文件建立会话目录，JSON 保存 `schemaVersion`、消息、滚动摘要、计划状态、待批准计划、自动写入状态和时间。
- `src/AIChatThemeManager.h/.cpp`：默认/自定义配色 JSON 和 WebView2 注入脚本。
- `src/AIConfigDialog.*`、`src/webview/ai_config_dialog*`、`src/webview/ai_chat_history.html`、`src/webview/ai_chat_theme_config_dialog*`：设置、会话历史和主题界面。
- `src/WinINetUtil.*`、`src/TavilyClient.*`、`src/WebDocumentClient.*`、`src/WebDocumentExtractor.*`：AI 接口、Tavily、公开 URL 获取和正文提取。

### 4.4 本地 MCP 层

- `src/LocalMcpServer.h/.cpp`：Winsock HTTP 服务、JSON-RPC 解析/响应、`initialize`/`ping`/`tools/list`/`tools/call`、GET 健康检查、端口绑定、日志和关闭。
- `src/LocalMcpInstanceRegistry.h/.cpp`：实例登记 JSON、命名互斥、进程存活判断、当前实例心跳和 `sourceFilePathHint/pageNameHint/pageTypeHint`。
- 工具目录由 `AIService::BuildPublicToolCatalog()` 构造（`src/AIService.cpp:1364-1730`），执行统一进入 `AIChatFeature::ExecutePublicTool()`（`src/AIChatFeature.cpp:6837-6854`）。

### 4.5 易语言工程工具和编译层

- `src/EPackagerIntegration.*`：从 IDE 内存导出 `.e` 快照、检查/下载/更新 `e-packager.exe`、PowerShell `Expand-Archive` 解包、子进程输出捕获和目录清理。
- `src/HeadlessCompileRunner.*`：`AutoLinkerTest headless-compile` 启动 `e.exe`，捕获启动/编译弹窗，写 JSON 结果并按退出码返回。
- `src/DependencyCatalogCache.*`：缓存和检索 `ecom/*.ec`、`lib/*.fne`，服务依赖工具。
- `src/ECOMEx.*`：导入、移除、查找 `.ec` 模块。
- `src/LinkerManager.h`、`src/AutoLinkerMenu.cpp`：读取默认 `tools/link.ini` 和 `AutoLinker/Config/*.ini`，在 IDE 编译菜单中动态生成链接器子菜单。
- `src/ModelManager.*`、`src/EcSwitchConfigDialog.*`：`ModelManager.ini` 中动态/静态 `.ec` 成对规则，WebView2 设置页校验重复/非法文件名。
- `src/ForceLinkLibManager.*`、`src/ForceLinkLibConfigDialog.*`、`src/AutoLinkerHooks.cpp`：`ForceLinkLib.ini` 规则、当前链接器名称过滤、把 `.lib` 放到 `krnln_static.lib` 前并处理 `/FORCE` 编译路径。

### 4.6 测试/示例/前端资源

- `AutoLinkerTest/AutoLinkerTest.cpp`：单一控制台测试入口和无头启动器；不是单元测试框架。
- `TestCore/`：核心库函数 C++20 静态库重写示例。
- `test_a.e`：易语言 IDE 场景测试工程资源。
- `src/webview/`：12 个 HTML、1 个 CSS；部分 `.src.html` 是构建前模板，`package.json` 只声明 `tailwindcss` 和 `preline` 开发依赖，构建脚本为 `scripts/build_ai_config_webview.mjs`。
- `.github/workflows/msbuild.yml`、`.github/release.yml`：Windows/MSBuild 与 Release 自动化线索。

## 5. 核心数据模型与持久化

| 数据/状态 | 载体 | 读写边界与用途 |
|---|---|---|
| AI 配置组 | `{易语言安装目录}/AutoLinker/AIConfig.json` | `AIJsonConfig` 内部 UTF-8；profile、active profile、全局值；`AIService::LoadSettings/SaveSettings` 消费 |
| 兼容旧配置 | `AutoLinker/Config/*.ini` 或旧键值 INI | `ConfigManager` 互斥读写；仅在 JSON 无数据时供迁移/回退 |
| 链接器集合 | `tools/link.ini` + `AutoLinker/Config/*.ini` | `LinkerManager` 以名称/ID 构建菜单；默认项 ID 从 17750 起（`LinkerManager.h:40-90`） |
| EC 动静态规则 | `AutoLinker/ModelManager.ini` | `ModelManager` 的 `map<string,string>`，动态名 → 静态名；WebView2 保存前校验文件名、重复和同名 |
| 强制链接规则 | `AutoLinker/ForceLinkLib.ini` | `ForceLinkLibRule{enabled, linkerName, libPath}`；按链接器名包含关系过滤 |
| AI 会话 | 当前 `.e` 对应的 AutoLinker 会话目录下 JSON | `AIChatStoredSession` 保存消息、摘要、计划 `normal/planning/awaiting_approval/approved`、待批准计划、自动写入和时间累计 |
| AI 配色 | AutoLinker 主题目录 JSON | `AIChatThemeManager::ThemeEntry{id,name,colors,isDefault}`；内置配色回退，自定义配色由 WebView2 提交 |
| 工程镜像 | `%TEMP%/AutoLinker/workspace-mirror/` 或工程旁 `.temp/` | `MirrorState{sourcePath,mirrorRoot,valid,itemByRelativePath}`；含内存未保存改动，成功真实页写回后可同步或失效 |
| 工程快照 | `%TEMP%/AutoLinker/unpack-snapshots/<pid>.<tick>/` | `EideProjectBinarySerializer::WriteCurrentProjectToFile` 写临时快照；成功/失败后按允许根清理 |
| e-packager 元数据 | `{易语言目录}/tools/e-packager.autolinker.json` | 记录 release `tag`、资源名和最近检查时间；缺工具/检查过期时触发 GitHub Release API |
| MCP 实例登记 | `LocalMcpInstanceRegistry::GetRegistryFilePath()` 返回的本机 JSON | `InstanceRecord` 含 PID、端口、endpoint、当前源码/页面提示和心跳；每 2 秒刷新 |
| 日志/诊断 | `AutoLinker/Log/` | `autolinker.log`、启动初始化日志、AI 代码读取/性能/往返日志、MCP 请求响应日志、无头编译结果 |
| 构建产物 | `bin/<Configuration>/` | `fne_release|Win32` 目标扩展名为 `.fne`；`AutoLinkerTest` 为控制台程序 |

持久化没有数据库或外部队列；核心状态是 JSON/INI/临时文件，IDE 内存页和私有 ABI 是最重要的运行时状态。

## 6. 真实调用链

### 6.1 插件启动/退出

1. 易语言调用导出的 `AutoLinker_MessageNotify`。
2. `NL_SYS_NOTIFY_FUNCTION` 设置 `g_notifySysReady`；`NL_IDE_READY` 进入 `FneInit`（`src/AutoLinker.cpp:454-492`）。
3. `FneInit` 获取主窗口，安装 `SetWindowSubclass(MainWindowSubclassProc)`，注册右键菜单，启动编辑器巡检，初始化 `AIChatFeature` 与 `LocalMcpServer`，异步刷新依赖目录，解析编译/调试入口，安装 `StartHookCreateFileA`，并按模式启动版本检查。
4. 主窗口收到 `WM_NCDESTROY` 时依次关闭 `GameAnalyticsClient`、`LocalMcpServer`、`AIChatFeature`，清理 `WorkspaceMirror` 并移除子类。
5. 当前 `.e` 路径变化通过 `HandleCurrentSourceFilePathChanged` 触发镜像清理、会话重绑定和 MCP 实例提示更新。

### 6.2 AI 对话与工具循环

```text
AIChatFeature::Handle... / AIChatAsyncRequest
  → AIService::ExecuteChatWithTools
  → BuildConfiguredToolCatalog / BuildChatToolDefinitions
  → AI HTTP 协议请求（流式或非流式）
  → 解析 assistant.tool_calls
  → ExecuteToolCall(toolName, argumentsJson)
  → 需要 IDE 状态的工具 RequestToolExecutionFromMainThread
  → ExecuteToolCallOnMainThreadImpl
  → 返回工具 JSON
  → 追加 tool 消息继续 AI 轮次
  → 保存 AIChatStoredSession / 更新 WebView
```

`AIService::AIChatResult` 明确区分 `ok`、`cancelled`、`toolRoundsExceeded`、工具事件、上下文前缀和 token 用量（`src/AIService.h:83-98`）。依赖管理工具在 `AIService.cpp:1777-1918` 按“最新用户消息是否明确请求”过滤，避免模型自行刷新/添加/删除模块或支持库。

### 6.3 镜像读取与真实页写入

- `WorkspaceMirror::RefreshMirror` 先取当前 `.e` 路径，再调用 `WriteCurrentProjectSnapshot`；快照失败时若存在已保存 `.e` 允许回退到文件，随后 `EnsureToolReady` 和 `RunProcessAndCapture({unpack,...})` 生成镜像（`src/WorkspaceMirror.cpp:406-577`）。
- `ParseMetadata` 读取 e-packager `_meta.json`，建立 `sourceFiles/formFiles` 及固定表索引；路径检查拒绝绝对路径、`..`、`.`、空路径和镜像外解析（`src/WorkspaceMirror.cpp:676-706`）。
- 读取工具只遍历镜像；`ResolveFileToProgramItem` 只允许 `editable` 当前工程源页面，`.xml` 窗口页面和 `ecom/elib/header` 等依赖参考不可作为普通可写源码。
- `read_real_file` 由 `AIChatToolingX86.cpp` 把镜像映射到 IDE `ProgramTreeItemInfo`，读取真实页面并计算 `code_hash`；`edit_file/multi_edit_file/write_file/restore_file_snapshot` 以此为 CAS 基线。
- 成功写回后，普通源页面在 `MirrorSourceBase` 模式尝试 `WorkspaceMirror::UpdateMirrorTextFile`；固定表或同步失败则 `InvalidateMirror`，迫使下一次读取重建镜像（`src/AIChatToolingX86.cpp:4034-4060`）。

### 6.4 MCP 请求链

1. `LocalMcpServer::Initialize` 启动 `ServerThreadMain`，尝试从 `127.0.0.1:19207` 起连续 16 个端口，成功后登记 `InstanceRecord`。
2. 服务线程 `select` 监听 socket，逐连接读取最多约 1 MiB HTTP 头、最多 2 MiB body；当前实现随后同步执行 `HandleClient`。
3. POST `/` 或 `/mcp` 进入 `TryHandleJsonRpc`；`initialize`、`ping`、`tools/list`、`tools/call` 返回 JSON-RPC，`notifications/initialized` 返回 202，无 ID 方法返回 202。
4. `tools/list` 调 `AIService::BuildPublicToolCatalogJson`；`tools/call` 调 `AIChatFeature::ExecutePublicTool`，主线程工具经窗口消息回到 IDE 上下文。
5. GET 返回健康 JSON；`Shutdown` 设置停止标记、关闭监听 socket、join 服务线程并移除实例登记（`src/LocalMcpServer.cpp:1125-1246`）。

## 7. API、CLI、协议与边界

### 7.1 AutoLinker 支持库 ABI

- `GetNewInf()` 返回 `LIB_INFOX`，公开菜单项和 `AutoLinker_MessageNotify`。
- `AutoLinker_MessageNotify(INT,DWORD,DWORD)` 是 IDE 通知入口；`NESRUNFUNC` 把原始 IDE 功能号转入 `IDEFacade::RunFunctionRaw`。
- `AutoLinkerTestApi.h` 导出 C ABI 的版本比较、链接器命令解析、版本文本、GameAnalytics 自检和多模型集成测试。

### 7.2 MCP 实现中已确认的公开方法

源码 `LocalMcpServer.cpp:843-963` 当前实际处理：`initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`；GET 健康检查和 OPTIONS 204 另行处理。工具目录包括镜像读取、真实页编辑/恢复、当前页/IDE 信息、依赖目录、模块/支持库管理、编译、PowerShell 和三个联网工具，具体 Schema 以 `AIService.cpp:1364-1730` 为准。

### 7.3 `AutoLinkerTest` CLI

`AutoLinkerTest/AutoLinkerTest.cpp:1556-1648` 实际登记：

- 无参数：轻量 smoke test。
- `version-compare <left> <right>`、`version-text`。
- `linker-out <link-command>`、`linker-krnln <link-command>`、`between-dashes <text>`。
- `gameanalytics-self-test`。
- `headless-compile <e.exe> <input.e> <output> [--target ...] [--static] [--result path] [--timeout seconds]`。
- `deepseek-model-test`、`openai-chat-test`、`openai-responses-test`、`gemini-model-test`、`claude-model-test`。

### 7.4 外部协议/系统边界

- Windows API：Win32 window/message/clipboard/process/filesystem、Winsock、WinHTTP/WinINet、COM/WebView2。
- 编译和 IDE：易语言私有通知函数、窗口标题/控件、剪贴板、内部对象布局、Detours Hook。
- 外部网络：AI provider、Tavily、GitHub Release API、网页抓取；源码通过 `WinINetUtil`/`WebDocumentClient` 统一部分 HTTP 行为。
- 外部可执行文件：`e-packager.exe`、PowerShell、易语言 `e.exe`；都经子进程捕获/诊断，但非所有调用都具备统一取消模型。
- 文件权限：插件在易语言安装目录下写配置/日志/工具，在 `%TEMP%` 写快照/镜像；写入 `.e` 的真实页面由 IDE 内部接口完成，不直接改原始加密文件。

## 8. 测试与验证结构

### 8.1 已存在的验证入口

- `AutoLinkerTest` 是可脱离易语言 IDE 的真实 C++ 验证入口，但其中多模型测试需要 API Key 和可用服务商，`headless-compile` 需要 Windows 易语言环境。
- IDE 场景由 `test_a.e`、编译后的 `AutoLinker.fne`、易语言 `e5.95.exe/e571.exe` 和日志共同验证；`AGENTS.md:43-58` 明确要求关闭 IDE 后覆盖 `lib/AutoLinker.fne`，再打开 `test_a.e`。
- 项目文件列出 `fne_release|Win32`、`fne_release|x64`、Debug/Release/静态库等配置；主 DLL 的 Win32 fne 目标在 `AutoLinker.vcxproj:133-138,426-442`，输出目录为 `bin/fne_release/`，扩展名 `.fne`。
- WebView2 依赖 `thirdparty/WebView2.h` 和 x86/x64 `WebView2LoaderStatic.lib`；主项目直接链接 `WebView2LoaderStatic.lib`，不依赖 vcpkg。

### 8.2 本次未执行事项

本机为 macOS，目标工程依赖 Windows/MSVC/Win32/MFC/WebView2、易语言 IDE 私有接口和 `.fne` 加载环境，因此没有执行 `MSBuild.exe`、`AutoLinkerTest.exe`、易语言 IDE、MCP 运行时或联网模型测试；这不是测试通过的替代品。没有发现仓库内 C++ 单元测试框架或 CI 测试报告；`.github/workflows/msbuild.yml` 只能作为 Windows CI 构建线索。

可在 Windows/VS2026 环境执行的基线命令：

```powershell
MSBuild.exe ..\AutoLinker.vcxproj /t:Build "/p:Configuration=fne_release;Platform=Win32" /m
MSBuild.exe AutoLinkerTest\AutoLinkerTest.vcxproj /t:Build "/p:Configuration=fne_release;Platform=Win32" /m
.\bin\fne_release\AutoLinkerTest.exe
.\bin\fne_release\AutoLinkerTest.exe version-compare 1.2.3 1.2.0
.\bin\fne_release\AutoLinkerTest.exe headless-compile "C:\path\to\e571.exe" "D:\demo\demo.e" "D:\demo\build\demo.exe" --target auto --static --result "D:\demo\build\compile-result.json" --timeout 120
```

正式验收应至少覆盖：加载/卸载、通知初始化、AI 配置读写和迁移、四协议连接测试、镜像包含未保存修改、路径逃逸拒绝、真实页 CAS 冲突、编辑后回读、计划批准门禁、MCP JSON-RPC 方法/工具 Schema、e-packager 缺失/更新失败、端口占用、编译产物时间戳和易语言 5.95/5.71 兼容性。

## 9. 未确认项、风险与后续复核点

### 9.1 文档与当前源码存在明显漂移（重要）

远程最新提交只更新了文档/技能，没有同步 `src/`。因此以下资料性描述不能当作当前实现证据：

- `README.md:61-63`、`skills/autolinker-usage/references/mcp-api.md:20-31` 声称 MCP 协商 `2025-11-25/2025-03-26/2024-11-05`、会话 `Mcp-Session-Id`、固定网关/多实例路由、4 个工作线程/队列和过载 503；但当前 `LocalMcpServer.cpp:759-772` 固定返回 `2024-11-05`，`TryHandleJsonRpc` 没有协议版本协商或会话状态，`ServerThreadMain:1146-1193` 是单服务线程同步处理连接，源码未见 503/队列实现。
- `LocalMcpServer.cpp:686-706` 返回 `Access-Control-Allow-Origin: *`，与文档“拒绝非空 Origin、无 CORS”不一致；应在 Windows 实机对浏览器 Origin 和原生客户端分别复测，随后决定以实现还是文档为准。
- 文档列出的 `list_instances`/`select_instance` 网关工具在当前 `AIService::BuildPublicToolCatalog` 的源码目录中未找到；当前源码只登记实例文件并提供单进程服务健康信息。多实例路由很可能是未合并分支或文档先行设计。
- `mcp-api.md` 对 21 个工具、参数必填和 `expected_base_hash` 的描述也应以 `tools/list` 运行结果及 `AIChatToolingX86.cpp` 实际校验为准；源码公开目录包含依赖管理、模块、支持库和编译工具，数量/可见性可能随源码模式过滤。

### 9.2 版本与构建风险

- `AUTOLINKER_VERSION` 为 `0.0.0`，而仓库已有 `5.0.x` 标签/远程文档版本语义；版本检查 `FneCheckNewVersion` 仍按 GitHub Releases 比较，发布产物版本身份可能不一致。
- 代码依赖 `v145`、Win32/MFC、WebView2 Runtime、易语言内部布局和 `thirdparty` 静态库；源码在 macOS 无法证明可编译。每次易语言版本或 VS 工具集变化都应重跑 `EideInternalTextBridge`/`EideProjectBinarySerializer`/`direct_global_search` 的探测路径。
- `AutoLinker.vcxproj` 的 x64 fne 配置段仅显式保留少量属性（`fne_release|x64` 在 `:139-141`），需在 Windows 真实工程中确认它是否通过继承属性完整构建；本项目主验收目标应先固定 `fne_release|Win32`。

### 9.3 读写一致性与安全风险

- 镜像是内存快照的派生物，真实页可能在读取后被用户手工修改；写入必须严格依赖 `read_real_file` 的完整 `code_hash`，不能把 `read_file` 镜像哈希当 CAS 基线。
- `WorkspaceMirror::BuildSafeRelativePath` 已做绝对路径/点段/`..`/镜像内检查，但 Windows 大小写、符号链接/重解析点、非普通文件和 UNC 路径仍应在 Windows 实机做攻击性测试。
- 公开 MCP 工具会直接进入当前 IDE 主线程，源码实现有连接/工具异常兜底，但长时间 IDE 私有调用可能阻塞 MCP；当前源码没有文档声称的统一线程池/队列/过载治理证据。
- `run_powershell_command`、模块/支持库导入和 `compile_with_output_path` 属于高影响本机动作；必须复核确认/权限/超时/进程树终止边界，不能仅依赖工具描述中的“用户确认”。
- AI 配置含 API Key；MCP 日志和 AI 往返日志应复核是否对密钥、Authorization 头、完整请求体做了脱敏，尤其是 `LocalMcpServer` 的文件日志与 `AIService` provider 日志。

### 9.4 测试缺口

- 没有仓库级跨平台自动测试；模型集成测试依赖真实外部服务，IDE/MCP/镜像/CAS/Hook 关键路径需要 Windows 集成测试夹具。
- 需要补充协议契约测试：版本协商、会话生命周期、Origin/CORS、安全绑定、tools/list 数量和 Schema、未知工具/非法 JSON/超大 body、并发连接和 503 语义。
- 需要补充数据迁移测试：AIConfig JSON 与旧 INI、会话 schemaVersion、ModelManager/ForceLinkLib 配置损坏/重复/部分写入、工具更新失败后旧版本回退。

## 10. 证据路径与维护约定

核心证据路径：

- 入口/生命周期：`src/AutoLinker.cpp`、`src/AutoLinker.h`、`src/AutoLinkerInternal.h`。
- IDE/真实页：`src/IDEFacade.h/.cpp`、`src/RealPageCodeToolSupport.*`、`src/EideInternalTextBridge.*`。
- 镜像/快照：`src/WorkspaceMirror.h/.cpp`、`src/EPackagerIntegration.h/.cpp`、`src/EideProjectBinarySerializer.*`。
- AI/会话/工具：`src/AIService.h/.cpp`、`src/AIChatFeature.h/.cpp`、`src/AIChatTooling*`、`src/AIChatSessionStore.*`。
- MCP/实例：`src/LocalMcpServer.h/.cpp`、`src/LocalMcpInstanceRegistry.*`、`skills/autolinker-usage/references/mcp-api.md`。
- 依赖/编译：`src/DependencyCatalogCache.*`、`src/HeadlessCompileRunner.*`、`src/ECOMEx.*`、`AutoLinkerTest/AutoLinkerTest.cpp`。
- 配置/设置：`src/AIJsonConfig.*`、`src/ConfigManager.*`、`src/ModelManager.*`、`src/LinkerManager.h`、`src/ForceLinkLibManager.*`、对应 WebView2 页面。
- 工程边界：`AGENTS.md`、`README.md`、`CONFIG.md`、`AutoLinker.vcxproj`、`AutoLinkerTest/AutoLinkerTest.vcxproj`。

维护规则：源码改变时先更新对应调用链、数据模型和风险段，再更新本文件的版本基线与验证记录；任何 README/技能中的新协议能力都必须在 `src/`、运行时工具目录和 Windows 集成测试中找到证据后才能升格为“已实现”。

## 11. 第三轮通用底座映射：动态库、ABI、符号与生命周期

### 11.1 本轮边界、证据等级与环境问题

本轮只对目标目录当前源码、项目文件、已有 `ARCHITECTURE.md` 和 `AGENTS.md` 做静态取证；目标根没有 `细探-*.md` 或其他旧细探文件，不能把不存在的旧材料当作证据。开工时调用 `project_context` 错绑到 `~/Documents/Agent/PHP/华世王镞_v3`，与本目标不一致，因此本轮**不采用**该项目的代码图、记忆、验证或任务状态，改以目标目录本地文件为唯一证据，并将本次结论标为弱验证。

本文采用以下事实标记，避免把声明、骨架和真实实现混写：

- **真实实现**：当前文件中存在可执行调用、资源分配/释放或条件分支，并能指出路径和行号；例如 `src/main.cpp:7-23` 的 `DllMain`、`src/WinINetUtil.cpp:183-392` 的 POST 句柄链。
- **声明/配置**：头文件、宏、`.def`、`#pragma comment(lib, ...)`、`.vcxproj` 或 README 只说明接口/构建意图，不证明宿主加载、运行库存在或调用成功；例如 `src/AutoLinker.h:67` 的通知声明、`src/AutoLinker.def:1-3` 的导出声明。
- **骨架/未证实**：存在入口或适配代码，但缺少当前 Windows 构建物、宿主实跑、依赖检查或失败场景证据；例如 x64 `fne_release` 只在 `AutoLinker.vcxproj:139-141,444-447` 显式保留少量属性，不能据此声称 x64 `.fne` 已成功构建。

L0-L4 是本轮的证据成熟度，不是功能名称：

| 等级 | 允许的结论 | 本项目当前证据 |
|---|---|---|
| L0 | 只有声明、配置、路径或设计线索 | `elib/*.h`、`*.def`、`.vcxproj`、README/技能文档；不能称运行成功 |
| L1 | 当前源码存在真实实现和可追踪调用链 | `DllMain`、`FneInit`、`LoadResource`、WinINet/进程句柄收口、`LocalMcpServer::Shutdown` |
| L2 | Windows/MSVC 编译、链接或 PE 导入/导出检查实际通过 | 本机 macOS 未执行；仓库未提供当前构建物或 CI 成功报告 |
| L3 | 脱离 IDE 的真实 Windows 运行/故障注入通过 | `AutoLinkerTest` 只是入口，未在本机运行；没有加载/卸载/位数/缺 DLL 专项结果 |
| L4 | 易语言 IDE + 目标 `.fne` + WebView2/私有 ABI/网关的端到端通过 | 未执行，必须在 Windows/易语言环境完成 |

因此，本轮能把多数源码节点定到 **L1（实现存在）**，但不能把整个动态库链路定为 L2-L4。以下“已实现”均只表示源代码事实，不表示宿主验收通过。

### 11.2 构建、链接和加载事实矩阵

| 边界 | 当前真实事实 | 归类与缺口 |
|---|---|---|
| 插件产物 | `AutoLinker.vcxproj:133-138` 将 `fne_release|Win32` 配成 `DynamicLibrary`，`TargetExt=.fne`、输出到 `bin\\fne_release\\`（`231-237`）；`src/main.cpp:7-23` 提供 DLL 入口 | **真实实现 + 构建声明**。Windows loader 如何发现并加载 `.fne` 由易语言 IDE 负责，仓库没有独立 loader |
| 官方导出 | `src/AutoLinker.def:1-3` 只导出 `GetNewInf`；`src/AutoLinker.cpp:540-544` 返回静态 `LIB_INFOX`；`src/AutoLinker.h:67` 用 `EXTERN_C` 声明 `AutoLinker_MessageNotify` | `GetNewInf` 是明确导出；通知函数是源码/ABI 声明和回调入口，但未由当前 `.def` 单独证明为 DLL 导出 |
| 静态链接依赖 | `AutoLinker.vcxproj:184-188` 直接链接 x86/x64 `WebView2LoaderStatic.lib`；源码 `#pragma comment` 还引用 `wininet.lib`、`comctl32.lib`、`Shell32.lib` 等；Detours 源文件在 `453-462` 被编入主项目 | **构建时依赖**，不是运行时依赖检测。未发现统一 import manifest、PE 导入审计或缺库诊断 |
| 运行时 WebView2 | `AIChatFeature.cpp:904-917` 调 `GetAvailableCoreWebView2BrowserVersionString` 并释放 `CoTaskMemFree`；`2763-2785` 调 `CreateCoreWebView2EnvironmentWithOptions` | **真实实现**，但 WebView2 loader 静态库和 Runtime 是两层依赖；当前没有把 Runtime 版本/位数结果上送统一依赖报告 |
| 显式动态加载 | `src/TimeManager.h:20-45` 用 `GetModuleHandle("kernel32.dll")` + `GetProcAddress("GetTickCount64")`；`src/WinINetUtil.cpp:60-83` 在错误格式化回退中 `LoadLibraryA("wininet.dll")` | **真实实现但非统一动态库支持库**。前者无独立签名/错误结果契约；后者若 `LoadLibraryA` 新增引用，当前路径没有对应 `FreeLibrary` |
| 主模块资源 | `ResourceTextLoader.cpp:12-19` 用 `GetModuleHandleExW(...UNCHANGED_REFCOUNT)` 找自身；`31-59` 使用 `FindResource/LoadResource/LockResource` | **真实实现**；借用模块句柄，不增加引用；资源数据由系统管理，未调用 `FreeResource`/`UnlockResource`，不应把它误报成缺失释放 |
| 私有宿主符号 | `EideInternalTextBridge.cpp:29-109,174-200` 保存 image base、RVA、签名和 `__thiscall/__cdecl/__stdcall` 函数指针；`559-600` 等从 `GetModuleHandleA(nullptr)` 得到宿主 EXE 基址；`MemFind.cpp:78-103` 扫描宿主完整映像 | **真实实现 + 版本敏感适配**，不是 DLL 导出符号解析。缺少通用 ABI manifest、版本/架构契约和统一失败对象 |
| 进程/管道 | `EPackagerIntegration.cpp:375-466`、`PowerShellToolRunner.cpp:152-296`、`HeadlessCompileRunner.cpp` 通过 `CreateProcessW` 管理外部 EXE | **真实实现**；部分调用有超时/取消，`EPackagerIntegration` 路径使用 `WaitForSingleObject(INFINITE)`，不是统一受管进程 |
| 网关 | `LocalMcpServer.cpp:1210-1246` 启动一个服务线程，`Shutdown` 设置停止标志、关闭监听 socket、移动线程并 `join` | **真实实现**；它是进程内协议网关，不是动态库 loader，也没有独立受管 provider 进程 |

### 11.3 唯一加载/解析链路（当前实现与底座目标分开）

当前源码可证实的唯一主链路应描述为：

```text
易语言 IDE 的 Windows loader
  → AutoLinker.fne 的 DllMain（只 DisableThreadLibraryCalls，不做业务初始化）
  → IDE 读取 GetNewInf() / LIB_INFOX
  → IDE 通过支持库 ABI 回调 AutoLinker_MessageNotify
  → NL_SYS_NOTIFY_FUNCTION 设置 g_notifySysReady
  → NL_IDE_READY 进入 FneInit
  → 获取 IDE 主窗口并安装窗口子类
  → 初始化 AIChatFeature / LocalMcpServer / 依赖目录刷新
  → 解析宿主 EXE 私有地址（image base + 固定 RVA/签名）
  → 安装 Detours Hook（成功才标记 installed）
  → IDE/MCP/AI 工具调用 IDEFacade、镜像、编译和依赖操作
```

证据是 `src/main.cpp:7-23`、`src/AutoLinker.cpp:454-492`、`355-451`。关键约束是：`DllMain` 不应被解释为 `FneInit`；当前业务初始化由 IDE 通知触发，若 `g_notifySysReady`、主窗口、子类化或后续私有地址缺失，`FneInit` 可返回失败或跳过 Hook。

动态依赖和宿主符号的子链路为：

```text
编译期 .lib / import
  → Windows loader 装入 AutoLinker.fne 的静态依赖
  → WebView2LoaderStatic.lib 的导出入口
  → WebView2 Runtime 版本探测
  → CreateCoreWebView2EnvironmentWithOptions
  → ICoreWebView2Environment → ICoreWebView2Controller → ICoreWebView2
```

```text
GetModuleHandle(NULL)
  → 当前宿主 e.exe image base
  → e571/e595 profile 的固定 RVA 或字节签名
  → MatchRvaSignature / ResolveUniqueCodeAddress
  → 带调用约定的函数指针
  → IDEFacade / EideInternalTextBridge / Detours 调用
```

```text
EPackagerIntegration / HeadlessCompileRunner / PowerShellToolRunner
  → CreatePipe + CreateProcessW
  → stdout/stderr 读取线程
  → 等待、退出码和诊断
  → CloseHandle + join
```

```text
LocalMcpServer
  → 127.0.0.1 连续端口 bind/listen
  → 服务线程读取 HTTP/JSON-RPC
  → tools/list 或 tools/call
  → AIChatFeature::ExecutePublicTool
  → 需要 IDE 状态时转主线程
```

**底座单链路裁决**：以后若把这类能力纳入系统工程平台，不应让每个模块各自 `LoadLibrary/GetProcAddress` 或各自解释 RVA。唯一落点应是“动态库支持库 → 运行核心 loader/ABI registry → 受管进程 provider → 网关”这一条链；项目适配层只提交库标识、版本、位数、符号签名、超时和所有权，不持有第二份解析逻辑。

### 11.4 ABI、符号解析、版本与位数的归属映射

| 能力 | AutoLinker 当前归属 | 通用底座归属 | 裁决 |
|---|---|---|---|
| 支持库正式 ABI | `src/AutoLinker.h` 的 `LIB_INFOX` 宏/声明、`GetNewInf`、`AutoLinker_MessageNotify`；`elib/` 提供私有头声明 | **动态库支持库**：导出表、调用约定、结构版本、所有权和错误码 | 吸收为“宿主 ABI 适配器”；`elib` 头文件只能算声明，必须有 PE 导出和宿主实跑证据才升格 |
| 系统 DLL 入口 | `TimeManager` 的 `GetModuleHandle/GetProcAddress`；WinINet 主要依靠静态 import | **动态库支持库**提供统一 `加载/取符号/卸载`；系统库也要走同一记录表 | 升级现有支持库，不在业务模块复制加载逻辑 |
| 私有 EXE 地址 | `EideInternalTextBridge` 的 image base/RVA/signature/typed pointer/Detours | **运行核心**的版本化符号解析器；项目适配层只提供 profile | 吸收模式，但当前硬编码 RVA 和 C++ 调用约定不可直接当通用 ABI |
| 版本/兼容 | `LIB_*` 固定宏；`AUTOLINKER_VERSION="0.0.0"`；`Version.cpp` 只做点分版本比较；私有适配有 e571/e595 profile | **动态库支持库 + 运行核心**：库版本、协议/ABI 版本、宿主版本、provider 版本、位数必须分别记录 | 待核/需升级；当前没有统一兼容矩阵，也没有运行时拒绝错误码 |
| 位数/架构 | Win32/x64 配置和 x86/x64 WebView2 `.lib`；`direct_global_search.cpp` 在 x64 配置被排除；若干函数指针为 x86 `__thiscall` | **运行核心**在加载前做 PE machine、进程位数、库位数、调用约定校验 | 这是 P0；当前只能证明配置分支存在，不能证明 x64 构建和跨位数拒绝 |
| 句柄/资源所有权 | 各模块各自持有 `HMODULE/HINTERNET/HGLOBAL/HANDLE/ComPtr` | **运行核心资源注册表/生命周期监督**；动态库支持库声明借用、转移、释放函数 | 需要收敛；当前只有局部 RAII/手工 close，无统一句柄清单 |
| 外部进程 | e-packager、`e.exe`、PowerShell 的 `CreateProcessW` 包装 | **受管进程**：进程组、stdin/stdout/stderr、截止时间、取消、崩溃、重启、残留验证 | 当前为局部实现；`EPackagerIntegration` 的无限等待是阻断级缺口 |
| MCP/本地 API | `LocalMcpServer` 同进程 socket/JSON-RPC | **统一网关**：认证/绑定、请求 id、deadline/cancel、背压、错误转换和证据 | 网关只调用运行核心公开能力，不直接解析动态库；当前网关无独立 loader 层 |

### 11.5 资源句柄与加载生命周期表

| 资源 | 创建/取得 | 持有与释放 | 正常/失败/取消/崩溃结论 |
|---|---|---|---|
| AutoLinker 自身 `HMODULE` | Windows loader；辅助函数用 `GetModuleHandleExW(...UNCHANGED_REFCOUNT)` | 借用句柄，不由辅助函数 `FreeLibrary`；进程/模块卸载由系统负责 | 正常路径清晰；DLL 崩溃或宿主强杀时不能依赖 `DllMain(DLL_PROCESS_DETACH)` 做完整业务清理，因为 `main.cpp:19-21` 为空 |
| `wininet.dll` `HMODULE` | `GetModuleHandleA`，为空时 `LoadLibraryA`（`WinINetUtil.cpp:60-73`） | `FormatSystemErrorMessage` 只 `LocalFree` `FormatMessage` 缓冲区（`80-82`），没有对新加载的 `HMODULE` 配对 `FreeLibrary` | 低频错误格式化分支存在引用计数泄漏风险；应由动态库支持库统一“是否新加载/是否释放” |
| WinINet `HINTERNET` | `InternetOpenA → InternetConnectA → HttpOpenRequestA` | POST 核心用 `cleanupAll` 和 `HttpRequestCancellation` 关闭 request/connection/internet（`183-240,252-390`）；GET 路径成功/失败显式 `InternetCloseHandle`（`454-536`） | POST 取消有真实句柄中断；GET 无 `HttpRequestCancellation` 参数，只有 WinINet 超时选项，取消闭环不足 |
| 资源 `HRSRC/HGLOBAL` | `FindResourceA → LoadResource → LockResource`（`ResourceTextLoader.cpp:31-59`） | 资源由模块映像管理，当前复制到 `std::string`，不手动释放 `HGLOBAL` | 这是正确的系统资源语义；失败返回空字符串，但没有结构化错误原因 |
| 剪贴板 `HGLOBAL` | `GlobalAlloc(GMEM_MOVEABLE) → GlobalLock`（`IDEFacade.cpp:365-406`） | `SetClipboardData` 成功后所有权转给系统，失败分支 `GlobalFree`；锁后 `GlobalUnlock` | 局部所有权实现较完整；跨模块传递时仍没有统一句柄类型/诊断 |
| WebView2 COM 对象 | Runtime 探测返回字符串；环境/控制器/WebView 由 `ComPtr` 持有（`AIChatFeature.cpp:225-227,904-917`） | `CoTaskMemFree(version)` 已实现；`ComPtr` 负责引用释放；窗口/异步 callback 销毁竞态需 Windows 实机验证 | 正常 RAII 证据存在；缺少统一 cancel/close 状态机和强制 callback 排空证据 |
| 子进程及管道 | `CreatePipe` + `CreateProcessW`（`EPackagerIntegration.cpp:375-432`、`PowerShellToolRunner.cpp:197-244`） | 写端先关闭；进程/线程/读端 `CloseHandle`，读线程 `join`（PowerShell `283-294`，EPackager `453-463`） | PowerShell 取消/超时调用 `TerminateProcess` 并最多等待 5 秒；未证明杀死子进程树。e-packager 使用 `INFINITE`，取消/超时不存在 |
| Detours Hook | `DetourAttach` 事务（`AutoLinkerHooks.cpp:620-691`、`EideInternalTextBridge.cpp:1626-1635`） | 当前源码中未找到与主 Hook 对称的 `DetourDetach`/卸载事务；仅 `direct_global_search.cpp:1719-1723` 有局部失败回滚 | 正常初始化后依赖宿主进程结束回收；插件卸载/IDE 重启/部分安装失败的 Hook 清理是重要风险 |
| MCP socket/线程 | `LocalMcpServer::Initialize` 建线程；监听 socket 在服务线程内创建 | `Shutdown` 设置停止、关闭监听 socket、`join`（`LocalMcpServer.cpp:1231-1246`） | 正常关闭有闭环；客户端断开、正在执行的 IDE 私有调用和宿主崩溃时的请求取消/句柄残留未统一证明 |
| 镜像/快照临时目录 | `WorkspaceMirror::RefreshMirror`、`EPackagerIntegration` 创建临时快照/解包目录 | `WorkspaceMirror::ResetAndCleanup` 调 `RemoveMirrorRootIfSafe`（`WorkspaceMirror.cpp:807-811`）；外部进程异常/强杀后须实机检查 | 正常窗口销毁有清理；DLL/IDE 崩溃可能遗留 `%TEMP%` 文件，当前无启动时残留扫描 |

### 11.6 失败、超时、取消、崩溃矩阵

| 阶段/场景 | 当前源码行为 | 资源与恢复 | 底座要求 / 当前等级 |
|---|---|---|---|
| Windows loader 找不到依赖 DLL、导入表不匹配或位数不符 | 失败发生在 `DllMain` 之前，当前源码没有机会返回统一错误；`.vcxproj` 只声明链接依赖 | 由 Windows 回滚模块加载；插件日志可能完全没有启动记录 | 动态库支持库必须先做 PE machine/import/ABI 预检并返回 `HOST_UNAVAILABLE`/`ABI_MISMATCH`；当前 L0-L1，未验证 |
| `DllMain` 进入/退出 | `DLL_PROCESS_ATTACH` 只 `DisableThreadLibraryCalls`；`DETACH` 空实现 | 不做业务资源释放；业务资源依赖 `FneInit` 后的窗口销毁路径 | 保持 DllMain 最小化，但运行核心必须有显式 `Start/Stop`；当前 L1 |
| `GetNewInf`/`LIB_INFOX` 不兼容 | 声明、静态结构和返回存在；没有宿主 ABI 版本探针或坏结构测试 | 宿主可能拒绝加载/忽略支持库，源码无结构化诊断 | 动态库支持库应固定 ABI 版本、结构大小、调用约定和错误码；当前 L0-L1 |
| `NL_SYS_NOTIFY_FUNCTION`/`NL_IDE_READY` 顺序错误 | `FneInit` 检查 `g_notifySysReady`，未就绪则记录并返回 false（`AutoLinker.cpp:366-370,476-489`） | 已安装资源若初始化到中途失败，没有统一回滚表；部分窗口/线程风险待核 | 运行核心需阶段事务和逆序回滚；当前 L1、未有故障注入 |
| 宿主 image base 无效、RVA 越界、签名不匹配/多匹配 | `EideInternalTextBridge` 返回 unsupported/trace；`MemFind::FindSelfModelMemoryUnique` 只唯一命中，否则 0；`FneInit` 缺地址时跳过对应 Hook（`AutoLinker.cpp:80-99`、`AutoLinkerHooks.cpp:647-651`） | 不调用未知地址是正确的安全分支；但已安装的其他 Hook 没有主路径卸载 | 运行核心需版本+位数+签名原子校验，失败不可部分激活；当前 L1 |
| 符号已解析但调用约定/结构布局错误 | 函数指针包含 `__thiscall/__cdecl/__stdcall` 声明，但没有运行时 ABI 校验；错误可能直接破坏栈/崩溃 | 进程级崩溃，DLL 无统一恢复 | 必须把调用约定、结构大小、所有权和版本作为签名契约；当前 L0-L1，P0 风险 |
| WebView2 Runtime 缺失/环境创建失败 | `IsWebView2RuntimeAvailable` 返回 false；异步创建失败记录 HRESULT 并回退/隐藏 WebView（源码 callback 路径） | `CoTaskMemFree`/`ComPtr` 的正常释放有证据；创建失败和窗口销毁竞态未全测 | provider 返回可区分的 `RUNTIME_UNAVAILABLE`/`CREATE_FAILED`，网关不能把它伪装成 AI 成功；当前 L1 |
| WinINet 连接/发送/读取失败 | 返回错误文本和状态码；POST 逐阶段关闭句柄，GET 各失败分支关闭句柄 | POST 支持取消；GET 仅超时选项；重试策略由上层而非统一 loader 管 | 运行核心/网关应统一 deadline、cancel、可重试；当前 L1 |
| WinINet 超时 | POST 设置 connect/send/receive timeout；GET 同样设置；超时错误来自 WinINet | 句柄最终关闭；没有统一超时错误码/证据链 | 需把 timeout 与 cancellation 分开记录；当前 L1 |
| AI/POST 主动取消或客户端断开 | `HttpRequestCancellation::Cancel` 关闭已登记三类句柄；发送前和读取循环多次检查（`WinINetUtil.cpp:132-179,252-390`） | 取消返回 HTTP 499 文本语义；MCP 同步请求是否能把断开传播到 AI 取消未证实 | 网关必须把 request id → cancellation token 传到运行核心；当前 POST L1，网关传播 L0 |
| e-packager 启动失败/退出非零 | `CreateProcessW`/管道错误返回 `ProcessRunResult`；等待使用 `INFINITE`（`EPackagerIntegration.cpp:375-466`） | 句柄和读线程正常收口；卡死时宿主线程可能永久等待 | 受管进程必须有 startup/deadline/cancel/进程组终止；当前 L1 但超时为阻断缺口 |
| PowerShell 启动失败/超时/取消 | 启动失败关闭管道；取消退出码 125，超时 124，其他等待错误 126；`TerminateProcess` 后等待 5 秒（`PowerShellToolRunner.cpp:249-295`） | 进程、线程、管道关闭并 join；未建立子进程树清理或残留验证 | 受管进程应使用独立进程组并验证树消失；当前 L1，清理不完整 |
| Detours 事务提交失败 | 记录 `hook transaction failed`，但主路径没有统一 `DetourTransactionAbort`/逆序卸载 | 已 attach 部分是否回滚取决于 Detours 事务语义，源码没有逐项验证 | 运行核心必须“全部激活或全部回滚”，并有 Hook registry；当前 L1/待核 |
| MCP 网关停止/监听端口失败 | 初始化在线程中尝试端口；关闭设置停止标志、关 socket、join | 正常 Stop 资源闭环；端口占用/线程阻塞/请求执行中 Stop 需实机 | 网关只负责协议和取消，不拥有动态库句柄；当前 L1 |
| 插件/IDE 崩溃、`TerminateProcess` 或宿主强杀 | `DllMain(DLL_PROCESS_DETACH)` 为空，无法保证窗口子类、Detours、线程、临时目录、WebView2 callback、MCP socket 逐项释放 | OS 回收进程句柄和映像；文件/外部子进程/临时目录可能残留 | 启动时残留审计 + 受管进程组 + 可恢复状态；当前仅 L0-L1，未做崩溃注入 |

### 11.7 依赖检测、错误处理与测试入口的真实边界

1. `DependencyCatalogCache` 的职责是索引 `ecom/*.ec`、`lib/*.fne` 和文本内容（`src/DependencyCatalogCache.cpp:227-230` 等），不是检查 PE import、DLL 位数、导出符号或 ABI 兼容；不能把“能搜到 `.fne` 文件”当成“可加载”。
2. `AutoLinker_MessageNotify` 对 `NL_GET_DEPENDENT_LIBS` 在 `src/AutoLinker.cpp:466-468` 返回 `NULL`；这表明当前支持库没有在该入口提供可验证的依赖清单。`#pragma comment(lib, ...)` 和 `.vcxproj` 的库名只是链接输入，不能代替运行时依赖探测。
3. 当前已有的动态库探测很少：`TimeManager` 只解析 `GetTickCount64`，WebView2 只探测 Runtime API，WinINet 只在格式化错误时回退加载 `wininet.dll`。未发现统一的 `LoadLibraryEx` 搜索策略、`GetProcAddress` 签名登记、`FreeLibrary` 配对、PE machine 检查、导出表校验或依赖图报告。
4. 现有错误形状以 `bool`、空字符串、`std::pair<string,int>`、日志和 HRESULT 为主，尚未形成跨动态库/进程/网关的稳定错误码、可重试字段、资源清单和证据 id。底座接入时必须在支持库边界一次转换，禁止各调用方自行翻译。
5. `AutoLinkerTest/AutoLinkerTest.cpp:1556-1648` 的 `main` 提供无参数 smoke、版本比较、链接命令字符串、GameAnalytics、模型集成和 `headless-compile` 命令；`src/AutoLinkerTestApi.h:15-81` 是脱离 IDE 的 C ABI 测试导出声明。当前没有专门的 `LoadLibrary/GetProcAddress/FreeLibrary`、缺库、坏 ABI、Win32/x64、Hook 回滚或 DLL 卸载测试入口。
6. `AGENTS.md:31-58` 要求 Windows/VS 构建后把 `.fne` 覆盖到易语言 `lib` 并打开 `test_a.e`；这属于宿主集成验收说明，不是本轮已执行证据。当前 macOS 环境不能运行 MSBuild、易语言 IDE、WebView2 Runtime、`.fne` loader 或 Windows 进程清理测试。

### 11.8 通用底座装配计划与裁决

| 底座对象 | 唯一 owner | 输入契约 | 必须产出的证据 | 本项目映射裁决 |
|---|---|---|---|---|
| 动态库支持库 | `动态库支持库` | 路径/系统库名、搜索策略、SHA/签名（如适用）、目标架构、ABI 版本、导出符号和签名 | 加载句柄、真实文件、machine、符号地址、引用计数、释放结果 | AutoLinker 的 `GetNewInf`/WinINet/WebView2 入口吸收；禁止复制到各业务模块 |
| 运行核心 | `运行核心 loader + ABI registry + 资源监督` | `LibrarySpec`、`SymbolSpec`、版本/位数约束、deadline/cancel、所有权 | 单一解析链、兼容判定、错误码、句柄状态、逆序释放、崩溃后残留报告 | `EideInternalTextBridge` 的 RVA/profile/signature 作为项目适配器输入；硬编码解析器本身不直接复用 |
| 受管进程 | `受管进程 supervisor` | exe、参数、cwd、环境、进程组、startup/deadline/cancel、输出上限 | pid/子树、退出码/信号、stdout/stderr、终止和残留验证 | `EPackagerIntegration`、`HeadlessCompileRunner`、`PowerShellToolRunner` 归入；先补 e-packager 无限等待 |
| 统一网关 | `LocalMcpServer/统一网关` | request id、能力 id、参数、身份、deadline、取消令牌 | JSON-RPC 响应、稳定错误、请求状态、断开取消、审计日志 | 当前 `LocalMcpServer` 只做进程内协议入口；必须调用运行核心公开能力，不直连 `LoadLibrary`/RVA |
| 项目适配层 | AutoLinker 专属适配 | e571/e595 profile、`LIB_INFOX` 版本、私有结构布局、支持库能力映射 | 版本探测、兼容/不兼容原因、可回退能力 | 吸收；不能把 AutoLinker 的宿主地址当成通用核心常量 |

目标单链应冻结为：

```text
LocalMcpServer/其他入口
  → 统一网关能力契约（请求、权限、deadline、cancel）
  → 运行核心唯一调用器
  → 动态库支持库（加载/ABI/符号/版本/位数/句柄）或受管进程 supervisor
  → AutoLinker 项目适配器（LIB_INFOX、e571/e595 RVA/signature、WebView2/WinINet）
  → IDE/系统 DLL/WebView2 Runtime/e-packager/e.exe
  → 统一结果、错误、释放、残留证据
```

不得形成以下侧链：MCP 工具直接 `GetProcAddress`、AI 模块直接加载 DLL、各 IDE 版本各维护一套 `GetModuleHandle(NULL)+RVA`、每个子进程调用者各自 `TerminateProcess`、或把 `DependencyCatalogCache` 的文件搜索当作可加载性证明。

### 11.9 吸收/废弃/待核清单

- **吸收**：`DllMain` 最小入口、`GetNewInf → LIB_INFOX` 官方 ABI 边界、WebView2 Runtime 探测、POST WinINet 取消句柄链、PowerShell 句柄收口、MCP `Shutdown` 的 socket/thread join、宿主私有地址解析的“版本 profile + 签名校验后再调用”原则。
- **升级**：`TimeManager` 的散落符号解析、WinINet 的错误回退加载、`EideInternalTextBridge` 的 RVA/函数指针表、各处手工 `HANDLE/HINTERNET` 生命周期，统一迁入动态库支持库/运行核心/受管进程边界。
- **待核**：x64 `fne_release` 实际产物、PE import/export 与 machine、易语言 IDE 对 `LIB_INFOX` 的真实兼容矩阵、WebView2 COM callback 在窗口销毁时的排空、Detours 主 Hook 的卸载、e-packager 卡死/子进程树残留、MCP 客户端断开到 AI/WinINet cancel 的传播。
- **废弃/禁止复用**：把 `LoadLibraryA`、`GetProcAddress`、固定 RVA、`TerminateProcess` 或 `DependencyCatalogCache` 搜索逻辑散落复制到新的模块/网关；把 README/技能中宣称的网关线程池、会话协商、503 和多实例能力当作当前 loader/运行核心证据。

### 11.10 本轮安全验证记录

本轮只执行了本地静态读取、路径检索和 Git 状态检查；没有创建或修改源码/依赖/配置/测试，也没有启动服务、IDE 或构建。现场命令及结果：

```text
git status --short -- ARCHITECTURE.md
→ ?? ARCHITECTURE.md（该根架构文档本来就是未跟踪文件；本轮仅继续修改它）

git rev-parse --show-toplevel
→ ~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/AutoLinker

git rev-parse HEAD
→ b3a1358a1ca80f201c14327cd082c65914c9a7e0

git ls-files '*细探*.md' '*ARCHITECTURE*.md'
→ 无输出（旧细探和架构文档均未纳入 Git 索引；磁盘上的 ARCHITECTURE.md 是本项目唯一架构文件）
```

以上命令退出码均为 `0`。本机为 macOS，以下命令本轮**未执行**，不能声称通过：

```powershell
MSBuild.exe ..\AutoLinker.vcxproj /t:Build "/p:Configuration=fne_release;Platform=Win32" /m
MSBuild.exe AutoLinkerTest\AutoLinkerTest.vcxproj /t:Build "/p:Configuration=fne_release;Platform=Win32" /m
.\bin\fne_release\AutoLinkerTest.exe
```

本轮唯一修改文件仍是目标根 `ARCHITECTURE.md`；未删除旧细探（目标目录现场未发现旧细探）。下一轮若要把 L1 提升到 L2-L4，必须在 Windows 环境实际生成并检查 Win32/x64 `.fne`、用 `dumpbin /headers /exports /dependents` 或等价工具核验 PE/导出/依赖，再以易语言 5.95/5.71 宿主完成加载、卸载、缺依赖、取消、超时、崩溃和残留验证。
