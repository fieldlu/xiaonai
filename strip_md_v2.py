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
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = text.replace("```", "")
    text = re.sub(r"^\|.+\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_resource_urls(text):
    """Strip ALL RESOURCE_SITE URLs that have a path.
    Only the bare domain (https://RESOURCE_SITE) survives.
    This is intentional: the agent fabricates /d/, /detail/, /api/download/ etc.
    URLs that all return auth errors for end users."""
    text = re.sub(r"https?://RESOURCE_SITE/\S+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
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
