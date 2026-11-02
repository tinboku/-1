# 同类开源项目调研与技术选型

日期：2026-11-02
目的：为 clean-room 复刻 Undermind 寻找可参考的开源实现与可复用组件。
原则：**借鉴架构与方法，不复制代码**；本仓库实现为自研代码，
数据源走各家官方公开 API。

## 1. 最相关的开源项目

| 项目 | 是什么 | 借鉴点 | 不直接用的原因 |
|---|---|---|---|
| **CiteLens (citens)**（yfxiao123/citens） | 开源文献综述 agent：多源检索→复合排序→结构化抽取→带引用写作→逐条引用核查 | 四源并发检索（arXiv/S2/OpenAlex/Crossref）；相关性×引用×期刊分区的复合排序；**逐条 claim 引用核查 + citation precision 指标**；滚雪球后精度显著提升的实证 | 体量大、面向综述写作而非 Undermind 式"项目+对话"产品形态；作为方法参考 |
| **OpenScholar**（AkariAsai/OpenScholar，★1.7k） | Ai2/UW 的检索增强文献综合模型（Nature 2026），45M OA 论文段落库 | 检索→引用支撑的综合→**自反馈修订循环**；引用准确性作为一等指标；ScholarQABench 可作评测参考 | 需要自建 45M 段落索引与模型部署，远超本项目体量 |
| **Ai2 Scholar QA**（Allen Institute） | 免费科学问答应用，全流水线开源 | 多阶段流水线：多索引查询→**逐篇抽取原文引句**→主题化组织→带归属的长答；引用蕴含（entailment）核查 | 偏问答而非深度检索发现；其"先抽引句再组织"值得抄作业 |
| **PaperQA2**（Future-House/paper-qa） | 对自有论文库做带页码引用的问答/抽取 | 全文解析→分块索引→问答与结构化抽取的工程做法（本项目"论文库问答/抽表"的参考） | 它不做全网发现，只处理已有文库；是互补件不是竞品骨架 |
| **STORM**（Stanford OVAL，knowledge-storm） | 从零研究一个主题并写出带引用的长文 | **提纲先行**、多视角提问驱动检索、写前先组织结构 | 数据源是开放网页而非学术图谱；报告组织法可借鉴 |
| **GPT-Researcher**（assafelovic，★30k） | 通用深度研究 agent（规划→爬取→聚合→长报告） | planner/executor 多 agent 分工、报告流水线工程化 | 面向开放网页研究，学术元数据与引用图谱不是其强项 |
| **LitLLM**（shubhamagarwal92/LitLLM） | 文献综述工具包（混合检索+计划式生成） | 检索与生成解耦、按计划逐节生成综述 | 偏综述成文，交互形态不同 |
| **ASReview**（asreview，★1k） | 系统综述主动学习筛选 | **主动学习排序筛选**：人标少量、机器排剩余——对应 MATCH 分的校准思路 | 是筛选工具，不做发现与报告 |
| **LitUbik** | 人类主导的系统综述平台（AGPL） | 协议→检索式→去重→筛选→滚雪球→抽取→PRISMA 的完整可追溯流程 | AGPL 且为重型 Web 平台；作流程完整性参照 |

## 2. 第二批参考（2026-11-02 晚补充）

| 项目 | 教我们的事 | 对应我们的缺口 |
|---|---|---|
| **PaSa**（ByteDance，ACL 2025，bytedance/pasa） | Crawler/Selector 双 agent：Crawler 对队列里**每篇论文**自主决策「调检索 / 展开引用 / 停」，Selector 逐篇按 criteria 判分。另有 AutoScholarQuery（35k 合成查询-论文对）与 RealScholarQuery 基准 | 我们的 reflect/滚雪球是固定轮数+模板规则，应升级为逐篇决策；其数据集可直接拿来做评测 |
| **DeepScholar-Bench**（guestrin-lab） | 活基准：用近期 arXiv 论文的人工 Related Work 当金标准，评组织性/要点覆盖/相关性率/引用可核查性；附参考实现 DeepScholar-ref（LOTUS 语义算子：filter/top-k/aggregate 组合管线）。全场最好系统综合分也不到约 31%——这件事本来就难 | 给我们立评测：没有基准，每次改版都是凭感觉 |
| **LitSearch**（Princeton，597 查询） | 检索基准实测：稠密检索（GritLM recall@5 74.8%）远胜 BM25 类词法方法，LLM 重排再 +4.4% | 我们的启发式词法评分只是占位；升级路线 = 语义检索 + LLM 重排 |
| **AutoSurvey / AutoSurvey2** | 综述生成管线：检索 → 并行分节 RAG 起草 → 整合修订 → 多标准自评；64K token 综述的引用 recall 82.25% / precision 77.41%，消融证明去掉检索引用 recall 直接崩到 60% | 我们的报告是单遍抽取式，应升级为提纲→分节起草→引用保真自评 |
| **ASReview Datatools** | `asreview data snowball` 用 OpenAlex 按 DOI 列表做前/后向滚雪球，是系统综述圈的标准做法；ASReview 本体的主动学习筛选（人标几篇→模型重排其余）是筛选环节的金标准 | 我们的 trace 与之同构（多一个 S2 通道）；可加「人工反馈重排」 |
| **GROBID** | PDF 结构化解析的事实标准（标题/作者/参考文献/章节切分） | 全文层：我们的 PDF 导入目前只登记文件，全文解析应走 GROBID 或 PaperQA2 的管线，别自己造 |

优先级建议：① 先接 LLM key（零代码、收益最大）→ ② PaSa 式逐篇遍历决策 + LitSearch 式语义重排 → ③ 用 DeepScholar-Bench/LitSearch 搭小评测 → ④ 全文层（GROBID/PaperQA2）→ ⑤ AutoSurvey 式报告管线。

## 3. 数据源选型（官方 API，均为公开接口）

| 数据源 | 角色 | 要点 |
|---|---|---|
| **Semantic Scholar Graph API** | **主源**（与 Undermind 同源） | 论文检索、批量检索、引用/参考文献端点（滚雪球）、推荐端点、TLDR、OA PDF 链接、SPECTER 向量；无 key 时共享池限流严重（实测首呼即 429），有 key 1 req/s；客户端必须做退避重试 |
| **OpenAlex API** | 副源与互补 | 250M+ works、CC0；`filter=cites:<id>` 做前向滚雪球、主题/概念分类、OA 位置；2026 年起改为 key+额度制，无 key 试用额度很小，需优雅降级 |
| **Crossref API** | DOI 元数据补全 | 按 DOI 查标题/作者/期刊/年份，导入与去重的锚点 |
| **arXiv API** | 预印本补充（规划中） | CS 预印本时效性；S2 已覆盖大部分，列为二期 |

## 4. 本项目的技术选型结论

- **语言/依赖**：Python 3.12，只依赖 `requests`（其余全标准库：
  sqlite3 存项目库、http.server 提供 Web UI、unittest 做测试）。
  零重型框架，保证在任何机器上 `pip install -e .` 即可跑。
- **LLM 层可插拔**：定义统一后端接口（头脑风暴、生成检索标准、
  MATCH 评分、报告写作、表格抽取、反思）。两种实现：
  ① OpenAI 兼容接口（设 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 后启用，
  质量模式）；② **离线启发式后端**（词法相关性+引用特征打分、
  抽取式报告），无 key 也能端到端跑通与测试。
- **引擎阶段**与 Undermind 对齐命名：Interpreting → Searching →
  Identifying → Reflecting → Adapting（滚雪球轮次）→ 收敛判定。
- **发现曲线**：用双通道捕获-再捕获（Lincoln–Petersen）估计相关
  文献总量（S2 与 OpenAlex 两路独立检索的重叠推总量），
  叠加轮次饱和曲线，输出覆盖率估计并注明方法——这是 Undermind
  评测中出现、但我们实测未证实的功能，按自研课题实现。
- **MCP**：实现一个最小 MCP（stdio JSON-RPC）服务器，暴露
  deep_search / search_papers / get_paper 三个工具，
  对齐 Undermind 的 agent 接入卖点。
