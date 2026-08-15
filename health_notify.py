#!/usr/bin/env python3
"""Health notification for the 小奈 QQ bot — admin/group with dedup + escalation.

Channels (primary -> fallback):
  1. bridge HTTP  :8081/send  (goes through the bridge -> NapCat WS)
  2. NapCat OneBot API :3000   (direct, used if the bridge is down)

Dedup: a state file (data/notify_state.json) per issue-key blocks repeat spam;
the block window grows with each repeat (dedup * count, capped at 4x) so a
persistent problem re-notifies on an escalating cadence instead of every run.

Usage:
  python3 health_notify.py report "<text>" [--key K] [--dedup N] [--group GID]
  python3 health_notify.py daily
  python3 health_notify.py test
"""
import json, os, sys, time, hashlib, urllib.request, re
from datetime import datetime, timezone, timedelta

BEIJING = timezone(timedelta(hours=8))
ADMIN_QQ = int(os.environ.get("XIAONAI_ADMIN_QQ", "ADMIN_QQ_PLACEHOLDER"))
TEST_GROUP = TEST_GROUP_PLACEHOLDER
BRIDGE_SEND = "http://127.0.0.1:8081/send"
NAPCAT_API = "http://127.0.0.1:3000"
STATE_FILE = "/opt/xiaonai/data/notify_state.json"
RUNS_LOG = "/opt/xiaonai/data/health_runs.log"


def _now():
    return datetime.now(BEIJING)


def _ts():
    return int(time.time())


def send(target_type, target_id, text):
    """Try bridge /send then NapCat OneBot. Returns (ok, channel)."""
    payload = {"message": text}
    payload["group_id" if target_type == "group" else "user_id"] = int(target_id)

    try:
        req = urllib.request.Request(
            BRIDGE_SEND, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if data.get("ok"):
            return True, "bridge"
    except Exception:
        pass

    try:
        ep = (f"{NAPCAT_API}/send_group_msg" if target_type == "group"
              else f"{NAPCAT_API}/send_private_msg")
        req = urllib.request.Request(
            ep, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if data.get("status") == "ok" or data.get("retcode") == 0:
            return True, "napcat"
    except Exception:
        pass

    return False, "none"


def load_state():
    try:
        return json.loads(open(STATE_FILE, encoding="utf-8").read())
    except Exception:
        return {}


def save_state(st):
    try:
        open(STATE_FILE, "w", encoding="utf-8").write(
            json.dumps(st, ensure_ascii=False, indent=1))
    except Exception:
        pass


def notify_admin(text, key=None, dedup_min=60):
    """Send a private message to the admin, dedup'd by key (default = text hash).
    Returns True if it actually sent."""
    key = key or hashlib.md5(text.encode()).hexdigest()[:12]
    st = load_state()
    rec = st.get(key, {"ts": 0, "count": 0})
    count = rec.get("count", 0) + 1
    now = _ts()
    window = dedup_min * min(count, 4)          # escalation: 60,120,180,240 min
    if now - rec.get("ts", 0) < window:
        return False
    ok, ch = send("private", ADMIN_QQ, text)
    st[key] = {"ts": now, "count": count, "channel": ch}
    save_state(st)
    return ok


def notify_group(gid, text):
    return send("group", gid, text)[0]


def _parse_run(line):
    """health_runs.log line: ts|score|actions|issues|selftest|disk|mem"""
    parts = line.rstrip("\n").split("|")
    while len(parts) < 7:
        parts.append("")
    return parts


def cmd_daily():
    """Aggregate today's health_runs.log into a daily digest for the admin."""
    today = _now().strftime("%Y-%m-%d")
    lines = []
    try:
        for line in open(RUNS_LOG, encoding="utf-8"):
            if line.startswith(today):
                lines.append(line.strip())
    except FileNotFoundError:
        pass

    # message volume today (from bridge journal)
    msgs = 0
    try:
        import subprocess
        out = subprocess.run(
            ['journalctl', '-u', 'xiaonai-bridge', '--since', 'today',
             '--no-pager'], capture_output=True, text=True, timeout=20).stdout
        msgs = len(re.findall(r'PRIVATE|GROUP', out))
    except Exception:
        pass

    if not lines:
        head = f"📊 小奈日报 {today}\n今日无健康记录（health_check 未运行？）"
    else:
        issues_total = sum(1 for l in lines if l.split("|")[3].strip())
        actions_total = sum(1 for l in lines if l.split("|")[2].strip())
        self_fail = sum(1 for l in lines if "FAIL" in l.split("|")[4].upper())
        scores = [int(l.split("|")[1]) for l in lines if l.split("|")[1].lstrip("-").isdigit()]
        score_avg = sum(scores) // len(scores) if scores else "N/A"
        last = _parse_run(lines[-1])
        head = (
            f"📊 小奈日报 {today}\n"
            f"• 运行 {len(lines)} 次, 平均健康分 {score_avg}\n"
            f"• 触发动作 {actions_total} 次 / 记录问题 {issues_total} 次\n"
            f"• 自检失败 {self_fail} 次\n"
            f"• 今日消息量 {msgs} 条\n"
            f"• 当前 磁盘{last[5]}% 内存{last[6]}MB"
        )
    return notify_admin(head, key=f"daily-{today}", dedup_min=24 * 60)


def cmd_test():
    ok, ch = send("private", ADMIN_QQ, "🧪 通知通道测试")
    return f"send ok={ok} channel={ch}"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "report":
        text = args[1] if len(args) > 1 else ""
        key = None
        dedup = 60
        gid = None
        i = 2
        while i < len(args):
            if args[i] == "--key" and i + 1 < len(args):
                key = args[i + 1]; i += 2
            elif args[i] == "--dedup" and i + 1 < len(args):
                dedup = int(args[i + 1]); i += 2
            elif args[i] == "--group" and i + 1 < len(args):
                gid = int(args[i + 1]); i += 2
            else:
                i += 1
        if gid:
            ok = notify_group(gid, text)
            print(f"group notify ok={ok}")
        else:
            ok = notify_admin(text, key=key, dedup_min=dedup)
            print(f"admin notify sent={ok}")
    elif cmd == "daily":
        print(f"daily sent={cmd_daily()}")
    elif cmd == "test":
        print(cmd_test())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
