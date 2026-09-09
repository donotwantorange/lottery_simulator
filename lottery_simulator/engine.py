from dataclasses import dataclass
import random
import secrets

from lottery_simulator.analysis import expected_six_stars
from lottery_simulator.rules.base import DrawState, LotteryRule


@dataclass(frozen=True, slots=True)
class DrawRecord:
    draw_index: int
    pity_position: int
    probability: float
    is_six_star: bool
    state_after: DrawState


@dataclass(frozen=True, slots=True)
class SimulationResult:
    rule_name: str
    draws: int
    trials: int
    seed: int
    initial_pity: int
    count_distribution: dict[int, int]
    mean_six_stars: float
    at_least_one_rate: float
    observed_mean_interval: float | None
    theoretical_expected_count: float
    records: tuple[DrawRecord, ...]


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def simulate(
    rule: LotteryRule,
    draws: int,
    trials: int = 1,
    seed: int | None = None,
    initial_pity: int = 0,
) -> SimulationResult:
    _positive_integer(draws, "draws")
    _positive_integer(trials, "trials")
    initial_state = DrawState(initial_pity)
    rule.probability(initial_state)
    actual_seed = secrets.randbits(64) if seed is None else seed
    if isinstance(actual_seed, bool) or not isinstance(actual_seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(actual_seed)
    count_distribution: dict[int, int] = {}
    records: list[DrawRecord] = []
    total_six_stars = 0
    interval_sum = 0
    completed_intervals = 0

    for _trial in range(trials):
        state = initial_state
        six_stars = 0
        for draw_index in range(1, draws + 1):
            probability = rule.probability(state)
            if not 0.0 <= probability <= 1.0:
                raise ValueError("rule returned a probability outside [0, 1]")
            pity_position = state.misses_since_six_star + 1
            is_six_star = rng.random() < probability
            state_after = rule.advance(state, is_six_star)
            if is_six_star:
                six_stars += 1
                interval_sum += pity_position
                completed_intervals += 1
            if trials == 1:
                records.append(
                    DrawRecord(
                        draw_index, pity_position, probability, is_six_star, state_after
                    )
                )
            state = state_after
        total_six_stars += six_stars
        count_distribution[six_stars] = count_distribution.get(six_stars, 0) + 1

    return SimulationResult(
        rule_name=rule.name,
        draws=draws,
        trials=trials,
        seed=actual_seed,
        initial_pity=initial_pity,
        count_distribution=count_distribution,
        mean_six_stars=total_six_stars / trials,
        at_least_one_rate=(trials - count_distribution.get(0, 0)) / trials,
        observed_mean_interval=(
            interval_sum / completed_intervals if completed_intervals else None
        ),
        theoretical_expected_count=expected_six_stars(rule, draws, initial_pity),
        records=tuple(records),
    )
