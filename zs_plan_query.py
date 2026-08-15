#!/usr/bin/env python3
"""WHUT Enrollment Plan Query - search admission plans"""
import sys, urllib.request, urllib.parse, json, time

CACHE = {}
CACHE_TTL = {}
API_BASE = "https://zs.whut.edu.cn/enroll-info/recruitScheme/"

PROVS = ["安徽","北京","重庆","福建","广东","广西","贵州","甘肃","湖北","湖南",
         "河北","河南","黑龙江","海南","江苏","江西","吉林","辽宁","宁夏",
         "内蒙古","青海","上海","四川","山东","山西","陕西","天津","新疆",
         "西藏","云南","浙江"]

SUBJECT_TYPES = ["物理类", "历史类", "艺术类", "艺术(历史类)", "艺术(物理类)", "艺术(不分科目类)"]

def _api(endpoint, data):
    key = endpoint + str(sorted(data.items()))
    now = time.time()
    if key in CACHE_TTL and now - CACHE_TTL[key] < 120:
        return CACHE[key]
    try:
        d = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(API_BASE + endpoint, data=d, method="POST")
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        CACHE[key] = resp
        CACHE_TTL[key] = now
        return resp
    except:
        return {"success": False}

def get_subject_types(province, year):
    resp = _api("selSubjectTypeByProvinceAndYear.do", {"province": province, "year": year})
    types = resp.get("data", []) if resp.get("success") else []
    return [t for t in types if t != "\u5168\u90e8"] or ["物理类", "历史类"]

def query_plan(province, year, subject_type, plan_type="\u5168\u90e8"):
    resp = _api("selRecruitByProvinceAndYearAndSubjectType.do",
                {"province": province, "year": year, "subjectType": subject_type, "type": plan_type})
    if resp.get("success"):
        return resp.get("ext", {}).get("recruitSchemeList", [])
    return []

def fmt_plan(plans, keyword=None):
    lines = []
    if not plans:
        return ["[emmm] 暂无招生计划数据"]
    if keyword:
        kw = keyword.lower()
        plans = [p for p in plans if kw in p.get("majorType", "").lower()]
    if not plans:
        if keyword:
            return ['未找到匹配 ' + keyword]
        return ["未找到匹配专业"]
    for ptype in sorted(set(p.get("type", "普通类") for p in plans)):
        items = [p for p in plans if p.get("type", "普通类") == ptype]
        if ptype != "普通类":
            lines.append("")
            lines.append("[" + ptype + "]")
        for p in items:
            name = p["majorType"]
            num = p.get("recruitNum", "--")
            elective = p.get("electiveSubject", "")
            remark = p.get("remarks", "")
            parts = ["  " + name + ": " + str(num) + "人"]
            if elective:
                parts.append("选科: " + elective)
            if remark:
                parts.append("包含: " + remark)
            lines.append(" | ".join(parts))
        total = sum(int(p.get("recruitNum", 0) or 0) for p in items)
        lines.append("  -> 合计 " + str(len(items)) + "个专业, " + str(total) + "人")
    return lines

def query_full(province, year, keyword, subject_type=None):
    types = [subject_type] if subject_type and subject_type in SUBJECT_TYPES else get_subject_types(province, year)
    if "物理类" in types and not subject_type:
        types = ["物理类"] + [t for t in types if t != "物理类"]
    all_lines = []
    has_data = False
    for st in types:
        plans = query_plan(province, year, st)
        if plans:
            has_data = True
            all_lines.append("")
            all_lines.append("=== " + province + " " + str(year) + " " + st + " ===")
            all_lines.extend(fmt_plan(plans, keyword))
    if not has_data:
        return "[X] 暂无招生计划数据 for " + province + " " + str(year)
    return "\n".join(all_lines)

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if args[0] == "list":
        for p in PROVS: print(p)
        sys.exit(0)
    province = args[0]
    if province not in PROVS:
        args.insert(0, "广西")
        province = "广西"
    year = 2025
    keyword = None
    subject_type = None
    for a in args[1:]:
        if a.isdigit() and len(a) == 4 and 2020 <= int(a) <= 2030:
            year = int(a)
        elif a in SUBJECT_TYPES:
            subject_type = a
        else:
            keyword = a
    try:
        print(query_full(province, year, keyword, subject_type))
    except Exception as e:
        print("[X] Error: " + str(e))
        sys.exit(1)
