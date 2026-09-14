"""psycopg 驱动翻译层包级中文入口。

本层是**唯一**直接接触 psycopg（psycopg3）的地方：把驱动英文 API 翻译成中文原语，
供支持库 `支持库.后端.数据库连接支持库.psycopg数据库` 调用。对外 PostgreSQL 能力
（连接数据库/查询数据库/事务执行数据库/连接池状态/关闭数据库连接）归该支持库，
本层只对外提供一个真实能力：驱动健康探针。
"""

from __future__ import annotations

from 公共契约.能力契约.契约 import 能力实现

from 支持库.适配层.psycopg提供者.实现.提供者 import 检查可用性
from 支持库.适配层.psycopg提供者.实现.提供者 import 打开连接
from 支持库.适配层.psycopg提供者.实现.提供者 import 归类错误
from 支持库.适配层.psycopg提供者.实现.提供者 import 校验超时
from 支持库.适配层.psycopg提供者.实现.提供者 import 校验连接串
from 支持库.适配层.psycopg提供者.实现.提供者 import 解析连接串
from 支持库.适配层.psycopg提供者.实现.提供者 import 释放连接
from 支持库.适配层.psycopg提供者.实现.提供者 import 驱动可用
from 支持库.适配层.psycopg提供者.实现.提供者 import 驱动版本

__all__ = ["检查可用性", "打开连接", "释放连接", "归类错误", "解析连接串", "校验连接串",
           "校验超时", "驱动可用", "驱动版本", "注册能力"]

包id = "支持库.适配层.psycopg提供者"


def 注册能力(注册表) -> None:
    """由支持库加载器调用：只注册驱动健康探针，不注册任何数据库操作能力。"""
    注册表.注册(能力实现(
        能力id=f"{包id}.检查可用性",
        包id=包id,
        实现函数=检查可用性,
        参数=[],
        返回="结果型",
        说明="驱动健康探针：返回 psycopg 是否可用与本机驱动版本；不连数据库、无副作用。",
    ))
