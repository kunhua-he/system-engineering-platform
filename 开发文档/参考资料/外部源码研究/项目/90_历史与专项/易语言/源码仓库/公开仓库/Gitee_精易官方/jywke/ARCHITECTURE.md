# jywke 架构建档

> 当前全量源码建档。本文是本仓库唯一架构事实源；结论按“源码已实现 / 仅声明或部分实现 / 未验证”区分。源码中的乱码注释不作为事实依据，优先以可执行代码、工程文件和符号引用为证据。

## 1. 项目定位

`jywke` 是“精易 Web 浏览器”易语言支持库源码，面向 Windows + 易语言 IDE/运行时，将 miniblink49 的 `wke` C API 封装成易语言支持库：

- 提供一个可视化 `精易Web浏览器` 窗口组件（数据类型英文名 `webkit`）；
- 通过 `GetNewInf()` 向易语言注册库元数据、命令、常量、复合数据类型、组件属性、组件事件和组件接口；
- 以 `wkeWebView` 为底层浏览器句柄，提供网页导航、Cookie、UA、代理、JS、DOM/表单填表、网络 Job 拦截、鼠标键盘模拟、弹窗和文件对话框事件等能力；
- 产物目标是易语言支持库文件 `wke.fne`，不是独立命令行程序或服务。

README 明确说明其基于 miniblink 开发；仓库工程和源码进一步确认依赖外部 `miniblink_4975_x32.dll` / `miniblink_4957_x32.dll` / `miniblink_4949_x32.dll` 或 `node.dll`。

## 2. 总体流程图

```text
易语言 IDE / 编译后程序
        │  加载 wke.fne，调用 GetNewInf / wke_ProcessNotifyLib
        ▼
jywke 支持库 ABI 层
  wke_dllMain.cpp + wke_cmd_typedef.h
  224 条命令元数据与 WKE_NAME(index,name) 函数表
        │  pArgInf / pRetData / NotifySys
        ├──────────────────────┬───────────────────────┬──────────────────────┐
        ▼                      ▼                       ▼                      ▼
webkit 组件适配层          JS / AJAX 命令层          填表与文档层           网络特殊功能层
wke_webkit*.cpp            fun_javascript.cpp        fun_tb.cpp             fun_SpecialFunction.cpp
属性/窗口/事件/生命周期     fun_ajax.cpp             CwkeTBInfo.cpp         wkeNet* / Job
        │                      │                       │                      │
        └───────────────┬──────┴───────────────┬───────┴───────────────┬──────┘
                        ▼                      ▼                       ▼
                 WKECtrl / MbE             jsValue/jsExecState       易语言复合数据
                 HWND + wkeWebView         miniblink JS API          RECT/MemBuf/PostElement
                        │
                        ▼
       wke.h 动态加载封装 ── LoadLibrary/GetProcAddress
                        │
                        ▼
       外部 miniblink49 DLL（不在当前源码工程中构建）
```

## 3. 版本与 Git 基线

| 项目 | 现场证据 |
|---|---|
| 本地分支 | `master` |
| 当前提交 | `bd3174d801d3b91fc84546cf616b7347d37ba4a4` |
| 提交时间 | `2022-09-12T21:59:48+08:00` |
| 提交主题 | `1.7.903更新说明` |
| 远程 | `https://gitee.com/JYtechnology/jywke.git` |
| 本地与远程 | `master...origin/master`，现场未见领先/落后 |
| 支持库版本宏 | `WKE_MAJORVERSION=1`、`WKE_MINORVERSION=7`、`WKE_BUILDVERSION=903` |
| 工程工具集 | Visual Studio `v143`，Windows SDK `10.0` |
| 工作树基线 | 建档前 `git status --short --branch` 仅显示分支信息，无源码修改 |

本仓库未发现既有 `ARCHITECTURE.md`，也未发现名称包含“细探”的既有细探材料文档；当前取证仅新增本文档，未删除任何文件。

## 4. 目录与工程地图

现场工作树共 103 个文件（不含 `.git` 内部文件）：根目录 5 个、`jywke/` 88 个、`testCallNode_Dll/` 10 个；另有两个源码/发布归档 ZIP。

```text
jywke/
├── JYwke.sln                         两个 Visual Studio 项目的解决方案
├── README.md                         项目说明与上游链接
├── VC6项目源码.zip                   旧 VC6/VS 源码归档，当前源码之外的历史材料
├── 易语言版支持库源码-2018-11-16.zip  易语言示例/成品归档，非当前构建输入
├── jywke/
│   ├── JYwke.vcxproj                 主项目，DynamicLibrary，目标名 wke.fne
│   ├── JYwke.def                     仅导出 GetNewInf
│   ├── wke_dllMain.cpp               DLL 入口、LIB_INFO、命令函数表、易语言通知入口
│   ├── wke_cmd_typedef.h             224 条命令的统一元数据宏 WKE_DEF
│   ├── wke_cmdDef.cpp                由 WKE_DEF 生成命令参数/命令描述数组
│   ├── wke_const.cpp                 常量元数据
│   ├── wke_dtType.cpp                10 类全局复合数据类型与方法索引
│   ├── wke_dtType_Webkit.cpp         webkit/newWindow 的方法、属性、事件描述
│   ├── wke_webkit*.cpp/.h             组件创建、属性序列化、事件和组件方法
│   ├── CwkeTBInfo.cpp/.h              iframe/DOM/表单/元素 JS 操作实现
│   ├── Cajax.h、fun_ajax.cpp          XMLHttpRequest 注入与回调
│   ├── fun_javascript.cpp             JS 值对象、执行状态、类型和回调转换
│   ├── fun_cmd.cpp                    非对象工具命令、编码、格式化、消息循环
│   ├── fun_tb.cpp                     WKE_填表命令转发
│   ├── fun_SpecialFunction.cpp        网络 Job、输入模拟、开发者工具等
│   ├── wke/                           MbE、WKECtrl 依赖的 miniblink 包装头和 JS 管理器
│   ├── include/elib/                  易语言支持库 ABI 头及公共函数
│   ├── include/hook/                  API Hook、trampoline、HDE32/HDE64、buffer
│   ├── include/tstr.h 等               字符串、编码、缓冲池、CPU 使用率辅助
│   ├── 易语言源码/例程/               9 个二进制易语言例程文件
│   ├── lib/wke.fne                    已随仓库提供的二进制支持库文件
│   └── 更新日志.txt                   版本与功能变更线索
└── testCallNode_Dll/
    ├── testCallNode_Dll.vcxproj       独立 Win32/x64 Application 工程
    └── testCallNode_Dll.cpp           手工创建 3 个 miniblink WebView 的内存/事件测试程序
```

主工程 `JYwke.vcxproj` 明确编译 22 个 `.cpp/.c` 单元，使用 `JYwke.def`，Release Win32 输出到硬编码的 `E:\易语言正式版\lib\wke.fne`，Debug Win32 后置复制到 `d:\e\lib\wke.fne`。x64 配置存在，但其目标名/输出文件没有像 Win32 一样完整设置，是否可直接产出可用支持库未验证。

## 5. 分层与模块职责

### 5.1 易语言 ABI 与注册层

**实现证据：** `jywke/wke_dllMain.cpp`、`jywke/wke_cmd_typedef.h`、`jywke/wke_cmdDef.cpp`、`jywke/wke_typedef.h`。

- `WKE_DEF` 是单一命令声明源：命令索引从 `0` 到 `223`，共 224 条，元数据与实现符号一一对应。
- `WKE_NAME(index,name)` 将索引、易语言英文名和 `__E_FNENAME` 拼成支持库 ABI 符号；`wke_dllMain.cpp` 用同一宏生成函数地址数组和静态编译命名数组。
- `s_libInfo` 注册 GUID `{6EC0A773-ABA1-49F4-AFD2-977EA30C0D4E}`、库名“精易Web浏览器”、2 个全局命令类别、数据类型表、常量表、命令表和 `wke_ProcessNotifyLib`。
- `JYwke.def` 只导出 `GetNewInf`；其余命令通过 `GetNewInf` 返回的函数表或静态编译命名机制被易语言使用。
- `GetNewInf()` 在返回库信息前调用 `head_dtType_Webkit(g_DataType_wke_global_var[4])` 和 `head_dtType_NewWnd(g_DataType_wke_global_var[9])`，动态填充组件和新窗口数据类型。
- `wke_ProcessNotifyLib()` 处理命令函数名、通知函数名、依赖库查询、系统通知和卸载通知；卸载时调用 `MbE::wkeUnInit_wke()`。该释放函数当前只检查初始化状态，真正 `wkeFinalize()` 被注释，属于资源风险。

### 5.2 浏览器组件、窗口与生命周期层

**实现证据：** `wke_webkit.cpp`、`wke_webkit_header.h`、`wke_head_base.h`、`WKECtrl.h`、`wke/MbE.h`。

- `WKE_STRUCT_BASE` 保存 `HWND`、父窗口、原窗口过程、易语言 `HUNIT`、窗体/单元 ID、设计模式标志和组件 flags。
- `MbE` 持有 `wkeWebView`、父窗口、`CRenderGDI` 和 `jsRunningManager`；`Create()` 调用 `wkeCreateWebWindow`，创建 JS 管理器和 GDI 渲染器，显示窗口并默认开启跨域、NPAPI、新窗口能力。
- `WKECtrl : MbE` 增加 `JYWEBKIT_EVENT` 回调槽和 `isDlg`，创建后绑定绘画回调并保证窗口类包含 `CS_DBLCLKS`。
- `wke_ControlCreate_Webkit()` 的真实主链是：初始化 miniblink → 通过窗体/单元 ID 获取或创建 `WEBKIT_PROPERTYEX` → 解析易语言属性数据 → 写入基础字段 → 创建 child HWND → 设置 UA/Cookie/缓存/LocalStorage/URL/新窗口选项 → 注册 miniblink 回调 → `NotifySys(NAS_CREATE_CWND_OBJECT_FROM_HWND)` 创建 `HUNIT` 并绑定数据。
- 设计模式与运行模式分流：运行模式设置运行路径、缓存/Cookie 目录并载入 URL；设计模式只在 `debugShow` 且有 URL 时预览，默认不会替用户打开任意网页。
- `InitDataEx()` 新建对象时 `clear()` + `init()`；重建时通过窗口属性发送关闭消息，但 `wke_ControlCreate_Webkit()` 注释明确承认存在已申请内存未记录、未释放的路径。
- `wke_SetDllPath()` 在易语言运行目录推导外部 DLL，按顺序检测 `miniblink_4975_x32.dll`、`miniblink_4957_x32.dll`、`miniblink_4949_x32.dll`、`node.dll`，成功后调用 `wkeSetWkeDllPath()`。

### 5.3 组件属性与持久化层

**实现证据：** `wke_dtType_Webkit.cpp`、`wke_webkit_Parse.cpp`、`wke_webkit_GetProp.cpp`、`wke_webkit_PropChange.cpp`。

组件定义 17 个属性：通用窗口属性 8 个（左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针）加浏览器属性 9 个（URL、网页标题、禁止 F5 刷新、禁止 Cookies、缓存目录、Cookie 目录、UserAgent、允许设计时预览、允许新窗口打开）。

属性数据模型 `WEBKIT_PROPERTY` 包含：

- ANSI/Wide URL、标题、缓存路径、Cookie 路径、UA；
- `DisableF5`、`DisableCookie`、`debugShow`、`isNewWnd`；
- 运行路径 `runPath`。

序列化格式在 `ParsePropData_webkit()` / `wke_PropGetDataAll_Webkit()` 中可直接确认：

```text
int32 version
int32 DisableF5
int32 DisableCookie
NUL 结尾 ANSI url
NUL 结尾 ANSI cachePath
NUL 结尾 ANSI cookiePath
NUL 结尾 ANSI userAgent
int32 isNewWnd
```

当前解析代码虽然读取 `version`，却使用 `if (version == 1 || 1)` 强制进入旧 ANSI 读取分支；Wide 属性读取分支仅保留为注释。写出版本使用 `WEBKIT_VERSION = 1.7.6.12` 的打包值，但写入内容仍是 ANSI 文本。属性返回使用 `GlobalAlloc(GMEM_MOVEABLE)`，调用方应承担对应释放责任；该边界未在本仓库测试确认。

属性修改行为已实现：URL 变更后跳转或载入空 HTML；新窗口开关作用于 `wkeSetNavigationToNewWindowEnable`；Cookie 开关作用于 `SetCookieEnabled`；缓存/Cookie 路径根据运行目录补全；UA 支持若干预置字符串并触发重载；设计时预览开关控制 URL 预览。标题属性为只读实时值，组件属性更新接口目前无禁用项，定制对话框接口直接返回 `FALSE`。

### 5.4 事件与 Windows 消息层

**实现证据：** `wke_webkit_Event.cpp`、`wke_webkit_Event_msg.cpp`、`wke_webkit_event.h`、`WKECtrl.h`。

`wke_dtType_Webkit.cpp` 定义 34 个组件事件；事件索引 0–33 覆盖文档就绪、标题/URL、导航、新窗口、加载、控制台、Alert/Confirm/Prompt、下载、网络开始/结束、鼠标链接、鼠标键盘滚轮、焦点、文件对话框和图标变化。

`__fill_wnd_data()` 当前显式绑定的 miniblink 回调为：

```text
wkeOnDocumentReady2       -> OnwkeDocumentReady2
wkeOnTitleChanged         -> OnwkeTitleChanged
wkeOnURLChanged2          -> OnwkeURLChanged2
wkeOnNavigation           -> OnwkeNavigation
wkeOnCreateView           -> OnwkeCreateView
wkeOnLoadingFinish        -> OnwkeLoadingFinish
wkeOnConsole              -> OnConsoleMessage
wkeOnAlertBox             -> OnwkeAlertBox
wkeOnConfirmBox           -> OnwkeConfirmBox
wkeOnPromptBox            -> OnwkePromptBox
wkeOnDownload             -> OnwkeDownload
wkeOnLoadUrlBegin         -> OnwkeLoadUrlBegin
wkeOnLoadUrlEnd           -> OnwkeLoadUrlEnd
wkeOnMouseOverUrlChanged  -> OnwkeMouseOverUrlChanged
wkeOnWindowClosing        -> handleWindowClosing
wkeOnWindowDestroy        -> handleWindowDestroy
```

回调在运行模式下构造 `EVENT_NOTIFY2`，填入窗体 ID、单元 ID、事件索引和参数，再调用 `NotifySys(NRS_EVENT_NOTIFY2)` 交给易语言；有返回值事件根据易语言返回的布尔值决定是否继续导航、下载、消息或对话框。`WM_LBUTTON*`、`WM_RBUTTON*`、`WM_MOUSEMOVE`、焦点、滚轮、字符、键盘消息由 `wke_WebViewWndProc` 转成组件事件；F5 是否放行由 `DisableF5` 参与判断。

文件打开/保存事件通过 `include/hook/apiHook.h` 的 API Hook 替换 `GetOpenFileNameW` / `GetSaveFileNameW`，使用全局 `g_wkeCtrl` 发送通知；该实现是进程级全局状态，不是每个 WebView 独立的事件上下文。

**仅声明或部分接入：** `wke_webkit_event.h`/`wke_webkit_Event.cpp` 还声明或实现了绘画位图、UI 线程、媒体、脚本上下文、网络响应等回调，但 `__fill_wnd_data()` 的当前注册列表未包含全部这些回调；不能仅凭函数存在就认定对应事件在运行时可达。`OnwkePaintUpdated` 另由 `WKECtrl::WKECtrl_OnPaint()` 绑定绘画更新路径。

### 5.5 WKE 浏览器命令层

**实现证据：** `wke_webkit_CmdFun.cpp`、`wke/MbE.h`、`wke_cmd_typedef.h`。

浏览器对象方法索引由 `s_dtCmdIndexiext_Webkit_static_var_04` 提供，共 35 个；`newWindow` 方法索引由 `s_dtCmdIndexiext_NewWindow_static_var_09` 提供，共 44 个，其中前置的是新窗口创建、复制、销毁、判断创建等操作，其余复用浏览器方法。

核心已实现命令族：

- 导航：浏览 URL、取 URL、载入 HTML/文件、前进、后退、停止、刷新、源码和网页文本；
- 会话：取/清 Cookie、Cookie 命令、UA、代理、WebView、窗口句柄、用户键值；
- 页面：加载状态、文档状态、截图、窗口创建/附加/销毁、消息循环；
- 新窗口：在 `OnwkeCreateView` 中根据易语言事件结果创建 `WKECtrl`，传回 `newWindow` 数据并转发窗口生命周期；
- 兼容/遗留：命令表保留若干隐藏、弃用或原封调用命令，例如 `wke_SetCookie` 运行时弹出弃用提示，建议使用 `wke_SetCookieCURL`。

`wke_webkit_CmdFun.cpp` 的具体实现多数是薄适配：通过 `WKE_CTRL` 从 `pArgInf` 获取 `WEBKIT_PROPERTYEX`，调用 `WKECtrl/MbE`，再用 `CloneTextData` 或 `m_dtDataType` 写回易语言返回值。

### 5.6 WKE_填表 / DOM / 表单层

**实现证据：** `fun_tb.cpp`、`CwkeTBInfo.cpp`、`CwkeTBInfo.h`。

`CwkeTBInfo` 是无持久化的操作上下文，主要字段为 `m_frameStr`、`m_framex`、`m_framey`。它将易语言选择器转换成 JS：

- `MODEL_JY`：把 `id==xxx class==yyy` 等精易模块式表达式转换为 `[id=xxx class=yyy]` 形式的 `querySelectorAll`；
- 其他模式：直接使用 CSS/JS 选择器；
- 下标从 1 开始，内部转为 0 基；
- iframe 通过递归 `document.querySelectorAll('iframe')` / `contentWindow` 构造 `m_frameStr`，并计算 iframe 偏移坐标。

已实现命令覆盖元素点击/焦点、属性读写/删除、checkbox/radio/combobox、表单数量/提交、标题/缩放/尺寸/滚动、编码/域名/选中文本/HTML、编辑模式、链接/图片地址、元素标记/显示隐藏/坐标/矩形/自定义事件/子元素数量等。

调用链为：

```text
易语言 WKE_填表 命令
  -> fun_tb.cpp 读取 WebView、模式、选择器、下标
  -> CwkeTBInfo::CreateElementSelectorStr / form_SetFrame
  -> 生成 JavaScript 字符串
  -> wkeRunJSW / jsEvalW
  -> jsToInt/jsToBoolean/jsToString 或 RECT
  -> pRetData / 易语言事件
```

风险：选择器、事件名、属性名和参数直接拼接进 JS 字符串，源码未见统一转义/参数化层；含引号、反斜杠或恶意输入时的行为未验证。

### 5.7 Javascript 值对象层

**实现证据：** `fun_javascript.cpp`、`wke/jsRunningManager.h/.cpp`、`wke/wke.h`。

该层通过 `jsValue` / `jsExecState` 的整数或 64 位整数承载 miniblink JS 不透明句柄，提供：

- JS 执行、指定 frame 执行、`eval`；
- 执行状态、类型判断、参数读取、结果转换；
- 全局对象/属性、全局函数/对象函数调用；
- 易语言子程序绑定到 JS 函数；
- JS 值的 Number/String/Boolean/Object/Function/Undefined/Null/Array 判断。

`jsRunningManager` 还实现 JS 值到 `ValueType` 的转换和函数调用参数构造。`wke_RunJsToStr` 在实现中只设置文本返回类型并置空，命令表同时标记为已废弃，因此不能把该命令当作完整 JS 执行路径；应使用当前的值对象/表达式命令并自行转换。

### 5.8 AJAX 层

**实现证据：** `Cajax.h`、`fun_ajax.cpp`。

`Cajax` 只保存一次请求使用的 `_header` 字符串。`Get()` / `Post()` 生成一段注入网页的 `XMLHttpRequest`：

```text
xhr.open(method, url, true)
设置请求头
onreadystatechange -> readyState == 4
  status 200/304 -> ajaxFun(responseText)
  其他 -> ajaxFun(status)
xhr.send(data)
```

`jsFun()` 为 miniblink 创建 `jsData` 函数对象，把 `ajaxFun` 和回调地址写入 JS 全局变量，最终通过 `ajax_get` / `ajax_post` 从 JS 回调易语言子程序。请求完成后清空 `_header`。初始化/销毁已实现；`AJAXCopy` 函数体为空，属于声明和元数据存在但赋值语义未实现。

### 5.9 特殊网络与输入层

**实现证据：** `fun_SpecialFunction.cpp`、`wke_webkit_Event.cpp`、`wke/wke.h`。

已实现的 API 适配包含 NPAPI、无头/爬虫模式、Cookie/CSP 开关、网络请求 Hook、HTTP 头/MIME/URL/响应数据修改、触屏/鼠标开关、DevTool、主 frame、frame URL、鼠标键盘消息、取消请求、请求/响应头读取、POST、挂起/继续 Job、调试配置。

POST 数据模型：

- `POST元素`：`size`、元素 `type`、`MemBuf` 数据、文件路径、文件起始位置、文件长度；
- `POST元素集`：元素数组、数量、`isDirty`、原始数据字段；
- 对应复合类型在 `wke_dtType.cpp` 中注册，部分“创建/释放 POST 数据”命令在 `fun_SpecialFunction.cpp` 中保留 `UNDONE`，不可认定为完整生命周期实现。

## 6. 数据模型与资源边界

| 模型 | 源码位置 | 生命周期/存储 |
|---|---|---|
| `WKE_STRUCT_BASE` | `wke_head_base.h` | 每个组件实例的内存对象，保存 HWND/HUNIT/ID/flags |
| `WEBKIT_PROPERTY` | `wke_webkit_header.h` | 组件属性，文本由 `BUFFER_POOL` 管理，无数据库 |
| `WEBKIT_PROPERTYEX` | `wke_webkit_header.h` | 继承基础结构，组合 `WEBKIT_PROPERTY`、`BUFFER_POOL`、`WKECtrl*` |
| `WKECtrl` / `MbE` | `WKECtrl.h` / `wke/MbE.h` | 浏览器窗口、WebView、GDI 渲染器、JS 管理器 |
| `CwkeTBInfo` | `CwkeTBInfo.h/.cpp` | 易语言复合变量指向的临时选择器/frame 上下文 |
| `Cajax` | `Cajax.h` | 易语言复合变量指向的临时请求头和 JS 回调状态 |
| `jsValue` / `jsExecState` | `wke/wke.h` | 外部 miniblink JS 引擎句柄，易语言侧以整数/长整数传递 |
| `RECT` | `wke_dtType.cpp` | 元素矩形返回值，6 个整数成员 |
| `MemBuf` | `wke_dtType.cpp` | 结构大小、数据指针、数据长度 |
| `POSTELEMENT(S)` | `wke_dtType.cpp` | 网络 POST 构造/读取的复合数据 |

持久化只来自外部 miniblink：Cookie 文件、LocalStorage/缓存目录由组件属性和 `MbE` 调用配置。当前仓库没有数据库、配置服务、HTTP 服务、队列或本地 JSON/SQLite 数据层。`jywke/lib/wke.fne` 是已存在的二进制成品，不是源码持久化数据。

## 7. 外部接口与依赖

### 7.1 易语言支持库接口

- 导出入口：`GetNewInf()`（`JYwke.def`）；
- 通知入口：`wke_ProcessNotifyLib(INT,DWORD,DWORD)`；
- 命令 ABI：224 个 `WKE_NAME(index,name)` 函数，统一参数 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`；
- 组件接口：`wke_GetInterface_webkit()` 返回创建、属性读写、接口询问、通知接收者等函数；
- 系统通知：`NotifySys()` / `ProcessNotifyLib()` / `NRS_EVENT_NOTIFY2` / `NAS_*`，来自易语言 `elib` ABI。

### 7.2 miniblink / Windows 接口

- `wke/wke.h`：miniblink C API 声明及动态加载入口；
- `wkeSetWkeDllPath`、`wkeInitializeEx`、`wkeCreateWebWindow`、`wkeLoadURL(W)`、`wkeRunJS(W)`、`wkeOn*`、`wkeNet*`、`js*` 等；
- Windows HWND、窗口过程、消息循环、GDI、COM/系统库；
- `Shlwapi.dll!PathFileExistsW` 动态加载；
- Hook 代码使用 Windows API Hook、trampoline 和 HDE32/HDE64。

### 7.3 工程链接依赖

主工程 Debug/Release Win32 列出 `kernel32.lib;user32.lib;gdi32.lib;winspool.lib;comdlg32.lib;advapi32.lib;shell32.lib;ole32.lib;oleaut32.lib;uuid.lib;odbc32.lib`，并包含项目内 `include/elib`、`include/hook`、`wke` 头文件。项目没有 NuGet、npm、Composer、Python 或 CMake 依赖声明。

## 8. 测试、示例与验证状态

### 已确认存在

- `testCallNode_Dll/testCallNode_Dll.cpp` 是独立 Win32 手工测试程序：设置 `E:\易语言正式版\node.dll`，调用 `wkeInit()`，创建 3 个 `WKE_WINDOW_TYPE_CONTROL` WebView，注册 URL 回调，加载网页，支持定时刷新、UA、消息循环、异常 MiniDump 和 `wkeFinalize()`。
- `jywke/易语言源码/例程/` 有 9 个 `.e` 文件：`test.e`、`jingyiWeb.e`、`挂接所有事件.e`、`新窗口打开.e`、`手动创建窗口.e`、`截图.e`、`触发tab键.e`、`挂机测试.e`、`url载入结束触发例子.e`。
- `VC6项目源码.zip` 内含较早版本 `wkeCode/` 源码和 `wke.dsp/.dsw`，是历史参考，不是当前工程输入。
- `易语言版支持库源码-2018-11-16.zip` 含旧版 `JinyiWeb.e`、`wke.dll` 等成品/源码材料，不能替代当前版本证据。

### 未执行/未验证

- 当前主机为 macOS，不能直接执行 Windows Visual Studio `v143` 工程；当前取证遵守只改架构文档约束，没有启动构建、安装依赖、运行 DLL、运行易语言 IDE 或运行示例。
- 未验证 Win32 Debug/Release 产物能否在目标 Windows 环境完整链接；未验证 x64 配置是否可产出可加载的易语言支持库。
- 未验证外部 miniblink DLL 版本、位数、导出符号、Cookie/缓存路径权限和实际事件可达性。
- 未验证 `GetNewInf` 返回的命令数量、属性序列化在真实易语言 IDE 中的兼容性；命令表与函数符号已通过源码静态盘点确认。
- 未验证 JS、AJAX、DOM 选择器在真实网页上的跨域、编码、异常、线程和内存行为。

## 9. 已实现 / 仅声明或部分实现 / 未验证清单

### 源码已实现（静态证据充分）

1. DLL 入口、`GetNewInf`、`LIB_INFO`、命令函数数组和易语言通知入口。
2. 224 条命令元数据，且当前源码存在对应 `WKE_NAME` 实现符号：`wke_webkit_CmdFun.cpp` 45、`fun_cmd.cpp` 16、`fun_ajax.cpp` 6、`fun_javascript.cpp` 47、`fun_tb.cpp` 65、`fun_SpecialFunction.cpp` 45。
3. 10 个全局复合数据类型注册，webkit 的 35 个方法、17 个属性、34 个事件以及 newWindow 方法索引填充。
4. WebView 创建、属性解析/读写/序列化、URL/UA/Cookie/路径配置和窗口句柄绑定。
5. 主要网页回调、易语言事件投递、Windows 鼠标键盘消息转发和打开文件 API Hook。
6. DOM/iframe/表单 JS 操作、JS 值对象基础转换、XHR GET/POST 注入、网络 Job 基础操作。

### 仅声明或部分实现（源码明确显示）

1. `AJAXCopy` 空函数；`JSIntialize`/`JSCopy`/`JSDestroy` 空函数；`NETIntialize`/`NETCopy`/`NETDestroy` 空函数。
2. `wke_RunJsToStr` 标记为弃用且当前实现返回空文本。
3. `wke_SetCookie` 标记弃用并弹窗返回，不执行原注释中的 Cookie 设置逻辑。
4. POST 数据创建/释放命令在源码中带 `UNDONE`，不能视为完整实现。
5. `Ccommand` 的 `AddCmd`、`AddArg`、`GetCmdPtr`、`GetCmdArgPtr` 只维护长度或返回空指针，且仓库内未发现其被主工程引用。
6. `MbE::wkeUnInit_wke()` 没有真正调用 `wkeFinalize()`；组件数据泄漏 TODO 仍在源码中。
7. 事件文件中有多个回调实现，但并未全部在 `__fill_wnd_data()` 注册；事件元数据存在不等于运行时一定触发。
8. `wke_webkit_Parse.cpp` 强制使用 ANSI 分支，版本判断中的 `|| 1` 表明 Wide 属性分支尚未启用。

### 未验证（不能由静态源码推出）

- Windows 真实加载/构建/运行结果；
- 外部 DLL 的实际 miniblink 版本和 API 兼容性；
- 支持库卸载、窗口重建、新窗口销毁、全局文件对话框 Hook 的资源释放；
- 真实网络、跨域、Cookie、代理、POST、AJAX 回调和多线程行为；
- x64 产物及易语言静态编译兼容性。

## 10. 风险与后续复核点

1. **资源释放：** `WEBKIT_PROPERTYEX`、`WKECtrl`、`CwkeTBInfo`、JS 数据、GlobalAlloc 属性块、Hook 和 WebView 的所有权分散；重点复核重复创建、新窗口关闭、易语言 IDE 卸载和异常路径。
2. **全局状态：** `g_wkeCtrl`、文件对话框 Hook 和 `isInit` 为进程级状态，多组件/多线程/多窗口边界需要在 Windows 真实运行中验证。
3. **字符串与注入：** DOM 选择器、属性、事件参数、AJAX URL/数据直接拼接 JavaScript；需补充转义、空指针、引号和跨域异常测试。
4. **ABI/位数：** 源码主要以 `DWORD`、`int` 承载 HWND、函数指针、WebView、JSValue；x64 工程虽声明存在，实际 ABI 安全性未确认。
5. **编码：** 文档和源码以 GBK/ANSI 注释与 UTF-8/Unicode API 混用，属性写出仍为 ANSI；需在真实易语言版本中验证中文 URL、UA、标题、Cookie 和返回值。
6. **配置路径：** 工程含 `d:\e\lib`、`E:\易语言正式版\lib`、`E:\易语言正式版\node.dll` 等开发机硬编码；发布目录、DLL 位数和命名约定需单独形成部署契约。
7. **文档与实现漂移：** README 只描述项目定位，更新日志包含历史行为和弃用说明；后续维护必须以源码和实测结果更新本文，不把 ZIP 内旧版本当作当前实现。

## 11. 证据索引

### 注册、命令与版本

- `jywke/wke_dllMain.cpp:13-28`：`DllMain`；`:34-114`：命令表、`LIB_INFO`、`GetNewInf`；`:132-173`：易语言通知。
- `jywke/wke_cmd_typedef.h:3-12`：ABI 名称拼接与 `WKE_DEF`；`:13-236`：224 条命令元数据。
- `jywke/wke_cmdDef.cpp`：命令参数/描述数组生成。
- `jywke/wke_version.h:8-12`：`1.7.903` 版本宏。
- `jywke/JYwke.def:2-5`：导出 `GetNewInf`。

### 组件、属性与事件

- `jywke/wke_webkit.cpp:23-86`：组件接口分派；`:89-215`：初始化与创建；`:296-364`：外部 DLL 路径。
- `jywke/wke_webkit_header.h:33-157`：属性结构、缓冲池、路径与对象绑定。
- `jywke/wke_webkit_Parse.cpp:6-98`：属性解析和全量序列化。
- `jywke/wke_webkit_GetProp.cpp:8-63`：属性读取。
- `jywke/wke_webkit_PropChange.cpp:8-151`：属性修改。
- `jywke/wke_dtType_Webkit.cpp:4-58`：webkit/newWindow 方法索引和 17 个属性；`:61-226`：事件参数与 34 个事件；`:228-263`：数据类型填充。
- `jywke/wke_webkit_Event.cpp:72-93`：事件投递；`:109-198`：回调初始化/文件对话框 Hook；`:1141-1166`：回调注册。
- `jywke/wke_webkit_Event_msg.cpp:117-263`：窗口消息到事件回调。

### 核心功能

- `jywke/wke/MbE.h:8-305`：WebView、窗口、导航、Cookie、代理、JS 和渲染包装。
- `jywke/WKECtrl.h:5-119`：易语言组件控制器与绘画回调。
- `jywke/CwkeTBInfo.cpp:21-854`：JS/iframe/DOM/表单/元素操作。
- `jywke/fun_tb.cpp`：WKE_填表命令转发。
- `jywke/fun_javascript.cpp`、`jywke/wke/jsRunningManager.h/.cpp`：JS 值与执行状态。
- `jywke/Cajax.h:13-174`、`jywke/fun_ajax.cpp:8-62`：XHR 注入与回调。
- `jywke/fun_SpecialFunction.cpp`：网络 Job、POST、输入和调试命令。
- `jywke/include/hook/apiHook.h`、`buffer.c`、`trampoline.c`、`hde/`：Hook 基础设施。

### 工程、示例与测试

- `JYwke.sln:6-8`：主 DLL 与测试应用两个项目；`:11-33`：Win32/x64 Debug/Release 映射。
- `jywke/JYwke.vcxproj:30-221`：配置、输出路径、编译/链接依赖；`:222-297`：源码文件清单。
- `testCallNode_Dll/testCallNode_Dll.vcxproj`：测试应用的四配置工程。
- `testCallNode_Dll/testCallNode_Dll.cpp:63-147`、`:217-303`：3 个 WebView、消息循环、URL/UA/定时和销毁测试。
- `jywke/更新日志.txt:1-80`：1.7.903、1.7.620、1.7.616 和历史功能线索。
- `jywke/易语言源码/例程/`：9 个易语言二进制例程；当前取证未运行。
- `README.md:5-24`：miniblink 项目定位和上游链接。

## 12. 规模与证据边界

仓库共有 103 个跟踪文件，主体是 `jywke/` 下的 WebKit/miniblink 封装、MinHook 代码、易语言 ABI 头文件及一个调用测试工程；没有可在当前 macOS 主机直接运行的 Windows 构建产物。源码链路可按以下顺序复核：`wke_dllMain.cpp` 注册导出，`wke_cmdDef.cpp`/`wke_cmd_typedef.h` 绑定命令，`wke_webkit*.cpp` 调用 WebKit，`fun_*.cpp` 实现易语言侧功能，`testCallNode_Dll.cpp` 驱动窗口与消息循环。

资源与失败边界包括浏览器实例销毁、消息循环退出、Hook trampoline 释放、网络/脚本回调异常和 GDI 位图清理。现有测试工程只覆盖显式调用样例，未证明多实例并发、跨线程回调、崩溃恢复或 ABI 版本兼容。后续补证应固定 miniblink 二进制版本、运行时 DLL 路径和 Win32/x64 配置，并记录每个实例的创建/销毁配对。
