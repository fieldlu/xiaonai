import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.memory.relationship_state as rel


class RelationshipStateTests(unittest.TestCase):
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

    def test_new_user_defaults_to_initial_stage_and_is_isolated(self):
        first = rel.load_state(1001)
        second = rel.load_state(1002)
        self.assertEqual(first["relationship_stage"], "初识")
        self.assertEqual(first["interaction_count"], 0)
        rel.update_on_message(1001, "我最近准备考试", is_group=False)
        self.assertTrue(rel.load_state(1001)["open_loops"])
        self.assertEqual(rel.load_state(1002)["open_loops"], [])

    def test_corrupt_state_falls_back_without_cross_user_data(self):
        rel.RELATIONSHIP_DIR.mkdir(parents=True)
        (rel.RELATIONSHIP_DIR / "1001.json").write_text("{bad", encoding="utf-8")
        state = rel.load_state(1001)
        self.assertEqual(state["relationship_stage"], "初识")
        self.assertEqual(state["interaction_count"], 0)

    def test_behavior_prioritizes_comfort_and_repair(self):
        state = rel.load_state(1001)
        self.assertEqual(rel.choose_behavior("我今天好累，压力好大", state), "comfort")
        state["repair_needed"] = True
        self.assertEqual(rel.choose_behavior("我爱你", state), "boundary_or_repair")

    def test_group_does_not_store_or_inject_private_open_loop(self):
        rel.update_on_message(1001, "我下周有个面试", is_group=False)
        private = rel.build_context(1001, "小明", False, "你还记得吗")
        group = rel.build_context(1001, "小明", True, "你还记得吗")
        self.assertIn("面试", private)
        self.assertNotIn("面试", group)
        self.assertNotIn("小明", group)
        self.assertNotIn("阶段：", group)
        self.assertIn("群聊公开场合", group)

    def test_text_cleanup_and_context_use_real_newlines(self):
        state = rel.update_on_message(1001, "我  最近\t准备考试")
        self.assertEqual(state["open_loops"][0]["snippet"], "我 最近 准备考试")
        context = rel.build_context(1001, "小明", False, "你还记得吗")
        self.assertIn("\n", context)
        self.assertNotIn("\\n", context)

    def test_stage_advances_only_after_interactions_and_existing_score(self):
        user_dir = self.data_dir / "memory" / "users"
        user_dir.mkdir(parents=True)
        (user_dir / "1001.json").write_text(json.dumps({"composite": 82}), encoding="utf-8")
        for text in ("在吗", "今天上课", "谢谢你"):
            state = rel.update_on_message(1001, text)
        self.assertEqual(state["relationship_stage"], "稳定期")


if __name__ == "__main__":
    unittest.main()
