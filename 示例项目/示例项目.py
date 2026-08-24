"""系统级支持库最小运行样板。"""
from __future__ import annotations

import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表
from 运行核心.加载器.生命周期管理.管理器 import 装配系统


def 主程序() -> int:
    注册表 = 能力注册表()
    装配 = 装配系统(系统根 / "支持库", 系统根 / "模块库", 注册表)
    if not 装配.成功:
        print(f"装配失败: {装配.问题列表}")
        return 1
    print(f"[1] 装配成功: {len(装配.顺序列表)} 个包, {装配.已注册能力数} 个能力")

    搜索列表 = 注册表.搜索(关键词="读取文件")
    if not 搜索列表:
        print("[2] 搜索 读取文件 失败")
        return 1
    print(f"[2] 搜索 读取文件 → {[实现.能力id for 实现 in 搜索列表]}")

    实现 = 注册表.获取("文件系统.写入文件")
    if 实现 is None:
        print("[3] 文件系统.写入文件 未注册")
        return 1
    临时目录 = 系统根 / "工程缓存"
    临时目录.mkdir(parents=True, exist_ok=True)
    临时文件 = str(临时目录 / "示例项目_临时文件.txt")
    写入结果 = 实现.调用(文件路径=临时文件, 内容="示例项目内容\n")
    if not 写入结果.成功:
        print(f"[3] 注册表调用写入失败: {写入结果.错误}")
        return 1
    print("[3] 经注册表调用 文件系统.写入文件 成功")

    from 支持库.后端.文件系统 import 读取文件, 写入文件
    读取结果 = 读取文件(临时文件)
    if not 读取结果.成功 or "示例项目内容" not in (读取结果.值 or ""):
        print("[4] 公开入口读取失败")
        return 1
    print("[4] 经公开入口调用 文件系统.读取文件 成功")

    from 模块库.文档读取 import 结构化读取
    文档路径 = str(临时目录 / "示例项目_文档.txt")
    写入文件(文档路径, "示例标题\n第一段。\n第二段。")
    结构结果 = 结构化读取(文档路径)
    if not 结构结果.成功 or 结构结果.值.get("标题") != "示例标题":
        print(f"[5] 模块组合调用失败: {结构结果.错误 if not 结构结果.成功 else 结构结果.值}")
        return 1
    print(f"[5] 模块组合调用 文档读取.结构化读取 成功（标题={结构结果.值['标题']}）")
    print("示例项目运行成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
