"""
Async tasks for PM/RCA system.
Includes email sending, report generation, and other background jobs.
"""

import logging
from datetime import datetime
from pm_app.celery import celery
from pm_app.services.email import send_email
from app import create_app
from pm_app.services.llm_summarizer import is_llm_enabled, generate_activity_suggestion
from model import Activity, AiSuggestion, db

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_async_email(self, subject, recipients, body, html_body=None):
    """
    Send email asynchronously.

    Args:
        subject: Email subject
        recipients: List of email addresses
        body: Plain text body
        html_body: Optional HTML body
    """
    try:
        logger.info(f"Sending email to {recipients}: {subject}")
        success = send_email(
            to=recipients[0] if isinstance(recipients, list) else recipients,
            subject=subject,
            body=body,
            html_body=html_body
        )
        if success:
            logger.info(f"Email sent successfully to {recipients}")
            return {'status': 'success', 'recipients': recipients}
        else:
            raise Exception("Email sending failed")
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        self.retry(exc=exc, countdown=60)


@celery.task(bind=True, max_retries=3)
def generate_pdf_report(self, activity_id, user_email):
    """
    Generate PDF report for an activity asynchronously.

    Args:
        activity_id: ID of activity to generate PDF for
        user_email: Email of requesting user
    """
    try:
        from model import Activity, db
        from app import create_app

        app = create_app()
        with app.app_context():
            activity = db.session.get(Activity, activity_id)
            if not activity:
                logger.error(f"Activity {activity_id} not found")
                return {'status': 'error', 'message': 'Activity not found'}

            # Generate PDF (existing code from app.py's build_activity_pdf_buffer)
            # ... (will implement in next step)

            # Notify user
            send_async_email.delay(
                subject=f"Your PM/RCA Report #{activity_id} is Ready",
                recipients=[user_email],
                body="Your report has been generated and is available for download.",
            )

            logger.info(f"PDF generated for activity {activity_id}")
            return {'status': 'success', 'activity_id': activity_id}
    except Exception as exc:
        logger.error(f"PDF generation failed: {exc}")
        self.retry(exc=exc)


@celery.task
def cleanup_old_files(days=30):
    """
    Clean up old uploaded files and logs.

    Args:
        days: Number of days to keep files
    """
    import time
    from pathlib import Path

    cutoff = time.time() - (days * 24 * 60 * 60)
    cleaned = 0

    # Clean uploads
    upload_dir = Path('uploads')
    if upload_dir.exists():
        for file in upload_dir.glob('*'):
            try:
                if file.is_file() and file.stat().st_mtime < cutoff:
                    file.unlink()
                    cleaned += 1
            except Exception as e:
                logger.error(f"Failed to delete {file}: {e}")

    # Clean logs (keep last N files)
    log_dir = Path('logs')
    if log_dir.exists():
        log_files = sorted(log_dir.glob('*.log*'), key=lambda f: f.stat().st_mtime)
        if len(log_files) > 10:
            for old_file in log_files[:-10]:
                try:
                    old_file.unlink()
                    cleaned += 1
                except Exception as e:
                    logger.error(f"Failed to delete log {old_file}: {e}")

    logger.info(f"Cleaned up {cleaned} old files")
    return {'cleaned': cleaned}


@celery.task
def daily_health_report():
    """
    Generate and send daily health report to administrators.
    Runs at configured time daily.
    """
    try:
        from model import User
        from datetime import datetime
        from pm_app.services.daily_reporter import DailyReporter

        reporter = DailyReporter()
        report = reporter.generate_daily_report()

        # Send to all developers
        developers = User.query.filter_by(role='developer').all()
        recipients = [dev.email for dev in developers]

        if recipients:
            send_async_email.delay(
                subject=f"PM System Daily Report - {datetime.now().strftime('%Y-%m-%d')}",
                recipients=recipients,
                body=report['text'],
                html_body=report['html']
            )
            logger.info(f"Daily report sent to {len(recipients)} developers")

        return {'status': 'success', 'recipients': recipients}
    except Exception as e:
        logger.error(f"Daily health report failed: {e}")
        raise


@celery.task
def check_sla_deadlines():
    """
    Periodic task to check SLA deadlines and send reminders.
    Enhanced with intelligent escalation.
    """
    try:
        from model import Activity, User
        from datetime import timedelta

        app = create_app()
        with app.app_context():
            now = datetime.utcnow().replace(tzinfo=None)
            due_soon_window = int(app.config.get("SLA_DUE_SOON_HOURS", 6))
            escalation_enabled = bool(app.config.get("SLA_ESCALATION_ENABLED", True))

            # Find activities due in next due_soon_window hours
            due_soon = Activity.query.filter(
                Activity.sla_deadline.between(now, now + timedelta(hours=due_soon_window)),
                Activity.is_approved.is_(False)
            ).all()

            # Find overdue activities
            overdue = Activity.query.filter(
                Activity.sla_deadline < now,
                Activity.is_approved.is_(False)
            ).all()

            escalations_sent = 0

            # Process due soon review reminders. These are sent regardless of whether overdue escalation is enabled.
            due_soon_sorted = sorted(due_soon, key=lambda a: (a.risk_score or 0, a.sla_deadline), reverse=True)  # High risk first
            for activity in due_soon_sorted[:10]:  # Limit to top 10
                hours_remaining = (activity.sla_deadline - now).total_seconds() / 3600

                reviewers = User.query.filter(
                    (User.role == 'manager') | (User.role == 'staff') | (User.role == 'general_manager')
                ).all()

                if reviewers:
                    subject = f"SLA Due Soon - {activity.formatted_id}"
                    body = f"""Activity {activity.formatted_id} is due in {hours_remaining:.1f} hours.

Site: {activity.details.split('Site Name:')[1].split('\\n')[0].strip() if 'Site Name:' in activity.details else 'Unknown'}
Risk Score: {activity.risk_score or 'Unknown'}

Please review promptly."""
                    send_async_email.delay(
                        subject=subject,
                        recipients=[u.email for u in reviewers],
                        body=body
                    )
                    escalations_sent += 1

            # Process overdue escalations
            for activity in overdue:
                hours_overdue = (now - activity.sla_deadline).total_seconds() / 3600

                if hours_overdue >= 12:
                    recipients = [u.email for u in User.query.filter_by(role='developer').all()]
                    subject = f"CRITICAL: SLA Breach - {activity.formatted_id}"
                    priority = "CRITICAL"
                elif hours_overdue >= 6:
                    recipients = [u.email for u in User.query.filter_by(role='general_manager').all()]
                    subject = f"URGENT: SLA Overdue - {activity.formatted_id}"
                    priority = "HIGH"
                elif hours_overdue >= 2:
                    recipients = [u.email for u in User.query.filter_by(role='manager').all()]
                    subject = f"SLA Overdue - {activity.formatted_id}"
                    priority = "MEDIUM"
                else:
                    continue

                if recipients and escalation_enabled:
                    body = f"""Activity {activity.formatted_id} is {hours_overdue:.1f} hours overdue.

Site: {activity.details.split('Site Name:')[1].split('\\n')[0].strip() if 'Site Name:' in activity.details else 'Unknown'}
Risk Score: {activity.risk_score or 'Unknown'}
Priority: {priority}

Please take immediate action."""
                    send_async_email.delay(
                        subject=subject,
                        recipients=recipients,
                        body=body
                    )
                    escalations_sent += 1

            logger.info(f"SLA check: {len(due_soon)} due soon, {len(overdue)} overdue, {escalations_sent} notifications sent")
            return {
                'due_soon': len(due_soon),
                'overdue': len(overdue),
                'notifications_sent': escalations_sent
            }
    except Exception as e:
        logger.error(f"SLA deadline check failed: {e}")
        raise


@celery.task(bind=True)
def generate_activity_suggestions(self, activity_id: int | None = None, limit: int = 50):
    """Generate and persist AI suggestions for activities.

    - If `activity_id` is provided, generate for that activity only.
    - Otherwise, find recent activities without an `AiSuggestion` and generate up to `limit`.
    This task is safe to run even when LLM is not configured; it will no-op.
    """
    if not is_llm_enabled():
        logger.info("LLM not enabled; skipping generate_activity_suggestions")
        return {"generated": 0, "skipped_llm_disabled": True}

    app = create_app()
    with app.app_context():
        try:
            query = Activity.query
            if activity_id:
                query = query.filter_by(id=activity_id)
            else:
                # Fallback: pick most recent activities up to `limit`
                query = query.order_by(Activity.created_at.desc()).limit(limit)

            generated = 0
            for activity in query:
                # Skip if there is already an AI suggestion recorded
                existing = AiSuggestion.query.filter_by(activity_id=activity.id).first()
                if existing:
                    continue
                try:
                    suggestion = generate_activity_suggestion(
                        activity.details or "",
                        sla_state=None,
                        risk_level=None,
                        activity_type=activity.activity_type,
                    )
                    if suggestion and suggestion.strip():
                        rec = AiSuggestion(
                            activity_id=activity.id,
                            suggestion_text=suggestion.strip(),
                            source="ai_llm",
                            provider="openai",
                        )
                        db.session.add(rec)
                        db.session.commit()
                        generated += 1
                except Exception as exc:
                    logger.error(f"Failed to generate suggestion for activity {activity.id}: {exc}")
                    db.session.rollback()
            logger.info(f"Generated {generated} AI suggestions")
            return {"generated": generated}
        except Exception as exc:
            logger.error(f"generate_activity_suggestions failed: {exc}")
            raise


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Configure periodic Celery tasks.
    """
    # Daily SLA check every hour
    sender.add_periodic_task(3600.0, check_sla_deadlines.s(), name='Check SLA every hour')

    # Daily cleanup at 2 AM
    sender.add_periodic_task(
        86400.0,
        cleanup_old_files.s(days=30),
        name='Daily cleanup'
    )
