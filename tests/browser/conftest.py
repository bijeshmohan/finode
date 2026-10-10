"""Tests that drive the web UI in a real browser, against the real app on a real port.

They need a browser. `uv run pytest` skips them when there is none. To run them:

- anywhere Playwright's own browsers work: `uv run playwright install chromium`, then `uv run pytest tests/browser`;
- elsewhere, with Docker: `scripts/browser-tests.sh` (a browser in a container, tests on the host).

`FINODE_BROWSER` picks chromium (default), webkit (closest to iOS Safari) or firefox;
`FINODE_BROWSER_WS` points at a browser server (the script sets it).
"""

import os
import threading
import time
from collections.abc import Generator

import pytest
import uvicorn

from app.auth import CurrentUser, require_authenticated_user
from app.dependencies import get_db_session
from app.main import app
from app.web_auth import web_login_required

from ..conftest import TEST_USER_ID

try:
    from playwright.sync_api import Browser, Page, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def pytest_collection_modifyitems(items):
    for item in items:
        if "/browser/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def browser() -> Generator["Browser", None, None]:
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    playwright = sync_playwright().start()
    kind = getattr(playwright, os.environ.get("FINODE_BROWSER", "chromium"))
    endpoint = os.environ.get("FINODE_BROWSER_WS")
    try:
        browser = kind.connect(endpoint) if endpoint else kind.launch()
    except Exception as error:  # no browser installed, or its system libraries are missing
        playwright.stop()
        pytest.skip(f"no browser available ({str(error).splitlines()[0]})")
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture
def live_server(session) -> Generator[str, None, None]:
    """The app on a free port, signed in as the test user, with the fresh in-memory database of the test."""
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=TEST_USER_ID, email="test@example.com", claims={}
    )
    app.dependency_overrides[web_login_required] = lambda: None
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("the test server did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    app.dependency_overrides.clear()


@pytest.fixture
def page(browser: "Browser", live_server: str) -> Generator["Page", None, None]:
    context = browser.new_context(viewport={"width": 390, "height": 844}, base_url=live_server)
    page = context.new_page()
    page.set_default_timeout(8000)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert not errors, f"JavaScript errors in the page: {errors}"


class Api:
    """Set data up through the JSON API, as the signed-in test user."""

    def __init__(self, page: "Page"):
        self.request = page.request

    def post(self, path: str, **body):
        response = self.request.post(f"/api{path}", data=body)
        assert response.ok, f"{path}: {response.status} {response.text()}"
        return response.json()

    def put(self, path: str, **body):
        response = self.request.put(f"/api{path}", data=body)
        assert response.ok, f"{path}: {response.status} {response.text()}"
        return response.json()

    def get(self, path: str):
        response = self.request.get(f"/api{path}")
        assert response.ok, f"{path}: {response.status}"
        return response.json()


@pytest.fixture
def api(page: "Page") -> Api:
    return Api(page)


@pytest.fixture
def books(api: Api) -> dict:
    """A small set of accounts, all directly under their type so pickers show plain names."""
    roots = {a["name"]: a["aid"] for a in api.get("/accounts/") if a["parent_id"] is None}
    return {
        "checking": api.post("/accounts/", name="Checking", parent_id=roots["Assets"], balance="5000"),
        "cash": api.post("/accounts/", name="Cash", parent_id=roots["Assets"]),
        "card": api.post("/accounts/", name="Visa", parent_id=roots["Liabilities"], on_budget=True),
        "salary": api.post("/accounts/", name="Salary", parent_id=roots["Income"]),
        "food": api.post("/accounts/", name="Groceries", parent_id=roots["Expenses"]),
        "rent": api.post("/accounts/", name="Rent", parent_id=roots["Expenses"]),
        "roots": roots,
    }
