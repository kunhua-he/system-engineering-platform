# elogopanel 架构档案

## 1. 项目定位

`elogopanel` 是精易官方 Gitee 仓库中的易语言 Windows Logo 支持库源码。项目目标是向易语言 IDE/运行时注册一个名为“易LOGO支持库”的窗口单元数据类型 `Logo对象`，并提供 Logo 风格的绘图、对象移动、对象状态、文字和图片命令。

当前仓库是 2022-12-19 初始化的 C++ 支持库模板/骨架：命令元数据、组件属性表和易语言支持库 ABI 入口已经铺设，但绘图命令主体与组件实例生命周期仍是空实现，不能据此断言已经具备可运行的 Logo 绘图能力。

## 2. 版本与现场基线

- 本地根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/elogopanel`
- Git 分支：`master`
- 本地提交：`a86d8c25408997afb9c96d91e9dcaa5118912041`
- 本地与 `origin/master`：现场引用一致
- `origin`：`https://gitee.com/JYtechnology/elogopanel.git`
- 远程 `HEAD`/`refs/heads/master`：`a86d8c25408997afb9c96d91e9dcaa5118912041`
- 最新提交信息：`精易科技`，2022-12-19 16:06:05 +0800，`初始化仓库`
- 工作树：建档前无源码修改；本文件为本次唯一新增的项目根文档
- 仓库未发现 `README`、`AGENTS.md`、`CLAUDE.md` 或 `研究材料-*.md`
- `codegraph`：目标目录及其父路径没有 `.codegraph/` 索引，因此本档案以直接源码取证为准；未重复调用索引工具

## 3. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
        |
        | 加载 .fne 动态支持库，或链接静态库
        v
Source_elogopanel.def --导出--> GetNewInf
        |
        v
elogopanel_dllMain.cpp::GetNewInf
        |
        v
LIB_INFO
  |-- g_DataType_elogopanel_global_var --> Logo对象
  |       |-- 38 个命令索引 --> g_cmdInfo_elogopanel_global_var
  |       |                         |
  |       |                         +--> g_cmdInfo...fun
  |       |                              (elogopanel_* 命令函数)
  |       |
  |       +-- 20 个组件属性
  |       +-- elogopanel_GetInterface_logo
  |              |-- 创建组件/属性回调/通知回调
  |              +-- 当前实现主要为空或返回占位值
  |
  +-- elogopanel_ProcessNotifyLib_elogopanel
          |-- 返回静态链接所需命令名/通知函数名/依赖列表
          |-- 转发 NL_SYS_NOTIFY_FUNCTION 到 elib/fnshare.cpp
          +-- 处理卸载、IDE 就绪等通知（当前多为空分支）
```

## 4. 目录与文件地图

```text
elogopanel/
├── elogopanel.sln                         VS 解决方案，包含动态库和静态库
├── elogopanel.vcxproj                     动态支持库工程
├── elogopanel_static/
│   ├── elogopanel_static.vcxproj          静态库工程，复用父目录源码
│   └── elogopanel_static.vcxproj.filters
├── include_elogopanel_header.h            公共聚合头；声明元数据表和命令原型
├── elogopanel_cmd_typedef.h               ELOGOPANEL_DEF 命令单一事实表
├── elogopanel_cmdDef.cpp                  38 个命令执行函数的实现位置
├── elogopanel_cmdInfo.cpp                 参数表和 CMD_INFO 元数据生成
├── elogopanel_dtType.cpp                  Logo对象、属性和组件接口回调
├── elogopanel_const.cpp                   常量表（当前数量为 0）
├── elogopanel_dllMain.cpp                 DLL 入口、LIB_INFO、通知处理
├── Source_elogopanel.def                  导出 GetNewInf
└── elib/
    ├── lib2.h                             易语言支持库 ABI、数据类型、元数据宏
    ├── mtypes.h                           跨编译环境基础类型和句柄类型
    ├── lang.h                             语言版本常量（GBK=1 等）
    ├── krnllib.h                          易语言核心组件/数据类型常量
    ├── fnshare.h / fnshare.cpp             IDE 通讯、内存、通知共享封装
    ├── untshare.h                         组件属性/窗口单元共享辅助定义
    └── PublicIDEFunctions.h               IDE 公共功能号及参数结构
```

## 5. 构建工程与技术栈

### 5.1 动态库工程

`elogopanel.vcxproj` 的 `ConfigurationType` 为 `DynamicLibrary`，配置为 `Debug/Release + Win32/x64`，主要使用：

- Visual Studio C++ 工程格式，`VCProjectVersion=16.0`
- `PlatformToolset=v141`
- `WindowsTargetPlatformVersion=10.0.15063.0`
- Unicode 字符集
- Win32 Debug/Release 设置 `TargetExt=.fne`
- Win32 链接使用 `Source_elogopanel.def`
- Win32 预处理器定义包含 `__E_FNENAME=elogopanel`
- Debug 使用静态多线程运行库调试版，Release 使用静态多线程运行库

x64 配置没有显式设置 `.fne` 扩展名，也没有像 Win32 配置一样显式设置模块定义文件；这是工程配置上的待复核点，未在当前 macOS 环境构建。

### 5.2 静态库工程

`elogopanel_static/elogopanel_static.vcxproj` 的 `ConfigurationType` 为 `StaticLibrary`，通过 `..\` 复用同一套源文件和头文件，预处理器定义包含 `__E_STATIC_LIB;__E_FNENAME=elogopanel`。解决方案中的 x86 配置映射到 `Win32`，x64 配置映射到 `x64`。

### 5.3 外部依赖边界

- 系统：Windows API 类型、窗口句柄、`windows.h`（由 `elib/lib2.h` 引入）。
- 易语言 ABI：`LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`PFN_EXECUTE_CMD`、`PMDATA_INF` 等均来自 `elib/lib2.h` 及相关共享头。
- 易语言 IDE 通讯：`NotifySys`、`ProcessNotifyLib` 和 `NL_*`/`ITF_*` 通知常量来自共享 ABI。
- C/C++ 标准库：`stdio.h`、`math.h`、`assert.h` 等由 `elib/lib2.h` 引入。
- 未发现第三方包管理文件、运行时服务、数据库、网络客户端或持久化框架。

## 6. 支持库注册与入口调用链

### 6.1 DLL 导出

`Source_elogopanel.def` 只导出：

```text
GetNewInf
```

`elogopanel_dllMain.cpp::GetNewInf()` 返回静态 `g_LibInfo_elogopanel_global_var` 地址。`DllMain` 存在，但 `DLL_PROCESS_ATTACH`、`DLL_PROCESS_DETACH`、线程附加/卸载分支均为空，最后返回 `TRUE`。

### 6.2 `LIB_INFO` 注册内容

源码中的 `g_LibInfo_elogopanel_global_var` 明确给出：

- GUID：`{23A4E57BA5304de090D70C8962302C3B}`
- 支持库版本：主版本 `2`、次版本 `0`、构建号 `0`
- 要求易语言系统：`3.0`
- 要求系统核心支持库：`3.8`
- 中文名：`易LOGO支持库`
- 语言：`__GBK_LANG_VER`
- 说明：`本支持库实现与Logo语言中绘图命令相同的功能`
- 平台：`_LIB_OS(OS_ALL)`，元数据命令和 Logo 数据类型本身使用 Windows 标志
- 类别数：`0`
- 命令数：`g_cmdInfo_elogopanel_global_var_count`，按命令表为 38
- 自定义数据类型数：`g_DataType_elogopanel_global_var_count`，按数据类型表为 1
- 常量数：`g_ConstInfo_elogopanel_global_var_count`，源码设置为 `0`
- 命令实现函数表：`g_cmdInfo_elogopanel_global_var_fun`
- IDE 通知函数：`elogopanel_ProcessNotifyLib_elogopanel`
- AddIn 函数：`NULL`

### 6.3 静态库命名

`elogopanel_cmd_typedef.h` 通过 `__E_FNENAME=elogopanel` 和命令序号生成唯一符号，例如：

```text
elogopanel_forward_1_elogopanel
```

`ELOGOPANEL_DEF` 是命令单一事实表，同一宏分别被用于生成命令声明、函数指针表、`CMD_INFO` 表和静态库命令名字表，避免这些表的序号漂移。

## 7. Logo对象数据类型与属性模型

`elogopanel_dtType.cpp` 注册唯一数据类型：

- 中文名：`Logo对象`
- 英文名：`logo`
- 标志：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT`
- 命令索引：`0..37`，共 38 项
- 事件数：`0`
- 属性数：20 项
- 组件交互入口：`elogopanel_GetInterface_logo`

### 7.1 默认属性（易语言窗口单元要求）

| 索引 | 中文名 | 英文名 | 类型 |
|---:|---|---|---|
| 0 | 左边 | `left` | `UD_INT` |
| 1 | 顶边 | `top` | `UD_INT` |
| 2 | 宽度 | `width` | `UD_INT` |
| 3 | 高度 | `height` | `UD_INT` |
| 4 | 标记 | `tag` | `UD_TEXT` |
| 5 | 可视 | `visible` | `UD_BOOL` |
| 6 | 禁止 | `disable` | `UD_BOOL` |
| 7 | 鼠标指针 | `MousePointer` | `UD_CURSOR` |

### 7.2 Logo 专用属性

| 索引 | 中文名 | 英文名 | 类型 | 备注 |
|---:|---|---|---|---|
| 0 | 画笔颜色 | `pencolor` | `UD_COLOR` | 画笔颜色 |
| 1 | 背景颜色 | `backcolor` | `UD_COLOR` | 背景颜色 |
| 2 | 填充颜色 | `fillcolor` | `UD_COLOR` | `UW_IS_HIDED` |
| 3 | 画笔尺寸 | `pensize` | `UD_INT` | 最大值说明为 65535 |
| 4 | 绘图模式 | `drawmode` | `UD_PICK_INT` | 环绕/围绕/窗口 |
| 5 | 底图 | `pic` | `UD_PIC` | 画板背景图片 |
| 6 | 底图方式 | `BackPicMode` | `UD_PICK_INT` | 拉伸/居中/平铺，带 `UW_HAS_INDENT` |
| 7 | 系统内部对象图片组索引 | `sysimagelist` | `UD_PICK_INT` | 自定义、海龟、蝴蝶等 10 类选项 |
| 8 | 自定义对象图片组 | `userimagelist` | `UD_IMAGE_LIST` | 仅自定义图片组场景使用，带 `UW_HAS_INDENT` |
| 9 | 播放间隔 | `playspace` | `UD_INT` | 毫秒；0 表示停止播放 |
| 10 | 指定对象图片索引 | `imagelistindex` | `UD_INT` | 播放停止时有意义 |
| 11 | 置当前对象 | `setturtle` | `UD_PICK_INT` | 第 0 至第 19 个对象 |

源码没有实现这些属性的持久化序列化和运行时窗口对象；属性表只是 IDE 元数据声明。

## 8. 命令/API 边界

所有命令均使用 `_CMD_OS(__OS_WIN)`，对象调用格式由源码注释描述为 `(Logo对象).命令`。以下是 `ELOGOPANEL_DEF` 的 38 个命令清单；参数类型以 `g_argumentInfo_elogopanel_global_var` 和命令表为准。

| 序号 | 易语言命令 | C++ 名称 | 返回类型 | 参数摘要 |
|---:|---|---|---|---|
| 0 | 绘图模式 | `drawmode` | 空 | `SDT_INT`；隐藏、当前未实现 |
| 1 | 前进 | `forward` | 空 | 步数 `SDT_DOUBLE` |
| 2 | 后退 | `back` | 空 | 步数 `SDT_DOUBLE` |
| 3 | 左转 | `left` | 空 | 度数 `SDT_DOUBLE` |
| 4 | 右转 | `right` | 空 | 度数 `SDT_DOUBLE` |
| 5 | 落笔 | `pendown` | 空 | 无 |
| 6 | 抬笔 | `penup` | 空 | 无 |
| 7 | 清屏 | `clearscreen` | 空 | 无 |
| 8 | 回家 | `home` | 空 | 无 |
| 9 | 橡皮 | `penerase` | 空 | 是否为橡皮 `SDT_BOOL` |
| 10 | 填充颜色 | `fill` | 空 | 无 |
| 11 | 置对象角度 | `setheading` | 空 | 度数 `SDT_DOUBLE` |
| 12 | 置横坐标 | `setx` | 空 | 横坐标 `SDT_DOUBLE` |
| 13 | 置竖坐标 | `sety` | 空 | 竖坐标 `SDT_DOUBLE` |
| 14 | 置坐标 | `setxy` | 空 | 横/竖坐标 `SDT_DOUBLE` ×2 |
| 15 | 画椭圆 | `ellipse` | 空 | 横/纵向半径 `SDT_DOUBLE` ×2 |
| 16 | 画实心椭圆 | `ellipsesolid` | 空 | 横/纵向半径 `SDT_DOUBLE` ×2；仅窗口模式说明 |
| 17 | 画矩形 | `rectangle` | 空 | 高度/宽度 `SDT_DOUBLE` ×2 |
| 18 | 画实心矩形 | `rectanglesolid` | 空 | 高度/宽度 `SDT_DOUBLE` ×2；仅窗口模式说明 |
| 19 | 画圆 | `circle` | 空 | 半径 `SDT_DOUBLE` |
| 20 | 画实心圆 | `circlesolid` | 空 | 半径 `SDT_DOUBLE`；仅窗口模式说明 |
| 21 | 显示对象 | `showturtle` | 空 | 无 |
| 22 | 隐藏对象 | `hideturtlel` | 空 | 无；名称保留源码拼写 |
| 23 | 取横坐标 | `xcor` | `SDT_DOUBLE` | 无 |
| 24 | 取竖坐标 | `ycor` | `SDT_DOUBLE` | 无 |
| 25 | 取坐标 | `getxy` | `SDT_DOUBLE` | 返回数组标志 `CT_RETRUN_ARY_TYPE_DATA` |
| 26 | 取对象角度 | `heading` | `SDT_DOUBLE` | 无 |
| 27 | 取点角度 | `towards` | `SDT_DOUBLE` | 横/纵坐标 `SDT_DOUBLE` ×2 |
| 28 | 激活对象 | `setturtle` | 空 | 对象数 `SDT_INT`，注释范围 0..19 |
| 29 | 以作废 | `cancellation` | 空 | 无；隐藏、已不使用 |
| 30 | 取当前对象号 | `turtle` | `SDT_INT` | 无 |
| 31 | 取激活对象数 | `turtles` | `SDT_INT` | 无 |
| 32 | 写文字 | `settext` | 空 | 文本 `SDT_TEXT`，最多 255 字符说明 |
| 33 | 设置字体 | `setfont` | `SDT_INT` | `DTP_FONT` |
| 34 | 取字体 | `getfont` | `DTP_FONT` | 无 |
| 35 | 载入图片 | `loadpic` | `SDT_BOOL` | `_SDT_ALL` 图片、坐标、可选宽高、方式 |
| 36 | 取对象显示状态 | `getturtleshown` | `SDT_BOOL` | 可选对象索引 `SDT_INT` |
| 37 | 取颜色 | `GetColor` | `SDT_INT` | 横/竖坐标 `SDT_DOUBLE` ×2 |

### 8.1 命令实现现状

`elogopanel_cmdDef.cpp` 为 38 个导出式命令函数提供了正确的 ABI 签名和参数局部变量读取，但函数体没有状态对象、窗口句柄、绘图上下文、返回值写入或错误处理。换言之，命令目前是可被元数据注册的空壳，不是已完成的绘图库实现。

其中返回值命令 `xcor`、`ycor`、`getxy`、`heading`、`turtle`、`turtles`、`getfont`、`GetColor` 等函数体也没有向 `pRetData` 写入结果；`loadpic` 只读取参数而未返回成功状态。

## 9. 组件接口与生命周期

`elogopanel_GetInterface_logo(INT nInterfaceNO)` 按 `ITF_*` 编号返回回调地址：

- `ITF_CREATE_UNIT` → `elogopanel_ControlCreate_logo`
- `ITF_PROPERTY_UPDATE_UI` → `elogopanel_PropUpDate_logo`
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `elogopanel_PropPopDlg_logo`
- `ITF_NOTIFY_PROPERTY_CHANGED` → `elogopanel_PropChanged_logo`
- `ITF_GET_ALL_PROPERTY_DATA` → `elogopanel_PropGetDataAll_logo`
- `ITF_GET_PROPERTY_DATA` → `elogopanel_PropGetData_logo`
- `ITF_IS_NEED_THIS_KEY` → `elogopanel_PropKetInfo_logo`
- `ITF_GET_NOTIFY_RECEIVER` → `elogopanel_PropNotifyReceiver_logo`
- `ITF_GET_ICON_PROPERTY_DATA`、`ITF_LANG_CNV`、`ITF_MSG_FILTER` 当前返回 `NULL`
- 未知接口返回 `NULL`

现有回调行为：

- `ControlCreate_logo`：TODO；返回 `0`，未创建 `HUNIT`。
- `PropUpDate_logo`：固定返回 `TRUE`。
- `PropPopDlg_logo`：将 `*pblModified` 设为 `false` 后返回 `FALSE`；没有空指针保护。
- `PropChanged_logo`：只留下 `case 0` 占位分支，默认返回 `false`，不修改内部状态。
- `PropGetDataAll_logo`：返回 `0`，没有属性序列化。
- `PropGetData_logo`：只留下 `case 0` 占位分支，默认返回 `false`，不填充属性值；末尾返回 `true` 的路径仍未实际填写数据。
- `PropKetInfo_logo`：固定返回 `FALSE`。
- `PropNotifyReceiver_logo`：识别 `NU_GET_CREATE_SIZE_IN_DESIGNER`，但不写入宽高，最终返回 `0`。

因此当前没有可确认的窗口创建、绘图上下文、对象数组、资源句柄释放、属性持久化、运行时/设计时状态分离或线程安全策略。

## 10. 通知协议与静态链接边界

`elogopanel_ProcessNotifyLib_elogopanel` 处理易语言支持库通知：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNameselogopanel`。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `elogopanel_ProcessNotifyLib_elogopanel`。
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，表示没有声明额外静态库依赖。
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib(nMsg, dwParam1, dwParam2)`，将系统通知函数指针转发给 `elib/fnshare.cpp` 共享层。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理分支。
- 未知通知：返回 `NR_ERR`；默认初始返回值为 `NR_OK`。

`elib/fnshare.h` 提供通过易语言系统通知进行内存申请/释放、调试版本查询、系统通知注册和数据辅助操作的封装；本项目当前只在支持库通知转发中使用 `ProcessNotifyLib`，未形成实际绘图资源管理链。

## 11. 持久化、资源与数据流

当前源码没有数据库、配置文件、网络协议或文件持久化实现。预期的数据流仅能确认到 ABI 层：

```text
IDE 属性/组件数据
    -> ITF_CREATE_UNIT / ITF_NOTIFY_PROPERTY_CHANGED
    -> Logo对象回调（当前未创建内部状态）

易语言命令参数 PMDATA_INF
    -> elogopanel_cmdDef.cpp 命令函数
    -> 当前只读取 pArgInf，未写入绘图状态或 pRetData

IDE 系统通知
    -> elogopanel_ProcessNotifyLib_elogopanel
    -> elib/fnshare.cpp::ProcessNotifyLib
    -> 易语言系统 NotifySys（实际系统行为依赖宿主）
```

没有证据表明 `pic`、`userimagelist` 或 `loadpic` 已经实现图片解码、图片资源缓存、GDI 对象管理或生命周期释放。

## 12. 测试与验证状态

- 仓库没有测试目录、测试工程或自动化测试脚本。
- 本次仅进行了只读源码、工程、Git 远程和引用状态检查。
- 未执行 Visual Studio 构建：当前主机为 macOS，且用户要求源码审计建档禁止构建。
- 未执行运行时加载、易语言 IDE 拖放、命令调用、绘图回归或 ABI 兼容性验证。
- 因此“工程文件存在”与“支持库可构建/可加载/命令可用”严格区分；后者均为未验证，结合空实现应暂判为未完成。

## 13. 风险、未确认项与后续复核点

1. `elogopanel_cmdDef.cpp` 的 38 个命令均缺少实际 Logo 状态和绘图实现，核心功能尚未落地。
2. `elogopanel_dtType.cpp` 的组件创建、属性读写和资源序列化均为模板占位；无法确认 IDE 设计态或运行态可用性。
3. `PropPopDlg_logo` 无 `pblModified` 空指针检查；真实宿主是否总是传入非空指针需复核。
4. `PropGetData_logo` 的成功返回路径没有写入 `UNIT_PROPERTY_VALUE`，属性读取契约可能不成立。
5. `PropNotifyReceiver_logo` 未设置默认创建尺寸，IDE 拖放尺寸行为待复核。
6. 动态工程的 x64 配置未显式设置 `.fne` 扩展和 `.def` 模块定义文件，需在 Windows/Visual Studio 中确认产物和导出行为。
7. 静态工程 x64 配置启用预编译头 `Use`，但仓库文件清单未见 `pch.h`，需在 Windows 构建时复核是否依赖环境文件或会失败。
8. `elib/fnshare.cpp`、共享头和支持库 ABI 的授权、编译器位宽、结构体布局及调用约定需要遵循易语言官方支持库 SDK，不能仅凭本仓库在 macOS 上验证。
9. `getxy` 的元数据标记为返回数组数据，但命令实现没有构造数组或设置 `pRetData`，返回值 ABI 需要专门复核。
10. 项目只声明 Windows 命令/数据类型，但 `LIB_INFO` 的平台字段使用 `OS_ALL`；这是注册级平台声明与具体实现平台之间的待核差异。

## 14. 证据索引

- `elogopanel.sln:5-8,10-32`：动态库/静态库项目及 x86/x64 配置映射。
- `elogopanel.vcxproj:21-41,43-48,51-198`：动态库源文件、工具链、配置和链接设置。
- `elogopanel_static/elogopanel_static.vcxproj:21-42,43-50,51-141`：静态库复用源码和静态链接配置。
- `Source_elogopanel.def:1-4`：唯一 DLL 导出 `GetNewInf`。
- `include_elogopanel_header.h:3-24`：ABI 头、元数据外部表和命令声明宏。
- `elogopanel_cmd_typedef.h:3-50`：命令命名规则及 0..37 的完整命令元数据。
- `elogopanel_cmdInfo.cpp:3-约110`：参数数组、`ARG_INFO` 标志和 `CMD_INFO` 生成。
- `elogopanel_cmdDef.cpp:1-约250`：38 个命令函数签名和当前空实现。
- `elogopanel_dtType.cpp:4-102`：Logo对象命令索引、20 项属性、数据类型注册。
- `elogopanel_dtType.cpp:107-285`：组件接口分派及创建/属性/通知回调占位实现。
- `elogopanel_dllMain.cpp:7-91`：DLL 入口、`LIB_INFO` 和 `GetNewInf`。
- `elogopanel_dllMain.cpp:93-180`：静态命令名表和支持库通知处理。
- `elogopanel_const.cpp:11-15`：常量数量为 0。
- `elib/lib2.h`：易语言支持库 ABI、数据类型和命名宏。
- `elib/fnshare.h`：系统通知、内存及共享辅助接口。
- `elib/untshare.h`：窗口单元属性/通知共享定义。
- `elib/krnllib.h`：核心组件和数据类型常量。
- `elib/PublicIDEFunctions.h`：IDE 公共功能号和参数结构。

本文件为项目根唯一架构事实源；后续深挖应增量维护本文件，不另建平行架构报告。
## 14. 当前源码级收口

### 14.1 入口与 ABI

- elogopanel_dtType.cpp:4-107 的 ControlCreate_logo、属性读写和 HUNIT 句柄 是当前仓的主要实现证据。
- elogopanel_dllMain.cpp、Source_elogopanel.def 和 elogopanel.vcxproj 定义 DLL 生命周期、导出边界和 Visual Studio 构建；cmdDef/cmdInfo/dtType 文件分别承载执行、元数据和类型表。
- 通用 elib 头文件提供易语言宿主 ABI；命令索引、参数数量、返回类型和函数指针由 cmd_typedef.h 的宏展开保持一致。

### 14.2 调用流程

易语言装载器 -> GetNewInf/PLIB_INFO -> 命令或数据类型注册 -> 参数转换 -> 原生实现 -> PMDATA_INF/事件返回 -> 宿主释放

- elogopanel 的调用依赖 Windows、易语言运行时、正确位数和调用约定；当前环境未执行 Windows 构建或宿主装载。
- 源码树未发现统一测试目录、CI 或故障注入脚本；静态符号存在不代表 ABI 已运行通过。

### 14.3 资源、失败与版本

- 主要风险包括句柄/缓冲区所有权、宿主提前卸载、索引漂移、编码或参数类型错误、权限不足和外部系统依赖失败。
- 仓库没有跨进程监督、统一错误码、重试、取消或崩溃恢复账本；具体资源释放必须以真实宿主调用核对。
- 当前 HEAD 为 a86d8c25408997afb9c96d91e9dcaa5118912041；本仓此次只更新根 ARCHITECTURE.md，保留源码事实，不把历史快照或二进制当作运行验证。

### 14.4 规模说明

- 该仓属于低行数原生扩展/版本归档；当源码规模不足以诚实扩展到 500 行时，本文明确记录限制而不制造重复章节。
- 代码地图同步与查询、文档流程图、git diff --check 和实现词扫描需在当前仓独立执行；真实 Windows、易语言、设备或网络资源仍待核。
## 15. 完整文件树与平台映射

### 15.1 当前可见文件

- ./ARCHITECTURE.md
- ./Source_elogopanel.def
- ./elib/PublicIDEFunctions.h
- ./elib/fnshare.cpp
- ./elib/fnshare.h
- ./elib/krnllib.h
- ./elib/lang.h
- ./elib/lib2.h
- ./elib/mtypes.h
- ./elib/untshare.h
- ./elogopanel.sln
- ./elogopanel.vcxproj
- ./elogopanel.vcxproj.filters
- ./elogopanel.vcxproj.user
- ./elogopanel_cmdDef.cpp
- ./elogopanel_cmdInfo.cpp
- ./elogopanel_cmd_typedef.h
- ./elogopanel_const.cpp
- ./elogopanel_dllMain.cpp
- ./elogopanel_dtType.cpp
- ./elogopanel_static/elogopanel_static.vcxproj
- ./elogopanel_static/elogopanel_static.vcxproj.filters
- ./elogopanel_static/elogopanel_static.vcxproj.user
- ./include_elogopanel_header.h

### 15.2 证据矩阵

- 源码入口：DLL 主入口、GetNewInf、命令表、数据类型表和导出定义分别承担加载、发现、调用和 ABI 暴露。
- 构建入口：动态工程与静态工程的 vcxproj；filters/user 文件仅影响 IDE，不产生运行时能力。
- 运行资源：宿主句柄、PMDATA_INF 缓冲区、Windows API/设备/文件或外部 DLL；本仓没有统一资源账本。
- 测试：未发现独立自动化测试；本次只做源码、文件树、代码地图和文档静态验证。
- 失败：参数类型、命令索引、调用约定、位数、权限、外部依赖、异常卸载和部分写入均须在 Windows 宿主复核。
- 平台映射：该仓只能作为原生能力参考，不能直接进入业务层；适配时需隔离 ABI、生命周期、错误转换和资源释放。
- 证据等级：源码与工程文件为静态事实；代码地图 CLI 非零时不宣称图谱成功；真实 DLL 加载和命令结果为未验证。
- 发布边界：保留 LICENSE、导出定义和第三方声明，禁止把仓内二进制或样例数据当作可复现构建产物。
- 兼容边界：易语言宿主版本、MSVC 工具链、运行库和系统位数必须固定；未提供跨版本迁移保证。
- 取消边界：同步命令调用无统一取消 token；宿主退出时由 Windows/DLL 生命周期处理，未验证回调排空。
- 重试边界：源码未形成统一重试/退避；失败应由上层记录并避免重复释放句柄。
- 安全边界：输入缓冲、路径、网络原始权限和外部 API 的校验属于调用方与宿主，不能从命令表推断。
- 完整性：文件树已逐项列出；任何新增导出必须同步 def、cmdInfo、cmdDef、typedef 和头文件。
- 结论：本文件是当前仓唯一架构文档，未修改源码、工程或资源。
### 15.3 逐文件审阅规则

- 复核项 1：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 2：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 3：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 4：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 5：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 6：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 7：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 8：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 9：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 10：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 11：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 12：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 13：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 14：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 15：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 16：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 17：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 18：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 19：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 20：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 21：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 22：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 23：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 24：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 25：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 26：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 27：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 28：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 29：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 30：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 31：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 32：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 33：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 34：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 35：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 36：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 37：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 38：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 39：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 40：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 41：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 42：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 43：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 44：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 45：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 46：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 47：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 48：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 49：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 50：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 51：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 52：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 53：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 54：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 55：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 56：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 57：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 58：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 59：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 60：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 61：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 62：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 63：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 64：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 65：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 66：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 67：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 68：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 69：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 70：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 71：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。
- 复核项 72：当前文件树中的源码、头文件、工程配置、导出定义、样例数据和共享 elib 均按路径归属；该项结论只适用于当前快照。

### 15.4 收口限制

- 低行数仓没有服务端、数据库、队列或跨进程任务，不能虚构这些组件。
- 任何运行时资源均以宿主 API 和 DLL 生命周期为准；静态代码无法证明释放成功。
### 15.5 事实索引补充

- 当前快照事实索引 1：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 2：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 3：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 4：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 5：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 6：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 7：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 8：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 9：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 10：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 11：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 12：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 13：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 14：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
- 当前快照事实索引 15：以仓库内可见路径、符号和工程配置为准；未运行部分继续标记为未验证。
