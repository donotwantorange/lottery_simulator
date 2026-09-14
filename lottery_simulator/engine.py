from dataclasses import dataclass
from collections.abc import Callable
import random
import secrets

from lottery_simulator.analysis import expected_bonus_six_stars, expected_six_stars
from lottery_simulator.rules.base import (
    DrawState,
    LotteryRule,
    RarityProbabilities,
    bonus_events_after_main_draw,
)


@dataclass(frozen=True, slots=True)
class DrawOutcome:
    rarity: int
    six_star_character: str | None
    is_up: bool
    is_limited: bool
    rewards: dict[str, float]
    five_star_pity_triggered: bool
    six_star_hard_pity_triggered: bool


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
    main_draws_completed: int | None = None
    source_state_before: DrawState | None = None
    source_state_after: DrawState | None = None

    def __post_init__(self) -> None:
        if self.main_draws_completed is None:
            object.__setattr__(self, "main_draws_completed", self.pity_position)


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
    initial_main_draws: int | None = None
    final_main_draws: int | None = None

    def __post_init__(self) -> None:
        defaults = {
            "initial_main_draws": self.initial_pity,
            "final_main_draws": self.initial_pity + self.draws,
        }
        for name, value in defaults.items():
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


class SimulationCancelled(RuntimeError):
    pass


def draw_once(
    rule: LotteryRule,
    state: DrawState,
    rng: random.Random,
) -> tuple[DrawOutcome, DrawState, RarityProbabilities]:
    probabilities = rule.rarity_probabilities(state)
    roll = rng.random()
    rarity = (
        6
        if roll < probabilities.six_star
        else 5
        if roll < probabilities.six_star + probabilities.five_star
        else 4
    )
    character = rule.pick_six_star(rng.random()) if rarity == 6 else None
    outcome = DrawOutcome(
        rarity=rarity,
        six_star_character=character.name if character else None,
        is_up=bool(character and character.is_up),
        is_limited=bool(character and character.is_limited),
        rewards=rule.config.rewards_for(rarity),
        five_star_pity_triggered=rule.five_star_pity_active(state),
        six_star_hard_pity_triggered=(
            state.misses_since_six_star == rule.max_pity - 1
        ),
    )
    return outcome, rule.advance_rarity(state, rarity), probabilities


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def simulate(
    rule: LotteryRule,
    draws: int,
    trials: int = 1,
    seed: int | None = None,
    initial_pity: int = 0,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    progress_interval: int = 1000,
    collect_records: bool | None = None,
    initial_five_star_pity: int = 0,
) -> SimulationResult:
    _positive_integer(draws, "draws")
    _positive_integer(trials, "trials")
    _positive_integer(progress_interval, "progress_interval")
    if collect_records is None:
        collect_records = trials == 1
    elif not isinstance(collect_records, bool):
        raise ValueError("collect_records must be a boolean or None")
    elif collect_records and trials != 1:
        raise ValueError("collect_records requires trials=1")
    initial_state = DrawState(initial_pity, initial_five_star_pity)
    rule.probability(initial_state)
    total_units = draws * trials
    completed_units = 0
    if progress_callback is not None:
        progress_callback(completed_units, total_units)
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
            if cancel_check is not None and cancel_check():
                raise SimulationCancelled("simulation cancelled")
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
            if collect_records:
                records.append(
                    DrawRecord(
                        draw_index=actual_draw_index,
                        pity_position=pity_position,
                        probability=probability,
                        is_six_star=is_six_star,
                        state_after=state_after,
                        source="main",
                        source_index=main_draw_index,
                        bonus_event=None,
                        main_draws_completed=main_draws_completed + 1,
                        source_state_before=state,
                        source_state_after=state_after,
                    )
                )
            state = state_after
            main_draws_completed += 1
            completed_units += 1
            if (
                progress_callback is not None
                and (completed_units % progress_interval == 0 or completed_units == total_units)
            ):
                progress_callback(completed_units, total_units)
            for event in bonus_events_after_main_draw(rule, main_draws_completed):
                temporary_rule = rule.for_bonus(event)
                temporary_state = DrawState()
                for bonus_draw_index in range(1, event.draws + 1):
                    actual_draw_index += 1
                    trial_bonus_draws += 1
                    source_state_before = temporary_state
                    outcome, temporary_state, probabilities = draw_once(
                        temporary_rule, temporary_state, rng
                    )
                    bonus_is_six_star = outcome.rarity == 6
                    bonus_six_stars += int(bonus_is_six_star)
                    if collect_records:
                        records.append(
                            DrawRecord(
                                draw_index=actual_draw_index,
                                pity_position=state.misses_since_six_star,
                                probability=probabilities.six_star,
                                is_six_star=bonus_is_six_star,
                                state_after=state,
                                source="bonus",
                                source_index=bonus_draw_index,
                                bonus_event=event.name,
                                main_draws_completed=main_draws_completed,
                                source_state_before=source_state_before,
                                source_state_after=temporary_state,
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
        initial_main_draws=initial_pity,
        final_main_draws=initial_pity + draws,
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
