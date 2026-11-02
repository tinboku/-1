"""Minimal MCP server (stdio, JSON-RPC) exposing literature tools.

Implements just enough of the Model Context Protocol for clients to
initialize, list tools, and call them:

- deep_search: run the full iterative search and return a summary
- search_papers: one-shot Semantic Scholar search
- get_paper: fetch one paper by S2 id / DOI / arXiv id
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "deep_search",
        "description": "Run an Undermind-style deep literature search: multi-query retrieval, per-paper match scoring, and citation snowballing until convergence. Returns the top papers with match scores and citation keys.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "max_rounds": {"type": "integer", "default": 2},
            },
            "required": ["question"],
        },
    },
    {
        "name": "search_papers",
        "description": "One-shot Semantic Scholar paper search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_paper",
        "description": "Fetch one paper by Semantic Scholar id, DOI (DOI:...) or arXiv id (ARXIV:...).",
        "inputSchema": {
            "type": "object",
            "properties": {"paper_id": {"type": "string"}},
            "required": ["paper_id"],
        },
    },
]


def _paper_json(p) -> dict:
    return {
        "key": p.key,
        "title": p.title,
        "year": p.year,
        "authors": p.authors,
        "venue": p.venue,
        "citations": p.citation_count,
        "match": p.match,
        "doi": p.doi,
        "url": p.url,
        "abstract": (p.abstract or "")[:500],
    }


def _call_tool(ctx, name: str, arguments: dict) -> str:
    if name == "search_papers":
        papers = ctx.s2.search(arguments["query"], limit=int(arguments.get("limit", 10)))
        for p in papers:
            ctx.store.upsert_paper(p)
        return json.dumps([_paper_json(p) for p in papers], ensure_ascii=False)
    if name == "get_paper":
        paper = ctx.s2.paper(arguments["paper_id"])
        if paper is None:
            return json.dumps({"error": "not found"})
        ctx.store.upsert_paper(paper)
        return json.dumps(_paper_json(paper), ensure_ascii=False)
    if name == "deep_search":
        question = arguments["question"]
        criteria = ctx.engine.build_criteria(question, {})
        outcome = ctx.engine.run(
            question, criteria, max_rounds=int(arguments.get("max_rounds", 2)), per_query=30
        )
        return json.dumps(
            {
                "search_id": outcome.search_id,
                "found": outcome.found,
                "with_full_text": outcome.with_full_text,
                "excluded": outcome.excluded_count,
                "coverage": outcome.coverage,
                "papers": [_paper_json(p) for p in outcome.included[:25]],
            },
            ensure_ascii=False,
        )
    raise ValueError(f"unknown tool: {name}")


def run_stdio(ctx) -> None:
    out = sys.stdout

    def send(obj: dict) -> None:
        out.write(json.dumps(obj) + "\n")
        out.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "deep-literature-search", "version": "0.1.0"},
                    },
                }
            )
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                text = _call_tool(ctx, params.get("name", ""), params.get("arguments") or {})
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": text}]},
                    }
                )
            except Exception as exc:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": f"error: {exc}"}],
                            "isError": True,
                        },
                    }
                )
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif msg_id is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )
