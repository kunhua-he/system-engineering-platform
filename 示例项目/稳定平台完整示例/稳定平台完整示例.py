"""稳定平台完整示例：真实执行需求、装配、制品、升级、回滚和证据链。"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Any
from 平台控制面.统一入口 import 统一能力服务
from 平台控制面.授权 import 发布者
from 支持库.适配层 import 生成密钥对

包id = "示例_文本统计包"
能力id = "文本.统计"
需求目标 = "需要统计中文文本的字数与行数，并验证制品构建、签名、安装、升级与回滚。"

class 稳定平台完整示例:
    def __init__(self, 存储目录: Path | None = None) -> None:
        self.目录 = Path(存储目录 or tempfile.mkdtemp(prefix="工作包20_"))
        self.服务 = 统一能力服务(self.目录); self.身份id = "示例发布者"
        self.令牌 = self.服务.授权.注册身份(身份id=self.身份id)
        成功, 消息 = self.服务.授权.引导授予(身份id=self.身份id, 角色=发布者, 授予者="系统引导")
        if not 成功: raise RuntimeError(消息)
        成功, 消息 = self.服务.授权.切换角色(self.令牌, 发布者)
        if not 成功: raise RuntimeError(消息)
        self.私钥, self.公钥 = 生成密钥对()
        self.服务.仓库.登记发布者(发布者=self.身份id, 公钥PEM=self.公钥)
        self.服务.导入签名密钥(身份id=self.身份id, 私钥PEM=self.私钥)

    @staticmethod
    def 统计文本(*, 文本: str) -> dict[str, Any]:
        return {"字数": sum(not c.isspace() for c in 文本), "行数": len(文本.splitlines()) or 1}

    @staticmethod
    def _预算() -> dict[str, Any]:
        return {x: 10 for x in ("内存上限", "线程上限", "子进程上限", "并发调用上限", "队列长度", "文件句柄上限", "临时空间上限", "每分钟重启次数", "空闲回收时间")} | {"单次调用超时": 5}

    def _证据(self, 类型: str, 内容: dict[str, Any]) -> None:
        self.服务.状态.追加证据(类型=类型, 主题=包id, 内容=内容, 调用者=self.身份id, 角色=发布者, 结果="成功")

    def 执行(self) -> dict[str, Any]:
        服务 = self.服务
        快照 = 服务.需求.登记需求(目标=需求目标, 调用者=self.身份id, 角色=发布者); 需求id = 快照["需求id"]; self._证据("登记", {"需求id":需求id})
        if not 服务.需求.确认需求(需求id=需求id, 调用者=self.身份id, 角色=发布者)[0]: raise RuntimeError("确认需求失败")
        self._证据("确认", {"需求id":需求id})
        if not 服务.目录.登记能力(能力id=能力id, 契约={"能力id":能力id,"名称":"文本统计","参数":["文本"],"返回":{"字数":"整数","行数":"整数"}}, 组件="文本工具", 领域="文本处理", 成熟度="稳定", 所有者=self.身份id)[0]: raise RuntimeError("登记能力失败")
        if not 服务.注册提供者(能力id=能力id, 函数=self.统计文本, 预算=self._预算())[0]: raise RuntimeError("注册提供者失败")
        搜索 = 服务.执行操作(令牌=self.令牌, 操作="搜索能力", 参数={"关键词":"文本"}); self._证据("搜索", {"数量":搜索.get("数量",0)})
        计划结果 = 服务.执行操作(令牌=self.令牌, 操作="生成装配计划", 参数={"需求id":需求id,"关键词":"文本"})
        计划 = 计划结果["计划"]; self._证据("装配", {"工作包数":len(计划["工作包表"])})
        工作包表=[]
        for 包 in 计划["工作包表"]:
            工作包表.append(服务.需求.保存工作包(需求id=需求id, 波次=包["波次"], 说明=包["说明"], 输入快照={"目标":需求目标}, 允许修改路径=["示例_输出"], 能力占用=包["能力占用"], 资源预算=self._预算(), 验收命令="python3.14 主.py")["工作包id"])
        self._证据("工作包", {"数量":len(工作包表)})
        def 构建(版本: str, 内容: str):
            ok,msg,摘要=服务.仓库.构建制品(包id=包id,版本=版本,文件表={"主.py":内容},构建输入={"源码":"文本统计组件","构建命令":"python3.14 主.py"})
            if not ok: raise RuntimeError(msg)
            签名成功, 签名消息 = 服务.仓库.签名制品(制品摘要=摘要,私钥PEM=self.私钥,发布者=self.身份id)
            if not 签名成功: raise RuntimeError(签名消息 or "签名失败")
            self._证据("签名", {"版本":版本, "制品摘要":摘要})
            return 摘要
        v1=构建("1","def 统计():\n    return 1\n"); self._证据("构建", {"版本":"1"})
        if not 服务.仓库.安装制品(制品摘要=v1,目标目录=self.目录/"已激活"/包id)[0]: raise RuntimeError("安装失败")
        self._证据("安装", {"版本":"1"})
        p1=服务.发布.登记期望版本(包id=包id,期望版本="1",调用者=self.身份id); 服务.发布.开始灰度(发布id=p1,候选版本="1",比例=0.1); 服务.发布.激活(发布id=p1,目标=v1)
        调用=服务.执行操作(令牌=self.令牌,操作="调用能力",参数={"能力id":能力id,"参数":{"文本":"你好世界\n第二行"}}); self._证据("调用", {"结果":调用["结果"]})
        v2=构建("2","def 统计():\n    return 2\n"); p2=服务.发布.登记期望版本(包id=包id,期望版本="2",调用者=self.身份id); 服务.发布.开始灰度(发布id=p2,候选版本="2",比例=0.1); 服务.发布.激活(发布id=p2,目标=v2); 升级=服务.发布.当前激活(包id); self._证据("升级", {"版本":"2"})
        if not 服务.发布.回滚(发布id=p2,回滚目标=v1,调用者=self.身份id)[0]: raise RuntimeError("回滚失败")
        回滚=服务.发布.当前激活(包id); self._证据("回滚", {"版本":"1"})
        return {"需求id":需求id, "计划":计划, "调用结果":调用["结果"],
                "v1摘要":v1, "v2摘要":v2, "升级后指针":升级,"回滚后指针":回滚,
                "证据":服务.状态.查询证据(主题=包id,限制=100),"工作包表":工作包表}
