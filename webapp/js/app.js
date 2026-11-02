// Deep Literature Search — web workbench.
// Layout: searches/files (left) · results table (center) ·
// progress / report / table / ask tabs (right). Talks to dls/api.py.

import { api, watchJob } from "./api.js";

/* ------------------------------------------------------------------ */
/* tiny markdown renderer (escape first, then a safe subset)           */
/* ------------------------------------------------------------------ */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<![*\w])\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[([A-Z][A-Za-zÀ-ÿ'-]*\d{2}[a-z]?)\]/g, '<span class="cite">[$1]</span>');
}

export function renderMarkdown(md) {
  const lines = String(md ?? "").split("\n");
  const out = [];
  let i = 0;
  let listOpen = false;
  const closeList = () => { if (listOpen) { out.push("</ul>"); listOpen = false; } };
  while (i < lines.length) {
    const line = lines[i];
    // table block
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      closeList();
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
      out.push("<table><thead><tr>" + head.map((h) => `<th>${inline(h)}</th>`).join("") + "</tr></thead><tbody>");
      for (const r of rows) out.push("<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      out.push("</tbody></table>");
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { if (!listOpen) { out.push("<ul>"); listOpen = true; } out.push(`<li>${inline(li[1])}</li>`); i++; continue; }
    closeList();
    if (line.trim() === "") { i++; continue; }
    if (/^\s*(-{3,}|_{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  closeList();
  return out.join("\n");
}

/* ------------------------------------------------------------------ */
/* state + element helpers                                             */
/* ------------------------------------------------------------------ */
const $ = (id) => document.getElementById(id);
const state = { searchId: null, search: null, tab: "progress", view: 0, jobs: new Map(), plannedQuestion: null };
function notify(message) {
  $("notice").textContent = message;
  $("notice").classList.remove("hidden");
}
// Central error boundary for async UI actions, including requests before a job exists.
window.addEventListener("unhandledrejection", e => { e.preventDefault(); notify(e.reason?.message || String(e.reason)); });
function clearInspector() {
  $("report-view").innerHTML = '<p class="muted">当前检索尚未打开报告。</p>';
  $("table-view").innerHTML = '<p class="muted">当前检索尚未打开表格。</p>';
  $("ask-log").innerHTML = '<p class="muted">基于当前检索的入选论文提问。</p>';
  $("extract-bar").classList.add("hidden");
  $("ask-input").value = "";
  $("paper-detail").innerHTML = '<p class="muted">选择论文查看摘要、引用和发现路径。</p>';
}
function safeUrl(url) {
  try { const u = new URL(url); return ['https:', 'http:'].includes(u.protocol) ? esc(u.href) : ''; } catch { return ''; }
}
function paperDetails(p) {
  const link = (url, label) => safeUrl(url) ? `<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '';
  $("paper-detail").innerHTML = `<div class="eyebrow">PAPER DETAILS · ${esc(p.key || p.paper_id)}</div>
    <h2>${esc(p.title)}</h2><p class="muted">${esc((p.authors || []).join(', '))} · ${esc(p.year ?? '年份未知')} · ${esc(p.venue || '')}</p>
    <div class="detail-meta"><span>被引 ${esc(p.citation_count ?? 0)}</span><span>参考文献 ${esc(p.reference_count ?? 0)}</span></div>
    <p>${link(p.doi ? 'https://doi.org/' + p.doi : null, 'DOI: ' + p.doi)} ${link(p.open_access_pdf, '开放 PDF')} ${link(p.url, '原始记录')}</p>
    <h3>摘要</h3><p class="abstract-text">${esc(p.abstract || '来源未提供摘要')}</p>
    ${p.tldr ? `<h3>简述</h3><p>${esc(p.tldr)}</p>` : ''}
    <h3>评分与溯源</h3><p>MATCH ${esc(p.match ?? '—')} · ${esc(p.match_source || '来源未记录')}</p>
    <p>${esc(p.match_reason || '无评分说明')}</p><p>发现路径：${esc(p.found_via || '未记录')}</p><p>数据来源：${esc(p.source || '未记录')}</p>
    <label>收藏夹 <input id="paper-folder" value="${esc(p.folder || '')}" placeholder="例如：综述 / 待读"></label>
    <button id="save-folder" class="btn">保存收藏夹</button>`;
  $("save-folder").addEventListener('click', async e => {
    const btn = e.currentTarget;
    const folder = $("paper-folder").value.trim() || null;
    btn.disabled = true;
    try { await api.setFolder(p.db_id, folder); p.folder = folder; notify('收藏夹已保存'); }
    finally { btn.disabled = false; }
  });
  switchTab('paper');
}

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  for (const page of ["progress", "paper", "report", "table", "ask"]) {
    $("tab-" + page).classList.toggle("hidden", page !== name);
  }
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

function scoreClass(m) { return m >= 80 ? "high" : m >= 55 ? "mid" : "low"; }

// Run a job: stream progress into the log, return the final event.
function searchWarnings(result) {
  const stop = result?.stop_reason ? `<p class="muted">停止原因：${esc(result.stop_reason)}</p>` : "";
  if (!result?.degraded && !result?.warnings?.length) return stop;
  return stop + `<div role="alert" class="status-error"><strong>${result.degraded ? "⚠ 部分数据源失败，结果可能不完整，未收敛" : "⚠ 检索警告"}</strong>` +
    `<ul>${(result.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
}

async function runJob(jobId, label) {
  if (state.jobs.has(jobId)) return state.jobs.get(jobId);
  switchTab("progress");
  if (!$("job-log").querySelector(".job-head")) $("job-log").innerHTML = "";
  const head = document.createElement('div');
  head.className = 'job-head'; head.textContent = `${label} · ${jobId}`;
  const connection = document.createElement('div'); connection.className = 'muted';
  const events = document.createElement('div');
  $("job-log").append(head, connection, events);
  const task = (async () => {
    try {
      const final = await watchJob(jobId, ev => {
        const row = document.createElement('div'); row.className = 'ev';
        row.innerHTML = `<span class="stage">${esc(ev.stage)}</span><span class="detail">${esc(ev.detail)}</span>`;
        events.appendChild(row);
      }, message => { connection.textContent = message; });
      connection.textContent = final.type === 'done' ? (final.result?.degraded ? '⚠ 完成，结果不完整' : '✓ 完成') : `失败：${final.error || '未知错误'}`;
      connection.className = final.type === 'done' && !final.result?.degraded ? 'status-done' : 'status-error';
      if (final.type === 'error') notify(final.error || '任务失败');
      const diagnostics = document.createElement('div');
      diagnostics.innerHTML = searchWarnings(final.result);
      events.appendChild(diagnostics);
      if (final.result?.degraded) notify('本次任务处于降级状态，请查看进度与警告。');
      return final;
    } catch (err) { connection.textContent = err.message; connection.className = 'status-error'; throw err; }
    finally { state.jobs.delete(jobId); }
  })();
  state.jobs.set(jobId, task);
  return task;
}
async function showArtifact(fileId, kind, view) {
  const f = await api.getFile(fileId);
  await refreshFiles();
  if (view !== state.view) { notify('后台文件已生成，可从左侧文件列表打开。'); return; }
  $(kind + '-view').innerHTML = renderMarkdown(f.content);
  switchTab(kind);
}
async function recoverJobs() {
  const jobs = await api.listJobs();
  const active = jobs.filter(j => ["queued", "running"].includes(j.status));
  for (const job of jobs.filter(j => ['queued', 'running'].includes(j.status))) {
    const view = state.view;
    (async () => {
      const final = await runJob(job.id, `恢复任务 · ${job.kind}${job.search_id ? ' · 检索 #' + job.search_id : ''}`);
      await refreshSearches();
      if (final.type !== 'done') return;
      if (final.result?.search_id && view === state.view) await openSearch(final.result.search_id);
      if (final.result?.file_id) {
        await refreshFiles();
        if (state.searchId === job.search_id) await showArtifact(final.result.file_id, job.kind === 'extract' ? 'table' : 'report', state.view);
      }
    })().catch(e => notify(e.message));
  }
  return active.length;
}

/* ------------------------------------------------------------------ */
/* searches list + detail                                              */
/* ------------------------------------------------------------------ */
async function refreshSearches() {
  const searches = await api.listSearches();
  const list = $("search-list");
  list.innerHTML = searches.length ? "" : '<p class="muted">还没有检索记录。</p>';
  for (const s of searches) {
    const div = document.createElement("div");
    div.tabIndex = 0;
    div.addEventListener("keydown", e => { if (e.key === "Enter") openSearch(s.id); });
    div.className = "search-item" + (s.id === state.searchId ? " active" : "");
    const found = s.counts?.found ?? "?";
    const date = s.created_at ? new Date(s.created_at * 1000).toLocaleDateString() : "";
    div.innerHTML = `<div class="q">${esc(s.question)}</div><div class="m">#${s.id} · ${found} 篇入选 · ${esc(date)}</div>`;
    div.addEventListener("click", () => openSearch(s.id));
    list.appendChild(div);
  }
}

async function refreshFiles() {
  const files = await api.listFiles();
  const list = $("file-list");
  list.innerHTML = files.length ? "" : '<p class="muted">还没有文件。</p>';
  for (const f of files) {
    const div = document.createElement("div");
    div.className = "file-item";
    div.innerHTML = `<span class="kind">${esc(f.kind)}</span>${esc(f.name)}`;
    div.addEventListener("click", () => openFile(f));
    list.appendChild(div);
  }
}

async function openFile(meta) {
  const view = state.view;
  const f = await api.getFile(meta.id);
  if (view !== state.view) return;
  if (f.kind === "table") {
    $("table-view").innerHTML = renderMarkdown(f.content);
    $("extract-bar").classList.remove("hidden");
    switchTab("table");
  } else {
    $("report-view").innerHTML = renderMarkdown(f.content);
    switchTab("report");
  }
}

function paperRow(p, mode) {
  const tr = document.createElement("tr");
  tr.className = "paper-row";
  const first = mode === "library"
    ? `<span class="key">${esc(p.key || "")}</span>`
    : `<span class="score ${scoreClass(p.match ?? 0)}">${p.match != null ? Number(p.match).toFixed(0) : "–"}</span><div class="score-source">${esc(p.match_source || "来源未记录")}</div>`;
  const titleLink = esc(p.title);
  const authors = (p.authors || []).slice(0, 4).join(", ") + ((p.authors || []).length > 4 ? " et al." : "");
  const via = p.found_via && p.found_via !== "search" ? `<span class="via">← ${esc(p.found_via)}</span>` : "";
  const fulltext = mode === "search" && p.open_access_pdf
    ? `<button class="fulltext-btn">读取全文</button> <span class="fulltext-status" role="status"></span>` : "";
  const pdf = p.open_access_pdf ? ` · <a href="${safeUrl(p.open_access_pdf)}" target="_blank" rel="noopener">PDF</a>` : "";
  tr.innerHTML = `
    <td>${first}</td>
    <td>
      <div class="paper-title">${titleLink}${via}</div>
      <div class="paper-sub">${esc(authors)} · ${p.year ?? "n.d."} · ${esc(p.venue || "")}${pdf} ${fulltext}</div>
      ${p.match_reason ? `<div class="paper-reason">${esc(p.match_reason)}</div>` : ""}
    </td>
    <td>${p.citations_per_year ?? ""}</td>
    <td><button class="star-btn ${p.starred ? "on" : ""}" title="收藏">★</button></td>`;
  const readButton = tr.querySelector(".fulltext-btn");
  if (readButton) {
    const status = tr.querySelector(".fulltext-status");
    const updateStatus = () => {
      status.textContent = p.fulltext_status === 'ok' ? '全文已读取' :
        p.fulltext_status === 'failed' ? `读取失败：${p.fulltext_error || '原因未记录'}` : '全文未读取';
      readButton.disabled = p.fulltext_status === 'ok';
    };
    updateStatus();
    const searchId = state.searchId;
    readButton.addEventListener('click', async () => {
      readButton.disabled = true;
      status.textContent = '正在读取全文…';
      try {
        Object.assign(p, await api.readFulltext(searchId, p.db_id));
        updateStatus();
      } catch (err) {
        status.textContent = `读取失败：${err.message}`;
        readButton.disabled = false;
      }
    });
  }
  const star = tr.querySelector(".star-btn");
  star.setAttribute('aria-label', '收藏论文');
  star.setAttribute('aria-pressed', String(!!p.starred));
  star.addEventListener("click", async e => {
    e.stopPropagation();
    const button = e.currentTarget; // Capture before await: the event is no longer dispatched afterward.
    button.disabled = true;
    try {
      const now = !p.starred;
      await api.setStar(p.db_id, now); p.starred = now;
      button.classList.toggle("on", now); button.setAttribute('aria-pressed', String(now));
    } finally { button.disabled = false; }
  });
  tr.tabIndex = 0;
  tr.addEventListener("click", e => { if (!e.target.closest('a, button')) paperDetails(p); });
  tr.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === tr) paperDetails(p); });
  return tr;
}

async function openSearch(id) {
  const view = ++state.view;
  state.searchId = id;
  state.search = null;
  clearInspector();
  $("search-detail").classList.add("hidden");
  const s = await api.getSearch(id);
  if (view !== state.view) return;
  state.search = s;
  localStorage.setItem("dls-search", String(id));
  $("search-warnings").innerHTML = searchWarnings(s);
  $("welcome").classList.add("hidden");
  $("library-view").classList.add("hidden");
  $("search-detail").classList.remove("hidden");
  $("detail-question").textContent = s.question;
  const c = s.counts || {};
  const cov = s.coverage
    ? ` · 覆盖估计 ≈${Math.round((s.coverage.estimated_coverage || 0) * 100)}%（约 ${s.coverage.estimated_total_relevant} 篇相关）`
    : "";
  $("detail-meta").innerHTML =
    `<span>入选 ${c.found ?? s.papers.length} 篇</span><span>OA PDF ${c.with_full_text ?? 0}</span>` +
    `<span>排除 ${c.excluded ?? 0}</span><span>候选 ${c.candidates ?? "?"}</span><span>${cov}</span>`;
  $("detail-criteria").innerHTML = (s.criteria || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("");
  const body = $("papers-body");
  body.innerHTML = "";
  for (const p of s.papers) body.appendChild(paperRow(p, "search"));
  $("papers-empty").classList.toggle("hidden", s.papers.length > 0);
  $("ask-log").innerHTML = '<p class="muted">基于当前检索的入选论文提问，例如：哪些用了表格画像？</p>';
  await refreshSearches();
}

/* ------------------------------------------------------------------ */
/* library view                                                        */
/* ------------------------------------------------------------------ */
async function openLibrary() {
  const view = ++state.view;
  state.searchId = null; state.search = null; clearInspector();
  $("welcome").classList.add("hidden");
  $("search-detail").classList.add("hidden");
  $("library-view").classList.remove("hidden");
  const papers = await api.listPapers($("chk-starred").checked, $("folder-filter").value.trim());
  if (view !== state.view) return;
  $("library-count").textContent = `${papers.length} 篇`;
  const body = $("library-body");
  body.innerHTML = "";
  for (const p of papers) body.appendChild(paperRow(p, "library"));
}
$("btn-library").addEventListener("click", openLibrary);
$("chk-starred").addEventListener("change", openLibrary);
$("folder-apply").addEventListener('click', openLibrary);
$("paper-lookup").addEventListener('click', async () => {
  const identifier = $("lookup-input").value.trim();
  const view = state.view;
  if (identifier) {
    const paper = await api.lookupPaper(identifier);
    if (view === state.view) paperDetails(paper);
  }
});

/* ------------------------------------------------------------------ */
/* per-search actions                                                  */
/* ------------------------------------------------------------------ */
function needSearch() {
  if (!state.searchId || !state.search) { alert("先在左侧选择一个检索。"); return false; }
  return true;
}

$("btn-report").addEventListener("click", async () => {
  if (!needSearch()) return;
  const view = state.view;
  const { job_id } = await api.launchReport(state.searchId);
  const final = await runJob(job_id, "生成报告");
  if (final.type === "done") {
    await showArtifact(final.result.file_id, 'report', view);
  }
});

$("btn-extract").addEventListener("click", () => {
  if (!needSearch()) return;
  $("extract-bar").classList.remove("hidden");
  switchTab("table");
  $("extract-columns").focus();
});

$("btn-do-extract").addEventListener("click", async () => {
  if (!needSearch()) return;
  const columns = $("extract-columns").value.split(",").map((x) => x.trim()).filter(Boolean);
  if (!columns.length) { alert("至少填写一列。"); return; }
  const view = state.view;
  const { job_id } = await api.launchExtract(state.searchId, columns, 10);
  const final = await runJob(job_id, "抽取对比表");
  if (final.type === "done") {
    await showArtifact(final.result.file_id, 'table', view);
  }
});

$("btn-updates").addEventListener("click", async () => {
  if (!needSearch()) return;
  const { job_id } = await api.launchUpdates(state.searchId);
  const final = await runJob(job_id, "检查新论文");
  if (final.type === "done") {
    const fresh = final.result.new_papers || [];
    alert(fresh.length ? `发现 ${fresh.length} 篇新论文，已记录在更新里。` : "暂时没有新论文。");
  }
});

document.querySelectorAll("[data-export]").forEach((b) =>
  b.addEventListener("click", () => {
    if (!needSearch()) return;
    window.open(api.exportUrl(state.searchId, b.dataset.export), "_blank");
  })
);

async function sendAsk() {
  if (!needSearch()) return;
  if ($("btn-ask").disabled) return;
  const q = $("ask-input").value.trim();
  if (!q) return;
  $("btn-ask").disabled = true;
  $("ask-input").value = "";
  const log = $("ask-log");
  if (log.querySelector(".muted")) log.innerHTML = "";
  const u = document.createElement("div");
  u.className = "ask-msg user"; u.textContent = q; log.appendChild(u);
  const b = document.createElement("div");
  b.className = "ask-msg bot"; b.textContent = "思考中…"; log.appendChild(b);
  try {
    const { answer } = await api.ask(state.searchId, q);
    b.innerHTML = renderMarkdown(answer);
  } catch (e) {
    b.textContent = "出错：" + e.message;
  } finally { $("btn-ask").disabled = false; }
}
$("btn-ask").addEventListener("click", sendAsk);
$("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendAsk(); });

/* ------------------------------------------------------------------ */
/* dialogs: new search / trace / import                                */
/* ------------------------------------------------------------------ */
const dlgSearch = $("dlg-search");
$("btn-new-search").addEventListener("click", () => { dlgSearch.showModal(); });

function readAnswers() {
  return Object.fromEntries([...document.querySelectorAll('#ns-questions input')]
    .filter(input => input.value.trim()).map(input => [input.dataset.q, input.value.trim()]));
}
function invalidatePlan() {
  $("ns-launch").disabled = true;
  $("ns-confirm").checked = false;
}
$("ns-question").addEventListener('input', () => {
  state.plannedQuestion = null; $("ns-plan-area").classList.add('hidden');
  $("ns-questions").innerHTML = ''; $("ns-plan").textContent = '澄清并生成标准'; invalidatePlan();
});
$("ns-criteria").addEventListener('input', invalidatePlan);
$("ns-confirm").addEventListener('change', () => { $("ns-launch").disabled = !$("ns-confirm").checked; });
$("ns-questions").addEventListener('input', () => {
  state.plannedQuestion = null; invalidatePlan();
  $("ns-plan-hint").textContent = '回答已修改，请按回答重新生成标准。';
});
$("ns-plan").addEventListener("click", async () => {
  const question = $("ns-question").value.trim();
  if (!question) { notify("先写研究问题。"); return; }
  const btn = $("ns-plan");
  const answers = readAnswers();
  state.plannedQuestion = null;
  $("ns-confirm").disabled = true;
  btn.disabled = true; btn.textContent = "生成中…"; invalidatePlan();
  try {
    const { questions, criteria } = await api.plan(question, answers);
    if ($("ns-question").value.trim() !== question || JSON.stringify(readAnswers()) !== JSON.stringify(answers)) return;
    // Keep previous questions and answers even when the LLM proposes new questions.
    const allQuestions = [...new Set([...Object.keys(answers), ...questions])];
    $("ns-questions").innerHTML = allQuestions.map(q => `<label class="ns-q"><span class="qtext">${esc(q)}</span>
      <input type="text" data-q="${esc(q)}" value="${esc(answers[q] || '')}" placeholder="你的回答（可留空）"></label>`).join('');
    $("ns-criteria").value = criteria.join('\n');
    state.plannedQuestion = question;
    $("ns-plan-area").classList.remove("hidden");
    $("ns-plan-hint").textContent = Object.keys(answers).length ? '已根据回答重新生成；请审阅并确认标准。' : '回答澄清问题后重新生成，或直接审阅并确认标准。';
  } finally { btn.disabled = false; $("ns-confirm").disabled = false; btn.textContent = '按回答重新生成标准'; }
});
$("ns-launch").addEventListener("click", async () => {
  const question = $("ns-question").value.trim();
  if (state.plannedQuestion !== question || !$("ns-confirm").checked) { notify('请生成并确认最新检索标准。'); return; }
  const criteria = $("ns-criteria").value.split('\n').map(x => x.trim()).filter(Boolean);
  if (!criteria.length) { notify('至少保留一条检索标准。'); return; }
  const btn = $("ns-launch"); btn.disabled = true;
  try {
    const { job_id } = await api.launchSearch({ question, criteria, answers: readAnswers() });
    dlgSearch.close();
    const view = ++state.view; state.searchId = null; state.search = null; clearInspector();
    $("search-detail").classList.add('hidden'); $("library-view").classList.add('hidden'); $("welcome").classList.remove('hidden');
    const final = await runJob(job_id, "深度检索");
    await refreshSearches();
    if (final.type === "done" && final.result?.search_id && view === state.view) await openSearch(final.result.search_id);
  } finally { btn.disabled = false; }
});

const dlgTrace = $("dlg-trace");
$("btn-new-trace").addEventListener("click", () => dlgTrace.showModal());
$("tr-launch").addEventListener("click", async () => {
  const identifier = $("tr-seed").value.trim();
  if (!identifier) { alert("先填种子论文。"); return; }
  const question = $("tr-question").value.trim() || null;
  const view = state.view;
  const { job_id } = await api.launchTrace({ identifier, question, hops: 1 });
  dlgTrace.close();
  const final = await runJob(job_id, "引用图谱扩展");
  await refreshSearches();
  if (final.type === "done" && final.result?.search_id && view === state.view) openSearch(final.result.search_id);
});

const dlgDoi = $("dlg-doi");
$("btn-import-doi").addEventListener("click", () => dlgDoi.showModal());
$("doi-launch").addEventListener("click", async () => {
  const doi = $("doi-input").value.trim();
  if (!doi) return;
  dlgDoi.close();
  try {
    const p = await api.importDoi(doi);
    alert(`已导入 [${p.key}] ${p.title}`);
  } catch (e) {
    alert("导入失败：" + e.message);
  }
});

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */
(async function boot() {
  try {
    const h = await api.health();
    const el = $("backend-status");
    el.textContent = `后端 OK · ${h.llm_backend} · ${h.llm_model}`;
    el.classList.add("ok");
  } catch {
    $("backend-status").textContent = "后端未连接";
  }
  const recovering = await recoverJobs();
  await Promise.all([refreshSearches(), refreshFiles()]);
  const previous = localStorage.getItem('dls-search');
  if (previous && !recovering && !state.searchId) { try { await openSearch(Number(previous)); } catch (e) { notify(e.message); } }
})();

$("btn-import-bibtex").addEventListener('click', () => $("dlg-bibtex").showModal());
$("bibtex-file").addEventListener('change', async e => {
  const file = e.target.files[0];
  if (file) $("bibtex-content").value = await file.text();
});
$("bibtex-launch").addEventListener('click', async e => {
  const content = $("bibtex-content").value.trim();
  if (!content) return;
  const btn = e.currentTarget; btn.disabled = true;
  try {
    const result = await api.importBibtex(content);
    $("dlg-bibtex").close(); notify(`已导入 ${result.imported} 篇论文`); await openLibrary();
  } finally { btn.disabled = false; }
});
