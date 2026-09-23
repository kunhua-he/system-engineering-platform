"""制品验证面：制品选择／来源绑定／字节快照／契约 HTML 矩阵／第三方访问声明。

内容：`选择待验证制品`、`读取统一工作区字节指纹`、`_读取契约能力`、`校验制品来源绑定`、
`读取制品字节快照`、`核验制品字节未变`、`构建验证缓存环境`、`_资源释放证据通过`、
`校验契约与HTML矩阵`、`_代码使用类型`、`_未核验前缀`、`_定位制品层根`、`校验第三方访问声明`、
`校验网关运行态同根`。

**本文件由 `开发工具/发布门禁/运行发布门禁.py` 按检查项簇**逐字搬移**（成员名一个不改、
判据一处不复制）。依赖方向**单向**：本文件只依赖底座/同族子模块，**不得 import 主文件**
（主文件 import 本文件；反向 import 会成循环）。主文件仍 re-export 本文件全部对外符号，
故 `from 开发工具.发布门禁.运行发布门禁 import <名>` 照旧可用。
"""

from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假

from 开发工具.发布门禁.运行发布门禁_底座 import (
    _创建门禁临时目录,
    _调用包仓库能力,
)
from typing import Any
from pathlib import Path
import ast
import json


def 校验网关运行态同根() -> tuple[bool, str]:
    """经**运行中的网关**（HTTP）判「网关运行态与构建链同根」（债务 #219）。

    为什么必须「经网关」、不能用本门禁进程内的装配（`_调用包仓库能力`）：那套装配跑在
    **本门禁进程**里、按本进程的根解析，判的是本进程而不是网关 —— 网关分叉时它照样全绿。
    实测形态（2026-09-21）：网关「健康 200／能力数 746／装配告警空」全绿，而它的
    `制品仓库`／`运行数据` 被解析到 `~/Library/Caches/系统工程平台/运行缓存/`，
    与构建链写入的源码树 `工程缓存` **不是同一棵树**。故本条走 HTTP 问运行中的那个进程。

    判据本体**不在此处复制**：`开发工具/能力网关/重启网关.py` 是「网关运行态」这条腿的
    唯一落点，`判定同根`／`运行态同根`／`期望运行缓存根` 都在那里（哲学 1.2）。
    """
    from 开发工具.能力网关.重启网关 import 读取凭证, 运行态同根
    try:
        凭证 = 读取凭证()
    except SystemExit as 错误:
        return 假, f"取不到网关凭证（{错误}）—— 判据取不到即判红"
    if not 凭证:
        return 假, "取不到网关凭证（plist 里为空）—— 判据取不到即判红"
    结论 = 运行态同根(凭证)
    return bool(结论.get("同根")), str(结论.get("说明") or "")


def 选择待验证制品(
    显式制品: Path | None,
    激活制品获取器: Any | None = None,
) -> tuple[Path, str]:
    """只选择明确待发布制品或正式激活制品，不允许演示/历史/备用回退。"""
    来源 = "明确待发布" if 显式制品 is not None else "正式激活"
    if 显式制品 is not None:
        制品 = Path(显式制品).resolve()
    else:
        if 激活制品获取器 is None:
            调用结果 = _调用包仓库能力("平台控制面.包仓库.校验平台客户端稳定路径", {})
            if not 调用结果.成功:
                raise ValueError(f"正式激活制品不可用: {调用结果.错误说明}")
            值 = 调用结果.值
            有效 = bool(值.get("有效"))
            消息 = str(值.get("消息", ""))
            激活路径 = 值.get("激活路径") or None
            if not 有效 or 激活路径 is None:
                raise ValueError(f"正式激活制品不可用: {消息}")
            制品 = Path(激活路径).resolve()
        else:
            激活结果 = 激活制品获取器()
            if isinstance(激活结果, tuple):
                有效, 消息, 激活路径 = 激活结果
                if not 有效 or 激活路径 is None:
                    raise ValueError(f"正式激活制品不可用: {消息}")
                制品 = Path(激活路径).resolve()
            else:
                if 激活结果 is None:
                    raise ValueError("正式激活制品不存在")
                制品 = Path(激活结果).resolve()
    if not 制品.is_dir():
        raise ValueError(f"{来源}制品目录不存在: {制品}")
    启动器 = 制品 / "运行入口" / "启动.py"
    if not 启动器.is_file():
        raise ValueError(f"{来源}制品缺少正式运行入口: {启动器}")
    return 制品, 来源


def 读取统一工作区字节指纹() -> dict[str, str]:
    """消费编译器唯一字节指纹契约；共享实现未合并时 fail-closed。"""
    from 开发工具.项目编译 import 项目编译器

    for 名称 in ("读取工作区字节指纹", "计算工作区字节指纹", "_工作区字节指纹"):
        函数 = getattr(项目编译器, 名称, None)
        if callable(函数):
            结果 = 函数()
            if isinstance(结果, dict):
                return 结果
    raise RuntimeError(
        "编译器唯一工作区字节指纹契约尚未合并；门禁禁止退回状态文本摘要或自造算法"
    )


def _读取契约能力(制品目录: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """经唯一聚合契约解析器读取制品全部正式能力。"""
    from 开发工具.契约编译.聚合契约解析 import 解析聚合契约

    能力表: list[dict[str, Any]] = []
    问题表: list[str] = []
    已见: set[str] = set()
    for 契约文件 in sorted(制品目录.rglob("能力契约/参数契约.json")):
        标准契约, 问题 = 解析聚合契约(契约文件, 严格=True)
        相对 = 契约文件.relative_to(制品目录).as_posix()
        问题表.extend(f"{相对}: {项}" for 项 in 问题)
        for 能力 in 标准契约.get("能力契约", []):
            能力id = str(能力.get("能力id", ""))
            if 能力id in 已见:
                问题表.append(f"公开能力重复: {能力id}")
                continue
            已见.add(能力id)
            缺字段 = [字段 for 字段 in ("返回", "错误码", "行为", "提供者", "版本")
                   if not 能力.get(字段)]
            if "参数" not in 能力 or not isinstance(能力.get("参数"), list):
                缺字段.insert(0, "参数")
            if 缺字段:
                问题表.append(f"{能力id}: 唯一契约缺字段 {缺字段}")
            能力表.append(能力)
    if not 能力表:
        问题表.append("制品内没有可校验的正式能力契约")
    return 能力表, 问题表


def 校验制品来源绑定(
    制品目录: Path,
    *,
    当前指纹: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """绑定当前 HEAD、统一工作区字节指纹与制品全文件摘要。"""
    身份: dict[str, Any] = {"制品路径": str(Path(制品目录).resolve())}
    try:
        来源 = json.loads((制品目录 / "制品来源.json").read_text(encoding="utf-8"))
        清单 = json.loads((制品目录 / "编译清单.json").read_text(encoding="utf-8"))
        摘要文件 = json.loads((制品目录 / "制品完整性摘要.json").read_text(encoding="utf-8"))
        指纹 = 当前指纹 if 当前指纹 is not None else 读取统一工作区字节指纹()
        当前提交 = str(指纹.get("提交", ""))
        当前字节指纹 = str(指纹.get("工作区字节指纹", ""))
        来源提交 = str(来源.get("提交", ""))
        清单提交 = str(清单.get("来源提交", ""))
        来源字节指纹 = str(来源.get("工作区字节指纹", ""))
        清单字节指纹 = str(清单.get("来源工作区字节指纹", ""))
        能力表, 契约问题 = _读取契约能力(制品目录)
        if 契约问题:
            raise ValueError("；".join(契约问题))
        from 开发工具.项目编译.项目编译器 import _制品文件摘要
        实际摘要 = _制品文件摘要(制品目录)
        身份.update({
            "全文件摘要": 实际摘要.get("制品摘要", ""),
            "文件数": 实际摘要.get("文件数", 0),
            "来源提交": 来源提交,
            "工作区字节指纹": 来源字节指纹,
            "能力数": len(能力表),
        })
        if not 当前提交 or not 当前字节指纹:
            raise ValueError("统一工作区字节指纹缺少 提交/工作区字节指纹")
        if 来源提交 != 当前提交 or 清单提交 != 当前提交:
            raise ValueError(f"来源提交与当前 HEAD 不一致: {来源提交 or '<空>'} != {当前提交}")
        if not 来源字节指纹 or not 清单字节指纹:
            raise ValueError("制品缺少统一工作区字节指纹字段")
        if 来源字节指纹 != 清单字节指纹:
            raise ValueError("制品来源与编译清单的工作区字节指纹不一致")
        if 来源字节指纹 != 当前字节指纹:
            状态 = 指纹.get("工作区状态", "未知")
            raise ValueError(f"旧制品阻断: 当前工作区({状态})真实字节指纹已变化")
        if 实际摘要.get("制品摘要") != 摘要文件.get("制品摘要"):
            raise ValueError("制品全文件摘要与真实制品不一致")
        详情 = (
            f"制品路径={身份['制品路径']}；全文件摘要={身份['全文件摘要']}；"
            f"来源提交={来源提交}；能力数={len(能力表)}"
        )
        return 真, 详情, 身份
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError, TypeError, AttributeError) as 错误:
        return 假, str(错误), 身份



# 本地环境依赖变量（哲学第 1 条 1 项）：见文件头 `开发工具.HTML验证.环境依赖` 的唯一实现导入。

def 读取制品字节快照(制品目录: Path) -> dict[str, bytes]:
    """读取制品全部文件原始字节，用于前后逐路径精确比较。"""
    快照: dict[str, bytes] = {}
    for 文件 in sorted(Path(制品目录).rglob("*")):
        if 文件.is_symlink():
            raise ValueError(f"制品包含符号链接: {文件.relative_to(制品目录)}")
        if 文件.is_file():
            快照[文件.relative_to(制品目录).as_posix()] = 文件.read_bytes()
    if not 快照:
        raise ValueError("制品没有正式文件")
    return 快照


def 核验制品字节未变(
    验证前: dict[str, bytes], 验证后: dict[str, bytes],
) -> tuple[bool, str]:
    """核验验证器没有新增、删除或修改制品内任何字节。"""
    if 验证前 == 验证后:
        return 真, f"验证前后 {len(验证前)} 个文件逐字节一致"
    新增 = sorted(set(验证后) - set(验证前))
    删除 = sorted(set(验证前) - set(验证后))
    漂移 = sorted(路径 for 路径 in set(验证前) & set(验证后)
                if 验证前[路径] != 验证后[路径])
    return 假, f"制品被验证过程修改：新增{新增} 删除{删除} 字节漂移{漂移}"


def 构建验证缓存环境(制品目录: Path) -> tuple[Path, dict[str, str]]:
    """创建制品外受管缓存，并返回验证子进程必须使用的环境。"""
    缓存根 = _创建门禁临时目录(前缀="发布门禁受管缓存_").resolve()
    if 缓存根.is_relative_to(Path(制品目录).resolve()):
        raise ValueError(f"受管缓存不得位于待验证制品内: {缓存根}")
    字节码根 = 缓存根 / "字节码"
    工程缓存根 = 缓存根 / "工程缓存"
    字节码根.mkdir(parents=True, exist_ok=True)
    工程缓存根.mkdir(parents=True, exist_ok=True)
    from 公共契约.运行时.运行缓存 import 解析运行缓存根
    共享提供者根 = 解析运行缓存根(Path(制品目录) / "平台客户端")
    return 缓存根, {
        "TMPDIR": str(缓存根), "TMP": str(缓存根), "TEMP": str(缓存根),
        "PYTHONPYCACHEPREFIX": str(字节码根),
        "PYTHONDONTWRITEBYTECODE": "1",
        "系统底座_工程缓存根": str(工程缓存根),
        "系统底座_提供者环境根": str(共享提供者根),
    }


def _资源释放证据通过(证据: Any) -> bool:
    if not isinstance(证据, dict) or not 证据:
        return 假
    for 键, 值 in 证据.items():
        if "已退出" in str(键):
            if 值 is not True:
                return 假
        elif "残留" in str(键) and 值 != 0:
            return 假
    return any("已退出" in str(键) or "残留" in str(键) for 键 in 证据)


def 校验契约与HTML矩阵(
    制品目录: Path, 报告: dict[str, Any],
) -> tuple[bool, str, int]:
    """消费冻结v1报告：契约完整、408目标全集、真实成功值、清理和制品不变。"""
    能力表, 问题表 = _读取契约能力(制品目录)
    if Path(str(报告.get("制品路径", ""))).resolve() != Path(制品目录).resolve():
        问题表.append("HTML执行矩阵不是同一制品")
    结果表 = 报告.get("结果列表")
    if not isinstance(结果表, list) or not 结果表:
        问题表.append("HTML执行矩阵缺少非空结果列表")
        结果表 = []
    if int(报告.get("失败数", 0) or 0) != 0:
        问题表.append(f"HTML执行矩阵有 {报告.get('失败数')} 项失败")
    正式全集 = {能力["能力id"] for 能力 in 能力表}
    目标全集 = set(报告.get("正向目标能力全集") or [])
    实际全集 = set(报告.get("实际成功目标能力全集") or [])
    if 目标全集 != 正式全集:
        问题表.append(f"目标能力全集不一致: 缺少={sorted(正式全集 - 目标全集)}")
    if 实际全集 != 正式全集:
        问题表.append(f"实际成功能力全集不一致: 缺少={sorted(正式全集 - 实际全集)}")
    资源回收 = 报告.get("资源回收")
    if (not isinstance(资源回收, dict) or 资源回收.get("已回收") is not True
            or 资源回收.get("进程组残留") is not False
            or int(报告.get("资源残留数", -1)) != 0
            or int(报告.get("清理失败数", -1)) != 0):
        问题表.append("HTML执行矩阵资源回收或清理证据不完整")
    摘要前 = (报告.get("制品摘要前") or {}).get("制品摘要")
    摘要后 = (报告.get("制品摘要后") or {}).get("制品摘要")
    if not 摘要前 or 摘要前 != 摘要后:
        问题表.append("HTML执行前后制品摘要不一致")
    for 能力id in sorted(正式全集):
        成功结果 = next((项 for 项 in 结果表
                     if isinstance(项, dict) and 项.get("能力id") == 能力id
                     and 项.get("步骤类型") == "目标" and 项.get("通过") is True
                     and isinstance(项.get("返回"), dict) and 项["返回"].get("成功") is True), None)
        if 成功结果 is None:
            问题表.append(f"{能力id}: 缺少真实成功目标场景")
            continue
        状态码 = 成功结果.get("状态码")
        if not isinstance(状态码, int) or not 200 <= 状态码 < 300:
            问题表.append(f"{能力id}: 成功状态码证据缺失或非法")
        if "值" not in 成功结果["返回"] or 成功结果["返回"].get("值") is None:
            问题表.append(f"{能力id}: 缺少真实业务值")
    return not 问题表, "；".join(问题表) or f"{len(能力表)} 个能力真实HTTP成功并完成资源收口", len(能力表)


def _代码使用类型(实现目录: Path) -> set[str]:
    """从第三方提供者真实实现识别网络/文件/进程访问类型。"""
    类型表: set[str] = set()
    网络模块 = {"socket", "urllib", "http", "ftplib", "smtplib"}
    进程模块 = {"subprocess", "multiprocessing"}
    文件调用 = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "unlink", "mkdir", "rmdir"}
    for 文件 in 实现目录.rglob("*.py") if 实现目录.is_dir() else []:
        try:
            树 = ast.parse(文件.read_text(encoding="utf-8"), filename=str(文件))
        except (OSError, UnicodeDecodeError, SyntaxError):
            类型表.add("不可审计")
            continue
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                模块表 = {别名.name.split(".")[0] for 别名 in 节点.names}
            elif isinstance(节点, ast.ImportFrom):
                模块表 = {(节点.module or "").split(".")[0]}
            else:
                模块表 = set()
            if 模块表 & 网络模块:
                类型表.add("网络")
            if 模块表 & 进程模块:
                类型表.add("进程")
            if isinstance(节点, ast.Call):
                名称 = 节点.func.id if isinstance(节点.func, ast.Name) else (
                    节点.func.attr if isinstance(节点.func, ast.Attribute) else "")
                if 名称 in 文件调用:
                    类型表.add("文件")
    return 类型表


_未核验前缀 = "未核验（不占通过位，不计入通过）"
"""**没有取到任何核验证据**时用的独立状态前缀（2026-09-17 修 A1「第三方声明恒绿」）。

原实现把「空集」写成 `跳过（空集，不构成证据）` 却仍 `return True`，于是一个
**强制项在没有任何证据的情况下占住了通过位**，最后被读成「N/N 项强制门禁全过」。
本前缀对应的返回值是 `None`（未核验），由 `门禁结果.汇总()` 归入独立的「未核验」桶：
既不占通过位，也不冒充失败证据。**只要一项强制门禁是未核验，发布状态就不可能是
「通过」**（未核验且无失败项 → 阻断）。空集本身就意味着「没东西可查」，
而「没东西可查」不构成核验证据（哲学第 1 条 4 项：空转即杀）。
"""


def _定位制品层根(制品目录: Path) -> Path | None:
    """双根探测真实制品层：先 `制品目录/平台客户端`，再兼容 `制品目录` 自身。

    为什么必须双根（2026-09-17 修 A1 的根因）：真实编译产物的平台代码放在
    `制品目录/平台客户端/` 之下，而 `制品来源.json`、`编译清单.json`、
    `运行入口/启动.py` 都在 `制品目录` 根，所以 `制品目录/支持库` 从来不存在
    ——原实现只认 `制品目录/支持库/适配层`，于是每次都落到空集分支，本强制项
    长期恒绿（“跳过（空集）”却计入「N/N 项强制门禁全过」）。

    判据是「候选根下存在 `支持库/` 目录」；两个候选都不成立即返回 `None`
    （由调用方按**未核验**记账，不得返回通过）。
    """
    制品目录 = Path(制品目录)
    for 候选 in (制品目录 / "平台客户端", 制品目录):
        if (候选 / "支持库").is_dir():
            return 候选
    return None


def 校验第三方访问声明(制品目录: Path) -> tuple[bool | None, str]:
    """按真实第三方依赖及实现访问类型强制核验权限/网络/文件/进程声明。

    返回 `(通过, 详情)`：

    - `通过=True/False`：真的核验到了提供者集合，结论可信；
    - `通过=None`：**未核验**——定位不到真实制品层（`平台客户端/支持库` 与
      `制品目录/支持库` 都不存在），本强制项没有取得任何证据。调用方必须按
      「不占通过位」记账，**不得**当成通过。
    """
    from 开发工具.契约编译.能力定义编译器 import 提取能力列表

    制品目录 = Path(制品目录)
    制品层根 = _定位制品层根(制品目录)
    if 制品层根 is None:
        return None, (f"{_未核验前缀}：{制品目录} 下 平台客户端/支持库 与 支持库 均不存在，"
                      "定位不到第三方提供者与依赖锁，本强制项未取得核验证据（不得计入通过）")
    问题表: list[str] = []
    提供者数 = 0
    适配层根 = 制品层根 / "支持库" / "适配层"
    from 开发工具.依赖生命周期审计.审计核心 import 扫描提供者目录
    标准提供者表, _ = 扫描提供者目录(制品层根)
    for 提供者目录 in 标准提供者表:
        if not (提供者目录 / "依赖锁.json").is_file():
            问题表.append(f"{提供者目录.name}: 第三方提供者缺真实依赖锁")
    锁文件表 = sorted(适配层根.rglob("依赖锁.json")) if 适配层根.is_dir() else []

    for 锁路径 in 锁文件表:
        提供者 = 锁路径.parent
        if not (提供者 / "包声明.json").is_file():
            问题表.append(f"{提供者.name}: 有第三方依赖锁但缺包声明")
            continue
        try:
            锁 = json.loads(锁路径.read_text(encoding="utf-8"))
            if not isinstance(锁, dict):
                raise ValueError("依赖锁必须是对象")
            第三方包 = 锁.get("包") or 锁.get("直接依赖") or []
        except (OSError, json.JSONDecodeError, ValueError):
            问题表.append(f"{提供者.name}: 第三方依赖锁不可读")
            continue
        if not 第三方包:
            # 空依赖锁不能当成“无第三方依赖”放行：依赖锁本身就是第三方声明，
            # 锁里没有任何包条目等于这份声明不可核验，必须点名而不是静默跳过。
            问题表.append(f"{提供者.name}: 第三方依赖锁没有任何包/直接依赖条目，访问声明不可核验")
            continue
        提供者数 += 1
        前缀 = 提供者.name
        if any(not isinstance(项, dict) or not 项.get("名称") or not 项.get("版本")
               or any(符号 in str(项.get("版本")) for 符号 in (">", "<", "~", "^", "*"))
               for 项 in 第三方包):
            问题表.append(f"{前缀}: 真实第三方依赖缺名称或精确版本")
        try:
            定义 = json.loads((提供者 / "能力定义.json").read_text(encoding="utf-8"))
            if not isinstance(定义, dict):
                raise ValueError("能力定义必须是对象")
        except (OSError, json.JSONDecodeError, ValueError):
            问题表.append(f"{前缀}: 能力定义不可读，无法核验访问声明")
            continue
        能力表 = 提取能力列表(定义)
        if not 能力表:
            问题表.append(f"{前缀}: 第三方提供者没有可核验能力")
        try:
            权限 = json.loads((提供者 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            权限 = {}
        if not isinstance(权限, dict):
            权限 = {}
        缺权限 = [能力.get("能力id") for 能力 in 能力表
                if 能力.get("能力id") not in 权限
                or not isinstance(权限.get(能力.get("能力id")), dict)
                or not 权限.get(能力.get("能力id"))]
        if 缺权限:
            问题表.append(f"{前缀}: 权限声明缺能力 {缺权限}")
        实际类型 = _代码使用类型(提供者 / "实现")
        参数文本 = json.dumps([能力.get("参数", []) for 能力 in 能力表], ensure_ascii=False)
        if "文件" in 参数文本 or "路径" in 参数文本:
            实际类型.add("文件")
        行为表: list[dict[str, Any]] = []
        for 能力 in 能力表:
            行为 = 能力.get("行为")
            行为表.append(行为 if isinstance(行为, dict) else {})
        副作用文本 = " ".join(str(行为.get("副作用", "")) for 行为 in 行为表)
        释放文本 = " ".join(str(行为.get("资源释放", "")) for 行为 in 行为表)
        if any(not str(行为.get("副作用", "")).strip()
               or not str(行为.get("资源释放", "")).strip() for 行为 in 行为表):
            问题表.append(f"{前缀}: 第三方能力缺显式副作用或资源释放声明")
        if "网络" in 实际类型 and "网络" not in 副作用文本:
            问题表.append(f"{前缀}: 真实网络访问缺网络声明")
        if "文件" in 实际类型 and (not 副作用文本.strip() or not 释放文本.strip()):
            问题表.append(f"{前缀}: 真实文件访问缺文件副作用/资源释放声明")
        if "进程" in 实际类型:
            try:
                生命周期 = json.loads((提供者 / "生命周期契约.json").read_text(encoding="utf-8"))
                预算 = json.loads((提供者 / "资源预算.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                生命周期, 预算 = {}, {}
            if ("进程" not in str(生命周期.get("资源模型", ""))
                    or int(预算.get("子进程上限", 0) or 0) <= 0
                    or "进程" not in (释放文本 + str(生命周期.get("释放策略", "")))):
                问题表.append(f"{前缀}: 真实进程访问缺进程模型/预算/释放声明")
        if "不可审计" in 实际类型:
            问题表.append(f"{前缀}: 实现源码不可审计")
    if 提供者数 == 0 and not 问题表:
        # 空集不能直接断言“未声明第三方依赖”，也不能占通过位：必须把真实核验范围
        # 与范围外的依赖锁数量一起报出来，避免“没扫到”被读成“不存在”。
        # 这里返回 None（未核验）而不是 True：核验对象为空集 = 没有取得任何证据，
        # 把它记成「通过」正是本项恒绿的第二个入口（与 _定位制品层根 同源缺陷）。
        支持库根 = 制品层根 / "支持库"
        外置锁数 = len([路径 for 路径 in 支持库根.rglob("依赖锁.json")
                       if 适配层根 not in 路径.parents])
        层标 = "平台客户端/" if 制品层根 != 制品目录 else ""
        return None, (f"{_未核验前缀}：{层标}支持库/ 下未发现第三方提供者"
                      f"（标准提供者 0、依赖锁 0），本项未取得核验证据（不得计入通过）；"
                      f"适配层外另有 {外置锁数} 份依赖锁不在本项声明核验范围")
    return not 问题表, "；".join(问题表) or f"{提供者数} 个第三方提供者权限/网络/文件/进程声明与真实依赖一致"


#: 制品落后提交数阈值（债务 #133③）：`git rev-list --count <制品提交>..HEAD` **超过**它即判红。
#: 0 = 「制品来源提交必须 = HEAD」，与 `校验制品来源绑定` 的提交比对同口径；但本条**只比
#: 提交数、不碰工作区字节指纹**，故工作区脏/本地残留不会误伤它（那类假红见 #133②）。
制品落后提交阈值 = 0


def _仓库根() -> Path:
    """本模块所在仓库根：`开发工具/发布门禁/<本文件>` 往上三层。"""
    return Path(__file__).resolve().parents[2]


def 计算制品落后提交数(
    制品目录: Path, 仓库根: Path | None = None,
) -> tuple[int | None, str]:
    """制品来源提交 → HEAD 之间的提交数（`git rev-list --count <制品提交>..HEAD`）。

    判据事实源（债务 #133③ / F4）：`制品来源.json` 的 `提交` 字段 + 真 `git` 计数。
    取不到（缺文件 / 缺字段 / 非 git 仓库 / 提交不存在）回 `(None, 说明)` —— fail-closed
    由调用方判红，绝不把「没量到」当「没落后」。
    """
    import subprocess

    制品目录 = Path(制品目录)
    根 = Path(仓库根) if 仓库根 is not None else _仓库根()
    try:
        来源 = json.loads((制品目录 / "制品来源.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        return None, f"制品来源.json 不可读: {错误}"
    制品提交 = str(来源.get("提交") or "").strip() if isinstance(来源, dict) else ""
    if not 制品提交:
        return None, "制品来源.json 缺 提交 字段"
    try:
        计数 = subprocess.run(
            ["git", "rev-list", "--count", f"{制品提交}..HEAD"],
            cwd=str(根), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as 错误:
        return None, f"git rev-list 起不来: {错误}"
    if 计数.returncode != 0:
        return None, (f"git rev-list 退出码 {计数.returncode}: "
                      f"{(计数.stderr or '').strip()[:200]}")
    try:
        return int(计数.stdout.strip()), 制品提交
    except ValueError:
        return None, f"git rev-list 输出不是整数: {计数.stdout!r}"


def 校验制品落后提交数(
    制品目录: Path, 仓库根: Path | None = None, 阈值: int | None = None,
) -> tuple[bool, str]:
    """判据：制品落后提交数 **超过阈值即判红**（债务 #133③，别靠人记得）。

    返回 `(通过, 详情)`。**取不到计数即判红**（fail-closed，与发布门禁其它项同口径）。
    """
    上限 = 制品落后提交阈值 if 阈值 is None else int(阈值)
    落后数, 说明 = 计算制品落后提交数(制品目录, 仓库根)
    if 落后数 is None:
        return 假, f"制品落后提交数取不到（{说明}）—— 判据取不到即判红"
    if 落后数 > 上限:
        return 假, (f"制品落后 HEAD {落后数} 个提交（阈值 {上限}，制品来源提交 {说明}）"
                    " —— 网关跑的是旧装配，须重建制品 + 重启网关")
    return 真, (f"制品落后 HEAD {落后数} 个提交（阈值 {上限}，"
                f"制品来源提交 {说明}）")


def 校验依赖与生命周期审计(仓库根: Path) -> tuple[bool, str]:
    """依赖与生命周期审计：把**源码树**的 `审计全部` 接进发布门禁必经路径（债务 #132）。

    为什么必须接（实测 2026-09-22/23）：`开发工具/依赖生命周期审计/` 自述是「发布门禁
    候选，只读」，但发布门禁**只用了它的一半** —— `校验第三方访问声明` 只 import
    `扫描提供者目录`，而产出 22 条违规的 `审计全部` **没有任何入口**（唯一入口是手工跑
    `运行依赖生命周期审计.py`）。判据存在却不在必经路径上 ⇒ 红着无人知（哲学 13.1：
    不在必经路径上的实现只是半个强制）。

    口径与 `运行依赖生命周期审计.py` **同一处判据**（`审计核心.审计全部`），本函数只做
    「跑它 + 归并结论」，不复制任何一条判据；违规明细逐条回带，不截断成「有违规」。

    返回 `(通过, 详情)`；取不到审计结果即判红（fail-closed）。
    """
    try:
        from 开发工具.依赖生命周期审计.审计核心 import 审计全部
    except ImportError as 错误:
        return 假, f"依赖与生命周期审计取不到判据本体（{错误}）—— 取不到即判红"
    结果列表, 跳过列表 = 审计全部(Path(仓库根))
    if not 结果列表:
        return 假, ("依赖与生命周期审计一个提供者都没审到（扫描面为 0 不得记作通过）"
                    f"；跳过 {len(跳过列表)} 个非标准目录")
    违规表: list[str] = []
    for 结果 in 结果列表:
        if 结果.是否通过:
            continue
        违规表.append(f"[{结果.提供者名}] " + "；".join(结果.违规列表))
    if 违规表:
        return 假, (f"依赖与生命周期审计判红：{len(违规表)} 个提供者、"
                    f"共 {sum(len(结果.违规列表) for 结果 in 结果列表 if not 结果.是否通过)} 条违规"
                    "（判据：开发工具/依赖生命周期审计/审计核心.审计全部，"
                    "本项只跑它、不另立判据）：\n" + "\n".join(违规表))
    return 真, (f"依赖与生命周期审计通过：{len(结果列表)} 个标准提供者逐条核过"
                f"依赖锁/完整性摘要/健康探针/停止入口/释放策略；跳过 {len(跳过列表)} 个非标准目录")
