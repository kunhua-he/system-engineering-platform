"""个人蒸馏支持库包级中文入口。

调用者只能经 40007 网关调用能力，禁止直接 import 实现目录。
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = []


def 注册能力(注册表) -> None:
    """由支持库加载器调用：注册个人蒸馏原子能力。"""
    from datetime import datetime
    from 公共契约.能力契约.契约 import 能力实现
    from 公共契约.基础类型.结果类型 import 结果
    from 支持库.后端.个人蒸馏支持库.实现.个人蒸馏 import (
        个人蒸馏不可用, 查询上下文, 格式化可注入上下文, 构建上下文请求参数,
    )

    def _包装查询上下文(*, 主体标识, 岗位标识, 场景="", as_of, known_at):
        try:
            结果值 = 查询上下文(
                主体标识, 岗位标识, 场景 or None,
                datetime.fromisoformat(as_of), datetime.fromisoformat(known_at),
            )
            return 结果.成功结果(结果值)
        except 个人蒸馏不可用 as e:
            return 结果.失败("个人蒸馏不可用", str(e))
        except Exception as e:
            return 结果.失败("查询异常", str(e))

    def _包装格式化(*, 上下文):
        try:
            return 结果.成功结果(格式化可注入上下文(上下文))
        except Exception as e:
            return 结果.失败("格式化异常", str(e))

    def _包装构建参数(*, 主体标识, 岗位标识, 场景="", as_of, known_at):
        try:
            结果值 = 构建上下文请求参数(
                主体标识=主体标识, 岗位标识=岗位标识, 场景=场景 or None,
                as_of=datetime.fromisoformat(as_of), known_at=datetime.fromisoformat(known_at),
            )
            return 结果.成功结果(结果值)
        except ValueError as e:
            return 结果.失败("参数不合法", str(e))
        except Exception as e:
            return 结果.失败("构建异常", str(e))

    for 能力id, 函数, 参数表, 说明 in [
        ("个人蒸馏支持库.查询上下文", _包装查询上下文,
         [{"名称": "主体标识", "类型": "文本型", "必填": True},
          {"名称": "岗位标识", "类型": "文本型", "必填": True},
          {"名称": "场景", "类型": "文本型", "必填": False},
          {"名称": "as_of", "类型": "文本型", "必填": True},
          {"名称": "known_at", "类型": "文本型", "必填": True}], "查询个人蒸馏上下文"),
        ("个人蒸馏支持库.格式化可注入上下文", _包装格式化,
         [{"名称": "上下文", "类型": "字典型", "必填": True}], "格式化投影为注入文本"),
        ("个人蒸馏支持库.构建上下文请求参数", _包装构建参数,
         [{"名称": "主体标识", "类型": "文本型", "必填": True},
          {"名称": "岗位标识", "类型": "文本型", "必填": True},
          {"名称": "场景", "类型": "文本型", "必填": False},
          {"名称": "as_of", "类型": "文本型", "必填": True},
          {"名称": "known_at", "类型": "文本型", "必填": True}], "构建上下文请求参数"),
    ]:
        注册表.注册(
            能力实现(
                能力id=能力id,
                包id="支持库.后端.个人蒸馏支持库",
                实现函数=函数,
                参数=参数表,
                返回="结果",
                说明=说明,
            )
        )
