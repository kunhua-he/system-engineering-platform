# -*- coding: utf-8 -*-
"""交付收尾：技能桥接脚本（stdin JSON 进，stdout JSON 出）。

契约：技能.交付收尾

固定工作流（顺序不可换：先门禁后落账，落账成功才释放资源）：
    校验入参 → 读协作状态 → 反馈门禁 → 证据指纹校验 → 写终态 → 释放资源 → 回执

只依赖标准库（受控执行 AST 审计只放行标准库，禁项目模块/支持库实现）。
落点与列语义与原 `MCP工具箱/协作状态.py 收口登记` 链路一致：
- 底座运行库 `工程缓存/运行数据/底座运行.db` 的 `协作状态` 域（主键 id = work_id）；
- 平台控制面 `工程缓存/平台控制面/权威状态.db` 的 `占用租约` 表（领域=文件按所有者匹配、领域=能力按任务匹配）；
- 释放能力占用时同步 `底座运行库` 的 `能力占用` 账本终态（账本失败只报同步错误，不改判定）。

失败一律 fail-closed：未反馈 / 证据指纹不匹配 / 未登记 时不写终态、不释放资源。
"""

import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

技能标识 = "技能.交付收尾"

开工id模式 = re.compile(r"^[0-9a-fA-F]{16}$")
排除片段表 = ("__pycache__", "工程缓存", "测试中心缓存", ".git",
          "完整性摘要.json", "项目证据", "临时文件")
清单列字段 = ("允许路径", "子任务列表")
测试标识前缀 = ("验收-", "验收_", "测试-", "test-")
测试标识能力前缀 = ("验收", "测试.", "test.")

领域_文件 = "文件"
领域_能力 = "能力"
租约状态_活跃 = "活跃"
租约状态_已释放 = "已释放"
账本域 = "能力占用"
账本状态_已释放 = "已释放"

错误_参数不合法 = "参数不合法"
错误_开工id非法 = "WORK_ID_INVALID"
错误_任务不存在 = "TASK_NOT_FOUND"
错误_未反馈阻断 = "FEEDBACK_BLOCKED"
错误_证据不匹配 = "EVIDENCE_MISMATCH"
错误_登记失败 = "REGISTRATION_FAILED"

运行库相对 = Path("工程缓存") / "运行数据" / "底座运行.db"
控制面库相对 = Path("工程缓存") / "平台控制面" / "权威状态.db"
反馈相对 = Path("开发文档") / "项目证据" / "MCP使用反馈.jsonl"
验证历史相对 = Path("开发文档") / "项目证据" / "验证历史.jsonl"

阅读上限行 = 200000
超时秒 = 10.0


# ── 基础工具（只用标准库） ────────────────────────────────────────

def _失败(错误码: str, 错误说明: str, **附加) -> dict:
    """统一失败回执：错误码 + 错误说明（不静默、不伪造成功）。"""
    值 = {"成功": False, "错误码": str(错误码), "错误说明": str(错误说明)}
    值.update(附加)
    return 值


def _文本参数(参数: dict, 名称: str, 默认: str = "") -> str:
    值 = 参数.get(名称)
    if 值 is None:
        return 默认
    return str(值).strip()


def _逻辑参数(参数: dict, 名称: str, 默认: bool = True) -> bool:
    值 = 参数.get(名称)
    if 值 is None:
        return 默认
    if isinstance(值, bool):
        return 值
    if isinstance(值, (int, float)):
        return bool(值)
    return str(值).strip().lower() in ("true", "1", "yes", "y", "是", "真", "释放")


def _解析路径(文本: str, 项目根: Path) -> Path:
    """相对路径按项目根解析（受控执行的工作目录），绝对路径原样。"""
    路径 = Path(str(文本)).expanduser()
    return 路径 if 路径.is_absolute() else (项目根 / 路径)


def _现在ISO() -> str:
    """与 `数据库连接支持库.SQLite数据库` 的 更新时间 口径一致（UTC 毫秒 ISO）。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _现在文本() -> str:
    """与 `能力占用` 账本的时间口径一致（本地时间到秒）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _目录内容摘要(目录: Path) -> str:
    """目录内容 sha256 前 16 位，排除缓存/证据目录段；目录不存在返回空串。

    与 `MCP工具箱/协作状态.py 计算代码指纹` 同口径（同一排除段表、同一摘要算法）。
    """
    根 = Path(目录)
    if not 根.is_dir():
        return ""
    摘要器 = hashlib.sha256()
    for 文件 in sorted(根.rglob("*")):
        if not 文件.is_file():
            continue
        相对 = 文件.relative_to(根)
        if any(段 in 排除片段表 for 段 in 相对.parts):
            continue
        摘要器.update(str(相对).encode("utf-8"))
        摘要器.update(文件.read_bytes())
    return 摘要器.hexdigest()[:16]


def _读JSONL(路径: Path) -> list[dict]:
    """读 JSONL 证据文件；缺失/坏行跳过，不抛错（门禁按「读不到即视为无记录」处理）。"""
    if not 路径.is_file():
        return []
    try:
        文本 = 路径.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    记录表: list[dict] = []
    for 行 in 文本.splitlines()[:阅读上限行]:
        行 = 行.strip()
        if not 行:
            continue
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if isinstance(记录, dict):
            记录表.append(记录)
    return 记录表


def _连接(库路径: Path) -> sqlite3.Connection:
    连接 = sqlite3.connect(str(库路径), timeout=超时秒)
    连接.row_factory = sqlite3.Row
    return 连接


def _测试标识命中(标识: str) -> str:
    return 标识 if any(str(标识).startswith(前缀) for 前缀 in 测试标识前缀) else ""


# ── 协作状态：读记录 / 写终态 ────────────────────────────────────

def _读协作状态(库路径: Path, 开工id: str) -> dict:
    """按主键读取协作状态记录：列值打底 + `载荷` JSON 覆盖，清单字段还原为列表。"""
    连接 = _连接(库路径)
    try:
        行 = 连接.execute(
            "SELECT * FROM 协作状态 WHERE id = ? OR work_id = ?", (开工id, 开工id)
        ).fetchone()
    finally:
        连接.close()
    if 行 is None:
        return {}
    列 = dict(行)
    载荷 = 列.get("载荷") or ""
    记录: dict = {}
    try:
        解析 = json.loads(载荷) if 载荷 else {}
        记录 = 解析 if isinstance(解析, dict) else {}
    except json.JSONDecodeError:
        记录 = {}
    for 键, 值 in 列.items():
        if 键 in ("载荷", "id") or 值 in (None, ""):
            continue
        if 记录.get(键) in (None, ""):
            记录[键] = 值
    for 键 in 清单列字段:
        值 = 记录.get(键)
        if isinstance(值, str):
            try:
                记录[键] = json.loads(值)
            except json.JSONDecodeError:
                continue
    return 记录


def _写协作状态终态(库路径: Path, 记录: dict, 五件套路径: str, 结论: str,
                收口时间: float) -> tuple[bool, str]:
    """生命周期=完成 + 五件套路径 + 收口结论 + 收口时间；表列与 `载荷` JSON 同步回写。"""
    视图 = dict(记录)
    视图["生命周期"] = "完成"
    视图["五件套路径"] = 五件套路径
    视图["收口结论"] = 结论
    视图["收口时间"] = 收口时间
    视图["状态"] = "完成"
    for 键 in 清单列字段:
        if isinstance(视图.get(键), (list, dict)):
            视图[键] = json.dumps(视图[键], ensure_ascii=False)
    更新时间 = _现在ISO()
    try:
        载荷 = json.dumps(视图, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as 错误:
        说明 = f"记录无法编码为 JSON：{错误}"
        return False, 说明
    连接 = _连接(库路径)
    try:
        with 连接:
            游标 = 连接.execute(
                "UPDATE 协作状态 SET 生命周期 = ?, 收口结论 = ?, 状态 = ?, "
                "更新时间 = ?, 载荷 = ? WHERE id = ?",
                ("完成", 结论, "完成", 更新时间, 载荷, str(记录.get("work_id") or "")),
            )
            if 游标.rowcount <= 0:
                return False, "协作状态终态未写入（主键未命中）"
    except sqlite3.Error as 错误:
        return False, f"运行库写入失败，已回滚：{错误}"
    finally:
        连接.close()
    return True, ""


# ── 资源释放：占用租约（文件/能力） + 能力占用账本终态 ──────────────

def _释放租约(连接: sqlite3.Connection, 领域: str, 匹配列: str, 开工id: str,
           证据: str) -> dict:
    """释放某领域下该开工id 持有的全部活跃租约；逐条消费 UPDATE 的真实返回值。"""
    行列表 = 连接.execute(
        f"SELECT 租约id FROM 占用租约 WHERE 状态 = ? AND 领域 = ? AND {匹配列} = ?",
        (租约状态_活跃, 领域, 开工id),
    ).fetchall()
    成功表: list[str] = []
    失败表: list[str] = []
    for 行 in 行列表:
        租约id = str(行["租约id"] if isinstance(行, sqlite3.Row) else 行[0])
        游标 = 连接.execute(
            "UPDATE 占用租约 SET 状态 = ?, 释放证据 = ? WHERE 租约id = ? AND 状态 = ?",
            (租约状态_已释放, 证据, 租约id, 租约状态_活跃),
        )
        (成功表 if 游标.rowcount > 0 else 失败表).append(租约id)
    return {"成功": not 失败表, "释放数量": len(成功表), "租约id": 成功表, "失败": 失败表}


def _标账本终态(控制面连接: sqlite3.Connection, 运行库路径: Path, 租约id: str,
            证据: str) -> str:
    """把某能力租约对应的能力占用账本行标为已释放；返回失败说明（成功为 ""）。"""
    行 = 控制面连接.execute(
        "SELECT 能力id, 所有者, 任务 FROM 占用租约 WHERE 租约id = ?", (租约id,)
    ).fetchone()
    if 行 is None:
        return ""
    能力id = str(行["能力id"] or "")
    if not 能力id:
        return ""
    if _测试标识命中(能力id) or any(能力id.startswith(前缀) for 前缀 in 测试标识能力前缀):
        return f"{租约id}: 能力id 属测试标识，不写账本"
    现在 = _现在文本()
    记录 = {"能力id": 能力id, "提供包id": str(行["所有者"] or ""), "开工id": str(行["任务"] or ""),
          "占用时间": 现在, "状态": 账本状态_已释放, "更新时间": 现在,
          "释放时间": 现在, "释放证据": 证据}
    载荷 = json.dumps(记录, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    连接 = _连接(运行库路径)
    try:
        with 连接:
            连接.execute(
                "INSERT INTO 能力占用 (id, 创建时间, 更新时间, 状态, 载荷, 能力id, 提供包id, 开工id, 占用时间) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET 更新时间 = excluded.更新时间, 状态 = excluded.状态, "
                "载荷 = excluded.载荷, 能力id = excluded.能力id, 提供包id = excluded.提供包id, "
                "开工id = excluded.开工id, 占用时间 = excluded.占用时间",
                (能力id, 现在, 现在, 账本状态_已释放, 载荷, 能力id,
                 str(行["所有者"] or ""), str(行["任务"] or ""), 现在),
            )
    except sqlite3.Error as 错误:
        return f"{租约id}: 账本落库失败：{错误}"
    finally:
        连接.close()
    return ""


def _释放资源(控制面库路径: Path, 运行库路径: Path, 开工id: str, 证据: str) -> dict:
    连接 = _连接(控制面库路径)
    try:
        with 连接:
            文件租约 = _释放租约(连接, 领域_文件, "所有者", 开工id, 证据)
            能力占用 = _释放租约(连接, 领域_能力, "任务", 开工id, 证据)
            账本失败: list[str] = []
            for 租约id in 能力占用["租约id"]:
                说明 = _标账本终态(连接, 运行库路径, 租约id, 证据)
                if 说明:
                    账本失败.append(说明)
    except sqlite3.Error as 错误:
        return {"成功": False, "错误码": 错误_登记失败,
                "错误说明": f"占用租约释放失败，已回滚：{错误}"}
    finally:
        连接.close()
    值 = {"文件租约": 文件租约, "能力占用": 能力占用}
    if 账本失败:
        值["同步错误"] = "占用账本未更新：" + "；".join(账本失败)
    return 值


# ── 主流程 ──────────────────────────────────────────────────────

def 主流程(参数: dict) -> dict:
    开工id原值 = _文本参数(参数, "开工id")
    五件套路径 = _文本参数(参数, "五件套路径")
    结论 = _文本参数(参数, "结论")
    if not 开工id原值 or not 五件套路径 or not 结论:
        return _失败(错误_参数不合法, "开工id、五件套路径、结论 均为必填")
    if not 开工id模式.fullmatch(开工id原值):
        return _失败(错误_开工id非法, "开工id 必须为 16 位十六进制", 开工id=开工id原值)
    开工id = 开工id原值.lower()
    if _测试标识命中(开工id):
        return _失败(错误_登记失败, f"正式运行库不得写入验收/测试标识记录：{开工id}", 开工id=开工id)

    项目根 = Path(_文本参数(参数, "项目根目录") or ".").expanduser().resolve()
    运行库路径 = _解析路径(_文本参数(参数, "运行库路径") or str(运行库相对), 项目根)
    控制面库路径 = _解析路径(_文本参数(参数, "控制面库路径") or str(控制面库相对), 项目根)
    反馈文件 = _解析路径(_文本参数(参数, "反馈文件") or str(反馈相对), 项目根)
    验证历史文件 = _解析路径(_文本参数(参数, "验证历史文件") or str(验证历史相对), 项目根)
    释放开关 = _逻辑参数(参数, "释放资源", True)

    if not 运行库路径.is_file():
        return _失败(错误_参数不合法, f"底座运行库不存在：{运行库路径}", 开工id=开工id)

    # 步骤 2：读协作状态记录
    try:
        记录 = _读协作状态(运行库路径, 开工id)
    except sqlite3.Error as 错误:
        return _失败(错误_登记失败, f"协作状态读取失败：{错误}", 开工id=开工id)
    if not 记录:
        return _失败(错误_任务不存在, f"{开工id} 未登记，无法收口",
                    开工id=开工id, 阻断标记=["未登记"])

    # 步骤 3：反馈门禁（未反馈一律阻断，不写终态）
    已反馈 = any(str(项.get("开工id") or "").strip().lower() == 开工id
               for 项 in _读JSONL(反馈文件))
    if not 已反馈:
        return _失败(错误_未反馈阻断, "未提交 MCP 反馈，阻断收口",
                    开工id=开工id, 阻断标记=["未反馈"])

    # 步骤 4：证据指纹校验（存证指纹与当前代码指纹比对）
    worktree路径 = str(记录.get("worktree路径") or "")
    当前指纹 = _目录内容摘要(_解析路径(worktree路径, 项目根)) if worktree路径 else ""
    证据 = [项 for 项 in _读JSONL(验证历史文件)
          if str(项.get("开工id") or "").strip().lower() == 开工id]
    证据指纹 = ""
    if 证据:
        最后 = 证据[-1]
        证据指纹 = str(最后.get("指纹") or 最后.get("工作区指纹") or "")
        if 证据指纹 != 当前指纹:
            return _失败(错误_证据不匹配, "验证证据指纹与当前代码指纹不匹配，阻断收口",
                        开工id=开工id, 阻断标记=["证据指纹不匹配"],
                        证据指纹=证据指纹, 当前指纹=当前指纹)
    指纹判定 = "匹配" if 证据 else "无证据放行"

    # 步骤 5：写终态
    收口时间 = time.time()
    成功, 说明 = _写协作状态终态(运行库路径, 记录, 五件套路径, 结论, 收口时间)
    if not 成功:
        return _失败(错误_登记失败, f"{开工id} 收口落库失败：{说明}", 开工id=开工id)

    # 步骤 6：释放资源（写终态成功后才释放；同旧链路：收口即不留残锁）
    if 释放开关:
        if not 控制面库路径.is_file():
            资源释放 = {"成功": False, "跳过": f"控制面库不存在，未释放占用租约：{控制面库路径}"}
        else:
            资源释放 = _释放资源(控制面库路径, 运行库路径, 开工id, f"收口：{结论}")
    else:
        资源释放 = {"成功": True, "跳过": "释放资源=false，未释放占用租约"}

    # 步骤 7：回执
    return {
        "技能标识": 技能标识,
        "开工id": 开工id,
        "生命周期": "完成",
        "五件套路径": 五件套路径,
        "收口结论": 结论,
        "代码指纹": 当前指纹,
        "反馈门禁": "通过",
        "证据指纹": 指纹判定,
        "证据条数": len(证据),
        "收口时间": 收口时间,
        "资源释放": 资源释放,
    }


def 主函数() -> int:
    原文 = sys.stdin.read()
    try:
        载荷 = json.loads(原文) if 原文.strip() else {}
    except json.JSONDecodeError as 错误:
        print(json.dumps({"成功": False, "错误码": "参数不合法",
                          "错误说明": f"stdin 不是合法 JSON: {错误}"}, ensure_ascii=False))
        return 0
    参数 = 载荷.get("参数") or {}
    if not isinstance(参数, dict):
        print(json.dumps({"成功": False, "错误码": "参数不合法",
                          "错误说明": "参数必须是 JSON 对象"}, ensure_ascii=False))
        return 0
    try:
        值 = 主流程(参数)
    except Exception as 错误:  # 失败要明确，不吞
        print(json.dumps({"成功": False, "错误码": "脚本执行失败",
                          "错误说明": f"{type(错误).__name__}: {错误}"}, ensure_ascii=False))
        return 0
    if isinstance(值, dict) and 值.get("成功") is False:
        print(json.dumps(值, ensure_ascii=False))
        return 0
    print(json.dumps({"成功": True, "值": 值}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
