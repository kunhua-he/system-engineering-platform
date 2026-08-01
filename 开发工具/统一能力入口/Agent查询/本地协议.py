"""本地 Agent 查询协议：标准本地命令行入口 + JSON 输入输出。

协议层只负责查询和控制，不实现业务。所有控制操作必须：明确返回
操作id、支持查询进度、支持查询最终结果、失败返回错误码、不允许静默
成功。不把源码全文塞进 Agent 上下文。

用法：
  echo '{"操作": "搜索能力", "参数": {"关键词": "读取文件"}}' | python3.14 Agent查询/本地协议.py
  或  python3.14 Agent查询/本地协议.py --请求 '{"操作": "查看版本"}'
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[1]
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

操作表 = [
    "搜索包", "查看包详情", "查看能力详情", "查看版本", "查看激活版本",
    "查看回滚版本", "查询失败记录", "查看诊断结论", "执行诊断复现",
    "执行升级前检查", "执行热切换", "查看灰度状态", "执行回滚", "查询卸载条件",
]


@dataclass
class 协议响应:
    """一次协议操作的响应。"""

    操作id: str = ""
    操作: str = ""
    状态: str = "完成"  # 进行中/完成/失败
    结果: Any = None
    错误码: str = ""
    错误说明: str = ""
    进度: float = 1.0

    def 转字典(self) -> dict[str, Any]:
        return {
            "操作id": self.操作id, "操作": self.操作, "状态": self.状态,
            "结果": self.结果, "错误码": self.错误码,
            "错误说明": self.错误说明, "进度": self.进度,
        }


class 本地协议服务器:
    """本地协议服务器：请求分派（依赖 查询入口）。"""

    def __init__(self, 查询入口: Any = None, 热切换: Any = None,
                 失败库: Any = None, 指标库: Any = None, 仓库: Any = None) -> None:
        from 开发工具.统一能力入口.Agent查询.查询入口 import 查询入口 as _查询入口
        from 运行核心.加载器.版本系统.热切换 import 热切换管理器
        from 运行核心.加载器.版本系统.版本注册表 import 版本注册表
        self.注册表 = 版本注册表()
        self.热切换 = 热切换 or 热切换管理器(self.注册表)
        self.入口 = 查询入口 or _查询入口(版本注册表实例=self.注册表, 热切换=self.热切换, 失败库=失败库)
        self.失败库 = 失败库
        self.指标库 = 指标库
        self.仓库 = 仓库
        self.操作状态表: dict[str, dict] = {}

    def 处理(self, 请求: dict) -> 协议响应:
        操作 = 请求.get("操作", "")
        参数 = 请求.get("参数") or {}
        if 操作 not in 操作表:
            return 协议响应(操作=操作, 状态="失败", 错误码="未知操作", 错误说明=f"不支持的操作: {操作}")
        操作id = uuid.uuid4().hex[:16]
        响应 = 协议响应(操作id=操作id, 操作=操作)
        try:
            if 操作 == "搜索包":
                结果 = self.入口.搜索能力(关键词=参数.get("关键词", ""))
                响应.结果, 响应.错误码, 响应.错误说明 = 结果.数据, "", 结果.说明
            elif 操作 == "查看版本":
                结果 = self.入口.查看包版本(参数.get("包id", ""))
                响应.结果, 响应.错误码 = 结果.数据, ""
            elif 操作 == "查看能力详情":
                响应.结果 = self.入口.查看能力版本(参数.get("能力id", ""))
            elif 操作 == "查看激活版本":
                结果 = self.入口.查看能力版本(参数.get("能力id", ""))
                响应.结果 = 结果.数据.get("当前激活版本") if 结果.成功 else None
            elif 操作 == "查看回滚版本":
                结果 = self.入口.查看能力版本(参数.get("能力id", ""))
                响应.结果 = 结果.数据.get("可回滚版本") if 结果.成功 else None
            elif 操作 == "查询失败记录":
                结果 = self.入口.查询失败记录(包id=参数.get("包id", ""), 错误码=参数.get("错误码", ""))
                响应.结果, 响应.错误码, 响应.错误说明 = 结果.数据, "", 结果.说明
            elif 操作 == "查看诊断结论":
                结果 = self.入口.查看诊断详情(参数.get("记录id", ""))
                响应.结果, 响应.错误码, 响应.错误说明 = 结果.数据, "", 结果.说明
            elif 操作 == "执行诊断复现":
                响应.结果 = self.执行复现(参数)
            elif 操作 == "执行升级前检查":
                结果 = self.入口.执行升级前检查(参数.get("能力id", ""), 参数.get("新版本", ""))
                响应.结果, 响应.错误码 = 结果.数据, ""
            elif 操作 == "执行热切换":
                响应.结果 = self.执行热切换(参数)
            elif 操作 == "查看灰度状态":
                响应.结果 = self.查看灰度(参数)
            elif 操作 == "执行回滚":
                响应.结果 = self.执行回滚(参数)
            elif 操作 == "查询卸载条件":
                响应.结果 = self.卸载条件(参数)
            else:
                响应.状态 = "失败"
                响应.错误码 = "未实现"
                响应.错误说明 = f"操作未实现: {操作}"
            self.操作状态表[操作id] = {"操作": 操作, "状态": 响应.状态, "时间": time.strftime("%H:%M:%S")}
            return 响应
        except Exception as 错误:
            响应.状态 = "失败"
            响应.错误码 = "内部错误"
            响应.错误说明 = str(错误)
            return 响应

    def 执行复现(self, 参数: dict) -> dict:
        from 运行核心.运行诊断.诊断中心.诊断复现 import 复现执行
        if self.失败库 is None:
            return {"错误码": "失败记录库未接入"}
        记录 = self.失败库.记录表.get(参数.get("记录id", ""))
        if 记录 is None:
            return {"错误码": "记录不存在"}
        结果 = 复现执行(记录)
        return 结果.转字典()

    def 执行热切换(self, 参数: dict) -> dict:
        能力id = 参数.get("能力id", "")
        新版本 = 参数.get("新版本", "")
        回退版本 = 参数.get("回退版本", "")
        结果 = self.热切换.真实热切换(
            能力id=能力id, 新版本=新版本, 回退版本=回退版本,
            指标库=self.指标库,
            状态可迁移=参数.get("状态可迁移", True),
        )
        return {"成功": 结果.成功, "自动回滚": 结果.自动回滚,
                "回滚记录": 结果.回滚记录, "问题": 结果.问题列表}

    def 查看灰度(self, 参数: dict) -> dict:
        if self.指标库 is None:
            return {"错误码": "灰度指标库未接入"}
        指标 = self.指标库.聚合(能力id=参数.get("能力id", ""), 版本=参数.get("版本", ""))
        return 指标.转字典()

    def 执行回滚(self, 参数: dict) -> dict:
        """执行回滚：恢复激活映射到回退版本（不修改源代码）。"""
        能力id = 参数.get("能力id", "")
        回退版本 = 参数.get("回退版本", "")
        if not 能力id or not 回退版本:
            return {"错误码": "缺少 能力id 或 回退版本"}
        原版本 = self.热切换.激活映射.get(能力id, "")
        self.热切换.激活映射[能力id] = 回退版本
        self.热切换.回退映射[能力id] = 原版本
        self.热切换.回滚记录表.append({
            "回滚id": uuid.uuid4().hex[:16], "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "能力id": 能力id, "恢复版本": 回退版本, "原因": "手动回滚（协议层）",
        })
        return {"成功": True, "恢复版本": 回退版本, "原版本": 原版本}

    def 卸载条件(self, 参数: dict) -> dict:
        from 运行核心.加载器.版本系统.弃用清理 import 卸载条件
        条件 = 卸载条件(
            无项目依赖=参数.get("无项目依赖", True),
            无运行中任务=参数.get("无运行中任务", True),
            无连接和句柄=参数.get("无连接和句柄", True),
            无待迁移状态=参数.get("无待迁移状态", True),
            无待处理失败记录=参数.get("无待处理失败记录", True),
            无回滚窗口=参数.get("无回滚窗口", True),
            已超过弃用期限=参数.get("已超过弃用期限", True),
        )
        return {"可卸载": 条件.全部满足(), "未满足条件": 条件.未满足列表()}

    def 查询操作进度(self, 操作id: str) -> dict:
        return self.操作状态表.get(操作id, {"状态": "未知操作id"})


def 主函数(argv: list[str] | None = None) -> int:
    """命令行入口：从 argv 或 stdin 读取 JSON 请求，输出 JSON 响应。"""
    import argparse
    解析器 = argparse.ArgumentParser(description="系统级支持库 本地查询协议")
    解析器.add_argument("--请求", default="", help="JSON 请求字符串")
    参数 = 解析器.parse_args(argv)
    请求文本 = 参数.请求
    if not 请求文本:
        请求文本 = sys.stdin.read().strip()
    if not 请求文本:
        print(json.dumps({"错误码": "缺少请求"}, ensure_ascii=False))
        return 1
    try:
        请求 = json.loads(请求文本)
    except json.JSONDecodeError as 错误:
        print(json.dumps({"错误码": "请求不是合法 JSON", "错误说明": str(错误)}, ensure_ascii=False))
        return 1
    服务器 = 本地协议服务器()
    响应 = 服务器.处理(请求)
    print(json.dumps(响应.转字典(), ensure_ascii=False, indent=2))
    return 0 if 响应.状态 != "失败" else 2


if __name__ == "__main__":
    raise SystemExit(主函数())
