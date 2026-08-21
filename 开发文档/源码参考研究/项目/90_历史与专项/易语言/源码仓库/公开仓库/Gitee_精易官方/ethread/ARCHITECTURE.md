# ethread 架构建档

> 本文件是 `ethread` 项目的唯一架构事实源。当前核对为首轮全量只读建档；后续细探只增量维护本文件，不再建立平行架构报告。

## 1. 项目定位

`ethread` 是 Gitee 精易官方维护的 **易语言多线程支持库 Ex** 源码。它不是独立应用，而是一个面向易语言运行时/IDE 的 Windows 支持库 DLL，同时提供静态库构建目标。项目以 C++ 实现线程、线程池、临界区、线程消息循环和可变参数封送，并通过易语言支持库 ABI 暴露为 36 个命令、1 个全局命令类别、2 个自定义数据类型。

仓库既包含可编译源码，也包含已经生成的 `.fne` 支持库和 ZIP 发布包；发布物不是源码事实源，源码与命令元数据优先。

## 2. 版本与证据基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/ethread` |
| Git 远程 | `https://gitee.com/JYtechnology/ethread.git` |
| 远程 HEAD | `origin/master` |
| 本地分支 | `master`，与 `origin/master` 对齐 |
| HEAD 提交 | `7ed21cc21b5506c47452774ca470c393380bb57a` |
| HEAD 提交时间 | 2023-05-02 21:18:59 +0800 |
| HEAD 提交说明 | `修改线程池销毁模式, 只保留自生自灭和等待模式, 等待模式增加了处理消息` |
| 工作树 | 现场检查为干净；当前核对只新增本文件 |
| README 宣称版本 | 多线程支持库 Ex 3.2；更新日志日期 2023-02-13 |
| DLL 元信息 | `ethread_dllMain.cpp` 声明主版本 `3`、次版本 `2`、构建号 `502`，库名 `多线程支持库Ex` |
| 系统要求元信息 | 易语言系统 `3.7`，系统核心支持库 `3.7` |
| 目标平台 | `_CMD_OS(__OS_WIN)` / `_LIB_OS(OS_ALL)` 元数据并存；实际源码大量使用 Win32 API，当前工程的可验证实现边界是 Windows |
| MCP 开工 | 专属 `system_engineering_toolkit` 已完成 `project_context`，开工标识 `869c7e4958de4810` |
| 代码地图 | 专属 MCP 的 `codegraph_explore` 对该外部仓库返回“无 `.codegraph/`，未索引”；未伪造代码图结论，以下路径均来自现场源码读取 |

本地仓库包含 `.gitmodules`：历史上声明 `ethread` 子模块，远程为 `https://gitee.com/qq121007124/ethread.git`；当前工作树中源码直接位于项目根，子模块声明与现状存在历史遗留关系。

## 3. 总体流程图

```text
易语言程序 / 易语言 IDE
        │  加载 EThread.fne 或静态库集成
        ▼
GetNewInf() ──返回──> LIB_INFO
        │               ├─库版本/系统要求/作者/类别
        │               ├─命令描述数组 g_cmdInfo...
        │               ├─命令函数指针数组 g_cmdInfo..._fun
        │               ├─常量数组 g_ConstInfo...
        │               └─自定义类型 ThreadPool / ThreadPoolInfo
        ▼
易语言命令分发
        │  ETHREAD_DEF 宏按索引建立“描述—函数—参数”三张对应表
        ├────────────────────────────────────────────────────────┐
        ▼                                                        ▼
基础线程命令                                             线程池对象命令
CreateThread / Wait / Handle                         ThreadPool_Init / AddTask
CreateThreadEx / Suspend / Resume                     Destroy / 查询 / 挂起恢复
OpenThread / 消息循环                                  参数回调 / 无限参数
        │                                                        │
        ▼                                                        ▼
Win32 线程句柄、事件、临界区、消息队列              ThreadPool
        │                                                ├─workers: std::thread
        │                                                ├─tasks: FIFO queue
        │                                                ├─condition_variable 唤醒
        │                                                └─任务完成回调
        ▼                                                        ▼
易语言子程序指针 ← _threadpool_call / 参数封送 ← THREAD_ARG_STRUCT
        │
        └─任务执行、回调、结果恢复、释放参数内存
```

## 4. 真实目录与文件地图

```text
ethread/
├── ethread.sln                         Visual Studio 解决方案
├── ethread.vcxproj                     DLL 工程（目标名 EThread）
├── ethread_static/
│   ├── ethread_static.vcxproj          静态库工程（目标名 EThread_static）
│   ├── ethread_static.vcxproj.filters
│   └── ethread_static.vcxproj.user
├── ALL_BUILD/                          解决方案聚合工程
│   ├── ALL_BUILD.vcxproj
│   ├── ALL_BUILD.vcxproj.filters
│   └── ALL_BUILD.vcxproj.user
├── include_ethread_header.h            ABI 聚合头、宏生成、参数结构、调用封装
├── ethread_cmd_typedef.h               36 条命令的单一宏定义表
├── ethread_cmdDef.cpp                  线程/临界区/线程消息循环命令实现
├── ethread_pool.cpp                    线程池对象与可变参数命令实现
├── CThreadPool.h                        C++ 线程池核心模板实现
├── ethread_cmdInfo.cpp                 命令参数描述与命令信息数组
├── ethread_const.cpp                   易语言常量描述
├── ethread_dtType.cpp                  ThreadPool / ThreadPoolInfo 类型描述
├── ethread_dllMain.cpp                 DLL 入口、LIB_INFO、通知、GetNewInf、参数封送
├── elib/                               易语言支持库 ABI 辅助头与通知适配
│   ├── fnshare.cpp / fnshare.h
│   ├── krnllib.h / lang.h / lib2.h / mtypes.h
│   ├── PublicIDEFunctions.h
│   └── untshare.h
├── Source_ethread.def                  仅声明导出 GetNewInf
├── README.md                           简短版本与更新日志
├── 课程笔记.txt                         支持库课程与改造计划线索
├── 易语言调用测试.e                     易语言调用示例/测试夹具（二进制格式）
├── out/
│   ├── lib/EThread.fne                 已生成 DLL 支持库发布物
│   ├── 多线程支持库Ex 3.2.502(EThread).zip 发布包
│   └── 易语言调用测试.e                 示例副本
└── ARCHITECTURE.md                      本文件，唯一架构文档
```

## 5. 分层与职责

### 5.1 易语言 ABI 与元数据层

- `include_ethread_header.h` 引入易语言 ABI 头，定义 `ETHREAD_EXTERN_C`、命令函数声明宏、`SDT_TYPE_POOLINFO`。
- `ethread_cmd_typedef.h` 的 `ETHREAD_DEF(_MAKE)` 是命令清单的单一事实源。不同宏展开分别生成：函数声明、命令描述、函数指针、静态编译函数名。
- `ethread_cmdInfo.cpp` 保存参数槽位描述和 `CMD_INFO g_cmdInfo_ethread_global_var[]`。
- `ethread_const.cpp` 保存 8 个公开常量。
- `ethread_dtType.cpp` 保存 `线程池` 与 `线程池信息` 的易语言类型元数据。
- `ethread_dllMain.cpp` 将以上数组组装进 `LIB_INFO`，由 `GetNewInf()` 返回；`Source_ethread.def` 只导出 `GetNewInf`。

### 5.2 基础线程命令层

`ethread_cmdDef.cpp` 实现直接面向 Win32 的命令：创建线程、临界区、等待/关闭/强杀线程、扩展线程创建、挂起/恢复、打开线程句柄，以及线程消息循环。`_thread_call` 和 `_threadpool_call` 是针对易语言调用约定的 naked 汇编跳板，负责压入参数、调用易语言子程序并恢复栈。

### 5.3 线程池层

`CThreadPool.h` 的 `ThreadPool` 负责通用 C++ 线程池；`ethread_pool.cpp` 的 `CMyThreadPool` 仅增加易语言任务完成回调 `PFN_Complete`，并把对象指针放入易语言复合数据槽 `m_ppCompoundData[0]`。

线程池使用 `std::vector<std::thread>` 保存工作线程、`std::queue<std::function<void()>>` 保存 FIFO 任务、`queue_mutex` 保护任务队列、`workers_mutex` 保护线程列表、`condition_variable` 唤醒工作线程、原子空闲数 `idlThrNum` 和原子状态 `state`。空闲线程为 0 且容量未满时，`commit()` 追加一条工作线程。

### 5.4 参数封送与生命周期层

`THREAD_ARG_STRUCT` 保存参数个数、整数槽数组、易语言回调指针、可选事件句柄和用于释放文本/字节集副本的链表。`_thread_GetArgs()` 把易语言数据转换成最多 256 个入参的整数槽；文本与字节集复制到堆内存并挂入链表，析构时统一释放。`线程池_取回参数` / `多线程_还原无限参数`按目标数据类型把槽位还原到易语言变量；`多线程_释放无限参数`显式释放生成的结构。

### 5.5 交付层

- DLL 工程：`ethread.vcxproj`，`ConfigurationType=DynamicLibrary`，目标名 `EThread`，源码层定义 `__E_FNENAME=ethread`。
- 静态库工程：`ethread_static/ethread_static.vcxproj`，`ConfigurationType=StaticLibrary`，目标名 `EThread_static`，Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=ethread`。
- `ALL_BUILD` 同时引用两个工程。
- 工程文件目标工具集主要为 `v141`；静态库 x64 配置使用 `v142`。Windows SDK 目标版本记录为 `10.0.15063.0`。
- 发布 ZIP 当前包含 `lib/EThread.fne`、`static_lib/EThread_static.lib` 和易语言示例文件。

## 6. 核心数据模型

### 6.1 `ThreadPool`

| 字段/状态 | 含义 |
|---|---|
| `workers` | 工作线程列表；容量由初始化的 `maxCount` 固定预留 |
| `tasks` | 待执行任务 FIFO 队列 |
| `queue_mutex` | 任务队列互斥锁 |
| `workers_mutex` | 工作线程列表互斥锁 |
| `condition` | 任务到达/销毁时唤醒线程 |
| `idlThrNum` | 原子空闲线程数量 |
| `state` | `ready`、`working`、`createing`、`destroying`、`suspending` |
| `POOL_DESTROY_MODE` | `WAIT=0`、`DETACH=1`、旧代码枚举中还保留 `SUSPEND=2`、`TERMINATE=3`、`WAIT_MSG=4` |

`create()` 默认最小线程数 5、最大容量 10；最小数不合法时回落 5，最大容量超过 `0x7fff` 截断，最大容量小于最小数时提升到最小数。线程工作循环只在 `createing/working` 状态运行；销毁先广播唤醒，再按模式处理，最终清队列、清线程列表、回到 `ready`。

### 6.2 `THREAD_POOL_INFO`

`Vacant` 空闲线程数、`ExecuteCount` 执行线程数、`QueueCount` 队列任务数、`size` 当前线程数、`MaxSize` 容量、`IsVacant` 是否空闲、`State` 状态枚举值。易语言类型映射在 `ethread_dtType.cpp` 中以中文/英文成员名同时描述。

### 6.3 `THREAD_ARG_STRUCT`

`count` 为参数槽数量；`arr` 为 `int` 槽数组；`pfn` 为易语言子程序地址；`hEvent` 用于等待“线程已开始执行”或相关同步；`node` 为复制数据链表头。基础标量占一个槽，64 位数值/日期占两个槽，文本和字节集通过链表复制后以地址占槽。`_thread_GetArgs()` 对参数数量设置 256 的上限。

### 6.4 `LIB_INFO`

`ethread_dllMain.cpp` 中的 `g_LibInfo_ethread_global_var` 固定登记 GUID `5F99C1642A2F4e03850721B4F5D7C3F8`、版本 3.2.502、库名、作者、系统要求、命令类别、命令数组、函数指针数组、自定义类型数组、常量数组和通知函数。

## 7. 公开 API 清单

命令索引由 `ethread_cmd_typedef.h` 定义；以下保留易语言展示名与源码英文名。索引 8–20、29–35 属于 `线程池` 对象方法或配套命令。

### 7.1 基础线程与同步（0–7）

| 索引 | 易语言命令 | 源码实现 | 作用 |
|---:|---|---|---|
| 0 | 启动线程 | `ethread_CreateThread_0_ethread` | 创建线程，支持可选整数参数和可选线程句柄 |
| 1 | 创建进入许可证 | `ethread_CreateCriticalSection_1_ethread` | 分配并初始化 `CRITICAL_SECTION` |
| 2 | 删除进入许可证 | `ethread_DeleteCriticalSection_2_ethread` | 删除并释放临界区 |
| 3 | 进入许可区 | `ethread_EnterCriticalSection_3_ethread` | 进入临界区 |
| 4 | 退出许可区 | `ethread_LeaveCriticalSection_4_ethread` | 离开临界区 |
| 5 | 等待线程 | `ethread_WaitThread_5_ethread` | 等待线程句柄结束 |
| 6 | 强制结束线程 | `ethread_TerminateThread_6_ethread` | 调用 `TerminateThread` |
| 7 | 关闭线程句柄 | `ethread_CloseThreadHandle_7_ethread` | 调用 `CloseHandle` |

### 7.2 线程池对象（8–20）

| 索引 | 易语言命令 | 源码实现 | 作用 |
|---:|---|---|---|
| 8 | 线程池构造函数 | `ethread_ThreadPoolConsturct_8_ethread` | 初始化复合数据槽为空 |
| 9 | 线程池复制构造函数 | `ethread_ThreadPoolCopy_9_ethread` | 按右侧池的当前/最大容量和回调创建新池 |
| 10 | 线程池析构函数 | `ethread_ThreadPoolFree_10_ethread` | `delete` 池并清槽 |
| 11 | 初始化 | `ethread_ThreadPool_Init_11_ethread` | 建池，默认 5/10，可选完成回调 |
| 12 | 添加任务 | `ethread_ThreadPool_AddTask_12_ethread` | 封送参数、入队、任务完成后回调 |
| 13 | 销毁 | `ethread_ThreadPool_Destroy_13_ethread` | 等待或异步自生自灭后销毁 |
| 14 | 取空闲线程数 | `ethread_ThreadPool_GetVacant_14_ethread` | 读空闲计数 |
| 15 | 取执行线程数 | `ethread_ThreadPool_GetExecuteCount_15_ethread` | 当前线程数减空闲数 |
| 16 | 取队列任务数 | `ethread_ThreadPool_GetQueueCount_16_ethread` | 读待执行队列长度 |
| 17 | 取线程池容量 | `ethread_ThreadPool_size_17_ethread` | 读当前工作线程数 |
| 18 | 取线程池最大容量 | `ethread_ThreadPool_MaxSize_18_ethread` | 读 `workers.capacity()` |
| 19 | 是否空闲 | `ethread_ThreadPool_IsVacant_19_ethread` | 队列为空且执行线程数为 0 |
| 20 | 取状态 | `ethread_ThreadPool_GetState_20_ethread` | 返回池状态枚举值 |

### 7.3 扩展线程与消息循环（21–28）

| 索引 | 易语言命令 | 源码实现 | 作用 |
|---:|---|---|---|
| 21 | 启动线程Ex | `ethread_CreateThreadEx_21_ethread` | 支持启动后挂起、等待启动、等待结束、处理消息和变长参数 |
| 22 | 等待线程Ex | `ethread_WaitThreadEx_22_ethread` | 返回等待结果；源码使用 Win32 等待值 |
| 23 | 挂起线程 | `ethread_SuspendThread_23_ethread` | 调用 `SuspendThread` |
| 24 | 唤醒线程 | `ethread_ResumeThread_24_ethread` | 调用 `ResumeThread` |
| 25 | 打开线程 | `ethread_OpenThread_25_ethread` | 以线程 ID 获取 `THREAD_ALL_ACCESS` 句柄 |
| 26 | 创建线程消息循环 | `ethread_CreateThreadMsgLoop_26_ethread` | 创建线程并运行 `GetMessageW` 循环 |
| 27 | 退出线程消息循环 | `ethread_QuitThreadMsgLoop_27_ethread` | 投递 `WM_QUIT` |
| 28 | 投递线程消息 | `ethread_PostThreadMsg_28_ethread` | 调用 `PostThreadMessageW` 投递消息 |

### 7.4 线程池扩展与无限参数（29–35）

| 索引 | 易语言命令 | 源码实现 | 作用 |
|---:|---|---|---|
| 29 | 挂起任务 | `ethread_ThreadPool_Suspend_29_ethread` | 调用线程池挂起 |
| 30 | 唤醒任务 | `ethread_ThreadPool_Resume_30_ethread` | 设计上恢复线程池 |
| 31 | 取信息 | `ethread_ThreadPool_GetInfo_31_ethread` | 写出 `THREAD_POOL_INFO` |
| 32 | 线程池_取回参数 | `ethread_GetArgument_32_ethread` | 回调内按类型恢复任务参数 |
| 33 | 多线程_生成无限参数 | `ethread_Make_Arguments_33_ethread` | 创建参数结构并返回整数指针 |
| 34 | 多线程_还原无限参数 | `ethread_Restore_Argument_34_ethread` | 委托索引 32 的恢复逻辑 |
| 35 | 多线程_释放无限参数 | `ethread_Free_Argument_35_ethread` | 删除参数结构及其副本 |

## 8. 关键真实调用链

### 8.1 支持库加载与命令分发

1. 易语言加载 `EThread.fne`。
2. DLL 导出 `GetNewInf()`，返回 `g_LibInfo_ethread_global_var`。
3. 易语言读取 `m_pBeginCmdInfo`、`m_pCmdsFunc`、常量和自定义类型。
4. `ETHREAD_DEF` 保证同一索引在描述、参数、函数指针和静态编译名称数组中保持对应。
5. 命令调用进入 `ethread_*_<index>_ethread(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。

### 8.2 普通线程

```text
易语言“启动线程”
  → ethread_CreateThread_0_ethread
  → 读取子程序地址/整数参数/可选句柄变量
  → new TMP_THREAD_STRUCT
  → CreateThread(pfn_thread, ptr)
  → 工作线程 _thread_call(pfn, pArg)
  → 删除 TMP_THREAD_STRUCT
  → 无句柄接收变量时 CloseHandle
```

### 8.3 扩展线程与参数

```text
易语言“启动线程Ex” + flags + 变长参数
  → _thread_GetArgs(nArgCount, pArgInf, 3, pfn)
  → THREAD_ARG_STRUCT / 参数复制链表
  → 按 flags 选择 CREATE_SUSPENDED、创建启动事件或等待结束
  → CreateThread(pfn_threadProc, args)
  → _threadpool_call(args->pfn, args->arr, args->count)
  → 关闭事件、delete args
```

### 8.4 线程池任务

```text
线程池初始化
  → pool_getobj(m_ppCompoundData[0], count, maxCount, callback)
  → ThreadPool::create → reserve(maxCount) → addThread(count)

线程池添加任务
  → 校验子程序指针
  → _thread_GetArgs(..., argStart=2)
  → pool->commit(lambda)
  → queue.emplace(packaged_task)
  → condition.notify_one()
  → 工作线程取 FIFO 任务
  → _threadpool_call(args->pfn, args->arr, args->count)
  → 可选完成回调(任务返回值, 参数结构指针, 保留参数)
  → delete args
```

### 8.5 线程池销毁

```text
ThreadPool_Destroy
  ├─ DETACH/自生自灭：清易语言槽 → 启动 detached 管理线程
  │                    → pool->destroy(WAIT) → delete pool
  └─ 其他模式：pool->destroy(mode) → 唤醒工作线程 → 等待/分离
                         → 清任务队列与 workers → state=ready
                         → delete pool（普通路径）
```

当前提交说明和 README 表达的有效产品语义是“自生自灭”与“等待”两类；`CThreadPool.h` 仍保留挂起/强制结束/等待消息的旧枚举，`destroy()` 的实现对非 `DETACH` 分支统一走等待逻辑。

## 9. 依赖与边界

### 9.1 编译期依赖

- C++ 标准库：`<vector>`、`<queue>`、`<atomic>`、`<thread>`、`<mutex>`、`<condition_variable>`、`<future>`。
- Windows API：`CreateThread`、`WaitForSingleObject`、`WaitForMultipleObjects`、`CreateEventW`、`CloseHandle`、`SuspendThread`、`ResumeThread`、`TerminateThread`、`OpenThread`、`PostThreadMessageW`、`GetMessageW`、`MsgWaitForMultipleObjects`、临界区 API 等。
- 易语言支持库 ABI：`elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/mtypes.h`、`elib/untshare.h` 等。
- 编译器/工程：Visual Studio C++ 工具集 `v141/v142`，Win32/x64 配置，Windows SDK `10.0.15063.0`。

### 9.2 运行期边界

- 源码实现是 Windows 线程模型；虽然部分命令说明保留 Linux 句柄表述，但当前工程没有 Linux 实现分支。
- 易语言回调通过裸函数指针和 32 位整数槽调用，ABI 强依赖目标位宽、调用约定和易语言运行时内存布局。
- 线程句柄、临界区、事件、任务参数副本均需调用方遵守生命周期契约。
- `线程池_取回参数` 只应在初始化时登记的任务完成回调中调用；源码注释明确其他位置可能崩溃。

## 10. 已确认问题、风险与版本漂移

以下是源码静态取证发现，**不是当前核对修复**：

1. `ethread_pool.cpp` 中 `ethread_ThreadPool_Resume_30_ethread()` 实际调用 `pool->suspend()`，与“唤醒任务”命令语义不符；应作为后续复核/修复候选。
2. `ethread_ThreadPool_GetInfo_31_ethread()` 先把 `GetInfo(info)` 写入 `m_int`，随后无条件把 `m_bool` 设为 `true`，返回值形状存在覆盖风险。
3. `ThreadPool` 的 `std::atomic<POOL_ENUM> state` 在无参构造函数中没有显式初始化为 `ready`；C++ 标准/工具集语义需在 Windows 目标环境复核，不能仅凭源码断言运行结果。
4. `destroy()` 的枚举仍包含 `SUSPEND`、`TERMINATE`，但对应分支实现被注释/统一降级到等待；旧命令说明、常量与当前提交说明之间存在历史兼容残留。
5. 参数/句柄大量经 `int` 传递或强转（例如 `HANDLE`、指针、`THREAD_ARG_STRUCT*`）；当前 DLL 是 PE32，x64 工程配置却仍保留这些路径，x64 可用性必须通过目标工具链和运行测试单独确认。
6. `CreateThreadMsgLoop` 在创建线程失败时未释放已分配的 `THREAD_MSGLOOP_ARG` 与事件句柄，需后续故障路径审计。
7. `ethread.fne` 根部已生成 PE32 DLL 的可见字符串只覆盖到线程池初始化/添加任务等较早命令；`out/lib/EThread.fne` 则可见完整的 0–35 命令符号。根部 DLL、`out/lib` DLL、源码与 ZIP 之间存在发布物版本/生成时点差异，使用发布包前应重新核验摘要与命令数量。
8. `out/多线程支持库Ex 3.2.502(EThread).zip` 内含 `lib/EThread.fne`、`static_lib/EThread_static.lib` 和易语言示例；这些是交付证据，不替代源码构建验证。
9. 仓库无自动化测试目录或 CTest/单元测试配置；`易语言调用测试.e` 是二进制示例夹具，不能据此声称测试通过。
10. 仓库存在 `.gitmodules` 的旧子模块声明，但当前源码直接在主仓库中；后续同步/归档应保持远程与实际 Git 结构分开记录。

## 11. 测试与验证边界

### 已完成的只读验证

- 读取并核对 `README.md`、`课程笔记.txt`、`.gitmodules`、解决方案/工程文件、全部可读 C/C++/头文件、命令元数据和库入口。
- 统计真实文件类型与大小；识别 `ethread.fne`/`out/lib/EThread.fne` 为 PE32 DLL，ZIP 为存储模式归档，并读取 ZIP 成员清单。
- 从源码命令宏、函数实现和二进制可见符号三方对照公开命令范围。
- 检查 Git 分支、远程、HEAD 提交和工作树状态。
- 检查旧 `细探-*.md`、`AGENTS.md`：目标根不存在这些文件。

### 当前核对明确未执行

- 未编译 Visual Studio 工程或静态库。
- 未启动 Windows/易语言运行时，未加载 `.fne`，未运行 `.e` 示例。
- 未安装依赖、未修改源码、未修改工程设置、未提交 Git。
- 未把 PE/DLL 反汇编结果当作源码行为；二进制仅作发布物与符号存在性佐证。

因此，本文件的“已确认”是源码/工程/元数据静态证据，“运行正确”“构建通过”“兼容 x64/Linux”均尚未得到当前核对执行证据。

## 12. 后续细探建议

1. 在隔离 Windows 环境用当前 `ethread.sln` 分别构建 DLL 与静态库，记录工具集、目标架构、警告和产物摘要；不要覆盖本仓库既有 `out/` 物料。
2. 以易语言真实工程验证 36 条命令，优先覆盖线程句柄关闭、异常回调、线程池销毁后二次初始化、参数类型/文本/字节集、消息循环和回调生命周期。
3. 单独审计 `Resume`、`GetInfo`、无参构造状态初始化、失败清理和 x64 指针宽度；这些属于源码级候选缺陷，修复前须由用户另行授权，不能在架构建档轮修改。
4. 对根部 `ethread.fne`、`out/lib/EThread.fne`、ZIP 内 DLL 做版本/命令表/哈希对账，确认哪个是 HEAD 对应发布物。
5. 若需要代码图，将由用户决定是否在该外部仓库初始化 `.codegraph/`；当前核对不创建索引目录，避免把研究副产物写入源码参考库。

## 13. 证据路径索引

- 项目说明与版本线索：`README.md`、`课程笔记.txt`
- Git 与工程入口：`.gitmodules`、`ethread.sln`、`ethread.vcxproj`、`ethread_static/ethread_static.vcxproj`、`ALL_BUILD/ALL_BUILD.vcxproj`
- ABI 与命令总表：`include_ethread_header.h`、`ethread_cmd_typedef.h`、`ethread_cmdInfo.cpp`
- DLL 入口与库元信息：`ethread_dllMain.cpp`、`Source_ethread.def`
- 基础线程命令：`ethread_cmdDef.cpp`
- 线程池命令：`ethread_pool.cpp`
- 线程池核心：`CThreadPool.h`
- 参数/类型/常量：`ethread_dtType.cpp`、`ethread_const.cpp`、`elib/fnshare.cpp`
- 已生成交付物：`out/lib/EThread.fne`、`out/多线程支持库Ex 3.2.502(EThread).zip`、`out/lib/`、`out/static_lib/`

> 已吸收当前核对所有旧细探线索（目标根未发现旧细探文件）；后续只维护本文件。
