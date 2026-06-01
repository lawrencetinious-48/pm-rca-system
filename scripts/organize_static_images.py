#!/usr/bin/env python3
"""
Move and organize static logo images into `static/images/` and normalize filenames.
Run this from the project root: `python scripts/organize_static_images.py`
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'static'
TARGET = STATIC / 'images'
TARGET.mkdir(parents=True, exist_ok=True)

mappings = [
    ('airtel logo.webp', 'airtel-logo.webp'),
    ('soliton-telmec.png', 'soliton-telmec.png'),
    ('soliton-telmec.jpeg', 'soliton-telmec.jpeg'),
]

moved = []
for src_name, dst_name in mappings:
    src = STATIC / src_name
    dst = TARGET / dst_name
    if src.exists():
        try:
            shutil.move(str(src), str(dst))
            moved.append((src_name, str(dst_name)))
        except Exception as e:
            print(f"Failed to move {src_name}: {e}")
    else:
        # already moved or not present
        if (TARGET / dst_name).exists():
            print(f"{dst_name} already present in {TARGET}")
        else:
            print(f"{src_name} not found, skipping")

if moved:
    print("Moved files:")
    for s,d in moved:
        print(f" - {s} -> {d}")
else:
    print("No files moved. Check existing files in static/ and static/images/.")
