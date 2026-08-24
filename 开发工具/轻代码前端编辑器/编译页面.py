"""轻代码页面编译器：JSON 页面定义 -> 可校验的规范化前端制品。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

根目录 = Path(__file__).resolve().parents[2]
if str(根目录) not in sys.path:
    sys.path.insert(0, str(根目录))
from 开发工具.轻代码前端编辑器.页面模型 import 校验页面


def 编译(源文件: Path, 输出文件: Path) -> dict[str, Any]:
    try:
        页面 = json.loads(源文件.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"页面 JSON 不可读取: {错误}") from 错误
    页面 = 校验页面(页面)
    组件列表 = []
    对象id集合: set[str] = set()
    组件id集合: set[str] = set()
    能力集合: set[str] = set()
    for 索引, 组件 in enumerate(页面["组件列表"], 1):
        if not isinstance(组件, dict) or not 组件.get("组件id") or not 组件.get("类型"):
            raise ValueError(f"第 {索引} 个组件缺少组件id或类型")
        属性 = 组件.get("属性") or {}
        if not isinstance(属性, dict):
            raise ValueError(f"组件 {组件.get('组件id')} 的属性必须是对象")
        能力id = str(属性.get("能力id", "")).strip()
        if 能力id:
            能力集合.add(能力id)
        for 事件项 in 组件.get("事件", []) or []:
            if isinstance(事件项, dict):
                事件能力id = str(事件项.get("能力id", "")).strip()
                if 事件能力id:
                    能力集合.add(事件能力id)
        对象id = str(组件.get("对象id") or 组件["组件id"])
        if 对象id in 对象id集合:
            raise ValueError(f"对象id重复: {对象id}")
        对象id集合.add(对象id)
        组件id集合.add(str(组件["组件id"]))
        组件列表.append({
            "对象id": 对象id, "组件id": str(组件["组件id"]),
            "显示名称": str(组件.get("显示名称") or 组件["组件id"]), "类型": str(组件["类型"]),
            "父组件id": 组件.get("父组件id"), "父对象id": 组件.get("父对象id"),
            "属性": {str(键): 值 for 键, 值 in 属性.items()},
            "事件": list(组件.get("事件") or []),
        })
    制品 = {
        "制品类型": "轻代码前端制品", "契约版本": "1.0.0",
        "页面": {"工程id": str(页面.get("工程id", "")), "修订号": int(页面.get("修订号", 0)),
                "页面id": str(页面["页面id"]), "标题": str(页面["标题"]),
                "路由": str(页面["路由"]), "项目类型": str(页面.get("项目类型", "软件项目")),
                "组件列表": 组件列表},
        "能力依赖": sorted(能力集合), "编译器": "轻代码前端编译器.1.0.0",
    }
    输出文件.parent.mkdir(parents=True, exist_ok=True)
    输出文件.write_text(json.dumps(制品, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 制品


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="编译轻代码前端 JSON")
    解析器.add_argument("源文件", type=Path)
    解析器.add_argument("--输出", type=Path, default=根目录 / "工程缓存" / "轻代码前端编辑器" / "编译制品.json")
    参数 = 解析器.parse_args()
    try:
        结果 = 编译(参数.源文件, 参数.输出)
    except ValueError as 错误:
        print(f"编译阻断：{错误}")
        raise SystemExit(1)
    print(f"编译成功：{参数.输出}；能力依赖 {len(结果['能力依赖'])} 个")
