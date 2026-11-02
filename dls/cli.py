"""Command-line interface: `dls`.

Examples:
    dls search "methods for generating dataset descriptions with LLMs"
    dls report 1
    dls ask 1 "which of these use table profiling?"
    dls extract 1 --columns paper,year,method,output type
    dls papers --starred
    dls import-doi 10.1145/1234567
    dls export 1 --format bibtex --out refs.bib
    dls updates 1
    dls serve --port 8765
    dls mcp
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .engine import DeepSearchEngine
from .extract import extract_table
from .importers import import_bibtex, import_doi, import_pdf
from .llm import get_llm
from .report import generate_report, papers_to_bibtex, papers_to_csv, papers_to_ris
from .store import Store
from .updates import check_updates


class Context:
    def __init__(self):
        self.config = Config.from_env()
        self.config.ensure_dirs()
        self.store = Store(self.config.db_path)
        from .clients.crossref import CrossrefClient
        from .clients.openalex import OpenAlexClient
        from .clients.semantic_scholar import SemanticScholarClient

        self.s2 = SemanticScholarClient(self.config.s2_api_key)
        self.openalex = OpenAlexClient(self.config.openalex_api_key, self.config.contact_email)
        self.crossref = CrossrefClient(self.config.contact_email)
        self.llm = get_llm(self.config)
        self.engine = DeepSearchEngine(self.s2, self.openalex, self.llm, self.store, crossref=self.crossref)


def _progress(stage: str, detail: str) -> None:
    print(f"  [{stage}] {detail}", file=sys.stderr)


def cmd_search(ctx: Context, args: argparse.Namespace) -> int:
    question = args.question
    answers: dict[str, str] = {}
    criteria: list[str]
    if args.criteria:
        criteria = [c.strip() for c in args.criteria.split(";") if c.strip()]
    else:
        questions = ctx.engine.brainstorm(question)
        if not args.yes:
            print("Before searching, a couple of quick questions (Enter to skip):")
            for q in questions:
                try:
                    ans = input(f"  {q}\n  > ").strip()
                except EOFError:
                    ans = ""
                if ans:
                    answers[q] = ans
        criteria = ctx.engine.build_criteria(question, answers)
        print("\nSearch criteria (the search draft):")
        for c in criteria:
            print(f"  - {c}")
        if not args.yes:
            try:
                go = input("Launch this search? [Y/n] ").strip().lower()
            except EOFError:
                go = "y"
            if go.startswith("n"):
                print("Aborted before launch.")
                return 0
    outcome = ctx.engine.run(
        question,
        criteria,
        answers=answers,
        project=args.project,
        per_query=args.per_query,
        max_rounds=args.rounds,
        progress=_progress,
    )
    for w in outcome.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    print(f"\n{outcome.found} papers · {outcome.with_full_text} with full text · {outcome.excluded_count} excluded")
    if outcome.coverage:
        cov = outcome.coverage
        print(
            f"Discovery estimate: ~{cov['estimated_total_relevant']} relevant papers exist; "
            f"this search found ≈{cov['estimated_coverage'] * 100:.1f}% of them "
            f"({cov['method']})."
        )
    print(f"Search id: {outcome.search_id}\n")
    for p in outcome.included[: args.show]:
        via = f"  ← {p.found_via}" if p.found_via and p.found_via != "search" else ""
        print(f"  [{p.key}] {p.match:5.1f}  {p.title} ({p.year or 'n.d.'}) — {p.citations_per_year():.1f} cit/yr{via}")
    if outcome.found > args.show:
        print(f"  … and {outcome.found - args.show} more (see: dls papers / web UI)")
    print(f"\nNext: dls report {outcome.search_id}   |   dls extract {outcome.search_id} --columns paper,year,method")
    return 0


def cmd_trace(ctx: Context, args: argparse.Namespace) -> int:
    seed = None
    stored = ctx.store.find_paper(args.identifier)
    if stored is not None:
        if stored.paper_id.startswith("doi:"):
            seed = ctx.s2.paper(f"DOI:{stored.doi}") if stored.doi else None
        else:
            seed = stored
    if seed is None and args.identifier.startswith("10."):
        try:
            seed = ctx.s2.paper(f"DOI:{args.identifier}")
        except Exception:
            seed = None
    if seed is None:
        try:
            results = ctx.s2.search(args.identifier, limit=1)
            seed = results[0] if results else None
        except Exception:
            seed = None
    if seed is None:
        print("Could not resolve that seed paper.")
        return 1
    outcome = ctx.engine.trace(
        seed, question=args.question, hops=args.hops, progress=_progress
    )
    for w in outcome.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    print(f"\n{outcome.found} connected papers · {outcome.excluded_count} excluded (search id: {outcome.search_id})\n")
    for p in outcome.included[: args.show]:
        print(f"  [{p.key}] {p.match:5.1f}  {p.title} ({p.year or 'n.d.'})  ← {p.found_via}")
    print(f"\nNext: dls report {outcome.search_id}")
    return 0


def cmd_report(ctx: Context, args: argparse.Namespace) -> int:
    file_id, md = generate_report(ctx.store, args.search_id, ctx.llm, focus=args.focus)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Report saved to file #{file_id} and {args.out}")
    else:
        print(md)
        print(f"\n(report stored as file #{file_id})", file=sys.stderr)
    return 0


def cmd_ask(ctx: Context, args: argparse.Namespace) -> int:
    papers = ctx.store.search_papers(args.search_id, included_only=True)
    if not papers:
        print("No included papers in that search yet.")
        return 1
    print(ctx.llm.answer(args.question, papers))
    return 0


def cmd_extract(ctx: Context, args: argparse.Namespace) -> int:
    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    table = extract_table(ctx.store, args.search_id, columns, ctx.llm, top_n=args.top)
    print(table)
    if args.save:
        fid = ctx.store.save_file("default", "table", f"extract-search-{args.search_id}", table)
        print(f"(saved as file #{fid})", file=sys.stderr)
    return 0


def cmd_papers(ctx: Context, args: argparse.Namespace) -> int:
    papers = ctx.store.list_papers(starred_only=args.starred, folder=args.folder)
    for p in papers:
        star = "★" if getattr(p, "starred", False) else " "
        folder = f" [{p.folder}]" if getattr(p, "folder", None) else ""
        print(f"{star} [{p.key}] {p.year or 'n.d.'}  {p.title}{folder}")
    print(f"{len(papers)} papers")
    return 0


def cmd_star(ctx: Context, args: argparse.Namespace) -> int:
    paper = ctx.store.find_paper(args.identifier)
    if not paper:
        print("Paper not found.")
        return 1
    ctx.store.set_star(getattr(paper, "db_id"), not args.off)
    print(f"{'Unstarred' if args.off else 'Starred'} [{paper.key}] {paper.title}")
    return 0


def cmd_folder(ctx: Context, args: argparse.Namespace) -> int:
    paper = ctx.store.find_paper(args.identifier)
    if not paper:
        print("Paper not found.")
        return 1
    ctx.store.set_folder(getattr(paper, "db_id"), args.folder)
    print(f"[{paper.key}] → folder '{args.folder}'")
    return 0


def cmd_import_doi(ctx: Context, args: argparse.Namespace) -> int:
    paper = import_doi(ctx.store, args.doi, ctx.crossref, ctx.s2)
    print(f"Imported [{paper.key}] {paper.title} ({paper.year or 'n.d.'})")
    return 0


def cmd_import_bibtex(ctx: Context, args: argparse.Namespace) -> int:
    n = import_bibtex(ctx.store, Path(args.path))
    print(f"Imported {n} papers from {args.path}")
    return 0


def cmd_import_pdf(ctx: Context, args: argparse.Namespace) -> int:
    paper = import_pdf(ctx.store, Path(args.path), ctx.config.files_dir)
    print(f"Imported [{paper.key}] {paper.title}")
    return 0


def cmd_export(ctx: Context, args: argparse.Namespace) -> int:
    papers = ctx.store.search_papers(args.search_id, included_only=not args.all)
    if args.format == "csv":
        out = papers_to_csv(papers)
    elif args.format == "bibtex":
        out = papers_to_bibtex(papers)
    else:
        out = papers_to_ris(papers)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"Wrote {len(papers)} papers to {args.out}")
    else:
        print(out)
    return 0


def cmd_searches(ctx: Context, args: argparse.Namespace) -> int:
    for s in ctx.store.list_searches():
        c = s["counts"]
        print(f"#{s['id']}  {s['question'][:70]}  ({c.get('found', '?')} found)")
    return 0


def cmd_updates(ctx: Context, args: argparse.Namespace) -> int:
    fresh = check_updates(ctx.store, args.search_id, ctx.s2, ctx.llm)
    if fresh:
        print(f"{len(fresh)} new papers since the original search:")
        for f in fresh:
            print(f"  [{f['key']}] {f['title']} ({f['year']}) — match {f['match']:.0f}")
    else:
        print("No new papers found for this search.")
    existing = ctx.store.list_updates(args.search_id)
    if existing:
        print(f"Total recorded updates: {len(existing)}")
    return 0


def cmd_serve(ctx: Context, args: argparse.Namespace) -> int:
    from .web import serve

    serve(ctx, port=args.port)
    return 0


def cmd_api(ctx: Context, args: argparse.Namespace) -> int:
    from .api import run_api

    run_api(port=args.port, host=args.host)
    return 0


def cmd_mcp(ctx: Context, args: argparse.Namespace) -> int:
    from .mcp_server import run_stdio

    run_stdio(ctx)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dls", description="Deep literature search (Undermind-style)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="run a deep search")
    p.add_argument("question")
    p.add_argument("--criteria", help="semicolon-separated criteria; skips brainstorming")
    p.add_argument("--yes", action="store_true", help="no interactive prompts")
    p.add_argument("--project", default="default")
    p.add_argument("--per-query", type=int, default=40)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--show", type=int, default=15)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("trace", help="expand from one seed paper along its citation graph")
    p.add_argument("identifier", help="KEY, DOI, S2 id, or a title fragment to resolve")
    p.add_argument("--question", default=None, help="score neighbours against this instead of the seed")
    p.add_argument("--hops", type=int, default=1)
    p.add_argument("--show", type=int, default=20)
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("report", help="generate a cited report for a search")
    p.add_argument("search_id", type=int)
    p.add_argument("--focus", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("ask", help="follow-up chat over a search's papers")
    p.add_argument("search_id", type=int)
    p.add_argument("question")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("extract", help="extract a comparison table")
    p.add_argument("search_id", type=int)
    p.add_argument("--columns", required=True, help="comma-separated column names")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--save", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("papers", help="list the library")
    p.add_argument("--starred", action="store_true")
    p.add_argument("--folder", default=None)
    p.set_defaults(func=cmd_papers)

    p = sub.add_parser("star", help="star a paper by KEY/DOI")
    p.add_argument("identifier")
    p.add_argument("--off", action="store_true")
    p.set_defaults(func=cmd_star)

    p = sub.add_parser("folder", help="file a paper into a folder")
    p.add_argument("identifier")
    p.add_argument("folder")
    p.set_defaults(func=cmd_folder)

    p = sub.add_parser("import-doi", help="import one paper by DOI")
    p.add_argument("doi")
    p.set_defaults(func=cmd_import_doi)

    p = sub.add_parser("import-bibtex", help="import a .bib file (also how Zotero exports arrive)")
    p.add_argument("path")
    p.set_defaults(func=cmd_import_bibtex)

    p = sub.add_parser("import-pdf", help="register a PDF in the library")
    p.add_argument("path")
    p.set_defaults(func=cmd_import_pdf)

    p = sub.add_parser("export", help="export a search's papers")
    p.add_argument("search_id", type=int)
    p.add_argument("--format", choices=["csv", "bibtex", "ris"], default="csv")
    p.add_argument("--all", action="store_true", help="include excluded papers too")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("searches", help="list past searches")
    p.set_defaults(func=cmd_searches)

    p = sub.add_parser("updates", help="check a search for new papers")
    p.add_argument("search_id", type=int)
    p.set_defaults(func=cmd_updates)

    p = sub.add_parser("serve", help="run the local web UI")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("api", help="run the HTTP API + web app (needs the api extra)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("mcp", help="run the MCP server on stdio")
    p.set_defaults(func=cmd_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = Context()
    return args.func(ctx, args)


if __name__ == "__main__":
    raise SystemExit(main())
