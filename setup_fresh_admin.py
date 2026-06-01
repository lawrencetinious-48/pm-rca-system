#!/usr/bin/env python3
"""Check and reset admin user."""

import sys
from pathlib import Path
from pm_app import create_app
from model import db, User
from pm_app.auth.utils import hash_password
from datetime import datetime

# Create app and init DB
app = create_app()

with app.app_context():
    # Delete all users
    try:
        User.query.delete()
        db.session.commit()
        print("✅ Cleared all users from database")
    except Exception as e:
        print(f"Error deleting users: {e}")
        db.session.rollback()

    # Create fresh admin
    try:
        admin = User(
            email='admin@pm.local',
            password_hash=hash_password('Welcome123!'),
            full_name='System Administrator',
            role='developer',
            is_blocked=False
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Created admin user: admin@pm.local")
        print("   Password: Welcome123!")
    except Exception as e:
        print(f"Error creating admin: {e}")
        db.session.rollback()
