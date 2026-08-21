# ecalc 架构档案

## 1. 项目定位

`ecalc` 是 Gitee `JYtechnology/ecalc` 的易语言数值计算支持库源码，目标形态是供易语言 IDE/运行时加载的 Windows 支持库动态库（`.fne`），并同时提供静态库工程。库元数据将自身声明为“数值计算支持库”，版本为 `2.3.0`，提供复数、矩阵、FFT、微积分、统计、方程组、回归/曲线拟合、特殊函数和“大数”对象等命令。

**当前源码状态必须单独说明：**仓库中的命令实现文件是接口生成骨架，不是可运行的数值算法实现。`ecalc_cmdDef.cpp` 共定义 112 个命令入口；其中 28 个函数体为空，另外 84 个函数体仅从 `pArgInf` 提取局部参数，未调用算法、未写入 `pRetData` 或输出参数、没有返回语句。因而“支持库元数据声称提供的能力”和“本仓库当前源码真正能执行的能力”并不相同。

## 2. 代码流程图

```text
易语言 IDE / 编译器 / 运行时
          │
          │ LoadLibrary / 静态编译登记
          ▼
  ecalc 动态库（ecalc.vcxproj）或 ecalc_static 静态库
          │
          ├── GetNewInf()
          │       └── LIB_INFO
          │             ├── g_DataType_ecalc_global_var（11 个自定义类型）
          │             ├── g_cmdInfo_ecalc_global_var（112 条命令元数据）
          │             ├── g_cmdInfo_ecalc_global_var_fun（112 个函数指针）
          │             ├── g_ConstInfo_ecalc_global_var（当前 0 个常量）
          │             └── ecalc_ProcessNotifyLib_ecalc
          │
          ├── 命令调用
          │       └── 函数指针数组按命令索引分发
          │             └── ecalc_<英文名>_<索引>_ecalc(pRetData, nArgCount, pArgInf)
          │                   └── 当前仅参数提取/空函数体，未形成计算闭环
          │
          ├── 自定义类型登记
          │       ├── 复数运算（ComplexCalc）
          │       └── 大数（UnlNum）
          │             └── 隐藏构造/析构/复制命令（当前也为空）
          │
          └── 系统通知
                  └── ecalc_ProcessNotifyLib_ecalc
                        └── elib/fnshare.cpp::ProcessNotifyLib
                              └── 保存宿主通知函数指针、转发用户通知
```

## 3. 真实目录与职责

仓库当前 Git 清单为 23 个文件，无 README、无测试目录、无 CI 配置、无额外源码依赖目录。

| 路径 | 实际职责 |
|---|---|
| `ecalc.sln` | Visual Studio 解决方案，包含 `ecalc` 动态库工程和 `ecalc_static` 静态库工程；配置为 Debug/Release、Win32/x64。 |
| `ecalc.vcxproj` | 动态库工程；Win32 配置目标扩展为 `.fne`，通过 `Source_ecalc.def` 导出 `GetNewInf`。 |
| `ecalc_static/ecalc_static.vcxproj` | 静态库工程；复用根目录的 `.cpp/.h`，以 `__E_STATIC_LIB` 区分静态编译分支。 |
| `Source_ecalc.def` | 动态库导出文件，仅导出 `GetNewInf`。 |
| `include_ecalc_header.h` | 项目统一头文件；引入 `elib` ABI、语言/核心库定义和命令宏声明，声明全局元数据数组。 |
| `ecalc_cmd_typedef.h` | 命令单一描述表 `ECALC_DEF(_MAKE)`；通过宏复用生成函数声明、命令名、命令元数据和函数指针表。 |
| `ecalc_cmdInfo.cpp` | 112 条命令共用的参数描述数组 `g_argumentInfo_ecalc_global_var`，索引 0—181 共 182 项；生成 `CMD_INFO` 数组。 |
| `ecalc_cmdDef.cpp` | 112 个 `PFN_EXECUTE_CMD` 形态的命令入口；当前均未实现业务算法。 |
| `ecalc_dtType.cpp` | 11 个易语言自定义数据类型的命令索引与成员描述；实现复数和大数的隐藏句柄成员登记。 |
| `ecalc_dllMain.cpp` | DLL 入口空壳、`LIB_INFO`、命令函数指针数组、静态编译函数名数组、`GetNewInf` 和系统通知处理。 |
| `ecalc_const.cpp` | 常量表；当前定义空表，数量为 0。 |
| `elib/lib2.h` | 易语言支持库 ABI 核心定义：`LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`MDATA_INF`、数据类型和通知常量。 |
| `elib/mtypes.h` | Windows/易语言兼容基础类型、整数/句柄别名、`MAKELONG` 等宏。 |
| `elib/fnshare.h/.cpp` | 支持库与易语言系统通信、宿主内存申请释放、数组/文本/字节集辅助、通知转发。 |
| `elib/lang.h` | 编译语言版本定义；当前为 `__GBK_LANG_VER`。 |
| `elib/krnllib.h` | 系统核心支持库类型和版本常量；声明所需核心版本相关宏。 |
| `elib/untshare.h` | 通用窗口/组件支持库辅助定义，本项目当前未在项目源文件中形成独立业务调用链。 |
| `elib/PublicIDEFunctions.h` | IDE 公共函数/信息宏定义，本项目工程将其作为公共头文件纳入。 |

## 4. 分层与模块关系

### 4.1 宿主适配层：易语言支持库 ABI

`elib/lib2.h` 是外部宿主协议边界。命令统一采用：

```cpp
void (*PFN_EXECUTE_CMD)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf);
```

`MDATA_INF` 使用一字节结构对齐（`#pragma pack(1)`），内部是一个联合体，覆盖：

- 基本值：`m_byte`、`m_short`、`m_int`、`m_int64`、`m_float`、`m_double`、`m_bool` 等；
- 只读文本/字节集：`m_pText`、`m_pBin`；
- 复合数据和数组：`m_pCompoundData`、`m_pAryData`；
- 传引用输出指针：`m_pInt`、`m_pDouble`、`m_pBool`、`m_ppCompoundData` 等；
- `m_dtDataType`：参数/返回数据类型和数组/变量标志。

实现命令不能自行假定普通 C++ 返回值，而必须按照 `CMD_INFO.m_dtRetValType`、`ARG_INFO.m_dtType` 和 `ARG_INFO.m_dwState` 与宿主交换数据。当前命令入口没有完成这一协议的写回部分。

### 4.2 元数据编译层

`ecalc_cmd_typedef.h` 是实际的元数据单一描述源。`ECALC_DEF(_MAKE)` 被不同宏展开为：

1. `include_ecalc_header.h` 中的函数声明；
2. `ecalc_cmdInfo.cpp` 中的 `CMD_INFO` 命令元数据；
3. `ecalc_dllMain.cpp` 中的命令函数指针数组；
4. `ecalc_dllMain.cpp` 中给静态编译使用的函数名字符串数组。

因此命令索引是 ABI 级契约，不能只改某一个生成结果。当前发现的元数据可疑重复包括：

- 索引 14“复矩阵相乘”和索引 16“复矩阵相加”都使用英文标识 `CMatrixMul`；
- 索引 65“导入文本文件”和索引 66“导出文本文件”都使用英文标识 `ImportTxtFile`，索引 66 的实现入口也命名为 `ecalc_ImportTxtFile_66_ecalc`；
- 这些名称带索引后仍能形成不同的 C 符号，但会造成静态编译函数名、调试/工具显示和后续维护歧义。

### 4.3 自定义数据类型层

`ecalc_dtType.cpp` 登记 11 个类型：

1. `复数运算 / ComplexCalc`：索引 0—12，并含复制构造索引 111；有一个隐藏成员 `复数存储句柄 / ComplexHandle`，类型为 `SDT_INT`。
2. `矩阵运算 / MatrixCalc`：索引 13—23。
3. `傅立叶变换 / FourierTransform`：索引 24—28。
4. `微积分 / Calculous`：索引 29—31。
5. `概要统计 / SummaryStats`：索引 32。
6. `联立方程 / GaussJordan`：索引 33—34。
7. `多重回归 / MultipleReg`：索引 35，类型标记为隐藏。
8. `曲线拟合 / CurveFit`：索引 36—38。
9. `其他计算 / OtherCalc`：索引 39—61。
10. `大数 / UnlNum`：索引 62—108，并含复制构造索引 110；有一个隐藏成员 `大数运算句柄 / UnlNumHandle`，类型为 `SDT_INT`。
11. `算式解析 / ExpressionParse`：索引 109。

所有类型的操作系统标记当前通过 `_DT_OS(__OS_WIN)` 声明为 Windows；源码没有实现句柄分配、释放或对象内部数据结构。

### 4.4 运行时入口与通知层

`ecalc_dllMain.cpp` 的动态库入口为：

- `GetNewInf()`：返回静态 `LIB_INFO g_LibInfo_ecalc_global_var`；
- `DllMain()`：四类 DLL 生命周期通知均为空，仅返回 `TRUE`；
- `ecalc_ProcessNotifyLib_ecalc()`：处理宿主通知。

已实现的通知分支：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNamesecalc`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `"ecalc_ProcessNotifyLib_ecalc"`；
- `NL_GET_DEPENDENT_LIBS`：返回双零结尾空依赖字符串；
- `NL_SYS_NOTIFY_FUNCTION`：转发到 `elib/fnshare.cpp::ProcessNotifyLib`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 未识别通知返回 `NR_ERR`。

`elib/fnshare.cpp` 保存宿主的 `PFN_NOTIFY_SYS`，并维护 `s_isDebug`。首次收到系统通知函数时通过 `NRS_GET_PRG_TYPE` 获取程序类型；用户可通过 `SetUserSysNotify` 注册额外通知回调。`ealloc/efree` 通过 `NotifySys` 请求宿主内存服务，不能脱离易语言运行时视为普通堆分配器。

## 5. 命令/API 边界

### 5.1 支持库导出边界

动态库外部导出仅在 `Source_ecalc.def` 中声明：

```text
GetNewInf
```

`GetNewInf` 返回 `LIB_INFO`，其关键字段为：

| 字段 | 当前值/来源 |
|---|---|
| 格式 | `LIB_FORMAT_VER`（`20000101`） |
| GUID | `306AA9E31B5940399723021A0D782077` |
| 版本 | 主版本 `2`、次版本 `3`、构建号 `0` |
| 所需易语言系统 | `3.7` |
| 所需核心支持库 | `3.7` |
| 名称 | `数值计算支持库` |
| 语言 | `__GBK_LANG_VER` |
| 操作系统 | `_LIB_OS(OS_ALL)`，但命令/自定义类型实际宏使用 Windows 标记 |
| 作者 | `大有吴涛易语言软件公司` |
| 命令数 | `g_cmdInfo_ecalc_global_var_count`，源码表为 112 |
| 自定义类型数 | `g_DataType_ecalc_global_var_count`，源码表为 11 |
| 常量数 | `g_ConstInfo_ecalc_global_var_count`，源码值为 0 |
| 外部依赖文件 | `NULL` |

### 5.2 命令域清单

| 领域 | 命令索引 | 数量 | 主要数据形态 |
|---|---:|---:|---|
| 复数运算 | 0—12、111 | 14 | 复合对象、复数数组、双精度数；111 为复制构造 |
| 矩阵运算 | 13—23 | 11 | 实数/复数数组、标量、引用输出；多个命令声明返回数组 |
| 傅立叶变换 | 24—28 | 5 | 实部/虚部数组原地输入输出、点数、窗口和时间间隔 |
| 微积分 | 29—31 | 3 | 数组积分、区间积分、一阶微分方程与引用输出 |
| 概要统计 | 32 | 1 | 二维原始数据和十组统计数组 |
| 联立方程 | 33—34 | 2 | 实数/复数系数矩阵、解向量、逆阵和行列式 |
| 多重回归 | 35 | 1 | 原始二维数据、多组结果数组与引用输出 |
| 曲线拟合 | 36—38 | 3 | 多项式/样条数组、插值值和引用输出 |
| 其他计算 | 39—61 | 23 | 双曲函数、Gamma/Beta/Bessel、误差函数和正交多项式 |
| 大数 | 62—108、110 | 48 | 句柄复合对象、文本/数字导入导出、任意精度运算 |
| 算式解析 | 109 | 1 | 表达式文本、积分上下限、误差和结果引用 |

隐藏命令共 15 个，主要是对象构造/析构/复制、复数/复矩阵内部操作、复数方程组、部分大数转换/幂运算。隐藏不等于已实现：当前这些入口同样为空或仅提取参数。

### 5.3 参数与返回契约

`ecalc_cmdInfo.cpp` 定义 182 个 `ARG_INFO` 槽位（索引 0—181），命令通过 `g_argumentInfo_ecalc_global_var + 起始偏移` 引用连续参数段。参数描述包含：中文名、解释、`DATA_TYPE`、默认值、数组/引用/变量限制。

已声明的典型输入输出契约：

- 实数计算采用 `SDT_DOUBLE`；整数/布尔/文本分别采用 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`；
- 复合复数数据采用 `MAKELONG(0x01, 0)`，大数对象采用 `MAKELONG(0x0A, 0)`；
- 数组参数通常使用 `AS_RECEIVE_ARRAY_DATA`，引用结果使用 `AS_RECEIVE_VAR`；
- FFT、矩阵、统计、回归和样条命令大量使用“输入数组原地改写/输出数组由引用参数提供”的设计；
- 默认值在源码明确出现的包括：忽略非法字符为真、覆盖现有为真、大数除法精度为 1、舍入位置为 0、计算精度为 3；
- Gamma、Beta、Bessel、正交多项式族使用引用参数返回错误码；
- 元数据中声明的错误码语义只存在于参数说明文本，当前命令实现没有执行校验或赋值。

## 6. 真实调用链

### 6.1 动态库加载和登记

```text
宿主加载 ecalc.fne
  → 查找导出 GetNewInf
  → GetNewInf() 返回 LIB_INFO*
  → 读取 m_pDataType / m_pBeginCmdInfo / m_pCmdsFunc
  → 按命令索引建立易语言命令和对象成员映射
  → 调用 m_pfnNotify(ecalc_ProcessNotifyLib_ecalc)
  → 发送 NL_SYS_NOTIFY_FUNCTION
  → fnshare.cpp 保存宿主 PFN_NOTIFY_SYS
```

### 6.2 命令调用

```text
易语言程序调用某命令
  → 宿主根据 CMD_INFO 校验参数形态
  → 取 m_pCmdsFunc[命令索引]
  → 调用 ecalc_<英文名>_<索引>_ecalc(pRetData, nArgCount, pArgInf)
  → 命令入口从 pArgInf[1..nArgCount] 读取 m_double/m_int/m_pAryData/引用指针等
  → 【当前缺失】执行数值算法、分配/释放对象数据、写入 pRetData 和引用输出
  → 【当前实际】函数返回，输出数据未被实现层设置
```

### 6.3 宿主内存/数组辅助链

```text
命令实现（未来需要对象或数组存储）
  → ealloc / efree / allocArray / CloneTextData / CloneBinData
  → fnshare.h 辅助函数
  → NotifySys(NRS_MALLOC/NRS_MFREE/其他系统消息)
  → 易语言运行时内存与数据管理
```

当前命令实现没有真正调用这条链；构造、析构、复制命令也为空，因此复数句柄和大数句柄的生命周期尚未闭合。

## 7. 数据、状态与持久化

本项目不是服务型应用，没有数据库、配置文件、网络 API、任务队列或持久化文件格式。运行时状态理论上全部位于：

1. 易语言宿主传入的 `MDATA_INF`；
2. 复数/大数自定义类型的 `m_pCompoundData` 所指向的运行时对象数据；
3. 宿主通过 `NotifySys` 提供的内存和系统通知状态；
4. `fnshare.cpp` 的静态进程内变量 `s_pfnNotifySys`、`s_pfnuserNotifySys`、`s_isDebug`。

`ecalc_dtType.cpp` 只登记隐藏句柄成员为 `SDT_INT`，没有定义句柄指向的结构、所有权、容量、精度、异常状态或销毁规则。`ecalc_cmdDef.cpp` 中也没有对象状态读写。因此当前仓库不存在可据源码确认的数值对象数据模型或持久化协议；只能确认其 ABI 预留形态。

## 8. 技术栈与依赖边界

| 类别 | 事实 |
|---|---|
| 语言 | C/C++，源文件为 `.cpp/.h`，中文注释和 GBK 编码内容较多 |
| 构建系统 | Visual Studio `.sln/.vcxproj`，PlatformToolset `v141` |
| 目标平台 | 设计上 Windows；代码依赖 `windows.h`、Win32 类型和 Windows DLL ABI |
| 动态产物 | Win32 配置声明 `.fne`，通过 `.def` 导出 `GetNewInf` |
| 静态产物 | `ecalc_static`，与动态目标复用同一批源码 |
| 标准库/系统库 | `stdio.h`、`math.h`、`assert.h`、`windows.h` 等，算法库未在本仓库另行提供 |
| 宿主依赖 | 易语言运行时、系统核心支持库版本 3.7 兼容接口、`NotifySys` 内存/通知协议 |
| 第三方依赖 | `LIB_INFO.m_szzDependFiles = NULL`；仓库未提供第三方静态库 |
| 外部服务 | 无 |
| 数据库/文件存储 | 无；仅支持库自身元数据和宿主内存 |

### 工程配置风险

以下结论来自工程文件静态检查，未通过构建验证：

1. `ecalc.vcxproj` 的 Debug/Release Win32 配置定义了 `__E_FNENAME=ecalc` 并指定 `Source_ecalc.def`；两个 x64 配置均没有 `__E_FNENAME=ecalc`，而 `elib/lib2.h` 明确在未定义时 `#error`，因此 x64 编译路径存在确定的预处理阻断。
2. 动态库 x64 配置没有 `ModuleDefinitionFile`，而源代码没有看到 `__declspec(dllexport)`；如果不由其他工程设置补充导出，`GetNewInf` 的 DLL 导出存在风险。
3. `ecalc_static` 的 Debug/Release Win32 配置定义了 `__E_STATIC_LIB;__E_FNENAME=ecalc`；两个 x64 配置均未定义这两个宏，且配置写为 `PrecompiledHeader=Use`、`PrecompiledHeaderFile=pch.h`，仓库清单没有 `pch.h`，需要单独复核。
4. 根目录只有 Windows 工程配置，macOS/Linux 环境不能直接验证宿主 ABI或构建结果。
5. `elib/lib2.h` 中 `MDATA_INF` 使用一字节对齐，任何迁移到其他编译器/架构都必须保持 ABI 兼容，不能只按普通 C++ 结构体默认对齐处理。

## 9. 测试、验证与发布现状

### 9.1 仓库内现状

- 未发现测试目录、测试源文件、测试夹具、CI 工作流或发布脚本；
- 没有 README 或使用示例；
- 没有可据源码复现的算法正确性验证；
- 没有可确认 DLL 加载、`GetNewInf` 导出、命令分发和对象生命周期的自动化测试；
- `ecalc_cmdInfo.cpp` 仅在 `_DEBUG` 下定义 `dbg_cmd_arg_count__`，用于开发者确认参数索引数量，但仓库没有断言测试消费它。

### 9.2 本轮已执行的只读验证

本轮遵守“不安装、不构建、不改源码、不提交 Git”的边界，仅执行了现场盘点和静态读取：

- 读取全部 23 个 Git 跟踪文件及工程配置；
- 统计 `ecalc_cmd_typedef.h` 的 `_MAKE` 条目：112 条，索引连续 0—111；
- 统计 `ecalc_cmdDef.cpp`：112 个入口，28 个空函数体，84 个仅参数提取，0 个函数调用，0 个 `pRetData` 写入；
- 统计 `ecalc_cmdInfo.cpp` 参数描述：182 项，索引 0—181；
- 核对 `ecalc_dtType.cpp`：11 个自定义数据类型、2 个隐藏句柄成员类型；
- 核对 Git 状态、分支、提交、远程和远程 HEAD；
- 未执行 Visual Studio/MSBuild、Windows DLL 加载、易语言运行时调用或任何安装操作。

### 9.3 后续可验证项

若后续任务要把它从骨架推进为可运行支持库，应按顺序补充：

1. 先修复 Win32/x64 工程宏、导出和预编译头配置；
2. 固定命令索引和元数据重复命名问题；
3. 明确复数/大数内部结构与宿主内存所有权；
4. 实现构造、析构、复制及每个数值算法入口；
5. 对所有 `pRetData`、引用输出、数组形状和错误码建立测试；
6. 在 Windows + 易语言宿主环境中验证 `GetNewInf`、通知回调、动态加载和静态编译两条链；
7. 对 FFT 点数约束、矩阵维度、奇异矩阵、积分边界、特殊函数域限制、大数精度和文件导入导出建立边界测试。

## 10. 风险、未确认项与边界

### 已确认风险

- 公开命令接口与实现状态严重不一致：接口声明了 112 个数值/大数命令，但当前入口不执行计算；
- 构造/析构/复制入口为空，复数和大数对象生命周期不成立；
- 复数/大数隐藏句柄仅有 `SDT_INT` 成员声明，没有内部结构和释放协议；
- 元数据存在英文名重复和索引 66“导出”仍名为 `ImportTxtFile` 的一致性问题；
- x64 工程配置缺少关键宏，静态 x64 还存在预编译头配置缺口；
- 没有自动化测试和 Windows 宿主验证，不能把编译通过或元数据存在当作功能完成。

### 未确认项

- 上游 `JYtechnology/ecalc` 是否在该初始化提交之后存在未同步的历史实现；当前本地仓库为浅克隆，`master` 与 `origin/master` 均停在同一个初始化提交 `492603fce0104282cc96e5e54fed7a9a54574f82`，远程 HEAD 也指向该提交；
- `elib` 头文件来自哪一版易语言 SDK，以及其与目标宿主具体版本的 ABI 兼容矩阵；
- 复数/大数句柄的预期内部内存布局和算法来源；
- `ecalc_cmdDef.cpp` 是否是特意保留的命令生成模板，还是不完整提交；
- x64 工程是否由外部 `.props`、环境或未纳入仓库的 `pch.h` 补齐配置。

### 旧细探核对

目标项目根目录未发现 `细探-*.md` 或其他旧架构文档；在源码参考库范围按 `ecalc` 文件名检索也未发现与本项目对应的旧细探文件。本文件因此直接以当前源码、工程文件和 Git 远程基线为唯一事实源。

## 11. Git 与版本基线

| 项目 | 当前事实 |
|---|---|
| 本地路径 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/ecalc` |
| 分支 | `master` |
| HEAD | `492603fce0104282cc96e5e54fed7a9a54574f82` |
| 提交时间 | `2022-12-19 16:54:45 +0800` |
| 提交说明 | `初始化仓库` |
| 远程 | `https://gitee.com/JYtechnology/ecalc.git` |
| 远程默认分支 | `master` |
| 远程 HEAD | 与本地 HEAD 相同：`492603fce0104282cc96e5e54fed7a9a54574f82` |
| 工作树 | 建档前为 clean；本轮只新增本文件，未修改已有源码、工程或 Git 提交 |

本文件是 ecalc 根目录唯一架构事实源。后续深挖应直接增量更新本文件，不再新建平行“细探”架构文档。
