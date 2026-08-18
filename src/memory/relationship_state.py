"""Per-user relationship behavior state for XiaoNai.

The state is intentionally small and user-scoped.  It supports warm, continuous
conversation while keeping proactive contact opt-in, low-frequency, and private.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
RELATIONSHIP_DIR = DATA_DIR / "memory" / "relationships"

_DEFAULT_QUIET_HOURS = {"start": "23:00", "end": "08:00"}
_INITIATIVE_COOLDOWN = timedelta(hours=20)
_RECENT_MESSAGE_COOLDOWN = timedelta(minutes=30)
_MAX_EVENTS = 20
_MAX_DISLIKED_PHRASES = 20
_MAX_LOOPS = 3

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


def _today() -> str:
    return datetime.now().date().isoformat()


def _default_state() -> Dict[str, Any]:
    return {
        "relationship_stage": "初识",
        "warmth": 50,
        "trust": 50,
        "intimacy": 35,
        "tension": 0,
        "last_interaction_at": "",
        "last_user_message_at": "",
        "last_care_topic": "",
        "open_loops": [],
        "preferred_nickname": "",
        "nickname_source": "",
        "disliked_phrases": [],
        "relationship_events": [],
        "initiative_enabled": False,
        "quiet_hours": dict(_DEFAULT_QUIET_HOURS),
        "daily_initiative_limit": 1,
        "initiative_count_today": 0,
        "initiative_count_date": "",
        "last_initiative_at": "",
        "repair_needed": False,
        "interaction_count": 0,
        "last_behavior": "warm_greeting",
    }


def _state_file(uid: int) -> Path:
    return RELATIONSHIP_DIR / f"{int(uid)}.json"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:300]


def _parse_clock(value: Any, fallback: int) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or ""))
    if not match:
        return fallback
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return fallback
    return hour * 60 + minute


def _normalize_quiet_hours(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return dict(_DEFAULT_QUIET_HOURS)
    start = _parse_clock(value.get("start"), 23 * 60)
    end = _parse_clock(value.get("end"), 8 * 60)
    return {"start": f"{start // 60:02d}:{start % 60:02d}", "end": f"{end // 60:02d}:{end % 60:02d}"}


def _normalize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    state["relationship_stage"] = str(state.get("relationship_stage") or "初识")
    for key in ("warmth", "trust", "intimacy", "tension"):
        try:
            state[key] = max(0, min(100, int(state.get(key, 50))))
        except (TypeError, ValueError):
            state[key] = 50 if key != "tension" else 0
    for key in ("last_interaction_at", "last_user_message_at", "last_care_topic",
                "preferred_nickname", "nickname_source", "last_initiative_at",
                "initiative_count_date", "last_behavior"):
        state[key] = str(state.get(key) or "")
    try:
        state["interaction_count"] = max(0, int(state.get("interaction_count", 0)))
    except (TypeError, ValueError):
        state["interaction_count"] = 0
    try:
        state["daily_initiative_limit"] = max(0, min(10, int(state.get("daily_initiative_limit", 1))))
    except (TypeError, ValueError):
        state["daily_initiative_limit"] = 1
    try:
        state["initiative_count_today"] = max(0, int(state.get("initiative_count_today", 0)))
    except (TypeError, ValueError):
        state["initiative_count_today"] = 0
    state["initiative_enabled"] = bool(state.get("initiative_enabled", False))
    state["repair_needed"] = bool(state.get("repair_needed", False))
    state["quiet_hours"] = _normalize_quiet_hours(state.get("quiet_hours"))

    loops = state.get("open_loops", [])
    normalized_loops = []
    if isinstance(loops, list):
        for item in loops:
            if not isinstance(item, dict):
                continue
            topic = _clean_text(item.get("topic", ""))[:30]
            snippet = _clean_text(item.get("snippet", ""))[:80]
            if topic and snippet:
                normalized_loops.append({
                    "topic": topic,
                    "snippet": snippet,
                    "updated": str(item.get("updated") or ""),
                })
    state["open_loops"] = normalized_loops[:_MAX_LOOPS]

    phrases = state.get("disliked_phrases", [])
    state["disliked_phrases"] = []
    if isinstance(phrases, list):
        for phrase in phrases:
            phrase = _clean_text(phrase)[:60]
            if phrase and phrase not in state["disliked_phrases"]:
                state["disliked_phrases"].append(phrase)
            if len(state["disliked_phrases"]) >= _MAX_DISLIKED_PHRASES:
                break

    events = state.get("relationship_events", [])
    state["relationship_events"] = []
    if isinstance(events, list):
        for event in events[-_MAX_EVENTS:]:
            if not isinstance(event, dict):
                continue
            kind = _clean_text(event.get("type", ""))[:40]
            summary = _clean_text(event.get("summary", ""))[:80]
            if kind and summary:
                state["relationship_events"].append({
                    "type": kind,
                    "summary": summary,
                    "at": str(event.get("at") or ""),
                    "source": "group" if event.get("source") == "group" else "private",
                })
    return state


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
    if state.get("interaction_count", 0) < 3:
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


def _record_event(state: Dict[str, Any], kind: str, summary: str, source: str = "private") -> None:
    event = {"type": kind, "summary": _clean_text(summary)[:80], "at": _now(), "source": source}
    state["relationship_events"] = [*state.get("relationship_events", []), event][-_MAX_EVENTS:]


def _extract_argument(text: str, prefix: str, max_len: int) -> str:
    value = _clean_text(text)[len(prefix):].strip(" ：:，,。.!！")
    return value[:max_len].strip()


def apply_relationship_command(uid: int, text: str, is_group: bool = False) -> Optional[str]:
    """Handle explicit private relationship controls without involving the LLM."""
    clean = _clean_text(text).strip()
    controls = {
        "开启陪伴提醒", "关闭陪伴提醒", "陪伴状态",
    }
    is_nickname = clean.startswith("叫我 ") and len(clean) > 3
    is_clear_nickname = clean.startswith("别这样叫我 ") and len(clean) > 6
    is_disliked = clean.startswith("我不喜欢你说 ") and len(clean) > 7
    if clean not in controls and not (is_nickname or is_clear_nickname or is_disliked):
        return None
    if is_group:
        return "这个设置要私聊我改哦，我不在群里动你的私人陪伴设置。"

    state = load_state(uid)
    if clean == "开启陪伴提醒":
        state["initiative_enabled"] = True
        save_state(uid, state)
        return "好呀，我会保持低频陪伴，不打扰你；想关的时候跟我说一声就好。"
    if clean == "关闭陪伴提醒":
        state["initiative_enabled"] = False
        save_state(uid, state)
        return "好，我先不主动打扰你了。你来找我的时候我一直在。"
    if clean == "陪伴状态":
        state = _normalize_state(state)
        remaining = max(0, state["daily_initiative_limit"] - _effective_initiative_count(state))
        enabled = "已开启" if state["initiative_enabled"] else "未开启"
        quiet = state["quiet_hours"]
        return f"陪伴提醒：{enabled}\n安静时段：{quiet['start']}-{quiet['end']}\n今天还可以主动 {remaining} 条（默认每天最多 1 条）。"
    if is_nickname:
        nickname = _extract_argument(clean, "叫我 ", 20)
        if not nickname:
            return "你想让我怎么叫你呀？"
        state["preferred_nickname"] = nickname
        state["nickname_source"] = "explicit_private"
        _record_event(state, "nickname_preference", "用户明确指定了称呼", "private")
        save_state(uid, state)
        return f"好，我记住了，以后叫你{nickname}。"
    if is_clear_nickname:
        nickname = _extract_argument(clean, "别这样叫我 ", 20)
        if not nickname or nickname == state.get("preferred_nickname", ""):
            state["preferred_nickname"] = ""
            state["nickname_source"] = ""
        _record_event(state, "boundary_feedback", "用户明确拒绝了一个称呼", "private")
        save_state(uid, state)
        return "好，不这样叫你了，我会注意。"
    phrase = _extract_argument(clean, "我不喜欢你说 ", 60)
    if phrase:
        if phrase not in state["disliked_phrases"]:
            state["disliked_phrases"].append(phrase)
            state["disliked_phrases"] = state["disliked_phrases"][-_MAX_DISLIKED_PHRASES:]
        _record_event(state, "boundary_feedback", "用户明确标记了一种不喜欢的说法", "private")
        state["repair_needed"] = True
        save_state(uid, state)
        return "好，我记住了，不再用这个说法惹你不舒服。"
    return None


def choose_behavior(text: str, state: Dict[str, Any], mood: Optional[Dict[str, Any]] = None,
                    is_group: bool = False) -> str:
    """Choose one compact behavior label; repair and comfort always win."""
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
    try:
        if int(mood.get("energy", 5) or 5) <= 3:
            return "low_energy"
    except (TypeError, ValueError):
        pass
    if not clean:
        return "warm_greeting"
    return "daily_companion"


def update_on_message(uid: int, text: str, is_group: bool = False,
                      mood: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record one interaction and return the updated, user-isolated state."""
    state = load_state(uid)
    clean = _clean_text(text)
    now = _now()
    state["interaction_count"] += 1
    state["last_interaction_at"] = now
    state["last_user_message_at"] = now
    source = "group" if is_group else "private"
    was_repair = bool(state.get("repair_needed"))
    if _is_repair_signal(clean):
        state["repair_needed"] = True
        state["tension"] = min(100, state.get("tension", 0) + 8)
        state["trust"] = max(0, state.get("trust", 50) - 1)
        _record_event(state, "boundary_feedback", "用户表达了不舒服或希望收住", source)
    else:
        state["warmth"] = min(100, state.get("warmth", 50) + 1)
        state["trust"] = min(100, state.get("trust", 50) + 1)
        if was_repair and any(word in clean for word in ("谢谢", "没事", "好了", "原谅", "可以")):
            state["repair_needed"] = False
            state["tension"] = max(0, state.get("tension", 0) - 6)
            _record_event(state, "repair_accepted", "用户接受了修复", source)
    if _is_comfort_signal(clean):
        _record_event(state, "asked_for_comfort", "用户表现出疲惫、低落或需要安慰", source)
    if _is_affection_signal(clean):
        state["intimacy"] = min(100, state.get("intimacy", 35) + 2)
        _record_event(state, "affection_signal", "用户表达了亲近或需要陪伴", source)
    topic = _is_topic_share(clean)
    if topic and not is_group:
        state["last_care_topic"] = topic
        loops = [item for item in state.get("open_loops", []) if item.get("topic") != topic]
        loops.insert(0, {"topic": topic, "snippet": clean[:80], "updated": now})
        state["open_loops"] = loops[:_MAX_LOOPS]
        _record_event(state, "shared_topic", f"用户提到{topic}", "private")
    state["last_behavior"] = choose_behavior(clean, state, mood, is_group)
    state["relationship_stage"] = _stage_for(state, _existing_user_profile(uid))
    return_state = _normalize_state(state)
    save_state(uid, return_state)
    return return_state


def _effective_initiative_count(state: Dict[str, Any], now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    if state.get("initiative_count_date") != now.date().isoformat():
        return 0
    return int(state.get("initiative_count_today", 0))


def _in_quiet_hours(now: datetime, quiet_hours: Dict[str, str]) -> bool:
    current = now.hour * 60 + now.minute
    start = _parse_clock(quiet_hours.get("start"), 23 * 60)
    end = _parse_clock(quiet_hours.get("end"), 8 * 60)
    if start == end:
        return True
    return current >= start or current < end if start > end else start <= current < end


def can_initiate(uid: int, now: Optional[datetime] = None) -> bool:
    """Return whether one proactive private message is allowed right now."""
    now = now or datetime.now()
    state = _normalize_state(load_state(uid))
    if not state["initiative_enabled"]:
        return False
    if _in_quiet_hours(now, state["quiet_hours"]):
        return False
    if _effective_initiative_count(state, now) >= state["daily_initiative_limit"]:
        return False
    if state.get("repair_needed"):
        return False
    for field in ("last_initiative_at", "last_user_message_at"):
        value = state.get(field)
        if value:
            try:
                at = datetime.fromisoformat(value)
            except ValueError:
                continue
            cooldown = _INITIATIVE_COOLDOWN if field == "last_initiative_at" else _RECENT_MESSAGE_COOLDOWN
            if now - at < cooldown:
                return False
    return True


def mark_initiative_sent(uid: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now()
    state = load_state(uid)
    today = now.date().isoformat()
    if state.get("initiative_count_date") != today:
        state["initiative_count_date"] = today
        state["initiative_count_today"] = 0
    state["initiative_count_today"] += 1
    state["last_initiative_at"] = now.isoformat(timespec="seconds")
    save_state(uid, state)
    return state


def time_guidance(now: Optional[datetime] = None) -> str:
    hour = (now or datetime.now()).hour
    if 5 <= hour < 11:
        return "现在是早晨：问候简短自然，不默认要求对方回复。"
    if 11 <= hour < 18:
        return "现在是白天：优先回应眼前的事，像平常聊天一样自然接话。"
    if 18 <= hour < 23:
        return "现在是晚上：可以更放松亲近，但别连续堆情话。"
    return "现在是深夜：回复短一点、少用表情，温柔提醒休息，不强行追问。"


def build_context(uid: int, user_name: str, is_group: bool = False,
                  text: str = "", mood: Optional[Dict[str, Any]] = None) -> str:
    """Build a prompt block without exposing private state in group chats."""
    state = load_state(uid)
    behavior = choose_behavior(text, state, mood, is_group)
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
        f"相处场合：{scene}",
        f"表达要求：{_BEHAVIORS[behavior]}",
        time_guidance(),
        "所有用户都可以得到温柔、熟络、关心和轻微暧昧；不要假装已有未发生的共同经历。",
        "不得泄露其他用户的记忆、称呼或关系；用户不舒服时立即收住并修复。",
    ]
    if state.get("preferred_nickname"):
        lines.append(f"用户明确喜欢的称呼（仅作自然参考）：{state['preferred_nickname']}")
    if state.get("disliked_phrases"):
        lines.append("用户明确不喜欢的说法，回复中避开：" + "、".join(state["disliked_phrases"][:5]))
    loops = state.get("open_loops", [])
    clean_text = _clean_text(text)
    current_topic = _is_topic_share(clean_text)
    recall_hint = any(word in clean_text for word in ("还记得", "上次", "最近怎么样", "结果呢"))
    if loops and (current_topic == loops[0].get("topic") or recall_hint):
        lines.append(f"可自然关心的未完话题（最多提一个）：{loops[0].get('snippet', '')[:80]}")
    if state.get("repair_needed"):
        lines.append("用户之前表达过不舒服：本轮优先真诚修复，少解释，不打趣、不撒娇施压。")
    return "\n".join(lines) + "\n"


__all__ = [
    "load_state", "save_state", "choose_behavior", "update_on_message", "build_context",
    "apply_relationship_command", "can_initiate", "mark_initiative_sent", "time_guidance",
]
