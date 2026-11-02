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

## Docs

- [docs/behavior-spec.md](docs/behavior-spec.md) — black-box behavior specification of Undermind (v0.1, from public pages + official FAQ; live search run still pending an account).

## Status

- 2026-11-02: project seeded. Behavior spec v0.1 written from public sources.
- 2026-11-02 (later): **v0.2 measured edition** — logged in with a free
  account and ran a complete real search (tabular dataset description
  methods): 2 brainstorming questions → search criteria draft → ~6 min
  deep search → 52 papers (36 with full text, 12 excluded) → cited report
  file → chat-driven extraction table. See docs/behavior-spec.md.
  Next: agree the MVP scope, then build the skeleton.
