"""发布管理包的实现层：治理面发布动作的唯一执行入口（能力实现）。

本模块是 `平台控制面.发布管理` 正式包的能力实现层，包级中文入口（同包 `__init__.py`）
的 `注册能力(注册表)` 从这里取实现函数。

分工：
- `服务.py` / `迁移互斥编排器.py` / `二阶恢复.py` / `发布事务/*.py`：发布语义与状态机（唯一实现）。
- 本模块：把上述公开方法包成**统一结果契约**的能力实现，并负责能力边界上的参数校验、
  存储目录缺省与状态实例装配。

为什么要有这一层：
- 发布事实与激活指针属**平台控制面证据域**，写入口只有本包的发布服务；
- 调用方（运行核心/统一网关、开发工具门禁、模块、薄壳）**不得 import 实现**，只能经唯一能力
  调用入口按能力 id 调用，实现与本层之间由包级中文入口隔离；
- 状态库目录由调用方按部署配置传入（缺省取工程缓存下的平台控制面目录），本层不硬编码任何
  调用方的缓存根；
- 迁移编排器要**持有一条连接的显式事务**（BEGIN IMMEDIATE 跨多条语句、事务内回读状态再决定
  推进/复用/冲突），该语义留在 `迁移互斥编排器.py` 内部，本层只暴露「执行互斥迁移(任务id, 目录)」
  这一完整动作，不在能力边界暴露连接对象。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from 公共契约.运行时.运行缓存 import 解析运行缓存根
# 错误码唯一源 = `公共契约/错误结构/错误结构.py`（B-9 收口）：平台同义码只导入，不复制字面量。
from 公共契约.错误结构 import 错误码_参数不合法

# 存储目录缺省值：经唯一解析器取运行态存储根（源码态 = `<系统根>/工程缓存/平台控制面`，
# 与旧的裸相对值同义；制品态 = 平台受管缓存）。裸相对路径在制品态会把运行态写进制品。
默认存储目录 = str(解析运行缓存根(Path(__file__).resolve().parents[3]) / "平台控制面")

# (存储目录, 项目id) → 平台状态（同目录复用同一实例，避免每次调用重建状态库连接）。
_状态表: dict[tuple[str, str], Any] = {}


def _文本(值: Any) -> str:
    return str(值).strip() if 值 is not None else ""


def _取状态(存储目录: str, 项目id: str = "") -> Any:
    """按 (存储目录, 项目id) 取平台状态；目录为空即抛错（由能力实现转 参数不合法）。"""
    目录 = _文本(存储目录) or 默认存储目录
    if not 目录:
        raise ValueError("存储目录不能为空")
    键 = (目录, _文本(项目id))
    状态 = _状态表.get(键)
    if 状态 is None:
        from 平台控制面.平台状态 import 平台状态

        状态 = 平台状态(目录, 项目id=键[1])
        _状态表[键] = 状态
    return 状态


def _取发布服务(存储目录: str, 项目id: str = "") -> Any:
    from 平台控制面.发布管理.服务 import 发布管理

    return 发布管理(_取状态(存储目录, 项目id))


def _取事务目录(存储目录: str) -> Any:
    from pathlib import Path

    目录 = _文本(存储目录) or 默认存储目录
    if not 目录:
        raise ValueError("存储目录不能为空")
    return Path(目录)


def _失败存储目录(错误: Exception) -> Any:
    from 公共契约.基础类型.结果类型 import 结果

    return 结果.失败(错误码_参数不合法, f"存储目录不合法：{错误}", 来源="发布管理")


def 登记发布期望(包id: str = "", 期望版本: str = "", 调用者: str = "",
                 存储目录: str = "", 项目id: str = "") -> Any:
    """登记一条发布期望（发布流程起点的唯一写入口）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _文本(包id) or not _文本(期望版本):
        return 结果.失败(错误码_参数不合法, "包id 与 期望版本 不能为空", 来源="发布管理")
    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        发布id = 服务.登记期望版本(包id=_文本(包id), 期望版本=_文本(期望版本),
                                   调用者=_文本(调用者))
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("发布登记失败", f"登记期望版本失败：{错误}", 来源="发布管理")
    return 结果.成功结果({"发布id": 发布id, "状态": "期望"})


def 开始灰度发布(发布id: str = "", 候选版本: str = "", 比例: float | None = None,
                 存储目录: str = "", 项目id: str = "") -> Any:
    """把一条发布推进到灰度（发布不存在即明确失败，不新建）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _文本(发布id) or not _文本(候选版本) or 比例 is None:
        return 结果.失败(错误码_参数不合法, "发布id、候选版本 与 比例 不能为空", 来源="发布管理")
    比例值 = float(比例)
    if not 0.0 <= 比例值 <= 1.0:
        return 结果.失败(错误码_参数不合法, "比例必须在 0.0 到 1.0 之间", 来源="发布管理")
    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        成功, 详情 = 服务.开始灰度(发布id=_文本(发布id), 候选版本=_文本(候选版本), 比例=比例值)
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("灰度推进失败", f"开始灰度失败：{错误}", 来源="发布管理")
    if not 成功:
        return 结果.失败(详情 or "灰度推进失败", 详情 or "开始灰度未推进", 来源="发布管理")
    return 结果.成功结果({"发布id": _文本(发布id), "状态": "灰度", "灰度比例": 比例值})


def 激活发布版本(发布id: str = "", 目标: str = "", 存储目录: str = "",
                 项目id: str = "") -> Any:
    """激活一条发布（准备 → 指针 CAS → 完成；目标一致按幂等复用）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _文本(发布id) or not _文本(目标):
        return 结果.失败(错误码_参数不合法, "发布id 与 目标 不能为空", 来源="发布管理")
    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        成功, 详情 = 服务.激活(发布id=_文本(发布id), 目标=_文本(目标))
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("激活写入失败", f"激活失败：{错误}", 来源="发布管理")
    if not 成功:
        码 = "发布不存在" if 详情 == "发布不存在" else "激活指针冲突"
        return 结果.失败(码, 详情 or "激活未完成", 来源="发布管理")
    return 结果.成功结果({"发布id": _文本(发布id), "激活目标": _文本(目标), "详情": 详情})


def 切换激活指针(指针id: str = "", 目标: str = "", 期望版本: int | None = None,
                 期望令牌: int | None = None, 存储目录: str = "",
                 项目id: str = "") -> Any:
    """通用激活指针切换（版本+栅栏令牌 CAS；陈旧令牌一律被拒）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _文本(指针id) or not _文本(目标) or 期望版本 is None or 期望令牌 is None:
        return 结果.失败(错误码_参数不合法, "指针id、目标、期望版本 与 期望令牌 不能为空",
                        来源="发布管理")
    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        成功, 详情 = 服务.切换激活指针(指针id=_文本(指针id), 目标=_文本(目标),
                                      期望版本=int(期望版本), 期望令牌=int(期望令牌))
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("陈旧栅栏令牌切换被拒", f"切换异常：{错误}", 来源="发布管理")
    if not 成功:
        return 结果.失败("陈旧栅栏令牌切换被拒", 详情 or "切换被拒", 来源="发布管理")
    return 结果.成功结果({"指针id": _文本(指针id), "目标": _文本(目标),
                        "版本": int(期望版本) + 1, "栅栏令牌": int(期望令牌) + 1})


def 回滚发布(发布id: str = "", 回滚目标: str = "", 调用者: str = "",
             存储目录: str = "", 项目id: str = "") -> Any:
    """回滚一条发布（指针 CAS 到回滚目标，历史发布记录保留）。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not _文本(发布id) or not _文本(回滚目标):
        return 结果.失败(错误码_参数不合法, "发布id 与 回滚目标 不能为空", 来源="发布管理")
    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        成功, 详情 = 服务.回滚(发布id=_文本(发布id), 回滚目标=_文本(回滚目标),
                              调用者=_文本(调用者))
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("回滚 CAS 失败", f"回滚异常：{错误}", 来源="发布管理")
    if not 成功:
        码 = "发布不存在" if 详情 == "发布不存在" else (
            "无激活指针可回滚" if 详情 == "无激活指针可回滚" else "回滚 CAS 失败")
        return 结果.失败(码, 详情 or "回滚未完成", 来源="发布管理")
    return 结果.成功结果({"发布id": _文本(发布id), "回滚目标": _文本(回滚目标), "详情": 详情})


def 恢复未完成发布(存储目录: str = "", 项目id: str = "") -> Any:
    """重启恢复：把 准备/灰度 的发布幂等收敛到明确版本（无半激活）。"""
    from 公共契约.基础类型.结果类型 import 结果

    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        恢复表 = 服务.恢复未完成发布()
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("恢复失败", f"恢复未完成发布失败：{错误}", 来源="发布管理")
    return 结果.成功结果({"恢复表": list(恢复表), "数量": len(恢复表)})


def 对账发布状态(存储目录: str = "", 项目id: str = "") -> Any:
    """控制面对账：期望状态（发布记录）vs 实际状态（激活指针）逐项核对并修复。"""
    from 公共契约.基础类型.结果类型 import 结果

    try:
        服务 = _取发布服务(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        对账表 = 服务.对账()
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("对账失败", f"对账失败：{错误}", 来源="发布管理")
    return 结果.成功结果({"对账表": list(对账表), "数量": len(对账表)})


def 执行互斥迁移(迁移任务id: str = "", 存储目录: str = "",
                 步骤延迟秒: float = 0.0) -> Any:
    """并发互斥迁移编排：同一存储上只允许一个任务推进，其余复用或明确冲突。"""
    from 公共契约.基础类型.结果类型 import 结果
    from 平台控制面.发布管理.迁移互斥编排器 import 迁移互斥编排器

    if not _文本(迁移任务id) or not _文本(存储目录):
        return 结果.失败(错误码_参数不合法, "迁移任务id 与 存储目录 不能为空", 来源="发布管理")
    try:
        编排器 = 迁移互斥编排器(_取事务目录(存储目录))
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    编排器.步骤延迟秒 = float(步骤延迟秒 or 0.0)
    try:
        结果文本, 状态 = 编排器.执行迁移(_文本(迁移任务id))
    except (TypeError, ValueError, OSError) as 错误:
        编排器.清理()
        return 结果.失败("迁移执行失败", f"执行迁移失败：{错误}", 来源="发布管理")
    编排器.清理()
    return 结果.成功结果({"结果": 结果文本, "状态": 状态})


def 校验幂等恢复(发布id: str = "", 期望版本: str = "", 调用者: str = "",
                 存储目录: str = "", 项目id: str = "") -> Any:
    """二阶幂等恢复校验：真实恢复 + 重复恢复稳定 + 证据只追加（不满足即明确失败）。"""
    from 公共契约.基础类型.结果类型 import 结果
    from 平台控制面.发布管理.二阶恢复 import 幂等恢复校验

    if not _文本(发布id) or not _文本(期望版本):
        return 结果.失败(错误码_参数不合法, "发布id 与 期望版本 不能为空", 来源="发布管理")
    try:
        状态 = _取状态(存储目录, 项目id)
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        值 = 幂等恢复校验(状态, _文本(发布id), _文本(期望版本), 调用者=_文本(调用者))
    except ValueError as 错误:
        return 结果.失败("发布不存在", str(错误), 来源="发布管理")
    except AssertionError as 错误:
        return 结果.失败("幂等恢复校验失败", str(错误), 来源="发布管理")
    except (TypeError, OSError) as 错误:
        return 结果.失败("幂等恢复校验失败", f"幂等恢复校验异常：{错误}", 来源="发布管理")
    return 结果.成功结果(值)


def 开始发布事务(包id: str = "", 版本: str = "", 存储目录: str = "") -> Any:
    """开始一条发布事务（同目录临时文件 + 原子替换持久化）。"""
    from 公共契约.基础类型.结果类型 import 结果
    from 平台控制面.发布管理.发布事务.发布事务 import 发布事务管理器

    if not _文本(包id) or not _文本(版本):
        return 结果.失败(错误码_参数不合法, "包id 与 版本 不能为空", 来源="发布管理")
    try:
        管理器 = 发布事务管理器(_取事务目录(存储目录))
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        事务 = 管理器.开始(_文本(包id), _文本(版本))
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("事务写入失败", f"开始发布事务失败：{错误}", 来源="发布管理")
    return 结果.成功结果({"事务id": 事务.事务id, "包id": 事务.包id,
                        "版本": 事务.版本, "状态": 事务.状态})


def 查询未完成发布事务(存储目录: str = "") -> Any:
    """查询未完成的发布事务（进行中/失败/回滚失败）与事务文件加载问题。"""
    from 公共契约.基础类型.结果类型 import 结果
    from 平台控制面.发布管理.发布事务.发布事务 import 发布事务管理器

    try:
        管理器 = 发布事务管理器(_取事务目录(存储目录))
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        未完成 = 管理器.查询未完成()
        加载问题 = list(管理器.加载问题)
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("事务查询失败", f"查询未完成事务失败：{错误}", 来源="发布管理")
    return 结果.成功结果({
        "事务列表": [事务.转字典() for 事务 in 未完成],
        "数量": len(未完成),
        "加载问题": 加载问题,
    })


def 扫描未完成操作(存储目录: str = "") -> Any:
    """扫描发布操作日志里未完成的操作并给出半成品判定（只读，不掩盖损坏日志）。"""
    from 公共契约.基础类型.结果类型 import 结果
    from 平台控制面.发布管理.发布事务.事务恢复 import 事务恢复

    try:
        恢复 = 事务恢复(_取事务目录(存储目录))
    except (TypeError, ValueError, OSError) as 错误:
        return _失败存储目录(错误)
    try:
        未完成 = 恢复.扫描未完成()
        拒绝 = bool(恢复.拒绝半成品())
    except (TypeError, ValueError, OSError) as 错误:
        return 结果.失败("操作日志查询失败", f"扫描未完成操作失败：{错误}", 来源="发布管理")
    return 结果.成功结果({
        "操作列表": [记录.转字典() for 记录 in 未完成],
        "数量": len(未完成),
        "拒绝半成品": 拒绝,
    })
