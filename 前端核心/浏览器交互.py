"""真实浏览器交互提供者：安全生成页面，并只经本地 HTTP 网关调用。"""

from __future__ import annotations

import html
import json
from typing import Any


页面状态 = {
    "等待": "等待", "加载中": "加载中", "成功": "成功",
    "参数错误": "参数错误", "能力不存在": "能力不存在",
    "权限不足": "权限不足", "超时": "超时", "任务取消": "任务取消",
    "网关断开": "网关断开", "提供者不可用": "提供者不可用",
}


def _属性值(值: Any) -> str:
    return html.escape(str(值), quote=True)


def _安全脚本数据(值: Any) -> str:
    """生成可放入 script 文本节点的 JSON，阻断结束标签和脚本分隔符。"""
    return (json.dumps(值, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


class 浏览器交互提供者:
    """生成自包含交互页面；页面不持有后端对象或业务实现。"""

    宿主类型 = "浏览器交互"
    渲染方式 = "HTML+JS"

    def __init__(self, 网关地址: str = "http://127.0.0.1:8899",
                 流式网关地址: str | None = None, 请求超时毫秒: int = 30000) -> None:
        self.网关地址 = 网关地址.rstrip("/")
        self.流式网关地址 = (流式网关地址 or 网关地址).rstrip("/")
        self.请求超时毫秒 = max(100, int(请求超时毫秒))

    def 渲染(self, 请求: Any) -> dict[str, Any]:
        窗口 = 请求.窗口定义
        页面块: list[str] = []
        按钮配置: dict[str, dict[str, Any]] = {}
        for 页面 in 窗口.页面列表:
            页面块.append(
                f'<section class="页面" id="页面_{_属性值(页面.页面id)}" '
                f'data-路由="{_属性值(页面.路由)}">')
            页面块.append(f"<h2>{html.escape(str(页面.标题 or 页面.页面id))}</h2>")
            for 组件 in 页面.组件列表:
                组件id = str(组件.组件id)
                安全id = _属性值(组件id)
                当前值 = 请求.状态表.get(组件id, 组件.属性.get("默认值", ""))
                if 组件.类型 == "输入框":
                    参数名 = 组件.属性.get("参数名") or 组件id.removesuffix("输入")
                    页面块.append(
                        f'<input id="{安全id}" class="组件输入" '
                        f'data-参数名="{_属性值(参数名)}" value="{_属性值(当前值)}">')
                elif 组件.类型 == "按钮":
                    按钮配置[组件id] = {
                        "能力id": 组件.属性.get("能力id", ""),
                        "参数": 组件.属性.get("参数", {}),
                        "回调": 组件.属性.get("回调", "结果区"),
                        "流式": bool(组件.属性.get("流式", False)),
                    }
                    页面块.append(
                        f'<button id="{安全id}" class="组件按钮" type="button" '
                        f'data-调用按钮="1">{html.escape(str(组件.属性.get("文本", "调用")))}</button>')
                elif 组件.类型 == "状态区":
                    页面块.append(
                        f'<div id="{安全id}" class="状态区">{html.escape(str(当前值))}</div>')
                elif 组件.类型 == "进度条":
                    页面块.append(f'<progress id="{安全id}" value="0" max="100"></progress>')
                elif 组件.类型 == "链接":
                    页面块.append(
                        f'<a href="#" data-路由目标="{_属性值(组件.属性.get("路由", "/"))}">'
                        f'{html.escape(str(组件.属性.get("文本", "链接")))}</a>')
                else:
                    页面块.append(f'<div id="{安全id}">{html.escape(str(当前值))}</div>')
            页面块.append("</section>")

        配置 = {
            "网关地址": self.网关地址,
            "流式网关地址": self.流式网关地址,
            "项目id": 请求.状态表.get("项目id", "示例项目"),
            "用户id": 请求.状态表.get("用户id", "示例用户"),
            "请求超时毫秒": self.请求超时毫秒,
            "状态表": 请求.状态表,
            "按钮配置": 按钮配置,
        }
        脚本 = r"""
<script>
"use strict";
const 页面配置 = JSON.parse(document.getElementById("页面配置").textContent);
let 当前路由 = window.location.hash.slice(1) || "/";
let 状态表 = Object.assign({}, 页面配置.状态表);
let 活动请求 = null;
let 活动流请求id = "";

function 更新状态(键, 值) {
  状态表[键] = 值;
  const 元素 = document.getElementById(键);
  if (!元素) return;
  if (元素 instanceof HTMLInputElement) 元素.value = String(值 ?? "");
  else 元素.textContent = typeof 值 === "string" ? 值 : JSON.stringify(值);
}

function 切换路由(路由) {
  当前路由 = 路由;
  window.location.hash = 路由;
  document.querySelectorAll(".页面").forEach((页面) => {
    页面.hidden = 页面.dataset.路由 !== 当前路由;
  });
}

function 收集参数(默认参数) {
  const 参数 = Object.assign({}, 默认参数 || {});
  document.querySelectorAll(".组件输入").forEach((输入) => {
    参数[输入.dataset.参数名 || 输入.id] = 输入.value;
  });
  return 参数;
}

function 映射错误(数据) {
  const 错误码 = 数据.错误码 || "提供者不可用";
  const 状态映射 = {"参数不合法":"参数错误", "外部不可访问":"提供者不可用"};
  更新状态("页面状态", 状态映射[错误码] || 错误码);
  更新状态("错误区", `${错误码}: ${数据.错误说明 || "请求失败"}`);
}

async function 调用网关(按钮id) {
  const 按钮 = 页面配置.按钮配置[按钮id];
  if (!按钮) return;
  if (按钮.流式) return 调用流式网关(按钮id);
  更新状态("加载状态", "加载中");
  更新状态("错误区", "");
  活动请求 = new AbortController();
  let 已超时 = false;
  const 超时器 = setTimeout(() => { 已超时 = true; if (活动请求) 活动请求.abort(); }, 页面配置.请求超时毫秒);
  try {
    const 响应 = await fetch(页面配置.网关地址 + "/网关/调用", {
      method: "POST", headers: {"Content-Type":"application/json"},
      signal: 活动请求.signal,
      body: JSON.stringify({能力id:按钮.能力id,
        参数:收集参数(按钮.参数), 项目id:页面配置.项目id, 用户id:页面配置.用户id})
    });
    const 数据 = await 响应.json().catch(() => ({成功:false,错误码:`HTTP ${响应.status}`,错误说明:"网关响应格式错误"}));
    if (数据.成功) {
      更新状态("页面状态", "成功");
      更新状态(按钮.回调, 数据.值);
    } else 映射错误(数据);
  } catch (错误) {
    if (错误.name === "AbortError" && 已超时) 映射错误({错误码:"超时",错误说明:"网关请求超时"});
    else if (错误.name === "AbortError") 更新状态("页面状态", "任务取消");
    else { 更新状态("页面状态", "网关断开"); 更新状态("错误区", "网关断开"); }
  } finally { clearTimeout(超时器); 活动请求 = null; 更新状态("加载状态", "等待"); }
}

async function 调用流式网关(按钮id) {
  const 按钮 = 页面配置.按钮配置[按钮id];
  更新状态("加载状态", "加载中");
  更新状态("错误区", "");
  活动请求 = new AbortController();
  let 已超时 = false;
  const 超时器 = setTimeout(() => { 已超时 = true; if (活动请求) 活动请求.abort(); }, 页面配置.请求超时毫秒);
  try {
    const 响应 = await fetch(页面配置.流式网关地址 + "/网关/流式", {
      method:"POST", headers:{"Content-Type":"application/json"}, signal:活动请求.signal,
      body:JSON.stringify({能力id:按钮.能力id, 参数:收集参数(按钮.参数)})
    });
    if (!响应.ok) {
      const 数据 = await 响应.json().catch(() => ({错误码:`HTTP ${响应.status}`,错误说明:"流式请求被拒绝"}));
      映射错误(数据); return;
    }
    if (!响应.body) throw new Error("流式响应体缺失");
    const 读取器 = 响应.body.getReader();
    const 解码器 = new TextDecoder();
    let 缓冲 = "";
    while (true) {
      const {done, value} = await 读取器.read();
      if (done) break;
      缓冲 += 解码器.decode(value, {stream:true});
      const 事件块 = 缓冲.split("\n\n");
      缓冲 = 事件块.pop() || "";
      for (const 块 of 事件块) {
        const 数据行 = 块.split("\n").find((行) => 行.startsWith("data: "));
        if (!数据行) continue;
        const 事件 = JSON.parse(数据行.slice(6));
        活动流请求id = 事件.请求id || 活动流请求id;
        if (事件.事件类型 === "中间事件") 更新状态(按钮.回调, 事件.数据);
        else if (事件.事件类型 === "完成事件") 更新状态("页面状态", "成功");
        else if (事件.事件类型 === "取消事件") 更新状态("页面状态", "任务取消");
        else if (事件.事件类型 === "超时事件") 映射错误(事件.数据 || {错误码:"超时"});
        else if (事件.事件类型 === "失败事件") 映射错误(事件.数据 || {});
      }
    }
  } catch (错误) {
    if (错误.name === "AbortError" && 已超时) 映射错误({错误码:"超时",错误说明:"流式请求超时"});
    else if (错误.name === "AbortError") 更新状态("页面状态", "任务取消");
    else { 更新状态("页面状态", "网关断开"); 更新状态("错误区", "流式网关断开"); }
  } finally { clearTimeout(超时器); 活动请求 = null; 活动流请求id = ""; 更新状态("加载状态", "等待"); }
}

function 取消任务() {
  if (活动流请求id) {
    fetch(页面配置.流式网关地址 + "/网关/流式/取消", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({请求id:活动流请求id}), keepalive:true
    }).catch(() => {});
  }
  if (活动请求) 活动请求.abort();
}
function 重试() { 更新状态("页面状态", "等待"); 更新状态("错误区", ""); }
document.querySelectorAll("[data-调用按钮]").forEach((按钮) =>
  按钮.addEventListener("click", () => 调用网关(按钮.id)));
document.querySelectorAll("[data-路由目标]").forEach((链接) =>
  链接.addEventListener("click", (事件) => {事件.preventDefault();切换路由(链接.dataset.路由目标);}));
window.addEventListener("beforeunload", 取消任务);
切换路由(当前路由);
</script>
"""
        html文本 = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(窗口.标题))}</title>
<style>
body {{ font-family: system-ui,sans-serif; max-width:640px; margin:2rem auto; padding:0 1rem; }}
.状态区 {{ margin:.5rem 0; padding:.6rem; background:#f4f4f6; border-radius:6px; min-height:1.2em; }}
.组件按钮 {{ padding:.5rem 1.2rem; margin:.3rem 0; }}
.组件输入 {{ padding:.4rem; width:90%; margin:.3rem 0; }}
#错误区 {{ color:#b00020; background:#fdecec; }}
</style></head><body>
<h1>{html.escape(str(窗口.标题))}</h1>
{''.join(页面块)}
<script type="application/json" id="页面配置">{_安全脚本数据(配置)}</script>
{脚本}
</body></html>"""
        return {"成功": True, "宿主": self.宿主类型,
                "渲染方式": self.渲染方式, "html": html文本}
