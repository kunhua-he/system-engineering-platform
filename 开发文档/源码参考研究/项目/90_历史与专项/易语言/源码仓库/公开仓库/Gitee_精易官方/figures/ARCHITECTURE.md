# figures 架构建档

> 本文是 `figures` 仓库的唯一架构建档文档。结论以当前工作树源码和工程文件为证据，明确区分“源码已实现”“仅声明/注册”“未验证”。未把仓库外部资料或无关 MCP 结果作为事实。
>
> 当前仓库没有 README、测试目录、CI 配置或旧 `细探-*.md` 文件；因此本文直接以源码、Visual Studio 工程和 Git 基线建档。

## 1. 项目定位

`figures` 是面向易语言 Windows 运行时/IDE 的“自定义图形支持库”示例工程，目标形态是一个可被易语言装载的动态库（Win32 目标扩展名配置为 `.fne`），同时提供一个静态库工程 `figures_static`。它通过易语言支持库 ABI 注册：

- 支持库基本信息、版本、GUID、作者和系统要求；
- 全局命令及对象方法的名称、参数、返回值和隐藏状态；
- 图形窗口组件、图形对象、图形操作接口、图形类型枚举；
- 组件属性、事件、组件交互回调；
- `GetNewInf` 入口和系统通知回调。

**实现状态结论：** 元数据和 ABI 桥接骨架已实现；图形文档/图形对象的实际存储、绘制、编辑、属性序列化、事件触发以及 120 个命令的业务执行逻辑没有在当前源码中实现。`figures_cmdDef.cpp` 中 120 个命令函数均只有参数局部变量读取或空函数体，没有向 `pRetData` 写返回值，也没有调用图形对象逻辑。

## 2. 总体流程图

```text
易语言 IDE / 运行时
        │
        │ Windows DLL 装载，查找固定入口 GetNewInf
        ▼
figures_dllMain.cpp::GetNewInf
        │
        │ 返回静态 LIB_INFO
        ├──────────────► g_ConstInfo_figures_global_var（16 个常量）
        ├──────────────► g_cmdInfo_figures_global_var（120 个命令/方法元数据）
        ├──────────────► g_cmdInfo_figures_global_var_fun（120 个执行函数指针）
        └──────────────► g_DataType_figures_global_var（图形相关数据类型元数据）
                                      │
                                      ├─ 图形窗口 FigureWindow
                                      │    ├─ 20 个成员命令索引 20..39
                                      │    ├─ 5 个鼠标事件
                                      │    ├─ 8 个固定属性 + 11 个自定义属性
                                      │    └─ figures_GetInterface_FigureWindow
                                      │
                                      ├─ 图形 Figure（隐藏组件）
                                      │    ├─ 20 个成员命令索引 40..59
                                      │    ├─ 1 个空名事件占位
                                      │    ├─ 8 个固定属性 + 3 个自定义属性
                                      │    └─ figures_GetInterface_Figure
                                      │
                                      ├─ 索引 2..4：空数据类型占位
                                      ├─ 图形操作接口 FigureInterface
                                      │    ├─ 60 个成员命令索引 60..119
                                      │    └─ 10 个隐藏空成员占位
                                      └─ 图形类型 FigureType
                                           └─ 111 个整数枚举成员，值 0..110

易语言调用命令
        │
        ▼
PFN_EXECUTE_CMD → figures_*_<index>_figures（figures_cmdDef.cpp）
        │
        ├─ 当前源码：读取若干 pArgInf 到局部变量
        └─ 当前源码：未执行图形操作、未填充返回值、未维护状态

易语言系统通知
        │
        ▼
figures_ProcessNotifyLib_figures
        ├─ NL_GET_CMD_FUNC_NAMES → 返回命令函数名数组（动态库路径）
        ├─ NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名
        ├─ NL_GET_DEPENDENT_LIBS → 返回空依赖列表
        ├─ NL_SYS_NOTIFY_FUNCTION → 转发到 elib/fnshare.cpp
        └─ 其他通知 → 空处理或 NR_ERR
```

## 3. 代码与工程地图

| 路径 | 职责 | 状态 |
|---|---|---|
| `figures.sln` | Visual Studio 解决方案；包含 `figures` 动态库项目和 `figures_static` 静态库项目；配置 Debug/Release、x86/x64 | 已实现（工程声明） |
| `figures.vcxproj` | 动态库工程；编译核心 `.cpp` 和 `elib/fnshare.cpp`；Win32 配置目标扩展名 `.fne`；使用 v141、Windows SDK 10.0.15063.0 | 已实现（工程声明，未在本环境构建） |
| `figures_static/figures_static.vcxproj` | 静态库工程；通过 `..\` 引用同一套源码；定义 `__E_STATIC_LIB` | 已实现（工程声明，未在本环境构建） |
| `figures.vcxproj.filters` / `figures_static/figures_static.vcxproj.filters` | Visual Studio 文件筛选器 | 已实现（工程声明） |
| `figures.vcxproj.user` / `figures_static/figures_static.vcxproj.user` | 用户工程属性；当前为空属性组 | 已实现（空配置） |
| `include_figures_header.h` | 聚合 `elib` 和命令定义；声明动态库元数据数组；用 `FIGURES_DEF` 生成命令函数声明 | 已实现 |
| `figures_cmd_typedef.h` | 命令唯一命名宏、120 项统一命令清单 `FIGURES_DEF` | 已实现（清单/注册定义） |
| `figures_cmdDef.cpp` | 120 个命令/方法执行函数骨架 | 仅声明/骨架；业务执行未实现 |
| `figures_cmdInfo.cpp` | 从 `FIGURES_DEF` 生成 `CMD_INFO` 命令元数据和参数表 | 已实现（元数据） |
| `figures_const.cpp` | 生成 16 项 `LIB_CONST_INFO` 常量表 | 已实现（元数据） |
| `figures_dtType.cpp` | 数据类型、属性、事件、枚举、组件接口回调 | 元数据已实现；组件逻辑未实现 |
| `figures_dllMain.cpp` | `DllMain`、`LIB_INFO`、`GetNewInf`、命令函数指针数组、支持库通知回调 | ABI 骨架已实现；通知业务为空 |
| `Source_figures.def` | 动态库模块定义；导出 `GetNewInf` | 已实现 |
| `elib/mtypes.h` | 基础 Windows/运行时类型别名、几何结构和宏 | 支持库底座声明 |
| `elib/lib2.h` | 易语言支持库 ABI：数据类型、参数/命令/组件/事件/库信息结构及辅助函数 | 支持库底座声明 |
| `elib/krnllib.h` | 系统核心支持库数据类型编号及版本常量 | 支持库底座声明 |
| `elib/lang.h` | 语言编码版本；当前编译语言为 GBK | 已实现（编译约定） |
| `elib/fnshare.h/.cpp` | 系统通知、易语言内存分配、数据复制、数组/字节集辅助函数；维护通知函数指针和调试版本 | 辅助实现；依赖宿主通知回调 |
| `elib/untshare.h` | 组件属性基类及 Windows 组件辅助函数/占位实现 | 支持库底座；部分实现为通用辅助或占位 |
| `elib/PublicIDEFunctions.h` | 易语言 IDE 功能通知编号、参数结构和 IDE 接口声明 | IDE 接口声明；本项目未接入具体 IDE 功能 |

### 3.1 动态库与静态库编译分支

- `figures.vcxproj` 定义 `FIGURES_EXPORTS`、`_WINDOWS`、`_USRDLL`，动态库分支不定义 `__E_STATIC_LIB`。
- `figures_static.vcxproj` 定义 `__E_STATIC_LIB`、`__E_FNENAME=figures`、`_LIB`；它复用父目录源码。
- `figures_cmdInfo.cpp`、`figures_const.cpp`、`figures_dtType.cpp` 的元数据表主要由 `#ifndef __E_STATIC_LIB` 包围；静态库因此不生成动态库登记所需的 `LIB_INFO` 表。
- `figures_dllMain.cpp` 中 `DllMain`、`LIB_INFO`、动态命令函数数组和命令名数组位于动态库分支；静态库只复用命令执行函数及公共定义。
- 动态库 Win32 配置明确 `TargetExt=.fne`；x64 配置未显式设置 `TargetExt`，实际产物扩展名需要在 Windows/MSBuild 环境验证。
- 静态库 x64 配置声明 `PrecompiledHeader=Use`、`PrecompiledHeaderFile=pch.h`，但仓库文件清单未发现 `pch.h`；这可能影响 x64 静态库构建，当前未验证。

## 4. 模块职责与调用链

### 4.1 支持库装载链

1. 宿主按易语言支持库约定查找并调用 `GetNewInf`（`figures_dllMain.cpp:89-92`）。
2. `GetNewInf` 返回静态 `g_LibInfo_figures_global_var`（`figures_dllMain.cpp:31-87`）。
3. `LIB_INFO` 声明：格式号 `LIB_FORMAT_VER`、GUID、版本 2.0.0、中文 GBK、Windows 平台、自定义图形支持库名称、易语言系统最低版本 4.0、系统核心支持库最低版本 4.0，以及命令/数据类型/常量表地址。
4. 宿主通过 `m_pfnNotify=figures_ProcessNotifyLib_figures` 接收库通知处理函数。
5. 动态库通过 `Source_figures.def` 导出 `GetNewInf`；其他函数由 `LIB_INFO` 指针或内部命名约定访问。

### 4.2 命令注册链

1. `figures_cmd_typedef.h:12-133` 的 `FIGURES_DEF(_MAKE)` 是唯一命令清单，索引连续为 0..119。
2. `include_figures_header.h:22-24` 用宏展开产生每个执行函数的 `extern "C"` 声明。
3. `figures_cmdInfo.cpp:131-141` 用同一清单生成 `CMD_INFO g_cmdInfo_figures_global_var[]` 和数量。
4. `figures_dllMain.cpp:26-29` 用同一清单生成 `PFN_EXECUTE_CMD g_cmdInfo_figures_global_var_fun[]`。
5. `figures_dllMain.cpp:94-98` 用同一清单生成静态编译使用的命令名数组。
6. `FIGURES_NAME` 将库名、英文标识、索引和库名拼成类似 `figures_test_0_figures` 的唯一符号。
7. 易语言执行命令时进入 `figures_cmdDef.cpp` 对应函数；当前函数没有连接到任何图形模型或绘制引擎。

### 4.3 组件接口链

`figures_dtType.cpp` 为 `FigureWindow` 和 `Figure` 分别提供 `figures_GetInterface_*`。接口号由 `elib/lib2.h:531-549` 定义：

- `ITF_CREATE_UNIT` → `figures_ControlCreate_*`；
- `ITF_PROPERTY_UPDATE_UI` → `figures_PropUpDate_*`；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `figures_PropPopDlg_*`；
- `ITF_NOTIFY_PROPERTY_CHANGED` → `figures_PropChanged_*`；
- `ITF_GET_ALL_PROPERTY_DATA` → `figures_PropGetDataAll_*`；
- `ITF_GET_PROPERTY_DATA` → `figures_PropGetData_*`；
- `ITF_IS_NEED_THIS_KEY` → `figures_PropKetInfo_*`；
- `ITF_GET_NOTIFY_RECEIVER` → `figures_PropNotifyReceiver_*`；
- 图标数据、语言转换、消息过滤等接口分支当前返回 `NULL`。

**源码实际行为：** 两个 `figures_ControlCreate_*` 都只返回 0；属性回调没有保存或读取组件状态；`PropUpDate` 无条件返回 `TRUE`；定制对话框返回 `FALSE` 且将 `*pblModified` 置为 `false`；按键和默认尺寸通知均返回假/0。接口分派已实现，组件生命周期和属性数据处理未实现。

### 4.4 系统通知链

`figures_ProcessNotifyLib_figures`（`figures_dllMain.cpp:101-177`）处理：

- `NL_GET_CMD_FUNC_NAMES`：动态库返回 `g_cmdNamesfigures` 地址；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `figures_ProcessNotifyLib_figures`；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\\0\\0"`，声明无额外静态依赖文件；
- `NL_SYS_NOTIFY_FUNCTION`：将宿主的 `PFN_NOTIFY_SYS` 转交 `elib/fnshare.cpp::ProcessNotifyLib`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 未识别通知：返回 `NR_ERR`。

`elib/fnshare.cpp::ProcessNotifyLib` 会保存系统通知函数指针，并在首次收到系统通知时调用 `NRS_GET_PRG_TYPE` 更新调试/运行版本；资源释放和命令名/通知名/依赖列表分支目前为空。`SetUserSysNotify` 可保存用户通知函数，并在处理后转发。

## 5. 数据模型与元数据

本项目没有数据库、文件持久化层、序列化存储或独立图形内存模型。所谓“数据模型”全部是易语言支持库 ABI 的静态描述和由宿主提供的 `HUNIT`/`MDATA_INF`/`UNIT_PROPERTY_VALUE` 等运行时句柄。

### 5.1 支持库元数据

`g_LibInfo_figures_global_var`（`figures_dllMain.cpp:31-87`）字段事实：

| 字段 | 当前值/来源 |
|---|---|
| 格式号 | `LIB_FORMAT_VER`，`elib/lib2.h:1246` 定义为 `20000101` |
| GUID | `{A00037C3-C1F8-4ae7-A724-475B2314045E}` |
| 版本 | 主版本 2、次版本 0、构建号 0 |
| 系统要求 | 易语言 4.0；系统核心支持库 4.0 |
| 名称 | `自定义图形支持库` |
| 语言 | `__GBK_LANG_VER`，值 1；`elib/lang.h:8-14` |
| 平台 | `_LIB_OS(__OS_WIN)`，Windows |
| 作者信息 | 大连大有吴涛易语言软件开发有限公司及其地址、电话、传真、邮箱、主页 |
| 数据类型 | `g_DataType_figures_global_var` 及数量 |
| 命令 | `g_cmdInfo_figures_global_var`、执行函数数组及数量 |
| 常量 | `g_ConstInfo_figures_global_var` 及数量 |
| 依赖文件 | `NULL`；通知接口返回空双零字符串 |

### 5.2 数据类型注册

`g_DataType_figures_global_var`（`figures_dtType.cpp:353-409`）共 7 个数组槽位：

| 索引 | 中文名/英文名 | 类型与成员 | 当前状态 |
|---:|---|---|---|
| 0 | `图形窗口` / `FigureWindow` | Windows 单元；20 个成员命令、5 个事件、19 个属性、`figures_GetInterface_FigureWindow` | 元数据已注册；创建/属性/事件运行时未实现 |
| 1 | `图形` / `Figure` | 隐藏 Windows 单元；20 个成员命令、1 个空名事件、11 个属性、`figures_GetInterface_Figure` | 元数据已注册；创建/属性/事件运行时未实现 |
| 2..4 | 空 | Windows 状态，字段为空 | 占位，未确认用途 |
| 5 | `图形操作接口` / `FigureInterface` | 60 个成员命令；10 个隐藏空成员占位；接口回调为 `figures_GetInterface_Figure` | 元数据已注册；具体操作命令未实现 |
| 6 | `图形类型` / `FigureType` | 枚举；111 个 `SDT_INT` 成员，默认值 0..110 | 枚举元数据已注册 |

`FigureType` 的枚举成员包括“自定义”“简单文本框”“曲线”“矩形”“椭圆”“文档”“多文档”“左箭头”“右箭头”等，完整成员表在 `figures_dtType.cpp:188-300`，值按源码连续为 0..110。不要把这些枚举定义等同于绘制实现。

### 5.3 FigureWindow 属性与事件

固定属性由 `elib/lib2.h:394-406` 的 `FIXED_WIN_UNIT_PROPERTY` 约定提供 8 项：`左边`、`顶边`、`宽度`、`高度`、`标记`、`可视`、`禁止`、`鼠标指针`。

自定义属性位于 `figures_dtType.cpp:130-140`，共 11 项：

1. `文档属性` / `DocProperties`，`UD_CUSTOMIZE`；
2. `文档索引` / `DocIndex`；
3. `文档个数` / `DocCount`，只读声明；
4. `图形个数` / `DocCount`，源码英文名与文档个数重复，疑似命名错误；
5. `背景颜色` / `BackColor`；
6. `边框` / `Border`，6 个选项；
7. `允许滚动` / `AllowScroll`；
8. `显示比例` / `Rate`；
9. `允许编辑` / `AllowEdit`，带 `UW_IS_HIDED`；
10. `允许编辑文本` / `AllowEditText`；
11. `允许右键菜单` / `AllowContextMenu`。

事件位于 `figures_dtType.cpp:306-333`，全部使用 `EVENT_INFO2`、`EV_IS_VER2`、`OS_ALL`，参数都是从 0 开始的图形索引 `SDT_INT`：

- `图形鼠标位置被移动`；
- `图形鼠标进入`；
- `图形鼠标离开`；
- `图形鼠标左键被单击`；
- `图形鼠标左键被放开`。

当前源码只注册事件表，没有看到鼠标消息接收、命中测试、事件派发或 `NotifySys` 触发代码。

### 5.4 Figure 属性

`Figure` 也包含 8 项固定属性（`figures_dtType.cpp:151-158`），自定义属性为：

- `类型` / `Kind`，`UD_PICK_INT`，提供大量图形类型选项；
- `基本属性` / `Properties`，`UD_CUSTOMIZE`；
- `底色` / `BackColor`，`UD_COLOR_TRANS`。

属性声明表达了图形对象的预期表面，但当前回调没有实际读取、写入或保存这些值。

### 5.5 命令与参数模型

- `FIGURES_DEF` 共 120 项，索引 0..119；`g_cmdInfo_figures_global_var_count` 在 `figures_cmdInfo.cpp:136-141` 由数组大小计算。
- 其中 66 项带 `CT_IS_HIDED`，54 项为非隐藏元数据项；隐藏项包括未知名字占位项和 `FigureInterface` 的构造/复制构造/析构函数。
- `FigureWindow` 使用索引 20..39；`Figure` 使用索引 40..59；`FigureInterface` 使用索引 60..119。
- 参数表 `g_argumentInfo_figures_global_var` 在 `figures_cmdInfo.cpp:5-128` 定义，索引 0..73，共 74 个参数描述槽位。
- 参数类型实际使用 `SDT_TEXT`、`SDT_INT`、`SDT_BOOL`、`SDT_BIN`、`DTP_FONT`、`MAKELONG(0x06,0)`/`MAKELONG(0x07,0)` 和 `_SDT_ALL`。
- 参数标志使用 `AS_DEFAULT_VALUE_IS_EMPTY`、`AS_RECEIVE_VAR`、`AS_RECEIVE_ALL_TYPE_DATA`；默认值和引用/数组语义由 ABI 元数据声明。

主要非隐藏命令按职责分组：

| 范围 | 对象 | 能力声明 |
|---:|---|---|
| 20、22 | `FigureWindow` | 加入/删除文档 |
| 25..30 | `FigureWindow` | 取图形接口、加入图形、取得实际宽高、取得全部/选中图形索引 |
| 39 | `FigureWindow` | 刷新显示 |
| 40..41 | `Figure` | 取图形接口、刷新显示 |
| 64..86 | `FigureInterface` | 刷新、位置/大小、边线、文本/字体、旋转、阴影、填充 |
| 96..99 | `FigureInterface` | 图形类型、自定义绘图数据的设置/读取 |
| 102..117 | `FigureInterface` | 刷新、选中、复制/粘贴/删除/剪切、锁定、层次、排列、微调、翻转、跳转、组合/分解 |

以上表格是命令注册信息表达的能力，不是运行能力证明。

### 5.6 常量模型

`figures_const.cpp:4-34` 注册 16 个 `CT_NUM` 常量：

- 对齐：`顶边对齐`、`底边对齐`、`左边对齐`、`右边对齐`、`等宽`、`等高`，值 1..6；
- 微调：`上移`、`下移`、`左移`、`右移`、`底边上移`、`底边下移`、`右边左移`、`右边右移`，值 1..8；
- 翻转：`水平翻转`、`垂直翻转`，值 1、2。

这些常量没有英文名和说明文本；不同类别存在相同数值，调用方必须按命令语义解释。

## 6. 接口边界

### 6.1 对外动态库入口

| 符号/接口 | 位置 | 作用 | 状态 |
|---|---|---|---|
| `GetNewInf` | `figures_dllMain.cpp:89-92`；`Source_figures.def:3-4` | 固定支持库信息入口 | 已实现 |
| `figures_ProcessNotifyLib_figures` | `figures_dllMain.cpp:101-177` | 易语言系统通知处理回调 | 分派骨架已实现，业务处理不完整 |
| `PFN_EXECUTE_CMD` 数组 | `figures_dllMain.cpp:26-29` | 120 个命令执行地址 | 已注册；函数体未实现 |
| `PFN_INTERFACE` 回调 | `figures_dtType.cpp:413-772` | 组件创建、属性、通知接口 | 分派已实现；大多为空回调 |

### 6.2 宿主通知与内存边界

`elib/fnshare.h/.cpp` 定义了支持库与易语言系统之间的边界：

- `NotifySys` 调用宿主传入的 `PFN_NOTIFY_SYS`；未设置时返回 0；
- `ealloc`/`efree` 通过 `NRS_MALLOC`/`NRS_MFREE` 使用宿主内存；
- `CloneTextData`、`CloneBinData`、`CloneTextDataW` 构造易语言格式的文本/字节集数据；
- `GetAryElementInf` 读取易语言数组头的维数和各维长度；
- `GetBinData`、`allocArray` 提供字节集/数组辅助；
- `SetUserSysNotify` 保存并链式调用用户通知函数。

这些辅助函数的指针宽度、调用约定、Windows API 和宿主内存格式都依赖易语言运行时；当前 macOS 环境没有验证 ABI 兼容性。

### 6.3 IDE 接口边界

`elib/PublicIDEFunctions.h` 声明通过 `NES_RUN_FUNC` 调用的 IDE 功能，如文本/帮助读取、文件操作、组件移动/对齐、编译运行、工具窗口和资源编辑等。当前 `figures` 只包含声明，没有在 `figures_ProcessNotifyLib_figures` 的 IDE 通知分支中实现这些功能。

## 7. 依赖与运行环境

| 类别 | 证据 | 结论 |
|---|---|---|
| 操作系统 | `figures_cmd_typedef.h` 全部命令 `_CMD_OS(__OS_WIN)`；`LIB_INFO` 使用 `_LIB_OS(__OS_WIN)` | 目标为 Windows |
| 编译器 | 两个 `.vcxproj` 的 `PlatformToolset=v141` | 需要 Visual C++ v141 工具集 |
| Windows SDK | 两个工程 `WindowsTargetPlatformVersion=10.0.15063.0` | 工程声明依赖该 SDK 版本 |
| C/C++ ABI | `extern "C"`、`WINAPI`、`PFN_EXECUTE_CMD`、`GetNewInf` | 依赖易语言支持库 ABI |
| 编码 | `elib/lang.h:8-14`，`__COMPILE_LANG_VER=__GBK_LANG_VER` | 源码含 GBK/本地编码文本；跨平台读取需保留编码事实 |
| 系统核心支持库 | `figures_dllMain.cpp:39-42` 要求 4.0；`elib/krnllib.h:123-126` 声明本地核心版本 4.5 | 运行时依赖易语言核心支持库，最低要求与头文件声明需在真实环境复核 |
| Windows API | `elib/lib2.h` 包含 `<windows.h>`；`untshare.h` 使用窗口/字体 API | 不能在当前 macOS 直接构建为目标产物 |
| 第三方包/包管理器 | 未发现 `CMakeLists.txt`、`Makefile`、包管理清单或第三方源码目录 | 当前无可见第三方依赖声明 |
| 支持库依赖文件 | `LIB_INFO.m_szzDependFiles=NULL`，通知返回空双零字符串 | 源码未声明额外静态支持文件；系统 DLL/核心库依赖不由该字段完整表达 |

## 8. 运行时状态、持久化与资源管理

### 已看到的状态

- `elib/fnshare.cpp` 维护静态系统通知函数指针 `s_pfnNotifySys`、用户通知函数指针 `s_pfnuserNotifySys` 和调试版本值 `s_isDebug`。
- `LIB_INFO`、命令表、常量表、数据类型表、属性表、事件表均为静态编译期数组。
- 命令执行函数接收宿主传入的 `PMDATA_INF pRetData`、`nArgCount`、`PMDATA_INF pArgInf`。

### 未实现/未发现的状态

- 没有 `Document`、`Figure`、`FigureInterface` 的 C++ 实例、容器或索引表；
- 没有文档新增/删除、当前文档切换、图形增删或选中集合；
- 没有绘制对象、画布、GDI/GDI+ 绘制或命中测试；
- 没有属性序列化实现。`CPropertyInfo::SaveData` 默认返回 0，`LoadData` 不解析数据（`elib/untshare.h:14-69`）；
- 没有事件消息循环、鼠标状态或事件通知；
- 没有显式的 `HGLOBAL` 释放/回收闭环用于图形对象；
- 没有线程模型、锁、并发策略、错误码策略或日志系统。

因此不能把属性/事件/命令元数据描述为已经具备可运行的图形编辑器功能。

## 9. 实现状态矩阵

| 能力 | 源码证据 | 状态 |
|---|---|---|
| 支持库入口 `GetNewInf` | `figures_dllMain.cpp:89-92` | 源码已实现 |
| 导出 `GetNewInf` | `Source_figures.def:1-4` | 源码已实现 |
| 支持库版本/GUID/作者/系统要求声明 | `figures_dllMain.cpp:31-87` | 源码已实现（声明） |
| 120 项命令统一注册 | `figures_cmd_typedef.h:12-133` | 源码已实现（元数据清单） |
| 命令参数类型和标志注册 | `figures_cmdInfo.cpp:5-141` | 源码已实现（元数据） |
| 常量注册 | `figures_const.cpp:4-34` | 源码已实现（元数据） |
| 数据类型/枚举/属性/事件注册 | `figures_dtType.cpp:83-409` | 源码已实现（元数据） |
| 120 个命令函数符号 | `figures_cmdDef.cpp:6-1020` | 仅声明/骨架 |
| 命令参数读取 | `figures_cmdDef.cpp` 多处局部 `argN` | 源码已实现（仅读取） |
| 命令返回值填充 | 应写入 `pRetData`，当前全文未见有效写入 | 未实现 |
| 文档/图形状态维护 | 当前仓库未见模型或容器 | 未实现 |
| 图形绘制与刷新 | `UpdateWindow`/`Refresh` 函数体为空 | 仅声明 |
| 组件创建 | `figures_ControlCreate_*` 返回 0 | 未实现 |
| 属性变更和读取 | 回调为模板分支/固定返回值，无状态对象 | 未实现 |
| 属性序列化 | `SaveData` 返回 0，`LoadData` 不解析 | 未实现/占位 |
| 鼠标事件派发 | 仅有五项事件元数据 | 仅声明 |
| 宿主通知函数接收 | `ProcessNotifyLib` 保存指针并查询运行版本 | 源码已实现（基础桥接） |
| IDE 插件功能 | `NL_IDE_READY` 等分支为空，未设置插件标志 | 未实现 |
| 静态库构建 | 工程文件存在，真实编译未执行 | 未验证 |
| 动态库构建 | 工程文件和 `.def` 存在，真实编译未执行 | 未验证 |
| 易语言 IDE/运行时联调 | 未提供运行环境和测试工程 | 未验证 |

## 10. 测试与验证

### 10.1 仓库内测试现状

- Git 跟踪文件中没有 `test`、`tests`、`spec`、测试工程或 CI 配置；
- 没有 `CMakeLists.txt`、`Makefile`、构建脚本或自动化验收脚本；
- `figures.vcxproj` 仅声明 Visual Studio 编译配置，不等于已经构建通过；
- 源码中的 `_DEBUG` 参数数量检查（`figures_cmdInfo.cpp:126-128`）是编译期调试辅助，不是行为测试。

### 10.2 本轮实际验证

本轮只读检查了：

- 解决方案、动态库和静态库 `.vcxproj`/`.filters`/`.user`；
- `Source_figures.def`；
- 所有根目录 C/C++ 源码和 `elib` 头/源文件；
- Git 工作树、当前提交、远程地址和跟踪文件清单；
- `figures_cmdDef.cpp` 的 120 个函数符号及函数体内容。

源码统计得到：`figures_cmdDef.cpp` 有 120 个 `FIGURES_EXTERN_C void` 命令函数，函数体内除参数局部变量读取外没有有效业务语句。未在 macOS 上运行 Visual Studio/MSBuild，也未加载易语言 IDE/运行时，因此没有宣称构建、装载或联调通过。

### 10.3 后续可执行验证项

在具备 Windows + Visual Studio v141 + 易语言运行时的隔离环境后，应至少验证：

1. Debug/Release、Win32/x64 动态库和静态库是否可编译；
2. 动态库产物是否正确为 `.fne`，且 `dumpbin /exports` 能看到 `GetNewInf`；
3. 易语言是否能成功装载 `LIB_INFO` 并显示命令/数据类型/常量；
4. 120 个命令函数指针数组与命令表索引是否一一对应；
5. `FigureWindow` 组件能否创建并销毁；
6. 属性全部读写、定制数据序列化和旧数据兼容性；
7. 文档/图形增删、图形接口、绘制刷新和坐标单位换算；
8. 鼠标五类事件是否正确命中、派发和携带图形索引；
9. 静态库链接时命名宏是否避免与其他支持库冲突；
10. 宿主通知、内存分配、释放和运行版本识别的 ABI 稳定性。

## 11. 风险、疑点与未确认项

1. **功能实现缺失是首要风险。** 元数据声称支持文档、图形编辑、绘制和事件，但命令函数、组件回调和持久化均为空/占位；调用可能返回未初始化结果或固定假值。
2. **返回值未填充。** 多个命令元数据声明返回 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`、`SDT_BIN` 或数组，但 `figures_cmdDef.cpp` 未对 `pRetData` 写值；真实宿主行为未验证。
3. **组件创建恒返回 0。** `figures_ControlCreate_FigureWindow` 和 `figures_ControlCreate_Figure` 不能提供可用 `HUNIT`，因此 IDE 设计器和运行时组件路径不能据此认定可用。
4. **属性回调存在模板遗留语义。** `figures_PropGetData_*` 的 `case 0` 不赋值却在 `Figure` 路径返回 `true`；这不是有效属性读取实现。
5. **属性英文名重复。** `FigureWindow` 的“文档个数”和“图形个数”都使用 `DocCount`，可能导致 IDE/序列化字段冲突，需在真实编译和 IDE 中复核。
6. **枚举/成员存在占位数据。** `FigureInterface` 具有 10 个隐藏空成员；数据类型索引 2..4 为空；`Figure` 有 1 个空名事件。这些可能来自生成模板或兼容性槽位，真实用途未确认。
7. **x64 静态库预编译头疑点。** `figures_static.vcxproj` 的 x64 配置使用 `pch.h`，仓库清单无该文件；需在 Windows 工具链复核。
8. **动态库 x64 后缀未明确。** `.fne` 只配置在 Win32 条件组，x64 产物扩展名未由工程显式指定。
9. **源码编码依赖 GBK。** 多个源码文件被 `file` 识别为 ISO-8859/扩展 ASCII，实际含中文本地编码和 CRLF；工具链转换编码可能破坏字符串或注释。
10. **宿主 ABI 未验证。** `DWORD`、句柄、指针转换和 `NotifySys` 参数依赖 Windows/易语言 ABI；不能在 macOS 本地编译结果替代 Windows 验证。
11. **资源释放链不完整。** `CloneTextData`/`CloneBinData` 需要宿主 `efree`，而命令本身尚未实现返回数据；未来实现必须明确所有权和释放责任。
12. **版本依据可能存在上下文差异。** `LIB_INFO` 最低要求系统核心支持库 4.0，而 `elib/krnllib.h` 注释给出核心版本 4.5；这是最低要求与头文件版本的差异，不能仅凭源码判定兼容范围。

## 12. Git 基线与证据路径

### 12.1 当前基线

- 仓库根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/figures`
- 分支：`master`
- HEAD：`a804e8afa2348a16ac7018a81c730ec1ffe32b49`
- 提交主题：`初始化仓库`
- 提交时间：`2022-12-19T16:09:02+08:00`
- 远程：`https://gitee.com/JYtechnology/figures.git`
- 本轮未执行 fetch、pull、checkout、commit、reset 或其他 Git 写操作。
- 本轮唯一允许的写入是新增本文件 `ARCHITECTURE.md`；未修改源码、工程、依赖、测试、配置或 Git 元数据。

### 12.2 关键证据索引

| 事实 | 证据路径 |
|---|---|
| 解决方案包含动态/静态两个项目 | `figures.sln:5-7` |
| 配置为 Debug/Release、x86/x64 | `figures.sln:10-32` |
| 动态库源码清单与 `.fne` Win32 后缀 | `figures.vcxproj:21-42,95-105` |
| 动态库平台工具集和 SDK | `figures.vcxproj:43-75` |
| 静态库复用父目录源码并定义 `__E_STATIC_LIB` | `figures_static/figures_static.vcxproj:21-45,92-96,109-115` |
| 仅导出 `GetNewInf` | `Source_figures.def:1-4` |
| 命令唯一命名与 120 项清单 | `figures_cmd_typedef.h:3-133` |
| 命令参数元数据 | `figures_cmdInfo.cpp:5-141` |
| 16 项常量 | `figures_const.cpp:4-34` |
| 支持库信息、命令/常量/数据类型登记 | `figures_dllMain.cpp:31-98` |
| 系统通知处理 | `figures_dllMain.cpp:101-177` |
| 数据类型、命令索引、属性、事件、枚举 | `figures_dtType.cpp:83-409` |
| 组件接口分派与占位回调 | `figures_dtType.cpp:413-772` |
| 120 个空命令函数骨架 | `figures_cmdDef.cpp:6-1020` |
| 支持库 ABI 类型与结构 | `elib/lib2.h:149-1240` |
| `LIB_INFO` 与 `GetNewInf` 约定 | `elib/lib2.h:1246-1318` |
| 核心支持库版本常量 | `elib/krnllib.h:114-126` |
| GBK 编译语言 | `elib/lang.h:6-14` |
| 内存/数组/字节集/通知辅助 | `elib/fnshare.h:20-102`、`elib/fnshare.cpp:1-71` |
| 属性序列化占位和通用组件辅助 | `elib/untshare.h:14-69,73-271` |
| IDE 功能声明 | `elib/PublicIDEFunctions.h:1-493` |

## 13. 首轮建档结论

`figures` 当前最准确的定位是：**一个面向易语言自定义图形支持库的 Visual C++ ABI/元数据生成骨架，而不是已经可运行的图形编辑支持库。**

已能确认的价值集中在支持库工程组织、统一命令清单宏、动态/静态库命名约定、`LIB_INFO` 登记、组件属性/事件元数据以及易语言宿主通知边界。未能确认、且源码明确尚未实现的部分集中在图形对象模型、文档状态、绘制引擎、命令返回值、属性序列化、组件创建、事件派发和 Windows/易语言真实联调。

后续深挖应继续维护本文件，优先验证真实 Windows 构建/装载链，再按“数据模型与组件生命周期 → 命令执行与返回值 → 属性序列化 → 绘制/事件 → 静态库链接”顺序补充，不应把当前元数据清单直接当作功能完成证明。
