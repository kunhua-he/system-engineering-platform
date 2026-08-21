# edirectx 架构建档

## 1. 项目定位

`edirectx` 是一个面向易语言支持库 ABI 的 Windows C++ 项目，目标名称为“DirectX2D支持库”。仓库提供动态库工程 `edirectx` 和静态库工程 `edirectx_static`，通过易语言支持库的 `LIB_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`PFN_EXECUTE_CMD` 等结构暴露命令、对象数据类型、常量和 IDE 交互接口。

**当前结论：**当前仓库主要是由支持库生成模板/接口元数据组成的骨架。命令表和参数/数据类型描述较完整，但 `edirectx_cmdDef.cpp` 中的 284 个命令函数只读取参数到局部变量，没有写入 `pRetData`、调用 DirectX 或返回业务结果；输入设备组件回调也保留 TODO/默认返回。因此不能把它描述为已实现的 DirectX 2D 功能库。

## 2. 真实调用流程

```text
易语言 IDE/运行时
    │
    ├─ 动态装载 edirectx.fne
    │      └─ 按 .def 导出名调用 GetNewInf
    │             └─ 返回静态 LIB_INFO
    │                    ├─ g_DataType_edirectx_global_var[16]
    │                    ├─ g_cmdInfo_edirectx_global_var[284]
    │                    ├─ g_cmdInfo_edirectx_global_var_fun[284]
    │                    └─ g_ConstInfo_edirectx_global_var[1]（实际常量数=0）
    │
    ├─ 按 CMD_INFO 解析中文名/英文名/返回类型/参数区
    │      └─ 通过函数指针调用 edirectx_<英文名>_<索引>_edirectx
    │             └─ 当前实现：读取 pArgInf 参数到局部 argN
    │                    └─ 未写 pRetData、未执行 DirectX、无实际结果
    │
    ├─ 系统通知 NL_SYS_NOTIFY_FUNCTION 等
    │      └─ edirectx_ProcessNotifyLib_edirectx
    │             └─ elib/fnshare.cpp::ProcessNotifyLib
    │                    ├─ 保存 PFN_NOTIFY_SYS
    │                    └─ 转发用户通知回调（如已设置）
    │
    └─ IDE 放置“输入设备”组件
           └─ edirectx_GetInterface_CDXInput
                  └─ 创建/属性/按键/尺寸等回调
                         └─ 当前多为默认值或 TODO
```

## 3. 仓库与工程地图

仓库根目录：

`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/edirectx`

```text
edirectx/
├── edirectx.sln                         # VS 解决方案，动态库+静态库
├── edirectx.vcxproj                     # 动态库项目
├── edirectx.vcxproj.filters              # 动态库 IDE 文件筛选器
├── edirectx.vcxproj.user                 # 空用户属性组
├── edirectx_static/
│   ├── edirectx_static.vcxproj           # 静态库项目，复用根目录源码
│   ├── edirectx_static.vcxproj.filters
│   └── edirectx_static.vcxproj.user      # 空用户属性组
├── Source_edirectx.def                   # 动态库导出 GetNewInf
├── include_edirectx_header.h             # 总头文件与元数据 extern/命令声明
├── edirectx_cmd_typedef.h                # 单一命令宏表 EDIRECTX_DEF
├── edirectx_cmdDef.cpp                   # 284 个命令函数骨架
├── edirectx_cmdInfo.cpp                  # 412 条参数元数据与 284 条 CMD_INFO
├── edirectx_dtType.cpp                   # 数据类型、成员、事件、IDE 回调
├── edirectx_const.cpp                    # 常量数组；当前实际常量数为 0
├── edirectx_dllMain.cpp                  # DllMain、LIB_INFO、GetNewInf、系统通知
└── elib/
    ├── lib2.h                            # 易语言支持库 ABI 基础结构/宏/类型
    ├── mtypes.h                          # 基础类型、兼容宏
    ├── lang.h                            # 编译语言版本，当前 GBK
    ├── krnllib.h                         # 系统核心支持库/控件类型常量
    ├── PublicIDEFunctions.h              # IDE 公共函数/属性/事件常量
    ├── untshare.h                        # 组件辅助宏/通用实现
    ├── fnshare.h                         # 系统通知、易语言内存和数组辅助函数
    └── fnshare.cpp                       # 通知回调状态与转发实现
```

工程文件显式列入动态库和静态库的 6 个编译单元：`elib/fnshare.cpp`、`edirectx_cmdDef.cpp`、`edirectx_const.cpp`、`edirectx_dllMain.cpp`、`edirectx_dtType.cpp`、`edirectx_cmdInfo.cpp`；头文件来自 `elib/`、`include_edirectx_header.h`、`edirectx_cmd_typedef.h`。证据：`edirectx.vcxproj:21-42`、`edirectx_static/edirectx_static.vcxproj:21-39`。

## 4. 构建目标与配置

### 4.1 解决方案

`edirectx.sln:5-7` 注册两个 Visual Studio C++ 项目：

- `edirectx.vcxproj`：`DynamicLibrary`，项目 GUID `{CEADC3DD-024E-4173-9CCF-E60334B2944F}`。
- `edirectx_static/edirectx_static.vcxproj`：`StaticLibrary`，项目 GUID `{5FF16995-6AD6-4964-A421-E0842E1BE946}`。
- 配置矩阵为 `Debug/Release × x86(x Win32)/x64`，见 `edirectx.sln:9-32`。

### 4.2 动态库工程

`edirectx.vcxproj` 声明：

- Visual Studio C++ 工程，`PlatformToolset=v141`，Windows SDK `10.0.15063.0`，Unicode 字符集，见 `:43-76`。
- Win32 Debug/Release 的 `ConfigurationType=DynamicLibrary`，输出扩展名显式为 `.fne`，见 `:95-102`。
- Win32 Debug/Release 使用 `Source_edirectx.def` 作为 `ModuleDefinitionFile`，见 `:109-157`。
- x64 Debug/Release 没有设置 `TargetExt=.fne`，也没有设置 `ModuleDefinitionFile`，见 `:159-198`；这与 Win32 动态库配置不对称，属于需要在 Windows/VS 上复核的发布风险。
- Win32 预处理宏含 `__E_FNENAME=edirectx`、`EDIRECTX_EXPORTS`、`_USRDLL`；静态库宏含 `__E_STATIC_LIB`，见动态工程 `:109-120`、静态工程 `:92-101`。

### 4.3 静态库工程

`edirectx_static/edirectx_static.vcxproj:48-73` 将目标设为 `StaticLibrary`，复用根目录的同一批 `.cpp/.h`。`__E_STATIC_LIB` 会改变头文件和 `edirectx_dllMain.cpp` 的编译分支：动态库元数据数组、`DllMain`、命令函数表等部分受 `#ifndef __E_STATIC_LIB` 保护；静态链接的真实宿主接线不在本仓库中，尚未验证。

### 4.4 导出与依赖

`Source_edirectx.def:1-4` 仅声明：

```text
LIBRARY

EXPORTS
    GetNewInf
```

`edirectx_dllMain.cpp:89-95` 的 `GetNewInf()` 返回 `&g_LibInfo_edirectx_global_var`。`LIB_INFO.m_pfnNotify` 指向 `edirectx_ProcessNotifyLib_edirectx`，依赖文件字段为 `NULL`（`:75-86`）。静态库依赖查询分支 `NL_GET_DEPENDENT_LIBS` 返回空字符串列表 `"\0\0"`（`:123-129`）。

## 5. 核心模块与真实职责

### 5.1 `edirectx_cmd_typedef.h`：单一命令宏表

`EDIRECTX_DEF(_MAKE)` 位于 `edirectx_cmd_typedef.h:12-297`，同一张宏表被重复展开为：

- `include_edirectx_header.h:22-24`：命令函数声明；
- `edirectx_cmdInfo.cpp:592-600`：`CMD_INFO` 元数据数组；
- `edirectx_dllMain.cpp:26-29`：命令函数指针数组；
- `edirectx_dllMain.cpp:97-101`：静态编译用函数名数组。

解析结果：

| 项目 | 事实 |
|---|---:|
| 命令索引 | 0–283，连续 284 条 |
| 命令中文/显示名 | 284 条，部分同名是不同对象的方法 |
| 英文实现名唯一数 | 253 个，索引被拼入最终符号以避免冲突 |
| Windows 命令 | 全部带 `_CMD_OS(__OS_WIN)` |
| 隐藏命令 | 84 条，含构造/析构/内部兼容命令 |
| 对象构造标记 | 8 条 |
| 对象析构标记 | 8 条 |
| 对象拷贝构造标记 | 2 条 |
| 参数总数（按命令声明计） | 436 |
| 单命令最大参数数 | 10 |
| 返回类型 | `SDT_BOOL` 160、`SDT_INT` 50、`_SDT_NULL` 59、`SDT_TEXT` 3、`SDT_FLOAT` 3、`SDT_BYTE` 1、`SDT_DOUBLE` 1、其余为复合类型表达式 |

主要命令域按索引区间分组：

| 索引 | 归属数据类型 | 数量 | 代表能力（仅元数据命名） |
|---:|---|---:|---|
| 0–11 | `CDXLayer` 滚动页面 | 12 | 创建、滚动、移动、绘制 |
| 12–60 | `CDXInput` 输入设备 | 49 | 初始化、鼠标/键盘/控制器位置和状态、独占、灵敏度 |
| 61–106 | `CDXScreen` 屏幕 | 46 | 全屏/窗口、位图、调色板、翻页、视频模式 |
| 107–192 | `CDXSurface` 页面 | 86 | 像素/线/矩形/文字、块复制、透明/缩放/旋转、字体/锁定 |
| 193–200 | `CDXMusic` MIDI 音乐 | 8 | 播放/停止/暂停/音轨相关基础操作 |
| 201–210 | `CDXMusicCd` CD 音乐 | 10 | 音轨、长度、播放、读取 |
| 211–227 | `CDXSound` 声音 | 17 | DirectSound 初始化、3D、音量、MIDI/CD 音量 |
| 228–244 | `DirectSoundBuffer` WAVE 声音 | 17 | Wave 装载、播放、音量、声道、频率、3D |
| 245–283 | `CDXSprite` 精灵 | 39 | 位置/速度/帧/透明度/阴影/缩放/碰撞/绘画 |

上述“能力”是 `EDIRECTX_DEF` 的显示契约，不代表当前运行实现已经完成。

### 5.2 `edirectx_cmdDef.cpp`：命令执行层

`edirectx_cmdDef.cpp:1-2769` 定义了 284 个 `EDIRECTX_EXTERN_C void edirectx_<name>_<index>_edirectx(...)` 函数，与命令索引一一对应。对全部函数做静态扫描的结果：

- 284 个函数定义，284 个唯一符号。
- `pRetData` 只出现在函数签名中，没有写回语句。
- 没有 `return` 语句、DirectX API 调用、`NotifySys` 调用、`ealloc/efree` 调用或状态保存。
- 函数体最多把 `pArgInf[n]` 读取到 `argN` 局部变量；没有业务执行语句。
- 因而当前命令调用的真实结果不是元数据所声明的 BOOL/INT/对象结果，而是未完成的空壳行为。

代表性证据：`edirectx_cmdDef.cpp:19-29` 的 `CreateWithFile`、`:129-159` 的输入设备初始化/刷新、`:571-597` 的屏幕创建、以及文件末段的精灵命令均为参数读取后空体。

### 5.3 `edirectx_cmdInfo.cpp`：参数和命令元数据

`edirectx_cmdInfo.cpp:4-585` 在动态编译分支中定义 `g_argumentInfo_edirectx_global_var[]`，共有 412 条编号连续的 `ARG_INFO` 记录（索引 `000–411`）。字段包含参数名、解释、参数类型、默认值、`AS_*` 参数标志；例如 `:20-43` 定义屏幕/文件名/存储位置/窗口句柄/是否重置等参数。

`edirectx_cmdInfo.cpp:592-602` 用 `EDIRECTX_DEF_CMDINFO` 展开出 `g_cmdInfo_edirectx_global_var[]`，命令数由 `sizeof` 计算，不硬编码。Debug 下 `:587-589` 提供 `dbg_cmd_arg_count__`，用于确认参数编号与数组长度一致；仓库没有配套自动化测试调用该检查。

### 5.4 `edirectx_dtType.cpp`：数据类型、事件和 IDE 组件接口

`edirectx_dtType.cpp:473-592` 定义 16 个 `LIB_DATA_TYPE_INFO`：

| 序号 | 中文名 | 英文名 | 命令/成员/状态 |
|---:|---|---|---|
| 0 | 输入设备 | `CDXInput` | 49 命令，6 事件，窗口组件/功能提供者 |
| 1 | 滚动页面 | `CDXLayer` | 12 命令，1 个句柄成员，隐藏 |
| 2 | `CDXMap` | `CDXMap` | 1 个隐藏句柄成员 |
| 3 | `CDXMapCell` | `CDXMapCell` | 1 个隐藏句柄成员 |
| 4 | MIDI音乐 | `CDXMusic` | 8 命令，1 个句柄成员 |
| 5 | CD音乐 | `CDXMusicCd` | 10 命令，1 个句柄成员，隐藏 |
| 6 | 屏幕 | `CDXScreen` | 46 命令，1 个句柄成员 |
| 7 | 声音 | `CDXSound` | 17 命令，1 个句柄成员 |
| 8 | WAVE声音 | `DirectSoundBuffer` | 17 命令，1 个句柄成员 |
| 9 | 精灵 | `CDXSprite` | 39 命令，1 个句柄成员，隐藏 |
| 10 | 页面 | `CDXSurface` | 86 命令，1 个句柄成员 |
| 11 | 调色板单元 | `PaletteEntry` | 4 个成员：red/green/blue/alpha |
| 12 | 矩形 | `rect` | 4 个成员：left/top/right/bottom |
| 13 | 键值常量 | `KeyConst` | 166 个键盘/鼠标/控制器常量，枚举 |
| 14 | 声音常量 | `SoundConst` | 5 个常量，含 3D 模式和左右声道 |
| 15 | 内存类别 | `MemKindConst` | 3 个常量：`VideoMemory`/`SystemMemory`/`VideoThenSys` |

9 个带命令索引的数组在 `:45-127` 中明确列出索引区间，总计 284 条命令。成员数组总计 192 个成员行（10 个句柄成员、4+4 个结构成员、166 个键值、5 个声音、3 个内存类别）。

`CDXInput` 事件在 `:427-471`：事件参数 20 个逻辑参数定义、6 个事件（控制器位置/按钮、鼠标位置/按键/滚轮、键盘按键状态）。

### 5.5 输入设备 IDE 回调

`edirectx_dtType.cpp:597-660` 的 `edirectx_GetInterface_CDXInput` 按 `ITF_*` 返回组件回调：创建、属性更新、定制对话框、属性变更、取全部/单个属性、按键需求、通知接收器等。

实现状态：

- `edirectx_ControlCreate_CDXInput` `:662-679` 只返回 `hUnit=0`，明确含 `TODO`。
- `edirectx_PropUpDate_CDXInput` `:681-686` 固定返回 `TRUE`。
- `edirectx_PropPopDlg_CDXInput` `:688-696` 设置 `*pblModified=false` 后返回 `FALSE`。
- `edirectx_PropChanged_CDXInput` `:698-717` 仅有空的 `case 0`，默认返回 `false`。
- `edirectx_PropGetDataAll_CDXInput` `:719-724` 返回 `0`。
- `edirectx_PropGetData_CDXInput` `:726-746` 仅有空的 `case 0`，默认最终返回 `true`。
- `edirectx_PropKetInfo_CDXInput` `:748-753` 固定返回 `FALSE`。
- `edirectx_PropNotifyReceiver_CDXInput` `:755-775` 未填充默认尺寸，返回 `0`。

### 5.6 `edirectx_dllMain.cpp`：宿主边界

`DllMain` 在 `edirectx_dllMain.cpp:7-24` 只对四种 DLL 生命周期消息做空分支并返回 `TRUE`，没有资源初始化或释放。

`g_LibInfo_edirectx_global_var` 在 `:31-87` 声明：

- 格式号 `LIB_FORMAT_VER`；
- GUID `81690053A86045bf9E362F5DE0BC4095`；
- 支持库版本 `2.0.0`；
- 要求易语言系统 `3.9`、系统核心支持库 `3.9`；
- 名称 `DirectX2D支持库`，说明为 DirectX 2D 支持；
- 语言 `__GBK_LANG_VER`，平台 `_LIB_OS(__OS_WIN)`；
- 16 个自定义数据类型、1 个全局命令类别、284 个命令、0 个常量；
- 依赖文件为 `NULL`，AddIn/SuperTemplate 也为 `NULL`。

`GetNewInf()` `:89-95` 对命令索引 65 和 127 修正英文名为 `LoadBitmap`、`DrawText`，避免 Windows 宏带来的 A/W 名称变化，然后返回全局 `LIB_INFO`。静态函数名返回分支 `:97-116` 则将对应符号指向 `LoadBitmapW`、`DrawTextW`。

### 5.7 `elib/fnshare.*`：通用支持库运行时桥接

`elib/fnshare.cpp:7-71` 保存三项静态状态：系统通知函数指针、用户通知函数指针、调试/运行版本值。核心行为：

- `NotifySys` `:11-17` 在系统回调存在时转发消息。
- `isDebugVer` `:18-22` 返回当前版本是否为 `PT_DEBUG_RUN_VER`。
- `ProcessNotifyLib` `:24-64` 接收 `NL_SYS_NOTIFY_FUNCTION`，保存 `PFN_NOTIFY_SYS`，首次通过 `NRS_GET_PRG_TYPE` 查询运行版本，之后把消息转发给用户回调。
- `SetUserSysNotify` `:67-71` 设置用户回调并返回 `ProcessNotifyLib`。

`elib/fnshare.h:25-141` 提供易语言内存/数组格式辅助：`ealloc`、`efree`、`CloneTextData`、`CloneBinData`、`CloneTextDataW`、`GetAryElementInf`、`GetBinData`；`:160-170` 提供 `allocArray`。这些函数依赖宿主系统通知接口，不是 edirectx 自己的持久化层。

## 6. 数据模型与状态

本项目没有业务数据库、配置文件、缓存目录、序列化模型或持久化状态。数据模型全部是易语言支持库 ABI 的静态描述：

- `CMD_INFO`：命令展示和调用契约。
- `ARG_INFO`：参数类型、默认值、引用/数组等标志。
- `LIB_DATA_TYPE_INFO`：对象/枚举数据类型、命令索引、成员、事件和交互接口。
- `LIB_DATA_TYPE_ELEMENT`：复合类型或枚举成员。
- `EVENT_INFO2`/`EVENT_ARG_INFO2`：`CDXInput` 事件契约。
- `LIB_INFO`：支持库版本、GUID、平台、命令和数据类型总入口。
- `MDATA_INF`：运行时传入的参数/返回数据容器，来自 `elib/lib2.h`，命令骨架目前未写回。

句柄成员以 `SDT_INT` 描述并以隐藏字段暴露，例如 `CDXSurface` 的 `SURFACEPOINTER`、`CDXScreen` 的 `SCREENPOINTER`。当前没有创建、保存、释放这些句柄的真实实现。

## 7. API、ABI 与协议边界

### 7.1 动态库公开入口

- `GetNewInf()`：`.def` 唯一导出，返回 `PLIB_INFO`。
- `edirectx_ProcessNotifyLib_edirectx()`：由 `LIB_INFO.m_pfnNotify` 连接易语言系统通知，通常由宿主按函数指针调用。
- `edirectx_<英文名>_<索引>_edirectx()`：通过 `g_cmdInfo_edirectx_global_var_fun` 间接调用；函数名由 `EDIRECTX_NAME` 宏拼接。

### 7.2 易语言宿主通知

支持 `NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、`NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` 等通知分支。当前除系统通知转发和函数名/依赖查询外，大多为空处理或返回默认错误/成功值，见 `edirectx_dllMain.cpp:104-183`。

### 7.3 IDE 组件协议

`CDXInput` 的 `PFN_INTERFACE` 通过 `ITF_*` 编号返回具体回调，调用者是易语言 IDE/运行时而非普通 C++ API 客户端。该协议要求组件创建、属性读取、属性修改、键盘需求和通知尺寸等语义；当前实现只完成接口地址分派，未完成组件状态管理。

## 8. 依赖边界与平台假设

### 已确认依赖

- Windows SDK：`elib/lib2.h:61` 包含 `<windows.h>`；`mtypes.h:4` 包含 `<time.h>`。
- C/C++ 运行库头：`elib/lib2.h:62-63` 包含 `<stdio.h>`、`<math.h>`，`:102` 包含 `<assert.h>`。
- Visual Studio `v141` 工具集和 Windows SDK `10.0.15063.0`，见两个 `.vcxproj` 的 Globals/Configuration 段。
- 易语言支持库 ABI 头文件和宿主通知/内存协议，全部在仓库 `elib/` 中或由 Windows SDK 提供。

### 未发现的依赖

- 源码没有包含 `ddraw.h`、`dinput.h`、`dsound.h`、DirectX SDK 专用头或 DirectX API 调用。
- 工程没有声明额外 `AdditionalDependencies`、第三方静态库或动态库；动态库的依赖文件字段为 `NULL`。
- 仓库没有包管理文件、安装脚本、CMake、Makefile、CI 配置或测试依赖。

因此“DirectX 2D”目前体现在库名、命令/类型元数据和注释上，尚没有从源码证实 DirectDraw/DirectInput/DirectSound 的真实链接或执行路径。

## 9. 测试、验证与发布现状

### 9.1 仓库内验证资产

现场扫描得到 23 个 Git 跟踪文件（不含 `.git` 内部文件），未发现：

- `README`；
- `AGENTS.md`、`CLAUDE.md`；
- `test*`、`测试*` 或测试项目；
- `既有专项文档`；
- `CMakeLists.txt`、`Makefile`、CI 配置、资源脚本或安装脚本。

`edirectx_cmdInfo.cpp:587-589` 仅有 Debug 编译期参数数量辅助变量，不能视为测试套件。

### 9.2 当前取证实际验证

- 只读检查 Git 状态、分支、提交、远程和文件清单。
- 本地提交：`9b8b76cfa8222da38173f32b230b082efebbb144`，提交时间 `2022-12-19T16:04:33+08:00`，提交说明 `初始化仓库`。
- 本地 `master` 与 `origin/master` 指向同一提交；只读 `git ls-remote origin HEAD refs/heads/master` 也返回同一提交。
- 远程：`https://gitee.com/JYtechnology/edirectx.git`。
- 通过只读源码扫描确认命令、参数、数据类型、事件和空实现统计；未执行构建或运行。
- 代码图工具返回项目没有 `.codegraph/` 索引，因此没有代码图调用链证据；不能把代码图不可用误写成源码不存在。
- `system_engineering_toolkit` MCP `http://127.0.0.1:8766/mcp/` 成功完成 MCP 初始化，服务端版本 `1.28.1`；本项目没有被该代码图索引覆盖。

**明确未执行：**Visual Studio/MSBuild 构建、DLL 加载、易语言宿主联调、DirectX 运行验证、静态库消费验证、单元测试/集成测试。原因是当前取证建档约束禁止构建和修改源码，且当前 macOS 环境不是目标 Windows/Visual Studio 环境。

## 10. 风险与未验证项

### 阻断级事实

1. **命令执行未实现。** `edirectx_cmdDef.cpp` 的 284 个命令函数没有 `pRetData` 写回和业务调用；任何依赖实际图形、输入、声音、精灵行为的程序都不能据此判定可运行。
2. **DirectX 后端未出现。** 未发现 DirectX 头文件、API 调用、库链接或运行时对象创建；“DirectX2D支持库”只是元数据/骨架定位。
3. **输入设备组件未实现。** 创建回调返回空句柄，属性和通知回调为 TODO/默认返回，IDE 拖放组件不能据此判定可用。

### 重要风险

1. **x64 工程配置不完整。** 动态库 x64 配置缺少 Win32 使用的 `.fne` 输出扩展名和 `.def` 模块定义文件，需在 Windows/VS 中确认最终导出和文件格式。
2. **32 位指针假设。** `elib/fnshare.h:38` 将指针转换为 `DWORD` 传给 `NotifySys`；`:215` 将 `void*` 转为 `INT` 做索引运算；这些写法在 x64 下存在指针截断风险，不能仅凭工程存在 x64 配置就认为 ABI 已兼容。
3. **静态库路径未闭环验证。** `__E_STATIC_LIB` 会排除动态元数据和 DLL 代码，仓库没有静态宿主/示例来证明 `NL_GET_CMD_FUNC_NAMES`、符号命名和链接行为正确。
4. **源码编码和目标平台耦合。** 中文源码/元数据按 GBK 语义使用，工程是 Windows/Unicode 配置；在非 Windows 环境无法直接复现构建链。
5. **生成式宏的一致性依赖人工维护。** 命令表、命令实现、参数数组、对象索引数组通过索引和宏约定关联，仓库没有自动校验命令索引、参数偏移、函数指针表和数据类型索引的一致性测试。

### 待后续复核

- 在隔离的 Windows + Visual Studio 环境读取最终 `edirectx.fne` 的导出表、依赖表和加载结果。
- 查明该仓库是否为模板/待填充的生成产物，或是否应从其他历史仓库/分支补入真实 DirectX 实现；当前浅克隆只显示一个提交。
- 复核命令表末段的历史兼容命令、重复英文名和 `LoadBitmap`/`DrawText` A/W 修正是否符合目标易语言版本。
- 逐项建立 ABI 契约测试：`LIB_INFO` 版本兼容、284 条命令函数指针顺序、412 条参数偏移、16 个数据类型索引、6 个输入事件和静态库符号查询。
- 若要实现功能，应先确定 DirectX 版本/组件选择（如 DirectDraw、DirectInput、DirectSound 或兼容层）、句柄所有权、错误返回、线程模型、资源释放和 x64 ABI，而不是直接填充当前空函数体。

## 11. 证据基线

| 事实 | 证据 |
|---|---|
| 远程与本地版本 | Git `master`/`origin/master`，提交 `9b8b76cfa8222da38173f32b230b082efebbb144` |
| 工程和目标 | `edirectx.sln:5-38`、`edirectx.vcxproj:43-198`、`edirectx_static/edirectx_static.vcxproj:40-163` |
| 动态导出 | `Source_edirectx.def:1-4` |
| 总头与命令声明 | `include_edirectx_header.h:3-24` |
| 单一命令表 | `edirectx_cmd_typedef.h:3-297` |
| 参数和命令元数据 | `edirectx_cmdInfo.cpp:4-602` |
| 命令执行骨架 | `edirectx_cmdDef.cpp:1-2769` |
| 数据类型/事件/组件接口 | `edirectx_dtType.cpp:3-778` |
| 库信息/入口/通知 | `edirectx_dllMain.cpp:5-184` |
| 常量数组为空 | `edirectx_const.cpp:12-16` |
| ABI 基础结构和 Windows 依赖 | `elib/lib2.h:1-63`、`elib/mtypes.h:1-176` |
| 内存/通知桥接 | `elib/fnshare.h:20-240`、`elib/fnshare.cpp:7-71` |
| IDE 类型/事件常量 | `elib/PublicIDEFunctions.h:31-127`、`:529-577` |

本文件是 `edirectx` 项目根唯一架构建档文档；当前取证没有创建或修改其他项目文档，也没有删除既有细探材料文件（现场未发现既有细探材料）。

## 10. 小型仓规模说明与边界

`edirectx` 只有 23 个跟踪文件，实际源码集中在支持库元数据和宿主桥接层，未发现 DirectX 调用实现、示例或测试。文件职责如下：

- `edirectx_cmdDef.cpp` 与 `edirectx_cmdInfo.cpp`：命令表、名称、参数描述及处理器地址。
- `edirectx_cmd_typedef.h`：函数指针、参数结构和返回约定；这是 ABI 检查的起点。
- `edirectx_dtType.cpp`：数据类型及属性/事件元数据注册。
- `edirectx_const.cpp`：常量表；当前为空表不能证明 DirectX 常量可用。
- `edirectx_dllMain.cpp`：`GetNewInf`、库信息、通知回调及宿主生命周期入口。
- `include_edirectx_header.h`：公共声明聚合，供动态和静态工程复用。
- `Source_edirectx.def`：导出符号清单，必须与链接产物逐项核对。
- `edirectx.vcxproj` / `edirectx_static/...vcxproj`：动态 DLL 与静态库的配置边界。
- `elib/*`：易语言运行库的内存、类型、通知和 ABI 定义。

没有仓内测试、资源包、第三方锁定文件或 DirectX 样例。未在 Windows/MSVC 下编译、装载或调用 DLL，未验证设备创建、错误码、资源释放、线程模型与 x86/x64 兼容性；这些均是使用前必须补充的环境证据。
