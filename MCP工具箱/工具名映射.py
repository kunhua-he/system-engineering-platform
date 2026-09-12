"""中文工具名 ↔ 英文协议名 稳定映射（SEP-986：Tool.name 仅允许 [A-Za-z0-9_.-]+）。

中文名是给人看的门面（工具目录、调用侧归一化）；协议名是唯一对外真名。
全量工具都必须有中文名——由 测试中心/MCP工具箱/测试_项目服务.py 的覆盖率测试兜底。
"""

中文名到协议名 = {
    # 上下文与画像
    "项目上下文": "project_context",
    "角色画像": "role_profile",
    "开发开工": "development_start",
    "代码地图探索": "codegraph_explore",
    "记忆搜索": "memory_search",
    "记忆写入": "memory_write",
    "临时上下文": "temporary_context",
    "任务观测": "task_observation",
    "隔离工作区": "workspace",
    "测试资源": "test_resource",
    "工具目录": "tool_catalog",
    "热重载工具模块": "reload_tool_modules",
    # 能力发现
    "搜索能力": "capability_search",
    "读取能力": "capability_read",
    # 反馈
    "提交反馈": "mcp_feedback",
    "反馈状态": "feedback_status",
    "反馈复核": "feedback_review",
    # 专属指南
    "支持库开发指南": "support_library_development_guide",
    "模块开发指南": "module_development_guide",
    "核心开发指南": "core_development_guide",
    "项目适配开发指南": "project_development_guide",
    "平台构建开发指南": "platform_build_development_guide",
    "平台维护指南": "platform_maintenance_guide",
    "发布者指南": "release_guide",
    # 验证
    "验证计划": "verification_plan",
    "验证并记录": "verify_and_record",
    # 需求与占用
    "登记需求": "register_requirement",
    "复用搜索": "reuse_search",
    "登记能力占用": "claim_capability",
    "文件占用租约": "file_lease",
    # 写入与合规
    "应用文件补丁": "apply_file_patch",
    "校验模块合规": "validate_module_compliance",
    "生成模块模板": "generate_module_template",
    # 核心快照与回滚
    "创建核心快照": "create_core_snapshot",
    "查询核心快照": "query_core_snapshot",
    "兼容性检查": "compatibility_check",
    "回滚门禁": "rollback_gate",
    # 发布门禁
    "运行发布门禁": "run_release_gate",
    "检查发布证据": "check_release_evidence",
    "生成发布证据": "generate_release_evidence",
    "切换激活指针": "switch_active_pointer",
    "依赖裁决": "dependency_arbitration",
    # 协作与收口
    "登记任务": "register_task",
    "协作状态": "collaboration_status",
    "收口登记": "delivery_closeout",
    # 验证命令
    "校验验证命令": "validate_verification_command",
    "判定验证结果": "judge_verification_result",
    # 后台作业
    "提交作业": "tool_job_submit",
    "查询作业": "tool_job_query",
    "取消作业": "tool_job_cancel",
}
协议名到中文名 = {协议名: 中文名 for 中文名, 协议名 in 中文名到协议名.items()}
