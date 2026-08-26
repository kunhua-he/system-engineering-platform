"""开发工具统一中文入口：Agent 开发闭环。

操作：搜索能力/查看契约/查看参数和返回/查看提供者和版本/查看依赖关系/
查看验证状态/查看已知失败/真实调用能力/创建支持库模板/创建模块模板/
验证指定组件/生成说明书/执行发布检查。
命令行、MCP 和 Python 调用复用同一实现（禁止三套逻辑）。
Agent 搜索只读取声明、索引和说明书，不加载实现；
Agent 调用必须经过公开能力注册表，并返回完整调用证据链。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "平台控制面").is_dir() and (_祖先 / "测试中心").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表


def 搜索能力(关键词: str = "", 限制: int = 20) -> list[dict[str, Any]]:
    """搜索能力：只读取 包声明/能力契约/说明书，不加载实现。

    内部层支持库（第三方能力，包声明 内部层=true）不暴露给开发者。
    """
    from 运行核心.加载器.包发现.发现器 import 扫描目录
    结果表: list[dict[str, Any]] = []
    声明表 = 扫描目录(系统根 / "支持库", "支持库") + 扫描目录(系统根 / "模块库", "模块")
    for 声明 in 声明表:
        # 内部层（第三方能力支持库）：0 暴露，跳过
        if getattr(声明, "内部层", False):
            continue
        声明数据 = json.loads((Path(声明.来源路径)).read_text(encoding="utf-8"))
        for 能力 in 声明数据.get("能力", []):
            能力id = 能力["能力id"]
            if 关键词 and 关键词 not in 能力id and 关键词 not in 能力.get("名称", ""):
                continue
            结果表.append({
                "能力id": 能力id, "名称": 能力.get("名称", ""), "包id": 声明.包id,
                "说明": 能力.get("说明", ""), "参数": [参数["名称"] for 参数 in 能力.get("参数", [])],
            })
            if len(结果表) >= 限制:
                return 结果表
    return 结果表


def 查看契约(能力id: str) -> dict[str, Any]:
    """查看契约与参数返回。"""
    from 开发工具.契约编译.契约编译器 import 校验契约结构
    结果: dict[str, Any] = {"能力id": 能力id, "找到": False}
    for 契约文件 in (系统根 / "支持库").rglob("能力契约/*.json"):
        try:
            数据 = json.loads(契约文件.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        条目表 = 数据.get("能力契约", [数据] if isinstance(数据, list) else [])
        if not 条目表 and isinstance(数据, dict) and "能力id" in 数据:
            条目表 = [数据]
        for 条目 in 条目表:
            if 条目.get("能力id") == 能力id:
                问题 = 校验契约结构(条目)
                结果.update({"找到": True, "版本": 条目.get("版本", ""),
                            "参数": 条目.get("参数", []), "返回": 条目.get("返回", ""),
                            "错误码": 条目.get("错误码", []), "结构问题": 问题,
                            "来源": str(契约文件)})
                return 结果
    return 结果


def 查看提供者和版本(能力id: str) -> dict[str, Any]:
    """查看提供者和版本。"""
    from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
    注册表 = 版本注册表(系统根 / "工程缓存" / "版本注册表")
    版本表 = 注册表.查询全部(能力id) if hasattr(注册表, "查询全部") else []
    返回 = {"能力id": 能力id, "版本表": 版本表,
            "提供者": "内置实现（能力注册表）" if 版本表 else "未注册"}
    return 返回


def 查看依赖关系(包id: str = "") -> dict[str, Any]:
    """查看依赖关系（真实依赖解析器）。"""
    from 运行核心.加载器.包发现.发现器 import 扫描目录
    from 运行核心.加载器.依赖解析.解析器 import 解析依赖
    from 公共契约.包声明.声明 import 包声明
    声明表 = 扫描目录(系统根 / "支持库", "支持库") + 扫描目录(系统根 / "模块库", "模块")
    目标表 = [声明 for 声明 in 声明表 if not 包id or 包id in 声明.包id]
    解析结果 = 解析依赖(目标表, {})
    return {
        "包数": len(目标表), "拓扑顺序": [声明.包id for 声明 in 解析结果.拓扑顺序],
        "问题": 解析结果.问题列表,
    }


def 查看验证状态(组件id: str = "") -> dict[str, Any]:
    """查看验证状态（组件合规）。"""
    from 开发工具.组件合规.合规测试包 import 组件合规
    组件目录 = 系统根 / "支持库"
    目标目录 = None
    for 目录 in (系统根 / "支持库").rglob("包声明.json"):
        数据 = json.loads(目录.read_text(encoding="utf-8"))
        if not 组件id or 组件id == 数据.get("包id") or 组件id == 数据.get("名称"):
            目标目录 = 目录.parent
            break
    if 目标目录 is None:
        return {"组件": 组件id or "全部", "状态": "未找到"}
    报告 = 组件合规(目标目录).执行()
    return {"组件": 目标目录.name, "通过数": 报告.通过数,
            "场景数": len(报告.场景结果表), "成功": 报告.成功}


def 查看已知失败(能力id: str = "") -> list[dict[str, Any]]:
    """查看已知失败（诊断中心）。"""
    from 运行核心.运行诊断.诊断中心.失败记录 import 失败记录库
    库 = 失败记录库(系统根 / "工程缓存" / "失败记录")
    记录表 = 库.查询(能力id=能力id) if hasattr(库, "查询") else []
    return [记录.转字典() if hasattr(记录, "转字典") else 记录 for 记录 in 记录表]


def 真实调用能力(能力id: str, 参数: dict[str, Any] | None = None,
                 *, 项目id: str = "", 用户id: str = "") -> dict[str, Any]:
    """真实调用：经公开能力注册表（装配）→ 完整调用证据链。"""
    from 后端核心.后端核心 import 后端核心
    from 运行核心.能力调用.运行上下文.上下文 import 运行上下文
    from 运行核心.能力调用.控制调用.证据链 import 证据链
    后端 = 后端核心()
    后端.启动()
    证据链实例 = 证据链()
    证据 = 证据链实例.开始调用(能力id=能力id, 项目=项目id)
    结果 = 后端.调用(能力id, 参数 or {}, 上下文=运行上下文(项目id=项目id, 用户id=用户id))
    证据链实例.记录结果(证据, 成功=结果.成功, 错误码=结果.错误码)
    return {
        "成功": 结果.成功, "值": 结果.值, "错误码": 结果.错误码,
        "说明": 结果.错误说明, "证据链": 证据.转字典(),
    }


def 创建支持库模板(名称: str, 目录: Path | None = None) -> str:
    """创建支持库模板（九要素）。"""
    目录 = 目录 or 系统根 / "支持库" / "后端" / 名称
    目录.mkdir(parents=True, exist_ok=True)
    for 子目录 in ("实现", "能力契约", "依赖契约", "配置契约", "权限契约", "说明", "验证场景", "默认配置"):
        (目录 / 子目录).mkdir(exist_ok=True)
    (目录 / "包声明.json").write_text(json.dumps({
        "包id": f"支持库.后端.{名称}", "名称": 名称, "类型": "支持库",
        "版本": "1.0.0", "说明": f"{名称} 支持库", "入口": "__init__.py", "依赖": [],
        "能力": [{"能力id": f"{名称}.示例能力", "名称": "示例能力",
                  "参数": [{"名称": "输入", "类型": "文本型"}], "说明": "示例能力"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (目录 / "__init__.py").write_text(
        f'"""支持库.{名称} 包级中文入口。"""\n\nfrom 公共契约.能力契约.契约 import 能力实现\n\n\ndef 注册能力(注册表) -> None:\n    """由支持库加载器调用。"""\n    注册表.注册(能力实现(\n        能力id="{名称}.示例能力", 包id="支持库.后端.{名称}",\n        实现函数=示例能力, 参数=[{{"名称": "输入", "类型": "文本型"}}],\n        返回="结果型", 说明="示例能力",\n    ))\n\n\ndef 示例能力(输入: str) -> dict:\n    if not 输入:\n        return {{"成功": False, "错误码": "参数不合法"}}\n    return {{"成功": True, "值": {{"长度": len(输入)}}}}\n',
        encoding="utf-8")
    (目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
        "能力契约": [{"能力id": f"{名称}.示例能力", "参数": [{"名称": "输入", "类型": "文本型"}], "返回": "结果型"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (目录 / "说明" / f"{名称}说明.md").write_text(f"# {名称} 支持库\n\n示例能力：输入文本，返回长度。\n", encoding="utf-8")
    (目录 / "验证场景引用.json").write_text(json.dumps({
        f"{名称}.示例能力": {"能力": "示例能力", "验证场景": ["组件合规"]},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"支持库模板已创建: {目录}"


def 创建模块模板(名称: str, 目录: Path | None = None) -> str:
    """薄委托到唯一模块模板生成器（基础模块 类型，示例能力占位）。

    唯一生成器：开发工具/组件规范/模块模板生成器.py（模块名/类型/能力清单/
    依赖能力清单 → 聚合契约+包声明+经调用器实现骨架+对称入口+完整性摘要）。
    """
    from 开发工具.组件规范.模块模板生成器 import 生成模块模板
    结果 = 生成模块模板(
        模块名=名称, 类型="基础模块",
        能力清单=[{"名称": "示例流程", "参数": [{"名称": "输入", "类型": "文本型", "必填": True}],
                   "返回": "结果型", "说明": "示例流程"}],
        依赖能力清单=[], 模块库根=目录.parent if 目录 else None,
    )
    if not 结果.成功:
        return f"创建模块模板失败: {结果.错误码}: {结果.错误说明}"
    return f"模块模板已创建: {结果.值['模块目录']}"


def 验证指定组件(组件目录: Path) -> dict[str, Any]:
    """验证指定组件（组件合规 13 项）。"""
    from 开发工具.组件合规.合规测试包 import 组件合规
    报告 = 组件合规(Path(组件目录)).执行()
    return {"组件": str(组件目录), "通过数": 报告.通过数,
            "场景数": len(报告.场景结果表), "成功": 报告.成功}


def 生成说明书(组件目录: Path) -> str:
    """生成组件说明书（契约编译器）。"""
    from 开发工具.契约编译.契约编译器 import 生成说明书
    契约文件 = next((Path(组件目录) / "能力契约").glob("*.json"), None)
    if 契约文件 is None:
        return "无契约可生成说明书"
    import json as _json
    契约 = _json.loads(契约文件.read_text(encoding="utf-8"))
    说明书 = 生成说明书(契约)
    输出 = Path(组件目录) / "说明" / "说明书.md"
    输出.write_text(说明书, encoding="utf-8")
    return f"说明书已生成: {输出}"


def 执行发布检查() -> dict[str, Any]:
    """执行发布检查（发布门禁，复用同一验证引擎）。"""
    import subprocess
    进程 = subprocess.run(
        [sys.executable, "-S", str(系统根 / "发布门禁" / "运行发布门禁.py")],
        cwd=str(系统根), capture_output=True, text=True, timeout=300)
    最后行 = [行 for 行 in 进程.stdout.splitlines() if "发布状态" in 行]
    return {"退出码": 进程.returncode, "发布状态": 最后行[-1] if 最后行 else "未知",
            "输出尾部": 进程.stdout.strip()[-200:]}


_操作表 = [
    "搜索能力", "查看契约", "查看参数和返回", "查看提供者和版本", "查看依赖关系",
    "查看验证状态", "查看已知失败", "真实调用能力", "创建支持库模板",
    "创建模块模板", "验证指定组件", "生成说明书", "执行发布检查",
]


def 执行操作(操作: str, 参数: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一操作分发：命令行、MCP、Python 调用同一实现。"""
    参数 = 参数 or {}
    try:
        if 操作 == "搜索能力":
            return {"成功": True, "数据": 搜索能力(参数.get("关键词", ""), 参数.get("限制", 20))}
        if 操作 == "查看契约":
            return {"成功": True, "数据": 查看契约(参数["能力id"])}
        if 操作 == "查看参数和返回":
            契约 = 查看契约(参数["能力id"])
            return {"成功": True, "数据": {"参数": 契约.get("参数", []), "返回": 契约.get("返回", "")}}
        if 操作 == "查看提供者和版本":
            return {"成功": True, "数据": 查看提供者和版本(参数["能力id"])}
        if 操作 == "查看依赖关系":
            return {"成功": True, "数据": 查看依赖关系(参数.get("包id", ""))}
        if 操作 == "查看验证状态":
            return {"成功": True, "数据": 查看验证状态(参数.get("组件id", ""))}
        if 操作 == "查看已知失败":
            return {"成功": True, "数据": 查看已知失败(参数.get("能力id", ""))}
        if 操作 == "真实调用能力":
            # 真实调用的结果本身就是统一结果。不能把内层失败无条件
            # 包装成外层成功，否则 Agent 会把后端未装配/提供者失败误判
            # 为成功，且丢失“假绿”证据。保留完整数据供调用方读取值、
            # 错误码和证据链，同时把外层成功状态透传。
            调用结果 = 真实调用能力(
                参数["能力id"], 参数.get("参数"), 项目id=参数.get("项目id", ""),
                用户id=参数.get("用户id", ""))
            返回结果 = {"成功": bool(调用结果.get("成功")), "数据": 调用结果}
            if not 返回结果["成功"]:
                返回结果.update({"错误码": 调用结果.get("错误码", ""),
                                "说明": 调用结果.get("说明", ""),
                                "错误说明": 调用结果.get("说明", "")})
            return 返回结果
        if 操作 == "创建支持库模板":
            return {"成功": True, "数据": 创建支持库模板(参数["名称"])}
        if 操作 == "创建模块模板":
            return {"成功": True, "数据": 创建模块模板(参数["名称"])}
        if 操作 == "验证指定组件":
            return {"成功": True, "数据": 验证指定组件(Path(参数["组件目录"]))}
        if 操作 == "生成说明书":
            return {"成功": True, "数据": 生成说明书(Path(参数["组件目录"]))}
        if 操作 == "执行发布检查":
            return {"成功": True, "数据": 执行发布检查()}
        return {"成功": False, "错误码": "参数不合法", "说明": f"未知操作: {操作}"}
    except KeyError as 错误:
        return {"成功": False, "错误码": "参数不合法", "说明": f"缺少参数: {错误}"}
    except Exception as 错误:
        return {"成功": False, "错误码": "内部错误", "说明": str(错误)}


def 命令行入口() -> int:
    """命令行入口：python3.14 开发工具/开发入口.py 操作 参数JSON。"""
    if len(sys.argv) < 2:
        print(json.dumps({
            "说明": "用法: 开发入口.py <操作> [参数JSON]",
            "操作表": list(_操作表),
        }, ensure_ascii=False, indent=2))
        return 0
    操作 = sys.argv[1]
    参数 = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    结果 = 执行操作(操作, 参数)
    print(json.dumps(结果, ensure_ascii=False, indent=2))
    return 0 if 结果.get("成功") else 1


_操作表 = [
    "搜索能力", "查看契约", "查看参数和返回", "查看提供者和版本", "查看依赖关系",
    "查看验证状态", "查看已知失败", "真实调用能力", "创建支持库模板",
    "创建模块模板", "验证指定组件", "生成说明书", "执行发布检查",
]


if __name__ == "__main__":
    raise SystemExit(命令行入口())
