from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
import time as _time


@dataclass
class MaintenanceSummary:
    holiday_created: int = 0
    sla_escalations: int = 0
    due_soon_alerts: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "holiday_created": self.holiday_created,
            "sla_escalations": self.sla_escalations,
            "due_soon_alerts": self.due_soon_alerts,
        }


class MaintenanceService:
    def __init__(
        self,
        *,
        db,
        activity_model,
        message_model,
        user_model,
        create_activity: Callable[[str, str], None],
        get_public_holidays: Callable[[], list[dict]],
        utcnow_naive: Callable[[], datetime],
        high_risk_threshold: int,
        sla_scan_cooldown_seconds: int,
        due_soon_hours: int,
        due_soon_alert_cooldown_hours: int = 6,
        overdue_escalation_cooldown_hours: int = 3,
        auto_escalation_enabled: bool = False,
    ):
        self.db = db
        self.activity_model = activity_model
        self.message_model = message_model
        self.user_model = user_model
        self.create_activity = create_activity
        self.get_public_holidays = get_public_holidays
        self.utcnow_naive = utcnow_naive
        self.high_risk_threshold = high_risk_threshold
        self.sla_scan_cooldown_seconds = int(sla_scan_cooldown_seconds)
        self.due_soon_hours = max(1, int(due_soon_hours))
        self.due_soon_alert_cooldown_hours = max(1, int(due_soon_alert_cooldown_hours))
        self.overdue_escalation_cooldown_hours = max(1, int(overdue_escalation_cooldown_hours))
        self.auto_escalation_enabled = bool(auto_escalation_enabled)
        self._last_sla_scan_at = 0.0
        # Holiday greeting only needs to be checked once per hour at most
        self._holiday_check_cooldown_seconds = 3600
        self._last_holiday_check_at = 0.0

    def run_all(self, *, respect_cooldown: bool = True) -> MaintenanceSummary:
        summary = MaintenanceSummary()
        summary.holiday_created += self.ensure_public_holiday_greeting_message()
        summary.due_soon_alerts += self.ensure_due_soon_alerts(respect_cooldown=respect_cooldown)
        summary.sla_escalations += self.ensure_sla_escalations(respect_cooldown=respect_cooldown)
        return summary

    def ensure_due_soon_alerts(self, *, respect_cooldown: bool = True) -> int:
        now_epoch = _time.time()
        if respect_cooldown and (now_epoch - self._last_sla_scan_at) < self.sla_scan_cooldown_seconds:
            return 0

        now = self.utcnow_naive()
        due_cutoff = now + timedelta(hours=self.due_soon_hours)
        technician_emails_query = self.db.session.query(self.user_model.email).filter(self.user_model.role == "technician")
        due_soon_items = self.activity_model.query.filter(
            self.activity_model.activity_type.in_(["pm", "rca"]),
            self.activity_model.approved_at.is_(None),
            self.activity_model.created_by.in_(technician_emails_query),
            self.activity_model.sla_deadline.is_not(None),
            self.activity_model.sla_deadline >= now,
            self.activity_model.sla_deadline <= due_cutoff,
        ).all()

        alerted_count = 0
        for item in due_soon_items:
            marker = f"SLA_DUE_SOON_ACTIVITY_{item.id}"
            role_alerted = False
            for target_role in ["staff", "manager", "general_manager"]:
                recent_cutoff = now - timedelta(hours=self.due_soon_alert_cooldown_hours)
                already_sent = self.message_model.query.filter(
                    self.message_model.recipient_role == target_role,
                    self.message_model.created_at >= recent_cutoff,
                    self.message_model.body.ilike(f"%{marker}%"),
                ).first()
                if already_sent:
                    continue

                # Include full form details to provide context to reviewers (truncate to avoid massive messages)
                details_text = (getattr(item, 'details', '') or '')
                if details_text:
                    snippet = details_text if len(details_text) <= 4000 else details_text[:4000] + "\n...[truncated]"
                    details_snippet = f"\n\nForm details:\n{snippet}"
                else:
                    details_snippet = ""

                body = (
                    f"{marker}\n"
                    f"SLA due soon: {item.activity_type.upper()} form #{item.id} approaches deadline.\n"
                    f"Submitted by: {item.created_by or 'Unknown'}\n"
                    f"Created at: {item.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"SLA deadline: {item.sla_deadline.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "Please prioritize review before breach."
                    f"{details_snippet}"
                )
                self.db.session.add(
                    self.message_model(
                        sender_email="system@soliton",
                        sender_role="system",
                        recipient_role=target_role,
                        recipient_email=None,
                        body=body,
                        created_at=now,
                    )
                )
                role_alerted = True

            if role_alerted:
                self.create_activity("alert", f"System sent due-soon SLA alert for form #{item.id}")
                self.db.session.commit()
                alerted_count += 1

        return alerted_count

    def ensure_sla_escalations(self, *, respect_cooldown: bool = True) -> int:
        now_epoch = _time.time()
        if respect_cooldown and (now_epoch - self._last_sla_scan_at) < self.sla_scan_cooldown_seconds:
            return 0
        self._last_sla_scan_at = now_epoch

        now = self.utcnow_naive()
        technician_emails_query = self.db.session.query(self.user_model.email).filter(self.user_model.role == "technician")
        pending_items = self.activity_model.query.filter(
            self.activity_model.activity_type.in_(["pm", "rca"]),
            self.activity_model.approved_at.is_(None),
            self.activity_model.created_by.in_(technician_emails_query),
            self.activity_model.sla_deadline.is_not(None),
            self.activity_model.sla_deadline < now,
        ).all()

        escalated_count = 0
        if not self.auto_escalation_enabled:
            return 0

        for item in pending_items:
            marker = f"SLA_ESCALATION_ACTIVITY_{item.id}"
            recent_cutoff = now - timedelta(hours=self.overdue_escalation_cooldown_hours)
            already_sent = self.message_model.query.filter(
                self.message_model.recipient_role == "manager",
                self.message_model.created_at >= recent_cutoff,
                self.message_model.body.ilike(f"%{marker}%"),
            ).first()
            if already_sent:
                continue

            # Include the original form details for context in escalations (truncate to reasonable length)
            details_text = (getattr(item, 'details', '') or '')
            if details_text:
                snippet = details_text if len(details_text) <= 8000 else details_text[:8000] + "\n...[truncated]"
                details_snippet = f"\n\nForm details:\n{snippet}"
            else:
                details_snippet = ""

            body = (
                f"{marker}\n"
                f"SLA escalation: {item.activity_type.upper()} form #{item.id} is overdue.\n"
                f"Submitted by: {item.created_by or 'Unknown'}\n"
                f"Created at: {item.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Please prioritize immediate review."
                f"{details_snippet}"
            )

            self.db.session.add(
                self.message_model(
                    sender_email="system@soliton",
                    sender_role="system",
                    recipient_role="manager",
                    recipient_email=None,
                    body=body,
                    created_at=now,
                )
            )

            self.create_activity("escalation", f"System escalated overdue high-risk form #{item.id}")
            self.db.session.commit()
            escalated_count += 1

        return escalated_count

    def ensure_public_holiday_greeting_message(self) -> int:
        now_epoch = _time.time()
        if (now_epoch - self._last_holiday_check_at) < self._holiday_check_cooldown_seconds:
            return 0
        self._last_holiday_check_at = now_epoch

        today_utc = self.utcnow_naive()
        today_iso = today_utc.date().isoformat()
        holiday_today = next((item for item in self.get_public_holidays() if item.get("date") == today_iso), None)
        if not holiday_today:
            return 0

        start_day = datetime.combine(today_utc.date(), datetime.min.time())
        end_day = start_day + timedelta(days=1)

        existing = self.message_model.query.filter(
            self.message_model.sender_role == "system",
            self.message_model.recipient_role == "all",
            self.message_model.created_at >= start_day,
            self.message_model.created_at < end_day,
            self.message_model.body.ilike(f"%{holiday_today['name']}%"),
        ).first()
        if existing:
            return 0

        greeting = self.message_model(
            sender_email="system@soliton",
            sender_role="system",
            recipient_role="all",
            recipient_email=None,
            body=f"Happy {holiday_today['name']}! Wishing everyone a peaceful and productive public holiday.",
            created_at=today_utc,
        )
        self.db.session.add(greeting)
        self.db.session.commit()
        return 1
