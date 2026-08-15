#!/usr/bin/env python3
"""Rebuild all KB indexes: index.json + chunked semantic (npz+pkl) + BM25 (jieba)."""
import json, re, sys, os
from pathlib import Path

KB = Path('/opt/xiaonai/data/knowledge')

# 1. index.json
topics = {}
for f in sorted(KB.glob('*.md')):
    if f.name == 'index.json':
        continue
    raw = f.read_bytes()
    content = raw.decode('utf-8', errors='replace')
    title = ''
    for line in content[:500].split('\n'):
        if line.startswith('# '):
            title = line[2:].strip()
            break
    if not title:
        title = f.stem
    kw = set(re.findall(r'[\w一-鿿]{2,}', title))
    kw |= set(re.findall(r'[\w一-鿿]{3,}', content[:300]))
    topics[f.name] = {'title': title, 'keywords': sorted(kw)[:30], 'size': len(content)}
data = json.dumps({'topics': topics}, ensure_ascii=False, indent=2)
KB.joinpath('index.json').write_bytes(data.encode('utf-8', errors='replace'))
print('1. index.json: %d files' % len(topics))

# 2. chunked semantic (kb_semantic format, npz+pkl consistent)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_semantic
kb_semantic.build_index()

# 3. BM25 (jieba)
import kb_manage
kb_manage._bm25_build()
print('3. bm25 done')
print('OK')
