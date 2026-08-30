"""把开发态项目编译成不依赖开发网关的独立目录。

输入约定：项目声明.json、前端/*.json、模块/流程/*.json、运行入口/（可选）。
编译只复制被页面/流程/入口引用的能力对应支持库与模块，运行核心属于固定运行时。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import os
import py_compile
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 开发工具.轻代码前端编辑器.页面模型 import 校验页面
from 开发工具.项目编译.工作区指纹 import 计算工作区字节指纹
from 开发工具.项目编译.正式包索引 import 构建索引, 校验显式包引用, 校验能力引用, 解析依赖闭包
固定运行时目录 = ("公共契约", "后端核心", "运行核心", "前端核心")
忽略目录 = {"__pycache__", ".pytest_cache", ".ruff_cache", "工程缓存"}
运行时适配文件 = ("__init__.py", "脱敏模式.py", "系统探针.py", "适配契约.py")
依赖锁文件名 = "依赖锁.json"
编译器版本 = "1.3.0"
关键源码目录 = {
    ".git", "公共契约", "平台控制面", "启动监督器", "运行核心", "前端核心",
    "后端核心", "支持库", "模块库", "项目适配层", "开发工具", "测试中心",
    "示例项目", "客户端", "MCP工具箱", "开发文档",
}


def _来源指纹(排除目录: Path | None = None) -> dict[str, str]:
    """兼容既有调用名；唯一实现使用冻结的正式文件字节语义。"""
    _ = 排除目录  # 排除规则由公共实现固定，调用方不得临时改变语义。
    结果 = 计算工作区字节指纹(系统根)
    return {键: str(结果[键]) for 键 in ("提交", "工作区摘要", "工作区状态")}


def 校验项目id(项目id: Any) -> str:
    """项目 id 必须是非关键字的点分 Python 标识符，拒绝类型漂移和源码注入。"""
    if not isinstance(项目id, str) or not 项目id:
        raise ValueError("项目id必须是非空字符串")
    if 项目id != 项目id.strip():
        raise ValueError("项目id不能含首尾空白")
    分段 = 项目id.split(".")
    if any(not 段 or not 段.isidentifier() or keyword.iskeyword(段) for 段 in 分段):
        raise ValueError("项目id必须是点分标识符，且每段不能是关键字")
    if len(项目id) > 200:
        raise ValueError("项目id过长")
    return 项目id


def 校验输出目录(项目目录: Path, 输出目录: Path) -> Path:
    """拒绝会覆盖项目、源码、祖先或关键目录的输出目标。"""
    项目 = Path(项目目录).resolve()
    输出 = Path(输出目录).resolve()
    源码根 = 系统根.resolve()
    if 输出 == 项目 or 输出 in 项目.parents:
        raise ValueError(f"输出目录危险：拒绝项目根或其祖先: {输出}")
    if 输出 == 源码根 or 输出 in 源码根.parents:
        raise ValueError(f"输出目录危险：拒绝源码根或其祖先: {输出}")
    try:
        输出.relative_to(源码根)
    except ValueError:
        pass
    else:
        工程缓存 = 源码根 / "工程缓存"
        if 输出 == 工程缓存:
            raise ValueError(f"输出目录危险：拒绝工程缓存根目录: {输出}")
        if 工程缓存 not in 输出.parents:
            raise ValueError(f"输出目录危险：源码树内只允许工程缓存子目录: {输出}")
    for 名称 in 关键源码目录:
        关键目录 = 源码根 / 名称
        if 输出 == 关键目录 or 关键目录 in 输出.parents:
            raise ValueError(f"输出目录危险：拒绝源码关键目录: {输出}")
    for 名称 in ("前端", "后端", "模块", "运行入口", "资源", ".git"):
        项目源码 = 项目 / 名称
        if 输出 == 项目源码 or 项目源码 in 输出.parents:
            raise ValueError(f"输出目录危险：拒绝项目源码目录: {输出}")
    return 输出


def _准备输出目录(项目目录: Path, 输出目录: Path) -> Path:
    """在任何递归删除前重新解析并最终校验，缩短路径替换竞态窗口。"""
    输出 = 校验输出目录(项目目录, 输出目录)
    if 输出.exists():
        shutil.rmtree(输出)
    输出.mkdir(parents=True)
    return 输出


def _写入并编译Python(路径: Path, 内容: str) -> None:
    """安全写入生成源码并立即 py_compile；临时 pyc 不进入正式制品。"""
    路径.write_text(内容, encoding="utf-8")
    描述符, 临时pyc = tempfile.mkstemp(prefix="统一编译语法_", suffix=".pyc")
    os.close(描述符)
    Path(临时pyc).unlink(missing_ok=True)
    try:
        py_compile.compile(str(路径), cfile=临时pyc, doraise=True)
    finally:
        Path(临时pyc).unlink(missing_ok=True)


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


def _项目JSON路径(项目目录: Path) -> list[Path]:
    输入目录 = [项目目录 / "前端" / "页面", 项目目录 / "模块", 项目目录 / "后端"]
    return sorted({
        路径.resolve() for 目录 in 输入目录 if 目录.is_dir() for 路径 in 目录.rglob("*.json")
        if not any(部分 in 忽略目录 for 部分 in 路径.parts)
        and 路径.name not in {"编译制品.json", "编辑记录.json"}
    })


def _收集数据引用(数据表: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    能力集合: set[str] = set()
    模块集合: set[str] = set()

    def 扫描能力(值: Any) -> None:
        if isinstance(值, str) and 值.strip():
            能力集合.add(值.strip())
        elif isinstance(值, list):
            for 项 in 值: 扫描能力(项)
        elif isinstance(值, dict):
            扫描能力(值.get("id") or 值.get("能力id") or "")

    def 扫描模块(值: Any) -> None:
        if isinstance(值, str) and 值.strip():
            模块集合.add(值.strip())
        elif isinstance(值, list):
            for 项 in 值: 扫描模块(项)
        elif isinstance(值, dict):
            扫描模块(值.get("包id") or 值.get("模块id") or "")

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
            for 项 in 值: 扫描(项)

    for 数据 in 数据表:
        扫描(数据)
    return 能力集合, 模块集合


def _引用能力(项目目录: Path) -> tuple[set[str], set[str]]:
    return _收集数据引用(_遍历JSON(项目目录))


def 计算影响闭包(
    项目目录: Path, *, 文件: Path | None = None, 能力: str | None = None,
    组件: str | None = None,
) -> dict[str, Any]:
    """从一个文件/能力/组件计算本次契约、依赖、边界与页面影响闭包。"""
    项目 = Path(项目目录).resolve()
    已给 = sum(值 is not None for 值 in (文件, 能力, 组件))
    if 已给 != 1:
        raise ValueError("本次变更必须且只能提供文件、能力、组件之一")
    全部路径 = _项目JSON路径(项目)
    选中路径: list[Path] = []
    类型, 值 = "", ""
    if 文件 is not None:
        类型 = "文件"
        目标 = Path(文件)
        if not 目标.is_absolute():
            目标 = 项目 / 目标
        目标 = 目标.resolve()
        try:
            目标.relative_to(项目)
        except ValueError as 错误:
            raise ValueError(f"变更文件必须位于项目目录内: {目标}") from 错误
        if not 目标.is_file():
            raise ValueError(f"变更文件不存在: {目标}")
        值 = 目标.relative_to(项目).as_posix()
        if 目标.name in {"项目声明.json", "项目.json"}:
            选中路径 = 全部路径
        elif 目标.suffix.lower() == ".json":
            选中路径 = [目标]
        else:
            raise ValueError("变更文件必须是项目声明或项目 JSON 小单元")
    elif 能力 is not None:
        类型, 值 = "能力", 能力
        if not isinstance(能力, str) or not 能力.strip():
            raise ValueError("变更能力不能为空")
        值 = 能力.strip()
        for 路径 in 全部路径:
            数据 = _读取(路径, {})
            引用能力, _ = _收集数据引用([数据] if isinstance(数据, dict) else [])
            if 值 in 引用能力:
                选中路径.append(路径)
        if not 选中路径:
            raise ValueError(f"项目未引用变更能力: {值}")
    else:
        类型, 值 = "组件", str(组件 or "").strip()
        if not 值:
            raise ValueError("变更组件不能为空")
        for 路径 in 全部路径:
            数据 = _读取(路径, {})
            组件表 = 数据.get("组件列表", []) if isinstance(数据, dict) else []
            if any(isinstance(项, dict) and str(项.get("组件id", "")) == 值 for 项 in 组件表):
                选中路径.append(路径)
        if not 选中路径:
            raise ValueError(f"项目未找到变更组件: {值}")
    数据表 = [_读取(路径, {}) for 路径 in 选中路径]
    数据表 = [数据 for 数据 in 数据表 if isinstance(数据, dict)]
    能力集合, 模块集合 = _收集数据引用(数据表)
    if 类型 == "能力":
        能力集合.add(值)
    页面根 = (项目 / "前端" / "页面").resolve()
    页面路径 = []
    for 路径 in 选中路径:
        try:
            路径.relative_to(页面根)
        except ValueError:
            continue
        页面路径.append(路径)
    return {
        "变更单元": {"类型": 类型, "值": 值},
        "受影响文件": [路径.relative_to(项目).as_posix() for 路径 in 选中路径],
        "受影响页面": [路径.name for 路径 in 页面路径],
        "契约": sorted(能力集合),
        "依赖": sorted(模块集合),
        "边界": {"项目根": str(项目), "仅项目内文件": True, "禁止测试中心和HTML全量": True},
    }


def _复制目录(源: Path, 目标: Path) -> None:
    # 编译输入必须闭合在源目录内；拒绝符号链接，避免 copytree 跟随链接
    # 把源目录外的文件带入独立制品。
    符号链接 = [路径 for 路径 in 源.rglob("*") if 路径.is_symlink()]
    if 符号链接:
        相对 = 符号链接[0].relative_to(源).as_posix()
        raise ValueError(f"编译输入包含不允许的符号链接: {相对}")
    if 目标.exists():
        raise ValueError(f"编译目标重复，拒绝递归删除子目录: {目标}")
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


def _生成启动器(项目id: str, 包前缀: str = "") -> str:
    """生成唯一独立启动器模板；包前缀只改变装配根，不复制启动逻辑。"""
    项目id字面量 = json.dumps(校验项目id(项目id), ensure_ascii=False)
    包前缀字面量 = json.dumps(包前缀, ensure_ascii=False)
    导入前缀 = f"{包前缀}." if 包前缀 else ""
    return f'''"""独立 HTML 启动器；不依赖开发网关。"""
from __future__ import annotations
import os, sys
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import argparse, json, threading, urllib.error, urllib.request, webbrowser
from urllib.parse import quote, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
项目id = {项目id字面量}
包前缀 = {包前缀字面量}
根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path: sys.path.insert(0, str(根))
源码根 = 根 / 包前缀 if 包前缀 else 根
from {导入前缀}后端核心.后端核心 import 后端核心
from {导入前缀}运行核心.统一网关.网关核心 import 网关核心
from {导入前缀}运行核心.统一网关.本地网关 import 本地网关服务器
def 主函数(端口=45080, 自动打开=True):
    from {导入前缀}公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    后端 = 后端核心(系统根目录=源码根); 启动 = 后端.启动()
    if not 启动.成功: raise RuntimeError(f"独立运行时装配失败: {{启动.错误说明}}")
    网关 = 本地网关服务器(网关核心实例=网关核心(后端), 端口=0); 成功, 说明 = 网关.启动()
    if not 成功: 后端.优雅关闭(); raise RuntimeError(说明)
    页面目录 = 根 / "前端" / "编译页面"
    路由数据 = json.loads((页面目录 / "路由表.json").read_text(encoding="utf-8"))
    if not isinstance(路由数据, dict) or not 路由数据: raise RuntimeError("页面路由表为空或不合法")
    页面表 = {{}}
    for 路由, 文件名 in 路由数据.items():
        if not isinstance(路由, str) or not 路由.startswith("/") or not isinstance(文件名, str): raise RuntimeError("页面路由表条目不合法")
        页面文件 = (页面目录 / 文件名).resolve()
        try: 页面文件.relative_to(页面目录.resolve())
        except ValueError as 错误: raise RuntimeError("页面路由逃逸") from 错误
        if not 页面文件.is_file(): raise RuntimeError(f"页面路由制品不存在: {{文件名}}")
        页面表[路由] = 页面文件.read_bytes()
    网关地址 = f"http://127.0.0.1:{{网关.端口}}"
    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式, *参数): return
        def _CORS头(self):
            # 允许本地验证页/HTML 黑盒验证器跨域直连（file:// 来源为 null，
            # 本地 HTTP 服务来源为 http://127.0.0.1:*）。黑盒验证必须走浏览器真实路径。
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        def do_OPTIONS(self):
            self.send_response(204); self._CORS头(); self.end_headers()
        def do_GET(self):
            路由 = unquote(self.path.split("?", 1)[0]); 页面 = 页面表.get(路由)
            if 页面 is None: self.send_error(404); return
            self.send_response(200); self._CORS头(); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(页面))); self.end_headers(); self.wfile.write(页面)
        def do_POST(self):
            # 浏览器/curl 会把中文路径编码（/网关/调用 → /%E7%BD%91...），
            # 必须 unquote 后再比较，否则收到编码路径直接 404。
            if unquote(self.path) != "/网关/调用": self.send_error(404); return
            try:
                长度 = int(self.headers.get("Content-Length", "-1"))
                if 长度 < 0 or 长度 > 1024 * 1024: raise ValueError("请求体超过上限")
                if "application/json" not in self.headers.get("Content-Type", "").lower(): raise ValueError("请求正文必须使用 JSON")
                请求数据 = json.loads(self.rfile.read(长度).decode("utf-8"))
                if not isinstance(请求数据, dict): raise ValueError("请求必须是对象")
                请求正文 = json.dumps(请求数据, ensure_ascii=False).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as 错误:
                正文 = json.dumps({{"成功":False,"错误码":"参数不合法","错误说明":str(错误)}}, ensure_ascii=False).encode()
                self.send_response(400); self._CORS头(); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
            # urllib 不能直接发原始中文路径（UnicodeEncodeError），必须 quote 编码；
            # quote 输出的 %XX 是合法 ASCII，urllib 不会二次转义（实测 200 成功）。
            请求头 = {{"Content-Type":"application/json"}}
            凭证 = os.environ.get("系统库网关凭证", "")
            if 凭证: 请求头["Authorization"] = f"Bearer {{凭证}}"
            请求 = urllib.request.Request(网关地址 + quote("/网关/调用"), data=请求正文, headers=请求头)
            try:
                with urllib.request.urlopen(请求, timeout=10) as 响应: 状态码, 正文 = 响应.status, 响应.read()
            except urllib.error.HTTPError as 错误:
                try: 状态码, 正文 = 错误.code, 错误.read()
                finally: 错误.close()
            except (urllib.error.URLError, TimeoutError, OSError):
                状态码 = 502; 正文 = json.dumps({{"成功":False,"错误码":"网关断开","错误说明":"网关不可访问"}}, ensure_ascii=False).encode()
            self.send_response(状态码); self._CORS头(); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文)
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


def 编译项目(
    项目目录: Path, 输出目录: Path, *, 变更单元: dict[str, Any] | None = None,
) -> dict[str, Any]:
    项目目录 = 项目目录.resolve(); 输出目录 = 校验输出目录(项目目录, 输出目录)
    声明 = _读取(项目目录 / "项目声明.json") or _读取(项目目录 / "项目.json")
    if not isinstance(声明, dict) or not 声明.get("项目id"):
        raise ValueError("项目必须提供 项目声明.json 或 项目.json，且包含项目id")
    项目id = 校验项目id(声明["项目id"])
    if 变更单元 is None:
        # 仅保留给仓库内既有程序化调用；唯一对外 CLI 强制提供小单元。
        声明文件 = 项目目录 / ("项目声明.json" if (项目目录 / "项目声明.json").is_file() else "项目.json")
        影响 = 计算影响闭包(项目目录, 文件=声明文件)
        影响["变更单元"] = {"类型": "内部兼容", "值": 声明文件.name}
    else:
        if not isinstance(变更单元, dict) or len(变更单元) != 1:
            raise ValueError("本次变更必须且只能提供文件、能力、组件之一")
        类型, 值 = next(iter(变更单元.items()))
        if 类型 not in {"文件", "能力", "组件"}:
            raise ValueError("本次变更类型只能是文件、能力、组件")
        影响 = 计算影响闭包(项目目录, **{类型: 值})
    索引 = 构建索引(系统根)
    支持库表 = dict(索引["支持库"]); 模块表 = dict(索引["模块库"])
    能力集合, 模块集合 = set(影响["契约"]), set(影响["依赖"])
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
    输出目录 = _准备输出目录(项目目录, 输出目录)
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
    受影响文件 = set(影响["受影响文件"])
    页面文件表 = [
        项目目录 / 相对 for 相对 in sorted(受影响文件)
        if 相对.startswith("前端/页面/") and 相对.endswith(".json")
    ]
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
        路由表[str(页面["路由"])] = 文件名
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
    _写入并编译Python(启动器目录 / "启动.py", _生成启动器(项目id))
    (启动器目录 / "启动网页.command").write_text(
        '#!/bin/sh\nset -eu\ncd "$(dirname "$0")/.." || exit 1\nexec env PYTHONDONTWRITEBYTECODE=1 python3 -B 运行入口/启动.py\n', encoding="utf-8"
    )
    (启动器目录 / "启动网页.bat").write_text(
        '@echo off\nset PYTHONDONTWRITEBYTECODE=1\ncd /d "%~dp0.."\npython -B 运行入口\\启动.py\n', encoding="utf-8"
    )
    (启动器目录 / "__init__.py").write_text('"""独立项目运行入口。"""\n', encoding="utf-8")
    (启动器目录 / "启动网页.command").chmod(0o755)
    来源 = _来源指纹(输出目录)
    影响闭包 = {
        "文件": list(影响["受影响文件"]), "页面": [str(页面["页面id"]) for 页面 in 页面表],
        "能力": sorted(能力集合), "模块": sorted(选中模块), "支持库": sorted(选中支持库),
        "依赖锁": 依赖锁, "边界": 影响["边界"],
    }
    清单 = {"制品类型": "独立项目", "编译器版本": 编译器版本, "项目id": 项目id,
           "变更单元": 影响["变更单元"], "影响闭包": 影响闭包,
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
        "项目id": 项目id,
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
        "项目id": 项目id, **来源,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (输出目录 / "制品完整性摘要.json").write_text(
        json.dumps(_制品文件摘要(输出目录), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    清单["制品摘要文件"] = "制品完整性摘要.json"
    清单["来源绑定文件"] = "制品来源.json"
    (输出目录 / "编译清单.json").write_text(json.dumps(清单, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 清单


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="唯一统一编译入口：只编译本次变更小单元")
    解析器.add_argument("项目目录", type=Path); 解析器.add_argument("--输出", type=Path, required=True)
    小单元 = 解析器.add_mutually_exclusive_group(required=True)
    小单元.add_argument("--文件", type=Path)
    小单元.add_argument("--能力")
    小单元.add_argument("--组件")
    参数 = 解析器.parse_args()
    变更单元 = {名称: 值 for 名称, 值 in (("文件", 参数.文件), ("能力", 参数.能力), ("组件", 参数.组件)) if 值 is not None}
    try: 结果 = 编译项目(参数.项目目录, 参数.输出, 变更单元=变更单元)
    except (ValueError, OSError) as 错误: print(f"编译阻断：{错误}"); raise SystemExit(1)
    print(json.dumps(结果, ensure_ascii=False, indent=2))
