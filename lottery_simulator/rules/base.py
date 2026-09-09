from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DrawState:
    misses_since_six_star: int = 0


class LotteryRule(Protocol):
    name: str
    max_pity: int

    def probability(self, state: DrawState) -> float: ...

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState: ...
