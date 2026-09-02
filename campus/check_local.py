#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-02f 本地规则层自检（不含 NB，ml 留给服务器回归确认）。"""
import json, re

src = open('campus_daily.py', encoding='utf-8').read()
i = src.index('BLACKLIST = (')
j = src.index('# 6) 本地机器学习兜底层')
seg = src[i:j]
ns = {'re': re}
exec(seg, ns)
classify = ns['classify']

L = json.load(open('campus_notice_labels.json', encoding='utf-8'))
lab = L['labels']

bad_keep = []   # y=0 被判 keep（规则层 FP）
bad_rule = []   # y=1 被规则层直接 drop（ml 属正常：交 NB 兜底）
for x in lab:
    v = classify(x['t'])
    if x['y'] == 0 and v == 'keep':
        bad_keep.append(x['t'])
    if x['y'] == 1 and v == 'drop':
        bad_rule.append((v, x['t']))

print('y0 规则层误放行(keep):', len(bad_keep))
for t in bad_keep[:10]:
    print('   FP!', t)
print('y1 规则层误杀(drop):', len(bad_rule))
for v, t in bad_rule[:10]:
    print('   ', v, t)
ml_keeps = sum(1 for x in lab if x['y'] == 1 and classify(x['t']) == 'ml')
print('y1 依赖 NB 兜底(ml) 的样本数:', ml_keeps, '(预期 14，边界样本本就规则不命中)')
print('OK' if not bad_keep and not bad_rule else 'NEED_FIX')
