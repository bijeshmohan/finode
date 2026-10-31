"""Isolation audit: nobody can see or change somebody else's books, whichever door they use.

Two people share one database. Person A has a complete ledger (every feature the app has); person B signs in
and tries everything against A's ids and names: every route that takes an id, every list and page, references
to A's accounts inside B's own requests, the assistants' tools, and doors without any sign-in. Nothing of A's may
come back, and A's books must be exactly as they were afterwards.

`test_every_route_is_covered` makes the audit grow with the app: a new route fails it until it is classified.
"""

import json
from contextlib import contextmanager
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth import CurrentUser, require_authenticated_user
from app.dependencies import get_db_session
from app.main import app
from app.repositories.api_token import ApiTokenRepository
from app.repositories.oauth_grant import OAuthGrantRepository
from app.schemas.api_token import ApiTokenCreate
from app.services.api_token import ApiTokenService
from app.services.oauth_grant import OAuthGrantService
from app.web_auth import web_login_required

from .books import leg, post_account
from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .svc import plain, services
from .test_backup import line, rich  # noqa: F401  (a ledger that uses every feature)

B_USER = UUID("00000000-0000-4000-8000-0000000000b2")

# What only A has: names and words that must never show up in anything B receives.
A_WORDS = [
    "Old Savings",
    "Visa",
    "Home Loan",
    "Employer",
    "Milk",
    "Split rule",
    "Ada L",
    "Laptop",
    "A-Assistant",
]

# Doors that need no sign-in, or have their own kind of sign-in (checked on their own).
PUBLIC = {
    ("GET", "/login"),
    ("POST", "/login"),
    ("POST", "/logout"),
    ("GET", "/signup"),
    ("POST", "/signup"),
    ("GET", "/forgot"),
    ("POST", "/forgot"),
    ("GET", "/reset"),
    ("POST", "/reset"),
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("DELETE", "/mcp"),
    ("GET", "/mcp"),
    ("HEAD", "/mcp"),
    ("POST", "/mcp"),  # bearer tokens, tested below
    ("GET", "/oauth/consent"),
    ("POST", "/oauth/consent"),  # a Supabase authorization id of the signed-in user
}

# Routes without an id in the path: what they list is scoped to whoever asks.
LISTS = {
    ("GET", "/"),
    ("GET", "/accounts"),
    ("GET", "/accounts/new"),
    ("GET", "/accounts/options"),
    ("GET", "/accounts/quick"),
    ("GET", "/api/accounts/"),
    ("GET", "/api/categories/"),
    ("GET", "/api/backup"),
    ("GET", "/api/budget/"),
    ("GET", "/api/todo/"),
    ("GET", "/todo/badge"),
    ("GET", "/todo/sheet"),
    ("GET", "/api/export"),
    ("GET", "/api/profile/"),
    ("GET", "/api/recurring/"),
    ("GET", "/api/reports/trial-balance"),
    ("GET", "/api/transactions/"),
    ("GET", "/api/transactions/changes"),
    ("GET", "/api/accounts/changes"),
    ("GET", "/api/transactions/payee-defaults"),
    ("GET", "/api/accounts/closed"),
    ("GET", "/api/accounts/deleted"),
    ("GET", "/api/profile/currencies"),
    ("GET", "/api/reports/breakdown"),
    ("GET", "/api/reports/summary"),
    ("GET", "/api/transactions/deleted"),
    ("GET", "/api/transactions/payees"),
    ("GET", "/backup"),
    ("GET", "/budget"),
    ("GET", "/budget/goal"),
    ("GET", "/budget/goal/preview"),
    ("GET", "/budget/move"),
    ("GET", "/export"),
    ("GET", "/profile/assistants"),
    ("GET", "/profile/data"),
    ("GET", "/recurring"),
    ("GET", "/recurring/new"),
    ("GET", "/categories"),
    ("GET", "/categories/new"),
    ("GET", "/settings"),
    ("GET", "/transactions"),
    ("GET", "/transactions/deleted"),
    ("GET", "/accounts/deleted"),
    ("GET", "/categories/deleted"),
    ("GET", "/transactions/suggest"),
    ("GET", "/transactions/tag-options"),
    ("GET", "/transactions/tag-picker"),
    ("GET", "/tags"),
    ("GET", "/api/tags/"),
    ("GET", "/transactions/more"),
    ("GET", "/transactions/related-picker"),
    ("GET", "/transactions/new"),
}

# Routes that take A's ids or names inside the request: refused (see `test_b_cannot_use_a_s_things_in_requests`).
REFERENCES = {
    ("POST", "/accounts"),
    ("POST", "/accounts/quick"),
    ("POST", "/api/accounts/"),
    ("POST", "/api/categories/"),
    ("POST", "/categories"),
    ("POST", "/categories/quick"),
    ("POST", "/api/import"),
    ("PATCH", "/api/profile/"),
    ("POST", "/api/recurring/"),
    ("POST", "/api/restore"),
    ("POST", "/api/transactions/"),
    ("POST", "/api/transactions/batch"),
    ("POST", "/budget/assign"),
    ("POST", "/budget/copy"),
    ("POST", "/budget/goal"),
    ("POST", "/budget/move"),
    ("POST", "/import"),
    ("POST", "/import/preview"),
    ("POST", "/profile"),
    ("POST", "/profile/assistants"),
    ("POST", "/recurring"),
    ("POST", "/restore"),
    ("POST", "/restore/preview"),
    ("POST", "/settings/currency"),
    ("POST", "/transactions/split"),
    ("POST", "/api/budget/copy"),
    ("POST", "/api/budget/goals"),
    ("POST", "/api/budget/move"),
}


# Actions on the caller's own data (their whole account): they take no id, so B's use of them must leave A alone.
OWN_DATA = {("POST", "/profile/data/erase"), ("POST", "/profile/data/delete-account")}


def routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def walk(items, prefix=""):
        for r in items:
            inner = getattr(r, "routes", None)
            if inner is not None and not isinstance(r, APIRoute):
                walk(inner, prefix + getattr(r, "path", ""))
                continue
            for method in getattr(r, "methods", None) or []:
                found.add((method, prefix + r.path))

    walk(app.routes)
    return found


def test_every_route_is_covered():
    """A route nobody classified is a route nobody audited: say what it does with other people's data."""
    unclassified = sorted(
        (m, p)
        for m, p in routes()
        if "{" not in p
        and (m, p) not in PUBLIC
        and (m, p) not in LISTS
        and (m, p) not in REFERENCES
        and (m, p) not in OWN_DATA
    )
    assert not unclassified, (
        f"classify these routes in tests/test_isolation.py (PUBLIC, LISTS or REFERENCES) and make sure the audit "
        f"exercises them: {unclassified}"
    )
    stale = sorted(x for x in PUBLIC | LISTS | REFERENCES | OWN_DATA if x not in routes())
    assert not stale, f"these audited routes no longer exist: {stale}"


# ---- the world: A's complete ledger, B's small one ------------------------------------------------------------


def as_user(user_id: UUID):
    email = "test@example.com" if user_id == TEST_USER_ID else "x@example.com"  # as in tests/conftest.py
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=user_id, email=email, claims={})


@contextmanager
def signed_in_as(user_id: UUID):
    as_user(user_id)
    try:
        yield
    finally:
        as_user(TEST_USER_ID)


class World:
    pass


@pytest.fixture
def world(client: TestClient, session, rich) -> World:
    w = World()
    client.patch("/api/profile/", json={"first_name": "Ada", "last_name": "L"})
    # More of A: an assistant token, a connected app, a deleted entry.
    w.token = ApiTokenService(ApiTokenRepository(session, TEST_USER_ID)).create(
        ApiTokenCreate(name="Laptop", scope="write")
    )
    w.grant = OAuthGrantService(OAuthGrantRepository(session, TEST_USER_ID)).allow("client-a", "A-Assistant", "write")
    spare = client.post(
        "/api/transactions/",
        json={
            "payee": "Employer",
            "postings": [line(rich["groceries"], "debit", "7"), line(rich["bank"], "credit", "7")],
        },
    ).json()
    client.delete(f"/api/transactions/{spare['id']}")
    assets = next(
        a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None and a["name"] == "Assets"
    )
    shelf = post_account(client, {"name": "Spare shelf", "parent_id": assets}).json()["id"]
    client.delete(f"/api/accounts/{shelf}")  # an account deleted for good, which can be restored
    w.deletion_ids = [str(d["id"]) for d in services(session).accounts.restorable()]
    client.post("/budget/goal", data={"name": "Isolated holiday", "amount": "5000", "by": "2999-12", "assign_now": "1"})
    w.goal_ids = [g["id"] for g in client.get("/api/budget/").json()["goals"]]
    doc = client.get("/api/backup").json()
    w.backup = doc
    w.categories = {c["name"]: c["id"] for c in doc["categories"]}
    w.accounts = {**{a["name"]: a["id"] for a in doc["accounts"]}, **w.categories}
    w.roots = [a["id"] for a in doc["accounts"] if a["parent_id"] is None]
    w.tags = sorted({name for t in doc["transactions"] for name in t.get("tags", [])})
    w.transaction_ids = [t["id"] for t in doc["transactions"]] + [spare["id"]]
    w.recurring_ids = [r["id"] for r in doc["recurring"]]
    w.history_ids = [str(d.id) for d in services(session).transactions.deleted()]
    w.token_id, w.grant_id = str(w.token.id), str(w.grant.id)
    w.markers = (
        A_WORDS
        + [
            str(i)
            for i in (
                *w.accounts.values(),
                *w.transaction_ids,
                *w.recurring_ids,
                *w.history_ids,
                *w.deletion_ids,
                w.token_id,
                w.grant_id,
                *w.goal_ids,
            )
        ]
        + ["Isolated holiday"]
    )
    # B has a small ledger of their own (and none of A's names).
    with signed_in_as(B_USER):
        roots = {a["name"]: a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
        w.b_roots = roots
        w.b_mine = post_account(client, {"name": "Mine", "parent_id": roots["Assets"], "balance": "700"}).json()
        w.b_bills = post_account(client, {"name": "Bills", "parent_id": roots["Expenses"]}).json()
        client.post(
            "/api/transactions/",
            json={
                "payee": "Power",
                "postings": [
                    leg(w.b_bills, "debit", "40"),
                    leg(w.b_mine, "credit", "40"),
                ],
            },
        )
        w.b_backup = client.get("/api/backup").json()
    return w


def sans_time(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "exported_at"}


def books_of(client: TestClient, user_id: UUID) -> dict:
    with signed_in_as(user_id):
        return sans_time(client.get("/api/backup").json())


def leaked(world: World, text: str, sent: str = "") -> list[str]:
    """A's names and ids in a response, except ones the caller sent in the request (an error may repeat them)."""
    return [m for m in world.markers if m in text and m not in sent]


# ---- every route that takes an id ------------------------------------------------------------------------------

BAD_ANSWERS = {400, 403, 404, 405, 409, 422}


def id_routes() -> list[tuple[str, str]]:
    return sorted((m, p) for m, p in routes() if "{" in p and (m, p) not in PUBLIC and m != "HEAD")


def candidates(world: World, name: str) -> list[str]:
    return {
        "account_id": [*world.accounts.values(), *world.roots],
        "category_id": list(world.categories.values()),
        "transaction_id": world.transaction_ids,
        "history_id": world.history_ids,
        "deletion_id": world.deletion_ids,
        "recurring_id": world.recurring_ids,
        "token_id": [world.token_id],
        "grant_id": [world.grant_id],
        "goal_id": world.goal_ids,
        "name": world.tags,
    }[name]


def body_for(world: World, method: str, path: str) -> dict:
    """A valid-looking request, so a refusal comes from the ownership check and not from validation."""
    mine, bills = world.b_mine["id"], world.b_bills["id"]
    rows = {"date": "2026-10-01", "account_id": [bills, mine], "side": ["debit", "credit"], "amount": ["5", "5"]}
    api = path.startswith("/api/")
    bodies = {
        ("PATCH", "/api/accounts/{account_id}"): {"json": {"name": "hacked", "details": "hacked"}},
        ("PATCH", "/api/transactions/{transaction_id}"): {"json": {"payee": "hacked"}},
        ("PUT", "/api/budget/categories/{category_id}"): {"json": {"amount": "5"}},
        ("PUT", "/api/recurring/{recurring_id}"): {
            "json": {"from_account_id": mine, "to_account_id": bills, "amount": "1", "start_date": "2999-01-01"}
        },
        ("POST", "/accounts/{account_id}/edit"): {"data": {"name": "hacked"}},
        ("POST", "/transactions/{transaction_id}/edit"): {"data": rows},
        ("POST", "/recurring/{recurring_id}/edit"): {
            "data": {**rows, "frequency": "monthly", "every": "1", "start": "2999-01-01"}
        },
        ("POST", "/budget/goal/{goal_id}"): {"data": {"name": "hacked", "amount": "5", "by": "2999-12"}},
        ("POST", "/budget/goal/{goal_id}/use"): {"data": {"category": bills, "amount": "1"}},
        ("POST", "/budget/goal/{goal_id}/assign"): {"data": {"amount": "5"}},
        ("POST", "/api/accounts/{account_id}/merge"): {"json": {"into": bills}},
        ("POST", "/api/categories/{category_id}/merge"): {"json": {"into": bills}},
        ("PATCH", "/api/categories/{category_id}"): {"json": {"name": "hacked"}},
        ("POST", "/oauth/apps/{grant_id}/access"): {"data": {"scope": "read"}},
        ("POST", "/profile/assistants/{token_id}/access"): {"data": {"scope": "read"}},
    }
    return bodies.get((method, path), {"json": {}} if api else {"data": {}})


def test_nothing_of_a_is_reachable_by_id(client: TestClient, world: World):
    before_a = books_of(client, TEST_USER_ID)
    before_b = books_of(client, B_USER)
    problems: list[str] = []
    calls = 0
    with signed_in_as(B_USER):
        for method, template in id_routes():
            name = template.split("{")[1].split("}")[0].split(":")[0]
            for value in candidates(world, name):
                url = template.replace("{" + name + "}", value)
                response = client.request(method, url, **body_for(world, method, template), follow_redirects=False)
                calls += 1
                redirect_only = response.status_code in (301, 307) and "/accounts/" in response.headers.get(
                    "location", ""
                )
                if response.status_code not in BAD_ANSWERS and not redirect_only:
                    problems.append(f"{method} {url} -> {response.status_code}")
                echoed = response.text.replace(value, "")  # an error may repeat the id the caller sent
                if leaked(world, echoed):
                    problems.append(f"{method} {url} leaked {leaked(world, echoed)[:2]}")
    assert calls > 150, "the sweep must really run"
    assert not problems, problems[:10]
    assert books_of(client, TEST_USER_ID) == before_a, "A's books were changed"
    assert books_of(client, B_USER) == before_b, "B's own books changed too (a refused request did something)"


# ---- what lists and pages show ---------------------------------------------------------------------------------


def test_b_sees_only_b_in_every_list_and_page(client: TestClient, session, world: World):
    seen = 0
    with signed_in_as(B_USER):
        for _method, path in sorted(LISTS):
            response = client.get(path)
            assert response.status_code in (200, 404, 400), (path, response.status_code)
            assert not leaked(world, response.text), (path, leaked(world, response.text)[:3])
            seen += 1
        # The numbers are B's too: the same endpoints, read as data.
        theirs = services(session, B_USER)
        assert plain(theirs.reports.summary())["net_worth"] == "660.00"
        trial = client.get("/api/reports/trial-balance").json()
        assert trial["balanced"] and {a["account"] for a in trial["lines"]} <= {
            "Assets:Mine",
            "Expenses:Bills",
            "Equity:Opening Balances",
        }
        assert {a["name"] for a in client.get("/api/accounts/").json() if a["parent_id"]} == {
            "Mine",
            "Opening Balances",
        }
        assert {c["name"] for c in client.get("/api/categories/").json()} == {"Bills"}
        assert sorted(t["payee"] for t in client.get("/api/transactions/").json() if t["payee"]) == [
            "Opening balance",
            "Power",
        ]
        assert theirs.transactions.deleted() == [] and theirs.accounts.restorable() == []
        assert client.get("/api/recurring/").json() == []
        assert client.get("/api/profile/").json()["first_name"] in (None, "")
        assert {l["name"] for l in client.get("/api/budget/").json()["lines"]} <= {"Bills"}
        backup = client.get("/api/backup").json()
        assert backup["recurring"] == [] and backup["allocations"] == []
        assert "Power" in json.dumps(backup) and not leaked(world, json.dumps(backup))
    assert seen == len(LISTS)


# ---- A's things named inside B's own requests ---------------------------------------------------------------------


def test_b_cannot_use_a_s_things_in_requests(client: TestClient, world: World):
    a = world.accounts
    mine, bills = world.b_mine["id"], world.b_bills["id"]
    before_a = books_of(client, TEST_USER_ID)
    before_b = books_of(client, B_USER)
    refusals = []

    def refused(label: str, method: str, url: str, **kw):
        response = client.request(method, url, **kw)
        sent = json.dumps(kw, default=str) + url
        refusals.append(label)
        assert (
            response.status_code in BAD_ANSWERS
            or "HX-Retarget" in response.headers
            or (response.status_code == 200 and ("Nothing was" in response.text or "error" in response.text.lower()))
        ), (label, response.status_code, response.text[:200])
        assert not leaked(world, response.text, sent), (label, leaked(world, response.text, sent)[:3])

    with signed_in_as(B_USER):
        # the JSON API
        refused(
            "tx with A's account",
            "POST",
            "/api/transactions/",
            json={
                "postings": [
                    {"category_id": a["Groceries"], "side": "debit", "amount": "5"},
                    {"account_id": mine, "side": "credit", "amount": "5"},
                ]
            },
        )
        refused("merge into A's account", "POST", f"/api/accounts/{mine}/merge", json={"into": a["Groceries"]})
        refused(
            "A's category on B's line",
            "POST",
            "/api/transactions/",
            json={
                "postings": [
                    {
                        "account_id": world.b_roots["Expenses"],
                        "side": "debit",
                        "amount": "5",
                        "category_id": a["Groceries"],
                    },
                    {"account_id": mine, "side": "credit", "amount": "5"},
                ]
            },
        )
        refused(
            "a line that names only A's category",
            "POST",
            "/api/transactions/",
            json={
                "postings": [
                    {"category_id": a["Groceries"], "side": "debit", "amount": "5"},
                    {"account_id": mine, "side": "credit", "amount": "5"},
                ]
            },
        )
        refused(
            "a category inside A's group",
            "POST",
            "/api/categories/",
            json={"name": "Mine", "kind": "spending", "parent_id": a["Groceries"]},
        )
        refused("a category merged into A's", "POST", f"/api/categories/{bills}/merge", json={"into": a["Groceries"]})
        refused(
            "batch with A's account",
            "POST",
            "/api/transactions/batch",
            json={
                "transactions": [
                    {
                        "postings": [
                            {"category_id": bills, "side": "debit", "amount": "5"},
                            {"account_id": mine, "side": "credit", "amount": "5"},
                        ]
                    },
                    {
                        "postings": [
                            {"category_id": a["Groceries"], "side": "debit", "amount": "5"},
                            {"account_id": mine, "side": "credit", "amount": "5"},
                        ]
                    },
                ]
            },
        )
        refused(
            "tx both A's",
            "POST",
            "/api/transactions/",
            json={
                "postings": [
                    {"category_id": a["Groceries"], "side": "debit", "amount": "5"},
                    {"account_id": a["HDFC"], "side": "credit", "amount": "5"},
                ]
            },
        )
        refused("account under A's group", "POST", "/api/accounts/", json={"name": "x", "parent_id": a["Banks"]})
        refused(
            "account under A's group (again)", "POST", "/api/accounts/", json={"name": "x", "parent_id": a["Banks"]}
        )
        refused("move into A's group", "PATCH", f"/api/accounts/{mine}", json={"parent_id": a["Banks"]})
        refused("A's payment category", "PATCH", f"/api/accounts/{mine}", json={"payment_category_id": a["Groceries"]})
        refused(
            "recurring on A's accounts",
            "POST",
            "/api/recurring/",
            json={
                "from_account_id": a["HDFC"],
                "to_account_id": a["Groceries"],
                "amount": "1",
                "start_date": "2999-01-01",
            },
        )
        refused(
            "recurring split with A's",
            "POST",
            "/api/recurring/",
            json={
                "start_date": "2999-01-01",
                "postings": [line({"id": a["Groceries"]}, "debit", "5"), line({"id": mine}, "credit", "5")],
            },
        )
        refused("budget A's category", "PUT", f"/api/budget/categories/{a['Groceries']}", json={"amount": "5"})
        refused(
            "API budget move A's",
            "POST",
            "/api/budget/move",
            json={"from_category": a["Groceries"], "to_category": bills, "amount": "1"},
        )
        refused("API group budget for A's", "PUT", f"/api/budget/groups/{a['Groceries']}", json={"total": "5"})
        refused("API include A's account", "POST", f"/api/budget/accounts/{a['HDFC']}/include")
        refused("API reopen A's account", "POST", f"/api/accounts/{a['HDFC']}/reopen")
        refused("API register of A's account", "GET", f"/api/accounts/{a['HDFC']}/register")
        refused("API filter by A's category", "GET", "/api/transactions/", params={"category_id": a["Groceries"]})
        refused(
            "budget move A's",
            "POST",
            "/budget/move",
            data={"from_category": a["Groceries"], "to_category": bills, "amount": "1"},
        )
        refused(
            "restore into a used ledger",
            "POST",
            "/api/restore",
            files={"file": ("b.json", json.dumps(world.backup), "application/json")},
        )
        # the web forms
        refused(
            "form tx with A's account",
            "POST",
            "/transactions/split",
            data={
                "date": "2026-10-01",
                "account": [a["Groceries"], mine],
                "side": ["debit", "credit"],
                "amount": ["5", "5"],
            },
        )
        refused(
            "form recurring with A's",
            "POST",
            "/recurring",
            data={
                "account": [a["Groceries"], mine],
                "side": ["debit", "credit"],
                "amount": ["5", "5"],
                "frequency": "monthly",
                "every": "1",
                "start": "2999-01-01",
            },
        )
        refused("assign A's category", "POST", "/budget/assign", data={"category": a["Groceries"], "amount": "5"})
        refused(
            "move A's money",
            "POST",
            "/budget/move",
            data={"from_category": a["Groceries"], "to_category": bills, "amount": "1"},
        )
        refused("move page for A's category", "GET", "/budget/move", params={"source": a["Groceries"]})
        refused("quick account under A's group", "POST", "/accounts/quick", data={"name": "x", "parent_id": a["Banks"]})
        refused(
            "quick category inside A's", "POST", "/categories/quick", data={"name": "x", "parent_id": a["Groceries"]}
        )
        refused("a category inside A's", "POST", "/categories", data={"name": "x", "parent_id": a["Groceries"]})
        refused("account form under A's group", "POST", "/accounts", data={"name": "x", "parent_id": a["Banks"]})
    assert len(refusals) >= 18
    assert books_of(client, TEST_USER_ID) == before_a, "A's books were changed"
    assert books_of(client, B_USER) == before_b, "a refused request still changed B's books"


def test_tags_are_per_person(client: TestClient, world: World):
    """B sees none of A's tags, cannot rename or delete them, and may use the same names for their own."""
    mine = sorted(t["tag"] for t in client.get("/api/tags/").json())
    assert "food" in mine and "weekly-shop" in mine
    before = books_of(client, TEST_USER_ID)
    with signed_in_as(B_USER):
        assert client.get("/api/tags/").json() == []
        assert client.patch("/api/tags/food", json={"name": "taken"}).status_code == 404
        assert client.delete("/api/tags/food").status_code == 404
        assert client.get("/tags/food/sheet").status_code == 404
        assert client.post("/tags/food/delete").status_code == 404
        assert (
            "food" not in client.get("/tags").text and "weekly-shop" not in client.get("/transactions/tag-picker").text
        )
        assert client.get("/api/transactions/", params={"tag": "food"}).json() == []
        made = client.post(
            "/api/transactions/",
            json={"tags": ["food"], "postings": [line(world.b_bills, "debit", "5"), line(world.b_mine, "credit", "5")]},
        )
        assert made.status_code == 201, made.text
        assert [t["tag"] for t in client.get("/api/tags/").json()] == ["food"], "the same name, their own tag"
    assert books_of(client, TEST_USER_ID) == before
    assert sorted(t["tag"] for t in client.get("/api/tags/").json()) == mine, "A's tags are untouched"


def test_a_goal_is_made_in_the_callers_own_books(client: TestClient, world: World):
    """B may call a goal what A calls theirs (names are per person); it lands in B's books and A's stay as they were."""
    before = books_of(client, TEST_USER_ID)
    with signed_in_as(B_USER):
        assert client.get("/api/budget/").json()["goals"] == [], "A's goal is not B's"
        done = client.post(
            "/budget/goal", data={"name": "Isolated holiday", "amount": "1000", "by": "2999-12", "assign_now": "1"}
        )
        assert done.status_code == 200, done.text
        mine = client.get("/api/budget/").json()["goals"]
        assert [g["name"] for g in mine] == ["Isolated holiday"] and mine[0]["id"] not in world.goal_ids
    assert books_of(client, TEST_USER_ID) == before


def test_a_backup_is_only_ever_the_callers_own(client: TestClient, world: World):
    with signed_in_as(B_USER):
        doc = client.get("/api/backup").json()
    assert {a["name"] for a in doc["accounts"]} == set({a["name"] for a in world.b_backup["accounts"]})
    assert not leaked(world, json.dumps(doc))
    # A's own file restores for a third person without touching A or B.
    before_a, before_b = books_of(client, TEST_USER_ID), books_of(client, B_USER)
    third = UUID("00000000-0000-4000-8000-0000000000c3")
    with signed_in_as(third):
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(world.backup), "application/json")})
        assert done.status_code == 200, done.text
        theirs = client.get("/api/backup").json()
    assert books_of(client, TEST_USER_ID) == before_a and books_of(client, B_USER) == before_b
    ids_a = {a["id"] for a in world.backup["accounts"]}
    assert not ids_a & {a["id"] for a in theirs["accounts"]}, "restoring makes new rows, never shares A's"


def test_b_erasing_their_own_books_leaves_a_alone(client: TestClient, world: World, monkeypatch):
    from app.config import settings
    from app.routers.web import profile as profile_router

    before_a = books_of(client, TEST_USER_ID)
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    deleted = []
    monkeypatch.setattr(profile_router, "delete_user", lambda user_id: deleted.append(user_id))
    with signed_in_as(B_USER):
        assert client.post("/profile/data/erase", data={"confirm": "x@example.com"}).headers["HX-Redirect"] == "/"
        assert (
            client.post("/profile/data/delete-account", data={"confirm": "x@example.com"}).headers["HX-Redirect"]
            == "/login"
        )
    assert deleted == [B_USER], "only B's login"
    assert books_of(client, TEST_USER_ID) == before_a, "A's books are exactly as they were"


# ---- the assistants' door -------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_b_s_assistant_cannot_reach_a(client: TestClient, session, world: World):
    a = world.accounts
    before_a = books_of(client, TEST_USER_ID)
    secret = make_token(session, B_USER, name="B-Assistant")
    async with running_app(session), mcp_client(secret) as c:

        async def fails(tool: str, **arguments):
            with pytest.raises(ToolFailed):
                payload(await c.call_tool(tool, arguments))

        listed = json.dumps(payload(await c.call_tool("list_accounts", {})))
        assert not leaked(world, listed) and "Mine" in listed
        for tool in ("get_overview", "check_books", "get_budget", "list_recurring"):
            assert not leaked(world, json.dumps(payload(await c.call_tool(tool, {})))), tool
        assert not leaked(world, json.dumps(payload(await c.call_tool("search_transactions", {}))))
        await fails("get_account", account="HDFC")
        await fails("get_account", account=a["HDFC"])
        await fails("get_transaction", transaction_id=world.transaction_ids[0])
        await fails("update_transaction", transaction_id=world.transaction_ids[0], payee="hacked")
        await fails("delete_transaction", transaction_id=world.transaction_ids[0])
        await fails("record_transaction", amount="1", from_account=a["HDFC"], to_account="Bills")
        await fails("record_transaction", amount="1", from_account="Mine", to_account=a["Groceries"])
        await fails("assign_to_category", category=a["Groceries"], amount="5")
        await fails("assign_to_category", category="Groceries", amount="5")
        await fails("stop_recurring", recurring_id=world.recurring_ids[0])
        await fails("create_account", name="x", parent=a["Banks"])
    assert books_of(client, TEST_USER_ID) == before_a, "A's books were changed through an assistant"


@pytest.mark.anyio
async def test_a_token_only_ever_acts_as_its_owner(client: TestClient, session, world: World):
    """A's token reads A's books and B's reads B's, whoever is signed in on the web at the time."""
    secret_a = make_token(session, TEST_USER_ID, name="A-Phone")
    secret_b = make_token(session, B_USER, name="B-Phone")
    async with running_app(session):
        async with mcp_client(secret_a) as ca:
            assert "HDFC" in json.dumps(payload(await ca.call_tool("list_accounts", {})))
        async with mcp_client(secret_b) as cb:
            assert "HDFC" not in json.dumps(payload(await cb.call_tool("list_accounts", {})))


# ---- doors without a sign-in ----------------------------------------------------------------------------------


def test_nothing_answers_without_a_sign_in(session, world: World):
    app.dependency_overrides.pop(require_authenticated_user, None)
    app.dependency_overrides.pop(web_login_required, None)
    app.dependency_overrides[get_db_session] = lambda: session
    try:
        with TestClient(app, follow_redirects=False) as anonymous:
            problems = []
            checked = 0
            for method, template in sorted(routes()):
                if (method, template) in PUBLIC or method == "HEAD":
                    continue
                url = template
                for name in (
                    "account_id",
                    "transaction_id",
                    "recurring_id",
                    "history_id",
                    "deletion_id",
                    "token_id",
                    "grant_id",
                    "category_id",
                    "goal_id",
                    "name",
                ):
                    url = url.replace("{" + name + "}", str(world.transaction_ids[0]))
                response = anonymous.request(
                    method,
                    url,
                    json={} if url.startswith("/api/") else None,
                    data=None if url.startswith("/api/") else {},
                )
                checked += 1
                ok = response.status_code in (401, 403) or (
                    response.status_code in (302, 303, 307) and "/login" in response.headers.get("location", "")
                )
                if not ok or leaked(world, response.text):
                    problems.append((method, url, response.status_code))
            assert checked > 100 and not problems, problems[:10]
            # the assistants' door wants a token
            assert anonymous.post("/mcp", json={}).status_code == 401
            assert (
                anonymous.post("/mcp", json={}, headers={"Authorization": "Bearer fin_notarealtoken"}).status_code
                == 401
            )
    finally:
        app.dependency_overrides.clear()
