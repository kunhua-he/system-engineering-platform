# espeechengine 架构档案

> 首轮全量架构建档。本文是本仓库唯一架构事实文档；源码、工程文件和 Git 历史保持只读。本轮未修改源码、未安装依赖、未构建、未运行宿主，也未提交 Git。

## 1. 项目定位与结论

`espeechengine` 是面向易语言支持库 ABI 的 Windows 语音支持库工程，目标是在易语言中提供文本转语音、WAV 输出、发音控制、语音库选择以及语音识别组件接口。仓库实现的是易语言支持库的元数据/导出/回调骨架，当前提交中的业务命令和语音识别组件仍是模板或未完成实现：命令函数体基本只读取参数或为空，未发现 SAPI、COM、`SpVoice`、Speech SDK 头文件、语音对象创建或识别回调的实际调用。

因此必须区分：

- **契约层已声明**：易语言命令名、英文内部名、参数、返回类型、对象/组件/枚举元数据和 Windows 限制。
- **执行层未落地**：命令函数没有给 `pRetData` 写入结果，没有播放、WAV 生成、暂停/恢复、枚举语音库或识别训练逻辑；识别组件创建函数返回 `0`。
- 根文件 `espeechengine_dllMain.cpp` 的库说明宣称依赖 Microsoft Speech SDK 5.1 或 Microsoft Office，但该依赖未随仓库提供，源码中也没有对应调用证据。

## 2. 真实版本基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/espeechengine` |
| 本地分支 | `master` |
| HEAD | `2c92b9eb99bf77d834f5291c7d9cc842ca06aaca` |
| HEAD 提交 | `初始化仓库`，`2022-12-19T16:07:57+08:00` |
| 远程 | `https://gitee.com/JYtechnology/espeechengine.git` |
| 远程 HEAD | `origin/master`，现场 `git ls-remote` 与本地 HEAD 同为 `2c92b9eb99bf77d834f5291c7d9cc842ca06aaca` |
| 标签 | 无 |
| Git 状态 | 初始盘点时工作树干净；本文件写入后仅产生本架构文档未跟踪变更 |
| Git 形态 | 当前浅克隆，历史仅能看到一个 grafted 初始化提交 |
| 仓库规模 | Git 跟踪文件 23 个；工作树约 432K；源码/工程文件总计约 432K |
| 代码图 | 目标目录无 `.codegraph/`，`codegraph_explore` 明确返回未建立索引；未以索引结果替代源码取证 |
| 旧细探 | 在本项目目录及其易语言源码仓库范围内未发现 `*细探*` 文件 |

本地与远程基线已核对，但没有执行 `fetch`；远程 HEAD 已通过 `git ls-remote` 读取，未发现版本漂移。

## 3. 运行/装载总流程

```text
Visual Studio / MSBuild
        │
        ├─ espeechengine.vcxproj ──> Windows DLL（目标扩展名 .fne，Win32 配置）
        │                              │
        │                              └─ 导出 GetNewInf
        │
        └─ espeechengine_static/espeechengine_static.vcxproj
                         └─> 静态库（__E_STATIC_LIB 分支，供静态编译）

易语言系统加载 .fne
        │
        ├─ GetNewInf()
        │    └─ 返回 g_LibInfo_espeechengine_global_var
        │         ├─ 支持库版本 2.0.0
        │         ├─ Windows 标志、GBK 语言标志
        │         ├─ 17 个命令元数据
        │         ├─ 3 个自定义数据类型描述
        │         └─ 命令实现函数指针表
        │
        ├─ NL_SYS_NOTIFY_FUNCTION
        │    └─ espeechengine_ProcessNotifyLib_espeechengine
        │         └─ ProcessNotifyLib()
        │              ├─ 保存宿主通知函数
        │              └─ 首次查询 NRS_GET_PRG_TYPE，记录调试/运行类型
        │
        ├─ 编译器按 g_cmdInfo_* 元数据解析命令
        │    └─ 通过宏拼接的 espeechengine_<英文名>_<序号>_espeechengine 符号调用
        │
        └─ 命令/组件执行
             ├─ 文本转语音命令：当前函数体未调用语音后端，未写返回值
             ├─ 语音识别组件：创建函数返回 0，属性/事件实现为占位逻辑
             └─ 释放/卸载：DllMain 与通知分支没有业务资源释放逻辑
```

## 4. 目录与文件地图

```text
espeechengine/
├── ARCHITECTURE.md                         # 本文，首轮架构事实源
├── espeechengine.sln                        # VS 解决方案，DLL + 静态库两个项目
├── espeechengine.vcxproj                    # 动态库工程
├── espeechengine.vcxproj.filters/.user      # VS 过滤器/用户配置
├── espeechengine_static/
│   ├── espeechengine_static.vcxproj         # 静态库工程，引用上级源码
│   ├── *.filters                            # VS 过滤器
│   └── *.user                               # VS 用户配置
├── Source_espeechengine.def                 # DLL 仅导出 GetNewInf
├── include_espeechengine_header.h           # 统一头文件、全局元数据声明、命令原型宏
├── espeechengine_cmd_typedef.h              # 17 条命令的唯一宏定义清单
├── espeechengine_cmdInfo.cpp                # 命令参数描述与 CMD_INFO 数组
├── espeechengine_cmdDef.cpp                 # 17 个命令执行入口；当前绝大多数是空实现
├── espeechengine_dtType.cpp                 # 自定义数据类型、对象命令索引、组件接口/属性/事件
├── espeechengine_const.cpp                  # 常量表，占位为空（数量 0）
├── espeechengine_dllMain.cpp                # DLL 生命周期、LIB_INFO、导出入口、通知处理
└── elib/
    ├── lib2.h                               # 易语言支持库 ABI 基础类型、命令/数据/库结构
    ├── fnshare.h/.cpp                       # 宿主通知、内存、数组/文本辅助与通知转发
    ├── krnllib.h                            # 系统核心支持库常量
    ├── lang.h                               # GBK/英语/BIG5/SJIS 语言版本常量
    ├── mtypes.h                             # 非 Windows/静态场景的类型兼容定义
    ├── untshare.h                           # 窗口单元辅助声明与元数据掩码
    └── PublicIDEFunctions.h                 # IDE 辅助函数编号/结构声明
```

## 5. 技术栈与构建工程

| 层 | 事实 |
|---|---|
| 语言 | C/C++，源码文件为 `.cpp/.h`；中文注释/元数据采用 GBK/扩展 ASCII 兼容编码，普遍 CRLF |
| IDE/构建 | Visual Studio Solution Format 12；`VCProjectVersion=16.0`；工程使用 MSVC `v141` 工具集 |
| 目标系统 | `__OS_WIN`；工程声明 Windows 10 SDK `10.0.15063.0`；DLL 与静态库均有 Win32/x64 配置 |
| 动态产物 | `ConfigurationType=DynamicLibrary`；Win32 配置的 `TargetExt=.fne`；`.def` 导出 `GetNewInf` |
| 静态产物 | `espeechengine_static` 为 `StaticLibrary`，Win32 Debug/Release 定义 `__E_STATIC_LIB` 和 `__E_FNENAME=espeechengine` |
| ABI | 易语言支持库 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`PFN_EXECUTE_CMD`、组件 `PFN_INTERFACE` |
| 依赖 | 仓库内自带 `elib` ABI 头/辅助源码；工程未声明第三方库链接项；`NL_GET_DEPENDENT_LIBS` 返回空依赖列表 |
| 语音后端 | 库说明要求 MS Speech SDK 5.1 或 Office 可提供语音组件，但本仓库未包含 SDK/运行库，也没有实际 API 调用证据 |
| 持久化 | 无数据库、配置文件、模型文件或本仓库自有持久化格式 |
| 测试 | 未发现测试目录、测试工程、CI 配置或自动化验证脚本 |

### 5.1 已观察到的工程配置风险

- `espeechengine.vcxproj` 的 Win32 配置明确设置 `__E_FNENAME=espeechengine`，而 x64 DLL 配置没有同等定义，且 x64 配置没有看到 Win32 使用的 `ModuleDefinitionFile`；静态库 x64 配置也未显示 `__E_STATIC_LIB`/`__E_FNENAME`。这些是工程文件事实，是否由外部属性表补齐、以及 x64 是否能成功构建，尚未在 Windows/MSBuild 上验证。
- `lib2.h` 强制要求先定义 `__E_FNENAME`；若 x64 配置没有从外部环境继承该宏，理论上会在预处理阶段失败。
- `elib` 中的 Windows 类型兼容层和回调参数大量使用 `DWORD` 承载指针/函数地址，x64 ABI 的指针宽度问题需要在目标 Windows 编译器和易语言宿主下专门验证，不能仅凭当前工程存在 x64 配置就判定可用。

## 6. 对外 ABI、入口与调用契约

### 6.1 DLL/静态库入口

- `Source_espeechengine.def` 只导出 `GetNewInf`。
- `espeechengine_dllMain.cpp::GetNewInf()` 返回静态 `LIB_INFO g_LibInfo_espeechengine_global_var`。
- `LIB_INFO` 关键值：库 GUID `4AA6F3ADE9264fbe8B618A1FCD60364F`；版本 `2.0.0`；要求易语言系统 `3.7`、核心支持库 `3.7`；库名“文本语音转换支持库”；语言 `__GBK_LANG_VER`；操作系统 `_LIB_OS(__OS_WIN)`。
- `g_cmdInfo_espeechengine_global_var_fun` 与 `g_cmdInfo_espeechengine_global_var` 按同一 `ESPEECHENGINE_DEF` 宏生成，依靠同序命令表配对。
- `__E_STATIC_LIB` 分支不编译动态库元数据表，改用 `g_cmdNamesespeechengine` 返回静态编译所需的实现函数名；但其 x64 宏配置仍需验证。

### 6.2 17 条命令

| 序号 | 易语言名 | 内部名/导出符号中段 | 返回 | 参数 | 语义声明 | 当前实现取证 |
|---:|---|---|---|---:|---|---|
| 0 | 创建 | `StartSpeech` | 空 | 0 | 隐藏对象构造命令，旧代码兼容保留 | 空函数 |
| 1 | 释放 | `CloseSpeech` | 空 | 0 | 隐藏对象析构命令，旧代码兼容保留 | 空函数 |
| 2 | 文本到语音 | `Speek` | `SDT_BOOL` | 4 | 数据类别、发音数据、可选等待超时、可选事件标签 | 只读取 `arg1..arg4`，未执行/未写返回值 |
| 3 | 输出声音文件 | `SpeekToWav` | `SDT_BOOL` | 3 | 数据类别、发音数据、WAV 文件名，同步执行 | 只读取 `arg1..arg3`，未执行/未写返回值 |
| 4 | 停止发音 | `StopSpeek` | `SDT_BOOL` | 0 | 停止发音 | 空函数 |
| 5 | 暂停发音 | `PauseSpeek` | `SDT_BOOL` | 0 | 暂停发音 | 空函数 |
| 6 | 恢复发音 | `ResumeSpeek` | `SDT_BOOL` | 0 | 恢复发音 | 空函数 |
| 7 | 设置声音大小 | `SetVolume` | `SDT_BOOL` | 1 | 音量 0 到 100 | 只读取 `arg1`，未校验/未执行 |
| 8 | 设置语速 | `SetRate` | `SDT_BOOL` | 1 | 语速 -10 到 10 | 只读取 `arg1`，未校验/未执行 |
| 9 | 列举语音库 | `EnumAllVoice` | `SDT_TEXT` + 数组标志 | 0 | 返回系统安装的语音库名称数组 | 空函数 |
| 10 | 设置语音库 | `SetVoice` | `SDT_BOOL` | 1 | 按名称设置语音库 | 只读取文本参数，未执行 |
| 11 | 创建 | `SetUpSR` | `SDT_BOOL` | 2 | 语音识别引擎（中文/英文）、作用域（系统/程序） | 只读取两个整数，未执行 |
| 12 | 释放 | `ReleaseSR` | `SDT_BOOL` | 0 | 释放识别引擎 | 空函数 |
| 13 | 训练 | `Training` | `SDT_BOOL` | 0 | 训练识别系统 | 空函数 |
| 14 | 加入常用 | `AddWord` | `SDT_BOOL` | 1 | 加入字/词/句数组 | 只读取数组指针，未执行 |
| 15 | 是否可用 | `IsValid` | `SDT_BOOL` | 0 | 查询文本转语音引擎初始化可用性 | 空函数 |
| 16 | 重新创建并初始化 | `ReCreateAndInit` | `SDT_BOOL` | 0 | 重新创建/初始化 | 空函数 |

说明：`Speek`、`SpeekToWav`、`StopSpeek` 等拼写是源码公开内部名，属于兼容契约，不能在后续整理中擅自改为 `Speak`。

### 6.3 参数契约

- `数据类别`：0=字符串，1=文本文件名，2=XML 文件名。
- `发音数据`：根据 `数据类别` 解释为文本、文本文件或 XML 文件。
- `等待超时`：大于 0 等待至结束或超时；小于 0 无限等待；等于 0/省略则启动后台播放后立即返回；单位毫秒；默认空值。
- `事件反馈标签`：可接收类型 1“开始播放”、类型 2“结束播放”的反馈事件；同一时间只保留最近一次指定标签。元数据声明为 `DTP_LABEL`，默认空值。
- `保存文件名`：输出 WAV 的完整文件名。
- `声音大小`：声明范围 0 到 100。
- `语速快慢`：声明范围 -10 到 10。
- `语音库名称`：系统语音库名称。
- `识别引擎`：0 中文，1 英文。
- `作用域`：0 系统作用域，1 程序作用域。
- `字词句数组`：文本数组，设置了 `AS_RECEIVE_ARRAY_DATA`，调用方必须传数组数据。

### 6.4 自定义数据类型、属性与事件

`espeechengine_dtType.cpp` 注册 3 项 `LIB_DATA_TYPE_INFO`：

1. **`机读文本` / `ETextToSpeech`**：Windows 对象类型，自动创建、初始化和销毁的契约描述；命令索引为 `[0, 1, 15, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16]`；保留两个枚举成员，其中一个标为“不再使用，为了向下兼容必须保留”。
2. **`语音识别` / `ESpeechReco`**：Windows 窗口单元/函数提供者类型；命令索引为 `[11, 12, 13, 14]`；有 8 个固定基础属性（左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针）；声明事件“识别到语音”，事件参数 `识别文本` 为 `SDT_TEXT`。
3. **`文本语音常量` / `TextSpeechConst`**：枚举成员 7 个：`字符串=0`、`文本文件名=1`、`XML文件名=2`、`中文识别=0`、`英文识别=1`、`系统作用域=0`、`程序作用域=1`。

组件接口 `espeechengine_GetInterface_ESpeechReco()` 支持创建、属性 UI 更新、定制对话框、属性变更、取全部/单个属性、按键询问和通知接收者等接口号；语言转换、消息过滤、图标属性接口返回空。当前组件实现仍为占位：创建返回 `HUNIT=0`，取全部属性返回 0，按键询问返回 FALSE，通知接收者未实现有效尺寸。

## 7. 关键模块与调用链

### 7.1 命令元数据链

`espeechengine_cmd_typedef.h` 中的 `ESPEECHENGINE_DEF(_MAKE)` 是命令单一清单。它被不同宏展开为：

- `espeechengine_cmdInfo.cpp`：`CMD_INFO` 命令展示/编译元数据；同时维护 13 个 `ARG_INFO` 参数描述。
- `include_espeechengine_header.h`：生成 17 个 `extern "C"` 命令原型。
- `espeechengine_dllMain.cpp`：生成命令函数指针表和静态编译函数名表。
- `espeechengine_cmdDef.cpp`：提供同名的 17 个执行函数。

这套设计通过“一个宏清单、多种展开”避免命令数量和顺序分叉，但也使序号变化、参数数组偏移和函数指针表必须同步维护。

### 7.2 宿主通知/内存辅助链

`espeechengine_dllMain.cpp::espeechengine_ProcessNotifyLib_espeechengine()` 收到易语言通知后：

1. `NL_SYS_NOTIFY_FUNCTION` 调用 `ProcessNotifyLib()`；
2. `elib/fnshare.cpp::ProcessNotifyLib()` 保存宿主 `PFN_NOTIFY_SYS`；
3. 首次通知时调用 `NRS_GET_PRG_TYPE`，把结果记录到静态 `s_isDebug`；
4. `NotifySys()` 将后续请求转发给宿主；
5. `SetUserSysNotify()` 可再挂接一个用户回调，当前仓库没有调用方。

`ealloc/efree`、`CloneTextData`、`CloneBinData` 等辅助函数依赖宿主 `NotifySys` 提供的内存接口；当前语音命令没有使用这些辅助函数。

### 7.3 组件接口链

`LIB_DATA_TYPE_INFO` 的 `espeechengine_GetInterface_ESpeechReco` 根据 `ITF_*` 编号返回函数指针。运行时/IDE 预期链路是“宿主创建窗口单元 → 取/改属性 → 触发事件/通知”，但 `ControlCreate` 没有实际组件句柄或识别引擎实例，因而目前只有接口形状，没有可运行组件。

## 8. 状态、数据模型与持久化

没有发现仓库自有数据库、配置文件、模型文件或磁盘状态。唯一可确认的运行期状态是 `elib/fnshare.cpp` 的进程内静态变量：

- `s_pfnNotifySys`：宿主系统通知回调；
- `s_pfnuserNotifySys`：用户追加通知回调；
- `s_isDebug`：初值为 `1253600`，收到系统通知后经 `NRS_GET_PRG_TYPE` 更新。

未发现文本转语音对象、当前语音库、音量、语速、播放线程、WAV 输出器、识别引擎、训练词表或事件标签的实际状态结构。因此文档中“自动创建/销毁”“退出后训练结果保留”等内容只能视为设计说明，不能视为当前提交的实现事实。

## 9. 风险与未验证项

### 9.1 已由源码直接确认的风险

1. **功能空实现**：17 个命令入口均未完成实际语音逻辑；多个布尔命令没有写 `pRetData`，返回行为不能作为可用功能承诺。
2. **识别组件空实现**：`ControlCreate` 固定返回 0，属性数据不序列化，事件没有产生路径。
3. **参数未校验**：执行函数直接按固定下标读取 `pArgInf`，没有检查 `nArgCount`、空指针、数据类别范围、音量/语速范围或文件名合法性。
4. **组件指针安全**：`espeechengine_PropPopDlg_ESpeechReco` 无条件解引用 `pblModified`；宿主若传空指针会有崩溃风险。
5. **属性返回不完整**：`PropGetData_ESpeechReco` 对基础属性没有实际填值，部分路径仍可能返回 TRUE，容易让宿主误认为属性已成功读取。
6. **外部语音依赖缺失**：库说明中的 Speech SDK/Office 依赖不在仓库，不存在版本、安装探测、错误码和降级策略实现。
7. **ABI/配置分裂**：Win32 与 x64 的预处理宏、导出配置和运行库配置不对称，x64 构建和装载契约未证实。
8. **指针宽度风险**：`DWORD` 被用于通知参数及内存地址传递；在 x64 目标上需要确认宿主 ABI 是否保证安全。
9. **编码风险**：源码/元数据含 GBK 语义，当前取证环境对部分文件显示为乱码；后续编辑必须保留原编码，不能用 UTF-8 重写源码。

### 9.2 本轮未验证项

- 未在 Windows、Visual Studio/MSBuild 或易语言 IDE 中构建。
- 未验证 DLL 是否能成功导出/加载 `GetNewInf`，未验证 `.fne` 产物。
- 未验证静态库的命令名回传与静态编译链接。
- 未安装/检测 Microsoft Speech SDK 5.1、SpeechSDK51LangPack、Office 或其他 SAPI 运行组件。
- 未验证 COM 初始化、线程模型、语音库枚举、播放同步/超时、WAV 输出、暂停/恢复、训练持久化、识别事件和跨进程资源释放。
- 未验证 x64 的 `DWORD` 指针传递、宏缺失、`.def`/导出行为和宿主兼容性。
- 未执行单元测试、集成测试、ABI 测试、静态分析或运行时测试；仓库本身没有发现测试入口。
- 未执行远程 `fetch`；仅读取远程 HEAD，未对历史之外的远程对象做完整同步检查。

## 10. 后续复核顺序

```text
先冻结当前命令/数据类型 ABI
        │
        ├─ 在 Windows + VS v141 验证 Win32 Debug/Release 构建
        ├─ 再单独验证 x64 宏、导出和指针宽度
        ├─ 在隔离 Windows 环境安装/确认 Speech SDK 5.1 或实际替代后端
        ├─ 以最小宿主验证 GetNewInf → 元数据 → 单条命令调用
        ├─ 补齐文本转语音对象生命周期、返回值和错误路径
        ├─ 补齐 WAV/超时/事件标签/语音库/音量/语速
        ├─ 补齐识别组件句柄、属性序列化、事件派发和训练持久化
        └─ 建立 Win32/x64、DLL/静态库、SDK 缺失/宿主异常的回归矩阵
```

以上只是复核路线，不代表本轮已启动实现。

## 11. 证据路径

- `espeechengine_cmd_typedef.h:12-29`：17 条命令清单、命令序号、参数数量、返回类型和 OS/隐藏标志。
- `espeechengine_cmdInfo.cpp:5-57`：13 个参数描述、默认值/数组标志、`CMD_INFO` 生成。
- `espeechengine_cmdDef.cpp:6-141`：17 个执行入口及当前空实现/仅取参事实。
- `espeechengine_dtType.cpp:43-150`：对象/组件/枚举元数据、命令索引、属性、事件。
- `espeechengine_dtType.cpp:154-333`：组件接口分派和占位回调实现。
- `espeechengine_dllMain.cpp:26-99`：命令函数指针、`LIB_INFO`、GUID、版本、Windows/GBK 元数据、依赖声明。
- `espeechengine_dllMain.cpp:101-178`：库通知处理、静态编译函数名和系统通知转发。
- `elib/fnshare.cpp:7-70`、`elib/fnshare.h:20-79`：通知回调、宿主内存辅助、运行类型状态。
- `espeechengine.vcxproj:21-48,51-75,95-199`：源码清单、Win32/x64 工程配置、v141、SDK、DLL/`.fne`。
- `espeechengine_static/espeechengine_static.vcxproj:21-45,48-163`：静态库源码复用、`__E_STATIC_LIB` 配置和 x64 配置差异。
- `Source_espeechengine.def:1-4`：唯一 DLL 导出 `GetNewInf`。
- Git 现场命令：`git log -1`、`git status --short --branch`、`git remote -v`、`git ls-remote --symref origin HEAD`。

> 旧细探未发现，故无旧文档可吸收；后续只维护本 `ARCHITECTURE.md`，不得把聊天摘要或临时文件当作第二事实源。
