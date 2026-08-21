# iext 架构建档

## 1. 项目定位

`iext` 是一个面向易语言的 Windows 扩展界面支持库源码仓库，目标形态是易语言支持库动态库（`.fne`）及其静态库版本。仓库以支持库元数据、命令声明/实现、窗口组件数据类型描述、属性/事件描述和易语言运行时通知适配为主。

本仓库当前更接近“支持库接口与代码生成模板骨架”：命令签名、中文帮助信息、组件属性、事件和库注册信息已经大量声明；命令函数体和组件交互回调仍是空实现或占位实现。因此不能把支持库元数据完整度等同于运行时功能完成度。

证据基线：本地 `master` 与 `origin/master` 同步，提交 `dd0a24d7093cde9fb276510af1100eb00befbbff`（2022-12-19 16:11:21 +08:00，提交说明“初始化仓库”）；远程为 `https://gitee.com/JYtechnology/iext.git`。本建档只读取源码和工程文件，不修改源码、工程、依赖、测试、配置或 Git。

## 2. 总体流程

```text
易语言 IDE / 易语言运行时
        │
        │ 加载支持库并查找固定导出 GetNewInf
        ▼
iext_dllMain.cpp::GetNewInf
        │ 返回 LIB_INFO
        ├──────────────► g_DataType_iext_global_var
        │                  ├─ TreeBox
        │                  ├─ StatusBar
        │                  ├─ ToolBar
        │                  ├─ ListView
        │                  └─ TransLabel
        │
        ├──────────────► g_cmdInfo_iext_global_var
        │                  └─ 90 条命令元数据（iext_cmd_typedef.h）
        │
        ├──────────────► g_cmdInfo_iext_global_var_fun
        │                  └─ 90 个 iext_* 命令函数指针
        │
        ├──────────────► g_ConstInfo_iext_global_var
        │                  └─ 16 个预定义数值常量
        │
        └──────────────► iext_ProcessNotifyLib_iext
                           ├─ 接收 NL_SYS_NOTIFY_FUNCTION
                           │    └─ 转发到 elib/fnshare.cpp::ProcessNotifyLib
                           ├─ 返回静态编译所需函数名/通知函数名/依赖列表
                           └─ 释放、IDE 就绪、菜单、新成员通知目前不处理

易语言命令调用
        │ pRetData + nArgCount + pArgInf
        ▼
iext_cmdDef.cpp 中 iext_<方法>_<序号>_iext
        │
        └─ 当前实现大多只读取参数，函数体没有实际控件操作

窗口组件交互
        │ ITF_* 接口索引
        ▼
iext_dtType.cpp::iext_GetInterface_<组件>
        ├─ 创建组件（当前返回 0）
        ├─ 属性 UI/属性变更/属性读写（当前为占位逻辑）
        ├─ 自定义属性对话框（当前返回 FALSE）
        └─ 通知接收者（当前默认返回 0）
```

## 3. 工程与目录地图

```text
iext/
├── iext.sln                         VS 解决方案，包含 iext 与 iext_static
├── iext.vcxproj                     动态库工程，ConfigurationType=DynamicLibrary
├── iext_static/iext_static.vcxproj  静态库工程，ConfigurationType=StaticLibrary
├── iext*.vcxproj.filters            Visual Studio 文件筛选器
├── iext*.vcxproj.user               用户工程配置文件（未作为运行契约）
├── Source_iext.def                  动态库导出定义，仅导出 GetNewInf
├── include_iext_header.h            总头文件、库级全局元数据声明、命令声明宏展开
├── iext_cmd_typedef.h               90 条命令的单一宏定义表及符号拼接规则
├── iext_cmdInfo.cpp                 命令参数表和 CMD_INFO 元数据表
├── iext_cmdDef.cpp                  90 个命令实现函数的源文件骨架
├── iext_const.cpp                   16 个支持库常量
├── iext_dtType.cpp                  5 个窗口组件的数据类型、属性、事件和交互回调
├── iext_dllMain.cpp                 DllMain、LIB_INFO、GetNewInf、库通知入口
└── elib/
    ├── lib2.h                       易语言支持库宏、数据类型、库信息结构和平台定义
    ├── lang.h                       编码/语言版本宏，当前为 GBK
    ├── krnllib.h                    系统核心支持库类型与版本标识
    ├── mtypes.h                     Windows/基础类型兼容定义、DATE 工具函数
    ├── fnshare.h                    易语言通知、内存、数组和数据类型辅助函数声明/内联实现
    ├── fnshare.cpp                  通知函数指针、调试版本缓存、库通知分发实现
    ├── PublicIDEFunctions.h         IDE 插件/辅助功能编号和参数契约声明
    └── untshare.h                   窗口样式、属性序列化和组件辅助占位实现
```

工程文件将动态、静态工程都指向同一组 6 个 `.cpp` 与公共头文件。解决方案提供 `Debug|x86`、`Release|x86`、`Debug|x64`、`Release|x64`；x86 映射到 Visual Studio 的 `Win32`。

## 4. 模块职责

| 模块 | 源码职责 | 状态 |
|---|---|---|
| `iext_cmd_typedef.h` | 用 `IEXT_DEF(_MAKE)` 同时生成命令声明、元数据、函数名数组和组件命令索引使用的统一命令表；定义 `IEXT_NAME`/`IEXT_NAME_STR` | **已实现（元数据层）** |
| `iext_cmdInfo.cpp` | 建立 91 条参数记录（索引 0~90）和 90 条 `CMD_INFO` 记录；Debug 下提供参数数量断言辅助计数 | **已实现（描述层）** |
| `iext_cmdDef.cpp` | 提供 90 个命令入口，按参数类型从 `pArgInf` 读取输入 | **仅声明/骨架：函数入口存在，业务行为未实现** |
| `iext_dtType.cpp` | 注册 5 个 `LIB_DATA_TYPE_INFO`；定义组件方法索引、属性、事件、接口回调 | **元数据已实现；组件运行时回调仅占位** |
| `iext_const.cpp` | 注册边框、按钮类型/状态、对齐方式等常量 | **已实现（常量描述层）** |
| `iext_dllMain.cpp` | 动态库装载入口、库信息聚合、固定导出 `GetNewInf`、系统通知分发 | **已实现（注册/通知骨架）** |
| `elib/fnshare.cpp` | 保存 `PFN_NOTIFY_SYS`、调用易语言通知、缓存调试/发布类型、接收库通知并转发用户回调 | **已实现（通知适配层）** |
| `elib/fnshare.h` | 易语言内存和数组数据格式辅助函数，如 `ealloc`、`efree`、`GetAryElementInf`、`CloneTextData` | **已实现（内联辅助；依赖宿主通知）** |
| `elib/lib2.h` | 支持库 ABI 基础：类型、命令函数签名、`LIB_INFO`、`DATA_TYPE`、OS 标志和命名宏 | **已实现（协议头）** |
| `elib/mtypes.h`/`krnllib.h`/`lang.h` | 基础类型、系统核心库版本/GUID、语言编码宏 | **已实现（协议头）** |
| `elib/PublicIDEFunctions.h` | IDE 功能编号和参数结构声明 | **仅声明；本项目未接入 AddIn 回调** |
| `elib/untshare.h` | 组件通用辅助函数和序列化/图标等接口 | **部分实现，多个功能保留注释/返回空值** |

## 5. 支持库注册与接口边界

### 5.1 `LIB_INFO` 注册

`iext_dllMain.cpp:31-87` 构造 `g_LibInfo_iext_global_var`，关键字段如下：

- 库格式：`LIB_FORMAT_VER`。
- GUID：`27bb20fdd3e145e4bee3db39ddd6e64c`。
- 版本：`2.0.3`。
- 所需易语言系统版本：`3.0`。
- 所需系统核心支持库版本：`3.0`（注意 `elib/krnllib.h` 自身声明的核心库版本是 `4.5`，两者是不同位置的事实，不能混写）。
- 名称：`扩展界面支持库一`。
- 编码：`__GBK_LANG_VER`。
- 平台标志：`_LIB_OS(OS_ALL)`，但具体数据类型、属性、命令均在元数据中标记为 `__OS_WIN` 或 `OS_ALL`，实际组件能力仍应以宿主和运行验证为准。
- 命令表：`g_cmdInfo_iext_global_var`、实现函数表 `g_cmdInfo_iext_global_var_fun`。
- 数据类型表：`g_DataType_iext_global_var`。
- 常量表：`g_ConstInfo_iext_global_var`。
- 通知函数：`iext_ProcessNotifyLib_iext`。
- 依赖文件列表：返回 `NULL`/`"\0\0"`，仓库没有声明额外第三方静态库文件。

`Source_iext.def:1-4` 的唯一导出为 `GetNewInf`；`iext_dllMain.cpp:89-92` 返回 `LIB_INFO*`。

### 5.2 库通知

`iext_ProcessNotifyLib_iext` 处理以下边界：

- `NL_GET_CMD_FUNC_NAMES`：返回静态编译命令函数名数组。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `iext_ProcessNotifyLib_iext` 文本。
- `NL_GET_DEPENDENT_LIBS`：返回空依赖列表。
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib` 保存宿主 `PFN_NOTIFY_SYS`，使 `fnshare` 的内存和通知辅助函数可工作。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前分支不执行实际逻辑，最终返回默认成功或未处理结果，需运行时验证具体宿主约定。

`elib/fnshare.cpp:11-17` 的 `NotifySys` 只有在宿主通知指针已设置后才转发；`ProcessNotifyLib:24-64` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时缓存通知函数并通过 `NRS_GET_PRG_TYPE` 读取运行版本，随后可调用用户回调。

## 6. 数据模型

本项目没有数据库、配置文件格式、磁盘持久化模型或自有序列化文件。核心数据模型是易语言支持库 ABI 内存结构和静态元数据数组。

### 6.1 命令模型

`IEXT_DEF` 的每项包含：命令序号、中文名、英文符号名、说明、分类、OS 状态、返回 `DATA_TYPE`、用户等级、位图信息、参数数目和参数表指针。命令符号按 `iext_<英文名>_<序号>_iext` 拼接；例如 `GetCount` 序号 0 形成 `iext_GetCount_0_iext`。

`CMD_INFO` 通过命令项指向 `ARG_INFO` 连续区域；参数模型包含中文名、说明、参数类型、默认值和 `AS_*` 接收标志。数组/非数组兼收通过 `AS_RECEIVE_ALL_TYPE_DATA` 表达，默认值通过 `AS_DEFAULT_VALUE_IS_EMPTY` 表达。

### 6.2 组件模型

`g_DataType_iext_global_var` 共 5 个 `LIB_DATA_TYPE_INFO`：

| 中文名 | 英文名 | 命令索引数 | 属性记录 | 事件记录 | 运行时状态 |
|---|---|---:|---:|---:|---|
| 树型框 | `TreeBox` | 25 | 26（8 个固定属性 + 18 个自定义属性） | 8 | 元数据有，创建/读写回调占位 |
| 状态条 | `StatusBar` | 18 | 14（8 + 6） | 0 | 元数据有，创建/读写回调占位 |
| 工具条 | `ToolBar` | 12 | 20（8 + 12） | 2 | 元数据有，创建/读写回调占位 |
| 超级列表框 | `ListView` | 35 | 39（8 + 31） | 9 | 元数据有，创建/读写回调占位 |
| 透明标签 | `TransLabel` | `NULL` | 15（8 + 7） | 0 | 没有命令索引，创建/读写回调占位 |

命令索引来自 `iext_dtType.cpp:205-237`；组件注册来自 `iext_dtType.cpp:516-558`。因此组件命令索引总数为 25+18+12+35=90，与命令总表一致；`TransLabel` 是属性型组件，不挂接命令。

固定属性统一包含 `left`、`top`、`width`、`height`、`tag`、`visible`、`disable`、`MousePointer`。自定义属性使用 `UD_INT`、`UD_TEXT`、`UD_BOOL`、`UD_PICK_INT`、`UD_COLOR`、`UD_COLOR_BACK`、`UD_FONT`、`UD_IMAGE_LIST`、`UD_CUSTOMIZE` 等宿主定义类型。

### 6.3 事件模型

事件只在元数据中描述，不在本仓库的命令实现文件中驱动：

- `TreeBox`：选择、双击、开始/结束编辑、即将扩展/收缩、右键、检查框变化。
- `ToolBar`：按钮单击、按钮下拉。
- `ListView`：当前表项改变、表项激活、表头单击、表项跟踪、左右键单击、开始/结束编辑、检查框变化。

事件参数使用 `EVENT_ARG_INFO2`，返回类型主要为 `_SDT_NULL` 或 `SDT_BOOL`。事件数据位于 `iext_dtType.cpp:422-514`。

### 6.4 宿主数据与内存

`PMDATA_INF`、`DATA_TYPE`、`LIB_INFO`、`UNIT_PROPERTY_VALUE`、`HUNIT`、`PFN_INTERFACE` 等定义由 `elib/lib2.h`/支持库协议头提供。`ealloc`/`efree` 不直接调用 C/C++ 堆，而是通过 `NotifySys(NRS_MALLOC/NRS_MFREE, ...)` 让易语言宿主分配和释放内存；`CloneBinData` 以易语言一维数组头（维数、元素个数）组织字节集数据。仓库没有独立内存所有权文档，具体宿主 ABI 语义未在本地运行验证。

## 7. 真实调用链

### 7.1 加载链

```text
宿主 LoadLibrary
  → 查找 Source_iext.def 导出的 GetNewInf
  → iext_dllMain.cpp::GetNewInf()
  → 返回 g_LibInfo_iext_global_var
  → 宿主读取命令、常量、数据类型及回调地址
  → 宿主发送 NL_SYS_NOTIFY_FUNCTION
  → iext_ProcessNotifyLib_iext()
  → ProcessNotifyLib()
  → 缓存 PFN_NOTIFY_SYS，并可向宿主发送 NRS_* 通知
```

### 7.2 命令链

```text
易语言程序命令
  → 宿主按 CMD_INFO 找到序号和参数定义
  → 按 g_cmdInfo_iext_global_var_fun[序号] 调用
  → iext_cmdDef.cpp::iext_<name>_<index>_iext(pRetData,nArgCount,pArgInf)
  → 当前源码只完成部分 pArgInf 参数读取
  → 实际控件操作、返回值填充和错误处理未实现/未验证
```

### 7.3 组件交互链

```text
宿主按 LIB_DATA_TYPE_INFO 找到组件
  → 调用 iext_GetInterface_<Type>(ITF_*)
  → 获得 PFN_INTERFACE
  → 调用创建、属性更新、属性读写、通知接收者等回调
  → 当前五组实现均为模板式占位
  → TreeBox/StatusBar/ToolBar/ListView/TransLabel 不会在本源码中真正创建可用窗口单元
```

## 8. 接口清单

### 对外 ABI

| 接口 | 位置 | 作用 | 状态 |
|---|---|---|---|
| `GetNewInf()` | `iext_dllMain.cpp:89-92`；`Source_iext.def:3-4` | 返回 `PLIB_INFO` | **已实现** |
| `iext_ProcessNotifyLib_iext()` | `iext_dllMain.cpp:101-178` | 宿主到支持库的通知入口 | **已实现骨架** |
| `PFN_EXECUTE_CMD` | `elib/lib2.h:1234-1239` | 命令统一调用约定 | **协议已声明，业务未实现** |
| `PFN_NOTIFY_LIB`/`PFN_NOTIFY_SYS` | `elib/lib2.h:1229-1230` | 支持库和宿主互相通知 | **协议已声明，部分适配已实现** |

### 命令接口分组

- `TreeBox`：序号 0~18、83~85、87~89，共 25 个，涵盖项目查询/修改、树层级、展开收缩、批量加入、检查框状态。
- `StatusBar`：序号 19~36，共 18 个，涵盖栏目增删、文本/提示、宽度/类型/图片及位置尺寸查询。
- `ToolBar`：序号 37~47、86，共 12 个，涵盖按钮插入/删除、标题/提示/类型/状态/图片和状态位操作。
- `ListView`：序号 48~82，共 35 个，涵盖表项、选择、查找、列、编辑和显示操作。

完整命令名、参数和说明以 `iext_cmd_typedef.h:12-102` 与 `iext_cmdInfo.cpp:5-162` 为准；`iext_cmdDef.cpp:3-822` 是对应实现入口。

## 9. 依赖与构建契约

### 已声明依赖

- Windows SDK：`iext.vcxproj` 和 `iext_static.vcxproj` 声明 `WindowsTargetPlatformVersion=10.0.15063.0`。
- MSVC：两个工程声明 `PlatformToolset=v141`。
- C/C++ Windows API：`lib2.h` 包含 `<windows.h>`、`<stdio.h>`、`<math.h>`；源码使用窗口、字体、样式和消息相关类型/函数。
- 易语言宿主 ABI：`LIB_INFO`、`PFN_NOTIFY_SYS`、`NRS_*`、`NL_*`、`ITF_*`、`UD_*` 等由 `elib` 协议头提供，运行时由易语言宿主提供。
- 编码：`lang.h` 将编译语言设置为 `__GBK_LANG_VER`；源码文件实际混用 GB18030/UTF-16/UTF-8 工程文件编码，需在 Windows/MSVC 环境核对转换链。

### 构建目标

- `iext`：动态库，Win32 配置的 `TargetExt` 为 `.fne`，并使用 `Source_iext.def`；x64 配置未显式设置同样的 `TargetExt`/模块定义文件。
- `iext_static`：静态库，使用 `__E_STATIC_LIB` 和 `__E_FNENAME=iext`；Win32 配置包含 `__E_STATIC_LIB`，x64 配置的预处理宏与预编译头配置和 Win32 不完全一致。
- 两个工程重复编译相同的源码，通过 `__E_STATIC_LIB` 区分动态/静态注册路径。

### 未确认的构建风险

1. `include_iext_header.h:17` 声明 `extern ARG_INFO g_argumentInfo_iext_global_var[]`，而 `iext_cmdInfo.cpp:5` 定义为 `static ARG_INFO ...`；这存在同一翻译单元外部声明与内部定义链接属性不一致的潜在编译问题，尚未在 MSVC 中验证。
2. `iext.vcxproj` 的 x64 配置没有像 Win32 那样显式指定 `TargetExt=.fne` 和 `ModuleDefinitionFile=Source_iext.def`，x64 产物名称/导出契约未验证。
3. `iext_static.vcxproj` 的 x64 配置使用 `<PrecompiledHeader>Use</PrecompiledHeader>` 和 `pch.h`，仓库文件清单中没有 `pch.h`；是否由外部工程环境提供、是否能构建未验证。
4. 本机为 macOS，无法直接运行 Visual Studio/MSVC、Windows SDK 或易语言宿主；不能据此声称任一配置可编译或可加载。

## 10. 测试与验证现状

仓库文件清单中没有测试目录、测试工程、CI 配置或自动化测试脚本。已完成的是静态人工源码/工程阅读与计数核对：

- `iext_cmd_typedef.h` 命令宏记录：90 条。
- `iext_cmdDef.cpp` 函数入口：90 个；其中按函数体文本统计 79 个包含参数读取语句、11 个为空函数体。即使包含参数读取，也没有看到控件操作或 `pRetData` 返回值填充。
- `iext_cmdInfo.cpp` 参数记录：91 条；命令元数据计数由数组 `sizeof` 计算。
- `iext_const.cpp` 常量：16 条。
- `iext_dtType.cpp`：5 个组件；组件命令索引 25/18/12/35/0；属性记录 26/14/20/39/15；事件记录 8/0/2/9/0。
- 组件 `ControlCreate_*` 都初始化 `HUNIT hUnit = 0` 后返回 0；属性获取全部返回 0 或模板值；自定义属性对话框返回 `FALSE`；因此运行时组件功能不能从当前源码证明。

未执行：MSVC 编译、链接、DLL 导出检查、静态库链接、易语言 IDE 加载、真实窗口创建、命令调用、属性序列化、事件触发、宿主内存分配/释放和跨版本兼容性测试。

## 11. 已实现/仅声明/未验证结论

### 源码已实现

- 支持库元数据静态数组及 `GetNewInf` 返回链。
- `GetNewInf` 的 DLL 导出定义。
- 90 条命令的统一元数据定义、参数表和函数入口命名。
- 16 条常量定义。
- 5 个组件的属性/事件/命令索引描述。
- `ProcessNotifyLib` 的通知函数缓存、调试版本读取和用户通知回调转发。
- `fnshare` 中部分易语言内存/数组格式辅助函数。

### 仅声明或骨架

- 命令的真实控件操作、结果写入、异常/错误码处理。
- 五个组件的真实窗口创建、句柄保存、属性同步、序列化和销毁。
- 自定义属性编辑对话框。
- 事件从 Windows 控件消息到易语言事件处理子程序的完整转发。
- `PublicIDEFunctions.h` 所声明的 IDE 辅助功能在本项目中的接入。
- 动态库 x64 产物的 `.fne` 和导出契约。

### 未验证

- 在指定 Visual Studio/MSVC、Windows SDK 和易语言宿主中的编译、链接、加载。
- `elib` 头文件与宿主 ABI 的结构体布局、调用约定和 32/64 位兼容性。
- 工程文件中的潜在链接属性冲突和 x64 预编译头/导出配置问题。
- IE 4.0 或以上依赖说明与当前源码真实实现之间的关系；该依赖只出现在 `LIB_INFO.m_szExplain`，未见工程链接或运行时探针。

## 12. Git 基线与证据路径

- 仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/iext`
- 分支：`master`，跟踪 `origin/master`。
- 提交：`dd0a24d7093cde9fb276510af1100eb00befbbff`。
- 远程：`https://gitee.com/JYtechnology/iext.git`。
- 工作树：建档前为干净状态；本次仅新增目标根目录 `ARCHITECTURE.md`，未改动其他路径。
- 工程入口：`iext.sln:1-40`、`iext.vcxproj:21-202`、`iext_static/iext_static.vcxproj:21-167`。
- 注册与通知：`iext_dllMain.cpp:26-178`、`Source_iext.def:1-4`。
- 命令表/参数/实现：`iext_cmd_typedef.h:1-103`、`iext_cmdInfo.cpp:1-165`、`iext_cmdDef.cpp:1-823`。
- 组件元数据/回调：`iext_dtType.cpp:203-1468`；注册数组从 `516` 行开始，第一组交互实现从 `562` 行开始。
- 常量：`iext_const.cpp:1-35`。
- ABI 与基础类型：`elib/lib2.h:1-1604`、`elib/mtypes.h:1-176`、`elib/lang.h:1-18`、`elib/krnllib.h:1-133`。
- 通知和宿主内存辅助：`elib/fnshare.h:1-380`、`elib/fnshare.cpp:1-71`。
- IDE 功能声明：`elib/PublicIDEFunctions.h:1-493`。
- 通用组件辅助：`elib/untshare.h:1-337`。

本文件为本项目首轮架构事实的唯一权威文档；后续深挖应在本文件增量更新，并继续区分源码事实、仅声明内容和未验证事项。
