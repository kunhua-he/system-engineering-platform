# shellex 架构建档

> 本文是 `shellex` 当前源码的唯一架构记录。首轮建档只新增本文件，不修改源码、工程、依赖、测试、配置或 Git，也不删除任何旧细探文件。
>
> **证据等级约定**：
> - **已实现**：当前仓库源码中存在可直接对应的实现。
> - **仅声明/协议**：源码有结构、宏、回调或工程声明，但当前项目没有完整实现，或没有运行证据。
> - **未验证**：从源码可以推断设计意图，但本机未能在目标 Windows/易语言环境中编译、加载或执行确认。
>
> **当前源码基线**：`master` / `312b4f9d02df0c62b584d301feb27738ef8284db`，提交时间 `2023-02-13T01:27:35Z`，提交主题 `!3 修复注册热键参数注释不对的情况 Merge pull request !3 from AlongsCode/master`。远程 `origin` 为 `https://gitee.com/JYtechnology/shellex.git`；现场 `git ls-remote origin HEAD refs/heads/master` 与本地 HEAD 均为同一提交。仓库为浅克隆（存在 `.git/shallow`），历史深度未在当前核对展开。

## 1. 项目定位

`shellex` 是一个面向 Windows 的易语言支持库（动态库目标扩展名为 `.fne`），以易语言支持库 ABI 向 IDE/运行环境登记元数据，并向易语言程序提供扩展功能命令。当前实现集中在四类能力：

1. **提示工具**：基于 Windows common controls 的 tooltip，支持添加、删除、文本、背景色、文本色、显示时间、图标、字体和延迟时间。
2. **拖放功能**：通过子类化窗口过程接收 `WM_DROPFILES`，把文件数量和文件名通过自定义 `WM_ELEBIL` 消息转发给标签控件。
3. **热键功能**：通过 `RegisterHotKey` 注册系统热键，并在被子类化的窗口过程中将 `WM_HOTKEY` 转发给标签控件。
4. **系统功能**：取易语言数据的地址、调用易语言子程序指针。

它不是独立的通用 Windows GUI 库，也没有自己的数据库、文件持久化、网络服务、配置文件、资源文件或测试程序；核心边界是“易语言命令表 + 命令执行回调 + 易语言运行时通知 ABI”。

## 2. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
        │
        │  加载支持库并查找固定导出 GetNewInf
        ▼
┌──────────────────────────────────────────────┐
│ shellex.dll / .fne（动态支持库目标）          │
│  shellex_dllMain.cpp                          │
│   ├─ g_LibInfo_shellex_global_var              │
│   ├─ g_cmdInfo_shellex_global_var             │
│   ├─ g_cmdInfo_shellex_global_var_fun         │
│   ├─ g_ConstInfo_shellex_global_var           │
│   ├─ g_DataType_shellex_global_var            │
│   └─ shellex_ProcessNotifyLib_shellex         │
│                                              │
│  shellex_cmd_typedef.h                       │
│   └─ SHELLEX_DEF：命令唯一索引/名称/参数表   │
│                                              │
│  shellex_cmdInfo.cpp                         │
│   └─ ARG_INFO + CMD_INFO（编辑元数据）       │
│                                              │
│  shellex_cmdDef.cpp                          │
│   └─ 15 个命令执行函数                       │
└──────────────────────────────────────────────┘
        │                                  ▲
        │ PFN_EXECUTE_CMD(PMDATA_INF...)    │ PFN_NOTIFY_SYS
        ▼                                  │
易语言命令参数/返回值 MDATA_INF              │
        │                                  │
        ├─ Windows HWND / common controls ──┤
        ├─ WM_DROPFILES / WM_ELEBIL         │
        ├─ WM_HOTKEY / WM_ELEBIL            │
        └─ RegisterHotKey / UnregisterHotKey│
                                           │
                             elib/fnshare.cpp
                              ProcessNotifyLib
                                ├─ 接收系统通知函数
                                ├─ 查询调试/发布版本
                                └─ 转发用户通知回调
```

静态库路线如下，实际是否由易语言静态编译器正确消费，当前核对未在 Windows 环境验证：

```text
shellex_static.vcxproj（StaticLibrary，__E_STATIC_LIB）
        │
        ├─ 复用 ../shellex_cmdDef.cpp 等同一批实现源码
        ├─ 通过 __LIB2_DEFFUNNAME / SHELLEX_NAME 生成带库名前缀符号
        ├─ shellex_ProcessNotifyLib_shellex 提供命令名/通知函数名/依赖列表协议
        └─ 外部静态编译流程负责链接并登记命令
```

## 3. 真实目录与文件地图

仓库当前现场共 23 个受 Git 跟踪的源码/工程文件；未发现 README、测试目录、旧 `细探-*.md` 或 `AGENTS.md`。`.git` 内部文件不计入源码地图。

```text
shellex/
├── Source_shellex.def                 动态库导出定义，仅导出 GetNewInf
├── shellex.sln                        VS 解决方案，动态库 + 静态库两个项目
├── shellex.vcxproj                    动态支持库工程
├── shellex.vcxproj.filters             动态工程筛选器
├── shellex.vcxproj.user                空的 VS 用户工程设置
├── shellex_static/
│   ├── shellex_static.vcxproj         静态库工程，复用上级源码
│   ├── shellex_static.vcxproj.filters 静态工程筛选器
│   └── shellex_static.vcxproj.user    空的 VS 用户工程设置
├── include_shellex_header.h           统一公共头，接入 elib 与命令声明
├── shellex_cmd_typedef.h              单一命令清单 SHELLEX_DEF
├── shellex_cmdInfo.cpp                参数/命令编辑元数据数组
├── shellex_cmdDef.cpp                 tooltip/拖放/热键/指针命令实现
├── shellex_dllMain.cpp                DLL 入口、库信息、通知协议、函数指针表
├── shellex_const.cpp                  常量表占位，当前数量为 0
├── shellex_dtType.cpp                  自定义数据类型表占位，当前数量为 0
└── elib/                              易语言支持库 ABI 头与共享通知辅助实现
    ├── lib2.h                         核心 ABI：DATA_TYPE、MDATA_INF、CMD_INFO、LIB_INFO 等
    ├── fnshare.h / fnshare.cpp         NotifySys、内存、数组、通知转发辅助
    ├── lang.h                          编译语言版本，当前为 GBK
    ├── krnllib.h                       系统核心支持库常量与版本/GUID声明
    ├── mtypes.h                        非 Windows 头环境的基础类型兼容声明
    ├── untshare.h                      组件/属性共享占位辅助，当前项目未注册组件类型
    └── PublicIDEFunctions.h            IDE 辅助功能常量，当前没有被业务实现使用
```

### 3.1 构建工程事实

- `shellex.sln:5-7` 声明两个项目：`shellex` 和 `shellex_static`。
- `shellex.sln:10-32` 提供 `Debug/Release × x86/x64` 配置；x86 在项目层映射为 `Win32`。
- `shellex.vcxproj:22-27` 将 `elib/fnshare.cpp` 与 5 个根目录 `.cpp` 纳入动态工程；`:30-42` 纳入头文件和 `.def`。
- 动态工程的 Win32 Debug/Release 配置为 `DynamicLibrary`、`v141`、Windows SDK `10.0.15063.0`；Win32 配置设置 `TargetExt=.fne`，并在链接项引用 `Source_shellex.def`（`shellex.vcxproj:51-63,95-152`）。
- 动态工程 x64 配置同样声明 `DynamicLibrary`/`v141`，但当前工程文本中未设置 `TargetExt=.fne`，也未在 x64 `<Link>` 中设置 `ModuleDefinitionFile`（`shellex.vcxproj:64-76,159-197`）。这是真实工程差异，不等同于已证明 x64 构建必然失败；需在 Windows/VS 中复核。
- `shellex_static/shellex_static.vcxproj:22-28` 通过 `..\` 复用同一批实现源码；其 Win32 Debug/Release 配置为 `StaticLibrary`，并设置 `__E_STATIC_LIB;__E_FNENAME=shellex`（`:48-59,92-121`）。x64 配置的预编译头设置为 `Use`，而仓库未提供 `pch.h`（`:130-155`），是否由外部工程环境补齐未验证。
- `Source_shellex.def:1-4` 的唯一导出为 `GetNewInf`，与 `elib/lib2.h:1317-1318` 的固定 ABI 名称一致。

## 4. 模块职责与依赖方向

### 4.1 `include_shellex_header.h`：公共接入层

`include_shellex_header.h:3-7` 引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和 `shellex_cmd_typedef.h`。动态模式下（`#ifndef __E_STATIC_LIB`）声明常量、命令、命令函数指针、参数和数据类型全局数组（`:11-20`）。

`SHELLEX_DEF_CMD`（`:22-24`）把统一命令清单展开为 15 个 `extern "C"` 命令执行函数声明。它是命令实现、元数据、函数指针表和静态命令名表之间的耦合接点。

### 4.2 `shellex_cmd_typedef.h`：命令单一事实清单

- `SHELLEX_NAME` / `SHELLEX_NAME_STR`（`:3-9`）将库名前缀、英文名、索引拼接为例如 `shellex_AddTooltip_0_shellex` 的符号/字符串。
- `SHELLEX_DEF(_MAKE)`（`:12-27`）定义 15 个命令的索引、中文名、英文名、说明、分类、平台、返回类型、参数数量和 `ARG_INFO` 起始位置。
- 类别编号实际为：`1` 提示工具，`2` 拖放功能，`3` 热键功能，`4` 系统功能；类别文本在 `shellex_dllMain.cpp:61-62` 定义。
- `DragTree` 索引 9 带 `CT_IS_HIDED`，`DragFiles` 索引 8 带 `CT_ALLOW_APPEND_NEW_ARG`；其余命令没有隐藏或可追加参数标志。

命令清单（**已实现函数**与**登记元数据**均来自源码，但运行结果未验证）：

| 索引 | 易语言命令 | C++ 实现符号 | 返回类型 | 参数 | 类别 | 实现状态 |
|---:|---|---|---|---:|---|---|
| 0 | `添加提示` | `shellex_AddTooltip_0_shellex` | `SDT_BOOL` | 4 | 提示工具 | 已实现 |
| 1 | `删除提示` | `shellex_DelTooltip_1_shellex` | `_SDT_NULL` | 1 | 提示工具 | 已实现 |
| 2 | `置提示文本` | `shellex_SetTooltipText_2_shellex` | `_SDT_NULL` | 2 | 提示工具 | 已实现 |
| 3 | `置提示底色` | `shellex_SetTooltipBColor_3_shellex` | `_SDT_NULL` | 1 | 提示工具 | 已实现 |
| 4 | `置提示文本色` | `shellex_SetTooltipTColor_4_shellex` | `_SDT_NULL` | 1 | 提示工具 | 已实现 |
| 5 | `置提示时间` | `shellex_SetTooltipTime_5_shellex` | `_SDT_NULL` | 1 | 提示工具 | 已实现 |
| 6 | `置提示图标` | `shellex_SetTooltipIcon_6_shellex` | `_SDT_NULL` | 2 | 提示工具 | 已实现 |
| 7 | `置提示字体` | `shellex_SetTooltipFont_7_shellex` | `SDT_BOOL` | 2 | 提示工具 | 已实现 |
| 8 | `设置文件拖放` | `shellex_DragFiles_8_shellex` | `SDT_BOOL` | 2+ | 拖放功能 | 已实现，但失败返回语义存在覆盖问题 |
| 9 | `设置树型框拖放` | `shellex_DragTree_9_shellex` | `SDT_BOOL` | 3 | 拖放功能 | 仅声明/占位；命令隐藏 |
| 10 | `注册热键` | `shellex_RegHotKey_10_shellex` | `SDT_INT` | 4 | 热键功能 | 已实现 |
| 11 | `撤销热键` | `shellex_UnRegHotKey_11_shellex` | `SDT_BOOL` | 2 | 热键功能 | 已实现，但返回值未写入 |
| 12 | `取指针地址` | `shellex_GetAddr_12_shellex` | `SDT_INT` | 1 | 系统功能 | 已实现 |
| 13 | `执行子程序` | `shellex_CallPtr_13_shellex` | `SDT_INT` | 2 | 系统功能 | 已实现 |
| 14 | `置提示延迟` | `shellex_SetDelayDisplay_14_shellex` | `_SDT_NULL` | 1 | 提示工具 | 已实现 |

### 4.3 `shellex_cmdInfo.cpp`：编辑期元数据

`g_argumentInfo_shellex_global_var`（`shellex_cmdInfo.cpp:5-62`）为命令参数提供名称、说明、数据类型、默认值/标志；最后一个参数条目是 `置提示延迟` 的 `延迟时间`。`SHELLEX_DEF_CMDINFO`（`:69-70`）把 `SHELLEX_DEF` 转成 `CMD_INFO`；`g_cmdInfo_shellex_global_var`（`:74-79`）是命令登记数组。

源码在 `:64-66` 仅于 `_DEBUG` 下计算参数数组数量，用于核对注释索引；这属于调试断言式辅助变量，不是运行时测试。当前仓库没有单元测试或自动化检查来验证命令索引与参数数组的完整一致性。

### 4.4 `shellex_dllMain.cpp`：支持库生命周期和登记协议

- `DllMain`（`shellex_dllMain.cpp:7-24`）对四类 DLL 生命周期通知均为空处理，返回 `TRUE`；没有资源释放、tooltip 窗口销毁、窗口过程恢复或热键注销。
- `g_cmdInfo_shellex_global_var_fun`（`:26-29`）按 `SHELLEX_DEF` 顺序保存 15 个 `PFN_EXECUTE_CMD` 函数地址。
- `g_LibInfo_shellex_global_var`（`:31-87`）登记格式号 `LIB_FORMAT_VER`、GUID `DA19AC3ADD2F4121AAD84AC5FBCAFC71`、版本 `3.0.0`、易语言系统依赖 `3.0`、核心库依赖 `3.0`、库名 `扩展功能支持库一`、GBK 语言、Windows 平台、4 个类别、命令表、函数表、通知函数和空常量/数据类型表。
- `GetNewInf`（`:89-92`）是动态库外部入口，返回 `LIB_INFO*`。
- 静态模式编译时，`g_LibInfo...` 与动态元数据在 `#ifndef __E_STATIC_LIB` 中排除；`shellex_ProcessNotifyLib_shellex` 仍提供静态编译协议分支。这是设计上的双模式切换，实际静态消费链未验证。

### 4.5 `shellex_const.cpp` 与 `shellex_dtType.cpp`：空登记表

- `shellex_const.cpp:14-18` 定义长度为 1 的占位数组，但 `g_ConstInfo_shellex_global_var_count = 0`；当前没有支持库常量。
- `shellex_dtType.cpp:3-10` 定义长度为 1 的占位 `LIB_DATA_TYPE_INFO` 数组，但数量为 0；当前没有注册自定义数据类型、窗口组件、属性或事件。
- `elib/untshare.h` 中虽然存在组件/属性/事件通用辅助和占位宏，但它们是共享模板/声明，不能据此认定 `shellex` 已实现组件模型。

### 4.6 `elib/fnshare.*`：运行时通知与内存辅助

`elib/fnshare.cpp:7-16` 保存易语言运行时传入的 `PFN_NOTIFY_SYS`，`NotifySys` 将命令库请求转发给它。`ProcessNotifyLib`（`:24-64`）处理 `NL_SYS_NOTIFY_FUNCTION`、释放和静态协议消息，并把通知继续转发给用户回调；`SetUserSysNotify`（`:67-71`）登记用户回调并返回 `ProcessNotifyLib`。

`elib/fnshare.h` 还提供以下 ABI 辅助：

- `ealloc`/`efree`（`:25-39`）：通过 `NRS_MALLOC`/`NRS_MFREE` 使用易语言运行时内存。
- `CloneTextData`、`CloneTextDataW`、`CloneBinData`（`:58-103`）：构造易语言文本/字节集布局。
- `GetAryElementInf` / `GetBinData`（`:107-141`）：解析数组头部并提取数据。
- `GetDataTypeType`（`:143-157`）：区分空、系统、用户和库数据类型。
- `allocArray`（`:160-169`）：用维数和元素数构造数组头部。

当前 `shellex_cmdDef.cpp` 没有调用 `ealloc`、`efree`、`CloneTextData` 或 `NotifySys` 来产生返回文本/字节集；其主要直接读 `MDATA_INF`、操作 Windows 对象并写回数值/逻辑返回值。

## 5. 命令执行调用链与数据流

所有命令函数使用 `PFN_EXECUTE_CMD` 原型：`void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`，该原型定义于 `elib/lib2.h:1234-1239`。`MDATA_INF` 是一个一字节对齐的 tagged union（`elib/lib2.h:775-824`）：union 保存整数、逻辑、文本指针、字节集指针、子程序地址、窗口单元、复合数据或数组指针，`m_dtDataType` 标识实际类型。

```text
易语言表达式参数
  │
  ▼
pArgInf[i].m_dtDataType + union 数据
  │
  ├─ HWND/颜色/延迟/热键参数：读取 m_int / m_bool
  ├─ 文本：读取 m_pText，按 CP_ACP 转为 std::wstring
  ├─ 字节集：读取易语言数组布局（维数、长度、数据）
  ├─ 字体复合数据：读取 EFONT* m_pCompoundData
  ├─ 数组：GetAryElementInf 取得首元素和数量
  └─ 子程序指针：读取 m_dwSubCodeAdr
  │
  ▼
Windows API / C++ helper / 回调
  │
  ▼
pRetData union 写回 m_bool / m_int；_SDT_NULL 命令不要求返回数据
  │
  ▼
易语言运行时接收结果或标签事件回调
```

### 5.1 Tooltip 调用链

```text
添加提示(hwnd, 文本/字节集, 气泡, 位置)
  ├─ IsWindow(hwnd)
  ├─ AddTooltip
  │   ├─ InitCommonControlsEx(ICC_BAR_CLASSES | ICC_TAB_CLASSES)
  │   ├─ 首次创建全局 Thwnd = CreateWindowExW(tooltips_class32)
  │   ├─ 组装 MYTOOL（TTF_IDISHWND | TTF_SUBCLASS）
  │   ├─ TTM_TRACKPOSITION
  │   └─ TTM_ADDTOOLW
  └─ 写回 pRetData->m_bool / m_int

删除/置文本/置背景色/置文本色/置时间/置图标/置字体/置延迟
  └─ 通过全局 Thwnd 发送 TTM_* 消息
```

实现位置：`shellex_cmdDef.cpp:31-73,106-317,169-284`。`Thwnd` 是单一静态 tooltip 窗口（`:19`），因此源码事实是所有控件共享一个 tooltip 窗口及全局样式；命令说明也明确背景色、文本色、时间、图标和字体是“所有控件”。

文本参数同时接受 `SDT_TEXT` 和 `SDT_BIN`：文本通过 `WIN_A2W`（`:75-95`）按 `CP_ACP` 转换；字节集按 `elib/fnshare.h:73-84` 兼容的数组头偏移读取宽字符。`WIN_A2W` 的错误消息写成 `Invalid UTF-8 sequence`，但实现实际使用系统 ANSI code page `CP_ACP`，不能据此认定它支持 UTF-8。

### 5.2 文件拖放调用链

```text
设置文件拖放(标签 hwnd, 控件 hwnd1, 可追加控件 hwnd2...)
  ├─ shellEx__DragFile(控件, 标签)
  │   ├─ 写全局 Droplabhwnds = 标签
  │   ├─ DragAcceptFiles(控件, TRUE)
  │   └─ SetWindowLongPtrA(GWLP_WNDPROC, Drag_WindowProc_shellex)
  └─ 控件收到 WM_DROPFILES
      ├─ DragQueryFileA(..., 0xFFFFFFFF) 得到文件数
      ├─ SendMessageA(标签, WM_ELEBIL, 0, 文件数)
      ├─ 循环 DragQueryFileA 得到每个 ANSI 路径
      ├─ SendMessageA(标签, WM_ELEBIL, 原 wParam, 文件名指针)
      └─ DragFinish
```

实现位置：`shellex_cmdDef.cpp:319-366`。`WM_ELEBIL` 固定为 `0x8075u`（`:15`）。反馈协议是源码注释中明确的项目约定：第一条消息的 `lParam` 是文件数，后续消息的 `lParam` 是 `char*` 文件名；消息同步发送，文件名缓冲区是 `OnDropFiles` 的栈变量，接收方不能在 `SendMessageA` 返回后异步保存该指针而不复制。

`Drag_WindowProc_shellex` 对非 `WM_DROPFILES` 消息调用 `CallWindowProcA(DropProcOld, ...)`（`:337-343`）。`Droplabhwnds` 和 `DropProcOld` 都是全局单例（`:319-320`），多控件/多标签并发使用未实现。

源码中的重要实现事实：`shellEx__DragFile` 的返回类型是 `LRESULT`，函数末尾固定 `return 0`（`:345-351`）；`shellex_DragFiles_8_shellex` 在循环中发现返回 0 会写 `FALSE`，但循环结束后无条件写 `pRetData->m_bool = TRUE`（`:358-366`）。因此当前实现的失败状态会被覆盖，不能把 `SDT_BOOL` 返回值解释为可靠的注册成功标志。

`DragTree`（`:374-385`）仅读取三个参数并注释“命令已经隐藏”，没有调用拖放安装逻辑，属于登记存在但功能未实现/未验证。

### 5.3 热键调用链

```text
注册热键(窗口 hwnd, 标签 hwnd, 修饰键, 虚拟键)
  ├─ 将 1/2/4/3/5/6 映射为 MOD_ALT/MOD_CONTROL/MOD_SHIFT 组合
  ├─ 首次为 hwnd 安装 shellEx__RegWindowProc
  ├─ remcount++，regcount++，ID = 33000 + regcount
  └─ RegisterHotKey(hwnd, ID, modifiers, vk)
      └─ 收到 WM_HOTKEY 时
          ├─ 遍历 ID 33000..IDarry
          ├─ 匹配 wParam
          └─ SendMessageA(label_hwnd, WM_ELEBIL, 热键ID, 0)

撤销热键(hwnd, ID)
  ├─ UnregisterHotKey(hwnd, ID)
  ├─ remcount--
  └─ remcount==0 时 SetWindowLongPtrA 恢复 old_proc
```

实现位置：`shellex_cmdDef.cpp:386-493`。全局状态为 `regcount`、`remcount`、`IDarry`、`label_hwnd`、`old_proc`（`:386-390`），只支持一个全局标签接收窗口和一个全局旧窗口过程。源码注释也明确提出“是否改为数组来让多标签支持？”但当前没有数组实现。

`RegHotKey` 先把易语言修饰键值映射为 Windows 常量（`:418-442`），首次调用在目标窗口上安装子类过程（`:444-446`），再调用 Windows `RegisterHotKey`（`:448-455`）。`UnRegHotKey` 外层命令没有把 `shellEx__unreghotkey` 的返回结果写入 `pRetData`（`:488-493`），所以元数据虽声明返回 `SDT_BOOL`，当前命令实现没有可靠输出该值。

### 5.4 指针与子程序调用链

`GetAddr`（`shellex_cmdDef.cpp:494-525`）按参数类型分支：数组调用 `GetAryElementInf` 后返回首元素地址；文本分支直接复制整个 `MDATA_INF` 到返回值；字节集分支返回数据区偏移；其他类型复制 `MDATA_INF`。其返回元数据是 `SDT_INT`，源码没有提供 64 位专用返回类型或安全句柄封装。

`CallPtr`（`:527-536`）把 `pArgInf[0].m_dwSubCodeAdr` 转换为 `int(WINAPI*)(VOID*)`，然后以 `pArgInf[1].m_pByte` 作为唯一参数调用，并把返回整数写入 `pRetData->m_int`。虽然元数据中第二参数 `_SDT_ALL`，实现只使用 `m_pByte`，调用约定、参数布局和被调用子程序签名必须由易语言运行时保证；本机没有易语言运行时验证。

## 6. 数据模型、状态和持久化

### 6.1 支持库登记模型

`LIB_INFO` 定义于 `elib/lib2.h:1246-1315`，本项目实际填写：

| 字段 | 当前值/来源 | 证据 |
|---|---|---|
| 格式号 | `LIB_FORMAT_VER`（`20000101`） | `shellex_dllMain.cpp:33`；`elib/lib2.h:1246` |
| GUID | `DA19AC3ADD2F4121AAD84AC5FBCAFC71` | `shellex_dllMain.cpp:34` |
| 版本 | `3.0.0` | `shellex_dllMain.cpp:35-37` |
| 系统依赖 | 易语言 `3.0` | `shellex_dllMain.cpp:39-40` |
| 核心库依赖 | `3.0` | `shellex_dllMain.cpp:41-42` |
| 名称/语言 | `扩展功能支持库一` / `__GBK_LANG_VER` | `shellex_dllMain.cpp:44-45`；`elib/lang.h:8,14` |
| 平台状态 | `_LIB_OS(OS_ALL)` | `shellex_dllMain.cpp:47` |
| 类别 | 4 个，以 `\0` 分隔 | `shellex_dllMain.cpp:61-62` |
| 命令 | 15 个，由 `g_cmdInfo...` 和函数表提供 | `shellex_dllMain.cpp:64-66` |
| 自定义类型 | 0 | `shellex_dtType.cpp:7-8` |
| 常量 | 0 | `shellex_const.cpp:15-16` |
| AddIn/SuperTemplate | 均为 `NULL` | `shellex_dllMain.cpp:68-81` |
| 依赖文件列表 | `NULL` | `shellex_dllMain.cpp:86` |

### 6.2 命令参数模型

`ARG_INFO`（`elib/lib2.h:266-292`）包含参数名、说明、编辑图像、`DATA_TYPE`、默认值和参数标志。当前清单共 29 个参数描述条目，按 `shellex_cmd_typedef.h` 的起始偏移分段：

- `0-3`：添加提示
- `4`：删除提示
- `5-6`：置提示文本
- `7`：背景色
- `8`：文本色
- `9`：显示时间
- `10-11`：图标类型/标题
- `12-13`：字体窗口句柄/`DTP_FONT`
- `14-15`：文件拖放标签/控件
- `16-18`：隐藏树型框拖放参数
- `19-22`：注册热键
- `23-24`：撤销热键
- `25`：取指针地址
- `26-27`：执行子程序
- `28`：延迟时间

`g_argumentInfo_shellex_global_var` 中使用了 `_SDT_ALL`（文本/字节集兼容）、`DTP_FONT`、`SDT_SUB_PTR`、`AS_HAS_DEFAULT_VALUE` 和 `AS_DEFAULT_VALUE_IS_EMPTY`。具体默认值是否被易语言编辑器按预期处理，需要目标 IDE 运行验证。

### 6.3 运行时状态模型

项目没有磁盘持久化；状态全部存在进程内静态变量或 Windows 对象中：

| 状态 | 所在位置 | 生命周期 | 风险/边界 |
|---|---|---|---|
| tooltip 窗口 | `Thwnd` | 首次 `添加提示` 创建，当前无释放 | DLL 卸载时未销毁 |
| tooltip 控件绑定 | common control 内部 | `TTM_ADDTOOLW` 后持续 | 删除依赖有效 `Thwnd` |
| 拖放标签/旧过程 | `Droplabhwnds`/`DropProcOld` | 首次拖放设置到进程结束或覆盖 | 单例，未恢复旧过程 |
| 热键计数/ID | `regcount`/`remcount`/`IDarry` | 进程内递增/递减 | 不保证跨窗口/线程一致 |
| 热键标签/旧过程 | `label_hwnd`/`old_proc` | 首次注册到最后注销 | 单例，多个窗口未隔离 |
| 易语言系统通知函数 | `s_pfnNotifySys` | `NL_SYS_NOTIFY_FUNCTION` 后至进程结束 | 未在释放通知中清空 |
| 用户通知函数 | `s_pfnuserNotifySys` | `SetUserSysNotify` 后至进程结束 | 无注销接口 |
| 调试版本号 | `s_isDebug` | 首次系统通知后缓存 | 初值为 `1253600` 哨兵 |

这些状态均为运行时内存，没有数据库、配置文件、日志文件、锁文件或网络端点。并发安全仅有源码注释层面的疑问（热键计数处 `shellex_cmdDef.cpp:386`），没有互斥、原子变量或线程模型实现。

## 7. 外部接口与协议边界

### 7.1 DLL 导出接口

- `GetNewInf()`：由 `Source_shellex.def:3-4` 导出；实现于 `shellex_dllMain.cpp:89-92`；返回 `PLIB_INFO`。
- 命令执行函数：源码以 `EXTERN_C` 生成函数，动态工程通过 `g_cmdInfo_shellex_global_var_fun` 间接提供，正常 DLL 导出表并未逐个导出这些命令。
- `shellex_ProcessNotifyLib_shellex`：作为 `LIB_INFO.m_pfnNotify` 回调地址提供；动态库的命令名字符串和静态协议处理在 `shellex_dllMain.cpp:94-178`。

### 7.2 支持库通知接口

`PFN_NOTIFY_LIB` / `PFN_NOTIFY_SYS` 都是 `INT(WINAPI*)(INT,DWORD,DWORD)`，定义于 `elib/lib2.h:1227-1230`。

已实现或明确分支的库通知：

| 通知 | 行为 | 状态 |
|---|---|---|
| `NL_SYS_NOTIFY_FUNCTION` | 保存系统通知函数；`fnshare.cpp` 还查询 `NRS_GET_PRG_TYPE` | 已实现 |
| `NL_GET_CMD_FUNC_NAMES` | 返回 `g_cmdNamesshellex` | 动态模式已实现；目标静态流程未验证 |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 返回 `shellex_ProcessNotifyLib_shellex` 字符串 | 动态模式已实现 |
| `NL_GET_DEPENDENT_LIBS` | 返回 `"\0\0"` | 动态模式已实现，表示无额外静态库依赖 |
| `NL_SYS_NOTIFY_FUNCTION`（库侧） | 转发到 `ProcessNotifyLib` | 已实现 |
| `NL_FREE_LIB_DATA` | 空处理 | 仅声明/未清理资源 |
| `NL_UNLOAD_FROM_IDE` | 空处理 | 仅声明/未处理 |
| `NR_DELAY_FREE` | 空处理 | 仅声明/未处理 |
| `NL_IDE_READY` | 空处理 | 仅声明/未适用（库未设置 IDE 插件标志） |
| `NL_RIGHT_POPUP_MENU_SHOW` | 空处理 | 仅声明/未适用 |
| `NL_ADD_NEW_ELEMENT` | 空处理 | 仅声明/未处理 |

通知常量和语义来自 `elib/lib2.h:1046-1193`，本项目真正的业务处理只在 `NL_SYS_NOTIFY_FUNCTION` 和静态协议查询处出现。

### 7.3 Windows 消息接口

- `WM_ELEBIL = 0x8075u`：项目自定义反馈消息。
- 拖放：`WM_DROPFILES`，通过 `DragAcceptFiles` 和窗口过程子类化接入。
- 热键：`WM_HOTKEY`，再通过 `WM_ELEBIL` 反馈给标签。
- tooltip：`TTM_ADDTOOLW`、`TTM_DELTOOLW`、`TTM_UPDATETIPTEXTW`、`TTM_SETTIPBKCOLOR`、`TTM_SETTIPTEXTCOLOR`、`TTM_SETDELAYTIME`、`TTM_SETTITLEW`、`WM_SETFONT`。

这些是进程内 Windows API/消息协议，不是 HTTP、RPC、命令行或文件接口。

## 8. 技术栈与依赖

### 8.1 已声明技术栈

- C++，Visual Studio `.sln/.vcxproj` 工程。
- Visual Studio Platform Toolset `v141`（`shellex.vcxproj:54,60,67,73`；静态工程对应 `:52,57,63,70`）。
- Windows SDK `10.0.15063.0`（两个项目 Globals）。
- 动态目标：`DynamicLibrary`，Win32 Debug/Release 目标扩展名 `.fne`。
- 静态目标：`StaticLibrary`，由 `__E_STATIC_LIB` 分支切换 ABI。
- Windows API：`commctrl.h`、tooltip common control、shell drag/drop、窗口过程、全局热键。
- `comctl32.lib`：`shellex_cmdDef.cpp:4` 通过 `#pragma comment(lib, "comctl32.lib")` 显式链接；其他 Windows 系统库由工程/系统默认链接关系提供，源码没有额外第三方包管理配置。
- C++ 标准库使用 `<string>`；项目没有 `CMakeLists.txt`、NuGet/vcpkg/Conan/Makefile、包锁定文件或运行时下载依赖。
- `elib` 是随仓库提交的易语言支持库接口头/辅助实现，不是本机外部安装包；其版权注释表明来自易语言支持库开发接口。

### 8.2 依赖方向

```text
shellex_cmdDef.cpp
  ├─ include_shellex_header.h
  │   ├─ elib/lib2.h       （ABI/结构/常量）
  │   ├─ elib/lang.h       （语言版本）
  │   ├─ elib/krnllib.h    （核心库常量）
  │   └─ shellex_cmd_typedef.h （命令清单）
  ├─ elib/fnshare.h        （数组/通知辅助）
  └─ Windows SDK + comctl32.lib

shellex_cmdInfo.cpp / shellex_dllMain.cpp / shellex_dtType.cpp / shellex_const.cpp
  └─ include_shellex_header.h

shellex_static/shellex_static.vcxproj
  └─ 复用同一组根目录源码，靠 __E_STATIC_LIB 改变登记和符号路径
```

## 9. 测试、验证和当前可确认程度

### 9.1 当前核对已完成的静态取证

- 人工读取了解决方案、动态/静态 `.vcxproj`、筛选器、用户工程文件、`.def`、全部根目录 C++/头文件和 `elib` 共享接口文件。
- 通过 `git status`、`git branch`、`git log`、`git remote -v`、`git ls-remote`、`git ls-files` 建立了本地/远程基线。
- 统计并核对了 `SHELLEX_DEF` 的索引 `0-14`、`g_argumentInfo...` 的偏移 `0-28`、`g_cmdInfo...` 的命令表和函数指针表。
- 检查了仓库内文件类型和源码编码；根目录 C++/头文件主要是 CRLF，部分中文注释按 GB18030 解码可读，`shellex_cmd_typedef.h` 的部分注释在当前工具显示为乱码，但不影响英文宏和命令表取证。
- 搜索了 `README`、`AGENTS.md`、`细探-*.md`、测试文件与 `TODO/FIXME/BUG`。未发现 README、AGENTS、细探或测试目录；发现的 TODO 主要是静态库命令名用途注释和 `elib` 模板注释。

### 9.2 未执行/未验证事项

- **未执行 Windows 编译**：当前执行环境是 macOS，未发现 `msbuild`；仓库要求的 Windows SDK、`v141`、`commctrl.h`、`comctl32.lib` 和易语言运行时均不可由本机现有 `xcodebuild` 替代。
- **未加载 DLL/.fne**：没有易语言 IDE/运行时，未验证 `GetNewInf`、库 GUID、版本兼容、命令表加载和通知协议。
- **未运行命令功能**：未验证 tooltip 显示/样式、拖放消息、热键注册与注销、指针地址和子程序调用。
- **未验证静态库链路**：虽然工程和 `__E_STATIC_LIB` 分支明确存在，但没有易语言静态编译器/Windows 链接环境确认其最终产物可用。
- **未执行 ABI/内存布局测试**：`MDATA_INF`、易语言字节集/数组布局、指针宽度、`WINAPI` 调用约定、复合字体 `EFONT` 均只依据源码静态读取。
- **未执行并发/资源测试**：源码包含全局窗口过程、全局计数器、单例标签、字体和 tooltip 句柄，尚未做多窗口、多线程、卸载和异常路径测试。

因此，本文把“代码路径存在”与“Windows/易语言环境下可用”严格分开；命令表中的“已实现”不表示当前核对已经运行通过。

## 10. 已确认风险与后续复核点

以下是基于当前源码的风险/疑点，不是当前核对修复项：

1. **x64 工程配置不完整的疑点**：动态工程的 `.fne` 后缀和 `.def` 链接只出现在 Win32 配置；静态工程 x64 使用预编译头但仓库无 `pch.h`。应在 Visual Studio 中分别构建四种动态配置和四种静态配置确认。
2. **指针宽度风险**：`GetAddr` 返回 `SDT_INT`，`CallPtr` 通过 `DWORD`/`INT` 风格 ABI 传地址；`elib/mtypes.h` 也定义 `HWND` 为 `DWORD`。x64 支持声明存在，但指针是否可无损穿过易语言类型和工程 ABI 未验证。
3. **拖放成功值被覆盖**：`shellEx__DragFile` 固定返回 0，外层 `DragFiles` 最后无条件写真；实际失败无法通过返回值传出。
4. **拖放窗口过程生命周期**：安装过程后没有对应卸载/恢复；`DropProcOld` 全局单例，重复给不同控件设置会覆盖旧过程，可能造成错误回调链。
5. **热键状态非隔离**：`label_hwnd`、`old_proc`、计数器是全局单例；多个窗口/标签、重复注销、注册失败后的计数回滚和线程交错均未处理。
6. **热键返回值未写回**：`UnRegHotKey` 声明 `SDT_BOOL`，但外层没有设置 `pRetData->m_bool`。
7. **资源释放不完整**：`SetTooltipFont` 创建 `HFONT` 且没有看到 `DeleteObject`；`GetDC` 没有对应 `ReleaseDC`；`DllMain` detach 没有销毁 tooltip 或恢复窗口过程。
8. **空句柄/初始化顺序**：删除、设置样式和延迟等命令直接使用全局 `Thwnd`；如果尚未执行 `添加提示`，消息目标可能为空，行为需要运行时确认。
9. **字符编码边界**：文本转宽字符使用 `CP_ACP`，拖放使用 `DragQueryFileA`/`SendMessageA`；系统区域设置变化时中文路径和文本行为需实测。
10. **异常路径**：`WIN_A2W` 可能抛出 `std::exception`，命令函数没有本地捕获；易语言运行时是否允许 C++ 异常穿过 `PFN_EXECUTE_CMD` 边界未验证。
11. **参数元数据与实现的细节差异**：`添加提示` 的文本/字节集分支分别写 `m_bool` 与 `m_int`；`设置文件拖放` 使用可追加参数；`执行子程序` 元数据为 `_SDT_ALL` 但实现只消费 `m_pByte`。需用易语言实际参数形态回归。
12. **库协议依赖**：库元数据要求易语言系统/核心支持库版本 3.0，而共享头 `krnllib.h` 内另有核心库版本常量 4.5；这是“项目登记要求”和“头文件参考常量”的不同来源，不能直接判定兼容关系，需在目标 IDE 中核对。
13. **提交历史浅**：`.git/shallow` 存在且本地只有当前 grafted 提交可见；不能从当前 clone 推断更早的设计演进或完整历史。

建议后续深挖顺序：

```text
初始（本文）
  └─ 完成结构、命令、ABI、状态、工程和证据建档
后续：Windows 构建与加载
  ├─ x86/x64 Debug/Release 动态库构建
  ├─ .fne 导出和 GetNewInf 检查
  └─ 易语言 IDE 登记/版本兼容
后续：命令行为
  ├─ tooltip 生命周期/编码/资源
  ├─ 拖放多控件和窗口过程恢复
  ├─ 热键多窗口/失败/注销
  └─ GetAddr/CallPtr ABI 与 x64
第四轮：安全与资源
  ├─ 指针和句柄边界
  ├─ 异常、线程和卸载
  └─ 内存/字体/消息缓冲区释放
```

## 11. Git 基线与工作树验收

- 仓库路径：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/shellex`
- 分支：`master`
- HEAD：`312b4f9d02df0c62b584d301feb27738ef8284db`
- 远程：`origin https://gitee.com/JYtechnology/shellex.git`
- `origin/HEAD`、`origin/master` 和本地 `HEAD` 在当前核对现场均指向同一提交。
- 初始工作树无已记录的源码修改；当前核对只新增根目录 `ARCHITECTURE.md`。
- 未执行 `git add`、`git commit`、`git pull`、`git merge`、`git reset` 或其他 Git 写操作。
- 未发现可供吸收的旧 `细探-*.md`；因此没有删除旧细探，也没有把任何旧细探当作事实来源。

## 12. 证据路径索引

所有路径均相对于本文所在的 `shellex` 根目录；行号以本次读取的当前基线为准：

| 主题 | 证据路径 |
|---|---|
| 动态导出 | `Source_shellex.def:1-4` |
| 解决方案与配置矩阵 | `shellex.sln:1-40` |
| 动态工程源文件/编译器/链接配置 | `shellex.vcxproj:1-202` |
| 静态工程与宏 | `shellex_static/shellex_static.vcxproj:1-167` |
| 动态工程筛选器 | `shellex.vcxproj.filters:1-74` |
| 静态工程筛选器 | `shellex_static/shellex_static.vcxproj.filters:1-66` |
| 公共接入头 | `include_shellex_header.h:1-26` |
| 统一命令清单 | `shellex_cmd_typedef.h:1-28` |
| 命令参数/元数据 | `shellex_cmdInfo.cpp:1-82` |
| Tooltip/拖放/热键/指针实现 | `shellex_cmdDef.cpp:1-537` |
| DLL 入口/库登记/通知协议 | `shellex_dllMain.cpp:1-180` |
| 常量空表 | `shellex_const.cpp:1-18` |
| 自定义类型空表 | `shellex_dtType.cpp:1-13` |
| ABI 数据类型/命令/库结构 | `elib/lib2.h:1-1604`，重点 `266-365,368-729,735-824,1227-1318` |
| 通知/内存/数组辅助 | `elib/fnshare.h:1-380`、`elib/fnshare.cpp:1-71` |
| 编译语言版本 | `elib/lang.h:1-18` |
| 核心库参考常量 | `elib/krnllib.h:1-133` |
| 基础类型兼容声明 | `elib/mtypes.h:1-176` |
| 组件/属性通用模板 | `elib/untshare.h:1-337` |
| IDE 功能常量 | `elib/PublicIDEFunctions.h:1-493` |
| Git/远程基线 | `.git/HEAD`、`.git/config`、`.git/shallow`、`git log`、`git ls-remote` |

> 后续深挖只更新本文件。源码中的实现、声明、未验证项和测试状态必须继续保持分层记录；不得用宣传性命令说明替代运行证据。