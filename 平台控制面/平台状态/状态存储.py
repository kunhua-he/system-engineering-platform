"""平台控制面权威状态：复用 运行核心.权威状态 的存储机制（子类化）。

六个权威服务（需求登记/能力目录/包仓库/策略中心/发布管理/证据账本）共用
本存储——每类事实只有一个权威写入口，禁止各自维护 JSON 真相。
子类化复用：连接管理、WAL、迁移器（BEGIN IMMEDIATE 串行化、失败证据、
假升级补列）、栅栏令牌与 CAS 全部继承；本类只扩展 1.3.0 平台表。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from 运行核心.权威状态 import 权威状态, 版本元组


class 平台状态(权威状态):
    """平台控制面状态（结构 1.3.0：六服务表 + 信任 + 激活指针 + 核心快照）。"""

    目标版本 = "1.4.0"
    迁移序列表 = 权威状态.迁移序列表 + [("1.3.0", "_迁移到130"), ("1.4.0", "_迁移到140")]
    校验规则表 = {
        **权威状态.校验规则表,
        "1.3.0": {"表": ["证据", "需求", "工作包", "能力条目", "占用租约", "制品",
                          "信任", "策略", "发布", "激活指针", "核心快照"]},
        "1.4.0": {"表": ["能力反馈"], "列": [("能力反馈", "去重键"), ("能力反馈", "状态")]},
    }

    def _迁移到130(self, 连接) -> None:
        """1.3.0：平台控制面六服务表 + 信任/激活指针/核心快照。"""
        连接.executescript("""
            CREATE TABLE IF NOT EXISTS 证据(
                证据id TEXT PRIMARY KEY, 类型 TEXT, 主题 TEXT, 内容 TEXT,
                操作id TEXT, 调用者 TEXT, 角色 TEXT, 来源快照 TEXT,
                结果 TEXT, 错误码 TEXT, 时间 TEXT, 哈希 TEXT);
            CREATE TABLE IF NOT EXISTS 需求(
                需求id TEXT PRIMARY KEY, 版本 TEXT, 状态 TEXT, 快照 TEXT,
                验收契约 TEXT, 装配计划 TEXT, 变更影响 TEXT, 确认状态 TEXT,
                创建时间 TEXT);
            CREATE TABLE IF NOT EXISTS 工作包(
                工作包id TEXT PRIMARY KEY, 需求id TEXT, 波次 INTEGER, 说明 TEXT,
                输入快照 TEXT, 允许修改路径 TEXT, 能力占用 TEXT, 资源预算 TEXT,
                验收命令 TEXT, 状态 TEXT);
            CREATE TABLE IF NOT EXISTS 能力条目(
                能力id TEXT PRIMARY KEY, 契约指纹 TEXT, 组件 TEXT, 领域 TEXT,
                成熟度 TEXT, 所有者 TEXT, 替代能力 TEXT, 复用裁决 TEXT,
                裁决状态 TEXT, 提供者 TEXT, 资源 TEXT, 版本 TEXT, 依赖 TEXT DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS 占用租约(
                租约id TEXT PRIMARY KEY, 能力id TEXT, 领域 TEXT, 契约指纹 TEXT,
                任务 TEXT, 所有者 TEXT, 心跳 REAL, 过期时间 REAL,
                释放证据 TEXT, 状态 TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS 索引_占用活跃
                ON 占用租约(能力id) WHERE 状态='活跃';
            CREATE TABLE IF NOT EXISTS 角色授予(
                授予id TEXT PRIMARY KEY, 身份id TEXT, 所有者 TEXT, 项目范围 TEXT,
                角色 TEXT, 授予者 TEXT, 有效期 REAL, 撤销状态 TEXT, 证据 TEXT);
            CREATE TABLE IF NOT EXISTS 制品(
                制品摘要 TEXT PRIMARY KEY, 包id TEXT, 版本 TEXT, 文件清单 TEXT,
                物料清单 TEXT, 来源证据 TEXT, 签名 TEXT, 签名者 TEXT,
                签名时间 TEXT, 状态 TEXT, 构建输入 TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS 索引_制品包版本
                ON 制品(包id, 版本);
            CREATE TABLE IF NOT EXISTS 信任(
                发布者 TEXT PRIMARY KEY, 公钥 TEXT, 状态 TEXT,
                轮换时间 TEXT, 过期时间 TEXT);
            CREATE TABLE IF NOT EXISTS 策略(
                策略id TEXT PRIMARY KEY, 类型 TEXT, 规则 TEXT, 版本 TEXT,
                决定 TEXT, 时间 TEXT);
            CREATE TABLE IF NOT EXISTS 发布(
                发布id TEXT PRIMARY KEY, 包id TEXT, 期望版本 TEXT, 候选版本 TEXT,
                灰度比例 REAL, 激活指针 TEXT, 状态 TEXT, 回滚事务 TEXT, 时间 TEXT);
            CREATE TABLE IF NOT EXISTS 激活指针(
                指针id TEXT PRIMARY KEY, 目标 TEXT, 版本 INTEGER, 栅栏令牌 INTEGER,
                状态 TEXT);
            CREATE TABLE IF NOT EXISTS 核心快照(
                快照id TEXT PRIMARY KEY, 摘要 TEXT, 核心版本 TEXT, 状态兼容 TEXT,
                回滚许可 TEXT, 迁移方式 TEXT, 签名 TEXT, 签名者 TEXT, 状态 TEXT);
        """)

    def _迁移到140(self, 连接) -> None:
        """1.4.0：能力反馈唯一持久化表与幂等索引。"""
        连接.executescript("""
            CREATE TABLE IF NOT EXISTS 能力反馈(
                反馈id TEXT PRIMARY KEY, 去重键 TEXT NOT NULL UNIQUE,
                来源系统 TEXT NOT NULL, 来源版本 TEXT NOT NULL,
                请求id TEXT NOT NULL, 能力id TEXT NOT NULL,
                契约版本 TEXT NOT NULL, 错误码 TEXT NOT NULL,
                错误说明 TEXT NOT NULL, HTTP状态码 INTEGER NOT NULL,
                请求摘要 TEXT NOT NULL, 响应摘要 TEXT NOT NULL,
                复现标识 TEXT NOT NULL, 优先级 TEXT NOT NULL,
                状态 TEXT NOT NULL, 创建时间 TEXT NOT NULL,
                更新时间 TEXT NOT NULL, 处理者 TEXT NOT NULL,
                状态原因 TEXT NOT NULL, 关联提交 TEXT NOT NULL,
                验证证据 TEXT NOT NULL, 发布制品 TEXT NOT NULL,
                内容摘要 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS 索引_能力反馈状态
                ON 能力反馈(状态, 更新时间 DESC);
            CREATE INDEX IF NOT EXISTS 索引_能力反馈能力
                ON 能力反馈(能力id, 更新时间 DESC);
        """)

    # ---- 六服务通用读写（唯一写入口） ----
    def 写入记录(self, 表: str, 记录: dict[str, Any], 主键: str = "id") -> None:
        """按主键写入记录；已存在时只更新传入字段（合并，不丢其他字段）。

        注意：部分更新（如 生成装配计划 只写 装配计划 字段）不得清空
        同一记录的其他字段（需求确认状态等）。
        """
        主键值 = 记录.get(主键)
        if 主键值 is not None:
            已有 = self.读取记录(表, 主键, str(主键值))
            if 已有 is not None:
                记录 = {**已有, **记录}
        字段表 = list(记录)
        占位符 = ", ".join(["?"] * len(字段表))
        列名 = ", ".join(字段表)
        连接 = self._连接()
        with 连接:
            连接.execute(
                f"INSERT OR REPLACE INTO {表}({列名}) VALUES({占位符})",
                [记录[字段] for 字段 in 字段表])

    def 原子插入(self, 表: str, 记录: dict[str, Any]) -> bool:
        """INSERT OR IGNORE：唯一约束冲突返回 False（并发互斥的原子防线）。"""
        字段表 = list(记录)
        占位符 = ", ".join(["?"] * len(字段表))
        列名 = ", ".join(字段表)
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                f"INSERT OR IGNORE INTO {表}({列名}) VALUES({占位符})",
                [记录[字段] for 字段 in 字段表])
            return 游标.rowcount > 0

    def 读取记录(self, 表: str, 主键列: str, 主键值: str) -> dict[str, Any] | None:
        连接 = self._连接()
        行 = 连接.execute(f"SELECT * FROM {表} WHERE {主键列}=?", (主键值,)).fetchone()
        if 行 is None:
            return None
        列名 = [描述[1] for 描述 in 连接.execute(f"PRAGMA table_info({表})").fetchall()]
        return dict(zip(列名, 行))

    def 查询记录(self, 表: str, 条件: str = "", 参数: tuple = ()) -> list[dict[str, Any]]:
        连接 = self._连接()
        条件SQL = f"WHERE {条件}" if 条件 else ""
        结果表 = []
        for 行 in 连接.execute(f"SELECT * FROM {表} {条件SQL}", 参数):
            列名 = [描述[1] for 描述 in 连接.execute(f"PRAGMA table_info({表})").fetchall()]
            结果表.append(dict(zip(列名, 行)))
        return 结果表

    def 条件更新(self, 表: str, 更新: dict[str, Any], 条件SQL: str, 参数: tuple) -> bool:
        赋值 = ", ".join([f"{字段}=?" for 字段 in 更新])
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                f"UPDATE {表} SET {赋值} WHERE {条件SQL}",
                [更新[字段] for 字段 in 更新] + list(参数))
            return 游标.rowcount > 0

    # ---- 证据账本（追加写，旧证据不可覆盖） ----
    def 追加证据(self, *, 类型: str, 主题: str, 内容: dict[str, Any],
                操作id: str = "", 调用者: str = "", 角色: str = "",
                来源快照: str = "", 结果: str = "", 错误码: str = "") -> str:
        证据id = uuid.uuid4().hex[:20]
        正文 = json.dumps(内容, ensure_ascii=False)
        哈希 = __import__("hashlib").sha256(正文.encode("utf-8")).hexdigest()[:16]
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT INTO 证据(证据id, 类型, 主题, 内容, 操作id, 调用者, 角色, "
                "来源快照, 结果, 错误码, 时间, 哈希) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (证据id, 类型, 主题, 正文, 操作id, 调用者, 角色, 来源快照,
                 结果, 错误码, time.strftime("%Y-%m-%d %H:%M:%S"), 哈希))
        return 证据id

    def 查询证据(self, 主题: str = "", 类型: str = "", 限制: int = 50) -> list[dict[str, Any]]:
        条件表, 参数表 = [], []
        if 主题:
            条件表.append("主题=?")
            参数表.append(主题)
        if 类型:
            条件表.append("类型=?")
            参数表.append(类型)
        条件 = " AND ".join(条件表) if 条件表 else ""
        条件SQL = f"WHERE {条件}" if 条件 else ""
        结果表 = []
        连接 = self._连接()
        for 行 in 连接.execute(
                f"SELECT 证据id, 类型, 主题, 内容, 操作id, 调用者, 角色, 来源快照, "
                f"结果, 错误码, 时间, 哈希 FROM 证据 {条件SQL} ORDER BY 时间 DESC LIMIT ?",
                参数表 + [限制]):
            结果表.append({"证据id": 行[0], "类型": 行[1], "主题": 行[2],
                          "内容": json.loads(行[3]), "操作id": 行[4], "调用者": 行[5],
                          "角色": 行[6], "来源快照": 行[7], "结果": 行[8],
                          "错误码": 行[9], "时间": 行[10], "哈希": 行[11]})
        return 结果表
