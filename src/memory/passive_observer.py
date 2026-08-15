"""被动知识观察器：实时读取群消息，自动提取事实存入记忆。

成本控制优先：多层过滤确保只有高质量消息进入 LLM 批量提取。
高流量群（每天几百条消息）也能安全运行，不浪费 API 费用。
"""
import re
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__import__('os').environ.get("QQBOT_DATA_DIR", "data"))

# 最近处理过的 message_id（去重）
_seen_mids: set[int] = set()
MAX_SEEN = 1000

# 批量 LLM 提取缓冲区
_buffer: list[dict] = []
BUFFER_MAX = 40       # 缓冲区上限才触发 LLM
BUFFER_MIN = 20       # 最少也要攒够 20 条
_last_llm_extract = 0.0
LLM_INTERVAL = 3600   # 60 分钟内最多触发一次 LLM 批量

# 每个用户在缓冲区中的消息上限（防止一人刷屏占满缓冲）
PER_USER_BUFFER_MAX = 4

# 最近缓冲消息的哈希（相似内容去重）
_recent_hashes: list[int] = []


def _has_cjk(text: str) -> bool:
    """检查是否包含至少 min_chars 个中文字符。"""
    cjk = re.findall(r"[一-鿿]", text)
    return len(cjk) >= 4


def _is_sensitive(text: str) -> bool:
    """敏感内容检测。返回 True 表示跳过提取（不存入记忆）。"""
    # 敏感内容过滤（成年用户群，放宽日常两性话题，坚守违法红线）
    sensitive_patterns = [
        # 色情/淫秽（违法 — 绝不提取）
        r"(裸照|裸聊|私密照|艳照|luo[照聊])",
        r"(约炮|YP|一夜情|嫖娼|卖淫|嫖|妓女|援交)",
        r"(SM.*圈|性奴|字母圈.*调教)",
        # 自残/自杀（安全 — 不提取但需关注）
        r"(自残|自杀|想死|不想活|割腕|跳楼|安眠药.*死)",
        # 毒品/违法（红线）
        r"(毒品|吸毒|贩毒|溜冰|嗑药|大麻|海洛因|冰毒)",
        # 赌博（违法）
        r"(赌博|网赌|赌球|赌场|下注|庄家)",
    ]
    for pat in sensitive_patterns:
        if re.search(pat, text):
            return True
    return False


def _is_noise(text: str) -> bool:
    """多级噪音过滤。返回 True 表示跳过。"""
    text = text.strip()

    # L0: 敏感内容不提取
    if _is_sensitive(text):
        return True

    # L1: 长度检查
    if len(text) < 4:
        return True
    if len(text) > 300:  # 长文通常是转发/公告/故事，不是个人事实
        return True

    # L2: 必须包含足够中文（过滤纯表情/数字/英文/拼音）
    if not _has_cjk(text):
        return True

    # L3: 纯 CQ 码（图片/表情/语音）
    if re.match(r"^\[CQ:[^\]]+\]$", text):
        return True

    # L4: 纯标点/空格
    if re.match(r"^[?？!！.。，,、;；:：…~～\s\d]+$", text):
        return True

    # L5: 短回复词典（最常见的无意义回复）
    short_replies = {
        "好的", "好", "嗯", "哦", "行", "OK", "ok", "对", "是的", "谢谢", "没事",
        "没有", "有", "是", "哈哈", "哈哈哈", "哈哈哈哈", "笑死", "草", "艹",
        "nb", "牛逼", "牛", "6", "666", "6666", "确实", "确实是这样", "没错",
        "来了", "在", "有人吗", "有人不", "1", "111", "dd", "打卡", "早", "晚安",
        "可以的", "可以", "还行", "不错", "真好", "加油", "辛苦了", "收到",
        "知道了", "了解", "懂了", "明白了", "好嘞", "好滴", "okok", "okk",
        "www", "w", "草草草", "乐", "太强了", "强", "支持", "顶", "赞",
    }
    if text.lower() in short_replies:
        return True

    # L6: @别人 的消息 — 但公告/通知类放行（通常 @全体成员）
    if re.search(r"\[CQ:at,qq=\d+\]", text):
        if not re.search(r"(通知|公告|提醒|注意|各位|大家|同学们|选课|考试|补考|重修|教务处|本科生院|学院|截止|报名|缴费|提交|答辩|答辩|开题|毕业)", text):
            return True

    # L7: 纯问句开头 + 很短（在问别人问题，不是陈述自己的信息）
    if len(text) < 15 and re.match(r"^(有没有|有人|谁|怎么|什么|为啥|为什|几点|哪里|哪儿|哪个|多少钱|能不能|可以不可以)", text):
        return True

    return False


def _content_hash(text: str) -> int:
    """简单的内容哈希，用于相似去重。"""
    # 取前 30 字 + 后 10 字的规范化哈希
    t = re.sub(r"\s+", "", text.strip())
    return hash((t[:30], t[-10:]))


def _extract_facts_local(user_id: int, nickname: str, text: str) -> list[str]:
    """本地正则提取事实。返回事实列表，每条 ≤ 30 字。"""
    facts = []
    text = text.strip()
    if len(text) < 6:
        return facts

    patterns = [
        # === 学校通知/公告（优先匹配，高价值信息）===
        (r"(?:通知|公告|提醒)[：:]\s*(.+?)(?:，|。|！|$)", r"\1"),
        (r"【(.+?)】\s*(.+?)(?:，|。|！|$)", r"\1：\2"),
        (r"关于(.+?)的通知", r"通知：\1"),
        # 选课/考试/教务
        (r"(?:选课|补考|重修|考试)(?:通知|安排|时间)[：:]*\s*(.+?)(?:，|。|！|$)", r"考试安排：\1"),
        (r"(\d{1,2})月(\d{1,2})[日号](?:前|之前|截止)(.+?)(?:，|。|！|$)", r"截止\1月\2日：\3"),
        (r"(?:明天|后天|下周[一二三四五六日]|周[一二三四五六日])(.+?)(?:考试|上课|答辩|开会|交|提交)(.+?)(?:，|。|！|$)", r"日程：\g<0>"),
        # 机构+动作
        (r"(?:本科生院|教务处|研究生院|学工部)(?:通知|提醒|公告)?[：:]?\s*(.+?)(?:，|。|！|$)", r"官方通知：\1"),
        # === 身份/专业 ===
        (r"我是学(.+?)(?:的|，|。|！|$)", r"学\1"),
        (r"我学的?是(.+?)(?:，|。|！|$)", r"专业是\1"),
        (r"我是(\S{2,4})专业的?", r"专业是\1"),
        (r"我读(.+?)(?:的|专业|，|。|！|$)", r"读\1"),
        # === 名字/称呼 ===
        (r"我叫(.+?)(?:，|。|！|$)", r"ta叫\1"),
        # === 位置 ===
        (r"我在(.+?)(?:上学|读书|工作|上班)", r"在\1"),
        (r"我住(.+?)(?:，|。|！|$)", r"住在\1"),
        (r"我(?:是|来自)(\S{2,6})人", r"是\1人"),
        # === 喜好 ===
        (r"我(?:很|非常|特别|超)?喜欢(.+?)(?:，|。|！|$)", r"喜欢\1"),
        (r"我不喜欢(.+?)(?:，|。|！|$)", r"不喜欢\1"),
        # === 正在做/近期计划 ===
        (r"我(?:最近)?在(学|做|搞|弄|准备|考|复习)(.+?)(?:，|。|！|$)", r"最近在\1\2"),
        (r"(?:期末|期中|明天|后天|下周|这周|马上)(?:要|需要)?(?:考|考试|复习|做|写|交)(.+?)(?:，|。|！|$)", r"近期要考\1"),
        (r"我(?:今天|明天|后天|下周|这周)要?(.+?)(?:，|。|！|$)", r"计划\1"),
        # === 想法/状态 ===
        (r"我觉得(.+?)(?:，|。|！|$)", r"觉得\1"),
        # === 通用"我是X"兜底 ===
        (r"我是(.{2,8}?)(?:的|，|。|！|$)", r"我是\1"),
    ]

    for pat, tmpl in patterns:
        m = re.search(pat, text)
        if m:
            try:
                fact = m.expand(tmpl)
            except Exception:
                fact = m.group(0)
            fact = re.sub(r"^是", "", fact).strip()
            if 3 < len(fact) <= 30 and fact not in facts:
                facts.append(fact)
        if len(facts) >= 3:
            break

    return facts


def _categorize(fact: str) -> str:
    """根据内容推断事实类别。"""
    if re.search(r"(通知|公告|考试|选课|补考|重修|答辩|截止|教务处|本科生院|学院|学校)", fact):
        return "event"
    if re.search(r"(我是|我叫|专业|学的是|读的是|住在|来自.*人)", fact):
        return "identity"
    if re.search(r"(喜欢|不喜欢|爱吃|讨厌|想)", fact):
        return "preference"
    if re.search(r"(计划|要考|要交|要写|要做|准备|最近在)", fact):
        return "status"
    return "general"


def _write_to_l1(user_id: int, fact: str) -> None:
    """将事实写入 L1 短期记忆（SQLite），接入 L1→L2→L3 管道。"""
    try:
        from src.memory.layers import l1_add
        cat = _categorize(fact)
        l1_add(user_id, fact, category=cat, importance=2)
    except Exception:
        pass  # db 不可用时静默降级，JSON 存储仍正常


def observe(user_id: int, nickname: str, text: str, message_id: int = 0) -> None:
    """被动观察一条群消息，提取知识并缓冲。

    多层过滤确保高流量群也不浪费成本。
    轻量、不阻塞、不回复。"""
    global _seen_mids, _recent_hashes

    if message_id and message_id in _seen_mids:
        return
    if message_id:
        _seen_mids.add(message_id)
        if len(_seen_mids) > MAX_SEEN:
            _seen_mids = set(list(_seen_mids)[-MAX_SEEN // 2:])

    if _is_noise(text):
        return

    # 本地正则提取（免费，严格过滤后才执行）
    local_facts = _extract_facts_local(user_id, nickname, text)
    if local_facts:
        from src.memory.store import memory_store
        for fact in local_facts:
            memory_store.remember(user_id, fact, nickname)
            # 同时写入 L1 短期记忆（进入 L1→L2→L3 管道）
            _write_to_l1(user_id, fact)
        print(f"[passive] {user_id} {nickname}: {local_facts}")

    # 缓冲池控制：只有足够"信息量"的消息才进缓冲区
    clean = text.strip()[:200]
    if not (15 <= len(clean) <= 200):
        return

    # 相似内容去重
    h = _content_hash(clean)
    if h in _recent_hashes:
        return
    _recent_hashes.append(h)
    if len(_recent_hashes) > 100:
        _recent_hashes = _recent_hashes[-50:]

    # 每个用户在缓冲区中不超过 PER_USER_BUFFER_MAX 条
    user_count = sum(1 for item in _buffer if item["user_id"] == user_id)
    if user_count >= PER_USER_BUFFER_MAX:
        return

    _buffer.append({
        "user_id": user_id,
        "nickname": nickname,
        "text": clean,
        "time": datetime.now().isoformat(),
    })
    # 缓冲区硬上限
    if len(_buffer) > BUFFER_MAX * 2:
        _buffer[:] = _buffer[-BUFFER_MAX:]


async def flush_llm_extract():
    """批量 LLM 提取：将缓冲区的消息发给 DeepSeek，提取事实。

    触发条件：缓冲区 ≥ BUFFER_MAX 条 或 距上次 ≥ LLM_INTERVAL 且 ≥ BUFFER_MIN 条。
    """
    global _buffer, _last_llm_extract

    if len(_buffer) < BUFFER_MIN:
        return
    if time.time() - _last_llm_extract < LLM_INTERVAL and len(_buffer) < BUFFER_MAX:
        return

    to_process = _buffer[:BUFFER_MAX]
    _buffer[:] = _buffer[BUFFER_MAX:]
    _last_llm_extract = time.time()

    lines = []
    for i, item in enumerate(to_process):
        lines.append(f"[{i}] {item['nickname']}(QQ{item['user_id']}): {item['text']}")

    prompt = (
        "从以下群聊消息中提取关于每个人的**新事实**（之前不知道的信息）。\n"
        "规则：\n"
        "- 每条事实以「QQ号: 事实内容」格式输出\n"
        "- 只提取关于具体个人的信息（喜好、计划、状态、身份等）\n"
        "- 不提取对别人的评价、闲聊废话、表情\n"
        "- 每条约 5-20 字，不含编号\n"
        "- 如果没有可提取的事实，输出「无」\n\n"
        + "\n".join(lines)
    )

    try:
        from src.llm.client import llm_client
        resp = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            tools=None,
        )
        content = resp.get("content", "")
    except Exception as e:
        print(f"[passive] LLM extract failed: {e}")
        return

    if not content or "无" in content[:5]:
        return

    from src.memory.store import memory_store

    valid_uids = {item["user_id"] for item in to_process}
    user_map = {str(item["user_id"]): item for item in to_process}
    for line_text in content.strip().split("\n"):
        line_text = line_text.strip()
        m = re.match(r"(\d{5,15}):\s*(.+)", line_text)
        if m:
            uid = int(m.group(1))
            fact = m.group(2).strip()
            if len(fact) >= 3 and uid in valid_uids:
                nick = user_map.get(str(uid), {}).get("nickname", "")
                memory_store.remember(uid, fact, nick)
                print(f"[passive:llm] {uid}: {fact}")

    print(f"[passive] LLM batch processed {len(to_process)} msgs, cost ~1 API call")
