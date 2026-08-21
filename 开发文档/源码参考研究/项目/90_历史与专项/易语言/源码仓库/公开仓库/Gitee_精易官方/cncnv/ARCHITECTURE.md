# cncnv 架构档案

> 首轮全量建档。本文是本项目唯一的架构事实源；源码参考库按只读方式研究。本次只新增本文件，不修改源码、工程配置或 Git 历史，不安装依赖、不构建、不启动服务。

## 1. 项目定位

`cncnv` 是一个面向易语言的 Windows 支持库工程，目标是提供“文字编码转换支持库”。工程声明了一个全局命令“内码转换”，支持文本在 GBK、BIG5、简体/繁体、SJIS 等编码方向之间转换；但当前提交中的命令实现只有参数读取，没有实际转换和返回值写入，因此仓库现状更接近支持库接口/工程骨架，而不是可用的转换实现。

它同时维护两种产物工程：

- `cncnv.vcxproj`：Visual C++ 动态库（Win32 配置将目标扩展设为 `.fne`，x64 配置未设置该属性）。
- `cncnv_static/cncnv_static.vcxproj`：Visual C++ 静态库，复用父目录的同一批 `.cpp/.h` 源码，并通过 `__E_STATIC_LIB` 切换编译路径。

## 2. 真实运行/装载流程

```text
易语言 IDE / 编译器
        │
        │ 加载支持库文件；查找固定入口 GetNewInf
        ▼
cncnv 动态库（cncnv.vcxproj）
        │
        ├─ GetNewInf()
        │      └─ 返回 g_LibInfo_cncnv_global_var
        │             ├─ 库格式/GUID/版本/系统要求
        │             ├─ 类别：0000内码转换
        │             ├─ 命令元数据：g_cmdInfo_cncnv_global_var
        │             ├─ 命令函数表：g_cmdInfo_cncnv_global_var_fun
        │             ├─ 常量表：g_ConstInfo_cncnv_global_var（7 项）
        │             └─ 自定义类型表：空（count=0）
        │
        ├─ cncnv_ProcessNotifyLib_cncnv(nMsg, dwParam1, dwParam2)
        │      ├─ NL_SYS_NOTIFY_FUNCTION → 转发到 elib/fnshare.cpp
        │      │      └─ 记录 PFN_NOTIFY_SYS，并查询 NRS_GET_PRG_TYPE
        │      ├─ NL_GET_CMD_FUNC_NAMES → 返回静态编译用函数名表
        │      ├─ NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名
        │      ├─ NL_GET_DEPENDENT_LIBS → 返回空依赖列表 "\\0\\0"
        │      ├─ 其余已知通知 → 当前空处理，返回 NR_OK
        │      └─ 未知通知 → 返回 NR_ERR
        │
        └─ 生成的命令函数 cncnv_CNCnv_0_cncnv
               ├─ pArgInf[0].m_pText → arg1（待转换文本）
               ├─ pArgInf[1].m_int  → arg2（转换方式）
               └─ 当前没有转换、分配、写 pRetData 或错误返回逻辑
```

静态库路径如下：

```text
cncnv_static.vcxproj（StaticLibrary，复用父目录源文件）
        │ 预定义 __E_STATIC_LIB
        ├─ cncnv_cmdDef.cpp → 保留命令函数实现
        ├─ cncnv_dllMain.cpp → 排除 DllMain/LIB_INFO 动态库数据段
        │                       保留 cncnv_ProcessNotifyLib_cncnv
        ├─ cncnv_const.cpp / cncnv_dtType.cpp / cncnv_cmdInfo.cpp
        │                       由 #ifndef __E_STATIC_LIB 排除
        └─ elib/fnshare.cpp → 保留通知转发与内存/系统通知辅助函数
```

## 3. 版本基线与现场状态

- 本地根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/cncnv`
- 本地分支：`master`
- 本地 HEAD：`c2ee4f81d268853f73a14ad0b68062c0da0a7302`
- HEAD 提交时间：`2022-12-19T16:53:22+08:00`
- HEAD 提交说明：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/cncnv.git`
- 现场 `git ls-remote origin HEAD refs/heads/master` 返回同一提交 `c2ee4f81d268853f73a14ad0b68062c0da0a7302`；本地与远程 `master` 在本次检查时一致。
- Git 仓库为浅克隆（`git rev-parse --is-shallow-repository` 返回 `true`），当前可见历史只有一个 grafted 提交，不能据此推断更早版本演进。
- 建档前工作树无源码和工程改动；本次新增本文件后，预期唯一工作树变化是未跟踪的 `ARCHITECTURE.md`。

## 4. 真实目录与文件职责

仓库实际跟踪 23 个文件，没有 README、测试目录、脚本目录、包管理文件、第三方二进制或资源文件。

```text
cncnv/
├── ARCHITECTURE.md                 # 本次新增的唯一架构档案
├── cncnv.sln                       # VS 解决方案，包含动态库与静态库两个项目
├── cncnv.vcxproj                   # 动态库项目
├── cncnv.vcxproj.filters           # VS 文件筛选器
├── cncnv.vcxproj.user              # VS 用户级项目设置
├── cncnv_static/
│   ├── cncnv_static.vcxproj        # 静态库项目，引用父目录源文件
│   ├── cncnv_static.vcxproj.filters
│   └── cncnv_static.vcxproj.user
├── Source_cncnv.def                # 动态库模块定义，仅导出 GetNewInf
├── include_cncnv_header.h          # 项目聚合头、全局表声明、命令声明宏
├── cncnv_cmd_typedef.h             # 单一命令定义表 CNCNV_DEF 与符号拼接宏
├── cncnv_cmdDef.cpp                # 命令执行函数；当前为未完成骨架
├── cncnv_cmdInfo.cpp               # 参数/命令元数据（动态库路径）
├── cncnv_const.cpp                 # 7 个编码转换常量（动态库路径）
├── cncnv_dtType.cpp                # 自定义数据类型表（当前为空）
├── cncnv_dllMain.cpp               # DllMain、LIB_INFO、GetNewInf、通知入口
└── elib/                           # 易语言支持库 ABI/运行时共享头与辅助实现
    ├── fnshare.cpp                 # PFN_NOTIFY_SYS 保存、通知转发、版本查询
    ├── fnshare.h                   # ealloc/efree、Clone*、NotifySys 等辅助接口
    ├── lib2.h                      # 支持库 ABI 主定义、数据类型、元数据、通知号
    ├── lang.h                      # 语言编码版本常量（本库使用 GBK=1）
    ├── krnllib.h                   # 系统核心支持库类型/组件常量
    ├── mtypes.h                    # 基础 Windows 风格类型兼容定义
    ├── untshare.h                  # 单元/属性等较大范围共享实现（本项目未直接引用）
    └── PublicIDEFunctions.h        # IDE 公共功能通知/函数编号（本项目未直接引用）
```

### 4.1 源码分层

| 层 | 文件 | 责任 | 当前状态 |
|---|---|---|---|
| 支持库入口/生命周期 | `cncnv_dllMain.cpp` | 提供 `DllMain`、`GetNewInf`、通知分发与库描述 | 元数据和通知骨架完整；多数通知空处理 |
| 命令契约 | `cncnv_cmd_typedef.h`、`cncnv_cmdInfo.cpp` | 用 `CNCNV_DEF` 单一来源生成命令声明、元数据、函数表/函数名表 | 一个命令、两个参数的描述完整 |
| 命令执行 | `cncnv_cmdDef.cpp` | 实现 `cncnv_CNCnv_0_cncnv` | 仅读取参数，功能未实现 |
| 常量/类型元数据 | `cncnv_const.cpp`、`cncnv_dtType.cpp` | 向 IDE 暴露常量和自定义类型 | 常量 7 项；自定义类型 0 项 |
| 运行时桥接 | `elib/fnshare.cpp/.h` | 系统通知函数、分配释放、复制文本/字节数据等 | 已实现通用桥接；未被命令实现使用 |
| ABI 头文件 | `elib/lib2.h` 等 | 定义 `MDATA_INF`、`CMD_INFO`、`LIB_INFO`、通知号和系统类型 | 主要是随库源码携带的 SDK 兼容层 |

## 5. 命令、常量与 ABI 契约

### 5.1 命令定义

`cncnv_cmd_typedef.h` 的 `CNCNV_DEF(_MAKE)` 是单一命令清单。当前唯一条目为：

- 内部显示名：`内码转换`
- 英文/符号名：`CNCnv`
- 生成实现符号：`cncnv_CNCnv_0_cncnv`（由 `__E_FNENAME=cncnv` 和索引 `0` 拼接）
- 说明：将指定汉字编码的文本转换为另外一种编码方式，非汉字部分不受影响，返回转换结果文本
- 类别：`1`，对应 `LIB_INFO.m_szzCategory = "0000内码转换\\0\\0"`
- 操作系统：`_CMD_OS(__OS_WIN)`
- 返回类型：`SDT_TEXT`
- 参数数：`2`

`include_cncnv_header.h` 再以 `CNCNV_DEF(CNCNV_DEF_CMD)` 展开声明执行函数；`cncnv_cmdInfo.cpp` 以同一清单展开 `CMD_INFO` 元数据；`cncnv_dllMain.cpp` 以同一清单展开执行函数指针表和静态编译用函数名表。这样可以避免命令数量或顺序在多张表之间手工漂移，但也要求新增命令时同步保证其实现、参数数组和构建宏条件存在。

### 5.2 参数契约

`cncnv_cmdInfo.cpp` 中 `g_argumentInfo_cncnv_global_var` 有两项：

1. `待转换文本`：`SDT_TEXT`，无默认值/特殊接收标志。
2. `转换方式`：`SDT_INT`，取值 1～7，分别为 `GBK到BIG5`、`BIG5到GBK`、`GBK繁体到简体`、`GBK简体到繁体`、`BIG5到GBK简体`、`GBK到SJIS`、`SJIS到GBK`。

执行函数收到 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`。当前源码读取 `pArgInf[0].m_pText` 与 `pArgInf[1].m_int`，但：

- 没有检查 `nArgCount`、空指针、参数类型或转换方式范围；
- 没有调用 Windows 编码 API、转换表或任何第三方编码库；
- 没有通过 `pRetData` 写入 `SDT_TEXT` 结果，也没有分配/释放返回文本；
- 因此不能从源码证明“命令会完成编码转换”或“调用后返回有效文本”。

`lib2.h` 的 ABI 定义中，`MDATA_INF` 的文本返回槽是 `m_ppText`，文本所有权需遵守运行时分配/释放约定；这只是框架契约，当前 `cncnv_cmdDef.cpp` 没有实施该契约。

### 5.3 常量与自定义类型

`cncnv_const.cpp` 在动态库编译路径下暴露 7 个 `LIB_CONST_INFO` 数值常量，数值为 1～7，与参数说明一一对应。它们没有单独的英文名和解释字段。

`cncnv_dtType.cpp` 声明 `g_DataType_cncnv_global_var[1]`，但 `g_DataType_cncnv_global_var_count = 0`，所以库对外没有有效自定义数据类型。

## 6. 动态库入口与通知边界

### 6.1 `GetNewInf`

`Source_cncnv.def` 仅列出：

```text
EXPORTS
    GetNewInf
```

`cncnv_dllMain.cpp` 的 `GetNewInf()` 返回静态 `g_LibInfo_cncnv_global_var` 地址。该结构包含：

- `LIB_FORMAT_VER`；
- 固定 GUID `63AA4BEA120C4DABAD567115556DE054`；
- 版本 `2.0.50`；
- 要求易语言系统 `3.6`、系统核心支持库 `3.0`；
- 名称“文字编码转换支持库”、语言 `__GBK_LANG_VER`、平台 `_LIB_OS(OS_ALL)`；
- 1 个命令类别、1 个命令、7 个常量、0 个自定义类型；
- `m_pfnNotify = cncnv_ProcessNotifyLib_cncnv`；
- `m_szzDependFiles = NULL`。

### 6.2 通知处理

`cncnv_ProcessNotifyLib_cncnv` 的已编码边界：

- `NL_SYS_NOTIFY_FUNCTION`：把系统通知函数指针转交 `ProcessNotifyLib`；
- `NL_GET_CMD_FUNC_NAMES`：动态库路径返回 `g_cmdNamescncnv`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回文本 `cncnv_ProcessNotifyLib_cncnv`；
- `NL_GET_DEPENDENT_LIBS`：返回空的双零字符串；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前仅空代码块，保持 `NR_OK`；
- 默认分支：`NR_ERR`。

该库没有设置 `LBS_IDE_PLUGIN`，所以依赖该标志的 IDE 插件通知即使代码分支存在，也不能仅凭当前 `LIB_INFO` 证明会被系统投递。

`elib/fnshare.cpp` 的 `ProcessNotifyLib` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时保存 `PFN_NOTIFY_SYS`，首次通知时通过 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 更新调试/发布状态；同时支持 `SetUserSysNotify` 注册一个用户回调，回调存在时会接收通知并覆盖返回值。

## 7. 技术栈与依赖边界

| 类别 | 事实 |
|---|---|
| 语言 | C/C++；工程使用 `.cpp/.h`，包含大量 Windows/易语言 ABI 定义 |
| 构建系统 | Visual Studio `.sln` + MSBuild `.vcxproj`，解决方案格式 12.00，VS 17 文件头 |
| 编译器工具集 | 工程配置为 `v141` |
| Windows SDK | `WindowsTargetPlatformVersion = 10.0.15063.0` |
| 目标 | 动态库 `DynamicLibrary` 与静态库 `StaticLibrary`；解决方案有 Win32/x64 的 Debug/Release 配置 |
| 字符集 | `Unicode` 工程属性；源码中文内容实际以本地 GB18030/CP936 可正确解码的文本存在，库元数据也声明 `__GBK_LANG_VER` |
| 系统头 | `elib/lib2.h` 包含 `<windows.h>`、`<stdio.h>`、`<math.h>`、`<assert.h>` |
| 本地 SDK/ABI | `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`、`elib/fnshare.h` |
| 外部库 | `LIB_INFO.m_szzDependFiles = NULL`，通知接口的 `NL_GET_DEPENDENT_LIBS` 返回 `"\\0\\0"`；没有包管理文件或第三方依赖声明 |
| 编码转换实现依赖 | 当前没有任何已确认的实现依赖；源码未出现转换 API、查表数据或第三方编码库调用 |

`mtypes.h` 提供 `DWORD`、`INT`、`LPBYTE`、`WINAPI` 等基础类型兼容定义；`lib2.h` 是真正的 ABI 核心，定义 `DATA_TYPE`、`ARG_INFO`、`CMD_INFO`、`MDATA_INF`、`LIB_INFO`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_SYS` 以及通知号。`krnllib.h` 和 `untshare.h` 是随工程携带的易语言核心/单元共享头，但当前业务源文件没有直接 include `untshare.h` 或 `PublicIDEFunctions.h`。

## 8. 工程配置与可疑点

### 8.1 动态库项目

- `cncnv.vcxproj` 的 Win32 Debug/Release 明确设置 `__E_FNENAME=cncnv`、`CNCNV_EXPORTS`、`TargetExt=.fne`，并链接 `Source_cncnv.def`。
- x64 Debug/Release 没有设置 `__E_FNENAME=cncnv`，也没有 `ModuleDefinitionFile`，没有 `.fne` 目标扩展配置。由于 `elib/lib2.h` 在未定义 `__E_FNENAME` 时会预处理报错，且命令/入口命名依赖该宏，x64 可构建性和输出格式需要在 Windows/VS 环境中单独复核；本次未构建。
- Release 使用静态运行库 `MultiThreaded`，Debug 使用 `MultiThreadedDebug`；警告级别为 Level3，开启 SDL 检查。

### 8.2 静态库项目

- `cncnv_static.vcxproj` 复用动态库相同的 6 个 `.cpp` 和 9 个项目头文件，Win32 Debug/Release 定义 `__E_STATIC_LIB`、`__E_FNENAME=cncnv`；静态库项目类型为 `StaticLibrary`。
- 静态路径下 `cncnv_cmdInfo.cpp`、`cncnv_const.cpp`、`cncnv_dtType.cpp` 中的动态库元数据被预处理排除；`cncnv_dllMain.cpp` 的 `DllMain`、`LIB_INFO`、动态数组也被排除，但通知函数和命令实现仍编译。
- 静态库 x64 Debug/Release 未见 `__E_FNENAME=cncnv` 定义；同时 x64 配置将 `PrecompiledHeader` 设为 `Use`、指定 `pch.h`，而仓库文件清单中没有 `pch.h`。这两点均可能影响 x64 构建，但未通过实际构建确认。
- 解决方案把 `Debug|x86/Release|x86` 映射到项目的 `Win32`，把 x64 映射到项目的 `x64`；项目本身没有自定义构建后处理命令。

## 9. 测试与验证现状

- 仓库中没有测试目录、测试源文件、测试脚本、CI 配置或样例调用程序。
- 没有执行构建、运行、DLL 装载、易语言 IDE 集成测试或编码转换行为测试；原因是本次任务明确要求只读架构建档且不构建。
- 已完成的只读验证：
  - 读取解决方案、两个项目文件、筛选器、模块定义和全部业务源码/头文件；
  - 核对真实 Git 文件清单，共 23 个跟踪文件；
  - 核对本地分支、HEAD、远程 URL、远程 `HEAD/master` 提交；
  - 执行 `git diff --check`，在建档前无输出/无格式错误；
  - 确认不存在 README、`AGENTS.md`、测试文件和 `细探-*.md` 旧细探文件。

“文件存在”与“功能已验证”必须区分：当前只能确认接口元数据和编译条件写在源码中，不能确认 DLL 能够构建，也不能确认“内码转换”命令能够产生结果。

## 10. 旧细探收口与代码地图状态

- 目标根目录没有 `细探-*.md`，没有可吸收的旧细探内容；后续只维护本 `ARCHITECTURE.md`，不另建平行架构文档。
- 按任务要求先调用 `project_context`，但该工具返回的是当前活动项目 `~/Documents/Agent/PHP/华世王镞_v3` 的上下文/代码地图，不是本目标仓库，不能把它作为 `cncnv` 证据使用。
- 随后按要求调用 `codegraph_explore` 指向本项目，工具如实返回：目标路径向上没有 `.codegraph/`，因此项目未建立代码地图，无法查询符号图和调用图。本档案改用目标仓库的真实文件读取、工程文件和 Git 只读命令建档，没有伪造代码地图结论。

## 11. 未确认项与后续复核点

1. 在 Windows + VS `v141` + SDK `10.0.15063.0` 环境中分别验证 Win32/x64、动态/静态四类配置的实际编译结果，重点核对 `__E_FNENAME`、`.def`、`pch.h` 和输出扩展。
2. 补读易语言支持库 ABI 对动态库命名、静态库命令函数名表和 `GetNewInf` 的实际装载要求，确认工程的静态编译分支是否完整。
3. 实现或补证 `cncnv_CNCnv_0_cncnv` 的编码转换算法、输入编码/输出编码语义、非法字节处理、内存所有权和失败返回约定。
4. 为 7 个转换方向建立最小的 Windows 运行测试，覆盖中文、非中文、空文本、非法序列、未支持的 `arg2` 和大文本。
5. 核对源文件编码与 Visual Studio `CharacterSet=Unicode` 的关系，避免支持库元数据和源码中文字符串在编译产物中出现乱码。
6. 若要修改任何工程或源码，先由维护者确认是否脱离“只读源码参考库”边界；当前核对不做这些变更。

## 12. 证据索引

- 入口与库元数据：`cncnv_dllMain.cpp`
- 命令实现：`cncnv_cmdDef.cpp`
- 命令/参数元数据：`cncnv_cmdInfo.cpp`
- 命令单一来源和符号拼接：`cncnv_cmd_typedef.h`
- 项目聚合声明：`include_cncnv_header.h`
- 常量：`cncnv_const.cpp`
- 自定义类型：`cncnv_dtType.cpp`
- 动态库导出：`Source_cncnv.def`
- 动态库工程：`cncnv.vcxproj`
- 静态库工程：`cncnv_static/cncnv_static.vcxproj`
- ABI/运行时契约：`elib/lib2.h`、`elib/fnshare.h`、`elib/fnshare.cpp`
- 语言版本：`elib/lang.h`
- 核心支持库常量：`elib/krnllib.h`
- 基础类型：`elib/mtypes.h`
- IDE/单元共享边界：`elib/PublicIDEFunctions.h`、`elib/untshare.h`
- 版本和远程证据：Git `HEAD`、`origin/HEAD`、`origin/master`，均为 `c2ee4f81d268853f73a14ad0b68062c0da0a7302`

## 13. 后续：文本编码能力边界与底座裁决

当前核对不是把“内码转换”的注释当作算法实现，而是回答：如果把该项目的价值收敛进一个通用文本编码支持库，哪些内容属于支持库 owner，哪些内容必须留在系统/第三方提供者边界，以及怎样形成唯一能力链。以下分为源码事实和平台候选裁决；候选裁决不代表本仓库已经实现。

### 13.1 编码事实的四个不同层次

| 层次 | 本仓库可证事实 | 不能据此推出的结论 |
|---|---|---|
| 源文件编码 | C++ 源文件中的中文文本可按本地 `GB18030/CP936` 解码；项目文件将 `CharacterSet` 设为 `Unicode` | `CharacterSet=Unicode` 不会把 `char*` 自动变成 Unicode，也不证明运行时完成了编码转换 |
| 支持库语言标识 | `elib/lang.h` 定义 `__GBK_LANG_VER=1`，并将 `__COMPILE_LANG_VER` 设为该值；`GetNewInf` 将语言写入 `LIB_INFO` | 这是支持库/编译语言元数据，不是输入文本的实际编码探测结果 |
| ABI 文本形状 | `elib/lib2.h` 的 `SDT_TEXT` 使用 `char* m_pText`；输入注释要求不能为 NULL、只读；返回槽是 `char** m_ppText` | `SDT_TEXT` 没有携带“GBK/BIG5/SJIS”标签，调用者与命令必须另行约定编码语义 |
| 转换算法 | `cncnv_cmd_typedef.h` 只声明 7 个方向；`cncnv_cmdDef.cpp` 仅读取 `m_pText` 与 `m_int` 后结束 | 当前没有 Windows 转换 API、Unicode 中间态、转换表、第三方库调用、非法序列策略或结果写回 |

因此，平台若吸收此项目，吸收的是“文本编码转换命令的候选契约和易语言 ABI 适配形状”，不是一个已经可复用的转换内核。`lang.h` 的 GBK 标识、源文件的本地编码、命令输入字节编码和输出字节编码必须在契约中分别命名，不能用“中文编码”一个词混在一起。

### 13.2 中文编码/转换支持库应负责什么

候选公共支持库落点为 `文本编码`（能力 id 建议为 `文本编码.转换`，仅作后续设计名，当前仓库没有该平台注册表）。它的唯一 owner 应负责：

1. **规范化编码标识**：维护 `gbk/cp936`、`big5`、`shift_jis`、`utf-8` 等稳定枚举或名称；历史的 `GBK到BIG5` 等中文常量只能在一个入口归一化，不能由每个消费者重新解释数字 1～7。
2. **定义输入输出语义**：输入是带明确编码的字节串，输出是带明确编码的字节串；若兼容易语言 `SDT_TEXT`，必须声明它实际承载的代码页，不能宣称“自动识别”。平台内部可采用 Unicode 中间表示，但中间表示不向消费者泄漏。
3. **定义字符边界**：按字节长度读取编码输入，按编码规则验证多字节序列；不得在 DBCS 的第二字节中间截断、按 C/C++ `char` 个数误算字符数，或把 `NUL` 当成可安全嵌入文本内容。输出长度变化时必须新分配，不能原地覆盖输入。
4. **定义转换策略**：明确非法字节、半个多字节字符、目标编码不可表示字符、组合/兼容字符、控制字符和空文本的行为。默认应是严格失败并返回稳定错误；替换字符、忽略字符或近似转换必须作为显式策略，不能隐藏 fallback。
5. **定义结果与错误**：统一返回结果、源编码、目标编码、输入/输出字节数、是否发生替换和诊断信息；消费者不得自行翻译 Windows、iconv 或第三方错误文本。
6. **定义资源所有权**：输入为借用只读视图；输出由支持库创建并交给明确 owner；跨易语言 ABI 写入前释放旧 `*m_ppText`，新值使用 ABI 认可的分配器；失败路径不得泄漏半成品。
7. **定义上限和可观测性**：限制输入字节数、输出字节数、转换膨胀比例和单次耗时；记录 provider、实际编码、替换数、错误码和资源清理结论，但不得记录原文或密钥。

文档解析、CSV/JSON、HTTP、文件读写等上层模块只组合 `文本编码.转换`，不拥有编码表、代码页别名、错误翻译或第三方库句柄。`cncnv` 的 `内码转换` 只能作为兼容适配入口，不能成为第二个文本编码内核。

### 13.3 字符、字节和返回内存边界

源码中已经出现三个必须固定的边界：

- `cncnv_cmdDef.cpp:6-11`：命令签名为 `PFN_EXECUTE_CMD`，当前直接取 `pArgInf[0].m_pText` 和 `pArgInf[1].m_int`，没有检查 `nArgCount`、指针、数据类型和方式范围。
- `elib/lib2.h:780-824`：`m_pText` 是输入文本指针，注释要求只读；`m_ppText` 是返回变量地址，写入前必须释放原值，再换入新指针。
- `elib/fnshare.h:25-102`：`ealloc/efree` 通过 `NotifySys(NRS_MALLOC/NRS_MFREE)` 管理易语言内存；`CloneTextData` 以 `lstrlenA` 和 `char` 字节复制，空指针/空首字节返回 NULL；`CloneTextDataW` 则按 `wchar_t` 字节数复制。

由此形成以下边界裁决：

| 边界 | 支持库必须保证 | 禁止的误用 |
|---|---|---|
| 输入借用 | 在调用期间只读，验证 `nArgCount`、`m_dtDataType`、指针和字节上限 | 修改 `m_pText`、把它当可扩容缓冲区、把 `strlen` 当字符数 |
| 多字节字符 | 以源编码解析完整序列，再转 Unicode/目标编码；截断只能发生在完整字符边界 | 在 GBK/BIG5/SJIS 双字节中间切片，或把高位字节一律当乱码 |
| 空与 NUL | 契约明确空文本、不可为 NULL 和嵌入 NUL 的区别；当前 ABI 文本是 C 字符串形状，默认不能承载嵌入 NUL | 把 NULL、空串、单个 NUL、长度为零的字节集混成一种情况 |
| 返回所有权 | 新建输出后再写 `m_ppText`；写入前按 ABI 规则释放旧值；异常时释放临时缓冲 | 直接把栈内存、provider 缓冲区或输入指针写进返回槽；成功返回但实际指针悬空 |
| 失败恢复 | 失败结果携带稳定错误码、源/目标编码和已清理状态 | 只返回空串掩盖失败、静默替换、跨 provider 传播原生异常 |

`fnshare.h` 的复制辅助只是可复用的 ABI 边界工具，不是字符转换实现；它按 `char`/`wchar_t` 拷贝也不等于完成 GBK、BIG5、SJIS 与 Unicode 之间的合法性校验。未来实现必须先冻结“字节串 + 编码标签”的内部契约，再选择转换 provider。

### 13.4 第三方库与系统库的归属边界

当前源码明确没有调用 `MultiByteToWideChar`、`WideCharToMultiByte`、`iconv` 或其他转换库；`LIB_INFO.m_szzDependFiles=NULL`、`NL_GET_DEPENDENT_LIBS` 返回双零字符串也只说明当前没有声明静态依赖，不能反推转换已由系统完成。

建议的边界如下：

| 组件 | 归属 | 对外暴露 | 本项目现状 |
|---|---|---|---|
| 文本编码契约/别名/边界/错误 | `支持库/后端/文本编码` 的公共 owner | `文本编码.转换` 及统一结果 | 尚不存在，属于底座候选 |
| Windows `MultiByteToWideChar` / `WideCharToMultiByte` | 受管系统 provider | 只返回规范化结果和稳定错误 | 源码未调用，待 Windows 实测 |
| `iconv` 或其他第三方转换库 | 可替换 provider/独立适配层 | 不泄漏 `iconv_t`、库错误码、第三方对象 | 无第三方依赖声明 |
| 易语言 ABI | `cncnv` 项目适配层 | `GetNewInf`、`PFN_EXECUTE_CMD`、`MDATA_INF`、`NotifySys` | 已有框架边界，但命令未接通转换 |
| 文件/网络/文档模块 | 上层模块 | 传递编码标签和字节结果 | 不应把编码算法复制进去 |

系统 API 或第三方库只能作为 provider，不能成为平台公共契约。provider 的加载失败、函数返回失败、不可表示字符和版本不兼容都必须在 provider 边界转成平台稳定错误。若 provider 需要动态库句柄、转换上下文或独立进程，句柄和进程只能留在支持库/运行核心内，不能穿透到调用方。

### 13.5 当前实现链与唯一目标链

**当前源码能证明的链只有：**

```text
易语言装载器
  → 导出 GetNewInf（Source_cncnv.def）
  → g_LibInfo_cncnv_global_var（cncnv_dllMain.cpp）
  → g_cmdInfo_cncnv_global_var / g_cmdInfo_cncnv_global_var_fun
  → cncnv_CNCnv_0_cncnv（cncnv_cmdDef.cpp）
  → 读取 m_pText、m_int
  → 结束；没有转换、返回写入或命令错误结果
```

**底座的唯一目标链应收敛为：**

```text
易语言兼容入口「内码转换」/平台公开调用
  → 唯一入口：文本编码.转换
  → 参数规范化：源编码、目标编码、字节视图、错误策略、长度/预算
  → 唯一能力注册表 owner
  → 受管文本编码 provider（优先系统 API；必要时第三方/隔离 provider）
  → Unicode 中间态与目标编码编码器
  → 统一结果/错误/诊断
  → ABI 适配层分配输出并写入 m_ppText
  → 释放临时缓冲、记录证据、返回调用方
```

固定规则：

- 一个原子功能只有 `文本编码.转换` 一个规范能力 id、一个契约 owner 和一个注册/调用入口；`cncnv.CNCnv`、数字 1～7 和英文历史键只能在兼容入口归一化。
- provider 只实现编码算法和宿主调用，不实现第二套参数校验、错误表、权限、资源监督或结果包装。
- `cncnv` 适配层不应直连多个 provider；provider 选择由唯一能力调用器按宿主能力、版本和策略完成。
- 任何模块直连 `WideCharToMultiByte`、`iconv` 或 provider 私有对象均属侧链；任何消费者自行把 `ERROR_NO_UNICODE_TRANSLATION` 等原生错误翻译成另一套错误码均属契约漂移。
- 若系统 provider 与第三方 provider 结果不一致，先按同一输入/输出/错误/替换契约验证，再裁决唯一默认 provider；不以“能返回字符串”作为通过标准。

### 13.6 资源生命周期与失败矩阵

| 资源/对象 | 创建/持有 | 正常释放 | 失败、超时、取消、崩溃 | owner 与当前证据 |
|---|---|---|---|---|
| `pArgInf[0].m_pText` 输入指针 | 易语言运行时借给命令 | 命令不释放、不修改 | 参数非法时立即返回；不保存到异步任务 | 易语言运行时；`lib2.h:793`，当前仅读取 |
| 转换临时缓冲/Unicode 中间态 | 文本编码 provider 在单次调用内创建 | 转换结束后释放 | 任一转换错误、异常或超限都进入统一清理；不返回裸指针 | provider/支持库；当前不存在 |
| `m_ppText` 输出缓冲 | ABI 适配层按易语言分配器创建 | 写入前释放旧值；新 owner 交给易语言变量 | 分配失败不覆盖旧值；写入失败释放新值；崩溃由宿主回收 | ABI 适配层；`lib2.h:811`，当前未写回 |
| `NotifySys`/`ealloc`/`efree` 回调 | `NL_SYS_NOTIFY_FUNCTION` 注入 `PFN_NOTIFY_SYS` | 库卸载前不再调用；库不关闭宿主回调 | 回调为空时返回 0；不能把空回调当分配成功 | 易语言宿主；`elib/fnshare.cpp:7-16,24-35` |
| 系统 API 句柄/第三方 context | 若 provider 需要，在一次调用或受管租约内创建 | `finally`/RAII 关闭；不跨公开契约 | provider 异常、超时、宿主崩溃后由运行核心核对零残留 | provider/运行核心；当前无此资源 |
| 诊断/证据 | 调用器创建结构化记录 | 返回前提交，不携带原文 | 失败也记录错误码、provider、清理结论；不能覆盖原始失败 | 平台运行核心；当前无证据账本 |

当前命令是同步空函数，源码没有线程、队列、取消、超时或异步句柄。因此不能把“没有看到泄漏”写成资源安全；只能说目标资源链尚未实现、未运行验证。若未来 provider 使用阻塞原生库或第三方扩展，超时/崩溃隔离应下沉到受管独立进程，不能在 ABI 命令函数内建立无界线程池。

### 13.7 L0-L4 验证等级与当前判定

本项目后续采用以下能力成熟度，不把声明、静态存在和真实运行混为一谈：

| 等级 | 进入条件 | 对文本编码能力的最小证据 | `cncnv` 当前判定 |
|---|---|---|---|
| **L0 声明骨架** | 有入口、命令名、参数/返回元数据或兼容符号 | 能定位 `GetNewInf`、`内码转换`、7 个方向常量和执行函数 | **达到 L0**：元数据和 ABI 框架存在 |
| **L1 契约冻结** | 输入/输出编码、字符边界、空/NUL、非法序列、替换策略、错误码、所有权、上限全部书面固定 | 同一契约可被 provider、适配层和测试共同引用 | **未达到**：源码只给中文说明和数字 1～7，无上述完整语义 |
| **L2 实现可调用** | 至少一个 provider 真实转换，统一结果/错误，返回内存按 ABI 正确交付 | 7 方向或明确子集有真实输出，错误与资源释放有证据 | **未达到**：`cncnv_cmdDef.cpp` 没有转换或 `pRetData` 写入 |
| **L3 集成可验收** | Windows 构建、动态/静态装载、易语言调用、边界/失败/资源测试通过 | 中文、ASCII、空、非法 DBCS、截断、不可表示、超长、重复调用和错误注入均有真实结果 | **未达到**：仓库无测试，当前核对未在 Windows 构建或运行 |
| **L4 底座生产能力** | 唯一能力注册/调用链、provider 可替换、权限/预算/超时/取消/崩溃清理、版本/回滚、证据和发布门禁齐全 | 运行期资源零残留、契约漂移和旁路扫描通过，默认 provider 有性能/兼容基线 | **未达到**：只能作为候选研究输入，不能进入生产底座 |

当前核对结论是“**源码事实吸收、实现能力待核**”：可以吸收单一命令清单、ABI 适配和资源契约观察；不能把当前仓库标记为已实现的中文转换支持库，也不能把 `cncnv` 直接登记为平台 `文本编码.转换` 的生产 provider。

## 14. 后续复用/升级/新建/废弃裁决

| 裁决 | 内容 | 依据 |
|---|---|---|
| 吸收 | `CNCNV_DEF` 单一命令清单、`GetNewInf`/通知入口、`MDATA_INF` 输入只读与返回槽所有权提示 | `cncnv_cmd_typedef.h`、`cncnv_dllMain.cpp`、`elib/lib2.h` |
| 升级候选 | 将“编码标识—字节边界—错误—输出所有权”抽成平台唯一 `文本编码.转换` 契约；把 `内码转换` 作为兼容别名 | 当前参数/常量只覆盖方向名，缺少稳定契约 |
| 待核 | Windows 系统 provider 对 GBK/BIG5/SJIS 的严格模式、不可表示字符和错误映射；是否需要第三方 provider | 当前源码完全没有 provider 调用，不能凭项目名选择 |
| 废弃/禁止 | 直接复制空的 `cncnv_CNCnv_0_cncnv` 作为平台实现；各模块直连系统 API；把数字 1～7 当全局契约 | 当前命令无转换、无返回、无错误；会形成第二能力链 |

### 当前核对验证边界

- 已做：目标仓库真实文件清单、源码/头文件只读解码、命令/ABI/分配辅助/工程配置静态核对；确认未调用转换 API、未定义第三方依赖、未实现命令返回。
- 未做：Windows/Visual Studio 构建，DLL/静态库装载，真实易语言调用，系统 API 转换行为，第三方库对比，内存泄漏/崩溃/超时测试。
- 环境问题：按任务要求调用了 `project_context`，但它错绑当前活动项目 `~/Documents/Agent/PHP/华世王镞_v3`；其代码地图和成功验证不属于 `cncnv`，当前核对不作为目标项目证据。目标仓库未建立可用 codegraph，故静态证据等级为弱验证。
- 只修改本文件；未修改源码、依赖、配置、测试、README、旧细探或 Git 历史。
