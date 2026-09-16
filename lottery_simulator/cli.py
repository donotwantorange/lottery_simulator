import argparse
from dataclasses import asdict
import json
import sys
from typing import TextIO

from lottery_simulator.analysis import distribution_stats
from lottery_simulator.engine import SimulationResult, simulate
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.pool_config import load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


RULES = {"rule1": Rule1}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lottery_simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--rule", choices=RULES, default="rule1")
    analyze.add_argument("--pool-config")
    analyze.add_argument("--format", choices=("text", "json"), default="text")
    simulation = commands.add_parser("simulate")
    simulation.add_argument("--rule", choices=RULES, default="rule1")
    simulation.add_argument("--draws", type=int, required=True)
    simulation.add_argument("--trials", type=int, default=1)
    simulation.add_argument("--seed", type=int)
    simulation.add_argument("--initial-pity", type=int, default=0)
    simulation.add_argument("--initial-five-star-pity", type=int, default=0)
    simulation.add_argument("--pool-config")
    simulation.add_argument("--trace", action="store_true")
    simulation.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _write_config_summary(pool_config: dict, output: TextIO) -> None:
    five_star = pool_config["five_star"]
    print("配置摘要：", file=output)
    print(f"  UP占比：{pool_config['up_share']:.4%}", file=output)
    pity_status = "开启" if five_star["pity_enabled"] else "关闭"
    print(
        f"  五星保底：{pity_status}（硬保底 {five_star['hard_pity']} 抽，"
        f"基础概率 {five_star['base_probability']:.4%}）",
        file=output,
    )
    print("  六星角色：", file=output)
    for character in pool_config["six_star_characters"]:
        tags = []
        if character["is_up"]:
            tags.append("UP")
        if character["is_limited"]:
            tags.append("限定")
        suffix = f"（{'、'.join(tags)}）" if tags else ""
        print(f"    {character['name']}{suffix}", file=output)
    print("  奖励：", file=output)
    for reward in pool_config["rewards"]:
        print(
            f"    {reward['name']}：四星 {reward['four_star']:g}，"
            f"五星 {reward['five_star']:g}，六星 {reward['six_star']:g}",
            file=output,
        )


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
        "rule_version": getattr(rule, "version", None),
        "pool_config": rule.config.to_dict(),
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
    theoretical_source_summaries = {}
    for source, summary in result.theoretical_source_summaries.items():
        summary = dict(summary)
        summary["rarity_counts"] = summary["mean_rarity_counts"]
        theoretical_source_summaries[source] = summary
    payload = {
        "rule": result.rule_name,
        "rule_version": getattr(rule, "version", None),
        "draws": result.draws,
        "main_draws": result.draws,
        "bonus_draws": result.bonus_draws,
        "total_draws": result.total_draws,
        "trials": result.trials,
        "seed": result.seed,
        "initial_pity": result.initial_pity,
        "initial_five_star_pity": result.initial_five_star_pity,
        "initial_main_draws": result.initial_main_draws,
        "final_main_draws": result.final_main_draws,
        "count_distribution": result.count_distribution,
        "mean_main_six_stars": result.mean_main_six_stars,
        "mean_bonus_six_stars": result.mean_bonus_six_stars,
        "mean_six_stars": result.mean_six_stars,
        "at_least_one_rate": result.at_least_one_rate,
        "observed_mean_interval": result.observed_mean_interval,
        "theoretical_mean_interval": theoretical_mean_interval,
        "theoretical_expected_main_count": result.theoretical_expected_main_count,
        "theoretical_expected_bonus_count": result.theoretical_expected_bonus_count,
        "theoretical_expected_count": result.theoretical_expected_count,
        "mean_count_error": mean_count_error,
        "mean_count_relative_error": (
            mean_count_error / result.theoretical_expected_count
            if result.theoretical_expected_count != 0.0 else None
        ),
        "pool_config": result.pool_config,
        "source_summaries": result.source_summaries,
        "theoretical_source_summaries": theoretical_source_summaries,
        "source_distributions": result.source_distributions,
        "at_least_one_rates": result.at_least_one_rates,
    }
    if include_records:
        payload["records"] = [asdict(record) for record in result.records]
    return payload


def _write_text_analysis(payload, output: TextIO) -> None:
    print(f"规则版本：{payload['rule_version']}", file=output)
    _write_config_summary(payload["pool_config"], output)
    print(f"规则：{payload['rule']}", file=output)
    print(f"六星平均间隔：{payload['mean']:.5f} 抽", file=output)
    print(f"长期综合六星率：{payload['long_run_rate']:.5%}", file=output)
    print(f"方差：{payload['variance']:.5f} 抽²", file=output)
    print(f"标准差：{payload['standard_deviation']:.5f} 抽", file=output)
    print(f"中位数：第 {payload['median']} 抽", file=output)
    print(f"众数：第 {payload['mode']} 抽", file=output)
    for level, pull in payload["quantiles"].items():
        print(f"{float(level):.0%} 分位数：第 {pull} 抽", file=output)
    print("抽次  条件六星概率  首次出六星概率  累计概率", file=output)
    for row in payload["probability_table"]:
        print(
            f"{row['pull']}  {row['conditional_probability']:.4%}  "
            f"{row['first_six_star_probability']:.6%}  "
            f"{row['cumulative_probability']:.6%}",
            file=output,
        )


def _write_text_simulation(payload, output: TextIO, trace: bool) -> None:
    print(f"规则版本：{payload['rule_version']}", file=output)
    _write_config_summary(payload["pool_config"], output)
    print(f"规则：{payload['rule']}", file=output)
    print(f"主池抽数：{payload['main_draws']}", file=output)
    print(f"赠送抽数：{payload['bonus_draws']}", file=output)
    print(f"总抽数：{payload['total_draws']}", file=output)
    print(f"实验轮数：{payload['trials']}", file=output)
    print(f"随机种子：{payload['seed']}", file=output)
    print(f"初始保底：{payload['initial_pity']}", file=output)
    print(f"初始五星保底：{payload['initial_five_star_pity']}", file=output)
    print(f"初始主池累计抽数：{payload['initial_main_draws']}", file=output)
    print(f"结束主池累计抽数：{payload['final_main_draws']}", file=output)
    print(f"主池平均六星数：{payload['mean_main_six_stars']:.6f}", file=output)
    print(f"赠送平均六星数：{payload['mean_bonus_six_stars']:.6f}", file=output)
    print(f"总平均六星数：{payload['mean_six_stars']:.6f}", file=output)
    print(f"至少一个六星：{payload['at_least_one_rate']:.4%}", file=output)
    print(
        f"主池理论六星期望：{payload['theoretical_expected_main_count']:.6f}",
        file=output,
    )
    print(
        f"赠送理论六星期望：{payload['theoretical_expected_bonus_count']:.6f}",
        file=output,
    )
    print(f"总理论六星期望：{payload['theoretical_expected_count']:.6f}", file=output)
    print(f"期望误差：{payload['mean_count_error']:+.6f}", file=output)
    relative_error = payload["mean_count_relative_error"]
    relative_error_text = "不可用" if relative_error is None else f"{relative_error:+.4%}"
    print(f"期望相对误差：{relative_error_text}", file=output)
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
    source_names = {"main": "主池", "bonus": "赠送", "total": "总计"}
    for source, source_name in source_names.items():
        summary = payload["source_summaries"][source]
        print(f"{source_name}星级：", file=output)
        for rarity, count in sorted(summary["mean_rarity_counts"].items()):
            print(f"  {rarity}星：{count:.6f}", file=output)
        print(f"{source_name}六星类别：", file=output)
        category_names = {
            "up": "UP六星",
            "other_limited": "其他限定六星",
            "standard": "常驻六星",
        }
        for category, count in summary["mean_six_star_categories"].items():
            print(f"  {category_names.get(category, category)}：{count:.6f}", file=output)
        print(f"{source_name}角色：", file=output)
        for character in payload["pool_config"]["six_star_characters"]:
            name = character["name"]
            print(f"  {name}：{summary['mean_character_counts'][name]:.6f}", file=output)
        print(f"{source_name}奖励：", file=output)
        for reward in payload["pool_config"]["rewards"]:
            name = reward["name"]
            print(f"  {name}：{summary['mean_rewards'][name]:.6f}", file=output)
        print(f"{source_name}双保底：", file=output)
        pity_names = {
            "five_star": "五星保底",
            "six_star_hard": "六星硬保底",
        }
        for pity_name, count in summary["mean_pity_triggers"].items():
            print(f"  {pity_names.get(pity_name, pity_name)}：{count:.6f}", file=output)
    if trace:
        print(
            "抽次  来源  来源序号  主池累计抽数  保底位置  六星概率  结果  抽后主池保底  "
            "星级  角色  奖励  4/5/6星概率  主池后双保底  来源池前双保底  "
            "来源池后双保底  五星保底触发  六星硬保底触发",
            file=output,
        )
        for record in payload["records"]:
            result = "六星" if record["is_six_star"] else "未出"
            after = record["state_after"]["misses_since_six_star"]
            source = "主池" if record["source"] == "main" else "赠送"
            probabilities = record["rarity_probabilities"]
            rewards = ", ".join(
                f"{name}={amount:g}" for name, amount in record["rewards"].items()
            ) or "—"
            state_text = lambda state: (
                f"({state['misses_since_six_star']},{state['misses_since_five_or_higher']})"
            )
            print(
                f"{record['draw_index']}  {source}  {record['source_index']}  "
                f"{record['main_draws_completed']}  "
                f"{record['pity_position']}  "
                f"{record['probability']:.1%}  {result}  {after}"
                f"  {record['rarity']}星  {record['six_star_character'] or '—'}  "
                f"{rewards}  {probabilities['four_star']:.1%}/"
                f"{probabilities['five_star']:.1%}/{probabilities['six_star']:.1%}  "
                f"主池后{state_text(record['state_after'])}  "
                f"来源池前{state_text(record['source_state_before'])}  "
                f"来源池后{state_text(record['source_state_after'])}  "
                f"{'是' if record['five_star_pity_triggered'] else '否'}  "
                f"{'是' if record['six_star_hard_pity_triggered'] else '否'}",
                file=output,
            )


def main(argv=None, stdout=None) -> int:
    output = sys.stdout if stdout is None else stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_pool_config(args.pool_config)
    except FileNotFoundError:
        parser.error("配置文件不存在或不可读取")
    except json.JSONDecodeError:
        parser.error("配置文件 JSON 格式错误")
    except OSError:
        parser.error("配置文件不存在或不可读取")
    except (TypeError, ValueError):
        parser.error("配置文件内容无效：请检查概率、角色、权重、奖励和保底配置")
    try:
        rule = RULES[args.rule](config=config)
    except ValueError as error:
        parser.error(str(error))
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
        rule.rarity_probabilities(
            DrawState(args.initial_pity, args.initial_five_star_pity)
        )
    except (TypeError, ValueError):
        parser.error("初始保底参数无效：请检查六星与五星保底进度范围")
    try:
        result = simulate(
            rule,
            args.draws,
            args.trials,
            args.seed,
            args.initial_pity,
            initial_five_star_pity=args.initial_five_star_pity,
            collect_records=args.trace,
        )
    except (TypeError, ValueError):
        parser.error("模拟参数无效：请检查抽数、轮数、随机种子等参数")
    payload = _simulation_payload(result, rule, include_records=args.trace)
    if args.format == "json":
        json.dump(payload, output, ensure_ascii=False, indent=2)
        print(file=output)
    else:
        _write_text_simulation(payload, output, args.trace)
    return 0
