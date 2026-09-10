from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.first_thirty_bonus import FirstThirtyBonusRule


class Rule1:
    name = "rule1"
    max_pity = 80
    subrules = (FirstThirtyBonusRule(),)

    def _validate(self, state: DrawState) -> None:
        misses = state.misses_since_six_star
        if isinstance(misses, bool) or not isinstance(misses, int):
            raise TypeError("misses_since_six_star must be an integer")
        if not 0 <= misses < self.max_pity:
            raise ValueError("misses_since_six_star must be between 0 and 79")

    def probability(self, state: DrawState) -> float:
        self._validate(state)
        pull = state.misses_since_six_star + 1
        if pull == self.max_pity:
            return 1.0
        if pull >= 65:
            return 0.008 + 0.05 * (pull - 64)
        return 0.008

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState:
        self._validate(state)
        if is_six_star:
            return DrawState(0)
        if state.misses_since_six_star == self.max_pity - 1:
            raise ValueError("the guaranteed pull cannot miss")
        return DrawState(state.misses_since_six_star + 1)
