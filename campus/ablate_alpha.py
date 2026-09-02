#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-02f 部署导向验证：本地复刻 规则层+N B 全管线，在 1032 集残余(ml)项上
比较 alpha∈{0.1,0.3,0.5} 的误判（以 27+2 条人工边界标注为准）。
"""
import json, re, math

# 1) 规则层：从 campus_daily.py 抽出常量与 classify
src = open('campus_daily.py', encoding='utf-8').read()
i = src.index('BLACKLIST = (')
j = src.index('# 6) 本地机器学习兜底层')
ns = {'re': re}
exec(src[i:j], ns)
classify = ns['classify']

# 2) NB：tune_nb 同款实现
from tune_nb import grams, nb_margin

L = json.load(open('campus_notice_labels.json', encoding='utf-8'))
lab = L['labels']
counts = {0: {}, 1: {}}
ndocs = {0: 0, 1: 0}
totals = {0: 0, 1: 0}
vocab = set()
for x in lab:
    y = x['y']
    ndocs[y] += 1
    for g in grams(x['t'], (1, 2, 3)):
        counts[y][g] = counts[y].get(g, 0) + 1
        totals[y] += 1
        vocab.add(g)
V = max(len(vocab), 1)

data = json.load(open('gztz_harvest.json', encoding='utf-8'))
items = data['items']


def full_verdict(title, alpha, theta=2.5):
    v = classify(title)
    if v != 'ml':
        return v, None
    m = nb_margin(title, counts, ndocs, totals, V, alpha, (1, 2, 3))
    return ('keep' if m > theta else 'drop'), m


# 人工判定的金标准（仅对我复核过的 ml 残余项；其余 None=不评估）
gold = {
    '【余区管委会】关于余家头校区部分污水管道改造的通知': 1,
    '【体育运动委员会】关于举行武汉理工大学第六届体育文化节开幕式暨第四届理工健康': 1,
    '【余区管委会】关于开通“余家头校区监控视频调阅申请”服务的通知': 1,
    '关于南湖北院邻泓悦府小区道路交通温馨提示': 1,
    '【余区管委会】“光影‘余’韵・理工风华”校园摄影征集活动获奖名单公示': 1,
    '【余区管委会】关于举办“光影‘余’韵·理工风华”摄影作品征集活动的通知': 1,
    '以雪为令齐发力 同心护校筑平安 —— 致全校师生员工的扫雪除冰倡议书': 1,
    '“卓越之光”第四届理工故事展演会座位图': 1,
    '【素质教育中心】关于举办中华传统文化艺术体验活动周的通知': 1,
    '关于学校网站全新改版上线运行通知': 1,
    '【风险提醒】关于我校师生账号信息泄露的风险提醒': 1,
    '【国际处】关于举办2026年夏季“平安留学”行前培训会通知': 1,
    '【党政办公室】本周校领导接待日安排': 1,
    '关于组织参加《大国工业》公开课的通知': 1,
    '【学工部】关于2026年学校科研财务助理岗位招聘工作的通知': 1,
    '【党政办】“合同管理系统”电子签章功能上线通知': 0,
    '【港澳台办】关于办理因公赴港澳通行证的紧急通知': 0,
    '关于推进落实“湖北省推动内河船舶产业转型升级和高质量发展工作方案”的通知': 0,
    '关于组织开展2026年保密宣传教育月活动的通知': 0,
    '关于开展2026年全民国家安全教育日系列活动的通知': 0,
    '关于做好2026年度“二上”预算编制相关工作的通知': 0,
    '关于分析总结2025年度工作、系统谋划2026年度工作、开展2025年度目标责任制考核工作': 0,
    '关于认真贯彻落实学校2026年工作布置会精神的通知': 0,
    '关于开展2027-2029年拟购置大型仪器设备规划论证工作的通知': 0,
    '【孔子学院】关于组织实施2026年度国家公派出国教师选派工作的通知': 0,
    '【保密办】关于开展涉密载体集中销毁工作的通知': 0,
    '【党政办】关于机构优化调整有关工作提醒': 0,
    '【党政办】关于开展2026年法治教育学习的通知': 0,
    '【审计处】关于组织参加审计政策宣贯及审计整改系统操作培训的通知': 0,
    '【党政办公室】会议调整通知': 0,
}

titles = [it['t'] for it in items]
uniq = sorted(set(titles))
# 保留 gold 中与 harvest 一致者
gold = {t: y for t, y in gold.items() if t in uniq or t + '...' in uniq}
# 处理 harvest 截断的标题（体育文化节/目标考核带 '...'）
tmap = {}
for t in uniq:
    tmap[t] = t
for t, y in list(gold.items()):
    if t not in tmap and t + '...' in tmap:
        gold[tmap[t + '...']] = gold.pop(t)

for alpha in (0.1, 0.3, 0.5):
    errs = []
    for t, y in gold.items():
        v, m = full_verdict(t, alpha)
        pred = 1 if v == 'keep' else 0
        if pred != y:
            errs.append((y, pred, round(m, 1), t))
    print('alpha=%.1f  金标准 %d 条残余项误判 %d 条:' % (alpha, len(gold), len(errs)))
    for y, p, m, t in errs:
        print('    want=%d got=%d m=%+.1f  %s' % (y, p, m, t[:45]))

# 全量残余统计
for alpha in (0.1, 0.3, 0.5):
    mlk = mld = 0
    for it in items:
        v, m = full_verdict(it['t'], alpha)
        if m is not None:
            if v == 'keep':
                mlk += 1
            else:
                mld += 1
    print('alpha=%.1f  NB残余: keep=%d drop=%d' % (alpha, mlk, mld))
