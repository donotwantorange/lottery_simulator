import math
import unittest

from lottery_simulator.probability import sample_distribution


class SampleDistributionTest(unittest.TestCase):
    def test_order_and_threshold(self):
        values = ((6, 0.008), (5, 0.08), (4, 0.912))

        self.assertEqual(sample_distribution(values, 0.0), 6)
        self.assertEqual(sample_distribution(values, 0.008), 5)
        self.assertEqual(sample_distribution(values, 0.5), 4)

    def test_zero_tail_never_selected(self):
        values = (("a", 0.9999999999995), ("zero", 0.0))

        self.assertEqual(sample_distribution(values, 0.9999999999998), "a")

    def test_accepts_valid_int_and_string_options(self):
        self.assertEqual(sample_distribution(((1, 1.0),), 0.25), 1)
        self.assertEqual(sample_distribution((("one", 1.0),), 0.25), "one")

    def test_rejects_empty_distribution(self):
        with self.assertRaises(ValueError):
            sample_distribution((), 0.0)

    def test_rejects_bool_or_other_option_types(self):
        for option in (True, 1.0, None):
            with self.subTest(option=option), self.assertRaises(ValueError):
                sample_distribution(((option, 1.0),), 0.0)

    def test_rejects_duplicate_options(self):
        with self.assertRaises(ValueError):
            sample_distribution((("same", 0.5), ("same", 0.5)), 0.0)

    def test_rejects_invalid_probability_values(self):
        for probability in (
            -0.1,
            1.1,
            math.nan,
            math.inf,
            -math.inf,
            True,
            "0.5",
            b"1.0",
            10**400,
        ):
            with self.subTest(probability=probability), self.assertRaises(ValueError):
                sample_distribution((("item", probability),), 0.0)

    def test_rejects_probability_sum_outside_tolerance(self):
        with self.assertRaises(ValueError):
            sample_distribution((("a", 0.4), ("b", 0.5)), 0.0)

    def test_rejects_invalid_roll_values(self):
        for roll in (-0.1, 1.0, math.nan, math.inf, True, "0.5", b"0.5"):
            with self.subTest(roll=roll), self.assertRaises(ValueError):
                sample_distribution((("item", 1.0),), roll)


if __name__ == "__main__":
    unittest.main()
