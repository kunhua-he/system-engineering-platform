"""HTTP 连接器：模块调用能力的唯一 HTTP 门面。

模块/支持库门面/项目适配层只经本连接器调用能力；连接器内部发 HTTP 请求
到统一网关 `/网关/调用`，不再进程内直接 import 实现。

职责（冻结，见 开发文档/临时文档/06_冻结HTTP契约.md）：
1. 按能力 id 发 HTTP 请求到 /网关/调用；
2. 校验参数基本类型（能力id 非空、参数是对象）；
3. 生成请求 id（幂等键）；
4. 处理超时/断开/连接失败/非 JSON 响应；
5. 校验返回结构（必须含 成功 字段）；
6. 转统一结果 dict（含 句柄 透传）。

句柄流转（华哥口径）：首次调用不传句柄 → 网关返回句柄 → 调用方从返回值
拿句柄 → 后续调用把该句柄当参数填入。连接器只做透传，不自行编造句柄。
"""

from __future__ import annotations

import json
import base64
import http.client
import math
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

默认响应上限字节 = 4 * 1024 * 1024

from 公共契约.运行时.JSON解码 import 解码冻结值
from 公共契约.错误结构 import (
    错误码_参数不合法,
    错误码_提供者不可用,
    错误码_超时,
    错误码_返回结果不符合契约,
)
from 公共契约.版本规则.契约版本 import 取契约版本


class HTTP连接器:
    """模块侧唯一跨边界调用门面（HTTP 客户端）。"""

    def __init__(self, *, 网关地址: str = "127.0.0.1", 网关端口: int = 40007,
                 默认超时秒: float = 10.0, 契约版本: str | None = None) -> None:
        self.网关地址 = 网关地址
        self.网关端口 = 网关端口
        self.默认超时秒 = 默认超时秒
        # 契约版本只能来自唯一事实源（公共契约/版本规则/契约版本.py）：
        # 写死字面量会让「请求版本」与网关侧契约版本长期分叉（只回报差异不失败，
        # 所以分叉不会被打红，只能靠不写字面量来防）。
        self.契约版本 = 契约版本 or 取契约版本()

    @property
    def 端点(self) -> str:
        return f"http://{self.网关地址}:{self.网关端口}/网关/调用"

    def 调用能力(self, 能力id: str, 参数: dict[str, Any] | None = None, *,
                 句柄: int | None = None, 项目id: str = "", 用户id: str = "",
                 超时秒: float | None = None, 契约版本: str = "",
                 请求id: str = "", 获取句柄: bool = True) -> dict[str, Any]:
        """按能力 id 经 HTTP 网关调用，返回统一结果 dict（含 句柄 字段）。"""
        # 1. 参数基本校验
        if not isinstance(能力id, str) or not 能力id.strip():
            return self._失败(错误码_参数不合法, "能力id 必须是非空文本", "")
        if 参数 is not None and not isinstance(参数, dict):
            return self._失败(错误码_参数不合法, "参数必须是对象", "")
        if 句柄 is not None and (
            isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999
        ):
            return self._失败(错误码_参数不合法, "句柄必须是 1 到 999999 的整数，且只能使用网关返回的句柄", "")
        if not isinstance(请求id, str):
            return self._失败(错误码_参数不合法, "请求id 必须是文本型", "")
        if not isinstance(获取句柄, bool):
            return self._失败(错误码_参数不合法, "获取句柄必须是逻辑型", "")
        实际超时 = 超时秒 if 超时秒 is not None else self.默认超时秒
        if isinstance(实际超时, bool) or not isinstance(实际超时, (int, float)):
            return self._失败(错误码_参数不合法, "超时秒必须是数值型", "")
        if not math.isfinite(float(实际超时)) or float(实际超时) <= 0:
            return self._失败(错误码_参数不合法, "超时秒必须是正的有限数值", "")
        # 2. 构造请求（请求id 作幂等键）
        请求id = 请求id or uuid.uuid4().hex[:16]
        请求体 = {
            "能力id": 能力id,
            "参数": 参数 or {},
            "契约版本": 契约版本 or self.契约版本,
            "请求id": 请求id,
            "句柄": 句柄,
            "获取句柄": 获取句柄,
            "超时秒": float(实际超时),
            "项目id": 项目id,
            "用户id": 用户id,
        }
        # 3. 发 HTTP 请求（处理超时/断开/连接失败）
        try:
            状态码, 数据, 错误说明 = self._请求(请求体, 超时秒=float(实际超时))
        except (TypeError, ValueError) as 错误:
            return self._失败(错误码_参数不合法, f"参数无法编码为 JSON：{错误}", 请求id)
        if isinstance(数据, dict):
            try:
                数据 = self._解码JSON值(数据)
            except ValueError as 错误:
                return self._失败(错误码_返回结果不符合契约, f"网关响应正文非法：{错误}", 请求id)
        if 状态码 >= 500 and (数据 is None or not isinstance(数据, dict) or 数据.get("成功") is not False):
            return self._失败(错误码_提供者不可用, f"网关服务错误（状态 {状态码}）：{错误说明}", 请求id)
        if 数据 is None:
            if 状态码 == 200:
                return self._失败(错误码_返回结果不符合契约, f"网关响应正文不可解析：{错误说明}", 请求id)
            if 状态码 == 0 and ("timed out" in 错误说明.lower() or "超时" in 错误说明):
                return self._失败(错误码_超时, f"网关请求超时：{错误说明}", 请求id)
            return self._失败(错误码_提供者不可用, f"网关不可达（状态 {状态码}）：{错误说明}", 请求id)
        # 4. 校验返回结构
        if not self._返回结构合法(数据):
            return self._失败(
                错误码_返回结果不符合契约,
                "网关返回结构不符合契约（字段类型或必填字段不正确）",
                请求id,
            )
        if 数据["请求id"] != 请求id:
            return self._失败(
                错误码_返回结果不符合契约,
                "网关返回请求id与本次请求不一致",
                请求id,
            )
        # 5. 转统一结果（句柄透传）
        return {
            "成功": 数据["成功"],
            "值": 数据.get("值"),
            "错误码": 数据["错误码"],
            "错误说明": 数据["错误说明"],
            "句柄": 数据.get("句柄"),
            "请求id": 数据["请求id"],
            "耗时毫秒": 数据.get("耗时毫秒", 0),
        }

    @staticmethod
    def _解码JSON值(值: Any) -> Any:
        """还原网关约定的字节集 JSON 表示。

        委托全平台唯一实现（宽松模式）：非法字节集原样保留；带最大深度/节点预算。
        """
        return 解码冻结值(值, 模式="宽松")

    @staticmethod
    def _编码JSON值(值: Any) -> Any:
        """把 JSON 不支持的二进制递归编码为冻结的字节集对象。"""
        if isinstance(值, (bytes, bytearray, memoryview)):
            return {
                "类型": "字节集型",
                "base64": base64.b64encode(bytes(值)).decode("ascii"),
            }
        if isinstance(值, dict):
            return {键: HTTP连接器._编码JSON值(子值) for 键, 子值 in 值.items()}
        if isinstance(值, list):
            return [HTTP连接器._编码JSON值(子值) for 子值 in 值]
        if isinstance(值, tuple):
            return [HTTP连接器._编码JSON值(子值) for 子值 in 值]
        return 值

    @staticmethod
    def _返回结构合法(数据: object) -> bool:
        """严格校验冻结返回契约，禁止 JSON 类型隐式转换。"""
        if not isinstance(数据, dict):
            return False
        必填字段 = {"请求id", "成功", "值", "错误码", "错误说明", "句柄", "耗时毫秒"}
        if not 必填字段.issubset(数据):
            return False
        if not isinstance(数据["请求id"], str):
            return False
        if not isinstance(数据["成功"], bool):
            return False
        if not isinstance(数据["错误码"], str) or not isinstance(数据["错误说明"], str):
            return False
        句柄 = 数据["句柄"]
        if 句柄 is not None and (
            isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999
        ):
            return False
        耗时 = 数据["耗时毫秒"]
        return (isinstance(耗时, (int, float)) and not isinstance(耗时, bool)
                and math.isfinite(float(耗时)) and 耗时 >= 0)

    def 请求(self, 目标: str, 参数: dict[str, Any] | None = None,
             句柄: int | None = None) -> dict[str, Any]:
        """最小调用入口。句柄必须是此前响应返回的整数。"""
        return self.调用能力(目标, 参数, 句柄=句柄)

    def 健康检查(self) -> bool:
        """探测网关是否可达（GET /健康 通过网关核心）。"""
        请求 = urllib.request.Request(
            urllib.parse.quote(
                f"http://{self.网关地址}:{self.网关端口}/健康",
                safe=":/@._-",
            ),
            method="GET",
        )
        try:
            开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with 开放器.open(请求, timeout=float(self.默认超时秒)) as 响应:
                return 响应.status == 200
        except Exception:
            return False

    def _请求(self, 请求体: dict[str, Any], *, 超时秒: float | None = None) -> tuple[int, dict[str, Any] | None, str]:
        """发 HTTP POST 到 /网关/调用；返回 (状态码, 数据, 错误说明)。"""
        载荷 = json.dumps(
            self._编码JSON值(请求体), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        请求 = urllib.request.Request(
            urllib.parse.quote(self.端点, safe=":/@._-"), data=载荷, method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                # 请求头值必须是 Latin-1；百分号编码后由网关还原中文请求 id。
                "X-Request-ID": urllib.parse.quote(str(请求体.get("请求id", "")), safe=""),
            },
        )
        try:
            开放器 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with 开放器.open(请求, timeout=float(超时秒 if 超时秒 is not None else self.默认超时秒)) as 响应:
                原始 = 响应.read(默认响应上限字节 + 1)
                if len(原始) > 默认响应上限字节:
                    return 响应.status, None, "网关响应超过大小上限"
                return 响应.status, json.loads(原始.decode("utf-8")), ""
        except urllib.error.HTTPError as 错误:
            try:
                try:
                    原始 = 错误.read(默认响应上限字节 + 1)
                    if len(原始) > 默认响应上限字节:
                        数据 = None
                        说明 = "HTTP错误响应超过大小上限"
                    else:
                        数据 = json.loads(原始.decode("utf-8"))
                        说明 = f"HTTP {错误.code}"
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    数据 = None
                    说明 = f"HTTP {错误.code}"
                return 错误.code, 数据, 说明
            finally:
                错误.close()
        except (http.client.RemoteDisconnected, http.client.IncompleteRead) as 错误:
            return 200, None, f"响应不完整：{错误}"
        except (urllib.error.URLError, TimeoutError, OSError) as 错误:
            return 0, None, str(错误)
        except (json.JSONDecodeError, UnicodeDecodeError) as 错误:
            return 200, None, f"响应不是有效 JSON：{错误}"

    @staticmethod
    def _失败(错误码: str, 错误说明: str, 请求id: str) -> dict[str, Any]:
        return {
            "成功": False, "值": None, "错误码": 错误码,
            "错误说明": 错误说明, "句柄": None, "请求id": 请求id,
            "耗时毫秒": 0,
        }


__all__ = ["HTTP连接器"]
