"""Strip Markdown formatting, resource-site URLs, and sensitive data from agent output for QQ."""
import re

# Email addresses — catch leaks before they reach QQ
EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.I)

# Credential-like patterns: "账号:xxx", "密码是xxx", "邮箱：xxx@xxx"
CREDENTIAL_RE = re.compile(
    r'(?:账号|密码|邮箱|登录|用户名|token|api[._-]?key|secret)[\s：:是为=]+\S{3,40}',
    re.I
)

# QQ号码 + 敏感上下文的组合（非机器人/管理员自己的QQ）
# 检测 "XXX@SCHOOL_DOMAIN" 这类学号邮箱模式
STUDENT_EMAIL_RE = re.compile(r'\d{5,12}@whut\.edu\.cn', re.I)


def strip_markdown(text):
    """Remove Markdown syntax that QQ cant render."""
    text = text.replace("**", "")
    # Strip leading dashes that leak from score_query.py / kb_manage.py output
    text = re.sub(r"^-\s+", "  ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s+-\s+", "  ", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = text.replace("```", "")
    text = re.sub(r"^\|.+\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_resource_urls(text):
    """Strip RESOURCE_SITE API/download URLs, keep share links (?id=...)."""
    share_re = re.compile(r'https?://RESOURCE_SITE/\?id=\d+')
    shares = share_re.findall(text)
    text = share_re.sub('__SHARE__', text)
    text = re.sub(r'https?://RESOURCE_SITE/\S+', '', text)
    for s in shares:
        text = text.replace('__SHARE__', s, 1)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def strip_sensitive(text):
    """Redact sensitive info from agent output before sending to QQ.

    Catches:
    - Email addresses (both @SCHOOL_DOMAIN and general)
    - Credential-like patterns (账号/密码/邮箱 followed by values)
    """
    if not text:
        return text

    # Redact student emails first (most specific pattern)
    text = STUDENT_EMAIL_RE.sub('[邮箱已隐藏]', text)

    # Redact all remaining email addresses
    text = EMAIL_RE.sub('[邮箱已隐藏]', text)

    # Redact credential patterns
    text = CREDENTIAL_RE.sub('[敏感信息已隐藏]', text)

    return text

# OpenClaw NO_REPLY control signal — strip it so it doesn't leak to QQ
NO_REPLY_RE = re.compile(r'^\s*NO_REPLY\s*$', re.MULTILINE)

def strip_no_reply(text):
    """Remove NO_REPLY control signal that may leak from OpenClaw agent."""
    if not text:
        return text
    text = NO_REPLY_RE.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# DeepSeek thinking-leak strip (2026-08-03) — remove chain-of-thought narration from replies
THINKING_LEAK_START = ["数据齐了", "关键差异已经清楚", "让我重新", "让我确认", "让我核对",
                       "从上面输出", "grep 结果", "我重新核对", "我已经拿到", "知识库里"]
THINKING_LEAK_END = ["我有足够信息", "给admin一个清晰的", "现在整理成", "我按这个给你",
                     "我来整理", "我来说说", "我来把", "我直接按", "让我来"]

# 英文推理泄漏: 开头英文思维块 (如 "The user said ... Let me be casual.")
_EN_LEAK_RE = re.compile(
    r"^(?:The user|the user|I should|Let me|I need to|I'm going to|I'll|meaning they|"
    r"continuing the conversation|respond naturally|The message|The person|"
    r"The admin|The assistant|The knowledge base|The conversation|The current|"
    r"The system|Based on the context|I think|I feel like|I want to|OK, |Okay, )"
    r"[^\u4e00-\u9fff]{5,400}?(?=[\u4e00-\u9fff])"
)


_DETACHED_MARKERS = [
    "上一轮", "上下文", "需要理解", "在私聊", "在群聊", "语气应该", "回复", "回应",
    "让我写", "让我回复", "让我看看", "让我看", "让我先", "让我想想", "让我来",
    "系统注入", "已知事实", "记忆恢复", "The user", "I should", "Let me",
    "meaning they", "Based on the context", "The admin", "The assistant", "said", "continu",
    "对话记录", "之前的对话", "从对话", "这段对话", "我们的对话", "用户问",
    "[Called", "Called exec", "Called read", "Called process", "工具调用",
    "用户说", "可以看到", "历史记录", "刚看了一下", "结合上下文",
]
_DIRECT_START = ("你", "哈哈", "那", "好呀", "哈", "诶", "下午好", "中午好", "早上好",
                 "晚上好", "早呀", "在呢", "嗯", "对呀", "哦", "真的")


def _is_meta_sentence(s):
    """Detect detached meta-reasoning sentences (NOT direct address to user)."""
    if not s:
        return False
    if s.startswith(_DIRECT_START):
        return False
    hits = sum(1 for m in _DETACHED_MARKERS if m in s)
    return hits >= 1


def strip_thinking_leak(text):
    """Strip chain-of-thought narration leaking into the reply (中英).
    Conservative: only removes strong reasoning-process markers."""
    if not text:
        return text
    # 1) 英文推理前置块: 去掉开头英文思维, 保留中文答案
    m = _EN_LEAK_RE.match(text)
    if m:
        # 英文思维块通常以「英文句号+中文答案」收尾, 取最后一个
        cuts = [mm.end() for mm in re.finditer(r"\.(?=\s*[一-鿿])", text)]
        if cuts:
            text = text[cuts[-1]:].strip()
        else:
            text = text[m.end():].strip()
        if not text:
            return text
    # 2) 元推理块: 开头句子是关于对话的思考, 剥到第一个直接回答
    sents = re.split(r"(?<=[。！？!?])", text)
    if sents and _is_meta_sentence(sents[0]):
        i = 0
        while i < len(sents) and _is_meta_sentence(sents[i]):
            i += 1
        text = "".join(sents[i:]).strip()
        if not text:
            return text
        sents = re.split(r"(?<=[。！？!?])", text)
    # 3) 中文推理块
    # 重新按句遍历
    cleaned = []
    in_reasoning = False
    for s in sents:
        t = s.strip()
        if not t:
            continue
        hit_start = any(m in t for m in THINKING_LEAK_START)
        hit_end = any(m in t for m in THINKING_LEAK_END)
        if hit_start:
            in_reasoning = True
            continue
        if in_reasoning:
            if hit_end:
                in_reasoning = False
                continue
            if len(t) < 150 and ("我" in t[:8] or "让" in t[:8] or "输出" in t or "核对" in t
                                 or "确认" in t or "grep" in t or "提取" in t):
                continue
            in_reasoning = False
        cleaned.append(t)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    return result if result else text
