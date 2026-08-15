"""好感度多维系统 — 8 维定义 + 文字雷达图渲染。（v3）"""

DIMENSIONS = {
    "affection": {
        "key": "affection", "label": "好感度", "weight": 0.30,
        "tiers": {
            (0, 5): "完全陌生", (5, 15): "点头之交", (15, 25): "慢慢熟起来了",
            (25, 35): "还不错的朋友", (35, 45): "放在心上的朋友",
            (45, 55): "每天不聊两句就少了点什么", (55, 62): "越来越在意了",
            (62, 70): "很特别的存在", (70, 78): "藏在心底的人",
            (78, 85): "非常非常重要的人", (85, 92): "心里最柔软的角落",
            (92, 98): "几乎要把心掏出来了", (98, 101): "已经完全沦陷了，最喜欢的人",
        },
        "triggers_up": ["被夸", "被信任", "被想念", "被关心", "被记住喜好"],
        "triggers_down": ["被冷落", "被骂", "被敷衍", "被遗忘"],
    },
    "closeness": {
        "key": "closeness", "label": "亲近度", "weight": 0.17,
        "tiers": {
            (0, 20): "客气疏离", (20, 40): "偶尔出现", (40, 55): "日常陪伴",
            (55, 70): "习惯有ta", (70, 85): "无话不聊", (85, 101): "形影不离",
        },
        "triggers_up": ["高频互动", "私聊长约", "连续多天聊天"],
        "triggers_down": ["长时间沉默", "敷衍回复", "只回表情包"],
    },
    "trust": {
        "key": "trust", "label": "信任度", "weight": 0.17,
        "tiers": {
            (0, 20): "有所保留", (20, 40): "偶尔坦白", (40, 60): "愿意分享",
            (60, 75): "敞开心扉", (75, 90): "知无不言", (90, 101): "绝对托付",
        },
        "triggers_up": ["倾诉心事", "求建议", "分享秘密", "坦白弱点"],
        "triggers_down": ["言不由衷", "隐瞒回避", "转移话题"],
    },
    "tacit": {
        "key": "tacit", "label": "默契度", "weight": 0.08,
        "tiers": {
            (0, 25): "频道对接中", (25, 50): "偶尔能接上", (50, 65): "心有灵犀有时有",
            (65, 80): "一个眼神就懂", (80, 101): "灵魂共频",
        },
        "triggers_up": ["接话顺畅", "共同话题多", "会心一笑"],
        "triggers_down": ["说不到一起", "互相误解", "尬聊"],
    },
    "dependency": {
        "key": "dependency", "label": "依赖度", "weight": 0.08,
        "tiers": {
            (0, 20): "独立自主", (20, 40): "偶尔求助", (40, 60): "习惯找小奈",
            (60, 75): "大小事都想问", (75, 90): "离不开小奈了", (90, 101): "你就是ta的世界",
        },
        "triggers_up": ["主动私聊", "反复询问", "表白心意"],
        "triggers_down": ["只被动响应", "可有可无", "移情别恋"],
    },
    "understanding": {
        "key": "understanding", "label": "了解度", "weight": 0.08,
        "tiers": {
            (0, 20): "还不了解", (20, 40): "略知一二", (40, 60): "比较了解",
            (60, 75): "知根知底", (75, 90): "比ta自己还懂ta", (90, 101): "灵魂共频",
        },
        "triggers_up": ["记住新事实", "分享偏好", "透露个人信息"],
        "triggers_down": ["记忆矛盾", "忘记说过的事"],
    },
    "protectiveness": {
        "key": "protectiveness", "label": "守护欲", "weight": 0.08,
        "tiers": {
            (0, 20): "无所谓", (20, 40): "会担心", (40, 60): "放心不下",
            (60, 75): "想要保护", (75, 90): "谁都不能欺负ta", (90, 101): "拼尽全力守护",
        },
        "triggers_up": ["倾诉困难", "表现脆弱", "被攻击"],
        "triggers_down": ["推开帮助", "显示独立"],
    },
    "sharing": {
        "key": "sharing", "label": "分享欲", "weight": 0.04,
        "tiers": {
            (0, 20): "惜字如金", (20, 40): "简明扼要", (40, 60): "乐于分享",
            (60, 75): "滔滔不绝", (75, 90): "什么事都跟你讲", (90, 101): "你的小世界全给了小奈",
        },
        "triggers_up": ["发照片", "讲日常", "分享心情", "发语音"],
        "triggers_down": ["只问不聊", "机械问答", "不愿多说"],
    },
}

COMPOSITE_TIERS = {
    (0, 15): "点头之交", (15, 30): "还不错的朋友",
    (30, 45): "放在心上的朋友", (45, 55): "每天不聊两句就少了点什么",
    (55, 65): "越来越在意了", (65, 75): "很特别的存在",
    (75, 85): "藏在心底的人", (85, 92): "心里最柔软的角落",
    (92, 101): "已经完全沦陷了，最喜欢的人",
}

DEFAULT_DIMS = {k: 50 for k in DIMENSIONS}


def get_tier(score: int, dimension: str = "affection") -> str:
    dim = DIMENSIONS.get(dimension, DIMENSIONS["affection"])
    for (lo, hi), label in dim["tiers"].items():
        if lo <= score < hi:
            return label
    return "未知"


def get_composite_tier(score: float) -> str:
    s = int(round(score))
    for (lo, hi), label in COMPOSITE_TIERS.items():
        if lo <= s < hi:
            return label
    return "未知"


def composite_score(dims: dict) -> float:
    total = 0.0
    for key, d in DIMENSIONS.items():
        total += dims.get(key, 50) * d["weight"]
    return round(total, 1)


def render_radar(nickname: str, dims: dict, events: list | None = None,
                 milestones: list | None = None, prev_dims: dict | None = None) -> str:
    """8 维雷达图，含趋势箭头和里程碑。prev_dims 为上周数据用于计算趋势。"""
    comp = composite_score(dims)
    tier = get_composite_tier(comp)
    bar_width = 10
    lines = [f"╭──── {nickname or 'ta'} 的关系图谱 ────╮"]

    for key, d in DIMENSIONS.items():
        score = dims.get(key, 50)
        filled = int(round(score / 100 * bar_width))
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        label = d["label"]
        arrow = ""
        if prev_dims and key in prev_dims:
            prev = prev_dims[key]
            diff = score - prev
            if diff > 1.5:
                arrow = "↗ "
            elif diff < -1.5:
                arrow = "↘ "
            else:
                arrow = "→ "
        lines.append(f"│  {arrow}{label} {bar} {score}/100")

    lines.append(f"│{'':─^34}")
    lines.append(f"│  综合：{comp}  ·  {tier}")

    if milestones:
        lines.append(f"│{'':─^34}")
        lines.append("│  ⭐ 近期里程碑：")
        for m in milestones[-3:]:
            lines.append(f"│  {m['icon']} {m['text']}")

    if events:
        lines.append(f"│{'':─^34}")
        lines.append("│  📌 好感变化：")
        for e in events[-2:]:
            delta_str = f"+{e['delta']}" if e['delta'] >= 0 else str(e['delta'])
            lines.append(f"│  {delta_str} {e['reason']}")

    lines.append(f"╰{'':─^34}╯")
    return "\n".join(lines)


def trend_text(dim_history: list) -> str:
    if len(dim_history) < 2:
        return "数据还不够，再聊几天吧~"
    recent = [d.get("composite", 50) for d in dim_history[-7:]]
    if len(recent) < 2:
        return "趋势计算中..."
    delta = recent[-1] - recent[0]
    if delta > 3:
        return f"↑ 快速升温中 (近7天 +{delta:.1f})"
    elif delta > 1:
        return f"↗ 稳步上升 (近7天 +{delta:.1f})"
    elif delta > -1:
        return f"→ 平稳 (近7天 {delta:+.1f})"
    elif delta > -3:
        return f"↘ 微微降温 (近7天 {delta:.1f})"
    else:
        return f"↓ 快速降温中 (近7天 {delta:.1f})"
