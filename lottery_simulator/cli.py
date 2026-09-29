import argparse
from dataclasses import asdict
import json
import sys
from typing import TextIO

from lottery_simulator.analysis import distribution_stats
from lottery_simulator.engine import SimulationResult, simulate
from lottery_simulator.formats import RESULT_FORMAT_VERSION, sampling_metadata
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.rule_1 import Rule1
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_POOL_DIRECTORY, load_pool_document,
    load_experiment_document, read_config_json, resolve_pool_reference,
    validate_experiment_parameters, rarity_label,
)


RULES = {"rule1": Rule1}


class ChineseParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"
        self.add_argument("-h", "--help", action="help", help="显示中文帮助并退出")

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：")

    def format_help(self):
        return super().format_help().replace("usage:", "用法：")

    def error(self, message):
        # argparse generates these diagnostics before application validation.
        translations = {
            "the following arguments are required:": "缺少必需参数：",
            "unrecognized arguments:": "无法识别的参数：",
            "invalid choice:": "不支持的选项：",
            "choose from": "可选值",
            "expected one argument": "需要一个参数值",
            "not allowed with argument": "不能与以下参数同时使用",
            "argument ": "参数 ",
        }
        for english, chinese in translations.items():
            message = message.replace(english, chinese)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}：错误：{message}\n")


def _integer(value):
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("参数值必须是整数") from None


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseParser(prog="lottery_simulator", description="本机抽奖分析工具；使用操作系统文件权限，不要求网页登录，不自动写入网页历史。")
    commands = parser.add_subparsers(dest="command", required=True, title="命令")
    analyze = commands.add_parser("analyze", help="分析池绑定规则", description="本机只读分析，读取新版池配置；文件访问由操作系统权限控制。",
                                  epilog="示例：python -m lottery_simulator analyze --pool-config configs/pools/default.json")
    analyze.add_argument("--pool-config", help="新版池文件路径（默认使用项目默认池）")
    analyze.add_argument("--format", choices=("text", "json"), default="text", help="输出格式：中文文本或结构化JSON")
    simulation = commands.add_parser("simulate", help="运行模拟", description="模拟使用池绑定规则，显式参数覆盖实验文件参数，不自动写入网页历史。",
        epilog="示例：python -m lottery_simulator simulate --experiment-config configs/experiments/default.json --draws 10 --trials 2；或 python -m lottery_simulator simulate --pool-config configs/pools/default.json --draws 10。Trace保存在内存，大结果请使用网页模拟落库。")
    simulation.add_argument("--draws", type=_integer, help="每轮主抽数（无实验文件时必填）")
    simulation.add_argument("--trials", type=_integer, help="实验轮数（默认1）")
    simulation.add_argument("--seed", type=_integer, help="整数随机种子（默认随机生成）")
    simulation.add_argument("--initial-pity", type=_integer, help="初始六星保底进度（默认0）")
    simulation.add_argument("--initial-five-star-pity", type=_integer, help="初始五星保底进度（默认0）")
    simulation.add_argument("--pool-config", help="显式选择新版池文件，解决实验引用")
    simulation.add_argument("--experiment-config", help="新版实验文件路径")
    simulation.add_argument("--pool-directory", default=str(DEFAULT_POOL_DIRECTORY), help="按ID查找引用池的目录（默认configs/pools）")
    trace = simulation.add_mutually_exclusive_group()
    trace.add_argument("--trace", action="store_true", default=None, help="开启逐抽Trace，覆盖文件开关")
    trace.add_argument("--no-trace", dest="trace", action="store_false", help="关闭逐抽Trace，覆盖文件开关")
    simulation.add_argument("--format", choices=("text", "json"), default="text", help="输出格式：中文文本或结构化JSON")
    export = commands.add_parser("export-trace", help="本机只读Trace导出维护工具",
        description="拥有数据库文件访问权限即可导出，不受网页登录或网页用户隔离控制；仅限可信本机维护，不自动写入网页历史。",
        epilog="示例：python -m lottery_simulator export-trace --database /tmp/history_v5.sqlite3 --run-id 实验UUID --output /tmp/trace.jsonl")
    export.add_argument("--database", required=True, help="可读取的本机数据库文件路径")
    export.add_argument("--run-id", required=True, help="实验记录UUID")
    export.add_argument("--output", required=True, help="导出文件路径")
    export.add_argument("--trial-from", type=_integer, help="起始轮次")
    export.add_argument("--trial-to", type=_integer, help="结束轮次")
    export.add_argument("--source", choices=("main", "bonus"), help="来源：main主池或bonus赠送池")
    export.add_argument("--rarity", type=_integer, choices=(4, 5, 6), help="稳定星级编号4、5、6，不受显示改名影响")
    export.add_argument("--character-name", help="角色名称筛选")
    export.add_argument("--unnamed-character", action="store_true", help="仅导出未配置角色名单的抽次")
    export.add_argument("--source-from", type=_integer, help="来源内起始抽次")
    export.add_argument("--source-to", type=_integer, help="来源内结束抽次")
    return parser


def _write_config_summary(pool_config: dict, output: TextIO) -> None:
    five_star = pool_config["five_star"]
    label = lambda rarity: rarity_label(rarity, pool_config.get("rarity_labels"))
    print("配置摘要：", file=output)
    print(f"  {label(4)}角色人数：{len(pool_config['four_star_characters'])}", file=output)
    print(f"  {label(5)}角色人数：{len(pool_config['five_star_characters'])}", file=output)
    print(f"  UP占比：{pool_config['up_share']:.4%}", file=output)
    pity_status = "开启" if five_star["pity_enabled"] else "关闭"
    print(
        f"  {label(5)}保底：{pity_status}（硬保底 {five_star['hard_pity']} 抽，"
        f"基础概率 {five_star['base_probability']:.4%}）",
        file=output,
    )
    print(f"  {label(6)}角色：", file=output)
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
            f"    {reward['name']}：{label(4)} {reward['four_star']:g}，"
            f"{label(5)} {reward['five_star']:g}，{label(6)} {reward['six_star']:g}",
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
        "rule_version": rule.version,
        "result_format_version": RESULT_FORMAT_VERSION,
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
        "rule_version": rule.version,
        "result_format_version": RESULT_FORMAT_VERSION,
        **sampling_metadata(),
        "draws": result.draws,
        "main_draws": result.draws,
        "bonus_draws": result.bonus_draws,
        "total_draws": result.total_draws,
        "trials": result.trials,
        "trace_enabled": result.trace_enabled,
        "record_count": result.record_count,
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
    six = rarity_label(6, payload["pool_config"].get("rarity_labels"))
    print(f"规则版本：{payload['rule_version']}", file=output)
    _write_config_summary(payload["pool_config"], output)
    print(f"规则：{payload['rule']}", file=output)
    print(f"{six}平均间隔：{payload['mean']:.5f} 抽", file=output)
    print(f"长期综合{six}率：{payload['long_run_rate']:.5%}", file=output)
    print(f"方差：{payload['variance']:.5f} 抽²", file=output)
    print(f"标准差：{payload['standard_deviation']:.5f} 抽", file=output)
    print(f"中位数：第 {payload['median']} 抽", file=output)
    print(f"众数：第 {payload['mode']} 抽", file=output)
    for level, pull in payload["quantiles"].items():
        print(f"{float(level):.0%} 分位数：第 {pull} 抽", file=output)
    print(f"抽次  条件{six}概率  首次出{six}概率  累计概率", file=output)
    for row in payload["probability_table"]:
        print(
            f"{row['pull']}  {row['conditional_probability']:.4%}  "
            f"{row['first_six_star_probability']:.6%}  "
            f"{row['cumulative_probability']:.6%}",
            file=output,
        )


def _write_text_simulation(payload, output: TextIO, trace: bool) -> None:
    label = lambda rarity: rarity_label(rarity, payload["pool_config"].get("rarity_labels"))
    print(f"规则版本：{payload['rule_version']}", file=output)
    _write_config_summary(payload["pool_config"], output)
    print(f"规则：{payload['rule']}", file=output)
    print(f"主池抽数：{payload['main_draws']}", file=output)
    print(f"赠送抽数：{payload['bonus_draws']}", file=output)
    print(f"总抽数：{payload['total_draws']}", file=output)
    print(f"实验轮数：{payload['trials']}", file=output)
    print(f"随机种子：{payload['seed']}", file=output)
    print(f"初始{label(6)}保底：{payload['initial_pity']}", file=output)
    print(f"初始{label(5)}保底：{payload['initial_five_star_pity']}", file=output)
    print(f"初始主池累计抽数：{payload['initial_main_draws']}", file=output)
    print(f"结束主池累计抽数：{payload['final_main_draws']}", file=output)
    print(f"主池平均{label(6)}数：{payload['mean_main_six_stars']:.6f}", file=output)
    print(f"赠送平均{label(6)}数：{payload['mean_bonus_six_stars']:.6f}", file=output)
    print(f"总平均{label(6)}数：{payload['mean_six_stars']:.6f}", file=output)
    print(f"至少一个{label(6)}：{payload['at_least_one_rate']:.4%}", file=output)
    print(
        f"主池理论{label(6)}期望：{payload['theoretical_expected_main_count']:.6f}",
        file=output,
    )
    print(
        f"赠送理论{label(6)}期望：{payload['theoretical_expected_bonus_count']:.6f}",
        file=output,
    )
    print(f"总理论{label(6)}期望：{payload['theoretical_expected_count']:.6f}", file=output)
    print(f"期望误差：{payload['mean_count_error']:+.6f}", file=output)
    relative_error = payload["mean_count_relative_error"]
    relative_error_text = "不可用" if relative_error is None else f"{relative_error:+.4%}"
    print(f"期望相对误差：{relative_error_text}", file=output)
    print(f"{label(6)}数量分布：", file=output)
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
            print(f"  {label(rarity)}：{count:.6f}", file=output)
        print(f"{source_name}{label(6)}类别：", file=output)
        category_names = {
            "up": f"UP {label(6)}",
            "other_limited": f"其他限定{label(6)}",
            "standard": f"常驻{label(6)}",
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
            "five_star": f"{label(5)}保底",
            "six_star_hard": f"{label(6)}硬保底",
        }
        for pity_name, count in summary["mean_pity_triggers"].items():
            print(f"  {pity_names.get(pity_name, pity_name)}：{count:.6f}", file=output)
    if trace:
        print(
            "轮次  抽次  来源  来源序号  主池累计抽数  "
            f"稀有度  角色  奖励  {label(4)}/{label(5)}/{label(6)}概率  主池前双保底  主池后双保底  来源池前双保底  "
            f"来源池后双保底  {label(5)}保底触发  {label(6)}硬保底触发",
            file=output,
        )
        for record in payload["records"]:
            draw_result = record["draw_result"]
            outcome = draw_result["outcome"]
            source = "主池" if record["source"] == "main" else "赠送"
            probabilities = draw_result["probabilities"]
            rewards = ", ".join(
                f"{name}={amount:g}" for name, amount in outcome["rewards"].items()
            ) or "—"
            state_text = lambda state: (
                f"({state['misses_since_six_star']},{state['misses_since_five_or_higher']})"
            )
            print(
                f"{record['trial_index']}  {record['draw_index']}  {source}  {record['source_index']}  "
                f"{record['main_draws_completed']}  "
                f"{label(outcome['rarity'])}  {outcome['character_name'] or '未配置角色名单'}  "
                f"{rewards}  {probabilities['four_star']:.1%}/"
                f"{probabilities['five_star']:.1%}/{probabilities['six_star']:.1%}  "
                f"主池前{state_text(record['main_state_before'])}  "
                f"主池后{state_text(record['main_state_after'])}  "
                f"来源池前{state_text(draw_result['state_before'])}  "
                f"来源池后{state_text(draw_result['state_after'])}  "
                f"{'是' if outcome['five_star_pity_triggered'] else '否'}  "
                f"{'是' if outcome['six_star_hard_pity_triggered'] else '否'}",
                file=output,
            )


def main(argv=None, stdout=None) -> int:
    output = sys.stdout if stdout is None else stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export-trace":
        from dashboard.trace_export import export_trace
        try:
            export_trace(
                args.database, args.run_id, args.output,
                trial_from=args.trial_from, trial_to=args.trial_to,
                source=args.source, rarity=args.rarity,
                character_name=args.character_name,
                unnamed_character=args.unnamed_character,
                source_from=args.source_from, source_to=args.source_to,
            )
        except (OSError, TypeError, ValueError):
            parser.error("导出失败：请检查本机文件权限、数据库版本及筛选参数")
        return 0
    try:
        experiment = None
        if args.command == "simulate" and args.experiment_config:
            experiment = load_experiment_document(read_config_json(args.experiment_config))
        if args.pool_config or experiment is None:
            document = load_pool_document(read_config_json(args.pool_config or DEFAULT_POOL_PATH))
        else:
            document = resolve_pool_reference(experiment.pool_ref, args.pool_directory,
                                              interactive=sys.stdin.isatty())
        rule = RULES[document.rule_name](config=document.to_pool_config())
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    if args.command == "analyze":
        payload = _analysis_payload(rule)
        payload["pool_document"] = document.to_dict()
        if args.format == "json":
            json.dump(payload, output, ensure_ascii=False, indent=2)
            print(file=output)
        else:
            _write_text_analysis(payload, output)
        return 0
    parameters = (dict(experiment.parameters) if experiment else
                  {"draws": None, "trials": 1, "seed": None, "initial_pity": 0,
                   "initial_five_star_pity": 0, "trace": False})
    for key in parameters:
        explicit = getattr(args, key)
        if explicit is not None:
            parameters[key] = explicit
    if parameters["draws"] is None:
        parser.error("无实验文件时必须指定--draws每轮主抽数")
    try:
        validate_experiment_parameters(parameters, document)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    try:
        result = simulate(
            rule,
            parameters["draws"],
            parameters["trials"],
            parameters["seed"],
            parameters["initial_pity"],
            initial_five_star_pity=parameters["initial_five_star_pity"],
            collect_records=parameters["trace"],
        )
    except (TypeError, ValueError):
        parser.error("模拟参数无效：请检查抽数、轮数、随机种子等参数")
    payload = _simulation_payload(result, rule, include_records=parameters["trace"])
    payload["pool_document"] = document.to_dict()
    if args.format == "json":
        json.dump(payload, output, ensure_ascii=False, indent=2)
        print(file=output)
    else:
        _write_text_simulation(payload, output, parameters["trace"])
    return 0
