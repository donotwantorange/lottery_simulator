from io import StringIO
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lottery_simulator.cli import RULES, main
from lottery_simulator.rules.rule_1 import Rule1
from lottery_simulator.rules.pool_config import load_pool_config


class DelayedSixStarRule(Rule1):
    name = "delayed-six-star"

    def probability(self, state):
        super().probability(state)
        return 1.0 if state.misses_since_six_star == self.max_pity - 1 else 0.0


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        output = StringIO()
        code = main(list(arguments), stdout=output)
        return code, output.getvalue()

    def test_analyze_json_contains_reference_mean(self):
        code, output = self.run_cli("analyze", "--format", "json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertAlmostEqual(payload["mean"], 53.89927355371174)
        self.assertEqual(payload["hard_pity"], 80)
        self.assertEqual(len(payload["probability_table"]), 80)
        self.assertEqual(payload["probability_table"][64]["conditional_probability"], 0.008)
        self.assertEqual(payload["probability_table"][65]["conditional_probability"], 0.058)

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
        self.assertAlmostEqual(
            payload["mean_count_relative_error"],
            payload["mean_count_error"] / payload["theoretical_expected_count"],
        )
        self.assertEqual(sum(payload["count_distribution"].values()), 2)

    def test_bonus_statistics_are_separate_in_json(self):
        code, output = self.run_cli(
            "simulate", "--draws", "30", "--trials", "2", "--seed", "42",
            "--format", "json",
        )

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["main_draws"], 30)
        self.assertEqual(payload["bonus_draws"], 10)
        self.assertEqual(payload["total_draws"], 40)
        self.assertIn("mean_main_six_stars", payload)
        self.assertIn("mean_bonus_six_stars", payload)
        self.assertAlmostEqual(payload["theoretical_expected_bonus_count"], 0.08)
        self.assertAlmostEqual(
            payload["theoretical_expected_count"],
            payload["theoretical_expected_main_count"] + 0.08,
        )

    def test_trace_displays_main_and_bonus_sources_separately(self):
        code, output = self.run_cli(
            "simulate", "--draws", "30", "--trials", "1", "--seed", "42",
            "--trace",
        )

        self.assertEqual(code, 0)
        self.assertIn("主池抽数：30", output)
        self.assertIn("赠送抽数：10", output)
        self.assertIn("总抽数：40", output)
        self.assertIn("来源  来源序号", output)
        self.assertIn("赠送  1", output)
        self.assertIn("赠送  10", output)

    def test_main_draw_counter_is_in_text_and_json_results(self):
        code, text_output = self.run_cli(
            "simulate", "--draws", "2", "--trials", "1", "--seed", "42",
            "--initial-pity", "29", "--trace",
        )
        self.assertEqual(code, 0)
        self.assertIn("初始主池累计抽数：29", text_output)
        self.assertIn("结束主池累计抽数：31", text_output)
        self.assertIn("主池累计抽数", text_output)

        code, json_output = self.run_cli(
            "simulate", "--draws", "2", "--trials", "1", "--seed", "42",
            "--initial-pity", "29", "--trace", "--format", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(json_output)
        self.assertEqual(payload["initial_main_draws"], 29)
        self.assertEqual(payload["final_main_draws"], 31)
        self.assertEqual(
            [record["main_draws_completed"] for record in payload["records"]],
            [30] + [30] * 10 + [31],
        )

    def test_batch_main_draw_counters_are_per_trial(self):
        code, output = self.run_cli(
            "simulate", "--draws", "2", "--trials", "3", "--seed", "42",
            "--initial-pity", "29", "--format", "json",
        )

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["initial_main_draws"], 29)
        self.assertEqual(payload["final_main_draws"], 31)

    def test_analyze_text_includes_variance_and_quantiles(self):
        code, output = self.run_cli("analyze")
        self.assertEqual(code, 0)
        self.assertIn("方差：530.66740", output)
        for level, draw in ((90, 73), (95, 74), (99, 76)):
            with self.subTest(level=level):
                self.assertIn(f"{level}% 分位数：第 {draw} 抽", output)

    def test_zero_expectation_simulation_formats(self):
        RULES[DelayedSixStarRule.name] = DelayedSixStarRule
        self.addCleanup(RULES.pop, DelayedSixStarRule.name)
        for output_format in ("json", "text"):
            with self.subTest(output_format=output_format):
                code, output = self.run_cli(
                    "simulate", "--rule", DelayedSixStarRule.name,
                    "--draws", "1", "--trials", "2", "--seed", "42",
                    "--format", output_format,
                )
                self.assertEqual(code, 0)
                if output_format == "json":
                    payload = json.loads(output)
                    self.assertEqual(payload["theoretical_expected_count"], 0.0)
                    self.assertEqual(payload["mean_count_error"], 0.0)
                    self.assertIsNone(payload["mean_count_relative_error"])
                    self.assertEqual(payload["count_distribution"], {"0": 2})
                else:
                    self.assertIn("理论六星期望：0.000000", output)
                    self.assertIn("期望误差：+0.000000", output)
                    self.assertIn("期望相对误差：不可用", output)

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

    def test_real_module_entry_point_returns_json(self):
        completed = subprocess.run(
            [
                sys.executable, "-m", "lottery_simulator", "simulate",
                "--draws", "1", "--trials", "1", "--seed", "7",
                "--format", "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["draws"], 1)

    def test_cli_loads_pool_config_and_reports_structured_results(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            raw = load_pool_config().to_dict()
            raw["up_share"] = 0.6
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            code, output = self.run_cli(
                "simulate", "--draws", "10", "--trials", "2", "--seed", "42",
                "--pool-config", str(path), "--initial-five-star-pity", "3",
                "--format", "json",
            )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rule_version"], "2.0")
        self.assertEqual(payload["pool_config"]["up_share"], 0.6)
        self.assertEqual(payload["initial_five_star_pity"], 3)
        self.assertIn("rarity_counts", payload["theoretical_source_summaries"]["total"])
        self.assertIn("source_summaries", payload)
        self.assertIn("source_distributions", payload)
        self.assertIn("at_least_one_rates", payload)

    def test_analyze_pool_config_reports_config_in_json_and_text(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            raw = load_pool_config().to_dict()
            raw["up_share"] = 1.0
            raw["six_star_characters"] = raw["six_star_characters"][:1]
            raw["six_star_characters"][0]["name"] = "独占角色"
            raw["rewards"] = [{"name": "独占奖励", "four_star": 1, "five_star": 2, "six_star": 3}]
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            code, json_output = self.run_cli(
                "analyze", "--pool-config", str(path), "--format", "json"
            )
            self.assertEqual(code, 0)
            payload = json.loads(json_output)
            self.assertEqual(payload["rule_version"], "2.0")
            self.assertEqual(payload["pool_config"]["up_share"], 1.0)
            code, text_output = self.run_cli("analyze", "--pool-config", str(path))
        self.assertEqual(code, 0)
        self.assertIn("配置摘要", text_output)
        self.assertIn("独占角色", text_output)
        self.assertIn("独占奖励", text_output)

    def test_simulation_text_reports_configured_sections_and_dynamic_names(self):
        code, output = self.run_cli("simulate", "--draws", "30", "--seed", "42")
        self.assertEqual(code, 0)
        for label in (
            "配置摘要", "主池星级", "赠送星级", "总计星级", "六星类别", "UP六星",
            "其他限定六星", "常驻六星", "角色", "奖励", "双保底", "五星保底",
            "六星硬保底",
        ):
            self.assertIn(label, output)
        for name in ("UP-A", "限定-B", "常驻-I", "奖励A", "奖励B"):
            self.assertIn(name, output)

    def test_cli_rejects_missing_malformed_and_semantically_invalid_configs(self):
        with self.assertRaises(SystemExit):
            self.run_cli("analyze", "--pool-config", "/no/such/pool.json")
        with TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.run_cli("analyze", "--pool-config", str(malformed))

            invalid = Path(directory) / "invalid.json"
            raw = load_pool_config().to_dict()
            raw["up_share"] = 1.5
            invalid.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.run_cli("analyze", "--pool-config", str(invalid))

    def test_cli_rejects_initial_five_star_pity_out_of_range_and_disabled_pity(self):
        with self.assertRaises(SystemExit):
            self.run_cli("simulate", "--draws", "1", "--initial-five-star-pity", "10")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "disabled.json"
            raw = load_pool_config().to_dict()
            raw["five_star"]["pity_enabled"] = False
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.run_cli(
                    "simulate", "--draws", "1", "--pool-config", str(path),
                    "--initial-five-star-pity", "1",
                )

    def test_trace_json_contains_extended_outcome_and_double_pity_fields(self):
        code, output = self.run_cli(
            "simulate", "--draws", "1", "--seed", "42", "--trace", "--format", "json"
        )
        self.assertEqual(code, 0)
        record = json.loads(output)["records"][0]
        for field in (
            "rarity", "rewards", "five_star_pity_triggered",
            "six_star_hard_pity_triggered", "source_state_before", "source_state_after",
        ):
            self.assertIn(field, record)


if __name__ == "__main__":
    unittest.main()
