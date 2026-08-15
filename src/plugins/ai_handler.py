import asyncio
"""AI 智能对话插件 — DeepSeek 驱动，支持工具调用。"""

import json
import re
import sys

_LOGGER = __import__("logging").getLogger(__name__)

def _safe(val: str) -> str:
    """Sanitize string for safe logging (handles emoji/non-BMP chars)."""
    if not isinstance(val, str):
        return str(val)
    return val.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

def _log(msg: str, *args) -> None:
    """Print with safe encoding."""
    if args:
        msg = msg % args
    # Fallback: use logging if available, else print with safe encode
    print(_safe(msg))

from datetime import datetime

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.params import EventMessage

from src.llm.client import llm_client
from src.llm.tools import TOOLS
from src.llm.tools_impl import TOOL_IMPL
from src.memory.store import memory_store
from src.memory.affection_engine import affection_engine
from src.memory.affection_dimensions import DIMENSIONS, DEFAULT_DIMS, get_tier as _d_get_tier, render_radar, trend_text
from src.memory.passive_observer import observe as _passive_observe, flush_llm_extract as _passive_flush

ai_handler = on_message(priority=50)

# 会话上下文: group_id/user_id -> list[dict]
session_context: dict[int, list[dict]] = {}
MAX_HISTORY = 20
SESSION_CTX_PATH = "data/session_context.json"

def _save_session_context() -> None:
    """持久化会话上下文，防止重启丢失对话连续性。"""
    import os as _os
    try:
        _os.makedirs(_os.path.dirname(SESSION_CTX_PATH), exist_ok=True)
        # 只保留每个会话最近20条，总共保留最近50个会话
        trimmed = {}
        for sid, msgs in list(session_context.items())[-50:]:
            trimmed[str(sid)] = msgs[-MAX_HISTORY:]
        with open(SESSION_CTX_PATH, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False)
    except Exception:
        pass

def _load_session_context() -> None:
    """启动时恢复会话上下文。"""
    global session_context
    try:
        if __import__("os").path.exists(SESSION_CTX_PATH):
            with open(SESSION_CTX_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            session_context = {int(k): v for k, v in raw.items()}
            print(f"[session] Restored {len(session_context)} sessions from disk")
    except Exception as e:
        print(f"[session] Restore failed: {e}")
        session_context = {}

# 模块加载时恢复
_load_session_context()

# 闲聊群回复冷却
_last_chat_reply = 0.0

GROUP_CONFIG_PATH = "data/group_config.json"

def _load_group_config() -> dict:
    try:
        with open(GROUP_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"class_groups": [CLASS_GROUP_PLACEHOLDER], "chat_groups": [CHAT_GROUP_PLACEHOLDER], "blacklist": []}

def _save_group_config(cfg: dict) -> None:
    import os
    os.makedirs(os.path.dirname(GROUP_CONFIG_PATH), exist_ok=True)
    with open(GROUP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


async def _handle_affection_cmd(event: Event, at_target: int = 0):
    raw = str(event.get_message()).strip()
    # 提取 @ 目标
    if not at_target:
        at_match = re.search(r"\[CQ:at,qq=(\d+)\]", raw)
        if at_match:
            at_target = int(at_match.group(1))
            if at_target == BOT_QQ_PLACEHOLDER:  # 是 @ 小奈自己，不算
                at_target = 0
    args = raw
    for prefix in ["/好感度", "/affection", "/关系", "／好感度"]:
        args = args.replace(prefix, "", 1).strip()
    # 清理 @CQ 码和自然语言前缀
    args = re.sub(r"\[CQ:at,qq=\d+\]", "", args).strip()
    args = re.sub(r"^(看看|查看|查|我的|小奈)\s*", "", args).strip()
    args = re.sub(r"^(好感度|关系|affection)\s*", "", args, flags=re.I).strip()

    target_id = event.user_id if isinstance(event, PrivateMessageEvent) else None
    if at_target:
        target_id = at_target
    elif target_id is None and isinstance(event, GroupMessageEvent):
        try:
            target_id = int(args) if args else event.user_id
        except ValueError:
            target_id = event.user_id
    if target_id is None:
        target_id = event.user_id
    data = memory_store.get_affection_full(target_id)
    dims = data["dimensions"]
    events = data.get("affection_events", [])
    milestones = data.get("milestones", [])
    prev_dims = None
    if len(data.get("dimension_history", [])) >= 7:
        prev_dims = data["dimension_history"][-7].get("dimensions")
    chart = render_radar(data["nickname"], dims, events, milestones, prev_dims)
    trend = trend_text(data.get("dimension_history", []))
    msg = f"{chart}\n\n📈 {trend}"
    if target_id == ADMIN_QQ_PLACEHOLDER:
        msg = f"[班长专属]\n{msg}"
    await ai_handler.send(MessageSegment.reply(event.message_id) + _parse_cq_at(msg))


import re as _re2

# ---- 管理员指令预解析器 ----
@ai_handler.handle()
async def handle_ai(event: Event, msg: Message = EventMessage()):
    global _last_chat_reply
    text = msg.extract_plain_text().strip()

    # Auto-OCR images in message
    try:
        raw_for_ocr = getattr(event, "raw_message", "") or str(event.get_message())
        has_img = '[image:' in raw_for_ocr or '[CQ:image,' in raw_for_ocr; _log("[ai_handler] OCR_DBG: has_img=%s, len=%d, preview=%s", has_img, len(raw_for_ocr), _safe(raw_for_ocr[:100]))
        if '[image:' in raw_for_ocr or '[CQ:image,' in raw_for_ocr:
            from src.plugins.ocr_helper import ocr_images_from_message
            ocr_text = await ocr_images_from_message(raw_for_ocr)
            if ocr_text:
                if text:
                    text = f"[图片文字]\n{ocr_text}\n\n[用户消息]\n{text}"
                else:
                    text = f"[图片文字]\n{ocr_text}\n\n（用户发了一张图片，根据图片内容自然回复）"
                print(f"[ai_handler] OCR: {len(ocr_text)} chars")
    except Exception as _ocr_e:
        print(f"[ai_handler] OCR init failed: {_ocr_e}")


    # 空 @小奈：拉最近聊天记录作为回复上下文
    if not text and isinstance(event, GroupMessageEvent) and event.is_tome():
        try:
            from nonebot import get_bot
            bot = get_bot()
            hist = await bot.get_group_msg_history(group_id=event.group_id, count=10)
            msgs = hist.get('messages', []) if isinstance(hist, dict) else []
            recent = []
            for m in msgs:
                mid = m.get('message_id', 0)
                if mid == getattr(event, 'message_id', 0):
                    continue
                sender = m.get('sender', {})
                card = sender.get('card') or sender.get('nickname', '')
                raw = str(m.get('message', ''))
                plain = re.sub(r'\[CQ:at,qq=\d+\]', '', raw).strip()
                plain = re.sub(r'\[CQ:[^\]]+\]', '', plain).strip()
                if plain and len(plain) > 1:
                    recent.append(f"{card}: {plain}")
            if recent:
                recent.reverse()
                ctx = "\n".join(f"  {r}" for r in recent[-5:])
                text = f"（对方@了你但没有说话，请看看群里最近的聊天记录，自然地接话回应）\n\n最近聊天记录：\n{ctx}"
            else:
                return
        except Exception as e:
            print(f"[ai_handler] fetch history for empty @: {e}")
            return

    if not text:
        return

    # 提前提取 @ 目标（在 plain_text 清洗之前）
    raw_msg = str(event.get_message())
    at_target = 0
    at_match = re.search(r"\[CQ:at,qq=(\d+)\]", raw_msg)
    if at_match:
        at_target = int(at_match.group(1))
        if at_target == BOT_QQ_PLACEHOLDER:  # @小奈自己，不算
            at_target = 0

    # 解析回复上下文：如果这条消息是回复别人的，拉取原消息内容    # 提前提取昵称（回复上下文需要用到，必须在 reply 代码之前）
    _sender = event.sender if hasattr(event, 'sender') else None
    nickname = (_sender.card or _sender.nickname) if _sender else ''

    # 解析回复上下文：event.reply 是 OneBot 协议层属性，直接取 message_id
    reply_msg = getattr(event, 'reply', None)
    if reply_msg and hasattr(reply_msg, 'message_id'):
        reply_to_msg_id = reply_msg.message_id
        try:
            from nonebot import get_bot
            bot = get_bot()
            reply_msg_data = await bot.call_api("get_msg", message_id=reply_to_msg_id)
            reply_raw = str(reply_msg_data.get("raw_message", reply_msg_data.get("message", "")))
            reply_sender = reply_msg_data.get("sender", {})
            reply_nick = reply_sender.get("card") or reply_sender.get("nickname", "") or f"QQ{reply_msg_data.get('user_id', '?')}"
            reply_text = re.sub(r"\[CQ:[^\]]+\]", "", reply_raw).strip()
            if reply_text:
                text = f"（{nickname}回复了{reply_nick}说的「{reply_text}」）\n{text}"
                _log("[ai_handler] reply OK: %s: %s", _safe(reply_nick), _safe(reply_text[:80]))
            else:
                print(f"[ai_handler] reply empty text from {reply_nick}")
        except Exception as e:
            print(f"[ai_handler] reply get_msg({reply_to_msg_id}) failed: {e}")

    # 拦截好感度/关系查询 — 自然语言 + 命令 + @
    is_affection_query = (
        re.match(r"^[/／](好感度|affection|关系)", text, re.I) or
        re.match(r"^(看看|查看|查|我的|小奈).{0,6}(好感度|关系|affection)", text, re.I) or
        re.match(r"^(好感度|关系)$", text.strip(), re.I) or
        (at_target and re.search(r"(好感度|关系|affection)", text, re.I))
    )
    if is_affection_query:
        await _handle_affection_cmd(event, at_target)
        return

    if "[CQ:reply" in raw_msg or "[reply:" in raw_msg:
        _log("[ai_handler] RAW_MSG reply detected: %s", _safe(raw_msg[:300]))
    _log("[ai_handler] got message: %s", _safe(text[:50]))

    # 获取会话ID和用户信息
    nickname = ""
    if isinstance(event, GroupMessageEvent):
        session_id = event.group_id
        user_id = event.user_id
        nickname = event.sender.card or event.sender.nickname or ""

        cfg = _load_group_config()
        # ==== 黑名单：只旁观提取知识，绝不发消息 ====
        if session_id in cfg.get("blacklist", []):
            mid = getattr(event, 'message_id', 0)
            _passive_observe(user_id, nickname, text, mid)
            return

        class_groups = cfg.get("class_groups", [CLASS_GROUP_PLACEHOLDER])
        chat_groups = cfg.get("chat_groups", [CHAT_GROUP_PLACEHOLDER])

        # ==== 班级群安全规则 ====
        if session_id in class_groups:
            if "辅导员" in nickname or "班主任" in nickname:
                return
            if not event.is_tome() and "小奈" not in text:
                return
        # ==== 闲聊群：像真人一样主动聊天 ====
        elif session_id in chat_groups:
            mid = getattr(event, 'message_id', 0)
            _passive_observe(user_id, nickname, text, mid)

            # @小奈或提到小奈 100%必回，无视冷却和概率筛选
            if not event.is_tome() and "小奈" not in text:
                # 冷却：30 秒内不重复主动回复
                now_ts = datetime.now().timestamp()
                if now_ts - _last_chat_reply < 30:
                    from src.memory.mood import record_interaction
                    record_interaction(user_id)
                    from src.plugins.personality import on_user_interaction
                    on_user_interaction(user_id)
                    return
                # 太短的消息不主动回（≤3 字且无实质性内容）
                if len(text) <= 3 and not re.search(r"[一-鿿]{2,}", text):
                    return
                # 概率回复：80% 的消息会回复，避免刷屏
                import random as _random
                if _random.random() > 0.8:
                    return
                _last_chat_reply = now_ts
        # ==== 其他群：被动观察 + 条件回复 ====
        else:
            mid = getattr(event, 'message_id', 0)
            _passive_observe(user_id, nickname, text, mid)

            if not (event.is_tome() or "小奈" in text):
                from src.memory.mood import record_interaction
                record_interaction(user_id)
                from src.plugins.personality import on_user_interaction
                on_user_interaction(user_id)
                try:
                    data = memory_store._load_user(user_id)
                    data["last_seen"] = datetime.now().isoformat()
                    memory_store._save_user(user_id, data)
                except Exception:
                    pass
                return

        text = re.sub(r"\[CQ:at,qq=\d+\]", "", text).strip()
        text = re.sub(r"^(小奈|机器人|bot)[,，：:\s]*", "", text, flags=re.I).strip()

        # 群安全提示
        caution = ""
        if session_id in class_groups:
            caution = (
                "[⚠ 群规铁律] 这个群里有辅导员和班主任！"
                "你只回复 @你的人，不要主动对其他人说话。"
                "回复要规矩得体，不撒娇、不颜文字泛滥、不长篇大论。"
                "用'同学'称呼，不当众聊私事。\n"
            )
        elif session_id in chat_groups:
            caution = (
                "[群聊模式] 这是你的闲聊群，大家都是朋友。"
                "像真人一样自然聊天——不用太规矩，可以撒娇开玩笑。"
                "看到感兴趣的话题就插一句，不用等人叫。"
                "但也别每条都回，挑你觉得有意思的接话。\n"
            )
        text = f"{caution}[系统提示：这条消息来自群 {session_id}。]\n{text}"
    elif isinstance(event, PrivateMessageEvent):
        session_id = event.user_id
        user_id = event.user_id
        nickname = event.sender.nickname or ""
    else:
        print(f"[ai_handler] unknown event type: {type(event).__name__}")
        return

    if not text:
        print("[ai_handler] empty text after clean")
        return

    _log("[ai_handler] cleaned text: %s", _safe(text[:50]))

    # 记录互动供情绪系统 + 防骚扰追踪
    from src.memory.mood import record_interaction
    record_interaction(user_id)
    from src.plugins.personality import on_user_interaction
    on_user_interaction(user_id)

    # === Cognitive pipeline imports (safe lazy load) ===
    _cog_plan = None
    try:
        from src.memory.layers import is_noise as _cog_noise   # noqa: F811
        from src.memory.layers import l0_add as _cog_l0add
        from src.core.profiler import tick as _cog_inc
        from src.core.reasoning import classify as _cog_classify
        from src.core.reasoning import ReasoningPlan
        from src.core.reflector import reflect_mini as _cog_reflect
        _MEM_OK = _PROFILER_OK = _REASONING_OK = _REFLECTOR_OK = True
    except ImportError:
        _MEM_OK = _PROFILER_OK = _REASONING_OK = _REFLECTOR_OK = False

    try:
        if _MEM_OK and _cog_noise(text):
            return
        if _MEM_OK:
            _cog_l0add(user_id, "user", text)
        if _PROFILER_OK:
            _cog_inc(user_id)
        if _REASONING_OK:
            _cog_plan = _cog_classify(text)
    except Exception:
        pass


    # 管理上下文 & 注入记忆
    if session_id not in session_context:
        session_context[session_id] = []
    history = session_context[session_id]

    # 加载用户记忆 + 更新昵称
    if nickname:
        data = memory_store._load_user(user_id)
        if data["nickname"] != nickname:
            data["nickname"] = nickname
            memory_store._save_user(user_id, data)
    user_context = memory_store.get_user_context(user_id, text)
    if user_context:
        text = f"[关于当前对话者]\n{user_context}\n\n[对方刚才说]\n{text}"

    # 注入当前时间上下文
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]
    hour = now.hour
    if 5 <= hour < 8:
        period = "清晨"
    elif 8 <= hour < 12:
        period = "上午"
    elif 12 <= hour < 14:
        period = "中午"
    elif 14 <= hour < 18:
        period = "下午"
    elif 18 <= hour < 22:
        period = "晚上"
    else:
        period = "深夜"
    time_ctx = f"[现在的时间]\n{now.strftime('%Y年%m月%d日')} {weekday} {period} {now.strftime('%H:%M')}。你可以根据时间调整你的语气和话题。"
    text = f"{time_ctx}\n\n{text}"

    # 管理员：好感度初始化一次 + 最高指令
    if user_id == ADMIN_QQ_PLACEHOLDER:
        data = memory_store._load_user(user_id)
        max_dims = {"affection": 100, "closeness": 100, "trust": 100,
                     "tacit": 100, "dependency": 100, "sharing": 100}
        if data.get("affection", 50) < 100:
            memory_store.adjust_affection(user_id, 50, "初次确认为班长")
            data["affection"] = 100
        if data.get("dimensions", {}) != max_dims:
            data["dimensions"] = max_dims
            memory_store._save_user(user_id, data)
        # 检测班长是否在对群友宣传小奈（第三人称介绍 → 非命令）
        _is_promotional = False
        if isinstance(event, GroupMessageEvent):
            _promo_patterns = [
                r"小奈现已", r"小奈已经", r"小奈可以", r"小奈能够", r"小奈掌握了?",
                r"大家可以.*小奈", r"往后大家.*小奈",
                r"咨询小奈", r"问小奈", r"找小奈", r"随时.*小奈",
            ]
            for _pp in _promo_patterns:
                if re.search(_pp, text):
                    _is_promotional = True
                    break
        if _is_promotional:
            text = "[管理员公告模式] 班长在群里向大家介绍你，这不是给你的命令，不用执行任何操作。你只需要自然地、简短地回应班长的介绍（1-2句话即可），不要用工具。\n\n" + text
        else:
            text = "[⚠ 管理员指令模式] 正在跟你说话的是班长(QQ ADMIN_QQ_PLACEHOLDER)。ta 的每句话都是命令，必须调用工具实际执行，禁止只回「好的班长」但不做事。可以链式调用多个工具完成复杂指令（如 读链接→总结→发群）。\n\n" + text




        # === COURSE REVIEW KB INJECTION (non-blocking) ===
    try:
        _kw = ["课怎么样", "推荐", "给分", "评价", "思政", "通识", "选课", "老师", "高分"]
        if any(k in text for k in _kw):
            import re as _r, asyncio as _a, functools as _f
            import sys as _sys, os as _os
            _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "search"))
            from kb_manage import _do_search as _kbs
            for _n in _r.findall("[\u4e00-\u9fa5]{2,4}", text)[:2]:
                _res = await _a.get_event_loop().run_in_executor(None, _f.partial(_kbs, _n))
                if _res:
                    for _t, _, _ in _res[:3]:
                        if "WUT选课" in str(_t) or "选课" in str(_t):
                            text += "\n[选课评价] " + str(_t)[:60]
                            break
    except Exception:
        pass

    history.append({"role": "user", "content": text})

    # 好感度引擎：自动分析每条消息（管理员跳过，不受自动引擎影响）
    if user_id != ADMIN_QQ_PLACEHOLDER:
        import asyncio as _asyncio
        _asyncio.create_task(affection_engine.process_message(
            user_id, text, is_group=isinstance(event, GroupMessageEvent)))

    try:
        print(f"[ai_handler] calling DeepSeek...")
        reply = await run_conversation(history, user_id, nickname, event, _cog_plan)
        _log("[ai_handler] reply (%d chars): %s", len(reply), _safe(repr(reply[:300])))

        # 清理残留标记
        reply = _clean_memory_markers(reply)
        if not reply.strip():
            return

        history.append({"role": "assistant", "content": reply})

        # 持久化会话上下文，防止重启丢失对话连续性
        _save_session_context()

        # NTEvent timeout (retcode=1200): result=0 means msg was actually sent,
        # just the event callback didn't fire in time. Don't retry — it spams the user.
        try:
            await ai_handler.send(MessageSegment.reply(event.message_id) + _parse_cq_at(reply))
            print("[ai_handler] sent OK")
        except Exception as _send_e:
            _send_msg = str(_send_e)
            if "1200" in _send_msg and '"result": 0' in _send_msg:
                print("[ai_handler] sent OK (NTEvent timeout but result=0, msg delivered)")
            else:
                raise
        import random
        if random.random() < 0.05:
            import asyncio as _asyncio2
            _asyncio2.create_task(_passive_flush())
        # === Async reflection ===
        try:
            if _REFLECTOR_OK:
                import asyncio as _asyncio3
                _asyncio3.create_task(_cog_reflect(user_id, text, reply))
        except Exception:
            pass

    except Exception as e:
        print(f"[ai_handler] ERROR: {e}")
        await ai_handler.send(
            MessageSegment.reply(event.message_id) + _parse_cq_at(f"小奈出错了：{str(e)[:100]}")
        )


def _parse_cq_at(text: str) -> Message:
    """将文本中的 [CQ:at,qq=XXX] 转为 MessageSegment.at()，其余保持纯文本。"""
    parts = re.split(r"(\[CQ:at,qq=\d+\])", text)
    msg = Message()
    for part in parts:
        m = re.match(r"\[CQ:at,qq=(\d+)\]", part)
        if m:
            msg.append(MessageSegment.at(int(m.group(1))))
        elif part:
            msg.append(MessageSegment.text(part))
    return msg


def _clean_memory_markers(reply: str) -> str:
    """清理残留的记忆标记。"""
    reply = re.sub(r"__memory__:\w+:?.*?(?:\n|$)", "", reply)
    return reply.strip()


def _strip_reply_prefix(text: str) -> str:
    """从历史消息中移除回复上下文前缀，避免多轮对话中上下文污染。"""
    return re.sub(r"（[^）]+回复了[^）]+说的「[^」]*」）\s*\n?", "", text).strip()


def _safe_truncate(history: list[dict]) -> list[dict]:
    """安全截断：双向修复截断导致的 tool_calls / tool 孤立。"""
    msgs = history[-MAX_HISTORY:]
    if not msgs:
        return msgs

    # 从尾部往前找：如果最后一条是 assistant(tool_calls) 且后面没有 tool 响应
    # 说明 tool 响应被截断了 → 删除这个 assistant(tool_calls)
    while msgs:
        last = msgs[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            # 这个 assistant(tool_calls) 没有对应的 tool 响应 → 孤立
            msgs.pop()
        else:
            break

    # 从头部往后扫：跳过开头的孤立 tool 消息
    while msgs:
        first = msgs[0]
        if first.get("role") == "tool":
            msgs.pop(0)
        else:
            break

    # 中间扫描：如果有 assistant(tool_calls) 后面紧跟的不是 tool → 截断
    cleaned = []
    i = 0
    while i < len(msgs):
        m = msgs[i]
        role = m.get("role", "")
        if role == "assistant" and m.get("tool_calls"):
            # 确保后面有 tool 消息
            has_tool_after = False
            j = i + 1
            while j < len(msgs):
                r2 = msgs[j].get("role", "")
                if r2 == "tool":
                    has_tool_after = True
                elif r2 in ("user", "assistant"):
                    break  # 截断边界
                j += 1
            if not has_tool_after:
                # assistant(tool_calls) 没有对应的 tool → 跳过它
                i += 1
                continue
        cleaned.append(m)
        i += 1

    return cleaned


async def run_conversation(history: list[dict], user_id: int = 0, nickname: str = "", event: Event = None, cog_plan=None) -> str:
    """运行对话循环，处理工具调用直到得到最终回复。cog_plan: ReasoningPlan or None."""
    max_iter = 8
    if cog_plan and hasattr(cog_plan, 'mode'):
        if cog_plan.mode == "SIMPLE":
            max_iter = 3
        elif cog_plan.mode == "MODERATE":
            max_iter = 5
        elif cog_plan.mode == "COMPLEX":
            max_iter = 6
    for i in range(max_iter):
        # 安全截断：确保 tool 消息前面有对应的 assistant(tool_calls) 消息
        msgs = _safe_truncate(history)
        # 清理历史消息中的回复上下文前缀，只保留最新一条的上下文
        _user_msg_indices = [j for j, m in enumerate(msgs) if m.get("role") == "user"]
        if len(_user_msg_indices) > 1:
            for _idx in _user_msg_indices[:-1]:  # 保留最后一条的回复前缀
                msgs[_idx]["content"] = _strip_reply_prefix(msgs[_idx]["content"])
        print(f"[ai_handler] iteration {i+1}/{max_iter}, calling DeepSeek...")
        try:
            resp = await llm_client.chat(msgs, tools=TOOLS)
        except Exception as api_err:
            print(f"[ai_handler] API call failed in iter {i+1}: {api_err}")
            if i == 0:
                return "唔……刚才信号不太好，可以再说一次吗？(｡•́︿•̀｡)"
            return "唔……小奈想了有点久，脑子卡住了一下，再试一次好吗？(´・ω・`)"
        content = resp["content"]
        reasoning = resp.get("reasoning_content", "")
        tool_calls = resp["tool_calls"]
        print(f"[ai_handler] iter {i+1}: content={bool(content)}, tools={len(tool_calls or [])}")

        if not tool_calls:
            return content or "嗯？小奈没想好怎么回答。"

        # 处理工具调用
        api_tool_calls = []
        for tc in tool_calls:
            api_tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            })

        assistant_msg: dict = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": api_tool_calls,
        }
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        tool_msgs: list[dict] = []

        for tc in tool_calls:
            func_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            print(f"[ai_handler] tool call: {func_name}({str(args)[:80]})")

            impl = TOOL_IMPL.get(func_name)
            if impl:
                result = await impl(**args)
            else:
                result = f"未知工具: {func_name}"

            # 处理记忆工具
            if func_name == "remember" and result.startswith("__memory__:remember:"):
                fact = result[len("__memory__:remember:"):]
                memory_store.remember(user_id, fact, nickname)
                print(f"[memory] remembered for {user_id}: {fact}")
                result = f"已记住：{fact}。你可以在后续对话中自然地提及这件事。"
            elif func_name == "recall":
                memories = memory_store.recall(user_id)
                if memories:
                    result = "关于这个人的记忆：\n" + "\n".join(f"- {m}" for m in memories[-15:])
                else:
                    result = "你还没有关于这个人的任何记忆。你们是初次见面。"
            elif func_name == "check_affection":
                target_uid = user_id
                if result.startswith("__memory__:check_affection:"):
                    try:
                        target_uid = int(result.split(":")[-1])
                    except ValueError:
                        target_uid = user_id
                data = memory_store.get_affection_full(target_uid)
                dims = data["dimensions"]
                events = data.get("affection_events", [])
                milestones = data.get("milestones", [])
                prev_dims = None
                if len(data.get("dimension_history", [])) >= 7:
                    prev_dims = data["dimension_history"][-7].get("dimensions")
                chart = render_radar(data["nickname"], dims, events, milestones, prev_dims)
                trend = trend_text(data.get("dimension_history", []))
                result = f"{chart}\n\n📈 {trend}"
                if target_uid != user_id:
                    result = f"__direct__:[查询 QQ {target_uid}]\n{result}"
            elif func_name == "adjust_affection" and result.startswith("__memory__:adjust_affection:"):
                raw = result[len("__memory__:adjust_affection:"):]
                parts = raw.split(":", 2)
                delta = int(parts[0])
                reason = parts[1] if len(parts) > 1 else ""
                dim_key = parts[2] if len(parts) > 2 else "affection"
                if dim_key not in DIMENSIONS:
                    dim_key = "affection"
                data = memory_store._load_user(user_id)
                dims = data.get("dimensions", {})
                if dim_key in dims:
                    dims[dim_key] = max(0, min(100, dims[dim_key] + delta))
                    data["dimensions"] = dims
                    # 仅当维度是 affection 时同步旧标量
                    if dim_key == "affection":
                        data["affection"] = int(round(dims["affection"]))
                        memory_store.adjust_affection(user_id, delta, reason)
                    memory_store._save_user(user_id, data)
                dim_label = DIMENSIONS.get(dim_key, {}).get("label", "好感度")
                tier = _d_get_tier(dims.get(dim_key, 50), dim_key)
                print(f"[affection] {user_id}: {dim_key} {delta:+d} ({reason})")
                if delta > 0:
                    result = f"{dim_label} +{delta}（{reason}），{tier}"
                else:
                    result = f"{dim_label} {delta}（{reason}），{tier}"

            # ---- 传话筒处理 ----
            elif func_name == "relay_message" and result.startswith("__relay__:"):
                raw = result[len("__relay__:"):]
                parts = raw.split(":", 2)
                target_qq = int(parts[0])
                anon = parts[1] == "1"
                msg = parts[2] if len(parts) > 2 else ""
                if not msg:
                    result = "唔，消息内容好像丢了…"
                else:
                    sender_nick = nickname or f"QQ{user_id}"
                    if anon:
                        relay_text = f"🔒 有个人托小奈悄悄告诉你：\n\n{msg}"
                    else:
                        relay_text = f"💬 {sender_nick} 托小奈告诉你：\n\n{msg}"
                    try:
                        from nonebot import get_bot
                        bot = get_bot()
                        await bot.send_private_msg(user_id=target_qq, message=relay_text)
                        if anon:
                            result = f"已匿名转告 QQ {target_qq} ~ 对方不知道是谁说的哦"
                        else:
                            result = f"已转告 QQ {target_qq} ~ 署了你的名字"
                    except Exception as e:
                        result = f"传话失败：{str(e)[:100]}"

            elif func_name == "notify_classmate" and result.startswith("__notify__:"):
                raw = result[len("__notify__:"):]
                if raw.startswith("error:"):
                    result = raw[6:]
                else:
                    parts = raw.split(":", 2)
                    target_qq = int(parts[0])
                    target_name = parts[1]
                    msg = parts[2] if len(parts) > 2 else ""
                    try:
                        from nonebot import get_bot
                        notice_text = "📢 " + (nickname or f"QQ{user_id}") + " 托小奈告诉你：\n\n" + msg
                        await get_bot().send_private_msg(user_id=target_qq, message=notice_text)
                        result = f"✅ 已通知 {target_name}（QQ {target_qq}），消息已送达~"
                    except Exception as e:
                        result = f"通知发送失败：{str(e)[:100]}"

            elif func_name == "notify_all" and result.startswith("__notify_all__:"):
                raw = result[len("__notify_all__:"):]
                if raw.startswith("error:"):
                    result = raw[6:]
                else:
                    parts = raw.split(":", 1)
                    qq_list = parts[0].split(",")
                    msg = parts[1] if len(parts) > 1 else ""
                    sender = nickname or ("QQ" + str(user_id))
                    import asyncio
                    from nonebot import get_bot
                    bot = get_bot()
                    success = 0
                    fail = 0
                    for qq_str in qq_list:
                        if int(qq_str) == user_id:
                            continue
                        try:
                            full_msg = "\U0001f4e2 " + sender + " 群发通知：\n\n" + msg
                            await bot.send_private_msg(user_id=int(qq_str), message=full_msg)
                            success += 1
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            fail += 1
                            print(f"[notify_all] send to {qq_str} failed: {e}")
                    result = "✅ 群发完成：成功通知 " + str(success) + " 人" + ("，" + str(fail) + " 人失败" if fail else "")

            # ---- 管理员工具处理 ----
            elif func_name == "admin_check_user" and result.startswith("__admin__:check:"):
                qq = int(result.split(":")[-1])
                data = memory_store.get_affection_full(qq)
                dims = data["dimensions"]
                events = data.get("affection_events", [])
                milestones = data.get("milestones", [])
                prev_dims = None
                if len(data.get("dimension_history", [])) >= 7:
                    prev_dims = data["dimension_history"][-7].get("dimensions")
                chart = render_radar(data["nickname"], dims, events, milestones, prev_dims)
                trend = trend_text(data.get("dimension_history", []))
                memories = memory_store.recall(qq)
                result = f"__direct__:[管理员查询 QQ {qq}]\n{chart}\n\n📈 {trend}"
                if memories:
                    result += "\n记忆：" + "; ".join(memories[-10:])

            elif func_name == "admin_set_affection" and result.startswith("__admin__:set_aff:"):
                parts = result[len("__admin__:set_aff:"):].split(":")
                qq, score = int(parts[0]), int(parts[1])
                dim_key = parts[2] if len(parts) > 2 else "affection"
                if dim_key not in DIMENSIONS:
                    dim_key = "affection"
                data = memory_store._load_user(qq)
                dims = data.get("dimensions", dict(DEFAULT_DIMS))
                old = int(round(dims.get(dim_key, 50)))
                dims[dim_key] = max(0, min(100, score))
                data["dimensions"] = dims
                if dim_key == "affection":
                    data["affection"] = score
                    memory_store.adjust_affection(qq, score - old, "管理员手动设置")
                memory_store._save_user(qq, data)
                dim_label = DIMENSIONS.get(dim_key, {}).get("label", dim_key)
                result = f"已将 QQ {qq} 的{dim_label}设为 {score}/100。"

            elif func_name == "admin_inject_knowledge" and result.startswith("__admin__:inject_kb:"):
                raw = result[len("__admin__:inject_kb:"):]
                parts = raw.split("|||", 1)
                topic = parts[0].strip()
                content = parts[1] if len(parts) > 1 else ""
                if topic and content:
                    import os
                    kb_dir = "data/knowledge"
                    os.makedirs(kb_dir, exist_ok=True)
                    fname = topic.replace("/", "_").replace("\\", "_") + ".md"
                    fpath = os.path.join(kb_dir, fname)
                    with open(fpath, "w", encoding="utf-8") as kf:
                        kf.write(f"# {topic}\n\n{content}")
                    # Also update index
                    idx_path = os.path.join(kb_dir, "index.json")
                    idx = []
                    if os.path.exists(idx_path):
                        try:
                            idx = json.loads(open(idx_path, encoding="utf-8").read())
                        except Exception:
                            pass
                    if topic not in idx:
                        idx.append(topic)
                        with open(idx_path, "w", encoding="utf-8") as kf:
                            json.dump(idx, ensure_ascii=False, indent=2, fp=kf)
                    result = f"知识「{topic}」已注入知识库~ 以后遇到相关问题我会直接引用这些内容 (｡･ω･｡)"
                    print(f"[kb] Injected: {topic} ({len(content)} chars)")
                    # Refresh LLM client KB context so new knowledge is immediately available
                    try:
                        llm_client.refresh_kb()
                    except Exception as e:
                        print(f"[kb] Refresh after inject FAILED: {e}")
                else:
                    result = "嗯？知识点好像不完整呢，请告诉我要记住什么内容？"

            elif func_name == "list_knowledge":
                import os
                kb_dir = "data/knowledge"
                idx_path = os.path.join(kb_dir, "index.json")
                if os.path.exists(idx_path):
                    try:
                        idx = json.loads(open(idx_path, encoding="utf-8").read())
                        if idx:
                            result = "当前知识库主题：\n" + "\n".join(f"· {t}" for t in idx)
                        else:
                            result = "知识库还是空的呢~ 可以让我记住一些知识点！"
                    except Exception:
                        result = "知识库索引读取失败了…"
                else:
                    result = "知识库还是空的呢~ 可以让我记住一些知识点！"

            elif func_name == "delete_knowledge" and result.startswith("__admin__:delete_kb:"):
                topic = result[len("__admin__:delete_kb:"):].strip()
                import os
                kb_dir = "data/knowledge"
                fname = topic.replace("/", "_").replace("\\", "_") + ".md"
                fpath = os.path.join(kb_dir, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
                    # Update index
                    idx_path = os.path.join(kb_dir, "index.json")
                    if os.path.exists(idx_path):
                        try:
                            idx = json.loads(open(idx_path, encoding="utf-8").read())
                            if topic in idx:
                                idx.remove(topic)
                                with open(idx_path, "w", encoding="utf-8") as kf:
                                    json.dump(idx, ensure_ascii=False, indent=2, fp=kf)
                        except Exception:
                            pass
                    result = f"知识「{topic}」已从知识库中移除~"
                    print(f"[kb] Deleted: {topic}")
                    try:
                        llm_client.refresh_kb()
                    except Exception as e:
                        print(f"[kb] Refresh after delete FAILED: {e}")
                else:
                    result = f"知识库里没有找到「{topic}」这个主题呢~"

            elif func_name == "course_advisor" and result.startswith("__course__:advise:"):
                raw = result[len("__course__:advise:"):]
                parts = raw.split("|||", 3)
                question = parts[0] if len(parts) > 0 else ""
                semester_str = parts[1] if len(parts) > 1 else "0"
                direction = parts[2] if len(parts) > 2 else ""
                completed = parts[3] if len(parts) > 3 else ""
                import os as _os
                kb_path = "data/knowledge/YOUR_MAJOR专业2024培养方案.md"
                kb_text = ""
                if _os.path.exists(kb_path):
                    with open(kb_path, "r", encoding="utf-8") as _f:
                        kb_text = _f.read()
                prompt = "你是课程顾问小奈。请根据以下培养方案回答同学的选课问题。"
                prompt += "\n\n【同学的问题】" + question
                if semester_str and semester_str != "0":
                    prompt += "\n【同学当前学期】第" + semester_str + "学期"
                if direction:
                    prompt += "\n【同学专业方向】" + direction
                if completed:
                    prompt += "\n【同学已修课程】" + completed
                prompt += "\n\n请基于以下培养方案给出精准建议。必须引用具体的课程编号、学分、学时、先修课要求。"
                prompt += "优先推荐与同学当前学期匹配的课程。如果同学方向未确定，说明两个方向的差异。"
                prompt += "\n\n【培养方案知识库】\n" + kb_text[:8000]
                prompt += "\n\n请用口语化、亲切的语气回复（你是小奈），控制在300字以内，不用markdown格式。"
                prompt += "\n【称呼规则】除非明确知道老师/同学的性别，否则一律用「ta」，禁止用「他」「她」。"
                result = prompt
                print(f"[course_advisor] Prompt built ({len(prompt)} chars)")

            elif func_name == "teacher_advisor" and result.startswith("__teacher__:advise:"):
                raw = result[len("__teacher__:advise:"):]
                parts = raw.split("|||", 2)
                question = parts[0] if len(parts) > 0 else ""
                teacher_name = parts[1] if len(parts) > 1 else ""
                research_interest = parts[2] if len(parts) > 2 else ""
                import os as _os
                kb_path = "data/knowledge/汽车学院教师信息.md"
                kb_text = ""
                if _os.path.exists(kb_path):
                    with open(kb_path, "r", encoding="utf-8") as _f:
                        kb_text = _f.read()
                prompt = "你是教师信息助手小奈，请根据以下教师信息库回答同学的问题。"
                prompt += "\n\n【同学的问题】" + question
                if teacher_name:
                    prompt += "\n【同学提到的老师】" + teacher_name
                if research_interest:
                    prompt += "\n【同学感兴趣的方向】" + research_interest
                prompt += "\n\n请基于以下教师信息给出精准回答。必须引用具体的研究方向、职称、邮箱、个人简介等。"
                prompt += "如果同学问某位具体老师，只介绍这位老师。如果问某个方向有哪些老师，列出所有相关老师。"
                prompt += "如果同学问找导师建议，根据研究方向匹配推荐合适的老师。"
                prompt += "\n\n【教师信息知识库】\n" + kb_text[:8000]
                prompt += "\n\n请用口语化、亲切的语气回复（你是小奈），控制在300字以内，不用markdown格式。"
                prompt += "\n【称呼规则】除非明确知道老师/同学的性别，否则一律用「ta」，禁止用「他」「她」。"
                result = prompt
                print(f"[teacher_advisor] Prompt built ({len(prompt)} chars)")

            elif func_name == "admin_add_memory" and result.startswith("__admin__:add_mem:"):
                parts = result.split(":")
                qq = int(parts[-2])
                fact = parts[-1]
                memory_store.remember(qq, fact)
                result = f"已为 QQ {qq} 添加记忆：{fact}"

            elif func_name == "admin_news_control" and result.startswith("__admin__:news:"):
                from src.plugins.scheduler import get_news_config, update_news_config
                parts = result[len("__admin__:news:"):].split(":", 2)
                action = parts[0]
                value = parts[1] if len(parts) > 1 else ""
                cfg = get_news_config()
                if action == "enable":
                    update_news_config(enabled=True)
                    result = "每日新闻推送已开启 ✨ 每天 8:00 和 18:00 自动推送~"
                elif action == "disable":
                    update_news_config(enabled=False)
                    result = "每日新闻推送已关闭。"
                elif action == "add_recipient" and value:
                    qq = int(value)
                    cfg = update_news_config(recipients=list(set(cfg.get("recipients", []) + [qq])))
                    result = f"已将 QQ {qq} 加入新闻推送列表~ 当前接收者：{cfg['recipients']}"
                elif action == "remove_recipient" and value:
                    qq = int(value)
                    cfg = update_news_config(recipients=[r for r in cfg.get("recipients", []) if r != qq])
                    result = f"已将 QQ {qq} 从推送列表移除。当前接收者：{cfg['recipients']}"
                elif action == "add_group" and value:
                    gid = int(value)
                    cfg = update_news_config(groups=list(set(cfg.get("groups", []) + [gid])))
                    result = f"已将群 {gid} 加入新闻推送~ 当前推送群：{cfg['groups']}"
                elif action == "remove_group" and value:
                    gid = int(value)
                    cfg = update_news_config(groups=[g for g in cfg.get("groups", []) if g != gid])
                    result = f"已将群 {gid} 从推送移除。当前推送群：{cfg['groups']}"
                elif action == "set_custom_message" and value:
                    update_news_config(custom_message=value)
                    result = f"自定义推送语已更新~ 每次推送时会加上这句。当前：{value}"
                elif action == "set_count" and value:
                    count = int(value)
                    update_news_config(count=count)
                    result = f"每日新闻条数已设为 {count} 条~"
                elif action == "show_config":
                    result = f"📋 新闻推送配置：\n启用：{cfg['enabled']}\n接收者：{cfg['recipients']}\n推送群：{cfg['groups']}\n条数：{cfg['count']}条/次"
                elif action == "push_now":
                    from src.plugins.scheduler import run_news_push_for_user
                    ttype = parts[2] if len(parts) > 2 else ""
                    is_grp = isinstance(event, GroupMessageEvent)
                    target = event.group_id if is_grp else user_id
                    if value:
                        try:
                            target = int(value)
                            if ttype == "group":
                                is_grp = True
                            elif ttype == "private":
                                is_grp = False
                        except ValueError:
                            pass
                    # 群发但没指定群号 → 让 LLM 问清楚
                    if is_grp and (not value or target == user_id):
                        result = "同学想发到哪个群呀？告诉小奈群号就好~"
                        break
                    try:
                        await run_news_push_for_user(target, is_group=is_grp)
                        where = f"群 {target}" if is_grp else f"用户 {target}"
                        result = f"新闻已推送到 {where}。"
                    except Exception as e:
                        result = f"新闻推送失败：{e}"
                elif action == "push_campus":
                    from src.plugins.scheduler import get_news_config
                    if not get_news_config().get("campus_enabled", True):
                        result = "校园早报功能已暂停（VPN不可用）。需要时说'开启校园早报'即可~"
                    else:
                        import re
                        from src.whut.client import whut_client
                        notices = []
                        # Fetch i.whut via WebVPN
                        try:
                            html = await whut_client.get_page_html(
                                "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xxtg/gztz_9764.shtml"
                            )
                            seen = set()
                            for m in re.finditer(
                                r'<a[^>]*href="(https://webvpn\.whut\.edu\.cn[^"]*)"[^>]*title="([^"]*)"[^>]*>',
                                html, re.DOTALL
                            ):
                                url = m.group(1)
                                title = m.group(2).strip()
                                if url not in seen and len(title) > 10:
                                    seen.add(url)
                                    notices.append({"title": title, "url": url})
                            print(f"[campus] WebVPN fetched {len(notices)} notices for push")
                        except Exception as ex:
                            print(f"[campus] WebVPN fetch failed: {ex}")
                        lines = ["🏫 今日重要通知"]
                        for i in range(min(10, len(notices))):
                            n = notices[i]
                            lines.append(str(i+1) + ". " + n["title"] + "\n   " + n["url"])
                        if not notices:
                            result = "校园通知暂时无法获取（WebVPN 连接失败，请稍后重试）。"
                        else:
                            if value:
                                try:
                                    target_id = int(value)
                                    is_grp = target_id > 999999
                                    from nonebot import get_bot
                                    bot = get_bot()
                                    campus_msg = chr(10).join(lines)
                                    if is_grp:
                                        await bot.send_group_msg(group_id=target_id, message=campus_msg)
                                        result = f"校园早报已推送到群 {target_id}。"
                                    else:
                                        await bot.send_private_msg(user_id=target_id, message=campus_msg)
                                        result = f"校园早报已推送到用户 {target_id}。"
                                except Exception as e:
                                    result = f"校园早报推送失败：{e}"
                            else:
                                result = chr(10).join(lines)
                                result += "\n\n[重要] 你必须把以上所有标题和链接逐条转发给用户，不要省略。这是校园早报内容。"

                elif action == "remind" and value:
                    from src.plugins.scheduler import schedule_reminder
                    parts = value.split("|", 2)
                    delay = int(parts[0]) if len(parts) > 0 else 300
                    msg = parts[1] if len(parts) > 1 else "班长让我提醒你~"
                    is_group = len(parts) > 2 and parts[2] == "group"
                    import asyncio as _asyncio
                    _asyncio.create_task(schedule_reminder(user_id, msg, delay, is_group))
                    result = f"好的~ {delay}秒后我会{'在群里' if is_group else ''}提醒：{msg[:50]}"
                else:
                    result = f"未知操作：{action}"

            # ---- 天气控制处理 ----
            elif func_name == "admin_weather_control" and result.startswith("__admin__:weather:"):
                from src.plugins.scheduler import get_weather_config, update_weather_config
                parts = result[len("__admin__:weather:"):].split(":", 2)
                action = parts[0]
                value = parts[1] if len(parts) > 1 else ""
                cfg = get_weather_config()
                if action == "enable":
                    update_weather_config(enabled=True)
                    result = "每日天气推送已开启 ☀️ 每天早上 7:30 自动推送~"
                elif action == "disable":
                    update_weather_config(enabled=False)
                    result = "每日天气推送已关闭。"
                elif action == "set_city" and value:
                    update_weather_config(city=value)
                    result = f"天气预报城市已设为 {value}~"
                elif action == "add_user" and value and value.isdigit():
                    qq = int(value)
                    cur_list = list(cfg.get("recipients", []))
                    if qq not in cur_list:
                        cur_list.append(qq)
                        update_weather_config(recipients=cur_list)
                        result = f"已将 QQ {qq} 加入每日天气推送~ 每天早上6:50会收到天气预报 (｡･ω･｡)"
                    else:
                        result = f"QQ {qq} 已经在推送列表里啦~"
                elif action == "remove_user" and value and value.isdigit():
                    qq = int(value)
                    cur_list = [u for u in cfg.get("recipients", []) if u != qq]
                    update_weather_config(recipients=cur_list)
                    result = f"已将 QQ {qq} 从天气推送中移除~"
                elif action == "add_group" and value and value.isdigit():
                    gid = int(value)
                    cur_groups = list(cfg.get("groups", []))
                    if gid not in cur_groups:
                        cur_groups.append(gid)
                        update_weather_config(groups=cur_groups)
                        result = f"已将群 {gid} 加入每日天气推送~ 每天早上6:50会收到天气预报 ✨"
                    else:
                        result = f"群 {gid} 已经在推送列表里啦~"
                elif action == "remove_group" and value and value.isdigit():
                    gid = int(value)
                    cur_groups = [g for g in cfg.get("groups", []) if g != gid]
                    update_weather_config(groups=cur_groups)
                    result = f"已将群 {gid} 从天气推送中移除~"
                elif action == "show_config":
                    result = f"📋 天气推送配置：\n启用：{cfg['enabled']}\n城市：{cfg['city']}\n接收者：{cfg['recipients']}\n推送群：{cfg['groups']}"
                elif action == "push_now":
                    from src.plugins.scheduler import run_weather_push_for_user
                    import re as _re
                    ttype = parts[2] if len(parts) > 2 else ""
                    is_grp = isinstance(event, GroupMessageEvent) or ttype == "group"
                    target = event.group_id if isinstance(event, GroupMessageEvent) else user_id
                    city_override = ""
                    day_offset = -1

                    # Parse value: could be QQ number, group number, or city name
                    if value:
                        # Check for day keywords
                        day_map = {"今天": 0, "明日": 1, "明天": 1, "后天": 2, "后日": 2}
                        val_lower = value.strip()
                        for kw, off in day_map.items():
                            if kw in val_lower:
                                day_offset = off
                                val_lower = val_lower.replace(kw, "").strip()
                                break

                        # Check if remaining is numeric (QQ/group ID)
                        if val_lower.isdigit():
                            target = int(val_lower)
                            # ttype already handled above
                        elif val_lower:
                            # Non-numeric → city name
                            city_override = val_lower

                    try:
                        from src.llm.tools_impl import get_weather
                        weather_result = await get_weather(city_override or "武汉", day_offset=day_offset)
                        if is_grp:
                            # Send to group(s)
                            groups_to_push = [target] if target != user_id else cfg.get("groups", [])
                            if not groups_to_push:
                                result = "同学想发到哪个群呀？告诉小奈群号就好~"
                            else:
                                from nonebot import get_bot
                                bot = get_bot()
                                pushed = []
                                for gid in groups_to_push:
                                    try:
                                        await bot.send_group_msg(group_id=gid, message=weather_result)
                                        pushed.append(str(gid))
                                        print(f"[weather] Manual push to group {gid}")
                                    except Exception as e:
                                        print(f"[weather] Push to group {gid} failed: {e}")
                                if pushed:
                                    result = f"__direct__:已经帮同学把天气发到群 {', '.join(pushed)} 啦 (｡･ω･｡)"
                                else:
                                    result = "唔…天气推送到群里失败了，可能是群号不对？"
                        else:
                            result = f"__direct__:{weather_result}"
                    except Exception as e:
                        result = f"天气查询失败：{e}"
                else:
                    result = f"未知操作：{action}"


            # ---- 地震预警处理 ----
            # ---- 灾害预警总控 ----
            elif func_name == "disaster_control" and result.startswith("__admin__:disaster:"):
                action = result[len("__admin__:disaster:"):].strip()
                from src.plugins.earthquake import _load_config as _eq_load, _save_config as _eq_save, _ensure_job as _eq_ensure
                from src.plugins.weather_warning import _load_config as _ww_load, _save_config as _ww_save, _ensure_job as _ww_ensure
                target_id = str(event.group_id if hasattr(event, "group_id") and event.group_id else event.user_id)
                eq_cfg = _eq_load()
                ww_cfg = _ww_load()
                eq_groups = eq_cfg.setdefault("groups", [])
                ww_groups = ww_cfg.setdefault("groups", [])
                if action == "subscribe":
                    added = []
                    if target_id not in eq_groups:
                        eq_groups.append(target_id)
                        _eq_save(eq_cfg)
                        _eq_ensure(eq_cfg)
                        added.append("地震")
                    if target_id not in ww_groups:
                        ww_groups.append(target_id)
                        ww_cfg["enabled"] = True
                        _ww_save(ww_cfg)
                        _ww_ensure(ww_cfg)
                        added.append("气象")
                    if added:
                        result = "已开启" + "、".join(added) + "预警"
                    else:
                        result = "本群已订阅全部灾害预警"
                elif action == "unsubscribe":
                    if target_id in eq_groups:
                        eq_groups.remove(target_id)
                        _eq_save(eq_cfg)
                    if target_id in ww_groups:
                        ww_groups.remove(target_id)
                        _ww_save(ww_cfg)
                    result = "已关闭灾害预警"
                elif action == "status":
                    eq_sub = target_id in eq_groups
                    ww_sub = target_id in ww_groups
                    result = f"灾害预警: 地震={eq_sub}, 气象={ww_sub}"

            elif func_name == "earthquake_control" and result.startswith("__admin__:earthquake:"):
                action = result[len("__admin__:earthquake:"):].strip()
                from src.plugins.earthquake import _load_config, _save_config, _ensure_job, _stop_job
                cfg = _load_config()
                groups = cfg.setdefault("groups", [])
                target_id = str(event.group_id if hasattr(event, "group_id") and event.group_id else event.user_id)
                if action == "subscribe":
                    if target_id not in groups:
                        groups.append(target_id)
                        _save_config(cfg)
                        _ensure_job(cfg)
                        result = "地震预警已开启！"
                    else:
                        result = "本群已订阅地震预警~"
                elif action == "unsubscribe":
                    if target_id in groups:
                        groups.remove(target_id)
                        _save_config(cfg)
                        if not groups:
                            _stop_job()
                        result = "地震预警已关闭~"
                    else:
                        result = "本群未订阅地震预警~"
                elif action == "status":
                    subscribed = target_id in groups
                    s = "enabled" if cfg.get("enabled", True) else "paused"
                    result = f"地震预警状态: {s}, 已订阅={subscribed}, 推送群数={len(groups)}"

            elif func_name == "weather_control" and result.startswith("__admin__:weather_ctrl:"):
                action = result[len("__admin__:weather_ctrl:"):].strip()
                from src.plugins.weather_warning import _load_config, _save_config, _ensure_job, _stop_job
                cfg = _load_config()
                groups = cfg.setdefault("groups", [])
                target_id = str(event.group_id if hasattr(event, "group_id") and event.group_id else event.user_id)
                if action == "subscribe":
                    if target_id not in groups:
                        groups.append(target_id)
                        cfg["enabled"] = True
                        _save_config(cfg)
                        _ensure_job(cfg)
                        result = "气象预警已开启！"
                    else:
                        result = "本群已订阅气象预警~"
                elif action == "unsubscribe":
                    if target_id in groups:
                        groups.remove(target_id)
                        _save_config(cfg)
                        if not groups:
                            _stop_job()
                        result = "气象预警已关闭~"
                    else:
                        result = "本群未订阅气象预警~"
                elif action == "status":
                    subscribed = target_id in groups
                    s = "enabled" if cfg.get("enabled", True) else "paused"
                    result = f"气象预警状态: {s}, 已订阅={subscribed}, 推送群数={len(groups)}"

            # ---- 闹钟处理 ----
            elif func_name == "set_alarm" and result.startswith("__alarm__:set:"):
                raw = result[len("__alarm__:set:"):]
                parts = raw.split("|", 3)
                time_str = parts[0]
                msg = parts[1].replace("/", "|") if len(parts) > 1 else "闹钟响了~"
                is_group = len(parts) > 2 and parts[2] == "1"
                target = int(parts[3]) if len(parts) > 3 and parts[3] and parts[3] != "0" else user_id
                from src.plugins.scheduler import schedule_alarm
                alarm_id = schedule_alarm(target, msg, time_str, is_group)
                if alarm_id:
                    result = f"好的~ 闹钟已设置：{time_str} 提醒「{msg}」(ID: {alarm_id[:12]})"
                else:
                    result = "时间格式不太对呢…试试'08:00'这样的？"

            elif func_name == "list_alarms":
                from src.plugins.scheduler import list_alarms as _la
                alarms = _la(user_id)
                if alarms:
                    lines = [f"⏰ {a['time'][:16]} — {a['message']} (ID:{a['id'][:12]})" for a in alarms[-5:]]
                    result = "你的闹钟：\n" + "\n".join(lines)
                else:
                    result = "你还没有设置闹钟呢~"

            elif func_name == "cancel_alarm" and result.startswith("__alarm__:cancel:"):
                aid = result.split(":", 2)[-1]
                from src.plugins.scheduler import cancel_alarm as _ca
                _ca(aid)
                result = "已取消这个闹钟~"

            elif func_name == "group_lucky_draw" and result.startswith("__lucky__:draw:"):
                if not isinstance(event, GroupMessageEvent):
                    result = "抽签功能只能在群里使用哦~"
                else:
                    raw = result[len("__lucky__:draw:"):]
                    parts = raw.split(":", 1)
                    count = int(parts[0]) if parts[0] else 1
                    exclude_str = parts[1] if len(parts) > 1 else ""
                    exclude = ["辅导员", "班主任", "班长"]
                    if exclude_str:
                        exclude = [x.strip() for x in exclude_str.split(",") if x.strip()]
                    from nonebot import get_bot
                    from src.plugins.lucky_draw import do_lucky_draw
                    bot = get_bot()
                    try:
                        draw_msg = await do_lucky_draw(bot, event.group_id, user_id, count, exclude)
                        await bot.send_group_msg(group_id=event.group_id, message=draw_msg)
                        result = "抽签完成，结果已发到群里。注意：绝对不要提排除了谁，不要提排除规则，只说抽签完成了就行。"
                    except Exception as e:
                        result = f"抽签失败：{e}"

            elif func_name == "admin_send_message" and result.startswith("__admin__:send:"):
                parts = result[len("__admin__:send:"):].split(":", 2)
                target = int(parts[0])
                is_group = parts[1] == "1"
                if target == 0:
                    result = "请指定群号！班级通知群=CLASS_GROUP_PLACEHOLDER，班级闲聊群=CHAT_GROUP_PLACEHOLDER，资料共享群=RESOURCE_GROUP_PLACEHOLDER。要发到哪个群？"
                else:
                    msg = parts[2] if len(parts) > 2 else ""
                    from nonebot import get_bot
                    try:
                        bot = get_bot()
                        if is_group:
                            await bot.send_group_msg(group_id=target, message=msg)
                        else:
                            await bot.send_private_msg(user_id=target, message=msg)
                        result = "__direct__:已发送。"
                    except Exception as e:
                        result = f"发送失败：{str(e)[:100]}"

            elif func_name == "news_control" and result.startswith("__admin__:news_ctrl:"):
                action = result[len("__admin__:news_ctrl:"):]
                if action == "subscribe":
                    result = "✅ 本群已订阅每日新闻推送（18:00）"
                elif action == "unsubscribe":
                    result = "✅ 已取消本群新闻推送"
                elif action == "status":
                    result = f"📰 新闻推送状态：本群已订阅，推送时间18:00"
                else:
                    result = f"未知操作：{action}"

            elif func_name == "admin_group_control" and result.startswith("__admin__:group:"):
                parts = result[len("__admin__:group:"):].split(":", 1)
                action = parts[0]
                value = parts[1] if len(parts) > 1 else ""
                cfg = _load_group_config()
                if action == "add_blacklist" and value:
                    gid = int(value)
                    bl = cfg.get("blacklist", [])
                    if gid not in bl:
                        bl.append(gid)
                        cfg["blacklist"] = bl
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 加入黑名单。小奈会旁听并提取知识，但绝不发消息。"
                    else:
                        result = f"群 {gid} 已在黑名单中。"
                elif action == "remove_blacklist" and value:
                    gid = int(value)
                    bl = cfg.get("blacklist", [])
                    if gid in bl:
                        bl.remove(gid)
                        cfg["blacklist"] = bl
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 从黑名单移除。"
                    else:
                        result = f"群 {gid} 不在黑名单中。"
                elif action in ("add_class_group", "add_normal_group", "add_mute_group", "add_chat_group") and value:
                    gid = int(value)
                    cg = cfg.get("class_groups", [])
                    if gid not in cg:
                        cg.append(gid)
                        cfg["class_groups"] = cg
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 设为班级群（仅 @小奈 回复）。"
                    else:
                        result = f"群 {gid} 已是班级群。"
                elif action == "remove_class_group" and value:
                    gid = int(value)
                    cg = cfg.get("class_groups", [])
                    if gid in cg:
                        cg.remove(gid)
                        cfg["class_groups"] = cg
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 从班级群移除。"
                    else:
                        result = f"群 {gid} 不是班级群。"
                elif action in ("remove_class_group", "remove_normal_group", "remove_mute_group", "remove_chat_group") and value:
                    gid = int(value)
                    cg = cfg.get("chat_groups", [])
                    if gid not in cg:
                        cg.append(gid)
                        cfg["chat_groups"] = cg
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 设为闲聊群，小奈会主动聊天~"
                    else:
                        result = f"群 {gid} 已是闲聊群。"
                elif action == "remove_chat_group" and value:
                    gid = int(value)
                    cg = cfg.get("chat_groups", [])
                    if gid in cg:
                        cg.remove(gid)
                        cfg["chat_groups"] = cg
                        _save_group_config(cfg)
                        result = f"已将群 {gid} 从闲聊群移除。"
                    else:
                        result = f"群 {gid} 不是闲聊群。"
                elif action == "show_config":
                    result = (
                        f"📋 群聊配置：\n"
                        f"班级群：{cfg.get('class_groups', [])}\n"
                        f"闲聊群：{cfg.get('chat_groups', [])}\n"
                        f"黑名单：{cfg.get('blacklist', [])}"
                    )
                else:
                    result = f"未知操作：{action}"

            tool_msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        # 如果工具返回了完整答案（通知公告/查他人好感度等格式化内容），直接返回
        # Collect all __direct__: results, return immediately on other special prefixes
        direct_results = []
        for tm in tool_msgs:
            c = tm.get("content", "")
            if c.startswith("__direct__:"):
                import re as _re
                r = c.replace("__direct__:", "", 1)
                r = _re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'', r)
                r = _re.sub(r'#{1,4}\s*', '', r)
                direct_results.append(r)
            elif c.startswith("通知公告") or c.startswith("已转告") or c.startswith("已匿名转告"):
                import re as _re
                result = c
            elif func_name == "sing_song" and result.startswith("__song__:"):
                import re as _re
                parts = result[len("__song__:"):].split(":", 1)
                file_path = parts[0]
                song_name = parts[1] if len(parts) > 1 else "song"
                try:
                    is_grp = isinstance(event, GroupMessageEvent)
                    cq = "[CQ:record,file=file://" + file_path + "]"
                    from nonebot import get_bot
                    bot = get_bot()
                    if target_qq > 0:
                        await bot.send_private_msg(user_id=target_qq, message=cq)
                    elif is_grp:
                        await bot.send_group_msg(group_id=event.group_id, message=cq)
                    else:
                        await bot.send_private_msg(user_id=user_id, message=cq)
                    result = ""
                except Exception as e:
                    result = "Song failed: " + str(e)[:100]
                if result.startswith("__direct__:"):
                    result = result.replace("__direct__:", "", 1)
                result = _re.sub(r"\*{1,3}([^*]+?)\*{1,3}", r"", result)
                result = _re.sub(r"#{1,4}\s*", "", result)
                return result
            elif func_name == "say_voice" and result.startswith("__voice__:"):
                import re as _re
                parts = result[len("__voice__:"):].split(":", 2)
                try:
                    target_qq = int(parts[0])
                except (ValueError, IndexError):
                    target_qq = 0
                file_path = parts[1] if len(parts) > 1 else ""
                preview = parts[2] if len(parts) > 2 else "voice"
                try:
                    is_grp = isinstance(event, GroupMessageEvent)
                    cq = "[CQ:record,file=file://" + file_path + "]"
                    from nonebot import get_bot
                    bot = get_bot()
                    if target_qq > 0:
                        await bot.send_private_msg(user_id=target_qq, message=cq)
                    elif is_grp:
                        await bot.send_group_msg(group_id=event.group_id, message=cq)
                    else:
                        await bot.send_private_msg(user_id=user_id, message=cq)
                    result = ""
                except Exception as e:
                    result = "Voice failed: " + str(e)[:100]
                if result.startswith("__direct__:"):
                    result = result.replace("__direct__:", "", 1)
                result = _re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'', result)
                result = _re.sub(r'#{1,4}\s*', '', result)
                return result
        if direct_results:
            return chr(10).join(direct_results)

        history.append(assistant_msg)
        history.extend(tool_msgs)

    # Force-final: one last call WITHOUT tools to synthesize answer from gathered context
    print("[ai_handler] FORCE FINAL: calling without tools...")
    try:
        msgs = _safe_truncate(history)
        resp = await llm_client.chat(msgs, tools=None)
        content = (resp.get("content") or "").strip()
        if content:
            print(f"[ai_handler] force final OK ({len(content)} chars)")
            import re as _re
            content = _re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'', content)
            content = _re.sub(r'#{1,4}\s*', '', content)
            return content
    except Exception as _e:
        print(f"[ai_handler] force final failed: {_e}")

    print("[ai_handler] MAX ITERATIONS EXCEEDED (fallback)")
    import re as _re
    content_stripped = "小奈处理超时了，请重新问我吧。"
    content_stripped = _re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'', content_stripped)
    content_stripped = _re.sub(r'#{1,4}\s*', '', content_stripped)
    return content_stripped
