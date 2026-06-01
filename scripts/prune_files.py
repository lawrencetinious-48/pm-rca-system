#!/usr/bin/env python3
"""
Delete non-essential files and directories after confirmation.
Use with caution. This will permanently remove files listed.

Usage:
  python scripts/prune_files.py --dry-run
  python scripts/prune_files.py --delete
"""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
candidates = [
    ROOT / 'logs',
    ROOT / 'uploads',
    ROOT / 'instance',
    ROOT / 'backups',
    ROOT / '.env',
    ROOT / '.env.prod',
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--delete', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def main():
    args = parse_args()
    print('Planned deletions:')
    for p in candidates:
        print('-', p)
    if args.dry_run:
        print('Dry run only. No changes made.')
        return 0
    if not args.delete:
        print('Pass --delete to actually remove the files.')
        return 2
    confirm = input('Type DELETE to confirm: ')
    if confirm != 'DELETE':
        print('Confirmation mismatch — aborting.')
        return 3
    for p in candidates:
        try:
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p)
                    print(f'Removed directory {p}')
                else:
                    p.unlink()
                    print(f'Removed file {p}')
            else:
                print(f'Not found: {p}')
        except Exception as e:
            print(f'Failed to remove {p}: {e}')
    print('Prune complete.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
