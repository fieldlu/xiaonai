#!/usr/bin/env python3
"""Look up classmate by name in contact list and prepare QQ notification."""
import sys, os

CONTACTS = "/opt/xiaonai/data/knowledge/YOUR_CONTACTS_FILE.md"

def lookup(name):
    if not os.path.exists(CONTACTS):
        return None, None, None, "通讯录文件不存在"
    with open(CONTACTS, encoding="utf-8") as f:
        lines = f.readlines()
    best_qq, best_name, best_role = None, None, None
    for line in lines:
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 3:
            qq, cname = cells[0], cells[1]
            role = cells[2] if len(cells) > 2 else ""
            if cname == name:
                return qq, cname, role, None
            if best_qq is None and name in cname:
                best_qq, best_name, best_role = qq, cname, role
    if best_qq:
        return best_qq, best_name, best_role, None
    return None, None, None, "未找到 " + name

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: notify_classmate.py <姓名> [消息内容]")
        sys.exit(1)
    name = sys.argv[1]
    msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    qq, full_name, role, err = lookup(name)
    if err:
        print("[Error] " + err)
        sys.exit(1)
    print("FOUND: QQ=" + qq + " Name=" + full_name)
    if role:
        print("ROLE: " + role)
    if msg:
        print("NOTIFY: user " + qq + ' (' + full_name + ') 消息: "' + msg + '"')
        print("HINT: 实际发送走对话工具 admin_send_message / admin_cli.py send " + qq + ' "' + msg + '"')
