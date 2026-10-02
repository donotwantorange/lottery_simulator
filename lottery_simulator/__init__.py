"""Pure simulator API, independent of the web application's persistence."""

from lottery_simulator.control import SimulationCancelled
from lottery_simulator.engine import draw_once, simulate, simulate_draws
from lottery_simulator.events import EventCounts, event_counts
from lottery_simulator.results import (
    DrawOutcome, DrawResult, ProcessEvent, SimulationResult, simulation_payload,
)
from lottery_simulator.rules.runtime import CompiledPool, DrawState, compile_pool
from lottery_simulator.analysis import expected_simulation_results
from lottery_simulator.waiting_analysis import waiting_time_stats

__all__ = [
    "CompiledPool", "DrawState", "DrawOutcome", "DrawResult", "ProcessEvent",
    "SimulationResult", "SimulationCancelled", "EventCounts", "compile_pool",
    "draw_once", "simulate", "simulate_draws", "event_counts", "simulation_payload",
    "expected_simulation_results", "waiting_time_stats",
]
