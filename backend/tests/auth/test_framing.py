"""No other site can show finode inside a frame (clickjacking): every answer, page or API, says so."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/login", "/api/auth/options", "/no-such-page"])
def test_no_answer_can_be_framed(client: TestClient, path: str):
    answer = client.get(path, follow_redirects=False)
    assert answer.headers.get("x-frame-options") == "DENY"
    assert answer.headers.get("content-security-policy") == "frame-ancestors 'none'"
