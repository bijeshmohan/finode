"""The AI assistants page: creating, showing once and revoking tokens; marks on what assistants did."""

from tests.htmlutil import element, text_of

from .conftest import TEST_USER_ID
from .mcputil import make_token


def test_profile_links_to_the_assistants_page(client):
    assert 'href="/profile/assistants"' in client.get("/profile").text


def test_page_shows_setup_with_this_servers_address(client):
    page = client.get("/profile/assistants")
    assert page.status_code == 200
    assert "<title>AI assistants · finode</title>" in page.text
    assert "http://testserver/mcp" in page.text and "YOUR_TOKEN" in page.text
    assert "Nothing connected yet." in page.text


def test_creating_a_token_shows_it_once_and_lists_it(client):
    response = client.post("/profile/assistants", data={"name": "Claude Desktop", "scope": "write"})
    assert response.status_code == 200
    secret = text_of(element(response.text, "token-secret")).strip()
    assert secret.startswith("fin_")
    assert f"Bearer {secret}" in response.text, "the snippets are filled in"
    assert 'id="token-list" hx-swap-oob="true"' in response.text and "Claude Desktop" in response.text

    page = client.get("/profile/assistants").text
    assert "Claude Desktop" in page and "read &amp; write" in page
    assert secret not in page, "never shown again"
    assert secret[:10] + "…" in page


def test_creating_reports_errors(client):
    response = client.post("/profile/assistants", data={"name": " ", "scope": "read"})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#token-error"
    client.post("/profile/assistants", data={"name": "Desk"})
    again = client.post("/profile/assistants", data={"name": "desk"})
    assert again.status_code == 400 and "already have a token" in again.text
    bad = client.post("/profile/assistants", data={"name": "x", "scope": "root"})
    assert bad.status_code == 400


def test_revoking_hides_the_token(client, session):
    make_token(session, TEST_USER_ID, name="Old laptop")
    page = client.get("/profile/assistants").text
    import re

    tkid = re.search(r'/profile/assistants/([0-9a-f-]+)/revoke', page).group(1)
    response = client.post(f"/profile/assistants/{tkid}/revoke")
    assert response.headers["HX-Redirect"] == "/profile/assistants"
    assert "token-revoked" in response.headers["set-cookie"]
    assert "Old laptop" not in client.get("/profile/assistants").text
    assert client.post("/profile/assistants/00000000-0000-4000-8000-0000000000aa/revoke").status_code == 404


def test_origin_is_recorded_for_web_api_and_import(client, root_accounts):
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    api = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5"},
                {"account": bank["aid"], "side": "credit", "amount": "5"},
            ]
        },
    ).json()
    assert api["created_via"] == "api" and api["updated_via"] == "api"
    client.post("/transactions", data={"amount": "7", "from_account": bank["aid"], "to_account": food["aid"]})
    web = next(t for t in client.get("/api/transactions/").json() if t["tid"] != api["tid"])
    assert web["created_via"] == "web"
    listing = client.get("/transactions").text
    assert "Added by" not in listing and "Changed by" not in listing, "only assistants are marked in the list"


def test_imports_are_marked(client):
    journal = "2026-09-01 Shop\n    Expenses:Food  10\n    Assets:Cash\n"
    response = client.post("/api/import", files={"file": ("a.ledger", journal.encode())})
    assert response.status_code == 200, response.text
    assert client.get("/api/transactions/").json()[0]["created_via"] == "import"


def test_breakdown_is_also_in_the_json_api(client, root_accounts):
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.post("/transactions", data={"amount": "70", "from_account": bank["aid"], "to_account": food["aid"]})
    report = client.get("/api/reports/breakdown").json()
    assert report["root"] == "Expenses" and report["total"] == "70.00"
    assert report["lines"] == [{"account": "Food", "amount": "70.00"}]
    assert client.get("/api/reports/breakdown", params={"depth": 0}).status_code == 400
    assert client.get("/api/reports/breakdown", params={"root": "Assets"}).status_code == 422


def test_page_explains_both_access_levels_on_the_token_form(client):
    page = client.get("/profile/assistants").text
    assert 'name="scope" value="read" checked' in page and 'name="scope" value="write"' in page
    assert "Never edits or deletes accounts" in page and "Cannot change anything" in page
    assert 'data-copy="#mcp-address"' in page


def test_a_tokens_access_can_be_changed_without_a_new_token(client, session):
    secret = make_token(session, TEST_USER_ID, name="Laptop", scope="read")
    import re

    page = client.get("/profile/assistants").text
    tkid = re.search(r"/profile/assistants/([0-9a-f-]+)/access", page).group(1)
    assert "Allow changes" in page
    response = client.post(f"/profile/assistants/{tkid}/access", data={"scope": "write"})
    assert response.headers["HX-Redirect"] == "/profile/assistants" and "access-changed" in response.headers["set-cookie"]
    page = client.get("/profile/assistants").text
    assert "Make read only" in page and "Allow changes" not in page
    from app.services.api_token import ApiTokenService

    assert ApiTokenService.authenticate(session, secret).scope == "write", "the same secret now writes"
    assert client.post(f"/profile/assistants/{tkid}/access", data={"scope": "root"}).status_code == 400
    assert client.post("/profile/assistants/00000000-0000-4000-8000-0000000000aa/access", data={"scope": "read"}).status_code == 404


def test_connected_apps_and_tokens_share_one_list_and_apps_can_change_access(client, session):
    from app.repositories.oauth_grant import OAuthGrantRepository
    from app.services.oauth_grant import OAuthGrantService

    make_token(session, TEST_USER_ID, name="Laptop")
    grant = OAuthGrantService(OAuthGrantRepository(session, TEST_USER_ID)).allow("c1", "Claude", "read")
    page = client.get("/profile/assistants").text
    assert "Claude" in page and "Laptop" in page and "Signed in" in page
    assert client.post(f"/oauth/apps/{grant.gid}/access", data={"scope": "write"}).headers["HX-Redirect"]
    session.refresh(grant)
    assert grant.scope == "write"
    assert client.post(f"/oauth/apps/{grant.gid}/access", data={"scope": "x"}).status_code == 400
    assert client.post("/oauth/apps/00000000-0000-4000-8000-0000000000aa/access", data={"scope": "read"}).status_code == 404
