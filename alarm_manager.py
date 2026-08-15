#!/usr/bin/env python3
"""Manage alarms for XiaoNai QQ bot. Stored in data/alarms.json."""
import sys, json, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ALARMS_FILE = Path("/opt/xiaonai/data/alarms.json")
BEIJING_TZ = timezone(timedelta(hours=8))

def load():
    if ALARMS_FILE.exists():
        return json.loads(ALARMS_FILE.read_text())
    return []

def save(alarms):
    ALARMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALARMS_FILE.write_text(json.dumps(alarms, ensure_ascii=False, indent=2))

def cmd_set(time_str, message, user_id=ADMIN_QQ_PLACEHOLDER, is_group=False, group_id=0):
    alarms = load()
    # Parse time: "08:00" or "2026-06-01 08:00"
    if " " in time_str:
        dt = datetime.fromisoformat(time_str).replace(tzinfo=BEIJING_TZ)
    elif ":" in time_str:
        today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        dt = datetime.fromisoformat(f"{today} {time_str}").replace(tzinfo=BEIJING_TZ)
        if dt < datetime.now(BEIJING_TZ):
            dt += timedelta(days=1)
    else:
        dt = datetime.now(BEIJING_TZ) + timedelta(minutes=int(time_str.replace("min","").strip()))
    alarm = {
        "id": f"alarm_{user_id}_{int(dt.timestamp())}",
        "user_id": user_id,
        "message": message,
        "time": dt.isoformat(),
        "is_group": is_group,
        "group_id": group_id
    }
    alarms.append(alarm)
    save(alarms)
    print(f"已设置闹钟: {dt.strftime('%m月%d日 %H:%M')} — {message}")
    return alarm

def cmd_list(user_id=None):
    alarms = load()
    now = datetime.now(BEIJING_TZ)
    active = []
    for a in alarms:
        dt = datetime.fromisoformat(a["time"]);
        if dt.tzinfo is None: dt = dt.replace(tzinfo=BEIJING_TZ)
        if dt > now:
            active.append(a)
    if not active:
        print("暂无闹钟")
        return
    for a in sorted(active, key=lambda x: x["time"]):
        dt = datetime.fromisoformat(a["time"]);
        if dt.tzinfo is None: dt = dt.replace(tzinfo=BEIJING_TZ)
        print(f"[{a['id'][-8:]}] {dt.strftime('%m/%d %H:%M')} — {a['message']}")

def cmd_cancel(alarm_id):
    alarms = load()
    before = len(alarms)
    alarms = [a for a in alarms if not a["id"].endswith(alarm_id)]
    save(alarms)
    print(f"已取消 {'1' if len(alarms) < before else '0'} 个闹钟")

def cmd_check():
    """Check for due alarms. Called by scheduler or cron."""
    alarms = load()
    now = datetime.now(BEIJING_TZ)
    due = []
    remaining = []
    for a in alarms:
        dt = datetime.fromisoformat(a["time"]);
        if dt.tzinfo is None: dt = dt.replace(tzinfo=BEIJING_TZ)
        if dt <= now:
            due.append(a)
        else:
            remaining.append(a)
    if due:
        save(remaining)
        for a in due:
            target = f"group {a['group_id']}" if a.get("is_group") else f"user {a['user_id']}"
            print(f"ALARM_DUE: {a['message']} | target={target} | id={a['id']}")
    else:
        print("NO_DUE_ALARMS")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: alarm_manager.py set|list|cancel|check [args...]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "set" and len(sys.argv) >= 4:
        cmd_set(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "list":
        cmd_list()
    elif cmd == "cancel" and len(sys.argv) == 3:
        cmd_cancel(sys.argv[2])
    elif cmd == "check":
        cmd_check()
    else:
        print("Usage: set <time> <msg> | list | cancel <id> | check")
