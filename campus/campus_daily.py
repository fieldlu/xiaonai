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

# ============================================================
# 学生相关性过滤（09-02c 数据驱动重写 → 09-02f 扩充：251 条标注回归 acc=100%）
# 综合信息网是全校门户，大量通知面向教职工/行政（工会、人事、采购、基建…），
# 班群受众是学生，这些推送全是噪音。过滤管线分层：
#   1) 硬黑名单（教师/职工/行政噪音词）
#   2) 强白名单（无歧义的学生/竞赛/生活词，先于部门否决）
#   3) 部门硬否决（纯行政/科研部门）
#   4) 弱白名单（宽泛词，行政部门否决后再放行）
#   5) 服务/学生部门默认放行
#   6) 残余 → 本地 NB 分类器兜底（零 API 成本）
# ============================================================

# 1) 硬黑名单：明确面向教师/职工/行政，正例中不会出现
BLACKLIST = (
    "工勤", "技师", "教职工", "青年教师", "教师岗", "师资", "博士后",
    "导师", "指导教师", "教材", "教研", "微课大赛", "微课教学", "微课建设",
    "课程思政", "教学设计", "教学竞赛",
    "教学类人才", "智慧课程", "先进工作者", "先进集体", "校企",
    "科研成果", "教育教学改革", "教改", "工程案例", "辅导员", "岗前培训",
    "行业育人", "正版化", "周转房", "三伏贴", "规章制度",
    # ("一号门"已移除，09-02f)：余区管委会"一号门临时封闭"通告关乎学生校门通行，
    # 此前被子串误杀；教职工向的周转房通知仍由"周转房"单独拦截。
    "防汛", "政府采购", "消防", "实验室安全", "值班表", "采购", "招投标",
    "任前公示", "拟聘用", "拟立项", "出国研修", "成果转化", "留学生",
    "公积金", "住房", "技能人才", "干部", "党员", "党支部", "中心组",
    "津贴", "揭榜挂帅", "成果文库", "优质新刊", "学术著作",
    "专业公示", "专业设置", "专业调整", "职称",
    # 党建会议铁词（09-02e 补）：党政机关内部会议通知常不带【部门】前缀，
    # 会漏到 NB 兜底被高分捞回（实测"政绩观学习教育总结会" margin=12.8 误推）。
    # 均为党内专用措辞，与 209 条标注正例零冲突。
    "政绩观", "民主生活会", "组织生活会", "三会一课", "主题教育",
    "党纪", "廉政", "廉洁", "巡察", "见习期", "收听收看", "六访六促",
    "研究专项",
    # 教学管理向复合词（09-02e 补）：本科生院等学生部门也发教师向的教改/教学
    # 管理通知，会借【本科生院】前缀命中"本科"强白放行。学生通知标题不会用
    # 这些措辞（选课/考试/课表/竞赛用词均不含），黑名单先于强白执行可精准拦截。
    "教学改革", "教学研究", "教学任务", "教学检查", "教学观摩", "教学创新",
    "教学日历", "教学质量", "教学督导", "课堂教学", "教学成果", "教学建设",
    "教学申报", "混合式教学", "教学案例库", "课程资源", "资源库", "实践基地申报",
    "党建", "医工交叉", "科普讲解", "科普短视频", "用印",
    # 教职工福利/赛事向残留 FP（09-02f 补，1032 条收割 + 120 样本复核）：
    # 幼儿园招生/离退休报销/财务借款/因公出访/高校教师数智教育大赛，正例零冲突。
    "幼儿园", "离退休", "借款", "出访", "数智教育", "高校教师",
    # 党建/教师向会议措辞（09-02d 补二）：
    # "学习贯彻"拦"召开学习贯彻…精神宣讲报告会"（其"召开学"子串会误命中"开学"白名单）；
    # "教师节/优秀教师"拦教师向表彰大会（其"表彰"会误中强白名单）。
    "学习贯彻", "召开学习", "教师节", "优秀教师", "教学名师", "师德师风",
    # "思政工作"（09-02f 补）：学工部内部对辅导员的"思政工作怎么做"专题培训，
    # 学工部已进 POS_DEPTS 默认放行，需此词先行拦截（全集仅此 1 条命中，零冲突）。
    "思政工作",
)

# 2) 强白名单：无歧义的学生/竞赛/生活词，先于部门否决
#   （覆盖"博士生专项计划"这类行政部门下发的学生项目）
WHITELIST_STRONG = (
    # 比赛
    "竞赛", "大赛", "比赛", "挑战赛", "挑战杯", "校赛", "创意赛",
    "创新创业", "创新大赛", "创业计划", "选拔赛", "选拔",
    # 生活服务
    "停电", "停水", "停气", "断网", "网络中断", "校园网", "供电", "供水",
    "直饮水", "热水", "班车", "食堂", "超市", "水电", "收费", "收发",
    "水池", "水箱", "清洗", "图书馆", "医院", "校园卡", "医保", "缴费",
    "信号屏蔽", "邮箱", "VPN", "云平台", "快递", "门禁", "空调",
    # 施工/通行影响（09-02f 补）：基建处/保卫处/余区管委会发布的道路封闭、占道、
    # 打围、交通管制通告直接影响学生通行路线与日常生活（全集 35/37 条基建处通知
    # 属此类），须先于部门否决放行；其行政类（需求征集/停车场整改）无这些词仍被拦。
    "临时封闭", "占道", "打围", "交通管制", "道路维修",
    # 课程 / 学业
    "选课", "补考", "缓考", "重修", "成绩", "考试", "自习",
    "体测", "体质健康", "缓测", "四六级", "普通话", "免试攻读", "推免",
    "保研", "考研", "答辩", "学位", "毕业", "报到", "注册", "开学",
    "校历", "本科",
    # 学生 / 综合
    "学生", "本科生", "研究生", "博士生", "助学金", "奖学金", "贷款",
    "勤工", "社团", "志愿者", "支教", "讲座", "实习", "实践", "评优",
    "表彰", "招聘会", "宣讲会", "就业", "心理", "国际合作",
)

# 4) 弱白名单：宽泛词，放在部门否决之后
#   （"暑假/网络/课程/放假"在行政、科研部门通知里是噪音，不能先于部门否决放行；
#     档案馆/工会的"放假/值班安排"被 NEG_DEPTS 拦，党政办/无部门的全校放假仍放行）
WHITELIST_WEAK = ("暑假", "寒假", "暑期", "网络", "课程", "放假")

# 3) 纯行政/科研部门（硬否决；强白名单已先行放行"博士生专项"等学生项）
NEG_DEPTS = (
    "人文社科处", "人力资源部", "基建处", "工会", "科技转化中心",
    "实验设备处", "测试中心", "组织部", "保卫处", "社会合作处",
    "党委教师工作部", "襄阳示范区", "机关直属单位党委", "留学生管理服务中心",
    "科发院", "三亚科教园", "宣传部",
    "档案馆", "巡察办", "纪委", "人事处",
)

# 5) 服务/学生部门（默认放行；黑名单已先行剔除 工勤/正版化/先进集体/三伏贴/周转房/
#    辅导员培训/思政工作培训 等教职工向内容）
POS_DEPTS = (
    "网络中心", "后管处", "图书馆", "后勤集团", "医院", "医管办",
    "财务处", "体育学院", "团委", "学工部",
)

DEPT_RE = re.compile(r'^【([^】]{1,12})】')


def dept_of(title):
    m = DEPT_RE.match(title)
    return m.group(1) if m else ''


def classify(title):
    """分层判定，返回 'keep' | 'drop' | 'ml'（'ml' 交 NB 兜底）。"""
    for w in BLACKLIST:
        if w in title:
            return 'drop'
    for w in WHITELIST_STRONG:
        if w in title:
            return 'keep'
    d = dept_of(title)
    for nd in NEG_DEPTS:
        if nd in d:
            return 'drop'
    for w in WHITELIST_WEAK:
        if w in title:
            return 'keep'
    for pd in POS_DEPTS:
        if pd in d:
            return 'keep'
    return 'ml'


# 6) 本地机器学习兜底层（零 API 成本）。
# 关键词白名单追不上通知措辞的变化（如"网上缴费""信号屏蔽""直饮水暂停"这类
# 不含任何关键词的标题），参考 GitHub 上校园通知机器人（CampusPing 等）用
# ML 判定相关性的思路，改为本地实现：字符 1/2/3-gram 多项式朴素贝叶斯。
# 训练集 campus_notice_labels.json：253 条人工标注（09-02f 起并入规则不命中的
# 决策边界样本，覆盖体育文化节/施工通行/风险提醒等 keep 与合同系统/因公出访等 drop，
# 解决训练分布与部署分布错位）。每次运行内存内训练一次（毫秒级），零外部依赖。
# 超参数 (1,2,3)-gram / alpha=0.5 / theta=2.5（09-02f 定标，tune_nb.py + ablate_alpha.py）：
# 1) (2,3)→(1,2,3) 是 CV 稳定增益（macroF1 0.8390→0.8455±0.013，keepR 0.876→0.889）；
# 2) α∈{0.1,0.3,0.5} 在 29 条金标准残余项上均 0 误判、残余判定一致，故取最大 α=0.5
#    以平滑罕见字共现、降低对"组织参加X培训/会议调整"类近重复行政措辞的过拟合；
# 3) θ=2.5 维持"NB 救援须有把握"的语义。
NOTICE_LABELS_FILE = Path(__file__).resolve().with_name('campus_notice_labels.json')

import math as _math

# NB 超参数（交叉验证定标，勿随意改）
NB_GRAM_WIDTHS = (1, 2, 3)
NB_ALPHA = 0.5
NB_THRESHOLD = 2.5

_NB_CACHE = None


def _char_grams(text):
    t = re.sub(r'\s+', '', text)
    grams = []
    for n in NB_GRAM_WIDTHS:
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
    """Local NB verdict for rule-missed titles (only 'ml' residual reaches here).
    Returns (keep 0/1, log-odds margin). Multinomial NB, add-alpha smoothing,
    presence-set char grams; keep iff margin > NB_THRESHOLD (CV-tuned).
    Empty model (labels file missing) → (0, 0.0), i.e. fall back to rule-only."""
    counts, meta = _train_nb()
    if not meta['ndocs'][0] or not meta['ndocs'][1]:
        return 0, 0.0
    n = meta['ndocs'][0] + meta['ndocs'][1]
    scores = {}
    for c in (0, 1):
        lp = _math.log(meta['ndocs'][c] / n)
        denom = meta['totals'][c] + NB_ALPHA * meta['V']
        for g in set(_char_grams(title)):
            lp += _math.log((counts[c].get(g, 0) + NB_ALPHA) / denom)
        scores[c] = lp
    margin = scores[1] - scores[0]
    return (1 if margin > NB_THRESHOLD else 0), margin

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
        # 09-02c: 分层过滤（黑名单 → 强白名单 → 部门否决 → 弱白名单 → 服务部门 → NB 兜底）
        kept = []
        for d, t, u in notices:
            verdict = classify(t)
            if verdict == 'keep':
                kept.append((d, t, u))
            elif verdict == 'ml':
                pred, margin = ml_is_student(t)
                if pred:
                    kept.append((d, t, u))
                    print(f'[campus_daily] NB rescue (logodds={margin:.1f}): {t[:45]}', file=sys.stderr)
                else:
                    print(f'[campus_daily] filter drop (NB, logodds={margin:.1f}): {t[:45]}', file=sys.stderr)
            else:
                print(f'[campus_daily] filter drop (rule): {t[:45]}', file=sys.stderr)
        notices = kept
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
