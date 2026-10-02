"""Task-3 simulation control regressions; collective execution is task 16."""

import unittest
from unittest.mock import patch

from lottery_simulator.control import SimulationCancelled, check_cancelled
from lottery_simulator.engine import simulate
from tests.fixtures_rules import default_parameters, deterministic_target_compiled


class EngineControlTests(unittest.TestCase):
    def test_cancellation_uses_the_shared_control_exception(self):
        with self.assertRaises(SimulationCancelled):
            check_cancelled(lambda: True)
        check_cancelled(lambda: False)
        check_cancelled(None)

    def test_complete_entry_passes_actual_parameters_and_runs_theory_after_simulation(self):
        compiled = deterministic_target_compiled()
        parameters = default_parameters(draws=1, trials=1, seed=None, initial_small_pity={})
        phases = []
        with patch("lottery_simulator.engine.secrets.randbits", return_value=42), \
                patch("lottery_simulator.analysis.expected_simulation_results", return_value={"fixture": True}) as theory:
            result = simulate(compiled, parameters, phase_callback=lambda *phase: phases.append(phase))
        self.assertEqual(result.parameters.seed, 42)
        self.assertEqual(result.theoretical, {"fixture": True})
        self.assertEqual([phase[0] for phase in phases], ["simulating", "theory"])
        self.assertEqual(theory.call_args.args, (compiled, result.parameters))

    def test_cancellation_at_theory_phase_prevents_completed_result(self):
        compiled = deterministic_target_compiled()
        cancelled = False

        def phase(name, *_):
            nonlocal cancelled
            cancelled = name == "theory"

        with patch("lottery_simulator.analysis.expected_simulation_results") as theory:
            with self.assertRaises(SimulationCancelled):
                simulate(compiled, default_parameters(draws=1, trials=1, seed=42, initial_small_pity={}),
                         phase_callback=phase, cancel_check=lambda: cancelled)
            theory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
