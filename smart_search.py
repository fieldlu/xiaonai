#!/usr/bin/env python3
"""smart_search.py v1.1 - enhanced knowledge base search"""
import sys, os, json, time, re, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path: sys.path.insert(0, _BASE)
_orig = sys.argv.copy(); sys.argv = ['dummy']
import kb_semantic, kb_manage, score_query, zs_whut_search, zs_plan_query
sys.argv = _orig
_CACHE = {}; _CACHE_TTL = 120
CRED = {'kb_keyword':0.95,'kb_semantic':0.85,'score_api':0.90,'enrollment':0.85,'campus':0.80,'web_search':0.55,'plan_api':0.96}
PROV = ['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江',
    '江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南',
    '广东','海南','四川','贵州','云南','陕西','甘肃','青海','台湾',
    '内蒙古','广西','西藏','宁夏','新疆']
CAMPUS = os.path.join(_BASE, 'campus_search.py')
INT_KW = ['机构优化','录取分数','招生政策','学院','专业','校区','宿舍',
    '学费','就业','培养方案','选课','转专业','奖学金','保研','考研',
    '助学','贷款','贫困','食堂','校车','图书馆','社团','学生会',
    '入党','绩点','毕业','学位','辅修','双学位','出国','交换',
    '实习','竞赛','科研','导师','通知','公告','校园卡','校园网',
    '校历','放假','军训','医保','户口','档案','成绩','挂科',
    '重修','补考','缓考','免修','创新学分','学院设置','机构设置']
QW = ['是','有','能','可以','怎么','如何','多少','什么',
    '为什么','哪个','哪些','何时','哪里','谁','吗']
STOP = {'可以','什么','怎么','如何','这个','那个','一个',
    '我们','他们','你们','没有','不是','就是','还是',
    '或者','因为','所以','但是','而且','虽然','如果',
    '然后','之后','之前','同时','已经','可能'}

def _cached(k, ttl=None):
    if ttl is None: ttl=_CACHE_TTL
    if k in _CACHE: v,ts=_CACHE[k]; return v if time.time()-ts<ttl else None
    return None
def _set_cache(k,v): _CACHE[k]=(v,time.time())

def extract_keywords(msg):
    kws=[msg.strip()[:60]]
    for w in INT_KW:
        if w in msg and w not in kws: kws.append(w)
    for q in QW:
        parts=msg.split(q,1)
        if len(parts)>1 and len(parts[1].strip())>1:
            kw=parts[1].strip()[:20]
            if kw not in kws: kws.append(kw)
        if len(parts[0].strip())>1:
            kw=parts[0].strip()[-20:]
            if kw not in kws: kws.append(kw)
    for w in re.findall(r'[一-龿]{2,10}',msg):
        if w not in kws and w not in STOP: kws.append(w)
    seen=set();res=[]
    for k in kws:
        if k not in seen: seen.add(k);res.append(k)
    return res[:8]

def classify_query(q):
    s=['kb_keyword','kb_semantic'];l=q.lower()
    if any(w in l for w in ['录取','分数','位次','多少分','分数线','投档','高考']):s.append('score_api')
    if any(w in l for w in ['招生','计划','名额','选科','专业介绍','招']):s.append('enrollment')
    if any(w in l for w in ['招生','计划']):s.append('plan_api')
    if any(w in l for w in ['通知','公告','校园','学校','whut','教务处','校']):s.append('campus')
    if any(w in l for w in ['什么','怎么','如何','为什么','哪个','吗']):s.append('web_search')
    return s

def _kb_kw(q,k=6):
    ck='kb_kw:'+q;cd=_cached(ck)
    if cd is not None: return cd
    try:
        r=kb_manage._do_search(q)
        if not r:
            for kw in extract_keywords(q)[1:]:
                r=kb_manage._do_search(kw)
                if r: break
        # 补充搜索：列表类查询补搜"机构设置""学院设置"等结构关键词
        if '有哪些' in q or '有哪' in q or '列表' in q or '所有' in q:
            if '学院' in q or '学部' in q or '机构' in q or '部门' in q:
                extra = kb_manage._do_search('机构设置')
                if extra:
                    if not r: r = []
                    # Merge, avoid duplicates by filename
                    seen = {item[0] for item in r}
                    for item in extra:
                        if item[0] not in seen:
                            seen.add(item[0])
                            r.append(item)
        if r:
            lines=[]
            for it in r[:k*3]:  # Larger candidate pool
                if len(it)>=3: fn,c,mt=it[:3]
                elif len(it)>=2: fn,c=it[:2];mt=[]
                else: continue
                t=kb_manage._topic_from_file(fn)
                sn=''
                if mt and len(mt)>0:
                    f=mt[0]
                    if isinstance(f,(list,tuple)) and len(f)>1: sn=f[1]
                    else: sn=str(f)
                lines.append({'source':'kb_keyword','topic':t,'snippet':sn,'file':fn,'credibility':CRED['kb_keyword']})
            _set_cache(ck,lines);return lines
    except: pass
    return []

def _kb_sem(q,k=6):
    ck='kb_sem:'+q;cd=_cached(ck)
    if cd is not None: return cd
    try:
        import contextlib
        with open(os.devnull,'w') as dn:
            with contextlib.redirect_stdout(dn):
                r=kb_semantic.search(q,top_k=k*3)  # Larger pool
        lines=[]
        for item in r:
            if len(item)>=3:
                fp,sc,sn=item[0],item[1],item[2]
            else:
                fp,sc=item[0],item[1]; sn=''
            if sc<0.025: continue  # Lower threshold: 0.04->0.025
            t=os.path.splitext(os.path.basename(fp))[0]
            cr=min(CRED['kb_semantic']+sc*0.5,0.95)
            ct=sn if sn else ''
            if not ct:
                try:
                    with open(os.path.join(_BASE,"data","knowledge",fp+".md"),'r',encoding='utf-8') as f: ct=f.read()
                except: ct=''
            lines.append({'source':'kb_semantic','topic':t,'snippet':ct,'score':round(sc,3),'credibility':round(cr,2)})
        _set_cache(ck,lines);return lines
    except: return []

def _score(q):
    ck='score:'+q;cd=_cached(ck)
    if cd is not None: return cd
    try:
        pv=None
        for p in PROV:
            if p in q: pv=p;break
        if pv:
            ys=score_query.get_all_years(pv)
            if ys and len(ys)>0:
                py=ys[-1]
                for st in score_query.get_types(pv,py)[:2]:
                    rs,_=score_query.query_year(pv,py,st,'','')
                    if rs:
                        _set_cache(ck,[{'source':'score_api','province':pv,'year':py,'type':st,'sample':rs[:3],'credibility':CRED['score_api']}]);return [{'source':'score_api','province':pv,'year':py,'type':st,'sample':rs[:3],'credibility':CRED['score_api']}]
    except: pass
    _set_cache(ck,[]);return []

def _plan(q):
    ck='plan:'+q;cd=_cached(ck,300)
    if cd is not None: return cd
    try:
        pv=None
        for p in PROV:
            if p in q: pv=p;break
        if not pv: pv = '广西'
        kw=None
        yr=2025
        parts=q.replace(pv,'').replace('省','').replace('计划','').replace('招生','').replace('专业','').split()
        for a in parts:
            if a.isdigit() and len(a)==4 and 2020<=int(a)<=2030: yr=int(a)
            elif len(a)>1 and a not in ('什么','的','在','有','吗','哪些','哪个'): kw=a
        output=zs_plan_query.query_full(pv, yr, kw)
        if output and not output.startswith('[X]'):
            item={'source':'plan_api','province':pv,'year':yr,'topic':pv+str(yr)+'招生计划','content':output,'credibility':CRED['plan_api']}
            _set_cache(ck,[item])
            return [item]
    except: pass
    _set_cache(ck,[])
    return []

def _campus(q):
    ck='campus:'+q;cd=_cached(ck,300)
    if cd is not None: return cd
    try:
        r=subprocess.run([sys.executable,CAMPUS,q],capture_output=True,text=True,timeout=20)
        if r.stdout.strip() and 'Error' not in r.stdout:
            _set_cache(ck,[{'source':'campus','content':r.stdout.strip(),'credibility':CRED['campus']}]);return [{'source':'campus','content':r.stdout.strip(),'credibility':CRED['campus']}]
    except: pass
    return []

def _zs(q):
    ck='zs:'+q;cd=_cached(ck,300)
    if cd is not None: return cd
    try:
        r=zs_whut_search.search(q,max_pages=5)
        if r:
            _set_cache(ck,[{'source':'enrollment','title':it.get('title',''),'snippet':it.get('snippet',''),'credibility':CRED['enrollment']} for it in r[:3]]);return [{'source':'enrollment','title':it.get('title',''),'snippet':it.get('snippet',''),'credibility':CRED['enrollment']} for it in r[:3]]
    except: pass
    return []

def _web(q):
    ck='web:'+q;cd=_cached(ck,300)
    if cd is not None: return cd
    try:
        import urllib.request,urllib.parse
        with urllib.request.urlopen('http://127.0.0.1:8899/search?q='+urllib.parse.quote(q),timeout=8) as r:
            d=json.loads(r.read())
        it=d.get('results',d.get('items',[]))
        if it:
            _set_cache(ck,[{'source':'web_search','title':i.get('title',''),'snippet':i.get('content',''),'credibility':CRED['web_search']} for i in it[:3]]);return [{'source':'web_search','title':i.get('title',''),'snippet':i.get('content',''),'credibility':CRED['web_search']} for i in it[:3]]
    except: pass
    return []

def smart_search(q,k=6,t=15):
    src=classify_query(q);res=[]
    with ThreadPoolExecutor(6) as p:
        fm={}
        if 'kb_keyword' in src: fm[p.submit(_kb_kw,q,k)]=1
        if 'kb_semantic' in src: fm[p.submit(_kb_sem,q,k)]=1
        if 'score_api' in src: fm[p.submit(_score,q)]=1
        if 'enrollment' in src: fm[p.submit(_zs,q)]=1
        if 'campus' in src: fm[p.submit(_campus,q)]=1
        if 'web_search' in src: fm[p.submit(_web,q)]=1
        if 'plan_api' in src:
            try:
                pr=_plan(q)
                if pr: res.extend(pr)
            except: pass
        for f in as_completed(fm,timeout=t):
            try:
                r=f.result()
                if r: res.extend(r)
            except: pass
    # Intent-based reranking: boost docs matching query intent
    if any(w in q for w in ['有哪些','有哪','列表','所有','全部','都有']):
        # For list queries about colleges/departments, boost structural docs
        boost_kw = ['机构', '学院', '学部', '教学单位', '设置', '院']
        for r in res:
            t = str(r.get('topic','')) + str(r.get('title',''))
            if any(kw in t for kw in boost_kw):
                r['credibility'] = min(r['credibility'] * 1.15, 0.99)
    res.sort(key=lambda x:x.get('credibility',0),reverse=True)
    return res[:k]

def fmt(res,q):
    if not res: return ''
    lb={'kb_keyword':'知识库关键词','kb_semantic':'知识库语义','score_api':'录取分数API','enrollment':'招生官网','campus':'校园通知','web_search':'网页搜索','plan_api':'招生计划API'}
    p=['','[智能搜索] 综合搜索结果（按可信度排序）：','='*50]
    for i,r in enumerate(res,1):
        cr=r.get('credibility',0);b='█'*int(cr*10)+'░'*(10-int(cr*10))
        lb2=lb.get(r.get('source',''),r.get('source',''))
        p.append('');p.append('  [{}] {}  [{}] 可信度 {:.0%}'.format(i,lb2,b,cr))
        for kk,pr in [('topic','主题'),('province','省份'),('year','年份'),('title','标题'),('snippet','摘要'),('content','内容')]:
            v=r.get(kk)
            if v: p.append('      {} {}'.format(pr,str(v)))
    p.append('');p.append('[智能搜索结束] 知识库=可信度95%，官方API=90%，招生官网=85%，网页搜索仅供参考。');p.append('='*50)
    return '\n'.join(p)

def smart_search_formatted(q,k=6):
    return fmt(smart_search(q,k),q)

if __name__=='__main__':
    print(smart_search_formatted(' '.join(sys.argv[1:]) or 'YOUR_SCHOOL'))
