#!/usr/bin/env python3
"""分层抽样 120 条（keep60/drop60）供人工标注，输出编号清单。"""
import json, random
random.seed(42)
v = json.load(open('gztz_verdict.json', encoding='utf-8'))
items = v['items']
kept = [x for x in items if x['v'] == 'keep']
dropped = [x for x in items if x['v'] != 'keep']

def pick(pool, n):
    # 按月份分散抽样
    by_m = {}
    for x in pool:
        by_m.setdefault(x['d'][:7], []).append(x)
    months = sorted(by_m)
    picked = []
    idx = 0
    while len(picked) < n and idx < len(months) * 5:
        for m in months:
            if by_m[m] and len(picked) < n:
                picked.append(by_m[m].pop(random.randrange(len(by_m[m]))))
        idx += 1
    picked += random.sample([x for x in pool if x not in picked], max(0, n - len(picked)))
    return picked[:n]

keep_s = pick(kept, 60)
drop_s = pick(dropped, 60)
print('KEEP 抽样 %d 条:' % len(keep_s))
for i, x in enumerate(keep_s, 1):
    print('K%03d|%s|%s' % (i, x['d'], x['t'][:70]))
print()
print('DROP 抽样 %d 条:' % len(drop_s))
for i, x in enumerate(drop_s, 1):
    print('D%03d|%s|%s' % (i, x['d'], x['t'][:70]))
