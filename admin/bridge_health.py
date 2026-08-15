#!/usr/bin/env python3
"""Bridge health check for the 小奈 QQ bot — hardened version.
Usage: python3 admin/bridge_health.py [--fix]
Output: JSON health status + optional auto-repair.

Hardening vs old version:
  - system services restarted via `sudo -n systemctl` (bare systemctl under the
    ubuntu user failed with "Interactive authentication required")
  - openclaw uid resolved dynamically (was hardcoded 1000)
  - stale-lock cleanup is PID-validated (no blind `kill -9` on stale PIDs)
  - adds disk / memory checks
"""
import subprocess, json, sys, time, os, re


def run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
SYSTEM_SERVICES = ["xiaonai-bridge", "xiaonai-qq", "xiaonai-scheduler",
                   "xiaonai-consult", "xiaonai-http-proxy"]
SESSION_PROC_RE = re.compile(r"openclaw|node|agent")


def _svc_active(svc):
    rc, out, _ = run(f"systemctl is-active {svc}")
    return rc == 0 and out == "active"


def _restart_system_svc(svc):
    rc, _, err = run(f"sudo -n systemctl restart {svc}", timeout=10)
    if rc != 0:
        return False, f"restart cmd failed: {err[:80]}"
    time.sleep(3)
    for _ in range(5):
        if _svc_active(svc):
            return True, "active"
        time.sleep(3)
    return False, "still not active"


def _restart_gateway():
    uid = run("id -u ubuntu")[1] or "1000"
    cmd = f"XDG_RUNTIME_DIR=/run/user/{uid} sudo -u ubuntu systemctl --user restart openclaw-gateway"
    run(cmd, timeout=10)
    time.sleep(3)
    for _ in range(5):
        rc, _, _ = run("curl -s --connect-timeout 3 http://127.0.0.1:18789/health")
        if rc == 0:
            return True, "ok"
        time.sleep(3)
    return False, "still unresponsive"


def _clean_locks():
    cleaned = 0
    for lock in os.listdir(SESSIONS_DIR):
        if not lock.endswith(".lock"):
            continue
        path = os.path.join(SESSIONS_DIR, lock)
        try:
            pid = ""
            with open(path) as f:
                pid = re.sub(r"\D", "", f.readline().strip())
            if pid and os.path.exists(f"/proc/{pid}/cmdline"):
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    blob = f.read().decode("utf-8", "replace")
                if SESSION_PROC_RE.search(blob):
                    os.kill(int(pid), 9)
            os.remove(path)
            cleaned += 1
        except (OSError, ValueError):
            continue
    return cleaned


def check():
    result = {"healthy": True, "services": {}, "actions": [], "issues": []}

    for svc in SYSTEM_SERVICES:
        result["services"][svc] = "active" if _svc_active(svc) else "dead"

    rc, _, _ = run("curl -s --connect-timeout 3 http://127.0.0.1:18789/health")
    result["services"]["openclaw-gateway"] = "ok" if rc == 0 else "dead"

    rc, out, _ = run('journalctl -u xiaonai-bridge --since "10 min" --no-pager 2>/dev/null | grep -cE "PRIVATE|GROUP" || echo 0')
    try:
        msg_count = int(out.strip()) if out.strip() else 0
    except ValueError:
        msg_count = 0
    result["recent_messages"] = msg_count

    result["stale_locks"] = sum(1 for f in os.listdir(SESSIONS_DIR) if f.endswith(".lock")) \
        if os.path.isdir(SESSIONS_DIR) else 0

    rc, out, _ = run('df / 2>/dev/null | awk \'NR==2 {gsub("%","",$5); print $5}\'')
    try:
        result["disk_percent"] = int(out.strip()) if out.strip() else 0
    except ValueError:
        result["disk_percent"] = 0

    rc, out, _ = run("free -m 2>/dev/null | awk '/Mem:/ {print $7}'")
    try:
        result["mem_available_mb"] = int(out.strip()) if out.strip() else 0
    except ValueError:
        result["mem_available_mb"] = 0

    for svc, state in result["services"].items():
        if state != "active" and state != "ok":
            result["healthy"] = False
            result["issues"].append(f"{svc} is {state}")
    if result["services"].get("xiaonai-bridge") == "active" and msg_count == 0:
        result["issues"].append("bridge active but no messages in 10min")
    if result["disk_percent"] >= 90:
        result["issues"].append(f"disk {result['disk_percent']}% used")
    if result["mem_available_mb"] < 150:
        result["issues"].append(f"low memory: {result['mem_available_mb']}MB")
    return result


def fix(result):
    fixed = []
    for svc in SYSTEM_SERVICES:
        if result["services"][svc] != "active":
            ok, detail = _restart_system_svc(svc)
            fixed.append(f"{svc} restart -> {detail}")
    if result["services"].get("openclaw-gateway") != "ok":
        ok, detail = _restart_gateway()
        fixed.append(f"openclaw-gateway restart -> {detail}")
    if result["stale_locks"] > 0:
        cleaned = _clean_locks()
        fixed.append(f"cleaned {cleaned} stale locks")
    return fixed


if __name__ == "__main__":
    result = check()
    if "--fix" in sys.argv:
        if not result["healthy"]:
            result["actions"] = fix(result)
            result = check()
            result["actions"] = result.get("actions", [])
    print(json.dumps(result, ensure_ascii=False, indent=2))
