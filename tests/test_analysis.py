"""The Rule1 analysis API was replaced by the dynamic contract."""

import unittest

from lottery_simulator import analysis


class AnalysisApiTests(unittest.TestCase):
    def test_only_dynamic_finite_expectations_are_exported(self):
        self.assertTrue(callable(analysis.expected_simulation_results))
        self.assertFalse(hasattr(analysis, "expected_pool_results"))
        self.assertFalse(hasattr(analysis, "expected_six_stars"))
