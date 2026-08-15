"""Web page parser - uses Scrapling for adaptive fetching + content extraction."""

import re
from dataclasses import dataclass
from typing import Optional

MAX_SIZE = 5 * 1024 * 1024  # 5MB


@dataclass
class PageResult:
    url: str
    title: str
    extract: str
    full_text: str
    publish_date: Optional[str] = None
    source: str = "web"
    error: Optional[str] = None


def _clean_html(html: str) -> str:
    try:
        from scrapling.parser import Selector
        page = Selector(html)
        # Remove noise elements
        for tag in page.css("script, style, nav, footer, header, aside"):
            try:
                tag.remove()
            except Exception:
                pass
        text = page.get_text(separator="\n")
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
    except Exception:
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I|re.S)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.I|re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return m.group(1).strip()[:200]
    return ""


async def fetch_page(url: str, timeout: float = 12.0) -> PageResult:
    """Fetch and parse a single web page using Scrapling's adaptive Fetcher."""
    try:
        from scrapling.fetchers import Fetcher

        page = Fetcher.get(url, timeout=timeout, follow_redirects=True)

        if page.status != 200:
            return PageResult(url=url, title="", extract="",
                              full_text="", error=f"HTTP {page.status}")

        html = page.html
        if len(html) > MAX_SIZE:
            return PageResult(url=url, title="", extract="",
                              full_text="", error="Page too large")

        title = page.css_first("title")
        title_text = title.text.strip() if title else _extract_title(html)
        if not title_text:
            title_text = "No title"

        text = _clean_html(html)
        extract = text[:4000] if len(text) > 4000 else text

        return PageResult(url=url, title=title_text, extract=extract,
                          full_text=text)
    except Exception as e:
        # Fallback to httpx if Scrapling fails
        try:
            import httpx
            UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
                if resp.status_code != 200:
                    return PageResult(url=url, title="", extract="",
                                      full_text="", error=f"HTTP {resp.status_code}")
                html = resp.text
                title = _extract_title(html) or "No title"
                text = _clean_html(html)
                extract = text[:4000] if len(text) > 4000 else text
                return PageResult(url=url, title=title, extract=extract, full_text=text)
        except Exception as e2:
            return PageResult(url=url, title="", extract="", full_text="", error=str(e2))
