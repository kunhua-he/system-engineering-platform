# -*- coding: utf-8 -*-
"""交付收尾：技能桥接脚本（stdin JSON 进，stdout JSON 出）。

契约：技能.交付收尾

固定工作流（顺序不可换：先门禁后落账，落账成功才释放资源）：
    校验入参 → 读协作状态 → 反馈门禁 → 证据指纹校验 → 写终态 → 释放资源 → 回执

调用腿唯一：平台注入的合成模块 `技能底座能力.调用底座能力(能力id, 参数)` → 唯一网关
`POST http://127.0.0.1:40007/网关/调用`（操作=调用能力）。脚本**不自开数据库、不 import 任何
项目模块/支持库实现、不直接拼 SQL**（平台第 7.4 / 7.8 / 8.2 条：能力调用只走唯一网关）。

四个白名单能力（调用方必须传 `可调能力白名单`，缺项即 `能力不在白名单`，fail-closed）：
- `数据库连接支持库.SQLite数据库.查询运行态`：读底座运行库 `协作状态` 域（主键 work_id）；
- `数据库连接支持库.SQLite数据库.写入运行态`：写协作状态终态 + `能力占用` 账本终态
  （唯一 SQLite 写入口的正常写入方向，不再绕过它直改表）；
- `平台控制面.平台状态.查询记录`：读平台控制面权威状态库 `占用租约` 表（只读）；
- `平台控制面.能力目录.释放文件租约`：唯一释放口径（幂等 + 释放原因 + 留改动流水）。

落点不再由参数决定：两份库一律由底座能力自己按平台唯一解析器定位
（`工程缓存/运行数据/底座运行.db`、`工程缓存/平台控制面/权威状态.db`）。库位置是平台事实；
`运行库路径` / `控制面库路径` 两个选填参数**只作隔离用**（技能验证夹具 / 临时库试跑），
不传即走平台默认解析器，生产调用不传（哲学 1.2「同一事实不得两处可改」）。

失败一律 fail-closed：未反馈 / 证据指纹不匹配 / 未登记 时不写终态、不释放资源。
"""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from 技能底座能力 import 调用底座能力

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
账本状态_已释放 = "已释放"

# ── 底座原子能力（唯一调用腿；白名单由调用方冻结进注入模块） ──────────────
能力_查询运行态 = "数据库连接支持库.SQLite数据库.查询运行态"
能力_写入运行态 = "数据库连接支持库.SQLite数据库.写入运行态"
能力_查询记录 = "平台控制面.平台状态.查询记录"
能力_释放文件租约 = "平台控制面.能力目录.释放文件租约"
必须授权能力 = (能力_查询运行态, 能力_写入运行态, 能力_查询记录, 能力_释放文件租约)

运行库域_协作状态 = "协作状态"
运行库域_能力占用 = "能力占用"
控制面表_占用租约 = "占用租约"

# 对外错误码一律中文（决策 0003「对外错误只走中文」）：
# 「开工id无效」与 平台控制面/能力反馈/开发反馈服务.py 的 稳定错误码映射 同词表，
# 由该表映射为平台稳定码 WORK_ID_INVALID；本技能不自造第二套码。
错误_参数不合法 = "参数不合法"
错误_开工id非法 = "开工id无效"
错误_任务不存在 = "任务不存在"
错误_未反馈阻断 = "未反馈阻断"
错误_证据不匹配 = "证据不匹配"
错误_登记失败 = "登记失败"

反馈相对 = Path("开发文档") / "项目证据" / "MCP使用反馈.jsonl"
验证历史相对 = Path("开发文档") / "项目证据" / "验证历史.jsonl"

阅读上限行 = 200000
能力超时秒 = 30.0


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


def _现在文本() -> str:
    """与 `能力占用` 账本的时间口径一致（本地时间到秒）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _目录内容摘要(目录: Path) -> str:
    """目录内容 sha256 前 16 位，排除缓存/证据目录段；目录不存在返回空串。

    与 `计算代码指纹` 同口径（同一排除段表、同一摘要算法）。
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


def _测试标识命中(标识: str) -> str:
    return 标识 if any(str(标识).startswith(前缀) for 前缀 in 测试标识前缀) else ""


def _能力值(结果: dict, 失败说明: str) -> tuple[dict | None, str]:
    """消费合成模块的统一回执：成功取 `值`，失败回能力自报的中文错误码与说明。"""
    if not isinstance(结果, dict):
        return None, f"{失败说明}：调用回执不是对象"
    if bool(结果.get("成功")):
        值 = 结果.get("值")
        return (值 if isinstance(值, dict) else {}), ""
    码 = str(结果.get("错误码") or "能力调用失败")
    说明 = str(结果.get("错误说明") or "")
    return None, f"{失败说明}：{码}{('（' + 说明 + '）') if 说明 else ''}"


# ── 协作状态：读记录 / 写终态（全部经唯一网关） ─────────────────────

def _读协作状态(开工id: str, 库路径: str = "") -> tuple[dict, str]:
    """经 查询运行态 读协作状态域：列值打底 + `载荷` JSON 覆盖，清单字段还原为列表。"""
    参数: dict = {"域": 运行库域_协作状态, "条件": {"work_id": 开工id}, "限制": 10,
               "超时秒": 能力超时秒}
    if 库路径:
        参数["数据库路径"] = 库路径
    结果 = 调用底座能力(能力_查询运行态, 参数, 超时秒=能力超时秒)
    值, 问题 = _能力值(结果, "协作状态读取失败")
    if 值 is None:
        return {}, 问题
    行列表 = 值.get("行列表")
    if not isinstance(行列表, list) or not 行列表:
        return {}, ""
    列 = dict(行列表[0]) if isinstance(行列表[0], dict) else {}
    载荷 = 列.get("载荷") or ""
    记录: dict = {}
    if 载荷:
        try:
            解析 = json.loads(载荷)
            记录 = 解析 if isinstance(解析, dict) else {}
        except json.JSONDecodeError:
            记录 = {}
    for 键, 值项 in 列.items():
        if 键 in ("载荷", "id") or 值项 in (None, ""):
            continue
        if 记录.get(键) in (None, ""):
            记录[键] = 值项
    for 键 in 清单列字段:
        值项 = 记录.get(键)
        if isinstance(值项, str):
            try:
                记录[键] = json.loads(值项)
            except json.JSONDecodeError:
                continue
    return 记录, ""


def _写协作状态终态(开工id: str, 记录: dict, 五件套路径: str, 结论: str,
                收口时间: float, 库路径: str = "") -> tuple[bool, str]:
    """生命周期=完成 + 五件套路径 + 收口结论 + 收口时间；表列与 `载荷` JSON 同步回写。

    走 `写入运行态`（唯一 SQLite 写入口）的正常写入方向：重复 id 采用更新语义，
    未传入的列原样保留，不整行覆盖（与旧直改 SQL 的合并语义一致）。
    """
    视图 = dict(记录)
    视图["生命周期"] = "完成"
    视图["五件套路径"] = 五件套路径
    视图["收口结论"] = 结论
    视图["收口时间"] = 收口时间
    视图["状态"] = "完成"
    for 键 in 清单列字段:
        if isinstance(视图.get(键), (list, dict)):
            视图[键] = json.dumps(视图[键], ensure_ascii=False)
    写入记录 = dict(视图)
    # 主键与真实列：表列白名单由能力侧校验；载荷逐字等于视图 JSON（与旧链路同口径）。
    写入记录["id"] = 开工id
    写入记录["work_id"] = 开工id
    参数: dict = {"域": 运行库域_协作状态, "记录": 写入记录, "超时秒": 能力超时秒}
    if 库路径:
        参数["数据库路径"] = 库路径
    结果 = 调用底座能力(能力_写入运行态, 参数, 超时秒=能力超时秒)
    值, 问题 = _能力值(结果, f"协作状态终态未写入（主键 {开工id}）")
    if 值 is None:
        return False, 问题
    if bool(值.get("已写入")):
        return True, ""
    return False, f"协作状态终态未写入（主键未命中）：{开工id}"


# ── 资源释放：占用租约（文件/能力）+ 能力占用账本终态 ──────────────

def _读活跃租约(领域: str, 匹配列: str, 开工id: str,
            存储目录: str = "") -> tuple[list[dict], str]:
    """经 平台状态.查询记录 读 `占用租约` 表（只读）：本开工id 在该领域的活跃租约。"""
    参数: dict = {"表": 控制面表_占用租约,
               "条件": f"状态=? AND 领域=? AND {匹配列}=?",
               "参数": [租约状态_活跃, 领域, 开工id], "限制": 1000}
    if 存储目录:
        参数["存储目录"] = 存储目录
    结果 = 调用底座能力(能力_查询记录, 参数, 超时秒=能力超时秒)
    值, 问题 = _能力值(结果, "占用租约读取失败")
    if 值 is None:
        return [], 问题
    记录表 = 值.get("记录表")
    if not isinstance(记录表, list):
        return [], ""
    return [dict(项) for 项 in 记录表 if isinstance(项, dict)], ""


def _释放租约(租约id清单: list[str], 证据: str, 存储目录: str = "") -> tuple[dict, str]:
    """经 释放文件租约（唯一释放口径）释放；幂等、留释放原因、可立即重新申请。"""
    参数: dict = {"租约id清单": list(租约id清单), "原因": 证据}
    if 存储目录:
        参数["存储目录"] = 存储目录
    结果 = 调用底座能力(能力_释放文件租约, 参数, 超时秒=能力超时秒)
    值, 问题 = _能力值(结果, "占用租约释放失败")
    if 值 is None:
        return {}, 问题
    return 值, ""


def _标账本终态(租约: dict, 证据: str, 库路径: str = "") -> str:
    """把某能力租约对应的能力占用账本行标为已释放；返回失败说明（成功为 ""）。

    走 `写入运行态`（域=能力占用）的正常写入方向：重复 id 更新语义，主键 = 能力id。
    """
    能力id = str(租约.get("能力id") or "")
    if not 能力id:
        return ""
    if _测试标识命中(能力id) or any(能力id.startswith(前缀) for 前缀 in 测试标识能力前缀):
        return f"{租约.get('租约id')}: 能力id 属测试标识，不写账本"
    现在 = _现在文本()
    记录 = {"id": 能力id, "能力id": 能力id, "提供包id": str(租约.get("所有者") or ""),
          "开工id": str(租约.get("任务") or ""), "占用时间": 现在,
          "状态": 账本状态_已释放, "释放时间": 现在, "释放证据": 证据}
    参数: dict = {"域": 运行库域_能力占用, "记录": 记录, "超时秒": 能力超时秒}
    if 库路径:
        参数["数据库路径"] = 库路径
    结果 = 调用底座能力(能力_写入运行态, 参数, 超时秒=能力超时秒)
    _, 问题 = _能力值(结果, f"{能力id}: 账本落库失败")
    return 问题


def _释放资源(开工id: str, 证据: str, 控制面存储目录: str = "",
          运行库路径: str = "") -> dict:
    """释放文件租约（按 所有者=开工id）与能力租约（按 任务=开工id）+ 账本终态。

    能力租约清单经 `查询记录` 只读拿到后，一并交给 `释放文件租约`（它按 `租约id` 在租约存储里
    找键，未找到即回幂等清单，不会误放别人的租约）；能力占用租约自身的申请/释放能力面尚未开，
    本技能不自造第二执行腿，回执里如实回报 `能力面缺口`。
    """
    文件租约清单, 文件问题 = _读活跃租约(领域_文件, "所有者", 开工id, 控制面存储目录)
    能力租约清单, 能力问题 = _读活跃租约(领域_能力, "任务", 开工id, 控制面存储目录)
    同步错误: list[str] = []
    if 文件问题:
        同步错误.append(文件问题)
    if 能力问题:
        同步错误.append(能力问题)
    文件释放: dict = {"释放数量": 0, "跳过": "读取失败，未释放"}
    能力释放: dict = {"释放数量": 0, "跳过": "读取失败，未释放"}
    if not 文件问题:
        文件id清单 = [str(项.get("租约id") or "") for 项 in 文件租约清单 if 项.get("租约id")]
        if not 文件id清单:
            文件释放 = {"成功": True, "释放数量": 0, "说明": "本开工id 无活跃文件租约"}
        else:
            值, 问题 = _释放租约(文件id清单, 证据, 控制面存储目录)
            if 问题:
                同步错误.append(问题)
                文件释放 = {"成功": False, "释放数量": 0, "错误说明": 问题}
            else:
                文件释放 = {"成功": True, "释放数量": int(值.get("释放数") or 0),
                          "租约id": 文件id清单, "幂等清单": 值.get("幂等清单") or []}
    if not 能力问题:
        能力id清单 = [str(项.get("租约id") or "") for 项 in 能力租约清单 if 项.get("租约id")]
        if not 能力id清单:
            能力释放 = {"成功": True, "释放数量": 0, "说明": "本开工id 无活跃能力租约"}
        else:
            值, 问题 = _释放租约(能力id清单, 证据, 控制面存储目录)
            if 问题:
                同步错误.append(问题)
                能力释放 = {"成功": False, "释放数量": 0, "错误说明": 问题}
            else:
                能力释放 = {"成功": True, "释放数量": int(值.get("释放数") or 0),
                          "租约id": 能力id清单, "幂等清单": 值.get("幂等清单") or []}
    账本失败: list[str] = []
    for 租约 in 能力租约清单:
        说明 = _标账本终态(租约, 证据, 运行库路径)
        if 说明:
            账本失败.append(说明)
    值 = {"成功": not 同步错误 and not 账本失败,
        "文件租约": 文件释放, "能力占用": 能力释放,
        "能力面缺口": ("能力占用租约的申请与释放尚无按能力id 的注册能力"
                   "（占用租约面只开文件租约一族）；本技能不自造第二执行腿，"
                   "补齐属底座能力面任务")}
    if 账本失败:
        值["同步错误"] = "占用账本未更新：" + "；".join(账本失败)
    if 同步错误:
        值["错误说明"] = "；".join(同步错误)
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
    反馈文件 = _解析路径(_文本参数(参数, "反馈文件") or str(反馈相对), 项目根)
    验证历史文件 = _解析路径(_文本参数(参数, "验证历史文件") or str(验证历史相对), 项目根)
    释放开关 = _逻辑参数(参数, "释放资源", True)
    # 隔离用选填参数：技能验证夹具 / 临时库试跑时传；生产调用不传（走平台默认解析器）。
    运行库路径 = _文本参数(参数, "运行库路径")
    控制面库路径 = _文本参数(参数, "控制面库路径")
    运行库绝对 = str(_解析路径(运行库路径, 项目根)) if 运行库路径 else ""
    控制面目录 = ""
    if 控制面库路径:
        控制面绝对 = _解析路径(控制面库路径, 项目根)
        控制面目录 = str(控制面绝对.parent if 控制面绝对.suffix
                    and 控制面绝对.name.endswith(".db") else 控制面绝对)

    # 步骤 2：读协作状态记录（经唯一网关）
    记录, 读问题 = _读协作状态(开工id, 运行库绝对)
    if 读问题:
        return _失败(错误_登记失败, 读问题, 开工id=开工id)
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
    成功, 说明 = _写协作状态终态(开工id, 记录, 五件套路径, 结论, 收口时间, 运行库绝对)
    if not 成功:
        return _失败(错误_登记失败, f"{开工id} 收口落库失败：{说明}", 开工id=开工id)

    # 步骤 6：释放资源（写终态成功后才释放；同旧链路：收口即不留残锁）
    if 释放开关:
        资源释放 = _释放资源(开工id, f"收口：{结论}", 控制面目录, 运行库绝对)
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
