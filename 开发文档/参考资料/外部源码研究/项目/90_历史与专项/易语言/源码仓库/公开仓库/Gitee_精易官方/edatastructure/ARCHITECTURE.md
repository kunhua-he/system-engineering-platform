# edatastructure 架构建档

> 首轮全量架构建档。本文只记录当前仓库源码与工程文件能够证明的事实；未运行构建、未运行源码、未修改源码、未提交 Git。后续以本文件为唯一项目架构档案。

## 1. 项目定位

`edatastructure` 是面向易语言的 Windows 数据结构支持库源码，仓库同时提供动态库工程 `edatastructure` 与静态库工程 `edatastructure_static`。支持库元信息在 `edatastructure_dllMain.cpp` 的 `g_LibInfo_edatastructure_global_var` 中声明：库名为“数据结构支持库”，版本为 `2.0.0`，要求易语言系统 `3.7`、系统核心支持库 `3.7`，支持语言为 `__GBK_LANG_VER`，操作系统状态为 `_LIB_OS(OS_ALL)`（`edatastructure_dllMain.cpp:34-67`）。

源码注释给出的能力范围是：节点、链表、栈、队列、树、二叉树和表（Map）等数据类型（`edatastructure_dllMain.cpp:45-47`）。当前仓库是 2022-12-19 初始化提交的浅克隆，未发现 README、测试目录或旧“细探”文档。

## 2. 总体流程图

```text
易语言运行时 / IDE
        │
        ├─ 动态加载 edatastructure.dll
        │       ├─ 固定导出 GetNewInf()
        │       └─ 通过 LIB_INFO 取得库元信息、数据类型、命令表、命令函数表
        │
        ├─ 向 edatastructure_ProcessNotifyLib_edatastructure 发送系统通知
        │       └─ NL_SYS_NOTIFY_FUNCTION → fnshare.cpp 保存 NotifySys 回调
        │
        └─ 编译器/运行时按 CMD_INFO 命令索引调用 PFN_EXECUTE_CMD
                │
                └─ edatastructure_cmdDef.cpp
                        ├─ ENode：属性型节点
                        ├─ EList：有序链表与当前节点游标
                        ├─ EStack：后进先出容器
                        ├─ EQueue：先进先出容器
                        ├─ EBiTree：按键值组织的二叉排序树
                        ├─ ETree：普通树、子节点/兄弟节点遍历
                        └─ Map：字节集键 → 节点值的键值容器
```

以上是源码声明的装配/调用关系，不代表当前命令实现已具备完整运行逻辑；实现文件中大量命令函数只有参数取值局部变量，详见“实现状态与限制”。

## 3. 工程与目录地图

```text
edatastructure/
├── edatastructure.sln                         # VS 17 solution，动态库+静态库
├── edatastructure.vcxproj                     # 动态库工程
├── edatastructure_static/
│   ├── edatastructure_static.vcxproj          # 静态库工程，引用根目录源码
│   ├── edatastructure_static.vcxproj.filters
│   └── edatastructure_static.vcxproj.user
├── edatastructure_dllMain.cpp                 # DLL 入口、LIB_INFO、GetNewInf、通知入口
├── edatastructure_cmd_typedef.h               # EDATASTRUCTURE_DEF 命令单一宏定义
├── edatastructure_cmdInfo.cpp                  # ARG_INFO、CMD_INFO、静态命令名表
├── edatastructure_cmdDef.cpp                   # 97 个导出命令函数的实现壳
├── edatastructure_dtType.cpp                   # 7 个自定义数据类型及成员索引/成员属性
├── edatastructure_const.cpp                    # 常量表（当前数量为 0）
├── include_edatastructure_header.h             # 公共头、全局元数据声明、命令原型展开
├── Source_edatastructure.def                   # DLL 导出 GetNewInf
└── elib/
    ├── lib2.h                                  # 易语言支持库 ABI、LIB_INFO、CMD_INFO、MDATA_INF
    ├── fnshare.h / fnshare.cpp                 # NotifySys、内存/系统通知共享辅助层
    ├── krnllib.h                               # 系统核心支持库常量与接口声明
    ├── lang.h                                  # GBK/英语/BIG5/SJIS 语言常量
    ├── mtypes.h                                # Windows/易语言兼容基础类型别名
    ├── untshare.h                              # 复合数据/属性相关共享 C++ 类型
    └── PublicIDEFunctions.h                    # IDE 公共功能通知常量与参数结构
```

工程文件的真实编译输入来自 `edatastructure.vcxproj:21-42`；静态工程用 `..\` 引用同一批根目录源码（`edatastructure_static/edatastructure_static.vcxproj:21-39`），不是另一套实现。Solution 同时声明 Debug/Release 与 x86/x64 配置（`edatastructure.sln:5-32`）。

## 4. 构建系统与依赖边界

### 4.1 动态库工程

- `edatastructure.vcxproj` 的 `ConfigurationType` 为 `DynamicLibrary`（`edatastructure.vcxproj:51-74`）。
- Win32 配置使用 `PlatformToolset v141`、Unicode、运行库 Debug=`MultiThreadedDebug`、Release=`MultiThreaded`（`edatastructure.vcxproj:51-74,109-190`）。
- Win32 动态库链接阶段指定 `Source_edatastructure.def`，输出扩展名设置为 `.fne`（`edatastructure.vcxproj:95-128,132-157`）。x64 配置未在项目文件中指定模块定义文件或 `.fne` 扩展名（`edatastructure.vcxproj:159-197`），这是一个需在 Windows/Visual Studio 中复核的工程差异。
- 预处理宏包含 `__E_FNENAME=edatastructure`；Win32 还包含 `EDATASTRUCTURE_EXPORTS`、`_USRDLL` 等（`edatastructure.vcxproj:109-120,132-145`）。

### 4.2 静态库工程

- `edatastructure_static.vcxproj` 的 `ConfigurationType` 为 `StaticLibrary`（`edatastructure_static/edatastructure_static.vcxproj:48-72`）。
- Win32 预处理定义含 `__E_STATIC_LIB` 与 `__E_FNENAME=edatastructure`（`edatastructure_static/edatastructure_static.vcxproj:92-121`）；这会使公共头和通知逻辑按静态库分支编译。
- x64 配置使用预编译头 `pch.h`（`edatastructure_static/edatastructure_static.vcxproj:130-163`），但仓库文件清单中没有 `pch.h`；该配置是否能直接构建未验证。

### 4.3 ABI 与外部边界

- `elib/lib2.h` 定义易语言支持库 ABI：`CMD_INFO` 描述命令名、英文名、返回类型、参数数量和参数表（`elib/lib2.h:297-364`）；`LIB_DATA_TYPE_INFO` 描述自定义数据类型及成员命令索引（`elib/lib2.h:693-729`）；`MDATA_INF` 是命令返回值/参数的运行时数据载体，含基本值、文本、字节集、复合数据和变量地址指针（`elib/lib2.h:786-823`）。
- 命令实现统一签名为 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`（`elib/lib2.h:1236-1239`）。
- 固定库元信息入口是 `GetNewInf`（`elib/lib2.h:1317-1318`）；`.def` 文件仅导出 `GetNewInf`（`Source_edatastructure.def:1-4`）。
- `include_edatastructure_header.h` 引入 `elib/lib2.h`、`lang.h`、`krnllib.h` 和命令类型定义，并以 `EDATASTRUCTURE_DEF` 宏展开所有命令原型（`include_edatastructure_header.h:1-24`）。
- 依赖库字符串 `m_szzDependFiles` 当前为 `NULL`（`edatastructure_dllMain.cpp:83-86`）；代码未声明第三方库依赖。Windows SDK、Visual C++ v141 和易语言运行时/IDE ABI 是工程实际外部边界。

## 5. 核心数据模型

### 5.1 支持库元模型

`LIB_INFO g_LibInfo_edatastructure_global_var` 将以下对象装配到易语言运行时（`edatastructure_dllMain.cpp:34-86`）：

1. 7 个自定义数据类型：`g_DataType_edatastructure_global_var`。
2. 1 个命令类别：`"0000出错信息\0\0"`。
3. 命令描述数组：`g_cmdInfo_edatastructure_global_var`。
4. 命令函数指针数组：`g_cmdInfo_edatastructure_global_var_fun`。
5. 参数描述数组：`g_argumentInfo_edatastructure_global_var`。
6. 常量表：`g_ConstInfo_edatastructure_global_var`，当前计数为 0。
7. 通知函数：`edatastructure_ProcessNotifyLib_edatastructure`。

### 5.2 自定义数据类型

`edatastructure_dtType.cpp:120-176` 声明 7 个库定义类型：

| 索引 | 中文名 | 英文名 | 语义/实现线索 | 成员命令索引 |
|---:|---|---|---|---|
| 0 | 节点 | `ENode` | 可有零个或多个属性 | 0–12 |
| 1 | 链表 | `EList` | 保存节点，按数据链组织；命令说明称加入时按键值升序 | 13–33 |
| 2 | 栈 | `EStack` | 节点容器，后进先出 | 34–42 |
| 3 | 队列 | `EQueue` | 节点容器，先进先出 | 43–51 |
| 4 | 二叉树 | `EBiTree` | 按键值组织的二叉排序树 | 52–70 |
| 5 | 树 | `ETree` | 普通树结构 | 71–86 |
| 6 | 表 | `Map` | 字节集键与节点值的键值对容器 | 88–96 |

每种类型通过 `s_dtCmdIndex...` 数组把类型成员映射到全局命令索引；通过 `s_objEvent...` 数组声明隐藏成员。`Map` 的类型索引跳过全局命令 87，因为 87 是全局命令“取失败原因”（`edatastructure_dtType.cpp:1-56,120-176`；`edatastructure_cmd_typedef.h:100-109`）。

可见的隐藏成员包括：`ENode` 的“节点的指针”、`EList` 的“链表当前节点的指针/链表中节点的数量”、`EStack` 的“栈顶指针/栈中节点的数量”、`EQueue` 的同类状态字段、`Map` 的隐藏 `Map` 成员（`edatastructure_dtType.cpp:59-118`）。其实际内存布局由易语言运行时复合数据 ABI 管理；本仓库没有独立序列化格式或持久化模型。

### 5.3 命令与参数模型

`EDATASTRUCTURE_DEF` 是命令元数据的单一来源，编号连续 `0–96`，共 97 条（`edatastructure_cmd_typedef.h:13-109`）。宏被多次展开为：

- `include_edatastructure_header.h:22-24`：命令函数原型；
- `edatastructure_dllMain.cpp:26-31`：函数指针数组；
- `edatastructure_cmdInfo.cpp:131-141`：`CMD_INFO` 命令说明数组；
- `edatastructure_cmdInfo.cpp:94-98`：静态编译所需的函数名数组。

`edatastructure_cmdInfo.cpp:5-124` 声明参数表，共 60 个参数项（编号 `000–059`）；每条命令通过 `m_nArgCount` 与 `g_argumentInfo... + offset` 关联参数区。参数类型使用 `SDT_*`、`MAKELONG(0xNN, 0)` 表示库自定义类型，并用 `AS_RECEIVE_VAR`、`AS_DEFAULT_VALUE_IS_EMPTY` 等标志表达引用参数、数组参数和可省略参数（`edatastructure_cmdInfo.cpp:5-122`）。

## 6. API、入口与调用链

### 6.1 DLL 加载入口

```text
Windows LoadLibrary
  → DLL_PROCESS_ATTACH（DllMain，当前只返回 TRUE）
  → GetNewInf()
  → PLIB_INFO
      → 命令/函数/参数/数据类型表
      → edatastructure_ProcessNotifyLib_edatastructure()
```

`DllMain` 的四类进程/线程通知分支均为空，仅返回 `TRUE`（`edatastructure_dllMain.cpp:6-24`）。动态库的公开导出由 `.def` 约束为 `GetNewInf`。

### 6.2 系统通知

`edatastructure_ProcessNotifyLib_edatastructure` 处理以下通知（`edatastructure_dllMain.cpp:101-177`）：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNamesedatastructure`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回通知函数名字符串；
- `NL_GET_DEPENDENT_LIBS`：返回空依赖字符串 `"\0\0"`；
- `NL_SYS_NOTIFY_FUNCTION`：转发到 `ProcessNotifyLib`，由 `elib/fnshare.cpp:24-64` 保存系统回调；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 未知通知：返回 `NR_ERR`。

`elib/fnshare.cpp:11-70` 提供 `NotifySys`、`ProcessNotifyLib`、`SetUserSysNotify`。`NotifySys` 只有在系统回调非空时才转发；`ProcessNotifyLib` 在设置系统回调后读取 `NRS_GET_PRG_TYPE`，并可继续调用用户回调。

### 6.3 命令调用

```text
易语言编译器/运行时
  → 由 CMD_INFO 定位命令索引与参数描述
  → g_cmdInfo_edatastructure_global_var_fun[索引]
  → edatastructure_<命令英文名>_<索引>_edatastructure
  → pArgInf[1..nArgCount] 读取输入/引用参数
  → pRetData 写入返回值（按 CMD_INFO 的返回类型）
```

命令函数的导出/链接名字由 `edatastructure_cmd_typedef.h:3-10` 的宏拼接生成，形式类似 `edatastructure_<英文命令名>_<编号>_edatastructure`。动态库函数指针表和命令描述表都由同一个 `EDATASTRUCTURE_DEF` 展开，理论上依赖编号一致性；仓库没有独立运行时注册器。

## 7. 功能分域与命令面

| 数据类型/范围 | 命令编号 | 能力概览 |
|---|---:|---|
| `ENode` | 0–12 | 创建/释放/复制；加入、删除、修改属性；读取全部属性名、属性类型和数值/逻辑/日期/文本/字节集值 |
| `EList` | 13–33 | 创建/释放/复制；空判断、计数；按键值添加/删除/修改；首尾/当前节点游标移动；搜索与读取节点 |
| `EStack` | 34–42 | 创建/释放/复制；空判断、计数、清空；查看栈顶、压入、弹出 |
| `EQueue` | 43–51 | 创建/释放/复制；空判断、计数、清空；查看队首、压入、弹出 |
| `EBiTree` | 52–70 | 创建/释放/复制；空判断、计数、深度；左右子树/根/父节点导航；搜索、插入、修改、删除 |
| `ETree` | 71–86 | 创建/释放/复制；空判断、计数、清空；子节点/兄弟/根/父节点导航；读取子节点数、插入、修改、删除、当前节点索引 |
| 全局 | 87 | `DSGetErrMsg`，读取上一次失败原因 |
| `Map` | 88–96 | 创建/释放/复制；加入/读取键值对；取大小、取全部键；删除键值对或全部键值对 |

命令名称、返回类型和参数约束以 `edatastructure_cmd_typedef.h` 为准；上表是按源码元数据的功能归纳，不是额外 API 契约。

## 8. 实现状态与限制

### 8.1 已确认的结构实现

- 工程项目、动态库/静态库双构建目标、源码输入和配置矩阵已存在。
- 支持库 ABI 装配链完整存在：`GetNewInf`、`LIB_INFO`、命令表、函数指针表、参数表、数据类型表、通知入口。
- 97 个命令函数符号在 `edatastructure_cmdDef.cpp` 中按编号生成，函数名与 `EDATASTRUCTURE_DEF` 的 0–96 编号对应。
- 7 个自定义数据类型的成员命令索引和隐藏成员元数据已声明。

### 8.2 当前源码显示的未完成/未验证部分

`edatastructure_cmdDef.cpp` 的命令函数普遍只是读取 `pArgInf` 到局部变量。例如 `AddAttr` 仅取出文本指针和字节指针（`edatastructure_cmdDef.cpp:31-36`），`ListAddNode` 仅取出复合节点和键值（`edatastructure_cmdDef.cpp:166-171`），`BiTreeDelete` 仅取出键值和删除标记（`edatastructure_cmdDef.cpp:565-570`）。文件内 97 个函数没有发现对应的数据结构算法、状态写入、错误码设置或 `pRetData` 填充逻辑的可见实现；构造/释放函数也为空函数体（例如 `edatastructure_cmdDef.cpp:6-17`）。

因此当前建档只能确认“支持库接口与代码生成骨架存在”，不能把节点/链表/树/Map 的实际运行行为判定为已实现。真实的算法实现可能来自未提交文件、生成阶段或外部运行时，但在本仓库当前提交中没有证据。

其他限制：

- 没有发现持久化、文件数据库、网络协议或序列化层；数据结构按源码说明属于内存容器。
- 没有发现异常/错误对象模型；接口依赖布尔返回值、输出参数和全局“取失败原因”命令，但当前函数骨架未展示其具体状态存储。
- 没有发现线程同步、锁、并发安全或所有权说明；不能假定容器可跨线程使用。
- `DllMain` 和多数通知分支为空；IDE 插件功能不是当前代码的已实现重点。

## 9. 测试、验证与发布证据

### 9.1 仓库内测试现状

未发现 `test/`、`tests/`、`测试/`、CTest、GoogleTest、单元测试工程或测试脚本；工程文件也只列出动态库/静态库源码，没有测试项目。当前提交未提供可在 macOS 上直接执行的测试入口。

### 9.2 当前核对实际执行的只读检查

- `git status --short --branch`：工作树初始为 `master...origin/master`，无源码改动。
- `git log -1`：`edf180249953f602318e5024eb31343bf380f877`，2022-12-19 16:54:52+08:00，`初始化仓库`。
- `git remote -v`：`origin` 为 `https://gitee.com/JYtechnology/edatastructure.git`。
- `git ls-remote origin HEAD refs/heads/master`：远程 `HEAD` 与 `master` 均为 `edf180249953f602318e5024eb31343bf380f877`，本地与远程默认分支提交一致。
- 文件清单/行数盘点：受 Git 跟踪的源码与工程文件共 23 个，合计约 5,213 行；未计 `.git` 内部文件。
- 只读源码阅读：工程、ABI 头、入口、类型元数据、命令元数据、命令函数骨架和共享辅助层。

### 9.3 未执行事项

按任务边界未执行：Visual Studio/MSBuild 构建、Windows 运行、DLL 加载、易语言 IDE 集成、静态库链接、单元测试、压力测试、ABI 实测、第三方依赖安装、Git fetch/pull、Git 提交。当前宿主为 macOS，不能据此验证 Windows 工程可构建或运行。

## 10. Git 与版本基线

| 项目 | 事实 |
|---|---|
| 本地分支 | `master` |
| 本地 HEAD | `edf180249953f602318e5024eb31343bf380f877` |
| HEAD 提交 | `初始化仓库`，2022-12-19 16:54:52+08:00 |
| 远程 | `origin https://gitee.com/JYtechnology/edatastructure.git` |
| 远程 HEAD/master | `edf180249953f602318e5024eb31343bf380f877` |
| 标签 | 未发现标签 |
| 工作树 | 建档前干净；当前核对仅新增本文件 |

版本信息还包括库内部 `LIB_INFO` 的 `2.0.0` 与 ABI `LIB_FORMAT_VER=20000101`（`edatastructure_dllMain.cpp:34-67`、`elib/lib2.h:1246-1258`）。这两个版本维度分别代表支持库产品元信息与 ABI 格式，不应混为 Git 提交版本。

## 11. 风险与后续复核点

1. **阻断性未验证：命令实现**。需要在 Windows/易语言运行时中确认 97 个命令是否只是当前提交的空骨架，还是由其他生成/链接机制补足；重点观察 `pRetData`、失败原因和复合数据内存释放。
2. **阻断性未验证：自定义类型内存布局**。`MDATA_INF.m_pCompoundData` 的实际布局来自易语言运行时约定，当前仓库没有实现或测试证据；构造、复制、析构和嵌套复合数据必须做 ABI 实测。
3. **重要风险：x64 工程配置不对称**。x64 动态库没有显式 `.def`/`.fne` 设置，x64 静态库引用缺失的 `pch.h`，应在 Visual Studio 中分别验证。
4. **重要风险：错误状态链缺失**。命令说明依赖“取失败原因”，但当前实现骨架未见错误状态存储或输出赋值；失败原因是否线程隔离、对象隔离、调用后即覆盖均未确认。
5. **重要风险：参数 ABI 边界**。`MAKELONG(0x01..0x07, 0)` 自定义类型编号、`AS_RECEIVE_VAR` 引用参数和数组返回值必须与目标易语言版本的 `lib2.h` ABI 一致，不能只依据宏名推断。
6. **重要风险：编码与平台**。源码为 GB18030/CRLF 风格，支持库元信息声明 GBK；跨工具读取或迁移时若误转 UTF-8，可能破坏易语言 IDE 显示或字符串 ABI。
7. **重要风险：仓库年代与可追溯性**。当前仓库为浅克隆且只有一个初始化提交，没有历史修复、发布包、变更日志或标签可供比对。
8. **建议：补充可执行测试**。至少应覆盖 `GetNewInf` 元数据一致性、命令数量/函数指针索引一致性、每类容器的构造/复制/释放/空容器边界、键值唯一性、树删除策略、错误原因和内存释放。
9. **建议：冻结 ABI 清单**。应保存目标易语言版本、Visual Studio 工具集、x86/x64 输出文件名、导出符号和 `LIB_INFO` 字段快照，作为后续构建验收基线。

## 12. 当前核对结论

`edatastructure` 的可确认架构是一个“易语言支持库 ABI 适配层”：以 `EDATASTRUCTURE_DEF` 为命令元数据单一来源，通过 `LIB_INFO` 将 7 个自定义内存数据类型、97 个命令、60 个参数描述、命令函数指针表和系统通知入口注册给易语言运行时；动态库与静态库共享同一份源代码。

但当前提交中 `edatastructure_cmdDef.cpp` 只呈现命令函数骨架，未提供可证明的容器算法和返回值实现；仓库无测试、无运行样例，Windows 构建与 ABI 集成均未验证。因此首轮建档结论为：**接口/工程架构已建档；运行实现与可发布性待 Windows + 易语言运行时复核，不能宣称已完成可用支持库。**

## 13. 后续：数据结构、所有权、序列化、线程与分层裁决

### 13.1 先分清“声明存在”与“实现存在”

当前核对不把命令注释、`CMD_INFO` 或 `LIB_DATA_TYPE_INFO` 当成算法实现。当前提交的证据应分为四层：

| 证据层 | 当前源码能证明的内容 | 当前不能证明的内容 |
|---|---|---|
| 类型声明 | `edatastructure_dtType.cpp:120-176` 声明 `ENode`、`EList`、`EStack`、`EQueue`、`EBiTree`、`ETree`、`Map` 七种库定义类型；各自成员命令索引在 `:5-56`，隐藏成员在 `:59-118` | 这些隐藏成员背后的真实对象布局、指针有效期、深拷贝规则 |
| 命令契约声明 | `edatastructure_cmd_typedef.h:13-109` 用 `EDATASTRUCTURE_DEF` 声明 0–96 共 97 个命令；`edatastructure_cmdInfo.cpp:5-124` 声明参数、引用参数、可省略参数、返回类型和失败文字 | 命令是否真的修改容器、是否填充返回值、是否设置失败原因 |
| ABI/装配声明 | `elib/lib2.h:693-729,780-824,1234-1239,1246-1315` 定义 `LIB_DATA_TYPE_INFO`、`MDATA_INF`、`PFN_EXECUTE_CMD`、`LIB_INFO`；`edatastructure_dllMain.cpp:31-92` 返回库元信息和函数表 | 目标易语言运行时是否接受当前结构体布局、调用约定、位宽和指针语义 |
| 代码实现证据 | `edatastructure_cmdDef.cpp` 的 97 个函数确实有符号和参数读取局部变量；例如构造/释放 `:6-17`、链表构造/释放/复制 `:127-147`、Map 操作 `:710-780` | 本提交中没有 `pRetData` 写回、算法状态更新、`new/delete`、`ealloc/efree`、`MFree`、`NRS_FREE_VAR`、锁或序列化调用；静态扫描结果为零命中 |

因此，“支持节点、链表、栈、队列、树、二叉树、Map”目前是**库元信息和命令面声明**；不能升级为“这些容器已实现”。特别是构造/析构命令虽按隐藏成员登记为系统生命周期入口，但函数体为空，释放责任尚未落地。

### 13.2 内存、所有权和释放：ABI 规则属于运行核心，适配动作属于支持库

`MDATA_INF` 是本仓库最重要的内存边界：

- `m_pText`、`m_pBin` 是传入数据的只读借用指针；`elib/lib2.h:793-795` 明确不能直接改写，且文本可能指向常量段。
- `m_pCompoundData` 是复合数据借用/可修改指针；`m_ppCompoundData` 才是复合数据变量的写回地址。运行时说明要求：替换成员前必须先释放旧成员（`elib/lib2.h:798,816`）。
- `m_ppText`、`m_ppBin` 是变量写回地址；写入新值前必须用 `MFree(*m_ppText)`/`MFree(*m_ppBin)` 释放旧指针，不能直接修改旧指针指向内容（`elib/lib2.h:811-812`）。
- `m_ppAryData` 替换数组前必须通过 `NRS_FREE_VAR` 释放原值，数组元素指针可能为空且不能直接改写（`elib/lib2.h:817`）。
- `elib/fnshare.h:25-40` 的 `ealloc/efree` 是通过 `NotifySys(NRS_MALLOC/NRS_MFREE)` 使用易语言堆的辅助实现；`CloneTextData`、`CloneBinData` 在 `:58-85` 明确把所有权交给调用方，注释要求不用时 `efree()`。这些是共享 SDK 辅助，不是 `edatastructure_cmdDef.cpp` 已调用的实现证据。
- `GetAryElementInf`/`GetBinData`/`allocArray`（`elib/fnshare.h:107-169`）只说明一种易语言数组/字节集内存格式读取和生成方式；不能据此推导 `ENode` 或容器内部布局。

**所有权裁决：** 当前库没有声明“加入节点/Map 值”是借用、浅拷贝还是深拷贝，也没有证明 `取节点`、`取当前节点`、`弹出` 写回后的节点由容器继续持有还是转移给调用方。现代落点必须固定为：

1. **运行核心**唯一持有通用 ABI 的分配、释放、写回、位宽、数组/字节集规则，并提供可审计的 `借用/复制/转移/释放` 结果；不让每个模块自行猜 `MDATA_INF`。
2. **数据结构支持库**实现具体容器的节点存储、复制和销毁，并在公开入口完成 ABI 到内部值的适配；任何节点进入容器的语义必须显式固定为“深拷贝”或“所有权转移”，不得隐式借用调用方指针。
3. **模块库**只接收稳定的逻辑节点/键值对象，不持有 `m_pCompoundData`、`m_ppText`、`m_ppAryData` 等裸 ABI 指针；模块组合失败时不得释放不属于它的借用值。
4. 释放必须覆盖正常返回、业务失败、输出写回失败、取消/超时、卸载通知和宿主崩溃；“有 `释放` 命令声明”不等于“已安全释放”。

### 13.3 数据结构、序列化、线程安全和 ABI 的单链路落点

这是针对平台底座的**映射裁决**，不是声称本仓库已经有“模块库/运行核心”目录。当前仓库把 ABI 适配和数据结构命令壳混在同一支持库中；若吸收为平台能力，应拆成一条链：

```text
调用方/业务模块
  → 模块库：稳定的节点、链表、栈、队列、树、Map 逻辑接口与组合流程
  → 数据结构支持库：具体容器算法、节点深拷贝/转移、键值规则、失败转换
  → 运行核心：MDATA_INF ABI 校验、易语言堆/数组释放、线程/租约/超时、错误证据与版本门
  → 易语言运行时 / Windows ABI
```

| 主题 | 数据结构支持库（本项目可吸收的实现 owner） | 模块库（上层组合 owner） | 运行核心（公共治理 owner） | 本仓库状态 |
|---|---|---|---|---|
| 数据结构 | 实现七类容器的真实算法、游标/根/父子/兄弟关系、键唯一性、复制与删除策略；公开能力不泄漏原始指针 | 把容器组合成业务流程，统一输入输出形状；不重复实现树/Map 算法 | 不承载领域算法，只提供调用、预算、取消和状态隔离 | 仅类型/命令声明；算法未见于 `edatastructure_cmdDef.cpp` |
| 内存/所有权 | 把“节点进入容器/从容器取出/弹出/复制”的深拷贝或转移语义写入契约；失败不得遗留半节点 | 只持有逻辑值或受管句柄；不调用 `MFree`/`NRS_FREE_VAR` | 统一分配器、释放器、数组/字节集/复合数据 ABI 规则、崩溃回收和残留检查 | ABI 规则在 `lib2.h`；目标实现没有分配/释放调用 |
| 序列化 | 若能力需要，提供逻辑值编码/解码适配；不得序列化裸指针、填充字节或运行时对象地址 | 定义版本化的节点/容器快照 schema、键顺序、空值和错误语义 | 提供帧长/上限/临时缓冲、校验、原子写入和版本兼容；不定义业务字段 | 目标无持久化；`untshare.h:14-65,180-195` 只有虚方法默认成功、注释代码和空字符串辅助 |
| 线程安全 | 明确单线程、实例级锁或不可变快照；若加锁，只保护本库对象，不把锁语义藏在模块 | 串行编排或通过运行核心提交并发任务；不跨线程共享游标/裸指针 | 负责线程隔离、锁/租约、超时取消、进程隔离和宿主退出清理 | 全仓未命中 `std::mutex`、`CRITICAL_SECTION`、`CreateMutex`、`CreateThread` 等同步实现；`fnshare.cpp:7-9` 的回调是进程级静态变量且无同步 |
| ABI | 实现 `GetNewInf`/`LIB_INFO`/命令函数表与具体能力的适配，按固定 `CDECL` 签名填充返回值 | 只依赖稳定中文逻辑契约，不直接拼命令索引或 `MDATA_INF` | 维护 ABI 版本、结构体/调用约定/位宽/编码检查和统一错误边界 | `GetNewInf`、`.def`、函数表存在；x86/x64、Windows 运行时 ABI 未实测 |

**单一 owner 规则：** 一个 ABI 字段的释放规则只能由运行核心定义；一个容器算法只能由数据结构支持库实现；一个业务快照 schema 只能由模块库声明；不能让三层各自复制一套“节点/Map/释放/序列化”实现。

### 13.4 序列化边界：当前没有可吸收的实现

`elib/untshare.h` 的 `CPropertyInfo::Serialize` 默认直接返回 `TRUE`，`SaveData` 返回空 `HGLOBAL`，`LoadData` 对非空输入也最终返回 `TRUE`（`:14-65`）；`SerializeCString` 的读写代码全部注释（`:180-195`）。这只能作为历史 SDK 模板，不能登记为 `edatastructure` 的序列化能力。

因此后续裁决为：

- **吸收**：把“不能把运行时指针图直接落盘”的原则和 `MDATA_INF` 的借用/释放约束纳入运行核心契约。
- **待核**：节点属性的类型编码（数值/逻辑/日期/文本/字节集）、容器游标/父子关系、Map 字节集键的规范化、版本迁移和失败后回滚。
- **新建（未启动）**：若确有持久化需求，在模块库定义版本化逻辑快照，在支持库实现编码器/解码器，在运行核心提供长度限制、校验和临时资源释放；不得复用 `CPropertyInfo` 的默认成功返回冒充实现。
- **废弃为实现证据**：`SaveData`/`LoadData`/`SerializeCString` 的注释块和默认返回值，不得写入能力目录或验收通过项。

### 13.5 失败、释放和并发矩阵

| 反向场景 | 合同上应发生的结果 | 当前源码证据 | 释放/恢复要求 |
|---|---|---|---|
| 空容器取首/尾/当前、无当前节点 | 返回假或约定失败值，并立即更新失败原因 | 命令说明有此类语义；实现未写 `pRetData`，也未写错误状态（`cmdDef.cpp:149-289,335-355,405-425,482-532`） | 不得写入无效输出；失败原因读取后不得继续使用悬空输出 |
| 重复键、非法键、节点类型不符 | 拒绝或按明确覆盖规则返回；Map 仅声明相同键覆盖 | `cmdInfo.cpp:53` 约束链表键非负且唯一；`cmd_typedef.h:104` 声明 Map 覆盖；真实检查未见 | 输入借用值不归库释放；已分配的临时副本必须回收 |
| 复制/更新/插入中途失败 | 原对象保持不变，不能留下半节点或部分树 | 复制/更新函数仅读取复合指针（如 `cmdDef.cpp:143-147,212-225,537-562`） | 采用临时深拷贝后提交；失败销毁临时对象，禁止半成品进入容器 |
| 取文本/字节集/数组/复合值写回 | 成功才替换输出旧值；失败保持输出可定义 | ABI 释放规则在 `lib2.h:811-817`，目标实现无写回 | 先按运行核心规则释放旧值，再原子写入；任何异常走 finally/宿主回收 |
| 序列化截断、坏版本、超限或解码失败 | 稳定错误码；不返回“成功但空对象” | 当前没有目标序列化入口；通用模板反而默认成功 | 临时缓冲、文件/句柄全部释放；不覆盖已有快照 |
| 并发读写、并发销毁、回调竞态 | 未声明线程安全时拒绝跨线程共享；受管入口串行或隔离 | 全仓无锁实现；`fnshare.cpp:7-9,24-70` 维护进程级静态回调，未见锁/清空 | 运行核心负责实例隔离、停止顺序和回调注销；销毁后不得回调已卸载 DLL |
| `NL_FREE_LIB_DATA`、IDE 卸载、延迟释放 | 释放库拥有的全局资源并使回调失效 | `edatastructure_dllMain.cpp:134-147` 分支为空；`fnshare.cpp:38-40` 也为空 | 在真实宿主中验证重复卸载、通知后调用、线程退出和 DLL detach；当前为未实现/未验证 |
| 宿主崩溃/强杀 | 重启后不读取裸指针；临时资源可审计回收 | 本库没有持久状态、监督器或崩溃恢复代码 | 交给运行核心的进程/资源治理；支持库不能宣称自身具备恢复能力 |

### 13.6 后续能力命中、缺口与装配裁决

| 分类 | 命中/缺口 | 单链路落点 | 裁决 |
|---|---|---|---|
| 已有能力命中 | `EDATASTRUCTURE_DEF` 多次展开、`LIB_INFO`、`GetNewInf`、`.def` 导出、七类类型元数据 | 数据结构支持库的 ABI 适配层；公共 ABI 规则上收运行核心 | **吸收声明模式；待核实现** |
| 已有能力命中 | `ealloc/efree`、`CloneTextData`、`CloneBinData`、数组格式辅助 | 运行核心的易语言内存适配工具，支持库只能调用公开入口 | **吸收为公共边界线索，不把未调用 helper 当目标能力** |
| 关键缺口 | 七类容器算法、节点复制/销毁、Map 键值存储、游标状态 | 数据结构支持库实现 | **待核/需实现；当前不能装配** |
| 关键缺口 | 统一错误码、失败原因存储、输出写回和失败后状态 | 运行核心定义错误/资源契约，支持库负责领域错误转换 | **待核；`DSGetErrMsg` 只是声明** |
| 关键缺口 | 逻辑快照序列化/反序列化和版本兼容 | 模块库定义 schema，支持库实现转换，运行核心负责边界治理 | **新建候选，未启动** |
| 关键缺口 | 实例线程安全、回调注销、并发销毁、超时/取消 | 运行核心治理；支持库声明线程模型 | **待核；当前无同步证据** |
| 关键缺口 | x86/x64 结构布局、调用约定、导出和易语言实机兼容 | 运行核心 ABI 门 + 支持库构建适配 | **待核；不能以 macOS 静态阅读通过代替** |
| 不应吸收 | `untshare.h` 的默认成功序列化空壳和注释实现 | 不装配为能力，不作为测试通过依据 | **废弃为实现证据** |

**装配计划（仅研究输入，未改生产底座）：**

1. 先冻结 `MDATA_INF`、`LIB_INFO`、`PFN_EXECUTE_CMD`、`GetNewInf`、`MFree/NRS_FREE_VAR` 的 ABI 契约和位宽/编码快照，登记为运行核心依赖。
2. 再为数据结构支持库建立真实内部对象与七类能力的单一 owner，明确每个输入、输出、借用、复制、转移和释放责任；模块库不得绕过支持库。
3. 需要持久化时先由模块库提交 schema/版本/失败契约，再由支持库实现编解码；运行核心只负责长度、校验、临时资源和原子提交。
4. 以空容器、重复键、非法键、复制失败、输出替换、重复释放、卸载回调、并发销毁和宿主强杀建立验证场景；没有真实失败/释放证据不进入活跃装配。
5. 最后才在 Windows + 易语言运行时做实机 ABI/加载/调用验收；x86 与 x64 分开出结果，静态库与 DLL 分开出结果。

### 13.7 L0-L4 验收等级

以下等级是当前核对研究定义的验收门，不是仓库已有测试等级。当前只能给出静态证据，不能把未执行等级标绿：

| 等级 | 验收目标 | 必须有的证据 | 当前状态 |
|---|---|---|---|
| **L0 声明盘点** | 类型、命令、参数、返回类型、ABI 入口和构建矩阵互相对齐 | `EDATASTRUCTURE_DEF` 四处展开一致；七类型索引；`LIB_INFO`/`.def`/`GetNewInf` 路径 | **已完成静态盘点** |
| **L1 实现静态审计** | 区分真实逻辑与生成壳，确认返回值、错误、释放、锁、序列化调用 | `cmdDef.cpp` 函数体扫描；`pRetData` 写回、分配/释放、同步、序列化命中；依赖/源码审计 | **已完成审计；结论为实现证据不足** |
| **L2 构建与 ABI** | Windows VS 工具集下 DLL/静态库均可编译并符合 ABI | x86/x64 Debug/Release 构建；导出仅 `GetNewInf`；`sizeof/offsetof`、CDECL、字符编码、`.fne` 和 `pch.h` 差异报告 | **未执行** |
| **L3 宿主运行集成** | 易语言真实运行时加载并正确调用全部生命周期与核心操作 | 逐类构造/复制/释放；节点属性；链表/栈/队列/树/Map 成功/失败；`pRetData`/引用输出/失败原因；卸载通知 | **未执行；当前空实现不具备通过依据** |
| **L4 破坏性与长期治理** | 证明内存、并发、序列化、ABI 在异常和压力下不泄漏、不竞态、不越界 | Windows 调试堆/ASan 或等价工具；重复释放、坏指针、超限/坏快照、并发读写/销毁、回调竞态、强杀重启、x86/x64 交叉验证 | **未执行** |

### 13.8 后续结论

- **吸收**：本项目最有价值的是易语言支持库 ABI 的声明/装配模式、`EDATASTRUCTURE_DEF` 单一宏展开、七类库定义类型登记，以及 `MDATA_INF` 的所有权边界说明。
- **待核**：所有容器算法、真实构造/析构/复制、错误状态、输出写回、线程模型、回调注销、x86/x64 ABI 和宿主实测。
- **新建候选**：模块库逻辑快照 schema 与编解码；运行核心统一 ABI/内存/线程/超时/崩溃资源治理；两者均未在当前核对启动实现。
- **废弃**：把空命令函数、默认成功的 `CPropertyInfo` 序列化模板、隐藏成员整数元数据或命令注释当作“可运行容器/可序列化/线程安全”证据。

当前核对未修改源码、依赖、配置、测试或 Git；只把上述后续研究结论写入本文件。错绑的 `project_context` 指向华世王镞_v3，未作为 `edatastructure` 证据使用。
