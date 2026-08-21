# dp1 架构建档

> 本文件是 `dp1` 项目的唯一架构事实源。源码参考库默认只读；当前核对只新增本文件，未修改源码、工程文件、构建物或 Git 提交。
>
> 本项目没有发现 `细探-*.md`、`README`、`AGENTS.md` 或测试目录；后续只维护本文件，旧细探不存在可吸收。

## 1. 项目定位

`dp1` 是 Gitee「精易官方」公开仓库中的易语言支持库源码，库中文名为 **数据操作支持库一**。它按易语言支持库 ABI 编写为 Windows C/C++ 动态库，同时提供一个静态库工程；目标能力是数据压缩/解压、数据摘要、对称加解密以及 RSA 数字签名/验证。

必须区分“声明的能力”和“当前实现”：`dp1_cmd_typedef.h`、`dp1_cmdInfo.cpp`、`dp1_dllMain.cpp` 已完整声明 7 个命令及其元数据，但 `dp1_cmdDef.cpp` 的 7 个命令函数体目前只读取参数指针并没有写入 `pRetData`，也没有调用压缩、摘要、加密或 RSA 算法。因此当前源码更接近一个可装载的支持库骨架/模板，不能据此断言这些命令已经可运行。

## 2. 证据与版本基线

- 本地根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/dp1`
- 本地分支：`master`
- 当前提交：`ee42416d1a19a1014d8d3202bf04852ef2507806`
- 提交时间：`2022-12-19 16:54:32 +0800`
- 提交说明：`初始化仓库`
- 远程：`origin = https://gitee.com/JYtechnology/dp1.git`
- 远程默认分支：`master`；现场 `git ls-remote` 返回与本地相同的 `ee42416d1a19a1014d8d3202bf04852ef2507806`
- Git 状态：建档前工作树无已显示的修改；仓库为 shallow clone，当前现场可见提交为初始化提交。
- 文件盘点：不含 `.git` 的项目文件共 23 个，源码/工程文本约 4167 行；没有 README、测试、CI、安装脚本或运行示例。
- 编码：项目 C/C++ 源码包含中文注释和字符串，现场按 `GB18030` 解码可读；工程 XML 为 UTF-8；源码使用 CRLF 行尾。
- 代码图：曾按要求以目标绝对路径调用 CodeGraph 探索，但该目录及其父目录没有 `.codegraph/` 索引，工具明确返回“未索引”；以下结论均改由现场逐文件取证，不把 CodeGraph 缺失误写成源码事实。

## 3. 总体流程图

```text
易语言 IDE / 运行时
        │
        │ LoadLibrary + 固定导出 GetNewInf
        ▼
┌──────────────────────────────┐
│ dp1_dllMain.cpp              │
│ DllMain / g_LibInfo /        │
│ g_cmdInfo[] / 函数指针表      │
└──────────────┬───────────────┘
               │ 返回 PLIB_INFO
               ▼
      易语言登记命令与参数元数据
               │ 用户调用命令
               ▼
┌──────────────────────────────┐
│ g_cmdInfo_dp1_global_var_fun │
│ DP1_NAME 生成的 7 个函数指针   │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ dp1_cmdDef.cpp               │
│ Compress / Uncompress /      │
│ GetMD5 / Encrypt / Decrypt / │
│ RSAEncrypt / RSACheck        │
└──────────────┬───────────────┘
               │ PMDATA_INF 输入；pRetData 输出（当前未填充）
               ▼
       易语言运行时接收返回值

系统通知链：
易语言运行时 ── NL_SYS_NOTIFY_FUNCTION ──► dp1_ProcessNotifyLib_dp1
       │                                      │
       │                                      └─► fnshare.cpp::ProcessNotifyLib
       │                                           保存 PFN_NOTIFY_SYS
       └◄──────────── NotifySys / ealloc / efree / 用户回调转发

构建分支：
  dp1.vcxproj                 → DynamicLibrary → .fne（Win32 Debug/Release）
  dp1_static/dp1_static.vcxproj → StaticLibrary → .lib（__E_STATIC_LIB 分支）
```

## 4. 目录与文件地图

```text
dp1/
├── dp1.sln                         # VS 解决方案，动态库 + 静态库两个项目
├── dp1.vcxproj                     # 动态库工程
├── dp1.vcxproj.filters             # 动态库 IDE 过滤器
├── dp1.vcxproj.user                # 用户工程设置（空壳）
├── dp1_static/
│   ├── dp1_static.vcxproj          # 静态库工程，复用上级源码
│   ├── dp1_static.vcxproj.filters
│   └── dp1_static.vcxproj.user
├── Source_dp1.def                  # 动态库唯一显式导出：GetNewInf
├── include_dp1_header.h            # 总入口：运行时头、语言/核心头、命令声明
├── dp1_cmd_typedef.h               # DP1_DEF 命令单一清单和名称拼接宏
├── dp1_cmdDef.cpp                  # 7 个命令执行函数（当前为空实现）
├── dp1_cmdInfo.cpp                 # ARG_INFO、CMD_INFO 参数/命令元数据
├── dp1_const.cpp                   # 2 个算法常量
├── dp1_dtType.cpp                  # 自定义数据类型表，当前数量为 0
├── dp1_dllMain.cpp                 # DllMain、LIB_INFO、函数表、系统通知入口
└── elib/
    ├── lib2.h                      # 易语言支持库 ABI、数据类型、通知码、LIB_INFO
    ├── fnshare.h / fnshare.cpp     # 内存/文本/数组/通知辅助及回调转发
    ├── lang.h                      # GBK 语言版本常量
    ├── krnllib.h                   # 系统核心支持库常量和版本信息
    ├── mtypes.h                    # Windows/旧式基础类型兼容定义
    ├── untshare.h                  # 组件/属性/事件辅助模板（本项目当前未使用）
    └── PublicIDEFunctions.h        # IDE 辅助功能编号与结构（当前源码未调用）
```

## 5. 分层与依赖边界

### 5.1 支持库入口层

`include_dp1_header.h` 引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和 `dp1_cmd_typedef.h`，并在非静态库模式声明全局命令、参数、常量和数据类型表。`DP1_DEF_CMD` 将同一个 `DP1_DEF` 清单展开为 7 个命令函数声明，避免声明清单与实现函数名分叉。

`dp1_dllMain.cpp` 是运行时入口：

1. `DllMain` 仅对四类 DLL 生命周期通知做空处理，返回 `TRUE`。
2. `g_cmdInfo_dp1_global_var_fun` 通过 `DP1_DEF(DP1_DEF_CMD_PTR)` 建立命令索引到函数指针的数组。
3. `g_LibInfo_dp1_global_var` 汇总 ABI 版本、库 GUID、版本号、平台状态、作者资料、分类、命令表、函数表、常量表、数据类型表和通知回调。
4. `GetNewInf()` 返回 `&g_LibInfo_dp1_global_var`。
5. `dp1_ProcessNotifyLib_dp1()` 处理系统通知；静态库相关通知返回命令函数名数组、通知函数名和空依赖列表，系统通知函数交给 `ProcessNotifyLib`。

### 5.2 声明与元数据层

`dp1_cmd_typedef.h` 的 `DP1_DEF(_MAKE)` 是命令的单一清单，当前 7 项索引固定为 0～6。它同时提供中文名、C/C++ 英文名、说明、分类、平台状态、返回类型、难度、参数数量和参数表起点。

`dp1_cmdInfo.cpp` 按清单展开：

- 14 个 `ARG_INFO` 条目，按命令顺序连续排列。
- 7 个 `CMD_INFO` 条目，`m_pBeginArgInfo` 指向上述数组内对应偏移。
- `g_cmdInfo_dp1_global_var_count` 用 `sizeof` 计算为 7。
- `_DEBUG` 下额外生成 `dbg_cmd_arg_count__`，用于人工核对参数表数量。

`dp1_const.cpp` 声明两个数值常量：`DES算法 = 1`、`RC4算法 = 2`。没有其它持久化或配置数据。

`dp1_dtType.cpp` 提供 `g_DataType_dp1_global_var[1]` 占位数组，但 `g_DataType_dp1_global_var_count = 0`，因此当前库没有自定义数据类型、对象方法、属性或事件。

### 5.3 命令执行层

每个命令采用统一 ABI：

```cpp
void 命令名(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

函数由 `DP1_NAME(index, name)` 生成形如 `dp1_Compress_0_dp1` 的符号。当前实现只把 `pArgInf[i]` 中的字段取到局部变量，没有参数校验、异常/失败码、内存分配、结果类型设置或 `pRetData` 写回。

### 5.4 运行时桥接层

`elib/fnshare.cpp` 保存三个进程内静态状态：

- `s_pfnNotifySys`：由 `NL_SYS_NOTIFY_FUNCTION` 注入的易语言系统通知函数。
- `s_pfnuserNotifySys`：通过 `SetUserSysNotify` 设置的用户回调。
- `s_isDebug`：初值 `1253600`，第一次接到系统通知后调用 `NRS_GET_PRG_TYPE` 更新。

`NotifySys` 调系统回调并返回结果；`ealloc`/`efree` 通过 `NRS_MALLOC`/`NRS_MFREE` 与易语言内存体系交互；`ProcessNotifyLib` 保存通知函数、获取程序类型，并把通知继续转给用户回调。当前命令函数没有使用这些辅助函数。

### 5.5 ABI 兼容头层

`elib/lib2.h` 定义易语言支持库 ABI：

- `DATA_TYPE`、`SDT_BIN`、`SDT_TEXT`、`SDT_INT`、`SDT_BOOL` 等系统类型。
- `MDATA_INF`：以一字节对齐的联合数据载体，同时包含值、变量指针、数组/复合数据指针及 `m_dtDataType`。
- `ARG_INFO`：参数名、说明、数据类型、默认值和参数传递标志。
- `CMD_INFO`：命令名、英文名、分类、状态、返回类型、难度、参数表。
- `LIB_CONST_INFO`、`LIB_DATA_TYPE_INFO`：常量及自定义数据类型描述。
- `PFN_EXECUTE_CMD`、`PFN_NOTIFY_LIB`、`PFN_NOTIFY_SYS` 等回调类型。
- `LIB_INFO`：支持库登记总结构；固定 ABI 入口名为 `GetNewInf`。

`elib/mtypes.h` 是旧 Windows 类型兼容层；`lib2.h` 直接包含 `<windows.h>`、`<stdio.h>`、`<math.h>`，Debug 分支另含 `<assert.h>`。这是 Windows/Visual C++ 工程，不是跨平台实现。

## 6. 命令、参数与数据模型

### 6.1 命令清单

| 索引 | 中文名 | 生成函数 | 返回类型 | 分类 | 参数 | 源码证据 |
|---:|---|---|---|---:|---:|---|
| 0 | 压缩数据 | `dp1_Compress_0_dp1` | `SDT_BIN` | 1 数据压缩解压 | 1：`SDT_BIN` | `dp1_cmd_typedef.h:13`、`dp1_cmdDef.cpp:5` |
| 1 | 解压数据 | `dp1_Uncompress_1_dp1` | `SDT_BIN` | 1 数据压缩解压 | 1：`SDT_BIN` | `dp1_cmd_typedef.h:14`、`dp1_cmdDef.cpp:13` |
| 2 | 取数据摘要 | `dp1_GetMD5_2_dp1` | `SDT_TEXT` | 2 数据完整性校验 | 1：`SDT_BIN` | `dp1_cmd_typedef.h:15`、`dp1_cmdDef.cpp:21` |
| 3 | 加密数据 | `dp1_Encrypt_3_dp1` | `SDT_BIN` | 3 数据加解密 | 3：`SDT_BIN`、`SDT_TEXT`、可选 `SDT_INT` | `dp1_cmd_typedef.h:16`、`dp1_cmdDef.cpp:31` |
| 4 | 解密数据 | `dp1_Decrypt_4_dp1` | `SDT_BIN` | 3 数据加解密 | 3：`SDT_BIN`、`SDT_TEXT`、可选 `SDT_INT` | `dp1_cmd_typedef.h:17`、`dp1_cmdDef.cpp:43` |
| 5 | 数字签名 | `dp1_RSAEncrypt_5_dp1` | `SDT_TEXT` | 2 数据完整性校验 | 3：`SDT_BIN`、私钥 `SDT_TEXT`、公共模数 `SDT_TEXT` | `dp1_cmd_typedef.h:18`、`dp1_cmdDef.cpp:55` |
| 6 | 签名验证 | `dp1_RSACheck_6_dp1` | `SDT_BOOL` | 2 数据完整性校验 | 4：`SDT_BIN`、签名文本、 公钥文本、公共模数文本，后三者均 `SDT_TEXT` | `dp1_cmd_typedef.h:19`、`dp1_cmdDef.cpp:68` |

命令状态通过 `_CMD_OS(__OS_WIN)` 写入，表示每项命令声明支持 Windows。库级状态通过 `_LIB_OS(OS_ALL)` 写入，源码元数据因此出现“库级 OS_ALL、命令级仅 Windows”的边界差异；不能仅凭库级字段断言命令已经跨平台。

### 6.2 参数表与内存语义

`ARG_INFO` 的参数表偏移为：

```text
压缩数据   → g_argumentInfo_dp1_global_var + 0（1 项）
解压数据   → +0（1 项）
取数据摘要 → +0（1 项）
加密数据   → +1（3 项）
解密数据   → +4（3 项）
数字签名   → +7（3 项）
签名验证   → +10（4 项）
```

加密/解密的第三个参数标记为 `AS_DEFAULT_VALUE_IS_EMPTY`，说明运行时可能传入 `_SDT_NULL`；注释约定省略时默认 DES（常量 1），另一个常量为 RC4（2）。但命令实现没有读取 `nArgCount` 或处理缺省值，因此该语义尚未落地。

输入的 `SDT_TEXT`/`SDT_BIN` 指针按 ABI 约定只读；结果若为文本/字节集，正式实现应使用易语言内存通知分配并正确设置 `pRetData`，否则会破坏运行时所有权。目前源码没有任何结果分配或释放路径。

### 6.3 持久化与状态

项目没有数据库、配置文件、缓存、资源文件或磁盘读写代码。唯一状态是 DLL 进程内的通知函数指针和调试/运行版本标记；命令元数据、常量、函数指针均为静态全局表。RSA 私钥、公钥、模数按命令设计应由调用方以文本参数传入，源码未保存任何密钥。

## 7. API、插件与 ABI 边界

### 7.1 动态库外部接口

`Source_dp1.def` 只显式导出：

```text
GetNewInf
```

`GetNewInf` 使用 `WINAPI`，返回 `PLIB_INFO`，调用方据此读取命令/常量/数据类型表和 `PFN_NOTIFY_LIB`。命令实现函数名由 `DP1_NAME` 拼接，主要通过 `m_pCmdsFunc` 函数指针表调用，而不是通过 `.def` 逐个导出。

### 7.2 系统通知

`dp1_ProcessNotifyLib_dp1` 是 `LIB_INFO.m_pfnNotify` 指向的库通知函数。当前明确处理的通知包括：

- `NL_GET_CMD_FUNC_NAMES`：返回命令实现函数名字数组（非静态库分支）。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `"dp1_ProcessNotifyLib_dp1"`。
- `NL_GET_DEPENDENT_LIBS`：返回 `"\\0\\0"`，表示无额外静态库依赖。
- `NL_SYS_NOTIFY_FUNCTION`：把 `dwParam1` 传给 `fnshare.cpp::ProcessNotifyLib` 保存为 `PFN_NOTIFY_SYS`。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前空处理。
- 未知通知：返回 `NR_ERR`。

### 7.3 静态库命名协议

静态构建定义 `__E_STATIC_LIB` 和 `__E_FNENAME=dp1`，`lib2.h`/`dp1_cmd_typedef.h` 通过宏生成唯一符号和字符串，避免多个支持库静态链接时命令重名。`dp1_static` 工程复用上级的 6 个 `.cpp` 文件和全部头文件，不是另一套实现。

## 8. 构建工程与依赖

### 8.1 工程矩阵

- 解决方案：Visual Studio 17 格式，最低 VS 10.0；含 `dp1` 和 `dp1_static` 两个项目。
- 动态库：`ConfigurationType=DynamicLibrary`，Win32 Debug/Release 目标扩展显式设为 `.fne`；Win32 链接使用 `Source_dp1.def`。
- 静态库：`ConfigurationType=StaticLibrary`，复用上级源码；Win32 Debug/Release 明确设置 `__E_STATIC_LIB;__E_FNENAME=dp1`。
- 工程列出 Debug/Release × Win32/x64；工具集为 `v141`，Windows SDK 为 `10.0.15063.0`，启用 SDL 检查，Win32 为多线程运行库。

### 8.2 依赖

源码只直接依赖 Windows SDK/Visual C++ 运行环境和随仓库提供的 `elib` ABI 头文件；未发现第三方包管理、外部静态库、网络服务、数据库或运行时配置。`LIB_INFO.m_szzDependFiles` 为 `NULL`，系统通知 `NL_GET_DEPENDENT_LIBS` 返回空依赖列表。

### 8.3 工程风险/未确认项

以下是工程配置中可见、但当前核对未在 Windows/Visual Studio 上构建验证的风险：

1. 动态库 x64 配置的预处理宏没有像 Win32 一样显式设置 `__E_FNENAME=dp1`；`lib2.h` 要求该宏必须先定义，x64 构建可能直接预处理失败，除非环境属性表另行注入。
2. 动态库 x64 配置没有 `ModuleDefinitionFile=Source_dp1.def`，不能仅凭工程文件确认 x64 产物会导出固定入口 `GetNewInf`。
3. 动态库 x64 配置没有显式 `TargetExt=.fne`，默认目标扩展可能与 Win32 不同。
4. 静态库 x64 Debug/Release 配置使用 `PrecompiledHeader=Use`，但仓库没有 `pch.h`；该配置与 Win32 的 `NotUsing` 不一致，构建可能失败。
5. x64 配置也没有显式 `__E_STATIC_LIB;__E_FNENAME=dp1`（静态库）或 `__E_FNENAME=dp1`（动态库），应在 Windows 环境复核。
6. `mtypes.h` 将 `DWORD` 定义为 `unsigned long`、句柄定义为 `DWORD`，这是旧 32 位 ABI 风格；x64 下的指针/句柄截断风险不能靠源码静态阅读排除。
7. `Source_dp1.def` 只导出 `GetNewInf`；是否由编译器/链接器保留 `dp1_ProcessNotifyLib_dp1` 作为回调可由 `g_LibInfo` 访问，尚未做 PE 导出与装载验证。

## 9. 测试、验证与当前可运行性

### 9.1 现场检查结果

- 没有 `test*`、`tests/`、测试工程、CI 配置、示例调用或验收脚本。
- 当前核对未安装依赖、未启动服务、未在 macOS 上尝试 Windows 工程构建，也未生成构建物。
- 仅做了只读文件盘点、源码取证、Git 版本/远程复核和 CodeGraph 索引状态检查。

### 9.2 静态可确认项

- `DP1_DEF` 同时展开命令声明、函数指针数组、命令名数组和 `CMD_INFO`，理论上索引保持一致。
- `g_argumentInfo_dp1_global_var` 的 14 项与各命令参数偏移/数量在源码表面一致。
- `g_DataType_dp1_global_var_count` 明确为 0；常量计数按数组大小计算为 2。
- 动态入口和 `.def` 文件文本上都指向 `GetNewInf`。

### 9.3 未验证项

压缩算法是否使用 zlib/自研实现、MD5 具体实现、DES/RC4 模式、RSA 填充/编码格式、错误处理、返回值内存所有权、Windows 下的 ABI 对齐、DLL 加载、静态链接和真实易语言运行时兼容性，源码当前都没有实现或测试证据，统一标记为“未确认”。

## 10. 后续复核建议

1. 在 Windows + Visual Studio v141/对应 SDK 上分别复核 Win32 Debug/Release 动态库和静态库构建；先处理 x64 宏、`.def`、目标扩展和 PCH 配置风险。
2. 补充以易语言运行时为宿主的装载烟测：调用 `GetNewInf`，检查 GUID/版本/命令计数/命令名/函数表/常量表。
3. 在实现命令前先冻结 `pRetData`、易语言内存分配、`SDT_BIN` 数据格式、错误返回和可选参数契约；禁止只补算法而不补 ABI 所有权。
4. 为 7 个命令分别建立正常输入、空数据、非法参数、缺省加密算法、错误密钥/签名和内存释放用例，并覆盖 Debug/Release 与 Win32/x64。
5. 若目标是恢复原库功能，应从可信历史版本或同系列实现获取算法证据；当前初始化提交的函数体不能作为算法实现依据。

## 11. 结论分级

```text
已证实：易语言支持库 ABI 骨架、GetNewInf 入口、7 个命令元数据、2 个算法常量、无自定义数据类型、动态/静态双工程、系统通知桥接。
已证实：当前 7 个命令函数体没有真正写回结果，因此“声明支持压缩/加密/RSA”不等于“当前代码可执行这些能力”。
未确认：Windows 构建、x64 配置是否可用、DLL 实际装载、算法实现、返回值内存所有权和易语言运行时端到端行为。
后续只维护：本 ARCHITECTURE.md；当前核对未发现旧细探文件，不删除任何源码或其他文档。
```
