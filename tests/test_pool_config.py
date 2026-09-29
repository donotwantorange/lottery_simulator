import copy
import json
import math
import unittest

from lottery_simulator.analysis import expected_pool_results
from lottery_simulator.rules.rule_1 import Rule1
from lottery_simulator.rules.pool_config import (
    PoolConfig,
    load_pool_config,
)


class PoolConfigTest(unittest.TestCase):
    def test_optional_rosters_round_trip_with_weighted_ordered_probabilities(self):
        raw = load_pool_config().to_dict()
        raw["four_star_characters"] = [
            {"name": "同名角色", "weight": 1},
            {"name": "四星B", "weight": 3},
        ]
        raw["five_star_characters"] = [{"name": "同名角色"}]

        config = PoolConfig.from_dict(raw)

        self.assertEqual(
            config.character_probabilities(4),
            {"同名角色": 0.25, "四星B": 0.75},
        )
        self.assertEqual(config.character_probabilities(5), {"同名角色": 1.0})
        self.assertEqual(PoolConfig.from_dict(config.to_dict()), config)

    def test_optional_rosters_default_to_empty_and_keep_configuration_order(self):
        raw = load_pool_config().to_dict()
        del raw["four_star_characters"]
        del raw["five_star_characters"]

        config = PoolConfig.from_dict(raw)

        self.assertEqual(config.character_probabilities(4), {})
        self.assertEqual(config.character_probabilities(5), {})
        self.assertEqual(config.to_dict()["four_star_characters"], [])
        self.assertEqual(config.to_dict()["five_star_characters"], [])

    def test_weighted_rosters_avoid_large_finite_weight_overflow(self):
        raw = load_pool_config().to_dict()
        raw["four_star_characters"] = [
            {"name": "四星A", "weight": 1e308},
            {"name": "四星B", "weight": 1e308},
        ]

        probabilities = PoolConfig.from_dict(raw).character_probabilities(4)

        self.assertEqual(list(probabilities), ["四星A", "四星B"])
        self.assertEqual(probabilities, {"四星A": 0.5, "四星B": 0.5})

    def test_rosters_reject_invalid_names_weights_and_duplicate_names(self):
        base = load_pool_config().to_dict()
        cases = {
            "null roster": lambda raw: raw.update({"four_star_characters": None}),
            "non-list roster": lambda raw: raw.update({"four_star_characters": {}}),
            "non-object entry": lambda raw: raw.update({"four_star_characters": ["A"]}),
            "empty name": lambda raw: raw.update({"four_star_characters": [{"name": " "}]}),
            "duplicate name": lambda raw: raw.update({"four_star_characters": [
                {"name": "A"}, {"name": "A"},
            ]}),
            "zero weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": 0},
            ]}),
            "negative weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": -1},
            ]}),
            "nan weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": math.nan},
            ]}),
            "infinite weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": math.inf},
            ]}),
            "bool weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": True},
            ]}),
            "overflow weight": lambda raw: raw.update({"four_star_characters": [
                {"name": "A", "weight": 10 ** 400},
            ]}),
        }
        for description, mutate in cases.items():
            with self.subTest(description=description):
                raw = copy.deepcopy(base)
                mutate(raw)
                with self.assertRaises(ValueError):
                    PoolConfig.from_dict(raw)

    def test_pool_config_requires_exact_format_version_and_valid_rarity(self):
        base = load_pool_config().to_dict()
        for version in (None, 0, 1, 3, True, "2"):
            with self.subTest(version=version):
                raw = copy.deepcopy(base)
                if version is None:
                    del raw["format_version"]
                else:
                    raw["format_version"] = version
                with self.assertRaises(ValueError):
                    PoolConfig.from_dict(raw)

        config = load_pool_config()
        for rarity in (False, 3, 7, "6", 4.0):
            with self.subTest(rarity=rarity):
                with self.assertRaises(ValueError):
                    config.character_probabilities(rarity)

    def test_default_config_has_expected_roster_probabilities_and_rewards(self):
        config = load_pool_config()
        probabilities = config.character_probabilities(6)

        self.assertEqual(len(config.six_star_characters), 9)
        self.assertEqual(sum(c.is_up for c in config.six_star_characters), 1)
        self.assertEqual(sum(c.is_limited for c in config.six_star_characters), 3)
        self.assertAlmostEqual(probabilities["UP-A"], 0.5)
        self.assertTrue(all(
            abs(probabilities[name] - 0.0625) < 1e-12
            for name in probabilities if name != "UP-A"
        ))
        self.assertEqual(config.rewards_for(5), {"奖励A": 5.0, "奖励B": 2.0})
        self.assertEqual(PoolConfig.from_dict(config.to_dict()), config)

    def test_multiple_up_characters_share_up_probability_by_weight(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][1].update(
            {"is_up": True, "is_limited": True, "up_weight": 3}
        )
        config = PoolConfig.from_dict(raw)
        probabilities = config.character_probabilities(6)

        self.assertAlmostEqual(probabilities["UP-A"], 0.125)
        self.assertAlmostEqual(probabilities["限定-B"], 0.375)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_six_star_probabilities_keep_configuration_order_with_late_up(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][4].update(
            {"is_up": True, "is_limited": True, "up_weight": 3}
        )

        probabilities = PoolConfig.from_dict(raw).character_probabilities(6)

        self.assertEqual(
            list(probabilities),
            [character["name"] for character in raw["six_star_characters"]],
        )

    def test_large_finite_up_weights_preserve_probabilities_and_character_expectations(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][0]["up_weight"] = 1e308
        raw["six_star_characters"][1].update(is_up=True, up_weight=1e308)
        config = PoolConfig.from_dict(raw)
        probabilities = config.character_probabilities(6)

        self.assertAlmostEqual(probabilities["UP-A"], 0.25)
        self.assertAlmostEqual(probabilities["限定-B"], 0.25)
        self.assertAlmostEqual(probabilities["UP-A"] + probabilities["限定-B"], 0.5)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        expected = expected_pool_results(Rule1(config), 1)
        self.assertAlmostEqual(expected.rarity_counts["6"], 0.008)
        self.assertAlmostEqual(expected.character_counts["UP-A"], 0.002)
        self.assertAlmostEqual(sum(expected.character_counts.values()), 0.008)
        self.assertAlmostEqual(expected.six_star_categories["up"], 0.004)

    def test_json_integer_too_large_for_float_reports_field_value_error(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][0]["up_weight"] = 10 ** 400
        raw = json.loads(json.dumps(raw))
        try:
            PoolConfig.from_dict(raw)
        except ValueError as error:
            self.assertIn("up_weight must be a finite number", str(error))
        except OverflowError:
            self.fail("JSON integer overflow bypassed field validation")
        else:
            self.fail("invalid UP weight was accepted")

    def test_invalid_character_combinations_are_rejected(self):
        base = load_pool_config().to_dict()
        cases = {
            "duplicate name": lambda raw: raw["six_star_characters"][1].update(
                {"name": raw["six_star_characters"][0]["name"]}
            ),
            "empty name": lambda raw: raw["six_star_characters"][0].update(
                {"name": "   "}
            ),
            "up must be limited": lambda raw: raw["six_star_characters"][0].update(
                {"is_limited": False}
            ),
            "no up character": lambda raw: [character.update({"is_up": False})
                                               for character in raw["six_star_characters"]],
            "up weight zero": lambda raw: raw["six_star_characters"][0].update(
                {"up_weight": 0}
            ),
            "up weight negative": lambda raw: raw["six_star_characters"][0].update(
                {"up_weight": -1}
            ),
            "up weight infinite": lambda raw: raw["six_star_characters"][0].update(
                {"up_weight": math.inf}
            ),
            "up weight nan": lambda raw: raw["six_star_characters"][0].update(
                {"up_weight": math.nan}
            ),
            "up share zero": lambda raw: raw.update({"up_share": 0}),
            "up share above one": lambda raw: raw.update({"up_share": 1.01}),
            "up share nan": lambda raw: raw.update({"up_share": math.nan}),
            "up share infinite": lambda raw: raw.update({"up_share": math.inf}),
            "up share bool": lambda raw: raw.update({"up_share": True}),
            "missing non-up when share below one": lambda raw: (
                raw.update({"up_share": 0.5}),
                [character.update({"is_up": True, "is_limited": True,
                                   "up_weight": 1})
                 for character in raw["six_star_characters"]],
            ),
        }
        for description, mutate in cases.items():
            with self.subTest(description=description):
                raw = copy.deepcopy(base)
                mutate(raw)
                with self.assertRaises(ValueError):
                    PoolConfig.from_dict(raw)

    def test_invalid_probability_and_reward_values_are_rejected(self):
        base = load_pool_config().to_dict()
        cases = {
            "probability below zero": lambda raw: raw["five_star"].update(
                {"base_probability": -0.1}
            ),
            "probability above one": lambda raw: raw["five_star"].update(
                {"base_probability": 1.1}
            ),
            "probability nan": lambda raw: raw["five_star"].update(
                {"base_probability": math.nan}
            ),
            "probability infinite": lambda raw: raw["five_star"].update(
                {"base_probability": math.inf}
            ),
            "probability bool": lambda raw: raw["five_star"].update(
                {"base_probability": True}
            ),
            "hard pity zero": lambda raw: raw["five_star"].update(
                {"hard_pity": 0}
            ),
            "hard pity negative": lambda raw: raw["five_star"].update(
                {"hard_pity": -1}
            ),
            "hard pity non-integer": lambda raw: raw["five_star"].update(
                {"hard_pity": 1.5}
            ),
            "hard pity bool": lambda raw: raw["five_star"].update(
                {"hard_pity": True}
            ),
            "reward negative": lambda raw: raw["rewards"][0].update(
                {"four_star": -1}
            ),
            "reward infinite": lambda raw: raw["rewards"][0].update(
                {"five_star": math.inf}
            ),
            "reward nan": lambda raw: raw["rewards"][0].update(
                {"six_star": math.nan}
            ),
            "reward bool": lambda raw: raw["rewards"][0].update(
                {"four_star": False}
            ),
        }
        for description, mutate in cases.items():
            with self.subTest(description=description):
                raw = copy.deepcopy(base)
                mutate(raw)
                with self.assertRaises(ValueError):
                    PoolConfig.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
