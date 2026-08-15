#!/usr/bin/env python3
import sys, re, json, html, requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

def has_hidden_style(tag):
    style = tag.get('style', '')
    return 'display:none' in style.replace(' ', '') or 'display: none' in style.replace(' ', '')

def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, 'html.parser')

    title_el = soup.select_one('#activity-name') or soup.select_one('.rich_media_title')
    title = title_el.get_text(strip=True) if title_el else ''

    author_el = soup.select_one('#js_name') or soup.select_one('#js_wx_follow_nickname')
    author = author_el.get_text(strip=True) if author_el else ''

    date_el = soup.select_one('#publish_time')
    date = date_el.get_text(strip=True) if date_el else ''

    content_el = soup.select_one('#js_content')
    if not content_el:
        return {'title': title, 'author': author, 'date': date, 'content': '', 'url': url, 'error': 'content not found'}

    # Remove hidden elements and junk
    for tag in content_el.find_all(style=re.compile(r'display\s*:\s*none', re.I)):
        tag.decompose()
    for cls in ['reward_area', 'rich_media_tool', 'qr_code_pc_outer', 'rich_media_area_extra']:
        for tag in content_el.find_all(class_=re.compile(cls)):
            tag.decompose()

    lines = []
    seen = set()
    for el in content_el.descendants:
        if el.name == 'img':
            alt = (el.get('alt') or '').strip()
            line = ('[图片: ' + alt + ']') if alt else '[图片]'
            if line not in seen:
                lines.append(line)
                seen.add(line)
        elif el.name == 'br':
            lines.append('')
        elif isinstance(el, str):
            t = el.strip()
            if t and t not in seen:
                lines.append(t)
                seen.add(t)

    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = html.unescape(text)

    if len(text) > 15000:
        text = text[:15000] + '\n\n[...内容过长，已截断...]'

    return {'title': title, 'author': author, 'date': date, 'content': text, 'url': url}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'usage: wechat_fetch.py <url>'}, ensure_ascii=False))
        sys.exit(1)
    try:
        result = fetch(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({'error': str(e), 'url': sys.argv[1]}, ensure_ascii=False))
        sys.exit(1)
