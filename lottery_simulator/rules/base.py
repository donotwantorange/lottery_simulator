from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DrawState:
    misses_since_six_star: int = 0


@dataclass(frozen=True, slots=True)
class BonusEvent:
    name: str
    draws: int
    six_star_probability: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.draws, bool)
            or not isinstance(self.draws, int)
            or self.draws <= 0
        ):
            raise ValueError("bonus draws must be a positive integer")
        if not 0.0 <= self.six_star_probability <= 1.0:
            raise ValueError("bonus probability must be inside [0, 1]")


class LotterySubRule(Protocol):
    """无状态子规则；相同累计主抽数必须始终返回相同事件。"""

    def events_after_main_draw(
        self, completed_main_draws: int
    ) -> tuple[BonusEvent, ...]: ...


class LotteryRule(Protocol):
    name: str
    max_pity: int
    subrules: tuple[LotterySubRule, ...]

    def probability(self, state: DrawState) -> float: ...

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState: ...


def bonus_events_after_main_draw(
    rule: LotteryRule, completed_main_draws: int
) -> tuple[BonusEvent, ...]:
    return tuple(
        event
        for subrule in rule.subrules
        for event in subrule.events_after_main_draw(completed_main_draws)
    )
