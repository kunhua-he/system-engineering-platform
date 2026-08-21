# ogrelib 架构档案

> 本文件是 `ogrelib` 项目根目录的唯一架构事实源。本轮只读取源码、工程文件和 Git 元数据，并且只新增本文件；未修改源码、工程、依赖、测试、配置或 Git。文中把“源码已经写出”“仅有声明/元数据”“未验证”明确区分，不能把命令说明表误认为 Direct3D 功能已经实现。

## 1. 项目定位

`ogrelib` 是一个面向易语言的 Windows DirectX 9 3D 支持库工程。它的目标形态是由 Visual Studio 生成一个易语言动态支持库（目标扩展名为 `.fne` 的 Win32 配置）以及一个静态库；通过易语言支持库 ABI 暴露库信息、命令表、自定义数据类型表、命令函数名表和系统通知入口。

当前快照的真实状态是：

- **已经实现**：易语言支持库的元数据骨架、382 个命令/方法的 C ABI 函数符号、649 条参数元数据、69 个自定义数据类型及其成员元数据、`GetNewInf` 信息入口、部分系统通知转发、若干内存/数组/数据辅助函数。
- **仅声明/描述**：命令在 `ogrelib_cmd_typedef.h` 中以统一宏登记，命令中文名、英文名、返回类型、参数类型和说明在 `ogrelib_cmdInfo.cpp` 中登记；这些是编辑器/运行时契约描述，不等于底层 Direct3D 调用。
- **未实现或未验证**：`ogrelib_cmdDef.cpp` 的 382 个命令函数体都没有 Direct3D/D3DX 调用，也没有向 `pRetData` 写入结果；当前未发现测试、构建产物或可在本机验证的 Windows/MSVC 构建记录。

源码内置库信息将其标识为：库名 `DirectX3D支持库`，GUID `2EAE87405D754ad780D8FE57432002EA`，版本 `2.0.0`，要求易语言系统 `3.9`、系统核心支持库 `3.9`，仅支持 Windows，语言编码标志为 `__GBK_LANG_VER`（证据：`ogrelib_dllMain.cpp:31-87`）。

## 2. 总体架构与流程

```text
易语言 IDE / 易语言运行时
        │
        │  加载支持库并查找固定导出 GetNewInf
        ▼
ogrelib.dll/.fne 或静态库适配层
        │
        ├─ GetNewInf()
        │      └─ 返回 LIB_INFO
        │             ├─ 69 个 LIB_DATA_TYPE_INFO（自定义数据类型/枚举）
        │             ├─ 382 个 CMD_INFO（命令和对象方法）
        │             ├─ 382 个 PFN_EXECUTE_CMD（命令函数指针）
        │             └─ 0 个 LIB_CONST_INFO（常量表为空）
        │
        ├─ 易语言根据 CMD_INFO / ARG_INFO 检查并组织 MDATA_INF 参数
        │
        ├─ 调用 ogrelib_<命令>_<索引>_ogrelib(pRetData, nArgCount, pArgInf)
        │      ├─ 当前实现：读取 pArgInf 中的参数指针/数值到局部变量
        │      └─ 当前缺口：未调用 IDirect3D9/D3DX，也未填充返回值
        │
        └─ 系统通知入口 ogrelib_ProcessNotifyLib_ogrelib
               ├─ 接收 NL_SYS_NOTIFY_FUNCTION，保存宿主 PFN_NOTIFY_SYS
               ├─ 通过 fnshare::ProcessNotifyLib 转发并读取调试/发布版本
               ├─ 响应静态编译相关的函数名/通知名/依赖库查询（动态编译分支）
               └─ 其它通知大多为空处理或返回 NR_ERR
```

### 2.1 加载与注册流程

1. 宿主按固定名称寻找 `GetNewInf`（`Source_ogrelib.def:1-4` 只导出该符号）。
2. `GetNewInf()` 返回静态 `LIB_INFO g_LibInfo_ogrelib_global_var`（`ogrelib_dllMain.cpp:31-91`）。
3. `LIB_INFO` 将命令表、函数指针表、数据类型表、常量表和通知函数地址交给易语言。
4. 动态支持库通过 `g_cmdInfo_ogrelib_global_var_fun` 将每个命令索引映射到 `OGRELIB_NAME(index, englishName)` 生成的函数符号。
5. 宿主通过 `NL_SYS_NOTIFY_FUNCTION` 注入 `PFN_NOTIFY_SYS`；`elib/fnshare.cpp` 保存该函数指针，之后可通过 `NotifySys` 与易语言系统交互。

### 2.2 单次命令调用流程（按当前源码）

```text
易语言命令调用
  → 根据命令索引定位 CMD_INFO / g_cmdInfo..._fun[index]
  → 进入 ogrelib_<Name>_<index>_ogrelib
  → 从 pArgInf[0..nArgCount] 读取 m_int / m_float / m_pText /
    m_pBin / m_pCompoundData / m_ppCompoundData / m_pAryData 等字段
  → 当前函数体没有外部 API 调用、状态写入或 pRetData 写入
  → 返回调用者（返回值内容未由本库设置）
```

> 注意：部分对象方法使用 `pArgInf[1]` 作为对象参数，部分全局 D3DX 方法使用 `pArgInf[0]` 作为第一个参数；这是生成代码中的现状，不应在后续重构时未经 ABI 核对而统一偏移。

## 3. 真实目录与文件地图

仓库没有 README、AGENTS.md、CLAUDE.md、测试目录、包管理文件或构建脚本；以下目录树由 Git 文件清单和工程文件人工核对得到。

```text
ogrelib/
├── ogrelib.sln                         # VS 解决方案；动态库 + 静态库两个项目
├── ogrelib.vcxproj                     # 主动态库项目
├── ogrelib.vcxproj.filters             # 主项目筛选器
├── ogrelib.vcxproj.user                # 本地用户工程设置
├── ogrelib_static/
│   ├── ogrelib_static.vcxproj          # 静态库项目，复用上级源码
│   ├── ogrelib_static.vcxproj.filters
│   └── ogrelib_static.vcxproj.user
├── Source_ogrelib.def                  # DLL 模块定义，仅导出 GetNewInf
├── include_ogrelib_header.h            # 统一入口头，连接 elib 与命令宏
├── ogrelib_cmd_typedef.h               # OGRELIB_DEF：382 条命令的单一宏登记表
├── ogrelib_cmdDef.cpp                  # 382 个命令执行函数的生成式骨架
├── ogrelib_cmdInfo.cpp                 # ARG_INFO 649 条 + CMD_INFO 命令元数据
├── ogrelib_dtType.cpp                  # 自定义类型/枚举/成员元数据
├── ogrelib_const.cpp                   # 常量表，目前数量为 0
├── ogrelib_dllMain.cpp                 # DLL 入口、LIB_INFO、GetNewInf、通知入口
└── elib/
    ├── lib2.h                          # 易语言支持库 ABI 基础契约与公共结构
    ├── mtypes.h                        # Windows 基础类型兼容定义
    ├── lang.h                          # 编译语言编码版本，当前 GBK
    ├── krnllib.h                       # 易语言系统核心支持库常量/版本信息
    ├── fnshare.h                       # 通知、内存、文本/字节集/数组辅助内联函数
    ├── fnshare.cpp                     # 通知回调保存与转发实现
    ├── untshare.h                      # 通用窗口/属性辅助代码；本项目未纳入 vcxproj 源文件
    └── PublicIDEFunctions.h             # IDE 公共函数/编辑器通知常量声明；本项目未纳入编译源文件
```

### 3.1 编译单元登记

主项目 `ogrelib.vcxproj:21-42` 编译：`elib/fnshare.cpp`、`ogrelib_cmdDef.cpp`、`ogrelib_const.cpp`、`ogrelib_dllMain.cpp`、`ogrelib_dtType.cpp`、`ogrelib_cmdInfo.cpp`，并包含对应头文件和 `.def`。静态项目 `ogrelib_static/ogrelib_static.vcxproj:21-39` 用 `..\` 相对路径复用同一批源码。

`untshare.h`、`PublicIDEFunctions.h` 虽在项目中显示为头文件，但没有被源文件直接包含，也没有独立编译单元；它们不能据此被视为当前运行路径的一部分。

## 4. 模块职责

| 模块 | 当前职责 | 状态与证据 |
|---|---|---|
| `ogrelib_cmd_typedef.h` | 用 `OGRELIB_DEF(_MAKE)` 统一登记命令索引、中文名、英文符号名、说明、类别、状态、返回类型、参数数目和参数表起点 | **已实现元数据声明**；`OGRELIB_DEF` 共 382 行命令登记（`ogrelib_cmd_typedef.h:12-394`） |
| `ogrelib_cmdDef.cpp` | 为每个登记命令提供 `PFN_EXECUTE_CMD` 兼容的 C ABI 函数 | **函数符号已生成，业务未实现**；382 个函数，函数体只有参数局部变量提取或为空（如 `:21-25`、`:1233-1240`、`:3858-3885`） |
| `ogrelib_cmdInfo.cpp` | 建立参数描述数组和命令描述数组 | **已实现元数据**；`ARG_INFO` 序号 `000..648`，`CMD_INFO` 由 `OGRELIB_DEF(OGRELIB_DEF_CMDINFO)` 展开（`:5-20`、`:877-896`） |
| `ogrelib_dtType.cpp` | 建立 Direct3D 资源对象、几何结构和枚举类型，绑定对象方法索引与成员表 | **已实现元数据**；顶层 `LIB_DATA_TYPE_INFO` `000..068`，数组入口 `:1316-1806` |
| `ogrelib_const.cpp` | 提供预定义常量表 | **空实现/数量为 0**；`g_ConstInfo...` 数组仅占位，`:14-18` |
| `ogrelib_dllMain.cpp` | DLL 生命周期入口；构造 `LIB_INFO`；提供 `GetNewInf`；生成函数指针/名称表；处理库通知 | **部分已实现**；`DllMain` 为空生命周期钩子（`:6-24`），`GetNewInf` 有效（`:89-92`），通知入口部分有效（`:101-177`） |
| `elib/lib2.h` | 易语言支持库 ABI：数据类型编码、参数/命令/类型/库信息结构、通知码、函数原型 | **公共契约已实现**；`MDATA_INF` `:780-824`，`LIB_INFO` `:1248-1315`，通知/命令函数原型 `:1225-1239` |
| `elib/fnshare.h/.cpp` | 通过宿主通知函数申请/释放内存、克隆文本/字节集、访问数组；保存系统通知回调并转发 | **辅助路径已实现**；内联函数在 `fnshare.h:20-169`，回调状态在 `fnshare.cpp:7-70` |
| `elib/mtypes.h` | 补充 `LONG`、`DWORD`、`RECT` 等 Windows 基础类型与宏 | **类型兼容层已实现**；`:1-176` |
| `elib/lang.h` | 语言版本常量 | **已实现**；当前 `__COMPILE_LANG_VER` 为 GBK（`:6-14`） |
| `elib/krnllib.h` | 系统核心支持库 GUID、文件名、版本和控件类型常量 | **公共常量已声明**；`:114-131` |
| `Source_ogrelib.def` | DLL 导出边界 | **已实现**；只导出 `GetNewInf`（`:1-4`） |

## 5. 命令与功能域地图

`OGRELIB_DEF` 的索引是 ABI 关键序号，不能随意重排。按源码登记表可分为以下功能域：

| 索引范围 | 代表对象/功能域 | 主要命令族 | 当前状态 |
|---:|---|---|---|
| 0-10 | `IDirect3DResource9` | 私有数据、设备、级数、优先级、类型、预加载 | 元数据完整；执行体为空 |
| 11-26 | `IDirect3DBaseTexture9` | LOD、过滤类型、私有数据、预加载 | 元数据完整；执行体为空 |
| 27-47 | `IDirect3DCubeTexture9` | 脏区域、立方体面、级别页面、区域读写 | 元数据完整；执行体为空 |
| 48-60 | `IDirect3DIndexBuffer9` | 描述、设备、私有数据、缓冲读写 | 元数据完整；执行体为空 |
| 61-76 | `IDirect3DTexture9` | 纹理级别、页面、区域读写 | 元数据完整；执行体为空 |
| 77-89 | `IDirect3DVertexBuffer9` | 缓冲描述、设备、缓冲读写 | 元数据完整；执行体为空 |
| 90-120 | `IDirect3DVolume9` / `IDirect3DVolumeTexture9` | 体数据、级别、区域读写 | 元数据完整；执行体为空 |
| 121-141 | 顶点声明、纹理设置、页面/锁定区域 | `GetDeclaration`、`SetTexture`、`LockRect` 等 | 元数据完整；执行体为空 |
| 142-224 | `Device` | 创建设备、灯光/材质、场景、渲染状态、资源创建、着色器、适配器查询 | 元数据完整；执行体为空 |
| 225-243 | 着色器、状态块、交换链、像素着色器 | `Apply`、`Capture`、`Present` 等 | 元数据完整；执行体为空 |
| 244 | 纹理层关联工具 | `TextureCombine` | 元数据存在；执行体为空 |
| 245-286 | D3DX 纹理工具 | 纹理需求检查、从文件/内存创建、图像信息、页面/纹理/立体保存 | 部分命令被标记隐藏；执行体为空 |
| 287-288 | 数值/颜色工具 | `TransColor`、`FloatToInt` | 元数据存在；执行体为空 |
| 289-335 | 向量、矩阵、平面数学 | `D3DXVec3*`、`D3DXVec4*`、`D3DXMatrix*`、`D3DXPlane*` | 元数据和类型关联存在；执行体为空 |
| 336-353 | D3DX 网格工具 | 清空、边界盒/球、法线、切条、创建/加载/保存模型 | 元数据存在；执行体为空 |
| 354-381 | `ID3DXMesh` | 克隆、绘制、顶点/索引/属性缓冲读写、优化 | 元数据完整；执行体为空 |

源码还把部分函数标记为 `CT_IS_HIDED`，包括对象构造/析构函数和若干 D3DX 兼容函数；隐藏只影响易语言编辑/调用可见性，不表示函数已有实现。

## 6. 核心数据模型

项目没有自有数据库、配置文件格式、磁盘缓存、资源包或持久化层；其“数据模型”是易语言支持库 ABI 中的内存结构和静态元数据数组。

### 6.1 调用数据：`MDATA_INF`

`elib/lib2.h:780-824` 定义了 1 字节对齐的 `MDATA_INF`：

- 匿名联合包含 `m_byte`、`m_short`、`m_int`、`m_int64`、`m_float`、`m_double`、`m_date`、`m_bool`。
- 文本/字节集使用 `m_pText`、`m_pBin`，只读指针。
- 易语言窗口组件使用 `MUNIT {m_dwFormID, m_dwUnitID}`。
- 复合数据使用 `m_pCompoundData`，数组使用 `m_pAryData`。
- 传引用参数使用 `m_pInt`、`m_ppBin`、`m_ppCompoundData`、`m_ppAryData` 等指针成员。
- `m_dtDataType` 标记数据类型；空白参数为 `_SDT_NULL`，数组/传址场景使用 `DT_IS_ARY`/`DT_IS_VAR`。

这解释了 `ogrelib_cmdDef.cpp` 中大量 `pArgInf[i].m_*` 读取。当前代码只完成 ABI 参数解包，没有把这些值交给 Direct3D。

### 6.2 参数与命令元数据

`ARG_INFO`（`elib/lib2.h:266-292`）包含参数名称、说明、编辑图像、`DATA_TYPE`、默认值和 `AS_*` 传参标记。`CMD_INFO`（`elib/lib2.h:297-364`）包含中文名、英文名、说明、类别、`CT_*` 状态、返回类型、用户级别、参数数目及参数表指针。

`ogrelib_cmdInfo.cpp`：

- 参数数组为 `g_argumentInfo_ogrelib_global_var`，序号从 `/*000*/` 到 `/*648*/`，共 649 条。
- 命令数组为 `g_cmdInfo_ogrelib_global_var`，通过 `OGRELIB_DEF(OGRELIB_DEF_CMDINFO)` 展开，共 382 条。
- `g_cmdInfo_ogrelib_global_var_count` 由 `sizeof` 计算，未硬编码数量。
- 这部分在 `#if !defined(__E_STATIC_LIB)` 下，静态库配置不会编译出同样的动态库元数据数组。

### 6.3 自定义数据类型

`LIB_DATA_TYPE_ELEMENT`（`elib/lib2.h:368-390`）描述成员数据类型、数组规格、中文/英文名、说明、状态和默认值；`LIB_DATA_TYPE_INFO` 的字段含义在 `ogrelib_dtType.cpp:1318-1320` 注释中说明。

`ogrelib_dtType.cpp` 顶层共 69 个类型：

- 几何与数学：`Rect`、`Vector3`、`Vector4`、`Matrix`、`Plane`、`Quaternion`、`ViewPort`。
- 设备与资源对象：`Direct3DSurface`、`Device`、`Light`、`Material`、`IDirect3DResource9`、各类纹理/缓冲/着色器/声明、`ID3DXMesh`、`Direct3DStateBlock`、`Direct3DSwapChain`、`IDirect3DVolume9`。
- 描述结构：`D3DVERTEXBUFFER_DESC`、`D3DVERTEXELEMENT9`、`D3DINDEXBUFFER_DESC`、`D3DPRESENT_PARAMETERS`、`Colour`、`SurfaceDest`、`LockedRect`、`PaletteEntry`、`DisplayMode`、`D3DBOX`、`D3DVOLUME_DESC`、`D3DCAPS9`、`D3DXIMAGE_INFO`、`D3DXATTRIBUTERANGE`、`D3DXINTERSECTINFO`。
- 枚举/常量类型：`LightType`、`DeviceConst`、`RenderState`、`D3DSAMPLERSTATETYPE`、`D3DTEXTUREADDRESS`、`D3DTEXTUREFILTERTYPE`、`D3DTEXTURESTAGESTATETYPE`、`D3DTEXTUREOP`、`D3DTA`、`D3DTSS_TCI`、`D3DTEXTURETRANSFORMFLAGS`、`D3DFORMAT`、`D3DRESOURCETYPE`、`D3DUSAGE`、`D3DMULTISAMPLE_TYPE`、`D3DPOOL`、`D3DTRANSFORMSTATETYPE`、`D3DCUBEMAP_FACES`、`D3DFVF`、`D3DDECLTYPE`、`D3DDECLMETHOD`、`D3DDECLUSAGE`、`D3DX_FILTER`、`D3DXIMAGE_FILEFORMAT`、`D3DXMESH`、`D3DXMESHOPT`。

对象方法通过静态索引数组绑定到命令索引。例如 `Vector3` 绑定 289-301，`Device` 绑定 142-224 及 134，`ID3DXMesh` 绑定 354-381（`ogrelib_dtType.cpp:4-177`）。源码中 `Device` 索引数组包含 `177` 两次而缺少预期的 `197` 位置，这属于应在后续轮次复核的元数据风险，本轮不改源码。

### 6.4 支持库描述：`LIB_INFO`

`LIB_INFO` 定义在 `elib/lib2.h:1248-1315`，本项目实例位于 `ogrelib_dllMain.cpp:31-87`，关键字段如下：

| 字段 | 当前值 | 证据 |
|---|---|---|
| 格式号 | `LIB_FORMAT_VER` | `ogrelib_dllMain.cpp:33` |
| GUID | `2EAE87405D754ad780D8FE57432002EA` | `:34` |
| 版本 | `2.0.0` | `:35-37` |
| 系统要求 | 易语言 `3.9`、核心支持库 `3.9` | `:39-42` |
| 名称/说明 | `DirectX3D支持库` / DirectX9 3D 说明 | `:44-47` |
| 平台/语言 | `_LIB_OS(__OS_WIN)` / `__GBK_LANG_VER` | `:45-47` |
| 数据类型 | `g_DataType...` / count | `:58-59` |
| 命令类别 | 3 类：纹理、模型、其它 | `:61-62` |
| 命令与函数表 | `g_cmdInfo...`、`g_cmdInfo..._fun` | `:64-66` |
| 通知函数 | `ogrelib_ProcessNotifyLib_ogrelib` | `:75` |
| 常量 | `g_ConstInfo...`，数量 0 | `:83-84`、`ogrelib_const.cpp:14-18` |
| 外部依赖文件串 | `NULL` | `ogrelib_dllMain.cpp:86` |

## 7. 接口与 ABI 边界

### 7.1 DLL 导出接口

| 接口 | 形式 | 当前实现 |
|---|---|---|
| `GetNewInf` | `EXTERN_C PLIB_INFO WINAPI GetNewInf()` | 返回 `&g_LibInfo_ogrelib_global_var`（`ogrelib_dllMain.cpp:89-92`） |
| `ogrelib_ProcessNotifyLib_ogrelib` | `EXTERN_C INT WINAPI ...(INT,DWORD,DWORD)` | 通过 `LIB_INFO.m_pfnNotify` 暴露；按 `nMsg` 分支（`:101-177`） |
| 382 个命令函数 | `void(PMDATA_INF, INT, PMDATA_INF)` | 名称由 `OGRELIB_NAME` 生成；当前是空/参数解包骨架 |

`Source_ogrelib.def` 只导出 `GetNewInf`。命令函数不通过 `.def` 直接导出，而是由 `LIB_INFO.m_pCmdsFunc` 函数指针数组提供给宿主。

### 7.2 命令命名规则

`ogrelib_cmd_typedef.h:3-9` 与 `elib/lib2.h:19-35` 组合生成命令符号：

```text
__E_FNENAME = ogrelib
OGRELIB_NAME(index, name)
  → ogrelib_<name>_<index>_ogrelib
示例：ogrelib_CreateDevice_144_ogrelib
```

`include_ogrelib_header.h:22-24` 用同一命令宏展开函数声明。动态库中 `g_cmdInfo_ogrelib_global_var_fun`（`ogrelib_dllMain.cpp:26-29`）按同样的索引顺序生成函数指针数组。

### 7.3 系统通知接口

`elib/lib2.h:1150-1193` 定义库可收到的通知码，主要包括：

- `NL_SYS_NOTIFY_FUNCTION = 1`：注入宿主 `PFN_NOTIFY_SYS`。
- `NL_FREE_LIB_DATA = 6`：释放库附加数据。
- `NL_GET_CMD_FUNC_NAMES = 14`：请求命令函数名数组。
- `NL_GET_NOTIFY_LIB_FUNC_NAME = 15`：请求通知入口函数名。
- `NL_GET_DEPENDENT_LIBS = 16`：请求静态库依赖列表。
- `NL_UNLOAD_FROM_IDE = 17`、`NL_IDE_READY = 18`、`NL_RIGHT_POPUP_MENU_SHOW = 19`、`NL_ADD_NEW_ELEMENT = 20`：IDE 生命周期/交互通知。

当前 `ogrelib_ProcessNotifyLib_ogrelib` 对 `NL_SYS_NOTIFY_FUNCTION` 有实际转发；释放、IDE 通知分支为空；未知通知返回 `NR_ERR`。动态编译分支对 14、15、16 返回命令名数组、函数名文本和空依赖串（`ogrelib_dllMain.cpp:106-123`）。

### 7.4 内存与宿主交互

`elib/fnshare.h:20-39` 将 `NotifySys`、`ealloc`、`efree` 绑定到宿主：

- 申请内存使用 `NotifySys(NRS_MALLOC, size, 0)`，随后清零。
- 释放内存使用 `NotifySys(NRS_MFREE, address, 0)`。
- `CloneTextData`、`CloneTextDataW`、`CloneBinData` 通过宿主分配格式化的易语言文本/字节集数据。
- `GetAryElementInf` 解析易语言数组头部的维数和各维长度。
- `GetBinData`、`allocArray` 基于上述布局复制或创建数组数据。

这些辅助函数是源码中少数具有实际运行逻辑的部分，但它们依赖宿主提供通知函数；脱离易语言运行时不能独立验证。

## 8. 构建与依赖边界

### 8.1 工程配置

| 项目 | 输出类型 | 配置/平台 | 关键设置 |
|---|---|---|---|
| `ogrelib.vcxproj` | `DynamicLibrary` | Debug/Release + Win32/x64 | `PlatformToolset=v141`，Windows SDK `10.0.15063.0`，Unicode；Win32 设置 `TargetExt=.fne` |
| `ogrelib_static/ogrelib_static.vcxproj` | `StaticLibrary` | Debug/Release + Win32/x64 | `PlatformToolset=v141`，Windows SDK `10.0.15063.0`；Win32 定义 `__E_STATIC_LIB` |
| `ogrelib.sln` | 解决方案 | `Debug|x86`、`Debug|x64`、`Release|x86`、`Release|x64` | x86 映射到工程的 Win32，x64 映射到 x64 |

工程级证据：主项目 `ogrelib.vcxproj:43-75`、`:95-105`、`:109-198`；静态项目 `ogrelib_static/ogrelib_static.vcxproj:40-72`、`:92-163`；解决方案映射 `ogrelib.sln:10-32`。

### 8.2 编译器/系统依赖

源码明确依赖或假设：

- Windows API 类型/宏和头文件：`elib/lib2.h:61-68` 包含 `<windows.h>`、`<stdio.h>`、`<math.h>`；`mtypes.h` 又提供一组兼容类型。
- C/C++ 编译器 ABI：`EXTERN_C`、`WINAPI`、`__declspec`/Visual Studio 工程约定和 1 字节 `MDATA_INF` 布局。
- 易语言运行时：`PFN_NOTIFY_SYS`、`NRS_MALLOC/NRS_MFREE/NRS_GET_PRG_TYPE` 等通知码。
- Direct3D 9 / D3DX 语义：由命令名、类型名、注释和数据类型表描述，但仓库中没有 `d3d9.h`、`d3dx9.h`、`.lib`、`.dll` 或显式链接库配置。

### 8.3 当前发现的工程风险

1. 主项目的 Win32 配置设置了 `ModuleDefinitionFile=Source_ogrelib.def`（`ogrelib.vcxproj:121-126`、`:146-153`），但 x64 配置没有该设置（`:171-175`、`:191-196`）。x64 是否仍正确导出 `GetNewInf` 未验证。
2. 主项目仅在 Win32 Debug/Release 定义 `__E_FNENAME=ogrelib`；x64 配置的预处理器定义没有 `__E_FNENAME`（`:109-114`、`:132-139` 与 `:159-164`、`:177-183`）。而 `elib/lib2.h:23-25` 明确要求先定义该宏。x64 构建可行性未验证。
3. 静态项目 Win32 定义 `__E_STATIC_LIB;__E_FNENAME=ogrelib`，但 x64 配置的预处理器定义只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有 `__E_STATIC_LIB`/`__E_FNENAME`（`ogrelib_static/ogrelib_static.vcxproj:92-96`、`:109-115`、`:130-135`、`:145-151`）。静态 x64 目标与源码条件编译的契合性未验证。
4. 静态项目 x64 配置为 `<PrecompiledHeader>Use</PrecompiledHeader>` 并指定 `pch.h`（`:134-137`、`:151-154`），但 Git 文件清单中没有 `pch.h`。是否由外部环境提供未验证。
5. `.vcxproj` 未声明 `AdditionalDependencies` 中的 Direct3D/D3DX 库；当前命令体也没有实际调用这些 API，因此不能据此断言缺库链接错误，但一旦补齐功能必须明确链接边界。
6. 代码文件是 GBK/本地代码页文本，`elib/lang.h` 也将编译语言设为 GBK；在非 Windows/非对应代码页工具链中直接读取或编译可能出现编码问题。

## 9. 实现状态矩阵

| 能力 | 证据 | 状态 |
|---|---|---|
| 导出 `GetNewInf` | `Source_ogrelib.def:1-4`、`ogrelib_dllMain.cpp:89-92` | 已实现 |
| 返回库版本/GUID/名称/平台元信息 | `ogrelib_dllMain.cpp:31-87` | 已实现 |
| 命令名称、参数、返回类型元数据 | `ogrelib_cmd_typedef.h`、`ogrelib_cmdInfo.cpp:5-896` | 已实现为描述数据 |
| 自定义数据类型/枚举成员元数据 | `ogrelib_dtType.cpp:180-1805` | 已实现为描述数据 |
| 命令函数符号和函数指针数组 | `ogrelib_cmdDef.cpp:6-3885`、`ogrelib_dllMain.cpp:26-29` | 符号/绑定已实现 |
| Direct3D 设备/资源实际创建 | 命令体仅有参数提取，无 D3D 调用 | 未实现 |
| D3DX 纹理/模型/数学实际计算 | `ogrelib_cmdDef.cpp:2264-3885` 仅有参数提取/空体 | 未实现 |
| 返回值写回 `pRetData` | 全仓库命令体无 `pRetData->` 写入 | 未实现 |
| `NotifySys` 回调保存和转发 | `elib/fnshare.cpp:11-70` | 已实现，但依赖宿主 |
| 宿主内存/数组辅助 | `elib/fnshare.h:25-169` | 已实现，但依赖宿主 |
| DLL 生命周期资源初始化/释放 | `DllMain` 各分支为空；通知释放分支为空 | 仅声明/空钩子 |
| 常量资源表 | `ogrelib_const.cpp:14-18` 数量为 0 | 空实现 |
| 单元测试/集成测试 | 仓库无测试文件 | 未提供 |
| Windows/MSVC 构建可复现性 | 当前环境为 macOS；未执行 VS 构建 | 未验证 |

## 10. 测试与验证

### 10.1 仓库现状

- Git 跟踪文件共 23 个源码/工程文件（不含 `.git` 内部文件）。
- 未发现 `test`、`tests`、`spec`、CI 配置、CTest、GoogleTest、Catch2 或自定义验收脚本。
- 工程只有 Debug/Release 和 Win32/x64 配置，没有测试项目。

### 10.2 本轮执行的只读检查

本轮没有安装依赖、启动服务、生成构建物或修改源码；执行的是源码与 Git 静态盘点：

- 读取 `ogrelib.sln`、两个 `.vcxproj`、两个 `.filters`、`.def`、公共头和所有 C/C++ 源码。
- 统计并核对：`OGRELIB_DEF` 382 条、命令函数 382 个、参数编号 `000..648` 共 649 条、顶层数据类型 `000..068` 共 69 个、常量数量 0。
- 对 `ogrelib_cmdDef.cpp` 的函数体做人工抽样及静态检查：函数体仅存在 `pArgInf[i].m_*` 局部变量读取或为空，未发现 `pRetData` 写入、Direct3D/D3DX API 调用、错误码处理或资源释放调用。
- 检查 `git status --short --branch`：初始工作树干净，分支为 `master`，跟踪 `origin/master`。
- 检查远程：`git ls-remote origin HEAD refs/heads/master` 与本地 `HEAD` 一致。

### 10.3 未执行事项

以下事项必须在 Windows + Visual Studio 环境中另行验证，不能用本档案替代：

1. `ogrelib.sln` 的四种解决方案配置能否编译。
2. Win32 `.fne` 是否成功导出并由易语言加载。
3. x64 配置的 `__E_FNENAME`、`.def`、预编译头和 ABI 是否成立。
4. `GetNewInf` 返回的 `LIB_INFO` 是否能被目标易语言版本接受。
5. `MDATA_INF` 传参布局、对象引用、数组与字节集读写是否与易语言运行时一致。
6. Direct3D 9/D3DX 的实际运行行为——当前命令函数没有底层实现，因此目前无法做功能验证。

## 11. Git 基线与证据索引

### 11.1 版本基线

| 项目 | 值 |
|---|---|
| 本地分支 | `master` |
| HEAD | `ae846126263834c553756de9dcd0931a6d699502` |
| HEAD 时间 | `2022-12-19T16:56:32+08:00` |
| 提交主题 | `初始化仓库` |
| 作者 | `精易科技 <413188828@qq.com>` |
| 远程 | `https://gitee.com/JYtechnology/ogrelib.git` |
| 远程 `HEAD` | `ae846126263834c553756de9dcd0931a6d699502` |
| 基线状态 | 建档前 `git status` 干净；本档案为唯一新增文件 |

### 11.2 关键证据路径

- 库出口与版本/注册：`Source_ogrelib.def:1-4`；`ogrelib_dllMain.cpp:26-177`。
- 命令单一登记表：`ogrelib_cmd_typedef.h:3-394`。
- 命令函数骨架：`ogrelib_cmdDef.cpp:1-3886`。
- 参数/命令元数据：`ogrelib_cmdInfo.cpp:1-897`。
- 类型/枚举元数据：`ogrelib_dtType.cpp:1-1811`。
- 统一包含入口：`include_ogrelib_header.h:1-26`。
- ABI 基础结构：`elib/lib2.h:1-35`、`:149-292`、`:297-390`、`:740-824`、`:1225-1318`。
- 宿主通知/内存辅助：`elib/fnshare.h:20-169`、`elib/fnshare.cpp:1-71`。
- 工程配置：`ogrelib.sln:1-40`、`ogrelib.vcxproj:21-202`、`ogrelib_static/ogrelib_static.vcxproj:21-167`。
- 项目文件清单：`git ls-files`；当前无 README、测试或既有 `细探-*.md`，因此本轮不存在需吸收或删除的旧细探文档。

## 12. 后续复核优先级

1. **P0：确认项目意图**——这是“DirectX3D 支持库完整实现”还是“从其他库生成的接口骨架”。当前元数据声称功能丰富，但执行层全部为空，二者存在明显落差。
2. **P0：先修复/核对构建契约再实现功能**——明确 `__E_FNENAME`、`__E_STATIC_LIB`、x64 `.def`、预编译头和 Direct3D/D3DX 链接库。
3. **P1：逐命令补齐真实调用边界**——按资源生命周期、COM 引用计数、易语言复合数据创建/释放、`pRetData` 写回和错误返回逐组实现，不能只把局部参数变量保留为“已实现”。
4. **P1：校验命令索引与类型方法索引**——尤其是 `Device` 数组中的重复/缺失索引，以及 125-141 等边界命令的对象归属。
5. **P1：建立 Windows 验收工程**——至少覆盖 `GetNewInf` 加载、命令表/类型表计数、一个资源创建-释放闭环、纹理读写、D3DX 数学函数和静态库链接。
6. **P2：补齐常量表或明确全部常量由枚举数据类型承载**——当前 `g_ConstInfo...` 数量为 0，但大量“常量数据类型”存在于 `g_DataType...` 中，需确认这是设计选择还是遗漏。

本轮结论：`ogrelib` 当前是“易语言 DirectX3D 支持库的 ABI/编辑器元数据与命令骨架”，不是已验证可运行的 DirectX 9 适配实现。