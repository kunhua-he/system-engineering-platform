"""轻代码前端 IDE：易语言式工程树、组件箱、窗体设计器、属性和事件面板。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

# 项目根入 sys.path 必须在任何项目内导入之前（直接执行时项目根不在 path）。
根目录 = Path(__file__).resolve().parents[2]
默认文件 = 根目录 / "工程缓存" / "轻代码前端编辑器" / "页面.json"
内部工程请求路径 = "/内部/工程请求"
if str(根目录) not in sys.path:
    sys.path.insert(0, str(根目录))

from 公共契约.运行时.有界HTTP import 有界线程HTTP服务器

from 开发工具.轻代码前端编辑器.页面模型 import 校验页面

页面 = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>轻代码前端 IDE</title>
<style>
*{box-sizing:border-box}body{margin:0;height:100vh;overflow:hidden;font:13px system-ui;color:#1f2937;background:#edf0f4;display:grid;grid-template-rows:30px 40px 1fr 24px}.菜单,.工具{display:flex;align-items:center;border-bottom:1px solid #cbd2dc;background:#f7f8fa}.菜单 span{padding:6px 14px;cursor:pointer}.菜单 span:hover{background:#dbeafe}.工具{gap:5px;padding:0 8px}.工具 button,.工具 select{height:28px;min-width:30px;border:1px solid #b9c2cf;background:#fff;border-radius:3px;cursor:pointer}.工具 select{padding:0 6px}.工具 button:hover{background:#e0ecff}.项目名{font-weight:700;margin-right:12px}.状态{margin-left:auto;color:#64748b}.主体{min-height:0;display:grid;grid-template-columns:210px 1fr 270px;grid-template-rows:1fr 180px}.面板{min-height:0;overflow:auto;background:#fff;border-right:1px solid #cbd2dc}.面板.右{border-right:0;border-left:1px solid #cbd2dc}.标题{height:28px;padding:7px 10px;font-weight:700;color:#334155;background:#e8ecf2;border-bottom:1px solid #cbd2dc}.树{padding:7px 10px;line-height:25px}.树 div{cursor:pointer;padding-left:8px}.树 div:hover{background:#e6f0ff}.工具箱{padding:8px;display:grid;grid-template-columns:1fr 1fr;gap:6px}.组件{padding:10px 5px;text-align:center;background:#f8fafc;border:1px solid #cbd5e1;border-radius:3px;cursor:grab}.组件:hover{border-color:#2563eb;background:#eff6ff}.设计区{min-width:0;min-height:0;overflow:auto;background:#dfe4eb;padding:18px}.窗体{position:relative;min-width:520px;min-height:410px;max-width:900px;margin:auto;background:#fff;border:1px solid #8290a5;box-shadow:0 3px 12px #9aa4b233}.窗体头{height:34px;padding:8px 12px;background:#27436b;color:#fff;font-weight:700}.网格{position:absolute;inset:34px 0 0;background-image:radial-gradient(#b7c1cf 1px,transparent 1px);background-size:16px 16px}.控件{position:absolute;min-width:70px;min-height:28px;padding:6px 9px;border:1px solid #8290a5;background:#fff;cursor:move;user-select:none;overflow:hidden}.控件.容器{background:#f8fbff;border:1px dashed #5b7aa5;padding:6px}.控件.选中{outline:2px solid #2563eb;z-index:2}.控件 [contenteditable]{cursor:text;outline:0}.控件 input,.控件 textarea{width:100%;height:100%;border:0;padding:0;background:transparent;font:inherit;outline:0}.属性{padding:9px}.属性行{margin:9px 0}.属性行 label{display:block;font-size:12px;color:#64748b;margin-bottom:3px}.属性行 input,.属性行 select,.属性行 textarea{width:100%;padding:5px;border:1px solid #cbd5e1;border-radius:2px;background:#fff}.属性 button{padding:6px 10px;border:1px solid #b9c2cf;background:#fff;border-radius:3px;cursor:pointer}.高级{margin-top:10px;border-top:1px solid #e2e8f0;padding-top:8px}.高级 summary{cursor:pointer;color:#64748b}.底部{grid-column:1/4;border-top:1px solid #aeb8c6;background:#fff;min-height:0}.页签{height:30px;display:flex;border-bottom:1px solid #cbd2dc;background:#e8ecf2}.页签 span{padding:7px 14px;cursor:pointer}.页签 .选中{background:#fff;border-top:2px solid #2563eb;padding-top:5px}.输出{margin:0;padding:10px;height:145px;overflow:auto;background:#101827;color:#d1fae5;font:12px ui-monospace}.事件表{padding:9px}.事件行{display:grid;grid-template-columns:90px 1fr;gap:8px;margin:6px 0}.事件行 input{padding:5px;border:1px solid #cbd5e1}.底栏{display:flex;align-items:center;padding:0 10px;color:#64748b;background:#e8ecf2;border-top:1px solid #cbd2dc}
</style><style>
.视图按钮{margin-left:8px}.代码区{min-width:0;min-height:0;overflow:auto;background:#fff;padding:18px 24px;color:#1f2937}.代码标题{font-size:16px;font-weight:700;margin-bottom:10px}.代码说明{color:#64748b;margin-bottom:14px}.签名表,.变量表{border-collapse:collapse;margin:8px 0 16px;min-width:520px}.签名表 th,.签名表 td,.变量表 th,.变量表 td{border:1px solid #b8c2cf;padding:4px 8px;text-align:left}.签名表 th,.变量表 th{background:#e8ecf2;font-weight:600}.代码行{display:grid;grid-template-columns:42px 1fr;line-height:23px;font:13px ui-monospace,SFMono-Regular,Menlo,monospace}.代码行号{text-align:right;color:#64748b;padding-right:12px;border-right:1px solid #e2e8f0;margin-right:12px;user-select:none}.代码关键字{color:#b91c1c}.代码命令{color:#1d4ed8}.代码字符串{color:#047857}.代码注释{color:#15803d}.代码对象{color:#7c3aed;cursor:pointer;text-decoration:underline}.代码空{height:8px}.树 .可点击{cursor:pointer}.树 .可点击:hover{color:#1d4ed8;text-decoration:underline}.模块区{min-width:0;min-height:0;overflow:auto;background:#fff;padding:20px}.模块卡{border:1px solid #b8c2cf;background:#f8fafc;padding:14px;max-width:760px}.模块卡 h3{margin:0 0 8px}.模块命令{display:grid;grid-template-columns:220px 1fr;gap:8px;border-top:1px solid #dbe2ea;padding:8px 0}.隐藏{display:none!important}
</style>
<div class="菜单"><button class="菜单项" title="文件菜单" onclick="菜单打开('文件',this)">文件</button><button class="菜单项" title="编辑菜单" onclick="菜单打开('编辑',this)">编辑</button><button class="菜单项" title="视图菜单" onclick="菜单打开('视图',this)">视图</button><button class="菜单项" title="项目菜单" onclick="菜单打开('项目',this)">项目</button><button class="菜单项" title="运行菜单" onclick="菜单打开('运行',this)">运行</button><button class="菜单项" title="工具菜单" onclick="菜单打开('工具',this)">工具</button><button class="菜单项" title="帮助菜单" onclick="菜单打开('帮助',this)">帮助</button><div id="菜单弹层" class="隐藏"></div></div>
<div class="工具"><span class="项目名">轻代码前端 IDE</span><select id="项目类型" title="项目类型"><option value="软件项目">软件项目</option><option value="网页项目">网页项目</option></select><button title="新建窗体" onclick="新建()">新建</button><button title="代码视图" class="视图按钮" onclick="切换视图('代码')">代码</button><button title="窗体视图" onclick="切换视图('窗体')">窗体</button><button title="模块视图" onclick="切换视图('模块')">模块</button><button title="撤销" onclick="撤销()">↶</button><button title="重做" onclick="重做()">↷</button><button title="编译运行" onclick="编译运行()">▶ F5</button><button title="预览" onclick="预览()">预览</button><button title="导出 JSON" onclick="导出()">JSON</button><span id="状态" class="状态">自动保存已开启</span></div>
<main class="主体"><aside class="面板"><div class="标题">工程</div><div class="树"><div>▾ 当前项目</div><div>　▾ 程序集</div><div class="可点击" onclick="切换视图('代码')">　　 程序集1</div><div>　　　 ├ 启动子程序</div><div>　　　 └ 窗口事件</div><div>　▾ 窗体</div><div id="树页面" class="可点击" onclick="切换视图('窗体')">　　 主页</div><div>　▾ 支持库</div><div class="可点击" onclick="切换视图('模块')">　　核心前端</div><div>　▾ 模块</div><div class="可点击" onclick="切换视图('模块')">　　流程</div><div>　▾ 资源</div><div>　　页面资源</div></div><div class="标题">组件箱（组件控件支持库）</div><div id="组件箱" class="工具箱"></div></aside>
<section id="设计区" class="设计区"><div id="窗体" class="窗体"><div id="窗体头" class="窗体头">新页面</div><div id="网格" class="网格"></div></div></section><section id="代码区" class="代码区 隐藏"></section><section id="模块区" class="模块区 隐藏"></section>
<aside class="面板 右"><div class="标题">属性</div><div id="属性" class="属性"><div style="color:#94a3b8">选择窗体或组件</div></div><div class="标题">事件</div><div id="事件" class="事件表"><div style="color:#94a3b8">选择组件后绑定事件</div></div></aside>
<section class="底部"><div class="页签"><span class="选中" onclick="页签(this,'输出')">输出</span><span onclick="页签(this,'事件日志')">事件日志</span><span onclick="页签(this,'页面JSON')">页面 JSON</span></div><pre id="输出" class="输出">欢迎使用轻代码前端 IDE。拖动左侧组件到窗体，按 F5 编译运行。</pre><pre id="页面JSON" class="输出" style="display:none"></pre><pre id="事件日志" class="输出" style="display:none">暂无事件</pre></section></main><div class="底栏">就绪　|　窗体设计　|　组件数: <span id="计数">0</span></div><section id="预览层" class="隐藏" style="position:fixed;inset:30px 0 24px;background:#f8fafc;z-index:20;overflow:auto;padding:28px"><div style="max-width:900px;margin:auto;background:#fff;border:1px solid #cbd5e1;box-shadow:0 8px 30px #0f172a22"><div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#27436b;color:#fff"><strong>运行预览</strong><button onclick="关闭预览()" style="padding:4px 10px">关闭</button></div><div id="预览内容" style="padding:20px"></div></div></section>
<script>
function 菜单打开(名称,锚点){let 层=document.querySelector('#菜单弹层');let 命令={文件:[['新建',()=>新建()],['导出 JSON',()=>导出()]],编辑:[['撤销',()=>撤销()],['重做',()=>重做()]],视图:[['窗体',()=>切换视图('窗体')],['代码',()=>切换视图('代码')],['模块',()=>切换视图('模块')]],项目:[['切换软件/网页',()=>{let 选择=document.querySelector('#项目类型');选择.value=选择.value==='软件项目'?'网页项目':'软件项目';选择.dispatchEvent(new Event('change'))}]],运行:[['编译运行',()=>编译运行()],['预览',()=>预览()]],工具:[['导出 JSON',()=>导出()]],帮助:[['查看帮助',()=>{输出.textContent='轻代码前端 IDE：页面 JSON 是唯一源，所有改动自动保存；F5 执行契约编译。';状态.textContent='帮助已显示'}]]}[名称]||[];层.innerHTML=命令.map(([文本])=>`<button type="button" data-命令="${文本}">${文本}</button>`).join('');层.style.cssText='position:absolute;z-index:30;top:30px;left:'+锚点.offsetLeft+'px;min-width:150px;background:#fff;border:1px solid #b9c2cf;box-shadow:0 4px 14px #0f172a22;padding:4px';层.classList.remove('隐藏');层.querySelectorAll('button').forEach((按钮,i)=>按钮.onclick=()=>{层.classList.add('隐藏');命令[i][1]()})}
let 数据={页面id:'主页',标题:'新页面',路由:'/',项目类型:'软件项目',组件列表:[]},选中=-1,历史=[],历史位置=-1,组件目录={},保存计时器=null,保存进行中=null,当前视图='窗体',脏=false;
const 网格=document.querySelector('#网格'),属性=document.querySelector('#属性'),事件=document.querySelector('#事件'),输出=document.querySelector('#输出'),状态=document.querySelector('#状态');
const 类型名={文本:'标签',输入框:'编辑框',按钮:'按钮',状态区:'标签框',列表:'列表框',容器:'容器'};
function 快照(){历史=历史.slice(0,历史位置+1);历史.push(JSON.stringify(数据));历史位置=历史.length-1}function 记录(){脏=true;快照();渲染();自动保存()}
function 自动保存(){clearTimeout(保存计时器);状态.textContent='正在保存…';保存计时器=setTimeout(保存,500)}
function 默认组件(类型){let n=数据.组件列表.length+1,定义=组件目录[类型]||{},默认值=Object.assign({},定义.默认属性||{}),对象id='对象_'+(crypto.randomUUID?.()||Math.random().toString(36).slice(2));默认值.左=默认值.左??(24+(n%4)*110);默认值.上=默认值.上??(28+Math.floor(n/4)*48);return {组件id:`组件${n}`,显示名称:`组件${n}`,对象id,类型,父组件id:null,父对象id:null,属性:默认值,事件:(定义.事件||[]).map(名称=>({事件id:'事件_'+(crypto.randomUUID?.()||Math.random().toString(36).slice(2)),名称,能力id:''}))}}
function 安全文本(值){return String(值??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function 代码行(编号,正文){return `<div class="代码行"><span class="代码行号">${编号}</span><span>${正文}</span></div>`}
function 生成代码(){
let 行=[],编号=1,组件=数据.组件列表||[],加=(正文)=>行.push(代码行(编号++,正文));
加('<span class="代码关键字">程序集</span> <span class="代码对象">程序集1</span>');
加('<span class="代码关键字">项目类型</span> '+安全文本(数据.项目类型||'软件项目'));
加('<span class="代码关键字">页面</span> <span class="代码对象">'+安全文本(数据.页面id)+'</span> <span class="代码字符串">"'+安全文本(数据.标题)+'"</span>');
行.push('<div class="代码空"></div>');
加('<span class="代码关键字">启动子程序</span> <span class="代码命令">()</span> <span class="代码关键字">返回</span> <span class="代码命令">()</span>');
加('<span class="代码注释">\' F5 从这里开始验证页面和能力引用</span>');
加('<span class="代码命令">载入</span> ('+安全文本(数据.页面id)+')');
行.push('<div class="代码空"></div>');
加('<span class="代码关键字">窗口事件</span> <span class="代码对象">'+安全文本(数据.标题)+'</span>');
组件.forEach((项,i)=>{let a=项.属性||{},文本=安全文本(a.文本||项.组件id);加('<span class="代码对象" onclick="定位对象('+i+')">'+安全文本(项.对象id||项.组件id)+'</span> <span class="代码关键字">'+安全文本(项.类型)+'</span> <span class="代码字符串">"'+文本+'"</span> <span class="代码注释">（'+安全文本(项.组件id||项.显示名称||'')+'）</span>');if(项.父对象id||项.父组件id)加('　<span class="代码注释">\' 父容器：</span><span class="代码对象">'+安全文本(项.父对象id||项.父组件id)+'</span>');(项.事件||[]).filter(x=>x.能力id).forEach(e=>加('　<span class="代码命令">'+安全文本(e.名称)+'</span> → <span class="代码对象">'+安全文本(e.能力id)+'</span>'))});
let 表='<table class="签名表"><tr><th>子程序名</th><th>返回值类型</th><th>公开</th><th>备注</th></tr><tr><td>启动子程序</td><td>逻辑型</td><td>是</td><td>F5 入口</td></tr><tr><td>窗口事件</td><td>逻辑型</td><td>是</td><td>页面组件事件映射</td></tr></table>';
let 变量='<table class="变量表"><tr><th>对象 id</th><th>类型</th><th>显示名称</th><th>父对象</th></tr>'+组件.map(function(x,i){return '<tr><td><a href="#" onclick="定位对象('+i+');return false">'+安全文本(x.对象id||x.组件id)+'</a></td><td>'+安全文本(x.类型)+'</td><td>'+安全文本(x.组件id||x.属性?.文本||'')+'</td><td>'+安全文本(x.父对象id||x.父组件id||'页面')+'</td></tr>'}).join('')+'</table>';
document.querySelector('#代码区').innerHTML='<div class="代码标题">程序集1 / '+安全文本(数据.标题)+'</div><div class="代码说明">这是页面 JSON 的可读代码投影。点击对象 id 可回到窗体定位真实组件。</div>'+表+'<div class="代码标题">变量与组件</div>'+变量+'<div class="代码标题">程序代码</div>'+行.join('')
}
function 生成模块(){let 能力=Object.values(组件目录);document.querySelector('#模块区').innerHTML=`<div class="模块卡"><h3>核心前端支持库</h3><div>包类型：原子组件描述　版本：按包声明　来源：支持库契约</div><p>这里显示的是公开命令映射，IDE 不展示实现源码。</p>${能力.map(x=>`<div class="模块命令"><strong>${安全文本(x.类型)}（${安全文本(x.别名||x.类型)}）</strong><span>创建组件、设置属性、绑定事件；参数和返回值来自能力契约。</span></div>`).join('')||'<div>正在读取支持库目录…</div>'}</div>`}
function 切换视图(视图){当前视图=视图;document.querySelector('#设计区').classList.toggle('隐藏',视图!=='窗体');document.querySelector('#代码区').classList.toggle('隐藏',视图!=='代码');document.querySelector('#模块区').classList.toggle('隐藏',视图!=='模块');if(视图==='代码')生成代码();if(视图==='模块')生成模块();状态.textContent=视图==='窗体'?'窗体设计':视图==='代码'?'代码视图':'模块/支持库视图'}
function 定位对象(i){选中=i;切换视图('窗体');渲染()}
function 渲染(){document.querySelector('#窗体头').textContent=数据.标题;网格.innerHTML='';let 画节点=(项,i,父)=>{let e=document.createElement('div'),a=项.属性||{};e.className='控件'+(项.类型==='容器'?' 容器':'')+(i===选中?' 选中':'');e.dataset.索引=i;e.style.left=(a.左||20)+'px';e.style.top=(a.上||20)+'px';e.style.width=(a.宽度||90)+'px';e.style.height=(a.高度||32)+'px';if(项.类型==='编辑框'){e.innerHTML=`<input value="${安全文本(a.文本)}" placeholder="${安全文本(a.占位文本)}" ${a.只读?'readonly':''}>`;e.querySelector('input').oninput=ev=>{a.文本=ev.target.value;自动保存()}}else if(项.类型==='容器'){e.innerHTML='<span style="color:#5b7aa5;font-size:11px">容器</span>'}else{let 文本=document.createElement('span');文本.textContent=a.文本||项.组件id;文本.contentEditable='true';文本.onfocus=()=>{e.dataset.编辑中='1'};文本.onblur=()=>{a.文本=文本.textContent;e.dataset.编辑中='';记录()};e.append(文本)}e.onclick=ev=>{ev.stopPropagation();选中=i;渲染()};e.ondblclick=ev=>{ev.stopPropagation();let 可编辑=e.querySelector('[contenteditable],input');可编辑?.focus();可编辑?.select?.()};e.onmousedown=ev=>{if(e.dataset.编辑中==='1'||ev.target.matches('input,[contenteditable]'))return;拖动(ev,i)};父.append(e);数据.组件列表.forEach((子,j)=>{if(子.父对象id===项.对象id||(!子.父对象id&&子.父组件id===项.组件id))画节点(子,j,e)})};数据.组件列表.filter(x=>!x.父对象id&&!x.父组件id).forEach((项,i)=>画节点(项,i,网格));document.querySelector('#计数').textContent=数据.组件列表.length;属性面板();事件面板();document.querySelector('#页面JSON').textContent=JSON.stringify(数据,null,2);document.querySelector('#项目类型').value=数据.项目类型||'软件项目';if(当前视图==='代码')生成代码();if(当前视图==='模块')生成模块()}
function 拖动(ev,i){let 项=数据.组件列表[i],sx=ev.clientX,sy=ev.clientY,ox=项.属性.左||20,oy=项.属性.上||20,moved=false;function 移动(e){if(Math.abs(e.clientX-sx)+Math.abs(e.clientY-sy)>3)moved=true;项.属性.左=Math.max(0,ox+e.clientX-sx);项.属性.上=Math.max(0,oy+e.clientY-sy);渲染()}function 松开(){if(moved)记录();window.removeEventListener('mousemove',移动);window.removeEventListener('mouseup',松开)}window.addEventListener('mousemove',移动);window.addEventListener('mouseup',松开)}
function 属性面板(){if(选中<0){属性.innerHTML='<div style="color:#94a3b8">选择窗体或组件</div>';return}let x=数据.组件列表[选中],a=x.属性||{},字段=[['对象id','对象 id'],['组件id','显示名称'],['文本','文本'],['占位文本','占位文本'],['左','左'],['上','上'],['宽度','宽度'],['高度','高度']];属性.innerHTML=字段.filter(([k])=>k==='对象id'||k==='组件id'||k==='文本'||k==='左'||k==='上'||k==='宽度'||k==='高度'||a[k]!==undefined).map(([k,n])=>`<div class="属性行"><label>${n}</label><input data-k="${k}" value="${安全文本(k==='对象id'?x.对象id:k==='组件id'?x.组件id:a[k]??'')}" ${k==='对象id'?'readonly':''}></div>`).join('')+`<details class="高级"><summary>高级属性与能力绑定</summary><div class="属性行"><label>能力 id</label><input data-k="能力id" value="${安全文本(a.能力id||'')}"></div><div class="属性行"><label>参数模板</label><textarea data-k="参数模板">${安全文本(a.参数模板||'{}')}</textarea></div><div class="属性行"><label>父容器</label><select data-k="父组件id"><option value="">页面</option>${数据.组件列表.filter(y=>y.类型==='容器'&&y.组件id!==x.组件id).map(y=>`<option value="${安全文本(y.组件id)}" ${x.父组件id===y.组件id?'selected':''}>${安全文本(y.组件id)}</option>`).join('')}</select></div></details><button onclick="删除()">删除组件</button>`;let 更新=(i)=>{let k=i.dataset.k;if(k==='对象id')return;else if(k==='组件id')x.组件id=i.value;else if(k==='父组件id'){x.父组件id=i.value||null;let p=数据.组件列表.find(y=>y.组件id===x.父组件id);x.父对象id=p?.对象id||null}else a[k]=['左','上','宽度','高度'].includes(k)?Number(i.value)||0:i.value;记录()};属性.querySelectorAll('input,textarea,select').forEach(i=>{i.oninput=()=>更新(i);i.onchange=()=>更新(i)})}
function 事件面板(){if(选中<0){事件.innerHTML='<div style="color:#94a3b8">选择组件后绑定事件</div>';return}let x=数据.组件列表[选中];事件.innerHTML=['点击','输入','改变','获得焦点'].map(名=>`<div class="事件行"><span>${名}</span><input placeholder="能力 id" value="${x.事件?.find(e=>e.名称===名)?.能力id||''}" onchange="绑定事件('${名}',this.value)"></div>`).join('')}
function 绑定事件(名,id){let x=数据.组件列表[选中];x.事件=x.事件||[];let e=x.事件.find(y=>y.名称===名);if(!e){e={名称:名,能力id:id};x.事件.push(e)}else e.能力id=id;记录()}
function 删除(){if(选中>=0){let id=数据.组件列表[选中].组件id;数据.组件列表=数据.组件列表.filter(x=>x.组件id!==id&&x.父组件id!==id);选中=-1;记录()}}function 新建(){let 工程id=数据.工程id,修订号=Number(数据.修订号||0);数据={工程id,修订号,页面id:'主页',标题:'新页面',路由:'/',项目类型:document.querySelector('#项目类型').value,组件列表:[]};选中=-1;记录();状态.textContent='新建页面'}function 撤销(){if(历史位置>0){历史位置--;数据=JSON.parse(历史[历史位置]);选中=-1;渲染()}}function 重做(){if(历史位置+1<历史.length){历史位置++;数据=JSON.parse(历史[历史位置]);选中=-1;渲染()}}
function 添加组件(类型,目标=null){let 项=默认组件(类型);if(目标){let 容器=数据.组件列表[Number(目标.dataset.索引)];if(容器?.类型==='容器'){项.父组件id=容器.组件id;项.父对象id=容器.对象id}}数据.组件列表.push(项);选中=数据.组件列表.length-1;记录()}
function 加载组件目录(目录){let 箱=document.querySelector('#组件箱');箱.innerHTML='';(目录.组件类型||[]).forEach(项=>{组件目录[项.类型]=项;let e=document.createElement('div');e.className='组件';e.draggable=true;e.dataset.类型=项.类型;e.textContent=项.别名||项.类型;e.title='点击添加，或拖动到窗体';e.onclick=()=>添加组件(项.类型);e.ondragstart=x=>x.dataTransfer.setData('类型',项.类型);箱.append(e)})}网格.ondragover=e=>e.preventDefault();网格.ondrop=e=>{e.preventDefault();添加组件(e.dataTransfer.getData('类型'),e.target.closest('.控件'))};网格.onclick=()=>{选中=-1;渲染();页面属性()};document.querySelector('#项目类型').onchange=()=>{数据.项目类型=document.querySelector('#项目类型').value;记录()};
async function 保存(){if(!脏)return true;if(保存进行中)return 保存进行中;保存进行中=(async()=>{try{let 基准修订号=Number(数据.修订号||0),r=await fetch('/内部/工程请求',{method:'POST',headers:{'Content-Type':'application/json','X-Internal-Call':'1'},body:JSON.stringify({操作:'提交变更',工程id:数据.工程id,基准修订号,来源:当前视图==='代码'?'代码视图':当前视图==='模块'?'模块视图':'窗体设计器',请求id:'请求_'+(crypto.randomUUID?.()||Math.random().toString(36).slice(2)),操作列表:[{操作:'替换页面模型',页面:数据}]})}),x=await r.json();if(x.成功){if(x.页面)数据=x.页面;数据.工程id=x.工程id||数据.工程id;数据.修订号=x.新修订号;脏=false;状态.textContent='已自动保存（修订 '+x.新修订号+'）';输出.textContent='页面模型已通过统一工程网关保存。';return true}else if(x.错误码==='编辑冲突'){状态.textContent='编辑冲突：未覆盖他人修改';输出.textContent=x.错误说明;return false}else{状态.textContent='保存失败';输出.textContent=x.错误说明||'保存失败';return false}}catch(e){状态.textContent='保存失败';输出.textContent=String(e);return false}})();try{return await 保存进行中}finally{保存进行中=null}}
function 导出(){let 文本=JSON.stringify(数据,null,2);document.querySelector('#页面JSON').textContent=文本;navigator.clipboard?.writeText(文本).catch(()=>{});状态.textContent='JSON 已复制'}
function 预览节点(项){let a=项.属性||{},类='控件';if(项.类型==='容器'){return `<section class="${类} 容器"><strong>${安全文本(a.文本||项.组件id)}</strong>${数据.组件列表.filter(x=>x.父组件id===项.组件id).map(预览节点).join('')}</section>`}if(项.类型==='输入框'){return `<label class="${类}">${安全文本(a.文本||项.组件id)}<input value="${安全文本(a.默认值||'')}" placeholder="${安全文本(a.占位文本||'')}"></label>`}if(项.类型==='按钮'){return `<button class="${类}" type="button">${安全文本(a.文本||项.组件id)}</button>`}return `<div class="${类}">${安全文本(a.文本||项.组件id)}</div>`}
async function 预览(){let 已保存=await 保存();if(!已保存)return;let 层=document.querySelector('#预览层'),内容=document.querySelector('#预览内容');内容.innerHTML=`<h1>${安全文本(数据.标题)}</h1>`+数据.组件列表.filter(x=>!x.父组件id).map(预览节点).join('');层.classList.remove('隐藏');状态.textContent='预览已打开'}function 关闭预览(){document.querySelector('#预览层').classList.add('隐藏');状态.textContent='窗体设计'}
async function 编译运行(){let 已保存=await 保存();if(!已保存)return;状态.textContent='正在编译…';try{let r=await fetch('/内部/工程请求',{method:'POST',headers:{'Content-Type':'application/json','X-Internal-Call':'1'},body:JSON.stringify({操作:'编译工程',工程id:数据.工程id})}),x=await r.json();if(x.成功){状态.textContent='F5：编译成功';输出.textContent=`编译成功：${x.输出文件}\n能力依赖：${(x.能力依赖||[]).join('、')||'无'}`}else{状态.textContent='F5：编译阻断';输出.textContent=`编译阻断：${x.错误说明||'页面契约不合法'}`}}catch(e){状态.textContent='F5：编译失败';输出.textContent=String(e)}}function 页签(e,id){document.querySelectorAll('.页签 span').forEach(x=>x.classList.remove('选中'));e.classList.add('选中');document.querySelectorAll('.输出').forEach(x=>x.style.display=x.id===id?'block':'none')}
function 页面属性(){if(选中>=0)return;属性.innerHTML=`<div class="属性行"><label>页面标题</label><input data-k="标题" value="${安全文本(数据.标题)}"></div><div class="属性行"><label>页面路由</label><input data-k="路由" value="${安全文本(数据.路由)}"></div><div style="color:#94a3b8;font-size:12px;margin-top:12px">改动会自动保存，无需点击保存。</div>`;属性.querySelectorAll('input').forEach(i=>i.onchange=()=>{数据[i.dataset.k]=i.value;记录()})}
fetch('/组件目录').then(r=>r.json()).then(加载组件目录).catch(()=>加载组件目录({组件类型:[{类型:'按钮',别名:'按钮',默认属性:{文本:'按钮'},事件:['点击']},{类型:'编辑框',别名:'编辑框',默认属性:{文本:''},事件:['输入']},{类型:'标签',别名:'标签',默认属性:{文本:'标签'},事件:[]}] }));快照();渲染();页面属性();
</script>'''


def 主函数(端口: int = 45082, 文件: Path = 默认文件) -> int:
    from 公共契约.运行时.端口策略 import 校验应用监听端口
    校验应用监听端口(端口)
    文件.parent.mkdir(parents=True, exist_ok=True)
    编辑锁 = threading.Lock()
    工程目录 = 文件.parent
    后端模型文件 = 工程目录 / "后端" / "工程模型.json"

    def 规范页面(数据: dict[str, Any]) -> dict[str, Any]:
        """规范唯一页面模型，并补齐工程修订和不可变对象身份。"""
        if not 数据.get("工程id"):
            数据["工程id"] = "工程_" + uuid.uuid4().hex[:16]
        数据.setdefault("修订号", 0)
        数据.setdefault("页面id", "主页")
        数据.setdefault("标题", "新页面")
        数据.setdefault("路由", "/")
        数据.setdefault("项目类型", "软件项目")
        数据.setdefault("组件列表", [])
        数据.setdefault("后端模型", {"模块引用": [], "程序集": [], "服务": []})
        别名映射: dict[str, str] = {}
        for 索引, 组件 in enumerate(数据["组件列表"], 1):
            组件.setdefault("组件id", f"组件{索引}")
            组件.setdefault("显示名称", 组件.get("组件id", f"组件{索引}"))
            组件.setdefault("对象id", "对象_" + uuid.uuid4().hex[:16])
            组件.setdefault("父组件id", None)
            组件.setdefault("父对象id", None)
            别名映射[str(组件["组件id"])] = str(组件["对象id"])
        for 组件 in 数据["组件列表"]:
            if not 组件.get("父对象id") and 组件.get("父组件id"):
                组件["父对象id"] = 别名映射.get(str(组件["父组件id"]))
        return 校验页面(数据)

    def 读取后端模型() -> dict[str, Any]:
        """读取当前后端工程投影；不存在时返回空模型。"""
        路径 = 后端模型文件
        if not 路径.is_file():
            return {"模块引用": [], "程序集": [], "服务": []}
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"模块引用": [], "程序集": [], "服务": []}
        return 数据 if isinstance(数据, dict) else {"模块引用": [], "程序集": [], "服务": []}

    def 原子写(路径: Path, 数据: dict[str, Any]) -> None:
        临时 = 路径.parent / f".{路径.name}.{uuid.uuid4().hex}.tmp"
        临时.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with 临时.open("rb") as 句柄:
            os.fsync(句柄.fileno())
        os.replace(临时, 路径)

    def 写工程模型(数据: dict[str, Any]) -> None:
        """页面与后端模型共享一次提交；后端文件是同一模型的物理投影。"""
        后端 = 数据.get("后端模型")
        if isinstance(后端, dict):
            后端模型文件.parent.mkdir(parents=True, exist_ok=True)
            原子写(后端模型文件, 后端)
        原子写(文件, 数据)

    def 写操作记录(记录: dict[str, Any]) -> None:
        日志 = 文件.parent / "编辑记录.jsonl"
        with 日志.open("a", encoding="utf-8") as 句柄:
            句柄.write(json.dumps(记录, ensure_ascii=False) + "\n")

    def 应用操作(页面数据: dict[str, Any], 操作列表: list[dict[str, Any]]) -> dict[str, Any]:
        """应用 Agent/命令行的结构化工程操作；失败即整体拒绝。"""
        候选 = json.loads(json.dumps(页面数据, ensure_ascii=False))
        候选.setdefault("后端模型", {"模块引用": [], "程序集": [], "服务": []})
        表 = {str(x.get("对象id")): x for x in 候选.get("组件列表", [])}
        for 操作 in 操作列表:
            类型 = str(操作.get("操作", ""))
            目标id = str(操作.get("目标对象id", ""))
            目标 = 表.get(目标id)
            if 类型 == "替换页面模型":
                新页面 = 操作.get("页面")
                if not isinstance(新页面, dict):
                    raise ValueError("替换页面模型缺少页面对象")
                候选 = 规范页面(json.loads(json.dumps(新页面, ensure_ascii=False)))
                候选.setdefault("后端模型", 页面数据.get("后端模型", {"模块引用": [], "程序集": [], "服务": []}))
                表 = {str(x.get("对象id")): x for x in 候选.get("组件列表", [])}
                continue
            if 类型 == "新增对象":
                新对象 = dict(操作.get("对象") or {})
                if not 新对象.get("对象id") or 新对象["对象id"] in 表:
                    raise ValueError("新增对象缺少唯一对象id或对象id重复")
                新对象.setdefault("组件id", 新对象["对象id"])
                新对象.setdefault("显示名称", 新对象["组件id"])
                新对象.setdefault("父对象id", None)
                新对象.setdefault("父组件id", None)
                新对象.setdefault("属性", {})
                新对象.setdefault("事件", [])
                候选.setdefault("组件列表", []).append(新对象)
                表[str(新对象["对象id"])] = 新对象
                continue
            if 类型 == "新增后端模块":
                模块 = dict(操作.get("模块") or {})
                模块id = str(模块.get("模块id", "")).strip()
                if not 模块id:
                    raise ValueError("后端模块缺少模块id")
                模块表 = 候选["后端模型"].setdefault("模块引用", [])
                if any(str(x.get("模块id", "")) == 模块id for x in 模块表 if isinstance(x, dict)):
                    raise ValueError(f"后端模块已存在: {模块id}")
                模块表.append(模块)
                continue
            if 类型 == "新增后端程序集":
                程序集 = dict(操作.get("程序集") or {})
                程序集id = str(程序集.get("程序集id", "")).strip()
                if not 程序集id:
                    raise ValueError("后端程序集缺少程序集id")
                程序集表 = 候选["后端模型"].setdefault("程序集", [])
                if any(str(x.get("程序集id", "")) == 程序集id for x in 程序集表 if isinstance(x, dict)):
                    raise ValueError(f"后端程序集已存在: {程序集id}")
                程序集表.append(程序集)
                continue
            if not 目标:
                raise ValueError(f"目标对象不存在: {目标id}")
            if 类型 == "设置属性":
                路径 = list(操作.get("路径") or [])
                if len(路径) != 2 or 路径[0] != "属性":
                    raise ValueError("设置属性只允许使用 属性/<字段> 路径")
                目标.setdefault("属性", {})[str(路径[1])] = 操作.get("新值")
            elif 类型 == "重命名对象":
                新名称 = str(操作.get("新名称", "")).strip()
                if not 新名称:
                    raise ValueError("新名称不能为空")
                目标["组件id"] = 新名称
                目标["显示名称"] = 新名称
            elif 类型 == "移动对象":
                属性 = 目标.setdefault("属性", {})
                属性["左"] = int(操作.get("左", 属性.get("左", 0)))
                属性["上"] = int(操作.get("上", 属性.get("上", 0)))
            elif 类型 == "调整尺寸":
                属性 = 目标.setdefault("属性", {})
                属性["宽度"] = int(操作.get("宽度", 属性.get("宽度", 0)))
                属性["高度"] = int(操作.get("高度", 属性.get("高度", 0)))
            elif 类型 == "建立父子关系":
                父id = 操作.get("父对象id")
                父 = 表.get(str(父id)) if 父id else None
                if 父id and (not 父 or 父.get("类型") != "容器"):
                    raise ValueError("父对象不存在或不是容器")
                if 父id == 目标id:
                    raise ValueError("对象不能成为自己的父对象")
                目标["父对象id"] = str(父id) if 父id else None
                目标["父组件id"] = 父.get("组件id") if 父 else None
            elif 类型 == "绑定事件":
                事件名称 = str(操作.get("事件名称", "")).strip()
                能力id = str(操作.get("能力id", "")).strip()
                if not 事件名称 or not 能力id:
                    raise ValueError("绑定事件必须提供事件名称和能力id")
                事件表 = 目标.setdefault("事件", [])
                已有 = next((x for x in 事件表 if x.get("名称") == 事件名称), None)
                if 已有:
                    已有["能力id"] = 能力id
                else:
                    事件表.append({"事件id": "事件_" + uuid.uuid4().hex[:16], "名称": 事件名称, "能力id": 能力id})
            elif 类型 == "删除对象":
                待删 = {目标id}
                改变 = True
                while 改变:
                    改变 = False
                    for 项 in 候选.get("组件列表", []):
                        if 项.get("父对象id") in 待删 and 项.get("对象id") not in 待删:
                            待删.add(str(项["对象id"])); 改变 = True
                候选["组件列表"] = [项 for 项 in 候选.get("组件列表", []) if 项.get("对象id") not in 待删]
                表 = {str(x.get("对象id")): x for x in 候选.get("组件列表", [])}
            else:
                raise ValueError(f"不支持的工程操作: {类型}")
        return 规范页面(候选)

    页面内容 = 页面
    if 文件.is_file():
        try:
            已保存 = 规范页面(json.loads(文件.read_text(encoding="utf-8")))
            已保存["后端模型"] = 读取后端模型()
            for 索引, 组件 in enumerate(已保存.get("组件列表", [])):
                属性 = 组件.setdefault("属性", {})
                组件.setdefault("父组件id", None)
                属性.setdefault("左", 24 + (索引 % 3) * 150)
                属性.setdefault("上", 28 + (索引 // 3) * 58)
                属性.setdefault("宽度", 110 if 组件.get("类型") != "输入框" else 220)
                属性.setdefault("高度", 32)
            页面内容 = 页面.replace(
                "let 数据={页面id:'主页',标题:'新页面',路由:'/',项目类型:'软件项目',组件列表:[]},",
                f"let 数据={json.dumps(已保存, ensure_ascii=False, separators=(',', ':'))},",
                1,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            页面内容 = 页面

    class 处理器(BaseHTTPRequestHandler):
        def log_message(self, 格式: str, *参数: Any) -> None:
            return

        def do_GET(self) -> None:
            路径 = unquote(urlsplit(self.path).path)
            if 路径 == "/组件目录":
                目录文件 = 根目录 / "支持库" / "前端" / "组件控件" / "组件目录" / "组件目录.json"
                try:
                    正文 = 目录文件.read_bytes()
                except OSError:
                    正文 = '{"组件类型":[]}'.encode("utf-8")
                类型 = "application/json; charset=utf-8"
            else:
                正文 = 页面内容.encode("utf-8") if 路径 == "/" else b""
                类型 = "text/html; charset=utf-8"
            self.send_response(200 if 正文 else 404)
            self.send_header("Content-Type", 类型)
            self.send_header("Content-Length", str(len(正文)))
            self.end_headers()
            self.wfile.write(正文)

        def do_POST(self) -> None:
            路径 = unquote(urlsplit(self.path).path)
            if 路径 != 内部工程请求路径:
                self.send_error(404)
                return
            if self.headers.get("X-Internal-Call", "") != "1":
                self.send_error(403)
                return
            try:
                # 编辑器接口只接受有界 Content-Length；拒绝 chunked/超长/短读，
                # 避免请求错位和慢体连接长期占用线程。
                if self.headers.get("Transfer-Encoding", "").strip():
                    raise ValueError("暂不支持分块传输")
                长度文本 = self.headers.get("Content-Length")
                if 长度文本 is None:
                    raise ValueError("缺少 Content-Length")
                长度 = int(长度文本)
                if not 0 <= 长度 <= 4 * 1024 * 1024:
                    raise ValueError("请求体超过 4194304 字节上限")
                self.connection.settimeout(10.0)
                原始字节 = self.rfile.read(长度)
                if len(原始字节) != 长度:
                    raise ValueError("请求正文长度不足")
                请求 = json.loads(原始字节.decode("utf-8"))
                if not isinstance(请求, dict):
                    raise ValueError("请求正文必须是 JSON 对象")
                if 路径 == 内部工程请求路径:
                    操作 = str(请求.get("操作", ""))
                    当前 = 规范页面(json.loads(文件.read_text(encoding="utf-8"))) if 文件.is_file() else 规范页面({"工程id": 请求.get("工程id", ""), "修订号": 0, "组件列表": []})
                    当前["后端模型"] = 读取后端模型()
                    if 操作 == "读取工程":
                        响应 = {"成功": True, "工程": 当前, "工程id": 当前.get("工程id", ""), "修订号": 当前.get("修订号", 0)}
                        正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8")
                        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
                    if 操作 == "预览变更":
                        try:
                            预览页面 = 应用操作(当前, list(请求.get("操作列表") or []))
                            响应 = {"成功": True, "工程id": 当前.get("工程id", ""), "基准修订号": 当前.get("修订号", 0), "预览页面": 预览页面}
                        except (ValueError, TypeError) as 错误:
                            响应 = {"成功": False, "错误码": "预览阻断", "错误说明": str(错误)}
                        正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8")
                        self.send_response(200 if 响应.get("成功") else 400); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
                    if 操作 not in {"编译工程", "提交变更"}:
                        响应 = {"成功": False, "错误码": "操作不支持", "错误说明": f"未知工程操作: {操作}"}
                        正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8"); self.send_response(400); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(正文))); self.end_headers(); self.wfile.write(正文); return
                if 操作 == "编译工程":
                    from 开发工具.轻代码前端编辑器.编译页面 import 编译
                    页面数据 = 当前
                    输出文件 = 文件.parent / "编译制品.json"
                    临时源 = 文件.parent / f".{文件.name}.{uuid.uuid4().hex}.compile.json"
                    临时源.write_text(json.dumps(页面数据, ensure_ascii=False), encoding="utf-8")
                    try:
                        制品 = 编译(临时源, 输出文件)
                    finally:
                        临时源.unlink(missing_ok=True)
                    响应 = {"成功": True, "输出文件": str(输出文件), "能力依赖": 制品.get("能力依赖", [])}
                else:
                    请求id = str(请求.get("请求id") or uuid.uuid4().hex)
                    来源 = str(请求.get("来源") or "工程编辑客户端")
                    基准修订号 = int(请求.get("基准修订号", 0))
                    with 编辑锁:
                        日志文件 = 文件.parent / "编辑记录.jsonl"
                        已有记录 = None
                        if 日志文件.is_file():
                            for 日志行 in 日志文件.read_text(encoding="utf-8").splitlines():
                                try:
                                    记录 = json.loads(日志行)
                                except json.JSONDecodeError:
                                    continue
                                if 记录.get("请求id") == 请求id and 记录.get("提交结果") == "成功":
                                    已有记录 = 记录
                                    break
                        if 已有记录:
                            响应 = {"成功": True, "幂等重放": True, "工程id": 已有记录.get("工程id", ""), "新修订号": int(已有记录.get("新修订号", 0)), "请求id": 请求id}
                            正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self.send_header("Content-Length", str(len(正文)))
                            self.end_headers()
                            self.wfile.write(正文)
                            return
                        当前 = 规范页面(json.loads(文件.read_text(encoding="utf-8"))) if 文件.is_file() else 规范页面({"工程id": 请求.get("工程id", ""), "修订号": 0, "组件列表": []})
                        当前修订号 = int(当前.get("修订号", 0))
                        if 基准修订号 != 当前修订号:
                            响应 = {"成功": False, "错误码": "编辑冲突", "错误说明": f"基准修订号 {基准修订号} 已过期，当前为 {当前修订号}", "当前修订号": 当前修订号, "当前页面": 当前}
                        else:
                            候选 = 应用操作(当前, list(请求.get("操作列表") or []))
                            候选["工程id"] = 当前.get("工程id") or str(请求.get("工程id") or 候选.get("工程id"))
                            新修订号 = 当前修订号 + 1
                            候选["修订号"] = 新修订号
                            写工程模型(候选)
                            写操作记录({"请求id": 请求id, "操作id": str(请求.get("操作id") or 请求id), "来源": 来源, "工程id": 候选.get("工程id", ""), "基准修订号": 当前修订号, "新修订号": 新修订号, "操作数量": len(请求.get("操作列表") or []), "提交结果": "成功", "时间": __import__("datetime").datetime.now().isoformat(timespec="seconds")})
                            响应 = {"成功": True, "工程id": 候选.get("工程id", ""), "新修订号": 新修订号, "请求id": 请求id, "页面": 候选}
                    正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8")
                    self.send_response(409 if not 响应.get("成功") else 200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(正文)))
                    self.end_headers()
                    self.wfile.write(正文)
                    return
            except (ValueError, OSError, UnicodeDecodeError) as 错误:
                响应 = {"成功": False, "错误码": "保存失败", "错误说明": str(错误)}
            正文 = json.dumps(响应, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if 响应.get("成功") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(正文)))
            self.end_headers()
            self.wfile.write(正文)

    try:
        # 指定端口失败必须阻断；只有调用方明确传入 0 才允许系统分配端口。
        服务 = 有界线程HTTP服务器(("127.0.0.1", 端口), 处理器)
    except OSError as 错误:
        raise RuntimeError(f"IDE 端口 {端口} 无法监听，未自动改绑随机端口: {错误}") from 错误
    threading.Thread(target=服务.serve_forever, daemon=True).start()
    地址 = f"http://127.0.0.1:{服务.server_port}"
    print(f"轻代码前端 IDE：{地址}；保存到：{文件}")
    webbrowser.open(地址)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        服务.shutdown()
        服务.server_close()
    return 0


if __name__ == "__main__":
    解析器 = argparse.ArgumentParser(description="启动易语言式轻代码前端 IDE")
    解析器.add_argument("--端口", type=int, default=45082)
    解析器.add_argument("--文件", type=Path, default=默认文件)
    参数 = 解析器.parse_args()
    raise SystemExit(主函数(参数.端口, 参数.文件))
