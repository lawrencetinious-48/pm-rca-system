#!/usr/bin/env python3
"""
PM System Watchdog - Monitors system health and sends alerts.
Runs continuously to check database, Redis, disk space, memory, and response times.
Sends email alerts to configured email when issues detected.
"""

import os
import sys
import time
import logging
import subprocess
import psutil
import redis
import requests
import sqlalchemy
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alert_system import send_alert
from pm_app.services.watchdog_ai import WatchdogBrain

# Ensure logs directory exists before creating file handlers
# Use project working directory so logs are colocated with repository `logs/`
project_root = os.getcwd()
logs_dir = os.path.join(project_root, 'logs')
try:
    os.makedirs(logs_dir, exist_ok=True)
except Exception:
    pass

file_handler = None
log_file_path = os.path.join(logs_dir, 'watchdog.log')
try:
    file_handler = logging.FileHandler(log_file_path, mode='a')
except Exception:
    file_handler = None

handlers = [logging.StreamHandler(sys.stdout)]
if file_handler:
    handlers.append(file_handler)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=handlers
)
logger = logging.getLogger(__name__)


class Watchdog:
    """System health watchdog that monitors and alerts on issues."""

    def __init__(self):
        self.config = self._load_config()
        self.redis_client = None
        self.last_alert_times = {}
        self.last_summary_at = 0.0
        self.last_hourly_summary_at = 0.0
        self.previous_results = {}
        self.alert_cooldown = 1800  # 30 minutes between same alerts
        self._init_redis()
        
        # Initialize brain - but don't fail if it can't
        try:
            self.brain = WatchdogBrain(self.config)
        except Exception as e:
            logger.warning(f"WatchdogBrain initialization failed: {e}")
            self.brain = None

    def _load_config(self):
        """Load configuration from environment variables."""
        return {
            'check_interval': int(os.getenv('WATCHDOG_INTERVAL', '300')),  # 5 minutes
            'thresholds': {
                'response_time_sec': float(os.getenv('WATCHDOG_RESPONSE_TIME_THRESHOLD', '2.0')),
                'cpu_percent': float(os.getenv('WATCHDOG_CPU_THRESHOLD', '90.0')),
                'memory_percent': float(os.getenv('WATCHDOG_MEMORY_THRESHOLD', '90.0')),
                'disk_percent': float(os.getenv('WATCHDOG_DISK_THRESHOLD', '90.0')),
                'max_error_rate': float(os.getenv('WATCHDOG_ERROR_RATE_THRESHOLD', '0.05')),  # 5%
            },
            'database_url': os.getenv('DATABASE_URL', ''),
            'app_url': os.getenv('APP_URL', 'http://localhost:5001'),
            'report_email': os.getenv('REPORT_EMAIL', os.getenv('ALERT_EMAIL_TO', os.getenv('ALERT_EMAIL_ADDRESS', ''))),
            'recipient_email': (
                os.getenv('WATCHDOG_RECIPIENT_EMAIL')
                or os.getenv('WATCHDOG_REPORT_EMAIL')
                or os.getenv('WATCHDOG_GMAIL_RECIPIENT')
                or os.getenv('WATCHDOG_EMAIL')
                or os.getenv('REPORT_EMAIL')
                or os.getenv('ALERT_EMAIL_TO')
                or os.getenv('ALERT_EMAIL_ADDRESS', '')
            ),
            'alert_email_address': os.getenv('ALERT_EMAIL_ADDRESS', ''),
            'alert_email_password': os.getenv('ALERT_EMAIL_PASSWORD', ''),
            'summary_interval_sec': int(os.getenv('WATCHDOG_REPORT_INTERVAL_SECONDS', '5400')),
            'hourly_summary_interval_sec': int(os.getenv('WATCHDOG_HOURLY_REPORT_INTERVAL_SECONDS', '3600')),
            'send_periodic_summary': os.getenv('WATCHDOG_SEND_PERIODIC_SUMMARY', '0') == '1',
            'send_admin_digest': os.getenv('WATCHDOG_SEND_ADMIN_DIGEST', '1') == '1',
            'log_path': os.getenv('WATCHDOG_LOG_PATH', 'logs/app.log'),
            'watchdog_history_path': os.getenv('WATCHDOG_HISTORY_DB', 'logs/watchdog_history.db'),
            'prometheus_url': os.getenv('PROMETHEUS_URL', ''),
            'loki_url': os.getenv('LOKI_URL', ''),
            # include senior_engineer by default so watchdog can target engineering inboxes
            'admin_inbox_roles': [role.strip() for role in os.getenv('WATCHDOG_ADMIN_INBOX_ROLES', 'developer,senior_engineer').split(',') if role.strip()],
        }

    def _init_redis(self):
        """Initialize Redis connection."""
        try:
            self.redis_client = redis.Redis.from_url(
                os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            self.redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self.redis_client = None

    def _tail_file(self, path, max_lines=200):
        """Return the last max_lines lines from a file."""
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            return [line.rstrip('\n') for line in lines[-max_lines:]]
        except Exception:
            return []

    def _extract_recent_traceback(self, lines):
        """Extract the most recent traceback or error snippet from log lines."""
        if not lines:
            return None

        traceback_start = None
        for index, line in enumerate(lines):
            if line.startswith('Traceback (most recent call last)') or 'Traceback (most recent call last)' in line:
                traceback_start = index
        if traceback_start is not None:
            return '\n'.join(lines[traceback_start:])

        error_lines = [line for line in lines if 'ERROR' in line or 'CRITICAL' in line]
        if error_lines:
            return '\n'.join(error_lines[-10:])
        return None

    def _format_threshold_line(self, label, value, threshold, units='%', status='ok'):
        prefix = 'OK' if status == 'ok' else 'WARN' if status == 'warning' else 'CRITICAL'
        return f"{label}: {value}{units} / threshold {threshold}{units} ({prefix})"

    def _query_activity_risk(self):
        """Check pending activity risk score distribution from the app database."""
        try:
            import sqlalchemy
            from sqlalchemy import text
            engine = sqlalchemy.create_engine(
                self.config['database_url'],
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                connect_args={"connect_timeout": 5} if 'sqlite' not in self.config['database_url'] else {}
            )
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT "
                    "SUM(CASE WHEN risk_score >= 70 THEN 1 ELSE 0 END) AS high_count, "
                    "SUM(CASE WHEN risk_score >= 40 AND risk_score < 70 THEN 1 ELSE 0 END) AS medium_count, "
                    "SUM(CASE WHEN risk_score < 40 OR risk_score IS NULL THEN 1 ELSE 0 END) AS low_count, "
                    "COUNT(*) AS total_count "
                    "FROM activities "
                    "WHERE is_approved = 0"
                ))
                row = result.mappings().first()
            if not row:
                return True, "Activity risk summary unavailable", False, None

            high = int(row['high_count'] or 0)
            medium = int(row['medium_count'] or 0)
            low = int(row['low_count'] or 0)
            total = int(row['total_count'] or 0)
            message = f"Pending activities: {total} (High={high}, Medium={medium}, Low={low})"
            warning = high > 0
            details = f"High-risk forms: {high}\nMedium-risk forms: {medium}\nLow-risk forms: {low}\nTotal pending: {total}"
            return True, message, warning, details
        except Exception as e:
            return True, f"Activity risk summary unavailable: {e}", False, None

    def check_database(self):
        """Check database connectivity."""
        try:
            import sqlalchemy
            from sqlalchemy import text
            engine = sqlalchemy.create_engine(
                self.config['database_url'],
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0
            )
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                if result.scalar() == 1:
                    return True, "Database connection OK"
                return False, "Database query failed"
        except Exception as e:
            return False, f"Database error: {str(e)}"

    def check_redis(self):
        """Check Redis connectivity."""
        if not self.redis_client:
            return False, "Redis client not initialized"
        try:
            if self.redis_client.ping():
                return True, "Redis connection OK"
            return False, "Redis ping failed"
        except Exception as e:
            return False, f"Redis error: {str(e)}"

    def check_disk_space(self):
        """Check disk usage."""
        try:
            usage = psutil.disk_usage('/')
            percent = usage.percent
            if percent > self.config['thresholds']['disk_percent']:
                return False, self._format_threshold_line('Disk usage', percent, self.config['thresholds']['disk_percent'], units='%', status='critical'), False
            elif percent > 80:
                return True, self._format_threshold_line('Disk usage', percent, self.config['thresholds']['disk_percent'], units='%', status='warning'), True
            return True, self._format_threshold_line('Disk usage', percent, self.config['thresholds']['disk_percent'], units='%', status='ok'), False
        except Exception as e:
            return False, f"Disk check error: {str(e)}", False, None

    def check_memory(self):
        """Check memory usage."""
        try:
            memory = psutil.virtual_memory()
            percent = memory.percent
            if percent > self.config['thresholds']['memory_percent']:
                return False, self._format_threshold_line('Memory usage', percent, self.config['thresholds']['memory_percent'], units='%', status='critical'), False, None
            elif percent > 85:
                return True, self._format_threshold_line('Memory usage', percent, self.config['thresholds']['memory_percent'], units='%', status='warning'), True, None
            return True, self._format_threshold_line('Memory usage', percent, self.config['thresholds']['memory_percent'], units='%', status='ok'), False, None
        except Exception as e:
            return False, f"Memory check error: {str(e)}", False, None

    def check_cpu(self):
        """Check CPU usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.config['thresholds']['cpu_percent']:
                return False, self._format_threshold_line('CPU usage', cpu_percent, self.config['thresholds']['cpu_percent'], units='%', status='critical'), False
            elif cpu_percent > 85:
                return True, self._format_threshold_line('CPU usage', cpu_percent, self.config['thresholds']['cpu_percent'], units='%', status='warning'), True
            return True, self._format_threshold_line('CPU usage', cpu_percent, self.config['thresholds']['cpu_percent'], units='%', status='ok'), False
        except Exception as e:
            return False, f"CPU check error: {str(e)}", False, None

    def check_response_time(self):
        """Check application response time."""
        try:
            start = time.time()
            response = requests.get(
                f"{self.config['app_url']}/health",
                timeout=10
            )
            elapsed = time.time() - start
            if response.status_code != 200:
                return False, f"Health endpoint returned {response.status_code}", False, None

            if elapsed > self.config['thresholds']['response_time_sec']:
                return False, self._format_threshold_line('Response time', elapsed, self.config['thresholds']['response_time_sec'], units='s', status='critical'), False, None
            elif elapsed > 1:
                return True, self._format_threshold_line('Response time', elapsed, self.config['thresholds']['response_time_sec'], units='s', status='warning'), True, None
            return True, self._format_threshold_line('Response time', elapsed, self.config['thresholds']['response_time_sec'], units='s', status='ok'), False, None
        except requests.exceptions.RequestException as e:
            return False, f"Response time check failed: {str(e)}", False, None

    def check_snags(self):
        """Check unresolved snag count and risk in the activity queue."""
        try:
            import sqlalchemy
            from sqlalchemy import text
            engine = sqlalchemy.create_engine(
                self.config['database_url'],
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                connect_args={"connect_timeout": 5} if 'sqlite' not in self.config['database_url'] else {}
            )
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT COUNT(*) AS total, SUM(CASE WHEN approved_at IS NULL THEN 1 ELSE 0 END) AS unresolved "
                    "FROM activities "
                    "WHERE activity_type = 'snag'"
                ))
                row = result.mappings().first()
            total = int(row['total'] or 0)
            unresolved = int(row['unresolved'] or 0)
            if total == 0:
                return True, "No snag records found.", False, None
            message = f"Snag queue: {total} records, {unresolved} unresolved."
            warning = unresolved > 0
            details = f"Total snag records: {total}\nUnresolved snag records: {unresolved}"
            return True, message, warning, details
        except Exception as e:
            return False, f"Snag check failed: {str(e)}", False, None

    def check_log_errors(self):
        """Check recent log files for error patterns."""
        try:
            log_file = 'logs/app.log'
            if not os.path.exists(log_file):
                return True, "No app log file found", False, None

            lines = self._tail_file(log_file, max_lines=300)
            if not lines:
                return True, "App log is empty", False, None

            error_lines = [line for line in lines if 'ERROR' in line or 'CRITICAL' in line]
            warning_lines = [line for line in lines if 'WARNING' in line]
            error_count = len(error_lines)
            warning_count = len(warning_lines)
            error_rate = error_count / len(lines) if lines else 0
            summary = f"Error rate: {error_rate:.1%} ({error_count} errors, {warning_count} warnings)"
            traceback_snippet = self._extract_recent_traceback(lines)
            details = traceback_snippet or '\n'.join(error_lines[-5:]) if error_lines else None

            if error_rate > self.config['thresholds']['max_error_rate']:
                return False, summary, False, details
            return True, summary, False, details
        except Exception as e:
            return False, f"Log check error: {str(e)}", False, None

    def check_network(self):
        """Analyze active network connections and listening ports."""
        try:
            conns = psutil.net_connections(kind='inet')
            established = [c for c in conns if c.status == 'ESTABLISHED' and c.raddr]
            listening = [c for c in conns if c.status == 'LISTEN']
            remote_counts = {}
            for c in established:
                ip = c.raddr.ip
                remote_counts[ip] = remote_counts.get(ip, 0) + 1

            top_remote = sorted(remote_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            top_remote_lines = [f"{ip} ({count})" for ip, count in top_remote]
            suspicious_ports = []
            standard_ports = {22, 80, 443, 5000, 5001, 6379, 5432, 3306, 8080, 8000}
            for c in listening[:20]:
                port = c.laddr.port
                if port not in standard_ports:
                    ip = c.laddr.ip or '0.0.0.0'
                    suspicious_ports.append(f"{ip}:{port}")

            summary = f"Connections: {len(conns)} total, {len(established)} established, {len(listening)} listening"
            details = []
            if top_remote_lines:
                details.append("Top remote peers: " + "; ".join(top_remote_lines))
            if suspicious_ports:
                details.append("Uncommon listening ports: " + ", ".join(suspicious_ports[:10]))

            details_text = "\n".join(details) if details else "No suspicious network signals detected."
            warning = len(suspicious_ports) > 0 or (top_remote and top_remote[0][1] > 20)
            return True, summary, warning, details_text
        except Exception as e:
            return False, f"Network check failed: {e}", False, None

    def check_process_usage(self):
        """Check system process load and identify top resource consumers."""
        try:
            metrics = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] is None:
                        proc_info['cpu_percent'] = proc.cpu_percent(interval=0.1)
                    metrics.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not metrics:
                return True, "No process rate data available", False, None

            top_cpu = sorted(metrics, key=lambda p: p['cpu_percent'], reverse=True)[:5]
            top_mem = sorted(metrics, key=lambda p: p['memory_percent'], reverse=True)[:5]
            lines = ["Top CPU consumers:"]
            lines.extend([f"{p['pid']} {p['name']} ({p['username']}) CPU={p['cpu_percent']:.1f}% MEM={p['memory_percent']:.1f}%" for p in top_cpu])
            lines.append("Top memory consumers:")
            lines.extend([f"{p['pid']} {p['name']} ({p['username']}) CPU={p['cpu_percent']:.1f}% MEM={p['memory_percent']:.1f}%" for p in top_mem])

            warning = any(p['cpu_percent'] > 85 or p['memory_percent'] > 85 for p in metrics)
            return True, "Process load snapshot collected", warning, "\n".join(lines)
        except Exception as e:
            return False, f"Process usage check failed: {e}", False, None

    def check_git_status(self):
        """Detect recent repository changes and code update status."""
        try:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            if not os.path.isdir(os.path.join(repo_root, '.git')):
                return True, "Code repository metadata unavailable", False, None

            branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_root, text=True).strip()
            commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_root, text=True).strip()[:12]
            status_output = subprocess.check_output(['git', 'status', '--short'], cwd=repo_root, text=True).strip()
            if status_output:
                details = "Modified files:\n" + status_output[:1200]
                warning = True
                summary = f"Git branch {branch} @ {commit} (uncommitted changes)"
            else:
                details = f"Clean working tree on branch {branch}."
                warning = False
                summary = f"Git branch {branch} @ {commit}"

            return True, summary, warning, details
        except Exception as e:
            return False, f"Git status check failed: {e}", False, None

    def send_alert_email(self, subject, message, severity='critical', recipient=None):
        """Send alert email using the centralized alert system."""
        try:
            full_subject = f"[{severity.upper()}] {subject}"
            full_message = f"""PM System Alert - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Severity: {severity.upper()}

{message}

This is an automated alert from the PM/RCA System Watchdog."""
            # Resolve explicit recipient for diagnostics
            final_recipient = recipient or self.config.get('recipient_email') or self.config.get('report_email') or self.config.get('alert_email_address')
            logger.info(f"Watchdog sending alert to: {final_recipient}")
            return send_alert(full_message, full_subject, recipient=final_recipient)
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")
            return False

    def _get_db_engine(self):
        """Create a database engine for inbox insertions."""
        if not self.config['database_url']:
            return None
        try:
            return sqlalchemy.create_engine(
                self.config['database_url'],
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                connect_args={"connect_timeout": 5} if 'sqlite' not in self.config['database_url'] else {}
            )
        except Exception as e:
            logger.warning(f"Watchdog DB engine creation failed: {e}")
            return None

    def send_admin_inbox_message(self, subject, body):
        """Insert a compact summary into the app inbox for admin roles."""
        try:
            engine = self._get_db_engine()
            if engine is None:
                logger.warning("Admin inbox message skipped because database engine is unavailable.")
                return False
            with engine.begin() as conn:
                for role in self.config.get('admin_inbox_roles', ['developer']):
                    conn.execute(
                        sqlalchemy.text(
                            "INSERT INTO messages (sender_email, sender_role, recipient_role, recipient_email, body, created_at) "
                            "VALUES (:sender_email, :sender_role, :recipient_role, NULL, :body, :created_at)"
                        ),
                        {
                            'sender_email': 'watchdog@soliton',
                            'sender_role': 'system',
                            'recipient_role': role,
                            'body': body,
                            'created_at': datetime.now(),
                        }
                    )
            logger.info(f"Watchdog admin inbox message created for roles: {', '.join(self.config.get('admin_inbox_roles', ['developer']))}")
            return True
        except Exception as e:
            logger.error(f"Failed to write admin inbox message: {e}")
            return False

    def build_admin_digest(self, results, analysis=None):
        """Build a small admin inbox digest summarizing the current state."""
        critical = [name for name, item in results.items() if item['status'] == 'critical']
        warnings = [name for name, item in results.items() if item['warning'] and item['status'] == 'ok']
        lines = [
            f"Watchdog digest — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Overall status: {'CRITICAL' if critical else ('WARN' if warnings else 'OK')}",
            "",
        ]
        if critical:
            lines.append("Critical alerts:")
            for name in critical[:5]:
                lines.append(f"- {name}: {results[name]['message']}")
                if results[name].get('details'):
                    lines.extend([f"    {line}" for line in str(results[name]['details']).splitlines() if line.strip()])
        else:
            lines.append("Critical alerts: none")

        if warnings:
            lines.append("")
            lines.append("Warnings:")
            for name in warnings[:5]:
                lines.append(f"- {name}: {results[name]['message']}")
                if results[name].get('details'):
                    lines.extend([f"    {line}" for line in str(results[name]['details']).splitlines() if line.strip()])

        lines.append("")
        lines.append("Next report will be generated in 90 minutes.")
        lines.append("To view full status, check the email summary that is sent every 90 minutes.")
        if analysis and analysis.get('ai_summary'):
            lines.append("")
            lines.append("AI summary:")
            ai_lines = [line for line in str(analysis['ai_summary']).splitlines() if line.strip()][:4]
            lines.extend([f"- {line}" for line in ai_lines])
        return "\n".join(lines)

    def should_alert(self, alert_type):
        """Check if we should send an alert (cooling period)."""
        now = time.time()
        last_time = self.last_alert_times.get(alert_type, 0)
        if now - last_time > self.alert_cooldown:
            self.last_alert_times[alert_type] = now
            return True
        return False

    def _trim_details(self, details, max_lines=6):
        """Trim detail text for inline report summaries."""
        if not details:
            return None
        lines = [line.strip() for line in str(details).splitlines() if line.strip()]
        if not lines:
            return None
        return " | ".join(lines[:max_lines])

    def _assess_check_risk(self, name, item):
        """Translate a subsystem result into a risk profile."""
        if item['status'] != 'ok':
            return 'High'
        if item.get('warning'):
            return 'Elevated'
        return 'Normal'

    def _get_check_insight(self, name, item):
        """Build system intelligence narratives for each health check."""
        # message/reason is available via item['message'] when needed
        if name == 'database':
            if item['status'] != 'ok':
                return (
                    'Database connectivity failure indicates broken persistence or invalid credentials. '
                    'The app cannot complete queries, which risks transaction failures and degraded UI behavior. '
                    'Validate DATABASE_URL, test DB reachability, and inspect DB logs for authentication or network errors.'
                )
            return 'Database is reachable and queryable. Continue monitoring connection latency and pool exhaustion risks.'
        if name == 'redis':
            if item['status'] != 'ok':
                return (
                    'Redis is unavailable or misconfigured. This breaks caching, session state, and background queue coordination. '
                    'Confirm REDIS_URL format, start the Redis service, and validate ACL/auth settings.'
                )
            return 'Redis connection is healthy. Watch for intermittent spikes or auth failures in worker logs.'
        if name == 'disk':
            return (
                'Storage pressure is the leading cause of cascading failures. High disk usage can produce failed writes, slow checkpointing, and container instability. '
                'Clean logs, archive old uploads, and expand disk capacity before the threshold becomes critical.'
            )
        if name == 'memory':
            return (
                'Memory stress is a high-risk symptom of a leak or overcommit. When memory usage stays elevated, the next failure is swap exhaustion or OOM kills. '
                'Profile top processes, reduce worker concurrency, or add RAM to stabilize the runtime.'
            )
        if name == 'cpu':
            return (
                'Sustained CPU pressure indicates expensive queries, busy background jobs, or runaway loops. '
                'If left unaddressed, service latency will rise across the stack and requests may queue or time out.'
            )
        if name == 'response_time':
            return (
                'Slow response time reveals application or infrastructure load issues. '
                'This may break user-facing endpoints first and then propagate to dependency timeouts. '
                'Inspect query plans, external service calls, and resource contention.'
            )
        if name == 'log_errors':
            return (
                'Error patterns in logs are direct evidence of failing code paths. '
                'The next breakage is likely a service exception, degraded endpoint, or silent data corruption.'
                'Capture the full traceback and remediate the underlying exception immediately.'
            )
        if name == 'activity_risk':
            return (
                'High-risk activities pending review and may drive SLA escalations. Pending activity risk is a business-level failure vector. '
                'Resolve or reassign reviews before risk items cascade into customer-impacting delays.'
            )
        if name == 'network':
            return (
                'Network anomalies can expose the service to unauthorized access or unexpected traffic patterns. '
                'Open ports and remote peers should be investigated before they become an incident.'
            )
        if name == 'process_usage':
            return (
                'Process load reveals the actual resource consumers driving system stress. '
                'A single rogue process can elevate CPU and memory across the host, causing broader failures.'
            )
        if name == 'git_status':
            return (
                'Repository state is an operational risk if local changes are present. '
                'Deployment drift can hide the true production configuration and impair incident triage.'
            )
        return 'Monitor this subsystem for emerging issues; the system health engine will flag any critical progression.'

    def _get_failure_prediction(self, name, item):
        """Provide a near-term failure prediction based on current warning state."""
        if item['status'] != 'ok':
            return 'Immediate failure risk is active and requires urgent remediation.'
        if not item.get('warning'):
            return 'No immediate failure predicted, but continue standard monitoring.'
        if name == 'disk':
            return 'Disk usage may cross critical thresholds soon, threatening write-heavy operations and log rotation.'
        if name == 'memory':
            return 'Memory pressure may produce OOM conditions or degraded worker throughput if left unresolved.'
        if name == 'cpu':
            return 'CPU saturation may cause request queuing, throttling, or repeated timeout events.'
        if name == 'response_time':
            return 'User-facing latency may continue to rise, increasing the chance of timeouts and failed frontend workflows.'
        if name == 'log_errors':
            return 'Ongoing log errors usually precede a service crash or degraded transaction flow.'
        if name == 'activity_risk':
            return 'Pending high-risk items may breach SLA and escalate into a business incident.'
        if name == 'network':
            return 'Network exposure could be exploited or may indicate misrouted services if not corrected.'
        if name == 'process_usage':
            return 'A hot process may become the point of failure as other components compete for resources.'
        return 'This warning is elevated; watch the subsystem closely for a transition to critical status.'

    def _get_system_engine_description(self):
        return (
            'Watchdog executes layered health checks across application, infrastructure, and business signals. '
            'It evaluates persistence, cache, compute, latency, logs, workload risk, network posture, process load, and repo drift. '
            'Each subsystem contributes to a concise, engineer-focused analysis that surfaces root cause, risk exposure, and remediation guidance.'
        )

    def _append_summary_header(self, report, healthy, critical_count, warning_count, total_checks):
        report.append('=== Executive Summary ===')
        report.append('This is a diagnostic engineering briefing with explicit risk, root cause, and remediation guidance.')
        report.append(f'Subsystems evaluated: {total_checks}')
        report.append(f"Overall status: {'ALL SYSTEMS HEALTHY' if healthy else 'ISSUES DETECTED'}")
        report.append(f'Critical systems: {critical_count}, elevated risk warnings: {warning_count}')
        report.append('The report is structured to expose what is broken, why it is broken, what may break next, and how to fix it.')
        report.append('')

    def _append_risk_profile(self, report, sorted_checks):
        report.append('=== Risk Profile ===')
        for name, item in sorted_checks:
            risk = self._assess_check_risk(name, item)
            report.append(f"- {name}: {item['status'].upper()} ({risk} risk) — {item['message']}")
        report.append('')

    def _append_health_snapshot(self, report, results):
        report.append('=== Health Snapshot ===')
        for name, item in results.items():
            report.append(f"- {name}: {item['status'].upper()} — {item['message']}")
            detail_snippet = self._trim_details(item.get('details'))
            if detail_snippet:
                report.append(f'    {detail_snippet}')
        report.append('')

    def _append_detailed_analysis(self, report, results):
        report.append('=== Details ===')
        report.append('Details:')
        any_details = False
        for name, item in results.items():
            if item.get('details'):
                any_details = True
                report.append(f'- {name}:')
                for detail_line in str(item['details']).splitlines():
                    if detail_line.strip():
                        report.append(f'    {detail_line.strip()}')
        if not any_details:
            report.append('No detailed items available.')
        report.append('')

        report.append('=== Diagnostic Breakdown ===')
        for name, item in results.items():
            risk = self._assess_check_risk(name, item)
            report.append(f'- {name} ({risk})')
            status_text = item['status'].upper()
            report.append(f'    Status: {status_text}')
            report.append(f"    Message: {item['message']}")
            if item.get('details'):
                report.append('    Detail block:')
                for line in str(item['details']).splitlines():
                    if line.strip():
                        report.append(f'      - {line.strip()}')
            report.append(f"    Why: {self._get_check_insight(name, item)}")
            report.append(f"    Predicted next failure: {self._get_failure_prediction(name, item)}")
            solution = self._get_check_solution(name, item['message'])
            if solution:
                report.append(f"    Fix: {solution}")
            report.append('')

    def _append_actionable_findings(self, report, results, healthy, warning_count):
        report.append('=== What is broken and why ===')
        if healthy and warning_count == 0:
            report.append('No broken subsystems detected. The system is currently operating within defined thresholds.')
        else:
            for name, item in results.items():
                if item['status'] != 'ok' or item.get('warning'):
                    report.append(f"- {name}: {item['status'].upper()} — {self._get_check_insight(name, item)}")
        report.append('')

        report.append('=== What is likely to break next ===')
        if healthy and warning_count == 0:
            report.append('No immediate failure vectors are visible, but continue monitoring for new warning signals.')
        else:
            for name, item in results.items():
                if item['status'] != 'ok' or item.get('warning'):
                    report.append(f"- {name}: {self._get_failure_prediction(name, item)}")
        report.append('')

        report.append('=== Recommended remediation plan ===')
        for name, item in results.items():
            if item['status'] != 'ok' or item.get('warning'):
                solution = self._get_check_solution(name, item['message'])
                if solution:
                    report.append(f"- {name}: {solution}")
        if healthy and warning_count == 0:
            report.append('No remediation required at this time. Continue service-level monitoring.')
        report.append('')

    def _append_system_mood(self, report, healthy, critical_count):
        report.append('=== System Mood ===')
        if healthy:
            report.append('The system feels stable and responsive. No urgent intervention required.')
        elif critical_count:
            report.append('The system feels critical: prioritize investigation and remediation now.')
        else:
            report.append('The system feels stressed: review the flagged areas and confirm there is no escalation path.')
        report.append('')

    def _append_smart_actions(self, report, results):
        report.append('=== Smart Actions ===')
        if self.previous_results:
            transitions = []
            for name, item in results.items():
                previous = self.previous_results.get(name, {}).get('status')
                if previous and previous != item['status']:
                    transitions.append(f"{name}: {previous.upper()} → {item['status'].upper()}")
            if transitions:
                report.append('Changes since last summary:')
                report.extend([f'  * {line}' for line in transitions])
            else:
                report.append('  * No status transitions detected since the last summary.')
        else:
            report.append('  * No historical comparison available for trend analysis.')
        report.append('')

    def build_summary_report(self, results, analysis=None):
        """Build a concise summary report from current health results."""
        report = [
            f"Watchdog Health Summary for {self.config['app_url']}",
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        healthy = all(item['status'] == 'ok' for item in results.values())
        critical_count = sum(1 for item in results.values() if item['status'] != 'ok')
        warning_count = sum(1 for item in results.values() if item.get('warning'))
        total_checks = len(results)

        sorted_checks = sorted(
            results.items(),
            key=lambda kv: ('High' if kv[1]['status'] != 'ok' else ('Elevated' if kv[1].get('warning') else 'Normal'), kv[0]),
            reverse=True
        )

        self._append_summary_header(report, healthy, critical_count, warning_count, total_checks)
        self._append_risk_profile(report, sorted_checks)
        report.append('=== System Engine Overview ===')
        report.append(self._get_system_engine_description())
        report.append('Each check is weighted by severity and contributes to a single operational picture for engineering review.')
        report.append('')
        self._append_health_snapshot(report, results)

        if analysis and analysis.get('ai_summary'):
            report.append('=== AI Insights ===')
            report.extend([line for line in str(analysis['ai_summary']).splitlines() if line.strip()])
            report.append('')

        self._append_detailed_analysis(report, results)
        self._append_actionable_findings(report, results, healthy, warning_count)
        self._append_system_mood(report, healthy, critical_count)
        self._append_smart_actions(report, results)

        report.append('=== Report Metadata ===')
        report.append('Generated by: PM/RCA Watchdog')
        report.append(f"Source app: {self.config['app_url']}")
        report.append('This is an automated watchdog summary report.')
        return '\n'.join(report)

    def build_detailed_report(self, results, analysis=None):
        """Build a verbose watchdog report that includes full diagnostics and AI intelligence."""
        report = [
            f"Watchdog Detailed Report for {self.config['app_url']}",
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "=== Executive Overview ===",
            f"Overall status: {'ALL SYSTEMS HEALTHY' if all(item['status'] == 'ok' for item in results.values()) else 'ISSUES DETECTED'}",
            f"Monitored subsystems: {len(results)}",
            f"Critical systems: {sum(1 for item in results.values() if item['status'] != 'ok')}",
            f"Elevated warnings: {sum(1 for item in results.values() if item.get('warning'))}",
            "",
            "=== Full Subsystem Diagnostics ===",
        ]

        for name, item in results.items():
            report.append(f"--- {name.upper()} ---")
            report.append(f"Status: {item['status'].upper()}")
            report.append(f"Message: {item['message']}")
            if item.get('details'):
                report.append("Details:")
                for detail_line in str(item['details']).splitlines():
                    if detail_line.strip():
                        report.append(f"  {detail_line.strip()}")
            report.append(f"Insight: {self._get_check_insight(name, item)}")
            report.append(f"Prediction: {self._get_failure_prediction(name, item)}")
            solution = self._get_check_solution(name, item['message'])
            if solution:
                report.append(f"Fix: {solution}")
            report.append("")

        report.append("=== AI Intelligence ===")
        if analysis:
            report.append(f"Anomaly count: {analysis.get('anomaly_count', 0)}")
            report.append(f"Forecast warning count: {analysis.get('prediction_count', 0)}")
            report.append("")
            if analysis.get('ai_summary'):
                report.append("AI summary:")
                report.extend([line for line in str(analysis['ai_summary']).splitlines() if line.strip()])
                report.append("")
            if analysis.get('log_intelligence'):
                log_intel = analysis['log_intelligence']
                report.append("Log intelligence:")
                report.append(f"  Recent error count: {log_intel.get('error_count', 'N/A')}")
                if log_intel.get('top_clusters'):
                    report.append("  Top error clusters:")
                    for cluster in log_intel.get('top_clusters', [])[:10]:
                        report.append(f"    - {cluster['count']} events → {cluster['pattern']}")
                report.append("")
        else:
            report.append("AI analysis unavailable.")
            report.append("")

        report.append("=== Raw Diagnostics Detail ===")
        raw_detail_exists = False
        for name, item in results.items():
            if item.get('details'):
                raw_detail_exists = True
                report.append(f"* {name}: full detail block")
                for detail_line in str(item['details']).splitlines():
                    if detail_line.strip():
                        report.append(f"    {detail_line.strip()}")
        if not raw_detail_exists:
            report.append("No raw detail blocks were collected.")
        report.append("")

        report.append("=== Recommended Actions ===")
        for name, item in results.items():
            if item['status'] != 'ok' or item.get('warning'):
                solution = self._get_check_solution(name, item['message'])
                if solution:
                    report.append(f"- {name}: {solution}")
        if all(item['status'] == 'ok' and not item.get('warning') for item in results.values()):
            report.append("No active remediation actions required at this time.")
        report.append("")

        report.append("=== Metadata ===")
        report.append("Generated by: PM/RCA Watchdog")
        report.append(f"Source app: {self.config['app_url']}")
        report.append("This is an automated detailed watchdog report.")
        return "\n".join(report)

    def _get_check_solution(self, name, reason):
        solution_map = {
            'database': "Verify DATABASE_URL and DB credentials. Ensure the database server is running and reachable.",
            'redis': "Check REDIS_URL, start Redis if stopped, and ensure the app can connect.",
            'disk': "Free disk space or expand storage. Remove old logs/uploads and clear temporary files.",
            'memory': "Investigate memory-hungry processes, restart heavy workers, or increase available RAM.",
            'cpu': "Profile CPU-bound processes and optimize or limit background jobs.",
            'response_time': "Review request latency, slow endpoints, and database query performance.",
            'log_errors': "Open recent log errors and fix the underlying exception or misconfiguration.",
            'activity_risk': "Review high-risk pending forms and approve or reassign them to avoid SLA breaches.",
            'network': "Check unusual listening ports and remote peers. Confirm firewall rules and close unexpected services.",
            'process_usage': "Inspect top CPU/memory consumers and restart or tune the offending processes.",
            'git_status': "Commit or stash local changes if this is a production environment, or deploy a clean branch.",
        }
        if name in solution_map:
            return solution_map[name]
        if 'timeout' in reason.lower() or 'response time' in name:
            return "Investigate slow endpoints, high latency, and downstream service delays."
        return "Investigate the component and apply standard remediation steps."

    def send_periodic_summary(self, results, analysis=None):
        """Send periodic watchdog reports by email and to admin inbox at configured intervals."""
        if not self.config.get('send_periodic_summary', False):
            logger.debug("Watchdog periodic summary email is disabled by configuration.")
            return False

        if self.config['summary_interval_sec'] <= 0 and self.config['hourly_summary_interval_sec'] <= 0:
            return False

        now = time.time()
        hourly_due = (
            self.config['hourly_summary_interval_sec'] > 0
            and now - self.last_hourly_summary_at >= self.config['hourly_summary_interval_sec']
        )
        summary_due = (
            self.config['summary_interval_sec'] > 0
            and now - self.last_summary_at >= self.config['summary_interval_sec']
        )

        if not hourly_due and not summary_due:
            self.previous_results = results
            return False

        recipient = self.config.get('recipient_email') or self.config.get('report_email') or self.config.get('alert_email_address')
        if not recipient:
            logger.debug("Watchdog summary skipped - no recipient configured.")
            if summary_due:
                self.last_summary_at = now
            if hourly_due:
                self.last_hourly_summary_at = now
            self.previous_results = results
            return False

        try:
            subject = f"Watchdog Detailed Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            body = self.build_detailed_report(results, analysis)
            sent = self.send_alert_email(subject, body, severity='info', recipient=recipient)
            if sent:
                logger.debug(f"Watchdog report sent to {recipient}")
        except Exception as e:
            logger.debug(f"Watchdog report send failed: {str(e)[:80]}")
            sent = False

        if summary_due:
            self.last_summary_at = now
        if hourly_due:
            self.last_hourly_summary_at = now

        if self.config.get('send_admin_digest', False):
            try:
                digest = self.build_admin_digest(results, analysis)
                self.send_admin_inbox_message(subject, digest)
            except Exception as e:
                logger.debug(f"Admin inbox message failed: {str(e)[:80]}")

        self.previous_results = results
        return sent

    def run_checks(self):
        """Run all health checks and send alerts if needed."""
        logger.info("Running health checks...")

        # Skip expensive/fragile checks if their dependencies aren't available
        checks = [
            ('disk', self.check_disk_space),           # Always run
            ('memory', self.check_memory),              # Always run
            ('cpu', self.check_cpu),                   # Always run
            ('response_time', self.check_response_time), # Core check
            ('log_errors', self.check_log_errors),     # Safe local check
        ]

        # Optional checks - skip if config unavailable
        optional_checks = [
            ('database', self.check_database, bool(self.config.get('database_url'))),
            ('redis', self.check_redis, bool(self.redis_client)),
            ('snags', self.check_snags, bool(self.config.get('database_url'))),
            ('activity_risk', self._query_activity_risk, bool(self.config.get('database_url'))),
            ('network', self.check_network, True),
            ('process_usage', self.check_process_usage, True),
            ('git_status', self.check_git_status, True),
        ]

        results = {}

        # Run core checks
        for name, check_func in checks:
            try:
                result = check_func()
                if isinstance(result, tuple):
                    success = result[0]
                    message = result[1]
                    warning = len(result) > 2 and result[2]
                    details = result[3] if len(result) > 3 else None
                else:
                    success, message = result, "Unknown"
                    warning = False
                    details = None

                results[name] = {
                    'status': 'ok' if success else 'critical',
                    'message': message,
                    'warning': warning,
                    'details': details
                }
            except Exception as e:
                logger.warning(f"Check {name} failed: {str(e)[:100]}")
                results[name] = {
                    'status': 'critical',
                    'message': f"{name} check error",
                    'warning': False,
                    'details': str(e)[:200]
                }

        # Run optional checks only if preconditions are met
        for name, check_func, should_run in optional_checks:
            if not should_run:
                logger.debug(f"Skipping {name} - preconditions not met")
                continue

            try:
                result = check_func()
                if isinstance(result, tuple):
                    success = result[0]
                    message = result[1]
                    warning = len(result) > 2 and result[2]
                    details = result[3] if len(result) > 3 else None
                else:
                    success, message = result, "Unknown"
                    warning = False
                    details = None

                results[name] = {
                    'status': 'ok' if success else 'critical',
                    'message': message,
                    'warning': warning,
                    'details': details
                }
            except Exception as e:
                logger.debug(f"Optional check {name} skipped: {str(e)[:80]}")
                # Don't include failed optional checks in results

        # Try to run analysis if we have results
        analysis = None
        try:
            if self.brain and results:
                analysis = self.brain.analyze_results(results)
        except Exception as e:
            logger.debug(f"Analysis failed: {e}")

        try:
            summary_sent = self.send_periodic_summary(results, analysis) if results else False
        except Exception as e:
            logger.debug(f"Summary send failed: {e}")
            summary_sent = False

        if not summary_sent and results:
            try:
                issues = [name for name, item in results.items() if item['status'] != 'ok' or item['warning']]
                if issues and self.config.get('send_admin_digest', False) and self.should_alert('interim_digest'):
                    digest = self.build_admin_digest(results, analysis)
                    self.send_admin_inbox_message("Watchdog Interim Digest", digest)
            except Exception as e:
                logger.debug(f"Interim digest failed: {e}")

        # Log summary
        status_summary = {k: v['status'] for k, v in results.items()}
        logger.info(f"Health check: {len(results)} checks completed - {status_summary}")

        return results

    def run(self):
        """Main watchdog loop - resilient to errors."""
        logger.info(f"Watchdog started (interval={self.config['check_interval']}s)")

        while True:
            try:
                self.run_checks()
            except KeyboardInterrupt:
                logger.info("Watchdog stopped by user")
                break
            except Exception as e:
                logger.error(f"Watchdog loop error: {str(e)[:100]}")

            try:
                time.sleep(self.config['check_interval'])
            except KeyboardInterrupt:
                logger.info("Watchdog interrupted during sleep")
                break


def main():
    """Entry point for watchdog."""
    try:
        watchdog = Watchdog()
        watchdog.run()
    except KeyboardInterrupt:
        logger.info("Watchdog terminated")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Watchdog failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
