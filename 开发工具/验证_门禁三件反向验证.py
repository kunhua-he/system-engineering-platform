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
from 开发工具.测试写入边界门禁 import 未解析写动作 as 未解析标签
from 开发工具.测试写入边界门禁 import 存量基线路径 as 边界基线路径

违规, 存量, 统计 = 运行边界门禁(仓库根)
记("#106", "绿拍", not 违规,
  f"违规 0；基线内存量 {统计['存量总数']} 键 / {统计['存量总处数']} 处"
  f"（判据一 写动作 {统计['判据一']['写动作数']} 处："
  f"仓库内写 {统计['判据一']['仓库内写']}／未解析 {统计['判据一']['未解析']}"
  f"（存量 {统计['判据一·未解析']['存量基线']['存量处数']} 处）；"
  f"判据二 {统计['判据二']['只成功断言用例']} 条／判据三 空转 {统计['判据三']['空转']}）")

码, 出 = 跑("开发工具.测试写入边界门禁")
判据一行 = [行 for 行 in 出.splitlines() if "判据一 写仓库内相对路径" in 行]
记("#106", "绿拍(子进程)", 码 == 0 and "基线内" in 出
   and "未解析（计入违规，fail-closed）" in 出,
  f"子进程退出码={码}；{(判据一行 or [''])[0].strip()[:120]}")

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
        "            self.assertTrue(True)\n"
        "\n"
        "    def test_未解析写动作(self):\n"
        '        外部根.write_text("x", encoding="utf-8")\n'
        "\n"
        "    def test_正常写动作(self):\n"
        '        Path("工程缓存/反向验证夹具").mkdir(parents=True, exist_ok=True)\n',
        encoding="utf-8")
    违规, 存量, 统计 = 运行边界门禁(临时)
    类型表 = sorted({项["缺口类型"] for 项 in 违规})
    记("#106", "红拍", len(类型表) == 4, f"临时根四类样本 ⇒ 违规类型 {类型表}")
    未解析项 = [项 for 项 in 违规 if 项["缺口类型"] == 未解析标签]
    未解析样例文本 = "；".join(
        f"{项['文件']}:{项['行']} 动作={项['动作']} 目标={项['目标']}" for 项 in 未解析项)
    记("#106", "红拍(未解析单列)", len(未解析项) == 1
       and "静态解析不出左端基" in 未解析项[0]["详情"],
      f"未解析违规 {len(未解析项)} 项：{未解析样例文本}")
    记("#106", "不误伤(正常写动作)", 统计["判据一"]["受管写"] >= 1
       and 统计["判据一"]["仓库内写"] == 1
       and not any("工程缓存" in 项["目标"] for 项 in 未解析项),
      "`Path(工程缓存/反向验证夹具).mkdir()` ⇒ 受管写 "
      f"{统计['判据一']['受管写']} 处（未进未解析档）；仓库内写 "
      f"{统计['判据一']['仓库内写']} 处（只有造的那一处，正常样本没被改判定连带判红）")
finally:
    shutil.rmtree(临时, ignore_errors=True)

违规, _, _ = 运行边界门禁(仓库根, 基线路径=Path("/不存在/基线.json"))
记("#106", "红拍(fail-closed)", any(项["缺口类型"] == "测试写入-存量基线不可用" for 项 in 违规),
  f"存量基线缺失 ⇒ 违规 {len(违规)} 项（含「存量基线不可用」）")

# 存量基线本身：**把基线调小** ⇒ 必须判红（证基线真的在起作用，不是摆设）。
# 两种调小都试：① 删掉一个未解析键（新增键）；② 把一个键的处数减 1（处数超出）。
#
# ★ 2026-09-23 修：夹具键必须取自**现场仍在**的未解析键。判据扩解析器后，
#   基线里会留下一批「已收敛」的键（判据现在解析得出、不再进未解析档）——
#   拿这种键做反向验证，把它的处数减 1 也不会判红（现场根本没有这个键），
#   该拍会**假失败**（实测：取 `…测试_装配单包隔离.py::mkdir::目录 / '能力契约'`）。
import json as _json  # noqa: E402  —— 本段局部导入，避免改动本件 #106 段以外的行
from 开发工具.测试写入边界门禁 import 扫描写入 as 扫描边界写入  # noqa: E402

基线数据 = _json.loads(边界基线路径.read_text(encoding="utf-8"))
未解析桶: dict[str, int] = 基线数据["测试写入-写动作未解析"]
现场判据一, _现场统计 = 扫描边界写入(仓库根)
现场未解析键 = {项["桶键"] for 项 in 现场判据一 if 项["缺口类型"] == 未解析标签}
可用键 = sorted(键 for 键 in 未解析桶 if 键 in 现场未解析键)
降键候选 = [键 for 键 in 可用键 if 未解析桶[键] > 1]
临时基线 = Path(tempfile.mkdtemp(prefix="反向验证_边界基线_")) / "基线_调小.json"
try:
    改 = _json.loads(边界基线路径.read_text(encoding="utf-8"))
    删键 = 可用键[0]
    降键 = 降键候选[0]
    改["测试写入-写动作未解析"] = {k: v for k, v in 未解析桶.items() if k != 删键}
    改["测试写入-写动作未解析"][降键] = 未解析桶[降键] - 1
    临时基线.write_text(_json.dumps(改, ensure_ascii=False), encoding="utf-8")
    违规, _, 统计 = 运行边界门禁(仓库根, 基线路径=临时基线)
    命中 = [项 for 项 in 违规 if 项["缺口类型"] == 未解析标签]
    记("#106", "红拍(基线删键)", any(项["桶键"] == 删键 for 项 in 命中),
      f"基线删掉未解析键 `{删键}` ⇒ 未解析违规 {len(命中)} 项，"
      f"含该键={any(项['桶键'] == 删键 for 项 in 命中)}")
    记("#106", "红拍(基线降处数)", any(项["桶键"] == 降键 for 项 in 命中),
      f"基线把 `{降键}` 处数 {未解析桶[降键]} → {未解析桶[降键] - 1} ⇒ "
      f"该键判红={any(项['桶键'] == 降键 for 项 in 命中)}"
      "（处数也是被冻结的量，同 #100 口径）")
finally:
    shutil.rmtree(临时基线.parent, ignore_errors=True)

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
