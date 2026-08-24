# pandoc 架构建档

## 1. 文档定位

本文是本目录当前源码的首轮全量架构建档。说明、备注、风险和结论使用中文；源码模块名、函数名、字段名、格式名和命令参数保留原文。

- **目标项目**：`pandoc`
- **本地根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/pandoc`
- **本地快照**：分支 `main`，HEAD `0f17d3966f3ff53c23ebcb9a325e9fb167523c07`，版本 `3.10.1-4-g0f17d39`。
- **许可证**：`GPL-2.0-or-later`；许可和版本证据见 `pandoc.cabal:1-15`。
- **上游地址**：`https://github.com/jgm/pandoc.git`，见 `pandoc.cabal:460-462`。
- **文档来源**：`README.md`、`细探-pandoc.md`、四个 Cabal/Stack 配置、核心 Haskell 模块、服务器 API 文档、`test/` 测试资源，以及独立远程快照。
- **规则文件**：项目根目录未发现 `AGENTS.md` 或 `CLAUDE.md`。
- **唯一正式架构文档声明**：本文件吸收并裁决 `细探-pandoc.md` 的有效内容；旧细探保留作历史研究记录，但后续架构维护只更新本文件，不再把旧细探作为平行事实源。

### 1.1 远程版本对账

按任务要求使用 `http://127.0.0.1:4780` 代理建立 `/tmp/pandoc-remote-snapshot` 独立快照，未覆盖工作树、未写回目标项目。

- 本地 HEAD：`0f17d3966f3ff53c23ebcb9a325e9fb167523c07`，2026-07-24，`3.10.1` 系列。
- 远程 `origin/main`：`0507289fce476dacbd165416a4a8ad56275c9f38`，2026-08-18，`pandoc 3.10.2`。
- 远程相对本地新增 13 个文件、删除本地细探文件 1 个、内容变化 38 个文件；主要包括 `pandoc 3.10.2` 发布变更、RTF/HTML/Markdown/Typst/LaTeX/JATS 修复、测试夹具和新文档。
- 本架构结论以**本地工作树源码**为准；远程差异只作为版本风险和后续同步提示，不把远程文件当成本地已实现证据。

## 2. 项目定位与总体架构

Pandoc 是 Haskell 实现的通用文档转换器，同时提供可复用的 `pandoc` library、命令行程序和可选 HTTP server。它把输入格式解析为统一的 Pandoc AST，再经过可选 filter/transforms，最后由 writer 输出目标格式。

```text
输入文件 / stdin / URL / HTTP JSON
        │
        ▼
Text.Pandoc.App.Input
  ├─ TextReader       文本输入
  └─ ByteStringReader 二进制输入
        │
        ▼
Text.Pandoc.Readers
  └─ getReader / readers / read<Format>
        │
        ▼
Pandoc AST（核心类型来自外部 pandoc-types 的 Text.Pandoc.Definition）
  ├─ Meta
  └─ Block / Inline / 资源引用等结构
        │
        ├─ CLI filters：JSON filter / Lua filter / citeproc / 内置 transforms
        │
        ▼
Text.Pandoc.Writers
  └─ getWriter / writers / write<Format>
        │
        ├─ TextWriter       文本输出
        └─ ByteStringWriter  二进制输出
        │
        ▼
目标文件 / stdout / HTTP response / JSON AST
```

README 对该边界的原始说明见 `README.md:257-274`：新增格式主要通过增加 Reader/Writer 扩展；统一 AST 的表达能力低于部分源格式，因此复杂格式到其他格式可能有损。

### 2.1 分层与职责

| 层 | 目录/包 | 主要职责 |
|---|---|---|
| 核心库 | `src/Text/Pandoc/`，Cabal 包 `pandoc` | AST 周边公共 API、Reader/Writer 注册表、格式实现、选项、错误、资源、模板、过滤和运行时抽象 |
| 输入层 | `Text.Pandoc.App.Input`、`Text.Pandoc.Readers` | 从文件、stdin、`http:`/`https:`/`file:` 读取，按格式选择 Reader，文本/二进制分流 |
| 输出层 | `Text.Pandoc.Writers`、`Text.Pandoc.App.OutputSettings` | 按 `--to`/输出文件推断 Writer，构造 `WriterOptions`，处理模板、PDF engine 和 sandbox |
| 变换层 | `Text.Pandoc.Transforms`、`Text.Pandoc.Citeproc`、`Text.Pandoc.Filter` | AST 变换、引用处理、外部 JSON filter、Lua filter |
| CLI | `pandoc-cli/`，Cabal 包 `pandoc-cli` | `Main` 解析程序名和命令行，调用 `convertWithOpts`；可选 server/Lua/WASM |
| HTTP 服务 | `pandoc-server/`，Cabal 包 `pandoc-server` + `pandoc-cli/server/` | Servant/WAI API、JSON 请求、内容协商、批处理、Babelmark、版本端点、超时中间件 |
| Lua | `pandoc-lua-engine/` + `pandoc-cli/lua/` | Lua filter、custom reader/writer、Lua interpreter/REPL；功能由 Cabal flag 控制 |
| 资源/数据 | `data/`、`templates/`、`MANUAL.txt`、`test/` | 内置模板、翻译、实体、参考 OOXML 文件、测试夹具与 golden 输出 |

## 3. 核心库与中间表示

### 3.1 公共聚合入口

`src/Text/Pandoc.hs:38-79` 是库级聚合入口，重新导出：

- `Text.Pandoc.Definition`：Pandoc AST 定义；本仓库未找到该源文件，来自依赖 `pandoc-types`，依赖声明见 `pandoc.cabal:549-552`。
- `Text.Pandoc.Generic`、`Text.Pandoc.Options`、`Text.Pandoc.Logging`、`Text.Pandoc.Class`、`Text.Pandoc.Data`、`Text.Pandoc.Error`。
- `Text.Pandoc.Readers` 和 `Text.Pandoc.Writers`。
- 模板、翻译和 `pandocVersion`/`pandocVersionText`。

因此平台接入若需要构造或消费 AST，必须同时锁定 `pandoc-types` 版本契约，不能只看本仓库的 `Text.Pandoc` façade。

### 3.2 Reader 注册表

`src/Text/Pandoc/Readers.hs:132-189` 定义：

- `TextReader (forall a . ToSources a => ReaderOptions -> a -> m Pandoc)`：文本/多来源输入。
- `ByteStringReader (ReaderOptions -> BL.ByteString -> m Pandoc)`：`docx`、`pptx`、`xlsx`、`odt`、`epub` 等二进制输入。
- `readers :: PandocMonad m => [(Text, Reader m)]`：格式名到 Reader 的关联表。
- `getReader`：按 `FlavoredFormat` 找 Reader，并应用扩展差异配置；未知格式返回 `PandocUnknownReaderError`。
- `readJSON`：读取 JSON native AST，使用 `eitherDecode'` 解码为 `Pandoc`；解析失败包装为 `PandocParseError`（`Readers.hs:191-210`）。

本地已登记的输入类别包括 `markdown`/`commonmark`/`gfm`、HTML/XML/LaTeX/RST/Org/wiki 系列、`docx`/`pptx`/`xlsx`/`odt`/`epub`/`ipynb`、CSV/TSV、BibTeX/RIS/CSL JSON、RTF、Typst、Djot 等。完整公开格式表见 `README.md:27-118`。

### 3.3 Writer 注册表

`src/Text/Pandoc/Writers.hs:154-235` 对称定义：

- `TextWriter (WriterOptions -> Pandoc -> m Text)`。
- `ByteStringWriter (WriterOptions -> Pandoc -> m BL.ByteString)`。
- `writers :: PandocMonad m => [(Text, Writer m)]`：目标格式到 Writer 的关联表。
- `getWriter`：格式解析、扩展配置应用、未知格式返回 `PandocUnknownWriterError`。
- `writeJSON`：`encode` Pandoc 后转换为 UTF-8 文本（`Writers.hs:246-247`）。

二进制输出主要包括 `docx`、`odt`、`pptx`、`epub`、`chunkedhtml`；文本输出覆盖 JSON、Markdown/CommonMark/GFM、HTML、LaTeX、DocBook/JATS、纯文本、RST、Typst、RTF、Office/slide 等。完整公开格式表见 `README.md:120-248`。

### 3.4 JSON AST / IR 契约

- `json` 不是独立的业务文档模型，而是 Pandoc native AST 的 JSON 表示：Reader 注册为 `readJSON`，Writer 注册为 `writeJSON`。
- 顶层版本协商字段 `pandoc-api-version` 属于 native AST 的兼容契约；本仓库的实际 `ToJSON/FromJSON` 实现由外部 `pandoc-types` 提供，仓库内只看到 `encode`/`eitherDecode'` 调用。相关历史说明见 `changelog.md` 中 `pandoc-api-version` 条目，当前设计摘要见 `细探-pandoc.md:43-53`。
- 版本字段不能被消费方忽略：读取方应按 API 版本做兼容判断；平台若映射到自己的统一 JSON/IR，应将 Pandoc AST 视为外部输入契约并保留版本隔离。
- `细探-pandoc.md:39-53` 确认 AST 是块级（如 `Para`、`Header`、`Table`、`CodeBlock`）和行内（如 `Str`、`Emph`、`Strong`、`Link`）节点组成的统一中间表示。

## 4. 运行时模型与数据流

### 4.1 文件/命令行转换

`pandoc-cli/src/pandoc.hs:46-67` 的主流程：

1. 读取程序名和 raw arguments。
2. 若包含 `-v/--version`，走版本输出。
3. 程序名为 `pandoc-server`/`pandoc-server.cgi` 时进入 HTTP/CGI；为 `pandoc-lua` 或第一个参数为 `lua` 时进入 Lua interpreter。
4. 普通调用获取 scripting engine，执行 `parseOptionsFromArgs`，成功后调用 `convertWithOpts`。

`Text.Pandoc.App.CommandLineOptions` 的选项表覆盖 `--from`、`--to`、`--output`、metadata、template、变量、过滤器、资源、PDF engine、格式扩展、引用、目录、编号、HTML math、Lua/JSON filter、版本/帮助等（代表性证据 `CommandLineOptions.hs:69-107`、`273-371`、`707-719`、`1001-1028`）。

### 4.2 输入资源读取

`Text.Pandoc.App.Input:37-77`：

- `InputParameters` 固定 Reader、格式名、`ReaderOptions`、输入路径、tab 设置和 `inputFileScope`。
- `readInput` 先读取所有来源，再依据 `TextReader`/`ByteStringReader` 分流。
- JSON 文本 Reader 对每个输入独立解码后合并；`inputFileScope` 开启时会为每个文件调整链接和标识符。
- `readSource` 支持 `-`（stdin）、`http:`/`https:`、`file:` 和普通路径（`Input.hs:85-96`）。
- 文本转码会处理 UTF-8、ISO-8859-1、其他 charset 和已知二进制签名（ZIP、PDF、CFBF、DjVu），避免把二进制误当文本（`Input.hs:98-134`）。

### 4.3 输出设置与 PDF

`Text.Pandoc.App.OutputSettings:55-153` 将 CLI `Opt` 转为 `OutputSettings`：

- 输出格式优先使用 `--to`；否则从输出文件扩展名推断，stdout 默认 HTML。
- `.pdf` 或 `--to=pdf` 进入 `pdfWriterAndProg`，由目标 writer 和 PDF engine 选择兼容组合。
- 二进制格式或 PDF 隐含 standalone/template 处理。
- 可加载自定义 Lua writer/template。
- `--sandbox` 下使用纯 writer 并保留必要资源。
- writer 选定后生成完整 `WriterOptions`，包括模板、变量、扩展、引用、目录、数学、图片和分页设置。

PDF 不是核心 Writer 的普通 `pdf` 字符串输出，而是经 `pdflatex`、`lualatex`、`xelatex`、`latexmk`、`tectonic`、`weasyprint`、`wkhtmltopdf`、`pagedjs-cli`、`prince`、`groff`、`pdfroff`、`typst`、`context` 等外部程序完成；默认和兼容矩阵见 `CommandLineOptions.hs:207-230`、`OutputSettings.hs:290-323`。

### 4.4 Filter 管道

`Text.Pandoc.Filter.JSON:35-82` 的 `apply`/`externalFilter`：

1. 判断 filter 文件是否存在和是否可执行。
2. 对 `.py/.hs/.pl/.rb/.php/.js/.r` 选择对应解释器，否则直接执行。
3. 注入 `PANDOC_VERSION` 和 JSON 编码的 `PANDOC_READER_OPTIONS`。
4. 通过 `pipeProcess` 把当前 `Pandoc` JSON 写入 filter stdin。
5. 仅接受零退出码并对 stdout 进行 JSON 解码；非零退出或异常包装为 `PandocFilterError`。

Lua filter 由 `Text.Pandoc.Lua` 暴露 `applyFilter`、`loadCustom`、`runLua`、`runLuaNoEnv`、`getEngine`（`pandoc-lua-engine/src/Text/Pandoc/Lua.hs:11-28`）。

## 5. CLI、HTTP 和 WASM 接口

### 5.1 CLI

- 主可执行文件：`pandoc-cli/pandoc-cli.cabal:65-107`，`main-is: pandoc.hs`。
- CLI 精确依赖当前同版本 `pandoc == 3.10.1`（本地；远程已为 `3.10.2`），避免 library/CLI API 漂移。
- Cabal flags：`lua`、`server`、`repl`、`nightly`；WASM 构建还会关闭 server/repl 并设置导出符号，见 `pandoc-cli.cabal:25-40`、`76-107`。

### 5.2 HTTP server

`pandoc-server/src/Text/Pandoc/Server.hs:182-218` 定义 Servant `API`：

- 根路径：同一 POST 请求按 `Accept` 提供 `OctetStream`、`PlainText` 或 JSON。
- `/batch`：接收 `[Params]`，返回 `[Output]`。
- `/babelmark`：GET，返回 `{ "html", "version" }`。
- `/version`：GET，返回 `pandocVersionText`。
- `app` 用 CORS middleware，仅额外允许 `Content-Type` 请求头（`Server.hs:199-207`）。

请求核心结构 `Params`（`Server.hs:122-157`）：

- `options :: Opt`：复用 CLI 选项模型。
- `text :: Text`：必填；二进制输入时是 base64 文本。
- `files :: Maybe (Map FilePath Blob)`：可选资源映射，`Blob` 的 JSON 编码是 base64。
- `citeproc :: Maybe Bool`：可选引用处理开关。

JSON 输出 `Output`（`Server.hs:159-180`）：

- 成功：`{"output": ..., "base64": Bool, "messages": [...]}`。
- 失败：`{"error": ...}`。
- `messages` 含 `message` 和 `verbosity`。

服务转换使用 `runPure`（`Server.hs:230-249`、`254-418`），将 `files` 放入纯内存 `FileTree`，选 Reader/Writer，应用 transforms/citeproc，再输出文本或 base64 二进制。`pandoc-server` 文档还明确说明：纯模式不允许 I/O，因此 PDF、filters、HTTP 资源抓取不可用，图片/include/其他资源必须通过 `files` 显式提供（`doc/pandoc-server.md:15-39`）。

CLI server 启动与超时由 `pandoc-cli/server/PandocCLI/Server.hs:23-35` 实现：默认端口 3030、默认超时 2 秒；CGI 可通过 `PANDOC_SERVER_TIMEOUT` 配置。

### 5.3 WASM

WASM 是 CLI package 的条件分支，不是独立核心层：`pandoc-cli.cabal:76-83` 切换 `hs-source-dirs` 到 `wasm` 并导出 `convert`、`query` 等符号。`cabal.project:13-56` 对 `arch(wasm32)` 关闭测试、关闭 HTTP 和 server/repl，并加入 WASI 兼容编译参数。

## 6. 包、依赖和配置

### 6.1 Cabal/Stack 组织

`cabal.project:1-8` 将四个包作为一个项目构建：`.`、`pandoc-lua-engine`、`pandoc-server`、`pandoc-cli`，并设置版本约束。`stack.yaml:6-40` 使用 resolver `lts-24.51`、对应 extra-deps 和 GHC 本地选项。

核心 `pandoc.cabal`：

- library 名为 `pandoc`，版本本地为 `3.10.1`。
- Haskell >=9.6.7、9.8.4、9.10.3、9.12.2 被列为测试编译器（`pandoc.cabal:14`）。
- 外部关键依赖包括 `aeson`、`pandoc-types`、`commonmark`、`citeproc`、`doclayout`、`doctemplates`、`hslua` 生态、`skylighting`、`texmath`、`yaml`、`zip-archive`、各类 XML/Office 处理依赖，以及可选 HTTP/TLS 依赖（`pandoc.cabal:513-595`）。
- `embed_data_files` 默认关闭但项目配置开启；`http` 默认开启，WASM 配置关闭（`pandoc.cabal:464-470`、`cabal.project:10-21`、`38-40`）。

### 6.2 数据文件和生成关系

- `README.md` 明确声明由 `README.template` 和 `MANUAL.txt` 经 `tools/update-readme.lua` 自动生成，不能手工编辑（`README.md:1-4`）。
- `Makefile:201-203` 固化 README 生成命令。
- `pandoc.cabal:51-210` 声明模板、翻译、实体、参考 docx/odt/pptx、默认数据和文档文件。
- 测试/发行包资源在 `pandoc.cabal:217-460` 通过 `extra-source-files` 逐项声明，避免源码、golden 文件和数据文件脱离发行包。

## 7. 测试、CI 与验证面

### 7.1 测试结构

- 主测试套件：`test/test-pandoc.hs`，在 `pandoc.cabal:839-927` 以 `exitcode-stdio-1.0` 注册。
- 测试模块覆盖 `Tests.Readers.*`、`Tests.Writers.*`、`Tests.Command`、`Tests.Helpers`、`Tests.Shared`、媒体/ XML/旧测试等。
- `test/` 既有大量 golden 输入/输出，也有 `test/command/` CLI 场景、`test/docx`、`test/pptx`、`test/xlsx-reader`、`test/ipynb`、`test/epub` 等格式夹具。
- `Makefile:50-55` 的常规测试入口是 `cabal test`，参数传入 `--hide-successes --ansi-tricks=false`；`Makefile:22-27` 的 `all` 会 build 后 test。
- 其他验证入口包括 `check-cabal`、`check-stack`、`check-version-sync`、`check-changelog`、`check-manversion`、`checkdocs`、`validate-epub`、两个 docx validator、benchmark、coverage 和 dependency graph（`Makefile:69-160`）。

### 7.2 CI/发布

根目录存在 `.github/workflows/`，包含 `ci.yml`、`benchmark.yml`、`docx-validation.yaml`、`nix.yml`、`release-candidate.yml`，并有 `.circleci/config.yml`。当前核对只做静态阅读，没有启动 CI、构建、安装或运行完整测试。

### 7.3 当前核对验证限制

按任务边界未执行安装、启动、构建、源码/依赖/测试/配置修改，也没有将目标仓库接入其他 MCP、记忆或外部代码地图。最终仅对新增 `ARCHITECTURE.md` 做静态文件存在性、首行和根目录写入范围核对；随后通过专属 `system_engineering_toolkit` 的 `verify_and_record` 记录该静态核对。

## 8. 设计边界、风险与注意事项

1. **许可证边界（重要）**：本项目是 GPL-2.0-or-later。`细探-pandoc.md:3-5,81-85` 将可复用边界归纳为只能 CLI/HTTP 独立进程调用、不可直接链接进平台。接入闭源或不同许可证平台时应采用独立进程/HTTP，并检查传输和部署方式；不要把 Haskell library 静态/动态链接进不兼容主体。
2. **IR 有损（重要）**：统一 AST 的表达能力低于部分输入格式；复杂表格、排版细节、边距等可能无法保留。`README.md:266-274` 已明确不能承诺任意格式之间无损转换。
3. **HTTP 纯执行限制（重要）**：server 的 `runPure` 安全边界同时限制了 PDF、filters、HTTP 抓取；资源必须随请求放入 `files`，否则转换可能失败。见 `doc/pandoc-server.md:21-39`。
4. **外部程序依赖（重要）**：PDF 生成和部分格式能力依赖 `pdflatex`、`weasyprint`、`typst` 等宿主程序。可移植部署需要显式探测、超时、错误归因和资源隔离；不能把这些命令当成核心库内置能力。
5. **版本滞后（重要）**：本地为 3.10.1，远程 main 已到 3.10.2。远程存在 Reader/Writer、模板、测试和依赖配置变化；任何二次开发前应先决定是以本地快照冻结，还是先做独立远程同步评估。当前未覆盖工作树。
6. **外部 AST 依赖（建议）**：`Text.Pandoc.Definition` 来自 `pandoc-types`，JSON 的具体实例和 `pandoc-api-version` 语义不能仅凭本地 `src/` 完整复原；集成方要锁定 `pandoc-types` 版本并把 JSON 样例纳入契约测试。
7. **生成文档边界（建议）**：README 是生成物，维护应修改 `README.template`/`MANUAL.txt`/Lua filter，而不是直接改 `README.md`。
8. **纯服务与 CLI 语义不同（建议）**：CLI 默认允许 I/O、filters 和外部资源；HTTP server 使用 `PandocPure`，同样的 `from/to` 在两个入口可能有不同可用能力，适配层应分别声明。
9. **测试未在当前核对执行（备注）**：没有真实 build/test 结果，不能据此声称当前环境可构建或所有 golden 测试通过。
10. **专属 MCP 上下文偏差（备注）**：本次 `system_engineering_toolkit` 的 `project_context` 与 `codegraph_explore` 服务固定返回“系统工程平台”上下文，而不是目标 `pandoc` 仓库；其证据可信度（50，部分可信）和最近成功验证记录均属于平台，不能作为 pandoc 的实现/测试证明。本档已以目标仓库本地文件、Git 元数据和独立远程快照为事实来源，没有把该平台证据写成 pandoc 通过证据。

## 9. 可复用架构结论

- **统一 AST + Reader/Writer 对称注册表**适合作为文档格式扩展骨架：格式适配与核心流程解耦。
- **JSON native AST + `pandoc-api-version`** 提供了明确的 schema 演进锚点；任何平台映射都应把版本放在协议边界而不是隐藏在实现里。
- **Filter 位于 AST 层**，可把引用处理、业务结构化后处理和外部脚本变换放在解析/输出之间；外部 filter 采用 stdin/stdout JSON 协议，易于进程隔离。
- **`PandocPure` / `PandocIO` 双运行模型**把安全边界显式化：服务端可用纯内存文件树降低 I/O 风险，CLI 则提供完整本地能力。
- **文本/二进制 Writer 分流**、资源映射和 base64 封装适合迁移到通用文档服务，但需要保留错误、日志、超时和输出编码语义。
- **当前最小安全接入方式**：以本地 `pandoc` 可执行程序或 `pandoc-server` 独立进程接入，限定格式白名单、超时、资源目录和输出大小；不要直接链接 GPL library。

## 9.1 旧细探吸收与裁决记录

本节记录对 `细探-pandoc.md`（已完整读取）的收口结果。裁决以当前本地工作树源码和本档已有路径证据为准；旧细探不删除，仅保留为历史输入。

| 旧细探结论 | 当前源码对照与正式文档落点 | 裁决 |
|---|---|---|
| 总体闭环为 `Reader → AST → Writer`，格式扩展具有对称性 | `src/Text/Pandoc/Readers.hs:132-189` 与 `src/Text/Pandoc/Writers.hs:154-235` 分别定义 Reader/Writer 类型和注册表；本档第 2、3.2、3.3 节已写明。 | **吸收**：作为核心架构闭环；“新增格式只加一对 Reader/Writer”收敛为主要扩展路径，不宣称所有格式都严格成对。 |
| Pandoc AST 由块级和行内节点构成，是统一中间表示 | `Text.Pandoc.Definition` 由外部 `pandoc-types` 提供；本档第 3.1、3.4 节已区分本仓库 façade 与外部 AST 定义，并保留 `Para`、`Header`、`Table`、`CodeBlock`、`Str`、`Emph`、`Strong`、`Link` 示例。 | **吸收**：作为 native AST/IR 事实；同时保留“外部依赖”和“跨格式可能有损”边界。 |
| JSON 带 `pandoc-api-version`，用于版本协商 | `src/Text/Pandoc/Readers.hs:200-210` 的 `readJSON` 使用 `eitherDecode'`，`src/Text/Pandoc/Writers.hs:246-247` 的 `writeJSON` 使用 `encode`；字段实例由 `pandoc-types` 提供，且 `changelog.md` 有历史条目。本档第 3.4 节已注明证据边界。 | **吸收**：作为 native AST 协议版本锚点；不把 JSON 误写成独立业务文档模型，也不臆测本仓库未定义的字段实现。 |
| Filter 可用 Lua/Python/自定义脚本在 AST 上做后处理 | `src/Text/Pandoc/Filter/JSON.hs:43-78` 明确通过 stdin/stdout JSON、解释器选择、环境变量和退出码处理外部 filter；`pandoc-lua-engine/src/Text/Pandoc/Lua.hs:11-28` 暴露 Lua filter/custom reader/writer 能力。本档第 4.4 节已展开。 | **吸收**：作为 AST 层 filter 管道；补充为受执行权限、外部解释器、退出码和 JSON 解码约束的进程边界，而非无条件“可执行”。 |
| 许可证为 GPL-2.0，平台应采用 CLI/HTTP 独立进程，不直接链接库 | `pandoc.cabal:2-6` 的正式声明为 `GPL-2.0-or-later`，`COPYING.md:1-3` 为 GNU GPL v2 文本；本档第 8 节已按当前许可证名称修正。 | **吸收并校正**：保留独立进程接入的工程合规建议；旧细探的“GPL-2.0”简写和绝对法律判断不作为源码事实，正式接入仍需单独进行许可证审查。 |
| `MANUAL.txt`、`lua/`、`test/` 是后续细探入口 | 当前根目录存在 `MANUAL.txt`、`test/`，Lua 实现实际分布在 `pandoc-lua-engine/` 与 `pandoc-cli/lua/`；本档第 2.1、6.2、7.1、7.2 节已覆盖。 | **部分吸收并校正**：保留 `MANUAL.txt` 和 `test/` 作为证据入口；将过于笼统的 `lua/` 修正为真实目录，不把旁路线索误当完整架构。 |
| 无 LLM 提示词，属于纯确定性转换 | 当前源码入口、Reader/Writer/filter 代码未显示 LLM/提示词组件；本档以确定性转换器定位，但未将“未发现”扩写成运行时保证。 | **吸收为定位边界**：不设 LLM 层；不额外声称所有外部 filter 或宿主程序行为均确定性。 |

后续如发现旧细探与源码冲突，以当前源码路径、版本基线和本文件的“未确认项/风险”记录为准；不得通过修改旧细探制造第二份正式架构结论。

## 10. 后续收口：转换链、进程、资源与真假验证

本节是对旧细探中“Reader→AST→Writer、JSON 版本、Filter”的逐条源码收口，不改变旧细探文件。重点补齐此前没有展开的执行顺序、外部进程、错误传播、临时文件、资源释放和验证等级。以下均以本地工作树 `0f17d3966f3ff53c23ebcb9a325e9fb167523c07` 为准。

### 10.1 CLI 真实转换链（不是概念图）

`pandoc-cli/src/pandoc.hs:46-67` 只负责入口分流：版本、`pandoc-server`/CGI、`pandoc-lua`/`lua` 和普通 CLI。普通 CLI 解析成功后进入 `Text.Pandoc.App.convertWithOpts`；真正的转换顺序在 `src/Text/Pandoc/App.hs:83-347`：

```text
raw args
  → parseOptionsFromArgs
  → configureCommonState（数据目录、verbosity、resource path、输入/输出文件、HTTP headers）
  → 选择 reader（--from；否则按输入扩展名；stdin 默认 markdown）
  → 选择 writer/output settings（--to；否则按输出扩展名；stdout 默认 html）
  → 生成 ReaderOptions / WriterOptions / 模板 / PDF engine
  → readInput
       → readSources：所有文件、stdin、http(s)、file URI 先读入内存
       → TextReader 或 ByteStringReader
       → Pandoc AST + MediaBag/日志状态
  → metadataFromFile + CLI metadata + CSL metadata
  → applyFilters：路径展开后按给定顺序 foldM 串行执行
  → applyTransforms：heading shift、East-Asian line break、ipynb output 等内置变换
  → 非 sandbox 且 docx/--extract-media 时 fillMediaBag
  → --extract-media 时 extractMedia
  → docx 非 sandbox 时创建 SVG PNG fallback
  → Writer（TextWriter / ByteStringWriter）
       └─ PDF 输出改走 makePDF 外部 engine
  → HTML self-contained/embed resources（若启用）
  → TextOutput / BinaryOutput / ZipOutput
  → stdout 或目标文件/目标目录
```

关键裁决：

- `applyFilters` 位于 metadata 调整之后、`applyTransforms` 之前（`App.hs:304-309`），不是 writer 后处理；多个 filter 由 `Text.Pandoc.Filter:83-101` 的 `foldM` 串行执行，前一个 filter 的 Pandoc 输出是后一个 filter 的输入。
- `--extract-media` 的抽取在 writer 之前；`extractMedia` 把 MediaBag 写到目录或 `.zip`，并用 `walk` 改写图片路径（`Class/IO.hs:249-296`）。这不是“writer 自动上传资源”。
- `TextWriter` 结果会补换行（非 standalone 且末尾无 `\n` 时）；二进制 writer 保留 `ByteString`；`chunkedhtml` 使用 `ZipOutput`，当输出路径无扩展名时还会解压为目录（`App.hs:321-346`、`426-432`）。
- CLI 输出写入没有事务/原子替换层：`UTF8.writeFileWith`/`BL.writeFile` 直接写目标（`App.hs:121-136,426-432`）。因此目标文件部分写入、权限失败和磁盘满等情况必须由调用方按失败结果处理，不能假定回滚。

### 10.2 Reader/Writer 与 AST 的实际边界

`Readers.hs:132-189` 和 `Writers.hs:154-235` 的注册表分别以 `TextReader`/`ByteStringReader`、`TextWriter`/`ByteStringWriter` 表示文本/二进制边界；`getReader`/`getWriter` 通过 `Format.applyExtensionsDiff` 应用格式扩展，未知格式分别抛 `PandocUnknownReaderError`/`PandocUnknownWriterError`。`readJSON` (`Readers.hs:200-210`) 对输入做 `eitherDecode'`；`writeJSON` (`Writers.hs:246-247`) 对 Pandoc 做 `aeson encode`。

- `Text.Pandoc.Definition` 不在本仓库 `src/` 中，来自 `pandoc-types`；Cabal 约束为 `>=1.23.1 && <1.24`（`pandoc.cabal:549-552`、测试依赖 `839-863`）。块级/行内构造和 JSON `ToJSON/FromJSON` 不能只凭本仓库源码重建。
- “所有格式都严格成对”不成立：注册表有仅作为输入或仅作为输出的格式，具体由各表决定；正确结论是核心流程通过 Reader/Writer registry 扩展，不是“新增格式必然加一对实现”。
- JSON 是 native Pandoc AST 的序列化协议，不是独立业务 IR。`pandoc-api-version` 的字段实例在外部 `pandoc-types`；本地源码只能证明 decode/encode 边界，不能证明任意版本间自动兼容。
- Reader 的输入形态在 `Input.hs:60-77` 分流：文本输入支持多来源并可按 `inputFileScope` 对链接/标识符逐文件调整；二进制 reader 每个来源以 lazy `ByteString` 调用。输入源整体先由 `readSources` 读取，不能把它描述成流式逐块转换。

### 10.3 Filter 协议与失败语义

`Text.Pandoc.Filter:75-110` 是统一调度层：先用 `findFileWithDataFallback "filters"` 查工作目录和用户 data 目录，再按 `Filter` 构造执行 Lua、JSON 或内置 `CiteprocFilter`。在 `INFO` verbosity 下记录 `RunningFilter`/`FilterCompleted`，耗时来自 CPU time；这只是日志，不是超时控制。

JSON filter（`src/Text/Pandoc/Filter/JSON.hs:35-82`）的真实协议为：

1. 期望 filter 文件可执行；若存在但不可执行，按扩展选择 `python`、`runhaskell`、`perl`、`ruby`、`php`、`node`、`Rscript`，未知扩展则直接尝试文件路径。文件不存在时按命令名从 `PATH` 查找。
2. 命令参数为目标格式（`args`，`App.hs:291-309` 传入 `[T.unpack format]`）；旧细探的“自定义脚本”应收敛到这个明确边界。
3. 在既有环境上追加 `PANDOC_VERSION` 与 JSON 编码的 `PANDOC_READER_OPTIONS`；具体字段见 `doc/filters.md:439-495`。
4. 把当前完整 Pandoc JSON 写入 stdin，读取 stdout；只有 `ExitSuccess` 且 stdout 能 `eitherDecode'` 为 Pandoc 才成功。非零退出、缺可执行文件、启动异常或 stdout 非法 JSON 都统一包装为 `PandocFilterError`（`JSON.hs:62-82`）。stderr 不由 filter API 收集，而由 `pipeProcess` 继承父进程 stderr。
5. filter 没有源码级 timeout、输出大小上限、重试、取消接口或隔离目录；调用方需要在独立进程/宿主层补齐这些边界。串行 `foldM` 也意味着前一 filter 成功后，后一 filter 失败时没有整体回滚。

Lua filter 通过 `engineApplyFilter` 执行；Lua 模块另提供 `pandoc.pipe`（`pandoc-lua-engine/src/Text/Pandoc/Lua/Module/Pandoc.hs:219-235`），同样经 `pipeProcess` 启动任意命令，失败返回 `PipeError`/Lua error。因而“Lua 内置”不等于“没有外部进程或没有宿主风险”。

### 10.4 外部进程、临时文件与释放责任

| 场景 | 创建/持有 | 成功路径 | 失败/取消路径与已证实清理 | 未证实项 |
|---|---|---|---|---|
| JSON filter / Lua `pandoc.pipe` | `Text.Pandoc.Process.pipeProcess` 用 `proc` + stdin/stdout pipe 创建子进程；stderr `Inherit` | `BL.hGetContents` 强制消费 stdout，关闭 stdin/stdout，`waitForProcess` 返回退出码 | `withCreateProcess` 负责进程/句柄范围；`withForkWait` 在异步异常时杀死消费 stdout 的线程；写 stdin/close stdin 忽略 `EPIPE`（`Process.hs:51-112`） | 当前核对未实际启动 hostile filter，故未做子进程树/残留现场验证；没有源码级 wall-clock timeout |
| PDF `typst`/HTML engine | `makePDF` 用 `withTempDir` 创建工作目录；媒体先 `extractMedia`；`toPdfViaTempFile` 用 `withTempFile` 创建输入和输出文件 | 关闭临时文件初始 handles，写 source，外部 engine 退出后以 strict bytes 读 PDF，再返回 bytes（`PDF.hs:491-527`） | `withTempDirectory`/`withSystemTempDirectory`/`withTempFile` 是 bracket 风格范围；strict 读取明确为了 Windows 删除目录；外部程序异常映射为 PDF 错误 | 未实测各 engine 的崩溃、SIGKILL、子进程树和残留目录 |
| TeX/ConTeXt/Tectonic | 临时目录中写 `input.tex`；TeX 可能写 `.pdf/.log/.toc` 等；`inDirectory` 用 `bracket` 保存/恢复 cwd（`PDF.hs:269-467,529-563`；`Shared.hs:767-772`） | 读取 log/PDF 为 strict bytes；TeX 按 rerun warning 最多运行 4 次；成功只返回 PDF bytes | 临时目录作用域退出时清理；外部 `DoesNotExist` 转 `PandocPDFProgramNotFoundError`；非零退出转 `PandocPDFError` 上层 | 未实测引擎写出额外文件、锁文件或异常中断后的残留 |
| 图片转换 | TeX 路径可能调用 `rsvg-convert`，PNG/JPEG 通过 JuicyPixels 写入同一临时目录，文件名由 SHA1 路径派生（`PDF.hs:221-267`） | 成功返回临时目录中的新路径，writer 使用该路径 | 转换失败仅报告 `CouldNotConvertImage` 并保留原引用；`makePDF` 的临时目录负责范围清理 | 未实测恶意 SVG、超大图片、工具挂死 |
| `--extract-media` | MediaBag 持有内存中的媒体；`writeMedia` 创建目标父目录并写文件（`Class/IO.hs:270-285`） | 写完后 walk 改写图片路径 | `writeMedia` 对单个写入使用 `logIOError`，I/O 失败可能只记 `IgnoredIOError`，不是必然让整次转换失败；无事务清理 | 未实测部分写入、磁盘满、路径穿越输入 |
| `inDirectory` | 进程全局 cwd 被临时切换 | `bracket` 恢复原 cwd | 异常也恢复 cwd；但 cwd 是进程级状态，不能并发安全使用 | 未做并发转换验证 |

`pipeProcess` 是本项目最清楚的进程资源证据：stdout 先被惰性读取但通过 `rnf` 强制消费，随后关闭 handles、等待进程；异常时由 `withCreateProcess` 的作用域清理，避免只凭“函数返回”推断已释放。与此同时，源码没有为 PDF engine/filter 提供统一进程组、wall-clock timeout 或宿主崩溃后的跨进程清理协议；这些是独立接入层的必补契约。

### 10.5 PandocIO、PandocPure 与 HTTP server 的事实差异

- `PandocIO` 是 `ExceptT PandocError (StateT CommonState IO)`，`runIO` 返回 `Either PandocError a`，`runIOorExplode` 调 `handleError` 并按错误类型退出（`Class/PandocIO.hs:34-53`、`Error.hs:158-208`）。CLI 的 `convertWithOpts` 再把错误抛给顶层 handler，并在成功后落盘。
- `PandocPure` 用 `PureState` 中的 `FileTree`、stdin、时间、环境和 MediaBag 模拟资源，`openURL` 总是 `PandocResourceNotFound`，缺文件也返回同一错误（`Class/PandocPure.hs:72-106,175-215`）。它不是“执行后再禁止 I/O”，而是从实例层根本不实现网络/真实文件 I/O。
- server 的 `convert'`（`pandoc-server/src/Text/Pandoc/Server.hs:254-419`）把请求 `files` 写进纯内存 `FileTree`，直接执行 reader → 内置 transforms → 可选 `processCitations` → writer。该函数**没有调用 `applyFilters`**；因此 server 不是“把 JSON/Lua filter 在 pure 中执行失败”，而是当前 API 路径根本不调自定义 filter。PDF engine、外部 filters、HTTP 抓取和未注入 `files` 的资源也都不可用。
- server 默认 `serverPort=3030`、`serverTimeout=2`（`pandoc-server/src/Text/Pandoc/Server.hs:61-63`）；CLI server/CGI 用 WAI `timeout` middleware（`pandoc-cli/server/PandocCLI/Server.hs:23-35`）。这是 HTTP 请求级超时，不是 filter/PDF 子进程级超时；`batch` 只是逐项 `mapM convertJSON`，不是并行或事务批处理。
- server JSON 错误返回 `{"error": ...}`，文本/字节路由把 `PandocError` 渲染为 HTTP 500；成功 JSON 另返回 `output/base64/messages`（`Server.hs:170-180,426-432`）。因此 CLI exit code、HTTP status 和 server JSON error 是三套外部错误表，不能互相替代。

### 10.6 错误分类与资源/失败矩阵

| 失败点 | 源码错误/结果 | CLI 行为 | server/pure 行为 | 证据等级 |
|---|---|---|---|---|
| Reader/Writer 不存在 | `PandocUnknownReaderError` / `PandocUnknownWriterError` | 渲染消息并退出 21/22 | `runPure` Left，转 HTTP 500 或 JSON `error` | 源码确认 |
| JSON AST 非法 | `PandocParseError`（`readJSON`） | 退出 64 | 500/`error` | 源码确认 |
| 输入 UTF-8/二进制误判 | `PandocUTF8DecodingError` / `PandocInputNotTextError`；已知 ZIP/PDF/CFBF/DjVu 签名拒绝按文本读 | 退出 92/95 | 同类 error | 源码确认 |
| 文件/HTTP/资源失败 | `PandocIOError`、`PandocHttpError`、`PandocResourceNotFound` | I/O 1、HTTP 61、资源 99；`fillMediaBag` 对图片可降级为 alt/placeholder 并记录 warning | Pure 不联网，缺 `files` 失败 | 源码确认，降级细节见 `Class/PandocMonad.hs:509-540` |
| filter 失败 | `PandocFilterError` | 退出 83；stderr 可能已有子进程输出 | server 当前不调用自定义 filter | 源码确认 |
| PDF engine 缺失/失败 | `PandocPDFProgramNotFoundError` / 上层 `PandocPDFError` | 退出 47/43 | pure 路径无 engine | 源码确认 |
| warning | `report` 进入 CommonState log；`--fail-if-warnings` 检查 `WARNING` | `PandocFailOnWarningError`，退出 3 | JSON `messages` 保留日志；不等同失败 | 源码确认 |
| 外部子进程挂死/宿主崩溃 | 本地源码无统一 wall-clock/进程组协议 | 不能从 `ExitCode` 证明已清理 | HTTP middleware 只包请求 | **未验证/能力缺口** |
| 目标文件部分写入 | `writeFile`/`BL.writeFile` 直写 | 失败时无源码级 rollback | server 返回 bytes，不直接写用户目标 | **源码确认的风险** |

### 10.7 真假验证账本（当前核对不把“存在”冒充“通过”）

| 验证层 | 本地证据 | 当前核对状态 | 可宣称内容 |
|---|---|---|---|
| 源码存在 | `App.hs`、`Input.hs`、`Filter.hs`、`Filter/JSON.hs`、`Process.hs`、`PDF.hs`、`Error.hs`、`Class/*` 等路径实际读取 | 已确认 | 可以写实现事实和路径引用 |
| 测试源码存在 | `test/test-pandoc.hs` 注册 `Tests.Command`、Readers/Writers、MediaBag/XML 等；`pandoc.cabal:839-927` 注册 `test-pandoc` | 已确认 | 只能说“有测试入口/夹具”，不能说测试通过 |
| 历史构建/CI | `.github/workflows/*`、`.circleci/config.yml` 存在 | 已确认为配置存在 | 不能当作本地当前版本通过证据 |
| 当前核对静态核对 | 逐段读取旧细探并与上述源码、Cabal、文档路径对照；新增本节与收口表 | 已执行 | 可以宣称“文档结论已按源码校正” |
| 当前核对真实 build/test | 未执行 `cabal build`、`cabal test`、安装依赖、启动服务 | 明确未执行 | 不得宣称可构建、测试通过或服务可用 |
| 外部依赖实测 | 未启动 Python/Lua/PDF engine/`rsvg-convert`/HTTP provider；未做 hostile filter、超时、SIGKILL、OOM、磁盘满或残留扫描 | 明确未执行 | 只能写“源码声明/未验证”，不能写运行时保证 |
| 文档结构/范围 | 本次只修改目标根 `ARCHITECTURE.md`；旧 `细探-pandoc.md` 保留 | 收口后需现场复核 | 可以宣称改动范围满足任务边界，前提是最终 `git status` 复核通过 |

因此当前核对的“验证通过”仅指源码路径、旧细探逐条对照、Markdown 章节和改动范围的静态验证；不等于 Pandoc 本地 build/test、外部 engine、filter 进程清理或 HTTP 运行验证通过。

### 10.8 后续补正：资源作用域与测试真假边界

当前核对进一步按实现逐项复核后，以下细节需要从“可能清理”收窄为可证和不可证两部分：

- `pipeProcess` 的成功路径是“消费完整 stdout → 关闭 stdin/stdout → `waitForProcess`”；`stderr = Inherit`，所以 filter/PDF engine 的 stderr 不是返回值的一部分，而是直接进入父进程 stderr。`withCreateProcess` 的 bracket 作用域负责句柄和子进程的异常清理，`withForkWait` 只负责 stdout 消费线程的等待与异常时杀线程；这不等价于统一的子进程组清理或 wall-clock timeout。
- `pipeProcess` 对写入 stdin 和关闭 stdin 忽略 `EPIPE`，但其他 I/O 异常仍会抛出。调用方看到 `PandocFilterError` 或 PDF 错误时，可以确认错误已归类，不能仅凭错误返回确认外部进程树、孙进程或宿主工具已经终止。
- PDF 的 `makePDF` 以 `withTempDirectory`/`withSystemTempDirectory` 包住媒体、TeX、日志和 PDF 读取；读出 PDF 前转换为 strict bytes 是为了让目录可删除。可是 `toPdfViaTempFile` 明确使用 `withTempFile "."`，临时输入/输出文件位于当前工作目录而不是必然位于系统临时目录；它们由 `withTempFile` 作用域清理，但当前工作目录本身仍是外部 engine 的工作边界。
- `withTempDir` 在 `typst`、路径含 `~` 或 Cygwin 情况下选择当前目录下的 `withTempDirectory "."`，其他情况选择系统临时目录。该选择是兼容路径策略，不是安全隔离策略；文档接入层仍应使用专用工作目录、权限限制和残留扫描。
- `inDirectory` 用 bracket 恢复进程 cwd，故异常路径可证明 cwd 恢复；cwd 是进程级全局状态，不能据此证明并发调用安全。调用方若并发转换，应使用独立进程或保证不会交叉切换 cwd。
- `extractMedia` 对媒体路径做 URI 解码和 `normalise` 后拼接目标目录，但本地实现没有显式的“规范化后仍在目标目录内”校验；输入媒体名含路径分隔符时不能把它描述成已完成路径穿越防护。`logIOError (BL.writeFile ...)` 还意味着单个媒体写失败可能只进入日志，不能默认使整个转换失败或回滚已写文件。

### 10.9 验证入口的真实强度

源码中的测试入口也必须按实际执行方式分级，而不能把 golden 文件或 CI 配置当作通过证据：

| 证据 | 实际行为 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| `test/test-pandoc.hs` + `pandoc.cabal` | 注册 Tasty 测试，覆盖 Reader/Writer、命令场景、Office/XML、媒体和 golden 资源 | 当前源码声明了可运行的测试套件 | 本机已经编译、执行、通过，或外部 engine 可用 |
| `test/Tests/Command.hs` | 从 `test/command/*.md` 读取 `%` 命令，用 `shell` 启动测试命令，捕获 stdout/stderr 和退出码；golden 比较可更新期望 | CLI 场景的协议和预期输出格式 | 没有 shell 风险、超时、进程树清理、磁盘回滚或真实发布环境等保证 |
| golden 输入/输出、Office archive 比较 | 对文本、归档成员、XML 和媒体内容做确定性比较 | 某个已执行场景的输出与基线一致 | 未覆盖的格式、资源耗尽、异常取消、宿主程序版本差异 |
| `Makefile`、`.github/workflows`、`.circleci` | 声明 `cabal test`、检查和 CI 任务 | 项目维护者定义了验证路径 | 本地当前快照已经跑过这些任务 |
| 当前核对源码阅读 | 读取并对照 `App`、`Input`、`Filter`、`Process`、`PDF`、`Class`、错误和测试实现 | 本档的执行顺序、错误边界、资源作用域已按源码校正 | Pandoc build/test、filter/PDF 实测、超时/SIGKILL/OOM、残留和并发安全 |

测试命令自身没有为每个 command fixture 增加 wall-clock timeout；因此测试“退出码为 0”也只代表该测试进程完成并通过比较，不代表被测 filter 或 PDF engine 具备独立超时。真实接入验收至少要把以下项目作为独立证据：构建成功、定向 Reader/Writer golden 通过、故意失败的 filter/PDF 错误归类、超时取消后的进程/目录残留扫描、目标文件失败后的部分写入检查，以及 HTTP pure 路径对 filters/PDF/网络资源不可用的断言。

## 11. 结论

`pandoc` 的真实核心仍是 `输入 → Reader → Pandoc AST → Filter/Transform → Writer → 输出`，但可落地的调用契约还包括：输入先整体读入、文本/二进制分流、filters 串行 JSON/Lua 进程边界、MediaBag 资源策略、PDF 临时目录与外部 engine、`PandocIO`/`PandocPure` 双运行模型，以及 CLI/server 各自的错误表。旧细探关于统一 AST、`pandoc-api-version` 和 filter 的方向有效；当前核对已将“对称扩展”“纯确定性”“GPL 只能独立进程”等过宽或未充分证实的表述收窄为源码可证事实和明确风险。

当前工作树仍为本地 `3.10.1` 快照，远程 main 已到 `3.10.2`。当前核对只更新本文件，未改源码、依赖、测试、配置、旧细探或 Git；未安装、启动、构建、运行完整测试或实测外部进程。后续若要将 Pandoc 接入平台，最低验收契约应显式包含格式白名单、AST API 版本、filter 禁止/允许策略、输入/输出大小、PDF/filter wall-clock timeout、进程组清理、临时目录残留扫描、目标文件原子写入和失败证据。

## 12. 代码地图现状复核（2026-08-22）

此前“目标仓库无 `.codegraph`”是早期审计时的现场状态，不能继续作为当前状态。当前目标根 `/Users/hekunhua/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/pandoc` 存在独立 `.codegraph/`；在该根执行 `codegraph status` 退出码为 0，返回 233 files、802 nodes、1,689 edges。该索引只用于源码导航，未把代码图状态升级为运行/测试通过证据。
