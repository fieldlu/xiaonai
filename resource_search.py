#!/usr/bin/env python3
"""WHUT Resource Site - search files, output names + site link (no API download URLs)."""
import sys, requests, json, os, time

TOKEN_FILE = "/opt/xiaonai/.resource_token"
SITE = "https://RESOURCE_SITE"
AUTH = {"email": "RESOURCE_EMAIL_PLACEHOLDER", "password": "RESOURCE_PASSWORD_PLACEHOLDER"}

ABBREV = {"大物":"大学物理","高数":"高等数学","线代":"线性代数","概统":"概率论与数理统计",
    "概率":"概率论与数理统计","数电":"数字电子技术","模电":"模拟电子技术",
    "计组":"计算机组成原理","计网":"计算机网络","复变":"复变函数",
    "思修":"思想道德与法治","史纲":"中国近现代史纲要",
    "近代史":"中国近现代史纲要","马原":"马克思主义基本原理",
    "毛概":"毛泽东思想和中国特色社会主义理论体系概论",
    "习概":"习近平新时代中国特色社会主义思想概论","数分":"数学分析",
    "高代":"高等代数","材力":"材料力学","理力":"理论力学",
    "工图":"工程图学","电工":"电工与电子技术基础","四级":"英语 四级 CET4",
    "六级":"英语 六级 CET6","考研":"考研 研究生","保研":"保研 推免",
    "毕设":"毕业设计 论文","期末":"期末 复习 考试"}

def get_token():
    try:
        mtime = os.path.getmtime(TOKEN_FILE)
        if time.time() - mtime < 3000:
            with open(TOKEN_FILE) as f:
                return f.read().strip()
    except Exception:
        pass
    r = requests.post(f"{SITE}/api/auth", json={"action":"login",**AUTH}, timeout=10)
    data = r.json()
    if data.get("success"):
        with open(TOKEN_FILE,"w") as f:
            f.write(data["token"])
        return data["token"]
    return None

def api_get(path, params=None):
    token = get_token()
    if not token:
        return None
    try:
        r = requests.get(f"{SITE}{path}",
            headers={"Authorization":f"Bearer {token}"}, params=params, timeout=15)
        return r.json()
    except Exception:
        return None

def search_ai(keyword, topk=15):
    data = api_get("/api/ai-search", {"query": keyword, "topK": topk})
    if data and data.get("success"):
        return data.get("files", []), data.get("directories", [])
    return [], []

def fmt_size(size_bytes):
    if not size_bytes:
        return ""
    size_bytes = int(size_bytes)
    if size_bytes >= 1073741824:
        return f"{size_bytes/1073741824:.1f}GB"
    if size_bytes >= 1048576:
        return f"{size_bytes/1048576:.1f}MB"
    if size_bytes >= 1024:
        return f"{size_bytes/1024:.1f}KB"
    return f"{size_bytes}B"

def dir_label(d):
    if isinstance(d, dict):
        return d.get("name", str(d))
    return str(d)

keyword = sys.argv[1] if len(sys.argv) > 1 else ""

if keyword == "--recent":
    data = api_get("/api/files?action=recentUploads", {"limit": "15"})
    if data and data.get("success"):
        files = data["files"]
        print(f"SITE: {SITE}")
        for f in files[:12]:
            name = f["name"]
            size = fmt_size(f.get("size", 0))
            fid = f.get("id", "")
            share = f"{SITE}/?id={fid}" if fid else SITE
            if size:
                print(f"{name} [{size}]")
                print(f"  {share}")
            else:
                print(name)
                print(f"  {share}")
        print()

elif keyword == "--dirs":
    data = api_get("/api/files?action=listAllDirs")
    if data and data.get("success"):
        dirs = data["directories"]
        cats = {}
        for d in dirs:
            top = d.split("/")[0] if "/" in d else d
            cats[top] = cats.get(top, 0) + 1
        for c in sorted(cats):
            print(f"{c} ({cats[c]}个子目录)")

elif keyword:
    expanded = ABBREV.get(keyword, keyword)
    kw = expanded if expanded != keyword else keyword
    files, dirs = search_ai(kw, 12)
    if not files and expanded != keyword:
        files, dirs = search_ai(keyword, 8)
    if files:
        print(f"SITE: {SITE}")
        for f in files:
            name = f["name"]
            size = fmt_size(f.get("size", 0))
            fid = f.get("id", "")
            share = f"{SITE}/?id={fid}" if fid else SITE
            if size:
                print(f"{name} [{size}]")
                print(f"  {share}")
            else:
                print(name)
                print(f"  {share}")
        if dirs:
            names = [dir_label(d) for d in dirs[:5]]
            print("相关目录: " + ", ".join(names))
        print()
    else:
        print("empty")

else:
    print("usage: --recent | --dirs | <keyword>")
