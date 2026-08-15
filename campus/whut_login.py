# -*- coding: utf-8 -*-
import requests, re

PROXY = {"http": "http://127.0.0.1:40000", "https": "http://127.0.0.1:40000"}
USER = "WHUT_ACCOUNT_PLACEHOLDER"
PASS = "WHUT_PASSWORD_PLACEHOLDER"

s = requests.Session()
s.proxies = PROXY
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
})

# Step 1: Get login page
print("Step 1: Get login page")
r = s.get("https://webvpn.whut.edu.cn/login", timeout=15)
print("Status:", r.status_code)
print("URL:", r.url[:100])

# Dump the form fields
forms = re.findall(r'<input[^>]+>', r.text)
print(f"Found {len(forms)} input fields:")
for f in forms:
    name = re.search(r'name="([^"]+)"', f)
    typ = re.search(r'type="([^"]+)"', f)
    val = re.search(r'value="([^"]*)"', f)
    if name:
        print(f"  name={name.group(1)}, type={typ.group(1) if typ else 'text'}, value={val.group(1) if val else ''}")

# Also find form action
form_action = re.search(r'<form[^>]+action="([^"]+)"', r.text)
if form_action:
    print(f"Form action: {form_action.group(1)}")
else:
    # Find any form
    all_forms = re.findall(r'<form[^>]*>', r.text)
    print(f"All forms: {all_forms}")

# Step 2: Try submitting login
# Based on WebVPN typical form fields
login_url = "https://webvpn.whut.edu.cn/login"
data = {
    "username": USER,
    "password": PASS,
}
print("\nStep 2: Submit login")
r2 = s.post(login_url, data=data, allow_redirects=True, timeout=15)
print("Status:", r2.status_code)
print("Final URL:", r2.url[:100])

# Check for ticket
for c in s.cookies:
    if "wengine" in c.name.lower():
        print(f"TICKET: {c.name} = {c.value}")

# Check Set-Cookie
for h in r2.headers.get("Set-Cookie", "").split(";"):
    if "wengine" in h.lower():
        print(f"Set-Cookie: {h.strip()[:80]}")

# Check for error messages
if "error" in r2.text.lower() or "fail" in r2.text.lower() or "incorrect" in r2.text.lower():
    print("Login may have failed")
    # Look for error message
    err_match = re.search(r'(error|fail|incorrect|wrong|invalid)[^<]{0,100}', r2.text, re.I)
    if err_match:
        print(f"Error: {err_match.group()}")
