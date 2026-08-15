#!/usr/bin/env python3
"""Exam countdown system. CLI usage:

  python3 admin/exam_countdown.py add "Exam Name" 2026-06-15 [--type cet4] [--remind 7]
  python3 admin/exam_countdown.py delete "Exam Name"
  python3 admin/exam_countdown.py list
  python3 admin/exam_countdown.py days "Exam Name"
  python3 admin/exam_countdown.py push
  python3 admin/exam_countdown.py archive
"""
import sqlite3, sys, os, argparse
from datetime import datetime, date
from pathlib import Path

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "exams.db"

STYLE_MAP = {
    "cet4":     "今天刷真题了没~ ",
    "cet6":     "单词背到第几轮啦~ ",
    "graduate": "坚持就是胜利，图书馆见！ ",
    "final":    "平时分拿到了吗_(:з」∠)_ ",
    "cert":     "拿下这个证！ ",
    "other":    "加油！ ",
}
TYPE_KEYWORDS = {
    "cet4":     ["四级", "cet4", "英语四级", "英语4级"],
    "cet6":     ["六级", "cet6", "英语六级", "英语6级"],
    "graduate": ["考研", "研究生", "政治", "数学"],
    "final":    ["期末", "高数", "大物", "线代", "毛概", "近代史"],
    "cert":     ["教资", "普通话", "会计", "ncre", "计算机"],
}


def guess_type(name: str) -> str:
    nl = name.lower()
    for et, kws in TYPE_KEYWORDS.items():
        if any(kw in nl for kw in kws):
            return et
    return "other"


def get_style(name: str) -> str:
    return STYLE_MAP.get(guess_type(name), "you can do it! ")


def _init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS exams ("
        "name TEXT PRIMARY KEY,"
        "exam_date TEXT NOT NULL,"
        "exam_type TEXT DEFAULT '',"
        "remind_ahead INTEGER DEFAULT 7,"
        "status TEXT DEFAULT 'active',"
        "created_at TEXT DEFAULT (datetime('now','localtime')),"
        "archived_at TEXT"
        ")"
    )
    conn.commit()
    return conn


def add_exam(name: str, exam_date: str, exam_type: str = "", remind_ahead: int = 7) -> str:
    conn = _init_db()
    try:
        exam_type = exam_type or guess_type(name)
        conn.execute(
            "INSERT INTO exams (name, exam_date, exam_type, remind_ahead) VALUES (?,?,?,?)",
            (name, exam_date, exam_type, remind_ahead),
        )
        conn.commit()
        return "OK: 已添加「{}」({})".format(name, exam_date)
    except sqlite3.IntegrityError:
        return "ERR: 「{}」已存在，先删了再添加吧~".format(name)
    finally:
        conn.close()


def delete_exam(name: str) -> str:
    conn = _init_db()
    cur = conn.execute("DELETE FROM exams WHERE name=? AND status='active'", (name,))
    conn.commit()
    conn.close()
    if cur.rowcount > 0:
        return "OK: 已删除「{}」".format(name)
    return "ERR: 没有找到「{}」的考试记录~".format(name)


def list_exams() -> str:
    conn = _init_db()
    rows = conn.execute(
        "SELECT name, exam_date, exam_type FROM exams WHERE status='active' ORDER BY exam_date"
    ).fetchall()
    conn.close()
    if not rows:
        return "📋 目前没有考试记录~ 让班长添加吧！"

    today = date.today()
    lines = [
        "📋 考试日历",
        "——————————————",
    ]
    emoji_map = {
        "cet4": "EN",
        "cet6": "EN",
        "graduate": "GR",
        "final": "FN",
        "cert": "CT",
    }
    for name, exam_date, etype in rows:
        d = datetime.strptime(exam_date, "%Y-%m-%d").date()
        days_left = (d - today).days
        if days_left < 0:
            continue
        tag = emoji_map.get(etype, "  ")
        lines.append("{} {} · {} · 还有{}天".format(tag, name, exam_date[-5:], days_left))
    lines.append("——————————————")
    return "\n".join(lines)


def days_until(name: str) -> str:
    conn = _init_db()
    row = conn.execute(
        "SELECT name, exam_date, exam_type FROM exams WHERE name=? AND status='active'", (name,)
    ).fetchone()
    conn.close()
    if not row:
        return "ERR: 没有找到「{}」的考试记录~".format(name)
    ename, exam_date, etype = row
    d = datetime.strptime(exam_date, "%Y-%m-%d").date()
    days_left = (d - date.today()).days
    if days_left < 0:
        return "「{}」已经在 {} 考完啦~ 🎉".format(ename, exam_date)
    style = STYLE_MAP.get(etype, "加油！ ")
    return "🚩 距「{}」还有 {} 天！{} ({})".format(ename, days_left, style, exam_date)

import random as _random

def _morning_greeting() -> str:
    wd = date.today().weekday()
    if wd >= 5:
        return _random.choice(["周末早~睡懒觉了吗", "周末早上好，今天也要加油~"])
    return _random.choice(["早上好呀~", "早安~今天也是元气满满的一天", "早~该起床啦"])

def _exam_msg(name, days_left, etype, remind_ahead):
    g = _morning_greeting()
    s = STYLE_MAP.get(etype, '加油！')
    if days_left == 0:
        return _random.choice([
            g + " 📢 今天考「{}」！！放平心态，你可以的！！(๑•̀ㅂ•́)و✧",
            g + " 「{}」就是今天！冲就完事了！",
            g + " 今天是「{}」考试日~相信自己，加油！！",
        ]).format(name)
    elif days_left <= 3:
        return _random.choice([
            g + " ⚡「{}」只剩 {} 天了！！ {}",
            g + " 「{}」倒计时 {} 天！撑住！！ {}",
            g + " 「{}」倒计时 {} 天！最后冲刺~ {}",
        ]).format(name, days_left, s)
    elif days_left <= 7:
        return _random.choice([
            g + " ⏰「{}」还有 {} 天！{}",
            g + " 「{}」倒计时 {} 天~ 该抓紧啦{}",
            g + " 距离「{}」只剩 {} 天了哦！{}",
        ]).format(name, days_left, s)
    elif days_left <= 14:
        return _random.choice([
            g + " 📌「{}」还有 {} 天，差不多该开始了~",
            g + " 「{}」还有 {} 天，时间过得很快哦 {}",
            g + " 提醒一下~「{}」还有 {} 天 {}",
        ]).format(name, days_left, s)
    elif days_left <= 30:
        return _random.choice([
            g + " 📌「{}」还有 {} 天，有计划了吗~",
            g + " 「{}」倒计时 {} 天，可以先做个计划~{}",
        ]).format(name, days_left, s)
    elif remind_ahead > 0 and days_left <= remind_ahead:
        return _random.choice([
            g + " 📌「{}」还有 {} 天，记在日历上了吗~",
            g + " 「{}」还有 {} 天哦~",
        ]).format(name, days_left)
    return ""

def push_due() -> str:
    """Return push messages with variety."""
    conn = _init_db()
    today = date.today()
    rows = conn.execute("SELECT name, exam_date, exam_type, remind_ahead FROM exams WHERE status='active' ORDER BY exam_date").fetchall()
    conn.close()
    lines = []
    for name, exam_date, etype, remind_ahead in rows:
        d = datetime.strptime(exam_date, '%Y-%m-%d').date()
        days_left = (d - today).days
        if days_left < 0:
            continue
        msg = _exam_msg(name, days_left, etype, remind_ahead)
        if msg:
            lines.append("[exam] PUSH: {} -> {}".format(name, msg))
    if not lines:
        return "[exam] no due reminders"
    return "\n".join(lines)

def delete_passed():
    """Delete exams whose date has already passed."""
    conn = _init_db()
    today = date.today().strftime('%Y-%m-%d')
    cur = conn.execute(
        "DELETE FROM exams WHERE status='active' AND exam_date < ?",
        (today,),
    )
    conn.commit()
    conn.close()
    if cur.rowcount > 0:
        return "[exam] auto-deleted {} passed exam(s)".format(cur.rowcount)
    return ""
def main():
    parser = argparse.ArgumentParser(description="exam countdown system")
    sub = parser.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("exam_date")
    a.add_argument("--type", dest="exam_type", default="")
    a.add_argument("--remind", dest="remind_ahead", type=int, default=7)
    d = sub.add_parser("delete")
    d.add_argument("name")
    sub.add_parser("list")
    da = sub.add_parser("days")
    da.add_argument("name")
    sub.add_parser("push")
    sub.add_parser("archive")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == "add":
        print(add_exam(args.name, args.exam_date, args.exam_type, args.remind_ahead))
    elif args.cmd == "delete":
        print(delete_exam(args.name))
    elif args.cmd == "list":
        print(list_exams())
    elif args.cmd == "days":
        print(days_until(args.name))
    elif args.cmd == "push":
        r = push_due()
        print(r)
        a = delete_passed()
        if a:
            print(a)
    elif args.cmd == "archive":
        r = delete_passed()
        if r:
            print(r)
        else:
            print("[exam] nothing to delete")


if __name__ == "__main__":
    main()
