# eppt2000 架构建档

## 1. 项目定位

`eppt2000` 是 Gitee「精易官方」仓库中的易语言支持库源码骨架，目标是向易语言暴露 PowerPoint 2000/XP/2003 或更高版本的 Windows 自动化操作能力。库元信息把它命名为“PowerPoint2000支持库”，要求易语言系统 3.7、系统核心支持库 3.7，运行环境必须安装 PowerPoint 2000 或以上版本。

当前仓库更准确的定位是：**支持库 ABI、命令/参数/数据类型元数据和组件回调模板已生成；PowerPoint 操作实现尚未落地**。源码中没有 COM 自动化调用、PowerPoint 类型库导入或实际对象状态管理。

本文件是本项目唯一的架构事实源。后续细探应并入本文件，不再建立平行长期报告。

## 2. 版本与证据基线

- 目标根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eppt2000`
- 本地分支：`master`
- 本地提交：`be7e9b7592f83fd328ab88ae601e15661fb027f2`
- 本地提交时间：`2022-12-19 16:07:38 +0800`
- Git 提交说明：`初始化仓库`
- 远程：`origin https://gitee.com/JYtechnology/eppt2000.git`
- 远程 `HEAD` / `refs/heads/master`：`be7e9b7592f83fd328ab88ae601e15661fb027f2`
- 工作树建档前状态：`master...origin/master`，无源码改动
- Git 跟踪文件数：23；没有测试、示例、文档、资源或生成二进制文件
- 旧细探文件：目标根及其子树未发现匹配 `*细探*` 的文件
- 代码地图：目标仓库没有 `.codegraph/`，因此 `codegraph_explore` 返回“未建立索引”；本次改用源码、工程文件和 Git 只读盘点
- 专属 MCP：`system_engineering_toolkit` HTTP `http://127.0.0.1:8766/mcp/` 可连接；其 `project_context` 当前绑定系统工程平台而非本仓库，不能把平台代码地图或平台验证记录当作本项目证据
- 当前核对未构建、未安装依赖、未启动 PowerPoint、未提交 Git；结论均来自当前源码和工程配置静态证据

## 3. 总体流程图

```text
易语言 IDE / 编译器
        │
        │ 加载 Windows .fne 支持库
        ▼
Source_eppt2000.def ──仅导出──> GetNewInf()
        │
        ▼
LIB_INFO（版本/GUID/命令表/数据类型表/通知入口）
        │
        ├── g_cmdInfo_eppt2000_global_var ──命令显示元数据
        ├── g_cmdInfo_eppt2000_global_var_fun ──48 个命令函数地址
        ├── g_DataType_eppt2000_global_var ──3 个组件 + 19 个枚举
        └── eppt2000_ProcessNotifyLib_eppt2000()
                         │
                         ├── NL_SYS_NOTIFY_FUNCTION
                         │       ▼
                         │   elib/fnshare.cpp 保存易系统通知函数指针
                         │
                         ├── NL_GET_CMD_FUNC_NAMES ──> 返回静态编译命令名数组
                         ├── NL_GET_NOTIFY_LIB_FUNC_NAME ──> 返回通知函数名
                         ├── NL_GET_DEPENDENT_LIBS ──> 返回空依赖列表
                         └── 其他通知 ──> 当前大多空处理并返回 NR_OK

命令调用
    │
    ▼
eppt2000_<英文名>_<索引>_eppt2000(pRetData, nArgCount, pArgInf)
    │
    ├── 少数函数只从 pArgInf 读取参数到局部变量
    └── 当前没有 COM 调用、状态变更、pRetData 写回或错误处理

组件设计器回调
    │
    ▼
PPTApp / PPTPresentations / PPTPlay 的 GetInterface_*
    │
    ├── 返回 ControlCreate / 属性更新 / 属性读写 / 事件接收等回调地址
    └── 回调仍为模板：创建返回 0，属性数据未序列化，事件通知未接入
```

## 4. 目录与文件地图

```text
eppt2000/
├── eppt2000.sln                         VS 解决方案，DLL + 静态库
├── eppt2000.vcxproj                     动态支持库工程，输出 Win32 .fne
├── eppt2000_static/
│   ├── eppt2000_static.vcxproj          静态库工程
│   ├── eppt2000_static.vcxproj.filters
│   └── eppt2000_static.vcxproj.user
├── eppt2000.vcxproj.filters
├── eppt2000.vcxproj.user
├── Source_eppt2000.def                  DLL 导出定义，仅导出 GetNewInf
├── include_eppt2000_header.h            统一包含、全局表声明、命令原型展开
├── eppt2000_cmd_typedef.h               EPPT2000_DEF 命令单一宏表及名称拼接
├── eppt2000_cmdInfo.cpp                 48 条命令的参数表和 CMD_INFO 表
├── eppt2000_cmdDef.cpp                  48 个命令函数的生成骨架
├── eppt2000_dtType.cpp                  组件、属性、事件、枚举、组件回调
├── eppt2000_const.cpp                   常量表占位，当前数量为 0
├── eppt2000_dllMain.cpp                 DLL 入口、LIB_INFO、通知入口、导出表
└── elib/
    ├── lib2.h                           易语言支持库 ABI/宏/基础类型依赖
    ├── mtypes.h                          非 Windows 类型兼容定义
    ├── lang.h                            GBK 编译语言版本定义
    ├── krnllib.h                         系统核心支持库组件常量
    ├── fnshare.h / fnshare.cpp           易系统通知、内存、数组和文本辅助
    ├── untshare.h                        组件属性/窗口辅助模板
    └── PublicIDEFunctions.h              IDE 通知功能与参数结构声明
```

仓库没有独立的业务层、COM 封装层、PowerPoint 对象适配层、配置文件、数据库、缓存、测试目录或发布脚本。

## 5. 构建工程与交付边界

### 5.1 解决方案

`eppt2000.sln` 包含两个 Visual C++ 项目：

1. `eppt2000.vcxproj`：`DynamicLibrary`，动态支持库。
2. `eppt2000_static/eppt2000_static.vcxproj`：`StaticLibrary`，静态链接版本。

解决方案声明 `Debug|x64`、`Debug|x86`、`Release|x64`、`Release|x86`；x86 配置映射到工程的 `Win32`。两个工程都使用 `PlatformToolset=v141`、Windows SDK `10.0.15063.0`、Unicode 字符集。

动态工程的 Win32 配置设置 `TargetExt=.fne`，链接使用 `Source_eppt2000.def`；x64 配置未显式设置 `.fne` 扩展，需在后续构建复核。静态工程 Win32 配置关闭预编译头，x64 配置写有 `PrecompiledHeader=Use`，但仓库未提供 `pch.h`，这是待复核的工程风险。

### 5.2 编译输入

动态、静态工程共同编译：

- `elib/fnshare.cpp`
- `eppt2000_cmdDef.cpp`
- `eppt2000_cmdInfo.cpp`
- `eppt2000_const.cpp`
- `eppt2000_dllMain.cpp`
- `eppt2000_dtType.cpp`

共同包含 `elib/*.h`、`include_eppt2000_header.h` 和 `eppt2000_cmd_typedef.h`。源码主要为 GB18030；`elib/fnshare.cpp` 为 UTF-16，编码一致性应由 Windows 工具链实际验证。

### 5.3 DLL 对外接口

`Source_eppt2000.def` 内容只有：

```text
LIBRARY

EXPORTS
    GetNewInf
```

因此 DLL 的正式装载入口是 `GetNewInf()`；48 个命令函数通过 `LIB_INFO.m_pCmdsFunc` 和命令名表交给易语言支持库系统，不是 `.def` 逐一导出。

## 6. ABI、宏和运行时通知

### 6.1 名称与静态链接

`elib/lib2.h` 要求先定义 `__E_FNENAME`。工程将其定义为 `eppt2000`。`eppt2000_cmd_typedef.h` 通过 `EPPT2000_NAME(index, name)` 将命令名拼成：

```text
eppt2000_<英文名>_<索引>_eppt2000
```

`EPPT2000_DEF(_MAKE)` 是命令的单一宏清单；同一清单被复用为：

- 命令函数声明（`include_eppt2000_header.h`）；
- `CMD_INFO` 元数据（`eppt2000_cmdInfo.cpp`）；
- 命令函数地址表（`eppt2000_dllMain.cpp`）；
- 静态编译命令名数组（`eppt2000_dllMain.cpp`）。

这保证命令索引、显示元数据和函数地址表理论上共享顺序；后续新增或调整命令必须只改 `EPPT2000_DEF` 并同步参数表。

### 6.2 `LIB_INFO` 元数据

`eppt2000_dllMain.cpp` 的 `g_LibInfo_eppt2000_global_var`：

| 字段 | 当前值 |
|---|---|
| GUID | `39A8BFA9AFF74dc9AC2C9ED581FB0510` |
| 版本 | `2.0.28` |
| 所需易语言系统 | `3.7` |
| 所需系统核心支持库 | `3.7` |
| 语言 | `__GBK_LANG_VER` |
| 系统 | Windows（`_LIB_OS(__OS_WIN)`） |
| 名称 | `PowerPoint2000支持库` |
| 依赖说明 | 机器中必须安装 PowerPoint2000 或更高版本 |
| 全局命令类别 | 0 |
| 常量数量 | 0 |
| AddIn/SuperTemplate | 均为 `NULL` |
| 通知函数 | `eppt2000_ProcessNotifyLib_eppt2000` |
| 依赖文件列表 | `NULL`；通知查询静态依赖时返回空双零字符串 |

### 6.3 系统通知

`eppt2000_ProcessNotifyLib_eppt2000` 处理：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNameseppt2000`；动态库路径下可用。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `eppt2000_ProcessNotifyLib_eppt2000` 的字符串名。
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，声明没有额外静态库依赖。
- `NL_SYS_NOTIFY_FUNCTION`：转发给 `elib/fnshare.cpp::ProcessNotifyLib`，记录易系统通知函数指针。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理。
- 未知通知：设 `NR_ERR`。

`elib/fnshare.cpp` 保存两个通知函数指针：一个用于向易系统发送消息，一个用于转发用户通知；收到 `NL_SYS_NOTIFY_FUNCTION` 后会通过 `NRS_GET_PRG_TYPE` 更新调试/编译版本标记。`NotifySys`、`ealloc`、`efree`、`CloneTextData`、`CloneBinData` 等辅助函数依赖易系统回调，不能脱离易语言运行时解释为独立 Windows API。

## 7. 命令面与调用契约

共 48 个命令，按数据类型索引分组如下。命令返回值的元数据多数标为 `SDT_BOOL`，但部分说明明确写出返回值目前“没有实际意义”。

### 7.1 `PPT程序`（索引 0—4，共 5）

- `创建` / `Create`：创建 PowerPoint 程序对象。
- `释放` / `Release`：释放程序对象。
- `取程序对象` / `GetApp`：取得 PowerPoint `Application` 对象。
- `退出` / `Quit`：退出 PowerPoint。
- `激活窗口` / `ActivateWindow`：激活 PowerPoint 窗口。

### 7.2 `PPT文稿`（索引 5—32，共 28）

- `置程序` / `SetApp`、`释放` / `Release`、`运行宏` / `RunMacro`。
- `取文稿集对象` / `GetPresentations`、`取文稿对象` / `GetPresentation`。
- `取幻灯集对象` / `GetSlides`、`取幻灯对象` / `GetSlide`。
- `取图形集对象` / `GetShapes`、`取图形对象` / `GetShape`。
- `打开` / `Open`、`保存` / `SaveAs`、`关闭` / `Close`、`打印` / `PrintOut`、`应用模板` / `ApplyTemplate`。
- `插入幻灯片` / `InsertNewSlide`、`删除幻灯片` / `DeleteSlide`、`删除全部幻灯片` / `DeleteAllSlides`。
- `添加媒体` / `AddMediaObject`、`添加图片` / `AddPicture`、`添加图形` / `AddShape`、`添加艺术字` / `AddTextEffect`、`添加文本框` / `AddTextbox`。
- `添加单色背景` / `AddSolidBkg`、`添加双色背景` / `AddTwoColorGradientBkg`、`添加预设背景` / `AddPresetGradientBkg`、`添加图案背景` / `AddPatternedBkg`、`添加预设纹理` / `AddPresetTexturedBkg`、`添加背景图` / `AddPictureBkg`。

### 7.3 `PPT播放`（索引 33—47，共 15）

- `置文稿` / `SetPresentation`、`释放` / `Release`。
- `取播放设置对象` / `GetSlideShowSettings`、`取播放视图对象` / `GetSlideShowView`、`取播放窗对象` / `GetSlideShowWindow`。
- `放映` / `Play`、`结束` / `Quit`、`切换` / `GoToSlide`、`到首张` / `First`、`到尾张` / `Last`、`下一张` / `Next`、`上一张` / `Previous`。
- `设放映指针` / `SetPointer`、`擦除笔迹` / `EraseDrawing`、`画线` / `DrawLine`。

### 7.4 参数元数据

`eppt2000_cmdInfo.cpp` 定义 79 个参数条目（索引 000—078），并由 `EPPT2000_DEF` 将参数起始位置和参数数量挂到命令上。参数类型使用易语言 ABI 的 `SDT_TEXT`、`SDT_BOOL`、`SDT_INT`、`SDT_FLOAT` 以及复合对象类型 `MAKELONG(0x01, 0)` / `MAKELONG(0x02, 0)`。

参数域覆盖：程序/文稿对象、宏名、文件名、只读/无标题/可见打开、保存格式、嵌入字体、打印页码和份数、模板名、幻灯片索引与版式、媒体/图片文件与位置尺寸、图形类型、艺术字和文本框排版、RGB 颜色、渐变样式与程度、播放指针和画线坐标等。默认值由 `AS_HAS_DEFAULT_VALUE` 标记；典型默认值包括：打开可见为真、保存格式为 11、插入索引为 -1、版式为 12、艺术字字号为 32、文本框自动调整/自动折行为真。

### 7.5 当前实现状态

`eppt2000_cmdDef.cpp` 共有 48 个函数定义。静态盘点结果：

- 24 个函数体完全为空。
- 另 24 个函数只读取 `pArgInf` 到 `arg1`—`arg14` 等局部变量。
- 没有命令函数调用 PowerPoint、访问 COM、写入 `pRetData`、设置错误码或释放对象。
- `创建`、`释放`、对象获取、关闭、放映、导航等无参数命令均为空函数体。
- 因此命令表是“可被 IDE 识别的接口声明”，不是已经可用的 PowerPoint 操作实现。

## 8. 数据类型、属性、事件与枚举

### 8.1 组件数据类型

`eppt2000_dtType.cpp` 注册 3 个 Windows 组件型/功能提供者数据类型，均带 `_DT_OS(__OS_WIN) | LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`：

1. `PPT程序` / `PPTApp`：负责创建并操作 PowerPoint 程序。
2. `PPT文稿` / `PPTPresentations`：负责操作 `Presentations`、`Presentation`、`Slides`、`Slide`、`Shapes`、`Shape`。
3. `PPT播放` / `PPTPlay`：负责操作 `SlideShowSettings`、`SlideShowView`、`SlideShowWindow`。

命令索引分别为 0—4、5—32、33—47；三者均有默认的 8 个易语言组件属性（左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针）。

属性表总量及自定义属性量：

| 类型 | 属性总数 | 默认属性 | 自定义属性 |
|---|---:|---:|---:|
| `PPTApp` | 18 | 8 | 10 |
| `PPTPresentations` | 73 | 8 | 65 |
| `PPTPlay` | 16 | 8 | 8 |

`PPTApp` 自定义属性包括窗口坐标/大小、标题、窗口状态、显示、版本、缩放、是否已创建。`PPTPresentations` 自定义属性覆盖幻灯片数量/索引/隐藏/版式、图形索引、视图和字体、页面设置、幻灯片尺寸、切换、动画、媒体播放等。`PPTPlay` 自定义属性覆盖放映方式、起止幻灯片、循环、画笔颜色、放映类型、动画和旁白设置。

### 8.2 事件

只有 `PPTApp` 注册 15 个事件：新文稿、文稿被关闭、新建幻灯片、文稿被打开、文稿被打印、文稿被保存、开始放映、结束放映、动画执行前、下一幻灯片、窗口被激活、双击前、右键单击前、窗口取消激活、选择区被改变。事件参数引用 PowerPoint 的 `Presentation`、`Slide`、`SlideShowWindow`、`DocumentWindow`、`Selection` 等兼容对象，双击/右键事件带可按引用修改的“取消”逻辑值。

`PPTPresentations` 和 `PPTPlay` 的 `LIB_DATA_TYPE_INFO` 事件指针为 `NULL`，当前未注册事件。

### 8.3 枚举类型

除 3 个组件外，还注册 19 个 Windows 枚举数据类型：

- `PPT格式` / `PPTFileFormat`（18 个成员）
- `幻灯版式` / `SlideLayout`（29 个成员）
- `文本方向` / `TextOrientation`（7 个成员）
- `文本水平定位` / `TextHorizontalAnchor`（3 个成员）
- `文本垂直定位` / `TextVerticalAnchor`（6 个成员）
- `过渡样式` / `GradientStyle`（8 个成员）
- `视图类型` / `ViewType`（9 个成员）
- `PPT对齐方式` / `Alignment`（6 个成员）
- `基准线对齐` / `BaseLineAlignment`（5 个成员）
- `打印方向` / `PrintOrientation`（3 个成员）
- `音效` / `SoundEffectType`（4 个成员）
- `动画高级模式` / `AdvanceMode`（3 个成员）
- `播放后效果` / `AfterEffect`（5 个成员）
- `动画方式` / `AnimateBy`（5 个成员）
- `文字动画级别` / `TextLevelEffect`（8 个成员）
- `文字组效果` / `TextUnitEffect`（4 个成员）
- `放映方式` / `PlayMode`（3 个成员）
- `放映类型` / `ShowType`（3 个成员）
- `指针类型` / `PointerType`（5 个成员）

枚举值是静态 `LIB_DATA_TYPE_ELEMENT` 表，供易语言 IDE 和命令参数选择使用；它们不是运行时 PowerPoint 类型库的动态读取结果。

## 9. 组件回调与状态模型

三个组件分别实现同构的 `GetInterface_*`，按照 `nInterfaceNO` 返回以下回调：

- `ITF_CREATE_UNIT` → `ControlCreate_*`
- `ITF_PROPERTY_UPDATE_UI` → `PropUpDate_*`
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `PropPopDlg_*`
- `ITF_NOTIFY_PROPERTY_CHANGED` → `PropChanged_*`
- `ITF_GET_ALL_PROPERTY_DATA` → `PropGetDataAll_*`
- `ITF_GET_PROPERTY_DATA` → `PropGetData_*`
- `ITF_IS_NEED_THIS_KEY` → `PropKetInfo_*`
- `ITF_GET_NOTIFY_RECEIVER` → `PropNotifyReceiver_*`

图标数据、语言转换、消息过滤接口返回 `NULL`。当前回调行为是模板行为：

- `ControlCreate_*` 返回 `HUNIT hUnit = 0`，没有创建内部对象。
- `PropUpDate_*` 无条件返回 `TRUE`。
- `PropPopDlg_*` 将 `*pblModified=false` 后返回 `FALSE`，且未检查空指针。
- `PropChanged_*` 只有占位的属性索引 `case 0`，没有合法性校验和状态更新。
- `PropGetDataAll_*` 返回 0，没有序列化属性。
- `PropGetData_*` 使用占位 `case 0`；部分路径返回 `false`，`PPTPlay` 模板末尾可返回 `true`，但没有填充 `pPropertyVaule`。
- `PropKetInfo_*` 无条件返回 `FALSE`。
- `PropNotifyReceiver_*` 没有设置设计器默认宽高，返回 0。

因此当前模型没有可恢复的 PowerPoint Application/Presentation/Slide/Shape 句柄，也没有资源生命周期、错误传播、线程模型或持久化状态。`pArgInf` 和 `pRetData` 只是易语言调用 ABI 的入口参数。

## 10. 依赖边界

### 10.1 已确认依赖

- Windows SDK / Win32：`windows.h`、窗口句柄、DLL 生命周期、`GetSysColor`、窗口样式等。
- 易语言支持库 ABI：`elib/lib2.h`、`fnshare.h`、`krnllib.h`、`lang.h`、`mtypes.h`、`untshare.h`、`PublicIDEFunctions.h`。
- 易语言运行时通知函数：内存申请释放、IDE/系统通知、调试版本查询。
- 外部产品契约（元数据声明）：Microsoft PowerPoint 2000 或以上版本。

### 10.2 未发现的依赖

源码中未发现 `#import`、`IApplication`/`_Application`、`CoCreateInstance`、`IDispatch`、COM 初始化、PowerPoint 类型库路径、第三方 `.lib`、DLL 名称或配置文件。`LIB_INFO` 中对 PowerPoint 的说明是产品前置条件，不等于当前源码已经接入 PowerPoint。

`NL_GET_DEPENDENT_LIBS` 返回空列表，工程也未填写额外链接库；但 Windows 系统库和易语言宿主提供的 ABI 仍是隐式运行依赖。

## 11. 真实调用链（当前可证实范围）

### 11.1 库加载链

```text
易语言加载 eppt2000.fne
  → 导出 GetNewInf()
  → 返回 g_LibInfo_eppt2000_global_var
  → 宿主读取命令/数据类型/常量/通知函数指针
  → 宿主发送 NL_SYS_NOTIFY_FUNCTION
  → eppt2000_ProcessNotifyLib_eppt2000
  → elib/fnshare.cpp::ProcessNotifyLib
  → 保存 PFN_NOTIFY_SYS，并查询 NRS_GET_PRG_TYPE
```

### 11.2 命令分发链

```text
宿主按 CMD_INFO 选择命令
  → g_cmdInfo_eppt2000_global_var_fun[index]
  → eppt2000_<EnglishName>_<index>_eppt2000(pRetData, nArgCount, pArgInf)
  → 当前最多读取 pArgInf[n] 的 m_pText/m_bool/m_int/m_float/m_pCompoundData
  → 当前没有后续业务调用，也没有写 pRetData
```

### 11.3 组件设计时链

```text
IDE 选择 PPTApp/PPTPresentations/PPTPlay 组件
  → 对应 LIB_DATA_TYPE_INFO 的组件交互函数
  → GetInterface_*(nInterfaceNO)
  → 返回 ControlCreate_* / 属性回调地址
  → 当前 ControlCreate_* 返回 0
  → 属性数据未保存、未加载、未同步到 PowerPoint
```

## 12. 测试、验证与未执行事项

### 12.1 仓库现状

- 没有测试目录、测试工程或测试脚本。
- 没有示例易语言工程或可运行样例。
- 没有 CI 配置、发布脚本或二进制夹具。
- 没有在本机 macOS 上构建；目标工程依赖 Windows/MSVC/易语言 ABI，当前环境不具备直接运行条件。
- 没有启动 PowerPoint，也没有做 COM/宿主实测。

### 12.2 当前核对已完成的只读验证

- 盘点 23 个 Git 跟踪文件、分支、提交和远程地址。
- `git ls-remote origin HEAD refs/heads/master` 确认远程与本地同为 `be7e9b7592f83fd328ab88ae601e15661fb027f2`。
- 静态提取 48 个命令函数、79 个命令参数条目、3 个组件、19 个枚举、15 个 `PPTApp` 事件。
- 对 `eppt2000_cmdDef.cpp` 逐函数检查：24 个空函数体，另外 24 个仅做参数局部变量读取。
- 检查工程文件、导出定义、ABI 头文件和通知入口。
- 确认目标仓库没有 `.codegraph/` 和旧细探文件。

### 12.3 后续定向验证建议

在 Windows + Visual Studio + 易语言 SDK 环境中，建议按以下顺序验证：

1. 先验证 DLL Win32 Debug/Release 是否能生成 `.fne`，并检查 `GetNewInf` 导出。
2. 再验证静态库 Win32 Debug/Release；单独复核 x64 配置的预编译头和输出扩展。
3. 用易语言 IDE 加载库，确认 48 个命令、3 个组件、19 个枚举和 `PPTApp` 事件可见。
4. 在 PowerPoint 实例可用的环境中验证 `创建`、`置程序`、`打开`、`保存`、`关闭` 的实际行为；当前源码预期会暴露“无实现”问题。
5. 如补实现，再补 COM 初始化/释放、宿主对象句柄、错误码、返回值写回、线程模型和 PowerPoint 版本兼容测试。

## 13. 风险与未确认项

### 高风险：接口元数据与实现脱节

命令和数据类型元数据看起来完整，但 48 个命令没有任何 PowerPoint 业务调用。对外显示“可操作”不代表功能可用；必须把元数据完成度与实现完成度分开记录。

### 高风险：返回值未写回

大量命令声明 `SDT_BOOL` 或对象返回类型，但函数体没有向 `pRetData` 写入结果。调用方可能得到未初始化/宿主残留值；不可把元数据返回类型当作实际返回契约。

### 高风险：组件句柄为 0

三个 `ControlCreate_*` 都直接返回 0，`SetApp`、`SetPresentation` 和 `Release` 只读取复合参数，没有形成句柄生命周期。任何依赖组件状态的属性、命令或事件都无法实际工作。

### 高风险：属性回调是占位代码

`PropPopDlg_*` 未检查 `pblModified` 是否为空；`PropGetData_*` 未填充输出结构；`PropChanged_*` 未验证输入；`PropGetDataAll_*` 始终返回 0。接入 IDE 设计器时可能出现崩溃、属性丢失或假成功。

### 中风险：事件只声明不接入

`PPTApp` 声明 15 个 PowerPoint 事件及对象参数，但源码没有事件监听、COM 连接点或通知转发实现；`PPTPresentations`、`PPTPlay` 的事件表为空。事件元数据不能作为运行时能力证据。

### 中风险：PowerPoint 版本契约未验证

库说明声称支持 PowerPoint 2000/XP/2003 或以上版本，但没有版本探测、COM 接口版本选择、降级策略或实际兼容测试。Office 版本、位数、COM 注册和权限边界均未确认。

### 中风险：工程配置不对称

动态工程 Win32 设置 `.fne` 和 `.def`，x64 没有同样的显式设置；静态工程 x64 使用预编译头但仓库没有 `pch.h`。这些是配置事实，不在当前核对通过构建推断是否可用。

### 中风险：ABI/指针宽度与现代 Windows

`elib/mtypes.h` 把若干句柄定义为 `DWORD`，并在 `efree`、通知返回值等路径把指针转换为 `DWORD`。这符合旧易语言 ABI 的历史约定，但在 x64 下可能截断指针；必须由对应易语言 SDK 的 ABI 规范和实际 x64 构建确认，不能直接按现代 Win64 句柄模型假设安全。

### 中风险：编码与字符集

核心源码标记为 GB18030，`elib/fnshare.cpp` 为 UTF-16，工程为 Unicode。命令文本、说明和 PowerPoint 文件路径均可能受到编码转换影响；后续实现文件路径与 COM 文本参数时应明确 ANSI/Unicode 边界。

### 未确认：宿主提供的 COM/自动化封装

当前仓库没有 COM 封装代码，不能确认“与 3.7 版对象兼容”是依赖外部旧支持库、易语言宿主内建机制，还是仅为接口设计说明。需要查同系列历史支持库或 Windows 构建产物，但不能用本仓库现有源码证明。

## 14. 后续研究边界

后续深挖应沿以下顺序增量补充本文件，不改写当前核对事实：

1. **实现核验**：确认是否存在同仓库历史提交、发布二进制或同系列项目提供真正 COM 实现；若无，明确其为未完成模板。
2. **ABI 核验**：在对应易语言 SDK 中确认 `LIB_INFO`、`LIB_DATA_TYPE_INFO`、`UNIT_PROPERTY`、`EVENT_INFO2` 和 `PMDATA_INF` 的精确内存布局。
3. **工程核验**：在 Windows/MSVC 环境验证 DLL/静态库配置、x64 输出、编码和 `.fne` 交付形态。
4. **COM 设计**：若要实现功能，单独设计 PowerPoint Application/Presentations/Presentation/Slides/Slide/Shapes/Shape/播放对象的持有、引用、释放和错误传播，不要把当前空函数当作实现基础事实。
5. **测试闭环**：先建立宿主加载测试，再建立 PowerPoint 可用/不可用、版本差异、文件错误、对象释放和事件回调测试。

当前核对仅完成架构建档；不得将上述后续事项表述为当前已实现能力。
