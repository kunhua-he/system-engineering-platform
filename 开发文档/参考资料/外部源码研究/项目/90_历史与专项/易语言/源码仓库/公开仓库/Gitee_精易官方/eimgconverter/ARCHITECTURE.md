# eimgconverter 架构建档

> 本文是本项目唯一的架构事实文档。首轮建档按只读方式完成：未修改源码、工程文件、依赖、测试或配置，未安装、未构建、未提交 Git。
>
> 旧细探检查结果：项目根及其上级 `Gitee_精易官方` 范围内未发现 `细探-*.md`；后续事实只维护本文件。

## 1. 项目定位与证据基线

### 1.1 项目身份

- 项目目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eimgconverter`
- 远程仓库：`https://gitee.com/JYtechnology/eimgconverter.git`
- 远程默认分支：`master`；本地分支：`master`
- 本地与远程 `HEAD`：`1b558a7644764cc79d2a839a4f40ba4592311083`
- 提交时间：`2022-12-19T16:54:58+08:00`
- 提交说明：`初始化仓库`
- Git 状态：工作树在建档前干净；仓库为浅克隆/单提交 grafted 历史，无标签、无其他分支提交可供比较。
- 仓库文件基线：Git 初始提交包含 23 个项目文件，共 4,228 行（按提交统计）；当前工作树还会新增本 `ARCHITECTURE.md`。

### 1.2 结论摘要

`eimgconverter` 是面向易语言的 Windows 图像格式转换支持库工程，采用 Visual C++ 支持库 ABI：通过 `GetNewInf` 返回 `LIB_INFO`，由元数据表暴露 10 个全局转换命令，再通过命令函数指针进入命令实现。

当前仓库实际落地的是“支持库外壳/接口骨架”，不是完整的图像编解码实现：

1. `eimgconverter_cmd_typedef.h`、`eimgconverter_cmdInfo.cpp` 已完整描述命令名、英文名、说明、参数、返回类型和默认值。
2. `eimgconverter_dllMain.cpp` 已实现库元信息、导出入口、命令函数表和系统通知分发壳。
3. `eimgconverter_cmdDef.cpp` 的 10 个命令函数只读取 `pArgInf` 到局部变量，没有图像读取、解码、编码、文件写入、错误码计算或 `pRetData` 返回值写入。
4. 项目未包含图像算法源码、图像格式第三方库、格式解析器、编码器、测试夹具或运行示例；工程文件也未声明额外图像库链接依赖。
5. 因此“支持读取/写入哪些格式”目前只能视为 `LIB_INFO`/命令说明中的产品契约线索，不能视为当前源码已实现并可运行的能力。

## 2. 总体流程

```text
易语言 IDE/运行时
    │
    │ 装载 .fne，按固定名称寻找 GetNewInf
    ▼
Source_eimgconverter.def
    │ 仅导出 GetNewInf
    ▼
eimgconverter_dllMain.cpp::GetNewInf
    │ 返回 g_LibInfo_eimgconverter_global_var
    ├── 库身份/版本/语言/OS/依赖声明
    ├── g_cmdInfo_eimgconverter_global_var（10 项命令元数据）
    ├── g_cmdInfo_eimgconverter_global_var_fun（10 项命令函数指针）
    ├── eimgconverter_ProcessNotifyLib_eimgconverter（系统通知入口）
    ├── 空的常量表、空的数据类型表
    └── 无额外依赖文件声明
    │
    │ 用户调用某个“转换到*”命令
    ▼
命令函数指针
    │ 由 eimgconverter_cmdDef.cpp 中 EIMGCONVERTER_NAME 生成符号
    ▼
eimgconverter_ConvertTo{格式}_{索引}_eimgconverter
    │ 当前仅把 pArgInf[0..N-1] 读入 arg1..argN
    ├── 没有读取源图像
    ├── 没有选择解码器/编码器
    ├── 没有写目标文件
    ├── 没有设置 pRetData
    └── 没有返回契约中的正数/负数错误码
    ▼
当前实现：函数返回 void，命令结果未被实现层写回

系统通知路径：
易语言系统 → eimgconverter_ProcessNotifyLib_eimgconverter
    ├── NL_SYS_NOTIFY_FUNCTION
    │     └── 转发到 elib/fnshare.cpp::ProcessNotifyLib
    │           ├── 保存 PFN_NOTIFY_SYS
    │           ├── 首次取得 NRS_GET_PRG_TYPE 更新调试/发布状态
    │           └── 再转发用户回调（若已设置）
    ├── NL_GET_CMD_FUNC_NAMES → 返回静态命令函数名数组（当前用 INT 承载指针）
    ├── NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名文本
    ├── NL_GET_DEPENDENT_LIBS → 返回空依赖列表
    ├── NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE / NL_IDE_READY 等 → 当前空处理
    └── 未知通知 → NR_ERR
```

## 3. 目录与职责地图

```text
eimgconverter/
├── eimgconverter.sln                         # VS 解决方案：动态库 + 静态库
├── eimgconverter.vcxproj                     # eimgconverter 动态库工程
├── eimgconverter_static/
│   ├── eimgconverter_static.vcxproj          # eimgconverter_static 静态库工程
│   ├── *.filters                             # VS 过滤器
│   └── *.user                                # 空用户工程设置
├── eimgconverter_cmd_typedef.h               # 10 个命令的唯一宏定义清单
├── eimgconverter_cmdInfo.cpp                 # ARG_INFO/CMD_INFO 元数据表
├── eimgconverter_cmdDef.cpp                  # 10 个命令实现壳（当前为空实现）
├── eimgconverter_dllMain.cpp                 # DllMain、LIB_INFO、GetNewInf、通知入口
├── eimgconverter_const.cpp                   # 常量表，当前数量为 0
├── eimgconverter_dtType.cpp                  # 自定义数据类型表，当前数量为 0
├── include_eimgconverter_header.h            # 公共头，聚合 elib 与命令声明
├── Source_eimgconverter.def                  # PE 导出定义，仅导出 GetNewInf
└── elib/
    ├── lib2.h                                # 易语言支持库 ABI、数据类型、命令/库结构
    ├── lang.h                                # GBK/English/BIG5/SJIS 语言版本宏
    ├── krnllib.h                             # 系统核心支持库常量与版本信息
    ├── mtypes.h                              # 跨编译环境基础类型兼容定义
    ├── fnshare.h / fnshare.cpp               # 系统通知、易语言内存、数组/文本辅助层
    ├── untshare.h                            # 通用窗口/组件辅助模板；本项目当前未被主源文件 include
    └── PublicIDEFunctions.h                  # IDE 功能号/参数结构；本项目当前未被主源文件 include
```

### 3.1 真实编译单元

动态库和 Win32 静态库工程都编译：

- `elib/fnshare.cpp`
- `eimgconverter_cmdDef.cpp`
- `eimgconverter_cmdInfo.cpp`
- `eimgconverter_const.cpp`
- `eimgconverter_dllMain.cpp`
- `eimgconverter_dtType.cpp`

头文件由工程项列出，包括 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`、`elib/fnshare.h`、`elib/untshare.h`、`elib/PublicIDEFunctions.h` 和项目公共头。

`eimgconverter_cmdDef.cpp`、`eimgconverter_cmdInfo.cpp`、`eimgconverter_const.cpp`、`eimgconverter_dllMain.cpp`、`eimgconverter_dtType.cpp` 均通过 `include_eimgconverter_header.h` 间接依赖 `lib2.h` 等 ABI 头；`eimgconverter_dllMain.cpp` 另直接 include `elib/fnshare.h`、`elib/lang.h`。

## 4. 核心模块与调用链

### 4.1 公共头与命名宏

`include_eimgconverter_header.h`：

- include `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`eimgconverter_cmd_typedef.h`。
- 在非静态库模式下声明全局常量、命令信息、命令函数、参数信息、数据类型信息数组。
- 用 `EIMGCONVERTER_DEF_CMD` 将同一命令清单展开成 10 个 `extern "C"` 命令函数声明。

`eimgconverter_cmd_typedef.h`：

- `EIMGCONVERTER_NAME` 将索引、英文名和 `__E_FNENAME` 拼接为 ABI 符号，例如 `eimgconverter_ConvertToJPG_0_eimgconverter`。
- `EIMGCONVERTER_DEF(_MAKE)` 是命令元数据的单一源，供声明、元数据、函数指针、静态命令名数组多次展开。
- 10 项索引连续为 `0..9`，命令英文名为 `ConvertToJPG`、`ConvertToBMP`、`ConvertToTIF`、`ConvertToPNG`、`ConvertToPPM`、`ConvertToPGM`、`ConvertToPBM`、`ConvertToPCX`、`ConvertToPIC`、`ConvertToSGI`。

### 4.2 命令元数据与参数布局

`eimgconverter_cmdInfo.cpp` 的 `g_argumentInfo_eimgconverter_global_var` 有 28 个参数描述项，按命令参数区间排列；`EIMGCONVERTER_DEF` 中的起始偏移和参数数量与其对应：

| 索引 | 易语言命令 | C++ 符号 | 参数区间/数量 | 参数与默认值 | 返回/平台 |
|---:|---|---|---|---|---|
| 0 | `转换到JPG` | `ConvertToJPG` | 0–5 / 6 | 源文件名、目标文件名、灰度 `假`、品质 `75`、优化编码 `真`、柔化 `0` | `SDT_INT`；Win32；JPEG |
| 1 | `转换到BMP` | `ConvertToBMP` | 6–7 / 2 | 源文件名、目标文件名 | `SDT_INT`；Win32；24 位 BMP |
| 2 | `转换到TIF` | `ConvertToTIF` | 8–10 / 3 | 源文件名、目标文件名、灰度 `假` | `SDT_INT`；Win32；TIFF |
| 3 | `转换到PNG` | `ConvertToPNG` | 11–13 / 3 | 源文件名、目标文件名、颜色位数 `24` | `SDT_INT`；Win32；24 位 PNG |
| 4 | `转换到PPM` | `ConvertToPPM` | 14–16 / 3 | 源文件名、目标文件名、二进制模式 `真` | `SDT_INT`；Win32；PPM |
| 5 | `转换到PGM` | `ConvertToPGM` | 17–19 / 3 | 源文件名、目标文件名、二进制模式 `真` | `SDT_INT`；Win32；PGM |
| 6 | `转换到PBM` | `ConvertToPBM` | 20–21 / 2 | 源文件名、目标文件名 | `SDT_INT`；Win32；文本 PBM |
| 7 | `转换到PCX` | `ConvertToPCX` | 22–23 / 2 | 源文件名、目标文件名 | `SDT_INT`；Win32；24 位 PCX |
| 8 | `转换到PIC` | `ConvertToPIC` | 24–25 / 2 | 源文件名、目标文件名 | `SDT_INT`；Win32；PICS（说明/命令名存在 PIC/PICS 不一致） |
| 9 | `转换到SGI` | `ConvertToSGI` | 26–27 / 2 | 源文件名、目标文件名 | `SDT_INT`；Win32；24 位 SGI |

所有命令的类别字段为 `0`，库类别字符串为 `0000图像转换`；用户难度为 `LVL_SIMPLE`；命令状态未设置隐藏/错误等标志。

### 4.3 命令实现现状

`eimgconverter_cmdDef.cpp` 的每个函数均遵循同一模板：

1. 从 `pArgInf` 按元数据顺序读取 `m_pText`、`m_bool` 或 `m_int`。
2. 存入 `arg1`…`arg6` 局部变量。
3. 函数体结束，没有其他调用。

源码中未出现 `pRetData` 写入、文件 API、图像 API、编码参数校验、错误码常量、异常处理或资源释放。因此当前源码的真实调用链在“参数解包”后终止；不能根据库说明推断实际转换行为。

### 4.4 库装载与系统通知

`eimgconverter_dllMain.cpp`：

- `DllMain` 对四类 Windows 生命周期事件均只做空处理并返回 `TRUE`。
- `g_LibInfo_eimgconverter_global_var`：
  - 格式号 `LIB_FORMAT_VER`；GUID `8FA3AA46276847db8F28E57E7FB97B7F`。
  - 版本 `2.0.4`。
  - 要求易语言系统 `3.0`、系统核心支持库 `3.0`。
  - 名称 `图像格式转换支持库`，语言 `__GBK_LANG_VER`。
  - OS 状态 `_LIB_OS(OS_ALL)`，即元数据声称 Windows/Linux/Unix 全部支持；但工程实际依赖 `windows.h`、Windows DLL/`.fne` 和 Win32 配置，存在“声明跨平台、工程实现 Windows 化”的明显矛盾。
  - 自定义数据类型数量 0、常量数量 0、依赖文件为 `NULL`。
  - 命令数量来自 `g_cmdInfo_eimgconverter_global_var_count`，命令函数表来自 `g_cmdInfo_eimgconverter_global_var_fun`。
- `GetNewInf` 是唯一 PE 导出，返回 `LIB_INFO*`。
- `eimgconverter_ProcessNotifyLib_eimgconverter` 是库通知回调，不通过 `.def` 直接导出，由 `LIB_INFO.m_pfnNotify` 提供。
- `NL_SYS_NOTIFY_FUNCTION` 转交 `elib/fnshare.cpp::ProcessNotifyLib`，保存系统回调；首次收到时通过 `NRS_GET_PRG_TYPE` 更新调试状态。
- `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 为静态编译兼容协议；前两个返回指针/字符串，第三个返回空依赖串 `"\0\0"`。
- 其他已列通知目前均为空处理；未知通知返回 `NR_ERR`。

## 5. API、ABI 与边界

### 5.1 外部入口

| 边界 | 入口/数据 | 证据 | 说明 |
|---|---|---|---|
| PE/DLL 装载 | `GetNewInf` | `Source_eimgconverter.def`；`eimgconverter_dllMain.cpp:90-92` | 固定返回 `LIB_INFO*` |
| 支持库信息 | `LIB_INFO g_LibInfo_eimgconverter_global_var` | `eimgconverter_dllMain.cpp:31-87` | 身份、版本、命令、通知、依赖元数据 |
| 命令调用 | `PFN_EXECUTE_CMD(PMDATA_INF, INT, PMDATA_INF)` | `elib/lib2.h`；`eimgconverter_dllMain.cpp:29` | 10 项函数指针与命令信息一一对应 |
| 命令 ABI 符号 | `eimgconverter_{EnglishName}_{index}_eimgconverter` | `eimgconverter_cmd_typedef.h` | 由宏生成，供 DLL/静态编译使用 |
| 系统通知 | `eimgconverter_ProcessNotifyLib_eimgconverter(INT,DWORD,DWORD)` | `eimgconverter_dllMain.cpp:5,101-180` | `LIB_INFO.m_pfnNotify` 指向该函数 |
| 静态编译协商 | `NL_GET_CMD_FUNC_NAMES` 等 | `eimgconverter_dllMain.cpp:102-124` | 返回函数名数组/通知函数名/依赖串 |

### 5.2 输入输出契约

- 输入：文件路径均为 `SDT_TEXT`，在命令实现中直接读取 `PMDATA_INF.m_pText`；没有源码级路径存在性、格式、权限、编码或安全校验。
- 选项：JPEG 品质/柔化、灰度、优化编码、位深、PPM/PGM 模式等仅在编辑元数据中声明；实现未消费这些值。
- 输出：每个命令元数据声明 `SDT_INT`，说明约定成功为 `1`，失败为 `0` 或若干负数错误码；但当前实现未写 `pRetData->m_int`，这个运行契约尚未真正实现。
- 错误码线索：说明中使用 `-1` 文件不存在、`-2` 资源不足、`-3` 格式不支持、`-4` 编码错误、`-6` 编码资源不足、`-7` 编码参数错误；源码没有对应常量或分支。
- 内存边界：`elib` 规定与易语言交互的内存应通过 `NRS_MALLOC/NRS_MFREE`；当前转换函数没有生成文本/字节集返回值，也没有做资源申请。

## 6. 依赖与工程构建边界

### 6.1 已确认依赖

- 编译器/工程：Visual Studio 2019/2022 可读的 `.sln/.vcxproj`，`VCProjectVersion=16.0`，`PlatformToolset=v141`。
- 目标平台：工程配置为 `Win32`/`x64`，Windows SDK `10.0.15063.0`。
- 系统头/API：`elib/lib2.h` include `windows.h`、`stdio.h`、`math.h`；`elib/mtypes.h` 是部分 Windows 基础类型兼容定义，但当前 `lib2.h` 直接依赖 Windows 头。
- C/C++ 运行库：动态库 Win32 Debug/Release 使用 `/MTd`/`/MT` 对应的 `MultiThreadedDebug`/`MultiThreaded`；静态库 Win32 同样使用静态 CRT；x64 工程未显式列出同等 RuntimeLibrary 条目。
- 易语言 ABI：仓库内 vendored `elib` 头文件与 `fnshare.cpp`，不需要仓库外的易语言源码才能完成接口编译（但真实宿主运行需要易语言运行时/IDE）。

### 6.2 未发现的依赖

肉眼检查项目源文件、工程 XML、`.def` 和 include 图，未发现：

- JPEG/PNG/TIFF/PCX/PCD/BMP 等图像编解码库源码或头文件；
- `AdditionalDependencies` 中的图像库、静态库或 DLL；
- OpenCV、GDI+、WIC、libjpeg、libpng、libtiff、FreeImage 等实现引用；
- 依赖包管理文件、安装脚本、运行时配置、测试项目或样例图像；
- `m_szDependFiles` 外部支持文件清单（源码固定为 `NULL`）。

因此“图像转换”实现依赖在当前仓库中没有落点，属于首轮建档必须保留的缺口，而不是已确认的隐藏第三方依赖。

### 6.3 两种产物

- `eimgconverter.vcxproj`：`DynamicLibrary`，Win32 目标扩展 `.fne`，通过 `Source_eimgconverter.def` 导出 `GetNewInf`。
- `eimgconverter_static/eimgconverter_static.vcxproj`：`StaticLibrary`，与主工程共享同一批源文件，通过 `__E_STATIC_LIB` 走静态编译分支；不使用 `.def`。
- `eimgconverter.sln` 同时包含动态库和静态库项目，解决方案配置包含 `Debug/Release` 与 `x86/x64` 映射。

### 6.4 工程配置风险

从 XML 逐项读取后确认：

1. 动态库 Win32 Debug/Release 明确设置 `__E_FNENAME=eimgconverter`；静态库 Win32 Debug/Release 明确设置 `__E_STATIC_LIB;__E_FNENAME=eimgconverter`。
2. 动态库 Debug/Release x64 的 `PreprocessorDefinitions` 没有 `__E_FNENAME=eimgconverter`。
3. 静态库 Debug/Release x64 的 `PreprocessorDefinitions` 也没有 `__E_STATIC_LIB` 和 `__E_FNENAME=eimgconverter`。
4. `elib/lib2.h` 明确要求 include 前定义 `__E_FNENAME`，否则触发 `#error`。因此 x64 配置至少存在宏定义不完整风险，不能在未实测构建前声称 x64 可编译。
5. `eimgconverter_cmd_typedef.h` 文件为 GB18030/GBK 文本，而若编译器未按项目实际编码处理中文字符串，命令显示文本可能出现编码问题；工程未设置源码编码选项。
6. `LIB_INFO.m_dwState` 使用 `OS_ALL`，但命令元数据 `_CMD_OS(__OS_WIN)`、工程/头文件均是 Windows 体系；跨平台声明与可编译/可运行证据不一致。

## 7. 静态库与 64 位 ABI 风险

静态模式由 `__E_STATIC_LIB` 控制：

- `include_eimgconverter_header.h` 不声明 DLL 全局元数据数组；
- `eimgconverter_dllMain.cpp` 不编译 `DllMain`、命令函数指针数组、`LIB_INFO` 和静态命令名数组之外的 DLL 专用部分；
- `eimgconverter_ProcessNotifyLib_eimgconverter` 仍保留，用于静态编译器协商命令函数名、通知函数名和依赖项；
- `eimgconverter_cmdDef.cpp` 的命令函数本体仍被编译。

源码存在未确认但高优先级的 64 位 ABI 风险：

- `eimgconverter_ProcessNotifyLib_eimgconverter` 将 `g_cmdNameseimgconverter` 数组指针强制转换为 `INT` 返回；将字符串指针强制转换为 `INT` 返回。
- `elib/fnshare.cpp`/`fnshare.h` 的通知协议使用 `DWORD` 承载参数，并将 `dwParam1` 转换为函数指针。
- 在 x64 下指针宽度通常大于 `INT`/`DWORD`，上述转换可能截断地址。仓库没有 x64 运行时验证或兼容适配。

这不是当前核对修改项；后续若维护工程，应先以宿主 ABI 文档和真实 x64 编译/装载验证为准，不能仅凭 Win32 逻辑推断安全。

## 8. 状态、资源、并发与持久化

- 持久化：无数据库、配置文件、缓存、索引、模型或磁盘状态管理。
- 并发：命令实现没有线程、锁、队列、异步任务或并发控制；`DllMain` 也没有初始化全局资源。
- 资源生命周期：当前命令没有打开文件、分配图像对象、创建临时文件或返回易语言托管数据，因此没有实现层释放路径可审计。
- 系统回调状态：`fnshare.cpp` 使用静态 `s_pfnNotifySys`、`s_pfnuserNotifySys` 和 `s_isDebug`；`NL_SYS_NOTIFY_FUNCTION` 会更新系统通知函数并可能查询程序类型。该状态是进程内全局状态，不持久化。
- 失败恢复：不存在转换失败重试、事务回滚、部分输出清理或崩溃恢复实现；这些只能作为后续实现要求，不能写成当前能力。

## 9. 测试、验证与当前核对执行边界

### 9.1 仓库内测试现状

未发现测试目录、测试源文件、测试工程、样例图像、CI 配置或验收脚本。Git 初始提交也只包含工程/源文件和 `elib` 头文件。

### 9.2 当前核对已执行的只读检查

- 读取项目根文件树、全部项目源文件/头文件/工程 XML/`.def`。
- 读取 Git 分支、远程 URL、本地 `HEAD`、远程 `HEAD`、提交时间和工作树状态。
- 对源码 include、函数定义、工程编译单元、配置宏、目标类型和外部库链接字段做静态盘点。
- 检查项目及同级仓库范围内的 `细探-*.md`，结果为无。
- 尝试使用 codegraph：目标目录没有 `.codegraph/` 索引，因此 codegraph 明确返回不可查询；当前核对改用现场源码逐文件读取，未将其他项目代码地图当作本项目证据。

### 9.3 未执行事项

按任务边界未执行：

- 未安装 Visual Studio、Windows SDK、易语言或任何依赖；
- 未在 macOS 上构建 Windows 工程；
- 未启动 DLL、加载支持库或调用易语言宿主；
- 未运行图像转换命令；
- 未做真实输入/输出、错误码、资源释放、x64 ABI 或跨平台验证；
- 未 fetch、pull、rebase、提交或修改远程/本地 Git 历史。

因此本文的“已确认”全部来自源码/工程/版本元数据静态证据，“可运行性”和“实际格式支持”均保留为未验证或缺实现状态。

## 10. 风险与后续复核清单

| 优先级 | 事项 | 当前证据/影响 | 后续复核方向 |
|---|---|---|---|
| P0 | 10 个命令没有转换实现 | `eimgconverter_cmdDef.cpp` 每个函数只解包参数 | 找回完整上游实现或确认该仓库是否仅为接口模板；补齐解码、编码、文件输出和 `pRetData` |
| P0 | x64 工程宏不完整 | x64 配置缺 `__E_FNENAME`，静态 x64 还缺 `__E_STATIC_LIB` | 在隔离 Windows 工具链中核对预处理结果并修复工程配置（需另行授权） |
| P0 | x64 指针转 `INT/DWORD` | 通知协商路径存在显式窄化转换 | 对照易语言 x64 支持库 ABI，改用宿主规定的宽指针传输方式并做宿主验证 |
| P1 | OS 元数据与实现不一致 | `OS_ALL` 与 Windows 头/`.fne`/Win32 命令状态矛盾 | 确认是否应只声明 Windows，或补齐真正跨平台实现 |
| P1 | 依赖缺口 | 没有任何图像编解码实现/依赖声明 | 通过上游历史、发布包或同组织仓库追溯实际 codec 来源；不要凭命令说明猜依赖 |
| P1 | 输出契约未落地 | 说明约定 `1/0/负数`，但函数不写 `pRetData` | 按 `elib/lib2.h` 的 `MDATA_INF` 规则补返回值和错误路径，并建立输入输出夹具 |
| P2 | 编码与命令名不一致 | `PIC` 命令说明写 `PICS`；源码为 GBK/GB18030 | 确认易语言支持库文本编码和历史兼容要求，固定显示名/目标扩展名契约 |
| P2 | 无测试与 CI | 只能静态审计，无法证明宿主装载/转换结果 | 首先建立 Windows 宿主装载冒烟，再覆盖各格式、错误码、默认参数和资源清理 |
| P2 | `NL_*` 生命周期多为空 | 卸载/释放/IDE 通知无资源清理 | 在真实宿主事件序列中确认是否需要实现，避免空处理造成资源泄漏 |

## 11. 证据路径索引

- 库公共 ABI：`elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`
- 项目公共头：`include_eimgconverter_header.h`
- 命令单一清单：`eimgconverter_cmd_typedef.h:12-22`
- 命令元数据和参数表：`eimgconverter_cmdInfo.cpp:1-76`
- 命令实现壳：`eimgconverter_cmdDef.cpp:1-118`
- 库元数据、导出入口、通知分发：`eimgconverter_dllMain.cpp:1-180`
- 常量表：`eimgconverter_const.cpp:1-18`
- 自定义数据类型表：`eimgconverter_dtType.cpp:1-13`
- 系统通知/内存辅助：`elib/fnshare.cpp`、`elib/fnshare.h`
- DLL 导出：`Source_eimgconverter.def:1-4`
- 动态库构建配置：`eimgconverter.vcxproj`
- 静态库构建配置：`eimgconverter_static/eimgconverter_static.vcxproj`
- 解决方案映射：`eimgconverter.sln`
- 版本基线：Git `1b558a7644764cc79d2a839a4f40ba4592311083`，远程 `origin/master` 同指该提交。

## 12. 首轮裁决

```text
吸收：支持库 ABI 外壳、LIB_INFO 装载模型、EIMGCONVERTER_DEF 单一命令清单、参数元数据布局、系统通知转发结构、动态/静态双工程组织。
废弃：把 LIB_INFO 中的“支持格式说明”直接当作当前已实现能力；把 OS_ALL 当作已验证的跨平台事实；把空命令函数当作可执行转换器。
待核：实际图像 codec 来源、上游完整实现是否存在、PIC/PICS 历史命名、易语言 x64 静态编译约定、空生命周期通知是否足够。
```
