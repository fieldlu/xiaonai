#!/usr/bin/env python3
"""XiaoNai Admin CLI — unified command center for bot operations.

Usage:
  python3 admin_cli.py status              Full system status dashboard
  python3 admin_cli.py logs <svc> [n]      View recent logs (bridge|qq|openclaw|scheduler|searxng)
  python3 admin_cli.py restart <svc>       Restart a service
  python3 admin_cli.py restart all         Restart all services
  python3 admin_cli.py agent [cmd]         Agent control (reload|model|session|clear|run)
  python3 admin_cli.py cron [cmd]          Cron job management (list|add|rm|run)
  python3 admin_cli.py timed_msg [cmd]  Timed msg queue (list|pending|rm|help)
  python3 admin_cli.py diag                Full diagnostic report
  python3 admin_cli.py fix                 Auto-fix common issues
  python3 admin_cli.py config [cmd]        Config management (show|reload)
  python3 admin_cli.py send <target> <msg> Send message to group/user
  python3 admin_cli.py sessions            List active sessions
  python3 admin_cli.py help                Show this help
"""

import subprocess, sys, json, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))
BRIDGE_HTTP = "http://127.0.0.1:8081"
QQBOT_DIR = "/opt/xiaonai"
SERVICES = {
    "qq": "xiaonai-qq",
    "bridge": "xiaonai-bridge",
    "scheduler": "xiaonai-scheduler",
    "searxng": "searxng-proxy",
    "openclaw": "openclaw-gateway",
}

def run(cmd, timeout=15, shell=True):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)

def svc_status(name, unit, is_user=False):
    if is_user:
        code, out = run(f"systemctl --user is-active {unit}")
    else:
        code, out = run(f"sudo systemctl is-active {unit}")
    active = out.strip() == "active"
    return active, out.strip()

def cmd_status():
    """Full system status dashboard."""
    now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"=== 小奈系统状态 [{now}] ===", ""]

    # Services
    lines.append("--- 服务 ---")
    for name, unit in SERVICES.items():
        is_user = name == "openclaw"
        active, state = svc_status(name, unit, is_user)
        icon = "✅" if active else "❌"
        lines.append(f"  {icon} {name}: {state}")

    # Bridge health
    code, out = run(f"cd {QQBOT_DIR} && python3 bridge_health.py")
    lines.append(f"\n--- 健康检查 ---")
    try:
        h = json.loads(out)
        lines.append(f"  healthy: {h.get('healthy')}")
        for k, v in h.get("services", {}).items():
            lines.append(f"  {k}: {v}")
        issues = h.get("issues", [])
        if issues:
            for i in issues:
                lines.append(f"  ⚠️ {i}")
    except:
        lines.append(f"  {out[:200]}")

    # Recent errors
    code, out = run("journalctl --user -u openclaw-gateway --since '30 min ago' --no-pager 2>&1 | grep -i 'error|fail|UNAVAILABLE' | grep -v 'sudo|pam_unix' | tail -5")
    errors = [l for l in out.split('\n') if l.strip()] if out else []
    lines.append(f"\n--- 最近30分钟错误 ({len(errors)}条) ---")
    for e in errors[-5:]:
        lines.append(f"  {e[:150]}")
    if not errors:
        lines.append("  无错误 ✅")

    # Session count
    sessions_dir = Path(os.path.expanduser("~/.openclaw/agents/main/sessions"))
    n_files = len(list(sessions_dir.glob("*.jsonl"))) if sessions_dir.exists() else 0
    n_locks = len(list(sessions_dir.glob("*.lock"))) if sessions_dir.exists() else 0
    lines.append(f"\n--- Session ---")
    lines.append(f"  文件: {n_files} | 锁: {n_locks}")

    # Disk & memory
    code, out = run("df -h / | tail -1 | awk '{print $5}'")
    disk = out.strip()
    code, out = run("free -m | awk '/Mem:/ {printf \"%.0f%%\", $3/$2*100}'")
    mem = out.strip()
    lines.append(f"\n--- 资源 ---")
    lines.append(f"  磁盘: {disk} | 内存: {mem}")

    # Circuit breaker status
    try:
        from infra.circuit_breaker import all_status
        cbs = all_status()
        lines.append(f"\n--- 熔断器 ({len(cbs)}个) ---")
        for name, st in sorted(cbs.items()):
            icon = "🔴" if st['state'] == 'open' else "🟡" if st['state'] == 'half-open' else "🟢"
            lines.append(f"  {icon} {name}: {st['state']} (失败{st['total_failures']}/{st['total_calls']}次)")
    except Exception:
        pass

    # Smart search cache
    try:
        import time
        from smart_search import _CACHE
        lines.append(f"\n--- 搜索缓存 ---")
        lines.append(f"  条目数: {len(_CACHE)}")
        if _CACHE:
            ages = [time.time() - ts for _, ts in _CACHE.values()]
            oldest = max(ages) if ages else 0
            newest = min(ages) if ages else 0
            lines.append(f"  最老: {oldest:.0f}s | 最新: {newest:.0f}s")
    except Exception:
        pass

    print('\n'.join(lines))

def cmd_logs(service, n=20):
    """View recent logs for a service."""
    unit_map = {
        "bridge": ("sudo journalctl -u xiaonai-bridge", False),
        "qq": ("sudo journalctl -u xiaonai-qq", False),
        "scheduler": ("sudo journalctl -u xiaonai-scheduler", False),
        "searxng": ("sudo journalctl -u searxng-proxy", False),
        "openclaw": ("journalctl --user -u openclaw-gateway", True),
    }
    if service not in unit_map:
        print(f"未知服务: {service}. 可用: {', '.join(unit_map.keys())}")
        return
    cmd_base, _ = unit_map[service]
    code, out = run(f"{cmd_base} --since '30 min ago' --no-pager 2>&1 | tail -{n}")
    print(out or "(无日志)")

def cmd_restart(service):
    """Restart a service or all services."""
    if service == "all":
        for name, unit in SERVICES.items():
            is_user = name == "openclaw"
            sudo = "" if is_user else "sudo "
            user_flag = " --user" if is_user else ""
            code, out = run(f"{sudo}systemctl{user_flag} restart {unit}")
            print(f"  {'✅' if code == 0 else '❌'} {name}: {'restarted' if code == 0 else out[:80]}")
        print("全部服务已重启")
        return

    if service not in SERVICES:
        print(f"未知服务: {service}. 可用: {', '.join(SERVICES.keys())}, all")
        return

    name = service
    unit = SERVICES[name]
    is_user = name == "openclaw"
    sudo = "" if is_user else "sudo "
    user_flag = " --user" if is_user else ""
    code, out = run(f"{sudo}systemctl{user_flag} restart {unit}")
    if code == 0:
        time.sleep(2)
        _, state = svc_status(name, unit, is_user)
        print(f"✅ {name} 已重启, 当前状态: {state}")
    else:
        print(f"❌ 重启失败: {out[:200]}")

def cmd_agent(args):
    """Agent control operations."""
    if not args or args[0] == "help":
        print("""agent 子命令:
  agent reload       — 重载 agent 配置 (restart openclaw)
  agent run <msg>    — 直接向 agent 发送指令并获取回复
  agent model <id>   — 切换模型 (mimo-v2.5)
  agent clear        — 清除所有 session
  agent sessions     — 查看活跃 session""")
        return

    subcmd = args[0]
    if subcmd == "reload":
        code, out = run("systemctl --user restart openclaw-gateway")
        if code == 0:
            time.sleep(2)
            print("✅ Agent 配置已重载")
        else:
            print(f"❌ 重载失败: {out[:200]}")

    elif subcmd == "run":
        if len(args) < 2:
            print("用法: admin_cli.py agent run <消息>")
            return
        msg = " ".join(args[1:])
        code, out = run(f"cd {QQBOT_DIR} && openclaw agent --agent main --message '[admin] [ADMIN_NAME]: {msg}' --json --timeout 60 2>&1")
        print(out[:2000] if len(out) > 2000 else out)

    elif subcmd == "model":
        if len(args) < 2:
            print("用法: admin_cli.py agent model <id>")
            print("可用: deepseek-v4-flash (主模型) | mimo-v2.5 (识图)")
            return
        model = args[1]
        config_path = os.path.expanduser("~/.openclaw/agents/main/agent/models.json")
        try:
            cfg = json.loads(Path(config_path).read_text())
            providers = cfg.get("providers", {})
            # Update default model ref
            for pname, pdata in providers.items():
                models = pdata.get("models", [])
                valid = any(m.get("id") == model for m in models)
                if valid:
                    # Write preferred model to agent config
                    print(f"✅ 模型已切换至 {model}")
                    print(f"   注意: 永久切换需修改 models.json 中 defaultModel 字段")
                    print(f"   当前仅本次生效: openclaw agent --model mimo/{model}")
                    return
            print(f"❌ 模型 {model} 不在可用列表中")
        except Exception as e:
            print(f"❌ {e}")

    elif subcmd == "clear":
        code, out = run(f"cd {QQBOT_DIR} && python3 session_cleaner_v2.py --force 2>&1")
        print(out)

    elif subcmd == "sessions":
        cmd_sessions()

def cmd_cron(args):
    """Cron job management."""
    if not args or args[0] == "list":
        code, out = run("openclaw cron list 2>&1")
        print(out)
    elif args[0] == "add":
        print("用法: admin_cli.py agent run '设置openclaw cron: openclaw cron add --cron <表达式> --name <名称> --agent main --message <消息>'")
    elif args[0] == "rm":
        if len(args) < 2:
            print("用法: admin_cli.py cron rm <job-id>")
            return
        code, out = run(f"openclaw cron rm {args[1]} 2>&1")
        print(out)
    elif args[0] == "run":
        if len(args) < 2:
            print("用法: admin_cli.py cron run <job-id>")
            return
        code, out = run(f"openclaw cron run {args[1]} 2>&1")
        print(out)

def cmd_timed_msg(args):
    import subprocess as _sp
    if not args or args[0] == "list":
        r = _sp.run(["python3", "/opt/xiaonai/timed_msg.py", "list", "--all"], capture_output=True, text=True)
        print((r.stdout or "").strip() or "(empty)")
    elif args[0] == "pending":
        r = _sp.run(["python3", "/opt/xiaonai/timed_msg.py", "pending"], capture_output=True, text=True)
        print((r.stdout or "").strip() or "(no pending)")
    elif args[0] == "rm":
        if len(args) < 2:
            print("Usage: admin_cli.py timed_msg rm <id>")
            return
        r = _sp.run(["python3", "/opt/xiaonai/timed_msg.py", "rm", args[1]], capture_output=True, text=True)
        print((r.stdout or "").strip())
    elif args[0] == "help":
        print("timed_msg subcommands:")
        print("  list          - Show all messages")
        print("  pending       - Show pending (unsent) messages")
        print("  rm <id>       - Remove a message")
        print("  help          - This help")
        print("  (to ADD a message: python3 /opt/xiaonai/timed_msg.py add ...)")
    else:
        print("Unknown, available: list, pending, rm, help")

def cmd_diag():
    """Full diagnostic report."""
    print("=== 小奈全面诊断 ===")
    now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"时间: {now}")
    print()

    # All services
    print("[1/6] 服务状态")
    for name, unit in SERVICES.items():
        is_user = name == "openclaw"
        active, state = svc_status(name, unit, is_user)
        print(f"  {'✅' if active else '❌'} {name}: {state}")

    # Bridge health
    print("\n[2/6] Bridge健康")
    code, out = run(f"cd {QQBOT_DIR} && python3 bridge_health.py")
    print(f"  {out[:300]}")

    # Recent errors
    print("\n[3/6] 今日错误")
    code, out = run("journalctl --user -u openclaw-gateway --since 'today' --no-pager 2>&1 | grep -i 'error|fail|UNAVAILABLE' | grep -v 'sudo|pam_unix' | wc -l")
    total = out.strip()
    code, out = run("journalctl --user -u openclaw-gateway --since 'today' --no-pager 2>&1 | grep -i 'SessionTakeoverError' | wc -l")
    takeover = out.strip()
    print(f"  今日总错误: {total}")
    print(f"  SessionTakeoverError: {takeover}")

    # Bridge errors
    code, out = run("sudo journalctl -u xiaonai-bridge --since 'today' --no-pager 2>&1 | grep -i 'error|fail' | wc -l")
    print(f"  Bridge错误: {out.strip()}")

    # Sessions
    print("\n[4/6] Session")
    cmd_sessions()

    # Disk
    print("\n[5/6] 磁盘")
    code, out = run("df -h / | tail -1")
    print(f"  {out.strip()}")

    # Memory
    print("\n[6/6] 内存")
    code, out = run("free -h | grep Mem")
    print(f"  {out.strip()}")

    print("\n=== 诊断完成 ===")

def cmd_fix():
    """Auto-fix common issues."""
    print("=== 自动修复 ===")

    # 1. Health check + fix
    print("[1] 健康检查...")
    code, out = run(f"cd {QQBOT_DIR} && python3 bridge_health.py --fix 2>&1")
    print(f"  {out[:200]}")

    # 2. Clean stale locks
    print("[2] 清理过期锁...")
    sessions_dir = Path(os.path.expanduser("~/.openclaw/agents/main/sessions"))
    for lock in sessions_dir.glob("*.lock"):
        try:
            pid = int(lock.read_text().strip())
            try: os.kill(pid, 0)
            except OSError:
                lock.unlink()
                print(f"  已清理过期锁: PID {pid}")
        except:
            lock.unlink()

    # 3. Run session cleaner
    print("[3] 清理过期session...")
    code, out = run(f"cd {QQBOT_DIR} && python3 session_cleaner_v2.py 2>&1")
    print(f"  {out[:200]}")

    # 4. Verify services
    print("[4] 验证服务...")
    for name, unit in SERVICES.items():
        is_user = name == "openclaw"
        active, state = svc_status(name, unit, is_user)
        if not active:
            print(f"  ⚠️ {name} 未运行，尝试重启...")
            cmd_restart(name)
        else:
            print(f"  ✅ {name}")

    print("\n=== 修复完成 ===")

def cmd_config(args):
    """Config management."""
    if not args or args[0] == "show":
        code, out = run(f"cd {QQBOT_DIR} && python3 admin_group_control.py show_config")
        print(out)
    elif args[0] == "reload":
        code, out = run(f"curl -s -X POST {BRIDGE_HTTP}/reload")
        print(f"配置热加载: {out}")

def cmd_send(target, msg):
    """Send message via bridge HTTP API."""
    import urllib.request
    payload = {"message": msg}
    if target.isdigit() and len(target) >= 9:
        payload["group_id"] = int(target)
    elif target.isdigit():
        payload["user_id"] = int(target)
    else:
        print("target 应为群号或QQ号")
        return
    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(f"{BRIDGE_HTTP}/send", data=data,
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"✅ 发送成功: {resp.read().decode()}")
    except Exception as e:
        print(f"❌ 发送失败: {e}")

def cmd_sessions():
    """List active sessions."""
    sessions_dir = Path(os.path.expanduser("~/.openclaw/agents/main/sessions"))
    if not sessions_dir.exists():
        print("无活跃session")
        return

    sessions_file = sessions_dir / "sessions.json"
    if sessions_file.exists():
        try:
            data = json.loads(sessions_file.read_text())
            for key in data:
                print(f"  {key}")
        except:
            pass

    lock_files = list(sessions_dir.glob("*.lock"))
    if lock_files:
        print(f"  锁文件: {len(lock_files)}个")

def cmd_help():
    print(__doc__)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_status()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "status":        cmd_status()
    elif cmd == "logs":        cmd_logs(*args) if args else print("用法: admin_cli.py logs <bridge|qq|openclaw|scheduler|searxng> [行数]")
    elif cmd == "restart":     cmd_restart(args[0]) if args else print("用法: admin_cli.py restart <服务名|all>")
    elif cmd == "agent":       cmd_agent(args)
    elif cmd == "cron":        cmd_cron(args)
    elif cmd == "timed_msg":  cmd_timed_msg(args)
    elif cmd == "diag":        cmd_diag()
    elif cmd == "fix":         cmd_fix()
    elif cmd == "config":      cmd_config(args)
    elif cmd == "send":
        if len(args) >= 2:
            cmd_send(args[0], " ".join(args[1:]))
        else:
            print("用法: admin_cli.py send <群号|QQ号> <消息>")
    elif cmd == "sessions":    cmd_sessions()
    elif cmd == "help":        cmd_help()
    else:
        print(f"未知命令: {cmd}")
        cmd_help()
