---
名称: 第二十五阶段wp4-TesseractOCR支持库-计划
标签: [第二十五阶段, wp4, Tesseract, 支持库, 计划]
创建时间: 2026-08-03T09:15:09.692431+00:00
---

任务类型: 功能开发（支持库）

说明: 新建 Tesseract OCR 支持库（独立提供者包 支持库/适配层/Tesseract提供者/），能力：OCR识别（图片路径/图片字节→文本/词级数据）、语言包列表、版本探针；统一中文契约与错误码（工具缺失/语言包缺失/识别失败/超时/取消/进程崩溃/提供者不可用/超出限制）。

落点: 按 PyMuPDF提供者 七件套模板新建包；实现/ 下三个文件：受管进程.py（start_new_session+killpg、超时、取消、输出上限、零残留）、临时文件.py（字节输入临时落盘与清理）、提供者.py（公开能力+错误分类）；__init__.py 公开入口+注册能力；测试 测试中心/支持库/测试_Tesseract提供者.py。

技术方案: 参考 PyMuPDF提供者/系统探针.py 模式。关键环境事实（实测）：Homebrew tesseract 5.5.2 无法读取绝对路径图片（Leptonica fopen 失败），必须以图片所在目录为 cwd + 相对文件名启动；`tesseract <img> stdout -l <lang>` 文本输出、`... tsv` TSV 词级输出均走 stdout，零临时文件；`tesseract --version` 首行版本；`--list-langs` 首行数据目录+后续语言行；语言包缺失 stderr 含 "Failed loading language"/"traineddata"。版本探针/语言包列表/OCR 在 tesseract 缺失时如实返回 工具缺失（可重试）。取消用 threading.Event 轮询，killpg 强杀。
