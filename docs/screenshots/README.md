# Streamlit 页面截图

本目录中的 PNG 由 `scripts/capture_screenshots.py` 调用本机无头浏览器
（Microsoft Edge / Google Chrome）**真实渲染**后截取，未使用任何占位图或伪造图片。
渲染失败或页面未成功切换的截图不会保留。

## 采集信息

- 截取时间：2026-11-16 19:41:54
- 浏览器：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
- 本次独立启动的后端端口：`8010`（uvicorn，临时数据库）
- 本次独立启动的前端端口：`8510`（streamlit）
- 截图窗口：`1440x1000`
- 截图方式：CDP（Chrome DevTools Protocol，等待真实渲染完成后截图）
- 前端入口：`frontend/app.py`（`st.navigation()` 组织 5 个页面）

## 已成功截取的页面

| 文件 | 对应页面 | 访问路径 | 像素 | 文件大小 |
| --- | --- | --- | --- | --- |
| `01_智能助手.png` | 智能助手（默认页） | `/` | 1440x1000 | 140,630 字节 |
| `02_知识库管理.png` | 知识库管理 | `/knowledge` | 1440x1000 | 176,167 字节 |
| `03_检索调试.png` | 检索调试 | `/retrieval` | 1440x1000 | 138,320 字节 |
| `04_Agent工具管理.png` | Agent 工具管理 | `/tools` | 1440x1000 | 162,349 字节 |
| `05_RAG评估中心.png` | RAG 评估中心 | `/evaluation` | 1440x1000 | 207,787 字节 |

## 未截取到的页面及原因

（无：5 个页面均成功截取。）

> 说明：Streamlit `st.navigation()` 的页面 URL 由 `st.Page` 的文件名推断，
> 默认页为 `/`。若某些 URL 渲染出的仍是默认页或空白页，脚本会判定为
> 未真实截取并丢弃对应图片，具体原因见上表。
