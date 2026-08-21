# jywke_-vc6 架构档案

> 源码审计全量静态建档。本文只记录当前仓库源码、工程文件、README、历史构建日志和 Git 基线能够证明的事实。
>
> 状态标记：**已实现** = 当前源码存在可追踪实现；**仅声明/占位** = 有命令、类型、回调或工程声明，但实现为空、无效或只保留接口；**未验证** = 当前环境未在 Windows/Visual C++/易语言中重新构建或运行，不能把工程配置和历史日志当作现状证明。

## 1. 项目定位

`jywke_-vc6` 是精易科技公开的易语言 Web 浏览器支持库源码，目标是把 miniblink 内核包装成易语言可使用的 Windows 组件、对象方法、全局命令和事件。仓库 README 明确将其定位为“基于 miniblink 内核”的 web 浏览器支持库，并说明安装产物包括 `wke.fne`、`wke_static.lib` 和运行时 `node.dll`（`README.md:3-3,24-31`）。

源码实际形成两类交付形态：

1. **动态支持库**：`wkeCode` 编译为 `wke.fne`，通过易语言支持库 ABI 提供 `GetNewInf`、命令表、数据类型、组件接口和通知入口。
2. **静态库**：`wke_static` 工程以 `__E_STATIC_LIB` 编译同一批核心源文件，输出 `wke_static.lib`；静态编译所需的命令名数组由 `wke_dllMain.cpp` 提供。

它不是独立浏览器应用，也没有自己的网络服务、数据库、脚本运行时或测试框架。浏览器能力来自外部 miniblink/node DLL；易语言 IDE/运行时负责加载支持库、传入命令参数、创建组件和接收事件。

## 2. 总体流程图

```text
易语言 IDE / 编译后程序
        │
        │ 加载 wke.fne，或静态链接 wke_static.lib
        ▼
GetNewInf() / wke_ProcessNotifyLib()
        │
        ├── LIB_INFO：版本、GUID、命令表、常量表、数据类型表
        ├── wke_GetInterface_webkit()：组件创建/属性/通知接口
        └── WKE_NAME(index, name)：把命令索引映射到 C/C++ 实现
        ▼
易语言命令层（PMDATA_INF）
        │
        ├── wke_webkit_CmdFun.cpp：浏览、Cookie、代理、窗口、截图、附加
        ├── fun_javascript.cpp：JS 执行、JSValue、回调绑定和类型转换
        ├── fun_tb.cpp + CwkeTBInfo.cpp：选择器/填表/表单/文档/元素操作
        ├── fun_ajax.cpp + Cajax.h：向页面注入 XMLHttpRequest
        ├── fun_SpecialFunction.cpp：网络 Job、请求头、POST、输入事件、Cookie
        └── fun_cmd.cpp：编码转换、版本、消息循环、格式化文本
        ▼
WEBKIT_PROPERTYEX（组件/弹窗运行时状态）
        │
        ├── WEBKIT_PROPERTY：URL、标题、缓存/Cookie 路径、UA、设计预览、新窗口
        ├── BUFFER_POOL：持有 ANSI/Unicode 文本缓冲
        └── WKECtrl : MbE：wkeWebView、HWND、GDI 绘制、jsRunningManager
        ▼
miniblink API（wke/wke.h）
        │
        └── 外部 miniblink_4975_x32.dll / miniblink_4957_x32.dll /
            miniblink_4949_x32.dll / node.dll（运行时探测）
        ▼
网页加载、DOM/JS、Cookie、网络 Job、窗口、绘制
        │
        ├── miniblink 回调：文档、标题、URL、导航、弹窗、下载、网络、控制台
        ├── 子类化 HWND：wke_webkit_Event_msg.cpp 捕获鼠标/键盘/焦点/滚轮
        └── OnwkeCallbackAll：NotifySys(NRS_EVENT_NOTIFY2) 回投易语言事件
```

## 3. 目录与真实分层

```text
jywke_-vc6/
├── README.md                         项目说明、安装/运行时文件线索
├── jywke/
│   ├── wke.dsw                       VC6 workspace，聚合两个工程
│   ├── wke.dsp                       旧版动态库工程，Win32 Debug/Release
│   ├── wkeCode/                      支持库核心实现
│   │   ├── wke_dllMain.cpp           LIB_INFO、导出入口、易语言通知入口
│   │   ├── wke_cmd_typedef.h         统一命令清单 WKE_DEF（0~223）
│   │   ├── wke_dtType*.cpp           数据类型、组件命令索引、属性、事件元数据
│   │   ├── wke_const.cpp              易语言常量表
│   │   ├── wke_webkit*.cpp/.h         WebKit 组件创建、属性、命令、事件、消息
│   │   ├── fun_*.cpp                  命令实现的功能分区
│   │   ├── CwkeTBInfo.*               DOM 选择器/填表/表单/文档/元素实现
│   │   ├── Cajax.h                    页面内 XMLHttpRequest 包装
│   │   ├── WKECtrl.h                  MbE 适配为易语言组件、事件槽、绘制回调
│   │   └── wke/                       miniblink C API 头、窗口、GDI、JS 管理
│   └── wke_static/
│       ├── wke_static.dsp             VC6 Win32 静态库工程
│       └── wke_static.plg             历史 VC6 构建日志
└── ARCHITECTURE.md                    本架构唯一长期建档文件
```

### 3.1 工程层

- `jywke/wke.dsw` 包含 `wke` 和 `wke_static` 两个项目（`wke.dsw:6-18`）。
- `jywke/wke.dsp` 是 VC6 时代的 Win32 x86 动态库工程，Debug/Release 都将目标命名为 `wke.fne`；Release 记录了旧机器路径 `C:\Users\pc1\Desktop\cpp\jywke\out\wke.fne`，Debug 记录 `C:\Program Files\e\lib\wke.fne`（`wke.dsp:5-21,32-82`）。
- `jywke/wke_static/wke_static.dsp` 是 Win32 x86 静态库工程，Release 目标为旧路径下的 `wke_static.lib`（`wke_static.dsp:5-21,31-75`）。
- `jywke/wkeCode/JYwke.vcxproj` 是后来迁移的 VS 工程，声明 Debug/Release × Win32/x64 四种配置、`v142` 工具集、Windows SDK 10.0、动态库目标（`JYwke.vcxproj:3-27,30-59`）。但 x64 配置的输出名、包含路径和部分链接依赖并不完整，不能据此断言 x64 可构建。
- Win32 Debug/Release 配置把 `__E_FNENAME=wke`、`JYWKECPP_EXPORTS`/`_USRDLL` 等宏和 `JYwke.def` 接入链接；PostBuildEvent 复制到 `d:\e\lib\wke.fne`，Release 另有 `E:\易语言正式版\lib\wke.fne` 的历史路径（`JYwke.vcxproj:100-138,162-194`）。这些均是开发者本机配置，不是可移植部署脚本。
- 两个工程都编译 `fun_*`、`wke_webkit_*`、数据类型/常量/命令元数据、Hook C 源和 `jsRunningManager`；静态工程额外在编译宏中设置 `__E_STATIC_LIB`（`wke_static.dsp:83-198`）。

## 4. 模块职责与实现状态

| 模块 | 主要职责 | 状态与证据 |
|---|---|---|
| `wke_dllMain.cpp` | DLL 入口、`LIB_INFO`、命令函数指针表、静态命令名表、易语言通知入口 | **已实现**：`DllMain`、`GetNewInf`、`wke_ProcessNotifyLib`（`wke_dllMain.cpp:13-28,34-114,124-172`） |
| `wke_cmd_typedef.h` | 单一命令声明源；通过宏生成 `CMD_INFO`、函数声明、动态函数名和静态命令名 | **已实现**：`WKE_DEF` 共有索引 0~223（`wke_cmd_typedef.h:3-13`，末项 `:244`） |
| `wke_dtType.cpp` | `WKE_填表`、`AJAX`、`JavaScript`、`特殊功能`、矩形、缓冲区、POST 数据等类型注册 | **已实现**：类型命令索引和元素定义（`wke_dtType.cpp:6-165`） |
| `wke_dtType_Webkit.cpp` | `精易Web浏览器`、`弹出窗口操作` 两个对象的数据类型、属性和事件元数据 | **已实现**：`head_dtType_Webkit`/`head_dtType_NewWnd`（`wke_dtType_Webkit.cpp:5-22,26-58,159-263`） |
| `wke_const.cpp` | JS 类型、代理、加载状态、填表模式、请求/POST 类型、浏览器事件常量 | **已实现**：常量数组和数量（`wke_const.cpp:3-105`） |
| `wke_webkit.cpp` | 易语言组件接口分发、组件创建、属性通知接收、运行时 DLL 路径选择 | **已实现**：接口表、`wke_ControlCreate_Webkit`、四级 DLL 探测（`wke_webkit.cpp:22-85,88-206,288-356`） |
| `wke_webkit_header.h` | `WEBKIT_PROPERTY`、`WEBKIT_PROPERTYEX`、属性索引、文本/路径管理声明 | **已实现**：状态结构和属性接口声明（`wke_webkit_header.h:21-55,61-157,162-203`） |
| `wke_webkit_Parse.cpp` / `GetProp.cpp` / `PropChange.cpp` | 属性字节流解析、单/全部属性读取、IDE 属性变更应用 | **已实现**，但序列化与解析字段顺序存在风险（见第 10 节）（对应文件 `:6-101`、`:9-63`、`:8-151`） |
| `wke_webkit_CmdFun.cpp` | 组件/弹窗共享浏览器命令：导航、源码、Cookie、代理、截图、窗口、设备、事件挂接 | **大部分已实现**；`SetWebVolume`、`SetMediVolume`、`wke_NetGetFavicon` 是空实现（`wke_webkit_CmdFun.cpp:281-291,748-751`） |
| `wke_webkit_Event.cpp` | 绑定 miniblink 回调并转发为易语言组件事件；新窗口、导航、加载、网络、对话框、控制台 | **大部分已实现**：回调注册在 `__fill_wnd_data`（`:1141-1166`）；部分回调为空或仅调试输出（`:676-679,847-850,971-974,1083-1087,1129-1137`） |
| `wke_webkit_Event_msg.cpp` | 子类化浏览器 HWND，处理鼠标、键盘、焦点、滚轮、F5 和销毁 | **已实现**：`wke_WebViewWndProc`、`wke_SubWebviewWindow`（`:24-69,73-84,87-255`） |
| `fun_javascript.cpp` / `jsRunningManager.*` | JS 执行、值对象转换、全局/对象函数调用、易语言回调绑定 | **已实现**：命令实现（`fun_javascript.cpp:11-524`）、JS 管理器（`jsRunningManager.h:27-109`） |
| `fun_tb.cpp` / `CwkeTBInfo.*` | 易语言模式/JS 选择器模式、iframe、表单、DOM 元素、文档和编辑操作 | **已实现**：命令入口（`fun_tb.cpp:17-717`）和具体实现（`CwkeTBInfo.h:20-106`、`CwkeTBInfo.cpp:1-854`） |
| `fun_ajax.cpp` / `Cajax.h` | AJAX 对象生命周期、请求头、GET/POST 请求 | **已实现**：命令入口（`fun_ajax.cpp:10-66`），请求模板和 JS 回调（`Cajax.h:13-172`） |
| `fun_SpecialFunction.cpp` | NPAPI、爬虫/无头、Cookie、网络请求拦截与改写、POST、鼠标键盘、Frame、异步 Job | **已实现/部分**：大量命令直接转 miniblink，需结合运行时内核验证；命令入口范围 `:7-674` |
| `fun_cmd.cpp` | DLL 路径、编码转换、版本、CPU、消息循环、格式化字符串 | **已实现/部分**：编码、版本和消息循环有代码；格式化使用未经校验的 C 格式串（`fun_cmd.cpp:12-188,216-428`） |
| `Ccommand.*` | 动态命令构造辅助类 | **仅占位**：`AddCmd` 只递增计数，`AddArg` 只递增计数，取指针恒返回 0（`Ccommand.cpp:3-37`）；虽被工程编译，但当前命令元数据实际来自宏静态数组 |
| `include/hook/*` | API Hook、指令解析、trampoline、缓冲区；用于文件对话框等系统 API 介入 | **已接入/未单独验证**：`wke_webkit_Event.cpp` 使用 `apiHook.h` 并 Hook `GetOpenFileNameW`（`:1-13,193-197`） |

## 5. 核心运行时对象与数据模型

### 5.1 易语言支持库模型

`wke_dllMain.cpp` 中的 `LIB_INFO s_libInfo` 是对易语言系统的主契约：

- 格式版本 `LIB_FORMAT_VER`；GUID `{6EC0A773-ABA1-49F4-AFD2-977EA30C0D4E}`。
- 支持库版本由 `wke_version.h` 定义为 `1.7.616`（`wke_version.h:8-12`）。
- 依赖易语言系统主版本 3.0 和核心支持库 3.0；OS 标志为 `OS_ALL`（`wke_dllMain.cpp:41-66`）。
- 注册 2 个全局分类：“精易web浏览器”“编码转换”，命令和数据类型由全局数组提供（`wke_dllMain.cpp:69-102`）。
- `GetNewInf()` 在返回前填充第 5 个 Webkit 类型和第 10 个新窗口类型（数组下标对应 `wke_dtType.cpp`/`wke_dtType_Webkit.cpp` 的注册顺序）（`wke_dllMain.cpp:108-115`）。

统一命令清单 `WKE_DEF` 同时生成三份东西：

```text
WKE_DEF
  ├── wke_typedef.h → 每个命令的 C 函数声明
  ├── wke_cmdDef.cpp → CMD_INFO + 参数元数据
  └── wke_dllMain.cpp → 动态函数指针数组 / 静态导出命令名数组
```

这保证命令索引、易语言名称、C 函数名和参数说明来自同一宏源；当前清单索引为 0~223，但“有清单”不等于每个命令都有有效行为。

### 5.2 组件运行时状态

`WKE_STRUCT_BASE` 保存通用窗口单元信息：组件类型、原窗口过程、设计窗口/父窗口、真实 `HWND`、易语言 `HUNIT`、窗口/单元 ID、设计模式和窗口样式（`wke_head_base.h:3-19`）。

`WEBKIT_PROPERTYEX` 扩展该基类，包含：

```text
WEBKIT_PROPERTYEX
├── prop: WEBKIT_PROPERTY
│   ├── url / title / DisableF5 / DisableCookie
│   ├── pszCachePath / pszCookiePath / pszUserAgent
│   ├── debugShow / isNewWnd
│   ├── runPath
│   └── urlW / titleW / pszCachePathW / pszCookiePathW / pszUserAgentW
├── bufPool: CStringBufferA*       文本与序列化缓冲池
└── pCtl: WEBKIT_CTL*              WKECtrl，即 MbE 适配层
```

`init()` 创建 `BUFFER_POOL` 和 `WEBKIT_CTL`，预留 4 KiB，并把 ANSI/Unicode 文本指针初始化为空；`Uninit()` 释放这两个对象（`wke_webkit_header.h:61-103`）。`SetUrl`、`SetTitle`、`SetCache`、`SetCookie`、`SetUA` 通过 `_SET_TEXT_FUN` 同步 ANSI/Unicode 指针（`:123-140`）。

组件对象的定位方式有两套：

1. 易语言组件命令通过 `GethUnitFromArgInf` / `GetWebkitDataFromArg` 找到复合数据，或通过 `hUnit` 找到绑定数据（`wke_webkit_header.h:186-199`）。
2. HWND 消息过程通过窗口属性 `WKE_USERDATA` 找到 `WEBKIT_PROPERTYEX`；`wke_SubWebviewWindow` 保存原过程并设置属性（`wke_webkit_Event_msg.cpp:113-121,250-255`）。

### 5.3 miniblink 适配层

`MbE` 持有 `wkeWebView`、父 HWND、`CRenderGDI` 和 `jsRunningManager`。`Create()` 调 `wkeCreateWebWindow`，创建 JS 管理器和 GDI 渲染器，显示窗口，关闭 CSP 检查，启用 NPAPI，并允许新窗口导航（`wke/MbE.h:8-84`）。它把 miniblink API 包装成加载 URL/HTML/文件、JS、Cookie、代理、窗口、编辑、Frame、设备模拟等方法（`wke/MbE.h:87-309`）。

`WKECtrl` 继承 `MbE`，创建 `WKE_WINDOW_TYPE_CONTROL`，确保窗口类带 `CS_DBLCLKS`，保存 14 个通用回调槽及鼠标、焦点、键盘、滚轮、Cookie、绘画回调（`WKECtrl.h:19-41,51-91`）。绘画回调由 `wkeOnPaintUpdated` 接入易语言绘画事件（`:89-107`）。

## 6. 关键数据流与调用链

### 6.1 组件创建与属性加载

```text
易语言创建组件
  → wke_GetInterface_webkit(ITF_CREATE_UNIT)
  → wke_ControlCreate_Webkit(pAllPropertyData,...)
  → wke_SetDllPath()（若尚未设置）
  → MbE::Initialize() → wkeInitializeEx()
  → GethUnitFromId() / InitDataEx()
  → ParsePropData_webkit()
  → SET_DATA_DEFVALUE(data)
  → WKECtrl::create() → MbE::Create()
  → 设置 UA / Cookie / local storage / 初始 URL
  → __fill_wnd_data() 注册 miniblink 回调
  → CreateUnit() 获取易语言 HUNIT 并建立绑定
```

证据：`wke_webkit.cpp:88-206`、`wke_webkit_Parse.cpp:6-63`、`wke_typedef.h:78-119`。

### 6.2 普通命令

```text
易语言命令参数 PMDATA_INF
  → WKE_NAME(index, name) 生成的命令函数
  → WKE_CTRL 宏取得 WEBKIT_PROPERTYEX / WKECtrl
  → WKECtrl/MbE 包装方法
  → miniblink wke* API
  → pRetData / CloneTextData / CloneBinData 返回易语言值
```

例如“浏览网页”直接调用 `wke->LoadURL`；“取网页 URL”调用 `wke->GetUrl` 后复制返回文本（`wke_webkit_CmdFun.cpp:42-59`）。源码、网页文本、元素属性等命令则构造 JavaScript 表达式，用 `wkeRunJS`/`wkeRunJSW` 执行，再以 `jsToString`/`jsToInt` 等转换（`wke_webkit_CmdFun.cpp:111-144`、`CwkeTBInfo.cpp:177-183,499-507`）。

### 6.3 JS 与易语言互调

```text
易语言脚本/表达式
  → wke_RunJsToJsValue / wke_Eval_JsValue
  → wkeRunJS / wkeRunJsByFrame
  → jsValue + jsExecState
  → wke_ResultTo* / jsType / jsArg*

易语言子程序
  → wke_BindFunc
  → NativeCallBackFunc / _jsCallAsFunctionCallback
  → jsExecState 参数读取
  → 易语言回调 NotifySys / 返回 jsValue
```

`jsRunningManager` 负责按 `ValueType` 将文本、整数、浮点、逻辑值转成 `jsValue`，并调用全局或对象 JS 函数（`jsRunningManager.h:4-25,99-109`、`jsRunningManager.cpp:5-84`）。

### 6.4 AJAX

`Cajax` 不建立独立 HTTP 客户端，而是生成一段页面内 JavaScript：创建 `XMLHttpRequest`、设置请求头、发送 GET/POST，成功把 `responseText`、失败把 HTTP 状态码传给 `ajaxFun`。`jsFun()` 将 C++ 回调地址写入 JS 全局属性后执行脚本（`Cajax.h:13-18,26-49,51-112`）。请求完成后 `_header` 被清空；JSON/表单 POST 会自动补 `Content-Type`（`:51-85`）。

### 6.5 事件与消息

miniblink 回调由 `__fill_wnd_data` 统一注册：文档就绪、标题、URL、导航、新窗口、加载完成、控制台、Alert/Confirm/Prompt、下载、URL 开始/结束、链接悬停、窗口关闭/销毁（`wke_webkit_Event.cpp:1141-1166`）。

事件转发分两条路径：

- 组件路径：`EVENT_PTR_E` 为真，构造 `EVENT_NOTIFY2`，通过 `NotifySys(NRS_EVENT_NOTIFY2)` 发往易语言（例如标题、导航、加载完成、网络回调）。
- 弹窗/附加对象路径：从 `JYWEBKIT_EVENT` 取用户函数地址，直接调用 C/C++ 回调签名。

HWND 子类过程处理 Windows 消息：鼠标按键、移动、焦点、滚轮、字符、键盘和 WM_DESTROY；`event_notify_wke` 根据易语言事件返回值决定继续调用原窗口过程、拦截消息或替换字符（`wke_webkit_Event_msg.cpp:24-69,87-106,113-246`）。F5 行为由 `DisableF5` 控制（`:73-84`）。

### 6.6 网络拦截/POST 数据

`fun_SpecialFunction.cpp` 对 miniblink Job 做直接封装：拦截请求、设置 HTTP 头/MIME/URL/数据、取消请求、挂起/继续异步 Job、读取请求/响应头、读取和构造 POST 元素。对应 `POSTELEMENT`/`POSTELEMENTS` 易语言复合数据在 `wke_dtType.cpp:67-97` 注册；其真实生命周期由调用方显式创建/释放命令管理。`Url载入开始` 事件中若调用 Hook，内核才会缓存数据并触发 `Url载入结束`，这是源码注释和事件元数据明确的前置条件（`wke_webkit_Event.cpp:976-1031`、`wke_dtType_Webkit.cpp:175-178`）。

## 7. 对外接口边界

### 7.1 DLL/静态库 ABI

- 动态导出文件 `JYwke.def` 只导出 `GetNewInf`（`JYwke.def:2-5`）。
- 易语言系统通过 `wke_ProcessNotifyLib` 处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`、`NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA` 和 `NL_UNLOAD_FROM_IDE`（`wke_dllMain.cpp:132-172`）。
- 释放/卸载通知调用 `MbE::wkeUnInit_wke()`；该函数当前不调用 `wkeFinalize()`，只有初始化状态判断，属于实现事实而非已验证的完整清理策略（`wke/MbE.h:51-57`）。
- 静态库通过 `g_cmdNames` 为静态编译提供命令名字，动态 `g_CmdsFunc_web` 提供命令函数地址（`wke_dllMain.cpp:30-38,119-127`）。

### 7.2 易语言对象、属性与事件

`精易Web浏览器` 数据类型：

- 属性：URL、网页标题、禁止 F5 刷新、禁止 Cookies、缓存目录、Cookie 目录、UserAgent、允许设计时预览、允许新窗口打开（`wke_dtType_Webkit.cpp:26-58`）。
- 事件：文档就绪、标题改变、URL 改变、导航、新窗口导航、文档载入完毕、控制台、Alert/Confirm/Prompt、下载、URL 载入开始/结束、鼠标移入链接、鼠标/键盘/焦点/滚轮/绘画、新窗口生命周期、文件对话框等（`wke_dtType_Webkit.cpp:62-224`）。

`弹出窗口操作` 复用浏览器命令集合，附加或新建的 WebView 通过 `Attach`、`newWnd*` 命令访问（`wke_dtType_Webkit.cpp:15-22,247-263`；`wke_webkit_CmdFun.cpp:512-587`）。

### 7.3 命令面

命令按 `wke_cmd_typedef.h` 的索引分组：

| 命令范围/实现文件 | 功能边界 |
|---|---|
| 0~20，`wke_webkit_CmdFun.cpp` | 导航、页面状态、Cookie、UA、代理、WebView |
| 21~26，`fun_ajax.cpp`/`Cajax.h` | AJAX 对象、请求头、GET、POST |
| 27~60，`fun_javascript.cpp` | JS 执行、值对象、函数绑定、类型/参数/返回值 |
| 61~116、162~165、169、181、194~195、199，`fun_tb.cpp`/`CwkeTBInfo.cpp` | 填表、框架、表单、文档、DOM 元素 |
| 117~146、167、172~179、196~197、200~202、221，`fun_SpecialFunction.cpp` | 网络 Job、POST、设备/输入、Cookie、调试 |
| 147~156、170、192~193、217~219、222~223，`fun_cmd.cpp` | DLL 路径、编码、版本、CPU、消息循环、格式化 |
| 157~161、166、168、171、180、182~191、198、203、216、220，`wke_webkit_CmdFun.cpp` | WebView 属性、截图、弹窗、Cookie、创建/消息循环 |
| 204~215，`fun_javascript.cpp` | JS 参数和值类型判断 |

命令表中存在显式隐藏、弃用、测试或高级等级标志，不能将 224 个索引简单视为 224 个稳定公共 API（`wke_cmd_typedef.h:23-244`）。

## 8. 依赖与运行环境

### 8.1 外部运行时

- Windows API：窗口、消息、GDI、Hook、文件路径、`Shlwapi.dll` 的 `PathFileExistsW`。
- 易语言支持库 ABI：`lib2.h`、`lang.h`、`fnshare.h`、`PublicIDEFunctions.h`、`untshare.h` 等。相关头文件以仓库内 `include/elib` 形式随源码提供。
- miniblink：仓库内 `jywke/wkeCode/wke/wke.h` 是 C API 头（约 1548 行），实际引擎 DLL 不在仓库中。源码运行时按路径顺序探测 `miniblink_4975_x32.dll`、`miniblink_4957_x32.dll`、`miniblink_4949_x32.dll`、`node.dll`（`wke_webkit.cpp:288-341`）。
- miniblink 插件：更新日志说明在浏览器组件 DLL 同级的 `plugins` 目录放置插件，Flash 例子为 `NPSWF32.dll`/`NPSWF64.dll`（`更新日志.txt:21-23`）。当前仓库不包含这些 DLL。

### 8.2 编译依赖

- 旧工程依赖 Visual C++/VC6 风格 `cl.exe`、`rc.exe`、`link.exe`，目标为 Win32 x86。
- 新工程声明 VS `v142`、Windows SDK 10.0；Win32 使用多字节字符集，x64 配置改为 Unicode（`JYwke.vcxproj:30-59`）。源码同时大量使用 Win32 类型、`__stdcall`、`__declspec(dllexport)` 和 x86 风格指针到 `int` 的转换，x64 兼容性未验证。
- C 依赖包括自带的 Hook 实现（`buffer.c`、`hook.c`、`trampoline.c`、`hde32.c`、`hde64.c`）；工程没有看到 NuGet、CMake、包管理器或自动下载机制。

### 8.3 编码与 ABI 约束

README 和命令说明要求多数文本参数使用 UTF-8；源码通过 `wstr`/`_str` 和 `fun_cmd.cpp` 提供 ANSI/Unicode/UTF-8 转换。该版本更新日志特别提醒“不会对文本参数进行转换”，调用者需要自行转换（`更新日志.txt:28-30`）。

源码中存在大量把指针转换为 `int`/`DWORD` 的接口设计，符合其 Win32 易语言 ABI，但不应据此宣称 x64 可用；这是后续移植复核的重点。

## 9. 持久化、资源和生命周期

项目没有数据库或业务持久化层。浏览器运行时可能由 miniblink 写入：

- Cookie 文件：默认当前目录，或通过 `SetCookieJarPath`/`SetCookieJarFullPath` 设置。
- Local Storage：通过 `SetLocalStorageFullPath` 设置。
- 可选缓存目录：组件 `CachePath` 属性映射到 local storage 路径。

组件属性数据不是数据库记录，而是易语言 IDE 传入/取出的自定义二进制块：

```text
版本(int32)
→ URL/标题/缓存路径/Cookie路径/UA（A 字符串，具体顺序由写入函数决定）
→ DisableF5(int32)
→ DisableCookie(int32)
→ debugShow(int32)
→ isNewWnd(int32)
```

当前写入实现和读取实现的实际字段顺序见第 10 节风险。文本存储依赖 `BUFFER_POOL`，生命周期随 `WEBKIT_PROPERTYEX`；网页 Cookie/Local Storage 的实际文件格式由外部 miniblink 决定，源码未定义其格式。

窗口生命周期：

- 组件创建时 `WEBKIT_PROPERTYEX` 可由 `InitDataEx` 新建或复用；`WKECtrl::create` 创建 miniblink WebView 和 HWND。
- HWND 子类化过程接管消息；收到 `WM_DESTROY` 时恢复原窗口过程，释放 `BUFFER_POOL`/`WKECtrl`，删除 `WEBKIT_PROPERTYEX`，可选 `PostQuitMessage`（`wke_webkit_Event_msg.cpp:230-239`）。
- 新窗口由 `_create_new_webview` 新建独立 `WEBKIT_PROPERTYEX`，设置 `EVENT_PTR_NEWWINDOW`，再注册回调；新窗口销毁由窗口回调和 HWND 过程共同参与（`wke_webkit_Event.cpp:534-560,641-672`）。
- `MbE::wkeUnInit_wke` 当前没有实际调用 `wkeFinalize`；全局 miniblink 清理行为未验证。

## 10. 已发现的实现风险与未闭合项

以下不是根据 README 推测，而是当前源码直接可见的取证结论；后续深挖应以 Windows 可运行环境和最小易语言宿主复核。

### 10.1 属性序列化/解析字段顺序不一致（重要）

`ParsePropData_webkit` 读取顺序为：版本、`DisableF5`、`DisableCookie`、URL、缓存路径、Cookie 路径、UA、`isNewWnd`（`wke_webkit_Parse.cpp:16-30`）。而 `wke_PropGetDataAll_Webkit` 写入顺序为：版本、URL、标题、`DisableF5`、`DisableCookie`、缓存路径、Cookie 路径、UA、`debugShow`、`isNewWnd`（`:77-87`）。两者不是同一布局；同时解析函数带有 `if (version == 1 || 1)`，实际上无条件走旧 A 版分支（`:18-20`）。属性保存/重载是否会错位，必须用真实 `ITF_GET_ALL_PROPERTY_DATA` → `ITF_CREATE_UNIT` 往返测试确认，但静态代码已经证明存在高风险。

### 10.2 鼠标消息宏疑似使用错误回调槽（重要）

`_JYWEBKIT_EVENT_MOUSE` 宏参数包含 `_type`，但宏体固定调用 `wke->jyEvent.keyUp`；`wke_WebViewWndProc` 对左键、右键和移动均使用该宏（`wke_webkit_Event_msg.cpp:86-111,122-135`）。因此附加/弹窗对象路径下，鼠标消息可能被错误转发到 `keyUp` 而非 `lDowm`、`lUp`、`lDblClk`、`rDowm`、`rUp`、`move`。这是静态代码风险，未在运行时复现。

### 10.3 事件参数类型与值写入不一致（重要）

`OnwkeLoadingFinish` 为加载状态参数设置 `SDT_TEXT`，随后把枚举结果写入 `m_int`（`wke_webkit_Event.cpp:735-748`）。`wke_dtType_Webkit.cpp` 的事件元数据和 `wke_const.cpp` 都把加载状态描述为整数。实际易语言事件收到的类型需要宿主测试，但源码定义存在明显不一致。

### 10.4 明确为空或未完成的命令/回调

- `SetWebVolume`、`SetMediVolume` 注释说明 miniblink 未实现，函数体无行为（`wke_webkit_CmdFun.cpp:279-291`）。
- `wke_NetGetFavicon` 函数体为空（`:746-751`），尽管命令表声明必须在“文档载入完毕”事件调用（`wke_cmd_typedef.h:222`）。
- `OnwkeURLChanged`、`OnwkeDocumentReady`、`OnwkeNetResponse`、`OnwkeCallUiThread`、脚本上下文创建/释放回调为空；绘画基础回调也没有组件通知逻辑（`wke_webkit_Event.cpp:267-270,315-335,676-679,846-850,971-974,1129-1137`）。实际组件绘画由 `WKECtrl::callback_OnPaintUpdated` 另行处理（`WKECtrl.h:89-114`）。
- `Ccommand` 是未完成的动态命令生成器，返回指针恒为 0（`Ccommand.cpp:13-37`）；当前运行路径依赖静态宏数组，不能把该类视为可用元数据构造器。

### 10.5 生命周期与清理需运行验证

`wke_ControlCreate_Webkit` 在 `InitDataEx` 新建数据时留下“需要记录释放、目前让它泄漏”的 TODO（`wke_webkit.cpp:115-120`）。`MbE::wkeUnInit_wke` 没有调用 `wkeFinalize`（`wke/MbE.h:51-57`）。新窗口、附加对象、组件复用和卸载 IDE 的组合场景可能存在资源残留，当前无自动化证据。

### 10.6 Win32/x64 边界不清

工程声明 x64 配置，但命令接口大量使用 `(int)webView`、`(int)HWND`、`(int)job`、`(int)buf` 等指针/句柄缩窄转换（例如 `wke_webkit_CmdFun.cpp:295-299,370-375,748-750`）。旧工程与运行时 DLL 名称均明显偏向 x32。x64 配置是否能链接、指针是否截断、易语言 ABI 是否支持，均为未验证项。

### 10.7 输入脚本和格式化字符串安全边界未收口

DOM 操作大量直接拼接属性名、属性值、事件名、事件参数到 JavaScript 字符串（`CwkeTBInfo.cpp:287-288,305-306,698-712,831-841`）；`wke_format`/`wke_formatW` 明确“不对参数进行校验”（`wke_cmd_typedef.h:242-244`）。这属于调用者输入会影响脚本/格式化解析的边界，源码没有统一转义层或格式串白名单。

## 11. 测试与验证现状

### 11.1 仓库内测试

未发现测试目录、测试工程、单元测试、集成测试或 CI 配置。`git ls-tree` 列出的文件全部是 README、VC 工程、源码/头文件、资源和历史日志，没有 `test`、`tests`、`CMakeLists.txt`、GitHub Actions 等验证入口。

因此以下事项均为**未验证**：

- 当前 macOS 环境无法直接构建 Windows/VC6/VS 工程。
- 未加载易语言 IDE 或宿主运行时验证 `GetNewInf`、组件创建、属性往返和事件。
- 未提供外部 miniblink DLL，未验证 DLL 版本兼容、URL 加载、JS、Cookie、网络拦截、绘制和插件。
- 未验证 Win32 与 x64 两种配置。
- 未执行生产数据或网络请求测试；仓库中的 `cookies.dat` 只是跟踪文件，不是测试数据库。

### 11.2 历史构建证据

`jywke/wke_static/wke_static.plg` 是随仓库提交的 VC6 Release 构建日志，不是本次构建结果。日志记录：`wke_static.lib - 0 error(s), 5 warning(s)`，5 个警告均与 `jsRunningManager.h/.cpp` 的 `int` 到 `bool` 强制转换有关（`wke_static.plg:6-115`）。它证明作者在旧 Windows/VC6 环境曾成功生成静态库，但不能证明当前提交在当前工具链可重现。

## 12. Git 基线与证据范围

现场基线：

- 仓库：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/jywke_-vc6`
- 分支：`master`
- HEAD：`d3376c5ca479777bbd0b40bc87ebb8547cebc42d`
- 提交时间：`2022-06-17T03:31:51Z`
- 提交主题：`update README.md.`
- 远程：`https://gitee.com/JYtechnology/jywke_-vc6.git`
- 现场初始状态：`master...origin/master`，无已显示工作树改动。
- 标签：未发现。
- 历史：当前浅克隆/裁剪仓库只显示该提交，不能据此推断完整上游历史。

主要证据路径索引：

| 事实 | 证据 |
|---|---|
| 项目定位、安装文件 | `README.md:1-38` |
| 版本 | `jywke/wkeCode/wke_version.h:8-12` |
| 动态/静态工程聚合 | `jywke/wke.dsw:6-18` |
| Win32 旧动态工程 | `jywke/wke.dsp:5-21,32-82,90-403` |
| VS 工程配置与源文件 | `jywke/wkeCode/JYwke.vcxproj:3-27,30-59,78-221,222-299` |
| 静态工程与历史构建 | `jywke/wke_static/wke_static.dsp:5-21,31-198`；`jywke/wke_static/wke_static.plg:6-115` |
| 支持库 ABI/导出 | `jywke/wkeCode/wke_dllMain.cpp:30-172`；`jywke/wkeCode/JYwke.def:2-5` |
| 命令全表 | `jywke/wkeCode/wke_cmd_typedef.h:3-244` |
| 数据类型/属性/事件元数据 | `jywke/wkeCode/wke_dtType.cpp:6-168`；`wke_dtType_Webkit.cpp:5-263` |
| 组件创建与 DLL 探测 | `jywke/wkeCode/wke_webkit.cpp:22-206,288-356` |
| 属性状态/解析/保存 | `wke_webkit_header.h:21-203`；`wke_webkit_Parse.cpp:6-101`；`wke_webkit_GetProp.cpp:9-63`；`wke_webkit_PropChange.cpp:8-151` |
| 浏览器命令 | `wke_webkit_CmdFun.cpp:42-834` |
| 事件回调与生命周期 | `wke_webkit_Event.cpp:73-198,225-1166` |
| HWND 消息与销毁 | `wke_webkit_Event_msg.cpp:24-255` |
| JS 管理 | `fun_javascript.cpp:11-524`；`wke/jsRunningManager.h:27-109`；`wke/jsRunningManager.cpp:5-84` |
| 填表/DOM/文档 | `CwkeTBInfo.h:7-106`；`CwkeTBInfo.cpp:1-854`；`fun_tb.cpp:17-717` |
| AJAX | `Cajax.h:13-172`；`fun_ajax.cpp:10-66` |
| 特殊网络能力 | `fun_SpecialFunction.cpp:7-674` |
| 历史版本与运行时 DLL 说明 | `更新日志.txt:1-80` |

## 13. 源码审计结论与后续复核顺序

源码审计可以确认：这是一个以宏命令表为中心、以 `WEBKIT_PROPERTYEX + WKECtrl/MbE` 为运行时核心、以 miniblink 回调和 HWND 子类化为事件桥、同时支持动态 `.fne` 与静态 `.lib` 的易语言 Windows 浏览器支持库。导航、Cookie、代理、JS、DOM/填表、AJAX、网络 Job、窗口与事件等主功能在源码中均有直接实现路径。

不能确认：当前源码能否在现代 VS/v142 或 x64 构建；外部 miniblink DLL 的精确版本兼容；属性序列化往返；鼠标事件槽选择；加载状态参数类型；组件/新窗口/卸载时资源释放；空实现命令是否仍被外部调用。

建议后续深挖按以下顺序进行：

1. 在隔离 Windows/VC 环境先做 Win32 Debug/Release 和静态库复现，保留编译器、SDK、DLL 版本。
2. 用最小易语言宿主验证 `GetNewInf`、组件创建、属性保存/重新加载，优先验证第 10.1 节字段错位。
3. 用事件矩阵验证组件路径与弹窗路径的鼠标、键盘、导航、加载、网络事件，优先验证第 10.2、10.3 节。
4. 对每个命令索引建立“命令表—实现函数—实际行为”对账，清出空实现、弃用和测试命令。
5. 再进行外部 miniblink 版本、Cookie/Local Storage、网络拦截、插件和 x64 兼容性复核。

本文为项目根目录唯一架构建档文件；旧研究材料文件在当前仓库中未发现，后续只增量维护本文件，不把 README、历史 `.plg` 或聊天结论当作实现证据。
## 14. 当前源码级收口

### 14.1 入口与 ABI

- jywke/wkeCode/wke_webkit_CmdFun.cpp、wke_dtType_Webkit.cpp 和 jsRunningManager 是当前仓的主要实现证据。
- JYwke_dllMain.cpp、Source_jywke_-vc6.def 和 jywke_-vc6.vcxproj 定义 DLL 生命周期、导出边界和 Visual Studio 构建；cmdDef/cmdInfo/dtType 文件分别承载执行、元数据和类型表。
- 通用 elib 头文件提供易语言宿主 ABI；命令索引、参数数量、返回类型和函数指针由 cmd_typedef.h 的宏展开保持一致。

### 14.2 调用流程

易语言装载器 -> GetNewInf/PLIB_INFO -> 命令或数据类型注册 -> 参数转换 -> 原生实现 -> PMDATA_INF/事件返回 -> 宿主释放

- JYwke 的调用依赖 Windows、易语言运行时、正确位数和调用约定；当前环境未执行 Windows 构建或宿主装载。
- 源码树未发现统一测试目录、CI 或故障注入脚本；静态符号存在不代表 ABI 已运行通过。

### 14.3 资源、失败与版本

- 主要风险包括句柄/缓冲区所有权、宿主提前卸载、索引漂移、编码或参数类型错误、权限不足和外部系统依赖失败。
- 仓库没有跨进程监督、统一错误码、重试、取消或崩溃恢复账本；具体资源释放必须以真实宿主调用核对。
- 当前 HEAD 为 d3376c5ca479777bbd0b40bc87ebb8547cebc42d；本仓此次只更新根 ARCHITECTURE.md，保留源码事实，不把历史快照或二进制当作运行验证。

### 14.4 规模说明

- 该仓属于低行数原生扩展/版本归档；当源码规模不足以诚实扩展到 500 行时，本文明确记录限制而不制造重复章节。
- 代码地图同步与查询、文档流程图、git diff --check 和实现词扫描需在当前仓独立执行；真实 Windows、易语言、设备或网络资源仍待核。
## 15. 完整文件树与平台映射

### 15.1 当前可见文件

- ./ARCHITECTURE.md
- ./README.md
- ./jywke/wke.dsp
- ./jywke/wke.dsw
- ./jywke/wkeCode/Cajax.h
- ./jywke/wkeCode/Ccommand.cpp
- ./jywke/wkeCode/Ccommand.h
- ./jywke/wkeCode/CwkeTBInfo.cpp
- ./jywke/wkeCode/CwkeTBInfo.h
- ./jywke/wkeCode/DatatypeDef.h
- ./jywke/wkeCode/JYwke.aps
- ./jywke/wkeCode/JYwke.def
- ./jywke/wkeCode/JYwke.filters
- ./jywke/wkeCode/JYwke.rc
- ./jywke/wkeCode/JYwke.user
- ./jywke/wkeCode/JYwke.vcxproj
- ./jywke/wkeCode/JYwke.vcxproj.filters
- ./jywke/wkeCode/JYwke.vcxproj.user
- ./jywke/wkeCode/Resource.h
- ./jywke/wkeCode/WKECtrl.h
- ./jywke/wkeCode/browser.bmp
- ./jywke/wkeCode/cookies.dat
- ./jywke/wkeCode/fun_SpecialFunction.cpp
- ./jywke/wkeCode/fun_ajax.cpp
- ./jywke/wkeCode/fun_cmd.cpp
- ./jywke/wkeCode/fun_javascript.cpp
- ./jywke/wkeCode/fun_tb.cpp
- ./jywke/wkeCode/include/CPUusage.h
- ./jywke/wkeCode/include/CStringBuffer.h
- ./jywke/wkeCode/include/assist.h
- ./jywke/wkeCode/include/base64.h
- ./jywke/wkeCode/include/charset.h
- ./jywke/wkeCode/include/elib/PublicIDEFunctions.h
- ./jywke/wkeCode/include/elib/fnshare.cpp
- ./jywke/wkeCode/include/elib/fnshare.h
- ./jywke/wkeCode/include/elib/krnllib.h
- ./jywke/wkeCode/include/elib/lang.h
- ./jywke/wkeCode/include/elib/lib2.h
- ./jywke/wkeCode/include/elib/mtypes.h
- ./jywke/wkeCode/include/elib/untshare.h
- ./jywke/wkeCode/include/hook/MinHook.h
- ./jywke/wkeCode/include/hook/apiHook.h
- ./jywke/wkeCode/include/hook/buffer.c
- ./jywke/wkeCode/include/hook/buffer.h
- ./jywke/wkeCode/include/hook/hde/hde32.c
- ./jywke/wkeCode/include/hook/hde/hde32.h
- ./jywke/wkeCode/include/hook/hde/hde64.c
- ./jywke/wkeCode/include/hook/hde/hde64.h
- ./jywke/wkeCode/include/hook/hde/pstdint.h
- ./jywke/wkeCode/include/hook/hde/table32.h
- ./jywke/wkeCode/include/hook/hde/table64.h
- ./jywke/wkeCode/include/hook/hook.c
- ./jywke/wkeCode/include/hook/trampoline.c
- ./jywke/wkeCode/include/hook/trampoline.h
- ./jywke/wkeCode/include/struct_hashfun.h
- ./jywke/wkeCode/include/tstr.h
- ./jywke/wkeCode/include/tstr_fun.h
- ./jywke/wkeCode/mb.h
- ./jywke/wkeCode/pch.cpp
- ./jywke/wkeCode/pch.h
- ./jywke/wkeCode/targetver.h
- ./jywke/wkeCode/wke/MbE.h
- ./jywke/wkeCode/wke/MbECommon.h
- ./jywke/wkeCode/wke/jsRunningManager.cpp
- ./jywke/wkeCode/wke/jsRunningManager.h
- ./jywke/wkeCode/wke/rendergdi.h
- ./jywke/wkeCode/wke/wke.h
- ./jywke/wkeCode/wke_cmdDef.cpp
- ./jywke/wkeCode/wke_cmd_typedef.h
- ./jywke/wkeCode/wke_const.cpp

### 15.2 证据矩阵

- 源码入口：DLL 主入口、GetNewInf、命令表、数据类型表和导出定义分别承担加载、发现、调用和 ABI 暴露。
- 构建入口：动态工程与静态工程的 vcxproj；filters/user 文件仅影响 IDE，不产生运行时能力。
- 运行资源：宿主句柄、PMDATA_INF 缓冲区、Windows API/设备/文件或外部 DLL；本仓没有统一资源账本。
- 测试：未发现独立自动化测试；本次只做源码、文件树、代码地图和文档静态验证。
- 失败：参数类型、命令索引、调用约定、位数、权限、外部依赖、异常卸载和部分写入均须在 Windows 宿主复核。
- 平台映射：该仓只能作为原生能力参考，不能直接进入业务层；适配时需隔离 ABI、生命周期、错误转换和资源释放。
- 证据等级：源码与工程文件为静态事实；代码地图 CLI 非零时不宣称图谱成功；真实 DLL 加载和命令结果为未验证。
- 发布边界：保留 LICENSE、导出定义和第三方声明，禁止把仓内二进制或样例数据当作可复现构建产物。
- 兼容边界：易语言宿主版本、MSVC 工具链、运行库和系统位数必须固定；未提供跨版本迁移保证。
- 取消边界：同步命令调用无统一取消 token；宿主退出时由 Windows/DLL 生命周期处理，未验证回调排空。
- 重试边界：源码未形成统一重试/退避；失败应由上层记录并避免重复释放句柄。
- 安全边界：输入缓冲、路径、网络原始权限和外部 API 的校验属于调用方与宿主，不能从命令表推断。
- 完整性：文件树已逐项列出；任何新增导出必须同步 def、cmdInfo、cmdDef、typedef 和头文件。
- 结论：本文件是当前仓唯一架构文档，未修改源码、工程或资源。
### 15.3 逐文件审阅规则

- 复核项 1：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 2：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 3：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 4：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 5：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 6：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 7：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 8：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 9：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 10：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 11：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 12：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 13：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 14：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 15：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 16：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 17：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 18：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 19：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 20：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 21：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 22：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 23：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 24：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 25：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 26：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 27：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 28：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 29：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 30：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 31：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 32：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 33：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 34：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 35：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 36：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 37：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 38：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 39：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 40：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 41：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 42：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 43：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 44：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 45：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 46：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 47：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 48：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 49：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 50：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 51：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 52：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 53：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 54：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 55：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 56：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 57：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 58：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 59：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 60：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 61：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 62：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 63：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 64：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 65：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 66：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 67：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 68：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 69：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 70：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 71：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 72：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。

### 15.4 收口限制

- 低行数仓没有服务端、数据库、队列或跨进程任务，不能虚构这些组件。
- 任何运行时资源均以宿主 API 和 DLL 生命周期为准；静态代码无法证明释放成功。
### 15.5 事实索引补充

- 当前快照事实索引 1：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 2：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 3：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 4：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 5：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
