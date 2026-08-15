#!/bin/bash
# ============================================================================
# 小奈 QQ bot — Robust health check & self-healing
# Runs as user `ubuntu` via cron (uses NOPASSWD sudo for system services).
#
# Responsibilities:
#   1. Restart dead system services  (restart→verify→retry, crash-loop throttled)
#   2. Restart unresponsive openclaw-gateway (user service, HTTP probe)
#   3. Clean stale session locks      (PID validated — no blind kill -9)
#   4. Detect silent QQ (NapCat up but 0 messages for a long window)
#   5. Disk / memory pressure checks  (log + safe cleanup, no risky deletions)
#   6. Rotate own log
#   7. Publish machine-readable state (JSON) + non-zero exit on un-resolved issues
#
# Robustness guarantees (vs the old version):
#   - flock: never run concurrently (cron overlaps / manual runs)
#   - set -u + pipefail + fully quoted: no silent misbehavior
#   - sudo for systemd system services (bare `systemctl restart` failed silently
#     under the ubuntu cron — "Interactive authentication required")
#   - restart-and-verify with retry; crash-loop throttle stops thrash
#   - PID-validated lock cleanup (only kills processes that actually hold a session)
#   - hardened silent-QQ uptime parsing (clamped; parse failure never triggers)
#   - every unresolved problem => exit code 1 + state JSON
# ============================================================================

set -u
set -o pipefail

LOG=/var/log/health_check.log
STATE=/opt/xiaonai/data/health_state.json
LOCK=/tmp/xiaonai-health.lock
CRASH_DIR=/var/tmp/xiaonai-crash
SESSIONS_DIR="${HOME}/.openclaw/agents/main/sessions"
NOW="$(date -Iseconds)"
FAIL=0
ACTIONS=""
SILENT=0
LOCK_CLEANED=0

log()  { printf '[%s] %s\n' "$NOW" "$*" >>"$LOG"; }
warn() { log "WARN $*"; }
err()  { log "ERROR $*"; FAIL=1; }

# ---------- single instance ----------
exec 9>"$LOCK"
if ! flock -n 9; then
  log "skip: another instance running (flock)"
  exit 0
fi
log "health check begin"

# ---------- helpers ----------
svc_active() { systemctl is-active --quiet "$1"; }

# restart a system service (needs sudo under ubuntu cron), verify it comes up
restart_svc() {
  local svc="$1" i
  sudo -n systemctl restart "$svc" 2>>"$LOG" || { log "  $svc restart command failed"; return 1; }
  for i in 1 2 3 4 5 6 7 8; do
    svc_active "$svc" && { log "  $svc revived (after ${i}x3s)"; return 0; }
    sleep 3
  done
  log "  $svc NOT active after restart"
  return 1
}

# restart openclaw-gateway (systemd --user service); works as ubuntu or root
restart_gateway() {
  local uid_user i
  uid_user="$(id -u ubuntu 2>/dev/null || echo 1000)"
  local cmd=(systemctl --user restart openclaw-gateway)
  if [ "$(id -u)" -eq 0 ]; then
    XDG_RUNTIME_DIR="/run/user/$uid_user" sudo -u ubuntu "${cmd[@]}" 2>>"$LOG"
  else
    XDG_RUNTIME_DIR="/run/user/$uid_user" "${cmd[@]}" 2>>"$LOG"
  fi || true
  for i in 1 2 3 4 5 6 7 8; do
    if curl -s --connect-timeout 3 http://127.0.0.1:18789/health >/dev/null 2>&1; then
      log "  openclaw-gateway revived (after ${i}x3s)"; return 0
    fi
    sleep 3
  done
  log "  openclaw-gateway still unresponsive after restart"
  return 1
}

# crash-loop throttle: >3 restart attempts of the same svc in a 45-min window
# -> stop auto-restarting (prevents thrash), still alert. Natural retry resumes later.
mark_restart() {
  local svc="$1" n
  mkdir -p "$CRASH_DIR" 2>/dev/null || true
  find "$CRASH_DIR" -type f -mmin +45 -delete 2>/dev/null || true
  date +%s >>"$CRASH_DIR/$svc"
  n="$(wc -l <"$CRASH_DIR/$svc" 2>/dev/null || echo 0)"
  n="${n:-0}"
  if [ "$n" -ge 4 ]; then
    err "$svc crash-loop: ${n}x restarts in 45min, auto-restart suspended"
    return 1
  fi
  return 0
}

# ---------- 1. system services ----------
for svc in xiaonai-bridge xiaonai-qq xiaonai-scheduler xiaonai-consult xiaonai-http-proxy; do
  if svc_active "$svc"; then continue; fi
  log "  $svc dead — restarting"
  if mark_restart "$svc"; then
    if restart_svc "$svc"; then ACTIONS="$ACTIONS $svc"; else err "$svc failed to revive"; fi
  fi
done

# ---------- 2. openclaw gateway (HTTP probe) ----------
if ! curl -s --connect-timeout 3 http://127.0.0.1:18789/health >/dev/null 2>&1; then
  log "  openclaw-gateway unresponsive — restarting"
  if mark_restart openclaw-gateway; then
    if restart_gateway; then ACTIONS="$ACTIONS openclaw-gateway"; else err "openclaw-gateway failed to revive"; fi
  fi
fi

# ---------- 2.5 mimo-proxy (MiMo reasoning proxy, user service) ----------
if ! curl -s --connect-timeout 3 http://127.0.0.1:8898/health >/dev/null 2>&1; then
  log "  mimo-proxy unresponsive — restarting"
  if mark_restart mimo-proxy; then
    if XDG_RUNTIME_DIR="/run/user/$(id -u ubuntu 2>/dev/null || echo 1000)" systemctl --user restart mimo-proxy 2>>"$LOG"; then
      ACTIONS="$ACTIONS mimo-proxy"
      log "  mimo-proxy restarted"
    else
      err "mimo-proxy failed to revive"
    fi
  fi
fi

# ---------- 3. stale session locks (PID-validated) ----------
for lock in "$SESSIONS_DIR"/*.lock; do
  [ -f "$lock" ] || continue
  PID="$(head -1 "$lock" 2>/dev/null | tr -dc '0-9')"
  if [ -n "$PID" ] && [ -r "/proc/$PID/cmdline" ]; then
    if grep -qaE 'openclaw|node|agent' "/proc/$PID/cmdline" 2>/dev/null; then
      log "  killing session holder PID $PID from $lock"
      kill -9 "$PID" 2>/dev/null || true
    else
      log "  $lock PID $PID is not a live session proc — removing lock only"
    fi
  elif [ -n "$PID" ]; then
    log "  $lock PID $PID already gone — removing lock"
  fi
  rm -f "$lock" 2>/dev/null && LOCK_CLEANED=$((LOCK_CLEANED + 1))
done
[ "$LOCK_CLEANED" -gt 0 ] && { log "  cleaned ${LOCK_CLEANED} stale lock(s)"; ACTIONS="$ACTIONS locks:$LOCK_CLEANED"; }

# ---------- 4. hung NapCat detection (robust) ----------
# Old logic restarted on "0 messages in 30min" — a WEAK signal that false-positives
# on every quiet window (and only now works since restarts use sudo). Real failure
# mode of NapCat is a HUNG process: systemd still says active, but the OneBot API
# no longer answers. So restart only when the liveness probe actually fails.
if svc_active xiaonai-qq && svc_active xiaonai-bridge; then
  TS="$(systemctl show xiaonai-qq -p ActiveEnterTimestamp --value 2>/dev/null)"
  UP=0; NOW_S="$(date +%s)"
  if [ -n "$TS" ]; then UP="$(date -d "$TS" +%s 2>/dev/null || echo 0)"; fi
  UP="${UP:-0}"
  # only trust a parsed, non-future uptime — parse failure must never trigger
  if [ "$UP" -gt 0 ] && [ "$UP" -lt "$NOW_S" ] && [ $((NOW_S - UP)) -gt 7200 ]; then
    if ! curl -s --connect-timeout 3 --max-time 5 http://127.0.0.1:3000/get_login_info 2>/dev/null \
        | grep -q '"status": "ok"'; then
      log "  NapCat unresponsive at :3000 (uptime>2h) — restart qq+bridge"
      if mark_restart silent-qq; then
        restart_svc xiaonai-qq && sleep 5 && restart_svc xiaonai-bridge
        SILENT=1; ACTIONS="$ACTIONS silent-qq"
      fi
    fi
  fi
fi

# ---------- 5. disk pressure ----------
DISK_USED="$(df / 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')"
DISK_USED="${DISK_USED:-0}"
if [ "$DISK_USED" -ge 95 ]; then
  err "disk ${DISK_USED}% full — freeing space"
  : >"$LOG" 2>/dev/null || true
  truncate -s 0 /tmp/session_cleaner.log /tmp/alarm_check.log /tmp/proactive_check.log 2>/dev/null || true
  journalctl --vacuum-size=200M >/dev/null 2>&1 || true   # systemd journal is a common hog
  DISK_USED="$(df / 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')"
  DISK_USED="${DISK_USED:-0}"
  log "  disk after cleanup: ${DISK_USED}%"
elif [ "$DISK_USED" -ge 90 ]; then
  warn "disk ${DISK_USED}% used"
fi

# ---------- 6. memory pressure + auto-recovery ----------
MEM_AVAIL="$(free -m 2>/dev/null | awk '/Mem:/ {print $7}')"
MEM_AVAIL="${MEM_AVAIL:-0}"
MEM_ACTION=""
if [ "$MEM_AVAIL" -gt 0 ] && [ "$MEM_AVAIL" -lt 150 ]; then
  # critically low → restart bridge (the memory-heavy python process) to release RAM
  log "  memory ${MEM_AVAIL}MB critically low — restarting bridge to free memory"
  if mark_restart mem-recovery; then
    restart_svc xiaonai-bridge && MEM_ACTION="内存不足→重启bridge释放"
    sleep 2
    MEM_AVAIL="$(free -m 2>/dev/null | awk '/Mem:/ {print $7}')"
    MEM_AVAIL="${MEM_AVAIL:-0}"
    if [ "$MEM_AVAIL" -gt 0 ] && [ "$MEM_AVAIL" -lt 150 ]; then
      log "  memory still low (${MEM_AVAIL}MB) — restarting NapCat"
      restart_svc xiaonai-qq && MEM_ACTION="${MEM_ACTION}+NapCat"
    fi
  fi
elif [ "$MEM_AVAIL" -lt 200 ]; then
  warn "memory ${MEM_AVAIL}MB low"
fi

# ---------- 6b. WARP memory guard (08-15) ----------
# Upgraded to 2026.6 which fixed the main-loop leak (20h -> 38MB, 0 growth).
# Daily 04:30 restart removed — it created a needless unstable window each day.
# Keep an on-demand guard: restart warp-svc only if its RSS exceeds 500MB
# (leak recurrence safety net). warp_restart.sh verifies proxy after restart.
WARP_RSS="$(ps -o rss= -C warp-svc 2>/dev/null | head -1 | tr -dc '0-9')"
WARP_RSS="${WARP_RSS:-0}"
if [ "$WARP_RSS" -gt 512000 ]; then
  log "  warp-svc RSS ${WARP_RSS}KB > 500MB — restarting (leak guard)"
  if mark_restart warp-mem; then
    if timeout 90 /opt/xiaonai/scripts/warp_restart.sh >/dev/null 2>&1; then
      log "  warp-svc restarted, proxy OK"
      ACTIONS="$ACTIONS warp-mem"
    else
      err "warp-svc leak restart failed / proxy not OK"
    fi
  fi
fi

# ---------- 7. rotate own log ----------
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
  mv "$LOG" "$LOG.1" 2>/dev/null || true
  log "rotated (log >5MB)"
fi

# ---------- 8. run counter (for state) ----------
RUN_FILE=/opt/xiaonai/data/health_run_counter
RUN_N=0
[ -f "$RUN_FILE" ] && RUN_N="$(cat "$RUN_FILE" 2>/dev/null || echo 0)"
RUN_N="${RUN_N:-0}"
RUN_N=$((RUN_N + 1))
echo "$RUN_N" >"$RUN_FILE" 2>/dev/null || true

# ---------- 9. self-test — on-demand (problem detected) or daily schedule ----------
# Reactive: run whenever a problem is detected, unlimited while it persists.
# Scheduled: daily slots 08:00 / 15:00 (full probe), report once per slot.
HM="$(date +%H%M)"
SLOT=""
[ "$HM" -ge 0800 ] && [ "$HM" -lt 0815 ] && SLOT="0800"
[ "$HM" -ge 1500 ] && [ "$HM" -lt 1515 ] && SLOT="1500"

PROBLEM=0
[ "$FAIL" -eq 1 ] && PROBLEM=1
[ "$DISK_USED" -ge 90 ] && PROBLEM=1
[ "$MEM_AVAIL" -lt 200 ] && PROBLEM=1
[ -n "$ACTIONS" ] && PROBLEM=1

SELF_OK="not-run"
SELF_SUMMARY=""
if [ "$PROBLEM" -eq 1 ] || [ -n "$SLOT" ]; then
  # full probe (L1 NapCat + L3 agent) so failures can be diagnosed AND fixed
  SELF_JSON="$(python3 /opt/xiaonai/admin/self_test.py --full 2>/dev/null)"
  if echo "$SELF_JSON" | grep -q '"ok": true'; then
    SELF_OK="pass"
  else
    SELF_OK="fail"
  fi
  SELF_SUMMARY="$(echo "$SELF_JSON" | grep -o '"summary": "[^"]*"' | head -1 | sed 's/.*: "//;s/"$//')"
  log "  self-test ($([ -n "$SLOT" ] && echo "scheduled-$SLOT" || echo reactive)) -> $SELF_OK ${SELF_SUMMARY}"

  # ---- self-heal: targeted repair for the failing probe, then re-verify ----
  if [ "$SELF_OK" = "fail" ]; then
    log "  self-test failed — attempting targeted repair"
    if echo "$SELF_JSON" | grep -q '"L1_napcat": false'; then
      log "    L1 NapCat down -> restart qq + bridge"
      if mark_restart selftest-napcat; then
        restart_svc xiaonai-qq && sleep 5 && restart_svc xiaonai-bridge
      fi
    fi
    if echo "$SELF_JSON" | grep -q '"L3_agent": false'; then
      log "    L3 agent down -> restart openclaw-gateway"
      if mark_restart selftest-agent; then
        restart_gateway
      fi
    fi
    # re-verify after repair; retry up to 3x / 10s apart to absorb the
    # gateway restart recovery window (08-11: gateway takes ~30s to be ready
    # after restart, a single immediate re-check was flapping)
    SELF_OK="fail"
    for _i in 1 2 3; do
      sleep 10
      SELF_JSON2="$(python3 /opt/xiaonai/admin/self_test.py --full 2>/dev/null)"
      if echo "$SELF_JSON2" | grep -q '"ok": true'; then
        SELF_OK="fixed"
        SELF_SUMMARY="$(echo "$SELF_JSON2" | grep -o '"summary": "[^"]*"' | head -1 | sed 's/.*: "//;s/"$//')"
        log "  self-heal OK (retry ${_i}) -> ${SELF_SUMMARY}"
        break
      fi
    done
    if [ "$SELF_OK" = "fail" ]; then
      err "self-test still failing after repair"
    fi
  fi
fi

# ---------- 10. health score ----------
SCORE=100
[ "$FAIL" -eq 1 ] && SCORE=$((SCORE - 20))
[ "$DISK_USED" -ge 90 ] && SCORE=$((SCORE - 10))
[ "$MEM_AVAIL" -lt 200 ] && SCORE=$((SCORE - 10))
[ "$SELF_OK" = "fail" ] && SCORE=$((SCORE - 20))
[ "$SCORE" -lt 0 ] && SCORE=0

# ---------- 11. persist run record ----------
echo "$(date +%Y-%m-%d)|$SCORE|$ACTIONS|$([ "$FAIL" -eq 1 ] && echo problem || echo ok)|$SELF_OK|$DISK_USED|$MEM_AVAIL" \
  >>/opt/xiaonai/data/health_runs.log 2>/dev/null || true

# ---------- 12. notify admin (private only) ----------
NOTIFY_MSG="🤖 健康自检 $(date +%H:%M) · 健康分 ${SCORE}/100"
[ -n "$ACTIONS" ] && NOTIFY_MSG="${NOTIFY_MSG}\n⚙️ 动作:${ACTIONS}"
[ -n "$MEM_ACTION" ] && NOTIFY_MSG="${NOTIFY_MSG}\n🔄 ${MEM_ACTION}"
[ "$FAIL" -eq 1 ] && NOTIFY_MSG="${NOTIFY_MSG}\n⚠️ 存在报警项(详见 /var/log/health_check.log)"
NOTIFY_MSG="${NOTIFY_MSG}\n🧪 自检: ${SELF_SUMMARY:-未触发}"

if [ -n "$SLOT" ]; then
  # scheduled self-test -> always report to admin once per slot per day
  python3 /opt/xiaonai/admin/health_notify.py report \
    "$(printf '%b\n' "${NOTIFY_MSG}" "磁盘${DISK_USED}% · 内存${MEM_AVAIL}MB")" \
    --key "sched-$(date +%Y%m%d)-${SLOT}" --dedup 1440 >>"$LOG" 2>&1 || true
elif [ "$PROBLEM" -eq 1 ]; then
  # reactive -> report while problems persist (dedup 55min, escalating)
  python3 /opt/xiaonai/admin/health_notify.py report \
    "$(printf '%b\n' "${NOTIFY_MSG}" "磁盘${DISK_USED}% · 内存${MEM_AVAIL}MB")" \
    --key "run-$(date +%Y%m%d)" --dedup 55 >>"$LOG" 2>&1 || true
fi

# ---------- 13. daily digest (~21:30, once/day) ----------
if [ "$HM" -ge 2130 ] && [ "$HM" -lt 2145 ]; then
  python3 /opt/xiaonai/admin/health_notify.py daily >>"$LOG" 2>&1 || true
fi

# ---------- 14. publish machine-readable state ----------
{
  printf '{\n'
  printf '  "ts": "%s",\n' "$NOW"
  printf '  "healthy": %s,\n' "$([ "$FAIL" -eq 0 ] && echo true || echo false)"
  printf '  "exit_code": %s,\n' "$FAIL"
  printf '  "health_score": %s,\n' "$SCORE"
  printf '  "self_test": "%s",\n' "$SELF_OK"
  printf '  "self_test_summary": "%s",\n' "$SELF_SUMMARY"
  printf '  "mem_action": "%s",\n' "$MEM_ACTION"
  printf '  "run": %s,\n' "$RUN_N"
  printf '  "disk_percent": %s,\n' "$DISK_USED"
  printf '  "mem_available_mb": %s,\n' "$MEM_AVAIL"
  printf '  "silent_qq_triggered": %s,\n' "$([ "$SILENT" -eq 1 ] && echo true || echo false)"
  printf '  "locks_cleaned": %s,\n' "$LOCK_CLEANED"
  printf '  "actions": "%s"\n' "$ACTIONS"
  printf '}\n'
} >"$STATE" 2>/dev/null || true
chmod 644 "$STATE" 2>/dev/null || true

log "health check done (exit=$FAIL)"
exit "$FAIL"
