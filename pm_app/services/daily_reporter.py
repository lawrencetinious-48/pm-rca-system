#!/usr/bin/env python3
"""
PM System Daily Reporter - Generates and emails daily performance reports.
Runs once per day (configurable time) and sends comprehensive system health report.
2"""

import os
import sys
import time
import logging
import smtplib
import sqlalchemy
import psutil
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pm_app.services.watchdog import Watchdog
from pm_app.services.watchdog_ai import WatchdogBrain
from sqlalchemy import text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/reporter.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


class DailyReporter:
    """Generates daily system performance and health reports."""

    def __init__(self):
        self.config = self._load_config()
        self.db = None
        self.brain = WatchdogBrain(self.config)
        self.last_sent_at = datetime.now() if self.config['report_interval_minutes'] > 0 else None

    def _load_config(self):
        """Load configuration from environment variables."""
        return {
            'report_time': os.getenv('REPORT_TIME', '09:00'),  # Send at 9 AM if no interval is configured
            'report_interval_minutes': int(os.getenv('REPORT_INTERVAL_MINUTES', os.getenv('WATCHDOG_REPORT_INTERVAL_MINUTES', '90'))),
            'report_email': os.getenv('REPORT_EMAIL', 'lawrencemulindwa48@gmail.com'),
            'alert_email_address': os.getenv('ALERT_EMAIL_ADDRESS', ''),
            'alert_email_password': os.getenv('ALERT_EMAIL_PASSWORD', ''),
            'database_url': os.getenv('DATABASE_URL', ''),
            'app_url': os.getenv('APP_URL', 'http://localhost:5001'),
            'watchdog_history_path': os.getenv('WATCHDOG_HISTORY_DB', 'logs/watchdog_history.db'),
            'log_path': os.getenv('WATCHDOG_LOG_PATH', 'logs/app.log'),
            'prometheus_url': os.getenv('PROMETHEUS_URL', ''),
            'loki_url': os.getenv('LOKI_URL', ''),
            'thresholds': {
                'response_time_sec': float(os.getenv('WATCHDOG_RESPONSE_TIME_THRESHOLD', '2.0')),
                'cpu_percent': float(os.getenv('WATCHDOG_CPU_THRESHOLD', '90.0')),
                'memory_percent': float(os.getenv('WATCHDOG_MEMORY_THRESHOLD', '90.0')),
                'disk_percent': float(os.getenv('WATCHDOG_DISK_THRESHOLD', '90.0')),
                'max_error_rate': float(os.getenv('WATCHDOG_ERROR_RATE_THRESHOLD', '0.05')),
            },
            'retention_days': int(os.getenv('REPORT_RETENTION_DAYS', '30')),
        }

    def _get_db_engine(self):
        """Create database engine."""
        try:
            engine = sqlalchemy.create_engine(
                self.config['database_url'],
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10
            )
            return engine
        except Exception as e:
            logger.error(f"Failed to create DB engine: {e}")
            return None

    def _collect_metrics(self, hours=24):
        """Collect system metrics from the last N hours."""
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'period_hours': hours,
            'system': {},
            'users': {},
            'activities': {},
            'performance': {},
            'errors': {},
            'security': {},
        }

        engine = self._get_db_engine()
        if not engine:
            metrics['system']['uptime_hours'] = self._get_uptime_hours()
            return metrics

        try:
            with engine.connect() as conn:
                # System uptime (from logs)
                metrics['system']['uptime_hours'] = self._get_uptime_hours()

                # User metrics
                user_stats = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_users,
                        COUNT(CASE WHEN is_blocked = true THEN 1 END) as blocked_users,
                        COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as new_users_24h
                    FROM users
                """)).first()
                metrics['users'] = dict(user_stats._mapping) if user_stats else {}

                # Activity metrics
                activity_stats = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_activities,
                        COUNT(CASE WHEN activity_type = 'pm' THEN 1 END) as pm_count,
                        COUNT(CASE WHEN activity_type = 'rca' THEN 1 END) as rca_count,
                        COUNT(CASE WHEN activity_type = 'snag' THEN 1 END) as snag_count,
                        COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as activities_24h,
                        COUNT(CASE WHEN is_approved = true THEN 1 END) as approved_count,
                        AVG(risk_score) as avg_risk_score
                    FROM activities
                """)).first()
                metrics['activities'] = dict(activity_stats._mapping) if activity_stats else {}

                # SLA metrics
                sla_stats = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_with_sla,
                        COUNT(CASE WHEN sla_deadline < NOW() THEN 1 END) as sla_overdue,
                        COUNT(CASE WHEN sla_deadline BETWEEN NOW() AND NOW() + INTERVAL '6 hours' THEN 1 END) as sla_due_soon
                    FROM activities
                    WHERE sla_deadline IS NOT NULL
                """)).first()
                metrics['activities']['sla'] = dict(sla_stats._mapping) if sla_stats else {}

                # Error count from logs (if available)
                metrics['errors'] = self._count_recent_errors()

                # Performance metrics - average response time
                perf_stats = conn.execute(text("""
                    SELECT
                        AVG(EXTRACT(EPOCH FROM updated_at - created_at)) as avg_processing_time,
                        COUNT(*) as total_requests
                    FROM (
                        SELECT created_at, updated_at
                        FROM activities
                        WHERE created_at >= NOW() - INTERVAL '24 hours'
                        AND updated_at IS NOT NULL
                    ) sub
                """)).first()
                metrics['performance'] = dict(perf_stats._mapping) if perf_stats else {}

                # Security audit log (would need separate audit table)
                metrics['security']['recent_logins'] = self._count_recent_logins()
                metrics['security']['failed_logins_24h'] = self._count_failed_logins()

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            metrics['error'] = str(e)

        return metrics

    def _get_uptime_hours(self):
        """Get system uptime in hours."""
        try:
            uptime_seconds = time.time() - psutil.boot_time()
            return round(uptime_seconds / 3600, 2)
        except Exception:
            return None

    def _safe_num(self, value, digits=2):
        """Safely format numeric values for report output."""
        try:
            if value is None:
                return 'N/A'
            return round(float(value), digits)
        except Exception:
            return value

    def _collect_watchdog_health(self):
        """Collect watchdog health checks and return rich health results."""
        try:
            watchdog = Watchdog()
            checks = [
                ('database', watchdog.check_database),
                ('redis', watchdog.check_redis),
                ('disk', watchdog.check_disk_space),
                ('memory', watchdog.check_memory),
                ('cpu', watchdog.check_cpu),
                ('response_time', watchdog.check_response_time),
                ('snags', watchdog.check_snags),
                ('log_errors', watchdog.check_log_errors),
                ('activity_risk', watchdog._query_activity_risk),
                ('network', watchdog.check_network),
                ('process_usage', watchdog.check_process_usage),
                ('git_status', watchdog.check_git_status),
            ]
            results = {}
            for name, check_func in checks:
                try:
                    result = check_func()
                    if isinstance(result, tuple):
                        success = result[0]
                        message = result[1]
                        warning = result[2] if len(result) > 2 else False
                        details = result[3] if len(result) > 3 else None
                    else:
                        success, message = result, 'Unknown'
                        warning = False
                        details = None
                    results[name] = {
                        'status': 'ok' if success else 'critical',
                        'message': message,
                        'warning': warning,
                        'details': details
                    }
                except Exception as e:
                    results[name] = {
                        'status': 'critical',
                        'message': f'Health check failed: {e}',
                        'warning': False,
                        'details': None
                    }
            return results
        except Exception as e:
            logger.error(f"Failed to collect watchdog health checks: {e}")
            return {}

    def _build_watchdog_insights(self, watchdog_results):
        try:
            if not watchdog_results:
                return {}
            return self.brain.analyze_results(watchdog_results)
        except Exception as e:
            logger.warning(f"Watchdog AI analysis failed: {e}")
            return {}

    def generate_daily_report(self):
        """Generate the daily report payload for email sending."""
        metrics = self._collect_metrics(hours=24)
        watchdog_results = self._collect_watchdog_health()
        analysis = self._build_watchdog_insights(watchdog_results)
        html = self.generate_html_report(metrics, watchdog_results, analysis)
        text = self.generate_text_report(metrics, watchdog_results, analysis)
        return {'html': html, 'text': text, 'metrics': metrics, 'watchdog_results': watchdog_results, 'analysis': analysis}

    def _count_recent_errors(self):
        """Count errors in recent logs."""
        try:
            log_file = 'logs/app.log'
            if not os.path.exists(log_file):
                return {'error_count': 0, 'warning_count': 0}

            cutoff = datetime.now() - timedelta(hours=24)
            error_count = 0
            warning_count = 0

            with open(log_file, 'r') as f:
                for line in f:
                    try:
                        log_time_str = line.split(']')[0].replace('[', '')
                        log_time = datetime.strptime(log_time_str, '%Y-%m-%d %H:%M:%S,%f')
                        if log_time >= cutoff:
                            if 'ERROR' in line:
                                error_count += 1
                            elif 'WARNING' in line:
                                warning_count += 1
                    except Exception:
                        continue

            return {'error_count': error_count, 'warning_count': warning_count}
        except Exception as e:
            logger.error(f"Error counting log errors: {e}")
            return {'error_count': 0, 'warning_count': 0}

    def _count_recent_logins(self):
        """Count successful logins in last 24h."""
        # This would typically query an audit log table
        # For now, estimate from app.log
        try:
            log_file = 'logs/app.log'
            if not os.path.exists(log_file):
                return 0

            cutoff = datetime.now() - timedelta(hours=24)
            login_count = 0

            with open(log_file, 'r') as f:
                for line in f:
                    if 'POST /login' in line and 'status=302' in line:
                        try:
                            log_time_str = line.split(']')[0].replace('[', '')
                            log_time = datetime.strptime(log_time_str, '%Y-%m-%d %H:%M:%S,%f')
                            if log_time >= cutoff:
                                login_count += 1
                        except Exception:
                            continue

            return login_count
        except Exception as e:
            logger.error(f"Error counting logins: {e}")
            return 0

    def _count_failed_logins(self):
        """Count failed logins in last 24h."""
        try:
            log_file = 'logs/app.log'
            if not os.path.exists(log_file):
                return 0

            cutoff = datetime.now() - timedelta(hours=24)
            failed_count = 0

            with open(log_file, 'r') as f:
                for line in f:
                    if 'status=401' in line or ('POST /login' in line and 'status=200' not in line and 'status=302' not in line):
                        try:
                            log_time_str = line.split(']')[0].replace('[', '')
                            log_time = datetime.strptime(log_time_str, '%Y-%m-%d %H:%M:%S,%f')
                            if log_time >= cutoff:
                                failed_count += 1
                        except Exception:
                            continue

            return failed_count
        except Exception as e:
            logger.error(f"Error counting failed logins: {e}")
            return 0

    def _render_watchdog_health_html(self, watchdog_results):
        if not watchdog_results:
            return "<p>No watchdog health checks were available for this report.</p>"

        rows = []
        for name, item in watchdog_results.items():
            status_class = 'critical' if item['status'] != 'ok' else 'warning' if item.get('warning') else 'ok'
            details_html = ''
            if item.get('details'):
                detail_lines = ''.join(f"<div>{line}</div>" for line in str(item['details']).splitlines() if line.strip())
                details_html = f"<div class='detail'>{detail_lines}</div>"
            rows.append(
                f"<tr><td>{name}</td><td class='{status_class}'>{item['status'].upper()}</td>"
                f"<td>{item['message']}</td><td>{details_html}</td></tr>"
            )
        return """
        <div class="section">
            <h2>Watchdog Health Checks</h2>
            <table>
                <tr><th>Check</th><th>Status</th><th>Message</th><th>Details</th></tr>
                {rows}
            </table>
        </div>
        """.replace('{rows}', ''.join(rows))

    def _render_ai_insights_html(self, analysis):
        if not analysis:
            return "<p>No AI insights were generated for this report.</p>"

        lines = []
        if analysis.get('ai_summary'):
            lines.append("<h3>AI Summary</h3>")
            for line in str(analysis['ai_summary']).splitlines():
                if line.strip():
                    lines.append(f"<div>{line}</div>")
        if analysis.get('log_intelligence'):
            log_intel = analysis['log_intelligence']
            lines.append("<h3>Log intelligence</h3>")
            lines.append(f"<div>Recent errors: {log_intel.get('error_count', 0)}</div>")
            if log_intel.get('top_clusters'):
                lines.append("<div>Top error patterns:</div>")
                for cluster in log_intel.get('top_clusters', [])[:10]:
                    lines.append(f"<div>• {cluster['count']} × {cluster['pattern']}</div>")
        return "<div class='section'><h2>AI Insights</h2>" + ''.join(lines) + "</div>"

    def generate_html_report(self, metrics, watchdog_results=None, analysis=None):
        """Generate HTML report from metrics and watchdog health data."""
        avg_risk_score = self._safe_num(metrics['activities'].get('avg_risk_score'))
        avg_processing_time = self._safe_num(metrics['performance'].get('avg_processing_time'))
        failed_logins = metrics['security'].get('failed_logins_24h', 0)
        error_count = metrics['errors'].get('error_count', 0)
        warning_count = metrics['errors'].get('warning_count', 0)
        watchdog_section = self._render_watchdog_health_html(watchdog_results)
        ai_section = self._render_ai_insights_html(analysis)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #1F2937; color: white; padding: 20px; border-radius: 8px; }}
                .section {{ margin: 20px 0; padding: 15px; border: 1px solid #e5e7eb; border-radius: 8px; }}
                .metric {{ display: inline-block; margin: 10px; padding: 10px; background: #f3f4f6; border-radius: 5px; }}
                .critical {{ color: #dc2626; font-weight: bold; }}
                .warning {{ color: #f59e0b; font-weight: bold; }}
                .ok {{ color: #10b981; font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
                th {{ background-color: #f3f4f6; }}
                .detail {{ margin-top: 6px; color: #374151; font-size: 13px; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 2px solid #e5e7eb; color: #6b7280; font-size: 12px; }}
                pre {{ white-space: pre-wrap; word-break: break-word; font-family: Consolas, monospace; background: #f3f4f6; padding: 10px; border-radius: 6px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>PM System Watchdog AI Report</h1>
                <p>Generated: {metrics['timestamp']}</p>
                <p>Period: Last {metrics['period_hours']} hours</p>
            </div>

            <div class="section">
                <h2>System Health</h2>
                <div class="metric">Uptime: {metrics['system'].get('uptime_hours', 'N/A')} hours</div>
            </div>

            <div class="section">
                <h2>User Overview</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Total Users</td><td>{metrics['users'].get('total_users', 'N/A')}</td></tr>
                    <tr><td>Blocked Users</td><td>{metrics['users'].get('blocked_users', 'N/A')}</td></tr>
                    <tr><td>New Users (24h)</td><td>{metrics['users'].get('new_users_24h', 'N/A')}</td></tr>
                    <tr><td>Successful Logins (24h)</td><td>{metrics['security'].get('recent_logins', 'N/A')}</td></tr>
                    <tr><td>Failed Logins (24h)</td><td class="{'critical' if failed_logins > 10 else 'ok'}">{failed_logins}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>Activity Summary</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Total Activities</td><td>{metrics['activities'].get('total_activities', 'N/A')}</td></tr>
                    <tr><td>PM Forms</td><td>{metrics['activities'].get('pm_count', 'N/A')}</td></tr>
                    <tr><td>RCA Forms</td><td>{metrics['activities'].get('rca_count', 'N/A')}</td></tr>
                    <tr><td>Snag Reports</td><td>{metrics['activities'].get('snag_count', 'N/A')}</td></tr>
                    <tr><td>New Activities (24h)</td><td>{metrics['activities'].get('activities_24h', 'N/A')}</td></tr>
                    <tr><td>Approved</td><td>{metrics['activities'].get('approved_count', 'N/A')}</td></tr>
                    <tr><td>Avg Risk Score</td><td>{avg_risk_score}</td></tr>
                    <tr><td>SLA Overdue</td><td class="critical">{metrics['activities'].get('sla', {}).get('sla_overdue', 'N/A')}</td></tr>
                    <tr><td>SLA Due Soon</td><td class="warning">{metrics['activities'].get('sla', {}).get('sla_due_soon', 'N/A')}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>Performance & Errors</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Avg Processing Time</td><td>{avg_processing_time} seconds</td></tr>
                    <tr><td>Errors (24h)</td><td class="{'critical' if error_count > 50 else 'ok'}">{error_count}</td></tr>
                    <tr><td>Warnings (24h)</td><td>{warning_count}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>Executive Summary</h2>
                <p>High-risk activity count: {metrics['activities'].get('sla', {}).get('sla_overdue', 0) or 0} overdue, {metrics['activities'].get('sla', {}).get('sla_due_soon', 0) or 0} due soon.</p>
                <p>Latest log summary: {error_count} errors and {warning_count} warnings were observed in the last 24 hours.</p>
            </div>

            {watchdog_section}
            {ai_section}

            <div class="footer">
                <p>This report was generated automatically by the PM System Watchdog AI Reporter.</p>
                <p>System URL: {self.config['app_url']}</p>
            </div>
        </body>
        </html>
        """
        return html

        if not watchdog_results:
            return "Watchdog health checks were unavailable for this report.\n"

        lines = ["Watchdog Health Checks:"]
        for name, item in watchdog_results.items():
            warning_tag = ' [WARNING]' if item.get('warning') else ''
            lines.append(f"- {name}: {item['status'].upper()}{warning_tag} — {item['message']}")
            if item.get('details'):
                for detail_line in str(item['details']).splitlines():
                    if detail_line.strip():
                        lines.append(f"    {detail_line.strip()}")
        lines.append("")
        return "\n".join(lines)

    def _render_ai_insights_text(self, analysis):
        if not analysis:
            return "AI insights are unavailable for this report.\n"

        lines = ["AI Insights:"]
        if analysis.get('ai_summary'):
            lines.append("AI summary:")
            for line in str(analysis['ai_summary']).splitlines():
                if line.strip():
                    lines.append(f"- {line.strip()}")
            lines.append("")
        if analysis.get('log_intelligence'):
            log_intel = analysis['log_intelligence']
            lines.append(f"Recent log error count: {log_intel.get('error_count', 0)}")
            if log_intel.get('top_clusters'):
                lines.append("Top error clusters:")
                for cluster in log_intel['top_clusters'][:10]:
                    lines.append(f"- {cluster['count']} × {cluster['pattern']}")
            lines.append("")
        return "\n".join(lines)

    def generate_text_report(self, metrics, watchdog_results=None, analysis=None):
        """Generate a plain text version of the daily report."""
        avg_risk_score = self._safe_num(metrics['activities'].get('avg_risk_score'))
        avg_processing_time = self._safe_num(metrics['performance'].get('avg_processing_time'))
        failed_logins = metrics['security'].get('failed_logins_24h', 0)
        error_count = metrics['errors'].get('error_count', 0)
        warning_count = metrics['errors'].get('warning_count', 0)
        watchdog_section = self._render_watchdog_health_text(watchdog_results)
        ai_section = self._render_ai_insights_text(analysis)

        return f"""
PM System Watchdog AI Report
Generated: {metrics['timestamp']}
Period: Last {metrics['period_hours']} hours

System Health:
- Uptime: {metrics['system'].get('uptime_hours', 'N/A')} hours

User Overview:
- Total Users: {metrics['users'].get('total_users', 'N/A')}
- Blocked Users: {metrics['users'].get('blocked_users', 'N/A')}
- New Users (24h): {metrics['users'].get('new_users_24h', 'N/A')}
- Successful Logins (24h): {metrics['security'].get('recent_logins', 'N/A')}
- Failed Logins (24h): {failed_logins}

Activity Summary:
- Total Activities: {metrics['activities'].get('total_activities', 'N/A')}
- PM Forms: {metrics['activities'].get('pm_count', 'N/A')}
- RCA Forms: {metrics['activities'].get('rca_count', 'N/A')}
- Snag Reports: {metrics['activities'].get('snag_count', 'N/A')}
- New Activities (24h): {metrics['activities'].get('activities_24h', 'N/A')}
- Approved: {metrics['activities'].get('approved_count', 'N/A')}
- Avg Risk Score: {avg_risk_score}
- SLA Overdue: {metrics['activities'].get('sla', {}).get('sla_overdue', 'N/A')}
- SLA Due Soon: {metrics['activities'].get('sla', {}).get('sla_due_soon', 'N/A')}

Performance:
- Avg Processing Time: {avg_processing_time} seconds
- Errors (24h): {error_count}
- Warnings (24h): {warning_count}

{watchdog_section}
{ai_section}
System URL: {self.config['app_url']}
"""

    def send_report_email(self, html_content, text_content, metrics):
        """Send daily report email."""
        if not self.config['alert_email_address'] or not self.config['alert_email_password']:
            logger.warning("Email credentials not configured, skipping report")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.config['alert_email_address']
            msg['To'] = self.config['report_email']
            msg['Subject'] = f"PM System Watchdog AI Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            html_part = MIMEText(html_content, 'html')
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
            msg.attach(html_part)

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(
                    self.config['alert_email_address'],
                    self.config['alert_email_password']
                )
                server.send_message(msg)

            logger.info(f"Daily report sent to {self.config['report_email']}")
            return True
        except Exception as e:
            logger.error(f"Failed to send report email: {e}")
            return False

    def should_send_now(self):
        """Check if it's time to send the report based on interval or fixed time."""
        now = datetime.now()
        if self.config['report_interval_minutes'] > 0:
            if self.last_sent_at is None:
                return True
            return now - self.last_sent_at >= timedelta(minutes=self.config['report_interval_minutes'])

        report_time = datetime.strptime(self.config['report_time'], '%H:%M').time()
        current_time = now.time().replace(second=0, microsecond=0)
        return current_time == report_time

    def run(self):
        """Main reporter loop."""
        logger.info("Daily reporter started")

        while True:
            try:
                if self.should_send_now():
                    logger.info("Generating watchdog AI report...")
                    report = self.generate_daily_report()
                    sent = self.send_report_email(report['html'], report['text'], report['metrics'])
                    if sent:
                        self.last_sent_at = datetime.now()

                    # Avoid repeated sending during the same interval.
                    time.sleep(61)
                else:
                    time.sleep(30)
            except KeyboardInterrupt:
                logger.info("Daily reporter stopped by user")
                break
            except Exception as e:
                logger.error(f"Daily reporter error: {e}")
                time.sleep(60)


def main():
    """Entry point for daily reporter."""
    try:
        reporter = DailyReporter()
        reporter.run()
    except KeyboardInterrupt:
        logger.info("Daily reporter terminated")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Daily reporter failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
