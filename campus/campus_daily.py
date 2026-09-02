#!/usr/bin/env python3
"""Fetch yesterday's notices from WHUT 综合信息网 (学校通知).
Usage: python3 campus_daily.py [--today]
Outputs formatted QQ message with yesterday's (or today's) new notices.
"""
import sys, re, os, json
from datetime import datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

# Check for --today flag before overriding sys.argv
_original_argv = sys.argv[:]
_use_today = '--today' in _original_argv
TARGET_DATE = datetime.now().strftime('%Y-%m-%d') if _use_today else (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

sys.argv = ['campus_search.py', '__campus_daily__']
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Suppress campus_search module-level search output
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')
# sys.stderr was suppressed here (removed to surface errors)
import campus_search
sys.stdout.close()
sys.stdout = _real_stdout

TARGET_URL = 'http://i.whut.edu.cn/xxtg/'

# 09-02: 学生相关性过滤。综合信息网是全校门户，大量通知面向教职工/行政
# （工会、人事、采购、基建…），班群受众是学生，这些推送全是噪音。
# 规则：命中行政部门标签或教师向排除词 → 丢弃；否则命中学生关键词才保留。
STUDENT_KEYWORDS = (
    "学生", "本科生", "研究生", "博士生", "推免", "保研", "考研",
    "免试攻读", "选课", "补考", "缓考", "重修", "成绩", "考试",
    "竞赛", "大赛", "报名", "自习", "体测", "体质健康", "缓测",
    "奖学金", "助学金", "资助", "贷款", "勤工", "评优", "表彰",
    "社团", "志愿者", "支教", "讲座", "实习", "实践", "毕业",
    "答辩", "学位", "四六级", "普通话", "征兵", "军训", "报到",
    "注册", "开学", "宿舍", "校园卡", "图书", "班车", "医保",
    "体检", "心理", "学工", "辅导员", "团委", "社会实践",
    "寒暑假", "放假", "校历", "信号屏蔽", "停电", "停水",
    "缴费", "学费", "招聘会", "宣讲会", "就业",
)
NOTICE_EXCLUDE_KEYWORDS = (
    "留学生", "教研", "教职工", "青年教师", "教师岗", "师资",
    "博士后", "拟聘用", "任前公示", "出国研修", "成果转化",
    "周转房", "住房", "公积金", "正版化",
)
ADMIN_DEPT_TAGS = (
    "工会", "人力资源部", "后管处", "基建处", "组织部", "统战部",
    "纪检监察", "纪委", "党校", "离退休", "档案馆", "审计处",
    "发展规划处", "采购", "招投标",
)
# 09-02b: 生活服务类词。行政处室（后管处/基建处）也会发学生关心的
# 停电停水/班车通知，这些词优先于行政标签判定，避免被一刀切否决。
UTILITY_KEYWORDS = (
    "停电", "停水", "停气", "断网", "网络中断", "校园网", "供电", "供水",
    "直饮水", "热水", "班车", "食堂", "超市",
)


def is_student_notice(title):
    """Keyword fast-path（判定顺序经过设计，勿随意调整）：
    1. 排除词 → False（正版化/周转房等已知噪音，硬否决）；
    2. 生活服务词 → True（后管处停电停水也是学生要看的）；
    3. 行政部门标签 → False（纯行政噪音，不给 NB 翻案）；
    4. 学生关键词 → True；
    5. 其余 → False，交给 NB 分类器兜底（见 main）。"""
    if any(w in title for w in NOTICE_EXCLUDE_KEYWORDS):
        return False
    if any(w in title for w in UTILITY_KEYWORDS):
        return True
    if any(tag in title for tag in ADMIN_DEPT_TAGS):
        return False
    return any(w in title for w in STUDENT_KEYWORDS)


# 09-02b: 本地机器学习兜底层（零 API 成本）。
# 关键词白名单追不上通知措辞的变化（如"网上缴费""信号屏蔽""直饮水暂停"这类
# 不含任何关键词的标题），参考 GitHub 上校园通知机器人（CampusPing 等）用
# ML 判定相关性的思路，改为本地实现：字符 2/3-gram 多项式朴素贝叶斯，
# 训练集为人工标注的历史推送标题（campus_notice_labels.json，209 条）。
# 每次运行内存内训练一次（毫秒级），无任何外部依赖、不调用任何 API。
NOTICE_LABELS_FILE = Path(__file__).resolve().with_name('campus_notice_labels.json')

import math as _math

_NB_CACHE = None


def _char_grams(text):
    t = re.sub(r'\s+', '', text)
    grams = []
    for n in (2, 3):
        if len(t) >= n:
            grams += [t[i:i + n] for i in range(len(t) - n + 1)]
    return grams


def _train_nb():
    """Train multinomial NB on labeled titles. Returns (counts, meta)."""
    global _NB_CACHE
    if _NB_CACHE is not None:
        return _NB_CACHE
    counts = {0: {}, 1: {}}
    ndocs = {0: 0, 1: 0}
    totals = {0: 0, 1: 0}
    vocab = set()
    try:
        data = json.loads(NOTICE_LABELS_FILE.read_text(encoding='utf-8'))
        for x in data['labels']:
            y = int(x['y'])
            ndocs[y] += 1
            for g in set(_char_grams(x['t'])):
                counts[y][g] = counts[y].get(g, 0) + 1
                totals[y] += 1
                vocab.add(g)
    except Exception as e:
        print('[campus_daily] NB labels unavailable, keyword-only mode:', e, file=sys.stderr)
    _NB_CACHE = (counts, {'ndocs': ndocs, 'totals': totals, 'V': max(len(vocab), 1)})
    return _NB_CACHE


def ml_is_student(title):
    """Local NB verdict for keyword-miss titles.
    Returns (keep 0/1, log-odds margin). Threshold 2.5 tuned on the labeled set
    (production view: keyword-missed docs only, LOO — recall 17/20, ~1 FP / 5 days).
    Empty model (labels file missing) → (0, 0.0), i.e. fall back to keyword-only."""
    counts, meta = _train_nb()
    if not meta['ndocs'][0] or not meta['ndocs'][1]:
        return 0, 0.0
    n = meta['ndocs'][0] + meta['ndocs'][1]
    scores = {}
    for c in (0, 1):
        lp = _math.log(meta['ndocs'][c] / n)
        denom = meta['totals'][c] + meta['V']
        for g in set(_char_grams(title)):
            lp += _math.log((counts[c].get(g, 0) + 1) / denom)
        scores[c] = lp
    margin = scores[1] - scores[0]
    return (1 if margin > 2.5 else 0), margin

# TARGET_DATE (today or yesterday) defined above

# sent-URL cache: prevents Seeyon OA dynamic links (which don't embed dates in URLs)
# from being re-sent when the school site groups them under a newer date section.
SENT_CACHE = Path(os.path.dirname(os.path.abspath(__file__))) / 'data' / 'campus_sent_cache.json'

def load_sent_cache():
    if SENT_CACHE.exists():
        try:
            data = json.loads(SENT_CACHE.read_text())
            return data.get('urls', [])
        except:
            pass
    return []

def save_sent_cache(urls):
    SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SENT_CACHE.write_text(json.dumps({
        'urls': urls[-1000:],
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, ensure_ascii=False))


def fetch_notice_list():
    """Fetch and parse the xxtg notice list page. Returns list of (date, title, url)."""
    session = campus_search.session
    webvpn_url = campus_search.encode_url(TARGET_URL)
    try:
        r = session.get(webvpn_url, timeout=15, allow_redirects=True)
    except Exception as e:
        print('[FAIL] campus_daily: network error -', e)
        sys.exit(1)
    if r.status_code != 200:
        print('[FAIL] campus_daily: server returned HTTP', r.status_code, '- will retry later')
        sys.exit(1)

    # Fix encoding
    r.encoding = 'utf-8'
    text = r.text
    if '学校' not in text and '通知' not in text:
        r.encoding = 'gbk'
        text = r.text

    soup = BeautifulSoup(text, 'lxml')
    items = []
    seen = set()

    for a in soup.select('a[href]'):
        title = a.get_text(strip=True)
        href = a.get('href', '')
        if not title or len(title) < 10:
            continue

        # Method 1: extract date from URL path (most reliable for standard WHUT notices)
        # WHUT URLs embed date as .../YYYYMM/tYYYYMMDD_xxx.shtml (e.g. /202605/t20260522_1400259.shtml)
        date_str = None
        if href:
            um = re.search(r'/t(202[56])(\d{2})(\d{2})_', href)
            if um:
                date_str = f'{um.group(1)}-{um.group(2)}-{um.group(3)}'

        # Method 2: extract date from <li> text (reliable for Seeyon OA URLs without date in path)
        if not date_str:
            li = a.find_parent('li')
            if li:
                li_dates = re.findall(r'(202[56][-/]\d{2}[-/]\d{2})', li.get_text())
                if li_dates:
                    date_str = li_dates[-1]

        # Method 3: fallback to ancestor text
        if not date_str:
            ancestor_text = ''
            el = a.parent
            for _ in range(5):
                if el:
                    ancestor_text += ' ' + el.get_text()
                    el = el.parent
            dm = re.search(r'(202[56])[-/](\d{2})[-/](\d{2})', ancestor_text)
            if not dm:
                continue
            date_str = dm.group(0)

        original_url = campus_search.decode_webvpn_url(href) if href else ''

        # Deduplicate
        key = title[:40]
        if key not in seen:
            seen.add(key)
            items.append((date_str, title, original_url))

    return items


def format_message(notices):
    """Format notices into a QQ-friendly message."""
    if not notices:
        return None

    lines = [
        '\U0001F4CB 综合信息网 · 最新通知',
        '━' * 16,
    ]
    for i, (date, title, url) in enumerate(notices[:15], 1):
        short_title = title[:55] + '...' if len(title) > 55 else title
        lines.append(f'{i}. {short_title}')
        if url:
            lines.append(f'   \U0001F517 {url}')

    if len(notices) > 15:
        lines.append(f'\n... 还有 {len(notices) - 15} 条，详见 http://i.whut.edu.cn/xxtg/')

    lines.append('━' * 16)
    return '\n'.join(lines)


def main():
    try:
        notices = fetch_notice_list()
        # 09-02b: 两级过滤——关键词快速通道 + 本地 NB 分类器兜底（零 API 成本）
        kept_kw = [(d, t, u) for d, t, u in notices if is_student_notice(t)]
        borderline = [(d, t, u) for d, t, u in notices if not is_student_notice(t)]
        for d, t, u in borderline:
            # 行政部门标签/教师向排除词 = 硬否决（生活服务词已在快速通道优先放行，
            # 所以后管处停电停水不受影响），不给 NB 翻案机会
            if any(tag in t for tag in ADMIN_DEPT_TAGS) or any(w in t for w in NOTICE_EXCLUDE_KEYWORDS):
                print(f'[campus_daily] filter drop (hard): {t[:45]}', file=sys.stderr)
                continue
            pred, margin = ml_is_student(t)
            if pred:
                kept_kw.append((d, t, u))
                print(f'[campus_daily] NB rescue (logodds={margin:.1f}): {t[:45]}', file=sys.stderr)
            else:
                print(f'[campus_daily] filter drop (kw+NB, logodds={margin:.1f}): {t[:45]}', file=sys.stderr)
        notices = kept_kw
        yesterday_notices = [(d, t, u) for d, t, u in notices if d == TARGET_DATE]

        # Skip items whose URL was already included in a previous campus daily run.
        # This prevents Seeyon OA dynamic links (no date in URL path) from being
        # re-sent when the school site re-groups them under a different date section.
        sent_cache = load_sent_cache()
        yesterday_notices = [(d, t, u) for d, t, u in yesterday_notices if not u or u not in sent_cache]

        if not yesterday_notices:
            # Try the latest date in the data (weekend/holiday fallback)
            if notices:
                latest = sorted(set(d for d, _, _ in notices), reverse=True)[0]
                fb = [(d, t, u) for d, t, u in notices if d == latest]
                fb = [(d, t, u) for d, t, u in fb if not u or u not in sent_cache]
                if fb:
                    msg = format_message(fb)
                    if msg:
                        msg = msg.replace(TARGET_DATE, latest)
                        msg = msg.replace("昨日通知", "最新通知")
                        print(msg)
                        new_urls = [u for _, _, u in fb if u and u not in sent_cache]
                        sent_cache.extend(new_urls)
                        sent_cache = sent_cache[-1000:]
                        save_sent_cache(sent_cache)
                        return
            print('')  # No output = skip send
            return

        msg = format_message(yesterday_notices)
        if msg:
            new_urls = [u for _, _, u in yesterday_notices if u and u not in sent_cache]
            sent_cache.extend(new_urls)
            sent_cache = sent_cache[-1000:]
            save_sent_cache(sent_cache)
            print(msg)
    except Exception as e:
        import traceback
        print(f'[campus_daily error] {e}', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
