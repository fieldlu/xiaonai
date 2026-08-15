#!/usr/bin/env python3
"""Scheduler v5.2: +timed_msg one-shot message queue."""
import asyncio, json, os, time, logging, httpx, re, math, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("scheduler")
# 08-14: 去掉 StreamHandler（不再写 stdout，避免 systemd 双捕获到 /tmp）；
# 改 RotatingFileHandler 自动轮转（5MB x 5）。崩溃栈仍由 systemd 捕获到 /tmp/scheduler.log。
from logging.handlers import RotatingFileHandler as _RFH
logging.basicConfig(level=logging.INFO, format="[scheduler] %(asctime)s %(message)s",
                    handlers=[_RFH("/opt/xiaonai/logs/scheduler.log", maxBytes=5*1024*1024, backupCount=5)])

DATA = Path("/opt/xiaonai/data")
CONFIG_FILE = DATA / "scheduler_config.json"
STATE_FILE = DATA / "scheduler_state.json"
QW_KEY = os.getenv("QW_API_KEY", "").strip()
QW_HOST = os.getenv("QW_API_HOST", "").strip()
EQ_API = "https://api.wolfx.jp/cenc_eqlist.json"
MAX_DAILY_FAILURES = 5
# 08-15: campus_daily 是持续轮询订阅（每2分钟），SSLError 等瞬时抖动
# 不该耗尽整天预算。给它宽松的 20 次/天上限（约 40 分钟连续失败才停）。
CAMPUS_DAILY_FAILURE_BUDGET = 20
NAP_CAT_WS = "ws://127.0.0.1:3001"

# PID lock: prevent duplicate instances
LOCK_FILE = DATA / "scheduler.pid"
def check_pid_lock():
    import sys
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            try:
                os.kill(old_pid, 0)
                log.warning("Another scheduler running (PID %s), exiting", old_pid)
                sys.exit(0)
            except OSError:
                pass
        except (ValueError, OSError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))
check_pid_lock()

DEFAULT_CONFIG = {
    "weather": {"enabled": True, "hour": 7, "groups": [CLASS_GROUP_PLACEHOLDER]},
    "news": {"enabled": True, "hour": 18, "groups": [CLASS_GROUP_PLACEHOLDER]},
    "earthquake": {"enabled": True, "interval_min": 0.5, "groups": [CLASS_GROUP_PLACEHOLDER], "min_magnitude": 4.0},
    "weather_warning": {"enabled": True, "interval_min": 10, "groups": [CLASS_GROUP_PLACEHOLDER]},
    "campus_daily": {"enabled": True, "interval_min": 2, "groups": [CLASS_GROUP_PLACEHOLDER]},
    "exam_countdown": {"enabled": True, "groups": []},
}

EQ_CACHE = DATA / "eq_sched_cache.json"
WW_CACHE = DATA / "ww_sched_cache.json"
EQ_SENTINEL = DATA / ".eq_sched_init"
WW_SENTINEL = DATA / ".ww_sched_init"

SEND_RETRIES = 3
SEND_TIMEOUT = 5.0
# Groups where 小奈 was removed; skip delivery without retry (08-13)
GONE_GROUPS = set()

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except: pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

def load_state():
    if STATE_FILE.exists():
        try:
            _s = json.loads(STATE_FILE.read_text())
            if isinstance(_s, dict) and 'failures' not in _s:
                _s['failures'] = {}   # 08-13: fix KeyError when old state lacks 'failures'
            return _s
        except: pass
    return {'failures': {}}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s))


def _record_failure(task: str, s: dict, limit: int = None):
    """Record a failure for a task. Returns True if budget exceeded."""
    limit = limit or MAX_DAILY_FAILURES
    today = datetime.now().strftime('%Y-%m-%d')
    if task not in s.get('failures', {}):
        s['failures'][task] = {'count': 0, 'date': today}
    f = s['failures'][task]
    if f.get('date') != today:
        f['count'] = 0
        f['date'] = today
    f['count'] = f.get('count', 0) + 1
    if f['count'] >= limit:
        log.warning("Error budget exceeded for %s (%d/%d), skipping rest of day", task, f['count'], limit)
        return True
    log.warning("Failure %d/%d for %s", f['count'], limit, task)
    return False

def _budget_ok(task: str, s: dict, limit: int = None) -> bool:
    """Check if task still has error budget."""
    limit = limit or MAX_DAILY_FAILURES
    today = datetime.now().strftime('%Y-%m-%d')
    f = s.get('failures', {}).get(task, {})
    if f.get('date') == today and f.get('count', 0) >= limit:
        log.warning("Skipping %s: error budget exhausted (%d/%d failures today)", task, f['count'], limit)
        return False
    return True



def cleanup_all_redundant(dry_run=False):
    now = time.time()
    max_age = 72 * 3600
    trash_dir = Path("/opt/xiaonai") /'.trash'
    max_files = 20
    total = 0
    ALLOWED = {'.docx','.doc','.xlsx','.xls','.pdf','.ppt','.pptx','.png','.jpg','.jpeg','.gif','.bmp','.svg'}
    BLOCKED = {'.git','.trash','data/knowledge','data/memory','data/diary'}
    def _blocked(p):
        ap = str(p.resolve())
        return any(b in ap for b in BLOCKED)
    def _trash(f, is_purge=False):
        nonlocal total
        if total >= max_files and not is_purge:
            return
        try:
            age_h = (now - f.stat().st_mtime) / 3600
            fname = f.name
        except OSError:
            return  # file already gone
        if dry_run:
            log.info('[DRY_RUN] would trash %s (age=%.1fh)', fname, age_h)
            total += 1
            return
        trash_dir.mkdir(parents=True, exist_ok=True)
        tp = trash_dir / f'{int(time.time())}_{os.getpid()}_{fname}'
        try:
            f.rename(tp)
            log.info('Cleanup: moved %s -> .trash/ (age=%.1fh)', fname, age_h)
            total += 1
        except OSError as e:
            log.warning('Cleanup: failed to move %s: %s', fname, e)
    def _purge():
        c = 0
        if not trash_dir.exists():
            return c
        for ff in list(trash_dir.iterdir()):
            if ff.is_file() and (now - ff.stat().st_mtime) > 7*86400:
                try:
                    ff.unlink(); c += 1
                    log.info('Trash: purged %s (age=%.1fd)', ff.name, (now-ff.stat().st_mtime)/86400)
                except Exception as e:
                    log.warning('Trash: purge error %s: %s', ff.name, e)
        return c
    targets = []
    ex = Path("/opt/xiaonai")/'exports'
    if ex.exists() and not _blocked(ex):
        for f in ex.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED:
                targets.append(f)



    for f in Path("/opt/xiaonai").iterdir():
        if f.is_file() and f.name.startswith("tmp_") and f.suffix.lower() in ALLOWED:
            targets.append(f)
    expired = [f for f in targets if (now - f.stat().st_mtime) > max_age]
    expired.sort(key=lambda f: f.stat().st_mtime)
    for f in expired:
        _trash(f)
    pc = _purge()
    mode = 'DRY_RUN' if dry_run else 'LIVE'
    log.info('Cleanup %s: trashed=%d purged=%d', mode, total, pc)
    return total

async def reconnect_ws():
    import websockets
    for attempt in range(10):
        try:
            ws = await websockets.connect(NAP_CAT_WS, close_timeout=5)
            log.info("Reconnected to NapCat")
            return ws
        except Exception as e:
            log.warning("Reconnect attempt %d/10: %s", attempt + 1, e)
            await asyncio.sleep(2)
    log.error("Failed to reconnect after 10 attempts")
    return None


async def is_ws_alive(ws):
    try:
        if ws.closed:
            return False
        pong = await asyncio.wait_for(ws.ping(), timeout=3.0)
        return True
    except Exception:
        return False


async def send_group_msg_confirmed(ws, gid, text):
    import websockets as ws_mod
    echo_id = f"s_{int(time.time()*1000)}"
    action = {"action": "send_group_msg", "params": {"group_id": gid, "message": text}, "echo": echo_id}
    try:
        await ws.send(json.dumps(action))
    except Exception as e:
        log.error("Send to %d failed (ws send error): %s", gid, e)
        return False
    try:
        while True:
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=SEND_TIMEOUT)
            try:
                resp = json.loads(resp_raw)
            except json.JSONDecodeError:
                continue
            if resp.get("echo") == echo_id:
                if resp.get("status") == "ok":
                    return True
                else:
                    _err = str(resp.get("wording", resp.get("msg", "unknown")))
                    log.error("NapCat returned error for %d: %s", gid, _err)
                    if ("移出该群" in _err) or ("not in group" in _err.lower()):
                        GONE_GROUPS.add(gid)
                        log.warning("Group %d: 小奈已被移出，标记为 GONE，今日不再重试", gid)
                    return False
    except asyncio.TimeoutError:
        log.error("Send to %d: no echo confirmation within %.1fs", gid, SEND_TIMEOUT)
        return False
    except Exception as e:
        log.error("Send to %d: recv error: %s", gid, e)
        return False


async def send_with_retry(ws_ref, gid, text, max_retries=SEND_RETRIES):
    # GONE group auto-recovery: still try once per push cycle so a re-added
    # group recovers automatically. Success clears the GONE flag; failure keeps
    # it so we don't hammer a removed group with full retries every cycle.
    if gid in GONE_GROUPS:
        max_retries = 1
    for attempt in range(max_retries):
        ws = ws_ref[0]
        alive = await is_ws_alive(ws)
        if not alive:
            log.warning("WS dead before send, reconnecting... (attempt %d)", attempt + 1)
            ws = await reconnect_ws()
            if not ws:
                await asyncio.sleep(3)
                continue
            ws_ref[0] = ws
        success = await send_group_msg_confirmed(ws, gid, text)
        if success:
            if gid in GONE_GROUPS:
                GONE_GROUPS.discard(gid)
                log.info("Group %d delivery recovered (was GONE) — auto-restored", gid)
            log.info("Confirmed delivery to %d (attempt %d)", gid, attempt + 1)
            return True
        else:
            log.warning("Send to %d failed (attempt %d/%d), reconnecting...", gid, attempt + 1, max_retries)
            ws = await reconnect_ws()
            if ws:
                ws_ref[0] = ws
            await asyncio.sleep(1)
    log.error("Send to %d FAILED after %d retries", gid, max_retries)
    return False


async def send_private_msg_confirmed(ws, uid, text):
    echo_id = f"s_{int(time.time()*1000)}"
    action = {"action": "send_private_msg", "params": {"user_id": uid, "message": text}, "echo": echo_id}
    try:
        await ws.send(json.dumps(action))
    except Exception as e:
        return False
    try:
        while True:
            resp_raw = await asyncio.wait_for(ws.recv(), timeout=SEND_TIMEOUT)
            try:
                resp = json.loads(resp_raw)
            except json.JSONDecodeError:
                continue
            if resp.get("echo") == echo_id:
                if resp.get("status") == "ok":
                    return True
                return False
    except:
        return False


async def send_private_with_retry(ws_ref, uid, text, max_retries=SEND_RETRIES):
    for attempt in range(max_retries):
        ws = ws_ref[0]
        alive = await is_ws_alive(ws)
        if not alive:
            log.warning("WS dead before private send, reconnecting... (attempt %d)", attempt + 1)
            ws = await reconnect_ws()
            if not ws:
                await asyncio.sleep(3)
                continue
            ws_ref[0] = ws
        success = await send_private_msg_confirmed(ws, uid, text)
        if success:
            log.info("Confirmed private to %d (attempt %d)", uid, attempt + 1)
            return True
        else:
            log.warning("Private send to %d failed (attempt %d/%d), reconnecting...", uid, attempt + 1, max_retries)
            ws = await reconnect_ws()
            if ws:
                ws_ref[0] = ws
            await asyncio.sleep(1)
    log.error("Private send to %d FAILED after %d retries", uid, max_retries)
    return False


async def weather_forecast():
    """Enhanced weather forecast with life indices."""
    for attempt in range(2):
        try:
            if not QW_HOST or not QW_KEY:
                raise Exception('QWeather not configured (QW_API_KEY/QW_API_HOST)')
            async with httpx.AsyncClient(timeout=10) as c:
                r7 = await c.get(f'https://{QW_HOST}/v7/weather/7d', params={'key': QW_KEY, 'location': '101200101'})
                ri = await c.get(f'https://{QW_HOST}/v7/indices/1d', params={'key': QW_KEY, 'location': '101200101', 'type': '1,2,3,5,8,9'})
                if r7.status_code != 200: raise Exception(f'Weather API HTTP {r7.status_code}')
                data7 = r7.json()
                datai = ri.json()
            if data7.get('code') != '200': raise Exception('err')
            daily = data7['daily']
            d0 = daily[0]
            o = []
            o.append('🌤 武汉' + str(int(d0.get('fxDate','')[5:7])) + '月' + str(int(d0.get('fxDate','')[8:10])) + '日')
            o.append('────────────────────')
            o.append('🌡 ' + d0.get('tempMin','?') + '°C~' + d0.get('tempMax','?') + '°C   ☁ ' + d0.get('textDay',''))
            o.append('💧 湿度 ' + d0.get('humidity','?') + '%   🌬 ' + d0.get('windDirDay','') + ' ' + d0.get('windScaleDay','') + '级')
            o.append('🌅 日出 ' + d0.get('sunrise','') + '   🌇 日落 ' + d0.get('sunset',''))
            o.append('☂ 降雨量 ' + d0.get('precip','?') + 'mm   紫外线 ' + d0.get('uvIndex','?'))
            o.append('')
            o.append('── 未来三天 ──')
            for i in range(1, min(4, len(daily))):
                d = daily[i]
                fd = d.get('fxDate','').replace('2026-','').replace('-','/')
                o.append('📅 ' + fd + ' ' + d.get('textDay','') + ' ' + d.get('tempMin','?') + '°~' + d.get('tempMax','?') + '°C')
            o.append('')
            if datai.get('code') == '200':
                for idx in datai.get('daily',[])[:5]:
                    o.append('💡 ' + idx.get('name','') + ':' + idx.get('category','') + '(' + idx.get('text','') + ')')
            o.append('────────────────────')
            return chr(10).join(o)
        except:
            if attempt == 0:
                await asyncio.sleep(2)
            continue
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get('https://wttr.in/Wuhan?format=3')
            return '🌤 武汉天气\n' + r.text.strip()
    except:
        pass
    return None

async def check_weather_warning(ws_ref, cfg):
    if not QW_HOST or not QW_KEY:
        log.warning("QWeather not configured, skip weather warning check")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://{QW_HOST}/weatheralert/v1/current/30.59/114.30",
                           params={"key": QW_KEY})
            if r.status_code != 200:
                return
            data = r.json()
        alerts = [a for a in data.get("alerts",[]) if "武汉" in (a.get("headline","") or "")]
        if not alerts: return
        seen = set()
        if WW_CACHE.exists():
            try: seen = set(json.loads(WW_CACHE.read_text()))
            except: pass
        first = not WW_SENTINEL.exists()
        now = datetime.now(timezone.utc)
        new_alerts = []
        for a in alerts:
            aid = a.get("id","")
            if not aid: continue
            if first: seen.add(aid)
            if aid in seen and not first: continue
            seen.add(aid)
            try:
                et = datetime.fromisoformat(a.get("expireTime","").replace("Z","+00:00"))
                if et <= now: continue
            except: pass
            new_alerts.append(a)
        if first:
            WW_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
            WW_SENTINEL.write_text("1")
            WW_CACHE.write_text(json.dumps(sorted(seen)[-500:]))
            log.info(f"WW init: {len(seen)} alerts cached")
# removed return
        if not new_alerts: return
        WW_CACHE.write_text(json.dumps(sorted(seen)[-500:]))
        for a in new_alerts:
            color = a.get("color",{}).get("code","")
            icon = {"blue":"🔵","yellow":"🟡","orange":"🟠","red":"🔴"}.get(color,"⚠️")
            msg = f"{icon} 武汉气象预警\n━━━━━━━━━━━━━━\n📌 {a.get('headline','')}\n📋 {(a.get('description','') or '')[:200]}\n💡 {(a.get('instruction','') or '')[:150]}\n━━━━━━━━━━━━━━"
            for gid in cfg["weather_warning"]["groups"]:
                ok = await send_with_retry(ws_ref, gid, msg, max_retries=2)
                if ok:
                    log.info(f"WW confirmed to {gid}: {a.get('headline','')[:50]}")
                else:
                    log.error(f"WW FAILED to {gid} after retries")
    except Exception as e:
        log.error("WW error: %s", e)
        log.error(traceback.format_exc())

def haversine_km(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))

async def check_earthquake(ws_ref, cfg):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(EQ_API)
            if r.status_code != 200:
                log.warning("EQ API returned %d, skipping cycle", r.status_code)
                return
            data = r.json()
        if isinstance(data, dict):
            items = [v for k, v in data.items() if isinstance(v, dict)]
        else:
            items = [x for x in data if isinstance(x, dict)]
        seen = set()
        if EQ_CACHE.exists():
            try: seen = set(json.loads(EQ_CACHE.read_text()))
            except: pass
        first = not EQ_SENTINEL.exists()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=6)
        new_eqs = []
        zones = cfg["earthquake"].get("zones", [])
        global_min_mag = cfg["earthquake"].get("min_magnitude", 3.0)
        items_with_coords = []
        for eq in items:
            try: mag = float(eq.get("magnitude", eq.get("mag", 0)))
            except: continue
            try:
                lat = float(eq.get("lat", eq.get("latitude", eq.get("Latitude", 0))))
                lon = float(eq.get("lon", eq.get("longitude", eq.get("Longitude", 0))))
            except:
                loc = eq.get("location","") or eq.get("placeName","") or ""
                if any(k in loc for k in ["日本","印尼","菲律宾","墨西哥","智利","韩国","朝鲜","俄罗斯","美国","加拿大","印度","尼泊尔","缅甸","越南","澳大利亚","新西兰"]):
                    continue
                try:
                    lat = float(eq.get("lat", eq.get("latitude", 0)))
                    lon = float(eq.get("lon", eq.get("longitude", 0)))
                except:
                    continue
            loc = eq.get("location","") or eq.get("placeName","") or ""
            exclude_kw = cfg["earthquake"].get("exclude_location_kw", [])
            skipped = False
            for ek in exclude_kw:
                if ek in loc:
                    skipped = True
                    break
            if skipped:
                continue
            if mag >= 1.0:
                items_with_coords.append((eq, mag, lat, lon))
        for eq, mag, eq_lat, eq_lon in items_with_coords:
            eid = eq.get("EventID","") or eq.get("id","") or str(eq.get("time",""))
            if not eid: continue
            if first: seen.add(eid)
            if eid in seen and not first: continue
            seen.add(eid)
            try:
                t_str = eq.get("time","") or eq.get("ReportTime","")
                if t_str:
                    et = datetime.strptime(t_str[:19],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if et < cutoff: continue
            except: pass
            matched = False
            best_label = "🟢"
            best_tag = ""
            groups_to_send = set()
            for zone in zones:
                dist = haversine_km(eq_lat, eq_lon, zone["lat"], zone["lon"])
                zone_mag = zone.get("min_mag", global_min_mag)
                if dist <= zone["radius_km"] and mag >= zone_mag:
                    matched = True
                    if mag >= 7:
                        best_label = "🔴"
                    elif mag >= 6:
                        if best_label in ("🟢","🟡"): best_label = "🟠"
                    elif mag >= 5:
                        if best_label == "🟢": best_label = "🟡"
                    best_tag = f"📍 {zone['name']} | {dist:.0f}km"
                    for gid in cfg["earthquake"]["groups"]:
                        groups_to_send.add(gid)
            if not matched:
                if mag >= global_min_mag:
                            break
            if not matched:
                continue
            new_eqs.append((eq, mag, best_label, best_tag, groups_to_send))
        if first:
            EQ_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
            EQ_SENTINEL.write_text("1")
            EQ_CACHE.write_text(json.dumps(sorted(seen)[-3000:]))
            log.info(f"EQ init: {len(seen)} events cached")
# removed return
        if not new_eqs: return
        EQ_CACHE.write_text(json.dumps(sorted(seen)[-3000:]))
        for eq, mag, label, tag, gids in new_eqs:
            loc = eq.get("location","") or eq.get("placeName","未知")
            msg = (f"📡 地震预警\n━━━━━━━━━━━━━━\n{label} M{mag} {loc}\n📏 深度 {eq.get('depth','?')}km\n{tag}\n🕐 {eq.get('time','?')}\n━━━━━━━━━━━━━━\n💡 数据：中国地震台网")
            for gid in gids:
                ok = await send_with_retry(ws_ref, gid, msg, max_retries=2)
                if ok:
                    log.info(f"EQ confirmed to {gid}: M{mag} {loc[:30]} | {tag}")
                else:
                    log.error(f"EQ FAILED to {gid} after retries: M{mag} {loc[:30]}")
    except Exception as e:
        log.error("EQ error: %s", e)
        log.error(traceback.format_exc())

async def fetch_news():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://top.baidu.com/board?tab=realtime",
                           headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            titles = re.findall(r'class="c-single-text-ellipsis"[^>]*>([^<]+)<', r.text)
            if titles:
                lines = ["📰 百度热搜", "━━━━━━━━━━━━━━"]
                for i, t in enumerate(titles[:8]):
                    lines.append(f"{i+1}. {t.strip()}")
                lines.append("━━━━━━━━━━━━━━")
                return "\n".join(lines)
    except Exception as e:
        log.error(f"Baidu news: {e}")
    return None


async def fetch_campus_daily():
    # 08-15: 加重试（2 次、间隔 3s）吸收 WARP 重启窗口——WARP 每日 04:30 重启
    # 后需几十秒~几分钟重建 MASQUE 隧道，期间经 40000 代理抓取 i.whut 会
    # 偶发 SSL UNEXPECTED_EOF。单次失败不再直接报错。
    for _attempt in range(3):
        try:
            proc = await asyncio.create_subprocess_exec(
                'python3', '/opt/xiaonai/campus/campus_daily.py', '--today',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode != 0:
                _err = stderr.decode(errors='replace')[:200]
                if _attempt < 2:
                    log.warning("campus_daily failed (attempt %d/3): %s — retrying", _attempt + 1, _err)
                    await asyncio.sleep(3)
                    continue
                log.error("campus_daily failed: %s", _err)
                return None
            text = stdout.decode(errors='replace').strip()
            if not text:
                log.info("campus_daily: no new notices today")
                return ""
            return text
        except asyncio.TimeoutError:
            if _attempt < 2:
                log.warning("campus_daily timed out (attempt %d/3) — retrying", _attempt + 1)
                await asyncio.sleep(3)
                continue
            log.error("campus_daily timed out")
            return None
        except Exception as e:
            if _attempt < 2:
                log.warning("campus_daily error (attempt %d/3): %s — retrying", _attempt + 1, e)
                await asyncio.sleep(3)
                continue
            log.error("campus_daily error: %s", e)
            return None
    return None


# --- Exam countdown push ---
async def exam_countdown_push(ws_ref, cfg):
    import subprocess as _sp, json as _json, os as _os
    _scp = "/opt/xiaonai/data/scheduler_config.json"
    if not _os.path.exists(_scp):
        return
    try:
        with open(_scp) as _f:
            _sc = _json.load(_f)
        _groups = _sc.get('exam_countdown', {}).get('groups', [])
        if not _groups:
            return
    except Exception:
        return
    try:
        r = _sp.run(["python3", "/opt/xiaonai/admin/exam_countdown.py", "push"],
                    capture_output=True, text=True, timeout=15)
        out = r.stdout or ""
    except Exception as e:
        log.error("exam_countdown push error: %s", e)
        return
    if not out:
        return
    for line in out.split("\n"):
        if line.startswith("[exam] PUSH:"):
            _, _, msg = line.partition(" -> ")
            for gid in _groups:
                await send_with_retry(ws_ref, gid, msg.strip())
    try:
        _sp.run(["python3", "/opt/xiaonai/admin/exam_countdown.py", "archive"],
                capture_output=True, timeout=10)
    except Exception:
        pass


# --- One-shot timed messages ---
# Bypasses OpenClaw cron entirely. The scheduler checks timed_msg.json
# on every loop and sends due messages via its own NapCat WS connection.
TIMED_MSG_FILE = DATA / "timed_msg.json"

def load_timed_messages():
    if TIMED_MSG_FILE.exists():
        try:
            return json.loads(TIMED_MSG_FILE.read_text())
        except:
            pass
    return []

def save_timed_messages(msgs):
    DATA.mkdir(parents=True, exist_ok=True)
    TIMED_MSG_FILE.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))

def _next_recurrence(dt, rec, dow, dom):
    """Compute next occurrence for a recurring reminder."""
    import calendar
    if rec == "daily":
        return dt + timedelta(days=1)
    if rec == "weekly":
        return dt + timedelta(days=7)
    if rec == "monthly":
        y, m = dt.year, dt.month + 1
        if m == 13:
            y, m = y + 1, 1
        last = calendar.monthrange(y, m)[1]
        day = min(dom or dt.day, last)
        return dt.replace(year=y, month=m, day=day)
    return dt + timedelta(days=1)


async def check_timed_messages(ws_ref):
    """Send due one-shot timed messages and mark them sent."""
    msgs = load_timed_messages()
    if not msgs:
        return
    now = datetime.now()
    changed = False
    for m in msgs:
        if m.get('sent'):
            continue
        try:
            send_dt = datetime.strptime(m['send_at'], '%Y-%m-%d %H:%M')
        except:
            continue
        if send_dt > now:
            continue
        # This message is due
        target = None
        ok = False
        msg_text = m.get('message', '')
        if m.get('group_id') and m.get('user_id'):
            msg_text = f"[CQ:at,qq={m['user_id']}] " + msg_text
        if m.get('group_id'):
            target = ('group', m['group_id'])
            ok = await send_with_retry(ws_ref, m['group_id'], msg_text)
        elif m.get('user_id'):
            target = ('user', m['user_id'])
            ok = await send_private_with_retry(ws_ref, m['user_id'], msg_text)
        if target:
            rec = m.get('recurring')
            if ok and rec:
                next_dt = _next_recurrence(send_dt, rec, m.get('recur_dow'), m.get('recur_dom'))
                m['send_at'] = next_dt.strftime('%Y-%m-%d %H:%M')
                m['error'] = None
                log.info(f"Timed msg [{m['id']}] delivered to {target[0]} {target[1]}, next @ {m['send_at']}")
            else:
                m['sent'] = True
                m['sent_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                if ok:
                    m['error'] = None
                    log.info(f"Timed msg [{m['id']}] delivered to {target[0]} {target[1]}")
                else:
                    m['error'] = 'send_failed'
                    log.error(f"Timed msg [{m['id']}] FAILED to {target[0]} {target[1]}")
            changed = True
    if changed:
        save_timed_messages(msgs)

last_ww_check = 0
last_eq_check = 0
last_cd_check = 0

async def main():
    import websockets
    global last_ww_check, last_eq_check, last_cd_check

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        log.info("Created default scheduler_config.json")

    log.info("Scheduler v5.2: +timed_msg queue")

    ws = None
    for _ in range(60):
        try:
            ws = await websockets.connect(NAP_CAT_WS, close_timeout=5)
            log.info("Connected to NapCat")
            break
        except:
            await asyncio.sleep(2)
    if not ws:
        log.error("Cannot connect to NapCat")
        return

    ws_ref = [ws]
    state = load_state()

    while True:
        try:
            cfg = load_config()
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # ─── Weather ───
            wf_cfg = cfg.get("weather", {})
            if wf_cfg.get("enabled", True):
                if state.get("wf_sent_today") != today and now.hour >= wf_cfg.get("hour", 7) and _budget_ok("weather", state):
                    fc = await weather_forecast()
                    if fc and wf_cfg.get("groups"):
                        all_ok = True
                        for gid in wf_cfg["groups"]:
                            ok = await send_with_retry(ws_ref, gid, fc)
                            if not ok and gid not in GONE_GROUPS:
                                all_ok = False
                        if all_ok:
                            state["wf_sent_today"] = today
                            save_state(state)
                            log.info("Weather confirmed sent to %s", wf_cfg["groups"])
                        else:
                            log.warning("Weather: some groups failed after retries, state NOT saved")
                            _record_failure("weather", state)

            # ─── News ───
            news_cfg = cfg.get("news", {})
            if news_cfg.get("enabled", True):
                if state.get("news_sent_today") != today and now.hour >= news_cfg.get("hour", 18) and _budget_ok("news", state):
                    news = await fetch_news()
                    if news and news_cfg.get("groups"):
                        all_ok = True
                        for gid in news_cfg["groups"]:
                            ok = await send_with_retry(ws_ref, gid, news)
                            if not ok and gid not in GONE_GROUPS:
                                all_ok = False
                        if all_ok:
                            state["news_sent_today"] = today
                            save_state(state)
                            log.info("News confirmed sent to %s", news_cfg["groups"])
                        else:
                            log.warning("News: some groups failed after retries, state NOT saved")
                            _record_failure("news", state)


            #
            # --- Daily Active Greetings ---
            grt_cfg = cfg.get("daily_greetings", {})
            if grt_cfg.get("enabled", False):
                grt_today = state.get("grt_sent_today", "")
                if grt_today != today:
                    for msg in grt_cfg.get("messages", []):
                        msg_time = msg.get("time", "")
                        if msg_time:
                            h, m = map(int, msg_time.split(":"))
                            if (now.hour > h) or (now.hour == h and now.minute >= m):
                                text = msg.get("text", "")
                                if text:
                                    grp_gids = grt_cfg.get("groups", [])
                                    if not grp_gids:  # fallback: use chat_groups from group_config
                                        import json as _j; _gc = _j.load(open("/opt/xiaonai/data/group_config.json"))
                                        grp_gids = _gc.get("chat_groups", [])
                                    for gid in grp_gids:
                                        await send_with_retry(ws_ref, gid, text)
                                        await asyncio.sleep(2)
                                    state["grt_sent_today"] = today
                                    save_state(state)
                                    log.info("Greetings: sent for %s", today)
                                    break
            # ─── Campus Daily (2-min polling) ───
            cd_cfg = cfg.get("campus_daily", {})
            if cd_cfg.get("enabled", True):
                interval = cd_cfg.get("interval_min", 2) * 60
                if time.time() - last_cd_check >= interval:
                    last_cd_check = time.time()
                    if _budget_ok("campus_daily", state, CAMPUS_DAILY_FAILURE_BUDGET):
                        notices = await fetch_campus_daily()
                        if notices and cd_cfg.get("groups"):
                            for gid in cd_cfg["groups"]:
                                ok = await send_with_retry(ws_ref, gid, notices)
                                if ok:
                                    log.info("Campus daily sent to %s: %d chars", gid, len(notices))
                                elif gid not in GONE_GROUPS:
                                    log.warning("Campus daily FAILED to %s", gid)
                                    _record_failure("campus_daily", state, CAMPUS_DAILY_FAILURE_BUDGET)
                        elif notices is None:
                            log.warning("Campus daily: fetch failed, will retry")
                            _record_failure("campus_daily", state, CAMPUS_DAILY_FAILURE_BUDGET)
                        # notices == "" means no new notices — normal, skip silently
            # --- Exam countdown push ---
            if now.hour >= 7:
                if state.get("exam_pushed_today") != today:
                    await exam_countdown_push(ws_ref, cfg)
                    state["exam_pushed_today"] = today
                    save_state(state)

            # ─── Export files cleanup (daily at 3:00 AM) ───
            if state.get("cleanup_run_today") != today and now.hour >= 3:
                cleanup_all_redundant()
                state["cleanup_run_today"] = today
                save_state(state)

            # ─── Weather warning ───
            ww_cfg = cfg.get("weather_warning", {})
            if ww_cfg.get("enabled", True):
                interval = ww_cfg.get("interval_min", 10) * 60
                if time.time() - last_ww_check >= interval:
                    last_ww_check = time.time()
                    await check_weather_warning(ws_ref, cfg)

            # ─── Earthquake ───
            eq_cfg = cfg.get("earthquake", {})
            if eq_cfg.get("enabled", True):
                interval = eq_cfg.get("interval_min", 2) * 60
                if time.time() - last_eq_check >= interval:
                    last_eq_check = time.time()
                    await check_earthquake(ws_ref, cfg)

            # ─── One-shot timed messages ───
            await check_timed_messages(ws_ref)

        except Exception as e:
            log.error("Loop: %s", e)
            log.error(traceback.format_exc())

        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
