#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-02f NB 超参数调优：在 251 条标注上做分层 5 折 CV，
搜 (alpha 平滑, theta 阈值, gram 宽度) 组合，输出宏 F1/acc/keep-P/R 排序。
纯 stdlib，本地可跑；与 campus_daily.ml_is_student 同一公式。
"""
import json, math, re, random
from collections import Counter

random.seed(42)

def grams(text, widths=(2, 3)):
    t = re.sub(r'\s+', '', text)
    out = []
    for n in widths:
        if len(t) >= n:
            out += [t[i:i + n] for i in range(len(t) - n + 1)]
    return set(out)  # presence

def nb_margin(title, counts, ndocs, totals, V, alpha, widths):
    n = sum(ndocs.values())
    s = {}
    for c in (0, 1):
        lp = math.log(ndocs[c] / n)
        denom = totals[c] + alpha * V
        for g in grams(title, widths):
            lp += math.log((counts[c].get(g, 0) + alpha) / denom)
        s[c] = lp
    return s[1] - s[0]

def evaluate(labels, alpha, theta, widths, seed=42, folds=5):
    """Stratified k-fold CV. Return (acc, macroF1, keepP, keepR, n)."""
    pos = [x for x in labels if x['y'] == 1]
    neg = [x for x in labels if x['y'] == 0]
    rnd = random.Random(seed)
    rnd.shuffle(pos); rnd.shuffle(neg)
    pfolds = [pos[i::folds] for i in range(folds)]
    nfolds = [neg[i::folds] for i in range(folds)]
    tp = fp = tn = fn = 0
    for k in range(folds):
        tr = [x for i in range(folds) if i != k for x in pfolds[i] + nfolds[i]]
        te = pfolds[k] + nfolds[k]
        counts = {0: {}, 1: {}}
        ndocs = {0: 0, 1: 0}
        totals = {0: 0, 1: 0}
        vocab = set()
        for x in tr:
            y = x['y']
            ndocs[y] += 1
            for g in grams(x['t'], widths):
                counts[y][g] = counts[y].get(g, 0) + 1
                totals[y] += 1
                vocab.add(g)
        V = max(len(vocab), 1)
        for x in te:
            m = nb_margin(x['t'], counts, ndocs, totals, V, alpha, widths)
            pred = 1 if m > theta else 0
            if x['y'] == 1:
                if pred: tp += 1
                else: fn += 1
            else:
                if pred: fp += 1
                else: tn += 1
    acc = (tp + tn) / len(labels)
    keepP = tp / (tp + fp) if tp + fp else 0.0
    keepR = tp / (tp + fn) if tp + fn else 0.0
    dropP = tn / (tn + fn) if tn + fn else 0.0
    dropR = tn / (tn + fp) if tn + fp else 0.0
    macroF1 = 2 * (keepP * keepR) / (keepP + keepR) if keepP + keepR else 0.0
    return acc, macroF1, keepP, keepR, dropP, dropR

L = json.load(open('campus_notice_labels.json', encoding='utf-8'))
labels = L['labels']
print('labels n=%d (pos=%d neg=%d)' % (L['n'], L['n_pos'], L['n'] - L['n_pos']))

results = []
for widths in [(2, 3), (2, 3, 4), (1, 2, 3)]:
    for alpha in (0.1, 0.3, 0.5, 1.0, 2.0, 3.0):
        for theta in (-1, 0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0):
            acc, mf1, kp, kr, dp, dr = evaluate(labels, alpha, theta, widths)
            results.append((mf1, acc, kp, kr, dp, dr, widths, alpha, theta))

# 当前生产配置对照
base = [r for r in results if r[6] == (2, 3) and r[7] == 1.0 and r[8] == 2.5][0]
print('\n当前生产配置 (grams=(2,3), alpha=1.0, theta=2.5):')
print('  macroF1=%.4f acc=%.4f keepP=%.3f keepR=%.3f dropP=%.3f dropR=%.3f' % base[:6])

results.sort(key=lambda r: (-r[0], -r[1]))
print('\nTop 12 配置 (按 macroF1, acc):')
for mf1, acc, kp, kr, dp, dr, w, a, th in results[:12]:
    print('  F1=%.4f acc=%.4f keepP=%.3f keepR=%.3f dropR=%.3f | grams=%s alpha=%.1f theta=%+.1f'
          % (mf1, acc, kp, kr, dr, w, a, th))

print('\n阈值敏感性 (grams=(2,3), alpha=1.0):')
for th in (-1, 0, 1, 1.5, 2, 2.5, 3, 4, 5, 6):
    r = [x for x in results if x[6] == (2, 3) and x[7] == 1.0 and x[8] == th][0]
    print('  theta=%+.1f  F1=%.4f acc=%.4f keepP=%.3f keepR=%.3f dropR=%.3f' % (th, r[0], r[1], r[2], r[3], r[5]))
