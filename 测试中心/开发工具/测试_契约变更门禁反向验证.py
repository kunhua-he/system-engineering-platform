"""卡点 B 接线第 3 条 · 「契约口径·对外契约变更 / 契约版本唯一」接线反向验证（2026-09-18）。

验证的是**接线本身**（判定口径 + 基准选得对不对 + fail-closed + 是否真在必经路径上），
不是重测 `对外契约变更判定` 的判据（判据已有 43 例，见
`测试中心/开发工具/测试_对外契约变更判定.py`）与 `契约版本唯一` 的判据（见
`测试中心/开发工具/测试_契约版本唯一.py`）。

**为什么用夹具仓库**：判据要真验，必须有人真的把某个能力的参数类型改掉**却不升版本**；
在真实仓库里改契约就是「改各包能力定义」——本任务的只改范围明确禁止。
故反向破坏全部落在 `tempfile` 的**夹具仓库**（夹具源码根 + 夹具制品仓库，真实
`能力定义.json` + 真实 `当前.json` 指针 + 真实判据链），基准也写成夹具自己的制品。
真实仓库只做两件事：默认路径跑绿、源码接线元组断言（都不改任何文件）。

断言清单：
1. 真仓库 5.3 判**绿**，详情报出「判据面 134 包／677 能力」「要求递增 0 包」。
2. 真仓库 5.1 判**绿**，详情报出「事实源 契约版本 = 2.0.0」「本次计数 0 条」。
3. 接线元组确实在必经路径（`("对外契约变更", …)` / `("契约版本唯一", …)`）——
   「定义了但没接线」正是本项要防的「半个强制」（13.1）。
4. 阻断口径两项都在 `防回潮阻断配置` 且显式 `阻断=真`（13.2）。
5. **反向验证（核心）**：夹具里改一个能力的参数类型**不升版本** → 判红，且**点名那个包、
   那个能力**、并给出字段级差异（上一版 → 本版）；**升版本后转绿**且详情报出「版本已递增合法」。
6. 版本回退仍判红；还原改动 → 转绿（与红互为逆命题，不许「红了就红着」）。
7. 契约面其它维度（删参数 / 新增能力）同样判红，且点名能力。
8. 只改说明文案（纯文档字段）→ 绿（不是契约面变化，不要求递增）。
9. 5.1 反向：夹具里把 `契约版本` 改成别的值 → 判红并点名包；缺字段 / 缺契约文件 → 判红；
   还原 → 绿。
10. fail-closed：基线内无同名包 / 制品指针缺失 → 判红（不得当「无变化」放行）；
    扫描面为 0 → **未核验**（不占通过位，也不冒充失败证据）。
11. 判据属主：本模块**不另写指纹算法**（源码里无 hashlib/hmac/sha256），
    `校验对外契约变更` 只依赖判定模块；5.1 的事实源直接 import，不另立常量。
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.发布门禁 import 契约变更门禁 as 接线模块
from 开发工具.发布门禁.运行发布门禁 import 防回潮阻断配置
from 开发工具.发布门禁.契约变更门禁 import 校验对外契约变更, 校验契约版本唯一

接线模块路径 = 仓库根 / "开发工具" / "发布门禁" / "契约变更门禁.py"
门禁源码路径 = 仓库根 / "开发工具" / "发布门禁" / "运行发布门禁.py"

夹具源码根名 = "夹具源码"
夹具制品仓库名 = "夹具制品仓库"
夹具包相对 = ("支持库", "夹具包")
夹具包id = "支持库.夹具包"
夹具能力id = "夹具.夹具包.能力一"
夹具目标能力id = "夹具.夹具包.能力二"
参数旧类型 = "双精度数型"
参数新类型 = "双精度数形"
制品摘要 = "f" * 16


def 能力一() -> dict:
    """夹具能力一：一个带可改类型的参数（反向破坏的落点）。"""
    return {
        "能力id": 夹具能力id, "版本": "1.0.0", "说明": "夹具能力一",
        "参数": [{"名称": "超时秒", "类型": 参数旧类型, "必填": 假, "默认值": 0.0,
                  "说明": "超时秒数"}],
        "返回": {"类型": "结果型", "值结构": {"值": "文本型"}},
        "错误码": ["参数不合法"],
        "行为": {"副作用": "纯计算", "资源释放": "无资源残留"},
    }


def 能力二() -> dict:
    return {
        "能力id": 夹具目标能力id, "版本": "1.0.0", "说明": "夹具能力二",
        "参数": [{"名称": "文本", "类型": "文本型", "必填": 真, "默认值": None,
                  "说明": "输入文本"}],
        "返回": {"类型": "结果型", "值结构": {"值": "文本型"}},
        "错误码": ["参数不合法"],
        "行为": {"副作用": "纯计算", "资源释放": "无资源残留"},
    }


def 写包(包目录: Path, *, 版本: str = "1.0.0", 契约版本: str = "2.0.0",
         能力表: list[dict] | None = None, 带契约文件: bool = 真,
         契约文件内容: dict | None = None) -> None:
    """写一个夹具包的**真实两件套**：能力定义.json（源码侧读数来源）+ 能力契约/参数契约.json。"""
    包目录.mkdir(parents=True, exist_ok=True)
    条目表 = 能力表 if 能力表 is not None else [能力一(), 能力二()]
    (包目录 / "能力定义.json").write_text(json.dumps(
        {"包id": 夹具包id, "版本": 版本, "说明": "夹具包", "能力列表": 条目表},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if not 带契约文件:
        return
    if 契约文件内容 is None:
        契约文件内容 = {"契约版本": 契约版本, "能力契约": 条目表}
    (包目录 / "能力契约").mkdir(parents=True, exist_ok=True)
    (包目录 / "能力契约" / "参数契约.json").write_text(
        json.dumps(契约文件内容, ensure_ascii=False, indent=1), encoding="utf-8")


def 造夹具仓库(父目录: Path) -> tuple[Path, Path]:
    """造夹具仓库：`(夹具源码根, 夹具制品仓库)`。基准 = 制品内同名包（与源码同版本）。"""
    源码根 = 父目录 / 夹具源码根名
    制品仓库 = 父目录 / 夹具制品仓库名
    制品目录 = 制品仓库 / f"平台客户端-{制品摘要}"
    写包(源码根.joinpath(*夹具包相对))
    写包(制品目录 / "平台客户端" / Path(*夹具包相对))
    (制品仓库 / "当前.json").write_text(json.dumps(
        {"摘要sha256": 制品摘要, "路径": 制品目录.name}, ensure_ascii=False),
        encoding="utf-8")
    return 源码根, 制品仓库


def 改源码包(源码根: Path, 改动) -> Path:
    包目录 = 源码根.joinpath(*夹具包相对)
    数据 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
    改动(数据)
    (包目录 / "能力定义.json").write_text(
        json.dumps(数据, ensure_ascii=False, indent=1), encoding="utf-8")
    return 包目录


class 契约口径接线反向验证(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="契约口径反验_"))
        self.源码根, self.制品仓库 = 造夹具仓库(self.临时根)

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    # ---------- 夹具工具 ----------

    def _判契约变更(self, 源码根: Path | None = None,
                 制品仓库: Path | None = None) -> tuple[bool | None, str]:
        return 校验对外契约变更(源码根 or self.源码根,
                             制品仓库根=制品仓库 or self.制品仓库)

    def _断言判红并点名(self, 期望片段: list[str]) -> str:
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 假, f"必须判红，实际详情：{详情}")
        for 片段 in 期望片段:
            self.assertIn(片段, 详情, f"判红详情必须含「{片段}」，实际：{详情}")
        return 详情

    # ---------- 一、真仓库存量（判据面实测可复核） ----------

    def test_真仓库契约变更判绿且报出判据面(self) -> None:
        """真仓库两态都必须是**判据正确**的那一态（不是恒绿，也不是恒红）。

        为什么不断言「一定绿」：本项的基准是**当前激活制品**，任何人在这份工作树里
        改了契约面却没升版本，本项就**应当**判红 —— 那是它的本职工作，不是本项 bug。
        恒绿断言在并行维修期会变成「谁改契约都报测试红」，把真违约说成测试噪声，
        正是判据 5 要防的「把判据错误说成被测缺陷」的反面。
        故这里两态都断言到位：无违约 → 必须绿且逐包逐字未变；有违约 → 必须红且点名包。
        """
        通过, 详情 = 校验对外契约变更()
        self.assertIn("判据面 134 包", 详情)
        self.assertIn("基线取证失败 0 包", 详情)
        self.assertIn("基准=激活制品", 详情)
        要求递增 = int(详情.split("**要求递增 ")[1].split(" 包**")[0])
        if 要求递增 == 0:
            self.assertIs(通过, 真, f"无违约时必须绿，实际详情：{详情}")
            self.assertIn("契约面逐字未变 134 包", 详情)
            return
        # 有真违约：门禁必须判红并指出那些包（不许静默放行）
        self.assertIs(通过, 假, f"有 {要求递增} 处契约面变化未递增版本，必须判红：{详情}")
        self.assertIn("契约面变但版本未递增/回退", 详情)
        self.assertIn("上一版", 详情)

    def test_真仓库契约版本唯一判绿且报出事实源(self) -> None:
        """真仓库按**实测计数**判：无违规必须绿、有违规必须红且点名包（两态都要断言）。

        为什么不断言恒绿：并行维修期有人可以真的把某个包的 `契约版本` 写歪或漏生成契约；
        本项本职就是红。恒绿断言会把真违约说成测试噪声（判据 5 的反面）。
        """
        通过, 详情 = 校验契约版本唯一()
        self.assertIn("事实源 契约版本 = 2.0.0", 详情)
        self.assertIn("门禁源码边界", 详情)
        计数 = int(详情.split("本次计数 ")[1].split(" 条")[0])
        if 计数 == 0:
            self.assertIs(通过, 真, f"无违规时必须绿，实际详情：{详情}")
            self.assertIn("全部逐字等于事实源", 详情)
            return
        self.assertIs(通过, 假, f"有 {计数} 条不唯一必须判红：{详情}")
        self.assertIn("契约版本不唯一 / 缺失", 详情)

    def test_边界外正式包根显式上报不当通过(self) -> None:
        """`技能库` 是正式包根但不在门禁源码边界内：必须写进详情，不得静默漏掉。"""
        通过, 详情 = 校验契约版本唯一()
        self.assertIs(通过, 真)
        self.assertIn("边界外正式包根", 详情)
        self.assertIn("技能库", 详情)

    # ---------- 二、核心反向验证：改参数类型不升版本 → 红且点名 ----------

    def test_反向_改参数类型不升版本判红并点名能力(self) -> None:
        def 改(数据):
            数据["能力列表"][0]["参数"][0]["类型"] = 参数新类型

        改源码包(self.源码根, 改)
        详情 = self._断言判红并点名(["支持库/夹具包", 夹具能力id, "参数类型变化",
                                参数新类型, "未递增"])
        # 「上一版是什么、本版变了什么」必须写得出来（不只报个真假）
        self.assertIn("上一版 1.0.0 → 本版 1.0.0", 详情)

    def test_反向_升版本后转绿且报出已递增(self) -> None:
        def 改(数据):
            数据["能力列表"][0]["参数"][0]["类型"] = 参数新类型
            数据["版本"] = "1.1.0"

        改源码包(self.源码根, 改)
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 真, f"版本递增后必须转绿，实际详情：{详情}")
        self.assertIn("已由版本递增承载 1 包", 详情)
        self.assertIn("上一版 1.0.0 → 本版 1.1.0", 详情)
        self.assertIn("版本已递增合法", 详情)

    def test_反向_版本回退仍判红(self) -> None:
        def 改(数据):
            数据["能力列表"][0]["参数"][0]["类型"] = 参数新类型
            数据["版本"] = "0.9.0"

        改源码包(self.源码根, 改)
        self._断言判红并点名(["支持库/夹具包", "版本回退"])

    def test_反向_还原改动后转绿(self) -> None:
        def 改(数据):
            数据["能力列表"][0]["参数"][0]["类型"] = 参数新类型

        包目录 = 改源码包(self.源码根, 改)
        原文 = (包目录 / "能力定义.json").read_text(encoding="utf-8")
        通过红前, _ = self._判契约变更()
        self.assertIs(通过红前, 假)
        包目录.joinpath("能力定义.json").write_text(原文, encoding="utf-8")
        # 还原后再动一次并回退，证明「红 → 绿」确实由改动本身决定
        原文真 = json.loads(原文)
        原文真["能力列表"][0]["参数"][0]["类型"] = 参数旧类型
        包目录.joinpath("能力定义.json").write_text(
            json.dumps(原文真, ensure_ascii=False, indent=1), encoding="utf-8")
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 真, f"还原后必须转绿，实际详情：{详情}")
        self.assertIn("契约面逐字未变 1 包", 详情)

    # ---------- 三、契约面其它维度同样判红 ----------

    def test_反向_丢必填参数判红并点名能力(self) -> None:
        def 改(数据):
            数据["能力列表"][1]["参数"] = []

        改源码包(self.源码根, 改)
        self._断言判红并点名([夹具目标能力id, "删除参数"])

    def test_反向_新增能力判红并点名能力(self) -> None:
        def 改(数据):
            新增 = json.loads(json.dumps(数据["能力列表"][0], ensure_ascii=False))
            新增["能力id"] = "夹具.夹具包.能力三"
            数据["能力列表"].append(新增)

        改源码包(self.源码根, 改)
        self._断言判红并点名(["新增能力", "夹具.夹具包.能力三"])

    def test_只改说明文案不要求递增(self) -> None:
        """纯文档字段（`参数.说明`）变化不是契约面变化 —— 判绿，且不点名要求递增。"""
        def 改(数据):
            数据["能力列表"][0]["参数"][0]["说明"] = "超时秒数（措辞调整）"

        改源码包(self.源码根, 改)
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 真, f"只改说明文案应判绿，实际详情：{详情}")
        self.assertIn("仅文档性变化（不要求递增）1 包", 详情)
        self.assertIn("要求递增 0 包", 详情)

    # ---------- 四、5.1 反向验证 ----------

    def test_反向_契约版本不唯一判红并点名包(self) -> None:
        包目录 = self.源码根.joinpath(*夹具包相对)
        数据 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        数据["契约版本"] = "3.0.0"
        (包目录 / "能力契约" / "参数契约.json").write_text(
            json.dumps(数据, ensure_ascii=False, indent=1), encoding="utf-8")
        通过, 详情 = 校验契约版本唯一(self.源码根)
        self.assertIs(通过, 假, f"契约版本不唯一必须判红，实际详情：{详情}")
        self.assertIn("支持库/夹具包", 详情)
        self.assertIn("3.0.0", 详情)
        self.assertIn("唯一事实源 2.0.0", 详情)

    def test_反向_缺契约版本字段判红(self) -> None:
        包目录 = self.源码根.joinpath(*夹具包相对)
        数据 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        数据.pop("契约版本")
        (包目录 / "能力契约" / "参数契约.json").write_text(
            json.dumps(数据, ensure_ascii=False, indent=1), encoding="utf-8")
        通过, 详情 = 校验契约版本唯一(self.源码根)
        self.assertIs(通过, 假, f"缺 契约版本 必须判红，实际详情：{详情}")
        self.assertIn("缺 契约版本", 详情)

    def test_反向_缺契约文件判红(self) -> None:
        shutil.rmtree(self.源码根.joinpath(*夹具包相对, "能力契约"))
        通过, 详情 = 校验契约版本唯一(self.源码根)
        self.assertIs(通过, 假, f"缺契约文件必须判红，实际详情：{详情}")
        self.assertIn("缺 能力契约/参数契约.json", 详情)

    def test_反向_契约版本还原后转绿(self) -> None:
        包目录 = self.源码根.joinpath(*夹具包相对)
        契约文件 = 包目录 / "能力契约" / "参数契约.json"
        原文 = 契约文件.read_text(encoding="utf-8")
        数据 = json.loads(原文)
        数据["契约版本"] = "9.9.9"
        契约文件.write_text(json.dumps(数据, ensure_ascii=False, indent=1), encoding="utf-8")
        通过红前, _ = 校验契约版本唯一(self.源码根)
        self.assertIs(通过红前, 假)
        契约文件.write_text(原文, encoding="utf-8")
        通过, 详情 = 校验契约版本唯一(self.源码根)
        self.assertIs(通过, 真, f"还原后必须转绿，实际详情：{详情}")
        self.assertIn("本次计数 0 条", 详情)

    # ---------- 五、fail-closed 与未核验 ----------

    def test_基线内无同名包判红(self) -> None:
        """制品里没有同名包（新包尚未进制品）→ 判红，不得当「无变化」放行。"""
        新包 = self.源码根 / "支持库" / "夹具新包"
        写包(新包, 能力表=[能力一()])
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 假, f"基线缺包必须判红，实际详情：{详情}")
        self.assertIn("支持库/夹具新包", 详情)
        self.assertIn("基线包缺失", 详情)

    def test_制品指针缺失判红(self) -> None:
        (self.制品仓库 / "当前.json").unlink()
        通过, 详情 = self._判契约变更()
        self.assertIs(通过, 假, f"制品指针缺失必须判红，实际详情：{详情}")
        self.assertIn("基线制品指针缺失", 详情)

    def test_源码根无包时判未核验(self) -> None:
        """扫描面为 0：判据什么都没看 → 未核验，不占通过位也不冒充失败证据。"""
        空源码根 = self.临时根 / "空源码根"
        空源码根.mkdir()
        通过, 详情 = self._判契约变更(空源码根)
        self.assertIsNone(通过, f"扫描面为 0 应为未核验，实际：{通过} / {详情}")
        self.assertIn("未核验", 详情)

    def test_契约版本扫描面为0判未核验(self) -> None:
        空源码根 = self.临时根 / "空源码根"
        空源码根.mkdir()
        通过, 详情 = 校验契约版本唯一(空源码根)
        self.assertIsNone(通过, f"扫描面为 0 应为未核验，实际：{通过} / {详情}")
        self.assertIn("未核验", 详情)

    # ---------- 六、接线在必经路径 / 不建第二份实现 ----------

    def test_两项都接在必经路径的for元组里(self) -> None:
        """「定义了但没接线」＝半个强制（13.1）。直接对门禁源码断言接线元组。"""
        树 = ast.parse(门禁源码路径.read_text(encoding="utf-8"))
        接线对: list[tuple[str, str]] = []
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.For) or not isinstance(节点.iter, ast.Tuple):
                continue
            for 元素 in 节点.iter.elts:
                if (isinstance(元素, ast.Tuple) and len(元素.elts) == 2
                        and isinstance(元素.elts[0], ast.Constant)
                        and isinstance(元素.elts[1], ast.Name)):
                    接线对.append((str(元素.elts[0].value), 元素.elts[1].id))
        self.assertIn(("对外契约变更", "校验对外契约变更"), 接线对,
                      f"接线元组缺失，实际：{接线对}")
        self.assertIn(("契约版本唯一", "校验契约版本唯一"), 接线对,
                      f"接线元组缺失，实际：{接线对}")

    def test_阻断口径显式配置为干净通过(self) -> None:
        for 名称 in ("对外契约变更", "契约版本唯一"):
            self.assertIn(名称, 防回潮阻断配置,
                          "阻断口径必须显式配置（13.2：不靠『未新增即放行』隐含）")
            配置 = 防回潮阻断配置[名称]
            self.assertEqual(配置["态"], "干净通过")
            self.assertIs(配置["阻断"], 真, "契约面一变就要拦，不得降级成只报告")
            self.assertEqual(配置["存量基线"], 0)

    def test_判据属主_不另写指纹与兼容算法(self) -> None:
        """本模块不许自带指纹/兼容实现（第二份实现是 E-f 类「同一行两个结论」的入口）。"""
        树 = ast.parse(接线模块路径.read_text(encoding="utf-8"))
        导入模块 = set()
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.Import):
                导入模块.update(别名.name.split(".")[0] for 别名 in 节点.names)
            elif isinstance(节点, ast.ImportFrom):
                导入模块.add((节点.module or "").split(".")[0])
        for 禁项 in ("hashlib", "hmac"):
            self.assertNotIn(禁项, 导入模块, f"本模块不许引入 {禁项}（指纹不是它算的）")
        调用名 = {节点.func.attr for 节点 in ast.walk(树)
                if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute)}
        self.assertNotIn("sha256", 调用名, "本模块不许自己算 sha256")

    def test_判据属主_契约变更函数只依赖判定模块(self) -> None:
        树 = ast.parse(接线模块路径.read_text(encoding="utf-8"))
        函数 = next(节点 for 节点 in ast.walk(树)
                  if isinstance(节点, ast.FunctionDef) and 节点.name == "校验对外契约变更")
        导入模块 = {节点.module for 节点 in ast.walk(函数)
                 if isinstance(节点, ast.ImportFrom)}
        self.assertEqual(导入模块, {"开发工具.契约编译.对外契约变更判定"},
                         f"本项只应依赖判定模块，实际：{导入模块}")

    def test_契约版本事实源是直接import不另立常量(self) -> None:
        树 = ast.parse(接线模块路径.read_text(encoding="utf-8"))
        函数 = next(节点 for 节点 in ast.walk(树)
                  if isinstance(节点, ast.FunctionDef) and 节点.name == "读契约版本事实源")
        导入名 = {别名.name for 节点 in ast.walk(函数) if isinstance(节点, ast.ImportFrom)
                for 别名 in 节点.names}
        模块表 = {节点.module for 节点 in ast.walk(函数) if isinstance(节点, ast.ImportFrom)}
        self.assertEqual(模块表, {"公共契约.版本规则.契约版本"})
        self.assertIn("契约版本", 导入名)
        # 本模块自己**不许**再写一个契约版本常量当第二事实源
        顶层常量 = [节点.targets[0].id for 节点 in 树.body
                if isinstance(节点, ast.Assign)
                and isinstance(节点.targets[0], ast.Name)
                and 节点.targets[0].id == "契约版本"]
        self.assertEqual(顶层常量, [], "契约版本的事实源只有一个，本模块不得另立常量")

    def test_枚举源码包与门禁同一份扫描面(self) -> None:
        """扫描面必须复用 `运行发布门禁.正式源码目录名表`，不另列一套。"""
        树 = ast.parse(接线模块路径.read_text(encoding="utf-8"))
        函数 = next(节点 for 节点 in ast.walk(树)
                  if isinstance(节点, ast.FunctionDef) and 节点.name == "枚举源码包")
        导入名 = {别名.name for 节点 in ast.walk(函数) if isinstance(节点, ast.ImportFrom)
                for 别名 in 节点.names}
        self.assertIn("正式源码目录名表", 导入名, "扫描面必须取门禁的唯一一份")

    def test_判定过程不写盘(self) -> None:
        """只读保证：两项判定跑完，夹具仓库字节与 mtime 不变。"""
        包目录 = self.源码根.joinpath(*夹具包相对)
        定义文件 = 包目录 / "能力定义.json"
        契约文件 = 包目录 / "能力契约" / "参数契约.json"
        指针 = self.制品仓库 / "当前.json"
        前 = [(文件, 文件.stat().st_mtime_ns, 文件.read_bytes())
             for 文件 in (定义文件, 契约文件, 指针)]
        self._判契约变更()
        校验契约版本唯一(self.源码根)
        后 = [(文件, 文件.stat().st_mtime_ns, 文件.read_bytes())
             for 文件 in (定义文件, 契约文件, 指针)]
        self.assertEqual(前, 后)


if __name__ == "__main__":
    unittest.main(verbosity=2)
