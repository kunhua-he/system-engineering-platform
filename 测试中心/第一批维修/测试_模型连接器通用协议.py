"""模型连接器通用协议契约的 TDD 测试：只访问本地 HTTP 夹具。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.大语言模型支持库.模型连接器 import (
    连接LLM,
    生成对话,
    释放句柄,
    查询句柄状态,
)
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型连接器 as 实现  # noqa: E402


class 请求夹具:
    def __init__(self) -> None:
        self.请求: list[tuple[str, dict]] = []
        self.响应状态 = 200
        self.服务 = ThreadingHTTPServer(("127.0.0.1", 0), self._处理器())
        self.线程 = threading.Thread(target=self.服务.serve_forever, daemon=True)
        self.线程.start()

    def _处理器(self):
        夹具 = self

        class 处理器(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                长度 = int(self.headers.get("Content-Length", "0"))
                正文 = json.loads(self.rfile.read(长度) or b"{}")
                夹具.请求.append((self.path, 正文))
                if 夹具.响应状态 != 200:
                    数据 = json.dumps({"error": {"message": "夹具拒绝请求"}}).encode()
                elif self.path.endswith("/responses"):
                    数据 = json.dumps({"output_text": "codex夹具回复"}).encode()
                else:
                    数据 = json.dumps({
                        "choices": [{"message": {"content": "chat夹具回复"}}],
                        "usage": {"total_tokens": 3},
                    }).encode()
                self.send_response(夹具.响应状态)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)

            def log_message(self, format: str, *args) -> None:
                pass

        return 处理器

    @property
    def 地址(self) -> str:
        return f"http://127.0.0.1:{self.服务.server_port}/v1"

    def 关闭(self) -> None:
        self.服务.shutdown()
        self.服务.server_close()
        self.线程.join(timeout=2)


class 测试模型连接器通用协议(unittest.TestCase):
    def setUp(self) -> None:
        实现.连接表.clear()
        self.夹具 = 请求夹具()
        self.句柄表: list[int] = []

    def tearDown(self) -> None:
        for 句柄 in self.句柄表:
            释放句柄(句柄)
        实现.连接表.clear()
        self.夹具.关闭()

    def _连接(self, 协议: str | None = None):
        参数 = {
            "模型": "fixture-model",
            "提供者": "fixture-provider",
            "部署形态": "云端",
            "url": self.夹具.地址,
            "超时秒": 60,
        }
        if 协议 is not None:
            参数["协议"] = 协议
        try:
            结果 = 连接LLM(**参数)
        except TypeError as 错误:
            self.fail(f"连接LLM尚未暴露协议参数：{错误}")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.句柄表.append(结果.值["句柄"])
        return 结果

    def test_连接LLM默认协议并随句柄配置保存(self) -> None:
        结果 = self._连接()
        句柄 = 结果.值["句柄"]
        self.assertEqual(结果.值["协议"], "chat_completions")
        self.assertEqual(实现.连接表[句柄]["配置"]["协议"], "chat_completions")

    def test_连接LLM允许codex_responses协议(self) -> None:
        结果 = self._连接("codex_responses")
        self.assertEqual(结果.值["协议"], "codex_responses")

    def test_连接LLM四种协议输入均只保存并返回长规范值(self) -> None:
        预期 = {
            "chat": "chat_completions",
            "chat_completions": "chat_completions",
            "res": "codex_responses",
            "codex_responses": "codex_responses",
        }
        for 输入协议, 规范协议 in 预期.items():
            with self.subTest(输入协议=输入协议):
                结果 = self._连接(输入协议)
                句柄 = 结果.值["句柄"]
                self.assertEqual(结果.值["协议"], 规范协议)
                self.assertEqual(实现.连接表[句柄]["配置"]["协议"], 规范协议)
                self.assertEqual(查询句柄状态(句柄).值["协议"], 规范协议)

    def test_连接LLM非法协议返回结构化参数错误(self) -> None:
        for 非法协议 in ("responses", "", "unsupported"):
            with self.subTest(非法协议=非法协议):
                结果 = 连接LLM(
                    模型="fixture-model", 提供者="fixture-provider", 部署形态="云端",
                    url=self.夹具.地址, 超时秒=60, 协议=非法协议,
                )
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")
                self.assertIsInstance(结果.错误说明, str)
                self.assertIsNone(结果.值)

    def test_连接LLM拒绝连接阶段流式输出未知参数(self) -> None:
        with self.assertRaises(TypeError):
            连接LLM(
                模型="fixture-model", 提供者="fixture-provider", 部署形态="云端",
                url=self.夹具.地址, 流式输出=True,
            )
        self.assertEqual(self.夹具.请求, [])

    def test_连接LLM未指定超时使用包申报的1800秒默认值(self) -> None:
        结果 = 连接LLM(
            模型="fixture-model", 提供者="fixture-provider", 部署形态="云端",
            url=self.夹具.地址,
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        句柄 = 结果.值["句柄"]
        self.句柄表.append(句柄)
        self.assertEqual(实现.默认超时秒, 1800)
        self.assertEqual(结果.值["超时秒"], 1800)
        self.assertEqual(实现.连接表[句柄]["超时秒"], 1800)

    def test_连接器契约默认超时与实现一致且流式只在生成对话(self) -> None:
        包目录 = 系统根 / "支持库" / "后端" / "大语言模型支持库" / "模型连接器"
        with (包目录 / "包声明.json").open(encoding="utf-8") as 文件:
            包声明 = json.load(文件)
        with (包目录 / "能力定义.json").open(encoding="utf-8") as 文件:
            能力定义 = json.load(文件)
        with (包目录 / "能力契约" / "参数契约.json").open(encoding="utf-8") as 文件:
            参数契约 = json.load(文件)
        with (包目录 / "能力数据" / "能力搜索数据.json").open(encoding="utf-8") as 文件:
            能力搜索 = json.load(文件)

        self.assertEqual(包声明["句柄超时秒"], 1800)
        # 「探测模型端点」是有意的小超时（15 秒）：它是交互式探针，要快速失败，
        # 与「长对话/流式生成」的 1800 秒不是一个口径 —— 不能拿 1800 一刀切。
        小超时例外能力 = ("探测模型端点",)
        for 文档 in (包声明, 能力定义, 参数契约):
            for 能力 in 文档.get("能力列表", 文档.get("能力契约", [])):
                是探针 = any(名 in json.dumps(能力, ensure_ascii=False) for 名 in 小超时例外能力)
                for 参数 in 能力.get("参数", []):
                    if 参数.get("名称") == "超时秒":
                        if 是探针:
                            self.assertEqual(参数.get("默认值"), 15)
                        else:
                            self.assertEqual(参数.get("默认值"), 1800)
        for 能力 in 能力搜索:
            说明 = 能力.get("说明", "")
            self.assertNotIn("连接阶段流式输出", 说明)
            self.assertNotIn("默认 300 秒", 说明)
        说明书 = (包目录 / "说明" / "使用说明.md").read_text(encoding="utf-8")
        self.assertNotIn("默认 300 秒", 说明书)
        self.assertIn("默认 1800 秒", 说明书)
        连接参数 = next(
            能力 for 能力 in 能力定义["能力列表"]
            if 能力["能力id"].endswith(".连接LLM")
        )["参数"]
        self.assertNotIn("流式输出", {参数["名称"] for 参数 in 连接参数})
        生成参数 = next(
            能力 for 能力 in 能力定义["能力列表"]
            if 能力["能力id"].endswith(".生成对话")
        )["参数"]
        self.assertIn("流式输出", {参数["名称"] for 参数 in 生成参数})

    def test_连接LLM本地启动调用传入规范协议参数(self) -> None:
        from tempfile import NamedTemporaryFile
        from unittest.mock import patch

        with NamedTemporaryFile(suffix=".gguf") as 模型文件:
            with patch.object(实现, "启动本地模型", return_value=实现.结果.成功结果({"句柄": 123})) as 启动模拟:
                返回 = 连接LLM(
                    模型="fixture-model", 部署形态="本地", 本地路径=模型文件.name,
                    协议="res", 超时秒=60,
                )
        self.assertTrue(返回.成功, 返回.错误说明)
        # 实现会把「上下文长度」一并带下去（启动期参数，见实现注释：不带会撞
        # `Context size has been exceeded.` 且调用方只看到「HTTP 500」）。
        # 本断言此前漏了该键，属测试滞后于实现，非本次拆分引入。
        启动模拟.assert_called_once_with(
            模型文件.name, None, "LLM", 模型大小字节=None,
            参数={"协议": "codex_responses", "上下文长度": None}, 超时秒=60,
        )

    def test_chat非流式返回统一结果并组装协议请求(self) -> None:
        句柄 = self._连接().值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "你好"}])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["回复"], "chat夹具回复")
        self.assertEqual(len(self.夹具.请求), 1)
        路径, 请求体 = self.夹具.请求[0]
        self.assertEqual(路径, "/v1/chat/completions")
        self.assertEqual(请求体["model"], "fixture-model")
        self.assertEqual(请求体["messages"][0]["content"], "你好")
        self.assertIs(请求体["stream"], False)

    def test_chat别名生成对话仍走chat_completions请求路径(self) -> None:
        句柄 = self._连接("chat").值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "别名"}])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(self.夹具.请求[0][0], "/v1/chat/completions")

    def test_codex_responses组装路径和请求体并返回统一结果(self) -> None:
        句柄 = self._连接("codex_responses").值["句柄"]
        结果 = 生成对话(
            句柄,
            [{"role": "user", "content": "只回复夹具"}],
            "系统规则",
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["回复"], "codex夹具回复")
        路径, 请求体 = self.夹具.请求[0]
        self.assertEqual(路径, "/v1/responses")
        self.assertEqual(请求体["model"], "fixture-model")
        self.assertNotIn("messages", 请求体)
        self.assertEqual(请求体["input"][0], {"role": "system", "content": "系统规则"})
        self.assertEqual(请求体["input"][1]["content"], "只回复夹具")
        self.assertIs(请求体["stream"], False)

    def test_res别名生成对话走codex_responses请求路径(self) -> None:
        句柄 = self._连接("res").值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "别名"}])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(self.夹具.请求[0][0], "/v1/responses")

    def test_codex_responses错误保持统一失败契约(self) -> None:
        self.夹具.响应状态 = 401
        句柄 = self._连接("codex_responses").值["句柄"]
        结果 = 生成对话(句柄, [{"role": "user", "content": "失败"}])
        self.assertFalse(结果.成功)
        self.assertIsNone(结果.值)
        self.assertEqual(结果.错误码, "认证失败")
        self.assertIsInstance(结果.错误说明, str)

    def test_流式输出为真不得静默降级且返回结构化错误(self) -> None:
        import inspect

        self.assertIn("流式输出", inspect.signature(生成对话).parameters)
        self.assertNotIn("流式输出", inspect.signature(连接LLM).parameters)
        句柄 = self._连接().值["句柄"]
        try:
            结果 = 生成对话(
                句柄,
                [{"role": "user", "content": "不要伪造完成"}],
                流式输出=True,
            )
        except TypeError as 错误:
            self.fail(f"生成对话尚未暴露流式输出参数：{错误}")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "流式能力未装配")
        self.assertIn("待补网关流", 结果.错误说明)
        self.assertEqual(结果.详细信息["流式输出"], True)
        self.assertEqual(self.夹具.请求, [])


if __name__ == "__main__":
    unittest.main()
