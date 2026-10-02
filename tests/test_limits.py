import os
import unittest
from unittest.mock import patch

from dataclasses import replace

from dashboard.limits import SimulationLimits, TraceLimits
from tests.fixtures_rules import default_parameters, make_default_compiled


class TraceLimitsTest(unittest.TestCase):
    def test_defaults_keep_batch_size_as_a_fixed_constant(self):
        with patch.dict(os.environ, {}, clear=True):
            limits = TraceLimits.from_env()

        self.assertEqual(limits.max_records, 1_000_000)
        self.assertEqual(limits.max_download_records, 10_000)
        self.assertEqual(limits.batch_size, 1000)

    def test_from_env_reads_only_the_two_trace_capacity_limits(self):
        environment = {
            "LOTTERY_MAX_TRACE_RECORDS": "001234",
            "LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS": "567",
            "LOTTERY_TRACE_BATCH_SIZE": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            limits = TraceLimits.from_env()

        self.assertEqual(limits, TraceLimits(1234, 567, 1000))

    def test_from_env_rejects_non_positive_integer_strings(self):
        for value in ("", "0", "-1", "1.5", " 1", "+1"):
            for name in (
                "LOTTERY_MAX_TRACE_RECORDS",
                "LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS",
            ):
                with self.subTest(name=name, value=value):
                    with patch.dict(os.environ, {name: value}, clear=True):
                        with self.assertRaises(ValueError):
                            TraceLimits.from_env()

    def test_event_limit_counts_one_grant_per_trigger_and_trace_off_keeps_work(self):
        compiled = make_default_compiled()
        compiled = replace(compiled, rule=replace(compiled.rule,
                           grant=replace(compiled.rule.grant, quantity=2)))
        parameters = default_parameters(draws=480, trials=1, trace=True)
        counts = SimulationLimits(max_records=492).validate(compiled, parameters)
        self.assertEqual((counts.total_draws, counts.grant_triggers,
                          counts.granted_characters, counts.trace_events), (490, 2, 4, 492))
        with self.assertRaises(ValueError):
            SimulationLimits(max_records=491).validate(compiled, parameters)
        counts = SimulationLimits(max_records=1).validate(
            compiled, replace(parameters, trace=False))
        self.assertEqual((counts.trace_events, counts.total_draws + counts.grant_triggers),
                         (0, 492))

    def test_admin_exemption_does_not_allow_invalid_types_or_overflow(self):
        for policy in (TraceLimits, SimulationLimits):
            with self.assertRaises(ValueError):
                policy(max_records=True)
            with self.assertRaises(ValueError):
                policy(batch_size=None)
        with self.assertRaises(ValueError):
            SimulationLimits(None, None, None, None, None).validate(
                make_default_compiled(), {**default_parameters(trials=1).to_dict(),
                                         "draws": 2**63})


if __name__ == "__main__":
    unittest.main()
