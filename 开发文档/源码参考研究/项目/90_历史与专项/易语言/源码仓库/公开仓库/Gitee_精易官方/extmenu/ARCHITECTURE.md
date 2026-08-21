# extmenu 架构建档

> 本文件是 `extmenu` 项目的唯一架构建档。首轮建档仅新增本文件；未修改源码、工程文件、依赖文件或 Git 历史，未构建、未运行支持库。

## 1. 项目定位

`extmenu` 是一个面向 Windows 的易语言支持库工程，库中文名为“超级菜单支持库”，目标是在易语言 IDE/运行时中注册一个名为 `SupperMenu` 的菜单组件，并提供菜单相关命令、属性、事件和组件交互回调。

当前仓库更接近“易语言支持库模板/接口骨架”，而不是已完成的超级菜单实现：

- 支持库元信息、命令元数据、组件类型元数据和 DLL 通知入口已经搭建；
- 3 个命令实现函数均只有参数取值或空函数体，没有实际菜单操作和返回值写入；
- 组件创建、属性持久化、属性修改、定制属性对话框和运行时属性读取均未完成；
- 没有业务源码之外的测试、示例、README 或部署说明；
- 架构事实以当前源码和工程文件为准，注释中的模板说明不视为已实现能力。

## 2. 版本与仓库基线

| 项目 | 事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/extmenu` |
| Git 分支 | `master` |
| 本地提交 | `70622fb04d39c833a9fe5dc933de99920455c852` |
| 提交主题 | `初始化仓库` |
| 提交时间 | `2022-12-19T16:08:51+08:00` |
| 作者 | `精易科技` |
| 远程仓库 | `https://gitee.com/JYtechnology/extmenu.git` |
| 远程 `HEAD` | `70622fb04d39c833a9fe5dc933de99920455c852` |
| 远程默认分支 | `master` |
| 建档时工作树 | 干净；建档前无已跟踪或未跟踪源码变更 |
| 历史范围 | 当前仓库为 shallow/grafted 单提交视图，不能据此推断更早历史 |

远程 `HEAD` 与本地 `HEAD` 一致，因此当前核对没有执行 `fetch`、`pull` 或任何远程写操作。

## 3. 运行与构建形态

项目由一个 Visual Studio solution 和两个 C++ project 组成：

- `extmenu.sln`：Visual Studio 17 solution，定义 `extmenu` 与 `extmenu_static` 两个项目；
- `extmenu.vcxproj`：动态库目标，`ConfigurationType=DynamicLibrary`；Win32 目标扩展名为 `.fne`；
- `extmenu_static/extmenu_static.vcxproj`：静态库目标，`ConfigurationType=StaticLibrary`；
- 两个项目共用上层源码和 `elib/` 头文件/实现，通过 `__E_STATIC_LIB` 区分动态库和静态库路径。

solution 将 `x86` 映射为工程的 `Win32` 配置，将 `x64` 映射为工程的 `x64` 配置。工程要求：

- Windows 目标平台版本：`10.0.15063.0`；
- Platform Toolset：`v141`；
- 字符集：`Unicode`；
- 动态库/静态库均提供 Debug、Release 和 Win32/x64 配置；
- 依赖 Visual Studio C++ 工具链、Windows API 头文件与易语言支持库 ABI 头文件。

### 3.1 工程配置风险

以下是静态检查发现的配置风险，未通过实际 MSBuild 验证：

1. `elib/lib2.h` 明确要求包含前定义 `__E_FNENAME`。动态库工程的 Win32 配置和静态库工程的 Win32 配置定义了 `__E_FNENAME=extmenu`，但两个工程的 x64 配置没有该定义；如果没有外部属性表补充，x64 编译可能在宏展开处失败。
2. `extmenu.vcxproj` 的 x64 Link 配置没有 `ModuleDefinitionFile=Source_extmenu.def`，而 Win32 配置有该项；因此 x64 动态库是否导出 `GetNewInf` 未确认，存在 DLL 装载入口不可见的风险。
3. `extmenu_static.vcxproj` 的 x64 配置使用 `PrecompiledHeader=Use` 和 `PrecompiledHeaderFile=pch.h`，仓库内没有 `pch.h`；该配置可能无法直接构建。
4. 当前仓库没有 CI、构建脚本、发布脚本或产物目录定义，无法从仓库内确认 `.fne`/静态库的最终投放路径。

## 4. 目录与文件地图

```text
extmenu/
├── ARCHITECTURE.md                    # 当前核对新增；唯一架构建档
├── extmenu.sln                        # Visual Studio solution
├── extmenu.vcxproj                    # 动态库工程
├── extmenu.vcxproj.filters            # 动态库工程筛选器
├── extmenu.vcxproj.user               # 动态库用户工程设置，基本为空
├── extmenu_static/
│   ├── extmenu_static.vcxproj         # 静态库工程
│   ├── extmenu_static.vcxproj.filters # 静态库工程筛选器
│   └── extmenu_static.vcxproj.user    # 静态库用户工程设置，基本为空
├── Source_extmenu.def                 # DLL 导出定义，仅声明 GetNewInf
├── include_extmenu_header.h           # 项目公共头，汇总 ABI、命令声明和全局元数据声明
├── extmenu_cmd_typedef.h              # 命令单一事实宏 EXTMENU_DEF 与符号拼接宏
├── extmenu_cmdDef.cpp                 # 3 个命令执行函数骨架
├── extmenu_cmdInfo.cpp                # 参数元数据和命令元数据数组
├── extmenu_const.cpp                  # 常量表，当前数量为 0
├── extmenu_dtType.cpp                 # SupperMenu 数据类型、属性、事件、组件接口回调
├── extmenu_dllMain.cpp                # DllMain、LIB_INFO、GetNewInf、通知入口
└── elib/
    ├── lib2.h                         # 易语言支持库核心 ABI 类型、回调、通知和 LIB_INFO
    ├── fnshare.h / fnshare.cpp        # 通知系统、内存、调试版本和用户通知转发封装
    ├── krnllib.h                      # 系统核心支持库类型编号和版本常量
    ├── lang.h                         # 语言版本常量；本库为 GBK
    ├── mtypes.h                       # 跨编译环境基础类型及 Windows 句柄别名
    ├── untshare.h                     # 组件通用辅助模板/函数，当前工程未直接 include
    └── PublicIDEFunctions.h           # 易语言 IDE 公共功能定义，当前工程仅列入工程文件
```

仓库实际包含 23 个 Git 跟踪文件（本文件加入后工作树会多出 1 个架构文档）。初始提交统计为 4,401 行新增；按现场对 23 个文件进行 GB18030 解码后的统计约为 4,260 行、184.6 KiB，其中 `elib/lib2.h` 是最大的 ABI 参考头。

## 5. 总体流程

```text
易语言 IDE/运行时
        │
        │ LoadLibrary / 绑定支持库 ABI
        ▼
动态库 extmenu*.fne
        │
        ├─ 导出 GetNewInf
        │       │
        │       └─ 返回 g_LibInfo_extmenu_global_var
        │              ├─ LIB_INFO：GUID、版本、系统要求、Windows 平台
        │              ├─ g_cmdInfo：3 个命令的名称/参数/返回类型
        │              ├─ g_cmdInfo_*_fun：3 个命令函数指针
        │              ├─ g_DataType：SupperMenu 组件类型
        │              └─ g_ConstInfo：当前为空
        │
        ├─ 支持库通知 extmenu_ProcessNotifyLib_extmenu
        │       ├─ NL_SYS_NOTIFY_FUNCTION → ProcessNotifyLib → fnshare 保存系统通知函数
        │       ├─ NL_GET_CMD_FUNC_NAMES → 返回静态编译所需命令函数名数组
        │       ├─ NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知入口名称
        │       ├─ NL_GET_DEPENDENT_LIBS → 返回空依赖列表
        │       ├─ NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE / NR_DELAY_FREE → 当前无动作
        │       ├─ NL_IDE_READY / NL_RIGHT_POPUP_MENU_SHOW / NL_ADD_NEW_ELEMENT → 当前无动作
        │       └─ 未识别通知 → NR_ERR
        │
        └─ SupperMenu 组件元数据
                │
                ├─ IDE 注册 8 个固定属性 + 16 个自定义属性
                ├─ IDE 注册 2 个事件：被点燃、被关闭
                ├─ IDE 注册 3 个成员命令索引：0、1、2
                └─ 通过 extmenu_GetInterface_SupperMenu 分发组件回调
                        ├─ 创建组件 → extmenu_ControlCreate_SupperMenu
                        ├─ 属性 UI 可编辑性 → extmenu_PropUpDate_SupperMenu
                        ├─ 定制属性对话框 → extmenu_PropPopDlg_SupperMenu
                        ├─ 属性变更 → extmenu_PropChanged_SupperMenu
                        ├─ 全部属性读取 → extmenu_PropGetDataAll_SupperMenu
                        ├─ 单项属性读取 → extmenu_PropGetData_SupperMenu
                        ├─ 按键拦截询问 → extmenu_PropKetInfo_SupperMenu
                        └─ 附加通知 → extmenu_PropNotifyReceiver_SupperMenu
```

## 6. ABI 与依赖边界

### 6.1 项目公共头

`include_extmenu_header.h` 的职责是：

- include `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`；
- include `extmenu_cmd_typedef.h`；
- 为动态库模式声明命令表、参数表、数据类型表和函数指针表；
- 通过 `EXTMENU_DEF_CMD` 展开 `EXTMENU_DEF`，生成 3 个命令执行函数的 `extern "C"` 声明。

`extmenu_cmd_typedef.h` 中的 `EXTMENU_NAME`/`EXTMENU_NAME_STR` 将 `__E_FNENAME`、命令英文名和序号拼成稳定符号，例如 `extmenu_SetPic_0_extmenu`。`EXTMENU_DEF(_MAKE)` 是命令元数据的单一事实源，当前包含：

| 序号 | 中文命令 | 英文名 | 返回类型 | 参数数 | 组件归属 |
|---:|---|---|---:|---:|---|
| 0 | `置菜单项图片` | `SetPic` | `_SDT_NULL` | 2 | `SupperMenu` |
| 1 | `置侧条图片` | `SetBandPic` | `_SDT_NULL` | 3 | `SupperMenu` |
| 2 | `取子菜单` | `GetChildrenMenu` | `DTP_MENU` 数组 | 1 | `SupperMenu` |

### 6.2 外部依赖

项目没有第三方包管理文件。源码依赖边界为：

- Microsoft Visual C++/Windows SDK：工程、`windows.h`、Win32 句柄和 API 类型；
- 易语言支持库 ABI：`elib/lib2.h`、`elib/krnllib.h`、`elib/lang.h` 等随源码仓库携带的头文件；
- C/C++ 运行库：`memset`、`memcpy`、`lstrlenA` 等基础函数；
- 易语言宿主运行时：通过 `PFN_NOTIFY_SYS` 和 `ProcessNotifyLib` 提供通知、内存和版本查询能力；
- 当前没有发现网络、数据库、文件系统、注册表或第三方图形库依赖。

`elib/untshare.h` 含 Windows 窗口、字体和样式辅助函数，但当前 6 个 C++ 源文件没有直接 include 它；`elib/PublicIDEFunctions.h` 也只是工程列入的接口资料，当前项目源码没有直接 include。

## 7. 支持库注册与加载链

### 7.1 动态库入口

`Source_extmenu.def` 使用 DLL `.def` 文件声明：

```text
LIBRARY

EXPORTS
    GetNewInf
```

`extmenu_dllMain.cpp` 的 `GetNewInf()` 返回静态 `g_LibInfo_extmenu_global_var` 地址。该 `LIB_INFO` 的关键字段如下：

| 字段 | 当前值/含义 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（来自 `elib/lib2.h`，值为 `20000101`） |
| `m_szGuid` | `9909FBB013704cfa8FE7E739DB7172DE` |
| 版本 | 主版本 `2`、次版本 `0`、构建号 `0` |
| 易语言系统要求 | 主 `4`、次 `0` |
| 核心支持库要求 | 主 `4`、次 `3` |
| 名称 | `超级菜单支持库` |
| 语言 | `__GBK_LANG_VER`（值 `1`） |
| 平台 | `_LIB_OS(__OS_WIN)`，仅 Windows |
| 命令数量 | `g_cmdInfo_extmenu_global_var_count`，当前为 3 |
| 自定义数据类型数量 | `g_DataType_extmenu_global_var_count`，当前为 1 |
| 常量数量 | `g_ConstInfo_extmenu_global_var_count`，当前为 0 |
| 依赖支持文件 | `NULL` |
| 通知回调 | `extmenu_ProcessNotifyLib_extmenu` |
| AddIn/SuperTemplate | 均为 `NULL` |

### 7.2 静态库入口配合

`__E_STATIC_LIB` 开启后，`extmenu_dllMain.cpp` 中动态库 `DllMain`、`LIB_INFO` 和动态库元数据部分被排除，但 `extmenu_ProcessNotifyLib_extmenu` 保留，并为静态编译返回：

- `NL_GET_CMD_FUNC_NAMES`：`g_cmdNamesextmenu`，由同一 `EXTMENU_DEF` 展开；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：`"extmenu_ProcessNotifyLib_extmenu"`；
- `NL_GET_DEPENDENT_LIBS`：空字符串列表 `"\0\0"`。

这保证静态库可以让宿主通过命令函数名和通知函数名继续绑定。静态工程直接编译上层 5 个 `extmenu_*.cpp` 和 `elib/fnshare.cpp`，没有单独的静态实现源。

## 8. 命令元数据与执行链

### 8.1 参数契约

`extmenu_cmdInfo.cpp` 中的 `g_argumentInfo_extmenu_global_var` 有 6 个参数描述，与 `EXTMENU_DEF` 的参数起始偏移对应：

| 参数索引 | 归属命令 | 名称 | 类型 | 备注 |
|---:|---|---|---|---|
| 0 | `置菜单项图片` | `欲置图标的菜单项` | `DTP_MENU` | 当前注释说明不支持顶级菜单图片 |
| 1 | `置菜单项图片` | `图片索引` | `SDT_INT` | `-1` 表示没有图片 |
| 2 | `置侧条图片` | `父菜单项` | `DTP_MENU` | 无子菜单时命令无效 |
| 3 | `置侧条图片` | `图片数据` | `SDT_BIN` | 支持图片数据/资源，空字节集表示删除 |
| 4 | `置侧条图片` | `图片高度自适应` | `SDT_BOOL` | 可空，`AS_DEFAULT_VALUE_IS_EMPTY` |
| 5 | `取子菜单` | `父菜单` | `DTP_MENU` | 可空；省略代表所有顶级菜单 |

`g_cmdInfo_extmenu_global_var` 通过再次展开 `EXTMENU_DEF(EXTMENU_DEF_CMDINFO)` 生成命令描述；函数指针表在 `extmenu_dllMain.cpp` 中通过 `EXTMENU_DEF(EXTMENU_DEF_CMD_PTR)` 生成。因此命令顺序、命令名和实现函数数组依赖同一个宏列表，修改命令时必须同步检查该宏及参数偏移。

### 8.2 当前执行实现

`extmenu_cmdDef.cpp` 中的 3 个导出命令函数均为骨架：

- `extmenu_SetPic_0_extmenu`：读取 `pArgInf[1].m_pCompoundData` 和 `pArgInf[2].m_int`，不访问菜单、不修改图片、不设置 `pRetData`；
- `extmenu_SetBandPic_1_extmenu`：读取菜单、字节集和布尔参数，未执行任何侧条图片逻辑；
- `extmenu_GetChildrenMenu_2_extmenu`：读取可选父菜单参数，未创建或填充返回数组。

因此“命令已注册”不能等价为“命令可用”。当前真实可确认的是元数据和函数地址存在，实际菜单行为、返回数组生命周期、参数合法性和宿主通知均未实现/未验证。

## 9. SupperMenu 组件模型

### 9.1 类型注册

`extmenu_dtType.cpp` 定义一个 `LIB_DATA_TYPE_INFO`：

| 字段 | 值 |
|---|---|
| 中文名 | `超级菜单` |
| 英文名 | `SupperMenu` |
| 说明 | `该组件实现了对菜单的美化和增强` |
| 成员命令索引 | `0, 1, 2` |
| 平台标志 | `_DT_OS(__OS_WIN) \| LDT_WIN_UNIT \| LDT_IS_FUNCTION_PROVIDER` |
| 事件 | 2 个 |
| 属性 | 24 个（8 个固定 + 16 个自定义） |
| 交互入口 | `extmenu_GetInterface_SupperMenu` |
| 枚举/成员字段 | `NULL` |

`LDT_WIN_UNIT` 表明它被描述为窗口/菜单组件；`LDT_IS_FUNCTION_PROVIDER` 表明该数据类型提供成员命令。

### 9.2 属性

固定属性 8 个：`左边`、`顶边`、`宽度`、`高度`、`标记`、`可视`、`禁止`、`鼠标指针`。

自定义属性 16 个：

1. `配色方案` / `ColorScheme`：`UD_PICK_INT`，选项为“自定义、蓝色、灰色、雅绿、粉红、青春、古朴”；
2. `底色` / `MenuBkColor`：`UD_COLOR`；
3. `文本颜色` / `TextColor`：`UD_COLOR`；
4. `禁止文本颜色` / `DisableTextColor`：`UD_COLOR`；
5. `点燃颜色` / `FocusColor`：`UD_COLOR`；
6. `渐变条颜色1` / `GradBarColor1`：`UD_COLOR`；
7. `渐变条颜色2` / `GradBarColor2`：`UD_COLOR`；
8. `菜单条点燃颜色1` / `BarFocusColor1`：`UD_COLOR`；
9. `菜单条点燃颜色2` / `BarFocusColor2`：`UD_COLOR`；
10. `点燃区边框颜色` / `FocusBorderColor`：`UD_COLOR`；
11. `分割条颜色` / `SeparatorColor`：`UD_COLOR`，带 `UW_GROUP_LINE`；
12. `菜单项图片组` / `ImageList`：`UD_IMAGE_LIST`；
13. `菜单项图片索引` / `ImgIndex`：`UD_CUSTOMIZE`；
14. `菜单条背景色` / `MenuBarBkColor`：`UD_COLOR_BACK`；
15. `菜单条底图` / `MenuBarBkPic`：`UD_COLOR_BACK`，带 `UW_IS_HIDED`；
16. `菜单项字体` / `MenuItemFont`：`UD_FONT`。

属性数组只定义了元数据。真正的属性存储必须由 `extmenu_PropGetDataAll_SupperMenu`、`extmenu_PropGetData_SupperMenu`、`extmenu_PropChanged_SupperMenu` 和创建回调共同完成，但这些函数当前没有完成持久化或窗口对象绑定。

### 9.3 事件

当前注册：

| 事件 | 参数 | 返回类型 | 说明 |
|---|---|---|---|
| `被点燃` | `被点燃的菜单项`，`DTP_MENU` | `_SDT_NULL` | 菜单项被高亮时触发 |
| `被关闭` | 无 | `_SDT_NULL` | 所有弹出菜单关闭时触发 |

事件参数数组 `s_eventArgInfo_extmenu_SupperMenu` 只显式初始化了 1 项，但第二个无参数事件使用 `s_eventArgInfo_extmenu_SupperMenu + 1`。这看起来可能是 ABI 允许的无参数占位写法，也可能是越界指针风险；当前未在易语言宿主中验证，应在后续深挖/真实运行时确认。

## 10. 组件接口分发与当前行为

`extmenu_GetInterface_SupperMenu(INT nInterfaceNO)` 按 `ITF_*` 编号返回函数指针：

| 接口 | 返回函数 | 当前实现状态 |
|---|---|---|
| `ITF_CREATE_UNIT` | `extmenu_ControlCreate_SupperMenu` | 返回 `0`，未创建窗口/菜单对象 |
| `ITF_PROPERTY_UPDATE_UI` | `extmenu_PropUpDate_SupperMenu` | 无条件返回 `TRUE` |
| `ITF_DLG_INIT_CUSTOMIZE_DATA` | `extmenu_PropPopDlg_SupperMenu` | 将 `*pblModified` 设为 `false`，返回 `FALSE`，未弹对话框 |
| `ITF_NOTIFY_PROPERTY_CHANGED` | `extmenu_PropChanged_SupperMenu` | 仅有空的 `case 0`，最终返回 `false` |
| `ITF_GET_ALL_PROPERTY_DATA` | `extmenu_PropGetDataAll_SupperMenu` | 返回 `0` |
| `ITF_GET_PROPERTY_DATA` | `extmenu_PropGetData_SupperMenu` | 属性 0 不填值却返回 `true`，其他索引返回 `false` |
| `ITF_GET_ICON_PROPERTY_DATA` | 无 | 返回 `NULL` |
| `ITF_IS_NEED_THIS_KEY` | `extmenu_PropKetInfo_SupperMenu` | 返回 `FALSE` |
| `ITF_LANG_CNV` | 无 | 返回 `NULL` |
| `ITF_MSG_FILTER` | 无 | 返回 `NULL` |
| `ITF_GET_NOTIFY_RECEIVER` | `extmenu_PropNotifyReceiver_SupperMenu` | 仅识别 `NU_GET_CREATE_SIZE_IN_DESIGNER`，默认返回 0，实际尺寸未设置 |

接口分发本身是清晰的，但回调只提供模板返回值，不能支撑可运行组件。

## 11. 系统通知与生命周期

`extmenu_ProcessNotifyLib_extmenu` 是支持库到宿主的通知入口：

1. 宿主发送 `NL_SYS_NOTIFY_FUNCTION`，函数调用 `ProcessNotifyLib`；
2. `ProcessNotifyLib` 在 `fnshare.cpp` 中保存 `PFN_NOTIFY_SYS`，并首次通过 `NRS_GET_PRG_TYPE` 查询调试/运行版本；
3. 后续 `NotifySys` 将消息转发给宿主保存的函数；
4. `SetUserSysNotify` 可保存用户通知函数，并由 `ProcessNotifyLib` 在自身处理后转发；
5. 释放、IDE 就绪、IDE 右键菜单和新增成员通知当前没有业务处理；
6. 未识别通知统一返回 `NR_ERR`。

`fnshare.cpp` 使用静态变量 `s_pfnNotifySys`、`s_pfnuserNotifySys` 和 `s_isDebug` 保存进程级状态。当前没有资源清理逻辑，也没有组件实例表、窗口句柄表、菜单句柄表或事件派发实现。

## 12. 数据模型与状态所有权

当前没有数据库、配置文件、序列化协议或持久化存储。已存在的“数据模型”全部是宿主 ABI 元数据和回调参数：

- `LIB_INFO`：支持库注册信息；静态对象位于 `extmenu_dllMain.cpp`；
- `CMD_INFO`、`ARG_INFO`：命令/参数描述表；
- `LIB_DATA_TYPE_INFO`、`UNIT_PROPERTY`、`EVENT_INFO2`、`EVENT_ARG_INFO2`：组件类型描述表；
- `HUNIT`：宿主组件句柄，当前没有内部对象与之对应；
- `UNIT_PROPERTY_VALUE`、`HGLOBAL`：属性数据交互载体，当前没有序列化实现；
- `MDATA_INF`：命令参数和返回值载体，命令函数目前未写返回状态；
- `EVENT_NOTIFY2`：事件通知 ABI，当前源码没有实际抛事件路径。

因此当前状态所有权仍在易语言宿主；`extmenu` 只暴露空壳回调。若后续实现真实菜单组件，应明确：组件实例由谁创建/销毁、菜单句柄与 `HUNIT` 如何绑定、属性数据的序列化格式、设计时与运行时属性读取差异、事件参数内存释放责任，以及宿主销毁通知到达后的资源回收顺序。

## 13. 关键调用链

### 13.1 支持库装载

```text
易语言宿主
  → LoadLibrary(extmenu*.fne)
  → 解析 Source_extmenu.def 中的 GetNewInf
  → GetNewInf()
  → g_LibInfo_extmenu_global_var
  → 注册 3 个命令、1 个 SupperMenu 数据类型、0 个常量
  → 记录 extmenu_ProcessNotifyLib_extmenu
```

### 13.2 命令调用

```text
易语言程序调用“超级菜单.命令”
  → 宿主按 g_cmdInfo 中的命令索引组织 PMDATA_INF 参数
  → 通过 g_cmdInfo_extmenu_global_var_fun[index] 调用函数
  → extmenu_SetPic_0_extmenu / extmenu_SetBandPic_1_extmenu /
     extmenu_GetChildrenMenu_2_extmenu
  → 当前只读取参数，不改变菜单，不写 pRetData
  → 实际返回值/副作用未实现
```

### 13.3 组件创建与属性交互

```text
IDE 选择“超级菜单”并放置到窗体
  → 查找 LIB_DATA_TYPE_INFO::m_pfnGetInterface
  → extmenu_GetInterface_SupperMenu(ITF_CREATE_UNIT)
  → extmenu_ControlCreate_SupperMenu(...)
  → 当前返回 HUNIT=0

IDE/运行时读取或修改属性
  → extmenu_GetInterface_SupperMenu(ITF_*)
  → 属性回调
  → 当前没有完整的属性数据序列化、校验、更新或实时读取
```

## 14. 质量、测试与验证现状

### 14.1 仓库内现状

- 没有测试目录；
- 没有单元测试、集成测试、宿主模拟器或 ABI 探针；
- 没有 CI 配置；
- 没有 README 或开发/构建文档；
- 没有示例易语言工程；
- 没有已提交二进制产物；
- 只有 `extmenu_cmdInfo.cpp` 的 `_DEBUG` 参数数量辅助常量 `dbg_cmd_arg_count__`，不是完整测试。

### 14.2 当前核对实际执行

当前核对只做只读盘点和文档写入：

- 已读取项目文件清单、C++ 源码、公共 ABI 头、工程 XML、solution、`.def`、Git 状态和远程引用；
- 已执行 `git ls-remote origin HEAD refs/heads/master`，远程 HEAD 与本地一致；
- 已检查目标目录及其仓库父目录，没有发现 `*细探*.md`；
- 已尝试按要求调用 `codegraph_explore`，但目标仓库没有 `.codegraph/` 索引，工具明确返回不可查询；没有再次调用代码图谱工具；
- `project_context` 返回的是当前默认项目 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是本目标仓库，因此其 V3 代码地图不作为本项目证据；本项目事实均来自目标绝对路径的现场读取；
- 未执行构建、链接、运行、DLL 加载、易语言宿主验证或任何源码测试。

## 15. 风险与未验证项

### 15.1 高风险/阻断性缺口

1. **组件创建未实现**：`extmenu_ControlCreate_SupperMenu` 固定返回 0，无法证明拖放后存在可用组件。
2. **命令无实际功能**：3 个命令函数均未调用 Win32 菜单 API、未操作句柄、未写入返回数据。
3. **属性状态未实现**：全部属性读取/修改/序列化回调为空或模板返回，设计时数据不能可靠保存，运行时数据也不能可靠反映。
4. **事件未触发**：虽注册了 `被点燃`、`被关闭`，源码中没有菜单消息钩子、事件构造或宿主事件通知调用。
5. **资源生命周期缺失**：没有窗口、菜单、图片、字体、图片组和自定义数据的创建/销毁表，也没有处理 `NL_FREE_LIB_DATA` 的释放逻辑。
6. **x64 工程配置可能无法直接编译/导出**：缺少 `__E_FNENAME`、动态 x64 缺少 `.def` 链接配置、静态 x64 引用了仓库不存在的 `pch.h`；需在 Windows + VS 环境实际验证。

### 15.2 重要风险

1. `s_eventArgInfo_extmenu_SupperMenu + 1` 作为无参数事件的参数指针超出显式数组边界，需结合宿主 ABI 确认是否允许。
2. `extmenu_PropPopDlg_SupperMenu` 无条件解引用 `pblModified`；虽然接口注释期望非空，但未做防御，宿主传空指针时会崩溃。
3. `extmenu_PropGetData_SupperMenu` 对属性索引 0 返回成功但不写 `pPropertyVaule`，会产生未初始化/旧数据语义。
4. `extmenu_PropChanged_SupperMenu` 没有对 `pPropertyVaule` 做类型和范围校验，属性变更不会落到内部状态。
5. 命令实现直接按固定参数下标读取，没有检查 `nArgCount`、数据类型、空句柄或数组标志。
6. `g_cmdInfo`、函数指针数组、参数偏移和组件成员命令索引全部依赖宏展开顺序；增删命令时若只改一处，会形成 ABI 索引错位。
7. 工程使用 GBK 源码/字符串与 Unicode 工程设置并存，实际编译器编码和宿主字符串 ABI 未验证。

### 15.3 未验证项

- Windows SDK/Visual Studio v141 实际构建结果；
- Win32 Debug/Release、x64 Debug/Release 的编译结果；
- DLL 是否成功导出并被易语言加载；
- `GetNewInf` 返回结构在真实宿主中的注册结果；
- 静态库命令名数组与宿主静态编译器的绑定结果；
- `DTP_MENU`、`HUNIT`、`MDATA_INF`、属性数据和图片组的真实内存/生命周期语义；
- `SupperMenu` 命名是否为历史兼容要求，还是应为 `SuperMenu`；
- 2 个事件的参数数组边界问题；
- 命令返回数组的正确分配、填充和释放方式；
- 设计时与运行时创建回调参数在不同易语言版本中的兼容性；
- 任何真实菜单绘制、皮肤、图片、字体、颜色、分割条和子菜单行为。

## 16. 后续深挖建议

后续如进入实现或二轮研究，建议保持以下顺序，不要先在空壳回调上堆业务代码：

1. 从同一易语言版本的已完成 Windows 菜单/窗口支持库中确认 `HUNIT`、属性序列化、事件抛送和资源释放 ABI；
2. 在 Windows + VS v141 环境先修复并验证 x64 工程宏、`.def` 导出和预编译头配置；
3. 设计 `HUNIT` 到内部实例对象的所有权表，明确 `NL_FREE_LIB_DATA`、宿主销毁通知和异常路径；
4. 先实现组件创建/销毁与固定属性往返，再实现自定义属性序列化；
5. 为每个命令定义输入校验、菜单句柄来源、错误语义和 `pRetData` 生命周期；
6. 接入菜单消息/高亮/关闭事件，再验证事件参数内存和 `DTP_MENU` 句柄有效期；
7. 增加最小宿主模拟测试或 Windows 集成测试，至少覆盖加载、元数据计数、属性往返、命令调用、事件触发和资源释放；
8. 所有实现完成并由真实宿主验证后，再更新本文件的“当前状态”和风险项。

## 17. 证据路径索引

| 结论 | 证据 |
|---|---|
| 项目定位、版本和 GUID | `extmenu_dllMain.cpp:31-87` |
| DLL 入口 | `Source_extmenu.def:1-4`、`extmenu_dllMain.cpp:89-92` |
| 通知分发 | `extmenu_dllMain.cpp:101-178` |
| 命令统一定义 | `extmenu_cmd_typedef.h:3-16` |
| 命令实现骨架 | `extmenu_cmdDef.cpp:1-32` |
| 参数元数据 | `extmenu_cmdInfo.cpp:3-47` |
| 组件、属性、事件元数据 | `extmenu_dtType.cpp:43-124` |
| 组件接口分发 | `extmenu_dtType.cpp:126-190` |
| 组件回调当前空实现 | `extmenu_dtType.cpp:192-305` |
| 宿主通知转发 | `elib/fnshare.cpp:7-71` |
| ABI 类型、组件接口和回调 | `elib/lib2.h:494-729`、`elib/lib2.h:1152-1239`、`elib/lib2.h:1246-1318` |
| 工程源文件与构建类型 | `extmenu.vcxproj:21-41`、`extmenu.vcxproj:51-75`、`extmenu_static/extmenu_static.vcxproj:21-45`、`extmenu_static/extmenu_static.vcxproj:48-72` |
| x64 配置差异 | `extmenu.vcxproj:159-198`、`extmenu_static/extmenu_static.vcxproj:130-163` |
| solution 配置映射 | `extmenu.sln:1-40` |
| 远程与提交基线 | Git `remote -v`、`git log -1`、`git ls-remote origin HEAD refs/heads/master` |

> 旧 `细探-*.md` 未发现。本文件已吸收当前核对源码盘点结果；后续只维护本文件，不建立同项目平行架构报告。
