"""Finite-state theoretical expectations for the dynamic lottery engine."""

from collections import defaultdict
from dataclasses import replace
import math

from lottery_simulator.control import CancelCheck, ProgressCallback, check_cancelled
from lottery_simulator.engine import (
    _empty_summary, _finite_add, _indicators, _merge, bonus_pool,
)
from lottery_simulator.events import event_counts
from lottery_simulator.rules.definitions import ExperimentParameters
from lottery_simulator.rules.runtime import (
    CompiledPool, DrawState, initial_state, normalize_parameters, pity_status,
    transition_branches,
)

# Exact ceilings fail loudly; exceeding them never returns a partial estimate.
_MAX_STATES = 200_000
_MAX_BRANCHES = 2_000_000


def _finite(value, label):
    if not math.isfinite(value):
        raise ValueError(f"理论{label}出现非有限数值")
    return value


def _probability_value(value, label):
    value = _finite(value, label)
    if not -1e-10 <= value <= 1 + 1e-10:
        raise ValueError(f"理论{label}超出概率范围")
    return min(1.0, max(0.0, value))


def _metrics(compiled):
    ranks = {r.id: r.rank for r in compiled.rule.rarities}
    empty = _empty_summary(compiled, "draws")
    metrics = []
    for rarity_id, rank in ranks.items():
        metrics.append(("rarities", rarity_id, lambda event, rid=rarity_id, rank=rank:
                        ranks[event[0]] >= rank))
    for character_id in empty["character_counts"]:
        metrics.append(("characters", character_id,
                        lambda event, cid=character_id: event[1] == cid))
    for rarity_id, categories in empty["category_counts"].items():
        for category in categories:
            metrics.append(("categories", (rarity_id, category),
                            lambda event, rid=rarity_id, cat=category:
                            event[0] == rid and event[2] == cat))
    return metrics


def _state_caps(compiled):
    """Return only soft-only caps whose floating-point probability is saturated."""
    caps = {}
    for rarity in compiled.rule.rarities:
        if not rarity.soft_enabled or rarity.hard_enabled:
            continue
        try:
            ratio = (1 - rarity.base_probability) / rarity.soft_step
        except OverflowError:
            continue
        if math.isfinite(ratio):
            cap = max(rarity.soft_start - 1,
                      rarity.soft_start + math.ceil(ratio) - 2)
            steps = cap - rarity.soft_start + 2
            try:
                saturated = min(1.0, rarity.base_probability + rarity.soft_step * steps) >= 1.0
            except OverflowError:
                saturated = False
            if saturated:
                caps[rarity.id] = cap
    return caps


def _cap_state(state, caps):
    """Theory-only canonical key; never passed to input-history validation or Trace."""
    small = dict(state.small_pity)
    for rarity_id, misses in tuple(small.items()):
        if rarity_id in caps:
            small[rarity_id] = min(misses, caps[rarity_id])
    return DrawState(small, state.big_misses, state.big_active)


def _aggregate_transitions(compiled, branches, metrics, caps, cancel_check):
    """Keep outcome marginals while grouping exact transitions by canonical state."""
    rosters = {pool.rarity_id: {character.id: character for character in pool.characters}
               for pool in compiled.pool.rarity_pools}
    groups = {}
    for index, (rarity_id, character_id, probability, after) in enumerate(branches):
        if index % 64 == 0:
            check_cancelled(cancel_check)
        character = rosters.get(rarity_id, {}).get(character_id)
        category = ("unnamed" if character is None else "up" if character.is_up else
                    "other_limited" if character.is_limited else "standard")
        outcome = (rarity_id, character_id, category)
        group = groups.setdefault(_cap_state(after, caps), {})
        parts = group.setdefault(outcome, [])
        parts.append(probability)

    aggregated = {}
    for index, (state, parts_by_outcome) in enumerate(groups.items()):
        if index % 64 == 0:
            check_cancelled(cancel_check)
        outcomes = {}
        for outcome_index, (outcome, parts) in enumerate(parts_by_outcome.items()):
            if outcome_index % 64 == 0:
                check_cancelled(cancel_check)
            outcomes[outcome] = math.fsum(parts)
        rarity_mass, character_mass, category_mass = defaultdict(list), defaultdict(list), defaultdict(list)
        for outcome_index, ((rarity_id, character_id, category), probability) in enumerate(outcomes.items()):
            if outcome_index % 64 == 0:
                check_cancelled(cancel_check)
            rarity_mass[rarity_id].append(probability)
            category_mass[(rarity_id, category)].append(probability)
            if character_id is not None:
                character_mass[character_id].append(probability)
        misses = []
        for _, _, predicate in metrics:
            def missed_terms():
                for outcome_index, (outcome, probability) in enumerate(outcomes.items()):
                    if outcome_index % 64 == 0:
                        check_cancelled(cancel_check)
                    if not predicate(outcome):
                        yield probability
            misses.append(_probability_value(math.fsum(missed_terms()), "未命中转移"))
        probability = _probability_value(math.fsum(outcomes.values()), "状态转移")
        aggregate = {
            "probability": probability,
            "rarities": {key: math.fsum(parts) for key, parts in rarity_mass.items()},
            "characters": {key: math.fsum(parts) for key, parts in character_mass.items()},
            "categories": {key: math.fsum(parts) for key, parts in category_mass.items()},
            "misses": misses,
        }
        aggregated[state] = aggregate
    return aggregated


def _run_pool(compiled: CompiledPool, draws: int, start: DrawState, *,
              cancel_check: CancelCheck | None = None, progress_callback: ProgressCallback | None = None):
    summary = _empty_summary(compiled, "draws")
    metrics = _metrics(compiled)
    caps = _state_caps(compiled)
    # Each state carries ordinary probability and one no-hit mass per indicator.
    masses = {_cap_state(start, caps): (1.0, *((1.0,) * len(metrics)))}
    transition_cache = {}
    if len(masses) > _MAX_STATES:
        raise ValueError("理论初始状态数超过资源上限")
    branch_count = 0
    for pull in range(draws):
        check_cancelled(cancel_check)
        following = defaultdict(lambda: [0.0] * (len(metrics) + 1))
        for state_index, (state, values) in enumerate(masses.items()):
            if state_index % 256 == 0:
                check_cancelled(cancel_check)
            status = pity_status(compiled, state)
            transitions = transition_cache.get(state)
            if transitions is None:
                if len(transition_cache) >= _MAX_STATES:
                    raise ValueError("理论缓存状态数超过资源上限")
                branches = transition_branches(compiled, state)
                transitions = transition_cache[state] = _aggregate_transitions(
                    compiled, branches, metrics, caps, cancel_check)
            branch_count += len(transitions)
            if branch_count > _MAX_BRANCHES:
                raise ValueError("理论分支数超过资源上限")
            for pity_id in status["soft_active"]:
                summary["pity_triggers"]["soft"][pity_id] = _finite_add(
                    summary["pity_triggers"]["soft"][pity_id], values[0])
            for pity_id in status["hard_active"]:
                summary["pity_triggers"]["hard"][pity_id] = _finite_add(
                    summary["pity_triggers"]["hard"][pity_id], values[0])
            if status["big_forced"]:
                summary["pity_triggers"]["big"] = _finite_add(
                    summary["pity_triggers"]["big"], values[0])
            for transition_index, (next_state, transition) in enumerate(transitions.items()):
                if transition_index % 64 == 0:
                    check_cancelled(cancel_check)
                probability = transition["probability"]
                joint = _finite(values[0] * probability, "状态质量")
                if joint == 0:
                    continue
                for rarity_id, conditional in transition["rarities"].items():
                    count = _finite(values[0] * conditional, "稀有度期望")
                    summary["rarity_counts"][rarity_id] = _finite_add(
                        summary["rarity_counts"][rarity_id], count)
                    for reward in compiled.pool.rewards:
                        amount = reward.amounts.get(rarity_id, 0.0)
                        summary["reward_totals"][reward.id] = _finite_add(
                            summary["reward_totals"][reward.id], count * amount)
                for character_id, conditional in transition["characters"].items():
                    summary["character_counts"][character_id] = _finite_add(
                        summary["character_counts"][character_id], values[0] * conditional)
                for (rarity_id, category), conditional in transition["categories"].items():
                    summary["category_counts"][rarity_id][category] = _finite_add(
                        summary["category_counts"][rarity_id][category], values[0] * conditional)
                if next_state not in following and len(following) >= _MAX_STATES:
                    raise ValueError("理论可达状态数超过资源上限")
                dest = following[next_state]
                dest[0] = _finite(dest[0] + joint, "状态质量")
                for index, no_hit_probability in enumerate(transition["misses"], start=1):
                    no_hit = _finite(values[index] * no_hit_probability, "未命中质量")
                    dest[index] = _finite(dest[index] + no_hit, "未命中质量")
        total_mass = math.fsum(values[0] for values in following.values())
        if not math.isfinite(total_mass) or abs(total_mass - 1.0) > 1e-10:
            raise ValueError("理论状态质量未守恒")
        masses = {state: tuple(values) for state, values in following.items()}
        summary["draw_count"] += 1
        if progress_callback is not None:
            progress_callback(pull + 1, draws)
    no_hit = [math.fsum(values[index] for values in masses.values())
              for index in range(1, len(metrics) + 1)]
    indicators = {"rarities": {}, "characters": {}, "categories":
                  {key: {} for key in summary["category_counts"]}}
    for (group, key, _), missed in zip(metrics, no_hit):
        value = _probability_value(1.0 - missed, "至少一次概率")
        if group == "categories":
            rarity_id, category = key
            indicators[group][rarity_id][category] = value
        else:
            indicators[group][key] = value
    for rarity_id in indicators["categories"]:
        for category in summary["category_counts"][rarity_id]:
            indicators["categories"][rarity_id].setdefault(category, 0.0)
    summary["at_least_one"] = indicators
    return summary


def _acquisition_from_draws(compiled, main, bonus):
    result = _empty_summary(compiled, "acquisitions")
    for source in (main, bonus):
        for rarity_id, count in source["rarity_counts"].items():
            result["rarity_counts"][rarity_id] = _finite_add(result["rarity_counts"][rarity_id], count)
        for character_id, count in source["character_counts"].items():
            result["character_counts"][character_id] = _finite_add(result["character_counts"][character_id], count)
        for rarity_id, categories in source["category_counts"].items():
            for category, count in categories.items():
                result["category_counts"][rarity_id][category] = _finite_add(
                    result["category_counts"][rarity_id][category], count)
    result["character_count"] = math.fsum(result["character_counts"].values())
    return result


def expected_simulation_results(
    compiled: CompiledPool, parameters: ExperimentParameters, *,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    parameters = normalize_parameters(compiled, parameters)
    counts = event_counts(compiled.rule, parameters)
    main_start = initial_state(compiled, parameters)
    total_steps = parameters.draws + (compiled.rule.bonus.draws if counts.bonus_draws else 0)
    if progress_callback is not None:
        progress_callback(0, total_steps)
    main = _run_pool(compiled, parameters.draws, main_start, cancel_check=cancel_check,
                     progress_callback=(lambda done, _: progress_callback(done, total_steps))
                     if progress_callback is not None else None)
    bonus = _empty_summary(compiled, "draws")
    bonus["at_least_one"] = {"rarities": {r: 0.0 for r in bonus["rarity_counts"]},
                             "characters": {c: 0.0 for c in bonus["character_counts"]},
                             "categories": {r: {k: 0.0 for k in v}
                                            for r, v in bonus["category_counts"].items()}}
    if counts.bonus_draws:
        temporary = bonus_pool(compiled)
        bonus = _run_pool(temporary, compiled.rule.bonus.draws,
                          initial_state(temporary, replace(parameters, initial_main_draws=0,
                              initial_small_pity={}, initial_big_pity=replace(
                                  parameters.initial_big_pity, target_obtained=False, misses=0))),
                          cancel_check=cancel_check,
                          progress_callback=(lambda done, _: progress_callback(parameters.draws + done, total_steps))
                          if progress_callback is not None else None)
    total = _empty_summary(compiled, "draws")
    for source in (main, bonus):
        for key in ("rarity_counts", "character_counts", "category_counts", "reward_totals", "pity_triggers"):
            _merge(total[key], source[key])
        total["draw_count"] += source["draw_count"]
    total["at_least_one"] = _combine_indicators(main["at_least_one"], bonus["at_least_one"])
    acquisitions = _acquisition_from_draws(compiled, main, bonus)
    grants = _empty_summary(compiled, "grants")
    grants["trigger_count"] = counts.grant_triggers // parameters.trials
    if counts.grant_triggers:
        target = next(c for pool in compiled.pool.rarity_pools for c in pool.characters
                      if c.id == compiled.targets["periodic_grant"])
        quantity = grants["trigger_count"] * compiled.rule.grant.quantity
        for group in (grants, acquisitions):
            _add_expected_character(group, target.rarity_id, target.id, target.is_up,
                                    target.is_limited, quantity)
    grants["at_least_one"] = _indicators(compiled, grants)
    acquisitions["at_least_one"] = _combine_indicators(
        total["at_least_one"], grants["at_least_one"])
    return {"draws": {"main": main, "bonus": bonus, "total": total},
            "grants": grants, "acquisitions": acquisitions}


def _add_expected_character(summary, rarity_id, character_id, is_up, is_limited, quantity):
    summary["rarity_counts"][rarity_id] = _finite_add(summary["rarity_counts"][rarity_id], quantity)
    category = "up" if is_up else "other_limited" if is_limited else "standard"
    summary["category_counts"][rarity_id][category] = _finite_add(
        summary["category_counts"][rarity_id][category], quantity)
    summary["character_counts"][character_id] = _finite_add(
        summary["character_counts"][character_id], quantity)
    if "character_count" in summary:
        summary["character_count"] = _finite_add(summary["character_count"], quantity)


def _combine_indicators(first, second):
    def combine(left, right):
        if isinstance(left, dict):
            return {key: combine(value, right[key]) for key, value in left.items()}
        return _probability_value(1 - (1 - left) * (1 - right), "至少一次概率")
    return combine(first, second)
