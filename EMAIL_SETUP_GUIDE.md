# Email & Watchdog Notification Setup Guide

## 🔴 Problem: Not Receiving Watchdog/Observer Notifications

Your `.env` file has placeholder values for email credentials. The watchdog cannot send notifications without these.

### Current Status
- ✗ `ALERT_EMAIL_ADDRESS=your-gmail-address@gmail.com` (placeholder)
- ✗ `ALERT_EMAIL_PASSWORD=your_gmail_app_password_here` (placeholder)
- ✓ `REPORT_EMAIL=lawrencemulindwa48@gmail.com` (configured for reports)

---

## Step 1: Generate a Gmail App-Specific Password

Gmail requires an **app-specific password** (not your regular password) for security reasons.

### Prerequisites
1. Gmail account with **2-Factor Authentication (2FA) enabled**
2. If 2FA isn't enabled, do that first: https://myaccount.google.com/security

### Generate App Password
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. In the left sidebar, find **"App passwords"** (below "2-Step Verification")
3. Select **App**: Mail
4. Select **Device**: Windows Computer (or your device)
5. Click **Generate**
6. Google will show a 16-character password: `xxxx xxxx xxxx xxxx`
7. **Copy this password** (it will only show once)

### Format
```
Original format from Google: a b c d e f g h i j k l m n o p
Space-separated groups (you may see it like this)

Copy the entire string and paste it into .env - the system will remove spaces automatically
```

---

## Step 2: Update Your .env File

Edit `c:\Users\Admin\Desktop\pm\.env` and update these lines:

```env
# ================= EMAIL =================
# Email configuration for alerts and notifications
# For Gmail, use an App Password (requires 2FA enabled on the account).
ALERT_EMAIL_ADDRESS=lawrencemulindwa48@gmail.com
ALERT_EMAIL_PASSWORD=your_16_char_app_password_here
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=465
ALERT_SMTP_USE_SSL=1
ALERT_SMTP_USE_TLS=0

# ================= MONITORING =================
# Watchdog configuration
WATCHDOG_ENABLED=true
WATCHDOG_INTERVAL=300  # Check every 5 minutes
WATCHDOG_SEND_PERIODIC_SUMMARY=1  # Enable to send periodic reports
WATCHDOG_SEND_ADMIN_DIGEST=0  # Disable summary digest; only full engineering reports are emailed
WATCHDOG_RECIPIENT_EMAIL=lawrencemulindwa48@gmail.com  # Add this line if not present

# Daily report configuration
REPORT_INTERVAL_MINUTES=90
REPORT_EMAIL=lawrencemulindwa48@gmail.com
```

### Key Points
- **ALERT_EMAIL_ADDRESS**: The Gmail address sending alerts (must match the account with the app password)
- **ALERT_EMAIL_PASSWORD**: The 16-character app-specific password
- **ALERT_RECIPIENT_ADDRESS** or **WATCHDOG_RECIPIENT_EMAIL**: Where to send notifications (can be different)
- **WATCHDOG_SEND_PERIODIC_SUMMARY**: Set to `1` to enable periodic report emails
- **WATCHDOG_SEND_ADMIN_DIGEST**: Set to `1` only if you want a short admin inbox digest in addition to full reports

---

## Step 3: Restart the Watchdog Service

After updating `.env`, restart the watchdog to use the new credentials.

### Option A: Command Line (if running locally)
```bash
# Stop the running watchdog
Ctrl+C (if running in terminal)

# Start watchdog in background
python watchdog_enterprise.py &

# Or use the simple watchdog
python watchdog_simple.py &
```

### Option B: Docker (if using containers)
```bash
docker-compose down watchdog
docker-compose up -d watchdog
```

### Option C: Check if it's running
```bash
# Windows - check for Python processes
tasklist | findstr python

# Check watchdog logs
tail -f logs/watchdog.log
```

---

## Step 4: Test Email Configuration

### Test 1: Run Alert System Test
```bash
cd c:\Users\Admin\Desktop\pm
python alert_system.py
```

Expected output:
```
Sending test alert...
[timestamp] [INFO] alert_system: Alert sent successfully: Test Alert
```

If it fails, you'll see an error like:
```
[ERROR] Failed to send alert after N attempts: ...
```

### Test 2: Check Logs for Errors
```bash
# View watchdog logs
tail -f logs/watchdog.log

# Look for these patterns:
# - "Alert sent successfully"
# - "Failed to send alert"
# - "Alert email credentials not configured"
```

### Test 3: Trigger a Watchdog Check
```bash
# Run watchdog service once
python watchdog_simple.py --once

# Or via service
pm_app.services.watchdog.Watchdog().run_checks()
```

---

## Common Issues & Solutions

### ❌ "Alert email credentials not configured"
**Problem**: `ALERT_EMAIL_ADDRESS` or `ALERT_EMAIL_PASSWORD` is empty or placeholder

**Solution**: 
1. Verify values in `.env` are NOT placeholders
2. Restart the app/watchdog
3. Check: `echo $ALERT_EMAIL_ADDRESS` (PowerShell: `$env:ALERT_EMAIL_ADDRESS`)

### ❌ "Failed to send alert: (535, b'5.7.8 Username and Password not accepted...'"
**Problem**: Wrong password or not an app-specific password

**Solution**:
1. Verify you're using the **16-character app-specific password** from Google
2. NOT your regular Gmail password
3. Re-generate if needed from [Google Account Security](https://myaccount.google.com/security)
4. Ensure 2FA is enabled on your Gmail account

### ❌ "Failed to send alert: (535, b'5.7.1 Please log in with your web browser..."
**Problem**: Gmail detected unusual activity or app not trusted

**Solution**:
1. Log in to your Gmail account
2. Review the security warning
3. Allow the app access: https://myaccount.google.com/connected-apps
4. Retry sending alert

### ❌ "Failed to send alert: timeout exceeded"
**Problem**: Network issue or Gmail server unreachable

**Solution**:
1. Check internet connectivity: `ping smtp.gmail.com`
2. Try alternate SMTP settings:
   ```env
   ALERT_SMTP_PORT=587
   ALERT_SMTP_USE_SSL=0
   ALERT_SMTP_USE_TLS=1
   ```

### ❌ "No alerts received even though logs say 'sent successfully'"
**Problem**: 
- Alert cooldown is active (30 minutes between same alerts)
- Wrong recipient address
- Notifications in Gmail filters

**Solution**:
1. Check cooldown: `ALERT_COOLDOWN_SECONDS` in alert_system.py (default 1800s = 30 min)
2. Verify recipient: `WATCHDOG_RECIPIENT_EMAIL` or `REPORT_EMAIL` 
3. Check Gmail filters: Settings > Filters and Blocked Addresses
4. Check spam folder
5. Whitelist sender: `ALERT_EMAIL_ADDRESS`

---

## Watchdog Alert Types

The watchdog sends alerts for:

1. **System Health Issues**
   - High CPU usage (>90%)
   - High memory usage (>90%)
   - High disk usage (>90%)
   - Slow response times (>2 seconds)

2. **Application Issues**
   - Database connection failed
   - Redis connection failed
   - Application timeout
   - High error rate (>5%)

3. **Periodic Reports** (if enabled)
   - Daily/hourly summary
   - Interval: `REPORT_INTERVAL_MINUTES` or `REPORT_TIME`
   - Recipient: `REPORT_EMAIL`

---

## Configuration Reference

### Email (Alert System)
```env
ALERT_EMAIL_ADDRESS=your-email@gmail.com          # Sender address
ALERT_EMAIL_PASSWORD=xxxx xxxx xxxx xxxx          # 16-char app password
ALERT_SMTP_HOST=smtp.gmail.com                    # SMTP server
ALERT_SMTP_PORT=465                               # SSL port (or 587 for TLS)
ALERT_SMTP_USE_SSL=1                              # Use SSL (1=yes, 0=no)
ALERT_SMTP_USE_TLS=0                              # Use TLS (0 if using SSL)
ALERT_SMTP_TIMEOUT=2                              # Connection timeout seconds
```

### Watchdog Email Delivery
```env
WATCHDOG_ENABLED=true                             # Enable watchdog
WATCHDOG_INTERVAL=300                             # Check every 5 minutes
WATCHDOG_RECIPIENT_EMAIL=email@gmail.com          # Where to send alerts
WATCHDOG_SEND_PERIODIC_SUMMARY=1                  # Send summary emails
WATCHDOG_REPORT_INTERVAL_SECONDS=5400             # 90 minutes
```

### Daily Reports
```env
REPORT_EMAIL=email@gmail.com                      # Report recipient
REPORT_INTERVAL_MINUTES=90                        # Send every 90 minutes
REPORT_TIME=09:00                                 # Or fixed time (fallback)
REPORT_RETENTION_DAYS=30                          # Keep reports for 30 days
```

---

## Verification Checklist

After setup, verify:

- [ ] Gmail 2FA is enabled
- [ ] App-specific password generated and copied (16 characters)
- [ ] `.env` file updated with actual values (not placeholders)
- [ ] No spaces in password when pasting
- [ ] `ALERT_EMAIL_ADDRESS` matches the Gmail account
- [ ] `WATCHDOG_ENABLED=true`
- [ ] `WATCHDOG_SEND_PERIODIC_SUMMARY=1` (for periodic reports)
- [ ] Recipient email addresses are correct
- [ ] Watchdog service is running
- [ ] Test alert sends successfully
- [ ] Check spam folder for first email
- [ ] Whitelist sender in Gmail if emails go to spam

---

## Running the Watchdog Service

### As a Background Process
```bash
# Windows PowerShell (background)
Start-Process python "watchdog_enterprise.py"

# Or with logging
python watchdog_enterprise.py > logs/watchdog.log 2>&1 &
```

### As a Service (Windows)
Create a batch file `start_watchdog.bat`:
```batch
@echo off
cd /d C:\Users\Admin\Desktop\pm
python watchdog_enterprise.py
```

Schedule with Task Scheduler:
1. Open Task Scheduler
2. Create Basic Task
3. Name: "PM Watchdog"
4. Trigger: At startup
5. Action: Run `start_watchdog.bat`

### As a Docker Service
```bash
# In docker-compose.yml, ensure watchdog service is enabled
docker-compose up -d watchdog

# Check logs
docker logs pm-watchdog
```

---

## Next Steps

1. **Generate Gmail app password** (5 minutes)
2. **Update .env file** (2 minutes)
3. **Test email sending** (2 minutes)
4. **Start watchdog service** (1 minute)
5. **Wait for notifications** (watchdog checks every 5 minutes by default)

If you still don't receive emails after 10 minutes, check `logs/watchdog.log` for errors.

---

## Support

For detailed error messages, check:
- `logs/watchdog.log` - Watchdog activity
- `logs/app.log` - Application errors
- `logs/alert_system.log` - Email sending details

Copy full error message when troubleshooting.
