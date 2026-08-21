# phonecortrol 架构建档

> 本文是对本仓库当前源码与 Visual Studio 工程的首轮全量静态建档。
> 结论严格区分：**已实现**（源码存在可执行的装载/元数据/转发逻辑）、**仅声明**（接口或编辑器元数据已声明，但业务行为为空）、**未验证**（当前环境无法证明构建或运行）。
> 研究范围只涉及本仓库及其随附 `elib/` 支持库头文件；不引用无关仓库或 MCP 结果作为事实。

## 1. 项目定位

`phonecortrol` 是一个面向易语言的 Windows 电话语音支持库工程模板/骨架，目标是把电话呼叫、接听、播放/录音、按键、保持/转接、传真、调制解调器文件传输等能力注册为易语言命令、组件属性、组件事件和枚举数据类型。

从当前源码看，它已经具备“易语言支持库 ABI 适配层”的完整外壳：DLL 导出入口、`LIB_INFO` 库描述、22 个命令的名称/参数元数据、6 个自定义数据类型、组件接口分发和系统通知转发。但电话设备调用、资源生命周期、属性持久化、事件触发和命令返回值均未写入实际逻辑，因此不能据此认定为可用的电话控制实现。

### 1.1 现状结论

| 层次 | 状态 | 证据与判断 |
|---|---|---|
| 易语言支持库 ABI 外壳 | **已实现** | `GetNewInf()` 返回静态 `LIB_INFO`；DLL 导出由 `Source_phonecortrol.def` 声明。`phonecortrol_dllMain.cpp:31-92` |
| 命令登记与函数名生成 | **已实现（登记层）** | `PHONECORTROL_DEF` 统一生成 22 条命令的声明、元数据、函数指针和静态编译名称。`phonecortrol_cmd_typedef.h:11-34` |
| 命令参数编辑信息 | **已实现（描述层）** | 30 个 `ARG_INFO` 条目和 22 个 `CMD_INFO` 条目已定义。`phonecortrol_cmdInfo.cpp:5-79` |
| 电话/传真/调制解调器业务 | **仅声明** | 22 个命令函数只有参数读取或空函数体，没有设备 API、状态变更、返回值填充或错误处理。`phonecortrol_cmdDef.cpp:3-203` |
| 组件类型/枚举/属性/事件元数据 | **已实现（描述层）** | `PhoneControl`、4 个枚举和隐藏的 `ModemFile` 已注册；属性与事件表存在。`phonecortrol_dtType.cpp:43-238` |
| 组件创建、属性存取和运行时事件 | **仅声明** | 创建直接返回 0；属性数据获取返回 0/空值；按键需求固定返回 `FALSE`；未见事件通知调用。`phonecortrol_dtType.cpp:240-418` |
| 预定义常量表 | **已实现为空表** | `g_ConstInfo...` 数组存在，但数量明确为 0。`phonecortrol_const.cpp:12-18` |
| Win32 Debug/Release 工程配置 | **已声明，未验证构建** | 工程配置目标为 Win32/x64 的 DLL 与静态库，但本环境为 macOS，未执行 MSBuild/Visual Studio。`phonecortrol.sln:1-40`、`phonecortrol.vcxproj:3-202` |
| 测试 | **未见/未验证** | Git 跟踪文件中没有测试文件；没有运行时电话设备或易语言宿主验收证据。 |

## 2. 文本架构流程图

```text
易语言 IDE / 易语言运行环境
          │
          │ 载入支持库：固定导出 GetNewInf
          ▼
Source_phonecortrol.def
          │
          ▼
phonecortrol_dllMain.cpp
  ├─ g_LibInfo_phonecortrol_global_var
  │    ├─ GUID、版本、Windows/GBK 标识
  │    ├─ 22 条命令描述 + 22 个函数指针
  │    ├─ 6 个自定义数据类型
  │    ├─ 0 个预定义常量
  │    └─ phonecortrol_ProcessNotifyLib_phonecortrol
  │
  ├─ 系统通知 NL_SYS_NOTIFY_FUNCTION
  │          ▼
  │   elib/fnshare.cpp::ProcessNotifyLib
  │          ├─ 保存易语言系统通知函数指针
  │          ├─ 查询调试/运行版本
  │          └─ 可转发到用户通知函数
  │
  ├─ 命令元数据（cmdInfo） ───────┐
  │                                │
  ├─ 命令函数指针数组（cmdDef）     │ 易语言命令调用
  │                                ▼
  │              phonecortrol_cmdDef.cpp
  │                ├─ 呼叫/断开/应答
  │                ├─ 播放/录音/按键/保持/转接
  │                ├─ 传真
  │                └─ 调制解调器文件传输
  │                    （当前仅参数读取/空体，无设备执行）
  │
  └─ 自定义数据类型（dtType）
       ├─ PhoneControl 组件
       │    ├─ 组件创建/属性接口分发
       │    ├─ 5 个业务属性 + 8 个固定窗口属性
       │    └─ 10 个事件描述
       ├─ KeyInterrupt / LineKind / SoundFile / PlayNumberType 枚举
       └─ 隐藏 ModemFile 命令分组
```

## 3. 仓库结构与模块职责

```text
phonecortrol/
├── ARCHITECTURE.md                         本架构建档（本文）
├── phonecortrol.sln                        两个 VS 项目的解决方案
├── phonecortrol.vcxproj                    DLL 支持库工程
├── phonecortrol.vcxproj.filters            DLL 工程文件过滤器
├── phonecortrol.vcxproj.user               空用户工程设置
├── phonecortrol_static/
│   ├── phonecortrol_static.vcxproj         静态库工程，复用上级源码
│   ├── phonecortrol_static.vcxproj.filters 静态库过滤器
│   └── phonecortrol_static.vcxproj.user    空用户工程设置
├── Source_phonecortrol.def                 DLL 导出 GetNewInf
├── include_phonecortrol_header.h            公共聚合头与命令声明
├── phonecortrol_cmd_typedef.h              命令 X-macro、符号命名规则
├── phonecortrol_cmdDef.cpp                 22 个命令执行函数骨架
├── phonecortrol_cmdInfo.cpp                参数/命令编辑器元数据
├── phonecortrol_dtType.cpp                 组件、属性、事件、枚举和接口回调
├── phonecortrol_const.cpp                  空预定义常量表
├── phonecortrol_dllMain.cpp                DLL 入口、库信息、通知分发
└── elib/
    ├── lib2.h                              易语言支持库 ABI/数据结构/通知常量
    ├── lang.h                              编译语言版本（GBK）
    ├── krnllib.h                           核心支持库相关定义
    ├── mtypes.h                            跨编译环境基础类型与 Win32 句柄别名
    ├── fnshare.h / fnshare.cpp             内存、通知、数据复制等共享辅助层
    ├── untshare.h                          组件共享辅助类/窗口辅助模板（当前未被目标源码直接 include）
    └── PublicIDEFunctions.h                IDE 辅助功能定义（当前未被目标源码直接 include）
```

### 3.1 模块职责与状态

| 模块 | 主要职责 | 当前状态 |
|---|---|---|
| `phonecortrol_cmd_typedef.h` | 以 X-macro 维护命令索引、中文名、英文名、返回类型、参数数量和参数表起始偏移；生成命令符号名。 | **已实现（登记机制）**。命令 17 的英文名复用 `SendFax`，但索引仍区分。 |
| `include_phonecortrol_header.h` | 引入 `elib` ABI，声明全局元数据数组，并二次展开命令函数声明。 | **已实现**。动态库专属全局数组声明受 `__E_STATIC_LIB` 控制。 |
| `phonecortrol_cmdInfo.cpp` | 构造 30 个参数的 `ARG_INFO` 表和 22 个 `CMD_INFO` 表。 | **已实现（编辑信息）**；仅在非静态库模式编译。 |
| `phonecortrol_cmdDef.cpp` | 提供 22 个 `PFN_EXECUTE_CMD` 入口。 | **仅声明/骨架**：有参数的函数只把 `pArgInf[1..n]` 读入局部变量，未调用电话/传真/调制解调器 API，未写 `pRetData`。 |
| `phonecortrol_dtType.cpp` | 注册 `LIB_DATA_TYPE_INFO`，描述组件、枚举、隐藏命令分组；分发组件创建、属性和通知接口。 | **元数据已实现；运行时组件仅声明**。 |
| `phonecortrol_dllMain.cpp` | DLL 入口、函数指针数组、`LIB_INFO`、`GetNewInf`、系统通知处理、静态编译命令名数组。 | **已实现（框架层）**；业务资源释放和多数通知分支为空。 |
| `phonecortrol_const.cpp` | 支持库预定义常量登记。 | **已实现为空表**，数量为 0。 |
| `elib/fnshare.*` | 保存系统通知函数、转发通知、判断调试运行版本、封装易语言内存与数据复制。 | **共享基础层已实现**；本项目未显示使用其内存/复制辅助函数。 |
| `elib/lib2.h` 等 | 提供易语言 SDK ABI 的数据类型、命令/事件/属性结构、通知号和 `LIB_INFO`。 | **外部/随仓库头文件依赖**；不是本项目电话业务实现。 |

## 4. 核心数据流

### 4.1 支持库加载与调用链

1. 易语言加载 DLL 的固定导出 `GetNewInf`（`Source_phonecortrol.def:3-4`）。
2. `GetNewInf()` 返回 `g_LibInfo_phonecortrol_global_var`（`phonecortrol_dllMain.cpp:89-92`）。
3. `LIB_INFO` 将命令描述数组、命令函数指针数组、数据类型数组和通知回调地址交给易语言（`phonecortrol_dllMain.cpp:31-86`）。
4. 易语言根据 `CMD_INFO` 的命令索引和参数表构造 `PMDATA_INF` 参数，调用对应 `PFN_EXECUTE_CMD`（命令函数签名由 `include_phonecortrol_header.h:22-24` 生成）。
5. 当前命令函数只读取参数；没有向设备驱动、电话线路、传真服务或调制解调器发出调用，返回数据也未填充。因此“命令可在 IDE 中显示”与“命令可执行”必须分开理解。

### 4.2 系统通知流

```text
易语言系统
   │ NL_SYS_NOTIFY_FUNCTION（dwParam1 = PFN_NOTIFY_SYS）
   ▼
phonecortrol_ProcessNotifyLib_phonecortrol
   │ ProcessNotifyLib(nMsg, dwParam1, dwParam2)
   ▼
elib/fnshare.cpp
   ├─ 保存 s_pfnNotifySys
   ├─ 调用 NRS_GET_PRG_TYPE 初始化调试/发布版本标记
   └─ 后续可通过 NotifySys 回调易语言系统
```

上述转发与保存函数指针的链路有源码实现（`phonecortrol_dllMain.cpp:125-132`、`elib/fnshare.cpp:11-36`）；电话事件如何进入 `NRS_EVENT_NOTIFY2` 的业务链路未实现/未见调用。

### 4.3 组件数据流

```text
IDE 拖放 PhoneControl
        │
        ▼
phonecortrol_GetInterface_PhoneControl(ITF_CREATE_UNIT)
        │
        ▼
phonecortrol_ControlCreate_PhoneControl
        │
        └─ 当前返回 HUNIT(0)，未创建真实单元

IDE 属性读取/修改
        ├─ ITF_GET_PROPERTY_DATA      → 当前未填充属性值
        ├─ ITF_GET_ALL_PROPERTY_DATA  → 当前返回 0
        ├─ ITF_NOTIFY_PROPERTY_CHANGED → 仅保留 case 0 骨架
        └─ ITF_PROPERTY_UPDATE_UI    → 固定返回 TRUE
```

## 5. 命令、接口与数据模型

### 5.1 22 条命令

命令索引、易语言中文名、英文符号、返回类型和参数数量以 `phonecortrol_cmd_typedef.h:12-34` 为准；执行函数位于 `phonecortrol_cmdDef.cpp` 同索引后缀的函数中。

| 索引 | 命令 | 英文符号 | 返回类型 | 参数 | 参数摘要 | 状态 |
|---:|---|---|---|---:|---|---|
| 0 | 呼叫 | `Call` | `SDT_BOOL` | 2 | 终端号码、等待时间（默认 60 秒） | 仅声明 |
| 1 | 断开 | `Disconnect` | `SDT_INT` | 0 | 无 | 仅声明 |
| 2 | 应答 | `Answer` | `SDT_BOOL` | 0 | 无 | 仅声明 |
| 3 | 播放 | `Play` | `SDT_BOOL` | 2 | WAV 文件名、中断方式 | 仅声明 |
| 4 | 录音 | `Record` | `SDT_BOOL` | 3 | 文件名、中断方式、秒数 | 仅声明 |
| 5 | 停止 | `Stop` | `SDT_BOOL` | 0 | 停止播放/录音 | 仅声明 |
| 6 | 检测按键 | `DetectKey` | `SDT_BOOL` | 1 | 是否检测按键 | 仅声明 |
| 7 | 产生按键 | `GenerateKey` | `SDT_BOOL` | 1 | DTMF 按键字符串 | 仅声明 |
| 8 | 保持 | `Hold` | `SDT_BOOL` | 1 | 是否保持 | 仅声明 |
| 9 | 转接 | `Transfer` | `SDT_BOOL` | 1 | 终端号码 | 仅声明；复用参数表偏移 0 |
| 10 | 收集按键 | `GatherKey` | `SDT_BOOL` | 4 | 个数、终止键、首键超时、键间超时 | 仅声明 |
| 11 | 初始化 | `Init` | `SDT_BOOL` | 0 | 初始化支持库 | 仅声明 |
| 12 | 清除 | `Clear` | `SDT_BOOL` | 0 | 清除支持库资源 | 仅声明 |
| 13 | 设置声音文件 | `SetSoundFile` | `SDT_BOOL` | 2 | 声音类型、WAV 文件名 | 仅声明 |
| 14 | 播放数字 | `PlayNumber` | `SDT_BOOL` | 4 | 数字、播放类型、声音类型、间隔 | 仅声明 |
| 15 | 初始化传真 | `InitFax` | `SDT_BOOL` | 1 | 传真设备号（默认 1） | 仅声明 |
| 16 | 发送传真 | `SendFax` | `SDT_BOOL` | 2 | 电话号码、文件名 | 仅声明 |
| 17 | 开启接收传真 | `SendFax` | `SDT_BOOL` | 1 | 是否开启 | 仅声明；英文符号疑似复用错误 |
| 18 | 清除传真 | `ClearFax` | `SDT_BOOL` | 0 | 清除传真资源 | 仅声明 |
| 19 | 发送文件 | `ModemSendFile` | `SDT_BOOL` | 4 | 串口、号码、文件路径、延时毫秒 | 仅声明 |
| 20 | 接收文件 | `ModemRecvFile` | `SDT_BOOL` | 2 | 串口、文件路径 | 仅声明 |
| 21 | 获得错误 | `ModemFileError` | `SDT_TEXT` | 0 | 调制解调器错误信息 | 仅声明 |

### 5.2 自定义数据类型

`phonecortrol_dtType.cpp:187-236` 注册 6 项：

1. `电话控制 / PhoneControl`：Windows 窗口单元、功能提供者；包含命令索引 0-18、属性和 10 个事件。
2. `按键中断 / KeyInterrupt`：12 个整数枚举成员，包含不可中断、任意键和 0-9 键中断。
3. `线路类型 / LineKind`：电话=1、主机=2、IP=3。
4. `声音文件 / SoundFile`：零至负等 20 个声音语义枚举成员，值为 0-19。
5. `播放数字类型 / PlayNumberType`：数字=1、金额=2。
6. `文件传送与接收 / ModemFile`：隐藏类型，提供命令索引 19-21。

### 5.3 PhoneControl 属性模型

属性元数据位于 `phonecortrol_dtType.cpp:59-84`：

- 固定窗口属性 8 个：左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针。
- 业务属性 5 个：
  - `LineCount` / 线路总数：整数，只读；
  - `LineName` / 线路名称：文本，只读；
  - `LineNo` / 线路号：整数，不能在设计时初始化；
  - `LineKind` / 线路类型：整数，不能在设计时初始化；
  - `ErrorText` / 错误信息：文本，只读。

这些是 IDE 属性描述，不是已存在的运行时状态对象；`ControlCreate`、`PropGetDataAll` 和 `PropGetData` 尚未提供对应存储或设备查询逻辑。

### 5.4 事件模型

事件元数据位于 `phonecortrol_dtType.cpp:151-185`，共 10 个：

| 事件 | 参数 | 源码语义 |
|---|---:|---|
| 接通 | 0 | 线路接通 |
| 振铃 | 1 | 来电每次振铃；之后可调用应答 |
| 来电显示 | 1 | 捕获来电号码 |
| 断开 | 0 | 呼叫断开 |
| 检测按键 | 1 | 对方按键 |
| 收集按键完毕 | 2 | 收集完成及触发原因 |
| 播放完毕 | 1 | 播放结束及文件名 |
| 录音完毕 | 0 | 录音结束 |
| 保持 | 0 | 呼叫进入保持 |
| 振铃之前 | 0 | 可在此开启接收传真 |

事件参数池包含次数、来电号码、键值、按键串、事件触发原因、文件名，类型为整数/文本/字节。当前未见 `NRS_EVENT_NOTIFY` 或 `NRS_EVENT_NOTIFY2` 调用，故事件“能被触发”属于**未实现/未验证**，不能由表定义推出运行时行为。

## 6. 对外接口与 ABI

### 6.1 DLL 接口

| 接口 | 位置 | 作用 | 状态 |
|---|---|---|---|
| `GetNewInf()` | `phonecortrol_dllMain.cpp:89-92`；`.def:3-4` | 返回 `PLIB_INFO` | 已实现 |
| `phonecortrol_ProcessNotifyLib_phonecortrol()` | `phonecortrol_dllMain.cpp:101-177` | 接收易语言通知；动态库模式返回命令函数名表、通知函数名和依赖库列表 | 框架已实现，业务通知分支为空 |
| `phonecortrol_GetInterface_PhoneControl()` | `phonecortrol_dtType.cpp:240-304` | 按 `ITF_*` 返回组件回调 | 分发已实现，回调多为空骨架 |

动态库 `LIB_INFO` 的关键值（`phonecortrol_dllMain.cpp:31-86`）：

- 格式号：`LIB_FORMAT_VER`；GUID：`2AF84E852855471aAFB52EB3CA85580D`；版本 `2.0.0`。
- 需要易语言系统 `3.7`、核心支持库 `3.7`。
- 名称：`电话语音支持库`；语言：`__GBK_LANG_VER`；平台：Windows。
- 命令数：`g_cmdInfo...`（静态分析为 22）；数据类型数：6；预定义常量数：0。
- 没有额外静态依赖列表（返回 `"\0\0"`）；`m_szzDependFiles` 为 `NULL`。

### 6.2 组件接口分发

`phonecortrol_GetInterface_PhoneControl` 当前返回实现函数的接口号：

- `ITF_CREATE_UNIT` → `phonecortrol_ControlCreate_PhoneControl`
- `ITF_PROPERTY_UPDATE_UI` → `phonecortrol_PropUpDate_PhoneControl`
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `phonecortrol_PropPopDlg_PhoneControl`
- `ITF_NOTIFY_PROPERTY_CHANGED` → `phonecortrol_PropChanged_PhoneControl`
- `ITF_GET_ALL_PROPERTY_DATA` → `phonecortrol_PropGetDataAll_PhoneControl`
- `ITF_GET_PROPERTY_DATA` → `phonecortrol_PropGetData_PhoneControl`
- `ITF_IS_NEED_THIS_KEY` → `phonecortrol_PropKetInfo_PhoneControl`
- `ITF_GET_NOTIFY_RECEIVER` → `phonecortrol_PropNotifyReceiver_PhoneControl`

图标数据、语言转换、消息过滤接口返回 `NULL`（`phonecortrol_dtType.cpp:275-303`），属于当前未提供的接口。

## 7. 构建与依赖

### 7.1 工程结构

- `phonecortrol.sln:5-7` 包含 `phonecortrol` DLL 工程和 `phonecortrol_static` 静态库工程。
- DLL 工程：`ConfigurationType=DynamicLibrary`，Win32/x64、Debug/Release 均列出；Win32 配置使用 `v141`、Windows SDK `10.0.15063.0`，Win32 Debug/Release 的输出扩展名为 `.fne`（`phonecortrol.vcxproj:43-76,95-108`）。
- 静态工程：`ConfigurationType=StaticLibrary`，源码全部通过 `..\` 复用根目录实现文件（`phonecortrol_static/phonecortrol_static.vcxproj:21-38,48-73`）。
- 两个工程都无自定义测试目标、安装目标、PostBuild 命令或外部包管理文件；`.user` 文件只有空 `PropertyGroup`。

### 7.2 代码依赖

| 依赖 | 来源 | 用途 |
|---|---|---|
| 易语言支持库 ABI | `elib/lib2.h` | `LIB_INFO`、`CMD_INFO`、`EVENT_INFO2`、`LIB_DATA_TYPE_INFO`、`PMDATA_INF`、通知号和宏命名规则 |
| 基础类型/句柄 | `elib/mtypes.h`（由 `lib2.h` 链接使用） | `INT`、`DWORD`、`HWND`、`HUNIT` 等 |
| 语言版本 | `elib/lang.h` | `__GBK_LANG_VER`、`__COMPILE_LANG_VER` |
| 核心支持库定义 | `elib/krnllib.h` | 易语言核心相关常量/接口定义 |
| 共享通知与内存辅助 | `elib/fnshare.h/.cpp` | `NotifySys`、`ProcessNotifyLib`、`ealloc`/`efree` 等 |
| Windows/Visual C++ | 工程平台与 `v141` 工具集 | DLL、Win32/x64、Windows API 类型和链接环境 |

未见 `README`、`CMakeLists.txt`、`Makefile`、`package`/依赖清单、第三方电话 SDK 或实际调制解调器/传真库链接配置。`PublicIDEFunctions.h` 与 `untshare.h` 被工程列为头文件，但当前目标源码未直接 include；它们更像支持库模板附带能力。

### 7.3 工程配置风险（源码事实与验证边界分开）

- 根 DLL 工程的 Win32 配置定义 `__E_FNENAME=phonecortrol`，但 x64 配置的预处理器定义（`phonecortrol.vcxproj:159-184`）没有该宏；`elib/lib2.h:17-24` 明确要求先定义 `__E_FNENAME`，因此 x64 是否可编译需要在 Windows 工具链实测，当前仅能记录为高风险配置漂移。
- 根 DLL 工程 x64 配置没有 Win32 配置中的 `.def` 模块定义文件设置（`phonecortrol.vcxproj:121-126,171-175,191-197`），导出 `GetNewInf` 的行为未验证。
- 静态工程 Win32 定义 `__E_STATIC_LIB;__E_FNENAME=phonecortrol`（`phonecortrol_static/phonecortrol_static.vcxproj:92-120`），但 x64 配置的预处理器定义没有这两个宏（`...:130-152`）；这会改变 `#ifndef __E_STATIC_LIB` 的编译分支，且同样受 `__E_FNENAME` 要求影响。
- 静态工程 x64 配置指定 `PrecompiledHeader=Use`（`...:130-154`），仓库跟踪文件中未见 `pch.h`/`pch.cpp`；是否由外部环境提供、是否导致构建失败，当前未验证。
- 解决方案的 x86 映射到项目 Win32，x64 映射到项目 x64（`phonecortrol.sln:10-32`），但项目自身的 x64 宏/导出设置与 Win32 不一致。

## 8. 测试、验证与未决事项

### 8.1 当前可证明的静态验证

- Git 跟踪文件总数为 23；其中 C/C++ 源码/头文件 15 个；未见测试文件、测试工程或测试脚本。
- 独立静态扫描得到 `phonecortrol_cmdDef.cpp` 中 22 个命令函数，`PHONECORTROL_DEF` 中 22 个命令元数据行，索引范围 0-21 一致。
- `phonecortrol_dtType.cpp` 的组件命令索引为 0-18，隐藏 `ModemFile` 命令索引为 19-21，与命令定义范围相符。
- 工程文件引用的根源码、`elib` 头文件和静态库复用路径均已人工核对；没有执行源文件改写、依赖安装或构建产物生成。

### 8.2 未执行/不能认定通过的验证

- 未在 macOS 上执行 Visual Studio/MSBuild；Windows API、`v141` 工具集、易语言宿主 ABI 和 DLL 导出均未运行验证。
- 未连接电话线路、传真服务、调制解调器或 DirectX 环境，无法验证设备行为、音频格式、传真和文件传送。
- 未验证 `pArgInf` 的实际参数布局、`pRetData` 返回协议、资源释放协议和事件通知参数所有权。
- 未验证 x64 配置的宏、预编译头、`.def` 导出和静态库链接问题。

### 8.3 首轮实现闭环前必须补齐

1. 为每个命令建立真实电话/传真/调制解调器后端和错误码策略，并在函数末尾正确填充 `pRetData`。
2. 为 `Init`/`Clear`、传真初始化/清除、线路切换和并发调用定义资源所有权与生命周期。
3. 实现 `PhoneControl` 的真实 `HUNIT`、属性存储/序列化/实时查询及销毁路径。
4. 通过 `NRS_EVENT_NOTIFY2`（或对应 ABI）实现并验证 10 个事件的触发、参数类型和线程边界。
5. 复核命令元数据：尤其是索引 9 复用参数表偏移 0、索引 17 的英文符号 `SendFax` 重复问题。
6. 统一 Win32/x64 DLL 与静态工程的 `__E_FNENAME`、`__E_STATIC_LIB`、`.def`/目标扩展名和预编译头配置。
7. 在 Windows + 易语言宿主中增加至少一组 ABI 加载测试、命令参数/返回值测试、属性序列化测试、事件通知测试和资源清理测试。

## 9. Git 基线与证据索引

### 9.1 Git 基线

- 远端：`https://gitee.com/JYtechnology/phonecortrol.git`
- 分支：`master`；HEAD 与 `origin/master` 同为 `e12c5fd59f9118dd80373fbca450576f4def26da`。
- 提交：`初始化仓库`
- 提交者：`精易科技 <413188828@qq.com>`
- 提交时间：2022-12-19 16:12:51 +0800
- 建档前工作树：干净；仓库为浅克隆（当前基线只有这一条可见历史提交）。
- 本次允许改动：仅新增根目录 `ARCHITECTURE.md`；未修改源码、工程、依赖、测试、配置或 Git 元数据。

### 9.2 关键证据路径

| 事实 | 证据 |
|---|---|
| 固定导出 | `Source_phonecortrol.def:1-4` |
| DLL/静态工程成员 | `phonecortrol.sln:5-40`；两个 `.vcxproj` 的 `ItemGroup` |
| 命令统一定义 | `phonecortrol_cmd_typedef.h:3-34` |
| 参数与命令元数据 | `phonecortrol_cmdInfo.cpp:5-79` |
| 命令函数骨架 | `phonecortrol_cmdDef.cpp:3-203` |
| 库信息、函数指针数组、通知 | `phonecortrol_dllMain.cpp:26-177` |
| 组件/枚举/属性/事件元数据 | `phonecortrol_dtType.cpp:43-238` |
| 组件接口与空回调 | `phonecortrol_dtType.cpp:240-418` |
| 空常量表 | `phonecortrol_const.cpp:12-18` |
| 公共 ABI 聚合头 | `include_phonecortrol_header.h:1-26` |
| 通知/内存共享辅助 | `elib/fnshare.cpp:1-71`；`elib/fnshare.h:20-55` |
| ABI 结构/通知号/宏 | `elib/lib2.h`，重点为 `:160-243,266-389,465-543,693-729,780-824,1046-1239,1246-1319` |
| 语言与基础类型 | `elib/lang.h:1-14`；`elib/mtypes.h:1-171` |
| Win32/x64 宏与工程漂移 | `phonecortrol.vcxproj:43-202`；`phonecortrol_static/phonecortrol_static.vcxproj:40-167` |

