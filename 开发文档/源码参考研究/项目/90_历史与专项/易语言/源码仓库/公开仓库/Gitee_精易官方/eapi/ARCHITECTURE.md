# eapi 架构建档

> 本文件是 `eapi` 项目根目录的唯一架构事实源。当前取证只读源码、工程文件、Git 元数据和本地导航；未修改源码、未安装依赖、未构建、未运行 Windows 二进制或测试。
>
> 证据基线：本地 `master` / `c9647ab69ed4877de9d6486b9e0db13b65d7f7c4`；`origin` = `https://gitee.com/JYtechnology/eapi.git`；远程 `HEAD` 与 `refs/heads/master` 均为同一提交。

## 1. 项目定位

`eapi` 是精易官方公开的易语言“应用接口支持库”源码样本：以 Visual Studio C++ 工程编译为 Windows 支持库动态库（目标扩展名 `.fne`），并提供一套静态库工程。它将约 98 个面向 Windows 的系统/网络/窗口/打印/文件/媒体能力包装成易语言支持库命令，通过易语言支持库 ABI 的 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`MDATA_INF` 等结构向 IDE/运行时暴露元数据和命令函数指针。

项目不是通用跨平台库：所有命令元数据都使用 `_CMD_OS(__OS_WIN)`，核心实现直接调用 Win32、COM/WMI、Winsock、WinINet、WNet、注册表、Shell、GDI/打印等 Windows API。源码中没有独立业务服务、数据库、HTTP API、CLI 或项目级测试框架。

## 2. 版本、规模与现场状态

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eapi` |
| 当前分支 | `master`，跟踪 `origin/master` |
| 本地 HEAD | `c9647ab69ed4877de9d6486b9e0db13b65d7f7c4` |
| HEAD 日期 | `2023-03-03T08:02:06Z` |
| HEAD 提交 | `!2 两个命令返回值定义错误 Merge pull request !2 from AlongsCode/master` |
| 远程默认分支探测 | `origin/HEAD -> refs/heads/master`；远程 master 同为 `c9647ab69ed4877de9d6486b9e0db13b65d7f7c4` |
| 工作树 | 建档前干净；当前取证仅新增根 `ARCHITECTURE.md` |
| 源码文件 | `103 .cpp`、`9 .h`、`1 .hpp`；合计 113 个 C/C++ 源文件 |
| `cppCode/` | 98 个按编号命名的命令实现文件，约 252,636 bytes |
| `elib/` | 9 个易语言 SDK/运行时接口头源文件，约 140,915 bytes |
| 工程文件 | `eapi.sln`、`eapi.vcxproj`、`eapi_static/eapi_static.vcxproj` 及 VS 过滤器/用户文件 |
| 本地测试/CI | 未发现 `tests/`、测试工程、CTest、CMake、Makefile、GitHub/Gitee CI 配置 |
| README | 项目根没有 README；上级源码库 `源码仓库/README.md` 仅将 `eapi` 标为“应用接口支持库元数据样本” |
| 既有专项材料 | 目标仓库及其上级归档目录未发现 `既有专项文档` 或 eapi 专用既有专项材料文件 |

## 3. 总体流程图

```text
易语言 IDE/运行时
        │  加载 .fne / 读取支持库信息
        ▼
GetNewInf() ───────────────► LIB_INFO
        │                       │
        │                       ├─ 版本/GUID/OS/作者/库名
        │                       ├─ g_DataType_eapi_global_var ─► 11 个自定义数据类型
        │                       ├─ g_cmdInfo_eapi_global_var ─► 98 个 CMD_INFO
        │                       ├─ g_cmdInfo_eapi_global_var_fun ─► 98 个函数指针
        │                       └─ g_ConstInfo_eapi_global_var ─► 0 个常量
        │
        ├─ NL_SYS_NOTIFY_FUNCTION
        │        ▼
        │   eapi_ProcessNotifyLib_eapi()
        │        ▼
        │   ProcessNotifyLib() ─► fnshare.cpp 保存 PFN_NOTIFY_SYS/调试版本/用户回调
        │
        └─ 调用命令（统一 ABI）
                 ▼
        eapi_<命令>_<编号>_eapi(PMDATA_INF 返回值, INT 参数数, PMDATA_INF 参数数组)
                 │
                 ├─ 读取 MDATA_INF（整数/文本/复合类型/数组/字节集）
                 ├─ 调用对应的静态辅助函数
                 ├─ 直接调用 Win32/COM/WMI/Winsock/WinINet/WNet/Shell 等系统能力
                 └─ 通过 ealloc/CloneTextData/CloneBinData/create_array 写回易语言数据

构建分支：
  eapi.sln ─► eapi.vcxproj ─► DynamicLibrary + Source_eapi.def ─► .fne
           └► eapi_static.vcxproj ─► StaticLibrary（宏 __E_STATIC_LIB）
```

## 4. 真实目录地图

```text
eapi/
├── ARCHITECTURE.md                 # 本文件，唯一架构文档
├── eapi.sln                         # VS 解决方案，动态库与静态库两个项目
├── eapi.vcxproj                     # DynamicLibrary，Win32/x64，Debug/Release
├── eapi.vcxproj.filters
├── eapi.vcxproj.user                # 调试命令指向不存在/未归档的 TestProject\test.exe 与 test.e
├── include_eapi_header.h            # 公共入口：ABI 头、控制结构、命令声明、全局元数据 extern
├── eapi_cmd_typedef.h               # EAPI_NAME 命名规则与 EAPI_DEF 98 命令清单
├── eapi_cmdInfo.cpp                 # 115 个参数描述 + CMD_INFO 数组和计数
├── eapi_dtType.cpp                  # 11 个自定义数据类型及其成员/枚举元数据
├── eapi_const.cpp                   # 常量表，目前计数为 0
├── eapi_dllMain.cpp                 # DllMain、LIB_INFO、命令函数表、GetNewInf、通知分发
├── Source_eapi.def                  # 动态库模块定义，仅显式导出 GetNewInf
├── cppCode/                         # 98 个 eapi_<编号>_<实现名>.cpp 命令薄入口/实现
└── elib/
    ├── lib2.h                       # 易语言支持库 SDK ABI、类型、通知码、元数据结构
    ├── lang.h                        # 语言/运行时相关定义
    ├── krnllib.h                     # 核心库接口定义
    ├── mtypes.h                      # 数据类型定义
    ├── untshare.h                    # 组件/窗口共享定义
    ├── PublicIDEFunctions.h          # IDE 公共函数/通知定义
    ├── fnshare.h                     # 内存、文本、数组、通知共享辅助函数
    ├── fnshare.cpp                   # PFN_NOTIFY_SYS、调试版状态、通知转发的实现
    └── Tace.hpp                      # 公共辅助头（项目直接包含）

eapi_static/
├── eapi_static.vcxproj              # StaticLibrary，复用上层 cppCode 与 elib
├── eapi_static.vcxproj.filters
└── eapi_static.vcxproj.user
```

## 5. 分层与职责

### 5.1 支持库 ABI/公共适配层

`include_eapi_header.h` 汇总 `elib/lib2.h`、`lang.h`、`krnllib.h`、`eapi_cmd_typedef.h`、`tace.hpp`、`fnshare.h`。它定义 `CONTROL_STRUCT_BASE` 和通用 `DefControlProc`，并在非静态模式下声明常量、命令、函数指针、参数、数据类型元数据的全局数组。

`elib/fnshare.h/.cpp` 是项目唯一明显的共享运行时辅助层：

- `NotifySys()`：通过易语言提供的 `PFN_NOTIFY_SYS` 回调向宿主发通知；
- `ProcessNotifyLib()`：接收宿主通知，保存系统通知函数，并转发给用户回调；
- `isDebugVer()`：通过 `NRS_GET_PRG_TYPE` 读取运行/调试版本；
- `ealloc()` / `efree()`：使用易语言宿主的 `NRS_MALLOC` / `NRS_MFREE`；
- `CloneTextData()` / `CloneTextDataW()` / `CloneBinData()`：分配符合宿主约定的文本、宽文本、字节集；
- `GetAryElementInf()`、`create_array()`、`empty_array()`：解析/生成易语言数组布局；
- `args_to_sdata()`、`args_to_wsdata()`：将 `MDATA_INF` 参数映射为文本视图；
- `_GetIntByIndex()`、`SetIntByIndex()`、`GetPointerByIndex()`：访问复合数据成员。

### 5.2 元数据装配层

`eapi_cmd_typedef.h` 以单一宏清单 `EAPI_DEF(_MAKE)` 逐项列出 0–97 共 98 个命令。不同消费者重定义 `_MAKE`：

1. `include_eapi_header.h`：生成所有 ABI 函数声明；
2. `eapi_dllMain.cpp`：生成 `PFN_EXECUTE_CMD` 函数指针表；
3. `eapi_cmdInfo.cpp`：生成 `CMD_INFO` 命令描述表；
4. `eapi_dllMain.cpp`：生成静态编译所需函数名数组。

`eapi_cmdInfo.cpp` 维护参数表 `g_argumentInfo_eapi_global_var`，最后编号为 `/*114*/`，因此当前静态参数元数据有 115 项。每个命令通过偏移指针复用这张参数表，并记录中文名、英文名、解释、分类、OS 状态、返回类型、参数数目和用户难度。

`eapi_dtType.cpp` 提供 11 个自定义类型：`接口常量/ApiConst`、`矩形数据/RECT`、`CPU信息/CpuInf`、`系统信息/CpuInf`、`文件版本信息/CpuInf`、`BIOS信息/CpuInf`、`硬盘信息/CpuInf`、`网卡信息/NetCardInf`、`进程信息/ProcInf`、`显示模式信息/DisPlayInf`、`打印信息/PrintInf`。类型成员直接按 `LIB_DATA_TYPE_INFO`、`LIB_DATA_TYPE_ELEMENT` 静态表声明。

`eapi_const.cpp` 预留 `LIB_CONST_INFO` 数组，但 `g_ConstInfo_eapi_global_var_count = 0`，当前真正的接口常量主要来自 `ApiConst` 自定义枚举类型。

### 5.3 命令实现层

每个 `cppCode/eapi_<编号>_*.cpp` 通常包含一个或多个静态/命名空间辅助函数，以及一个符合 ABI 的 `EAPI_EXTERN_C void eapi_<name>_<number>_eapi(...)` 入口。入口读取 `PMDATA_INF`，调用实现函数，将结果写到 `pRetData` 或参数的复合数据指针中。

命令实现没有统一的业务服务抽象，按 Windows 能力域直接分文件：

- 系统与硬件：键盘灯、磁盘 IDENTIFY、驱动器/光驱、进程/DLL、系统/BIOS/CPU/内存/声卡；
- 文件、注册表与 Shell：自动运行、临时文件/URL 缓存、历史记录、字体、快捷方式、IE 工具条、程序组/程序项；
- 网络：网卡、MAC、主机名/IP、邮件、网络资源枚举、联网判断、端口、网络驱动器、网络消息；
- 窗口与桌面：特殊系统窗口、URL、桌面图标、任务栏、时钟、开始按钮、墙纸、透明度、鼠标捕获、窗口枚举/标题/类名/句柄；
- 显示与图像：显示模式、分辨率、单位换算、鼠标像素颜色、屏幕截图、图标提取、图片尺寸/格式、窗口圆角/置顶；
- 打印与进程外调用：打印机枚举/默认打印机/设置对话框、`eapi_93_GetDiskNumber.cpp` 通过 `CreatePipe` + `CreateProcessA` 执行 `wmic diskdrive get serialnumber`。

## 6. 完整命令清单

下表以 `eapi_cmd_typedef.h` 的 `EAPI_DEF` 为元数据事实源；括号内为实现文件。所有命令状态均标记 `_CMD_OS(__OS_WIN)`。

### 系统、硬件、进程与清理（0–41）

|编号|易语言命令|英文实现符号|实现文件|
|---:|---|---|---|
|0|取键盘指示灯状态|`GetKeyboardLockState`|`cppCode/eapi_0_GetKeyboardLockState.cpp`|
|1|模拟按键|`SimulateKey`|`eapi_1_SimulateKey.cpp`|
|2|模拟鼠标点击|`SimulateMouse`|`eapi_2_SimulateMouse.cpp`|
|3|取硬盘信息|`GetHDInfo`|`eapi_3_GetHDInfo.cpp`|
|4|取驱动器数量|`GetDrivesNum`|`eapi_4_GetDrivesNum.cpp`|
|5|取驱动器列表|`GetDrivesList`|`eapi_5_GetDrivesList.cpp`|
|6|弹出光驱|`PopupCdrom`|`eapi_6_PopupCdrom.cpp`|
|7|关闭光驱|`CloseCdrom`|`eapi_7_CloseCdrom.cpp`|
|8|取光驱盘符|`GetCdrom`|`eapi_8_GetCdrom.cpp`|
|9|光驱中是否有盘|`IsDiskInside`|`eapi_9_IsDiskInside.cpp`|
|10|取系统进程列表|`GetProcessList`|`eapi_10_GetProcessList.cpp`|
|11|终止进程|`KillProcess`|`eapi_11_SimulateKey.cpp`|
|12|取正在使用DLL列表|`GetDllList`|`eapi_12_GetDllList.cpp`|
|13|取没有响应程序列表|`GetHungProgramList`|`eapi_13_GetHungProgramList.cpp`|
|14|取系统信息|`GetSystemInfo`|`eapi_14_GetSystemInfo.cpp`|
|15|取BIOS信息|`GetBiosInfo`|`eapi_15_GetBiosInfo.cpp`|
|16|取文件版本信息|`GetFileVersionInfoW`|`eapi_16_GetFileVersionInfoW.cpp`|
|17|取CPU信息|`GetCpuInfo`|`eapi_17_GetCpuInfo.cpp`|
|18|取CPU占用率|`GetCpuUsges`|`eapi_18_GetCpuUsges.cpp`|
|19|取内存容量信息|`GetMemoryInfo`|`eapi_19_GetMemoryInfo.cpp`|
|20|取声卡名称|`GetAudioCard`|`eapi_20_GetAudioCard.cpp`|
|21|打开屏幕|`OpenMonitor`|`eapi_21_OpenMonitor.cpp`|
|22|关闭屏幕|`CloseMonitor`|`eapi_22_CloseMonitor.cpp`|
|23|添加右键菜单|`AddRightMenu`|`eapi_23_AddRightMenu.cpp`|
|24|删除右键菜单|`DeleteRightMenu`|`eapi_24_DeleteRightMenu.cpp`|
|25|设置自动运行|`SetAutoRun`|`eapi_25_SetAutoRun.cpp`|
|26|删除临时文件|`DeleteTempFile`|`eapi_26_DeleteTempFile.cpp`|
|27|清除历史记录|`ClearHistory`|`eapi_27_ClearHistory.cpp`|
|28|取系统字体列表|`GetFontList`|`eapi_28_GetFontList.cpp`|
|29|安装字体|`AddFont`|`eapi_29_AddFont.cpp`|
|30|删除字体|`RemoveFont`|`eapi_30_RemoveFont.cpp`|
|31|取图片宽度|`GetImageWidth`|`eapi_31_GetImageWidth.cpp`|
|32|取图片高度|`GetImageHeight`|`eapi_32_GetImageHeight.cpp`|
|33|提取资源文件图标|`GetIconFromResource`|`eapi_33_GetIconFromResource.cpp`|
|34|取IE版本号|`GetIEVersion`|`eapi_34_GetIEVersion.cpp`|
|35|添加IE工具条按钮|`AddButtonToIE`|`eapi_35_AddButtonToIE.cpp`|
|36|删除IE工具条按钮|`DeleteButtonFromIE`|`eapi_36_DeleteButtonFromIE.cpp`|
|37|创建程序组|`CreateProgramGroup`|`eapi_37_CreateProgramGroup.cpp`|
|38|删除程序组|`DeleteProgramGroupGroup`|`eapi_38_DeleteProgramGroupGroup.cpp`|
|39|创建程序项|`CreateProgramItem`|`eapi_39_CreateProgramItem.cpp`|
|40|删除程序项|`DeleteProgramItem`|`eapi_40_DeleteProgramItem.cpp`|
|41|取快捷方式目标|`GetShortCutTarget`|`eapi_41_GetShortCutTarget.cpp`|

### 网络与窗口（42–83）

|编号|易语言命令|英文实现符号|实现文件|
|---:|---|---|---|
|42|取网卡信息列表|`GetApapterList`|`eapi_42_GetApapterList.cpp`|
|43|取本机网卡名|`GetLocalAdapterName`|`eapi_43_GetLocalAdapterName.cpp`|
|44|取本机网卡物理地址|`GetLocalMac`|`eapi_44_GetLocalMac.cpp`|
|45|取远程网卡物理地址|`GetRemoteMac`|`eapi_45_GetRemoteMac.cpp`|
|46|取远程机器名|`GetRemoteName`|`eapi_46_GetRemoteName.cpp`|
|47|取IP地址|`GetRemoteName`|`eapi_47_GetRemoteName.cpp`|
|48|撰写邮件|`RunEmailAddr`|`eapi_48_RunEmailAddr.cpp`|
|49|取网络类型列表|`GetNetList`|`eapi_49_GetNetList.cpp`|
|50|取网络工作组列表|`GetGroupList`|`eapi_50_GetGroupList.cpp`|
|51|取网络计算机列表|`GetComputerList`|`eapi_51_GetComputerList.cpp`|
|52|是否联网|`IsConnectToInternet`|`eapi_52_IsConnectToInternet.cpp`|
|53|是否存在网络|`IsLoginNet`|`eapi_53_IsLoginNet.cpp`|
|54|端口检测|`CheckPort`|`eapi_54_CheckPort.cpp`|
|55|打开特殊系统窗口|`OpenSysWindow`|`eapi_55_OpenSysWindow.cpp`|
|56|打开指定网址|`OpenURL`|`eapi_56_OpenURL.cpp`|
|57|隐藏桌面图标|`HideDesktopIcon`|`eapi_57_HideDesktopIcon.cpp`|
|58|显示桌面图标|`ShowDesktopIcon`|`eapi_58_ShowDesktopIcon.cpp`|
|59|隐藏任务栏|`HideTaskBar`|`eapi_59_HideTaskBar.cpp`|
|60|显示任务栏|`ShowTaskBar`|`eapi_60_ShowTaskBar.cpp`|
|61|隐藏系统时钟|`HideClock`|`eapi_61_HideClock.cpp`|
|62|显示系统时钟|`ShowClock`|`eapi_62_ShowClock.cpp`|
|63|隐藏开始按钮|`HideStartButton`|`eapi_63_HideStartButton.cpp`|
|64|显示开始按钮|`ShowStartButton`|`eapi_64_ShowStartButton.cpp`|
|65|设置桌面墙纸|`SetDeskWallPaper`|`eapi_65_SetDeskWallPaper.cpp`|
|66|设置窗口透明度|`SetDiaphaneity`|`eapi_66_SetDiaphaneity.cpp`|
|67|取显示模式列表|`GetVideoList`|`eapi_67_GetVideoList.cpp`|
|68|取当前显示模式|`GetCurVideo`|`eapi_68_GetCurVideo.cpp`|
|69|设置屏幕分辨率|`SetResolveRatio`|`eapi_69_SetResolveRatio.cpp`|
|70|屏幕单位转换|`ChangeUnit`|`eapi_70_ChangeUnit.cpp`|
|71|取当前鼠标处颜色值|`GetPointRGB`|`eapi_71_GetPointRGB.cpp`|
|72|捕获鼠标|`SetCapture`|`eapi_72_SetCapture.cpp`|
|73|释放鼠标|`ReleaseCapture`|`eapi_73_ReleaseCapture.cpp`|
|74|截取屏幕区域|`GetScreenBitma`|`eapi_74_GetScreenBitma.cpp`|
|75|取所有窗口列表|`GetAllWindowsList`|`eapi_75_GetAllWindowsList.cpp`|
|76|取窗口标题|`GetWindowTextW`|`eapi_76_GetWindowTextW.cpp`|
|77|取窗口类名|`GetClassNameW`|`eapi_77_GetClassNameW.cpp`|
|78|取鼠标所在窗口句柄|`GetHwndFromPoint`|`eapi_78_GetHwndFromPoint.cpp`|
|79|映射网络驱动器|`NetAddConnection`|`eapi_79_NetAddConnection.cpp`|
|80|发送网络信息|`NetSendMessage`|`eapi_80_NetSendMessage.cpp`|
|81|取网络共享资源列表|`GetShareResourceList`|`eapi_81_GetShareResourceList.cpp`|
|82|取消网络驱动器映射|`CancelNetConnection`|`eapi_82_CancelNetConnection.cpp`|
|83|取消自动运行|`CancelAutoRun`|`eapi_83_CancelAutoRun.cpp`|

### 格式化、打印、显示与权限（84–97）

|编号|易语言命令|英文实现符号|实现文件|
|---:|---|---|---|
|84|格式化字符串|`sprintf`|`eapi_84_sprintf.cpp`|
|85|取打印机列表|`GetPrinterList`|`eapi_85_GetPrinterList.cpp`|
|86|取默认打印机|`GetDefaultPrinterW`|`eapi_86_GetDefaultPrinterW.cpp`|
|87|设置默认打印机|`SetDefaultPrinterW`|`eapi_87_SetDefaultPrinterW.cpp`|
|88|打开打印机对话框|`OpenPrintSetDlg`|`eapi_88_OpenPrintSetDlg.cpp`|
|89|取屏幕DPI|`GetMoniterDPI`|`eapi_89_GetMoniterDPI.cpp`|
|90|隐藏鼠标|`HideCursor`|`eapi_90_HideCursor.cpp`|
|91|显示鼠标|`ShowCursor`|`eapi_91_ShowCursor.cpp`|
|92|取图片格式|`GetPictureFormat`|`eapi_92_GetPictureFormat.cpp`|
|93|取硬盘编号|`GetDiskNumber`|`eapi_93_GetDiskNumber.cpp`|
|94|蜂鸣|`MessageBeep`|`eapi_94_MessageBeep.cpp`|
|95|置窗口圆角化|`RoundedWindow`|`eapi_95_RoundedWindow.cpp`|
|96|窗口置顶|`SetForegroundWindow`|`eapi_96_SetForegroundWindow.cpp`|
|97|程序提权|`UpPrivilegeValue`|`eapi_97_UpPrivilegeValue.cpp`|

## 7. 关键调用链与数据契约

### 7.1 动态库加载与元数据

```text
LoadLibrary(eapi.fne)
  └─ GetNewInf()
      └─ 返回 static LIB_INFO g_LibInfo_eapi_global_var
          ├─ m_nMajorVersion=3, m_nMinorVersion=2, m_nBuildNumber=0
          ├─ m_szGuid="F7FC1AE45C5C4758AF03EF19F18A395D"
          ├─ m_szName="应用接口支持库"
          ├─ m_dwState=_LIB_OS(__OS_WIN)
          ├─ m_nCmdCount=g_cmdInfo..._count
          ├─ m_pBeginCmdInfo=g_cmdInfo...
          ├─ m_pCmdsFunc=g_cmdInfo..._fun
          ├─ m_nDataTypeCount=g_DataType..._count
          ├─ m_pLibConst=g_ConstInfo...（当前 count=0）
          └─ m_pfnNotify=eapi_ProcessNotifyLib_eapi
```

`GetNewInf()` 会按固定数组下标修正 5 个被 Windows A/W 宏影响的英文名：索引 16、76、77、86、87 分别改为不带 `A/W` 的 `GetFileVersionInfo`、`GetWindowText`、`GetClassName`、`GetDefaultPrinter`、`SetDefaultPrinter`。静态编译通知 `NL_GET_CMD_FUNC_NAMES` 则反向返回这些位置的 W 版本符号名。

### 7.2 单值命令：键盘灯

`eapi_0_GetKeyboardLockState.cpp` 是最小入口样本：

```text
pArgInf[0].m_int（可省略，默认0）
  └─ GetKeyboardLockState(type)
      └─ GetKeyboardState(BYTE[256])
          └─ VK_NUMLOCK/VK_CAPITAL/VK_SCROLL 的低位
              └─ pRetData->m_bool
```

### 7.3 复合输出：硬盘信息

`eapi_3_GetHDInfo.cpp` 读取 `pArgInf[0].m_pCompoundData` 取得 `HDInfo`，默认磁盘序号为 0；实现打开 `\\.\PhysicalDriveN`，依次调用 `DeviceIoControl(SMART_GET_VERSION)` 与 `SMART_RCV_DRIVE_DATA`，解析 ATA IDENTIFY 扇区，使用 `CloneTextData()` 写入 `model`、`Version`、`serial`，再填容量、缓存、柱面、磁头、扇区字段。

### 7.4 数组输出：进程列表

`eapi_10_GetProcessList.cpp` 使用 `CreateToolhelp32Snapshot`、`Process32First/Next` 遍历进程；每个 `PROCINF` 及进程名通过 `ealloc()` 分配，汇总到 `std::vector<LPPROCINF>`，最后通过 `create_array<LPPROCINF>()` 生成易语言数组；无结果返回 `empty_array()`。

### 7.5 外部协议/系统组件：端口与 BIOS

- `eapi_54_CheckPort.cpp`：`WSAStartup` → `getaddrinfo` → `socket` → `connect` → `closesocket` → `freeaddrinfo` → `WSACleanup`；空 IP 时先通过主机名解析得到本机 IP。
- `eapi_15_GetBiosInfo.cpp`：使用 `GetSystemFirmwareTable` 取得 SMBIOS 原始表，解析 DMI 字符串；同时通过 WMI/COM (`CoInitialize`、`CoCreateInstance`、`IWbemServices::ConnectServer`) 取得其它 BIOS 字段，并统一 `CloneTextData`/`clone_text` 输出。

### 7.6 字节集输出：屏幕截图

`eapi_74_GetScreenBitma.cpp` 先用 GDI 获取屏幕位图；输出类型由参数决定：写文件走 `CreateFileA`/`WriteFile`，剪贴板走 `OpenClipboard`/`SetClipboardData`，字节集走宿主通知码 `NotifySys(2034, ...)` 获得全局内存后 `GlobalLock`/`GlobalSize`，最终 `CloneBinData()` 生成易语言字节集并释放位图/内存对象。

### 7.7 变长参数：格式化字符串

命令 84 在元数据中带 `CT_ALLOW_APPEND_NEW_ARG`。`eapi_84_sprintf.cpp` 遍历 `pArgInf[1..nArgCount)`，按 `SDT_INT`、`SDT_FLOAT`、`SDT_DOUBLE`、`SDT_INT64`、`SDT_BYTE`、`SDT_TEXT` 将值拼入字节缓冲区，调用 `vsprintf_s`，然后 `CloneTextData()` 写回文本。该路径依赖调用方格式字符串与参数类型严格匹配。

## 8. 构建、链接与平台边界

### 8.1 动态库项目

`eapi.vcxproj` 为 `DynamicLibrary`，使用 `PlatformToolset=v142`、`CharacterSet=Unicode`，Win32 Debug/Release 明确 `LanguageStandard=stdcpp17`，Win32 Debug 输出扩展名 `.fne`，Release/调试输出目录保留历史 Windows 路径 `G:\IDE\E语言\e\lib\`。动态库链接 `Source_eapi.def`，而 `.def` 文件仅显式导出 `GetNewInf`；命令函数由支持库元数据函数表间接提供。

### 8.2 静态库项目

`eapi_static/eapi_static.vcxproj` 为 `StaticLibrary`，复用上层 `cppCode`、`elib`、元数据和入口实现，Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=eapi`，输出历史路径 `G:\IDE\E语言\e\static_lib\`。静态模式由 `#ifndef __E_STATIC_LIB` 分支排除 `DllMain`/`LIB_INFO` 动态加载数据，但保留命令函数名/通知协议供编译器或宿主使用。

### 8.3 未在本机执行的验证

本机为 macOS，仓库是 Windows Visual Studio 工程，不能把本机无法运行的 `msbuild`/Windows SDK 构建结果伪称为通过。当前取证没有安装交叉编译依赖、没有生成 DLL/静态库、没有加载 `.fne`，因此 ABI、链接、运行时资源释放和 Windows API 行为尚未得到现场执行验证。

## 9. 测试与验证现状

### 已确认

- 工程文件完整列出了动态库的 98 个 `cppCode` 命令源和 `elib/fnshare.cpp`；静态库工程复用了同一批命令源。
- `eapi_cmd_typedef.h` 的索引 0–97 连续，`eapi_cmdInfo.cpp` 的参数表编号 000–114 连续，`eapi_dtType.cpp` 的自定义类型编号 000–010 连续。
- Git 工作树建档前干净；远程 `HEAD` 已用 `git ls-remote --symref` 核对。
- 目标仓库无项目级单元测试/集成测试/CI 文件；上级 README 仅作为归档导航，不能作为实现证明。

### 未执行/未证明

- 未执行 Visual Studio `msbuild`、链接器、Windows SDK、Win32 API 运行测试；
- 未验证 98 个函数指针与 98 个 `CMD_INFO` 的运行时逐项对应关系；
- 未验证易语言宿主分配器 `NRS_MALLOC/NRS_MFREE`、数组布局、复合数据布局在目标版本运行时中的实际兼容性；
- 未验证 COM/WMI、注册表、WinINet、WNet、打印机、WMIC、管理员权限和桌面交互场景；
- 未验证多线程/重入/宿主卸载通知下的静态全局回调和资源生命周期。

## 10. 风险与待核项

### 阻断级（若要生产复用，必须先解决）

1. **平台锁定 Windows ABI**：所有命令状态和实现都指向 Windows；不能直接编译或加载到 macOS/Linux 后端。若接入其它平台，需独立进程/远程 Windows worker 或明确的平台适配边界。
2. **宿主内存和复合数据 ABI 未隔离**：命令直接操作 `PMDATA_INF`、`m_pCompoundData`、`m_pAryData` 并调用宿主通知码；错误的结构对齐、版本或释放方式可能造成宿主崩溃。不能在主进程直接复用这些原生入口。
3. **缺少自动化测试和 CI**：仓库没有验证命令、测试夹具或跨版本 ABI 回归，当前只能完成静态建档，不能宣称实现可运行。
4. **命令入口返回契约依赖手写元数据**：`EAPI_DEF`、参数表偏移、数据类型表和每个 `eapi_*` 实现是多处手工同步；任何索引/偏移/返回类型漂移都会在宿主侧表现为内存解释错误。

### 重要风险

1. `eapi_47_GetRemoteName.cpp` 的实现实际为“主机名→IP”（`GetIpFromHostName`），但 `EAPI_DEF` 的英文符号仍写 `GetRemoteName`，而注释参数也写“IP地址”；这是命令语义/命名/参数说明漂移，后续复核应以调用方期望为准。
2. `eapi_38_DeleteProgramGroupGroup.cpp` 的文件名与 `DeleteProgramGroupGroup` 符号包含重复 `Group`，疑似历史命名遗留；不能自动改名，需核对 ABI 兼容。
3. `eapi_52_IsConnectToInternet.cpp` 直接调用 `InternetGetConnectedState`；元数据说明文本复制了工作组列表描述，属于文档契约错误。
4. `GetNewInf()` 按固定下标修改命令名，隐含数组顺序不可变；新增/删除/重排命令必须同时更新这些下标。
5. `eapi_cmdInfo.cpp` 与 `eapi_dtType.cpp` 中多个自定义类型的英文名重复（例如 `CpuInf`），可能影响工具侧按英文名索引。
6. `eapi_84_sprintf.cpp` 使用 `reinterpret_cast<va_list>` 拼接变长参数，格式串/类型不匹配时存在未定义行为或越界风险；它还依赖宿主文本分配约定。
7. `eapi_93_GetDiskNumber.cpp` 通过 `CreateProcessA` 执行 `wmic`，并以固定 500ms 等待；新 Windows 环境可能没有 WMIC，且当前实现的管道/子进程错误路径与等待策略需运行时验证。
8. 多个命令通过 `#pragma comment(lib, ...)` 隐式链接 `wbemuuid.lib`、`wininet.lib`、`shlwapi.lib`、`Winmm.lib` 等，依赖 Windows SDK/库版本；工程文件没有独立依赖锁或能力探测。
9. `eapi_11_SimulateKey.cpp` 同时出现 Windows 头与 `unistd.h`/`sys/wait.h`，显示跨平台残留或移植实验痕迹；在目标 MSVC 配置下需专门编译核查。
10. `eapi.vcxproj.user` 的调试命令指向仓库未发现的 `TestProject\\test.exe` 和 `TestProject\\test.e`，调试配置不能作为可复现实验入口。
11. `eapi.sln` 含重复 `SolutionGuid` 行；静态工程的若干 x64 配置与 Win32 配置在预处理宏/链接设置上不完全对称，尤其需核查 `__E_FNENAME`、`.def` 和导出/符号发现行为。
12. 若干操作会修改系统状态（右键菜单注册表、自动运行、字体、桌面/任务栏、屏幕分辨率、网络映射、权限提升、文件擦除）；不能在生产宿主或未经隔离的分析环境直接调用。

### 待核复查顺序

```text
1. 在隔离 Windows x86/x64 环境确认 VS 工程可编译
   ↓
2. 加载 DLL，逐项核对 GetNewInf() 的 LIB_INFO / 98 CMD_INFO / 98 函数指针
   ↓
3. 建立 MDATA_INF、复合类型、数组、文本/字节集所有返回路径的 ABI 夹具
   ↓
4. 先测无副作用查询命令，再测 COM/WMI/网络/打印机
   ↓
5. 最后才测注册表、Shell、文件擦除、权限提升、桌面和网络写操作
   ↓
6. 记录不同易语言系统/核心库版本下的兼容性与失败码
```

## 11. 后续深挖建议

当前不改源码。后续核查，应继续在本文件增量维护，不建立平行架构事实源：

1. **元数据闭环**：脚本解析 `EAPI_DEF`、参数偏移、实现入口，静态核对命令数/索引/参数计数/返回类型；
2. **ABI 夹具**：在 Windows 隔离 worker 中加载 DLL，验证 `GetNewInf`、通知函数、分配/释放、数组和复合类型；
3. **命令契约**：按“无副作用查询 → 只读系统 API → 外部网络/COM → 系统写操作”分层，记录真实返回值、错误路径和资源释放；
4. **安全边界**：把注册表、Shell、WMIC、权限提升、文件擦除、桌面操作标为高风险能力，禁止主进程无确认调用；
5. **版本兼容**：以提交 `c9647ab...` 为当前证据，远程更新后重新核对 `EAPI_DEF` 数组顺序和 `LIB_INFO` 版本/GUID；
6. **复用裁决**：只提取易语言支持库元数据组织、宿主回调、命令契约和 Windows worker 边界，不复制原生实现到平台主进程。

## 12. 证据路径索引

- ABI 入口与库元数据：`include_eapi_header.h`、`eapi_dllMain.cpp`
- 命令命名与完整清单：`eapi_cmd_typedef.h`
- 参数/命令元数据：`eapi_cmdInfo.cpp`
- 自定义数据类型：`eapi_dtType.cpp`
- 常量表：`eapi_const.cpp`
- 宿主通知、内存、文本、数组：`elib/fnshare.h`、`elib/fnshare.cpp`
- SDK ABI：`elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`
- 动态库工程：`eapi.vcxproj`、`Source_eapi.def`
- 静态库工程：`eapi_static/eapi_static.vcxproj`
- 代表性实现：`cppCode/eapi_0_GetKeyboardLockState.cpp`、`eapi_3_GetHDInfo.cpp`、`eapi_10_GetProcessList.cpp`、`eapi_15_GetBiosInfo.cpp`、`eapi_54_CheckPort.cpp`、`eapi_74_GetScreenBitma.cpp`、`eapi_84_sprintf.cpp`、`eapi_93_GetDiskNumber.cpp`
- 版本与远程：`.git/HEAD`、`.git/config`、`git ls-remote --symref origin HEAD refs/heads/master`
- 归档导航：上级 `源码仓库/README.md`

> 未发现并列历史研究文件；后续新增材料必须逐条回到源码核实并吸收到本文件后，继续只维护本文件。

## 源码实现补充

- `cppCode/eapi_*.cpp` 按命令编号拆分 Windows API 适配，覆盖键盘锁、磁盘、进程、BIOS、网络端口、屏幕和字符串格式化；单文件通常负责参数转换、系统调用和易语言返回值封装。
- `eapi_0_GetKeyboardLockState.cpp`、`eapi_3_GetHDInfo.cpp`、`eapi_10_GetProcessList.cpp` 和 `eapi_15_GetBiosInfo.cpp` 代表状态查询类接口；句柄、缓冲区和权限失败不能统一当作空结果。
- `eapi_54_CheckPort.cpp`、`eapi_74_GetScreenBitma.cpp`、`eapi_84_sprintf.cpp` 代表网络、图像和格式化路径，分别存在超时、像素缓冲区大小、变参和编码风险。
- 工程/导出定义决定命令编号与 ABI；仓库未提供完整自动化测试，必须在 Win32/Win64 与易语言宿主中验证返回值、错误码、资源释放和系统权限。

## API 分组与资源边界

- 输入模拟：`eapi_1_SimulateKey.cpp`、`eapi_2_SimulateMouse.cpp`、`eapi_11_SimulateKey.cpp` 使用窗口/进程句柄；需验证权限、目标进程退出和句柄关闭。
- 硬件与系统信息：`eapi_3_GetHDInfo.cpp`、`eapi_14_GetSystemInfo.cpp`、`eapi_15_GetBiosInfo.cpp`、`eapi_17_GetCpuInfo.cpp`、`eapi_19_GetMemoryInfo.cpp` 读取 Windows API/WMI/SMART；权限和设备差异会导致失败。
- 进程与模块：`eapi_10_GetProcessList.cpp`、`eapi_12_GetDllList.cpp`、`eapi_13_GetHungProgramList.cpp` 调用 `OpenProcess`；必须对访问拒绝、快照句柄和进程竞态做失败测试。
- 文件与资源：`eapi_26_DeleteTempFile.cpp`、`eapi_33_GetIconFromResource.cpp`、`eapi_74_GetScreenBitma.cpp` 使用 `CreateFile*`、GDI 或资源句柄；异常路径需保证关闭。
- 网络与适配器：`eapi_42_GetApapterList.cpp` 至 `eapi_54_CheckPort.cpp` 查询网卡、MAC、连接和端口；超时、IPv6、无网卡和防火墙状态未统一。
- Shell/桌面：`eapi_55_OpenSysWindow.cpp` 至 `eapi_70_ChangeUnit.cpp` 修改窗口、任务栏、壁纸和显示设置；属于高权限副作用能力。
- 字符串/格式：`eapi_84_sprintf.cpp` 等格式化接口涉及缓冲区长度和编码，需覆盖空指针、超长文本和 GBK/Unicode 转换。
- 提权：`eapi_97_UpPrivilegeValue.cpp` 请求进程令牌权限；失败必须显式返回，不能把管理员权限假定为默认。

所有实现均通过支持库命令表进入，返回值和数组写回依赖 `PMDATA_INF` ABI。当前仅有源码和工程证据，未在 Windows 运行真实硬件、权限、网络或桌面操作；不得将函数名和注释视为通过测试。验证应先执行 Win32/x64 Debug 构建，再装载 `GetNewInf`，按能力分组运行最小成功/失败夹具，并记录 Windows 版本、权限令牌、目标进程位数、设备列表和清理结果。仓库没有自动化测试目录、CI 配置或发布门禁，本档案仅保存源码事实和未验证风险。
