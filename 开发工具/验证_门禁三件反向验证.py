"""门禁面三件反向验证：#97 依赖分两段 / #100 第三方导入分布 / #106 测试写入边界。

口径（哲学 1.4 反向试验 / 13.1 三要素第三栏）：每一项都要有「绿拍 → 红拍 → 恢复拍」，
且红拍必须在**临时根**造违规样本 —— **绝不写仓库**（否则验证脚本自己就是 #106 判据一 的违规）。

用法（在仓库任意 cwd 下都可跑）：
    python3.14 -m 开发工具.验证_门禁三件反向验证

退出码：0 = 三件绿/红/恢复拍全过；1 = 有拍失败（逐条打印失败项）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(仓库根))

结果: list[tuple[str, str, bool, str]] = []


def 记(项: str, 拍: str, 通过: bool, 说明: str) -> None:
    结果.append((项, 拍, 通过, 说明))
    print(f"[{'✓' if 通过 else '✗'}] {项} · {拍}：{说明}")


def 跑(模块: str, *参数: str, 超时秒: int = 200) -> tuple[int, str]:
    完成 = subprocess.run([sys.executable, "-m", 模块, *参数], cwd=str(仓库根),
                      capture_output=True, text=True, timeout=超时秒)
    return 完成.returncode, (完成.stdout or "") + (完成.stderr or "")


# ── #97 依赖分两段 ───────────────────────────────────────────────────────────
from 开发工具.依赖派生 import 生成依赖分两段 as 派生

码, 出 = 跑("开发工具.依赖派生.生成依赖分两段", "--校验")
记("#97", "绿拍", 码 == 0 and "校验通过" in 出,
  f"子进程 --校验 退出码={码}；{(出.strip().splitlines() or [''])[-1][:80]}")

问题 = 派生.校验问题(派生.汇总())
记("#97", "绿拍(纯函数)", 问题 == [],
  f"in-process 校验问题(汇总()) 返回 {len(问题)} 项（发布门禁消费的就是它）")

数据 = 派生.汇总()
原件表 = list(数据["件表"])
数据["件表"] = [件 for 件 in 数据["件表"] if 件["名称"] != "FFmpeg提供者"]
破问题 = 派生.校验问题(数据)
记("#97", "红拍", len(破问题) > 0,
  f"抹掉一件后校验问题 {len(破问题)} 项：{破问题[:2]}")
数据["件表"] = 原件表
记("#97", "恢复拍", 派生.校验问题(数据) == [], "还原汇总数据后校验问题回到 0 项")

# ── #100 第三方导入分布 ──────────────────────────────────────────────────────
from 开发工具.第三方导入分布基线门禁 import 运行门禁 as 运行分布门禁
from 开发工具.第三方导入分布基线门禁 import 新增模块 as 新增模块标签

违规, 留痕, 统计 = 运行分布门禁(仓库根)
记("#100", "绿拍", not 违规,
  f"扫描 {统计['文件数']} 个 .py；模块 {统计['模块数']}（基线 {统计['基线模块数']}）"
  f"／import {统计['处数']} 处；违规 {len(违规)}／留痕 {len(留痕)}")

码, 出 = 跑("开发工具.第三方导入分布基线门禁")
记("#100", "绿拍(子进程)", 码 == 0, f"子进程退出码={码}")

临时 = Path(tempfile.mkdtemp(prefix="反向验证_导入分布_"))
try:
    (临时 / "支持库" / "后端").mkdir(parents=True)
    (临时 / "支持库" / "后端" / "违规样本.py").write_text(
        "import requests\n", encoding="utf-8")
    违规, _, 统计 = 运行分布门禁(临时)
    命中 = [项 for 项 in 违规 if 项["缺口类型"] == 新增模块标签]
    记("#100", "红拍", any(项["模块"] == "requests" for 项 in 命中),
      f"临时根里造 `import requests` ⇒ 新增模块违规 {len(命中)} 项："
      f"{[项['模块'] for 项 in 命中]}（违规总 {len(违规)}）")
finally:
    shutil.rmtree(临时, ignore_errors=True)

违规, _, _ = 运行分布门禁(仓库根, 基线文件=Path("/不存在/基线.json"))
记("#100", "红拍(fail-closed)", bool(违规),
  f"基线文件不存在 ⇒ 违规 {len(违规)} 项（不静默按空基线判绿）")

# ── #106 测试写入边界 ────────────────────────────────────────────────────────
from 开发工具.测试写入边界门禁 import 运行门禁 as 运行边界门禁

违规, 存量, 统计 = 运行边界门禁(仓库根)
记("#106", "绿拍", not 违规,
  f"违规 0；基线内存量 {统计['存量总数']} 条"
  f"（判据一 {统计['判据一']['仓库内写']} 处命中／判据二 {统计['判据二']['只成功断言用例']} 条"
  f"／判据三 空转 {统计['判据三']['空转']}）")

码, 出 = 跑("开发工具.测试写入边界门禁")
记("#106", "绿拍(子进程)", 码 == 0 and "基线内" in 出,
  f"子进程退出码={码}；{(出.strip().splitlines() or [''])[-1][:70]}")

临时 = Path(tempfile.mkdtemp(prefix="反向验证_测试边界_"))
try:
    样本 = 临时 / "测试中心"
    样本.mkdir(parents=True)
    (样本 / "测试_违规样本.py").write_text(
        '"""三判据违规样本（只存在于临时根，绝不进仓库）。"""\n'
        "import os\n"
        "import unittest\n"
        "from pathlib import Path\n"
        "from unittest import mock\n"
        "\n"
        "\n"
        "class 违规样本(unittest.TestCase):\n"
        "    def test_写仓库内相对路径(self):\n"
        '        目录 = Path("支持库/适配层/违规样本提供者")\n'
        "        目录.mkdir(parents=True, exist_ok=True)\n"
        "\n"
        "    def test_只断言成功(self):\n"
        "        结果 = type('R', (), {'成功': True, '错误说明': ''})()\n"
        "        self.assertTrue(结果.成功, 结果.错误说明)\n"
        "\n"
        "    def test_mock空转(self):\n"
        '        with mock.patch.dict(os.environ, {"反向验证_不存在的开关": "1"}):\n'
        "            self.assertTrue(True)\n",
        encoding="utf-8")
    违规, 存量, 统计 = 运行边界门禁(临时)
    类型表 = sorted({项["缺口类型"] for 项 in 违规})
    记("#106", "红拍", len(类型表) == 3,
      f"临时根三判据样本 ⇒ 违规类型 {类型表}")
finally:
    shutil.rmtree(临时, ignore_errors=True)

违规, _, _ = 运行边界门禁(仓库根, 基线路径=Path("/不存在/基线.json"))
记("#106", "红拍(fail-closed)", any(项["缺口类型"] == "测试写入-存量基线不可用" for 项 in 违规),
  f"存量基线缺失 ⇒ 违规 {len(违规)} 项（含「存量基线不可用」）")

# 仓库零污染：临时根都在系统临时目录，仓库内不得出现新文件
G = "/Library/Developer/CommandLineTools/usr/bin/git"
出 = subprocess.run([G, "status", "--porcelain", "--untracked-files=all", "--",
                "支持库/适配层/违规样本提供者", "测试中心"],
               cwd=str(仓库根), capture_output=True, text=True).stdout
记("#106", "恢复拍", "违规样本" not in 出,
  f"仓库内无验证残留（git status 过滤后：{出.strip() or '空'}）")

失败 = [项 for 项 in 结果 if not 项[2]]
print()
print(f"反向验证：共 {len(结果)} 拍，通过 {len(结果) - len(失败)}，失败 {len(失败)}")
for 项 in 失败:
    print("   失败：", 项)
sys.exit(1 if 失败 else 0)
