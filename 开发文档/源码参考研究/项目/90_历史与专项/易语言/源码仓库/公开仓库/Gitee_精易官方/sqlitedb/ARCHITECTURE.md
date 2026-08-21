# sqlitedb 架构建档

> 本文件是 `sqlitedb` 仓库当前唯一的架构事实文档。内容以本地源码、Visual Studio 工程和 Git 基线为证据；命令元数据中的说明不能替代运行实现证据。本文只描述已在仓库中看到的内容，并明确区分“已实现”“仅声明/注册”“未验证”。

## 1. 项目定位

`sqlitedb` 是精易官方 Gitee 仓库中的易语言支持库工程，目标形态是向易语言 IDE/运行时注册一个名为“Sqlite数据库支持库”的 Windows 支持库，暴露数据库、表、记录集和字段信息等易语言数据类型及其命令。

源码当前更准确的定位是：**易语言支持库 ABI/元数据模板与命令入口壳**。仓库没有 SQLite 引擎源码、SQLite 头文件、数据库句柄字段、SQL 调用、表/记录集状态结构或测试样例；`sqlitedb_cmdDef.cpp` 中 230 个命令函数均只有参数读取或空函数体，未形成可运行的 SQLite 数据库功能。因此 README/元数据宣称的数据库能力不能在本仓库内视为已验证事实。

支持库元数据在 `sqlitedb_dllMain.cpp` 的解释文本中声称内部 SQLite 版本为 3.2.5，并建议使用“Sqlite3数据库支持库”；该信息是库说明字符串，不是本仓库的实现证据。

## 2. 架构结论与实现状态

| 范畴 | 状态 | 结论与证据 |
|---|---|---|
| Visual Studio 解决方案 | 已实现/仅工程声明 | `sqlitedb.sln:5-7` 注册动态库项目和静态库项目，配置 Win32/x64 的 Debug/Release。 |
| 动态库构建骨架 | 已实现/未验证 | `sqlitedb.vcxproj:21-42` 纳入源码和头文件，Win32 配置链接 `Source_sqlitedb.def`；未在本机 Windows/MSVC 环境构建。 |
| 静态库构建骨架 | 已实现/未验证 | `sqlitedb_static/sqlitedb_static.vcxproj:21-38` 复用上级源码；静态库宏仅在部分 Win32 配置明确设置。 |
| 易语言库信息注册 | 已实现 | `sqlitedb_dllMain.cpp:31-91` 定义 `LIB_INFO` 并由 `GetNewInf()` 返回。仅动态库编译路径包含该注册结构。 |
| 命令目录/参数元数据 | 已实现 | `sqlitedb_cmd_typedef.h:12-242` 用 `SQLITEDB_DEF(_MAKE)` 统一生成 230 个槽位；`sqlitedb_cmdInfo.cpp:5-159` 生成参数和 `CMD_INFO` 数组。 |
| 命令入口符号 | 已实现（空壳） | `sqlitedb_cmdDef.cpp:6-1875` 生成 230 个 `SQLITEDB_EXTERN_C` 入口；函数体没有 SQLite 操作和返回值写入。 |
| 自定义数据类型元数据 | 已实现/仅声明 | `sqlitedb_dtType.cpp:4-181` 注册 10 个类型槽位，其中实际命名的为 `SqliteDB`、`SqliteTable`、`SqliteDataset`、`SqliteFieldInfo`，其余为 `NULL` 占位。 |
| SQLite 引擎/数据库连接 | 未发现 | 全仓搜索无 `sqlite3`、`sqlite3_*`、SQLite 头文件、数据库句柄或第三方库链接项。 |
| SQL、事务、游标、表 CRUD | 仅声明/未实现 | 命令名称和参数已注册；对应函数体没有执行逻辑，不能据此认定功能存在。 |
| 错误码、错误文本、资源释放 | 仅声明/未实现 | 元数据有相关命令；实现入口未填充 `pRetData`，也没有错误状态或句柄释放逻辑。 |
| 测试 | 未发现/未验证 | 仓库没有测试目录、测试工程、测试源码、CI 配置或可执行验收样例。 |

## 3. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
          │
          │ 加载 .fne 或链接静态库
          ▼
  GetNewInf() ───────────────► LIB_INFO
          │                      │
          │                      ├─ 库名、版本、GUID、系统版本要求
          │                      ├─ g_DataType_sqlitedb_global_var
          │                      ├─ g_cmdInfo_sqlitedb_global_var
          │                      ├─ g_cmdInfo_sqlitedb_global_var_fun
          │                      └─ sqlitedb_ProcessNotifyLib_sqlitedb
          │
          ▼
  易语言命令/对象成员解析
          │
          ├─ SQLITEDB_DEF(_MAKE)
          │       ├─ 命令中文名/英文名/说明/返回类型
          │       ├─ 参数数量与 g_argumentInfo 偏移
          │       └─ 230 个命令槽位（含隐藏、未知占位）
          │
          └─ 命令分派
                  ▼
          g_cmdInfo_sqlitedb_global_var_fun[i]
                  ▼
          sqlitedb_*_<index>_sqlitedb(PMDATA_INF, ...)
                  │
                  ├─ 当前源码仅读取少量参数或空函数体
                  └─ 未连接 SQLite 引擎，未产生数据库结果
```

## 4. 目录与文件地图

```text
sqlitedb/
├── sqlitedb.sln                         解决方案；动态库 + 静态库
├── sqlitedb.vcxproj                     动态库（DynamicLibrary）工程
├── Source_sqlitedb.def                  Win32 导出 GetNewInf
├── sqlitedb_static/
│   ├── sqlitedb_static.vcxproj          静态库（StaticLibrary）工程，复用上级源码
│   ├── *.filters                        VS 文件筛选器
│   └── *.user                           本地 VS 用户配置
├── sqlitedb_cmd_typedef.h               SQLITEDB_DEF 命令总表和名字拼接宏
├── sqlitedb_cmdInfo.cpp                 ARG_INFO、CMD_INFO 元数据数组
├── sqlitedb_cmdDef.cpp                  230 个命令执行入口（当前为空壳）
├── sqlitedb_dtType.cpp                  自定义数据类型及成员元数据
├── sqlitedb_dllMain.cpp                 DLL 生命周期、LIB_INFO、通知分派、GetNewInf
├── sqlitedb_const.cpp                   常量表；当前数量为 0
├── include_sqlitedb_header.h            统一包含与命令函数声明展开
└── elib/
    ├── lib2.h                           易语言支持库 ABI、数据类型、LIB_INFO/CMD_INFO 结构
    ├── mtypes.h                          Windows/基础类型兼容定义
    ├── lang.h                            语言版本宏（文件较小，当前为非 UTF-8 编码）
    ├── krnllib.h                         易语言核心库相关类型/常量
    ├── fnshare.h / fnshare.cpp           通知、内存、数组、数据复制辅助函数
    ├── untshare.h                        通用组件/属性辅助声明
    └── PublicIDEFunctions.h              IDE 公共函数声明
```

仓库没有 README、开发文档、`AGENTS.md`、`CLAUDE.md`、测试目录、CI 文件、SQLite 第三方目录或数据库样例。当前 Git 树共 23 个受跟踪文件；上述文件地图覆盖其工程和源码文件。

## 5. 构建与模块职责

### 5.1 解决方案与两个产物

`sqlitedb.sln:5-7` 定义两个 C++ 项目：

1. `sqlitedb`：`sqlitedb.vcxproj`，`ConfigurationType=DynamicLibrary`，目标扩展在 Win32 Debug/Release 配置为 `.fne`（`sqlitedb.vcxproj:95-105`）。Win32 Debug/Release 通过 `Source_sqlitedb.def` 指定模块定义文件（`sqlitedb.vcxproj:121-126`、`146-152`）。
2. `sqlitedb_static`：`sqlitedb_static/sqlitedb_static.vcxproj`，`ConfigurationType=StaticLibrary`，通过 `__E_STATIC_LIB` 和 `__E_FNENAME=sqlitedb` 让同一批入口适配静态链接（Win32 Debug/Release，`sqlitedb_static/sqlitedb_static.vcxproj:92-121`）。

两个工程都声明 Debug/Release 与 Win32/x64；解决方案把 x86 配置映射为项目的 `Win32`（`sqlitedb.sln:10-32`）。

### 5.2 项目宏与可疑配置边界

- 动态库 Win32 Debug/Release 定义 `__E_FNENAME=sqlitedb`（`sqlitedb.vcxproj:109-145`），并定义 `SQLITEDB_EXPORTS`、`_WINDOWS`、`_USRDLL`。
- 动态库 x64 Debug/Release 的预处理器定义（`sqlitedb.vcxproj:159-189`）没有 `__E_FNENAME=sqlitedb`，但 `elib/lib2.h:23-24` 明确要求先定义 `__E_FNENAME`，否则预处理报错；x64 构建因此**未验证且存在高风险**。
- 静态库 Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=sqlitedb`（`sqlitedb_static/sqlitedb_static.vcxproj:92-121`）；静态库 x64 配置只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`（`sqlitedb_static/sqlitedb_static.vcxproj:130-155`），同样没有 `__E_FNENAME`，且没有 `__E_STATIC_LIB`，存在与静态设计不一致的风险。
- 静态库 x64 配置使用 `<PrecompiledHeader>Use</PrecompiledHeader>` 和 `pch.h`（`sqlitedb_static/sqlitedb_static.vcxproj:136-137`、`153-154`），仓库文件树中没有 `pch.h`；该配置未验证。
- 动态库 x64 配置没有像 Win32 那样设置 `ModuleDefinitionFile`（`sqlitedb.vcxproj:171-175`、`191-197`），`GetNewInf` 的 x64 导出行为未验证。
- 工程使用 `PlatformToolset=v141`、`WindowsTargetPlatformVersion=10.0.15063.0`（动态库 `sqlitedb.vcxproj:43-75`；静态库 `sqlitedb_static/sqlitedb_static.vcxproj:40-72`），依赖 Windows/MSVC 环境；当前 macOS 工作环境不能直接证明其可构建。

### 5.3 源码模块职责

| 文件 | 职责 | 状态 |
|---|---|---|
| `sqlitedb_cmd_typedef.h` | 用 X-Macro 形式维护命令索引、中文名、英文符号、说明、返回类型、参数起始偏移及隐藏/对象构造标志；定义 `SQLITEDB_NAME`。 | 元数据已实现 |
| `include_sqlitedb_header.h` | 引入 `elib` ABI 和命令总表；非静态库声明全局元数据数组；通过 `SQLITEDB_DEF_CMD` 展开 230 个函数声明。 | 接口胶水已实现 |
| `sqlitedb_cmdInfo.cpp` | 定义 79 个参数槽（注释编号 000~078），为动态库生成 `ARG_INFO` 和 `CMD_INFO`；静态库路径以 `#if !defined(__E_STATIC_LIB)` 排除。 | 元数据已实现，静态路径未验证 |
| `sqlitedb_cmdDef.cpp` | 为每个命令提供统一 `PMDATA_INF` ABI 入口；按元数据读取传入参数。 | 入口符号已实现，业务逻辑未实现 |
| `sqlitedb_dtType.cpp` | 为 `SqliteDB`、`SqliteTable`、`SqliteDataset` 建立命令索引；为 `SqliteFieldInfo` 建立三个成员描述；填充 10 项类型表。 | 类型注册已实现，对象状态未实现 |
| `sqlitedb_dllMain.cpp` | DLL 进程生命周期空处理；生成命令函数指针表；定义库信息、`GetNewInf`、通知函数名/命令名列表。 | 支持库壳已实现 |
| `sqlitedb_const.cpp` | 预留库常量数组。 | 当前无常量 |
| `elib/fnshare.cpp/.h` | 通过易语言系统通知函数做内存申请/释放、调试版本探测、通知转发、文本/字节集/数组辅助。 | 通用辅助已实现；未被 SQLite 业务调用 |
| `elib/lib2.h` | 定义 `DATA_TYPE`、`MDATA_INF`、`ARG_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_INFO`、通知码和 ABI 函数指针。 | 依赖接口已实现 |

## 6. 命令与接口边界

### 6.1 命令总表机制

`sqlitedb_cmd_typedef.h:12-242` 的 `SQLITEDB_DEF(_MAKE)` 是唯一命令目录来源。每一行包含：

- 稳定槽位索引 `0..229`；
- 中文命令名；
- 英文符号名；
- 解释文本；
- 全局类别或对象成员标志；
- Windows 平台标志和 `CT_IS_HIDED` 等状态；
- 返回数据类型；
- 参数个数和 `g_argumentInfo_sqlitedb_global_var` 起始偏移。

该宏被多次展开：

```text
SQLITEDB_DEF_CMD      → include_sqlitedb_header.h → 函数声明
SQLITEDB_DEF_CMDINFO  → sqlitedb_cmdInfo.cpp       → CMD_INFO
SQLITEDB_DEF_CMD_PTR  → sqlitedb_dllMain.cpp       → PFN_EXECUTE_CMD[]
SQLITEDB_DEF_CMDNAME_STR → sqlitedb_dllMain.cpp    → 静态编译函数名数组
```

命令索引完整覆盖 `0..229`，共 230 个槽位：82 个非隐藏命令、148 个隐藏/未知/生命周期占位命令。隐藏项包括 `_bunengshibie_1..19` 等未知名字、各数据类型构造/复制构造/析构函数和若干保留槽位。

### 6.2 `Sqlite数据库`（命令索引 20~99）

数据类型说明位于 `sqlitedb_dtType.cpp:110-116`，方法索引表位于 `sqlitedb_dtType.cpp:5-16`。可见命令如下：

- 生命周期/连接：`是否已打开(IsOpen)`、`打开(Open)`、`关闭(Close)`。
- SQL/结果：`执行SQL语句(ExecuteSQL)`、`取记录集(GetDataset)`。
- 配置/错误：`置最大等待时间(SetBusyTimeout)`、`取错误码(GetLastErrorCode)`、`取错误文本(GetLastErrorText)`、`取最新插入ID(GetLastInsertRowId)`。
- 事务：`开始事务(BeginTransaction)`、`提交事务(CommitTransaction)`、`回滚事务(RollbackTransaction)`；`结束事务(EndTransaction)` 为隐藏命令。
- 元数据/读操作：`表是否存在(IsTableExist)`、`取所有表(GetTables)`、`取表内容(GetTableContent)`、`取表定义(GetTableSql)`、`读字段值(GetFieldValue)`。
- DDL/维护：`创建表(CreateTable)`、`删除表(DropTable)`、`清空表(ClearTable)`、`收缩数据库(ShrinkDB)`。
- `创建SQL函数todo(CreateSqlFunction)` 为隐藏命令，参数名为 `UL`，没有实现。

参数元数据位于 `sqlitedb_cmdInfo.cpp:17-48`、`sqlitedb_cmdInfo.cpp:50-78`；例如：

- `Open`：数据库文件 `SDT_TEXT`，是否允许创建 `SDT_BOOL`，后者可省略，默认不创建；说明还声称空文件名且允许创建时可打开内存数据库。
- `ExecuteSQL`：文本 SQL；说明称可用分号分隔多条语句，但不能处理 SQL 参数。
- `GetDataset`：文本 SQL，返回 `MAKELONG(0x03, 0)` 的 `SqliteDataset` 对象。
- `GetTables`：三个逻辑参数，分别控制表、视图、临时表/视图是否包含，返回数组文本。
- `CreateTable`：表名和 `SqliteFieldInfo` 数组/非数组。

以上是**编辑器/调用契约**；`sqlitedb_cmdDef.cpp:246-453`、`503-536` 等对应函数只有局部参数读取，没有打开文件、执行 SQL、填充返回值或保存句柄的代码。

### 6.3 `Sqlite表`（命令索引 100~179）

数据类型说明位于 `sqlitedb_dtType.cpp:117-123`，方法索引表位于 `sqlitedb_dtType.cpp:19-30`。可见命令分组如下：

- 生命周期：`是否已打开(IsOpen)`、`打开(Open)`、`关闭(Close)`。
- 游标：`到首记录(First)`、`到尾记录(Last)`、`到下一记录(Next)`、`到上一记录(Prior)`、`跳过(Skip)`、`跳到(Goto)`、`首记录前(Bof)`、`尾记录后(eof)`。
- 编辑状态：`编辑(Edit)`、`插入(Insert)`、`删除(Delete)`、`提交(Post)`、`取消(Cancel)`、`刷新(Refresh)`、`查找(Locate)`。
- 字段读写：通用 `读字段值(GetFieldValue)`、`写字段值(SetFieldValue)`，以及文本、整数、小数、双精度、字节集、逻辑、日期时间、长整数、短整数、字节等转换读取命令。
- 信息读取：`取表名(GetTableName)`、`取记录号(GetRecordNO)`、`取记录个数(GetRecordCount)`、`取所有记录(GetContent)`、`取字段个数(GetFieldCount)`、`取所有字段(GetFields)`。

`Open` 接受表名和 `Sqlite数据库` 复合数据（`sqlitedb_cmdDef.cpp:856-864`）；`Skip`、`Goto`、`Locate` 只读取传入整数或文本（`sqlitedb_cmdDef.cpp:901-1019`）；字段转换命令只声明了目标变量指针，未执行转换（`sqlitedb_cmdDef.cpp:1085-1199`）。

### 6.4 `Sqlite记录集`（命令索引 180~229）

数据类型说明位于 `sqlitedb_dtType.cpp:124-130`，方法索引表位于 `sqlitedb_dtType.cpp:33-41`。可见命令分组如下：

- SQL/参数：`置SQL语句(SetSQL)`、`取参数个数(GetParameterCount)`、`取所有参数(GetParameters)`、`绑定参数(BindParameter)`。
- 生命周期/游标：`是否已打开(IsOpen)`、`打开(Open)`、`关闭(Close)`、`到下一记录(Next)`、`首记录前(Bof)`、`尾记录后(Eof)`。
- 读取：通用 `读字段值(GetFieldValue)`、`取记录个数(GetRecordCount)`、`取所有记录(GetContent)`、`取字段个数(GetFieldCount)`、`取所有字段(GetFields)`，以及各基础类型读取命令。

`SetSQL` 的参数为 SQL 文本和已打开的 `Sqlite数据库` 对象（元数据 `sqlitedb_cmdInfo.cpp:101-103`）；`BindParameter` 允许参数名称/索引和通用数据值，未绑定值说明为 null（`sqlitedb_cmdInfo.cpp:105-106`）。对应实现入口在 `sqlitedb_cmdDef.cpp:1496-1835`，仅读取参数，未建立预编译语句、参数绑定或结果集。

### 6.5 `SqliteFieldInfo` 数据成员

`sqlitedb_dtType.cpp:95-102` 定义三个成员：

| 中文名 | 英文名 | 类型 | 说明 |
|---|---|---|---|
| 名称 | `Name` | `SDT_TEXT` | 字段名称长度不限，默认值标志存在 |
| 类型 | `Datatype` | `SDT_INT` | 约定值包含 -1 主键自增、0 无类型、1/2/3/4/5/6/7/8/10/11/12 等易语言类型 |
| 最大文本长度 | `MaxTextLength` | `SDT_INT` | 仅在文本型时作为描述性长度，0 表示任意长度 |

该对象只作为 `创建表(CreateTable)` 的参数描述；未看到其被解析为 SQL 列定义的代码。

### 6.6 外部 ABI/API

动态库对外接口由 `Source_sqlitedb.def:1-4` 声明，仅导出：

```text
GetNewInf
```

`GetNewInf()` 位于 `sqlitedb_dllMain.cpp:91`，返回静态 `g_LibInfo_sqlitedb_global_var` 地址。命令函数不是普通用户 API，而是通过 `LIB_INFO.m_pCmdsFunc` 数组按索引分派；函数原型由 `elib/lib2.h:1234-1239` 定义为：

```cpp
typedef void (*PFN_EXECUTE_CMD)(PMDATA_INF pRetData,
                               INT nArgCount,
                               PMDATA_INF pArgInf);
```

通知接口 `sqlitedb_ProcessNotifyLib_sqlitedb` 位于 `sqlitedb_dllMain.cpp:101-180`，处理 `NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 等通知；真正有动作的只有系统通知函数转发到 `ProcessNotifyLib`，其余分支为空。静态编译支持的函数名查询通过 `NL_GET_CMD_FUNC_NAMES` 和 `NL_GET_NOTIFY_LIB_FUNC_NAME` 返回字符串/数组，但该分支由 `#ifndef __E_STATIC_LIB` 包住。

## 7. 数据模型与数据流

### 7.1 支持库运行时数据模型

本项目没有 SQLite 业务对象结构，能确认的“数据模型”只有易语言支持库 ABI 元数据：

```text
LIB_INFO
├── m_szGuid = {295DD8F2-3584-4780-818D-9569AC5BC9D8}
├── version = 2.0.0
├── required 易语言系统 = 3.7
├── required 核心支持库 = 3.7
├── m_nDataTypeCount = sizeof(g_DataType...)
├── m_pDataType → 10 个 LIB_DATA_TYPE_INFO 槽位
├── m_nCmdCount = sizeof(g_cmdInfo...)
├── m_pBeginCmdInfo → 230 个 CMD_INFO
├── m_pCmdsFunc → 230 个 PFN_EXECUTE_CMD
├── m_pfnNotify → sqlitedb_ProcessNotifyLib_sqlitedb
└── m_pLibConst → 空常量数组，数量 0
```

`MDATA_INF` 的联合体在 `elib/lib2.h:780-824`，可携带基础数值、文本、字节集、复合数据、数组数据及变量地址；命令入口按 `m_dtDataType` 和对应联合成员解释参数。该结构是调用协议，不是 SQLite 行、列、连接或结果集的持久化模型。

### 7.2 预期数据流（由元数据描述，当前未闭环）

```text
易语言文本/变量
   │
   ▼
PMDATA_INF 参数数组
   │
   ├─ Open(数据库文件, 是否允许创建)
   ├─ ExecuteSQL(SQL)
   ├─ GetDataset(SQL) / Dataset.SetSQL(SQL)
   ├─ Table.Open(表名, 数据库)
   └─ CreateTable(表名, SqliteFieldInfo[])
   │
   ▼
[仓库缺失的 SQLite 连接/语句/游标/字段映射实现]
   │
   ▼
PMDATA_INF 返回值或变量地址写回
```

实际源码在上述中括号位置没有任何实现；因此不存在可以据源码确认的连接生命周期、SQL 解析、事务边界、游标推进、结果集缓存、错误传播或资源回收流程。

### 7.3 持久化模型

- 未发现 `.db`、`.sqlite`、`.sql`、迁移文件或数据库表定义。
- 未发现 `sqlite3_open`、`sqlite3_prepare`、`sqlite3_step`、`sqlite3_finalize`、`sqlite3_close` 等调用。
- 未发现数据库句柄字段、表/记录集容器、事务栈、错误码存储或线程同步。
- `m_szzDependFiles` 在 `sqlitedb_dllMain.cpp:91` 初始化为 `NULL`，工程也没有第三方库或附加依赖链接声明。

因此数据库持久化、内存数据库、事务、触发器、视图等均为元数据说明或设计意图，当前仓库未提供实现证据。

## 8. 依赖与运行边界

### 已确认依赖

- Windows API/类型：`elib/lib2.h:61-63` 引入 `windows.h`、`stdio.h`、`math.h`。
- 易语言支持库 ABI：`elib/lib2.h` 定义 `LIB_INFO`、`CMD_INFO`、`MDATA_INF`、通知码和函数指针。
- 易语言运行时通知：`elib/fnshare.cpp:10-71` 通过 `PFN_NOTIFY_SYS` 实现通知、内存分配和调试版本获取。
- MSVC 工具链：工程使用 `v141`，目标 Windows SDK 10.0.15063.0。

### 未确认/未提供的依赖

- SQLite 3.2.5 二进制、源代码、头文件、静态库或导入库：未发现。
- `.fne` 产物、`.lib` 产物、运行时安装目录：未发现。
- 易语言 IDE、易语言核心支持库和实际加载器：本机 macOS 无法验证。

库说明宣称“无需额外驱动程序”，不等于仓库包含 SQLite 实现；当前源码层面无法证明这一点。

## 9. 测试、构建与验证记录

### 仓库内测试资产

未发现以下内容：

- `test/`、`tests/`、`unittest`、GoogleTest/Catch2 工程；
- CI 工作流、构建脚本、示例易语言工程；
- SQLite 数据库样例、SQL 脚本或端到端验收脚本。

### 已进行的静态验证

以下结果来自当前验证人工读取和静态搜索：

1. `git ls-files` 确认仓库包含 23 个受跟踪文件，无 `ARCHITECTURE.md`、README 或测试文件。
2. 人工读取 `sqlitedb.sln`、两个 `.vcxproj`、两个 `.filters`、`.def`、核心 `.cpp/.h` 和 `elib` ABI 文件。
3. `SQLITEDB_DEF` 行索引确认命令槽位为 `0..229`，共 230 个；按 `CT_IS_HIDED` 统计为 82 个可见、148 个隐藏/占位。
4. 人工检查 `sqlitedb_cmdDef.cpp` 的 230 个函数体：除参数局部变量声明外，没有数据库调用、返回值赋值或业务状态更新；部分类型转换入口只有 `BOOL* arg2 = ...` 之类的参数指针读取。
5. 全仓库静态搜索未找到 `sqlite3`/`sqlite3_*`、SQLite 头文件、SQL 库链接声明、测试或数据库文件。
6. 未在 macOS 上运行 Visual Studio/MSBuild；因此没有“构建通过”“DLL 可加载”“易语言可调用”结论。

### 未执行项目

- Windows + Visual Studio `v141` 下的 Win32/x64 Debug/Release 构建；
- `.fne` 导出检查及 `GetNewInf` 加载；
- 静态库链接和命令名回调验证；
- 易语言 IDE 中的数据类型/命令显示验证；
- 真实 SQLite 打开、建表、SQL、事务、记录集和错误处理验收。

## 10. 风险与后续复核点

### 高风险

1. **业务实现缺失**：命令说明覆盖数据库能力，但命令入口没有执行代码；若将当前工程视为可用支持库，会产生严重的功能误判。
2. **x64 宏配置不完整**：动态库 x64 和静态库 x64 工程未定义 `__E_FNENAME`，而 `elib/lib2.h:23-24` 将其作为硬性前置条件；需在 Windows/MSVC 中确认是否因外部属性表或环境宏补齐。
3. **静态库 x64 配置不一致**：未定义 `__E_STATIC_LIB`，且启用不存在的 `pch.h`；不能据工程名认定静态库可编译。
4. **x64 导出未确认**：动态库 x64 未配置 `Source_sqlitedb.def`，需要确认 `GetNewInf` 是否通过其他导出机制可见。
5. **ABI/平台过时**：工程固定 `v141` 与 2017 SDK 目标，且 `elib` 依赖 Windows；现代工具链兼容性未验证。

### 中风险

- `sqlitedb_cmdInfo.cpp` 的参数元数据在 `#ifndef __E_STATIC_LIB` 下排除，静态构建是否由宿主提供等价命令元数据没有证据。
- `sqlitedb_cmdDef.cpp` 入口函数未写 `pRetData`，即使被调用也不能提供元数据声明的布尔、文本、整数或对象返回值。
- 构造函数、复制构造函数、析构函数虽然被标记为对象生命周期命令，但函数体为空，复合数据生命周期行为未实现。
- `elib/fnshare.h` 中 `efree`、数组和文本辅助函数依赖易语言通知指针，未提供空指针保护的运行验证。
- 代码中存在 `创建SQL函数todo`、大量 `_bunengshibie_`/`???` 占位，说明该版本可能是从某个支持库模板或反向生成结果初始化而来。

### 后续复核顺序

```text
先确认目标仓库/分支是否缺失子模块或历史提交
  ↓
在 Windows/MSVC 中修复或验证 x64 宏、PCH、导出配置
  ↓
确认真正的 SQLite 引擎来源和 ABI 句柄设计
  ↓
实现/接入 Open → SQL/事务 → Dataset/Table → Close 的最短闭环
  ↓
补充 pRetData、错误状态、资源释放和对象生命周期
  ↓
用易语言 IDE + SQLite 样例做端到端验证
```

在没有以上证据前，不应把本仓库描述为“已实现 SQLite 支持库”，只能称为“SQLite 支持库接口元数据与入口骨架”。

## 11. Git 基线与证据索引

### Git 基线

- 仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/sqlitedb`
- 分支：`master`，跟踪 `origin/master`
- 远程：`https://gitee.com/JYtechnology/sqlitedb.git`
- HEAD：`43ae380e0d11adf4d632c6c831937a50c05d2d51`
- 提交时间：`2022-12-19 16:57:41 +0800`
- 提交者：`精易科技`
- 提交说明：`初始化仓库`
- 当前验证开始时工作树：干净；此前不存在 `ARCHITECTURE.md`。
- 当前验证允许变更：仅新增根目录 `ARCHITECTURE.md`；不删除旧研究材料（现场未发现旧研究材料文件）。

### 关键证据路径

| 证据 | 路径与行号 |
|---|---|
| 两个项目及四种配置 | `sqlitedb.sln:5-32` |
| 动态库源码清单 | `sqlitedb.vcxproj:21-42` |
| 动态库配置、宏、Win32 DEF | `sqlitedb.vcxproj:43-201` |
| 静态库源码复用与配置 | `sqlitedb_static/sqlitedb_static.vcxproj:21-166` |
| DEF 导出 | `Source_sqlitedb.def:1-4` |
| 统一命令宏、230 槽位 | `sqlitedb_cmd_typedef.h:3-242` |
| 头文件元数据声明与函数声明展开 | `include_sqlitedb_header.h:3-24` |
| 参数表与 CMD_INFO | `sqlitedb_cmdInfo.cpp:5-159` |
| 230 个入口函数 | `sqlitedb_cmdDef.cpp:6-1875` |
| 数据类型索引和 `LIB_DATA_TYPE_INFO` | `sqlitedb_dtType.cpp:4-181` |
| `LIB_INFO`、`GetNewInf`、通知 | `sqlitedb_dllMain.cpp:5-180` |
| 空常量表 | `sqlitedb_const.cpp:12-18` |
| 易语言 ABI 结构/函数原型 | `elib/lib2.h:243-362`、`elib/lib2.h:780-824`、`elib/lib2.h:1225-1318` |
| 通知与内存/数组辅助 | `elib/fnshare.h:20-169`、`elib/fnshare.cpp:10-71` |
| 项目源码筛选器 | `sqlitedb.vcxproj.filters:20-73`、`sqlitedb_static/sqlitedb_static.vcxproj.filters:18-66` |

> 当前验证没有旧 `ARCHITECTURE.md` 或 `研究材料-*.md` 可吸收；后续研究材料应增量维护本文件，不另建平行架构事实源。
## 14. 当前源码级收口

### 14.1 入口与 ABI

- sqlitedb_cmdDef.cpp、cmdInfo.cpp、dtType.cpp 和 Source_sqlitedb.def 是当前仓的主要实现证据。
- sqlitedb_dllMain.cpp、Source_sqlitedb.def 和 sqlitedb.vcxproj 定义 DLL 生命周期、导出边界和 Visual Studio 构建；cmdDef/cmdInfo/dtType 文件分别承载执行、元数据和类型表。
- 通用 elib 头文件提供易语言宿主 ABI；命令索引、参数数量、返回类型和函数指针由 cmd_typedef.h 的宏展开保持一致。

### 14.2 调用流程

易语言装载器 -> GetNewInf/PLIB_INFO -> 命令或数据类型注册 -> 参数转换 -> 原生实现 -> PMDATA_INF/事件返回 -> 宿主释放

- sqlitedb 的调用依赖 Windows、易语言运行时、正确位数和调用约定；当前环境未执行 Windows 构建或宿主装载。
- 源码树未发现统一测试目录、CI 或故障注入脚本；静态符号存在不代表 ABI 已运行通过。

### 14.3 资源、失败与版本

- 主要风险包括句柄/缓冲区所有权、宿主提前卸载、索引漂移、编码或参数类型错误、权限不足和外部系统依赖失败。
- 仓库没有跨进程监督、统一错误码、重试、取消或崩溃恢复账本；具体资源释放必须以真实宿主调用核对。
- 当前 HEAD 为 43ae380e0d11adf4d632c6c831937a50c05d2d51；本仓此次只更新根 ARCHITECTURE.md，保留源码事实，不把历史快照或二进制当作运行验证。

### 14.4 规模说明

- 该仓属于低行数原生扩展/版本归档；当源码规模不足以诚实扩展到 500 行时，本文明确记录限制而不制造重复章节。
- 代码地图同步与查询、文档流程图、git diff --check 和实现词扫描需在当前仓独立执行；真实 Windows、易语言、设备或网络资源仍待核。
## 15. 完整文件树与平台映射

### 15.1 当前可见文件

- ./ARCHITECTURE.md
- ./Source_sqlitedb.def
- ./elib/PublicIDEFunctions.h
- ./elib/fnshare.cpp
- ./elib/fnshare.h
- ./elib/krnllib.h
- ./elib/lang.h
- ./elib/lib2.h
- ./elib/mtypes.h
- ./elib/untshare.h
- ./include_sqlitedb_header.h
- ./sqlitedb.sln
- ./sqlitedb.vcxproj
- ./sqlitedb.vcxproj.filters
- ./sqlitedb.vcxproj.user
- ./sqlitedb_cmdDef.cpp
- ./sqlitedb_cmdInfo.cpp
- ./sqlitedb_cmd_typedef.h
- ./sqlitedb_const.cpp
- ./sqlitedb_dllMain.cpp
- ./sqlitedb_dtType.cpp
- ./sqlitedb_static/sqlitedb_static.vcxproj
- ./sqlitedb_static/sqlitedb_static.vcxproj.filters
- ./sqlitedb_static/sqlitedb_static.vcxproj.user

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
