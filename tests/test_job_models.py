"""Frozen v6 task-file contracts; end-to-end execution is covered at task 16."""

from dataclasses import replace
from datetime import datetime, timezone
import unittest
from uuid import uuid4

from dashboard.job_models import JobState, RunParameters
from dashboard.limits import SimulationLimits
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, load_pool_document, load_rule_document,
    read_config_json,
)
from lottery_simulator.engine import simulate
from lottery_simulator.results import simulation_payload
from lottery_simulator.rules.definitions import BigInitial, ExperimentParameters
from lottery_simulator.rules.runtime import compile_pool, initial_context


def frozen_parameters(*, trace=False):
    rule = load_rule_document(read_config_json(DEFAULT_RULE_PATH))
    pool = load_pool_document(read_config_json(DEFAULT_POOL_PATH))
    compiled = compile_pool(rule, pool)
    experiment = ExperimentParameters(2, 1, 42, trace, 0,
        {item.id: 0 for item in rule.rarities}, BigInitial(False, 0))
    return RunParameters(experiment, rule, pool, dict(compiled.targets), initial_context(compiled))


def valid_state():
    parameters = frozen_parameters()
    pool, rule = parameters.pool_snapshot, parameters.rule_snapshot
    counts = SimulationLimits().validate(compile_pool(rule, pool), parameters.parameters)
    return JobState(
        job_id=str(uuid4()), status="running", parameters=parameters.to_dict(),
        completed_units=1, total_units=counts.total_draws + counts.grant_triggers,
        phase="theory", owner_id=str(uuid4()), accepted_at=datetime.now(timezone.utc).isoformat(),
        pool_source={"id": pool.id, "revision": 1, "name": pool.name,
                     "original_author": pool.original_author or "作者"},
        rule_source={"id": rule.id, "revision": 1, "name": rule.name,
                     "author": rule.original_author or "作者"},
        limit_policy=SimulationLimits().to_dict(),
    )


class JobModelsTest(unittest.TestCase):
    def test_versions_are_explicit_strict_integers(self):
        params, state = frozen_parameters().to_dict(), valid_state().to_dict()
        for loader, payload in ((RunParameters.from_dict, params), (JobState.from_dict, state)):
            for field in ("job_format_version", "sampling_version"):
                for value in (None, True, 1.0):
                    with self.subTest(loader=loader.__qualname__, field=field, value=value):
                        invalid = dict(payload)
                        invalid[field] = value
                        with self.assertRaises(ValueError):
                            loader(invalid)

    def test_frozen_snapshot_round_trip_and_rejects_drift(self):
        snapshot = frozen_parameters(trace=True)
        restored = RunParameters.from_dict(snapshot.to_dict())
        self.assertEqual(restored, snapshot)
        invalid = snapshot.to_dict()
        invalid["resolved_targets"] = {}
        with self.assertRaises(ValueError):
            RunParameters.from_dict(invalid)

    def test_job_state_round_trip_and_rejects_invalid_controls(self):
        state = valid_state()
        self.assertEqual(JobState.from_dict(state.to_dict()), state)
        for invalid in (
            replace(state, status="unknown"),
            replace(state, phase_completed=3),
            replace(state, phase_completed=1, phase_total=None),
            replace(state, cancel_requested=1),
            replace(state, cleanup_error=1),
            replace(state, owner_id=None),
            replace(state, total_units=state.total_units + 1),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    invalid.validate()

    def test_result_summary_excludes_trace_events(self):
        snapshot = frozen_parameters(trace=True)
        compiled = compile_pool(snapshot.rule_snapshot, snapshot.pool_snapshot)
        result = simulate(compiled, snapshot.parameters)
        payload = simulation_payload(result, compiled, 0.25)
        self.assertEqual(payload["event_count"], result.counts.trace_events)
        self.assertNotIn("events", payload)
        self.assertNotIn("records", payload)


if __name__ == "__main__":
    unittest.main()
