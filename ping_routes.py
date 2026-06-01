from app import app

with app.test_client() as client:
    for rule in app.url_map.iter_rules():
        methods = list(rule.methods - {"HEAD", "OPTIONS"})

        for method in methods:
            try:
                if method == "GET":
                    response = client.get(rule.rule)
                elif method == "POST":
                    response = client.post(rule.rule)
                elif method == "PUT":
                    response = client.put(rule.rule)
                elif method == "DELETE":
                    response = client.delete(rule.rule)
                else:
                    continue

                print(f"{method:6} {rule.rule:40} -> {response.status_code}")

            except Exception as e:
                print(f"{method:6} {rule.rule:40} -> ERROR: {e}")
