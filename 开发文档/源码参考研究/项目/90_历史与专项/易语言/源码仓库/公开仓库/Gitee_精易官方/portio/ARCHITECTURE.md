# portio 架构档案

> 本文件是 `portio` 仓库根目录唯一的架构事实文档。结论以当前源码、Visual Studio 工程文件和 Git 现场为准；支持库注释中的“应实现”或第三方说明不等于当前代码已经实现。

## 1. 项目定位

`portio` 是一个面向易语言的 Windows 原生支持库工程，目标是以 `.fne` 动态支持库或静态库的形式，向易语言 IDE/运行时登记“端口访问”和“并口设置”命令。

当前仓库更准确的定位是：**易语言支持库接口骨架/模板，已完成元数据登记、入口通知和构建工程配置，但四个端口命令的实际硬件访问逻辑均为空实现**。命令说明宣称依赖第三方 `port95nt.exe`，但当前仓库没有对应头文件、导入库、进程调用、端口读写 API 或并口探测代码，因此不能把端口访问能力标记为已实现。

- 目标使用方：易语言 IDE、易语言编译/运行时、静态编译链。
- 输出形态：动态库项目 `portio`；静态库项目 `portio_static`。
- 运行平台声明：命令元数据声明仅支持 `__OS_WIN`；工程目标为 Windows，使用 Visual C++ 工具链。
- 数据性质：没有数据库、配置文件、网络服务或持久化模型；所有支持库信息和命令元数据均为进程内静态结构。
- 当前边界：仓库只提供支持库契约和空的命令执行函数，不提供可验证的真实端口 I/O。

## 2. 总体架构与真实流程

```text
易语言 IDE / 编译器 / 运行时
        │
        │ 动态加载 portio.fne，查找固定导出 GetNewInf
        ▼
portio_dllMain.cpp
        │
        ├─ GetNewInf()
        │    └─ 返回静态 LIB_INFO
        │         ├─ 支持库身份、版本、GUID、语言、系统要求
        │         ├─ 两个命令类别
        │         ├─ 四个 CMD_INFO 命令描述
        │         ├─ 四个 PFN_EXECUTE_CMD 执行函数指针
        │         ├─ 零个自定义数据类型
        │         └─ 零个常量
        │
        ├─ portio_ProcessNotifyLib_portio()
        │    ├─ NL_GET_CMD_FUNC_NAMES → 返回命令函数名数组（动态构建分支）
        │    ├─ NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名
        │    ├─ NL_GET_DEPENDENT_LIBS → 返回空静态依赖列表
        │    └─ NL_SYS_NOTIFY_FUNCTION → 转发到 elib/fnshare.cpp
        │
        └─ g_cmdInfo_portio_global_var_fun[]
             └─ 指向 portio_cmdDef.cpp 的四个命令函数

portio_cmd_typedef.h
        │ PORTIO_DEF 宏一次定义四条命令的元数据输入
        ├─ portio_cmdInfo.cpp → ARG_INFO + CMD_INFO 数组
        ├─ portio_dllMain.cpp → 执行函数指针数组 + 函数名数组
        └─ include_portio_header.h → 四个命令函数声明

易语言调用某条命令
        │ 传入 PMDATA_INF pRetData、nArgCount、PMDATA_INF pArgInf
        ▼
portio_cmdDef.cpp
        ├─ PortIn：读取端口参数；当前没有端口读取，也没有写返回值
        ├─ PortOut：读取端口和字节参数；当前没有端口写出
        ├─ CheckParallelPort：当前函数体为空，没有探测并口或构造数组
        └─ SetECPMode：读取端口和模式参数；当前没有设置 ECP 模式

elib/fnshare.cpp
        └─ 保存易语言系统通知函数指针，提供 NotifySys / 内存辅助能力

外部 port95nt.exe
        └─ 仅出现在命令说明和支持库说明文本中；当前源码没有实际接入证据
```

### 状态标记

- **已实现**：当前源码中存在可定位的实际控制流、数据构造或接口返回。
- **仅声明**：存在宏、元数据、函数原型、注释或工程配置，但没有对应的真实业务实现。
- **未验证**：代码或工程看起来具备某种意图，但没有在本机目标环境中构建、加载或运行验证。
- **空实现/缺失**：函数体存在但不执行目标动作，或目标路径在仓库中不存在。

## 3. 目录与分层职责

```text
portio/
├── portio.sln                         Visual Studio 解决方案，动态库 + 静态库
├── portio.vcxproj                     动态库工程，目标扩展名 Win32 下为 .fne
├── portio_static/
│   ├── portio_static.vcxproj          静态库工程，复用上级源码
│   ├── portio_static.vcxproj.filters  静态工程的文件筛选器
│   └── portio_static.vcxproj.user     用户工程空配置
├── portio_cmd_typedef.h               四条命令的唯一宏定义源
├── include_portio_header.h             公共头，元数据外部符号与命令声明
├── portio_cmdInfo.cpp                  参数元数据、命令元数据数组
├── portio_cmdDef.cpp                   四个命令执行函数（当前均为空实现）
├── portio_dllMain.cpp                  DLL 入口、LIB_INFO、通知分发、函数指针表
├── portio_const.cpp                    常量表占位，当前数量为 0
├── portio_dtType.cpp                   自定义数据类型表占位，当前数量为 0
├── Source_portio.def                   动态库显式导出 GetNewInf
└── elib/
    ├── lib2.h                          易语言支持库 ABI、类型、元数据和通知契约
    ├── fnshare.h / fnshare.cpp         系统通知、内存、数组/文本辅助与通知状态
    ├── lang.h                           语言版本宏，当前为 GBK
    ├── krnllib.h                        系统核心支持库常量和版本标识
    ├── mtypes.h                         Windows/易语言兼容基础类型定义
    ├── PublicIDEFunctions.h             IDE 功能编号与参数结构
    └── untshare.h                       通用组件辅助代码；本项目端口命令未使用其核心功能
```

### 3.1 命令定义层：`portio_cmd_typedef.h`

`PORTIO_DEF(_MAKE)` 是四条命令的单一描述源。每一行同时提供命令序号、中文名、英文符号、说明、类别、系统标志、返回类型、用户级别、参数数量和参数元数据起点。不同文件传入不同的 `_MAKE`，从而生成不同的表或声明，避免命令数量和顺序分裂。

**已实现**：四条命令的登记输入、顺序和参数描述存在。

**仅声明**：该文件的说明文字说端口操作依赖 `port95nt.exe`，但宏本身不执行任何调用。

### 3.2 元数据层：`portio_cmdInfo.cpp`

动态构建分支（`#if !defined(__E_STATIC_LIB)`）创建：

- `g_argumentInfo_portio_global_var[]`：5 个参数记录；
- `g_cmdInfo_portio_global_var[]`：由 `PORTIO_DEF(PORTIO_DEF_CMDINFO)` 生成的 4 个命令记录；
- `g_cmdInfo_portio_global_var_count`：以数组大小计算命令数。

参数顺序是：

| 命令 | 参数 | 类型 | 状态 |
|---|---|---|---|
| `PortIn` | `端口号` | `SDT_INT` | 已声明，执行函数只读入局部变量 |
| `PortOut` | `端口号` | `SDT_INT` | 已声明，执行函数只读入局部变量 |
| `PortOut` | `欲写出字节` | `SDT_BYTE` | 已声明，执行函数只读入局部变量 |
| `SetECPMode` | `并口端口号` | `SDT_INT` | 已声明，执行函数只读入局部变量 |
| `SetECPMode` | `ECP模式` | `SDT_INT` | 已声明，执行函数只读入局部变量 |

`CheckParallelPort` 的参数数量为 0，返回类型为 `SDT_INT`，并设置 `CT_RETRUN_ARY_TYPE_DATA`，表示返回整数数组；但函数体没有创建或写入数组。

### 3.3 入口与支持库注册层：`portio_dllMain.cpp`

- `DllMain`：仅对四类 DLL 生命周期通知做空分支，最终返回 `TRUE`。它不初始化端口驱动、不加载 `port95nt.exe`、不释放端口资源。
- `g_LibInfo_portio_global_var`：填充易语言支持库注册结构。
- `GetNewInf()`：返回 `&g_LibInfo_portio_global_var`，是 `Source_portio.def` 显式导出的固定入口。
- `g_cmdInfo_portio_global_var_fun[]`：通过 `PORTIO_DEF` 生成四个命令函数指针，顺序必须与 `CMD_INFO` 数组一致。
- `g_cmdNamesportio[]`：动态分支中通过宏生成函数名字符串，供静态编译相关通知使用。
- `portio_ProcessNotifyLib_portio()`：处理易语言系统发送给支持库的通知。

### 3.4 运行时辅助层：`elib/fnshare.*`

`fnshare.cpp` 保持两个进程内状态：系统通知回调 `s_pfnNotifySys`、用户回调 `s_pfnuserNotifySys`，以及调试/运行版本标记 `s_isDebug`。`ProcessNotifyLib()` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时保存系统回调，并调用 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 获取程序类型；之后把通知转发给用户回调（如已设置）。

`fnshare.h` 还提供 `ealloc`、`efree`、`CloneTextData`、`CloneBinData`、`GetAryElementInf`、`GetBinData`、`allocArray` 等支持库辅助函数。它们属于通用支持库模板能力，不等于 `portio` 的端口业务已经使用这些函数。

### 3.5 占位数据层：`portio_const.cpp` 与 `portio_dtType.cpp`

- `g_ConstInfo_portio_global_var[1]` 存在，但 `g_ConstInfo_portio_global_var_count = 0`，因此当前没有可用常量。
- `g_DataType_portio_global_var[1]` 存在，但 `g_DataType_portio_global_var_count = 0`，因此当前没有自定义数据类型。

这两个数组是零数量占位，不应计为已提供的业务数据模型。

## 4. 命令契约与实际执行状态

| 序号 | 易语言命令 | C/C++ 符号 | 返回契约 | 参数契约 | 元数据状态 | 执行状态 |
|---:|---|---|---|---|---|---|
| 0 | `端口读入` | `portio_PortIn_0_portio` | `SDT_BYTE` | `端口号: SDT_INT` | 已实现登记 | 空实现；没有读取端口，也没有设置 `pRetData` |
| 1 | `端口写出` | `portio_PortOut_1_portio` | `_SDT_NULL` | `端口号: SDT_INT`、`欲写出字节: SDT_BYTE` | 已实现登记 | 空实现；没有写出端口 |
| 2 | `查询并口` | `portio_CheckParallelPort_2_portio` | `SDT_INT` + `CT_RETRUN_ARY_TYPE_DATA` | 无 | 已实现登记 | 空实现；没有探测并口，也没有生成数组 |
| 3 | `置ECP模式` | `portio_SetECPMode_3_portio` | `_SDT_NULL` | `并口端口号: SDT_INT`、`ECP模式: SDT_INT` | 已实现登记 | 空实现；没有设置 ECP 模式 |

### 4.1 已确认的函数体事实

- `portio_cmdDef.cpp:5-9`：`PortIn` 只读取 `pArgInf[0].m_int` 到局部变量 `arg1`，函数结束前没有任何 I/O 或返回值写入。
- `portio_cmdDef.cpp:14-19`：`PortOut` 只读取端口号和字节到 `arg1`、`arg2`，没有副作用。
- `portio_cmdDef.cpp:23-26`：`CheckParallelPort` 函数体为空。
- `portio_cmdDef.cpp:31-36`：`SetECPMode` 只读取两个整数到局部变量，没有副作用。

因此当前支持库即使能够成功加载，四条命令也不能据源码证明会访问真实硬件。尤其是 `PortIn` 的声明返回 `SDT_BYTE`，但没有填充 `pRetData`，其运行结果不能按命令说明推断。

## 5. 核心数据模型（进程内 ABI）

本项目没有业务数据库或文件持久化；“数据模型”是易语言支持库 ABI 中的 C/C++ 结构体和静态数组。

### 5.1 支持库注册模型：`LIB_INFO`

`elib/lib2.h:1248-1315` 定义 `LIB_INFO`。本项目在 `portio_dllMain.cpp:31-87` 填入：

- 格式号：`LIB_FORMAT_VER`；
- 固定 GUID：`2F48E8AD71534EB79B5AD580D189231A`；
- 版本：`2.0.0`；
- 易语言系统要求：`3.0`；系统核心支持库要求：`3.0`；
- 名称：`端口访问支持库`；语言：`__GBK_LANG_VER`；
- 操作系统状态：`_LIB_OS(OS_ALL)`，即库级元数据声明 Windows/Linux/Unix；
- 类别数量：2；类别文本：`端口访问`、`并口设置`；
- 命令数量：由 `g_cmdInfo_portio_global_var_count` 计算；
- 命令描述和函数指针：分别指向两个全局数组；
- 自定义数据类型数量：0；常量数量：0；
- 通知回调：`portio_ProcessNotifyLib_portio`；
- 依赖文件文本：`NULL`。

这里存在一个重要的“库级声明与命令级声明”差异：`LIB_INFO` 使用 `OS_ALL`，但四条命令的 `_wState` 均由 `_CMD_OS(__OS_WIN)` 生成，命令实际元数据只声明 Windows。当前代码没有对该差异做额外解释或校验。

### 5.2 命令模型：`CMD_INFO`

`elib/lib2.h:297-364` 定义 `CMD_INFO`，每条命令保存中文名、英文名、说明、类别、状态、返回类型、学习级别、图标范围、参数数量和参数数组指针。`portio_cmdInfo.cpp:33-43` 使用同一个 `PORTIO_DEF` 生成四条记录，命令顺序是 0、1、2、3。

### 5.3 参数模型：`ARG_INFO`

`elib/lib2.h:266-292` 定义 `ARG_INFO`。本仓库参数没有默认值、图标和特殊引用/数组标志，主要有效字段是参数名称、解释和 `m_dtType`。参数数组只有动态库分支定义，静态库工程通过 `__E_STATIC_LIB` 关闭编辑元数据。

### 5.4 调用数据模型：`MDATA_INF`

`elib/lib2.h:800-824` 定义 `MDATA_INF`。每个命令函数接收：

- `pRetData`：返回值描述和数据存放位置；
- `nArgCount`：实际参数数量；
- `pArgInf`：连续的输入参数描述数组。

联合体根据 `m_dtDataType` 选择 `m_int`、`m_byte`、文本、字节集、数组或复合数据指针。`portio_cmdDef.cpp` 当前只从输入联合体读取 `m_int`/`m_byte`，没有对返回联合体做任何写入。

### 5.5 并口返回数组的声明模型

`CheckParallelPort` 的说明文本规定结果为每个并口三个整数一组：端口地址、并口类型、ECP 模式；`portio_cmd_typedef.h:15` 以 `CT_RETRUN_ARY_TYPE_DATA` 声明整数数组返回。`elib/fnshare.h:160-169` 的 `allocArray` 和 `107-125` 的 `GetAryElementInf` 提供易语言数组格式辅助，但当前 `portio_cmdDef.cpp` 没有调用它们，所以该返回格式只有契约声明，没有实现证据。

## 6. 接口与边界

### 6.1 动态库入口

| 接口 | 位置 | 作用 | 状态 |
|---|---|---|---|
| `GetNewInf()` | `portio_dllMain.cpp:89-92` | 返回 `PLIB_INFO` | 已实现 |
| `GetNewInf` 导出 | `Source_portio.def:1-4` | 为加载器提供固定符号 | 工程声明；未在本机 Windows 链接验证 |
| `portio_ProcessNotifyLib_portio()` | `portio_dllMain.cpp:101-178` | 处理库通知 | 已实现基础分发，业务通知分支多为空 |

### 6.2 通知接口

`elib/lib2.h:1152-1180` 定义通知编号，当前实现行为如下：

| 通知 | 当前行为 | 状态 |
|---|---|---|
| `NL_GET_CMD_FUNC_NAMES` | 动态分支返回 `g_cmdNamesportio` | 已实现于非静态分支 |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 动态分支返回文本 `portio_ProcessNotifyLib_portio` | 已实现于非静态分支 |
| `NL_GET_DEPENDENT_LIBS` | 动态分支返回 `"\\0\\0"` | 已实现，表示无额外静态库文本依赖 |
| `NL_SYS_NOTIFY_FUNCTION` | 转发到 `ProcessNotifyLib`，保存系统回调并查询程序类型 | 已实现基础转发 |
| `NL_FREE_LIB_DATA` | 空分支 | 仅声明生命周期边界，无资源释放逻辑 |
| `NL_UNLOAD_FROM_IDE` | 空分支 | 仅声明通知，不做清理 |
| `NR_DELAY_FREE` | 空分支，保持初始 `NR_OK` | 未实现延迟释放策略 |
| `NL_IDE_READY` | 空分支 | 未实现 IDE 就绪动作 |
| `NL_RIGHT_POPUP_MENU_SHOW` | 空分支 | 未实现 IDE 菜单动作 |
| `NL_ADD_NEW_ELEMENT` | 空分支 | 未实现 IDE 新成员插入 |
| 未知编号 | 返回 `NR_ERR` | 已实现 |

### 6.3 静态库边界

`portio_static/portio_static.vcxproj` 将上级目录的同一批 `.cpp/.h` 纳入静态库工程，并在 Win32 Debug/Release 配置定义 `__E_STATIC_LIB`。该宏使 `include_portio_header.h` 不声明动态元数据外部符号，并使部分动态注册信息被排除。

但工程存在未验证的配置差异：

- 静态工程的 x64 Debug/Release 预处理器定义只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有 Win32 配置中的 `__E_STATIC_LIB`；
- 静态工程的 x64 配置使用 `PrecompiledHeader=Use`，仓库中没有 `pch.h`；
- 动态工程只有 Win32 配置明确引用 `Source_portio.def`，x64 配置没有 `ModuleDefinitionFile`；
- 动态工程 x64 配置没有 `TargetExt=.fne`，Win32 才显式设置该扩展名。

这些是工程文件中可直接定位的事实，是否导致具体构建/导出问题需要 Windows + Visual Studio 实际构建才能确认。

## 7. 依赖与运行环境

### 7.1 编译期依赖

- Visual Studio C++ 工程格式：`portio.sln`、`portio.vcxproj`、`portio_static/portio_static.vcxproj`。
- 工具集：`v141`。
- Windows SDK 目标版本：`10.0.15063.0`。
- 字符集：`Unicode`，但支持库语言宏为 `__GBK_LANG_VER`，命令文本源码以 GB18030/兼容编码保存。
- 头文件依赖：`windows.h`、CRT 头和 `elib` 内的支持库 ABI 定义；`portio.vcxproj` 没有额外包含目录。
- 运行库：Win32 Debug 使用 `MultiThreadedDebug`，Win32 Release 使用 `MultiThreaded`；x64 同样配置为静态运行库。
- 编译模式：动态库 `DynamicLibrary`；静态库 `StaticLibrary`。

### 7.2 运行期依赖声明与实际证据

支持库说明和四条端口命令说明均要求目标机安装第三方 `port95nt.exe`（见 `portio_dllMain.cpp:44-47`、`portio_cmd_typedef.h:13-16`）。但仓库内：

- 没有 `port95nt.exe` 文件；
- 没有 `port95nt` 头文件、导入库或动态加载代码；
- 没有 `_inp`、`_outp`、`ReadFile`、`DeviceIoControl` 等端口访问实现；
- 没有并口枚举、ECP 模式设置或驱动错误处理代码；
- `m_szzDependFiles` 为 `NULL`，通知返回的静态依赖文本为空。

因此 `port95nt.exe` 是**文本层面的运行前提声明**，不是当前仓库已接入的可验证依赖。

## 8. 构建配置审计（仅读取工程，未执行构建）

| 工程 | 配置 | 输出类型 | 关键设置 | 证据 |
|---|---|---|---|---|
| `portio` | Debug/Release Win32 | 动态库 | `v141`、Unicode、Win32、`.fne`、引用 `Source_portio.def` | `portio.vcxproj:51-63,95-158` |
| `portio` | Debug/Release x64 | 动态库 | `v141`、Unicode、未配置 `.fne` 与 `.def` | `portio.vcxproj:64-75,159-198` |
| `portio_static` | Debug/Release Win32 | 静态库 | `__E_STATIC_LIB`、`_LIB`、多处理器编译 | `portio_static/portio_static.vcxproj:48-59,92-129` |
| `portio_static` | Debug/Release x64 | 静态库 | `Use` 预编译头，但未见 `pch.h`；未定义 `__E_STATIC_LIB` | `portio_static/portio_static.vcxproj:61-72,130-163` |

解决方案声明四种组合：`Debug|x86`、`Release|x86`、`Debug|x64`、`Release|x64`，并将 x86 映射到 Visual Studio 的 `Win32` 平台（`portio.sln:10-32`）。

## 9. 测试、验证与当前证据等级

### 9.1 仓库内测试现状

- Git 文件清单中没有测试目录、测试源文件、测试工程或测试脚本。
- 没有 `README.md`、许可证文件、持续集成配置或发布脚本。
- 没有样例易语言工程，也没有端口硬件模拟器。
- `portio.vcxproj.user` 与 `portio_static/portio_static.vcxproj.user` 只有空的用户属性组。

### 9.2 当前取证实际执行的验证

当前取证只做只读取证，没有安装依赖、没有启动服务、没有生成构建产物，也没有修改源码、工程、依赖、测试、配置或 Git 历史。已完成：

1. 读取 `portio.sln`、两个 `.vcxproj`、两个 `.filters`、两个 `.user` 和 `Source_portio.def`；
2. 读取 `portio_cmd_typedef.h`、`include_portio_header.h`、四个核心 `.cpp`；
3. 读取 `elib` 中的 ABI、通知、数据和辅助头文件；
4. 读取 Git 分支、远程、HEAD、提交时间、提交历史和远程引用；
5. 搜索端口实现、`port95nt`、TODO、测试和既有 `既有专项文档`。

未执行且不能宣称通过：

- Visual Studio/`MSBuild` Windows 构建；
- `.fne` 加载与 `GetNewInf` 运行验证；
- 四条易语言命令的真实调用；
- `port95nt.exe` 安装后硬件访问；
- x86/x64 动态导出检查；
- 静态库链接和静态编译链验证。

### 9.3 当前结论

| 能力 | 结论 | 证据等级 |
|---|---|---|
| 支持库元数据登记 | 已实现静态结构和返回入口 | 源码已证，未构建加载 |
| 四条命令名称/参数/返回契约 | 已登记 | 源码已证 |
| 动态通知基础分发 | 已实现部分分支 | 源码已证，未运行 |
| 系统通知回调保存 | 已实现 | 源码已证，未运行 |
| 端口读入 | 未实现 | 命令函数体为空 |
| 端口写出 | 未实现 | 命令函数体为空 |
| 并口查询 | 未实现 | 命令函数体为空 |
| ECP 模式设置 | 未实现 | 命令函数体为空 |
| `port95nt.exe` 接入 | 仅声明 | 只有文本说明 |
| 动态 `.fne` 导出 | Win32 工程声明；运行未验证 | `.def` 与工程配置 |
| x64 构建/导出 | 未验证，存在配置风险 | 工程配置差异 |

## 10. 风险、缺口与后续复核点

1. **核心功能缺失**：四个执行函数都是空实现，支持库当前不能提供端口访问业务。后续若要实现，必须补齐端口驱动/访问适配、返回值写入、错误路径和资源释放，并用 Windows 隔离环境验证。
2. **外部依赖只是说明**：`port95nt.exe` 没有被工程或代码实际引用。应明确由目标机预装、由支持库加载，还是改为其他驱动/接口；在决策前不能将其写成已接入依赖。
3. **返回数据未填充**：`PortIn` 没有设置 `pRetData`，`CheckParallelPort` 没有创建数组。元数据契约与执行代码不闭合。
4. **动态 x64 导出风险**：`Source_portio.def` 只在 Win32 工程配置中作为模块定义文件使用；x64 Link 配置没有该项，而 `GetNewInf` 也没有 `__declspec(dllexport)` 证据。必须在 Windows 上检查最终导出表。
5. **静态 x64 配置风险**：静态 x64 没有 `__E_STATIC_LIB`，且要求使用缺失的 `pch.h`。应先确认这是工程模板错误还是外部属性表提供了补充定义。
6. **库级操作系统声明不一致**：`LIB_INFO` 写入 `OS_ALL`，命令状态只写 Windows。需要在目标易语言 ABI 规则下确认这是有意的库级兼容声明还是应收窄。
7. **无测试与样例**：没有自动化回归、硬件模拟、加载探针或 ABI 断言。任何后续实现都应至少增加隔离的参数/返回值测试、导出检查和无硬件失败路径验证，但当前取证不修改测试目录。
8. **浅克隆限制**：当前仓库只有一个根提交，Git 日志显示 `(grafted)`；不能据此推断完整历史、旧版本行为或上游长期维护状态。

## 11. Git 基线与证据路径

### 11.1 Git 现场基线

- 本地仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/portio`
- 远程：`https://gitee.com/JYtechnology/portio.git`
- 当前分支：`master`
- 当前 HEAD：`26f987d14bd7247efc69bc354047479e10dab8b1`
- HEAD 提交时间：`2022-12-19T16:56:54+08:00`
- HEAD 提交说明：`初始化仓库`
- `origin/master`：与本地 HEAD 相同（远程引用查询结果为 `26f987d14bd7247efc69bc354047479e10dab8b1`）。
- 分支/标签：现场只有 `master` 和对应的 `origin/master`，没有标签。
- 仓库形态：浅克隆/移植历史（`git log` 标记为 `grafted`），历史完整性未验证。
- 文档材料：建档前工作树干净；当前取证未发现已有 `ARCHITECTURE.md` 或 `既有专项文档`，因此不存在既有细探材料可吸收或删除。本文件是当前取证唯一新增文件。

### 11.2 关键证据索引

| 证据 | 路径与行号 |
|---|---|
| 解决方案项目和平台矩阵 | `portio.sln:5-38` |
| 动态库源文件/头文件清单 | `portio.vcxproj:21-48` |
| 动态库配置、工具集、目标扩展名、`.def` | `portio.vcxproj:51-76,95-158,159-198` |
| 静态库复用源码和配置 | `portio_static/portio_static.vcxproj:21-45,48-73,92-163` |
| 显式动态导出 | `Source_portio.def:1-4` |
| 公共符号和命令声明宏 | `include_portio_header.h:1-26` |
| 四条命令定义与说明 | `portio_cmd_typedef.h:1-17` |
| 四个空/半空命令函数 | `portio_cmdDef.cpp:1-37` |
| 参数和命令元数据表 | `portio_cmdInfo.cpp:1-46` |
| 零常量/零自定义类型 | `portio_const.cpp:12-18`、`portio_dtType.cpp:3-10` |
| DLL 入口、LIB_INFO、通知分发 | `portio_dllMain.cpp:1-178` |
| 系统通知状态与转发 | `elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-55` |
| ABI 数据类型和命令结构 | `elib/lib2.h:243-364,700-748,800-824` |
| LIB_INFO 与固定入口契约 | `elib/lib2.h:1229-1318` |
| 通知编号 | `elib/lib2.h:1152-1180` |
| 易语言数组/内存辅助 | `elib/fnshare.h:25-169` |
| 语言、核心库和兼容类型 | `elib/lang.h:1-18`、`elib/krnllib.h:1-133`、`elib/mtypes.h:1-176` |
| IDE 功能编号/结构定义 | `elib/PublicIDEFunctions.h:1-493` |

## 12. 后续轮次边界

本文件已完成当前全量架构建档。后续如继续研究，只能在本文件内增量补证，不另建平行事实源：

- 补充取证：在 Windows 隔离环境中沿 `GetNewInf`、通知回调和命令函数做真实加载/调用取证，补返回值、错误码和资源释放；
- 扩展取证：核查 `port95nt.exe` 或替代驱动的真实接口、权限、并发、故障恢复和硬件安全边界；
- 后续核查：分别验证 Win32/x64 动态导出、静态链接、易语言 IDE 登记和版本兼容；
- 后续核查：如有跨项目共性，只将裁决写入源码参考库的 `00_catalog/` 专题文档，单仓事实仍保留在本文件。

以上后续事项均是待核查内容，不代表当前仓库已经实现或通过验证。

## 13. 小型仓规模说明与边界

本仓库由 23 个跟踪文件组成，属于端口 I/O 支持库的元数据模板；没有端口驱动源码、测试程序或硬件模拟器。关键文件责任如下：

- `portio_cmdDef.cpp`、`portio_cmdInfo.cpp`：命令名、参数和处理器登记。
- `portio_cmd_typedef.h`：函数指针和宿主参数 ABI；任何整数宽度变化都可能破坏调用。
- `portio_dtType.cpp`、`portio_const.cpp`：类型与常量登记，不能替代真实端口访问实现。
- `portio_dllMain.cpp`：DLL 导出、`GetNewInf`、通知函数和库信息。
- `include_portio_header.h`：公共声明；`Source_portio.def`：导出表。
- `portio.vcxproj` 与 `portio_static/portio_static.vcxproj`：动态/静态构建配置。
- `elib/*`：宿主内存、通知和通用结构定义。

没有 `tests/`、驱动二进制、安装脚本或运行时配置。macOS 环境不能验证 `port95nt`、管理员权限、I/O 指令异常、并发访问、超时和卸载释放；文档低于 500 行是由仓库规模和证据边界决定，而非遗漏源码。
