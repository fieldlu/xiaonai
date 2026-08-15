#!/usr/bin/env python3
"""Fetch WHUT campus page content via WebVPN.
Usage: python3 campus/campus_fetch.py <url>
Reuses campus_search.py's CAS login session.
"""
import sys, re, subprocess, os
from bs4 import BeautifulSoup

def fetch(url):
    # Reuse campus_search's authenticated session
    sys.argv = ['campus_search.py', 'dummy_keyword_for_import']
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import campus_search
    session = campus_search.session
    encode_url = campus_search.encode_url

    webvpn_url = encode_url(url)
    r = session.get(webvpn_url, timeout=15)
    r.encoding = 'utf-8'

    if r.status_code != 200:
        return f"[Error] HTTP {r.status_code}"
    if len(r.text) < 300:
        return f"[Error] Response too short"
    if '统一身份认证' in r.text or '资源访问控制' in r.text:
        # Ticket expired, re-login
        campus_search.session = campus_search.full_cas_login()
        session = campus_search.session
        r = session.get(webvpn_url, timeout=15)
        r.encoding = 'utf-8'
        if '统一身份认证' in r.text or '资源访问控制' in r.text:
            return "[Error] CAS login failed"

    soup = BeautifulSoup(r.text, 'lxml')
    for t in soup(['script', 'style', 'nav', 'footer', 'header']):
        t.decompose()

    title_tag = soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else 'No title'

    main = soup.select_one('div.article_content')
    if not main:
        main = soup.select_one('div.view.TRS_UEDITOR')
    if not main:
        main = soup.select_one('div.article')
    if not main:
        main = soup.find('div', class_=re.compile(r'content|main|article', re.I))
    if not main:
        main = soup.find('body')
    if not main:
        main = soup

    text = main.get_text(separator='\n', strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    if len(text) > 8000:
        text = text[:8000] + '\n...[truncated]'

    return f"标题: {title}\n---\n{text}"


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 campus/campus_fetch.py <url>")
        sys.exit(1)
    print(fetch(sys.argv[1]))
