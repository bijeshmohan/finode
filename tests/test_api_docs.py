from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_the_interactive_docs_are_off_by_default():
    assert Settings(_env_file=None).api_docs is False
    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path, follow_redirects=False).status_code in (404, 303), path
