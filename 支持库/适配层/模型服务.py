#!/usr/bin/env python3
"""底座内部 HuggingFace 模型服务；脚本路径不属于对外调用参数。"""
from __future__ import annotations

import argparse
import time
from typing import Any

import torch
import torch.nn.functional as F
import uvicorn
from fastapi import FastAPI
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer


class 模型服务:
    def __init__(self, 模型路径: str, 模型类型: str, 最大长度: int = 8192) -> None:
        self.模型路径 = 模型路径
        self.模型类型 = 模型类型
        self.最大长度 = 最大长度
        self.分词器: Any | None = None
        self.模型: Any | None = None
        self.设备 = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.数据类型 = torch.float16 if self.设备 in {"mps", "cuda"} else torch.float32

    def 加载(self) -> None:
        if self.模型 is not None:
            return
        self.分词器 = AutoTokenizer.from_pretrained(self.模型路径, trust_remote_code=True, padding_side="left")
        类 = AutoModelForCausalLM if self.模型类型 == "重排" else AutoModel
        self.模型 = 类.from_pretrained(self.模型路径, trust_remote_code=True, torch_dtype=self.数据类型).to(self.设备).eval()

    def 生成嵌入(self, 文本列表: list[str]) -> list[list[float]]:
        self.加载()
        分词器, 模型 = self.分词器, self.模型
        assert 分词器 is not None and 模型 is not None
        编码 = 分词器(文本列表, padding=True, truncation=True, max_length=self.最大长度, return_tensors="pt")
        编码 = {键: 值.to(self.设备) for 键, 值 in 编码.items()}
        with torch.inference_mode():
            输出 = 模型(**编码)
            掩码 = 编码["attention_mask"]
            位置 = 掩码.sum(dim=1) - 1
            行号 = torch.arange(输出.last_hidden_state.shape[0], device=self.设备)
            池化 = 输出.last_hidden_state[行号, 位置]
            return F.normalize(池化, p=2, dim=1).float().cpu().tolist()

    def 生成重排(self, 查询: str, 文档列表: list[str]) -> list[float]:
        self.加载()
        分词器, 模型 = self.分词器, self.模型
        assert 分词器 is not None and 模型 is not None
        指令 = "Given a web search query, retrieve relevant passages that answer the query"
        前缀 = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. The answer can only be yes or no.<|im_end|>\n<|im_start|>user\n"
        后缀 = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        文本 = [f"{前缀}<Instruct>: {指令}\n<Query>: {查询}\n<Document>: {文档}{后缀}" for 文档 in 文档列表]
        编码 = 分词器(文本, padding=True, truncation=True, max_length=self.最大长度, return_tensors="pt")
        编码 = {键: 值.to(self.设备) for 键, 值 in 编码.items()}
        真编号 = 分词器.convert_tokens_to_ids("yes")
        假编号 = 分词器.convert_tokens_to_ids("no")
        with torch.inference_mode():
            logits = 模型(**编码).logits[:, -1, :]
            概率 = F.log_softmax(logits[:, [假编号, 真编号]], dim=1)
            return 概率[:, 1].exp().float().cpu().tolist()


def 创建应用(服务: 模型服务) -> FastAPI:
    应用 = FastAPI(title="底座内部模型服务")

    @应用.get("/v1/models")
    async def 模型列表() -> dict:
        return {"object": "list", "data": [{"id": 服务.模型路径, "owned_by": "local"}]}

    @应用.post("/v1/embeddings")
    async def 嵌入(载荷: dict) -> dict:
        输入 = 载荷.get("input")
        文本列表 = 输入 if isinstance(输入, list) else [输入]
        文本列表 = [str(文本 or "") for 文本 in 文本列表]
        开始 = time.perf_counter()
        向量列表 = 服务.生成嵌入(文本列表)
        return {"data": [{"object": "embedding", "index": i, "embedding": 向量} for i, 向量 in enumerate(向量列表)], "model": 载荷.get("model") or 服务.模型路径, "diagnostics": {"duration_ms": round((time.perf_counter() - 开始) * 1000, 2), "device": 服务.设备}}

    @应用.post("/v1/rerank")
    async def 重排(载荷: dict) -> dict:
        查询 = str(载荷.get("query") or "")
        文档列表 = [str(文档) for 文档 in (载荷.get("documents") or [])]
        开始 = time.perf_counter()
        分数列表 = 服务.生成重排(查询, 文档列表)
        结果列表 = [{"index": i, "relevance_score": 分数} for i, 分数 in enumerate(分数列表)]
        结果列表.sort(key=lambda 项: 项["relevance_score"], reverse=True)
        return {"results": 结果列表, "model": 载荷.get("model") or 服务.模型路径, "diagnostics": {"duration_ms": round((time.perf_counter() - 开始) * 1000, 2), "device": 服务.设备}}

    return 应用


def 主程序() -> None:
    解析器 = argparse.ArgumentParser()
    解析器.add_argument("--model-path", required=True)
    解析器.add_argument("--model-type", choices=["LLM", "向量", "重排"], required=True)
    解析器.add_argument("--port", type=int, required=True)
    解析器.add_argument("--host", default="127.0.0.1")
    参数 = 解析器.parse_args()
    uvicorn.run(创建应用(模型服务(参数.model_path, 参数.model_type)), host=参数.host, port=参数.port)


if __name__ == "__main__":
    主程序()
