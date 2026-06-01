#!/usr/bin/env python3
"""
Simplified PM System Watchdog - Core health checks only.
Minimal dependencies, fast, reliable.
"""

import os
import sys
import time
import logging
import requests
import psutil
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class SimpleWatchdog:
    """Minimal watchdog that checks what actually matters."""

    def __init__(self):
        self.app_url = os.getenv('APP_URL', 'http://localhost:5001')
        self.check_interval = int(os.getenv('WATCHDOG_INTERVAL', '300'))  # 5 mins

    def check_app_health(self):
        """Check if app is responding."""
        try:
            response = requests.get(f"{self.app_url}/health", timeout=5)
            status = "OK" if response.status_code == 200 else "FAILED"
            return status, f"App health: {response.status_code}"
        except Exception as e:
            return "FAILED", f"App unreachable: {str(e)[:80]}"

    def check_disk_space(self):
        """Check if disk space is critically low."""
        try:
            usage = psutil.disk_usage('/')
            if usage.percent > 95:
                return "CRITICAL", f"Disk: {usage.percent:.1f}% FULL"
            elif usage.percent > 90:
                return "WARN", f"Disk: {usage.percent:.1f}% (above 90%)"
            return "OK", f"Disk: {usage.percent:.1f}%"
        except Exception as e:
            return "ERROR", f"Disk check failed: {str(e)[:50]}"

    def check_memory(self):
        """Check memory usage."""
        try:
            memory = psutil.virtual_memory()
            if memory.percent > 95:
                return "CRITICAL", f"Memory: {memory.percent:.1f}% FULL"
            elif memory.percent > 90:
                return "WARN", f"Memory: {memory.percent:.1f}% (above 90%)"
            return "OK", f"Memory: {memory.percent:.1f}%"
        except Exception as e:
            return "ERROR", f"Memory check failed: {str(e)[:50]}"

    def check_cpu(self):
        """Check CPU usage."""
        try:
            cpu = psutil.cpu_percent(interval=1)
            if cpu > 95:
                return "CRITICAL", f"CPU: {cpu:.1f}% (sustained high load)"
            elif cpu > 85:
                return "WARN", f"CPU: {cpu:.1f}% (elevated)"
            return "OK", f"CPU: {cpu:.1f}%"
        except Exception as e:
            return "ERROR", f"CPU check failed: {str(e)[:50]}"

    def run_once(self):
        """Run all checks once and print results."""
        logger.info("=== Watchdog Health Check ===")
        
        checks = [
            ("App Health", self.check_app_health()),
            ("Disk Space", self.check_disk_space()),
            ("Memory", self.check_memory()),
            ("CPU", self.check_cpu()),
        ]
        
        critical_count = 0
        for name, (status, message) in checks:
            logger.info(f"{name:20} [{status:8}] {message}")
            if status == "CRITICAL":
                critical_count += 1
        
        logger.info(f"Overall: {'CRITICAL' if critical_count > 0 else 'OK'} ({critical_count} critical issues)")
        logger.info("")
        
        return critical_count == 0

    def run_daemon(self):
        """Run watchdog continuously."""
        logger.info(f"Watchdog starting - checking every {self.check_interval} seconds")
        
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            
            time.sleep(self.check_interval)


if __name__ == '__main__':
    watchdog = SimpleWatchdog()
    
    # Check if running as daemon or one-shot
    if len(sys.argv) > 1 and sys.argv[1] == '--daemon':
        watchdog.run_daemon()
    else:
        # Run once
        watchdog.run_once()
