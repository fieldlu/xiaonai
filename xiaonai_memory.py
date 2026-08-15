#!/usr/bin/env python3
"""
XiaoNai Memory & Affection Engine v2 — standalone module.
  - Importable: bridge.py calls process_message() directly (sync, keyword-only)
  - CLI: OpenClaw calls for query/manage operations
Usage:
  python3 xiaonai_memory.py recall <user_id> [keyword]
  python3 xiaonai_memory.py remember <user_id> <fact>
  python3 xiaonai_memory.py affection <user_id>
  python3 xiaonai_memory.py radar <user_id>
  python3 xiaonai_memory.py stage <user_id>
  python3 xiaonai_memory.py set_affection <user_id> <score> [dimension]
  python3 xiaonai_memory.py check_user <user_id>
  python3 xiaonai_memory.py list_users
  python3 xiaonai_memory.py process <user_id> <text> [group]
"""
import sys, os, json, re, time
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", os.path.join(os.path.dirname(__file__), "data")))
MEMORY_DIR = DATA_DIR / "memory"
USERS_DIR = MEMORY_DIR / "users"
FACTS_FILE = MEMORY_DIR / "facts.json"
USERS_DIR.mkdir(parents=True, exist_ok=True)

# ── Sentiment Analysis (keyword-based, fast, no LLM) ──

NEUTRAL_PATTERNS = re.compile(r"^(嗯|好|哦|行|可以|是的|对|OK|ok|知道了|收到|明白|晚安|早安|再见)\s*$")
POSITIVE_WARM = ["谢谢","爱你","喜欢","想你","好厉害","开心","太好","真棒","感动","温暖","好温柔","好可爱","爱了","心动了","暖","治愈"]
POSITIVE_PLAYFUL = ["哈哈哈","hhh","www","草","笑死","太好笑了","好有趣","诶嘿","嘻嘻","噗","棒棒"]
POSITIVE_INTIMATE = ["抱抱","贴贴","mua","亲亲","想你了","陪我","晚安咯","早安呀","在吗","在不在","理我一下"]
NEGATIVE_HURT = ["讨厌","别烦我","滚","走开","够了","不好","生气","拉黑","取关","不想理你"]
NEGATIVE_COLD = ["不好","烦","无语","算了","呵呵","随便","不想说","别问了","累","没意思","没空"]
QUESTION_PATTERNS = re.compile(r"[？?]|怎么|什么|帮帮|求|请教|帮我|如何|你觉得|为什么")
SHARE_PATTERNS = re.compile(r"\[image|\[video|http|pic|照片|图片|看这个|今天|昨天|刚才|我[去在到吃买看发]")
KAOMOJI_PATTERNS = re.compile(r"[(（][^)）]{1,10}[)）]")
TILDE_PATTERN = re.compile(r"~{1,}")

def analyze_sentiment(text: str) -> dict:
    if not text or len(text) < 2:
        return {"sentiment":0.0,"mood":"neutral","nuance":"","intensity":1,"length":"空",
                "is_question":False,"is_share":False,"word_count":0,"pos_score":0,
                "neg_score":0,"has_kaomoji":False,"tilde_count":0}
    wc = len(text)
    length = "短" if wc < 6 else ("中" if wc < 25 else "长")
    if NEUTRAL_PATTERNS.match(text.strip()):
        return {"sentiment":0.0,"mood":"neutral","nuance":"","intensity":1,"length":length,
                "is_question":False,"is_share":False,"word_count":wc,"pos_score":0,
                "neg_score":0,"has_kaomoji":False,"tilde_count":0}
    pos = sum(1 for kw in POSITIVE_WARM if kw in text)
    pos += sum(0.7 for kw in POSITIVE_PLAYFUL if kw in text)
    pos += sum(1.2 for kw in POSITIVE_INTIMATE if kw in text)
    neg = sum(1.5 for kw in NEGATIVE_HURT if kw in text)
    neg += sum(0.8 for kw in NEGATIVE_COLD if kw in text)
    net = pos - neg
    sentiment = max(-1.0, min(1.0, net * 0.4))
    mood = "neutral"
    if pos >= 3: mood = "happy"
    elif pos >= 1: mood = "tender"
    if neg >= 2: mood = "angry" if neg >= 3 else "sad"
    return {"sentiment":round(sentiment,2),"mood":mood,"nuance":"","intensity":max(1,min(5,int(abs(net)))),
            "length":length,"is_question":bool(QUESTION_PATTERNS.search(text)),
            "is_share":bool(SHARE_PATTERNS.search(text)),"word_count":wc,"pos_score":pos,
            "neg_score":neg,"has_kaomoji":bool(KAOMOJI_PATTERNS.search(text)),
            "tilde_count":len(TILDE_PATTERN.findall(text))}

# ── Affection Dimensions ──

DIMENSIONS = {
    "affection": {"label":"好感度","weight":0.30},
    "closeness": {"label":"亲近度","weight":0.17},
    "trust": {"label":"信任度","weight":0.17},
    "tacit": {"label":"默契度","weight":0.08},
    "dependency": {"label":"依赖度","weight":0.08},
    "understanding": {"label":"了解度","weight":0.08},
    "protectiveness": {"label":"守护欲","weight":0.08},
    "sharing": {"label":"分享欲","weight":0.04},
}
DEFAULT_DIMS = {k: 50 for k in DIMENSIONS}
GROUP_DIMS = {"closeness", "tacit", "sharing"}
SENSITIVITY = 1.5

STAGES = [
    (0,15,"点头之交"),(15,30,"还不错的朋友"),(30,45,"放在心上的朋友"),
    (45,55,"每天不聊两句就少了点什么"),(55,65,"越来越在意了"),
    (65,75,"很特别的存在"),(75,85,"藏在心底的人"),
    (85,92,"心里最柔软的角落"),(92,101,"已经完全沦陷了，最喜欢的人"),
]

def composite_score(dims: dict) -> float:
    return round(sum(dims.get(k,50)*DIMENSIONS[k]["weight"] for k in DIMENSIONS), 1)

def get_stage(comp: float) -> str:
    for lo, hi, label in STAGES:
        if lo <= comp < hi: return label
    return "未知"

# ── User Data Store ──

def _user_file(uid: int) -> Path:
    return USERS_DIR / f"{uid}.json"

def _load_user(uid: int) -> dict:
    f = _user_file(uid)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except: pass
    return {"user_id": uid, "nickname": "", "dimensions": dict(DEFAULT_DIMS),
            "affection": 50, "facts": [], "created": datetime.now().isoformat()}

def _save_user(uid: int, data: dict):
    _user_file(uid).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Affection Engine (sync, keyword-only) ──

def apply_decay(dims: dict, last_seen: str) -> dict:
    if not last_seen: return dims
    try:
        last = datetime.fromisoformat(last_seen)
    except ValueError:
        return dims
    hours = (datetime.now() - last).total_seconds() / 3600
    changes = {}
    if hours > 168:
        days = int(hours/24) - 6
        changes["closeness"] = max(-25, -days*2)
        changes["trust"] = max(-20, -days)
        changes["dependency"] = max(-20, -days)
        changes["protectiveness"] = max(-15, -days)
    elif hours > 72:
        days = int(hours/24) - 2
        changes["closeness"] = max(-12, -days*2)
        changes["sharing"] = max(-8, -days)
        changes["understanding"] = max(-5, -days)
    elif hours > 24:
        changes["closeness"] = -2
        changes["sharing"] = -1
    for k, v in changes.items():
        dims[k] = max(0, min(100, dims.get(k, 50) + v))
    return dims

def calc_delta(dims: dict, analysis: dict, is_group: bool = False) -> dict:
    delta = {k: 0.0 for k in DIMENSIONS}
    s = analysis.get("sentiment", 0)
    mood = analysis.get("mood", "neutral")
    length = analysis.get("length", "中")
    is_q = analysis.get("is_question", False)
    is_s = analysis.get("is_share", False)
    pos = analysis.get("pos_score", 0)
    neg = analysis.get("neg_score", 0)
    kao = analysis.get("has_kaomoji", False)
    tilde = analysis.get("tilde_count", 0)
    intensity = analysis.get("intensity", 1)

    if s > 0:
        delta["affection"] += s * 0.8
        delta["closeness"] += s * 0.5
    elif s < 0:
        delta["affection"] += s * 0.8
        delta["trust"] += s * 0.4

    mood_map = {"tender":{"affection":0.3,"protectiveness":0.4},"sad":{"protectiveness":0.5,"dependency":0.3},
                "anxious":{"trust":0.4,"dependency":0.3},"playful":{"closeness":0.4,"tacit":0.3},
                "happy":{"affection":0.2,"sharing":0.3},"angry":{"trust":-0.3,"protectiveness":0.3},
                "tired":{"dependency":0.2,"tacit":0.1}}
    if mood in mood_map:
        for dk, dv in mood_map[mood].items():
            delta[dk] += dv * (intensity/3)

    if pos >= 2: delta["closeness"] += 0.6; delta["affection"] += 0.4
    if pos >= 4: delta["closeness"] += 0.5; delta["sharing"] += 0.4
    if neg >= 2: delta["closeness"] -= 0.5; delta["trust"] -= 0.3

    if length == "长": delta["closeness"] += 0.8; delta["sharing"] += 0.8; delta["trust"] += 0.3; delta["understanding"] += 0.5
    elif length == "中": delta["closeness"] += 0.4; delta["sharing"] += 0.3; delta["understanding"] += 0.2

    if is_q: delta["dependency"] += 0.5; delta["trust"] += 0.35
    if is_s: delta["sharing"] += 0.8; delta["closeness"] += 0.4; delta["understanding"] += 0.3
    if kao: delta["closeness"] += 0.35; delta["affection"] += 0.2; delta["tacit"] += 0.2
    if tilde >= 1: delta["closeness"] += 0.3
    if tilde >= 3: delta["affection"] += 0.25

    for k in delta: delta[k] = round(delta[k] * SENSITIVITY, 2)

    if is_group:
        delta = {k: v for k, v in delta.items() if k in GROUP_DIMS}

    for k in delta:
        cur = dims.get(k, 50)
        if cur > 95 and delta[k] > 0: delta[k] *= 0.1
        elif cur > 85 and delta[k] > 0: delta[k] *= 0.5
        elif cur < 15 and delta[k] < 0: delta[k] *= 0.5
        elif cur < 5 and delta[k] < 0: delta[k] *= 0.1
        target = cur + delta[k]
        if target > 100: delta[k] = 100 - cur
        elif target < 0: delta[k] = -cur
        delta[k] = round(delta[k], 2)
    return delta

def process_message(uid: int, text: str, is_group: bool = False) -> dict:
    """Process a message through affection engine. Sync, fast, no LLM."""
    data = _load_user(uid)
    dims = data.get("dimensions", dict(DEFAULT_DIMS))
    # Normalize: ensure all 8 dimensions exist (old data may have only 6)
    for k in DIMENSIONS:
        if k not in dims:
            dims[k] = 50
    dims = apply_decay(dims, data.get("last_seen", ""))
    analysis = analyze_sentiment(text)
    delta = calc_delta(dims, analysis, is_group)
    for k, v in delta.items():
        dims[k] = max(0, min(100, dims.get(k, 50) + v))
    data["dimensions"] = dims
    data["affection"] = int(round(dims.get("affection", 50)))
    data["last_seen"] = datetime.now().isoformat()
    if "msg_count" not in data: data["msg_count"] = 0
    data["msg_count"] += 1

    # Milestone tracking (simplified)
    comp = composite_score(dims)
    history = data.get("dimension_history", [])
    today = datetime.now().strftime("%Y-%m-%d")
    if history and history[-1].get("date") == today:
        history[-1] = {"date": today, "composite": comp, "dimensions": dict(dims)}
    else:
        history.append({"date": today, "composite": comp, "dimensions": dict(dims)})
    if len(history) > 90: history = history[-90:]
    data["dimension_history"] = history
    data["current_stage"] = get_stage(comp)
    data["composite"] = comp

    _save_user(uid, data)
    return {"delta": delta, "composite": comp, "stage": data["current_stage"],
            "affection": data["affection"], "analysis": analysis}

# ── Memory Operations ──

def remember(uid: int, fact: str, nickname: str = "") -> dict:
    data = _load_user(uid)
    if nickname: data["nickname"] = nickname
    data.setdefault("facts", []).append({"content": fact, "time": datetime.now().isoformat()})
    seen = set()
    unique = []
    for f in reversed(data["facts"]):
        c = f["content"]
        if c not in seen: seen.add(c); unique.append(f)
    data["facts"] = list(reversed(unique))[-200:]
    _save_user(uid, data)
    return {"ok": True, "fact": fact, "total_facts": len(data["facts"])}

def recall(uid: int, keyword: str = "") -> dict:
    data = _load_user(uid)
    facts = [f["content"] for f in data.get("facts", [])]
    if not keyword:
        recent = facts[-10:]
        return {"user_id": uid, "nickname": data.get("nickname",""), "facts": recent,
                "total": len(facts), "affection": data.get("affection", 50)}
    kw = keyword.lower()
    scored = [(sum(1 for w in kw.split() if w in f.lower()) + (3 if kw in f.lower() else 0), f) for f in facts]
    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [f for s, f in scored if s > 0][:10]
    return {"user_id": uid, "nickname": data.get("nickname",""), "keyword": keyword,
            "facts": matches, "total": len(facts), "affection": data.get("affection", 50)}

def get_affection(uid: int) -> dict:
    data = _load_user(uid)
    dims = data.get("dimensions", dict(DEFAULT_DIMS))
    comp = composite_score(dims)
    stage = get_stage(comp)
    return {"user_id": uid, "nickname": data.get("nickname",""), "affection": data.get("affection",50),
            "composite": comp, "stage": stage, "dimensions": dims,
            "msg_count": data.get("msg_count",0), "fact_count": len(data.get("facts",[])),
            "last_seen": data.get("last_seen","")}

def set_affection(uid: int, score: int, dimension: str = "affection") -> dict:
    data = _load_user(uid)
    dims = data.get("dimensions", dict(DEFAULT_DIMS))
    old = dims.get(dimension, 50)
    dims[dimension] = max(0, min(100, int(score)))
    data["dimensions"] = dims
    if dimension == "affection":
        data["affection"] = int(score)
    data["updated"] = datetime.now().isoformat()
    _save_user(uid, data)
    comp = composite_score(dims)
    return {"ok": True, "dimension": dimension, "old": old, "new": int(score),
            "composite": comp, "stage": get_stage(comp)}

# ── Radar / Display ──

def render_radar(uid: int) -> str:
    data = _load_user(uid)
    dims = data.get("dimensions", dict(DEFAULT_DIMS))
    comp = composite_score(dims)
    stage = get_stage(comp)
    nick = data.get("nickname", str(uid))
    bar_w = 10
    lines = [f"╭──── {nick} 的关系图谱 ────╮"]
    for key, d in DIMENSIONS.items():
        score = dims.get(key, 50)
        filled = int(round(score/100*bar_w))
        bar = "█" * filled + "░" * (bar_w - filled)
        lines.append(f"│  {d['label']} {bar} {score}/100")
    lines.append(f"│{'':─^30}")
    lines.append(f"│  综合：{comp}  ·  {stage}")
    # Show recent stage events
    events = data.get("stage_events", [])
    if events:
        last_ev = events[-1]
        lines.append(f"│  ↗ {last_ev['from']} → {last_ev['to']}")
    lines.append(f"╰{'':─^30}╯")
    return "\n".join(lines)

def get_users() -> list:
    users = []
    for f in sorted(USERS_DIR.glob("*.json")):
        try:
            uid = int(f.stem)
            data = json.loads(f.read_text(encoding="utf-8"))
            users.append({"user_id": uid, "nickname": data.get("nickname",""),
                          "affection": data.get("affection",50),
                          "msg_count": data.get("msg_count",0),
                          "last_seen": data.get("last_seen","")[:10]})
        except: pass
    users.sort(key=lambda u: u["affection"], reverse=True)
    return users

# ── CLI ──

def _cli():
    if len(sys.argv) < 2:
        print("xiaonai_memory.py <command> [args...]")
        print("Commands: recall|remember|affection|radar|stage|set_affection|check_user|list_users|process")
        sys.exit(1)
    cmd = sys.argv[1]
    try:
        if cmd == "recall":
            uid = int(sys.argv[2])
            kw = sys.argv[3] if len(sys.argv) > 3 else ""
            r = recall(uid, kw)
            for f in r["facts"]:
                print(f"  - {f}")
            if not r["facts"]:
                print(f"(暂无关于 {r['nickname'] or uid} 的记忆)")
        elif cmd == "remember":
            uid = int(sys.argv[2])
            fact = " ".join(sys.argv[3:])
            r = remember(uid, fact)
            print(f"[memory] 记住了！共 {r['total_facts']} 条关于此用户的记忆")
        elif cmd == "affection":
            uid = int(sys.argv[2])
            r = get_affection(uid)
            print(f"用户 {r['nickname'] or uid}：好感度 {r['affection']} | 综合 {r['composite']} | {r['stage']}")
            print(f"消息数 {r['msg_count']} | 记忆数 {r['fact_count']} | 最后活跃 {r['last_seen'][:10]}")
            for k, d in DIMENSIONS.items():
                print(f"  {d['label']}: {r['dimensions'].get(k, 50)}")
        elif cmd == "radar":
            uid = int(sys.argv[2])
            print(render_radar(uid))
        elif cmd == "stage":
            uid = int(sys.argv[2])
            r = get_affection(uid)
            print(f"{r['nickname'] or uid}：{r['stage']} (好感度 {r['affection']}, 综合 {r['composite']})")
        elif cmd == "set_affection":
            uid = int(sys.argv[2])
            score = int(sys.argv[3])
            dim = sys.argv[4] if len(sys.argv) > 4 else "affection"
            r = set_affection(uid, score, dim)
            print(f"[affection] {dim}: {r['old']} → {r['new']} | 综合 {r['composite']} | {r['stage']}")
        elif cmd == "check_user":
            uid = int(sys.argv[2])
            data = _load_user(uid)
            dims = data.get("dimensions", dict(DEFAULT_DIMS))
            comp = composite_score(dims)
            print(f"用户ID: {uid}")
            print(f"昵称: {data.get('nickname', '(未知)')}")
            print(f"好感度: {data.get('affection', 50)} | 综合: {comp} | {get_stage(comp)}")
            print(f"消息数: {data.get('msg_count', 0)} | 记忆数: {len(data.get('facts', []))}")
            print(f"创建: {data.get('created', '?')[:10]} | 最后活跃: {data.get('last_seen', '?')[:19]}")
            facts = data.get("facts", [])[-5:]
            if facts:
                print("最近记忆:")
                for f in facts:
                    print(f"  [{f['time'][:19]}] {f['content']}")
        elif cmd == "list_users":
            users = get_users()
            print(f"共 {len(users)} 位用户：")
            for u in users:
                print(f"  {u['user_id']:>12} | 好感{u['affection']:>3} | 消息{u['msg_count']:>5} | {u['nickname'] or '(匿名)':<15} | {u['last_seen']}")
        elif cmd == "process":
            uid = int(sys.argv[2])
            text = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
            is_group = "--group" in sys.argv
            text = text.replace("--group", "").strip()
            r = process_message(uid, text, is_group)
            print(f"[affection] {uid}: 好感度 {r['affection']} | 综合 {r['composite']} | {r['stage']}")
            if r["delta"]:
                changes = {k: v for k, v in r["delta"].items() if abs(v) > 0.1}
                if changes:
                    for k, v in sorted(changes.items(), key=lambda x: abs(x[1]), reverse=True):
                        sign = "+" if v > 0 else ""
                        print(f"  {DIMENSIONS[k]['label']}: {sign}{v}")
        else:
            print(f"未知命令: {cmd}")
    except (IndexError, ValueError) as e:
        print(f"参数错误: {e}")
        print("Usage: xiaonai_memory.py <recall|remember|affection|radar|stage|set_affection|check_user|list_users|process> ...")
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    _cli()
