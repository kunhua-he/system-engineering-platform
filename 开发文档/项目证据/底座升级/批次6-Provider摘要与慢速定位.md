# 批次 6：Provider 摘要与慢速失败定位

```text
重建 18 个 Provider 文件清单摘要
              |
              v
统一摘要校验：18/18 闭合
              |
              v
慢速层真实执行：172 项
              |
              +--> 171 通过
              +--> 1 失败：残留审计内嵌发布门禁
                         |
                         +--> 当前根因：表格文档成功调用向 Provider
                             传入未声明参数“数据模式”；另有模板包扫描边界问题
```

## 本批修改

按 `开发工具/组件规范/完整性摘要.py` 唯一生成器重建以下 18 个带 `包声明.json` 的 Provider 摘要：FFmpeg、Git、LibreOffice、MLXWhisper、PDF 隔离、Pillow、PyMuPDF、Tesseract、openpyxl、pdfplumber、pg8000、psycopg2、psycopg、python-docx、python-pptx、reportlab、textutil、密码签名。

MySQL 提供者与密钥提供者没有 `包声明.json`，属于适配器豁免，本批不新增正式包摘要。

## 验证证据

```text
python3.14 测试中心/运行测试.py --测试文件 测试中心/开发工具/测试_完整性摘要统一.py --并行数 0
退出码：0
结果：18/18 通过
```

摘要逐目录直接校验：18/18 通过，清单与实际文件闭合。

慢速真实命令：

```text
python3.14 测试中心/运行测试.py --范围 慢速 --强制慢速 --并行数 1
退出码：1
```

失败不是摘要不一致：`测试_残留审计.py` 的嵌套发布门禁因权威逐包合规失败而返回 1。当前工作树中表格文档实现向受管 Provider 传入契约未声明的 `数据模式`；模板目录也仍被正式包扫描。两项均保持阻断，不能以“阻断项数 0”放行。本批未修改正式后端能力实现。

## MCP 闭环

- MCP：`system_engineering_toolkit`，根目录已核对。
- 开工id：`3e63a9ede8534046`。
- 已提交 `mcp_feedback`，随后 `verify_and_record` 记录上述 18 项定向测试退出码 0。
- 未使用其他仓库 MCP，未访问或监听 4780。

