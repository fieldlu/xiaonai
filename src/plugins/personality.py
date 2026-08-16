"""小奈主动行为调度器 — 早安/晚安/想念/午后分享/群冒泡。（v1）"""

import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from nonebot import get_bot, get_driver, require

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", "data"))

ADMIN_QQ = ADMIN_QQ_PLACEHOLDER
# 群冒泡只发闲聊群（chat_groups）；班级群有导员/班主任，不主动冒泡
BUBBLE_GROUP = CHAT_GROUP_PLACEHOLDER

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


async def _get_eligible_users(min_affection: int = 40, active_since_hours: int = 48,
                              skip_admin: bool = True) -> list[dict]:
    """获取符合主动推送条件的用户列表。按好感度降序。skip_admin=True 跳过班长。"""
    users_dir = DATA_DIR / "memory" / "users"
    if not users_dir.exists():
        return []
    from src.memory.affection_dimensions import composite_score
    now = datetime.now()
    eligible = []
    for fn in sorted(users_dir.glob("*.json")):
        try:
            d = json.loads(fn.read_text(encoding="utf-8"))
        except Exception:
            continue
        uid = d.get("user_id", 0)
        if uid == 0:
            continue
        if skip_admin and uid == ADMIN_QQ:
            continue
        nickname = d.get("nickname", str(uid))
        dims = d.get("dimensions", {})
        comp = composite_score(dims)
        if comp < min_affection:
            continue
        last_seen = d.get("last_seen", "")
        if last_seen:
            try:
                ls = datetime.fromisoformat(last_seen)
                if (now - ls).total_seconds() / 3600 > active_since_hours:
                    continue
            except ValueError:
                continue
        eligible.append({"user_id": uid, "nickname": nickname, "affection": comp})
    eligible.sort(key=lambda x: x["affection"], reverse=True)
    return eligible[:8]  # 最多推8人


# ======== 防骚扰追踪器 ========

PROACTIVE_TRACKER = DATA_DIR / "proactive_tracker.json"
def _load_tracker() -> dict:
    if PROACTIVE_TRACKER.exists():
        try:
            return json.loads(PROACTIVE_TRACKER.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_tracker(t: dict) -> None:
    PROACTIVE_TRACKER.parent.mkdir(parents=True, exist_ok=True)
    PROACTIVE_TRACKER.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")


def _can_proactive(user_id: int) -> bool:
    """检查是否可以向此用户发主动消息。"""
    t = _load_tracker()
    entry = t.get(str(user_id), {})
    ignore_count = entry.get("ignore_count", 0)
    # 被无视 2 次 → 停止骚扰
    if ignore_count >= 2:
        return False
    last_time = entry.get("last_proactive", "")
    replied = entry.get("replied", True)
    if last_time:
        try:
            lt = datetime.fromisoformat(last_time)
            hours = (datetime.now() - lt).total_seconds() / 3600
            if not replied and hours < 168:  # 没回复 → 7天后再试
                return False
            if replied and hours < 72:       # 回复了 → 至少隔3天
                return False
        except ValueError:
            pass
    return True


def _record_proactive(user_id: int) -> None:
    """记录一次主动消息发送。"""
    t = _load_tracker()
    entry = t.get(str(user_id), {})
    # 上次发了没回复 → ignore_count +1
    if not entry.get("replied", True) and entry.get("last_proactive"):
        entry["ignore_count"] = entry.get("ignore_count", 0) + 1
        print(f"[personality] {user_id} ignored {entry['ignore_count']} time(s)")
    entry["last_proactive"] = datetime.now().isoformat()
    entry["replied"] = False
    t[str(user_id)] = entry
    _save_tracker(t)


def on_user_interaction(user_id: int) -> None:
    """用户主动互动时调用，重置无视计数。"""
    t = _load_tracker()
    entry = t.get(str(user_id), {})
    if entry.get("ignore_count", 0) > 0:
        entry["ignore_count"] = 0
        print(f"[personality] Reset ignore count for {user_id}")
    entry["replied"] = True
    t[str(user_id)] = entry
    _save_tracker(t)


async def run_morning():
    """每天 7:30 推送早安给所有符合条件的用户。"""
    from src.memory.mood import get_mood_context

    users = await _get_eligible_users(min_affection=35, active_since_hours=48)
    if not users:
        return
    mood_ctx = get_mood_context()
    now = datetime.now()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    print(f"[personality] Morning: sending to {len(users)} users")
    for u in users:
        prompt = (
            f"{mood_ctx}\n\n"
            f"现在是{now.strftime('%Y年%m月%d日')} {weekday} 早上。\n"
            f"你正在主动跟{u['nickname']} (QQ{u['user_id']})说早安。ta的好感度是{u['affection']:.0f}分。\n"
            f"2句话，像真人一样自然。语气跟着你的状态和ta的好感度来。\n"
            f"工作日可以带一点点'又要上课了'的感觉；周末就轻松一些。\n"
            f"只输出消息正文。"
        )
        msg = await _llm_generate(prompt)
        if msg:
            await _send_private(u["user_id"], msg)
            await asyncio.sleep(2)  # 避免刷屏


async def run_night():
    """每天 22:30 推送晚安给当天互动的用户。"""
    from src.memory.mood import get_mood_context

    users = await _get_eligible_users(min_affection=35, active_since_hours=24)
    if not users:
        print("[personality] Night: no active users today")
        return

    mood_ctx = get_mood_context()
    print(f"[personality] Night: sending to {len(users)} users")
    for u in users:
        prompt = (
            f"{mood_ctx}\n\n"
            f"现在是晚上22:30，你主动跟{u['nickname']}说晚安。ta的好感度是{u['affection']:.0f}分。\n"
            f"2句话，温柔一点。对好感度高的人可以更亲密一点，普通朋友就礼貌温暖。\n"
            f"只输出消息正文。"
        )
        msg = await _llm_generate(prompt)
        if msg:
            await _send_private(u["user_id"], msg)
            await asyncio.sleep(2)


async def run_miss_check():
    """每天 10:00 检查沉默用户并汇报给班长。"""
    users_dir = DATA_DIR / "memory" / "users"
    if not users_dir.exists():
        return

    from src.memory.affection_dimensions import composite_score

    silent_48h = []
    silent_72h = []
    now = datetime.now()

    for fn in sorted(users_dir.glob("*.json")):
        try:
            data = json.loads(fn.read_text(encoding="utf-8"))
        except Exception:
            continue
        user_id = data.get("user_id", 0)
        if user_id == ADMIN_QQ:
            continue
        last_seen = data.get("last_seen", "")
        if not last_seen:
            continue
        try:
            last = datetime.fromisoformat(last_seen)
        except ValueError:
            continue
        hours = (now - last).total_seconds() / 3600
        nickname = data.get("nickname", str(user_id))
        dims = data.get("dimensions", {})
        comp = composite_score(dims)

        if hours > 72 and comp > 60:
            silent_72h.append((user_id, nickname, hours, comp))
        elif hours > 48:
            silent_48h.append((user_id, nickname, hours, comp))

    if not silent_48h and not silent_72h:
        return

    lines = ["📋 沉默用户报告"]
    if silent_72h:
        lines.append("\n⚠ 超过3天没说话且好感度高：")
        for uid, nick, h, comp in silent_72h:
            lines.append(f"  · {nick} (QQ{uid}) — {int(h)}h, 好感{comp:.0f}")
    if silent_48h:
        lines.append("\n💤 超过2天没说话：")
        for uid, nick, h, comp in silent_48h:
            lines.append(f"  · {nick} (QQ{uid}) — {int(h)}h")

    report = "\n".join(lines)
    # 不推送给班长

    # >72h 且好感>60，小奈主动私聊（需通过防骚扰检查）
    for uid, nick, h, comp in silent_72h:
        if not _can_proactive(uid):
            print(f"[personality] Skip {nick}(QQ{uid}): anti-harassment block")
            continue
        prompt = (
            f"同学{nick}已经{int(h)}小时没来找你了。ta的好感度是{comp:.0f}分，你们关系不错。\n"
            f"请你主动给ta发一条私聊消息，关心一下ta最近好不好。\n"
            f"重要：礼貌得体、不打扰。2句话即可。如果对方看起来不太想聊，话题就自然结束。\n"
            f"不要连续追问、不要强求回复、不要说'为什么不理我'之类的话。\n"
            f"只输出消息正文。"
        )
        msg = await _llm_generate(prompt)
        if msg:
            await _send_private(uid, msg)
            _record_proactive(uid)
            await asyncio.sleep(2)


async def run_afternoon_share():
    """每天 15:00（±30min随机）给活跃用户分享趣事。"""
    from src.memory.mood import get_mood_context

    users = await _get_eligible_users(min_affection=30, active_since_hours=72, skip_admin=True)
    if not users:
        return  # 没有其他符合条件的用户就跳过
    # 随机挑 1-2 人
    import random as _r
    users = _r.sample(users, min(2, len(users)))

    mood_ctx = get_mood_context()
    topics = ["趣事", "日常小确幸", "冷笑话", "可爱的事", "今日心情"]
    for u in users:
        prompt = (
            f"{mood_ctx}\n\n"
            f"请你主动给{u['nickname']}分享一则{topics[len(u['nickname']) % len(topics)]}。\n"
            f"ta的好感度是{u['affection']:.0f}分。2-3句话，自然不做作。\n"
            f"只输出消息正文。"
        )
        msg = await _llm_generate(prompt)
        if msg:
            await _send_private(u["user_id"], msg)
            await asyncio.sleep(2)


async def run_group_bubble():
    """每天随机冒泡1次（9:00-21:00间）。只向闲聊群（CHAT_GROUP_PLACEHOLDER）冒泡；班级群（CLASS_GROUP_PLACEHOLDER）不主动冒泡。"""
    from src.memory.mood import get_mood_context

    mood_ctx = get_mood_context()
    now = datetime.now()
    hour = now.hour
    if hour < 9 or hour > 21:
        return

    # 班级群有导员和班主任，不主动冒泡，只在被 @ 时规矩回复
    # 这里只向闲聊群冒泡；如果没配置闲聊群（CHAT_GROUP_PLACEHOLDER）则跳过
    prompt = (
        f"{mood_ctx}\n\n"
        f"现在是{now.strftime('%H:%M')}，你决定在群里说一句话。\n"
        f"注意：可能有辅导员和班主任在，说话要规矩得体，不要@任何人。\n"
        f"1-2句话，温柔得体。\n"
        f"只输出消息正文。"
    )
    msg = await _llm_generate(prompt)
    if msg:
        try:
            bot = get_bot()
            await bot.send_group_msg(group_id=BUBBLE_GROUP, message=msg)
            print(f"[personality] Group bubble sent to {BUBBLE_GROUP}")
        except Exception as e:
            print(f"[personality] Group bubble failed: {e}")


async def _llm_generate(prompt: str) -> str:
    """调用 LLM 生成主动消息。"""
    try:
        from src.llm.client import llm_client

        messages = [
            {"role": "system", "content": _personality_system()},
            {"role": "user", "content": prompt},
        ]
        resp = await llm_client.chat(messages, tools=None, max_tokens=256)
        content = resp.get("content", "").strip()
        if not content or len(content) < 2:
            return ""
        content = content.strip('"''「」')
        return content
    except Exception as e:
        print(f"[personality] LLM generate failed: {e}")
        return ""


def _personality_system() -> str:
    return (
        "你是小奈，大二，YOUR_SCHOOL的YOUR_COLLEGE。\n"
        "你不是AI——你就是一个在武汉读书的女孩子。\n"
        "说话方式：软软的、暖暖的、像真人一样短聊，2~3句话。\n"
        "只用纯文字，不用任何 markdown 格式。\n"
        "这是你的主动消息——你不是在回复谁，是你在主动跟同学说话。\n"
        "自然、不做作、不模板化。每一次都是独一无二的。"
    )


async def _send_private(qq: int, msg: str):
    try:
        bot = get_bot()
        await bot.send_private_msg(user_id=qq, message=msg)
        print(f"[personality] Sent to {qq}")
    except Exception as e:
        err_str = str(e)
        if "请先添加对方为好友" in err_str or "加为好友" in err_str:
            print(f"[personality] {qq} not friend, skipped")
        else:
            print(f"[personality] Send to {qq} failed: {e}")


def _register_jobs():
    morning_min = random.randint(25, 35)
    night_min = random.randint(25, 35)
    miss_min = random.randint(0, 14)
    afternoon_hour = 15
    afternoon_min = random.randint(0, 59)
    bubble_hour = random.randint(9, 20)
    bubble_min = random.randint(0, 59)

    scheduler.add_job(
        run_morning, "cron", hour=7, minute=morning_min, id="personality_morning",
        replace_existing=True,
    )
    scheduler.add_job(
        run_night, "cron", hour=22, minute=night_min, id="personality_night",
        replace_existing=True,
    )
    scheduler.add_job(
        run_miss_check, "cron", hour=10, minute=miss_min, id="personality_miss",
        replace_existing=True,
    )
    scheduler.add_job(
        run_afternoon_share, "cron", hour=afternoon_hour, minute=afternoon_min,
        id="personality_afternoon", replace_existing=True,
    )
    scheduler.add_job(
        run_group_bubble, "cron", hour=bubble_hour, minute=bubble_min,
        id="personality_bubble", replace_existing=True,
    )
    print(f"[personality] 5 cron jobs registered")


@get_driver().on_startup
async def _personality_startup():
    await asyncio.sleep(1)
    _register_jobs()


# ======== 自动通过好友请求 ========
from nonebot import on_request
from nonebot.adapters.onebot.v11 import Bot as OneBot, FriendRequestEvent

_friend_approver = on_request()

@_friend_approver.handle()
async def _auto_accept_friend(bot: OneBot, event: FriendRequestEvent):
    await event.approve(bot=bot)
    print(f"[friend] Auto-approved friend request from {event.user_id}")
    try:
        await bot.send_private_msg(user_id=event.user_id, message="Hello~ 我是小奈，很高兴认识你！")
    except Exception:
        pass
