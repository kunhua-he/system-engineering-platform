"""能力 id 冻结基线的反向验证（第 29 项 完成判据）。

**为什么用夹具根**：判据「id 只增不改」要真验，必须有人真的把某条能力 id 从
``能力定义.json`` 里删掉；在真实仓库里删 id 就是「改各包能力定义」——本任务的
只改范围明确禁止。故反向破坏全部落在 ``tempfile`` 里的**夹具根**（真实
``支持库/…/包声明.json`` + ``能力定义.json`` 两件套 + 真实判据链），基线也写成
夹具自己的文件。真实仓库只做两件事：默认路径跑绿、临时改名真基线验 fail-closed
（改完立刻改回，不落任何修改）。

三档完成判据（原文）：
  ① 删一条基线里的 id → 必红；
  ② 把基线文件删掉 → 必红（fail-closed）；
  ③ 恢复 → 绿。
另加 fail-closed 的其余形态（基线坏 JSON／条目为空／扫描面为空）与「契约变更
允许但留痕」的正向对照，防止门禁退化成恒红。

直跑：``python3.14 开发工具/验证_能力id冻结基线反向验证.py``；退出码 0 = 全通过。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

根 = Path(__file__).resolve().parents[1]
门禁 = 根 / "开发工具" / "能力id冻结基线门禁.py"
真基线 = 根 / "开发文档" / "项目证据" / "能力id冻结基线.json"

夹具能力一 = "夹具.包甲.能力一"
夹具能力二 = "夹具.包乙.能力二"
夹具能力三 = "夹具.包甲.能力三"


def 写(路径: Path, 文本: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(文本, encoding="utf-8")


def 写包(包目录: Path, 包id: str, 能力们: list[dict]) -> None:
    """真实两件套：包声明.json（能力列表）+ 能力定义.json（能力列表，带指纹字段）。"""
    写(包目录 / "包声明.json", json.dumps(
        {"包id": 包id, "名称": 包目录.name, "类型": "支持库",
         "能力": [{"能力id": 条["能力id"], "名称": 条["能力id"].split(".")[-1]} for 条 in 能力们]},
        ensure_ascii=False, indent=1))
    写(包目录 / "能力定义.json", json.dumps(
        {"包id": 包id, "版本": "1.0.0", "能力列表": 能力们}, ensure_ascii=False, indent=1))


def 造夹具根(父目录: Path) -> Path:
    夹具 = 父目录 / "夹具根"
    写包(夹具 / "支持库" / "后端" / "夹具包甲", "支持库.后端.夹具包甲", [
        {"能力id": 夹具能力一, "版本": "1.0.0",
         "参数": [{"名称": "输入", "类型": "文本型", "必填": True}],
         "返回": {"类型": "结果型", "值结构": {"值": "文本"}},
         "错误码": ["参数不合法"]},
    ])
    写包(夹具 / "支持库" / "后端" / "夹具包乙", "支持库.后端.夹具包乙", [
        {"能力id": 夹具能力二, "版本": "1.0.0",
         "参数": [], "返回": {"类型": "逻辑型", "值结构": {"存在": "布尔"}},
         "错误码": []},
    ])
    return 夹具


def 跑(目标根: Path, 基线路径: Path) -> tuple[int, str]:
    结果 = subprocess.run(
        [sys.executable, str(门禁), str(目标根), "--基线", str(基线路径)],
        cwd=str(根), capture_output=True, text=True)
    return 结果.returncode, 结果.stdout + 结果.stderr


结果集: list[tuple[bool, str]] = []


def 断言(名: str, 条件: bool, 实际: str) -> None:
    结果集.append((条件, f"{'✅' if 条件 else '❌'} {名}｜{实际}"))


def main() -> int:
    临时 = Path(tempfile.mkdtemp(prefix="能力id冻结反向验证_"))
    通过 = True
    try:
        夹具 = 造夹具根(临时)
        基线 = 临时 / "夹具冻结基线.json"

        # ============ 夹具态：冻结 + 三档判据 ============
        冻结 = subprocess.run([sys.executable, str(门禁), str(夹具),
                              "--冻结", "--基线", str(基线)],
                             cwd=str(根), capture_output=True, text=True)
        冻结出 = 冻结.stdout + 冻结.stderr
        断言("夹具冻结", 冻结.returncode == 0 and "已冻结 2 条" in 冻结出,
             f"退出码={冻结.returncode}；{冻结出.strip().splitlines()[-1] if 冻结出.strip() else ''}")

        码, 出 = 跑(夹具, 基线)
        断言("夹具基线态", 码 == 0 and "通过" in 出, f"退出码={码}（应=0）")

        # ---- ① 删一条基线里的 id → 必红 ----
        # 破坏点 = 真的把能力一从 夹具包甲/能力定义.json 里删掉（等价于「改/删了 id」）。
        甲 = 夹具 / "支持库" / "后端" / "夹具包甲"
        定义 = json.loads((甲 / "能力定义.json").read_text(encoding="utf-8"))
        assert any(条["能力id"] == 夹具能力一 for 条 in 定义["能力列表"]), "夹具里应有能力一"
        定义["能力列表"] = [条 for 条 in 定义["能力列表"] if 条["能力id"] != 夹具能力一]
        (甲 / "能力定义.json").write_text(json.dumps(定义, ensure_ascii=False, indent=1), encoding="utf-8")
        声明 = json.loads((甲 / "包声明.json").read_text(encoding="utf-8"))
        声明["能力"] = [条 for 条 in 声明.get("能力", []) if 条.get("能力id") != 夹具能力一]
        (甲 / "包声明.json").write_text(json.dumps(声明, ensure_ascii=False, indent=1), encoding="utf-8")
        码, 出 = 跑(夹具, 基线)
        断言("① 删一条基线里的 id（能力定义+包声明同步摘除）",
             码 == 1 and "能力id消失" in 出 and 夹具能力一 in 出,
             f"退出码={码}（应=1）；含『能力id消失』={'能力id消失' in 出}；含被删 id={夹具能力一 in 出}")

        # ---- ①b 改名（只增不改的另一形态：老 id 消失）→ 必红 ----
        定义["能力列表"] = [{"能力id": "夹具.包甲.能力一改名", "版本": "1.0.0",
                          "参数": [], "返回": {"类型": "结果型", "值结构": {}}, "错误码": []}]
        (甲 / "能力定义.json").write_text(json.dumps(定义, ensure_ascii=False, indent=1), encoding="utf-8")
        声明["能力"] = [{"能力id": "夹具.包甲.能力一改名", "名称": "能力一改名"}]
        (甲 / "包声明.json").write_text(json.dumps(声明, ensure_ascii=False, indent=1), encoding="utf-8")
        码, 出 = 跑(夹具, 基线)
        断言("①b 改 id 名（新增一条 + 老 id 消失）",
             码 == 1 and "能力id消失" in 出 and 夹具能力一 in 出 and "新增能力id" in 出,
             f"退出码={码}（应=1）；消失项有={夹具能力一 in 出}；新增加报有={'新增能力id' in 出}")

        # ---- 恢复夹具到冻结态 → 绿（三档里的第 ③ 档第一半）----
        写包(甲, "支持库.后端.夹具包甲", [
            {"能力id": 夹具能力一, "版本": "1.0.0",
             "参数": [{"名称": "输入", "类型": "文本型", "必填": True}],
             "返回": {"类型": "结果型", "值结构": {"值": "文本"}},
             "错误码": ["参数不合法"]},
        ])
        码, 出 = 跑(夹具, 基线)
        断言("③a 恢复能力定义", 码 == 0 and "通过" in 出, f"退出码={码}（应=0）")

        # ---- ② 把基线文件删掉 → 必红（fail-closed）----
        基线.unlink()
        码, 出 = 跑(夹具, 基线)
        断言("② 基线文件缺失",
             码 == 1 and "基线文件缺失" in 出 and "fail-closed" in 出,
             f"退出码={码}（应=1）；含『基线文件缺失』={'基线文件缺失' in 出}；含 fail-closed={'fail-closed' in 出}")

        # ---- ②b 基线坏 JSON → 必红 ----
        基线.write_text("{ 这不是 JSON", encoding="utf-8")
        码, 出 = 跑(夹具, 基线)
        断言("②b 基线文件不可读（坏 JSON）",
             码 == 1 and "基线文件不可读" in 出,
             f"退出码={码}（应=1）；含『基线文件不可读』={'基线文件不可读' in 出}")

        # ---- ②c 基线条目为空 → 必红 ----
        基线.write_text(json.dumps({"版本": 1, "条目": {}}, ensure_ascii=False), encoding="utf-8")
        码, 出 = 跑(夹具, 基线)
        断言("②c 基线条目为空（空基线不是通过）",
             码 == 1 and "形状非法" in 出,
             f"退出码={码}（应=1）；含『形状非法』={'形状非法' in 出}")

        # ---- ②d 扫描面为空（根下无正式包）→ 必红 ----
        空根 = 临时 / "空根"
        (空根 / "支持库").mkdir(parents=True, exist_ok=True)
        码, 出 = 跑(空根, 基线)
        断言("②d 扫描面为空（0 条能力 id）",
             码 == 1 and "扫描面为空" in 出,
             f"退出码={码}（应=1）；含『扫描面为空』={'扫描面为空' in 出}")

        # ---- ③ 恢复基线 → 绿 ----
        子进程 = subprocess.run([sys.executable, str(门禁), str(夹具),
                               "--冻结", "--基线", str(基线)],
                              cwd=str(根), capture_output=True, text=True)
        assert 子进程.returncode == 0, 子进程.stdout + 子进程.stderr
        码, 出 = 跑(夹具, 基线)
        断言("③b 恢复基线", 码 == 0 and "通过" in 出, f"退出码={码}（应=0）")

        # ---- 正向对照：内容指纹变化 → 允许但留痕（防门禁退化成恒红）----
        写包(甲, "支持库.后端.夹具包甲", [
            {"能力id": 夹具能力一, "版本": "1.1.0",
             "参数": [{"名称": "输入", "类型": "文本型", "必填": True},
                    {"名称": "编码", "类型": "文本型", "必填": False}],
             "返回": {"类型": "结果型", "值结构": {"值": "文本"}},
             "错误码": ["参数不合法", "文件不存在"]},
        ])
        码, 出 = 跑(夹具, 基线)
        断言("④ 已存 id 内容指纹变化（契约变更合法，允许但留痕）",
             码 == 0 and "内容指纹变化" in 出,
             f"退出码={码}（应=0）；含『内容指纹变化』={'内容指纹变化' in 出}")

        # ---- 正向对照：新增 id → 允许只报 ----
        写包(甲, "支持库.后端.夹具包甲", [
            {"能力id": 夹具能力一, "版本": "1.1.0",
             "参数": [{"名称": "输入", "类型": "文本型", "必填": True},
                    {"名称": "编码", "类型": "文本型", "必填": False}],
             "返回": {"类型": "结果型", "值结构": {"值": "文本"}},
             "错误码": ["参数不合法", "文件不存在"]},
            {"能力id": 夹具能力三, "版本": "1.0.0", "参数": [],
             "返回": {"类型": "结果型", "值结构": {}}, "错误码": []},
        ])
        码, 出 = 跑(夹具, 基线)
        断言("⑤ 新增能力 id（只增的合法方向，只报不拦）",
             码 == 0 and "新增能力id" in 出 and 夹具能力三 in 出,
             f"退出码={码}（应=0）；含『新增能力id』={'新增能力id' in 出}")

        # ============ 真实仓库：默认路径绿 + 临时改名真基线验 fail-closed ============
        结果 = subprocess.run([sys.executable, str(门禁)], cwd=str(根),
                             capture_output=True, text=True)
        真出 = 结果.stdout + 结果.stderr
        真基线数 = len(json.loads(真基线.read_text(encoding="utf-8"))["条目"])
        断言("⑥ 真实仓库默认路径跑绿",
             结果.returncode == 0 and "通过" in 真出,
             f"退出码={结果.returncode}（应=0）；基线条目数={真基线数}")

        备份 = 真基线.with_name(真基线.name + ".反向验证备份")
        assert not 备份.exists(), f"备份路径已存在，拒绝覆盖: {备份}"
        真基线.rename(备份)
        try:
            结果 = subprocess.run([sys.executable, str(门禁)], cwd=str(根),
                                 capture_output=True, text=True)
            码, 出 = 结果.returncode, 结果.stdout + 结果.stderr
        finally:
            备份.rename(真基线)
        断言("⑦ 真实默认基线缺失（未传 --基线）必须 fail-closed",
             码 == 1 and "基线文件缺失" in 出,
             f"退出码={码}（应=1）；含『基线文件缺失』={'基线文件缺失' in 出}")

        结果 = subprocess.run([sys.executable, str(门禁)], cwd=str(根),
                             capture_output=True, text=True)
        断言("⑧ 真基线恢复后默认跑绿", 结果.returncode == 0, f"退出码={结果.returncode}（应=0）")
        断言("⑨ 真基线文件已复原（未被破坏）", 真基线.is_file(), f"存在={真基线.is_file()}")

    finally:
        shutil.rmtree(临时, ignore_errors=True)

    for 条, 文本 in 结果集:
        print(文本)
        通过 = 通过 and 条
    print(f"\n共 {len(结果集)} 项断言｜" + ("全部通过" if 通过 else "**有失败**"))
    return 0 if 通过 else 1


if __name__ == "__main__":
    sys.exit(main())
