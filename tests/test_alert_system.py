import alert_system


def test_send_alert_sends_multipart_email(monkeypatch):
    class DummyServer:
        def __init__(self, host=None, port=None, context=None):
            self.host = host
            self.port = port
            self.context = context
            self.msg = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def login(self, username, password):
            assert username == 'sender@example.com'
            assert password == 'password123'

        def send_message(self, message):
            self.msg = message

    dummy_server = DummyServer()

    monkeypatch.setattr(alert_system, 'EMAIL_ADDRESS', 'sender@example.com')
    monkeypatch.setattr(alert_system, 'EMAIL_PASSWORD', 'password123')
    monkeypatch.setattr(alert_system, 'SMTP_USE_SSL', True)
    monkeypatch.setattr('smtplib.SMTP_SSL', lambda host, port, *args, timeout=None, context=None: dummy_server)

    result = alert_system.send_alert(
        "First line\nSecond line\nThird line\nFourth line",
        "Watchdog Test Subject",
        recipient="destination@example.com",
    )

    assert result is True
    assert dummy_server.msg is not None
    msg = dummy_server.msg
    assert msg['From'] == 'sender@example.com'
    assert msg['To'] == 'destination@example.com'
    assert msg['Subject'] == 'Watchdog Test Subject'

    payload = msg.get_payload()
    assert len(payload) == 2
    assert payload[0].get_content_type() == 'text/plain'
    assert payload[1].get_content_type() == 'text/html'
    assert 'First line' in payload[0].get_content()
    assert '<pre' in payload[1].get_content()
    assert 'Second line' in payload[1].get_content()
