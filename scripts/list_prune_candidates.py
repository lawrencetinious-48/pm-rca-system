#!/usr/bin/env python3
"""
List candidate files and directories for cleanup (logs, uploads, instance sqlite, backups).
This script only lists; use prune_files.py --delete to actually remove after review.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
candidates = [
    ROOT / 'logs',
    ROOT / 'uploads',
    ROOT / 'instance',
    ROOT / 'backups',
    ROOT / '.env',
    ROOT / '.env.prod',
    ROOT / 'tests'  # keep tests but user may want to delete; listing for review
]

print('Candidate cleanup items:')
for p in candidates:
    exists = p.exists()
    size = None
    if exists:
        try:
            if p.is_file():
                size = p.stat().st_size
            else:
                size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        except Exception:
            size = None
    print(f"- {p} | exists={exists} | approx_bytes={size}")

print('\nReview the list above. To actually delete, run scripts/prune_files.py --delete')
