#!/usr/bin/env python3
"""
PM System Diagnostic Tool
Verifies app, database, users, and watchdog functionality
"""

import os
import sys
import time
from datetime import datetime

# Set up path
sys.path.insert(0, os.path.dirname(__file__))

def diagnose():
    """Run comprehensive diagnostics."""
    print("=" * 80)
    print("PM SYSTEM DIAGNOSTIC REPORT")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("")

    # 1. Database Check
    print("1. DATABASE CONNECTION")
    print("-" * 40)
    try:
        from model import db, User
        from pm_app.legacy_app import create_app
        
        app = create_app()
        with app.app_context():
            user_count = db.session.query(User).count()
            print(f"✓ Database connected")
            print(f"  Users in database: {user_count}")
            
            # List users
            users = db.session.query(User).all()
            if users:
                print(f"  User details:")
                for user in users[:10]:
                    print(f"    - {user.email}: role={user.role}, blocked={user.is_blocked}, has_password={bool(user.password_hash)}")
            else:
                print(f"  WARNING: No users found in database!")
    except Exception as e:
        print(f"✗ Database error: {e}")
    print("")

    # 2. App Health Check
    print("2. APP HEALTH CHECK")
    print("-" * 40)
    try:
        import requests
        app_url = os.getenv('APP_URL', 'http://localhost:5001')
        response = requests.get(f"{app_url}/health", timeout=5)
        if response.status_code == 200:
            print(f"✓ App responding at {app_url}")
            print(f"  Status code: {response.status_code}")
        else:
            print(f"✗ App returned {response.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"✗ Cannot connect to app at {os.getenv('APP_URL', 'http://localhost:5001')}")
        print(f"  Make sure the app is running: python app.py")
    except Exception as e:
        print(f"✗ App check failed: {e}")
    print("")

    # 3. Authentication Test
    print("3. LOGIN AUTHENTICATION")
    print("-" * 40)
    try:
        from pm_app.legacy_app import create_app
        from werkzeug.security import check_password_hash
        from model import User
        
        app = create_app()
        with app.app_context():
            users = User.query.all()
            if not users:
                print("✗ No users in database - cannot test login")
                print("  Create a user first using: python scripts/create_admin.py")
            else:
                print(f"✓ Found {len(users)} users")
                for user in users[:5]:
                    if user.password_hash:
                        print(f"  User: {user.email}")
                        print(f"    Role: {user.role}")
                        print(f"    Password hash: {'✓ Set' if user.password_hash else '✗ Not set'}")
                        print(f"    Blocked: {user.is_blocked}")
                    else:
                        print(f"  WARNING: {user.email} has no password hash!")
    except Exception as e:
        print(f"✗ Auth check failed: {e}")
    print("")

    # 4. System Resources
    print("4. SYSTEM RESOURCES")
    print("-" * 40)
    try:
        import psutil
        disk = psutil.disk_usage('/')
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        
        status = "✓" if disk.percent < 85 and memory.percent < 85 else "⚠"
        print(f"{status} Disk:   {disk.percent:.1f}% used ({disk.free/(1024**3):.1f}GB free)")
        print(f"{'✓' if memory.percent < 85 else '⚠'} Memory: {memory.percent:.1f}% used ({memory.available/(1024**3):.1f}GB free)")
        print(f"{'✓' if cpu < 80 else '⚠'} CPU:    {cpu:.1f}%")
    except Exception as e:
        print(f"✗ System check failed: {e}")
    print("")

    # 5. Environment Variables
    print("5. ENVIRONMENT CONFIGURATION")
    print("-" * 40)
    env_vars = ['APP_ENV', 'APP_URL', 'DATABASE_URL', 'REDIS_URL', 'SECRET_KEY', 'ENABLE_ROLE_LOCKED_LOGIN']
    for var in env_vars:
        value = os.getenv(var, 'NOT SET')
        if var == 'SECRET_KEY':
            value = '***' if value and value != 'NOT SET' else value
        elif var == 'DATABASE_URL':
            value = '***' if value and value != 'NOT SET' else value
        print(f"  {var}: {value}")
    print("")

    # 6. File System
    print("6. FILE SYSTEM")
    print("-" * 40)
    paths = ['logs', 'uploads', 'instance', '.env']
    for path in paths:
        exists = os.path.exists(path)
        status = "✓" if exists else "✗"
        if exists and os.path.isdir(path):
            size = sum(os.path.getsize(os.path.join(dirpath, filename))
                      for dirpath, _, filenames in os.walk(path)
                      for filename in filenames) / (1024**2)
            print(f"{status} {path}/: exists ({size:.1f}MB)")
        else:
            print(f"{status} {path}: {'exists' if exists else 'missing'}")
    print("")

    # 7. Watchdog Test
    print("7. WATCHDOG FUNCTIONALITY")
    print("-" * 40)
    try:
        from watchdog_enterprise import ComprehensiveWatchdog
        watchdog = ComprehensiveWatchdog()
        healthy = watchdog.run_once()
        print(f"✓ Watchdog executed successfully")
        print(f"  Checks passed: {watchdog.checks_passed}/{watchdog.checks_performed}")
        print(f"  Overall status: {'HEALTHY' if healthy else 'ISSUES DETECTED'}")
    except Exception as e:
        print(f"✗ Watchdog test failed: {e}")
    print("")

    # Summary
    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)
    print("")
    print("Next steps:")
    print("1. If database has no users, run: python scripts/create_admin.py")
    print("2. If app not responding, start it: python app.py")
    print("3. Test login with user credentials shown above")
    print("4. Monitor watchdog with: python watchdog_enterprise.py --daemon")
    print("")


if __name__ == '__main__':
    diagnose()
