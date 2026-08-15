#!/usr/bin/env python3
"""kb_search.py — thin wrapper delegating to kb_manage.py.
Preserves backward compatibility. Supports:
  kb_search.py <keyword>     -> kb_manage.py search <keyword>
  kb_search.py -s <query>    -> kb_manage.py semantic <query>
"""
import sys, os, subprocess

def main():
    script = os.path.join(os.path.dirname(__file__), "kb_manage.py")

    if len(sys.argv) < 2:
        print("Usage: python3 kb_search.py <keyword>")
        print("       python3 kb_search.py -s <query>   (semantic search)")
        sys.exit(1)

    if sys.argv[1] == "-s" and len(sys.argv) >= 3:
        cmd = "semantic"
        query = " ".join(sys.argv[2:])
    else:
        cmd = "search"
        query = " ".join(sys.argv[1:])

    result = subprocess.run(
        [sys.executable, script, cmd, query],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
