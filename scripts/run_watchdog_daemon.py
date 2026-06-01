#!/usr/bin/env python3
"""
Run the Watchdog in foreground (daemon-like). Logs to `logs/watchdog.log`.
Run:
  python scripts/run_watchdog_daemon.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, '.')

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path('.') / '.env')
except Exception:
    pass

from pm_app.services.watchdog import Watchdog
import logging
import sys

# Ensure file logging for daemon runs
logs_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(logs_dir, exist_ok=True)
log_file = os.path.join(logs_dir, 'watchdog.log')
handlers = [logging.StreamHandler(sys.stdout)]
try:
    fh = logging.FileHandler(log_file, mode='a')
    handlers.append(fh)
except Exception:
    fh = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=handlers)


def main():
    wd = Watchdog()
    try:
        wd.run()
    except KeyboardInterrupt:
        print('Watchdog stopped')


if __name__ == '__main__':
    main()
