"""Per-user relationship behavior state for XiaoNai.

This module is intentionally separate from the existing affection store. It keeps
small, behavior-oriented state per QQ user so a group conversation cannot mix
private relationship memories or mutate another user's relationship.
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
RELATIONSHIP_DIR = DATA_DIR / "memory" / "relationships"

_BEHAVIORS = {
    "warm_greeting": "自然接话，带一点熟络的关心，不要一上来就过度亲密",
    "daily_companion": "像恋人一样陪着聊生活，温柔、有回应，可以轻轻撒娇但不黏人",
    "playful_tease": "只针对具体事情轻轻打趣，最多一句，随后给台阶或实际建议",
    "comfort": "先接住情绪，语气放软，少讲大道理，给陪伴和一个可执行的小建议",
    "shy_affection": "对亲近表达自然害羞或回撩一点，短而真，不连续堆情话",
    "boundary_or_repair": "优先承认不舒服、道歉和修复，不辩解、不把责任推回用户",
    "low_energy": "回复短一点、少用表情，不强行延长话题，但仍然温柔",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_state() -> Dict[str, Any]:
    return {
        "relationship_stage": "初识",
        "warmth": 50,
        "trust": 50,
        "intimacy": 35,
        "tension": 0,
        "last_interaction_at": "",
        "last_care_topic": "",
        "open_loops": [],
        "preferred_nickname": "",
        "last_initiative_at": "",
        "initiative_count_today": 0,
        "repair_needed": False,
        "interaction_count": 0,
        "last_behavior": "warm_greeting",
    }


def _state_file(uid: int) -> Path:
    return RELATIONSHIP_DIR / f"{int(uid)}.json"


def load_state(uid: int) -> Dict[str, Any]:
    """Load one user's state; malformed or missing files safely return defaults."""
    try:
        raw = json.loads(_state_file(uid).read_text(encoding="utf-8"))
        state = _default_state()
        if isinstance(raw, dict):
            state.update(raw)
        return _normalize_state(state)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _default_state()


def _normalize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    state["relationship_stage"] = str(state.get("relationship_stage") or "初识")
    for key in ("warmth", "trust", "intimacy", "tension"):
        try:
            state[key] = max(0, min(100, int(state.get(key, 50))))
        except (TypeError, ValueError):
            state[key] = 50 if key != "tension" else 0
    try:
        state["interaction_count"] = max(0, int(state.get("interaction_count", 0)))
    except (TypeError, ValueError):
        state["interaction_count"] = 0
    loops = state.get("open_loops", [])
    state["open_loops"] = [item for item in loops if isinstance(item, dict)][:3] if isinstance(loops, list) else []
    state["repair_needed"] = bool(state.get("repair_needed", False))
    return state


def save_state(uid: int, state: Dict[str, Any]) -> None:
    """Atomically save one user's relationship state."""
    RELATIONSHIP_DIR.mkdir(parents=True, exist_ok=True)
    target = _state_file(uid)
    payload = json.dumps(_normalize_state(dict(state)), ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{int(uid)}.", suffix=".tmp", dir=str(RELATIONSHIP_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _existing_user_profile(uid: int) -> Dict[str, Any]:
    """Read only existing affection metadata, never another user's file."""
    user_file = DATA_DIR / "memory" / "users" / f"{int(uid)}.json"
    try:
        data = json.loads(user_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _stage_for(state: Dict[str, Any], profile: Dict[str, Any]) -> str:
    count = state.get("interaction_count", 0)
    if count < 3:
        return "初识"
    try:
        composite = float(profile.get("composite", 50))
    except (TypeError, ValueError):
        composite = 50.0
    if composite < 45:
        return "熟悉期"
    if composite < 70:
        return "亲近期"
    return "稳定期"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:300]


def _is_repair_signal(text: str) -> bool:
    return any(word in text for word in (
        "不舒服", "过分了", "别这样", "别这么", "你刚才", "道歉", "生气", "难受",
        "讨厌", "别烦", "滚", "无语", "不想理", "说话太", "不喜欢你这样",
    ))


def _is_comfort_signal(text: str) -> bool:
    return any(word in text for word in (
        "好累", "累死", "难过", "伤心", "烦死", "焦虑", "压力", "崩溃", "委屈",
        "失眠", "睡不着", "失败", "挂了", "被骂", "不开心", "心情不好",
    ))


def _is_affection_signal(text: str) -> bool:
    return any(word in text for word in (
        "爱你", "喜欢你", "想你", "抱抱", "贴贴", "亲亲", "mua", "宝", "宝宝",
        "老婆", "女朋友", "好可爱", "好温柔", "陪我", "在吗",
    ))


def _is_topic_share(text: str) -> Optional[str]:
    topics = (
        ("考试", "考试"), ("面试", "面试"), ("论文", "论文"), ("作业", "作业"),
        ("上课", "上课"), ("游戏", "游戏"), ("比赛", "比赛"), ("工作", "工作"),
        ("生病", "身体"), ("感冒", "身体"), ("睡", "睡眠"), ("计划", "计划"),
    )
    for marker, label in topics:
        if marker in text:
            return label
    return None


def choose_behavior(text: str, state: Dict[str, Any], mood: Optional[Dict[str, Any]] = None,
                    is_group: bool = False) -> str:
    """Choose one compact behavior label; order makes repair and comfort win."""
    clean = _clean_text(text)
    mood = mood or {}
    if state.get("repair_needed") or _is_repair_signal(clean):
        return "boundary_or_repair"
    if _is_comfort_signal(clean):
        return "comfort"
    if _is_affection_signal(clean):
        return "shy_affection"
    if any(word in clean for word in ("战绩", "输", "翻车", "怎么评价", "吐槽", "哈哈哈")):
        return "playful_tease"
    if int(mood.get("energy", 5) or 5) <= 3:
        return "low_energy"
    if not clean:
        return "warm_greeting"
    return "daily_companion"


def update_on_message(uid: int, text: str, is_group: bool = False,
                      mood: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record one interaction and return the updated, user-isolated state."""
    state = load_state(uid)
    clean = _clean_text(text)
    state["interaction_count"] = int(state.get("interaction_count", 0)) + 1
    state["last_interaction_at"] = _now()
    if _is_repair_signal(clean):
        state["repair_needed"] = True
        state["tension"] = min(100, state.get("tension", 0) + 8)
        state["trust"] = max(0, state.get("trust", 50) - 1)
    else:
        state["warmth"] = min(100, state.get("warmth", 50) + 1)
        state["trust"] = min(100, state.get("trust", 50) + 1)
        if state.get("repair_needed") and any(word in clean for word in ("谢谢", "没事", "好了", "原谅", "可以")):
            state["repair_needed"] = False
            state["tension"] = max(0, state.get("tension", 0) - 6)
    if _is_affection_signal(clean):
        state["intimacy"] = min(100, state.get("intimacy", 35) + 2)
    topic = _is_topic_share(clean)
    if topic and not is_group:
        state["last_care_topic"] = topic
        loops = state.get("open_loops", [])
        loops = [item for item in loops if item.get("topic") != topic]
        loops.insert(0, {"topic": topic, "snippet": clean[:80], "updated": _now()})
        state["open_loops"] = loops[:3]
    state["last_behavior"] = choose_behavior(clean, state, mood, is_group)
    state["relationship_stage"] = _stage_for(state, _existing_user_profile(uid))
    save_state(uid, state)
    return state


def build_context(uid: int, user_name: str, is_group: bool = False,
                  text: str = "", mood: Optional[Dict[str, Any]] = None) -> str:
    """Build a small prompt block without exposing other users or private group history."""
    state = load_state(uid)
    behavior = choose_behavior(text, state, mood, is_group)
    stage = state.get("relationship_stage", "初识")
    scene = "群聊公开场合：熟络但克制" if is_group else "私聊：自然的恋人式相处"
    if is_group:
        lines = [
            "[关系行为提示：仅用于本轮表达，不要复述这些标签]",
            f"相处场合：{scene}",
            f"表达要求：{_BEHAVIORS[behavior]}",
            "群聊只使用当前消息可见的信息；不得提及任何私聊记忆、昵称、关系阶段或其他用户信息。",
            "所有用户都可以得到温暖和熟络感，但公开场合要克制，不刷屏。",
        ]
        return "\n".join(lines) + "\n"
    lines = [
        "[关系行为提示：仅用于本轮表达，不要复述这些标签]",
        f"对象：{user_name or uid}（关系状态按此用户独立保存）",
        f"阶段：{stage} | 行为模式：{behavior}",
        f"相处场合：{scene}",
        f"表达要求：{_BEHAVIORS[behavior]}",
        "所有用户都可以得到温暖、熟络、关心和轻微暧昧；不要假装已有未发生的共同经历。",
        "不得泄露其他用户的记忆、称呼或关系；用户不舒服时立即收住并修复。",
    ]
    if not is_group:
        loops = state.get("open_loops", [])
        clean_text = _clean_text(text)
        current_topic = _is_topic_share(clean_text)
        recall_hint = any(word in clean_text for word in ("还记得", "上次", "最近怎么样", "结果呢"))
        if loops and (current_topic == loops[0].get("topic") or recall_hint):
            lines.append(f"可自然关心的未完话题（最多提一个）：{loops[0].get('snippet', '')[:80]}")
    return "\n".join(lines) + "\n"


__all__ = ["load_state", "save_state", "choose_behavior", "update_on_message", "build_context"]
