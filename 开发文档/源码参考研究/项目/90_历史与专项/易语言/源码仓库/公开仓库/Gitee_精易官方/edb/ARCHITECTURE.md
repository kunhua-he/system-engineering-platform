# edb 架构档案

> 首轮全量架构建档。本文是 edb 项目根目录唯一的架构事实文档；后续细探只增量维护本文件，不另建平行架构报告。
>
> 现场基线：本地 `master` 与 `origin/master` 均为 `a39ac4bb806b584ff7289f11950f90fd8bc95133`，提交时间 `2022-12-19T16:04:13+08:00`，提交说明为“初始化仓库”。远程为 `https://gitee.com/JYtechnology/edb.git`，远程默认分支为 `master`。

## 1. 项目定位与首轮结论

`edb` 是一个面向易语言支持库 ABI 的 Windows 数据库操作支持库工程，库名元数据为“数据库操作支持库”，元数据说明其设计目标是基于 ADO 访问多种数据库，并提供“数据库连接”和“记录集”两类组件。

但必须区分“元数据宣称的目标”和“当前源码已实现的能力”：当前提交主要是由易语言支持库向导生成的接口、命令描述、常量和组件回调骨架。56 个命令的实现位于 `edb_cmdDef.cpp`，函数体只有参数取值或为空，没有给 `pRetData` 写返回值，也没有数据库句柄、COM/ADO 调用、SQL 执行、记录集读写或文件持久化实现。因此，本版本不能从源码证明可运行的数据库功能。

首轮事实摘要：

- 动态库项目 `edb`：Visual Studio C++ `DynamicLibrary`，Win32/x86 配置通过 `Source_edb.def` 导出 `GetNewInf`，目标扩展名为 `.fne`。
- 静态库项目 `edb_static`：Visual Studio C++ `StaticLibrary`，Win32 配置定义 `__E_STATIC_LIB` 和 `__E_FNENAME=edb`，复用同一批源文件。
- 支持库元数据：库格式 `LIB_FORMAT_VER`（`20000101`），GUID `46E94341933A462383A4DE26B146322C`，版本 `2.7.0`，要求易语言系统 `3.0`、核心支持库 `3.0`，支持 Windows，GBK 语言版本。
- 命令表：56 项，索引 `0..55`；`数据库连接` 类型挂接 15 项，`记录集` 类型挂接 41 项。
- 参数描述：60 项，索引 `0..59`。
- 常量：64 项，索引 `0..63`，均为数值型 ADO/记录集相关常量。
- 自定义数据类型：2 项，`DBConnection`（数据库连接）和 `RecordSet`（记录集）；两者均为 `LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER` 类型，源码未实现实际组件实例。
- 测试：仓库未发现 README、CI、测试目录或测试文件；当前核对未安装依赖、未构建、未启动运行时，符合只读建档边界。

## 2. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
          |
          +-- 动态装载 edb.fne
          |       |
          |       +--> Source_edb.def: GetNewInf
          |       +--> GetNewInf()
          |               +--> LIB_INFO
          |                     +--> g_DataType_edb_global_var[DBConnection, RecordSet]
          |                     +--> g_cmdInfo_edb_global_var[56]
          |                     +--> g_cmdInfo_edb_global_var_fun[56]
          |                     +--> g_ConstInfo_edb_global_var[64]
          |                     +--> edb_ProcessNotifyLib_edb
          |
          +-- 静态链接 edb_static.lib
          |       |
          |       +--> __E_STATIC_LIB / __E_FNENAME=edb 名称改写
          |       +--> edb_*_<index>_edb 命令实现符号
          |       +--> edb_ProcessNotifyLib_edb
          |
          +-- 易语言命令分派
          |       +--> CMD_INFO + PFN_EXECUTE_CMD
          |       +--> edb_Connect... / edb_Open... / edb_Read... / edb_Write...
          |       |       +--> 当前版本仅取 pArgInf 参数或空函数体
          |       |       +--> 没有数据库/ADO/COM/文件实际调用
          |       |
          |       +--> 组件类型元数据
          |               +--> edb_GetInterface_DBConnection / RecordSet
          |               +--> 创建、属性、通知回调
          |               +--> 当前回调多为 TODO、0、FALSE 或空分支
          |
          +-- 系统通知
                  +--> edb_ProcessNotifyLib_edb(NL_SYS_NOTIFY_FUNCTION,...)
                          +--> fnshare.cpp::ProcessNotifyLib
                                  +--> 缓存 PFN_NOTIFY_SYS
                                  +--> NotifySys(NRS_GET_PRG_TYPE,...)
                                  +--> 后续可转发用户通知函数
```

流程图中的“数据库/ADO/COM/文件实际调用”是当前源码的缺口，不是已实现路径；依据为 `edb_cmdDef.cpp` 中 56 个命令函数体和全仓库未出现相应后端调用。

## 3. 真实目录与工程地图

仓库根目录没有业务层、运行时服务层或第三方依赖目录，只有一个解决方案、两个 C++ 工程、命令/元数据源文件和 `elib` 支持库 ABI 头文件。

```text
edb/
├── edb.sln                         # VS 解决方案，edb + edb_static
├── edb.vcxproj                     # 动态库工程
├── edb.vcxproj.filters             # VS 文件筛选器
├── edb.vcxproj.user                # 空用户属性组
├── edb_static/
│   ├── edb_static.vcxproj          # 静态库工程，复用根目录源文件
│   ├── edb_static.vcxproj.filters
│   └── edb_static.vcxproj.user     # 空用户属性组
├── Source_edb.def                  # 动态库导出表，仅 GetNewInf
├── include_edb_header.h            # edb 统一包含入口与 56 个命令声明展开
├── edb_cmd_typedef.h               # EDB_DEF 命令单一事实表（56 项）
├── edb_cmdInfo.cpp                 # ARG_INFO（60 项）和 CMD_INFO 数组
├── edb_cmdDef.cpp                  # 56 个 PFN_EXECUTE_CMD 命令函数骨架
├── edb_const.cpp                   # 64 个 LIB_CONST_INFO 常量
├── edb_dtType.cpp                  # 两个库定义组件、属性和交互回调骨架
├── edb_dllMain.cpp                 # DLL 入口、LIB_INFO、命令函数表、系统通知
└── elib/
    ├── lib2.h                      # 易语言支持库 ABI、类型、命令/库信息结构
    ├── mtypes.h                    # Windows/C 基础类型兼容定义
    ├── fnshare.h / fnshare.cpp     # 系统通知、内存及参数辅助函数
    ├── lang.h                      # GBK/英语/BIG5/SJIS 语言版本宏
    ├── krnllib.h                   # 核心支持库版本及组件常量
    ├── untshare.h                  # 组件/属性辅助声明（本项目未直接 include）
    └── PublicIDEFunctions.h        # 公共 IDE 函数声明（工程纳入，当前源码未直接 include）
```

工程文件以 `edb.vcxproj` 和 `edb_static/edb_static.vcxproj` 为准；两个工程都编译 `elib/fnshare.cpp`、`edb_cmdDef.cpp`、`edb_cmdInfo.cpp`、`edb_const.cpp`、`edb_dllMain.cpp`、`edb_dtType.cpp`，静态工程通过 `..\` 路径复用根目录源文件。

## 4. 启动、装载与 ABI 边界

### 4.1 动态库入口

- `Source_edb.def:1-4` 声明 `LIBRARY`，并在 `EXPORTS` 下导出 `GetNewInf`。
- `edb_dllMain.cpp:7-24` 提供 `DllMain`，四种 DLL 生命周期分支均为空，仅返回 `TRUE`。
- `edb_dllMain.cpp:89-92` 实现 `EXTERN_C PLIB_INFO WINAPI GetNewInf()`，返回静态的 `g_LibInfo_edb_global_var` 地址。
- `edb_dllMain.cpp:31-87` 填充 `LIB_INFO`，把命令、命令函数、数据类型、常量和通知函数连接到易语言系统。

### 4.2 命令符号与分派

`edb_cmd_typedef.h:3-9` 用 `EDB_NAME(_index, _name)` 将命令名称、索引和库名前缀拼成唯一符号，例如 `edb_Connect_0_edb`。`include_edb_header.h:22-24` 用同一张 `EDB_DEF` 表展开全部命令声明。

`EDB_DEF` 的每一项同时携带中文名、英文名、说明、对象类型、Windows 状态、返回数据类型、用户等级、参数数量和 `ARG_INFO` 起始位置。`edb_cmdInfo.cpp:118-128` 再把相同表展开成 `CMD_INFO` 元数据。

动态库模式下，`edb_dllMain.cpp:26-29` 用 `EDB_DEF(EDB_DEF_CMD_PTR)` 生成 `g_cmdInfo_edb_global_var_fun` 函数指针表；`edb_dllMain.cpp:94-98` 生成供静态编译使用的命令名称数组。命令执行 ABI 来自 `elib/lib2.h:1235-1239`：

```text
PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

`MDATA_INF` 位于 `elib/lib2.h:780-824`，并使用一字节结构对齐（`#pragma pack(1)`）。参数读取采用其 union 中的 `m_pText`、`m_int`、`m_double`、`m_pByte`、`m_ppText`、`m_ppBin`、`m_int64` 等成员。当前生成代码使用 `pArgInf[1]` 起始的易语言参数约定，但未把结果写入 `pRetData`。

### 4.3 系统通知边界

`edb_ProcessNotifyLib_edb` 在 `edb_dllMain.cpp:101-178` 处理易语言库通知：

- `NL_GET_CMD_FUNC_NAMES`：返回动态库命令函数名称数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `edb_ProcessNotifyLib_edb`；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\\0\\0"`，即未声明额外静态库依赖；
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib` 转交系统通知函数指针；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；未知通知返回 `NR_ERR`。

`elib/fnshare.cpp:11-17` 的 `NotifySys` 通过缓存的 `PFN_NOTIFY_SYS` 转发通知；`ProcessNotifyLib:24-64` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时缓存函数指针，并用 `NRS_GET_PRG_TYPE` 获取程序类型；`SetUserSysNotify:67-71` 记录用户通知回调。该路径是当前源码中唯一可确认的运行时通知转发链。

## 5. 命令、数据类型与调用面

### 5.1 数据库连接类型

`edb_dtType.cpp:85-101` 的命令索引为：

```text
0, 1, 2, 53, 3, 4, 5, 6, 7, 8, 54, 55, 9, 10, 11
```

对应连接、连接 Access、连接 SQL Server、连接持久文件、关闭、执行 SQL、取得/设置权限、连接超时、事务、置/取连接、置/取命令超时等命令。

类型名为 `数据库连接` / `DBConnection`，元数据说明为“用来连接大多数数据库”。属性包括固定的 `left`、`top`、`width`、`height`、`tag`、`visible`、`disable`、`MousePointer`，以及只读的 `LastError`、`IsConnect`、`ProviderName`、`Version`。

### 5.2 记录集类型

`edb_dtType.cpp:93-101` 的命令索引为：

```text
12, 13, 14, 15, 48, 16, 17, 18, 19, 20, 21, 22, 23, 51, 24, 25,
49, 26, 27, 28, 29, 52, 30, 31, 50, 32, 33, 34, 35, 36, 37, 38,
39, 40, 41, 42, 43, 44, 45, 46, 47
```

类型名为 `记录集` / `RecordSet`，元数据说明为打开并操作记录集。命令面覆盖打开/关闭、排序、增删改、文本/数字/逻辑/日期/字节集/长整数读写、记录移动、字段元数据、查找、过滤、XML/ADTG 保存等。

属性除固定的八项外，还包括只读的 `IsConnect`、`Status`、`RecordsCount`、`FieldsCount`、`BOF`、`EOF`、`Pos`。

### 5.3 实现现状核对

`edb_cmdDef.cpp` 明确生成了索引 `0..55` 的 56 个 `EDB_EXTERN_C void` 函数。逐函数阅读结果如下：

- 39 个函数体只把 `pArgInf` 成员绑定到局部变量；
- 17 个函数体为空；
- `pRetData` 只出现在函数签名中，未出现结果写入；
- 未发现 `ADO`、`ADODB`、`CoCreate`、`NotifySys`、`MFree`、SQL 执行、连接句柄、记录集句柄或文件 I/O 调用。

因此命令表可以被 IDE 识别和展示，但当前版本不能完成命令说明中承诺的数据库操作。

## 6. 常量、数据模型与持久化

### 6.1 常量表

`edb_const.cpp:4-82` 生成 `g_ConstInfo_edb_global_var`，共有 64 个数值常量，分为：

- 连接权限：`ModeUnknown`、`ModeRead`、`ModeWrite`、`ModeReadWrite`、共享/独占权限；
- 命令类型：`CmdSQL`、`CmdTableName`、`CmdStoredProc`、`CmdPersistFile`；
- 字段属性位：`FldMayDefer`、`FldUpdatable`、`FldIsNullable`、`FldLong` 等；
- ADO 数据类型编号：`BigInt`、`Binary`、`Boolean`、`BSTR`、`Currency`、`Date`、`DBDate`、`DBTime`、`DBTimeStamp`、`Decimal`、`Double`、`Integer`、`Variant` 等；
- 搜索方向和游标类型：`SearchForward`、`SearchBackward`、无游标/服务器端/客户端游标。

常量是描述和编译期元数据，不是数据库状态存储。

### 6.2 持久化边界

命令描述中出现 `保存到XML`、`保存到ADTG`、`连接持久文件`，但 `edb_cmdDef.cpp` 对应函数没有文件操作；库信息的 `m_szzDependFiles` 在 `edb_dllMain.cpp:86` 为 `NULL`，系统通知中的依赖列表也返回空字符串。因此当前源码没有可确认的数据库连接持久化、记录集持久化或内部数据库存储层。

## 7. 技术栈、依赖与构建契约

### 7.1 工具链与配置

依据 `edb.vcxproj` 和 `edb_static/edb_static.vcxproj`：

- Visual Studio 工程版本 `VCProjectVersion 16.0`，解决方案记录 Visual Studio 17；
- Windows SDK `10.0.15063.0`；
- `PlatformToolset` 为 `v141`；
- 配置为 `Debug/Release` × `Win32/x64`；解决方案将 `x86` 映射到 `Win32`；
- 动态项目 `ConfigurationType=DynamicLibrary`，静态项目 `ConfigurationType=StaticLibrary`；
- Win32 动态 Release 使用 `Source_edb.def`，目标扩展名 `.fne`；
- Debug/Release 均为静态运行库 `MultiThreadedDebug` / `MultiThreaded`；开启 `SDLCheck`、Level 3 警告；
- 头文件直接依赖 `elib/lib2.h` 中的 Windows 头 `windows.h`、`stdio.h`、`math.h` 及本项目 `elib` ABI 头文件；仓库未提供第三方库源码或包管理清单。

### 7.2 动态与静态编译宏

- 动态 Win32 的预处理定义包含 `__E_FNENAME=edb; WIN32; EDB_EXPORTS; _WINDOWS; _USRDLL`；
- 静态 Win32 的预处理定义包含 `__E_STATIC_LIB; __E_FNENAME=edb; WIN32; _LIB`；
- `elib/lib2.h:23-25` 强制要求先定义 `__E_FNENAME`，否则预处理直接报错；
- 两个工程的 x64 配置没有看到 `__E_FNENAME=edb`；静态 x64 也没有 `__E_STATIC_LIB`。此外静态 x64 配置把 `PrecompiledHeader` 设为 `Use` 并指定 `pch.h`，仓库中没有 `pch.h`。这些是未执行构建前的高风险配置缺口，不能在当前核对断言具体编译错误。
- 动态 x64 配置未配置 `TargetExt=.fne`，也未看到 `ModuleDefinitionFile=Source_edb.def`；这与 Win32 动态配置存在差异，应在后续 Windows 构建复核。

### 7.3 运行时依赖声明

`edb_dllMain.cpp:39-46` 的说明文字写明目标是 ADO，并要求系统具有 ADO `2.10.3711.9` 或以上版本，推荐 MDAC 2.8；但这是库说明字符串，不等同于源码中的链接或运行时依赖。当前项目没有 `#import`、COM 初始化、ADO 类型库、`.lib`、`.dll` 或显式依赖文件声明。

## 8. 组件接口与资源生命周期

`edb_dtType.cpp` 为两个类型各提供 `edb_GetInterface_*`，按 `nInterfaceNO` 返回以下回调：

- `ITF_CREATE_UNIT` → `edb_ControlCreate_*`；
- `ITF_PROPERTY_UPDATE_UI` → `edb_PropUpDate_*`；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `edb_PropPopDlg_*`；
- `ITF_NOTIFY_PROPERTY_CHANGED` → `edb_PropChanged_*`；
- `ITF_GET_ALL_PROPERTY_DATA` → `edb_PropGetDataAll_*`；
- `ITF_GET_PROPERTY_DATA` → `edb_PropGetData_*`；
- `ITF_IS_NEED_THIS_KEY` → `edb_PropKetInfo_*`；
- `ITF_GET_NOTIFY_RECEIVER` → `edb_PropNotifyReceiver_*`。

当前状态：

- 两个 `edb_ControlCreate_*` 都标记 `TODO`，直接返回 `HUNIT 0`；
- 属性全部是模板式回调，取全部属性返回 `0`，按键查询返回 `FALSE`；
- 属性弹窗将 `*pblModified` 置为 `false` 并返回 `FALSE`；
- 设计器默认尺寸通知未填充宽高，返回 `0`；
- 只读属性元数据没有对应的实际对象状态来源。

因此不能从当前源码证明组件创建、对象复制/释放、属性序列化或运行时资源回收已闭环。`elib/lib2.h` 规定了 `MDATA_INF` 中文本、字节集、复合数据和数组指针的所有权注意事项，但 edb 当前没有使用这些规则实现对象生命周期。

## 9. 测试与验证现状

### 已确认存在

- Visual Studio 解决方案和两个工程配置存在；
- 动态导出表、`GetNewInf`、通知函数、命令元数据、常量表、两类组件元数据在源码中均可定位；
- 本地 Git 工作树在建档前无改动，本地与远程 `master` 指针一致；
- 全仓库未发现 `README*`、`AGENTS.md`、`CLAUDE.md`、`细探-*.md`、`ARCHITECTURE.md`、测试目录、测试脚本或 CI 配置。

### 当前核对未执行

- 未安装 Visual Studio/Windows SDK/ADO 或其他依赖；
- 未执行构建、链接、DLL 导出检查、静态库链接、Windows 运行验证；
- 未连接真实数据库，未验证 Access、SQL Server、ADO Provider、事务、记录集、XML/ADTG；
- 未删除任何旧细探文件（现场不存在旧细探）；
- 未提交 Git。

## 10. 风险、未确认项与后续复核点

1. **实现缺口（已确认）**：56 个命令函数是空/参数绑定骨架，数据库功能、返回值和错误处理均未实现。
2. **组件缺口（已确认）**：两个 `HUNIT` 创建回调返回 0，属性数据和生命周期均为模板代码。
3. **x64 构建契约（源码已见风险，待 Windows 复核）**：x64 配置未定义 `__E_FNENAME`，静态 x64 未定义 `__E_STATIC_LIB`，并引用缺失的 `pch.h`；动态 x64 的 `.fne`/`.def` 配置也与 Win32 不一致。
4. **ABI 位宽（待核）**：`elib/mtypes.h` 和 `lib2.h` 使用 `DWORD` 保存句柄、组件 ID、通知参数，并存在把指针转换为 `DWORD`/`INT` 的历史 ABI 约定；x64 下是否可用必须在目标 Windows/易语言运行时实测，不能仅由当前工程配置推断。
5. **ADO 依赖（待核）**：库说明声称基于 ADO，但源码没有 COM/ADO 实现或显式链接；需要后续确认该提交是否仅为待填充模板，或实现位于未纳入仓库的外部支持库。
6. **错误/内存/并发（待核）**：没有数据库对象状态、锁、超时实际控制、错误码转译、内存释放、线程模型或失败恢复路径。
7. **命令元数据质量（待核）**：常量索引 `059/060/061` 的英文名存在重复/可疑命名，需与正式易语言文档或可运行版本对照，但当前核对不擅自修正源码。

## 11. 证据索引

- 工程与装载：`edb.sln:1-40`、`edb.vcxproj:21-202`、`edb_static/edb_static.vcxproj:21-166`、`Source_edb.def:1-4`。
- 动态入口与通知：`edb_dllMain.cpp:1-178`。
- 命令单一事实表：`edb_cmd_typedef.h:1-69`。
- 命令参数与展示元数据：`edb_cmdInfo.cpp:1-131`。
- 命令实现骨架：`edb_cmdDef.cpp:1-487`。
- 数据类型、组件接口和属性：`edb_dtType.cpp:1-546`。
- 常量表：`edb_const.cpp:1-83`。
- ABI 入口：`include_edb_header.h:1-26`、`elib/lib2.h:1-80`、`elib/lib2.h:1235-1318`。
- 参数与返回数据布局：`elib/lib2.h:780-824`。
- 通知转发与内存辅助：`elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-169`。
- 语言与核心库版本：`elib/lang.h:1-18`、`elib/krnllib.h:116-131`。
- Git 基线：本地 `git log`、`git show-ref`、`git ls-remote origin HEAD refs/heads/master`；均指向 `a39ac4bb806b584ff7289f11950f90fd8bc95133`。

## 12. 维护边界

本文件已吸收当前核对源码、工程、入口/ABI/API、依赖、测试、Git 远程和旧细探现场信息。当前未发现旧 `细探-*.md`，后续只维护项目根 `ARCHITECTURE.md`；不得把构建产物、外部快照或其他临时报告作为第二事实源。

## 13. 后续：数据库能力到底落在哪一层

### 13.1 当前核对范围与证据等级

当前核对不是把 `edb` 的声明当成可运行实现，而是把它声明的数据库连接、SQL、事务、游标、记录集、句柄和 ADO/驱动边界映射到系统工程平台的四个职责层。目标仓库的源码证据仍以当前提交为准：

- `edb_cmd_typedef.h:12-27,65-67` 声明了连接、关闭、执行 SQL、连接超时、开始/保存/回滚事务、记录集置/取连接、打开、游标和命令超时等契约。
- `edb_cmdDef.cpp:5-128,468-487` 可见命令函数只读取 `pArgInf` 或保留空函数体；`pRetData` 只出现在 56 个函数签名中，没有写返回值。`edb_cmdDef.cpp:82-101` 的事务三命令、`122-128` 的打开记录集、`468-479` 的持久文件/命令超时均没有后端调用。
- `edb_dtType.cpp:121-153` 只给出 `LastError`、`IsConnect`、`ProviderName`、`RecordsCount`、`BOF`、`EOF`、`Pos` 等元数据；`edb_dtType.cpp:250-265,431-446` 的 `DBConnection` 与 `RecordSet` 创建回调都标记 TODO 并返回 `HUNIT 0`。
- `edb_cmdInfo.cpp:28-39,83-85` 与 `edb_const.cpp:25-26,54-56,79-80` 说明 SQL、ADO `CursorLocationEnum`、OLE `IDispatch/IUnknown`、XML/ADTG 和存储过程等概念，但这些是声明/常量，不是实现证据。
- `edb_dllMain.cpp:44-46,65-86` 的 ADO 说明字符串和空依赖列表不能证明 ADO/COM 已装载；全仓库静态搜索没有 `CoCreate`、`#import`、ADO 类型库、驱动连接、SQL 执行或实际句柄释放路径。

因此，本节分为“源码已确认”和“平台应如何落位”两种语气。后者是后续架构裁决输入，不代表 `edb` 当前已经具备这些平台组件。前置的 `project_context` 工具当前核对错误绑定到华世王镞_v3，属于环境问题；以下结论不使用该错误项目的代码图，完全基于目标 `edb` 本地源码静态证据，验证强度标为弱验证。

### 13.2 唯一单链路

数据库调用不得由网关、模块或项目代码各自直连驱动。目标平台的唯一链路应为：

```text
调用方 / 项目适配层
  -> 统一网关（鉴权、限流、请求取消、统一结果；不持有数据库对象）
  -> 数据库领域模块（可选的业务编排；不拼接第二套驱动逻辑）
  -> 数据库支持库（版本化公共契约、参数/结果/错误归一化）
  -> 运行核心（分配专属执行单元、句柄/租约、超时取消、崩溃回收）
  -> 专属执行单元（一个驱动边界一个会话/进程，真正调用 ADO/ODBC/具体驱动）
  -> 数据库或持久文件提供者
```

`edb` 的 DLL/静态库 ABI 只能作为项目适配层的历史兼容入口：`Source_edb.def:1-4` 导出 `GetNewInf`，`edb_dllMain.cpp:31-87` 组装 `LIB_INFO`，`elib/lib2.h:1235-1239` 定义 `PFN_EXECUTE_CMD`。它不能成为平台第二个网关，也不能让 `edb_cmdDef.cpp` 中的命令函数绕过数据库支持库直接持有 ADO/驱动对象。

### 13.3 四层职责裁决表

| 能力/对象 | 数据库支持库（公共契约） | 专属执行单元（真实数据库边界） | 运行核心（治理与生命周期） | 网关（对外边界） |
|---|---|---|---|---|
| 数据库连接 | 定义 `打开/关闭/连接状态/连接参数引用`、稳定错误码和脱敏诊断；只暴露不透明连接句柄 | 解析已授权的 DSN/密钥引用，创建并持有具体驱动连接；记录驱动会话状态 | 分配执行单元、连接句柄、租约、代际号；检测失联并回收 | 接收打开/关闭请求并返回句柄摘要；不返回原始驱动对象、密码或指针 |
| SQL/存储过程 | 定义 SQL 文本/参数/命令类型/幂等性/超时契约；优先参数化，不承担 SQL 方言执行 | 在同一会话上调用具体驱动，绑定参数，接收驱动原始返回并转成内部结果 | 监督执行预算、取消信号、输出上限、进程组；不解释 SQL 语义 | 只做鉴权、请求大小和策略检查；不能直接 `connect/execute` |
| 事务 | 定义 `begin/commit/rollback`、嵌套层数或保存点语义、同连接约束、未知结果语义 | 在被绑定的同一连接上实际开启/提交/回滚；驱动异常后标记连接是否可复用 | 将事务句柄绑定到连接句柄/执行单元/所有者；超时或崩溃后封存并触发恢复策略 | 只能携带不透明 `connection_handle + transaction_handle`，禁止跨租约拼接提交 |
| 游标 | 定义无/服务端/客户端游标、读取/移动/耗尽/关闭契约；不暴露 ADO 接口指针 | 创建并消费具体驱动 cursor/Recordset，执行 `Move*`、字段读取、过滤和排序 | 维护游标作为连接的从属句柄；连接关闭前排空/关闭游标，防止悬挂句柄 | 只分页/流式转发通用行或块；不把 cursor 对象跨请求传出 |
| 结果/记录集 | 定义统一结果、列/字段类型、空值、行数未知、分页/流式边界、失败形状 | 从驱动 Recordset/rowset 提取并转换；驱动对象只在执行单元内存在 | 负责结果流背压、最大行/字节预算、取消后的排空和临时缓冲清理 | 返回 JSON/二进制/分页结果和证据摘要；不持有结果集句柄 |
| 句柄/指针 | 只定义 opaque id、代际、所有者和有效期字段，不传 `HUNIT`/`IDispatch*`/`IUnknown*` | 持有真实连接、事务、游标和结果对象；不得把 C++/COM 指针跨边界 | 唯一句柄注册表、状态机、租约、过期 tombstone、二次释放幂等性和崩溃批量回收 | 只看到授权范围内的句柄字符串；不得自行制造、猜测或复活句柄 |
| 驱动/ADO | 定义驱动无关能力与 capability/版本报告 | 唯一允许引用 ADO/ODBC/具体发行驱动；驱动差异、COM 初始化和错误文本均在此收口 | 管理独立进程/线程、环境指纹、启动失败和 killpg/进程组回收 | 不知道驱动类名和对象模型，只接收稳定错误码 |

结论：数据库支持库负责“能被平台稳定调用的契约”，专属执行单元负责“真的连库和跑 SQL”，运行核心负责“让连接/事务/游标在时间、故障和所有权约束下可治理”，网关负责“谁能调用以及如何安全进出”。四层不能互相替代。

### 13.4 现有命中、缺口与复用裁决

| `edb` 现有命令/概念 | 源码命中 | 后续落点 | 裁决 |
|---|---|---|---|
| `Connect/ConnectAccess/ConnectSQLServer/Close`、连接超时 | `edb_cmd_typedef.h:13-16,20-21`；函数骨架 `edb_cmdDef.cpp:5-40,69-80` | 数据库支持库定义连接契约；专属执行单元实现 ADO/驱动连接；运行核心持有连接句柄 | **吸收契约，升级支持库**；不复用空函数体 |
| `ExecuteSQL`、存储过程、命令超时 | `edb_cmdDef.cpp:42-50,473-486`；`edb_const.cpp:79` | 支持库定义 SQL/参数/超时/错误；专属执行单元执行；核心监督取消 | **吸收边界，建立专属执行单元**；网关禁止直连 |
| `BeginTrans/CommitTrans/RollbackTrans` | `edb_cmd_typedef.h:22-24`；`edb_cmdDef.cpp:82-101` | 支持库定义同连接事务契约；执行单元绑定实际连接；核心维护事务句柄和未知结果 | **吸收契约，待核实现**；必须以同一连接执行 |
| `SetConnection/GetConnection`、`Open` | `edb_cmd_typedef.h:25-27`；`edb_cmdDef.cpp:103-128` | `RecordSet` 只能绑定仍有效的 connection handle；执行单元创建从属 cursor/result | **吸收依赖关系**；禁止把 `void* m_pCompoundData` 原样穿透网关 |
| 游标/移动/过滤/字段读写/`RecordSet` 属性 | `edb_cmdDef.cpp:133-461`；`edb_dtType.cpp:147-153` | 支持库统一结果/字段契约；执行单元持有 provider cursor；核心治理流式结果 | **吸收契约，专属执行单元实现**；不把 ADO Recordset 当公共类型 |
| `SaveToXML/SaveToADTG/ConnectPersist` | `edb_cmdDef.cpp:291-305,466-471`；`edb_const.cpp:80` | 若继续支持，作为记录集序列化能力或独立文件提供者；不得伪装成数据库事务能力 | **隔离/待核**；当前无文件 I/O 证据，不进入数据库核心最小闭环 |
| ADO、`IDispatch`、`IUnknown`、CursorLocation | `edb_dllMain.cpp:44-46`；`edb_cmdInfo.cpp:39`；`edb_const.cpp:54-56` | 仅专属执行单元/驱动适配层可见；公共层只保留中性枚举和能力报告 | **隔离**；不把 COM 指针或 ADO 常量扩散到网关/模块 |
| `HUNIT`、`MDATA_INF`、`m_pCompoundData` | `elib/lib2.h:526-576,780-824`；创建回调返回 0 | 旧 ABI 只在兼容适配层；平台句柄由运行核心生成 opaque id | **废弃直穿模式**；不把 `DWORD`/指针当平台持久句柄 |

当前项目没有可直接复用的实现、驱动、事务管理器或网关接入代码；可吸收的是命令语义和对象依赖关系。不能以“元数据完整”替代能力命中，也不能因为 ADO 在说明字符串中出现就把 ADO 记为已安装或已验证。

## 14. 同连接事务、结果和句柄的硬约束

`edb` 的声明已经明确：先用“数据库连接”连接，再用“记录集.置连接()”关联连接，之后才能打开记录集（`edb_cmdDef.cpp:103-128`）；事务命令又挂在数据库连接对象上（`edb_cmdDef.cpp:82-101`）。平台化时必须把这一隐含关系变成可验证契约：

1. **连接身份不可替换**：`connection_handle` 至少绑定 `execution_unit_id、owner、project、lease、generation`。连接关闭、租约过期或执行单元重启后，旧句柄一律失效，不得由相同 DSN 重新打开后“复活”。
2. **事务必须同连接**：`transaction_handle` 必须引用唯一的 `connection_handle`。`Begin`、SQL 写入、`Commit`/`Rollback` 均在同一专属执行单元、同一驱动会话和同一连接上执行；另一个连接即使使用同一个 DSN，也不得提交或回滚该事务。
3. **记录集/游标是连接的子资源**：`RecordSet.SetConnection` 只接受同所有者、同执行单元且仍有效的连接句柄。游标/结果集不能跨连接迁移；要换连接，先关闭旧游标和结果，再建立新绑定。
4. **事务和结果集并存要显式声明**：支持库契约必须声明 provider 是否允许事务内打开游标、是否允许提交后继续读取客户端游标、是否必须先关闭结果集。不能以 ADO 某一 provider 的行为推断所有驱动。
5. **网关不转发驱动对象**：跨 HTTP/MCP/进程边界只传 opaque handle、分页 token 或已转换结果；`IDispatch*`、`IUnknown*`、`HUNIT`、C++ 指针、驱动 cursor 对象均不得进入返回 JSON。
6. **连接串不是事务身份**：连接串/密钥引用只用于打开连接；`Commit`/`Rollback` 必须带句柄，不能仅凭 DSN、用户名或数据库名定位连接。这一规则阻止误提交其他请求的同库事务。
7. **同连接并发策略必须固定**：默认一个事务连接在同一时刻只允许一个有序 SQL/游标操作；若 provider 支持并行游标，也必须由执行单元声明并由核心配额控制，不能让网关并发写同一个连接对象。

### 14.1 正常关闭与释放顺序

```text
停止接受新操作
  -> 关闭/耗尽结果流和游标
  -> 对活动事务执行显式 Commit 或 Rollback
  -> 执行单元在同一连接上关闭数据库连接
  -> 运行核心撤销租约、注销句柄并写释放证据
  -> 关闭专属进程/线程及其 stdin/stdout/stderr，回收进程组
```

- 调用方未声明提交时，关闭活动事务不得静默提交；默认走有界回滚，回滚失败则把连接标为不可复用并返回结构化失败。
- `Close(cursor)`、`Close(result)`、`Close(connection)` 和执行单元释放必须幂等；首次释放成功，重复释放返回“已关闭/已失效”而不是再次操作底层指针。
- 释放责任随所有权转移：执行单元创建的驱动连接、cursor、Recordset 和临时结果只能由执行单元关闭；运行核心负责监督和最后回收；网关不直接 `Release`。
- `HUNIT 0` 不是合法数据库连接，也不能作为“尚未创建但可继续使用”的占位句柄。当前 `edb` 创建回调返回 0，故现版本没有可证明的释放闭环。

## 15. 失败、超时、取消、断线和崩溃矩阵

| 场景 | 支持库结果契约 | 专属执行单元动作 | 运行核心动作 | 是否允许复用连接 |
|---|---|---|---|---|
| 参数非法/连接字符串非法 | 稳定 `INVALID_ARGUMENT`，不泄露密码 | 不创建连接；清理已解析的临时数据 | 不登记活跃句柄，写失败证据 | 不适用 |
| 驱动缺失/ADO 不可用 | `PROVIDER_UNAVAILABLE`，附可诊断版本信息 | 启动探测失败即退出，不伪造成功 | 标记宿主不可用，禁止无限重启 | 否 |
| 认证失败/SQL 语法或约束失败 | 错误码、原始驱动信息脱敏、默认不可重试 | 按驱动判断事务是否进入 aborted/failed 状态 | 若事务状态不明，强制进入清理分支 | 仅在确认会话干净后 |
| 连接超时 | `CONNECT_TIMEOUT`，可重试但不隐式重放写操作 | 中断连接建立，关闭底层资源 | 取消启动任务，回收执行单元和租约 | 否 |
| SQL/命令超时 | `COMMAND_TIMEOUT`，标记是否可重试 | 优先调用驱动取消/interrupt；排空响应；同连接回滚 | 到截止时间仍不退出则终止执行单元进程组，所有子句柄失效 | 未确认回滚时否 |
| 用户主动取消 | `CANCELLED`，保留请求/操作 id | 在同一执行单元发取消，禁止新 SQL 进入该连接 | 记录取消证据；等待有限清理，超时升级强杀 | 仅确认驱动回到干净状态后 |
| 网关断开 | 请求型操作默认转取消；已声明后台任务不因连接断开而丢失 | 按核心传入的取消/继续策略执行 | 网关只发信号，核心决定取消和租约归属 | 由任务契约决定 |
| 关闭失败/底层 `Release` 失败 | `RESOURCE_RELEASE_FAILED`，不报告“已关闭”假成功 | 尝试一次有界补偿，之后放弃底层复用 | 句柄 tombstone、记录残留、必要时杀执行单元 | 否 |
| 执行单元崩溃/被 kill | `PROVIDER_CRASHED`；若写事务结果未知必须显式标记 | 进程级资源由 OS 回收，不能在新进程假装接管旧指针 | 回收进程组、批量失效连接/事务/游标/结果句柄并写证据 | 否 |
| 崩溃发生在提交前后边界 | `OUTCOME_UNKNOWN`，禁止自动重复非幂等 SQL | 新执行单元只可执行状态查询/人工恢复协议 | 用 operation id/幂等键/数据库状态查询裁决，不能凭客户端重试猜测 | 原连接否 |

特别规则：超时或取消后“future 已结束”不等于数据库会话已干净；必须由执行单元报告驱动取消、事务状态和结果流排空，运行核心才能决定复用。崩溃时不能把“进程退出码为 0”当成提交成功，也不能用新连接重新执行上一条未知是否提交的写 SQL。

## 16. 资源生命周期表

| 资源 | 创建者 | 持有/转移 | 正常释放 | 失败/超时/取消 | 崩溃清理与残留判据 |
|---|---|---|---|---|---|
| 连接句柄 | 运行核心登记、执行单元实际创建 | 只向同一 owner 的调用方转移 opaque id | 先处理子游标/事务，再 driver close，撤销租约 | 连接状态标记 suspect，回滚失败即销毁 | 核心按执行单元批量 tombstone；句柄表不得仍可调用 |
| 事务句柄 | 支持库发起、执行单元在连接上创建 | 不得脱离连接句柄 | 显式 commit/rollback 后销毁 | 取消后有界 rollback；状态不明记 `OUTCOME_UNKNOWN` | 崩溃后不可恢复为 active；需证据/对账 |
| 游标/Recordset | 执行单元创建 | 作为 connection 的子资源 | 关闭并排空驱动游标、结果流 | 停止读取、取消、释放临时缓冲；失败不再复用 | 连接 tombstone 时子句柄全部失效 |
| 结果/字段值 | 执行单元转换 | 以页、流或受限内存返回，不转移驱动对象 | 调用方消费完或达到 EOF 后释放缓冲 | 超限丢弃剩余流，记录字节/行上限 | 核心回收临时文件/管道，检查无子进程持有 |
| ADO/驱动对象 | 专属执行单元 | 永不跨 ABI/网关转移 | 在创建它的执行单元中按驱动规则 `Close/Release` | 取消后禁止悬挂调用，关闭失败即销毁单元 | 进程退出由 OS 回收，核心记录非正常退出 |
| 执行单元进程/线程 | 运行核心 | 由核心持有进程组/管道 | 先停止接收、排空 I/O、优雅退出、wait 回收 | deadline 后 SIGTERM/SIGKILL/killpg | 验证 pid/进程组不存在、管道关闭、句柄表清空 |
| 网关请求/取消 token | 网关创建 | 只传 operation id 到核心 | 响应结束或取消确认后销毁 | 客户端断线按任务契约取消/继续 | 不得留下无界后台操作或孤儿租约 |

## 17. L0-L4 验证等级与本项目结论

当前核对采用以下统一等级，避免把“命令存在”误写成“数据库功能通过”：

| 等级 | 含义 | 必须有的证据 |
|---|---|---|
| L0 | 只有名称、说明、常量或设计声明 | 元数据/注释/README；不能证明代码路径 |
| L1 | 源码/ABI 静态路径已核对 | 入口、参数、返回槽、对象关系、失败分支和资源责任能在源码定位；仍不等于可运行 |
| L2 | 本地构建与装载烟测 | 目标工具链成功编译链接，导出/静态链接/`GetNewInf` 和命令分派真实可加载；不要求真实数据库 |
| L3 | 真实数据库端到端 | 独立测试数据库上真实连接、同连接事务、SQL、游标/结果、提交/回滚、关闭释放、连接/命令超时和取消通过；至少覆盖一个实际驱动 |
| L4 | 故障与恢复闭环 | 注入断连、驱动失败、超时、取消、执行单元崩溃/强杀、网关断开；验证句柄失效、进程组/管道/锁/临时结果无残留，未知提交结果不被错误重放，并覆盖多驱动差异 |

`edb` 当前分项结论：

| 分项 | 当前最高等级 | 依据 | 未达到原因 |
|---|---|---|---|
| 命令/参数/对象关系 | L1（声明本身含 L0 内容） | `edb_cmd_typedef.h`、`edb_cmdInfo.cpp`、`edb_dtType.cpp` | 只能看到契约和元数据 |
| 连接/SQL/事务/游标/结果行为 | L1 的负向静态证据 | `edb_cmdDef.cpp` 56 个函数无后端调用/返回写入 | 没有实现、构建、真实数据库验证 |
| 句柄/组件生命周期 | L1 的 ABI 与缺口 | `HUNIT`/`MDATA_INF` 定义；创建回调返回 0 | 无对象创建、状态表、关闭、释放实现 |
| ADO/驱动边界 | L0-L1 | ADO 说明字符串、CursorLocation/OLE 常量 | 无 COM/ADO/驱动装载或调用 |
| 运行核心/专属执行单元/网关接入 | L0（目标项目不包含这些层） | 仓库目录和工程文件仅有 edb ABI/模板 | 不应把缺失层推断为已存在 |
| 故障、超时、取消、崩溃恢复 | L0 | 只有命令说明中的超时文字 | 没有取消信号、进程、恢复、残留审计或故障测试 |

所以本项目整体不能标记为 L2、L3 或 L4。后续若平台实现数据库能力，必须分别取得 L2（平台/适配器可装载）、L3（真实数据库链路）和 L4（故障闭环）的独立证据，不能用本仓库的元数据补齐。

## 18. 后续交付：依赖、验收与装配计划

### 18.1 依赖与资源契约

- 数据库支持库只依赖公共结果/错误/能力契约和运行核心公开句柄接口；不得依赖某个具体 ADO/驱动包。
- 每个实际驱动建立独立提供者/专属执行单元边界；驱动异常、版本探测、连接参数差异和取消方式在该边界收口。COM/ADO 若保留，只能在 Windows 专属执行单元中实现。
- 运行核心复用现有句柄、租约、资源监督、进程组和证据机制；不为数据库另建第二套生命周期中心。
- 网关复用统一鉴权、限流、请求/操作 id、统一错误和取消协议；网关代码不得出现数据库驱动 `connect/execute` 或 `Release`。
- 连接、事务、游标、结果的 ownership 必须逐层声明；任何跨进程/网关返回都只能是 opaque id、分页 token 或已转换数据。

### 18.2 最低验收契约（尚未执行）

1. **同连接事务**：打开一个连接，在同一 `connection_handle` 上 `Begin -> 写入 -> 查询 -> Rollback`，确认查询可见性符合驱动契约且回滚后独立连接读不到写入；再测 `Commit`。使用另一连接调用提交/回滚必须被拒绝。
2. **游标/结果生命周期**：同一连接打开记录集，读取字段、移动、EOF/BOF、耗尽结果；关闭游标后句柄不可读，关闭连接后所有子句柄均失效，重复关闭幂等且不出现二次释放。
3. **连接与命令超时**：连接建立超时不留下连接/执行单元；长 SQL 超时触发真实 driver cancel 或执行单元终止，排空/回滚或明确 `OUTCOME_UNKNOWN`，不能只靠客户端 `timeout` 返回。
4. **主动取消与网关断开**：调用方取消和网关断开分别覆盖请求型操作与声明为后台任务的操作；验证核心收到取消、结果流停止、租约有界结束或按契约继续。
5. **崩溃/强杀**：在连接、事务、游标和提交前后注入执行单元崩溃；验证子进程/管道/句柄/临时文件无残留，未知提交不自动重复非幂等 SQL，重启后旧句柄全部失效。
6. **驱动故障与缺失**：缺少驱动、认证失败、SQL 错误、连接断开、取消不支持均返回稳定错误码；禁止用空结果或 `true` 伪造成功。
7. **网关边界**：只通过统一网关调用，审计确认网关/模块没有外部驱动直连；响应不含密码、原始 COM 指针、驱动对象或内部文件路径。

以上场景在当前 `edb` 仓库均未执行；它们是平台装配后的验收契约，不得回填为本项目已通过。

### 18.3 装配计划与裁决

| 波次 | 计划 | 归属 | 当前状态 |
|---|---|---|---|
| 0 | 冻结连接/SQL/事务/游标/结果/句柄的公共契约、错误码、所有权和同连接不变量 | 数据库支持库 + 公共契约 | 待平台需求确认 |
| 1 | 新增/升级数据库支持库：参数化 SQL、连接/事务/结果中性模型、能力和驱动版本报告 | 数据库支持库 | 待核；不复制 `edb_cmdDef.cpp` 空实现 |
| 2 | 按驱动建立专属执行单元，先做一个真实驱动，再扩展 ADO/其他驱动；实现 cancel、timeout、close、错误映射 | 专属执行单元/提供者 | 待建；不在网关内实现 |
| 3 | 接入运行核心句柄、租约、资源预算、进程组、取消、崩溃回收和证据 | 运行核心 | 复用现有公共治理，不新建数据库专属核心 |
| 4 | 通过统一网关注册能力、鉴权、限流、请求/后台任务语义和结果投影 | 网关 | 复用唯一网关；禁止数据库直连侧链 |
| 5 | 以 L2→L3→L4 顺序验收，并对每个驱动单独记录真实证据和残留检查 | 验证/发布门禁 | 未执行 |

最终裁决：**吸收** `edb` 的连接/SQL/事务/游标/记录集语义作为契约研究输入；**升级**数据库支持库和运行核心的既有公共能力；**建立**按驱动隔离的专属执行单元；**复用**唯一统一网关；**隔离** ADO/COM、`HUNIT`、`IDispatch*`/`IUnknown*` 和 XML/ADTG 兼容面；**废弃**“命令函数直接碰驱动、句柄跨网关、按连接串猜事务、超时后盲目重试”的侧链模式。没有 L3/L4 真实证据前，所有实现性结论保持“待核”，不把 `edb` 当前源码升级为生产数据库能力。

## 19. 第四轮：ABI、错误和资源所有权的源码级补证

### 19.1 命令 ABI 的输入、输出和边界条件

命令函数的真实 ABI 不是 C++ 返回值，而是 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`（`elib/lib2.h:1235-1239`）。因此每个命令必须同时满足三条约束：

1. `pArgInf` 是按易语言参数约定从 `pArgInf[1]` 开始读取的数组；源码所有带参数命令都直接这样取值，例如 `edb_Connect_0_edb`、`edb_Open_14_edb` 和 `edb_WriteBin_49_edb`。但当前实现没有检查 `pArgInf`、`nArgCount`、参数数据类型或可空指针，参数不足时存在越界读取风险；这属于源码能确认的 ABI 防御缺口，不应被描述为数据库错误处理。
2. 返回值必须写入 `pRetData` 的 union 及 `m_dtDataType`，输出文本/字节集必须遵循运行时分配和释放协议。`edb_cmdDef.cpp` 的 56 个函数均不写 `pRetData`，所以即使命令元数据声明了 `SDT_BOOL`、`SDT_INT` 或 `SDT_TEXT`，调用者也不能得到可信结果。
3. `m_pText`、`m_pBin`、`m_pCompoundData` 和 `m_pAryData` 是输入侧指针；`m_ppText`、`m_ppBin`、`m_ppCompoundData` 和 `m_ppAryData` 是输出侧指针。`elib/lib2.h:793-817` 明确要求写回文本/字节集前按运行时规则释放旧值，不能把静态缓冲、C++ `new`、普通 `malloc` 或驱动拥有的指针直接写回。

`MDATA_INF` 采用 `#pragma pack(1)`（`elib/lib2.h:775-827`），union 中同时存在标量、指针和 ABI 地址字段。它只能在匹配的易语言运行时、编译器和位宽下解释，不能把序列化后的 `MDATA_INF` 当作跨进程或跨机器协议。当前命令函数既没有输入校验，也没有输出初始化和失败分支，故 L1 只能证明函数签名和参数槽位，不能证明一次合法 ABI 调用会安全返回。

### 19.2 内存分配、返回值和释放责任

`elib/fnshare.h:25-40` 的 `ealloc/efree` 通过 `NotifySys(NRS_MALLOC/NRS_MFREE, ...)` 使用易语言运行时堆；`CloneTextData`、`CloneBinData`、`GetBinData` 和 `allocArray` 也都把结果交给该堆。由此可确定的规则是：

- 运行时拥有的文本、字节集、数组和属性数据只能由匹配的运行时释放；提供者/驱动不能把自己的缓冲所有权转给 `MDATA_INF`。
- 命令输出写回前要区分“借用输入指针”和“新分配结果”；失败时不得留下半初始化的 `m_ppText`/`m_ppBin`，也不得把错误文本写成未终止字符串。
- `CloneTextData`、`CloneBinData` 等辅助函数没有展示分配失败后的统一错误结果；当前 edb 也没有调用它们，因此源码不能证明错误文本、字段字节集或属性数据的释放闭环。
- `edb_PropGetDataAll_*` 返回 `HGLOBAL`，当前直接返回 0；`PFN_GET_PROPERTY_DATA` 的 ABI 注释还要求回调返回的文本/字节数据遵循调用方释放约定。属性回调未实现，不能把返回 0 解读为“无属性数据已安全释放”。

### 19.3 位宽和 COM/句柄 ABI 边界

`HUNIT`、`HGLOBAL`、`HWND`、`HMENU`、`HANDLE` 以及多个通知参数在 `elib/lib2.h`/`mtypes.h` 中定义为 `DWORD`（`lib2.h:526`，`mtypes.h:26,52-58`）。同时，`m_pCompoundData` 等成员是原生指针，`fnshare.h:38` 把指针强制转换为 `DWORD` 后传给 `NRS_MFREE`，`fnshare.cpp:31` 也把 `DWORD dwParam1` 强转为 `PFN_NOTIFY_SYS`。

这形成两个独立边界：

- Win32 目标下这些历史 ABI 字段通常是 32 位，和工程的 `Win32/x86` 目标相容；
- x64 下原生指针、函数指针和 `DWORD` 容器大小不等，指针截断、函数指针截断和 `HUNIT` 无法表示原生地址均是待实测的高风险。工程文件已经显示 x64 宏和 `.def` 配置不完整，但即便补齐工程配置，也不能自动修复 ABI 位宽。

因此 ADO 的 `IDispatch*`/`IUnknown*`、数据库连接对象、游标对象和组件内部指针绝不能塞入 `HUNIT`、`DWORD` 通知参数或 JSON。兼容层若必须支持历史调用，只能在明确的 Win32 进程边界内保存指针，并以 opaque、代际校验的 64 位平台句柄向新架构暴露；不能把旧 ABI 地址当作跨进程句柄。

### 19.4 组件回调的错误和生命周期缺口

`PFN_DLG_INIT_CUSTOMIZE_DATA` 的 ABI 注释允许 `pblModified` 为 `NULL`（`elib/lib2.h:575-577`），但 `edb_PropPopDlg_DBConnection` 和 `edb_PropPopDlg_RecordSet` 都直接执行 `*pblModified = false`（`edb_dtType.cpp:276-282,457-463`）。这是独立于数据库未实现的空指针风险。类似地，`edb_PropGetData_*` 在默认模板分支返回 `true`，却没有填充 `pPropertyVaule`；调用者可能把未初始化属性误认为成功读取。

两个 `ITF_CREATE_UNIT` 回调返回 `HUNIT 0`，且没有对应的销毁回调、对象表、引用计数或通知解绑路径。`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 和 `NR_DELAY_FREE` 在 `edb_dllMain.cpp`/`fnshare.cpp` 中没有释放本库状态；`fnshare.cpp` 的进程级 `s_pfnNotifySys` 与 `s_pfnuserNotifySys` 也没有在卸载时清空。当前虽没有实际分配数据库资源，但 ABI 层已经缺少“创建成功—持有—关闭—释放—卸载解绑”的可验证状态机。

## 20. 数据库连接、事务、游标和错误模型的补充裁决

### 20.1 连接与事务

命令表把 `BeginTrans` 返回值声明为 `SDT_INT`，说明文字表示它可能是嵌套事务层数；但源码没有保存点、嵌套计数、活动连接状态或事务句柄。平台契约不能仅复制这个整数：必须把“层数”作为同一连接内部的可观察状态，把实际事务身份作为独立 opaque handle，并明确 provider 不支持嵌套时是拒绝、映射为保存点，还是只允许深度 1。

`SetMode` 的说明还要求连接处于关闭状态才能修改权限，`SetConnectTimeout` 是连接建立预算，`SetCommandTimeout` 是命令执行预算；三者不是同一个超时，也不能在网关用一个通用 timeout 覆盖。连接建立失败要销毁半成品连接和执行单元；命令超时后只有在驱动报告取消并确认事务/结果流干净时才可复用连接，否则必须标记 suspect 并销毁。

### 20.2 游标、记录集和结果值

`Open` 的参数同时允许 SQL、表名、存储过程、XML/ADTG 持久文件和游标位置；这实际上混合了数据库查询、文件反序列化和结果集定位五类行为。平台实现应先按 source kind 分流，再创建统一 result/cursor；不能让 `CursorLocation`、ADO 字段类型、`IDispatch` 或 `IUnknown` 直接成为公共返回类型。

`RecordsCount=-1`、`Pos=-2/-3/-4` 等说明文字已经承认 provider 可能不支持总数、滚动接口或文件边界。公共契约应保留“未知/不可定位”状态，而不是把这些值转成合法行号；EOF/BOF、字段空值、二进制长度和字段类型转换都必须在结果转换层定义。关闭连接时先关闭游标/记录集；任何连接代际变化都要使其子句柄失效。

### 20.3 错误分层

当前源码没有错误码、错误对象、`LastError` 写入或异常捕获；`LastError` 只是组件只读属性元数据。因此错误不能从 `false`、0、空文本或未写回的 `pRetData` 推断。建议的最小分层为：

```text
ABI/参数错误       INVALID_ARGUMENT / ABI_MISMATCH
连接与提供者错误   PROVIDER_UNAVAILABLE / AUTH_FAILED / CONNECT_TIMEOUT
SQL/记录集错误     SQL_FAILED / RESULT_STATE_INVALID / FIELD_TYPE_MISMATCH
事务结果不确定     OUTCOME_UNKNOWN
资源与生命周期错误 RESOURCE_RELEASE_FAILED / HANDLE_EXPIRED
取消与预算错误     CANCELLED / COMMAND_TIMEOUT
```

原始 ADO/驱动错误文本只能在专属执行单元转换并脱敏后进入诊断字段；公共结果必须包含稳定错误码、可重试判断、操作 id 和资源状态。特别是提交前后崩溃、取消未确认、驱动不支持 interrupt 时，必须返回 `OUTCOME_UNKNOWN` 或不可复用状态，禁止把失败布尔值当作“数据库肯定未执行”。

## 21. 旧细探承接结论与证据边界

本次复核没有发现仓库内独立的 `细探-*.md` 或其他架构事实源；已有根 `ARCHITECTURE.md` 的后续内容已保留，当前核对只在其后追加源码补证。新增结论来自 `edb_cmdDef.cpp`、`edb_cmd_typedef.h`、`edb_dtType.cpp`、`elib/lib2.h`、`elib/mtypes.h`、`elib/fnshare.h` 和 `elib/fnshare.cpp` 的直接阅读。

可升级为“源码已确认”的事实：

- 56 个命令没有写回返回槽，也没有参数计数/类型防御；
- `MDATA_INF` 的输入/输出指针和运行时分配协议在 ABI 头文件中有明确约定，但 edb 没有实现这些约定；
- `HUNIT`/通知参数使用 `DWORD`，辅助释放和通知注册存在指针转 `DWORD` 的历史边界；
- 组件创建返回 0，属性读取/弹窗回调存在空指针和伪成功模板风险；
- 连接超时、命令超时、事务层数、游标位置和字段特殊值只存在命令说明/元数据，没有运行状态来源。

仍不能升级的事实：是否存在未提交的外部 ADO 实现、目标 Windows 运行时的实际调用约定、x64 下宿主是否提供兼容包装、真实 provider 的事务/游标行为、错误文本和资源回收结果。没有 Windows 构建、导出装载、真实数据库和故障注入证据前，项目等级仍为 L1 负向静态证据，整体不是 L2/L3/L4。

## 22. 后续验收新增硬门槛

在原第 18.2 节最低验收之外，装配任何兼容实现还必须增加：

1. 对每个命令以参数缺失、错误类型、空文本、空字节集和输出指针为空进行 ABI 负向测试，确认不越界、不伪成功，并检查 `m_dtDataType` 与返回槽一致。
2. 在 Win32 目标验证 `GetNewInf`、命令函数表、`HUNIT` 和运行时堆释放；在 x64 目标单独验证所有 `DWORD`/指针/函数指针边界，不能复用 Win32 通过结论。
3. 对文本、字节集、数组和属性数据做分配器配对测试：运行时分配由运行时释放，驱动缓冲不跨边界，重复释放和失败路径均无泄漏或悬挂指针。
4. 传入 `pblModified=NULL`、`pPropertyVaule=NULL` 及卸载通知，确认组件回调和通知链安全返回并解除全局回调引用。
5. 为事务嵌套/保存点、同连接游标、未知记录数、EOF/BOF、提交边界崩溃和 `OUTCOME_UNKNOWN` 建立逐 provider 的行为证据；不能以 ADO 常量或命令说明代替真实结果。
