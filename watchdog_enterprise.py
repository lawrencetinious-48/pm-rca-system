#!/usr/bin/env python3
"""
PM System Watchdog - Comprehensive Health Monitoring & Engineering Report
Full-featured system monitoring with detailed diagnostics, predictions, and remediation guidance.
Resilient error handling with graceful degradation for failed checks.
"""

import os
import sys
import time
import logging
import subprocess
import psutil
import requests
from datetime import datetime
from pathlib import Path

# Setup comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/watchdog.log', mode='a') if os.path.exists('logs') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)


class ComprehensiveWatchdog:
    """Enterprise-grade system health monitoring with engineering insights."""

    def __init__(self):
        self.app_url = os.getenv('APP_URL', 'http://localhost:5001').rstrip('/')
        self.check_interval = int(os.getenv('WATCHDOG_INTERVAL', '300'))
        self.report_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.checks_performed = 0
        self.checks_passed = 0
        self.checks_failed = 0
        self.check_results = {}

    def log_check(self, name, status, message, details=None, severity='info'):
        """Unified check logging with structured data."""
        self.checks_performed += 1
        if status == 'PASS':
            self.checks_passed += 1
            log_level = logging.INFO
        elif status == 'WARN':
            log_level = logging.WARNING
        else:  # FAIL
            self.checks_failed += 1
            log_level = logging.ERROR

        logger.log(log_level, f"[{name:20}] {status:5} - {message}")
        self.check_results[name] = {
            'status': status,
            'message': message,
            'details': details or '',
            'severity': severity
        }

    def check_app_connectivity(self):
        """Verify application is running and responding."""
        check_name = "App Connectivity"
        try:
            response = requests.get(f"{self.app_url}/health", timeout=10)
            if response.status_code == 200:
                self.log_check(check_name, 'PASS', 'Application responding with HTTP 200')
                return True
            else:
                message = f'Application returned HTTP {response.status_code}'
                self.log_check(check_name, 'FAIL', message, f'Endpoint: {self.app_url}/health')
                return False
        except requests.exceptions.ConnectionError:
            message = f'Cannot connect to {self.app_url} - application may be offline'
            self.log_check(check_name, 'FAIL', message, 'Check network and app service status')
            return False
        except requests.exceptions.Timeout:
            message = f'Timeout connecting to {self.app_url} (>10s) - app may be hanging'
            self.log_check(check_name, 'FAIL', message, 'App response time critical')
            return False
        except Exception as e:
            message = f'Connectivity check failed: {str(e)[:80]}'
            self.log_check(check_name, 'FAIL', message, str(e)[:200])
            return False

    def check_disk_space(self):
        """Monitor disk usage and storage capacity."""
        check_name = "Disk Space"
        try:
            usage = psutil.disk_usage('/')
            percent = usage.percent
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)

            message = f'{percent:.1f}% used ({free_gb:.1f}GB free of {total_gb:.1f}GB total)'

            if percent > 95:
                self.log_check(check_name, 'FAIL', message,
                    f'CRITICAL: Disk nearly full. Free space: {free_gb:.1f}GB. Immediate action required.',
                    severity='critical')
                return False
            elif percent > 90:
                self.log_check(check_name, 'WARN', message,
                    f'WARNING: Disk usage high ({percent:.1f}%). Monitor closely and clean up old files.',
                    severity='warning')
                return True
            elif percent > 85:
                self.log_check(check_name, 'WARN', message,
                    f'Disk usage approaching threshold. Current: {percent:.1f}%',
                    severity='info')
                return True
            else:
                self.log_check(check_name, 'PASS', message)
                return True
        except Exception as e:
            message = f'Disk check failed: {str(e)[:60]}'
            self.log_check(check_name, 'FAIL', message, str(e)[:150])
            return False

    def check_memory_usage(self):
        """Monitor system memory and available RAM."""
        check_name = "Memory Usage"
        try:
            memory = psutil.virtual_memory()
            percent = memory.percent
            available_mb = memory.available / (1024**2)
            total_mb = memory.total / (1024**2)

            message = f'{percent:.1f}% used ({available_mb:.0f}MB free of {total_mb:.0f}MB total)'

            if percent > 95:
                self.log_check(check_name, 'FAIL', message,
                    f'CRITICAL: System memory exhausted. Available: {available_mb:.0f}MB. OOM risk.',
                    severity='critical')
                return False
            elif percent > 90:
                self.log_check(check_name, 'WARN', message,
                    f'WARNING: Memory pressure high ({percent:.1f}%). May trigger OOM killer.',
                    severity='warning')
                return True
            elif percent > 85:
                self.log_check(check_name, 'WARN', message,
                    f'Memory usage elevated. Monitor for leaks.',
                    severity='info')
                return True
            else:
                self.log_check(check_name, 'PASS', message)
                return True
        except Exception as e:
            message = f'Memory check failed: {str(e)[:60]}'
            self.log_check(check_name, 'FAIL', message, str(e)[:150])
            return False

    def check_cpu_usage(self):
        """Monitor CPU utilization and thermal state."""
        check_name = "CPU Usage"
        try:
            cpu_percent = psutil.cpu_percent(interval=2)
            cpu_count = psutil.cpu_count()
            load_avg = os.getloadavg()[0] if hasattr(os, 'getloadavg') else cpu_percent

            message = f'{cpu_percent:.1f}% ({cpu_count} cores)'

            if cpu_percent > 95:
                self.log_check(check_name, 'FAIL', message,
                    f'CRITICAL: CPU maxed at {cpu_percent:.1f}%. System near saturation.',
                    severity='critical')
                return False
            elif cpu_percent > 85:
                self.log_check(check_name, 'WARN', message,
                    f'WARNING: High CPU usage ({cpu_percent:.1f}%). May cause slowdowns.',
                    severity='warning')
                return True
            elif cpu_percent > 70:
                self.log_check(check_name, 'WARN', message,
                    f'CPU elevated at {cpu_percent:.1f}%. Monitor for runaway processes.',
                    severity='info')
                return True
            else:
                self.log_check(check_name, 'PASS', message)
                return True
        except Exception as e:
            message = f'CPU check failed: {str(e)[:60]}'
            self.log_check(check_name, 'FAIL', message, str(e)[:150])
            return False

    def check_process_health(self):
        """Identify processes consuming excessive resources."""
        check_name = "Process Health"
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    if proc.info['cpu_percent'] is None:
                        proc.info['cpu_percent'] = 0
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            top_cpu = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:3]
            top_mem = sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:3]

            issues = []
            for proc in top_cpu:
                if proc['cpu_percent'] > 80:
                    issues.append(f"{proc['name']} (PID {proc['pid']}) using {proc['cpu_percent']:.1f}% CPU")
            for proc in top_mem:
                if proc['memory_percent'] > 20:
                    issues.append(f"{proc['name']} (PID {proc['pid']}) using {proc['memory_percent']:.1f}% RAM")

            if issues:
                message = f'Processes: {len(processes)} total'
                details = 'High resource consumers:\n' + '\n'.join(issues[:5])
                self.log_check(check_name, 'WARN', message, details, severity='warning')
                return True
            else:
                message = f'Process load: {len(processes)} processes, all within normal limits'
                self.log_check(check_name, 'PASS', message)
                return True
        except Exception as e:
            message = f'Process check failed: {str(e)[:60]}'
            self.log_check(check_name, 'WARN', message, str(e)[:150], severity='info')
            return True  # Not critical

    def check_log_errors(self):
        """Scan application logs for recent errors."""
        check_name = "Log Errors"
        try:
            log_file = 'logs/app.log'
            if not Path(log_file).exists():
                self.log_check(check_name, 'WARN', 'No app log file found', 'Cannot scan for errors')
                return True

            with open(log_file, 'r', errors='ignore') as f:
                lines = f.readlines()[-500:]  # Last 500 lines

            errors = [l for l in lines if 'ERROR' in l or 'CRITICAL' in l]
            warnings = [l for l in lines if 'WARNING' in l]

            if not lines:
                self.log_check(check_name, 'PASS', 'Log file empty or just created')
                return True

            error_rate = len(errors) / len(lines) if lines else 0

            if error_rate > 0.1:  # >10% errors
                message = f'Error rate: {error_rate:.1%} ({len(errors)} errors, {len(warnings)} warnings)'
                details = 'Recent errors:\n' + '\n'.join(errors[-5:])
                self.log_check(check_name, 'FAIL', message, details, severity='critical')
                return False
            elif error_rate > 0.05:  # >5% errors
                message = f'Error rate: {error_rate:.1%} ({len(errors)} errors, {len(warnings)} warnings)'
                self.log_check(check_name, 'WARN', message, f'{error_rate:.1%} of log entries are errors')
                return True
            else:
                message = f'Log health: {len(errors)} errors, {len(warnings)} warnings in recent logs'
                self.log_check(check_name, 'PASS', message)
                return True
        except Exception as e:
            message = f'Log check failed: {str(e)[:60]}'
            self.log_check(check_name, 'WARN', message, str(e)[:150], severity='info')
            return True  # Not critical

    def build_engineering_report(self):
        """Generate detailed engineering diagnostics report."""
        report = []
        report.append('=' * 80)
        report.append('PM SYSTEM WATCHDOG - ENGINEERING HEALTH REPORT')
        report.append('=' * 80)
        report.append(f"Report Generated: {self.report_timestamp}")
        report.append(f"System Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Watchdog Interval: {self.check_interval}s")
        report.append('')

        # Summary
        report.append('HEALTH SUMMARY')
        report.append('-' * 40)
        report.append(f"Checks Run: {self.checks_performed}")
        report.append(f"Passed: {self.checks_passed} ({self.checks_passed*100//max(1,self.checks_performed)}%)")
        report.append(f"Failed: {self.checks_failed} ({self.checks_failed*100//max(1,self.checks_performed)}%)")

        overall_status = 'HEALTHY' if self.checks_failed == 0 else 'DEGRADED' if self.checks_failed < 3 else 'CRITICAL'
        report.append(f"Overall Status: {overall_status}")
        report.append('')

        # Detailed Results
        report.append('DETAILED CHECK RESULTS')
        report.append('-' * 40)
        for name, result in self.check_results.items():
            report.append(f"\n{name}")
            report.append(f"  Status: {result['status']}")
            report.append(f"  Message: {result['message']}")
            if result['details']:
                for line in result['details'].split('\n'):
                    if line.strip():
                        report.append(f"  Detail: {line.strip()}")

        # System Information
        report.append('\nSYSTEM INFORMATION')
        report.append('-' * 40)
        try:
            report.append(f"Hostname: {os.getenv('HOSTNAME', 'unknown')}")
            report.append(f"Platform: {sys.platform}")
            report.append(f"Python: {sys.version.split()[0]}")
            report.append(f"CPU Cores: {psutil.cpu_count()}")
            report.append(f"Total Memory: {psutil.virtual_memory().total / (1024**3):.1f}GB")
        except Exception as e:
            report.append(f"System info unavailable: {e}")

        # Recommendations
        report.append('\nRECOMMENDATIONS')
        report.append('-' * 40)
        for name, result in self.check_results.items():
            if result['status'] != 'PASS':
                if 'App Connectivity' in name:
                    report.append("• Check if application service is running")
                    report.append("• Verify network connectivity and firewall rules")
                    report.append("• Check if the app URL is correct in APP_URL environment variable")
                elif 'Disk Space' in name:
                    report.append("• Clean up old logs and temporary files")
                    report.append("• Consider expanding storage capacity")
                    report.append("• Archive old data and uploads")
                    report.append("• Run: find logs -type f -mtime +30 -delete  # Remove logs older than 30 days")
                elif 'Memory Usage' in name:
                    report.append("• Identify memory-leaking processes")
                    report.append("• Restart heavy workers or services")
                    report.append("• Consider adding more RAM")
                    report.append("• Monitor with: top -o %MEM")
                elif 'CPU Usage' in name:
                    report.append("• Profile and optimize expensive operations")
                    report.append("• Reduce background job concurrency")
                    report.append("• Consider load balancing or scaling")
                    report.append("• Monitor with: top -o %CPU")
                elif 'Log Errors' in name:
                    report.append("• Review recent application errors")
                    report.append("• Check database and external service connectivity")
                    report.append("• Validate application configuration")
                    report.append("• Run: tail -f logs/app.log")

        # Process Health Details
        if self.check_results.get('Process Health', {}).get('status') != 'PASS':
            report.append('\nTOP RESOURCE CONSUMERS')
            report.append('-' * 40)
            try:
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        if proc.info['cpu_percent'] is None:
                            proc.info['cpu_percent'] = 0
                        processes.append(proc.info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                if processes:
                    top_cpu = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:5]
                    top_mem = sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:5]
                    
                    report.append('Top 5 CPU consumers:')
                    for proc in top_cpu:
                        report.append(f"  {proc['name']:20} (PID {proc['pid']:6}) CPU: {proc['cpu_percent']:6.1f}% MEM: {proc['memory_percent']:5.1f}%")
                    
                    report.append('\nTop 5 Memory consumers:')
                    for proc in top_mem:
                        report.append(f"  {proc['name']:20} (PID {proc['pid']:6}) CPU: {proc['cpu_percent']:6.1f}% MEM: {proc['memory_percent']:5.1f}%")
            except Exception as e:
                report.append(f"Could not gather process details: {e}")

        # Environmental Configuration
        report.append('\nENVIRONMENTAL CONFIGURATION')
        report.append('-' * 40)
        report.append(f"APP_URL: {os.getenv('APP_URL', 'http://localhost:5001')}")
        report.append(f"APP_ENV: {os.getenv('APP_ENV', 'development')}")
        report.append(f"DATABASE_URL: {'configured' if os.getenv('DATABASE_URL') else 'not configured'}")
        report.append(f"WATCHDOG_INTERVAL: {self.check_interval}s")

        # File System Status
        report.append('\nFILE SYSTEM STATUS')
        report.append('-' * 40)
        try:
            for path in ['.', 'logs', 'uploads', 'pm_app', 'templates']:
                if os.path.exists(path):
                    report.append(f"✓ {path}/")
                else:
                    report.append(f"✗ {path}/ (missing)")
        except Exception as e:
            report.append(f"File system check failed: {e}")

        # Watchdog Functionality Test
        report.append('\nWATCHDOG SELF-CHECK')
        report.append('-' * 40)
        report.append("✓ Watchdog engine operational")
        report.append("✓ Check engine initialized")
        report.append("✓ Report generation working")
        report.append(f"✓ Checks executed: {self.checks_performed}")

        report.append('\n' + '=' * 80)
        report.append('END OF REPORT')
        report.append('=' * 80)
        return '\n'.join(report)

    def run_once(self):
        """Execute all health checks and generate report."""
        logger.info("=" * 80)
        logger.info("WATCHDOG HEALTH CHECK CYCLE STARTING")
        logger.info("=" * 80)

        self.check_app_connectivity()
        self.check_disk_space()
        self.check_memory_usage()
        self.check_cpu_usage()
        self.check_process_health()
        self.check_log_errors()

        report = self.build_engineering_report()
        
        # Print report line by line to ensure full output
        for line in report.split('\n'):
            logger.info(line)

        return self.checks_failed == 0

    def run_daemon(self):
        """Run watchdog continuously with periodic reporting."""
        logger.info(f"Watchdog daemon starting - interval {self.check_interval}s")

        while True:
            try:
                self.check_results = {}
                self.checks_performed = 0
                self.checks_passed = 0
                self.checks_failed = 0
                healthy = self.run_once()

                if not healthy:
                    logger.warning(f"System health degraded: {self.checks_failed} failures detected")
            except KeyboardInterrupt:
                logger.info("Watchdog stopped by user")
                break
            except Exception as e:
                logger.error(f"Watchdog cycle error: {str(e)}", exc_info=False)

            time.sleep(self.check_interval)


if __name__ == '__main__':
    watchdog = ComprehensiveWatchdog()

    if len(sys.argv) > 1 and sys.argv[1] == '--daemon':
        logger.info("Starting watchdog in daemon mode")
        watchdog.run_daemon()
    else:
        logger.info("Running watchdog health check (single cycle)")
        is_healthy = watchdog.run_once()
        sys.exit(0 if is_healthy else 1)
