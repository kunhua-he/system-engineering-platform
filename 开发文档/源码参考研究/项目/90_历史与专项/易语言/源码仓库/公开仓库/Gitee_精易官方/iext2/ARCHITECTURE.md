# iext2 架构建档

> 首轮全量架构建档。本文是本项目根目录唯一的架构事实汇总；本轮未发现旧的 `细探-*.md`、README、`AGENTS.md` 或测试文档。说明中的“已实现”仅表示源码中存在可执行的实现路径；“仅声明/元数据”表示接口、描述表或函数骨架存在；“未验证”表示本轮没有在 Windows/易语言 IDE 中运行确认。
>
> 本轮约束：只新增/更新本文件；未修改源码、工程、依赖、测试、配置或 Git 历史。

## 1. 项目定位

`iext2` 是一个面向易语言的 Windows 扩展界面支持库源码，库名为“扩展界面支持库二”。它通过易语言支持库 ABI 向 IDE/运行时注册：

- 全局命令：文档格式转换、图片组处理，以及动画框相关的成员命令；
- 自定义数据类型/窗口组件：超级按钮、 高级影像框、分隔条、超级编辑框、IP 编辑框、动画框、动画物体；
- 枚举/复合数据类型：字符格式、段落格式；
- 组件属性、事件、命令索引和组件交互回调；
- 动态库（`.fne`）与静态库（`.lib`）两种 Visual Studio 工程形态。

源码表现为“支持库 ABI 描述表 + 函数入口骨架”的仓库，而不是完整的控件/编辑器/动画引擎实现：命令实现函数共 118 个，其中 21 个函数体为空、97 个函数体仅读取 `pArgInf` 参数而没有返回值设置、调用或状态变更；组件创建、属性读写、通知等回调也主要返回固定值或原样返回句柄。因此，不能把元数据中描述的功能等同于已经可运行的业务能力。

### 1.1 实现状态口径

| 状态 | 本项目中的含义 |
|---|---|
| 已实现 | ABI 注册、元数据数组、函数指针分派、通知回调转发、内存/数组辅助函数等源码路径存在。是否能在真实易语言环境工作仍需运行验证。 |
| 仅声明/元数据 | 命令名称、参数、返回类型、组件属性、事件、接口函数声明和注册表存在，但没有对应功能逻辑或只返回固定值。 |
| 未验证 | 需要 Windows、Visual Studio、易语言 IDE/运行时或真实支持库加载器才能确认的编译、装载、消息和 UI 行为。 |

## 2. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
          │
          │ 载入支持库文件，按固定导出名查找 GetNewInf
          ▼
Source_iext2.def ──导出──> GetNewInf()
                              │
                              ▼
                   g_LibInfo_iext2_global_var
                    │       │          │
                    │       │          ├── 常量表 g_ConstInfo...
                    │       │          ├── 命令表 g_cmdInfo...
                    │       │          └── 命令函数表 g_cmdInfo..._fun
                    │       │
                    │       └── 自定义类型表 g_DataType...
                    │                  │
                    │                  ├── 命令索引 → IEXT2_DEF 中的命令编号
                    │                  ├── 属性表 UNIT_PROPERTY
                    │                  ├── 事件表 EVENT_INFO2
                    │                  └── 组件接口 iext2_GetInterface_*
                    │
                    └── pfnNotify → iext2_ProcessNotifyLib_iext2
                                      │
                                      ├── NL_SYS_NOTIFY_FUNCTION
                                      │       └── ProcessNotifyLib → fnshare 保存核心通知函数
                                      ├── NL_GET_CMD_FUNC_NAMES（动态/静态桥接）
                                      ├── NL_GET_NOTIFY_LIB_FUNC_NAME
                                      ├── NL_GET_DEPENDENT_LIBS
                                      └── 其余 IDE 生命周期通知（当前多数空处理）

命令调用路径（当前仓库状态）
易语言命令/成员命令 → CMD_INFO 元数据 → PFN_EXECUTE_CMD 函数指针
                         → iext2_*_iext2 函数骨架
                         → 读取 pArgInf（部分命令）/空函数体
                         → 未形成真实控件或文档/图像处理结果

组件路径（当前仓库状态）
IDE 创建组件/修改属性/询问接口
  → LIB_DATA_TYPE_INFO.m_pfnGetInterface
  → iext2_GetInterface_*
  → ControlCreate / PropChanged / PropGetData / PropNotifyReceiver 等回调
  → 创建回调仅返回传入 hUnit，属性全量数据多返回 0，通知逻辑多为空
```

## 3. 目录与工程地图

仓库 Git 基线共 23 个受跟踪文件：16 个源码/头文件/导出定义文件，7 个解决方案/工程/过滤器/用户工程文件。

```text
iext2/
├── iext2.sln                         两个 Visual Studio C++ 工程的解决方案
├── iext2.vcxproj                     动态库工程，ConfigurationType=DynamicLibrary
├── iext2.vcxproj.filters             动态工程的源文件/头文件/elib 过滤器
├── iext2.vcxproj.user                空用户属性组
├── iext2_static/
│   ├── iext2_static.vcxproj          静态库工程，ConfigurationType=StaticLibrary
│   ├── iext2_static.vcxproj.filters  静态工程过滤器
│   └── iext2_static.vcxproj.user     空用户属性组
├── Source_iext2.def                  动态库只导出 GetNewInf
├── include_iext2_header.h            项目统一入口头文件和命令函数声明宏
├── iext2_cmd_typedef.h               IEXT2_DEF 命令单一描述源、名称拼接宏
├── iext2_cmdInfo.cpp                 ARG_INFO、CMD_INFO 元数据数组
├── iext2_cmdDef.cpp                  118 个命令函数骨架
├── iext2_dtType.cpp                  数据类型、属性、事件、组件接口和回调骨架
├── iext2_const.cpp                   4 个库常量
├── iext2_dllMain.cpp                 DLL 入口、LIB_INFO、通知分派、静态命令名数组
└── elib/
    ├── lib2.h                        易语言支持库 ABI、数据类型和回调结构定义
    ├── mtypes.h                      基础 Windows 风格类型与宏的兼容定义
    ├── lang.h                        编译语言版本（GBK）定义
    ├── krnllib.h                     系统核心支持库标识和版本常量
    ├── fnshare.h / fnshare.cpp       核心通知、易内存、文本/字节集/数组辅助函数
    ├── PublicIDEFunctions.h          IDE 辅助功能编号和参数结构声明
    └── untshare.h                    组件/单元相关共享定义
```

工程文件把动态、静态工程都指向同一批核心源文件：`elib/fnshare.cpp`、`iext2_cmdDef.cpp`、`iext2_cmdInfo.cpp`、`iext2_const.cpp`、`iext2_dllMain.cpp`、`iext2_dtType.cpp` 及同一组头文件；静态工程通过 `__E_STATIC_LIB` 改变条件编译路径，而不是维护一套独立实现。

## 4. 模块职责与实现状态

| 模块 | 主要职责 | 当前证据与状态 |
|---|---|---|
| `include_iext2_header.h` | 引入 ABI 头文件，声明全局表，使用 `IEXT2_DEF` 为每个命令生成 `extern` 函数声明。 | **已实现（声明层）**：第 1-24 行；不包含业务实现。 |
| `iext2_cmd_typedef.h` | 用 `IEXT2_DEF(_MAKE)` 维护命令编号、中文名、英文名、说明、类别、返回类型、参数区间；提供 `IEXT2_NAME` 名称拼接。 | **已实现（元数据源）**：第 3-13 行及第 13-130 行；命令功能仍依赖其他文件。 |
| `iext2_cmdInfo.cpp` | 建立 325-340 行的 `ARG_INFO` 与 `CMD_INFO` 数组；参数标志包含默认值、传引用、数组等 ABI 语义。 | **已实现（注册描述）**：第 5-340 行；不是参数运行时校验器。静态库下整个文件主要被 `#if !defined(__E_STATIC_LIB)` 排除。 |
| `iext2_cmdDef.cpp` | 提供 118 个 `PFN_EXECUTE_CMD` 兼容函数入口。 | **仅声明/骨架**：118 个函数中 21 个空体、97 个仅有参数局部变量读取；本轮脚本未发现 `return`、`NotifySys`、`SendMessage` 或其他函数调用。 |
| `iext2_dtType.cpp` | 定义 9 个自定义数据类型、7 组组件属性、5 组事件、2 组枚举成员、命令索引和组件交互回调。 | **元数据已实现；组件行为仅骨架**：`LIB_DATA_TYPE_INFO` 第 739-809 行；接口分派第 813-2078 行。 |
| `iext2_const.cpp` | 注册“禁止更改”“段落居左”“段落居中”“段落居右”4 个数值常量。 | **已实现（常量注册）**：第 3-23 行；`__E_STATIC_LIB` 下不编译该表。 |
| `iext2_dllMain.cpp` | DLL 入口；组装 `LIB_INFO`；导出 `GetNewInf`；为静态编译返回命令函数名、通知函数名和依赖列表。 | **已实现（ABI 外壳）**：第 6-100、101-178 行。生命周期通知除 `NL_SYS_NOTIFY_FUNCTION` 外基本空处理。 |
| `elib/fnshare.cpp` | 保存易语言系统通知函数；将 `NotifySys` 转发到核心；读取调试/编译版本；保存用户通知回调。 | **已实现（共享辅助层）**：第 7-71 行；真实通知函数指针依赖宿主注入，未在本机验证。 |
| `elib/fnshare.h` | 易内存 `ealloc/efree`、文本/字节集复制、数组数据解析、数据类型分类等 inline 辅助。 | **已实现（ABI 辅助）**：第 20-170 行等；实现依赖宿主的 `NotifySys` 和兼容运行环境。 |
| `elib/lib2.h` | 定义 `ARG_INFO`、`CMD_INFO`、`UNIT_PROPERTY`、`EVENT_INFO2`、`LIB_DATA_TYPE_INFO`、`LIB_INFO` 和全部接口回调类型。 | **已实现（协议头）**：参数第 266-292 行，命令第 297-364 行，组件/属性第 692-729 行，库信息第 1246-1318 行。 |
| `Source_iext2.def` | 将 DLL 的公开入口固定为 `GetNewInf`。 | **已实现（导出契约）**：第 1-4 行。 |
| `iext2.vcxproj` / `iext2_static/iext2_static.vcxproj` | 分别构建动态库和静态库。 | **工程声明存在；本轮未验证编译**。动态 Win32 使用 `.fne` 和 `Source_iext2.def`；静态工程使用 `__E_STATIC_LIB`。 |

## 5. 核心数据模型

本项目没有数据库、文件持久化模型或业务实体仓库。核心数据是编译期静态数组和 ABI 结构体指针。

### 5.1 库级模型：`LIB_INFO`

`iext2_dllMain.cpp:31-87` 初始化 `LIB_INFO`：

| 字段 | 实际值/来源 |
|---|---|
| 格式号 | `LIB_FORMAT_VER`，定义于 `elib/lib2.h:1246` |
| GUID | `AF6AD80AA4244A59AFB3D83ECF5173CC` |
| 版本 | 主版本 `2`、次版本 `0`、构建号 `2` |
| 宿主要求 | 易语言 `3.4`；核心库 `3.3` |
| 名称/说明 | “扩展界面支持库二”；“本支持库用作实现对扩展界面组件的支持” |
| 语言/平台 | `__GBK_LANG_VER`；`_LIB_OS(OS_ALL)` |
| 数据类型 | `g_DataType_iext2_global_var`，数量由 `sizeof` 计算 |
| 全局命令类别 | 2 类：`文档格式转换`、`图片组处理` |
| 命令/函数 | `g_cmdInfo_iext2_global_var` 与 `g_cmdInfo_iext2_global_var_fun` |
| 通知 | `iext2_ProcessNotifyLib_iext2`，非空 |
| 常量 | `g_ConstInfo_iext2_global_var`，4 项 |
| 额外依赖文件 | `NULL`，源码没有声明第三方静态库依赖列表 |

### 5.2 命令模型：`ARG_INFO` + `CMD_INFO`

- `ARG_INFO` 保存参数名、说明、数据类型、默认值、参数接收方式；其 `AS_RECEIVE_VAR`、`AS_RECEIVE_ARRAY_DATA`、`AS_DEFAULT_VALUE_IS_EMPTY` 等标志是 IDE/编译器侧契约，不等于 `iext2_cmdDef.cpp` 已经执行校验。
- `CMD_INFO` 保存命令中文/英文名、说明、所属类别、命令状态、返回类型、用户级别、参数数目和参数表起始指针。
- `iext2_cmd_typedef.h` 通过同一份 `IEXT2_DEF` 生成声明、函数指针数组、命令名数组和命令描述，命令编号从 `0` 到 `117`，共 118 个。
- 118 个命令覆盖两类元数据类别：命令编号 23-32 使用类别 `1/2`，其余多数为成员命令类别 `-1`；具体行为由命令说明描述，但当前函数体未产生返回结果。

### 5.3 自定义数据类型模型：`LIB_DATA_TYPE_INFO`

`iext2_dtType.cpp:739-809` 注册 9 项：

| 编号 | 中文名 / 英文名 | 类型 | 命令索引 | 属性 | 事件/成员 |
|---:|---|---|---:|---:|---:|
| 000 | 超级按钮 / `SuperBtn` | Windows 组件 | 0 | 35 | 1 |
| 001 | 高级影像框 / `SuperAnimateBox` | Windows 组件 | 0 | 17 | 0 |
| 002 | 分隔条 / `SplitterBar` | Windows 组件 | 0 | 10 | 1 |
| 003 | 字符格式 / `CharFormat` | 非窗口枚举/成员数据 | 0 | 0 | 5 个成员 |
| 004 | 段落格式 / `ParaFormat` | 非窗口枚举/成员数据 | 0 | 0 | 5 个成员 |
| 005 | 超级编辑框 / `RichEdit` | Windows 组件 | 23 个，索引 0-22 | 21 | 2 |
| 006 | IP 编辑框 / `IPEditBox` | Windows 组件 | 0 | 10 | 1 |
| 007 | 动画框 / `CartoonBox` | Windows 组件 | 83 个，索引 35-117 | 21 | 18 |
| 008 | 动画物体 / `CartoonObject` | Windows 组件、`LDT_IS_FUNCTION_PROVIDER` | 2 个，索引 33-34 | 32 | 0 |

源码数组中合计 146 个组件属性、23 个组件事件、10 个枚举成员。组件属性均以静态 `UNIT_PROPERTY` 表描述；固定窗口属性通常包含左/顶/宽/高、标记、可视、禁止、鼠标指针等 8 项，之后追加组件自身属性。

### 5.4 事件模型：`EVENT_INFO2`

事件数组使用 `EV_IS_VER2`，事件参数使用 `EVENT_ARG_INFO2`，由 `lib2.h:491-522` 定义。已描述的事件包括：

- `SuperBtn`：被单击；
- `SplitterBar`：被拖动，带原位置/目的位置；
- `RichEdit`：内容被改变、选择区被改变；
- `IPEditBox`：地址被改变；
- `CartoonBox`：鼠标按下/放开/双击、进入/离开、位置即将/已经改变、销毁、物体/边界碰撞、越界、自动前进/旋转停止、动画播放完成、监视键被按下等。

这些事件目前只有注册描述。源码中没有看到实际创建窗口、消息循环、鼠标/键盘处理、碰撞检测或事件抛出实现。

### 5.5 属性值模型：`UNIT_PROPERTY_VALUE`

`elib/lib2.h:580-663` 用联合体承载属性值：整数、双精度、逻辑、日期、颜色、文本/文件名和带长度的二进制数据。`PFN_GET_PROPERTY_DATA` 和 `PFN_NOTIFY_PROPERTY_CHANGED` 定义了读取/修改属性的 ABI，但 `iext2_dtType.cpp` 中对应的组件回调没有形成完整的内部状态或 Windows 控件绑定。

## 6. 接口与调用边界

### 6.1 DLL 导出接口

```text
宿主加载 DLL
  → 通过 Source_iext2.def 找到 GetNewInf
  → GetNewInf() 返回 PLIB_INFO
  → 宿主读取 LIB_INFO 中的命令、常量、类型、回调和通知函数
```

- 导出定义：`Source_iext2.def:1-4`；仅公开 `GetNewInf`。
- 实现：`iext2_dllMain.cpp:89-92` 返回 `&g_LibInfo_iext2_global_var`。
- `DllMain` 在 `DLL_PROCESS_ATTACH/DETACH`、线程附加/卸载分支中没有初始化或释放逻辑（`iext2_dllMain.cpp:6-24`）。

### 6.2 命令执行接口

ABI 类型为 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`，定义于 `elib/lib2.h:1236-1239`。动态库路径使用：

```text
IEXT2_DEF
  → IEXT2_NAME(_index, _szEgName)
  → iext2_<英文名>_<编号>_iext2
  → g_cmdInfo_iext2_global_var_fun[]
  → PFN_EXECUTE_CMD
```

目前命令入口只声明/读取参数，没有把结果写入 `pRetData`，也没有调用 Windows RichEdit、图像列表、动画对象或文档转换 API；因此命令契约已描述，运行语义未完成/未验证。

### 6.3 系统通知接口

`iext2_ProcessNotifyLib_iext2` 的实际分支见 `iext2_dllMain.cpp:101-178`：

| 通知 | 当前处理 |
|---|---|
| `NL_SYS_NOTIFY_FUNCTION` | 调用 `ProcessNotifyLib(nMsg, dwParam1, dwParam2)`；这是唯一向 `fnshare.cpp` 传递宿主通知函数的有效初始化路径。 |
| `NL_GET_CMD_FUNC_NAMES` | 返回静态命令函数名数组 `g_cmdNamesiext2`。 |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 返回字符串 `iext2_ProcessNotifyLib_iext2`。 |
| `NL_GET_DEPENDENT_LIBS` | 返回 `"\0\0"`，表示未声明额外依赖文件。 |
| `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` | 分支存在但没有业务动作，返回默认 `NR_OK`。 |
| 未知通知 | `nRet = NR_ERR`。 |

`elib/fnshare.cpp:11-71` 将系统通知函数保存到 `s_pfnNotifySys`，并通过 `NotifySys` 转发；`SetUserSysNotify` 可设置用户回调并返回 `ProcessNotifyLib`。真实宿主通知函数、分配器和消息生命周期本轮未验证。

### 6.4 组件交互接口

每个组件的 `iext2_GetInterface_*` 按 `nInterfaceNO` 分派以下接口：

- `ITF_CREATE_UNIT` → `iext2_ControlCreate_*`；
- `ITF_PROPERTY_UPDATE_UI` → `iext2_PropUpDate_*`；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `iext2_PropPopDlg_*`；
- `ITF_NOTIFY_PROPERTY_CHANGED` → `iext2_PropChanged_*`；
- `ITF_GET_ALL_PROPERTY_DATA` → `iext2_PropGetDataAll_*`；
- `ITF_GET_PROPERTY_DATA` → `iext2_PropGetData_*`；
- `ITF_IS_NEED_THIS_KEY` → `iext2_PropKetInfo_*`；
- `ITF_GET_NOTIFY_RECEIVER` → `iext2_PropNotifyReceiver_*`；
- 图标、语言转换、消息过滤等未提供回调时返回 `NULL`。

`iext2_dtType.cpp:813-878` 是 `SuperBtn` 的代表性分派实现，其他组件采用同一模板。当前回调状态：

- `ControlCreate_*` 标注 `TODO`，返回传入的 `hUnit`，没有创建 Windows 控件；
- `PropUpDate_*` 固定返回 `TRUE`；
- `PropPopDlg_*` 固定返回 `FALSE`；
- `PropChanged_*` 主要返回 `false`，没有属性校验或状态更新；
- `PropGetDataAll_*` 返回 `0`；
- `PropGetData_*` 主要返回 `true`，没有填充属性值；
- `PropKetInfo_*` 固定返回 `FALSE`；
- `PropNotifyReceiver_*` 当前返回 `0`。

## 7. 数据流与资源边界

### 7.1 元数据注册流（已实现）

```text
编译期静态数组
  → g_ConstInfo / g_argumentInfo / g_cmdInfo / g_DataType
  → g_LibInfo_iext2_global_var 的指针和计数
  → GetNewInf
  → 易语言宿主建立支持库索引、命令列表、组件列表和属性/事件编辑信息
```

### 7.2 命令数据流（仅输入读取已出现）

```text
宿主构造 PMDATA_INF
  → PFN_EXECUTE_CMD(pRetData, nArgCount, pArgInf)
  → iext2_cmdDef.cpp 中按位置读取 pArgInf[i].m_int/m_bool/m_pText/...
  → 当前没有稳定的 pRetData 写入、宿主调用或组件状态保存
```

`pArgInf` 的下标在部分代码中从 `0` 开始、部分函数使用 `pArgInf[1]`，实际偏移依赖易语言调用约定和生成器约定；本轮仅确认源码现状，没有在宿主中验证其正确性。

### 7.3 宿主通知和内存流（辅助层已实现，运行未验证）

```text
易语言宿主提供 PFN_NOTIFY_SYS
  → iext2_ProcessNotifyLib_iext2(NL_SYS_NOTIFY_FUNCTION, ...)
  → ProcessNotifyLib
  → fnshare.cpp 保存 s_pfnNotifySys
  → NotifySys → 宿主通知函数
  → NRS_MALLOC/NRS_MFREE 等通知提供 ealloc/efree
```

`CloneTextData`、`CloneBinData`、`GetBinData`、`GetAryElementInf`、`allocArray` 是基于易语言内存/数组格式的辅助函数；它们没有独立的持久化层。

## 8. 工程、编译与依赖

### 8.1 动态库工程

`iext2.vcxproj`：

- Visual Studio C++ 工程，`ConfigurationType=DynamicLibrary`；
- `Debug/Release × Win32/x64` 四种配置；解决方案对 `Debug|x86` 映射到工程 `Debug|Win32`，`Release|x86` 同理（`iext2.sln:17-32`）；
- `PlatformToolset=v141`，Windows SDK `10.0.15063.0`；
- Win32 Debug/Release 定义 `__E_FNENAME=iext2`，目标扩展名 `.fne`，并设置 `Source_iext2.def`；
- x64 配置在工程文件中未看到 `__E_FNENAME=iext2`、`TargetExt=.fne` 或 `ModuleDefinitionFile` 设置；这构成需要在 Windows 工具链中复核的工程风险，不在本轮直接判定为必然编译失败；
- 使用多线程 CRT（Debug `MultiThreadedDebug`，Release `MultiThreaded`）。

证据：`iext2.vcxproj:43-76`、`:95-153`、`:159-198`。

### 8.2 静态库工程

`iext2_static/iext2_static.vcxproj`：

- `ConfigurationType=StaticLibrary`，同样提供 Win32/x64 Debug/Release；
- Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=iext2`；
- x64 配置的预处理器定义没有 `__E_FNENAME=iext2`，且使用 `PrecompiledHeader=Use`/`pch.h`，但仓库文件地图中没有 `pch.h`；这属于未验证工程配置风险；
- Win32 开启 `MultiProcessorCompilation`；
- 静态工程直接引用上级目录源码，不复制代码。

证据：`iext2_static/iext2_static.vcxproj:21-45`、`:48-73`、`:92-163`。

### 8.3 依赖边界

| 依赖 | 证据 | 状态 |
|---|---|---|
| 易语言支持库 ABI | `include_iext2_header.h` 引入 `elib/lib2.h`、`lang.h`、`krnllib.h` | 已声明，真实宿主版本兼容未验证 |
| Windows 风格类型/API 契约 | `elib/mtypes.h`、`krnllib.h`，组件标记使用 `__OS_WIN` | 已声明；在 macOS 本机无法按目标平台验证 |
| 易语言系统通知/内存管理 | `elib/fnshare.h/.cpp` 的 `NotifySys`、`ealloc/efree` | 已实现转发代码；宿主注入未验证 |
| C/C++ 运行库 | `memset`、`memcpy`、`strcmp`、`lstrlenA` 等 | 源码直接使用；未在目标 MSVC 环境编译验证 |
| 第三方静态库 | `LIB_INFO.m_szzDependFiles = NULL`，`NL_GET_DEPENDENT_LIBS` 返回空列表 | 源码未声明第三方依赖；不能据此证明最终链接完全不需系统库 |
| MFC/控件实现库 | 当前 `iext2_cmdDef.cpp`/`iext2_dtType.cpp` 没有形成真实实现调用 | 未发现本仓库内的实现依赖；功能需补齐 |

## 9. 测试、验证与质量基线

### 9.1 仓库内测试现状

- Git 跟踪文件中没有测试目录、测试源文件、测试工程、CI 配置或测试计划；
- 没有发现 `README.md`、`AGENTS.md`、`细探-*.md`；
- 工程文件没有测试目标，也没有 PostBuild 测试命令；
- 因此“测试不存在”与“测试通过”必须严格区分，本项目当前没有可报告的自动化测试结果。

### 9.2 本轮已执行的静态核验

以下是本轮针对源码和工程的实际核验，不代表目标程序运行成功：

- `git status --short --untracked-files=all`：建档前工作树无输出；
- `git ls-files`：确认 23 个受跟踪文件；
- `git log -1 --format='%H%n%ad%n%s' --date=iso-strict`：确认本地提交基线；
- `git ls-remote origin HEAD refs/heads/master`：远程 `HEAD` 与 `master` 均为同一提交；
- 人工读取所有 6 个 `.cpp`、9 个 `elib`/项目头文件、2 个 `.vcxproj`、2 个 `.filters`、`.sln`、`.def` 和 `.user` 文件；
- 脚本核对 `iext2_cmdDef.cpp`：118 个命令函数，21 个空函数体，97 个仅参数读取函数体；
- 脚本核对 `iext2_dtType.cpp`：9 个数据类型、146 个属性条目、23 个事件条目、10 个枚举成员；
- 本轮未运行 `msbuild`、Visual Studio、易语言 IDE、DLL 加载、静态链接、组件创建、命令执行或事件触发。

### 9.3 目标环境验证缺口

```text
Windows + Visual Studio v141/Windows SDK
  → Debug/Release × Win32/x64 动态库编译
  → Debug/Release × Win32/x64 静态库编译
  → 检查 GetNewInf 导出和 .fne/.lib 产物
  → 在易语言 IDE 中注册支持库
  → 验证命令元数据、组件拖放、属性读写、事件触发
  → 验证宿主通知、内存释放、静态编译命令名桥接
```

上述链路全部属于后续验证事项；当前不能声称 DLL 可加载、组件可显示或命令可用。

## 10. Git 基线与版本证据

| 项目 | 基线事实 |
|---|---|
| 本地仓库 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/iext2` |
| 当前分支 | `master` |
| 本地 HEAD | `388ac0b1c8083b7b67f6bc7f81c5ace2383e70ca` |
| 提交时间 | `2022-12-19T16:11:37+08:00` |
| 提交说明 | `初始化仓库` |
| 远程 | `https://gitee.com/JYtechnology/iext2.git` |
| 远程 `HEAD` / `master` | `388ac0b1c8083b7b67f6bc7f81c5ace2383e70ca`（本轮通过 `git ls-remote` 读取） |
| 仓库状态 | 建档前工作树干净；本轮预期只产生根目录 `ARCHITECTURE.md` 未跟踪变更 |
| 历史完整性 | 本地仓库为 shallow repository；仅以当前提交和远程 ref 作为本轮版本证据，未据此推断完整历史 |

## 11. 风险、未确认项与后续复核重点

### 阻断级事实

1. **命令功能未形成。** `iext2_cmdDef.cpp` 的 118 个入口没有任何一个形成可观察的返回/调用/状态更新路径；仅有命令描述和参数读取不能支撑运行时功能。
2. **组件功能未形成。** 7 类组件的创建、属性、通知和数据存取回调主要是模板返回值；没有真实 Windows 控件、动画对象、RichEdit、图片组或事件分发实现。
3. **没有仓库内测试或目标环境验证。** 无法证明工程可编译、支持库可加载、ABI 版本匹配或 UI 行为可用。

### 重要风险

1. **动态/静态 x64 工程宏和输出配置不对称。** x64 工程配置缺少部分 Win32 中存在的 `__E_FNENAME`、`.fne`、`.def` 设置；静态 x64 还引用未在仓库地图中出现的 `pch.h`。需在 Visual Studio 中复核。
2. **参数下标约定未验证。** 一些命令从 `pArgInf[1]` 读取，一些从 `pArgInf[0]` 读取；需要以易语言实际 `PFN_EXECUTE_CMD` ABI 和生成器约定为准，不能仅凭元数据判断正确。
3. **固定返回值可能掩盖失败。** `PropGetData_*` 返回 `true` 但不填充 `UNIT_PROPERTY_VALUE`，`PropUpDate_*` 固定返回 `TRUE`，创建回调返回输入句柄；一旦宿主调用，可能造成假成功或未初始化数据。
4. **资源与生命周期未闭合。** DLL/组件回调没有真实分配、销毁、释放、消息解绑路径；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 等通知为空处理。
5. **编码/ABI 环境依赖。** 库声明 GBK，头文件和 C++ 源码实际以 GB18030/本地编码读取；需要在 Windows 编译器与易语言加载器中确认字符串编码、结构体布局、指针宽度和 `DWORD` 转指针行为。
6. **静态库依赖契约只返回空列表。** 这表示源码没有声明额外支持文件，不等于静态链接所需的 Windows 系统库或宿主符号已被工程正确配置。

### 建议后续复核顺序

1. 先修正/确认 Win32 与 x64 两套工程的预处理器、输出扩展名、`.def`、预编译头和 SDK/toolset 配置；
2. 以 `lib2.h` 的 ABI 为准，为每一个 `PFN_EXECUTE_CMD` 明确参数下标、返回值初始化、数据复制与释放策略；
3. 为组件建立真实 `HUNIT`/窗口句柄与内部状态，完成创建、属性序列化、属性读写、销毁和通知回收；
4. 优先实现 `RichEdit`、图片组命令和 `CartoonBox` 的最小可运行闭环，再补事件和资源生命周期；
5. 在 Windows/易语言环境增加 ABI 烟囱测试：`GetNewInf`、命令/函数指针数量一致性、静态命令名、组件接口索引、属性 round-trip、事件参数和宿主内存释放；
6. 将“声明存在”“函数体有返回”“真实功能可运行”分成独立验收项，避免再次把模板代码当成实现。

## 12. 证据路径索引

以下路径均相对于项目根目录，行号以本轮读取版本为准：

- `iext2_dllMain.cpp:6-24`：DLL 入口；`:26-29` 命令函数指针数组；`:31-87` `LIB_INFO`；`:89-92` `GetNewInf`；`:94-99` 静态命令名；`:101-178` 系统通知分派。
- `iext2_cmd_typedef.h:3-9`：命令名拼接宏；`:12-130` 118 项 `IEXT2_DEF` 命令描述。
- `iext2_cmdInfo.cpp:5-323`：参数 `ARG_INFO`；`:325-327` 调试参数数量；`:330-340` `CMD_INFO` 表和计数。
- `iext2_cmdDef.cpp:1-1239`：118 个命令执行入口及当前空/参数读取骨架。
- `iext2_dtType.cpp:284-313`：组件成员命令索引；`:315-581` 属性表；`:583-737` 事件参数与事件表；`:739-809` 数据类型注册；`:813-2078` 组件接口和回调骨架。
- `iext2_const.cpp:3-23`：常量表。
- `include_iext2_header.h:3-24`：ABI 头引入、全局数组声明、命令声明生成。
- `elib/lib2.h:266-364`：`ARG_INFO`/`CMD_INFO`；`:410-458` `UNIT_PROPERTY`；`:491-522` `EVENT_INFO2`；`:580-729` 属性值与 `LIB_DATA_TYPE_INFO`；`:1246-1318` `LIB_INFO`/导出契约。
- `elib/fnshare.h:20-170`：通知、宿主内存、文本/字节集/数组辅助；`elib/fnshare.cpp:7-71`：通知函数保存与转发。
- `elib/mtypes.h:4-172`：基础类型和兼容宏；`elib/lang.h:6-14`：GBK 编译语言版本；`elib/krnllib.h:114-131`：核心支持库 GUID、名称和版本。
- `iext2.vcxproj:21-48`、`:51-76`、`:95-153`、`:159-198`：动态工程源文件、配置、toolset、输出和定义。
- `iext2_static/iext2_static.vcxproj:21-45`、`:48-73`、`:92-163`：静态工程源文件、配置和 `__E_STATIC_LIB`。
- `iext2.sln:5-32`：动态/静态项目和 Win32/x64 配置映射。
- `Source_iext2.def:1-4`：唯一 DLL 导出 `GetNewInf`。

本文件之后应作为 `iext2` 架构建档的唯一长期维护入口；源码事实发生变化时，优先更新本文件并保留“已实现/仅声明/未验证”的区分。
