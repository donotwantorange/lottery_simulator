from io import StringIO
import json
import unittest

from lottery_simulator.cli import main


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        output = StringIO()
        code = main(list(arguments), stdout=output)
        return code, output.getvalue()

    def test_analyze_json_contains_reference_mean(self):
        code, output = self.run_cli("analyze", "--format", "json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertAlmostEqual(payload["mean"], 53.32595362219928)
        self.assertEqual(payload["hard_pity"], 80)
        self.assertEqual(len(payload["probability_table"]), 80)
        self.assertEqual(payload["probability_table"][64]["conditional_probability"], 0.058)

    def test_simulate_json_contains_reproduction_parameters(self):
        code, output = self.run_cli(
            "simulate", "--draws", "10", "--trials", "2", "--seed", "42",
            "--initial-pity", "60", "--format", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rule"], "rule1")
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["initial_pity"], 60)
        self.assertNotIn("records", payload)
        self.assertIn("mean_count_error", payload)
        self.assertEqual(sum(payload["count_distribution"].values()), 2)

    def test_trace_prints_each_draw(self):
        code, output = self.run_cli(
            "simulate", "--draws", "2", "--trials", "1", "--seed", "42", "--trace"
        )
        self.assertEqual(code, 0)
        self.assertIn("抽次", output)
        self.assertIn("保底位置", output)

    def test_trace_rejects_multiple_trials(self):
        with self.assertRaises(SystemExit):
            self.run_cli("simulate", "--draws", "2", "--trials", "2", "--trace")


if __name__ == "__main__":
    unittest.main()
