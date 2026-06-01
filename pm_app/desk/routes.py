# flake8: noqa
from datetime import datetime, timedelta
from flask import render_template, request, flash, redirect, url_for, send_file, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_
from typing import Tuple, Union
from werkzeug.wrappers import Response

from pm_app.legacy_analysis import BREACH_REASON_CATEGORIES
from pm_app.legacy_helpers import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD


def register_desk_routes(
    app,
    *,
    Activity,
    FormAssignment,
    Message,
    User,
    db,
    get_active_sla_policy,
    build_activity_review_rows,
    get_record_or_404,
    build_activity_pdf_buffer,
    parse_activity_kv,
    parse_activity_details_structured,
    utcnow_naive,
    classify_risk_level,
    extract_recommendations_from_details,
):
    def desk_activities():
        if not current_user.is_authenticated:
            abort(403)
        # assume desk role check is enforced by decorator in original app
        view_mode = (request.args.get("mode") or "rcas").strip().lower()
        if view_mode not in {"rcas", "forms", "rejected"}:
            view_mode = "rcas"
        type_filter = (request.args.get("type") or "").strip().lower()
        review_filter = (request.args.get("review") or "").strip().lower()
        search_query = (request.args.get("q") or "").strip()[:100]
        created_on = (request.args.get("date") or "").strip()
        month_filter = (request.args.get("month") or "").strip()
        risk_filter = (request.args.get("risk") or "").strip().lower()
        sla_filter = (request.args.get("sla") or "").strip().lower()

        query = Activity.query.filter(Activity.activity_type.in_(["pm", "rca"]))
        if type_filter in {"pm", "rca"}:
            query = query.filter(Activity.activity_type == type_filter)

        if view_mode == "rcas":
            query = query.filter(Activity.approved_at.is_(None))
        elif view_mode == "rejected":
            query = query.filter(Activity.is_approved.is_(False), Activity.approved_at.is_not(None))
        elif view_mode == "forms":
            if review_filter == "reviewed":
                query = query.filter(Activity.approved_at.is_not(None))
            elif review_filter == "approved":
                query = query.filter(Activity.is_approved.is_(True), Activity.approved_at.is_not(None))
            elif review_filter == "pending":
                query = query.filter(Activity.approved_at.is_(None))

        if search_query:
            like = f"%{search_query}%"
            filters = [
                Activity.details.ilike(like),
                Activity.created_by.ilike(like),
                Activity.activity_type.ilike(like),
            ]
            if search_query.isdigit():
                filters.append(Activity.id == int(search_query))
            query = query.filter(or_(*filters))
        if created_on:
            try:
                day_start = datetime.fromisoformat(created_on)
                day_end = day_start + timedelta(days=1)
                query = query.filter(Activity.created_at >= day_start, Activity.created_at < day_end)
            except Exception:
                pass
        if month_filter:
            try:
                month_start = datetime.strptime(month_filter, "%Y-%m")
                next_month = month_start.replace(day=28) + timedelta(days=4)
                month_end = next_month.replace(day=1)
                query = query.filter(Activity.created_at >= month_start, Activity.created_at < month_end)
            except Exception:
                pass
        if risk_filter == "high":
            query = query.filter(Activity.risk_score >= HIGH_RISK_THRESHOLD)
        elif risk_filter == "medium":
            query = query.filter(Activity.risk_score >= MEDIUM_RISK_THRESHOLD, Activity.risk_score < HIGH_RISK_THRESHOLD)
        elif risk_filter == "low":
            query = query.filter(or_(Activity.risk_score < MEDIUM_RISK_THRESHOLD, Activity.risk_score.is_(None)))
        if sla_filter == "overdue":
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline < utcnow_naive())
        elif sla_filter == "due_soon":
            cutoff = utcnow_naive() + timedelta(hours=get_active_sla_policy()["due_soon_hours"])
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline >= utcnow_naive(), Activity.sla_deadline <= cutoff)
        elif sla_filter == "on_track":
            cutoff = utcnow_naive() + timedelta(hours=get_active_sla_policy()["due_soon_hours"])
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline > cutoff)

        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(max(10, request.args.get("per_page", 20, type=int)), 100)
        pagination = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return render_template(
            "desk_activities.html",
            view_mode=view_mode,
            type_filter=type_filter,
            review_filter=review_filter,
            search_query=search_query,
            created_on=created_on,
            month_filter=month_filter,
            risk_filter=risk_filter,
            sla_filter=sla_filter,
            review_rows=build_activity_review_rows(pagination.items),
            pagination=pagination,
            active_sla_policy=get_active_sla_policy(),
        )

    def _current_user_is_assigned_reviewer(activity):
        if not getattr(current_user, "is_authenticated", False):
            return False
        if getattr(current_user, "role", None) not in {"manager", "general_manager"}:
            return False
        current_email = getattr(current_user, "email", None)
        if not current_email:
            return False
        return FormAssignment.query.filter(
            FormAssignment.activity_id == activity.id,
            FormAssignment.assignee_email == current_email,
            FormAssignment.status.in_(["pending", "escalated"]),
        ).first() is not None

    def _current_user_can_review_activity(activity):
        role = getattr(current_user, "role", None)
        if role in {"staff", "developer"}:
            return True
        if role in {"manager", "general_manager"}:
            return bool(app.config.get("MANAGER_CAN_APPROVE")) and _current_user_is_assigned_reviewer(activity)
        return False

    @app.route("/activity/<int:activity_id>/view")
    @login_required
    def view_activity(activity_id):
        activity = get_record_or_404(Activity, activity_id)
        if activity.activity_type not in ("pm", "rca"):
            abort(404)
        structured = parse_activity_details_structured(activity.details)
        if not any(structured.get(key) for key in ("header_rows", "sections", "insights", "photos", "signature_url")):
            values = parse_activity_kv(activity.details)
            if values:
                structured = {
                    "header_rows": list(values.items()),
                    "sections": [],
                    "insights": {},
                    "photos": [],
                    "signature_url": "",
                }
        risk_score = activity.risk_score if activity.risk_score is not None else 0
        sla_deadline = activity.sla_deadline
        now = utcnow_naive()
        if activity.approved_at:
            sla_state = "Resolved"
        elif sla_deadline and now > sla_deadline:
            sla_state = "Overdue"
        elif sla_deadline and (sla_deadline - now).total_seconds() <= get_active_sla_policy()["due_soon_hours"] * 3600:
            sla_state = "Due Soon"
        elif sla_deadline:
            sla_state = "On Track"
        else:
            sla_state = "Not Set"
        priority = build_activity_review_rows([activity])[0]
        return render_template(
            "activity_view.html",
            activity=activity,
            structured=structured,
            review_priority=priority,
            risk_score=risk_score,
            sla_state=sla_state,
            can_review_activity=_current_user_can_review_activity(activity),
        )

    @app.route("/api/activity/<int:activity_id>/suggestion")
    @login_required
    def api_activity_suggestion(activity_id):
        activity = get_record_or_404(Activity, activity_id)
        # Prefer persisted AI suggestion if available
        try:
            from model import AiSuggestion
            ai = AiSuggestion.query.filter_by(activity_id=activity.id).order_by(AiSuggestion.created_at.desc()).first()
            if ai:
                return jsonify({"status": "ok", "suggestion": ai.suggestion_text, "source": ai.source})
        except Exception:
            # Fall back to existing heuristics if AiSuggestion table is missing or query fails
            pass

        # Use existing recommendation extraction + SLA-derived suggestion as fallback
        recommendations = extract_recommendations_from_details(activity.details)
        if recommendations:
            suggestion = recommendations[0]
            source = "manual"
        else:
            # derive based on SLA and risk
            risk_score = activity.risk_score if activity.risk_score is not None else 0
            # reuse classify_risk_level and derive_sla_suggestion where available
            try:
                from pm_app.legacy_analysis import derive_sla_suggestion, classify_risk_level
                rlevel = classify_risk_level(risk_score)
                sla_state = "Resolved" if activity.approved_at else ("Overdue" if activity.sla_deadline and activity.sla_deadline < utcnow_naive() else ("Due Soon" if activity.sla_deadline else "Not Set"))
                suggestion = derive_sla_suggestion(sla_state, rlevel)
                source = "heuristic"
            except Exception:
                suggestion = "Review and add recommended actions based on observations."
                source = "heuristic"
        return jsonify({"status": "ok", "suggestion": suggestion, "source": source})

    @app.route("/activity/<int:activity_id>/approve", methods=["GET", "POST"])
    @login_required
    def approve_activity(activity_id):
        activity = get_record_or_404(Activity, activity_id)
        if request.method == "GET":
            return redirect(url_for("view_activity", activity_id=activity.id))
        breach_category = request.form.get("breach_category", "").strip().upper()
        breach_reason = request.form.get("breach_reason", "").strip()
        now_value = utcnow_naive()
        if activity.sla_deadline and now_value > activity.sla_deadline:
            if breach_category not in BREACH_REASON_CATEGORIES or not breach_reason:
                flash("SLA breached: provide a breach category and reason.", "warning")
                return redirect(url_for("view_activity", activity_id=activity.id))
        if not _current_user_can_review_activity(activity):
            flash('You are not authorised to approve this form.', 'warning')
            return redirect(url_for('view_activity', activity_id=activity.id))

        activity.is_approved = True
        activity.approved_by = current_user.email
        activity.approved_at = now_value
        if breach_category in BREACH_REASON_CATEGORIES:
            activity.details = upsert_detail_line(activity.details, "SLA Breach Category", breach_category)
        if breach_reason:
            activity.details = upsert_detail_line(activity.details, "SLA Breach Reason", breach_reason)
        assignment = FormAssignment.query.filter_by(activity_id=activity.id, assignee_email=current_user.email).first()
        if assignment:
            assignment.status = "approved"
        else:
            FormAssignment.query.filter_by(activity_id=activity.id).update({"status": "approved"})
        tech_message = Message(
            sender_email=current_user.email,
            sender_role=current_user.role,
            recipient_email=activity.created_by,
            recipient_role="technician",
            body=f"Your {activity.activity_type.upper()} form #{activity.id} has been approved by {current_user.display_name or current_user.email}.",
            created_at=utcnow_naive(),
        )
        db.session.add(tech_message)
        db.session.commit()
        flash("Activity approved", "success")
        return redirect(url_for("desk_activities"))

    @app.route("/activity/<int:activity_id>/reject", methods=["GET", "POST"])
    @login_required
    def reject_activity(activity_id):
        activity = get_record_or_404(Activity, activity_id)
        if request.method == "GET":
            return redirect(url_for("view_activity", activity_id=activity.id))
        breach_category = request.form.get("breach_category", "").strip().upper()
        breach_reason = request.form.get("breach_reason", "").strip()
        now_value = utcnow_naive()
        if activity.sla_deadline and now_value > activity.sla_deadline:
            if breach_category not in BREACH_REASON_CATEGORIES or not breach_reason:
                flash("SLA breached: provide a breach category and reason.", "warning")
                return redirect(url_for("view_activity", activity_id=activity.id))
        if not _current_user_can_review_activity(activity):
            flash('You are not authorised to reject this form.', 'warning')
            return redirect(url_for('view_activity', activity_id=activity.id))

        activity.is_approved = False
        activity.approved_by = current_user.email
        activity.approved_at = now_value
        if breach_category in BREACH_REASON_CATEGORIES:
            activity.details = upsert_detail_line(activity.details, "SLA Breach Category", breach_category)
        if breach_reason:
            activity.details = upsert_detail_line(activity.details, "SLA Breach Reason", breach_reason)
        assignment = FormAssignment.query.filter_by(activity_id=activity.id, assignee_email=current_user.email).first()
        if assignment:
            assignment.status = "rejected"
        else:
            FormAssignment.query.filter_by(activity_id=activity.id).update({"status": "rejected"})
        tech_message = Message(
            sender_email=current_user.email,
            sender_role=current_user.role,
            recipient_email=activity.created_by,
            recipient_role="technician",
            body=f"Your {activity.activity_type.upper()} form #{activity.id} has been rejected by {current_user.display_name or current_user.email}.",
            created_at=utcnow_naive(),
        )
        db.session.add(tech_message)
        db.session.commit()
        flash("Activity rejected", "warning")
        return redirect(url_for("desk_activities"))

    @app.route('/activity/<int:activity_id>/escalate', methods=['POST'])
    @login_required
    def escalate_activity(activity_id: int) -> Union[str, Response]:
        """Allow staff to escalate a pending form to managers for additional review."""
        activity = get_record_or_404(Activity, activity_id)
        # Only staff or developer may escalate
        if getattr(current_user, 'role', None) not in ('staff', 'developer'):
            flash('Only staff may escalate forms to managers.', 'warning')
            return redirect(url_for('view_activity', activity_id=activity.id))

        if activity.approved_at:
            flash('This form has already been reviewed and cannot be escalated.', 'warning')
            return redirect(url_for('view_activity', activity_id=activity.id))

        # Create manager assignments
        managers = User.query.filter(User.role == 'manager', User.is_blocked.is_(False)).all()
        if not managers:
            flash('No managers available to escalate to.', 'warning')
            return redirect(url_for('view_activity', activity_id=activity.id))

        for m in managers:
            db.session.add(FormAssignment(activity_id=activity.id, assignee_email=m.email, assignee_role=m.role, status='pending'))

        # Mark existing staff assignments as escalated
        FormAssignment.query.filter_by(activity_id=activity.id, assignee_role='staff').update({'status': 'escalated'})

        db.session.add(
            Message(
                sender_email=current_user.email,
                sender_role=current_user.role,
                recipient_role='manager',
                recipient_email=None,
                body=f"Form {activity.formatted_id} has been escalated to managers by {current_user.display_name or current_user.email}.",
                created_at=utcnow_naive(),
            )
        )
        db.session.commit()
        flash('Form escalated to managers for review.', 'success')
        return redirect(url_for('view_activity', activity_id=activity.id))

    @app.route('/message/<int:message_id>/delete', methods=['POST'])
    @login_required
    def delete_message(message_id: int) -> Union[str, Response]:
        msg = get_record_or_404(Message, message_id)
        allowed_roles = {'technician', 'staff', 'manager', 'general_manager', 'developer'}
        user_role = getattr(current_user, 'role', None)
        if user_role not in allowed_roles:
            abort(403)

        # Developers may delete any message. Other roles may delete messages they sent or that were directed to their role/email.
        if user_role == 'developer' or msg.sender_email == current_user.email or msg.recipient_email == current_user.email or (msg.recipient_role and msg.recipient_role == user_role):
            db.session.delete(msg)
            db.session.commit()
            flash('Message deleted.', 'success')
            return redirect(request.referrer or url_for('dashboard'))

        abort(403)

    @app.route("/activity/<int:activity_id>/download")
    @login_required
    def download_activity(activity_id: int) -> Union[Response, Tuple[str, int]]:
        activity = get_record_or_404(Activity, activity_id)
        buffer = build_activity_pdf_buffer(activity, app.config["UPLOAD_FOLDER"])
        return send_file(buffer, as_attachment=True, download_name=f"{activity.activity_type}_form_{activity.id}.pdf", mimetype="application/pdf")

    # =========================================================================
    # Admin & Developer Routes (full original)
    # =========================================================================
