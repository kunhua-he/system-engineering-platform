"""唯一模块模板生成器：按 模块名/类型/能力清单/依赖能力清单 生成模块模板。

类型只允许 基础模块|功能模块；产出 聚合契约(S0.1)+包声明+实现（经
获取能力调用器().调用能力 骨架）+对称 __init__+说明+验证场景引用+完整性
摘要（委托唯一生成器）。实现不 import 支持库/提供者/第三方/核心；拒绝
覆盖/路径逃逸/能力重复/类型不合法/参数类型不合法/依赖无提供者。
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.版本规则.契约版本 import 契约版本
来源 = "模块模板生成器"
模块名正则 = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_]{1,40}$")
允许类型 = {"基础模块", "功能模块"}
# 只允许正式类型名（公共契约/基础类型/类型目录.md 冻结的 16 项）；本白名单会原样写进
# 新生成模块的 参数契约.json，用短名会把历史写法扩散到新包（真正的污染源）。
允许参数类型 = {"文本型", "整数型", "长整数型", "单精度数型", "双精度数型", "逻辑型",
                "字节型", "字节集型", "列表型", "字典型", "日期时间型", "资源引用型",
                "句柄型", "结果型", "空值型", "JSON值型"}
# 模板里 `聚合契约.契约版本` 必须等于平台唯一事实源（上面 import），不再写字面量：
# 原先写死 "1.0.0" 会让「生成的模块包」一落地就违反 测试中心/开发工具/测试_契约版本唯一。
# 新包/新能力各自的迭代版本仍从 1.0.0 起（见 契约版本.py 的边界说明），
# 但它们不是「契约版本」，故分别命名，避免与契约版本同名混淆。
新包默认版本 = "1.0.0"
新能力默认版本 = "1.0.0"
占位值表 = {"文本型": '""', "整数型": "0", "长整数型": "0", "单精度数型": "0.0",
           "双精度数型": "0.0", "逻辑型": "False", "字典型": "{}", "列表型": "[]",
           "资源引用型": "''", "空值型": "None", "字节型": "0", "字节集型": "b''",
           "日期时间型": "''", "句柄型": "0", "结果型": "{}", "JSON值型": "None"}

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

def 校验输入(模块名: str, 类型: str, 能力清单: list[dict], 依赖清单: list[dict],
            能力集: dict[str, str]) -> 结果:
    """校验 模块名/类型/能力名重复/参数类型/依赖无提供者（结构化错误码）。"""
    if not isinstance(模块名, str) or not 模块名.strip():
        return 结果.失败("参数不合法", f"模块名不能为空: {模块名!r}", 来源=来源)
    if any(符号 in 模块名 for 符号 in ("/", "\\", "..")):
        return 结果.失败("路径逃逸", f"模块名含路径成分: {模块名!r}", 来源=来源)
    if not 模块名正则.match(模块名):
        return 结果.失败("参数不合法", f"模块名只能含中文/字母/数字/下划线: {模块名!r}", 来源=来源)
    if 类型 not in 允许类型:
        return 结果.失败("类型不合法", f"类型只能为 {允许类型}: {类型!r}", 来源=来源)
    if not isinstance(能力清单, list) or not 能力清单:
        return 结果.失败("参数不合法", "能力清单不能为空", 来源=来源)
    已见: set[str] = set()
    for 条目 in 能力清单:
        if not isinstance(条目, dict) or not 条目.get("名称"):
            return 结果.失败("参数不合法", "能力清单条目必须含非空 名称", 来源=来源)
        能力id = f"{模块名}.{条目['名称']}"
        if 能力id in 已见:
            return 结果.失败("能力重复", f"能力名重复: {能力id}", 来源=来源)
        已见.add(能力id)
        for 参数 in 条目.get("参数", []):
            if not 参数.get("名称"):
                return 结果.失败("参数不合法", f"{能力id} 参数必须含非空 名称", 来源=来源)
            if 参数.get("类型", "文本型") not in 允许参数类型:
                return 结果.失败("参数类型不合法",
                                  f"{能力id} 参数类型只能是 {允许参数类型}: {参数.get('类型')!r}",
                                  来源=来源)
    for 条目 in 依赖清单 or []:
        if not isinstance(条目, dict) or not 条目.get("能力"):
            return 结果.失败("参数不合法", "依赖能力条目必须含非空 能力", 来源=来源)
        if 条目["能力"] not in 能力集:
            return 结果.失败("无提供者", f"依赖能力在支持库无提供者: {条目['能力']}", 来源=来源)
    return 结果.成功结果()

def _依赖能力id(条目: dict, 依赖清单: list[dict]) -> str:
    """能力转发目标：显式 依赖能力 优先，否则按同名末段匹配。"""
    if 条目.get("依赖能力"):
        return str(条目["依赖能力"])
    for 依赖 in 依赖清单:
        if 依赖["能力"].rsplit(".", 1)[-1] == 条目["名称"]:
            return str(依赖["能力"])
    return ""

def 实现函数块(模块名: str, 条目: dict, 依赖清单: list[dict]) -> str:
    """单个能力的实现骨架：参数装配 + 获取能力调用器().调用能力。"""
    名称 = 条目["名称"]
    参数表 = [{"名称": p["名称"], "类型": p.get("类型", "文本型"), "必填": bool(p.get("必填", True))}
             for p in 条目.get("参数", [])]
    签名 = ", ".join(f"{p['名称']}: {p['类型']}" + ("" if p["必填"] else " = None") for p in 参数表)
    请求参数 = "{" + ", ".join(f'"{p["名称"]}": {p["名称"]}' for p in 参数表) + "}"
    说明行 = f'    """{条目.get("说明") or 名称}。"""\n'
    依赖 = _依赖能力id(条目, 依赖清单)
    if 依赖:
        正文 = f'    return _调用("{依赖}", {请求参数})'
    else:
        正文 = f'    return 结果.失败("未实现", "请按依赖能力组合实现 {名称}", 来源="{模块名}")'
    return f"def {名称}({签名}) -> 结果:\n{说明行}{正文}"

def 模块包内容(模块名: str, 类型: str, 能力清单: list[dict], 依赖清单: list[dict]) -> dict[str, str]:
    """构造模块包文件内容（相对路径 → 文本）；完整性摘要另行写入。"""
    包id = f"模块库.{模块名}"
    能力id列表 = [f"{模块名}.{e['名称']}" for e in 能力清单]
    依赖声明 = [{"能力": e["能力"], "版本": e.get("版本", ">=1.0.0")} for e in 依赖清单]
    能力声明 = [{"能力id": 能力id, "名称": e["名称"], "参数": e.get("参数", []),
                "返回": e.get("返回", "结果"), "说明": e.get("说明", "")}
               for 能力id, e in zip(能力id列表, 能力清单)]
    包声明 = {"包id": 包id, "名称": 模块名, "类型": 类型, "版本": 新包默认版本,
              "说明": f"{模块名} 模块（{类型}）：组合支持库公开能力。", "入口": "__init__.py",
              "依赖": 依赖声明, "能力": 能力声明}
    聚合契约 = {"契约版本": 契约版本, "能力契约": [
        {"能力id": 能力id, "版本": 新能力默认版本, "说明": e.get("说明", ""),
         "参数": [{"名称": p["名称"], "类型": p.get("类型", "文本型"), "必填": bool(p.get("必填", True)),
                   "默认值": p.get("默认值"), "说明": p.get("说明", "")} for p in e.get("参数", [])],
         "返回": {"类型": e.get("返回", "结果"), "值结构": {}},
         "错误码": e.get("错误码", ["参数不合法"]),
         "调用示例": {"能力id": 能力id, "参数": {p["名称"]: None for p in e.get("参数", [])}}}
        for 能力id, e in zip(能力id列表, 能力清单)]}
    实现文本 = (f'"""{模块名} 模块（{类型}）：只经 获取能力调用器().调用能力 组合支持库能力。"""\n\n'
                "from __future__ import annotations\n\n"
                "from 公共契约.基础类型.结果类型 import 结果\n\n"
                f'来源 = "{模块名}"\n\n\n'
                "def _调用(能力id: str, 请求参数: dict) -> 结果:\n"
                '    """经唯一能力调用服务调用支持库能力；未装配时如实返回失败。"""\n'
                "    from 公共契约.能力契约.调用器 import 获取能力调用器\n"
                "    try:\n"
                f'        return 获取能力调用器().调用能力(能力id, 请求参数, 调用方="{模块名}")\n'
                "    except RuntimeError as 错误:\n"
                f'        return 结果.失败("提供者不可用", str(错误), 来源="{模块名}")\n\n\n'
                + "\n\n".join(实现函数块(模块名, e, 依赖清单) for e in 能力清单) + "\n")
    注册行 = "\n".join(
        f'        ("{能力id}", {e["名称"]}, {[p["名称"] for p in e.get("参数", [])]!r},'
        f' "{e.get("返回", "结果")}", "{e.get("说明", "")}"),'
        for 能力id, e in zip(能力id列表, 能力清单))
    入口文本 = (f'"""{模块名} 模块包级中文入口（{类型}）。"""\n\nfrom __future__ import annotations\n\n'
                + "\n".join(f"from {包id}.实现.{模块名} import {e['名称']}" for e in 能力清单)
                + f'\n\n__all__ = {[e["名称"] for e in 能力清单]!r}\n\n\n'
                "def 注册能力(注册表) -> None:\n    \"\"\"由模块加载器调用。\"\"\"\n"
                "    from 公共契约.能力契约.契约 import 能力实现\n\n"
                "    for 能力id, 函数, 参数名, 返回类型, 说明 in [\n" + 注册行 + "\n    ]:"
                f'\n        注册表.注册(能力实现(能力id=能力id, 包id="{包id}", 实现函数=函数,\n'
                '                         参数=[{"名称": 名称, "类型": "文本型"} for 名称 in 参数名],\n'
                "                         返回=返回类型, 说明=说明))\n")
    说明 = (f"# {模块名} 模块（{类型}）\n\n"
            "只经 获取能力调用器().调用能力 组合支持库公开能力，失败返回统一错误结构"
            "（错误码/说明/来源）。\n\n## 公开能力\n"
            + "\n".join(f"- {e['名称']}：{e.get('说明') or '组合支持库公开能力。'}" for e in 能力清单)
            + "\n\n错误码由支持库统一结构透传，来源标记为支持库或本模块。\n")
    return {
        "包声明.json": json.dumps(包声明, ensure_ascii=False, indent=2) + "\n",
        "能力契约/参数契约.json": json.dumps(聚合契约, ensure_ascii=False, indent=2) + "\n",
        "依赖契约/依赖契约.json": json.dumps({"依赖": 依赖声明}, ensure_ascii=False, indent=2) + "\n",
        "配置契约/配置契约.json": json.dumps({"默认超时秒": 30}, ensure_ascii=False, indent=2) + "\n",
        "权限契约/权限契约.json": json.dumps({id: {"允许用户": ["*"]} for id in 能力id列表},
                                           ensure_ascii=False, indent=2) + "\n",
        "验证场景引用.json": json.dumps(
            {"验证场景引用": [{"场景id": "模块.装配验证", "目标": 包id, "范围": "装配"}]},
            ensure_ascii=False, indent=2) + "\n",
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
        f"\n    def test_{e['名称']}_返回统一结果(self):\n        返回值 = {e['名称']}({', '.join(占位值表.get(p.get('类型', '文本'), 'None') for p in e.get('参数', []))})\n"
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

def _默认系统根() -> Path:
    """向上定位项目根：同时含 支持库 与 模块库 双目录的最近祖先。

    本包由 `开发工具/组件规范/` 下沉到支持库层，目录深度改变，不能再按
    `parents[2]` 硬编码定位（会落到 支持库/后端），故按双目录判据定位。
    """
    for 祖先 in Path(__file__).resolve().parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
            return 祖先
    raise RuntimeError("无法定位项目根（找不到同时含 支持库 与 模块库 的祖先目录）")


def 生成模块模板(*, 模块名: str, 类型: str = "基础模块", 能力清单: list[dict],
                 依赖能力清单: list[dict] | None = None, 系统根: Path | str | None = None,
                 模块库根: Path | str | None = None, 测试中心根: Path | str | None = None) -> 结果:
    """主入口：校验输入 → 生成模块包 + 测试骨架（已存在一律拒绝覆盖）。"""
    系统根 = Path(系统根 or _默认系统根())
    模块库根, 测试中心根 = Path(模块库根 or 系统根 / "模块库"), Path(测试中心根 or 系统根 / "测试中心")
    依赖清单 = 依赖能力清单 or []
    校验 = 校验输入(模块名, 类型, 能力清单, 依赖清单, 扫描支持库能力集(系统根))
    if not 校验.成功:
        return 校验
    模块目录 = (模块库根 / 模块名).resolve()
    骨架路径 = (测试中心根 / "模块库" / f"测试_{模块名}.py").resolve()
    if not (模块目录.is_relative_to(模块库根.resolve()) and 骨架路径.is_relative_to(测试中心根.resolve())):
        return 结果.失败("路径逃逸", f"目标路径逃出根目录: {模块名}", 来源=来源)
    if 模块目录.exists() or 骨架路径.exists():
        return 结果.失败("已存在", f"目标已存在，拒绝覆盖: {模块目录 if 模块目录.exists() else 骨架路径}", 来源=来源)
    文件表 = 模块包内容(模块名, 类型, 能力清单, 依赖清单)
    for 相对路径, 内容 in 文件表.items():
        (模块目录 / 相对路径).parent.mkdir(parents=True, exist_ok=True)
        (模块目录 / 相对路径).write_text(内容, encoding="utf-8")
    from 支持库.后端.组件规范支持库.实现.组件规范 import 生成完整性摘要
    生成完整性摘要(模块目录)
    骨架结果 = 生成测试骨架(模块名, 能力清单, 测试中心根)
    if not 骨架结果.成功:
        return 骨架结果
    return 结果.成功结果({"模块目录": str(模块目录), "测试骨架": str(骨架路径), "文件数": len(文件表) + 1})
