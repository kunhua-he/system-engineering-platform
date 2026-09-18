"""开发编译口：底座开发循环的一键口（华哥 2026-09-19 裁决「易语言模式」）。

一条命令完成：影响面清单 → 生成物核对 → 静态规则全查 → 定向测试点名。
全部被编排的检查器都是现成件，本口只做编排与结论归并，不新建第二套判据。

用法：
    python3.14 -m 开发工具.开发编译口.编译口 --变更          # 默认：读 git 变更集（含未跟踪）
    python3.14 -m 开发工具.开发编译口.编译口 --文件 路径1 路径2  # 并行期显式点名自己的文件
    python3.14 -m 开发工具.开发编译口.编译口 --全仓          # 全仓口径（影响面按全量叙述）
    python3.14 -m 开发工具.开发编译口.编译口 --自证          # 编译口自身三拍（绿/红/恢复）
    可选 --联动：允许重算生成物（默认只读，等价 全量重算摘要 --只报）

退出码：0 干净通过（可含 只报告/债务冻结 信息）；1 失败（有红项）；2 未核验（门禁自身无法执行）。
五态结论（对齐哲学第 13 条）：干净通过 / 债务冻结 / 只报告 / 未核验 / 失败。
"""
from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
import time
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]

# 静态门禁清单：名字 / 模块入口 / 参数 / 角色（阻断=红绿判定，只报告=展示不判定）/ 单项超时秒。
门禁清单 = [
    {"名字": "摘要闭合", "模块": "开发工具.全量重算摘要", "参数": ["--只报"], "角色": "阻断", "超时秒": 120},
    {"名字": "契约漂移", "模块": "开发工具.契约编译.漂移检测", "参数": ["--报告"], "角色": "只报告", "超时秒": 120},
    {"名字": "公开调用完整性", "模块": "开发工具.公开调用完整性门禁", "参数": [], "角色": "阻断", "超时秒": 120},
    {"名字": "能力id冻结基线", "模块": "开发工具.能力id冻结基线门禁", "参数": [], "角色": "阻断", "超时秒": 120},
    {"名字": "验证场景体检", "模块": "开发工具.验证场景体检", "参数": [], "角色": "阻断", "超时秒": 120},
]

每门禁输出行数 = 6


def _跑(命令列表: list[str], 超时秒: int = 120) -> tuple[int, str, float]:
    """跑一条命令，返回（退出码，尾部输出，耗时秒）。超时/崩溃按退出码 -1 记（未核验）。"""
    开始 = time.monotonic()
    try:
        完成 = subprocess.run(
            命令列表, capture_output=True, text=True, timeout=超时秒, cwd=str(系统根),
        )
        输出 = (完成.stdout or "") + (完成.stderr or "")
        return 完成.returncode, 输出.strip(), time.monotonic() - 开始
    except subprocess.TimeoutExpired:
        return -1, f"超时（>{超时秒}秒，按未核验处理，绝不按通过处理）", time.monotonic() - 开始
    except OSError as 异常:
        return -1, f"无法执行：{异常}", time.monotonic() - 开始


def _尾部(文本: str, 行数: int = 每门禁输出行数) -> str:
    行列表 = [行 for 行 in 文本.splitlines() if 行.strip()]
    return "\n".join(行列表[-行数:]) if 行列表 else "（无输出）"


def _git变更文件() -> list[str]:
    """git 变更集（含未跟踪，-uall 让新目录里的文件逐个列出），返回相对路径列表；删除条目自然排除。"""
    退出码, 输出, _ = _跑(["git", "status", "--porcelain", "-uall"], 超时秒=30)
    if 退出码 != 0:
        raise RuntimeError(f"git status 不可用：{输出[:200]}")
    文件列表 = []
    for 行 in 输出.splitlines():
        if len(行) < 4:
            continue
        状态, 路径 = 行[:2], 行[3:].strip().strip('"')
        if 状态.strip() in {"D", "R"}:
            # 重命名取新名（porcelain 的 R 行是 "旧 -> 新"）。
            if "->" in 路径:
                路径 = 路径.split("->")[-1].strip()
            else:
                continue
        if not 路径:
            continue
        if any(段 in 路径 for 段 in ("__pycache__",)) or 路径.startswith(("工程缓存/", ".git/")):
            continue
        文件列表.append(路径)
    return 文件列表


def _包id(路径文本: str) -> str | None:
    """文件 → 所属包：向上找最近的 包声明.json。"""
    当前 = (系统根 / 路径文本).resolve()
    if not 当前.exists():
        当前 = 当前.parent
    for 候选 in (当前, *当前.parents):
        if (候选 / "包声明.json").is_file():
            try:
                import json
                return str(json.loads((候选 / "包声明.json").read_text(encoding="utf-8")).get("包id") or "")
            except Exception:
                return 候选.name
        if 候选 == 系统根:
            break
    return None


def _影响面(变更文件列表: list[str]) -> dict[str, list[str]]:
    """受影响包 + 反向依赖闭包（按包声明.json 的 依赖 字段逐层扩散）。"""
    import json
    受影响: set[str] = set()
    非包文件: list[str] = []
    for 路径文本 in 变更文件列表:
        包id = _包id(路径文本)
        if 包id:
            受影响.add(包id)
        else:
            非包文件.append(路径文本)

    依赖表: dict[str, list[str]] = {}
    for 声明路径 in 系统根.rglob("包声明.json"):
        相对 = 声明路径.relative_to(系统根)
        if any(段 in {"工程缓存", ".git", "__pycache__"} for 段 in 相对.parts):
            continue
        try:
            数据 = json.loads(声明路径.read_text(encoding="utf-8"))
            依赖表[str(数据.get("包id") or "")] = [str(项) for 项 in (数据.get("依赖") or [])]
        except Exception:
            continue
    反向: dict[str, set[str]] = {}
    for 包id, 依赖列表 in 依赖表.items():
        for 被依赖 in 依赖列表:
            反向.setdefault(被依赖, set()).add(包id)

    已扩散: set[str] = set()
    队列 = list(受影响)
    while 队列:
        当前 = 队列.pop()
        if 当前 in 已扩散:
            continue
        已扩散.add(当前)
        队列.extend(反向.get(当前, ()))
    摘要联动提示 = sorted(
        {包id.rsplit(".", 1)[0] for 包id in 已扩散 if 包id.count(".") >= 3},
    )
    return {
        "受影响包": sorted(受影响),
        "反向依赖闭包": sorted(已扩散 - 受影响),
        "非包文件": sorted(非包文件),
        "摘要联动提示": 摘要联动提示,
    }


def _定向测试点名(受影响包: list[str]) -> list[str]:
    """受影响包短名 → 测试中心里文件名含该短名的模块（只点名，不执行）。"""
    短名列表 = [包id.rsplit(".", 1)[-1] for 包id in 受影响包 if 包id]
    命中: set[str] = set()
    测试根 = 系统根 / "测试中心"
    for 测试文件 in 测试根.rglob("测试_*.py"):
        文件名 = 测试文件.stem
        if any(短名 and 短名 in 文件名 for 短名 in 短名列表):
            相对 = 测试文件.relative_to(系统根)
            命中.add(".".join(相对.with_suffix("").parts))
    return sorted(命中)


def _变更py编译(变更文件列表: list[str]) -> tuple[int, str]:
    """只编译变更集里的 .py 文件（全仓模式由 --全仓 显式选择）。"""
    目标 = [str(系统根 / 路径文本) for 路径文本 in 变更文件列表 if 路径文本.endswith(".py")]
    if not 目标:
        return 0, "变更集无 .py 文件，跳过语法编译"
    退出码, 输出, _ = _跑(["python3.14", "-m", "py_compile", *目标], 超时秒=120)
    return 退出码, 输出 or f"{len(目标)} 个 .py 编译通过"


def _三拍自证() -> int:
    """编译口自身三拍：绿拍（真门禁必绿）→ 红拍（坏样本必红）→ 恢复拍（清理后归绿）。"""
    print("── 三拍自证：绿拍 ──")
    退出码, 输出, _ = _跑(["python3.14", "-m", "开发工具.能力id冻结基线门禁"], 超时秒=120)
    print(f"  能力id冻结基线门禁 退出码={退出码}（期望 0）：{_尾部(输出, 1)}")
    绿拍成立 = 退出码 == 0

    print("── 三拍自证：红拍（故意弄坏，必须红）──")
    坏样本目录 = Path("/tmp/开发编译口自证")
    坏样本目录.mkdir(parents=True, exist_ok=True)
    坏样本 = 坏样本目录 / "坏样本.py"
    坏样本.write_text("def 残缺(:\n", encoding="utf-8")
    退出码, 输出, _ = _跑(["python3.14", "-m", "py_compile", str(坏样本)], 超时秒=60)
    print(f"  坏样本 py_compile 退出码={退出码}（期望非 0）：{_尾部(输出, 1)}")
    红拍成立 = 退出码 != 0

    print("── 三拍自证：恢复拍（清理后必须归绿）──")
    坏样本.unlink(missing_ok=True)
    退出码, 输出, _ = _跑(["python3.14", "-m", "py_compile", str(系统根 / "开发工具/开发编译口/编译口.py")], 超时秒=60)
    print(f"  编译口本体 py_compile 退出码={退出码}（期望 0）")
    恢复拍成立 = 退出码 == 0 and not 坏样本.exists()

    if 绿拍成立 and 红拍成立 and 恢复拍成立:
        print("三拍自证通过：绿必绿 / 坏必红 / 恢复归绿。")
        return 0
    print(f"三拍自证失败：绿拍={绿拍成立} 红拍={红拍成立} 恢复拍={恢复拍成立}")
    return 1


def 主函数() -> int:
    解析 = argparse.ArgumentParser(description="开发编译口：改完文件后的一键静态全查")
    范围 = 解析.add_mutually_exclusive_group(required=True)
    范围.add_argument("--变更", action="store_true", help="读 git 变更集（含未跟踪文件）")
    范围.add_argument("--文件", nargs="+", metavar="路径", help="显式点名文件（并行期推荐）")
    范围.add_argument("--全仓", action="store_true", help="全仓口径")
    范围.add_argument("--自证", action="store_true", help="编译口自身三拍自证")
    解析.add_argument("--联动", action="store_true", help="允许重算生成物（默认只读）")
    参数 = 解析.parse_args()

    if 参数.自证:
        return _三拍自证()

    print("═══ 开发编译口（易语言模式：一次编译，规则全查）═══")
    if 参数.变更:
        变更文件 = _git变更文件()
    elif 参数.文件:
        变更文件 = list(参数.文件)
    else:
        变更文件 = []

    影响面 = _影响面(变更文件) if not 参数.全仓 else {
        "受影响包": ["（全仓口径）"], "反向依赖闭包": [], "非包文件": [], "摘要联动提示": [],
    }
    print(f"── 阶段甲 影响面：变更文件 {len(变更文件)} 个，受影响包 {len(影响面['受影响包'])}，"
          f"反向依赖闭包 {len(影响面['反向依赖闭包'])}，非包文件 {len(影响面['非包文件'])}")
    for 标签, 键 in (("受影响包", "受影响包"), ("反向依赖闭包", "反向依赖闭包")):
        if 影响面[键]:
            print(f"  {标签}：{', '.join(影响面[键][:12])}{' …' if len(影响面[键]) > 12 else ''}")

    未核验 = False
    失败门禁: list[str] = []

    print("── 阶段乙 生成物核对（默认只读；--联动 才重算写入）──")
    if 参数.联动:
        退出码, 输出, 耗时 = _跑(["python3.14", "-m", "开发工具.全量重算摘要"], 超时秒=180)
        print(f"  全量重算摘要（联动写入）退出码={退出码} 耗时={耗时:.2f}s：{_尾部(输出, 2)}")
    else:
        退出码, 输出, 耗时 = _跑(["python3.14", "-m", "开发工具.全量重算摘要", "--只报"], 超时秒=120)
        print(f"  摘要闭合核对（只报）退出码={退出码} 耗时={耗时:.2f}s：{_尾部(输出, 2)}")
    if 退出码 == -1:
        未核验 = True
    elif 退出码 != 0:
        失败门禁.append(f"摘要闭合（退出码 {退出码}）")

    print("── 阶段丙 静态规则全查 ──")
    if 变更文件:
        退出码, 输出 = _变更py编译(变更文件)
        print(f"  变更 .py 语法编译 退出码={退出码}：{_尾部(输出, 2)}")
        if 退出码 == -1:
            未核验 = True
        elif 退出码 != 0:
            失败门禁.append("变更 .py 语法编译")

    for 门禁 in 门禁清单:
        退出码, 输出, 耗时 = _跑(
            ["python3.14", "-m", 门禁["模块"], *门禁["参数"]], 超时秒=门禁["超时秒"],
        )
        角色标注 = "阻断" if 门禁["角色"] == "阻断" else "只报告"
        print(f"  [{角色标注}] {门禁['名字']} 退出码={退出码} 耗时={耗时:.2f}s：{_尾部(输出, 2)}")
        if 门禁["角色"] != "阻断":
            continue
        if 退出码 == -1:
            未核验 = True
        elif 退出码 != 0:
            失败门禁.append(f"{门禁['名字']}（退出码 {退出码}）")

    点名 = _定向测试点名(影响面["受影响包"]) if 影响面["受影响包"] and 影响面["受影响包"][0] != "（全仓口径）" else []
    print(f"── 阶段戊 定向测试点名（默认不执行，{len(点名)} 个候选）──")
    for 模块名 in 点名[:8]:
        print(f"  python3.14 -m unittest {模块名}")

    print("═══ 结论 ═══")
    if 未核验:
        print("五态结论：未核验 —— 有门禁自身无法执行，本轮不许当通过处理（fail-closed）。")
        return 2
    if 失败门禁:
        print(f"五态结论：失败 —— 阻断类红项：{'、'.join(失败门禁)}。按红项修完再跑一遍。")
        return 1
    print("五态结论：干净通过（只报告类信息见上方各门禁输出；存量冻结债以登记基线为准）。")
    return 0


if __name__ == "__main__":
    sys.exit(主函数())
