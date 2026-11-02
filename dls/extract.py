"""Chat-driven table extraction: name the columns, get a table."""

from __future__ import annotations

from .llm import HeuristicLLM
from .store import Store


def extract_table(
    store: Store,
    search_id: int,
    columns: list[str],
    llm: HeuristicLLM,
    top_n: int = 10,
) -> str:
    papers = store.search_papers(search_id, included_only=True)[:top_n]
    if not papers:
        return "(no included papers in this search)"
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for p in papers:
        row = llm.extract_row(p, columns)
        cells = [str(row.get(c, "—")).replace("|", "/").replace("\n", " ") for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(f"Only papers from search #{search_id} were included; no external sources were added.")
    return "\n".join(lines)
