"""Local web UI (stdlib http.server only).

Pages: home (searches + library), search detail (ranked papers table),
library, report view (rendered HTML), updates. A search form runs the
engine synchronously — fine for a local single-user tool.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .report import generate_report, markdown_to_html

_CSS = (
    "body{font-family:system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
    "table{border-collapse:collapse;width:100%;font-size:.92em}td,th{border:1px solid #ddd;padding:.3rem .5rem;text-align:left}"
    "a{color:#0b5cad;text-decoration:none}a:hover{text-decoration:underline}"
    "input[type=text]{width:70%;padding:.4rem}button{padding:.4rem .9rem}"
    ".meta{color:#666;font-size:.9em}"
)


def _page(title: str, inner: str) -> bytes:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
        "<nav><a href='/'>Searches</a> · <a href='/papers'>All Papers</a> · "
        "<a href='/updates'>Updates</a></nav><hr>"
        + inner
        + "</body></html>"
    ).encode("utf-8")


def serve(ctx, port: int = 8765) -> None:
    store = ctx.store

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, body: bytes, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/":
                    return self._home()
                if path == "/papers":
                    return self._papers()
                if path == "/updates":
                    return self._updates()
                if path.startswith("/search/"):
                    return self._search(int(path.split("/")[2]))
                if path.startswith("/report/"):
                    return self._report(int(path.split("/")[2]))
                self._send(_page("404", "<h1>Not found</h1>"), 404)
            except Exception as exc:
                self._send(_page("Error", f"<h1>Error</h1><p>{html.escape(str(exc))}</p>"), 500)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/run-search":
                self._send(_page("404", "<h1>Not found</h1>"), 404)
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            question = (form.get("question") or [""])[0].strip()
            if not question:
                self._send(_page("Search", "<p>Please enter a question.</p>"))
                return
            criteria = ctx.engine.build_criteria(question, {})
            outcome = ctx.engine.run(question, criteria, per_query=30, max_rounds=1)
            self.send_response(303)
            self.send_header("Location", f"/search/{outcome.search_id}")
            self.end_headers()

        # -- pages ---------------------------------------------------------
        def _home(self):
            rows = []
            for s in store.list_searches():
                c = s["counts"]
                rows.append(
                    f"<tr><td><a href='/search/{s['id']}'>#{s['id']}</a></td>"
                    f"<td>{html.escape(s['question'])}</td>"
                    f"<td>{c.get('found', '?')} found · {c.get('with_full_text', '?')} full text · {c.get('excluded', '?')} excluded</td>"
                    f"<td><a href='/report/{s['id']}'>Report</a></td></tr>"
                )
            inner = (
                "<h1>Deep literature search</h1>"
                "<form method='post' action='/run-search'>"
                "<input type='text' name='question' placeholder='Describe your research question…'>"
                "<button type='submit'>Deep search</button></form>"
                "<p class='meta'>Searches run synchronously and can take a few minutes.</p>"
                "<h2>Searches</h2><table><tr><th>ID</th><th>Question</th><th>Results</th><th></th></tr>"
                + "".join(rows)
                + "</table>"
            )
            self._send(_page("Searches", inner))

        def _search(self, search_id: int):
            s = store.get_search(search_id)
            if not s:
                self._send(_page("404", "<h1>Search not found</h1>"), 404)
                return
            papers = store.search_papers(search_id, included_only=False)
            rows = []
            for p in papers:
                inc = (p.match or 0) >= 55
                rows.append(
                    f"<tr><td>{html.escape(p.key or '')}</td><td>{p.year or ''}</td>"
                    f"<td>{p.citations_per_year():.1f}</td><td>{p.match if p.match is not None else ''}</td>"
                    f"<td>{html.escape(p.title)}</td>"
                    f"<td>{'included' if inc else 'excluded'}</td></tr>"
                )
            cov = ""
            if s["coverage"]:
                cov = f"<p class='meta'>Discovery estimate: ≈{s['coverage']['estimated_coverage'] * 100:.0f}% coverage of ~{s['coverage']['estimated_total_relevant']} relevant papers ({html.escape(s['coverage']['method'])}).</p>"
            inner = (
                f"<h1>Search #{search_id}</h1><p>{html.escape(s['question'])}</p>{cov}"
                "<table><tr><th>KEY</th><th>Year</th><th>Cit/yr</th><th>MATCH</th><th>Title</th><th>Status</th></tr>"
                + "".join(rows)
                + "</table>"
            )
            self._send(_page(f"Search #{search_id}", inner))

        def _papers(self):
            papers = store.list_papers()
            rows = [
                f"<tr><td>{'★' if getattr(p, 'starred', False) else ''}</td>"
                f"<td>{html.escape(p.key or '')}</td><td>{p.year or ''}</td>"
                f"<td>{html.escape(p.title)}</td><td>{html.escape(p.venue or '')}</td>"
                f"<td>{html.escape(getattr(p, 'folder', None) or '')}</td></tr>"
                for p in papers
            ]
            inner = (
                "<h1>All Papers</h1><table><tr><th></th><th>KEY</th><th>Year</th><th>Title</th><th>Venue</th><th>Folder</th></tr>"
                + "".join(rows)
                + "</table>"
            )
            self._send(_page("All Papers", inner))

        def _updates(self):
            ups = store.list_updates()
            rows = [
                f"<tr><td>search #{u['search_id']}</td><td>{html.escape(u['key'] or '')}</td>"
                f"<td>{html.escape(u['title'])}</td><td>{u['year'] or ''}</td></tr>"
                for u in ups
            ]
            inner = (
                "<h1>Search updates</h1><p class='meta'>Your searches are checked for new papers; "
                "new matches appear here. Run <code>dls updates &lt;id&gt;</code> to check now.</p>"
                "<table><tr><th>Search</th><th>KEY</th><th>Title</th><th>Year</th></tr>"
                + "".join(rows)
                + "</table>"
            )
            self._send(_page("Updates", inner))

        def _report(self, search_id: int):
            # Reuse an existing report file for this search if present, else generate.
            files = store.list_files()
            content = None
            file_id = None
            search = store.get_search(search_id)
            if search:
                name = search["question"][:60].strip()
                for f in files:
                    if f["kind"] == "report" and f["name"] == name:
                        full = store.get_file(f["id"])
                        if full:
                            content, file_id = full["content"], f["id"]
                        break
            if content is None:
                file_id, content = generate_report(store, search_id, ctx.llm)
            self._send(markdown_to_html(content, title=f"Report #{search_id}").encode("utf-8"))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Web UI at http://127.0.0.1:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
