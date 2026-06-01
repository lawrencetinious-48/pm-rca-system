import io
from pm_app.legacy_app import create_app
from model import db, User, BootstrapState


def test_onboarding_e2e():
    app = create_app({'TESTING': True})
    with app.app_context():
        # cleanup
        db.session.query(BootstrapState).delete()
        db.session.query(User).filter(User.email.like('%e2e.admin%')).delete()
        db.session.commit()

        client = app.test_client()

        # Visit welcome
        r = client.get('/welcome')
        assert r.status_code == 200
        assert b'Terms & Conditions' in r.data or b'Welcome' in r.data

        # GET setup to obtain CSRF
        r = client.get('/setup-first-admin')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        import re
        m = re.search(r'name="csrf_token" value="([A-Za-z0-9_\-]+)"', html)
        token = m.group(1) if m else None
        assert token

        # POST create admin
        data = {
            'name': 'E2E Admin',
            'email': 'e2e.admin@example.com',
            'password': 'E2Epass!23',
            'password_confirm': 'E2Epass!23',
            'gender': 'other',
            'age': '37',
            'csrf_token': token,
            'signature': (io.BytesIO(b'fake-image-data'), 'sig.png')
        }
        r = client.post('/setup-first-admin', data=data, content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200
        assert b'Admin Account Created' in r.data or b'created' in r.data.lower()

        # Check DB user
        user = User.query.filter_by(email='e2e.admin@example.com').first()
        assert user is not None
        assert user.role == 'admin'

        # Login
        r = client.get('/login')
        html = r.get_data(as_text=True)
        m2 = re.search(r'name="login_csrf_token" value="([A-Za-z0-9_\-]+)"', html)
        login_token = m2.group(1) if m2 else None
        assert login_token

        login_data = {
            'email': 'e2e.admin@example.com',
            'password': 'E2Epass!23',
            'account_type': 'admin',
            'login_csrf_token': login_token,
            'csrf_token': login_token,
            'role': 'admin'
        }
        r = client.post('/login', data=login_data, follow_redirects=True)
        assert r.status_code == 200
        assert b'dashboard' in r.data.lower() or b'Welcome Back' in r.data
