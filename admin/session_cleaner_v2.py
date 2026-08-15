#!/usr/bin/env python3
"""Session cleaner v2 — safe cleanup with idle-age gating.

Key fix: only cleans sessions that have been IDLE (no file writes) for
IDLE_THRESHOLD seconds. This prevents the race condition where cron
deletes a session file while the OpenClaw agent is actively using it,
which caused EmbeddedAttemptSessionTakeoverError.
"""
import os, json, time, glob, logging, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format='[cleaner] %(asctime)s %(message)s')
log = logging.getLogger('cleaner')

SESSIONS_DIR = Path(os.path.expanduser('~/.openclaw/agents/main/sessions'))
AGENT_DIR = Path(os.path.expanduser('~/.openclaw/agents/main/agent'))
MEMORY_DIR = Path(os.path.expanduser('~/.openclaw/agents/main/memory'))
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
BEIJING_TZ = timezone(timedelta(hours=8))

IDLE_THRESHOLD = 180   # 3 min — skip if agent might still be writing
MAX_AGE = 1800         # 30 min — force clean stuck/stale sessions
FORCE = '--force' in sys.argv


def _session_age_seconds(trajectory_path):
    try:
        return time.time() - trajectory_path.stat().st_mtime
    except FileNotFoundError:
        return 999999


def _process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def extract_summary(session_id, trajectory_path):
    try:
        with open(trajectory_path, 'r', encoding='utf-8', errors='replace') as f:
            raw = f.read()
        recent = []
        for line in raw.strip().split('\n')[-500:]:
            try:
                entry = json.loads(line.strip())
                data = entry.get('data', {})
                msgs = data.get('messages', [])
                if not msgs:
                    msgs = data.get('assistantTexts', [])
                    if msgs:
                        for t in msgs[-2:]:
                            if isinstance(t, str) and t.strip():
                                recent.append({'role': 'assistant', 'content': t[:300]})
                        continue
                for m in msgs[-3:]:
                    role = m.get('role', '')
                    content = str(m.get('content', ''))[:300]
                    if role in ('user', 'assistant') and content and content not in ('None', ''):
                        recent.append({'role': role, 'content': content})
            except Exception:
                continue
        return recent[-10:] if recent else None
    except Exception as e:
        log.warning(f'Failed extract {session_id}: {e}')
        return None


def save_memory(session_key, summary):
    safe_key = session_key.replace(':', '_').replace('-', '_')
    memory_data = {
        'updated_at': datetime.now(BEIJING_TZ).isoformat(),
        'session_key': session_key,
        'recent_context': summary,
    }
    memory_file = MEMORY_DIR / f'{safe_key}.json'
    memory_file.write_text(json.dumps(memory_data, ensure_ascii=False, indent=2))

    resume_file = AGENT_DIR / f'resume_{safe_key}.json'
    resume_file.write_text(json.dumps(memory_data, ensure_ascii=False, indent=2))


def delete_session_files(session_id):
    for f in SESSIONS_DIR.glob(f'{session_id}*'):
        f.unlink()


def clean_safe():
    sessions_file = SESSIONS_DIR / 'sessions.json'
    if not sessions_file.exists():
        log.info('No sessions.json found, nothing to clean')
        return

    try:
        sessions = json.loads(sessions_file.read_text())
    except Exception as e:
        log.error(f'Failed to read sessions.json: {e}')
        return

    cleaned = 0
    skipped_active = 0

    for session_key in list(sessions.keys()):
        info = sessions[session_key]
        sid = info.get('sessionId', '')
        if not sid:
            continue

        traj_path = SESSIONS_DIR / f'{sid}.trajectory.jsonl'
        age = _session_age_seconds(traj_path)

        # Skip active sessions (recently written = agent is using them)
        if not FORCE and age < IDLE_THRESHOLD:
            skipped_active += 1
            continue

        if age > MAX_AGE:
            log.info(f'Force-cleaning stale session {sid[:8]}... (idle {age:.0f}s)')

        # Save memory before deleting
        if traj_path.exists():
            summary = extract_summary(sid, traj_path)
            if summary:
                save_memory(session_key, summary)

        delete_session_files(sid)
        del sessions[session_key]
        cleaned += 1

    sessions_file.write_text(json.dumps(sessions, ensure_ascii=False))
    log.info(f'Cleaned {cleaned} sessions, skipped {skipped_active} active')

    # Only remove lock files whose process is dead
    for lock_file in SESSIONS_DIR.glob('*.lock'):
        try:
            pid = int(lock_file.read_text().strip())
            if not _process_running(pid):
                lock_file.unlink()
        except (ValueError, Exception):
            lock_file.unlink()

    # Clean old memories (> 7 days)
    now = time.time()
    for f in MEMORY_DIR.glob('*.json'):
        if now - f.stat().st_mtime > 604800:
            f.unlink()


def purge_session(session_key):
    """真清除：删 session 文件 + sessions.json 条目 + memory/resume。

    与 clean_safe() 的区别：clean_safe 会先 save_memory() 存摘要再删，
    下一条消息会被 bridge.py 的 _check_session_resume() 原样恢复；
    purge 是用户明确说「清除上下文」时用的，必须让上下文回不来。
    """
    sessions_file = SESSIONS_DIR / 'sessions.json'
    sessions = {}
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text())
        except Exception as e:
            log.error('Failed to read sessions.json: %s' % e)
            return 1

    sid = (sessions.get(session_key) or {}).get('sessionId', '')
    if sid:
        delete_session_files(sid)
        del sessions[session_key]
        sessions_file.write_text(json.dumps(sessions, ensure_ascii=False))
        log.info('Purged session %s... key=%s' % (sid[:8], session_key))
    else:
        log.info('No live session for key=%s (only clearing memory/resume)' % session_key)

    safe_key = session_key.replace(':', '_').replace('-', '_')
    for p in (MEMORY_DIR / ('%s.json' % safe_key),
              AGENT_DIR / ('resume_%s.json' % safe_key)):
        if p.exists():
            p.unlink()
            log.info('Removed %s' % p.name)
    return 0


if __name__ == '__main__':
    _args = sys.argv[1:]
    if '--purge-session' in _args:
        _i = _args.index('--purge-session')
        if _i + 1 >= len(_args):
            log.error('--purge-session 需要跟一个 session key')
            sys.exit(2)
        sys.exit(purge_session(_args[_i + 1]))
    clean_safe()
