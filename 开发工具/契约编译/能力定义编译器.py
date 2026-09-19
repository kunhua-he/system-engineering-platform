"""能力定义编译器：以 能力定义.json 为唯一可编辑事实源，自动生成全部契约派生物。

能力作者只维护：
- 能力定义（能力id/版本/说明/参数/返回/错误码/行为/提供者）
- 实现函数体
- 必要的真实验证样例

编译器自动生成（带生成标记，禁止手工编辑）：
- 能力契约/参数契约.json（保持既有结构向后兼容）
- 包声明.json 中的能力清单
- 注册入口（__init__.py 的 注册能力）
- 能力搜索数据.json / Agent查询数据.json
- 完整性摘要.json

验证场景引用.json 不在此列：v1 场景引用契约由能力作者手写维护，旧版
编译器生成的 {场景id,目标,范围} 三键格式缺 契约版本、不是合法 v1 引用，
生成即会把合法文件覆盖成非法文件，故编译器一律不生成、不覆盖。

漂移规则：实现或契约变化后未重新生成必须失败；手工篡改生成物由漂移门禁阻断。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 开发工具.契约编译.聚合契约解析 import 解析聚合契约
from 公共契约.版本规则.契约版本 import 契约版本

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"

#: 装配器实际接受的包类型（**与 `运行核心/加载器/生命周期管理/管理器.py:198` 同口径**）。
#: 注意不要改用 `公共契约/包声明/声明.py` 的 `允许类型集合` —— 那里多一个「模块」，
#: 但装配器不认；两处不一致时以**能真正装配**的那个为准（否则产物到装配期才炸）。
_装配器可装类型 = ("支持库", "基础模块", "功能模块")

行为字段表 = [
    "修改输入", "幂等", "副作用", "排序稳定", "时区", "编码", "精度",
    "空值", "输入上限", "超时可重试", "取消", "重试条件",
    "事务边界", "补偿动作", "线程安全", "进程安全", "资源释放",
    "错误码", "可重试性",
]

易语言类型别名 = {
    "文本": "文本型", "布尔": "逻辑型", "整数": "整数型",
    "长整数": "长整数型", "双精度数": "双精度数型",
    "单精度数": "单精度数型", "字典": "字典型", "列表": "列表型",
    "字节集": "字节集型", "空值": "空值型",
}


@dataclass
class 编译结果:
    """一次能力定义编译结果。"""

    包id: str = ""
    产物列表: list[dict] = field(default_factory=list)
    问题列表: list[str] = field(default_factory=list)
    #: 聚合父包（自身不注册能力、能力在子包里）：**不编译是正确结果**，不是失败。
    聚合父包: bool = False
    #: 聚合父包识别到的子包数（仅诊断用）。
    子包数: int = 0

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 读取能力定义(文件: Path) -> dict[str, Any]:
    """读取能力定义 JSON。"""
    return json.loads(文件.read_text(encoding="utf-8"))


def 提取能力列表(定义: dict[str, Any]) -> list[dict]:
    """从能力定义提取能力列表（统一 能力列表 数组格式；兼容多种旧格式）。"""
    if "能力列表" in 定义 and isinstance(定义["能力列表"], list):
        return 定义["能力列表"]
    if "能力定义" in 定义 and isinstance(定义["能力定义"], list):
        标准条目 = []
        for 项 in 定义["能力定义"]:
            # reportlab 格式兼容：名称/能力说明
            标准条目.append({
                "能力id": 项.get("能力id") or 项.get("领域契约名", ""),
                "版本": 项.get("版本", 定义.get("版本", "1.0.0")),
                "中文名称": 项.get("中文名称") or 项.get("名称", ""),
                "说明": 项.get("说明") or 项.get("能力说明", ""),
                "参数": 项.get("参数", []),
                "返回": 项.get("返回", "结果"),
                "错误码": 项.get("错误码", []),
                "行为": 项.get("行为", {}),
                "提供者": 项.get("提供者", {}),
            })
        return 标准条目
    if "能力" in 定义 and isinstance(定义["能力"], list):
        # 兼容 能力 数组（openpyxl 格式）：转标准条目
        标准条目 = []
        for 项 in 定义["能力"]:
            领域契约名 = 项.get("领域契约名") or 项.get("能力id", "")
            标准条目.append({
                "能力id": 领域契约名,
                "版本": 定义.get("版本", "1.0.0"),
                "中文名称": 项.get("函数") or 领域契约名.split(".")[-1],
                "说明": 项.get("说明", ""),
                "参数": 项.get("参数", []),
                "返回": 项.get("返回", "结果"),
                "错误码": 项.get("错误码", []),
            })
        return 标准条目
    if 定义.get("能力id"):
        return [定义]
    return []


def 标准化易语言类型(对象: Any, *, 值结构: bool = False) -> Any:
    """只标准化类型字段和值结构中的类型值，不改业务字段/说明文字。"""
    if isinstance(对象, dict):
        结果 = {}
        for 键, 值 in 对象.items():
            if (键 in {"类型", "数据类型"} or 值结构) and isinstance(值, str):
                结果[键] = 易语言类型别名.get(值, 值)
            else:
                结果[键] = 标准化易语言类型(值, 值结构=(键 == "值结构"))
        return 结果
    if isinstance(对象, list):
        return [标准化易语言类型(值, 值结构=值结构) for 值 in 对象]
    return 对象


def 从现有包生成能力定义(包目录: Path, *, 覆盖: bool = False) -> tuple[Path | None, list[str]]:
    """从既有包声明与参数契约迁移唯一能力定义。

    这是一次性迁移入口，不读取实现源码，也不覆盖已有定义。历史包的
    参数契约/包声明是迁移事实输入；行为字段使用保守的显式默认值，后续
    能力作者可在唯一定义中修订。返回(定义路径,问题列表)，便于批次审计
    逐包记录无法安全生成的情况。
    """
    包目录 = Path(包目录)
    声明路径 = 包目录 / "包声明.json"
    契约路径 = 包目录 / "能力契约" / "参数契约.json"
    定义路径 = 包目录 / "能力定义.json"
    问题: list[str] = []
    if not 声明路径.is_file():
        return None, ["缺少包声明.json"]
    if not 契约路径.is_file():
        return None, ["缺少能力契约/参数契约.json"]
    if 定义路径.exists() and not 覆盖:
        return 定义路径, ["已有能力定义，按保护规则跳过"]
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        契约原文 = json.loads(契约路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        return None, [f"输入 JSON 不可读: {错误}"]
    能力列表 = 契约原文.get("能力契约") if isinstance(契约原文, dict) else None
    if not isinstance(能力列表, list) or not 能力列表:
        return None, ["参数契约缺少非空 能力契约 列表"]
    包id = 声明.get("包id")
    if not isinstance(包id, str) or not 包id:
        return None, ["包声明缺少包id"]
    版本 = str(声明.get("版本") or "1.0.0")
    迁移列表: list[dict[str, Any]] = []
    for 原能力 in 能力列表:
        if not isinstance(原能力, dict) or not 原能力.get("能力id"):
            问题.append("存在缺少能力id的契约条目")
            continue
        能力id = str(原能力["能力id"])
        能力版本 = str(原能力.get("版本") or 版本)
        名称 = 能力id.rsplit(".", 1)[-1]
        # 只补齐编译器要求的治理字段，不改变参数/返回/错误码事实。
        行为 = {
            "修改输入": False,
            "幂等": True,
            "副作用": "只读",
            "排序稳定": True,
            "时区": "不涉及",
            "编码": "utf-8",
            "精度": "不涉及",
            "空值": "按参数契约处理",
            "输入上限": "由资源预算约束",
            "超时可重试": False,
            "取消": "不支持",
            "重试条件": "无",
            "事务边界": "无",
            "补偿动作": "无",
            "线程安全": True,
            "进程安全": True,
            "资源释放": "按句柄生命周期自动释放",
            "错误码": "统一",
            "可重试性": "参数错误不可重试",
        }
        迁移列表.append({
            "能力id": 能力id,
            "版本": 能力版本,
            "中文名称": str(原能力.get("中文名称") or 名称),
            "说明": str(原能力.get("说明") or 名称),
            "参数": 原能力.get("参数") if isinstance(原能力.get("参数"), list) else [],
            "返回": 标准化易语言类型(原能力.get("返回") or "结果型"),
            "错误码": 原能力.get("错误码") if isinstance(原能力.get("错误码"), list) and 原能力.get("错误码") else ["参数不合法"],
            "行为": 行为,
            "提供者": {"默认": 包id, "版本": f">={能力版本}"},
        })
    if 问题:
        return None, 问题
    定义 = {
        "包id": 包id,
        "版本": 版本,
        "说明": str(声明.get("说明") or ""),
        "能力列表": 迁移列表,
        "迁移来源": {
            "参数契约": "能力契约/参数契约.json",
            "包声明": "包声明.json",
            "规则": "批次5：只从现有契约与声明迁移，不读取实现源码",
        },
    }
    if not 校验能力定义(定义):
        定义路径.write_text(json.dumps(定义, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 定义路径, []
    return None, ["迁移结果未通过能力定义结构校验"]


def 校验能力定义(定义: dict[str, Any]) -> list[str]:
    """校验能力定义结构完整（含行为与提供者字段）。"""
    问题列表 = []
    if not 定义.get("包id"):
        问题列表.append("缺少 包id")
    能力列表 = 提取能力列表(定义)
    if not 能力列表:
        问题列表.append("缺少 能力列表（须含至少一个能力）")
        return 问题列表
    # 能力id 唯一性：同一份 能力定义.json 内重复 id 会让装配直接红（「能力 id 重复」），
    # 而此前编译器只判「缺能力id」不判重复 —— 实测漏网一次（Git提供者 13 条含 2 组重复）。
    # 哲学 1.4：重复与空集都不算通过，必须在编译期拦下，不能等运行时装配才发现。
    _计数: dict[str, int] = {}
    for 能力 in 能力列表:
        _名 = str(能力.get("能力id") or "").strip()
        if _名:
            _计数[_名] = _计数.get(_名, 0) + 1
    for _名, _次 in _计数.items():
        if _次 > 1:
            问题列表.append(f"能力 id 重复: {_名} 出现 {_次} 次（同一包内能力id 必须唯一）")
    for 能力 in 能力列表:
        前缀 = f"能力 {能力.get('能力id', '?')}: "
        if not 能力.get("能力id"):
            问题列表.append("存在缺少 能力id 的能力")
        if not 能力.get("版本"):
            问题列表.append(f"{前缀}缺少 版本")
        if not 能力.get("中文名称"):
            问题列表.append(f"{前缀}缺少 中文名称")
        if not 能力.get("说明"):
            问题列表.append(f"{前缀}缺少 说明")
        if "参数" not in 能力 or not isinstance(能力["参数"], list):
            问题列表.append(f"{前缀}缺少 参数 列表")
        else:
            for 参数 in 能力["参数"]:
                if not 参数.get("名称"):
                    问题列表.append(f"{前缀}存在缺少 名称 的参数")
        if not 能力.get("返回"):
            问题列表.append(f"{前缀}缺少 返回")
        if "错误码" not in 能力 or not isinstance(能力["错误码"], list) or not 能力["错误码"]:
            问题列表.append(f"{前缀}错误码 必须为非空列表")
        # 行为字段（P5）：缺失任一正式行为字段即拒绝
        行为 = 能力.get("行为", {})
        for 字段 in 行为字段表:
            if 字段 not in 行为:
                问题列表.append(f"{前缀}行为缺少字段: {字段}")
        # 提供者优选（P4）：默认提供者必填
        提供者 = 能力.get("提供者", {})
        if not 提供者.get("默认"):
            问题列表.append(f"{前缀}提供者缺少 默认 字段")
        if not 提供者.get("版本"):
            问题列表.append(f"{前缀}提供者缺少 版本 字段")
    return 问题列表


当前契约版本 = 契约版本  # 契约版本唯一（哲学第 5 条 1 项）：本文件不再另立 1.0.0
契约条目自有键 = {"能力id", "版本", "说明", "参数", "返回", "错误码", "调用示例", "行为", "提供者"}
契约条目可保留键 = ("中文名称", "名称")


def 生成能力契约(定义: dict[str, Any], 既有契约: dict[str, Any] | None = None) -> str:
    """生成 能力契约/参数契约.json（S0 唯一聚合格式：契约版本+能力契约）。

    非破坏性口径（不降级、不丢手写内容）：
    - **契约版本唯一**：恒等于平台契约事实源（哲学第 5 条 1 项）——契约只有一套；
    - **能力/包各自的迭代版本原样保留**（支持库与模块按自身迭代展示，不强制对齐）；
    - 既有条目里的 中文名称/名称 等编译器不产出的键原样保留；
    - 既有条目里的 调用示例 若与默认拼装结果不同（人工维护），保留人工版本。
    """
    能力列表 = 提取能力列表(定义)
    既有条目表 = {}
    if isinstance(既有契约, dict) and isinstance(既有契约.get("能力契约"), list):
        既有条目表 = {条目.get("能力id"): 条目 for 条目 in 既有契约["能力契约"]
                  if isinstance(条目, dict) and 条目.get("能力id")}
    契约条目表 = []
    for 能力 in 能力列表:
        参数表 = []
        for 参数 in 能力.get("参数", []):
            参数表.append({
                "名称": 参数["名称"],
                "类型": 参数.get("类型", ""),
                "必填": 参数.get("必填", True),
                "默认值": 参数.get("默认值"),
                "说明": 参数.get("说明", ""),
            })
        默认示例 = {
            "能力id": 能力["能力id"],
            "参数": {参数["名称"]: 参数["默认值"]
                     for 参数 in 参数表 if 参数["默认值"] is not None},
        }
        既有条目 = 既有条目表.get(能力["能力id"], {})
        调用示例 = 既有条目.get("调用示例", 默认示例)
        if not isinstance(调用示例, dict) or 调用示例 == {}:
            调用示例 = 默认示例
        条目 = {
            "能力id": 能力["能力id"],
            "版本": 能力.get("版本", 契约版本),
            "说明": 能力.get("说明", ""),
            "参数": 参数表,
            "返回": 能力.get("返回", "结果"),
            "错误码": 能力.get("错误码", []),
            "调用示例": 调用示例,
            "行为": 能力.get("行为", {}),
            "提供者": 能力.get("提供者", {}),
        }
        for 可保留键 in 契约条目可保留键:
            if 可保留键 in 既有条目 and 可保留键 not in 条目:
                条目[可保留键] = 既有条目[可保留键]
        for 自定义键, 值 in 既有条目.items():
            if 自定义键 not in 契约条目自有键 and 自定义键 not in 条目:
                条目[自定义键] = 值
        契约条目表.append(条目)
    版本 = 契约版本
    return json.dumps({"契约版本": 版本, "能力契约": 契约条目表},
                      ensure_ascii=False, indent=1)


def 版本序(版本: str) -> tuple[int, ...]:
    """把 主.次.修 文本版本转成可比较元组；非法版本一律视为最低。"""
    段 = []
    for 片段 in str(版本).split("."):
        try:
            段.append(int(片段))
        except ValueError:
            return (0,)
    return tuple(段) or (0,)


def 生成包声明(定义: dict[str, Any], 包id: str, 包名称: str, 包类型: str,
               依赖: list[dict], 入口: str = "__init__.py") -> str:
    """生成 包声明.json 的能力清单（保留既有包级字段）。"""
    能力列表 = 提取能力列表(定义)
    声明 = {
        "包id": 包id,
        "名称": 包名称,
        "类型": 包类型,
        "版本": 定义.get("版本", "1.0.0"),
        "说明": 定义.get("说明", ""),
        "入口": 入口,
        "依赖": 依赖,
        "能力": [
            {
                "能力id": 能力["能力id"],
                "名称": 能力.get("中文名称", ""),
                "参数": [
                    {"名称": 参数["名称"], "类型": 参数.get("类型", "")}
                    for 参数 in 能力.get("参数", [])
                ],
                "返回": 能力.get("返回", "结果"),
                "说明": 能力.get("说明", ""),
            }
            for 能力 in 能力列表
        ],
    }
    return json.dumps(声明, ensure_ascii=False, indent=1)


def _默认值文本(值: Any) -> str:
    """把能力定义里的默认值写成 Python 字面量文本（中文工程口径：空值写 `无`）。"""
    if 值 is None:
        # 直接写 `None`（与全仓既有注册表同形）；平台没有 `无` 这个常量，
        # 写 `无` 会让注册入口在装配期 NameError（2026-09-18 实测踩到）。
        return "None"
    if 值 is True:
        return "真"
    if 值 is False:
        return "假"
    if isinstance(值, str):
        return json.dumps(值, ensure_ascii=False)
    if isinstance(值, (list, dict)):
        return json.dumps(值, ensure_ascii=False)
    return repr(值)


def 生成注册入口(定义: dict[str, Any], 包id: str, 实现模块: str) -> str:
    """生成 __init__.py 注册入口（含 注册能力 函数）。"""
    能力列表 = 提取能力列表(定义)
    导入行表 = []
    注册行表 = []
    __all__表 = []
    for 能力 in 能力列表:
        能力id = 能力["能力id"]
        函数名 = 能力id.split(".")[-1]
        # 参数表**必须带全四要素**（名称/类型/必填/默认值）。
        # ★ 原实现只输出名字（`参数=["任务", "项目根"]`），导致注册口径缺「类型/必填/默认值」，
        #   在发布门禁「契约声明一致（注册口径）」里沉淀成漏声明（2026-09-18 实测：
        #   全仓 42 条不一致，其中 23 条是新建模块因本行只发名字而漏声明）。
        #   类型/必填/默认值在 `能力定义.json` 里是**权威且齐全**的，生成器没有理由不产出它们。
        参数行 = ",\n".join(
            '            {"名称": %s, "类型": %s, "必填": %s, "默认值": %s}'
            % (json.dumps(str(参数.get("名称", "")), ensure_ascii=False),
               json.dumps(str(参数.get("类型", "")), ensure_ascii=False),
               "真" if 参数.get("必填") else "假",
               _默认值文本(参数.get("默认值")))
            for 参数 in 能力.get("参数", []))
        说明 = 能力.get("说明", "")
        返回 = 能力.get("返回", "结果")
        导入行表.append(f"from {实现模块} import {函数名}")
        __all__表.append(f'"{函数名}"')
        注册行表.append(f"""    注册表.注册(
        能力实现(
            能力id="{能力id}",
            包id="{包id}",
            实现函数={函数名},
            参数=[
{参数行}
            ],
            返回="{返回}",
            说明="{说明}",
        )
    )""")
    导入行 = "\n".join(导入行表)
    __all__ = ", ".join(__all__表)
    注册行 = "\n".join(注册行表)
    return f'''# {生成标记}
"""中文公开入口（由能力定义编译器生成）。"""

from __future__ import annotations

from 公共契约.能力契约.契约 import 能力实现
from 公共契约.基础类型.逻辑类型 import 真, 假

{导入行}

__all__ = [{__all__}, "注册能力"]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本库能力。"""
{注册行}
'''


def 生成搜索数据(定义: dict[str, Any]) -> str:
    """生成 能力搜索数据.json（能力列表数组）。"""
    能力列表 = 提取能力列表(定义)
    数据 = [
        {
            "能力id": 能力["能力id"],
            "名称": 能力.get("中文名称", ""),
            "说明": 能力.get("说明", ""),
            "版本": 能力.get("版本", ""),
            "参数": [参数["名称"] for 参数 in 能力.get("参数", [])],
            "返回": 能力.get("返回", "结果"),
            "错误码": 能力.get("错误码", []),
        }
        for 能力 in 能力列表
    ]
    return json.dumps(数据, ensure_ascii=False, indent=1)


def 生成Agent数据(定义: dict[str, Any], 包id: str) -> str:
    """生成 Agent查询数据.json（能力列表数组）。"""
    能力列表 = 提取能力列表(定义)
    数据 = [
        {
            "能力id": 能力["能力id"],
            "提供方": 包id,
            "输入": [参数["名称"] for 参数 in 能力.get("参数", [])],
            "返回": 能力.get("返回", "结果"),
            "是否异步": False,
            "是否流式": False,
            "是否有状态": 能力.get("行为", {}).get("副作用", "") not in ("纯计算", "只读"),
            "错误码": 能力.get("错误码", []),
        }
        for 能力 in 能力列表
    ]
    return json.dumps(数据, ensure_ascii=False, indent=1)


def 生成验证场景引用(定义: dict[str, Any], 包id: str) -> str | None:
    """不再生成 验证场景引用.json（v1 场景引用契约由能力作者手写维护）。

    旧实现输出的 {场景id,目标,范围} 三键格式缺 契约版本、不是合法 v1 引用
    条目，生成即把合法文件覆盖成非法文件并毁掉作者手写的富场景。本函数恒返回
    None，任何调用方都不得据此写盘；保留定义只为让「不生成」这一决定有单一
    落点，避免又有代码误生成该文件。
    """
    return None
def 生成完整性摘要(定义: dict[str, Any], 包id: str, 实现摘要: str,
                包目录: Path) -> str:
    """生成 完整性摘要.json —— **只委托唯一生成器**（形状唯一，不再自行追加字段）。

    历史：此处曾追加 能力数/能力清单/实现摘要/生成时间，造成与唯一生成器形状不一致；
    现统一由 `支持库/后端/组件规范支持库/实现/完整性摘要.py::生成完整性摘要` 产出全部字段。
    """
    from 支持库.后端.组件规范支持库 import 生成完整性摘要 as 生成文件清单摘要
    数据 = 生成文件清单摘要(
        包目录, 包id=包id, 版本=定义.get("版本", "1.0.0"))
    return json.dumps(数据, ensure_ascii=False, indent=1)


def _摘要(对象) -> str:
    return hashlib.sha256(
        json.dumps(对象, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def 编译能力定义(定义文件: Path, 包目录: Path, 包id: str, 包名称: str,
                包类型: str, 依赖: list[dict], 实现模块: str) -> 编译结果:
    """编译一个能力定义：生成全部契约派生物并写盘。"""
    结果 = 编译结果(包id=包id)
    try:
        定义 = 读取能力定义(定义文件)
    except json.JSONDecodeError as 错误:
        结果.问题列表.append(f"能力定义 JSON 解析失败: {错误}")
        return 结果
    问题列表 = 校验能力定义(定义)
    if 问题列表:
        结果.问题列表.extend(问题列表)
        return 结果
    # 输出目录：包目录/能力契约
    契约目录 = 包目录 / "能力契约"
    契约目录.mkdir(parents=True, exist_ok=True)
    # 1. 能力契约（S0 唯一聚合格式；生成物经唯一聚合契约解析器自检）
    契约路径 = 契约目录 / "参数契约.json"
    既有契约 = None
    if 契约路径.is_file():
        try:
            既有契约 = json.loads(契约路径.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            既有契约 = None
    契约文本 = 生成能力契约(定义, 既有契约)
    _写产物(契约路径, 契约文本, 结果)
    _契约数据, 契约问题 = 解析聚合契约(契约文本)
    if 契约问题:
        结果.问题列表.extend(f"生成契约: {问题}" for 问题 in 契约问题)
        return 结果
    # 2. 包声明能力清单（保留既有额外顶层字段，如 句柄超时秒）
    声明路径 = 包目录 / "包声明.json"
    声明文本 = 生成包声明(定义, 包id, 包名称, 包类型, 依赖)
    try:
        既有声明 = json.loads(声明路径.read_text(encoding="utf-8")) if 声明路径.is_file() else {}
        新声明 = json.loads(声明文本)
        if isinstance(既有声明, dict) and isinstance(新声明, dict):
            额外字段 = {键: 值 for 键, 值 in 既有声明.items() if 键 not in 新声明}
            if 额外字段:
                新声明.update(额外字段)
                声明文本 = json.dumps(新声明, ensure_ascii=False, indent=1)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    _写产物(声明路径, 声明文本, 结果)
    # 3. 注册入口
    入口路径 = 包目录 / "__init__.py"
    _写产物(入口路径, 生成注册入口(定义, 包id, 实现模块), 结果)
    # 4. 搜索数据 + Agent 数据
    数据目录 = 包目录 / "能力数据"
    数据目录.mkdir(parents=True, exist_ok=True)
    _写产物(数据目录 / "能力搜索数据.json", 生成搜索数据(定义), 结果)
    _写产物(数据目录 / "Agent查询数据.json", 生成Agent数据(定义, 包id), 结果)
    # 5. 验证场景引用：编译器不再生成（v1 契约由能力作者手写维护），
    #    避免把合法文件覆盖成非法旧格式。
    场景引用文本 = 生成验证场景引用(定义, 包id)
    if 场景引用文本 is not None:
        _写产物(包目录 / "验证场景引用.json", 场景引用文本, 结果)
    # 6. 完整性摘要
    _写产物(包目录 / "完整性摘要.json", 生成完整性摘要(定义, 包id, "实现", 包目录), 结果)
    return 结果


def _写产物(路径: Path, 内容: str, 结果: 编译结果) -> None:
    """写生成物；已存在且被手工修改（缺生成标记）则拒绝覆盖。

    __init__.py 特判：手写入口若含 注册能力 函数则视为合法（提供者实现
    复杂注册逻辑时不强制编译器覆盖），否则拒绝。
    """
    if 路径.is_file():
        try:
            既有 = 路径.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            既有 = ""
        if 路径.suffix in (".py", ".md") and 生成标记 not in 既有:
            if 路径.name == "__init__.py" and "def 注册能力" in 既有:
                return  # 手写入口含注册能力 → 合法，保留
            结果.问题列表.append(f"生成文件被手工修改: {路径.name}（缺少生成标记）")
            return
    路径.write_text(内容, encoding="utf-8")
    结果.产物列表.append({"类型": 路径.name, "路径": str(路径), "摘要": _摘要(内容)})


def 从包推导编译参数(包目录: Path) -> tuple[dict[str, Any], list[str]]:
    """**从包自身的既有事实推导全部编译参数**；返回 `(参数字典, 问题列表)`。

    **为什么必须由编译器自己推导（2026-09-18 修根）**：原 `编译能力定义` 要求调用方手传
    5 个元数据（包id / 包名称 / 包类型 / 依赖 / 实现模块）。这些**全部是包自己的既有事实**：
    前 4 个就在同目录 `包声明.json` 里，`实现模块` 就在同目录 `__init__.py` 的导入行里。
    让调用方「记得传对」的结果是**同一类错反复发生** —— 父会话实测连错两次：
    ① `实现模块` 少写一层，生成的 `__init__.py` 变成自我循环导入；
    ② `包类型` 写成 `模块`（装配器只认 支持库/基础模块/功能模块），装配器直接拒绝启动。
    按哲学「判据挂在产出点」：**能在产出点自己读出来的，就不要让调用方传**。

    推导规则（全部现场读取，读不到即如实报错、不猜默认值）：
    - `包id` / `包名称` / `包类型` / `依赖` ← 同目录 `包声明.json`（缺该文件即报错）；
    - `实现模块` ← 同目录 `__init__.py` 里 `from <模块> import` 的**实现模块**那一条。
      识别口径：优先匹配 `<包id>.实现.<子模块>`；无 `__init__.py` 或匹配不到时，
      退回「`实现/` 下唯一 .py」；仍定不下来则报错（多实现文件且入口未声明，不许猜）。
    """
    问题: list[str] = []
    声明路径 = 包目录 / "包声明.json"
    if not 声明路径.is_file():
        问题.append(f"缺少 包声明.json：无法推导 包id/名称/类型/依赖（{包目录}）")
        return {}, 问题
    try:
        声明 = json.loads(声明路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        问题.append(f"包声明.json 不可读: {错误}")
        return {}, 问题
    包id = str(声明.get("包id") or "").strip()
    包名称 = str(声明.get("名称") or "").strip()
    包类型 = str(声明.get("类型") or "").strip()
    for 字段名, 值 in (("包id", 包id), ("名称", 包名称), ("类型", 包类型)):
        if not 值:
            问题.append(f"包声明.json 缺少 {字段名}")
    if 问题:
        return {}, 问题
    # **包类型必须在产出点就校验**（2026-09-18 修根）：`包声明/声明.py` 的允许类型集合含「模块」，
    # 而装配器 `运行核心/加载器/生命周期管理/管理器.py:198` 只认 (支持库/基础模块/功能模块)
    # —— 两处权威不一致，照前者写的类型会在装配期才被拒绝（实测父会话就这么踩了一次）。
    # 这里以**装配器口径**为准就地拦下，报错同时给出该用哪个值。
    if 包类型 not in _装配器可装类型:
        提示 = ("「模块」不是可装配类型；模块类包按目录层写 `基础模块` 或 `功能模块`"
                if 包类型 == "模块" else "请改用可装配类型之一")
        问题.append(f"包声明.json 类型不可装配: {包类型!r}；{提示}"
                  f"（合法值：{'/'.join(_装配器可装类型)}）")
        return {}, 问题
    依赖 = 声明.get("依赖") if isinstance(声明.get("依赖"), list) else []
    实现模块, 实现问题 = _推导实现模块(包目录, 包id)
    if 实现问题:
        问题.append(实现问题)
        return {}, 问题
    return {"包id": 包id, "包名称": 包名称, "包类型": 包类型,
            "依赖": 依赖, "实现模块": 实现模块}, []


def _推导实现模块(包目录: Path, 包id: str) -> tuple[str, str]:
    """按「入口 `__init__.py` 的导入行 → 唯一实现文件」两级推导实现模块；失败返回 `("", 原因)`。

    **必须按入口导入行推导，不能一律取「实现/ 下唯一 .py」**：实测有包带子进程实现
    （`实现/提供者.py` + `实现/子进程解析.py`），取唯一文件会取错。
    """
    import re as _re
    入口 = 包目录 / "__init__.py"
    if 入口.is_file():
        try:
            源 = 入口.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            源 = ""
        # 匹配 `from <包id>.实现.<子模块> import ...`，以及相对更短的 `from ...实现.<子> import`
        模式 = _re.compile(r"^\s*from\s+([\w.]+)\s+import\s", _re.M)
        for 匹配 in 模式.finditer(源):
            模块 = 匹配.group(1)
            片段 = 模块.split(".")
            if "实现" in 片段 and 模块.startswith(包id + ".实现."):
                return 模块, ""
        for 匹配 in 模式.finditer(源):
            模块 = 匹配.group(1)
            片段 = 模块.split(".")
            if "实现" in 片段 and 片段[:2] == 包id.split(".")[:2]:
                return 模块, ""
    实现目录 = 包目录 / "实现"
    if 实现目录.is_dir():
        文件表 = sorted(f.name for f in 实现目录.iterdir()
                      if f.is_file() and f.suffix == ".py" and f.name != "__init__.py")
        if len(文件表) == 1:
            return f"{包id}.实现.{文件表[0][:-3]}", ""
        if len(文件表) > 1:
            return "", (f"无法推导实现模块：入口 __init__.py 未声明实现导入，"
                      f"而 实现/ 下有 {len(文件表)} 个 .py，不许猜（{包目录}）")
    return "", f"无法推导实现模块：既无入口声明导入，也无唯一实现文件（{包目录}）"


def 编译包(包目录: Path) -> 编译结果:
    """**按包目录一键编译**（参数全自动推导，调用方零元数据）。

    这是推荐入口：`编译包(Path("模块库/开工编排"))` 即可，不必手传 5 个元数据
    （手传是同类错误反复发生的根因，见 `从包推导编译参数` 的 docstring）。
    定义文件固定取 `<包目录>/能力定义.json`；参数由 `从包推导编译参数` 现场读取。
    """
    定义文件 = 包目录 / "能力定义.json"
    if not 定义文件.is_file():
        # **聚合父包**是合法形态：自身不注册能力（能力在子包里），故没有 能力定义.json 与 实现/。
        # 全仓实测 6 个（办公文档/大语言模型/数据操作/文件系统/系统核心/网络通信 支持库）。
        # 对它们「不编译」是**正确结果**，不是失败——报错会让调用方以为包有问题。
        子包 = [子 for 子 in sorted(包目录.iterdir())
               if 子.is_dir() and (子 / "包声明.json").is_file()]
        if 子包 and not (包目录 / "实现").is_dir():
            结果 = 编译结果(包id=str(包目录.name))
            结果.聚合父包 = True
            结果.子包数 = len(子包)
            return 结果
        结果 = 编译结果(包id=str(包目录.name))
        结果.问题列表.append(f"缺少 能力定义.json（{包目录}）")
        return 结果
    参数, 问题 = 从包推导编译参数(包目录)
    if 问题:
        结果 = 编译结果(包id=str(参数.get("包id") or ""))
        结果.问题列表.extend(问题)
        return 结果
    return 编译能力定义(定义文件=定义文件, 包目录=包目录,
                    包id=参数["包id"], 包名称=参数["包名称"], 包类型=参数["包类型"],
                    依赖=参数["依赖"], 实现模块=参数["实现模块"])


def 编译目录(定义目录: Path, 包目录映射: dict[Path, dict]) -> 编译结果:
    """编译目录内全部能力定义；包目录映射: {定义文件: 包元数据}。"""
    汇总 = 编译结果(包id="目录")
    for 定义文件, 元数据 in 包目录映射.items():
        单结果 = 编译能力定义(
            定义文件,
            元数据["包目录"],
            元数据["包id"],
            元数据["包名称"],
            元数据.get("包类型", "支持库"),
            元数据.get("依赖", []),
            元数据.get("实现模块", ""),
        )
        汇总.产物列表.extend(单结果.产物列表)
        汇总.问题列表.extend(单结果.问题列表)
    return 汇总


def 入口(argv: list[str] | None = None) -> int:
    """命令行入口（**fail-closed**）：必须显式给包目录，否则明确报用法并退出 2。

    **为什么必须加它（2026-09-18 实测假绿）**：本文件此前**没有 `__main__` 块**，
    于是 `python3.14 -m 开发工具.契约编译.能力定义编译器` 只是导入模块、**零输出、退出码 0**
    —— 而 `开发文档/规范/任务类型规范.json` 的「加新能力」判据里正好写着这条命令。
    子代理跑完看到 exit 0，会**以为编译成功了**（实际什么都没编译）。这属于哲学 14.4
    「文案给人看，错误码给机器判」的反面：静默成功比报错更危险。

    用法（一次只编译本次改动的包，禁止全量）：
        python3.14 -m 开发工具.契约编译.能力定义编译器 <包目录> [<包目录> …]
    """
    import sys as _sys
    参数 = list(_sys.argv[1:] if argv is None else argv)
    if not 参数:
        print("用法：python3.14 -m 开发工具.契约编译.能力定义编译器 <包目录> [<包目录> …]")
        print("说明：一次只编译本次改动的包（禁止全量）；聚合父包会如实报「聚合父包，无需编译」。")
        return 2
    有问题 = 0
    for 原始 in 参数:
        包目录 = Path(原始)
        if not 包目录.is_dir():
            print(f"✗ 不是目录: {原始}")
            有问题 += 1
            continue
        结果 = 编译包(包目录)
        父包 = bool(getattr(结果, "聚合父包", False))
        if 父包:
            print(f"[聚合父包] {原始}：无需编译（能力在 {结果.子包数} 个子包里）")
        elif 结果.问题列表:
            print(f"✗ {原始}：{len(结果.问题列表)} 个问题")
            for 问题 in 结果.问题列表:
                print(f"    {问题}")
            有问题 += 1
        else:
            print(f"✓ {原始}：生成 {len(结果.产物列表)} 份派生物，问题 0")
    if 有问题:
        print(f"共 {有问题} 个包失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(入口())
