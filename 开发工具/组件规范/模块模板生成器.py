"""模块模板生成器：按 模块名/能力清单/依赖能力清单 生成九要素模块模板。
产出九要素+定向测试骨架；实现只 import 支持库公开入口；摘要委托唯一生成器；拒绝覆盖/路径逃逸/能力重复/依赖无提供者。
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from 公共契约.基础类型.结果类型 import 结果
来源 = "模块模板生成器"
模块名正则 = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_]{1,40}$")
占位值表 = {"文本": '""', "整数": "0", "布尔": "False"}

def 扫描支持库能力集(系统根: Path) -> dict[str, str]:
    """扫描支持库公开能力：能力id → 提供方包id（多提供方优先 后端 包）。"""
    能力表: dict[str, str] = {}
    for 声明路径 in (系统根 / "支持库").rglob("包声明.json"):
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if 声明.get("类型") == "支持库":
            for 能力 in 声明.get("能力") or []:
                能力id = str(能力.get("能力id", ""))
                if 能力id and (能力id not in 能力表 or 声明.get("包id", "").startswith("支持库.后端.")):
                    能力表[能力id] = str(声明.get("包id", ""))
    return 能力表

def 校验输入(模块名: str, 能力清单: list[dict], 依赖清单: list[dict], 能力集: dict[str, str]) -> 结果:
    """校验模块名/能力名重复/依赖无提供者（失败返回结构化错误码）。"""
    if not isinstance(模块名, str) or not 模块名.strip():
        return 结果.失败("参数不合法", f"模块名不能为空: {模块名!r}", 来源=来源)
    if any(符号 in 模块名 for 符号 in ("/", "\\", "..")):
        return 结果.失败("路径逃逸", f"模块名含路径成分: {模块名!r}", 来源=来源)
    if not 模块名正则.match(模块名):
        return 结果.失败("参数不合法", f"模块名只能含中文/字母/数字/下划线: {模块名!r}", 来源=来源)
    已见: set[str] = set()
    for 条目 in 能力清单 or []:
        if not isinstance(条目, dict) or not 条目.get("名称"):
            return 结果.失败("参数不合法", "能力清单条目必须含非空 名称", 来源=来源)
        能力id = f"{模块名}.{条目['名称']}"
        if 能力id in 已见:
            return 结果.失败("能力重复", f"能力名重复: {能力id}", 来源=来源)
        已见.add(能力id)
    if not 已见:
        return 结果.失败("参数不合法", "能力清单不能为空", 来源=来源)
    for 条目 in 依赖清单 or []:
        if not isinstance(条目, dict) or not 条目.get("能力"):
            return 结果.失败("参数不合法", "依赖能力条目必须含非空 能力", 来源=来源)
        if 条目["能力"] not in 能力集:
            return 结果.失败("无提供者", f"依赖能力在支持库无提供者: {条目['能力']}", 来源=来源)
    return 结果.成功结果()

def 模块包内容(模块名: str, 能力清单: list[dict], 依赖清单: list[dict], 能力集: dict[str, str]) -> dict[str, str]:
    """构造九要素文件内容（相对路径 → 文本），完整性摘要由唯一生成器另行写入。"""
    包id = f"模块库.{模块名}"
    能力id列表 = [f"{模块名}.{e['名称']}" for e in 能力清单]
    依赖声明 = [{"能力": e["能力"], "版本": e.get("版本", ">=1.0.0")} for e in 依赖清单]
    能力声明 = [{"能力id": 能力id, "名称": e["名称"], "参数": e.get("参数", []),
                "返回": e.get("返回", "结果"), "说明": e.get("说明", "")}
               for 能力id, e in zip(能力id列表, 能力清单)]
    包声明 = {"包id": 包id, "名称": 模块名, "类型": "模块", "版本": "1.0.0",
              "说明": f"{模块名} 模块：组合支持库公开能力。", "入口": "__init__.py",
              "依赖": 依赖声明, "能力": 能力声明}
    提供方函数表: dict[str, list[str]] = {}
    for e in 依赖清单:
        提供方函数表.setdefault(能力集[e["能力"]], []).append(e["能力"].rsplit(".", 1)[-1])
    import行 = "\n".join(f"from {提供方} import " + ", ".join(f"{函数} as _{函数}" for 函数 in 函数列表)
                         for 提供方, 函数列表 in 提供方函数表.items())
    转发名表 = {e["能力"].rsplit(".", 1)[-1] for e in 依赖清单}
    参数名表 = [[p["名称"] for p in e.get("参数", [])] for e in 能力清单]
    函数块 = "\n\n".join(
        f"def {e['名称']}({', '.join(参数)}) -> 结果:\n    "
        + (f"return _{e['名称']}({', '.join(参数)})" if e["名称"] in 转发名表 else f"return 结果.失败('未实现', '请按依赖能力组合实现 {e['名称']}')") for e, 参数 in zip(能力清单, 参数名表))
    实现文本 = (f'"""{模块名} 模块：只经支持库公开入口组合，不深入实现目录。"""\n\nfrom __future__ import annotations\n\n'
                "from 公共契约.基础类型.结果类型 import 结果\n"
                + (import行 + "\n" if import行 else "") + "\n" + 函数块 + "\n")
    注册行 = "\n".join(f'        ("{模块名}.{e["名称"]}", {e["名称"]}, {参数!r}, "{e.get("返回", "结果")}", "{e.get("说明", "")}"),'
                       for e, 参数 in zip(能力清单, 参数名表))
    入口文本 = (f'"""{模块名} 模块包级中文入口。"""\n\nfrom __future__ import annotations\n\n'
                + "\n".join(f"from {包id}.实现.{模块名} import {e['名称']}" for e in 能力清单)
                + f'\n\n__all__ = {[e["名称"] for e in 能力清单]!r}\n\n\n'
                'def 注册能力(注册表) -> None:\n    """由模块加载器调用。"""\n'
                "    from 公共契约.能力契约.契约 import 能力实现\n\n    for 能力id, 函数, 参数名, 返回类型, 说明 in [\n" + 注册行 + "\n    ]:"
                f'\n        注册表.注册(能力实现(能力id=能力id, 包id="{包id}", 实现函数=函数,\n'
                '                         参数=[{"名称": 名称, "类型": "任意"} for 名称 in 参数名],\n'
                "                         返回=返回类型, 说明=说明))\n")
    说明 = (f"# {模块名} 模块\n\n组合支持库公开入口，失败返回统一错误结构（错误码/说明/来源）。\n\n## 公开能力\n"
            + "\n".join(f"- {e['名称']}：{e.get('说明') or '组合支持库公开能力。'}" for e in 能力清单)
            + "\n\n错误码由支持库统一结构透传，来源标记为支持库或本模块。\n")
    return {
        "包声明.json": json.dumps(包声明, ensure_ascii=False, indent=2) + "\n",
        "能力契约/参数契约.json": json.dumps(
            {"能力契约": [{"能力id": id, "参数": e.get("参数", []), "返回": e.get("返回", "结果")} for id, e in zip(能力id列表, 能力清单)]},
            ensure_ascii=False, indent=2) + "\n",
        "依赖契约/依赖契约.json": json.dumps({"依赖": 依赖声明}, ensure_ascii=False, indent=2) + "\n",
        "配置契约/配置契约.json": json.dumps({"默认超时秒": 30}, ensure_ascii=False, indent=2) + "\n",
        "权限契约/权限契约.json": json.dumps({id: {"允许用户": ["*"]} for id in 能力id列表}, ensure_ascii=False, indent=2) + "\n",
        "验证场景引用.json": json.dumps({"验证场景引用": [{"场景id": "模块.装配验证", "目标": 包id, "范围": "装配"}]}, ensure_ascii=False, indent=2) + "\n",
        "实现/" + 模块名 + ".py": 实现文本,
        "__init__.py": 入口文本,
        "说明/使用说明.md": 说明,
    }

def 生成测试骨架(模块名: str, 能力清单: list[dict], 测试中心根: Path) -> 结果:
    """生成定向测试骨架（装配冒烟：入口可导入/注册齐全/返回统一结果）。"""
    骨架路径 = (测试中心根 / "模块库" / f"测试_{模块名}.py").resolve()
    if 骨架路径.exists():
        return 结果.失败("已存在", f"测试骨架已存在，拒绝覆盖: {骨架路径}", 来源=来源)
    名称列表 = [e["名称"] for e in 能力清单]
    能力id列表 = [f"{模块名}.{名称}" for 名称 in 名称列表]
    能力测试块 = "\n".join(
        f"\n    def test_{e['名称']}_返回统一结果(self):\n        返回值 = {e['名称']}({', '.join(占位值表.get(p.get('类型', '任意'), 'None') for p in e.get('参数', []))})\n"
        "        self.assertIsInstance(返回值, 结果)" for e in 能力清单)
    文本 = (f'"""{模块名} 模块定向测试骨架（模块模板生成器产出，按需补充真实场景）。"""\n\n'
            "from __future__ import annotations\n\nimport sys\nimport unittest\nfrom pathlib import Path\n\n"
            "系统根 = Path(__file__).resolve().parents[2]\n"
            "if str(系统根) not in sys.path:\n    sys.path.insert(0, str(系统根))\n\n"
            "from 公共契约.基础类型.结果类型 import 结果\n"
            f"from 模块库.{模块名} import " + ", ".join(名称列表) + ", 注册能力\n\n"
            f"class Test{模块名}模块(unittest.TestCase):\n"
            "    \"\"\"装配冒烟：公开入口可导入、注册能力齐全、调用返回统一结果。\"\"\"\n"
            f"\n    def test_公开入口可导入(self):\n        for 能力名 in {名称列表!r}:\n"
            "            self.assertTrue(callable(globals()[能力名]), f\"{能力名} 未从公开入口导出\")\n"
            "\n    def test_注册能力齐全(self):\n"
            "        from 公共契约.能力契约.契约 import 能力注册表\n"
            "        注册表 = 能力注册表()\n        注册能力(注册表)\n"
            f"        for 能力id in {能力id列表!r}:\n"
            "            self.assertIn(能力id, 注册表.能力id列表)\n" + 能力测试块
            + '\n\n\nif __name__ == "__main__":\n    unittest.main()\n')
    骨架路径.parent.mkdir(parents=True, exist_ok=True)
    骨架路径.write_text(文本, encoding="utf-8")
    return 结果.成功结果({"测试骨架": str(骨架路径)})

def 生成模块模板(*, 模块名: str, 能力清单: list[dict], 依赖能力清单: list[dict] | None = None,
                 系统根: Path | str | None = None, 模块库根: Path | str | None = None,
                 测试中心根: Path | str | None = None) -> 结果:
    """主入口：校验输入 → 生成九要素模块包 + 测试骨架（已存在一律拒绝覆盖）。"""
    系统根 = Path(系统根 or Path(__file__).resolve().parents[2])
    模块库根, 测试中心根 = Path(模块库根 or 系统根 / "模块库"), Path(测试中心根 or 系统根 / "测试中心")
    依赖清单 = 依赖能力清单 or []
    能力集 = 扫描支持库能力集(系统根)
    校验 = 校验输入(模块名, 能力清单, 依赖清单, 能力集)
    if not 校验.成功:
        return 校验
    模块目录 = (模块库根 / 模块名).resolve()
    骨架路径 = (测试中心根 / "模块库" / f"测试_{模块名}.py").resolve()
    if not (模块目录.is_relative_to(模块库根.resolve()) and 骨架路径.is_relative_to(测试中心根.resolve())):
        return 结果.失败("路径逃逸", f"目标路径逃出根目录: {模块名}", 来源=来源)
    if 模块目录.exists() or 骨架路径.exists():
        return 结果.失败("已存在", f"目标已存在，拒绝覆盖: {模块目录 if 模块目录.exists() else 骨架路径}", 来源=来源)
    文件表 = 模块包内容(模块名, 能力清单, 依赖清单, 能力集)
    for 相对路径, 内容 in 文件表.items():
        (模块目录 / 相对路径).parent.mkdir(parents=True, exist_ok=True)
        (模块目录 / 相对路径).write_text(内容, encoding="utf-8")
    from 开发工具.组件规范.组件规范 import 生成完整性摘要
    生成完整性摘要(模块目录)
    骨架结果 = 生成测试骨架(模块名, 能力清单, 测试中心根)
    if not 骨架结果.成功:
        return 骨架结果
    return 结果.成功结果({"模块目录": str(模块目录), "测试骨架": str(骨架路径), "文件数": len(文件表) + 1})
