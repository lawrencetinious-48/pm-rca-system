#!/usr/bin/env python3
"""
Quick test script to verify email configuration for the PM/RCA Watchdog system.
Run this to diagnose email setup issues.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

def check_config():
    """Check if all required email configuration is present."""
    print("\n" + "="*70)
    print("📧 WATCHDOG EMAIL CONFIGURATION CHECKER")
    print("="*70 + "\n")
    
    config = {
        'ALERT_EMAIL_ADDRESS': os.getenv('ALERT_EMAIL_ADDRESS', '').strip(),
        'ALERT_EMAIL_PASSWORD': os.getenv('ALERT_EMAIL_PASSWORD', '').strip(),
        'ALERT_RECIPIENT_ADDRESS': os.getenv('ALERT_RECIPIENT_ADDRESS', '').strip(),
        'WATCHDOG_RECIPIENT_EMAIL': os.getenv('WATCHDOG_RECIPIENT_EMAIL', '').strip(),
        'REPORT_EMAIL': os.getenv('REPORT_EMAIL', '').strip(),
        'ALERT_SMTP_HOST': os.getenv('ALERT_SMTP_HOST', '').strip(),
        'ALERT_SMTP_PORT': os.getenv('ALERT_SMTP_PORT', '').strip(),
        'ALERT_SMTP_USE_SSL': os.getenv('ALERT_SMTP_USE_SSL', '').strip(),
        'WATCHDOG_ENABLED': os.getenv('WATCHDOG_ENABLED', '').strip(),
        'WATCHDOG_SEND_PERIODIC_SUMMARY': os.getenv('WATCHDOG_SEND_PERIODIC_SUMMARY', '').strip(),
    }
    
    issues = []
    
    # Check sender email
    print("1️⃣  SENDER EMAIL CONFIGURATION")
    print("-" * 70)
    sender = config['ALERT_EMAIL_ADDRESS']
    if not sender:
        print("   ❌ ALERT_EMAIL_ADDRESS is not set (placeholder)")
        issues.append("Missing ALERT_EMAIL_ADDRESS")
    elif sender.startswith('your-'):
        print("   ❌ ALERT_EMAIL_ADDRESS is still a placeholder")
        issues.append("ALERT_EMAIL_ADDRESS is a placeholder")
    else:
        print(f"   ✅ Sender: {sender}")
    
    # Check password
    print("\n2️⃣  SENDER PASSWORD CONFIGURATION")
    print("-" * 70)
    password = config['ALERT_EMAIL_PASSWORD']
    if not password:
        print("   ❌ ALERT_EMAIL_PASSWORD is not set")
        issues.append("Missing ALERT_EMAIL_PASSWORD")
    elif password.startswith('your_'):
        print("   ❌ ALERT_EMAIL_PASSWORD is still a placeholder")
        issues.append("ALERT_EMAIL_PASSWORD is a placeholder")
    else:
        pwd_len = len(password.replace(' ', ''))
        if pwd_len < 8:
            print(f"   ⚠️  Password seems too short: {pwd_len} chars (should be 16)")
            issues.append("Password may be too short")
        else:
            print(f"   ✅ Password configured ({pwd_len} characters)")
    
    # Check recipients
    print("\n3️⃣  RECIPIENT EMAIL CONFIGURATION")
    print("-" * 70)
    recipients = {
        'ALERT_RECIPIENT_ADDRESS': config['ALERT_RECIPIENT_ADDRESS'],
        'WATCHDOG_RECIPIENT_EMAIL': config['WATCHDOG_RECIPIENT_EMAIL'],
        'REPORT_EMAIL': config['REPORT_EMAIL'],
    }
    
    has_recipient = False
    for key, value in recipients.items():
        if value and not value.startswith('your'):
            print(f"   ✅ {key}: {value}")
            has_recipient = True
        elif value and not value.startswith('your'):
            print(f"   ✅ {key}: {value}")
            has_recipient = True
    
    if not has_recipient:
        print("   ❌ No valid recipient email configured")
        issues.append("No recipient email configured")
    
    # Check SMTP settings
    print("\n4️⃣  SMTP CONFIGURATION")
    print("-" * 70)
    smtp_host = config['ALERT_SMTP_HOST']
    smtp_port = config['ALERT_SMTP_PORT']
    use_ssl = config['ALERT_SMTP_USE_SSL']
    
    print(f"   SMTP Host: {smtp_host}")
    print(f"   SMTP Port: {smtp_port}")
    print(f"   Use SSL: {use_ssl}")
    
    if smtp_host.lower() == 'smtp.gmail.com' and smtp_port == '465' and use_ssl == '1':
        print("   ✅ Gmail configuration correct")
    elif smtp_host.lower() == 'smtp.gmail.com' and smtp_port == '587' and use_ssl == '0':
        print("   ✅ Gmail TLS configuration correct")
    else:
        print("   ⚠️  Non-standard SMTP configuration (may be custom)")
    
    # Check watchdog settings
    print("\n5️⃣  WATCHDOG SETTINGS")
    print("-" * 70)
    watchdog_enabled = config['WATCHDOG_ENABLED'].lower() == 'true'
    send_summary = config['WATCHDOG_SEND_PERIODIC_SUMMARY'].lower() == '1'
    
    if watchdog_enabled:
        print("   ✅ WATCHDOG_ENABLED=true")
    else:
        print("   ❌ WATCHDOG_ENABLED is not true")
        issues.append("Watchdog not enabled")
    
    if send_summary:
        print("   ✅ WATCHDOG_SEND_PERIODIC_SUMMARY=1 (periodic emails enabled)")
    else:
        print("   ⚠️  WATCHDOG_SEND_PERIODIC_SUMMARY=0 (only critical alerts)")
    
    # Summary
    print("\n" + "="*70)
    if issues:
        print("❌ CONFIGURATION ISSUES FOUND:")
        print("-" * 70)
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
        print("\n📋 Fix these issues and restart the watchdog service.")
    else:
        print("✅ EMAIL CONFIGURATION LOOKS GOOD!")
        print("-" * 70)
        print("\n🔧 NEXT STEPS:")
        print("   1. Ensure Gmail 2FA is enabled")
        print("   2. Generate app-specific password from Google Account")
        print("   3. Update ALERT_EMAIL_PASSWORD with the 16-char password")
        print("   4. Restart watchdog service")
        print("   5. Wait 5 minutes for first check")
        print("   6. Check logs/watchdog.log for 'Alert sent' messages")
    
    print("\n" + "="*70 + "\n")
    
    return len(issues) == 0


def test_email_send():
    """Test actual email sending."""
    print("\n6️⃣  TESTING EMAIL SEND")
    print("-" * 70)
    print("   Running alert_system test...")
    
    try:
        from alert_system import send_alert
        
        result = send_alert(
            "This is a test alert from the PM/RCA Watchdog system.",
            "Test Alert from PM/RCA Watchdog"
        )
        
        if result:
            print("   ✅ Email sent successfully!")
            print("\n   📧 Check your inbox (or spam folder) for the test email.")
        else:
            print("   ❌ Email send failed - check logs for details")
            return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    return True


if __name__ == '__main__':
    ok = check_config()
    
    # Only attempt to send test email if config looks good
    if ok and len(sys.argv) > 1 and sys.argv[1] == '--send-test':
        test_email_send()
    elif ok:
        print("💡 TIP: Run with --send-test to send a test email")
        print("   python test_email_config.py --send-test\n")
    
    sys.exit(0 if ok else 1)
