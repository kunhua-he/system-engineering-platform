"""测试体系门禁：测试资产的「全量可导入性 + 非零测试」守护。

为什么需要它（证据：`开发文档/临时文档/20260915_底座专业审计/落点清单_02_测试体系.md`
问题 1 的 A3 与 B-6）：`15f974d0` 退役了旧测试总入口、零测试门禁与覆盖门禁，
却保留了 `测试中心/` 下全部 `测试_*.py`——没有入口即没有守护，仓内唯一僵尸
（`测试中心/支持库/测试_psycopg提供者.py` 的 `ImportError: cannot import name '关闭'`）
因此潜伏到审计当天。

本门禁做三件事，全部 fail-closed：

1. **全量可导入性**：对 `测试中心/**/测试_*.py` 逐个在独立子进程
   （`-B -P`，清空 `PYTHONPATH`）里真实 `import`，任一失败即违规；连字符等
   无法点号导入的文件跳过并单独报出（`--连字符即失败` 可升级为违规）。
2. **零测试不得成功**：单文件被 `TestLoader` 收集到 0 个用例即违规；
   `测试中心` 下无测试文件、或发现的文件全部被跳过，同样违规（`AGENTS.md:135`）。
3. **未解释跳过不得成功**：静态判定跳过无理由（口径同
   `MCP工具箱/验证门禁.py:169 _检出未解释跳过`）。

**它不是测试入口**：只导入与收集，不执行任何用例。正式执行入口仍是
`AGENTS.md:125-139` 的 `python3.14 -m unittest 测试中心.<模块路径>`，因此既不
与「不使用 unittest discover 或不存在的聚合测试脚本」冲突，也不构成归档契约
所禁的第二入口。判定逻辑在 `开发工具/测试体系门禁实现/`，本文件只调度。

入参与退出码：

    python3.14 开发工具/测试体系门禁.py [--根 路径] [--并发 N] [--超时 秒]
                                        [--连字符即失败] [--只报告] [--json]

    --根            仓库根（默认：本文件向上找到同时含 测试中心/ 与 开发工具/ 的目录）
    --并发          子进程并发数，默认 4
    --超时          单文件导入超时秒数，默认 120
    --连字符即失败  把「跳过（连字符等）」升级为违规；默认只报出不阻断
    --只报告        有违规也返回 0（供「先报告、后强制」落地）；默认阻断
    --json          以 JSON 输出完整结果

    退出码：0 通过（或 --只报告）；1 存在违规；2 用法/环境错误（根或 测试中心 不存在）

被发布门禁调用（落点清单 A4 形制，接线由发布门禁属主实施）：

    from 开发工具.测试体系门禁 import 运行门禁
    违规 = 运行门禁(系统根)          # list[dict]，空列表即通过；本函数不打印

轻检（不跑全量的自检方式）：

    python3.14 -B 开发工具/测试体系门禁.py --帮助
    python3.14 -B 开发工具/测试体系门禁.py --根 <夹具目录>     # 夹具自测，不碰仓库现场
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

本文件 = Path(__file__).resolve()
系统根 = 本文件.parents[1]
for _祖先 in 本文件.parents:
    if (_祖先 / "测试中心").is_dir() and (_祖先 / "开发工具").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.测试体系门禁实现 import 发现, 报告, 跳过检查, 零测试检查, 可导入性检查

默认并发 = 可导入性检查.默认并发
默认超时秒 = 可导入性检查.默认超时秒

门禁说明 = (
    "三项检查：① 全量可导入性（逐文件真实 import，失败即违规，"
    "连字符等不可点号导入的文件跳过并单独报出）；② 零测试不得成功"
    "（单文件 0 用例、或无测试文件、或全部被跳过）；③ 未解释跳过不得成功"
    "（静态判定 skip 无理由）。本门禁只导入与收集，不执行任何用例，不是测试入口。"
)
退出码说明 = (
    "退出码：0 通过（或 --只报告）；1 存在违规；2 用法或环境错误"
    "（根目录或 测试中心/ 不存在）。"
)


def 构造解析器() -> argparse.ArgumentParser:
    解析器 = argparse.ArgumentParser(
        prog="测试体系门禁.py",
        description=门禁说明,
        epilog=退出码说明,
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    解析器.add_argument("-h", "--help", "--帮助", action="help",
                        help="显示本帮助（本门禁的轻检命令）")
    解析器.add_argument("--根", default=str(系统根),
                        help="仓库根目录（默认：本文件所在仓库根）")
    解析器.add_argument("--并发", type=int, default=默认并发,
                        help=f"子进程并发数（默认 {默认并发}）")
    解析器.add_argument("--超时", dest="超时秒", type=int, default=默认超时秒,
                        help=f"单文件导入超时秒数（默认 {默认超时秒}）")
    解析器.add_argument("--连字符即失败", dest="连字符即失败", action="store_true",
                        help="把「跳过（连字符等不可点号导入）」升级为违规")
    解析器.add_argument("--只报告", dest="只报告", action="store_true",
                        help="有违规也返回 0（先报告、后强制）")
    解析器.add_argument("--json", dest="json输出", action="store_true",
                        help="以 JSON 输出完整结果")
    return 解析器


def 运行检查(根: Path, *, 并发: int = 默认并发, 超时秒: int = 默认超时秒,
             连字符即失败: bool = False, 解释器: str | None = None) -> dict:
    """执行三项检查并汇总：只返回结果，不打印、不退出。"""
    根 = Path(根).resolve()
    开始 = time.perf_counter()
    资产列表 = 发现.发现测试文件(根)
    探测结果 = 可导入性检查.检查可导入性(
        根, 资产列表, 并发=并发, 超时秒=超时秒, 解释器=解释器,
    )
    跳过项 = [
        {"文件": 资产.相对路径, "细节": 资产.跳过原因}
        for 资产 in 资产列表 if 资产.跳过原因
    ]
    违规: list[dict] = []
    违规.extend(可导入性检查.导入失败违规(探测结果))
    违规.extend(零测试检查.零测试违规(探测结果, 资产列表))
    违规.extend(跳过检查.未解释跳过违规(资产列表))
    if 连字符即失败:
        违规.extend(
            {"类型": "跳过资产未守护", "文件": 条["文件"], "行号": None,
             "细节": f"{条['细节']}（--连字符即失败 已升级为违规）"}
            for 条 in 跳过项
        )
    return {
        "相对根": str(根),
        "测试文件数": len(资产列表),
        "参与数": sum(1 for 资产 in 资产列表 if not 资产.跳过原因),
        "导入成功数": sum(1 for 项 in 探测结果 if 项["导入成功"]),
        "用例总数": sum(int(项["用例数"] or 0) for 项 in 探测结果 if 项["导入成功"]),
        "跳过数": len(跳过项),
        "跳过": 跳过项,
        "违规": 违规,
        "耗时秒": time.perf_counter() - 开始,
    }


def 运行门禁(根: Path, *, 并发: int = 默认并发, 超时秒: int = 默认超时秒,
             连字符即失败: bool = False) -> list[dict]:
    """门禁入口（供发布门禁调用）：返回违规清单，空列表即通过；不打印。"""
    return 运行检查(根, 并发=并发, 超时秒=超时秒, 连字符即失败=连字符即失败)["违规"]


def 主程序(参数: list[str] | None = None) -> int:
    解析 = 构造解析器().parse_args(参数)
    根 = Path(解析.根).resolve()
    if not (根 / 发现.测试中心目录名).is_dir():
        print(f"环境错误：{根} 下不存在 {发现.测试中心目录名}/ 目录", file=sys.stderr)
        return 2
    结果 = 运行检查(
        根, 并发=max(1, 解析.并发), 超时秒=max(1, 解析.超时秒),
        连字符即失败=解析.连字符即失败,
    )
    print(报告.生成json报告(结果) if 解析.json输出 else 报告.生成文本报告(结果))
    if not 结果["违规"]:
        return 0
    if 解析.只报告:
        print(f"（--只报告：本次 {len(结果['违规'])} 项违规按约定不阻断，退出码 0）")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(主程序())
