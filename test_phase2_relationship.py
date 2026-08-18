import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import src.memory.relationship_state as rel


class Phase2RelationshipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.patches = (
            patch.object(rel, "DATA_DIR", self.data_dir),
            patch.object(rel, "RELATIONSHIP_DIR", self.data_dir / "memory" / "relationships"),
        )
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_defaults_are_opt_in_and_legacy_json_migrates(self):
        rel.RELATIONSHIP_DIR.mkdir(parents=True)
        (rel.RELATIONSHIP_DIR / "1001.json").write_text(
            json.dumps({"interaction_count": 2, "preferred_nickname": "旧称呼"}), encoding="utf-8"
        )
        state = rel.load_state(1001)
        self.assertFalse(state["initiative_enabled"])
        self.assertEqual(state["quiet_hours"], {"start": "23:00", "end": "08:00"})
        self.assertEqual(state["preferred_nickname"], "旧称呼")
        self.assertEqual(state["relationship_events"], [])

    def test_controls_are_private_and_user_isolated(self):
        self.assertIn("私聊", rel.apply_relationship_command(1001, "开启陪伴提醒", is_group=True))
        self.assertFalse(rel.load_state(1001)["initiative_enabled"])
        self.assertIn("低频陪伴", rel.apply_relationship_command(1001, "开启陪伴提醒"))
        self.assertTrue(rel.load_state(1001)["initiative_enabled"])
        self.assertFalse(rel.load_state(1002)["initiative_enabled"])

    def test_nickname_and_disliked_phrase_require_explicit_commands(self):
        rel.apply_relationship_command(1001, "叫我 FieldLu")
        rel.apply_relationship_command(1001, "我不喜欢你说 人类能做到吗")
        state = rel.load_state(1001)
        self.assertEqual(state["preferred_nickname"], "FieldLu")
        self.assertIn("人类能做到吗", state["disliked_phrases"])
        context = rel.build_context(1001, "原昵称", False, "在吗")
        self.assertIn("FieldLu", context)
        self.assertIn("人类能做到吗", context)
        rel.apply_relationship_command(1001, "别这样叫我 FieldLu")
        self.assertEqual(rel.load_state(1001)["preferred_nickname"], "")

    def test_events_are_bounded_and_do_not_store_full_message(self):
        for index in range(25):
            rel.update_on_message(1001, f"我最近准备考试，这是很长的原文 {index}", is_group=False)
        state = rel.load_state(1001)
        self.assertLessEqual(len(state["relationship_events"]), 20)
        self.assertTrue(all(len(event["summary"]) < 80 for event in state["relationship_events"]))
        self.assertFalse(any("这是很长的原文" in event["summary"] for event in state["relationship_events"]))

    def test_group_context_never_injects_private_nickname_or_loop(self):
        rel.apply_relationship_command(1001, "叫我 小树")
        rel.update_on_message(1001, "我下周有个面试", is_group=False)
        group = rel.build_context(1001, "公开昵称", True, "你还记得吗")
        self.assertNotIn("小树", group)
        self.assertNotIn("面试", group)
        self.assertIn("群聊公开场合", group)

    def test_initiative_quiet_hours_daily_limit_and_cooldown(self):
        now = datetime(2026, 8, 18, 12, 0, 0)
        state = rel.load_state(1001)
        state.update({"initiative_enabled": True, "last_user_message_at": "", "last_initiative_at": ""})
        rel.save_state(1001, state)
        self.assertTrue(rel.can_initiate(1001, now))
        rel.mark_initiative_sent(1001, now)
        self.assertFalse(rel.can_initiate(1001, now + timedelta(hours=1)))
        old = rel.load_state(1001)
        old["initiative_count_date"] = (now - timedelta(days=1)).date().isoformat()
        old["initiative_count_today"] = 1
        old["last_initiative_at"] = (now - timedelta(days=2)).isoformat()
        rel.save_state(1001, old)
        self.assertFalse(rel.can_initiate(1001, datetime(2026, 8, 18, 23, 30)))
        self.assertTrue(rel.can_initiate(1001, datetime(2026, 8, 18, 12, 0)))
        old = rel.load_state(1001)
        old["last_user_message_at"] = datetime(2026, 8, 18, 11, 50).isoformat()
        rel.save_state(1001, old)
        self.assertFalse(rel.can_initiate(1001, datetime(2026, 8, 18, 12, 0)))

    def test_repair_has_priority_over_affection(self):
        state = rel.update_on_message(1001, "你这样说我不舒服", is_group=False)
        self.assertTrue(state["repair_needed"])
        self.assertEqual(rel.choose_behavior("抱抱我", state), "boundary_or_repair")
        state = rel.update_on_message(1001, "没事了", is_group=False)
        self.assertFalse(state["repair_needed"])
        self.assertEqual(rel.choose_behavior("抱抱我", state), "shy_affection")


if __name__ == "__main__":
    unittest.main()
