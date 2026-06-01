import os
import sys
sys.path.insert(0, '.')

from pm_app.services.watchdog import Watchdog


def test_run_checks_and_build_report():
    # Ensure we don't attempt to send periodic summary in tests
    os.environ['WATCHDOG_SEND_PERIODIC_SUMMARY'] = '0'
    wd = Watchdog()
    results = wd.run_checks()
    # run_checks returns None normally; but build_detailed_report should work
    results = wd.previous_results or {}
    report = wd.build_detailed_report(results, wd.brain.analyze_results(results))
    assert report and 'Watchdog Detailed Report' in report
