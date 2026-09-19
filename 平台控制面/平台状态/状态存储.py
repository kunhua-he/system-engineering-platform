"""平台控制面权威状态：复用 运行核心.权威状态 的存储机制（子类化）。

六个权威服务（需求登记/能力目录/包仓库/策略中心/发布管理/证据账本）共用
本存储——每类事实只有一个权威写入口，禁止各自维护 JSON 真相。
子类化复用：连接管理、WAL、迁移器（BEGIN IMMEDIATE 串行化、失败证据、
假升级补列）、栅栏令牌与 CAS 全部继承；本类只扩展 1.3.0 平台表。

1.5.0 增量：`能力条目(契约指纹)` 部分唯一索引（`索引_能力条目契约指纹`）。
为什么必须落到数据库层：`平台控制面/能力目录/服务.py` 的 `登记能力` 是
「读契约指纹 → 判重 → 写记录」，读判写之间没有闸门，而同包的
`单文件互斥存储` 只管单 JSON 文件存储（文件租约/消费者契约），管不到这条
sqlite 写入。修复前实测（8 路并发登记同一指纹的 8 个不同能力 id）：8/8 全部
落库，跨进程 6 路并发也 6/6 落库——「相同契约指纹阻断重复实现」这道门禁
在并发下等于不存在。应用层判重保留（顺序调用的失败文案逐字不变），
数据库唯一索引做原子边界：只放行一条，另一条由 `写入记录或唯一冲突`
收成返回值回到同一条既有文案。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from typing import Any

from 运行核心.权威状态 import 权威状态, 版本元组
from 公共契约.基础类型.逻辑类型 import 真, 假

# 能力条目契约指纹唯一索引（1.5.0 结构事实）：迁移与结构校验共用同一常量，禁止两处各写一遍。
索引_能力条目契约指纹 = "索引_能力条目契约指纹"
# 索引只约束「非空契约指纹」：空指纹（如发布门禁直接写入的 `契约指纹=''` 行）
# 不在「相同契约指纹阻断重复实现」的语义内，多条空白行仍合法。
能力条目指纹索引条件 = "契约指纹 IS NOT NULL AND 契约指纹 <> ''"

# ---- 标识符白名单（P2-10①，2026-09-18 硬化）----
# 为什么需要：本类的 `表`/`列名`/`条件` 是**拼进 SQL 文本**的位置（值已参数化，这些
# 不是值），而 `读取记录`/`查询记录`/`写入记录` 同时是公开能力——`表`/`主键列`/`条件`
# 由调用方（Agent、网关、门禁）给，不是全部来自代码常量。白名单是纵深防御的最后一层。
# 六服务与门禁的全部调用点现场核对过：传的都是代码常量（条件字面量只有标识符/占位符/
# 比较与逻辑运算符/括号/逗号），因此白名单不会拦住任何既有调用。
标识符白名单 = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_]+$")
# 裸条件（WHERE 之后）允许的词法：字符串字面量 / 参数占位符 / 标识符 / 数字 /
# 比较与逻辑运算符 / 括号 / 逗号 / 空白。分号、注释符（-- /*）、引号拼接、
# 反斜杠一律不在允许集内——它们进不了 SQL。
条件片段词法 = re.compile(
    r"\s*(?:'(?:[^']|'')*'|\?|[A-Za-z\u4e00-\u9fa5_][A-Za-z0-9_\u4e00-\u9fa5]*"
    r"|[0-9]+(?:\.[0-9]+)?|<>|!=|<=|>=|=|<|>|\(|\)|,)\s*")
# 裸条件里禁止出现的结构关键字（按大写比对，大小写不敏感）：词法上它们是标识符，
# 语义上绝不属于 WHERE 条件（DDL/DML/子查询注入骨架），逐个拒绝做纵深防御。
条件禁止关键字 = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE", "REPLACE", "DROP", "ALTER", "CREATE",
    "UNION", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "TRIGGER", "EXEC", "EXECUTE",
    "WITH", "RECURSIVE", "RETURNING", "INTO", "TABLE", "INDEX", "VIEW", "TEMP",
    "TEMPORARY", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "REINDEX", "ANALYZE",
    "LOAD_EXTENSION", "GRANT", "REVOKE", "MASTER", "SQLITE_MASTER",
})


class 标识符不合法(sqlite3.OperationalError):
    """表名/列名/条件片段不在白名单内（P2-10① 纵深防御的拒答类型）。

    为什么继承 `sqlite3.OperationalError`：这些参数是**拼进 SQL 的文本**，被拒等价于
    「这条语句无法执行」——与 sqlite 自己的 `no such table` 同一错误类。于是
    `平台控制面/平台状态/实现/能力入口.py`（只捕 `sqlite3.Error`）仍能把拒答收成既有的
    `读取记录失败`/`查询记录失败`/`写入记录失败`（网关 → 400 调用方输入问题），
    不会退化成 500 内部错误；也不需要新增任何错误码。

    机器判据用**异常类型**（`isinstance`），禁止解析本类的文案。
    """


def _校验标识符(值: Any, 用途: str) -> str:
    """表名/列名白名单校验（纵深防御）：不合法直接拒答，绝不拼进 SQL。"""
    if not isinstance(值, str) or not 标识符白名单.match(值):
        raise 标识符不合法(f"{用途}不在标识符白名单内: {值!r}")
    return 值


def _校验条件片段(条件: Any) -> str:
    """裸条件词法校验（纵深防御）：逐段吃掉允许的词法，出现禁止关键字即拒答。"""
    if 条件 is None or 条件 == "":
        return ""
    if not isinstance(条件, str):
        raise 标识符不合法(f"条件必须是文本: {条件!r}")
    位置 = 0
    长度 = len(条件)
    while 位置 < 长度:
        匹配 = 条件片段词法.match(条件, 位置)
        if 匹配 is None or 匹配.end() == 位置:
            raise 标识符不合法(f"条件片段含未允许的词法（位置 {位置}）: {条件!r}")
        词 = 匹配.group(0).strip().upper()
        if 词 in 条件禁止关键字:
            raise 标识符不合法(f"条件片段含禁止关键字 {词}: {条件!r}")
        位置 = 匹配.end()
    return 条件


def _校验写入参数(表: str, 记录: dict[str, Any], 主键: str = "", 唯一列: str = "") -> None:
    """写入路径的标识符白名单：表名 / 主键 / 唯一列 / 记录里的每个列名。"""
    _校验标识符(表, "表名")
    if 主键:
        _校验标识符(主键, "主键")
    if 唯一列:
        _校验标识符(唯一列, "唯一列")
    for 字段 in 记录:
        _校验标识符(字段, "列名")


def _列名表(连接, 表: str) -> list[str]:
    """取表的列名清单（每次调用执行一次 `PRAGMA table_info`，P2-10②）。

    前置条件：调用方已过 `_校验标识符(表, "表名")`（本函数只拼已白名单化的表名）。
    """
    return [描述[1] for 描述 in 连接.execute(f"PRAGMA table_info({表})").fetchall()]


def _拼UPSERT(表: str, 记录: dict[str, Any], 主键: str, *,
              主键缺失时替换: bool = True) -> str:
    """单事务写语句（`写入记录` 与 `写入记录或唯一冲突` 共用，禁止各写一套）。

    记录带主键列 → `INSERT … ON CONFLICT(主键) DO UPDATE SET 仅传入列=excluded.列`
    （P2-10③：不先读整行、不整行覆盖，未传入的列保持原值；只带主键列时 DO NOTHING
    即「无字段可更新」的幂等空操作）。

    记录不带主键列（如 `需求登记.登记需求` 只传业务列、主键走默认 "id"，主键值在业务列里）
    → 按 `主键缺失时替换` 走老语义：
    - True（`写入记录`）：`INSERT OR REPLACE`，与硬化前逐字一致——这些调用点传的是整行，
      没有「同主键不同字段并发合并」可言；
    - False（`写入记录或唯一冲突`）：纯 `INSERT`，绝不 REPLACE（REPLACE 会删掉占着
      `唯一列` 的那一行，与本方法「谁该消失不由存储层决定」的契约相反）。
    """
    字段表 = list(记录)
    占位符 = ", ".join(["?"] * len(字段表))
    列名 = ", ".join(字段表)
    语句 = f"INSERT INTO {表}({列名}) VALUES({占位符})"
    更新列 = [字段 for 字段 in 字段表 if 字段 != 主键]
    if 主键 in 记录:
        if 更新列:
            语句 += (f" ON CONFLICT({主键}) DO UPDATE SET "
                    + ", ".join(f"{字段}=excluded.{字段}" for 字段 in 更新列))
        else:
            语句 += f" ON CONFLICT({主键}) DO NOTHING"
        return 语句
    if 主键缺失时替换:
        return f"INSERT OR REPLACE INTO {表}({列名}) VALUES({占位符})"
    return 语句


class 平台状态(权威状态):
    """平台控制面状态（结构 1.5.0：六服务表 + 信任 + 激活指针 + 核心快照 + 指纹唯一索引）。"""

    目标版本 = "1.5.0"
    迁移序列表 = 权威状态.迁移序列表 + [
        ("1.3.0", "_迁移到130"), ("1.4.0", "_迁移到140"), ("1.5.0", "_迁移到150")]
    校验规则表 = {
        **权威状态.校验规则表,
        "1.3.0": {"表": ["证据", "需求", "工作包", "能力条目", "占用租约", "制品",
                          "信任", "策略", "发布", "激活指针", "核心快照"]},
        "1.4.0": {"表": ["能力反馈"], "列": [("能力反馈", "去重键"), ("能力反馈", "状态")]},
        "1.5.0": {"索引": [("能力条目", 索引_能力条目契约指纹)]},
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

    def _迁移到150(self, 连接) -> None:
        """1.5.0：`能力条目(契约指纹)` 部分唯一索引 —— 并发登记同指纹的原子防线。

        修复前实测：`登记能力` 读指纹 → 判重 → 写记录，读判写之间没有闸门，
        同指纹的两个不同能力 id 会双双落库（8 路并发 8/8 落库），此后
        「重复实现门禁」按指纹只查得到一条，等于漏判。

        迁移方式（**兼容旧库、幂等、单事务**，无需重建数据库）：
        1. **先去重再建索引**：旧库里可能已经躺着修复前双落的同指纹行（同指纹多
           id 按 `登记能力` 的设计判据不允许：`已有[0]["能力id"] != 能力id` 即阻断）。
           逐指纹保留 `rowid` 最小的一行（= 最先登记那条，与顺序调用的判据一致），
           其余行的 `契约指纹` 清成 `''`（等于「该行未声明契约指纹」）而**不删行**：
           能力条目仍在目录里可查，审计不丢；同一事务内往 `证据` 追加一条迁移证据，
           记下每个指纹保留了谁、清了谁。
        2. **建部分唯一索引**：只约束非空契约指纹，空指纹行（如发布门禁直接写入的
           `契约指纹=''` 行）不受影响，仍可多条共存。
        3. 索引建不出来（极端：库内还有本函数修不掉的重复）即整体回滚，
           结构版本不前进，不会留下「版本已升、防线没建」的半迁移状态。
        """
        重复指纹表 = [
            行[0] for 行 in 连接.execute(
                "SELECT 契约指纹 FROM 能力条目 "
                f"WHERE {能力条目指纹索引条件} GROUP BY 契约指纹 HAVING COUNT(*) > 1")]
        清理记录: list[dict[str, str]] = []
        for 指纹 in 重复指纹表:
            已有行 = 连接.execute(
                "SELECT 能力id FROM 能力条目 WHERE 契约指纹=? ORDER BY rowid",
                (指纹,)).fetchall()
            保留 = str(已有行[0][0])
            for (能力id,) in 已有行[1:]:
                连接.execute("UPDATE 能力条目 SET 契约指纹='' WHERE 能力id=?", (能力id,))
                清理记录.append({"契约指纹": 指纹, "保留能力id": 保留,
                                 "清空能力id": str(能力id)})
        if 清理记录:
            self._写迁移证据(连接, 清理记录)
        连接.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {索引_能力条目契约指纹} "
            f"ON 能力条目(契约指纹) WHERE {能力条目指纹索引条件}")

    def _写迁移证据(self, 连接, 清理记录: list[dict[str, str]]) -> None:
        """把 1.5.0 去重动作写进证据账本（与迁移同一事务，回滚则证据也不留）。"""
        内容 = {"迁移": "1.5.0", "动作": "同契约指纹去重",
                "口径": "同指纹保留最先登记的一条，其余行清空契约指纹（不删行）",
                "条数": len(清理记录), "清理": 清理记录}
        正文 = json.dumps(内容, ensure_ascii=False)
        连接.execute(
            "INSERT INTO 证据(证据id, 类型, 主题, 内容, 操作id, 调用者, 角色, "
            "来源快照, 结果, 错误码, 时间, 哈希) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex[:20], "结构迁移", "能力条目.契约指纹唯一索引", 正文,
             "", "平台状态", "平台维护者", "", "去重完成", "",
             time.strftime("%Y-%m-%d %H:%M:%S"),
             hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]))

    # ---- 结构校验（基类只认表/列，本类补索引） ----
    def _校验版本结构(self, 连接, 版本: str) -> None:
        """结构校验：基类（表/列/完整性）+ 本类 1.5.0 起新增的**索引**规则。

        为什么索引必须进校验：`运行核心.权威状态._校验版本结构` 只认 表/列，
        「假升级」（元信息版本已是目标版本但结构没建全）的判定因此看不见
        「唯一索引没建出来」的旧库——而那正是并发登记的唯一防线，看不见就会
        静默放行双落。索引与列一样是结构事实，必须校验。
        """
        super()._校验版本结构(连接, 版本)
        目标元组 = 版本元组(版本)
        for 规则版本 in sorted(self.校验规则表, key=版本元组):
            if 版本元组(规则版本) > 目标元组:
                continue
            for 表, 索引名 in self.校验规则表[规则版本].get("索引", []):
                self._校验索引(连接, 表, 索引名)

    def _校验索引(self, 连接, 表: str, 索引名: str) -> None:
        """必需索引存在且确实建在该表上；缺失即抛错（与 `_校验表存在` 同口径）。"""
        行 = 连接.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?",
            (索引名,)).fetchone()
        if 行 is None:
            raise RuntimeError(f"缺少必需索引: {索引名}")
        if str(行[0]) != 表:
            raise RuntimeError(f"索引 {索引名} 建在 {行[0]}，结构要求建在 {表}")

    # ---- 六服务通用读写（唯一写入口） ----
    def 写入记录(self, 表: str, 记录: dict[str, Any], 主键: str = "id") -> None:
        """按主键写入记录；已存在时**只更新本次传入的字段**（不读旧行、不整行覆盖）。

        单事务 UPSERT（P2-10③）：原先「先 SELECT 整行 → 合并 → INSERT OR REPLACE」跨
        两个事务，并发写同一主键的不同字段会互相覆盖（丢失更新窗口），且 REPLACE 是
        DELETE+INSERT（触发级联、换 rowid、清未传字段）。现改为
        `INSERT … ON CONFLICT(主键) DO UPDATE SET 仅传入列=excluded.列`：不先读、
        不整行替换，未传入的列原样保留，判冲突与写入在同一事务内原子完成。

        部分更新（如 生成装配计划 只写 装配计划 字段）不得清空同一记录的其他字段
        （需求确认状态等）——UPSERT 只写传入列，正是这条口径。
        表名/列名/主键走标识符白名单（P2-10①）。
        """
        _校验写入参数(表, 记录, 主键)
        字段表 = list(记录)
        连接 = self._连接()
        with 连接:
            连接.execute(_拼UPSERT(表, 记录, 主键),
                        [记录[字段] for 字段 in 字段表])

    def 写入记录或唯一冲突(self, 表: str, 记录: dict[str, Any], 主键: str = "id",
                          唯一列: str = "") -> tuple[bool, str]:
        """按主键合并写入；`唯一列` 已被**别的行**占用时不覆盖对方，返回 (False, 占用者)。

        与 `写入记录` 只差冲突策略：`INSERT OR REPLACE`（SQLite REPLACE 语义）在任何
        唯一索引冲突时都会**先删掉对方那行**再插入自己（本地实测：A 占着指纹 F，
        写 B 之后库里只剩 B），并发登记同一契约指纹的第二个能力 id 因此会把先落库那条
        静默删掉、自己还报成功——比双双落库更糟。本方法改用
        `ON CONFLICT(主键) DO UPDATE`：只解决主键冲突（合并更新语义与 `写入记录` 一致），
        别的主键占着 `唯一列` 时原样抛 `IntegrityError`，由本方法收成返回值——
        谁该消失不由存储层替调用方决定。

        P2-10③：与 `写入记录` 共用 `_拼UPSERT`（单事务 UPSERT，只更新本次传入的列），
        不再「先 SELECT 整行合并再写」——并发写同一主键的不同字段不再有丢失更新窗口。

        返回：`(True, "")` 写入成功；`(False, 占用者主键值)` 唯一列被占用，调用方按既有
        错误码/文案回话（占用者定位不到时**不吞异常**，原样抛出，绝不假装成功）。
        """
        _校验写入参数(表, 记录, 主键, 唯一列)
        字段表 = list(记录)
        语句 = _拼UPSERT(表, 记录, 主键, 主键缺失时替换=假)
        连接 = self._连接()
        try:
            with 连接:
                连接.execute(语句, [记录[字段] for 字段 in 字段表])
        except sqlite3.IntegrityError:
            if not 唯一列:
                raise
            占用者 = self._唯一列占用者(连接, 表, 主键, 唯一列, 记录)
            if not 占用者:
                raise
            return 假, 占用者
        return 真, ""

    def _唯一列占用者(self, 连接, 表: str, 主键: str, 唯一列: str,
                    记录: dict[str, Any]) -> str:
        """定位占着 `唯一列` 的那一行（主键不同于本次写入行）；找不到返回空串。"""
        主键值 = 记录.get(主键)
        行 = 连接.execute(
            f"SELECT {主键} FROM {表} WHERE {唯一列}=? AND {主键}<>?",
            (记录.get(唯一列), "" if 主键值 is None else str(主键值))).fetchone()
        return str(行[0]) if 行 else ""

    def 原子插入(self, 表: str, 记录: dict[str, Any]) -> bool:
        """INSERT OR IGNORE：唯一约束冲突返回 False（并发互斥的原子防线）。

        表名/列名走标识符白名单（P2-10①）。
        """
        _校验写入参数(表, 记录)
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
        """读取一条记录（列名按实际表结构取，不依赖位置索引）。

        P2-10①：表名/主键列走标识符白名单；P2-10②：`PRAGMA table_info` 每次调用
        只执行一次（原先在结果行循环里每行执行一次，纯浪费）。
        """
        _校验标识符(表, "表名")
        _校验标识符(主键列, "主键列")
        连接 = self._连接()
        列名 = _列名表(连接, 表)
        行 = 连接.execute(f"SELECT * FROM {表} WHERE {主键列}=?", (主键值,)).fetchone()
        if 行 is None:
            return None
        return dict(zip(列名, 行))

    def 查询记录(self, 表: str, 条件: str = "", 参数: tuple = ()) -> list[dict[str, Any]]:
        """按条件查询记录（列名按实际表结构取，不依赖位置索引）。

        P2-10①：表名与条件片段走白名单/词法校验；P2-10②：`PRAGMA table_info`
        提到结果行循环外，每次查询只执行一次。
        """
        _校验标识符(表, "表名")
        _校验条件片段(条件)
        连接 = self._连接()
        列名 = _列名表(连接, 表)
        条件SQL = f"WHERE {条件}" if 条件 else ""
        结果表 = []
        for 行 in 连接.execute(f"SELECT * FROM {表} {条件SQL}", 参数):
            结果表.append(dict(zip(列名, 行)))
        return 结果表

    def 条件更新(self, 表: str, 更新: dict[str, Any], 条件SQL: str, 参数: tuple) -> bool:
        """按条件更新（表名/列名/条件片段走标识符白名单与条件词法，P2-10①）。"""
        _校验写入参数(表, 更新)
        _校验条件片段(条件SQL)
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
        # #166（2026-09-20）：本文件 :20 已 `import hashlib`，此处原为弯绕写法，
        # 绕开静态检查、也让「谁用了 hashlib」的检索失效。直接用模块名。
        哈希 = hashlib.sha256(正文.encode("utf-8")).hexdigest()[:16]
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
