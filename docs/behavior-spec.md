# Undermind 行为规格（黑盒）v0.2 — 实测版

日期：2026-11-02
方法：用已有免费账号登录 app.undermind.ai，完整跑通一次真实搜索
（描述生成测试问题）+ 报告生成 + 聊天抽表，并逐页盘点了工作区功能。
证据分级：= 本次亲眼确认；= 官网/FAQ 说法；
= 评测站描述；未标注的均为。

## 1. 账号与登录

- 已有免费账号即可用；登录方式为邮箱 + 6 位验证码（无密码登录流程）。
- 账号标识："TB tin boku Free"，带 "Upgrade to Pro" 入口。
- 官网无游客模式（v0.1 已确认）：不注册连搜索框都看不到。

## 2. 工作区结构

- 对象类型：Searches、Chats、Files、Papers（论文库）、Folders、Uploads。
- 侧边栏：New chat、Add papers、All Papers、Starred、Uploads、Files、
Chats、Updates；底部主视图切换：Browse / Read / Chat。
- 顶部是标签页式导航，可同时打开多个搜索、报告文件、论文库页签。
- 论文的稳定标识是作者年简码 KEY（如 Zha25、Cai26b），全站通用：
结果列表、报告行内引用、文末论文表都用它。

## 3. 一次搜索的完整流程（实测时间线，2026-11-02 JST）

1. **提交问题**（17:20）：在 Chat 里输入自然语言研究问题，
状态文案依次出现 Papertrailing… 等。
2. **头脑风暴澄清**（17:21，状态 Brainstorming…）：先问 2 道问题再搜——
一道问范围取舍（只看 LLM 方法，还是纳入早期非 LLM 方法作对比）；
一道问用途与重点（面向编目/数据集发现还是更广的表格理解，
评估是否优先）。可答可不答。
3. **生成搜索草稿**（状态 Crafting…）：产出一个带标题的搜索草稿，
核心是 "Search criteria"——一组自然语言检索标准句（本次 2 条，
分别覆盖"自动生成表格数据集自然语言描述/画像/元数据的方法"和
"含非 LLM 早期方法、面向编目与发现的方法与评估"），用户确认后点 Launch。
4. **深度搜索运行**（17:22 → 约 17:28，约 6 分钟）：进度页阶段标签按序为
Interpreting your search criteria → Searching for the most promising
papers → Identifying the best candidate papers → Reflecting on the
results → Adapting and searching again；顶部状态词 Deepdigging…，
有 Stop 按钮。**没有实时篇数计数器**，跑完才给最终计数。
5. **结果页**：标题行 "52 papers · 36 with full text · 12 excluded"，
有 "Open all 52 results"。结果表列：KEY、YEAR、CIT/YR（年均引用）、
TITLE、作者/来源、MATCH（匹配度百分比），可按 MATCH 排序；
单篇可 Star、看 PDF、Add to folder、展开看摘要与 "Read full text"。
6. 本次 MATCH 前五：AutoDDG（2025，100%）、DataAtlas（2026，99%）、
TACO（2026，98%）、Pneuma（2025，98%）、一篇数据生成方法综述（2025，98%）；
Polaris（2026）第 9，97%。

## 4. 跟进聊天与技能

- 搜索完成后有 Follow-up Chat；聊天输入框上方有三个"技能"按钮：
Deep search、Write report、Organize papers。
- Organize papers 的官方说明：用文件夹和自定义字段组织论文库，
选择后同样先头脑风暴提问再动手建结构。

## 5. 报告生成

- 搜索页点 Generate Report，会在聊天框预填一句可编辑的指令；
发送后**再来一轮头脑风暴**（本次 2 道：一道问报告定位——方法地图 /
选型指南 / 批判性评估；一道问是否与用户已有的跨表发现工作挂钩）。
- 产物是一个 **Files 里的文件**（本次名 "LLM Dataset Description Methods"），
17:31 答完问题后约 4 分钟生成完毕。
- 结构（本次实测）：标题 → Executive summary → What counts as a dataset
description → Inputs and evidence used → Output types and method
families → How description quality and usefulness are evaluated →
Reliability, review, and operational limits → Practical synthesis →
Bottom line → 文末完整论文表。正文含多张对比表
（方法映射、输入、输出家族、评估方法）。
- 行内引用就是 KEY 简码（如 Zha25），点开即对应论文。
- **报告里没有相关性分数列，也没有覆盖率/完整度百分比**——
只有篇数口径（52 篇、36 篇全文）。见第 10 节与第三方说法的出入。
- 文件页操作：Export file、Request Edit、More actions
（Share / Duplicate / Rename / Move to folder / Download / Delete）。

## 6. 表格抽取

- 论文列表和搜索页**没有独立的"添加列/抽取"按钮**；抽取走聊天：
自然语言指定列名即可。本次让它对 top 论文抽
paper / year / method / profiling-metadata inputs / output type 五列，
约 3 分钟生成 10 行表，并附注只用搜索结果内的论文、不引入外部来源。
- 对比 Elicit 的列式抽取 UI，Undermind 的抽取更"对话驱动"。

## 7. 论文导入（Add papers 菜单）

Upload PDFs、Add via DOI、Import from Zotero、
Import from Semantic Scholar、Import from BibTeX。

## 8. 导出

- 论文：Export as CSV / BibTeX / RIS。
- 报告文件：Markdown、DOCX、PDF、LaTeX、BibTeX、Research notebook
（可导入 Obsidian/Notion 的 Markdown），另有 Copy as Markdown。

## 9. 监控、协作、集成、设置

- **Updates（新论文提醒）默认开启**：每次搜索自动被定期检查，
有新论文出现在 Updates 页，可对单条搜索 Turn off。
- 协作：Invite to workspace；文件可 Share、Request Edit。
- **MCP**：账号页有 "MCP access" 区（本次账号显示已有 1 个 app 接入，
可 Revoke），另有 Manage apps。
- 账号页：改名、改密码、删号、Data export（Download your data）、Billing。
- 定价（账号页实测，年度价）：学术 Pro $16/月、Team $15/人/月；
行业 Pro $30/月、Team $25/人/月。（官网首页年付切换曾显示行业 Pro $20，
口径不一，以账号页为准。）Pro 卖点：无限搜索/Deep Search/论文库/
上传/聊天/文件夹 + 优先速率与搜索质量。
- 免费档官方口径只有一句 "standard rate limits and search quality"，
**未公示每月次数**；本次一次完整搜索 + 报告 + 抽表全程未撞付费墙。

## 10. 与第三方说法的出入（重要）

- **"发现曲线/覆盖率百分比"未证实**：多家评测称它会给出
"已找到约 89.7% 相关文献"这类覆盖度估计；本次报告与结果页
均未出现任何覆盖率指标，只有篇数计数。可能已改版、或仅在
特定视图/套餐出现，复刻时不要当作已确认功能。
- **平均 2.9 分钟是营销口径**：本次实测约 6 分钟（免费档）。
- **免费额度**：评测有"每月 5 次""送 2 次深度搜索"等说法互相矛盾，
官方未公示，以账号页"standard rate limits"为准。
- 数据源 Semantic Scholar 为官方 FAQ 实锤（v0.1 已确认），
与"官方不公开数据库"的评测说法矛盾，以官方为准。

## 11. 检索方法（官方自述，FAQ，v0.1 沿用）

把研究目标扩展成多个检索，逐篇细读评估，再用引用关系扩展，
直到搜索收敛；单次可读数百篇；数据源为 Semantic Scholar
（2 亿+）加 PubMed Central 等开放获取全文源。

## 12. 对复刻的启示（v0.2 更新）

- **产品骨架 = 项目工作区 + 对话**，搜索/报告/组织都是聊天里的"技能"；
所有产物（搜索、报告文件、论文库）沉淀在项目里，可多标签并行。
- **两个头脑风暴关卡**是它体验的灵魂：搜前澄清范围、写报告前澄清定位，
且都先产出"草稿/标准"让用户确认再执行——可控感来自这里。
- **KEY 简码引用**（作者年）比数字编号更适合做行内引用：
人类可读、跨视图稳定，复刻时建议沿用。
- 核心引擎仍是三件事：检索标准生成（把问题改写成多条 criteria）、
逐篇相关性评估产出 MATCH 分、反思-再搜索的自适应循环（阶段标签
里的 Reflecting / Adapting 就是这个循环的产品化呈现）。
- 发现曲线若真实存在，是"敢说找全了"的关键差异化；但未实测到，
复刻时可作为自研课题（用捕获-再捕获估计总量），不列入 MVP。
