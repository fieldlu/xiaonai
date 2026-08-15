#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, requests, time
from bs4 import BeautifulSoup

PORT = 8899
TIMEOUT = 10

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def search_sogou(query, count=10):
    try:
        r = requests.get('https://www.sogou.com/web', params={'query': query}, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(r.content, 'html.parser')
        results = []
        for item in soup.select('.results .rb, .vrwrap, .result'):
            h3 = item.select_one('h3 a') or item.select_one('h3')
            a = item.select_one('a')
            desc = item.select_one('.str-text, .star-wiki, .space-txt, .abstract')
            if h3:
                results.append({
                    'title': h3.get_text(strip=True),
                    'url': a.get('href', '') if a else '',
                    'content': desc.get_text(strip=True)[:300] if desc else '',
                })
            if len(results) >= count:
                break
        return results
    except Exception:
        return []

def search_360(query, count=10):
    try:
        r = requests.get('https://www.so.com/s', params={'q': query}, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(r.content, 'html.parser')
        results = []
        for item in soup.select('.result, .res-list, .res-list-top'):
            h3 = item.select_one('h3 a') or item.select_one('h3')
            a = item.select_one('a')
            desc = item.select_one('.res-desc, .res-rich, .res-summary')
            if h3:
                results.append({
                    'title': h3.get_text(strip=True),
                    'url': a.get('href', '') if a else '',
                    'content': desc.get_text(strip=True)[:300] if desc else '',
                })
            if len(results) >= count:
                break
        return results
    except Exception:
        return []

def search_bing(query, count=10):
    try:
        r = requests.get('https://cn.bing.com/search', params={'q': query}, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(r.content, 'html.parser')
        results = []
        for li in soup.select('li.b_algo'):
            h2 = li.select_one('h2')
            a = li.select_one('h2 a')
            desc = li.select_one('.b_caption p, .b_lineclamp2')
            if h2:
                results.append({
                    'title': h2.get_text(strip=True),
                    'url': a.get('href', '') if a else '',
                    'content': desc.get_text(strip=True)[:300] if desc else '',
                })
            if len(results) >= count:
                break
        return results
    except Exception:
        return []

def search_all(query, count=8):
    # Sogou first (best Chinese search), then 360, then Bing
    for engine_fn in [search_sogou, search_360, search_bing]:
        results = engine_fn(query, count)
        if results:
            return results
    return []

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/search' and params.get('format') == ['json']:
            query = params.get('q', [''])[0]
            results = search_all(query)
            resp = {'query': query, 'number_of_results': len(results), 'results': results}
        else:
            resp = {'status': 'ok'}

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
