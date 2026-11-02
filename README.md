# deep-literature-search

An Undermind-style AI literature deep-search agent.

**Goal:** given a natural-language research question, iteratively search the
scientific literature, evaluate relevance paper by paper, expand the search
along citation trails until it converges, and produce a report whose claims
are traceable to specific papers.

This repository starts as a clean-room reimplementation study: first a
black-box behavior specification of the reference product (Undermind), then
an MVP built on public APIs.

## Data sources (planned)

- Semantic Scholar Graph API — 200M+ papers, citation graph (references / citations)
- OpenAlex — works, concepts, authors
- Crossref — DOI metadata
- arXiv / PubMed Central — full texts where open access

## Core loop (planned)

1. **Intake** — take the research question; ask clarifying follow-ups to pin down scope.
2. **Expand** — turn the goal into multiple diverse searches (not just the user's keywords).
3. **Evaluate** — LLM reads titles/abstracts (later full texts) and scores relevance to the specific question.
4. **Snowball** — expand from the best papers along citation trails (cited-by and references).
5. **Converge** — repeat 2–4 until new rounds stop adding relevant papers.
6. **Report** — structured synthesis with in-line citations back to source papers, plus an extractable paper table.

## Usage

```bash
pip install -e .

# Interactive deep search: brainstorming questions → search-criteria draft
# → launch → iterative search with citation snowballing → ranked results
dls search "Methods for automatically generating natural-language descriptions of tabular datasets using large language models"

dls trace 10.1145/3786626         # expand from ONE seed paper along its citation graph
                                  # (references + citations), score and summarize the neighbourhood
dls report 1                      # cited Markdown report for search #1
dls ask 1 "which papers use table profiling?"     # follow-up chat over the results
dls extract 1 --columns paper,year,method,"output type"   # comparison table
dls papers --starred              # browse the library
dls import-doi 10.1038/s41586-025-10072-4
dls import-bibtex refs.bib        # Zotero users: export BibTeX, then this
dls export 1 --format bibtex --out refs.bib
dls updates 1                     # check search #1 for newly published papers
dls serve --port 8765             # local web UI (Searches / Papers / Updates / reports)
dls api --port 8000               # HTTP API + web workbench in webapp/ (needs: pip install -e ".[api]")
dls mcp                           # MCP server on stdio (deep_search, search_papers, get_paper)
python -m unittest discover -s tests
```

Data lives in `~/.dls/` (override with `DLS_HOME`).

### Configuration (environment variables)

| Variable | Effect |
|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | Strongly recommended. Without it, Semantic Scholar's shared anonymous pool throttles hard (frequent 429s); a free key gives a dedicated 1 req/s |
| `OPENALEX_API_KEY` | OpenAlex moved to keyed, credit-based access in 2026; without a key the secondary channel may be unavailable and the engine degrades gracefully |
| `LLM_API_KEY` (+ `LLM_BASE_URL`, `LLM_MODEL`) | Any OpenAI-compatible endpoint. Enables generated brainstorming/criteria, LLM-judged MATCH scores, synthesized reports, extraction and Q&A. Without it, a deterministic heuristic backend runs the same pipeline offline |
| `DLS_LLM_BACKEND` | `auto` (default) \| `gemini-connector` \| `heuristic`. `gemini-connector` routes LLM calls through a locally registered Gemini connector helper (`DLS_GEMINI_HELPER`), so the API key never touches this process; default model becomes `gemini-3.8-flash` |
| `CROSSREF_EMAIL` | Polite-pool contact for Crossref |

## Docs

- [docs/behavior-spec.md](docs/behavior-spec.md) — black-box behavior specification of Undermind (v0.2, measured with a logged-in free account: a complete real search, report generation and table extraction).
- [docs/research-landscape.md](docs/research-landscape.md) — open-source projects surveyed (CiteLens, OpenScholar, Ai2 Scholar QA, PaperQA2, STORM, GPT-Researcher, LitLLM, ASReview) and the resulting tech choices.
- [docs/design.md](docs/design.md) — feature-parity matrix vs Undermind and the architecture.

## Status

- 2026-11-02: project seeded; behavior spec v0.1 from public sources.
- 2026-11-02: behavior spec **v0.2 measured edition** (logged-in run: 52 papers, AutoDDG top match at 100%).
- 2026-11-02: **v0.1 implementation** — full pipeline working: brainstorming → criteria → multi-source search (Semantic Scholar + OpenAlex + Crossref fallback) → MATCH scoring → citation snowballing with convergence → capture–recapture discovery estimate → cited reports, chat extraction, follow-up Q&A, library with stars/folders, DOI/BibTeX/PDF import, CSV/BibTeX/RIS export, update checks, web UI, MCP server. 10 offline unit tests pass; a live smoke run (Crossref channel, while S2/OpenAlex anonymous pools were throttling) found real on-topic papers end-to-end.
- 2026-11-02: **Gemini connector LLM backend** (`DLS_LLM_BACKEND=gemini-connector`) — the same prompts/scoring/report code, transported through a credential-isolated helper; verified live against a free-tier Gemini key (first head-to-head vs the heuristic backend: two genuinely model-judged papers, incl. one relevant paper the lexical backend missed entirely).
- 2026-11-02: **HTTP API + web workbench (v0.2)** — `dls api` serves a FastAPI backend (`dls/api.py`): minute-long operations (search / trace / report / extract / updates) run as background jobs with a Server-Sent-Events progress stream; searches, papers, files, import/export are plain REST. The frontend in `webapp/` is a dependency-free ES-module SPA (no build step): three-pane workbench — search history & files · results table with MATCH scores and provenance · progress/report/table/ask tabs. 23 tests pass (6 new API tests, fully offline); a live smoke run completed a real search through the API end-to-end.
