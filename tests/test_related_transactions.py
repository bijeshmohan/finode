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


def test_related_opens_a_blank_form_with_the_link(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    page = client.get("/transactions/new", params={"related": first["id"]}).text
    assert f'name="related" value="{first["id"]}"' in page
    assert "Related to" in page and "Swiggy · 10 Oct · 1,000.00" in page
    import re

    assert not re.search(r'name="payee"[^>]*value="Swiggy"|value="Swiggy"[^>]*name="payee"', page), (
        "nothing is copied from the original"
    )
    assert 'value="1000' not in page
    assert (
        client.get("/transactions/new", params={"related": "00000000-0000-4000-8000-0000000000aa"}).status_code == 404
    )
    assert "data-related-chip" in page and "data-related-chip hidden" not in page


def test_a_plain_new_form_offers_the_dashed_row(client, account, expense_account):
    page = client.get("/transactions/new").text
    assert "Transaction</button>" in page and "Related to an earlier entry" not in page
    assert "data-related-chip hidden" in page
    assert 'name="related" value=""' in page


def test_saving_the_form_keeps_the_link_and_the_edit_page_can_remove_it(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    saved = client.post(
        "/transactions/split",
        data={
            "account": [account["id"], expense_account["id"]],
            "side": ["debit", "credit"],
            "amount": ["300", "300"],
            "date": "2026-10-12",
            "payee": "Swiggy refund",
            "related": first["id"],
        },
    )
    assert saved.status_code == 200, saved.text
    new = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Swiggy refund")
    assert new["related_id"] == first["id"]
    edit = client.get(f"/transactions/{new['id']}/edit").text
    assert f'name="related" value="{first["id"]}"' in edit and "Swiggy · 10 Oct · 1,000.00" in edit
    cleared = client.post(
        f"/transactions/{new['id']}/edit",
        data={
            "account": [account["id"], expense_account["id"]],
            "side": ["debit", "credit"],
            "amount": ["300", "300"],
            "date": "2026-10-12",
            "payee": "Swiggy refund",
            "related": "",
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"/api/transactions/{new['id']}").json()["related_id"] is None


def test_the_form_refuses_a_link_that_is_not_there(client, account, expense_account):
    bad = client.post(
        "/transactions/split",
        data={
            "account": [account["id"], expense_account["id"]],
            "side": ["debit", "credit"],
            "amount": ["3", "3"],
            "related": "not-an-id",
        },
    )
    assert bad.status_code == 400 and "related transaction was not found" in bad.text


def test_both_sheets_show_the_link(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    second = make(client, account, expense_account, "300", "Swiggy cashback", on="2026-10-12", related_id=first["id"])
    new_sheet = client.get(f"/transactions/{second['id']}/sheet").text
    assert "Related to" in new_sheet and f"/transactions/{first['id']}/sheet" in new_sheet and "1,000.00" in new_sheet
    old_sheet = client.get(f"/transactions/{first['id']}/sheet").text
    assert "Related · 1" in old_sheet and f"/transactions/{second['id']}/sheet" in old_sheet and "300.00" in old_sheet
    assert f"/transactions/new?related={first['id']}" in old_sheet and ">Related</a>" in old_sheet
    plain = make(client, expense_account, account, "5", "Plain")
    assert "sheet-related" not in client.get(f"/transactions/{plain['id']}/sheet").text


def test_the_picker_lists_earlier_entries_and_narrows_by_text(client, account, expense_account):
    a = make(client, expense_account, account, "1000", "Swiggy")
    b = make(client, expense_account, account, "420", "DMart", on="2026-10-11")
    page = client.get("/transactions/related-picker").text
    assert "Related to…" in page and "Swiggy" in page and "DMart" in page and f'data-related-pick="{a["id"]}"' in page
    assert page.index("DMart") < page.index("Swiggy"), "newest first"
    found = client.get("/transactions/related-picker", params={"results": 1, "q": "dmart"}).text
    assert "DMart" in found and "Swiggy" not in found and "<input" not in found
    assert "Nothing matches." in client.get("/transactions/related-picker", params={"results": 1, "q": "zzz"}).text
    left = client.get("/transactions/related-picker", params={"results": 1, "exclude": b["id"]}).text
    assert "DMart" not in left and "Swiggy" in left


def test_the_backup_and_the_service_see_the_links(session, client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["id"])
    doc = client.get("/api/backup").json()
    assert next(t for t in doc["transactions"] if t["id"] == b["id"])["related_id"] == a["id"]
    assert services(session).transactions.related(UUID(a["id"]))[0].id == UUID(b["id"])


# ---- the details sheet on an account's or a category's own page ----------------------------------------------------


def test_account_and_category_pages_open_the_sheet_and_come_back(client, account, expense_account):
    made = make(client, expense_account, account, "250", "DMart")
    for page_url, back in (
        (f"/accounts/{account['id']}", f"/accounts/{account['id']}"),
        (f"/categories/{expense_account['id']}", f"/categories/{expense_account['id']}"),
    ):
        page = client.get(page_url).text
        assert 'id="txn-sheet-body"' in page, page_url
        assert f'hx-get="/transactions/{made["id"]}/sheet?back={back}"' in page, page_url
    sheet = client.get(f"/transactions/{made['id']}/sheet", params={"back": f"/accounts/{account['id']}"}).text
    back = f"/accounts/{account['id']}"
    assert f"/transactions/{made['id']}/edit?back={back}" in sheet
    assert (
        f"/transactions/new?repeat={made['id']}&amp;back={back}" in sheet
        or f"/transactions/new?repeat={made['id']}&back={back}" in sheet
    )
    plain = client.get(f"/transactions/{made['id']}/sheet").text
    assert f'/transactions/{made["id"]}/edit"' in plain and "back=" not in plain.split("sheet-actions")[1]
    assert (
        "back="
        not in client.get(f"/transactions/{made['id']}/sheet", params={"back": "https://evil.example"}).text.split(
            "sheet-actions"
        )[1]
    )


def test_an_upcoming_entry_on_an_account_page_opens_the_sheet(client, account, expense_account):
    from datetime import date, timedelta

    ahead = make(client, expense_account, account, "99", "Later", on=(date.today() + timedelta(days=5)).isoformat())
    page = client.get(f"/accounts/{account['id']}").text
    assert f'hx-get="/transactions/{ahead["id"]}/sheet?back=' in page and 'id="txn-sheet-body"' in page
