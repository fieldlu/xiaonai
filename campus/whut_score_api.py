#!/usr/bin/env python3
"""WHUT official score API query tool.
Queries zs.whut.edu.cn directly for admission score data.
Usage:
  python3 campus/whut_score_api.py list                        # List provinces
  python3 campus/whut_score_api.py <province> [year] [category] [major] [--score N]
  python3 campus/whut_score_api.py 湖北                          # All data for 湖北
  python3 campus/whut_score_api.py 湖北 2024                     # 湖北 2024
  python3 campus/whut_score_api.py 湖北 2024 物理类                # 湖北 2024 物理类
  python3 campus/whut_score_api.py 湖北 2024 物理类 计算机          # Filter by major keyword
  python3 campus/whut_score_api.py 湖北 --score 620              # 湖北 620分能报的专业
  python3 campus/whut_score_api.py verify all                   # Cross-check all files
  python3 campus/whut_score_api.py verify 湖北 湖南               # Check specific provinces
"""
import json, sys, os
from urllib.request import Request, urlopen
from urllib.parse import urlencode

BASE = 'https://zs.whut.edu.cn/enroll-info/recruitByMajor'
KB = '/opt/xiaonai/data/knowledge'

ALL_PROVS = ['安徽','北京','重庆','福建','广东','广西','贵州','甘肃',
             '湖北','湖南','河北','河南','黑龙江','海南','江苏','江西',
             '吉林','辽宁','宁夏','内蒙古','青海','上海','四川','山东',
             '山西','陕西','天津','新疆','西藏','云南','浙江']

def api_post(endpoint, data):
    req = Request(f'{BASE}/{endpoint}', data=urlencode(data).encode(), method='POST')
    return json.loads(urlopen(req, timeout=30).read())

def get_years(province):
    return api_post('selYearbyProvince.do', {'province': province})['data']

def get_subject_types(province, year):
    return api_post('selSubjectTypeByProvinceAndYear.do', {'province': province, 'year': year})['data']

def get_scores(province, year, subject_type):
    return api_post('selRecruitByProvinceAndYearAndSubjectType.do',
                    {'province': province, 'year': year, 'subjectType': subject_type})

def query(province, year=None, subject_type=None, major_keyword=None, score=None):
    years = get_years(province) if year is None else [year]
    for y in years:
        types = get_subject_types(province, y) if subject_type is None else [subject_type]
        for st in types:
            if st == '全部':
                continue
            data = get_scores(province, y, st)
            stats = data['ext'].get('recruitStatisticsList', [])
            majors = data['ext'].get('recruitByMajorList', [])
            if major_keyword:
                majors = [m for m in majors if major_keyword in m.get('majorType', '')]
            if score is not None:
                majors = [m for m in majors if m.get('zdf') and m['zdf'] != '--'
                         and float(m['zdf']) <= score]
                majors.sort(key=lambda m: float(m['zdf']), reverse=True)
            yield {'year': y, 'subject_type': st, 'stats': stats, 'majors': majors}

def do_verify(provinces):
    if 'all' in provinces:
        provinces = ALL_PROVS
    results = []
    for p in provinces:
        fp = os.path.join(KB, f'YOUR_SCHOOL{p}录取分数.md')
        if not os.path.exists(fp):
            print(f'[MISS] {p}: FILE MISSING')
            results.append((p, False, 'MISSING'))
            continue
        try:
            years = get_years(p)
        except Exception as e:
            print(f'[ERR]  {p}: {e}')
            results.append((p, False, str(e)))
            continue
        with open(fp, encoding='utf-8') as f:
            content = f.read()
        issues = [y for y in years if str(y) not in content]
        if issues:
            print(f'[ISSUE]{p}: missing years {issues}')
            results.append((p, False, issues))
        else:
            print(f'[OK]   {p}')
            results.append((p, True, None))
    ok = sum(1 for _, o, _ in results if o)
    fail = sum(1 for _, o, _ in results if not o)
    print(f'\nSummary: {ok} OK, {fail} issues')
    return results

def cmd_query(args):
    if not args:
        print('Usage: whut_score_api.py <province> [year] [category] [major] [--score N]')
        return
    province = args[0]
    year = None
    subject_type = None
    major_keyword = None
    score = None
    i = 1
    while i < len(args):
        a = args[i]
        if a.startswith('--score'):
            score = float(a.split('=')[1] if '=' in a else args[i+1])
            if '=' not in a: i += 1
        elif a.isdigit() and len(a) == 4:
            year = int(a)
        elif a in ('历史类', '物理类', '艺术类', '文史', '理工', '全部'):
            subject_type = a
        else:
            major_keyword = a
        i += 1
    results = list(query(province, year, subject_type, major_keyword, score))
    if not results:
        print(f'[X] No data for: {" ".join(args)}')
        return
    for r in results:
        print(f'\n=== {r["year"]} {r["subject_type"]} ===')
        for s in r['stats']:
            print(f'  概况: {s.get("type","")} 线{s.get("skx","--")} '
                  f'最低{s.get("zdf","--")} 最高{s.get("zgf","--")} '
                  f'平均{s.get("pjf","--")} 位次{s.get("wcz","--")}')
        for m in r['majors']:
            tag = ''
            if score is not None and m.get('zdf') and m['zdf'] != '--':
                g = float(m['zdf']) - score
                tag = f' (差{g:.0f}分)' if g > 0 else ' SAFE'
            print(f'  {m["majorType"]}: 最低{m.get("zdf","--")} '
                  f'最高{m.get("zgf","--")} 位次{m.get("wcz","--")}{tag}')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == 'list':
        for p in ALL_PROVS:
            print(p)
    elif sys.argv[1] == 'verify':
        do_verify(sys.argv[2:]) if len(sys.argv) > 2 else do_verify(['all'])
    else:
        cmd_query(sys.argv[1:])
