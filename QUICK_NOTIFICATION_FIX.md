# ⚡ Quick Fix: Watchdog Notifications Not Arriving

## The Problem
Your `.env` file has placeholder email credentials. Watchdog can't send notifications without them.

## The Solution (5 minutes)

### Step 1: Get Gmail App Password (3 min)
1. Go to: https://myaccount.google.com/apppasswords
2. Select: **Mail** | **Windows Computer**
3. Click **Generate**
4. Copy the 16-character password (e.g., `abcd efgh ijkl mnop`)

### Step 2: Update .env File (1 min)
Edit `c:\Users\Admin\Desktop\pm\.env`:

```ini
ALERT_EMAIL_ADDRESS=lawrencemulindwa48@gmail.com
ALERT_EMAIL_PASSWORD=abcd efgh ijkl mnop
WATCHDOG_SEND_PERIODIC_SUMMARY=1
WATCHDOG_RECIPIENT_EMAIL=lawrencemulindwa48@gmail.com
```

**Replace `abcd efgh ijkl mnop` with your actual app password!**

### Step 3: Test Configuration (1 min)
```bash
cd c:\Users\Admin\Desktop\pm
python test_email_config.py --send-test
```

### Step 4: Restart Watchdog
```bash
# Kill any running watchdog
taskkill /F /IM python.exe

# Start watchdog again
python watchdog_enterprise.py &
```

## ✅ What Should Happen
- Watchdog checks system every 5 minutes
- Critical alerts sent immediately to Gmail
- Summary emails sent every 90 minutes
- Check spam folder if not in inbox

## ⚠️ Common Issues

### "Failed to send: Username and Password not accepted"
→ You're using your regular Gmail password, not the app password!
→ Go to Google Account Security and generate a NEW app password

### "Timeout exceeded"
→ Check internet connection: `ping smtp.gmail.com`
→ Try port 587 instead of 465:
```ini
ALERT_SMTP_PORT=587
ALERT_SMTP_USE_SSL=0
ALERT_SMTP_USE_TLS=1
```

### "No emails received"
→ Check spam folder
→ Verify email went through: Look in `logs/watchdog.log`
→ Alerts have 30-minute cooldown for same issue

## 📂 Configuration Files
- `.env` - Main config (edit this!)
- `EMAIL_SETUP_GUIDE.md` - Detailed setup instructions
- `test_email_config.py` - Test script
- `logs/watchdog.log` - Watchdog activity log
- `alert_system.py` - Email sending system

## 🔗 Useful Links
- Gmail Account Security: https://myaccount.google.com/security
- App Passwords: https://myaccount.google.com/apppasswords
- Gmail Less Secure Apps: https://myaccount.google.com/connectedapps

---

**Need more help?** See `EMAIL_SETUP_GUIDE.md` for detailed troubleshooting.
