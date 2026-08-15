#!/usr/bin/env python3
"""Proactive agent check: health + alarms + activity monitoring.
Called by OpenClaw cron every 10 min. The agent reads this output
and takes action on any issues found.
"""
import subprocess, sys, json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))
BRIDGE_HTTP = "http://127.0.0.1:8081"
ADMIN_QQ = "ADMIN_QQ_PLACEHOLDER"

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)

def send_qq(target_type, target_id, message):
    """Send message via bridge HTTP API."""
    import urllib.request
    data = json.dumps({
        "group_id" if target_type == "group" else "user_id": int(target_id),
        "message": message
    }).encode()
    try:
        req = urllib.request.Request(f"{BRIDGE_HTTP}/send", data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False

def _get_test_group():
    try:
        cfg = json.load(open("/opt/xiaonai/data/scheduler_config.json"))
        return cfg.get("test_group", TEST_GROUP_PLACEHOLDER)
    except:
        return TEST_GROUP_PLACEHOLDER

def check_health():
    """Run bridge_health.py and return issues."""
    code, out = run("cd /opt/xiaonai && python3 bridge_health.py")
    issues = []
    try:
        data = json.loads(out)
        if not data.get("healthy"):
            issues.append(f"System unhealthy: {data.get('issues', [])}")
    except:
        if code != 0:
            issues.append(f"Health check failed: {out[:200]}")
    return issues

def check_alarms():
    """Check for due alarms and dispatch them via QQ."""
    code, out = run("cd /opt/xiaonai && python3 alarm_manager.py check")
    dispatched = 0
    if "ALARM_DUE:" in out:
        for line in out.split('\n'):
            if line.startswith("ALARM_DUE:"):
                parts = line.replace("ALARM_DUE: ", "").split(" | ")
                msg = parts[0].strip()
                target_info = {p.split('=')[0].strip(): p.split('=')[1].strip() for p in parts[1:] if '=' in p}
                target = target_info.get("target", "")
                if target.startswith("user "):
                    uid = target.replace("user ", "")
                    send_qq("private", uid, f"Alarm: {msg}")
                    dispatched += 1
                elif target.startswith("group "):
                    gid = target.replace("group ", "")
                    send_qq("group", gid, f"Alarm: {msg}")
                    dispatched += 1
    return dispatched

def check_sessions():
    """Check for stale sessions."""
    sessions_dir = Path(os.path.expanduser("~/.openclaw/agents/main/sessions"))
    lock_count = len(list(sessions_dir.glob("*.lock"))) if sessions_dir.exists() else 0
    return lock_count

def main():
    now = datetime.now(BEIJING_TZ).strftime("%H:%M")
    results = {"time": now, "health_issues": [], "alarms_dispatched": 0, "stale_locks": 0}

    results["health_issues"] = check_health()
    results["alarms_dispatched"] = check_alarms()
    results["stale_locks"] = check_sessions()

    # Build summary
    lines = [f"[Proactive Check {now}]"]
    has_issues = bool(results["health_issues"]) or results["stale_locks"] > 0

    if results["health_issues"]:
        for issue in results["health_issues"]:
            lines.append(f"HEALTH: {issue}")
        # Send health alert to admin (private), not the test group
        alert = "\n".join([f"System Alert {now}"] + [f"HEALTH: {i}" for i in results["health_issues"]])
        send_qq("private", ADMIN_QQ, alert)
    else:
        lines.append("System healthy")
    if results["alarms_dispatched"] > 0:
        lines.append(f"Alarms dispatched: {results['alarms_dispatched']}")
    if results["stale_locks"] > 0:
        lines.append(f"Stale locks: {results['stale_locks']}")

    summary = "\n".join(lines)
    if has_issues or results["alarms_dispatched"] > 0:
        print(summary)
    else:
        print(f"[Proactive Check {now}] All OK")

if __name__ == "__main__":
    main()
