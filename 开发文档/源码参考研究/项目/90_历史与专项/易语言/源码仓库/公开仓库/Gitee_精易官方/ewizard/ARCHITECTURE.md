# ewizard 架构档案

> 本文件是本项目唯一的首轮架构事实源。内容依据当前工作树源码、Visual Studio 工程文件和 Git 元数据整理；源码本身保持只读。
>
> 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/ewizard`

## 1. 项目定位

`ewizard` 是一个面向易语言 IDE/运行系统的 Windows 支持库（动态库文件名配置为 `ewizard.fne`），定位是为“易语言向导程序”提供一组可被易语言调用的程序项修改与模板生成命令。

从当前仓库快照看，它已经具备完整的支持库**元数据与 ABI 骨架**：库信息、命令信息、参数信息、枚举数据类型、动态库入口、系统通知入口和静态库兼容分支均已搭建；但 16 个命令实现函数目前只从 `pArgInf` 读取参数到局部变量，没有实际修改程序、写出程序、设置返回值或调用 IDE 能力的业务逻辑。因此，当前快照更准确的定位是“易向导支持库接口/代码生成骨架”，不能据源码宣称已经实现可运行的向导引擎。

## 2. 总体流程

```text
易语言 IDE / 易语言编译运行系统
        │
        ├─ 动态方式：LoadLibrary("ewizard.fne")
        │       │
        │       ├─ 固定导出 GetNewInf()
        │       │       └─ 返回静态 LIB_INFO
        │       │              ├─ 版本/GUID/名称/系统要求/平台
        │       │              ├─ 16 项 CMD_INFO 命令元数据
        │       │              ├─ 16 项 PFN_EXECUTE_CMD 函数指针
        │       │              ├─ 3 个枚举型 LIB_DATA_TYPE_INFO
        │       │              └─ 0 个库常量
        │       │
        │       └─ 易语言按命令索引调用
        │               └─ ewizard_*_<index>_ewizard(pRetData, nArgCount, pArgInf)
        │                       └─ 当前仅读取参数，未执行修改/生成
        │
        ├─ 系统通知：ewizard_ProcessNotifyLib_ewizard(...)
        │       ├─ NL_SYS_NOTIFY_FUNCTION
        │       │       └─ 转发到 elib/fnshare.cpp::ProcessNotifyLib
        │       │               └─ 保存系统通知函数指针，查询程序类型
        │       ├─ NL_GET_CMD_FUNC_NAMES
        │       │       └─ 返回静态编译所需的命令函数名数组
        │       ├─ NL_GET_NOTIFY_LIB_FUNC_NAME
        │       │       └─ 返回通知函数名文本
        │       ├─ NL_GET_DEPENDENT_LIBS
        │       │       └─ 返回空的双 NUL 依赖列表
        │       └─ 其它通知
        │               ├─ 已识别但当前无资源释放/IDE 操作逻辑
        │               └─ 未识别消息返回 NR_ERR
        │
        └─ 静态方式：链接 ewizard_static.lib
                ├─ 编译同一组命令/元数据源码
                ├─ __E_STATIC_LIB 分支排除动态 LIB_INFO、参数表、数据类型表
                ├─ 保留命令实现函数和命令名数组
                └─ 由宿主静态链接流程取得函数名并完成绑定
```

## 3. 仓库与工程布局

当前 Git 版本库共 22 个受版本控制的非 Git 文件，按职责可分为：

```text
ewizard/
├── ewizard.sln                         # VS 解决方案，动态库项目 + 静态库项目
├── ewizard.vcxproj                     # ewizard 动态库工程
├── ewizard.vcxproj.filters              # 动态库工程筛选器
├── ewizard.vcxproj.user                 # 空的用户工程设置
├── ewizard_static/
│   ├── ewizard_static.vcxproj          # ewizard_static 静态库工程
│   ├── ewizard_static.vcxproj.filters
│   └── ewizard_static.vcxproj.user      # 空的用户工程设置
├── Source_ewizard.def                   # 动态库模块定义，仅导出 GetNewInf
├── include_ewizard_header.h             # 项目总头文件、全局元数据声明、命令声明宏
├── ewizard_cmd_typedef.h                # 16 个命令的 X-macro 总表
├── ewizard_cmdDef.cpp                   # 16 个命令入口的当前实现骨架
├── ewizard_cmdInfo.cpp                  # 40 个参数描述 + 16 项 CMD_INFO
├── ewizard_dtType.cpp                   # 3 个枚举型易语言自定义数据类型
├── ewizard_const.cpp                    # 空库常量表
├── ewizard_dllMain.cpp                  # DllMain、LIB_INFO、GetNewInf、系统通知分发
└── elib/
    ├── lib2.h                           # 易语言支持库 ABI、数据类型、命令/库信息结构
    ├── mtypes.h                         # Windows 风格基础类型兼容定义
    ├── lang.h                           # 编译语言版本，当前为 GBK
    ├── krnllib.h                        # 系统核心支持库常量/类型辅助
    ├── fnshare.h                        # 支持库共享通知与内存/数据辅助声明
    ├── fnshare.cpp                      # 通知函数指针与调试版本状态实现
    ├── untshare.h                       # 组件/窗口共享辅助声明，当前未进入实际调用链
    └── PublicIDEFunctions.h             # IDE 功能通知协议与功能编号，当前仅作为工程头文件
```

源码文件以 Windows 工具链习惯的 CRLF 保存，中文源码按 GB18030/CP936 兼容方式读取；项目没有 README、AGENTS.md、测试目录、外部依赖清单或旧 `细探-*.md` 文件。目标目录及其易语言归档父目录内当前核对未发现 `细探-*.md`，因此没有可吸收的旧细探结论。

## 4. 工程与构建拓扑

### 4.1 `ewizard` 动态库工程

- 工程类型：`DynamicLibrary`。
- 解决方案配置：`Debug|x86`、`Release|x86`、`Debug|x64`、`Release|x64`；解决方案中的 `x86` 映射到项目 `Win32`。
- 编译单元：`elib/fnshare.cpp`、`ewizard_cmdDef.cpp`、`ewizard_const.cpp`、`ewizard_dllMain.cpp`、`ewizard_dtType.cpp`、`ewizard_cmdInfo.cpp`。
- 头文件：项目总头、命令宏头和 `elib` 下六个协议/辅助头。
- Win32 Debug/Release 明确设置 `__E_FNENAME=ewizard`，并设置 `EWIZARD_EXPORTS`；Win32 目标扩展为 `.fne`。
- 链接使用 `Source_ewizard.def`，因此当前明确的 DLL 导出是 `GetNewInf`。
- 目标 Windows SDK：`10.0.15063.0`；工具集：`v141`；字符集：Unicode；运行库为 Debug 多线程调试、Release 多线程。
- 没有 PostBuildEvent 内容。

### 4.2 `ewizard_static` 静态库工程

- 工程类型：`StaticLibrary`。
- 编译同一组 `ewizard_*.cpp` 和 `elib/fnshare.cpp`，路径从子目录以 `..\\` 引用。
- Win32 Debug/Release 设置 `__E_STATIC_LIB` 与 `__E_FNENAME=ewizard`；x64 配置的预处理宏较少，工程文件中没有看到同等的 `__E_STATIC_LIB`/`__E_FNENAME` 设置。
- 静态分支不编译动态库 `LIB_INFO` 数据与 DLL 生命周期逻辑，但保留 `ewizard_ProcessNotifyLib_ewizard`、命令函数及 `g_cmdNamesewizard`，供静态链接器/宿主按名称绑定。
- 静态项目没有自己的源文件，实质上是同一实现骨架的另一种装配方式。

### 4.3 构建前置条件与当前验证边界

源码直接依赖 Windows/MSVC 头和 ABI（`windows.h`、`windef.h`、`tchar.h`、`winnt.h` 等），并使用 `WINAPI`、`HMODULE`、`DLL_PROCESS_ATTACH`、`__stdcall` 等 Windows 语义。本机为 macOS，且当前核对明确禁止构建/安装依赖，因此没有执行 Visual Studio/MSBuild 构建，也没有产出 `.fne`、`.lib` 或 `.dll`。构建能否在 Windows 上通过仍需在匹配的 VS v141 + Windows SDK 环境验证。

## 5. 核心模块与调用链

### 5.1 `ewizard_cmd_typedef.h`：命令单一总表

`EWIZARD_DEF(_MAKE)` 是 X-macro 命令总表。每一项同时驱动：

1. `include_ewizard_header.h` 生成命令函数声明；
2. `ewizard_cmdDef.cpp` 中的实际函数命名约定；
3. `ewizard_cmdInfo.cpp` 生成 `CMD_INFO`；
4. `ewizard_dllMain.cpp` 生成 `PFN_EXECUTE_CMD` 函数指针表；
5. `ewizard_dllMain.cpp` 生成静态编译用命令名数组。

函数名规则由 `ewizard_cmd_typedef.h` 与 `elib/lib2.h` 的宏拼接：

```text
ewizard_<英文命令名>_<十进制索引>_ewizard
```

例如 `CopyProgram` 的实现符号是 `ewizard_CopyProgram_0_ewizard`。这种设计把索引、显示名、英文名、返回类型、系统标志、参数数目和参数数组起点集中在一处，降低元数据与实现索引错位的风险。

### 5.2 `ewizard_dllMain.cpp`：宿主入口与库登记

当前动态路径包含三个关键对象：

- `DllMain`：处理四类 DLL 生命周期通知，但四个分支均为空，仅返回 `TRUE`。
- `g_LibInfo_ewizard_global_var`：静态 `LIB_INFO` 登记对象，集中提供 ABI 元数据。
- `GetNewInf`：按易语言约定的固定导出名返回 `&g_LibInfo_ewizard_global_var`。

登记事实：

| 字段 | 当前值 |
|---|---|
| 库格式 | `LIB_FORMAT_VER`，值为 `20000101` |
| GUID | `F4252F5EB88342579B4E216FC410E5D7` |
| 库版本 | 主版本 `2`，次版本 `0`，构建号 `0` |
| 易语言系统要求 | 主版本 `3`，次版本 `8` |
| 系统核心支持库要求 | 主版本 `3`，次版本 `0` |
| 名称 | `易向导支持库` |
| 语言 | `__GBK_LANG_VER`（1，中文 GBK） |
| 平台 | `_LIB_OS(__OS_WIN)`，仅 Windows |
| 命令类别 | 1 类，文本为 `0000易向导` |
| 命令数量 | 16 |
| 自定义数据类型 | 3 |
| 常量数量 | 0 |
| AddIn | 未提供，`NULL` |
| SuperTemplate | 未提供，`NULL` |
| 依赖文件串 | `NULL` |
| 通知函数 | `ewizard_ProcessNotifyLib_ewizard` |

### 5.3 `ewizard_cmdDef.cpp`：命令执行入口现状

所有命令都使用统一 ABI：

```text
void 命令函数(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

当前实现只完成由参数描述推导出的读取动作，例如：

- `SDT_TEXT` 参数读取 `pArgInf[i].m_pText`；
- `SDT_BIN` 参数读取 `pArgInf[i].m_pBin`；
- `SDT_BOOL` 参数读取 `pArgInf[i].m_bool`；
- `SDT_INT` 参数读取 `pArgInf[i].m_int`；
- 复合/通用数据读取 `m_pCompoundData` 或 `m_pByte`。

没有命令调用 `NotifySys`、`ProcessNotifyLib`、`PublicIDEFunctions.h` 中的 IDE 功能通知，亦没有写入 `pRetData`。特别是元数据宣称会返回错误文本的 `写出程序`，当前函数也没有填充文本返回值。因此真实写入/读取/执行调用链在当前快照于命令实现层断开：宿主可以完成 ABI 分发，但命令不会改变目标程序。

## 6. 公开命令/API 边界

支持库公开的是易语言命令元数据和 ABI 函数指针，而不是 HTTP、CLI 或独立 SDK。当前 16 项命令如下：

| 索引 | 中文命令 | 英文名/实现符号尾部 | 参数数 | 返回类型 | 语义线索 |
|---:|---|---|---:|---|---|
| 0 | 复制程序 | `CopyProgram` | 3 | `_SDT_NULL` | 按程序项类型、名称复制并使用新名称建立项目 |
| 1 | 复制程序段 | `CopyCode` | 3 | `_SDT_NULL` | 在子程序内按标记复制完整程序段 |
| 2 | 删除程序 | `RemoveProgram` | 2 | `_SDT_NULL` | 按程序项类型和名称删除项目 |
| 3 | 删除程序段 | `RemoveCode` | 2 | `_SDT_NULL` | 在子程序内按标记删除完整程序段 |
| 4 | 删除标记程序 | `RemoveMarkedItem` | 1 | `_SDT_NULL` | 删除备注包含指定标记的程序项目，不含代码段 |
| 5 | 修改程序 | `ModiProgram` | 4 | `_SDT_NULL` | 按项目、属性和值修改程序项 |
| 6 | 置组件属性 | `SetCtrlProperty` | 2 | `_SDT_NULL` | 按窗口/组件/属性路径设置属性值 |
| 7 | 置语句备注 | `SetStatmentRemark` | 3 | `_SDT_NULL` | 设置子程序中指定标记语句的备注 |
| 8 | 置程序信息 | `SetProgramInfo` | 5 | `_SDT_NULL` | 设置名称、类型、备注、版本和图标 |
| 9 | 置作者信息 | `SetAuthorInfo` | 8 | `_SDT_NULL` | 设置作者、地址、电话、邮箱、主页等信息 |
| 10 | 定义模板变量 | `SetTemplateVar` | 2 | `_SDT_NULL` | 设置向导模板变量及其可选值 |
| 11 | 删除模板变量 | `RemoveTemplateVar` | 1 | `_SDT_NULL` | 删除已定义模板变量 |
| 12 | 清除修改记录 | `ClearModiRec` | 0 | `_SDT_NULL` | 清除此前记录的模板修改 |
| 13 | 写出程序 | `WritePrg` | 2 | `SDT_TEXT` | 根据模板修改记录生成程序并返回错误文本 |
| 14 | 添加模块引用 | `AddEComRef` | 1 | `_SDT_NULL` | 添加易模块文件引用 |
| 15 | 删除模块引用 | `RemoveEComRef` | 1 | `_SDT_NULL` | 按文件名删除易模块引用 |

总计 16 个命令、40 个参数；只有 `清除修改记录` 为零参数，最大参数数为 8。命令及参数均标记为 Windows 支持，用户级别均为 `LVL_SIMPLE`，命令类别均为 1。

### 参数数据契约

`ewizard_cmdInfo.cpp` 的参数表共 40 项，使用 `ARG_INFO` 描述名称、解释、数据类型、默认值和参数标志。关键契约包括：

- 项目类型、修改项类型、修改属性等枚举数据使用 `MAKELONG(0x01, 0)` 或 `MAKELONG(0x02, 0)` 的库自定义类型编码。
- 通用修改值、组件属性值、模板变量值使用 `_SDT_ALL`，表示系统基本类型的通用输入。
- 文本参数使用 `SDT_TEXT`，模板程序数据和图标使用 `SDT_BIN`。
- `置语句备注` 的第三参数、`置程序信息` 的五个参数、`置作者信息` 的八个参数及 `定义模板变量` 的第二参数使用 `AS_DEFAULT_VALUE_IS_EMPTY`，允许省略为空或保持不变，具体以参数解释为准。
- 模板条件语法通过备注中的标记文本表达，包括 `$如果/$if`、`$否则/$else`、`$结束/$end` 以及 `$(标记)`、`$(标记/)`、`$(/标记)`。

## 7. 数据模型与持久化

本项目没有数据库、配置文件、网络存储、磁盘缓存或业务持久化层。数据模型全部是进程内静态 ABI 结构：

- `LIB_INFO`：整个支持库登记信息。
- `CMD_INFO`：命令显示名、英文名、说明、类别、状态、返回类型、参数范围。
- `ARG_INFO`：单个命令参数的编辑器/运行时契约。
- `LIB_DATA_TYPE_INFO`：库自定义数据类型定义。
- `LIB_DATA_TYPE_ELEMENT`：枚举成员定义。
- `LIB_CONST_INFO`：常量定义；本项目数量为 0，数组仅作占位。
- `MDATA_INF`：命令调用时的输入/输出数据容器，使用联合体承载基础值、文本、字节集、复合数据、数组和变量指针。

`MDATA_INF` 在 `elib/lib2.h` 中采用 1 字节对齐的协议结构；命令实现必须按照 `m_dtDataType` 与参数标志解释联合体字段。当前代码仅读输入，不负责内存释放，也没有产生新的文本/字节集结果，因此没有可验证的资源所有权闭环。

## 8. 系统通知与生命周期

### 8.1 库级通知

`ewizard_ProcessNotifyLib_ewizard` 处理以下消息：

| 消息 | 当前行为 |
|---|---|
| `NL_SYS_NOTIFY_FUNCTION` | 把 `dwParam1` 作为 `PFN_NOTIFY_SYS` 交给 `ProcessNotifyLib`，后者保存系统回调并首次查询 `NRS_GET_PRG_TYPE` |
| `NL_FREE_LIB_DATA` | 空分支，无资源释放逻辑 |
| `NL_GET_CMD_FUNC_NAMES` | 动态库分支返回 `g_cmdNamesewizard` |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 动态库分支返回 `ewizard_ProcessNotifyLib_ewizard` 文本 |
| `NL_GET_DEPENDENT_LIBS` | 动态库分支返回 `"\0\0"`，声明无额外静态依赖 |
| `NL_UNLOAD_FROM_IDE` | 空分支 |
| `NR_DELAY_FREE` | 空分支，未返回延迟释放语义 |
| `NL_IDE_READY` | 空分支；库未设置 `LBS_IDE_PLUGIN`，正常情况下不会依赖该通知 |
| `NL_RIGHT_POPUP_MENU_SHOW` | 空分支；同样未声明 IDE 插件状态 |
| `NL_ADD_NEW_ELEMENT` | 空分支，未实现新成员拦截/修改 |
| 其它 | 返回 `NR_ERR` |

### 8.2 `elib/fnshare.cpp` 共享通知层

- `s_pfnNotifySys` 保存宿主提供的系统通知回调。
- `NotifySys` 对回调为空做保护，否则原样转发消息与两个参数。
- `ProcessNotifyLib` 处理 `NL_SYS_NOTIFY_FUNCTION`，并在首次收到时调用 `NRS_GET_PRG_TYPE` 更新 `s_isDebug`。
- `SetUserSysNotify` 保存用户回调，并返回 `ProcessNotifyLib` 函数指针。
- `isDebugVer` 返回当前程序类型是否为 `PT_DEBUG_RUN_VER`，并可通过指针输出内部状态。

这是当前源码中唯一实际存在的跨层通知调用链；命令实现没有接入它。

## 9. 自定义数据类型

`ewizard_dtType.cpp` 注册 3 个 `LDT_ENUM` 数据类型，均为 Windows 支持：

1. `程序项类型` / `AppItemType`：13 个成员，包括 `Module`、`Sub`、`GlobalVar`、`ModuleVar`、`LocalVar`、`SubArg`、`DataType`、`DataTypeElement`、`DllCmd`、`DllCmdArg`、`Win`、`WinControl`、`Resource`。
2. `程序项属性` / `AppItemProperty`：12 个成员，包括名称、备注、常量或资源值、数据类型、数组类型、静态、参考、可空、公开、收缩、DLL库文件名、DLL库命令名。
3. `程序项数据类型` / `AppItemDataType`：11 个成员，包括空白型、字节型、短整数型、整数型、长整数型、小数型、双精度小数型、逻辑型、日期时间型、文本型、字节集型。

枚举成员的英文名和数值掩码构成命令参数可用的编辑契约，但当前命令实现没有消费这些枚举值。

## 10. 依赖边界

### 10.1 直接源码依赖

- Windows 平台头：`windows.h`、`windef.h`、`winnt.h`、`tchar.h`。
- C/C++ 运行库头：`stdio.h`、`math.h`、`assert.h`、`time.h`。
- 易语言支持库 ABI：`elib/lib2.h`。
- 易语言语言版本与核心辅助：`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`。
- 共享通知辅助：`elib/fnshare.h`、`elib/fnshare.cpp`。

### 10.2 外部库与运行时

工程文件未声明第三方 NuGet/vcpkg/包管理器依赖，也未声明额外 DLL/静态库依赖；`m_szzDependFiles` 为 `NULL`，静态依赖查询返回空双 NUL 字符串。真正的宿主依赖是：

1. Windows + 易语言系统 ABI；
2. 与 `LIB_FORMAT_VER` 兼容的易语言支持库加载器；
3. MSVC v141/Windows SDK 10.0.15063.0（构建侧）。

## 11. 测试、验证与当前证据

仓库没有测试源文件、测试工程、CI 配置或自动化验证脚本。首轮只读验证已完成：

- 现场扫描确认目标根只有 22 个 Git 跟踪文件，无 README、AGENTS.md、测试目录、依赖清单和旧 `细探-*.md`。
- 解析 `ewizard.sln`、两个 `.vcxproj`、两个 filters 文件和 `.def`，核对动态/静态工程边界。
- 读取并分析 6 个主 C++ 文件、项目头、命令总表以及 `elib` ABI 头的关键结构和调用点。
- 通过源码计数确认 16 个命令、40 个参数、3 个枚举数据类型、0 个库常量。
- 通过源码调用检查确认 16 个命令函数均未写 `pRetData`，没有发现实际程序修改或生成调用。
- 未执行构建、链接、运行、加载 DLL、易语言 IDE 交互或 ABI 端到端验证，原因是任务边界要求不构建且当前主机为 macOS。

因此，当前可验证结论是“接口元数据和宿主接入骨架存在”；“命令在易语言 IDE 中可以真正修改/生成程序”属于未验证且被当前空实现直接否定的能力，不应作为现状能力记录。

## 12. 风险、缺口与后续复核点

1. **核心业务实现缺失**：16 个命令均为空心参数读取函数，尤其 `写出程序` 未返回约定的错误文本。若目标是可用向导支持库，需要补齐程序项模型访问、修改记录、模板条件解析、程序写出和错误处理。
2. **返回值契约未落实**：`pRetData` 从未使用；未来实现必须遵循 `PFN_EXECUTE_CMD` 对 `_SDT_ALL`/`SDT_TEXT` 等返回类型的填充规则，并明确文本/字节集所有权和释放方式。
3. **IDE 协议未接线**：`PublicIDEFunctions.h` 定义了大量 `NES_RUN_FUNC`/`FN_*` 能力，但当前实现没有通过 `NotifySys` 发起 `NES_RUN_FUNC` 调用。向导真正读写 IDE 程序状态前，需要确认宿主通知协议、参数结构和失败码。
4. **x64 工程宏配置需复核**：主动态工程和静态工程的 x64 配置中未见 Win32 配置所使用的 `__E_FNENAME=ewizard`（静态 x64 也未见 `__E_STATIC_LIB`）。`elib/lib2.h` 对 `__E_FNENAME` 有强制要求；在 Windows 上实际生成 x64 前应先验证工程预处理宏，否则可能预处理失败或符号命名不一致。
5. **动态导出边界较窄**：`.def` 只导出 `GetNewInf`，这是符合支持库加载约定的最小边界；若外部工具想直接调用命令符号，当前导出表不提供该路径，只能经 `LIB_INFO.m_pCmdsFunc`。
6. **ABI/编码兼容风险**：`MDATA_INF` 依赖 1 字节对齐、Windows 类型宽度和 GBK 文本契约。迁移到非 Windows 或改变编译器结构对齐会破坏 ABI，不能把当前代码直接当跨平台实现。
7. **生命周期与资源释放未完成**：`DllMain`、`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 均为空；当前没有命令级上下文、修改记录或资源管理对象，无法证明重复加载、卸载、异常退出和并发调用安全。
8. **无测试与无版本演进记录**：仓库只有一次初始化提交，缺少测试夹具、发布产物和兼容性矩阵；后续应以 Windows 宿主实测补齐加载、命令元数据、每个参数类型、通知转发、静态链接和失败恢复验证。

## 13. Git 版本基线与证据路径

- 远程：`https://gitee.com/JYtechnology/ewizard.git`
- 当前分支：`master`
- 当前提交：`61c899273aec9eb7e5f66db4afa584c42762b845`
- 提交信息：`初始化仓库`
- 提交时间：`2022-12-19 16:55:35 +0800`
- 本地 `master` 与 `origin/master`：同为 `61c899273aec9eb7e5f66db4afa584c42762b845`。
- 工作树建档前状态：干净；当前核对新增的唯一文件为本项目根 `ARCHITECTURE.md`。
- 关键证据：`ewizard_dllMain.cpp`（库入口/登记/通知）、`ewizard_cmd_typedef.h`（命令总表）、`ewizard_cmdInfo.cpp`（参数与命令元数据）、`ewizard_cmdDef.cpp`（命令实现现状）、`ewizard_dtType.cpp`（枚举类型）、`elib/lib2.h`（ABI 结构）、`elib/fnshare.cpp`（共享通知）、`ewizard.vcxproj` 与 `ewizard_static/ewizard_static.vcxproj`（构建拓扑）、`Source_ewizard.def`（导出边界）。

本档案后续应在同一 `ARCHITECTURE.md` 内增量维护；不得再以平行“细探”文件作为事实源。
