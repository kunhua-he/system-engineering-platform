"""参数探测：按公开参数契约生成「最小合法真实输入」（组件合规测试包拆分件）。

**归属与判据唯一事实源**：
- 正式类型名以 `公共契约/基础类型/类型目录.md` 为唯一事实源，本模块**只认正式类型名**
  —— 历史短名（逻辑/文本/字符串型/…）一律不给值，给值就是「自造名一进契约就有值可用」
  的假绿来源（原文件 E-5 同批清理结论，一并搬来，不重排）。
- 目录型参数一律给**真实存在/真实创建**的目录：判据是「不把占位字符串冒充真实输入」。
- 本模块**只做代码搬家**，成员名/签名/默认值/超时/端口分配/临时目录策略与拆分前逐字一致
  （拆分前 blob 冻结于 `/tmp/拆分基线/合规测试包.py`，
  sha256 前16=`daa8fd30a0565f33`，对应提交 `1dc0f0f6`）。
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真


def _合规真实输入根(根目录: Path) -> Path:
    """返回当前合规工作单元专属输入根，避免并发包互删文件。"""
    覆盖 = os.environ.get("系统底座_合规输入根", "").strip()
    return Path(覆盖) if 覆盖 else 根目录 / "工程缓存" / "合规真实输入"

def _空闲端口() -> int:
    """取得当前进程可用的回环端口；不占用固定代理端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as 套接字:
        套接字.bind(("127.0.0.1", 0))
        return int(套接字.getsockname()[1])

def _最小PNG() -> bytes:
    """返回一个真实的 1x1 PNG，供图像能力做最小成功调用。"""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

def _参数最小值(能力id: str, 参数: dict[str, Any], 根目录: Path) -> Any:
    """按公开参数契约生成最小合法值，不把占位字符串冒充真实输入。"""
    名称 = str(参数.get("名称", ""))
    类型 = str(参数.get("类型", ""))
    能力输入根 = _合规真实输入根(根目录) / hashlib.sha1(
        能力id.encode("utf-8")).hexdigest()[:10]
    if 名称 in {"端口", "监听端口"}:
        return _空闲端口()
    if 名称 in {"调用函数", "回调函数"} or 类型 in {"句柄型"}:
        return lambda *参数值, **关键字值: {"成功": 真, "值": 参数值[0] if 参数值 else ""}
    if 类型 in {"逻辑型"}:
        return bool(参数.get("默认值", False))
    # 只认正式类型名（见 公共契约/基础类型/类型目录.md）；历史短名与非正式名不得出现在这里，
    # 否则会给「非法类型名」造出可调用值、掩盖契约漂移（曾把 浮点数型 当数值型放行）。
    # E-5 同批清理：`逻辑/文本/字符串型/二进制型/映射型/数组型/空/函数/子程序` 这批判据
    # 已删 —— 它们不是正式类型名，全是「自造名一进契约就有值可用」的假绿来源。
    # 实测全仓 参数契约.json 对这批名字 **0 命中**，删除不改变任何真实契约的取值路径。
    if 类型 in {"整数型", "长整数型", "单精度数型", "双精度数型"}:
        if "默认值" in 参数 and 参数.get("默认值") is not None:
            return 参数["默认值"]
        return 1 if 名称 in {"宽度", "高度", "最大边长", "字节数", "最大页数", "最大幻灯片数"} else 0
    if 类型 in {"字节集型"} or 名称 in {"字节", "图片字节"}:
        return _最小PNG()
    if 类型 in {"字典型"}:
        if 名称 in {"编码选项", "请求参数"}:
            return {}
        return {"标题": "合规测试", "内容": "真实输入"} if "文档" in 能力id or "生成" in 能力id else {}
    if 类型 in {"列表型"}:
        if 名称 == "验证命令":
            return [[sys.executable, "-c", "print('ok')"]]
        if 名称 == "补丁列表":
            return []
        return ["合规测试"]
    if 类型 in {"空值型"}:
        return None
    if "提交哈希" in 名称:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=根目录, text=True).strip()
        except (OSError, subprocess.SubprocessError):
            return "0" * 40
    if "仓库路径" in 名称:
        return str(根目录)
    if "目录" in 名称:
        # 凡语义为「目录」的文本参数，一律给**真实的临时目录**。原实现只认白名单里的
        # 若干目录名，其余（技能根目录/目录路径/目标目录/工作目录…）落到下面的文本兜底
        # 分支拿到字面量"合规测试"，被调用方当成相对路径解析 → 在项目根**凭空建出
        # 「合规测试/」目录**（技能库写 索引.json 就是这么来的），污染工作树。
        目录 = 能力输入根
        目录.mkdir(parents=True, exist_ok=True)
        if 名称 == "来源目录":
            (目录 / "来源.txt").write_text("真实快照输入", encoding="utf-8")
        return str(目录)
    if "相对路径" in 名称:
        目录 = 能力输入根
        目录.mkdir(parents=True, exist_ok=True)
        (目录 / "输入.txt").write_text("真实文件输入", encoding="utf-8")
        return "输入.txt"
    if "路径" in 名称 or 名称 in {"文件", "源文件"}:
        扩展名 = {"PDF文档": ".pdf", "表格文档": ".xlsx", "演示文稿": ".pptx",
                 "文字文档": ".docx"}.get(能力id.split(".", 1)[0], ".txt")
        路径 = 能力输入根 / f"输入{扩展名}"
        路径.parent.mkdir(parents=True, exist_ok=True)
        if not 路径.exists():
            if 扩展名 == ".pdf":
                候选 = next((根目录 / "支持库" / "适配层").rglob("示例.pdf"), None)
                if 候选 and 候选.is_file():
                    路径.write_bytes(候选.read_bytes())
                else:
                    路径.write_bytes(b"%PDF-1.4\n")
            elif 扩展名 == ".txt":
                路径.write_text("真实文档输入\n第二段", encoding="utf-8")
            else:
                路径.write_bytes("真实格式输入".encode("utf-8"))
        return str(路径)
    if 名称 in {"地址", "网址", "URL"}:
        return "http://127.0.0.1:1"
    if 名称 in {"提供者名", "提供者"}:
        return "全部"
    if 名称 in {"目标格式", "输出格式", "格式"}:
        return str(参数.get("默认值") or "txt")
    if 名称 in {"文本", "内容", "标题", "页面说明", "旧文本", "新文本", "目标", "字段名", "键", "值", "条目", "分隔符", "语言"}:
        return "合规测试"
    if "时间戳" in 名称:
        return time.time()
    if 名称 in {"提交消息", "操作", "分支名", "期望值", "新值", "期望版本", "资源id", "持有者"}:
        return "合规测试"
    if "默认值" in 参数 and 参数["默认值"] is not None:
        return 参数["默认值"]
    return "合规测试"
