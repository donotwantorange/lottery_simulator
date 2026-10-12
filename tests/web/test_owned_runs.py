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
    def test_default_pool_rename_preserves_accepted_history_names(self):
        self.scenario("""
from dashboard.models import Pool, ExperimentConfig
default = Pool.objects.get(pk=read_config_json(DEFAULT_POOL_PATH)['id'])
default.name = default.name_key = '默认角色池'
default.config_json = {**default.config_json, 'name': default.name}
default.save()
saved = ExperimentConfig.objects.create(owner=admin, name='旧实验', name_key='旧实验',
    pool=default, pool_name_hint=default.name, parameters_json=payload['parameters'])
old_payload = {**payload, 'pool_id': str(default.pk), 'expected_pool_revision': default.revision}
old_state = submit_job(admin, old_payload, synchronous=True)
assert old_state.status == 'completed'
before = SimulationRun.objects.get(owner=admin)
assert before.pool_name_snapshot == '默认角色池'
initialize_business_defaults()
default.refresh_from_db(); before.refresh_from_db(); saved.refresh_from_db()
assert default.name == 'zmd默认角色池'
assert saved.pool_name_hint == '默认角色池'
assert before.pool_name_snapshot == '默认角色池'
assert before.pool_config_json['name'] == '默认角色池'
assert before.result_json['pool_source']['name'] == '默认角色池'
""")

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

    def test_before_commit_idempotent_boundary_and_final_cancel(self):
        self.scenario("""
from uuid import uuid4
from dataclasses import replace
from django.db import connection
from dashboard.job_models import RunParameters, read_json
from lottery_simulator.engine import simulate, SimulationCancelled
from lottery_simulator.results import simulation_payload
params = RunParameters.from_dict(read_json(get_manager().root / state.job_id / 'parameters.json'))
result = simulate(compiled, replace(params.parameters, trace=False))
summary = simulation_payload(result, compiled, 0)
summary.update(owner_id=state.owner_id, accepted_at=state.accepted_at,
    pool_source=state.pool_source, rule_source=state.rule_source, limit_policy=state.limit_policy)
run_id = str(uuid4()); notices = []
def before():
    assert connection.in_atomic_block
    assert SimulationRun.objects.filter(pk=run_id).exists()
    notices.append('before_commit')
repository = HistoryRepository()
repository.save_run(run_id, summary, before_commit=before)
repository.save_run(run_id, summary, before_commit=before)
assert notices == ['before_commit', 'before_commit']
cancelled = False
def final_cancel():
    global cancelled
    cancelled = True
rejected = str(uuid4())
try: repository.save_run(rejected, summary, before_commit=final_cancel, cancel_check=lambda: cancelled)
except SimulationCancelled: pass
else: raise AssertionError('final cancellation ignored')
assert not SimulationRun.objects.filter(pk=rejected).exists()
try: repository.save_run(run_id, {**summary, 'simulation': {**summary['simulation'], 'changed': 1}}, before_commit=before)
except ValueError: pass
else: raise AssertionError('different same-ID snapshot accepted')
assert len(notices) == 2
""")

    def test_atomic_event_history_and_owner_isolation(self):
        self.scenario("""
run = get_run_for_actor(alice, state.run_id)
assert run.seed == str(2**100+1) and run.pool_revision_snapshot == pool.revision
assert run.events.count() == 2
rows = query_trace_for_actor(alice, run.pk, TraceFilter())
assert rows['total'] == 2 and len(rows['items']) == 2
from django.test import Client
from django.utils import timezone
client = Client()
def logged_in(user):
    client.force_login(user)
    session = client.session
    session['created_at'] = session['last_activity_at'] = timezone.now().isoformat()
    session['auth_version'] = user.auth_version
    session.save()
logged_in(alice)
for url in (f'/api/v1/runs/{run.pk}/trace/', f'/api/v1/jobs/{state.job_id}/trace/'):
    response = client.get(url)
    assert response.status_code == 200, response.content
    assert response.json()['download_limit'] == '10000', response.content
logged_in(admin)
assert client.get(f'/api/v1/runs/{run.pk}/trace/').json()['download_limit'] is None
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

    def test_same_format_legacy_sampling_history_is_read_only(self):
        self.scenario("""
import json
from copy import deepcopy
from uuid import uuid4
from dashboard.job_models import RunParameters, JobState, read_json
from dashboard.trace_export import export_trace, iter_jsonl
run = get_run_for_actor(alice, state.run_id)
legacy = deepcopy(run.result_json)
legacy['sampling_version'] = 2
SimulationRun.objects.filter(pk=run.pk).update(result_json=legacy)
repository = HistoryRepository()
assert repository.get_run(str(run.pk))['sampling_version'] == 2
assert repository.list_runs({'owner_id': alice.pk})[0]['sampling_version'] == 2
reader = repository.get_trace_reader(str(run.pk))
assert reader.count_events(TraceFilter()) == 2
lines = [json.loads(line) for line in iter_jsonl(legacy, reader, TraceFilter())]
assert lines[0]['run']['sampling_version'] == 2 and len(lines) == 3
export_path = get_manager().root / 'legacy.jsonl'
export_trace(repository.path, str(run.pk), export_path)
assert json.loads(export_path.read_text().splitlines()[0])['run']['sampling_version'] == 2
assert SimulationRun.objects.get(pk=run.pk).result_json == legacy
for version in (True, 1, 4, '2'):
    invalid = {**legacy, 'sampling_version': version}
    SimulationRun.objects.filter(pk=run.pk).update(result_json=invalid)
    try: repository.get_run(str(run.pk))
    except ValueError: pass
    else: raise AssertionError(f'unknown history version accepted: {version!r}')
    try: repository.get_trace_reader(str(run.pk))
    except ValueError: pass
    else: raise AssertionError(f'unknown Trace version accepted: {version!r}')
    try: list(iter_jsonl(invalid, reader, TraceFilter()))
    except ValueError: pass
    else: raise AssertionError(f'unknown export version accepted: {version!r}')
SimulationRun.objects.filter(pk=run.pk).update(result_json=legacy)
try: repository.save_run(str(uuid4()), legacy)
except ValueError: pass
else: raise AssertionError('legacy sampling result accepted for new save')
parameters = read_json(get_manager().root / state.job_id / 'parameters.json')
for loader, data in ((RunParameters.from_dict, parameters),
                     (JobState.from_dict, read_json(get_manager().root / state.job_id / 'state.json'))):
    try: loader({**data, 'sampling_version': 2})
    except ValueError: pass
    else: raise AssertionError('legacy sampling job accepted')
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
