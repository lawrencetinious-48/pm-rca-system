"""
Audit logging for PM/RCA system.
Tracks all significant security and data events.
"""

from datetime import datetime
from model import db


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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

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
            log_entry = cls(
                user_id=user.id if hasattr(user, 'id') else user,
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
            # Don't raise - audit failures shouldn't break main flow
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
