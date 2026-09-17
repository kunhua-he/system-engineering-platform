"""九要素支持库模板生成器：能力清单 → 支持库包模板（骨架占位）+ 定向测试骨架。

产出：能力定义.json（单源）/包声明.json/能力契约/参数契约.json/依赖锁.json/
配置契约.json/权限契约.json/实现/{子进程入口,提供者}.py/验证场景引用.json/
说明/使用说明.md/__init__.py（中文公开入口+注册能力）/完整性摘要.json，
测试骨架放 测试中心/支持库/测试_<名称>.py。
防御：输出目录已存在文件拒绝覆盖（返回已存在清单）；包名/能力名含 ../ 或
绝对路径拒绝（路径逃逸）；能力名重复拒绝（同名能力）。
第三方只能声明为外部工具/受管，不得直接进入模板；第三方必须单独支持库。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

def _定位项目根() -> Path:
    """向上定位项目根：同时含 支持库 与 模块库 双目录的最近祖先（下沉后不再用 parents[2]）。"""
    for 祖先 in Path(__file__).resolve().parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
            return 祖先
    raise RuntimeError("无法定位项目根（找不到同时含 支持库 与 模块库 的祖先目录）")


# 项目根入 sys.path 必须在任何项目内导入之前（直接执行时项目根不在 path）。
_项目根 = _定位项目根()
if str(_项目根) not in sys.path:
    sys.path.insert(0, str(_项目根))

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.组件规范支持库.实现.完整性摘要 import 生成完整性摘要

系统根 = _定位项目根()
错误来源 = "支持库模板生成器"
默认错误码 = ["参数不合法", "超时", "提供者崩溃", "提供者不可用"]
默认行为 = {"修改输入": False, "幂等": True, "副作用": "只读", "排序稳定": True,
            "时区": "不涉及", "编码": "utf-8", "精度": "不涉及", "空值": "缺省",
            "输入上限": "骨架不设限", "超时可重试": True, "取消": "支持",
            "重试条件": "超时/提供者崩溃/提供者不可用", "事务边界": "无",
            "补偿动作": "无", "线程安全": True, "进程安全": True,
            "资源释放": "子进程自动回收", "错误码": "统一", "可重试性": "超时可重试"}


def _写(路径: Path, 内容: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(内容, encoding="utf-8")


def _转JSON文本(数据: dict) -> str:
    return json.dumps(数据, ensure_ascii=False, indent=2) + "\n"


def _渲染(模板: str, **替换: Any) -> str:
    for 键, 值 in 替换.items():
        模板 = 模板.replace(f"@@{键}@@", str(值))
    return 模板


def _规范能力(能力: dict) -> dict:
    """规范单条能力；自动补齐 超时秒 参数（保证测试骨架可测超时）。"""
    参数表 = list(能力.get("参数") or [])
    if not any(p.get("名称") == "超时秒" for p in 参数表):
        参数表.append({"名称": "超时秒", "类型": "双精度数型", "必填": False, "默认值": 60.0,
                      "说明": "子进程超时"})
    return {"能力id": str(能力["能力id"]),
            "中文名称": str(能力.get("中文名称") or str(能力["能力id"]).split(".")[-1]),
            "说明": str(能力.get("说明") or ""), "参数": 参数表,
            "返回": str(能力.get("返回") or "结果"),
            "错误码": list(能力.get("错误码") or 默认错误码),
            "行为": dict(能力.get("行为") or 默认行为)}


def 校验输入(输出目录: Path, 测试文件路径: Path, 包id: str, 名称: str,
            能力清单: list[dict]) -> tuple[str | None, list[str]]:
    """路径逃逸/非法名称/同名能力检查；返回 (错误码, 明细)，None 表示通过。

    输出目录/测试文件路径 为文件系统路径（绝对路径合法），不参与逃逸检查；
    逃逸检查针对 包id/包名称/能力id/参数名 等标识符类输入。
    """
    文本表 = [包id, 名称]
    文本表 += [c["能力id"] for c in 能力清单]
    文本表 += [p["名称"] for c in 能力清单 for p in c["参数"]]
    逃逸表 = [文本 for 文本 in 文本表 if 文本 and (".." in 文本 or 文本.startswith(("/", "\\")))]
    if 逃逸表:
        return "路径逃逸", 逃逸表
    if not 名称.isidentifier():
        return "参数不合法", [f"包名称不是合法标识符: {名称}"]
    能力id表 = [c["能力id"] for c in 能力清单]
    重复表 = sorted({i for i in 能力id表 if 能力id表.count(i) > 1})
    if 重复表:
        return "同名能力", [f"能力id 重复: {', '.join(重复表)}"]
    if not any(p.get("必填") for c in 能力清单 for p in c["参数"]):
        return "参数不合法", ["至少一个能力必须含必填参数（测试骨架依赖）"]
    return None, []


def _数据表(包id: str, 名称: str, 说明: str, 能力清单: list[dict],
            第三方说明: list[dict]) -> dict[str, str]:
    """九要素中全部 JSON 文件内容（路径 → 文本），不含完整性摘要。"""
    提供者 = {"默认": 包id, "版本": ">=1.0.0"}
    契约列表 = [{"能力id": c["能力id"], "参数": c["参数"], "返回": c["返回"],
                "错误码": c["错误码"], "说明": c["说明"], "行为": c["行为"],
                "提供者": 提供者} for c in 能力清单]
    定义列表 = [{"能力id": c["能力id"], "版本": "1.0.0", "中文名称": c["中文名称"],
                "说明": c["说明"], "参数": c["参数"], "返回": c["返回"],
                "错误码": c["错误码"], "行为": c["行为"], "提供者": 提供者} for c in 能力清单]
    声明列表 = [{"能力id": c["能力id"], "名称": c["中文名称"],
                "参数": [{"名称": p["名称"], "类型": p["类型"]} for p in c["参数"]],
                "返回": c["返回"], "说明": c["说明"]} for c in 能力清单]
    return {
        "能力定义.json": _转JSON文本({"包id": 包id, "版本": "1.0.0", "说明": 说明,
                               "能力列表": 定义列表}),
        "包声明.json": _转JSON文本({"包id": 包id, "名称": 名称, "类型": "支持库",
                             "版本": "1.0.0", "说明": 说明, "入口": "__init__.py",
                             "依赖": [], "能力": 声明列表}),
        "能力契约/参数契约.json": _转JSON文本({"能力契约": 契约列表}),
        "依赖锁.json": _转JSON文本({"包": [], "提供者id": 包id, "直接依赖": [], "依赖闭包": [],
                             "第三方说明": 第三方说明,
                             "环境": {"Python": "", "操作系统": "", "CPU": ""},
                             "生成时间": "",
                             "说明": "第三方不得直接进入模板；只能声明为外部工具/受管，第三方必须单独支持库"}),
        "配置契约.json": _转JSON文本({"配置需求": [], "说明": "骨架无配置需求，新增后由配置契约校验"}),
        "权限契约.json": _转JSON文本({"权限需求": [], "说明": "骨架无权限需求"}),
        "验证场景引用.json": _转JSON文本({"验证场景引用": [
            {"场景id": "支持库.资产验证", "目标": 包id, "范围": "资产"},
            {"场景id": "支持库.能力契约验证", "目标": 包id, "范围": "契约"}]}),
    }


def _参数默认(参数: dict) -> str:
    值 = 参数.get("默认值")
    if 值 is None:
        return "None"
    if isinstance(值, (int, float)) and not isinstance(值, bool):
        return repr(值)
    return repr(str(值))


def _公开函数源码(能力: dict) -> str:
    """生成单个能力的中文公开函数源码（签名/必填校验/执行任务）。"""
    参数表 = 能力["参数"]
    签名 = [p["名称"] if p.get("必填") else f"{p['名称']}={_参数默认(p)}" for p in 参数表]
    必填表 = [p["名称"] for p in 参数表 if p.get("必填")]
    校验 = ""
    if 必填表:
        校验 = (f"    if {' or '.join(f'{n} is None' for n in 必填表)}:\n"
                "        return _失败(\"参数不合法\", \"缺少必填参数\")\n")
    打包 = ", ".join(f'"{p["名称"]}": {p["名称"]}' for p in 参数表 if p["名称"] != "超时秒")
    超时 = next((p["名称"] for p in 参数表 if p["名称"] == "超时秒"), "60.0")
    return (f"def {能力['中文名称']}({', '.join(签名)}):\n"
            f'    """{能力["说明"]}"""\n' + 校验 +
            f'    return 执行任务("{能力["能力id"]}", {{{打包}}}, 超时秒={超时})\n')


def _示例值(类型: str) -> str:
    return {"文本": '"样例"', "整数": "1", "数字": "1", "字节": 'b"样例"',
            "布尔": "True"}.get(类型, '"样例"')


def _调用文本(能力: dict, *, 空调用: bool = False, 带超时: bool = False) -> str:
    调用 = [] if 空调用 else [
        f"{p['名称']}={_示例值(p.get('类型', '文本'))}" for p in 能力["参数"] if p.get("必填")]
    if 空调用:
        首必填 = next((p["名称"] for p in 能力["参数"] if p.get("必填")), None)
        调用 = [f"{首必填}=None"] if 首必填 else []
    if 带超时:
        调用.append("超时秒=0.2")
    return f"{能力['中文名称']}({', '.join(调用)})"


子进程入口模板 = '''"""@@名称@@ 骨架子进程入口：stdin 一行 JSON 请求，stdout 一行 JSON 响应。"""
from __future__ import annotations
import json, os, sys, time

能力操作表 = @@操作表@@


def _响应(成功, 值=None, 错误码="", 错误说明="") -> str:
    return json.dumps({"成功": 成功, "值": 值, "错误码": 错误码, "错误说明": 错误说明}, ensure_ascii=False)


def 主循环() -> int:
    if os.environ.get("@@名称@@_禁用库") == "1":
        print(_响应(False, 错误码="提供者不可用", 错误说明="@@名称@@ 被禁用")); return 0
    try:
        请求 = json.loads(sys.stdin.readline() or "")
    except json.JSONDecodeError:
        print(_响应(False, 错误码="参数不合法", 错误说明="请求不是 JSON")); return 0
    操作 = str(请求.get("操作") or "")
    if 操作 not in 能力操作表:
        print(_响应(False, 错误码="参数不合法", 错误说明=f"未知操作 {操作}")); return 0
    if os.environ.get("@@名称@@_测试超时") == "1":
        time.sleep(5)
    print(_响应(True, 值={"占位": 操作, "参数": 请求.get("参数", {})})); return 0


if __name__ == "__main__":
    主循环(); sys.stdout.flush(); os._exit(0)
'''

提供者模板 = '''"""@@名称@@ 主进程管理器：子进程协议 + 稳定错误码（骨架占位）。"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

系统根 = "@@系统根@@"
if 系统根 not in sys.path:
    sys.path.insert(0, 系统根)
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.有界IO import 受限通信
from 公共契约.运行时 import 平台适配, 进程终止

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
可重试错误码 = ("超时", "提供者崩溃", "提供者不可用")


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="@@名称@@", 可重试=错误码 in 可重试错误码)


def _终止进程组(进程, 宽限秒: float = 1.0) -> None:
    """超时/异常时回收整个进程组（终止 → 宽限 → 强杀 → 复查）。

    唯一实现是 公共契约.运行时.进程终止.强制结束子进程；本模板不生成任何
    平台判断，进程组启动标志与整组回收都由 公共契约.运行时 收口。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


def 执行任务(操作: str, 参数: dict, 超时秒: float = 60.0) -> 结果:
    """启动一次性骨架子进程执行任务；超时/崩溃/不可用逐类映射稳定错误码。"""
    try:
        进程 = subprocess.Popen([sys.executable, str(子进程入口路径)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **平台适配.子进程组启动标志(), env=dict(os.environ))
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动子进程: {错误}")
    try:
        输出, _, 已超时, 已超限 = 受限通信(
            进程,
            输入=(json.dumps({"操作": 操作, "参数": 参数}, ensure_ascii=False) + "\\n").encode(),
            超时秒=超时秒,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return _失败("超时", f"执行超过 {超时秒} 秒")
        if 已超限:
            return _失败("超出限制", "子进程输出超过上限")
    except OSError as 错误:
        return _失败("提供者不可用", f"子进程通信失败: {错误}")
    if 进程.returncode:
        return _失败("提供者崩溃", f"子进程异常退出（退出码 {进程.returncode}）")
    try:
        响应 = json.loads(输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("提供者崩溃", "子进程返回无效响应")
    if not 响应.get("成功"):
        return _失败(str(响应.get("错误码") or "提供者崩溃"), str(响应.get("错误说明") or "执行失败"))
    return 结果.成功结果(响应.get("值"))


@@公开函数块@@


def 注册能力(注册表) -> None:
    """向能力注册表注册本库能力（骨架占位）。"""
    from 公共契约.能力契约.契约 import 能力实现
    for 能力id, 函数, 参数名, 说明 in @@注册表条目@@:
        注册表.注册(能力实现(能力id=能力id, 包id="@@包id@@", 实现函数=函数,
                           参数=[{"名称": 名称, "类型": "字典型"} for 名称 in 参数名],
                           返回="结果型", 说明=说明))
'''

入口模板 = '''"""@@名称@@ 支持库模板中文公开入口（骨架占位实现）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力：@@能力表@@
"""
from __future__ import annotations

from .实现.提供者 import 注册能力
from .实现.提供者 import @@公开函数导入@@

__all__ = [@@公开函数引用@@]
'''

说明模板 = '''# @@名称@@ 使用说明

## 定位
@@说明@@

## 能力
| 能力id | 功能 | 返回 |
|---|---|---|
@@能力行@@

## 架构
主进程调用者 → @@名称@@ 公开函数 → 一次性子进程（实现/子进程入口.py）
→ stdin 一行 JSON 请求，stdout 一行 JSON 响应（骨架占位实现）。

## 生命周期
| 场景 | 行为 |
|---|---|
| 启动失败 | 提供者不可用（可重试） |
| 正常调用 | 成功结果（占位值） |
| 执行超时 | 超时（可重试） |
| 子进程崩溃/无效响应 | 提供者崩溃（可重试） |
| @@名称@@_禁用库=1 | 提供者不可用（测试注入） |

## 错误码
| 错误码 | 含义 |
|---|---|
| 参数不合法 | 必填参数缺失或请求不合法 |
| 超时 | 执行超过超时秒 |
| 提供者崩溃 | 子进程异常退出或无效响应 |
| 提供者不可用 | 子进程启动失败或被禁用 |

## 第三方依赖
@@第三方行@@
'''

测试模板 = '''"""@@名称@@ 模板测试骨架：合法调用/错误码/超时/提供者不可用（真实可跑）。"""
from __future__ import annotations
import os, sys, unittest
from unittest import mock

for 目录 in ("@@库父目录@@", "@@系统根@@"):
    if 目录 not in sys.path:
        sys.path.insert(0, 目录)

from @@名称@@ import @@公开函数导入@@
from 公共契约.基础类型.结果类型 import 结果


class Test@@类名@@(unittest.TestCase):
    """@@名称@@ 骨架测试。"""

    def test_合法调用(self):
        结果对象 = @@函数调用合法@@
        self.assertTrue(结果对象.成功, str(结果对象.错误说明))

    def test_参数不合法(self):
        结果对象 = @@函数调用空@@
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_超时(self):
        with mock.patch.dict(os.environ, {"@@名称@@_测试超时": "1"}):
            结果对象 = @@函数调用超时@@
        self.assertEqual(结果对象.错误码, "超时")

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"@@名称@@_禁用库": "1"}):
            结果对象 = @@函数调用合法@@
        self.assertEqual(结果对象.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
'''


def 生成支持库模板(*, 输出目录: str | Path, 包id: str, 名称: str, 能力清单: list[dict],
                   说明: str = "", 第三方说明: list[dict] | None = None,
                   测试文件路径: str | Path | None = None) -> 结果:
    """按能力清单生成九要素支持库包模板；失败返回结构化错误码。"""
    输出目录 = Path(输出目录)
    测试文件路径 = Path(测试文件路径 or 系统根 / "测试中心" / "支持库" / f"测试_{名称}.py")
    能力清单 = [_规范能力(c) for c in 能力清单]
    if not 能力清单:
        return 结果.失败("参数不合法", "能力清单不能为空", 来源=错误来源)
    错误码, 明细 = 校验输入(输出目录, 测试文件路径, 包id, 名称, 能力清单)
    if 错误码:
        return 结果.失败(错误码, f"{错误码}: {明细[0]}", 来源=错误来源, 详情={"明细": 明细})
    已存在清单 = [str(p.relative_to(输出目录)) for p in 输出目录.rglob("*") if p.is_file()]
    if 测试文件路径.is_file():
        已存在清单.append(f"测试文件:{测试文件路径}")
    if 已存在清单:
        return 结果.失败("文件已存在", "输出目录或测试文件已存在，拒绝覆盖",
                         来源=错误来源, 详情={"已存在": 已存在清单})
    第三方 = 第三方说明 or []
    能力id表 = [c["能力id"] for c in 能力清单]
    函数名表 = [c["中文名称"] for c in 能力清单]
    公开函数块 = "\n".join(_公开函数源码(c) for c in 能力清单)
    注册表条目 = repr(list(zip(能力id表, 函数名表,
                               [[p["名称"] for p in c["参数"]] for c in 能力清单],
                               [c["说明"] for c in 能力清单])))
    首能力 = 能力清单[0]
    空调用能力 = next((c for c in 能力清单 if any(p.get("必填") for p in c["参数"])), 首能力)
    能力行 = "\n".join(f"| {c['能力id']} | {c['说明']} | {c['返回']} |" for c in 能力清单)
    第三方行 = "\n".join(f"- {d.get('名称', '')} {d.get('版本', '')}（{d.get('模块名', '')}）："
                        f"{d.get('接入方式', '外部工具')}，{d.get('说明', '')}" for d in 第三方) or \
        "- 无。第三方必须单独支持库，模板内只允许声明为外部工具/受管"
    for 相对路径, 文本 in _数据表(包id, 名称, 说明, 能力清单, 第三方).items():
        _写(输出目录 / 相对路径, 文本)
    _写(输出目录 / "实现" / "__init__.py", '"""实现包标记。"""\n')
    _写(输出目录 / "实现" / "子进程入口.py", _渲染(
        子进程入口模板, 名称=名称, 操作表=repr(set(能力id表))))
    _写(输出目录 / "实现" / "提供者.py", _渲染(
        提供者模板, 名称=名称, 系统根=系统根, 包id=包id,
        公开函数块=公开函数块, 注册表条目=注册表条目))
    _写(输出目录 / "__init__.py", _渲染(
        入口模板, 名称=名称,
        能力表="、".join(f"{n}（{i}）" for n, i in zip(函数名表, 能力id表)),
        公开函数导入=", ".join(函数名表),
        公开函数引用=", ".join(f'"{n}"' for n in 函数名表 + ["注册能力"])))
    _写(输出目录 / "说明" / "使用说明.md", _渲染(
        说明模板, 名称=名称, 说明=说明, 能力行=能力行, 第三方行=第三方行))
    _写(测试文件路径, _渲染(
        测试模板, 名称=名称, 类名=名称, 库父目录=输出目录.parent, 系统根=系统根,
        公开函数导入=", ".join(函数名表),
        函数调用合法=_调用文本(首能力),
        函数调用空=_调用文本(空调用能力, 空调用=True),
        函数调用超时=_调用文本(首能力, 带超时=True)))
    _写(输出目录 / "完整性摘要.json", _转JSON文本(
        生成完整性摘要(输出目录, 包id=包id, 版本="1.0.0")))
    return 结果.成功结果({"包目录": str(输出目录), "测试文件": str(测试文件路径),
                          "能力数": len(能力清单)})


if __name__ == "__main__":
    print("支持库模板生成器：调用 生成支持库模板(输出目录=..., 包id=..., 名称=..., 能力清单=[...])")
