#!/usr/bin/env python3
"""One-shot timed message queue for QQ bot.
Managed via CLI, consumed by scheduler_v5.py.
Usage:
  python3 admin/timed_msg.py add --group CLASS_GROUP_PLACEHOLDER --at "2026-06-02 19:00" --msg "Hello"
  python3 admin/timed_msg.py add --user 123456 --at "2026-06-02 19:00" --msg "Hello"
  python3 admin/timed_msg.py list
  python3 admin/timed_msg.py rm <id>
  python3 admin/timed_msg.py pending   # Show unsent + due
"""
import sys, json, uuid, argparse
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path('/opt/xiaonai/data')
TIMED_MSG_FILE = DATA / 'timed_msg.json'


def load():
    if TIMED_MSG_FILE.exists():
        try:
            return json.loads(TIMED_MSG_FILE.read_text())
        except:
            pass
    return []


def save(msgs):
    DATA.mkdir(parents=True, exist_ok=True)
    TIMED_MSG_FILE.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))


def _get_test_group():
    try:
        import json
        cfg = json.load(open("/opt/xiaonai/data/scheduler_config.json"))
        return cfg.get("test_group", TEST_GROUP_PLACEHOLDER)
    except:
        return TEST_GROUP_PLACEHOLDER

def add(group_id, user_id, send_at_str, message, recurring=None, recur_dow=None, recur_dom=None):
    msgs = load()
    try:
        send_dt = datetime.strptime(send_at_str, '%Y-%m-%d %H:%M')
    except ValueError:
        print(f'Error: invalid datetime format "{send_at_str}", use YYYY-MM-DD HH:MM')
        sys.exit(1)
    now = datetime.now()
    if send_dt <= now:
        print(f'Warning: send_at ({send_at_str}) is in the past, will send immediately on next scheduler check')
    entry = {
        'id': str(uuid.uuid4())[:8],
        'group_id': group_id,
        'user_id': user_id,
        'message': message,
        'send_at': send_at_str,
        'recurring': recurring,
        'recur_dow': recur_dow,
        'recur_dom': recur_dom,
        'created_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'sent': False,
        'error': None,
    }
    msgs.append(entry)
    save(msgs)
    target = f'group {group_id}' if group_id else f'user {user_id}'
    print(f'Added: [{entry["id"]}] -> {target} @ {send_at_str}')
    return entry['id']


def list_msgs(show_all=False):
    msgs = load()
    if not msgs:
        print('No timed messages')
        return
    now = datetime.now()
    for m in msgs:
        if m.get('sent') and not show_all:
            continue
        status = 'SENT' if m.get('sent') else 'PENDING'
        target = f'group {m["group_id"]}' if m.get('group_id') else f'user {m["user_id"]}'
        due = ''
        if not m.get('sent'):
            try:
                send_dt = datetime.strptime(m['send_at'], '%Y-%m-%d %H:%M')
                if send_dt <= now:
                    due = ' [DUE NOW]'
                else:
                    delta = send_dt - now
                    due = f' [in {int(delta.total_seconds()/60)}m]'
            except:
                pass
        err = f' error={m["error"]}' if m.get('error') else ''
        print(f'  [{m["id"]}] {status} -> {target} @ {m["send_at"]}{due}{err}')
        print(f'       msg: {m["message"][:80]}')


def rm(msg_id):
    msgs = load()
    before = len(msgs)
    msgs = [m for m in msgs if m['id'] != msg_id]
    if len(msgs) == before:
        print(f'Not found: {msg_id}')
        sys.exit(1)
    save(msgs)
    print(f'Removed: {msg_id}')


def get_pending():
    """Return list of unsent due messages (called by scheduler)."""
    msgs = load()
    now = datetime.now()
    pending = []
    for m in msgs:
        if m.get('sent'):
            continue
        try:
            send_dt = datetime.strptime(m['send_at'], '%Y-%m-%d %H:%M')
            if send_dt <= now:
                pending.append(m)
        except:
            pass
    return pending


def mark_sent(msg_id, error=None):
    """Mark a message as sent (called by scheduler after delivery)."""
    msgs = load()
    for m in msgs:
        if m['id'] == msg_id:
            m['sent'] = True
            m['sent_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if error:
                m['error'] = error
            break
    save(msgs)


def cleanup():
    """Remove sent messages older than 7 days."""
    msgs = load()
    now = datetime.now()
    before = len(msgs)
    msgs = [m for m in msgs if not (
        m.get('sent') and m.get('sent_at')
        and (now - datetime.strptime(m['sent_at'], '%Y-%m-%d %H:%M:%S')) > timedelta(days=7)
    )]
    if len(msgs) < before:
        save(msgs)
        print(f'Cleaned up {before - len(msgs)} old messages')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Manage one-shot timed QQ messages')
    sub = p.add_subparsers(dest='cmd')

    p_add = sub.add_parser('add')
    p_add.add_argument('--group', type=int, help='Target group ID')
    p_add.add_argument('--user', type=int, help='Target user ID')
    p_add.add_argument('--at', required=True, help='Send time: YYYY-MM-DD HH:MM')
    p_add.add_argument('--msg', required=True, help='Message text')
    p_add.add_argument('--recurring', choices=['daily', 'weekly', 'monthly'], default=None, help='Recurring: daily|weekly|monthly')
    p_add.add_argument('--dow', type=int, default=None, help='Weekly day of week (0=Mon..6=Sun)')
    p_add.add_argument('--dom', type=int, default=None, help='Monthly day of month')

    p_list = sub.add_parser('list')
    p_list.add_argument('--all', action='store_true', help='Show sent messages too')

    p_rm = sub.add_parser('rm')
    p_rm.add_argument('id', help='Message ID to remove')

    p_pending = sub.add_parser('pending')

    p_cleanup = sub.add_parser('cleanup')

    args = p.parse_args()

    if args.cmd == 'add':
        if not args.group and not args.user:
            tg = _get_test_group()
            args.group = tg
            print("[timed_msg] No target, defaulting to test group " + str(tg), file=sys.stderr)
        add(args.group, args.user, args.at, args.msg, args.recurring, args.dow, args.dom)
    elif args.cmd == 'list':
        list_msgs(show_all=args.all if hasattr(args, 'all') else False)
    elif args.cmd == 'rm':
        rm(args.id)
    elif args.cmd == 'pending':
        items = get_pending()
        if items:
            for m in items:
                target = f'group {m["group_id"]}' if m.get('group_id') else f'user {m["user_id"]}'
                print(f'  [{m["id"]}] -> {target} @ {m["send_at"]}: {m["message"][:60]}')
        else:
            print('No pending messages')
    elif args.cmd == 'cleanup':
        cleanup()
    else:
        p.print_help()
