#!/usr/bin/env python3
"""WHUT enrollment plan query tool.
Queries zs.whut.edu.cn for per-major enrollment plans (招生计划).
Usage:
  python3 campus/whut_plan_api.py 广西 2025 物理类
  python3 campus/whut_plan_api.py 湖北 2025 物理类
"""
import sys, urllib.request, urllib.parse, json

BASE = 'https://zs.whut.edu.cn/enroll-info/recruitScheme'
CACHE = {}
CACHE_TTL = {}

def api(endpoint, data):
    key = endpoint + str(sorted(data.items()))
    now = __import__('time').time()
    if key in CACHE_TTL and now - CACHE_TTL[key] < 120:
        return CACHE[key]
    req = urllib.request.Request(BASE + '/' + endpoint, data=urllib.parse.urlencode(data).encode(), method='POST')
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    CACHE[key] = resp
    CACHE_TTL[key] = now
    return resp

def query(province, year, subject_type):
    """Get enrollment plan for a province+year+subject."""
    types = api('selTypeByProvinceAndYearAndSubjectType.do', {'province': province, 'year': year, 'subjectType': subject_type})['data']
    result = []
    for t in types:
        data = api('selRecruitByProvinceAndYearAndSubjectType.do', {'province': province, 'year': year, 'subjectType': subject_type, 'type': t})
        plans = data['ext'].get('recruitSchemeList', [])
        for p in plans:
            result.append({
                'type': t,
                'major': p['majorType'],
                'count': p['recruitNum'],
                'subject': p.get('electiveSubject', '--'),
                'remarks': p.get('remarks', '--')
            })
    return result

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) < 3:
        print('Usage: whut_plan_api.py <province> <year> <subject_type>'); sys.exit(1)
    province, year, subject_type = args[0], int(args[1]), args[2]
    try:
        plans = query(province, year, subject_type)
        if not plans:
            print('[X] No plan data for: ' + province + ' ' + str(year) + ' ' + subject_type)
            sys.exit(0)
        for p in plans:
            print(p['major'] + ' | ' + str(p['count']) + '人 | ' + p['subject'] + ' | ' + p['type'])
    except urllib.error.HTTPError as e:
        print('[X] API error: ' + str(e.code))
    except urllib.error.URLError:
        print('[X] Cannot reach zs.whut.edu.cn')
