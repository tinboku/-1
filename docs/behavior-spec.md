# Undermind 行为规格（黑盒）v0.1

日期：2026-11-02
方法：未登录状态下实测官网 + 官方 FAQ 自述 + 第三方评测交叉核对。
证据分级：= 本次亲眼确认；= Undermind 自己页面/FAQ 的说法，未独立验证；= 评测/教程站描述；= 被注册墙挡住，尚未看到。

## 1. 入口与注册墙

- 官网首页没有游客搜索框，唯一主入口是 "Sign up free"。
- app.undermind.ai 同样没有搜索入口，点 Get started 直达注册页。
- 注册页只要一个邮箱地址 + Continue 按钮（另有 Sign in 入口），
无游客试用、无跳过选项。因此：**任何搜索行为都必须先有账号。**
- 免费档的具体额度（如深度搜索次数）注册前不可见。
一所大学图书馆的教程页称注册送 2 次"深度"（全文）搜索，
之后免费档只搜摘要。

## 2. 产品流程

官网 "How Undermind works" 四步：

1. **Describe** — 用户说明研究课题，系统先追问以澄清需求。
2. **Explore** — 系统检索文献，阅读并评估数百篇论文，顺引用轨迹追踪，直到找全。
3. **Build** — 围绕报告迭代：读全文、抽取细节成表、深化理解。
4. **Keep up** — 持续监控用户关注的主题，有新论文时通知。

功能点（官网 Features）：与"读过相关文献的 AI 专家"头脑风暴；
行内引用可回溯原文核对；相关性判断与排序筛选；新论文提醒；
可通过 MCP Server 接入 Claude、ChatGPT 等外部 agent。

## 3. 检索方法

- **数据源实锤**：Semantic Scholar（2 亿+论文），另可访问
PubMed Central 及其他开放获取全文源。（纠正早期第三方评测
"官方不公开数据库"的说法——FAQ 明确写了 Semantic Scholar。）
- **不靠关键词匹配**：把研究目标扩展成多个不同的检索，逐篇细读评估，
再用引用关系扩展搜索，**直到搜索收敛**（iterative, agent-based reasoning）。
- **单次搜索规模**：可阅读数百篇论文；耗时几分钟量级；
用户可以离开，回来时报告已备好。
- **没找到某篇论文的官方解释**：可能不在 Semantic Scholar 库内，
或本次搜索尚未收敛（结果随搜索展开而变好）。

## 4. 效果宣称

- 自称 v1 搜索引擎结果比 Google Scholar 好 10 倍，v2 又有改进。
- 官方基准图：23 个研究目标、10 分钟时平均召回——
Undermind 深度搜索 73%；若干前沿模型 + 联网搜索的 agent 配置为 29–39%。
- 第三方评测转述的官方基准：10 分钟内找回 top-20 最相关论文的 85%；
一次搜索平均约 2.9 分钟自动停止。

## 5. 交互细节

- 登录后是"项目制"工作区，主模式有 Browse / Read / Chat；
左侧栏有 Files 与 Searches；核心交互是对话式的 Chat，不是手动翻论文表。
- Chat 回答前会出现工具状态块，如 "Reviewing searches"、
"Finding relevant papers"、"Reading abstracts"、"Reading full texts"。
- 提交问题后，系统会先提出"sharpen"追问，用户可答可不答，答了结果更准。
- 报告含由生成式 AI 撰写的分类小结（每条论断链接到来源文章），
底部附引用论文表；报告下方可继续追问以细化查询。
- 论文以 paper key（如 @Lu24）互相引用对照。

## 6. 定价

- 学术：Free $0；Pro $16/月（年付）；Team $15/人/月（年付）；Enterprise 定制。
- 行业：Free $0；Pro $20/月（年付）；Team $25/人/月（年付）。
（纠正个别评测站"行业 Pro $60"的说法，以官网为准。）
- Pro 相对 Free：最新最强模型、全文深度分析、10 倍额度、
无限工作区/文件/论文库。

## 7. 待实测清单

1. 澄清追问的原文、题型（选择/填空）、轮数。
2. 搜索运行时的进度 UI 文案、各阶段名称、实际耗时、评估论文数。
3. 报告的完整结构：分节方式、引用格式、覆盖度/收敛指标是否存在及长相。
4. 结果论文列表的排序依据、相关性分数呈现。
5. 免费额度与付费墙触发点、升级提示文案。
6. 用一个可判质量的测试问题跑完整搜索，记录 top-10 论文，与
Google Scholar / Semantic Scholar 直接检索的结果做召回对照。
测试问题（已备好）：
"Methods for automatically generating natural-language descriptions of
tabular datasets using large language models, including data profiling
and metadata generation approaches"

## 8. 对复刻的启示（初步）

- 数据层用 Semantic Scholar Graph API 即可对齐它的主库，自建索引不必要。
- 核心差异化不在检索 API，而在：目标扩展策略、逐篇相关性评估的质量、
引用滚雪球的收敛判据。这三点正是 MVP 要重点打磨的。
- 产品形态值得抄作业的是"项目 + 对话"而不是"搜索框 + 结果页"：
搜索是一次性动作，项目库 + 持续追问 + 新论文监控才是留存。
