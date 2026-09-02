#!/usr/bin/env python3
"""本地回归：验证修改后标注集分类 + 两条真实样例。"""
import json, sys
sys.path.insert(0, '.')
import campus_daily as c

def verdict(title):
    v = c.classify(title)
    if v == 'ml':
        pred, m = c.ml_is_student(title)
        return 'keep' if pred else 'drop', m
    return v, None

# 1. 全量标注集回归
d = json.load(open('campus_notice_labels.json', encoding='utf-8'))
tp = fp = tn = fn = 0
bad = []
for x in d['labels']:
    v, m = verdict(x['t'])
    keep = v == 'keep'
    if x['y'] == 1:
        if keep: tp += 1
        else:
            fn += 1
            bad.append(('FN', x['t'], v, m))
    else:
        if keep:
            fp += 1
            bad.append(('FP', x['t'], v, m))
        else:
            tn += 1
n = len(d['labels'])
print('标注集回归: n=%d TP=%d FP=%d TN=%d FN=%d acc=%.4f' % (
    n, tp, fp, tn, fn, (tp + tn) / n))
for kind, t, v, m in bad:
    print('  %s %s (verdict=%s margin=%s)' % (kind, t, v, m))

# 2. 真实样例复核
print('\n真实样例复核:')
cases = [
    ('【医管办】关于做好2027年度大学生医保参保缴费工作的通知', 1),
    ('关于举行树立和践行正确政绩观学习教育总结会的通知', 0),
]
for t, want in cases:
    v, m = verdict(t)
    ok = (v == 'keep') == (want == 1)
    print('  %s %s (want=%d, verdict=%s%s) %s' % (
        'OK' if ok else 'WRONG', t, want, v,
        ', margin=%.1f' % m if m is not None else '', ''))
