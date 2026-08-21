# sqlite3 易语言支持库架构档案

> 本文件是本项目根目录唯一的架构事实源。首轮建档仅依据当前工作树中人工读取的源码、Visual Studio 工程、Git 元数据和文件清单；不把命令声明、注释或工程配置当作已实现功能。后续细探应继续收口到本文件，不另建平行架构文档。

## 1. 项目定位

本仓库意图实现一个面向易语言的 `Sqlite3数据库支持库`，以支持库 ABI/元数据形式向易语言 IDE/运行时暴露 SQLite 数据库、表、记录集和字段信息等对象及命令。`sqlite3_dllMain.cpp:31-87` 的 `LIB_INFO` 明确将库描述为本地关系型文件数据库支持库，说明中声称支持 SQL、事务、触发器、视图，内部文本编码为 UTF-8，目标 SQLite 版本写为 3.7.11。

**当前源码事实：** 仓库内没有 SQLite amalgamation、SQLite 官方头文件、SQLite 静态库或动态库，也没有检索到 `sqlite3_open`、`sqlite3_exec`、`sqlite3_prepare`、`sqlite3_step`、`sqlite3_bind`、`sqlite3_column`、`sqlite3_finalize`、`sqlite3_close` 等 SQLite C API 调用。`sqlite3_cmdDef.cpp` 共生成 230 个命令函数，其中 180 个为空函数体，另外 50 个仅做参数局部变量读取；没有函数写入 `pRetData`，也没有实际数据库状态或 SQL 执行逻辑。因此，本项目在当前提交更准确的定位是：**易语言 SQLite 支持库的接口/元数据骨架与构建外壳，运行时数据库能力尚未在仓库源码中实现或接入。**

实现状态约定：

- **已实现：** 支持库 ABI 框架、命令/参数/自定义数据类型元数据、DLL 导出入口、系统通知转发骨架、动态库/静态库两个工程配置。
- **仅声明：** SQLite 数据库、表、记录集的面向用户命令，以及 `sqlite3_cmd_typedef.h` 中的命令索引和名称映射。
- **未实现或未验证：** SQLite 引擎接入、数据库句柄生命周期、SQL 执行、事务、游标、字段读写、参数绑定、错误返回、内存释放、DLL/静态库实际编译产物和易语言运行时联调。

## 2. 总体定位与数据流

```text
易语言 IDE / 运行时
        │
        │ 加载支持库、读取 LIB_INFO、枚举命令和自定义类型
        ▼
GetNewInf() ───────────────► g_LibInfo_sqlite3_global_var
        │                              │
        │                              ├─ 版本/GUID/库名/依赖描述
        │                              ├─ g_cmdInfo_sqlite3_global_var
        │                              ├─ g_cmdInfo_sqlite3_global_var_fun
        │                              ├─ g_DataType_sqlite3_global_var
        │                              └─ g_ConstInfo_sqlite3_global_var（当前 0 项）
        │
        ├─ 命令调用：PMDATA_INF pRetData + pArgInf
        │             ▼
        │      sqlite3_cmdDef.cpp 中 230 个导出函数
        │             │
        │             ├─ 当前：空函数体，或只读取 pArgInf 局部变量
        │             └─ 当前未连接 SQLite C API / 未写 pRetData
        │
        └─ 系统通知 NL_SYS_NOTIFY_FUNCTION
                      ▼
        sqlite3_ProcessNotifyLib_sqlite3()
                      ▼
        elib/fnshare.cpp::ProcessNotifyLib()
                      ├─ 记录 PFN_NOTIFY_SYS
                      ├─ 查询 NRS_GET_PRG_TYPE 更新调试版本值
                      └─ 可选转发用户回调

（设计意图但当前缺失的运行时路径）
Sqlite数据库.Open
    ▼ sqlite3_open / sqlite3_close 句柄生命周期
执行SQL语句 / 事务 / 建表 / 表读写 / 记录集
    ▼ prepare/bind/step/column/finalize 等 SQLite C API
    ▼ 数据类型转换、游标状态、错误码和 pRetData 返回
```

上述下半段是根据命令元数据和 `LIB_INFO` 说明推导的设计意图，不是当前实现证据。

## 3. 目录与文件地图

当前 Git 树共 23 个版本控制文件；无 README、测试目录、构建脚本、SQLite 源码或第三方二进制依赖。

```text
sqlite3/
├── sqlite3.sln                         Visual Studio 解决方案；DLL + 静态库
├── sqlite3.vcxproj                     动态库工程（Win32/x64，目标扩展主要为 .fne）
├── sqlite3.vcxproj.filters             动态库工程文件筛选器
├── sqlite3.vcxproj.user                空用户工程配置
├── sqlite3_static/
│   ├── sqlite3_static.vcxproj         静态库工程，复用上级源码
│   ├── sqlite3_static.vcxproj.filters 静态库工程文件筛选器
│   └── sqlite3_static.vcxproj.user    空用户工程配置
├── sqlite3_cmdDef.cpp                 230 个命令函数的导出/桩函数
├── sqlite3_cmdInfo.cpp                参数表、命令信息表及计数
├── sqlite3_cmd_typedef.h              命令宏表、索引、英文名和元数据声明
├── sqlite3_dtType.cpp                 自定义数据类型及对象方法索引
├── sqlite3_dllMain.cpp                DLL 入口、LIB_INFO、命令函数表、通知入口
├── sqlite3_const.cpp                  常量表（当前数量为 0）
├── include_sqlite3_header.h            项目聚合头文件、extern 声明和函数声明宏
├── Source_sqlite3.def                 DLL 导出定义，仅导出 GetNewInf
└── elib/
    ├── lib2.h                         易语言支持库 ABI、数据结构、通知编号和宏
    ├── fnshare.h / fnshare.cpp        通知、易语言内存、调试值和用户回调辅助层
    ├── krnllib.h                      系统核心支持库常量/版本等兼容定义
    ├── lang.h                         GBK/English 语言版本宏
    ├── mtypes.h                       Windows 风格基础类型别名
    ├── untshare.h                     非 MFC 单元共享辅助头
    └── PublicIDEFunctions.h           IDE 辅助功能接口定义（当前未接入业务流程）
```

工程纳入关系由 `sqlite3.vcxproj:21-42`、`sqlite3_static/sqlite3_static.vcxproj:21-39` 和两个 `.filters` 文件确认。静态工程通过 `..\` 复用同一套源码，并不包含另一份 SQLite 实现。

## 4. 构建与运行时分层

### 4.1 支持库 ABI 层（已实现骨架）

- `elib/lib2.h` 提供 `EXTERN_C`、`DEF_EXECUTE_CMD`、`CMD_INFO`、`ARG_INFO`、`LIB_INFO`、`MDATA_INF`、`PFN_NOTIFY_LIB`、`PFN_NOTIFY_SYS`、通知编号和返回码等 ABI 定义。
- `include_sqlite3_header.h:3-20` 聚合 `elib/lib2.h`、`lang.h`、`krnllib.h`、命令类型表，并声明动态库模式下的元数据数组。
- `sqlite3_cmd_typedef.h:3-12` 通过 `SQLITE3_NAME`、`SQLITE3_NAME_STR` 和 `SQLITE3_DEF(_MAKE)` 统一生成命令实现声明、命令信息表、函数指针表和静态库名称表。

### 4.2 命令入口层（函数外壳已存在，业务实现缺失）

- `sqlite3_cmdDef.cpp` 为每个命令生成 `extern "C"` 函数，签名统一为 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`。
- 函数体目前只出现空体或参数局部变量读取。源码中没有 SQLite C API 调用、句柄字段、对象私有数据结构、SQL 字符串构造/执行、结果写回或错误处理。
- `pArgInf` 的下标遵循生成代码原样（例如 `打开`读取 `pArgInf[1]`、`pArgInf[2]`），但是否与易语言实际参数布局一致没有运行时验证。

### 4.3 元数据注册层（已实现）

- `sqlite3_cmdInfo.cpp:5-142` 定义参数描述数组；`149-159` 用 `SQLITE3_DEF` 生成 `CMD_INFO` 和命令总数。
- `sqlite3_dtType.cpp:5-41` 将命令索引连续映射到三个对象：数据库 20–99、表 100–179、记录集 180–229。
- `sqlite3_dtType.cpp:104-181` 定义 `SqliteDB`、`SqliteTable`、`SqliteDataset` 和 `SqliteFieldInfo` 等自定义数据类型元数据；其中前 3 个对象绑定方法索引，字段信息类型提供 `名称/Name`、`类型/Datatype`、`最大文本长度/MaxTextLength` 三个成员。
- `sqlite3_cmdInfo.cpp` 以 `#if !defined(__E_STATIC_LIB)` 包住动态库元数据；静态库依靠命令名称数组和 `__E_STATIC_LIB` 宏模式，具体静态编译链路未验证。

### 4.4 库生命周期与通知层（框架已实现）

- `sqlite3_dllMain.cpp:7-24` 提供空操作的 `DllMain`。
- `sqlite3_dllMain.cpp:31-87` 构造 `LIB_INFO`，设置格式号、GUID、版本、系统要求、作者信息、数据类型、命令表、通知回调和常量表。
- `sqlite3_dllMain.cpp:89-92` 的 `GetNewInf()` 返回 `LIB_INFO` 地址；`Source_sqlite3.def:1-4` 仅导出此入口。
- `sqlite3_dllMain.cpp:101-178` 实现 `sqlite3_ProcessNotifyLib_sqlite3`：动态库模式处理函数名数组、通知函数名和依赖库查询；收到 `NL_SYS_NOTIFY_FUNCTION` 时转发到 `ProcessNotifyLib`；释放、卸载、IDE 就绪等分支为空操作。
- `elib/fnshare.cpp:11-70` 保存系统通知回调，使用 `NotifySys` 调用易语言系统分配器/释放器和调试查询，并将通知交给可选用户回调。

## 5. 模块职责表

| 模块 | 主要职责 | 当前状态 | 证据 |
|---|---|---|---|
| `sqlite3_cmd_typedef.h` | 命令索引 0–229、中文名、英文名、返回类型、可见性、参数数量、对象方法范围 | 已实现元数据声明 | `sqlite3_cmd_typedef.h:3-243` |
| `sqlite3_cmdDef.cpp` | 导出各命令函数入口 | 仅有桩函数；无 SQLite 执行 | `sqlite3_cmdDef.cpp:1-1878`；230 函数统计见本文“验证记录” |
| `sqlite3_cmdInfo.cpp` | 参数 ABI 描述、默认值、引用/数组标志、命令信息表 | 已实现描述表 | `sqlite3_cmdInfo.cpp:5-159` |
| `sqlite3_dtType.cpp` | 自定义对象类型、成员和对象方法索引 | 已实现元数据 | `sqlite3_dtType.cpp:5-181` |
| `sqlite3_dllMain.cpp` | DLL 入口、库信息、函数指针表、系统通知 | ABI 骨架已实现 | `sqlite3_dllMain.cpp:7-178` |
| `sqlite3_const.cpp` | 预定义常量注册 | 空表，当前无常量 | `sqlite3_const.cpp:14-18` |
| `include_sqlite3_header.h` | 统一头文件和导出声明宏 | 已实现 | `include_sqlite3_header.h:1-26` |
| `elib/lib2.h` | 易语言支持库接口协议和数据结构 | 外部兼容底座 | `elib/lib2.h:1-43`、`297-364`、`822-824`、`1152-1260` |
| `elib/fnshare.*` | 系统通知、内存和用户通知回调 | 辅助框架已实现 | `elib/fnshare.cpp:1-70`、`elib/fnshare.h:20-55` |
| `sqlite3.vcxproj` | 编译动态库 `.fne` | 工程声明；未在本环境编译 | `sqlite3.vcxproj:21-199` |
| `sqlite3_static.vcxproj` | 编译静态库 | 工程声明；未在本环境编译 | `sqlite3_static/sqlite3_static.vcxproj:21-166` |

## 6. 核心数据模型与状态

### 6.1 支持库注册模型

`LIB_INFO` 是宿主发现本库的顶层注册对象，实际字段由 `elib/lib2.h` 定义，实例在 `sqlite3_dllMain.cpp:31-87`：

- `m_dwLibFormatVer = LIB_FORMAT_VER`；
- GUID `{E5D631FE-E3C9-4eb3-A687-C89598FE6691}`；
- 版本 `2.1.0`；
- 要求易语言系统 `3.7`、系统核心支持库 `3.7`；
- 库名 `Sqlite3数据库支持库`，语言 `__GBK_LANG_VER`；
- 自定义类型数组 `g_DataType_sqlite3_global_var`；
- 命令表 `g_cmdInfo_sqlite3_global_var` 和函数指针表 `g_cmdInfo_sqlite3_global_var_fun`；
- 常量表数量为 0；
- 依赖文件列表为 `NULL`；
- 通知函数为 `sqlite3_ProcessNotifyLib_sqlite3`。

### 6.2 用户可见对象模型（仅元数据已实现）

| 易语言类型 | 英文名 | 设计用途 | 方法索引 | 当前持久化/运行状态 |
|---|---|---|---:|---|
| `Sqlite数据库` | `SqliteDB` | 打开/关闭数据库、执行 SQL、事务、表级操作 | 20–99 | 未发现数据库句柄字段或对象实例状态 |
| `Sqlite表` | `SqliteTable` | 打开表、游标移动、编辑/插入/删除、字段读写 | 100–179 | 未发现表名、游标、缓存记录或所属数据库状态 |
| `Sqlite记录集` | `SqliteDataset` | SQL 查询/非查询、参数绑定、结果集游标 | 180–229 | 未发现 prepared statement、绑定值或结果集状态 |
| `Sqlite字段信息` | `SqliteFieldInfo` | 创建表时描述字段 | 无对象方法 | 仅有 `Name`、`Datatype`、`MaxTextLength` 元数据成员 |

### 6.3 数据库与持久化边界

设计说明将 SQLite 描述为文件数据库，但仓库中没有数据库文件、连接句柄、表结构缓存、事务状态、记录集对象、字段值缓存或持久化适配层。没有迁移、schema、数据模型实现；真正的 SQLite 文件读写需由后续实现补齐。

### 6.4 命令覆盖概览

- 命令索引总量：230（0–229）。
- 元数据中公开命令：82；隐藏命令：148。
- `Sqlite数据库` 区间 20–99：80 个槽位，公开 21 个。
- `Sqlite表` 区间 100–179：80 个槽位，公开 36 个。
- `Sqlite记录集` 区间 180–229：50 个槽位，公开 25 个。
- 0–19 是全局/保留槽位，当前均隐藏；大量 `无法识别的名字_N` 是为历史命令索引保留的隐藏占位。

公开 API 按能力分组如下（这是元数据契约，不代表实现已完成）：

- 数据库：`是否已打开`、`打开`、`关闭`、`执行SQL语句`、`取记录集`、`置最大等待时间`、错误码/错误文本、最新插入 ID、事务开始/提交/回滚、表存在性、取表列表/内容/定义、读取字段、创建/删除/清空表、收缩数据库。
- 表：打开/关闭、首尾/前后/跳过/跳到游标、BOF/EOF、编辑/插入/删除/提交/取消/刷新/查找、通用字段读写、文本/整数/浮点/双精度/字节集/逻辑/日期时间/长整数/短整数/字节读取、表名/记录号/记录数/所有记录/字段数/字段名。
- 记录集：设置 SQL、参数计数/参数名/绑定参数、打开/关闭、字段读取、下一记录、BOF/EOF、记录数/所有记录/字段数/字段名及多种类型读取。

## 7. 接口与调用契约

### 7.1 DLL 对外入口

| 接口 | 位置 | 作用 | 状态 |
|---|---|---|---|
| `GetNewInf()` | `sqlite3_dllMain.cpp:89-92` | 返回 `PLIB_INFO`，供宿主加载支持库 | 已实现 |
| `sqlite3_ProcessNotifyLib_sqlite3(INT,DWORD,DWORD)` | `sqlite3_dllMain.cpp:101-178` | 处理宿主通知、返回命令函数名/通知函数名/依赖列表 | 框架已实现 |
| `Source_sqlite3.def` 导出 | `Source_sqlite3.def:1-4` | DLL 只显式导出 `GetNewInf` | 已声明 |

### 7.2 命令函数 ABI

所有命令函数原型由 `include_sqlite3_header.h:22-24` 的 `SQLITE3_DEF_CMD` 生成，形式为：

```cpp
extern "C" void sqlite3_<英文名>_<索引>_sqlite3(
    PMDATA_INF pRetData,
    INT nArgCount,
    PMDATA_INF pArgInf
);
```

函数名拼接规则由 `sqlite3_cmd_typedef.h:3-9` 和 `elib/lib2.h:28-35` 控制，目的是在支持库名称、命令英文名、命令索引和后缀之间形成稳定符号，兼顾动态库和静态库。

### 7.3 参数/返回值契约

参数类型、默认值和引用标志由 `g_argumentInfo_sqlite3_global_var` 描述，包括 `SDT_TEXT`、`SDT_BOOL`、`SDT_INT`、`SDT_INT64`、`_SDT_ALL`、数组类型 `MAKELONG(0x0A, 0)`、对象类型 `MAKELONG(0x01, 0)`/`MAKELONG(0x03, 0)` 及 `AS_RECEIVE_VAR`、`AS_RECEIVE_ALL_TYPE_DATA` 等标志（`sqlite3_cmdInfo.cpp:5-142`）。

当前实现没有将结果写入 `pRetData`，也没有把引用参数写回；因此“返回真/假”“写入字段值”“返回数组”等契约目前只是命令描述层声明。

### 7.4 通知协议

`sqlite3_ProcessNotifyLib_sqlite3` 已处理或预留：

- `NL_GET_CMD_FUNC_NAMES`：动态库模式返回命令实现函数名数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `sqlite3_ProcessNotifyLib_sqlite3`；
- `NL_GET_DEPENDENT_LIBS`：返回空依赖列表 `"\0\0"`；
- `NL_SYS_NOTIFY_FUNCTION`：将系统通知函数指针转交 `elib/fnshare.cpp`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY` 等：当前为空操作。

## 8. 依赖与编译配置

### 8.1 代码依赖

- C++/Visual C++ 项目系统：`sqlite3.sln` 声明 Visual Studio 17 格式（`sqlite3.sln:1-8`）。
- Windows/Visual C++ 支持库 ABI：`elib/*.h`。
- 易语言系统核心支持库协议：`elib/krnllib.h` 的核心库版本常量，`LIB_INFO` 要求系统和核心库版本 3.7。
- C 运行时/Windows 类型兼容定义：`elib/mtypes.h`。
- **SQLite 引擎依赖：未发现。** 工程的 `<AdditionalDependencies>`、SQLite 源文件和 SQLite 头文件均未出现；动态库 `m_szzDependFiles = NULL`，通知返回的静态库依赖列表为空。

### 8.2 动态库工程

`sqlite3.vcxproj`：

- 配置：`Debug/Release|Win32`、`Debug/Release|x64`；
- 类型：`DynamicLibrary`；
- 工具集：`v141`；
- Windows SDK：`10.0.15063.0`；
- 字符集：Unicode；
- Win32 定义含 `__E_FNENAME=sqlite3`、`SQLITE3_EXPORTS`；
- Win32 链接使用 `Source_sqlite3.def`；
- Win32 设置 `<TargetExt>.fne</TargetExt>`；x64 未设置同一目标扩展；
- 未发现 SQLite 或其它第三方库的显式链接项。

### 8.3 静态库工程

`sqlite3_static/sqlite3_static.vcxproj`：

- 配置同为 `Debug/Release|Win32/x64`；
- 类型：`StaticLibrary`；
- 工具集：`v141`；
- Win32 定义含 `__E_STATIC_LIB;__E_FNENAME=sqlite3`；
- Win32 启用多处理器编译；
- x64 配置使用预编译头 `pch.h`，但仓库文件清单中没有 `pch.h`；
- 工程未声明 SQLite 静态库或其它第三方依赖。

## 9. 关键调用链（当前实现与预期分开）

### 9.1 已实现：宿主加载 DLL

```text
宿主 LoadLibrary(sqlite3.fne/等实际文件名)
  → GetNewInf() [Source_sqlite3.def]
  → g_LibInfo_sqlite3_global_var
  → 读取命令信息/参数信息/数据类型/函数指针
  → 根据 g_cmdInfo_sqlite3_global_var_fun 调用 sqlite3_<命令>_<索引>_sqlite3
```

DLL 文件扩展、实际产物命名和宿主加载成功未验证。

### 9.2 已实现：系统通知转发

```text
宿主 → sqlite3_ProcessNotifyLib_sqlite3(NL_SYS_NOTIFY_FUNCTION, pfn, ...)
     → ProcessNotifyLib()
     → s_pfnNotifySys = pfn
     → NotifySys(NRS_GET_PRG_TYPE, 0, 0)
     → s_isDebug 更新
     → 可选 s_pfnuserNotifySys 回调
```

证据：`sqlite3_dllMain.cpp:125-132`、`elib/fnshare.cpp:24-70`。

### 9.3 仅声明：数据库操作链

```text
易语言调用 Sqlite数据库.打开(数据库文件, 是否允许创建)
  → sqlite3_Open_30_sqlite3()
  → [缺失：sqlite3_open / 句柄保存 / pRetData 写回 / 错误处理]

易语言调用 Sqlite数据库.执行SQL语句(SQL)
  → sqlite3_ExecuteSQL_32_sqlite3()
  → [缺失：SQL 执行、事务边界、错误码和成功值]

易语言调用 Sqlite记录集.置SQL语句(SQL, Sqlite数据库)
  → sqlite3_SetSQL_184_sqlite3()
  → [缺失：prepare、参数元数据、statement 保存]

易语言调用 Sqlite记录集.绑定参数(名称或索引, 值)
  → sqlite3_BindParameter_187_sqlite3()
  → [缺失：类型映射、bind、生命周期]

易语言调用 Sqlite记录集.打开()/到下一记录()/读字段值()
  → 对应命令桩
  → [缺失：step、column、游标状态、finalize、返回数据转换]
```

## 10. 测试与验证现状

### 10.1 仓库内测试

未发现测试目录、测试源码、测试工程、CI 配置或测试数据。当前不能宣称任何功能测试通过。

### 10.2 本轮静态验证

已人工读取并交叉核对：

- Git 工作树、分支、提交、远程地址和提交历史；
- 解决方案、动态库工程、静态库工程及筛选器；
- `sqlite3_cmdDef.cpp`、`sqlite3_cmdInfo.cpp`、`sqlite3_cmd_typedef.h`、`sqlite3_dtType.cpp`、`sqlite3_dllMain.cpp`、`sqlite3_const.cpp`；
- `include_sqlite3_header.h`；
- `elib/lib2.h`、`fnshare.cpp/.h`、`krnllib.h`、`lang.h`、`mtypes.h`、`untshare.h`、`PublicIDEFunctions.h`；
- `Source_sqlite3.def` 和完整 Git 文件清单。

脚本统计（仅读取源码，不修改仓库）：

- `sqlite3_cmd_typedef.h` 中命令宏条目 230 个，索引范围 0–229；
- `sqlite3_cmdDef.cpp` 中 `SQLITE3_EXTERN_C void` 函数 230 个；
- 命令函数体：180 个无有效语句，50 个仅局部读取参数，0 个包含业务逻辑；
- 230 个命令函数中没有调用 SQLite C API 的函数；没有函数使用 `pRetData` 写回结果；
- `g_ConstInfo_sqlite3_global_var_count = 0`；
- 工程文件声明的源文件与 Git 文件清单已对照，未发现 SQLite 第三方源码/头文件/库。

### 10.3 未执行验证

以下项目在当前 macOS 环境、且本轮仅做架构建档的范围内没有执行：

- Visual Studio/MSBuild 编译；
- Windows DLL/静态库链接；
- 易语言 IDE 加载支持库；
- SQLite 文件创建、SQL、事务、游标、绑定参数和字段类型转换；
- ABI 运行时回调和内存释放；
- x64 静态工程预编译头配置的可用性。

## 11. 风险、缺口与后续复核点

1. **核心阻断：SQLite 引擎未接入。** 设计说明宣称的数据库能力在当前源代码没有任何对应 C API、第三方源码或库依赖证据。
2. **核心阻断：命令函数没有返回结果。** `pRetData` 未使用，成功/失败、对象返回值、数组返回值和引用参数均不能由当前实现产生。
3. **对象生命周期未建模。** `SqliteDB`、`SqliteTable`、`SqliteDataset` 没有可见句柄、statement、游标、所属关系或析构清理实现；构造/复制/析构命令也只是隐藏桩。
4. **命令元数据与实现脱节。** 元数据描述 82 个公开命令，但公开命令并不等于可用实现；后续必须逐命令建立“参数→SQLite 调用→错误→返回值”证据。
5. **参数索引需运行时验证。** 生成函数从 `pArgInf[1]` 开始读取，但函数 ABI 是否包含 0 号保留项未在仓库测试中验证。
6. **静态库配置存在疑点。** x64 静态工程启用 `pch.h`，仓库无该文件；动态库和静态库的部分预处理定义也不完全一致，需在 Windows 工具链实编。
7. **构建产物扩展不一致。** 动态库 Win32 配置设置 `.fne`，x64 配置未设置目标扩展；宿主实际加载名称未被工程或测试确认。
8. **编码和工具链风险。** 源码为 CRLF，中文源码主要按 GB18030/本地扩展编码读取，`include_sqlite3_header.h` 中存在乱码注释迹象；需确认 Visual C++ 源码编码和易语言元数据展示。
9. **错误/资源策略未实现。** 设计上有错误码、错误文本、busy timeout、事务和自动关闭说明，但没有可追踪的数据库错误状态、锁等待策略、statement finalize 或句柄释放。
10. **安全边界未定义。** `执行SQL语句` 和 `查找` 说明允许直接传 SQL/where 文本；当前没有参数化约束、标识符转义、线程模型或并发说明。
11. **依赖声明可能失真。** `m_szzDependFiles` 和 `NL_GET_DEPENDENT_LIBS` 都报告无依赖，但若未来接入 SQLite 外部库，必须同步工程链接项、部署文件和支持库依赖协议。
12. **版本信息需复核。** `LIB_INFO` 说明写 SQLite 3.7.11，但仓库没有 SQLite 版本源码或二进制可供核验，不能把它作为实际引擎版本。

## 12. Git 基线与证据边界

- 仓库路径：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/sqlite3`
- 当前分支：`master`
- 当前提交：`e5faa507de7e60fe9ed72f92963ff23e3dd28972`
- 提交主题：`初始化仓库`
- 提交时间：`2022-12-19T16:57:34+08:00`
- 远程：`https://gitee.com/JYtechnology/sqlite3.git`
- `master` 与 `origin/master` 在本地基线均指向上述提交；本轮未 fetch、pull、切换分支或提交 Git。
- 建档前工作树无修改；本轮按任务约束只允许新增/更新根目录 `ARCHITECTURE.md`，未修改源码、工程、依赖、测试、配置或 Git 元数据。

本文件中的路径和行号均指向上述提交工作树中的真实文件；若后续提交改变文件行号，应在同一文件内更新证据定位。
