"""Multi-engine search - DDG + Bing parallel, SQLite cache, cross-validation."""

import asyncio
import hashlib
import json
import random
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx
import urllib.parse

from .parser import fetch_page

UAS = [
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]

CACHE_TTL_HOURS = 1


def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()[:16]


def _cache_get(query: str) -> Optional[list]:
    from src.memory.db import db
    key = _cache_key(query)
    row = db.execute(
        "SELECT results, cached_at FROM search_cache WHERE cache_key=?",
        (key,)
    ).fetchone()
    if row:
        try:
            cached_at = datetime.fromisoformat(row["cached_at"])
            if datetime.now() - cached_at < timedelta(hours=CACHE_TTL_HOURS):
                return json.loads(row["results"])
        except Exception:
            pass
    return None


def _cache_set(query: str, results: list) -> None:
    from src.memory.db import db
    db.execute(
        "INSERT OR REPLACE INTO search_cache(cache_key,results,cached_at) VALUES(?,?,?)",
        (_cache_key(query), json.dumps(results, ensure_ascii=False),
         datetime.now().isoformat())
    )
    db.commit()


async def _search_cn_bing(query: str, n: int = 5) -> list:
    """cn.bing.com search - works in China. Extracts h2 titles + nearby hrefs."""
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query)
    # Narrow academic filter - only for degree/admission queries
    academic_keywords = ["高考", "考研", "录取", "招生简章", "研究生院"]
    if any(kw in query for kw in academic_keywords) and "site:" not in query:
        url += "+site%3Aedu.cn"
    ua = random.choice(UAS)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": ua, "Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    results = []
    # Strategy 1: Find all h2 blocks, extract title text, then find nearest href
    h2_pattern = re.compile(r'<h2[^>]*>(.*?)</h2>', re.I | re.S)
    href_pattern = re.compile(r'href="(https?://[^"]+)"', re.I)

    h2_matches = list(h2_pattern.finditer(html))
    for h2_m in h2_matches:
        title = re.sub(r"<[^>]+>", "", h2_m.group(1)).strip()
        if not title or len(title) < 5:
            continue

        # Search for nearest href: first look in 500 chars before, then after
        search_start = max(0, h2_m.start() - 500)
        search_end = min(len(html), h2_m.end() + 200)
        context = html[search_start:search_end]

        # Find all hrefs in context and pick the one closest to the h2
        href_matches = list(href_pattern.finditer(context))
        if not href_matches:
            continue

        # Find href closest to h2 position in the original HTML
        h2_abs_pos = h2_m.start()
        best_href = None
        best_dist = 99999
        for href_m in href_matches:
            href_abs_pos = search_start + href_m.start()
            dist = abs(href_abs_pos - h2_abs_pos)
            if dist < best_dist:
                best_dist = dist
                best_href = href_m.group(1)

        if best_href and not any(s in best_href for s in ["bing.com", "microsoft.com", "live.com"]):
            results.append({"title": title[:150], "url": best_href, "engine": "cn-bing"})

    # Strategy 2 (fallback): If no results, try the old h2>a regex
    if not results:
        for m in re.finditer(
            r'<h2[^>]*>.*?<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html, re.I | re.S
        ):
            link = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if link and title and len(title) > 5 and not any(s in link for s in ["bing.com", "microsoft.com"]):
                results.append({"title": title[:150], "url": link, "engine": "cn-bing"})

    return results[:n]


async def _search_sogou(query: str, n: int = 5) -> list:
    """Sogou search - China-native engine, extracts h3 results."""
    url = "https://www.sogou.com/web?query=" + urllib.parse.quote(query)
    ua = random.choice(UAS)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": ua, "Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    results = []
    # Extract h3 blocks with their associated links
    h3_blocks = re.findall(
        r'<h3[^>]*>(.*?)</h3>',
        html, re.I | re.S
    )
    for h3 in h3_blocks[:n*2]:
        # Extract link from h3
        link_match = re.search(r'href="([^"]+)"', h3, re.I)
        title = re.sub(r"<[^>]+>", "", h3).strip()
        if title and len(title) > 5:
            link = link_match.group(1) if link_match else ""
            if link and link.startswith("/"):
                link = "https://www.sogou.com" + link
            if not link:
                link = "https://www.sogou.com/web?query=" + query
            if "sogou.com" not in link or link.startswith("https://www.sogou.com/link"):
                results.append({"title": title[:120], "url": link, "engine": "sogou"})
    return results[:n]



async def _search_ddg(query: str, n: int = 5) -> list:
    """DuckDuckGo Lite search - no API key needed, good EN+ZH results."""
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    ua = random.choice(UAS)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": ua, "Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    results = []
    # DDG Lite uses table rows with result-link class
    for m in re.finditer(
        r'<a[^>]*class="result-link"[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        html, re.I | re.S
    ):
        link = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if link and title and len(title) > 5:
            results.append({"title": title[:150], "url": link, "engine": "ddg"})
    
    # Fallback: try alternative regex if first pattern yields nothing
    if not results:
        for m in re.finditer(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</a>',
            html, re.I | re.S
        ):
            link = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if link and title and len(title) > 5:
                results.append({"title": title[:150], "url": link, "engine": "ddg"})
    
    return results[:n]



async def _search_baidu(query: str, n: int = 5) -> list:
    """Baidu search - best Chinese results. Uses mobile UA to avoid blocking."""
    url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)
    ua = random.choice(UAS)
    headers = {"User-Agent": ua, "Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []

    results = []
    seen = set()
    # Baidu mobile: find all links with data-showurl or direct URL
    for m in re.finditer(
        r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        html, re.I | re.S
    ):
        link = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if link and title and len(title) > 5:
            if "baidu.com" not in link and link not in seen:
                seen.add(link)
                results.append({"title": title[:150], "url": link, "engine": "baidu"})
    
    # Also try h3-based parsing as fallback
    if not results:
        for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', html, re.I|re.S):
            h3 = m.group(1)
            link_m = re.search(r'href="(https?://[^"]+)"', h3)
            title = re.sub(r"<[^>]+>", "", h3).strip()
            if title and len(title) > 5:
                link = link_m.group(1) if link_m else ""
                if link and "baidu.com" not in link and link not in seen:
                    seen.add(link)
                    results.append({"title": title[:150], "url": link, "engine": "baidu"})
    return results[:n]



def _filter_garbage(results: list) -> list:
    """Remove dictionary/character-explanation spam from results."""
    garbage_domains = [
        "hanyuguoxue.com", "zdic.net", "chagushici.com",
        "xuexiha.com", "zidian.edu", "cidian.com",
        "iciba.com", "kmcha.com", "hancibao.com",
        "gushici.net", "hgcha.com", "cidianwang.com",
        "zidianwang.com", "cizu.com", "hanzi.com",
        "qidian.com", "zidian.18dao.net", "cidian.qianp.com",
        "zdict.net", "moedict.tw",
    ]
    clean = []
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        # Skip dictionary/character sites
        if any(d in url for d in garbage_domains):
            continue
        # Skip single-character Baidu Baike entries
        if "baike.baidu.com" in url and len(title) <= 15 and (
            "汉字" in title or "的意思" in title or "的解释" in title or
            "拼音" in title or "笔顺" in title or "部首" in title or
            "漢字" in title or "怎麼" in title or "怎么写" in title or
            "汉语" in title or "词语" in title or "成语" in title or
            "字" in title and len(title) <= 4
        ):
            continue
        clean.append(r)
    return clean


async def search(query: str, n: int = 5, use_cache: bool = True) -> list:
    """Parallel multi-engine search, dedup and merge."""
    if use_cache:
        cached = _cache_get(query)
        if cached:
            return cached

    engines = [_search_baidu, _search_sogou, _search_cn_bing, _search_ddg]  # Baidu+Sogou+Bing+DDG parallel
    tasks = [e(query, n) for e in engines]
    all_results = []
    for coro in asyncio.as_completed(tasks):
        try:
            results = await coro
            all_results.extend(results)
        except Exception:
            pass

    seen = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    unique = _filter_garbage(unique)
    result = unique[:n]

    if result:
        _cache_set(query, result)
    return result


async def search_and_read(query: str, n: int = 3, read_pages: int = 3) -> dict:
    """Search + fetch page content for cross-validation."""
    results = await search(query, n=n)
    if not results:
        return {"results": [], "pages": [], "summary": "No results found."}

    pages = []
    tasks = [fetch_page(r["url"]) for r in results[:read_pages]]
    for coro in asyncio.as_completed(tasks):
        try:
            page = await coro
            if page and not page.error:
                pages.append(page)
        except Exception:
            pass

    return {"results": results, "pages": pages}
