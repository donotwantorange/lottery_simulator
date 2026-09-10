from dataclasses import dataclass
import random
import secrets

from lottery_simulator.analysis import expected_bonus_six_stars, expected_six_stars
from lottery_simulator.rules.base import (
    DrawState,
    LotteryRule,
    bonus_events_after_main_draw,
)


@dataclass(frozen=True, slots=True)
class DrawRecord:
    draw_index: int
    source: str
    source_index: int
    bonus_event: str | None
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
    bonus_draws: int
    total_draws: int
    count_distribution: dict[int, int]
    mean_main_six_stars: float
    mean_bonus_six_stars: float
    mean_six_stars: float
    at_least_one_rate: float
    observed_mean_interval: float | None
    theoretical_expected_main_count: float
    theoretical_expected_bonus_count: float
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
    total_main_six_stars = 0
    total_bonus_six_stars = 0
    interval_sum = 0
    completed_intervals = 0
    bonus_draws_per_trial = 0

    for trial in range(trials):
        state = initial_state
        main_draws_completed = initial_pity
        main_six_stars = 0
        bonus_six_stars = 0
        trial_bonus_draws = 0
        actual_draw_index = 0
        for main_draw_index in range(1, draws + 1):
            actual_draw_index += 1
            probability = rule.probability(state)
            if not 0.0 <= probability <= 1.0:
                raise ValueError("rule returned a probability outside [0, 1]")
            pity_position = state.misses_since_six_star + 1
            is_six_star = rng.random() < probability
            state_after = rule.advance(state, is_six_star)
            if is_six_star:
                main_six_stars += 1
                interval_sum += pity_position
                completed_intervals += 1
            if trials == 1:
                records.append(
                    DrawRecord(
                        actual_draw_index,
                        "main",
                        main_draw_index,
                        None,
                        pity_position,
                        probability,
                        is_six_star,
                        state_after,
                    )
                )
            state = state_after
            main_draws_completed += 1
            for event in bonus_events_after_main_draw(rule, main_draws_completed):
                for bonus_draw_index in range(1, event.draws + 1):
                    actual_draw_index += 1
                    trial_bonus_draws += 1
                    bonus_is_six_star = rng.random() < event.six_star_probability
                    bonus_six_stars += int(bonus_is_six_star)
                    if trials == 1:
                        records.append(
                            DrawRecord(
                                actual_draw_index,
                                "bonus",
                                bonus_draw_index,
                                event.name,
                                state.misses_since_six_star,
                                event.six_star_probability,
                                bonus_is_six_star,
                                state,
                            )
                        )
        if trial == 0:
            bonus_draws_per_trial = trial_bonus_draws
        six_stars = main_six_stars + bonus_six_stars
        total_main_six_stars += main_six_stars
        total_bonus_six_stars += bonus_six_stars
        total_six_stars += six_stars
        count_distribution[six_stars] = count_distribution.get(six_stars, 0) + 1

    theoretical_main = expected_six_stars(rule, draws, initial_pity)
    theoretical_bonus = expected_bonus_six_stars(rule, draws, initial_pity)

    return SimulationResult(
        rule_name=rule.name,
        draws=draws,
        trials=trials,
        seed=actual_seed,
        initial_pity=initial_pity,
        bonus_draws=bonus_draws_per_trial,
        total_draws=draws + bonus_draws_per_trial,
        count_distribution=count_distribution,
        mean_main_six_stars=total_main_six_stars / trials,
        mean_bonus_six_stars=total_bonus_six_stars / trials,
        mean_six_stars=total_six_stars / trials,
        at_least_one_rate=(trials - count_distribution.get(0, 0)) / trials,
        observed_mean_interval=(
            interval_sum / completed_intervals if completed_intervals else None
        ),
        theoretical_expected_main_count=theoretical_main,
        theoretical_expected_bonus_count=theoretical_bonus,
        theoretical_expected_count=theoretical_main + theoretical_bonus,
        records=tuple(records),
    )
