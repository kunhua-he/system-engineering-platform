# FreeCOMObject 架构说明

## 1. 项目定位

FreeCOMObject 是一个 Windows 原生 C++ DLL，用于在特殊调用环境下释放 COM 接口指针。项目只提供一个导出函数 `ReleaseCOMObject`：调用方把可转换为 `IUnknown*` 的 COM 对象地址以 `void*` 传入，DLL 在非空时调用一次 `IUnknown::Release()`。

README.md 明确要求使用 `X86 + Release` 编译；当前工程实际同时声明了 Win32/x64 与 Debug/Release 配置，但没有提交调用方、示例程序或测试工程。因此，README 的 X86 + Release 是项目推荐/兼容基线，x64 与 Debug 只是工程配置存在，不能据此推断已验证。

## 2. 真实执行流程

```text
调用方（未随仓库提供）
    │
    │ 取得 COM 接口地址，转换为 void*
    ▼
FreeCOMObject.dll!ReleaseCOMObject(void* p)
    │
    ├─ p == nullptr ───────────────► 直接返回，不产生释放动作
    │
    └─ p != nullptr
          │ reinterpret_cast<IUnknown*>(p)
          ▼
       IUnknown::Release()
          │
          ▼
       COM 对象按自身引用计数规则释放/保留
```

DLL 装载流程如下：

```text
Windows 装载 DLL
    ▼
DllMain(HMODULE, DWORD ul_reason_for_call, LPVOID)
    ▼
忽略 DLL_PROCESS_ATTACH / DLL_THREAD_ATTACH /
    DLL_THREAD_DETACH / DLL_PROCESS_DETACH
    ▼
返回 TRUE
```

`DllMain` 没有初始化 COM、线程局部状态、全局对象或资源清理逻辑；COM 初始化责任、对象类型责任和调用线程责任均在调用方/宿主环境边界之外。

## 3. 目录与文件地图

```text
FreeCOMObject/
├── README.md                         项目简介与 X86 + Release 使用提示
├── FreeCOMObject.sln                 Visual Studio 解决方案
└── FreeCOMObject/
    ├── FreeCOMObject.cpp             唯一业务实现；实现 ReleaseCOMObject
    ├── FreeCOMObject.h               导出宏与函数声明
    ├── FreeCOMObject.def             DLL 名称与导出表，ReleaseCOMObject @1
    ├── FreeCOMObject.vcxproj         MSBuild/Visual C++ 工程配置
    ├── FreeCOMObject.vcxproj.filters Visual Studio 文件分组
    ├── dllmain.cpp                   DLL 入口 DllMain
    ├── framework.h                   Windows 头文件封装
    ├── pch.h / pch.cpp               预编译头及其编译单元
    └── cpp.hint                      Visual Studio C++ 提示文件
```

仓库当前未发现 `ARCHITECTURE.md` 以外的架构文档、历史研究文档、测试目录、调用示例、安装脚本或 CI 配置；本文件是项目根唯一架构归档文档。

## 4. 核心模块与真实调用链

### 4.1 `FreeCOMObject/FreeCOMObject.cpp`

- 包含 `pch.h`、`framework.h`、`FreeCOMObject.h` 与 Windows OLE 头 `ole2.h`。
- `ReleaseCOMObject(void* p)` 是唯一业务函数。
- 实现先执行 `reinterpret_cast<IUnknown*>(p)`，再判断指针是否为 `nullptr`。
- 非空时直接调用 `pUnknown->Release()`，不检查返回值，也不把指针置空。
- 注释中的 `MessageBoxA` 已被注释，不属于运行逻辑。
- 注释掉的 `CFreeCOMObject` 类和 `nFreeCOMObject` 导出变量均未形成可用 API。

### 4.2 `FreeCOMObject/FreeCOMObject.h`

`FREECOMOBJECT_EXPORTS` 定义时，`FREECOMOBJECT_API` 展开为 `__declspec(dllexport)`；其他调用方包含该头文件时展开为 `__declspec(dllimport)`。公开声明为：

```cpp
FREECOMOBJECT_API void ReleaseCOMObject(void* p);
```

声明没有显式 `extern "C"`、调用约定或 `noexcept`。因此，调用方必须按 Visual C++ 工程的默认 ABI 使用；导出名/名称修饰在目标 Windows 构建产物中仍需用 `dumpbin /exports` 或等价工具确认。

### 4.3 `FreeCOMObject/FreeCOMObject.def`

```text
LIBRARY "FreeCOMObject"
EXPORTS
ReleaseCOMObject @1
```

模块名为 `FreeCOMObject`，导出表把 `ReleaseCOMObject` 固定到 ordinal 1。该文件由 `FreeCOMObject.vcxproj` 的 `ModuleDefinitionFile` 配置引用。

### 4.4 `FreeCOMObject/dllmain.cpp`

`DllMain` 对四类通知全部不执行动作并返回 `TRUE`。它不是 COM 初始化入口，也不负责释放传入对象；仓库没有 `CoInitialize*`、`CoUninitialize`、线程池或全局 COM 状态代码。

## 5. 数据模型、状态与资源所有权

项目没有数据库、配置文件、持久化模型、消息队列或业务实体。唯一运行时数据是函数参数 `void* p` 及其临时解释出的 `IUnknown* pUnknown`。

| 数据/资源 | 来源 | 生命周期与处理 |
|---|---|---|
| `void* p` | DLL 调用方 | 仅在本次调用中读取，不保存、不修改、不归零 |
| `IUnknown* pUnknown` | `reinterpret_cast<IUnknown*>(p)` | 仅为局部指针别名；非空时调用一次 `Release()` |
| COM 对象引用计数 | COM 对象实现 | 由对象自己的 `IUnknown::Release()` 决定是否销毁 |
| DLL 模块状态 | Windows Loader | `DllMain` 不维护额外状态 |

所有权边界必须明确：`ReleaseCOMObject` 假定传入地址确实指向可调用 `IUnknown::Release()` 的 COM 接口，并把一次引用释放责任转交给对象实现。传入悬空指针、非 COM 指针、错误接口布局或已经释放的地址都会导致未定义行为；该函数没有运行时类型检查能力。

## 6. API、ABI 与使用边界

### 6.1 DLL API

| 项目 | 事实 |
|---|---|
| 导出函数 | `ReleaseCOMObject(void* p)` |
| 返回值 | `void`；无法报告成功、失败或释放后的引用计数 |
| 空指针行为 | `p == nullptr` 时安全直接返回 |
| 非空行为 | 转为 `IUnknown*` 后调用一次 `Release()` |
| 导出 ordinal | `.def` 指定 `@1` |
| 调用约定 | 未显式指定，采用工程/编译器默认值 |
| COM 初始化 | DLL 不负责，仓库未实现 |
| CLI/HTTP/SDK/插件协议 | 未发现 |

### 6.2 调用方契约

调用方至少需要满足：

1. 传入的地址指向有效且仍持有引用的 COM 接口对象。
2. 该地址的首个虚函数表布局可按 `IUnknown` 调用 `Release()`。
3. 调用方自行管理 COM apartment、线程模型、对象生命周期和其余引用。
4. 释放后不得继续使用该引用；DLL 不会把调用方变量清零。
5. 构建/加载位数与宿主一致；README 给出的推荐基线为 `X86 + Release`。

## 7. 技术栈与依赖边界

- 语言：C++（Visual C++ 工程）。
- 构建系统：Visual Studio/MSBuild，`PlatformToolset` 为 `v143`。
- 目标平台：Windows，`WindowsTargetPlatformVersion` 为 `10.0`。
- 产物类型：`DynamicLibrary`，目标名为 `FreeCOMObject`。
- 系统依赖：Windows SDK 的 `windows.h`，以及 `ole2.h` 提供的 COM/OLE 声明；`IUnknown` 来自 Windows COM ABI。
- 工程依赖：预编译头 `pch.h`，模块定义文件 `FreeCOMObject.def`。
- 第三方依赖：未发现。
- 运行时依赖：Windows COM ABI；实现没有显式链接库、配置中心或外部服务声明。

工程声明四组配置：`Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64`。Win32 Release 额外启用 `RuntimeLibrary=MultiThreaded`、全程序优化、COMDAT 折叠和引用优化；x64 Release 也启用链接优化，但未配置与 Win32 Release 完全相同的运行库项。

## 8. 构建产物与入口

工程把 `FreeCOMObject.cpp`、`dllmain.cpp`、`pch.cpp` 编译为 DLL，并通过 `FreeCOMObject.def` 接入导出表。解决方案只包含该 DLL 项目；仓库没有安装步骤、注册表脚本、COM 类注册（CLSID/ProgID）、`DllRegisterServer`/`DllUnregisterServer`，因此它不是一个自注册 COM in-proc server，而是被其他程序显式加载并调用导出函数的工具 DLL。

README 的唯一操作提示是“请使用X86+Release编译”。本次未在 macOS 上执行 Windows/MSBuild 构建，也未生成或检查 DLL 导出二进制；不能把工程文件存在误报为构建成功。

## 9. 测试与验证结构

- 测试目录：未发现。
- 测试源码：未发现。
- CI/自动化验证：未发现。
- 示例调用方：未发现。
- 已执行的只读验证：读取 README、全部已跟踪源码/工程配置、Git 工作区与远程引用；远程 `HEAD` 与本地 `HEAD` 一致。
- 未执行事项：未安装依赖、未启动程序、未构建 DLL、未加载 COM、未执行 Windows API/ABI 验证、未运行测试。

在可用 Windows 环境中，后续验证应至少包含：

1. `Release|Win32` 构建退出码为 0。
2. 用 `dumpbin /exports FreeCOMObject.dll` 确认 `ReleaseCOMObject` 的导出名称和 ordinal 1。
3. 用最小 COM 测试宿主验证有效 `IUnknown*` 释放一次、`nullptr` 不崩溃。
4. 验证错误指针、重复释放和跨 apartment 使用属于调用方错误，不应被描述为 DLL 已安全处理。

## 10. 版本基线与远程复核

- 本地分支：`master`。
- 本地提交：`bc13be3ac5b96e23d6d5c796bc33eb816088f55c`。
- 本地最后提交时间：`2023-10-11T15:48:23+08:00`。
- 本地最后提交：`Update README.md`。
- 远程地址：`https://github.com/aiqinxuancai/FreeCOMObject.git`。
- 远程 `HEAD`/`refs/heads/master`：`bc13be3ac5b96e23d6d5c796bc33eb816088f55c`。
- 版本结论：远程与本地当前提交一致，本次没有创建独立远程快照，也没有对目标仓库执行 fetch/pull。
- 工作树基线：任务开始时 `git status --short --branch` 显示 `master...origin/master`，无未提交改动；本文件创建后是唯一预期新增文件。

## 11. 未确认项、风险与后续复核点

1. **导出名称风险**：C++ 声明未使用 `extern "C"`，而 `.def` 写的是未修饰名称。需要在 Windows 产物上检查链接是否确实导出 `ReleaseCOMObject`；仅凭源码无法替代二进制验证。
2. **ABI/位数风险**：README 指定 X86 + Release，但工程也提供 x64；调用方的指针大小、默认调用约定与 DLL 必须一致。
3. **指针类型风险**：公开接口使用无类型 `void*`，不能验证对象是否为 `IUnknown`，错误地址可能直接崩溃。
4. **重复释放风险**：函数不把调用方指针置空，也没有幂等标记；同一引用重复调用可能造成 COM 引用计数错误或崩溃。
5. **线程/apartment 风险**：DLL 不初始化或切换 COM apartment；跨线程传递接口指针是否有效由调用方的 COM marshaling 负责。
6. **返回契约限制**：返回 `void`，调用方无法获得 `Release()` 结果或对象是否销毁的确认。
7. **可维护性风险**：仓库没有自动化测试、示例宿主、CI 或发布说明，README 之外的使用契约主要依赖源码推断。
8. **工程配置差异**：Win32/x64、Debug/Release 的运行库和链接选项并不完全对称；若需要 x64 或 Debug 发布，应在 Windows 上单独验证。

以上风险是基于当前源码和工程配置的待核项，不对未执行的 Windows 构建或运行结果作肯定结论。

## 12. 证据路径

- `README.md`
- `FreeCOMObject/FreeCOMObject.cpp`
- `FreeCOMObject/FreeCOMObject.h`
- `FreeCOMObject/FreeCOMObject.def`
- `FreeCOMObject/dllmain.cpp`
- `FreeCOMObject/FreeCOMObject.vcxproj`
- `FreeCOMObject/pch.h`
- `FreeCOMObject/pch.cpp`
- `FreeCOMObject/framework.h`
- `FreeCOMObject/FreeCOMObject.vcxproj.filters`
- Git 版本与远程引用：目标仓库 `.git` 元数据（本地 `HEAD` 与远程 `HEAD` 均为 `bc13be3ac5b96e23d6d5c796bc33eb816088f55c`）

## 13. 当前裁决：COM 语义与平台底座映射

### 13.1 当前审计边界与证据等级

当前审计只在目标仓库根目录补充本文件；没有修改 C++ 源码、Visual Studio 工程、依赖、测试、README、Git 或历史研究。目标仓库的源码证据以本地文件为准；平台映射读取的是系统工程平台的公开架构与现有实现，用于判断归属，不把平台代码误写成 FreeCOMObject 已有实现。

任务要求的 `project_context` 当前错绑到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与目标源码根不一致；该返回结果只作为环境问题记录，不作为目标项目、平台能力命中或验证证据。当前审计改用目标仓库现场静态取证，并将平台能力命中单独标为“可复用模式/部分命中/缺口”。

COM 的通用语义以 Microsoft 文档作为外部规范参考：`IUnknown` 的前三个 vtable 槽为 `QueryInterface`、`AddRef`、`Release`，分别用于获取接口、增加引用和减少引用（<https://learn.microsoft.com/en-us/windows/win32/api/unknwn/nn-unknwn-iunknown>）；COM 必须在使用线程上初始化，成功的 `CoInitializeEx` 需要与对应的 `CoUninitialize` 配对，STA 接口不能把裸接口指针直接复制给其他线程，而应通过 marshaling（<https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex>、<https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library>）。这些是规范约束，不是本仓库已运行验证的结果。

### 13.2 当前项目只实现“释放一次”，不实现 COM 对象创建与查询

| COM 能力 | 当前源码事实 | 结论 |
|---|---|---|
| 对象创建/激活 | 未发现 `CoCreateInstance`、`CoCreateObject`、`CoGetClassObject`、CLSID/类工厂、`DllGetClassObject` 或注册表注册；工程是普通 `DynamicLibrary` | **未实现**；FreeCOMObject 不是 COM in-proc server，也不是对象工厂 |
| `QueryInterface` | `FreeCOMObject.cpp:13-21` 没有调用 `QueryInterface`，头文件也只有 `ReleaseCOMObject(void*)` | **未实现**；没有 IID 输入、接口支持查询或返回接口契约 |
| `AddRef`/引用获取 | 目标业务实现没有 `AddRef`；调用方传入的已有指针由调用方负责持有 | **未实现**；DLL 不创建新的接口引用 |
| `Release`/减少引用 | `FreeCOMObject.cpp:15-18` 将 `void*` 重解释为 `IUnknown*`，非空时直接调用一次 `pUnknown->Release()` | **唯一已实现的业务动作** |
| COM 线程单元 | `dllmain.cpp:4-17` 四类 DLL 通知均为空；未发现 `CoInitialize*`、`CoUninitialize`、STA/MTA、消息循环或 marshaling | **未实现**；线程单元责任在宿主/调用方，且没有被 DLL 保护 |
| 跨模块接口 | `FreeCOMObject.h:22` 暴露 `void*`；`.def` 以 ordinal 1 导出 `ReleaseCOMObject` | **低层 ABI 适配接口**，不是平台可序列化的跨模块对象契约 |
| 返回/错误 | 函数返回 `void`，不传出 `HRESULT`、释放后计数、对象是否销毁或诊断 | **无法形成统一结果**；失败可能直接表现为未定义行为/宿主崩溃 |

因此不能把“COM 对象创建、`QueryInterface`、引用计数、线程单元”反推为项目能力。当前项目的准确定位是：**调用方已经拥有一个 COM 接口引用时，向 DLL 请求执行一次 `IUnknown::Release()` 的 Windows C++ 兼容性小适配器**。

### 13.3 当前调用链的所有权含义

```text
调用方/宿主先取得 COM 接口引用
  │  （本仓库不创建、不 AddRef、不 QueryInterface）
  ▼
void* ──FreeCOMObject.h:22──► ReleaseCOMObject(void*)
  │
  ├─ nullptr ─► 返回；无释放动作
  │
  └─ 非空 ─► reinterpret_cast<IUnknown*>(p)
                 │
                 └─ 调用一次 IUnknown::Release()
                         │
                         ├─ 引用计数仍大于 0：对象继续存在
                         └─ 引用计数归零：由 COM 对象实现决定销毁
```

这里的“引用计数归零后销毁”是 COM 对象实现的语义，不是 FreeCOMObject 的可观测保证。FreeCOMObject 不知道对象实际计数、不知道该指针是否为同一接口引用、不保存指针、不将调用方变量清零，也没有释放成功/失败返回值。

### 13.4 重复释放、错误指针与崩溃边界

| 场景 | 当前代码行为 | 平台化结论 |
|---|---|---|
| `nullptr` | 安全返回 | 可作为输入校验的静态分支；没有运行时测试 |
| 有效且仍持有的 `IUnknown*` | 调用一次 `Release()` | 仅能释放一个调用方已经持有的引用 |
| 同一引用第二次调用 | DLL 不保存“已释放”标志，仍再次执行 `Release()` | **不能声称幂等**；可能减少错误引用、访问已释放 vtable 并崩溃 |
| 两个别名各代表不同合法引用 | 各自调用一次 `Release()` 可能正确 | 需要调用方准确维护每个引用的所有权；DLL 无法区分 |
| 悬空指针/非 COM 指针/错误 vtable | 直接通过虚函数调用 | 未定义行为，可能访问冲突；不存在错误码闭环 |
| `QueryInterface` 后未配对释放 | 本项目没有 QI，无法修复调用方泄漏 | QI 返回的新接口引用必须由相同所有权链单独释放 |
| 其他线程/apartment 直接复用 | DLL 不检查、不 marshaling、不切换线程 | 由 COM 线程模型决定，不能把裸指针跨线程当作安全 |
| 宿主进程崩溃 | DLL 没有崩溃钩子、恢复、对象账本或清理协议 | 不能保证 `Release()` 被执行；只能由进程终止、COM 服务器和外部资源自行收尾 |
| DLL 卸载/进程退出 | `DllMain` 不处理清理 | 不应把 DLL 卸载当作 COM 引用自动释放机制 |

“重复释放”在 COM 中不能靠简单的再次 `Release()` 实现幂等；**平台必须在受管句柄层记录一次性消费状态，在底层指针层保证 `Release()` 最多调用一次**。平台的“重复释放幂等”与 COM 的“每个接口引用必须精确配对”是两层不同语义，不能混为一个计数器。

### 13.5 归属裁决：原生对象支持库、句柄执行单元、运行核心

#### A. 原生对象支持库：拥有 COM 原子动作和 ABI 适配

建议新增（待需求登记与能力搜索确认）一个 Windows 原生对象支持库/受管 COM 提供者，能力范围应收敛为原子动作，而不是复制 FreeCOMObject 的业务流程：

- 创建/激活：输入 `CLSID`、激活上下文、目标接口 `IID` 和权限/位数约束，返回平台统一结果，不返回裸 `IUnknown*`；
- `QueryInterface`：输入受管对象句柄与 `IID`，成功返回新的不透明接口句柄，并记录一次新的 COM 引用；不支持的 IID 返回明确错误；
- `AddRef`：只允许对受管接口句柄执行，记录“引用获取”证据；不向跨模块调用方暴露指针；
- `Release`：对接口句柄执行一次底层 `Release()`，句柄转为已释放；再次释放只返回幂等结果，不再触碰底层 vtable；
- 调用：只允许在对象所属执行单元/线程单元内完成，输入输出必须是可序列化契约或受管制品引用；
- 能力探针：报告 Windows、架构、COM 初始化、CLSID/IID 支持和 provider 版本，缺宿主能力时返回 `HOST_UNAVAILABLE`，不能模拟成功。

现有 `支持库/适配层/动态库适配器/动态库适配器.py:1-54` 只能作为接口形状参考：其文件明确写明“模拟提供者（不加载真实动态库）”，`建立连接`、`执行最小操作`、`关闭连接` 返回模拟状态；不能把它升级描述为真实 COM/DLL 支持。现有 `支持库/适配层/适配契约.py:1-70` 的检查→版本→连接→操作→关闭顺序可复用为提供者外壳，但 COM 的引用、IID、apartment 和 marshaling 仍是新的原子语义。

#### B. 句柄执行单元：拥有对象的运行上下文，而不是 COM 方法语义

COM 对象不是普通短值。需要 STA 的对象必须绑定到创建它的线程单元；MTA 对象也不能因平台句柄抽象而被错误地假定为任意线程安全。因此建议把“对象 + 所属 COM apartment + provider 进程/线程”建模为一个受管执行单元：

```text
申请 COM 执行单元
  → 运行核心分配 execution_id + lease_id + owner + apartment/thread policy
  → 受管线程调用 CoInitializeEx（STA 或 MTA）
  → 原生对象支持库在该单元内创建对象并保存私有接口引用
  → 调用方只得到不透明 execution_id/interface_handle
  → QueryInterface/调用/Release 均路由回所属单元
  → 释放时排空调用 → 对每个受管接口精确 Release → CoUninitialize
  → 句柄失效、保留释放证据、检查线程/进程/句柄残留
```

`运行核心/句柄体系.py:1-117` 已有可复用的句柄状态机：句柄含 `句柄id/资源id/项目id/所有者/版本/状态`，失效重复调用返回“幂等”，并保存回收证据；但它当前是内存表，没有 COM 引用槽、apartment 亲和性、真实租约时间检查或进程重启恢复，不能直接宣称已支持 COM。`运行核心/资源协调/服务.py:84-101` 的读取句柄“失效 + 引用归零”模式可作为快照类资源参考，但 COM 引用不能使用其文件快照方式替代真实 `Release()`。

句柄的公开字段建议至少包含：`execution_id`、`lease_id`、`interface_handle`、`object_identity`（仅用于证据，不能泄露指针）、`owner`、`apartment_model`、`thread_affinity`、`provider_version`、`expiry` 和 `state`。其中 COM 引用计数与租约计数必须分开：租约到期意味着拒绝新调用并进入排空；只有受管单元完成所有接口引用释放后才可报告 `已释放`。

#### C. 运行核心：拥有 apartment、调度、超时、崩溃和恢复治理

以下责任归 `运行核心/提供者监督器/执行协调器`，不应塞进普通模块或让 DLL 的 `DllMain` 代办：

1. 选择 STA/MTA/自由线程策略，创建并维护拥有 apartment 的线程或独立 provider 进程；
2. 在该线程初始化 COM，在同一线程、同一数量语义下配对 `CoUninitialize`；不在 `DllMain` 调用 COM 初始化/反初始化；
3. 对 STA 对象把请求投递回所属线程并保证消息泵/排空策略；跨 apartment 需要显式 marshaling，而不是复制 `void*`；
4. 分配和校验 `execution_id/lease_id/owner`，阻止跨项目、跨 owner、过期和跨版本复用；
5. 管理并发、调用截止时间、取消、队列上限、进程/线程上限和内存/句柄预算；
6. 释放阶段只执行一次排空和一次底层引用回收；记录每个 `interface_handle` 的释放结果，未释放时不得返回完整成功；
7. provider 访问冲突或崩溃时隔离并回收线程/进程组/管道/临时目录/句柄；禁止用旧的裸指针或旧 lease “自动复活”；
8. 记录请求 id、能力 id、provider、COM apartment、IID、对象句柄、错误码、退出码和资源释放结论，支持重启后对账。

平台已有 `运行核心/运行环境管理器/提供者生命周期.py:271-559` 的独立提供者生命周期可复用：启动/停止幂等、最大进程数、崩溃检测、有限重启、取消后的进程重置、管道关闭、临时目录清理和零残留核对。`运行核心/加载器/提供者隔离/独立进程.py:134-281` 也已有 JSON 行协议、启动/调用超时、退出码、管道关闭与崩溃重启。但这些实现尚未声明 COM apartment/对象引用模型；COM provider 仍需新增专属生命周期状态与测试。

### 13.6 跨模块/跨进程接口：严禁 `void*` 穿透平台边界

FreeCOMObject 的 `void*` 入口只能作为 Windows 同进程兼容层的历史参考，不能成为平台模块接口。平台现有边界要求：模块只持能力 id/契约版本，调用方不持第三方对象、连接、线程、进程或原生句柄；跨支持库、跨模块、跨执行单元走唯一能力调用器和 HTTP/JSON 契约。

推荐的跨边界形状：

```text
模块/任意语言调用方
  → HTTP 能力网关
      {能力id, 契约版本, execution_id, lease_id,
       interface_handle, IID/方法, 参数, request_id, deadline}
  → 运行核心校验 owner/apartment/租约
  → COM provider 所属线程单元执行
  → 统一结果 {成功, 值, 错误码, 错误说明, 可重试,
               request_id, provider, 资源释放结论, 证据}
```

`interface_handle` 必须是不透明、不可猜测、带 owner/版本/状态校验的 token；不能是地址、vtable、`IUnknown*` 序列化值、进程号或 C++ 对象内存。返回值只能是基础类型、结构化 JSON、受管文件/制品引用或另一个受管句柄。若模块需要组合 `创建→QI→调用→释放`，组合流程归模块库，但每个 COM 原子动作仍由原生对象支持库实现，所有执行和生命周期治理由运行核心注入。

现有 `运行核心/能力调用/唯一能力调用.py:53-171` 是唯一调用链候选：它以能力 id 查注册表、创建调用证据、锁定版本、记录成功/失败与资源释放结论；`运行核心/能力调用/唯一能力调用.py:283-291` 还有版本锁释放结论。需要注意当前实现的异常分支会重新抛出异常（`157-171`），不能直接当作 COM 对外契约；COM provider 必须把 HRESULT/异常/崩溃先转换为稳定错误码，网关再透传统一结果。

### 13.7 现有能力命中、缺口与单链路裁决

| 底座位置 | 命中程度 | 可复用内容 | 不能替代的缺口 |
|---|---|---|---|
| `支持库/后端/资源管理` | 部分命中 | 唯一运行目录、原子写入、短锁、CAS、安全释放；支持资源生命周期的文件/目录侧治理 | 不理解 COM 指针、IID、`AddRef/Release`、apartment 或 marshaling |
| `支持库/适配层/适配契约.py` | 部分命中 | 检查、版本、建立、操作、关闭的 provider 统一外壳与结果类型 | 当前契约没有 COM 对象身份、接口引用槽、线程单元和释放次数 |
| `运行核心/句柄体系.py` | 部分命中 | 不透明句柄、项目/所有者校验、失效幂等、回收证据 | 无真实租约过期、COM 引用账本、apartment 亲和性、重启恢复 |
| `运行核心/能力调用/唯一能力调用.py` | 可复用调用骨架 | 唯一注册表、版本锁、请求证据、资源释放结论 | 需补 provider 路由、HRESULT 映射、异常不外泄和有状态句柄参数 |
| `运行核心/运行环境管理器/提供者生命周期.py` | 可复用治理骨架 | 独立进程、健康、超时、取消、崩溃、重启、管道/临时目录清理 | 未绑定 COM apartment 初始化、对象引用释放和 STA 消息泵 |
| `运行核心/加载器/提供者隔离/独立进程.py`、`支持库/适配层/本地进程适配器` | 部分命中 | 受控子进程/JSON 协议/进程组终止/输出边界 | 仅进程生命周期，不是 COM 接口调用协议 |
| `支持库/适配层/动态库适配器` | 仅参考 | 外部库检查/连接/操作/关闭的形状 | 明确是模拟提供者，不能当真实 COM/DLL 实现 |
| `后端核心/后端核心.py` | 部分命中 | 通用宿主、装配、排空、请求计数和统一结果 | 直接调用注册函数，不处理原生对象、apartment 和有状态 lease |

**单链路落点：**

```text
调用方/模块
  → HTTP 网关（唯一通信入口）
  → 运行核心唯一能力调用器
  → 原生对象支持库的 COM 能力契约
  → COM provider 受管执行单元（STA/MTA 线程或隔离进程）
  → Windows COM API / COM 服务器
  → 结构化结果 + 释放证据
```

不允许出现“模块直接加载 FreeCOMObject.dll”“模块自己缓存 `IUnknown*`”“每个模块自己调用 `ReleaseCOMObject`”“网关保存 COM 对象”或“为 COM 再建第二个注册表/调用器”。

### 13.8 复用、升级、新建、隔离/废弃裁决

| 裁决 | 对象 | 结论与理由 |
|---|---|---|
| 复用 | 资源管理、唯一能力调用、提供者独立进程、任务取消/清理模式 | 这些是公共底座已有通用治理能力，COM 只接入其契约和 provider 边界，不复制生命周期系统 |
| 升级 | 运行核心句柄体系/提供者监督器 | 增加 apartment 亲和性、lease 过期、接口引用槽、释放一次性、崩溃后句柄失效和恢复对账 |
| 新建 | Windows 原生对象/COM 支持库及其真实 provider | 当前 38 个正式支持库和源码检索未命中 COM 原子能力；FreeCOMObject 只有危险的释放薄壳，不能充当完整 owner |
| 新建 | COM 执行单元适配（可作为运行核心子模块，不作为业务模块） | 需要 STA/MTA、线程回调、marshaling、CoInitializeEx/CoUninitialize 配对和对象引用账本 |
| 隔离/废弃 | `ReleaseCOMObject(void*)` 作为平台公开接口 | 保留为源码参考/兼容适配候选；不纳入跨模块公开能力，不允许新代码直接依赖裸指针 |
| 待核 | 是否必须支持 COM 创建/激活、哪些 CLSID/IID、STA 还是 MTA、是否允许 in-proc | 目标项目没有创建/查询/调用方信息，不能凭一个 Release 函数决定公共契约 |

### 13.9 依赖、资源和错误契约草案（仅作为装配输入）

#### 依赖边界

- 宿主：Windows、Windows SDK、COM/OLE ABI；目标架构和 DLL/调用方位数必须一致；
- provider：CLSID/IID、COM server 注册/激活条件、线程模型、权限、位数、版本和许可证须声明；
- 主进程：不得加载未知原生扩展或向网关暴露接口地址；高风险/不可协作取消/可能访问冲突的 provider 默认独立进程；
- 调用协议：能力 id、契约版本、参数 schema、错误码、超时/取消、幂等键、执行单元和资源释放结论必须固定。

#### 资源所有权表

| 资源 | 创建者 | 持有者 | 转移规则 | 正常释放 | 失败/超时/崩溃 |
|---|---|---|---|---|---|
| COM apartment 线程 | 运行核心 | 执行单元 | 不向调用方转移线程对象 | 排空后在同一线程 `CoUninitialize` | 单元失败；线程 join/终止；残留核对 |
| COM 对象引用 | 原生对象支持库/provider | 执行单元私有引用槽 | 只转移不透明 interface handle，不转移指针 | 每槽最多一次 `Release` | 记录未释放；进程隔离时由进程终止兜底，不能伪报已 Release |
| QI 返回接口引用 | `QueryInterface` 成功路径 | 新 interface handle | 新句柄独立计数，不与源句柄混用 | 新句柄单独 Release | QI 失败无新引用；重复释放返回已释放 |
| execution/lease 句柄 | 运行核心 | owner/项目 | 仅同 owner、同版本、未过期可用 | 显式释放或 TTL 回收 | 过期不可复活，返回句柄过期 |
| provider 进程/管道 | 运行核心 | provider 监督器 | 不向模块暴露 | 优雅停止→强制终止→close 管道 | 崩溃/超时 kill 进程组，重启次数有界 |
| 临时目录/制品 | 支持库/provider | 执行单元 | 只传受管引用 | finally/释放阶段清理并核对 | 失败、取消、崩溃后清理；残留阻止完整成功 |

建议错误码（名称需经正式契约审核，当前不是已登记能力）：`参数不合法`、`HOST_UNAVAILABLE`、`CLSID_UNSUPPORTED`、`IID_UNSUPPORTED`、`COM_NOT_INITIALIZED`、`APARTMENT_MISMATCH`、`HANDLE_NOT_FOUND`、`EXECUTION_HANDLE_EXPIRED`、`INTERFACE_ALREADY_RELEASED`、`RELEASE_FAILED`、`TIMEOUT`、`CANCELLED`、`PROVIDER_CRASHED`、`RESOURCE_LEAK`、`ABI_MISMATCH`。HRESULT、访问冲突和 C++ 异常只作为详细证据，不能直接泄漏为跨模块业务协议。

### 13.10 失败、重复释放和崩溃验收矩阵

| 场景 | 必须验证的结果 | 不能用什么冒充通过 |
|---|---|---|
| 创建成功 | 执行单元健康；对象句柄有效；创建的引用槽有账本 | 只检查 DLL/类名存在 |
| CLSID/IID 不支持 | 稳定错误码；无泄漏；执行单元可继续或明确失败 | 返回空指针但标成功 |
| `QueryInterface` 成功 | 新接口句柄独立存在；引用增加一次；源句柄仍有效 | 只比较返回地址非空 |
| `QueryInterface` 失败 | 不增加引用；错误可重试语义明确 | 捕获异常后吞掉 |
| 正常 `Release` | 底层调用一次；句柄失效；释放证据完整 | 只把 Python/平台句柄删掉 |
| 重复 `Release` | 第二次不再触碰 COM 指针，返回幂等/已释放；账本无负数 | 再次调用原始 `Release()` |
| 释放后继续调用 | 拒绝并返回句柄已失效/已释放 | 让旧 vtable 继续执行 |
| STA 跨线程调用 | 通过所属线程或 marshaling 成功，或明确 `APARTMENT_MISMATCH` | 直接复制 `void*` |
| MTA 并发 | 仅在 provider 声明对象可并发时放行；否则串行/拒绝 | 看到 MTA 就默认对象线程安全 |
| 取消/超时 | 请求停止、排空、释放或隔离；线程/进程/管道无残留 | 只让等待线程返回 |
| provider 崩溃 | 退出码/信号可见；旧 execution/interface handle 全部失效；重启次数有界 | 自动新建对象后继续使用旧句柄 |
| 宿主/DLL 崩溃 | 记录未知终态，重启后对账；不声称已执行 Release | 根据 finally 或日志猜测释放成功 |
| 位数/ABI 不匹配 | 构建/加载前明确拒绝或静态门禁阻断 | 仅依赖 README 的 X86 提示 |

### 13.11 L0-L4 证据阶梯与当前结论

本档沿用平台文档的诚实分级，不把“源码存在”写成真实运行通过：

| 等级 | 证据含义 | FreeCOMObject 当前证据 |
|---|---|---|
| L0 | 源码路径、声明、工程契约和目录事实存在 | **已具备**：`FreeCOMObject.cpp/.h/.def/dllmain.cpp/.vcxproj` 已现场读取；唯一公开动作与缺失动作可定位 |
| L1 | 源码中存在可执行控制流/静态可复核路径；配置能解释预期构建入口 | **部分具备**：`nullptr→return`、非空→`Release()`、四配置 DLL 工程和 ordinal 导出路径存在；未在目标宿主编译 |
| L2 | 目标平台真实构建/导出/最小功能测试或测试源码证据 | **未具备**：仓库无测试、示例或 CI；本机 macOS 未执行 Windows/MSBuild、`dumpbin` 或 DLL 加载 |
| L3 | Windows COM 宿主真实创建/QI/AddRef/Release/apartment/跨线程/跨模块链路验证 | **未具备**：无 Windows runtime、COM server、CLSID/IID、调用方或真实宿主结果 |
| L4 | 故障注入与恢复：重复释放、悬空指针、线程错用、超时取消、provider/宿主崩溃、重启对账和零残留 | **未具备**：没有故障注入测试、崩溃转储、进程/句柄残留核对或恢复证据 |

当前裁决平台映射本身也只能标为 **L0（架构/路径/契约命中）**；现有平台 Python 句柄、进程和资源治理代码不能证明 COM provider 已存在。COM 能力的 L2-L4 必须在 Windows 隔离环境中单独建立证据。

### 13.12 装配计划与验收契约（不在当前审计执行）

若后续需求确认需要 COM 能力，应按以下顺序登记工作包，不得直接把当前 DLL 接入生产链：

1. **需求与能力搜索**：明确是否需要创建、QI、方法调用、事件、连接点、持久会话；登记 CLSID/IID、Windows 版本、Win32/x64 和 STA/MTA 要求；当前搜索未命中现有正式 COM 能力。
2. **公共契约冻结**：冻结能力 id、输入输出、HRESULT 映射、错误码、超时/取消/幂等、`execution_id/lease_id/interface_handle` 字段和释放证据；明确 COM 引用计数与平台租约分账。
3. **原生对象支持库工作包**：实现真实 Windows provider；所有 `IUnknown*` 仅在 provider 私域；创建/QI/AddRef/Release 做引用槽账本；成功和异常路径都输出结构化结果。
4. **运行核心工作包**：增加 apartment worker、线程亲和性、消息泵/排空、marshaling 策略、租约过期、释放幂等、崩溃隔离和恢复对账；复用现有唯一调用器、提供者监督器和进程回收，不建第二套。
5. **模块/网关接线**：模块只能传能力 id 与不透明句柄；HTTP/MCP/CLI 只做同一网关薄映射；禁止 C++ `void*`、`IUnknown*` 或 provider 对象穿透。
6. **验证波次**：Windows `Release|Win32` 和 `Release|x64` 构建；导出表；假 COM 对象计数器；QI 支持/不支持 IID；每个句柄一次 Release；重复释放；STA/MTA；跨线程 marshaling；超时取消；provider 崩溃/重启/零残留。
7. **发布门禁**：包声明、能力契约、provider 版本/架构、资源预算、完整性摘要和依赖防火墙齐全；只有 L2-L4 证据闭环后才可把候选从“待核”提升为“吸收”。

当前审计最终裁决：**吸收的是 COM 生命周期问题的底座归属与验收约束，不吸收当前 FreeCOMObject 的裸 `void*` 释放实现为平台公共内核；对象创建、QueryInterface、引用账本、线程单元和真实崩溃恢复均为待核/新建能力。**
