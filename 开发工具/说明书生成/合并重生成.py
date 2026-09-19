"""说明书合并式重生成：**让说明书由工具生成，而不是靠人工维护**。

华哥 2026-09-20 口述「能不能弄个工具，生成出来，而不是靠人工维护」。本工具就是它。

## 与两个现成生成器的分工

全仓说明书有**两套生成器血统**（登记在 `开发文档/项目证据/说明书白名单.json`），
本工具**按血统自动选生成器**——选错会把 73 行的文件"合并"成 32 行的残本（实测踩过）：

| 血统 | 生成器 | 辨识特征 |
|---|---|---|
| G1 | `开发工具.说明书生成.说明书生成器.生成单包说明书` | 含签名句 `- 权威分工：**调用口径以本文为准**` |
| G2 | `支持库.后端.组件规范支持库.实现.说明书生成器.生成说明书文本` | 首行 `# <包名> 使用说明` + 能力清单表（`能力id`/`名称`/`版本`/`返回`/`说明` 五列） |

- 两个生成器都**只从零产出、拒绝覆盖**已有文件——因为现存说明书里混着人工行。
- `契约编译.生成物一致性检查`：**只报告**哪份说明书与生成器产出不一致。
- 本工具：**修**。按**行级合并**把生成行刷新、把人工行原样留住，
  并在写盘前做「人工行零丢失」自检——不通过即**拒绝写盘**（fail-closed）。

## 行级合并口径（与人工行处置无关，纯按「字段键」配对）

账 = 按血统选中的生成器现场重算（源字段权威）；现 = 磁盘现行。
现-only 行与 账-only 行按「字段键」配对（键 = 首个全角冒号前的字段名，去尾部括号限定）：

| 情形 | 处置 |
|---|---|
| 无同键配对 | 人工行 → **保**（原样保留） |
| 现值 ⊊ 账值（源字段扩充） | 陈旧生成行 → **刷**（改为账值） |
| 值空/无 且下一非空行是缩进或围栏 | 人工块表头 → **保** |
| 其余（人工改写/超集） | 人工改写行 → **保**（丢账的同键对照行） |

**结构行纪律**（实测踩坑）：空行一律取现行（人工排版与人工围栏内的空行都在里面），
账的空行一律不落盘 —— 否则会把人工代码块里的空行吞掉。标题行 `# ` 恒取账。

## 为什么要留着白名单

`开发文档/项目证据/说明书白名单.json` 登记的是「哪份说明书含人工行」这一**血统事实**。
本工具**不改血统类别**：它只刷生成行、不动人工行，所以合并后白名单条目一条不撤
（该结论在 2026-09-19 G4/G9 收口时已验）。白名单的作用从「禁止生成器靠近」
转为「禁止**整文件覆盖**，允许**行级合并**」。

## 用法

```bash
python3.14 -m 开发工具.说明书生成.合并重生成              # 干跑：全仓扫描，只报告漂移与合并提案
python3.14 -m 开发工具.说明书生成.合并重生成 --包 模块库/能力目录
python3.14 -m 开发工具.说明书生成.合并重生成 --写盘        # 落盘（人工行零丢失校验全绿才写）
```

退出码：0 = 无漂移或（写盘后）全部合并成功；1 = 有漂移（干跑口径，供门禁判红）；
2 = 参数错误或**写盘被自检拦下**。
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.包声明.声明 import 从字典构建
from 开发工具.说明书生成.说明书生成器 import 生成单包说明书

说明书相对名 = ("说明", "使用说明.md")
白名单路径 = 系统根 / "开发文档" / "项目证据" / "说明书白名单.json"
空值集 = {"", "无", "（无）"}

#: G1 血统签名句（`说明书生成器` 的固定产出行）。
G1签名句 = "- 权威分工：**调用口径以本文为准**"
#: G2 血统签名（`组件规范支持库.说明书生成器` 的清单表头）。
G2表头 = "| 能力id | 名称 | 版本 | 返回 | 说明 |"


def _生成G1(包目录: Path) -> list[str]:
    """G1 账行：`说明书生成器.生成单包说明书`。"""
    声明 = json.loads((包目录 / "包声明.json").read_text(encoding="utf-8"))
    return 生成单包说明书(
        从字典构建(声明, 来源路径=str(包目录 / "包声明.json"))).strip().splitlines()


def _生成G2(包目录: Path) -> list[str]:
    """G2 账行：`组件规范支持库` 的说明书生成器（惰性导入，避免无谓依赖）。

    读的是**同一个包目录的声明侧**（能力定义/参数契约/搜索数据/验证引用）——
    与 G1 的输入源不同，所以两者产出形态不能用同一份账去比。
    """
    模块 = importlib.import_module(
        "支持库.后端.组件规范支持库.实现.说明书生成器")
    return 模块.生成说明书文本(包目录).strip().splitlines()


def 判定血统(现行文本: str) -> tuple[str, Callable[[Path], list[str]]]:
    """按现行文本辨认说明书血统，返回 (血统名, 账行生成函数)。

    **默认 G2**：G2 的形态（`# XX 使用说明` + 清单表）是全仓多数派（实测 21 份），
    且现行文本**不含** G1 签名句时更可能是 G2。有签名句才判 G1 ——
    两个特征都在时以 G1 签名句优先（它是显式声明，比形态推断硬）。
    """
    if G1签名句 in 现行文本:
        return "G1", _生成G1
    if G2表头 in 现行文本 or 现行文本.lstrip().startswith("# "):
        return "G2", _生成G2
    return "G1", _生成G1


def 包目录表(项目根: Path) -> list[Path]:
    """全部含 `说明/使用说明.md` 的正式包目录（排除缓存与制品）。"""
    表: list[Path] = []
    for 根名 in ("支持库", "模块库", "平台控制面"):
        根 = 项目根 / 根名
        if not 根.is_dir():
            continue
        for 声明路径 in 根.rglob("包声明.json"):
            相对 = 声明路径.relative_to(根)
            if "工程缓存" in 相对.parts or "__pycache__" in 相对.parts:
                continue
            包目录 = 声明路径.parent
            if (包目录 / 说明书相对名[0] / 说明书相对名[1]).is_file():
                表.append(包目录)
    return sorted(表, key=lambda 路径: 路径.as_posix())


def 读白名单() -> dict[str, dict]:
    """说明书白名单：相对路径 → 条目（缺失或非法即返回空表，不猜）。"""
    try:
        数据 = json.loads(白名单路径.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    表: dict[str, dict] = {}
    for 条 in 数据.get("白名单") or []:
        if isinstance(条, dict) and 条.get("路径"):
            表[str(条["路径"])] = 条
    return 表


def 字段键(行: str) -> tuple:
    """一行的「字段键」：用于把现-only 行与账-only 行配对。

    `- 字段：值` 取首个全角冒号前的字段名（去掉尾部括号限定，如 `版本（契约）` → `版本`）；
    小节行按标题文本整体配对；标题行只按「是标题」配对（标题恒取账）。
    """
    净 = 行.strip()
    if not 净:
        return ("空",)
    if 净.startswith("##"):
        return ("小节", 净)
    if 净.startswith("#"):
        return ("标题",)
    if 净.startswith("- "):
        核 = 净[2:]
        位 = 核.find("：")
        if 位 < 0:
            return ("独有", 核)
        名 = re.sub(r"[（(][^（()）]*[）)]$", "", 核[:位]).strip()
        return ("字段", 名)
    return ("独有", 净)


def 字段值(行: str) -> str:
    """`- 字段：值` 的值部分；非字段行返回整行。"""
    净 = 行.strip()
    if not 净.startswith("- "):
        return 净
    核 = 净[2:]
    位 = 核.find("：")
    return 核[位 + 1:] if 位 >= 0 else ""


def 合并说明书(现行文本: str, 账行表: list[str]) -> tuple[list[str], dict[str, Any]]:
    """行级合并：返回 (合并后行表, 统计)。**不改磁盘**，可反复干跑。"""
    现 = 现行文本.strip().splitlines()
    账 = list(账行表)
    账集, 现集 = set(账), set(现)
    账独有 = [行 for 行 in 账 if 行 not in 现集]
    账独有位置: dict[str, list[int]] = {}
    for 序, 行 in enumerate(账):
        if 行 not in 现集:
            账独有位置.setdefault(行, []).append(序)

    判定: dict[int, str] = {}
    配对: dict[int, str] = {}
    账待配 = list(账独有)
    for 序, 行 in enumerate(现):
        if 行 in 账集 or 行 == "":
            continue
        键 = 字段键(行)
        if 键[0] == "标题":
            判定[序] = "刷"
            continue
        同键 = [第 for 第, 候 in enumerate(账待配) if 字段键(候) == 键]
        if 键[0] == "字段" and 同键:
            候 = 账待配.pop(同键[0])
            值现, 值账 = 字段值(行), 字段值(候)
            下一非空 = ""
            for 探 in range(序 + 1, len(现)):
                if 现[探].strip():
                    下一非空 = 现[探]
                    break
            续写块 = 下一非空[:2] in ("  ", "\t") or 下一非空[:1] == "`"
            if 值现 in 空值集 and 续写块:
                判定[序], 配对[序] = "保", 候        # 人工块表头（下方还有缩进/围栏内容）
            elif 值现 == "" and 值账 and not 续写块:
                判定[序], 配对[序] = "刷", 候
            elif 值现 in 值账 and len(值现) < len(值账):
                判定[序], 配对[序] = "刷", 候        # 源字段扩充
            else:
                判定[序], 配对[序] = "保", 候        # 人工改写/超集
        else:
            判定[序] = "保"

    丢弃序 = set(位 for 位, 行 in enumerate(账) if 行 == "")
    for 序, 候 in 配对.items():
        if 判定[序] == "保":
            for 位 in 账独有位置.get(候, []):
                if 位 not in 丢弃序:
                    丢弃序.add(位)
                    break

    输出: list[str] = []
    指针盒 = [0]
    超配对: list[str] = []

    def 冲(到: int) -> None:
        while 指针盒[0] <= 到:
            if 指针盒[0] not in 丢弃序:
                输出.append(账[指针盒[0]])
            指针盒[0] += 1

    位置表: dict[str, list[int]] = {}
    for 序, 行 in enumerate(账):
        位置表.setdefault(行, []).append(序)
    已用: dict[str, int] = {}

    for 序, 行 in enumerate(现):
        if 行 == "":
            输出.append(行)                      # 空行一律取现行
            continue
        if 行 in 账集:
            候选 = 位置表[行]
            起点 = 已用.get(行, 0)
            while 起点 < len(候选) and 候选[起点] < 指针盒[0]:
                起点 += 1
            if 起点 < len(候选):
                冲(候选[起点])
                已用[行] = 起点 + 1
            else:
                超配对.append(行)
                输出.append(行)
            continue
        if 判定[序] == "保":
            输出.append(行)
        else:
            候 = 配对.get(序)
            if 候 is None and 字段键(行)[0] == "标题":
                候选标题 = [第 for 第, 候行 in enumerate(账待配) if 字段键(候行)[0] == "标题"]
                if 候选标题:
                    候 = 账待配.pop(候选标题[0])
                    配对[序] = 候
            if 候 is not None:
                for 位 in 账独有位置.get(候, []):
                    if 位 >= 指针盒[0] and 位 not in 丢弃序:
                        冲(位)
                        break
    冲(len(账) - 1)

    人工行 = [现[序] for 序 in sorted(判定) if 判定[序] == "保"]
    刷行 = [现[序] for 序 in sorted(判定) if 判定[序] == "刷"]
    丢行 = [账[位] for 位 in sorted(丢弃序) if 账[位] != ""]
    补行 = [行 for 行 in 输出 if 行 not in 现集]
    丢人头 = [行 for 行 in 人工行 if 行 not in set(输出)]
    必保 = {现[序] for 序 in range(len(现)) if 判定.get(序) != "刷"}
    意外丢 = sorted(行 for 行 in 必保 if 行 not in set(输出))

    结构异常: list[str] = []
    if 输出 and 输出[0] == "" and 现 and 现[0] != "":
        结构异常.append("合并后首行为空，而现行首行非空")
    if sum(1 for 行 in 输出 if 行 == "") > sum(1 for 行 in 现 if 行 == ""):
        结构异常.append("合并后空行数多于现行")
    if 输出 and 输出[-1] == "":
        结构异常.append("合并后末行为空")

    统计 = {
        "现总行": len(现), "账总行": len(账), "合并总行": len(输出),
        "人工行数": len(人工行), "刷行数": len(刷行),
        "丢弃账行数": len(丢行), "补入账行数": len(补行), "超配对": len(超配对),
        "有改动": 输出 != 现,
        "人工行零丢失": not 丢人头 and not 意外丢 and not 结构异常,
        "结构异常": 结构异常,
        "丢人工": 丢人头, "意外丢": 意外丢, "超配对行": 超配对,
        "人工行": 人工行, "刷行": 刷行, "补行": 补行,
    }
    return 输出, 统计


def 合并单包(包目录: Path, 项目根: Path, 白名单: dict[str, dict]) -> dict[str, Any]:
    """算一份说明书的合并提案（**不写盘**）。返回提案 + 统计 + 差异文本。"""
    说明路径 = 包目录 / 说明书相对名[0] / 说明书相对名[1]
    说明相对 = 说明路径.relative_to(项目根).as_posix()
    包相对 = 包目录.relative_to(项目根).as_posix()
    结果: dict[str, Any] = {"包": 包相对, "路径": 说明相对, "可合并": False, "问题": ""}
    try:
        现行文本 = 说明路径.read_text(encoding="utf-8")
    except (OSError, ValueError) as 错误:
        结果["问题"] = f"读取失败: {错误}"
        return 结果
    血统, 账生成器 = 判定血统(现行文本)
    try:
        账行表 = 账生成器(包目录)
    except (OSError, ValueError, ImportError, AttributeError) as 错误:
        结果["问题"] = f"{血统} 账重算失败: {错误}"
        return 结果
    # **血统选错的哨兵**：账行数远小于现行时，几乎一定是选错了生成器
    # （实测：G2 的文件用 G1 的账去比，73 行的文件会被"合并"成 32 行残本）。
    # 宁可如实报错让调用方指定血统，也不能安静地产出一份残本。
    现行行数 = len(现行文本.strip().splitlines())
    if 现行行数 >= 20 and len(账行表) < 现行行数 // 2:
        结果["问题"] = (f"账行数 {len(账行表)} 远小于现行 {现行行数} 行："
                    f"疑似血统判错（判为 {血统}）；请核对生成器或手工指定血统")
        return 结果
    输出行表, 统计 = 合并说明书(现行文本, 账行表)
    差 = list(difflib.unified_diff(
        现行文本.strip().splitlines(), 输出行表,
        fromfile="现行", tofile="合并", lineterm="", n=1))
    结果.update({
        "可合并": True,
        "血统": 血统,
        "统计": 统计,
        "提案": "\n".join(输出行表) + "\n",
        "差异": 差,
        "白名单类别": (白名单.get(说明相对) or {}).get("类别", ""),
    })
    return 结果


def 主函数(argv: list[str] | None = None) -> int:
    解析器 = argparse.ArgumentParser(
        description="说明书合并式重生成：刷生成行、保人工行；写盘前自检人工行零丢失")
    解析器.add_argument("--包", action="append", default=[],
                     help="只处理该包目录（可多次）；缺省 = 全仓扫描")
    解析器.add_argument("--全部", action="store_true", help="全仓扫描（默认即为全仓）")
    解析器.add_argument("--写盘", action="store_true",
                     help="落盘（人工行零丢失校验全绿才写；缺省干跑）")
    解析器.add_argument("--详单", action="store_true", help="打印逐行 diff")
    参数 = 解析器.parse_args(argv)

    白名单 = 读白名单()
    if 参数.包:
        目标表 = []
        for 原文 in 参数.包:
            包目录 = (系统根 / 原文) if not Path(原文).is_absolute() else Path(原文)
            if not 包目录.is_dir():
                print(f"✗ 不是目录: {原文}")
                return 2
            目标表.append(包目录)
    else:
        目标表 = 包目录表(系统根)
    if not 目标表:
        print("✗ 未扫描到任何含 说明/使用说明.md 的包")
        return 2

    提案表: dict[str, dict] = {}
    for 包目录 in 目标表:
        单 = 合并单包(包目录, 系统根, 白名单)
        if 单.get("可合并"):
            提案表[单["路径"]] = 单
        else:
            print(f"  － {单['包']}: {单['问题']}")

    有改动 = {路径: 单 for 路径, 单 in 提案表.items() if 单["统计"]["有改动"]}
    零丢失坏 = {路径: 单 for 路径, 单 in 提案表.items() if not 单["统计"]["人工行零丢失"]}

    for 路径, 单 in sorted(有改动.items()):
        统计 = 单["统计"]
        类别 = 单["白名单类别"] or "（不在白名单）"
        print(f"\n═══ {单['包']} ═══  血统={单['血统']} 白名单类别={类别}")
        print(f"  现行 {统计['现总行']} 行 / 账 {统计['账总行']} 行 / 合并 {统计['合并总行']} 行；"
              f"人工 {统计['人工行数']} 保、{统计['刷行数']} 刷、"
              f"丢账 {统计['丢弃账行数']}、补账 {统计['补入账行数']}；"
              f"人工行零丢失={统计['人工行零丢失']}")
        for 行 in 统计["刷行"]:
            print(f"    [刷] {行}")
        for 行 in 统计["补行"]:
            print(f"    [补账] {行}")
        if 参数.详单:
            for 行 in 单["差异"]:
                print(f"      {行}")

    print(f"\n扫描 {len(提案表)} 份说明书；有漂移 {len(有改动)} 份；"
          f"人工行零丢失未过 {len(零丢失坏)} 份")

    if 零丢失坏:
        print("⇒ 拒绝写盘：下列说明书的人工行零丢失校验未过（合并算法有缺陷，先修算法）")
        for 路径 in sorted(零丢失坏):
            print(f"    ✗ {路径}: {零丢失坏[路径]['统计']['结构异常'] or '有人工行被丢'}")
        return 2

    if not 参数.写盘:
        if 有改动:
            print("⇒ 干跑（未写盘）。确认无误后加 --写盘 落盘")
            return 1
        print("⇒ 全部已是固定点（零漂移）")
        return 0

    for 路径, 单 in sorted(有改动.items()):
        (系统根 / 路径).write_text(单["提案"], encoding="utf-8")
        print(f"    ✓ 已写盘 {路径}（人工行 {单['统计']['人工行数']} 行原样保留）")
    print(f"⇒ 已写盘 {len(有改动)} 份；{len(提案表) - len(有改动)} 份零漂移未动")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
