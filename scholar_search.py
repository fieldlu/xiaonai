#!/usr/bin/env python3
"""XiaoNai Scholar Search v2 — OpenAlex Direct.

High-quality academic paper search with abstracts, citations, and journal info.

Usage:
  python3 scholar_search.py search <query> [--rows N]
  python3 scholar_search.py health

JSON output format (backward compatible with v1):
  {
    "query": "...", "total": N,
    "results": [{
      "title", "authors": [...], "year", "source": "OpenAlex",
      "doi", "url", "citations": N,
      "abstract": "...", "journal": "...", "journal_type": "..."
    }],
    "sources": ["OpenAlex"]
  }
"""
import sys, json, urllib.request, urllib.error, urllib.parse
from urllib.parse import quote

API_BASE = "https://api.openalex.org"
USER_AGENT = "XiaoNaiBot/1.0 (mailto:xiaonai@example.com)"
TIMEOUT = 20


def search_openalex(query: str, rows: int = 10) -> dict:
    """Search OpenAlex API and return parsed results with abstracts."""
    url = (f"{API_BASE}/works?search={quote(query)}"
           f"&per_page={min(rows, 50)}"
           # OpenAlex defaults to relevance sort when no sort param given
           f"&select=id,title,authorships,publication_year,doi,"
           f"abstract_inverted_index,primary_location,cited_by_count")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    data = json.loads(resp.read().decode())

    total = data.get("meta", {}).get("count", 0)
    works = data.get("results", [])

    results = []
    for w in works:
        # ── Abstract: reconstruct from inverted index ──
        abstract = ""
        inv = w.get("abstract_inverted_index")
        if inv:
            words = []
            for token, positions in inv.items():
                for pos in positions:
                    words.append((pos, token))
            words.sort()
            abstract = " ".join(w for _, w in words)

        # ── Authors: clean up ──
        raw_authors = []
        for a in w.get("authorships", []):
            author_obj = a.get("author") or {}
            name = (author_obj.get("display_name") or "").strip()
            if name and not any(
                kw in name for kw in ["大学", "学院", "研究所", "中心", "实验室", "公司"]
            ):
                raw_authors.append(name)

        # ── Source / Journal ──
        loc = w.get("primary_location") or {}
        source = loc.get("source") or {}
        journal = source.get("display_name", "") if source else ""
        journal_type = source.get("type", "") if source else ""

        # ── DOI ──
        doi_raw = (w.get("doi") or "").strip()
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        # ── URL ──
        url = f"https://doi.org/{doi}" if doi else w.get("id", "")

        year = w.get("publication_year") or ""
        citations = w.get("cited_by_count") or 0

        results.append({
            "title": w.get("title", "?"),
            "authors": raw_authors,
            "year": str(year),
            "source": "OpenAlex",
            "doi": doi,
            "url": url,
            "citations": citations,
            "abstract": abstract,
            "journal": journal,
            "journal_type": journal_type,
        })

        if len(results) >= rows:
            break

    return {
        "query": query,
        "total": total,
        "results": results,
        "sources": ["OpenAlex"],
    }


def health_check() -> dict:
    """Check if OpenAlex API is reachable."""
    try:
        search_openalex("test", rows=1)
        return {"status": "ok", "source": "OpenAlex"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        rows = 10
        for i, a in enumerate(sys.argv[3:], 3):
            if a == "--rows" and i + 1 < len(sys.argv):
                rows = int(sys.argv[i + 1])

        if not query:
            print("Usage: scholar_search.py search <query> [--rows N]")
            sys.exit(1)

        try:
            result = search_openalex(query, rows=rows)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except urllib.error.HTTPError as e:
            print(json.dumps({"error": f"HTTP {e.code}: {e.reason}", "query": query}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": f"Network: {e.reason}", "query": query}))
            sys.exit(1)
        except Exception as e:
            print(json.dumps({"error": str(e), "query": query}))
            sys.exit(1)

    elif cmd == "health":
        result = health_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print("Unknown command:", cmd)
        sys.exit(1)


if __name__ == "__main__":
    main()
