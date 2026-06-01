"""
Email utilities for the PM/RCA application.
Handles sending credential notifications and other transactional emails.
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# SMTP configuration (shared with alert_system)
SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "465"))
EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS", "").strip()
EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "").strip().replace(" ", "")


def send_activation_email(recipient_email: str, activation_url: str) -> bool:
    """
    Send account activation email with one-time setup link.

    Args:
        recipient_email: Email address of the new account.
        activation_url: Full URL to activation page (includes token).

    Returns:
        True if sent successfully, False otherwise.
    """
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.warning("Email credentials not configured – cannot send activation email")
        return False

    subject = "Activate Your Account"
    body = (
        f"Your account has been created.\n\n"
        f"Please click the link below to set your password and activate your account:\n\n"
        f"{activation_url}\n\n"
        f"This link expires in 24 hours.\n"
        f"If this was not expected, contact the administrator immediately."
    )

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info(f"Activation email sent to {recipient_email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send activation email to {recipient_email}: {exc}")
        return False


def send_password_reset_email(recipient_email: str, reset_url: str) -> bool:
    """
    Send password reset email with one-time reset link.

    Args:
        recipient_email: Email address of the account.
        reset_url: Full URL to password reset page (includes token).

    Returns:
        True if sent successfully, False otherwise.
    """
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.warning("Email credentials not configured – cannot send reset email")
        return False

    subject = "Reset Your Password"
    body = (
        f"A password reset has been requested for your account.\n\n"
        f"Please click the link below to set a new password:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour.\n"
        f"If you did not request this, contact the administrator immediately."
    )

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info(f"Password reset email sent to {recipient_email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send password reset email to {recipient_email}: {exc}")
        return False


# DEPRECATED: send_credentials_email - replaced by send_activation_email and send_password_reset_email
def send_credentials_email(recipient_email: str, username: str, password: str, action: str = "created") -> bool:
    """DEPRECATED - plaintext passwords should never be emailed.
    Use send_activation_email() for new accounts or send_password_reset_email() for resets.
    """
    logger.warning(f"send_credentials_email() called for {username} - this is deprecated and insecure")
    return False
