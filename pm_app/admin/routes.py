# flake8: noqa
from flask import render_template, request, flash, redirect, url_for, current_app, jsonify, session, abort
from flask_login import login_required, current_user
from datetime import timedelta
from pm_app.legacy_analysis import apply_user_search
from pm_app.legacy_helpers import AVATAR_OPTIONS, AVATAR_ICON_MAP, normalize_role_access_matrix, DEFAULT_ROLE_ACCESS_MATRIX
from pm_app.users import developer_required


def register_admin_routes(
    app,
    *,
    User,
    UserSettings,
    Activity,
    PasswordResetToken,
    db,
    create_activity,
    normalize_photo_library_controls,
    LOGIN_MATRIX_KEYS,
    normalize_role,
    VALID_ACCOUNT_ROLES,
    AVATAR_KEYS,
    get_record_or_404,
    send_password_reset_email,
    generate_password_hash,
    secrets,
    utcnow_naive,
    AuditLog,
):
    # Developer-only creation endpoints
    def _developer_user_context():
        try:
            search_query, users, grouped, pagination = apply_user_search(request.args.get("q"))
            upload_limits = {
                "max_photo_mb": app.config.get("MAX_PHOTO_MB", 10),
                "max_upload_mb": app.config.get("MAX_UPLOAD_MB", 256),
                "min_upload_mb": 64,
            }
            photo_library_controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
            sla_policy_settings = {
                "standard_hours": app.config.get("SLA_STANDARD_HOURS", 24),
                "critical_hours": app.config.get("SLA_CRITICAL_HOURS", 72),
                "due_soon_hours": app.config.get("SLA_DUE_SOON_HOURS", 24),
                "escalation_enabled": app.config.get("SLA_ESCALATION_ENABLED", True),
            }
            user_ids = [user.id for user in users if getattr(user, "id", None) is not None]
            settings_rows = UserSettings.query.filter(UserSettings.user_id.in_(user_ids)).all() if user_ids else []
            user_settings_map = {
                row.user_id: row.get_preferences() if hasattr(row, "get_preferences") else {}
                for row in settings_rows
            }
            avatar_choice_map = {}
            for user in users:
                prefs = user_settings_map.get(user.id) or {}
                avatar_key = prefs.get("profile_avatar") if isinstance(prefs, dict) else None
                if avatar_key not in AVATAR_KEYS:
                    avatar_key = "neutral"
                avatar_choice_map[user.id] = avatar_key

            privileged_roles = ("developer", "admin", "general_manager", "manager")
            total_users = User.query.count()
            privileged_user_count = User.query.filter(User.role.in_(privileged_roles)).count()
            blocked_user_count = User.query.filter_by(is_blocked=True).count()
            privileged_user_ratio = int((privileged_user_count / total_users * 100) if total_users else 0)

            role_breakdown = {}
            for user in users:
                role_breakdown[user.role] = role_breakdown.get(user.role, 0) + 1

            configured_role_matrix = app.config.get("ROLE_ACCESS_MATRIX", {})
            normalized_role_matrix = normalize_role_access_matrix(configured_role_matrix)
            matrix_issues = []
            matrix_open_entries = 0
            for matrix_key in LOGIN_MATRIX_KEYS:
                allowed = set(normalized_role_matrix.get(matrix_key, []))
                default_allowed = set(DEFAULT_ROLE_ACCESS_MATRIX.get(matrix_key, []))
                extra_roles = sorted(allowed - default_allowed)
                if extra_roles:
                    matrix_open_entries += 1
                    matrix_issues.append(f"{matrix_key.title()} login also permits {', '.join(extra_roles)}")
                if matrix_key == "developer" and allowed != {"developer"}:
                    matrix_issues.append("Developer login should only allow developers.")
                if matrix_key == "staff" and "developer" in allowed:
                    matrix_issues.append("Staff login should not allow developer accounts.")
                if matrix_key == "technician" and allowed != {"technician"}:
                    matrix_issues.append("Technician login should be reserved for technicians only.")
            role_matrix_summary = {
                "entry_count": len(LOGIN_MATRIX_KEYS),
                "open_entry_count": matrix_open_entries,
                "issue_count": len(matrix_issues),
                "issues": matrix_issues,
                "is_secure": len(matrix_issues) == 0,
            }

            same_site_value = str(app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax")
            security_posture = {
                "session_cookie_secure": bool(app.config.get("SESSION_COOKIE_SECURE")),
                "remember_cookie_secure": bool(app.config.get("REMEMBER_COOKIE_SECURE")),
                "preferred_url_scheme": str(app.config.get("PREFERRED_URL_SCHEME", "http") or "http").lower(),
                "same_site": same_site_value,
                "same_site_policy": same_site_value,
                "csrf_protection": bool(app.config.get("WTF_CSRF_ENABLED", True)),
                "http_only": bool(app.config.get("SESSION_COOKIE_HTTPONLY", True)),
            }
            score = 0
            score += 20 if security_posture["session_cookie_secure"] else 0
            score += 20 if security_posture["remember_cookie_secure"] else 0
            score += 20 if security_posture["preferred_url_scheme"] == "https" else 0
            score += 20 if security_posture["same_site"].lower() in {"lax", "strict"} else 0
            score += 20 if security_posture["http_only"] else 0
            security_posture["score"] = score
            security_posture.update({
                "privileged_user_count": privileged_user_count,
                "blocked_users": blocked_user_count,
                "total_users": total_users,
                "privileged_user_ratio": privileged_user_ratio,
                "privileged_access_ok": privileged_user_ratio <= 25,
                "blocked_users_ok": blocked_user_count == 0,
            })

            recent_user_actions = Activity.query.filter_by(activity_type="user").order_by(Activity.created_at.desc()).limit(20).all()
            supported_languages = app.config.get("SUPPORTED_LANGUAGES", {})
            return {
                "users": users,
                "grouped": grouped,
                "pagination": pagination,
                "search_query": search_query,
                "max_photo_mb": upload_limits["max_photo_mb"],
                "max_upload_mb": upload_limits["max_upload_mb"],
                "min_upload_mb": upload_limits["min_upload_mb"],
                "photo_library_controls": photo_library_controls,
                "sla_policy_settings": sla_policy_settings,
                "recent_user_actions": recent_user_actions,
                "role_matrix_columns": VALID_ACCOUNT_ROLES,
                "role_matrix_keys": LOGIN_MATRIX_KEYS,
                "role_matrix": normalized_role_matrix,
                "role_matrix_summary": role_matrix_summary,
                "avatar_options": AVATAR_OPTIONS,
                "avatar_choice_map": avatar_choice_map,
                "avatar_icon_map": AVATAR_ICON_MAP,
                "user_settings_map": user_settings_map,
                "role_breakdown": role_breakdown,
                "security_posture": security_posture,
                "role_options": VALID_ACCOUNT_ROLES,
                "theme_options": ["light", "dark"],
                "language_options": list(supported_languages.keys()),
                "issued_credentials": session.get("issued_credentials"),
            }
        except Exception:
            app.logger.exception("Developer user context failed")
            return {
                "users": [],
                "grouped": [],
                "pagination": None,
                "search_query": "",
                "max_photo_mb": 10,
                "max_upload_mb": 256,
                "min_upload_mb": 64,
                "photo_library_controls": {
                    "include_screenshots": False,
                    "allow_import": False,
                    "max_scan_limit": 0,
                },
                "sla_policy_settings": {
                    "standard_hours": 24,
                    "critical_hours": 72,
                    "due_soon_hours": 24,
                    "escalation_enabled": True,
                },
                "recent_user_actions": [],
                "role_matrix_columns": [],
                "role_matrix_keys": [],
                "role_matrix": {},
                "role_matrix_summary": {
                    "entry_count": 0,
                    "open_entry_count": 0,
                    "issue_count": 0,
                    "issues": [],
                    "is_secure": True,
                },
                "avatar_options": [],
                "avatar_choice_map": {},
                "avatar_icon_map": {},
                "user_settings_map": {},
                "role_breakdown": {},
                "security_posture": {
                    "score": 0,
                    "session_cookie_secure": False,
                    "remember_cookie_secure": False,
                    "preferred_url_scheme": "http",
                    "same_site": "Lax",
                    "same_site_policy": "Lax",
                    "csrf_protection": False,
                    "http_only": False,
                    "privileged_user_count": 0,
                    "blocked_users": 0,
                    "total_users": 0,
                    "privileged_user_ratio": 0,
                    "privileged_access_ok": True,
                    "blocked_users_ok": True,
                },
                "role_options": [],
                "theme_options": ["light", "dark"],
                "language_options": ["en"],
                "issued_credentials": None,
            }

    def _admin_user_control_redirect():
        target = "admin_user_control" if request.endpoint and request.endpoint.startswith("admin_") else "developer_user_control"
        return redirect(url_for(target))

    def _create_user_from_role_form(role, template_name):
        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "").strip()
            region = (request.form.get("region") or "").strip() or None
            gender = (request.form.get("gender") or "").strip() or None
            support_desk = (request.form.get("support_desk") or "").strip() or None
            site_operations_phone = (request.form.get("site_operations_phone") or "").strip() or None
            emergency_phone = (request.form.get("emergency_phone") or "").strip() or None

            if not first_name and not last_name:
                flash("First name or last name is required.", "warning")
                return render_template(template_name)
            if not email:
                flash("Email is required.", "warning")
                return render_template(template_name)

            if User.query.filter_by(email=email).first():
                flash("Email is already registered.", "warning")
                return render_template(template_name)

            if not password:
                password = secrets.token_urlsafe(12)

            full_name = f"{first_name} {last_name}".strip() or email
            user = User(
                email=email,
                full_name=full_name,
                first_name=first_name or None,
                last_name=last_name or None,
                role=role,
                password_hash=generate_password_hash(password),
                region=region,
                gender=gender,
                support_desk=support_desk,
                site_operations_phone=site_operations_phone,
                emergency_phone=emergency_phone,
                created_at=utcnow_naive(),
            )
            db.session.add(user)
            db.session.commit()
            AuditLog.log(
                "user_created",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={
                    "role": role,
                    "email": user.email,
                },
            )
            session["issued_credentials"] = {
                "email": user.email,
                "password": password,
                "previous_password": None,
            }
            flash(f"{role.replace('_', ' ').title()} account created", "success")
            return _admin_user_control_redirect()

        return render_template(template_name)

    @app.route("/admin/add-technician/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def add_technician():
        return _create_user_from_role_form("technician", "add_technician.html")

    @app.route("/admin/add-staff/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def add_staff():
        return _create_user_from_role_form("staff", "add_staff.html")

    @app.route("/admin/add-manager/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def add_manager():
        return _create_user_from_role_form("manager", "add_manager.html")

    @app.route("/admin/add-general-manager/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def add_general_manager():
        return _create_user_from_role_form("general_manager", "add_general_manager.html")

    @app.route("/admin/add-admin/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def add_admin():
        return _create_user_from_role_form("admin", "add_admin.html")

    @app.route("/admin/staff/", methods=["GET", "POST"])
    @login_required
    def admin_staff():
        # Allow developers, admins, managers, and general_managers to access
        if current_user.role not in ("developer", "admin", "manager", "general_manager"):
            abort(403)
        search_query, users, grouped, pagination = apply_user_search(request.args.get("q"))
        return render_template(
            "admin_staff.html",
            users=users,
            grouped=grouped,
            pagination=pagination,
            search_query=search_query,
        )

    @app.route("/developer/users/block/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def developer_user_control():
        if request.method == "POST":
            action = request.form.get("action")
            if action == "update_upload_limits":
                app.config["MAX_PHOTO_MB"] = min(max(request.form.get("max_photo_mb", 10, type=int), 1), 50)
                app.config["MAX_UPLOAD_MB"] = min(max(request.form.get("max_upload_mb", 256, type=int), 16), 4096)
                app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_UPLOAD_MB"] * 1024 * 1024
                create_activity("user", f"Updated upload limits to photo={app.config['MAX_PHOTO_MB']}MB upload={app.config['MAX_UPLOAD_MB']}MB")
                AuditLog.log(
                    "upload_limits_updated",
                    "system",
                    user=current_user,
                    resource_type="configuration",
                    details={
                        "max_photo_mb": app.config["MAX_PHOTO_MB"],
                        "max_upload_mb": app.config["MAX_UPLOAD_MB"],
                    },
                )
                flash("Upload limits updated.", "success")
            elif action == "update_photo_library_controls":
                controls = normalize_photo_library_controls({
                    "include_screenshots": bool(request.form.get("include_screenshots")),
                    "allow_import": bool(request.form.get("allow_import")),
                    "max_scan_limit": request.form.get("max_scan_limit", type=int),
                })
                app.config["PHOTO_LIBRARY_CONTROLS"] = controls
                create_activity("user", "Updated photo library controls")
                AuditLog.log(
                    "photo_library_controls_updated",
                    "system",
                    user=current_user,
                    resource_type="configuration",
                    details=controls,
                )
                flash("Photo scanner controls updated.", "success")
            elif action == "update_role_access_matrix":
                matrix = {key: request.form.getlist(f"matrix_{key}") for key in LOGIN_MATRIX_KEYS}
                app.config["ROLE_ACCESS_MATRIX"] = normalize_role_access_matrix(matrix)
                create_activity("user", "Updated role access matrix")
                AuditLog.log(
                    "role_access_matrix_updated",
                    "authorization",
                    user=current_user,
                    resource_type="configuration",
                    details={"matrix": app.config["ROLE_ACCESS_MATRIX"]},
                )
                flash("Role access matrix updated.", "success")
            elif action == "reset_role_access_matrix":
                app.config["ROLE_ACCESS_MATRIX"] = normalize_role_access_matrix(DEFAULT_ROLE_ACCESS_MATRIX)
                create_activity("user", "Reset role access matrix to recommended defaults")
                AuditLog.log(
                    "role_access_matrix_reset",
                    "authorization",
                    user=current_user,
                    resource_type="configuration",
                    details={"matrix": app.config["ROLE_ACCESS_MATRIX"]},
                )
                flash("Role access matrix reset to recommended defaults.", "success")
            elif action == "update_sla_policy_settings":
                app.config["SLA_STANDARD_HOURS"] = min(max(request.form.get("standard_hours", type=int, default=app.config.get("SLA_STANDARD_HOURS")), 1), 168)
                app.config["SLA_CRITICAL_HOURS"] = min(max(request.form.get("critical_hours", type=int, default=app.config.get("SLA_CRITICAL_HOURS")), 1), 168)
                app.config["SLA_DUE_SOON_HOURS"] = min(max(request.form.get("due_soon_hours", type=int, default=app.config.get("SLA_DUE_SOON_HOURS")), 1), app.config["SLA_STANDARD_HOURS"])
                app.config["SLA_ESCALATION_ENABLED"] = bool(request.form.get("escalation_enabled"))
                create_activity("user", f"Updated SLA settings: standard={app.config['SLA_STANDARD_HOURS']}h critical={app.config['SLA_CRITICAL_HOURS']}h due_soon={app.config['SLA_DUE_SOON_HOURS']}h escalation={'enabled' if app.config['SLA_ESCALATION_ENABLED'] else 'disabled'}")
                AuditLog.log(
                    "sla_policy_settings_updated",
                    "system",
                    user=current_user,
                    resource_type="configuration",
                    details={
                        "standard_hours": app.config["SLA_STANDARD_HOURS"],
                        "critical_hours": app.config["SLA_CRITICAL_HOURS"],
                        "due_soon_hours": app.config["SLA_DUE_SOON_HOURS"],
                        "escalation_enabled": app.config["SLA_ESCALATION_ENABLED"],
                    },
                )
                flash("SLA and escalation settings updated.", "success")
            redirect_target = "admin_user_control" if request.endpoint == "admin_user_control" else "developer_user_control"
            return redirect(url_for(redirect_target))
        return render_template("developer_user_control.html", **_developer_user_context())

    @app.route("/admin/users/block/", methods=["GET", "POST"])
    @login_required
    @developer_required
    def admin_user_control():
        # Admin-facing alias for the developer user control surface.
        return developer_user_control()

    # The remaining admin endpoints use helpers provided by the app; bind them via get_record_or_404 etc.
    @app.route("/admin/staff/<int:user_id>/edit-profile", methods=["POST"])
    @login_required
    @developer_required
    def edit_user_profile(user_id):
        user = get_record_or_404(User, user_id)
        email = (request.form.get("email") or "").strip().lower()
        duplicate = User.query.filter(db.func.lower(User.email) == email, User.id != user.id).first()
        if duplicate:
            flash("That email address is already in use.", "warning")
            return _admin_user_control_redirect()
        user.email = email
        user.uid = (request.form.get("uid") or "").strip() or user.uid
        user.first_name = (request.form.get("first_name") or "").strip()
        user.last_name = (request.form.get("last_name") or "").strip()
        user.full_name = f"{user.first_name} {user.last_name}".strip() or user.email
        user.region = (request.form.get("region") or "").strip() or None
        user.gender = (request.form.get("gender") or "").strip() or None
        user.support_desk = (request.form.get("support_desk") or "").strip() or None
        user.site_operations_phone = (request.form.get("site_operations_phone") or "").strip() or None
        user.emergency_phone = (request.form.get("emergency_phone") or "").strip() or None
        settings = UserSettings.query.filter_by(user_id=user.id).first()
        if not settings:
            settings = UserSettings(user_id=user.id)
            db.session.add(settings)
        prefs = settings.get_preferences()
        avatar_key = request.form.get("avatar_key")
        if avatar_key in AVATAR_KEYS:
            prefs["profile_avatar"] = avatar_key
            settings.set_preferences(prefs)
        db.session.commit()
        AuditLog.log(
            "user_profile_updated",
            "authorization",
            user=current_user,
            resource_type="user",
            resource_id=user.id,
            details={
                "email": user.email,
                "role": user.role,
                "uid": user.uid,
            },
        )
        flash("Profile updated.", "success")
        return _admin_user_control_redirect()

    @app.route("/admin/staff/<int:user_id>/controls", methods=["POST"])
    @login_required
    @developer_required
    def update_user_controls(user_id):
        user = get_record_or_404(User, user_id)
        settings = UserSettings.query.filter_by(user_id=user.id).first()
        if not settings:
            settings = UserSettings(user_id=user.id)
            db.session.add(settings)
        action = request.form.get("developer_control_action")
        prefs = settings.get_preferences()
        if action == "update_settings":
            supported_language_keys = set(app.config.get("SUPPORTED_LANGUAGES", {}).keys())
            settings.theme = request.form.get("theme") if request.form.get("theme") in {"light", "dark"} else "light"
            settings.language = request.form.get("language") if request.form.get("language") in supported_language_keys else "en"
            db.session.commit()
            AuditLog.log(
                "user_settings_updated",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={
                    "theme": settings.theme,
                    "language": settings.language,
                },
            )
            flash("User settings updated.", "success")
        elif action == "reset_app_settings":
            avatar = prefs.get("profile_avatar")
            settings.theme = "light"
            settings.language = "en"
            settings.set_preferences({"profile_avatar": avatar} if avatar else {})
            db.session.commit()
            AuditLog.log(
                "user_app_settings_reset",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={"profile_avatar": avatar},
            )
            flash("User app settings reset.", "success")
        elif action == "clear_hidden_messages":
            prefs["hidden_message_ids"] = []
            settings.set_preferences(prefs)
            db.session.commit()
            AuditLog.log(
                "user_hidden_messages_cleared",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={"hidden_message_ids": []},
            )
            flash("Hidden messages restored.", "success")
        return _admin_user_control_redirect()

    @app.route("/admin/staff/<int:user_id>/role", methods=["POST"])
    @login_required
    @developer_required
    def set_user_role(user_id):
        user = get_record_or_404(User, user_id)
        role = normalize_role(request.form.get("role") or "")
        if role in VALID_ACCOUNT_ROLES and user.id != current_user.id:
            user.role = role
            db.session.commit()
            AuditLog.log(
                "user_role_updated",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={"new_role": role},
            )
            flash("Role updated.", "success")
        return _admin_user_control_redirect()

    @app.route("/admin/staff/<int:user_id>/reset-password", methods=["POST"])
    @login_required
    @developer_required
    def reset_user_password(user_id):
        user = get_record_or_404(User, user_id)
        new_password = (request.form.get("new_password") or "").strip()
        generate_only = bool(request.form.get("generate_only"))
        if not new_password and generate_only:
            new_password = secrets.token_urlsafe(10)

        if not new_password:
            flash("New password is required.", "warning")
            return redirect(url_for("admin_user_control"))

        if normalize_role(current_user.role) not in {"developer", "admin"}:
            flash("Unauthorized password reset.", "danger")
            return redirect(url_for("admin_user_control"))

        previous_password = (request.form.get("current_password") or "").strip() or None
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        AuditLog.log(
            "user_password_reset",
            "authorization",
            user=current_user,
            resource_type="user",
            resource_id=user.id,
            details={"method": "admin_reset", "generated": bool(generate_only)},
        )
        session["issued_credentials"] = {
            "email": user.email,
            "password": new_password,
            "previous_password": previous_password,
        }
        flash(f"Password reset for {user.display_name}.", "success")
        return redirect(url_for("admin_user_control"))

    @app.route("/admin/staff/<int:user_id>/block", methods=["POST"])
    @login_required
    @developer_required
    def toggle_user_block(user_id):
        user = get_record_or_404(User, user_id)
        if user.id != current_user.id:
            user.is_blocked = not user.is_blocked
            db.session.commit()
            AuditLog.log(
                "user_block_toggled",
                "authorization",
                user=current_user,
                resource_type="user",
                resource_id=user.id,
                details={"is_blocked": user.is_blocked},
            )
            flash("User block status updated.", "success")
        return _admin_user_control_redirect()

    @app.route("/admin/staff/<int:user_id>/delete", methods=["POST"])
    @login_required
    @developer_required
    def delete_user(user_id):
        user = get_record_or_404(User, user_id)
        if user.id == current_user.id:
            flash("You cannot delete your own account.", "warning")
            return _admin_user_control_redirect()
        UserSettings.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        AuditLog.log(
            "user_deleted",
            "authorization",
            user=current_user,
            resource_type="user",
            resource_id=user.id,
            details={"deleted_user_email": user.email},
        )
        flash("User deleted.", "success")
        return redirect(url_for("developer_user_control"))

    @app.route("/developer/users/<int:user_id>/activity")
    @login_required
    @developer_required
    def developer_user_activity(user_id):
        target_user = get_record_or_404(User, user_id)
        search_query = (request.args.get("q") or "").strip()[:100]
        query = Activity.query.filter(Activity.created_by == target_user.email)
        if search_query:
            query = query.filter(Activity.details.ilike(f"%{search_query}%"))
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(max(10, request.args.get("per_page", 20, type=int)), 100)
        pagination = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return render_template("developer_user_activity.html", target_user=target_user, activities=pagination.items, pagination=pagination, search_query=search_query, per_page=per_page)

    @app.route("/admin/users/<int:user_id>/activity")
    @login_required
    @developer_required
    def admin_user_activity(user_id):
        return developer_user_activity(user_id)

    @app.route("/admin/photo-library")
    @login_required
    @developer_required
    def admin_photo_library():
        developer_library_view = app.view_functions.get("developer_photo_library")
        if not developer_library_view:
            abort(404)
        return developer_library_view()

    @app.route("/admin/photo-library/import", methods=["POST"])
    @login_required
    @developer_required
    def admin_import_photo_library_file():
        developer_import_view = app.view_functions.get("import_photo_library_file")
        if not developer_import_view:
            abort(404)
        return developer_import_view()

    @app.route("/admin/share-qr.png")
    @login_required
    def admin_share_qr():
        if getattr(current_user, "role", None) not in {"admin", "developer"}:
            abort(403)
        developer_share_view = app.view_functions.get("developer_share_qr")
        if not developer_share_view:
            abort(404)
        return developer_share_view()

    @app.route("/developer/security-posture", methods=["GET"])
    @login_required
    @developer_required
    def developer_security_posture():
        session_cookie_secure = bool(app.config.get("SESSION_COOKIE_SECURE", False))
        remember_cookie_secure = bool(app.config.get("REMEMBER_COOKIE_SECURE", False))
        preferred_url_scheme = str(app.config.get("PREFERRED_URL_SCHEME", "http") or "http").lower()
        same_site = str(app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax")
        session_httponly = bool(app.config.get("SESSION_COOKIE_HTTPONLY", True))
        csrf_enabled = bool(app.config.get("WTF_CSRF_ENABLED", True))
        privileged_roles = ("developer", "admin", "general_manager", "manager")
        total_users = User.query.count()
        privileged_user_count = User.query.filter(User.role.in_(privileged_roles)).count()
        blocked_user_count = User.query.filter_by(is_blocked=True).count()
        privileged_user_ratio = int((privileged_user_count / total_users * 100) if total_users else 0)
        score = 0
        score += 20 if session_cookie_secure else 0
        score += 20 if remember_cookie_secure else 0
        score += 20 if preferred_url_scheme == "https" else 0
        score += 20 if same_site.lower() in {"lax", "strict"} else 0
        score += 20 if session_httponly else 0

        return jsonify({
            "session_cookie_secure": session_cookie_secure,
            "remember_cookie_secure": remember_cookie_secure,
            "preferred_url_scheme": preferred_url_scheme,
            "csrf_on": csrf_enabled,
            "session_httponly": session_httponly,
            "same_site": same_site,
            "same_site_policy": same_site,
            "score": score,
            "privileged_user_count": privileged_user_count,
            "total_users": total_users,
            "blocked_users": blocked_user_count,
            "privileged_user_ratio": privileged_user_ratio,
            "privileged_access_ok": privileged_user_ratio <= 25,
            "blocked_users_ok": blocked_user_count == 0,
            "checked_at": utcnow_naive().isoformat() + "Z",
        })

    @app.route("/admin/security-posture", methods=["GET"])
    @login_required
    def admin_security_posture():
        return developer_security_posture()
