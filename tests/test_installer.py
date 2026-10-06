"""Exercise the installer with fake Docker; never install software or start services."""
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.sh"
FAKE_DOCKER = '''#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
with open(os.environ['INSTALL_CALLS'], 'a') as f:
    f.write(json.dumps(a) + '\\n')
if a[:2] == ['ps', '-aq'] and os.environ.get('INSTALL_RUNNING') == '1':
    print('existing-container')
if a[:2] == ['volume', 'ls'] and os.environ.get('INSTALL_VOLUME') == '1':
    print('existing-lottery-data')
if a[:2] == ['volume', 'ls'] and os.path.exists(os.environ.get('INSTALL_READ_MARKER', '/missing')):
    sys.exit(1)
if a[:2] == ['volume', 'ls'] and os.path.exists(os.environ.get('INSTALL_VOLUME_MARKER', '/missing')):
    print('created-lottery-data')
if a[:4] == ['compose', 'config', '--format', 'json']:
    print(json.dumps({'name': 'fixture', 'networks': {'backend': {'internal': True,
        'ipam': {'config': [{'subnet': '172.30.96.0/24', 'ip_range': '172.30.96.128/25', 'gateway': '172.30.96.1'}]}}}, 'services': {
        'caddy': {'networks': {'backend': {'ipv4_address': '172.30.96.2'}}}}}))
if a[:3] == ['network', 'ls', '-q'] and os.environ.get('INSTALL_FAIL_NETWORK_READ') == '1':
    pathlib.Path(os.environ['INSTALL_READ_MARKER']).touch()
    sys.exit(1)
if a[:2] == ['run', '--rm'] and 'node:22-bookworm-slim' in a:
    for i, item in enumerate(a):
        if item == '-v' and a[i+1].endswith(':/work/frontend'):
            source = pathlib.Path(a[i+1].split(':')[0])
            (source / 'dist').mkdir(exist_ok=True)
            (source / 'dist/index.html').write_text('fixture')
if a[:2] == ['compose', 'run'] and 'shell' in a:
    print(os.environ.get('INSTALL_STATE', 'READY'))
if a[:4] == ['compose', 'run', '--rm', '-T'] and 'python' in a and (
    os.environ.get('INSTALL_PREFLIGHT_FAIL') == '1' or
    os.environ.get('INSTALL_STATE') in {'READY', 'PARTIAL'}
):
    print('检测到已有数据库或文件数据，首次安装已停止。', file=sys.stderr)
    sys.exit(1)
if a[:2] == ['compose', 'run'] and 'manage.py' in a and (
    (os.environ.get('INSTALL_FAIL_MIGRATE') == '1' and a[-1] == 'migrate') or
    (os.environ.get('INSTALL_FAIL_INIT_ADMIN') == '1' and 'init_admin' in a)
):
    pathlib.Path(os.environ['INSTALL_VOLUME_MARKER']).touch()
    print('simulated initialization failure', file=sys.stderr)
    sys.exit(1)
'''


class InstallerTest(unittest.TestCase):
    def run_installer(self, create_env=True, answers=b'n\n', **flags):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copy2(SCRIPT, root / 'scripts/install.sh')
            shutil.copy2(SCRIPT.parents[0] / 'check_proxy_network.py', root / 'scripts/check_proxy_network.py')
            for name in ['docker-compose.yml', 'Dockerfile', 'Caddyfile',
                         'configs/pools/default.json', 'configs/rules/zmd.json',
                         'frontend/package-lock.json']:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            env_file = root / '.env'
            if create_env:
                env_file.write_text('DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            binary = root / 'bin'
            binary.mkdir()
            for name, content in {'docker': FAKE_DOCKER,
                                  'sudo': '#!/bin/sh\n[ "$1" = "-v" ] && exit 0\nexec "$@"\n',
                                  'curl': '#!/bin/sh\nexit 99\n',
                                  'ip': '#!/bin/sh\nprintf "[]\\n"\n',
                                  'git': '#!/bin/sh\nexit 99\n',
                                  'openssl': '#!/bin/sh\nprintf "%096d\\n" 0\n',
                                  'nano': '#!/bin/sh\nexit 99\n'}.items():
                target = binary / name
                target.write_text(content)
                target.chmod(0o755)
            (binary / 'python3').symlink_to(sys.executable)
            calls = root / 'calls'
            env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
                   'INSTALL_CALLS': str(calls), 'INSTALL_VOLUME_MARKER': str(root / 'created-volume'),
                   'INSTALL_READ_MARKER': str(root / 'read-failed'), **flags}
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(['bash', str(root / 'scripts/install.sh')],
                                           stdin=slave, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, env=env)
                os.write(master, answers)
                output, _ = process.communicate(timeout=20)
            finally:
                os.close(master)
                os.close(slave)
            import json
            commands = [json.loads(x) for x in calls.read_text().splitlines()]
            if create_env:
                self.assertEqual(env_file.read_text(), 'DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            elif env_file.exists():
                self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
                self.assertIn('DOMAIN=fixture.example\n', env_file.read_text())
            return process.returncode, output.decode(), commands

    def test_running_installation_exits_before_changes(self):
        code, output, calls = self.run_installer(INSTALL_RUNNING='1')
        self.assertNotEqual(code, 0, output)
        self.assertIn('首次安装已停止', output)
        self.assertFalse(any(x[0] in {'pull', 'run', 'compose'} for x in calls))

    def test_existing_stopped_database_volume_stops_before_changes(self):
        code, output, calls = self.run_installer(INSTALL_VOLUME='1')
        self.assertNotEqual(code, 0, output)
        self.assertIn('首次安装已停止', output)
        self.assertFalse(any(x[0] in {'pull', 'run'} or tuple(x[:2]) in
            {('compose', 'build'), ('compose', 'up')} for x in calls))

    def test_initialized_database_stops_after_read_only_preflight(self):
        code, output, calls = self.run_installer(INSTALL_STATE='READY')
        self.assertNotEqual(code, 0, output)
        self.assertIn('首次安装已停止', output)
        build = next(x for x in calls if 'node:22-bookworm-slim' in x)
        self.assertTrue(any(x.endswith(':/work/frontend') for x in build))
        self.assertTrue(any(x.endswith(':/work/configs:ro') for x in build))
        self.assertIn('/work/frontend', build)
        self.assertFalse(any('init_admin' in x or 'migrate' in x or x[:2] == ['compose', 'up'] for x in calls))

    def test_nonempty_data_preflight_stops_before_migrate_or_init(self):
        code, output, calls = self.run_installer(INSTALL_PREFLIGHT_FAIL='1')
        self.assertNotEqual(code, 0, output)
        self.assertFalse(any('migrate' in x or 'init_admin' in x or x[:2] == ['compose', 'up'] for x in calls))

    def test_partial_database_stops_without_start_or_reset(self):
        code, output, calls = self.run_installer(INSTALL_STATE='PARTIAL')
        self.assertNotEqual(code, 0)
        self.assertIn('首次安装已停止', output)
        self.assertFalse(any('migrate' in x or 'init_admin' in x or x[:2] == ['compose', 'up'] for x in calls))

    def test_fresh_install_creates_private_env_and_initializes(self):
        code, output, calls = self.run_installer(create_env=False,
            answers=b'n\nfixture.example\nadmin-fixture\n', INSTALL_STATE='EMPTY')
        self.assertEqual(code, 0, output)
        self.assertIn(['compose', 'run', '--rm', 'app', 'python', 'manage.py',
                       'init_admin', '--username', 'admin-fixture'], calls)
        self.assertIn(['compose', 'up', '-d'], calls)

    def test_fresh_retry_keeps_existing_env_and_initializes(self):
        code, output, calls = self.run_installer(answers=b'n\nadmin-fixture\n', INSTALL_STATE='EMPTY')
        self.assertEqual(code, 0, output)
        self.assertIn(['compose', 'run', '--rm', 'app', 'python', 'manage.py',
                       'init_admin', '--username', 'admin-fixture'], calls)
        self.assertIn(['compose', 'up', '-d'], calls)

    def test_ip_rejected_before_build_or_database_changes(self):
        code, output, calls = self.run_installer(create_env=False,
                                                answers=b'n\n127.0.0.1\n')
        self.assertNotEqual(code, 0)
        self.assertIn('不接受 IP 地址', output)
        self.assertFalse(any('migrate' in x or 'node:22-bookworm-slim' in x for x in calls))

    def test_migration_failure_reports_manual_recovery_without_retry(self):
        code, output, calls = self.run_installer(INSTALL_STATE='EMPTY', INSTALL_FAIL_MIGRATE='1')
        self.assertNotEqual(code, 0)
        self.assertIn('已存在运行材料', output)
        self.assertIn('不会自动续跑或清理数据', output)
        self.assertEqual(sum(x[-1:] == ['migrate'] for x in calls), 1)
        self.assertFalse(any(x[:2] == ['compose', 'up'] or 'init_admin' in x or
                             x[:2] == ['compose', 'down'] for x in calls))

    def test_admin_init_failure_reports_manual_recovery_without_retry(self):
        code, output, calls = self.run_installer(create_env=False,
            answers=b'n\nfixture.example\nadmin-fixture\n', INSTALL_STATE='EMPTY',
            INSTALL_FAIL_INIT_ADMIN='1')
        self.assertNotEqual(code, 0)
        self.assertIn('已存在运行材料', output)
        self.assertEqual(sum('init_admin' in x for x in calls), 1)
        self.assertFalse(any(x[:2] == ['compose', 'up'] or x[:2] == ['compose', 'down'] for x in calls))

    def test_unreadable_docker_state_never_claims_safe_rerun(self):
        code, output, calls = self.run_installer(INSTALL_FAIL_NETWORK_READ='1')
        self.assertNotEqual(code, 0)
        self.assertIn('现有数据状态未知', output)
        self.assertNotIn('未发现数据库、容器或数据卷', output)
        self.assertFalse(any('migrate' in x or x[:2] == ['compose', 'up'] for x in calls))


if __name__ == '__main__':
    unittest.main()
