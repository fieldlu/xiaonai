"""好感度引擎 v3 — 8维分析 + 里程碑 + 群聊/私聊分离。（v3）"""

from datetime import datetime, timedelta
import logging

from .affection_dimensions import DIMENSIONS, DEFAULT_DIMS, composite_score, get_composite_tier
from .sentiment import sentiment_analyzer
from .store import memory_store

logger = logging.getLogger(__name__)

GROUP_DIMS = {"closeness", "tacit", "sharing"}

MILESTONE_THRESHOLDS = [60, 75, 90]
CONSECUTIVE_DAYS_MILESTONES = [3, 7, 30]
MEMORY_MILESTONES = [10, 25, 50]
COMPOSITE_JUMP = 5

STAGE_MAP = [
    (0, 15, "点头之交"), (15, 30, "还不错的朋友"),
    (30, 45, "放在心上的朋友"), (45, 55, "每天不聊两句就少了点什么"),
    (55, 65, "越来越在意了"), (65, 75, "很特别的存在"),
    (75, 85, "藏在心底的人"), (85, 92, "心里最柔软的角落"),
    (92, 101, "已经完全沦陷了，最喜欢的人"),
]


def _get_stage(composite: float) -> str:
    for lo, hi, label in STAGE_MAP:
        if lo <= composite < hi:
            return label
    return "未知"


class DecayScheduler:
    @staticmethod
    def apply_decay(dims: dict, last_seen: str) -> dict:
        if not last_seen:
            return dims
        try:
            last = datetime.fromisoformat(last_seen)
        except ValueError:
            return dims
        hours = (datetime.now() - last).total_seconds() / 3600
        changes = {}
        if hours > 168:
            days = int(hours / 24) - 6
            changes["closeness"] = max(-25, -days * 2)
            changes["trust"] = max(-20, -days)
            changes["dependency"] = max(-20, -days)
            changes["protectiveness"] = max(-15, -days)
        elif hours > 72:
            days = int(hours / 24) - 2
            changes["closeness"] = max(-12, -days * 2)
            changes["sharing"] = max(-8, -days)
            changes["understanding"] = max(-5, -days)
        elif hours > 24:
            changes["closeness"] = -2
            changes["sharing"] = -1
        for k, v in changes.items():
            dims[k] = max(0, min(100, dims[k] + v))
        return dims


class AffectionEngine:
    def __init__(self):
        self._pending: dict[int, dict] = {}
        self._msg_counters: dict[int, int] = {}
        self._last_msg_time: dict[int, datetime] = {}

    async def process_message(self, user_id: int, text: str,
                              is_group: bool = False) -> dict | None:
        """处理一条消息。is_group=True 时仅更新群聊允许的维度。"""
        analysis = await sentiment_analyzer.analyze(text)

        data = memory_store._load_user(user_id)
        dims = data.get("dimensions", dict(DEFAULT_DIMS))
        dims = DecayScheduler.apply_decay(dims, data.get("last_seen", ""))

        now = datetime.now()
        last_time = self._last_msg_time.get(user_id)
        rapid_fire = last_time and (now - last_time).total_seconds() < 300

        delta = self._calc_delta(dims, analysis, rapid_fire, is_group)
        for k, v in delta.items():
            dims[k] = max(0, min(100, dims[k] + v))

        pid = self._pending.setdefault(user_id, {})
        for k, v in delta.items():
            pid[k] = round(pid.get(k, 0) + v, 2)

        self._last_msg_time[user_id] = now
        self._msg_counters[user_id] = self._msg_counters.get(user_id, 0) + 1

        # Always update last_seen and save dims
        data["dimensions"] = dims
        data["affection"] = int(round(dims.get("affection", 50)))
        data["last_seen"] = now.isoformat()
        memory_store._save_user(user_id, data)

        if self._msg_counters[user_id] >= 5 or any(
            abs(v) >= 1.5 for v in pid.values()
        ):
            await self._flush(user_id, dims)

        return analysis

    async def flush_user(self, user_id: int) -> None:
        if user_id in self._pending:
            data = memory_store._load_user(user_id)
            dims = data.get("dimensions", dict(DEFAULT_DIMS))
            await self._flush(user_id, dims)

    async def _flush(self, user_id: int, dims: dict) -> None:
        data = memory_store._load_user(user_id)
        old_dims = data.get("dimensions", dict(DEFAULT_DIMS))
        data["dimensions"] = dims
        data["affection"] = int(round(dims.get("affection", 50)))

        # ---- 历史记录 ----
        history = data.get("dimension_history", [])
        today = datetime.now().strftime("%Y-%m-%d")
        comp = composite_score(dims)
        if history and history[-1].get("date") == today:
            history[-1] = {"date": today, "composite": comp, "dimensions": dict(dims)}
        else:
            history.append({"date": today, "composite": comp, "dimensions": dict(dims)})
        if len(history) > 90:
            history = history[-90:]
        data["dimension_history"] = history

        # ---- 阶段检测 ----
        old_comp = composite_score(old_dims)
        old_stage = _get_stage(old_comp)
        new_stage = _get_stage(comp)
        stage_events = data.get("stage_events", [])
        if old_stage != new_stage:
            stage_events.append({
                "from": old_stage, "to": new_stage,
                "from_score": round(old_comp, 1), "to_score": round(comp, 1),
                "time": datetime.now().isoformat(),
            })
            if len(stage_events) > 20:
                stage_events = stage_events[-20:]
            data["stage_events"] = stage_events
        data["current_stage"] = new_stage

        # ---- 里程碑检测 ----
        milestones = data.get("milestones", [])

        # 首次突破
        for k in DIMENSIONS:
            for th in MILESTONE_THRESHOLDS:
                old_val = old_dims.get(k, 50)
                new_val = dims.get(k, 50)
                if old_val < th <= new_val:
                    m_key = f"first_{k}_{th}"
                    if m_key not in {m.get("key", "") for m in milestones}:
                        milestones.append({
                            "key": m_key, "icon": "🔓",
                            "type": "首次突破",
                            "text": f"{DIMENSIONS[k]['label']} 首次突破 {th}",
                            "time": datetime.now().isoformat(),
                        })

        # 综合跳升
        daily_jump = comp - old_comp
        if daily_jump >= COMPOSITE_JUMP:
            milestones.append({
                "key": f"jump_{today}", "icon": "⚡",
                "type": "综合跳升",
                "text": f"综合分日变化 +{daily_jump:.1f}",
                "time": datetime.now().isoformat(),
            })

        # 连续聊天
        active_dates = set()
        for h in history:
            active_dates.add(h.get("date", ""))
        active_dates.add(today)
        today_date = datetime.now().date()
        streak = 0
        for i in range(90):
            d = today_date - timedelta(days=i)
            if d.strftime("%Y-%m-%d") in active_dates:
                streak = i + 1
            else:
                break
        for th in CONSECUTIVE_DAYS_MILESTONES:
            m_key = f"streak_{th}"
            if streak >= th and m_key not in {m.get("key", "") for m in milestones}:
                milestones.append({
                    "key": m_key, "icon": "🔥",
                    "type": "连续聊天",
                    "text": f"连续 {th} 天聊天",
                    "time": datetime.now().isoformat(),
                })

        # 记忆里程碑
        facts_count = len(data.get("facts", []))
        for th in MEMORY_MILESTONES:
            m_key = f"memory_{th}"
            if facts_count >= th and m_key not in {m.get("key", "") for m in milestones}:
                milestones.append({
                    "key": m_key, "icon": "🧠",
                    "type": "记忆里程碑",
                    "text": f"记住了 {th}+ 条关于ta的事",
                    "time": datetime.now().isoformat(),
                })

        if len(milestones) > 50:
            milestones = milestones[-50:]
        data["milestones"] = milestones

        # ---- 好感事件 ----
        events = data.get("affection_events", [])
        for k, v in dims.items():
            old_v = old_dims.get(k, 50)
            diff = round(v - old_v, 1)
            if abs(diff) >= 2:
                d_label = DIMENSIONS.get(k, {}).get("label", k)
                if diff > 0:
                    reasons = {
                        "affection": "ta让我的心跳了一下",
                        "closeness": "和ta的距离又近了一点",
                        "trust": "更信任ta了",
                        "tacit": "和ta的默契又多了一点",
                        "dependency": "ta好像越来越需要我了",
                        "understanding": "我好像又多懂了ta一点",
                        "protectiveness": "突然好想保护ta",
                        "sharing": "ta愿意跟我分享更多了",
                    }
                else:
                    reasons = {
                        "affection": "心里有点凉凉的",
                        "closeness": "和ta之间好像远了一点",
                        "trust": "信任少了那么一点点",
                        "tacit": "默契好像差了一点",
                        "dependency": "ta没那么需要我了",
                        "understanding": "ta好像变了，我不太懂了",
                        "protectiveness": "好像不太需要我保护了",
                        "sharing": "ta不太愿意分享了",
                    }
                events.append({
                    "dimension": k, "label": d_label, "delta": diff,
                    "from": old_v, "to": v,
                    "reason": reasons.get(k, f"{d_label}自然变化"),
                    "time": datetime.now().isoformat(),
                })
        if len(events) > 30:
            events = events[-30:]
        data["affection_events"] = events

        data["last_seen"] = datetime.now().isoformat()
        memory_store._save_user(user_id, data)

        self._pending.pop(user_id, None)
        self._msg_counters[user_id] = 0

    SENSITIVITY = 1.5  # 敏感度倍率，越大好感变化越快

    def _calc_delta(self, dims: dict, analysis: dict, rapid: bool = False,
                    is_group: bool = False) -> dict:
        """计算 8 维 delta。群聊模式仅更新 GROUP_DIMS。"""
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

        # ---- 核心好感度 ----
        if s > 0:
            delta["affection"] += s * 0.8
            delta["closeness"] += s * 0.5
        elif s < 0:
            delta["affection"] += s * 0.8
            delta["trust"] += s * 0.4

        # ---- mood 驱动 ----
        mood_map = {
            "tender": {"affection": 0.3, "protectiveness": 0.4},
            "sad": {"protectiveness": 0.5, "dependency": 0.3},
            "anxious": {"trust": 0.4, "dependency": 0.3},
            "playful": {"closeness": 0.4, "tacit": 0.3},
            "happy": {"affection": 0.2, "sharing": 0.3},
            "angry": {"trust": -0.3, "protectiveness": 0.3},
            "tired": {"dependency": 0.2, "tacit": 0.1},
        }
        if mood in mood_map:
            for dim_k, dim_v in mood_map[mood].items():
                delta[dim_k] += dim_v * (intensity / 3)

        # ---- 亲密度信号 ----
        if pos >= 2:
            delta["closeness"] += 0.6
            delta["affection"] += 0.4
        if pos >= 4:
            delta["closeness"] += 0.5
            delta["sharing"] += 0.4
        if neg >= 2:
            delta["closeness"] -= 0.5
            delta["trust"] -= 0.3

        # ---- 消息长度 → 了解度 ----
        if length == "长":
            delta["closeness"] += 0.8
            delta["sharing"] += 0.8
            delta["trust"] += 0.3
            delta["understanding"] += 0.5
        elif length == "中":
            delta["closeness"] += 0.4
            delta["sharing"] += 0.3
            delta["understanding"] += 0.2

        # ---- 提问 → 依赖+信任 ----
        if is_q:
            delta["dependency"] += 0.5
            delta["trust"] += 0.35

        # ---- 分享 → 分享欲+亲近+了解度 ----
        if is_s:
            delta["sharing"] += 0.8
            delta["closeness"] += 0.4
            delta["understanding"] += 0.3

        # ---- 颜文字 ----
        if kao:
            delta["closeness"] += 0.35
            delta["affection"] += 0.2
            delta["tacit"] += 0.2

        # Apply sensitivity multiplier
        for k in delta:
            delta[k] = round(delta[k] * self.SENSITIVITY, 2)

        # ---- 波浪线 ----
        if tilde >= 1:
            delta["closeness"] += 0.3
        if tilde >= 3:
            delta["affection"] += 0.25

        # ---- 高频互动 ----
        if rapid:
            delta["closeness"] += 0.5
            delta["dependency"] += 0.3

        # ---- 小奈 mood 加成 ----
        try:
            from .mood import load_mood
            xiaonai_mood = load_mood().get("mood", "普通日常")
            mood_bonus = {
                "心情低落": {"affection": 0.3, "protectiveness": 0.2},
                "想撒娇": {"tacit": 0.3, "closeness": 0.2},
                "元气满满": {"affection": 0.2, "sharing": 0.2},
            }
            if xiaonai_mood in mood_bonus:
                for dim_k, dim_v in mood_bonus[xiaonai_mood].items():
                    delta[dim_k] += dim_v
        except Exception:
            pass

        # ---- 群聊过滤 ----
        if is_group:
            delta = {k: v for k, v in delta.items() if k in GROUP_DIMS}

        # ---- 上限减速 ----
        for k in delta:
            current = dims.get(k, 50)
            if current > 95 and delta[k] > 0:
                delta[k] *= 0.1
            elif current > 85 and delta[k] > 0:
                delta[k] *= 0.5
            elif current < 15 and delta[k] < 0:
                delta[k] *= 0.5
            elif current < 5 and delta[k] < 0:
                delta[k] *= 0.1

            target = current + delta[k]
            if target > 100:
                delta[k] = 100 - current
            elif target < 0:
                delta[k] = -current

            delta[k] = round(delta[k], 2)

        return delta


affection_engine = AffectionEngine()
