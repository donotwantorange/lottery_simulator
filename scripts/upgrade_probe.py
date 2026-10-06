"""Run via stdin inside the OLD app container; use that image's job validator."""

import os
from pathlib import Path
import sqlite3
import stat
import sys
from uuid import UUID


def check(version, root=Path('/app/data'), processes=Path('/proc')):
    from dashboard.job_models import JobState, read_json

    database = root / f'history_v{version}.sqlite3'
    if not stat.S_ISREG(database.lstat().st_mode):
        raise ValueError('数据库不是普通文件')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != version:
            raise ValueError('数据库版本与运行容器路径不一致')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('数据库完整性检查失败')
        if db.execute('SELECT COUNT(*) FROM users WHERE deleting=1').fetchone()[0]:
            raise ValueError('存在删除中的账号')
        if db.execute("SELECT COUNT(*) FROM app_meta WHERE key LIKE 'account_deletion:%'").fetchone()[0]:
            raise ValueError('存在未完成的账号删除清单')
        if not db.execute('SELECT COUNT(*) FROM users WHERE is_superuser=1 AND is_active=1 AND deleting=0').fetchone()[0]:
            raise ValueError('没有可用管理员')
    jobs = root / f'jobs_v{version}'
    if not stat.S_ISDIR(jobs.lstat().st_mode):
        raise ValueError('任务根目录不安全')
    for directory in jobs.iterdir():
        if directory.name == 'active.lock' and stat.S_ISREG(directory.lstat().st_mode):
            continue
        if str(UUID(directory.name)) != directory.name or not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError('任务目录包含未知或不安全的条目')
        state_path = directory / 'state.json'
        if not stat.S_ISREG(state_path.lstat().st_mode):
            raise ValueError('任务状态文件不安全')
        state = JobState.from_dict(read_json(state_path))
        if state.job_id != directory.name or state.status in {'queued', 'running'}:
            raise ValueError('仍有活动任务或任务身份不一致')
    for proc in processes.iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            args = (proc / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        if b'run_job' in args:
            raise ValueError('仍有任务worker进程')
    if version == 5:
        if any(root.glob('history_v6.sqlite3*')):
            raise ValueError('已有v6目标库；拒绝自动覆盖或续跑')
        for name in ('jobs_v6', 'exports_v6'):
            path = root / name
            if path.exists() or path.is_symlink():
                if not stat.S_ISDIR(path.lstat().st_mode) or any(path.iterdir()):
                    raise ValueError('已有v6目标任务或导出材料')


def main():
    action, raw_version = sys.argv[1:3]
    if raw_version not in {'5', '6'} or action not in {'probe', 'backup'}:
        raise ValueError('升级参数无效')
    version = int(raw_version)
    check(version)
    if action == 'backup':
        from scripts.backup_db import backup_database

        destination = Path(sys.argv[3])
        if destination.parent != Path('/app/backups') or not destination.name.startswith('upgrade-'):
            raise ValueError('备份路径无效')
        os.umask(0o077)
        destination.mkdir(mode=0o700)  # Existing snapshots are never overwritten.
        backup_database(Path(f'/app/data/history_v{version}.sqlite3'), destination / 'source.sqlite3')
    print(f'v{version}数据与任务检查通过')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, sqlite3.Error, ImportError) as error:
        print(f'升级预检或备份失败：{error}', file=sys.stderr)
        sys.exit(1)
