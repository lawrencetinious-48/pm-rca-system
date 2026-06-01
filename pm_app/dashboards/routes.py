# flake8: noqa
"""Dashboard routes module."""
from datetime import datetime, timedelta

from flask import abort, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from pm_app.services.time_utils import utcnow_naive


def register_dashboard_routes(app, *, user_model, activity_model, message_model, db, normalize_role, is_technician_role, get_live_dashboard_counts, calculate_notification_count, create_activity, get_active_sla_policy):
    """Register dashboard-related routes with the app."""

    def _as_preferences_dict(user_settings):
        if not user_settings:
            return {}
        prefs = user_settings.get_preferences()
        return prefs if isinstance(prefs, dict) else {}

    def _build_monthly_archive():
        cutoff = utcnow_naive() - timedelta(days=540)
        month_buckets = {}
        for activity in activity_model.query.filter(
            activity_model.activity_type.in_(["pm", "rca"]),
            activity_model.created_at >= cutoff,
        ).order_by(activity_model.created_at.desc()).all():
            month_key = activity.created_at.strftime("%Y-%m")
            bucket = month_buckets.setdefault(month_key, {
                "key": month_key,
                "label": datetime.strptime(month_key, "%Y-%m").strftime("%B %Y"),
                "total": 0,
                "pending": 0,
                "approved": 0,
                "rejected": 0,
            })
            bucket["total"] += 1
            if activity.approved_at is None:
                bucket["pending"] += 1
            elif activity.is_approved:
                bucket["approved"] += 1
            else:
                bucket["rejected"] += 1

        archive_rows = list(month_buckets.values())
        archive_rows.sort(key=lambda item: item["key"], reverse=True)
        return archive_rows[:12]

    def _staff_review_analytics():
        now = utcnow_naive()
        field_base = activity_model.query.filter(activity_model.activity_type.in_(["pm", "rca"]))
        pending_base = field_base.filter(activity_model.approved_at.is_(None))
        pending_items = pending_base.order_by(activity_model.created_at.desc()).limit(200).all()
        pending_count = len(pending_items)
        avg_risk = 0
        if pending_items:
            avg_risk = round(sum((item.risk_score or 0) for item in pending_items) / pending_count)
        overdue_count = sum(1 for item in pending_items if item.sla_deadline and item.sla_deadline < now)
        high_risk_count = sum(1 for item in pending_items if (item.risk_score or 0) >= 70)
        rca_count = sum(1 for item in pending_items if item.activity_type == "rca")
        oldest_pending_hours = 0
        if pending_items:
            oldest = min((item.created_at for item in pending_items if item.created_at), default=None)
            if oldest:
                oldest_pending_hours = max(0, int((now - oldest).total_seconds() // 3600))
        if overdue_count:
            recommendation = "Start with overdue forms, then high-risk RCA items."
        elif high_risk_count:
            recommendation = "High-risk pending forms should be reviewed first."
        elif pending_count:
            recommendation = "Queue is active; keep reviewing newest pending forms."
        else:
            recommendation = "No pending technician forms need review right now."
        return {
            "pending": pending_count,
            "avg_risk": avg_risk,
            "overdue": overdue_count,
            "high_risk": high_risk_count,
            "rca": rca_count,
            "oldest_pending_hours": oldest_pending_hours,
            "recommendation": recommendation,
        }

    @app.route("/dashboard/")
    @login_required
    def dashboard():
        live_counts = get_live_dashboard_counts() or {}
        active_sla_policy = get_active_sla_policy()
        dashboard_counts = {
            "users_total": live_counts.get("users_total", 0),
            "blocked_users": live_counts.get("blocked_users", 0),
            "technician_users": live_counts.get("technician_users", 0),
            "staff_users": live_counts.get("staff_users", 0),
            "manager_users": live_counts.get("manager_users", 0),
            "general_manager_users": live_counts.get("general_manager_users", 0),
        }

        if is_technician_role(current_user.role):
            recent_submissions = (
                activity_model.query.filter(
                    activity_model.activity_type.in_(["pm", "rca"]),
                    activity_model.created_by == current_user.email,
                )
                .order_by(activity_model.created_at.desc())
                .limit(8)
                .all()
            )
            return render_template(
                "technician_dashboard.html",
                user_name=current_user.display_name,
                technician_stats={
                    "pm": live_counts.get("technician_pm", 0),
                    "rca": live_counts.get("technician_rca", 0),
                    "consumables": live_counts.get("technician_consumables", 0),
                    "total": live_counts.get("technician_total", 0),
                    "rejected": live_counts.get("technician_rejected", 0),
                },
                recent_submissions=recent_submissions,
            )

        consumables_count = live_counts.get("consumables_count", 0)
        total_rcas = live_counts.get("total_rcas", 0)
        total_rcas_pending = activity_model.query.filter_by(activity_type="rca", is_approved=False).count()
        total_rcas_approved = activity_model.query.filter_by(activity_type="rca", is_approved=True).count()
        total_snags = live_counts.get("total_snags", 0)
        total_dars = live_counts.get("total_dars", 0)
        total_pms = live_counts.get("total_pms", 0)

        recent_activity = activity_model.query.order_by(activity_model.created_at.desc()).limit(10).all()
        pending_pm_rcas = live_counts.get("pending_pm_rcas", 0)
        high_risk_pending_pm_rcas = live_counts.get("high_risk_pending_pm_rcas", 0)
        sla_overdue_pm_rcas = live_counts.get("sla_overdue_pm_rcas", 0)
        approved_pm_forms = live_counts.get("approved_pm_forms", 0)
        rejected_pm_rcas = live_counts.get("rejected_pm_rcas", 0)

        # Use config-based sharing info to avoid circular import
        share_context = current_app.config.get("_share_context", {
            "public_base_url": request.host_url,
            "login_url": url_for("technician_login", _external=True),
            "is_public": False
        })
        technician_login_url = share_context.get("login_url", url_for("technician_login", _external=True))
        share_link_is_public = bool(share_context.get("is_public", False))

        technician_emails_query = db.session.query(user_model.email).filter(user_model.role == "technician")
        approved_rca_forms = (
            activity_model.query.filter(
                activity_model.activity_type == "rca",
                activity_model.created_by.in_(technician_emails_query),
                activity_model.is_approved.is_(True),
                activity_model.approved_at.is_not(None),
            ).count()
        )
        reviewed_rca_forms = (
            activity_model.query.filter(
                activity_model.activity_type == "rca",
                activity_model.created_by.in_(technician_emails_query),
                activity_model.approved_at.is_not(None),
            ).count()
        )

        current_role = normalize_role(current_user.role)
        if current_role == "staff":
            # Paginate latest technician submissions so staff can page forward/back
            page = max(1, request.args.get("page", 1, type=int))
            per_page = min(max(3, request.args.get("per_page", 6, type=int)), 50)
            query = (
                activity_model.query.filter(activity_model.activity_type.in_(["pm", "rca"]))
                .order_by(activity_model.created_at.desc())
            )
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            recent_field_submissions = pagination.items
            return render_template(
                "staff_dashboard.html",
                user_name=current_user.display_name,
                pending_pm_rcas=pending_pm_rcas,
                high_risk_pending_pm_rcas=high_risk_pending_pm_rcas,
                sla_overdue_pm_rcas=sla_overdue_pm_rcas,
                approved_pm_forms=approved_pm_forms,
                rejected_pm_rcas=rejected_pm_rcas,
                consumables_count=consumables_count,
                staff_has_form_data=(pending_pm_rcas + approved_pm_forms + rejected_pm_rcas) > 0,
                active_sla_policy=active_sla_policy,
                recent_field_submissions=recent_field_submissions,
                review_analytics=_staff_review_analytics(),
                pagination=pagination,
            )

        if current_role == "manager":
            return render_template(
                "manager_dashboard.html",
                user_name=current_user.display_name,
                pending_pm_rcas=pending_pm_rcas,
                high_risk_pending_pm_rcas=high_risk_pending_pm_rcas,
                sla_overdue_pm_rcas=sla_overdue_pm_rcas,
                approved_pm_forms=approved_pm_forms,
                rejected_pm_rcas=rejected_pm_rcas,
                reviewed_rca_forms=reviewed_rca_forms,
                consumables_count=consumables_count,
                staff_has_form_data=(pending_pm_rcas + approved_pm_forms + rejected_pm_rcas) > 0,
                active_sla_policy=active_sla_policy,
                monthly_archive=_build_monthly_archive(),
            )

        if current_role == "general_manager":
            return render_template(
                "general_manager_dashboard.html",
                user_name=current_user.display_name,
                approved_rca_forms=approved_rca_forms,
                reviewed_rca_forms=reviewed_rca_forms,
                consumables_count=consumables_count,
                active_sla_policy=active_sla_policy,
                monthly_archive=_build_monthly_archive(),
            )

        if current_role == "admin":
            return render_template(
                "admin_dashboard.html",
                user_name=current_user.display_name,
                dashboard_counts=dashboard_counts,
                technician_login_url=technician_login_url,
                share_link_is_public=share_link_is_public,
            )

        if current_role == "developer":
            return render_template(
                "developer_role_dashboard.html",
                user_name=current_user.display_name,
                dashboard_counts=dashboard_counts,
                technician_login_url=technician_login_url,
                share_link_is_public=share_link_is_public,
                current_role='admin',
            )

        return render_template(
            "dashboard.html",
            user_name=current_user.display_name,
            stats={
                "consumables": consumables_count,
                "rcas": total_rcas,
                "rcas_pending": total_rcas_pending,
                "rcas_approved": total_rcas_approved,
                "snags": total_snags,
                "dars": total_dars,
                "pms": total_pms,
            },
            recent_activity=recent_activity,
            pending_pm_rcas=pending_pm_rcas,
            high_risk_pending_pm_rcas=high_risk_pending_pm_rcas,
            sla_overdue_pm_rcas=sla_overdue_pm_rcas,
            approved_pm_forms=approved_pm_forms,
            rejected_pm_rcas=rejected_pm_rcas,
            staff_has_form_data=(pending_pm_rcas + approved_pm_forms + rejected_pm_rcas) > 0,
            dashboard_counts=dashboard_counts,
            is_technician=False,
            technician_login_url=technician_login_url,
            share_link_is_public=share_link_is_public,
        )

    @app.route("/activities/")
    @login_required
    def activities():
        activity_type = request.args.get('type')
        q = activity_model.query
        if activity_type:
            q = q.filter_by(activity_type=activity_type)
        items = q.order_by(activity_model.created_at.desc()).all()
        return render_template("activities.html", activities=items, activity_type=activity_type, is_technician=is_technician_role(current_user.role))

    @app.route("/notifications/")
    @login_required
    def notifications():
        session["notifications_last_seen_at"] = utcnow_naive().isoformat(timespec="seconds")
        from model import UserSettings

        current_role = normalize_role(current_user.role)
        inbox_roles = {current_role, "all"}
        items = activity_model.query.order_by(activity_model.created_at.desc()).limit(80).all()
        user_settings = db.session.query(UserSettings).filter_by(user_id=current_user.id).first()
        hidden_ids = set()
        if user_settings:
            prefs = _as_preferences_dict(user_settings)
            raw_hidden = prefs.get("hidden_message_ids", [])
            if isinstance(raw_hidden, list):
                for value in raw_hidden:
                    try:
                        hidden_ids.add(int(value))
                    except (TypeError, ValueError):
                        continue

        messages_query = message_model.query.filter(
            (message_model.recipient_role.in_(inbox_roles))
            | (message_model.recipient_email == current_user.email)
            | (message_model.sender_email == current_user.email)
        )
        if hidden_ids:
            messages_query = messages_query.filter(~message_model.id.in_(hidden_ids))

        messages = messages_query.order_by(message_model.created_at.desc()).limit(80).all()

        recipient_options_by_role = {
            "technician": ["staff", "developer", "manager"],
        }
        default_options = ["all", "developer", "staff", "technician", "manager", "general_manager"]
        recipient_options = recipient_options_by_role.get(current_role, default_options)

        return render_template(
            "notifications.html",
            activities=items,
            messages=messages,
            recipient_options=recipient_options,
        )

    @app.route("/notifications/messages/send", methods=["GET", "POST"])
    @login_required
    def send_system_message():
        if request.method == "GET":
            return redirect(url_for("notifications"))

        recipient_role = (request.form.get("recipient_role") or "all").strip().lower()
        body = (request.form.get("message_body") or "").strip()
        current_role = normalize_role(current_user.role)

        allowed_roles_by_sender = {
            "technician": {"staff", "developer", "manager"},
        }
        default_allowed_roles = {"all", "developer", "manager", "general_manager", "staff", "technician"}
        allowed_roles = allowed_roles_by_sender.get(current_role, default_allowed_roles)

        if recipient_role not in allowed_roles:
            flash("Invalid recipient role selected.", "warning")
            return redirect(url_for("notifications"))
        if not body:
            flash("Message body is required.", "warning")
            return redirect(url_for("notifications"))

        message = message_model(
            sender_email=current_user.email,
            sender_role=current_role,
            recipient_role=recipient_role,
            recipient_email=None,
            body=body,
            created_at=utcnow_naive(),
        )
        db.session.add(message)
        db.session.commit()

        create_activity("message", f"{current_user.email} sent a message to {recipient_role}")
        flash("Message sent successfully.", "success")
        return redirect(url_for("notifications"))

    @app.route("/notifications/messages/<int:message_id>/delete", methods=["POST"])
    @login_required
    def delete_system_message(message_id):
        from model import UserSettings

        current_role = normalize_role(current_user.role)
        message = db.session.get(message_model, message_id)
        if message is None:
            abort(404)

        allowed_roles = {"technician", "staff", "manager", "general_manager", "developer", "admin"}
        if current_role not in allowed_roles:
            flash("You are not authorised to delete this message.", "warning")
            return redirect(url_for("notifications"))

        is_sender = message.sender_email == current_user.email
        is_power_user = current_role in {"developer", "admin"}

        if is_power_user and not is_sender:
            db.session.delete(message)
            db.session.commit()
            create_activity("message", f"{current_user.email} permanently deleted message #{message_id}")
            flash("Message deleted.", "success")
            return redirect(url_for("notifications"))

        user_settings = db.session.query(UserSettings).filter_by(user_id=current_user.id).first()
        if not user_settings:
            user_settings = UserSettings(user_id=current_user.id)
            db.session.add(user_settings)

        preferences = _as_preferences_dict(user_settings)
        hidden_ids = preferences.get("hidden_message_ids", [])
        if not isinstance(hidden_ids, list):
            hidden_ids = []
        if message_id not in hidden_ids:
            hidden_ids.append(message_id)
        preferences["hidden_message_ids"] = hidden_ids
        user_settings.set_preferences(preferences)
        db.session.commit()
        create_activity("message", f"{current_user.email} hid message #{message_id} from their inbox")
        flash("Message hidden from your inbox.", "success")
        return redirect(url_for("notifications"))

    @app.route("/settings/", methods=["GET", "POST"])
    @login_required
    def settings_page():
        from model import UserSettings
        current_role = normalize_role(current_user.role)
        can_manage_sla = current_role in {"staff", "manager", "general_manager", "developer"}
        active_sla_policy = get_active_sla_policy()
        user_settings = db.session.query(UserSettings).filter_by(user_id=current_user.id).first()
        current_preferences = _as_preferences_dict(user_settings)
        current_sla_policy = current_preferences.get("sla_policy")
        if not isinstance(current_sla_policy, dict):
            current_sla_policy = active_sla_policy.copy()

        if request.method == "POST":
            save_section = (request.form.get("save_section") or "preferences").strip().lower()

            if save_section == "change_password":
                if current_user.role != "admin":
                    flash("Password updates are managed by an administrator.", "warning")
                    return redirect(url_for("settings_page"))

                current_password = (request.form.get("current_password") or "").strip()
                new_password = (request.form.get("new_password") or "").strip()
                confirm_password = (request.form.get("confirm_password") or "").strip()

                if not current_password or not new_password or not confirm_password:
                    flash("Current password, new password, and confirmation are required.", "warning")
                    return redirect(url_for("settings_page"))

                if not current_user.password_hash or not check_password_hash(current_user.password_hash, current_password):
                    flash("Current password is incorrect.", "warning")
                    return redirect(url_for("settings_page"))

                if len(new_password) < 8:
                    flash("New password must be at least 8 characters long.", "warning")
                    return redirect(url_for("settings_page"))

                if new_password != confirm_password:
                    flash("New password and confirmation do not match.", "warning")
                    return redirect(url_for("settings_page"))

                current_user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash("Password updated successfully.", "success")
                return redirect(url_for("settings_page"))

            language = (request.form.get("language") or "").strip().lower()
            theme = (request.form.get("theme") or "").strip().lower()

            supported_languages = current_app.config.get("SUPPORTED_LANGUAGES", {"en": {}, "sw": {}, "fr": {}, "ar": {}})
            allowed_languages = set(supported_languages.keys())
            allowed_themes = {"light", "dark"}

            if language in allowed_languages:
                session["language"] = language
            if theme in allowed_themes:
                session["theme"] = theme

            if not user_settings:
                user_settings = UserSettings(user_id=current_user.id)
                db.session.add(user_settings)

            if language in allowed_languages:
                user_settings.language = language
            if theme in allowed_themes:
                user_settings.theme = theme

            if can_manage_sla and (request.form.get("save_section") or "") == "sla_policy":
                sla_enabled = (request.form.get("sla_enabled") or "inactive").strip().lower() == "active"
                policy_agreed = bool(request.form.get("sla_policy_agreed"))

                try:
                    standard_hours = int(request.form.get("sla_standard_hours") or active_sla_policy["standard_hours"])
                    critical_hours = int(request.form.get("sla_critical_hours") or active_sla_policy["critical_hours"])
                    due_soon_hours = int(request.form.get("sla_due_soon_hours") or active_sla_policy["due_soon_hours"])
                except ValueError:
                    flash("SLA hours must be valid whole numbers.", "warning")
                    return redirect(url_for("settings_page"))

                if standard_hours < 1 or standard_hours > 168 or critical_hours < 1 or critical_hours > 168:
                    flash("SLA review hours must stay between 1 and 168 hours.", "warning")
                    return redirect(url_for("settings_page"))
                if due_soon_hours < 1 or due_soon_hours > min(72, standard_hours, critical_hours):
                    flash("Due soon hours must be at least 1 and no greater than the active SLA windows.", "warning")
                    return redirect(url_for("settings_page"))
                if not policy_agreed:
                    flash("You must agree to the SLA policy before saving it.", "warning")
                    return redirect(url_for("settings_page"))

                preferences = _as_preferences_dict(user_settings)
                preferences["sla_policy"] = {
                    "enabled": sla_enabled,
                    "standard_hours": standard_hours,
                    "critical_hours": critical_hours,
                    "due_soon_hours": due_soon_hours,
                    "policy_agreed": True,
                    "updated_at": utcnow_naive().isoformat(timespec="seconds"),
                    "updated_by": current_user.display_name or current_user.email,
                    "updated_role": current_role,
                    "source": "saved",
                }
                user_settings.set_preferences(preferences)

            db.session.commit()
            flash("Settings updated", "success")
            return redirect(url_for("settings_page"))

        if user_settings:
            session["language"] = user_settings.language
            session["theme"] = user_settings.theme

        return render_template(
            "settings.html",
            active_sla_policy=active_sla_policy,
            current_sla_policy=current_sla_policy,
            can_manage_sla=can_manage_sla,
        )
