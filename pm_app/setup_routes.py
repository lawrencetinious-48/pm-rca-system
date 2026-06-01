"""
First-time admin setup flow for fresh system deployment.
Handles welcome page, T&C agreement, and admin account creation.
"""
from flask import render_template, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash


def register_setup_routes(app, db, User, BootstrapState):
    """Register setup routes for first-time admin creation."""

    @app.route('/welcome')
    def welcome_admin():
        """Display welcome page with terms and conditions."""
        # Check if system is already initialized
        bs = db.session.query(BootstrapState).first()
        users_exist = db.session.query(User).count() > 0
        # If bootstrap state indicates complete and users exist, go to login
        if bs and bs.bootstrap_complete and users_exist:
            return redirect(url_for('login'))
        
        return render_template('welcome_admin.html')

    @app.route('/setup-first-admin', methods=['GET', 'POST'])
    def setup_first_admin():
        """Create first admin account."""
        # Check if system is already initialized
        bs = db.session.query(BootstrapState).first()
        users_exist = db.session.query(User).count() > 0
        # Allow setup if there are no users, even if a stale bootstrap record exists.
        if bs and bs.bootstrap_complete and users_exist:
            return redirect(url_for('login'))

        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''
            password_confirm = request.form.get('password_confirm') or ''
            gender = (request.form.get('gender') or '').strip()
            age = request.form.get('age')

            # Validation
            if not name or not email or not password:
                flash('All required fields must be filled.', 'danger')
                return render_template('setup_first_admin.html')

            if len(password) < 8:
                flash('Password must be at least 8 characters long.', 'danger')
                return render_template('setup_first_admin.html')

            if password != password_confirm:
                flash('Passwords do not match.', 'danger')
                return render_template('setup_first_admin.html')

            # Check if user already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('An account with this email already exists.', 'danger')
                return render_template('setup_first_admin.html')

            # Create admin user
            try:
                password_hash = generate_password_hash(password)
                admin_user = User(
                    email=email,
                    full_name=name,
                    password_hash=password_hash,
                    role='admin',
                    gender=gender if gender else None,
                )
                try:
                    admin_user.age = int(age) if age else None
                except Exception:
                    admin_user.age = None

                db.session.add(admin_user)

                # Mark bootstrap as complete
                if bs:
                    bs.bootstrap_complete = True
                else:
                    bs = BootstrapState(bootstrap_complete=True, first_developer=admin_user)
                    db.session.add(bs)

                db.session.commit()

                # Show success page
                return render_template(
                    'admin_created_success.html',
                    admin_name=name,
                    admin_email=email
                )
            except Exception as e:
                db.session.rollback()
                flash(f'Error creating account: {str(e)}', 'danger')
                return render_template('setup_first_admin.html')

        return render_template('setup_first_admin.html')

    @app.route('/bootstrap-check')
    def bootstrap_check():
        """Redirect to setup if not bootstrapped, else to login."""
        try:
            bs = db.session.query(BootstrapState).first()
            if not bs or not bs.bootstrap_complete:
                return redirect(url_for('welcome_admin'))
        except:
            pass
        return redirect(url_for('login'))
