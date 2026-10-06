"""Exercise --upgrade with fixture-only Docker and system commands."""
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
with open(os.environ['UPGRADE_CALLS'], 'a') as f: f.write(json.dumps(a) + '\n')
if a == ['info']: sys.exit(0)
if a[:2] == ['context','inspect']:
    print('tcp://remote:2376' if os.environ.get('UPGRADE_REMOTE_DOCKER') else 'unix:///var/run/docker.sock')
if a[:1] == ['run'] and any(x.endswith('node:22-bookworm-slim') for x in a):
    dist=pathlib.Path(os.environ['UPGRADE_PROJECT'])/'frontend'/'dist'
    dist.mkdir(parents=True,exist_ok=True); (dist/'index.html').write_text('fixture')
if a[:3] == ['compose', 'config', '--quiet']: sys.exit(0)
if a[:3] == ['compose', 'config', '--format']:
    print(json.dumps({'name':'fixture','services':{
      'app':{'environment':{'LOTTERY_DB_PATH':'/app/data/history_v6.sqlite3'},'ports':[],
        'networks':{'backend':{}},'volumes':[
        {'type':'volume','source':'lottery_data','target':'/app/data'},
        {'type':'volume','source':'lottery_backups','target':'/app/backups'}]},
      'caddy':{'networks':{'default':{},'backend':{'ipv4_address':'172.30.96.2'}},'volumes':[{'type':'volume','source':'caddy_data','target':'/data'},
        {'type':'volume','source':'caddy_config','target':'/config'}]}},
      'networks':{'backend':{'internal':True,'ipam':{'config':[{'subnet':'172.30.96.0/24','ip_range':'172.30.96.128/25','gateway':'172.30.96.1'}]}}},
      'volumes':{n:{'name':'fixture_'+n} for n in ('lottery_data','lottery_backups','caddy_data','caddy_config')}}))
elif a[:2] == ['ps', '-q']:
    print('a11a11a11a11' if 'service=app' in ' '.join(a) else 'cadd11cadd11')
elif a[:2] == ['ps', '-a']:
    print('a11a11a11a11\ncadd11cadd11' + ('\nother123' if os.environ.get('UPGRADE_OTHER') else ''))
elif a[:1] == ['inspect']:
    v = os.environ.get('UPGRADE_VERSION','6')
    def item(service):
      mounts=([{'Destination':'/app/data','Type':'volume','Name':'fixture_lottery_data'},
          {'Destination':'/app/backups','Type':'volume','Name':'fixture_lottery_backups'}] if service=='app' else [
          {'Destination':'/data','Type':'volume','Name':'fixture_caddy_data'},
          {'Destination':'/config','Type':'volume','Name':'fixture_caddy_config'},
          {'Destination':'/srv','Type':'bind','Source':os.environ['UPGRADE_PROJECT']+'/frontend/dist'},
          {'Destination':'/etc/caddy/Caddyfile','Type':'bind','Source':os.environ['UPGRADE_PROJECT']+'/Caddyfile'}])
      if service=='app' and os.environ.get('UPGRADE_UNKNOWN_MOUNT'): mounts.append({'Destination':'/unknown','Type':'bind','Source':'/tmp/unknown'})
      return {'Image':'sha256:'+'1'*64,'Config':{'Labels':{'com.docker.compose.project':'fixture',
        'com.docker.compose.project.working_dir':os.environ['UPGRADE_PROJECT']},
        'Env':[f'LOTTERY_DB_PATH=/app/data/history_v{v}.sqlite3','LOTTERY_DATA_DIR=/app/data',
          f'LOTTERY_JOBS_DIR=/app/data/jobs_v{v}',f'LOTTERY_EXPORTS_DIR=/app/data/exports_v{v}'],
        'WorkingDir':'/app'},'State':{'Running':True,'Health':{'Status':'healthy'}},
        'HostConfig':{'PortBindings':({'8000/tcp':[{'HostPort':'8000'}]} if os.environ.get('UPGRADE_PUBLISHED') else {}),'NetworkMode':'fixture_default'},
        'NetworkSettings':{'Networks':{'fixture_default':{}}},'Mounts':mounts}
    print(json.dumps([item('app'),item('caddy')]))
elif a[:3] == ['exec','-i','a11a11a11a11'] or (a[:1] == ['run'] and 'backup' in a):
    data = sys.stdin.read()
    if '--cidfile' in a: pathlib.Path(a[a.index('--cidfile')+1]).write_text('f'*64)
    with open(os.environ['UPGRADE_HELPERS'],'a') as f: f.write(json.dumps({'args':a[2:],'source':data})+'\n')
    fail = os.environ.get('UPGRADE_HELPER_FAIL')
    if (fail == 'probe' and 'probe' in a) or (fail == 'backup' and 'backup' in a):
      print('simulated helper failure',file=sys.stderr); sys.exit(1)
elif a[0:1] == ['cp'] and a[1].startswith('a11a11a11a11:/app/backups/'):
    import sqlite3
    db=sqlite3.connect(a[-1]); db.execute('create table snapshot(value)'); db.commit(); db.close()
elif a[0:1] == ['cp'] and a[1]=='a11a11a11a11:/app/data/.':
    pathlib.Path(a[-1]).mkdir()
elif a[:2] == ['compose','run']:
    fail = os.environ.get('UPGRADE_RUN_FAIL')
    if fail and fail in a: print('simulated command failure',file=sys.stderr); sys.exit(1)
'''

FAKE_SYSTEM = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys, tarfile
a=sys.argv[1:]; name=pathlib.Path(sys.argv[0]).name
with open(os.environ['UPGRADE_CALLS'],'a') as f: f.write(json.dumps(['system',name,*a])+'\n')
if name=='systemctl':
  if a[:1]==['stop']:
    pathlib.Path(os.environ['UPGRADE_TIMER_STOPPED']).touch()
  if a[:1]==['show']:
    unit=a[1]; prop=next((x.split('=',1)[1] for x in a if x.startswith('--property=')),'')
    if unit=='lottery-backup.timer': print(os.environ.get('UPGRADE_TIMER_LOAD','loaded') if prop=='LoadState' else ('inactive' if pathlib.Path(os.environ['UPGRADE_TIMER_STOPPED']).exists() else 'active'))
    else: print(os.environ.get('UPGRADE_SERVICE_STATE','inactive'))
elif name=='install':
  p=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT']); p.mkdir(parents=True,exist_ok=True)
elif name=='mktemp':
  template=a[-1]; d=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/(template.rsplit('/',1)[-1].rsplit('-',1)[0]+'-fixture01'); d.mkdir(parents=True); print(d)
elif name=='cp':
  src=pathlib.Path(a[-2]); dst=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/pathlib.Path(a[-1]).name; shutil.copy2(src,dst)
elif name=='tee':
  data=sys.stdin.read(); (pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/pathlib.Path(a[-1]).name).write_text(data); print(data,end='')
elif name=='tar':
  (pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/pathlib.Path(a[a.index('-czf')+1]).name).write_text('fixture archive')
elif name=='chmod': pass
'''


class UpgraderTest(unittest.TestCase):
    def run_upgrade(self, answers=b'UPGRADE\n', **flags):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'scripts').mkdir(); (root/'bin').mkdir()
            for name in ('install.sh','upgrade.sh','upgrade_probe.py','check_proxy_network.py'):
                shutil.copy2(SOURCE/'scripts'/name,root/'scripts'/name)
            for name in ('docker-compose.yml','Dockerfile','Caddyfile','configs/pools/default.json',
                         'configs/rules/zmd.json','frontend/package-lock.json'):
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            env_file=root/'.env'; env_file.write_text('DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            calls=root/'calls'; helpers=root/'helpers'
            (root/'bin/docker').write_text(FAKE_DOCKER); (root/'bin/docker').chmod(0o755)
            for name in ('systemctl','install','mktemp','cp','tee','tar','chmod'):
                p=root/'bin'/name; p.write_text(FAKE_SYSTEM); p.chmod(0o755)
            (root/'bin/python3').symlink_to(sys.executable)
            (root/'bin/ip').write_text('#!/usr/bin/env python3\nimport json,os\nprint(json.dumps([{\"dst\":\"172.30.96.0/24\",\"dev\":\"foreign\"}] if os.environ.get(\"UPGRADE_NETWORK_CONFLICT\") else []))\n'); (root/'bin/ip').chmod(0o755)
            (root/'bin/sudo').write_text('#!/bin/sh\nif [ "$1" = "-v" ]; then exit 0; fi\nexec "$@"\n'); (root/'bin/sudo').chmod(0o755)
            env={**{k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT'}},'PATH':str(root/'bin')+':'+os.environ['PATH'],
                 'UPGRADE_CALLS':str(calls),'UPGRADE_HELPERS':str(helpers),
                 'UPGRADE_TIMER_STOPPED':str(root/'timer-stopped'),
                 'UPGRADE_BACKUP_ROOT':str(root/'backup-root'),'UPGRADE_PROJECT':str(root),**flags}
            master,slave=pty.openpty()
            try:
                proc=subprocess.Popen(['bash',str(root/'scripts/install.sh'),'--upgrade'],cwd=root,
                    stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
                os.write(master,answers); out,_=proc.communicate(timeout=25)
            finally: os.close(master); os.close(slave)
            cmds=[json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
            helper=[json.loads(x) for x in helpers.read_text().splitlines()] if helpers.exists() else []
            self.assertEqual(env_file.read_text(),'DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            return proc.returncode,out.decode(errors='replace'),cmds,helper

    def test_v6_completes_without_v5_import_or_init(self):
        code,out,calls,helpers=self.run_upgrade()
        self.assertEqual(code,0,out)
        self.assertTrue(any('migrate' in c for c in calls))
        self.assertFalse(any('import_v5_accounts' in c or 'init_business_defaults' in c for c in calls))
        self.assertTrue(any(c[:3]==['compose','up','-d'] for c in calls))
        self.assertTrue(any('probe' in h['args'] for h in helpers))

    def test_v5_migrates_then_imports_then_initializes(self):
        code,out,calls,_=self.run_upgrade(answers=b'ACCOUNTS\nUPGRADE\n',UPGRADE_VERSION='5')
        self.assertEqual(code,0,out)
        ops=[next((x for x in c if x in {'migrate','import_v5_accounts','init_business_defaults'}),None) for c in calls]
        ops=[x for x in ops if x]
        self.assertEqual(ops,['migrate','import_v5_accounts','init_business_defaults'])

    def test_preflight_and_backup_failures_stop_before_compose_down(self):
        for flags in ({'UPGRADE_HELPER_FAIL':'probe'},{'UPGRADE_HELPER_FAIL':'backup'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertFalse(any(c[:2]==['compose','down'] for c in calls))
                self.assertNotIn(['rm','--force','a11a11a11a11'],calls)
                self.assertFalse(any(c[:2]==['compose','up'] for c in calls))
                if flags['UPGRADE_HELPER_FAIL']=='backup': self.assertIn(['unpause','a11a11a11a11'],calls)

    def test_import_and_migration_failures_stop_before_down_or_up(self):
        for version,answers,fail in [('5',b'ACCOUNTS\nUPGRADE\n','import_v5_accounts'),
                                     ('6',b'UPGRADE\n','migrate')]:
            with self.subTest(fail=fail):
                code,out,calls,_=self.run_upgrade(answers=answers,UPGRADE_VERSION=version,UPGRADE_RUN_FAIL=fail)
                self.assertNotEqual(code,0,out)
                # Migration runs only after the deliberate network teardown; failure must prevent restart.
                self.assertTrue(any(c[:2]==['compose','down'] for c in calls))
                self.assertFalse(any(c[:2]==['compose','up'] for c in calls))

    def test_conflict_and_unconfirmed_upgrade_stop_before_timer_or_docker_changes(self):
        for flags,answers in [({'UPGRADE_OTHER':'1'},b'UPGRADE\n'),
                              ({'UPGRADE_UNKNOWN_MOUNT':'1'},b'UPGRADE\n'),
                              ({'UPGRADE_PUBLISHED':'1'},b'UPGRADE\n'),
                              ({'UPGRADE_VERSION':'4'},b'UPGRADE\n'), ({},b'NO\n')]:
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(answers=answers,**flags)
                self.assertNotEqual(code,0,out)
                self.assertFalse(any(c[:2] in (['compose','stop'],['compose','down'],['compose','up']) for c in calls))

    def test_timer_is_stopped_and_left_paused(self):
        code,out,calls,_=self.run_upgrade()
        self.assertEqual(code,0,out)
        self.assertIn(['system','systemctl','stop','lottery-backup.timer'],calls)
        self.assertNotIn(['system','systemctl','start','lottery-backup.timer'],calls)
        self.assertFalse(any(c[:1] in (['pull'],['git'],['apt-get']) or 'volume' in c for c in calls))
        self.assertFalse(any(c[:3]==['compose','down','-v'] for c in calls))

    def test_unsafe_service_state_stops_before_compose_down(self):
        for flags in ({'UPGRADE_SERVICE_STATE':'activating'}, {'UPGRADE_TIMER_LOAD':'unknown'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertFalse(any(c[:2]==['compose','down'] for c in calls))



    def test_network_conflict_after_backup_prevents_build_or_restart(self):
        code,out,calls,_=self.run_upgrade(UPGRADE_NETWORK_CONFLICT='1')
        self.assertNotEqual(code,0,out)
        self.assertIn(['compose','down'],calls)
        self.assertFalse(any('migrate' in c or c[:2]==['compose','up'] or c[:2]==['compose','build'] for c in calls))

    def test_no_timer_does_not_create_or_start_one(self):
        code,out,calls,_=self.run_upgrade(UPGRADE_TIMER_LOAD='not-found')
        self.assertEqual(code,0,out)
        self.assertFalse(any(c[:3]==['system','systemctl','stop'] or c[:3]==['system','systemctl','start'] for c in calls))

    def test_remote_daemon_cannot_use_local_host_route_checks(self):
        for flags in ({'UPGRADE_REMOTE_DOCKER':'1'}, {'UPGRADE_REMOTE_DOCKER':'1', 'DOCKER_CONTEXT':'remote', 'DOCKER_HOST':'unix:///var/run/docker.sock'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertNotIn(['info'],calls)
                self.assertFalse(any(c[:2] in (['compose','stop'],['compose','down'],['compose','up']) for c in calls))


if __name__=='__main__':
    unittest.main()
