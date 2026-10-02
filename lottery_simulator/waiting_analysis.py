"""First-hit waiting distribution for future main-pool draws."""

import math

from lottery_simulator.control import check_cancelled
from lottery_simulator.rules.runtime import (
    DrawState, initial_state, normalize_parameters, rarity_probabilities,
)


_WINDOW = 100
_MAX_STEPS = 100_000
_QUANTILES = (0.90, 0.95, 0.99)


def _payload(target_id, state, *, kind, maximum, window, tail_status, tail_value,
             mean_status, mean_value, quantiles, status, hit_probability=None,
             tail_log_value=None, message=None):
    result = {
        "target_rarity_id": target_id,
        "source": "main",
        "unit": "additional_main_draws",
        "initial_state": state.to_dict(),
        "distribution": {
            "kind": kind,
            "support": {"minimum": 1, "maximum": maximum},
            "window": {"through_draws": len(window), "probabilities": window},
            "tail_mass": {"status": tail_status, "value": tail_value,
                          **({"log_value": tail_log_value} if tail_log_value is not None else {})},
        },
        "mean": {"status": mean_status, "value": mean_value},
        "hit_probability": hit_probability or (
            {"status": "finite", "value": 1.0} if status == "finite" else
            {"status": "finite", "value": 0.0} if status == "unreachable" else
            {"status": "incomplete", "value": None}),
        "quantiles": quantiles,
        "long_run_rate": {"status": "not_applicable", "value": None},
        "status": status,
    }
    if message:
        result["message"] = message
    return result


def _state_probability(compiled, state, target_rank):
    # Only the query tier and higher can affect the probability of a query hit.
    probability = math.fsum(
        value for rarity_id, value in rarity_probabilities(compiled, state).items()
        if next(r.rank for r in compiled.rule.rarities if r.id == rarity_id) >= target_rank
    )
    if math.isfinite(probability) and 1 < probability <= 1 + 1e-12:
        probability = 1.0
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ArithmeticError("命中概率超出有限数值范围")
    return probability


def _project_miss(compiled, state, target_rank):
    # Lower-tier state is intentionally zeroed only in this probability projection.
    small = dict(state.small_pity)
    projected = {
        rarity.id: small.get(rarity.id, 0) + 1 if rarity.rank >= target_rank else 0
        for rarity in compiled.rule.rarities
        if rarity.soft_enabled or rarity.hard_enabled
    }
    big_misses = state.big_misses + 1 if state.big_active else 0
    return DrawState(projected, big_misses, state.big_active)


def _project_initial(compiled, state, target_rank):
    small = dict(state.small_pity)
    projected = {
        rarity.id: small.get(rarity.id, 0) if rarity.rank >= target_rank else 0
        for rarity in compiled.rule.rarities
        if rarity.soft_enabled or rarity.hard_enabled
    }
    return DrawState(projected, state.big_misses, state.big_active)


def _guaranteed_bound(compiled, state, target_rank):
    candidates = []
    small = dict(state.small_pity)
    for rarity in compiled.rule.rarities:
        if rarity.rank < target_rank:
            continue
        misses = small.get(rarity.id, 0)
        if rarity.hard_enabled:
            candidates.append(rarity.hard_pity - misses)
        if rarity.soft_enabled:
            try:
                increments = math.ceil((1.0 - rarity.base_probability) / rarity.soft_step)
            except (OverflowError, ZeroDivisionError):
                continue
            try:
                saturated = rarity.base_probability + rarity.soft_step * increments >= 1.0
            except OverflowError:
                saturated = True
            if not saturated:
                increments += 1
            # On the nth next draw, projected misses are misses+n-1.
            candidates.append(max(1, increments - misses + rarity.soft_start - 1))
    policy = compiled.rule.big_pity
    if state.big_active and policy.enabled:
        candidates.append(policy.hard_pity - state.big_misses)
    return min(candidates, default=None)


def _empty_quantiles(status):
    return {str(level): {"status": status, "value": None} for level in _QUANTILES}


def _incomplete(target_id, state, window, tail, maximum=None, message="分析超过资源或数值范围，未完成"):
    return _payload(
        target_id, state, kind="finite" if maximum is not None else "windowed",
        maximum=maximum, window=window, tail_status="remaining", tail_value=tail,
        mean_status="incomplete", mean_value=None,
        quantiles=_empty_quantiles("incomplete"), status="incomplete", message=message,
    )


def waiting_time_stats(compiled, parameters, target_rarity_id=None, *, cancel_check=None):
    """Return time to first future main draw at or above the requested rarity."""
    check_cancelled(cancel_check)
    parameters = normalize_parameters(compiled, parameters)
    ordered = sorted(compiled.rule.rarities, key=lambda item: item.rank)
    if target_rarity_id is None:
        target_rarity_id = ordered[-1].id
    target = next((rarity for rarity in ordered if rarity.id == target_rarity_id), None)
    if target is None:
        raise ValueError("等待分析目标稀有度无效")
    real_state = initial_state(compiled, parameters)
    projected = _project_initial(compiled, real_state, target.rank)
    try:
        q = _state_probability(compiled, projected, target.rank)
    except (ArithmeticError, OverflowError, ValueError) as exc:
        return _incomplete(target.id, real_state, [], 1.0, message=f"命中概率数值无效：{exc}")
    bound = _guaranteed_bound(compiled, real_state, target.rank)
    if q == 1:
        values = [{"draws": 1, "probability": 1.0}]
        quantiles = {str(level): {"status": "finite", "value": 1} for level in _QUANTILES}
        return _payload(target.id, real_state, kind="finite", maximum=1,
                        window=values, tail_status="zero", tail_value=0.0,
                        mean_status="finite", mean_value=1.0,
                        quantiles=quantiles, status="finite",
                        hit_probability={"status": "finite", "value": 1.0})

    relevant = any(r.rank >= target.rank and (r.soft_enabled or r.hard_enabled)
                   for r in ordered) or real_state.big_active
    if not relevant:
        if q == 0:
            return _payload(target.id, real_state, kind="geometric", maximum=None,
                            window=[], tail_status="remaining", tail_value=1.0,
                            mean_status="infinite", mean_value=None,
                            quantiles=_empty_quantiles("unreachable"), status="unreachable",
                            hit_probability={"status": "finite", "value": 0.0})
        try:
            mean = 1.0 / q
            if not math.isfinite(mean):
                return _incomplete(target.id, real_state, [], 1.0,
                                   message="几何分布均值超出可表示数值范围")
            log_tail = math.log1p(-q)
            probs = []
            for n in range(1, _WINDOW + 1):
                check_cancelled(cancel_check)
                p = q * math.exp((n - 1) * log_tail)
                probs.append({"draws": n, "probability": p})
            log_remaining = _WINDOW * log_tail
            remaining = math.exp(log_remaining)
            tail_status = "underflow" if remaining == 0.0 and log_remaining != -math.inf else "remaining"
            quantiles = {}
            for level in _QUANTILES:
                n = math.ceil(math.log1p(-level) / log_tail)
                quantiles[str(level)] = {"status": "finite", "value": n}
            return _payload(target.id, real_state, kind="geometric", maximum=None,
                            window=probs, tail_status=tail_status,
                            tail_value=None if tail_status == "underflow" else remaining,
                            mean_status="finite", mean_value=mean,
                            quantiles=quantiles, status="finite",
                            hit_probability={"status": "finite", "value": 1.0},
                            tail_log_value=log_remaining if tail_status == "underflow" else None)
        except (OverflowError, ValueError):
            return _incomplete(target.id, real_state, [], 1.0,
                               message="几何分布统计超出可表示数值范围")

    if bound is None:
        return _incomplete(target.id, real_state, [], 1.0, message="无法证明有限必达边界")
    if bound < 1:
        return _incomplete(target.id, real_state, [], 1.0, bound,
                           message="推导出的必达边界无效")
    if bound > _MAX_STEPS:
        return _incomplete(target.id, real_state, [], 1.0, bound,
                           message=f"有限必达边界{bound}超过计算上限{_MAX_STEPS}")

    window = []
    survival = 1.0
    mean = 0.0
    cumulative = 0.0
    window_tail = 1.0
    quantile_values = {level: None for level in _QUANTILES}
    support_bound = bound
    for draw in range(1, bound + 1):
        check_cancelled(cancel_check)
        try:
            q = _state_probability(compiled, projected, target.rank)
        except (ArithmeticError, OverflowError, ValueError) as exc:
            return _incomplete(target.id, real_state, window, survival, bound,
                               message=f"第{draw}步命中概率无效：{exc}")
        hit = survival * q
        if not math.isfinite(hit):
            return _incomplete(target.id, real_state, window, survival, bound)
        if draw <= _WINDOW:
            window.append({"draws": draw, "probability": hit})
        mean += survival
        cumulative = math.fsum((cumulative, hit))
        for level in _QUANTILES:
            if quantile_values[level] is None and cumulative >= level:
                quantile_values[level] = draw
        if draw == min(bound, _WINDOW):
            window_tail = survival * (1.0 - q)
        if q == 1:
            support_bound = draw
            survival = 0.0
            break
        previous_survival = survival
        survival *= 1.0 - q
        if survival == 0 and previous_survival > 0 and q < 1:
            return _incomplete(target.id, real_state, window, None, bound,
                               message=f"第{draw}步未命中尾部质量发生数值下溢")
        if q < 1:
            try:
                projected = _project_miss(compiled, projected, target.rank)
            except (ValueError, OverflowError):
                return _incomplete(target.id, real_state, window, survival, bound)
    if not math.isfinite(mean) or survival > 1e-12:
        return _incomplete(target.id, real_state, window, survival, bound,
                           message="有限保证边界后仍有未归零尾部质量")
    quantiles = {
        str(level): {"status": "finite", "value": quantile_values[level]}
        if quantile_values[level] is not None else {"status": "incomplete", "value": None}
        for level in _QUANTILES
    }
    if any(quantile_values[level] is None for level in _QUANTILES):
        return _incomplete(target.id, real_state, window, survival, bound,
                           message="等待分位数的累计概率未达到所需水平")
    shown_tail = support_bound > _WINDOW
    return _payload(target.id, real_state, kind="finite", maximum=support_bound,
                    window=window,
                    tail_status="remaining" if shown_tail and window_tail > 0 else "zero",
                    tail_value=window_tail if shown_tail and window_tail > 0 else 0.0,
                    mean_status="finite", mean_value=mean,
                    quantiles=quantiles, status="finite",
                    hit_probability={"status": "finite", "value": 1.0})
