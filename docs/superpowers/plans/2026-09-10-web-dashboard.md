# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure Streamlit dashboard that runs the existing lottery simulator, shows interactive analysis, persists SQLite history, compares two runs, supports cancellable background jobs, and deploys behind Caddy on Linux.

**Architecture:** Streamlit is a thin presentation layer over the existing rule, analysis, and simulation modules. A subprocess worker writes atomic job-state JSON files, while a standard-library SQLite repository persists completed results and optional single-trial traces; Caddy is the only public endpoint and Streamlit OIDC plus an email allowlist protects the app.

**Tech Stack:** Python 3.12.14, Streamlit 1.63.0 with auth extra, standard-library `sqlite3`/`subprocess`/`json`, Python 3.12.14 slim Docker image, Caddy 2.11.4 Alpine, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-10-web-dashboard-design.md`

## Global Constraints

- Preserve all existing CLI and public Python behavior; the current 41 tests remain green.
- The dashboard must call the existing simulator and analyzer; no probability formula may be copied into dashboard code.
- The visible parameter label is exactly `假设主池已累计多少抽仍未出6星`.
- Trace is available only when `trials == 1`; only traced runs persist draw records.
- One application instance runs at most one simulation job at a time.
- Progress and cancellation hooks must not change RNG calls or fixed-seed results.
- Completed simulations are saved automatically; failed and cancelled jobs are not saved.
- SQLite summary and trace rows commit in one transaction, with foreign keys and cascade deletion enabled.
- History comparison selects at most two runs and warns when rule/statistical versions differ.
- Public deployment requires HTTPS, OIDC, and an allowed-email check; missing production auth configuration must fail closed.
- `APP_AUTH_MODE=disabled` is valid only in development bound to loopback.
- The app container has no published host port; only Caddy publishes 80/443.
- Secrets, database files, job state, backups, and certificates are never committed.
- Every rule or behavior change is recorded in `docs/changes/`.

## File Map

- `requirements.txt`: Exact runtime dependency lock.
- `lottery_simulator/engine.py`: Backward-compatible progress and cancellation hooks.
- `lottery_simulator/rules/rule_1.py`: Stable `version = "1.1"`.
- `dashboard/models.py`: Job parameters/state and JSON conversion.
- `dashboard/repository.py`: SQLite schema, migrations, transactions, queries, and backup.
- `dashboard/jobs.py`: Atomic job state, subprocess lifecycle, one-job lock, cancel/recovery.
- `dashboard/worker.py`: Module entry point that runs one simulation job.
- `dashboard/auth.py`: Environment validation, OIDC gate, and email allowlist.
- `dashboard/charts.py`: Convert saved/current result payloads into Streamlit chart data.
- `dashboard/views/simulation.py`: Parameter form, progress, metrics, charts, trace, download.
- `dashboard/views/history.py`: Filters, details, parameter reuse, two-run comparison, deletion.
- `dashboard/app.py`: Page configuration, auth, repository initialization, and navigation.
- `.streamlit/config.toml`: Light theme and safe server defaults.
- `.streamlit/secrets.example.toml`: Non-secret OIDC configuration shape.
- `Dockerfile`, `docker-compose.yml`, `Caddyfile`: Reproducible Linux deployment.
- `scripts/backup_db.py`: SQLite online backup command.
- `docs/deployment.md`: DNS, auth, deploy, upgrade, backup/restore, logs, rollback.
- `tests/test_engine.py`: Hook determinism/cancellation.
- `tests/test_dashboard_models.py`: JSON contracts.
- `tests/test_repository.py`: Database behavior/migration/rollback/backup.
- `tests/test_jobs.py`: Real worker start/progress/cancel/stale recovery.
- `tests/test_auth.py`: Fail-closed configuration and allowlist.
- `tests/test_charts.py`: Exact chart data derived from results.
- `tests/test_dashboard_app.py`: Streamlit AppTest states and confirmed UI copy.
- `docs/changes/2026-09-10-web-dashboard.md`: Actual verification and commit log.

---

### Task 1: Dependency lock, rule version, and cancellable engine hooks

**Files:**
- Create: `requirements.txt`
- Modify: `lottery_simulator/engine.py`
- Modify: `lottery_simulator/rules/rule_1.py`
- Modify: `tests/test_engine.py`
- Modify: `tests/test_rule_1.py`

**Interfaces:**
- Consumes: Existing `simulate(rule, draws, trials=1, seed=None, initial_pity=0)`.
- Produces: `SimulationCancelled`, `ProgressCallback`, `CancelCheck`, and appended optional arguments `progress_callback=None`, `cancel_check=None`, `progress_interval=1000`; `Rule1.version == "1.1"`.

- [ ] **Step 1: Add failing hook and version tests**

Append to `tests/test_engine.py`:

```python
from lottery_simulator.engine import SimulationCancelled

    def test_progress_hooks_do_not_change_seeded_result(self):
        updates = []
        baseline = simulate(self.rule, 20, trials=3, seed=42)
        instrumented = simulate(
            self.rule, 20, trials=3, seed=42,
            progress_callback=lambda done, total: updates.append((done, total)),
            cancel_check=lambda: False,
            progress_interval=7,
        )
        self.assertEqual(instrumented, baseline)
        self.assertEqual(updates[0], (0, 60))
        self.assertEqual(updates[-1], (60, 60))

    def test_cancel_check_stops_without_returning_partial_result(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 4
        with self.assertRaises(SimulationCancelled):
            simulate(self.rule, 100, trials=2, seed=42, cancel_check=cancelled)

    def test_progress_interval_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "progress_interval"):
            simulate(self.rule, 1, progress_interval=0)
```

Append to `tests/test_rule_1.py`:

```python
    def test_rule_version_identifies_bonus_rule_behavior(self):
        self.assertEqual(self.rule.version, "1.1")
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_engine.EngineTest.test_progress_hooks_do_not_change_seeded_result tests.test_engine.EngineTest.test_cancel_check_stops_without_returning_partial_result tests.test_rule_1.Rule1Test.test_rule_version_identifies_bonus_rule_behavior -v`

Expected: FAIL because the hook arguments, exception, and version do not exist.

- [ ] **Step 3: Implement hooks without changing random sampling**

Add above `simulate` in `lottery_simulator/engine.py`:

```python
from collections.abc import Callable

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]

class SimulationCancelled(RuntimeError):
    pass
```

Append these parameters after `initial_pity`:

```python
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    progress_interval: int = 1000,
```

Before creating the RNG, validate `progress_interval` exactly like other positive integers. Set `total_units = draws * trials`, `completed_units = 0`, call `progress_callback(0, total_units)` once, then after each main draw increment `completed_units`. Every `progress_interval` units and at the final unit call the callback. Before every main draw call `cancel_check`; if true, raise `SimulationCancelled("simulation cancelled")`. These hooks must not call the RNG.

Set in `Rule1`:

```python
    version = "1.1"
```

Pin runtime dependency:

```text
streamlit[auth]==1.63.0
```

- [ ] **Step 4: Verify GREEN and mutation sensitivity**

Run: `python3 -m unittest tests.test_engine tests.test_rule_1 -v`

Expected: all focused tests pass. Temporarily move the cancel check after `rng.random()`, rerun `test_progress_hooks_do_not_change_seeded_result`, and confirm it still passes; then add a cancel-at-first-check assertion that a tracking RNG path is never entered, observe it fail under the mutation, restore the pre-draw check, and observe it pass.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt lottery_simulator/engine.py lottery_simulator/rules/rule_1.py tests/test_engine.py tests/test_rule_1.py
git commit -m "feat: add deterministic simulation progress hooks"
```

---

### Task 2: Dashboard data contracts and JSON serialization

**Files:**
- Create: `dashboard/__init__.py`
- Create: `dashboard/models.py`
- Create: `tests/test_dashboard_models.py`

**Interfaces:**
- Consumes: `SimulationResult`, `Rule1.name`, `Rule1.version`.
- Produces: `RunParameters`, `JobState`, `result_payload(result, rule_version, duration_seconds)`, and atomic JSON helpers.

- [ ] **Step 1: Write failing model tests**

```python
# tests/test_dashboard_models.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard.models import JobState, RunParameters, read_json, result_payload, write_json
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1

class DashboardModelsTest(unittest.TestCase):
    def test_parameters_validate_trace_and_limits(self):
        with self.assertRaisesRegex(ValueError, "Trace"):
            RunParameters("rule1", 10, 2, 0, 42, True).validate()
        with self.assertRaisesRegex(ValueError, "上限"):
            RunParameters("rule1", 10_000_001, 1, 0, 42, False).validate()

    def test_result_payload_is_json_round_trippable(self):
        rule = Rule1()
        result = simulate(rule, 2, seed=42, initial_pity=29)
        payload = result_payload(result, rule.version, 0.25)
        self.assertEqual(payload["rule_version"], "1.1")
        self.assertEqual(payload["duration_seconds"], 0.25)
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_json_write_is_atomic_and_readable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_json(path, {"status": "running"})
            self.assertEqual(read_json(path), {"status": "running"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_job_state_uses_known_status(self):
        with self.assertRaisesRegex(ValueError, "status"):
            JobState("id", "unknown", {}, 0, 1).validate()
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_dashboard_models -v`

Expected: `ModuleNotFoundError: No module named 'dashboard'`.

- [ ] **Step 3: Implement exact data contracts**

Use frozen slotted dataclasses. `RunParameters` fields are `rule_name`, `draws`, `trials`, `initial_pity`, `seed`, `trace`; limits are 10,000,000 main draws and 1,000,000 trials, and `draws * trials <= 100,000,000`. `JobState` fields are `job_id`, `status`, `parameters`, `completed_units`, `total_units`, `pid=None`, `started_at=None`, `updated_at=None`, `duration_seconds=None`, `error=None`, `result=None`, with statuses exactly `queued/running/completed/cancelled/failed`.

Implement `result_payload` from `dataclasses.asdict(result)` and add `rule_version` and `duration_seconds`. Implement `write_json` with `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)`, `json.dump`, `flush`, `os.fsync`, and `os.replace`; unlink the temp file on exceptions. `read_json` returns a dict and rejects non-dict roots.

- [ ] **Step 4: Verify and commit**

Run: `python3 -m unittest tests.test_dashboard_models -v`

Expected: 4 tests pass.

```bash
git add dashboard tests/test_dashboard_models.py
git commit -m "feat: add dashboard data contracts"
```

---

### Task 3: Transactional SQLite history repository

**Files:**
- Create: `dashboard/repository.py`
- Create: `tests/test_repository.py`

**Interfaces:**
- Consumes: JSON payload from Task 2.
- Produces: `HistoryRepository(path)`, `initialize()`, `save_run(payload, trace_enabled)`, `get_run(id, include_records=False)`, `list_runs(filters, limit, offset)`, `delete_run(id)`, `backup_to(path)`.

- [ ] **Step 1: Add failing repository tests**

Tests must create a real temporary SQLite database and assert:

```python
repository.initialize(); repository.initialize()
run_id = repository.save_run(payload, trace_enabled=True)
self.assertEqual(len(repository.get_run(run_id, include_records=True)["records"]), 12)
self.assertEqual(repository.list_runs({"trace_enabled": True}, 20, 0)[0]["id"], run_id)
repository.delete_run(run_id)
self.assertIsNone(repository.get_run(run_id))
```

Add a non-trace run and assert `SELECT count(*) FROM draw_records` is zero. Install a test-only SQLite trigger that aborts the second draw-record insert; assert `save_run` raises and both table counts remain zero. Set `PRAGMA user_version=0`, initialize, and assert it becomes 1. Back up to a second path and query the copied run.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_repository -v`

Expected: import failure for `dashboard.repository`.

- [ ] **Step 3: Implement schema version 1 and repository methods**

Use `sqlite3.connect`, set `row_factory=sqlite3.Row`, execute `PRAGMA foreign_keys=ON`, and create the exact two tables and columns from the design spec. Store booleans as 0/1 and JSON with `sort_keys=True`. Wrap `save_run` and `delete_run` in `with connection:` transactions. Insert records only when `trace_enabled` is true. Use `ON DELETE CASCADE`. Validate `limit` in 1–100 and nonnegative offset. Filters accept only `rule_name`, `trace_enabled`, `created_from`, and `created_to`; build SQL from this fixed key map, never interpolate arbitrary columns. Use `Connection.backup` for `backup_to`.

- [ ] **Step 4: Verify rollback causally**

Run repository tests and observe green. Temporarily remove the transaction context around trace inserts, rerun the abort-trigger test, confirm it fails with a surviving summary row, restore the transaction, and confirm pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/repository.py tests/test_repository.py
git commit -m "feat: add transactional simulation history"
```

---

### Task 4: Background job worker, progress, cancellation, and recovery

**Files:**
- Create: `dashboard/jobs.py`
- Create: `dashboard/worker.py`
- Create: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `RunParameters`, `JobState`, JSON helpers, rule registry, engine hooks, repository.
- Produces: `JobManager(root, database_path)`, `start(parameters)`, `get(job_id)`, `cancel(job_id)`, `reconcile_after_restart()`, and `python -m dashboard.worker JOB_DIR DATABASE`.

- [ ] **Step 1: Write failing real-process tests**

Use a temporary jobs directory and database. Start a 2-draw job at initial pity 29, poll with a 10-second deadline, and assert completed state contains seed 42 and was saved once. Start a large job, wait for `running`, call cancel, and assert final `cancelled` with zero history rows. Start two jobs without waiting and assert the second raises `JobAlreadyRunning`. Create a `running` state with a nonexistent PID, call `reconcile_after_restart`, and assert `failed` with public error `服务重启，未完成任务已停止`.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_jobs -v`

Expected: import failure for `dashboard.jobs`.

- [ ] **Step 3: Implement file-backed job lifecycle**

Each job has `data/jobs/<uuid>/state.json`, `parameters.json`, and optional `cancel.request`. Use `fcntl.flock` on `data/jobs/active.lock` while checking/creating active state. Launch with:

```python
subprocess.Popen(
    [sys.executable, "-m", "dashboard.worker", str(job_dir), str(database_path)],
    start_new_session=True,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
```

The worker selects the rule from the shared CLI registry, marks running with PID/time, calls `simulate` with callbacks, writes completed progress atomically, saves to SQLite, then writes completed result. On `SimulationCancelled`, write cancelled and do not save. On other exceptions, log the traceback server-side and write only `模拟任务失败` to public state. `cancel` creates `cancel.request`; the engine checks it before main draws. `reconcile_after_restart` changes every queued/running state to failed and sends SIGTERM only to a positive PID whose command line is verified as `dashboard.worker` on Linux; if verification is unavailable, do not signal.

- [ ] **Step 4: Verify real process behavior and commit**

Run: `python3 -m unittest tests.test_jobs -v`

Expected: all process tests finish within their deadlines, no orphan worker remains, completed history count is one, cancelled count is zero.

```bash
git add dashboard/jobs.py dashboard/worker.py tests/test_jobs.py
git commit -m "feat: add cancellable simulation jobs"
```

---

### Task 5: Authentication and fail-closed deployment configuration

**Files:**
- Create: `dashboard/auth.py`
- Create: `.streamlit/config.toml`
- Create: `.streamlit/secrets.example.toml`
- Create: `tests/test_auth.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Environment and Streamlit `st.user`/`st.login`/`st.logout`.
- Produces: `AuthConfig.from_env()`, `authorize_email(email, allowed)`, `require_access(st, config)`.

- [ ] **Step 1: Add failing pure boundary tests**

Test exact cases: production plus disabled auth raises; OIDC without allowed emails raises; development disabled on `0.0.0.0` raises; development disabled on `127.0.0.1` passes; email comparison trims and lowercases; unknown email fails.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_auth -v`

Expected: import failure for `dashboard.auth`.

- [ ] **Step 3: Implement auth config and gate**

`AuthConfig` fields: `environment`, `mode`, `bind_address`, `allowed_emails`. Accept only environment `development/production` and mode `disabled/oidc`. `require_access` returns immediately only for validated disabled mode. For OIDC: if not logged in, render one login button and call `st.stop`; if logged in but email not allowed, render `无权访问此应用`, logout button, and stop; otherwise return normalized email. Do not read or expose tokens.

Configure a light theme, `client.showErrorDetails="none"`, and server address from deployment command. Add `.streamlit/secrets.toml`, `data/`, `backups/`, and `.env` to `.gitignore`. The example secrets file contains dummy absolute OIDC metadata/redirect URLs and no usable secret.

- [ ] **Step 4: Verify and commit**

Run: `python3 -m unittest tests.test_auth -v`

```bash
git add dashboard/auth.py .streamlit .gitignore tests/test_auth.py
git commit -m "feat: add fail-closed dashboard authentication"
```

---

### Task 6: Chart data adapters and result presentation

**Files:**
- Create: `dashboard/charts.py`
- Create: `dashboard/views/__init__.py`
- Create: `dashboard/views/simulation.py`
- Create: `tests/test_charts.py`
- Create: `tests/test_simulation_view.py`

**Interfaces:**
- Consumes: analyzer output, job result payload, Streamlit API.
- Produces: `probability_rows(rule)`, `count_distribution_rows(payload)`, `source_comparison_rows(payload)`, `render_result(st, payload, trace_enabled)`.

- [ ] **Step 1: Add failing chart-data tests**

Assert Rule1 probability rows have 80 entries and rows 65/80 contain 0.058/1.0; count distribution sorts numeric string keys as integers; source comparison returns exactly main/bonus/total simulated and theoretical values. These expectations use known literals, not dashboard helper output.

- [ ] **Step 2: Verify RED and implement adapters**

Run `python3 -m unittest tests.test_charts -v`, observe import failure, then implement list-of-dict adapters that call `waiting_time_distribution`, `distribution_stats`, and `rule.probability`. No rule constants appear in `dashboard/charts.py`.

- [ ] **Step 3: Implement result renderer with a recording Streamlit test double**

The renderer creates metric cards, three native charts, summary/source tabs, a trace dataframe only when enabled and records exist, an explicit no-trace message otherwise, and JSON download bytes encoded UTF-8. A recording test double must assert all visible labels and that no records are passed to a dataframe for a non-trace payload.

- [ ] **Step 4: Verify and commit**

Run: `python3 -m unittest tests.test_charts tests.test_simulation_view -v`

```bash
git add dashboard/charts.py dashboard/views tests/test_charts.py tests/test_simulation_view.py
git commit -m "feat: add dashboard result visualizations"
```

---

### Task 7: Simulation page, live progress, and Streamlit AppTest

**Files:**
- Create: `dashboard/app.py`
- Modify: `dashboard/views/simulation.py`
- Create: `tests/test_dashboard_app.py`

**Interfaces:**
- Consumes: Auth gate, JobManager, HistoryRepository, `render_result`.
- Produces: runnable `streamlit run dashboard/app.py`, parameter form, polling fragment, start/stop states.

- [ ] **Step 1: Add failing AppTest for confirmed form copy**

Set development/disabled/loopback environment before loading `AppTest.from_file("dashboard/app.py")`. Assert zero exceptions; locate number input label exactly `假设主池已累计多少抽仍未出6星`; set trials to 2 and assert Trace toggle is disabled with explanatory help; set invalid work size and assert start is rejected while widget values remain.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_dashboard_app -v`

Expected: missing `dashboard/app.py` or missing widgets.

- [ ] **Step 3: Build the confirmed single-page layout**

Use `st.set_page_config(page_title="抽奖概率实验室", layout="wide")`. Render parameter widgets in the sidebar and current status/results in the main column. Store only `current_job_id` and selected history IDs in Session State. A `@st.fragment(run_every=0.5)` polls the job while queued/running, renders progress and elapsed time, and calls `st.rerun()` on terminal state. The stop button calls `JobManager.cancel` and never writes history itself. Disable Start while a live job exists.

For AppTest only, `DASHBOARD_SYNC_JOBS=1` uses a synchronous adapter with the same `start/get/cancel` result contract and a temporary database path supplied by `LOTTERY_DATA_DIR`; production rejects this mode.

- [ ] **Step 4: Add terminal-state AppTests**

Assert completed renders metrics/download; cancelled renders `模拟已取消` and no result; failed renders only safe summary; repository failure renders result plus `历史保存失败` and download. Use real temporary SQLite for completed flow and the synchronous adapter to avoid process timing in UI tests.

- [ ] **Step 5: Verify and commit**

Run: `python3 -m unittest tests.test_dashboard_app -v`

Expected: all AppTests pass with zero Streamlit exceptions.

```bash
git add dashboard/app.py dashboard/views/simulation.py tests/test_dashboard_app.py
git commit -m "feat: add interactive simulation dashboard"
```

---

### Task 8: History filters, two-run comparison, reuse, and deletion

**Files:**
- Create: `dashboard/views/history.py`
- Modify: `dashboard/app.py`
- Modify: `tests/test_dashboard_app.py`

**Interfaces:**
- Consumes: repository list/get/delete and result renderer.
- Produces: history list, filters, at-most-two selection, comparison cards, reuse callback, confirmed delete.

- [ ] **Step 1: Add failing history AppTests**

Seed three real history rows. Assert newest-first list; filter trace and rule; select two and see two cards; attempt three and see `最多选择两次运行`; compare different rule versions and see `统计口径不同`; click reuse and assert form widget Session State receives draws/trials/initial pity/seed without starting; click delete once and assert record remains, confirm and assert it is removed with trace cascade.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_dashboard_app.DashboardAppTest.test_history_workflow -v`

Expected: missing history controls.

- [ ] **Step 3: Implement history view**

Use repository pagination of 20 rows. Selection IDs are stored as a list and truncated only after displaying the explicit limit error. Reuse writes widget keys before the simulation form is instantiated on the rerun. Delete confirmation uses a selected run ID plus `st.warning` and separate Confirm/Cancel buttons; no immediate delete callback on the first click. Comparison uses saved snapshots, never recalculates old results.

- [ ] **Step 4: Verify and commit**

Run: `python3 -m unittest tests.test_dashboard_app tests.test_repository -v`

```bash
git add dashboard/views/history.py dashboard/app.py tests/test_dashboard_app.py
git commit -m "feat: add simulation history comparison"
```

---

### Task 9: Docker, Caddy, backup, deployment documentation, and acceptance

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `Caddyfile`
- Create: `.dockerignore`
- Create: `scripts/backup_db.py`
- Create: `docs/deployment.md`
- Create: `tests/test_deployment_files.py`
- Modify: `README.md`
- Modify: `docs/changes/2026-09-10-web-dashboard.md`

**Interfaces:**
- Consumes: runnable dashboard and SQLite repository.
- Produces: reproducible public deployment and verified backup/restore procedure.

- [ ] **Step 1: Add failing deployment contract tests**

Parse Compose YAML text conservatively without a YAML dependency and assert: Caddy image is `caddy:2.11.4-alpine`; app has no `ports:`; Caddy alone maps 80/443; app environment fixes production/OIDC; data and Caddy certificate volumes exist. Assert Dockerfile starts with `python:3.12.14-slim-trixie`, creates a non-root user, runs Streamlit on `0.0.0.0:8501`, and has health check. Assert Caddyfile uses `${DOMAIN}` and `reverse_proxy app:8501`.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_deployment_files -v`

Expected: required deployment files are missing.

- [ ] **Step 3: Write exact deployment artifacts**

Dockerfile installs `requirements.txt`, copies project files, creates `/app/data/jobs`, changes ownership to unprivileged `app`, exposes 8501 only as metadata, health-checks `http://127.0.0.1:8501/_stcore/health`, and uses exec-form Streamlit command. Compose uses named `lottery_data`, `caddy_data`, and `caddy_config` volumes; only Caddy publishes ports. Caddyfile:

```caddyfile
{$DOMAIN} {
    encode zstd gzip
    reverse_proxy app:8501
}
```

- [ ] **Step 4: Implement and verify online backup**

`scripts/backup_db.py SOURCE DESTINATION` resolves both paths, refuses identical paths, creates the destination parent, opens source read-only, uses `source.backup(destination)`, runs `PRAGMA integrity_check` on the destination, and exits nonzero unless result is `ok`. Test it against a temporary repository and query the backup.

- [ ] **Step 5: Write operational documentation**

Document exact `.env` variables (`DOMAIN`, `ALLOWED_EMAILS`), OIDC secrets file shape, callback `https://${DOMAIN}/oauth2callback`, DNS A/AAAA, ports 80/443, `docker compose up -d --build`, health/log commands, daily backup command, restore to a stopped app, image upgrade, and rollback to a named Git commit. State that HTTPS/OIDC must be tested from the public domain and cannot be proven by unit tests alone.

- [ ] **Step 6: Run full verification**

Run:

```bash
python3 -m unittest discover -v
python3 -m streamlit run dashboard/app.py --server.headless true --server.address 127.0.0.1
docker compose config
docker build -t lottery-simulator-dashboard:test .
```

Expected: all tests pass; local Streamlit health endpoint returns 200; Compose config shows no app host port; Docker build succeeds and image health command exists. Stop the local Streamlit process after the health check.

If Docker is unavailable, record this as an unverified deployment item; do not claim image or Compose runtime success.

- [ ] **Step 7: Update change record and commit**

Replace the change record status with implemented, list actual test count and verified/unverified deployment checks, and append every implementation commit SHA.

```bash
git add Dockerfile docker-compose.yml Caddyfile .dockerignore scripts/backup_db.py docs/deployment.md tests/test_deployment_files.py README.md docs/changes/2026-09-10-web-dashboard.md
git commit -m "feat: add secure Linux dashboard deployment"
```
