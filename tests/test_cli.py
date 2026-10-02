"""CLI contract checks; run together with the planned task-16 acceptance suite."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from io import StringIO
from unittest.mock import patch

from lottery_simulator.cli import main
from lottery_simulator.config_documents import (
    DEFAULT_EXPERIMENT_PATH, DEFAULT_POOL_PATH, DEFAULT_RULE_PATH,
    read_config_json,
)


class CliTest(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        output = StringIO()
        code = main(list(args), stdout=output)
        return code, output.getvalue()

    def test_default_files_trace_counts_and_dynamic_json(self):
        code, output = self.run_cli("simulate", "--pool-config", str(DEFAULT_POOL_PATH),
            "--draws", "30", "--trials", "2", "--seed", "42", "--trace", "--format", "json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rule_snapshot"]["name"], "zmd")
        self.assertEqual(payload["counts"]["main_draws"], 60)
        self.assertEqual(payload["counts"]["bonus_draws"], 20)
        self.assertEqual(payload["counts"]["total_draws"], 80)
        self.assertEqual(payload["event_count"], 80)
        self.assertEqual(len(payload["events"]), 80)
        self.assertEqual(payload["parameters"]["seed"], 42)
        self.assertNotIn("mean_six_stars", output)
        self.assertNotIn("Infinity", output)
        self.assertNotIn("NaN", output)

    def test_experiment_defaults_and_arbitrary_integer_seed(self):
        exp = read_config_json(DEFAULT_EXPERIMENT_PATH)
        self.assertEqual(exp["parameters"]["trials"], 1000)
        large_seed = 2**200 + 987654321
        _, output = self.run_cli("simulate", "--experiment-config", str(DEFAULT_EXPERIMENT_PATH),
            "--draws", "1", "--trials", "1", "--seed", str(large_seed), "--format", "json")
        self.assertEqual(json.loads(output)["seed"], large_seed)

    def test_old_fixed_pity_flags_and_old_config_are_rejected(self):
        for flag in ("--initial-pity", "--initial-five-star-pity"):
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--draws", "1", flag, "0"], stdout=StringIO())
            self.assertEqual(error.exception.code, 2)
        with TemporaryDirectory() as directory:
            old_config = Path(directory, "old-pool.json")
            old_config.write_text('{"format_version":2}', encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--pool-config", str(old_config), "--draws", "1"], stdout=StringIO())
            self.assertEqual(error.exception.code, 2)
        with self.assertRaises(SystemExit) as error:
            main(["simulate"], stdout=StringIO())
        self.assertEqual(error.exception.code, 2)

    def test_initial_small_pity_requires_strict_json_object(self):
        for raw in ('[]', '{"a":1,"a":2}', '{"x":NaN}', '"text"'):
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--draws", "1", "--initial-small-pity", raw], stdout=StringIO())
            self.assertEqual(error.exception.code, 2)

    def test_initial_history_and_next_periodic_grant_at_480(self):
        _, output = self.run_cli("simulate", "--pool-config", str(DEFAULT_POOL_PATH),
            "--draws", "230", "--trials", "1", "--seed", "9", "--trace",
            "--initial-main-draws", "250", "--initial-small-pity", "{}",
            "--initial-target-obtained", "--format", "json")
        payload = json.loads(output)
        grants = [event for event in payload["events"] if event["event_type"] == "character_grant"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["grant"]["trigger_main_draw"], 480)

    def test_wrong_rule_config_cannot_replace_pool_binding(self):
        pool = read_config_json(DEFAULT_POOL_PATH)
        with TemporaryDirectory() as directory:
            path = Path(directory, "other.json")
            other = read_config_json(DEFAULT_RULE_PATH)
            other["id"] = "a33e8fb2-6ca9-4f89-9d7f-e4975c5c4aaa"
            path.write_text(json.dumps(other), encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--pool-config", str(DEFAULT_POOL_PATH), "--rule-config", str(path),
                      "--draws", "1"], stdout=StringIO())
            self.assertEqual(error.exception.code, 2)

    def test_export_trace_delegates_event_filters_to_streaming_export(self):
        with patch("dashboard.trace_export.export_trace") as export:
            code, output = self.run_cli("export-trace", "--database", "history_v6.sqlite3",
                "--run-id", "id", "--output", "trace.jsonl", "--event-type", "character_grant",
                "--main-from", "240", "--main-to", "480")
        self.assertEqual(code, 0)
        self.assertIn("过程事件已导出", output)
        self.assertEqual(export.call_args.kwargs["event_type"], "character_grant")
        self.assertEqual(export.call_args.kwargs["main_from"], 240)

    def test_simulate_text_golden_for_dynamic_default_rarities(self):
        _, output = self.run_cli("simulate", "--draws", "1", "--trials", "1", "--seed", "42")
        self.assertIn("四星：模拟均值 1；理论期望 0.912", output)
        self.assertIn("五星：模拟均值 0；理论期望 0.08", output)
        self.assertIn("六星：模拟均值 0；理论期望 0.008", output)
        self.assertIn("主抽：1", output)
        self.assertIn("赠送抽：0", output)
        self.assertIn("直接赠送角色：0", output)
        self.assertIn("下次累计主抽：240", output)

    def test_analyze_text_identifies_waiting_units_and_theory(self):
        _, output = self.run_cli("analyze", "--draws", "1")
        self.assertIn("理论期望", output)
        self.assertIn("新增主抽", output)
        self.assertIn("主池", output)

    def test_analyze_preserves_experiment_draw_count(self):
        experiment = read_config_json(DEFAULT_EXPERIMENT_PATH)
        experiment["parameters"]["draws"] = 3
        experiment["parameters"]["trials"] = 1
        with TemporaryDirectory() as directory:
            path = Path(directory, "experiment.json")
            path.write_text(json.dumps(experiment), encoding="utf-8")
            _, output = self.run_cli("analyze", "--experiment-config", str(path), "--format", "json")
        self.assertEqual(json.loads(output)["parameters"]["draws"], 3)

    def test_nonzero_experiment_history_requires_current_context(self):
        experiment = read_config_json(DEFAULT_EXPERIMENT_PATH)
        experiment["parameters"]["initial_main_draws"] = 1
        with TemporaryDirectory() as directory:
            path = Path(directory, "experiment.json")
            path.write_text(json.dumps(experiment), encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--experiment-config", str(path)], stdout=StringIO())
        self.assertEqual(error.exception.code, 2)

    def test_nonzero_experiment_history_rejects_stale_context(self):
        experiment = read_config_json(DEFAULT_EXPERIMENT_PATH)
        experiment["parameters"]["initial_main_draws"] = 1
        experiment["initial_context"] = {
            "rule_id": "00000000-0000-0000-0000-000000000001",
            "rarity_ids": [item["id"] for item in read_config_json(DEFAULT_RULE_PATH)["rarities"]],
            "big_mode": "disable_after_obtain",
            "big_target_id": read_config_json(DEFAULT_POOL_PATH)["rarity_pools"][-1]["characters"][0]["id"],
        }
        with TemporaryDirectory() as directory:
            path = Path(directory, "experiment.json")
            path.write_text(json.dumps(experiment), encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                main(["simulate", "--experiment-config", str(path)], stdout=StringIO())
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
