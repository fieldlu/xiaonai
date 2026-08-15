# System Health Monitor

## Every Heartbeat (Agent runs this proactively)

### 1. Service Check
Run: `systemctl is-active xiaonai-bridge xiaonai-qq && systemctl --user is-active openclaw-gateway`
- If any service dead → restart it immediately
- If NapCat active but no recent logs → restart QQ+Bridge

### 2. Session Health
Run: `ls ~/.openclaw/agents/main/sessions/*.lock 2>/dev/null`
- If locks found → check if PID is still running (`ps -p <pid>`)
- If PID dead → remove stale lock file
- If PID alive (e.g. heartbeat node process) → keep lock, it's legitimate
- Run: `python3 /opt/xiaonai/session_cleaner.py --dry-run`
- If >3 sessions flagged → run cleaner for real

### 3. Message Flow Check
Run: `sudo journalctl -u xiaonai-bridge --since "15 min" --no-pager | grep -c "PRIVATE\|GROUP"`
- If 0 messages in 15 min AND services are active → possible silent disconnect
- Restart QQ+Bridge to re-establish connection

### 4. Disk + Memory
Run: `df -h / | tail -1` and `free -h | grep Mem`
- If disk >90% → clean old logs
- If memory <500MB free → restart QQ (heaviest)

### 5. Self-Improving Maintenance
- Read `~/self-improving/heartbeat-rules.md`
- Check memory.md line count (<100 target)
- Move stale entries to archive
- Update `~/self-improving/heartbeat-state.md`

### 6. Report (only if action taken)
- If any fix was applied → send summary to ADMIN_NAME via QQ
- Format: "🔧 自动维护: [做了什么] [结果]"
- If all healthy → silent (no noise)
- NOTE: 0 messages in journalctl is normal during low-activity periods (late night, no group chat activity). Only alert if services are active AND no messages for >1 hour AND it's during active hours (8AM-11PM).

## Self-Improving Check
- Read `skills/self-improving/heartbeat-rules.md`
- Use `~/self-improving/heartbeat-state.md` for last-run markers
- If no file changed since last reviewed change, return HEARTBEAT_OK

## Memory Health (daily)
- Check `~/self-improving/memory.md` line count (target <100)
- Move entries unused for 30+ days to `~/self-improving/archive/`
- Verify `xiaonai_memory.py` data intact (`ls /opt/xiaonai/data/memory/users/ | wc -l` users)
- Verify `session_cleaner.py` exists and is runnable (`python3 /opt/xiaonai/session_cleaner.py --dry-run; echo EXIT:$?`)
