import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard.models import JobState, RunParameters, read_json, result_payload, write_json
from lottery_simulator.engine import simulate
from lottery_simulator.rules.pool_config import load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


class DashboardModelsTest(unittest.TestCase):
    def test_serialized_parameters_require_explicit_versions(self):
        raw = RunParameters("rule1", 1, 1, 0, 42, False).to_dict()

        for field in ("job_format_version", "sampling_version"):
            with self.subTest(field=field):
                invalid = dict(raw)
                invalid.pop(field, None)
                with self.assertRaises(ValueError):
                    RunParameters.from_dict(invalid)

    def test_serialized_job_state_requires_explicit_versions(self):
        parameters = RunParameters("rule1", 1, 1, 0, 42, False)
        raw = JobState("id", "queued", parameters.to_dict(), 0, 1).to_dict()

        for field in ("job_format_version", "sampling_version"):
            with self.subTest(field=field):
                invalid = dict(raw)
                invalid.pop(field, None)
                with self.assertRaises(ValueError):
                    JobState.from_dict(invalid)

    def test_parameters_validate_trace_and_limits(self):
        with self.assertRaisesRegex(ValueError, "Trace"):
            RunParameters("rule1", 10, 2, 0, 42, True).validate()
        with self.assertRaisesRegex(ValueError, "上限"):
            RunParameters("rule1", 10_000_001, 1, 0, 42, False).validate()
        with self.assertRaisesRegex(ValueError, "Trace"):
            RunParameters("rule1", 100_001, 1, 0, 42, True).validate()
        RunParameters("rule1", 100_000, 1, 0, 42, True).validate()

    def test_parameters_append_five_star_pity_and_pool_snapshot_after_existing_positions(self):
        config = load_pool_config().to_dict()

        parameters = RunParameters("rule1", 10, 1, 0, 42, False, 7, config)

        self.assertEqual(parameters.initial_five_star_pity, 7)
        self.assertEqual(parameters.pool_config, config)
        self.assertEqual(parameters.to_dict()["pool_config"], config)

    def test_result_payload_is_json_round_trippable(self):
        rule = Rule1()
        result = simulate(rule, 2, seed=42, initial_pity=29)
        payload = result_payload(result, rule, 0.25)
        self.assertEqual(payload["rule_version"], "2.0")
        self.assertEqual(payload["duration_seconds"], 0.25)
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(set(payload["count_distribution"]), {"0"})
        self.assertNotIn("records", payload)
        self.assertEqual(payload["result_format_version"], 1)
        self.assertEqual(payload["sampling_version"], 1)
        self.assertEqual(payload["rng_algorithm"], "python.random.Random")
        self.assertIsInstance(payload["python_implementation"], str)
        self.assertIsInstance(payload["python_version"], str)
        self.assertEqual(payload["main_draws"], 2)
        self.assertAlmostEqual(payload["theoretical_mean_interval"], 53.89927355371174)
        self.assertAlmostEqual(payload["mean_count_error"], -0.096)
        self.assertEqual(payload["mean_count_relative_error"], -1.0)

    def test_result_payload_trace_has_only_nested_draw_result(self):
        rule = Rule1()
        payload = result_payload(simulate(rule, 1, seed=42, collect_records=True), rule, 0.1)
        record = payload["records"][0]
        self.assertEqual(record["record_format_version"], 1)
        self.assertEqual(record["draw_result"]["outcome"]["rarity"], 4)
        self.assertEqual(record["draw_result"]["state_before"],
                         {"misses_since_six_star": 0, "misses_since_five_or_higher": 0})
        self.assertNotIn("is_six_star", record)

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
