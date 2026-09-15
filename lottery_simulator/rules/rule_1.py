from dataclasses import replace
from functools import cached_property

from lottery_simulator.rules.base import BonusEvent, DrawState, RarityProbabilities
from lottery_simulator.rules.first_thirty_bonus import FirstThirtyBonusRule
from lottery_simulator.rules.pool_config import (
    PoolConfig,
    SixStarCharacter,
    load_pool_config,
)


class Rule1:
    name = "rule1"
    version = "2.0"
    max_pity = 80
    subrules = (FirstThirtyBonusRule(),)

    @cached_property
    def config(self) -> PoolConfig:
        return load_pool_config()

    def __init__(
        self,
        config: PoolConfig | None = None,
        fixed_six_star_probability: float | None = None,
        subrules: tuple | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        self._fixed_six_star_probability = fixed_six_star_probability
        self.subrules = type(self).subrules if subrules is None else subrules
        base_five_is_reachable = (
            not self.config.five_star.pity_enabled
            or self.config.five_star.hard_pity > 1
        )
        if base_five_is_reachable:
            for misses in range(self.max_pity - 1):
                six_star_probability = Rule1.probability(self, DrawState(misses))
                if (
                    six_star_probability < 1.0
                    and six_star_probability + self.config.five_star.base_probability
                    > 1.0
                ):
                    raise ValueError("five-star and six-star probabilities exceed 1")

    def _validate(self, state: DrawState) -> None:
        misses = state.misses_since_six_star
        if isinstance(misses, bool) or not isinstance(misses, int):
            raise TypeError("misses_since_six_star must be an integer")
        if not 0 <= misses < self.max_pity:
            raise ValueError("misses_since_six_star must be between 0 and 79")
        five_misses = state.misses_since_five_or_higher
        if isinstance(five_misses, bool) or not isinstance(five_misses, int):
            raise TypeError("misses_since_five_or_higher must be an integer")
        if self.config.five_star.pity_enabled:
            if not 0 <= five_misses < self.config.five_star.hard_pity:
                raise ValueError("misses_since_five_or_higher is outside its pity range")
        elif five_misses != 0:
            raise ValueError("misses_since_five_or_higher must be 0 when pity is disabled")

    def probability(self, state: DrawState) -> float:
        self._validate(state)
        fixed_six_star_probability = getattr(
            self, "_fixed_six_star_probability", None
        )
        if fixed_six_star_probability is not None:
            return fixed_six_star_probability
        pull = state.misses_since_six_star + 1
        if pull == self.max_pity:
            return 1.0
        if pull >= 66:
            return 0.008 + 0.05 * (pull - 65)
        return 0.008

    def for_bonus(self, event: BonusEvent) -> "Rule1":
        temporary_config = replace(
            self.config,
            five_star=replace(
                self.config.five_star,
                pity_enabled=True,
                hard_pity=event.five_star_hard_pity,
            ),
        )
        return Rule1(
            config=temporary_config,
            fixed_six_star_probability=event.six_star_probability,
            subrules=(),
        )

    def five_star_pity_active(self, state: DrawState) -> bool:
        self._validate(state)
        return (
            self.config.five_star.pity_enabled
            and state.misses_since_five_or_higher
            == self.config.five_star.hard_pity - 1
        )

    def rarity_probabilities(self, state: DrawState) -> RarityProbabilities:
        six = self.probability(state)
        five = (
            0.0
            if six == 1.0
            else 1.0 - six
            if self.five_star_pity_active(state)
            else self.config.five_star.base_probability
        )
        return RarityProbabilities(max(0.0, 1.0 - six - five), five, six)

    def advance_rarity(self, state: DrawState, rarity: int) -> DrawState:
        self._validate(state)
        if rarity == 6:
            return DrawState(0, 0)
        six_misses = state.misses_since_six_star + 1
        five_misses = (
            0
            if rarity == 5 or not self.config.five_star.pity_enabled
            else state.misses_since_five_or_higher + 1
        )
        return DrawState(six_misses, five_misses)

    def pick_six_star(self, roll: float) -> SixStarCharacter:
        probabilities = self.config.six_star_character_probabilities()
        cumulative = 0.0
        for character in self.config.six_star_characters:
            cumulative += probabilities[character.name]
            if roll < cumulative:
                return character
        return self.config.six_star_characters[-1]

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState:
        self._validate(state)
        if is_six_star:
            return DrawState(0, 0)
        if state.misses_since_six_star == self.max_pity - 1:
            raise ValueError("the guaranteed pull cannot miss")
        return DrawState(
            state.misses_since_six_star + 1,
            state.misses_since_five_or_higher,
        )
