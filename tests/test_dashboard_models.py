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
        RunParameters("rule1", 10, 2, 0, 42, True).validate()
        with self.assertRaisesRegex(ValueError, "上限"):
            RunParameters("rule1", 10_000_001, 1, 0, 42, False).validate()
        RunParameters("rule1", 100_001, 1, 0, 42, True).validate()

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
        self.assertEqual(payload["result_format_version"], 2)
        self.assertEqual(payload["sampling_version"], 1)
        self.assertEqual(payload["rng_algorithm"], "python.random.Random")
        self.assertIsInstance(payload["python_implementation"], str)
        self.assertIsInstance(payload["python_version"], str)
        self.assertEqual(payload["main_draws"], 2)
        self.assertAlmostEqual(payload["theoretical_mean_interval"], 53.89927355371174)
        self.assertAlmostEqual(payload["mean_count_error"], -0.096)
        self.assertEqual(payload["mean_count_relative_error"], -1.0)

    def test_result_payload_trace_keeps_trace_summary_but_never_records(self):
        rule = Rule1()
        payload = result_payload(simulate(rule, 1, seed=42, collect_records=True), rule, 0.1)
        self.assertNotIn("records", payload)
        self.assertIs(payload["trace_enabled"], True)
        self.assertEqual(payload["record_count"], 1)

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

    def test_job_state_reads_legacy_payload_without_control_fields(self):
        parameters = RunParameters("rule1", 1, 1, 0, 42, False)
        state = JobState("id", "queued", parameters.to_dict(), 0, 1)
        raw = state.to_dict()
        for field in ("phase_completed", "phase_total", "cancel_requested", "cleanup_error"):
            raw.pop(field, None)

        restored = JobState.from_dict(raw)

        self.assertIsNone(getattr(restored, "phase_completed", None))
        self.assertIsNone(getattr(restored, "phase_total", None))
        self.assertFalse(getattr(restored, "cancel_requested", False))
        self.assertIsNone(getattr(restored, "cleanup_error", None))

    def test_job_state_round_trips_control_fields(self):
        parameters = RunParameters("rule1", 1, 1, 0, 42, False)
        state = JobState(
            "id", "running", parameters.to_dict(), 0, 1,
            phase="validating", phase_completed=1, phase_total=2,
            cancel_requested=True, cleanup_error="cleanup pending",
        )

        restored = JobState.from_dict(state.to_dict())

        self.assertEqual(restored, state)

    def test_job_state_rejects_invalid_control_fields(self):
        parameters = RunParameters("rule1", 1, 1, 0, 42, False)
        base = JobState("id", "running", parameters.to_dict(), 0, 1)
        cases = (
            {"phase_completed": True, "phase_total": 1},
            {"phase_completed": -1, "phase_total": 1},
            {"phase_completed": 0, "phase_total": -1},
            {"phase_completed": 2, "phase_total": 1},
            {"phase_completed": 1, "phase_total": None},
            {"phase_completed": None, "phase_total": 1},
            {"phase_completed": 1, "phase_total": "2"},
            {"phase_completed": 0, "phase_total": True},
            {"cancel_requested": 1},
            {"cleanup_error": 1},
        )

        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(base, **changes).validate()

    def test_job_state_accepts_new_phases(self):
        parameters = RunParameters("rule1", 1, 1, 0, 42, False)
        for phase in ("theory", "validating", "committing"):
            with self.subTest(phase=phase):
                JobState(
                    "id", "running", parameters.to_dict(), 0, 1,
                    phase=phase,
                ).validate()
