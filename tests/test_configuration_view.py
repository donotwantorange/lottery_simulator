import json
import unittest

from dashboard.views.configuration import (
    config_to_editor_rows,
    editor_rows_to_config,
    pool_config_from_json,
    pool_config_to_json,
)
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config


class ConfigurationViewTest(unittest.TestCase):
    def setUp(self):
        self.original = load_pool_config()
        self.characters, self.rewards = config_to_editor_rows(self.original)

    def rebuild(self, **overrides):
        arguments = {
            "up_share": 0.5,
            "five_star_probability": 0.08,
            "five_star_pity_enabled": True,
            "five_star_hard_pity": 10,
            "character_rows": self.characters,
            "reward_rows": self.rewards,
        }
        arguments.update(overrides)
        return editor_rows_to_config(**arguments)

    def test_editor_rows_round_trip_and_preserve_dynamic_entries(self):
        self.characters.append({
            "角色名称": "UP-J", "是否UP": True, "是否限定": True, "UP权重": 2.0
        })

        rebuilt = self.rebuild()

        self.assertEqual(len(rebuilt.six_star_characters), 10)
        self.assertEqual(rebuilt.six_star_characters[-1].name, "UP-J")
        self.assertEqual(PoolConfig.from_dict(rebuilt.to_dict()), rebuilt)

    def test_non_up_blank_weight_is_normalized_to_none(self):
        self.characters[1]["UP权重"] = ""

        rebuilt = self.rebuild()

        self.assertIsNone(rebuilt.six_star_characters[1].up_weight)

    def test_up_row_without_weight_is_rejected_by_pool_validation(self):
        self.characters[0]["UP权重"] = None

        with self.assertRaisesRegex(ValueError, "UP characters require up_weight"):
            self.rebuild()

    def test_reward_rows_support_add_and_delete_round_trip(self):
        self.rewards.pop(0)
        self.rewards.append({"奖励名称": "新奖励", "四星": 2, "五星": 7, "六星": 30})

        rebuilt = self.rebuild()
        _, reward_rows = config_to_editor_rows(rebuilt)

        self.assertEqual([row["奖励名称"] for row in reward_rows], ["奖励B", "新奖励"])
        self.assertEqual(reward_rows[-1], {
            "奖励名称": "新奖励", "四星": 2.0, "五星": 7.0, "六星": 30.0,
        })

    def test_json_import_reports_safe_chinese_errors(self):
        for payload in (b"\xff", b"{", json.dumps({"up_share": 0.5}).encode("utf-8")):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "配置 JSON 无效"):
                pool_config_from_json(payload)

    def test_json_export_is_utf8_and_round_trips_dynamic_names(self):
        self.characters[0]["角色名称"] = "限定角色甲"
        rebuilt = self.rebuild()

        exported = pool_config_to_json(rebuilt)

        self.assertIsInstance(exported, bytes)
        self.assertIn("限定角色甲".encode("utf-8"), exported)
        self.assertEqual(pool_config_from_json(exported), rebuilt)


if __name__ == "__main__":
    unittest.main()
