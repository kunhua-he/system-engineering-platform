---
名称: 第二十五阶段wp4-TesseractOCR支持库-完成
标签: [第二十五阶段, wp4, Tesseract, 支持库, 完成]
创建时间: 2026-08-03T09:35:26.879444+00:00
---

调用方式: 从 支持库.适配层.Tesseract提供者 导入 识别图片(图片路径/图片字节二选一, 语言="eng", 词级数据=False, 超时秒=60, 取消事件=None, 输出上限字节=None) → {文本} 或 {词列表}；语言包列表(超时秒) → {语言列表, 数据目录, 数量}；版本探针(超时秒) → {tesseract, 版本, 满足最低版本}。tesseract 缺失时如实返回 工具缺失（可重试）。

关键决策: (1) 实测 Homebrew tesseract 5.5.2 无法读取绝对路径图片（Leptonica fopen 失败），必须以图片目录为 cwd + 相对文件名启动；字节输入经临时文件.py 落盘（临时目录前缀 Tesseract提供者_）后同样以相对名调用，finally 即时清理零残留。(2) 受管进程.py 通用外部命令管理：start_new_session+killpg（SIGTERM→SIGKILL）、超时/取消（threading.Event 轮询）/输出上限（后台泵线程）三类强制终止映射稳定错误码 超时/取消/超出限制；正常结束返回 {退出码, 标准输出, 标准错误} 由调用方分类（退出码<0→进程崩溃）。(3) 语言包缺失分类：stderr 含 "Failed loading language"/"traineddata"→语言包缺失；其余非零退出→识别失败。(4) 词级数据用 tesseract TSV 输出（level=5 行），位置索引解析（conf=10,left=6,top=7,width=8,height=9,text=11）。验证：18 个测试全部通过（真实 OCR 用 PIL 生成图片 + tesseract 5.5.2）；文件行数 ≤160；完整性摘要已生成。

边界: verify_and_record 官方证据通道绑定主工作区且禁止 worktree 绝对路径（跨仓库任务限制），验证证据以 worktree 内 bash 执行退出码 0 为准。
