"""LLM 优先情绪分析器 — 关键词兜底。（v3）"""

import json
import re
import asyncio
import logging

logger = logging.getLogger(__name__)

# ---- 关键词兜底（保留旧分析逻辑） ----

NEUTRAL_PATTERNS = re.compile(
    r"^(嗯|好|哦|行|可以|是的|对|OK|ok|知道了|收到|明白|晚安|早安|再见)\s*$"
)

POSITIVE_WARM = [
    "谢谢", "爱你", "喜欢", "想你", "好厉害", "开心", "太好", "真棒",
    "感动", "温暖", "好温柔", "好可爱", "爱了", "心动了", "暖", "治愈",
]
POSITIVE_PLAYFUL = [
    "哈哈哈", "hhh", "www", "草", "笑死", "太好笑了", "好有趣",
    "诶嘿", "嘻嘻", "噗", "棒棒", "哈哈哈笑死",
]
POSITIVE_INTIMATE = [
    "抱抱", "贴贴", "mua", "亲亲", "想你了", "陪我", "晚安咯",
    "早安呀", "在吗", "在不在", "理我一下",
]
NEGATIVE_HURT = [
    "讨厌", "别烦我", "滚", "走开", "够了", "不好", "生气",
    "拉黑", "取关", "不想理你",
]
NEGATIVE_COLD = [
    "不好", "烦", "无语", "算了", "呵呵", "随便",
    "不想说", "别问了", "累", "没意思", "没空",
]

QUESTION_PATTERNS = re.compile(r"[？?]|怎么|什么|帮帮|求|请教|帮我|如何|你觉得|为什么")
SHARE_PATTERNS = re.compile(
    r"\[image|\[video|http|pic|照片|图片|看这个|今天|昨天|刚才|我[去在到吃买看发]"
)
KAOMOJI_PATTERNS = re.compile(r"[(（][^)）]{1,10}[)）]")
TILDE_PATTERN = re.compile(r"~{1,}")


def analyze_fallback(text: str) -> dict:
    """关键词兜底分析，逻辑等同旧 MessageAnalyzer.analyze()。"""
    if not text or len(text) < 2:
        return {"sentiment": 0.0, "mood": "neutral", "nuance": "",
                "intensity": 1, "length": "空", "is_question": False,
                "is_share": False, "word_count": 0, "pos_score": 0,
                "neg_score": 0, "has_kaomoji": False, "tilde_count": 0}

    word_count = len(text)
    if word_count < 6:
        length = "短"
    elif word_count < 25:
        length = "中"
    else:
        length = "长"

    if NEUTRAL_PATTERNS.match(text.strip()):
        return {"sentiment": 0.0, "mood": "neutral", "nuance": "",
                "intensity": 1, "length": length, "is_question": False,
                "is_share": False, "word_count": word_count, "pos_score": 0,
                "neg_score": 0, "has_kaomoji": False, "tilde_count": 0}

    pos_score = 0
    for kw in POSITIVE_WARM:
        if kw in text: pos_score += 1
    for kw in POSITIVE_PLAYFUL:
        if kw in text: pos_score += 0.7
    for kw in POSITIVE_INTIMATE:
        if kw in text: pos_score += 1.2

    neg_score = 0
    for kw in NEGATIVE_HURT:
        if kw in text: neg_score += 1.5
    for kw in NEGATIVE_COLD:
        if kw in text: neg_score += 0.8

    net = pos_score - neg_score
    sentiment = max(-1.0, min(1.0, net * 0.4))

    mood = "neutral"
    if pos_score >= 3:
        mood = "happy"
    elif pos_score >= 1:
        mood = "tender"
    if neg_score >= 2:
        mood = "angry" if neg_score >= 3 else "sad"

    return {
        "sentiment": round(sentiment, 2),
        "mood": mood,
        "nuance": "",
        "intensity": max(1, min(5, int(abs(net)))),
        "length": length,
        "is_question": bool(QUESTION_PATTERNS.search(text)),
        "is_share": bool(SHARE_PATTERNS.search(text)),
        "word_count": word_count,
        "pos_score": pos_score,
        "neg_score": neg_score,
        "has_kaomoji": bool(KAOMOJI_PATTERNS.search(text)),
        "tilde_count": len(TILDE_PATTERN.findall(text)),
    }


# ---- LLM 优先分析 ----

SENTIMENT_PROMPT = """分析这条消息的情绪，仅返回JSON无其他文字：
{"sentiment":-1到1的浮点数,"mood":"happy/sad/angry/anxious/tender/playful/tired/neutral","nuance":"5字以内的微妙情绪描述","intensity":1到5的整数}"""


class SentimentAnalyzer:
    """LLM 优先情绪分析器。异步调用，超时自动兜底。"""

    def __init__(self):
        self._llm_client = None

    def _get_client(self):
        if self._llm_client is None:
            from src.llm.client import llm_client
            self._llm_client = llm_client
        return self._llm_client

    async def analyze(self, text: str) -> dict:
        """分析一条消息的情绪。LLM 优先，超时/报错则用关键词。"""
        if not text or len(text) < 6:
            return analyze_fallback(text)

        try:
            client = self._get_client()
            messages = [
                {"role": "system", "content": SENTIMENT_PROMPT},
                {"role": "user", "content": text[:200]},
            ]
            resp = await asyncio.wait_for(
                client.chat(messages, tools=None),
                timeout=3.0,
            )
            content = resp.get("content", "").strip()
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            result = json.loads(content)
            fb = analyze_fallback(text)
            result["length"] = fb["length"]
            result["is_question"] = fb["is_question"]
            result["is_share"] = fb["is_share"]
            result["word_count"] = fb["word_count"]
            result["pos_score"] = fb["pos_score"]
            result["neg_score"] = fb["neg_score"]
            result["has_kaomoji"] = fb["has_kaomoji"]
            result["tilde_count"] = fb["tilde_count"]
            result["llm"] = True
            return result
        except Exception:
            logger.debug("LLM sentiment failed, fallback to keyword")
            result = analyze_fallback(text)
            result["llm"] = False
            return result


sentiment_analyzer = SentimentAnalyzer()
