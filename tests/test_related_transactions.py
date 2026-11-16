"""An entry can be related to an earlier one: a link, stored on the new entry, shown on both."""

from uuid import UUID

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

from .books import leg, post_account
from .conftest import TEST_USER_ID
from .svc import services

OTHER = UUID("00000000-0000-4000-8000-0000000000bb")


def as_user(user_id):
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=user_id, email="x@example.com", claims={}
    )


def make(client, debit, credit, amount, payee, on="2026-10-10", **extra):
    body = {
        "date": on,
        "payee": payee,
        "postings": [
            leg(debit, "debit", amount),
            leg(credit, "credit", amount),
        ],
        **extra,
    }
    response = client.post("/api/transactions/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_entry_can_name_the_one_it_is_related_to(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    assert first["related_id"] is None
    second = make(client, account, expense_account, "300", "Swiggy", related_id=first["id"])
    assert second["related_id"] == first["id"]
    assert client.get(f"/api/transactions/{second['id']}").json()["related_id"] == first["id"]


def test_the_link_must_lead_to_one_of_your_own_entries(client, account, expense_account):
    body = {
        "postings": [
            leg(expense_account, "debit", "5"),
            leg(account, "credit", "5"),
        ],
    }
    missing = client.post("/api/transactions/", json={**body, "related_id": "00000000-0000-4000-8000-0000000000aa"})
    assert missing.status_code == 400 and "not found" in missing.text
    # Somebody else's entry is as good as missing.
    mine = make(client, expense_account, account, "10", "Mine")
    try:
        as_user(OTHER)
        roots = {x["name"]: x["id"] for x in client.get("/api/accounts/").json() if x["parent_id"] is None}
        bank = post_account(client, {"name": "Bank", "parent_id": roots["Assets"]}).json()
        food = post_account(client, {"name": "Food", "parent_id": roots["Expenses"]}).json()
        theirs = {
            "postings": [
                leg(food, "debit", "5"),
                leg(bank, "credit", "5"),
            ]
        }
        stranger = client.post("/api/transactions/", json={**theirs, "related_id": mine["id"]})
        assert stranger.status_code == 400 and "not found" in stranger.text
    finally:
        as_user(TEST_USER_ID)


def test_an_entry_cannot_be_related_to_itself_or_in_a_circle(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["id"])
    own = client.patch(f"/api/transactions/{a['id']}", json={"related_id": a["id"]})
    assert own.status_code == 400 and "itself" in own.text
    circle = client.patch(f"/api/transactions/{a['id']}", json={"related_id": b["id"]})
    assert circle.status_code == 400 and "already related" in circle.text


def test_changing_the_link_and_keeping_it(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B")
    assert client.patch(f"/api/transactions/{b['id']}", json={"related_id": a["id"]}).json()["related_id"] == a["id"]
    assert client.patch(f"/api/transactions/{b['id']}", json={"payee": "B2"}).json()["related_id"] == a["id"], (
        "left out keeps it"
    )
    assert client.patch(f"/api/transactions/{b['id']}", json={"related_id": None}).json()["related_id"] is None


def test_deleting_the_original_clears_the_link(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["id"])
    assert client.delete(f"/api/transactions/{a['id']}").status_code in (200, 204)
    assert client.get(f"/api/transactions/{b['id']}").json()["related_id"] is None


def test_the_ledger_still_balances_with_links(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    make(client, account, expense_account, "10", "A back", related_id=a["id"])
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_the_backup_and_the_service_see_the_links(session, client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["id"])
    doc = client.get("/api/backup").json()
    assert next(t for t in doc["transactions"] if t["id"] == b["id"])["related_id"] == a["id"]
    assert services(session).transactions.related(UUID(a["id"]))[0].id == UUID(b["id"])


# ---- the details sheet on an account's or a category's own page ----------------------------------------------------


def test_only_the_related_entry_carries_a_pill_with_the_originals_date_and_amount(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Amazon", on="2026-10-12")
    second = make(client, account, expense_account, "300", "Amazon refund", on="2026-10-20", related_id=first["id"])
    for url in ("/transactions?month=2026-10", f"/accounts/{account['id']}"):
        page = client.get(url).text
        assert page.count('class="tx-pill"') == 1, url
        marked = [r for r in page.split("<li>") if "tx-pill" in r]
        assert len(marked) == 1 and "Amazon refund" in marked[0], url
        assert "12 Oct" in marked[0] and "1,000.00" in marked[0], url
        assert f"/transactions/{first['id']}/sheet" in marked[0], "the pill opens the original, the row its own"
        assert f"/transactions/{second['id']}/sheet" in marked[0]
