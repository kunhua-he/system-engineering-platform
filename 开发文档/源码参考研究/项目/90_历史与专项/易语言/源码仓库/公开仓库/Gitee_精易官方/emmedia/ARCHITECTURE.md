# emmedia 架构档案

> 首轮全量架构建档。本文是本项目根目录唯一的架构事实文档；后续细探、补充和复核只更新本文件。
>
> 研究边界：本轮仅读取源码、工程文件、协议头、Git 元数据和同级旧细探索引；未修改源码，未安装依赖，未启动服务，未执行构建，未提交 Git。

## 1. 项目定位

`emmedia` 是面向易语言 Windows 运行环境的“多媒体支持库”源码骨架，采用易语言支持库 ABI：动态库通过固定导出 `GetNewInf` 返回 `LIB_INFO`，由 `LIB_INFO` 提供命令元数据、命令函数指针表、自定义数据类型、常量表和系统通知回调；静态库则通过 `__E_STATIC_LIB` 分支保留静态编译所需的命令函数名和通知协议。

源码声明了 81 个易语言命令，覆盖 7 个功能提供对象，以及 1 个枚举数据类型：

- `系统音量 / SysVolume`：系统音量、静音、左右声道；
- `录音 / WaveRecord`：Wave 录音控制；
- `MIDI演奏 / MIDIPlay`：MIDI 设备、乐器和音符；
- `录音音波 / WaveInForm`：录音输入波形读取；
- `CD播放 / CDPlay`：光驱、曲目、MCI CD 播放；
- `媒体播放 / MediaPlay`：MCI 媒体文件播放、窗口句柄和音量；
- `音频转换 / AudioConvert`：编码器查询、音频格式转换；
- `音量类型 / VolumeType`：系统音量源枚举，包含 7 个枚举成员。

**重要实现结论**：当前提交中的命令函数和可视化组件回调主要是生成器模板/占位实现，而不是可运行的多媒体后端。`emmedia_cmdDef.cpp` 的 81 个命令函数只读取部分入参，没有向 `pRetData` 写返回值，也没有发现 `mciSendString`、`waveOut*`、`waveIn*`、`midi*` 等实际设备调用；`emmedia_dtType.cpp` 的组件创建函数返回 0，属性和通知回调使用模板默认返回值。元数据完整度高于行为实现完整度。

## 2. 真实调用与装载流程

```text
易语言编译器/运行时或 IDE
        |
        | 动态装载 emmedia.fne / 通过静态库整合
        v
GetNewInf()  [Source_emmedia.def -> emmedia_dllMain.cpp]
        |
        v
LIB_INFO g_LibInfo_emmedia_global_var
        |
        +--> g_cmdInfo_emmedia_global_var[]       命令展示/参数/返回类型
        +--> g_cmdInfo_emmedia_global_var_fun[]   81 个 PFN_EXECUTE_CMD 函数指针
        +--> g_DataType_emmedia_global_var[]      7 个对象 + 1 个枚举
        +--> g_ConstInfo_emmedia_global_var[]     当前为空，数量 0
        +--> emmedia_ProcessNotifyLib_emmedia()   系统通知入口

命令调用
   |
   v
命令索引 -> g_cmdInfo..._fun[index]
   |
   v
emmedia_<EnglishName>_<index>_emmedia()
   |
   +--> 从 PMDATA_INF pArgInf[1..n] 取 m_int/m_bool/m_pText/引用指针
   +--> 当前源码没有实际设备/文件/播放调用
   +--> 当前源码没有写入 PMDATA_INF pRetData

对象/组件交互
   |
   v
LIB_DATA_TYPE_INFO -> emmedia_GetInterface_<Object>(nInterfaceNO)
   |
   +--> ITF_CREATE_UNIT -> emmedia_ControlCreate_<Object>() -> 当前返回 0
   +--> ITF_PROPERTY_UPDATE_UI -> 默认 TRUE
   +--> ITF_DLG_INIT_CUSTOMIZE_DATA -> 默认 FALSE
   +--> ITF_NOTIFY_PROPERTY_CHANGED -> 模板校验后默认 FALSE
   +--> ITF_GET_ALL_PROPERTY_DATA -> 当前返回 0
   +--> ITF_GET_PROPERTY_DATA -> 模板默认值/占位逻辑
   +--> ITF_IS_NEED_THIS_KEY -> 默认 FALSE
   +--> ITF_GET_NOTIFY_RECEIVER -> 默认不处理/返回 0

系统通知
   |
   v
emmedia_ProcessNotifyLib_emmedia()
   |
   +--> NL_SYS_NOTIFY_FUNCTION -> ProcessNotifyLib()
   |       -> 保存易语言运行时 PFN_NOTIFY_SYS
   |       -> 首次通过 NRS_GET_PRG_TYPE 获取调试/运行类型
   +--> 其他通知 -> 当前大多空处理或返回默认状态
   |
   v
elib/fnshare.cpp 的 NotifySys()/ealloc()/efree()
```

## 3. 目录与文件地图

仓库当前 Git 树共 23 个受版本控制文件；没有 README、测试目录、脚本目录、CI 配置或细探文档。

### 3.1 根目录入口与元数据

| 路径 | 作用 | 关键事实 |
|---|---|---|
| `emmedia.sln` | Visual Studio 解决方案 | 包含动态库工程 `emmedia.vcxproj` 和静态库工程 `emmedia_static/emmedia_static.vcxproj`；Debug/Release × Win32/x64 |
| `emmedia.vcxproj` | 动态库工程 | `ConfigurationType=DynamicLibrary`；Win32 目标扩展 `.fne`；`PlatformToolset=v141`；Windows SDK `10.0.15063.0`；Win32 使用 `Source_emmedia.def` |
| `emmedia_static/emmedia_static.vcxproj` | 静态库工程 | `ConfigurationType=StaticLibrary`；复用根目录全部实现源码；Win32 Debug/Release 定义 `__E_STATIC_LIB` |
| `Source_emmedia.def` | DLL 导出定义 | 仅导出 `GetNewInf`，命令函数通过 `LIB_INFO.m_pCmdsFunc` 间接提供，不是 DLL 公共导出 |
| `include_emmedia_header.h` | 项目总头文件 | 引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和命令宏；为 `EMMEDIA_DEF` 展开生成全部命令声明 |
| `emmedia_cmd_typedef.h` | 命令单一清单 | `EMMEDIA_DEF(_MAKE)` 为 81 条命令提供索引、中文名、英文名、说明、平台、返回类型、参数数量和参数表起点 |
| `emmedia_cmdInfo.cpp` | 命令元数据 | 51 个 `ARG_INFO` 参数条目；由 `EMMEDIA_DEF_CMDINFO` 展开 `CMD_INFO` 数组 |
| `emmedia_const.cpp` | 常量元数据 | 动态库分支创建常量表，但 `g_ConstInfo_emmedia_global_var_count = 0`，当前没有公开常量 |
| `emmedia_dllMain.cpp` | DLL/静态库装载入口 | 定义 `DllMain`、命令函数指针表、`LIB_INFO`、`GetNewInf`、静态编译命令名数组和系统通知分发 |

### 3.2 命令与数据类型实现

| 路径 | 作用 | 关键事实 |
|---|---|---|
| `emmedia_cmdDef.cpp` | 81 个命令函数定义 | 函数签名统一为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`；当前只做入参局部变量提取或空函数体 |
| `emmedia_dtType.cpp` | 组件/自定义类型和 IDE 接口 | 定义 7 组 `GetInterface`、7 组组件回调、7 个对象命令索引表、`VolumeType` 枚举和 `LIB_DATA_TYPE_INFO` |

### 3.3 `elib/` 运行时适配层

| 路径 | 作用 |
|---|---|
| `elib/lib2.h` | 易语言支持库核心 ABI 类型、`CMD_INFO`、`LIB_INFO`、`LIB_DATA_TYPE_INFO`、`PFN_INTERFACE`、`PFN_EXECUTE_CMD`、`ITF_*`、`NRS_*`、`NL_*` 与平台宏 |
| `elib/fnshare.h` | 共享函数声明和内联工具；封装 `NotifySys`、`ealloc`、`efree`、数组/文本/字节集数据访问 |
| `elib/fnshare.cpp` | 共享通知状态；保存运行时 `PFN_NOTIFY_SYS`、调试类型和用户通知回调，负责 `ProcessNotifyLib` 转发 |
| `elib/lang.h` | 语言版本常量；当前编译语言为 `__GBK_LANG_VER` |
| `elib/krnllib.h` | 系统核心支持库 GUID、文件名、版本等兼容常量；当前固定引用核心库版本宏 4.5 信息 |
| `elib/mtypes.h` | Windows/易语言风格基础类型别名，如 `INT`、`BOOL`、`HWND`、`HUNIT` 相关基础句柄类型 |
| `elib/untshare.h` | 可视化组件共享辅助类和窗口样式/属性工具；本项目组件模板当前未真正使用其大部分能力 |
| `elib/PublicIDEFunctions.h` | IDE 通知功能编号、程序文本/工程编辑相关协议结构；属于通用 SDK 头文件，本项目未观察到实际 IDE 功能实现 |

## 4. 命令模型与对象分层

### 4.1 命令清单的单一来源

`emmedia_cmd_typedef.h` 以 X-Macro 风格定义 `EMMEDIA_DEF(_MAKE)`。同一清单被不同宏重复展开：

1. `include_emmedia_header.h`：展开为 81 个函数声明；
2. `emmedia_cmdInfo.cpp`：展开为 `CMD_INFO` 描述数组；
3. `emmedia_dllMain.cpp`：展开为函数指针数组 `g_cmdInfo_emmedia_global_var_fun`；
4. `emmedia_dllMain.cpp`：在静态编译分支展开为命令函数名数组；
5. `emmedia_dtType.cpp`：用命令索引数组把命令归属到对象。

因此，命令索引是 ABI 级稳定字段。任何调整命令顺序、删除命令或改变参数起始索引，都会同时影响易语言命令调用、元数据展示和对象方法归属。

### 4.2 81 个命令的对象归属

| 对象 | 命令索引 | 数量 | 备注 |
|---|---:|---:|---|
| `系统音量` | 0–10 | 11 | 系统音量/静音和设备信息 |
| `录音` | 11–19 | 9 | Wave 录音生命周期、格式、保存 |
| `MIDI演奏` | 20–30 | 11 | MIDI 设备、乐器、音符 |
| `录音音波` | 31–37 | 7 | 波形输入和波段值；34、35 为隐藏命令 |
| `CD播放` | 38–55、70 | 19 | MCI 光驱播放，索引 70 的 `取起始时间` 插入对象方法表 |
| `媒体播放` | 56–69、79–80 | 16 | MCI 媒体播放和独立于系统的播放音量 |
| `音频转换` | 71–78 | 8 | 编码器与格式转换 |
| **合计** | — | **81** | 与 `EMMEDIA_DEF` 条目数一致 |

### 4.3 自定义数据类型

`g_DataType_emmedia_global_var` 共 8 项：

- 7 个 `_DT_OS(__OS_WIN) | LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER` 对象：`SysVolume`、`WaveRecord`、`MIDIPlay`、`WaveInForm`、`CDPlay`、`MediaPlay`、`AudioConvert`；
- 1 个 `_DT_OS(__OS_WIN) | LDT_ENUM` 枚举：`VolumeType`。

`VolumeType` 的 7 个中文成员是 `主音量`、`波形`、`麦克`、`CD`、`电话线`、`线路输入`、`软件合成器`，英文标识依次为 `Master`、`WaveOut`、`Microphone`、`CD`、`TelphoneLine`、`LineIn`、`MIDI`。

`系统音量`声明 2 个事件：`音量改变`、`静音改变`；其他对象没有事件数组。对象元数据的组件资源、属性数组和自定义属性均为空或 `NULL`。

## 5. ABI、边界和协议

### 5.1 动态库 ABI

- DLL 入口：`Source_emmedia.def` 导出 `GetNewInf`；
- `GetNewInf()` 返回 `PLIB_INFO`，实际对象为 `g_LibInfo_emmedia_global_var`；
- 库 GUID：`824F144B108A4bcbB966F45670D42A00`；
- 库版本：主版本 `3`、次版本 `0`、构建号 `0`；
- 所需易语言系统版本：主 `3`、次 `7`；所需系统核心支持库版本：主 `3`、次 `7`；
- 库名：`多媒体支持库`；语言：`__GBK_LANG_VER`；平台：`_LIB_OS(__OS_WIN)`；
- `m_nCmdCount` 来自 `g_cmdInfo_emmedia_global_var_count`；`m_pCmdsFunc` 指向 81 项命令函数指针；
- `m_pfnNotify` 为 `emmedia_ProcessNotifyLib_emmedia`；
- 常量表数量为 0；依赖文件列表为 `NULL`；IDE AddIn 和 SuperTemplate 均为 `NULL`。

### 5.2 命令调用协议

`PFN_EXECUTE_CMD` 定义为：

```text
void (*)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

命令参数从 `pArgInf[1]` 开始，按 `CMD_INFO.m_nArgCount` 和 `ARG_INFO` 的类型/标志解释。当前源码展示了以下参数边界：

- 基础值：`m_int`、`m_bool`、`m_byte`；
- 文本：`m_pText`；
- 引用输出：`m_pInt`、`m_pShort`、`m_pBool`；
- 默认参数：`AS_HAS_DEFAULT_VALUE`、`AS_DEFAULT_VALUE_IS_EMPTY`；
- 只传变量：`AS_RECEIVE_VAR`。

`emmedia_cmdInfo.cpp` 的参数表中包含默认值和引用标志，但命令函数当前没有完成参数校验、设备操作、返回值填充或错误处理。

### 5.3 组件/IDE 接口协议

每个对象的 `emmedia_GetInterface_<Object>(INT nInterfaceNO)` 通过 `ITF_*` 编号返回回调函数指针，覆盖组件创建、属性更新、定制属性对话框、属性变更、属性读取、按键拦截和通知接收者。未知接口返回 `NULL`。

当前组件回调的真实语义是模板默认行为：

- 创建返回空 `HUNIT`（0）；
- 设计时默认尺寸通知返回 0；
- 全部属性数据读取返回 0；
- 属性变更回调默认拒绝/不重建；
- 属性 UI 更新返回 `TRUE`；
- 定制属性对话框返回 `FALSE`；
- 按键查询返回 `FALSE`；
- 未实现的语言转换、消息过滤、图标属性等接口返回 `NULL`。

### 5.4 系统通知协议

`emmedia_ProcessNotifyLib_emmedia` 接收 `NL_*` 通知：

- `NL_SYS_NOTIFY_FUNCTION`：把 `dwParam1` 解释为 `PFN_NOTIFY_SYS`，交给 `ProcessNotifyLib` 保存；
- `NL_GET_CMD_FUNC_NAMES`：返回静态编译需要的命令名字数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `emmedia_ProcessNotifyLib_emmedia` 的字符串名；
- `NL_GET_DEPENDENT_LIBS`：返回空的双 NUL 字符串；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 默认分支返回 `NR_ERR`。

`elib/fnshare.cpp` 在收到 `NL_SYS_NOTIFY_FUNCTION` 后还会通过 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 获取运行类型，并把通知继续传给可选的用户回调 `s_pfnuserNotifySys`。

## 6. 技术栈与依赖边界

### 6.1 工具链

- C++/Win32 Visual Studio 工程；
- `PlatformToolset=v141`；
- Windows SDK `10.0.15063.0`；
- Unicode 字符集；
- Debug 使用静态运行库（`MultiThreadedDebug`），Release 使用静态运行库（`MultiThreaded`）；
- 动态工程 Win32 输出扩展 `.fne`；
- 静态工程输出类型为 `StaticLibrary`。

### 6.2 代码依赖

- 项目内 ABI/SDK：`elib/lib2.h`、`elib/fnshare.h/.cpp`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`、`elib/untshare.h`、`elib/PublicIDEFunctions.h`；
- Windows 系统头由 `elib/lib2.h` 引入 `windows.h`；
- 多媒体后端意图在元数据说明中指向 Windows MCI、Wave、MIDI 和音频编码器/解码器；
- `CD播放` 与 `媒体播放` 的说明明确写出 Windows MCI，并允许调用方使用 `mciSendString` 等 API 通过 MCI 别名协同控制；
- `音频转换` 说明指出部分能力依赖 DirectX，并依赖系统中安装的编码器/解码器；
- 当前 `.vcxproj` 没有声明第三方库、`AdditionalDependencies` 或额外库目录；源码也没有观察到实际多媒体 API 调用或链接指令。因此上述 MCI/DirectX/编码器是设计目标/说明边界，不是本提交已落地的实现依赖。

### 6.3 工程配置风险

- 动态工程 Win32 配置显式定义 `__E_FNENAME=emmedia`，但 x64 配置的 `PreprocessorDefinitions` 未显式定义该宏；
- 静态工程 Win32 配置显式定义 `__E_STATIC_LIB;__E_FNENAME=emmedia`，但 x64 配置未显式定义这两个宏；
- 动态工程 x64 配置未配置 `ModuleDefinitionFile` 和 `TargetExt=.fne`，与 Win32 DLL 配置不对称；
- 静态工程 x64 配置使用 `PrecompiledHeader=Use`，而工程文件中没有对应的 `pch.h` 条目；
- 上述配置只作为静态检查发现记录，本轮没有在 Windows/Visual Studio 上构建验证，不应推断为已复现的构建失败。

## 7. 状态、资源和错误语义

当前仓库没有持久化数据模型、配置文件、线程池、队列、缓存、数据库或文件格式实现。能确认的状态只有：

- `elib/fnshare.cpp` 中的进程级静态通知函数指针 `s_pfnNotifySys`；
- 可选用户通知函数指针 `s_pfnuserNotifySys`；
- 运行/调试类型 `s_isDebug`；
- `LIB_INFO` 中的静态元数据表及命令函数指针表。

命令约定普遍使用 `SDT_BOOL`/`SDT_INT`/`SDT_TEXT` 表达成功、状态或查询结果，但实现函数没有填充 `pRetData`，因此当前不能把命令说明中的返回值描述视为实际运行契约。当前未发现统一错误码、异常转换、日志、资源释放、设备句柄管理或文件覆盖策略的实现。

## 8. 测试、验证与构建现状

### 已存在

- Visual Studio 解决方案和两个工程配置；
- Debug/Release、Win32/x64 配置声明；
- 动态库导出定义；
- 命令元数据、参数元数据、对象/枚举元数据；
- Git 工作树和远程版本基线可读取。

### 未存在

- 没有 `README`；
- 没有单元测试、集成测试、示例程序或验收脚本；
- 没有 CI/CD、构建流水线或发布脚本；
- 没有真实设备模拟器或 MCI/Wave/MIDI 测试夹具；
- 没有实现完成度检查、返回值检查或 ABI 自动校验。

### 本轮实际执行

本轮执行了只读盘点：Git 文件树、Git 分支/提交/远程、`git ls-remote origin`、工程 XML 静态解析、源码文本解码与符号/命令/元数据统计。没有执行 `msbuild`、Visual Studio 构建、运行 DLL、运行易语言宿主或任何设备操作。

## 9. 主要风险与后续复核点

1. **行为实现缺失**：81 个命令函数没有真实业务调用，也没有返回值写入；若以“支持库可用”为目标，必须逐对象补齐 Windows API/MCI/编码器调用和 `MDATA` 返回封装。
2. **组件骨架未落地**：7 组 `ControlCreate` 返回 0，属性/通知回调大多是模板默认值；易语言 IDE 中的可视化组件生命周期尚未形成闭环。
3. **命令元数据与实现可能漂移**：命令清单通过宏共享，但 `ARG_INFO` 使用手工偏移；应建立命令索引、参数数量、参数起始位置和函数指针数量的自动校验。
4. **静态/动态 ABI 分支需复核**：`__E_STATIC_LIB` 影响元数据与 `DllMain`；静态库和 DLL 共用同一源码，但 x64 预处理宏不完整，需在 Windows 工具链上逐配置验证。
5. **输出类型/编码风险**：项目要求 GBK 语言版本，源码同时包含中文、Windows `TCHAR`/文本指针和 ANSI 风格 `LPSTR` 参数；需复核 Unicode 工程配置与易语言 GBK ABI 的实际编码转换。
6. **外部依赖未声明**：设计说明提到 MCI、DirectX、系统编码器/解码器，但工程没有显式库依赖；真实实现落地前需要明确 Windows SDK 库、系统版本、编码器发现与缺失错误语义。
7. **资源生命周期未实现**：录音、MIDI、波形输入、CD/媒体播放和音频转换均应有打开/初始化、使用、暂停/恢复、停止、关闭、析构和异常路径；当前没有句柄或上下文状态。
8. **协议返回值未验证**：命令实现应验证 `pRetData`、`nArgCount`、引用参数有效性、默认参数和文本生命周期；当前源码没有这些边界检查。
9. **没有运行证据**：当前所有“支持”结论都来自元数据/注释/模板，不代表在实际 Windows 设备和易语言宿主中可运行。
10. **远程版本刷新策略**：本轮本地提交与远程 `origin/master` 相同；如后续发现本地未跟踪 `ARCHITECTURE.md`，更新源码前须避免直接覆盖该文档。

## 10. 版本基线与证据路径

- 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/emmedia`
- Git 分支：`master`，跟踪 `origin/master`；工作树在建档前为干净状态；
- HEAD：`3b2932b552a2e6803acdf1c3b2202ef722374aa9`；
- HEAD 时间：`2022-12-19T16:06:22+08:00`；提交信息：`初始化仓库`；
- 远程：`https://gitee.com/JYtechnology/emmedia.git`；
- `git ls-remote origin HEAD refs/heads/master` 返回同一提交 `3b2932b552a2e6803acdf1c3b2202ef722374aa9`；
- 关键证据：
  - `emmedia_dllMain.cpp:31-92`：`LIB_INFO`、版本、GUID、函数表、`GetNewInf`；
  - `emmedia_dllMain.cpp:101-178`：系统通知分发；
  - `emmedia_cmd_typedef.h:12-94`：81 条命令宏清单；
  - `emmedia_cmdInfo.cpp:18-100`：51 个参数元数据；
  - `emmedia_cmdDef.cpp:1-648`：81 个命令函数骨架；
  - `emmedia_dtType.cpp:283-432`：对象命令索引、枚举和数据类型元数据；
  - `emmedia_dtType.cpp:437-1700`：7 组组件接口及模板回调；
  - `elib/fnshare.cpp:7-71`：通知函数指针、内存通知和用户回调转发；
  - `emmedia.vcxproj`、`emmedia_static/emmedia_static.vcxproj`：工程配置与源码清单；
  - `Source_emmedia.def:1-4`：DLL 导出边界。

## 11. 旧细探收口声明

本轮在目标项目根、其上级 `公开仓库/Gitee_精易官方`、源码仓库和历史专项范围内检索 `细探-*.md`、`*细探*` 与项目名相关文件，没有发现属于 `emmedia` 的旧细探文档；目标根此前也没有 `ARCHITECTURE.md`。因此本文件为首次建档，不存在可删除的旧细探；后续只维护本文件，禁止重新建立平行架构报告。
