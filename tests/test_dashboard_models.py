import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard.models import JobState, RunParameters, read_json, result_payload, write_json
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class DashboardModelsTest(unittest.TestCase):
    def test_parameters_validate_trace_and_limits(self):
        with self.assertRaisesRegex(ValueError, "Trace"):
            RunParameters("rule1", 10, 2, 0, 42, True).validate()
        with self.assertRaisesRegex(ValueError, "上限"):
            RunParameters("rule1", 10_000_001, 1, 0, 42, False).validate()

    def test_result_payload_is_json_round_trippable(self):
        rule = Rule1()
        result = simulate(rule, 2, seed=42, initial_pity=29)
        payload = result_payload(result, rule, 0.25)
        self.assertEqual(payload["rule_version"], "1.2")
        self.assertEqual(payload["duration_seconds"], 0.25)
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(set(payload["count_distribution"]), {"0"})
        self.assertIsInstance(payload["records"], list)
        self.assertEqual(payload["main_draws"], 2)
        self.assertAlmostEqual(payload["theoretical_mean_interval"], 53.89927355371174)
        self.assertAlmostEqual(payload["mean_count_error"], -0.096)
        self.assertEqual(payload["mean_count_relative_error"], -1.0)

    def test_result_payload_uses_none_for_zero_theoretical_expected_count(self):
        rule = Rule1()
        result = replace(
            simulate(rule, 1, seed=42),
            mean_six_stars=0.0,
            theoretical_expected_count=0.0,
        )

        payload = result_payload(result, rule, 0.25)

        self.assertEqual(payload["mean_count_error"], 0.0)
        self.assertIsNone(payload["mean_count_relative_error"])

    def test_json_write_is_atomic_and_readable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json(path, {"status": "running"})
            self.assertEqual(read_json(path), {"status": "running"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_job_state_uses_known_status(self):
        with self.assertRaisesRegex(ValueError, "status"):
            JobState("id", "unknown", {}, 0, 1).validate()
