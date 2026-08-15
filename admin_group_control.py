#!/usr/bin/env python3
"""CLI wrapper for admin_group_control — usable by OpenClaw agent via exec.

Usage:
  python3 admin_group_control.py add_class_group CADRE_GROUP_PLACEHOLDER
  python3 admin_group_control.py add_chat_group TEST_GROUP_PLACEHOLDER
  python3 admin_group_control.py add_normal_group 123456789
  python3 admin_group_control.py add_mute_group 123456789
  python3 admin_group_control.py add_blacklist 123456789
  python3 admin_group_control.py remove_class_group CADRE_GROUP_PLACEHOLDER
  python3 admin_group_control.py remove_chat_group TEST_GROUP_PLACEHOLDER
  python3 admin_group_control.py remove_normal_group 123456789
  python3 admin_group_control.py remove_mute_group 123456789
  python3 admin_group_control.py remove_blacklist 123456789
  python3 admin_group_control.py show_config
  python3 admin_group_control.py subscribe 群号 [weather|news|earthquake|weather_warning|campus_daily|exam_countdown|all]
  python3 admin_group_control.py unsubscribe 群号 [weather|news|earthquake|weather_warning|campus_daily|exam_countdown|all]

Each add_* command removes the group from all other lists (cross-list dedup).
Auto-reloads bridge policy after each change.
"""

import json
import os
import sys
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.openclaw/agents/main/agent/group_config.json")
BRIDGE_CONFIG_PATH = "/opt/xiaonai/data/group_config.json"
RELOAD_URL = "http://127.0.0.1:8081/reload"

ALL_GROUP_KEYS = ["class_groups", "chat_groups", "normal_groups", "mute_groups", "blacklist"]


def _remove_from_all_other_lists(cfg, gid, keep_key):
    """Remove gid from all group lists EXCEPT keep_key. Ensures mutual exclusivity."""
    for key in ALL_GROUP_KEYS:
        if key == keep_key:
            continue
        lst = cfg.get(key, [])
        if gid in lst:
            lst.remove(gid)
            cfg[key] = lst


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"class_groups": [], "chat_groups": [], "normal_groups": [], "mute_groups": [], "blacklist": []}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(BRIDGE_CONFIG_PATH), exist_ok=True)
        with open(BRIDGE_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def reload_bridge():
    try:
        urllib.request.urlopen(
            urllib.request.Request(RELOAD_URL, method="POST"), timeout=5
        )
        return True
    except Exception:
        return False




_SUB_LABELS = [
    ("weather", "每日天气"),
    ("news", "新闻晚报"),
    ("campus_daily", "校园通知"),
    ("earthquake", "地震预警"),
    ("weather_warning", "气象预警"),
    ("exam_countdown", "考试倒计时"),
    ("daily_greetings", "每日问候"),
]


def _print_subscriptions():
    """读实时 scheduler_config.json 输出订阅明细。"""
    sc_path = "/opt/xiaonai/data/scheduler_config.json"
    print()
    print("当前订阅（数据源 scheduler_config.json，实时读取）：")
    if not os.path.exists(sc_path):
        print("  scheduler_config.json 不存在，无任何订阅。")
        return
    try:
        with open(sc_path, encoding="utf-8") as f:
            sc = json.load(f)
    except Exception as e:
        print("  读取失败: %s" % e)
        return
    for key, label in _SUB_LABELS:
        item = sc.get(key) or {}
        groups = item.get("groups") or []
        enabled = item.get("enabled", False)
        when = ""
        if item.get("hour") is not None:
            when = " 每天%02d:%02d" % (item.get("hour", 0), item.get("minute", 0))
        elif item.get("interval_min") is not None:
            _iv = item.get("interval_min")
            if _iv is not None and float(_iv) < 1:
                when = " 每%d秒检查一次" % round(float(_iv) * 60)
            else:
                when = " 每%s分钟检查一次" % (int(_iv) if float(_iv) == int(float(_iv)) else _iv)
        gs = ", ".join(str(g) for g in groups)
        if groups and enabled:
            print("  [开] %s%s → 群 %s" % (label, when, gs))
        elif groups and not enabled:
            print("  [已禁用] %s → 群 %s（enabled=false，不推送）" % (label, gs))
        else:
            print("  [未订阅] %s → 无群" % label)
    print()
    print("  ℹ️ 以上是定时推送订阅；用户临时设的闹钟/提醒属于 cron 定时任务，两者不同系统。")

def main():
    if len(sys.argv) < 2:
        print("Usage: admin_group_control.py <action> [value]")
        print("Actions: add_class_group, remove_class_group, add_chat_group,")
        print("         remove_chat_group, add_normal_group, remove_normal_group,")
        print("         add_mute_group, remove_mute_group,")
        print("         add_blacklist, remove_blacklist, show_config, subscribe, unsubscribe")
        sys.exit(1)

    action = sys.argv[1]
    value = sys.argv[2] if len(sys.argv) > 2 else ""

    cfg = load_config()
    # Actions that don't need a group ID
    no_value_actions = ["show_config", "set_all_class", "set_all_chat", "set_all_normal", "set_all_mute"]
    if action not in no_value_actions:
        if not value:
            print(f"错误：{action} 需要提供群号")
            sys.exit(1)
        try:
            gid = int(value)
        except ValueError:
            print(f"错误：群号必须是数字，收到: {value}")
            sys.exit(1)
    if action == "show_config":
        print("当前群配置（未配置的群默认为静默群）：")
        print(f"  [聊天群] 主动回复: {cfg.get('chat_groups', [])}")
        print(f"  [普通群] 正常回复: {cfg.get('normal_groups', [])}")
        print(f"  [静默群] 仅@才回: {cfg.get('class_groups', [])}")
        print(f"  [免打扰] 全沉默: {cfg.get('mute_groups', [])}")
        print(f"  [黑名单] 不回复: {cfg.get('blacklist', [])}")
        print()
        all_cfg = set(cfg.get('chat_groups', []) + cfg.get('normal_groups', []) + cfg.get('class_groups', []) + cfg.get('mute_groups', []))
        print(f"  ⚠️ 未在上列列表的群默认为「静默群」（仅@小奈才回复）")
        print("  ✔️ 订阅通知功能不受群类型影响，定时推送正常工作")
        _print_subscriptions()
    elif action == "add_class_group":
        cg = cfg.get("class_groups", [])
        if gid not in cg:
            _remove_from_all_other_lists(cfg, gid, "class_groups")
            cg.append(gid)
            cfg["class_groups"] = cg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 设为静默群（仅@小奈才回复）。")
        else:
            print(f"群 {gid} 已是静默群。")
            print(f"  当前静默群: {cfg.get('class_groups', [])}")

    elif action == "remove_class_group":
        cg = cfg.get("class_groups", [])
        if gid in cg:
            cg.remove(gid)
            cfg["class_groups"] = cg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 从班级群移除。")
        else:
            print(f"群 {gid} 不在班级群中。")
            print(f"  当前班级群: {cfg.get('class_groups', [])}")

    elif action == "add_chat_group":
        cg = cfg.get("chat_groups", [])
        if gid not in cg:
            _remove_from_all_other_lists(cfg, gid, "chat_groups")
            cg.append(gid)
            cfg["chat_groups"] = cg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 设为闲聊群（正常聊天）。")
        else:
            print(f"群 {gid} 已是闲聊群。")
            print(f"  当前闲聊群: {cfg.get('chat_groups', [])}")

    elif action == "remove_chat_group":
        cg = cfg.get("chat_groups", [])
        if gid in cg:
            cg.remove(gid)
            cfg["chat_groups"] = cg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 从闲聊群移除。")
        else:
            print(f"群 {gid} 不在闲聊群中。")
            print(f"  当前闲聊群: {cfg.get('chat_groups', [])}")

    elif action == "add_normal_group":
        ng = cfg.get("normal_groups", [])
        if gid not in ng:
            _remove_from_all_other_lists(cfg, gid, "normal_groups")
            ng.append(gid)
            cfg["normal_groups"] = ng
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 设为普通群（仅@回复，无推送）。")
        else:
            print(f"群 {gid} 已是普通群。")
            print(f"  当前普通群: {cfg.get('normal_groups', [])}")

    elif action == "remove_normal_group":
        ng = cfg.get("normal_groups", [])
        if gid in ng:
            ng.remove(gid)
            cfg["normal_groups"] = ng
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 从普通群移除。")
        else:
            print(f"群 {gid} 不在普通群中。")
            print(f"  当前普通群: {cfg.get('normal_groups', [])}")

    elif action == "add_mute_group":
        mg = cfg.get("mute_groups", [])
        if gid not in mg:
            _remove_from_all_other_lists(cfg, gid, "mute_groups")
            mg.append(gid)
            cfg["mute_groups"] = mg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 设为免打扰群（小奈不会回复，仅管理员可通知）。")
        else:
            print(f"群 {gid} 已是免打扰群。")
            print(f"  当前免打扰群: {cfg.get('mute_groups', [])}")

    elif action == "remove_mute_group":
        mg = cfg.get("mute_groups", [])
        if gid in mg:
            mg.remove(gid)
            cfg["mute_groups"] = mg
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 从免打扰群移除，此群将恢复正常回复。")
        else:
            print(f"群 {gid} 不在免打扰群中。")
            print(f"  当前免打扰群: {cfg.get('mute_groups', [])}")

    elif action == "add_blacklist":
        bl = cfg.get("blacklist", [])
        if gid not in bl:
            _remove_from_all_other_lists(cfg, gid, "blacklist")
            bl.append(gid)
            cfg["blacklist"] = bl
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 加入黑名单（小奈不会再回复）。")
        else:
            print(f"群 {gid} 已在黑名单中。")
            print(f"  当前黑名单: {cfg.get('blacklist', [])}")

    elif action == "remove_blacklist":
        bl = cfg.get("blacklist", [])
        if gid in bl:
            bl.remove(gid)
            cfg["blacklist"] = bl
            save_config(cfg)
            reload_bridge()
            print(f"已将群 {gid} 从黑名单移除。")
        else:
            print(f"群 {gid} 不在黑名单中。")
            print(f"  当前黑名单: {cfg.get('blacklist', [])}")


    elif action == "set_all_class":
        """Set all configured groups to class_group (silent)."""
        all_gids = set()
        for key in ["chat_groups", "normal_groups", "mute_groups", "class_groups"]:
            for g in cfg.get(key, []):
                all_gids.add(g)
        for gid in all_gids:
            _remove_from_all_other_lists(cfg, gid, "class_groups")
            cg = cfg.get("class_groups", [])
            if gid not in cg:
                cg.append(gid)
            cfg["class_groups"] = cg
        save_config(cfg)
        reload_bridge()
        print(f"已将全部 {len(all_gids)} 个已配置群改为静默群。")
        print(f"  当前静默群: {cfg.get('class_groups', [])}")
        print(f"  当前聊天群: {cfg.get('chat_groups', [])}")
        print(f"  当前普通群: {cfg.get('normal_groups', [])}")
        print(f"  当前免打扰群: {cfg.get('mute_groups', [])}")

    elif action == "set_all_chat":
        all_gids = set()
        for key in ["class_groups", "normal_groups", "mute_groups", "chat_groups"]:
            for g in cfg.get(key, []):
                all_gids.add(g)
        for gid in all_gids:
            _remove_from_all_other_lists(cfg, gid, "chat_groups")
            cg = cfg.get("chat_groups", [])
            if gid not in cg:
                cg.append(gid)
            cfg["chat_groups"] = cg
        save_config(cfg)
        reload_bridge()
        print(f"已将全部 {len(all_gids)} 个已配置群改为聊天群。")

    elif action == "set_all_normal":
        all_gids = set()
        for key in ["class_groups", "chat_groups", "mute_groups", "normal_groups"]:
            for g in cfg.get(key, []):
                all_gids.add(g)
        for gid in all_gids:
            _remove_from_all_other_lists(cfg, gid, "normal_groups")
            ng = cfg.get("normal_groups", [])
            if gid not in ng:
                ng.append(gid)
            cfg["normal_groups"] = ng
        save_config(cfg)
        reload_bridge()
        print(f"已将全部 {len(all_gids)} 个已配置群改为普通群。")

    elif action == "set_all_mute":
        all_gids = set()
        for key in ["class_groups", "chat_groups", "normal_groups", "mute_groups"]:
            for g in cfg.get(key, []):
                all_gids.add(g)
        for gid in all_gids:
            _remove_from_all_other_lists(cfg, gid, "mute_groups")
            mg = cfg.get("mute_groups", [])
            if gid not in mg:
                mg.append(gid)
            cfg["mute_groups"] = mg
        save_config(cfg)
        reload_bridge()
        print(f"已将全部 {len(all_gids)} 个已配置群改为免打扰群。")

    elif action == "subscribe":
        sc_path = "/opt/xiaonai/data/scheduler_config.json"
        _DEFAULTS = {
            "weather": {"enabled": True, "hour": 7, "groups": []},
            "news": {"enabled": True, "hour": 18, "groups": []},
            "earthquake": {"enabled": True, "interval_min": 2, "groups": [], "min_magnitude": 4.0},
            "weather_warning": {"enabled": True, "interval_min": 10, "groups": []},
            "campus_daily": {"enabled": True, "hour": 7, "minute": 40, "groups": []},
            "exam_countdown": {"enabled": True, "groups": []},
        }
        sc = {}
        if os.path.exists(sc_path):
            with open(sc_path) as f:
                sc = json.load(f)
        ntype = sys.argv[3] if len(sys.argv) > 3 else "all"
        valid_types = ["weather", "news", "earthquake", "weather_warning", "campus_daily", "exam_countdown"]
        if ntype == "all":
            targets = valid_types
        elif ntype in valid_types:
            targets = [ntype]
        else:
            print(f"未知通知类型: {ntype}，可选: all, {', '.join(valid_types)}")
            sys.exit(1)
        updated = []
        for t in targets:
            if t not in sc or not isinstance(sc[t], dict):
                sc[t] = dict(_DEFAULTS.get(t, {"enabled": True, "groups": []}))
            entry = sc[t]
            groups = list(entry.get("groups", []))
            if gid not in groups:
                groups.append(gid)
                entry["groups"] = groups
                updated.append(t)
        if updated:
            os.makedirs(os.path.dirname(sc_path), exist_ok=True)
            with open(sc_path, "w") as f:
                json.dump(sc, f, ensure_ascii=False, indent=2)
            print(f"群 {gid} 已订阅: {', '.join(updated)}")
        else:
            print(f"群 {gid} 已订阅所有通知，无需重复操作。")

    elif action == "unsubscribe":
        sc_path = "/opt/xiaonai/data/scheduler_config.json"
        if not os.path.exists(sc_path):
            print("scheduler_config.json 不存在，无需退订。")
        sys.exit(0)
        with open(sc_path) as f:
            sc = json.load(f)
        ntype = sys.argv[3] if len(sys.argv) > 3 else "all"
        valid_types = ["weather", "news", "earthquake", "weather_warning", "campus_daily", "exam_countdown"]
        if ntype == "all":
            targets = valid_types
        elif ntype in valid_types:
            targets = [ntype]
        else:
            print(f"未知通知类型: {ntype}，可选: all, {', '.join(valid_types)}")
            sys.exit(1)
        updated = []
        for t in targets:
            entry = sc.get(t, {})
            if isinstance(entry, dict):
                groups = list(entry.get("groups", []))
                if gid in groups:
                    groups.remove(gid)
                    entry["groups"] = groups
                    sc[t] = entry
                    updated.append(t)
        if updated:
            with open(sc_path, "w") as f:
                json.dump(sc, f, ensure_ascii=False, indent=2)
            print(f"群 {gid} 已退订: {', '.join(updated)}")
        else:
            print(f"群 {gid} 未订阅任何通知。")

    else:
            print(f"未知操作: {action}")
            print("支持: add_class_group, remove_class_group, add_chat_group,")
            print("      remove_chat_group, add_normal_group, remove_normal_group,")
            print("      add_mute_group, remove_mute_group,")
            print("      add_blacklist, remove_blacklist, show_config, subscribe, unsubscribe")
            sys.exit(1)


if __name__ == "__main__":
    main()
