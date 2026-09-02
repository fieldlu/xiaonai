#!/usr/bin/env python3
"""全量抓取 gztz 工作通知公告 29 页历史（约 1000 条），落盘 /tmp/gztz_all.json。
字段: d=日期 t=标题 u=原始校内URL(decode)。"""
import sys, re, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_real_out = sys.stdout
sys.stdout = open(os.devnull, 'w')
import campus_search
sys.stdout.close()
sys.stdout = _real_out
from bs4 import BeautifulSoup

OUT = '/tmp/gztz_all.json'
N_PAGES = 29
BASE = 'http://i.whut.edu.cn/xxtg/gztz_9764'

def grab(url):
    enc = campus_search.encode_url(url)
    r = campus_search.session.get(enc, timeout=25, allow_redirects=True)
    r.encoding = 'utf-8'
    text = r.text
    if '学校' not in text and '通知' not in text:
        r.encoding = 'gbk'
        text = r.text
    soup = BeautifulSoup(text, 'lxml')
    items = []
    for a in soup.select('a[href]'):
        txt = a.get_text(strip=True)
        href = a.get('href', '')
        if len(txt) < 8:
            continue
        li = a.find_parent('li')
        m = re.search(r'(202[56])[-/](\d{1,2})[-/](\d{1,2})', li.get_text()) if li else None
        if m:
            raw = campus_search.decode_webvpn_url(href) if href else ''
            items.append({'d': '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))),
                          't': txt, 'u': raw})
    return items

all_items = []
for pg in range(N_PAGES):
    url = '%s.shtml' % BASE if pg == 0 else '%s_%d.shtml' % (BASE, pg)
    try:
        its = grab(url)
        all_items.extend(its)
        print('page %d/%d: %d items (now %d)' % (pg + 1, N_PAGES, len(its), len(all_items)), flush=True)
    except Exception as e:
        print('page %d ERROR: %s' % (pg, e), flush=True)
    time.sleep(0.4)

# 去重（跨页可能重复）
seen, uniq = set(), []
for it in all_items:
    k = (it['d'], it['t'][:40])
    if k not in seen:
        seen.add(k)
        uniq.append(it)

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'n': len(uniq), 'items': uniq}, f, ensure_ascii=False, indent=0)
print('DONE total=%d unique=%d saved=%s' % (len(all_items), len(uniq), OUT), flush=True)
