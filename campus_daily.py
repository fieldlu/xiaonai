#!/usr/bin/env python3
"""Fetch yesterday's notices from WHUT 综合信息网 (学校通知).
Usage: python3 campus_daily.py [--today]
Outputs formatted QQ message with yesterday's (or today's) new notices.
"""
import sys, re, os, json
from datetime import datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

# Check for --today flag before overriding sys.argv
_original_argv = sys.argv[:]
_use_today = '--today' in _original_argv
TARGET_DATE = datetime.now().strftime('%Y-%m-%d') if _use_today else (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

sys.argv = ['campus_search.py', '__campus_daily__']
sys.path.insert(0, '/opt/xiaonai')
# Suppress campus_search module-level search output
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')
# sys.stderr was suppressed here (removed to surface errors)
import campus_search
sys.stdout.close()
sys.stdout = _real_stdout

TARGET_URL = 'http://i.whut.edu.cn/xxtg/'
# TARGET_DATE (today or yesterday) defined above

# sent-URL cache: prevents Seeyon OA dynamic links (which don't embed dates in URLs)
# from being re-sent when the school site groups them under a newer date section.
SENT_CACHE = Path('/opt/xiaonai/data/campus_sent_cache.json')

def load_sent_cache():
    if SENT_CACHE.exists():
        try:
            data = json.loads(SENT_CACHE.read_text())
            return data.get('urls', [])
        except:
            pass
    return []

def save_sent_cache(urls):
    SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SENT_CACHE.write_text(json.dumps({
        'urls': urls[-1000:],
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, ensure_ascii=False))


def fetch_notice_list():
    """Fetch and parse the xxtg notice list page. Returns list of (date, title, url)."""
    session = campus_search.session
    webvpn_url = campus_search.encode_url(TARGET_URL)
    try:
        r = session.get(webvpn_url, timeout=15, allow_redirects=True)
    except Exception as e:
        print('[FAIL] campus_daily: network error -', e)
        sys.exit(1)
    if r.status_code != 200:
        print('[FAIL] campus_daily: server returned HTTP', r.status_code, '- will retry later')
        sys.exit(1)

    # Fix encoding
    r.encoding = 'utf-8'
    text = r.text
    if '学校' not in text and '通知' not in text:
        r.encoding = 'gbk'
        text = r.text

    soup = BeautifulSoup(text, 'lxml')
    items = []
    seen = set()

    for a in soup.select('a[href]'):
        title = a.get_text(strip=True)
        href = a.get('href', '')
        if not title or len(title) < 10:
            continue

        # Method 1: extract date from URL path (most reliable for standard WHUT notices)
        # WHUT URLs embed date as .../YYYYMM/tYYYYMMDD_xxx.shtml (e.g. /202605/t20260522_1400259.shtml)
        date_str = None
        if href:
            um = re.search(r'/t(202[56])(\d{2})(\d{2})_', href)
            if um:
                date_str = f'{um.group(1)}-{um.group(2)}-{um.group(3)}'

        # Method 2: extract date from <li> text (reliable for Seeyon OA URLs without date in path)
        if not date_str:
            li = a.find_parent('li')
            if li:
                li_dates = re.findall(r'(202[56][-/]\d{2}[-/]\d{2})', li.get_text())
                if li_dates:
                    date_str = li_dates[-1]

        # Method 3: fallback to ancestor text
        if not date_str:
            ancestor_text = ''
            el = a.parent
            for _ in range(5):
                if el:
                    ancestor_text += ' ' + el.get_text()
                    el = el.parent
            dm = re.search(r'(202[56])[-/](\d{2})[-/](\d{2})', ancestor_text)
            if not dm:
                continue
            date_str = dm.group(0)

        original_url = campus_search.decode_webvpn_url(href) if href else ''

        # Deduplicate
        key = title[:40]
        if key not in seen:
            seen.add(key)
            items.append((date_str, title, original_url))

    return items


def format_message(notices):
    """Format notices into a QQ-friendly message."""
    if not notices:
        return None

    lines = [
        '\U0001F4CB 综合信息网 · 最新通知',
        '━' * 16,
    ]
    for i, (date, title, url) in enumerate(notices[:15], 1):
        short_title = title[:55] + '...' if len(title) > 55 else title
        lines.append(f'{i}. {short_title}')
        if url:
            lines.append(f'   \U0001F517 {url}')

    if len(notices) > 15:
        lines.append(f'\n... 还有 {len(notices) - 15} 条，详见 http://i.whut.edu.cn/xxtg/')

    lines.append('━' * 16)
    return '\n'.join(lines)


def main():
    try:
        notices = fetch_notice_list()
        yesterday_notices = [(d, t, u) for d, t, u in notices if d == TARGET_DATE]

        # Skip items whose URL was already included in a previous campus daily run.
        # This prevents Seeyon OA dynamic links (no date in URL path) from being
        # re-sent when the school site re-groups them under a different date section.
        sent_cache = load_sent_cache()
        yesterday_notices = [(d, t, u) for d, t, u in yesterday_notices if not u or u not in sent_cache]

        if not yesterday_notices:
            # Try the latest date in the data (weekend/holiday fallback)
            if notices:
                latest = sorted(set(d for d, _, _ in notices), reverse=True)[0]
                fb = [(d, t, u) for d, t, u in notices if d == latest]
                fb = [(d, t, u) for d, t, u in fb if not u or u not in sent_cache]
                if fb:
                    msg = format_message(fb)
                    if msg:
                        msg = msg.replace(TARGET_DATE, latest)
                        msg = msg.replace("昨日通知", "最新通知")
                        print(msg)
                        new_urls = [u for _, _, u in fb if u and u not in sent_cache]
                        sent_cache.extend(new_urls)
                        sent_cache = sent_cache[-1000:]
                        save_sent_cache(sent_cache)
                        return
            print('')  # No output = skip send
            return

        msg = format_message(yesterday_notices)
        if msg:
            new_urls = [u for _, _, u in yesterday_notices if u and u not in sent_cache]
            sent_cache.extend(new_urls)
            sent_cache = sent_cache[-1000:]
            save_sent_cache(sent_cache)
            print(msg)
    except Exception as e:
        import traceback
        print(f'[campus_daily error] {e}', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
