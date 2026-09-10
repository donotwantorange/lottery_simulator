import json
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
        payload = result_payload(result, rule.version, 0.25)
        self.assertEqual(payload["rule_version"], "1.1")
        self.assertEqual(payload["duration_seconds"], 0.25)
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(set(payload["count_distribution"]), {"0"})
        self.assertIsInstance(payload["records"], list)

    def test_json_write_is_atomic_and_readable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json(path, {"status": "running"})
            self.assertEqual(read_json(path), {"status": "running"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_job_state_uses_known_status(self):
        with self.assertRaisesRegex(ValueError, "status"):
            JobState("id", "unknown", {}, 0, 1).validate()
