from dataclasses import dataclass
from math import sqrt

from lottery_simulator.rules.base import DrawState, LotteryRule


@dataclass(frozen=True, slots=True)
class DistributionStats:
    probabilities: tuple[float, ...]
    mean: float
    variance: float
    standard_deviation: float
    median: int
    mode: int
    quantiles: dict[float, int]
    long_run_rate: float


def _probability(rule: LotteryRule, state: DrawState) -> float:
    probability = rule.probability(state)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("rule returned a probability outside [0, 1]")
    return probability


def _state(initial_pity: int, rule: LotteryRule) -> DrawState:
    state = DrawState(initial_pity)
    _probability(rule, state)
    return state


def waiting_time_distribution(
    rule: LotteryRule, initial_pity: int = 0
) -> tuple[float, ...]:
    state = _state(initial_pity, rule)
    survival = 1.0
    probabilities: list[float] = []
    for _ in range(rule.max_pity - initial_pity):
        probability = _probability(rule, state)
        probabilities.append(survival * probability)
        survival *= 1.0 - probability
        if probability == 1.0:
            break
        state = rule.advance(state, False)
    if abs(sum(probabilities) - 1.0) > 1e-12:
        raise ValueError("rule does not produce a complete waiting-time distribution")
    return tuple(probabilities)


def _quantile(probabilities: tuple[float, ...], level: float) -> int:
    cumulative = 0.0
    for pull, probability in enumerate(probabilities, start=1):
        cumulative += probability
        if cumulative >= level:
            return pull
    raise ValueError("incomplete probability distribution")


def distribution_stats(
    rule: LotteryRule, initial_pity: int = 0
) -> DistributionStats:
    probabilities = waiting_time_distribution(rule, initial_pity)
    mean = sum(pull * p for pull, p in enumerate(probabilities, start=1))
    second = sum(pull * pull * p for pull, p in enumerate(probabilities, start=1))
    variance = second - mean * mean
    return DistributionStats(
        probabilities=probabilities,
        mean=mean,
        variance=variance,
        standard_deviation=sqrt(variance),
        median=_quantile(probabilities, 0.5),
        mode=max(range(1, len(probabilities) + 1), key=lambda n: probabilities[n - 1]),
        quantiles={level: _quantile(probabilities, level) for level in (0.90, 0.95, 0.99)},
        long_run_rate=1.0 / mean if initial_pity == 0 else float("nan"),
    )


def expected_six_stars(
    rule: LotteryRule, draws: int, initial_pity: int = 0
) -> float:
    if isinstance(draws, bool) or not isinstance(draws, int) or draws <= 0:
        raise ValueError("draws must be a positive integer")
    initial = _state(initial_pity, rule)
    states = {initial: 1.0}
    expected = 0.0
    for _ in range(draws):
        next_states: dict[DrawState, float] = {}
        for state, mass in states.items():
            probability = _probability(rule, state)
            success_mass = mass * probability
            expected += success_mass
            success_state = rule.advance(state, True)
            next_states[success_state] = (
                next_states.get(success_state, 0.0) + success_mass
            )
            if probability < 1.0:
                miss_state = rule.advance(state, False)
                next_states[miss_state] = (
                    next_states.get(miss_state, 0.0) + mass * (1.0 - probability)
                )
        states = next_states
    return expected
