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
const state = { searchId: null, search: null, tab: "progress" };

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  for (const page of ["progress", "report", "table", "ask"]) {
    $("tab-" + page).classList.toggle("hidden", page !== name);
  }
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

function scoreClass(m) { return m >= 80 ? "high" : m >= 55 ? "mid" : "low"; }

function logJobEvent(jobLabel) {
  const head = document.createElement("div");
  head.className = "job-head";
  head.textContent = jobLabel + " ";
  $("job-log").appendChild(head);
  return (ev) => {
    const row = document.createElement("div");
    row.className = "ev";
    row.innerHTML = `<span class="stage">${esc(ev.stage)}</span><span class="detail">${esc(ev.detail)}</span>`;
    $("job-log").appendChild(row);
    $("tab-progress").scrollTop = $("tab-progress").scrollHeight;
    return head;
  };
}

// Run a job: stream progress into the log, return the final event.
async function runJob(jobId, label) {
  switchTab("progress");
  if ($("job-log").querySelector(".muted")) $("job-log").innerHTML = "";
  const render = logJobEvent(label);
  let headEl = null;
  const final = await watchJob(jobId, (ev) => { headEl = render(ev) || headEl; });
  const status = document.createElement("span");
  status.className = final.type === "done" ? "status-done" : "status-error";
  status.textContent = final.type === "done" ? "✓ 完成" : `✗ ${final.error || "失败"}`;
  (headEl || $("job-log")).appendChild(status);
  for (const warning of final.result?.warnings || []) {
    const row = document.createElement("div");
    row.className = "status-error";
    row.textContent = warning;
    $("job-log").appendChild(row);
  }
  return final;
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
  const f = await api.getFile(meta.id);
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
    : `<span class="score ${scoreClass(p.match ?? 0)}">${p.match != null ? p.match.toFixed(0) : "–"}</span>`;
  const scoring = p.match_source === "llm" ? "模型评分" : p.match_source === "heuristic" ? "启发式评分" : "评分来源未知";
  const titleLink = p.doi
    ? `<a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">${esc(p.title)}</a>`
    : esc(p.title);
  const authors = (p.authors || []).slice(0, 4).join(", ") + ((p.authors || []).length > 4 ? " et al." : "");
  const via = p.found_via && p.found_via !== "search" ? `<span class="via">← ${esc(p.found_via)}</span>` : "";
  const pdf = p.open_access_pdf ? ` · <a href="${esc(p.open_access_pdf)}" target="_blank" rel="noopener">PDF</a>` : "";
  tr.innerHTML = `
    <td>${first}</td>
    <td>
      <div class="paper-title">${titleLink}${via}</div>
      <div class="paper-sub">${esc(authors)} · ${p.year ?? "n.d."} · ${esc(p.venue || "")}${pdf}</div>
      ${mode === "search" ? `<div class="paper-sub">${scoring}${p.match_fallback ? ` · 降级原因：${esc(p.match_fallback)}` : ""}</div>` : ""}
      ${p.match_reason ? `<div class="paper-reason">${esc(p.match_reason)}</div>` : ""}
    </td>
    <td>${p.citations_per_year ?? ""}</td>
    <td><button class="star-btn ${p.starred ? "on" : ""}" title="收藏">★</button></td>`;
  tr.querySelector(".star-btn").addEventListener("click", async (e) => {
    e.stopPropagation();
    const now = !p.starred;
    await api.setStar(p.db_id, now);
    p.starred = now;
    e.currentTarget.classList.toggle("on", now);
  });
  tr.addEventListener("click", () => {
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("abstract-row")) { next.remove(); return; }
    const abs = document.createElement("tr");
    abs.className = "abstract-row";
    abs.innerHTML = `<td colspan="4">${esc(p.tldr || p.abstract || "（无摘要）")}</td>`;
    tr.after(abs);
  });
  return tr;
}

async function openSearch(id) {
  state.searchId = id;
  const s = await api.getSearch(id);
  state.search = s;
  $("welcome").classList.add("hidden");
  $("library-view").classList.add("hidden");
  $("search-detail").classList.remove("hidden");
  $("detail-question").textContent = s.question;
  const c = s.counts || {};
  const cov = s.coverage
    ? ` · 覆盖估计 ≈${Math.round((s.coverage.estimated_coverage || 0) * 100)}%（约 ${s.coverage.estimated_total_relevant} 篇相关）`
    : "";
  $("detail-meta").innerHTML =
    `<span>入选 ${c.found ?? s.papers.length} 篇</span><span>全文 ${c.with_full_text ?? 0}</span>` +
    `<span>排除 ${c.excluded ?? 0}</span><span>候选 ${c.candidates ?? "?"}</span><span>${cov}</span>`;
  const fallbacks = c.match_fallbacks || {};
  const fallbackCount = Object.values(fallbacks).reduce((sum, n) => sum + n, 0);
  if (fallbackCount) {
    const warning = document.createElement("span");
    warning.className = "status-error";
    warning.textContent = `MATCH 评分降级：${fallbackCount} 篇候选论文使用启发式评分（${Object.entries(fallbacks).map(([reason, n]) => `${reason}: ${n}`).join("，")}）。`;
    $("detail-meta").appendChild(warning);
  }
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
  $("welcome").classList.add("hidden");
  $("search-detail").classList.add("hidden");
  $("library-view").classList.remove("hidden");
  const papers = await api.listPapers($("chk-starred").checked);
  $("library-count").textContent = `${papers.length} 篇`;
  const body = $("library-body");
  body.innerHTML = "";
  for (const p of papers) body.appendChild(paperRow(p, "library"));
}
$("btn-library").addEventListener("click", openLibrary);
$("chk-starred").addEventListener("change", openLibrary);

/* ------------------------------------------------------------------ */
/* per-search actions                                                  */
/* ------------------------------------------------------------------ */
function needSearch() {
  if (!state.searchId) { alert("先在左侧选择一个检索。"); return false; }
  return true;
}

$("btn-report").addEventListener("click", async () => {
  if (!needSearch()) return;
  const { job_id } = await api.launchReport(state.searchId);
  const final = await runJob(job_id, "生成报告");
  if (final.type === "done") {
    await refreshFiles();
    const f = await api.getFile(final.result.file_id);
    $("report-view").innerHTML = renderMarkdown(f.content);
    switchTab("report");
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
  const { job_id } = await api.launchExtract(state.searchId, columns, 10);
  const final = await runJob(job_id, "抽取对比表");
  if (final.type === "done") {
    await refreshFiles();
    const f = await api.getFile(final.result.file_id);
    $("table-view").innerHTML = renderMarkdown(f.content);
    switchTab("table");
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
  const q = $("ask-input").value.trim();
  if (!q) return;
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
  }
}
$("btn-ask").addEventListener("click", sendAsk);
$("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendAsk(); });

/* ------------------------------------------------------------------ */
/* dialogs: new search / trace / import                                */
/* ------------------------------------------------------------------ */
const dlgSearch = $("dlg-search");
$("btn-new-search").addEventListener("click", () => { dlgSearch.showModal(); });

$("ns-plan").addEventListener("click", async () => {
  const question = $("ns-question").value.trim();
  if (!question) { alert("先写研究问题。"); return; }
  const btn = $("ns-plan");
  btn.disabled = true; btn.textContent = "生成中…";
  try {
    const { questions, criteria } = await api.plan(question, {});
    $("ns-questions").innerHTML = questions.map((q) => `
      <div class="ns-q"><div class="qtext">${esc(q)}</div>
      <input type="text" data-q="${esc(q)}" placeholder="你的回答（可留空）"></div>`).join("");
    $("ns-criteria").value = criteria.join("\n");
    $("ns-plan-area").classList.remove("hidden");
    btn.textContent = "按回答重新生成标准";
  } finally { btn.disabled = false; }
});

$("ns-launch").addEventListener("click", async () => {
  const question = $("ns-question").value.trim();
  if (!question) { alert("先写研究问题。"); return; }
  const answers = {};
  document.querySelectorAll("#ns-questions input").forEach((inp) => {
    if (inp.value.trim()) answers[inp.dataset.q] = inp.value.trim();
  });
  const criteriaText = $("ns-criteria").value.trim();
  const criteria = criteriaText ? criteriaText.split("\n").map((x) => x.trim()).filter(Boolean) : null;
  dlgSearch.close();
  const { job_id } = await api.launchSearch({ question, criteria, answers });
  const final = await runJob(job_id, "深度检索");
  await refreshSearches();
  if (final.type === "done" && final.result?.search_id) openSearch(final.result.search_id);
});

const dlgTrace = $("dlg-trace");
$("btn-new-trace").addEventListener("click", () => dlgTrace.showModal());
$("tr-launch").addEventListener("click", async () => {
  const identifier = $("tr-seed").value.trim();
  if (!identifier) { alert("先填种子论文。"); return; }
  const question = $("tr-question").value.trim() || null;
  dlgTrace.close();
  const { job_id } = await api.launchTrace({ identifier, question, hops: 1 });
  const final = await runJob(job_id, "引用图谱扩展");
  await refreshSearches();
  if (final.type === "done" && final.result?.search_id) openSearch(final.result.search_id);
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
  await refreshSearches();
  await refreshFiles();
})();
