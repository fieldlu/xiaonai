#!/usr/bin/env python3
"""WHUT 招生网全站搜索 & 校验工具.
搜索 zs.whut.edu.cn 全部通知公告页面。
与知识库交叉校验，冲突时以知识库为准。

Usage:
  python3 search/zs_whut_search.py search <keyword>     # 全站搜索
  python3 search/zs_whut_search.py list [page]           # 通知公告列表
  python3 search/zs_whut_search.py read <path>           # 阅读全文
  python3 search/zs_whut_search.py verify <keyword>      # 搜索+校验知识库
"""
import sys, re, os, urllib.request, html as html_mod
from urllib.parse import urljoin

BASE = 'https://zs.whut.edu.cn'
NOTICE_URL = BASE + '/zc/tzgg/'
KB_PATH = '/opt/xiaonai/data/knowledge'

HEADERS = {'User-Agent': 'Mozilla/5.0'}

def fetch_page(url):
    """Fetch with urllib - simple and reliable."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode('utf-8', errors='replace')
    except Exception:
        return None

def parse_notices(html):
    """Extract notice links from list page."""
    if not html: return []
    notices = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', html):
        href = m.group(1)
        text = m.group(2).strip()
        if href.startswith('./') and text and len(text) > 5:
            full_url = urljoin(NOTICE_URL, href[2:])
            notices.append((text, full_url))
    return notices

def list_notices(page=1):
    """List recent notices."""
    url = NOTICE_URL if page == 1 else NOTICE_URL + 'index_' + str(page - 1) + '.shtml'
    html = fetch_page(url)
    if not html:
        print('[X] Cannot fetch page ' + str(page))
        return
    notices = parse_notices(html)
    for title, url in notices[:30]:
        print(title)
        print('  ' + url)
        print()

def search(keyword, max_pages=32):
    """Search ALL notice pages for keyword."""
    found = []
    for page in range(1, max_pages + 1):
        url = NOTICE_URL if page == 1 else NOTICE_URL + 'index_' + str(page - 1) + '.shtml'
        html = fetch_page(url)
        if not html: break
        notices = parse_notices(html)
        for title, url in notices:
            if keyword in title:
                found.append((title, url, page))
    if found:
        for title, url, page in found:
            print(title)
            print('  ' + url + ' (第' + str(page) + '页)')
            print()
        print('共' + str(len(found)) + '条结果')
    else:
        print('[X] 未找到含"' + keyword + '"的通知')

def read_notice(path):
    """Read full content of a notice page."""
    url = urljoin(NOTICE_URL, path)
    return read_url(url)

def read_url(url):
    """Read and extract text content from a URL."""
    html = fetch_page(url)
    if not html:
        print('[X] Cannot fetch page')
        return
    # Try extracting主体 content
    body = re.search(r'<!--主体开始-->(.*?)<!--主体结束-->', html, re.DOTALL)
    content = body.group(1) if body else html
    text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    print(text)
    #

def verify(keyword):
    """Search website + check KB for conflicts."""
    print('=== 招生网搜索: ' + keyword + ' ===')
    found_online = []
    for page in range(1, 33):
        url = NOTICE_URL if page == 1 else NOTICE_URL + 'index_' + str(page - 1) + '.shtml'
        html = fetch_page(url)
        if not html: break
        notices = parse_notices(html)
        for title, url in notices:
            if keyword in title:
                found_online.append((title, url))
    if found_online:
        for title, url in found_online[:10]:
            print(title)
            print('  ' + url)
    else:
        print('[X] 招生网未找到')
    print('')
    print('=== 知识库搜索: ' + keyword + ' ===')
    kb_files = []
    if os.path.exists(KB_PATH):
        for f in os.listdir(KB_PATH):
            if f.endswith('.md'):
                try:
                    with open(os.path.join(KB_PATH, f), 'r', encoding='utf-8') as fh:
                        if keyword in fh.read():
                            kb_files.append(f)
                except: pass
    if kb_files:
        for f in kb_files[:10]:
            print('  ' + f)
    else:
        print('[X] 知识库未找到')
    print('')
    if found_online and kb_files:
        print('数据源对比：招生网和知识库均有相关内容。以知识库为准。')
    elif found_online and not kb_files:
        print('数据源对比：仅在招生网找到。')
    elif not found_online and kb_files:
        print('数据源对比：仅在知识库找到。')
    else:
        print('数据源对比：均未找到。')

def scan():
    """Scan all notice pages and build index."""
    all_notices = []
    for page in range(1, 33):
        url = NOTICE_URL if page == 1 else NOTICE_URL + 'index_' + str(page - 1) + '.shtml'
        html = fetch_page(url)
        if not html: break
        notices = parse_notices(html)
        all_notices.extend(notices)
        print('第' + str(page) + '页: ' + str(len(notices)) + '条', file=sys.stderr)
    print('共' + str(len(all_notices)) + '条通知')
    for title, url in all_notices:
        print(title)
        print('  ' + url)
        print()

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0)
    cmd = args[0]
    if cmd == 'list':
        p = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        list_notices(p)
    elif cmd == 'search':
        search(args[1] if len(args) > 1 else '')
    elif cmd == 'read':
        read_notice(args[1] if len(args) > 1 else '')
    elif cmd == 'verify':
        verify(args[1] if len(args) > 1 else '')
    elif cmd == 'scan':
        scan()
    else:
        search(cmd)
