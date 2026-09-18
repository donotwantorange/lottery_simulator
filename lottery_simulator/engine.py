from dataclasses import dataclass, field
from collections.abc import Callable
import random
import secrets

from lottery_simulator.analysis import expected_simulation_results
from lottery_simulator.formats import RECORD_FORMAT_VERSION
from lottery_simulator.probability import sample_distribution
from lottery_simulator.rules.base import (
    DrawState,
    LotteryRule,
    RarityProbabilities,
    bonus_events_after_main_draw,
)


@dataclass(frozen=True, slots=True)
class DrawOutcome:
    rarity: int
    character_name: str | None
    is_up: bool
    is_limited: bool
    rewards: dict[str, float]
    five_star_pity_triggered: bool
    six_star_hard_pity_triggered: bool


@dataclass(frozen=True, slots=True)
class DrawResult:
    outcome: DrawOutcome
    probabilities: RarityProbabilities
    state_before: DrawState
    state_after: DrawState


@dataclass(frozen=True, slots=True)
class DrawRecord:
    record_format_version: int
    draw_index: int
    source: str
    source_index: int
    bonus_event: str | None
    main_draws_completed: int
    draw_result: DrawResult
    main_state_before: DrawState
    main_state_after: DrawState


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
    source_summaries: dict[str, dict] = field(default_factory=dict)
    source_distributions: dict[str, dict] = field(default_factory=dict)
    at_least_one_rates: dict[str, dict[str, float]] = field(default_factory=dict)
    pool_config: dict = field(default_factory=dict)
    initial_five_star_pity: int = 0
    theoretical_source_summaries: dict[str, dict] = field(default_factory=dict)

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


def _empty_counts(config):
    return {
        "rarities": {"4": 0, "5": 0, "6": 0},
        "categories": {"up": 0, "other_limited": 0, "standard": 0},
        "characters": {c.name: 0 for c in config.six_star_characters},
        "rewards": {reward.name: 0.0 for reward in config.rewards},
        "pity_triggers": {"five_star": 0, "six_star_hard": 0},
    }


def _add_outcome(counts: dict, outcome: DrawOutcome) -> None:
    counts["rarities"][str(outcome.rarity)] += 1
    if outcome.rarity == 6:
        category = (
            "up"
            if outcome.is_up
            else "other_limited"
            if outcome.is_limited
            else "standard"
        )
        counts["categories"][category] += 1
        counts["characters"][outcome.character_name] += 1
    counts["pity_triggers"]["five_star"] += int(
        outcome.five_star_pity_triggered
    )
    counts["pity_triggers"]["six_star_hard"] += int(
        outcome.six_star_hard_pity_triggered
    )


def _add_counts(target: dict, source: dict) -> None:
    for group, values in source.items():
        for name, value in values.items():
            target[group][name] += value


def draw_once(
    rule: LotteryRule,
    state: DrawState,
    rng: random.Random,
) -> DrawResult:
    probabilities = rule.rarity_probabilities(state)
    rarity = sample_distribution(
        ((6, probabilities.six_star), (5, probabilities.five_star),
         (4, probabilities.four_star)),
        rng.random(),
    )
    characters = rule.character_probabilities(rarity, state)
    if rarity == 6 and not characters:
        raise ValueError("six-star character distribution must not be empty")
    name = sample_distribution(tuple(characters.items()), rng.random()) if characters else None
    character = (
        next(c for c in rule.config.six_star_characters if c.name == name)
        if rarity == 6 else None
    )
    outcome = DrawOutcome(
        rarity=rarity,
        character_name=name,
        is_up=bool(character and character.is_up),
        is_limited=bool(character and character.is_limited),
        rewards=rule.config.rewards_for(rarity),
        five_star_pity_triggered=rule.five_star_pity_active(state),
        six_star_hard_pity_triggered=rule.six_star_hard_pity_active(state),
    )
    return DrawResult(outcome, probabilities, state, rule.advance_rarity(state, rarity))


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
    collect_records: bool = False,
    initial_five_star_pity: int = 0,
) -> SimulationResult:
    _positive_integer(draws, "draws")
    _positive_integer(trials, "trials")
    _positive_integer(progress_interval, "progress_interval")
    if not isinstance(collect_records, bool):
        raise ValueError("collect_records must be a boolean")
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
    sources = ("main", "bonus", "total")
    total_counts = {source: _empty_counts(rule.config) for source in sources}
    source_distributions = {
        source: {
            "rarity_counts": {rarity: {} for rarity in ("4", "5", "6")},
            "reward_totals": {reward.name: {} for reward in rule.config.rewards},
        }
        for source in sources
    }
    rate_names = (
        "five_or_higher",
        "six_star",
        "up_six_star",
        "limited_six_star",
    )
    at_least_one_counts = {
        source: {name: 0 for name in rate_names} for source in sources
    }
    records: list[DrawRecord] = []
    interval_sum = 0
    completed_intervals = 0
    bonus_draws_per_trial = 0

    for trial in range(trials):
        state = initial_state
        trial_counts = {source: _empty_counts(rule.config) for source in sources}
        main_draws_completed = initial_pity
        trial_bonus_draws = 0
        actual_draw_index = 0
        for main_draw_index in range(1, draws + 1):
            if cancel_check is not None and cancel_check():
                raise SimulationCancelled("simulation cancelled")
            actual_draw_index += 1
            draw_result = draw_once(rule, state, rng)
            outcome = draw_result.outcome
            state_after = draw_result.state_after
            pity_position = state.misses_since_six_star + 1
            is_six_star = outcome.rarity == 6
            _add_outcome(trial_counts["main"], outcome)
            _add_outcome(trial_counts["total"], outcome)
            if is_six_star:
                interval_sum += pity_position
                completed_intervals += 1
            if collect_records:
                records.append(
                    DrawRecord(
                        record_format_version=RECORD_FORMAT_VERSION,
                        draw_index=actual_draw_index,
                        source="main",
                        source_index=main_draw_index,
                        bonus_event=None,
                        main_draws_completed=main_draws_completed + 1,
                        draw_result=draw_result,
                        main_state_before=state,
                        main_state_after=state_after,
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
                    draw_result = draw_once(
                        temporary_rule, temporary_state, rng
                    )
                    outcome = draw_result.outcome
                    temporary_state = draw_result.state_after
                    _add_outcome(trial_counts["bonus"], outcome)
                    _add_outcome(trial_counts["total"], outcome)
                    if collect_records:
                        records.append(
                            DrawRecord(
                                record_format_version=RECORD_FORMAT_VERSION,
                                draw_index=actual_draw_index,
                                source="bonus",
                                source_index=bonus_draw_index,
                                bonus_event=event.name,
                                main_draws_completed=main_draws_completed,
                                draw_result=draw_result,
                                main_state_before=state,
                                main_state_after=state,
                            )
                        )
        if trial == 0:
            bonus_draws_per_trial = trial_bonus_draws
        for source in sources:
            counts = trial_counts[source]
            counts["rewards"] = {
                reward.name: (
                    counts["rarities"]["4"] * reward.four_star
                    + counts["rarities"]["5"] * reward.five_star
                    + counts["rarities"]["6"] * reward.six_star
                )
                for reward in rule.config.rewards
            }
            _add_counts(total_counts[source], counts)
            distributions = source_distributions[source]
            for rarity, count in counts["rarities"].items():
                frequency = distributions["rarity_counts"][rarity]
                count_string = str(count)
                frequency[count_string] = frequency.get(count_string, 0) + 1
            for reward_name, reward_total in counts["rewards"].items():
                frequency = distributions["reward_totals"][reward_name]
                total_string = str(reward_total)
                frequency[total_string] = frequency.get(total_string, 0) + 1
            indicators = {
                "five_or_higher": counts["rarities"]["5"] + counts["rarities"]["6"],
                "six_star": counts["rarities"]["6"],
                "up_six_star": counts["categories"]["up"],
                "limited_six_star": (
                    counts["categories"]["up"]
                    + counts["categories"]["other_limited"]
                ),
            }
            for name, count in indicators.items():
                at_least_one_counts[source][name] += int(count > 0)

    expectations = expected_simulation_results(
        rule, draws, initial_pity, initial_five_star_pity
    )
    source_draws = {
        "main": draws,
        "bonus": bonus_draws_per_trial,
        "total": draws + bonus_draws_per_trial,
    }
    theoretical_source_summaries = {
        source: {
            "draws": source_draws[source],
            "mean_rarity_counts": expected.rarity_counts,
            "mean_six_star_categories": expected.six_star_categories,
            "mean_character_counts": expected.character_counts,
            "mean_rewards": expected.rewards,
            "mean_pity_triggers": expected.pity_triggers,
        }
        for source, expected in expectations.items()
    }
    source_summaries = {
        source: {
            "draws": source_draws[source],
            "mean_rarity_counts": {
                name: value / trials
                for name, value in total_counts[source]["rarities"].items()
            },
            "mean_six_star_categories": {
                name: value / trials
                for name, value in total_counts[source]["categories"].items()
            },
            "mean_character_counts": {
                name: value / trials
                for name, value in total_counts[source]["characters"].items()
            },
            "mean_rewards": {
                name: value / trials
                for name, value in total_counts[source]["rewards"].items()
            },
            "mean_pity_triggers": {
                name: value / trials
                for name, value in total_counts[source]["pity_triggers"].items()
            },
        }
        for source in sources
    }
    at_least_one_rates = {
        source: {
            name: at_least_one_counts[source][name] / trials for name in rate_names
        }
        for source in sources
    }
    count_distribution = {
        int(count): frequency
        for count, frequency in source_distributions["total"]["rarity_counts"][
            "6"
        ].items()
    }

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
        mean_main_six_stars=source_summaries["main"]["mean_rarity_counts"]["6"],
        mean_bonus_six_stars=source_summaries["bonus"]["mean_rarity_counts"]["6"],
        mean_six_stars=source_summaries["total"]["mean_rarity_counts"]["6"],
        at_least_one_rate=at_least_one_rates["total"]["six_star"],
        observed_mean_interval=(
            interval_sum / completed_intervals if completed_intervals else None
        ),
        theoretical_expected_main_count=expectations["main"].rarity_counts["6"],
        theoretical_expected_bonus_count=expectations["bonus"].rarity_counts["6"],
        theoretical_expected_count=expectations["total"].rarity_counts["6"],
        records=tuple(records),
        source_summaries=source_summaries,
        source_distributions=source_distributions,
        at_least_one_rates=at_least_one_rates,
        pool_config=rule.config.to_dict(),
        initial_five_star_pity=initial_five_star_pity,
        theoretical_source_summaries=theoretical_source_summaries,
    )
