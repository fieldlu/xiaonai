#!/usr/bin/env python3
"""Diagnostic self-test for the 小奈 QQ bot.

Runs reactively (when health_check detects a problem — unlimited while the
problem persists) or on a daily schedule (2 slots). Pure probes, no side-effect
messages: the admin report is composed and sent by health_check.sh, and the
delivery of that report doubles as the outbound-send capability check.

L1 NapCat : OneBot API get_login_info answers with status ok
L3 agent  : openclaw CLI responds to a ping (only with --full)

Usage: python3 admin/self_test.py [--full]
Output: JSON (stdout) + persisted data/self_test_state.json
Exit:   0 = all probes ok, 1 = any probe failed
"""
import json, sys, subprocess, time, urllib.request, os
from datetime import datetime, timezone, timedelta

# 09-03: health_check.sh 用绝对路径调本脚本，cwd 可能是 cron 的 HOME；
# 注入脚本所在目录 + 其父目录，兼容「根目录版(与 config 同级)」和「admin/ 子目录版(本地镜像)」。
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

BEIJING = timezone(timedelta(hours=8))
NAPCAT_API = "http://127.0.0.1:3000"
STATE_FILE = "/opt/xiaonai/data/self_test_state.json"


def _now():
    return datetime.now(BEIJING)


def level1_napcat():
    try:
        with urllib.request.urlopen(f"{NAPCAT_API}/get_login_info", timeout=5) as r:
            data = json.loads(r.read())
        ok = data.get("status") == "ok" and data.get("retcode") == 0
        return ok, (f"user_id={data.get('data', {}).get('user_id')}" if ok
                    else f"unexpected: {json.dumps(data)[:80]}")
    except Exception as e:
        return False, str(e)[:80]


def level3_agent():
    """Probe openclaw with a FRESH session key + retry.

    Uses a timestamped session key (health-selftest-<epoch>) so each probe
    starts from a clean session instead of resuming whatever the previous
    probe left behind. A reused session can carry stale context that makes
    the ping slow/timeout, which previously caused a false "L3 down" that
    triggered an unnecessary gateway restart — and that restart then killed
    the in-flight probe session, making the re-check fail too.

    Retries twice (3s apart) to absorb transient jitter before declaring
    the agent layer down.
    """
    import time as _t
    from config import bot_config  # 09-03: L3 探测跟随生效 provider，勿硬编码 MiMo

    attempts = 0
    while attempts < 3:
        attempts += 1
        sess = "health-selftest-%d" % int(_t.time())
        cmd = [
            "openclaw", "agent", "--agent", "main",
            "--model", bot_config.active_openclaw_model,
            "--thinking", "off",
            "--session-key", sess,
            "--message", "ping", "--json", "--timeout", "70",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=80)
            text = r.stdout or ""
            ok = r.returncode == 0 and len(text) > 0
            if ok:
                return True, ("rc=%s resp=%s" % (r.returncode, text[:60]))
            last_err = "rc=%s err=%s" % (r.returncode, r.stderr[:60])
        except Exception as e:
            last_err = str(e)[:80]
        if attempts < 3:
            _t.sleep(3)
    return False, last_err


def main():
    full = "--full" in sys.argv
    _t0 = time.time()
    res = {"ts": _now().isoformat()}

    l1, d1 = level1_napcat()
    res["L1_napcat"] = l1
    res["L1_detail"] = d1

    l3 = True
    if full:
        l3, d3 = level3_agent()
        res["L3_agent"] = l3
        res["L3_detail"] = d3

    res["ok"] = l1 and l3
    res["full"] = full
    res["duration_s"] = round(time.time() - _t0, 1)

    parts = [f"NapCat{'✓' if l1 else '✗'}", f"Agent{'✓' if l3 else '✗'}"]
    if not l1:
        parts.append(f"({d1})")
    if full and not l3:
        parts.append(f"({d3})")
    res["summary"] = " ".join(parts)

    try:
        open(STATE_FILE, "w", encoding="utf-8").write(
            json.dumps(res, ensure_ascii=False, indent=1))
    except Exception:
        pass

    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
