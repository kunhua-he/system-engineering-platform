# BlackMoonKernelStaticLib 架构档案

> 本文件是本项目唯一的架构归档文件。本文档已按当前源码、工程文件、CI 配置和远程版本复核；没有发现旧 `历史研究-*.md` 文件。后续历史研究直接增量维护本文件，不另建平行事实源。

## 1. 项目定位

`BlackMoonKernelStaticLib` 是面向易语言黑月编译器/运行环境的 Windows 核心支持库源码。仓库主要产出 `kernel.lib` 所需的核心静态库，同时保留两个适配形态：

- `krnln`：主核心静态库，聚合易语言原生核心命令、运行时内存/错误/通知桥接、文件/内存文件、COM/OLE、DLL、媒体、日期时间、文本/字节集、数值和系统功能。
- `krnln_Obj`：对象/程序入口相关的静态库目标，包含 `BlackMoonDll.cpp`、`BlackMoonDll2.cpp`、`BlackMoonExe.cpp`、`BlackMoonResDll.cpp`、`EyComInit.cpp`、`EyInit.cpp`。
- `MFCBlackMoon`：MFC 动态库目标，为 MFC DLL/应用入口提供 `CWinApp` 封装，并复用 `E_Init`、`E_DestroyRes`、`DllEntryFunc` 和 `ECodeStart`。

源码以 C++/Win32 API 为基础，接口目标是保持与易语言原生核心库的参数、返回值和运行效果一致。README 说明编译后的 `kernel.lib` 应替换易语言安装目录 `\\BlackMoon\\obj\\kernel.lib`（黑月 4.0 以上）或 `\\BlackMoon\\lib\\kernel.lib`（黑月 4.0 以下）。

## 2. 总体流程

```text
易语言用户程序/黑月运行环境
        │
        ├─ 加载支持库/静态链接 kernel.lib
        │       │
        │       ├─ krnln 命令入口：LIBAPI(_cdecl)(nArgCount, MDATA_INF ArgInf,...)
        │       │       ├─ 数值/字符串/字节集/日期时间命令
        │       │       ├─ 文件、目录、注册表、剪贴板、窗口、网络、媒体、COM/OLE
        │       │       └─ Variant/Dispatch、数组、DLL 和控制台能力
        │       │
        │       ├─ 运行时桥接：BlackMoonFuncForeLibNotifySys / NotifySys
        │       │       ├─ NRS_MALLOC / NRS_MFREE / NRS_MREALLOC
        │       │       ├─ NRS_FREE_ARY / NRS_RUNTIME_ERR / NRS_EXIT_PROGRAM
        │       │       ├─ NAS_GET_PATH / NAS_GET_VER / NRS_GET_CMD_LINE_STR
        │       │       └─ 窗口单元、事件和 COM 对象通知
        │       │
        │       └─ 外部支持库链：BlackMoonCalleLibList
        │               ├─ BlackMoonInitAllElib：NL_SYS_NOTIFY_FUNCTION
        │               └─ BlackMoonFreeAllElib：NL_FREE_LIB_DATA + 用户 DLL 释放
        │
        ├─ 对象/EXE/DLL 入口（krnln_Obj）
        │       ├─ DllMain → E_Init → DllEntryFunc → ECodeStart → DestroyAddress
        │       ├─ EDllMain 转发（BlackMoonDll2.cpp）
        │       └─ BMEntrypoint / WinMain / main → E_Init → ECodeStart
        │
        └─ MFCBlackMoon 动态库
                ├─ CMFCBlackMoonDLLApp::InitInstance
                │       → E_Init → DllEntryFunc → DestroyAddress
                └─ ExitInstance → E_DestroyRes → 外部库/文件/媒体/入口资源释放
```

## 3. 真实目录地图

| 路径 | 真实职责 |
|---|---|
| `krnln/` | 核心 C++ 源码、易语言 ABI 头文件、命令实现、运行时桥接和内部资源管理。仓库盘点为 249 个 `.cpp`、13 个 `.h`，另有已提交的 `Diskid32.obj`、`PY.OBJ` 等二进制对象。 |
| `krnln/lib.h` | 易语言支持库 ABI 的旧/主定义：`DATA_TYPE`、`ARG_INFO`、`CMD_INFO`、`MDATA_INF`、通知码和 `LIB_INFO`。 |
| `krnln/lib2.h` | 兼容版本/实现侧 ABI 定义，包含 `MDATA_INF`、事件通知、`LIB_INFO` 和 `GetNewInf` 契约。 |
| `krnln/StdAfx.h` | Win32 基础包含、`lib2.h`、`LIBAPI` 宏、运行时生命周期/内存/数组/日期/文件管理声明。 |
| `krnln/krnln_*.cpp` | 以易语言原生命令英文名命名的命令实现，覆盖算术、文本、字节集、文件、日期、系统、窗口、网络、媒体和 Variant 等。 |
| `krnln/DllEntryFunc.cpp` | `DllEntryFunc`：保护寄存器后调用外部 `ECodeStart`，把返回值作为 `PDESTROY` 保存。 |
| `krnln/eHelpFunc.cpp` | `E_MAlloc`/`E_MFree`/`E_Destroy`/`E_End`/`E_ReportError`、数组复制、外部支持库通知链和 `BlackMoonCalleLibFunctionHelper`。 |
| `krnln/EyInit.cpp` | 非 COM 初始化变体：获取进程堆、`BlackMoonInitAllElib`；释放入口、文件、MIDI 和外部库。 |
| `krnln/EyComInit.cpp` | COM 初始化变体：在 `EyInit.cpp` 流程基础上调用 `CoInitialize(0)`，释放时调用 `CoUninitialize()`。 |
| `krnln/BlackMoonLibNotifySys.cpp` | `BlackMoonFuncForeLibNotifySys`/`NotifySys` 系统通知总线，负责内存、运行时错误、退出、路径、命令行、版本及若干窗口/事件通知。 |
| `krnln/FileManager.cpp`、`MyMemFile.*` | 文件句柄登记链、临界区保护、文件/内存文件释放和 `CMyMemFile` 的可增长缓冲区读写/定位。 |
| `krnln/Myfunctions.*`、`mem.*`、`md5t.*`、`midi.*` | 性能字符串/字节集辅助、内存/MD5/音频 MIDI 辅助。`Myfunctions.cpp` 含 SSE2 检测及内联汇编优化路径。 |
| `MFCObj/` | MFC 应用/DLL 外壳、资源和 `CWinApp` 生命周期。 |
| `Project/` | VS2019 `.vcxproj`、VS6 `.dsp/.dsw`、filters/user 文件。 |
| `.github/workflows/` | `blackmoon_krnln.yml`、`blackmoon_krnlnobj.yml`、`blackmoon_mfc.yml` 三组 Windows GitHub Actions 构建检查。 |

## 4. 构建目标与依赖边界

### 4.1 工程目标

- `Project/krnln_VS2019.vcxproj`：`StaticLibrary`，`TargetName=krnln`，VS `v142`，Win32/x64、Debug/Release；主工程在当前配置中编译 238 个 `.cpp`。
- `Project/krnln_VS2019_Obj.vcxproj`：`StaticLibrary`，`TargetName=krnln`，VS `v142`，Win32/x64、Debug/Release；只编译入口/对象相关 6 个 `.cpp`。
- `Project/MFCBlackMoon_VS2019.vcxproj`：`DynamicLibrary`，VS `v142`，Win32/x64，Debug/Release/ReleaseDll；编译 `MFCObj/` 下 5 个 `.cpp`，输出目录配置为 `$(SolutionDir)Release`。
- `krnln_VC6.dsw` 及 `Project/*_VC6.dsp`：保留的 Visual C++ 6 兼容工程入口。

### 4.2 外部依赖

- Windows SDK/Win32：`windows.h`、进程堆、文件、注册表、剪贴板、窗口、进程、网络和系统路径 API。
- Windows 链接库由 `krnln/BlackMoonLibNotifySys.cpp` 通过 `#pragma comment(lib, ...)` 声明：`gdi32.lib`、`winspool.lib`、`comdlg32.lib`、`advapi32.lib`、`shell32.lib`、`ole32.lib`、`oleaut32.lib`、`uuid.lib`、`odbc32.lib`、`odbccp32.lib`。
- MFC：`MFCObj/` 使用 `CWinApp`、消息映射和 `nafxcw.lib`。
- C/C++ 运行库：工程 Release/Debug 配置使用静态运行库选项（主目标可见 `MultiThreaded`/`MultiThreadedDebug`）。
- 易语言运行时/IDE：由 `lib.h`/`lib2.h` 定义 ABI 和通知码；`ECodeStart`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_SYS` 等由宿主或外部支持库提供。
- 不存在 package manager、第三方源码依赖或运行时数据库；工程文件引用的源文件均位于本仓库。

## 5. 核心数据模型与内存所有权

### 5.1 易语言 ABI 数据

`lib.h`/`lib2.h` 定义 `DATA_TYPE` 及其系统类型：`SDT_BYTE`、`SDT_SHORT`、`SDT_INT`、`SDT_INT64`、`SDT_FLOAT`、`SDT_DOUBLE`、`SDT_BOOL`、`SDT_DATE_TIME`、`SDT_TEXT`、`SDT_BIN`、`SDT_SUB_PTR`；`DT_IS_ARY` 标记数组数据，另区分系统、用户和支持库数据类型。

`MDATA_INF` 采用一字节对齐，核心字段是联合体值/指针加 `m_dtDataType`。数值使用 `m_byte`/`m_short`/`m_int`/`m_int64`/`m_float`/`m_double`/`m_date`/`m_bool`；文本和字节集使用 `m_pText`/`m_pBin`；变量/数组/复合类型使用对应指针字段。`LIBAPI(rType, fnName)` 将每个命令统一暴露为：

```text
extern "C" rType _cdecl fnName(INT nArgCount, MDATA_INF ArgInf, ...)
```

命令通过 `ArgInf` 读取参数并把结果写入 ABI 约定的寄存器/结构字段；例如 `krnln_abs` 直接修改 `ArgInf.m_double`，`krnln_open` 返回文件对象指针。

### 5.2 数组、文件和内存文件

- 易语言数组数据头部保存维数和各维元素数；`GetAryElementInf` 计算元素总数并返回数据区，`E_CloneConstArray` 在必要时复制常量区数组。
- `FILEELEMENT` 保存 `nType`、`FileHandle`、链表后继 `pLast`、加密/MD5 相关缓冲。类型 1/3 由 Windows `HANDLE` 管理，类型 2 由 `CMyMemFile` 管理。
- `FileManager.cpp` 通过 `CRITICAL_SECTION csFileMan` 保护全局 `pFileList`；`AddFileMangerList` 登记，`CloseEfile` 单个释放，`ResetFileIO` 全量释放并清空 `HFileDestroyAddress`。
- `CMyMemFile` 维护 `m_lpBuffer`、`m_nBufferSize`、`m_nFileSize`、`m_nPosition`、`m_nGrowBytes` 和 `m_bAutoDelete`，实现 `Read`、`Write`、`Seek`、`SetLength`、`GetBufferPtr`、`Close`；自有缓冲区由 `malloc/realloc/free` 管理，外部缓冲区通过 `Attach/Detach` 借用。

### 5.3 统一释放原则

与易语言程序交互的数据由 `NotifySys(NRS_MALLOC/NRS_MFREE/NRS_MREALLOC/NRS_FREE_ARY)` 管理；`E_MAlloc` 使用进程堆并在失败时报告错误/退出，`E_MAlloc_Nzero` 使用非清零堆分配。文本、字节集、数组和复合数据不能直接用不匹配的分配器释放。全局销毁指针包括 `DestroyAddress`、`HFileDestroyAddress`、`DestroyMidiPlayer` 和 `BlackMoonFreeAllUserDll`。

## 6. 真实初始化、调用与销毁链

### 6.1 静态库命令调用

1. 宿主按 `LIB_INFO`/`CMD_INFO` 元数据识别命令和参数类型。
2. 进入对应 `krnln_*.cpp` 的 `LIBAPI` 函数，例如 `krnln_abs`、`krnln_open`、`krnln_GetCmdLine`、`krnln_DispGetProperty`、`krnln_VariantGetText`。
3. 命令通过 Win32、C 运行库、内部辅助对象或 `NotifySys` 完成功能。
4. 文本、字节集、数组结果通过易语言分配/释放协议返回；错误通过 `E_ReportError`、`fnEError_callback`、消息框或 `E_End` 处理。

### 6.2 运行时初始化

```text
E_Init
  → hBlackMoonHeap = GetProcessHeap()
  → [EyComInit.cpp 变体额外 CoInitialize(0)]
  → BlackMoonInitAllElib
      → 遍历 BlackMoonCalleLibList
      → 各外部支持库接收 NL_SYS_NOTIFY_FUNCTION

E_DestroyRes
  → DestroyAddress()
  → HFileDestroyAddress()
  → DestroyMidiPlayer()
  → BlackMoonFreeAllElib
      → 各外部支持库接收 NL_FREE_LIB_DATA
      → BlackMoonFreeAllUserDll()
  → [EyComInit.cpp 变体额外 CoUninitialize()]
```

### 6.3 DLL/EXE/MFC 入口

- `BlackMoonDll.cpp::DllMain`：进程附加时设置 `hBlackMoonInstanceHandle`，执行 `E_Init()`，再调用 `DllEntryFunc()`；分离时 `E_DestroyRes()`。
- `BlackMoonDll2.cpp::DllMain`：同样初始化，但最终转发至外部 `EDllMain`。
- `BlackMoonExe.cpp::BMEntrypoint`、`WinMain`、`main`：初始化后调用外部 `ECodeStart`；入口保存 `nBMProtectESP/nBMProtectEBP`，供 `E_End` 恢复栈并返回/退出。
- `MFCObj/BlackMoonMFCdll.cpp::CMFCBlackMoonDLLApp::InitInstance`：设置实例句柄，调用 `E_Init` 和 `DllEntryFunc`；`ExitInstance` 调用 `E_DestroyRes`。`MFCBlackMoon.cpp` 和 `MFCBlackMoonCon.cpp` 提供 MFC 应用/控制台入口并调用 `ECodeStart`。

## 7. API、CLI、插件和协议边界

本项目没有 HTTP API、命令行 CLI、脚本插件协议或数据库接口；其主要边界是易语言支持库 ABI 和 Windows DLL/静态链接边界：

- 固定宿主导出/调用符号：`GetNewInf`（`FUNCNAME_GET_LIB_INFO`）、`LIBAPI` 命令入口、`DllMain`、`EDllMain`、`BMEntrypoint`、`NotifySys`、`BlackMoonFuncForeLibNotifySys`。
- 运行时函数：`E_Init`、`E_DestroyRes`、`E_End`、`E_ReportError`、`E_MAlloc`、`E_MAlloc_Nzero`、`E_MRealloc`、`E_MFree`、`E_Destroy`、`E_NULLARRAY`。
- 动态库调用：`BlackMoonCallUserDllFunc` 使用 `GetModuleHandle`/`LoadLibrary`/`GetProcAddress`，支持名称和 `#序号`，失败时回调 `fnEError_callback` 或显示错误后 `E_End(0)`。
- 外部支持库桥接：`BlackMoonCalleLibList` 保存通知入口；`BlackMoonInitAllElib`/`BlackMoonFreeAllElib` 只通过协议码通知外部库，不在此处定义其实现。
- COM/OLE/Dispatch：`krnln_Dispatch.cpp` 和 `krnln_Variant.cpp` 提供 `IDispatch`/`VARIANT` 相关命令；实际宿主可用性依赖 Windows COM 初始化和对象实现。

## 8. 功能分区概览

- 算术/数学：`krnln_abs.cpp`、`krnln_sin.cpp`、`krnln_cos.cpp`、`krnln_tan.cpp`、`krnln_pow.cpp`、`krnln_exp.cpp`、`krnln_log.cpp`、`krnln_int.cpp`、`krnln_mod.cpp`、`krnln_IDiv.cpp` 等。
- 文本/编码：`krnln_left.cpp`、`krnln_mid.cpp`、`krnln_right.cpp`、`krnln_len.cpp`、`krnln_InStr*.cpp`、`krnln_ReplaceText.cpp`、`krnln_StrToUTF8.cpp`、`krnln_UTF8ToStr.cpp`、大小写/空白处理命令。
- 字节集/数组/转换：`krnln_Bin*.cpp`、`krnln_SplitBin.cpp`、`krnln_SpaceBin.cpp`、`krnln_SortAry.cpp`、`krnln_Variant.cpp`、`krnln_To*.cpp`、`krnln_p2*.cpp`。
- 文件/目录/注册表：`krnln_open.cpp`、`krnln_create.cpp`、`krnln_read.cpp`、`krnln_write.cpp`、`krnln_Read*.cpp`、`krnln_Write*.cpp`、`krnln_File*.cpp`、`krnln_MkDir.cpp`、`krnln_RmDir.cpp`、`krnln_*RegItem.cpp`。
- 日期时间/系统：`GetDatePart.cpp`、`GetTimePart.cpp`、`DateTimeFormat.cpp`、`krnln_*Time*`、`krnln_GetSysVer.cpp`、`krnln_GetDisk*.cpp`、`krnln_GetRunPath.cpp`、`krnln_GetCmdLine.cpp`。
- 窗口/剪贴板/图像/输入：`krnln_MsgBox.cpp`、`krnln_InputBox.cpp`、`krnln_GetWinPic.cpp`、`krnln_GetClipBoardText.cpp`、`krnln_SetClipBoardText.cpp`、光标/屏幕/颜色命令。
- 网络/进程/DLL/媒体/COM：`krnln_ping.cpp`、`krnln_HostNameToIP.cpp`、`krnln_IPToHostName.cpp`、`krnln_RunConsoleApp.cpp`、`BlackMoonCallUserDll.cpp`、`krnln_PlayMID.cpp`、`krnln_PlayMusic.cpp`、`krnln_Dispatch.cpp`、`krnln_Variant.cpp`。

## 8.1 源码覆盖与关键实现证据

本仓库不是一个只有少数导出函数的薄封装。当前工作树的可核对规模是：`krnln/` 有 256 个文件，其中 249 个 C++ 源文件、13 个头文件以及已提交的对象文件；`MFCObj/` 有 13 个文件；`Project/` 有 13 个工程/过滤器/用户配置文件；`.github/workflows/` 有 3 个 Windows 工作流。下面按实际文件而不是文件名猜测归纳核心实现。

| 能力链 | 关键源码与行号 | 实际行为 | 不能推断的内容 |
|---|---|---|---|
| 宿主 ABI 元数据 | `krnln/lib.h:804-805`、`krnln/lib2.h` | 以 `GetNewInf` 返回 `PLIB_INFO`，宿主再按 `LIBAPI` 命令签名调用函数 | 本仓库不包含完整宿主注册表或 IDE 端装配代码 |
| 命令入口 | `krnln/krnln_abs.cpp:10`、`krnln/krnln_open.cpp:22-88`、`krnln/krnln_write.cpp:18-54` | 统一从 `MDATA_INF ArgInf` 读取参数；数值命令直接写 ABI 返回槽，文件命令创建/登记 Windows 句柄 | 仅有工程配置不能证明每个命令在目标 Windows 版本都可运行 |
| DLL 初始化 | `krnln/BlackMoonDll.cpp:11-31`、`krnln/BlackMoonDll2.cpp` | `DLL_PROCESS_ATTACH` 设置实例句柄、调用 `E_Init` 和 `DllEntryFunc`；分离时调用 `E_DestroyRes` | 未验证宿主重复加载、异常卸载和并发加载 |
| EXE 入口 | `krnln/BlackMoonExe.cpp`、`MFCObj/MFCBlackMoon.cpp:64-86`、`MFCObj/MFCBlackMoonCon.cpp:15-55` | 入口保存栈保护值，初始化后转入外部 `ECodeStart`；部分路径使用内联汇编 | macOS 无法证明 MSVC 汇编、栈恢复和 x64 变体正确 |
| MFC 适配 | `MFCObj/BlackMoonMFCdll.cpp:40-81`、`MFCObj/EyMFCComInit.cpp:17-36` | `InitInstance` 调用 `E_Init`/`EDllMain`，`ExitInstance` 调用资源销毁；初始化含 `AfxOleInit` 和 `CoInitialize` | 未在 Windows/MFC 宿主中执行消息循环或 DLL 生命周期测试 |
| 运行时内存 | `krnln/eHelpFunc.cpp`、`krnln/BlackMoonLibNotifySys.cpp:313` 起、`krnln/lib.h:508-526` | 文本、字节集、数组通过通知码使用宿主分配器；核心同时维护进程堆和全局销毁回调 | 不能把 `malloc/free` 与宿主数组/文本内存混用 |
| 文件资源 | `krnln/FileManager.cpp`、`krnln/MyMemFile.cpp`、`krnln/krnln_open.cpp` | Windows 文件句柄和内存文件都进入全局登记链；关闭、重置和进程退出走不同释放路径 | 没有测试证明异常路径都能从登记链移除 |
| 外部支持库 | `krnln/eHelpFunc.cpp`、`krnln/BlackMoonLibNotifySys.cpp` | `BlackMoonInitAllElib`/`BlackMoonFreeAllElib` 通过通知协议初始化和释放外部库 | 外部库实现、排序和注册来源不在本仓库 |
| 用户 DLL | `krnln/BlackMoonCallUserDll.cpp:23-69` | `LoadLibrary`/`GetProcAddress` 支持名称和序号；失败会回调错误或终止运行时 | 不能将该路径视为沙箱或可恢复插件系统 |
| COM/Variant | `krnln/krnln_Dispatch.cpp`、`krnln/krnln_Variant.cpp`、`krnln/EyComInit.cpp:13-31` | COM 变体先初始化 COM，再通过 `IDispatch`/`VARIANT` 命令工作，销毁时撤销 COM 初始化 | 未运行真实 COM 对象和跨线程公寓测试 |

### 8.2 命令实现不是统一安全层

`LIBAPI` 只是 ABI 入口宏，不代表命令具备统一错误处理、权限隔离或资源事务。源码中至少存在三类不同实现：

1. 纯计算命令，例如 `krnln_abs.cpp`、`krnln_sin.cpp`，主要改写 `ArgInf` 中的数值槽位。
2. 宿主内存命令，例如 `krnln_StrToUTF8.cpp`、`krnln_BinMid.cpp`，需要通过 `NotifySys` 或 `E_MAlloc` 创建结果并遵守文本/字节集所有权。
3. 有外部副作用的命令，例如 `krnln_open.cpp`、`krnln_create.cpp`、`krnln_GetNumRegItem.cpp`、`krnln_ping.cpp` 和 `BlackMoonCallUserDll.cpp`，直接触达文件、注册表、ICMP 或 DLL 装载。

因此接入系统工程平台时，不能把整个仓库注册成一个“通用执行能力”。应按原子能力拆分：纯计算可以进入数学/文本支持库；文件、注册表、网络、进程、DLL、COM 必须分别经过权限、超时、资源释放和失败结果转换；旧 ABI 只在适配层保留。

### 8.3 资源释放的真实顺序

```text
DLL_PROCESS_DETACH / MFC ExitInstance
  -> E_DestroyRes
     -> DestroyAddress（程序入口/对象）
     -> HFileDestroyAddress（登记的文件/内存文件）
     -> DestroyMidiPlayer（媒体资源）
     -> BlackMoonFreeAllElib（外部支持库通知）
     -> BlackMoonFreeAllUserDll（用户 DLL）
     -> CoUninitialize（仅 COM 变体）
```

`krnln/EyComInit.cpp:19-31` 和 `MFCObj/EyMFCComInit.cpp:24-36` 明确了这条顺序；其中 MFC 变体的 `CoUninitialize` 当前被注释掉，不能把两个初始化实现当成完全等价。`FileManager.cpp` 的全局链表和临界区也说明“函数返回”不等于资源已释放，平台适配层必须建立句柄/临时文件/外部模块的显式所有权记录。

### 8.4 当前工程矩阵的可验证边界

| 工程 | 类型 | 配置事实 | 当前可验证状态 |
|---|---|---|---|
| `Project/krnln_VS2019.vcxproj` | 静态库 | Win32/x64、Debug/Release、v142 | 已读取 XML；当前 macOS 未执行 MSBuild |
| `Project/krnln_VS2019_Obj.vcxproj` | 静态库 | 对象/入口子集、Win32/x64、Debug/Release | 已读取 XML；未证明链接产物与主库兼容 |
| `Project/MFCBlackMoon_VS2019.vcxproj` | 动态库 | MFC、Win32/x64、Debug/Release/ReleaseDll | 已读取 XML；未执行 MFC 构建 |
| `Project/*_VC6.dsp` | 旧工程 | VC6 兼容入口 | 仅作为历史工程文件，未在 VC6 环境验证 |
| `.github/workflows/*.yml` | CI | Windows runner + MSBuild，分别覆盖三类工程 | 仅静态核对工作流，未取得远端运行记录 |

工程文件中的 x64 配置不能覆盖源文件中的 32 位假设。`DllEntryFunc.cpp`、`BlackMoonExe.cpp` 和 `Myfunctions.cpp` 使用寄存器/内联汇编或旧调用约定，x64 只能标为“待 Windows/MSVC 实跑”，不能在平台能力目录中声明为已验证能力。

## 9. 测试、CI 与验证状态

### 已存在的验证结构

仓库没有 `test/`、`tests/` 或测试命名文件；`search_files` 未发现测试文件。质量门槛由三组 GitHub Actions 构建工作流承担：

- `blackmoon_krnln.yml`：Windows runner，使用 `microsoft/setup-msbuild@v1.0.2`，构建 `Project/krnln_VS2019.vcxproj` 的 Debug/Release Win32。
- `blackmoon_krnlnobj.yml`：同样构建 `Project/krnln_VS2019_Obj.vcxproj` 的 Debug/Release Win32。
- `blackmoon_mfc.yml`：构建 `Project/MFCBlackMoon_VS2019.vcxproj` 的 Debug/Release Win32。

### 本次执行状态

- 已读取源码、README/Readme.txt、许可证、工程文件、CI 文件、依赖边界、入口、数据模型、调用链和远程版本。
- 未在当前 macOS 宿主上安装依赖、启动服务或构建；Windows/MSBuild/MFC/Win32 依赖不可在当前环境直接验证。
- 未发现项目内其他架构事实文档；本文件是当前项目唯一架构事实源，后续复核只更新本文件。

## 10. 风险、未确认项与后续复核点

1. **平台边界**：源码直接依赖 Win32、MFC、COM/OLE、注册表、Windows 文件 API，当前 macOS 无法替代 Windows 构建证据。
2. **x64 配置真实性**：VS2019 工程列出 x64 配置，但 `DllEntryFunc.cpp`、`BlackMoonExe.cpp`、`BlackMoonCallPropertyVaule.cpp`、`Myfunctions.cpp` 等仍使用 MSVC 内联汇编和 32 位寄存器/指针假设；x64 配置是否能通过需在 Windows/MSVC 上单独验证，不能由工程 XML 的配置存在推断为可构建。
3. **ABI/栈约束**：`LIBAPI` 使用 `_cdecl`、返回值和部分回调依赖寄存器约定，`E_End` 直接恢复 `ESP/EBP`；任何编译器、架构或调用约定变化都可能破坏宿主兼容性。
4. **生命周期全局状态**：`DestroyAddress`、`HFileDestroyAddress`、`DestroyMidiPlayer`、用户 DLL 列表和 `pFileList` 为全局状态；重复初始化、异常退出和并发调用应在 Windows 宿主中做回归验证。
5. **错误处理副作用**：内存失败、未找到用户 DLL、运行时错误可能通过消息框并调用 `E_End` 终止进程；宿主无 UI 或需要可恢复错误时需明确兼容策略。
6. **编码约束**：README 要求源码使用 ANSI/GB2312，仓库同时存在不同历史编码和 CRLF；后续编辑源码不能顺手转换编码或换行。本文档不修改源码。
7. **外部支持库注册来源**：`BlackMoonCalleLibList` 和 `BlackMoonFuncForeLib` 的完整装配依赖宿主/链接对象；当前仓库分析确认了消费方式，但未运行宿主验证完整支持库链。
8. **发布产物路径**：README 说明 `kernel.lib` 替换路径，但当前仓库未提交 Release 产物；需要在 Windows 上验证各配置的实际输出文件名和目录。
9. **远程版本**：本地 `master` 提交 `18c80b64bb2af7b5654a494cb8ab7fb38218bd4f`，远程 `origin/master`/`HEAD` 同为该提交，当前不落后远程；未创建独立快照。

## 11. 证据路径与版本基线

- 项目根：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/BlackMoonKernelStaticLib`
- 远程：`https://github.com/aiqinxuancai/BlackMoonKernelStaticLib.git`
- 当前分支：`master`；建档前除本文件外无源码改动，HEAD 与 `origin/master` 均为 `18c80b64bb2af7b5654a494cb8ab7fb38218bd4f`。
- 关键证据：`README.md`、`Readme.txt`、`LICENSE`、`krnln/StdAfx.h`、`krnln/lib.h`、`krnln/lib2.h`、`krnln/eHelpFunc.cpp`、`krnln/EyInit.cpp`、`krnln/EyComInit.cpp`、`krnln/DllEntryFunc.cpp`、`krnln/BlackMoonLibNotifySys.cpp`、`krnln/FileManager.cpp`、`krnln/MyMemFile.cpp`、`Project/*.vcxproj`、`.github/workflows/*.yml`。
- 代码地图：已按要求先调用 `codegraph_explore`；该外部目标仓库没有 `.codegraph/` 索引，因此返回不可查询，后续改用本地源码/工程文件取证，没有重复调用。
