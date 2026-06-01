#!/usr/bin/env python3
"""Ping every major PM system component and report reachability."""

import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import redis as redis_lib
import sqlalchemy
from sqlalchemy import text
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env.prod')
load_dotenv(PROJECT_ROOT / '.env')


def safe_print(message: str) -> None:
    sys.stdout.write(message.encode('utf-8', errors='replace').decode('utf-8') + '\n')
    sys.stdout.flush()


def check_http(url: str, timeout: int = 8):
    try:
        response = requests.get(url, timeout=timeout)
        status_ok = response.status_code < 400
        return status_ok, f"HTTP {response.status_code} {response.reason}", response.text[:200].strip()
    except Exception as exc:
        return False, str(exc), None


def check_tcp(host: str, port: int, use_ssl: bool = False, timeout: int = 5):
    try:
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        family, socktype, proto, _, sockaddr = addr_info[0]
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(timeout)
            if use_ssl:
                context = ssl.create_default_context()
                with context.wrap_socket(sock, server_hostname=host) as ssl_sock:
                    ssl_sock.connect(sockaddr)
            else:
                sock.connect(sockaddr)
        return True, f"TCP connect to {host}:{port} succeeded", None
    except Exception as exc:
        return False, str(exc), None


def check_database(db_url: str):
    try:
        engine = sqlalchemy.create_engine(
            db_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5} if not db_url.startswith("sqlite") else {},
        )
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            value = result.scalar()
            if value == 1:
                return True, "Database connection OK", None
            return False, "Database responded but SELECT 1 returned unexpected result", None
    except Exception as exc:
        return False, str(exc), None


def check_redis(redis_url: str):
    try:
        client = redis_lib.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
        if client.ping():
            return True, "Redis PONG", None
        return False, "Redis ping returned false", None
    except Exception as exc:
        return False, str(exc), None


def build_service_list():
    app_url = os.getenv('APP_URL') or os.getenv('PUBLIC_BASE_URL') or 'http://localhost:5001'
    services = [
        {
            'name': 'Web Application health endpoint',
            'check': lambda: check_http(f"{app_url.rstrip('/')}/health"),
            'expected': 'HTTP 200 or 2xx',
        },
        {
            'name': 'Web Application root',
            'check': lambda: check_http(app_url),
            'expected': 'HTTP 200 or redirect',
        },
        {
            'name': 'Prometheus',
            'check': lambda: check_http(os.getenv('PROMETHEUS_URL', 'http://localhost:9090') + '/-/healthy'),
            'expected': 'HTTP 200',
        },
        {
            'name': 'Grafana',
            'check': lambda: check_http(os.getenv('GRAFANA_URL', 'http://localhost:3000')),
            'expected': 'HTTP 200 or redirect',
        },
        {
            'name': 'Loki',
            'check': lambda: check_http(os.getenv('LOKI_URL', 'http://localhost:3100') + '/ready'),
            'expected': 'HTTP 200',
        },
        {
            'name': 'Tempo',
            'check': lambda: check_http(os.getenv('TEMPO_URL', 'http://localhost:3200') + '/ready'),
            'expected': 'HTTP 200',
        },
        {
            'name': 'Alertmanager',
            'check': lambda: check_http(os.getenv('ALERTMANAGER_URL', 'http://localhost:9093')),
            'expected': 'HTTP 200 or redirect',
        },
    ]

    database_url = os.getenv('DATABASE_URL')
    if database_url:
        services.append({
            'name': 'Database connection',
            'check': lambda: check_database(database_url),
            'expected': 'SELECT 1 returns 1',
        })

    redis_url = os.getenv('REDIS_URL') or 'redis://localhost:6379/0'
    services.append({
        'name': 'Redis connection',
        'check': lambda: check_redis(redis_url),
        'expected': 'PONG',
    })

    smtp_host = os.getenv('ALERT_SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('ALERT_SMTP_PORT', '465'))
    smtp_ssl = os.getenv('ALERT_SMTP_USE_SSL', '1') == '1'
    services.append({
        'name': 'SMTP server connectivity',
        'check': lambda: check_tcp(smtp_host, smtp_port, use_ssl=smtp_ssl),
        'expected': f'TCP connect to {smtp_host}:{smtp_port}',
    })

    return services


def main():
    safe_print('\n' + '=' * 70)
    safe_print('SYSTEM PING REPORT')
    safe_print(f'Time: {Path.cwd()}')
    safe_print('=' * 70 + '\n')

    services = build_service_list()
    passed = 0
    results = []

    for service in services:
        safe_print(f"--> {service['name']}")
        expected = service['expected']
        safe_print(f"    Expected: {expected}")
        ok, detail, snippet = service['check']()
        if ok:
            passed += 1
            safe_print(f"    PASS: {detail}")
        else:
            safe_print(f"    FAIL: {detail}")
        if snippet:
            safe_print(f"    Response snippet: {snippet}")
        safe_print('')
        results.append((service['name'], ok, detail))

    safe_print('\n' + '=' * 70)
    safe_print('SUMMARY')
    safe_print('=' * 70)
    safe_print(f'Passed: {passed}/{len(services)}')
    for name, ok, detail in results:
        if not ok:
            safe_print(f'- {name}: {detail}')

    return 0 if passed == len(services) else 1


if __name__ == '__main__':
    sys.exit(main())
