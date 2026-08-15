#!/usr/bin/env python3
"""Session cleaner v2 — safe cleanup with idle-age gating.

Key fix: only cleans sessions that have been IDLE (no file writes) for
IDLE_THRESHOLD seconds. This prevents the race condition where cron
deletes a session file while the OpenClaw agent is actively using it,
which caused EmbeddedAttemptSessionTakeoverError.
"""
import os, json, time, glob, logging, sys
from pathlib import Path

# session_cleaner.py (v1) — 被 session_cleaner_v2.py 取代
# cron 已在用 v2，此文件保留作参考
