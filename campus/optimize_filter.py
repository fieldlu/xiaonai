#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园通知过滤器 评估/训练 harness（纯 Python，零依赖，零 API）。

在 209 条人工标注集上评估过滤管线，目标：
  1) 整体准确率 >= 95%；
  2) 比赛 / 生活服务 / 课程 / 学生 四类零遗漏（FN=0）。
"""
import json, re, math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / 'campus_notice_labels.json').read_text(encoding='utf-8'))['labels']
N = len(DATA)
N_POS = sum(1 for x in DATA if x['y'] == 1)

DEPT_RE = re.compile(r'^【([^】]{1,12})】')

def dept_of(t):
    m = DEPT_RE.match(t)
    return m.group(1) if m else ''


# ============================================================
# v2 规则管线（数据驱动，逐词对照 209 条标注核验）
# ============================================================
# 硬黑名单（教师/职工/行政噪音，正例中不出现）
BLACKLIST = (
    "工勤", "技师", "教职工", "青年教师", "教师岗", "师资", "博士后",
    "导师", "指导教师", "教材", "教研", "微课", "教学设计", "教学竞赛",
    "教学类人才", "智慧课程", "先进工作者", "先进集体", "校企",
    "科研成果", "教育教学改革", "教改", "工程案例", "辅导员", "岗前培训",
    "行业育人", "正版化", "周转房", "一号门", "三伏贴", "规章制度",
    "防汛", "政府采购", "消防", "实验室安全", "值班表", "采购", "招投标",
    "任前公示", "拟聘用", "拟立项", "出国研修", "成果转化", "留学生",
    "公积金", "住房", "技能人才", "干部", "党员", "党支部", "中心组",
    "津贴", "揭榜挂帅", "成果文库", "优质新刊", "学术著作",
    "专业公示", "专业设置", "专业调整", "职称",
)

# 强白名单（无歧义的学生/竞赛/生活词，先于部门否决，覆盖"博士生专项"等行政部门的例外）
WHITELIST_STRONG = (
    # 比赛
    "竞赛", "大赛", "比赛", "挑战赛", "挑战杯", "校赛", "创意赛",
    "创新创业", "创新大赛", "创业计划", "选拔赛", "选拔",
    # 生活服务
    "停电", "停水", "停气", "断网", "网络中断", "校园网", "供电", "供水",
    "直饮水", "热水", "班车", "食堂", "超市", "水电", "收费", "收发",
    "水池", "水箱", "清洗", "图书馆", "医院", "校园卡", "医保", "缴费",
    "信号屏蔽", "邮箱", "VPN", "云平台", "快递", "门禁", "空调",
    # 课程 / 学业
    "选课", "补考", "缓考", "重修", "成绩", "考试", "自习",
    "体测", "体质健康", "缓测", "四六级", "普通话", "免试攻读", "推免",
    "保研", "考研", "答辩", "学位", "毕业", "报到", "注册", "开学",
    "放假", "校历", "本科",
    # 学生 / 综合
    "学生", "本科生", "研究生", "博士生", "助学金", "奖学金", "贷款",
    "勤工", "社团", "志愿者", "支教", "讲座", "实习", "实践", "评优",
    "表彰", "招聘会", "宣讲会", "就业", "心理", "国际合作",
)

# 弱白名单（宽泛词，后于部门否决——"暑假/网络/课程"在行政/科研部门通知里是噪音）
WHITELIST_WEAK = ("暑假", "寒假", "暑期", "网络", "课程")

# 纯行政/科研部门（硬否决，但白名单已先行放行"博士生专项"等学生项）
NEG_DEPTS = (
    "人文社科处", "人力资源部", "基建处", "工会", "科技转化中心",
    "实验设备处", "测试中心", "组织部", "保卫处", "社会合作处",
    "党委教师工作部", "襄阳示范区", "机关直属单位党委", "留学生管理服务中心",
    "科发院", "三亚科教园", "宣传部",
)

# 服务/学生部门（默认放行，黑名单先行剔除 工勤/正版化/先进集体/三伏贴/周转房）
POS_DEPTS = (
    "网络中心", "后管处", "图书馆", "后勤集团", "医院", "医管办",
    "财务处", "体育学院", "团委",
)


def decide_v2(title, residual='drop'):
    """v2 规则管线。residual: 'drop' | 'nb' | 'keep'（未命中规则的标题如何处理）。"""
    # 1. 硬黑名单（教师/职工/行政噪音）
    for w in BLACKLIST:
        if w in title:
            return False, f'blk:{w}'
    # 2. 强白名单（先于部门否决，覆盖"博士生专项"等行政部门的例外）
    for w in WHITELIST_STRONG:
        if w in title:
            return True, f'wlS:{w}'
    # 3. 部门硬否决（纯行政/科研部门）
    d = dept_of(title)
    for nd in NEG_DEPTS:
        if nd in d:
            return False, f'dept-:{nd}'
    # 4. 弱白名单（宽泛词，行政部门已否决后再放行）
    for w in WHITELIST_WEAK:
        if w in title:
            return True, f'wlW:{w}'
    # 5. 服务/学生部门默认放行
    for pd in POS_DEPTS:
        if pd in d:
            return True, f'dept+:{pd}'
    # 6. 残余
    if residual == 'drop':
        return False, 'resid-drop'
    if residual == 'keep':
        return True, 'resid-keep'
    return None  # nb 由外部处理


def evaluate(decide, tag, verbose=True):
    tp = fn = fp = tn = 0
    fns, fps, resid_pos = [], [], []
    for x in DATA:
        pred, why = decide(x['t'])
        if pred is None:  # residual，交给 NB
            pred, why = nb_decide(x['t'])
        if x['y'] == 1 and pred:
            tp += 1
        elif x['y'] == 1 and not pred:
            fn += 1; fns.append((x['t'], why))
        elif x['y'] == 0 and pred:
            fp += 1; fps.append((x['t'], why))
        else:
            tn += 1
        if pred is None:
            pass
    acc = (tp + tn) / N
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    print(f'[{tag}] acc={acc:.4f} ({tp+tn}/{N})  prec={prec:.4f}  rec={rec:.4f}  f1={f1:.4f}  | TP={tp} FN={fn} FP={fp} TN={tn}')
    if verbose and fns:
        print(f'  --- FN 漏判 ({len(fns)}) ---')
        for t, w in fns:
            print(f'    [{w}] {t[:50]}')
    if verbose and fps:
        print(f'  --- FP 误判 ({len(fps)}) ---')
        for t, w in fps:
            print(f'    [{w}] {t[:50]}')
    return dict(acc=acc, prec=prec, rec=rec, f1=f1, fn=fns, fp=fps)


# ============================================================
# NB 兜底（现有实现，仅用于残余标题）
# ============================================================
def _char_grams(text):
    t = re.sub(r'\s+', '', text)
    out = []
    for n in (2, 3):
        if len(t) >= n:
            out += [t[i:i + n] for i in range(len(t) - n + 1)]
    return out


def _train_nb():
    counts = {0: {}, 1: {}}
    ndocs = {0: 0, 1: 0}
    totals = {0: 0, 1: 0}
    vocab = set()
    for x in DATA:
        y = int(x['y'])
        ndocs[y] += 1
        for g in set(_char_grams(x['t'])):
            counts[y][g] = counts[y].get(g, 0) + 1
            totals[y] += 1
            vocab.add(g)
    return counts, {'ndocs': ndocs, 'totals': totals, 'V': max(len(vocab), 1)}


_NB = _train_nb()


def nb_decide(title):
    counts, meta = _NB
    n = meta['ndocs'][0] + meta['ndocs'][1]
    s = {}
    for c in (0, 1):
        lp = math.log(meta['ndocs'][c] / n)
        denom = meta['totals'][c] + meta['V']
        for g in set(_char_grams(title)):
            lp += math.log((counts[c].get(g, 0) + 1) / denom)
        s[c] = lp
    margin = s[1] - s[0]
    return (margin > 2.5), f'nb({margin:.1f})'


if __name__ == '__main__':
    print(f'标注集: {N} 条, 正例 {N_POS} 条\n')
    print('=== v2 规则管线（残余=丢弃）===')
    evaluate(lambda t: decide_v2(t, 'drop'), 'v2-rules')
    print()
    print('=== v2 规则管线 + NB 兜底（残余=NB）===')
    def v2_nb(t):
        p, w = decide_v2(t, 'nb')
        if p is None:
            p, w = nb_decide(t)
        return p, w
    evaluate(v2_nb, 'v2+nb')
