# javalib 架构建档

> 首轮全量架构建档。本文是本仓库当前唯一的架构事实文档；后续细探应直接更新本文，不另建平行事实源。
>
> **证据口径**：以下结论以当前工作树源码、Visual Studio 工程文件和 Git 元数据为准。`javalib_cmd_typedef.h` / `javalib_cmdInfo.cpp` 中的命令说明描述了目标能力，但不能替代执行代码证据。本文明确区分“源码已实现”“仅声明/注册”“未验证”。

## 1. 项目定位

`javalib` 是面向易语言的 Windows 支持库工程，目标是向易语言暴露 Java Virtual Machine（JVM）生命周期和 Java Native Interface（JNI）访问能力。工程同时声明：

- `Java虚拟机`（英文名 `JavaVM`）数据类型，负责 JVM 生命周期相关命令；
- `Java本地接口`（英文名 `JNIEnv`）数据类型，负责类、对象、成员、方法、字符串、数组、异常和监视器等 JNI 风格操作；
- `数组类型` 枚举，用于基本类型数组创建；
- 一套动态库支持库入口（输出 `.fne`，导出 `GetNewInf`）和一个静态库工程。

**当前真实状态需要特别注意**：仓库只有接口元数据和由模板生成的命令函数骨架。`javalib_cmdDef.cpp` 中函数主要完成 `pArgInf` 参数取值，没有 JNI 调用、JVM 创建、返回值写入或异常处理；11 个无参数/隐藏命令甚至是空函数体。因此，当前提交更接近“Java 支持库接口声明/工程骨架”，不是已验证可运行的 Java 访问实现。

## 2. 总体流程图

```text
易语言 IDE / 编译器
        │
        │ 读取支持库元数据、命令名、数据类型、常量
        ▼
动态库 javalib.fne ──导出──> GetNewInf()
        │                         │
        │                         ├─ LIB_INFO
        │                         ├─ 3 个 LIB_DATA_TYPE_INFO
        │                         ├─ 66 个 CMD_INFO
        │                         └─ 1 个 LIB_CONST_INFO
        │
        ├─ 系统通知 NL_SYS_NOTIFY_FUNCTION
        │          ▼
        │   javalib_ProcessNotifyLib_javalib()
        │          ▼
        │   elib/fnshare.cpp 保存 PFN_NOTIFY_SYS
        │          ▼
        │   ProcessNotifyLib() / NotifySys()
        │
        └─ 易语言命令调用
                   ▼
        g_cmdInfo_javalib_global_var_fun[]
                   ▼
        javalib_*_<index>_javalib()
                   ▼
        当前代码仅取 pArgInf 参数
                   │
                   ├─ 目标应为 JNI/JVM 调用（当前未实现）
                   └─ 目标应写 pRetData/输出变量（当前未实现）
```

静态编译路径如下：

```text
易语言静态编译器
        │
        ▼
 javalib_static.vcxproj（StaticLibrary）
        │  __E_STATIC_LIB（Win32 配置显式定义）
        ▼
复用 javalib_cmdDef.cpp + elib/fnshare.cpp 等源文件
        │
        └─ javalib_dllMain.cpp 中的 DLL 信息注册部分被排除
           （具体静态编译装配契约未在本仓库验证）
```

## 3. 真实目录与分层

当前仓库根目录没有 README、AGENTS.md、测试目录或旧 `细探-*.md` 文件；已纳入 Git 的源码/工程文件共 23 个（不含 `.git` 元数据）。

```text
javalib/
├── ARCHITECTURE.md                  本文，架构事实源（本轮新增）
├── javalib.sln                      VS Solution，动态库+静态库
├── javalib.vcxproj                  动态库项目
├── javalib.vcxproj.filters          动态库文件筛选器
├── javalib.vcxproj.user              用户工程配置
├── javalib_static/
│   ├── javalib_static.vcxproj       静态库项目
│   ├── javalib_static.vcxproj.filters
│   └── javalib_static.vcxproj.user
├── include_javalib_header.h         本库总头文件、元数据外部声明、命令原型生成
├── javalib_cmd_typedef.h            JAVALIB_DEF 命令单一清单和符号拼接宏
├── javalib_cmdDef.cpp               66 个命令函数骨架
├── javalib_cmdInfo.cpp              ARG_INFO 参数表、CMD_INFO 命令元数据
├── javalib_dtType.cpp               3 个库数据类型及成员索引/枚举成员
├── javalib_const.cpp                 1 个库常量
├── javalib_dllMain.cpp               DllMain、LIB_INFO、GetNewInf、通知分发
├── Source_javalib.def                DLL 模块定义，仅导出 GetNewInf
└── elib/                             易语言支持库 ABI/运行时公共头
    ├── lib2.h                        基础类型、元数据结构、通知/命令 ABI
    ├── fnshare.h / fnshare.cpp       库间通知、内存/辅助函数声明与转发
    ├── lang.h                        语言版本常量
    ├── krnllib.h                     系统核心支持库常量
    ├── mtypes.h                      基础 Windows 风格类型和兼容宏
    ├── untshare.h                    组件/通用支持库辅助宏
    └── PublicIDEFunctions.h          IDE 扩展函数编号和数据结构
```

## 4. 模块职责

### 4.1 `javalib_cmd_typedef.h`：命令单一清单

- `JAVALIB_DEF(_MAKE)` 在第 12—78 行定义索引 `0`—`65` 共 66 个命令。
- 同一清单被多次传入不同宏，生成：
  - `include_javalib_header.h` 中的 66 个命令函数声明；
  - `javalib_cmdInfo.cpp` 中的 `CMD_INFO` 元数据；
  - `javalib_dllMain.cpp` 中的函数指针表和静态编译函数名表。
- `JAVALIB_NAME` 将函数拼接为类似 `javalib_FindClass_7_javalib` 的 ABI 符号，避免不同支持库命令重名。
- 命令状态大量使用 `_CMD_OS(__OS_WIN)`，说明接口声明只面向 Windows。

### 4.2 `javalib_cmdDef.cpp`：命令执行入口骨架

- 每个函数遵循 `PFN_EXECUTE_CMD` ABI：`(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。
- 函数体按元数据预取参数，例如整数使用 `m_int`、文本使用 `m_pText`、字节集使用 `m_pBin`、引用参数使用 `m_pInt`/`m_pBool`、通用数据使用 `m_pByte`。
- 当前未见 JNI 头文件、`JNI_CreateJavaVM`、`JNIEnv`/`JavaVM` 指针调用、JVM 句柄存储、`pRetData` 填充或 `NotifySys` 之外的运行时实现。
- 66 个函数中 55 个至少有参数取值语句，11 个函数体为空：`Destroy`、`AttachCurrentThread`、`DetachCurrentThread`、`GetVersionText`、`GetMinorVersion`、`IsExceptionOccurred`、`ExceptionOccurred`、`ExceptionDescribe`、`GetExceptionMsg`、`ExceptionClear`、`DoDestroyJVM`。

### 4.3 `javalib_cmdInfo.cpp`：参数和命令编辑信息

- `g_argumentInfo_javalib_global_var[]` 在第 5—199 行提供参数名、解释、数据类型、默认值和 `AS_*` 传参标志。
- `_DEBUG` 下有参数数量自检变量 `dbg_cmd_arg_count__`，但当前未执行编译验证。
- `CMD_INFO g_cmdInfo_javalib_global_var[]` 在第 211—216 行由 `JAVALIB_DEF` 生成，命令总数来自 `sizeof`。
- 这里是编辑器/编译器识别命令的声明元数据，不是命令功能实现。

### 4.4 `javalib_dtType.cpp`：数据类型注册

- `Java虚拟机` 成员命令索引为 `[0,1,2,3,4]`，即生命周期相关的前 5 个命令。
- `Java本地接口` 成员命令索引为 `[0,5,6,...,65]`，即除前 5 个 JVM 命令外的 61 个命令。
- `数组类型` 是 `LDT_ENUM` 枚举，拥有 8 个 `SDT_INT` 成员，值从 `0x00000001` 到 `0x00000008`，分别对应逻辑型、字节型、字符型、短整数型、整数型、长整数型、小数型、双精度小数型。
- 三个数据类型均标记 `_DT_OS(__OS_WIN)`。

### 4.5 `javalib_const.cpp`：库常量

仅注册一个文本常量：`本库开发代号` / `LibAlias` = `JavaLib`。常量注册位于 `#ifndef __E_STATIC_LIB` 条件内。

### 4.6 `javalib_dllMain.cpp`：动态库生命周期与支持库 ABI

- `DllMain` 当前只切换并返回 `TRUE`，四种 DLL 进程/线程事件均无资源处理。
- `g_cmdInfo_javalib_global_var_fun[]` 由命令清单生成，作为 66 个命令的执行函数表。
- `g_LibInfo_javalib_global_var` 注册库格式、GUID、版本、依赖系统版本、名称、作者、数据类型、命令、常量和通知函数。
- `GetNewInf()` 返回 `&g_LibInfo_javalib_global_var`；`.def` 文件只导出此入口。
- `javalib_ProcessNotifyLib_javalib()` 处理易语言通知：命令函数名、通知函数名、依赖库列表、系统通知函数、释放/卸载/IDE 等事件。除 `NL_SYS_NOTIFY_FUNCTION` 转发到 `ProcessNotifyLib` 外，大多数分支为空或返回固定值。

### 4.7 `elib/`：公共 ABI 与辅助层

`elib/lib2.h` 定义 `ARG_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_CONST_INFO`、`MDATA_INF`、`LIB_INFO`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_LIB`、`PFN_NOTIFY_SYS` 等支持库 ABI。`fnshare.cpp` 保存系统通知回调，并通过 `NotifySys` 转发；它没有实现 Java 能力。其余头文件属于易语言 SDK/运行时公共契约，本仓库直接随项目编译引用。

## 5. 功能与命令边界

### 5.1 JVM 生命周期（索引 0—6）

- `测试函数`（隐藏，模板占位）；
- `创建`、`销毁`、`连接`、`断开`；
- `取版本`、`取次版本`。

### 5.2 类、对象和引用（索引 7—18）

`加载类`、`字节集加载类`、`取父类`、`分配对象`、`创建对象`、`取对象类`、`是否为类实例`、`是否相同`、`可否强制转换`、`创建全局引用`、`销毁全局引用`、`销毁局部引用`。

### 5.3 实例/静态成员（索引 19—28）

`取成员标志符`、`取成员`、`置成员`、`取对象成员`、`置对象成员`、`取静态成员标志符`、`取静态成员`、`置静态成员`、`取静态对象成员`、`置静态对象成员`。

### 5.4 实例/非虚拟/静态方法（索引 29—39）

`取方法标志符`、`方法`、`对象方法`、`空方法`、`非虚拟方法`、`非虚拟对象方法`、`非虚拟空方法`、`取静态方法标志符`、`静态方法`、`静态对象方法`、`静态空方法`。调用类命令均使用 `CT_ALLOW_APPEND_NEW_ARG`，允许在参数表末尾追加方法参数。

### 5.5 字符串（索引 40—47）

`创建字符串`、`取字符串长度`、`取字符串文本`、`释放字符串`、`创建UTF字符串`、`取UTF字符串长度`、`取UTF字符串文本`、`释放UTF字符串`。其中 UTF 相关底层方法和释放方法被标记为隐藏命令。

### 5.6 数组（索引 48—54）

`取数组长度`、`创建数组`、`取数组成员`、`置数组成员`、`创建对象数组`、`取对象数组成员`、`置对象数组成员`。基本数组类型通过 `数组类型` 枚举传递，对象数组通过类标志符和初始对象标志符传递。

### 5.7 异常、监视器和销毁确认（索引 55—65）

`抛出异常`、`抛出新异常`、`是否有异常`、`取异常对象`、`输出异常`、`取异常文本`、`清除异常`、`致命错误`、`进入监视`、`退出监视`、`确认销毁JVM`。多个异常/销毁命令被标记为隐藏；当前实现仍未完成。

## 6. 数据模型与运行时数据

本项目没有数据库、配置文件、业务持久化模型或磁盘数据存储。其“数据模型”是易语言支持库 ABI 中的内存结构和句柄约定。

| 模型/结构 | 作用 | 当前证据 | 状态 |
|---|---|---|---|
| `ARG_INFO` | 命令参数名称、类型、默认值、引用/数组标志 | `elib/lib2.h:266-292`；`javalib_cmdInfo.cpp:5-199` | 已实现元数据结构；仅声明参数语义 |
| `CMD_INFO` | 命令中文名、英文名、说明、返回类型、参数表、状态位 | `elib/lib2.h:297-364`；`javalib_cmdInfo.cpp:206-216` | 已实现注册 |
| `LIB_DATA_TYPE_INFO` | 自定义类型名称、成员命令索引、枚举元素 | `elib/lib2.h:693-729`；`javalib_dtType.cpp:39-67` | 已实现注册 |
| `LIB_DATA_TYPE_ELEMENT` | `数组类型` 枚举成员的值和名称 | `javalib_dtType.cpp:24-37` | 已实现注册 |
| `LIB_CONST_INFO` | 库常量名称和值 | `elib/lib2.h:735-748`；`javalib_const.cpp:4-19` | 已实现注册 |
| `MDATA_INF` | 命令输入/输出的联合数据载体，含 `m_dtDataType` | `elib/lib2.h:780-824` | ABI 已定义；当前命令未正确产出结果 |
| `LIB_INFO` | 支持库总登记：版本、GUID、类型、命令、常量、通知函数 | `elib/lib2.h:1246-1318`；`javalib_dllMain.cpp:31-87` | 已实现动态库登记 |
| JVM/JNI 句柄 | 目标中的类、对象、字段、方法、字符串、数组、异常标志符 | 命令说明和参数表中以 `SDT_INT` 传递 | 仅声明；未见底层句柄生命周期实现 |

`MDATA_INF` 的文本/字节集输入是只读指针，通用变量参数通过 `m_pByte`，整数输出变量通过 `m_pInt`，逻辑输出变量通过 `m_pBool`。这些是调用约定，不等于当前函数已经执行相应的 JNI 读写。

## 7. 真实调用链与接口

### 7.1 动态库装载接口

```text
易语言装载器
  → LoadLibrary（工程目标为 DynamicLibrary）
  → 按 Source_javalib.def 查找 GetNewInf
  → GetNewInf()
  → LIB_INFO
  → 读取 m_pDataType / m_pBeginCmdInfo / m_pCmdsFunc / m_pLibConst
```

- `.def` 第 1—4 行只导出 `GetNewInf`。
- `GetNewInf` 在 `javalib_dllMain.cpp:89-92` 返回 `PLIB_INFO`。
- `LIB_INFO` 的库名为 `Java支持库`，GUID 为 `F3DA9F65E55F47cb8A8DAC95A189F4B1`，主/次/构建版本为 `2.0.0`，要求易语言系统 `3.7`、系统核心支持库 `3.7`，Windows 状态由 `_LIB_OS(__OS_WIN)` 给出。

### 7.2 命令调用接口

```text
易语言编译器按照 CMD_INFO 生成调用
  → 通过 m_pCmdsFunc[index] 取函数指针
  → PFN_EXECUTE_CMD(pRetData, nArgCount, pArgInf)
  → javalib_<EnglishName>_<index>_javalib
  → 读取 pArgInf[1..nArgCount]
  → 当前没有 JNI/JVM 执行和结果写回
```

函数命名宏定义在 `elib/lib2.h:19-35`、`javalib_cmd_typedef.h:3-9`；函数 ABI 在 `elib/lib2.h:1234-1239`。

### 7.3 系统通知接口

```text
易语言系统
  → javalib_ProcessNotifyLib_javalib(NL_SYS_NOTIFY_FUNCTION, PFN_NOTIFY_SYS, ...)
  → ProcessNotifyLib()
  → 保存 s_pfnNotifySys
  → NotifySys() 转发 NRS_* 通知
```

`elib/fnshare.cpp:7-16,24-64` 实现回调保存/转发，`SetUserSysNotify` 在第 67—71 行保存用户回调并返回 `ProcessNotifyLib`。当前没有 Java 运行时通知处理证据。

### 7.4 静态库接口

`javalib_static.vcxproj` 将根目录源文件以 `StaticLibrary` 重新编译，Win32 Debug/Release 明确定义 `__E_STATIC_LIB;__E_FNENAME=javalib`。`include_javalib_header.h`、常量/命令/数据类型元数据和 `javalib_dllMain.cpp` 均有 `__E_STATIC_LIB` 条件分支。静态编译器如何消费 `g_cmdNamesjavalib`、通知函数名和依赖库列表，在当前仓库没有独立文档或测试证明，只能记录为工程预留契约。

## 8. 依赖与构建

### 8.1 工程配置

| 工程 | 输出 | 配置 | 工具集/目标 |
|---|---|---|---|
| `javalib.vcxproj` | DynamicLibrary | Debug/Release × Win32/x64 | `PlatformToolset=v141`；`WindowsTargetPlatformVersion=10.0.15063.0`；Win32 目标扩展为 `.fne` |
| `javalib_static/javalib_static.vcxproj` | StaticLibrary | Debug/Release × Win32/x64 | `PlatformToolset=v141`；Win32 配置定义 `__E_STATIC_LIB` |

`javalib.sln` 提供 `Debug|x86`、`Debug|x64`、`Release|x86`、`Release|x64` 四种方案，并将 x86 映射到项目的 `Win32`。

### 8.2 直接依赖

- Visual C++/MSBuild 工程体系；
- Windows DLL/静态库 ABI（`HMODULE`、`DllMain`、`WINAPI` 等）；
- 随仓库提供的 `elib` 易语言支持库 SDK 头文件和辅助源码；
- 目标设计上依赖目标机器的 Java Runtime Environment（JRE），这一点只出现在库说明字符串 `javalib_dllMain.cpp:46`，当前源码未形成可验证的 JVM/JRE 链接和加载实现；
- 工程未声明外部包管理器、NuGet、CMake、Make、Java Maven/Gradle 或数据库依赖。

### 8.3 工程风险/待核

1. 动态库工程的 x64 配置没有 `__E_FNENAME=javalib`，而 `lib2.h` 明确要求使用前定义 `__E_FNENAME`；是否由外部属性表/编译环境补充，当前未验证。
2. 静态库工程的 x64 配置没有 `__E_STATIC_LIB`、`__E_FNENAME=javalib`，且使用预编译头 `pch.h`，但仓库未提供 `pch.h`；x64 静态配置不能据此判定可构建。
3. 动态库 x64 配置没有 `ModuleDefinitionFile=Source_javalib.def`，而 Win32 配置有；x64 是否仍能导出 `GetNewInf` 未验证。
4. 工程未声明 `jni.h`、JDK include 目录、JVM import library 或 `jvm.dll` 加载路径；加上当前命令体为空，JRE 运行能力不能视作已实现。
5. 工程没有 post-build 部署、JRE 探测、类路径验证或运行时诊断脚本。

## 9. 测试、验证和当前结论

### 9.1 仓库内测试现状

- 未发现测试目录、测试源码、CI 配置、CTest、GoogleTest、单元测试框架或运行样例。
- `javalib_cmdInfo.cpp` 仅在 `_DEBUG` 下计算参数数组数量用于调试确认，不是测试套件。
- 当前工作环境为 macOS，不能直接执行该 Windows Visual Studio/MSBuild 工程；本轮未安装依赖、未启动服务、未生成构建物。

### 9.2 已完成的静态验证

- 人工读取并核对 `javalib.sln`、两个 `.vcxproj`、`.def`、本库所有 `.cpp/.h` 和 `elib` 核心 ABI 头文件；
- 从 `JAVALIB_DEF` 统计到 66 个命令，索引连续 `0`—`65`；
- 从 `javalib_cmdDef.cpp` 核对到 66 个同名命令函数；
- 核对 3 个数据类型、8 个数组枚举成员和 1 个库常量；
- 核对动态库唯一入口 `GetNewInf` 和命令函数指针表生成关系；
- 静态检查命令函数体：没有发现 JNI 调用、JVM 创建、`pRetData` 写回或实际异常处理；11 个函数体为空；
- `git ls-remote origin HEAD refs/heads/master` 与本地 `HEAD` 一致，均为 `8beeb2b303b75582218843e7f171ed795ac648e8`。

### 9.3 实现状态矩阵

| 能力层 | 源码已实现 | 仅声明/注册 | 未验证/缺口 |
|---|---|---|---|
| 易语言支持库元数据 | `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、数据类型、常量、函数名表 | — | Windows 装载实测未做 |
| DLL 入口 | `GetNewInf`、`.def` 导出声明、基础 `DllMain` | — | x64 导出未验证 |
| 通知回调 | `javalib_ProcessNotifyLib_javalib` 与 `elib/fnshare` 的回调保存/转发 | — | 与真实易语言系统联调未做 |
| 命令 ABI | 66 个 `PFN_EXECUTE_CMD` 符号和参数提取骨架 | Java 功能命令元数据 | 无实际 JNI/JVM 调用和返回值 |
| JVM 生命周期 | 无实际生命周期逻辑 | `创建/销毁/连接/断开/版本` 命令及说明 | JRE/JVM 创建、线程绑定、销毁均未验证 |
| JNI 类/对象/成员/方法 | 无实际 JNI 逻辑 | 相关命令、参数、返回类型 | 全部未验证 |
| 字符串/数组/异常/监视器 | 无实际逻辑 | 相关命令和枚举 | 全部未验证 |
| 动态/静态构建 | 工程文件和配置声明 | 静态编译通知名/依赖名契约 | Windows 构建、链接、运行均未验证 |

**首轮结论**：本仓库目前可确认的是一个易语言支持库的接口描述、ABI 注册和 Visual Studio 双工程骨架；不能据当前源码宣称 Java/JNI 功能已经实现或可运行。

## 10. Git 基线

- 仓库：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/javalib`
- 分支：`master`，跟踪 `origin/master`；远程：`https://gitee.com/JYtechnology/javalib.git`
- HEAD：`8beeb2b303b75582218843e7f171ed795ac648e8`
- 提交时间：`2022-12-19T16:56:17+08:00`
- 提交说明：`初始化仓库`
- 远程 `HEAD`/`master` 本轮只读查询结果与本地 HEAD 相同。
- 初始提交统计：23 个文件、5050 行新增；当前工作树在架构文档写入前为干净状态，本轮仅允许新增本文档，不应修改其他文件或提交 Git。

## 11. 证据路径索引

| 主题 | 证据路径 |
|---|---|
| Solution 项目和平台 | `javalib.sln:5-38` |
| 动态库源文件、输出类型、工具集、Win32 `.fne` | `javalib.vcxproj:21-48,51-76,95-125,132-152` |
| 静态库源文件、`__E_STATIC_LIB`、输出类型 | `javalib_static/javalib_static.vcxproj:21-45,48-73,92-128` |
| DLL 导出 | `Source_javalib.def:1-4` |
| 命令名、索引、返回类型、状态 | `javalib_cmd_typedef.h:3-18`（清单延续至第 78 行） |
| 命令函数骨架 | `javalib_cmdDef.cpp:1-680` |
| 参数元数据 | `javalib_cmdInfo.cpp:1-218` |
| 数据类型和枚举 | `javalib_dtType.cpp:4-69` |
| 库常量 | `javalib_const.cpp:3-20` |
| `LIB_INFO`、函数表、入口和通知 | `javalib_dllMain.cpp:5-178` |
| 公共支持库 ABI | `elib/lib2.h:266-364,693-748,780-824,1225-1318` |
| 系统通知/辅助转发 | `elib/fnshare.cpp:1-71`、`elib/fnshare.h:21-55` |
| 基础类型和 Windows 兼容定义 | `elib/mtypes.h:1-176` |
| 语言版本 | `elib/lang.h:1-18` |
| SDK/IDE 辅助接口 | `elib/PublicIDEFunctions.h:1-493`、`elib/untshare.h:1-337` |

## 12. 后续复核建议（不代表已启动实现）

1. 在隔离的 Windows + Visual Studio 环境先修复/确认 x64 工程预处理宏、`.def` 导出和静态库 `pch.h`/配置问题，再做最小空库装载验证。
2. 明确 JDK/JRE 支持策略：动态加载 `jvm.dll` 还是链接 JNI import library，记录位数、JRE 版本、`java.class.path`/`java.library.path` 和错误传递契约。
3. 以 `创建 → 加载类 → 取方法标志符 → 创建对象/调用方法 → 异常读取 → 销毁引用 → 销毁 JVM` 为最小真实闭环，逐命令补实现并添加 Windows 集成测试。
4. 为每个命令验证返回值、`pRetData` 类型、变量输出和失败路径，特别是 `_SDT_ALL`、文本/字节集内存释放、全局/局部引用、线程附着和异常清理。
5. 将“元数据存在”与“JNI 行为可运行”分别纳入构建/测试门禁，避免接口声明被误认为功能完成。
