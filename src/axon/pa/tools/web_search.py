"""
pa/tools/web_search.py — DuckDuckGo Instant Answer API (sem key).
"""

from __future__ import annotations

import httpx


_DDG_URL = "https://api.duckduckgo.com/"
_TIMEOUT = 10.0


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Busca na web via DuckDuckGo Instant Answer API.

    Args:
        query:       termo de busca
        max_results: número máximo de resultados (1-10)

    Returns:
        list de dicts com keys: title, snippet, url
        Lista vazia se nenhum resultado encontrado.
    """
    max_results = max(1, min(10, max_results))

    params = {
        "q":             query,
        "format":        "json",
        "no_html":       "1",
        "no_redirect":   "1",
        "skip_disambig": "1",
    }

    try:
        resp = httpx.get(_DDG_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"DuckDuckGo request failed: {exc}") from exc

    results: list[dict] = []

    # Abstract (resultado principal)
    if data.get("AbstractText") and data.get("AbstractURL"):
        results.append({
            "title":   data.get("Heading", query),
            "snippet": data["AbstractText"],
            "url":     data["AbstractURL"],
        })

    # RelatedTopics
    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break

        # tópico direto
        if "Text" in topic and "FirstURL" in topic:
            results.append({
                "title":   topic.get("Text", "").split(" - ")[0][:80],
                "snippet": topic.get("Text", ""),
                "url":     topic.get("FirstURL", ""),
            })

        # sub-tópicos
        elif "Topics" in topic:
            for sub in topic["Topics"]:
                if len(results) >= max_results:
                    break
                if "Text" in sub and "FirstURL" in sub:
                    results.append({
                        "title":   sub.get("Text", "").split(" - ")[0][:80],
                        "snippet": sub.get("Text", ""),
                        "url":     sub.get("FirstURL", ""),
                    })

    return results[:max_results]