"""Deep search - query decomposition + multi-keyword parallel search + result fusion."""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Optional

from .engine import search, _filter_garbage
from .parser import fetch_page


def decompose_query(question: str) -> list[str]:
    """Break a complex question into multiple keyword-search queries.

    Generates 2-4 alternative search queries from a natural-language question
    so that each sub-query works well with keyword-based search engines.
    """
    q = question.strip()
    queries = [q]  # Always include the original

    # Remove common question words to get core keywords
    core = q
    for word in ["为什么", "为何", "是什么", "什么是", "怎么样", "如何", "怎么", "哪些",
                 "哪个", "多少", "什么原因", "怎么回事", "帮我搜", "搜索", "查一下",
                 "请", "帮我", "请问", "?", "？", "!", "！", "。", ".", "吗", "呢", "吧"]:
        core = core.replace(word, " ")
    core = re.sub(r"\s+", " ", core).strip()

    # Extract key phrases (split by spaces or punctuation)
    parts = [p.strip() for p in re.split(r"[，,、\s]+", core) if len(p.strip()) >= 2]
    
    if not parts:
        return [q]

    # Strategy 1: Full core as one query (keyword form)
    kw_query = " ".join(parts)
    if kw_query != q:
        queries.append(kw_query)

    # Strategy 2: If there are 3+ parts, make 2-keyword combos
    if len(parts) >= 3:
        # First 2 parts + last part
        queries.append(f"{parts[0]} {parts[1]} {parts[-1]}")
        # Most important looking parts (longer = more specific)
        long_parts = sorted(parts, key=len, reverse=True)[:3]
        queries.append(" ".join(long_parts))

    # Strategy 3: If parts have 2 items, just use both
    elif len(parts) == 2:
        queries.append(" ".join(parts))

    # Strategy 4: Add "最新" / "2025" / "2026" for time-sensitive queries
    time_hints = ["最新", "最近", "今年", "现在", "2025", "2026", "近日", "当前"]
    if any(h in q for h in time_hints):
        queries.append(kw_query + " 最新")

    # Strategy 5: For "why" questions, add "原因" variant
    if any(w in q for w in ["为什么", "为何", "原因", "什么原因"]):
        queries.append(kw_query + " 原因")
        queries.append(kw_query + " 分析")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for query in queries:
        if query not in seen and len(query) >= 2:
            seen.add(query)
            unique.append(query)

    return unique[:5]  # Max 5 sub-queries


def _result_key(result: dict) -> str:
    """Generate a dedup key from a search result."""
    url = result.get("url", "")
    # Normalize: strip trailing slash, www prefix
    url = re.sub(r"^https?://(www\.)?", "", url)
    url = url.rstrip("/")
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _score_result(result: dict, base_query: str) -> float:
    """Score a result for relevance ranking. Higher = more relevant."""
    score = 0.0
    title = result.get("title", "")
    url = result.get("url", "")

    # --- Keyword extraction ---
    # Extract meaningful keywords: remove common stop words and short fragments
    stop_words = {"武汉", "北京", "上海", "广州", "深圳", "中国", "美国", "日本",
                  "什么", "怎么", "为什么", "如何", "哪里", "哪些", "哪个", "多少",
                  "可以", "一下", "什么原因", "怎么回事", "吗", "呢", "吧"}

    cleaned = base_query.replace(" ", "")
    # Long ngrams (3-4 chars) - most specific, high weight
    long_ngrams = set()
    for i in range(len(cleaned) - 2):
        ng = cleaned[i:i+3]
        if ng not in stop_words:
            long_ngrams.add(ng)
    # Also try 4-grams if query is long enough
    if len(cleaned) >= 4:
        for i in range(len(cleaned) - 3):
            ng = cleaned[i:i+4]
            if ng not in stop_words:
                long_ngrams.add(ng)

    # Bigrams - medium weight, filtered
    bigrams = set()
    for i in range(len(cleaned) - 1):
        bg = cleaned[i:i+2]
        if bg not in stop_words:
            bigrams.add(bg)

    # Full keyword phrases from space-separated words
    words = [w for w in base_query.split() if len(w) >= 2 and w not in stop_words]

    title_lower = title.lower()
    url_lower = url.lower()

    # Long ngram matches (most valuable)
    long_matched = sum(1 for kw in long_ngrams if kw.lower() in title_lower)
    long_total = max(len(long_ngrams), 1)
    score += (long_matched / long_total) * 6.0

    # Bigram matches
    bi_matched = sum(1 for kw in bigrams if kw.lower() in title_lower)
    bi_total = max(len(bigrams), 1)
    score += (bi_matched / bi_total) * 3.0

    # Word matches
    word_matched = sum(1 for w in words if w.lower() in title_lower or w.lower() in url_lower)
    score += word_matched * 1.0

    # --- Title quality ---
    if len(title) > 40:
        score += 0.5
    elif len(title) > 20:
        score += 0.3
    elif len(title) < 8:
        score -= 2.0

    # Heavy penalty for domain-name-as-title
    if re.match(r"^[a-zA-Z0-9.-]+\.(com|cn|org|net|gov|edu)", title):
        score -= 5.0

    # --- URL quality ---
    good_domains = ["zhihu.com", "edu.cn", "gov.cn", "weixin.qq.com",
                    "wikipedia.org", "baike.baidu.com",
                    "people.com.cn", "xinhuanet.com", "cctv.com",
                    "sohu.com", "news.qq.com", "163.com"]
    bad_domains = ["hanyuguoxue.com", "zdic.net", "chagushici.com",
                   "xuexiha.com", "zidian.edu", "cidian.com",
                   "iciba.com", "kmcha.com", "hancibao.com"]

    for d in good_domains:
        if d in url:
            score += 0.3
            break
    for d in bad_domains:
        if d in url_lower:
            score -= 3.0
            break

    # Penalize travel/tourism URLs
    travel_kw = ["travel", "trip", "tour", "lvyou", "youji", "gonglue", "jingdian"]
    if any(kw in url_lower or kw in title_lower for kw in travel_kw):
        score -= 2.0

    # --- Engine weight ---
    engine_weights = {"sogou": 0.2, "baidu": 0.2, "cn-bing": 0.1, "ddg": 0.0}
    score += engine_weights.get(result.get("engine", ""), 0.0)

    return score


async def deep_search(question: str, n: int = 8, read_pages: int = 2) -> dict:
    """Multi-perspective deep search for complex questions.

    Decomposes the question into multiple keyword queries, searches each
    across all engines in parallel, then deduplicates and ranks results.
    """
    if not question or len(question) < 2:
        return {"results": [], "pages": [], "queries_used": [],
                "summary": "Please provide a longer question to search."}

    sub_queries = decompose_query(question)

    # Phase 1: Search all sub-queries in parallel (each engine query is parallel)
    all_tasks = []
    for sq in sub_queries:
        all_tasks.append(search(sq, n=max(n // len(sub_queries), 3), use_cache=False))

    all_results = []
    for coro in asyncio.as_completed(all_tasks):
        try:
            results = await coro
            all_results.extend(results)
        except Exception:
            pass

    # Deduplicate by normalized URL
    seen_keys = set()
    unique = []
    for r in all_results:
        key = _result_key(r)
        if key not in seen_keys:
            seen_keys.add(key)
            # Score and attach
            r["_score"] = _score_result(r, question)
            unique.append(r)

    # Filter garbage and sort by score
    unique = _filter_garbage(unique)
    unique.sort(key=lambda r: r.get("_score", 0), reverse=True)

    # Remove score field before returning
    top_results = []
    for r in unique[:n]:
        top_results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "engine": r.get("engine", ""),
        })

    # Phase 2: Fetch top pages for deeper context (optional, limited)
    pages = []
    if read_pages > 0:
        fetch_tasks = [fetch_page(r["url"]) for r in top_results[:read_pages]]
        for coro in asyncio.as_completed(fetch_tasks):
            try:
                page = await coro
                if page and not page.error:
                    pages.append(page)
            except Exception:
                pass

    return {
        "results": top_results,
        "pages": pages,
        "queries_used": sub_queries,
    }

