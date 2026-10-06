"""Deployment contracts plus executable SQLite backup/restore acceptance."""

import configparser
from contextlib import closing
import json
import ipaddress
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import textwrap
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
from scripts.check_proxy_network import preflight


ROOT = Path(__file__).resolve().parents[1]


class ProxyNetworkPreflightTest(unittest.TestCase):
    def config(self, subnet="172.30.96.0/24", address="172.30.96.2"):
        return {"networks": {"backend": {"internal": True, "ipam": {"config": [{"subnet": subnet, "ip_range": "172.30.96.128/25", "gateway": "172.30.96.1"}]}}},
                "services": {"caddy": {"networks": {"backend": {"ipv4_address": address}}}}}

    def test_default_route_is_not_a_conflict(self):
        with patch("scripts.check_proxy_network.inspect", return_value=[]), \
             patch("scripts.check_proxy_network.subprocess.run") as run:
            run.return_value.stdout = "net1\n"
            self.assertEqual(preflight(self.config(), "project", "docker",
                                       lambda: json.dumps([{"dst": "default", "gateway": "172.30.96.1"},
                                                           {"dst": "192.168.1.0/24", "dev": "eth0"}])),
                             (ipaddress.ip_network("172.30.96.0/24"), ipaddress.ip_address("172.30.96.2")))

    def test_builtin_networks_without_ipam_ranges_are_valid(self):
        networks = [{'Name': name, 'Labels': None, 'IPAM': {'Config': None}}
                    for name in ('host', 'none')]
        with patch('scripts.check_proxy_network.inspect', return_value=networks), \
             patch('scripts.check_proxy_network.subprocess.run') as run:
            run.return_value.stdout = 'host-id none-id'
            self.assertEqual(preflight(self.config(), 'project', 'docker', lambda: '[]')[1],
                             ipaddress.ip_address('172.30.96.2'))

    def test_invalid_addresses_and_small_subnets_fail(self):
        for subnet, address in (("172.30.96.0/24", "172.30.97.2"),
                                ("172.30.96.0/30", "172.30.96.2"),
                                ("172.30.96.0/24", "172.30.96.1"),
                                ("172.30.96.1/24", "172.30.96.2"),
                                ("172.30.96.0/255.255.255.0", "172.30.96.2")):
            with self.subTest(subnet=subnet, address=address), self.assertRaises(ValueError):
                preflight(self.config(subnet, address), "project", "docker", lambda: [])

    def test_host_route_overlap_fails(self):
        with patch("scripts.check_proxy_network.inspect", return_value=[]), \
             patch("scripts.check_proxy_network.subprocess.run") as run:
            run.return_value.stdout = ""
            with self.assertRaisesRegex(ValueError, "主机路由"):
                preflight(self.config(), "project", "docker",
                          lambda: json.dumps([{"dst": "172.30.0.0/16", "dev": "eth0"}]))

    def test_typed_and_other_table_routes_fail_closed(self):
        conflicts = (
            {"dst": "172.30.96.0/24", "type": "blackhole", "table": "main"},
            {"dst": "172.30.96.0/24", "type": "unreachable", "table": 77},
            {"dst": "172.30.96.0/24", "type": "throw", "table": 77},
        )
        for route in conflicts:
            with self.subTest(route=route), \
                 patch("scripts.check_proxy_network.inspect", return_value=[]), \
                 patch("scripts.check_proxy_network.subprocess.run") as run:
                run.return_value.stdout = "network-id\n"
                with self.assertRaisesRegex(ValueError, "主机路由"):
                    preflight(self.config(), "project", "docker", lambda: json.dumps([route]))
        for malformed in ('[{"type":"unreachable"}]', '[{"dst":"not-a-route","type":"blackhole"}]'):
            with self.subTest(malformed=malformed), \
                 patch("scripts.check_proxy_network.inspect", return_value=[]), \
                 patch("scripts.check_proxy_network.subprocess.run") as run:
                run.return_value.stdout = "network-id\n"
                with self.assertRaises(ValueError):
                    preflight(self.config(), "project", "docker", lambda: malformed)

    def test_same_project_network_is_reused_but_other_overlap_fails(self):
        own = {"Name": "project_backend", "Labels": {"com.docker.compose.project": "project",
               "com.docker.compose.network": "backend"}, "Internal": True,
               "Driver": "bridge", "Id": "0123456789ab0000",
               "Options": {}, "IPAM": {"Config": [{"Subnet": "172.30.96.0/24",
               "Gateway": "172.30.96.1", "IPRange": "172.30.96.128/25"}]}}
        other = {"Name": "other", "Labels": {}, "Internal": False,
                 "IPAM": {"Config": [{"Subnet": "172.30.96.0/24"}]}}
        with patch("scripts.check_proxy_network.subprocess.run") as run, \
             patch("scripts.check_proxy_network.inspect", return_value=[own]):
            run.return_value.stdout = "network-id\n"
            self.assertEqual(preflight(self.config(), "project", "docker",
                lambda: json.dumps([
                    {"dst": "172.30.96.0/24", "type": "unicast", "table": "main", "dev": "br-0123456789ab"},
                    {"dst": "172.30.96.1", "type": "local", "table": "local", "dev": "br-0123456789ab"},
                    {"dst": "172.30.96.0", "type": "broadcast", "table": "local", "dev": "br-0123456789ab"},
                    {"dst": "172.30.96.255", "type": "broadcast", "table": "local", "dev": "br-0123456789ab"},
                ]))[0],
                             ipaddress.ip_network("172.30.96.0/24"))
        with patch("scripts.check_proxy_network.subprocess.run") as run, \
             patch("scripts.check_proxy_network.inspect", return_value=[other]):
            run.return_value.stdout = "network-id\n"
            with self.assertRaisesRegex(ValueError, "现存 Docker 网络"):
                preflight(self.config(), "project", "docker", lambda: [])

    def test_docker_and_route_read_failures_are_rejected(self):
        with patch("scripts.check_proxy_network.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "docker")), \
             self.assertRaises(subprocess.CalledProcessError):
            preflight(self.config(), "project", "docker", lambda: [])
        with patch("scripts.check_proxy_network.inspect", return_value=[]), \
             patch("scripts.check_proxy_network.subprocess.run",
                   side_effect=[type("R", (), {"stdout": ""})(), OSError("permission denied")]), \
             self.assertRaises(OSError):
            preflight(self.config(), "project", "docker")

    def test_dynamic_range_reserves_caddy_address_and_rejects_mismatched_reuse(self):
        for value in (None, "172.30.96.0/24", "172.30.97.128/25", "172.30.96.129/25", "172.30.96.255/32"):
            config = self.config()
            config['networks']['backend']['ipam']['config'][0]['ip_range'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                preflight(config, 'project', 'docker', lambda: [])
        network = {'Name': 'project_backend', 'Labels': {'com.docker.compose.project': 'project',
            'com.docker.compose.network': 'backend'}, 'Internal': True, 'Driver': 'bridge',
            'IPAM': {'Config': [{'Subnet': '172.30.96.0/24', 'Gateway': '172.30.96.1'}]}}
        with patch('scripts.check_proxy_network.subprocess.run') as run, \
             patch('scripts.check_proxy_network.inspect', return_value=[network]):
            run.return_value.stdout = 'id'
            with self.assertRaisesRegex(ValueError, '现存 Docker 网络'):
                preflight(self.config(), 'project', 'docker', lambda: [])

    def test_gateway_is_explicit_and_cannot_occupy_caddy_or_invalid_addresses(self):
        for value in (None, '172.30.96.2', '172.30.96.0', '172.30.96.255', '172.30.97.1'):
            config = self.config()
            config['networks']['backend']['ipam']['config'][0]['gateway'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                preflight(config, 'project', 'docker', lambda: [])


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

    def test_compose_and_backup_use_v6_database_path(self):
        compose = self.compose_services()
        self.assertEqual(
            compose["app"]["environment"]["LOTTERY_DB_PATH"],
            "/app/data/history_v6.sqlite3",
        )
        command = self.backup_command()
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertEqual(
            command[2],
            "/usr/bin/docker compose exec -T app python3 scripts/backup_db.py "
            "/app/data/history_v6.sqlite3 /app/backups/lottery-v6-$(date +%%F).sqlite3",
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
        self.assertEqual(environment["LOTTERY_DB_PATH"], "/app/data/history_v6.sqlite3")
        self.assertEqual(environment["LOTTERY_JOBS_DIR"], "/app/data/jobs_v6")
        self.assertEqual(environment["LOTTERY_EXPORTS_DIR"], "/app/data/exports_v6")
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
        self.assertEqual(app["networks"], ["backend"])
        self.assertNotIn("ports", app)
        self.assertEqual(caddy["networks"]["backend"]["ipv4_address"], "${LOTTERY_CADDY_IP:-172.30.96.2}")
        backend = compose["networks"]["backend"]
        self.assertEqual(backend["internal"], "true")
        self.assertEqual(backend["ipam"]["config"][0]["subnet"], "${LOTTERY_PROXY_SUBNET:-172.30.96.0/24}")
        self.assertEqual(backend["ipam"]["config"][0]["ip_range"], "${LOTTERY_PROXY_DYNAMIC_RANGE:-172.30.96.128/25}")
        self.assertEqual(backend["ipam"]["config"][0]["gateway"], "${LOTTERY_PROXY_GATEWAY:-172.30.96.1}")
        self.assertEqual(environment["LOTTERY_TRUSTED_PROXIES"], "${LOTTERY_CADDY_IP:-172.30.96.2}")

    def test_image_runs_unprivileged_gunicorn_with_health_probe(self):
        lines = self.read("Dockerfile").splitlines()
        self.assertEqual(lines[0], "FROM python:3.12.14-slim-trixie")
        instructions = {}
        for line in lines:
            command, _, value = line.partition(" ")
            instructions.setdefault(command, []).append(value)
        self.assertEqual(instructions["USER"], ["app"])
        self.assertTrue(any("useradd" in line for line in instructions["RUN"]))
        self.assertTrue(any("/app/data/jobs_v6" in line and "/app/data/exports_v6" in line
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

    def test_trusted_proxy_settings_normalize_exact_ips_and_reject_ranges(self):
        base = {**os.environ, "LOTTERY_ENV": "development"}
        result = subprocess.run([sys.executable, "-c",
            "from webapp.settings import LOTTERY_TRUSTED_PROXIES; assert LOTTERY_TRUSTED_PROXIES == frozenset({'2001:db8::1', '192.0.2.4'})"],
            cwd=ROOT, env={**base, "LOTTERY_TRUSTED_PROXIES": " 2001:0db8::1 , 192.0.2.4 "},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for invalid in ("*", "192.0.2.0/24", "proxy.example", "not-an-ip", "192.0.2.4,"):
            with self.subTest(invalid=invalid):
                result = subprocess.run([sys.executable, "-c", "import webapp.settings"],
                    cwd=ROOT, env={**base, "LOTTERY_TRUSTED_PROXIES": invalid},
                    capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("只能包含精确 IP 地址", result.stderr)

    def test_login_source_separates_trusted_ipv4_ipv6_and_ignores_untrusted_spoof(self):
        script = textwrap.dedent("""\
            import django
            django.setup()
            from django.core.management import call_command
            from django.test import RequestFactory, override_settings
            from dashboard.models import LoginLimit
            from dashboard.services.accounts import login_source, record_login_failure
            call_command('migrate', verbosity=0, interactive=False)
            factory = RequestFactory()
            with override_settings(LOTTERY_TRUSTED_PROXIES=frozenset({'172.30.96.2'})):
                ipv4 = login_source(factory.get('/', REMOTE_ADDR='172.30.96.2', HTTP_X_FORWARDED_FOR='198.51.100.8'))
                ipv6 = login_source(factory.get('/', REMOTE_ADDR='172.30.96.2', HTTP_X_FORWARDED_FOR='2001:0db8::2'))
                spoof = login_source(factory.get('/', REMOTE_ADDR='198.51.100.9', HTTP_X_FORWARDED_FOR='203.0.113.7'))
                malformed = login_source(factory.get('/', REMOTE_ADDR='172.30.96.2', HTTP_X_FORWARDED_FOR='not-an-ip'))
            assert ipv4 == '198.51.100.8' and ipv6 == '2001:db8::2'
            assert ipv4 != ipv6 and spoof == '198.51.100.9' and malformed == 'unknown'
            for source in (ipv4, ipv6, spoof, malformed):
                record_login_failure('fixture-user', source)
            assert set(LoginLimit.objects.filter(scope='source').values_list('key', flat=True)) == {ipv4, ipv6, spoof, malformed}
        """)
        with TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            data.mkdir()
            result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                env={**os.environ, "DJANGO_SETTINGS_MODULE": "webapp.settings", "LOTTERY_ENV": "development",
                     "LOTTERY_TRUSTED_PROXIES": "", "LOTTERY_DATA_DIR": str(data),
                     "LOTTERY_DB_PATH": str(data / "history_v6.sqlite3"), "LOTTERY_JOBS_DIR": str(data / "jobs_v6"),
                     "LOTTERY_EXPORTS_DIR": str(data / "exports_v6")},
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_proxy_and_backup_scheduler_contract(self):
        caddyfile = self.read("Caddyfile")
        self.assertIn("@api path /api /api/*", caddyfile)
        self.assertIn("handle @api", caddyfile)
        self.assertIn("reverse_proxy app:8000", caddyfile)
        self.assertIn("header_up X-Forwarded-Proto {scheme}", caddyfile)
        self.assertIn("header_up X-Forwarded-For {remote_host}", caddyfile)
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
                         "/app/data/history_v6.sqlite3 /app/backups/lottery-v6-$(date +%%F).sqlite3")
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
                                 "frontend/node_modules", "frontend/dist/index.html",
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
        self.data_dir = self.root / 'data'
        self.data_dir.mkdir()
        self.source = self.data_dir / 'history_v6.sqlite3'
        self.destination = self.root / 'backups' / 'snapshot.sqlite3'
        self.username, self.password = 'backup-' + uuid4().hex[:12], 'sample-password'
        self.environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LOTTERY_ENV': 'development',
            'LOTTERY_DATA_DIR': str(self.data_dir), 'LOTTERY_DB_PATH': str(self.source),
            'LOTTERY_JOBS_DIR': str(self.data_dir / 'jobs_v6'),
            'LOTTERY_EXPORTS_DIR': str(self.data_dir / 'exports_v6')}
        self.manage('migrate', '--noinput', '--verbosity', '0')
        self.manage('shell', stdin=self._create_v6_fixture())
        with closing(sqlite3.connect(self.source)) as connection:
            self.session_key = connection.execute('SELECT session_key FROM django_session').fetchone()[0]
            self.run_id = str(UUID(connection.execute('SELECT id FROM simulation_runs').fetchone()[0]))

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return {
                table: connection.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                for table in ('users', 'django_session', 'rules', 'pools',
                              'simulation_runs', 'simulation_events')
            }

    def manage(self, *arguments, stdin=None):
        result = subprocess.run([sys.executable, str(ROOT / 'manage.py'), *arguments],
            cwd=ROOT, env=self.environment, input=stdin, capture_output=True,
            text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def _create_v6_fixture(self):
        return f'''\
from django.contrib.sessions.backends.db import SessionStore
from dashboard.models import Pool, Rule, User
from dashboard.services.accounts import create_account
from dashboard.services.runs import submit_job
from dashboard.management.commands.init_business_defaults import initialize_business_defaults
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
admin = create_account(None, {self.username!r}, {self.password!r}, admin=True, must_change_password=False)
initialize_business_defaults()
alice = create_account(admin, 'alice', 'sample-password', must_change_password=False)
pool = Pool.objects.get(pk=read_config_json(DEFAULT_POOL_PATH)['id'])
session = SessionStore()
session['_auth_user_id'] = str(admin.pk)
session['_auth_user_backend'] = 'dashboard.services.accounts.UsernameBackend'
session['_auth_user_hash'] = admin.get_session_auth_hash()
session['auth_version'] = admin.auth_version
session['created_at'] = '2026-09-29T00:00:00+00:00'
session['last_activity_at'] = '2026-09-29T00:00:00+00:00'
session.save()
state = submit_job(alice, {{'pool_id': str(pool.pk), 'expected_pool_revision': pool.revision,
    'expected_rule_revision': pool.rule.revision, 'initial_context': None,
    'parameters': {{'draws': '12', 'trials': '1', 'seed': '42', 'trace': True,
        'initial_main_draws': '0', 'initial_small_pity': {{}},
        'initial_big_pity': {{'target_obtained': False, 'misses': '0'}}}}}}, synchronous=True)
assert state.status == 'completed' and state.history_saved
assert User.objects.get(pk=admin.pk).check_password({self.password!r})
'''

    def backup(self, source=None, destination=None):
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts/backup_db.py'),
             str(source or self.source), str(destination or self.destination)],
            capture_output=True, text=True, timeout=10,
        )

    def test_online_backup_preserves_accounts_and_rules_and_restores(self):
        before = self.snapshot(self.source)
        self.assertEqual(len(before['users']), 2)
        self.assertEqual(len(before['django_session']), 1)
        self.assertEqual(len(before['rules']), 1)
        self.assertEqual(len(before['pools']), 1)
        self.assertEqual(len(before['simulation_runs']), 1)
        self.assertGreater(len(before['simulation_events']), 0)
        with closing(sqlite3.connect(self.source)) as live:
            live.execute('PRAGMA journal_mode=WAL')
            result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(self.destination), before)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(self.destination)) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute('PRAGMA foreign_keys=OFF')
            for table in ('simulation_events', 'simulation_runs', 'django_session',
                          'pools', 'rules', 'users'):
                connection.execute(f'DELETE FROM {table}')
        result = self.backup(self.destination, self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(self.source), before)
        self.manage('shell', stdin=f'''\
from django.contrib.sessions.models import Session
from dashboard.models import SimulationRun, User
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter
admin = User.objects.get(username={self.username!r})
assert admin.check_password({self.password!r})
assert Session.objects.get(session_key={self.session_key!r}).get_decoded()['_auth_user_id'] == str(admin.pk)
summary = HistoryRepository().get_run({self.run_id!r})
assert SimulationRun.objects.get(pk={self.run_id!r}).schema_version == 6
assert summary['result_format_version'] == 4 and summary['event_count'] > 0
assert HistoryRepository().get_trace_reader({self.run_id!r}).count_events(TraceFilter()) == summary['event_count']
''')

    def test_same_resolved_path_is_rejected_without_losing_data(self):
        before = self.snapshot(self.source)
        alias = self.root / 'alias.sqlite3'
        alias.symlink_to(self.source)
        hardlink = self.root / 'hardlink.sqlite3'
        hardlink.hardlink_to(self.source)
        for destination in (self.source, alias, hardlink):
            result = self.backup(destination=destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('same', result.stderr.lower())
            self.assertEqual(self.snapshot(self.source), before)

    def test_missing_source_is_not_created(self):
        missing = self.root / 'missing.sqlite3'
        result = self.backup(source=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
