"""豁免清单：把「存量违规」与「新增违规」分开的唯一机制。

硬规则 2 的存量是全仓 185 处（`autospec` 计数为 0），若首发即全红，门禁必然
被绕过——这是 `落点清单_02_测试体系.md` 硬规则 2 原文的判断（「避免一次性全红
导致门禁被绕过」「先把历史 185 处列入豁免清单并输出基线数」）。所以「只报不拦」
必须配一份可审计的豁免清单，而不是靠放宽判据。

清单格式（JSON，UTF-8）：

    {
      "规则1": [{"文件": "测试中心/xx/测试_yy.py", "行号": 12, "理由": "依赖注入式替换"}],
      "规则2": [{"文件": "测试中心/xx/测试_yy.py", "行号": null, "理由": "存量基线"}],
      "规则3": []
    }

- 命中键是 `(规则, 文件相对路径, 行号)`；`行号` 为 `null` 表示**整文件**豁免
  （仅建议用于规则 2 的存量基线，理由必写清批次）。
- **理由必填**：空理由条目视为无效，`清单错误` 非空时主程序返回退出码 2
  （fail-closed）——静默吞掉一份写错的清单，会让「豁免生效」与「判据失效」
  在现场无法区分，存量数字随即失去意义。
- 未命中的条目（行号漂移导致失效）单独统计并在报告里列出，避免「豁免静默
  失效 → 旧违规被当成新增违规」或反过来的误判。

本模块只读清单文件：不写、不打印。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

清单文件名 = "豁免清单.json"
规则名集合 = ("规则1", "规则2", "规则3")


@dataclass(frozen=True)
class 豁免条目:
    规则: str
    文件: str
    行号: int | None
    理由: str

    @property
    def 键(self) -> tuple[str, str, int | None]:
        return (self.规则, self.文件, self.行号)


@dataclass
class 豁免表:
    """豁免清单的查询视图；同时记录命中情况以暴露「失效条目」。"""

    条目列表: list[豁免条目] = field(default_factory=list)
    _命中: set[tuple[str, str, int | None]] = field(default_factory=set, repr=False)

    def __bool__(self) -> bool:
        return bool(self.条目列表)

    @property
    def 条目数(self) -> int:
        return len(self.条目列表)

    def 查(self, 规则: str, 文件: str, 行号: int | None) -> str:
        """命中则返回理由并登记命中；未命中返回空字符串。"""
        for 键 in ((规则, 文件, 行号), (规则, 文件, None) if 行号 is not None else None):
            if 键 is None:
                continue
            for 条目 in self.条目列表:
                if 条目.键 == 键:
                    self._命中.add(条目.键)
                    return 条目.理由 or "（清单理由为空）"
        return ""

    def 失效条目(self) -> list[豁免条目]:
        """清单里写了但现场没有再命中的条目（行号漂移 / 已修复）。"""
        return [条目 for 条目 in self.条目列表 if 条目.键 not in self._命中]

    def 命中数(self) -> int:
        return len(self._命中)


def 空豁免表() -> 豁免表:
    return 豁免表()


def 读取豁免清单(路径: Path) -> tuple[豁免表, list[str]]:
    """读取清单 → `(豁免表, 清单错误列表)`；错误非空即 fail-closed。"""
    错误: list[str] = []
    if not 路径.is_file():
        return 空豁免表(), []
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 异常:
        return 空豁免表(), [f"{路径}：JSON 无法解析（{type(异常).__name__}: {异常}）"]
    if not isinstance(数据, dict):
        return 空豁免表(), [f"{路径}：顶层必须是对象（规则名 → 条目列表）"]
    条目列表: list[豁免条目] = []
    for 规则, 原始条目 in 数据.items():
        if 规则 not in 规则名集合:
            continue
        if not isinstance(原始条目, list):
            错误.append(f"{路径}：{规则} 必须是条目列表")
            continue
        for 序号, 条目数据 in enumerate(原始条目, start=1):
            if not isinstance(条目数据, dict):
                错误.append(f"{路径}：{规则} 第 {序号} 条不是对象")
                continue
            文件 = 条目数据.get("文件")
            行号 = 条目数据.get("行号")
            理由 = 条目数据.get("理由")
            if not isinstance(文件, str) or not 文件:
                错误.append(f"{路径}：{规则} 第 {序号} 条缺 `文件`")
                continue
            if 行号 is not None and not isinstance(行号, int):
                错误.append(f"{路径}：{规则} 第 {序号} 条 `行号` 必须是整数或 null")
                continue
            if not isinstance(理由, str) or not 理由.strip():
                错误.append(f"{路径}：{规则} 第 {序号} 条（{文件}）缺 `理由`")
                continue
            条目列表.append(豁免条目(规则=规则, 文件=文件, 行号=行号, 理由=理由.strip()))
    return 豁免表(条目列表=条目列表), 错误
