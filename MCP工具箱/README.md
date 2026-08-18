# MCP工具箱 · 系统工程平台 MCP

系统工程平台专属 MCP 服务：项目身份、代码地图、记忆、验证证据与角色化工具面。
单实例多角色，服务端按角色过滤工具与写权限，默认拒绝、不静默放行。

## 架构

- **唯一入口**：`项目服务.py`。所有角色共用一个权威 MCP 服务进程逻辑；
  实例名不再随角色变化，由环境变量 `SYSTEM_ENGINEERING_MCP_ROLE` 指定默认角色。
- **角色→工具映射**：`角色权限.py`。维护 8 个角色（调用者、支持库开发者、模块开发者、
  核心开发者、项目开发者、平台构建开发者、平台维护者、发布者）的工具白名单、
  目录边界与验证命令白名单；越权调用一律抛 `越权拒绝`，不静默放行。
- **精简注入**：每个实例只直接注入「基础 + 业务核心 + tool_catalog」，
  其余工具经 `tool_catalog` 按分类/关键词发现后再按实例角色集白名单校验调用。

## 启动方式（HTTP）

平台 MCP 以 **Streamable HTTP** 协议对外提供（stdio 已废弃），供 opencode
以 `remote` 方式接入：

```bash
./MCP工具箱/启动HTTP服务.sh [端口] [角色]
# 默认端口 8766，默认角色 平台维护者
```

- 一个 HTTP 服务进程固定一个角色（角色在导入期由环境变量
  `SYSTEM_ENGINEERING_MCP_ROLE` 确定）；需要多角色并存时开多个端口。
- 项目级 `opencode.json` 已注册 `system_engineering_toolkit` 为
  `remote: http://127.0.0.1:8766/mcp/`。
- 服务根路径固定为 `/mcp/`，与 `项目服务.py::主程序HTTP` 一致。

### 多角色端口建议

| 端口 | 承载角色 | 默认角色 | 覆盖 |
|---|---|---|---|
| 8766 | 平台维护者、发布者 | 平台维护者 | 治理/门禁/发布面 |
| 8767 | 支持库、模块、核心、项目、平台构建 5 开发者 | 核心开发者 | 各开发面 |
| 8768 | 调用者 | 调用者 | 只读公开契约面 |

> 聚合接入：华世王镞_v3 侧只载入聚合 MCP，本平台工具经 `se_` 前缀路由到
> `system_engineering_toolkit`（平台维护者）HTTP 实例；平台自身
> `opencode.json` 以 remote 注册本平台 HTTP 服务。（聚合方案落地中）

## 工具目录（tool_catalog）

`tool_catalog` 是只读发现工具，对所有实例开放，不触碰项目资源：

- 按**分类**过滤：基础 / 公开能力 / 开发 / 支持库 / 模块 / 核心 / 发布 / 协作 /
  记忆 / 验证 / 工作区 / 临时上下文 / 任务观测 / 测试资源。
- 按**关键词**过滤工具名或描述。
- 返回中文名、协议名、描述、分类、当前实例可调用性。

```json
{"分类": "验证", "关键词": "验证"}
```

调用未注入的工具仍受实例角色集白名单校验，越权拒绝。

## 工具清单（44 个）

| 分类 | 工具 |
|---|---|
| 基础 | project_context、role_profile、mcp_feedback、feedback_status、feedback_review、tool_catalog |
| 公开能力 | capability_search、capability_read |
| 开发 | codegraph_explore、support_library_development_guide、module_development_guide、core_development_guide、project_development_guide、platform_build_development_guide、platform_maintenance_guide、release_guide |
| 支持库 | 登记需求、复用搜索、登记能力占用 |
| 模块 | 校验模块合规、生成模块模板 |
| 核心 | 创建核心快照、查询核心快照、兼容性检查、回滚门禁 |
| 发布 | 运行发布门禁、检查发布证据、生成发布证据、切换激活指针、依赖裁决 |
| 协作 | 登记任务、协作状态、收口登记 |
| 记忆 | memory_search、memory_write |
| 验证 | verify_and_record、verification_plan、校验验证命令、判定验证结果 |
| 工作区 | workspace、development_start |
| 临时上下文 | temporary_context |
| 任务观测 | task_observation |
| 测试资源 | test_resource |

## 角色工具面

| 角色 | 可用工具面 | 边界 |
|---|---|---|
| 调用者 | 基础工具 | 只读公开能力目录与契约 |
| 支持库开发者 | 基础 + 开发 + 支持库协作 | 只开发原子能力与第三方边界 |
| 模块开发者 | 基础 + 开发 + 模块工具 | 只组合支持库公开能力 |
| 核心开发者 | 基础 + 开发 + 核心治理 | 只开发跨项目运行治理 |
| 项目开发者 | 基础 + 开发 | 只绑定项目与公开能力 |
| 平台构建开发者 | 基础 + 开发 | 只维护客户端制品构建与包仓库 |
| 平台维护者 | 基础 + 开发 + 维护/门禁/协作 | 不执行发布签名 |
| 发布者 | 基础 + 开发 + 发布治理 | 只审核、签名、激活、回滚 |

## 验证

```bash
python3.14 -m py_compile MCP工具箱/项目服务.py MCP工具箱/角色权限.py
./MCP工具箱/启动HTTP服务.sh 8766 平台维护者   # 启动后 curl POST /mcp/ initialize 验证
python3.14 测试中心/运行测试.py --测试文件 测试中心/…（按角色范围限定）
```
