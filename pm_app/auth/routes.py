# flake8: noqa
import secrets
import hmac
from datetime import timedelta
from urllib.parse import urlparse
from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash


def register_auth_routes(  # noqa: C901
    app,
    *,
    user_model,
    db,
    app_env,
    role_lock_enabled,
    normalize_role,
    allowed_login_roles,
    get_lockout_seconds,
    register_login_failure,
    reset_login_failures,
    hash_password,
):
    is_development = (app_env or "").strip().lower() in {"development", "dev", "local"}
    role_lock_active = bool(role_lock_enabled) and (not is_development)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        # Always respect the ?role= query parameter for pre‑selection
        requested_role = normalize_role(request.args.get("role") or "")
        if requested_role in {"developer", "staff", "technician", "manager", "general_manager", "admin"}:
            preselected_role = requested_role
        else:
            preselected_role = ""

        login_csrf_token = session.get("login_csrf_token")
        if not login_csrf_token:
            login_csrf_token = secrets.token_urlsafe(32)
            session["login_csrf_token"] = login_csrf_token

        # Preserve where the user was trying to go so we can redirect back after login
        next_url = (request.args.get("next") or request.form.get("next") or "").strip()
        first_user = user_model.query.count() == 0
        show_first_time_setup = app.config.get("SELF_SERVICE_ENABLED", False) and first_user

        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            selected_role = normalize_role(
                (request.form.get("account_type")
                or request.form.get("role")
                or preselected_role
                or "")
            )
            # Support both legacy login_csrf_token and the global csrf_token field name.
            csrf_token = (
                request.form.get("login_csrf_token")
                or request.form.get("csrf_token")
                or ""
            ).strip()

            # Role lock: ensure the submitted role matches the preselected one (if any)
            if role_lock_active and preselected_role and selected_role != preselected_role:
                flash("Invalid credentials", "danger")
                register_login_failure(email)
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            # CSRF protection using constant-time comparison
            expected_csrf = session.get("login_csrf_token")
            if not expected_csrf or not hmac.compare_digest(expected_csrf, csrf_token):
                flash("Session verification failed. Please try again.", "danger")
                # Rotate CSRF token to prevent replay
                session["login_csrf_token"] = secrets.token_urlsafe(32)
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            lockout_seconds = get_lockout_seconds(email)
            if lockout_seconds > 0:
                flash(f"Too many login attempts. Try again in {lockout_seconds} seconds.", "warning")
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            if not role_lock_active:
                valid_roles = {"developer", "staff", "manager", "general_manager", "technician", "admin"}
            else:
                valid_roles = allowed_login_roles(selected_role)
            if role_lock_active and not valid_roles:
                flash("Select the account type you want to use.", "warning")
                register_login_failure(email)
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            user = user_model.query.filter_by(email=email).first()
            password_ok = False
            if user and user.password_hash:
                try:
                    password_ok = check_password_hash(user.password_hash, password)
                except ValueError:
                    password_ok = False

            if not password_ok:
                # Password mismatch - fail early
                register_login_failure(email)
                flash("Invalid email or password.", "danger")
                return render_template(
                    "login.html",
                    login_csrf_token=session["login_csrf_token"],
                    preselected_role=preselected_role,
                    show_first_time_setup=show_first_time_setup,
                    next_url=next_url,
                )

            if user.is_blocked:
                flash("Invalid email or password.", "danger")
                register_login_failure(email)
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            user_role = normalize_role(user.role)

            # For non-developers: role selection must match user's assigned role
            if user_role != "developer" and selected_role and user_role.lower() != selected_role.lower():
                # Staff/managers can switch roles, but technicians are locked
                if user_role == "technician":
                    register_login_failure(email)
                    flash("Invalid credentials.", "danger")
                    return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            if role_lock_active and user_role != "developer" and user_role not in valid_roles:
                flash("Invalid credentials", "danger")
                register_login_failure(email)
                return render_template("login.html", login_csrf_token=session["login_csrf_token"], preselected_role=preselected_role)

            # User authenticated successfully
            login_user(user)
            session.permanent = True
            session["role"] = user_role

            # Load user settings (theme, language) from database
            from model import UserSettings
            try:
                user_settings = db.session.query(UserSettings).filter_by(user_id=user.id).first()
                if user_settings:
                    session["theme"] = user_settings.theme
                    session["language"] = user_settings.language
                else:
                    session["theme"] = "light"
                    session["language"] = "en"
            except Exception:
                session["theme"] = "light"
                session["language"] = "en"

            reset_login_failures(email)
            # Rotate CSRF token after successful login
            session["login_csrf_token"] = secrets.token_urlsafe(32)
            
            # Respect the requested `next` parameter if it is a safe local path
            if next_url:
                try:
                    parsed = urlparse(next_url)
                    if parsed.scheme == "" and parsed.netloc == "" and next_url.startswith("/"):
                        return redirect(next_url)
                except Exception:
                    pass
            return redirect(url_for("dashboard"))

        # GET request - show login form
        return render_template(
            "login.html",
            login_csrf_token=login_csrf_token,
            preselected_role=preselected_role,
            show_first_time_setup=show_first_time_setup,
            next_url=next_url,
        )

    @app.route("/technician/login")
    def technician_login():
        return redirect(url_for("login", role="technician"))

    @app.route("/staff/login")
    def staff_login():
        return redirect(url_for("login", role="staff"))

    @app.route("/developer/login")
    def developer_login():
        return redirect(url_for("login", role="developer"))

    @app.route("/manager/login")
    def manager_login():
        return redirect(url_for("login", role="manager"))

    @app.route("/general_manager/login")
    def general_manager_login():
        return redirect(url_for("login", role="general_manager"))

    @app.route("/admin/login")
    def admin_login():
        return redirect(url_for("login", role="admin"))

    @app.route("/logout/", methods=["GET", "POST"], strict_slashes=False)
    @login_required
    def logout():
        logout_user()
        flash("Logged out", "info")
        return redirect(url_for("login"))

    @app.route("/register/", methods=["GET", "POST"])
    def register():
        # The bootstrap registration path is only open when no users exist.
        # This is intentionally minimal, but a dedicated transactional
        # bootstrapping state table should be used for true multi-worker safety.
        first_user = user_model.query.count() == 0
        if not first_user:
            if not current_user.is_authenticated or normalize_role(current_user.role) != "developer":
                abort(403)

        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            full_name = (request.form.get("full_name") or "").strip()
            role = (request.form.get("role") or "technician").strip().lower()
            password = request.form.get("password") or ""

            if role not in {"developer", "staff", "technician", "manager", "general_manager", "admin"}:
                flash("Invalid account role selected", "danger")
                return render_template("register.html", first_user=user_model.query.count() == 0)

            if first_user:
                role = "developer"

            if not email or not password or not full_name:
                flash("Fill required fields", "warning")
                return render_template("register.html", first_user=first_user)
            else:
                if user_model.query.filter_by(email=email).first():
                    flash("Email already exists", "danger")
                    return render_template("register.html", first_user=first_user)
                else:
                    # For simplicity, we use the same hash_password function passed in.
                    # The user model will be created with minimal fields.
                    user = user_model(
                        email=email,
                        full_name=full_name,
                        role=role,
                        support_desk=request.form.get("support_desk") or None,
                        site_operations_phone=request.form.get("site_operations_phone") or None,
                        emergency_phone=request.form.get("emergency_phone") or None,
                        password_hash=hash_password(password),
                    )
                    db.session.add(user)
                    db.session.commit()
                    flash("Account created. Please log in.", "success")
                    return redirect(url_for("login"))

        return render_template("register.html", first_user=first_user)

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()

            # CSRF validation
            if not csrf_token_is_valid():
                flash("Session verification failed. Please try again.", "danger")
                return render_template("forgot_password.html")

            user = user_model.query.filter_by(email=email).first()
            if user:
                # Generate secure reset token
                token = secrets.token_urlsafe(32)
                token_hash = generate_password_hash(token, method="pbkdf2:sha256")

                # Create reset token record
                from model import PasswordResetToken
                expires_at = app_env.utcnow_naive() + timedelta(hours=1)
                reset_token = PasswordResetToken(
                    user_id=user.id,
                    token_hash=token_hash,
                    expires_at=expires_at
                )
                db.session.add(reset_token)
                db.session.commit()

                # Send reset email using shared email service
                reset_url = url_for("reset_password", token=token, _external=True)
                try:
                    from pm_app.services.email import send_password_reset_email

                    sent = send_password_reset_email(user.email, reset_url)
                    if not sent:
                        app.logger.warning("Password reset email not sent to %s", user.email)
                except Exception as exc:  # pragma: no cover - best-effort logging
                    app.logger.exception("Failed to send password reset email to %s: %s", user.email, exc)

                flash("Password reset instructions sent to your email.", "info")
            else:
                # Don't reveal if email exists or not for security
                flash("If an account with that email exists, password reset instructions have been sent.", "info")

        return redirect(url_for("login"))

        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        # Find valid reset token using secure comparison
        from model import PasswordResetToken
        reset_tokens = PasswordResetToken.query.filter_by(used=False).all()
        reset_token = next(
            (t for t in reset_tokens if check_password_hash(t.token_hash, token)),
            None,
        )

        if not reset_token or not reset_token.is_valid():
            flash("Invalid or expired reset link.", "danger")
            return redirect(url_for("forgot_password"))

        if request.method == "POST":
            password = request.form.get("password") or ""
            confirm_password = request.form.get("confirm_password") or ""

            # CSRF validation
            if not csrf_token_is_valid():
                flash("Session verification failed. Please try again.", "danger")
                return render_template("reset_password.html", token=token)

            if len(password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return render_template("reset_password.html", token=token)

            if password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template("reset_password.html", token=token)

            # Update password and mark token as used
            reset_token.user.password_hash = hash_password(password)
            reset_token.used = True
            db.session.commit()

            flash("Password reset successfully. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("reset_password.html", token=token)
