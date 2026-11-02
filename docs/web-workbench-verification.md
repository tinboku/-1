# Web Workbench 验证

启动：`dls api --port 8000`，打开 `http://127.0.0.1:8000/`。需要 API extra（`pip install -e '.[api]'`）及相应数据源网络访问；LLM 配置沿用 README。前端无需安装依赖或构建。

## 完整用户流程

1. **研究问题**：点「新检索」，输入问题，点「先澄清并生成标准」。Network 应出现 `POST /api/plan`，页面展示返回的 questions 和 criteria。
2. **澄清回答**：填写回答，点「按回答重新生成标准」。检查本次 `/api/plan` 的 `answers` 包含真实回答；输入内容在重新生成后保留，criteria 来自本次响应。请求失败会显示错误，不能启动旧标准。
3. **确认标准**：编辑 criteria（每行一条），勾选「我已审阅并确认」。点「开始检索」，检查 `POST /api/searches` 同时携带编辑后的 criteria 和回答。回答修改后必须重新生成标准。
4. **真实进度**：右侧「进度」显示 `/api/jobs/{id}/events` 返回的 stage/detail。没有百分比计时器或伪造论文。搜索失败显示真实 error；warnings 和 degraded 在进度及结果页可见。
5. **断线与刷新**：在任务运行时刷新页面，检查先请求 `GET /api/jobs`，自动监视 queued/running 任务。中断 SSE 后观察 `GET /api/jobs/{id}` 每 2.5 秒持续查询；恢复网络后继续显示增量事件且不重复。服务重启导致任务 404 时显示明确提示。任务仅存在于后端内存中。
6. **结果与详情**：完成后自动打开结果。MATCH 下显示 match_source；未记录时显示「来源未记录」，不会由当前模型配置推断历史来源。点击论文行或标题、或聚焦行后按 Enter，查看摘要、引用量、参考文献数、DOI/PDF/来源链接、评分理由及 found_via。星标成功后立即更新状态。
7. **报告和表格**：点「生成报告」，等待真实 job 完成后展示存储的 Markdown 文件。点「抽取对比表」，填写逗号分隔列名后抽取；文件出现在左侧。任务期间切换检索，旧任务的文件不能覆盖新检索的右侧内容；仍可从文件列表打开。
8. **后续追问**：在「问答」输入问题并发送。检查 `POST /api/searches/{id}/ask`，回答来自当前检索的论文。接口错误会显示在回答位置。
9. **论文库**：导入 DOI；或打开 BibTeX 对话框，选择 .bib 文件/粘贴内容后导入。当前解析器要求条目的结束花括号独占一行；无法识别的内容返回 422，临时文件会清理。论文详情可保存收藏夹，论文库可按名称和星标筛选；KEY、DOI、arXiv 或 paper ID 查找使用 `/api/papers/lookup`。CSV/BibTeX/RIS 导出沿用现有接口。
10. **视口**：检查桌面三栏、平板两栏加下方详情、手机纵向布局。论文表格横向滚动，弹窗不超出视口，键盘焦点清晰可见。

## 自动验证

- `python -m unittest discover -s tests`：当前基线 23 个测试全部保留，新增 12 个 API 回归测试，共 35 个。
- `node --test tests/webapp/*.test.mjs`：11 个零依赖回归测试，覆盖真实回答传递、失效事件目标、切换检索与迟到结果隔离、启动时优先恢复任务、SSE 与重复快照/网络故障。
- `node --check webapp/js/api.js` 和 `node --check webapp/js/app.js`，测试脚本也进行语法检查。
- `git diff --check`。

自动化测试使用离线测试夹具，不访问外部学术服务；生产 UI 直接调用实际 API。前端测试使用最小 DOM 适配器，不等同于真实浏览器验收。本次环境禁止绑定 localhost 端口（`operation not permitted`），未能执行浏览器端到端或真实外部搜索验证。以上手动步骤用于联网环境验收。

`match_source` 在当前检出的模型/存储中未定义；API 兼容读取该属性，缺失时返回 null。没有修改评分引擎或从评分文字猜测来源。warnings/degraded 从本次服务会话的 jobs 回填到搜索详情，服务重启后不保留这些任务元数据。

## 本次测试结果原文

### python -m unittest discover -s tests

```text
...................................
----------------------------------------------------------------------
Ran 35 tests in 0.922s

OK
```

### node --test tests/webapp/*.test.mjs

```text
✔ plan sends the real clarification answers (4.163584ms)
✔ folder and lookup query strings preserve special characters (0.770541ms)
✔ SSE displays actual engine stages and resolves only on terminal event (0.497083ms)
✔ disconnect keeps polling, avoids replay duplicates and survives another network failure (2.734584ms)
✔ server restart gives an actionable missing-job error (0.826916ms)
✔ job failure and SSE constructor failure are both handled (1.015292ms)
✔ clarification answers survive regeneration and reach the launched search with edited criteria (6.224292ms)
✔ failed criteria regeneration prevents launching stale criteria (1.1795ms)
✔ star callback works after currentTarget is invalidated by dispatch (1.231ms)
✔ switching searches clears artifacts and late results cannot overwrite the new view (1.057ms)
✔ page boot attaches to running jobs before store-backed history can block (1.148166ms)
ℹ tests 11
ℹ suites 0
ℹ pass 11
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 81.241
```

### JavaScript 语法检查

```text
node --check tests/webapp/api.test.mjs: exit 0
node --check tests/webapp/app.test.mjs: exit 0
node --check webapp/js/api.js: exit 0
node --check webapp/js/app.js: exit 0
```

`git diff --check`：无输出，退出码 0。
