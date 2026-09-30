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
if a[:2] == ['ps', '-q'] and os.environ.get('INSTALL_RUNNING') == '1':
    print('existing-container')
if a[:2] == ['run', '--rm'] and 'node:22-bookworm-slim' in a:
    for i, item in enumerate(a):
        if item == '-v' and a[i+1].endswith(':/work/frontend'):
            source = pathlib.Path(a[i+1].split(':')[0])
            (source / 'dist').mkdir(exist_ok=True)
            (source / 'dist/index.html').write_text('fixture')
if a[:2] == ['compose', 'run'] and 'shell' in a:
    print(os.environ.get('INSTALL_STATE', 'READY'))
'''


class InstallerTest(unittest.TestCase):
    def run_installer(self, create_env=True, answers=b'n\n', **flags):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copy2(SCRIPT, root / 'scripts/install.sh')
            for name in ['docker-compose.yml', 'Dockerfile', 'Caddyfile',
                         'configs/pools/default.json', 'frontend/package-lock.json']:
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
                                  'git': '#!/bin/sh\nexit 99\n',
                                  'openssl': '#!/bin/sh\nprintf "%096d\\n" 0\n',
                                  'nano': '#!/bin/sh\nexit 99\n'}.items():
                target = binary / name
                target.write_text(content)
                target.chmod(0o755)
            (binary / 'python3').symlink_to(sys.executable)
            calls = root / 'calls'
            env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
                   'INSTALL_CALLS': str(calls), **flags}
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
        self.assertEqual(code, 0, output)
        self.assertIn('已有运行中的服务', output)
        self.assertFalse(any(x[0] in {'pull', 'run', 'compose'} for x in calls))

    def test_initialized_database_and_required_build_mounts(self):
        code, output, calls = self.run_installer()
        self.assertEqual(code, 0, output)
        build = next(x for x in calls if 'node:22-bookworm-slim' in x)
        self.assertTrue(any(x.endswith(':/work/frontend') for x in build))
        self.assertTrue(any(x.endswith(':/work/configs:ro') for x in build))
        self.assertIn('/work/frontend', build)
        self.assertFalse(any('init_admin' in x for x in calls))
        self.assertIn(['compose', 'up', '-d'], calls)

    def test_partial_database_stops_without_start_or_reset(self):
        code, output, calls = self.run_installer(INSTALL_STATE='PARTIAL')
        self.assertNotEqual(code, 0)
        self.assertIn('初始化状态异常', output)
        self.assertNotIn(['compose', 'up', '-d'], calls)
        self.assertFalse(any('init_admin' in x or 'down' in x for x in calls))

    def test_fresh_install_creates_private_env_and_initializes(self):
        code, output, calls = self.run_installer(create_env=False,
            answers=b'n\nfixture.example\nadmin-fixture\n', INSTALL_STATE='EMPTY')
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


if __name__ == '__main__':
    unittest.main()
