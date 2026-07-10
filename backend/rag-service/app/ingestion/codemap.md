# backend/rag-service/app/ingestion/

## 职责

文档处理管道。支持 PDF / DOCX / MD / HTML / TXT 格式的解析、清洗和智能分块。

## 设计

- `DocumentProcessor.process()`: 提取→清洗→分块→hash 完整链路
- 分块策略: 优先按 Markdown 标题分割，否则用固定窗口 + 重叠
- Token 级分块（tiktoken），降级到字符级分块
- PDF/DOCX 解析有多个降级路径（unstructured → PyMuPDF / python-docx）
