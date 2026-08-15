"""武汉气象预警 — QWeather Alert API v1，仅武汉本地预警。"""



import asyncio

import json

from datetime import datetime, timezone, timedelta

from pathlib import Path

from typing import Optional



import httpx

from nonebot import get_bot, get_driver, require

from nonebot import on_command

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent



require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402



DATA_DIR = Path("/opt/xiaonai/data")

CONFIG_FILE = DATA_DIR / "weather_warning_config.json"

CACHE_FILE = DATA_DIR / "weather_warning_cache.json"

INIT_SENTINEL = DATA_DIR / ".ww_init_done"

EXPIRY_WINDOW_HOURS = 3



SEVERITY_ICON = {"blue": "🔵", "yellow": "🟡", "orange": "🟠", "red": "🔴"}



DEFAULT_CONFIG = {"enabled": True, "groups": [], "interval": 600}





def _load_config() -> dict:

    if CONFIG_FILE.exists():

        try:

            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

        except Exception:

            pass

    return dict(DEFAULT_CONFIG)





def _save_config(cfg: dict) -> None:

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")





def _load_cache() -> set:

    if CACHE_FILE.exists():

        try:

            return set(json.loads(CACHE_FILE.read_text(encoding="utf-8")))

        except Exception:

            pass

    return set()





def _save_cache(ids: set) -> None:

    trimmed = sorted(ids)[-500:]

    CACHE_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")





async def fetch_wuhan_alerts(api_key: str, api_host: str) -> list[dict]:

    """获取武汉本地天气预警"""

    try:

        base = f"https://{api_host}" if api_host else "https://devapi.qweather.com"

        url = f"{base}/weatheralert/v1/current/30.59/114.30"

        async with httpx.AsyncClient(timeout=10) as c:

            r = await c.get(url, params={"key": api_key})

            d = r.json()

        all_alerts = d.get("alerts", [])

        # 只保留武汉本地的预警

        return [a for a in all_alerts

                if "武汉" in (a.get("headline", "") or "")

                or "武汉" in (a.get("senderName", "") or "")]

    except Exception as e:

        print(f"[WW] fetch error: {e}")

        return []





def format_alert(a: dict) -> str:

    color = a.get("color", {}).get("code", "")

    icon = SEVERITY_ICON.get(color, "⚠️")

    title = a.get("headline", "气象预警")

    desc = (a.get("description", "") or "")[:200]

    inst = (a.get("instruction", "") or "")[:150]

    expiry_raw = a.get("expireTime", "") or ""

    if expiry_raw:

        try:

            utc_dt = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))

            bj_dt = utc_dt + timedelta(hours=8)

            expiry = bj_dt.strftime("%Y-%m-%d %H:%M")

        except Exception:

            expiry = expiry_raw.replace("T", " ").replace("Z", " UTC")

    else:

        expiry = ""
    msg = f"{icon} 武汉气象预警\n"

    msg += f"━━━━━━━━━━━━━━\n"

    msg += f"📌 {title}\n"

    msg += f"📋 {desc}\n"

    if inst:

        msg += f"💡 {inst}\n"

    if expiry:

        msg += f"⏱ 有效期至：{expiry}\n"

    msg += f"━━━━━━━━━━━━━━"

    return msg





async def check_weather_warning():

    cfg = _load_config()

    if not cfg.get("enabled", True):

        return

    groups = cfg.get("groups", [])

    if not groups:

        return



    from config import bot_config

    api_key = bot_config.qw_api_key

    api_host = bot_config.qw_api_host

    if not api_key:

        print("[WW] no API key")

        return



    alerts = await fetch_wuhan_alerts(api_key, api_host)

    if not alerts:

        return



    seen = _load_cache()

    now = datetime.now(timezone.utc)

    cutoff = now - timedelta(hours=EXPIRY_WINDOW_HOURS)

    first_run = not INIT_SENTINEL.exists()



    new_ones = []

    for a in alerts:

        aid = a.get("id", "")

        if not aid:

            continue



        # 部署哨兵：首次启动预填所有ID，不推送

        if first_run:

            seen.add(aid)

            continue



        if aid in seen:

            continue

        seen.add(aid)



        # 时效检查1：expireTime已过 → 过期

        expire_str = a.get("expireTime", "")

        expired = False

        if expire_str:

            try:

                et = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))

                if et <= now:

                    expired = True

            except (ValueError, TypeError):

                pass



        # 时效检查2：pubTime太久远 → 不推

        pub_str = a.get("pubTime", "") or a.get("sendTime", "")

        if pub_str and not expired:

            try:

                pt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))

                if pt < cutoff:

                    expired = True

            except (ValueError, TypeError):

                pass



        if not expired:

            new_ones.append(a)



    # 标记首次完成

    if first_run:

        INIT_SENTINEL.parent.mkdir(parents=True, exist_ok=True)

        INIT_SENTINEL.write_text("1")

        _save_cache(seen)

        print(f"[WW] first-run init: cached {len(seen)} alerts")

        return



    if not new_ones:

        return



    _save_cache(seen)



    try:

        bot = get_bot()

    except Exception:

        print("[WW] no bot")

        return



    for a in new_ones:

        text = format_alert(a)

        for gid in groups:

            try:

                await bot.send_group_msg(group_id=int(gid), message=text)

                await asyncio.sleep(0.5)

            except Exception as e:

                print(f"[WW] push fail: {e}")





# ---- Commands ----



ww_sub = on_command("气象订阅", priority=50, block=True)

ww_unsub = on_command("气象退订", priority=50, block=True)

ww_stat = on_command("气象状态", priority=50, block=True)





@ww_sub.handle()

async def _(bot: Bot, event: GroupMessageEvent):

    gid = str(event.group_id)

    cfg = _load_config()

    groups = cfg.setdefault("groups", [])

    if gid not in groups:

        groups.append(gid)

        cfg["enabled"] = True

        _save_config(cfg)

        _ensure_job(cfg)

        await ww_sub.finish("✅ 本群已开启武汉气象预警！\n仅推送武汉市本地预警信息")

    else:

        await ww_sub.finish("ℹ️ 已订阅气象预警。")





@ww_unsub.handle()

async def _(bot: Bot, event: GroupMessageEvent):

    gid = str(event.group_id)

    cfg = _load_config()

    groups = cfg.get("groups", [])

    if gid in groups:

        groups.remove(gid)

        _save_config(cfg)

        if not groups:

            _stop_job()

        await ww_unsub.finish("✅ 已关闭气象预警。")

    else:

        await ww_unsub.finish("ℹ️ 未订阅气象预警。")





@ww_stat.handle()

async def _(bot: Bot, event: GroupMessageEvent):

    cfg = _load_config()

    subscribed = str(event.group_id) in cfg.get("groups", [])

    msg = (

        f"🌤 武汉气象预警\n"

        f"━━━━━━━━━\n"

        f"本群：{'✅ 已订阅' if subscribed else '❌ 未订阅'}\n"

        f"推送群数：{len(cfg.get('groups',[]))}\n"

        f"━━━━━━━━━\n"

        f"💡 气象订阅 — 开启\n"

        f"💡 气象退订 — 关闭"

    )

    await ww_stat.finish(msg)





def _ensure_job(cfg: dict):

    interval = cfg.get("interval", 600)

    old = scheduler.get_job("ww_check")

    if old:

        old.remove()

    scheduler.add_job(check_weather_warning, "interval", seconds=interval, id="ww_check", replace_existing=True)





def _stop_job():

    old = scheduler.get_job("ww_check")

    if old:

        old.remove()





driver = get_driver()





@driver.on_startup

async def _():

    cfg = _load_config()

    from config import bot_config

    if cfg.get("groups") and bot_config.qw_api_key:

        _ensure_job(cfg)

        print(f"[WW] started, {len(cfg['groups'])} groups")

    else:

        print("[WW] idle")

