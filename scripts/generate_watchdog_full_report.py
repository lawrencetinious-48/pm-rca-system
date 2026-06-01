#!/usr/bin/env python3
"""
One-shot generator for a full AI-driven Watchdog detailed report.
Usage:
  python scripts/generate_watchdog_full_report.py [--to recipient] [--send]

If --send is provided, the report will be emailed using the project's alert system.
"""
import os
import argparse
from datetime import datetime

# Ensure repo root is importable
import sys
sys.path.insert(0, '.')

from pm_app.services.watchdog import Watchdog
from alert_system import send_alert


def collect_results(wd):
    checks = [
        ('database', wd.check_database),
        ('redis', wd.check_redis),
        ('disk', wd.check_disk_space),
        ('memory', wd.check_memory),
        ('cpu', wd.check_cpu),
        ('response_time', wd.check_response_time),
        ('snags', wd.check_snags),
        ('log_errors', wd.check_log_errors),
        ('activity_risk', wd._query_activity_risk),
        ('network', wd.check_network),
        ('process_usage', wd.check_process_usage),
        ('git_status', wd.check_git_status),
    ]

    results = {}
    for name, fn in checks:
        try:
            r = fn()
            if isinstance(r, tuple):
                success = r[0]
                message = r[1]
                warning = len(r) > 2 and r[2]
                details = r[3] if len(r) > 3 else None
            else:
                success, message = r, 'Unknown'
                warning = False
                details = None
            results[name] = {
                'status': 'ok' if success else 'critical',
                'message': message,
                'warning': warning,
                'details': details,
            }
        except Exception as e:
            results[name] = {'status': 'critical', 'message': f'Check exception: {e}', 'warning': False, 'details': None}
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--to', help='Recipient override for sending report')
    p.add_argument('--send', action='store_true', help='Send report via email')
    args = p.parse_args()

    wd = Watchdog()
    results = collect_results(wd)
    analysis = wd.brain.analyze_results(results)
    report = wd.build_detailed_report(results, analysis)

    # Output to stdout
    print('\n----- Watchdog Detailed Report -----\n')
    print(report)
    print('\n----- End of Report -----\n')

    if args.send:
        recipient = args.to or wd.config.get('recipient_email') or wd.config.get('report_email') or wd.config.get('alert_email_address')
        if not recipient:
            print('No recipient configured; cannot send email.')
            return
        subject = f"Watchdog Detailed Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ok = send_alert(report, subject, recipient=recipient)
        if ok:
            print(f'Report sent to {recipient}')
        else:
            print('Failed to send report; check alert logs and SMTP settings.')


if __name__ == '__main__':
    main()
