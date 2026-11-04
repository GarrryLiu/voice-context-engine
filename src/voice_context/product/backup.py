"""Consistent SQLite snapshots, including sources, versions and map evidence.

Restore into a NEW path while the application is stopped; existing files are
never overwritten. SQLite's backup API includes committed WAL transactions.
"""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if destination.exists():
        raise FileExistsError('Destination already exists; choose a new path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.voiceline-backup-', dir=destination.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(temporary)) as copy:
                original.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Database integrity check failed')
        with open(temporary, 'rb') as file:
            os.fsync(file.fileno())
        # Atomic publication without a check/overwrite race.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    try:
        path = snapshot(args.source, args.destination)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'Backup failed ({type(error).__name__}); destination was not overwritten.\n')
    print(f'Verified database snapshot: {path}')


if __name__ == '__main__':
    main()
