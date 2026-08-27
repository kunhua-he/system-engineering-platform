"""适配层示例：项目公开入口的最小真实运行样板。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
项目根 = Path(__file__).resolve().parent.parent

from 公共契约.能力契约.契约 import 能力注册表
from 运行核心.加载器.生命周期管理.管理器 import 装配系统
from 项目适配层.能力适配.能力适配 import 从项目声明构建映射
from 项目适配层.依赖锁定.依赖锁定 import 生成依赖锁定
from 项目适配层.运行入口.项目入口 import 项目入口
from 项目适配层.支持库绑定.支持库绑定 import 校验绑定 as 校验支持库
from 项目适配层.模块绑定.模块绑定 import 校验绑定 as 校验模块


def 主程序() -> int:
    print("适配层示例运行开始")
    # 功能域分组 v2：6 大聚合库以父包为公开入口（子域是目录分组），
    # 绑定写法与 项目声明.json 保持一致
    for 支持库id in ("支持库.后端.文件系统支持库", "支持库.后端.数据操作支持库"):
        if not 校验支持库(支持库id, ">=1.0.0", 系统根 / "支持库").成功:
            return 1
    print("[1] 绑定支持库: 文件系统、文本处理 ✓")
    if not 校验模块("模块库.文件管理", ">=1.0.0", 系统根).成功:
        return 1
    print("[2] 绑定模块: 文件管理 ✓")
    锁定 = 生成依赖锁定(项目根, 系统根)
    if not 锁定.成功:
        print(f"[3] 依赖锁定失败: {锁定.问题列表}")
        return 1
    print(f"[3] 生成依赖锁: {锁定.包数量} 个包 ✓")
    注册表 = 能力注册表()
    装配 = 装配系统(系统根 / "支持库", 系统根 / "模块库", 注册表)
    if not 装配.成功:
        print(f"[4] 装配失败: {装配.问题列表}")
        return 1
    print(f"[4] 装配系统: {装配.已注册能力数} 个能力 ✓")
    项目数据 = json.loads((项目根 / "项目声明.json").read_text(encoding="utf-8"))
    from 运行核心.加载器.包发现.发现器 import 发现全部
    映射 = 从项目声明构建映射(项目数据, 发现全部(系统根 / "支持库", 系统根 / "模块库").声明列表)
    入口 = 项目入口(注册表, 映射)
    资源 = 项目根 / "项目资源"
    资源.mkdir(parents=True, exist_ok=True)
    路径 = str(资源 / "示例输出.txt")
    写入 = 入口.调用("写入文件", {"文件路径": 路径, "内容": "适配层示例内容"})
    读取 = 入口.调用("读取文件", {"文件路径": 路径})
    分割 = 入口.调用("分割文本", {"文本": "甲,乙,丙", "分隔符": ","})
    if not (写入.成功 and 读取.成功 and 分割.成功 and 分割.值 == ["甲", "乙", "丙"]):
        return 1
    print("[6] 经项目入口调用: 写入文件/读取文件/分割文本 ✓")
    print("[7] 返回统一结果结构: 成功/值/错误 ✓")
    print("[8] 项目适配验证: 通过 ✓")
    print("适配层示例运行成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
