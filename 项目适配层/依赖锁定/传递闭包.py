"""传递依赖闭包硬门禁：项目锁与声明依赖闭包的六项校验。

闭包 = 项目绑定包 + 其声明依赖逐级可达的全部提供者包。
六项校验（fail-closed，任一失败即整体失败）：
1. 缺项：声明所需能力在锁闭包内无提供者；
2. 多余项：锁闭包出现声明之外（未绑定且非任何绑定包依赖）的包；
3. 版本漂移：声明版本约束与锁定版本不符、锁内版本与提供者能力定义版本不符；
4. 循环依赖：依赖图有环（复用 运行核心/加载器/依赖解析/解析器.py 的检测）；
5. 提供者锁缺失：第三方提供者目录缺 依赖锁.json 或锁为空
   （复用 运行核心/运行环境管理器/环境管理器.py 的 读取依赖锁）；
6. 问题清单按 包id/能力id 稳定排序，每条含 包→能力→提供者 可诊断路径。

对外入口：校验传递闭包(项目根目录, 系统根目录) -> 闭包校验结果。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from 运行核心.加载器.包发现.发现器 import 发现全部
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.提供者选择.选择器 import 选择全部提供者
from 运行核心.运行环境管理器.环境管理器 import 读取依赖锁

版本约束正则 = re.compile(r"^(>=|<=|==|>|<)?\s*(\d+\.\d+\.\d+)$")

# 问题类别序号：决定同 包id/能力id 下的输出次序
缺项类别 = 0
多余类别 = 1
版本漂移类别 = 2
循环类别 = 3
提供者锁类别 = 4


@dataclass
class 闭包校验结果:
    """一次传递依赖闭包校验的结果。"""

    成功: bool = False
    问题列表: list[str] = field(default_factory=list)
    校验项数: int = 0
    包数量: int = 0


def _版本元组(版本: str) -> tuple[int, int, int]:
    """版本字符串转三段元组用于比较。"""
    return tuple(int(部分) for 部分 in 版本.split("."))  # type: ignore[return-value]


def _满足约束(实际版本: str, 约束: str) -> bool:
    """实际版本是否满足 >=/<=/==/>/< 约束；无约束或约束不合法视为满足。"""
    匹配 = 版本约束正则.match(约束.strip())
    if not 匹配:
        return True
    运算符, 目标版本 = 匹配.group(1) or "==", 匹配.group(2)
    实际, 目标 = _版本元组(实际版本), _版本元组(目标版本)
    if 运算符 == ">=":
        return 实际 >= 目标
    if 运算符 == "<=":
        return 实际 <= 目标
    if 运算符 == ">":
        return 实际 > 目标
    if 运算符 == "<":
        return 实际 < 目标
    return 实际 == 目标


def _读取项目声明(项目根目录: Path) -> dict:
    """读取 项目声明.json；结构不合法时抛异常由调用方兜底。"""
    return json.loads((项目根目录 / "项目声明.json").read_text(encoding="utf-8"))


def _绑定约束表(项目数据: dict) -> dict[str, str]:
    """从项目声明收集 包id -> 版本约束（支持库绑定 + 模块绑定）。"""
    约束表: dict[str, str] = {}
    for 组名 in ("支持库绑定", "模块绑定"):
        for 条目 in 项目数据.get(组名) or []:
            if isinstance(条目, dict) and 条目.get("包id"):
                约束表[str(条目["包id"])] = str(条目.get("版本约束", ""))
    return 约束表


def _提供者目录(系统根目录: Path, 提供者id: str) -> Path | None:
    """按提供者id 定位提供者目录（与 依赖锁定.py 的查找规则一致）。

    提供者id 形如 支持库.后端.支持库名.子包 或 支持库.适配层.提供者名：
    去掉 支持库./模块库./技能库. 前缀后，剩余段即为相对根目录的路径。
    """
    段路径 = Path(*提供者id.split(".")[1:])
    for 根 in ("支持库", "模块库", "技能库"):
        候选 = 系统根目录 / 根 / 段路径
        if (候选 / "能力定义.json").is_file():
            return 候选
    return None


def _应有闭包集合(绑定约束表: dict[str, str], 声明表: dict[str, object],
                   系统能力提供者: dict[str, tuple[str, str]]) -> set[str]:
    """从绑定包出发，沿系统声明依赖逐级扩展得到应有闭包集合。"""
    闭包: set[str] = set(绑定约束表)
    待探索 = list(闭包)
    while 待探索:
        当前 = 待探索.pop()
        声明 = 声明表.get(当前)
        if 声明 is None:
            continue
        for 依赖 in 声明.依赖:
            能力id = str(依赖.get("能力", ""))
            提供 = 系统能力提供者.get(能力id)
            if 提供 and 提供[0] not in 闭包:
                闭包.add(提供[0])
                待探索.append(提供[0])
    return 闭包


def 校验传递闭包(项目根目录: Path, 系统根目录: Path) -> 闭包校验结果:
    """校验项目锁（依赖锁定.json）与声明依赖闭包的一致性，任一漂移即失败。

    参数:
        项目根目录: 含 项目声明.json 与 依赖锁定.json 的项目目录。
        系统根目录: 含 支持库/ 与 模块库/ 的平台根目录。
    返回:
        闭包校验结果：成功标记与稳定排序问题清单（包→能力→提供者 路径）。
    """
    结果 = 闭包校验结果()
    问题条目: list[tuple[str, str, int, str]] = []

    # 一、项目声明：绑定集合与版本约束
    声明路径 = 项目根目录 / "项目声明.json"
    if not 声明路径.is_file():
        结果.问题列表.append(f"缺项: 项目→—→—（缺少项目声明 {声明路径}）")
        return 结果
    try:
        项目数据 = _读取项目声明(项目根目录)
    except (json.JSONDecodeError, OSError) as 错误:
        结果.问题列表.append(f"缺项: 项目→—→—（项目声明不可读: {错误}）")
        return 结果
    绑定约束表 = _绑定约束表(项目数据)
    if not 绑定约束表:
        结果.问题列表.append("缺项: 项目→—→—（项目声明未绑定任何支持库或模块）")
        return 结果

    # 二、项目锁：依赖锁定.json 包列表
    锁定路径 = 项目根目录 / "依赖锁定.json"
    if not 锁定路径.is_file():
        结果.问题列表.append(f"缺项: 项目→—→—（缺少依赖锁定文件 {锁定路径}）")
        return 结果
    try:
        锁定数据 = json.loads(锁定路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        结果.问题列表.append(f"缺项: 项目→—→—（依赖锁定不可读: {错误}）")
        return 结果
    锁包表 = {条目["包id"]: 条目 for 条目 in 锁定数据.get("包列表") or []
              if isinstance(条目, dict) and 条目.get("包id")}
    锁包集合 = set(锁包表)
    结果.包数量 = len(锁包集合)
    if not 锁包集合:
        结果.问题列表.append("缺项: 项目→—→—（依赖锁定为空，未锁定任何包）")
        return 结果

    # 三、系统声明与能力提供者
    发现 = 发现全部(系统根目录 / "支持库", 系统根目录 / "模块库",
                  系统根目录 / "技能库")
    if not 发现.成功:
        结果.问题列表.extend(发现.问题列表)
        return 结果
    声明表 = {声明.包id: 声明 for 声明 in 发现.声明列表}
    系统提供者表 = 选择全部提供者(发现.声明列表)
    系统能力提供者 = {
        能力id: (选择.提供包id, 选择.提供版本)
        for 能力id, 选择 in 系统提供者表.items() if 选择.成功
    }

    # 四、缺项 + 版本漂移（声明约束 vs 锁版本）+ 循环（复用解析器）
    锁内声明 = [声明 for 声明 in 发现.声明列表 if 声明.包id in 锁包集合]
    锁内提供者表 = 选择全部提供者(锁内声明)
    锁内能力提供者 = {
        能力id: (选择.提供包id, 选择.提供版本)
        for 能力id, 选择 in 锁内提供者表.items()
        if 选择.成功 and 选择.提供包id in 锁包集合
    }
    解析 = 解析依赖(锁内声明, 锁内能力提供者)
    for 声明 in sorted(锁内声明, key=lambda 条目: 条目.包id):
        for 依赖 in 声明.依赖:
            能力id = str(依赖.get("能力", ""))
            约束 = str(依赖.get("版本", ""))
            结果.校验项数 += 1
            提供 = 锁内能力提供者.get(能力id)
            if 提供 is None:
                问题条目.append((
                    声明.包id, 能力id, 缺项类别,
                    f"缺项: {声明.包id}→{能力id}→无提供者（锁闭包内无能力提供者）",
                ))
                continue
            提供包id, _ = 提供
            锁版本 = str(锁包表.get(提供包id, {}).get("版本", ""))
            if 约束 and 锁版本 and not _满足约束(锁版本, 约束):
                问题条目.append((
                    声明.包id, 能力id, 版本漂移类别,
                    f"版本漂移: {声明.包id}→{能力id}→{提供包id}"
                    f"（声明约束 {约束} 与锁定版本 {锁版本} 不符）",
                ))
    for 包id in 解析.循环:
        问题条目.append((
            包id, "", 循环类别,
            f"循环依赖: {包id}→依赖环→{', '.join(解析.循环)}（依赖图有环）",
        ))

    # 五、绑定约束 vs 锁版本（声明版本约束与锁定版本不符）
    for 包id, 约束 in sorted(绑定约束表.items()):
        结果.校验项数 += 1
        条目 = 锁包表.get(包id)
        if 条目 is None:
            问题条目.append((
                包id, "", 缺项类别,
                f"缺项: 项目→绑定→{包id}（绑定包未出现在依赖锁定中）",
            ))
            continue
        锁版本 = str(条目.get("版本", ""))
        if 约束 and 锁版本 and not _满足约束(锁版本, 约束):
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: 项目→绑定→{包id}（声明约束 {约束} 与锁定版本 {锁版本} 不符）",
            ))

    # 六、多余项：锁闭包 - 应有闭包（声明之外的包）
    应有闭包 = _应有闭包集合(绑定约束表, 声明表, 系统能力提供者)
    for 包id in sorted(锁包集合 - 应有闭包):
        原因 = "系统无此包声明" if 包id not in 声明表 else "未绑定且非任何绑定包依赖"
        问题条目.append((
            包id, "", 多余类别,
            f"多余项: 锁闭包→—→{包id}（声明之外: {原因}）",
        ))

    # 七、锁内版本 vs 提供者能力定义版本 + 提供者锁缺失（复用 读取依赖锁）
    for 包id in sorted(锁包集合):
        条目 = 锁包表[包id]
        提供者id = str(条目.get("提供者id", ""))
        if not 提供者id:
            continue
        提供者目录 = _提供者目录(系统根目录, 提供者id)
        结果.校验项数 += 1
        if 提供者目录 is None:
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}（能力定义.json 不存在，无法核对版本）",
            ))
            问题条目.append((
                包id, "", 提供者锁类别,
                f"提供者锁缺失: {包id}→—→{提供者id}（提供者目录或依赖锁.json 不存在）",
            ))
            continue
        定义路径 = 提供者目录 / "能力定义.json"
        if not 定义路径.is_file():
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}（能力定义.json 不存在，无法核对版本）",
            ))
            continue
        try:
            定义 = json.loads(定义路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as 错误:
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}（能力定义.json 不可读: {错误}）",
            ))
            continue
        提供者定义 = 定义.get("提供者") or {}
        定义版本 = str(定义.get("版本", ""))
        锁版本 = str(条目.get("版本", ""))
        约束 = str(提供者定义.get("版本", ""))
        if str(提供者定义.get("默认", "")) != 提供者id:
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}"
                f"（锁提供者id 与能力定义默认提供者 {提供者定义.get('默认', '')} 不符）",
            ))
        if 约束 and 约束 != str(条目.get("提供者版本", "")):
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}"
                f"（锁提供者版本 {条目.get('提供者版本', '')} 与能力定义约束 {约束} 不符）",
            ))
        if 定义版本 and 锁版本 and 定义版本 != 锁版本:
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}"
                f"（锁定版本 {锁版本} 与能力定义版本 {定义版本} 不符）",
            ))
        if 定义版本 and 约束 and not _满足约束(定义版本, 约束):
            问题条目.append((
                包id, "", 版本漂移类别,
                f"版本漂移: {包id}→—→{提供者id}"
                f"（能力定义版本 {定义版本} 不满足自身约束 {约束}）",
            ))
        锁文件 = 提供者目录 / "依赖锁.json"
        if not 锁文件.is_file():
            问题条目.append((
                包id, "", 提供者锁类别,
                f"提供者锁缺失: {包id}→—→{提供者id}（依赖锁.json 不存在: {锁文件}）",
            ))
            continue
        依赖锁 = 读取依赖锁(提供者目录)
        if not 依赖锁 or not 依赖锁.get("包"):
            问题条目.append((
                包id, "", 提供者锁类别,
                f"提供者锁缺失: {包id}→—→{提供者id}（依赖锁.json 为空，未锁定任何第三方包）",
            ))

    # 八、稳定排序输出：包id → 能力id → 类别 → 文本
    结果.问题列表 = [
        文本 for _, _, _, 文本 in sorted(
            问题条目, key=lambda 条目: (条目[0], 条目[1], 条目[2], 条目[3])
        )
    ]
    结果.成功 = not 结果.问题列表
    return 结果
