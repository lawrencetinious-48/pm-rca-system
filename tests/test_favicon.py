def test_login_page_declares_favicon_and_favicon_route_serves_image(client):
    login_response = client.get("/login")

    assert login_response.status_code == 200
    html = login_response.get_data(as_text=True)
    assert 'rel="icon"' in html
    assert 'href="/favicon.ico"' in html or 'href="/static/images/soliton-telmec.jpeg"' in html

    favicon_response = client.get("/favicon.ico")

    assert favicon_response.status_code == 200
    assert favicon_response.mimetype == "image/jpeg"
