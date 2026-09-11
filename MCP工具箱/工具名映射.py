"""中文工具名 ↔ 英文协议名 稳定映射（SEP-986：Tool.name 仅允许 [A-Za-z0-9_.-]+）。"""

中文名到协议名 = {
    "登记需求": "register_requirement",
    "复用搜索": "reuse_search",
    "登记能力占用": "claim_capability",
    "应用文件补丁": "apply_file_patch",
    "校验模块合规": "validate_module_compliance",
    "生成模块模板": "generate_module_template",
    "创建核心快照": "create_core_snapshot",
    "查询核心快照": "query_core_snapshot",
    "兼容性检查": "compatibility_check",
    "回滚门禁": "rollback_gate",
    "运行发布门禁": "run_release_gate",
    "检查发布证据": "check_release_evidence",
    "生成发布证据": "generate_release_evidence",
    "切换激活指针": "switch_active_pointer",
    "依赖裁决": "dependency_arbitration",
    "登记任务": "register_task",
    "协作状态": "collaboration_status",
    "收口登记": "delivery_closeout",
    "校验验证命令": "validate_verification_command",
    "判定验证结果": "judge_verification_result",
}
协议名到中文名 = {协议名: 中文名 for 中文名, 协议名 in 中文名到协议名.items()}
