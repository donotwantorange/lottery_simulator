"""Deployment contracts plus executable SQLite backup/restore acceptance."""

import configparser
from contextlib import closing
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid4

from dashboard.limits import TraceLimits
from dashboard.job_models import result_payload
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceWriter
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


ROOT = Path(__file__).resolve().parents[1]


def mapping(text):
    """Parse this deployment's deliberately limited YAML subset; reject ambiguity."""
    root = {}
    stack = [(-2, root)]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 or "\t" in line:
            raise ValueError("Only two-space indentation is supported")
        key, separator, value = line.strip().partition(":")
        if not separator or key.startswith("-"):
            raise ValueError("Only mappings and JSON inline lists are supported")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if indent != stack[-1][0] + 2 or key in parent:
            raise ValueError("Invalid nesting or duplicate key")
        value = value.strip()
        parent[key] = json.loads(value) if value.startswith(("[", "{", '"')) else value
        if not value:
            parent[key] = {}
            stack.append((indent, parent[key]))
    return root


class DeploymentFilesTest(unittest.TestCase):
    def read(self, name):
        path = ROOT / name
        self.assertTrue(path.is_file(), f"Missing deployment file: {name}")
        return path.read_text()

    def compose_services(self):
        return mapping(self.read("docker-compose.yml"))["services"]

    def backup_command(self):
        service = configparser.ConfigParser(interpolation=None)
        service.read_string(self.read("deploy/lottery-backup.service"))
        return shlex.split(service["Service"]["ExecStart"])

    def test_compose_and_backup_use_v5_database_path(self):
        compose = self.compose_services()
        self.assertEqual(
            compose["app"]["environment"]["LOTTERY_DB_PATH"],
            "/app/data/history_v5.sqlite3",
        )
        command = self.backup_command()
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertEqual(
            command[2],
            "/usr/bin/docker compose exec -T app python3 scripts/backup_db.py "
            "/app/data/history_v5.sqlite3 /app/backups/lottery-v5-$(date +%%F).sqlite3",
        )

    def test_compose_public_boundary_and_persistent_paths(self):
        compose = mapping(self.read("docker-compose.yml"))
        app, caddy = (compose["services"][name] for name in ("app", "caddy"))
        self.assertNotIn("ports", app)
        self.assertEqual(caddy["ports"], ["80:80", "443:443"])
        self.assertEqual(set(compose["services"]), {"app", "caddy"})
        self.assertEqual(caddy["image"], "caddy:2.11.4-alpine")
        environment = app["environment"]
        self.assertEqual(environment["LOTTERY_ENV"], "production")
        self.assertIn("${SECRET_KEY", environment["SECRET_KEY"])
        self.assertEqual(environment["LOTTERY_DB_PATH"], "/app/data/history_v5.sqlite3")
        self.assertEqual(environment["LOTTERY_JOBS_DIR"], "/app/data/jobs_v5")
        self.assertEqual(environment["LOTTERY_EXPORTS_DIR"], "/app/data/exports_v5")
        self.assertNotIn("APP_AUTH_MODE", environment)
        self.assertNotIn("STREAMLIT_SERVER_ADDRESS", environment)
        self.assertIn("lottery_data:/app/data", app["volumes"])
        self.assertIn("lottery_backups:/app/backups", app["volumes"])
        self.assertNotIn(".streamlit/secrets.toml", str(app["volumes"]))
        self.assertIn("./frontend/dist:/srv:ro", caddy["volumes"])
        self.assertIn("caddy_data:/data", caddy["volumes"])
        self.assertIn("caddy_config:/config", caddy["volumes"])
        self.assertEqual(set(compose["volumes"]),
                         {"lottery_data", "lottery_backups", "caddy_data", "caddy_config"})

    def test_image_runs_unprivileged_gunicorn_with_health_probe(self):
        lines = self.read("Dockerfile").splitlines()
        self.assertEqual(lines[0], "FROM python:3.12.14-slim-trixie")
        instructions = {}
        for line in lines:
            command, _, value = line.partition(" ")
            instructions.setdefault(command, []).append(value)
        self.assertEqual(instructions["USER"], ["app"])
        self.assertTrue(any("useradd" in line for line in instructions["RUN"]))
        self.assertTrue(any("/app/data/jobs_v5" in line and "/app/data/exports_v5" in line
                            and "-m 700" in line and "-o app -g app" in line
                            for line in instructions["RUN"]))
        command = json.loads(instructions["CMD"][0])
        self.assertEqual(command[:2], ["gunicorn", "webapp.wsgi:application"])
        self.assertIn("0.0.0.0:8000", command)
        self.assertIn("--workers", command)
        self.assertEqual(command[command.index("--worker-class") + 1], "gthread")
        self.assertEqual(command[command.index("--threads") + 1], "4")
        self.assertEqual(command[command.index("--timeout") + 1], "120")
        health = json.loads(instructions["HEALTHCHECK"][0].split("CMD ", 1)[1])
        self.assertEqual(health[:2], ["python3", "-c"])
        compile(health[2], "Dockerfile-healthcheck", "exec")
        self.assertIn("http://127.0.0.1:8000/api/v1/auth/csrf/", health[2])
        self.assertIn("LOTTERY_ALLOWED_HOSTS", health[2])
        self.assertIn("headers={'Host': host}", health[2])

    def test_proxy_and_backup_scheduler_contract(self):
        caddyfile = self.read("Caddyfile")
        self.assertIn("@api path /api /api/*", caddyfile)
        self.assertIn("handle @api", caddyfile)
        self.assertIn("reverse_proxy app:8000", caddyfile)
        self.assertIn("header_up X-Forwarded-Proto {scheme}", caddyfile)
        self.assertIn("root * /srv", caddyfile)
        self.assertIn("try_files {path} /index.html", caddyfile)
        self.assertIn("file_server", caddyfile)
        self.assertIn('header @assets Cache-Control "public, max-age=31536000, immutable"', caddyfile)
        self.assertIn('header @index Cache-Control "no-cache"', caddyfile)
        self.assertIn('header Strict-Transport-Security "max-age=31536000; includeSubDomains"', caddyfile)
        service = configparser.ConfigParser(interpolation=None)
        service.read_string(self.read("deploy/lottery-backup.service"))
        self.assertEqual(service["Service"]["WorkingDirectory"], "/opt/lottery-simulator")
        self.assertEqual(service["Service"]["Type"], "oneshot")
        command = shlex.split(service["Service"]["ExecStart"])
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertEqual(command[2], "/usr/bin/docker compose exec -T app python3 scripts/backup_db.py "
                         "/app/data/history_v5.sqlite3 /app/backups/lottery-v5-$(date +%%F).sqlite3")
        timer = configparser.ConfigParser(interpolation=None)
        timer.read_string(self.read("deploy/lottery-backup.timer"))
        self.assertEqual(timer["Timer"]["OnCalendar"], "daily")
        self.assertTrue(timer["Timer"].getboolean("Persistent"))
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")

    def test_private_state_excluded_from_image_and_git(self):
        excluded = set(self.read(".dockerignore").splitlines())
        for pattern in (".git", ".env", ".streamlit/secrets.toml", "data", "backups",
                        "frontend/node_modules", "frontend/dist",
                        "*.sqlite3", "*.pem", "*.key", "*.crt", "*.cer", "*.p12", "*.pfx",
                        "caddy_data", "caddy_config"):
            self.assertIn(pattern, excluded)
        result = subprocess.run(["git", "check-ignore", ".env", ".streamlit/secrets.toml",
                                 "data/lottery.sqlite3", "backups/example.sqlite3",
                                 "frontend/node_modules/package.json", "frontend/dist/index.html",
                                 "private.key", "certificate.pem", "certificate.crt",
                                 "certificate.cer", "certificate.p12", "certificate.pfx",
                                 "caddy_data/state.json",
                                 "caddy_config/autosave.json", "snapshot.sqlite3"],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), 15)


class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        self.source = self.data_dir / "history_v5.sqlite3"
        self.destination = self.root / "backups" / "snapshot.sqlite3"
        self.run_id = str(uuid4())
        self.username = "backup-" + uuid4().hex[:12]
        self.password = "sample-password"
        self.session_key = uuid4().hex
        self.environment = {
            **os.environ,
            "LOTTERY_DATA_DIR": str(self.data_dir),
            "LOTTERY_DB_PATH": str(self.source),
            "LOTTERY_JOBS_DIR": str(self.data_dir / "jobs_v5"),
            "LOTTERY_EXPORTS_DIR": str(self.data_dir / "exports_v5"),
            "LOTTERY_ENV": "development",
        }
        self.manage("migrate", "--noinput", "--verbosity", "0")
        self.manage("shell", stdin=self._create_v5_fixture())
        session_rows = self.snapshot(self.source)["django_session"]
        self.assertEqual(len(session_rows), 1)
        self.session_key = session_rows[0][0]

    def manage(self, *arguments, stdin=None):
        result = subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), *arguments],
            cwd=ROOT, env=self.environment, input=stdin, capture_output=True,
            text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def _create_v5_fixture(self):
        return f'''\
from django.contrib.sessions.backends.db import SessionStore
from dashboard.job_models import result_payload
from dashboard.limits import TraceLimits
from dashboard.models import User
from dashboard.repository import HistoryRepository
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from dashboard.trace_store import TraceWriter
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1
from pathlib import Path
from uuid import UUID

admin = create_account(None, {self.username!r}, {self.password!r}, admin=True, must_change_password=False)
pool = save_pool(admin, {{**read_config_json(DEFAULT_POOL_PATH), "name": "备份验收池", "kind": "public"}})
session = SessionStore(session_key={self.session_key!r})
session["_auth_user_id"] = str(admin.pk)
session["_auth_user_backend"] = "dashboard.services.accounts.UsernameBackend"
session["_auth_user_hash"] = admin.get_session_auth_hash()
session["auth_version"] = admin.auth_version
session["created_at"] = "2026-09-29T00:00:00+00:00"
session["last_activity_at"] = "2026-09-29T00:00:00+00:00"
session.save()
rule = Rule1()
trace_path = Path({str(self.root / 'trace.sqlite3')!r})
writer = TraceWriter(trace_path, limits=TraceLimits(batch_size=5, max_records=100))
try:
    result = simulate(rule, 12, seed=42, collect_records=True, record_sink=writer.append)
    writer.finish(trials=1, draws=12, initial_main_draws=0, bonus_per_trial=result.bonus_draws)
finally:
    writer.close()
payload = result_payload(result, rule, 0.25)
payload.update(owner_id=str(admin.pk), pool_source={{"id": str(pool.pk), "revision": pool.revision,
    "name": pool.name, "original_author": pool.original_author}})
HistoryRepository().save_run({self.run_id!r}, payload, trace_path=trace_path)
assert User.objects.get(pk=admin.pk).check_password({self.password!r})
assert SessionStore(session.session_key).load()["_auth_user_id"] == str(admin.pk)
'''

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("users", "django_session", "pools", "simulation_runs", "draw_records")
            }

    def backup(self, source=None, destination=None):
        script = ROOT / "scripts/backup_db.py"
        self.assertTrue(script.is_file(), "Missing deployment file: scripts/backup_db.py")
        return subprocess.run([sys.executable, str(script), str(source or self.source),
                               str(destination or self.destination)], capture_output=True,
                              text=True, timeout=10)

    def test_online_backup_is_independent_complete_and_restorable(self):
        before = self.snapshot(self.source)
        self.assertEqual(len(before["users"]), 1)
        self.assertEqual(len(before["django_session"]), 1)
        self.assertEqual(len(before["pools"]), 1)
        self.assertEqual(len(before["simulation_runs"]), 1)
        self.assertEqual(len(before["draw_records"]), 12)
        with closing(sqlite3.connect(self.source)) as live:
            live.execute("PRAGMA journal_mode=WAL")
            result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(self.destination), before)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(self.destination)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM draw_records WHERE run_id=?", (UUID(self.run_id).hex,)
            ).fetchone()[0], 12)
        with closing(sqlite3.connect(self.source)) as live:
            live.execute("DELETE FROM draw_records")
            live.execute("DELETE FROM simulation_runs")
            live.execute("DELETE FROM django_session")
            live.execute("DELETE FROM users")
            live.commit()
        result = self.backup(self.destination, self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(self.source), before)
        self.manage("shell", stdin=f'''\
from django.contrib.sessions.models import Session
from dashboard.models import User, SimulationRun, DrawRecord
from dashboard.repository import HistoryRepository
admin = User.objects.get(username={self.username!r})
assert admin.check_password({self.password!r})
session = Session.objects.get(session_key={self.session_key!r})
assert session.get_decoded()["_auth_user_id"] == str(admin.pk)
run = HistoryRepository().get_run({self.run_id!r})
assert run["record_count"] == 12
assert DrawRecord.objects.filter(run_id={UUID(self.run_id).hex!r}).count() == 12
''')

    def test_same_resolved_path_is_rejected_without_losing_data(self):
        before = self.snapshot(self.source)
        alias = self.root / "alias.sqlite3"
        alias.symlink_to(self.source)
        hardlink = self.root / "hardlink.sqlite3"
        hardlink.hardlink_to(self.source)
        for destination in (self.source, alias, hardlink):
            result = self.backup(destination=destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("same", result.stderr.lower())
            self.assertEqual(self.snapshot(self.source), before)

    def test_missing_source_is_not_created(self):
        missing = self.root / "missing.sqlite3"
        result = self.backup(source=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

if __name__ == "__main__":
    unittest.main()
