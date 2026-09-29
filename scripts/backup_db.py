"""Back up SQLite online: python3 scripts/backup_db.py SOURCE DESTINATION.

The database may contain account password hashes and sessions; backups are
therefore created with owner-only permissions.
"""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and source.samefile(destination)):
        raise ValueError("Source and destination refer to the same file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.touch(mode=0o600, exist_ok=True)
    destination.chmod(0o600)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            result = snapshot.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise ValueError(f"Backup integrity_check failed: {result}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    try:
        backup_database(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Backup failed: {error}\n")
    print("Backup integrity_check: ok")
