# mysql 支持库架构建档

> 首轮全量建档。本文是本仓库唯一架构事实文档；源码、工程文件和依赖均未修改。
> 结论严格区分：**已实现** = 当前源码中有可执行实现；**仅声明** = 元数据、函数壳或工程配置中声明了接口；**未验证** = 需要 Windows/Visual Studio/易语言宿主或真实 MySQL 环境，当前现场未能执行。

## 1. 项目定位

`mysql` 是一个面向易语言的 MySQL 数据库支持库工程，目标形态是 Windows 下的易语言动态支持库（`.fne`）和静态库（`.lib`）。它通过易语言支持库 ABI 暴露“连接、执行 SQL、记录集遍历、库表管理、用户权限、索引、事务、类型转换”等命令，并向易语言 IDE 提供命令说明、参数说明、常量和自定义数据类型元数据。

**当前源码状态的关键判断：**

- 支持库 ABI 外壳、版本信息、53 个命令的声明/元数据、57 个常量、2 个复合数据类型以及通知入口已经写入源码。
- `mysql_cmdDef.cpp` 中 53 个命令函数都只读取 `pArgInf` 参数，未调用 MySQL 客户端 API，未写入 `pRetData`，也没有连接/记录集/错误/事务等运行时状态。因此数据库功能在本版本中是**仅声明/脚手架状态**，不能据源码认定为可用 MySQL 客户端。
- 仓库没有 MySQL 客户端头文件、导入库、第三方依赖声明、测试工程、README 或 CI 配置；真实数据库链路未验证。

## 2. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
          |
          | 装载支持库：按固定入口查找 GetNewInf
          v
+------------------------------+
| mysql.dll / mysql.fne        |
| 或 mysql_static.lib          |
+------------------------------+
          |
          +--> GetNewInf()
          |      返回 LIB_INFO
          |      - GUID/版本/系统要求
          |      - 命令目录与命令函数表
          |      - 常量表与自定义数据类型表
          |
          +--> mysql_ProcessNotifyLib_mysql()
          |      接收易语言系统通知
          |      - NL_SYS_NOTIFY_FUNCTION -> ProcessNotifyLib
          |      - 其余已列举通知多为空处理
          |
          +--> g_cmdInfo_mysql_global_var_fun[0..52]
                 53 个命令函数
                 当前实现：读取 pArgInf -> 无数据库调用
                 -> 未写 pRetData -> 未形成真实结果

理论目标链路（当前未实现）
  连接MySql -> MySql句柄 -> 执行SQL -> 取记录集
       |                              |
       |                              +-> 记录集遍历/字段读取/字段类型
       +-> 库表/用户/索引/事务/错误/状态/影响行数
```

## 3. 版本与仓库基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/mysql` |
| Git 分支 | `master` |
| HEAD | `a5272d2678015e779a95ace589d44851752ca619` |
| HEAD 时间 | `2022-12-19 16:56:24 +08:00` |
| HEAD 提交说明 | `初始化仓库` |
| 远程 | `https://gitee.com/JYtechnology/mysql.git` |
| 本地与 `origin/master` | 现场读取时相同 |
| Git 提交数量 | 1；本地仓库为浅历史（需后续拉取历史时另行确认远程版本） |
| 原有架构文档 | 未发现；本文件为首轮新增 |
| 源码编码 | C/C++ 与头文件主体按 `GB18030` 解码可读，源码包含 Windows/易语言约定的 CRLF 文本；`elib/lang.h` 明确 `__GBK_LANG_VER = 1` |

## 4. 真实目录地图

现场仓库（排除 `.git`）共 22 个受版本控制的工程/源码文件，目录如下：

```text
mysql/
├── ARCHITECTURE.md                 # 本文，唯一架构事实文档（本轮新增）
├── mysql.sln                       # Visual Studio 解决方案，mysql + mysql_static
├── mysql.vcxproj                   # 动态库项目
├── mysql.vcxproj.filters           # 动态库 IDE 分组
├── mysql.vcxproj.user              # 用户级 VS 配置
├── mysql_static/
│   ├── mysql_static.vcxproj        # 静态库项目，复用上级源码
│   ├── mysql_static.vcxproj.filters
│   └── mysql_static.vcxproj.user
├── Source_mysql.def                # DLL 导出定义，仅导出 GetNewInf
├── include_mysql_header.h          # 聚合 SDK、命令声明与全局元数据声明
├── mysql_cmd_typedef.h             # 53 个命令的 X-macro 总表
├── mysql_cmdInfo.cpp               # 参数元数据、命令元数据数组
├── mysql_cmdDef.cpp                # 53 个命令函数壳
├── mysql_const.cpp                 # 常量元数据（57 项，动态库构建）
├── mysql_dtType.cpp                # 自定义复合数据类型元数据（2 项，动态库构建）
├── mysql_dllMain.cpp               # DLL 入口、LIB_INFO、命令指针表、通知入口
└── elib/                           # 随仓库携带的易语言支持库 ABI/SDK 头文件
    ├── lib2.h                      # 核心类型、命令/库信息结构、通知码、宏
    ├── fnshare.h / fnshare.cpp     # 通知、内存、数组、文本/字节集辅助封装
    ├── lang.h                      # GBK 语言版本声明
    ├── krnllib.h                   # 系统核心支持库常量与版本信息
    ├── mtypes.h                    # Windows 风格基础类型兼容定义
    ├── untshare.h                  # 窗口/组件辅助函数与占位宏
    └── PublicIDEFunctions.h        # IDE 扩展函数编号与数据结构声明
```

没有发现 `README*`、测试目录、测试源文件、CI 工作流、CMake/Makefile、MySQL 客户端源码或二进制库。

## 5. 分层与模块职责

### 5.1 易语言 ABI 适配层：`elib/`

**已实现（辅助/协议层）：**

- `elib/lib2.h` 定义支持库 ABI 的基本数据类型 `DATA_TYPE`、参数描述 `ARG_INFO`、命令描述 `CMD_INFO`、库自定义类型描述 `LIB_DATA_TYPE_INFO`、常量描述 `LIB_CONST_INFO`、运行时参数 `MDATA_INF`、库信息 `LIB_INFO`、命令函数指针 `PFN_EXECUTE_CMD` 和通知函数指针。
- `MDATA_INF` 通过 union 承载整数、长整数、日期、逻辑、文本、字节集、数组、复合数据和“变量地址”指针；命令实现统一签名为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。
- `elib/fnshare.cpp` 保存易语言系统通知指针和用户通知指针，转发 `NL_SYS_NOTIFY_FUNCTION`，并提供 `NotifySys`、`ProcessNotifyLib`、内存/文本/字节集/数组辅助函数。
- `elib/lang.h` 将本库语言版本固定为 GBK；`elib/mtypes.h` 提供 `INT`、`INT64`、`LPSTR`、`LPBYTE` 等类型。

**仅声明/未验证：**

- 这些文件是随仓库复制的易语言 SDK/运行时接口头文件，不等于本仓库已经实现或携带易语言运行时。
- `elib/untshare.h`、`elib/PublicIDEFunctions.h` 主要提供通用窗口/IDE 辅助声明，本 MySQL 命令实现没有使用其数据库能力（也没有发现数据库实现）。

### 5.2 命令目录与命令分发：`mysql_cmd_typedef.h`、`mysql_cmdInfo.cpp`

**已实现（元数据）：**

- `MYSQL_DEF(_MAKE)` 是唯一的 53 命令 X-macro 总表。它同时被用于生成命令声明、`CMD_INFO` 元数据和动态库命令函数指针表，减少命令编号与元数据错配。
- 每项包含命令编号、中文名、英文名、说明、类别、操作系统标志、返回类型、学习级别、参数数量和参数数组起始地址。
- `mysql_cmdInfo.cpp` 用 `g_argumentInfo_mysql_global_var` 定义参数说明，索引从 `000` 到 `103`，并生成 `g_cmdInfo_mysql_global_var` 与命令数量。

**关键约束：**

- 命令函数名通过 `MYSQL_NAME(_index, _szEgName)` 拼接为 `mysql_<英文名>_<编号>_mysql` 形态；第 52 项英文标识符实际为中文 `SQL语句序号`，形成 `mysql_SQL语句序号_52_mysql`，是否被目标编译器/链接器接受需在 Windows 工具链验证。
- 参数的输出变量依靠 `AS_RECEIVE_VAR` 和 `MDATA_INF` 中的 `m_ppText`、`m_pInt` 等指针字段传入；这是协议声明，不代表当前函数已经写出结果。

### 5.3 命令函数层：`mysql_cmdDef.cpp`

**仅声明/脚手架：**

- 文件中确实有 53 个 `MYSQL_EXTERN_C void` 函数，与命令编号 0–52 一一对应。
- 每个函数只将 `pArgInf[i]` 的内容读入局部变量，例如 `m_int`、`m_pText`、`m_pByte`、`m_pBin`、`m_pAryData`、`m_pCompoundData`、`m_ppText`。
- 全文件没有任何 `pRetData` 引用；没有 SQL 字符串拼接、连接对象、记录集对象、错误缓存、事务状态或资源释放代码。
- 未发现 `mysql.h`、`MYSQL*`、`mysql_real_connect`、`mysql_query` 等 MySQL C API 头文件/符号；`mysql_*` 主要是本库自己的命令函数名。

因此，命令说明中描述的真实行为（例如“返回 MySql 句柄”“执行 SQL”“取记录集”）属于**接口设计意图/仅声明**，不能当作当前版本已实现功能。

### 5.4 支持库装载与通知生命周期：`mysql_dllMain.cpp`

**已实现：**

- `DllMain` 存在，四类 DLL 生命周期通知均为空处理并返回 `TRUE`。
- `g_cmdInfo_mysql_global_var_fun` 由 X-macro 生成 53 个命令函数指针。
- `g_LibInfo_mysql_global_var` 返回固定支持库信息：`LIB_FORMAT_VER`、GUID、版本 `3.0.0`、易语言系统要求 `3.7`、系统核心支持库要求 `3.7`、名称 `MySQL支持库`、GBK 语言、`OS_ALL`。
- `GetNewInf()` 返回 `&g_LibInfo_mysql_global_var`，符合 `lib2.h` 规定的固定入口名称。
- `mysql_ProcessNotifyLib_mysql()` 处理 `NL_SYS_NOTIFY_FUNCTION`，把系统通知转发到 `ProcessNotifyLib`；释放、IDE 就绪、右键菜单、新成员等通知分支存在但为空处理；未知消息返回 `NR_ERR`。
- 动态库编译路径额外生成命令名数组，用于静态编译时取回命令名；`NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 在非静态构建分支中返回相应信息。

**工程边界：**

- `Source_mysql.def` 只声明导出 `GetNewInf`；`mysql_ProcessNotifyLib_mysql` 通过支持库信息结构提供给宿主，不在 `.def` 中直接导出。
- `mysql_dllMain.cpp` 以 `#ifndef __E_STATIC_LIB` 区分动态库与静态库元数据/入口逻辑。

## 6. 对外接口清单

### 6.1 固定 ABI 入口

| 入口 | 状态 | 作用 |
|---|---|---|
| `GetNewInf()` | 已实现 | 返回 `PLIB_INFO`，供易语言装载器读取库元数据、命令、常量和数据类型 |
| `mysql_ProcessNotifyLib_mysql(INT,DWORD,DWORD)` | 已实现骨架 | 接收易语言系统通知；系统通知函数转发到 `ProcessNotifyLib` |
| `DllMain(...)` | 已实现骨架 | Windows DLL 生命周期入口，当前各生命周期分支无资源处理 |

### 6.2 53 个易语言命令

以下名称、编号、参数/返回形状来自 `MYSQL_DEF`；**声明存在不代表运行实现存在**。

| 编号 | 中文命令 | 英文/内部名 | 返回类型 | 主要参数/资源 |
|---:|---|---|---|---|
| 0 | 设置MySql目录 | `path` | `SDT_BOOL` | 安装目录 |
| 1 | 连接MySql | `mysql_connect` | `SDT_INT` | 地址、用户名、密码、数据库、端口 |
| 2 | 断开MySql | `mysql_close` | 空 | MySql句柄 |
| 3 | 执行SQL语句 | `mysql_query` | `SDT_BOOL` | MySql句柄、SQL文本 |
| 4 | 取记录集 | `store_result` | `SDT_INT` | MySql句柄 |
| 5 | 释放记录集 | `free_result` | 空 | 记录集句柄 |
| 6 | 读字段值 | `fetch_text` | `SDT_BOOL` | 记录集、字段、结果变量 |
| 7 | 取记录集行数 | `num_rows` | `SDT_INT64` | 记录集句柄 |
| 8 | 当前行号 | `row_tell` | `SDT_INT64` | 记录集句柄（隐藏） |
| 9 | 到上一行 | `row_up` | `SDT_INT64` | 记录集句柄（隐藏） |
| 10 | 到下一行 | `row_next` | `SDT_BOOL` | 记录集句柄 |
| 11 | 到指定行 | `row_seek` | `SDT_BOOL` | 记录集、记录位置 |
| 12 | 到首行 | `row_head` | `SDT_BOOL` | 记录集句柄 |
| 13 | 到尾行 | `row_cauda` | `SDT_BOOL` | 记录集句柄 |
| 14 | 取字段总数 | `num_fields` | `SDT_INT` | 记录集句柄 |
| 15 | 序号到字段名 | `field_name` | `SDT_BOOL` | 记录集、序号、结果变量 |
| 16 | 字段名到序号 | `field_index` | `SDT_BOOL` | 记录集、字段名、结果变量 |
| 17 | 查找记录 | `mysql_select` | `SDT_INT` | 句柄、表名、字段名、条件、排序 |
| 18 | 增加记录 | `insert` | `SDT_BOOL` | 句柄、表名、赋值语句 |
| 19 | 更新记录 | `update` | `SDT_BOOL` | 句柄、表名、赋值语句、条件 |
| 20 | 删除记录 | `delete` | `SDT_BOOL` | 句柄、表名、条件 |
| 21 | 取字段宽度 | `field_len` | `SDT_INT` | 记录集、字段序号 |
| 22 | 取字段属性 | `field_type` | `SDT_INT` | 记录集、字段名或序号 |
| 23 | 取服务器版本 | `server_info` | `SDT_BOOL` | 句柄、结果变量 |
| 24 | 取客户端版本 | `client_info` | `SDT_BOOL` | 结果变量 |
| 25 | 创建库 | `create_db` | `SDT_BOOL` | 句柄、库名 |
| 26 | 删除库 | `delete_db` | `SDT_BOOL` | 句柄、库名 |
| 27 | 查找库 | `search_db` | `SDT_BOOL` | 句柄、库名 |
| 28 | 取库名列表 | `show_databases` | `SDT_BOOL` | 句柄，结果通过记录集读取 |
| 29 | 创建表 | `create_table` | `SDT_BOOL` | 句柄、表名、`字段信息类型[]` |
| 30 | 修改表 | `change_table` | `SDT_BOOL` | 句柄、表名、`表更改信息类型`、字段信息、修改类型 |
| 31 | 删除表 | `drop_table` | `SDT_BOOL` | 句柄、表名 |
| 32 | 查找表 | `search_table` | `SDT_BOOL` | 句柄、表名 |
| 33 | 取表名列表 | `show_table` | `SDT_BOOL` | 句柄，结果通过记录集读取 |
| 34 | 创建用户 | `create_user` | `SDT_BOOL` | 句柄、主机、用户名、密码、库、表、权限 |
| 35 | 删除用户 | `delete_user` | `SDT_BOOL` | 句柄、用户名、主机 |
| 36 | 查找用户 | `search_user` | `SDT_BOOL` | 句柄、用户名、主机 |
| 37 | 取用户列表 | `show_user` | `SDT_BOOL` | 句柄，结果通过记录集读取 |
| 38 | 修改用户 | `change_user` | `SDT_BOOL` | 句柄、用户名、主机、库、表、权限 |
| 39 | 建立索引 | `create_index` | `SDT_BOOL` | 句柄、表、列、索引名 |
| 40 | 删除索引 | `drop_index` | `SDT_BOOL` | 句柄、表、索引名 |
| 41 | 取错误文本 | `error_info` | `SDT_BOOL` | 句柄、错误信息结果变量 |
| 42 | 开始事务 | `begin_trans` | `SDT_BOOL` | 句柄 |
| 43 | 保存事务 | `commit_trans` | `SDT_BOOL` | 句柄 |
| 44 | 回滚事务 | `rollback_trans` | `SDT_BOOL` | 句柄 |
| 45 | 到MYSQL文本 | `mysql_type` | `SDT_TEXT` | 易语言数据、时间类型 |
| 46 | 写字节集字段 | `write_bin` | `SDT_BOOL` | 句柄、表、字段、条件、字节集 |
| 47 | 字段是否为空 | `field_is_null` | `SDT_BOOL` | 记录集、字段 |
| 48 | 选择库 | `select_database` | `SDT_BOOL` | 句柄、库名 |
| 49 | 关闭MySql | `shupdown_mysql` | `SDT_BOOL` | 句柄、服务器 shutdown 权限 |
| 50 | 返回服务器状态 | `mysql_status` | `SDT_BOOL` | 句柄、状态结果变量（隐藏） |
| 51 | 取影响行数 | `affected_rows` | `SDT_INT64` | 句柄 |
| 52 | 输出SQL | `SQL语句序号` | `SDT_BOOL` | SQL 序号、返回 SQL 文本（隐藏） |

### 6.3 常量与自定义数据类型

`mysql_const.cpp` 声明 57 个 `LIB_CONST_INFO`：

- 表结构操作常量：`字段基本类型`、`字段附加类型`、`增加字段`、`修改字段`、`删除字段`、`增加索引`、`删除索引`、`增加主键`、`删除主键`。
- 字段附加属性：`最大长度`、`无符号`、`以0填充`、`二进制`。
- MySQL 类型映射：`decimal`、`tinyint`、`bool`、`smallint`、`int`、`float`、`double`、`timestamp`、`bigint`、`mediumint`、`date`、`time`、`datetime`、`year`、多种 blob/text、`varchar`、`enum`、`set`、`char`，以及用于类型判断的组合值。
- 权限位：`无任何权限`、`查询权限`、`增加权限`、`更改权限`、`删除权限`、`索引权限`、`改变表权限`、`创建表或库或索引权限`、`删除表或库权限`、`备注表或库权限`、`重新装载服务器权限`、`关闭服务器权限`、`服务器进程管理权限`、`服务器文件存取权限`、`所有权限`。

`mysql_dtType.cpp` 声明 2 个 `LIB_DATA_TYPE_INFO`：

1. `字段信息类型` / `field_info`：10 个成员，包括 `类型`、`字段名`、`字段类型`、`列内容为空`、`列数据默认值`、`自增量标记`、`附加类型信息`、`附加内容`、`主键`、`索引`。
2. `表更改信息类型` / `table_alter`：4 个成员，包括 `字段名`、`字段信息`、`索引名`、`主键名`。

## 7. 数据模型与资源生命周期

### 7.1 已存在的数据模型（元数据模型）

| 模型 | 实际载体 | 说明 |
|---|---|---|
| 支持库信息 | `LIB_INFO g_LibInfo_mysql_global_var` | GUID、版本、系统要求、名称、语言、命令/常量/自定义类型计数与指针 |
| 命令定义 | `CMD_INFO g_cmdInfo_mysql_global_var[]` | 53 条命令的名称、说明、返回类型、参数区间、隐藏/平台标志 |
| 参数定义 | `ARG_INFO g_argumentInfo_mysql_global_var[]` | 104 个参数槽位；变量输出通过 `AS_RECEIVE_VAR` 标志描述 |
| 命令分发表 | `PFN_EXECUTE_CMD g_cmdInfo_mysql_global_var_fun[]` | 53 个命令实现函数指针 |
| 常量 | `LIB_CONST_INFO g_ConstInfo_mysql_global_var[]` | 57 个数字型常量及解释/英文名 |
| 自定义类型 | `LIB_DATA_TYPE_INFO g_DataType_mysql_global_var[]` | 2 个类型及其成员 `LIB_DATA_TYPE_ELEMENT[]` |
| 通知状态 | `fnshare.cpp` 静态变量 | `s_pfnNotifySys`、`s_pfnuserNotifySys`、`s_isDebug` |

### 7.2 设计中的外部数据库模型（当前未实现）

命令说明隐含了以下运行时资源，但源码没有对应 C++ 结构或管理表：

- `MySql句柄`：应代表连接对象；当前仅以 `SDT_INT` 作为句柄值声明。
- `记录集句柄`：应代表查询结果及当前行指针；当前仅以 `SDT_INT` 声明。
- 连接到数据库/当前库：连接参数包含地址、用户名、密码、数据库名、端口；没有持久化或连接池。
- 错误文本、服务器状态、影响行数：只有输出参数声明，没有错误缓存或结果字段。
- 事务：仅有开始/提交/回滚三个命令声明，没有事务状态机。

仓库中没有本地数据库、迁移、配置、缓存、日志、序列化文件或数据表；因此“数据模型”目前是易语言支持库元数据模型，而不是 MySQL 客户端运行时模型。

### 7.3 资源生命周期结论

- **已声明：** 连接应由“连接MySql”创建并由“断开MySql”释放；记录集应由“取记录集”产生并由“释放记录集”释放。
- **未实现：** 当前命令函数未创建、持有、释放任何连接或记录集；也没有异常路径、线程安全、句柄有效性校验或重复释放处理。
- **未验证：** 易语言运行时对 `SDT_INT` 句柄和输出变量的具体约定，以及 MySQL 客户端库版本兼容性。

## 8. 真实调用链与实现证据

### 8.1 当前可确认的调用链

```text
宿主加载 GetNewInf
  -> 读取 g_LibInfo_mysql_global_var
  -> 获取 g_cmdInfo_mysql_global_var[0..52]
  -> 按索引调用 g_cmdInfo_mysql_global_var_fun[i]
  -> 进入 mysql_<命令>_<编号>_mysql
  -> 读取 pArgInf[i]
  -> 函数结束（无 pRetData 写入、无外部调用）
```

### 8.2 证据与判定

- `mysql_cmdDef.cpp` 共 53 个 `MYSQL_EXTERN_C void` 函数；人工读取确认函数体只有局部参数取值语句。
- 53 个函数中没有 `pRetData` 引用；这直接证明当前函数没有按 ABI 写返回结果。
- `mysql_cmdDef.cpp` 没有 MySQL C API 头文件、连接函数、查询函数、结果集类型或链接符号。
- `include_mysql_header.h` 只包含 `elib` 与本库元数据头，不包含 `mysql.h`。
- 两个 `.vcxproj` 都没有 `AdditionalDependencies` 或 MySQL 客户端库路径声明。

由此，不能将 `mysql_cmd_typedef.h` 的命令说明当作已完成业务逻辑；真实 SQL/连接/记录集链路属于后续实现或历史缺失部分，当前首轮只记录为未实现/未验证。

## 9. 构建工程与依赖边界

### 9.1 解决方案

`mysql.sln` 使用 Visual Studio solution format 12.00 / VS 17 元信息，包含：

- `mysql.vcxproj`：GUID `{CEADC3DD-024E-4173-9CCF-E60334B2944F}`，配置类型为 `DynamicLibrary`。
- `mysql_static/mysql_static.vcxproj`：GUID `{5FF16995-6AD6-4964-A421-E0842E1BE946}`，配置类型为 `StaticLibrary`。
- 解决方案配置：`Debug|x64`、`Debug|x86`、`Release|x64`、`Release|x86`；x86 映射到项目的 `Win32`。

### 9.2 动态库项目

`mysql.vcxproj` 编译：

- `elib/fnshare.cpp`；
- `mysql_cmdDef.cpp`、`mysql_cmdInfo.cpp`、`mysql_const.cpp`、`mysql_dllMain.cpp`、`mysql_dtType.cpp`；
- 对应 `elib/*.h`、`include_mysql_header.h`、`mysql_cmd_typedef.h`；
- Win32 Debug/Release 使用 `__E_FNENAME=mysql`、`MYSQL_EXPORTS` 等预处理宏；Win32 目标扩展为 `.fne`，并使用 `Source_mysql.def`。
- 工具集声明为 `v141`，Windows SDK 版本声明为 `10.0.15063.0`，字符集为 Unicode，运行库为静态多线程（Debug `MultiThreadedDebug`，Release `MultiThreaded`）。

注意：项目的 x64 Debug/Release 配置没有像 Win32 配置那样声明 `__E_FNENAME=mysql`、`TargetExt=.fne` 和 `ModuleDefinitionFile=Source_mysql.def`；这可能造成命名或导出行为与 Win32 不一致，必须在 Windows 工具链中复核，本文不把它判定为已修复或已失败。

### 9.3 静态库项目

`mysql_static/mysql_static.vcxproj` 复用上级目录的 6 个 C/C++ 源文件和 9 个头文件，配置类型为 `StaticLibrary`。

- Win32 Debug/Release 定义 `__E_STATIC_LIB`、`__E_FNENAME=mysql`，使用多处理器编译。
- x64 Debug/Release 没有显式 `__E_FNENAME=mysql`；并且声明 `PrecompiledHeader=Use`、`PrecompiledHeaderFile=pch.h`，仓库实际未发现 `pch.h`，这是明确的构建风险点。
- 静态项目不包含 `Source_mysql.def`，符合静态库不通过 DLL `.def` 导出的方向。

### 9.4 依赖清单

| 依赖 | 证据 | 状态 |
|---|---|---|
| Visual Studio/MSBuild、MSVC `v141` | `mysql.sln`、两个 `.vcxproj` | 工具链声明，当前 macOS 未验证 |
| Windows SDK 10.0.15063.0 | 两个 `.vcxproj` | 工具链声明，当前未验证 |
| 易语言支持库 ABI | `elib/lib2.h` 等 | 源码随仓库携带，协议声明可读 |
| 易语言系统核心支持库 | `elib/krnllib.h`、`LIB_INFO` 的 3.7 要求 | 运行宿主依赖声明，未验证 |
| MySQL 客户端库 | 未发现 `mysql.h`、`mysqlclient.lib`、`libmysql.dll`、链接配置 | **缺失/未声明** |
| MySQL 服务器 | 由命令说明隐含 | 当前无连接代码，未验证 |

## 10. 测试、验证与当前可运行性

### 10.1 仓库测试现状

- 未发现测试目录、测试源文件、测试运行器、CI 配置或示例程序。
- `mysql.vcxproj.filters` 仅对源码/头文件做 IDE 分组，没有测试项目。
- 因而不存在“测试通过”的证据；只能记录源码和工程静态取证结果。

### 10.2 本轮已做的静态验证

- 现场核对仓库文件清单、项目/解决方案配置、源文件编码和主要源码。
- 统计并人工核对：53 个命令声明/实现函数、104 个参数元数据槽位、57 个常量、2 个自定义复合数据类型。
- 核对动态库/静态库项目的源文件集合、配置矩阵、预处理宏和导出定义。
- 核对命令函数是否写入 `pRetData`：当前 53 个命令均未引用 `pRetData`。
- 核对 MySQL 客户端依赖：源码和工程中均未发现 `mysql.h`、`mysqlclient`、`MYSQL*` 或 `AdditionalDependencies`。
- 核对 Git 基线：工作树在建档前为干净状态，本地 `HEAD` 与 `origin/master` 相同。

### 10.3 未执行/不能在当前环境执行的验证

- 未执行 Visual Studio/MSBuild 编译：当前现场为 macOS，仓库工程是 Windows/MSVC `v141` 项目。
- 未执行 DLL 装载、`GetNewInf` 宿主验收或易语言编译器/运行时验收。
- 未执行真实 MySQL 连接、SQL 查询、记录集遍历、事务、权限、字节集写入和错误读取。
- 未执行 Windows x86/x64 兼容性检查，也未确认 x64 项目导出/预编译头风险。

## 11. 风险、缺口与后续复核点

1. **功能实现缺口（最高优先级）**：53 个命令函数没有任何实际业务逻辑和返回值写入；当前不能作为可用 MySQL 支持库发布。
2. **数据库客户端依赖缺失**：需要明确支持的 MySQL/MariaDB 客户端版本、头文件、导入库、运行时 DLL 和许可证边界，并补进工程配置或适配层。
3. **句柄模型未定义**：需要设计连接句柄/记录集句柄的分配、查找、有效性、跨线程限制、释放和错误行为，不能仅以裸 `INT` 假定安全。
4. **SQL 构造安全性未定义**：插入/更新/查询/用户权限命令接收文本片段，当前没有转义、参数化、编码转换或标识符校验逻辑。
5. **结果转换未实现**：`SDT_TEXT`、`SDT_BIN`、`SDT_DATE_TIME`、数字和 NULL 到易语言变量的映射尚未实现；GBK/服务器字符集转换也未定义。
6. **事务语义未实现**：MyISAM/InnoDB 差异、自动提交、异常回滚、连接关闭时未提交事务均未处理。
7. **工程配置不对称**：动态库 x64 配置缺少 Win32 中的命名宏、`.fne` 后缀和 `.def` 导出设置；静态库 x64 使用不存在的 `pch.h`，需在 Windows 上复核。
8. **ABI 兼容风险**：源码携带的 `elib` 头文件含旧版 Windows/易语言 ABI 定义，`LIB_INFO` 声明要求系统/核心库版本 3.7，但 `krnllib.h` 自身记录的核心库版本为 4.5；两者是否为历史兼容关系需查对应易语言 SDK/宿主。
9. **命名风险**：命令 52 的内部名包含中文 `SQL语句序号`，需用目标 MSVC 与易语言静态编译链确认符号、导出和命令名数组行为。
10. **版本来源风险**：本地只有 1 个提交且为浅历史；不能从当前 Git 记录推断完整演进史，也没有把远程未读取内容写成事实。

## 12. 证据路径索引

### 12.1 项目与构建

- `mysql.sln:5-7,9-40`：动态库/静态库项目及 Debug/Release、x86/x64 解决方案配置。
- `mysql.vcxproj:21-41`：动态库源码/头文件/`.def` 清单。
- `mysql.vcxproj:43-202`：DynamicLibrary、`v141`、Windows SDK、预处理宏、Win32 `.fne` 与 `.def` 配置。
- `mysql_static/mysql_static.vcxproj:21-39,40-166`：静态库复用文件、StaticLibrary 配置、`__E_STATIC_LIB` 与 x64 预编译头配置。
- `Source_mysql.def:1-4`：DLL 仅导出 `GetNewInf`。

### 12.2 ABI 与装载入口

- `include_mysql_header.h:1-26`：SDK 聚合、全局元数据声明、`MYSQL_DEF_CMD` 命令函数声明宏。
- `elib/lib2.h:266-364`：`ARG_INFO`、`CMD_INFO`、命令状态与平台宏。
- `elib/lib2.h:693-748`：`LIB_DATA_TYPE_INFO`、`LIB_CONST_INFO`。
- `elib/lib2.h:780-824`：`MDATA_INF` 运行时参数 union 与输出变量指针。
- `elib/lib2.h:1152-1239`：系统通知码、`PFN_NOTIFY_LIB`、`PFN_EXECUTE_CMD`。
- `elib/lib2.h:1246-1318`：`LIB_INFO`、`GetNewInf` 固定入口定义。
- `mysql_dllMain.cpp:1-180`：DLL 入口、命令函数表、`LIB_INFO`、`GetNewInf`、通知处理。
- `elib/fnshare.cpp:1-71`、`elib/fnshare.h:1-260`：通知转发、内存/文本/数组辅助函数。

### 12.3 命令、参数、常量与数据类型

- `mysql_cmd_typedef.h:1-66`：`MYSQL_NAME`/`MYSQL_NAME_STR` 和 0–52 共 53 项 `MYSQL_DEF`。
- `mysql_cmdInfo.cpp:1-约 180`：104 个参数槽位、`g_cmdInfo_mysql_global_var` 与命令数量。
- `mysql_cmdDef.cpp:1-约 565`：53 个命令函数壳；当前仅读取参数，无 `pRetData` 写入。
- `mysql_const.cpp:1-约 76`：57 项 `LIB_CONST_INFO`，含类型/字段属性/权限常量。
- `mysql_dtType.cpp:1-约 58`：`字段信息类型` 和 `表更改信息类型` 两个自定义类型。

### 12.4 基线核对

- Git 分支、提交、远程和工作树状态：仓库根执行 `git status --short --branch`、`git log -1 --format='%H%n%aI%n%s'`、`git remote -v`、`git rev-parse HEAD origin/master`。
- 本轮静态取证未修改上述源码、工程、依赖、测试或 Git；唯一写入目标为仓库根 `ARCHITECTURE.md`。

## 13. 首轮结论

该仓库目前更准确的定位是：**一个带完整易语言支持库元数据和命令接口设计的 MySQL 支持库工程骨架**，而不是已经完成数据库访问的实现。其可复用价值主要在于易语言支持库 ABI 接入方式、X-macro 命令登记、参数/常量/复合数据类型描述、动态/静态库双工程组织和通知生命周期入口；其 MySQL 连接、SQL 执行、记录集、错误、事务、权限和二进制数据能力均需后续从源码或历史版本重新取证，当前不能宣称已实现。

后续深挖应优先复核：远程完整历史/标签、是否存在未纳入仓库的 MySQL 客户端依赖、Windows 工具链实际编译结果，以及是否有对应易语言示例或发布包；在这些证据出现前，保持本文“接口已声明、运行实现未验证/未实现”的判定不变。
