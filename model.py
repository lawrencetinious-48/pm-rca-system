"""
Database models for the PM/RCA system.
Defines Consumable, Activity, FormAssignment, Message, User, UserSettings, AuditLog.
"""

import json
from flask_sqlalchemy import SQLAlchemy
from pm_app.services.time_utils import utcnow_naive

db = SQLAlchemy()


class UIDCounter(db.Model):
    """Database-backed counter for UID generation to avoid race conditions."""
    __tablename__ = "uid_counters"

    role = db.Column(db.String(50), primary_key=True)
    last_value = db.Column(db.Integer, nullable=False, default=0)


class PasswordResetToken(db.Model):
    """Secure password reset tokens with expiry and usage tracking."""
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    user = db.relationship('User', backref=db.backref('reset_tokens', lazy=True))

    def is_expired(self):
        return utcnow_naive() > self.expires_at

    def is_valid(self):
        return not self.used and not self.is_expired()


class BootstrapState(db.Model):
    """System bootstrap state — tracks whether first developer has been created.

    Ensures transactional safety for first-user registration.
    Only one row should ever exist; accessed under write lock.
    """
    __tablename__ = "bootstrap_state"

    id = db.Column(db.Integer, primary_key=True)
    bootstrap_complete = db.Column(db.Boolean, nullable=False, default=False)
    first_developer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    first_developer = db.relationship('User', foreign_keys=[first_developer_id], backref=db.backref('bootstrap_state', lazy=True))


class AccountActivationToken(db.Model):
    """One-time activation tokens for new account setup.

    When a new account is created, an activation token is generated
    and sent via email. User clicks link to set their own password.
    Replaces plaintext temporary password flow.
    """
    __tablename__ = "account_activation_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    token_hash = db.Column(db.String(255), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    user = db.relationship('User', backref=db.backref('activation_tokens', lazy=True))

    def is_expired(self):
        return utcnow_naive() > self.expires_at

    def is_valid(self):
        return not self.used and not self.is_expired()


class Consumable(db.Model):
    """Consumable item record (e.g., coolant, filters)."""

    __tablename__ = "consumables"
    __table_args__ = (
        db.Index("ix_consumable_created_at", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.String(20), nullable=False)
    site_name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    location = db.Column(db.String(120), nullable=True)

    signage_image_url = db.Column(db.String(300), nullable=True)
    screenshot_url = db.Column(db.String(300), nullable=True)
    before_usage_image_url = db.Column(db.String(300), nullable=True)

    # Approval / review fields to align consumables with PM/RCA workflow
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    approved_by = db.Column(db.String(150), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    treatment_given = db.Column(db.Text, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Consumable {self.site_name} ({self.site_id})>"


class Activity(db.Model):
    """PM/RCA form submission and other system activities."""

    __tablename__ = "activities"
    __table_args__ = (
        db.Index("ix_activity_created_by", "created_by"),
        db.Index("ix_activity_created_at", "created_at"),
        db.Index("ix_activity_risk_score", "risk_score"),
        db.Index("ix_activity_sla_deadline", "sla_deadline"),
        db.Index("ix_activity_type_approved", "activity_type", "is_approved"),
        db.Index("ix_activity_type_created_at", "activity_type", "created_at"),
        db.Index("ix_activity_approved_at", "approved_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    activity_type = db.Column(db.String(20), nullable=False)  # pm, rca, snag, dar, user, approval
    details = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    approved_by = db.Column(db.String(150), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    # Stored columns to avoid repeated parsing
    risk_score = db.Column(db.Integer, nullable=True)
    sla_deadline = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<Activity {self.activity_type} {self.created_at}>"

    @property
    def formatted_id(self) -> str:
        """Generate a professional formatted ID like PM-UG-2026-TEC-000043"""
        year = self.created_at.year if self.created_at else 2026
        activity_prefix = self.activity_type.upper() if self.activity_type else "UNK"

        technician_initials = ""
        if getattr(self, 'submitted_by', None) and hasattr(self.submitted_by, 'full_name'):
            name_parts = self.submitted_by.full_name.split()
            technician_initials = "".join(p[0].upper() for p in name_parts if p)[:3]
        elif self.created_by:
            local_part = self.created_by.split('@', 1)[0]
            name_parts = [p for p in local_part.replace('.', ' ').replace('_', ' ').split() if p]
            technician_initials = "".join(p[0].upper() for p in name_parts if p)[:3]

        role_prefix = technician_initials or "TEC"
        return f"{activity_prefix}-UG-{year}-{role_prefix}-{self.id:06d}"


class FormAssignment(db.Model):
    """Assignment of a PM/RCA form to a specific reviewer (staff/manager)."""

    __tablename__ = "form_assignments"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True)
    assignee_email = db.Column(db.String(150), nullable=False, index=True)
    assignee_role = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending, approved, rejected
    assigned_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    activity = db.relationship("Activity", backref="assignments")

    def __repr__(self):
        return f"<FormAssignment activity_id={self.activity_id} assignee={self.assignee_email} status={self.status}>"


class Message(db.Model):
    """Internal messaging between users (role‑based or direct)."""

    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_email = db.Column(db.String(150), nullable=False)
    sender_role = db.Column(db.String(50), nullable=False)
    recipient_role = db.Column(db.String(50), nullable=False, default="all")
    recipient_email = db.Column(db.String(150), nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    def __repr__(self):
        return f"<Message {self.sender_email} -> {self.recipient_role} {self.created_at}>"


class User(db.Model):
    """System user account."""

    __tablename__ = "users"
    __table_args__ = (
        db.Index("ix_user_created_at", "created_at"),
        db.Index("ix_user_role", "role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(12), unique=True, nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    region = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(50), nullable=False, default="staff")
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    support_desk = db.Column(db.String(100), nullable=True)
    site_operations_phone = db.Column(db.String(40), nullable=True)
    emergency_phone = db.Column(db.String(40), nullable=True)
    # Optional admin metadata
    age = db.Column(db.Integer, nullable=True)
    signature_path = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    def get_id(self):
        return str(self.id)

    @property
    def is_active(self):
        return not self.is_blocked

    @property
    def display_name(self):
        parts = [part for part in [self.first_name, self.last_name] if part]
        return " ".join(parts) if parts else self.full_name

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class UserSettings(db.Model):
    """Per‑user settings for theme, language, and custom preferences."""

    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    theme = db.Column(db.String(20), nullable=False, default="light")
    language = db.Column(db.String(10), nullable=False, default="en")
    preferences_json = db.Column(db.Text, nullable=False, default="{}")
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationship
    user = db.relationship("User", backref="settings", uselist=False)

    def get_preferences(self):
        """Return parsed preferences dictionary."""
        try:
            return json.loads(self.preferences_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_preferences(self, preferences_dict):
        """Store preferences dictionary as JSON."""
        self.preferences_json = json.dumps(preferences_dict or {})

    def __repr__(self):
        return f"<UserSettings user_id={self.user_id} theme={self.theme} language={self.language}>"


class AuditLog(db.Model):
    """Audit log for tracking security and administrative events."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        db.Index("ix_audit_timestamp", "created_at"),
        db.Index("ix_audit_user", "user_id"),
        db.Index("ix_audit_action", "action"),
        db.Index("ix_audit_ip", "ip_address"),
        db.Index("ix_audit_category", "category"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # authentication, authorization, data, system
    resource_type = db.Column(db.String(50), nullable=True)  # user, activity, file, etc.
    resource_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    # Relationship
    user = db.relationship("User", backref="audit_logs")

    @classmethod
    def log(cls, action, category, user=None, resource_type=None, resource_id=None, details=None, ip_address=None, user_agent=None):
        """
        Create and log an audit entry.

        Args:
            action: What happened (e.g., 'login_success', 'user_created')
            category: Category (authentication, authorization, data, system)
            user: User object or user_id
            resource_type: Type of resource affected
            resource_id: ID of affected resource
            details: JSON-serializable dict with extra info
            ip_address: Request IP address
            user_agent: Request user agent
        """
        try:
            user_id = user.id if hasattr(user, 'id') else user
            log_entry = cls(
                user_id=user_id,
                action=action,
                category=category,
                resource_type=resource_type,
                resource_id=resource_id,
                details=str(details) if details else None,
                ip_address=ip_address,
                user_agent=user_agent[:255] if user_agent else None,
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            # Audit failures shouldn't break main flow
            print(f"Audit log failed: {e}")

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'category': self.category,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AiSuggestion(db.Model):
    """Store AI-generated suggestions for activities without requiring schema changes to Activity.

    This separate table is used to persist LLM outputs safely and allow UI/server to display
    per-activity suggestions without altering the core Activity table schema.
    """
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        db.Index("ix_ai_suggestion_activity_id", "activity_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True)
    suggestion_text = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(50), nullable=False)  # ai_llm, ai_embedded, manual, heuristic
    provider = db.Column(db.String(80), nullable=True)  # e.g., openai
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    activity = db.relationship("Activity", backref=db.backref("ai_suggestions", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "suggestion_text": self.suggestion_text,
            "source": self.source,
            "provider": self.provider,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
