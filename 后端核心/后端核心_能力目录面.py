"""能力目录面：Skill 式四层渐进披露（能力搜索/能力目录/包详情/能力详情）（混入类）。

**为什么独立成文件**：这是「调用方读契约」的**只读读取面** —— 四层渐进披露
（`能力搜索` → `能力目录` → `包详情` → `能力详情`）与三个只读助手
（`_紧凑说明` / `_包目录路径` / `_读取JSON`）。它与装配/调用/生命周期完全解耦：
不改注册表、不起线程、不落盘，只按包声明与参数契约读文件，是宿主里最可独立
审阅与独立测试的一簇（`测试中心/运行核心/测试_渐进能力目录.py` 走网关黑盒覆盖）。

**对外零变化（2026-09-19 拆分）**：本文件成员逐字取自冻结基线
`/tmp/拆分基线/后端核心.py`（812 行，sha256 前16 = 7fa787df454402a3，对应 HEAD
干净工作区），成员名、签名、默认值、函数体一个不改。

**宿主契约**（类注解，真源＝`后端核心.py` `后端核心.__init__`）：
`系统根目录` / `注册表`。

**安全边界（逐字保留）**：`_包目录路径` 只允许读取**已注册包**自己的公开声明
目录，并做 `relative_to(系统根目录)` 越界拦截 —— 改动即越权读文件。

**导入方向**：本文件只被 `后端核心.py` 模块级导入，**不得反向导入** `后端核心.py`。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class 能力目录面:
    """四层渐进披露读取簇。

    宿主契约（类注解，真源＝`后端核心.后端核心.__init__`）：
    `系统根目录` / `注册表`。
    """

    系统根目录: Path
    注册表: Any

    def 能力搜索(self, *, 关键词: str = "", 限制: int = 20) -> list[dict]:
        """按关键词返回紧凑候选；完整契约只能经 能力详情 按需读取。"""
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        return [
            {"能力id": 能力id, "包id": self.注册表.获取(能力id).包id,
             "简介": self._紧凑说明(self.注册表.获取(能力id).说明 or "")}
            for 能力id in self.注册表.能力id列表
            if not 关键词 or 关键词 in 能力id or 关键词 in (self.注册表.获取(能力id).说明 or "")
        ][:限制]

    @staticmethod
    def _紧凑说明(说明: str, 上限: int = 60) -> str:
        """目录简介最多 60 字；去除换行和多余空白。"""
        文本 = " ".join(str(说明 or "").split())
        return 文本 if len(文本) <= 上限 else 文本[:上限 - 1] + "…"

    def _包目录路径(self, 包id: str) -> Path | None:
        """仅允许读取已注册包自己的公开声明目录。"""
        if not isinstance(包id, str) or not 包id:
            return None
        已注册包 = {
            self.注册表.获取(能力id).包id for 能力id in self.注册表.能力id列表
        }
        if 包id not in 已注册包:
            return None
        候选 = self.系统根目录.joinpath(*包id.split(".")).resolve()
        try:
            候选.relative_to(self.系统根目录.resolve())
        except ValueError:
            return None
        return 候选 if (候选 / "包声明.json").is_file() else None

    @staticmethod
    def _读取JSON(路径: Path) -> dict:
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return 数据 if isinstance(数据, dict) else {}

    def 能力目录(self, *, 关键词: str = "", 偏移: int = 0, 限制: int = 20) -> dict:
        """Skill 式第一层：分页返回包级树和紧凑简介，不返回命令参数。

        四个桶（支持库按领域二级分组 / 模块库 / 技能库 / 其他库）恒存在，
        当前页每包只落一个桶，故 包数 与各桶条目总数相等、分页走查不漏包。
        """
        if isinstance(偏移, bool) or not isinstance(偏移, int) or 偏移 < 0:
            偏移 = 0
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        包表: dict[str, dict] = {}
        for 能力id in self.注册表.能力id列表:
            实现 = self.注册表.获取(能力id)
            if 实现.包id in 包表:
                包表[实现.包id]["能力数"] += 1
                continue
            包目录 = self._包目录路径(实现.包id)
            声明 = self._读取JSON(包目录 / "包声明.json") if 包目录 else {}
            名称 = str(声明.get("名称") or 实现.包id.rsplit(".", 1)[-1])
            简介 = self._紧凑说明(str(声明.get("说明") or 实现.说明 or ""))
            包表[实现.包id] = {
                "包id": 实现.包id, "名称": 名称, "简介": 简介, "能力数": 1,
            }
        if 关键词:
            包表 = {
                包id: 条目 for 包id, 条目 in 包表.items()
                if 关键词 in 包id or 关键词 in 条目["名称"] or 关键词 in 条目["简介"]
            }
        包条目表 = [条目 for _, 条目 in sorted(包表.items())]
        总数 = len(包条目表)
        当前页 = 包条目表[偏移:偏移 + 限制]
        下一偏移 = 偏移 + len(当前页)
        支持库树: dict[str, list[dict]] = {}
        模块库列表: list[dict] = []
        技能库列表: list[dict] = []
        其他库列表: list[dict] = []
        # 分桶必须完备：当前页每一条只能落一个桶，否则 包数 虚高、下一偏移
        # 跨过一个永远取不到的包（技能库 前缀原就如此被静默丢掉，分页走查
        # 也永远走不到它）。未知前缀一律进「其他库」，保证收纳总数守恒。
        for 条目 in 当前页:
            包id = 条目["包id"]
            根库名 = 包id.split(".", 1)[0]
            if 根库名 == "支持库":
                分段 = 包id.split(".")
                领域 = 分段[1] if len(分段) > 2 else "其他"
                支持库树.setdefault(领域, []).append(条目)
            elif 根库名 == "模块库":
                模块库列表.append(条目)
            elif 根库名 == "技能库":
                技能库列表.append(条目)
            else:
                其他库列表.append(条目)
        return {
            "使用顺序": ["选择包", "查看包详情", "查看能力详情", "调用能力"],
            "支持库": [{"领域": 领域, "包": 包列表} for 领域, 包列表 in sorted(支持库树.items())],
            "模块库": 模块库列表,
            "技能库": 技能库列表,
            "其他库": 其他库列表,
            "包数": len(当前页),
            "总包数": 总数,
            "偏移": 偏移,
            "限制": 限制,
            "下一偏移": 下一偏移 if 下一偏移 < 总数 else None,
            "是否完成": 下一偏移 >= 总数,
        }

    def 包详情(self, 包id: str) -> dict | None:
        """Skill 式第二层：只返回该包的命令目录，不展开参数正文。"""
        包目录 = self._包目录路径(包id)
        if 包目录 is None:
            return None
        声明 = self._读取JSON(包目录 / "包声明.json")
        命令表 = []
        for 能力 in 声明.get("能力", []):
            if not isinstance(能力, dict) or not 能力.get("能力id"):
                continue
            命令表.append({
                "能力id": 能力["能力id"],
                "名称": 能力.get("名称") or str(能力["能力id"]).rsplit(".", 1)[-1],
                "简介": self._紧凑说明(str(能力.get("说明") or "")),
            })
        return {
            "包id": 包id, "名称": 声明.get("名称", ""),
            "简介": self._紧凑说明(str(声明.get("说明") or "")),
            "版本": 声明.get("版本", ""), "命令": 命令表,
            "下一步": "选中能力id后调用 能力详情；此处不返回参数正文",
        }

    def 能力详情(self, 能力id: str) -> dict | None:
        """Skill 式第三层：按需读取单个能力的完整权威契约和调用方式。"""
        实现 = self.注册表.获取(能力id)
        if 实现 is None:
            return None
        包目录 = self._包目录路径(实现.包id)
        if 包目录 is None:
            return None
        契约总表 = self._读取JSON(包目录 / "能力契约" / "参数契约.json")
        能力表 = 契约总表.get("能力契约", 契约总表.get("能力列表", []))
        正文 = next((项 for 项 in 能力表
                   if isinstance(项, dict) and 项.get("能力id") == 能力id), None)
        if 正文 is None:
            正文 = {
                "能力id": 能力id, "说明": 实现.说明,
                "参数": 实现.参数, "返回": {"类型": 实现.返回},
            }
        声明 = self._读取JSON(包目录 / "包声明.json")
        返回正文 = copy.deepcopy(正文)
        返回正文["包id"] = 实现.包id
        返回正文["包版本"] = 声明.get("版本", 实现.版本)
        返回正文["契约版本"] = 契约总表.get("契约版本", "")
        返回正文["依赖"] = 声明.get("依赖", [])
        返回正文["配置契约"] = self._读取JSON(包目录 / "配置契约" / "配置契约.json")
        返回正文["资源预算"] = self._读取JSON(包目录 / "资源预算.json")
        返回正文["调用方式"] = {
            "操作": "调用能力", "目标": 能力id,
            "参数": 正文.get("调用示例", {}).get("参数", 正文.get("调用示例", {})),
        }
        return 返回正文

