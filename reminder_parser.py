# -*- coding: utf-8 -*-
"""自然语言定时提醒解析器 (纯函数, 无 I/O).

parse_reminder(msg, now, uid, gid, at_target) -> action dict | None

action:
  set:    {"action":"set", "send_at":"YYYY-MM-DD HH:MM", "recurring":None|"daily"|"weekly"|"monthly",
            "recur_dow":None|int, "recur_dom":None|int, "content":str, "user_id":int, "group_id":int|None}
  list:   {"action":"list"}
  delete: {"action":"delete", "match":str}
  clear:  {"action":"clear"}
"""
import re
from datetime import datetime, timedelta

# ---------- 意图 ----------
_CLEAR_RE = re.compile(
    r"清空.{0,8}提醒|删除所有(?:定制|定时)?提醒|取消所有(?:定制|定时)?提醒|"
    r"清掉提醒|清理所有(?:定制|定时)?提醒|全部取消(?:定制|定时)?提醒"
)
_LIST_RE = re.compile(r"查看.{0,8}提醒|查看所有|所有提醒|提醒任务|查看定时任务|列出提醒|有哪些提醒|我的提醒|看看提醒|显示提醒|什么提醒")
_DEL_RE = re.compile(
    r"删除提醒|取消提醒|取消.{0,15}提醒|删除.{0,15}提醒|删掉.{0,10}提醒|"
    r"移除.{0,10}提醒|去掉.{0,10}提醒|把.{0,12}提醒.{0,4}(删|取|取消)|"
    r"(?:删除|取消|删掉|移除|去掉)\s*20\d{2}[./年-]\d{1,2}[./月-]\d{1,2}(?:日|号)?(?:的(?:提醒)?|那天|日期)?"
)
_COMMAND_PREFIX_RE = re.compile(r"^(?:(?:请|帮我|帮忙|麻烦)\s*)+")
_EXPLANATION_PREFIX_RE = re.compile(
    r"^(?:请解释|解释一下|解释|说明一下|说明|我想知道|告诉我|怎么理解|如何理解|什么叫|为什么)"
)
_QUOTED_EXPLANATION_RE = re.compile(
    r"^[\"“].*(?:提醒|定时|闹钟).*?[\"”](?:是什么意思|什么意思|怎么理解|如何理解)$"
)
_SET_RE = re.compile(r"提醒|定时|闹钟|设个提醒|设置提醒")

# ---------- 重复 ----------
_WEEK_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_RECUR_RE = re.compile(r"每天|每周(?P<dow>[一二三四五六日天])|每星期(?P<dow2>[一二三四五六日天])|每月(?P<dom>\d{1,2})[日号]?")

# ---------- 时间 ----------
_PERIOD_HOUR = {"凌晨": 0, "早晨": 6, "早上": 6, "上午": 9, "中午": 12,
                "下午": 13, "傍晚": 18, "晚上": 18, "夜晚": 20, "夜里": 22}
_TIME_RE = re.compile(
    r"(?:(?P<peri>凌晨|早晨|早上|上午|中午|下午|傍晚|晚上|夜晚|夜里))?"
    r"(?P<h>\d{1,2})[:：点](?P<mi>\d{1,2})?(?:[:：]\d{2})?(?P<half>半|一刻|三刻|整)?"
)
_ABS_DATE_RE = re.compile(r"(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})[日号]?")
_MD_DATE_RE = re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})[日号]?")
_DUR_RE = re.compile(r"(?P<n>\d{1,3}|半)(?P<u>分钟|小时|天|星期|周)后")
_REL_DAY_RE = re.compile(r"今天|明天|后天|大后天|明早|明晚|今晚|下周[一二三四五六日天]|周[一二三四五六日天]")

_PREFIX_RE = re.compile(r"^(提醒我|帮我提醒|请提醒|提醒|定时|闹钟|请|帮我|设置|设个|设一个|记得)")


def _parse_clock(msg):
    """解析 时分. 返回 (hour, minute) 或 None."""
    m = _TIME_RE.search(msg)
    if not m:
        return None
    hour = int(m.group("h"))
    minute = int(m.group("mi")) if m.group("mi") else 0
    half = m.group("half")
    if half == "半":
        minute = 30
    elif half == "一刻":
        minute = 15
    elif half == "三刻":
        minute = 45
    peri = m.group("peri")
    if peri in ("下午", "傍晚", "晚上", "夜晚", "夜里") and hour < 12:
        hour += 12
    elif peri == "中午" and hour < 12:
        hour = 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _rel_day_offset(msg):
    """相对日. 返回 (date, end_pos) 或 None."""
    if "大后天" in msg:
        return None, 0
    if "后天" in msg:
        return 2, 0
    if "明天" in msg:
        return 1, 0
    if "今天" in msg:
        return 0, 0
    m = re.search(r"下周([一二三四五六日天])", msg)
    if m:
        return 7 + (_WEEK_CN[m.group(1)] - 0) % 7, m.end()
    m = re.search(r"周([一二三四五六日天])", msg)
    if m:
        return (_WEEK_CN[m.group(1)] - 0) % 7, m.end()
    return None, 0


def _resolve(msg, now):
    """返回 (send_at_str, recurring, dow, dom) 或 (None, rec, dow, dom)."""
    # 1. 重复
    rm = _RECUR_RE.search(msg)
    rec = dow = dom = None
    if rm:
        if "每天" in rm.group(0):
            rec = "daily"
        elif rm.group("dow") or rm.group("dow2"):
            rec = "weekly"
            dow = _WEEK_CN[rm.group("dow") or rm.group("dow2")]
        elif rm.group("dom"):
            rec = "monthly"
            dom = int(rm.group("dom"))
    # 2. 相对时长
    dm = _DUR_RE.search(msg)
    if dm:
        n_raw = dm.group("n"); u = dm.group("u")
        base = now
        if n_raw == "半":
            if u == "小时":
                base = now + timedelta(minutes=30)
            elif u == "天":
                base = now + timedelta(hours=12)
            else:
                return None, None, None, None
        else:
            n = int(n_raw)
            if u == "分钟":
                base = now + timedelta(minutes=n)
            elif u == "小时":
                base = now + timedelta(hours=n)
            elif u == "天":
                base = now + timedelta(days=n)
            else:
                base = now + timedelta(weeks=n)
        return base.strftime("%Y-%m-%d %H:%M"), None, None, None
    # 3. 时钟
    clock = _parse_clock(msg)
    # 4. 日期
    date = None
    rd, _ = _rel_day_offset(msg)
    if rd is not None:
        date = now.date() + timedelta(days=rd)
    if date is None:
        m = _ABS_DATE_RE.search(msg)
        if m:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        else:
            m = _MD_DATE_RE.search(msg)
            if m:
                month, day = int(m.group("m")), int(m.group("d"))
                year = now.year
                if (month, day) <= (now.month, now.day):
                    year += 1
                date = datetime(year, month, day).date()
    if rec:
        # 重复提醒
        hour = clock[0] if clock else 9
        minute = clock[1] if clock else 0
        return _next_occurrence(now, rec, dow, dom, hour, minute).strftime("%Y-%m-%d %H:%M"), rec, dow, dom
    if clock is None:
        if date is not None:
            # 有日期没时间 → 默认 09:00
            hour, minute = 9, 0
        else:
            return None, None, None, None
    else:
        hour, minute = clock
    if date is None:
        date = now.date()
        if (hour, minute) <= (now.hour, now.minute):
            date += timedelta(days=1)
    return datetime(date.year, date.month, date.day, hour, minute).strftime("%Y-%m-%d %H:%M"), None, None, None


def _next_occurrence(now, rec, dow, dom, hour, minute):
    if rec == "daily":
        dt = datetime(now.year, now.month, now.day, hour, minute)
        if dt <= now:
            dt += timedelta(days=1)
        return dt
    if rec == "weekly":
        d = now.date()
        days_ahead = (dow - d.weekday() + 7) % 7
        dt = datetime(d.year, d.month, d.day, hour, minute) + timedelta(days=days_ahead)
        if dt <= now:
            dt += timedelta(days=7)
        return dt
    if rec == "monthly":
        d = now.date()
        y, m = d.year, d.month
        try:
            dt = datetime(y, m, dom, hour, minute)
        except ValueError:
            dt = None
        if dt is None or dt <= now:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            try:
                dt = datetime(y, m, dom, hour, minute)
            except ValueError:
                dt = datetime(y, m, 28, hour, minute)
        return dt
    return now


def _extract_content(msg):
    ends = []
    for pat in (_ABS_DATE_RE, _MD_DATE_RE, _TIME_RE, _DUR_RE, _REL_DAY_RE, _RECUR_RE):
        for m in pat.finditer(msg):
            ends.append(m.end())
    if not ends:
        for m in re.finditer(r"提醒我|提醒|闹钟", msg):
            ends.append(m.end())
    if not ends:
        return "提醒"
    content = msg[max(ends):].strip()
    if content.startswith("@") or content.startswith("[CQ:at"):
        content = re.sub(r"^@\d+\s*|^\[CQ:at,qq=\d+\]\s*", "", content).strip()
    content = _PREFIX_RE.sub("", content).strip()
    content = content.strip("，。！？,;!? ：:")
    return content or "提醒"


def parse_reminder(msg, now, uid, gid=0, at_target=None):
    if not msg or not isinstance(msg, str):
        return None
    command = _COMMAND_PREFIX_RE.sub("", msg.strip()).rstrip("。！？!?，, ")
    if _CLEAR_RE.fullmatch(command) and "提醒" in command:
        return {"action": "clear"}
    if _LIST_RE.fullmatch(command):
        return {"action": "list"}
    if _DEL_RE.fullmatch(command):
        return {"action": "delete", "match": command}
    text = msg.strip()
    if (
        (_EXPLANATION_PREFIX_RE.match(text) and _SET_RE.search(text))
        or _QUOTED_EXPLANATION_RE.fullmatch(text)
    ):
        return None
    if not _SET_RE.search(msg):
        return None
    send_at, rec, dow, dom = _resolve(msg, now)
    if send_at is None:
        return None
    content = _extract_content(msg)
    target_user = at_target or uid
    m_at = re.search(r"\[CQ:at,qq=(\d+)\]", msg)
    if m_at:
        target_user = int(m_at.group(1))
    return {
        "action": "set", "send_at": send_at, "recurring": rec,
        "recur_dow": dow, "recur_dom": dom, "content": content,
        "user_id": target_user, "group_id": gid if gid else None,
    }
