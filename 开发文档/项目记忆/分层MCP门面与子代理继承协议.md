---
名称: 分层MCP门面与子代理继承协议
标签: [架构, MCP, 任务信, 收信验收, 反馈, 已实现]
创建时间: 2026-08-01T11:46:01.517478+00:00
---

任务信必须显式包含 project_context 开工、角色门面、子代理递归继承、mcp_feedback 五字段、反馈后 verify_and_record、回信携带开工id。平台MCP新增 feedback_review，仅平台维护者和发布者可用，可按 work_id 或 task 读取原始反馈与升级候选。收信不能只看回信：必须 feedback_review(work_id=回信开工id)，比对反馈与验证顺序，并将候选分类为本次立即修复、进入平台升级池、无需处理。缺开工id、缺原始反馈或验证早于反馈均不得验收完成。

子代理上下文采用临时层：主代理用 temporary_context(写入) 写入子任务范围、定向记忆查询、已确认事实和验证命令；子代理只读取该开工id的上下文，发现不足时按查询词追加，不得扫描全部历史。临时上下文只写工程缓存/MCP临时上下文，绑定项目和开工id，默认两小时过期，收工后必须 temporary_context(清理)。它不进入长期记忆、不提升可信度、不替代 project_context、codegraph_explore、mcp_feedback 或 verify_and_record。影响架构的结论才由主代理提升到长期记忆。
