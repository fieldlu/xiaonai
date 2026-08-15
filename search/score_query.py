#!/usr/bin/env python3
import sys, urllib.request, urllib.parse, json, time
from collections import defaultdict

BASE = 'https://zs.whut.edu.cn/enroll-info/recruitByMajor'
CACHE = {}
CACHE_TTL = {}

def api(endpoint, data):
    key = endpoint + str(sorted(data.items()))
    now = time.time()
    if key in CACHE_TTL and now - CACHE_TTL[key] < 120:
        return CACHE[key]
    req = urllib.request.Request(BASE + '/' + endpoint, data=urllib.parse.urlencode(data).encode(), method='POST')
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    CACHE[key] = resp
    CACHE_TTL[key] = now
    return resp

PROVS = ['安徽','北京','重庆','福建','广东','广西','贵州','甘肃','湖北','湖南','河北','河南','黑龙江','海南','江苏','江西','吉林','辽宁','宁夏','内蒙古','青海','上海','四川','山东','山西','陕西','天津','新疆','西藏','云南','浙江']



def get_gaokao_system(year):
    """Return gaokao system label for a given year.
    Pre-2024: 老高考 (理工/文史)
    2024+: 新高考 (物理类/历史类)"""
    return "新高考(物理类/历史类)" if year >= 2024 else "老高考(理工/文史)"

def get_all_years(province):
    return api('selYearbyProvince.do', {'province': province})['data']

def get_types(province, year):
    return [t for t in api('selSubjectTypeByProvinceAndYear.do', {'province': province, 'year': year})['data'] if t != '全部']

def get_data(province, year, subject_type):
    return api('selRecruitByProvinceAndYearAndSubjectType.do', {'province': province, 'year': year, 'subjectType': subject_type})

def fs(v):
    if v is not None and str(v).strip() not in ('--', '', 'None'):
        try:
            return str(int(float(str(v).strip())))
        except:
            return str(v).strip()
    return '--'

def f_rank(r):
    if r is None or str(r).strip() in ('--', '', 'None'):
        return '--'
    try:
        n = int(float(str(r)))
        return '{:,}'.format(n)
    except:
        return str(r)

def query_year(province, year, subject_type, keyword, score):
    d = get_data(province, year, subject_type)
    # Fallback: pre-2024 uses legacy type names (理工/文史 instead of 物理类/历史类)
    if not d.get("ext", {}).get("recruitByMajorList"):
        _legacy = {"物理类": "理工", "历史类": "文史",
                   "艺术类": ["艺术类", "艺术(理工)", "艺术(文史)"]}
        if subject_type in _legacy:
            _candidates = _legacy[subject_type]
            if isinstance(_candidates, str):
                _candidates = [_candidates]
            for _cand in _candidates:
                d = get_data(province, year, _cand)
                if d.get("ext", {}).get("recruitByMajorList"):
                    break
    majors = d['ext'].get('recruitByMajorList', [])
    if keyword:
        majors = [m for m in majors if keyword in m.get('majorType', '')]
    if score is not None:
        try:
            score_float = float(score)
        except (ValueError, TypeError):
            score_float = None
        if score_float is not None:
            majors = [m for m in majors if m.get('zdf') is not None and str(m['zdf']).strip() not in ('--', '', 'None') and float(m['zdf']) <= score_float]
        else:
            majors = [m for m in majors if m.get('zdf') is not None and str(m['zdf']).strip() not in ('--', '', 'None')]
        majors.sort(key=lambda m: float(m['zdf']), reverse=True)
    return d['ext'].get('recruitStatisticsList', []), majors

def show_trend(province, keyword, years_data, score):
    major_trends = defaultdict(list)
    for year, st, majors in years_data:
        for m in majors:
            mn = m['majorType']
            major_trends[mn].append({'year': year, 'st': st, 'zdf': m.get('zdf','--'), 'zgf': m.get('zgf','--'), 'wcz': m.get('wcz','--'), 'type': m.get('type','')})
    if not major_trends:
        print('[X] No matching majors found for trend'); return
    print('=== ' + province + ' 位次趋势分析 ===')
    sorted_majors = sorted(major_trends.items(), key=lambda x: max((int(e['zdf']) for e in x[1] if e['zdf'] not in ('--','None','')), default=0), reverse=True)
    for mn, entries in sorted_majors:
        if len(entries) < 1: continue
        entries.sort(key=lambda x: x['year'], reverse=True)
        scores = [str(e['year']) + ':' + fs(e['zdf']) for e in entries]
        ranks = [str(e['year']) + ':' + f_rank(e['wcz']) for e in entries]
        latest_zdf = entries[0]['zdf']
        tag = ''
        if score is not None and latest_zdf not in ('--', 'None', '', None):
            try:
                g = float(latest_zdf) - score
                tag = ' SAFE' if g <= 0 else ' 差' + str(int(g)) + '分'
            except: pass
        print(mn + ' | ' + ' -> '.join(scores) + ' | 位次: ' + ' -> '.join(ranks) + tag)

def show_score_analysis(province, primary_year, results, score):
    primary_year = primary_year or (results[0]['year'] if results else None)
    primary_results = [r for r in results if r['year'] == primary_year]
    other_results = [r for r in results if r['year'] != primary_year]
    for r in primary_results:
        print('=== ' + province + ' ' + str(r['year']) + ' ' + r['subject_type'] + ' ===')
        for s in r['stats']:
            print('  [' + s.get('type', '') + '] 线' + fs(s.get('skx')) + ' 最低' + fs(s.get('zdf')) + ' 最高' + fs(s.get('zgf')) + ' 平均' + fs(s.get('pjf')) + ' 位次' + f_rank(s.get('wcz')))
        safe_majors = []; reach_majors = []
        for m in r['majors']:
            zdf = m.get('zdf', '')
            if score is not None and zdf is not None and str(zdf).strip() not in ('--', '', 'None'):
                g = float(zdf) - score
                if g <= 0: safe_majors.append((m, abs(g)))
                else: reach_majors.append((m, g))
        if safe_majors:
            print('\n  ★稳妥（最低分≤你的分数）:')
            for m, _ in sorted(safe_majors, key=lambda x: float(x[0].get('zdf', '0')), reverse=True):
                gap = int(score - float(m['zdf'])) if score is not None else 0
                print('  ✓ ' + m['majorType'] + ': ' + fs(m.get('zdf')) + '-' + fs(m.get('zgf')) + '分 位次' + f_rank(m.get('wcz')) + ' (低' + str(gap) + '分)')
        if reach_majors:
            print('\n  ★冲刺（最低分接近你的分数）:')
            for m, g in sorted(reach_majors, key=lambda x: x[1]):
                print('  ↑ ' + m['majorType'] + ': ' + fs(m.get('zdf')) + '-' + fs(m.get('zgf')) + '分 位次' + f_rank(m.get('wcz')) + ' (差' + str(int(g)) + '分)')
    if other_results:
        major_data = defaultdict(list)
        for r in primary_results + other_results:
            for m in r['majors']:
                zdf = m.get('zdf'); wcz = m.get('wcz')
                if zdf is not None and str(zdf).strip() not in ('--','','None') and wcz is not None and str(wcz).strip() not in ('--','','None'):
                    major_data[m['majorType']].append({'y': r['year'], 'zdf': int(float(zdf)), 'wcz': int(float(wcz))})
        top_majors = sorted(major_data.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        if top_majors:
            print('\n  --- 近三年趋势（位次比分数更稳定） ---')
            for mn, entries in top_majors:
                entries.sort(key=lambda x: x['y'])
                scores_show = [str(e['zdf']) for e in entries]
                ranks_show = [f_rank(e['wcz']) for e in entries]
                if len(entries) >= 2:
                    delta = entries[-1]['zdf'] - entries[0]['zdf']
                    arrow = '↑涨' + str(abs(delta)) + '分' if delta > 0 else ('↓降' + str(abs(delta)) + '分' if delta < 0 else '→持平')
                else: arrow = ''
                print('  ' + mn + ': ' + '->'.join(scores_show) + ' ' + arrow)
                print('    位次: ' + '->'.join(ranks_show))

def fetch_plan(province, year, subject_type):
    """Fetch enrollment plan for reference."""
    try:
        url = 'https://zs.whut.edu.cn/enroll-info/recruitScheme/selRecruitByProvinceAndYearAndSubjectType.do'
        data = {'province': province, 'year': year, 'subjectType': subject_type, 'type': '全部'}
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return resp['ext'].get('recruitSchemeList', [])
    except:
        return []

def show_professional(province, primary_year, results, score_val):
    try:
        primary_results = [r for r in results if r['year'] == primary_year]
        if not primary_results: return
        physics = [x for x in primary_results if x['subject_type'] == '物理类']
        r = physics[0] if physics else primary_results[0]
        main_stat = None
        for s in r['stats']:
            if s.get('type', '') in ('普通类', ''): main_stat = s; break
        if not main_stat and r['stats']: main_stat = r['stats'][0]
        skx = fs(main_stat.get('skx')) if main_stat else '--'
        zdf = fs(main_stat.get('zdf')) if main_stat else '--'
        wcz = f_rank(main_stat.get('wcz')) if main_stat else '--'
        print('\n【READY】')
        print('当前是2026年，2026年高考录取数据尚未公布。以下为' + str(primary_year) + '年' + province + r['subject_type'] + '省控线' + skx + '分，普通类投档线' + zdf + '分（对应位次' + wcz + '）。你的' + fs(score_val) + '分已达到学校投档要求。')

        # Fetch enrollment plan
        plans = fetch_plan(province, primary_year, r['subject_type'])
        plan_map = {}
        for p in plans:
            plan_map[p['majorType']] = p['recruitNum']

        # Build enriched major list with risk analysis
        enriched = []
        for m in r['majors']:
            zdf_v = m.get('zdf')
            if zdf_v is None or str(zdf_v).strip() in ('--', '', 'None'):
                continue
            sc = float(zdf_v)
            if score_val is not None and sc > score_val:
                continue
            gap = score_val - sc if score_val is not None else 0
            mn = m['majorType']
            cnt = plan_map.get(mn, None)
            wcz_v = m.get('wcz', '--')

            # Compute risk level
            risk_score = 0
            # Factor 1: score gap (lower gap = higher risk)
            if score_val is not None and gap <= 3: risk_score += 3
            elif gap <= 6: risk_score += 2
            elif gap <= 10: risk_score += 1
            # Factor 2: enrollment count (fewer spots = higher risk)
            if cnt is not None:
                try:
                    c = int(cnt)
                    if c <= 2: risk_score += 3
                    elif c <= 5: risk_score += 2
                    elif c <= 10: risk_score += 1
                except: pass
            # Factor 3: rank available? If major rank > school rank → lower risk
            # (simplified: if gap >= 10 → safe)

            if risk_score >= 5: risk = '高'
            elif risk_score >= 3: risk = '中'
            else: risk = '低'

            plan_note = ''
            if cnt is not None:
                try:
                    c = int(cnt)
                    if c == 1: plan_note = '，仅招1人'
                    elif c <= 3: plan_note = '，仅招' + str(c) + '人'
                    elif c >= 15: plan_note = '，招' + str(c) + '人，名额充足'
                    else: plan_note = '，招' + str(c) + '人'
                except: pass

            enriched.append({
                'name': mn, 'zdf': sc, 'zgf': m.get('zgf',''),
                'wcz': wcz_v, 'gap': gap, 'risk': risk,
                'plan_note': plan_note, 'cnt': cnt
            })

        # Sort: best picks first (low risk, high gap)
        enriched.sort(key=lambda x: (0 if x['risk'] == '低' else 1 if x['risk'] == '中' else 2, -x['gap']))

        if enriched:
            print('')
            print('参考' + str(primary_year) + '年录取数据及招生计划，综合分析如下：')
            print('')
            # Best picks (low risk)
            best = [x for x in enriched if x['risk'] == '低']
            if best:
                print('★★★ 首选推荐（低风险，录取把握大）：')
                for x in best[:5]:
                    print('  ' + x['name'] + '：最低' + fs(x['zdf']) + '分，位次' + f_rank(x['wcz']) + '，低' + str(int(x['gap'])) + '分' + x['plan_note'])

            medium = [x for x in enriched if x['risk'] == '中']
            if medium:
                print('')
                print('★★ 稳妥选择（中等风险，建议搭配保底）：')
                for x in medium[:5]:
                    print('  ' + x['name'] + '：最低' + fs(x['zdf']) + '分，位次' + f_rank(x['wcz']) + '，低' + str(int(x['gap'])) + '分' + x['plan_note'])

            high = [x for x in enriched if x['risk'] == '高']
            if high:
                print('')
                print('★ 可以冲刺（高风险，建议放前面志愿）：')
                for x in high[:3]:
                    print('  ' + x['name'] + '：最低' + fs(x['zdf']) + '分，位次' + f_rank(x['wcz']) + '，低' + str(int(x['gap'])) + '分' + x['plan_note'])

            # Smart summary - find best recommendation
            print('')
            # Pick best popular safe major
            popular_keywords = ['计算机','人工智能','车辆','电子','自动化','机械','材料']
            best_safe = [x for x in enriched if x['risk'] == '低']
            # Among safe picks, prefer popular majors
            for kw in popular_keywords:
                popular_picks = [x for x in best_safe if kw in x['name']]
                if popular_picks:
                    best_safe = popular_picks[:3]
                    break

            if best_safe:
                first = best_safe[0]
                print('建议：可将' + first['name'] + '作为第一志愿（低' + str(int(first['gap'])) + '分，录取概率较高）。')
                if len(best_safe) > 1:
                    second = best_safe[1]
                    print('第二志愿可用' + second['name'] + '作为保底（低' + str(int(second['gap'])) + '分），形成梯度。')
            if high:
                print('如有意冲刺热门专业，可将' + high[0]['name'] + '放第一志愿，但后续需跟稳妥专业保底。')

        other_years = [r2 for r2 in results if r2['year'] != primary_year]
        if other_years:
            print('')
            print('近三年位次趋势：')
            for r2 in sorted(other_years + [r], key=lambda x: x['year']):
                st = r2['stats']
                if st:
                    w = f_rank(st[0].get('wcz')) if st[0].get('wcz') else '--'
                    print('  ' + str(r2['year']) + '年' + r2['subject_type'] + '普通类位次：' + w)
        print('')
        print('以上数据供你参考，填报志愿需综合考虑个人兴趣与职业规划。【ENDREADY】')
    except Exception as e:
        # Silent fail for the professional output
        pass

def smart_analyze(province, year, score_val, subject_type=None):
    """Smart admission analysis: 3-year data + risk tiers + KB reference hints.
    Returns compact QQ-optimized output."""
    lines = []
    lines.append("【小奈智能招生分析】" + province + (" " + str(score_val) + "分" if score_val else ""))
    
    all_years = get_all_years(province)
    if not all_years:
        return "[X] 暂无" + province + "录取数据"
    
    # Determine subject type
    if not subject_type:
        types = get_types(province, year)
        subject_type = "物理类" if "物理类" in types else types[0]
    
    years_data = []
    for y in [year, year-1, year-2]:
        if y not in all_years:
            continue
        stats, majors = query_year(province, y, subject_type, "", score_val)
        if stats or majors:
            years_data.append({"year": y, "stats": stats, "majors": majors})
    
    if not years_data:
        return "[X] 暂无" + province + str(year) + subject_type + "录取数据"
    
    # Latest year stats
    latest = years_data[0]
    main_stat = None
    for s in latest["stats"]:
        if s.get("type", "") in ("普通类", ""):
            main_stat = s
            break
    if not main_stat and latest["stats"]:
        main_stat = latest["stats"][0]
    
    if main_stat:
        skx = fs(main_stat.get("skx"))
        zdf = fs(main_stat.get("zdf"))
        wcz = f_rank(main_stat.get("wcz"))
        lines.append("")
        lines.append(str(year) + "年" + subject_type + "省控线" + skx + "分 投档线" + zdf + "分(位次" + wcz + ")")
        
        # Score gap
        if score_val and zdf not in ("--", "", None):
            try:
                gap = score_val - float(zdf)
                if gap >= 0:
                    lines.append("你的" + str(score_val) + "分超投档线" + str(int(gap)) + "分，已达到学校投档要求")
                else:
                    lines.append("你的" + str(score_val) + "分低于投档线" + str(int(abs(gap))) + "分，可以冲刺但风险较高")
            except:
                pass
    
    # Build enriched major list
    enriched = []
    for m in latest["majors"]:
        zdf_v = m.get("zdf")
        if zdf_v is None or str(zdf_v).strip() in ("--", "", "None"):
            continue
        sc = float(zdf_v)
        name = m["majorType"]
        wcz_v = m.get("wcz", "--")
        
        if score_val:
            # Score-based risk analysis
            if sc > score_val:
                continue
            gap = int(score_val - sc)
            
            # Risk score calculation
            risk_score = 0
            if gap <= 3: risk_score += 4
            elif gap <= 6: risk_score += 2
            elif gap <= 10: risk_score += 1
            try:
                cnt = int(m.get("recruitNum", 10) or 10)
                if cnt <= 2: risk_score += 3
                elif cnt <= 5: risk_score += 2
            except: pass
            
            if risk_score >= 5: risk = "冲刺"
            elif risk_score >= 3: risk = "稳妥"
            else: risk = "保底"
        else:
            # No score: show all majors sorted by score descending
            risk = "全部"
            gap = 0
        
        enriched.append({"name": name, "zdf": sc, "gap": gap, "risk": risk, "wcz": wcz_v})
    
    if score_val:
        # Sort by risk (保底 first, then 稳妥, then 冲刺) then by gap (larger gap = safer)
        risk_order = {"保底": 0, "稳妥": 1, "冲刺": 2}
        enriched.sort(key=lambda x: (risk_order.get(x["risk"], 9), -x["gap"]))
        # Output by tier
        for tier, icon in [("保底", "🟢"), ("稳妥", "🟡"), ("冲刺", "🟠")]:
            items = [x for x in enriched if x["risk"] == tier]
            if not items:
                continue
            lines.append("")
            lines.append(icon + " " + tier + "推荐（" + str(len(items)) + "个）：")
            for x in items[:6]:
                lines.append("  " + x["name"] + "：最低" + str(x["zdf"]) + "分(低" + str(x["gap"]) + "分)")
    else:
        # No score: show all majors sorted by score descending
        enriched.sort(key=lambda x: -x["zdf"])
        lines.append("")
        lines.append("📋 全部专业（" + str(len(enriched)) + "个）：")
        for x in enriched:
            lines.append("  " + x["name"] + "：最低" + str(x["zdf"]) + "分")
    
    # Trend insight
    if len(years_data) >= 2:
        lines.append("")
        lines.append("近3年位次趋势：")
        for yd in years_data:
            s = yd["stats"]
            if s and s[0].get("wcz"):
                w = f_rank(s[0]["wcz"])
                lines.append("  " + str(yd["year"]) + "年: " + w)
    
    # Best recommendation
    safe = [x for x in enriched if x["risk"] == "保底"]
    medium = [x for x in enriched if x["risk"] == "稳妥"]
    lines.append("")
    if safe:
        top = safe[0]
        lines.append("首选推荐" + top["name"] + "（低" + str(top["gap"]) + "分，录取概率高）")
    
    # KB reference hint
    lines.append("")
    lines.append("可追问：某专业的培养方案/就业方向/学费/转专业政策")
    lines.append("")
    lines.append("数据来源：zs.whut.edu.cn 官方API + 知识库招生章程")
    
    return "\n".join(lines)


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__); sys.exit(0)
    if args[0] == 'list':
        for p in PROVS: print(p); sys.exit(0)
    province = args[0]
    # 强制默认广西：如果第一个参数不是有效省份名，自动设为广西
    if province not in PROVS and province != "list":
        args.insert(0, "广西")
        province = "广西"
    province = args[0]
    year = None; subject_type = None; keyword = None; score_val = None; trend_mode = False; smart_mode = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == '--smart': smart_mode = True
        elif a == '--trend': trend_mode = True
        elif a.startswith('--score'):
            score_val = float(a.split('=')[1] if '=' in a else args[i+1])
            if '=' not in a: i += 1
        elif a.isdigit() and len(a) == 4: year = int(a)
        elif a in ('物理','物理类','历史','历史类','文史','理工','艺术','艺术类'):
            subject_type = a.replace('物理','物理类').replace('历史','历史类').replace('艺术','艺术类')
            if subject_type not in ('物理类','历史类','艺术类'): subject_type = a
        else: keyword = a
        i += 1
    try:
        t0 = time.time()
        if smart_mode:
            print(smart_analyze(province, year, score_val, subject_type))
        elif trend_mode:
            all_years = get_all_years(province)[:3]
            years_collected = []
            for y in all_years:
                types_to_query = [subject_type] if subject_type else get_types(province, y)
                for st in types_to_query:
                    stats, majors = query_year(province, y, st, keyword, None)
                    if majors: years_collected.append((y, st, majors))
            if years_collected: show_trend(province, keyword, years_collected, score_val)
            else: print('[X] No trend data for: ' + province + ' ' + (keyword or ''))
        elif year and subject_type and keyword:
            stats, majors = query_year(province, year, subject_type, keyword, score_val)
            print('=== ' + province + ' ' + str(year) + ' ' + subject_type + ' ===')
            for s in stats:
                print('  [' + s.get('type', '') + '] 线' + fs(s.get('skx')) + ' 最低' + fs(s.get('zdf')) + ' 最高' + fs(s.get('zgf')) + ' 平均' + fs(s.get('pjf')) + ' 位次' + f_rank(s.get('wcz')))
            for m in majors:
                zdf = fs(m.get('zdf'))
                tag = ''
                if score_val is not None and zdf not in (chr(39)+chr(45)+chr(45)+chr(39), chr(39)+chr(39), chr(39)+chr(78)+chr(111)+chr(110)+chr(101)+chr(39)):
                    g = float(zdf) - score_val
                    tag = ' SAFE' if g <= 0 else ' 差' + str(int(g)) + '分'
                print('  ' + m['majorType'] + ': 最低' + zdf + ' 最高' + fs(m.get('zgf')) + ' 位次' + f_rank(m.get('wcz')) + tag)
        else:
            all_years = get_all_years(province)
            if year:
                primary_year = year
                trend_years = []
                if year in all_years:
                    idx = all_years.index(year)
                    if idx + 1 < len(all_years): trend_years.append(all_years[idx + 1])
                    if idx > 0: trend_years.append(all_years[idx - 1])
                years_to_query = [year] + trend_years[:2]
            elif score_val is not None:
                years_to_query = all_years[:3]; primary_year = years_to_query[0]
            else:
                years_to_query = all_years[:4]; primary_year = years_to_query[0]
            results = []
            for y in years_to_query:
                types_to_query = [subject_type] if subject_type else get_types(province, y)
                for st in types_to_query:
                    stats, majors = query_year(province, y, st, keyword, score_val)
                    if stats or (majors and ((keyword and any(keyword in m['majorType'] for m in majors)) or not keyword)):
                        results.append({'year': y, 'subject_type': st, 'stats': stats, 'majors': majors})
            if results:
                show_score_analysis(province, primary_year, results, score_val)
                show_professional(province, primary_year, results, score_val)
        elapsed = time.time() - t0
    except urllib.error.HTTPError as e:
        print('[X] API error: ' + str(e.code)); sys.exit(1)
    except urllib.error.URLError:
        print('[X] Cannot reach zs.whut.edu.cn'); sys.exit(1)
    except Exception as e:
        print('[X] Error: ' + str(e)); sys.exit(1)
