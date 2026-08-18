# MCP工具箱 · 系统工程平台 MCP

系统工程平台专属 MCP 服务：项目身份、代码地图、记忆、验证证据与统一网关工具面。
**单网关无角色**：所有工具对网关调用者开放，默认拒绝、不静默放行
（未知工具名、未授权开工id、越界路径、非法参数一律拒绝）。

## 架构

- **唯一入口**：`项目服务.py`，Streamable HTTP 单端口 8766 单实例。
- **网关定义**：`角色权限.py`。保留 `越权拒绝(PermissionError)` 语义，
  提供 `网关实例名`、`网关角色名`、`网关说明()` 与 `获取角色指南(工具名)`；
  角色工具白名单、目录边界与验证命令白名单已全部移除，网关直通全部工具。
- **工具发现**：`tool_catalog` 是只读发现工具，返回全量工具清单与当前实例可调用性；
  未注入的工具同样可经目录发现后调用（网关模式不再按角色过滤）。

## 启动方式（HTTP）

平台 MCP 以 **Streamable HTTP** 协议对外提供（stdio 已废弃），供 opencode
以 `remote` 方式接入：

```bash
./MCP工具箱/启动HTTP服务.sh [端口]
# 默认端口 8766，单网关无角色
```

- 单网关单实例，固定端口 8766，不再按角色区分实例或端口。
- 项目级 `opencode.json` 已注册 `system_engineering_toolkit` 为
  `remote: http://127.0.0.1:8766/mcp/`。
- 服务根路径固定为 `/mcp/`，与 `项目服务.py::主程序HTTP` 一致。

> 聚合接入：华世王镞_v3 侧只载入聚合 MCP，本平台工具经 `se_` 前缀路由到
> `system_engineering_toolkit` 网关（只负责路由，不改变工具面）。（聚合方案落地中）

## 工具目录（tool_catalog）

`tool_catalog` 是只读发现工具，不触碰项目资源：

- 按**分类**过滤：基础 / 公开能力 / 开发 / 支持库 / 模块 / 核心 / 发布 / 协作 /
  记忆 / 验证 / 工作区 / 临时上下文 / 任务观测 / 测试资源。
- 按**关键词**过滤工具名或描述。
- 返回中文名、协议名、描述、分类、当前实例可调用性。

```json
{"分类": "验证", "关键词": "验证"}
```

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

## 网关安全边界

- 开工与协作：反馈、验证入账、临时上下文写入等只认当前开工id或
  `工程缓存/协作状态/` 下已登记的开工id（防伪造身份）。
- 测试资源：临时根固定 `工程缓存/测试临时/`，仅清理登记且为本进程派生
  集合内的子进程/端口占用（防任意 kill）。
- 发布治理：提交必须是 40 位十六进制（防证据文件路径穿越）；激活指针 CAS 切换。
- 核心回滚：快照标识拒绝绝对路径与 `..` 段；执行回滚前复核激活指针未变（CAS）。
- 所有工具参数非法（KeyError/ValueError/TypeError）统一返回
  `{"成功": False, "错误码": "参数无效", "错误说明": ...}`。

## 验证

```bash
python3.14 -m py_compile MCP工具箱/项目服务.py MCP工具箱/角色权限.py
./MCP工具箱/启动HTTP服务.sh 8766   # 启动后 curl POST /mcp/ initialize 验证
python3.14 测试中心/运行测试.py --测试文件 测试中心/MCP工具箱/…
```