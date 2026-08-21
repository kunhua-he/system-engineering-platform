# e-packager 架构归档

> 本文是目标项目唯一架构事实文档。源码路径、类名、函数名、字段名、命令和 JSON 键保留原文；说明、结论、风险和验证记录使用中文。旧 `细探-*.md` 未发现，本轮不删除任何文件。

## 1. 项目定位

`e-packager` 是 Windows C++20 命令行工具，将易语言 `.e` / `.ec` 工程解析为可读、可版本管理的目录工程，也将目录工程恢复为 `.e`；本地基线支持依赖派生内容导出、二进制资源索引、支持库公开接口文本导出、目录一致性比较、往返验证和自更新。源码预检、语义校验、XML 轻量解析及 AutoLinker 无头编译检查属于已核对但尚未合入本地基线的远程版本能力。

本地基线是 `master` 提交 `ffb50ab812fbaa24e26af30138c0790ab20f2b93`（2026-07-20 17:19:13+08:00，`优化bug反馈的ISSUE模版`）。远程 `origin/master` 通过本机代理 `127.0.0.1:4780` 独立浅克隆核对为 `5ca7864d682cbe6570140f7f6e15c05f9762b873`（2026-08-17 18:07:29+08:00，`新增易语言大模型基准评分参考链接`），本地落后远程。远程快照仅作版本取证，不是第二事实源；本文件按当前本地源码描述，并在末尾记录远程差异。

## 2. 总体流程图

```text
命令行 / 拖放 / 无参入口
        │
        ▼
main.cpp::MainImpl → RunCommand
        │
        ├─ unpack / 拖放 .e/.ec
        │      └─ DoUnpackInternal
        │          ├─ e2txt::Generator::GenerateBundle
        │          │   └─ 读取文件 → 解密 → 解析 section → ProjectBundle
        │          ├─ BundleDirectoryCodec::WriteBundle
        │          │   └─ project/src/image/audio/header 元数据与文件
        │          ├─ WorkspaceProjectSupport::WriteWorkspaceFiles
        │          │   └─ info.json + AGENTS.md + tool/e-packager.exe
        │          └─ RefreshDependencyArtifacts
        │              ├─ ecom/ 易模块工作区
        │              └─ elib/ 支持库公开接口文本
        │
        ├─ pack / 无参回包
        │      └─ DoPack
        │          ├─ ValidateInfoJsonVersion + ResolvePackOutputPath
        │          ├─ BundleDirectoryCodec::ReadBundle
        │          ├─ Restorer::RestoreBundleToBytes
        │          │   └─ 原生快照复用，或源码预检 → 语义模型 → section 序列化
        │          ├─ EncodeSourceBytesForWrite（可选密码封装）
        │          └─ 写出 .e；.ec 工作区走 RestoreBundleToBytesForEcBridge 后输出 .e
        │
        ├─ update
        │      └─ 读目录 → 增加 ECom/ELib/image/audio → 清理原生字节快照
        │          → 重写目录 → 刷新 ecom/elib 派生内容
        │
        ├─ compare-bundle / roundtrip / verify-roundtrip
        │      └─ 解析、恢复、再解析或目录树比较
        │
        ├─ decrypt-fne / 拖放 .fne
        │      └─ SupportLibraryPublicInfo → x86 支持库动态加载 → elib 文本
        │
        └─ /update
               └─ UpdateCheck → GitHub Release → SelfUpdater 后台替换
```

## 3. 目录地图与分层

```text
e-packager/
├─ src/
│  ├─ main.cpp                         CLI 调度、工作区编排、比较和验证
│  ├─ e2txt.h/.cpp                     .e/.ec 二进制读取、section 解析、文本模型
│  ├─ e2txt_restore.cpp                文本/ProjectBundle 恢复、二进制序列化
│  ├─ EFolderCodec.h/.cpp              ProjectBundle ↔ 目录工程
│  ├─ WorkspaceProjectSupport.*        info.json、AGENTS.md、tool 与默认输出
│  ├─ SupportLibraryPublicInfo.*       .fne/.fnr/.dll 公开接口导出和依赖解析
│  ├─ BundlePathUtils.*                Windows 路径清理、保留名、冲突改名
│  ├─ PathHelper.*                     UTF-8/宽字符、注册表、易模块候选路径
│  ├─ UpdateCheck.*                    GitHub Release 查询与版本比较
│  └─ SelfUpdater.*                    Win32 自更新脚本调度
├─ elib/lib2.h                         易语言支持库 ABI 数据结构
├─ thirdparty/json.hpp                 nlohmann::json 单头文件依赖
├─ e-packager.vcxproj / .sln           Visual Studio 工程
├─ README.md                            用户命令和目录契约
├─ AGENTS.md                            工程编辑规范、编译与全量测试建议
└─ test.e / test.bak / test.png         本地样例/夹具；不是自动化测试套件
```

远程版本在上述本地分层上新增 `SourceExpressionParser.*`、`SourcePreflightValidator.*`、`SourceSemanticValidator.*`、`SimpleXmlDocument.*`、`AutoLinkerCompileCheck.*` 五组模块，并把 `main.cpp`、`e2txt_restore.cpp` 等接入预检/编译检查；这些文件不在当前本地基线，不能写成本地已实现能力。

## 4. 核心数据模型与持久化

### 4.1 `ProjectBundle`

`src/e2txt.h` 中的 `e2txt::ProjectBundle` 是目录编排和回包的核心内存模型，主要字段为：

- `sourcePath`、`sourceFileKind`（`E`/`EC`）、`projectName`、`projectNameStored`、`versionText`、`bundleFormatVersion`；
- `dependencies`：`DependencyKind::ELib`（支持库）和 `DependencyKind::ECom`（易模块），含 `name`、`fileName`、`guid`、`versionText`、`path`、`resolvedPath`、`localWorkspace`、`reExport`、`definedIds`；
- `sourceFiles`（`BundleSourceFile`：`key`、`logicalName`、`relativePath`、`content`）与 `formFiles`（`BundleFormFile`：XML 文本）；
- 四个固定源码表：`dataTypeText`、`dllDeclareText`、`constantText`、`globalText`；
- `resources`（`BundleBinaryResource`，`Image`/`Sound`、逻辑常量名、稳定 `key`、二进制 `data`）；
- 过滤器树 `folderAllocatedKey`、`folders`、`rootChildKeys` 和 `windowBindings`；
- `.e` 原生保真快照：`nativeSourceBytes`、`nativeSourceSnapshots`、`nativeProgramHeader`、`nativeGlobalSnapshots`、`nativeStructSnapshots`、`nativeDllSnapshots`、`nativeConstantSnapshots`、`nativeBundleDigest`；
- `.ec` 公开接口 `publicHeaderText`。

`ComputeBundleDigest` 对可见目录内容做稳定摘要；`nativeBundleDigest` 用于判断原生快照能否安全复用。

### 4.2 目录持久化契约

`BundleDirectoryCodec::WriteBundle` 写出：

- `project/.module.json`：工程名、版本、来源路径和依赖；兼容读取旧的 `project/模块.json`、`src/模块.json`；
- `project/_meta.json`：`formatVersion=3`、来源类型、源码/窗体清单、过滤器树、窗口绑定、`nativeBundleDigest`；
- `project/.native_source.bin`、`.native_source_map.json`、`.native_symbol_map.json`：可选原生快照；
- `src/*.txt`、`src/*.xml` 和四个固定文件 `src/.数据类型.txt`、`src/.DLL声明.txt`、`src/.常量.txt`、`src/.全局变量.txt`；
- `image/list.json`、`audio/list.json` 及对应二进制文件；索引条目包含 `key`、`logicalName`、`relativePath`、`comment`、`isPublic`、`order`；
- `.ec` 额外写 `header/header.txt`；工作区辅助层再写 `info.json`、`AGENTS.md`、`tool/e-packager.exe`。

`BundleDirectoryCodec::ReadBundle` 按 JSON 清单读取，加载文本和二进制内容，解析快照，按 `order` 合并图片/音频资源，最后自动发现 `src/**/*.txt`/`src/**/*.xml` 中未登记的新文件。派生目录 `ecom/`、`elib/` 不参与主回包，只作为依赖解析和查阅辅助。

路径安全由 `BundlePathUtils::SanitizeRelativePath`、`MakeUniqueRelativePath` 和 `ReserveBundleRelativePaths` 负责：清除非法字符、`.`/`..`、Windows 保留设备名和尾部空格/点号；对保留元数据路径预占用，冲突文件追加 `_2` 等后缀。

## 5. 真实读取、写入和执行调用链

### 5.1 `.e` / `.ec` 解包

1. `Generator::GenerateBundle` 读取字节；`DecodeEncryptedSourceBytes` 识别普通 `.e`、E 标准加密和 `.ec` 加密，按 `ReadOptions.password` 使用 MD5 派生 secret id 与 RC4 状态解密。
2. `ParseModuleSectionsFromBytes` 读取文件头和 section；`ByteReader` 负责有边界的整数、动态字节、动态文本、BSTR 和文本数组读取。
3. 解析 program、resource、folder、event、class publicity、losable 等 section，构建 `ProjectBundle` 并保留原生字节/快照。
4. `.ec` 在 `DoUnpackInternal` 中先生成 EC bundle，再经 `RestoreBundleToBytesForEcBridge` 桥接为临时 `.e`，重新解析为可编辑 bundle；最终保留 `SourceFileKind::EC` 和 `publicHeaderText`。
5. `WriteBundle` 写出目录；`WriteWorkspaceFiles` 查询源文件尺寸、修改时间、MD5，生成 `info.json` 和面向 AI 的 `AGENTS.md`。
6. 默认 `.e` 解包会清理并刷新 `ecom/` 与 `elib/`；`--main-only` 将 `writeDependencyArtifacts`、`unpackDependencyModules` 置为 false，不触碰这两类派生内容。

### 5.2 目录回包

1. `DoPack` 先校验 `info.json` 版本（当前支持版本 `1`），并按 `.ec` 工作区规则把目标扩展为 `.e`。
2. `ReadBundle` 读取目录；`.ec` 调 `RestoreBundleToBytesForEcBridge`，普通 `.e` 调 `RestoreBundleToBytes`。
3. `RestoreBundleToBytesInternal` 首先检查 `CanReuseNativeBundleSnapshot`；未改变的工程直接复用原生字节，避免无意义重建。
4. 发生源码/资源/依赖变化时，先构建 `Document` 与 `RestoreDocumentModel`，再按 section 顺序序列化。回包前保留源码结构、窗口 XML、依赖、常量、资源、目录树和可复用的未修改方法快照；失败返回结构化 `outError`，不伪造成功。
5. `EncodeSourceBytesForWrite` 可在最后对普通 `.e` 或 `.ec` 外层加密码；目录 `.ec` 的实际输出仍是 `.e`。

### 5.3 update 与资源

`RunUpdate` 读 `ProjectBundle`，逐项处理 `--add-ecom`、`--add-elib`、`--add-image`、`--add-audio`：依赖以 `IsEquivalentDependency` 去重，资源以 `logicalName` 区分同类冲突，并支持 `资源名=文件路径`。新增依赖或资源后调用 `ClearNativeByteReuseState`，强制后续语义重建，避免新增常量资源被旧快照吞掉；随后重写目录并刷新 `ecom/`/`elib/`。

### 5.4 依赖导出与并发

- `PathHelper::BuildModuleFileLookupCandidates` 按源文件目录、`ecom/`、`模块/` 及祖先目录查找 `.ec`；`ExportDependencyModules` 去重绝对路径、生成安全目录名并递归调用 `DoUnpackInternal`。
- `RunFixedThreadTasks` 用原子任务索引和固定线程数（默认 `kDefaultDependencyExportThreadCount=4`）并行导出，收集首个异常；结果按任务数组回收后统一追加运行警告。
- `SupportLibraryPublicInfo::ExportDependencies` 查找 `.fne`/`.fnr`/`.dll`，加载 `elib/lib2.h` 定义的 x86 支持库 ABI，读取命令、常量、数据类型、成员和事件，输出 `elib/*.txt` 并回写 `resolvedPath`/`localWorkspace`。

## 6. CLI、协议与边界

`main.cpp::RunCommand` 的公开入口：

| 命令 | 行为 |
|---|---|
| 无参数 | `RunDefaultPack`，从当前目录或 `tool/` 识别 `info.json`/`src`/`project`，输出到 `pack/` |
| `unpack <input.e|input.ec> <output-dir>` | 解包，可带 `--password`、`--main-only` |
| `pack <input-dir> <output.e|output.ec>` | 目录回包，可带 `--password` |
| `update <input-dir>` | 刷新依赖，可重复传 `--add-ecom`、`--add-elib`、`--add-image`、`--add-audio` |
| `decrypt-fne <input.fne> [output.txt]` | Win32 导出支持库公开接口 |
| `compare-bundle <input> <dir>` | 解析源文件并比较 bundle 摘要/首个差异 |
| `roundtrip <input> <work-dir> <output>` | 解包后立即回包 |
| `verify-roundtrip <input> <work-dir> <output>` | 解包、回包、再次解包、目录树比较 |
| `/update [--force]`、`self-update` | Win32 后台自更新；x64 编译提示不启用 |
| `version`、`help` | 版本和帮助 |
| 单参数拖放 `.e/.ec` | 输出到源文件同目录同名目录 |
| 单参数 `.fne` | 输出同目录同名 `.txt` |

所有命令统一返回进程退出码，并通过 `PrintStringResult` 输出 `label: ...`；`MainImpl` 在非版本调用时输出版本，收集并打印 `e2txt::ConsumeRuntimeWarnings`，Win32 非预发布版本还异步查询最新 tag，最多等待 1500ms，不阻塞主命令超过该等待窗口。

## 7. 技术栈与依赖边界

- 平台：Windows；MSVC `v145`、ISO C++20、`MultiByte`；Release/Debug 均有 Win32 与 x64 配置。
- 外部代码：`thirdparty/json.hpp`（nlohmann::json 单头文件）；`elib/lib2.h` 为易语言支持库 ABI 头，不是通用第三方包管理依赖。
- Windows API：`Windows.h`、文件系统、注册表、控制台代码页、CryptoAPI（MD5）、文件时间、进程/自更新相关 API；支持库加载依赖 x86 ABI，故 `decrypt-fne` 仅 Win32 有效。
- 无 CMake、包管理清单、服务端或数据库；无网络 API 运行时服务。联网只用于 `UpdateCheck`/`SelfUpdater` 的 GitHub Release。
- 编码约定：源码按 AGENTS 说明使用 UTF-8+BOM、CRLF；运行时在 Windows 控制台切换 UTF-8，文件内容按本地代码页与 UTF-8 转换。

## 8. 测试、验证与未执行事项

### 已确认的验证结构

- 仓库内未发现 `tests/`、`test_*.cpp`、CTest、单元测试工程或自动化测试脚本；只发现 `test.e`、`test.bak`、`test.png` 夹具/样例。
- `AGENTS.md` 要求 Windows 环境完成 Release Win32/x64 编译，并在强调全量测试时对外部模块目录复制后执行解包→回包→字节/MD5 比较；还建议用 AutoLinker 做无头编译。
- 目标环境是 macOS，当前源码包含 `Windows.h`、`Wincrypt.h`、MSVC 工程和 x86 `.fne` ABI，未执行伪造的跨平台编译或测试。

### 本轮实际检查

- 已检查目标根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/e-packager`。
- 已确认原先不存在合格 `ARCHITECTURE.md`，也不存在 `细探-*.md`；本轮只新增目标根唯一架构文档。
- 已读取 `README.md`、`AGENTS.md`、Visual Studio 工程、入口、核心头文件和关键实现；已通过 `127.0.0.1:4780` 获取远程快照并核对版本差异。
- 未安装依赖、未启动服务、未构建、未提交 Git；未改源码/依赖/测试/配置。

## 9. 风险、未确认项与后续复核点

1. 当前本地基线 `e2txt.cpp`/`e2txt_restore.cpp` 体量很大，协议常量、section 排序、表达式字节码和快照兼容性仍需在 Windows + 真实易语言样本上持续回归。
2. 原生快照复用是正确性与保真度关键：源码/资源/依赖变更必须清除相应快照；若新增字段未纳入 `ComputeBundleDigest`，可能误复用旧字节。
3. `.ec` 通过临时 `.e` 桥接再解析，公开接口 `header/header.txt` 只查阅不参与回包；需要真实 `.ec` 样本确认复杂依赖、密码提示和公开符号边界。
4. `.fne` 导出依赖 Win32 x86 支持库 ABI；x64 仅能明确失败，不能在无宿主环境中以空数据冒充成功。
5. `info.json` 记录绝对 `sourcePath`、文件时间和 MD5；跨机器移动工作区时默认输出和依赖查找应以实际路径回退规则复核。
6. `compare-bundle`/`verify-roundtrip` 对文本做 BOM、换行和首尾空白归一化，对 JSON 忽略来源路径、时间、原生摘要等字段；这验证的是语义/目录一致性，不等同于所有原始字节完全一致。
7. 远程版本新增预检、表达式解析、XML 轻量解析、语义检查和 AutoLinker 编译检查，后续若同步远程必须单独评估文件拆分、事务式输出（暂存文件再 `MoveFileExW`）和未覆盖语义；不能把远程差异误记为本地现状。

## 10. 证据路径与版本基线

- 项目说明：`README.md`、`AGENTS.md`
- CLI 与流程编排：`src/main.cpp`
- 数据模型与公共入口：`src/e2txt.h`
- 二进制解析/加密/section：`src/e2txt.cpp`
- 恢复与序列化：`src/e2txt_restore.cpp`
- 目录读写：`src/EFolderCodec.cpp`
- 路径安全：`src/BundlePathUtils.cpp`
- 工作区元数据：`src/WorkspaceProjectSupport.cpp`
- 支持库导出：`src/SupportLibraryPublicInfo.cpp`、`elib/lib2.h`
- 路径/注册表：`src/PathHelper.cpp`
- 远程只读快照：`/tmp/e-packager-remote`（仅研究缓存，不属于目标项目事实源）
- 本地提交：`ffb50ab812fbaa24e26af30138c0790ab20f2b93`
- 远程提交：`5ca7864d682cbe6570140f7f6e15c05f9762b873`

## 11. MCP 与收口说明

本任务要求的专属 `system_engineering_toolkit` HTTP MCP 为 `http://127.0.0.1:8766/mcp/`。首条 `project_context` 已调用，但当前工具层绑定到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与目标仓库不一致；`codegraph_explore` 已按目标绝对路径调用并真实返回“该项目没有 `.codegraph/` 索引”。随后 `development_start` 两次被拒：第一次服务暂不可达，第二次明确返回 `MCP_TARGET_PROJECT_MISMATCH`。因此无法取得目标仓库专属 `work_id`，也无法按该 MCP 的前置状态机提交 `mcp_feedback`、`verify_and_record` 入账；此阻塞已如实保留，未用 V3 工具记录冒充目标项目成功。

## 12. 第三轮：制品、版本、安装与唯一制品链

### 12.1 真实制品分层

源码没有独立的“包管理器/制品仓库”抽象，实际存在四类不同性质的产物，不能混为一个版本号：

| 产物 | 真实生成点 | 元数据/完整性 | 是否参与 `.e` 回包 | 第三轮归位 |
|---|---|---|---|---|
| 原始 `.e`/`.ec` | `e2txt::Generator::GenerateBundle` 读取并解析；`src/e2txt.cpp:8026-8053` | `ProjectBundle.nativeSourceBytes` + `nativeBundleDigest` | 未修改且摘要相等时可直接复用 | 制品支持库的输入适配与解析能力 |
| 可编辑工作区 | `BundleDirectoryCodec::WriteBundle`；`src/EFolderCodec.cpp:1299-1545` | `project/.module.json`、`project/_meta.json`、资源清单、可选原生快照；`info.json` 另记来源 | `src/`、XML、依赖、资源和目录树参与；`ecom/`、`elib/`、`AGENTS.md`、`tool/`不参与主回包 | 制品支持库的工作区制品格式 |
| 回包 `.e` | `Restorer::RestoreBundleToBytes` → `EncodeSourceBytesForWrite` → `main.cpp::DoPack` 写目标文件；`src/main.cpp:741-808` | 输出只在 summary 中报告字节数和路径，没有独立清单/签名 | 是 | 运行核心监督写入，支持库提供格式转换 |
| 发布程序包 | `.github/workflows/release.yml:23-70` 构建 `bin/Win32/Release`、`bin/x64/Release`，但只打包并发布 Win32 ZIP | tag 写入 `src/version.h`；没有哈希、签名、SBOM 或依赖锁 | 不参与项目回包 | 发布制品由制品支持库管理，网关只触发命令 |

因此，“工作区”是可变编辑制品，“回包 `.e`”是业务输出，“GitHub ZIP”是程序发布制品；三者必须使用不同的制品类型和生命周期，不能通过一个 `versionText` 代替。

### 12.2 元数据、依赖和版本事实

- `info.json` 是工作区来源记录，不是可信制品清单：`WorkspaceProjectSupport::BuildInfoJson` 写 `version=1`、来源类型/文件名/绝对 `sourcePath`、UTC 修改时间、尺寸、MD5、`toolUrl` 和可选 `defaultPackOutputFileName`（`src/WorkspaceProjectSupport.cpp:316-330`）。`ValidateInfoJsonVersion` 只接受版本 `1`（`src/WorkspaceProjectSupport.cpp:861-884`），不校验字段类型、来源文件仍匹配、MD5 是否重算。
- `project/.module.json` 保存 `projectName`、`versionText`、`sourcePath` 和依赖数组；每个依赖可带 `kind/name/fileName/guid/versionText/path/resolvedPath/localWorkspace/reExport/definedIds`（`src/EFolderCodec.cpp:275-301`）。`resolvedPath`、`localWorkspace` 是本机派生辅助字段，读取时相对路径会拼到工作区根（`src/EFolderCodec.cpp:1588-1605`），不应进入跨机器制品的权威身份。
- `project/_meta.json` 的目录格式版本为 `3`，记录 `.e/.ec` 类型、源码/窗体清单、过滤器树、窗口绑定和 `nativeBundleDigest`（`src/EFolderCodec.cpp:1345-1416、1513-1520`）。读取时把 `formatVersion` 放入模型，但本地代码没有对未知目录格式做强制拒绝（`src/EFolderCodec.cpp:1581-1587`）；这是版本兼容缺口。
- `ComputeBundleDigest` 覆盖项目版本、依赖的声明字段、源码/窗体文本、四类固定文本、资源二进制、目录树和窗口绑定（`src/e2txt.cpp:7942-8014`），**不覆盖** `resolvedPath/localWorkspace`、`info.json`、`AGENTS.md`、`tool/e-packager.exe`、`ecom/`、`elib/`。它用于原生快照复用，不是签名清单，也不是整个工作区的完整性证明。
- 程序版本本地固定为 `APP_VERSION "dev"`（`src/version.h:3`）；发布工作流以 tag 改写该文件并按 `alpha/beta/pre/rc` 设置预发布标志（`.github/workflows/release.yml:23-33`）。运行时版本比较只解析最多三段数字并去掉 `v`/横线后缀（`src/UpdateCheck.cpp:21-39、142-160`），没有锁定发布资产摘要或兼容范围。
- 依赖导出是“尽力而为”而非可复现依赖安装：`.ec` 通过 `BuildModuleFileLookupCandidates` 查找并按绝对规范化路径去重，四线程递归解包到 `ecom/`；`.fne/.fnr/.dll` 通过候选路径查找并由 `SupportLibraryPublicInfo` 加载，写 `elib/`。缺依赖、x64 无法加载 x86 ABI、单项导出失败都追加运行警告而非形成锁文件（`src/main.cpp:438-568、600-643`；`src/SupportLibraryPublicInfo.cpp:1550-1604`）。工程只有 `thirdparty/json.hpp` 这一单头文件依赖，VC 工程固定 MSVC v145/C++20（`e-packager.vcxproj:29-55、95-103、167-192`）。

### 12.3 唯一制品链（现状与平台落点）

当前项目的主链是：

```text
.e/.ec 输入
  → Generator::GenerateBundle（解密/边界解析/ProjectBundle）
  → BundleDirectoryCodec::WriteBundle（工作区文件+元数据+快照+资源清单）
  → [可选] update（依赖/资源变更，清空原生复用状态并重写工作区）
  → BundleDirectoryCodec::ReadBundle
  → Restorer::RestoreBundleToBytes（摘要相等则快照复用，否则语义模型+section 序列化）
  → EncodeSourceBytesForWrite（可选密码）
  → .e 输出
```

发布程序的另一条现状链是：

```text
git tag
  → CI 改写 APP_VERSION
  → Release Win32/x64 编译
  → 仅 Win32 文件复制到 release-assets/并 Compress-Archive
  → GitHub Release
  → /update 查询 tag/资产名
  → PowerShell 临时目录下载/解压
  → 等待当前进程退出
  → 目标 exe → .old → 新 exe
```

第三轮裁决是**两条输入域不同但各自唯一的制品链**，而不是让 `pack`、`update`、`/update` 各自再造一套：

1. **制品支持库（唯一 owner）**：定义 `工作区制品`、`回包制品`、`发布程序包` 的类型、manifest、依赖锁、版本/兼容范围、内容摘要、签名、路径规范化、暂存目录和安装验证；负责将旧别名/旧元数据归一化一次。当前 `info.json`、`_meta.json` 和 ZIP 只能作为待升级的输入适配，不等于平台可信制品契约。
2. **运行核心（唯一 owner）**：负责真实文件/目录句柄、临时目录、子进程、动态库和安装替换的生命周期；负责写入事务、崩溃恢复、残留清理、原子激活指针和回滚。`main.cpp` 当前直接 `ofstream` 写目标（`src/main.cpp:789-797`），`WriteBundle`/`update` 也没有暂存-提交事务，故只能标为“可提炼模式”，不能声称已具备平台级运行核心能力。
3. **统一网关（唯一公开入口）**：负责把 CLI/拖放/未来 HTTP/MCP 命令归一成 `unpack/pack/update/verify-roundtrip/self-update` 契约、授权、幂等键、超时和统一错误；不持有 `.e` section 解析、JSON 元数据或发布 ZIP 逻辑。当前 `RunCommand` 同时做路由、参数解析和业务调度（`src/main.cpp:1994-2160`），应作为项目适配层接入，而不是复制为第二网关。

### 12.4 安装、发布与回滚归位

- **工作区安装**：`WriteWorkspaceFiles` 先写 `info.json`，再把当前可执行文件复制到 `tool/e-packager.exe`，最后写 `AGENTS.md`（`src/WorkspaceProjectSupport.cpp:736-765`）。这是工作区附带工具复制，不是受信安装：复制使用 `copy_file(...overwrite_existing)`，没有摘要核对、权限边界、临时文件或原子替换。
- **程序自更新**：`SelfUpdater::ScheduleSelfUpdate` 先请求 GitHub Release，再按文件名中的 Windows/Win32/x64 标记选择 ZIP/EXE；`TrySelectUpdateAsset` 是启发式评分，不校验资产签名/哈希（`src/SelfUpdater.cpp:162-224`）。PowerShell 下载后 ZIP 解压并递归找 `e-packager.exe`，等待源进程最多 90 秒，再最多 30 次移动/复制；失败到最后一轮仅在“备份存在且目标不存在”时恢复 `.old`（`src/SelfUpdater.cpp:304-366`）。
- **发布**：CI 同时构建 Win32 与 x64，但 `Package Win32 Release Files` 只复制 Win32，发布步骤只上传该 ZIP（`.github/workflows/release.yml:35-70`）。x64 运行 `/update` 直接返回“未发布 x64 包”的成功跳过结果（`src/SelfUpdater.cpp:439-447`），这是明确的架构差异，不是回滚能力。
- **平台归位**：制品支持库负责发布物料清单/摘要/签名/兼容矩阵/安装前后校验；运行核心负责 `staging → verified → activate → old pointer` 的原子切换、进程退出等待、句柄关闭和强杀恢复；网关只提交“发布/安装/回滚”命令并返回证据 id。回滚不能依赖“再下载一个可能已变的 latest”，而应指向已验证的旧制品摘要/版本。

## 13. 路径安全、失败、崩溃与残留矩阵

### 13.1 路径安全真实边界

- `BundlePathUtils::SanitizeRelativePath` 逐段把空段、`.`、`..` 和 Windows 非法字符改写为 `_`，处理保留设备名、尾部空格/点号；`MakeUniqueRelativePath` 按大小写不敏感键追加 `_2`；`ReserveBundleRelativePaths` 预占元数据、固定文本和资源索引路径（`src/BundlePathUtils.cpp:43-138`）。这属于“改写后继续写”，不是拒绝策略。
- `WriteBundle` 对源码、窗体和资源路径都经过上述规范化，并避免覆盖 `project/`、`src/` 固定入口、`image/list.json`、`audio/list.json` 等保留文件（`src/EFolderCodec.cpp:1315-1399、1484-1510`）。`update` 对资源逻辑名另拒绝 Windows 非法字符，并以同类逻辑名去重（`src/main.cpp:920-1045`）。
- 默认输出文件名使用 `path.filename()`，可剥离 `info.json` 中的目录部分（`src/WorkspaceProjectSupport.cpp:657-704`）；但显式 `pack <input-dir> <output>` 只把路径转绝对路径，未限制输出必须位于 `pack/` 或工作区外部安全目录。`ReadBundle` 读取元数据中的 `relativePath` 时直接 `root / file.relativePath`，没有再次做“必须位于 root 内”的拒绝校验（`src/EFolderCodec.cpp:1614-1637、1714-1721`），恶意工作区仍需平台入口加固。

### 13.2 失败与残留事实

| 场景 | 当前行为 | 可能残留/一致性风险 | 平台 owner |
|---|---|---|---|
| 参数、`info.json`/JSON/源文件不存在或版本不支持 | 返回 `false`/非零，错误文本带阶段前缀 | 通常未写或已写少量工作区文件 | 网关做参数契约；支持库做格式校验 |
| 解包中途写文件失败 | `WriteBundle` 按文件顺序直接写，失败立即返回 | `project/src/image/audio` 可能是半成品；无事务回滚 | 运行核心暂存、清理、原子提交 |
| `update` 依赖/资源已改而派生刷新失败 | 先 `WriteBundle`，再 `RefreshDependencyArtifacts`；刷新前 `remove_all(ecom/elib)` | 旧派生物可能已删除，新派生物只生成一部分 | 运行核心恢复工作区；支持库重建派生物 |
| 缺 `.ec`/`.fne`/`.fnr` 或 x64 无 x86 ABI | `AddRuntimeWarning`，主命令可能仍成功 | 依赖清单存在但 `resolvedPath/localWorkspace` 缺失，不能当完整成功 | 支持库返回结构化“依赖不可用”；网关决定 warning/失败语义 |
| 语义构建/模型/序列化异常 | `RestoreBundleToBytesInternal` 捕获并返回 `build_document_exception`、`build_restore_model_exception`、`serialize_exception` | 目标文件尚未写时较安全；若直接写阶段失败则没有恢复点 | 运行核心保留诊断与临时目录 |
| 输出文件打开/写入失败 | `DoPack` 返回 `open_output_failed`/`write_output_failed` | 目标路径可能已有旧文件；没有备份或原子替换 | 运行核心原子写入 |
| 进程崩溃/强杀 | 只有 `main()` 顶层 C++ 异常捕获；没有崩溃钩子、事务日志或启动恢复扫描 | 工作区临时目录、部分文件、`verify-roundtrip` 工作目录、更新脚本可能遗留 | 运行核心按操作 id 扫描、判定、清理/恢复 |
| 自更新下载/替换失败 | PowerShell 记录 `update.log`，30 次失败后有条件恢复 `.old` | `e-packager-self-update-*`、`e-packager-self-update-work-*`、`.old` 可能残留；无签名校验 | 制品支持库验证；运行核心回滚并清残留 |

运行时警告由 `AddRuntimeWarning` 去重、`ConsumeRuntimeWarnings` 在命令结束时一次性打印（`src/e2txt.cpp:7667-7693`）；它是用户提示通道，不是持久证据账本，也不能支撑崩溃后恢复。

### 13.3 L0-L4 归档与验收等级

这里的 L0-L4 是第三轮对平台底座的验收等级，不把源码已有的“返回 true”误写成通过：

| 等级 | 必须证明的边界 | e-packager 现状 | 归属与最低验收 |
|---|---|---|---|
| **L0 输入/路径** | 参数、来源类型、目录格式、版本、绝对/相对路径、`..`、保留名和输出范围在任何写入前拒绝非法值 | 有参数数量检查、`info.json version=1`、写路径改写；读取路径和显式输出范围仍弱 | 制品支持库；恶意 JSON/路径夹具必须零越界写、错误码稳定 |
| **L1 解析/依赖** | `.e/.ec` 解密、section、ProjectBundle、依赖解析、缺 provider 的可解释结果 | 本地真实实现；依赖导出尽力而为，缺失主要是 warning；未做依赖锁/版本兼容矩阵 | 支持库；逐项断言输入失败、依赖缺失、x64 ABI 不可用，区分 warning 与 failure |
| **L2 制品事务** | manifest/摘要/签名、暂存写、完整校验、原子提交；失败不破坏旧制品 | `WriteBundle`/`DoPack`/`update` 直接改目标，digest 只保护原生快照复用 | 制品支持库 + 运行核心；故障注入每个写入点，旧目录/旧 `.e` 必须保持可读 |
| **L3 运行/崩溃** | 文件句柄、线程、支持库 DLL、临时目录和子任务在成功/失败/取消/崩溃后可回收；重启可恢复 | 线程异常会汇总重抛，DLL 正常路径 `FreeLibrary`；无操作日志、崩溃恢复和全局残留扫描 | 运行核心；真实强杀后验证进程/句柄/临时目录/`.old`/半成品，重复恢复幂等 |
| **L4 发布/回滚/网关** | 发布资产可验证、版本兼容、权限/幂等/超时、原子激活、回滚到已知摘要，统一网关证据闭环 | CI tag+Win32 ZIP+latest 启发式下载；无签名、哈希、旧制品指针和网关契约 | 制品支持库（物料与信任）+运行核心（激活/恢复）+网关（命令/授权/证据）；注入下载失败、替换失败、进程退出超时和重复回滚 |

**裁决**：现有源码可吸收的是 `ProjectBundle`、稳定摘要、保留路径预占、依赖去重、错误前缀、线程任务汇总和自更新“备份后替换”的局部模式；“直接写正式目录、latest 下载、无签名、warning 代替失败、条件恢复 `.old`、无崩溃扫描”只能列为待核/隔离，不得直接升级为平台生产契约。

## 14. 第三轮能力命中、缺口与装配计划

| 能力 | 现有源码命中 | 裁决 | 目标落点 |
|---|---|---|---|
| 工作区/回包格式 | `ProjectBundle`、`EFolderCodec`、`Restorer` | 吸收为项目适配器输入，不复制协议 | 制品支持库的 `.e` provider；模块层只编排 unpack/pack |
| 元数据与版本 | `info.json v1`、目录 `formatVersion=3`、`APP_VERSION`/tag | 升级为显式 schema + 兼容范围；现实现待核 | 制品支持库；版本选择由运行核心执行 |
| 依赖解析/导出 | `PathHelper`、ECom/ELib 导出、x86 ABI | 吸收查找/去重/释放模式；缺失不可静默成功 | 支持库 provider；依赖锁与宿主能力报告归制品支持库 |
| 路径安全 | `BundlePathUtils`、默认名 `filename()` | 吸收保留名/冲突改名；必须补拒绝而非仅 sanitize | 制品支持库统一路径能力 |
| 安装/发布 | `WriteWorkspaceFiles`、`SelfUpdater`、release workflow | 仅作历史适配；无签名/原子安装/稳定回滚 | 制品支持库验证 + 运行核心安装事务 |
| 网关 | `RunCommand`/拖放/无参入口 | 只保留项目命令适配，不再建设第二网关 | 统一网关注册命令、授权、超时和结果 |
| 故障与残留 | `outError`、warning 去重、顶层 catch | 吸收错误分层；补操作证据和重启恢复 | 运行核心监督/诊断/残留清理 |

装配顺序固定为：

1. 制品支持库先冻结三类制品的 manifest、版本/兼容、依赖锁、摘要/签名和路径拒绝契约；将 `info.json` 与 `_meta.json` 作为 legacy reader，不让消费者直接读 JSON。
2. 运行核心提供唯一 `暂存目录 → 校验 → 原子提交 → 激活指针 → 失败恢复`，并接管 `ofstream`、`copy_file`、PowerShell 子进程、DLL/线程和临时目录；保留 `.old` 只能是受状态机管理的回滚记录。
3. 网关把 `unpack/pack/update/verify-roundtrip/install/publish/rollback` 绑定到唯一能力 id，统一错误码、幂等键、权限、超时和证据；`RunCommand` 只能作为适配层，不得旁路调用第三方或另写安装流程。
4. 验收按 L0→L4 逐层推进：先恶意路径/坏 JSON，再缺依赖/错误版本，再写入点故障注入，再强杀恢复，最后做发布资产篡改、替换失败、重复发布/回滚和网关重启；任一层只有成功路径没有失败/残留读回证据，均标“部分实现”。

本轮仍仅修改本文件；没有把上述平台目标写回源码，也没有把远程版本或错误绑定的 `project_context` 结果当作目标项目证据。
