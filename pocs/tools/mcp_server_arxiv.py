"""
pocs/tools/mcp_server_arxiv.py — arXiv deep-research MCP server (stdio).

Uma única tool, autossuficiente: numa chamada ela busca no arXiv, baixa os
papers mais relevantes e sintetiza um briefing. Diferente das tools locais do PA
(calculator, web_search/DuckDuckGo, file_reader, datetime) — é específica de
pesquisa acadêmica e resolve o problema inteiro sem encadear chamadas.

Por ser stdio, ao ser registrada num Gateway Agent ela vira um recurso
callable_by=ga_proxy: o PA não roda este comando: ele pede ao GA para executar.

Usa a lib `arxiv` (pip/uv: arxiv) — ela cuida de User-Agent, paginação,
rate-limit (~1 req/3s) e retries, então não há HTTP/XML manual aqui.

Registrar no gateway local:
  axon add mcp arxiv \\
    --stdio "python pocs/tools/mcp_server_arxiv.py" \\
    --tag deep_research \\
    --description "Deep research on arXiv: one call searches, fetches and synthesizes recent papers"

Rodar direto (debug):
  python pocs/tools/mcp_server_arxiv.py
"""

from __future__ import annotations

import arxiv
from fastmcp import FastMCP

# Cliente compartilhado: a lib aplica delay entre páginas e retries por conta própria.
_client = arxiv.Client(page_size=10, delay_seconds=3.0, num_retries=2)

mcp = FastMCP(
    name="axon-arxiv-research",
    instructions=(
        "Deep research over arXiv. Call deep_research_arxiv with a topic to get a "
        "synthesized brief plus the most relevant recent papers (title, authors, "
        "abstract, link). Use it for literature reviews and state-of-the-art surveys."
    ),
)


def _synthesize(topic: str, papers: list[dict]) -> str:
    """Monta um briefing curto a partir dos papers — sem LLM, só estrutura."""
    if not papers:
        return f"No arXiv papers found for '{topic}'."
    lines = [
        f"Deep research on '{topic}' — {len(papers)} relevant arXiv paper(s):",
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        lines.append(f"{i}. {p['title']} ({p['published']})")
        lines.append(f"   {authors}")
        lines.append(f"   {p['abstract'][:240].rstrip()}…")
        lines.append(f"   {p['url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


@mcp.tool
def deep_research_arxiv(topic: str, max_papers: int = 5) -> dict:
    """
    Run a one-shot deep research on arXiv for a topic.

    Searches arXiv, fetches the most relevant recent papers, and returns a
    synthesized brief together with structured metadata for each paper. A single
    call solves the whole task — no follow-up calls needed.

    Args:
        topic:      research topic or question, e.g. "diffusion models for audio"
        max_papers: how many papers to include (1-10, default 5)

    Returns:
        Dict with: topic, paper_count, brief (synthesized text), and papers
        (list of {title, authors, published, url, abstract}).
    """
    n = max(1, min(max_papers, 10))
    search = arxiv.Search(
        query=f"all:{topic}",
        max_results=n,
        sort_by=arxiv.SortCriterion.Relevance,
        sort_order=arxiv.SortOrder.Descending,
    )

    try:
        results = list(_client.results(search))
    except arxiv.ArxivError as exc:
        return {"topic": topic, "paper_count": 0, "brief": f"arXiv error: {exc}", "papers": []}

    papers = [
        {
            "title":     " ".join(r.title.split()),
            "authors":   [a.name for a in r.authors],
            "published": r.published.date().isoformat() if r.published else "",
            "url":       r.entry_id,
            "abstract":  " ".join(r.summary.split()),
        }
        for r in results
    ]

    return {
        "topic":       topic,
        "paper_count": len(papers),
        "brief":       _synthesize(topic, papers),
        "papers":      papers,
    }


if __name__ == "__main__":
    mcp.run()
