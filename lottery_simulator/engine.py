"""Random execution, event aggregation and the complete simulation entry."""

from collections.abc import Callable
from dataclasses import replace
import math
import random
import secrets

from lottery_simulator.control import (
    CancelCheck, PhaseCallback, ProgressCallback, SimulationCancelled, check_cancelled,
)
from lottery_simulator.events import event_counts
from lottery_simulator.formats import EVENT_FORMAT_VERSION
from lottery_simulator.probability import sample_distribution
from lottery_simulator.results import DrawOutcome, DrawResult, ProcessEvent, SimulationResult
from lottery_simulator.rules.definitions import ExperimentParameters
from lottery_simulator.rules.runtime import (
    CompiledPool, DrawState, advance_state, character_probabilities, compile_pool,
    initial_state, normalize_parameters, pity_status, rarity_probabilities,
)


def draw_once(compiled: CompiledPool, state: DrawState, rng: random.Random) -> DrawResult:
    probabilities = rarity_probabilities(compiled, state)
    rarity_id = sample_distribution(tuple(probabilities.items()), rng.random())
    characters = character_probabilities(compiled, rarity_id, state)
    character_id = sample_distribution(tuple(characters.items()), rng.random()) if characters else None
    character = next((c for p in compiled.pool.rarity_pools for c in p.characters
                      if c.id == character_id), None)
    outcome = DrawOutcome(
        rarity_id, character_id, character.name if character else None,
        bool(character and character.is_up), bool(character and character.is_limited),
        {reward.id: reward.amounts.get(rarity_id, 0.0) for reward in compiled.pool.rewards},
        pity_status(compiled, state),
    )
    return DrawResult(outcome, probabilities, characters.get(character_id) if characters else None,
                      state, advance_state(compiled, state, rarity_id, character_id))


def bonus_pool(compiled: CompiledPool) -> CompiledPool:
    """Independent pool shared by random and theoretical bonus draws."""
    rule = compiled.rule
    if not rule.bonus.enabled:
        raise ValueError("首次赠送池未启用")
    names = {r.id: r.name for r in rule.rarities}
    rarities = tuple(replace(r, name=names[r.id]) for r in rule.bonus.rarities)
    return compile_pool(replace(rule, rarities=rarities,
                                big_pity=replace(rule.big_pity, enabled=False),
                                bonus=replace(rule.bonus, enabled=False),
                                grant=replace(rule.grant, enabled=False)), compiled.pool)


def _empty_summary(compiled, kind):
    rarities = {r.id: 0 for r in sorted(compiled.rule.rarities, key=lambda r: r.rank, reverse=True)}
    summary = {
        "rarity_counts": rarities,
        "character_counts": {c.id: 0 for p in compiled.pool.rarity_pools for c in p.characters},
        "category_counts": {key: {name: 0 for name in ("up", "other_limited", "standard", "unnamed")}
                            for key in rarities},
    }
    if kind == "draws":
        summary.update(draw_count=0, reward_totals={r.id: 0.0 for r in compiled.pool.rewards},
                       pity_triggers={"soft": dict(rarities), "hard": dict(rarities), "big": 0})
    else:
        summary["character_count"] = 0
        if kind == "grants":
            summary["trigger_count"] = 0
    return summary


def _add_acquisition(summary, rarity_id, character_id, is_up, is_limited, quantity=1):
    summary["rarity_counts"][rarity_id] += quantity
    category = "unnamed" if character_id is None else "up" if is_up else "other_limited" if is_limited else "standard"
    summary["category_counts"][rarity_id][category] += quantity
    if character_id is not None:
        summary["character_counts"][character_id] += quantity
        if "character_count" in summary:
            summary["character_count"] += quantity


def _finite_add(left, right):
    result = left + right
    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError("奖励累计或汇总数值溢出，不能保存非有限结果")
    return result


def _add_draw(summary, outcome):
    _add_acquisition(summary, outcome.rarity_id, outcome.character_id, outcome.is_up, outcome.is_limited)
    summary["draw_count"] += 1
    for key, value in outcome.rewards.items():
        summary["reward_totals"][key] = _finite_add(summary["reward_totals"][key], value)
    for group in ("soft", "hard"):
        for rarity_id in outcome.pity_status[f"{group}_active"]:
            summary["pity_triggers"][group][rarity_id] += 1
    summary["pity_triggers"]["big"] += int(outcome.pity_status["big_forced"])


def _merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict):
            _merge(target[key], value)
        else:
            target[key] = _finite_add(target[key], value)


def _scale(values, divisor):
    return {key: _scale(value, divisor) if isinstance(value, dict) else value / divisor
            for key, value in values.items()}


def _indicators(compiled, summary):
    ranks = {r.id: r.rank for r in compiled.rule.rarities}
    return {
        "rarities": {key: int(any(count > 0 and ranks[other] >= rank
                                  for other, count in summary["rarity_counts"].items()))
                     for key, rank in ranks.items()},
        "characters": {key: int(value > 0) for key, value in summary["character_counts"].items()},
        "categories": {key: {name: int(value > 0) for name, value in categories.items()}
                       for key, categories in summary["category_counts"].items()},
    }


def _histogram(summary):
    return {key: _histogram(value) if isinstance(value, dict) else {}
            for key, value in summary.items()}


def _observe(distributions, summary):
    for key, frequency in distributions.items():
        values = summary[key]
        if isinstance(values, dict):
            _observe(frequency, values)
        else:
            label = str(values)
            frequency[label] = frequency.get(label, 0) + 1


def simulate_draws(
    compiled: CompiledPool, parameters: ExperimentParameters, *,
    record_sink: Callable[[ProcessEvent], None] | None = None,
    progress_callback: ProgressCallback | None = None,
    phase_callback: PhaseCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> SimulationResult:
    parameters = normalize_parameters(compiled, parameters)
    if record_sink is not None and not parameters.trace:
        raise ValueError("流式事件保存要求开启Trace")
    seed = secrets.randbits(64) if parameters.seed is None else parameters.seed
    parameters = replace(parameters, seed=seed)
    counts = event_counts(compiled.rule, parameters)
    start = initial_state(compiled, parameters)
    temporary = bonus_pool(compiled) if counts.bonus_draws else None
    temporary_start = initial_state(temporary, replace(parameters, initial_main_draws=0,
                                    initial_small_pity={}, initial_big_pity=replace(
                                        parameters.initial_big_pity, target_obtained=False, misses=0))) if temporary else None
    grant_target = next((c for p in compiled.pool.rarity_pools for c in p.characters
                         if c.id == compiled.targets["periodic_grant"]), None)
    groups = ("main", "bonus", "total", "grants", "acquisitions")
    kinds = {group: "draws" if group in ("main", "bonus", "total") else group for group in groups}
    totals = {group: _empty_summary(compiled, kinds[group]) for group in groups}
    indicators = {group: _indicators(compiled, totals[group]) for group in groups}
    distributions = {group: _histogram(totals[group]) for group in groups}
    records = []
    completed = 0
    units = counts.total_draws + counts.grant_triggers
    # ponytail: report about 1000 updates; tune cadence if clients need finer progress.
    cadence = max(1, units // 1000)
    check_cancelled(cancel_check)
    if phase_callback is not None:
        phase_callback("simulating", 0, units)
    if progress_callback is not None:
        progress_callback(0, units)
    rng = random.Random(seed)

    def report():
        nonlocal completed
        completed += 1
        if progress_callback is not None and (completed % cadence == 0 or completed == units):
            progress_callback(completed, units)
        check_cancelled(cancel_check)

    def emit(event):
        if record_sink is None:
            records.append(event)
        else:
            record_sink(event)

    for trial_index in range(1, parameters.trials + 1):
        check_cancelled(cancel_check)
        state = start
        summaries = {group: _empty_summary(compiled, kinds[group]) for group in groups}
        event_index = draw_index = bonus_index = 0
        for main_index in range(1, parameters.draws + 1):
            check_cancelled(cancel_check)
            main_completed = parameters.initial_main_draws + main_index
            before = state
            draw = draw_once(compiled, before, rng)
            state = draw.state_after
            draw_index += 1
            event_index += 1
            for group in ("main", "total"):
                _add_draw(summaries[group], draw.outcome)
            outcome = draw.outcome
            _add_acquisition(summaries["acquisitions"], outcome.rarity_id, outcome.character_id,
                             outcome.is_up, outcome.is_limited)
            if parameters.trace:
                emit(ProcessEvent(EVENT_FORMAT_VERSION, trial_index, event_index, "draw", main_completed,
                                  None, draw_index, "main", main_index, draw, before, state, None))
            report()
            if temporary is not None and main_completed == compiled.rule.bonus.at_main_draw:
                temporary_state = temporary_start
                for _ in range(compiled.rule.bonus.draws):
                    check_cancelled(cancel_check)
                    draw = draw_once(temporary, temporary_state, rng)
                    temporary_state = draw.state_after
                    draw_index += 1
                    bonus_index += 1
                    event_index += 1
                    for group in ("bonus", "total"):
                        _add_draw(summaries[group], draw.outcome)
                    outcome = draw.outcome
                    _add_acquisition(summaries["acquisitions"], outcome.rarity_id, outcome.character_id,
                                     outcome.is_up, outcome.is_limited)
                    if parameters.trace:
                        emit(ProcessEvent(EVENT_FORMAT_VERSION, trial_index, event_index, "draw", main_completed,
                                          "first_bonus", draw_index, "bonus", bonus_index, draw, state, state, None))
                    report()
            if compiled.rule.grant.enabled and main_completed % compiled.rule.grant.period == 0:
                check_cancelled(cancel_check)
                quantity = compiled.rule.grant.quantity
                event_index += 1
                summaries["grants"]["trigger_count"] += 1
                for group in ("grants", "acquisitions"):
                    _add_acquisition(summaries[group], grant_target.rarity_id, grant_target.id,
                                     grant_target.is_up, grant_target.is_limited, quantity)
                if parameters.trace:
                    grant = {"character_id": grant_target.id, "rarity_id": grant_target.rarity_id,
                             "character_name": grant_target.name, "is_up": grant_target.is_up,
                             "is_limited": grant_target.is_limited, "quantity": quantity,
                             "trigger_main_draw": main_completed}
                    emit(ProcessEvent(EVENT_FORMAT_VERSION, trial_index, event_index, "character_grant",
                                      main_completed, "periodic_grant", None, None, None, None, None, None, grant))
                report()
        for group in groups:
            check_cancelled(cancel_check)
            _merge(totals[group], summaries[group])
            _merge(indicators[group], _indicators(compiled, summaries[group]))
            _observe(distributions[group], summaries[group])
    summaries = {group: {**_scale(totals[group], parameters.trials),
                         "at_least_one": _scale(indicators[group], parameters.trials),
                         "distributions": distributions[group]} for group in groups}
    simulation = {"draws": {group: summaries[group] for group in ("main", "bonus", "total")},
                  "grants": summaries["grants"], "acquisitions": summaries["acquisitions"]}
    check_cancelled(cancel_check)
    return SimulationResult(seed, parameters, counts, simulation, None, parameters.trace,
                            counts.trace_events, tuple(records))


def simulate(
    compiled: CompiledPool, parameters: ExperimentParameters, *,
    record_sink: Callable[[ProcessEvent], None] | None = None,
    progress_callback: ProgressCallback | None = None,
    phase_callback: PhaseCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> SimulationResult:
    # The theory module reuses the aggregation helpers above; import after loading.
    from lottery_simulator.analysis import expected_simulation_results

    result = simulate_draws(compiled, parameters, record_sink=record_sink,
                            progress_callback=progress_callback, phase_callback=phase_callback,
                            cancel_check=cancel_check)
    check_cancelled(cancel_check)
    if phase_callback is not None:
        phase_callback("theory", None, None)
    check_cancelled(cancel_check)
    theoretical = expected_simulation_results(compiled, result.parameters, cancel_check=cancel_check)
    check_cancelled(cancel_check)
    return replace(result, theoretical=theoretical)
