"""An entry can be related to an earlier one: a link, stored on the new entry, shown on both."""

from uuid import UUID

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

from .conftest import TEST_USER_ID
from .svc import services

OTHER = UUID("00000000-0000-4000-8000-0000000000bb")


def as_user(user_id):
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=user_id, email="x@example.com", claims={})


def make(client, debit, credit, amount, payee, on="2026-10-10", **extra):
    body = {
        "date": on, "payee": payee,
        "postings": [
            {"account": debit["aid"], "side": "debit", "amount": amount},
            {"account": credit["aid"], "side": "credit", "amount": amount},
        ],
        **extra,
    }
    response = client.post("/api/transactions/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_entry_can_name_the_one_it_is_related_to(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    assert first["related_id"] is None
    second = make(client, account, expense_account, "300", "Swiggy", related_id=first["tid"])
    assert second["related_id"] == first["tid"]
    assert client.get(f"/api/transactions/{second['tid']}").json()["related_id"] == first["tid"]


def test_the_link_must_lead_to_one_of_your_own_entries(client, account, expense_account):
    body = {
        "postings": [
            {"account": expense_account["aid"], "side": "debit", "amount": "5"},
            {"account": account["aid"], "side": "credit", "amount": "5"},
        ],
    }
    missing = client.post("/api/transactions/", json={**body, "related_id": "00000000-0000-4000-8000-0000000000aa"})
    assert missing.status_code == 400 and "not found" in missing.text
    # Somebody else's entry is as good as missing.
    mine = make(client, expense_account, account, "10", "Mine")
    try:
        as_user(OTHER)
        roots = {x["name"]: x["aid"] for x in client.get("/api/accounts/").json() if x["parent_id"] is None}
        bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": roots["Assets"]}).json()
        food = client.post("/api/accounts/", json={"name": "Food", "parent_id": roots["Expenses"]}).json()
        theirs = {"postings": [
            {"account": food["aid"], "side": "debit", "amount": "5"},
            {"account": bank["aid"], "side": "credit", "amount": "5"},
        ]}
        stranger = client.post("/api/transactions/", json={**theirs, "related_id": mine["tid"]})
        assert stranger.status_code == 400 and "not found" in stranger.text
    finally:
        as_user(TEST_USER_ID)


def test_an_entry_cannot_be_related_to_itself_or_in_a_circle(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["tid"])
    own = client.patch(f"/api/transactions/{a['tid']}", json={"related_id": a["tid"]})
    assert own.status_code == 400 and "itself" in own.text
    circle = client.patch(f"/api/transactions/{a['tid']}", json={"related_id": b["tid"]})
    assert circle.status_code == 400 and "already related" in circle.text


def test_changing_the_link_and_keeping_it(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B")
    assert client.patch(f"/api/transactions/{b['tid']}", json={"related_id": a["tid"]}).json()["related_id"] == a["tid"]
    assert client.patch(f"/api/transactions/{b['tid']}", json={"payee": "B2"}).json()["related_id"] == a["tid"], "left out keeps it"
    assert client.patch(f"/api/transactions/{b['tid']}", json={"related_id": None}).json()["related_id"] is None


def test_deleting_the_original_clears_the_link(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["tid"])
    assert client.delete(f"/api/transactions/{a['tid']}").status_code in (200, 204)
    assert client.get(f"/api/transactions/{b['tid']}").json()["related_id"] is None


def test_the_ledger_still_balances_with_links(client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    make(client, account, expense_account, "10", "A back", related_id=a["tid"])
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_related_opens_a_blank_form_with_the_link(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    page = client.get("/transactions/new", params={"related": first["tid"]}).text
    assert f'name="related" value="{first["tid"]}"' in page
    assert "Related to" in page and "Swiggy · 10 Oct · 1,000.00" in page
    import re
    assert not re.search(r'name="payee"[^>]*value="Swiggy"|value="Swiggy"[^>]*name="payee"', page), "nothing is copied from the original"
    assert 'value="1000' not in page
    assert client.get("/transactions/new", params={"related": "00000000-0000-4000-8000-0000000000aa"}).status_code == 404
    assert "data-related-chip" in page and "data-related-chip hidden" not in page


def test_a_plain_new_form_offers_the_dashed_row(client, account, expense_account):
    page = client.get("/transactions/new").text
    assert "+ Related to an earlier entry" in page
    assert "data-related-chip hidden" in page
    assert 'name="related" value=""' in page


def test_saving_the_form_keeps_the_link_and_the_edit_page_can_remove_it(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    saved = client.post("/transactions/split", data={
        "account": [account["aid"], expense_account["aid"]], "side": ["debit", "credit"], "amount": ["300", "300"],
        "date": "2026-10-12", "payee": "Swiggy refund", "related": first["tid"],
    })
    assert saved.status_code == 200, saved.text
    new = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "Swiggy refund")
    assert new["related_id"] == first["tid"]
    edit = client.get(f"/transactions/{new['tid']}/edit").text
    assert f'name="related" value="{first["tid"]}"' in edit and "Swiggy · 10 Oct · 1,000.00" in edit
    cleared = client.post(f"/transactions/{new['tid']}/edit", data={
        "account": [account["aid"], expense_account["aid"]], "side": ["debit", "credit"], "amount": ["300", "300"],
        "date": "2026-10-12", "payee": "Swiggy refund", "related": "",
    })
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"/api/transactions/{new['tid']}").json()["related_id"] is None


def test_the_form_refuses_a_link_that_is_not_there(client, account, expense_account):
    bad = client.post("/transactions/split", data={
        "account": [account["aid"], expense_account["aid"]], "side": ["debit", "credit"], "amount": ["3", "3"],
        "related": "not-an-id",
    })
    assert bad.status_code == 400 and "related transaction was not found" in bad.text


def test_both_sheets_show_the_link(client, account, expense_account):
    first = make(client, expense_account, account, "1000", "Swiggy")
    second = make(client, account, expense_account, "300", "Swiggy cashback", on="2026-10-12", related_id=first["tid"])
    new_sheet = client.get(f"/transactions/{second['tid']}/sheet").text
    assert "Related to" in new_sheet and f"/transactions/{first['tid']}/sheet" in new_sheet and "1,000.00" in new_sheet
    old_sheet = client.get(f"/transactions/{first['tid']}/sheet").text
    assert "Related · 1" in old_sheet and f"/transactions/{second['tid']}/sheet" in old_sheet and "300.00" in old_sheet
    assert f"/transactions/new?related={first['tid']}" in old_sheet and 'aria-label="Related"' in old_sheet
    plain = make(client, expense_account, account, "5", "Plain")
    assert "Related" not in client.get(f"/transactions/{plain['tid']}/sheet").text.replace('aria-label="Related"', "").replace('title="Related"', "")


def test_the_picker_lists_earlier_entries_and_narrows_by_text(client, account, expense_account):
    a = make(client, expense_account, account, "1000", "Swiggy")
    b = make(client, expense_account, account, "420", "DMart", on="2026-10-11")
    page = client.get("/transactions/related-picker").text
    assert "Related to…" in page and "Swiggy" in page and "DMart" in page and f'data-related-pick="{a["tid"]}"' in page
    assert page.index("DMart") < page.index("Swiggy"), "newest first"
    found = client.get("/transactions/related-picker", params={"results": 1, "q": "dmart"}).text
    assert "DMart" in found and "Swiggy" not in found and "<input" not in found
    assert "Nothing matches." in client.get("/transactions/related-picker", params={"results": 1, "q": "zzz"}).text
    left = client.get("/transactions/related-picker", params={"results": 1, "exclude": b["tid"]}).text
    assert "DMart" not in left and "Swiggy" in left


def test_the_backup_and_the_service_see_the_links(session, client, account, expense_account):
    a = make(client, expense_account, account, "10", "A")
    b = make(client, expense_account, account, "20", "B", related_id=a["tid"])
    doc = client.get("/api/backup").json()
    assert next(t for t in doc["transactions"] if t["id"] == b["tid"])["related_id"] == a["tid"]
    assert services(session).transactions.related(UUID(a["tid"]))[0].tid == UUID(b["tid"])


# ---- the details sheet on an account's or a category's own page ----------------------------------------------------

def test_account_and_category_pages_open_the_sheet_and_come_back(client, account, expense_account):
    made = make(client, expense_account, account, "250", "DMart")
    for page_url, back in ((f"/accounts/{account['aid']}", f"/accounts/{account['aid']}"), (f"/categories/{expense_account['aid']}", f"/categories/{expense_account['aid']}")):
        page = client.get(page_url).text
        assert 'id="txn-sheet-body"' in page, page_url
        assert f'hx-get="/transactions/{made["tid"]}/sheet?back={back}"' in page, page_url
    sheet = client.get(f"/transactions/{made['tid']}/sheet", params={"back": f"/accounts/{account['aid']}"}).text
    back = f"/accounts/{account['aid']}"
    assert f"/transactions/{made['tid']}/edit?back={back}" in sheet
    assert f"/transactions/new?repeat={made['tid']}&amp;back={back}" in sheet or f"/transactions/new?repeat={made['tid']}&back={back}" in sheet
    plain = client.get(f"/transactions/{made['tid']}/sheet").text
    assert f"/transactions/{made['tid']}/edit\"" in plain and "back=" not in plain.split("sheet-actions")[1]
    assert "back=" not in client.get(f"/transactions/{made['tid']}/sheet", params={"back": "https://evil.example"}).text.split("sheet-actions")[1]


def test_an_upcoming_entry_on_an_account_page_opens_the_sheet(client, account, expense_account):
    from datetime import date, timedelta

    ahead = make(client, expense_account, account, "99", "Later", on=(date.today() + timedelta(days=5)).isoformat())
    page = client.get(f"/accounts/{account['aid']}").text
    assert f'hx-get="/transactions/{ahead["tid"]}/sheet?back=' in page and 'id="txn-sheet-body"' in page
