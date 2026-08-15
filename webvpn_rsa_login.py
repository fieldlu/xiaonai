#!/usr/bin/env python3
"""WebVPN RSA login — refresh WebVPN ticket manually."""
import sys, os, json, requests, re
USER = os.environ.get('ZHLGD_USER') or os.environ.get('WHUT_USER') or ''
PASS = os.environ.get('ZHLGD_PASS') or os.environ.get('WHUT_PASS') or ''
if not USER:
    print('[Error] Set ZHLGD_USER / ZHLGD_PASS environment variables'); sys.exit(1)
s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})
r2 = s.get('https://zhlgd.whut.edu.cn/tpass/login?service=https://webvpn.whut.edu.cn/login?cas_login=true', timeout=15)
cookies = s.cookies.get_dict()
print(json.dumps(cookies, indent=2))
print('WebVPN ticket refreshed.')
