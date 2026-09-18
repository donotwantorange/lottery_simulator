from dataclasses import dataclass, fields
from math import sqrt

from lottery_simulator.rules.base import (
    DrawState,
    LotteryRule,
    bonus_events_after_main_draw,
)


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


@dataclass(frozen=True, slots=True)
class PoolExpectations:
    rarity_counts: dict[str, float]
    six_star_categories: dict[str, float]
    character_counts: dict[str, float]
    rewards: dict[str, float]
    pity_triggers: dict[str, float]


def expected_pool_results(
    rule: LotteryRule, draws: int, initial_state: DrawState = DrawState()
) -> PoolExpectations:
    """Finite-draw expectations over reachable double-pity states only."""
    if isinstance(draws, bool) or not isinstance(draws, int) or draws <= 0:
        raise ValueError("draws must be a positive integer")
    states = {initial_state: 1.0}
    rarity_counts = {"4": 0.0, "5": 0.0, "6": 0.0}
    pity_triggers = {"five_star": 0.0, "six_star_hard": 0.0}
    # A rule's transitions depend only on the two counters. Cache each
    # reached state's transitions, while retaining only current nonzero masses.
    transitions = {}
    for _ in range(draws):
        next_states: dict[DrawState, float] = {}
        for state, mass in states.items():
            if state not in transitions:
                _probability(rule, state)
                probabilities = rule.rarity_probabilities(state)
                branches = (
                    (4, probabilities.four_star),
                    (5, probabilities.five_star),
                    (6, probabilities.six_star),
                )
                if (
                    any(not 0.0 <= probability <= 1.0 for _, probability in branches)
                    or abs(sum(probability for _, probability in branches) - 1.0) > 1e-12
                ):
                    raise ValueError("rule returned invalid rarity probabilities")
                transitions[state] = (
                    rule.five_star_pity_active(state),
                    rule.six_star_hard_pity_active(state),
                    tuple(
                        (str(rarity), probability, rule.advance_rarity(state, rarity))
                        for rarity, probability in branches if probability > 0.0
                    ),
                )
            five_pity, six_pity, branches = transitions[state]
            if five_pity:
                pity_triggers["five_star"] += mass
            if six_pity:
                pity_triggers["six_star_hard"] += mass
            for rarity, probability, after in branches:
                branch = mass * probability
                if branch == 0.0:
                    continue
                rarity_counts[rarity] += branch
                next_states[after] = next_states.get(after, 0.0) + branch
        states = next_states

    character_counts = {
        name: rarity_counts["6"] * share
        for name, share in rule.config.character_probabilities(6).items()
    }
    categories = {"up": 0.0, "other_limited": 0.0, "standard": 0.0}
    for character in rule.config.six_star_characters:
        category = (
            "up" if character.is_up else
            "other_limited" if character.is_limited else "standard"
        )
        categories[category] += character_counts[character.name]
    rewards = {
        reward.name: (
            rarity_counts["4"] * reward.four_star
            + rarity_counts["5"] * reward.five_star
            + rarity_counts["6"] * reward.six_star
        )
        for reward in rule.config.rewards
    }
    return PoolExpectations(rarity_counts, categories, character_counts, rewards, pity_triggers)


def _add_pool_expectations(
    first: PoolExpectations, second: PoolExpectations
) -> PoolExpectations:
    return PoolExpectations(**{
        field.name: {
            name: value + getattr(second, field.name)[name]
            for name, value in getattr(first, field.name).items()
        }
        for field in fields(PoolExpectations)
    })


def expected_simulation_results(
    rule: LotteryRule, draws: int, initial_pity: int = 0,
    initial_five_star_pity: int = 0,
) -> dict[str, PoolExpectations]:
    main = expected_pool_results(rule, draws, DrawState(initial_pity, initial_five_star_pity))
    bonus = PoolExpectations(**{
        field.name: {name: 0.0 for name in getattr(main, field.name)}
        for field in fields(PoolExpectations)
    })
    for completed_main_draws in range(initial_pity + 1, initial_pity + draws + 1):
        for event in bonus_events_after_main_draw(rule, completed_main_draws):
            bonus = _add_pool_expectations(
                bonus, expected_pool_results(rule.for_bonus(event), event.draws)
            )
    return {"main": main, "bonus": bonus, "total": _add_pool_expectations(main, bonus)}


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
    """Rule1's dynamic cycle; its six-star probability ignores five-star progress."""
    if rule.fixed_six_star_probability is not None:
        raise ValueError("fixed-probability pools do not have a dynamic pity cycle")
    _state(initial_pity, rule)
    survival = 1.0
    probabilities: list[float] = []
    for offset in range(rule.max_pity - initial_pity):
        probability = _probability(rule, DrawState(initial_pity + offset, 0))
        probabilities.append(survival * probability)
        survival *= 1.0 - probability
        if probability == 1.0:
            break
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
    return expected_pool_results(rule, draws, DrawState(initial_pity, 0)).rarity_counts["6"]


def expected_bonus_six_stars(
    rule: LotteryRule, draws: int, initial_pity: int = 0
) -> float:
    if isinstance(draws, bool) or not isinstance(draws, int) or draws <= 0:
        raise ValueError("draws must be a positive integer")
    _state(initial_pity, rule)
    return sum(
        event.draws * event.six_star_probability
        for completed_main_draws in range(
            initial_pity + 1, initial_pity + draws + 1
        )
        for event in bonus_events_after_main_draw(rule, completed_main_draws)
    )
