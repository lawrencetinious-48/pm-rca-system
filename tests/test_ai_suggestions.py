from werkzeug.security import generate_password_hash

from model import Activity, AiSuggestion, User, db

from conftest import extract_hidden_input


def test_api_activity_suggestion_prefers_persisted(app, client, login_as_developer):
    with app.app_context():
        # create an activity
        activity = Activity(
            activity_type="pm",
            details="Test activity for AI suggestion",
            created_by="tech@example.com",
        )
        db.session.add(activity)
        db.session.commit()
        # create persisted suggestion
        s = AiSuggestion(activity_id=activity.id, suggestion_text="Check generator and logs.", source="ai_llm", provider="openai")
        db.session.add(s)
        db.session.commit()
        aid = activity.id

    login_as_developer()
    resp = client.get(f"/api/activity/{aid}/suggestion")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "ok"
    assert payload["suggestion"] == "Check generator and logs."
    assert payload.get("source") == "ai_llm"


def test_admin_ai_suggestions_access_control(app, client):
    with app.app_context():
        # create an activity and a suggestion
        activity = Activity(activity_type="pm", details="Example", created_by="tech2@example.com")
        db.session.add(activity)
        db.session.commit()
        s = AiSuggestion(activity_id=activity.id, suggestion_text="Review battery health.", source="ai_llm", provider="openai")
        db.session.add(s)
        db.session.commit()

        # create a staff user
        staff = User(email="staff-user@example.com", full_name="Staff User", role="staff", password_hash=generate_password_hash("Password123!"))
        db.session.add(staff)
        db.session.commit()

    # login as staff via standard login flow
    response = client.get('/login')
    token = extract_hidden_input(response.get_data(as_text=True), 'login_csrf_token')
    login_resp = client.post('/login', data={
        'email': 'staff-user@example.com',
        'password': 'Password123!',
        'account_type': 'staff',
        'login_csrf_token': token,
    }, follow_redirects=False)
    assert login_resp.status_code == 302

    # staff should be forbidden from admin page
    denied = client.get('/admin/ai-suggestions/')
    assert denied.status_code == 403

    # now login as developer and access page
    # use helper fixture
    from conftest import developer_user, login_as_developer
    # developer_user fixture already provided elsewhere; reuse login_as_developer via client
    # call login_as_developer from tests via client — import done at top of test run
    # Instead perform programmatic login using existing developer fixture endpoint
    # fetch login page for developer
    resp2 = client.get('/login?role=developer')
    token2 = extract_hidden_input(resp2.get_data(as_text=True), 'login_csrf_token')
    # create the developer account if not present
    with app.app_context():
        dev = User.query.filter_by(email='developer@example.com').first()
        if not dev:
            db.session.add(User(email='developer@example.com', full_name='Dev', role='developer', password_hash=generate_password_hash('Password123!')))
            db.session.commit()
    login_resp2 = client.post('/login?role=developer', data={
        'email': 'developer@example.com',
        'password': 'Password123!',
        'account_type': 'developer',
        'login_csrf_token': token2,
    }, follow_redirects=False)
    assert login_resp2.status_code == 302

    page = client.get('/admin/ai-suggestions/')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'AI Suggestions' in body
    assert 'Review persisted AI suggestions' in body or 'No suggestions found' in body
