"""What finode answers outside the app itself: the JSON API under /api, compressed and never cached by a proxy, the
old /app prefix gone, and settings that ignore what is not theirs."""

from fastapi.testclient import TestClient

from .books import post_account


def test_the_old_app_prefix_is_gone(client: TestClient):
    """The web UI left /app long ago; the redirects that kept old links alive were removed once nothing pointed there."""
    for old in ("/app", "/app/", "/app/accounts", "/app/oauth/consent?authorization_id=x"):
        assert client.get(old, follow_redirects=False).status_code == 404, old


def test_the_json_api_is_under_api(client: TestClient):
    assert client.get("/api/accounts/").status_code == 200


def test_json_api_answers_carry_no_cache_headers(client: TestClient):
    assert "cache-control" not in client.get("/api/accounts/").headers


def test_a_large_json_answer_is_compressed(client: TestClient, root_accounts):
    for i in range(40):
        post_account(client, {"name": f"Account {i:02d}", "parent_id": root_accounts["Assets"]})
    zipped = client.get("/api/accounts/", headers={"Accept-Encoding": "gzip"})
    assert zipped.headers.get("content-encoding") == "gzip" and zipped.num_bytes_downloaded < len(zipped.content) // 2
    plain = client.get("/api/accounts/", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == zipped.json()


def test_settings_ignore_unrelated_dotenv_keys(tmp_path):
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("FINODE_DATABASE_ECHO=false\nAPP_DOMAIN=finode.example.com\n")
    settings = Settings(_env_file=env_file)
    assert settings.database_echo is False
