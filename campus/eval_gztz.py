#!/usr/bin/env python3
"""对 gztz 全量 1032 条跑当前管线，输出判定明细供人工审查。"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_real_out = sys.stdout
sys.stdout = open(os.devnull, 'w')
import campus_search
sys.stdout.close()
sys.stdout = _real_out
import campus_daily as c

data = json.load(open('/tmp/gztz_all.json', encoding='utf-8'))
items = data['items']
print('total:', len(items), flush=True)

def verdict(title):
    v = c.classify(title)
    if v == 'ml':
        pred, m = c.ml_is_student(title)
        return 'keep' if pred else 'drop', m
    return v, None

out = []
nkeep = ndrop = 0
for it in items:
    v, m = verdict(it['t'])
    if v == 'keep':
        nkeep += 1
    else:
        ndrop += 1
    out.append({'d': it['d'], 't': it['t'], 'u': it['u'], 'v': v, 'm': m})

print('keep=%d drop=%d keep_rate=%.1f%%' % (nkeep, ndrop, 100.0 * nkeep / len(items)), flush=True)
with open('/tmp/gztz_verdict.json', 'w', encoding='utf-8') as f:
    json.dump({'n': len(out), 'nkeep': nkeep, 'items': out}, f, ensure_ascii=False, indent=0)
print('saved /tmp/gztz_verdict.json', flush=True)
