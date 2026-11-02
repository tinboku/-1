# 复刻版设计：deep-literature-search

## 功能对照（Undermind → 本项目）

| Undermind 功能 | 本项目实现 | 状态 |
|---|---|---|
| 搜前头脑风暴澄清（2 问） | `brainstorm`：LLM 生成 / 启发式模板，按问题类型给范围与重点两问 | 已实现 |
| 搜索草稿（Search criteria + Launch 确认） | `criteria` 生成多条自然语言检索标准，CLI 展示后确认；`--yes` 可跳过 | 已实现 |
| 深度搜索（多路检索+逐篇评估） | S2 主检索 + OpenAlex 副检索合并去重；逐篇 MATCH 评分 | 已实现 |
| 进度阶段（Interpreting…Adapting） | 引擎回调输出同名阶段 + 每轮统计 | 已实现 |
| 引用滚雪球至收敛 | 对 top 种子做 citations+references 扩展，逐轮重评，新增相关率低于阈值即收敛；另有 `trace` 命令从单篇种子出发沿引用图谱双向展开（带来源溯源） | 已实现 |
| 结果计数（found / full text / excluded） | 搜索结果对象含三计数（全文=有 OA PDF 或有全文链接） | 已实现 |
| MATCH 分（百分比） | LLM 评分或启发式评分，0–100，存库可排序 | 已实现 |
| 发现曲线/覆盖估计 | 双通道捕获-再捕获 + 轮次饱和估计（实验性，注明方法） | 已实现（实验） |
| 带 KEY 引用的报告文件 | Markdown 报告：执行摘要/方法族/输入证据/评估/局限/结论 + 文末论文表；引用用作者年 KEY | 已实现 |
| 写报告前再一轮头脑风暴 | `report --focus` 参数 + 默认定位提问（CLI 交互） | 部分实现 |
| 跟进聊天（对搜索结果追问） | `ask`：以入选论文摘要为上下文的 RAG 式问答（需 LLM；启发式模式给出抽取式回答） | 已实现 |
| 聊天抽表（指定列→表格） | `extract --columns ...`：LLM 按列抽 JSON；启发式模式抽年份/方法关键词等基础列 | 已实现 |
| 论文库（All Papers / Starred / Folders） | SQLite 库：papers、stars、folders；CLI 与 Web UI 可浏览 | 已实现 |
| 导入（PDF / DOI / Zotero / S2 / BibTeX） | DOI 导入（Crossref+S2）、BibTeX 文件导入、PDF 文件登记（存文件+基础元数据）；Zotero 经其 BibTeX 导出兼容 | 已实现（PDF 全文解析为基础版） |
| 导出（论文 CSV/BibTeX/RIS；报告多格式） | 论文：CSV/BibTeX/RIS；报告：Markdown/HTML | 已实现（DOCX/PDF 待后续） |
| Updates 新论文监控（默认开） | `updates check`：按已存 criteria 重跑并按日期过滤出新增，存 updates 表 | 已实现 |
| MCP 接入 | 最小 MCP stdio 服务器：deep_search/search_papers/get_paper | 已实现（基础版） |
| Web 工作区（多标签、Browse/Read/Chat） | 本地 Web UI：项目/搜索/论文库/报告浏览（单页式，非多标签） | 部分实现 |
| 账号/计费/协作 | 本地单机工具，不做 | 不做 |

## 架构

```
dls/
  config.py          # 环境变量配置（API key、LLM、路径）
  models.py          # Paper / SearchResult / SearchRun 数据类
  llm.py             # LLM 后端协议 + OpenAI 兼容实现 + 启发式实现
  clients/
    semantic_scholar.py
    openalex.py
    crossref.py
  engine.py          # 深度搜索编排（阶段、滚雪球、收敛、覆盖估计）
  scoring.py         # 启发式 MATCH 评分、KEY 生成、去重
  store.py           # SQLite 项目库
  report.py          # 报告生成与导出（MD/HTML/BibTeX/CSV/RIS）
  extract.py         # 聊天抽表
  updates.py         # 新论文监控
  importers.py       # DOI / BibTeX / PDF 导入
  cli.py             # 命令行入口 `dls`
  web.py             # 本地 Web UI（stdlib http.server）
  mcp_server.py      # MCP stdio 服务器
tests/               # unittest（假客户端/假 LLM，可离线跑）
```

## 数据流（一次深度搜索）

问题 → 头脑风暴问答 → criteria[] → 多路检索（S2 各 criteria +
原始问题；OpenAlex 原始问题；Crossref 兜底通道）→ 合并去重 → 逐篇 MATCH →
入选集 → top 种子滚雪球（references+citations，≤2 轮）→
新候选重评 → 收敛判定 → 覆盖估计 → 存库 → 报告/抽表/问答。

## 已知边界

- S2 无 key 时限流严苛（429 常见）：客户端指数退避；建议用户申请
  免费 S2 API key 后设 `SEMANTIC_SCHOLAR_API_KEY`。
- OpenAlex 2026 年起 key+额度制：无 key 时副通道可能不可用，
  引擎自动降级为单通道（覆盖估计随之标注为不可用/低置信）。
- 启发式后端的报告是抽取式拼装，质量定位为"结构正确的草稿"；
  设 LLM key 后报告、评分、抽表均为生成式，质量显著提升。
