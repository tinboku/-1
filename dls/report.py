"""Report generation and exports (papers: CSV/BibTeX/RIS; reports: MD/HTML)."""

from __future__ import annotations

import csv
import html
import io
import re
from pathlib import Path

from .llm import HeuristicLLM
from .models import Paper
from .store import Store


# These are paper-level availability checks, not semantic entailment checks.
# Bracket tokens in Markdown links/images are not paper citations.
def verify_report(report_md: str, papers: list[Paper]) -> dict:
    body = report_md.split("\n## 证据摘录\n", 1)[0].split("\n## 证据核查\n", 1)[0]
    keys = list(dict.fromkeys(re.findall(r"(?<!!)\[([^\]\n]+)\](?!\()", body)))
    by_key = {p.key: p for p in papers if p.key}
    citations = []
    for key in keys:
        paper = by_key.get(key)
        scope, reason = "none", "unknown citation KEY"
        if paper is not None:
            scope, reason = "none", "no abstract or readable full text record"
            if paper.abstract and paper.abstract.strip():
                scope, reason = "abstract", "stored abstract available"
            if paper.fulltext_status == "ok" and paper.fulltext_path:
                try:
                    if Path(paper.fulltext_path).read_text(encoding="utf-8").strip():
                        scope, reason = "fulltext", "readable full text cache available"
                    elif scope == "none":
                        reason = "empty full text cache"
                except (OSError, UnicodeError) as exc:
                    reason = f"full text cache unavailable: {exc}; " + reason
            elif paper.fulltext_error:
                reason += f"; full text: {paper.fulltext_error}"
        citations.append({"key": key, "exists": paper is not None,
                          "traceable": scope != "none", "evidence_scope": scope, "reason": reason})
    traceable = sum(c["traceable"] for c in citations)
    return {"total": len(citations), "traceable": traceable,
            "untraceable": len(citations) - traceable, "no_citations": not citations,
            "citations": citations}


def _verification_markdown(result: dict) -> str:
    lines = ["", "## 证据核查", "",
             "仅核查 KEY 和摘要/全文记录可回查性；不代表原文在语义上支持每项主张。", ""]
    if result["no_citations"]:
        lines.append("- 无引用：未发现 [KEY] 引用，无法建立引用证据链。")
    for item in result["citations"]:
        label = "可追溯" if item["traceable"] else "不可追溯"
        lines.append(f"- [{item['key']}] {label} · evidence_scope={item['evidence_scope']} · {item['reason']}")
    return "\n".join(lines) + "\n"


def generate_report(
    store: Store,
    search_id: int,
    llm: HeuristicLLM,
    focus: str | None = None,
    project: str = "default",
) -> tuple[int, str]:
    search = store.get_search(search_id)
    if not search:
        raise ValueError(f"search {search_id} not found")
    papers = store.search_papers(search_id, included_only=True)
    from .fulltext import extract_sections

    evidence_lines = ["", "## 证据摘录", "",
                      "以下为原文摘录；离线模式按章节开头抽取，不作语义支持判断。", ""]
    for paper in papers:
        text, error = store.read_fulltext(paper)
        sections = extract_sections(text) if text else {}
        summarize = getattr(llm, "summarize_evidence", HeuristicLLM().summarize_evidence)
        paper.evidence = summarize(paper, sections, search["question"])
        if error:
            evidence_lines.append(f"- [{paper.key}] 全文降级：{error}；使用摘要（如有）。")
        for kind, item in paper.evidence.items():
            evidence_lines.append(
                f"- [{paper.key}] {kind} · evidence_scope={item['evidence_scope']} · "
                f"section={item['section'] or 'none'} · 原文：{item['quote'] or '无可用证据'}"
            )
            if item.get("reason"):
                evidence_lines.append(f"  原因：{item['reason']}")
    md = llm.write_report(search["question"], search["criteria"], papers, focus)
    verification = verify_report(md, papers)
    md += "\n" + "\n".join(evidence_lines) + "\n" + _verification_markdown(verification)
    # Title for the file: first 60 chars of the question.
    name = search["question"][:60].strip()
    file_id = store.save_file(project, "report", name, md)
    return file_id, md


# ---------------------------------------------------------------------------
# Paper exports
# ---------------------------------------------------------------------------

def _bibtex_key(paper: Paper) -> str:
    return paper.key or f"paper{paper.year or ''}"


def papers_to_bibtex(papers: list[Paper]) -> str:
    out = []
    for p in papers:
        authors = " and ".join(p.authors)
        fields = [
            f"  title = {{{p.title}}}",
            f"  author = {{{authors}}}",
        ]
        if p.year:
            fields.append(f"  year = {{{p.year}}}")
        if p.venue:
            fields.append(f"  journal = {{{p.venue}}}")
        if p.doi:
            fields.append(f"  doi = {{{p.doi}}}")
        if p.url:
            fields.append(f"  url = {{{p.url}}}")
        out.append("@article{" + _bibtex_key(p) + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(out) + "\n"


def papers_to_csv(papers: list[Paper]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["key", "year", "cit_per_year", "match", "title", "authors", "venue", "doi", "url"])
    for p in papers:
        writer.writerow([
            p.key or "",
            p.year or "",
            f"{p.citations_per_year():.1f}",
            p.match if p.match is not None else "",
            p.title,
            "; ".join(p.authors),
            p.venue or "",
            p.doi or "",
            p.url or "",
        ])
    return buf.getvalue()


def papers_to_ris(papers: list[Paper]) -> str:
    out = []
    for p in papers:
        lines = ["TY  - JOUR"]
        lines.append(f"TI  - {p.title}")
        for a in p.authors:
            lines.append(f"AU  - {a}")
        if p.year:
            lines.append(f"Y1  - {p.year}")
        if p.venue:
            lines.append(f"JO  - {p.venue}")
        if p.doi:
            lines.append(f"DO  - {p.doi}")
        if p.url:
            lines.append(f"UR  - {p.url}")
        if p.abstract:
            lines.append(f"AB  - {p.abstract[:500]}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Minimal Markdown -> HTML (enough for our own reports: headings, tables,
# lists, paragraphs, bold, inline code, links)
# ---------------------------------------------------------------------------

def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def markdown_to_html(md: str, title: str = "Report") -> str:
    lines = md.splitlines()
    body: list[str] = []
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            close_list()
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            body.append("<table><thead><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in headers) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            body.append("</tbody></table>")
            continue
        if stripped.startswith("#"):
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            body.append(f"<h{level}>{_inline(text)}</h{level}>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(stripped[2:])}</li>")
        elif stripped == "":
            close_list()
        else:
            close_list()
            body.append(f"<p>{_inline(stripped)}</p>")
        i += 1
    close_list()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.55}"
        "table{border-collapse:collapse;width:100%;font-size:.9em}td,th{border:1px solid #ccc;padding:.3rem .5rem;text-align:left}"
        "code{background:#f2f2f2;padding:0 .25rem}</style></head><body>"
        + "\n".join(body)
        + "</body></html>"
    )
