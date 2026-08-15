#!/usr/bin/env python3
"""Campus notice keyword search — CAS login, session cookies, multi-threaded.
Usage: campus_search.py <keyword> | campus_search.py --read <url>"""
import sys, requests, re, base64, urllib.parse, os, time
import re as _re
from bs4 import BeautifulSoup

def read_page(url):
    """Fetch and extract text content from a WHUT campus page via WebVPN."""
    global session
    webvpn_url = encode_url(url)
    try:
        r = session.get(webvpn_url, timeout=15)
        r.encoding = 'utf-8'
        if r.status_code == 403 or len(r.text) < 300:
            return None, "403 or empty - page may need different auth"
        if '统一身份认证' in r.text:
            # Try re-login
            session = full_cas_login()
            r = session.get(webvpn_url, timeout=15)
            r.encoding = 'utf-8'
            if '统一身份认证' in r.text:
                return None, "CAS re-login failed"
        soup = BeautifulSoup(r.text, 'lxml')
        for t in soup(['script', 'style', 'nav', 'footer', 'header']):
            t.decompose()
        # WHUT pages: try specific selectors first
        main = soup.select_one('div.article_content')
        if not main:
            main = soup.select_one('div.view.TRS_UEDITOR')
        if not main:
            main = soup.select_one('div.article')
        if not main:
            main = soup.find('div', class_=_re.compile(r'con|main|content|art|text|body', _re.I))
        if not main:
            main = soup.find('article')
        if not main:
            main = soup.find('body')
        if not main:
            main = soup
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ''
        text = main.get_text(separator='\n', strip=True)
        text = _re.sub(r'\n{3,}', '\n\n', text)
        text = _re.sub(r'[ \t]{2,}', ' ', text)
        if len(text) > 8000:
            text = text[:8000] + '\n...[truncated]'
        return title, text
    except Exception as e:
        return None, str(e)

from concurrent.futures import ThreadPoolExecutor, as_completed

if __name__ == "__main__":
    keyword = sys.argv[1]
USER = 'WHUT_ACCOUNT_PLACEHOLDER'
PASS = 'WHUT_PASSWORD_PLACEHOLDER'

def find_proxy():
    # Use WARP proxy on port 40000 for all WHUT traffic
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', 40000))
        sock.close()
        if result == 0:
            return 40000
    except:
        pass
    # No WARP fallback - try direct
    return None

PROXY_PORT = find_proxy()
PROXY = {"http": "http://127.0.0.1:" + str(PROXY_PORT), "https": "http://127.0.0.1:" + str(PROXY_PORT)} if PROXY_PORT else {}

def full_cas_login():
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    s = requests.Session()
    s.proxies = PROXY
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    r = s.post('https://zhlgd.whut.edu.cn/tpass/rsa?skipWechat=true', json={}, timeout=10)
    der = base64.b64decode(r.json()['publicKey'])
    pem = '-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(der).decode() + '\n-----END PUBLIC KEY-----'
    key = RSA.import_key(pem)
    cipher = PKCS1_v1_5.new(key)
    eu = base64.b64encode(cipher.encrypt(USER.encode())).decode()
    ep = base64.b64encode(cipher.encrypt(PASS.encode())).decode()
    r2 = s.get('https://zhlgd.whut.edu.cn/tpass/login?service=https://webvpn.whut.edu.cn/login?cas_login=true', timeout=15)
    form = {}
    for inp in re.findall(r'<input[^>]*>', r2.text):
        nm = re.search(r'name="([^"]+)"', inp)
        vm = re.search(r'value="([^"]*)"', inp)
        if nm:
            form[nm.group(1)] = vm.group(1) if vm else ''
    form.update({'ul': eu, 'pl': ep, 'un': USER, 'pd': PASS, '_eventId': 'submit'})
    for k in ['code', 'captcha', 'mobile', 'phone', 'sms', 'rsa']:
        form.pop(k, None)
    parsed = urllib.parse.urlparse(r2.url)
    login_url = f'{parsed.scheme}://{parsed.netloc}/tpass/login?service=https://webvpn.whut.edu.cn/login?cas_login=true'
    s.post(login_url, data=form,
           headers={'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': f'{parsed.scheme}://{parsed.netloc}',
                    'Referer': r2.url},
           timeout=15, allow_redirects=True)
    s.get('https://webvpn.whut.edu.cn/', timeout=10, allow_redirects=True)
    for c in s.cookies:
        if 'wengine_vpn_ticket' in c.name:
            with open('/opt/xiaonai/.webvpn_ticket', 'w') as f:
                f.write(c.value)
            break
    return s

session = full_cas_login()


_XOR_KEY = bytes.fromhex("909721fc475008301e68e9ccf835435516")
_MAGIC = "77726476706e69737468656265737421"

def decode_webvpn_url(url):
    """Convert WebVPN proxy URL back to original campus URL."""
    m = re.match(r"https://webvpn\.whut\.edu\.cn/(https?)/([0-9a-f]+)(/.*)?", url)
    if not m:
        return url
    proto = m.group(1)
    hex_part = m.group(2)
    path = m.group(3) or ""
    if hex_part.startswith(_MAGIC):
        hex_part = hex_part[len(_MAGIC):]
    try:
        host_bytes = bytes(a ^ b for a, b in zip(bytes.fromhex(hex_part), _XOR_KEY))
        host = host_bytes.decode("ascii")
        return f"{proto}://{host}{path}"
    except:
        return url

def encode_url(url):
    if not url.startswith("http"):
        url = "http://" + url
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    protocol = parsed.scheme or "http"
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    encoded_host = bytes(a ^ b for a, b in zip(host.encode(), _XOR_KEY)).hex()
    return f"https://webvpn.whut.edu.cn/{protocol}/{_MAGIC}{encoded_host}{path}"

def search_page(url, keyword):
    try:
        webvpn_url = encode_url(url)
        r = session.get(webvpn_url, timeout=8)
        r.encoding = 'utf-8'
        if r.status_code == 403 or len(r.text) < 500:
            return [], True
        if '统一身份认证' in r.text:
            return [], True
        soup = BeautifulSoup(r.text, 'lxml')
        for t in soup(['script', 'style']):
            t.decompose()
        results, seen = [], set()
        kw = keyword.lower()
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a.get('href', '')
            if not text or len(text) < 4:
                continue
            if href.startswith('#') or href.startswith('javascript'):
                continue
            if kw not in text.lower():
                continue
            full_url = href
            if href.startswith('/'):
                full_url = f'https://webvpn.whut.edu.cn{href}'
            elif not href.startswith('http'):
                full_url = f'https://webvpn.whut.edu.cn/{href}'
            # Decode to original campus URL for users
            original_url = decode_webvpn_url(full_url)
            date = ''
            parent = a.find_parent(['li', 'div', 'tr', 'td'])
            if parent:
                dm = re.search(r'(\d{4}-\d{2}-\d{2})', parent.get_text())
                if dm:
                    date = dm.group(1)
            if (text, full_url) not in seen:
                seen.add((text, full_url))
                results.append((text, original_url, date))
        return results, False
    except Exception:
        return [], False

def read_page(url):
    """Fetch and extract text content from a WHUT campus page via WebVPN."""
    import re
    webvpn_url = encode_url(url)
    try:
        r = session.get(webvpn_url, timeout=15)
        r.encoding = 'utf-8'
        if r.status_code == 403 or len(r.text) < 300:
            return None, "403 or empty response — page may require different auth"
        if '统一身份认证' in r.text:
            return None, "CAS login required — ticket may be expired"
        soup = BeautifulSoup(r.text, 'lxml')
        # Remove noise
        for t in soup(['script', 'style', 'nav', 'footer', 'header']):
            t.decompose()
        # Try to find the main content area
        main = soup.find('div', class_=re.compile(r'con|main|content|art|text|body', re.I))
        if not main:
            main = soup.find('article')
        if not main:
            main = soup.find('body')
        if not main:
            main = soup
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ''
        # Extract clean text
        text = main.get_text(separator='\n', strip=True)
        # Collapse whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        if len(text) > 8000:
            text = text[:8000] + '\n...[truncated]'
        return title, text
    except Exception as e:
        return None, str(e)

TARGETS = [
    ('本科生院', 'http://i.whut.edu.cn/xxtg/znbm/jwc/'),
    ('学校通知', 'http://i.whut.edu.cn/xxtg/'),
    ('学院通知', 'http://i.whut.edu.cn/xytg/'),
    ('部门资讯', 'http://i.whut.edu.cn/bmxw/'),
    ('学术讲座', 'http://i.whut.edu.cn/lgjz/'),
    ('教务处', 'http://jwc.whut.edu.cn/'),
]

SYNONYMS = {
    '四六级': ['CET', '英语考试'], '六级': ['CET', '英语考试'],
    '四级': ['CET', '英语考试'], '考研': ['研究生', '硕士'],
    '选课': ['课程', '选修'], '奖学金': ['奖励', '评优'],
    '竞赛': ['大赛', '比赛'],
}

def do_search(kw):
    results, blocked = [], False
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(search_page, url, kw): name for name, url in TARGETS}
        for f in as_completed(futures):
            try:
                items, blk = f.result()
                if blk:
                    blocked = True
                for item in items:
                    results.append((*item, futures[f]))
            except:
                pass
    return results, blocked

# Main
if len(sys.argv) >= 3 and sys.argv[1] == '--read':
    url = sys.argv[2]
    title, text = read_page(url)
    if title is None:
        print(f'[Error] {text}')
        sys.exit(1)
    print(f'标题: {title}')
    print('---')
    print(text)
    sys.exit(0)

keyword_arg = sys.argv[1] if len(sys.argv) > 1 else ''
results, blocked = do_search(keyword_arg)
if blocked and not results:
    print('[auto] re-login via CAS...', file=sys.stderr)
    session = full_cas_login()
    results, _ = do_search(keyword_arg)
if not results and keyword_arg in SYNONYMS:
    for syn in SYNONYMS[keyword_arg]:
        results, _ = do_search(syn)
        if results:
            break
if not results and len(keyword_arg) > 2:
    results, _ = do_search(keyword_arg[:2])

print(f'搜索: {keyword_arg}')
if results:
    by_label = {}
    for title, url, date, label in results:
        by_label.setdefault(label, []).append((title, url, date))
    total = 0
    for label in [t[0] for t in TARGETS]:
        items = by_label.get(label, [])
        if items:
            print(f'\n--- {label} ({len(items)}条) ---')
            for title, url, date in items[:8]:
                total += 1
                ds = f'[{date}] ' if date else ''
                print(f'{ds}{title}')
                print(f'  {url}')
    print(f'\n共 {total} 条')
else:
    print('未找到。建议换更短关键词重试。')
