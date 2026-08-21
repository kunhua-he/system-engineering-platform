# shell 架构档案

## 1. 项目定位

`shell` 是一个面向易语言的 Windows 操作系统界面功能支持库，项目以 C++ 封装 Windows Shell、快捷方式、文件操作、特殊目录、进程执行和系统关机/重启等能力，并通过易语言支持库 ABI 向 IDE/运行时注册命令、常量和命令实现。

项目同时提供两种构建形态：

- `shell.vcxproj`：动态库（`DynamicLibrary`），目标扩展名在 Win32 配置中为 `.fne`，通过 `GetNewInf` 返回 `LIB_INFO`。
- `shell_static/shell_static.vcxproj`：静态库（`StaticLibrary`），复用同一批实现源文件，并以 `__E_STATIC_LIB` 改变支持库信息代码和命名方式。

本档案只描述当前仓库源码、工程和 Git 现场证据；README、远程说明或未来设计不作为实现证据。仓库没有 README、AGENTS.md、测试目录或旧 `细探-*.md` 文件。

## 2. 总体流程图

```text
易语言 IDE/运行时
        │
        │ 动态加载 GetNewInf / 或静态库注册
        ▼
┌─────────────────────────────────────────────┐
│ shell 支持库 ABI 层                         │
│ shell_dllMain.cpp                           │
│ - LIB_INFO 元数据                           │
│ - 3 个命令分类、9 个命令、24 个常量         │
│ - 命令函数指针表 / ProcessNotifyLib         │
└─────────────────────────────────────────────┘
        │
        │ PMDATA_INF 参数 + pRetData 返回值
        ▼
┌─────────────────────────────────────────────┐
│ shell_cmdDef.cpp 命令适配层                 │
│ - args_to_sdata / args_to_data               │
│ - 易语言数组转 std::vector                  │
│ - char* 结果交给易语言内存分配器            │
└─────────────────────────────────────────────┘
        │
        ▼
┌────────────────────┬────────────────────────┐
│ elibshell 操作实现 │ fnshare 运行时桥接      │
│ 快捷方式/文件/Shell│ NotifySys / clone_text  │
│ /目录/电源操作     │ /数组参数解码           │
└────────────────────┴────────────────────────┘
        │
        ▼
Windows API / COM ShellLink / 文件系统 / 回收站 / 进程与电源管理
        │
        ├── BOOL/HINSTANCE：直接写入 pRetData
        └── char*：通过易语言 NotifySys(NRS_MALLOC) 分配后返回
```

## 3. 真实目录与分层

```text
shell/
├── shell.sln                         Visual Studio 解决方案
├── shell.vcxproj                     动态库工程
├── shell.vcxproj.filters/.user       动态库工程辅助文件
├── shell_static/
│   ├── shell_static.vcxproj          静态库工程
│   ├── shell_static.vcxproj.filters/.user
├── Source_shell.def                  动态库模块定义，仅列出 GetNewInf
├── include/
│   ├── include_shell_header.h        本支持库总头文件、全局表声明、命令声明
│   ├── shell_cmd_typedef.h           9 条命令的单一宏定义表与名称拼接
│   └── elib/
│       ├── lib2.h                    易语言支持库 ABI/数据结构/宏
│       ├── lang.h                    语言版本定义
│       ├── krnllib.h                 核心支持库接口依赖
│       ├── mtypes.h                  基础类型兼容定义
│       ├── fnshare.h                  参数解码、内存桥接、数组解码声明/模板
│       ├── fnshare.cpp               NotifySys、ProcessNotifyLib 状态桥实现
│       ├── untshare.h                 共享辅助类和窗口/IDE辅助函数
│       └── PublicIDEFunctions.h       IDE 公共功能常量与结构
└── src/
    ├── shell_dllMain.cpp              动态库入口、LIB_INFO、通知分发、GetNewInf
    ├── shell_cmdDef.cpp               命令实现适配器和底层函数前置声明
    ├── shell_cmdInfo.cpp              命令参数元数据和 CMD_INFO 表
    ├── shell_const.cpp                常量元数据表
    ├── shell_dtType.cpp               自定义数据类型占位表（数量为 0）
    ├── BrowseForFolder.cpp            文件夹选择
    ├── CreateLink.cpp                 创建 .lnk 快捷方式
    ├── DeleteIntoRecycleBin.cpp       删除到回收站
    ├── GetShortCutTarget.cpp          读取快捷方式目标
    ├── GetSpecialFolderPath.cpp       特殊目录路径
    ├── MyExitWindows.cpp              关机/重启/注销/休眠/冬眠
    ├── ShellCopyFile.cpp              Shell 进度复制
    ├── ShellExecute.cpp               ShellExecuteA 操作
    └── ShellMoveFile.cpp               Shell 进度移动
```

工程文件明确把 `include/elib/fnshare.cpp` 和上述 14 个 `src/*.cpp` 纳入动态库；静态库通过 `..\` 路径复用同一批源文件。仓库共 32 个 Git 跟踪文件，其中 C/C++ 源/头文件、Visual Studio 工程和 ABI 模板文件构成全部实现面。

## 4. ABI、注册与命令元数据

### 4.1 命名和注册

`include/shell_cmd_typedef.h:3-37` 使用 `SHELL_DEF(_MAKE)` 作为单一命令清单。每条记录包含索引、中文名、英文名、说明、类别、Windows 平台标志、返回类型、参数数量和参数元数据起点。当前共 9 条命令，索引为 `0..8`。

`include/include_shell_header.h:1-18` 引入 `lib2.h`、`lang.h`、`krnllib.h` 和命令表，并再次以宏展开生成所有命令函数声明。命令实现函数通过 `SHELL_EXTERN_C` 保持 C ABI；实际名称由 `SHELL_NAME` 拼接为类似 `shell_CreateShortCut_0_shell` 的符号。

动态库模式下：

1. `shell_dllMain.cpp:31-87` 构造 `LIB_INFO`。
2. `shell_dllMain.cpp:89-94` 的 `GetNewInf` 返回该结构。
3. `Source_shell.def:1-4` 只显式导出 `GetNewInf`。
4. `LIB_INFO.m_pBeginCmdInfo` 指向 `g_cmdInfo_shell_global_var`，`m_pCmdsFunc` 指向由 `SHELL_DEF` 生成的函数指针数组。

静态库模式下，`shell_static.vcxproj:108-181` 通过 `__E_STATIC_LIB` 编译；动态库专属的 `DllMain`、`LIB_INFO`、命令/常量/自定义数据类型元数据表受条件编译排除，但命令函数仍由同一批实现源提供。`shell_ProcessNotifyLib_shell` 中的静态编译相关通知代码则被 `#ifndef __E_STATIC_LIB` 排除。

### 4.2 支持库元数据

`shell_dllMain.cpp:31-87` 的已实现元数据如下：

| 项目 | 当前值 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（定义于 `include/elib/lib2.h:1317` 附近） |
| GUID | `52F260023059454187AF826A3C07AF2A` |
| 版本 | `3.0.0` |
| 所需易语言系统 | `3.0` |
| 所需核心支持库 | `3.0` |
| 中文名 | `操作系统界面功能支持库` |
| 说明 | `本支持库封装了Windows操作系统用户界面中的常用功能` |
| 目标平台状态 | `_LIB_OS(OS_ALL)`，但所有命令记录均是 `_CMD_OS(__OS_WIN)` |
| 分类 | `快捷方式操作`、`文件操作`、`杂类` |
| 自定义数据类型 | 0（`src/shell_dtType.cpp:3-7`） |
| AddIn / SuperTemplate | 未提供（均为 `NULL`） |
| 依赖文件列表 | `NULL`；静态通知中返回空双零字符串 |

这里“库级状态为 `OS_ALL`”与“9 个命令均为 Windows”同时存在；应以具体命令的 `_CMD_OS(__OS_WIN)` 为能力边界，不能据此宣称底层实现跨平台。

### 4.3 命令清单

以下是 `include/shell_cmd_typedef.h:10-36` 的注册定义与 `src/shell_cmdDef.cpp` 的实现映射。状态“已实现”仅表示源码中存在调用链，不表示本机已运行验证。

| 索引 | 易语言命令 | 返回 | 参数摘要 | 底层实现 | 状态 |
|---:|---|---|---|---|---|
| 0 | `创建快捷方式` / `CreateShortCut` | `SDT_BOOL` | 名称、目标路径、备注、命令行、工作目录、可选热键 | `CreateLink` → `IShellLinkA`/`IPersistFile` | 已实现，未运行验证 |
| 1 | `查询快捷方式` / `GetShortCut` | `SDT_TEXT` | 快捷方式路径 | `GetShortCutTarget` → `SHGetFileInfoA`、COM ShellLink | 已实现，未运行验证 |
| 2 | `浏览文件夹` / `BrowseForFolder` | `SDT_TEXT` | 标题、是否包含文件、可选窗口句柄 | `BrowseForFolder` → `SHBrowseForFolderA` | 已实现，未运行验证 |
| 3 | `删除到回收站` / `DeleteIntoRecycleBin` | `SDT_BOOL` | 删除选项、文件/目录数组或单值 | `DeleteIntoRecycleBin` → `SHFileOperationA(FO_DELETE)` | 已实现，未运行验证 |
| 4 | `进度复制文件` / `ShellCopyFile` | `SDT_BOOL` | 目标目录、文件/目录数组或单值 | `ShellCopyFiles` → `SHFileOperationA(FO_COPY)` | 已实现，未运行验证 |
| 5 | `进度移动文件` / `ShellMoveFile` | `SDT_BOOL` | 目标目录、文件/目录数组或单值 | `ShellMoveFiles` → `SHFileOperationA(FO_MOVE)` | 已实现，未运行验证 |
| 6 | `执行` / `ShellExecuteW`（运行时改显示名为 `ShellExecute`） | `_SDT_NULL`，适配器写布尔成功标志 | 命令类型、文件名、命令行、当前目录、显示模式 | `MyShellExecute` → `ShellExecuteA` | 已实现，未运行验证；命名有兼容改写 |
| 7 | `取特定目录` / `GetSpecialFolderPath` | `SDT_TEXT` | 目录类型 1..11 | `GetSpecialFolderPath` → `SHGetSpecialFolderPathA`/系统目录 API | 已实现，未运行验证 |
| 8 | `关闭系统` / `ExitWindows` | `SDT_BOOL` | 关闭方式、是否强制 | `MyExitWindows` → `ExitWindowsEx`/`SetSystemPowerState` | 已实现，未运行验证；有高风险副作用 |

### 4.4 参数数据模型

`src/shell_cmdInfo.cpp:5-58` 建立 `ARG_INFO g_argumentInfo_shell_global_var[]`。实际表包含索引 `0..29` 的 30 个参数槽位：

- `0..4`：创建快捷方式的名称、路径、备注、命令行、工作目录；
- `5..6`：浏览标题、是否显示文件；
- `7..8`：删除选项、待删除文件；
- `9..10`：复制目标目录、源文件；
- `11..12`：移动目标目录、源文件；
- `13..17`：执行命令类型、文件名、命令行、当前目录、显示模式；
- `18`：特殊目录类型；
- `19..20`：关闭方式、强制执行；
- `21..26`：创建快捷方式的另一套参数描述（包含热键）；
- `27..29`：浏览文件夹标题、是否包含文件、窗口句柄。

`SHELL_DEF` 使用的参数起点分别为 `+21`、`+0`、`+27`、`+7`、`+9`、`+11`、`+13`、`+18`、`+19`。因此参数表前半段存在与后半段重复的描述，属于当前 ABI 元数据布局，不应在后续文档中简化为只有 21 个槽位。

`include/elib/fnshare.h:26-70` 的 `args_to_data`/`args_to_sdata` 将 `PMDATA_INF` 映射为基础值或 `std::string_view`；`_SDT_NULL` 返回 `std::optional` 空值。数组参数由 `get_array_element_inf`（同文件 `214-247`）读取易语言数组的维数、各维长度和元素区，文本数组转为 `std::vector<std::string_view>`。

## 5. 各模块职责与真实调用链

### 5.1 快捷方式

```text
shell_CreateShortCut_0_shell
  → args_to_sdata / args_to_data<DWORD>
  → CreateLink
  → CoCreateInstance(CLSID_ShellLink)
  → QueryInterface(IID_IPersistFile)
  → SetPath / SetDescription / SetArguments / SetHotkey / SetWorkingDirectory
  → MultiByteToWideChar
  → IPersistFile::Save(..., TRUE)
  → BOOL 写入 pRetData->m_bool
```

证据：`src/shell_cmdDef.cpp:35-45`、`src/CreateLink.cpp:6-32`。

`CreateLink` 在名称无任何 `.` 时追加 `.lnk`，并非只检查扩展名位置；名称带任意点号都会被原样使用。源码未显式调用 `CoInitialize`/`CoUninitialize`，COM 初始化责任未在本仓库确认。

查询链：

```text
shell_GetShortCut_1_shell
  → GetShortCutTarget
  → SHGetFileInfoA(..., SHGFI_ATTRIBUTES)
  → 检查 SFGAO_LINK
  → CoCreateInstance(CLSID_ShellLink)
  → IPersistFile::Load(STGM_READ)
  → IShellLinkA::GetPath
  → clone_text
  → pRetData->m_pText
```

证据：`src/shell_cmdDef.cpp:48-52`、`src/GetShortCutTarget.cpp:5-33`。

### 5.2 文件选择、删除、复制、移动

`BrowseForFolder` 使用 `BROWSEINFOA`、`BIF_EDITBOX`，可选 `BIF_BROWSEINCLUDEFILES`，无效父窗口时回退到 `GetActiveWindow`；选中后用 `SHGetPathFromIDListA` 取路径，并用 `SHGetMalloc` 释放 `LPITEMIDLIST`。证据：`src/BrowseForFolder.cpp:5-30`。

删除、复制、移动都使用 `SHFILEOPSTRUCTA`，源路径采用“每个路径一个 NUL，整个列表末尾再追加一个 NUL”的 Windows 多字符串格式，并设置 `FOF_ALLOWUNDO`：

- 删除：`src/DeleteIntoRecycleBin.cpp:33-55`，根据位标志 `1/2/4` 加入 `FOF_NOCONFIRMATION`、`FOF_NOERRORUI`、`FOF_SILENT`；
- 复制：`src/ShellCopyFile.cpp:33-55`，`FO_COPY`；
- 移动：`src/ShellMoveFile.cpp:5-29`，`FO_MOVE`。

适配器 `shell_cmdDef.cpp:68-96` 对追加参数逐项调用底层函数；底层函数本身又接受 vector。因此源码支持数组，但多参数调用时每个参数会触发一次 Windows 操作，且 `pRetData->m_bool` 最终反映最后一次调用结果。此行为是已实现事实，不应描述为一个统一事务。

### 5.3 执行命令

`src/ShellExecute.cpp:5-32` 将显示模式 `1..6` 映射为 `SW_HIDE`、`SW_SHOWNORMAL`、`SW_SHOWMINIMIZED`、`SW_SHOWMAXIMIZED`、`SW_SHOWNA`、`SW_MINIMIZE`；命令类型 `1..4` 映射为 `edit`、`explore`、`find`、`open`，类型 `5` 为 `print`，其他值传空操作名以使用系统默认行为。

`src/shell_cmdDef.cpp:105-113` 使用默认命令类型 4、默认显示模式 2，并将 `MyShellExecute` 返回的 `HINSTANCE` 整数值与 32 比较后写入 `pRetData->m_bool`。虽然注册返回类型是 `_SDT_NULL`，适配器实际产生了布尔结果，属于 ABI/实现不完全一致的风险点。

`GetNewInf` 在 `src/shell_dllMain.cpp:89-93` 将第 7 个命令（索引 6）的英文显示名从宏生成的 `ShellExecuteW` 改写为 `ShellExecute`；静态通知 `NL_GET_CMD_FUNC_NAMES` 又把实现名指定为 `shell_ShellExecuteW_6_shell`（`src/shell_dllMain.cpp:108-115`）。这是当前源码明确存在的兼容层。

### 5.4 特殊目录

`src/GetSpecialFolderPath.cpp:17-48` 支持 11 类：

1. `CSIDL_PERSONAL`；2. `CSIDL_FAVORITES`；3. `CSIDL_DESKTOPDIRECTORY`；4. `CSIDL_FONTS`；5. `CSIDL_STARTMENU`；6. `CSIDL_PROGRAMS`；7. `CSIDL_STARTUP`；8. `CSIDL_APPDATA`；9. `GetWindowsDirectoryA`；10. `GetSystemDirectoryA`；11. `GetTempPathA`。

成功时保证末尾有 `\\`，然后通过 `clone_text` 以易语言分配器返回；类型不在 `1..11` 时返回空指针。

### 5.5 系统电源

`src/MyExitWindows.cpp:5-28` 尝试打开当前进程令牌并启用 `SE_SHUTDOWN_NAME`；`MyExitWindows` 对类型做 `1..5` 校验：

- `1`：根据 Windows NT 平台选择 `EWX_POWEROFF` 或 `EWX_SHUTDOWN`；
- `2`：`EWX_REBOOT`；
- `3`：`EWX_LOGOFF`；
- `4`：`SetSystemPowerState(TRUE, force)`；
- `5`：`SetSystemPowerState(FALSE, force)`；
- `force=true` 时加入 `EWX_FORCE`。

这是直接改变系统状态的高副作用能力。本仓库无权限、模拟、回滚或测试保护层，不能在当前 macOS 环境验证，也不应在未明确授权的 Windows 环境自动调用。

## 6. 运行时内存与通知模型

`include/elib/fnshare.cpp:9-17` 保存两个进程内函数指针：`s_pfnNotifySys` 和用户通知指针 `s_pfnuserNotifySys`。`NotifySys` 仅在系统通知指针非空时转发消息；`ProcessNotifyLib` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时把 `dwParam1` 解释为 `PFN_NOTIFY_SYS`，并在末尾转发给用户回调（如已设置）。

返回文本的所有权通过 `clone_text` 处理，而非 C++ `new`：

```text
Windows 临时 char/wchar 数据
  → clone_text
  → NotifySys(NRS_MALLOC, size, 0)
  → 拷贝并补 NUL
  → pRetData->m_pText
  → 由易语言运行时负责后续释放（源码未提供释放调用点）
```

`fnshare.h:78-129` 同时提供文本、宽文本、字节集复制；当前 shell 命令实际使用的是文本 `clone_text`。数组只保存 `std::string_view`，底层操作执行期间依赖 `PMDATA_INF` 输入缓冲区仍有效，源码没有跨调用缓存这些视图。

## 7. 数据模型与持久化

本项目没有数据库、配置文件、磁盘索引、缓存目录或业务持久化模型。可称为“数据模型”的部分只有易语言支持库注册结构和一次调用期内的参数/返回值：

| 模型 | 位置 | 内容 | 持久化 |
|---|---|---|---|
| `LIB_INFO` | `src/shell_dllMain.cpp:31-87` / `include/elib/lib2.h:1248-1315` | 库版本、GUID、名称、平台、分类、命令表、函数表、常量表、通知函数 | 否，静态进程数据 |
| `CMD_INFO` | `src/shell_cmdInfo.cpp:65-75` | 命令中文/英文名、说明、类别、返回类型、参数范围 | 否 |
| `ARG_INFO` | `src/shell_cmdInfo.cpp:5-58` | 参数名称、类型、默认/可空标志、数组接收标志 | 否 |
| `LIB_CONST_INFO` | `src/shell_const.cpp:4-42` | 24 个数值常量 | 否 |
| `MDATA_INF` | `include/elib/lib2.h:763-823` | 易语言调用期数据描述，由宿主传入/接收 | 否，调用期 |
| Windows Shell 状态 | Windows API | 文件、快捷方式、回收站、电源状态 | 由外部 Windows 系统产生，本库不维护事务记录 |

## 8. 依赖边界

### 已由源码直接确认

- Windows SDK：`windows.h`、`shlobj.h`、Win32 Shell API、文件操作 API、进程令牌和电源 API；
- COM：`CLSID_ShellLink`、`IShellLinkA`、`IPersistFile`；
- C++ 标准库：`string`、`string_view`、`vector`、`optional`、`stdexcept`、`cstring` 等；
- 易语言支持库 ABI：仓库内 `include/elib/lib2.h`、`lang.h`、`krnllib.h`、`mtypes.h`、`fnshare.h`；
- Visual Studio/MSBuild 工具链：工程设置为 `PlatformToolset v142`、`WindowsTargetPlatformVersion 10.0`、C++17（Win32 配置明确设置）。

### 工程声明但未在当前环境验证

- `shell.vcxproj` 与静态库工程声明的 Win32/x64、Debug/Release 四组配置；
- `Source_shell.def` 的动态库 `GetNewInf` 导出；
- 易语言宿主对 `PMDATA_INF`、`NotifySys` 内存释放和通知消息的真实 ABI 行为。

没有发现第三方包管理文件、NuGet/CMake/Conan/vcpkg 配置，也没有仓库内运行时 DLL、`.fne`、`.lib` 或测试夹具。

## 9. 工程构建基线与配置风险

`shell.sln:10-32` 声明 `Debug|x64`、`Debug|x86`、`Release|x64`、`Release|x86`；x86 映射到工程的 `Win32`，x64 映射到 `x64`。两个工程均声明动态/静态目标和 `v142` 工具集。

已从工程文件确认的配置差异：

- 动态库 Win32 Debug/Release 设置 `TargetExt=.fne`、`OutDir=$(SolutionDir)$(Platform)\\$(Configuration)\\`、`IntDir=$(SolutionDir)build\\$(ProjectName)\\$(Platform)\\$(Configuration)\\`，并指定 `Source_shell.def`；
- 动态库 x64 配置没有出现与 Win32 相同的 `TargetExt`、`OutDir`、`IntDir`、`ModuleDefinitionFile` 和 `__E_FNENAME=shell` 定义；
- 静态库 Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=shell`，x64 配置的预处理定义只出现 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，且 x64 使用 `PrecompiledHeader=Use`，工程文件未列出 `pch.h`；
- 工程没有定义 PostBuildEvent 内容，也没有复制/安装/部署步骤。

这些是工程静态审查发现的配置差异，尚未在 Windows/MSBuild 上复现其最终失败或成功结果，不能写成“已确认无法构建”。

## 10. 测试与验证现状

### 仓库内测试

未发现 `test`、`tests`、`unittest`、`catch2`、`gtest`、CTest 或其他测试目标；Visual Studio 工程也未声明测试项目。因而：

- “源码中存在实现”是已确认事实；
- “命令在 Windows 上可运行”是未验证；
- “工程可在所有四种配置构建”是未验证；
- “文件复制/删除/移动、COM 快捷方式和电源操作行为正确”是未验证。

### 本轮实际验证

本轮只读读取并核对了源码、头文件、两个工程、解决方案、模块定义文件和 Git 基线；没有安装依赖、没有启动 Windows 程序、没有生成构建产物、没有调用会修改文件/回收站/系统电源的 API。当前执行环境为 macOS，无法直接运行 Windows SDK/MSVC 构建。

建议后续在隔离 Windows 测试机补充：

1. `GetNewInf` 加载、9 条命令注册数量与函数指针顺序；
2. 动态库 Win32/x64 和静态库 Win32/x64 的 MSBuild 构建；
3. 快捷方式创建/读取与 Unicode、无扩展名、多点号路径；
4. 单文件、目录、通配符、多文件数组的复制/移动/回收站行为；
5. `ShellExecute` 的命令类型、显示模式、失败码；
6. 特殊目录 1..11 与尾部反斜杠；
7. 令牌权限不足时的 `ExitWindows` 失败行为（不得在非测试环境执行电源调用）；
8. `NotifySys` 分配文本的宿主释放和跨位数 ABI。

## 11. 已实现 / 仅声明 / 未验证边界

### 已实现（源码存在直接调用链）

- 动态库 `DllMain` 空生命周期入口；
- `GetNewInf` 返回 `LIB_INFO`；
- 9 条命令的命令适配器和底层 Windows API 调用；
- 24 个常量的元数据；
- 3 个命令分类；
- `NotifySys` / `ProcessNotifyLib` 的基本函数指针桥接；
- 文本返回值通过宿主内存分配器复制；
- 静态库复用源文件并通过宏生成冲突规避命名。

### 仅声明或占位

- `shell_dtType.cpp` 的自定义数据类型数组存在，但数量为 0，没有自定义类型；
- `m_pfnRunAddInFn`、`m_pfnSuperTemplate`、对应描述均为 `NULL`；
- `PublicIDEFunctions.h`、`untshare.h` 提供大量通用 IDE/窗口辅助声明和实现，但本 shell 命令未建立实际调用链；
- `fnshare.cpp` 的 `s_pfnuserNotifySys` 仅提供 `SetUserSysNotify`，本项目未发现调用点；
- `Source_shell.def` 只声明 `GetNewInf` 导出，其他命令的可见性依赖函数表/链接方式，不应假设其为模块级导出。

### 未验证

- Windows 下 MSVC v142 实际编译、链接和装载；
- x64 工程配置中缺失项是否由用户属性表或外部环境补齐；
- COM 初始化、易语言宿主 ABI、内存回收和通知消息的真实运行行为；
- 所有文件系统、回收站、快捷方式和电源副作用行为。

## 12. 代码风险与后续复核点

1. `DeleteIntoRecycleBin` 在空路径列表时初始返回 `TRUE`；`ShellMoveFiles` 在输入为空时也初始返回 `TRUE`，与失败语义不一致。证据：`src/DeleteIntoRecycleBin.cpp:35-37`、`src/ShellMoveFile.cpp:7-9`。
2. `shell_cmdDef.cpp:68-94` 在循环中反复覆盖 `pRetData->m_bool`，多参数场景只保留最后一次底层操作结果。
3. `CreateLink` 仅用 `strchr(LinkName.data(), '.')` 判断是否追加 `.lnk`，且未检查 `SetPath` 等中间 COM 调用返回值。证据：`src/CreateLink.cpp:18-27`。
4. 多处底层 API 使用 ANSI 版本（`SHFileOperationA`、`ShellExecuteA`、`SHGetSpecialFolderPathA`、`IShellLinkA`），中文和非系统代码页路径的行为需要 Windows 实测。
5. `GetShortCutTarget`、`CreateLink` 使用 COM，但源码没有显示 COM apartment 初始化/反初始化；需确认宿主契约或补充隔离测试。
6. `MyExitWindows` 依赖过时的 `GetVersionEx` 和 `SetSystemPowerState`，同时具有系统级破坏性副作用，需单独权限与安全审查。
7. `shell_dllMain.cpp:47` 的库级平台标志为 `OS_ALL`，而命令级标志为 Windows；需要确认易语言 IDE 对两级平台声明的筛选优先级。
8. `src/shell_dllMain.cpp:92` 修改全局命令元数据中的英文名，`GetNewInf` 重复调用的幂等性目前看似成立，但没有专门测试。
9. `fnshare.h:57` 通过 `reinterpret_cast<T>` 从 `m_pCompoundData` 读取多种类型，属于强 ABI 假设；位数、对齐、调用宿主结构必须用 Windows 实测确认。
10. 工程 x64 配置与 Win32 配置在预处理宏、模块定义、输出扩展名和预编译头设置上不一致；在宣布 x64 支持前必须实际构建。

## 13. Git 基线与证据路径

- 仓库根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/shell`
- 远程：`origin https://gitee.com/JYtechnology/shell.git`
- 分支：`master`，跟踪 `origin/master`
- 本地 HEAD：`cc6b49a971953841ac10d4654ffe760c85b478b3`
- 远程 `HEAD` / `refs/heads/master`：`cc6b49a971953841ac10d4654ffe760c85b478b3`，本地与远程同提交
- 提交时间：`2023-01-06T08:46:41Z`
- 提交主题：`!1 shell Merge pull request !1 from AlongsCode/master`
- 本轮开始时工作树：干净；本轮只新增/更新本文件
- 旧细探：未发现 `细探-*.md`

关键证据索引：

| 主题 | 证据 |
|---|---|
| 解决方案与四种配置 | `shell.sln:1-40` |
| 动态库源文件、Win32/x64 配置 | `shell.vcxproj:21-216` |
| 静态库源文件与 `__E_STATIC_LIB` | `shell_static/shell_static.vcxproj:21-184` |
| 动态库导出 | `Source_shell.def:1-4` |
| 命令总表 | `include/shell_cmd_typedef.h:3-37` |
| 命令/参数元数据 | `src/shell_cmdInfo.cpp:5-78` |
| 命令适配器 | `src/shell_cmdDef.cpp:1-126` |
| 支持库信息/通知 | `src/shell_dllMain.cpp:1-184` |
| 常量 | `src/shell_const.cpp:1-43` |
| 自定义类型数量 | `src/shell_dtType.cpp:1-13` |
| ABI 和 `LIB_INFO` | `include/elib/lib2.h:1-43`、`include/elib/lib2.h:1238-1329` |
| 参数、数组、宿主内存桥 | `include/elib/fnshare.h:19-247` |
| 通知函数指针状态 | `include/elib/fnshare.cpp:7-64` |
| Windows 具体能力 | `src/BrowseForFolder.cpp`、`src/CreateLink.cpp`、`src/DeleteIntoRecycleBin.cpp`、`src/GetShortCutTarget.cpp`、`src/GetSpecialFolderPath.cpp`、`src/MyExitWindows.cpp`、`src/ShellCopyFile.cpp`、`src/ShellExecute.cpp`、`src/ShellMoveFile.cpp`

本文件是该项目的首轮架构事实源；后续细探应增量更新本文件，不创建平行架构结论文档。