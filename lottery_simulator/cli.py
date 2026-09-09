import argparse
from dataclasses import asdict
import json
import sys
from typing import TextIO

from lottery_simulator.analysis import distribution_stats
from lottery_simulator.engine import SimulationResult, simulate
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.rule_1 import Rule1


RULES = {"rule1": Rule1}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lottery_simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--rule", choices=RULES, default="rule1")
    analyze.add_argument("--format", choices=("text", "json"), default="text")
    simulation = commands.add_parser("simulate")
    simulation.add_argument("--rule", choices=RULES, default="rule1")
    simulation.add_argument("--draws", type=int, required=True)
    simulation.add_argument("--trials", type=int, default=1)
    simulation.add_argument("--seed", type=int)
    simulation.add_argument("--initial-pity", type=int, default=0)
    simulation.add_argument("--trace", action="store_true")
    simulation.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _analysis_payload(rule):
    stats = distribution_stats(rule)
    cumulative = 0.0
    table = []
    for pull, first_six_star_probability in enumerate(stats.probabilities, start=1):
        cumulative += first_six_star_probability
        table.append(
            {
                "pull": pull,
                "conditional_probability": rule.probability(DrawState(pull - 1)),
                "first_six_star_probability": first_six_star_probability,
                "cumulative_probability": cumulative,
            }
        )
    return {
        "rule": rule.name,
        "hard_pity": rule.max_pity,
        "probability_table": table,
        "mean": stats.mean,
        "variance": stats.variance,
        "standard_deviation": stats.standard_deviation,
        "median": stats.median,
        "mode": stats.mode,
        "quantiles": {str(level): pull for level, pull in stats.quantiles.items()},
        "long_run_rate": stats.long_run_rate,
    }


def _simulation_payload(result: SimulationResult, rule, include_records: bool):
    theoretical_mean_interval = distribution_stats(rule).mean
    mean_count_error = result.mean_six_stars - result.theoretical_expected_count
    payload = {
        "rule": result.rule_name,
        "draws": result.draws,
        "trials": result.trials,
        "seed": result.seed,
        "initial_pity": result.initial_pity,
        "count_distribution": result.count_distribution,
        "mean_six_stars": result.mean_six_stars,
        "at_least_one_rate": result.at_least_one_rate,
        "observed_mean_interval": result.observed_mean_interval,
        "theoretical_mean_interval": theoretical_mean_interval,
        "theoretical_expected_count": result.theoretical_expected_count,
        "mean_count_error": mean_count_error,
        "mean_count_relative_error": mean_count_error / result.theoretical_expected_count,
    }
    if include_records:
        payload["records"] = [asdict(record) for record in result.records]
    return payload


def _write_text_analysis(payload, output: TextIO) -> None:
    print(f"规则：{payload['rule']}", file=output)
    print(f"六星平均间隔：{payload['mean']:.5f} 抽", file=output)
    print(f"长期综合六星率：{payload['long_run_rate']:.5%}", file=output)
    print(f"标准差：{payload['standard_deviation']:.5f} 抽", file=output)
    print(f"中位数：第 {payload['median']} 抽", file=output)
    print(f"众数：第 {payload['mode']} 抽", file=output)
    print("抽次  条件六星概率  首次出六星概率  累计概率", file=output)
    for row in payload["probability_table"]:
        print(
            f"{row['pull']}  {row['conditional_probability']:.4%}  "
            f"{row['first_six_star_probability']:.6%}  "
            f"{row['cumulative_probability']:.6%}",
            file=output,
        )


def _write_text_simulation(payload, output: TextIO, trace: bool) -> None:
    print(f"规则：{payload['rule']}", file=output)
    print(f"每轮抽数：{payload['draws']}", file=output)
    print(f"实验轮数：{payload['trials']}", file=output)
    print(f"随机种子：{payload['seed']}", file=output)
    print(f"初始保底：{payload['initial_pity']}", file=output)
    print(f"平均六星数：{payload['mean_six_stars']:.6f}", file=output)
    print(f"至少一个六星：{payload['at_least_one_rate']:.4%}", file=output)
    print(f"理论六星期望：{payload['theoretical_expected_count']:.6f}", file=output)
    print(f"期望误差：{payload['mean_count_error']:+.6f}", file=output)
    print(f"期望相对误差：{payload['mean_count_relative_error']:+.4%}", file=output)
    print("六星数量分布：", file=output)
    for count, frequency in sorted(payload["count_distribution"].items()):
        print(f"  {count} 个：{frequency / payload['trials']:.4%}", file=output)
    observed = payload["observed_mean_interval"]
    if observed is not None:
        print(f"已完成周期平均间隔：{observed:.5f} 抽", file=output)
    print(
        f"完整周期理论平均间隔：{payload['theoretical_mean_interval']:.5f} 抽",
        file=output,
    )
    if trace:
        print("抽次  保底位置  六星概率  结果  抽后保底", file=output)
        for record in payload["records"]:
            result = "六星" if record["is_six_star"] else "未出"
            after = record["state_after"]["misses_since_six_star"]
            print(
                f"{record['draw_index']}  {record['pity_position']}  "
                f"{record['probability']:.1%}  {result}  {after}",
                file=output,
            )


def main(argv=None, stdout=None) -> int:
    output = sys.stdout if stdout is None else stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    rule = RULES[args.rule]()
    if args.command == "analyze":
        payload = _analysis_payload(rule)
        if args.format == "json":
            json.dump(payload, output, ensure_ascii=False, indent=2)
            print(file=output)
        else:
            _write_text_analysis(payload, output)
        return 0
    if args.trace and args.trials != 1:
        parser.error("--trace requires --trials 1")
    try:
        result = simulate(rule, args.draws, args.trials, args.seed, args.initial_pity)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    payload = _simulation_payload(result, rule, include_records=args.trace)
    if args.format == "json":
        json.dump(payload, output, ensure_ascii=False, indent=2)
        print(file=output)
    else:
        _write_text_simulation(payload, output, args.trace)
    return 0
