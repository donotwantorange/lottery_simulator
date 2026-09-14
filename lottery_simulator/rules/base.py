from dataclasses import dataclass
from typing import Protocol

from lottery_simulator.rules.pool_config import PoolConfig, SixStarCharacter


@dataclass(frozen=True, slots=True)
class DrawState:
    misses_since_six_star: int = 0
    misses_since_five_or_higher: int = 0


@dataclass(frozen=True, slots=True)
class RarityProbabilities:
    four_star: float
    five_star: float
    six_star: float


@dataclass(frozen=True, slots=True)
class BonusEvent:
    name: str
    draws: int
    six_star_probability: float
    five_star_hard_pity: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.draws, bool)
            or not isinstance(self.draws, int)
            or self.draws <= 0
        ):
            raise ValueError("bonus draws must be a positive integer")
        if not 0.0 <= self.six_star_probability <= 1.0:
            raise ValueError("bonus probability must be inside [0, 1]")
        if (
            isinstance(self.five_star_hard_pity, bool)
            or not isinstance(self.five_star_hard_pity, int)
            or self.five_star_hard_pity <= 0
        ):
            raise ValueError("bonus five-star hard pity must be a positive integer")


class LotterySubRule(Protocol):
    """无状态子规则；相同累计主抽数必须始终返回相同事件。"""

    def events_after_main_draw(
        self, completed_main_draws: int
    ) -> tuple[BonusEvent, ...]: ...


class LotteryRule(Protocol):
    name: str
    max_pity: int
    subrules: tuple[LotterySubRule, ...]
    config: PoolConfig

    def probability(self, state: DrawState) -> float: ...

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState: ...

    def rarity_probabilities(self, state: DrawState) -> RarityProbabilities: ...

    def advance_rarity(self, state: DrawState, rarity: int) -> DrawState: ...

    def five_star_pity_active(self, state: DrawState) -> bool: ...

    def pick_six_star(self, roll: float) -> SixStarCharacter: ...

    def for_bonus(self, event: BonusEvent) -> "LotteryRule": ...


def bonus_events_after_main_draw(
    rule: LotteryRule, completed_main_draws: int
) -> tuple[BonusEvent, ...]:
    return tuple(
        event
        for subrule in rule.subrules
        for event in subrule.events_after_main_draw(completed_main_draws)
    )
