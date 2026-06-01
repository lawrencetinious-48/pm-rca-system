"""
Email alert system for the PM/RCA application.
Sends critical error notifications to the configured email address.
"""

import os
import smtplib
import ssl
import time
import logging
import html as html_module
import socket
from typing import Optional
from email.message import EmailMessage

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
# Normalize Gmail app password formatting (users often paste grouped characters with spaces)
def _normalize_app_password(value: str) -> str:
    if not value:
        return ""
    return value.strip().replace(" ", "")

def _get_alert_email_address() -> str:
    return os.getenv("ALERT_EMAIL_ADDRESS", "").strip()

def _get_alert_email_password() -> str:
    return _normalize_app_password(os.getenv("ALERT_EMAIL_PASSWORD", ""))

def _get_alert_recipient_address() -> str:
    return os.getenv("ALERT_RECIPIENT_ADDRESS", os.getenv("ALERT_EMAIL_TO", "")).strip()

def _get_smtp_host() -> str:
    return os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")

def _get_smtp_port() -> int:
    return int(os.getenv("ALERT_SMTP_PORT", "465"))

def _get_smtp_use_ssl() -> bool:
    return os.getenv("ALERT_SMTP_USE_SSL", "1") == "1"

def _get_smtp_use_tls() -> bool:
    return os.getenv("ALERT_SMTP_USE_TLS", "0") == "1"

def _get_smtp_timeout() -> int:
    return int(os.getenv("ALERT_SMTP_TIMEOUT", "2"))

def _get_alert_cooldown_seconds() -> int:
    return int(os.getenv("ALERT_COOLDOWN_SECONDS", "1800"))

def _get_max_retries() -> int:
    return int(os.getenv("ALERT_MAX_RETRIES", "1"))

def _get_retry_backoff_factor() -> int:
    return int(os.getenv("ALERT_RETRY_BACKOFF_FACTOR", "1"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("alert_system")

# ---------------------------------------------------------------------------
# Cooldown state
# ---------------------------------------------------------------------------
_last_alert_time = 0.0
_last_alert_subject = ""


def _build_html_body(message: str) -> str:
    escaped = html_module.escape(message)
    html_lines = escaped.replace("\n", "<br>\n")
    return (
        '<html>'
        '<body style="font-family:Arial,Helvetica,sans-serif;line-height:1.4;color:#111;">'
        '<h2 style="margin-bottom:0.2em;color:#2a4d8f;">PM/RCA System Watchdog Alert</h2>'
        '<div style="margin-bottom:1em;">This alert contains the full generated report below. Scroll to review the complete status information.</div>'
        '<div style="background:#f5f7fb;padding:12px;border:1px solid #d1d9e6;border-radius:6px;">'
        '<pre style="white-space:pre-wrap;word-break:break-word;font-family:Segoe UI,Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;margin:0;">'
        f'{html_lines}'
        '</pre>'
        '</div>'
        '<div style="margin-top:1em;color:#555;font-size:12px;">This is an automated alert from the PM/RCA System Watchdog.</div>'
        '</body>'
        '</html>'
    )


def send_alert(message: str, subject: str = "System Alert", recipient: Optional[str] = None) -> bool:
    """
    Send an email alert with cooldown and retry logic.

    Args:
        message: Plain text message body.
        subject: Email subject line.
        recipient: Optional recipient email address. Defaults to the configured alert address.

    Returns:
        True if the alert was sent successfully, False otherwise.
    """
    global _last_alert_time, _last_alert_subject

    email_address = _get_alert_email_address()
    email_password = _get_alert_email_password()
    if not email_address or not email_password:
        logger.warning("Alert email credentials not configured – skipping alert")
        return False

    recipient = (recipient or _get_alert_recipient_address() or email_address).strip()
    if not recipient:
        logger.warning("Alert recipient is not configured – skipping alert")
        return False

    # Cooldown check: prevent flooding with identical subject
    now = time.time()
    if now - _last_alert_time < _get_alert_cooldown_seconds() and subject == _last_alert_subject:
        logger.debug(f"Alert cooldown active for subject '{subject}' – skipping")
        return False

    # Build email with a plain-text body and an HTML alternative.
    msg = EmailMessage()
    msg['From'] = email_address
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.set_content(message, subtype='plain', charset='utf-8')
    msg.add_alternative(_build_html_body(message), subtype='html', charset='utf-8')

    # Send with retry
    for attempt in range(_get_max_retries()):
        try:
            if _get_smtp_use_ssl():
                with smtplib.SMTP_SSL(
                    _get_smtp_host(),
                    _get_smtp_port(),
                    timeout=_get_smtp_timeout(),
                    context=ssl.create_default_context(),
                ) as server:
                    server.login(email_address, email_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(_get_smtp_host(), _get_smtp_port(), timeout=_get_smtp_timeout()) as server:
                    if _get_smtp_use_tls():
                        server.starttls(context=ssl.create_default_context())
                    server.login(email_address, email_password)
                    server.send_message(msg)

            # Success – update cooldown state
            _last_alert_time = now
            _last_alert_subject = subject
            logger.info(f"Alert sent successfully: {subject}")
            return True

        except Exception as e:
            wait = _get_retry_backoff_factor() ** attempt
            logger.warning(f"Alert attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)

    logger.error(f"Failed to send alert after {_get_max_retries()} attempts: {subject}")
    return False


def send_alert_with_details(message: str, subject: str = "System Alert", details: Optional[str] = None, recipient: Optional[str] = None) -> bool:
    """
    Send an alert with optional additional details (e.g., traceback).

    Args:
        message: Short description.
        subject: Email subject.
        details: Optional longer details (appended to message).
        recipient: Optional recipient email address.

    Returns:
        True if sent, False otherwise.
    """
    full_message = message
    if details:
        full_message += f"\n\nDetails:\n{details}"
    return send_alert(full_message, subject, recipient=recipient)


# ---------------------------------------------------------------------------
# Test function (only runs when script is executed directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick test – only if credentials are set
    if _get_alert_email_address() and _get_alert_email_password():
        print("Sending test alert...")
        send_alert("This is a test alert from the PM/RCA system.", "Test Alert")
    else:
        print("Alert email not configured. Set ALERT_EMAIL_ADDRESS and ALERT_EMAIL_PASSWORD.")
