import os

from pm_app.services.watchdog import Watchdog


def test_check_log_errors_includes_traceback_details(monkeypatch):
    watchdog = Watchdog()

    sample_lines = [
        "INFO Starting application",
        "ERROR Unhandled exception occurred",
        "Traceback (most recent call last):",
        "  File \"app.py\", line 123, in <module>",
        "    raise ValueError('boom')",
        "ValueError: boom",
    ]

    monkeypatch.setattr(watchdog, '_tail_file', lambda path, max_lines=300: sample_lines)
    monkeypatch.setattr('pm_app.services.watchdog.os.path.exists', lambda path: True)

    success, message, warning, details = watchdog.check_log_errors()

    assert success is False
    assert 'Error rate' in message
    assert details is not None
    assert 'Traceback (most recent call last):' in details
    assert 'File "app.py", line 123' in details


def test_build_summary_report_contains_actionable_analysis():
    watchdog = Watchdog()
    results = {
        'disk': {'status': 'critical', 'message': 'Disk usage critical: 92.0%', 'warning': False, 'details': None},
        'cpu': {'status': 'ok', 'message': 'CPU usage OK: 50.0%', 'warning': False, 'details': None},
        'activity_risk': {'status': 'ok', 'message': 'Pending activities: 7 (High=2, Medium=3, Low=2)', 'warning': True, 'details': 'High-risk forms: 2\nMedium-risk forms: 3\nLow-risk forms: 2\nTotal pending: 7'},
    }

    report = watchdog.build_summary_report(results)

    assert 'Overall status: ISSUES DETECTED' in report
    assert 'High-risk activities pending review' in report
    assert 'Details:' in report


def test_send_periodic_summary_sends_hourly_and_summary_reports(monkeypatch):
    watchdog = Watchdog()
    watchdog.config['send_periodic_summary'] = True
    watchdog.config['hourly_summary_interval_sec'] = 2
    watchdog.config['summary_interval_sec'] = 3
    watchdog.config['recipient_email'] = 'recipient@example.com'

    reports = []
    def fake_send_alert_email(subject, message, severity='info', recipient=None):
        reports.append((subject, message, severity, recipient))
        return True

    inbox_messages = []
    def fake_send_admin_inbox_message(subject, body):
        inbox_messages.append((subject, body))
        return True

    monkeypatch.setattr(watchdog, 'send_alert_email', fake_send_alert_email)
    monkeypatch.setattr(watchdog, 'send_admin_inbox_message', fake_send_admin_inbox_message)

    monkeypatch.setattr('pm_app.services.watchdog.time.time', lambda: 0)
    results = {'disk': {'status': 'ok', 'message': 'ok', 'warning': False, 'details': None}}
    analysis = {}

    assert watchdog.send_periodic_summary(results, analysis) is False
    assert reports == []
    assert inbox_messages == []

    monkeypatch.setattr('pm_app.services.watchdog.time.time', lambda: 2.1)
    assert watchdog.send_periodic_summary(results, analysis) is True
    assert len(reports) == 1
    assert len(inbox_messages) == 1
    assert 'Watchdog Detailed Report' in reports[0][0]
    assert 'Watchdog Detailed Report' in inbox_messages[0][0]

    monkeypatch.setattr('pm_app.services.watchdog.time.time', lambda: 3.2)
    assert watchdog.send_periodic_summary(results, analysis) is True
    assert len(reports) == 2
    assert len(inbox_messages) == 2
    assert reports[1][3] == 'recipient@example.com'


def test_send_periodic_summary_skips_admin_digest_by_default(monkeypatch):
    watchdog = Watchdog()
    watchdog.config['send_periodic_summary'] = True
    watchdog.config['send_admin_digest'] = False
    watchdog.config['hourly_summary_interval_sec'] = 2
    watchdog.config['summary_interval_sec'] = 3
    watchdog.config['recipient_email'] = 'recipient@example.com'

    reports = []
    def fake_send_alert_email(subject, message, severity='info', recipient=None):
        reports.append((subject, message, severity, recipient))
        return True

    inbox_messages = []
    def fake_send_admin_inbox_message(subject, body):
        inbox_messages.append((subject, body))
        return True

    monkeypatch.setattr(watchdog, 'send_alert_email', fake_send_alert_email)
    monkeypatch.setattr(watchdog, 'send_admin_inbox_message', fake_send_admin_inbox_message)
    monkeypatch.setattr('pm_app.services.watchdog.time.time', lambda: 2.1)

    results = {'disk': {'status': 'ok', 'message': 'ok', 'warning': False, 'details': None}}
    analysis = {}

    assert watchdog.send_periodic_summary(results, analysis) is True
    assert len(reports) == 1
    assert len(inbox_messages) == 0
    assert 'Watchdog Detailed Report' in reports[0][0]


def test_send_periodic_summary_skips_admin_digest_by_default(monkeypatch):
    watchdog = Watchdog()
    watchdog.config['send_periodic_summary'] = True
    watchdog.config['send_admin_digest'] = False
    watchdog.config['hourly_summary_interval_sec'] = 2
    watchdog.config['summary_interval_sec'] = 3
    watchdog.config['recipient_email'] = 'recipient@example.com'

    reports = []
    def fake_send_alert_email(subject, message, severity='info', recipient=None):
        reports.append((subject, message, severity, recipient))
        return True

    inbox_messages = []
    def fake_send_admin_inbox_message(subject, body):
        inbox_messages.append((subject, body))
        return True

    monkeypatch.setattr(watchdog, 'send_alert_email', fake_send_alert_email)
    monkeypatch.setattr(watchdog, 'send_admin_inbox_message', fake_send_admin_inbox_message)
    monkeypatch.setattr('pm_app.services.watchdog.time.time', lambda: 2.1)

    results = {'disk': {'status': 'ok', 'message': 'ok', 'warning': False, 'details': None}}
    analysis = {}

    assert watchdog.send_periodic_summary(results, analysis) is True
    assert len(reports) == 1
    assert len(inbox_messages) == 0
    assert 'Watchdog Detailed Report' in reports[0][0]
