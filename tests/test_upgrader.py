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
if os.environ.get('UPGRADE_LEGACY_SUCCESS'):
    root=pathlib.Path(os.environ['UPGRADE_PROJECT'])
    state=root/'legacy-removed'
    cid='a'*64; nid='b'*64
    project='fixture'
    volume='fixture_lottery_data'; network='fixture_backend'
    config={'name':project,'services':{'app':{'environment':{'LOTTERY_DB_PATH':'/app/data/history_v6.sqlite3'}},
      'caddy':{'networks':{'backend':{'ipv4_address':'172.30.96.2'}}}},
      'volumes':{'lottery_data':{'name':volume}},
      'networks':{'backend':{'name':network,'internal':True,'ipam':{'config':[{'subnet':'172.30.96.0/24','ip_range':'172.30.96.128/25','gateway':'172.30.96.1'}]}}}}
    container={'Id':cid,'Name':'/fixture-worker','Config':{'Labels':{'com.docker.compose.project':project,
      'com.docker.compose.project.working_dir':str(root),'com.docker.compose.service':'legacy-worker'}},
      'Mounts':[{'Type':'volume','Name':volume,'Destination':'/app/data'}],
      'NetworkSettings':{'Networks':{network:{}}}}
    if a[:2]==['context','inspect']: print('unix:///var/run/docker.sock')
    elif a[:4]==['compose','config','--format','json']: print(json.dumps(config))
    elif a[:2]==['ps','-aq']: print('' if state.exists() else cid)
    elif a==['inspect',cid]: print(json.dumps([container]))
    elif a[:5]==['volume','ls','-q','--filter','label=com.docker.compose.project=fixture']:
        print('' if state.exists() else volume)
    elif a[:5]==['network','ls','-q','--filter','label=com.docker.compose.project=fixture']:
        print('' if state.exists() else nid)
    elif a[:2]==['volume','inspect']:
        print(json.dumps([{'Name':volume,'Labels':{'com.docker.compose.project':project,'com.docker.compose.volume':'lottery_data'}}]))
    elif a[:2]==['network','inspect']:
        print(json.dumps([{'Id':nid,'Name':network,'Labels':{'com.docker.compose.project':project,
          'com.docker.compose.network':'backend'},'Containers':{cid:{}}}]))
    elif a[:2]==['rm',cid]: state.touch()
    elif a[:2]==['run','--rm'] and 'node:22-bookworm-slim' in a and ':/work/frontend' in ' '.join(a):
        dist=root/'frontend/dist'; dist.mkdir(exist_ok=True); (dist/'index.html').write_text('new frontend')
    elif a[:2]==['compose','run'] and 'shell' in a: print('EMPTY')
    sys.exit(0)
if a == ['info']: sys.exit(0)
if a[:1] == ['run'] and any(x.startswith('sha256:') for x in a) and os.environ.get('UPGRADE_IMAGE_FAIL'):
    print('docker: No such image',file=sys.stderr); sys.exit(1)
if a[:2] == ['context','inspect']:
    print('tcp://remote:2376' if os.environ.get('UPGRADE_REMOTE_DOCKER') else 'unix:///var/run/docker.sock')
if a[:1] == ['run'] and any(x.endswith('node:22-bookworm-slim') for x in a):
    dist=pathlib.Path(os.environ['UPGRADE_PROJECT'])/'frontend'/'dist'
    if not os.environ.get('UPGRADE_REQUIRE_OFFLINE_FRONTEND') or pathlib.Path(os.environ['UPGRADE_TIMER_STOPPED']).exists():
        dist.mkdir(parents=True,exist_ok=True); (dist/'index.html').write_text('fixture')
    else: print('frontend built while live',file=sys.stderr); sys.exit(1)
if a[:2] == ['pull','node:22-bookworm-slim'] and os.environ.get('UPGRADE_NEW_IMAGE_FAIL'):
    sys.exit(1)
if a[:3] == ['compose', 'config', '--quiet']: sys.exit(0)
if a[:3] == ['compose', 'config', '--format']:
    print(json.dumps({'name':'fixture','services':{
      'app':{'environment':{'LOTTERY_DB_PATH':'/app/data/history_v6.sqlite3','LOTTERY_DATA_DIR':'/app/data','LOTTERY_JOBS_DIR':'/app/data/jobs_v6','LOTTERY_EXPORTS_DIR':'/app/data/exports_v6'},'ports':[],
        'networks':{'backend':{}},'volumes':[
        {'type':'volume','source':'lottery_data','target':'/app/data'},
        {'type':'volume','source':'lottery_backups','target':'/app/backups'}]},
      'caddy':{'networks':{'default':{},'backend':{'ipv4_address':'172.30.96.2'}},'volumes':[{'type':'volume','source':'caddy_data','target':'/data'},
        {'type':'volume','source':'caddy_config','target':'/config'}]}},
      'networks':{'backend':{'internal':True,'ipam':{'config':[{'subnet':'172.30.96.0/24','ip_range':'172.30.96.128/25','gateway':'172.30.96.1'}]}}},
      'volumes':{n:{'name':'fixture_'+n} for n in ('lottery_data','lottery_backups','caddy_data','caddy_config')}}))
elif a[:2] == ['ps', '-q']:
    print('a11a11a11a11' if 'service=app' in ' '.join(a) else 'cadd11cadd11')
elif a[:2] == ['ps','-aq']:
    if os.environ.get('UPGRADE_PS_FAIL'): sys.exit(1)
    if os.environ.get('UPGRADE_NO_CONTAINERS'): pass
    elif 'service=app' in ' '.join(a): print('a11a11a11a11')
    elif 'service=caddy' in ' '.join(a): print('cadd11cadd11')
    elif any(x.startswith('volume=') for x in a): print('bad123' if os.environ.get('UPGRADE_SHARED_VOLUME') else 'a11a11a11a11\ncadd11cadd11')
    else: print('a11a11a11a11\ncadd11cadd11' + ('\nother123' if os.environ.get('UPGRADE_OTHER') else ''))
elif a[:2] == ['ps', '-a']:
    print('a11a11a11a11\ncadd11cadd11' + ('\nother123' if os.environ.get('UPGRADE_OTHER') else ''))
elif a[:1] == ['inspect']:
    if '--format' in a:
        fmt=a[a.index('--format')+1]
        print('sha256:'+'1'*64 if '.Image' in fmt else ('true' if 'Running' in fmt else ('true' if os.environ.get('UPGRADE_PAUSED') else 'false')))
        sys.exit(0)
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
        'com.docker.compose.project.working_dir':os.environ['UPGRADE_PROJECT'],'com.docker.compose.service':service},
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
    if os.environ.get('UPGRADE_OLD_SAMPLING') and 'probe' in a and str(os.environ['UPGRADE_OLD_SAMPLING']) != a[-1]:
      print('目标版本与原任务不兼容；保留原现场',file=sys.stderr); sys.exit(1)
    if (fail == 'probe' and 'probe' in a) or (fail == 'backup' and 'backup' in a):
      print('simulated helper failure',file=sys.stderr); sys.exit(1)
elif a[0:1] == ['cp'] and a[1].startswith('a11a11a11a11:/app/backups/'):
    import sqlite3
    destination=a[-1]
    if destination.startswith('/var/backups/'):
        destination=str(pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/'source.sqlite3')
    db=sqlite3.connect(destination); db.execute('create table snapshot(value)'); db.commit(); db.close()
elif a[0:1] == ['cp'] and a[1]=='a11a11a11a11:/app/data/.':
    pathlib.Path(a[-1]).mkdir()
elif a[:2] == ['compose','run']:
    if 'backup' in a:
        sys.stdin.read()
        if os.environ.get('UPGRADE_RESTORE_BAD'): sys.exit(1)
    fail = os.environ.get('UPGRADE_RUN_FAIL')
    if fail and fail in a: print('simulated command failure',file=sys.stderr); sys.exit(1)
elif a[:2] == ['compose','pull'] and os.environ.get('UPGRADE_NEW_IMAGE_FAIL'):
    sys.exit(1)
elif a[:2] == ['volume','inspect']:
    name=a[2].removeprefix('fixture_')
    print(json.dumps([{'Labels':{'com.docker.compose.project':'foreign' if os.environ.get('UPGRADE_FOREIGN_VOLUME') else 'fixture','com.docker.compose.volume':name}}]))
'''

FAKE_GIT = r'''#!/usr/bin/env python3
import json,os,sys
a=sys.argv[1:]
with open(os.environ['UPGRADE_CALLS'],'a') as f: f.write(json.dumps(['git',*a])+'\n')
if a==['rev-parse','--show-toplevel']: print(os.environ['UPGRADE_PROJECT'])
elif a==['branch','--show-current']: print('other' if os.environ.get('UPGRADE_BRANCH_FAIL') else 'master')
elif a==['status','--porcelain']: print(' M changed' if os.environ.get('UPGRADE_DIRTY') else '',end='')
elif a==['remote','get-url','origin']: print('https://example.invalid/other.git' if os.environ.get('UPGRADE_ORIGIN_FAIL') else 'https://github.com/donotwantorange/lottery_simulator.git')
elif a==['rev-parse','HEAD']: print('fixture-commit')
elif a[:1]==['pull'] and os.environ.get('UPGRADE_GIT_FAIL'): sys.exit(1)
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
    if os.environ.get('UPGRADE_SYSTEMCTL_FAIL') and prop==os.environ['UPGRADE_SYSTEMCTL_FAIL']: sys.exit(1)
    if prop=='LoadState': print(os.environ.get('UPGRADE_TIMER_LOAD','loaded') if unit.endswith('.timer') else os.environ.get('UPGRADE_SERVICE_LOAD','loaded'))
    elif prop=='FragmentPath': print('/etc/systemd/system/'+unit)
    elif prop=='DropInPaths': print('custom.conf' if os.environ.get('UPGRADE_CUSTOM_UNIT') else '')
    elif prop=='NeedDaemonReload': print('no')
    elif prop=='WorkingDirectory': print(os.environ.get('UPGRADE_UNIT_DIRECTORY',os.environ['UPGRADE_PROJECT']))
    elif prop=='ExecStart': print(os.environ.get('UPGRADE_EXEC_START','/bin/sh -c /usr/bin/docker compose exec -T app python3 scripts/backup_db.py /app/data/history_v6.sqlite3 /app/backups/lottery-v6-$(date +%F).sqlite3'))
    elif prop=='Unit': print(os.environ.get('UPGRADE_TIMER_UNIT','lottery-backup.service'))
    elif prop=='Result': print('failed' if os.environ.get('UPGRADE_SERVICE_FAIL') else 'success')
    elif unit=='lottery-backup.timer': print('inactive' if pathlib.Path(os.environ['UPGRADE_TIMER_STOPPED']).exists() else 'active')
    else: print(os.environ.get('UPGRADE_SERVICE_STATE','inactive'))
elif name=='install':
  p=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT']); p.mkdir(parents=True,exist_ok=True)
elif name=='mktemp':
  template=a[-1]; d=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/(template.rsplit('/',1)[-1].rsplit('-',1)[0]+'-fixture01'); d.mkdir(parents=True); print(d)
elif name=='cp':
  src=pathlib.Path(a[-2]); dst=pathlib.Path(a[-1]);
  if str(dst).startswith('/var/backups/'): dst=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/dst.name
  shutil.copy2(src,dst)
elif name=='tee':
  data=sys.stdin.read(); p=pathlib.Path(a[-1]);
  if str(p).startswith('/var/backups/'): p=pathlib.Path(os.environ['UPGRADE_BACKUP_ROOT'])/p.name
  p.write_text(data); print(data,end='')
elif name=='tar':
  if '-czf' in a:
    if os.environ.get('UPGRADE_TAR_FAIL'): sys.exit(1)
    p=pathlib.Path(a[a.index('-czf')+1])
    with tarfile.open(p,'w:gz') as archive:
      archive.add(pathlib.Path(os.environ['UPGRADE_PROJECT'])/'frontend/dist',arcname='frontend/dist')
  elif '-tzf' in a:
    with tarfile.open(a[a.index('-tzf')+1]) as archive: archive.getmembers()
elif name=='cmp':
  installed=pathlib.Path(os.environ['UPGRADE_INSTALLED_UNITS'])/pathlib.Path(a[-1]).name
  if os.environ.get('UPGRADE_CUSTOM_BODY') or pathlib.Path(a[-2]).read_bytes()!=installed.read_bytes(): sys.exit(1)
elif name=='chmod': pass
'''


class UpgraderTest(unittest.TestCase):
    def run_upgrade(self, answers=b'UPGRADE\n', arguments=('--upgrade',), shell_body=None, **flags):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'scripts').mkdir(); (root/'bin').mkdir()
            for name in ('install.sh','upgrade.sh','manage.sh','upgrade_probe.py','check_proxy_network.py','deployment_checks.sh','deployment_resources.py'):
                if (SOURCE/'scripts'/name).exists(): shutil.copy2(SOURCE/'scripts'/name,root/'scripts'/name)
            # All successful purge filesystem operations stay inside this temporary project.
            with (root/'scripts/manage.sh').open('a') as f:
                f.write(r'''
management_private() {
  [[ $2 == /var/backups/lottery/fixture ]] || exit 1
  [[ ${UPGRADE_REDIRECTED_BACKUP:-} != 1 ]] || exit 1
  if [[ $1 == delete ]]; then
    python3 -c 'from pathlib import Path; import sys; Path(sys.argv[1]).unlink()' "$3"
  fi
}
management_legacy_ports() { :; }
''')
            for name in ('docker-compose.yml','Dockerfile','Caddyfile','manage.py','requirements.txt','configs/pools/default.json',
                         'configs/rules/zmd.json','frontend/package.json','frontend/package-lock.json','scripts/backup_db.py'):
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            formats=root/'lottery_simulator/formats.py'; formats.parent.mkdir(parents=True)
            shutil.copy2(SOURCE/'lottery_simulator/formats.py',formats)
            (root/'Caddyfile').write_text('fixture.example { reverse_proxy app:8000 }\n')
            (root/'deploy').mkdir()
            for unit in ('lottery-backup.service','lottery-backup.timer'):
                shutil.copy2(SOURCE/'deploy'/unit,root/'deploy'/unit)
            if not flags.get('UPGRADE_STANDARD_UNIT'):
                service=root/'deploy/lottery-backup.service'
                service.write_text(service.read_text().replace('/opt/lottery-simulator',str(root)))
            (root/'installed-units').mkdir()
            for unit in ('lottery-backup.service','lottery-backup.timer'):
                shutil.copy2(root/'deploy'/unit,root/'installed-units'/unit)
            env_file=root/'.env'; env_file.write_text('DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            calls=root/'calls'; helpers=root/'helpers'
            (root/'bin/docker').write_text(FAKE_DOCKER); (root/'bin/docker').chmod(0o755)
            (root/'bin/git').write_text(FAKE_GIT); (root/'bin/git').chmod(0o755)
            for name in ('systemctl','install','mktemp','cp','tee','tar','chmod','journalctl','cmp'):
                p=root/'bin'/name; p.write_text(FAKE_SYSTEM); p.chmod(0o755)
            (root/'frontend/dist').mkdir(parents=True); (root/'frontend/dist/index.html').write_text('old frontend')
            (root/'bin/python3').symlink_to(sys.executable)
            (root/'bin/ip').write_text('#!/usr/bin/env python3\nimport json,os\nprint(json.dumps([{\"dst\":\"172.30.96.0/24\",\"dev\":\"foreign\"}] if os.environ.get(\"UPGRADE_NETWORK_CONFLICT\") else []))\n'); (root/'bin/ip').chmod(0o755)
            (root/'bin/sudo').write_text('#!/bin/sh\nif [ "$1" = "-v" ]; then exit 0; fi\nexec "$@"\n'); (root/'bin/sudo').chmod(0o755)
            (root/'bin/nano').write_text('#!/bin/sh\nexit 0\n'); (root/'bin/nano').chmod(0o755)
            env={**{k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT'}},'PATH':str(root/'bin')+':'+os.environ['PATH'],
                 'UPGRADE_CALLS':str(calls),'UPGRADE_HELPERS':str(helpers),
                 'UPGRADE_TIMER_STOPPED':str(root/'timer-stopped'),
                 'UPGRADE_BACKUP_ROOT':str(root/'backup-root'),'UPGRADE_PROJECT':str(root),
                 'UPGRADE_INSTALLED_UNITS':str(root/'installed-units'),**flags}
            master,slave=pty.openpty()
            try:
                command=(['bash','-c',shell_body,'bash',str(root/'scripts/manage.sh')] if shell_body else ['bash',str(root/'scripts/install.sh'),*arguments])
                proc=subprocess.Popen(command,cwd=root,
                    stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
                os.write(master,answers); out,_=proc.communicate(timeout=25)
            finally: os.close(master); os.close(slave)
            cmds=[json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
            helper=[json.loads(x) for x in helpers.read_text().splitlines()] if helpers.exists() else []
            if flags.get('UPGRADE_EXPECT_NEW_ENV'):
                if env_file.exists():
                    self.assertNotIn('SECRET_KEY=unchanged',env_file.read_text())
                    if proc.returncode==0:
                        self.assertIn('COMPOSE_PROJECT_NAME=fixture\n',env_file.read_text())
                        self.assertIn('LOTTERY_PROXY_SUBNET=172.30.96.0/24\n',env_file.read_text())
            elif flags.get('UPGRADE_EXPECT_PURGE') and proc.returncode==0: self.assertFalse(env_file.exists())
            else: self.assertEqual(env_file.read_text(),'DOMAIN=fixture.example\nSECRET_KEY=unchanged\n')
            return proc.returncode,out.decode(errors='replace'),cmds,helper

    def test_v6_completes_without_v5_import_or_init(self):
        code,out,calls,helpers=self.run_upgrade()
        self.assertEqual(code,0,out)
        self.assertTrue(any('migrate' in c for c in calls))
        self.assertFalse(any('import_v5_accounts' in c or 'init_business_defaults' in c for c in calls))
        self.assertTrue(any(c[:3]==['compose','up','-d'] for c in calls))
        self.assertTrue(any('probe' in h['args'] for h in helpers))
        self.assertEqual(sum('probe' in h['args'] for h in helpers),2)
        self.assertTrue(all(h['args'][-2:]==['4','3'] for h in helpers))

    def test_v5_is_rejected_before_service_changes(self):
        code,out,calls,_=self.run_upgrade(answers=b'ACCOUNTS\nUPGRADE\n',UPGRADE_VERSION='5')
        self.assertNotEqual(code,0,out)
        self.assertIn('v5',out)
        self.assertFalse(any(c[:1] in (['stop'],['pause'],['rm']) or c[:2]==['compose','down'] or 'import_v5_accounts' in c for c in calls))

    def test_old_sampling_blocks_before_timer_or_caddy_changes(self):
        code,out,calls,helpers=self.run_upgrade(UPGRADE_OLD_SAMPLING='2')
        self.assertNotEqual(code,0,out)
        self.assertIn('保留原现场',out)
        self.assertTrue(any('probe' in h['args'] for h in helpers))
        self.assertFalse(any(c[:3]==['system','systemctl','stop'] or c[:2]==['compose','stop'] or c[:1]==['pause'] for c in calls))

    def test_unusable_old_image_stops_before_maintenance(self):
        code,out,calls,_=self.run_upgrade(UPGRADE_IMAGE_FAIL='1')
        self.assertNotEqual(code,0,out)
        self.assertIn('尚未暂停备份或停止网站',out)
        self.assertFalse(any(c[:2] in (['compose','stop'],['compose','down'],['compose','up']) or c[:1] in (['pause'],['rm']) for c in calls))
        self.assertFalse(any(c[:2]==['system','systemctl'] or c[:2]==['system','mktemp'] for c in calls))
        preflight=next(c for c in calls if c[:1]==['run'])
        self.assertIn('never',preflight)
        self.assertNotIn('-v',preflight)

    def test_preflight_and_backup_failures_stop_before_compose_down(self):
        for flags in ({'UPGRADE_HELPER_FAIL':'probe'},{'UPGRADE_HELPER_FAIL':'backup'}, {'UPGRADE_TAR_FAIL':'1'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertFalse(any(c[:2]==['compose','down'] for c in calls))
                self.assertNotIn(['rm','--force','a11a11a11a11'],calls)
                self.assertFalse(any(c[:2]==['compose','up'] for c in calls))
                if flags.get('UPGRADE_HELPER_FAIL')=='backup' or flags.get('UPGRADE_TAR_FAIL'):
                    self.assertIn(['unpause','a11a11a11a11'],calls)

    def test_import_and_migration_failures_stop_before_down_or_up(self):
        for version,answers,fail in [('6',b'UPGRADE\n','migrate')]:
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
        self.assertFalse(any(c[:1] in (['git'],['apt-get']) or c[:2]==['volume','rm'] for c in calls))
        self.assertLess(calls.index(['compose','build','app']),calls.index(['system','systemctl','stop','lottery-backup.timer']))
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
        self.assertFalse(any('migrate' in c or c[:2]==['compose','up'] for c in calls))

    def test_no_timer_does_not_create_or_start_one(self):
        code,out,calls,_=self.run_upgrade(UPGRADE_TIMER_LOAD='not-found')
        self.assertEqual(code,0,out)
        self.assertFalse(any(c[:3]==['system','systemctl','stop'] or c[:3]==['system','systemctl','start'] for c in calls))

    def test_no_timer_rejects_active_or_foreign_service(self):
        for flags in ({'UPGRADE_SERVICE_STATE':'active'}, {'UPGRADE_UNIT_DIRECTORY':'/opt/other'}):
            code,out,calls,_=self.run_upgrade(UPGRADE_TIMER_LOAD='not-found',**flags)
            self.assertNotEqual(code,0,out)
            self.assertFalse(any(c[:3]==['system','systemctl','stop'] or c[:2]==['compose','stop'] for c in calls))

    def test_foreign_or_unreadable_timer_never_changes_services(self):
        for flags in ({'UPGRADE_UNIT_DIRECTORY':'/opt/other'}, {'UPGRADE_TIMER_UNIT':'other.service'},
                      {'UPGRADE_CUSTOM_UNIT':'1'}, {'UPGRADE_CUSTOM_BODY':'1'},
                      {'UPGRADE_SYSTEMCTL_FAIL':'LoadState'},
                      {'UPGRADE_EXEC_START':'/usr/bin/docker compose exec app /other/project.py'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertFalse(any(c[:3] in (['system','systemctl','stop'],['system','systemctl','disable'],['system','systemctl','start']) or c[:2]==['compose','stop'] for c in calls))

    def test_new_image_failure_and_live_frontend_remain_before_maintenance(self):
        code,out,calls,_=self.run_upgrade(UPGRADE_NEW_IMAGE_FAIL='1')
        self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[:3]==['system','systemctl','stop'] or c[:2]==['compose','stop'] for c in calls))
        code,out,calls,_=self.run_upgrade(UPGRADE_REQUIRE_OFFLINE_FRONTEND='1')
        self.assertEqual(code,0,out)

    def test_remote_daemon_cannot_use_local_host_route_checks(self):
        for flags in ({'UPGRADE_REMOTE_DOCKER':'1'}, {'UPGRADE_REMOTE_DOCKER':'1', 'DOCKER_CONTEXT':'remote', 'DOCKER_HOST':'unix:///var/run/docker.sock'}):
            with self.subTest(flags=flags):
                code,out,calls,_=self.run_upgrade(**flags)
                self.assertNotEqual(code,0,out)
                self.assertNotIn(['info'],calls)
                self.assertFalse(any(c[:2] in (['compose','stop'],['compose','down'],['compose','up']) for c in calls))

    def test_menu_exit_does_not_call_docker(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'0\n')
        self.assertEqual(code,0,out); self.assertEqual(calls,[])

    def test_menu_starts_original_containers_without_new_build(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'3\n1\n',UPGRADE_VERSION='5')
        self.assertEqual(code,0,out)
        self.assertIn(['start','a11a11a11a11'],calls); self.assertIn(['start','cadd11cadd11'],calls)
        self.assertFalse(any(c[:1]==['compose'] and c[1] in {'up','build','run'} for c in calls))

    def test_menu_can_unpause_original_app(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'3\n1\nUNPAUSE\n',UPGRADE_PAUSED='1')
        self.assertEqual(code,0,out); self.assertIn(['unpause','a11a11a11a11'],calls)

    def test_menu_stop_or_restart_checks_tasks(self):
        for operation in ('2','3'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=f'3\n{operation}\nSTOP\n'.encode(),UPGRADE_TIMER_LOAD='not-found')
            self.assertEqual(code,0,out)
            self.assertIn(['stop','cadd11cadd11'],calls); self.assertIn(['stop','--timeout','120','a11a11a11a11'],calls)
            if operation=='3': self.assertIn(['start','a11a11a11a11'],calls)
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'3\n2\nSTOP\n',UPGRADE_TIMER_LOAD='not-found',UPGRADE_HELPER_FAIL='probe')
        self.assertNotEqual(code,0,out)
        self.assertNotIn(['stop','--timeout','120','a11a11a11a11'],calls)

    def test_menu_backup_uses_actual_v5_or_v6_path(self):
        for version in ('5','6'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=b'3\n6\n',UPGRADE_VERSION=version)
            self.assertEqual(code,0,out)
            self.assertTrue(any(c[:3]==['exec','a11a11a11a11','python3'] and f'/app/data/history_v{version}.sqlite3' in c for c in calls))

    def test_menu_retained_uninstall_never_removes_volumes(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'2\n1\nUNINSTALL\n',UPGRADE_TIMER_LOAD='not-found')
        self.assertEqual(code,0,out); self.assertIn(['rm','a11a11a11a11','cadd11cadd11'],calls)
        self.assertFalse(any(c[:2]==['volume','rm'] for c in calls))
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'2\n1\nUNINSTALL\n',UPGRADE_TIMER_LOAD='not-found',UPGRADE_IMAGE_FAIL='1')
        self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[:1] in (['stop'],['rm']) for c in calls))

    def test_menu_permanent_uninstall_requires_both_confirmations(self):
        for answer in (b'NO\n',b'UNINSTALL\nNO\n'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=b'2\n2\n'+answer,UPGRADE_TIMER_LOAD='not-found',UPGRADE_LEGACY_SUCCESS='1')
            self.assertNotEqual(code,0,out)
            self.assertFalse(any(c[:1] in (['stop'],['rm']) or c[:2]==['volume','rm'] for c in calls))
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'2\n2\nUNINSTALL\nDELETE-fixture\n',UPGRADE_TIMER_LOAD='not-found',UPGRADE_LEGACY_SUCCESS='1',UPGRADE_EXPECT_PURGE='1')
        self.assertEqual(code,0,out)
        self.assertIn(['rm','a'*64],calls)
        self.assertIn(['volume','rm','fixture_lottery_data'],calls)
        self.assertFalse(any(c[:1]==['run'] and any(x.startswith('sha256:') for x in c) for c in calls))

    def test_menu_unknown_legacy_resources_are_left_untouched(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'2\n2\nUNINSTALL\nDELETE-fixture\n',UPGRADE_TIMER_LOAD='not-found')
        self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[:1] in (['stop'],['rm']) or c[:2]==['volume','rm'] for c in calls))

    def test_menu_downloaded_legacy_reinstall_reaches_fresh_admin(self):
        answers=b'4\n4\nUNINSTALL\nDELETE-fixture\nn\nfixture.example\nadmin-fixture\n'
        code,out,calls,_=self.run_upgrade(arguments=(),answers=answers,UPGRADE_TIMER_LOAD='not-found',
            UPGRADE_LEGACY_SUCCESS='1',UPGRADE_EXPECT_NEW_ENV='1')
        self.assertEqual(code,0,out)
        self.assertLess(calls.index(['volume','rm','fixture_lottery_data']),
            next(i for i,c in enumerate(calls) if 'init_admin' in c))
        self.assertTrue(any('init_admin' in c for c in calls))

    def test_menu_git_legacy_reinstall_fetches_before_removal(self):
        answers=b'4\n3\nUPDATE\nUNINSTALL\nDELETE-fixture\nn\nfixture.example\nadmin-fixture\n'
        code,out,calls,_=self.run_upgrade(arguments=(),answers=answers,UPGRADE_TIMER_LOAD='not-found',
            UPGRADE_LEGACY_SUCCESS='1',UPGRADE_EXPECT_NEW_ENV='1')
        self.assertEqual(code,0,out)
        self.assertLess(calls.index(['git','pull','--ff-only','origin','master']),
                        calls.index(['rm','a'*64]))

    def test_menu_legacy_network_conflict_blocks_before_confirmation(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'4\n4\n',
            UPGRADE_LEGACY_SUCCESS='1',UPGRADE_NETWORK_CONFLICT='1')
        self.assertNotEqual(code,0,out)
        self.assertIn('代理网络预检失败',out)
        self.assertFalse(any(c[:1] in (['stop'],['rm']) or c[:2] in
                             (['network','rm'],['volume','rm']) for c in calls))

    def test_menu_update_reexecutes_downloaded_upgrade(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'4\n1\nUPDATE\nUPGRADE\n')
        self.assertEqual(code,0,out); self.assertIn(['git','pull','--ff-only','origin','master'],calls)
        self.assertTrue(any('migrate' in c for c in calls))

    def test_menu_git_failure_or_dirty_tree_never_stops_services(self):
        for flag in ('UPGRADE_DIRTY','UPGRADE_GIT_FAIL','UPGRADE_BRANCH_FAIL','UPGRADE_ORIGIN_FAIL'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=b'4\n1\nUPDATE\nUPGRADE\n',**{flag:'1'})
            self.assertNotEqual(code,0,out)
            self.assertFalse(any(c[:2]==['compose','stop'] or c[:1] in (['stop'],['pause']) for c in calls))

    def test_private_deletion_rejects_path_outside_fixed_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=Path(tmp)/'.env'; env.write_text('keep')
            script='set -Eeuo pipefail; source "$1"; admin=(); management_private delete "$2" "$3"'
            result=subprocess.run(['bash','-c',script,'bash',str(SOURCE/'scripts/manage.sh'),tmp,str(env)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(env.read_text(),'keep')

    def test_schedule_requires_v6_and_standard_location(self):
        for version in ('5','6'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=b'3\n7\nBACKUP\nVERIFIED\n',UPGRADE_VERSION=version)
            self.assertNotEqual(code,0,out)
            self.assertFalse(any(c[:3]==['system','install','-m'] or c[:3]==['system','systemctl','enable'] for c in calls))

    def test_schedule_and_resume_only_enable_after_successful_backup(self):
        shell=r'''set -Eeuo pipefail; source "$1"; admin=(); source_version=6; project_dir=/opt/lottery-simulator; project_name=lottery-simulator
command() { if [[ $1 == -v && $2 == docker ]]; then echo /usr/bin/docker; else builtin command "$@"; fi; }
test() { return 1; }
management_schedule
'''
        for flags in ({},{'UPGRADE_SERVICE_FAIL':'1'},{'UPGRADE_CUSTOM_UNIT':'1'}):
            code,out,calls,_=self.run_upgrade(shell_body=shell,answers=b'BACKUP\nVERIFIED\n',UPGRADE_STANDARD_UNIT='1',UPGRADE_UNIT_DIRECTORY='/opt/lottery-simulator',**flags)
            enabled=['system','systemctl','enable','--now','lottery-backup.timer']
            if flags:
                self.assertNotEqual(code,0,out); self.assertNotIn(enabled,calls)
            else:
                self.assertEqual(code,0,out); self.assertIn(enabled,calls)
                self.assertLess(calls.index(['system','systemctl','start','lottery-backup.service']),calls.index(enabled))

    def test_status_and_logs_are_read_only(self):
        for option in ('4','5'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=f'3\n{option}\n'.encode())
            self.assertEqual(code,0,out)
            self.assertFalse(any(c[:1] in (['stop'],['start'],['rm'],['run']) or c[:2]==['volume','rm'] for c in calls))

    def test_retained_v6_reinstall_backs_up_before_migrate_without_init(self):
        code,out,calls,_=self.run_upgrade(arguments=(),answers=b'1\n2\nRESTORE\n',UPGRADE_NO_CONTAINERS='1')
        self.assertEqual(code,0,out)
        backup=next(i for i,c in enumerate(calls) if 'backup' in c)
        migration=next(i for i,c in enumerate(calls) if 'migrate' in c)
        self.assertLess(backup,migration)
        self.assertFalse(any('init_admin' in c or 'init_business_defaults' in c for c in calls))

    def test_retained_reinstall_rejects_live_containers_and_invalid_data(self):
        for flags in ({},{'UPGRADE_NO_CONTAINERS':'1','UPGRADE_RESTORE_BAD':'1'},{'UPGRADE_NO_CONTAINERS':'1','UPGRADE_FOREIGN_VOLUME':'1'}):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=b'1\n2\nRESTORE\n',**flags)
            self.assertNotEqual(code,0,out)
            self.assertFalse(any('migrate' in c or 'init_admin' in c or c[:2]==['compose','up'] for c in calls))

    def test_unreadable_container_list_never_permits_management_or_restore(self):
        for answers in (b'2\n2\nUNINSTALL\nDELETE-fixture\n', b'1\n2\nRESTORE\n'):
            code,out,calls,_=self.run_upgrade(arguments=(),answers=answers,UPGRADE_PS_FAIL='1')
            self.assertNotEqual(code,0,out)
            self.assertFalse(any(c[:1] in (['stop'],['rm'],['start']) or c[:2] in (['volume','rm'],['compose','build']) for c in calls))


if __name__=='__main__':
    unittest.main()
