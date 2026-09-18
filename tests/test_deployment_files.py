"""Deployment contracts plus executable SQLite backup/restore acceptance."""

import configparser
from contextlib import closing
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from dashboard.auth import AuthConfig
from dashboard.models import result_payload
from dashboard.repository import HistoryRepository
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

    def test_compose_and_backup_use_v3_database_path(self):
        compose = self.compose_services()
        self.assertEqual(
            compose["app"]["environment"]["LOTTERY_DB_PATH"],
            "/app/data/lottery_v3.sqlite3",
        )
        command = self.backup_command()
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertEqual(
            command[2],
            "/usr/bin/docker compose exec -T app python3 scripts/backup_db.py "
            "/app/data/lottery_v3.sqlite3 /app/backups/lottery-v3-$(date +%%F).sqlite3",
        )

    def test_compose_public_boundary_and_persistent_paths(self):
        compose = mapping(self.read("docker-compose.yml"))
        app, caddy = (compose["services"][name] for name in ("app", "caddy"))
        self.assertNotIn("ports", app)
        self.assertEqual(caddy["ports"], ["80:80", "443:443"])
        self.assertEqual(set(compose["services"]), {"app", "caddy"})
        self.assertEqual(caddy["image"], "caddy:2.11.4-alpine")
        environment = app["environment"]
        self.assertEqual(environment["APP_ENVIRONMENT"], "production")
        self.assertEqual(environment["APP_AUTH_MODE"], "oidc")
        self.assertIn("${ALLOWED_EMAILS", environment["ALLOWED_EMAILS"])
        self.assertEqual(environment["LOTTERY_DB_PATH"], "/app/data/lottery_v3.sqlite3")
        config = AuthConfig(environment["APP_ENVIRONMENT"], environment["APP_AUTH_MODE"],
                            environment["STREAMLIT_SERVER_ADDRESS"], ("owner@example.invalid",))
        self.assertEqual(config.mode, "oidc")
        with self.assertRaises(ValueError):
            AuthConfig(config.environment, config.mode, config.bind_address, ())
        self.assertIn("lottery_data:/app/data", app["volumes"])
        self.assertIn("lottery_backups:/app/backups", app["volumes"])
        self.assertIn("./.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro", app["volumes"])
        self.assertIn("caddy_data:/data", caddy["volumes"])
        self.assertIn("caddy_config:/config", caddy["volumes"])
        self.assertEqual(set(compose["volumes"]),
                         {"lottery_data", "lottery_backups", "caddy_data", "caddy_config"})

    def test_image_runs_unprivileged_streamlit_with_health_probe(self):
        lines = self.read("Dockerfile").splitlines()
        self.assertEqual(lines[0], "FROM python:3.12.14-slim-trixie")
        instructions = {}
        for line in lines:
            command, _, value = line.partition(" ")
            instructions.setdefault(command, []).append(value)
        self.assertEqual(instructions["USER"], ["app"])
        self.assertTrue(any("useradd" in line for line in instructions["RUN"]))
        self.assertTrue(any("/app/data/jobs_v3" in line and "chown" in line
                            for line in instructions["RUN"]))
        command = json.loads(instructions["CMD"][0])
        self.assertEqual(command[:5], ["python3", "-m", "streamlit", "run", "dashboard/app.py"])
        self.assertIn("--server.address=0.0.0.0", command)
        self.assertIn("--server.port=8501", command)
        health = json.loads(instructions["HEALTHCHECK"][0].split("CMD ", 1)[1])
        self.assertEqual(health[:2], ["python3", "-c"])
        compile(health[2], "Dockerfile-healthcheck", "exec")
        self.assertIn("http://127.0.0.1:8501/_stcore/health", health[2])

    def test_proxy_and_backup_scheduler_contract(self):
        self.assertEqual(self.read("Caddyfile").split(),
                         ["{$DOMAIN}", "{", "encode", "zstd", "gzip", "header",
                          "Strict-Transport-Security", "\"max-age=31536000;",
                          "includeSubDomains\"", "reverse_proxy", "app:8501", "}"])
        service = configparser.ConfigParser(interpolation=None)
        service.read_string(self.read("deploy/lottery-backup.service"))
        self.assertEqual(service["Service"]["WorkingDirectory"], "/opt/lottery-simulator")
        self.assertEqual(service["Service"]["Type"], "oneshot")
        command = shlex.split(service["Service"]["ExecStart"])
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertEqual(command[2], "/usr/bin/docker compose exec -T app python3 scripts/backup_db.py "
                         "/app/data/lottery_v3.sqlite3 /app/backups/lottery-v3-$(date +%%F).sqlite3")
        timer = configparser.ConfigParser(interpolation=None)
        timer.read_string(self.read("deploy/lottery-backup.timer"))
        self.assertEqual(timer["Timer"]["OnCalendar"], "daily")
        self.assertTrue(timer["Timer"].getboolean("Persistent"))
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")

    def test_private_state_excluded_from_image_and_git(self):
        excluded = set(self.read(".dockerignore").splitlines())
        for pattern in (".git", ".env", ".streamlit/secrets.toml", "data", "backups",
                        "*.sqlite3", "*.pem", "*.key", "*.crt", "*.cer", "*.p12", "*.pfx",
                        "caddy_data", "caddy_config"):
            self.assertIn(pattern, excluded)
        result = subprocess.run(["git", "check-ignore", ".env", ".streamlit/secrets.toml",
                                 "data/lottery.sqlite3", "backups/example.sqlite3",
                                 "private.key", "certificate.pem", "certificate.crt",
                                 "certificate.cer", "certificate.p12", "certificate.pfx",
                                 "caddy_data/state.json",
                                 "caddy_config/autosave.json", "snapshot.sqlite3"],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), 13)


class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source #?.sqlite3"
        self.destination = self.root / "backups" / "snapshot.sqlite3"
        self.repository = HistoryRepository(self.source)
        self.repository.initialize()
        rule = Rule1()
        self.payload = result_payload(simulate(rule, 12, seed=42, collect_records=True), rule, 0.25)
        self.run_id = self.repository.save_run(self.payload, trace_enabled=True)

    def backup(self, source=None, destination=None):
        script = ROOT / "scripts/backup_db.py"
        self.assertTrue(script.is_file(), "Missing deployment file: scripts/backup_db.py")
        return subprocess.run([sys.executable, str(script), str(source or self.source),
                               str(destination or self.destination)], capture_output=True,
                              text=True, timeout=10)

    def test_online_backup_is_independent_complete_and_restorable(self):
        with closing(sqlite3.connect(self.source)) as live:
            live.execute("PRAGMA journal_mode=WAL")
            self.repository.save_run(self.payload, trace_enabled=False)
            result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = HistoryRepository(self.destination)
        expected = self.repository.get_run(self.run_id, include_records=True)
        self.assertEqual(backup.get_run(self.run_id, include_records=True), expected)
        self.assertEqual(len(backup.list_runs({}, 20, 0)), 2)
        with closing(sqlite3.connect(self.destination)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
        self.repository.delete_run(self.run_id)
        self.assertIsNotNone(backup.get_run(self.run_id))
        result = self.backup(self.destination, self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.repository.get_run(self.run_id, include_records=True), expected)
        self.assertIsNotNone(self.repository.get_run(self.repository.save_run(self.payload, False)))

    def test_same_resolved_path_is_rejected_without_losing_data(self):
        alias = self.root / "alias.sqlite3"
        alias.symlink_to(self.source)
        hardlink = self.root / "hardlink.sqlite3"
        hardlink.hardlink_to(self.source)
        for destination in (self.source, alias, hardlink):
            result = self.backup(destination=destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("same", result.stderr.lower())
            self.assertIsNotNone(self.repository.get_run(self.run_id))

    def test_missing_source_is_not_created(self):
        missing = self.root / "missing.sqlite3"
        result = self.backup(source=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_integrity_failure_exits_nonzero(self):
        # Real SQLite can store a broken CHECK row with checks temporarily disabled.
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE simulation_runs SET trace_enabled=7")
        result = self.backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("integrity", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
