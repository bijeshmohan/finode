from fastapi.testclient import TestClient


def test_the_site_root_is_the_web_app(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]


def test_the_old_app_paths_still_lead_to_the_new_ones(client: TestClient):
    for old, new in (("/app", "/"), ("/app/", "/"), ("/app/accounts", "/accounts"), ("/app/oauth/consent?authorization_id=x", "/oauth/consent?authorization_id=x")):
        response = client.get(old, follow_redirects=False)
        assert response.status_code == 301 and response.headers["location"] == new, old


def test_the_json_api_moved_to_api(client: TestClient):
    assert client.get("/api/accounts/").status_code == 200


def test_settings_ignore_unrelated_dotenv_keys(tmp_path):
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("FINODE_DATABASE_ECHO=false\nAPP_DOMAIN=finode.example.com\n")
    settings = Settings(_env_file=env_file)
    assert settings.database_echo is False
