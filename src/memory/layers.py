"""Four-layer memory manager - L0/L1/L2/L3 read/write and transitions."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .db import db

# Noise detection patterns
_TEST_PATTERNS = [
    re.compile(p) for p in (
        r"^[\d\s]+$", r"^[a-z]{1,3}$", r"^[!@#$%^&*(),.?\":{}|<>]+$",
        r"^(test|123|asdf|qwer|abcd|hello|hi)$", r"(.)\1{4,}"
    )
]

L0_SESSIONS: dict = {}
MAX_L0 = 20


def is_noise(text: str) -> bool:
    """Detect test/meaningless messages."""
    t = text.strip().lower()
    # Don't reject short messages containing Chinese/CJK characters
    has_cjk = any('一' <= c <= '鿿' or '　' <= c <= '〿' for c in t)
    if has_cjk:
        return False
    if len(t) <= 2:
        return True
    return any(p.match(t) for p in _TEST_PATTERNS)


# ======== L0 transient ========

def l0_add(user_id: int, role: str, content: str) -> None:
    if is_noise(content):
        return
    L0_SESSIONS.setdefault(user_id, []).append({
        "role": role, "content": content,
        "time": datetime.now().isoformat()
    })
    if len(L0_SESSIONS[user_id]) > MAX_L0:
        L0_SESSIONS[user_id] = L0_SESSIONS[user_id][-MAX_L0:]


def l0_get(user_id: int) -> list:
    return L0_SESSIONS.get(user_id, [])


def l0_clear(user_id: int) -> None:
    L0_SESSIONS.pop(user_id, None)


# ======== L1 short-term ========

def l1_add(user_id: int, fact: str, category: str = "general", importance: int = 1) -> int:
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO short_term(user_id,fact,category,importance,created_at) VALUES(?,?,?,?,?)",
        (user_id, fact, category, importance, now)
    )
    db.commit()
    row = db.execute("SELECT last_insert_rowid()").fetchone()
    rec_id = row[0]
    db.execute("INSERT INTO st_fts(rowid, fact) VALUES(?,?)", (rec_id, fact))
    db.commit()
    return rec_id


def l1_search(user_id: int, query: str, limit: int = 5) -> list:
    like_q = "%" + query + "%"
    rows = db.execute(
        "SELECT * FROM short_term WHERE user_id=? AND fact LIKE ? "
        "ORDER BY recall_count DESC, created_at DESC LIMIT ?",
        (user_id, like_q, limit)
    ).fetchall()
    results = [dict(r) for r in rows]
    for r in results:
        _touch("short_term", r["id"])
    return results


def _touch(table: str, rec_id: int) -> None:
    now = datetime.now().isoformat()
    db.execute(
        f"UPDATE {table} SET last_recalled=?, recall_count=recall_count+1 WHERE id=?",
        (now, rec_id)
    )
    db.commit()


def l1_get_old(days: int = 7) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT * FROM short_term WHERE "
        "(last_recalled IS NULL OR last_recalled < ?) AND importance < 3",
        (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]


def l1_soft_delete(rec_id: int) -> None:
    db.execute("DELETE FROM short_term WHERE id=?", (rec_id,))
    db.execute("DELETE FROM st_fts WHERE rowid=?", (rec_id,))
    db.commit()


def l1_promote_to_l2(rec_id: int) -> None:
    row = db.execute("SELECT * FROM short_term WHERE id=?", (rec_id,)).fetchone()
    if not row:
        return
    r = dict(row)
    l2_add(r["user_id"], r["fact"], r["category"], max(r["importance"], 3), "conversation")
    l1_soft_delete(rec_id)


def l1_user_count(user_id: int) -> int:
    row = db.execute("SELECT COUNT(*) as cnt FROM short_term WHERE user_id=?", (user_id,)).fetchone()
    return row["cnt"] if row else 0


# ======== L2 long-term ========

def l2_add(user_id: int, fact: str, category: str = "general",
           importance: int = 3, source: str = "conversation") -> int:
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO long_term(user_id,fact,category,importance,source,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, fact, category, importance, source, now)
    )
    db.commit()
    row = db.execute("SELECT last_insert_rowid()").fetchone()
    rec_id = row[0]
    db.execute("INSERT INTO lt_fts(rowid, fact) VALUES(?,?)", (rec_id, fact))
    db.commit()
    return rec_id


def l2_search(user_id: int, query: str, limit: int = 5) -> list:
    like_q = "%" + query + "%"
    rows = db.execute(
        "SELECT * FROM long_term WHERE user_id=? AND fact LIKE ? "
        "ORDER BY recall_count DESC, created_at DESC LIMIT ?",
        (user_id, like_q, limit)
    ).fetchall()
    results = [dict(r) for r in rows]
    for r in results:
        _touch("long_term", r["id"])
    return results


def l2_find_duplicate(user_id: int, fact: str) -> Optional[dict]:
    like_q = "%" + fact[:20] + "%"
    rows = db.execute(
        "SELECT * FROM long_term WHERE user_id=? AND fact LIKE ? LIMIT 1",
        (user_id, like_q)
    ).fetchall()
    return dict(rows[0]) if rows else None


def l2_touch(rec_id: int) -> None:
    _touch("long_term", rec_id)



def search_all(user_id: int, query: str, limit: int = 5) -> list:
    """Search both L1 and L2, return merged results sorted by importance."""
    l1 = l1_search(user_id, query, limit)
    l2 = l2_search(user_id, query, limit)
    seen = set()
    merged = []
    for r in l2 + l1:
        fact = r.get("fact", "") if isinstance(r, dict) else r[1] if isinstance(r, tuple) else ""
        if fact and fact not in seen:
            seen.add(fact)
            merged.append(r)
    return merged[:limit]

# ======== L3 global knowledge base ========

def l3_add(topic: str, knowledge: str, confidence: float = 0.5, sources=None) -> int:
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO global_kb(topic,knowledge,confidence,sources,last_updated,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (topic, knowledge, confidence, json.dumps(sources or [], ensure_ascii=False), now, now)
    )
    db.commit()
    row = db.execute("SELECT last_insert_rowid()").fetchone()
    rec_id = row[0]
    db.execute("INSERT INTO gkb_fts(rowid, topic, knowledge) VALUES(?,?,?)", (rec_id, topic, knowledge))
    db.commit()
    return rec_id


def l3_search(query: str, limit: int = 5) -> list:
    like_q = "%" + query + "%"
    rows = db.execute(
        "SELECT * FROM global_kb WHERE topic LIKE ? OR knowledge LIKE ? "
        "ORDER BY confidence DESC LIMIT ?",
        (like_q, like_q, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def l3_update_confidence(rec_id: int, delta: float) -> None:
    row = db.execute("SELECT confidence FROM global_kb WHERE id=?", (rec_id,)).fetchone()
    if row:
        new = max(0.0, min(1.0, row["confidence"] + delta))
        db.execute(
            "UPDATE global_kb SET confidence=?, last_updated=? WHERE id=?",
            (new, datetime.now().isoformat(), rec_id)
        )
        db.commit()
