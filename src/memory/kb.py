"""L3 global knowledge base operations - aggregation, demotion, dedup."""

import json
from datetime import datetime

from .db import db
from .layers import l3_add as _l3_add, l3_search


def merge_cross_user(min_users: int = 2) -> int:
    """Scan L1+L2 cross-user common facts, promote to L3. Returns count."""
    rows = db.execute("""
        SELECT fact, COUNT(DISTINCT user_id) as uc, GROUP_CONCAT(DISTINCT category) as cats
        FROM (
            SELECT user_id, fact, category FROM short_term WHERE importance >= 3
            UNION ALL
            SELECT user_id, fact, category FROM long_term WHERE importance >= 3
        )
        GROUP BY fact HAVING uc >= ?
    """, (min_users,)).fetchall()
    count = 0
    for r in rows:
        fact = r["fact"]
        cats = set(r["cats"].split(",")) if r["cats"] else {"general"}
        topic = cats.pop() if len(cats) == 1 else "general"
        existing = l3_search(fact[:30], 1)
        if not existing:
            _l3_add(topic, fact, 0.6, [{"source": "cross_user_" + str(r["uc"])}])
            count += 1
    return count


def demote_contradicted(knowledge_id: int, reason: str) -> None:
    row = db.execute("SELECT * FROM global_kb WHERE id=?", (knowledge_id,)).fetchone()
    if not row:
        return
    r = dict(row)
    contradictions = json.loads(r.get("contradictions", "[]") or "[]")
    contradictions.append({"reason": reason, "time": datetime.now().isoformat()})
    new_conf = r["confidence"] * 0.5
    db.execute(
        "UPDATE global_kb SET confidence=?, contradictions=?, last_updated=? WHERE id=?",
        (new_conf, json.dumps(contradictions, ensure_ascii=False),
         datetime.now().isoformat(), knowledge_id)
    )
    db.commit()


def get_weak_knowledge(threshold: float = 0.3) -> list:
    rows = db.execute(
        "SELECT * FROM global_kb WHERE confidence < ? ORDER BY confidence ASC",
        (threshold,)
    ).fetchall()
    return [dict(r) for r in rows]
