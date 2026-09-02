#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量金标准回归(09-02g 固化版): 用当前 campus_daily.py 的 classify() 重算
1032 条规则结论, 与金标准 gold_full.json 对比; 并跑端到端(规则+NB)。
改完规则后重跑本脚本验证: 期望规则层 FP=0、FN 全部落在 ML 层(交 NB)。
用法: python regress_full.py
"""
import sys, json, types, os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_bs = types.ModuleType('bs4')
class _S:
    def __init__(self, *a, **k): pass
_bs.BeautifulSoup = _S
sys.modules['bs4'] = _bs
_cs = types.ModuleType('campus_search')
_cs.session = None
_cs.encode_url = lambda u: u
_cs.decode_webvpn_url = lambda h: h
sys.modules['campus_search'] = _cs
import campus_daily as cd

BASE = os.path.dirname(os.path.abspath(__file__))
items = json.load(open(os.path.join(BASE, 'gztz_harvest.json'), encoding='utf-8'))['items']
goldfull = json.load(open(os.path.join(BASE, 'gold_full.json'), encoding='utf-8'))
gold = {int(k): v for k, v in goldfull['gold'].items()}
conf = goldfull['conf']
assert len(items) == 1032 and len(gold) == 1032


def layer_of(t):
    for w in cd.BLACKLIST:
        if w in t: return ('BLACK', w)
    for w in cd.WHITELIST_STRONG:
        if w in t: return ('STRONG', w)
    d = cd.dept_of(t)
    for nd in cd.NEG_DEPTS:
        if nd in d: return ('NEGDEPT', nd)
    for w in cd.WHITELIST_WEAK:
        if w in t: return ('WEAK', w)
    for pd in cd.POS_DEPTS:
        if pd in d: return ('POSDEPT', pd)
    return ('ML', '')


def rule_cm():
    cm = Counter(); fp = []; fn = []
    for idx, it in enumerate(items):
        t = it['t']; gl = gold[idx]
        v = cd.classify(t)
        rl = 1 if v == 'keep' else 0
        key = (rl, gl); cm[key] += 1
        if key == (1, 0): fp.append((idx, t, layer_of(t)))
        elif key == (0, 1): fn.append((idx, t, layer_of(t)))
    return cm, fp, fn


def e2e_cm():
    cm = Counter(); fp = []; fn = []
    for idx, it in enumerate(items):
        t = it['t']; gl = gold[idx]
        v = cd.classify(t)
        if v == 'keep': pred = 1
        elif v == 'drop': pred = 0
        else: pred, _ = cd.ml_is_student(t)
        key = (pred, gl); cm[key] += 1
        if key == (1, 0): fp.append((idx, t))
        elif key == (0, 1): fn.append((idx, t))
    return cm, fp, fn


def report(tag, cm, fp, fn):
    TP = cm[(1, 1)]; FPn = cm[(1, 0)]; TN = cm[(0, 0)]; FN = cm[(0, 1)]
    print('=== %s vs 金标准(1032) ===' % tag)
    print('TP=%d FP=%d FN=%d TN=%d  acc=%.3f  keep_rate=%.3f' %
          (TP, FPn, FN, TN, (TP + TN) / 1032, (TP + FPn) / 1032))
    if fp or fn:
        try:
            print('FP by layer:', Counter(x[2][0] for x in fp))
            print('FN by layer:', Counter(x[2][0] for x in fn))
        except IndexError:
            pass
        for x in fn[:40]: print('  FN %4d %s' % (x[0], x[1][:60]))
        for x in fp[:40]: print('  FP %4d %s' % (x[0], x[1][:60]))
    print()


report('规则层即时回归', *rule_cm())
report('端到端(规则+NB)', *e2e_cm())
