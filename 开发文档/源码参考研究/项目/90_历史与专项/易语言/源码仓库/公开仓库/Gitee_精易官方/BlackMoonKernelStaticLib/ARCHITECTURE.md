# BlackMoonKernelStaticLib 架构建档

> 本文件是本仓库唯一的架构事实源。本文档创建于首轮全量静态建档；源码参考库按只读方式分析，未修改源码、工程文件或构建产物，未执行构建、测试或服务。
>
> 旧版 `细探-*.md`：现场未发现，因此无旧细探可吸收或清理。后续架构结论只维护本文件。

## 1. 项目定位

`BlackMoonKernelStaticLib` 是面向易语言黑月编译器/运行时环境的 Windows x86 C/C++ 核心静态库源码。仓库以易语言支持库调用约定为边界，将大量“系统核心支持库”命令实现编译为 `Release/krnln.lib`，供易语言安装目录 `BlackMoon/lib/` 中的核心库替换使用；同时保留一个独立的 `BlackMoonExe` 控制台/Windows 入口示例工程，用于调用易语言代码入口。

项目不是通用跨平台 C++ 库：实现深度依赖 Win32 API、VC6/Visual C++ 6.0 工程格式、32 位 x86 ABI、易语言运行时数据结构，以及部分内联汇编/预编译二进制对象。

README（`Readme.txt`）给出的作者链为：原作者“云外归鸟”，后续升级“泪闯天涯（邓学彬）”，后续优化“被封七号”。仓库版权文件为 `LICENSE` 中的 BSD 3-Clause License，版权年份 2019、版权人钟建华；`Readme.txt` 另含源码使用、传播署名和编码规范说明，许可证适用性以实际发布要求为准。

## 2. 版本与现场基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/BlackMoonKernelStaticLib` |
| Git 分支 | `master`，跟踪 `origin/master` |
| 本地 HEAD | `4d257236a87a95b3455e43ec534fe6a0ba1e53a5` |
| HEAD 短哈希 | `4d25723` |
| HEAD 时间 | `2019-12-19T15:16:51+08:00` |
| HEAD 提交主题 | `Merge pull request #4 from clhhz/master` |
| HEAD 作者 | `zhongjianhua163` |
| 远程 | `https://gitee.com/JYtechnology/BlackMoonKernelStaticLib.git`（fetch/push） |
| 远程 `HEAD` 现场查询 | `4d257236a87a95b3455e43ec534fe6a0ba1e53a5`，`refs/heads/master` 同值 |
| 工作树 | 建档前 `git status --short --branch` 为 `## master...origin/master`，未见源码改动 |
| 历史可见性 | 本地仓库存在 `.git/shallow`，当前克隆为浅历史；本次只能把可见 HEAD 作为版本基线，不能推断完整历史 |
| 代码地图 | `codegraph_explore` 已按要求调用，但目标仓库没有 `.codegraph/`，向上目录也无索引；因此本档完全依据现场文件、工程、Git 元数据和静态文本读取，不把其他项目代码地图结果当证据 |

现场统计（排除 `.git`）：266 个文件，约 1,409,877 bytes；其中 `krnln/` 254 个文件、约 750,807 bytes，`BlackMoonExe/` 1 个源文件，`Release/` 1 个静态库，根目录及工程/许可/CI 文件 9 个。源码统计：242 个 `.cpp`、9 个 `.h`；另有 2 个 `.obj`、1 个 `.lib`、2 个 `.dsp`、2 个 `.dsw`、1 个 `.dep`、1 个 `.mak`、1 个 `.yml`、1 个 `.asp` 和文本/许可文件。

## 3. 总体流程图

```text
易语言编译器/运行环境
        │
        │  传入 nArgCount + MDATA_INF ArgInf + 可变参数
        ▼
LIBAPI 宏
extern "C" 返回值 _cdecl krnln_xxx(INT, MDATA_INF, ...)
        │
        ├── 参数类型/默认值/变量或数组标志由 lib.h / lib2.h 定义
        ├── 从 MDATA_INF 读取 m_int/m_double/m_pText/m_pBin 等运行时数据
        ├── 调用 Win32、C 运行库或内部辅助实现
        ├── 需要时通过 E_MAlloc/E_MFree/CloneTextData/CloneBinData 返回易语言数据
        └── 文件、媒体、COM、外部支持库资源登记到生命周期管理器
        │
        ▼
krnln/*.cpp（约 206 个易语言核心命令实现 + 辅助实现）
        │
        ├── 文本/字节集/数组/数值/日期时间
        ├── 文件/内存文件/加密文件/注册表/目录
        ├── 系统环境/窗口/剪贴板/消息框/进程/网络
        ├── MIDI/音乐/拼音/编码转换
        └── 支持库通知、用户 DLL/属性调用、黑月扩展
        │
        ▼
VC6 Win32 x86 Static Library 工程
krnln.dsp + krnln.mak + krnln.dep
编译选项：Release /MT、Win32、x86、无 MFC、stdafx.h 预编译头
        │
        ├── 源码对象 + 固定二进制对象 krnln/PY.OBJ、krnln/Diskid32.obj
        ▼
Release/krnln.lib
        │
        ▼
复制到易语言安装目录 BlackMoon/lib/，替换核心静态库

独立入口支线：
BlackMoonExe/BlackMoonExe.cpp
  ├── E_Init()
  ├── ECodeStart()（普通 C 调用或 32 位内联汇编调用）
  └── 返回入口结果
```

## 4. 真实目录与分层

```text
BlackMoonKernelStaticLib/
├── Readme.txt                         项目说明、VC6 编译/安装、使用规范
├── LICENSE                            BSD 3-Clause License
├── .gitignore                         VC6 临时文件和 Release 中间物忽略规则
├── .github/workflows/ccpp.yml         GitHub Actions Windows CI 声明
├── krnln.dsw                          VC6 工作区（旧二进制/文本混合格式）
├── krnln.dsp                          krnln Win32 x86 静态库工程
├── krnln.mak                          从 VC6 工程导出的 NMAKE 文件
├── krnln.dep                          VC6 生成的依赖文件
├── BlackMoonExe.dsw                   BlackMoonExe VC6 工作区
├── BlackMoonExe.dsp                   BlackMoonExe Win32 控制台工程
├── krnln/
│   ├── StdAfx.h/.cpp                  Windows/运行时公共头与预编译头
│   ├── lib.h                          易语言支持库旧版 ABI/元数据定义
│   ├── lib2.h                         扩展 ABI、操作系统/通知/运行时定义
│   ├── Myfunctions.h/.cpp             字符串、内存、SSE2 自适配等内部基础函数
│   ├── MyMemFile.h/.cpp               CMyMemFile 内存文件类
│   ├── mem.h/.cpp                     频繁内存/数组辅助类
│   ├── midi.h/.cpp                    MIDI 数据结构和播放辅助
│   ├── md5t.h/.cpp                    MD5/RC4 加密文件辅助
│   ├── FileManager.cpp                文件句柄/内存文件登记与清理
│   ├── eHelpFunc.cpp                  E_* 运行时桥接、内存/错误/支持库通知
│   ├── EyInit.cpp                     不带 COM 初始化的 E_Init/E_DestroyRes
│   ├── EyComInit.cpp                  带 COM 初始化的 E_Init/E_DestroyRes
│   ├── DllEntryFunc.cpp               DLL 入口生命周期
│   ├── BlackMoonDll*.cpp              DLL 入口/扩展转发
│   ├── BlackMoonCall*.cpp             用户 DLL、属性值调用
│   ├── BlackMoonLibNotifySys.cpp      支持库通知系统实现
│   ├── BlackMoonResDll.cpp            资源 DLL 相关实现
│   ├── 206 个 krnln_*.cpp             易语言核心命令实现（按命令分文件）
│   ├── 其他辅助 .cpp                  拼音、日期、数组、复制、文件等共同实现
│   ├── PY.OBJ                         预编译 Intel 80386 COFF 拼音相关对象
│   └── Diskid32.obj                   预编译 Intel 80386 COFF 磁盘标识相关对象
├── BlackMoonExe/
│   └── BlackMoonExe.cpp               E_Init + ECodeStart 入口示例
└── Release/
    └── krnln.lib                      已随仓库保存的 Windows 静态库归档
```

### 4.1 代码分层事实

1. **易语言 ABI/公共契约层**：`krnln/StdAfx.h` 引入 `windows.h` 和 `lib2.h`，定义 `LIBAPI`；`lib.h`/`lib2.h` 定义 `DATA_TYPE`、`MDATA_INF`、`CMD_INFO`、`LIB_INFO`、通知号、函数指针和支持库元数据。
2. **运行时桥接层**：`eHelpFunc.cpp` 提供 `E_End`、`E_ReportError`、`E_MAlloc`、`E_MFree`、`E_MRealloc`、`E_Destroy`、`E_NULLARRAY` 等运行时调用；`EyInit.cpp`/`EyComInit.cpp` 负责初始化堆和支持库资源；`DllEntryFunc.cpp`、`BlackMoonDll*.cpp` 处理 DLL 进出程。
3. **共享内部基础设施层**：包括 `Myfunctions`、`CMyMemFile`、`CFreqMem/CMyDWordArray`、数组/日期/数据类型/字符串复制、文件管理、MD5/RC4、MIDI、拼音表等。
4. **命令实现层**：每个 `krnln_*.cpp` 一般实现一个或一组同一领域的易语言核心命令，统一以 `LIBAPI` 暴露 C 符号和 `_cdecl` 调用约定。
5. **构建/交付层**：VC6 工程和导出的 NMAKE 文件将源码、`PY.OBJ`、`Diskid32.obj` 归档成 `Release/krnln.lib`；CI 仅声明 Windows 上执行 `nmake install` 和 `MAKE --makefile krnln.mak CFG="krnln - Win32 Release"`。

## 5. ABI、运行时数据模型与所有权

### 5.1 易语言运行时类型

`lib.h`/`lib2.h` 中的核心类型编码使用 `MAKELONG(MAKEWORD(...), mask)` 组合：

- 系统数据类型：`SDT_BYTE`、`SDT_SHORT`、`SDT_INT`、`SDT_INT64`、`SDT_FLOAT`、`SDT_DOUBLE`、`SDT_BOOL`、`SDT_DATE_TIME`、`SDT_TEXT`、`SDT_BIN`、`SDT_SUB_PTR`、`SDT_STATMENT`。
- 类型掩码：`DTM_SYS_DATA_TYPE_MASK`、`DTM_USER_DATA_TYPE_MASK`、`DTM_LIB_DATA_TYPE_MASK`。
- 参数形态标志：`DT_IS_ARY`、`DT_IS_VAR`；参数接收标志 `AS_RECEIVE_VAR`、`AS_RECEIVE_VAR_ARRAY`、`AS_RECEIVE_VAR_OR_ARRAY`、`AS_RECEIVE_ARRAY_DATA`、`AS_RECEIVE_ALL_TYPE_DATA`。
- 命令状态：`CT_IS_HIDED`、`CT_IS_ERROR`、`CT_DISABLED_IN_RELEASE_VER`、`CT_ALLOW_APPEND_NEW_ARG`、`CT_RETURN_ARRAY_DATA`。
- 布尔约定：`DTBOOL` 为 `SHORT`，`BL_TRUE=-1`，`BL_FALSE=0`。
- 扩展操作系统标志：`__OS_WIN`、`__OS_LINUX`、`__OS_UNIX`，但本仓库实现和工程实际配置明显以 Windows x86 为主；不能据此宣称 Linux/Unix 可构建。

### 5.2 参数和返回值

`LIBAPI(rType, fnName)` 展开为：

```cpp
extern "C" rType _cdecl fnName(INT nArgCount, MDATA_INF ArgInf, ...)
```

实现通常将 `&ArgInf` 视为参数数组，按 `pArgInf[0]`、`pArgInf[1]` 读取参数。`MDATA_INF`/`MDATA` 内含数据类型和数值、文本、字节集、数组、变量/语句等联合数据。返回 `char*`、`void*`、`LPBYTE` 的命令常通过 `CloneTextData`、`CloneBinData` 或运行时分配器返回由易语言运行时负责释放的数据；返回 `void` 的部分命令通过 EAX/EDX 或传址参数回写结果，这是从命令注释与实现可见的旧 ABI 约定。

### 5.3 内存和资源所有权

- `E_Init()` 设置 `hBlackMoonHeap = GetProcessHeap()` 并调用 `BlackMoonInitAllElib()`。
- `E_MAlloc`/`E_MAlloc_Nzero`/`E_MRealloc`/`E_MFree`/`E_Destroy` 是面向易语言运行时的分配、重分配、释放和销毁回调桥。
- `E_DestroyRes()` 依次调用 `DestroyAddress`、`HFileDestroyAddress`、`DestroyMidiPlayer`（若非空），再调用 `BlackMoonFreeAllElib()`；COM 版本额外调用 `CoUninitialize()`。
- `FileManager.cpp` 使用全局 `pFileList` 和 `CRITICAL_SECTION csFileMan` 登记文件对象。`nType==1/3` 使用 `CloseHandle`，`nType==2` 删除 `CMyMemFile`；列表清空时重置 `HFileDestroyAddress`。
- `CMyMemFile` 自行管理可增长缓冲区，支持 `Attach`/`Detach`、`Read`/`Write`/`Seek`/`SetLength`/`Close`，初始增长粒度默认 1024 字节。
- `BlackMoonInitAllElib`/`BlackMoonFreeAllElib` 通过 `BlackMoonCalleLibList` 与 `BlackMoonFuncForeLib` 等运行时登记信息初始化或释放其他支持库接口；真实外部支持库加载/注册契约需在易语言运行时侧继续核对。

## 6. 真实调用链

### 6.1 普通命令调用

```text
易语言程序调用命令
  → 易语言运行时按支持库 ABI 准备 MDATA_INF
  → krnln_xxx(nArgCount, ArgInf, ...)
  → 命令实现校验 _SDT_NULL/数据类型/参数值
  → Win32/C 运行库/内部辅助函数
  → 通过返回值、传址参数或 EAX/EDX 返回
  → 文本/字节集/数组结果由运行时所有权规则接管
```

示例证据：`krnln/krnln_CryptOpen.cpp` 按打开方式映射 `GENERIC_READ/WRITE` 和 `CREATE_ALWAYS/OPEN_ALWAYS/OPEN_EXISTING`，按共享方式映射 `FILE_SHARE_*`，调用 `CreateFile`，有密码时计算 MD5、初始化 RC4 表，生成 `FILEELEMENT` 并交由 `AddFileMangerList` 登记。

### 6.2 初始化与销毁

```text
DLL_PROCESS_ATTACH / BlackMoonExe 启动
  → E_Init()
  → hBlackMoonHeap = GetProcessHeap()
  → （EyComInit 版本）CoInitialize(0)
  → BlackMoonInitAllElib()
  → 命令和外部支持库可用

DLL_PROCESS_DETACH / E_End
  → E_DestroyRes()
  → DestroyAddress()
  → HFileDestroyAddress()：关闭文件/释放内存文件
  → DestroyMidiPlayer()
  → BlackMoonFreeAllElib()
  → （EyComInit 版本）CoUninitialize()
```

`DllEntryFunc.cpp` 的 `DllMain` 在进程附加时保存 `hBlackMoonInstanceHandle`、调用 `E_Init` 并将 `DllEntryFunc()` 返回值写入 `DestroyAddress`；进程分离时调用 `E_DestroyRes`。`BlackMoonDll2.cpp` 在类似流程后把控制权转给外部 `EDllMain`。

### 6.3 BlackMoonExe 入口

`BlackMoonExe/BlackMoonExe.cpp` 声明 `extern "C" int ECodeStart()`，提供 `BMEntrypoint()`（C 调用）和 `WinMain`/`main` 两类入口。三者均先 `E_Init()`；`WinMain`/`main` 以 32 位内联汇编保存 `ESP/EBP` 到 `nBMProtectESP/nBMProtectEBP`，调用 `ECodeStart` 并取 EAX 作为返回值。该代码明确是旧式 x86/VC ABI，不应在 macOS 或 x64 编译器上直接推断可用。

## 7. API 边界清单

### 7.1 运行时桥接 API

`krnln/StdAfx.h` 和 `krnln/eHelpFunc.cpp` 可确认的 C ABI 边界包括：

- 生命周期：`E_Init`、`E_DestroyRes`、`E_End`。
- 错误与内存：`E_ReportError`、`E_MAlloc`、`E_MAlloc_Nzero`、`E_MRealloc`、`E_MFree`、`E_Destroy`。
- 数组/运行时辅助：`E_CloneConstArray`、`E_NULLARRAY`、`E_HelpFunc12`。
- 公开内部辅助：`GetAryElementInf`、`FreeAryElement`、`GetTimePart`、`GetDatePart`、`DateTimeFormat`、`GetSpecDateTime`、`GetDataTypeType`、`CloneBinData`、`CloneTextData`、`GetSysDataTypeDataSize`。
- 外部调用/通知：`BlackMoonInitAllElib`、`BlackMoonFreeAllElib`，以及由 `lib.h/lib2.h` 定义的 `PFN_NOTIFY_LIB`、`PFN_NOTIFY_SYS`、`PFN_EXECUTE_CMD`、`PFN_GET_LIB_INFO` 等函数指针契约。

### 7.2 `LIBAPI` 命令 API

静态扫描 `krnln/*.cpp` 得到 211 个 `LIBAPI` 定义（其中 `eHelpFunc.cpp` 的 `krnln_SetErrorManger` 为运行时管理类命令；同一源文件可能提供多个 API）。以下按功能域归档，名称保持源码原文：

**文本与字符：**
`krnln_BJCase`、`krnln_LCase`、`krnln_UCase`、`krnln_LTrim`、`krnln_RTrim`、`krnln_TrimAll`、`krnln_left`、`krnln_mid`、`krnln_right`、`krnln_len`、`krnln_InStr`、`krnln_InStrRev`、`krnln_ReplaceText`、`krnln_RpSubText`、`krnln_StrComp`、`krnln_str`、`krnln_string`、`krnln_chr`、`krnln_asc`、`krnln_pstr`、`krnln_UNum`、`krnln_QJCase`、`krnln_hex`、`krnln_oct`、`krnln_bin`、`krnln_UTF8ToStr`、`krnln_StrToUTF8`、`krnln_Val`/`krnln_val`（实际文件为 `krnln_val.cpp`，符号大小写需以工程对象为准）。

**字节集与数据转换：**
`krnln_BinLeft`、`krnln_BinMid`、`krnln_BinRight`、`krnln_BinLen`、`krnln_InBin`、`krnln_InBinRev`、`krnln_RpBin`、`krnln_RpSubBin`、`krnln_SplitBin`、`krnln_SpaceBin`、`krnln_InsBin`、`krnln_RemoveData`、`krnln_GetBinElement`、`krnln_GetBinRegItem`、`krnln_SetIntInsideBin`、`krnln_GetIntInsideBin`、`krnln_ToBin`、`krnln_pbin`、`krnln_p2int`、`krnln_p2float`、`krnln_p2double`、`krnln_ToByte`、`krnln_ToShort`、`krnln_ToInt`、`krnln_ToLong`、`krnln_ToFloat`、`krnln_MakeWord`、`krnln_MakeLong`、`krnln_ReverseIntBytes`。

**数值与逻辑/数学：**
`krnln_abs`、`krnln_atn`、`krnln_band`、`krnln_bor`、`krnln_bxor`、`krnln_bnot`、`krnln_shl`、`krnln_shr`、`krnln_IDiv`、`krnln_int`、`krnln_fix`、`krnln_mod`、`krnln_sgn`、`krnln_sqr`、`krnln_sin`、`krnln_cos`、`krnln_tan`、`krnln_exp`、`krnln_log`、`krnln_pow`、`krnln_rnd`、`krnln_round`、`krnln_randomize`、`krnln_IsCalcOK`、`krnln_ToTime`、`krnln_TimePart`、`krnln_TimeChg`、`krnln_TimeDiff`、`krnln_TimeToText`。

**日期时间：**
`krnln_now`、`krnln_year`、`krnln_month`、`krnln_day`、`krnln_hour`、`krnln_minute`、`krnln_second`、`krnln_WeekDay`、`krnln_GetDatePart`、`krnln_GetTimePart`、`krnln_GetDaysOfSpecMonth`、`krnln_GetSpecTime`、`krnln_DateTimeFormat` 对应的内部实现链；文件名和符号存在新旧大小写/命名差异，调用者以 `.dsp/.mak` 与源码定义共同核对。

**数组与类型：**
`krnln_GetDataTypeSize`、`krnln_GetRuntimeDataType`、`krnln_ZeroAry`、`krnln_SortAry`、`krnln_Split`/`krnln_split`、`krnln_GetAllPY`、`krnln_GetPYCount`、`krnln_GetPY`、`krnln_GetSM`、`krnln_GetYM`、`krnln_CompPY`、`krnln_CompPYCode`。

**文件、内存文件和目录：**
`krnln_open`、`krnln_close`、`krnln_read`、`krnln_write`、`krnln_fgets`、`krnln_fputs`、`krnln_feof`、`krnln_loc`、`krnln_lof`、`krnln_FSeek`、`krnln_SeekToBegin`、`krnln_SeekToEnd`、`krnln_ReadFile`、`krnln_WriteFile`、`krnln_ReadBin`、`krnln_WriteBin`、`krnln_ReadText`、`krnln_WriteText`、`krnln_ReadLine`、`krnln_WriteLine`、`krnln_WriteMem`、`krnln_OpenMemFile`、`krnln_InsLine`、`krnln_InsText`、`krnln_FileCopy`、`krnln_FileMove`、`krnln_FileLen`、`krnln_FileDateTime`、`krnln_MkDir`、`krnln_RmDir`、`krnln_IsFileExist`、`krnln_CurDir`、`krnln_ChDir`、`krnln_ChDrive`、`krnln_GetTempFileName`、`krnln_CryptOpen`、`krnln_RemoveData`。

**系统、注册表、窗口和剪贴板：**
`krnln_GetAttr`、`krnln_SetAttr`、`krnln_GetDiskFreeSpace`、`krnln_GetDiskTotalSpace`、`krnln_GetDiskLabel`、`krnln_SetDiskLabel`、`krnln_GetHDiskCode`、`krnln_GetSysVer`、`krnln_GetSysVer2`、`krnln_GetCmdLine`、`krnln_GetRunPath`、`krnln_GetRunFileName`、`krnln_GetEnv`、`krnln_PutEnv`、`krnln_SetSysTime`、`krnln_GetTickCount`、`krnln_GetScreenWidth`、`krnln_GetScreenHeight`、`krnln_GetCursorHorzPos`、`krnln_GetCursorVertPos`、`krnln_GetBackColor`、`krnln_GetColorCount`、`krnln_GetWinPic`、`krnln_MsgBox`、`krnln_InputBox`、`krnln_DoEvents`、`krnln_SetWaitCursor`、`krnln_RestroeCursor`、`krnln_GetClipBoardText`、`krnln_SetClipBoardText`、`krnln_ClearClipBoard`、`krnln_IsHaveTextInClip`、`krnln_GetKeyText`、`krnln_SetKeyText`、`krnln_SaveRegItem`、`krnln_DeleteRegItem`、`krnln_IsRegItemExist`、`krnln_IsRegItemExist`、`krnln_GetNumRegItem`、`krnln_GetTextRegItem`、`krnln_GetBinRegItem`、`krnln_GetSectionNames`。

**进程、网络、媒体和杂项：**
`krnln_RunConsoleApp`、`krnln_run`、`krnln_kill`、`krnln_HostNameToIP`、`krnln_IPToHostName`、`krnln_ping`、`krnln_PlayMID`、`krnln_PlayMusic`、`krnln_PlayStop`、`krnln_Name`/`krnln_name`、`krnln_SetErrorManger`。

> API 清单是从源码中的 `LIBAPI` 宏静态提取的命令边界，不等于已验证的运行行为，也不等于完整的易语言支持库元数据清单。仓库没有独立 API 文档或测试目录；需要确认命令是否在当前 `krnln.lib` 中导出时，应在 Windows x86 工具链中检查归档符号和易语言运行时加载结果。本次未在 macOS 上执行该验证。

## 8. 依赖和技术栈

| 类别 | 现场证据 | 边界/影响 |
|---|---|---|
| 语言 | C/C++，约 242 个 `.cpp`、9 个 `.h` | 旧式 VC6 语法、C ABI、全局状态较多 |
| 编译器/IDE | `krnln.dsp`/`.dsw` 格式 Version 6.00；README 要求 VC6.0 | 目标为 Microsoft Visual C++ 6.0 时代工程 |
| 目标架构 | 工程名 `Win32 (x86) Static Library`；`BlackMoonExe` 链接 `/machine:I386` | 32 位 x86，不能按 x64/macOS 直接推断 |
| 运行库 | Release `/MT`；Debug 工程含 `/MTd` 或旧基线配置 | 静态 CRT；跨模块内存所有权必须遵循易语言运行时契约 |
| Windows | `windows.h`、Win32 文件/注册表/窗口/进程/剪贴板/网络/COM API | Windows 专属实现大量存在 |
| COM/OLE | `EyComInit.cpp` 调 `CoInitialize/CoUninitialize`；`lib.h/lib2.h` 有 `LPDISPATCH`/COM 契约 | COM 版本与非 COM 版本并存，需选择正确初始化实现 |
| C 运行库 | `stdio.h`、`math.h`、`float.h`、`conio.h`、`stdlib/string` 类调用 | 提供文件、数学、字符串和内存基础能力 |
| Shell/网络 | `SHLWAPI.h`；源码出现 `WSAStartup`、`GetHostName`/IP 转换等 | 依赖 WinSock/Shell 相关系统库，工程默认系统库链需复核 |
| 媒体 | `midi.h/.cpp`、`PlaySound`、MCI/MIDI 相关结构 | Windows 音频环境依赖 |
| 加密 | `md5t.cpp/.h`、`krnln_CryptOpen.cpp`，MD5 + RC4 表初始化 | 代码注释称 RC4；该命令源码标记“未完成”，不可视为完整密码学产品 |
| 预编译对象 | `PY.OBJ`、`Diskid32.obj` 是 Intel 80386 COFF | 必须与 32 位链接器兼容；不能仅由源码重建全部能力 |
| 字符编码 | `Readme.txt` 要求 ANSI/GB2312，源码存在 ISO-8859/GB2312/乱码注释混用 | 改写编码可能破坏易语言/VC6 兼容，源码只读时保留原样 |

`krnln.mak` Release 配置明确包含 `cl.exe`、`link.exe -lib`、`/MT`、`/O2`、`/D WIN32`、`/D NDEBUG`、`/Yu"stdafx.h"`，输出 `Release/krnln.lib`；Debug 配置使用 `/MDd` 等历史选项，且与 README 中“多线程 `/MT`”存在配置差异，应以具体构建配置和目标版本为准。

## 9. 构建、安装与 CI 契约（仅静态记录，未执行）

### 9.1 README 规定的人工流程

1. 用 VC6.0 打开工程（README 写作 `kernel.dsw`，现场实际文件名为 `krnln.dsw`，这是文档与仓库现状的命名漂移）。
2. 编译静态库。
3. 将 `Release` 目录下的 `kernel.lib`（现场实际产物为 `Release/krnln.lib`）替换到易语言安装目录 `BlackMoon/lib/` 下的核心库。
4. 非 VC6 IDE 需新建 Win32 Static Library，导入源码但不导入 `EyInit.obj`、`EyComInit.obj`、`BlackMoonDll.obj`、`BlackMoonDll2.obj`、`BlackMoonExe.cpp`；设置“不使用 MFC”、预编译头 `stdafx.h`、输出 `.\Release\krnln.lib`、多线程 `/MT`。

### 9.2 工程文件事实

- `krnln.dsp`：Win32 x86 静态库，Release/Debug 两配置，Release 输出 `.\Release\krnln.lib`；工程中有 247 个 `SOURCE=` 条目，实际 `krnln.mak` 的源码/对象编译清单与目录存在历史漂移，不能只以一个文件推断完整输入。
- `krnln.mak`：NMAKE 导出文件，Release 和 Debug 块都生成 `krnln.lib`；Release `LIB32_OBJS` 中明确包含 `krnln/PY.OBJ`，并引用 `Diskid32.obj` 等预编译对象；没有可在本机直接执行的 macOS 构建路径。
- `krnln.dep`：VC6 自动依赖，记录 `Myfunctions.h`、`MyMemFile.h`、`mem.h`、`midi.h`、`LTrimZeroChr.h`、`md5t.h` 和 `StdAfx.h` 等关系，含历史绝对路径 `c:\program files (x86)\microsoft visual studio\vc98\include\basetsd.h`。
- `BlackMoonExe.dsp`：独立 Win32 x86 Console Application，源文件只有 `BlackMoonExe/BlackMoonExe.cpp`；链接 Windows 系统库并指定 `/machine:I386`。

### 9.3 CI 事实

`.github/workflows/ccpp.yml`：

```text
push
  → windows-latest
  → actions/checkout@v1
  → run: nmake install
  → run: MAKE --makefile "krnln.mak" CFG="krnln - Win32 Release"
```

注意：仓库现场没有 `install` 目标的明确独立文档，工作流写法也使用旧版 `actions/checkout@v1` 和 `MAKE`；本次遵守只读/禁止构建运行边界，未验证 CI 是否仍能在当前 GitHub Windows runner 上工作。

## 10. 测试与验证现状

- 未发现独立 `test/`、`tests/`、单元测试工程、测试脚本或测试 CI 步骤。
- 文件名中出现 `GetSpecTime.cpp`、`GetDaysOfSpecMonth.cpp` 等命令实现，但它们不是测试文件。
- `.github/workflows/ccpp.yml` 只有构建步骤，没有测试/静态分析/ABI 冒烟步骤。
- `Release/krnln.lib` 已随仓库保存；它是交付参考二进制，不是本次构建生成物。
- 本次未执行编译、链接、NMAKE、GitHub Actions、Windows 运行、易语言加载、导出符号检查或命令行为测试。故不能声称当前源码可在 macOS 构建，也不能声称 CI 通过。

## 11. 已确认的风险与未确认项

### 11.1 已确认风险

1. **平台/架构绑定**：代码使用 `windows.h`、Win32 API、`__asm`、`_EMIT`、x86 栈寄存器和 80386 COFF 对象；移植到 x64 或非 Windows 平台需要 ABI 级重构。
2. **工程与 README 命名漂移**：README 说 `kernel.dsw/kernel.lib`，仓库实际为 `krnln.dsw/Release/krnln.lib`；使用说明不能原样执行。
3. **构建输入存在多份历史清单**：`krnln.dsp`、`krnln.mak`、`krnln.dep` 和目录现场数量不完全同构；变更前必须核对所有清单，否则可能漏编译或重复编译。
4. **预编译对象不可由现有源码完全替代**：`PY.OBJ` 与 `Diskid32.obj` 是旧版 Intel 80386 COFF，来源、可重建性、许可证/兼容性需另行确认。
5. **全局状态和销毁钩子**：`pFileList`、`HFileDestroyAddress`、`DestroyAddress`、`DestroyMidiPlayer`、`hBlackMoonHeap` 等依赖生命周期顺序；重复初始化、异常退出、DLL 卸载时机可能产生资源问题。
6. **并发边界有限**：文件管理列表使用 `CRITICAL_SECTION`，但 `bIsCSinit` 初始化本身是普通全局布尔值，其他全局结构的并发安全性未见统一抽象。
7. **密码学实现不应直接视为安全保证**：`krnln_CryptOpen.cpp` 自身标记“未完成”，注释中的 RC4/MD5 组合也不等于现代安全存储方案。
8. **编码和乱码**：源码按 ANSI/GB2312 约束维护，部分读取呈现乱码，任何自动格式化、UTF-8 转换或换行转换都可能改变兼容性。
9. **API 命名/大小写漂移**：文件名、宏生成符号和注释中有 `Get...`/`krnln_Get...`、大小写不一致及重复实现迹象，必须以最终对象符号和运行时注册表核对。
10. **错误处理不统一**：部分实现依赖 `GetLastError`、全局错误回调或返回空指针/布尔值；未见统一异常模型和错误码文档。

### 11.2 未确认项

- `PY.OBJ`、`Diskid32.obj` 的源码来源、构建命令、授权和与当前 C++ 源码的精确对应关系。
- `BlackMoonResDll.cpp`、`BlackMoonLibNotifySys.cpp` 与实际易语言运行环境/其他支持库的完整交互协议。
- `lib.h` 与 `lib2.h` 两套 ABI 定义在最终目标环境中选用哪一套，以及是否存在不同易语言版本兼容矩阵。
- `nmake install` 在 CI 中应安装什么内容；仓库未提供显式 `install` 目标说明，需在 Windows 环境核验。
- `Release/krnln.lib` 是否与 HEAD 源码完全同步，当前静态库成员是否包含全部当前源文件。
- 命令级默认参数、返回数组所有权、错误行为和易语言 IDE 元数据是否与原生核心库逐项一致。
- 代码中个别“系统需求 Windows；Linux/Unix”注释与实际工程的关系；不能仅凭宏定义认定跨平台支持。

## 12. 后续复核建议

后续如允许进入专门的 Windows 验证轮次，建议仍只增量维护本文件：

1. 在隔离 Windows x86/VC6 或可复现兼容工具链中核对 `krnln.dsp`、`krnln.mak`、`krnln.dep` 的源文件集合和链接输入。
2. 对 `PY.OBJ`、`Diskid32.obj` 做 COFF 归属、符号、许可证和可重建性登记。
3. 从 `Release/krnln.lib` 与新构建归档分别提取对象/符号，核对 `LIBAPI` 命令边界和 C ABI 名称。
4. 在真实易语言运行时中验证 `E_Init → 命令 → E_End/E_DestroyRes` 生命周期，重点覆盖文本/字节集/数组/文件/加密文件/COM/MIDI。
5. 建立不改变源码编码的命令级回归样例，并明确区分“存在测试”“测试执行成功”。
6. 复核 CI 的 `nmake install`、旧 checkout action、大小写命令 `MAKE` 和当前 runner 兼容性。
7. 逐项确认 README 命名漂移和安装路径，将事实更新到本文件；不要另建平行架构报告。

## 13. 证据路径索引

- 项目说明/编译安装/使用规范：`Readme.txt`
- 许可证：`LICENSE`
- CI：`.github/workflows/ccpp.yml`
- 静态库工程：`krnln.dsp`
- NMAKE 构建：`krnln.mak`
- 工程依赖：`krnln.dep`
- 工作区/工程入口：`krnln.dsw`、`BlackMoonExe.dsw`、`BlackMoonExe.dsp`
- ABI 与元数据：`krnln/lib.h`、`krnln/lib2.h`
- 公共入口与宏：`krnln/StdAfx.h`、`krnln/StdAfx.cpp`
- 运行时桥接：`krnln/eHelpFunc.cpp`
- 初始化/销毁：`krnln/EyInit.cpp`、`krnln/EyComInit.cpp`
- DLL 生命周期：`krnln/DllEntryFunc.cpp`、`krnln/BlackMoonDll.cpp`、`krnln/BlackMoonDll2.cpp`
- 文件登记和清理：`krnln/FileManager.cpp`
- 内存文件：`krnln/MyMemFile.h`、`krnln/MyMemFile.cpp`
- 内部优化/字符串基础：`krnln/Myfunctions.h`、`krnln/Myfunctions.cpp`
- 数组/频繁内存：`krnln/mem.h`、`krnln/mem.cpp`
- MIDI：`krnln/midi.h`、`krnln/midi.cpp`
- MD5/RC4 辅助：`krnln/md5t.h`、`krnln/md5t.cpp`、`krnln/krnln_CryptOpen.cpp`
- 拼音实现和固定对象：`krnln/krnln_GetAllPY.cpp`、`krnln/PY.OBJ`
- 磁盘标识固定对象：`krnln/Diskid32.obj`
- 入口示例：`BlackMoonExe/BlackMoonExe.cpp`
- 已保存交付归档：`Release/krnln.lib`
- 版本基线：Git remote `origin`、HEAD `4d257236a87a95b3455e43ec534fe6a0ba1e53a5`

---

**建档结论：** 当前仓库可确认的是一个 VC6 时代、Windows x86、面向易语言运行时 ABI 的核心静态库源码与交付归档；其主要价值在于按 `LIBAPI + MDATA_INF + E_* 生命周期 + Win32/内部辅助` 组织的原生支持库命令实现。当前没有代码地图、独立测试或可在本机验证的构建链，因此所有行为、兼容性和 CI 结论均保留为静态证据级别，不作运行成功推断。
