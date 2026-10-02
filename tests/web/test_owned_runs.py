"""Task 9 history import/ownership acceptance; functional execution is task 16."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = """
from dashboard.models import SimulationEvent, SimulationRun, User
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool, load_rule_definition
from dashboard.management.commands.init_business_defaults import initialize_business_defaults
from dashboard.services.runs import *
from dashboard.repository import HistoryRepository
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
from lottery_simulator.rules.definitions import PoolDefinition
from lottery_simulator.rules.runtime import compile_pool, initial_context
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
initialize_business_defaults()
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
pool = save_pool(alice, read_config_json(DEFAULT_POOL_PATH), expected_rule_revision=1)
rule_snapshot = load_rule_definition(pool.rule)
pool_snapshot = PoolDefinition.from_dict(pool.config_json)
compiled = compile_pool(rule_snapshot, pool_snapshot)
payload = {'pool_id': str(pool.pk), 'expected_pool_revision': pool.revision,
    'expected_rule_revision': pool.rule.revision, 'initial_context': initial_context(compiled).to_dict(),
    'parameters': {'draws': 2, 'trials': 1, 'initial_main_draws': 0,
        'initial_small_pity': {}, 'initial_big_pity': {'target_obtained': False, 'misses': 0},
        'seed': str(2**100+1), 'trace': True}}
state = submit_job(alice, payload, synchronous=True)
assert state.status == 'completed' and state.history_saved
"""


class OwnedRunTests(SimpleTestCase):
    def scenario(self, script):
        with TemporaryDirectory(prefix="lottery-owned-runs-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/v6.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            for arguments, stdin in ((["migrate", "--noinput", "--verbosity", "0"], None),
                                     (["shell"], FIXTURE + script)):
                result = subprocess.run([sys.executable, str(ROOT / "manage.py"), *arguments],
                    input=stdin, text=True, cwd=ROOT, env=environment, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_atomic_event_history_and_owner_isolation(self):
        self.scenario("""
run = get_run_for_actor(alice, state.run_id)
assert run.seed == str(2**100+1) and run.pool_revision_snapshot == pool.revision
assert run.events.count() == 2
rows = query_trace_for_actor(alice, run.pk, TraceFilter())
assert rows['total'] == 2 and len(rows['items']) == 2
assert all(item['event_type'] == 'draw' for item in rows['items'])
for access in (lambda: get_run_for_actor(bob, run.pk),
               lambda: get_trace_reader_for_actor(bob, run.pk),
               lambda: resave_job_for_actor(bob, state.job_id)):
    try: access()
    except RunError as error: assert error.status == 404
    else: raise AssertionError('历史或重存越权')
assert list_runs_for_actor(bob)['items'] == []
assert get_run_for_actor(admin, run.pk).pk == run.pk
assert HistoryRepository().get_trace_reader(str(run.pk)).count_events(TraceFilter()) == 2
""")

    def test_cancelled_import_rolls_back_and_rechecks_authorization(self):
        self.scenario("""
from uuid import uuid4
from dashboard.job_models import RunParameters, read_json
from dashboard.limits import TraceLimits
from dashboard.trace_store import TraceWriter
from lottery_simulator.engine import simulate, SimulationCancelled
from lottery_simulator.rules.runtime import compile_pool
parameters = RunParameters.from_dict(read_json(get_manager().root / state.job_id / 'parameters.json'))
compiled = compile_pool(parameters.rule_snapshot, parameters.pool_snapshot)
result = simulate(compiled, parameters.parameters)
trace_path = get_manager().root / 'retry.sqlite3'
writer = TraceWriter(trace_path, limits=TraceLimits(max_records=None))
for event in result.records: writer.append(event)
from lottery_simulator.events import event_counts
writer.finish(compiled, result.parameters, event_counts(compiled.rule, result.parameters))
writer.close()
summary = get_run_for_actor(alice, state.run_id).result_json
rejected = str(uuid4())
try:
    HistoryRepository().save_run(rejected, summary, trace_path=trace_path, cancel_check=lambda: True)
except SimulationCancelled: pass
else: raise AssertionError('取消导入未被拒绝')
assert not SimulationRun.objects.filter(pk=rejected).exists()
def revoked(): raise RuntimeError('authorization revoked')
rejected_auth = str(uuid4())
try:
    HistoryRepository().save_run(rejected_auth, summary, trace_path=trace_path, authorize=revoked)
except RuntimeError: pass
else: raise AssertionError('导入未重验授权')
assert not SimulationRun.objects.filter(pk=rejected_auth).exists()
""")

    def test_inactive_owner_can_import_but_deleting_owner_cannot(self):
        self.scenario("""
from dataclasses import replace
from uuid import uuid4
from dashboard.job_models import RunParameters, read_json
from dashboard.limits import SimulationLimits
from lottery_simulator.engine import simulate
from lottery_simulator.results import simulation_payload
from lottery_simulator.rules.runtime import compile_pool
from dashboard.services.accounts import AccountError
params = RunParameters.from_dict(read_json(get_manager().root / state.job_id / 'parameters.json'))
compiled = compile_pool(params.rule_snapshot, params.pool_snapshot)
result = simulate(compiled, replace(params.parameters, trace=False))
summary = simulation_payload(result, compiled, 0)
summary.update(owner_id=state.owner_id, accepted_at=state.accepted_at,
    pool_source=state.pool_source, rule_source=state.rule_source, limit_policy=state.limit_policy)
User.objects.filter(pk=alice.pk).update(is_active=False, auth_version=2)
new_id = str(uuid4())
HistoryRepository().save_run(new_id, summary)
assert SimulationRun.objects.filter(pk=new_id, owner_id=alice.pk).exists()
User.objects.filter(pk=alice.pk).update(deleting=True)
rejected = str(uuid4())
try: HistoryRepository().save_run(rejected, summary)
except ValueError: pass
else: raise AssertionError('删除中账号被重新导入')
assert not SimulationRun.objects.filter(pk=rejected).exists()
""")

    def test_history_reader_counts_grants_once_and_positions_only_draws(self):
        self.scenario("""
from dataclasses import replace
from uuid import uuid4
from dashboard.job_models import RunParameters, read_json
from dashboard.limits import TraceLimits
from dashboard.trace_store import TraceWriter
from lottery_simulator.engine import simulate
from lottery_simulator.results import simulation_payload
from lottery_simulator.rules.runtime import compile_pool, normalize_parameters
parameters = RunParameters.from_dict(read_json(get_manager().root / state.job_id / 'parameters.json'))
rule = replace(parameters.rule_snapshot, grant=replace(parameters.rule_snapshot.grant, quantity=2))
rule = replace(rule,
    rarities=tuple(replace(rarity, soft_enabled=False, hard_enabled=False)
                   for rarity in rule.rarities),
    big_pity=replace(rule.big_pity, enabled=False),
    bonus=replace(rule.bonus, enabled=False))
compiled = compile_pool(rule, parameters.pool_snapshot)
experiment = normalize_parameters(compiled, replace(parameters.parameters, draws=480, trials=1))
trace_path = get_manager().root / 'grants.sqlite3'
writer = TraceWriter(trace_path, limits=TraceLimits(max_records=None))
result = simulate(compiled, experiment, record_sink=writer.append)
writer.finish(compiled, result.parameters, result.counts)
writer.close()
summary = simulation_payload(result, compiled, 0)
summary.update(owner_id=state.owner_id, accepted_at=state.accepted_at,
    pool_source=state.pool_source, rule_source=state.rule_source, limit_policy=state.limit_policy)
run_id = str(uuid4())
HistoryRepository().save_run(run_id, summary, trace_path=trace_path)
reader = HistoryRepository().get_trace_reader(run_id)
grants = reader.query_events(TraceFilter(event_type='character_grant'), limit=50, offset=0)
assert len(grants) == 2 and sum(item['grant']['quantity'] for item in grants) == 4
assert all(item['source'] is None and 'draw_result' not in item for item in grants)
positions = reader.position_counts(source='main', trial_from=1, trial_to=1,
    source_from=239, source_to=241)
assert [row['observations'] for row in positions] == [1, 1, 1]
""")


if __name__ == "__main__":
    import unittest
    unittest.main()
