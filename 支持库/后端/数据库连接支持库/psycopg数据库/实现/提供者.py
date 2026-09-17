"""psycopg 数据库支持库：唯一对外 PostgreSQL 原子能力（句柄 + 有界同步池）。

公开能力（五）：连接数据库 / 查询数据库 / 事务执行数据库 / 连接池状态 / 关闭数据库连接。
调用方只持 `数据库句柄`，不接触连接对象；池只在底座进程内存在，连接失效只丢弃不回收。
第三方（psycopg）不在本层直接出现——驱动交互全部经最底层翻译层
`支持库.适配层.psycopg提供者`；驱动缺失明确返回 提供者不可用。
稳定错误码：参数不合法/提供者不可用/超时/连接失败/查询失败/句柄失效。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄类型_资源, 句柄体系
# 错误码唯一源 = `公共契约/错误结构/错误结构.py`（B-9 收口）：平台同义码只导入，不复制字面量。
from 公共契约.错误结构 import 错误码_参数不合法, 错误码_提供者不可用, 错误码_超时

# 本包自有码（不在平台规范集内）。
错误码_连接失败 = "连接失败"
错误码_查询失败 = "查询失败"
错误码_句柄失效 = "句柄失效"
来源 = "psycopg提供者"

from 支持库.适配层.psycopg提供者 import 打开连接 as _打开
from 支持库.适配层.psycopg提供者 import 归类错误 as _归类错误
from 支持库.适配层.psycopg提供者 import 校验超时 as _校验超时
from 支持库.适配层.psycopg提供者 import 校验连接串 as _校验连接串
from 支持库.适配层.psycopg提供者 import 解析连接串 as _解析URL
from 支持库.适配层.psycopg提供者 import 释放连接 as _释放
from 支持库.适配层.psycopg提供者 import 驱动可用 as _驱动可用


@dataclass
class _池连接:
    """池内连接状态；失效连接只允许丢弃，不回收到空闲队列。"""
    连接对象: Any
    创建时间: float
    使用次数: int = 0


class _同步连接池:
    """唯一 PostgreSQL 同步连接池：有界借还、失效替换、关闭收口。

    池只在底座进程内存在；调用方只持数据库句柄，不接触连接对象。
    并发上限由信号量统一约束「在用 + 空闲」总数，任何时刻都不得超过
    连接池大小，新建连接也必须先取得许可。
    """

    def __init__(self, 连接串: str, *, 大小: int, 连接超时秒: float):
        self.连接串 = 连接串
        self.大小 = 大小
        self.连接超时秒 = 连接超时秒
        self._空闲: queue.LifoQueue[_池连接] = queue.LifoQueue(maxsize=大小)
        self._许可 = threading.Semaphore(大小)
        self._全部: set[int] = set()
        self._锁 = threading.Lock()
        self._关闭 = False
        self._借出数 = 0

    def _新建(self) -> _池连接:
        连接对象 = _打开(self.连接串, self.连接超时秒)
        池连接 = _池连接(连接对象, time.monotonic())
        with self._锁:
            if self._关闭:
                _释放(连接对象)
                raise RuntimeError("数据库连接池已关闭")
            self._全部.add(id(池连接))
        return 池连接

    def _记借出(self, 池连接: _池连接) -> _池连接:
        池连接.使用次数 += 1
        with self._锁:
            self._借出数 += 1
        return 池连接

    def 借出(self, 超时秒: float) -> _池连接:
        """取得一个池连接：许可即借出权，池空时按剩余时间等待空闲连接。"""
        截止 = time.monotonic() + max(0.0, float(超时秒))
        if not self._许可.acquire(timeout=max(0.0, 截止 - time.monotonic())):
            raise TimeoutError("等待数据库连接池超时")
        try:
            with self._锁:
                if self._关闭:
                    raise RuntimeError("数据库连接池已关闭")
            try:
                return self._记借出(self._空闲.get_nowait())
            except queue.Empty:
                with self._锁:
                    需等待 = len(self._全部) >= self.大小
                if not 需等待:
                    return self._记借出(self._新建())
                剩余 = 截止 - time.monotonic()
                if 剩余 <= 0:
                    raise TimeoutError("等待数据库连接池超时")
                try:
                    return self._记借出(self._空闲.get(timeout=剩余))
                except queue.Empty as 错误:
                    raise TimeoutError("等待数据库连接池超时") from 错误
        except BaseException:
            self._许可.release()
            raise

    def 归还(self, 池连接: _池连接, *, 失效: bool = False) -> str | None:
        """归还池连接；返回**释放问题**（None=干净归还），调用方必须并入结果，不得丢弃。

        `释放连接()` 的契约是「返回释放过程中的问题，None 表示干净释放，**绝不静默吞掉**」——
        调用方把返回值丢掉，就是把释放失败静默吞掉（句柄残留假绿），由 `_收尾()` 收口。
        """
        try:
            with self._锁:
                self._借出数 = max(0, self._借出数 - 1)
                是否关闭 = self._关闭
            if 失效 or 是否关闭:
                问题 = _释放(池连接.连接对象)
                with self._锁:
                    self._全部.discard(id(池连接))
                return 问题
            try:
                池连接.连接对象.rollback()
                self._空闲.put_nowait(池连接)
                return None
            except Exception:
                问题 = _释放(池连接.连接对象)
                with self._锁:
                    self._全部.discard(id(池连接))
                return 问题
        finally:
            self._许可.release()

    def 关闭(self) -> None:
        with self._锁:
            self._关闭 = True
        while True:
            try:
                池连接 = self._空闲.get_nowait()
            except queue.Empty:
                break
            _释放(池连接.连接对象)
            with self._锁:
                self._全部.discard(id(池连接))
            self._许可.release()

    def 状态(self) -> dict[str, Any]:
        with self._锁:
            return {"最大连接数": self.大小, "已创建连接数": len(self._全部),
                    "空闲连接数": self._空闲.qsize(), "借出连接数": self._借出数,
                    "已关闭": self._关闭}


_句柄体系 = 句柄体系()
_池表: dict[int, _同步连接池] = {}
_池锁 = threading.RLock()


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=True)


def _收尾(结果对象: 结果, 释放问题: str | None) -> 结果:
    """把连接释放问题并入结果：成功路径出现释放问题视为失败（句柄残留不得假绿）。"""
    if not 释放问题:
        return 结果对象
    if 结果对象.成功:
        return _失败(错误码_连接失败, 释放问题)
    return 结果.失败(
        结果对象.错误码,
        f"{结果对象.错误说明}；{释放问题}",
        来源=来源,
        可重试=结果对象.可重试,
    )


def _校验句柄类型(数据库句柄: Any) -> str | None:
    if isinstance(数据库句柄, bool) or not isinstance(数据库句柄, int):
        return "数据库句柄必须是整数"
    return None


def _池对象(数据库句柄: int) -> _同步连接池 | None:
    if isinstance(数据库句柄, bool) or not isinstance(数据库句柄, int):
        return None
    通过, _ = _句柄体系.校验(数据库句柄)
    if not 通过:
        return None
    with _池锁:
        return _池表.get(数据库句柄)


def 连接数据库(连接串: str, 连接池大小: int = 4, 超时秒: float = 10) -> 结果:
    """创建唯一同步 PostgreSQL 连接池，返回底座资源句柄。"""
    if (问题 := _校验连接串(连接串)) or (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if (isinstance(连接池大小, bool) or not isinstance(连接池大小, int)
            or not 1 <= 连接池大小 <= 100):
        return _失败(错误码_参数不合法, "连接池大小必须是 1 到 100 的整数")
    # `_驱动可用` 是翻译层 def 出来的**健康探针函数**（支持库/适配层/psycopg提供者/实现/提供者.py
    # 的 `def 驱动可用() -> bool`）。此处漏写调用括号时 `not <函数对象>` 恒为 False，
    # 该 fail-closed 门禁永不触发：驱动真缺失时不走 提供者不可用，而是掉进下面的
    # 连接池创建再以别的错误码爆出（2026-09-17 修）。
    if not _驱动可用():
        return _失败(错误码_提供者不可用, "psycopg 驱动未安装，提供者不可用")
    try:
        池 = _同步连接池(连接串, 大小=连接池大小, 连接超时秒=float(超时秒))
        探针 = 池.借出(float(超时秒))
        if (探针问题 := 池.归还(探针)):
            return _失败(错误码_连接失败, f"连接池探针释放问题：{探针问题}")
        对象 = _句柄体系.创建句柄(
            句柄类型=句柄类型_资源, 资源id=f"postgresql:{id(池)}", 版本="1.0.0",
        )
        with _池锁:
            _池表[对象.句柄id] = 池
        return 结果.成功结果({"数据库句柄": 对象.句柄id, "连接池": 池.状态()})
    except TimeoutError as 错误:
        return _失败(错误码_超时, str(错误))
    except Exception as 错误:
        return _失败(_归类错误(错误), f"创建数据库连接池失败：{错误}")


def 查询数据库(数据库句柄: int, SQL: str, 参数: list | None = None,
             超时秒: float = 30) -> 结果:
    """持句柄查询：借还池连接，查询失败连接丢弃，绝不污染后续借用。"""
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    if not isinstance(参数, (list, tuple)) and 参数 is not None:
        return _失败(错误码_参数不合法, "参数必须是列表或元组")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if (问题 := _校验句柄类型(数据库句柄)):
        return _失败(错误码_参数不合法, 问题)
    池 = _池对象(数据库句柄)
    if 池 is None:
        return _失败(错误码_句柄失效, "数据库句柄不存在、已关闭或已失效")
    池连接 = None
    失效 = False
    释放问题: str | None = None
    try:
        池连接 = 池.借出(float(超时秒))
        with 池连接.连接对象.cursor() as 游标:
            游标.execute(SQL, 参数 or ())
            行列表 = 游标.fetchall()
            列名表 = [描述[0] for 描述 in 游标.description] if 游标.description else []
        结果对象 = 结果.成功结果({"行列表": [dict(zip(列名表, 行)) for 行 in 行列表]})
    except TimeoutError as 错误:
        结果对象 = _失败(错误码_超时, str(错误))
    except Exception as 错误:
        失效 = True
        结果对象 = _失败(_归类错误(错误), f"查询失败：{错误}")
    finally:
        if 池连接 is not None:
            释放问题 = 池.归还(池连接, 失效=失效)
    return _收尾(结果对象, 释放问题)


def 事务执行数据库(数据库句柄: int, SQL列表: list, 超时秒: float = 30) -> 结果:
    """持句柄事务执行：全部成功提交，任一失败回滚并丢弃失效连接。"""
    if not isinstance(SQL列表, list) or not SQL列表 or any(
            not isinstance(条, str) or not 条.strip() for 条 in SQL列表):
        return _失败(错误码_参数不合法, "SQL列表 必须是非空文本列表")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if (问题 := _校验句柄类型(数据库句柄)):
        return _失败(错误码_参数不合法, 问题)
    池 = _池对象(数据库句柄)
    if 池 is None:
        return _失败(错误码_句柄失效, "数据库句柄不存在、已关闭或已失效")
    池连接 = None
    失效 = False
    释放问题: str | None = None
    try:
        池连接 = 池.借出(float(超时秒))
        with 池连接.连接对象.cursor() as 游标:
            for 条 in SQL列表:
                游标.execute(条)
        池连接.连接对象.commit()
        结果对象 = 结果.成功结果({"已提交": True})
    except TimeoutError as 错误:
        结果对象 = _失败(错误码_超时, str(错误))
    except Exception as 错误:
        失效 = True
        说明 = ""
        if 池连接 is not None:
            try:
                池连接.连接对象.rollback()
            except Exception as 回滚错误:
                失效 = True
                说明 = f"；回滚失败：{回滚错误}"
            else:
                说明 = ""
        结果对象 = _失败(_归类错误(错误), f"事务执行失败，已回滚{说明}：{错误}")
    finally:
        if 池连接 is not None:
            释放问题 = 池.归还(池连接, 失效=失效)
    return _收尾(结果对象, 释放问题)


def 连接池状态(数据库句柄: int) -> 结果:
    """读取句柄对应池的有界状态，不暴露连接对象。"""
    if (问题 := _校验句柄类型(数据库句柄)):
        return _失败(错误码_参数不合法, 问题)
    池 = _池对象(数据库句柄)
    if 池 is None:
        return _失败(错误码_句柄失效, "数据库句柄不存在、已关闭或已失效")
    return 结果.成功结果(池.状态())


def 关闭数据库连接(数据库句柄: int) -> 结果:
    """关闭池并使句柄失效；重复关闭保持幂等。"""
    if isinstance(数据库句柄, bool) or not isinstance(数据库句柄, int):
        return _失败(错误码_参数不合法, "数据库句柄必须是整数")
    with _池锁:
        池 = _池表.pop(数据库句柄, None)
    对象 = _句柄体系.句柄表.get(数据库句柄)
    if 池 is None or 对象 is None:
        return 结果.成功结果({"已关闭": True, "说明": "数据库句柄已不存在"})
    池.关闭()
    _句柄体系.失效(数据库句柄, 原因="主动释放")
    return 结果.成功结果({"已关闭": True})


def _提供者版本() -> dict[str, str]:
    """返回 psycopg 版本字典。"""
    try:
        return {"psycopg": str(getattr(psycopg, "__version__", "未知"))}
    except Exception as 错误:
        return {"psycopg": f"未知（{错误}）"}
