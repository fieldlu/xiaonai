#!/usr/bin/env python3
"""WHUT WebVPN Auto-Login with RSA encryption."""
import requests, re, urllib.parse, json, base64, os, sys, time

PROXY = {'http': 'http://127.0.0.1:8888', 'https': 'http://127.0.0.1:8888'}
USER = 'WHUT_ACCOUNT_PLACEHOLDER'
PASS = 'WHUT_PASSWORD_PLACEHOLDER'
TICKET_FILE = '/opt/xiaonai/.webvpn_ticket'

# Try importing RSA library
try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    print("No pycryptodome, trying pure Python RSA...")

def js_encrypt_rsa(public_key_pem, plaintext):
    """Replicate JSEncrypt.encrypt() behavior."""
    if HAS_CRYPTO:
        key = RSA.import_key(public_key_pem)
        cipher = PKCS1_v1_5.new(key)
        encrypted = cipher.encrypt(plaintext.encode('utf-8'))
        return base64.b64encode(encrypted).decode('ascii')
    else:
        # Fallback: use Python's built-in rsa if available
        import rsa
        pubkey = rsa.PublicKey.load_pkcs1_openssl_pem(public_key_pem.encode())
        encrypted = rsa.encrypt(plaintext.encode('utf-8'), pubkey)
        return base64.b64encode(encrypted).decode('ascii')

s = requests.Session()
s.proxies = PROXY
s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

# Step 1: Get RSA public key
r_key = s.post('https://zhlgd.whut.edu.cn/tpass/rsa?skipWechat=true', json={}, timeout=10)
key_data = r_key.json()
public_key = key_data.get('publicKey', key_data.get('modulus', ''))
print(f"Got key: {public_key[:60]}...")

# Step 2: Get CAS login page
r = s.get('https://zhlgd.whut.edu.cn/tpass/login?service=https://webvpn.whut.edu.cn/login?cas_login=true', timeout=15)
text = r.text

# Parse form
form_data = {}
for inp in re.findall(r'<input[^>]*>', text):
    name_m = re.search(r'name="([^"]+)"', inp)
    val_m = re.search(r'value="([^"]*)"', inp)
    if name_m:
        form_data[name_m.group(1)] = val_m.group(1) if val_m else ''

# Encrypt username and password
if HAS_CRYPTO:
    from Crypto.PublicKey import RSA as RSA2
    from Crypto.Cipher import PKCS1_v1_5 as PKCS
    key = RSA2.import_key(public_key)
    cipher = PKCS.new(key)
    form_data['ul'] = base64.b64encode(cipher.encrypt(USER.encode())).decode()
    form_data['pl'] = base64.b64encode(cipher.encrypt(PASS.encode())).decode()
else:
    # Fallback: try without encryption
    form_data['ul'] = USER
    form_data['pl'] = PASS

form_data['un'] = USER
form_data['pd'] = PASS
form_data['_eventId'] = 'submit'

for k in ['code', 'captcha', 'mobile', 'phone', 'sms', 'rsa']:
    form_data.pop(k, None)

parsed = urllib.parse.urlparse(r.url)
login_url = f'{parsed.scheme}://{parsed.netloc}/tpass/login?service=https://webvpn.whut.edu.cn/login?cas_login=true'

# Step 3: Submit login
r2 = s.post(login_url, data=form_data,
    headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': f'{parsed.scheme}://{parsed.netloc}',
        'Referer': r.url,
        'X-Requested-With': 'XMLHttpRequest',
    },
    timeout=15, allow_redirects=True)

print(f"Login response: {r2.status_code}, URL: {r2.url[:100]}")

# Follow redirects to WebVPN
if 'zhlgd' not in r2.url.lower() or 'webvpn' in r2.url.lower():
    # Final redirect to WebVPN
    r3 = s.get(r2.url, timeout=15, allow_redirects=True)
    print(f"Final: {r3.status_code}, URL: {r3.url[:100]}")

# Check for ticket
ticket = None
for c in s.cookies:
    if 'wengine_vpn_ticket' in c.name:
        ticket = c.value
        print(f"TICKET FOUND: {c.name} = {ticket[:40]}...")

# Check Set-Cookie from ALL responses
for r_obj in [r2] + list(r2.history):
    for h in r_obj.headers.get('Set-Cookie', '').split(','):
        if 'wengine_vpn_ticketwebvpn_whut_edu_cn' in h:
            m = re.search(r'wengine_vpn_ticketwebvpn_whut_edu_cn=([^;,]+)', h)
            if m:
                ticket = m.group(1)
                print(f"TICKET from header: {ticket[:40]}...")

if ticket:
    with open(TICKET_FILE, 'w') as f:
        f.write(ticket)
    print(f"SAVED: {ticket[:40]}...")
    
    # Verify ticket
    s2 = requests.Session()
    s2.proxies = PROXY
    s2.cookies.set('wengine_vpn_ticketwebvpn_whut_edu_cn', ticket)
    rv = s2.get('https://webvpn.whut.edu.cn/', timeout=15, allow_redirects=True)
    if 'login' not in rv.url.lower():
        print("VERIFIED: Ticket is valid!")
        sys.exit(0)
    else:
        print("FAILED: Ticket doesn't work")
else:
    title = re.search(r'<title>([^<]+)</title>', r2.text)
    if title:
        print(f"Page: {title.group(1)}")
    # Check errors
    errs = re.findall(r'class="(?:error|warning|msg)[^"]*"[^>]*>([^<]+)', r2.text)
    for e in errs[:5]:
        e = re.sub(r'<[^>]+>', '', e).strip()
        if len(e) > 2:
            print(f"Error: {e}")

sys.exit(1)
