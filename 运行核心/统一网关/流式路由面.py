"""流式路由面：`/网关/流式`、`/网关/流式/取消` 两条路由的 HTTP 侧实现（本地网关服务器的混入类）。

**为什么独立成文件**：这 2 个方法原先住在 `本地网关.py`（1222 行）的 HTTP 处理类
内部，共 139 行，是**流式通道专用簇**：请求体校验 → `HTTP流式管理器` 开始/取消通道
→ SSE 逐事件写出（`self.wfile`）。与普通调用、反馈路由、边界校验的读取成本完全
可以切开（哲学 6.1）。

**属于本簇的强制接线，不得替换实现**（判据唯一事实源在 `流式HTTP.py` 头部与本
文件注释）：`/网关/流式` 的实体是 `运行核心.统一网关.流式HTTP.HTTP流式管理器`；
HTTP 服务仍必须是 `有界线程HTTP服务器` —— 网关域唯一有界实现（429 结构化拒绝），
**不得**改用 `公共契约.运行时.有界HTTP` 那份（满载不回响应）；两者由
`本地网关.本地网关服务器.__init__` 装配（延迟导入 `流式HTTP`，避免导入环）。

**对外零变化（2026-09-19 拆分）**：`本地网关.本地网关服务器` 的公开成员一个不改；
本类的成员名与签名逐字保留，宿主依赖写成**类注解**（契约）。宿主属性口径的唯一
事实源在 `本地网关.py` `本地网关服务器.__init__`。

**导入方向**：本文件只被 `本地网关.py` 模块级导入，**不得反向导入** `本地网关.py`
（会成环）。`流式请求冲突` / `流式HTTP` 的导入仍是**方法内延迟导入**（原因见
`_处理流式网关请求` 内注释），位置一字未动。
"""

from __future__ import annotations

import uuid
from typing import Any

from 运行核心.统一网关.有界服务器 import 有界线程HTTP服务器  # 网关域唯一有界实现（429 结构化拒绝），勿改用 公共契约.运行时.有界HTTP 那份（满载不回响应）
from 公共契约.基础类型.逻辑类型 import 真, 假


class 流式路由面:
    """流式通道路由簇：通道开始/取消、请求严格校验、SSE 写出与断开诊断。

    宿主依赖（类注解即契约，真源＝`本地网关.本地网关服务器.__init__`）：
    ``_拒绝`` / ``_写JSON`` / ``_读请求体`` 由 `网关边界面` 提供。
    """

    # ---- 宿主契约（由 本地网关.本地网关服务器 提供，只声明不赋值） ----
    网关核心实例: Any

    # 宿主服务器实例引用（由 `本地网关._构造处理类` 显式挂上：`处理类.网关服务器 = self`）
    网关服务器: Any
    流式管理器: Any
    禁止客户端身份: bool
    请求超时秒: float
    headers: Any
    server: Any
    wfile: Any
    client_address: Any
    close_connection: bool

    # ---- 宿主契约（由 网关边界面 提供） ----
    def _拒绝(self, 状态码: int, 错误码: str, 错误说明: str, 操作: str = "HTTP边界") -> None: ...
    def _写JSON(self, 状态码: int, 数据: dict[str, Any]) -> None: ...
    def _读请求体(self) -> tuple[bool, dict[str, Any], str]: ...

    def _处理流式取消请求(self) -> None:
        """按请求 id 取消同一 40007 服务中的流式通道。"""
        读取成功, 请求数据, 错误说明 = self._读请求体()
        if not 读取成功:
            self._拒绝(400, "参数不合法", 错误说明, "流式取消")
            return
        if self.网关服务器.禁止客户端身份 and any(
            str(请求数据.get(字段, ""))
            for 字段 in ("项目id", "用户id", "会话id", "任务id")
        ):
            self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入", "流式取消")
            return
        # 兼容口径（哲学第 5 条 2 项）：未知字段忽略，不因上游多传字段而整条失败。
        请求id = 请求数据.get("请求id", "")
        if not isinstance(请求id, str) or not 请求id or len(请求id) > 64:
            self._拒绝(400, "参数不合法", "取消请求必须提供不超过64字符的请求id", "流式取消")
            return
        成功 = self.网关服务器.流式管理器.取消(请求id)
        if not 成功:
            self._拒绝(404, "句柄无效", "流式请求不存在或已经结束", "流式取消")
            return
        self.网关服务器.网关核心实例.审计.记录(
            操作="流式取消", 请求id=请求id, 成功=真,
            来源地址=self.client_address[0],
        )
        self._写JSON(200, {
            "请求id": 请求id, "操作": "流式取消", "成功": 真,
            "值": {"已取消": 真}, "错误码": "", "错误说明": "",
            "句柄": None, "耗时毫秒": 0.0,
        })

    def _处理流式网关请求(self) -> None:
        """在同一 40007 HTTP 服务内逐事件转发模型连接器 SSE。"""
        读取成功, 请求数据, 错误说明 = self._读请求体()
        if not 读取成功:
            状态码 = 413 if "大小上限" in 错误说明 else 400
            self._拒绝(状态码, "参数不合法", 错误说明, "流式生成对话")
            return
        允许字段 = {"能力id", "参数", "句柄", "请求id", "最大事件数", "最大持续秒"}
        if self.网关服务器.禁止客户端身份 and any(
            str(请求数据.get(字段, ""))
            for 字段 in ("项目id", "用户id", "会话id", "任务id")
        ):
            self._拒绝(403, "权限不足", "项目/用户/会话/任务身份必须由网关凭证注入", "流式生成对话")
            return
        # 冻结的流式字段清单（协议只增不删，只作说明，不再用于拒绝未知字段）：
        # 能力id / 参数 / 句柄 / 请求id / 最大事件数 / 最大持续秒
        # 兼容口径（哲学第 5 条 2 项）：未知字段忽略，只校验必填与类型。
        能力id = 请求数据.get("能力id", "")
        目标能力 = "大语言模型支持库.模型连接器.生成对话"
        if 能力id != 目标能力:
            self._拒绝(404, "能力不存在", "流式入口只支持模型连接器生成对话", "流式生成对话")
            return
        参数 = 请求数据.get("参数")
        if not isinstance(参数, dict):
            self._拒绝(400, "参数不合法", "流式参数必须是对象", "流式生成对话")
            return
        参数 = dict(参数)
        顶层句柄 = 请求数据.get("句柄")
        参数句柄 = 参数.get("句柄")
        if 顶层句柄 is not None and 参数句柄 is not None and 顶层句柄 != 参数句柄:
            self._拒绝(400, "参数不合法", "顶层句柄与参数句柄不一致", "流式生成对话")
            return
        句柄 = 顶层句柄 if 顶层句柄 is not None else 参数句柄
        if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
            self._拒绝(400, "参数不合法", "句柄必须是 1 到 999999 的整数", "流式生成对话")
            return
        消息列表 = 参数.get("消息列表")
        if not isinstance(消息列表, list) or not 消息列表:
            self._拒绝(400, "参数不合法", "消息列表必须是非空列表", "流式生成对话")
            return
        流式输出 = 参数.get("流式输出")
        if 流式输出 is not 真:
            self._拒绝(400, "参数不合法", "流式输出必须是逻辑型真值", "流式生成对话")
            return
        请求id = str(请求数据.get("请求id", self.headers.get("X-请求-id", "")))[:64]
        if not 请求id:
            请求id = uuid.uuid4().hex[:16]
        try:
            最大事件数 = 请求数据.get("最大事件数", 1000)
            最大持续秒 = 请求数据.get("最大持续秒", self.网关服务器.请求超时秒)
            def 事件生成函数(_停止事件):
                # SSE 传输特例：JSON 结果契约装不下生成器，故直取模型连接器包级
                # 中文入口导出的流式实现；实现目录未被穿透，不构成第二条跨包通道。
                from 支持库.后端.大语言模型支持库.模型连接器 import 流式生成对话
                return 流式生成对话(
                    句柄=句柄,
                    消息列表=消息列表,
                    系统提示词=参数.get("系统提示词"),
                    流式输出=真,
                    温度=参数.get("温度"),
                    最大令牌数=参数.get("最大令牌数"),
                    工具=参数.get("工具"),
                    响应格式=参数.get("响应格式"),
                    附加请求头=参数.get("附加请求头"),
                )
            通道 = self.网关服务器.流式管理器.开始(
                能力id=能力id,
                事件生成函数=事件生成函数,
                请求id=请求id,
                最大事件数=最大事件数,
                最大持续秒=最大持续秒,
            )
        except RuntimeError as 错误:
            self._拒绝(429, "限流", str(错误), "流式生成对话")
            return
        except (TypeError, ValueError) as 错误:
            # 判据＝异常类型 + 公开错误码，**不按消息文案**（P1-6）：
            # 冲突由 流式HTTP.流式请求冲突 抛出（错误码 幂等键冲突），
            # 异常文案改字（含中文化）不影响状态码结论。
            # 延迟导入：流式HTTP.py 模块级 import 本模块，模块级反向导入会成环。
            from 运行核心.统一网关.流式HTTP import 流式请求冲突
            冲突 = (isinstance(错误, 流式请求冲突)
                    or getattr(错误, "错误码", "") == "幂等键冲突")
            状态码 = 409 if 冲突 else 400
            错误码 = "幂等键冲突" if 冲突 else "参数不合法"
            self._拒绝(状态码, 错误码, str(错误), "流式生成对话")
            return
        self.网关服务器.网关核心实例.审计.记录(
            操作="流式生成对话", 能力id=能力id, 请求id=通道.请求id,
            成功=真, 来源地址=self.client_address[0],
        )
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            for 事件 in 通道.迭代事件():
                self.wfile.write(通道.格式事件行(事件))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError) as 错误:
            if isinstance(self.server, 有界线程HTTP服务器):
                self.server.记录连接诊断("流式写回断开", 错误)
            self.网关服务器.流式管理器.断开(通道.请求id)
        finally:
            self.网关服务器.流式管理器.清理(通道.请求id)
            self.close_connection = True
