"""定时任务：动态调度 + 多源新闻 + 可靠提醒。"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from nonebot import get_bot, get_driver, require

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from config import bot_config
from src.llm.tools_impl import get_weather

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", "data"))
NEWS_CONFIG = DATA_DIR / "news_config.json"
NEWS_CACHE = DATA_DIR / "news_cache.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "schedule": ["18:00"],
    "count": 10,
    "recipients": [],
    "groups": [],
    "custom_message": "",
    "news_only": True,
}


def _load_config() -> dict:
    if NEWS_CONFIG.exists():
        try:
            return json.loads(NEWS_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(cfg: dict) -> None:
    NEWS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_news_config() -> dict:
    return _load_config()


def update_news_config(**kwargs) -> dict:
    cfg = _load_config()
    cfg.update(kwargs)
    _save_config(cfg)
    _reschedule_jobs(cfg)
    return cfg


# ======== 动态调度 ========

def _reschedule_jobs(cfg: dict):
    """根据配置重新设定 cron 任务。"""
    times = cfg.get("schedule", ["08:00", "18:00"])
    for i, t in enumerate(times[:4]):  # 最多 4 个时间点
        try:
            h, m = map(int, t.split(":"))
        except Exception:
            continue
        job_id = f"news_dynamic_{i}"
        old = scheduler.get_job(job_id)
        if old:
            old.remove()
        scheduler.add_job(
            _dynamic_push, "cron", hour=h, minute=m, id=job_id,
            replace_existing=True,
        )
    # 清理多余的旧任务
    for i in range(len(times), 4):
        job = scheduler.get_job(f"news_dynamic_{i}")
        if job:
            job.remove()


async def _dynamic_push():
    """定时推送：每次到点都发，不检查去重。"""
    cfg = _load_config()
    if cfg.get("enabled", True):
        await run_news_push()


# ======== 新闻抓取 ========

def _decode_response(r, declared_enc: str) -> str:
    """Auto-detect encoding to avoid garbled Chinese text."""
    raw_bytes = r.content
    # Try declared encoding first, then common Chinese encodings
    for try_enc in [declared_enc, 'utf-8', 'gbk', 'gb2312', 'gb18030']:
        try:
            decoded = raw_bytes.decode(try_enc)
            if '�' not in decoded:  # No replacement characters
                return decoded
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode('utf-8', errors='replace')


async def fetch_raw_news(count: int = 10) -> list[str]:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    sent = set()
    if NEWS_CACHE.exists():
        try:
            d = json.loads(NEWS_CACHE.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                updated = d.get('updated', '')
                if updated:
                    try:
                        age = datetime.now() - datetime.fromisoformat(updated[:19])
                        if age > timedelta(hours=24):
                            sent = set()
                            print(f'[scheduler] Cache expired ({age.days}d {age.seconds//3600}h), clearing')
                        else:
                            sent = set(d.get('titles', []))
                    except:
                        sent = set(d.get('titles', []))
                else:
                    sent = set()
            else:
                sent = set(d)
        except: pass
        if not sent:
            NEWS_CACHE.unlink(missing_ok=True)
    seen = set(); items = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as cli:
        try:
            r = await cli.get('https://top.baidu.com/board?tab=realtime')
            if r.status_code == 200:
                _pat = chr(123) + r'[^{}]*"word"[^{}]*' + chr(125)
                for b in re.findall(_pat, r.text):
                    try:
                        d2 = json.loads(b)
                        w = d2.get('word','').strip()
                        desc = d2.get('desc','').strip()[:300]
                        if 5 < len(w) < 60 and w not in seen and w not in sent:
                            seen.add(w)
                            if desc:
                                items.append(w + '||DESC||' + desc)
                            else:
                                items.append(w)
                            if len(items) >= count: break
                    except: pass
        except: pass
    if items:
        sent.update(items)
        import json as _json
        NEWS_CACHE.write_text(_json.dumps({'titles': list(sent)[-300:], 'updated': str(datetime.now())}, ensure_ascii=False), encoding='utf-8')
    print(f'[scheduler] Fetch: {len(items)} items')
    return items[:count]

async def transform_news(news_titles: list[str]) -> list[str]:
    '''Summarize news via shared _summarize_news - same output as get_news.'''
    if not news_titles: return []
    from src.llm.tools_impl import _summarize_news
    articles = ""
    for item in news_titles[:8]:
        if '||DESC||' in item:
            t, desc = item.split('||DESC||', 1)
            articles += f"Article: {t}\nContent: {desc}\n\n"
        else:
            articles += f"Title: {item}\n\n"
    if articles:
        result = await _summarize_news(articles)
        if result:
            return [l.strip() for l in result.split(chr(10)) if l.strip()]
    return [item.split('||DESC||')[0] if '||DESC||' in item else item for item in news_titles[:5]]

async def run_news_push():
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return

    now = datetime.now()
    h = now.hour
    if h < 12:
        greeting = f"早安~ {now.month}月{now.day}日，小奈给同学带了今天的新闻呢 (๑•̀ㅂ•́)و✧"
    elif h < 18:
        greeting = f"下午好~ {now.month}月{now.day}日，小奈给同学带了今天的新闻呢 (๑•̀ㅂ•́)و✧"
    else:
        greeting = f"晚上好呀~ {now.month}月{now.day}日啦，新闻整理好啦 (◍•ᴗ•◍)"

    raw = await fetch_raw_news(cfg.get("count", 10))
    if not raw:
        print("[scheduler] No news fetched")
        return

    transformed = await transform_news(raw)
    news_text = "\n".join(transformed)
    custom = cfg.get("custom_message", "")
    message = f"{custom}\n\n[News] {greeting}\n\n{news_text}" if custom else f"[News] {greeting}\n\n{news_text}"

    for qq in cfg.get("recipients", []):
        await _push_user(qq, message)
    for gid in cfg.get("groups", []):
        await _push_group(gid, message)

    print(f"[scheduler] Pushed to {len(cfg.get('recipients', []))}u + {len(cfg.get('groups', []))}g")


NL = chr(10)

async def run_news_push_for_user(target: int, is_group: bool = False):
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return
    now = datetime.now()
    h = now.hour
    if h < 12:
        greeting = "早~ " + now.strftime("%m月%d日") + "，小奈给同学带了今天的新闻呢 (o'v'o)"
    elif h < 18:
        greeting = "下午好~ " + now.strftime("%m月%d日") + "，小奈给同学带了今天的新闻呢 (o'v'o)"
    else:
        greeting = "晚好呀~ " + now.strftime("%m月%d日") + "啦，新闻整理好啦 (=^w^=)"
    raw = await fetch_raw_news(cfg.get("count", 10))
    if not raw:
        msg = "诶？今天好像没什么特别的新闻呢..."
        if is_group:
            await _push_group(target, msg)
        else:
            await _push_user(target, msg)
        return
    transformed = await transform_news(raw)
    news_text = NL.join(transformed)
    custom = cfg.get("custom_message", "")
    if custom:
        message = custom + NL + NL + "[News] " + greeting + NL + NL + news_text
    else:
        message = "[News] " + greeting + NL + NL + news_text
    if is_group:
        await _push_group(target, message)
    else:
        await _push_user(target, message)
    print("[scheduler] Push to " + ("group" if is_group else "user") + " " + str(target))


async def _push_user(qq: int, msg: str):
    try:
        bot = get_bot()
        if bot:
            await bot.send_private_msg(user_id=qq, message=msg)
    except Exception as e:
        print(f"[scheduler] push user {qq}: {e}")


async def _push_group(gid: int, msg: str, retry: int = 5):
    for attempt in range(retry):
        try:
            bot = get_bot()
            if not bot:
                raise RuntimeError("bot not ready")
            await bot.send_group_msg(group_id=gid, message=msg)
            return
        except Exception as e:
            if attempt < retry - 1:
                print(f"[scheduler] push group {gid} attempt {attempt+1} failed: {e}, retrying...")
                await asyncio.sleep(3)
            else:
                print(f"[scheduler] push group {gid} failed after {retry} attempts: {e}")


# ======== 闹钟 & 提醒 ========

ALARMS_FILE = DATA_DIR / "alarms.json"


async def schedule_reminder(target: int, message: str, delay_seconds: int, is_group: bool = False):
    run_at = datetime.now() + timedelta(seconds=delay_seconds)
    job_id = f"remind_{target}_{int(run_at.timestamp())}"
    scheduler.add_job(
        _send_reminder, "date", run_date=run_at, id=job_id,
        args=[target, message, is_group],
    )


def schedule_alarm(user_id: int, message: str, time_str: str, is_group: bool = False) -> str:
    """添加闹钟。time_str 格式: 'HH:MM' 或 'YYYY-MM-DD HH:MM'。返回闹钟 ID。"""
    now = datetime.now()
    try:
        if " " in time_str:
            run_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        else:
            h, m = map(int, time_str.split(":"))
            run_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
    except Exception:
        return ""

    job_id = f"alarm_{user_id}_{int(run_at.timestamp())}"
    scheduler.add_job(
        _send_alarm, "date", run_date=run_at, id=job_id,
        args=[job_id, user_id, message, is_group],
    )
    # 保存到文件
    alarms = _load_alarms()
    alarms.append({
        "id": job_id, "user_id": user_id, "message": message,
        "time": run_at.isoformat(), "is_group": is_group,
    })
    _save_alarms(alarms)
    return job_id


def cancel_alarm(alarm_id: str) -> bool:
    """取消闹钟。支持前缀匹配（LLM可能截断ID）。"""
    job = scheduler.get_job(alarm_id)
    if job:
        job.remove()
    else:
        for j in scheduler.get_jobs():
            if j.id.startswith(alarm_id):
                j.remove()
                break
    alarms = [a for a in _load_alarms() if not a["id"].startswith(alarm_id)]
    _save_alarms(alarms)
    return True


def list_alarms(user_id: int = 0) -> list[dict]:
    """列出闹钟。user_id=0 列出全部。"""
    alarms = _load_alarms()
    if user_id:
        alarms = [a for a in alarms if a["user_id"] == user_id]
    return alarms


def _load_alarms() -> list:
    if ALARMS_FILE.exists():
        try:
            return json.loads(ALARMS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_alarms(alarms: list) -> None:
    ALARMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALARMS_FILE.write_text(json.dumps(alarms, ensure_ascii=False, indent=2), encoding="utf-8")


async def _send_reminder(target: int, message: str, is_group: bool):
    await _do_send(target, message, is_group)


async def _send_alarm(job_id: str, target: int, message: str, is_group: bool):
    print(f"[alarm] Firing {job_id[:20]}... target={target} is_group={is_group} msg={message[:30]}")
    await _do_send(target, f"⏰ 闹钟响了~\n{message}", is_group)
    # 完成后自动删除
    alarms = [a for a in _load_alarms() if a["id"] != job_id]
    _save_alarms(alarms)
    print(f"[alarm] Cleaned up {job_id[:20]}, {len(alarms)} remaining")


async def _do_send(target: int, message: str, is_group: bool):
    try:
        bot = get_bot()
        if is_group:
            await bot.send_group_msg(group_id=target, message=message)
        else:
            await bot.send_private_msg(user_id=target, message=message)
        print(f"[scheduler] Sent to {target}")
    except Exception as e:
        print(f"[scheduler] Send failed: {e}")


DIARY_DIR = DATA_DIR / "diary"


async def _generate_diary():
    '''APScheduler cron job — fires daily at 23:59. Survives bot restarts.'''
    today = datetime.now().strftime("%Y-%m-%d")
    diary_path = DIARY_DIR / f"{today}.json"
    if diary_path.exists():
        print(f"[diary] Already exists: {today}")
        return

    users_dir = DATA_DIR / "memory" / "users"
    user_summaries = []
    total_msgs = 0
    if users_dir.exists():
        for uf in sorted(users_dir.glob("*.json")):
            try:
                data = json.loads(uf.read_text(encoding="utf-8"))
                qq = data.get("user_id", uf.stem)
                nick = data.get("nickname", "")
                aff = data.get("affection", 50)
                msgs = data.get("msg_count", 0)
                total_msgs += msgs
                facts = [f["content"] for f in data.get("facts", [])[-5:]]
                aff_log = data.get("affection_log", [])[-3:]
                dims = data.get("dimensions", {})
                dim_events = data.get("affection_events", [])
                user_summaries.append({
                    "qq": qq,
                    "nickname": nick,
                    "affection": aff,
                    "dimensions": dims,
                    "msg_count": msgs,
                    "recent_facts": facts,
                    "recent_affection_changes": aff_log,
                    "affection_events_today": [
                        e for e in dim_events if e.get("time", "")[:10] == today
                    ],
                })
            except Exception as e:
                print(f"[diary] Error reading {uf}: {e}")

    affection_changes_today = []
    for u in user_summaries:
        for e in u.get("affection_events_today", []):
            affection_changes_today.append({
                "qq": u["qq"],
                "nickname": u["nickname"],
                "dimension": e.get("dimension", "affection"),
                "label": e.get("label", "好感度"),
                "delta": e["delta"],
                "reason": e["reason"],
            })

    entry = {
        "date": today,
        "generated": datetime.now().isoformat(),
        "user_count": len(user_summaries),
        "total_messages": total_msgs,
        "users": user_summaries,
        "affection_summary": {
            "total_changes": len(affection_changes_today),
            "changes": affection_changes_today,
            "notable": [c for c in affection_changes_today if abs(c["delta"]) >= 3],
        },
        "summary": f"今日与{len(user_summaries)}位用户互动，共{total_msgs}条消息。好感度变动{len(affection_changes_today)}次。",
    }
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    diary_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[diary] Diary saved: {today} ({len(user_summaries)} users, {total_msgs} msgs)")


# Register cron job at 23:59 daily
try:
    scheduler.add_job(
        _generate_diary, "cron", hour=23, minute=59, id="diary_daily",
        replace_existing=True,
    )
    print("[diary] Cron job registered at 23:59 daily")
except Exception as e:
    print(f"[diary] Failed to register cron: {e}")


# ======== 周报 ========

async def run_weekly_report():
    """每周日 22:00 生成好感度周报，仅推送给班长。"""

    users_dir = DATA_DIR / "memory" / "users"
    if not users_dir.exists():
        return

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    user_stats = []
    for fn in sorted(users_dir.glob("*.json")):
        user_id = int(fn.stem)
        try:
            data = json.loads(fn.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("msg_count", 0) == 0:
            continue
        history = data.get("dimension_history", [])
        week_history = [h for h in history if h.get("date", "") >= week_ago]
        if len(week_history) >= 2:
            delta = week_history[-1]["composite"] - week_history[0]["composite"]
        else:
            delta = 0
        user_stats.append({
            "user_id": user_id,
            "nickname": data.get("nickname", str(user_id)),
            "delta": round(delta, 1),
            "milestones_this_week": [
                m for m in data.get("milestones", [])
                if m.get("time", "")[:10] >= week_ago
            ],
        })

    if not user_stats:
        return

    user_stats.sort(key=lambda x: x["delta"], reverse=True)
    most_up = user_stats[0]
    most_down_candidates = [u for u in user_stats if u["delta"] < 0]
    most_down = most_down_candidates[-1] if most_down_candidates else None
    active_count = len([u for u in user_stats if abs(u["delta"]) > 0])
    new_count = len([u for u in user_stats if u["delta"] == 0])

    lines = [f"📊 小奈的关系周报 ({week_ago} ~ {datetime.now().strftime('%m.%d')})"]
    lines.append(f"\n 新认识 {new_count} 人，活跃 {active_count} 人")
    lines.append(f"\n 💕 本周最甜：{most_up['nickname']} (+{most_up['delta']})")
    if most_down and most_down["delta"] < -1:
        lines.append(f" 📉 慢慢走远：{most_down['nickname']} ({most_down['delta']})")

    for u in user_stats:
        for m in u["milestones_this_week"][:2]:
            lines.append(f" ⭐ {u['nickname']} — {m['text']}")

    report = "\n".join(lines)

    # 周报不推送，仅存档到日记
    print(f"[weekly] Report generated (not sent): {len(user_stats)} users")


try:
    scheduler.add_job(
        run_weekly_report, "cron", day_of_week="sun", hour=22, minute=0,
        id="weekly_report", replace_existing=True,
    )
    print("[weekly] Cron job registered at Sun 22:00")
except Exception as e:
    print(f"[weekly] Failed to register cron: {e}")


# ======== CAMPUS MORNING BRIEFING (via aTrust utun7) ========

CAMPUS_CACHE = DATA_DIR / "campus_cache.json"
_ATRUST_SRC_IP = "bot_config.atrust_ip"


def _atrust_client() -> httpx.AsyncClient:
    """Create httpx client bound to aTrust utun7 source IP for campus access."""
    import socket
    transport = httpx.AsyncHTTPTransport()

    orig_connect = socket.socket.connect

    def bound_connect(sock, addr):
        try:
            sock.bind((_ATRUST_SRC_IP, 0))
        except OSError:
            pass
        return orig_connect(sock, addr)

    socket.socket.connect = bound_connect
    try:
        return httpx.AsyncClient(timeout=15, transport=transport,
                                 headers={"User-Agent": "Mozilla/5.0"})
    finally:
        socket.socket.connect = orig_connect


async def _fetch_notices():
    notices = []
    try:
        async with _atrust_client() as c:
            r = await c.get("http://i.whut.edu.cn/xxtg/gztz_9764.shtml")
            r.encoding = "utf-8"
            seen = set()
            for m in re.finditer(r'<a[^>]*href="(\./[^"]*)"[^>]*title="([^"]*)"[^>]*>', r.text, re.DOTALL):
                href = m.group(1)
                title = m.group(2).strip()
                if href not in seen and len(title) > 10:
                    seen.add(href)
                    url = "http://i.whut.edu.cn/xxtg/" + href.lstrip("./")
                    notices.append({"title": title, "url": url})
    except Exception as e:
        print(f"[campus] notices fetch failed (VPN may need re-auth): {e}")
    return notices


async def _fetch_auto():
    """Fetch auto school news — via aTrust VPN (218.197.x.x is campus network)."""
    news = []
    try:
        async with _atrust_client() as c:
            r = await c.get("http://auto.whut.edu.cn/xwsc/")
            r.encoding = "utf-8"
            seen = set()
            for m in re.finditer(r'<a[^>]*href="(\./[^"]*)"[^>]*title="([^"]*)"[^>]*>', r.text, re.DOTALL):
                href = m.group(1)
                title = m.group(2).strip()
                if href not in seen and len(title) > 10 and "./202" in href:
                    seen.add(href)
                    url = "http://auto.whut.edu.cn/xwsc/" + href.lstrip("./")
                    news.append({"title": title, "url": url})
    except Exception as e:
        print(f"[campus] auto fetch failed: {e}")
    return news

def _fmt_campus(notices, auto_news):
    lines = []
    lines.append("🏫 Today Important Notices")
    for i in range(min(10, len(notices))):
        n = notices[i]
        lines.append(str(i+1) + ". " + n["title"] + chr(10) + "   " + n["url"])
    lines.append(chr(10) + "🔧 Auto School News")
    for i in range(min(2, len(auto_news))):
        a = auto_news[i]
        lines.append(str(i+1) + ". " + a["title"] + chr(10) + "   " + a["url"])
    return chr(10).join(lines)

async def run_campus_morning_push():
    notices = await _fetch_notices()
    auto = await _fetch_auto()
    sent = set()
    if CAMPUS_CACHE.exists():
        try:
            sent = set(json.loads(CAMPUS_CACHE.read_text(encoding="utf-8")))
        except: pass
    new_n = [n for n in notices if n["title"] not in sent]
    new_a = [a for a in auto if a["title"] not in sent]
    if not new_n and not new_a:
        return
    msg = _fmt_campus(new_n, new_a)
    for n in new_n: sent.add(n["title"])
    for a in new_a: sent.add(a["title"])
    CAMPUS_CACHE.write_text(json.dumps(list(sent)[-200:], ensure_ascii=False), encoding="utf-8")
    # Push to class group + admin
    weather_groups = _load_weather_config().get("groups", [])
    class_gid = weather_groups[0] if weather_groups else 0
    try:
        bot = get_bot()
        if class_gid:
            await bot.send_group_msg(group_id=class_gid, message=msg)
        print(f"[campus] Pushed to group {class_gid}")
    except Exception as e:
        print(f"[campus] Group: {e}")
    # 不推送给班长

@scheduler.scheduled_job("cron", hour=7, minute=30, id="campus_morning")
async def campus_job():
    cfg = _load_config()
    if cfg.get("campus_enabled", True):
        await run_campus_morning_push()

async def run_campus_push_manual(admin_only=True):
    notices = await _fetch_notices()
    auto = await _fetch_auto()
    sent = set()
    if CAMPUS_CACHE.exists():
        try:
            sent = set(json.loads(CAMPUS_CACHE.read_text(encoding="utf-8")))
        except: pass
    new_n = [n for n in notices if n["title"] not in sent]
    new_a = [a for a in auto if a["title"] not in sent]
    if not new_n and not new_a:
        return
    msg = _fmt_campus(new_n, new_a)
    bot = get_bot()
    admin_qq = bot_config.bot_admins[0] if bot_config.bot_admins else 0
    await bot.send_private_msg(user_id=admin_qq, message=msg)
    if not admin_only:
        try:
            weather_groups = _load_weather_config().get("groups", [])
            class_gid = weather_groups[0] if weather_groups else 0
            if class_gid:
                await get_bot().send_group_msg(group_id=class_gid, message=msg)
        except: pass
    for n in new_n: sent.add(n["title"])
    for a in new_a: sent.add(a["title"])
    CAMPUS_CACHE.write_text(json.dumps(list(sent)[-200:], ensure_ascii=False), encoding="utf-8")
    print(f"[campus] Manual push admin_only={admin_only}")

# ======== WEATHER PUSH ========

WEATHER_CONFIG = DATA_DIR / "weather_config.json"

DEFAULT_WEATHER_CONFIG = {
    "enabled": True,
    "city": "武汉",
    "recipients": [],
    "groups": [],
    "custom_message": "",
}


def _load_weather_config() -> dict:
    if WEATHER_CONFIG.exists():
        try:
            return json.loads(WEATHER_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(DEFAULT_WEATHER_CONFIG)


def _save_weather_config(cfg: dict) -> None:
    WEATHER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    WEATHER_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_weather_config() -> dict:
    return _load_weather_config()


def update_weather_config(**kwargs) -> dict:
    cfg = _load_weather_config()
    cfg.update(kwargs)
    _save_weather_config(cfg)
    return cfg


async def run_weather_push():
    cfg = _load_weather_config()
    if not cfg.get("enabled", True):
        return

    city = cfg.get("city", "武汉")
    now = datetime.now()
    greeting = f"☀️ 早安~ {now.month}月{now.day}日天气预报 (๑•̀ㅂ•́)و✧"

    weather_text = await get_weather(city, day_offset=0)
    # Strip __direct__: prefix (used for LLM tool routing, not for scheduled pushes)
    if weather_text.startswith("__direct__:"):
        weather_text = weather_text[len("__direct__:"):]
    custom = cfg.get("custom_message", "")
    message = f"{greeting}\n\n{weather_text}"
    if custom:
        message = f"{custom}\n{message}"

    for qq in cfg.get("recipients", []):
        await _push_user(qq, message)
    for gid in cfg.get("groups", []):
        await _push_group(gid, message)

    print(f"[weather] Pushed to {len(cfg.get('recipients', []))}u + {len(cfg.get('groups', []))}g")


async def run_weather_push_for_user(target: int, is_group: bool = False, city: str = "", day_offset: int = -1):
    cfg = _load_weather_config()
    if not cfg.get("enabled", True):
        return ""
    city = city or cfg.get("city", "武汉")
    weather_text = await get_weather(city, day_offset=day_offset)
    if weather_text.startswith("__direct__:"):
        weather_text = weather_text[len("__direct__:"):]
    custom = cfg.get("custom_message", "")
    message = f"{custom}\n\n{weather_text}" if custom else weather_text
    if is_group:
        await _push_group(target, message)
    else:
        await _push_user(target, message)
    print(f"[weather] Push to {'group' if is_group else 'user'} {target} city={city} day={day_offset}")
    return message


@scheduler.scheduled_job("cron", hour=6, minute=50, id="weather_morning")
async def weather_morning_job():
    cfg = _load_weather_config()
    if cfg.get("enabled", True):
        await run_weather_push()


# ======== 启动 ========

@get_driver().on_startup
async def _startup_push():
    cfg = _load_config()
    _reschedule_jobs(cfg)

    # Restore alarms from disk (APScheduler date jobs are lost on restart)
    alarms = _load_alarms()
    now = datetime.now()
    future_alarms = []
    for a in alarms:
        try:
            run_at = datetime.fromisoformat(a["time"])
            if run_at > now:
                scheduler.add_job(
                    _send_alarm, "date", run_date=run_at,
                    id=a["id"], args=[a["id"], a["user_id"], a["message"], a.get("is_group", False)],
                    replace_existing=True,
                )
                future_alarms.append(a)
                print(f"[alarm] Restored: {a['id'][:24]}... at {a['time']}")
            else:
                print(f"[alarm] Expired, removing: {a['id'][:24]}... ({a['time']})")
        except Exception as e:
            print(f"[alarm] Failed to restore {a.get('id','?')}: {e}")
    if len(future_alarms) != len(alarms):
        _save_alarms(future_alarms)
    print(f"[alarm] Restored {len(future_alarms)}/{len(alarms)} alarms")

    print("[scheduler] Startup hook complete - push deferred to bot connect")





# ============ Startup push on bot connect ============

@get_driver().on_bot_connect
async def _on_bot_connect(bot):
    """Startup news push disabled - only scheduled pushes (18:00)."""
    pass


# ======== L3 Cross-User Knowledge Merge (daily at 3:30) ========

@scheduler.scheduled_job("cron", hour=3, minute=30, id="l3_merge")
async def l3_merge_job():
    """Merge cross-user L2 knowledge into L3 global knowledge base."""
    try:
        from src.memory.kb import merge_cross_user
        result = merge_cross_user()
        print(f"[kb] L3 merge: {result}")
    except Exception as e:
        print(f"[kb] L3 merge failed: {e}")


# ======== News subscribe/unsubscribe (added by user request) ========
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent

news_sub = on_command("新闻订阅", priority=50, block=True)
news_unsub = on_command("新闻退订", priority=50, block=True)
news_stat = on_command("新闻状态", priority=50, block=True)

def _get_target(event, cfg):
    """Return (target_id, is_group, label) for the event."""
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
    if isinstance(event, GroupMessageEvent):
        return event.group_id, True, f"群 {event.group_id}"
    else:
        uid = event.user_id if hasattr(event, 'user_id') else event.self_id
        return uid, False, f"用户 {uid}"

@news_sub.handle()
async def _(bot: Bot, event):
    cfg2 = _load_config()
    tid, is_grp, label = _get_target(event, cfg2)
    if is_grp:
        if tid not in cfg2.get("groups", []):
            cfg2.setdefault("groups", []).append(tid)
            _save_config(cfg2)
            await news_sub.finish(f"[OK] 本群已订阅每日新闻推送 (18:00)")
        else:
            await news_sub.finish("[i] 本群已订阅，无需重复")
    else:
        if tid not in cfg2.get("recipients", []):
            cfg2.setdefault("recipients", []).append(tid)
            _save_config(cfg2)
            await news_sub.finish(f"[OK] 已订阅每日新闻推送 (18:00)~ 小奈每天会私聊给你发新闻哦")
        else:
            await news_sub.finish("[i] 你已订阅过了哦，小奈每天18:00会发新闻给你的~")

@news_unsub.handle()
async def _(bot: Bot, event):
    cfg2 = _load_config()
    tid, is_grp, label = _get_target(event, cfg2)
    if is_grp:
        if tid in cfg2.get("groups", []):
            cfg2["groups"].remove(tid)
            _save_config(cfg2)
            await news_unsub.finish("[OK] 已取消本群新闻推送")
        else:
            await news_unsub.finish("[i] 本群未订阅新闻")
    else:
        if tid in cfg2.get("recipients", []):
            cfg2["recipients"].remove(tid)
            _save_config(cfg2)
            await news_unsub.finish("[OK] 已取消新闻推送")
        else:
            await news_unsub.finish("[i] 你还没有订阅新闻哦~")

@news_stat.handle()
async def _(bot: Bot, event):
    cfg2 = _load_config()
    tid, is_grp, label = _get_target(event, cfg2)
    NL = chr(10)
    if is_grp:
        subscribed = tid in cfg2.get("groups", [])
        status = "YES" if subscribed else "NO"
        msg = f"[News] Status{NL}Group: {tid}{NL}Subscribed: {status}{NL}Total groups: {len(cfg2.get('groups', []))}{NL}Push: 18:00"
    else:
        subscribed = tid in cfg2.get("recipients", [])
        status = "YES" if subscribed else "NO"
        msg = f"[News] Status{NL}User: {tid}{NL}Subscribed: {status}{NL}Total users: {len(cfg2.get('recipients', []))}{NL}Push: 18:00"
    await news_stat.finish(msg)
