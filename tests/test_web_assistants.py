"""The AI assistants page: creating, showing once and revoking tokens; marks on what assistants did."""

from tests.htmlutil import element, text_of

from .conftest import TEST_USER_ID
from .mcputil import make_token


def test_profile_links_to_the_assistants_page(client):
    assert 'href="/app/profile/assistants"' in client.get("/app/profile").text


def test_page_shows_setup_with_this_servers_address(client):
    page = client.get("/app/profile/assistants")
    assert page.status_code == 200
    assert "<title>AI assistants · finode</title>" in page.text
    assert "http://testserver/mcp" in page.text and "YOUR_TOKEN" in page.text
    assert "No tokens yet." in page.text


def test_creating_a_token_shows_it_once_and_lists_it(client):
    response = client.post("/app/profile/assistants", data={"name": "Claude Desktop", "scope": "write"})
    assert response.status_code == 200
    secret = text_of(element(response.text, "token-secret")).strip()
    assert secret.startswith("fin_")
    assert f"Bearer {secret}" in response.text, "the snippets are filled in"
    assert 'id="token-list" hx-swap-oob="true"' in response.text and "Claude Desktop" in response.text

    page = client.get("/app/profile/assistants").text
    assert "Claude Desktop" in page and "read &amp; write" in page
    assert secret not in page, "never shown again"
    assert secret[:10] + "…" in page


def test_creating_reports_errors(client):
    response = client.post("/app/profile/assistants", data={"name": " ", "scope": "read"})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#token-error"
    client.post("/app/profile/assistants", data={"name": "Desk"})
    again = client.post("/app/profile/assistants", data={"name": "desk"})
    assert again.status_code == 400 and "already have a token" in again.text
    bad = client.post("/app/profile/assistants", data={"name": "x", "scope": "root"})
    assert bad.status_code == 400


def test_revoking_hides_the_token(client, session):
    make_token(session, TEST_USER_ID, name="Old laptop")
    page = client.get("/app/profile/assistants").text
    import re

    tkid = re.search(r'/app/profile/assistants/([0-9a-f-]+)/revoke', page).group(1)
    response = client.post(f"/app/profile/assistants/{tkid}/revoke")
    assert response.headers["HX-Redirect"] == "/app/profile/assistants"
    assert "token-revoked" in response.headers["set-cookie"]
    assert "Old laptop" not in client.get("/app/profile/assistants").text
    assert client.post("/app/profile/assistants/00000000-0000-4000-8000-0000000000aa/revoke").status_code == 404


def test_origin_is_recorded_for_web_api_and_import(client, root_accounts):
    bank = client.post("/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = client.post("/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    api = client.post(
        "/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5"},
                {"account": bank["aid"], "side": "credit", "amount": "5"},
            ]
        },
    ).json()
    assert api["created_via"] == "api" and api["updated_via"] == "api"
    client.post("/app/transactions", data={"amount": "7", "from_account": bank["aid"], "to_account": food["aid"]})
    web = next(t for t in client.get("/transactions/").json() if t["tid"] != api["tid"])
    assert web["created_via"] == "web"
    listing = client.get("/app/transactions").text
    assert "Added by" not in listing and "Changed by" not in listing, "only assistants are marked in the list"


def test_imports_are_marked(client):
    journal = "2026-09-01 Shop\n    Expenses:Food  10\n    Assets:Cash\n"
    response = client.post("/import", files={"file": ("a.ledger", journal.encode())})
    assert response.status_code == 200, response.text
    assert client.get("/transactions/").json()[0]["created_via"] == "import"


def test_breakdown_is_also_in_the_json_api(client, root_accounts):
    bank = client.post("/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = client.post("/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.post("/app/transactions", data={"amount": "70", "from_account": bank["aid"], "to_account": food["aid"]})
    report = client.get("/reports/breakdown").json()
    assert report["root"] == "Expenses" and report["total"] == "70.00"
    assert report["lines"] == [{"account": "Food", "amount": "70.00"}]
    assert client.get("/reports/breakdown", params={"depth": 0}).status_code == 400
    assert client.get("/reports/breakdown", params={"root": "Assets"}).status_code == 422
