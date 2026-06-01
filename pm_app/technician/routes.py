# flake8: noqa
from flask import render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
import os
import uuid


def _call_jinja_global(app, name, default=None):
    factory = app.jinja_env.globals.get(name)
    if callable(factory):
        try:
            return factory()
        except Exception:
            return default if default is not None else []
    return default if default is not None else []


def register_technician_routes(
    app,
    *,
    Activity,
    Message,
    FormAssignment,
    User,
    db,
    TECHNICIAN_PM_SECTIONS,
    TECHNICIAN_PHOTO_FIELDS,
    allowed_file,
    _check_image_magic,
    analyze_uploaded_photo_quality,
    describe_uploaded_photo,
    save_signature_image,
    collect_technician_form_details,
    build_form_insights,
    parse_activity_details_structured,
    parse_activity_kv,
    get_record_or_404,
    utcnow_naive,
    secure_filename,
    AuditLog,
):
    """Register technician-facing routes that were extracted from app_main.py."""

    @app.route("/field/rca", methods=["GET", "POST"])
    @login_required
    def field_rca():
        # Require technician role
        if not current_user.is_authenticated or getattr(current_user, "role", None) != "technician":
            abort(403)
        if request.method == "POST":
            activity_type = (request.form.get("activity_type") or "").strip().lower()
            if activity_type not in {"pm", "rca"}:
                flash("Select a valid activity type before submitting.", "warning")
                return redirect(url_for("field_rca"))

            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)

            photo_lines = []
            uploaded_photo_count = 0
            for photo in TECHNICIAN_PHOTO_FIELDS:
                field_name = f"photo_{photo['key']}"
                file_storage = request.files.get(field_name)
                if not file_storage or not file_storage.filename:
                    continue

                original_name = secure_filename(file_storage.filename)
                if not original_name:
                    flash(f"{photo['label']} has an invalid filename.", "warning")
                    return redirect(url_for("field_rca"))

                if not allowed_file(original_name):
                    flash(f"{photo['label']} must be a valid PNG, JPG, JPEG, GIF, or WebP image.", "warning")
                    return redirect(url_for("field_rca"))

                ext = original_name.rsplit(".", 1)[1].lower()
                stored_name = f"{photo['key']}_{uuid.uuid4().hex}.{ext}"
                stored_path = os.path.join(upload_folder, stored_name)

                if file_storage.stream is None:
                    flash(f"{photo['label']} has no stream data.", "warning")
                    return redirect(url_for("field_rca"))
                file_size = None
                try:
                    current = file_storage.stream.tell()
                    file_storage.stream.seek(0, os.SEEK_END)
                    file_size = file_storage.stream.tell()
                    file_storage.stream.seek(current)
                except Exception:
                    file_size = None
                if file_size is not None and file_size > app.config["MAX_PHOTO_BYTES"]:
                    flash(
                        f"{photo['label']} is too large. Maximum per photo is {app.config['MAX_PHOTO_MB']}MB.",
                        "warning",
                    )
                    return redirect(url_for("field_rca"))
                file_storage.stream.seek(0)

                if not _check_image_magic(file_storage.stream):
                    flash(f"{photo['label']} must be a valid PNG, JPG, JPEG, GIF, or WebP image file.", "warning")
                    return redirect(url_for("field_rca"))

                try:
                    file_storage.stream.seek(0)
                    from PIL import Image as _Image
                    with _Image.open(file_storage.stream) as img:
                        img.verify()
                    file_storage.stream.seek(0)
                except Exception:
                    flash(f"{photo['label']} could not be verified as a valid image. Please ensure the file is not corrupted.", "warning")
                    return redirect(url_for("field_rca"))

                file_storage.stream.seek(0)
                file_storage.save(stored_path)

                if os.path.getsize(stored_path) == 0:
                    os.remove(stored_path)
                    flash(f"{photo['label']} resulted in an empty file. Please try again.", "warning")
                    return redirect(url_for("field_rca"))

                quality = analyze_uploaded_photo_quality(stored_path)
                uploaded_photo_count += 1
                photo_url = url_for("uploaded_file", filename=stored_name)
                photo_lines.append(f"- {photo['label']}: {photo_url}")
                photo_description = describe_uploaded_photo(photo["label"], original_name)
                if quality.get("width") and quality.get("height"):
                    photo_description += f" Quality: {quality['width']}x{quality['height']}px"
                    if quality.get("megapixels") is not None:
                        photo_description += f", {quality['megapixels']}MP."
                for warning in quality.get("warnings", []):
                    photo_description += f" Photo quality warning: {warning}"
                photo_lines.append(f"  System description: {photo_description}")

            signature_name = save_signature_image(request.form.get("signature_data"), upload_folder)
            if not signature_name:
                flash("Please provide a valid technician signature before submitting.", "warning")
                return redirect(url_for("field_rca"))

            form_details = collect_technician_form_details(request.form)
            insights = build_form_insights(request.form, photo_lines, activity_type)
            if insights["errors"]:
                for error in insights["errors"]:
                    flash(error, "warning")
                return redirect(url_for("field_rca"))

            detail_lines = [form_details, "", *insights.get("_insight_lines", [])]
            # original code built insight lines inline; reuse build_insight_lines if available on app
            if hasattr(app, 'build_insight_lines'):
                detail_lines = [form_details, "", *app.build_insight_lines(insights)]
            else:
                # best-effort: append summary
                detail_lines = [form_details, "", "SMART INSIGHTS"]

            # Include photo specification lines in activity details for audit trail
            if photo_lines:
                detail_lines.append("\nPHOTO SPECIFICATIONS")
                detail_lines.extend(photo_lines)
            
            detail_lines.append(f"Technician Signature: {url_for('uploaded_file', filename=signature_name)}")

            activity = Activity(
                activity_type=activity_type,
                details="\n".join(detail_lines),
                created_by=current_user.email,
                created_at=utcnow_naive(),
                risk_score=insights["risk_score"],
                sla_deadline=insights["sla_deadline"],
            )
            db.session.add(activity)
            db.session.flush()

            db.session.add(
                Message(
                    sender_email=current_user.email,
                    sender_role="technician",
                    recipient_role="staff",
                    recipient_email=None,
                    body=(
                        f"New {activity_type.upper()} form #{activity.formatted_id} submitted by "
                        f"{current_user.display_name or current_user.email} with {uploaded_photo_count} photo(s)."
                    ),
                    created_at=utcnow_naive(),
                )
            )
            for assignee in User.query.filter(User.role == 'staff', User.is_blocked.is_(False)).all():
                db.session.add(
                    FormAssignment(
                        activity_id=activity.id,
                        assignee_email=assignee.email,
                        assignee_role=assignee.role,
                        status="pending",
                    )
                )
            db.session.commit()
            AuditLog.log(
                "activity_submitted",
                "data",
                user=current_user,
                resource_type="activity",
                resource_id=activity.id,
                details={
                    "activity_type": activity_type,
                    "photo_count": uploaded_photo_count,
                    "sla_deadline": activity.sla_deadline.isoformat() if activity.sla_deadline else None,
                },
            )

            flash(f"Form #{activity.formatted_id} submitted for staff review.", "success")
            return redirect(url_for("technician_activity_view", activity_id=activity.id))

        return render_template(
            "field_rca.html",
            pm_sections=TECHNICIAN_PM_SECTIONS,
            photo_fields=TECHNICIAN_PHOTO_FIELDS,
            slugify_label=app.jinja_env.globals.get('slugify_label'),
            is_yes_no_label=app.jinja_env.globals.get('is_yes_no_label'),
            site_master=_call_jinja_global(app, 'load_site_master', []),
        )

    @app.route("/field/submissions/")
    @login_required
    def technician_submissions():
        if not current_user.is_authenticated or getattr(current_user, "role", None) != "technician":
            abort(403)
        view_type = request.args.get("type", "all").strip().lower()
        query = Activity.query.filter(
            Activity.activity_type.in_(["pm", "rca"]),
            Activity.created_by == current_user.email,
        )
        if view_type in ("pm", "rca"):
            query = query.filter(Activity.activity_type == view_type)
        page = max(1, request.args.get("page", 1, type=int))
        pagination = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
        return render_template("technician_submissions.html", reports=pagination.items, pagination=pagination, view_type=view_type)

    @app.route("/field/rejected-reports/")
    @login_required
    def technician_rejected_reports():
        if not current_user.is_authenticated or getattr(current_user, "role", None) != "technician":
            abort(403)
        reports = Activity.query.filter(
            Activity.activity_type.in_(["pm", "rca"]),
            Activity.created_by == current_user.email,
            Activity.is_approved.is_(False),
            Activity.approved_at.is_not(None),
        ).order_by(Activity.approved_at.desc()).all()
        return render_template("technician_rejected_reports.html", reports=reports)

    @app.route("/field/report/<int:activity_id>/")
    @login_required
    def technician_activity_view(activity_id):
        if not current_user.is_authenticated or getattr(current_user, "role", None) != "technician":
            abort(403)
        activity = get_record_or_404(Activity, activity_id)
        if activity.created_by != current_user.email:
            abort(403)
        structured = parse_activity_details_structured(
            activity.details,
            expected_photo_labels=[item["label"] for item in TECHNICIAN_PHOTO_FIELDS],
        )
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
        return render_template("technician_activity_view.html", activity=activity, structured=structured)

    @app.route("/technician/calendar/")
    @login_required
    def technician_calendar():
        import calendar
        from datetime import date

        if not current_user.is_authenticated or getattr(current_user, "role", None) != "technician":
            abort(403)

        holidays = _call_jinja_global(app, 'get_public_holidays', [])
        today = utcnow_naive().date()
        selected_year = request.args.get("year", type=int) or today.year
        selected_month = request.args.get("month", type=int) or today.month
        if selected_month < 1 or selected_month > 12:
            selected_month = today.month
        try:
            view_date = date(selected_year, selected_month, 1)
        except ValueError:
            view_date = today.replace(day=1)

        month_matrix = calendar.monthcalendar(view_date.year, view_date.month)
        return render_template(
            "technician_calendar.html",
            holidays=holidays,
            month_matrix=month_matrix,
            today=today,
            view_date=view_date,
        )
