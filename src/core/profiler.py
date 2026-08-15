"""User profiler - LLM-driven interest extraction, heuristic level/style detection."""

import json
from datetime import datetime, timedelta
from typing import Optional

from src.memory.db import db

ADMIN_QQ = ADMIN_QQ_PLACEHOLDER

LEVEL_HINTS = {
    "beginner": "Use everyday language, avoid jargon.",
    "intermediate": "",
    "advanced": "Can use technical terms normally.",
}
STYLE_HINTS = {
    "casual_short": "",
    "formal": "Be appropriate, use fewer kaomoji.",
    "technical": "Be concise and direct, logic first.",
}


def get_or_create_profile(user_id: int) -> dict:
    row = db.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return dict(row)
    now = datetime.now().isoformat()
    db.execute("INSERT INTO user_profiles(user_id, last_profiled) VALUES(?,?)", (user_id, now))
    db.commit()
    return {"user_id": user_id, "nickname": "", "knowledge_level": "intermediate",
            "comm_style": "casual_short", "interest_tags": "[]",
            "kb_gaps": "[]", "last_profiled": now, "total_messages": 0}


def update_profile(user_id: int, **kwargs) -> None:
    get_or_create_profile(user_id)
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    db.execute(f"UPDATE user_profiles SET {sets} WHERE user_id=?", vals)
    db.commit()


def increment_messages(user_id: int) -> None:
    get_or_create_profile(user_id)
    db.execute(
        "UPDATE user_profiles SET total_messages=total_messages+1, last_profiled=? WHERE user_id=?",
        (datetime.now().isoformat(), user_id)
    )
    db.commit()


def add_interest(user_id: int, tag: str) -> None:
    p = get_or_create_profile(user_id)
    tags = json.loads(p["interest_tags"])
    found = next((t for t in tags if t["tag"] == tag), None)
    if found:
        found["weight"] = min(10, found["weight"] + 3)
        found["last"] = datetime.now().isoformat()
    else:
        tags.append({"tag": tag, "weight": 3, "first": datetime.now().isoformat(),
                     "last": datetime.now().isoformat()})
    tags.sort(key=lambda t: t["weight"], reverse=True)
    update_profile(user_id, interest_tags=json.dumps(tags[:20], ensure_ascii=False))


def decay_interests(user_id: int) -> None:
    p = get_or_create_profile(user_id)
    tags = json.loads(p["interest_tags"])
    now = datetime.now()
    kept = []
    for t in tags:
        try:
            last = datetime.fromisoformat(t["last"])
        except (ValueError, KeyError):
            last = now
        days = (now - last).days
        if days <= 30:
            if days >= 7:
                t["weight"] = max(0, t["weight"] - 2)
            kept.append(t)
    update_profile(user_id, interest_tags=json.dumps(kept, ensure_ascii=False))


def get_top_interests(user_id: int, top_n: int = 5) -> list:
    p = get_or_create_profile(user_id)
    tags = json.loads(p["interest_tags"])
    return [t["tag"] for t in tags[:top_n]]


def detect_level(message: str) -> str:
    """Heuristic knowledge level detection."""
    msg = message.lower()
    advanced_kw = ["算法", "架构", "底层", "源码", "编译", "并发", "分布式",
                   "transformer", "attention", "gradient", "backpropagation",
                   "优化器", "损失函数", "超参数", "微调", "预训练"]
    beginner_kw = ["什么是", "怎么学", "入门", "新手", "基础", "不会", "帮我解释",
                   "好难", "太难", "学不会", "看不懂", "不理解", "教教我", "零基础"]
    if any(kw in msg for kw in advanced_kw):
        return "advanced"
    if any(kw in msg for kw in beginner_kw):
        return "beginner"
    return "intermediate"


def detect_style(message: str) -> Optional[str]:
    """Heuristic communication style detection."""
    msg = message.lower()
    if any(kw in msg for kw in ["代码", "bug", "error", "函数", "class", "api"]):
        return "technical"
    if len(message) > 200 and not any(kw in msg for kw in ["哈哈", "~", "呀", "呢"]):
        return "formal"
    return None


def update_profile_intelligent(user_id: int, message: str) -> None:
    """Local keyword-driven profile update. Ultra-wide coverage."""
    p = get_or_create_profile(user_id)
    total = p["total_messages"]

    if total > 0 and total % 5 == 0:
        level = detect_level(message)
        update_profile(user_id, knowledge_level=level)

    style = detect_style(message)
    if style:
        update_profile(user_id, comm_style=style)

    # Ultra-wide interest detection
    interest_map = {
        # --- 学术/大学课程 ---
        "高等数学": ["高等数学", "高数", "微积分", "线性代数", "概率论", "数理统计"],
        "大学物理": ["大学物理", "大物", "力学", "电磁学", "光学", "热学"],
        "英语学习": ["英语", "四级", "六级", "雅思", "托福", "单词", "听力", "口语", "阅读", "写作", "语法"],
        "编程开发": ["编程", "代码", "Python", "Java", "C++", "JavaScript", "Go", "Rust", "前端", "后端", "全栈", "算法", "数据结构", "debug", "API", "框架", "Git", "Docker"],
        "机械设计": ["机械", "制图", "CAD", "SolidWorks", "设计基础", "工程材料", "制造工艺", "公差", "装配"],
        "汽车工程": ["汽车", "发动机", "底盘", "新能源", "电动汽车", "智能驾驶", "车辆工程", "YOUR_MAJOR_ABBR", "动力电池", "混合动力", "变速箱", "悬挂"],
        "电气电子": ["电路", "模电", "数电", "电工", "电子", "单片机", "嵌入式", "PCB", "传感器", "PLC"],
        "材料科学": ["材料", "金属", "合金", "复合材料", "陶瓷", "高分子", "纳米"],
        "计算机科学": ["计算机", "操作系统", "网络", "数据库", "SQL", "编译原理", "计算机组成"],
        "人工智能": ["AI", "ML", "深度学习", "神经网络", "机器学习", "NLP", "CV", "transformer", "模型训练", "pytorch", "tensorflow"],
        "考研考公": ["考研", "考公", "公务员", "复习", "政治", "专业课", "数学一", "数学二", "数学三", "英语一", "英语二", "国考", "省考", "行测", "申论"],
        "竞赛比赛": ["竞赛", "大赛", "数模", "数学建模", "挑战杯", "互联网+", "ACM", "蓝桥杯", "英语竞赛"],
        "论文科研": ["论文", "科研", "实验", "数据", "文献", "综述", "开题", "答辩", "SCI", "核心期刊", "知网"],
        # --- 生活/娱乐 ---
        "游戏电竞": ["游戏", "Steam", "LOL", "王者荣耀", "原神", "吃鸡", "CS", "DOTA", "Switch", "PS5", "手游", "端游", "电竞"],
        "体育运动": ["篮球", "足球", "跑步", "健身", "游泳", "羽毛球", "乒乓球", "网球", "运动", "健身房", "马拉松", "瑜伽"],
        "音乐爱好": ["音乐", "唱歌", "吉他", "钢琴", "乐队", "KTV", "演唱会", "livehouse", "rap", "hiphop", "古典乐", "流行歌"],
        "影视动漫": ["电影", "电视剧", "动漫", "番剧", "B站", "Netflix", "追剧", "综艺", "纪录片", "二次元"],
        "美食吃货": ["美食", "火锅", "烧烤", "奶茶", "咖啡", "甜品", "小吃", "探店", "做饭", "烘焙", "外卖"],
        "旅游出行": ["旅游", "旅行", "景点", "攻略", "酒店", "机票", "自驾", "露营", "徒步", "签证"],
        "购物消费": ["购物", "淘宝", "京东", "拼多多", "618", "双11", "潮牌", "球鞋", "数码产品", "性价比"],
        # --- 职业/发展 ---
        "实习就业": ["实习", "工作", "面试", "简历", "offer", "薪资", "大厂", "国企", "外企", "秋招", "春招", "内推"],
        "创业商科": ["创业", "商业", "市场", "营销", "管理", "MBA", "金融", "股票", "基金", "投资", "理财", "比特币"],
        "考证书": ["考证", "驾照", "教资", "CPA", "CFA", "法考", "建筑", "消防", "普通话", "计算机二级"],
        "出国留学": ["留学", "出国", "美国", "英国", "澳洲", "加拿大", "日本", "德国", "GRE", "GMAT", "申请", "offer"],
        # --- 社交/情感 ---
        "恋爱情感": ["恋爱", "表白", "分手", "暗恋", "对象", "男朋友", "女朋友", "前任", "Crush", "暧昧"],
        "校园生活": ["宿舍", "室友", "食堂", "图书馆", "选课", "绩点", "GPA", "学分", "奖学金", "社团", "学生会"],
        "星座命理": ["星座", "MBTI", "性格", "塔罗", "算命", "运势", "INTP", "INTJ", "ENFP"],
    }
    msg_lower = message.lower()
    for topic, keywords in interest_map.items():
        if any(kw.lower() in msg_lower for kw in keywords):
            add_interest(user_id, topic)


def adaptive_prefix(user_id: int) -> str:
    """Generate adaptive prefix for system prompt injection."""
    if user_id == ADMIN_QQ:
        return "[Admin - no adaptation needed]"
    p = get_or_create_profile(user_id)
    level = p["knowledge_level"]
    style = p["comm_style"]
    interests = get_top_interests(user_id)
    parts = ["[User: %s, level: %s, style: %s]" % (p.get("nickname") or str(user_id), level, style)]
    if interests:
        parts.append("Interests: " + ", ".join(interests))
    hint = LEVEL_HINTS.get(level, "")
    if hint:
        parts.append(hint)
    hint2 = STYLE_HINTS.get(style, "")
    if hint2:
        parts.append(hint2)
    return "\n".join(parts)
