# iext3 架构档案

> 本文件是 `iext3` 的唯一架构事实源。首轮建档仅允许写入本文件；未修改源码、工程、依赖、测试、配置或 Git，也未删除任何旧细探文件。
>
> **判定口径：**“已实现”只表示源码中存在可执行实现并能从静态证据确认；“仅声明/元数据”表示存在接口、描述或注册信息但没有行为闭环；“未验证”表示本机没有 Windows/Visual Studio 环境或没有测试证据，不能把静态阅读当成编译/运行结果。

## 1. 项目定位

`iext3` 是精易官方仓库中的易语言 Windows 支持库源码，库名为“扩展界面支持库三”，版本元数据为 `3.1.0`，用于向易语言 IDE/运行时注册两个窗口组件：

- “卷帘式菜单”（英文名 `OutlookBar`）：分组菜单、菜单项目、图标/底图、禁止/隐藏、提示文本和组件菜单等能力的命令与事件描述。
- “高级选择夹”（英文名 `PageControl`）：动态子夹、图标、颜色、底图、提示文本、禁止/隐藏和强制刷新的命令与事件描述。

源码当前更接近**支持库接口/元数据骨架**：命令入口函数已批量生成，参数读取语句存在，但命令没有写入返回值或操作组件状态；两个组件的创建、属性存取和通知回调也主要是占位实现。因此不能依据命令名、属性表或注释宣称运行时控件功能已完成。

## 2. 总体流程图

```text
易语言 IDE / 运行时
        │
        │ 加载 .fne，按 DEF 导出入口查找
        ▼
Source_iext3.def ── GetNewInf()
        │
        ▼
 g_LibInfo_iext3_global_var
   ├─ 库版本、GUID、语言、依赖版本
   ├─ g_DataType_iext3_global_var（2 个窗口组件）
   ├─ g_cmdInfo_iext3_global_var（111 个命令描述）
   ├─ g_cmdInfo_iext3_global_var_fun（命令函数指针数组）
   └─ iext3_ProcessNotifyLib_iext3（系统通知入口）
        │
        ├─ 命令调用：pRetData + nArgCount + pArgInf
        │       ▼
        │   iext3_cmdDef.cpp 的 111 个 iext3_* 函数
        │       ├─ 当前只读取参数到局部变量（部分函数为空）
        │       └─ 未形成返回值/控件状态变更闭环
        │
        ├─ 组件注册：LIB_DATA_TYPE_INFO
        │       ├─ OutlookBar ── GetInterface ── 创建/属性/通知回调
        │       └─ PageControl ── GetInterface ── 创建/属性/通知回调
        │               └─ 当前回调多为 0/TRUE/FALSE 占位返回
        │
        └─ 系统通知：ProcessNotifyLib → fnshare.cpp
                ├─ 保存 PFN_NOTIFY_SYS
                ├─ 首次取得程序类型（debug/release）
                └─ 可转发给用户通知回调
```

## 3. 目录与真实分层

仓库当前没有 README、AGENTS.md、测试目录或旧 `细探-*.md` 文件；以下地图来自实际工程文件和源码读取，不来自外部 MCP 结果。

```text
iext3/
├── iext3.sln                         VS 解决方案，包含动态库和静态库两个项目
├── iext3.vcxproj                     iext3 动态库项目（DynamicLibrary）
├── iext3_static/
│   ├── iext3_static.vcxproj          iext3_static 静态库项目（StaticLibrary）
│   ├── iext3_static.vcxproj.filters
│   └── iext3_static.vcxproj.user
├── iext3.vcxproj.filters              源/头/elib 分组
├── iext3.vcxproj.user                 VS 用户级工程设置文件
├── Source_iext3.def                  DLL 模块定义，仅导出 GetNewInf
├── include_iext3_header.h             项目公共入口：基础 ABI、宏、全量命令声明
├── iext3_cmd_typedef.h                IEXT3_DEF 命令清单及命名拼接宏
├── iext3_cmdInfo.cpp                  参数表、命令描述数组及命令数量
├── iext3_cmdDef.cpp                   111 个命令函数体（目前是骨架）
├── iext3_dtType.cpp                   两个窗口组件的数据类型、属性、事件、回调
├── iext3_const.cpp                    支持库常量表（1 个常量）
├── iext3_dllMain.cpp                  DLL 入口、库描述、函数指针表、通知分发、GetNewInf
└── elib/
    ├── lib2.h                         易语言支持库 ABI/数据类型/通知/组件接口定义
    ├── mtypes.h                       基础 Win32 风格类型和宏
    ├── lang.h                         编译语言编码版本（GBK）
    ├── krnllib.h                      系统核心支持库版本及控件类型常量
    ├── fnshare.h / fnshare.cpp        内存、系统通知、数组/文本辅助封装
    ├── untshare.h                     组件辅助类/Win32 属性和序列化辅助（本项目当前未形成组件实现）
    └── PublicIDEFunctions.h            IDE 功能通知号/字段定义（工程列入，当前主入口未包含）
```

## 4. 模块职责与实现状态

| 模块 | 职责 | 源码事实 | 状态 |
|---|---|---|---|
| `iext3_cmd_typedef.h` | 用一次 `IEXT3_DEF(_MAKE)` 同时生成函数声明、命令元数据、函数指针表、静态名称表 | 索引 `0..110` 共 111 条；命令名、英文名、返回类型、参数数量和 `g_argumentInfo... + offset` 均在宏中声明 | **元数据已实现；行为未验证** |
| `iext3_cmdInfo.cpp` | 给动态支持库生成 `ARG_INFO` 参数表与 `CMD_INFO` 命令表 | 参数表 130 个槽位；命令表由 `IEXT3_DEF` 展开；`__E_STATIC_LIB` 时不编译这些动态元数据 | **注册数据已实现** |
| `iext3_cmdDef.cpp` | 命令执行入口 | 111 个函数符号均定义；人工读取显示函数体只取 `pArgInf` 局部值或为空，没有返回值赋值、状态对象或 `NotifySys` 调用 | **仅骨架/未实现业务行为** |
| `iext3_dtType.cpp` | 注册窗口组件、组件属性/事件/方法索引，并按接口号返回回调 | 两个 `LIB_DATA_TYPE_INFO`；接口分发完整覆盖创建、属性、按键和附加通知接收者 | **接口映射已实现** |
| `iext3_dtType.cpp` 回调 | 创建窗口、保存/读取属性、响应属性变化、设计器尺寸 | 创建返回 `HUNIT 0`；全部属性数据返回 `0`；单属性读取未赋值却返回 `TRUE`；属性变化基本返回 `FALSE`；按键/尺寸通知未处理 | **占位实现** |
| `iext3_dllMain.cpp` | DLL 装载、库描述、命令函数表、通知入口 | `DllMain` 四类生命周期分支为空；`GetNewInf` 返回静态 `LIB_INFO`；通知入口实现部分协议分支 | **库壳已实现，生命周期无业务逻辑** |
| `iext3_const.cpp` | 预定义支持库常量 | 动态模式注册 `LibAlias = "iext3"`，文本值为 `iext3` | **已实现** |
| `elib/fnshare.cpp` | 保存系统通知函数、转发通知、判断运行版本、设置用户通知回调 | `NL_SYS_NOTIFY_FUNCTION` 保存回调并查询 `NRS_GET_PRG_TYPE`；`NotifySys` 可转发；`SetUserSysNotify` 覆盖用户回调 | **辅助链已实现，未被命令使用** |
| `elib/lib2.h` 等 | 提供易语言支持库 ABI 和通用结构 | 包含 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、组件回调 typedef、`MDATA_INF` 等 | **依赖契约已声明** |

## 5. 构建目标与依赖边界

### 5.1 工程配置

证据：`iext3.sln:1-40`、`iext3.vcxproj:3-202`、`iext3_static/iext3_static.vcxproj:3-166`。

| 目标 | 工程类型 | Win32 配置 | x64 配置 | 输出/关键宏 |
|---|---|---|---|---|
| `iext3` | `DynamicLibrary` | Debug/Release，`v141`，`TargetExt=.fne`，链接 `Source_iext3.def` | Debug/Release，`v141`；工程文件未配置 `.fne` 扩展和 `.def` 链接 | Win32 定义 `__E_FNENAME=iext3; IEXT3_EXPORTS` |
| `iext3_static` | `StaticLibrary` | Debug/Release，`v141`，定义 `__E_STATIC_LIB; __E_FNENAME=iext3` | Debug/Release；未见同样的 `__E_STATIC_LIB`/`__E_FNENAME` 定义，且使用预编译头 `pch.h` | Win32 目标为静态库；x64 配置与 Win32 不对称 |

两项目都声明 Windows SDK `10.0.15063.0`、Unicode 字符集；代码实际使用 `HWND`、`HMENU`、`HGLOBAL`、`WINAPI`、Win32 控件/窗口接口。源码自带 `elib/mtypes.h`、`elib/lib2.h` 等兼容层，没有第三方包管理文件、外部库清单或运行时配置文件。

### 5.2 编码和 ABI

- C/C++ 源码中的中文文本实际以 GBK/CP936 解码可读；`elib/lang.h:8-14` 把编译语言设为 `__GBK_LANG_VER`。
- `include_iext3_header.h:3-7` 依次引入 `lib2.h`、`lang.h`、`krnllib.h` 和命令类型宏。
- `elib/lib2.h` 定义 `EXTERN_C`、`__E_FNENAME` 约束、命令/参数/组件 ABI 和通知号；缺少 `__E_FNENAME` 会触发预处理错误（`lib2.h:17-24`）。
- `IEXT3_NAME` 将库名、英文函数名、命令索引和库名拼成符号，例如 `iext3_AddFolder_1_iext3`（`iext3_cmd_typedef.h:3-9`）。

## 6. 核心数据模型（内存描述模型，无持久化）

本项目没有数据库、文件存储、序列化格式实现或持久化模型。以下“数据模型”是易语言支持库加载时读取的内存描述和运行时句柄契约：

### 6.1 库级模型

`g_LibInfo_iext3_global_var`（`iext3_dllMain.cpp:31-87`）包含：

- ABI 版本 `LIB_FORMAT_VER`；固定 GUID `{B6F7542F-B8FE-46a8-9605-98856A687097}`；库版本 `3.1.0`。
- 系统要求：易语言 `4.0`、系统核心支持库 `4.0`。
- 名称“扩展界面支持库三”、GBK 语言、Windows 状态、作者和联系信息。
- 两个自定义数据类型、111 个命令、命令函数指针数组、1 个常量、通知函数 `iext3_ProcessNotifyLib_iext3`。
- 全局命令类别、AddIn、SuperTemplate 和依赖文件列表均为 `NULL/0`。

### 6.2 命令和参数模型

- `CMD_INFO`（`elib/lib2.h:297-364`）描述中文名、英文名、说明、对象类别、隐藏标志、返回 `DATA_TYPE`、难度级别、参数数目和参数表地址。
- `ARG_INFO`（`elib/lib2.h:266-292`）描述参数名、说明、数据类型、默认值和引用/数组/可空标志。
- 111 条命令索引连续为 `0..110`；索引 `0` 是隐藏占位命令。`IEXT3_DEF` 的组件映射为：`OutlookBar` 方法索引 `1..30`、`91..110`，`PageControl` 方法索引 `31..90`。
- 公开（未标记 `CT_IS_HIDED`）的 55 条命令，按源码命名为：
  - `OutlookBar`：`AddFolder`、`AddItem`、`RemoveFolder`、`RemoveItem`、`GetFolderCount`、`GetItemCount`、`GetFolderText`、`GetItemText`、`SetFolderText`、`SetItemText`、`GetFolderData`、`GetItemData`、`SetFolderData`、`SetItemData`、`GetItemImage`、`SetItemImage`、`RemoveAll`、`AddCtrlFolder`、`SetFolderIcon`、`GetFolderIcon`、`SetFolderBackImage`、`GetFolderBackImage`、`IsFolderDisabled`、`DisableFolder`、`IsItemDisabled`、`DisableItem`、`IsFolderHided`、`HideFolder`、`IsItemHided`、`HideItem`、`GetFolderTipText`、`SetFolderTipText`、`GetItemTipText`、`SetItemTipText`。
  - `PageControl`：`AddPage`、`DeletePage`、`GetPageCount`、`GetPageCaption`、`SetPageCaption`、`GetPageIcons`、`SetPageIcons`、`GetPageDatas`、`SetPageDatas`、`GetTabBackColors`、`SetTabBackColors`、`GetTabBackImage`、`SetTabBackImage`、`GetPageTipText`、`SetPageTipText`、`GetTabRect`、`DisablePage`、`IsPageDisabled`、`HidePage`、`IsPageHidden`、`ForceRedraw`。
- 56 条被隐藏/占位/兼容命令仍留在索引表中，其中 `AddChild` 的说明明确表示“本命令不再使用”，大量 `_bunengshibie_` 入口为空。

### 6.3 组件模型

每个 `LIB_DATA_TYPE_INFO`（`elib/lib2.h:693-729`）由中文名、英文名、方法索引数组、操作系统/组件标志、事件数组、属性数组和 `PFN_GET_INTERFACE` 构成：

| 数据类型 | 方法索引 | 属性 | 事件 | 标志 | 接口函数 |
|---|---:|---:|---:|---|---|
| `OutlookBar` / 卷帘式菜单 | 50（`1..30`,`91..110`） | 33（固定 8 + 自定义 25，含隐藏占位属性） | 9 | `LDT_WIN_UNIT` | `iext3_GetInterface_OutlookBar` |
| `PageControl` / 高级选择夹 | 60（`31..90`） | 55（固定 8 + 自定义 47，含隐藏占位属性） | 5 | `LDT_WIN_UNIT | LDT_IS_CONTAINER | LDT_IS_TAB_UNIT | LDT_CANNOT_GET_FOCUS` | `iext3_GetInterface_PageControl` |

属性定义使用 `UNIT_PROPERTY`（`elib/lib2.h:410-458`）：类型覆盖整数、文本、逻辑、颜色、字体、图片组和自定义数据。`OutlookBar` 重点属性包括 `Items`、`BigImageList`、`SmallImageList`、`RangeStyle`、菜单/项目颜色、字体、菜单高度和图片组；`PageControl` 重点属性包括 `TabDirection`、`AllowMultiLines`、`Items`、`PageIndex`、`HideTabs`、`TabHeight`、`UIStyle`、各种颜色/图片组、`PageLeft/PageTop/PageWidth/PageHeight` 和隐藏/禁止策略。

事件定义使用 `EVENT_INFO2`（`elib/lib2.h:494-522`），两组件均标记 `_EVENT_OS(OS_ALL) | EV_IS_VER2`。事件名为：

- `OutlookBar`：`项目被选择`、`菜单被改变`、`项目名称被改变`、`菜单名称被改变`、`项目被拖动`、`菜单被单击`、`菜单被右击`、`项目被右击`、`项目被双击`。
- `PageControl`：`子夹被改变`、`将改变子夹`、`子夹头被单击`、`子夹头被点燃`、`子夹头被右击`。

### 6.4 运行时句柄与内存

- `HUNIT` 是 `DWORD`（`elib/lib2.h:526`），组件创建函数应返回组件句柄；当前两个创建函数都返回 `0`。
- 命令入口接收 `PMDATA_INF pRetData`、参数数量和 `PMDATA_INF pArgInf`；当前函数只读取 `m_pText`、`m_int`、`m_bool`、`m_pInt` 或 `m_pByte`，未向 `pRetData` 写回。
- `UNIT_PROPERTY_VALUE` 用联合体承载整数、逻辑、文本、文件名以及二进制/图片组数据（`elib/lib2.h:580-663`）。当前组件没有自己的状态结构，也没有对 `UD_CUSTOMIZE`/`UD_IMAGE_LIST` 数据进行复制或释放。
- `fnshare.h` 的 `ealloc/efree`、`CloneTextData/CloneBinData` 和数组头格式是可用的通用辅助契约，但在当前命令和组件回调中没有发现调用闭环。

## 7. 接口与调用链

### 7.1 DLL 装载接口

1. `Source_iext3.def:1-4` 只导出 `GetNewInf`。
2. `GetNewInf`（`iext3_dllMain.cpp:89-92`）返回 `&g_LibInfo_iext3_global_var`。
3. 易语言系统随后读取库级命令、类型、常量和通知回调指针。
4. 动态模式由 `g_cmdInfo_iext3_global_var_fun`（`iext3_dllMain.cpp:26-29`）提供 111 个命令实现地址。

### 7.2 系统通知接口

`iext3_ProcessNotifyLib_iext3`（`iext3_dllMain.cpp:101-178`）处理：

- `NL_GET_CMD_FUNC_NAMES`：返回静态编译需要的命令实现名称数组。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `iext3_ProcessNotifyLib_iext3` 名称。
- `NL_GET_DEPENDENT_LIBS`：返回空的双零结尾依赖列表。
- `NL_SYS_NOTIFY_FUNCTION`：转发到 `ProcessNotifyLib`，由 `fnshare.cpp:24-36` 保存 `PFN_NOTIFY_SYS` 并读取 `NRS_GET_PRG_TYPE`。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：分支存在但当前无业务处理。
- 未识别消息返回 `NR_ERR`。

`fnshare.cpp:60-71` 在系统通知后调用用户通过 `SetUserSysNotify` 设置的回调；这条扩展链已有代码，但本项目没有命令使用它。

### 7.3 组件接口

两个 `iext3_GetInterface_*` 都按 `nInterfaceNO` 返回：

- `ITF_CREATE_UNIT` → `iext3_ControlCreate_*`
- `ITF_PROPERTY_UPDATE_UI` → `iext3_PropUpDate_*`
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `iext3_PropPopDlg_*`
- `ITF_NOTIFY_PROPERTY_CHANGED` → `iext3_PropChanged_*`
- `ITF_GET_ALL_PROPERTY_DATA` → `iext3_PropGetDataAll_*`
- `ITF_GET_PROPERTY_DATA` → `iext3_PropGetData_*`
- `ITF_IS_NEED_THIS_KEY` → `iext3_PropKetInfo_*`
- `ITF_GET_NOTIFY_RECEIVER` → `iext3_PropNotifyReceiver_*`

`ITF_GET_ICON_PROPERTY_DATA`、`ITF_LANG_CNV` 和 `ITF_MSG_FILTER` 明确落到 `break` 后返回 `NULL`，不是已支持接口。

## 8. 实现闭环审计

### 已实现或可静态确认

- 支持库元数据结构和固定 GUID/版本/依赖版本填充。
- `GetNewInf` DLL 入口和 `.def` 导出。
- 111 条命令的索引、名称、参数计数、返回类型和函数符号一一生成。
- 两个组件的属性、事件、方法索引、操作系统和组件标志登记。
- 动态通知协议的命令函数名、通知函数名、静态依赖空列表分支。
- `fnshare` 的系统通知保存/转发和用户回调转发。

### 仅声明、描述或占位

- 命令实现：`iext3_cmdDef.cpp:6-1050` 的 111 个函数体没有业务逻辑。静态计数为 58 个空函数，另外 53 个仅把参数复制到局部变量；没有 `pRetData` 写回或控件句柄访问证据。
- 控件创建：`iext3_dtType.cpp:404-421`、`585-602` 返回 `HUNIT 0`。
- 属性持久化：`PropGetDataAll_*`（462-466、642-647）返回 `0`；`PropGetData_*`（469-488、650-669）没有给属性值赋值，默认分支和最终返回值不能构成真实读取。
- 属性变更和自定义编辑：`PropChanged_*`（440-459、621-640）没有处理有效属性；`PropPopDlg_*`（430-438、611-619）固定 `*pblModified=false`、返回 `FALSE`。
- 设计器通知/按键：`PropKetInfo_*` 固定返回 `FALSE`；`PropNotifyReceiver_*` 只识别 `NU_GET_CREATE_SIZE_IN_DESIGNER` 但没有写入宽高，最终返回 `0`。
- `elib/untshare.h` 的 `CPropertyInfo::SaveData` 返回零句柄、`LoadData` 基本直接返回真，`LoadIco` 最终返回 `NULL`；这些是通用骨架，不是 iext3 控件完成证据。

### 当前未完成的真实闭环

```text
命令参数 → 组件 HUNIT → 内部菜单/项目/子夹状态 → Win32 窗口绘制
       ↘ pRetData 返回值 / 引用参数写回
       ↘ EVENT_NOTIFY2 事件抛出 → 易语言用户事件处理
设计时属性 → 序列化字节集 → 运行时恢复
```

上述链路中的状态对象、Win32 窗口创建/销毁、属性编码/解码、返回值、引用参数写回和事件抛出在本版本源码中均未形成实现证据。

## 9. 测试与验证状态

- 仓库内未发现测试文件、测试目录、CI 配置或可执行样例。
- 本次只做人工源码/工程读取和静态结构核对，未安装依赖、未启动服务、未生成构建物。
- 未在本机执行 Visual Studio/MSBuild 编译：当前环境为 macOS，工程依赖 Windows SDK、Win32 ABI、Visual Studio `v141` 和 `.fne` 产物规则；因此“可编译”“可加载”“控件可运行”均为**未验证**。
- 已核对的静态事实包括：命令宏条目 111 条、命令函数定义 111 个、组件数据类型 2 个、OutlookBar 属性/事件为 33/9、PageControl 属性/事件为 55/5、常量 1 个、`.def` 导出 1 个。
- 不能把函数符号存在、元数据注册成功或参数局部读取误判为功能测试通过。

## 10. 风险与后续复核点

1. **功能完成度风险（高）：** 命令入口没有返回值和状态操作，控件创建返回空句柄；当前版本不能作为可运行控件支持库使用的证据。
2. **元数据与实现漂移风险（高）：** 111 条命令、属性和事件已暴露给 IDE，但对应实现缺失，易语言项目可能能显示命令却在运行时得到空结果或无动作。
3. **动态/x64 工程不对称（高，未在 Windows 验证）：** `iext3.vcxproj` 仅 Win32 配置显式设置 `.fne` 和 `Source_iext3.def`；`iext3_static.vcxproj` 的 x64 配置没有复现 Win32 的 `__E_STATIC_LIB`、`__E_FNENAME=iext3`；需在 Windows/MSBuild 中核验目标是否可产出和链接。
4. **ABI/编码风险（中高）：** 工程声明 Unicode，但 `elib/mtypes.h` 的 `TCHAR/LPTSTR` 与 GBK 文本、Win32 A/W 调用约定混杂；需在目标易语言版本和真实编码环境验证。
5. **空属性返回风险（高）：** `iext3_PropGetData_*` 返回 `TRUE` 却未写入 `UNIT_PROPERTY_VALUE`，调用方若信任成功标志可能读取未定义/旧值。
6. **内存所有权风险（中）：** 文本、图片组、`UD_CUSTOMIZE` 等数据需要按 `lib2.h` 契约释放；当前未见组件状态与序列化实现，不能确认所有权闭环。
7. **来源边界风险（中）：** `elib` 文件含易语言作者吴涛的授权声明（例如 `fnshare.h:1-6`、`untshare.h:1-6`）；后续复用必须遵守原始授权范围。
8. **缺少动态依赖声明不等于无依赖（中）：** `NL_GET_DEPENDENT_LIBS` 返回空字符串，但 Win32 系统 DLL 和易语言核心运行环境属于隐含宿主依赖；需以目标构建/加载工具实测。

## 11. Git 基线与证据路径

### 基线

- 仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/iext3`
- 分支：`master`，跟踪 `origin/master`
- 当前提交：`09241b5803106fd49781d6bd128302fa824b79a8`（短哈希 `09241b5`）
- 提交时间：`2022-12-19 16:11:53 +08:00`
- 提交信息：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/iext3.git`
- 工作树：建档前静态核对为 clean；仓库为浅克隆，`.git/shallow` 指向当前提交。

### 关键证据

- 库入口和元数据：`iext3_dllMain.cpp:5-101`
- 通知分发：`iext3_dllMain.cpp:101-178`
- 导出表：`Source_iext3.def:1-4`
- 命令清单/索引/返回类型：`iext3_cmd_typedef.h:3-124`
- 参数描述：`iext3_cmdInfo.cpp:3-215`
- 命令函数骨架：`iext3_cmdDef.cpp:1-1050`
- 组件定义、属性、事件和接口回调：`iext3_dtType.cpp:1-701`
- 常量：`iext3_const.cpp:1-20`
- 项目公共入口：`include_iext3_header.h:1-26`
- ABI 与组件契约：`elib/lib2.h:243-735`、`elib/lib2.h:838-1000`
- 通知/内存辅助：`elib/fnshare.h:20-169`、`elib/fnshare.cpp:1-71`
- 基础类型：`elib/mtypes.h:1-171`
- 语言和核心库版本：`elib/lang.h:1-18`、`elib/krnllib.h:1-133`
- 工程配置：`iext3.sln:1-40`、`iext3.vcxproj:21-202`、`iext3_static/iext3_static.vcxproj:21-166`

## 12. 首轮结论

`iext3` 已完成“易语言支持库三”的**注册协议、命令/参数/组件元数据和函数符号骨架**，但尚未完成两个控件的运行时实现。首轮架构建档应把它归类为：

```text
接口与元数据：已实现（静态证据充分）
DLL/通知壳：部分实现（静态证据充分）
命令业务行为：仅声明/骨架（未实现）
控件创建与属性状态：占位（未实现）
事件、序列化、运行时兼容性：未实现或未验证
Windows 编译、加载、真实控件运行：未验证
```

后续如进行深挖，应优先在 Windows 目标环境核验工程配置和 ABI，再围绕组件状态模型、创建/销毁、属性序列化、命令返回值、引用参数写回和 `EVENT_NOTIFY2` 事件发送补齐实现证据；在此之前不能把本仓库当作已完成的 `OutlookBar`/`PageControl` 支持库。
