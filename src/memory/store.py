"""小奈记忆系统 — 智能关联、自动摘要、情绪追踪。（v3）"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

from .affection_dimensions import DIMENSIONS, DEFAULT_DIMS, get_tier as _dim_get_tier, composite_score

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", "data"))
MEMORY_DIR = DATA_DIR / "memory"
USERS_DIR = MEMORY_DIR / "users"


class MemoryStore:
    def __init__(self):
        USERS_DIR.mkdir(parents=True, exist_ok=True)

    # ======== 好感度 ========

    def get_affection(self, user_id: int) -> dict:
        data = self._load_user(user_id)
        dims = data.get("dimensions", {})
        if "affection" in dims:
            score = int(round(dims["affection"]))
            data["affection"] = score
        else:
            score = data.get("affection", 50)
        tier = _dim_get_tier(score, "affection")
        return {
            "score": score,
            "tier": tier,
            "nickname": data.get("nickname", ""),
        }

    def adjust_affection(self, user_id: int, delta: int, reason: str = "") -> int:
        """仅用于维度 affection=affection 时同步旧标量。不应从外部直接调用。"""
        data = self._load_user(user_id)
        old = data.get("affection", 50)
        new = max(0, min(100, old + delta))
        data["affection"] = new
        data["last_seen"] = datetime.now().isoformat()
        data["msg_count"] = data.get("msg_count", 0) + 1
        if reason:
            data.setdefault("affection_log", []).append({
                "delta": delta, "reason": reason,
                "time": datetime.now().isoformat(),
            })
            if len(data["affection_log"]) > 20:
                data["affection_log"] = data["affection_log"][-20:]
        self._save_user(user_id, data)
        return new

    # ======== 事实记忆 ========

    def remember(self, user_id: int, fact: str, nickname: str = "") -> None:
        data = self._load_user(user_id)
        if nickname:
            data["nickname"] = nickname
        data.setdefault("facts", []).append({
            "content": fact,
            "time": datetime.now().isoformat(),
        })
        seen = set()
        unique = []
        for f in reversed(data["facts"]):
            if f["content"] not in seen:
                seen.add(f["content"])
                unique.append(f)
        data["facts"] = list(reversed(unique))[-50:]

        if len(data["facts"]) > 25:
            old = data["facts"][:-15]
            summary = "；".join(f["content"] for f in old[-10:])
            data["auto_summary"] = summary
            data["facts"] = data["facts"][-15:]

        data["msg_count"] = data.get("msg_count", 0) + 1
        self._save_user(user_id, data)

    def recall(self, user_id: int, keyword: str = "") -> list[str]:
        facts = [f["content"] for f in self._load_user(user_id).get("facts", [])]
        if not keyword:
            return facts[-10:]
        kw = keyword.lower()
        scored = []
        for f in facts:
            score = sum(1 for w in kw.split() if w in f.lower()) + (3 if kw in f.lower() else 0)
            if score > 0:
                scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:10]]

    # ======== 智能上下文 ========

    def get_user_context(self, user_id: int, current_msg: str = "") -> str:
        """生成给 LLM 的上下文：昵称 + 相关记忆 + 好感度 + 阶段 + 统计。"""
        data = self._load_user(user_id)
        parts = []

        if data.get("nickname"):
            parts.append(f"昵称：{data['nickname']}")

        if data.get("auto_summary"):
            parts.append(f"关于 ta 的概要：{data['auto_summary']}")

        relevant = self.recall(user_id, current_msg) if current_msg else []
        recent = [f["content"] for f in data.get("facts", [])[-5:]]
        facts = relevant or recent
        if facts:
            parts.append("相关记忆：" + "；".join(facts[:8]))

        aff = self.get_affection(user_id)
        parts.append(f"好感：{aff['score']}/100（{aff['tier']}）")

        stage = data.get("current_stage", "")
        stage_events = data.get("stage_events", [])
        if stage:
            stage_line = f"关系阶段：{stage}"
            if stage_events:
                last_se = stage_events[-1]
                stage_line += f"（上一次是「{last_se['from']}」，{last_se['time'][:10]} 升的）"
            parts.append(stage_line)

        msg_count = data.get("msg_count", 0)
        if msg_count > 0:
            first = data.get("first_seen", "")
            last = data.get("last_seen", "")
            parts.append(f"统计：聊过 {msg_count} 次" + (f"，最近 {last[:10]}" if last else ""))

        return "\n".join(parts)

    def get_affection_full(self, user_id: int) -> dict:
        data = self._load_user(user_id)
        dims = data.get("dimensions", {})
        if "affection" in dims:
            data["affection"] = int(round(dims["affection"]))
        return {
            "nickname": data.get("nickname", ""),
            "affection": data.get("affection", 50),
            "dimensions": dims,
            "dimension_history": data.get("dimension_history", []),
            "affection_events": data.get("affection_events", []),
            "affection_log": data.get("affection_log", []),
            "stage_events": data.get("stage_events", []),
            "milestones": data.get("milestones", []),
            "current_stage": data.get("current_stage", ""),
            "msg_count": data.get("msg_count", 0),
        }

    # ======== 情绪追踪 ========

    def track_mood(self, user_id: int, mood: str) -> None:
        data = self._load_user(user_id)
        data.setdefault("moods", []).append({
            "mood": mood,
            "time": datetime.now().isoformat(),
        })
        if len(data["moods"]) > 30:
            data["moods"] = data["moods"][-30:]
        data["last_mood"] = mood
        self._save_user(user_id, data)

    # ======== 内部 ========

    def _user_path(self, user_id: int) -> Path:
        return USERS_DIR / f"{user_id}.json"

    def _load_user(self, user_id: int) -> dict:
        path = self._user_path(user_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("affection", 50)
                data.setdefault("nickname", "")
                data.setdefault("dimensions", dict(DEFAULT_DIMS))
                data.setdefault("dimension_history", [])
                data.setdefault("affection_events", [])
                data.setdefault("stage_events", [])
                data.setdefault("milestones", [])
                data.setdefault("current_stage", "点头之交")
                dims = data.get("dimensions", {})
                if "affection" in dims:
                    data["affection"] = int(round(dims["affection"]))
                return data
            except json.JSONDecodeError:
                pass
        now = datetime.now().isoformat()
        return {
            "user_id": user_id, "nickname": "",
            "facts": [], "affection": 50,
            "affection_log": [], "msg_count": 0,
            "first_seen": now, "last_seen": now,
            "moods": [],
            "dimensions": dict(DEFAULT_DIMS),
            "dimension_history": [],
            "affection_events": [],
            "stage_events": [],
            "milestones": [],
            "current_stage": "点头之交",
        }

    def _save_user(self, user_id: int, data: dict) -> None:
        self._user_path(user_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


memory_store = MemoryStore()
