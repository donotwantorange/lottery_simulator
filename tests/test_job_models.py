"""Current task payload contracts independent of the retired v4 web UI."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from dashboard.job_models import JobState, RunParameters, read_json, result_payload, write_json
from dashboard.limits import SimulationLimits
from lottery_simulator.engine import simulate
from lottery_simulator.formats import JOB_FORMAT_VERSION, RESULT_FORMAT_VERSION
from lottery_simulator.rules.pool_config import load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


def valid_state():
    pool_id = str(uuid4())
    return JobState(
        job_id=str(uuid4()), status="running",
        parameters=RunParameters("rule1", 2, 1, 0, 42, True).to_dict(),
        completed_units=1, total_units=2,
        phase="validating", phase_completed=1, phase_total=2,
        owner_id=str(uuid4()), accepted_at=datetime.now(timezone.utc).isoformat(),
        pool_source={"id": pool_id, "revision": 1, "name": "测试池", "original_author": "作者"},
        limit_policy=SimulationLimits().to_dict(),
    )


class JobModelsTest(unittest.TestCase):
    def test_versions_are_explicit_strict_integers(self):
        params = RunParameters("rule1", 2, 1, 0, 42, True).to_dict()
        state = valid_state().to_dict()
        for loader, payload in ((RunParameters.from_dict, params), (JobState.from_dict, state)):
            for field in ("job_format_version", "sampling_version"):
                for value in (None, True, 1.0):
                    with self.subTest(loader=loader.__qualname__, field=field, value=value):
                        invalid = dict(payload)
                        invalid[field] = value
                        with self.assertRaises(ValueError):
                            loader(invalid)
        self.assertEqual(params["job_format_version"], JOB_FORMAT_VERSION)

    def test_parameters_keep_five_star_progress_and_pool_snapshot(self):
        pool = load_pool_config().to_dict()
        params = RunParameters("rule1", 10, 1, 0, 42, False, 7, pool)
        restored = RunParameters.from_dict(params.to_dict())
        self.assertEqual(restored.initial_five_star_pity, 7)
        self.assertEqual(restored.pool_config, pool)

    def test_job_state_round_trip_and_rejects_invalid_controls(self):
        state = valid_state()
        self.assertEqual(JobState.from_dict(state.to_dict()), state)
        for invalid in (
            replace(state, status="unknown"),
            replace(state, phase_completed=3),
            replace(state, phase_total=None),
            replace(state, cancel_requested=1),
            replace(state, cleanup_error=1),
            replace(state, owner_id=None),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    invalid.validate()

    def test_result_summary_excludes_records_and_keeps_sampling_metadata(self):
        rule = Rule1()
        payload = result_payload(simulate(rule, 2, seed=42, collect_records=True), rule, 0.25)
        self.assertEqual(payload["result_format_version"], RESULT_FORMAT_VERSION)
        self.assertEqual(payload["rule_version"], "2.0")
        self.assertEqual(payload["sampling_version"], 1)
        self.assertEqual(payload["record_count"], 2)
        self.assertNotIn("records", payload)
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_zero_theoretical_expectation_has_no_relative_error(self):
        rule = Rule1()
        result = replace(simulate(rule, 1, seed=42), mean_six_stars=0.0,
                         theoretical_expected_count=0.0)
        payload = result_payload(result, rule, 0.25)
        self.assertEqual(payload["mean_count_error"], 0.0)
        self.assertIsNone(payload["mean_count_relative_error"])

    def test_json_write_is_atomic_and_readable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json(path, valid_state().to_dict())
            self.assertEqual(JobState.from_dict(read_json(path)).status, "running")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
