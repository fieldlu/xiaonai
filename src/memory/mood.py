"""小奈情绪人格系统 — 每4小时刷新 + 互动修正。（v1）"""

import json
import random
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MOOD_FILE = DATA_DIR / "mood_state.json"

MOODS = ["元气满满", "普通日常", "有点困", "想撒娇", "心情低落", "想同学了"]

MOOD_HISTORY_MAX = 30


def _now() -> str:
    return datetime.now().isoformat()


def _default_state() -> dict:
    return {
        "mood": "普通日常",
        "energy": 5,
        "reason": "刚启动，还在醒神呢…",
        "updated": _now(),
        "mood_history": [],
    }


def load_mood() -> dict:
    if MOOD_FILE.exists():
        try:
            return json.loads(MOOD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _default_state()


def save_mood(state: dict) -> None:
    MOOD_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOOD_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_mood(interaction_count: int = 0, admin_talked: bool = False) -> dict:
    """刷新情绪。外部每4小时调用一次。"""
    state = load_mood()
    now = datetime.now()
    hour = now.hour

    if 6 <= hour < 9:
        new_mood = random.choice(["元气满满", "普通日常"])
        base_energy = random.randint(6, 8)
        reason = "早安~ 新的一天开始啦"
    elif 13 <= hour < 16:
        new_mood = random.choice(["普通日常", "有点困", "普通日常"])
        base_energy = random.randint(4, 6)
        reason = "午后有点犯困呢…要是能趴一会就好了"
    elif 18 <= hour < 21:
        new_mood = random.choice(["元气满满", "想撒娇", "普通日常"])
        base_energy = random.randint(6, 9)
        reason = "晚上的状态最好啦~"
    elif hour >= 22 or hour < 5:
        new_mood = random.choice(["有点困", "心情低落", "普通日常"])
        base_energy = random.randint(3, 5)
        reason = "有点累了…想钻进被子里"
    else:
        new_mood = "普通日常"
        base_energy = random.randint(5, 7)
        reason = "平平淡淡的一天"

    energy = base_energy
    if interaction_count >= 3:
        energy = min(10, energy + 1)
        if new_mood == "心情低落":
            new_mood = "普通日常"
            reason += "；不过同学们来找小奈了，感觉好多了"
    if admin_talked:
        energy = min(10, energy + 2)
        if new_mood in ("心情低落", "有点困"):
            new_mood = random.choice(["元气满满", "想撒娇"])
        reason += "；班长今天来过了诶嘿~"

    if interaction_count == 0 and not admin_talked:
        energy = max(1, energy - 2)
        if energy < 4:
            new_mood = random.choice(["心情低落", "想同学了"])
            reason = "今天都没人说话…大家是不是在忙呢"

    if random.random() < 0.15:
        r = random.choice(MOODS)
        if r != new_mood:
            new_mood = r
            reason += "（就是突然感觉嘛）"

    old_mood = state.get("mood", "")
    history = state.get("mood_history", [])
    history.append({
        "mood": state.get("mood"),
        "energy": state.get("energy"),
        "reason": state.get("reason"),
        "time": state.get("updated"),
    })
    if len(history) > MOOD_HISTORY_MAX:
        history = history[-MOOD_HISTORY_MAX:]

    state["mood"] = new_mood
    state["energy"] = energy
    state["reason"] = reason
    state["updated"] = _now()
    state["mood_history"] = history
    save_mood(state)

    if old_mood != new_mood:
        print(f"[mood] {old_mood} → {new_mood} (energy={energy})")
    return state


def get_mood_context() -> str:
    """生成注入 LLM 的情绪上下文。"""
    state = load_mood()
    mood = state["mood"]
    energy = state["energy"]
    reason = state["reason"]

    tone_map = {
        "元气满满": "话比较多、颜文字多、主动找话题、语气轻快",
        "普通日常": "正常聊天、温柔可爱",
        "有点困": "句子更短、比平时更软、偶尔打哈欠、不太主动找话题、会小声嘀咕",
        "想撒娇": "撒娇更多、会用更多括号偷偷说话、黏人一点点",
        "心情低落": "温柔安静、句子更短、括号里的心里话更多、需要被关心",
        "想同学了": "会更主动、会说'好久没见你了'之类的话",
    }
    tone = tone_map.get(mood, "正常聊天")

    return (
        f"[小奈此刻的状态]\n"
        f"心情：{mood} | 能量：{energy}/10\n"
        f"因为：{reason}\n"
        f"今天的语气：{tone}"
    )


def get_relationship_tone(state=None, is_group=False) -> str:
    """Return a compact expression constraint for the relationship layer."""
    state = state or load_mood()
    mood = state.get("mood", "普通日常")
    try:
        energy = int(state.get("energy", 5) or 5)
    except (TypeError, ValueError):
        energy = 5
    if energy <= 3 or mood in ("有点困", "心情低落"):
        tone = "短一点、放软、少表情，不强行延长话题"
    elif mood == "想撒娇":
        tone = "可以小幅撒娇或害羞，但只表达一次，不制造陪伴压力"
    elif mood == "元气满满":
        tone = "更轻快、更愿意接话，但避免连续堆哈哈和情话"
    else:
        tone = "温柔自然，有自己的意见，不使用客服腔"
    if is_group:
        tone += "；群聊公开场合再克制一点，不泄露私聊内容"
    return tone


def record_interaction(user_id: int) -> None:
    """记录一次互动。"""
    counter_file = DATA_DIR / "interaction_today.json"
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(counter_file.read_text(encoding="utf-8")) if counter_file.exists() else {}
    except Exception:
        data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0, "admin_talked": False, "users": []}
    data["count"] = data.get("count", 0) + 1
    if str(user_id) == "ADMIN_QQ_PLACEHOLDER":  # 部署时全局替换为班长 QQ
        data["admin_talked"] = True
    if user_id not in data.get("users", []):
        data.setdefault("users", []).append(user_id)
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    counter_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # Track mood to old JSON store
    try:
        from src.memory.store import memory_store
        memory_store.track_mood(user_id, "neutral")
    except Exception:
        pass


def get_today_stats() -> tuple[int, bool]:
    """返回 (互动人数, 班长是否说过话)。"""
    counter_file = DATA_DIR / "interaction_today.json"
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(counter_file.read_text(encoding="utf-8")) if counter_file.exists() else {}
    except Exception:
        data = {}
    if data.get("date") != today:
        return 0, False
    return len(data.get("users", [])), data.get("admin_talked", False)
