"""把开发态项目编译成不依赖开发网关的独立目录。

输入约定：项目声明.json、前端/*.json、模块/流程/*.json、运行入口/（可选）。
编译只复制被页面/流程/入口引用的能力对应支持库与模块，运行核心属于固定运行时。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 开发工具.轻代码前端编辑器.页面模型 import 校验页面
from 开发工具.项目编译.正式包索引 import 构建索引, 校验显式包引用, 校验能力引用, 解析依赖闭包
固定运行时目录 = ("公共契约", "后端核心", "运行核心", "前端核心")
忽略目录 = {"__pycache__", ".pytest_cache", ".ruff_cache", "工程缓存"}
运行时适配文件 = ("__init__.py", "脱敏模式.py", "系统探针.py", "适配契约.py")
依赖锁文件名 = "依赖锁.json"
编译器版本 = "1.2.0"


def _来源指纹(排除目录: Path | None = None) -> dict[str, str]:
    """记录编译输入对应的 Git 提交和工作区指纹，避免旧制品冒充当前源码。"""
    def 执行(命令: list[str]) -> str:
        try:
            结果 = subprocess.run(
                命令, cwd=系统根, capture_output=True, text=True, timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return 结果.stdout.strip() if 结果.returncode == 0 else ""

    提交 = 执行(["git", "rev-parse", "HEAD"])
    状态 = 执行(["git", "status", "--porcelain=v1", "-z"])
    if 排除目录 is not None:
        try:
            排除相对 = 排除目录.resolve().relative_to(系统根.resolve()).as_posix().rstrip("/") + "/"
            条目 = []
            for 项 in 状态.split("\0"):
                if not 项:
                    continue
                路径 = 项[3:] if len(项) >= 4 and 项[2] == " " else 项
                if not 路径.startswith(排除相对):
                    条目.append(项)
            状态 = "\0".join(条目)
        except ValueError:
            pass
    return {
        "提交": 提交 or "未知",
        "工作区摘要": hashlib.sha256(状态.encode("utf-8")).hexdigest(),
        "工作区状态": "干净" if not 状态 else "含未提交变更",
    }


def _制品文件摘要(目录: Path) -> dict[str, Any]:
    """对制品文件做稳定清单摘要；元数据文件不纳入自身摘要。"""
    文件表 = []
    for 文件 in sorted(目录.rglob("*")):
        if not 文件.is_file() or 文件.name in {"制品来源.json", "制品完整性摘要.json", "编译清单.json"}:
            continue
        if 文件.suffix in {".pyc", ".pyo"} or "__pycache__" in 文件.parts:
            continue
        文件表.append({
            "路径": 文件.relative_to(目录).as_posix(),
            "sha256": hashlib.sha256(文件.read_bytes()).hexdigest(),
        })
    汇总 = hashlib.sha256()
    for 项 in 文件表:
        汇总.update(项["路径"].encode("utf-8")); 汇总.update(项["sha256"].encode("ascii"))
    return {"摘要算法": "sha256", "文件数": len(文件表), "文件清单": 文件表,
            "制品摘要": 汇总.hexdigest()}


def _读取(路径: Path, 默认: Any = None) -> Any:
    if not 路径.is_file():
        return 默认
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        raise ValueError(f"JSON 不合法: {路径}: {错误}") from 错误


def _所有包(根: Path, 类型目录: str) -> dict[str, tuple[Path, dict[str, Any]]]:
    索引 = 构建索引(根)
    return dict(索引["支持库" if 类型目录 == "支持库" else "模块库"])


def _遍历JSON(项目目录: Path) -> list[dict[str, Any]]:
    文件表 = []
    输入目录 = [项目目录 / "前端" / "页面", 项目目录 / "模块", 项目目录 / "后端"]
    候选路径 = [路径 for 目录 in 输入目录 if 目录.is_dir() for 路径 in 目录.rglob("*.json")]
    for 路径 in 候选路径:
        if any(部分 in 忽略目录 for 部分 in 路径.parts):
            continue
        数据 = _读取(路径, {})
        if isinstance(数据, dict):
            文件表.append(数据)
    return 文件表


def _引用能力(项目目录: Path) -> tuple[set[str], set[str]]:
    能力集合: set[str] = set()
    模块集合: set[str] = set()
    for 数据 in _遍历JSON(项目目录):
        def 扫描(值: Any) -> None:
            if isinstance(值, dict):
                for 键, 子值 in 值.items():
                    if 键 in ("能力id", "能力", "能力依赖"):
                        扫描能力(子值)
                    elif 键 in ("模块id", "模块", "模块依赖"):
                        扫描模块(子值)
                    else:
                        扫描(子值)
            elif isinstance(值, list):
                for 项 in 值:
                    扫描(项)
        def 扫描能力(值: Any) -> None:
            if isinstance(值, str) and 值.strip(): 能力集合.add(值.strip())
            elif isinstance(值, list):
                for 项 in 值: 扫描能力(项)
            elif isinstance(值, dict):
                扫描能力(值.get("id") or 值.get("能力id") or "")
        def 扫描模块(值: Any) -> None:
            if isinstance(值, str) and 值.strip(): 模块集合.add(值.strip())
            elif isinstance(值, list):
                for 项 in 值: 扫描模块(项)
            elif isinstance(值, dict):
                扫描模块(值.get("包id") or 值.get("模块id") or "")
        扫描(数据)
    return 能力集合, 模块集合


def _复制目录(源: Path, 目标: Path) -> None:
    # 编译输入必须闭合在源目录内；拒绝符号链接，避免 copytree 跟随链接
    # 把源目录外的文件带入独立制品。
    符号链接 = [路径 for 路径 in 源.rglob("*") if 路径.is_symlink()]
    if 符号链接:
        相对 = 符号链接[0].relative_to(源).as_posix()
        raise ValueError(f"编译输入包含不允许的符号链接: {相对}")
    if 目标.exists(): shutil.rmtree(目标)
    shutil.copytree(源, 目标, ignore=shutil.ignore_patterns(*忽略目录, "*.pyc"))


def _依赖项目标(依赖: Any) -> tuple[str, str, str | None]:
    """把包声明中的依赖统一成 (包id, 能力id, 版本约束)。"""
    if isinstance(依赖, str):
        return 依赖.strip(), "", None
    if not isinstance(依赖, dict):
        return "", "", None
    包id = str(依赖.get("包id") or 依赖.get("包") or "").strip()
    能力id = str(依赖.get("能力id") or 依赖.get("能力") or "").strip()
    版本 = 依赖.get("版本")
    return 包id, 能力id, str(版本) if 版本 is not None else None


def _解析依赖闭包(
    支持库表: dict[str, tuple[Path, dict[str, Any]]],
    模块表: dict[str, tuple[Path, dict[str, Any]]],
    能力归属: dict[str, str],
    初始支持库: set[str],
    初始模块: set[str],
) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    """兼容旧私有调用名；实际解析唯一落在正式包索引。"""
    return 解析依赖闭包(
        系统根, 初始支持库, 初始模块,
        支持库表=支持库表, 模块表=模块表, 能力归属表=能力归属,
    )


def _生成HTML(页面: dict[str, Any]) -> str:
    """把统一页面 IR 编译成可运行 DOM；保留树、布局、事件和绑定。"""
    数据 = json.dumps(页面, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title></title><style>body{{font-family:system-ui;max-width:900px;margin:24px auto;padding:0 20px;color:#1f2937}}.组件{{box-sizing:border-box;margin:8px;padding:8px;border:1px solid #d1d5db;border-radius:6px}}.容器{{min-height:80px;background:#f8fafc}}textarea{{padding:8px}}button{{padding:8px 18px;cursor:pointer}}pre{{white-space:pre-wrap;background:#f3f4f6;padding:10px;min-height:32px}}</style></head><body><h1 id="标题"></h1><main id="页面"></main><script>
const 页面={数据},节点=new Map();document.title=页面.标题||'';document.querySelector('#标题').textContent=页面.标题||'';
function 取值(v){{return typeof v==='string'&&v.startsWith('$')?(document.getElementById('输入-'+v.slice(1))||{{}}).value||'':v}}
async function 调用(c,e,o){{const 能力id=e.能力id||c.属性?.能力id||'';if(!能力id){{o.textContent='未绑定能力';return}}const 参数={{}};for(const[k,v]of Object.entries(e.参数模板||c.属性?.参数模板||{{}}))参数[k]=取值(v);o.textContent='调用中...';try{{const r=await fetch('/网关/调用',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{能力id,参数}})}}),d=await r.json();o.textContent=d.成功?JSON.stringify(d.值,null,2):`${{d.错误码}}: ${{d.错误说明}}`;const id=c.属性?.结果组件id;if(d.成功&&id&&节点.get(id))节点.get(id).textContent=JSON.stringify(d.值)}}catch(x){{o.textContent='网关断开: '+x}}}}
function 创建(c){{const a=c.属性||{{}},x=document.createElement('section');x.className='组件 '+(c.类型||'');x.dataset.组件id=c.组件id;x.style.marginLeft=(Number(a.左||0))+'px';x.style.marginTop=(Number(a.上||0))+'px';if(a.宽度)x.style.width=a.宽度+'px';if(a.高度)x.style.minHeight=a.高度+'px';let o=document.createElement('pre');o.textContent=String(a.文本||c.显示名称||c.组件id);if(c.类型==='编辑框'||c.类型==='输入框'){{x.textContent='';let i=document.createElement('textarea');i.id='输入-'+c.组件id;i.value=String(a.文本||'');i.placeholder=String(a.占位文本||'');x.append(i)}}else if(c.类型==='按钮'){{x.textContent='';let b=document.createElement('button');b.textContent=String(a.文本||c.显示名称||c.组件id);x.append(b,o);for(const e of c.事件||[])if(e.名称==='点击')b.onclick=()=>调用(c,e,o)}}else if(c.类型==='容器'){{x.textContent='';x.classList.add('容器')}}else x.append(o);节点.set(c.组件id,o);return x}}
function 挂载(c,p){{const x=创建(c);p.append(x);for(const y of 页面.组件列表||[])if(y.父组件id===c.组件id)挂载(y,x)}}for(const c of 页面.组件列表||[])if(!c.父组件id)挂载(c,document.querySelector('#页面'));
</script></body></html>'''


def _生成启动器(项目id: str) -> str:
    """生成独立 HTML 启动器，源码只依赖制品目录内的运行核心。"""
    return f'''"""{项目id} 独立 HTML 启动器；不依赖开发网关。"""
from __future__ import annotations
import os, sys
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import argparse, json, threading, urllib.error, urllib.request, webbrowser
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path: sys.path.insert(0, str(根))
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
def 主函数(端口=45080, 自动打开=True):
    from 公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    后端 = 后端核心(系统根目录=根); 启动 = 后端.启动()
    if not 启动.成功: raise RuntimeError(f"独立运行时装配失败: {{启动.错误说明}}")
    网关 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0); 成功, 说明 = 网关.启动()
    if not 成功: 后端.优雅关闭(); raise RuntimeError(说明)
    页面 = (根 / "前端" / "编译页面" / "index.html").read_bytes(); 网关地址 = f"http://127.0.0.1:{{网关.端口}}"
    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式, *参数): return
        def do_GET(self):
            if self.path != "/": self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(页面))); self.end_headers(); self.wfile.write(页面)
        def do_POST(self):
            if self.path != "/网关/调用": self.send_error(404); return
            try:
                长度 = int(self.headers.get("Content-Length", "-1"))
                if 长度 < 0 or 长度 > 1024 * 1024: raise ValueError("请求体超过上限")
                if "application/json" not in self.headers.get("Content-Type", "").lower(): raise ValueError("请求正文必须使用 JSON")
                请求数据 = json.loads(self.rfile.read(长度).decode("utf-8"))
                if not isinstance(请求数据, dict): raise ValueError("请求必须是对象")
                请求正文 = json.dumps(请求数据, ensure_ascii=False).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as 错误:
                正文 = json.dumps({{"成功":False,"错误码":"参数不合法","错误说明":str(错误)}}, ensure_ascii=False).encode()
                self.send_response(400); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
            请求 = urllib.request.Request(网关地址 + quote("/网关/调用"), data=请求正文, headers={{"Content-Type":"application/json"}})
            try:
                with urllib.request.urlopen(请求, timeout=10) as 响应: 状态码, 正文 = 响应.status, 响应.read()
            except urllib.error.HTTPError as 错误:
                状态码, 正文 = 错误.code, 错误.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                状态码 = 502; 正文 = json.dumps({{"成功":False,"错误码":"网关断开","错误说明":"网关不可访问"}}, ensure_ascii=False).encode()
            self.send_response(状态码); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文)
    服务 = ThreadingHTTPServer(("127.0.0.1", 端口), 处理器); 地址 = f"http://127.0.0.1:{{服务.server_port}}"
    try:
        threading.Thread(target=服务.serve_forever, daemon=True).start(); print(f"独立项目已启动: {{地址}}")
        if 自动打开: webbrowser.open(地址)
        threading.Event().wait()
    except KeyboardInterrupt: return 0
    finally:
        服务.shutdown(); 服务.server_close(); 网关.优雅停止(); 后端.优雅关闭()
    return 0
if __name__ == "__main__":
    解析器=argparse.ArgumentParser(); 解析器.add_argument("--端口", type=int, default=45080); 解析器.add_argument("--不自动打开", action="store_true"); 参数=解析器.parse_args(); raise SystemExit(主函数(参数.端口, not 参数.不自动打开))
'''


def 编译项目(项目目录: Path, 输出目录: Path) -> dict[str, Any]:
    项目目录 = 项目目录.resolve(); 输出目录 = 输出目录.resolve()
    声明 = _读取(项目目录 / "项目声明.json") or _读取(项目目录 / "项目.json")
    if not isinstance(声明, dict) or not 声明.get("项目id"):
        raise ValueError("项目必须提供 项目声明.json 或 项目.json，且包含项目id")
    索引 = 构建索引(系统根)
    支持库表 = dict(索引["支持库"]); 模块表 = dict(索引["模块库"])
    能力集合, 模块集合 = _引用能力(项目目录)
    能力归属: dict[str, str] = dict(索引["能力所有者"])
    for 能力id in sorted(能力集合):
        校验能力引用(系统根, 能力id)
        if 能力归属.get(能力id, "").startswith("冲突:"):
            raise ValueError(f"公开能力重复 owner: {能力id} -> {能力归属[能力id]}")
    for 包id in sorted(模块集合):
        校验显式包引用(系统根, 包id)
    # 能力引用自动选中其所属包；显式模块引用优先加入模块闭包。
    选中模块 = set(模块集合)
    选中支持库: set[str] = set()
    待处理能力 = list(能力集合)
    while 待处理能力:
        能力id = 待处理能力.pop()
        包id = 能力归属.get(能力id)
        if not 包id: raise ValueError(f"找不到能力所属包: {能力id}")
        if 包id.startswith("模块库."): 选中模块.add(包id)
        else: 选中支持库.add(包id)
    # 支持库与模块统一递归展开能力/包依赖，并生成制品依赖锁。
    选中支持库, 选中模块, 依赖锁 = _解析依赖闭包(
        支持库表, 模块表, 能力归属, 选中支持库, 选中模块)
    if not 能力集合 and not 模块集合:
        raise ValueError("项目没有发现能力id或模块id引用，拒绝生成空项目")
    if 输出目录.exists(): shutil.rmtree(输出目录)
    输出目录.mkdir(parents=True)
    for 目录名 in 固定运行时目录:
        _复制目录(系统根 / 目录名, 输出目录 / 目录名)
    # 运行核心的内部适配器，不属于用户业务支持库，但属于启动闭包。
    (输出目录 / "支持库" / "适配层").mkdir(parents=True, exist_ok=True)
    for 文件名 in 运行时适配文件:
        源 = 系统根 / "支持库" / "适配层" / 文件名
        if 源.is_file(): shutil.copy2(源, 输出目录 / "支持库" / "适配层" / 文件名)
    for 目录名 in ("提供者注册表", "密码签名提供者", "数据库适配器", "HTTP服务适配器", "本地进程适配器", "动态库适配器", "配置契约"):
        源目录 = 系统根 / "支持库" / "适配层" / 目录名
        if not 源目录.is_dir():
            continue
        目标目录 = 输出目录 / "支持库" / "适配层" / 目录名
        _复制目录(源目录, 目标目录)
        # 密码签名实现是运行核心的内部依赖，不是制品公开 Provider；不复制
        # 包声明/依赖锁/契约元数据，避免独立项目被运行时误发现并生成环境缓存。
        if 目录名 == "密码签名提供者":
            for 文件 in list(目标目录.rglob("*")):
                if 文件.is_file() and 文件.name != "__init__.py" and "实现" not in 文件.parts:
                    文件.unlink()
            for 文件 in (目标目录 / "实现").rglob("*.pyc") if (目标目录 / "实现").is_dir() else []:
                文件.unlink()
    (输出目录 / "支持库").mkdir(parents=True, exist_ok=True)
    (输出目录 / "模块库").mkdir(parents=True, exist_ok=True)
    shutil.copy2(系统根 / "支持库" / "__init__.py", 输出目录 / "支持库" / "__init__.py")
    shutil.copy2(系统根 / "模块库" / "__init__.py", 输出目录 / "模块库" / "__init__.py")
    for 包id in sorted(选中支持库):
        if 包id not in 支持库表: raise ValueError(f"找不到支持库包: {包id}")
        源, _ = 支持库表[包id]; _复制目录(源, 输出目录 / "支持库" / 源.relative_to(系统根 / "支持库"))
    for 包id in sorted(选中模块):
        源, _ = 模块表[包id]; _复制目录(源, 输出目录 / "模块库" / 源.relative_to(系统根 / "模块库"))
    for 名称 in ("项目声明.json", "项目.json", "模块", "资源"):
        源 = 项目目录 / 名称
        if 源.is_file(): (输出目录 / 名称).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(源, 输出目录 / 名称)
        elif 源.is_dir(): _复制目录(源, 输出目录 / 名称)
    页面文件表 = sorted((项目目录 / "前端" / "页面").glob("*.json")) if (项目目录 / "前端" / "页面").is_dir() else []
    页面表: list[dict[str, Any]] = []
    路由表: dict[str, str] = {}
    for 页面文件 in 页面文件表:
        if 页面文件.name in {"编译制品.json", "编辑记录.json"}:
            continue
        页面项 = 校验页面(_读取(页面文件, {}))
        路由 = str(页面项["路由"])
        if 路由 in 路由表:
            raise ValueError(f"页面路由重复: {路由} ({路由表[路由]} / {页面项['页面id']})")
        路由表[路由] = str(页面项["页面id"])
        页面表.append(页面项)
    if not 页面表:
        页面表 = [校验页面({
            "页面id": "主页", "标题": 声明.get("项目名称", 声明["项目id"]), "路由": "/", "组件列表": []
        })]
    编译页面目录 = 输出目录 / "前端" / "编译页面"
    编译页面目录.mkdir(parents=True, exist_ok=True)
    for 页面 in 页面表:
        文件名 = "index.html" if 页面["路由"] == "/" else f"{页面['页面id']}.html"
        (编译页面目录 / 文件名).write_text(_生成HTML(页面), encoding="utf-8")
    输入摘要 = hashlib.sha256()
    for 文件 in sorted((项目目录 / "前端" / "页面").glob("*.json")):
        输入摘要.update(文件.name.encode("utf-8")); 输入摘要.update(文件.read_bytes())
    (编译页面目录 / "编译制品.json").write_text(json.dumps({
        "制品类型": "轻代码前端制品", "契约版本": "1.0.0",
        "源页面摘要": 输入摘要.hexdigest(), "页面数": len(页面表),
        "页面id": [页面["页面id"] for 页面 in 页面表],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (编译页面目录 / "路由表.json").write_text(json.dumps(路由表, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    启动器目录 = 输出目录 / "运行入口"
    启动器目录.mkdir(exist_ok=True)
    (启动器目录 / "启动.py").write_text(_生成启动器(str(声明["项目id"])), encoding="utf-8")
    (启动器目录 / "启动网页.command").write_text(
        '#!/bin/sh\nset -eu\ncd "$(dirname "$0")/.." || exit 1\nexec env PYTHONDONTWRITEBYTECODE=1 python3 -B 运行入口/启动.py\n', encoding="utf-8"
    )
    (启动器目录 / "启动网页.bat").write_text(
        '@echo off\nset PYTHONDONTWRITEBYTECODE=1\ncd /d "%~dp0.."\npython -B 运行入口\\启动.py\n', encoding="utf-8"
    )
    (启动器目录 / "__init__.py").write_text('"""独立项目运行入口。"""\n', encoding="utf-8")
    (启动器目录 / "启动网页.command").chmod(0o755)
    来源 = _来源指纹(输出目录)
    清单 = {"制品类型": "独立项目", "编译器版本": 编译器版本, "项目id": 声明["项目id"],
           "来源目录": "编译输入项目", "能力引用": sorted(能力集合), "模块引用": sorted(选中模块),
           "支持库引用": sorted(选中支持库), "开发网关": "不包含",
           "前端制品": "前端/编译页面/index.html",
           "启动器": ["运行入口/启动.py", "运行入口/启动网页.command", "运行入口/启动网页.bat"],
           "运行时目录": list(固定运行时目录),
           "依赖锁": 依赖锁文件名,
           "源页面摘要": 输入摘要.hexdigest(), "源页面修订号": [int(页面.get("修订号", 0)) for 页面 in 页面表]}
    清单["来源提交"] = 来源["提交"]
    清单["来源工作区摘要"] = 来源["工作区摘要"]
    清单["来源工作区状态"] = 来源["工作区状态"]
    (输出目录 / "编译清单.json").write_text(json.dumps(清单, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (输出目录 / 依赖锁文件名).write_text(json.dumps({
        "格式": "独立项目依赖锁",
        "版本": "1.0.0",
        "项目id": 声明["项目id"],
        "包": [
            {"包id": 包id, "类型": "支持库", "版本": 支持库表[包id][1].get("版本", "")}
            for 包id in sorted(选中支持库)
        ] + [
            {"包id": 包id, "类型": "模块库", "版本": 模块表[包id][1].get("版本", "")}
            for 包id in sorted(选中模块)
        ],
        "依赖闭包": 依赖锁,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (输出目录 / "制品来源.json").write_text(json.dumps({
        "格式": "独立制品来源绑定", "编译器版本": 编译器版本,
        "项目id": 声明["项目id"], **来源,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (输出目录 / "制品完整性摘要.json").write_text(
        json.dumps(_制品文件摘要(输出目录), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    清单["制品摘要文件"] = "制品完整性摘要.json"
    清单["来源绑定文件"] = "制品来源.json"
    (输出目录 / "编译清单.json").write_text(json.dumps(清单, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 清单


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="编译独立项目制品")
    解析器.add_argument("项目目录", type=Path); 解析器.add_argument("--输出", type=Path, required=True)
    参数 = 解析器.parse_args()
    try: 结果 = 编译项目(参数.项目目录, 参数.输出)
    except (ValueError, OSError) as 错误: print(f"编译阻断：{错误}"); raise SystemExit(1)
    print(json.dumps(结果, ensure_ascii=False, indent=2))
