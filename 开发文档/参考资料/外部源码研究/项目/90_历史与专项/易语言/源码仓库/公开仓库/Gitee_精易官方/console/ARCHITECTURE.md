# console 架构归档

> 首轮全量架构建档。本文是本项目唯一架构事实文档；后续细探、源码回读和版本复核只更新本文件。
> 归档边界：只读取真实源码、工程文件、Git 元数据和本地旧细探索引；未修改源码、未构建、未安装依赖、未启动 DLL、未提交 Git。

## 1. 项目定位

`console` 是精易官方 Gitee 仓库中的易语言“控制台操作支持库”源码。它不是独立的命令行程序，也不是 HTTP/API 服务，而是面向易语言运行时/IDE 的 Windows 支持库插件：

- 动态库形态由 `console.vcxproj` 产出，模块扩展名配置为 `.fne`（Win32 配置）；
- 静态库形态由 `console_static/console_static.vcxproj` 产出，复用同一组命令实现源码；
- 通过 `GetNewInf` 返回 `LIB_INFO`，向易语言注册库版本、名称、支持系统、数据类型、命令元数据、命令函数表和系统通知回调；
- 对外能力模型是“控制台对象 + 控制台颜色枚举 + 12 个对象命令”；
- 当前仓库中的命令函数主体基本是生成模板/占位实现：读取参数后没有调用 Windows Console API，也没有向返回槽写入结果。因此源码描述的是支持库 ABI 和命令目录，不能据此宣称控制台功能已经可运行。

## 2. 总体流程图

```text
易语言 IDE/运行时
    │
    ├─ 动态加载 console.fne
    │      │
    │      ├─ GetNewInf()
    │      │     └─ LIB_INFO
    │      │          ├─ 库元信息：GUID/版本/系统/语言/作者
    │      │          ├─ 自定义数据类型：控制台对象、控制台颜色
    │      │          ├─ CMD_INFO[]：12 条命令的名称/说明/参数/返回类型
    │      │          ├─ PFN_EXECUTE_CMD[]：12 个命令实现函数
    │      │          └─ PFN_NOTIFY_LIB：console_ProcessNotifyLib_console
    │      │
    │      ├─ 易语言传入 NL_SYS_NOTIFY_FUNCTION
    │      │      └─ ProcessNotifyLib()
    │      │           ├─ 保存系统通知函数指针 s_pfnNotifySys
    │      │           ├─ 首次调用 NRS_GET_PRG_TYPE 获取调试/编译状态
    │      │           └─ 可转发用户通知 s_pfnuserNotifySys
    │      │
    │      └─ 用户调用对象命令
    │             └─ console_cmdDef.cpp 的 PFN_EXECUTE_CMD ABI
    │                  ├─ 当前实现：读取 pArgInf 参数
    │                  └─ 当前实现：未执行控制台操作/未填充返回值
    │
    └─ 静态编译路径
           └─ console_static 工程复用同一组 .cpp/.h
                └─ 以 __E_STATIC_LIB 区分 DLL 元数据和静态链接辅助路径
```

## 3. 工程与目录地图

现场工作树（排除 `.git`）共 23 个文件；无 README、无测试目录、无 CI 配置、无构建脚本（仅 Visual Studio 工程）。

```text
console/
├── console.sln                         # VS solution，console + console_static
├── console.vcxproj                     # DynamicLibrary，4 配置：Debug/Release × Win32/x64
├── console.vcxproj.filters             # VS 源/头文件筛选器
├── console.vcxproj.user                # 空用户属性
├── console_static/
│   ├── console_static.vcxproj          # StaticLibrary，复用上级源码
│   ├── console_static.vcxproj.filters
│   └── console_static.vcxproj.user     # 空用户属性
├── Source_console.def                  # DLL 导出表，仅 GetNewInf
├── include_console_header.h            # 本库公共汇总头；声明元数据及命令
├── console_cmd_typedef.h               # CONSOLE_DEF 命令单一清单、名称拼接宏
├── console_cmdDef.cpp                  # 12 个命令的执行函数（当前为空壳）
├── console_cmdInfo.cpp                 # 参数表和 CMD_INFO[]
├── console_const.cpp                   # 常量表（当前 0 项）
├── console_dtType.cpp                  # 自定义数据类型、对象方法索引、颜色枚举
├── console_dllMain.cpp                 # DllMain、LIB_INFO、导出函数、通知处理
└── elib/
    ├── lib2.h                          # 易语言支持库 ABI/数据/命令/通知基础定义
    ├── mtypes.h                        # Windows/基础类型兼容定义
    ├── lang.h                          # 语言编码版本常量（GBK 等）
    ├── krnllib.h                       # 系统核心支持库常量与类型类别
    ├── fnshare.h/.cpp                  # 通知、内存、文本/字节集/数组辅助函数
    ├── untshare.h                      # 单元/窗口/字体/属性事件辅助宏与接口
    └── PublicIDEFunctions.h            # IDE Add-in 通知功能编号和参数结构
```

### 3.1 工程文件声明的编译单元

两个工程均编译以下 6 个 `.cpp`（静态工程用 `..\` 引用）：

- `elib/fnshare.cpp`
- `console_cmdDef.cpp`
- `console_const.cpp`
- `console_dllMain.cpp`
- `console_dtType.cpp`
- `console_cmdInfo.cpp`

两个工程均引用本项目头文件和 `elib` 头文件。没有第三方包清单、NuGet、vcpkg、CMake、Makefile 或脚本化依赖锁。

## 4. 分层与职责

### 4.1 支持库 ABI 层：`elib/`

`elib/lib2.h` 是本项目最重要的外部契约：

- 定义 `DATA_TYPE`、`MDATA_INF/PMDATA_INF`、`ARG_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_CONST_INFO`、`LIB_INFO` 等结构；
- 定义 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)` 命令调用 ABI；
- 定义 `PFN_NOTIFY_LIB` 和 `PFN_NOTIFY_SYS` 通知函数指针；
- 定义系统数据类型 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT` 等以及命令状态/隐藏/构造/析构标志；
- 定义 `NL_*` 库通知、`NRS_*` 系统通知和 `FUNCNAME_GET_LIB_INFO = "GetNewInf"`。

`elib/mtypes.h` 提供 `INT`、`BOOL`、`DWORD`、`LPSTR`、`PINT`、`HWND` 等 Windows/基础类型别名。它不是完整 Windows SDK 的替代品，`lib2.h`/`untshare.h` 仍依赖 Windows API 常量和函数声明。

### 4.2 支持库共享辅助层：`elib/fnshare.cpp/.h`

已实现的共享辅助行为：

- `NotifySys`：调用易语言系统传入的 `PFN_NOTIFY_SYS`；
- `isDebugVer`：读取 `s_isDebug`，判断是否为 `PT_DEBUG_RUN_VER`；
- `ProcessNotifyLib`：处理系统通知、保存系统通知函数、首次读取程序类型、转发用户通知；
- `SetUserSysNotify`：设置用户通知回调并返回 `ProcessNotifyLib`；
- `ealloc/efree`：通过 `NRS_MALLOC/NRS_MFREE` 使用易语言内存管理；
- `CloneTextData`、`CloneBinData`、`CloneTextDataW`、`GetBinData`、`allocArray` 等内联数据辅助。

`console` 只把 `ProcessNotifyLib` 作为其库通知实现的内部转发基础；没有自己的持久化状态、配置文件、网络客户端或线程系统。

### 4.3 本库声明层：`include_console_header.h` 与 `console_cmd_typedef.h`

`include_console_header.h`：

- 引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和本库命令清单；
- 声明全局常量、命令信息、命令函数、参数信息、数据类型数组；
- 用 `CONSOLE_DEF_CMD` 对 `CONSOLE_DEF` 展开，生成 12 个命令函数声明。

`console_cmd_typedef.h`：

- `CONSOLE_NAME` 把库名、英文命令名和索引拼接成符号，如 `console_InPut_3_console`；
- `CONSOLE_NAME_STR` 为静态编译生成字符串形式的函数名；
- `CONSOLE_DEF(_MAKE)` 是命令单一来源。命令元数据、执行函数指针、静态命令名和 `CMD_INFO[]` 均从此宏清单展开，避免各表独立维护命令序号。

### 4.4 元数据层：`console_cmdInfo.cpp`、`console_dtType.cpp`、`console_const.cpp`

- `console_cmdInfo.cpp`：27 个参数条目（索引 000–026）和 `g_cmdInfo_console_global_var[]`；动态库条件下编译，Debug 下用 `dbg_cmd_arg_count__` 检查参数表长度。
- `console_dtType.cpp`：
  - `控制台对象 / Console`：命令索引 0–11；一个隐藏的 `SDT_INT` 成员 `控制台句柄 / ConsoleHandle`；Windows 平台标志；
  - `控制台颜色 / ConsoleColor`：枚举数据类型，16 个 `SDT_INT` 成员，值 1–16，对应黑色、红褐、墨绿、褐绿、藏青、紫红、深青、银白、灰色、红色、绿色、黄色、蓝色、品红、艳青、白色；
  - 全局自定义数据类型计数为 2。
- `console_const.cpp`：`g_ConstInfo_console_global_var` 仅分配 1 个占位数组，实际常量数 `g_ConstInfo_console_global_var_count = 0`。

## 5. 命令/API 契约

### 5.1 动态库入口

`Source_console.def` 的 DLL 导出表只有：

```text
LIBRARY
EXPORTS
    GetNewInf
```

`console_dllMain.cpp` 的 `GetNewInf()` 返回静态 `g_LibInfo_console_global_var` 地址。元数据基线如下：

| 字段 | 真实值 |
|---|---|
| 库名/解释 | `控制台操作支持库` |
| GUID | `1E86AA0150514527BB567CD22F3733C8` |
| 库版本 | `2.0.1`（主/次/构建） |
| 所需易语言系统 | `3.6` |
| 所需系统核心支持库 | `3.6` |
| 语言 | `__GBK_LANG_VER` |
| 操作系统 | `_LIB_OS(OS_ALL)` |
| 数据类型数 | 2 |
| 全局命令类别数 | 0 |
| 命令数 | `g_cmdInfo_console_global_var_count`，由 `CONSOLE_DEF` 展开为 12 |
| 系统通知函数 | `console_ProcessNotifyLib_console` |
| 常量数 | 0 |
| 依赖文件 | `NULL` |

`DllMain` 的四个生命周期分支（`DLL_PROCESS_ATTACH/DETACH`、`DLL_THREAD_ATTACH/DETACH`）均为空，仅返回 `TRUE`。

### 5.2 12 个对象命令

| 索引 | 中文名 | 英文名/实现符号 | 返回 | 参数概要 | 当前实现状态 |
|---:|---|---|---|---|---|
| 0 | 构造 | `construct` / `console_construct_0_console` | `_SDT_NULL` | 无；隐藏构造命令 | 空函数 |
| 1 | 析构 | `free` / `console_free_1_console` | `_SDT_NULL` | 无；隐藏析构命令 | 空函数 |
| 2 | 清屏 | `Clear` / `console_Clear_2_console` | `_SDT_NULL` | 无 | 空函数 |
| 3 | 输入 | `InPut` / `console_InPut_3_console` | `SDT_TEXT` | 横坐标、纵坐标、保存当前光标、是否回显、回显数据、回车结束、最大接收长度 | 仅读取 7 个 `pArgInf` 槽位，不写返回值 |
| 4 | 输出 | `OutPut` / `console_OutPut_4_console` | `SDT_BOOL` | 横坐标、纵坐标、保存当前光标、前景颜色、背景颜色、输出数据 | 仅读取 6 个 `pArgInf` 槽位，不写返回值 |
| 5 | 置光标位置 | `SetCursorPosition` / `console_SetCursorPosition_5_console` | `SDT_BOOL` | 横坐标、纵坐标 | 仅读取参数，不写返回值 |
| 6 | 取光标位置 | `GetCursorPosition` / `console_GetCursorPosition_6_console` | `SDT_BOOL` | `&横坐标`、`&纵坐标`，读取 `m_pInt` | 仅取得引用指针，不写引用/返回值 |
| 7 | 取显示区大小 | `GetScreenSize` / `console_GetScreenSize_7_console` | `_SDT_NULL` | `&宽度`、`&高度` | 仅取得引用指针，不写引用 |
| 8 | 显示光标 | `ShowCursor` / `console_ShowCursor_8_console` | `SDT_BOOL` | 无 | 空函数 |
| 9 | 隐藏光标 | `HideCursor` / `console_HideCursor_9_console` | `SDT_BOOL` | 无 | 空函数 |
| 10 | 填充背景颜色 | `FillBackColor` / `console_FillBackColor_10_console` | `SDT_INT` | 横坐标、纵坐标、背景颜色、填充长度 | 仅读取参数，不写返回值 |
| 11 | 填充字符 | `FillChar` / `console_FillChar_11_console` | `SDT_INT` | 横坐标、纵坐标、填充字符、填充长度 | 仅读取参数，不写返回值 |

调用函数统一使用：

```cpp
void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

输入数据通过 `MDATA_INF` 联合体的 `m_int`、`m_bool`、`m_pText` 或引用指针成员读取；真实实现应按 `pRetData` 的返回类型写回，并按 `elib` 的内存约定分配/释放文本和字节集。

### 5.3 通知边界

`console_ProcessNotifyLib_console` 在 `console_dllMain.cpp` 中处理：

- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib`，把 `dwParam1` 保存为系统通知函数，并在首次通知时调用 `NRS_GET_PRG_TYPE`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前分支为空；
- 未知消息：返回 `NR_ERR`；其他路径默认返回 `NR_OK`；
- `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`：动态库分支返回静态编译辅助所需的命令名、通知函数名和空依赖串；
- `NL_SYS_NOTIFY_FUNCTION` 最终还会由 `fnshare.cpp` 中用户回调 `s_pfnuserNotifySys` 接收（若已设置）。

## 6. 数据模型、状态与持久化

本项目没有业务数据库、配置文件、缓存、日志、消息队列、网络协议或磁盘状态。运行时状态只有进程内静态变量：

- `g_LibInfo_console_global_var` 及其指向的命令/类型/常量静态数组；
- `s_pfnNotifySys`：易语言系统通知函数指针；
- `s_pfnuserNotifySys`：用户注册的通知函数指针；
- `s_isDebug`：初始化时通过 `NRS_GET_PRG_TYPE` 更新的版本/调试状态。

`控制台句柄` 只是易语言对象成员元数据，源码没有创建、关闭或保存句柄的实现。因而“控制台句柄生命周期”“输入缓冲”“光标状态”“颜色状态”目前均未落地为可验证的状态机。

## 7. 真实调用链与实现缺口

### 7.1 加载与注册

```text
LoadLibrary(console.fne)
  → 解析导出 GetNewInf
  → GetNewInf()
  → LIB_INFO
      → g_DataType_console_global_var[2]
      → g_cmdInfo_console_global_var[12]
      → g_cmdInfo_console_global_var_fun[12]
      → console_ProcessNotifyLib_console
  → 易语言按 CMD_INFO/数据类型把命令挂载到“控制台对象”
```

### 7.2 命令执行

```text
易语言命令调用
  → 从 CMD_INFO 确认参数/返回类型
  → 取对应 g_cmdInfo_console_global_var_fun[index]
  → console_*_N_console(pRetData, nArgCount, pArgInf)
  → 当前源码仅做局部参数读取
  → 没有调用 ReadConsole/WriteConsole/FillConsoleOutput*/SetConsoleCursor*
  → 没有写 pRetData 或引用参数
```

这里的“没有调用”是基于当前 6 个本地实现 `.cpp` 的真实源码检索结论；不是说外部 `elib` 不能提供其他能力。

### 7.3 通知初始化

```text
宿主发送 NL_SYS_NOTIFY_FUNCTION
  → console_ProcessNotifyLib_console
  → ProcessNotifyLib
      → s_pfnNotifySys = (PFN_NOTIFY_SYS)dwParam1
      → 若 s_isDebug 初始值仍为 1253600
          → NotifySys(NRS_GET_PRG_TYPE, 0, 0)
          → 更新 s_isDebug
      → 若 s_pfnuserNotifySys 非空，转发相同通知
```

## 8. 技术栈、构建配置与依赖边界

### 8.1 已确认技术栈

- C/C++ 源码，Visual Studio MSBuild 工程；
- `console.sln` 格式 12.00，Visual Studio 17 元数据；
- Platform Toolset `v141`；
- Windows SDK `10.0.15063.0`；
- `CharacterSet=Unicode`，但支持库 ABI/文本元数据大量使用 `LPCSTR/LPSTR`，语言标志为 GBK；
- Win32 与 x64；Debug 使用多线程调试运行库，Release 使用多线程运行库；
- 主工程配置类型 `DynamicLibrary`；静态工程配置类型 `StaticLibrary`；
- 无外部包管理依赖。外部边界主要是 Windows SDK、易语言运行时/IDE ABI 和系统核心支持库 ABI。

### 8.2 工程基线与风险

- `console.sln` 的 `Debug|x86/Release|x86` 映射到主工程的 `Win32`，x64 映射到 x64。
- 主 DLL 工程只在 Win32 的 `Link` 条件组显式设置 `ModuleDefinitionFile=Source_console.def`；x64 条件组未看到该设置。由于 `GetNewInf` 没有源码级 `__declspec(dllexport)`，x64 DLL 导出是否成立需在 Windows/MSBuild 上实测，当前不能宣称成立。
- `.fne` 的 `TargetExt` 只出现在主工程 Win32 条件组；x64 输出扩展名未明确配置。
- 静态工程 Win32 Debug/Release 显式定义 `__E_STATIC_LIB;__E_FNENAME=console`；静态工程 x64 条件组未显式定义 `__E_FNENAME=console`，且启用了 `PrecompiledHeader=Use`，与 Win32 的 `NotUsing` 不一致。x64 静态构建可行性需在 Visual Studio 环境验证。
- `console_cmdInfo.cpp`、`console_const.cpp`、`console_dllMain.cpp` 的部分数据受 `__E_STATIC_LIB` 条件编译控制；动态和静态模式的元数据发现机制不完全相同，不能只看 DLL 路径推断静态编译行为。

## 9. 测试、验证与发布

### 9.1 现场发现

- 项目内无 `test/`、`tests/`、`测试/`、CI workflow、CTest、GoogleTest、单元测试或集成测试文件；
- 无 README 或开发文档；
- `.vcxproj.user` 只有空 `PropertyGroup`，没有可复现的调试命令；
- Git 是浅克隆，当前可见历史只有初始化提交；
- 没有在当前核对执行构建，因为当前宿主为 macOS，项目依赖 Visual Studio/MSVC/Windows SDK，且任务明确禁止构建。

### 9.2 可执行验证命令（未执行）

应在 Windows + Visual Studio 2017/兼容工具链环境执行：

```text
msbuild console.sln /p:Configuration=Debug /p:Platform=x86
msbuild console.sln /p:Configuration=Release /p:Platform=x86
msbuild console.sln /p:Configuration=Debug /p:Platform=x64
msbuild console.sln /p:Configuration=Release /p:Platform=x64
```

验证重点不是只有编译成功，还包括：

1. DLL 是否确实导出 `GetNewInf`；
2. 动态加载器能否解析 `LIB_INFO`，并看到 2 个数据类型、12 个命令；
3. `CMD_INFO` 参数起始索引与 `console_cmdInfo.cpp` 的 27 项参数表是否一致；
4. 静态工程能否解析 12 个命令实现名；
5. 各命令是否真正操作 Windows Console，并正确填充返回值/引用参数；
6. `NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、卸载路径是否无资源泄漏或悬挂回调。

## 10. 未确认项、风险与后续复核点

### 阻断级（若目标是可运行支持库）

1. **12 个命令没有功能实现**：`console_cmdDef.cpp` 只读取参数，未调用 Windows Console API，未写返回值。当前仓库更接近 ABI/元数据骨架，不是完成的控制台操作库。
2. **无测试或宿主冒烟**：没有验证加载、命令注册、通知生命周期、返回值和控制台副作用的测试。
3. **x64 DLL 导出未确认**：主工程 x64 条件没有显式 `Source_console.def`，而 `GetNewInf` 无源码导出属性。

### 重要风险

1. `OutPut` 的元数据返回 `SDT_BOOL`，`InPut` 返回 `SDT_TEXT`，但实现没有初始化 `pRetData`；调用方可能获得未定义/默认数据。
2. `GetCursorPosition`、`GetScreenSize` 取得 `m_pInt` 引用指针但不写回；即使未来调用 WinAPI，也必须处理空指针、坐标边界和返回状态。
3. `控制台句柄` 的元数据标记为隐藏成员，但构造/析构为空，句柄所有权、共享、失效和线程安全均未定义。
4. `elib` 文件头声明“仅授权第三方开发易语言支持库，禁止其他用途”；后续复用时需保留许可边界并核实授权范围。
5. 源码文件为 CRLF，中文源码/元数据为 GBK/扩展 ASCII 风格；跨平台编辑、编码转换和静态分析需要保留原编码。
6. 版本信息在 `console_dllMain.cpp` 内硬编码为 2.0.1，GUID 必须跨版本保持不变；没有自动版本生成或发布门禁。

### 待核实

- Windows SDK 10.0.15063 与 v141 下实际可编译性；
- x86/x64 动态 DLL 的实际导出表与 `.fne` 文件名；
- 静态编译器使用的命令名回调及 `__E_STATIC_LIB` 的完整调用约定；
- 易语言 3.6/系统核心支持库 3.6 的真实 ABI 兼容性；
- `SDT_TEXT`/字节集内存释放及 GBK 文本在真实宿主中的编码约定；
- 控制台对象是否应保存 `HANDLE`、是否允许多个对象、是否需要跨线程同步。

## 11. Git 与证据基线

现场 Git 信息：

- 根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/console`
- 分支：`master`，工作树在建档前干净；
- 本地 HEAD：`0835dc3b1bb3cb3265a85df6065144d9ca9846e6`
- 提交时间：`2022-12-19 16:53:58 +0800`
- 提交信息：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/console.git`
- 本地 `origin/master` 与远程 `HEAD/refs/heads/master` 均为 `0835dc3b1bb3cb3265a85df6065144d9ca9846e6`（当前核对未 fetch/pull）。
- 本项目根不存在旧 `细探-*.md`；在源码参考库范围按 `细探-*` 与项目名检索未找到 `console` 对应旧细探，因此当前核对无旧细探可吸收。
- `codegraph_explore` 已按要求调用，但目标目录没有 `.codegraph/` 索引，工具返回不可查询；本归档改用真实文件读取和只读文本/工程盘点完成。未自行初始化索引。

## 12. 当前核对结论

`console` 的真实架构是一个非常小的易语言 Windows 支持库骨架：`CONSOLE_DEF` 统一声明 12 个对象命令，元数据层把命令、参数和两个自定义数据类型注册到 `LIB_INFO`，`fnshare` 提供易语言系统通知/内存辅助，动态入口仅导出 `GetNewInf`。但是命令执行层当前没有完成 Windows 控制台行为，也没有测试和可复现构建验证；后续若要生产化，应先冻结并验证 ABI，再逐条实现命令与句柄生命周期，补 Windows 宿主冒烟/回归测试，最后修复并验证 x64 导出与静态工程配置。

## 13. 后续底座映射：终端 I/O、编码、进程/管道/句柄与失败治理

> 本节是后续“基于底座的映射与裁决”，不是把目标平台已经存在的能力写成事实。凡只在本仓库 ABI 中声明、没有 Windows API 调用、测试或目标平台代码支撑的内容，均标记为“待核/装配计划”。当前源码事实仍然是：12 个命令函数没有执行控制台操作或填充返回值；本节只规定应如何归属，不宣称本仓库已具备终端执行能力。
>
> 事实证据：`console_cmdDef.cpp:34-44,53-62,67-92,113-134` 只取 `pArgInf` 局部参数；`console_dtType.cpp:15` 只在对象元数据中声明一个隐藏的 `SDT_INT`“控制台句柄”；`elib/fnshare.h:20-39,58-103,129-169` 提供通知、易语言内存分配和文本/字节集复制；`elib/lib2.h:780-824` 定义 `MDATA_INF` 文本、字节集和传址槽位，`:1094-1123` 定义数组/内存/运行时错误通知，`:1150-1173` 定义支持库生命周期通知；`console_dllMain.cpp:101-178` 对释放、卸载、延迟释放分支没有清理实现。当前核对对 `console*.cpp` 与 `elib/*` 的静态检索未发现 `CreateProcess`、`CreatePipe`、`ReadConsole`、`WriteConsole`、`ReadFile`、`WriteFile` 或 `CloseHandle` 调用。

### 13.1 单链路与职责边界

```text
请求/CLI/SDK
  → 统一网关：鉴权、限流、参数/大小校验、协议编解码、流式结果投影
  → 公共终端命令：console.read / console.write / process.spawn / pipe.read ...
  → 运行核心：task、租约、deadline、cancel、状态迁移、重试/恢复、证据
  → 系统/终端支持库：Windows Console/Process/Pipe/Handle 适配、编码转换、OS 错误归一化
  → Windows API/受管子进程/标准输入输出句柄
  → 结果/事件/资源清理证据
  → 运行核心收口终态 → 网关向调用方投影
```

固定边界如下：

- **系统/终端支持库是 OS 资源 owner**：创建、借用、转移和关闭 `HANDLE`、控制台输入输出、进程/管道、编码转换和 Windows 错误读取均在此层。上层只拿不透明的受管资源引用，不接触裸 `HANDLE`、线程句柄或 provider 对象。
- **运行核心是执行事实 owner**：创建任务和 attempt，保存 `deadline/cancel_reason/exit_code/error_code`，管理 lease/heartbeat，决定超时、取消与正常完成的竞态，负责进程组终止、重试/恢复、终态收口和资源残留审计。它不实现 `ReadConsole` 等 OS 细节。
- **统一网关是传输与安全边界**：做身份/租户授权、能力路由、速率/并发/输出大小限制、请求编解码和 SSE/WebSocket/轮询投影；断开连接不等于取消任务，网关不得直接 `CreateProcess`、杀进程、写任务状态或把“已发送响应”当成执行成功。
- **当前 `console` 只能作为 legacy 支持库适配层候选**：`GetNewInf`、`LIB_INFO`、`PFN_EXECUTE_CMD` 和 `PFN_NOTIFY_LIB` 可作为 ABI 事实输入；现有命令壳不能直接成为终端 provider，也不能绕过运行核心形成第二条执行链。

### 13.2 现有能力命中表与归属裁决

| 现有事实/目标能力 | 系统/终端支持库 | 运行核心 | 统一网关 | 后续裁决 |
|---|---|---|---|---|
| `GetNewInf`、`LIB_INFO`、`CMD_INFO[]`、`PFN_EXECUTE_CMD` | 保留为易语言 legacy ABI adapter 的注册/调用边界；不把元数据当功能实现 | 通过唯一能力调用器调度 adapter；记录版本、调用 id 和结果 | 不暴露 `MDATA_INF`/函数指针，只映射公共 JSON/CLI 契约 | **吸收为契约证据；隔离为兼容适配层** |
| 控制台输入 `InPut` | 实现受管 console read：坐标、回显、回车结束、最大长度、EOF/中断、编码和底层错误；当前源码没有实现 | 为一次读取分配 task/lease/deadline/cancel；决定阻塞、超时、取消和完成的最终状态 | 校验输入大小/编码声明、鉴权、流式投影；连接关闭不隐式取消 | **升级/新建 `terminal.console.read`；当前命令壳不复用为已实现能力** |
| 控制台输出 `OutPut`、清屏、光标、填充 | 实现 Windows Console API 适配、颜色/坐标边界和 `BOOL/INT` 结果；当前没有 `WriteConsole`/填充 API 调用 | 记录一次输出的幂等键、顺序和失败证据；长输出必须受限并可取消 | 做输出大小/速率/权限限制和结果投影，不直接写 OS console | **升级终端支持库；公共结果/错误由核心统一** |
| 编码与文本返回 | 以平台规范文本（建议 UTF-8）为公共边界，在适配器内显式转换 UTF-8↔UTF-16/legacy GBK；`LPSTR`/`__GBK_LANG_VER` 仅是当前旧 ABI 事实 | 保存 `encoding`、转换失败原因、原始/规范化长度和结果摘要；禁止静默替换导致不可审计 | 校验 `Content-Type`/编码声明、拒绝超限/非法序列并按协议返回错误 | **吸收边界，升级编码支持库；不得把 `CharacterSet=Unicode` 误读成命令已 Unicode 化** |
| 隐藏 `ConsoleHandle`（`SDT_INT`） | 真正持有 typed/opaque resource；负责有效性、线程归属、关闭和 double-close 防护；不能把裸 64 位 `HANDLE` 简单塞进 `SDT_INT` | 只持有资源租约/引用 id，超时或任务终止时调用统一 release/kill；维护资源与 task 关联 | 只接收不透明 resource id，按租户授权，禁止客户端提交裸句柄 | **升级句柄契约；现有成员仅元数据，不能视为句柄生命周期实现** |
| 进程启动、标准输入输出和管道 | 新建受管 `process.spawn`/`pipe.read`/`pipe.write` provider，拥有 `CreateProcess`、继承属性、读写句柄、EOF 和关闭顺序；本项目无此代码 | 拥有 process attempt、进程组/job、deadline、取消升级（优雅→强制）、退出码和重启恢复 | 只提交受限命令/参数或能力 id，做 allowlist、审计和输出限制，禁止直连 OS | **新建原子能力；不能从本 `console` 代码推导已有进程支持** |
| 易语言文本/字节集内存 | 用 `NRS_MALLOC/NRS_MFREE` 或 `ealloc/efree` 与宿主分配器交互；返回文本必须由支持库按 ABI 生成，避免跨 CRT 释放 | 记录分配责任、转移和清理结果；运行时错误/退出语义由宿主核心执行 | 不接触指针，只接收序列化结果/制品 | **吸收内存契约；禁止 provider 自行 `malloc/free` 穿过 ABI** |
| `NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` | 支持库清空回调、释放句柄/缓冲/线程/进程资源并拒绝新调用；当前释放分支为空，用户回调也未见清空 | 先停止任务/撤销 lease，再等待 provider 清理并记录证据；不可用 DLL 卸载代替任务终态 | 网关只呈现卸载/不可用错误，不决定资源是否已释放 | **升级生命周期支持；当前仅有通知框架** |

### 13.3 I/O、编码与资源契约

1. **输入契约**：公共命令必须显式携带 `task_id`、`request_id/idempotency_key`、`deadline`、`cancel_token`、`encoding`、`max_bytes/max_chars` 和 `echo/line_end` 等语义。当前 `InPut` 的 7 个参数只存在于 `console_cmdDef.cpp:26-44` 的元数据/局部变量，未形成可执行契约；不能把注释中的“回车结束”“不过滤特殊字符”当作实现。
2. **输出契约**：输出按字节/字符数和单次/累计额度限流，返回 `written`、`encoding`、`cursor`（如适用）及结构化错误。当前 `OutPut` 声明 `SDT_BOOL` 却不写 `pRetData`（`console_cmdDef.cpp:53-62`），`FillBackColor` 注释说失败返回 `-1` 却不写返回槽（`:108-120`），只能标记为未实现。
3. **编码契约**：`elib/lang.h:8-14` 将本库语言标为 `__GBK_LANG_VER`；`MDATA_INF.m_pText` 是只读 `char*`（`elib/lib2.h:793-794`），不能直接改写入参或假定其为 UTF-8。支持库必须在边界做严格解码/编码、明确替换策略（默认拒绝非法序列）、保留输入长度和转换错误；网关传输编码与 legacy GBK 不应混在同一字段里。
4. **返回内存契约**：需要返回新文本/字节集时，使用宿主分配器并把所有权写进契约；`m_ppText/m_ppBin` 在 `elib/lib2.h:811-812` 要求写新值前先释放旧值。`fnshare.h:61-102,129-140` 的 clone/get helper 返回的内存必须由调用方 `efree`，不得交给普通 CRT `free`。
5. **句柄契约**：当前“控制台句柄”是 `SDT_INT` 元数据（`console_dtType.cpp:15`），不是源码中的 `HANDLE`。目标平台应以 opaque resource id + owner + generation + release state 表达资源；支持库内部再保存真正 `HANDLE`，保证关闭只发生一次，并在句柄失效、父进程退出、管道 EOF 时清理关联资源。
6. **进程/管道契约**：进程 provider 必须声明命令白名单、工作目录、环境继承、stdin/stdout/stderr 绑定、最大输出、退出码和句柄继承策略；pipe reader/writer 要区分正常 EOF、broken pipe、超时和取消，不能以“读到空串”冒充成功。上述能力在当前仓库不存在，进入平台只能作为新 provider 装配。

### 13.4 失败、超时、取消与崩溃矩阵

| 场景 | 当前源码证据/现状 | 权威 owner | 最低正确语义与清理要求 |
|---|---|---|---|
| `nArgCount` 不足、`pArgInf/pRetData` 为空、引用参数为空 | 命令函数直接访问 `pArgInf[1..7]` 或 `m_pInt`，未见边界/空指针检查（`console_cmdDef.cpp:34-134`） | 终端支持库先做契约校验；运行核心记录拒绝 | 返回结构化 `invalid_argument`，不触碰 OS，不崩宿主；已创建的临时缓冲/句柄仍走清理；网关只投影 4xx/等价错误 |
| 空文本、负坐标、负长度、超长输入/输出、非法颜色 | 元数据声明参数类型，但无实现或范围校验 | 支持库负责域校验，网关做第一层大小/速率门禁 | fail-closed；保留实际限制版本和拒绝原因，不能让 Windows API 或整数溢出决定行为 |
| GBK/UTF-8/UTF-16 非法序列、NUL/控制字符策略不一致 | `LPSTR` 与 GBK 语言标志已确认，转换实现不存在 | 编码支持库 | 明确拒绝或按版本化策略替换；记录输入/输出编码和字节数；释放转换缓冲 |
| 无控制台、句柄失效、Console API 失败 | 当前没有句柄创建和 API 调用；未知通知才在 `console_dllMain.cpp:173-177` 返回 `NR_ERR` | 终端支持库归一化 OS 错误，核心收口任务 | 返回 `console_unavailable/invalid_resource/os_error`，不把未初始化 `SDT_BOOL/SDT_INT` 当成功；释放失效句柄并保留 OS 错误码 |
| 输入阻塞超过 deadline | 当前 `InPut` 没有 deadline 参数，也没有阻塞实现 | 运行核心拥有 deadline；支持库负责可中断读 | 进入 `timed_out`，取消读事件/关闭或替换受管读句柄；不能只让网关 HTTP 超时而留下后台阻塞线程 |
| 主动取消与完成/失败竞态 | 当前无取消状态、token 或异步执行 | 运行核心原子裁决；支持库执行停止动作 | 取消是请求而非保证；核心记录请求时点、裁决时点和最终唯一终态。断开 SSE/HTTP 不得直接写 `CANCELED` |
| 进程退出、非零退出、正常 pipe EOF、broken pipe | 本项目没有进程/管道代码 | 终端 provider 报事实，运行核心收口 | 区分 `completed(exit_code=0)`、`failed(exit_code!=0)`、`eof`、`broken_pipe`；关闭 stdin/stdout/stderr 顺序固定，回收 process/job/pipe 句柄 |
| 重复命令、重复事件、重试 | `console` 没有 request id、幂等表或事件存储 | 运行核心 | 以 `request_id/idempotency_key + attempt` 去重；重试不得重复输出或重复释放；网关不能用重发请求创建第二进程 |
| 内存分配失败 | `ealloc` 调 `NRS_MALLOC(size,0)` 后直接 `memset`（`elib/fnshare.h:25-32`）；`lib2.h:1099-1112` 规定失败可触发运行时错误/退出 | 易语言运行时/系统核心提供 allocator 和错误语义；支持库负责不继续使用空指针 | 失败必须终止当前能力并释放已取得资源；不能跨 CRT 释放；若宿主按 `dwParam2=0` 退出，证据应记录 runtime error/exit code |
| DLL unload、`NL_FREE_LIB_DATA`、宿主进程退出 | `console_dllMain.cpp:134-147` 分支为空，`DllMain` attach/detach 也为空（`:7-24`）；`fnshare.cpp:38-40` 的释放通知分支为空 | 支持库先 quiesce/release，核心保证没有 in-flight 调用 | 拒绝新命令、等待/取消在途调用、清空用户/系统回调、关闭所有句柄/线程/管道，再允许卸载；当前源码为未实现风险 |
| 支持库/worker/宿主崩溃 | 当前无 worker、崩溃恢复或残留扫描 | 运行核心发现 lease/心跳失效并恢复；支持库/宿主负责进程级清理 | 任务不能永久卡在 running；重启后按 lease/attempt 判定 `failed`/可重试；扫描 PID、端口、句柄、临时文件、管道和锁，不能用同进程内存状态假装恢复 |

### 13.5 底座 L0-L4 验收等级

以下等级沿源码参考库的统一口径使用；“通过”只表示该层证据满足，不把源码存在、日志打印或历史声明升级为运行级通过。

| 等级 | 对本项目/平台装配的证明目标 | 当前状态 | 升级后的通过条件 |
|---|---|---|---|
| **L0 结构/契约** | 能定位 `GetNewInf`、12 命令、`MDATA_INF`、GBK/`LPSTR`、句柄元数据、通知和内存边界，并明确支持库/核心/网关 owner | **已完成（静态证据）**：本文件第 3、5、7、13 节与列出的源码路径 | 公共 capability id、输入输出 schema、错误/超时/取消、编码、资源所有权和版本兼容均只有一个 owner |
| **L1 纯逻辑** | 无 Windows/外部服务时验证参数边界、空值/超限、编码策略、返回槽初始化、幂等键和状态迁移 | **未通过/未执行**：现有命令未校验参数、未写返回值，也无测试目录 | 固定样本覆盖空/非法/重复/超限/非法编码；每个拒绝有稳定错误和无资源残留断言 |
| **L2 隔离终端服务** | 在 Windows 受控 harness/mock 中验证 console attach、读写/颜色/光标、编码转换、process/pipe、OS 错误、timeout/cancel | **阻断/未验证**：源码未实现 Console/Process/Pipe API，当前 macOS 不能执行 MSVC/Windows 验证 | provider 有 health/version、deadline/cancel、错误码和句柄探针；正常/失败/超时/取消都能读回结果并释放资源 |
| **L3 宿主/数据面闭环** | 真实易语言运行时加载 `.fne` 或静态库，调用 `GetNewInf`/`PFN_EXECUTE_CMD`，验证通知、GBK/返回内存、console/process/pipe 结果闭环 | **阻断/未验证**：无 Windows 构建、宿主冒烟或集成测试；现有实现本身不产生真实 I/O | 宿主读回唯一任务/事件/结果；动态/静态、x86/x64、卸载和重复调用均通过，内存/句柄/进程归零 |
| **L4 生产式恢复** | 并发长读写、网关断线、主动取消、deadline 超时、pipe/worker/宿主崩溃、重启恢复、残留审计 | **未验证且当前能力缺失**：无异步、租约、进程组、恢复器或清理测试 | 注入每个故障点后任务最终可重试/终止；无孤儿 PID、端口、pipe、HANDLE、临时文件、锁和后台线程，并保留完整证据链 |

### 13.6 吸收、升级、隔离与装配计划

| 裁决 | 内容 | 进入位置 | 前置验收 |
|---|---|---|---|
| **吸收** | `LIB_INFO`/`CMD_INFO`/`PFN_EXECUTE_CMD` ABI、GBK legacy 标志、`NRS_MALLOC/MFREE`、`NL_*` 通知语义 | 公共 ABI/legacy adapter 契约 | 结构体大小/调用约定/字符串编码/返回内存读回；不能只凭源码声明通过 |
| **升级现有支持库** | 编码转换、终端 console read/write、错误归一化、opaque resource/handle registry、文本/字节集所有权 | 系统/终端支持库 | Windows API 隔离测试、x86/x64 句柄宽度、double-close、EOF/broken pipe、超时/取消清理 |
| **新建原子能力** | `terminal.process.spawn`、`terminal.pipe.read/write`、`terminal.resource.release`（若现有底座没有对应唯一 owner） | 系统/终端支持库 + 唯一能力注册表 | allowlist/环境继承/句柄继承/进程组/退出码/资源清理契约；禁止模块和网关各建一套 |
| **升级运行核心** | task/attempt、lease/heartbeat、deadline/cancel、取消与完成竞态、进程组终止、崩溃恢复、证据和残留扫描 | 运行核心 | 真实新进程重启后恢复；四种终态（完成、业务失败、主动取消/超时、宿主/子进程崩溃）都能收口 |
| **隔离网关细节** | HTTP/CLI/WS/SSE 编码映射、鉴权、限流、输出投影、兼容别名 | 统一网关 | 网关不直连 OS、不持有裸句柄、不写任务状态；断线、重复请求和错误投影有契约测试 |
| **待核/不直接复用** | 当前 12 个空壳命令、`SDT_INT ConsoleHandle` 作为裸句柄、空的卸载清理分支 | 仅留在 legacy 研究记录 | 只有逐命令实现、Windows 宿主验证和 L0→L4 证据齐全后，才可决定是否作为兼容入口；此前不能进入生产单链路 |

装配顺序固定为：

1. **先冻结公共契约**：登记唯一 `terminal.console.read/write/clear/cursor/fill`、`terminal.process.spawn`、`terminal.pipe.read/write`、`terminal.resource.release` 和 `task.cancel` 能力 id，明确版本、输入输出、错误、deadline、取消、幂等和资源 owner。
2. **再升级系统/终端支持库**：内部用 UTF-16/WinAPI 与受管 `HANDLE`，边界显式适配 UTF-8 和 legacy GBK；所有文本/字节集使用易语言分配器；资源以 opaque id 传递，禁止裸指针/裸句柄穿层。
3. **再接运行核心**：把每次 console/process/pipe 操作包成 task/attempt，记录 lease、deadline、cancel、exit/error、事件序号和清理结果；超时/取消必须能传到实际读写和进程组，而不是只取消等待者。
4. **最后接统一网关**：只做鉴权、限流、参数/编码校验、协议映射和事件投影；不创建进程、不关闭核心资源、不通过 HTTP 连接存活推断任务状态。
5. **按 L0→L4 放行**：每一级记录源码/测试/真实执行/外部依赖/退出码/测试数/进程与句柄清理结果；当前本仓库只能报告 L0 静态完成，不能报告 L1-L4 通过。

后续结论：**吸收**的是易语言支持库 ABI、GBK legacy 边界、宿主内存通知和库生命周期通知的契约事实；**升级**的是系统/终端支持库的编码、console I/O、错误和句柄所有权，以及运行核心的 deadline/cancel/进程组/恢复；**新建**的是本仓库完全没有的 process/pipe 原子能力；**隔离**的是网关传输和 `console` 的旧 ABI 适配；**待核**的是任何真实 Windows Console API 行为、进程/管道实现、卸载清理和 L1-L4 运行证据。当前源码不得被描述为已具备终端、进程或资源回收能力。
