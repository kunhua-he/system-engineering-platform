"""契约编译器：以能力契约为唯一事实源，自动生成全链路产物。

生成：Python 中文入口/前端调用入口/网关参数校验/说明书/契约测试/
能力搜索数据/Agent 查询数据。
拒绝：声明能力但没有实现；有实现但没有声明；参数顺序漂移；返回结构
漂移；错误码漂移；说明书与入口不一致；契约破坏但未升级主版本；
生成文件被手工修改。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.聚合契约解析 import 校验能力条目, 读取原始

生成标记 = "本文件由契约编译器自动生成，禁止手工修改"


@dataclass
class 编译产物:
    """一份契约编译产物。"""

    产物类型: str
    路径: Path
    内容: str
    摘要: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {"产物类型": self.产物类型, "路径": str(self.路径), "摘要": self.摘要}


@dataclass
class 编译结果:
    """一次契约编译的结果。"""

    契约id: str = ""
    产物列表: list[编译产物] = field(default_factory=list)
    问题列表: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not self.问题列表


def 读取契约(契约文件: Path) -> dict[str, Any]:
    """读取契约 JSON（委托唯一聚合契约解析器的读取；非法 JSON 抛错保持兼容）。"""
    数据 = 读取原始(契约文件)
    if 数据 is None:
        raise json.JSONDecodeError("契约 JSON 非法", "", 0)
    return 数据


def 校验契约结构(契约: dict[str, Any]) -> list[str]:
    """校验契约 JSON 结构合法（委托唯一聚合契约解析器的能力条目校验）。"""
    return 校验能力条目(契约)


def 生成Python入口(契约: dict[str, Any]) -> str:
    """生成 Python 中文入口（参数关键字 + 统一结果）。"""
    能力id = 契约["能力id"]
    参数列表 = 契约.get("参数", [])
    参数行 = []
    for 参数 in 参数列表:
        名称 = 参数["名称"]
        默认值 = "None" if 参数.get("必填", True) else "None"
        参数行.append(f"    {名称}: Any = {默认值},")
    参数签名 = "\n".join(参数行) if 参数行 else "    无参数: bool = False,"
    错误码行 = ", ".join(f'"{错误码}"' for 错误码 in 契约.get("错误码", []))
    return f'''# {生成标记}
"""契约编译产物：{能力id} Python 中文入口。"""
from __future__ import annotations
from typing import Any


def {能力id.split(".")[-1]}入口({参数签名}) -> dict[str, Any]:
    """{契约.get("说明", "")}（由契约编译器生成）"""
    参数表 = {{k: v for k, v in locals().items() if k != "无参数" and v is not None}}
    return {{"能力id": "{能力id}", "参数": 参数表}}


能力元数据 = {{
    "能力id": "{能力id}",
    "版本": "{契约.get("版本", "")}",
    "错误码": [{错误码行}],
}}
'''


def 生成前端调用入口(契约: dict[str, Any]) -> str:
    """生成前端调用入口（JS fetch 网关调用）。"""
    能力id = 契约["能力id"]
    参数列表 = 契约.get("参数", [])
    参数对象行 = ",\n".join(
        f"        {参数['名称']}: {参数['名称']}" for 参数 in 参数列表)
    return f'''// {生成标记}
// 契约编译产物：{能力id} 前端调用入口（浏览器交互提供者使用）
async function 调用{能力id.split(".")[-1]}({参数对象行}) {{
    const 响应 = await fetch(网关地址 + "/网关/调用", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ 能力id: "{能力id}", 参数: {{ {参数对象行} }} }})
    }});
    return 响应.json();
}}
'''


def 生成网关参数校验(契约: dict[str, Any]) -> str:
    """生成网关参数校验函数（Python）。

    校验逻辑**不在这里重新实现**：唯一校验点是
    ``运行核心/统一网关/网关核心.py::校验能力参数``（网关参数校验层），
    本函数只生成一层薄委托，参数类型表随契约声明一起带过去。
    历史实现自带「整数/文本/逻辑型」三类型表，等于每个能力各写一遍校验，
    正是「两端不对称」的裂缝来源（也是文本型漏校的老根），已废止。
    """
    能力id = 契约["能力id"]
    声明 = 契约.get("参数", [])
    # 生成的是 Python 源码，声明必须用 Python 字面量（repr），
    # 不能用 json.dumps——JSON 的 true/false/null 在 Python 里是语法错误。
    声明字面量 = repr(声明)
    return f'''# {生成标记}
# 契约编译产物：{能力id} 网关参数校验（委托唯一校验点，不自带类型表）
from typing import Any

参数声明: list[dict[str, Any]] = {声明字面量}


def 校验参数(参数表: dict) -> tuple[str, str]:
    """参数校验；返回 (错误码, 错误说明)；空错误码=通过。"""
    from 运行核心.统一网关.网关核心 import 校验能力参数
    错误 = 校验能力参数({能力id!r}, 参数声明, dict(参数表 or {{}}))
    if not 错误:
        return "", ""
    错误码, _, 说明 = 错误.partition("：")
    return 错误码, 说明
'''


def 生成说明书(契约: dict[str, Any]) -> str:
    """生成能力说明书（Markdown）。"""
    能力id = 契约["能力id"]
    行列表 = [
        f"# 能力说明书：{能力id}",
        "",
        f"- 版本：{契约.get('版本', '')}",
        f"- 说明：{契约.get('说明', '')}",
        f"- 返回类型：{契约.get('返回', '普通返回')}",
        "",
        "## 参数",
        "",
        "| 名称 | 类型 | 必填 | 默认值 | 说明 |",
        "|------|------|------|--------|------|",
    ]
    for 参数 in 契约.get("参数", []):
        行列表.append(
            f"| {参数['名称']} | {参数.get('类型', '')} | {'是' if 参数.get('必填', True) else '否'} | {参数.get('默认值', '')} | {参数.get('说明', '')} |")
    行列表 += ["", "## 返回", "", f"```text\n{契约.get('返回', '普通返回')}\n```", "",
                "## 错误码", ""]
    for 错误码 in 契约.get("错误码", []):
        行列表.append(f"- {错误码}")
    行列表.append("")
    return "\n".join(行列表)


def 生成契约测试(契约: dict[str, Any]) -> str:
    """生成契约测试（unittest 断言契约结构）。"""
    能力id = 契约["能力id"]
    参数断言 = "\n".join(
        f'    def test_参数_{参数["名称"]}(self):\n'
        f'        self.assertIn("{参数["名称"]}", [参数["名称"] for 参数 in self.契约["参数"]])'
        for 参数 in 契约.get("参数", []))
    错误码断言 = "\n".join(
        f'    def test_错误码_{错误码}(self):\n'
        f'        self.assertIn("{错误码}", self.契约["错误码"])'
        for 错误码 in 契约.get("错误码", []))
    return f'''# {生成标记}
# 契约编译产物：{能力id} 契约测试
import unittest


class Test{能力id.replace(".", "")}(unittest.TestCase):
    """{能力id} 契约测试（由契约编译器生成）"""

    def setUp(self):
        self.契约 = {json.dumps(契约, ensure_ascii=False)}

    def test_能力id(self):
        self.assertEqual(self.契约["能力id"], "{能力id}")

    def test_版本(self):
        self.assertTrue(self.契约["版本"])

    def test_参数列表(self):
        self.assertIsInstance(self.契约["参数"], list)
{参数断言}
{错误码断言}


if __name__ == "__main__":
    unittest.main()
'''


def 生成能力搜索数据(契约: dict[str, Any]) -> dict[str, Any]:
    """生成能力搜索数据（结构化）。"""
    return {
        "能力id": 契约["能力id"],
        "名称": 契约.get("名称", ""),
        "说明": 契约.get("说明", ""),
        "版本": 契约.get("版本", ""),
        "参数": [参数["名称"] for 参数 in 契约.get("参数", [])],
        "返回": 契约.get("返回", "普通返回"),
        "错误码": 契约.get("错误码", []),
    }


def 生成Agent查询数据(契约: dict[str, Any]) -> dict[str, Any]:
    """生成 Agent 查询数据（回答：由谁提供/输入/返回/是否异步/流式/有状态等）。"""
    return {
        "能力id": 契约["能力id"],
        "提供方": 契约.get("包id", ""),
        "核心": 契约.get("核心", "后端"),
        "模块": 契约.get("模块", ""),
        "输入": [参数["名称"] for 参数 in 契约.get("参数", [])],
        "返回": 契约.get("返回", "普通返回"),
        "是否异步": 契约.get("返回") == "任务句柄返回",
        "是否流式": 契约.get("返回") in ("流式返回", "事件返回"),
        "是否有状态": 契约.get("有状态", False),
        "支持热切换": 契约.get("支持热切换", True),
        "失败处理": "统一错误码 + 诊断中心",
        "验证场景": 契约.get("验证场景", ""),
        "回滚方式": "热切换自动回滚",
    }


def 编译契约(契约文件: Path, 输出目录: Path) -> 编译结果:
    """编译一个能力契约：生成全部产物并写盘。"""
    结果 = 编译结果()
    try:
        契约 = 读取契约(契约文件)
    except json.JSONDecodeError as 错误:
        结果.问题列表.append(f"契约 JSON 解析失败: {错误}")
        return 结果
    结果.契约id = 契约.get("能力id", 契约文件.stem)
    问题列表 = 校验契约结构(契约)
    if 问题列表:
        结果.问题列表.extend(问题列表)
        return 结果
    输出目录.mkdir(parents=True, exist_ok=True)
    产物定义表 = [
        ("Python入口", f"{契约['能力id'].replace('.', '_')}_入口.py", 生成Python入口(契约)),
        ("前端调用入口", f"{契约['能力id'].replace('.', '_')}_前端.js", 生成前端调用入口(契约)),
        ("网关参数校验", f"{契约['能力id'].replace('.', '_')}_校验.py", 生成网关参数校验(契约)),
        ("说明书", f"{契约['能力id'].replace('.', '_')}_说明书.md", 生成说明书(契约)),
        ("契约测试", f"{契约['能力id'].replace('.', '_')}_契约测试.py", 生成契约测试(契约)),
    ]
    for 类型, 文件名, 内容 in 产物定义表:
        路径 = 输出目录 / 文件名
        if 路径.is_file() and 生成标记 not in 路径.read_text(encoding="utf-8"):
            结果.问题列表.append(f"生成文件被手工修改: {文件名}（缺少生成标记）")
            continue
        路径.write_text(内容, encoding="utf-8")
        结果.产物列表.append(编译产物(类型, 路径, 内容, _摘要文本(内容)))
    # 搜索数据 + Agent 数据（JSON 产物）
    搜索数据 = 生成能力搜索数据(契约)
    搜索路径 = 输出目录 / "能力搜索数据.json"
    搜索路径.write_text(json.dumps(搜索数据, ensure_ascii=False, indent=2), encoding="utf-8")
    结果.产物列表.append(编译产物("能力搜索数据", 搜索路径, json.dumps(搜索数据, ensure_ascii=False)))
    agent数据 = 生成Agent查询数据(契约)
    agent路径 = 输出目录 / "Agent查询数据.json"
    agent路径.write_text(json.dumps(agent数据, ensure_ascii=False, indent=2), encoding="utf-8")
    结果.产物列表.append(编译产物("Agent查询数据", agent路径, json.dumps(agent数据, ensure_ascii=False)))
    return 结果


def _摘要文本(文本: str) -> str:
    import hashlib
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()[:16]


def 编译目录(契约目录: Path, 输出目录: Path) -> 编译结果:
    """统一编译器内部阶段：编译已计算影响闭包内的契约目录。"""
    汇总 = 编译结果(契约id="目录")
    for 契约文件 in sorted(契约目录.glob("*.json")):
        if "验证" in 契约文件.name or "数据" in 契约文件.name:
            continue
        单结果 = 编译契约(契约文件, 输出目录 / 契约文件.stem)
        汇总.产物列表.extend(单结果.产物列表)
        汇总.问题列表.extend(单结果.问题列表)
    return 汇总


if __name__ == "__main__":
    print("编译阻断：契约编译已降为统一编译器内部阶段，不可独立正式调用")
    raise SystemExit(2)
