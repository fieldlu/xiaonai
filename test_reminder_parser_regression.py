from datetime import datetime
import builtins
import json
import tempfile
import unittest
from pathlib import Path

builtins.BOT_QQ_PLACEHOLDER = 0
builtins.ADMIN_QQ_PLACEHOLDER = 0
import bridge  # noqa: E402
from reminder_parser import parse_reminder


class ReminderParserRegressionTests(unittest.TestCase):
    NOW = datetime(2026, 8, 18, 0, 55)

    def test_clear_accepts_custom_reminder_wording(self):
        result = parse_reminder("取消所有定制提醒", self.NOW, 1001)
        self.assertEqual(result, {"action": "clear"})

    def test_stacked_polite_prefixes_are_supported(self):
        self.assertEqual(parse_reminder("请帮我取消所有定制提醒", self.NOW, 1001), {"action": "clear"})
        self.assertEqual(parse_reminder("麻烦帮我查看所有提醒", self.NOW, 1001), {"action": "list"})
        self.assertEqual(parse_reminder("请帮我取消2026-08-19的", self.NOW, 1001)["action"], "delete")

    def test_cancel_date_without_repeating_reminder_word(self):
        result = parse_reminder("取消2026-08-19的", self.NOW, 1001)
        self.assertEqual(result, {"action": "delete", "match": "取消2026-08-19的"})

    def test_normal_reminder_setting_is_unchanged(self):
        result = parse_reminder("明天9点提醒我报名", self.NOW, 1001)
        self.assertEqual(result["action"], "set")
        self.assertEqual(result["send_at"], "2026-08-19 09:00")
        self.assertEqual(result["content"], "报名")
        quoted_content = parse_reminder("明天9点提醒我给她说“报名”", self.NOW, 1001)
        self.assertEqual(quoted_content["action"], "set")

    def test_destructive_words_are_not_found_inside_explanations(self):
        self.assertIsNone(parse_reminder("不要取消所有定制提醒", self.NOW, 1001))
        self.assertIsNone(parse_reminder("我想知道怎么取消2026-08-19的", self.NOW, 1001))
        self.assertIsNone(parse_reminder("请解释“明天9点提醒我报名”是什么意思", self.NOW, 1001))
        self.assertIsNone(parse_reminder("“明天9点提醒我报名”是什么意思", self.NOW, 1001))

    def test_executor_deletes_by_date_and_keeps_other_scopes(self):
        records = [
            {"id": "a1", "user_id": 1001, "group_id": None, "message": "我的私聊提醒", "send_at": "2026-08-19 09:00", "sent": False},
            {"id": "a2", "user_id": 1001, "group_id": None, "message": "我的第二条", "send_at": "2026-08-24 09:00", "sent": False},
            {"id": "b1", "user_id": 2002, "group_id": None, "message": "别人的提醒", "send_at": "2026-08-19 09:00", "sent": False},
            {"id": "g1", "user_id": 3003, "group_id": 9009, "message": "群提醒", "send_at": "2026-08-19 09:00", "sent": False},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timed_msg.json"
            path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            listed = bridge._exec_reminder({"action": "list"}, 1001, 0, str(path))
            self.assertIn("我的私聊提醒", listed)
            self.assertNotIn("别人的提醒", listed)
            self.assertNotIn("群提醒", listed)
            delete = parse_reminder("取消2026-08-19的", self.NOW, 1001)
            bridge._exec_reminder(delete, 1001, 0, str(path))
            ids = {item["id"] for item in json.loads(path.read_text(encoding="utf-8"))}
            self.assertEqual(ids, {"a2", "b1", "g1"})
            bridge._exec_reminder({"action": "clear"}, 1001, 0, str(path))
            ids = {item["id"] for item in json.loads(path.read_text(encoding="utf-8"))}
            self.assertEqual(ids, {"b1", "g1"})

    def test_executor_scopes_group_actions(self):
        records = [
            {"id": "g1", "user_id": 3003, "group_id": 9009, "message": "当前群提醒", "send_at": "2026-08-19 09:00", "sent": False},
            {"id": "g2", "user_id": 3003, "group_id": 9010, "message": "其他群提醒", "send_at": "2026-08-19 09:00", "sent": False},
            {"id": "p1", "user_id": 3003, "group_id": None, "message": "私聊提醒", "send_at": "2026-08-19 09:00", "sent": False},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timed_msg.json"
            path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            listed = bridge._exec_reminder({"action": "list"}, 4004, 9009, str(path))
            self.assertIn("当前群提醒", listed)
            self.assertNotIn("其他群提醒", listed)
            self.assertNotIn("私聊提醒", listed)
            bridge._exec_reminder({"action": "clear"}, 4004, 9009, str(path))
            ids = {item["id"] for item in json.loads(path.read_text(encoding="utf-8"))}
            self.assertEqual(ids, {"g2", "p1"})


if __name__ == "__main__":
    unittest.main()
