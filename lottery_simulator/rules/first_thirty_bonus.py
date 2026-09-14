from lottery_simulator.rules.base import BonusEvent


class FirstThirtyBonusRule:
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
