"""Chinese, file-based entry points for the pure simulator."""

import argparse
from dataclasses import replace
import json
import sqlite3
import sys
from time import perf_counter

from lottery_simulator.analysis import expected_simulation_results
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_POOL_DIRECTORY,
    DEFAULT_RULE_DIRECTORY, load_experiment_document, load_pool_document,
    load_rule_document, parse_config_json, read_config_json,
    resolve_pool_reference, resolve_rule_reference,
)
from lottery_simulator.events import event_counts
from lottery_simulator.engine import simulate
from lottery_simulator.formats import (
    EVENT_FORMAT_VERSION, RESULT_FORMAT_VERSION, RULE_VERSION, sampling_metadata,
)
from lottery_simulator.results import simulation_payload
from lottery_simulator.rules.definitions import BigInitial, ExperimentParameters
from lottery_simulator.rules.runtime import compile_pool, initial_context, normalize_parameters
from lottery_simulator.waiting_analysis import waiting_time_stats


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
        translations = {
            "the following arguments are required:": "缺少必需参数：",
            "unrecognized arguments:": "无法识别的参数：",
            "invalid choice:": "不支持的选项：",
            "choose from": "可选值",
            "expected one argument": "需要一个参数值",
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


def _boolean(value):
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    raise argparse.ArgumentTypeError("请使用true或false")


def _initial_small_pity(value):
    try:
        parsed = parse_config_json(value.encode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"初始小保底必须是严格JSON对象：{error}") from None
    if any(not isinstance(key, str) for key in parsed):
        raise argparse.ArgumentTypeError("初始小保底键必须是稀有度ID")
    return parsed


def _common_files(parser):
    parser.add_argument("--pool-config", help="新版池文件路径")
    parser.add_argument("--experiment-config", help="新版实验文件路径")
    parser.add_argument("--pool-directory", default=str(DEFAULT_POOL_DIRECTORY), help="按ID查找引用池的目录")
    parser.add_argument("--rule-directory", default=str(DEFAULT_RULE_DIRECTORY), help="按ID查找绑定规则的目录")
    parser.add_argument("--rule-config", help="显式规则文件；必须匹配池的ID或经确认的名称")
    parser.add_argument("--draws", type=_integer, help="每轮主抽数")
    parser.add_argument("--trials", type=_integer, help="实验轮数")
    parser.add_argument("--seed", type=_integer, help="任意精度整数随机种子")
    parser.add_argument("--initial-main-draws", type=_integer, help="历史累计主抽数")
    parser.add_argument("--initial-small-pity", type=_initial_small_pity, help="严格JSON对象：稀有度ID到未满足计数")
    parser.add_argument("--initial-target-obtained", nargs="?", const=True,
                         type=_boolean, help="历史是否已获得大保底目标（可写true或false；单独出现视为true）")
    parser.add_argument("--initial-big-pity", type=_integer, help="循环模式大保底连续未获计数")
    trace = parser.add_mutually_exclusive_group()
    trace.add_argument("--trace", dest="trace", action="store_true", default=None, help="开启过程Trace")
    trace.add_argument("--no-trace", dest="trace", action="store_false", help="关闭过程Trace")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="中文文本或结构化JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseParser(prog="lottery_simulator", description="本机抽奖分析工具；读取新版配置，不写入网页历史。")
    commands = parser.add_subparsers(dest="command", required=True, title="命令")
    analyze = commands.add_parser("analyze", help="分析池绑定规则及等待时间")
    _common_files(analyze)
    simulation = commands.add_parser("simulate", help="运行完整模拟并计算理论期望",
        epilog="本命令的Trace保存在内存；大量过程事件请使用网页流式保存。")
    _common_files(simulation)
    export = commands.add_parser("export-trace", help="按条件导出新版过程事件")
    export.add_argument("--database", required=True, help="明确指定的v6历史库路径")
    export.add_argument("--run-id", required=True, help="实验记录UUID")
    export.add_argument("--output", required=True, help="导出文件路径")
    export.add_argument("--trial-from", type=_integer, help="起始轮次")
    export.add_argument("--trial-to", type=_integer, help="结束轮次")
    export.add_argument("--event-type", choices=("draw", "character_grant"), help="事件类型")
    export.add_argument("--source", choices=("main", "bonus"), help="抽取来源")
    export.add_argument("--rarity-id", help="稀有度UUID")
    export.add_argument("--character-id", help="角色UUID")
    export.add_argument("--source-from", type=_integer, help="来源内起始位置")
    export.add_argument("--source-to", type=_integer, help="来源内结束位置")
    export.add_argument("--main-from", type=_integer, help="主抽累计触发位置起点（含）")
    export.add_argument("--main-to", type=_integer, help="主抽累计触发位置终点（含）")
    export.add_argument("--unnamed-character", action="store_true", help="仅未配置角色名单的抽次")
    return parser


def _confirm_resource(kind, resource, stdin, stderr):
    if not stdin.isatty():
        return False
    print(f"ID未匹配。候选{kind}：{resource.name}（ID：{resource.id}）", file=stderr)
    try:
        print("确认使用此名称候选？输入y确认：", end="", file=stderr, flush=True)
        answer = stdin.readline().strip().lower()
    except EOFError:
        return False
    return answer == "y"


def _load_experiment(args):
    if not args.experiment_config:
        return None
    return load_experiment_document(read_config_json(args.experiment_config))


def _load_pool(args, experiment, stdin, stderr):
    explicit = args.pool_config
    if explicit:
        pool = load_pool_document(read_config_json(explicit))
        if experiment and pool.id != experiment.pool_ref["id"]:
            try:
                by_id = resolve_pool_reference(experiment.pool_ref, args.pool_directory)
            except ValueError as error:
                if not str(error).startswith("无法按ID找到池"):
                    raise
                by_id = None
            if by_id is not None:
                raise ValueError("实验引用的池ID已解析到其他池，拒绝显式替换")
            if pool.name != experiment.pool_ref["name"] or not _confirm_resource("池", pool, stdin, stderr):
                raise ValueError("显式池文件与实验引用不匹配，拒绝静默替换")
        return pool
    if experiment:
        return resolve_pool_reference(experiment.pool_ref, args.pool_directory,
                                      interactive=stdin.isatty())
    return load_pool_document(read_config_json(DEFAULT_POOL_PATH))


def _load_rule(pool, args, stdin, stderr):
    reference = dict(pool.rule_ref)
    if args.rule_config:
        rule = load_rule_document(read_config_json(args.rule_config))
        if rule.id != reference["id"]:
            candidate = resolve_rule_reference(reference, args.rule_directory,
                confirm=lambda found: _confirm_resource("规则", found, stdin, stderr))
            if candidate.id != rule.id:
                raise ValueError("显式规则文件与池引用不匹配，拒绝静默替换")
        return rule, replace(pool, rule_ref={"id": rule.id, "name": rule.name})
    rule = resolve_rule_reference(reference, args.rule_directory,
        confirm=lambda candidate: _confirm_resource("规则", candidate, stdin, stderr))
    return rule, replace(pool, rule_ref={"id": rule.id, "name": rule.name})


def _parameters(args, experiment, compiled):
    if args.command == "simulate" and experiment is None and args.draws is None:
        raise ValueError("未指定实验文件时必须提供--draws")
    defaults = experiment.parameters if experiment else ExperimentParameters(
        draws=100 if args.command == "analyze" else 1, trials=1, seed=None,
        trace=False, initial_main_draws=0, initial_small_pity={},
        initial_big_pity=BigInitial(False, 0))
    values = defaults.to_dict()
    if args.draws is not None:
        values["draws"] = args.draws
    if args.trials is not None:
        values["trials"] = args.trials
    if args.seed is not None:
        values["seed"] = args.seed
    if args.trace is not None:
        values["trace"] = args.trace
    for option, key in (("initial_main_draws", "initial_main_draws"),
                        ("initial_small_pity", "initial_small_pity")):
        value = getattr(args, option)
        if value is not None:
            values[key] = value
    obtained, misses = args.initial_target_obtained, args.initial_big_pity
    if obtained is not None or misses is not None:
        big = dict(values["initial_big_pity"])
        if obtained is not None:
            big["target_obtained"] = obtained
        if misses is not None:
            big["misses"] = misses
        values["initial_big_pity"] = big
    parameters = ExperimentParameters.from_dict(values)
    normalized = normalize_parameters(compiled, parameters)
    if experiment:
        nonzero = (normalized.initial_main_draws or any(normalized.initial_small_pity.values()) or
                   normalized.initial_big_pity.target_obtained or normalized.initial_big_pity.misses)
        current_context = initial_context(compiled)
        if nonzero and experiment.initial_context != current_context:
            raise ValueError("初始历史缺少确认上下文或规则目标已变化，需重新确认实验上下文")
    return normalized


def _safe_json(payload, output):
    json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
    print(file=output)


def _label(compiled, rarity_id):
    rarity = next(item for item in compiled.rule.rarities if item.id == rarity_id)
    return compiled.pool.rarity_labels.get(rarity_id, rarity.name)


def _text_analysis(payload, compiled, output):
    params = payload["parameters"]
    print(f"规则：{compiled.rule.name}（ID：{compiled.rule.id}）", file=output)
    print(f"池：{compiled.pool.name}（ID：{compiled.pool.id}）", file=output)
    print(f"理论计算范围：每轮{params['draws']}次主抽；赠送抽与直接赠送不计入主抽等待时间。", file=output)
    theoretical = payload["theoretical"]
    _text_source_expectations(theoretical, compiled, output)
    _text_targets(compiled, params, output)
    waiting = payload["waiting_time"]
    target = waiting["target_rarity_id"]
    print(f"等待目标：{_label(compiled, target)}或更高；单位：新增主抽；来源：主池。", file=output)
    print(f"等待分析状态：{_status_label(waiting['status'])}", file=output)
    mean = waiting["mean"]
    print("等待期望：" + (f"{mean['value']:.8g} 抽" if mean["status"] == "finite" else _status_label(mean["status"])), file=output)
    if waiting.get("message"):
        print(f"等待分析说明：{waiting['message']}", file=output)


def _status_label(status):
    return {"finite": "有限", "geometric": "几何分布", "infinite": "无穷（存在永不获得的可能）",
            "unreachable": "不可达", "incomplete": "未完成"}.get(status, status)


def _target_name(compiled, character_id):
    character = next((c for group in compiled.pool.rarity_pools for c in group.characters
                      if c.id == character_id), None)
    if character is None:
        return "未配置"
    return f"{character.name}（{_label(compiled, character.rarity_id)}，ID：{character.id}）"


def _text_targets(compiled, parameters, output):
    policy = compiled.rule.big_pity
    if policy.enabled:
        print(f"大保底目标：{_target_name(compiled, compiled.targets['big_pity'])}；阈值：{policy.hard_pity}主抽。", file=output)
    grant = compiled.rule.grant
    if grant.enabled:
        upcoming = (parameters["initial_main_draws"] // grant.period + 1) * grant.period
        print(f"周期直接赠送目标：{_target_name(compiled, compiled.targets['periodic_grant'])}；周期：{grant.period}主抽；下次累计主抽：{upcoming}。", file=output)


def _text_source_expectations(theoretical, compiled, output):
    for source in ("main", "bonus", "total"):
        source_label = {"main": "主池", "bonus": "首次赠送池", "total": "抽取合计"}[source]
        summary = theoretical["draws"][source]
        print(f"{source_label}各档抽取理论期望（每轮）：", file=output)
        for rarity in sorted(compiled.rule.rarities, key=lambda item: item.rank, reverse=True):
            print(f"  {_label(compiled, rarity.id)}：{summary['rarity_counts'][rarity.id]:.8g}", file=output)
        for reward in compiled.pool.rewards:
            value = summary["reward_totals"][reward.id]
            if value:
                print(f"  奖励{reward.name}：{value:.8g}", file=output)
        print("  角色类别期望：", file=output)
        for rarity_id, categories in summary["category_counts"].items():
            names = {"up": "UP", "other_limited": "其他限定", "standard": "常驻",
                     "unnamed": "未配置角色名单"}
            values = [f"{names[name]} {count:.8g}" for name, count in categories.items() if count]
            if values:
                print(f"    {_label(compiled, rarity_id)}：" + "；".join(values), file=output)
    acquisitions = theoretical["acquisitions"]
    print("理论角色获得合计（含直接赠送）：", file=output)
    for group in compiled.pool.rarity_pools:
        for character in group.characters:
            value = acquisitions["character_counts"].get(character.id, 0)
            if value:
                print(f"  {character.name}（{_label(compiled, group.rarity_id)}）：{value:.8g}", file=output)
    grants = theoretical["grants"]
    if grants["trigger_count"]:
        print(f"理论周期赠送次数（每轮）：{grants['trigger_count']:.8g}；角色数：{grants['character_count']:.8g}。", file=output)


def _text_simulation(payload, compiled, output):
    params = payload["parameters"]
    sim = payload["simulation"]
    theory = payload["theoretical"]
    print(f"规则：{compiled.rule.name}（ID：{compiled.rule.id}）", file=output)
    print(f"池：{compiled.pool.name}（ID：{compiled.pool.id}）", file=output)
    print(f"每轮主抽：{params['draws']}；轮数：{params['trials']}；随机种子：{payload['seed']}", file=output)
    print(f"总主抽：{payload['counts']['main_draws']}；赠送抽：{payload['counts']['bonus_draws']}；直接赠送角色：{payload['counts']['granted_characters']}", file=output)
    print(f"总抽取数（主池＋赠送池）：{payload['counts']['total_draws']}。", file=output)
    print("模拟均值与理论期望（每轮）：", file=output)
    for source in ("main", "bonus", "total"):
        source_label = {"main": "主池", "bonus": "首次赠送池", "total": "抽取合计"}[source]
        print(f"{source_label}：", file=output)
        observed = sim["draws"][source]["rarity_counts"]
        expected = theory["draws"][source]["rarity_counts"]
        for rarity in sorted(compiled.rule.rarities, key=lambda item: item.rank, reverse=True):
            print(f"  {_label(compiled, rarity.id)}：模拟均值 {observed[rarity.id]:.8g}；理论期望 {expected[rarity.id]:.8g}", file=output)
        for reward in compiled.pool.rewards:
            seen = sim["draws"][source]["reward_totals"][reward.id]
            mean = theory["draws"][source]["reward_totals"][reward.id]
            if seen or mean:
                print(f"  奖励{reward.name}：模拟均值 {seen:.8g}；理论期望 {mean:.8g}", file=output)
    _text_targets(compiled, params, output)
    acquisition = sim["acquisitions"]["character_counts"]
    expected_acquisition = theory["acquisitions"]["character_counts"]
    print("角色获得合计（含直接赠送；直接赠送不计抽数、不触发抽取奖励）：", file=output)
    for group in compiled.pool.rarity_pools:
        for character in group.characters:
            value = acquisition.get(character.id, 0)
            expected = expected_acquisition.get(character.id, 0)
            if value or expected:
                category = "UP" if character.is_up else "其他限定" if character.is_limited else "常驻"
                print(f"  {character.name}（{_label(compiled, group.rarity_id)}，{category}）：模拟均值 {value:.8g}；理论期望 {expected:.8g}", file=output)
    print(f"Trace事件数：{payload['event_count']}", file=output)


def main(argv=None, stdout=None) -> int:
    output = sys.stdout if stdout is None else stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export-trace":
        try:
            from dashboard.trace_export import export_trace
            filters = {key: getattr(args, key) for key in (
                "trial_from", "trial_to", "event_type", "source", "rarity_id",
                "character_id", "source_from", "source_to", "main_from", "main_to",
                "unnamed_character") if getattr(args, key) is not None}
            export_trace(args.database, args.run_id, args.output, **filters)
        except (OSError, TypeError, ValueError, sqlite3.Error) as error:
            parser.error(f"导出未完成：{error}")
        print(f"过程事件已导出：{args.output}", file=output)
        return 0
    try:
        experiment = _load_experiment(args)
        pool = _load_pool(args, experiment, sys.stdin, sys.stderr)
        rule, pool = _load_rule(pool, args, sys.stdin, sys.stderr)
        compiled = compile_pool(rule, pool)
        parameters = _parameters(args, experiment, compiled)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    if args.command == "analyze":
        try:
            theory = expected_simulation_results(compiled, parameters)
            highest = max(compiled.rule.rarities, key=lambda item: item.rank)
            waiting = waiting_time_stats(compiled, parameters, highest.id)
            counts = event_counts(rule, parameters)
            payload = {"result_format_version": RESULT_FORMAT_VERSION,
                       "event_format_version": EVENT_FORMAT_VERSION,
                       "rule_version": RULE_VERSION, **sampling_metadata(),
                       "counts": {name: getattr(counts, name) for name in counts.__dataclass_fields__},
                       "rule_snapshot": rule.to_dict(), "pool_snapshot": pool.to_dict(),
                       "targets": dict(compiled.targets),
                       "initial_context": initial_context(compiled).to_dict(),
                       "parameters": parameters.to_dict(), "theoretical": theory,
                       "waiting_time": waiting}
        except (OSError, TypeError, ValueError) as error:
            parser.error(f"分析未完成：{error}")
        if args.format == "json":
            _safe_json(payload, output)
        else:
            _text_analysis(payload, compiled, output)
        return 0
    start = perf_counter()
    try:
        result = simulate(compiled, parameters)
        payload = simulation_payload(result, compiled, perf_counter() - start,
                                     include_events=result.trace_enabled)
    except (OSError, TypeError, ValueError) as error:
        parser.error(f"模拟未完成：{error}")
    if args.format == "json":
        _safe_json(payload, output)
    else:
        _text_simulation(payload, compiled, output)
    return 0
