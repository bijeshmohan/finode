from fastapi.testclient import TestClient


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "welcome to finode"}


def test_settings_ignore_unrelated_dotenv_keys(tmp_path):
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("FINODE_DATABASE_ECHO=false\nAPP_DOMAIN=finode.example.com\n")
    settings = Settings(_env_file=env_file)
    assert settings.database_echo is False
