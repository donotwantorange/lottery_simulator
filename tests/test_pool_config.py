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
    def test_default_config_has_expected_roster_probabilities_and_rewards(self):
        config = load_pool_config()
        probabilities = config.six_star_character_probabilities()

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
        probabilities = config.six_star_character_probabilities()

        self.assertAlmostEqual(probabilities["UP-A"], 0.125)
        self.assertAlmostEqual(probabilities["限定-B"], 0.375)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_large_finite_up_weights_preserve_probabilities_and_character_expectations(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][0]["up_weight"] = 1e308
        raw["six_star_characters"][1].update(is_up=True, up_weight=1e308)
        config = PoolConfig.from_dict(raw)
        probabilities = config.six_star_character_probabilities()

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
