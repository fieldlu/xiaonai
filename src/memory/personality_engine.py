#!/usr/bin/env python3
"""Personality Engine - Big Five (OCEAN) inference from chat patterns."""
import json, os, re
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")))
USERS_DIR = DATA_DIR / "memory" / "users"
USERS_DIR.mkdir(parents=True, exist_ok=True)

OCEAN = {
    "openness":          {"label": "Openness", "high": "curious innovative", "low": "practical traditional"},
    "conscientiousness": {"label": "Conscientiousness", "high": "disciplined organized", "low": "flexible spontaneous"},
    "extraversion":      {"label": "Extraversion", "high": "outgoing social", "low": "quiet reserved"},
    "agreeableness":     {"label": "Agreeableness", "high": "cooperative empathetic", "low": "direct competitive"},
    "neuroticism":       {"label": "Neuroticism", "high": "sensitive anxious", "low": "stable calm"},
}

DEFAULT_TRAITS = {k: 50 for k in OCEAN}

INFERENCE_RULES = [
    (r"why|explore|curious|new.*thing|try|creative|idea", "openness", 3),
    (r"always.*been|tradition|rule|habit|stable|no.*change", "openness", -3),
    (r"plan|schedule|goal|must|guarantee|careful|organize|list", "conscientiousness", 3),
    (r"whatever|casual|random|later|no.*rush|slowly", "conscientiousness", -3),
    (r"haha|lol|wow|!!|together|everyone|chat|party", "extraversion", 3),
    (r"alone|quiet|leave.*alone|dont.*talk|by.*myself|shy", "extraversion", -3),
    (r"thanks|please|help|sorry|love.*you|ok.*sure|trust", "agreeableness", 3),
    (r"no|wrong|stupid|nonsense|shut.*up|whatever|dont.*care", "agreeableness", -3),
    (r"worried|anxious|stress|scared|nervous|panic|cant.*sleep|help.*me", "neuroticism", 3),
    (r"fine|calm|chill|dont.*worry|relax|never.*mind|whatever", "neuroticism", -3),
    (r".{80,}", "extraversion", 1),
    (r"^.{0,5}$", "extraversion", -1),
    (r"[?!]{2,}", "neuroticism", 1),
    (r"~+", "agreeableness", 1),
]

def _user_file(uid):
    return USERS_DIR / (str(uid) + ".json")

def load_personality(uid):
    f = _user_file(uid)
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "traits" in data:
                return data
        except: pass
    return {"user_id": uid, "traits": dict(DEFAULT_TRAITS), "count": 0, "pattern": "unknown"}

def save_personality(uid, data):
    f = _user_file(uid)
    existing = {}
    if f.exists():
        try: existing = json.loads(f.read_text(encoding="utf-8"))
        except: pass
    existing["traits"] = data.get("traits", {})
    existing["count"] = data.get("count", 0)
    existing["pattern"] = data.get("pattern", "")
    f.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

def infer_personality(uid, text):
    if not text or len(text) < 3:
        return load_personality(uid)
    data = load_personality(uid)
    traits = data["traits"]
    count = data.get("count", 0) + 1
    for pattern, trait, delta in INFERENCE_RULES:
        if re.search(pattern, text):
            traits[trait] = max(10, min(90, traits.get(trait, 50) + delta))
    if count > 20 and count % 10 == 0:
        for k in traits:
            traits[k] = 50 + (traits[k] - 50) * 0.9
    data["count"] = count
    data["pattern"] = _classify_pattern(traits)
    save_personality(uid, data)
    return data

def _classify_pattern(traits):
    patterns = []
    e = traits.get("extraversion", 50)
    o = traits.get("openness", 50)
    c = traits.get("conscientiousness", 50)
    a = traits.get("agreeableness", 50)
    n = traits.get("neuroticism", 50)
    if e > 65: patterns.append("Extroverted-Social")
    elif e < 35: patterns.append("Quiet-Reserved")
    if o > 65: patterns.append("Curious-Explorer")
    elif o < 35: patterns.append("Steady-Traditional")
    if c > 65: patterns.append("Goal-Driven")
    elif c < 35: patterns.append("Spontaneous-Flexible")
    if a > 65: patterns.append("Warm-Cooperative")
    if n > 65: patterns.append("Emotionally-Sensitive")
    elif n < 35: patterns.append("Calm-Stable")
    return " + ".join(patterns[:3]) if patterns else "Not yet identified"

def personality_context(uid, user_name=""):
    data = load_personality(uid)
    traits = data.get("traits", DEFAULT_TRAITS)
    pattern = data.get("pattern", "unknown")
    count = data.get("count", 0)
    if count < 5:
        return ""
    st = sorted(traits.items(), key=lambda x: x[1])
    low = [(k, v) for k, v in st[:2] if v < 30]
    high = [(k, v) for k, v in st[-2:] if v > 70]
    lines = ["[Personality] " + user_name]
    lines.append("Pattern: " + pattern + " (based on " + str(count) + " msgs)")
    if high:
        items = [OCEAN[k]["label"] + " high(" + str(int(v)) + ")" for k, v in high]
        lines.append("Strengths: " + ", ".join(items))
    if low:
        items = [OCEAN[k]["label"] + " low(" + str(int(v)) + ")" for k, v in low]
        lines.append("Growth areas: " + ", ".join(items))
    return '\n'.join(lines) + '\n\n'

def on_message(uid, text, user_name=""):
    data = infer_personality(uid, text)
    return personality_context(uid, user_name)
