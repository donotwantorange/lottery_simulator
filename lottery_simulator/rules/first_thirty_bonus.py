from lottery_simulator.rules.base import (
    BonusEvent,
    _validate_expected_draw_inputs,
)


class FirstThirtyBonusRule:
    def expected_draws(self, initial_main_draws: int, draws: int) -> int:
        _validate_expected_draw_inputs(initial_main_draws, draws)
        return sum(
            event.draws
            for completed_main_draws in range(
                initial_main_draws + 1, initial_main_draws + draws + 1
            )
            for event in self.events_after_main_draw(completed_main_draws)
        )

    def events_after_main_draw(
        self, completed_main_draws: int
    ) -> tuple[BonusEvent, ...]:
        if completed_main_draws != 30:
            return ()
        return (
            BonusEvent(
                name="first_thirty_bonus",
                draws=10,
                six_star_probability=0.008,
                five_star_hard_pity=10,
            ),
        )
