# ecompress 架构建档

> 首轮全量架构建档。本文是项目根目录唯一的架构事实文档；后续细探应直接补充本文件，不再建立平行架构报告。
>
> 研究边界：本轮只读源码、Visual Studio 工程、导出定义、依赖头文件、Git 元数据及测试目录；未改源码，未安装依赖，未构建，未提交。

## 1. 项目定位

`ecompress` 是面向易语言（Windows）的“压缩解压支持库”源码骨架，目标是以易语言支持库 ABI 提供 ZIP 压缩/解压命令、一个 `ZIP` 组件/函数提供者数据类型、压缩与解压缩进度事件，以及 UTF-8 文件名开关。

源码中的库元数据将其描述为：支持 `.zip`，可解压 WINZIP/WINRAR 等软件生成的 ZIP，生成的 ZIP 也可被其他压缩软件使用；但当前仓库没有 ZIP 算法、文件系统访问或事件驱动实现，五个命令函数和组件回调主要仍是生成器模板/空实现。因此“目标能力”与“当前可执行能力”必须区分：当前源码完成了支持库注册与 ABI 形状，尚未完成压缩业务。

仓库同时维护两个构建产物：

- `ecompress.vcxproj`：`DynamicLibrary`，Win32 配置目标扩展名为 `.fne`，由 `Source_ecompress.def` 公开 `GetNewInf`。
- `ecompress_static/ecompress_static.vcxproj`：`StaticLibrary`，使用同一组实现源文件，并通过 `__E_STATIC_LIB` 切换静态编译分支。

## 2. 总体流程图

```text
易语言 IDE / 运行时
        |
        | 动态库装载：GetNewInf()
        v
g_LibInfo_ecompress_global_var
        |
        +--> 版本/GUID/系统要求/库说明/类别
        +--> g_cmdInfo_ecompress_global_var
        |       |
        |       +--> 5 个 CMD_INFO 命令元数据
        |       +--> g_argumentInfo_ecompress_global_var（8 个参数描述）
        |       +--> g_cmdInfo_ecompress_global_var_fun
        |               |
        |               +--> ecompress_FolderToZip_0_ecompress（空实现）
        |               +--> ecompress_BinToZip_1_ecompress（空实现）
        |               +--> ecompress_ZipToFolder_2_ecompress（空实现）
        |               +--> ecompress_GetZipText_3_ecompress（空实现）
        |               +--> ecompress_SetUTF8Zip_4_ecompress（空实现）
        |
        +--> g_DataType_ecompress_global_var
        |       |
        |       +--> ZIP 数据类型/函数提供者
        |       +--> ecompress_GetInterface_ZIP()
        |               +--> 创建/属性/按键/通知接口分派
        |               +--> 组件/属性回调（当前为占位实现）
        |               +--> 压缩进度、解压缩进度事件元数据
        |
        +--> ecompress_ProcessNotifyLib_ecompress()
                |
                +--> NL_SYS_NOTIFY_FUNCTION
                |       +--> ProcessNotifyLib()
                |               +--> fnshare 保存系统通知函数指针
                |               +--> NotifySys() 查询调试/运行类型
                +--> 静态编译辅助：命令名/通知函数名/依赖库名

当前真实结果：注册和回调骨架可被编译器继续处理；压缩、解压、进度文本、组件创建和属性存取均未形成业务闭环。
```

## 3. 真实分层与目录地图

项目根目录只有一个解决方案、两个工程和一组共享源文件；没有 README、测试目录、第三方源码目录、脚本、安装包或运行时资源。

| 层次 | 路径 | 真实职责 |
|---|---|---|
| 解决方案 | `ecompress.sln` | 注册 `ecompress` 与 `ecompress_static` 两个 C++ 工程；配置 Debug/Release × Win32/x64。 |
| 动态库工程 | `ecompress.vcxproj` | 构建 `DynamicLibrary`；编译 6 个 `.cpp`，使用 `Source_ecompress.def`；Win32 目标扩展名为 `.fne`。 |
| 静态库工程 | `ecompress_static/ecompress_static.vcxproj` | 构建 `StaticLibrary`；以相对路径复用根目录实现与 `elib`。 |
| 命令声明/命名 | `ecompress_cmd_typedef.h` | 用 `ECOMPRESS_DEF` 单一宏表定义 5 条命令及其索引、显示名、英文名、返回类型、参数数和参数描述数组偏移；生成 ABI 符号名。 |
| 命令实现入口 | `ecompress_cmdDef.cpp` | 定义 5 个 `PFN_EXECUTE_CMD` 形状的导出内部函数；目前只读取参数到局部变量，没有业务处理或返回值写入。 |
| 命令元数据 | `ecompress_cmdInfo.cpp` | 定义 8 条 `ARG_INFO`，并由 `ECOMPRESS_DEF(ECOMPRESS_DEF_CMDINFO)` 生成 5 条 `CMD_INFO`；动态库分支有效，静态分支整体排除。 |
| 类型/组件元数据与接口 | `ecompress_dtType.cpp` | 注册 `ZIP` 数据类型，定义 2 个进度事件，按接口号返回创建、属性、按键和通知函数；具体组件回调是模板占位。 |
| 库生命周期/元数据 | `ecompress_dllMain.cpp` | 动态库 `DllMain`、`LIB_INFO`、`GetNewInf`、命令函数指针表、系统通知分派和静态编译辅助查询。 |
| 常量表 | `ecompress_const.cpp` | 动态分支提供空常量表，`g_ConstInfo..._count` 为 0。 |
| 系统通知适配层 | `elib/fnshare.cpp`、`elib/fnshare.h` | 保存易语言系统通知函数指针，转发 `ProcessNotifyLib`，提供 `NotifySys`、调试版本查询和用户通知回调。 |
| 易语言 ABI 基础 | `elib/lib2.h`、`elib/mtypes.h`、`elib/lang.h`、`elib/krnllib.h` | Windows 类型、易语言数据类型、库/命令/组件元数据结构、通知常量、函数指针和编译宏。 |
| 组件共享接口 | `elib/untshare.h` | 组件/窗口单元相关共享定义，由基础头间接提供组件 ABI。 |
| IDE 辅助接口 | `elib/PublicIDEFunctions.h` | 易语言 IDE 功能号和辅助数据结构；当前项目没有实际调用。 |
| 对外聚合头 | `include_ecompress_header.h` | 聚合 `lib2.h`、`lang.h`、`krnllib.h` 和命令宏，并声明动态元数据全局变量。 |
| 动态库导出定义 | `Source_ecompress.def` | 仅列出 `GetNewInf`。 |

## 4. 核心数据模型与持久化

### 4.1 支持库元数据模型

`ecompress_dllMain.cpp` 中的 `g_LibInfo_ecompress_global_var` 是运行时注册中心，关键事实如下：

- `LIB_FORMAT_VER = 20000101`。
- GUID 为 `7B68736E818E41c5A28B0AE4D43C128C`，源码注释要求同一库的所有版本保持不变。
- 库版本 `2.1.0`。
- 需要易语言系统 `3.0`，系统核心支持库 `3.0`。
- 名称为 `压缩解压支持库`，语言为 `__GBK_LANG_VER`。
- 运行平台状态为 `_LIB_OS(OS_ALL)`；具体命令和 ZIP 类型均通过 `_CMD_OS(__OS_WIN)`/`_DT_OS(__OS_WIN)`标记 Windows。
- 一个全局命令类别：`0000全局设置`。
- 5 个命令、1 个自定义数据类型、0 个预定义常量、无额外支持文件依赖字符串。
- `m_pfnNotify` 指向 `ecompress_ProcessNotifyLib_ecompress`，动态装载入口由 `GetNewInf()` 返回。

### 4.2 命令与参数模型

`ECOMPRESS_DEF` 是命令元数据的单一来源：

| 索引 | 易语言命令 | C++ 实现符号 | 返回值 | 参数 |
|---:|---|---|---|---:|
| 0 | `压缩` | `ecompress_FolderToZip_0_ecompress` | `SDT_INT` | 2 |
| 1 | `字节集压缩` | `ecompress_BinToZip_1_ecompress` | `SDT_INT` | 3 |
| 2 | `解压` | `ecompress_ZipToFolder_2_ecompress` | `SDT_INT` | 2 |
| 3 | `取进度提示` | `ecompress_GetZipText_3_ecompress` | `SDT_TEXT` | 0 |
| 4 | `置压缩解压UTF8字符集` | `ecompress_SetUTF8Zip_4_ecompress` | `_SDT_NULL` | 1 |

参数描述表共有 8 项，依次覆盖：源文件/文件夹、ZIP 文件名、字节集、ZIP 内文件名、解压 ZIP 文件名、目标文件夹名、UTF-8 布尔开关。实现函数使用 `pArgInf` 的约定槽位读取数据：前三个命令使用 `pArgInf[1..n]`，UTF-8 命令当前读取 `pArgInf[0].m_bool`；该索引差异应在后续实现前按易语言 ABI 再复核，不能仅凭模板注释推断。

### 4.3 ZIP 数据类型与事件模型

`g_DataType_ecompress_global_var` 只有一条 `LIB_DATA_TYPE_INFO`：

- 中文名 `ZIP` 压缩，英文名 `ZIP`。
- 标志 `_DT_OS(__OS_WIN) | LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`。
- 命令索引数组为 `0, 1, 2, 3`，表示 ZIP 类型关联前四条命令；UTF-8 设置命令是全局命令，不在该对象命令索引中。
- 两个事件：`压缩进度`、`解压缩进度`，各有一个 `SDT_INT` 参数“已完成百分比”，事件返回 `SDT_BOOL`。
- 事件说明声明：用户事件返回“假”时中止压缩/解压缩；当前源码没有触发事件的实现。
- 组件交互函数为 `ecompress_GetInterface_ZIP`，按接口号映射到创建、属性更新、定制对话框、属性改变、全部/单个属性读取、按键询问、附加通知接收者等回调。

### 4.4 持久化与外部状态

仓库中不存在数据库、配置文件、缓存、资源文件或压缩算法库。当前源码也没有实际的文件读写、内存持久化、ZIP 中央目录处理、编码转换或错误状态存储。所谓“源文件夹/文件名”“ZIP 文件名”“目标文件夹”等只是命令参数元数据和空实现中的局部变量，尚未产生 I/O。

组件属性接口目前没有声明实际属性数组；`ecompress_PropGetDataAll_ZIP` 返回 `0`，`ecompress_PropGetData_ZIP` 只有模板 `switch`，`ecompress_PropPopDlg_ZIP` 将 `*pblModified` 置 `false` 后返回 `FALSE`。因此没有可记录和恢复的组件实例状态。

## 5. 真实调用链与执行边界

### 5.1 动态库装载链

1. 易语言加载 `.fne` 后由 `Source_ecompress.def` 找到 `GetNewInf`。
2. `GetNewInf()` 返回 `g_LibInfo_ecompress_global_var`。
3. 易语言读取库版本、平台、类别、命令元数据、类型元数据和通知函数。
4. 命令调用通过 `g_cmdInfo_ecompress_global_var_fun` 按索引落到 `ecompress_cmdDef.cpp` 的五个函数。
5. 这些函数当前不写 `pRetData`，也不报告参数错误、文件错误或 ZIP 错误；不能据此宣称压缩/解压已可用。

### 5.2 系统通知链

`ecompress_ProcessNotifyLib_ecompress(nMsg, dwParam1, dwParam2)` 处理通知：

- `NL_SYS_NOTIFY_FUNCTION`：转发至 `ProcessNotifyLib`，由 `elib/fnshare.cpp` 保存 `PFN_NOTIFY_SYS`；首次收到时通过 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 更新调试/运行类型。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理。
- 动态分支的 `NL_GET_CMD_FUNC_NAMES` 返回命令函数名数组；`NL_GET_NOTIFY_LIB_FUNC_NAME` 返回通知函数名字符串；`NL_GET_DEPENDENT_LIBS` 返回双零结束的空依赖列表。
- 未识别消息返回 `NR_ERR`。

`ProcessNotifyLib` 末尾还会调用用户通过 `SetUserSysNotify` 注册的通知函数，用户回调的返回值会覆盖其默认返回值；当前项目没有使用该用户扩展入口。

### 5.3 ZIP 组件接口链

`ecompress_GetInterface_ZIP` 以 `nInterfaceNO` 分派：

- 返回 `ecompress_ControlCreate_ZIP`、`ecompress_PropUpDate_ZIP`、`ecompress_PropPopDlg_ZIP`、`ecompress_PropChanged_ZIP`、`ecompress_PropGetDataAll_ZIP`、`ecompress_PropGetData_ZIP`、`ecompress_PropKetInfo_ZIP`、`ecompress_PropNotifyReceiver_ZIP`。
- `ITF_GET_ICON_PROPERTY_DATA`、`ITF_LANG_CNV`、`ITF_MSG_FILTER` 等分支返回 `NULL`。
- `ecompress_ControlCreate_ZIP` 直接返回 `HUNIT hUnit = 0`；没有对象创建、窗口句柄、事件绑定或资源释放。
- 属性更新固定返回 `TRUE`，属性对话框固定未修改并返回 `FALSE`，属性通知/按键/设计器尺寸回调没有实际行为。

## 6. API、插件与协议边界

### 6.1 对易语言运行时的 ABI

- 动态入口：`EXTERN_C PLIB_INFO WINAPI GetNewInf()`，唯一显式 DLL 导出名见 `Source_ecompress.def`。
- 命令入口：`PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`；实现符号通过 `ECOMPRESS_NAME` 追加库名、命令英文名和命令索引，形成例如 `ecompress_FolderToZip_0_ecompress`。
- 通知入口：`ecompress_ProcessNotifyLib_ecompress(INT, DWORD, DWORD)`，通过 `m_pfnNotify` 注册；静态编译时还通过通知消息返回函数名。
- 组件接口：`PFN_GET_INTERFACE(INT)` 返回各 `PFN_INTERFACE` 回调。

### 6.2 命令语义边界

元数据声称的输入输出契约是：

- `压缩`：源文件夹或文件名 + ZIP 文件名，返回整数成功/失败/参数错误。
- `字节集压缩`：字节集 + ZIP 文件名 + ZIP 内文件名，返回整数。
- `解压`：ZIP 文件名 + 目标文件夹名，返回整数。
- `取进度提示`：无参数，返回文本。
- `置压缩解压UTF8字符集`：布尔值，全局影响后续压缩解压操作，无返回值。

以上是支持库元数据/注释定义的接口契约，不是已验证行为；当前实现尚未满足这些语义。

### 6.3 静态编译边界

`__E_STATIC_LIB` 会改变 `include_ecompress_header.h` 的外部元数据声明、`ecompress_cmdInfo.cpp` 的元数据编译、`ecompress_const.cpp` 的常量表、`ecompress_dtType.cpp` 的类型注册以及 `ecompress_dllMain.cpp` 的动态库入口/函数名数组分支。静态工程仍复用命令实现和部分通知代码，且 `ecompress_static.vcxproj` 在 Win32 配置显式定义 `__E_STATIC_LIB` 与 `__E_FNENAME=ecompress`。

静态库是否能被完整的易语言静态编译器正确链接，仓库没有测试或示例证明；应以后续真实工具链验证为准。

## 7. 技术栈与依赖边界

- 语言：C++，源码注释主要为中文，部分文件使用 GB18030 编码；工程 XML/解决方案为 UTF-8/ASCII 风格。
- 构建系统：Visual Studio/MSBuild C++ 工程，工程版本 `VCProjectVersion 16.0`，解决方案记录 Visual Studio 17.3；平台为 Windows，配置为 Win32/x64、Debug/Release。
- 工具集：动态与静态工程的 Win32 配置声明 `PlatformToolset v141`；目标 Windows SDK `10.0.15063.0`。
- 系统依赖：`lib2.h` 引入 Windows API 头（包括 `windows.h`），使用 `WINAPI`、`HMODULE`、`HWND`、`HMENU`、`HGLOBAL` 等 Windows 类型。
- 易语言支持库 ABI：`elib/lib2.h`、`elib/mtypes.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/untshare.h`、`elib/fnshare.h`。
- 编译期依赖：`__E_FNENAME` 必须在包含 `elib/lib2.h` 前定义；工程 Win32 动态配置定义 `__E_FNENAME=ecompress`，静态 Win32 配置也定义该宏。`ECOMPRESS_DEF` 和 `__E_STATIC_LIB` 控制命令/元数据代码生成。
- 第三方依赖：源码没有第三方 ZIP 库、包管理清单或链接库声明；`m_szzDependFiles` 和 `NL_GET_DEPENDENT_LIBS` 均为空。
- 运行时 I/O：当前代码没有真正调用 ZIP/文件系统 API；`elib` 仅为易语言支持库宿主 ABI 适配层。

## 8. 测试、验证与未执行事项

### 8.1 仓库内测试现状

未发现 `test`、`tests`、测试工程、测试脚本、CI 配置、示例程序或 README。项目只包含两个 Visual Studio 工程及源码/头文件。因此不存在“项目测试通过”的证据，也不能把工程文件存在等同于构建成功。

### 8.2 本轮实际验证

本轮完成的是静态证据核对，不是编译验证：

- 已核对解决方案确实包含 `ecompress` 与 `ecompress_static` 两工程。
- 已核对动态/静态工程的源文件清单、配置平台、预处理器宏、输出类型和动态库 `.def` 引用。
- 已核对 `ECOMPRESS_DEF` 的 5 条命令、8 条参数、命令函数符号、`LIB_INFO` 元数据、`ZIP` 类型、2 个事件和通知分派。
- 已核对 Git 工作树初始状态为 `master...origin/master` 且无源码差异；远程为 `https://gitee.com/JYtechnology/ecompress.git`。
- 已通过只读 `git ls-remote origin refs/heads/master` 核对远程 `master` 当前指向 `decadc1b52fc4d07c2ebf7ef07f7eaea7a75ff9f`。
- 本地 HEAD、`origin/master` 与远程 `master` 均为 `decadc1b52fc4d07c2ebf7ef07f7eaea7a75ff9f`，提交时间为 `2022-12-19 16:03:42 +08:00`，提交说明为 `初始化仓库`。

### 8.3 明确未执行

按任务边界未执行 Visual Studio/MSBuild、交叉编译、DLL/静态库装载、易语言 IDE 注册、ZIP 端到端调用、ABI 运行测试、内存检查、静态分析、依赖安装、远程 fetch/pull 和 Git 提交。因当前主机为 macOS，不能以本机未构建结果推断 Windows 工程可构建。

## 9. 风险、缺口与后续复核点

1. **核心业务为空**：`ecompress_cmdDef.cpp` 五个命令函数都没有写返回值或执行压缩/解压；文档中的成功/失败约定目前未实现。
2. **进度链路未接通**：事件元数据存在，但没有压缩循环、百分比计算、`NotifySys`/用户事件调用或取消处理；`取进度提示`也没有返回文本来源。
3. **组件仍是模板**：`ecompress_ControlCreate_ZIP` 返回 0，属性数组为空，属性读写和设计器尺寸处理没有实际状态；`ZIP` 类型的 `LDT_WIN_UNIT` 能否作为纯函数提供者使用需在真实 IDE 复核。
4. **编码开关只有声明**：`SetUTF8Zip` 只读取一个布尔值，未看到全局状态或 ZIP 文件名编码转换。
5. **x64 工程配置需复核**：动态工程的 x64 配置没有看到 Win32 配置中的 `TargetExt=.fne` 和 `ModuleDefinitionFile=Source_ecompress.def`；静态工程 x64 配置启用 `PrecompiledHeader=Use` 并指定 `pch.h`，仓库中没有 `pch.h`。这些是配置层风险，不以本轮构建结果定论。
6. **源码编码维护风险**：C++ 源文件和多个 `elib` 文件含 GB18030 中文，后续编辑需保持编码，避免字符串/注释损坏。
7. **参数槽位待复核**：`ecompress_SetUTF8Zip_4_ecompress` 读取 `pArgInf[0]`，其他命令读取 `pArgInf[1..n]`；实现前必须结合易语言 `PFN_EXECUTE_CMD` 调用约定及现成支持库样例确认。
8. **历史范围有限**：本仓库是 shallow clone，当前可见历史只有一个提交；旧分支、标签和未抓取的远程历史不能从本地仓库确认。
9. **缺少发布契约**：没有版本变更记录、ABI 兼容测试、安装路径约定、`.fne` 产物样例、静态链接示例或 CI 门禁。
10. **依赖声明与目标能力不一致**：库说明声称 ZIP 兼容性，但源码未包含 ZIP 引擎或第三方库；需要确认压缩引擎是否计划由后续提交、外部库或易语言宿主提供。

建议后续复核顺序：先确认 ZIP 引擎来源和支持库 ABI 参数槽位，再实现命令返回/错误/资源释放；随后接通进度事件与 UTF-8 状态；最后在 Windows + Visual Studio v141 下分别验证 Win32/x64 动态库和静态库，并用易语言 IDE 做装载、命令调用、组件创建和取消压缩的端到端测试。

## 10. 证据路径与版本基线

- 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/ecompress`
- 解决方案：`ecompress.sln`
- 动态工程：`ecompress.vcxproj`
- 静态工程：`ecompress_static/ecompress_static.vcxproj`
- 导出定义：`Source_ecompress.def`
- 命令表/实现：`ecompress_cmd_typedef.h`、`ecompress_cmdInfo.cpp`、`ecompress_cmdDef.cpp`
- 库入口/通知：`ecompress_dllMain.cpp`、`elib/fnshare.cpp`、`elib/fnshare.h`
- 类型/组件：`ecompress_dtType.cpp`
- ABI 聚合头：`include_ecompress_header.h`
- ABI 基础头：`elib/lib2.h`、`elib/mtypes.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/untshare.h`、`elib/PublicIDEFunctions.h`
- Git 远程：`https://gitee.com/JYtechnology/ecompress.git`
- 基线分支：`master`；本地与 `origin/master` 均指向 `decadc1b52fc4d07c2ebf7ef07f7eaea7a75ff9f`。
- 基线提交：`decadc1b52fc4d07c2ebf7ef07f7eaea7a75ff9f`，`2022-12-19T16:03:42+08:00`，`初始化仓库`。
- 旧细探：目标根未发现 `细探-*.md`；本文件没有可吸收的旧细探内容。
