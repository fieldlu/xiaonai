"""地震预警插件 v4 — 时效性优先 + 区域分级 + 外国过滤。"""

import asyncio
import json
import math
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
CONFIG_FILE = DATA_DIR / "earthquake_config.json"
CACHE_FILE = DATA_DIR / "earthquake_cache.json"
EQ_API = "https://api.wolfx.jp/cenc_eqlist.json"
POLL_INTERVAL = 30  # 2分钟轮询一次

# 武汉坐标
WUHAN_LAT, WUHAN_LON = 30.59, 114.30

# 分级阈值（用户规格）
THRESHOLDS = [
    (50, 3.0, "urban"),    # 武汉市区50km内 M>=3.0
    (200, 3.0, "wuhan"),   # 武汉圈200km内 M>=3.0
    (800, 4.0, "central"), # 华中800km内 M>=4.0
]

# 全国中国境内 M>=4.5（非外国）
CHINA_MAG = 4.5

# 中国省份/城市关键词（用于判断是否中国境内）
CHINA_KW = [
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西", "海南",
    "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
    "青海", "宁夏", "新疆", "内蒙古",
    "香港", "澳门",
]

# 外国名称关键词（排除）
OCEAN_KW = [
    "海域", "沿海",
]

FOREIGN_KW = [
    "日本", "印尼", "菲律宾", "墨西哥", "智利",
    "土耳其", "伊朗", "阿富汗", "缅甸", "印度",
    "蒙古", "哈萨克", "吉尔吉斯", "塔吉克",
    "尼泊尔", "不丹", "孟加拉", "越南", "老挝",
    "柬埔寨", "泰国", "马来西亚", "新加坡",
    "韩国", "朝鲜", "澳大利亚", "新西兰",
    "加拿大", "美国", "巴西", "阿根廷",
    "英国", "法国", "德国", "意大利", "西班牙",
    "俄罗斯", "埃及", "南非", "肯尼亚",
    "太平洋", "大西洋", "印度洋",
]

# 中国地理包围盒（粗略）
CHINA_BBOX = (18.0, 54.0, 73.0, 135.0)
# 台湾
TAIWAN_KW = ["台湾"]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def is_in_china(location: str, lat: float, lon: float) -> bool:
    """判断地震是否在中国境内（且非海域）"""
    # 海洋地震过滤
    for kw in OCEAN_KW:
        if kw in location:
            return False
    # 检查外国关键词（排除）
    for kw in FOREIGN_KW:
        if kw in location:
            return False
    # 中国关键词
    for kw in CHINA_KW + TAIWAN_KW:
        if kw in location:
            return True
    # 包围盒兜底
    if CHINA_BBOX[0] <= lat <= CHINA_BBOX[1] and CHINA_BBOX[2] <= lon <= CHINA_BBOX[3]:
        return True
    return False


def evaluate(eq: dict) -> tuple:
    """评估地震。返回 (是否推送, 标签, 距武汉km)"""
    try:
        mag = float(eq.get("magnitude", 0))
        lat = float(eq.get("latitude", 0))
        lon = float(eq.get("longitude", 0))
    except (ValueError, TypeError):
        return False, "", 0

    loc = eq.get("location") or eq.get("placeName") or ""

    # 外国过滤
    if not is_in_china(loc, lat, lon):
        return False, "", 0

    dist = haversine(WUHAN_LAT, WUHAN_LON, lat, lon)

    # 武汉圈
    if dist <= THRESHOLDS[0][0]:
        return mag >= THRESHOLDS[0][1], THRESHOLDS[0][2], dist
    # 华中
    if dist <= THRESHOLDS[1][0]:
        return mag >= THRESHOLDS[1][1], THRESHOLDS[1][2], dist
    # 全国
    return mag >= CHINA_MAG, "china", dist


def severity_label(mag: float) -> str:
    if mag >= 7.0: return "🔴 强烈地震"
    if mag >= 6.0: return "🟠 强震"
    if mag >= 5.0: return "🟡 中强震"
    if mag >= 4.0: return "🟢 有感地震"
    if mag >= 3.0: return "⚪ 轻震"
    return "⚫ 微震"


def format_eq(eq: dict, tag: str, dist: float) -> str:
    mag = float(eq.get("magnitude", 0))
    label = severity_label(mag)
    loc = eq.get("location") or eq.get("placeName") or "未知"
    depth = eq.get("depth", "?")
    lat = eq.get("latitude", "?")
    lon = eq.get("longitude", "?")
    ot = eq.get("time", "?")
    rt = eq.get("ReportTime", "?")

    tag_map = {
        "urban": f"🚨 武汉市区（距{dist:.0f}km）",
        "wuhan": f"📍 武汉圈（距{dist:.0f}km）",
        "central": f"📍 华中（距{dist:.0f}km）",
        "china": "🌐 全国",
    }
    tag_text = tag_map.get(tag, "")

    return (
        f"{label}\n"
        f"{tag_text}\n"
        f"━━━━━━━━━━━━\n"
        f"📍 震中：{loc}\n"
        f"📊 震级：M {mag}\n"
        f"📏 深度：{depth} km\n"
        f"🌐 {lat}°N, {lon}°E\n"
        f"🕐 发震：{ot}\n"
        f"⏱ 报出：{rt}\n"
        f"━━━━━━━━━━━━\n"
        f"💡 保持冷静，注意安全"
    )


# ---- 配置持久化 ----

DEFAULT_CONFIG = {
    "enabled": True,
    "groups": [],
}

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
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(ids)[-3000:]
    CACHE_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


# ---- 数据获取 ----

async def fetch_eq_list() -> Optional[list[dict]]:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(EQ_API)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                return [v for k, v in data.items() if k.startswith("No")]
            return data if isinstance(data, list) else None
    except Exception as e:
        print(f"[EQ] fetch error: {e}")
        return None


# ---- 轮询 ----

async def check_earthquake():
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return
    groups = cfg.get("groups", [])
    if not groups:
        return

    items = await fetch_eq_list()
    if not items:
        return

    seen = _load_cache()
    now = datetime.now(timezone.utc)

    # 时效过滤：只处理最近2小时内的地震
    cutoff = now - timedelta(hours=2)
    INIT_SENTINEL_FILE = DATA_DIR / ".eq_init_done"

    new_ones = []
    first_run = not INIT_SENTINEL_FILE.exists()

    for eq in items:
        eid = eq.get("EventID", "")
        if not eid:
            continue

        # 部署哨兵：首次启动预填所有EventID，不推送
        if first_run:
            seen.add(eid)
            continue

        if eid in seen:
            continue
        seen.add(eid)

        # 时效检查
        try:
            eq_time_str = eq.get("time") or eq.get("ReportTime", "")
            if eq_time_str:
                eq_time = datetime.strptime(eq_time_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if eq_time < cutoff:
                    continue  # 太旧了，跳过
        except (ValueError, IndexError):
            pass

        ok, tag, dist = evaluate(eq)
        if ok:
            new_ones.append((eq, tag, dist))

    # 标记首次完成
    if first_run:
        INIT_SENTINEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        INIT_SENTINEL_FILE.write_text("1")
        _save_cache(seen)
        print(f"[EQ] first-run init: cached {len(seen)} events")
        return

    if not new_ones:
        return

    _save_cache(seen)

    try:
        bot = get_bot()
    except Exception:
        print("[EQ] no bot")
        return

    for eq, tag, dist in new_ones:
        text = format_eq(eq, tag, dist)
        print(f"[EQ] pushing: {eq.get('EventID','')} mag={eq.get('magnitude','')} tag={tag}")
        for gid in groups:
            try:
                await bot.send_group_msg(group_id=int(gid), message=text)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[EQ] push to {gid} failed: {e}")
# ---- 命令 ----

eq_sub = on_command("地震订阅", priority=50, block=True)
eq_unsub = on_command("地震退订", priority=50, block=True)
eq_stat = on_command("地震状态", priority=50, block=True)


@eq_sub.handle()
async def _(bot: Bot, event):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
    is_grp = isinstance(event, GroupMessageEvent)
    tid = str(event.group_id if is_grp else event.user_id)
    cfg = _load_config()
    groups = cfg.setdefault("groups", [])
    if tid not in groups:
        groups.append(tid)
        _save_config(cfg)
        _ensure_job(cfg)
        await eq_sub.finish(
            "✅ 本群已开启地震预警！\n"
            "📍 武汉圈200km M≥3.0\n"
            "📍 华中800km M≥4.0\n"
            "🌐 全国 M≥4.5（仅中国）\n"
            "⏱ 仅推送2小时内最新地震\n"
            "💡 发送「地震状态」查看详情"
        )
    else:
        await eq_sub.finish("ℹ️ 已订阅地震预警。")


@eq_unsub.handle()
async def _(bot: Bot, event):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
    is_grp = isinstance(event, GroupMessageEvent)
    tid = str(event.group_id if is_grp else event.user_id)
    cfg = _load_config()
    groups = cfg.get("groups", [])
    if tid in groups:
        groups.remove(tid)
        _save_config(cfg)
        if not groups:
            _stop_job()
        await eq_unsub.finish("✅ 地震预警已关闭。")
    else:
        await eq_unsub.finish("ℹ️ 未订阅地震预警。")


@eq_stat.handle()
async def _(bot: Bot, event):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
    is_grp = isinstance(event, GroupMessageEvent)
    tid = str(event.group_id if is_grp else event.user_id)
    cfg = _load_config()
    subscribed = tid in cfg.get("groups", [])
    total = len(cfg.get("groups", []))

    msg = (
        f"📡 地震预警\n"
        f"━━━━━━━━━\n"
        f"状态：🟢 运行中\n"
        f"本群：{'✅ 已订阅' if subscribed else '❌ 未订阅'}\n"
        f"推送群数：{total}\n"
        f"━━━━━━━━━\n"
        f"📍 武汉圈200km M≥3.0\n"
        f"📍 华中800km M≥4.0\n"
        f"🌐 全国 M≥4.5（仅中国）\n"
        f"⏱ 2小时时效窗口\n"
        f"━━━━━━━━━\n"
        f"数据源：中国地震台网\n"
        f"💡 地震订阅 — 开启"
    )
    await eq_stat.finish(msg)


# ---- 任务管理 ----

def _ensure_job(cfg: dict):
    old = scheduler.get_job("eq_check")
    if old:
        old.remove()
    scheduler.add_job(
        check_earthquake, "interval", seconds=POLL_INTERVAL,
        id="eq_check", replace_existing=True,
    )

def _stop_job():
    old = scheduler.get_job("eq_check")
    if old:
        old.remove()


# ---- 生命周期 ----

driver = get_driver()

@driver.on_startup
async def _():
    cfg = _load_config()
    if cfg.get("groups"):
        _ensure_job(cfg)
        print(f"[EQ] v4 started, {len(cfg['groups'])} groups, interval={POLL_INTERVAL}s")
    else:
        print("[EQ] v4 idle (no groups)")
