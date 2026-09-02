#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-02f: 修正训练集误标。
基建处/余区管委会/保卫处的道路封闭、占道、打围、交通管制类通知直接关系学生
通行（=生活服务），此前在批量标注时被误标为 y=0，导致规则层与 NB 都学成"丢弃"。
本次把这类样本翻转为 y=1（保持规则层"强白救援词先于部门否决"语义一致）。
"""
import json, re, sys

p = 'campus_notice_labels.json'
L = json.load(open(p, encoding='utf-8'))
lab = L['labels']

RESCUE = ('临时封闭', '占道', '打围', '交通管制', '道路维修', '临时管控', '通行管制')
FLIP_DEPS = ('基建处', '余区管委会', '保卫处')

n_flip = 0
for x in lab:
    if x['y'] != 0:
        continue
    m = re.match(r'^【([^】]{1,12})】', x['t'])
    d = m.group(1) if m else ''
    if d in FLIP_DEPS and any(w in x['t'] for w in RESCUE):
        x['y'] = 1
        n_flip += 1
        print('FLIP->1', d, '|', x['t'])

L['n_pos'] = sum(x['y'] for x in lab)
L['n'] = len(lab)
json.dump(L, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('flipped=%d  n=%d  n_pos=%d' % (n_flip, L['n'], L['n_pos']))
