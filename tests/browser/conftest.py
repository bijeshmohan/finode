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
import warnings
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
from fastapi import HTTPException

from app import auth, auth_flows
from app.auth import CurrentUser, require_authenticated_user
from app.config import settings
from app.dependencies import get_db_session
from app.main import app
from app.session import ACCESS_COOKIE, InvalidCredentialsError, SessionTokens
from app.web_auth import web_login_required

from ..conftest import TEST_USER_ID
from .spa import spa_app

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def pytest_collection_modifyitems(items):
    for item in items:
        if "/browser/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def browser() -> Generator[Browser]:
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


def _serve(asgi_app, session) -> Generator[str]:
    """`asgi_app` on a free port, using the test's in-memory database, until the test ends.

    The test database is one in-memory SQLite connection, which must not be used by two threads at once (a page
    fetches several things at the same time; that raised "bad parameter or other API misuse" now and then). So
    requests take turns, each with its own read memory, as every request has its own session in production.
    """
    turn = threading.Lock()

    def one_at_a_time():
        with turn:
            session.info.pop("read_memory", None)
            yield session

    app.dependency_overrides[get_db_session] = one_at_a_time
    server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=0, log_level="warning"))
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
def live_server(session) -> Generator[str]:
    """The app on a free port, signed in as the test user, with the fresh in-memory database of the test."""
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=TEST_USER_ID, email="test@example.com", claims={}
    )
    app.dependency_overrides[web_login_required] = lambda: None
    yield from _serve(app, session)


# The React app signs in for real through /api/auth; only Supabase is stood in for: a password starting "right" signs in, and
# the session cookie it sets ("test-access") is the test user.
SPA_TOKEN = "test-access"


def _fake_jwt(token: str) -> dict:
    if token == SPA_TOKEN:
        return {"sub": str(TEST_USER_ID), "email": "test@example.com"}
    raise HTTPException(status_code=401, detail="invalid authentication token")


def _fake_sign_in(email: str, password: str) -> SessionTokens:
    if not password.startswith("right"):
        raise InvalidCredentialsError()
    return SessionTokens(SPA_TOKEN, "test-refresh", 3600)


@pytest.fixture
def spa_server(session, monkeypatch: pytest.MonkeyPatch) -> Generator[str]:
    """The built React app and the API on one free port, signed out, with the test's in-memory database."""
    monkeypatch.setattr(auth, "verify_supabase_jwt", _fake_jwt)
    monkeypatch.setattr(auth_flows, "sign_in", _fake_sign_in)
    monkeypatch.setattr(settings, "recurring_interval_minutes", 0)
    monkeypatch.setattr(settings, "cookie_secure", False)  # plain http on 127.0.0.1: WebKit drops a Secure cookie there
    served = _serve(spa_app(), session)
    url = next(served)
    monkeypatch.setattr(settings, "frontend_origin", url)
    yield url
    next(served, None)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    setattr(item, f"report_{report.when}", report)
    return report


FAILURES = Path(__file__).parent / "failures"


def keep_evidence(item, page: Page) -> None:
    """A failed browser test leaves a screenshot and the page's HTML next to the tests (git ignores them), so a failure
    that only happens now and then can be read afterwards instead of guessed at."""
    report = getattr(item, "report_call", None)
    if report is None or not report.failed:
        return
    try:
        FAILURES.mkdir(exist_ok=True)
        name = item.name.replace("/", "_")[:120]
        page.screenshot(path=str(FAILURES / f"{name}.png"))
        (FAILURES / f"{name}.html").write_text(page.content())
    except Exception as error:  # the evidence is a convenience: never hide the real failure behind it
        warnings.warn(f"could not keep the evidence of {item.name}: {error}", stacklevel=2)


def _new_page(browser: Browser, base_url: str) -> tuple[BrowserContext, Page, list[str]]:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, base_url=base_url, reduced_motion="reduce"
    )  # measured positions must not catch a page mid-rise
    page = context.new_page()
    page.set_default_timeout(8000)
    errors: list[str] = []
    # WebKit reports a background request that was cancelled by a navigation (or by the page closing) as an error
    # "... due to access control checks"; it has no effect for a person using the app.
    page.on(
        "pageerror",
        lambda error: errors.append(str(error)) if "due to access control checks" not in str(error) else None,
    )
    return context, page, errors


@pytest.fixture
def page(request, browser: Browser, live_server: str) -> Generator[Page]:
    context, page, errors = _new_page(browser, live_server)
    yield page
    keep_evidence(request.node, page)
    context.close()
    assert not errors, f"JavaScript errors in the page: {errors}"


@pytest.fixture
def spa_page(request, browser: Browser, spa_server: str) -> Generator[Page]:
    """The React app in a phone-sized browser, signed out."""
    context, page, errors = _new_page(browser, spa_server)
    yield page
    keep_evidence(request.node, page)
    context.close()
    assert not errors, f"JavaScript errors in the page: {errors}"


@pytest.fixture
def signed_in_spa_page(spa_page: Page, spa_server: str) -> Page:
    """The React app, signed in as the test user (the session cookie a real sign-in sets)."""
    spa_page.context.add_cookies([{"name": ACCESS_COOKIE, "value": SPA_TOKEN, "url": spa_server}])
    return spa_page


class Api:
    """Set data up through the JSON API, as the signed-in test user."""

    def __init__(self, page: Page):
        self.request = page.request

    def post(self, path: str, **body):
        if path == "/accounts/":  # an "account" under Expenses or Income (or inside a category) is a category
            roots = {a["id"]: a["name"] for a in self.get("/accounts/") if a["parent_id"] is None}
            kinds = {c["id"]: c["kind"] for c in self.get("/categories/?include_closed=true")}
            parent = body.get("parent_id")
            if roots.get(parent) in ("Expenses", "Income") or parent in kinds:
                kind = ("spending" if roots[parent] == "Expenses" else "earning") if parent in roots else kinds[parent]
                send = {"name": body["name"], "kind": kind, **({"parent_id": parent} if parent in kinds else {})}
                made = self.post("/categories/", **send)
                return {**made, "id": made["id"]}
        response = self.request.post(f"/api{path}", data=body)
        assert response.ok, f"{path}: {response.status} {response.text()}"
        return response.json()

    def put(self, path: str, **body):
        response = self.request.put(f"/api{path}", data=body)
        assert response.ok, f"{path}: {response.status} {response.text()}"
        return response.json()

    def delete(self, path: str):
        response = self.request.delete(f"/api{path}")
        assert response.ok, f"{path}: {response.status} {response.text()}"

    def get(self, path: str):
        response = self.request.get(f"/api{path}")
        assert response.ok, f"{path}: {response.status}"
        return response.json()


def row_button(page: Page, side: str, index: int = 0):
    """The button of a row on the Add screen (its account or category, its date and its amount)."""
    return page.locator(f'[data-rows="{side}"] [data-row]').nth(index).locator("[data-pick].slim")


def row_gear(page: Page, side: str, index: int = 0):
    """The settings glyph at the right of a row that has its account."""
    return page.locator(f'[data-rows="{side}"] [data-row]').nth(index).locator("[data-row-settings]")


def set_row(page: Page, side: str, index: int = 0, amount: str | None = None, date: str | None = None) -> None:
    """Open the settings of a row that already has its account, type its amount and/or day and press Done."""
    row_gear(page, side, index).click()
    sheet = page.locator("#row-settings")
    if amount is not None:
        sheet.locator("[data-config-amount]").fill(amount)
    if date is not None:
        sheet.locator("[data-config-date]").fill(date)
    sheet.locator("[data-config-ok]").click()


def add_row(
    page: Page, side: str, label: str, index: int = 0, amount: str | None = None, date: str | None = None
) -> None:
    """Choose an account or category in the picker (it closes at once), then set its amount and/or day from the row."""
    row_button(page, side, index).click()
    page.locator("#row-picker [data-pick-option]", has_text=label).first.click()
    if amount is not None or date is not None:
        set_row(page, side, index, amount, date)


@pytest.fixture
def api(page: Page) -> Api:
    return Api(page)


@pytest.fixture
def books(api: Api) -> dict:
    """A small set of accounts, all directly under their type so pickers show plain names."""
    roots = {a["name"]: a["id"] for a in api.get("/accounts/") if a["parent_id"] is None}
    return {
        "checking": api.post("/accounts/", name="Checking", parent_id=roots["Assets"], balance="5000"),
        "cash": api.post("/accounts/", name="Cash", parent_id=roots["Assets"]),
        "card": api.post("/accounts/", name="Visa", parent_id=roots["Liabilities"], on_budget=True),
        "salary": api.post("/accounts/", name="Salary", parent_id=roots["Income"]),
        "food": api.post("/accounts/", name="Groceries", parent_id=roots["Expenses"]),
        "rent": api.post("/accounts/", name="Rent", parent_id=roots["Expenses"]),
        "roots": roots,
    }


@pytest.fixture
def touch_page(browser: Browser, live_server: str) -> Generator[Page]:
    """A phone: a finger instead of a mouse, so a tap blurs the field it leaves before the click arrives (as on iOS)."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        base_url=live_server,
        reduced_motion="reduce",
        has_touch=True,
        is_mobile=True,
    )
    page = context.new_page()
    page.set_default_timeout(8000)
    yield page
    context.close()
