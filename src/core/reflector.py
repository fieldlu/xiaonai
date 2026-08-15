"""Autonomous learning engine - LLM-driven reflection and periodic review."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from openai import AsyncOpenAI

from config import bot_config
from src.memory.db import db
from src.memory.layers import (
    l1_add, l2_add, l3_add, l1_get_old, l1_soft_delete, l1_promote_to_l2,
    l2_find_duplicate, is_noise,
)
from src.memory.kb import merge_cross_user, get_weak_knowledge

logger = logging.getLogger(__name__)

ADMIN_QQ = ADMIN_QQ_PLACEHOLDER
_reflect_llm = None


def _get_llm():
    global _reflect_llm
    if _reflect_llm is None:
        _reflect_llm = AsyncOpenAI(
            api_key=bot_config.mimo_api_key,
            base_url=bot_config.mimo_base_url,
        )
    return _reflect_llm


async def _llm_reflect(prompt: str, user_text: str) -> Optional[str]:
    """Call DeepSeek for lightweight reflection. Returns text or None."""
    try:
        resp = await _get_llm().chat.completions.create(
            model="mimo-v2.5",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3, max_tokens=300, timeout=10.0,
        )
        content = resp.choices[0].message.content
        print("[reflect_mini] LLM returned: " + str(content)[:200] if content else "[reflect_mini] LLM returned: None/Empty")
        return content
    except Exception as e:
        import traceback; print("[reflect_mini] LLM call failed: " + type(e).__name__ + " " + str(e)[:200] + "\n" + traceback.format_exc()[:500])
        return None


async def reflect_mini(user_id: int, user_msg: str, reply: str) -> None:
    print("[reflect_mini] START uid=" + str(user_id))
    """After each message: extract <=3 facts -> L1; detect corrections/new topics."""
    try:
        if is_noise(user_msg):
            return

        text = "User: " + user_msg + "\nXiaoNai: " + reply
        result = await _llm_reflect(
            "Extract facts about the user from this conversation (max 3). "
            "One per line, format: category|fact content. "
            "Categories: identity/preference/status/event/knowledge/other. "
            "If this is a test or meaningless message, reply only: SKIP",
            text
        )
        print("[reflect_mini] LLM result: " + str(result)[:200])
        if not result or result.strip() == "SKIP":
            return

        for line in result.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|", 1)
            cat = parts[0].strip()
            fact = parts[1].strip()
            if not fact or is_noise(fact):
                print("[reflect_mini] filtered fact: " + str(fact)[:80])
                continue

            imp = 5 if user_id == ADMIN_QQ else _estimate_importance(fact, user_msg)

            print("[reflect_mini] storing: " + fact[:60])
            if user_id == ADMIN_QQ:
                dup = l2_find_duplicate(user_id, fact)
                if not dup:
                    l2_add(user_id, fact, cat, imp, "admin")
            else:
                l1_add(user_id, fact, cat, imp)
    except Exception as e:
        print("[reflect_mini] ERROR: " + str(e))
        logger.error("reflect mini failed: %s", e)


async def reflect_daily() -> int:
    """Daily 03:00: L1 promotion/cleanup, interest analysis, L3 aggregation."""
    count = 0
    try:
        # L1 promotion: recall_count >= 3 or importance >= 4
        rows = db.execute(
            "SELECT * FROM short_term WHERE recall_count>=3 OR importance>=4"
        ).fetchall()
        for r in rows:
            rd = dict(r)
            l1_promote_to_l2(rd["id"])
            count += 1

        # L1 cleanup: 7 days no recall + importance < 3
        old = l1_get_old(7)
        for r in old:
            l1_soft_delete(r["id"])
            count += 1

        # L3 cross-user aggregation
        n = merge_cross_user(min_users=2)
        count += n

        # Interest decay
        try:
            from src.core.profiler import decay_interests
            users = db.execute("SELECT user_id FROM user_profiles").fetchall()
            for u in users:
                decay_interests(u["user_id"])
        except Exception:
            pass
    except Exception as e:
        logger.error("reflect daily failed: %s", e)
    return count


async def reflect_weekly() -> str:
    """Weekly Sunday 23:00: full review. Returns summary."""
    try:
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        l1_row = db.execute(
            "SELECT COUNT(*) as cnt FROM short_term WHERE created_at>=?", (week_ago,)
        ).fetchone()
        l2_row = db.execute(
            "SELECT COUNT(*) as cnt FROM long_term WHERE created_at>=?", (week_ago,)
        ).fetchone()
        l3_row = db.execute("SELECT COUNT(*) as cnt FROM global_kb").fetchone()

        l1_c = l1_row["cnt"] if l1_row else 0
        l2_c = l2_row["cnt"] if l2_row else 0
        l3_c = l3_row["cnt"] if l3_row else 0
        summary = "[Weekly] L1 new: %d, L2 new: %d, L3 total: %d" % (l1_c, l2_c, l3_c)

        
        # Check for contradictory L3 knowledge
        try:
            from src.memory.kb import demote_contradicted
            low_conf = get_weak_knowledge(0.2)
            for item in low_conf:
                if item.get("evidence_count", 1) <= 1:
                    demote_contradicted(item["id"], "Single-source unverified knowledge flagged in weekly review")
        except Exception:
            pass
        weak = get_weak_knowledge(0.4)
        if weak:
            summary += ", weak knowledge: %d items" % len(weak)

        logger.info("reflect weekly: %s", summary)
        return summary
    except Exception as e:
        logger.error("reflect weekly failed: %s", e)
        return "Weekly report failed: %s" % str(e)


def _estimate_importance(fact: str, msg: str) -> int:
    """Quick local importance estimation."""
    imp = 1
    identity_kw = ["is", "studies", "major", "lives", "likes", "hates",
                   "是", "学", "专业", "住在", "喜欢", "讨厌"]
    if any(kw in fact for kw in identity_kw):
        imp = 3
    declare_kw = ["remember", "don't forget", "my name is", "I am",
                  "记住", "别忘了", "我叫", "我是"]
    if any(kw in msg.lower() for kw in declare_kw):
        imp = 5
    return min(5, imp)
