"""门面核验：拆文件前后，**对外门面是否逐字未变**（B1 拆上帝文件的安全网）。

## 为什么必须有（哲学 6.1 + 1.4）
拆大文件的第一铁律是「**对外门面不变**」（import 路径、类名、方法签名、默认值全不动）。
但人眼核不住：一个 1371 行的文件拆成 6 个单元，谁也不能保证没漏一个方法、没改一个默认值。
没有机械核验，「门面不变」就只是句口号 —— 拆完的回归要等别人调用时才炸。

## 怎么判（用 AST，**不 import**）
import 会触发装配（几十秒 + 副作用），且拆到一半的代码可能根本 import 不进去。
AST 只读源码文本，**零副作用、零装配、拆到一半也能核**。

比对三样：
1. **顶层公开符号**：`class` / `def` 名（去掉 `_` 前缀的私有件不比对）；
2. **每个类的公开方法**：名字 + 参数名列表 + 默认值有无；
3. **每个顶层函数的签名**：参数名列表 + 默认值有无。

## 用法
    # 拆之前先存基准（从 HEAD 存，不受在途改动影响）
    python3.14 开发工具/门面核验.py --存基准 运行核心/权威状态.py
    # 拆完比对（默认对 HEAD 比）
    python3.14 开发工具/门面核验.py 运行核心/权威状态.py
    # 或指定基准文件
    python3.14 开发工具/门面核验.py 运行核心/权威状态.py --基准 /private/tmp/…/基准.json

退出码：0 = 门面完全一致；1 = 有差异（**不许提交**）。
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
基准目录 = Path("/private/tmp/系统平台临时脚本_20260918/门面基准")


def 读HEAD(相对路径: str) -> str:
    r = subprocess.run(["git", "-C", str(系统根), "show", f"HEAD:{相对路径}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"✗ HEAD 里没有该文件：{相对路径}")
    return r.stdout


def _签名(节点: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """参数名列表 + 默认值有无（不比对默认值内容，那是行为不是门面）。"""
    参表 = []
    for a in list(节点.args.posonlyargs) + list(节点.args.args) + list(节点.args.kwonlyargs):
        参表.append(a.arg)
    if 节点.args.vararg:
        参表.append("*" + 节点.args.vararg.arg)
    if 节点.args.kwarg:
        参表.append("**" + 节点.args.kwarg.arg)
    默认数 = len(节点.args.defaults)
    必填数 = len(参表) - 默认数
    return "(" + ", ".join(参表[:必填数] + [p + "=?" for p in 参表[必填数:]]) + ")"


def 抽门面(源码: str) -> dict:
    """抽公开门面：顶层 class/def + 类内公开方法 + 签名。"""
    树 = ast.parse(源码)
    门面: dict[str, dict] = {}
    for 节点 in 树.body:
        if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not 节点.name.startswith("_"):
                门面[f"def {节点.name}"] = {"签名": _签名(节点)}
        elif isinstance(节点, ast.ClassDef):
            if 节点.name.startswith("_"):
                continue
            方法 = {}
            for 子 in 节点.body:
                if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)) and not 子.name.startswith("_"):
                    方法[子.name] = _签名(子)
            门面[f"class {节点.name}"] = {"方法": 方法}
    return 门面


def 存基准(相对路径: str) -> Path:
    门面 = 抽门面(读HEAD(相对路径))
    基准目录.mkdir(parents=True, exist_ok=True)
    目标 = 基准目录 / (相对路径.replace("/", "__") + ".json")
    目标.write_text(json.dumps(门面, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"✓ 基准已存：{目标}")
    print(f"  顶层符号 {len(门面)} 个，方法合计 "
          f"{sum(len(v.get('方法', {})) for v in 门面.values())} 个")
    return 目标


def 比对(相对路径: str, 基准文件: Path) -> int:
    基准 = json.loads(基准文件.read_text(encoding="utf-8"))
    当前文件 = 系统根 / 相对路径
    if not 当前文件.is_file():
        print(f"✗ 当前文件不存在：{相对路径}")
        return 1
    当前 = 抽门面(当前文件.read_text(encoding="utf-8"))
    差异: list[str] = []

    消失 = sorted(set(基准) - set(当前))
    新增 = sorted(set(当前) - set(基准))
    for 名 in 消失:
        差异.append(f"✗ 顶层符号消失：{名}")
    for 名 in 新增:
        差异.append(f"⚠ 顶层符号新增：{名}（拆文件不该新增公开符号；若确有意，需在提交信息里说明）")

    for 名 in sorted(set(基准) & set(当前)):
        基方法 = 基准[名].get("方法")
        当方法 = 当前[名].get("方法")
        if 基方法 is None:
            if 基准[名]["签名"] != 当前[名]["签名"]:
                差异.append(f"✗ 函数签名变了：{名}  {基准[名]['签名']} → {当前[名]['签名']}")
            continue
        for 方名 in sorted(set(基方法) - set(当方法)):
            差异.append(f"✗ {名} 的方法消失：{方名}{基方法[方名]}")
        for 方名 in sorted(set(当方法) - set(基方法)):
            差异.append(f"⚠ {名} 新增方法：{方名}{当方法[方名]}")
        for 方名 in sorted(set(基方法) & set(当方法)):
            if 基方法[方名] != 当方法[方名]:
                差异.append(f"✗ 方法签名变了：{名}.{方名}  {基方法[方名]} → {当方法[方名]}")

    print(f"\n=== 门面核验：{相对路径}（基准 {基准文件.name}）===")
    print(f"  基准顶层 {len(基准)} 个 / 当前顶层 {len(当前)} 个")
    if not 差异:
        print("  ✓ 门面逐字一致（import 路径、类名、方法签名、默认值有无 全未变）")
        return 0
    for d in 差异:
        print("  " + d)
    硬伤 = [d for d in 差异 if d.startswith("✗")]
    print(f"  → 硬伤 {len(硬伤)} 条 / 提示 {len(差异) - len(硬伤)} 条")
    if 硬伤:
        print("  判据：**不许提交**。拆文件是纯内部重组，门面动了就是对外契约变了。")
    return 1 if 硬伤 else 0


def main(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="门面核验：拆文件前后对外门面是否逐字未变")
    解析.add_argument("文件", help="仓库相对路径")
    解析.add_argument("--存基准", action="store_true", help="从 HEAD 存基准（拆之前跑）")
    解析.add_argument("--基准", default="", help="指定基准 json（默认用同路径的基准文件）")
    参 = 解析.parse_args(argv)
    if 参.存基准:
        存基准(参.文件)
        return 0
    基准文件 = Path(参.基准) if 参.基准 else 基准目录 / (参.文件.replace("/", "__") + ".json")
    if not 基准文件.is_file():
        print(f"✗ 没有基准：{基准文件}\n  → 先跑：python3.14 开发工具/门面核验.py --存基准 {参.文件}")
        return 2
    return 比对(参.文件, 基准文件)


if __name__ == "__main__":
    raise SystemExit(main())
