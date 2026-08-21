# eide（易IDE视觉库）架构文档

> 本文档是本项目根目录唯一的架构归档。结论来自当前工作树源码、项目文档、工程文件与远程版本查询；源码符号、路径、导出名和协议名保留原文。

## 1. 项目定位

`eide` 是面向 Windows 易语言 IDE 的 C++ 原生视觉支持库及插件生态，项目对易语言 IDE 的窗口、菜单、工具条、代码区、组件箱、选择夹、状态夹和资源进行重绘或扩展。核心交付不是独立应用，而是易语言 `Lib` 目录可加载的 `iDraw.fne` 与配套 DLL、插件 DLL、配色/资源文件和 `setup.exe`。

主要目标：

- 通过窗口子类化、Win32 消息处理、Hook、D2D/GDI 绘画和资源加载改善 IDE 视觉效果；
- 通过 `IDRAW_INFO`、`PLUGIN_INFO`、`IDraw_Interface` 和导出函数为插件提供扩展边界；
- 保持易语言 IDE 原有功能，支持易语言 5.8+、Windows 7/10（README 口径）；
- 以 Win32/x86 为主要发布目标，同时工程保留 x64 配置。

README 宣称项目“免侵入、不编译代码到用户程序”，但实现层实际使用 DLL 加载、窗口子类化、线程消息、`SetWindowsHookExW`、InlineHook 和易语言 IDE 内部窗口结构；因此这里的“免侵入”应理解为不修改用户业务源码，而不是进程内完全无 Hook。

## 2. 总体流程

```text
易语言启动并加载 Lib/iDraw.fne
        │
        ├─ iDraw.fne 导出 IDraw_Interface
        │      ├─ 接收 IDRAW_INFO / IGetEWindow
        │      ├─ 初始化核心绘画对象、主题与插件管理
        │      ├─ 注册 ShowWindow/CreateDialog 等 Hook
        │      ├─ 子类化 IDE 窗口并分发 Win32 消息
        │      └─ 暴露 iDraw_* API 与 IDC_* 内部功能号
        │
        ├─ 加载 iDraw\iControls.dll
        │      └─ 控件、菜单、窗口边框、滚动条和 MDI/选择夹绘画
        ├─ 加载 iDraw\iResource.dll
        │      └─ .eil/.xml/图片/压缩资源解析与图标加载
        ├─ 加载 iDraw\iEvent.dll
        │      └─ 按 HWND + message/event + 插件 GUID 管理回调
        ├─ 加载 iDraw\iConfig.dll / iTheme.dll / iWindowSize.dll
        │      └─ 配置、主题和窗口布局/尺寸相关能力
        └─ 加载 plugin\iDraw_Background.dll、iDraw_LineCode.dll
               └─ 通过公开 iDraw.h API 注册事件、菜单、绘画与 Hook

构建：MSBuild iDraw.sln → build\\<Configuration>\\Win32\\lib
发布：scripts/package-release.ps1 + dist 素材 → 主包 zip / 插件开发资料 zip
安装：setup.exe 校验 lib/clr/Tools → 复制到用户指定易语言根目录
```

## 3. 真实目录地图

```text
eide/
├── iDraw.sln                         主解决方案
├── Directory.Build.props             统一 MSBuild 输出与 GBK 编码
├── src/
│   ├── include/                      公共头文件、结构、常量、版本和导出契约
│   ├── CommonCode/                   d2d、hook、控件、zlib、tinyxml2 等共享实现
│   ├── iDraw/                        核心支持库，输出 iDraw.fne
│   ├── iDrawControl/                 控件与 IDE 窗口绘画，输出 iControls.dll
│   ├── IDraw_Resource/               资源与图片，输出 iResource.dll
│   ├── iDraw_Event/                  消息/事件回调，输出 iEvent.dll
│   ├── iConfig/                      配置 DLL 工程，输出名 iConfig
│   ├── iTheme/                       主题 DLL 工程，输出 iTheme.dll
│   ├── EWindowSize/                  窗口尺寸/布局，输出 iWindowSize.dll
│   ├── iDraw_Config/                 独立配置解决方案，工程目标名也为 iConfig
│   └── insert/                       安装器 setup.exe
├── tools/                            ImageListView、ImageExt、ExtView、易语言工具
├── tests/                            MFC/窗口调试和试验工程，不是自动化测试框架
├── plugins/                          背景插件、行号插件、易语言助手插件
├── assets/                           主题图片、工具条、图标等静态素材
├── dist/                             发布模板、配色、接口模块、插件源码/示例
├── docs/                             项目结构说明及组件资料
├── scripts/                          package-release.ps1 等发布辅助脚本
└── build/                            本地构建输出，按文档约定应为可删除/非源码目录
```

现场统计（排除 `.git`）：约 1,831 个文件；`src` 1,137 个、`assets` 458 个、`tests` 75 个、`plugins` 33 个、`tools` 38 个、`dist` 80 个。主要源码为 171 个 `.cpp`、215 个 `.h`、20 个 `.c`，工程为 20 个 `.vcxproj` 和 9 个 `.sln`；大量 `.png/.xml/.eil/.ires/.bin` 属于主题和易语言资源资产。

## 4. 分层与模块职责

### 4.1 公共契约层：`src/include/`

- `IDraw_Header.h`：`IDRAW_INFO`、`PLUGIN_INFO`、`ETOOLS_PLUGIN_INFO`、`EVENT_CALLBACK_FUN`、`THEME_D2D_INFO`、函数指针类型、插件信息和资源/事件接口。
- `iDraw_const.h`：`MDICLIENT_TYPE`、`MDICLIENT_CODETYPE`、事件结构、`IGI_*` 信息键、`IRE_*` 事件键、`IDC_*` 功能号区间和具体调用号。
- `iDraw_Virtual.h`：`ID2DDraw`、绘画资源、画布、字体、画笔、图片、窗口数据和回调相关抽象。
- `iDraw_Interface.def`：插件类 DLL 的 `IDraw_Interface`/`IDraw_UnInterface` 导出契约。
- `iDraw_Version.h`：`IDRAW_MAJORVERSION=1`、`IDRAW_MINORVERSION=5`、`IDRAW_BUILDVERSION=1003`，派生出 `IDRAW_VERSION`/`IDRAW_VERSIONA`。
- `iDraw.h`：插件开发者使用的 C 接口头文件；发布 SDK 由打包脚本复制。

### 4.2 核心支持库：`src/iDraw/`

`iDraw_Interface.cpp` 是对外 API 的主要实现，`iDraw_Interface_Plugin.cpp` 管理插件枚举/查询，`iDraw_Interface_Info.cpp` 读取和设置 `IGI_*` 信息，`iDraw_PluginFunction.cpp` 将插件通知功能号转发到核心模块。核心 DLL 通过 `iDraw.def` 导出以下几类能力：

- 生命周期/版本：`IDraw_Interface`、`IDraw_UnInterface`、`iDraw_GetVersion`、`iDraw_GetVersionA`、`iDraw_GetEVersion`；
- 内存与窗口：`iDraw_malloc`、`iDraw_free`、`iDraw_SubclassWindow`、`iDraw_DrawWindow`、`iDraw_CreateWindow`、`iDraw_DrawWindowProc`、`iDraw_GetWindowData`；
- 控件重绘：`iDraw_Subclass_Button`、`iDraw_Subclass_Edit`、`iDraw_Subclass_TreeView`、`iDraw_Subclass_ListView`、`iDraw_Subclass_Tool`、`iDraw_Subclass_Tab`、`iDraw_Subclass_ComboBox` 等；
- 菜单/系统按钮/工具条：`iDraw_MenuInsert`、`iDraw_MenuRemove`、`iDraw_MenuExt_Insert`、`iDraw_AddSysButton`、`iDraw_Tool_InsertButton` 等；
- IDE 交互：`iDraw_EIDE_Notify`、`iDraw_EIDE_RunFunctions`、`iDraw_GetCodeManage`、`iDraw_GetCodeWindow`、`iDraw_GetMDIClientType`；
- 事件：`iDraw_Event_RegisterMessage`、`iDraw_Event_RegisterEvent`、`iDraw_UnRegister_Message`、`iDraw_UnRegister_Event`；
- Hook：`iDraw_InlineHook`、`iDraw_UnInlineHook`，内部支持 `detoursHook` 和 `MinHook` 两种模式；
- D2D/GDI 绘画：`iDraw_canvas_*`、`iDraw_brush_*`、`iDraw_pen_*`、`iDraw_path_*`、`iDraw_img_*`、`iDraw_font_*`；
- 资源：`iDraw_LoadExtFromFile`、`iDraw_LoadExtFromMemory`、`iDraw_BindWindow`、`iDraw_GetIcon`、`iDraw_GetImageHandle`。

源码中 `iDraw_Xml_SetAttrValue`、`iDraw_Xml_GetAttrValue`、`iDraw_Xml_SetNodeValue`、`iDraw_Xml_SaveFile` 等函数当前可见实现直接 `return 0`，原有真实调用被注释；这些导出应视为兼容占位或未完成能力，不能在架构层宣称 XML API 已完整可用。

### 4.3 控件与 IDE 窗口层：`src/iDrawControl/`

`EControls_main.cpp` 负责控件插件入口及核心 `IDraw_NotifyCallback`，`EWindow_EIDE.cpp` 处理 IDE 代码窗口/内部窗口交互，`EWindow_Fne_SetWindowsHook.cpp` 使用 `SetWindowsHookExW(WH_GETMESSAGE/WH_CBT)` 观察线程消息和窗口创建、激活、销毁、鼠标/键盘事件。`WndProc_cpp/` 按控件类型拆分窗口过程，包括 `WndProc_Button`、`WndProc_Edit`、`WndProc_ListView`、`WndProc_Menu`、`WndProc_TreeView`、`WndProc_ToolBar` 等。

控件层通过 `s_info->pfnControls(IDC_*, wParam, lParam)` 与核心/其他插件通信；窗口状态通过 `LPOBJSTRUCT`、`DRAW_WINDOW_ARGUMENT`、`RECT`、`LPCANVAS` 等结构传递。菜单和工具条属于功能号分区 `IDC_ICONTROL_*`，而核心功能位于 `IDC_IDRAW_*`。

### 4.4 主题、配置、资源与尺寸层

- `src/iTheme/`：`iTheme_Main.cpp` 以插件形式注册“核心主题插件”，通过 `THEME_D2D_INFO` 和 `IThemeColor` 管理主题色、D2D 对象和配置变更。
- `src/iConfig/`、`src/iDraw_Config/`：使用 `tinyxml2` 相关共享代码读写/转换配置；两个工程都出现目标名 `iConfig`，应在后续 Windows 构建中确认其是否为历史并存工程或目标冲突。
- `src/IDraw_Resource/`：`tinyxml2`、zlib 与 `ThemeResource*` 组合，服务 `.eil/.xml` 资源、图片和图标加载；输出 `iResource.dll`。
- `src/EWindowSize/`：使用 Detours 相关代码处理 `EWindow_Size_*`、菜单、工作夹、状态夹、MDIClient 等尺寸/布局行为。
- `assets/theme/` 与 `src/iDraw/data/`：主题图片、工具条、树控件图标、易语言资源目录及 `.eil/.xml` 配对数据，是运行时资源输入，不是 C++ 数据模型。

### 4.5 插件层：`plugins/`

插件以 `IDraw_Interface(IDRAW_INFO*, IGetEWindow*, int, int)` 接入，并在返回的 `PLUGIN_INFO` 中提供 `guid`、名称、版本、依赖、菜单回调和通知回调。

- `易IDE视觉库_背景插件`：通过 `iDraw_Event_RegisterEvent` 订阅背景绘画、代码选择夹切换和 MDI 尺寸事件；利用 `IGI_MDICLIENTTYPE`、`IGI_RCMDICLIENT`、`iDraw_GetCodeVisibleRect` 和 `ID2DDraw` 将图片绘制到 MDI 代码区背景。
- `易IDE视觉库_行号插件`：使用 `CLineCodeConfig`、`CPrivateProfile` 和 `SetWindowsHook/InlineHook` 相关接口读取配置、追踪光标/代码窗口、创建分层窗口并绘制当前行号线；根据 `IGI_DPI` 做缩放。
- `易语言助手插件`：以易语言 `.e/.ec/.eil` 资料为主，需在 Windows 易语言环境中进一步核对其与核心 `IDC_ICONTROL_*` 功能号的调用关系。

### 4.6 安装与发布层

`src/insert/setup.cpp` 是 Win32 GUI 安装器：启动时加载自身目录 `lib\iDraw.fne`，通过 `GetProcAddress("GetNewInf")` 取得版本信息；验证目标目录存在 `krnln.fne` 且可由 `LoadLibraryExW(..., DONT_RESOLVE_DLL_REFERENCES)` 加载；递归枚举自身目录下的 `lib`、`clr`、`Tools`，逐文件调用 `cmpmd5` 比对并复制，最后由用户点击安装。目标目录不符合易语言根目录约束时拒绝安装。

`scripts/package-release.ps1` 负责：

1. 检查 `build\<Configuration>\Win32\lib\iDraw.fne`；
2. 从 `iDraw_Version.h` 读取版本，或接受 `-Version`；
3. 组装主包和 SDK 包暂存目录；
4. 主包收集 `iDraw.fne`、6 个 DLL、2 个插件 DLL、`setup.exe`、`clr` 和运行时资料；
5. SDK 包收集插件源码、测试代码、设置程序源码和 `iDraw.h/iDraw_const.h`；
6. 清除 `.pdb/.lib/.exp/.ilk/.obj/.tlog` 与调试目录；
7. 校验必要文件后生成两个 zip，并写入 GitHub Actions 的 `GITHUB_OUTPUT`。

## 5. 核心数据模型与状态

本项目没有数据库或服务端持久化；状态主要是进程内结构、Windows 窗口属性、INI/XML 文件和资源文件。

| 模型/状态 | 作用 | 证据 |
|---|---|---|
| `IDRAW_INFO` | 核心上下文：易语言主窗口句柄、版本、路径、插件信息、主题/配置/事件/控件回调和日志函数 | `src/include/IDraw_Header.h` |
| `PLUGIN_INFO` / `ETOOLS_PLUGIN_INFO` | 插件身份、GUID、版本、作者、依赖、菜单和 `pfnCallback` | `src/include/IDraw_Header.h` |
| `EVENT_CALLBACK_FUN` | 事件插件注入 `pfnRegister_Message`、`pfnRegister_Event`、查询和取消注册函数 | `src/include/IDraw_Header.h` |
| `LPOBJSTRUCT` | 窗口子类化后保存的窗口绘画/回调/状态数据，通过 HWND 查询 | `src/include/IDraw_Header.h`、`iDraw_Interface.cpp` |
| `MAP_MESSAGE` / `MAP_MODULE` | `iDraw_Event` 按 HWND → message → 插件 hash 保存消息回调 | `src/iDraw_Event/iDraw_Event_Main.cpp` |
| `MAP_MODULE_EVT` | 按 event → 插件 hash 保存事件回调 | `src/iDraw_Event/iDraw_Event_Main.cpp` |
| `SCROLL_CALLBACK` / `INLINEHOOK_CALLBACK` | 通过 `SetPropW` 绑定到易语言主窗口，供插件释放时清理 | `src/include/IDraw_Header.h` |
| `THEME_D2D_INFO` / `IThemeColor` | 主题颜色、D2D 资源和默认绘画对象 | `src/include/IDraw_Header.h`、`src/iDraw_Interface_Info.cpp` |
| `CLineCodeConfig` | 行号插件的开关、颜色、线宽、点划线和绘制状态 | `plugins/易IDE视觉库_行号插件/lineCode_main.cpp` |
| 背景插件配置 | `enabled`、`index`、`path` 三个键控制背景开关、图片索引、图片目录 | `plugins/易IDE视觉库_背景插件/dllmain.cpp` |
| 发布包暂存目录 | `build/package-stage/易IDE视觉库_vX.Y.Z` 和 SDK 目录 | `scripts/package-release.ps1` |

## 6. 真实调用链

### 6.1 支持库加载与核心初始化

```text
易语言加载 iDraw.fne
  → IDraw_Interface(IDRAW_INFO*, IGetEWindow*, ...)
  → 保存全局 s_info / eWnd
  → 初始化 D2D/主题/资源/控件相关回调
  → 注册 iDraw 核心插件信息与 GUID
  → _idc_InlineHook(ShowWindow / ShowWindowAsync / CreateDialogIndirectParamA)
  → _hook_CreateWindowEx()
  → MDIClientCode_Hook()
  → 子类化菜单、工具条、树、编辑框、代码区等窗口
  → Win32 消息进入 WndProc_* / HookProc_Message / HookProc_Cbt
  → iDrawControl 绘画、布局、消息转发或调用原窗口过程
```

`IDraw_UnInterface()` 释放 Hook、插件回调和资源。`EWindow_Fne_SetWindowsHook.cpp` 的 `IDraw_windowshook_Destroy` 明确调用 `UnhookWindowsHookEx`；核心层还通过 `IDraw_PushPluginFreeCallback` 记录插件释放清理动作。

### 6.2 插件注册与事件分发

```text
插件 DLL 加载
  → 插件 IDraw_Interface(info, eWnd, ...)
  → 填充 PLUGIN_INFO（guid/name/version/dependence/pfnCallback）
  → 核心调用 iDraw_InitPlugin 或插件调用公开 API
  → iDraw_Event_RegisterMessage / iDraw_Event_RegisterEvent
  → iDraw_Event 建立 HWND/message/event/GUID 哈希表
  → Win32 消息或内部 IRE_* 事件到达
  → _event_before / _event_after 遍历回调
  → 回调返回拦截值，决定是否继续传播
  → 插件卸载 → iDraw_UnRegister_Message/Event + Hook/窗口资源清理
```

同一消息/事件最多支持 `EVENT_MAX_ITEM=128` 个回调；回调函数签名和调用约定由头文件固定，源码注释警告参数数量或调用约定不匹配会导致堆栈不平衡和崩溃。

### 6.3 背景插件调用链

```text
iDraw_Event_RegisterEvent(..., IRE_SIZE_TABMDICLIENT / 绘画事件)
  → Event_MDIClientSize 更新 MDI 第三层窗口矩形
  → Event_CodeTabChang 调用 iDraw_UpdateShadow
  → Event_BeforeDraw 查询 IGI_MDICLIENTTYPE
  → 排除设计器/起始页
  → g_showImage.GetSize + DPI/窗口尺寸缩放
  → iDraw_GetCodeVisibleRect 获取裁剪区域
  → ID2DDraw::_canvas_setClip / _canvas_drawimagerectrect
  → 返回 1 拦截默认绘画
```

### 6.4 安装调用链

```text
setup.exe
  → LoadLibraryW(自身目录/lib/iDraw.fne)
  → GetProcAddress("GetNewInf")
  → 显示支持库版本
  → 用户选择目录
  → isEPath 检查 krnln.fne 并尝试加载
  → _enum_files 只枚举 lib/clr/Tools
  → cmpmd5 源/目标逐文件比对
  → g_isInsert=true 时复制文件
  → 用户点击安装完成
```

## 7. API、插件和协议边界

### 7.1 DLL 导出边界

- 核心支持库：`src/iDraw/iDraw.def` 中列出的 `iDraw_*`，对易语言支持库与 C/C++ 插件提供 ABI；
- 插件模块：`src/include/iDraw_Interface.def` 的 `IDraw_Interface`/`IDraw_UnInterface`；
- 安装器动态检查：`setup.cpp` 依赖 `GetNewInf`，这是安装器与 `iDraw.fne` 的隐式边界；
- 资源/主题/事件/尺寸 DLL 通过各自 `IDraw_Interface` 接入核心，不提供 HTTP/CLI/API Server。

### 7.2 功能号协议

跨 DLL 调用大量使用 `int nCode, WPARAM wParam, LPARAM lParam`：

- `IDC_IDRAW_BEGIN..END`：核心支持库能力；
- `IDC_ICONTROL_BEGIN..END`：绘画控件、菜单、工具条；
- `IDC_IRESOURCE_BEGIN..END`：资源能力；
- `IDC_IEVENT_BEGIN..END`：事件能力；
- `IDC_ICONFIG_BEGIN..END`、`IDC_ITHEME_BEGIN..END`、`IDC_IMOVE_BEGIN..END`、`IDC_IETOOLS_BEGIN..END`：配置、主题、窗口移动、助手。

`wParam/lParam` 常携带结构体指针或回调指针，属于不安全的原生 ABI；调用方必须使用同一版本的 `iDraw.h`、结构体大小字段（例如 `DRAW_WINDOW_ARGUMENT.cbSize`）和调用约定。

### 7.3 文件/配置边界

- 运行时安装布局：`lib\iDraw.fne`、`lib\iDraw\*.dll`、`lib\iDraw\plugin\*.dll`、`clr\`、`Tools\`；
- 主题/资源：`assets/theme/`、`src/iDraw/data/` 中的 `.png/.bmp/.eil/.xml/.ires`；
- 插件配置：背景插件使用 `enabled/index/path`，行号插件使用 `CPrivateProfile`；
- 路径查询由 `IGI_LIBPATH`、`IGI_DATAPATH`、`IGI_PATH_PLUGIN`、`IGI_PATH_CONFIG` 等键向插件提供；
- 发布脚本与安装器均只操作 Windows 路径和反斜杠布局。

## 8. 技术栈与依赖边界

| 范围 | 真实依赖 |
|---|---|
| 语言/构建 | C/C++、MSBuild、Visual Studio 2022 `v143`、Windows SDK 10.0 |
| Windows 平台 | Win32、User32、GDI/GDI+、D2D 封装、Shell/Commdlg、MFC（部分工具/测试） |
| 内置/随源码 | `src/CommonCode/d2d`、`hook`、`hook_detours/detours`、`MinHook` 头/实现、`zlib`、`xml2/tinyxml2` |
| 外部/工具链 | Visual Studio C++ Desktop、MFC；部分工程 `<VcpkgEnabled>true</VcpkgEnabled>`，仓库未发现 `vcpkg.json` 或 CMake 配置 |
| 编码 | 绝大多数历史源码为无 BOM GBK；`Directory.Build.props` 固定 `/source-charset:.936` 与 `/execution-charset:.936` |
| 目标平台 | 发布 CI `windows-2022`、`Release|Win32`；工程也列出 x64/Debug/testdll/调试Release 配置 |

第三方依赖边界主要集中于 `CommonCode` 与各模块工程的静态编译/头文件引用；没有 Python、Node、PHP、数据库或网络服务依赖。项目不是 HTTP/CLI 服务，也没有运行时远程数据模型。

## 9. 构建、发布与部署

### 构建

```cmd
msbuild iDraw.sln -m -p:Configuration=Release -p:Platform=Win32
```

`Directory.Build.props` 将输出统一到 `build\<Configuration>\<Platform>\`，中间文件到 `build\obj\<项目>\<Configuration>\<Platform>\`。Release 类配置通过 `PostBuildEvent` 把核心 DLL 复制到 `dist\lib\`。两个插件虽然在主解决方案中列出，但文档明确提示必要时可单独编译其 `.vcxproj`。

### 发布

```cmd
# 版本号来自 src\include\iDraw_Version.h，也可以 -Version 显式覆盖
powershell -ExecutionPolicy Bypass -File scripts\package-release.ps1 -Configuration Release
```

主包面向普通用户，SDK 包面向插件开发者。打包脚本在压缩前删除调试/中间文件并校验 `setup.exe`、`iDraw.fne`、6 个运行 DLL及两个插件 DLL。GitHub Actions 的 `.github/workflows/release.yml` 在 `v*` 标签或 `workflow_dispatch` 时执行 `windows-2022` + MSBuild + 字符集警告检查 + 打包；带 `v*` 标签时创建 Release。

### 部署

将主包解压后运行 `setup.exe`，选择含 `krnln.fne` 的易语言安装目录；安装器仅比较和复制 `lib`、`clr`、`Tools` 三个目录。首次启用后需在易语言“工具 → 支持库配置”启用并重启 IDE。卸载需取消勾选并删除 `iDraw.fne`、`iDraw\` 和相关 DLL。

## 10. 测试与验证结构

仓库没有发现 Python/CTest/GoogleTest/Catch2 或统一自动化测试入口；`tests/` 是 Visual Studio/MFC 试验工程和调试素材：

- `tests/MFCApplication1/`：MFC 停靠界面试验；
- `tests/测试浮动-停靠窗口/`：独立 `.sln` 的浮动/停靠窗口测试工程；
- `tests/调试火花编辑框/`：`SciLexer.dll`、`KWmusic.py` 和图片等调试资源。

已确认的验证能力：

- 编译层：Windows + MSBuild 能验证工程引用、链接和导出；
- CI 层：字符集警告 `C4566/C4819` 检查、发布包必需文件检查；
- 安装层：`setup.exe` 对 `krnln.fne`、`GetNewInf`、MD5 和路径进行真实检查；
- 运行层：需在安装易语言的 Windows 主机中验证窗口 Hook、DPI、菜单、主题、插件生命周期和不同易语言版本。

本轮未在 macOS 上启动、安装、构建或运行 Windows 工程；因此不能宣称编译通过、插件运行通过或安装验证通过。Windows 侧后续应至少覆盖：Win32 Release 全量构建、缺失 `krnln.fne`/错误 `iDraw.fne`、重复安装 MD5 幂等、插件加载/卸载、DPI、易语言 5.8/5.93/5.95 兼容性、Hook 清理、配置变更和事件回调异常。

## 11. 版本基线与远程复核

- 本地分支：`master`，工作树现场无未提交变更；
- 本地 HEAD：`b4431a307718207e91c9e2a7138902d9ca03196d`，提交主题“修正CI编译”，时间 `2026-07-27T11:56:04+08:00`；
- 远程：`https://github.com/aiqinxuancai/eide.git`；
- `git ls-remote`：`refs/heads/master` 为 `b4431a307718207e91c9e2a7138902d9ca03196d`，与本地一致；
- 远程标签：`v0.0.1` → `5ebb6dd0a79bd3f1c595e5013006ea0c248f6e67`，`v0.0.2` → `b4431a307718207e91c9e2a7138902d9ca03196d`；
- README 宣称的示例发布版本 `v1.4.1029`/`v1.5.1003` 与当前 Git 标签命名不一致；代码版本头为 `1.5.1003`，应以源码和构建产物为实现基线。

本项目未发现 `细探-*.md` 或其他旧架构细探文件，因此不存在需要合并或删除的旧细探。此前专属 `project_context` 返回的是华世王镞_v3 根而非本目标仓库；本文件的项目身份改以本目标仓库路径、Git、README、工程和源码现场证据为准。目标仓库没有 `.codegraph/`，`codegraph_explore` 明确返回未索引，本轮使用本地源码工具完成取证。

## 12. 风险、未确认项与后续复核

1. **Windows-only**：核心依赖 Win32、MSVC、MFC、D2D 和易语言内部窗口层，macOS/Linux 无法直接验证。
2. **原生 ABI 风险**：大量 `WPARAM/LPARAM`、裸指针、函数指针和 `__stdcall/CALLBACK/__cdecl` 混用；头文件版本、结构体布局或调用约定不一致会直接崩溃。
3. **内部窗口假设**：代码使用固定控件 ID（如 `59648`、`65280` 区间）和 MDI 层级；易语言 IDE 版本改变内部窗口树时可能失效。
4. **Hook 与卸载顺序**：核心和插件都注册 Hook/窗口回调；异常卸载、插件崩溃或回调指针失效可能影响宿主 IDE。
5. **配置工程重名**：`src/iConfig/iConfig.vcxproj` 与 `src/iDraw_Config/iDraw_Config.vcxproj` 均出现 `iConfig` 目标，需在 Windows 完整构建时确认是否存在历史重复或解决方案配置差异。
6. **发布脚本与部署语义差异**：`scripts/deploy-to-e.cmd` 确实存在，但只是将构建目录通过 `xcopy` 复制到易语言目录；`scripts/package-release.ps1` 才负责主包/SDK 包组装。两者都不提供完整制品摘要、原子切换和回滚，不能把调试部署脚本当作可信发布事务。
7. **脚本硬编码与跨环境**：`setup.cpp` Debug 分支含开发机绝对路径；发布脚本、安装器和工程依赖 Windows 反斜杠路径，不能在 macOS 直接替代执行。
8. **XML API 完整性**：核心若干 XML 导出函数存在直接返回 0 的实现，需根据易语言接口兼容性决定补全、废弃还是仅保留 ABI。
9. **版本来源不统一**：Git 标签为 `v0.0.2`，代码版本为 `1.5.1003`，README 还记载 `v1.4.1029`；发布流程应明确“Git 标签版本”与“支持库内部版本”的关系。
10. **测试覆盖不足**：仓库测试以手工/GUI 工程为主，未见对所有导出 API、回调注册、资源损坏、DPI、并发事件和卸载清理的自动化覆盖。

## 13. 证据路径清单

- `README.md`：定位、兼容性、安装、特性、版本说明与许可口径；
- `docs/项目结构.md`：重组后的目录、构建输出、发布布局和 CI 说明；
- `Directory.Build.props`：输出目录与 GBK 编译字符集；
- `iDraw.sln`：主解决方案项目组成与 Win32/x64 配置；
- `src/include/IDraw_Header.h`、`src/include/iDraw_const.h`、`src/include/iDraw_Virtual.h`：公共数据模型、回调、功能号和绘画抽象；
- `src/iDraw/iDraw_Interface.cpp`、`src/iDraw/iDraw_Interface_Plugin.cpp`、`src/iDraw/iDraw_Interface_Info.cpp`：核心 API、插件、信息接口；
- `src/iDrawControl/EControls_main.cpp`、`src/iDrawControl/EWindow_EIDE.cpp`、`src/iDrawControl/EWindow_Fne_SetWindowsHook.cpp`：控件、IDE Hook 和消息处理；
- `src/iDraw_Event/iDraw_Event_Main.cpp`：消息/事件注册表与分发；
- `src/iTheme/iTheme_Main.cpp`、`src/IDraw_Resource/`、`src/EWindowSize/`：主题、资源、尺寸模块；
- `plugins/易IDE视觉库_背景插件/dllmain.cpp`、`plugins/易IDE视觉库_行号插件/lineCode_main.cpp`：两个公开插件的真实调用链；
- `src/insert/setup.cpp`：安装器校验、版本读取、MD5 复制；
- `scripts/package-release.ps1`、`.github/workflows/release.yml`：打包、发布与 CI；
- `src/include/iDraw_Version.h`、`src/iDraw/iDraw.def`、`src/include/iDraw_Interface.def`：版本和 DLL 导出契约。

> 后续架构维护只更新本文件；不创建平行“细探”文档，不把未在源码/构建/Windows 运行中验证的行为写成已实现事实。

## 14. 第三轮：通用开发工具底座映射（源码事实版）

本节是第三轮补充，不是把 eide 宣称成完整 IDE 平台。映射规则是：先记录源码已有边界，再判断它可归入开发工具支持库、开发工具模块、运行核心或网关；没有源码证据的项目模型、编译器、终端、任务调度和 HTTP/CLI 网关明确标为“缺失/待核”。本轮只修改本文件；此前 `project_context` 错绑到 `~/Documents/Agent/PHP/华世王镞_v3`，代码图结果不作为 eide 证据，改用目标仓库本地静态取证。

### 14.1 一条权威链路与四层归属

```text
易语言 e.exe / 支持库配置
  → iDraw.fne::GetNewInf() 读取 LIB_INFO（GUID/版本/兼容/能力标志）
  → jy_estudio_ProcessNotifyLib(nMsg, dwParam1, dwParam2)
  → iDraw_Init() 建立 IDRAW_INFO + IGetEWindow 窗口上下文
  → 固定核心 DLL 按配置→主题→控件→资源→事件→尺寸顺序 IDraw_Interface()
  → Plugin_Init(guid, HMODULE, PLUGIN_INFO) 进入唯一插件注册表
  → 插件注册 nCode/wParam/lParam 功能、HWND/message/event 回调和资源绑定
  → Win32 消息/易语言通知/IRE_* 事件
  → before 回调 → 原窗口过程或核心绘画 → after 回调
  → 配置/主题/资源/窗口状态更新 → 绘画与事件结果
  → NL_FREE_LIB_DATA/NL_UNLOAD_FROM_IDE
  → IDraw_UnInterface() → Plugin_UnInit() → 回调/Hook/菜单/窗口/模块释放
```

| 目标底座层 | eide 中可直接归属的事实 | 不能越界宣称的内容 | 第三轮裁决 |
|---|---|---|---|
| **开发工具支持库** | `src/include/` 的 ABI 结构/函数指针/功能号；`IGetEWindow` 窗口发现；`IEIDE_CodeManage` 编辑器内存适配；`CommonCode/process_muster.*` 的 Win32 进程句柄、启动、枚举、终止；`CFileRW`/主题资源/MD5/路径工具；GBK 编码约束 | 没有统一结果类型、取消令牌、超时对象、进程组协议、跨平台实现或安全资源句柄 | **吸收为低层支持库候选**；只提供窄能力，不放项目编排、插件策略或业务状态 |
| **开发工具模块** | `iDraw.fne` 主支持库；`iDrawControl` 控件/窗口重绘；`iDraw_Event` 消息和事件模块；`iConfig` 配置；`iTheme` 主题；`IDraw_Resource` 资源；`EWindowSize` 布局；插件 DLL；`setup.exe` 和发布脚本 | 没有可持久化项目树、构建任务模型、编译诊断模型、终端会话或任务历史 | **吸收为编辑器视觉/宿主适配模块**；构建/项目/终端只能作为未来模块缺口，不能从资源目录名推断已实现 |
| **运行核心** | `IDRAW_INFO` 共享上下文、`s_plugin_info`/`s_plugin_array` 注册状态、`MAP_MESSAGE`/`MAP_MODULE`/`MAP_MODULE_EVT` 事件索引、窗口子类化/Hook、加载顺序和卸载顺序 | 不是独立守护进程；没有崩溃隔离、健康监督、状态持久化、事务回滚和线程安全注册表 | **吸收为进程内运行核心原型**；若迁移到通用底座，必须补生命周期状态、所有权、线程模型和崩溃隔离 |
| **统一网关** | 源码没有 HTTP、MCP、RPC、CLI 或稳定序列化入口；导出函数和 `nCode,wParam,lParam` 只适用于同进程/同 ABI | 不能把 `IDraw_Interface` 或裸函数指针当通用网关；也不能让调用方直接传 `HWND`、`LPARAM`、插件对象穿透网关 | **废弃直接复用为网关**；若未来接入，只能由项目适配层把项目/操作/插件能力转换为版本化命令，网关不持有裸窗口/模块指针 |

**唯一链路约束：** 同一个插件 GUID 只能有一个注册 owner，事件只能从 `iDraw_Event` 注册/取消，资源只能由 `IEWindowResource`/`ID2DDraw` 所属模块创建和销毁，配置只能经过 `iConfig`/`IConfig`，窗口状态只能经过 `IDRAW_INFO` 和 `IGetEWindow` 的适配入口。禁止未来模块绕过这些入口直接 `LoadLibrary`、改 `s_plugin_info`、写主题文件或自行维护第二张事件表。

### 14.2 项目模型、编辑器模型和易语言式组件契约

#### 项目/编辑器模型的真实边界

源码中的“项目”不是持久化领域对象，而是易语言 IDE 当前窗口树的运行时投影：

- `IGetEWindow` 以 `HWND` 暴露菜单、代码区 MDI、状态夹、工作夹、支持库树、程序树、组件树、属性框和状态输出等窗口（`src/CommonCode/e/CGetEWindow.h:14-164`）；`EWINDOW_MDICHILD` 只保存 MDI 四层窗口和滚动条句柄。
- `IDRAW_INFO` 把上述句柄、`RECT`、DPI、运行/停止标志、`path_e/path_lib/path_data/path_plugin/path_config`、主题/配置/资源/事件回调聚合为共享上下文（`src/include/IDraw_Header.h:375-538`）。这是**宿主投影**，不是项目、文件、目标或构建图的权威存储。
- `MDICLIENT_CODETYPE`/`ECODETYPE` 与 `CUSTOMTAB_INFO` 提供代码窗口类别：程序集、窗口、类、全局变量、数据类型、DLL 命令、常量、图片、声音等（`src/include/iDraw_const.h:4-26`、`src/include/EIDE_Virtual.h:9-80`）。它们是识别/绘画所需的枚举，不是编译器 AST 或项目清单。
- `IEIDE_CodeManage` 以 `init(HWND)` 绑定代码窗口，读写光标/选区/行信息/代码类型/对象指针/代码文本，并以 `alloc/free` 约束返回文本的释放；实现通过固定内存偏移和字节特征扫描调用易语言内部对象（`src/include/EIDE_Virtual.h:84-169`、`src/include/EIDE_CodeManage.cpp:146-205,346-375,447-530`）。这应归“编辑器宿主适配支持库”，不能当通用代码编辑器协议。
- `EIDE_InternalMethods.cpp` 的 `CWnd_FromHandle`、`EIDE_FindAddress`、`EIDE_PushMemory` 依赖宿主进程布局和定时释放线程（`src/include/EIDE_InternalMethods.cpp:9-110`），属于高风险进程内兼容层。

**底座映射：** 项目模型缺口必须由“项目适配层/开发工具模块”未来补建，至少要有 `项目id、根路径、文件集合、活动编辑器、配置版本、目标/构建任务引用`；eide 当前只贡献“活动宿主窗口与编辑器句柄读取”能力。不能从 `assets/theme/data/project/` 的图标目录推导出项目文件模型。

#### 易语言式组件契约（事实字段与所有权）

| 契约对象 | 入口/字段 | 生命周期与所有权 | 风险/底座要求 |
|---|---|---|---|
| 支持库契约 | `GetNewInf()` 返回静态 `LIB_INFO`：库格式、库 GUID、主/次/构建版本、所需易语言/核心版本、语言、说明、`LBS_IDE_PLUGIN` 与 `LBS_FUNC_NO_RUN_CODE`、`jy_estudio_ProcessNotifyLib`（`src/iDraw/EWindow_Fne_main.cpp:1098-1160`） | 返回指针由 DLL 静态存储；宿主只读，不能跨卸载继续使用 | 版本/GUID/标志必须固定；`LIB_INFO` 缺少现代结构化错误、取消和资源预算字段，需适配层补契约版本 |
| 组件/插件契约 | 导出 `IDraw_Interface(IDRAW_INFO*, IGetEWindow*, int, int)` 与 `IDraw_UnInterface()`；返回 `PLUGIN_INFO` | `IDRAW_INFO*`、`IGetEWindow*` 由核心借用；插件返回的 `PLUGIN_INFO` 多为静态或核心 map 内对象；回调地址归插件 DLL 所有 | 卸载前必须撤销所有回调、Hook、窗口绑定；不能缓存插件函数指针到 DLL 卸载后 |
| 插件身份 | `PLUGIN_INFO.cbSize/name/remarks/version/author/Versionlimit/Dependence/guid/pfnMenuExt_Command/pfnCallback`（`src/include/IDraw_Header.h:200-234`） | GUID 是注册主键；`Plugin_Init` 用 GUID hash 进入 `s_plugin_info`、`s_plugin_array`，重复同名同 GUID 返回已有对象（`src/iDraw/EWindow_Fne_main.cpp:1325-1406`） | `Dependence` 字段存在，但当前加载代码未见依赖拓扑/版本约束执行；不能把声明当已实现依赖治理 |
| 功能调用契约 | `pfnCallback(nCode,wParam,lParam)`、各 `pfnControls(IDC_*,wParam,lParam)`；结构体常用 `cbSize`、裸指针、`WPARAM/LPARAM` | 参数由调用方按功能号解释；结构体和调用约定要求同版本、同位数、同编码 | 统一底座应把每个 `IDC_*` 固定成能力 id + 参数/返回/错误/超时/释放契约，禁止继续扩张无 schema 的裸参数 |
| 编辑器对象契约 | `IEIDE_CodeManage::GetCodeText` 返回需调用同一对象 `free()` 的内存；`alloc/free` 不接受外部指针 | 返回文本所有权转移给调用者，但释放器绑定对象；`destroy()` 只清空内部对象指针 | 项目适配层只能在对象仍有效且宿主版本匹配时使用；对象失效、窗口销毁和宿主升级应返回结构化“宿主不可用”，不能继续读固定偏移 |
| 事件契约 | `iDraw_Register_Message(guid,hWnd,message,before,after)`、`iDraw_Register_Event(guid,nEvent,paramBefore,before,paramAfter,after)`；返回 `IDRAW_ERR_*` | 注册表按 HWND→message→GUID 或 event→GUID 保存回调；插件 GUID 是取消/清理边界 | 回调 before 可设置拦截结果，after 可返回拦截结果；函数签名/调用约定错误会栈失衡并崩溃，必须在通用底座中禁止未经声明的函数指针 |

### 14.3 组件插件注册、构建任务和工具链映射

#### 组件/插件注册链

```text
核心 DLL/可选插件文件
  → LoadLibraryW
  → GetProcAddress(IDraw_Interface, IDraw_UnInterface)
  → IDraw_Interface 返回 PLUGIN_INFO
  → 校验 cbSize/name/pfnCallback/guid
  → Plugin_Init：GUID hash + s_plugin_info + s_plugin_array
  → 写入 IDRAW_INFO.pfnX / pResource / d2d / evt
  → iDraw_Event_Register_* 或 iDraw_MenuExt_Insert / iDraw_Subclass_*
  → 事件/消息运行
  → Plugin_UnInit：菜单、滚动回调、InlineHook、工具条、消息/事件、窗口绑定
  → IDraw_UnInterface → FreeLibrary
```

核心模块在 `src/iDraw/EWindow_Fne_main.cpp:683-691,729-825` 固定按配置、主题、控件、资源、事件、移动尺寸、助手加载；缺少必备模块时 `errText`/消息框后 `exit(0)`。可选插件由 `iDraw_LoadPlugin()` 扫描 `path_plugin + iDraw_*.dll`，逐个 `LoadLibraryW` 并登记（`...:1236-1267`）；源码明确留下“应签名/应按配置顺序加载”的 TODO，因此当前不是可审计的插件清单或依赖 DAG。

#### 构建任务与工具链是真实存在的，但不是用户项目构建系统

- 根 `iDraw.sln`、20 个 `.vcxproj`、`Directory.Build.props` 构成**仓库自身**构建图；`EideBinDir` 将产物放入 `build\\$(Configuration)\\$(Platform)\\`，中间文件进入 `build\\obj\\...`，并用 `/source-charset:.936 /execution-charset:.936` 固定 GBK（`Directory.Build.props:8-33`）。
- 正式构建任务是 `msbuild iDraw.sln -m -p:Configuration=Release -p:Platform=Win32`；插件在主支持库依赖链之外，还需单独 MSBuild `.vcxproj`（`docs/项目结构.md:76-97`）。这属于开发工具支持库的**仓库构建适配器**，不是易语言用户项目的 `项目→目标→编译器→终端` 执行单元。
- `scripts/package-release.ps1:41-160` 读取 `iDraw_Version.h`，清理/创建 `build/package-stage`，分流主包与 SDK，删除调试文件，校验 `setup.exe`、`iDraw.fne`、6 个 DLL 和 2 个插件 DLL，然后生成两个 zip；这是可追踪的“构建制品/发布任务”。
- `.github/workflows/release.yml:20-84` 在 `windows-2022` 安装 MSBuild，编译 Win32 Release，扫描 C4566/C4819，调用打包脚本并上传 artifact/创建 Release。它是 CI 编排入口，不是运行核心，也没有任务取消/重试/断点状态。
- 源码、工程、脚本中没有用户项目 `BuildTask`/`Target`/`Compiler`/诊断流/任务队列模型；内容命中主要是资源目录名和 MSBuild 工程文件。因而“构建任务”在本项目只能映射到开发工具模块的仓库构建适配器，不能映射成通用编译器模块。

#### 进程与终端边界

`src/CommonCode/process_muster.*` 是 Win32 低层进程工具：`process_create` 调 `CreateProcessW`，可选择 `WaitForSingleObject(INFINITE)` 或 `WaitForInputIdle(1000)`；`process_open` 使用 `PROCESS_ALL_ACCESS`，`process_terminate` 直接 `TerminateProcess`，并提供 Toolhelp 枚举、命令行读取和按端口查询（`process_muster.cpp:15-88,168-218,392-405,810-889`）。

这不是终端子进程执行器：没有标准输入/输出/错误管道、逐行协议、工作目录沙箱、环境白名单、超时取消令牌、进程组 kill、退出码/信号统一结果或输出上限；`PROCESS_INFORMATION`/返回句柄需要调用者自行 `CloseHandle`。因此：

- **归属：** `process_open/create/close/terminate` 可吸收为开发工具支持库的“受限宿主进程能力”；
- **隔离：** 不能直接作为运行核心任务系统；运行核心若要执行编译器/终端，必须包一层独立进程组监督器；
- **缺口：** 当前 eide 没有终端 UI、终端会话、shell 解析、编译器进程或用户命令入口，不能声称支持“终端子进程”；
- **风险：** `WaitForSingleObject(INFINITE)` 是无界等待，`TerminateProcess` 是强杀且不执行被杀进程清理；二者都不能满足通用任务超时/取消契约。

### 14.4 文件、资源、配置和事件的唯一链路

#### 文件与制品

```text
源码/资源/工程文件
  → MSBuild 输出 build/<配置>/<平台>/
  → PostBuildEvent 复制到 dist/lib/
  → package-release.ps1 创建 package-stage
  → 主包 zip 或 SDK zip
  → setup.exe 加载包内 lib/iDraw.fne
  → GetNewInf 校验支持库身份
  → isEPath 校验目标存在且可加载 lib/krnln.fne
  → _enum_files 只枚举 lib/clr/Tools
  → cmpmd5
  → CFileRW 逐文件写入目标易语言目录
```

- `build/` 是构建中间/最终产物；`dist/` 是发布素材与构建复制目标；`build/package-stage` 是一次打包暂存；zip 是可交付制品。它们不能被运行时插件当作配置数据库。
- `setup.exe` 在复制失败时记录错误、关闭/重置源目标文件并 `DeleteFileW` 目标文件，但已经成功复制的前序文件不会事务性回滚（`src/insert/setup.cpp:397-458`）；这是**部分安装**，不是原子发布。
- `setup.exe` 对目录只校验 `krnln.fne` 存在及 `LoadLibraryExW(...,DONT_RESOLVE_DLL_REFERENCES)` 成功（`...:599-620`），没有签名、权限边界、版本锁或安装回滚；未来底座应把“安装目标/制品摘要/激活指针”纳入发布事务，不复用当前逐文件复制语义作为可信发布。
- 运行时配置链是 `IDRAW_INFO.path_config` → `CPrivateProfile` 打开 `config.ini` → `[Theme] name` 选择 `path_data` 下主题文件 → `iniColor` 读取颜色/布局；`iConfig` 收到 `INE_CONFIG_CHANGED` 后重读配置、通知主题/控件和其他插件（`src/iConfig/iConfig_Main.cpp:92-113,115-166`）。配置写入/即时效果属于开发工具模块，不能由任意插件旁路写入。
- 资源模块从 `.eil/.xml/图片/.ires` 等文件加载，`EWindowResource::EWindow_Resource_Free` 释放哈希字符串、GDI+/D2D 图片和缓存（`src/IDraw_Resource/EWindow_Resource.cpp:548-573`）；主题模块 `DeleteDefaultObject` 释放画刷/画笔/字体（`src/iTheme/iTheme_DefColor.cpp:103-123`）。资源制品的创建者和释放者应保持同一模块。

#### 事件唯一 owner 与状态投影

`iDraw_Event` 内部没有第二个事件源：

- 消息索引为 `HWND → UINT message → GUID → REGISTER_MESSAGE_INFO`，事件索引为 `nEvent → GUID → REGISTER_EVENT_INFO`（`src/iDraw_Event/iDraw_Event_Main.cpp:14-35`）。
- 注册消息会拒绝空 GUID/无效 HWND；注册事件会拒绝空 GUID，并把 before/after 参数、回调和 DLL 名写入表；消息/事件取消按 GUID 删除（`...:221-340,379-415`）。
- `_event_before`/`_event_after` 依次调用回调；`isStop` 时非零返回值可拦截后续插件，单消息/事件上限为 `EVENT_MAX_ITEM=128`（`...:437-520`）。
- 窗口销毁用 `iDraw_DetachRegister_Message(HWND)` 删除该 HWND 的消息表；插件卸载由 `Plugin_UnInit` 统一调用 `pfnUnRegister_Message/Event` 和 `pResource->UnBindWindow`（`src/iDraw/EWindow_Fne_main.cpp:1459-1516`）。

这条链路可作为运行核心“事件注册表 + 事件投影”原型吸收，但当前 map/hash/全局集合没有源码级互斥、持久化或事件序列号；禁止把它直接当可重放事件账本。

### 14.5 执行单元生命周期（易语言宿主版）

这里的执行单元是一个“支持库/插件 DLL 在 e.exe 进程中的运行实例”，不是编译任务。通用底座可借鉴状态边界，但不能照搬裸指针。

| 状态 | 真实动作 | 成功出口 | 失败/释放要求 |
|---|---|---|---|
| `发现` | 宿主从 `GetNewInf` 获取 `LIB_INFO`；核心从 `lib\\iDraw\\` 查固定 DLL，从 `plugin\\` 查 `iDraw_*.dll` | 身份/版本/路径可继续 | 缺文件、无法 `LoadLibraryW`、缺导出：核心记录错误；核心插件会终止启动，可选插件跳过；关闭已打开模块句柄 |
| `绑定` | 调用 `IDraw_Interface`，传 `IDRAW_INFO` 与 `IGetEWindow`；校验 `cbSize/name/guid/pfnCallback`；`Plugin_Init` 登记 GUID | 返回 `PLUGIN_INFO`，写入模块回调 | 返回空/字段缺失：`Plugin_UnInit` 清事件后 `FreeLibrary`；不允许保留半注册项 |
| `装配` | 配置→主题→控件→资源→事件→尺寸初始化，建立 `pfnConfig/pfnTheme/pfnControls/pfnResource/pfnEvent/pfnMove` | `pResource/d2d/iDraw/evt` 就绪，开始子类化窗口 | 任一必备能力缺失：消息框 + `exit(0)`；当前无事务回滚，后续底座需按依赖逆序回滚 |
| `就绪` | `NL_IDE_READY` 通知插件；设置 DPI/窗口尺寸，取消热键，发送 `WM_SIZE` | `IDRAW_INFO.isReady=true`，接受用户操作 | `NL_IDE_READY` 处理函数为空/未实现的部分不能算就绪保障；需记录失败事件 |
| `运行` | Win32 消息、Hook、菜单、绘画、编辑器读写、`IRE_*` 事件进入回调；配置变化触发重载 | 回调返回 0 继续，非零可按事件策略拦截 | 回调崩溃同宿主进程；错误码仅少量 `IDRAW_ERR_*`，无隔离/熔断/超时 |
| `重配置` | `iConfig` 读 INI/XML、装载 CLR、调用主题/控件/插件变化回调 | 主题/尺寸/绘画对象重新创建 | 配置文件缺失有默认主题路径，但某些文件/接口失败只返回 0；必须先保留旧资源，再交换新资源，当前代码未形成事务 |
| `停用` | `NL_UNLOAD_FROM_IDE`/`NL_FREE_LIB_DATA` 逐插件通知；debug 路径调用 `pfnUnInterface`、`Plugin_UnInit`、`FreeLibrary` | 回调表、菜单、Hook、窗口绑定、模块句柄清理 | 核心 `_ide_free(INT)` 为空；多个核心 DLL 的 `IDraw_UnInterface` 为空，释放覆盖不完整，属于待核风险 |
| `崩溃/强退` | 没有宿主监督器；进程/插件异常直接影响 e.exe；外部进程 helper 只能强杀句柄 | 无自动恢复 | 不存在崩溃恢复、孤儿进程/窗口/Hook 扫描、事件重放或最近状态恢复；通用底座必须采用独立进程组 + 资源租约 |

### 14.6 资源释放和所有权账本

| 资源 | 创建/持有者 | 正常释放证据 | 失败/超时/取消/崩溃现状 | 底座要求 |
|---|---|---|---|---|
| DLL `HMODULE` | `_load_plugin`/`iDraw_LoadPlugin` | `FreeLibrary`（`EWindow_Fne_main.cpp:301-303,1207-1221`） | 插件初始化失败会释放；宿主崩溃无法执行 | 句柄包装 + owner + 逆序释放 + 崩溃扫描 |
| 插件注册项/GUID hash | `Plugin_Init` 写 `s_plugin_info`/`s_plugin_array` | `Plugin_UnInit` 删除 map、hash、菜单和回调 | 重复 GUID 同名返回已有对象；异常中途可能半注册；hash 字符串集合释放路径不完整 | 唯一 GUID、幂等注册、注册事务和失败回滚 |
| 消息/事件回调 | `iDraw_Event` 全局 map | `UnRegister_Message/Event`、窗口 detach | 无线程锁；回调抛异常会伤害宿主；事件模块 `IDraw_UnInterface` 为空 | 单 owner、回调快照、禁注册期、异常隔离和清空审计 |
| HWND 子类化/原 WndProc | `iDrawControl::_subclass_*` | `Plugin_UnInit` 仅间接清理部分绑定；Hook 清理由模块回调 | 窗口销毁/插件崩溃时可能留下旧函数指针 | 保存 old proc、卸载前停止派发、确认还原后再 `FreeLibrary` |
| InlineHook/Detours/MinHook | 控件/插件调用 `iDraw_InlineHook` | `IDC_IDRAW_UNINLINEHOOK_PLUGIN` + 插件 free callback；菜单 Hook 有 `_unHook()` | 无超时；崩溃后只能随宿主退出恢复 | Hook lease + owner module + 释放确认，严禁 DLL 卸载前仍可执行 |
| D2D/GDI 画刷/画笔/字体/Canvas | `iTheme`/`iDrawControl`/插件 | `DeleteDefaultObject`、`_brush_destroy/_pen_destroy/_font_destroy`、插件自清理 | 主题重载中途失败可能无原子交换；跨模块句柄释放风险 | 资源句柄类型/代际/owner，创建新资源成功后原子替换 |
| GDI+/D2D 图片与资源缓存 | `IDraw_Resource` | `EWindow_Resource_Free` 和 `FreeResourceReturn` | `IDraw_Resource::IDraw_UnInterface` 空；崩溃无清理 | 资源包引用计数、finally 清理、磁盘残留审计 |
| 配置文件/CLR/主题文件 | `iConfig`/插件读取，`CFileRW` | 栈对象/`reset`/`delete[]`；配置写入由 `CPrivateProfile` | 安装器部分成功不回滚；异常写入一致性未证实 | 临时文件 + 原子替换 + 版本/摘要 + 写 owner |
| `PROCESS_INFORMATION`/进程句柄 | `process_create` 返回调用方 | 调用方 `process_close`/`CloseHandle` | 无 RAII；无限等待；强杀不清理子树；无输出管道 | 独立进程组、stdout/stderr 上限、超时→终止→回收→残留验证 |
| 定时释放内存线程 | `EIDE_PushMemory` 的 `s_free_memory`/`CreateThread` | 到期调用 `pfn` 并从集合移除 | `s_IsLoopFree` 无停止路径，线程/临界区未见宿主卸载时 join；迭代 erase 也需复核 | 任务 owner、取消/停止信号、线程 join、双重释放保护 |
| 安装制品/目标文件 | `setup.exe` 逐文件打开读写 | 单文件失败时删除目标文件；成功文件留在目标目录 | 部分安装、无事务回滚、用户取消没有显式状态机 | 制品摘要、临时目标目录、原子切换、可恢复发布事务 |

### 14.7 失败/超时/取消/崩溃矩阵

| 场景 | 当前源码行为 | 当前等级 | 通用底座映射/验收要求 |
|---|---|---:|---|
| `GetNewInf`/支持库格式、版本或路径不合法 | 宿主或安装器拒绝；详细错误依赖宿主消息 | L1 | 适配层返回稳定错误码与版本范围，不把 MessageBox 当 API 结果 |
| 固定核心 DLL 缺失/无 `IDraw_Interface`/无 `IDraw_UnInterface` | `errText` 汇总；核心启动阶段 `exit(0)`；可选插件可能跳过 | L2 | 依赖 DAG + 逐节点回滚 + `CORE_DEPENDENCY_MISSING`，禁止半装配 |
| 插件 `PLUGIN_INFO` 字段缺失/回调为空 | `_load_plugin`/`_call_plugin` 判失败，可能 `FreeLibrary` | L1 | 结构大小、GUID、调用约定、位数和 ABI 预检；记录证据 |
| GUID 重复/同插件重复初始化 | 同名同 GUID 返回已有对象；不同信息可能覆盖部分字段 | L1 | 一个 GUID 一个 owner；重复相同内容幂等，不同契约版本拒绝 |
| 无效 HWND/GUID 注册事件 | 返回 `IDRAW_ERR_INVALIDHWND`/`IDRAW_ERR_INVALIDGUID` | L1 | 可直接映射稳定错误码；验证表必须覆盖空句柄、空 GUID、窗口销毁竞态 |
| 回调签名、栈约定、结构体版本不匹配 | 头文件已警告可能栈失衡并崩溃 | L2 | 不能通过字符串能力 id 调用裸函数；生成 ABI 适配器和隔离进程 |
| 配置/主题/CLR 文件不存在或损坏 | 主题名/文件有默认回退；部分 `CFileRW`/XML API 失败返回 0 | L1 | 读路径白名单、旧配置保留、错误不覆盖成功；补损坏/半写测试 |
| 配置变化时控件尚未初始化 | `iConfig` 分配缓冲区，后台线程每 200ms 等待 `pfnControls`，成功后 `delete[]` | L1 | 当前无截止时间、取消或宿主退出检测；必须改为有界等待 + 取消 + join |
| 构建工具链缺失/编译失败/字符集警告 | MSBuild 非零；CI 检查 C4566/C4819 后失败；打包脚本抛异常 | L0/L1 | 任务结果含退出码/日志/制品清单；失败不得发布或覆盖已激活制品 |
| `process_create` 启动失败 | 返回 0，若无输出 `PROCESS_INFORMATION` 则关闭句柄 | L0 | 返回结构化 `PROCESS_START_FAILED`，区分权限/路径/参数；句柄 ownership 必须可验证 |
| 外部进程超时 | `wait=true` 使用 `INFINITE`，没有超时实现 | L0 | 运行核心必须设置软超时、SIG/Terminate、kill 子树、宽限、回收和残留检查 |
| 用户取消构建/终端 | 没有取消令牌、任务 id 或终端入口 | L3 | 当前标“未实现”；未来用命令状态机 `queued/running/cancelling/cancelled/finished`，取消结果不可伪装为成功 |
| 进程/插件崩溃 | 插件与 e.exe 同进程；没有 supervisor；外部 helper 直接 `TerminateProcess` | L2 | 第三方编译器/插件移到独立进程，崩溃转 `PROVIDER_CRASHED`，重启次数有界 |
| 回调抛异常/事件链阻断 | 原生回调无异常边界；可直接伤害宿主 | L2 | 回调包装 catch/SEH 记录，阻断该插件而非宿主；事件快照防注销竞态 |
| 安装中途文件写失败 | 记录错误、删除当前目标文件，但保留前序成功文件 | L1 | 现状是部分安装；底座必须临时目录+摘要+原子切换+回滚/重试 |
| 正常卸载 | `_debug_free_plugin` 有明确 `pfnUnInterface→Plugin_UnInit→FreeLibrary`；核心/配置/资源/尺寸若干 `IDraw_UnInterface` 为空 | L2 | 只有逐资源确认后才可宣称释放完成；补卸载清单和残留扫描 |
| 宿主崩溃/断电 | 无持久事务、恢复指针、事件账本或孤儿扫描 | L4 | 当前不支持恢复；通用发布/任务/资源底座需持久意图先于切换、重启对账 |

**结论：** 本项目没有“超时/取消/崩溃安全”实现，只能把这些列为平台升级约束；不能用正常路径的 `return 0` 或 MessageBox 证明失败治理完成。

### 14.8 L0-L4 能力分级与吸收裁决

| 等级 | 定义 | eide 事实 | 结论 |
|---|---|---|---|
| **L0 原子宿主支持** | 文件、路径、编码、动态库、窗口句柄、受限进程、资源句柄等可测原子能力 | `CFileRW`、`CGetEWindow`、`process_muster`、MD5、Win32/D2D/GDI、GBK MSBuild 属性 | **吸收**：拆成有所有权/错误/超时/取消字段的支持库能力；不复制第二套加载器或任务系统 |
| **L1 开发工具模块** | 编辑器宿主适配、配置/主题/资源、控件、布局、插件 API、构建/打包适配 | `iDraw.fne`、`iDrawControl`、`iConfig`、`iTheme`、`IDraw_Resource`、`EWindowSize`、插件、MSBuild/PowerShell 发布 | **吸收**：作为“易语言视觉宿主适配模块”；仓库构建和安装器作为独立模块，不冒充用户构建器 |
| **L2 运行核心** | 单进程装配、注册表、事件路由、执行单元状态、资源逆序释放和故障隔离 | `IDRAW_INFO`、`Plugin_Init/UnInit`、事件 map、Hook/子类化和固定加载顺序 | **待核/升级**：可借鉴链路，但必须补线程安全、状态机、异常隔离、资源租约、清理证据 |
| **L3 开发工具编排** | 项目模型、构建任务、工具链发现、终端会话、编译诊断、取消/重试/产物索引 | 目标仓库未发现这些领域模型或终端入口；只有自身 MSBuild/CI/打包流程 | **缺失**：不得从 eide 源码直接声称存在；若立项需新契约和唯一 owner |
| **L4 统一网关/控制面** | 版本化命令、能力搜索/契约/执行、权限、证据、发布/恢复 | 目标仓库无 HTTP/MCP/RPC/CLI 网关，无统一序列化命令 | **废弃直接映射**：只保留为未来适配方向，禁止把 DLL 导出和裸指针暴露为网关 |

第三轮最终裁决：

1. **吸收：** `IDRAW_INFO`/`IGetEWindow` 的宿主窗口发现、`IEIDE_CodeManage` 的编辑器窄适配、`Plugin_Init/UnInit` 的 GUID 生命周期轮廓、`iDraw_Event` 的单表消息/事件路由、资源/主题释放清单、MSBuild/PowerShell 制品链。
2. **升级后吸收：** `process_muster` 只能作为底层能力；必须补结构化结果、有限等待、进程组、输出管道、取消和句柄 RAII。`IDraw_Interface` 只能作为项目适配器内部 ABI，不能作为公共网关。
3. **废弃/隔离：** 同进程第三方插件、固定内存特征扫描、裸 `HWND/WPARAM/LPARAM` 跨边界、无限等待、`TerminateProcess` 代替取消、逐文件非事务安装、无签名的 `iDraw_*.dll` 自动扫描，不进入通用运行核心。
4. **待核：** `PLUGIN_INFO.Dependence` 是否在旧宿主中另有依赖约束、所有模块的 `IDraw_UnInterface` 是否由外层统一清理、事件 map 的多线程访问、`CFileRW` 的具体句柄 RAII、`iDraw.fne` 在真实易语言 5.8/5.93/5.95 上的 ABI 兼容；这些必须在 Windows 实机/调试器/构建产物上复核。

### 14.9 本轮验证边界

| 验证项 | 命令/证据 | 结果 |
|---|---|---|
| 目标身份 | `git -C <目标根> rev-parse --show-toplevel`；`git log -1` | 目标为 eide，HEAD `b4431a307718207e91c9e2a7138902d9ca03196d`，`master`，与既有文档一致 |
| 工作树边界 | `git status --short` | 现场原有 `?? ARCHITECTURE.md`；本轮只允许继续修改此文件 |
| 源码静态取证 | 本轮读取 `src/include/`、`src/CommonCode/`、`src/iDraw/`、`src/iDrawControl/`、`src/iDraw_Event/`、`src/iConfig/`、`src/iTheme/`、`src/IDraw_Resource/`、`src/EWindowSize/`、`src/insert/`、`plugins/`、`scripts/`、`.github/workflows/`、`tests/`、`docs/` | 已完成；关键路径均保留到文件和行号 |
| 真实构建/运行 | `msbuild ...`、`setup.exe`、易语言宿主 | 本轮未执行；当前主机 macOS，不能把静态证据写成 Windows 构建/插件/安装通过 |
| 自动化测试 | `tests/` 工程和 `.sln/.vcxproj` 盘点 | 未发现统一 CTest/GoogleTest/Catch2/Python 测试入口；测试是 MFC/GUI 试验工程，未形成回归门禁 |
| project_context | 曾返回华世王镞_v3 根和其代码图 | 错绑环境问题；未使用其符号、依赖图或验证结果 |

本节只证明源码映射和缺口，不证明 Windows 构建、易语言宿主运行、插件卸载、DPI、真实编译器、终端子进程或安装回滚已通过。后续若要把 L3/L4 补入平台，必须先登记能力需求、确认唯一 owner、冻结消费者契约、定义资源/失败/取消/崩溃验收，再由项目适配层接入；不得直接改写 eide 的公共 ABI。

### 14.10 第三轮底座对象清单

为了避免把“有相关文件”误判成“已有通用能力”，本轮将目标底座对象逐项落到源码事实：

| 底座对象 | eide 的可映射事实 | 当前不是 | 迁移边界 |
|---|---|---|---|
| **项目模型** | `IGetEWindow` 能发现程序树、代码区、组件箱、属性框、输出夹和 MDI 子窗口；`IDRAW_INFO` 保存宿主路径、窗口句柄、矩形、DPI 和运行标志 | 没有项目 id、项目根、文件清单、目标图、活动文件持久化或版本化快照 | 仅吸收“宿主窗口/编辑器投影”；项目模型必须由适配层另建并以路径和稳定 id 为主键 |
| **组件/插件模型** | `LIB_INFO`、`PLUGIN_INFO`、`IDraw_Interface`、`IDraw_UnInterface`、GUID hash、菜单/工具条回调和 `Dependence` 字段 | 没有签名清单、依赖拓扑、版本求解、权限声明、沙箱或跨进程隔离 | GUID 注册和逆序卸载可作原型；正式插件契约必须补 manifest、能力声明、兼容范围和进程边界 |
| **构建任务** | `iDraw.sln`/`.vcxproj`、`Directory.Build.props`、PostBuildEvent、`package-release.ps1`、GitHub Actions | 不是用户项目的任务图；没有 queued/running/cancelled 状态、日志流、诊断、产物索引或重试策略 | 吸收为仓库构建适配器；任务结果必须结构化记录退出码、警告、制品摘要和工具链版本 |
| **编译器/工具链** | 真实工具链是 MSBuild + Visual Studio C++ + Windows SDK + PowerShell；Win32/Win64 和 GBK 编码属性由工程约束 | 没有 `Compiler` 接口、工具链发现、版本锁、编译诊断模型或易语言用户程序编译入口 | 新建工具链提供者契约；不得把 `process_create` 或 `.vcxproj` 文件名当作编译器抽象 |
| **进程** | `process_open/create/enum/getids/terminate` 和 Toolhelp/窗口到 PID 查询；`CreateProcessW` 以文件目录为工作目录 | 无 RAII、权限最小化、进程组、stdout/stderr 管道、有限等待、退出码统一化或子树回收 | 只吸收为受限原子能力；由运行核心包成独立进程监督器，禁止直接暴露 `PROCESS_ALL_ACCESS` |
| **终端** | 源码没有终端控件、PTY/ConPTY、shell 会话、输入输出协议或终端历史 | 不能宣称存在终端功能；`process_create` 也不等于终端 | 终端必须作为新模块：会话 id、工作目录、环境白名单、输出上限、编码和取消/终止协议均需单独定义 |
| **文件/制品** | `CFileRW`、路径键、主题/资源文件、`build/`、`dist/`、package-stage、zip 和安装器逐文件复制 | 安装器不是原子发布；没有内容寻址制品库、锁、恢复指针或全量回滚 | 文件读写、资源包、制品发布分层；写入用临时文件+摘要+原子替换，不复用部分安装语义 |
| **配置** | `path_config` + `CPrivateProfile` 读取 `config.ini`，主题通过 `[Theme] name` 选择；`INE_CONFIG_CHANGED` 触发模块重载 | 没有 schema、迁移、并发写入协调、秘密隔离、审计版本或事务提交 | 配置 owner 固定为配置模块；读写结果需区分缺失、损坏、默认回退和成功提交 |
| **事件** | `iDraw_Event` 维护 HWND/message/GUID 与 event/GUID 两张索引；before/after 回调、停止传播、`EVENT_MAX_ITEM=128` | 没有线程安全、序列号、持久事件账本、重放或跨进程事件协议 | 作为进程内事件路由原型；正式事件总线须有订阅租约、回调快照、异常隔离和注销确认 |
| **资源生命周期** | DLL、窗口子类、Hook、菜单、D2D/GDI 对象、图片缓存、配置缓冲和进程句柄均有分散创建/释放代码 | 没有统一 owner/lease、代际、引用计数、崩溃清理、残留扫描或释放证据 | 采用“创建者负责登记、使用者借用、owner 逆序释放”的账本；卸载完成必须有逐类确认 |

### 14.11 从源码到通用底座的最小映射

```text
项目适配层
  ├─ 将易语言宿主窗口树投影为活动编辑器/宿主上下文
  ├─ 将 IDraw/插件 ABI 转换为版本化组件能力
  └─ 将仓库构建脚本转换为声明式构建任务
          ↓
开发工具模块
  ├─ 项目与编辑器状态（eide 当前缺失）
  ├─ 组件/插件注册与配置/主题/资源
  ├─ 构建任务与编译器提供者（eide 仅有自身构建适配）
  └─ 终端会话（eide 缺失）
          ↓
运行核心
  ├─ 进程组监督、超时、取消、输出限额
  ├─ 插件/资源/事件 owner 与逆序释放
  ├─ 失败状态、崩溃隔离、重启和残留对账
  └─ 统一结果：成功、值、错误码、错误说明、可重试、详细信息
```

这条映射中只有右侧“适配器输入”属于当前 eide；其余对象是平台待建能力。特别是：

1. `IDRAW_INFO` 是宿主上下文，不是项目数据库；`PLUGIN_INFO` 是进程内 ABI，不是安全插件 manifest。
2. `msbuild` 是 eide 自身的构建工具链，不代表存在可供用户项目复用的编译器服务。
3. `process_create` 只能说明能够启动 Windows 进程；没有管道就没有终端，没有有限等待就没有可治理任务。
4. 配置变化、事件回调和资源重载必须以 owner 为边界；任何模块不得直接改全局 map、直接卸载仍有回调的 DLL，或绕过配置模块写主题文件。

### 14.12 统一生命周期状态图

通用底座吸收 eide 的生命周期轮廓，但把原项目缺少的失败出口显式化：

```text
discovered
  → validated（身份、版本、位数、依赖、路径）
  → attached（建立宿主/插件/任务上下文）
  → allocated（登记句柄、回调、窗口、资源和临时文件）
  → ready
  → running / reconfiguring
  → stopping（停止新事件，拒绝新资源）
  → released（逐项确认 owner 资源已释放）

任一阶段失败：
  → cancelling（撤销可取消工作）
  → draining（等待有限宽限期）
  → terminated（必要时终止进程组）
  → reconciled（对账句柄、文件、窗口、Hook、子进程和制品）
  → failed / cancelled
```

对于 eide 现状，`attached` 对应 `IDraw_Interface`，`allocated` 对应插件注册、窗口子类、Hook 和资源创建，`stopping` 对应 `NL_UNLOAD_FROM_IDE`/`NL_FREE_LIB_DATA`，`released` 只能在所有 `IDraw_UnInterface`、`Plugin_UnInit`、`UnhookWindowsHookEx`、事件注销和资源释放均有证据时成立。当前源码只能可靠证明部分正常路径，不能证明取消、超时、崩溃后的 `reconciled`。

### 14.13 第三轮验收结论

- **已映射：** 宿主窗口/编辑器投影、插件 GUID 注册、进程内消息事件路由、配置/主题/资源入口、仓库自身 MSBuild/打包链以及正常路径的部分资源释放。
- **明确缺失：** 持久项目模型、通用组件 manifest、用户构建任务、编译器提供者、终端会话、结构化进程输出、任务取消/超时、制品事务和统一资源账本。
- **不得复用：** 裸 `HWND/WPARAM/LPARAM` 作为跨边界协议，`PROCESS_ALL_ACCESS`、`WaitForSingleObject(INFINITE)`、`TerminateProcess`、同进程第三方插件、未签名 DLL 扫描和逐文件非事务安装。
- **下一轮前置条件：** 先冻结项目/任务/编译器/终端/组件/资源契约，定义唯一 owner 与错误码，再做 Windows 实机验证；没有这些证据，架构文档只能保留“映射/缺口”，不能升级为“能力已实现”。

### 14.14 交互链与文档质量审计

本轮按“宿主加载 → 编辑器投影 → 插件注册 → 事件/绘画 → 配置与资源 → 构建/发布 → 安装/卸载”复核了完整交互链，并将仓库自身工具链与用户项目能力分开：

```text
e.exe / 易语言支持库配置
  → GetNewInf / IDraw_Interface
  → IDRAW_INFO + IGetEWindow
  → 固定 DLL 与可选插件 GUID 注册
  → HWND/message/IRE_* 回调
  → 控件、主题、资源和编辑器宿主投影
  → MSBuild 构建 eide 自身
  → package-release.ps1 生成主包/SDK 包
  → setup.exe 校验并逐文件复制到易语言目录
  → 支持库配置启用并重启宿主
```

审计结论：

- 交互链的运行时 owner 基本可定位到核心 `IDRAW_INFO`、插件 GUID、`iDraw_Event` 回调索引、主题/资源模块和安装器；但事件索引没有源码级互斥、序列号或持久账本，资源重配置与安装也不是事务。
- `IGetEWindow`、`IEIDE_CodeManage` 和 `MDICLIENT_CODETYPE` 只提供宿主窗口、代码窗口和页面类别的进程内投影；它们不构成项目根、文件树、目标图、活动文件快照或编译 AST。文档中所有“项目模型”表述均应保持“缺失/未来适配”口径。
- MSBuild、Visual Studio C++、Windows SDK、PowerShell 和 GitHub Actions 只构成 **eide 仓库自身** 的构建与发布链；当前没有用户项目构建任务、编译器服务、诊断流、终端会话、任务历史或取消协议。README 的“完整插件开发支持”和 `docs/项目结构.md` 的构建说明不能被解读为这些能力已经存在。
- `process_muster` 能启动、等待或强杀 Win32 进程，但没有标准流管道、输出上限、进程组回收、有限 deadline 或结构化退出结果；因此不能作为终端或通用编译任务实现的证据。
- `scripts/deploy-to-e.cmd` 确实存在，并把 `build\<配置>\Win32\lib\` 通过 `xcopy` 复制到用户易语言目录；它是调试/手工部署辅助脚本，不属于 `package-release.ps1` 的制品发布事务，也没有摘要校验、原子切换或回滚。因此 `docs/项目结构.md` 对它的引用有效，但不能把该脚本描述成可信部署或发布入口。
- README 的“免侵入”与源码中的 DLL 加载、窗口子类化、`SetWindowsHookExW`、InlineHook 和宿主内部结构访问存在语义张力；架构事实应解释为“不修改用户业务源码”，不能解释为“不进入宿主进程或不使用 Hook”。

**文档维护规则：** 根 `ARCHITECTURE.md` 是本项目唯一架构归档；README 和 `docs/项目结构.md` 负责用户/构建说明，不应另行复制项目模型、插件依赖或生命周期事实。新增能力必须同时补充真实入口、owner、失败/释放路径和 Windows 验证证据；仅新增目录、工程文件、函数名或脚本名不足以证明能力已实现。
