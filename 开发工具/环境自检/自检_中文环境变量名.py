"""第 7 项：中文环境变量名能不能原样传到子进程（真传 + 逐字回读比对）。

父进程设得进去、子进程读不到时**不会报错，只会静默退化成默认值**，所以本项不接受
「父进程内往返成功」当结论：必须由子进程回读并逐字比对。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from 开发工具.环境自检.基础 import 结论_不支持, 结论_通过, 自检项


_中文键探针 = {
    "系统库运行库": "环境自检_纯中文键_系统库运行库",
    "pdfplumber提供者_禁用库": "环境自检_中英混合键_pdfplumber",
}


def 自检_中文环境变量名() -> 自检项:
    为什么 = ("全仓（不含制品）有 42 处 `os.environ` 读中文键，如 `系统库运行库`、`系统底座_指纹校验`、"
              "`pdfplumber提供者_禁用库`、`V3个人蒸馏地址`。父进程设得进去、子进程读不到时，"
              "**不会报错，只会静默退化成默认值**（指纹校验不启用、运行库落到默认目录）。"
              "本项真起一个子进程：父进程传中文键 → 子进程回读 → 逐字比对值。")
    键表 = dict(_中文键探针)
    环境 = dict(os.environ)
    环境.update(键表)
    代码 = (
        "import json, os, sys\n"
        f"键表 = {json.dumps(list(键表), ensure_ascii=False)}\n"
        "sys.stdout.write(json.dumps({键: os.environ.get(键, None) for 键 in 键表}, "
        "ensure_ascii=False))\n"
    )
    # 顺带验一下父进程内的 setenv/getenv 往返（子进程路径不通时的对照）
    父进程回读: dict[str, Any] = {}
    for 键, 值 in 键表.items():
        os.environ[键] = 值
        try:
            父进程回读[键] = os.environ.get(键)
        finally:
            os.environ.pop(键, None)
    运行 = subprocess.run([sys.executable, "-c", 代码], env=环境,
                       capture_output=True, text=True, timeout=60, check=False)  # 返回码进详情，不检查
    详情 = {"传下去的键": 键表, "子进程退出码": 运行.returncode,
            "子进程原始输出": 运行.stdout[:500], "父进程内 os.environ 往返": 父进程回读}
    子进程回读: dict[str, Any] = {}
    try:
        子进程回读 = json.loads(运行.stdout.strip() or "{}")
    except json.JSONDecodeError as 错误:
        详情["解析失败"] = str(错误)
    详情["子进程回读"] = 子进程回读
    不一致 = {键: (键表[键], 子进程回读.get(键))
            for 键 in 键表 if 子进程回读.get(键) != 键表[键]}
    if 不一致:
        return 自检项("7", "中文环境变量名", 结论_不支持,
                    f"中文键没法原样传到子进程（不一致 {不一致}）；"
                    f"子进程 stderr：{运行.stderr.strip()[:200]!r}",
                    为什么,
                    "全仓约 42 处中文环境变量读取会**静默退化为默认值**（不报错）："
                    "系统库运行库/系统库网关凭证/系统底座_指纹校验/各提供者的『_禁用库』等全部失效。",
                    详情)
    return 自检项("7", "中文环境变量名", 结论_通过,
                f"{len(键表)} 个中文键（含中英混合）父进程传入 → 子进程逐字回读一致",
                为什么, "", 详情)
