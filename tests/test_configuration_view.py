import json
import unittest
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

from dashboard.views.configuration import (
    config_to_editor_rows,
    editor_rows_to_config,
    pool_config_from_json,
    pool_config_to_json,
    render_pool_config_editor,
    set_pool_config_editor_state,
)
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config


class EditorBoundary:
    """Record public editor inputs; no Streamlit delta/state protocol emulation."""

    def __init__(self):
        self.session_state = {}
        self.inputs = {}
        self.edited_rows = {}
        self.download = None
        self.column_config = SimpleNamespace(
            TextColumn=lambda: None, NumberColumn=lambda **kwargs: None,
        )

    def caption(self, text):
        self.caption_text = text

    def expander(self, label):
        return nullcontext()

    def file_uploader(self, *args, **kwargs):
        return None

    def button(self, label):
        return False

    def number_input(self, label, *, key, **kwargs):
        return self.session_state[key]

    toggle = number_input

    def data_editor(self, data, *, key, **kwargs):
        self.inputs[key] = deepcopy(data)
        return deepcopy(self.edited_rows.get(key, data))

    def download_button(self, label, *, data, **kwargs):
        self.download = data


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

    def test_editor_rebuild_keeps_imported_optional_roster(self):
        raw = load_pool_config().to_dict()
        raw["four_star_characters"] = [{"name": "四星A", "weight": 2}]
        st = EditorBoundary()
        config = PoolConfig.from_dict(raw)

        set_pool_config_editor_state(st, config)
        rebuilt = render_pool_config_editor(st)

        self.assertEqual(rebuilt.four_star_characters, config.four_star_characters)
        self.assertEqual(PoolConfig.from_dict(json.loads(st.download)), rebuilt)

    def test_consecutive_edits_keep_widget_inputs_stable_and_export_latest_values(self):
        st = EditorBoundary()
        set_pool_config_editor_state(st, self.original)
        characters, rewards = deepcopy(self.characters), deepcopy(self.rewards)
        for name, weight, four, five, six in (
            ("UP-X", 2, 3, 2, 25),
            ("UP-Y", 3, 3, 7, 25),
            ("UP-Y", 3, 3, 7, 30),
        ):
            characters[0].update({"角色名称": name, "UP权重": weight})
            rewards[0].update({"四星": four, "六星": six})
            rewards[1]["五星"] = five
            st.edited_rows = {
                "pool_character_editor": characters,
                "pool_reward_editor": rewards,
            }
            config = render_pool_config_editor(st)
            # Changing the next input invalidates dynamic widget identity.
            self.assertEqual(st.inputs["pool_character_editor"][0]["角色名称"], "UP-A")
            self.assertEqual(st.inputs["pool_character_editor"][0]["UP权重"], 1)
            self.assertEqual(st.inputs["pool_reward_editor"][0]["四星"], 1)
            self.assertEqual(st.inputs["pool_reward_editor"][1]["五星"], 2)
            self.assertEqual(config.six_star_characters[0].name, name)
            self.assertEqual(config.six_star_characters[0].up_weight, weight)
            exported = json.loads(st.download)
            self.assertEqual(exported["rewards"][0]["four_star"], four)
            self.assertEqual(exported["rewards"][1]["five_star"], five)
            self.assertEqual(exported["rewards"][0]["six_star"], six)

    def test_explicit_configuration_reset_replaces_bases_and_clears_editor_state(self):
        st = EditorBoundary()
        set_pool_config_editor_state(st, self.original)
        st.session_state["pool_character_editor"] = {"old": "edit"}
        st.session_state["pool_reward_editor"] = {"old": "edit"}
        raw = self.original.to_dict()
        raw["six_star_characters"][0]["name"] = "导入角色"
        raw["rewards"][0]["four_star"] = 9
        set_pool_config_editor_state(st, PoolConfig.from_dict(raw))
        self.assertNotIn("pool_character_editor", st.session_state)
        self.assertNotIn("pool_reward_editor", st.session_state)
        config = render_pool_config_editor(st)
        self.assertEqual(st.inputs["pool_character_editor"][0]["角色名称"], "导入角色")
        self.assertEqual(st.inputs["pool_reward_editor"][0]["四星"], 9)
        self.assertEqual(config.six_star_characters[0].name, "导入角色")
        self.assertEqual(json.loads(st.download)["rewards"][0]["four_star"], 9)


if __name__ == "__main__":
    unittest.main()
