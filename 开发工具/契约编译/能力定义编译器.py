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
- 验证场景引用.json
- 完整性摘要.json

漂移规则：实现或契约变化后未重新生成必须失败；手工篡改生成物由漂移门禁阻断。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"

行为字段表 = [
    "修改输入", "幂等", "副作用", "排序稳定", "时区", "编码", "精度",
    "空值", "输入上限", "超时可重试", "取消", "重试条件",
    "事务边界", "补偿动作", "线程安全", "进程安全", "资源释放",
    "错误码", "可重试性",
]


@dataclass
class 编译结果:
    """一次能力定义编译结果。"""

    包id: str = ""
    产物列表: list[dict] = field(default_factory=list)
    问题列表: list[str] = field(default_factory=list)

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


def 校验能力定义(定义: dict[str, Any]) -> list[str]:
    """校验能力定义结构完整（含行为与提供者字段）。"""
    问题列表 = []
    if not 定义.get("包id"):
        问题列表.append("缺少 包id")
    能力列表 = 提取能力列表(定义)
    if not 能力列表:
        问题列表.append("缺少 能力列表（须含至少一个能力）")
        return 问题列表
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


def 生成能力契约(定义: dict[str, Any]) -> str:
    """生成 能力契约/参数契约.json（保持既有结构 + P5 行为/提供者字段）。"""
    能力列表 = 提取能力列表(定义)
    契约条目表 = []
    for 能力 in 能力列表:
        契约条目表.append({
            "能力id": 能力["能力id"],
            "参数": 能力.get("参数", []),
            "返回": 能力.get("返回", "结果"),
            "错误码": 能力.get("错误码", []),
            "说明": 能力.get("说明", ""),
            "行为": 能力.get("行为", {}),
            "提供者": 能力.get("提供者", {}),
        })
    return json.dumps({"能力契约": 契约条目表}, ensure_ascii=False, indent=1)


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


def 生成注册入口(定义: dict[str, Any], 包id: str, 实现模块: str) -> str:
    """生成 __init__.py 注册入口（含 注册能力 函数）。"""
    能力列表 = 提取能力列表(定义)
    导入行表 = []
    注册行表 = []
    __all__表 = []
    for 能力 in 能力列表:
        能力id = 能力["能力id"]
        函数名 = 能力id.split(".")[-1]
        参数行 = ", ".join(f'"{参数["名称"]}"' for 参数 in 能力.get("参数", []))
        说明 = 能力.get("说明", "")
        返回 = 能力.get("返回", "结果")
        导入行表.append(f"from {实现模块} import {函数名}")
        __all__表.append(f'"{函数名}"')
        注册行表.append(f"""    注册表.注册(
        能力实现(
            能力id="{能力id}",
            包id="{包id}",
            实现函数={函数名},
            参数=[{参数行}],
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


def 生成验证场景引用(定义: dict[str, Any], 包id: str) -> str:
    """生成 验证场景引用.json。"""
    数据 = {
        "验证场景引用": [
            {
                "场景id": "支持库.资产验证",
                "目标": 包id,
                "范围": "资产",
            },
            {
                "场景id": "支持库.能力契约验证",
                "目标": 包id,
                "范围": "契约",
            },
        ]
    }
    return json.dumps(数据, ensure_ascii=False, indent=1)


def 生成完整性摘要(定义: dict[str, Any], 包id: str, 实现摘要: str) -> str:
    """生成 完整性摘要.json。"""
    能力列表 = 提取能力列表(定义)
    数据 = {
        "包id": 包id,
        "版本": 定义.get("版本", "1.0.0"),
        "能力数": len(能力列表),
        "能力清单": [能力["能力id"] for 能力 in 能力列表],
        "实现摘要": 实现摘要,
        "能力定义摘要": _摘要(定义),
        "生成时间": "由能力定义编译器生成",
    }
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
    # 1. 能力契约
    契约路径 = 契约目录 / "参数契约.json"
    _写产物(契约路径, 生成能力契约(定义), 结果)
    # 2. 包声明能力清单
    声明路径 = 包目录 / "包声明.json"
    _写产物(声明路径, 生成包声明(定义, 包id, 包名称, 包类型, 依赖), 结果)
    # 3. 注册入口
    入口路径 = 包目录 / "__init__.py"
    _写产物(入口路径, 生成注册入口(定义, 包id, 实现模块), 结果)
    # 4. 搜索数据 + Agent 数据
    数据目录 = 包目录 / "能力数据"
    数据目录.mkdir(parents=True, exist_ok=True)
    _写产物(数据目录 / "能力搜索数据.json", 生成搜索数据(定义), 结果)
    _写产物(数据目录 / "Agent查询数据.json", 生成Agent数据(定义, 包id), 结果)
    # 5. 验证场景引用
    _写产物(包目录 / "验证场景引用.json", 生成验证场景引用(定义, 包id), 结果)
    # 6. 完整性摘要
    _写产物(包目录 / "完整性摘要.json", 生成完整性摘要(定义, 包id, "实现"), 结果)
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
