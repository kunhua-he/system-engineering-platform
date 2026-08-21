# htmlview 架构建档

> 当前全量架构建档，基于本地源码现场人工读取形成。本文是本项目根目录唯一架构事实文档；后续核查应直接更新本文件，不另建平行架构结论。
>
> 状态标记约定：
> - **源码已实现**：源码中存在可直接确认的实现、元数据或导出路径。
> - **仅声明**：有接口/命令/元数据声明，但当前仓库没有足够执行逻辑证明已完成。
> - **未验证**：需要 Windows、Visual Studio、易语言运行环境或真实宿主才能确认，当前未执行。

## 1. 项目定位

`htmlview` 是 Gitee `JYtechnology/htmlview` 仓库中的易语言支持库工程，目标是向易语言 IDE/运行时注册一个 Windows 超文本浏览框组件 `HtmlViewer`，并提供与浏览器组件相关的命令、属性、事件和对象接口。

从仓库当前源码看，它更接近“易语言支持库接口骨架/模板化实现”而不是可独立运行的 HTML 浏览器内核：

- 支持库 DLL 的注册入口 `GetNewInf` 已实现，能返回 `LIB_INFO` 元数据。
- `HtmlViewer` 自定义数据类型、属性、事件、接口回调及命令目录已声明。
- `Execute`、`Navigate`、`HttpPost` 等命令的参数签名已生成，但命令函数体没有浏览器调用逻辑。
- `htmlview_ControlCreate_HtmlViewer` 明确保留 `TODO`，返回 `HUNIT hUnit = 0`；因此当前代码不能据此证明真实浏览器窗口已创建。
- 仓库没有 README、测试目录、浏览器 COM 封装实现、资源文件或第三方浏览器依赖声明。

**结论**：项目定位为 Windows/易语言支持库的 `HtmlViewer` 组件声明与接入骨架；“浏览器功能已可运行”在当前仓库证据下属于未验证，部分核心行为明确尚未实现。

## 2. 当前架构流程图

```text
易语言 IDE / 编译运行时
        │
        │ LoadLibrary + 固定导出名 GetNewInf
        ▼
htmlview.dll（htmlview.vcxproj，DynamicLibrary）
        │
        ├─ GetNewInf()
        │      └─ 返回 g_LibInfo_htmlview_global_var
        │             ├─ 库版本/GUID/系统版本要求/作者信息
        │             ├─ g_DataType_htmlview_global_var
        │             │      └─ HtmlViewer / 超文本浏览框
        │             │             ├─ 成员命令索引 0..12
        │             │             ├─ 固定属性 + Windows 专用属性
        │             │             ├─ 10 个事件及事件参数
        │             │             └─ htmlview_GetInterface_HtmlViewer
        │             ├─ g_cmdInfo_htmlview_global_var
        │             │      └─ 13 条命令元数据（含 5 条隐藏占位命令）
        │             ├─ g_cmdInfo_htmlview_global_var_fun
        │             │      └─ 13 个 htmlview_* 命令函数指针
        │             └─ g_ConstInfo_htmlview_global_var
        │                    └─ 10 个浏览器操作常量 0..9
        │
        ├─ 系统通知 htmlview_ProcessNotifyLib_htmlview
        │      └─ NL_SYS_NOTIFY_FUNCTION
        │             └─ ProcessNotifyLib → fnshare.cpp 保存宿主通知函数
        │
        ├─ 组件生命周期（当前主要是接口分发）
        │      ├─ ITF_CREATE_UNIT → htmlview_ControlCreate_HtmlViewer
        │      │      └─ 当前 TODO，返回 0（未创建真实窗口）
        │      ├─ ITF_PROPERTY_* → 属性更新/读写回调
        │      ├─ ITF_IS_NEED_THIS_KEY → 按键询问
        │      └─ ITF_GET_NOTIFY_RECEIVER → 设计器尺寸通知
        │
        └─ 命令执行入口（签名已声明，业务逻辑未落地）
               ├─ Execute → 当前仅读取 arg1
               ├─ Navigate → 当前仅读取 3 个文本参数
               ├─ HttpPost → 当前仅读取 URL/字节集/请求头
               └─ GetType/GetBusy/IsReady/GetBrowser/GetDocument
                      当前没有填充返回值或调用浏览器对象
```

## 3. 工程与真实目录地图

仓库在当前提交中共 23 个 Git 跟踪文件，根目录没有 README、AGENTS.md、测试文件、细探文档或既有 `ARCHITECTURE.md`。真实结构如下：

```text
htmlview/
├── htmlview.sln                         # VS 解决方案，含 DLL 与静态库两个项目
├── htmlview.vcxproj                     # htmlview 动态库工程
├── htmlview.vcxproj.filters             # VS 文件筛选器
├── htmlview.vcxproj.user                # 空用户工程设置
├── htmlview_static/
│   ├── htmlview_static.vcxproj          # htmlview 静态库工程
│   ├── htmlview_static.vcxproj.filters
│   └── htmlview_static.vcxproj.user     # 空用户工程设置
├── Source_htmlview.def                  # DLL 导出定义，仅导出 GetNewInf
├── include_htmlview_header.h            # 统一包含与命令函数前置声明
├── htmlview_cmd_typedef.h               # HTMLVIEW_DEF 命令单一事实宏
├── htmlview_cmdDef.cpp                  # 13 个命令函数骨架
├── htmlview_cmdInfo.cpp                 # 参数表与命令元数据表
├── htmlview_const.cpp                   # 浏览器命令常量表
├── htmlview_dllMain.cpp                 # DLL 入口、库信息、系统通知
├── htmlview_dtType.cpp                  # HtmlViewer 数据类型、属性、事件、组件回调
└── elib/
    ├── fnshare.cpp                      # 易语言宿主通知转发与内存/调试辅助
    ├── fnshare.h                        # 通知、内存、数组和数据类型辅助声明
    ├── lib2.h                           # 支持库 ABI、元数据和运行时数据结构
    ├── lang.h                           # GBK/英语/BIG5/SJIS 语言版本宏
    ├── krnllib.h                        # 核心支持库版本/GUID/组件类型常量
    ├── mtypes.h                         # Windows/基础 C 类型兼容定义
    ├── untshare.h                        # 窗口组件公共辅助定义
    └── PublicIDEFunctions.h             # 易语言 IDE 功能编号与公共数据结构
```

### 3.1 解决方案组成

`htmlview.sln:5-7` 注册两个 Visual Studio C++ 项目：

| 项目 | 工程类型 | 作用 | 证据 |
|---|---|---|---|
| `htmlview` | `DynamicLibrary` | 生成支持库 DLL，Win32 配置目标扩展为 `.fne` | `htmlview.vcxproj:22-28,51-76,95-107` |
| `htmlview_static` | `StaticLibrary` | 复用同一批源码，供静态库路径使用 | `htmlview_static/htmlview_static.vcxproj:21-38,48-72` |

解决方案配置包含 `Debug/Release` 与 `Win32/x64` 四种组合；Win32 配置在解决方案中映射到 `Win32`，x64 配置映射到 `x64`（`htmlview.sln:10-32`）。两个工程均使用 `v141` 工具集，目标 Windows SDK 为 `10.0.15063.0`（动态工程 `htmlview.vcxproj:43-49`；静态工程 `htmlview_static/htmlview_static.vcxproj:40-45`）。

### 3.2 编译输入与条件编译

动态工程编译 6 个 `.cpp`：`elib/fnshare.cpp`、`htmlview_cmdDef.cpp`、`htmlview_const.cpp`、`htmlview_dllMain.cpp`、`htmlview_dtType.cpp`、`htmlview_cmdInfo.cpp`（`htmlview.vcxproj:21-28`）。静态工程通过 `..\` 路径复用相同 6 个源文件（`htmlview_static/htmlview_static.vcxproj:21-27`）。

- 动态工程定义 `HTMLVIEW_EXPORTS`、`_USRDLL`、`_WINDOWS`，Win32 还定义 `__E_FNENAME=htmlview`（`htmlview.vcxproj:109-125,132-152`）。
- 静态工程 Debug/Release Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=htmlview`；但其 x64 配置的定义仅显示 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有在工程文件中看到 `__E_STATIC_LIB` 与 `__E_FNENAME=htmlview`（`htmlview_static/htmlview_static.vcxproj:130-154`）。这只是工程配置事实，是否为历史模板遗漏及是否影响 x64 构建，当前未验证。
- 头文件中通过 `#ifndef __E_STATIC_LIB` 控制 DLL 元数据数组和 `DllMain` 等内容（`include_htmlview_header.h:11-20`、`htmlview_dllMain.cpp:6-29`、`htmlview_dtType.cpp:43-127`）。

## 4. 模块职责与依赖方向

### 4.1 业务/适配模块

| 模块 | 主要职责 | 当前状态 | 关键证据 |
|---|---|---|---|
| `htmlview_cmd_typedef.h` | 以 `HTMLVIEW_DEF(_MAKE)` 一次性声明命令编号、中文名、英文名、说明、返回类型、参数数量和参数表起点 | **源码已实现（元数据声明）** | `htmlview_cmd_typedef.h:3-25` |
| `htmlview_cmdDef.cpp` | 暴露每条命令的 `PFN_EXECUTE_CMD` 兼容函数 | **仅声明/骨架**；函数体未执行业务 | `htmlview_cmdDef.cpp:5-108` |
| `htmlview_cmdInfo.cpp` | 参数描述数组 `ARG_INFO`、命令描述数组 `CMD_INFO` 及数量 | **源码已实现（编辑期元数据）** | `htmlview_cmdInfo.cpp:5-46` |
| `htmlview_const.cpp` | 生成前进、后退、首页、搜索页、刷新、停止、另存为、打印、打印预览、页面设置 10 个数值常量 | **源码已实现（常量声明）** | `htmlview_const.cpp:3-28` |
| `htmlview_dtType.cpp` | 声明 `HtmlViewer` 数据类型、属性、事件，分发组件接口并提供组件回调 | **元数据已实现；运行组件仅部分骨架** | `htmlview_dtType.cpp:43-125,129-193,195-308` |
| `htmlview_dllMain.cpp` | DLL 生命周期、支持库信息、命令函数指针表、系统通知入口、静态编译名称查询 | **源码已实现（接入壳）；浏览器行为未实现** | `htmlview_dllMain.cpp:7-100,101-178` |
| `elib/fnshare.cpp/.h` | 保存宿主的 `PFN_NOTIFY_SYS`，向宿主转发通知，查询运行版本，提供用户通知回调 | **源码已实现（通用接入辅助）** | `elib/fnshare.cpp:7-71`、`elib/fnshare.h:20-55` |

### 4.2 公共 ABI/SDK 模块

`elib` 不是本项目独立业务层，而是随仓库拷贝的易语言支持库 SDK/兼容头：

- `elib/lib2.h` 定义 `ARG_INFO`、`CMD_INFO`、`EVENT_INFO2`、`UNIT_PROPERTY`、`LIB_DATA_TYPE_INFO`、`MDATA_INF`、`LIB_INFO` 以及 `PFN_EXECUTE_CMD`、`PFN_NOTIFY_LIB` 等 ABI 类型（`elib/lib2.h:266-364,409-522,693-729,780-824,1229-1318`）。
- `elib/mtypes.h` 提供 `INT`、`DWORD`、`HWND`、`HGLOBAL`、`RECT` 等基础兼容类型和宏（`elib/mtypes.h:4-59,61-106`）。
- `elib/krnllib.h` 提供 `DTC_HTML_VIEWER=35`、核心库 GUID、核心支持库版本 4.5 等常量（`elib/krnllib.h:6-56,114-131`）。
- `elib/lang.h` 固定 `__COMPILE_LANG_VER` 为 `__GBK_LANG_VER`（`elib/lang.h:6-14`）。
- `elib/untshare.h` 和 `elib/PublicIDEFunctions.h` 提供组件/IDE 公共辅助定义；在当前 htmlview 源码中没有发现实际 HTML/COM 实现被这些头文件补齐的证据。

依赖方向可以概括为：

```text
htmlview_cmdDef.cpp / cmdInfo / const / dtType / dllMain
                         │
                         ▼
             include_htmlview_header.h
                         │
                         ├─ htmlview_cmd_typedef.h
                         └─ elib/lib2.h + lang.h + krnllib.h
                                      │
                                      ├─ mtypes.h（基础类型）
                                      ├─ fnshare.h/cpp（宿主通知辅助）
                                      ├─ untshare.h（组件辅助）
                                      └─ PublicIDEFunctions.h（IDE 编号/结构）
```

## 5. 核心数据模型与元数据

本项目没有数据库、文件存储或持久化领域模型。核心“数据模型”是编译进支持库的静态 ABI 描述表和宿主传入的运行时数据结构。

### 5.1 支持库级 `LIB_INFO`

`htmlview_dllMain.cpp:31-87` 构造 `g_LibInfo_htmlview_global_var`：

| 字段 | 当前值/含义 | 状态 |
|---|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（`20000101`） | **源码已实现** |
| `m_szGuid` | `5014D8FA6DCA40b68FA626D8183666EB` | **源码已实现** |
| 版本 | 主 `2`、次 `2`、构建 `1` | **源码已实现** |
| 系统要求 | 易语言系统 `3.0`；核心支持库 `3.0` | **源码已实现（声明）** |
| 名称/说明 | `超文本浏览框支持库` / `本支持库实现了对超文本浏览框窗口组件的支持。` | **源码已实现（声明）** |
| OS 状态 | `_LIB_OS(OS_ALL)` | **源码已实现（声明）**；实际平台可用性未验证 |
| 语言 | `__GBK_LANG_VER` | **源码已实现** |
| 作者联系信息 | `大有吴涛易语言软件公司`及地址、电话、邮箱、主页 | **源码已实现（元数据）** |
| 数据类型 | `g_DataType_htmlview_global_var` | **源码已实现** |
| 命令 | `g_cmdInfo_htmlview_global_var` 和函数指针表 | **源码已实现（注册）**；实现完整性不足 |
| 通知 | `htmlview_ProcessNotifyLib_htmlview` | **源码已实现** |
| 常量 | `g_ConstInfo_htmlview_global_var` | **源码已实现** |
| 依赖文件 | `NULL` | **源码已实现（声明无额外文件）**；宿主系统/核心依赖仍需运行环境 |

固定 DLL 导出文件 `Source_htmlview.def` 仅导出 `GetNewInf`（`Source_htmlview.def:1-4`）；`GetNewInf` 在 `htmlview_dllMain.cpp:89-92` 返回上述库信息指针。

### 5.2 `HtmlViewer` 数据类型

`htmlview_dtType.cpp:111-125` 注册一个 `LIB_DATA_TYPE_INFO`：

- 中文名称：`超文本浏览框`。
- 英文名称：`HtmlViewer`。
- 说明：`提供对HTML页面的浏览支持`。
- 类型标志：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT`，即元数据明确为 Windows 窗口组件。
- 成员命令索引：`0..12`，共 13 项（`htmlview_dtType.cpp:45-50`）。
- 事件数量：10。
- 属性数量：代码数组声明为 8 个固定属性 + 7 个自定义属性，共 15 项；但 `s_objProperty..._count_00` 的初始化表达式使用了 `sizeof(s_objPropertyhtmlview_HtmlViewer_static_var_00)`，源码文本中该标识看起来与前面的属性数组名不一致，是否导致编译问题需在 Windows 编译器中验证（`htmlview_dtType.cpp:53-79`）。本文不将其推断为已修复或必然失败。
- 组件接口：`htmlview_GetInterface_HtmlViewer`。

#### 固定属性（来自 `FIXED_WIN_UNIT_PROPERTY` 的展开）

| 索引 | 中文名 | 英文名 | 类型 |
|---:|---|---|---|
| 0 | 左边 | `left` | `UD_INT` |
| 1 | 顶边 | `top` | `UD_INT` |
| 2 | 宽度 | `width` | `UD_INT` |
| 3 | 高度 | `height` | `UD_INT` |
| 4 | 标记 | `tag` | `UD_TEXT` |
| 5 | 可视 | `visible` | `UD_BOOL` |
| 6 | 禁止 | `disable` | `UD_BOOL` |
| 7 | 鼠标指针 | `MousePointer` | `UD_CURSOR` |

证据：`htmlview_dtType.cpp:53-68`。

#### HtmlViewer 自定义属性

| 回调索引 | 中文名 | 英文名 | 类型 | 读写声明 |
|---:|---|---|---|---|
| 0 | 字体大小 | `FontSize` | `UD_PICK_INT` | 可选值“最小/较小/中等/较大/最大” |
| 1 | 离线浏览 | `Offline` | `UD_BOOL` | 普通属性 |
| 2 | 静默 | `Silent` | `UD_BOOL` | 普通属性 |
| 3 | 地址 | `url` | `UD_FILE_NAME` | 网页文件选择器，设计时默认安全限制说明写入元数据 |
| 4 | 状态条文本 | `StatusText` | `UD_TEXT` | `UW_ONLY_READ` |
| 5 | 标题 | `Caption` | `UD_TEXT` | `UW_ONLY_READ` |
| 6 | 允许设计时预览 | `PreviewInDesignMode` | `UD_BOOL` | 设计期属性 |

证据：`htmlview_dtType.cpp:69-78`。以上是属性**元数据声明**，属性的实际保存、读取、更新和窗口联动不能仅由该表证明。

#### HtmlViewer 事件

事件及参数元数据在 `htmlview_dtType.cpp:81-109`：

1. `即将跳转`：返回 `SDT_BOOL`，用于允许/拒绝跳转。
2. `跳转完毕`：无返回值。
3. `载入开始`：无返回值。
4. `载入进度改变`：参数 `进度百分比`，`SDT_INT`。
5. `载入完毕`：无返回值。
6. `已就绪`：无返回值。
7. `状态文本被改变`：无返回值。
8. `标题被改变`：无返回值。
9. `命令状态被改变`：参数 `命令`（`SDT_INT`）与 `是否被允许`（参考传递 `SDT_BOOL`）。
10. `即将打开新窗口`：返回 `SDT_BOOL`。

事件文本描述了预期宿主行为，但当前仓库没有找到浏览器事件源、COM 事件接收器或 `NRS_EVENT_NOTIFY2` 调用，因此事件触发链属于**仅声明/未验证**。

### 5.3 命令模型

`HTMLVIEW_DEF` 是命令元数据的单一来源，后续被用于生成前置声明、`CMD_INFO`、函数指针数组和静态编译命令名数组：

| 编号 | 易语言命令 | C 函数符号 | 返回类型 | 参数 |
|---:|---|---|---|---:|
| 0 | `执行命令` | `htmlview_Execute_0_htmlview` | `_SDT_NULL` | 1 个 `SDT_INT` |
| 1 | `跳转` | `htmlview_Navigate_1_htmlview` | `_SDT_NULL` | 3 个 `SDT_TEXT`，后 2 个可空 |
| 2 | `取文档类型` | `htmlview_GetType_2_htmlview` | `SDT_TEXT` | 0 |
| 3 | `是否正在下载` | `htmlview_GetBusy_3_htmlview` | `SDT_BOOL` | 0 |
| 4 | `是否就绪` | `htmlview_IsReady_4_htmlview` | `SDT_BOOL` | 0 |
| 5 | 隐藏占位命令 `无法识别的名字_5` | `htmlview__bunengshibie__5_htmlview` | `_SDT_NULL` | 0 |
| 6 | 隐藏占位命令 `无法识别的名字_6` | `htmlview__bunengshibie__6_htmlview` | `_SDT_NULL` | 0 |
| 7 | 隐藏占位命令 `无法识别的名字_7` | `htmlview__bunengshibie__7_htmlview` | `_SDT_NULL` | 0 |
| 8 | `提交数据` | `htmlview_HttpPost_8_htmlview` | `SDT_BOOL` | `URL`、`SDT_BIN`、可空 `数据头` |
| 9 | 隐藏占位命令 `无法识别的名字_9` | `htmlview__bunengshibie__9_htmlview` | `_SDT_NULL` | 0 |
| 10 | 隐藏占位命令 `无法识别的名字_10` | `htmlview__bunengshibie__10_htmlview` | `_SDT_NULL` | 0 |
| 11 | `取浏览器对象` | `htmlview_GetBrowser_11_htmlview` | `MAKELONG(0x10030, 0)` | 0 |
| 12 | `取文档对象` | `htmlview_GetDocument_12_htmlview` | `MAKELONG(0x10030, 0)` | 0 |

证据：命令目录 `htmlview_cmd_typedef.h:12-25`；函数体 `htmlview_cmdDef.cpp:3-108`；参数表 `htmlview_cmdInfo.cpp:18-26`。`GetBrowser`/`GetDocument` 的返回类型编码声明为库对象类型，但没有找到对应 COM 对象获取和引用释放实现。

## 6. 真实调用链与接口边界

### 6.1 支持库装载链

```text
宿主按 Source_htmlview.def 查找 GetNewInf
  → GetNewInf()
  → &g_LibInfo_htmlview_global_var
  → 读取数据类型/命令/常量/通知函数指针
  → 根据 HtmlViewer 的 LIB_DATA_TYPE_INFO 建立 IDE 组件元数据
```

- **源码已实现**：导出定义、`GetNewInf`、库信息静态结构、指针数组组装。
- **未验证**：易语言宿主是否能在真实系统成功装载并正确解释所有结构。

### 6.2 宿主通知链

```text
易语言系统调用 htmlview_ProcessNotifyLib_htmlview
  → NL_SYS_NOTIFY_FUNCTION
  → ProcessNotifyLib(nMsg, dwParam1, dwParam2)
  → fnshare.cpp 保存 s_pfnNotifySys
  → 后续 NotifySys(...) 可转发给宿主
```

`htmlview_ProcessNotifyLib_htmlview` 还对以下通知提供静态编译相关响应：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNameshtmlview`。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `htmlview_ProcessNotifyLib_htmlview`。
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`。
- `NL_SYS_NOTIFY_FUNCTION`：转发到 `ProcessNotifyLib`。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前分支不做业务处理。

证据：`htmlview_dllMain.cpp:101-178`、`elib/fnshare.cpp:24-64`。

### 6.3 组件接口分发链

`htmlview_GetInterface_HtmlViewer(INT nInterfaceNO)` 按接口编号返回函数指针（`htmlview_dtType.cpp:129-193`）：

| 接口编号 | 返回函数 | 当前状态 |
|---|---|---|
| `ITF_CREATE_UNIT` | `htmlview_ControlCreate_HtmlViewer` | **仅声明/骨架**，返回 0 |
| `ITF_PROPERTY_UPDATE_UI` | `htmlview_PropUpDate_HtmlViewer` | **源码已实现**，无条件返回 `TRUE` |
| `ITF_DLG_INIT_CUSTOMIZE_DATA` | `htmlview_PropPopDlg_HtmlViewer` | **源码已实现**，设置未修改并返回 `FALSE` |
| `ITF_NOTIFY_PROPERTY_CHANGED` | `htmlview_PropChanged_HtmlViewer` | **仅声明/骨架**，只处理空的 `case 0` |
| `ITF_GET_ALL_PROPERTY_DATA` | `htmlview_PropGetDataAll_HtmlViewer` | **仅声明/骨架**，返回 0 |
| `ITF_GET_PROPERTY_DATA` | `htmlview_PropGetData_HtmlViewer` | **仅声明/骨架**，仅有空的 `case 0` |
| `ITF_GET_ICON_PROPERTY_DATA` | 无 | **未实现**，返回 `NULL` |
| `ITF_IS_NEED_THIS_KEY` | `htmlview_PropKetInfo_HtmlViewer` | **源码已实现占位**，返回 `FALSE` |
| `ITF_LANG_CNV` | 无 | **未实现**，返回 `NULL` |
| `ITF_MSG_FILTER` | 无 | **未实现**，返回 `NULL` |
| `ITF_GET_NOTIFY_RECEIVER` | `htmlview_PropNotifyReceiver_HtmlViewer` | **源码已实现占位**，当前默认尺寸分支仍返回 0 |

### 6.4 命令执行链

命令实现函数统一接收 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`，这是 `PFN_EXECUTE_CMD` ABI（`elib/lib2.h:1234-1239`）。当前函数体的事实如下：

- `Execute` 读取 `pArgInf[1].m_int`，但没有 `switch` 或浏览器对象调用。
- `Navigate` 读取 `m_pText` 的三个指针，但没有使用它们。
- `HttpPost` 读取 URL、字节集和请求头指针，但没有提交请求，也没有写 `pRetData`。
- `GetType`、`GetBusy`、`IsReady`、`GetBrowser`、`GetDocument` 的函数体为空。
- 隐藏占位命令函数体为空。

因此命令 ABI 和编辑器元数据已建立，浏览器业务语义尚未建立。证据：`htmlview_cmdDef.cpp:5-108`。

## 7. 数据流、生命周期与资源边界

### 7.1 已确认的数据流

```text
命令/组件元数据（静态数组）
  → LIB_INFO / LIB_DATA_TYPE_INFO / CMD_INFO
  → 易语言 IDE 读取并展示

宿主系统通知函数指针
  → s_pfnNotifySys
  → NotifySys(nMsg, dwParam1, dwParam2)
  → 宿主回调返回值

易语言命令参数
  → MDATA_INF 数组
  → 命令函数读取 m_int / m_pText / m_pBin
```

`MDATA_INF` 是一个按 1 字节对齐的联合数据载体，既可承载基础值、文本、字节集、窗口单元，也可承载变量指针和数组/复合数据指针（`elib/lib2.h:775-824`）。`htmlview_cmdDef.cpp` 当前只做参数读取，没有形成后续浏览器数据流。

### 7.2 资源与所有权

- `fnshare.h:ealloc/efree` 通过 `NotifySys(NRS_MALLOC/NRS_MFREE,...)` 使用易语言宿主内存（`elib/fnshare.h:25-39`）。
- `CloneTextData`、`CloneBinData`、`GetBinData` 提供宿主格式文本/字节集转换辅助，但当前 htmlview 业务函数没有调用它们的证据（`elib/fnshare.h:58-85,129-141`）。
- `UNIT_PROPERTY_VALUE` 规定文本、文件名、图片/字节数据等属性值的联合表示和释放责任；当前 HtmlViewer 属性回调没有实现实际读写和释放路径（`elib/lib2.h:580-676`、`htmlview_dtType.cpp:231-279`）。
- `GetBrowser`/`GetDocument` 若未来返回 COM 对象，当前仓库没有 `AddRef/Release`、`NRS_FREE_COMOBJECT` 或等价所有权协议的实现证据；当前仅为返回类型声明。
- 没有数据库、配置文件、缓存文件、业务日志或持久化存储模块。

### 7.3 生命周期状态

当前代码能确认的生命周期只有支持库通知级别：

```text
DLL_PROCESS_ATTACH / DLL_PROCESS_DETACH / DLL_THREAD_ATTACH / DLL_THREAD_DETACH
  → DllMain 空分支

宿主发送 NL_SYS_NOTIFY_FUNCTION
  → 保存 PFN_NOTIFY_SYS
  → 查询一次 NRS_GET_PRG_TYPE，设置 s_isDebug

宿主发送 NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE
  → 当前空处理
```

`DllMain` 四类分支均无初始化/释放逻辑（`htmlview_dllMain.cpp:7-24`）；`htmlview_ControlCreate_HtmlViewer` 当前也没有组件句柄、窗口、浏览器对象或事件订阅状态。因此“组件销毁/浏览器释放/事件解绑”均为**未实现或未验证**。

## 8. 接口、协议与外部依赖

### 8.1 对外接口

| 边界 | 接口/符号 | 说明 | 状态 |
|---|---|---|---|
| DLL 装载 | `GetNewInf` | 固定导出，返回 `PLIB_INFO` | **源码已实现** |
| 支持库通知 | `htmlview_ProcessNotifyLib_htmlview` | `PFN_NOTIFY_LIB` 入口 | **源码已实现** |
| 命令 ABI | `htmlview_*_<index>_htmlview` | `PFN_EXECUTE_CMD` 形态 | **签名已实现；行为未完成** |
| 组件接口 | `htmlview_GetInterface_HtmlViewer` | 根据 `ITF_*` 返回组件回调 | **源码已实现；回调完成度不足** |
| 组件创建 | `htmlview_ControlCreate_HtmlViewer` | 宿主创建窗口单元回调 | **仅声明/骨架** |
| 属性读写 | `htmlview_Prop*` | 设计期/运行期属性交互 | **仅声明/骨架或占位** |
| IDE 通知 | `NotifySys` / `ProcessNotifyLib` | 支持库与易语言系统双向通知 | **通用转发已实现** |

### 8.2 外部依赖

直接可见的依赖边界：

1. Windows C/C++ ABI：`windows.h` 及 Windows 类型/宏在 `elib/lib2.h` 中引入或兼容定义（`elib/lib2.h:53-67`、`elib/mtypes.h`）。
2. Visual Studio C++ `v141` 工具链与 Windows SDK `10.0.15063.0`。
3. 易语言支持库 ABI：`LIB_INFO`、`MDATA_INF`、`PFN_NOTIFY_SYS`、组件接口编号、内存通知编号。
4. 易语言系统核心支持库：工程元数据声明最低版本 `3.0`；`elib/krnllib.h` 另记录核心库版本常量 `4.5`，二者用途不同，不能混为当前运行时验证。
5. 浏览器宿主：命令说明提到浏览器命令、`IWebBrowser2`、`IHTMLDocument2`，但仓库没有 `#import`、COM 初始化、COM 事件 sink、`CoCreateInstance` 或浏览器控件创建代码。因此这些是接口目标/历史契约线索，而非当前实现依赖已闭合的证据。

`LIB_INFO.m_szzDependFiles` 为 `NULL` 且通知接口返回空依赖列表（`htmlview_dllMain.cpp:83-86,117-123`），仅能说明源码没有声明额外静态依赖文件，不等同于脱离易语言宿主即可运行。

## 9. 测试、构建与验证状态

### 9.1 仓库内测试现状

现场扫描 Git 跟踪文件和真实目录：

- 没有 `test/`、`tests/`、单元测试源、集成测试、CI 配置或测试脚本。
- 没有 README 或构建说明。
- 两个 `.vcxproj.user` 只有空 `PropertyGroup`，没有可复用的本地环境路径（`htmlview.vcxproj.user:1-4`、`htmlview_static/htmlview_static.vcxproj.user:1-3`）。
- 当前仓库只有一次浅历史提交 `f71a451`，没有可从 Git 历史追溯的功能演进。

### 9.2 当前取证实际验证

当前取证只执行了只读源码/工程/Git 盘点，未在 macOS 上运行 Windows Visual Studio 构建、未加载 DLL、未连接易语言 IDE、未调用浏览器 COM，也未运行任何测试。验证边界如下：

| 项目 | 结果 | 说明 |
|---|---|---|
| 目录与文件盘点 | 已完成 | 23 个 Git 跟踪源码/工程文件，另有本次 `ARCHITECTURE.md` |
| Git 基线读取 | 已完成 | `master` 与 `origin/master` 同指 `f71a451d954c9af23a96d6878dc1ac4ec2292f5b` |
| 导出入口静态核对 | 已完成 | `.def` 仅列 `GetNewInf`；源码实现该入口 |
| 命令/属性/事件元数据核对 | 已完成 | 依据 `htmlview_cmd_typedef.h`、`htmlview_cmdInfo.cpp`、`htmlview_dtType.cpp` |
| C++ 编译 | 未验证 | 当前主机为 macOS，仓库工程针对 Windows/VS v141 |
| DLL 装载 | 未验证 | 无 Windows/易语言宿主 |
| 真实 HtmlViewer 创建 | 未验证且源码显示未完成 | `htmlview_ControlCreate_HtmlViewer` 有 `TODO` 并返回 0 |
| 命令运行行为 | 未验证且源码显示未完成 | 命令函数仅取参或为空 |
| 属性序列化/事件触发 | 未验证且源码显示未完成 | 回调没有真实组件状态实现 |

## 10. 当前实现裁决

### 10.1 可确认已实现

- Visual Studio 解决方案同时包含 DLL 和静态库工程。
- 支持库 ABI 元数据静态表：库信息、命令表、参数表、常量表、数据类型表。
- 固定导出 `GetNewInf`。
- 支持库系统通知入口及 `PFN_NOTIFY_SYS` 保存/转发辅助。
- `HtmlViewer` 的名称、Windows 组件标志、13 个成员命令索引、15 项属性声明、10 个事件声明。
- 10 个浏览器操作常量的声明。

### 10.2 仅声明或占位

- `Execute`、`Navigate`、`HttpPost`、状态查询、文档/浏览器对象获取的业务行为。
- `HtmlViewer` 窗口/浏览器对象创建、销毁和句柄状态。
- 属性持久化、属性合法性校验、设计时/运行时实时值读取。
- 页面跳转、下载、POST、文档类型读取、就绪状态和忙状态。
- 事件产生、事件参数填充以及易语言事件回调通知。
- `IWebBrowser2`、`IHTMLDocument2` 对象返回与资源所有权。

### 10.3 当前未验证的工程风险

1. `htmlview_dtType.cpp:79` 的属性数组计数表达式标识名疑似与定义数组名不一致，需在目标编译器中确认。
2. 静态工程 x64 条件中的预处理宏与 Win32 条件不一致，是否为工程配置遗漏需在 Visual Studio x64 构建中确认。
3. 代码中存在 `DWORD` 承载指针、`(INT)g_cmdNameshtmlview` 等旧式 ABI 写法；在目标 32 位/64 位易语言 ABI 下的兼容性未验证。
4. `htmlview_cmdDef.cpp` 以 `pArgInf[1]` 开始取参数，是否符合宿主 `pArgInf` 的 0/1 起始约定需结合易语言运行时 ABI 和真实调用验证；当前只能记录源码现状，不能自行修正。
5. `htmlview_dtType.cpp` 的属性、事件元数据可能来自支持库模板，不能据此推断浏览器内核或宿主事件接线存在。
6. 工程没有显式第三方浏览器库、COM 封装或资源文件，当前无法确认历史目标浏览器技术（如 `WebBrowser`/MSHTML）与系统版本要求。

## 11. 后续复核建议（不代表已启动实现）

按风险和证据优先级，下一轮如需深挖应先做：

1. 在 Windows + 对应 Visual Studio 工具链中仅做编译前检查，确认属性计数标识名、x64 条件宏和 32/64 位 ABI 警告。
2. 对照易语言支持库 ABI 文档/真实宿主，确认 `pArgInf` 索引、`MDATA_INF` 所有权、`HUNIT` 生命周期及 `GetNewInf` 装载流程。
3. 若要判断历史真实功能，补查同 GUID/同库名的其他版本或发布包；当前仓库本身没有浏览器实现代码，不能以猜测替代证据。
4. 若后续实现组件，需单独建立窗口创建、浏览器对象管理、COM 事件接收、属性序列化、宿主事件通知、资源释放和错误路径的验证矩阵。
5. 补充最小宿主集成测试：DLL 装载与元数据计数、组件创建/销毁、属性往返、`Navigate`、POST、状态查询、事件顺序、COM 对象释放和 x86/x64 构建。

以上建议仅是架构复核入口；当前取证没有修改源码、工程、依赖、测试或配置，也没有启动实现工作。

## 12. Git 基线与证据索引

### 12.1 Git 基线

- 仓库路径：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/htmlview`
- 分支：`master`
- 远程：`https://gitee.com/JYtechnology/htmlview.git`
- 基线提交：`f71a451d954c9af23a96d6878dc1ac4ec2292f5b`
- 提交主题：`初始化仓库`
- 提交时间：`2022-12-19T16:09:14+08:00`
- 初始现场状态：`master...origin/master`，工作树无已知修改；本文件为当前取证唯一允许新增/更新的文件。

### 12.2 关键证据路径

- 库导出与库信息：`Source_htmlview.def:1-4`；`htmlview_dllMain.cpp:31-92`
- 系统通知：`htmlview_dllMain.cpp:101-178`；`elib/fnshare.cpp:7-71`
- 命令统一定义：`htmlview_cmd_typedef.h:3-25`
- 命令实现骨架：`htmlview_cmdDef.cpp:3-108`
- 参数/命令元数据：`htmlview_cmdInfo.cpp:5-46`
- 常量：`htmlview_const.cpp:3-28`
- 数据类型、属性、事件及组件回调：`htmlview_dtType.cpp:43-308`
- 统一头与外部符号：`include_htmlview_header.h:1-26`
- 支持库 ABI：`elib/lib2.h:266-364,409-522,526-729,780-824,1229-1318`
- 宿主辅助内存/通知：`elib/fnshare.h:20-169`
- 工程输入与配置：`htmlview.sln:5-40`；`htmlview.vcxproj:21-201`；`htmlview_static/htmlview_static.vcxproj:21-166`
- 工程筛选器：`htmlview.vcxproj.filters:1-74`；`htmlview_static/htmlview_static.vcxproj.filters:1-66`

## 13. 当前取证变更边界

当前取证只新增或更新目标根目录 `ARCHITECTURE.md`。未修改源码、工程文件、依赖、测试、配置或 Git 历史；未删除任何既有细探材料（现场未发现既有细探材料文件）。

## 14. 调用链与失败边界补充

`htmlview` 是 23 文件的支持库模板，命令表和类型表位于 `htmlview_cmdDef.cpp`、`htmlview_cmdInfo.cpp`、`htmlview_cmd_typedef.h`、`htmlview_dtType.cpp`；DLL 入口由 `htmlview_dllMain.cpp` 和 `Source_htmlview.def` 约束。仓内没有浏览器控件实现、COM 封装、资源文件或测试程序，因此“HTML 加载、脚本执行、导航事件、窗口销毁”只能视为接口意图。

动态/静态工程分别是 `htmlview.vcxproj` 与 `htmlview_static/htmlview_static.vcxproj`，共享 `elib/*` ABI。使用前必须在 Windows 验证 WebBrowser/COM 初始化、线程亲和、导航失败、回调重入、释放顺序、x86/x64 导出和宿主异常隔离；当前 macOS 未执行这些行为测试。23 文件的小型规模与文档现有 500 行以上篇幅相符，无需重复铺陈。
