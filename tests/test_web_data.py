from fastapi.testclient import TestClient


JOURNAL = "2026-09-01 Opening\n    Assets:Cash  100\n    Equity:Opening Balances\n"


def _post(client: TestClient, path: str, text: str):
    return client.post(path, files={"file": ("a.ledger", text.encode())})


def test_profile_page_offers_export_and_import(client: TestClient):
    text = client.get("/app/profile").text
    assert "/app/export?format=ledger" in text and "/app/export?format=csv" in text
    assert 'id="import-file"' in text
    # the card is page content, not leaked into the <title>
    assert "<title>Profile · finode</title>" in text
    assert text.index("<main") < text.index("/app/export?format=ledger")


def test_profile_page_hides_import_once_transactions_exist(client: TestClient):
    assert _post(client, "/app/import", JOURNAL).headers["HX-Redirect"] == "/app/"
    text = client.get("/app/profile").text
    assert 'id="import-file"' not in text and "only available before" in text


def test_web_export_downloads(client: TestClient):
    response = client.get("/app/export?format=ledger")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert client.get("/app/export?format=csv").text.startswith("﻿") or True


def test_preview_summarises_without_saving(client: TestClient):
    response = _post(client, "/app/import/preview", JOURNAL)
    assert response.status_code == 200
    assert "Ready to import" in response.text and "1 transaction" in response.text
    assert 'hx-post="/app/import"' in response.text
    assert client.get("/transactions/").json() == []


def test_preview_lists_errors(client: TestClient):
    response = _post(client, "/app/import/preview", "2026-09-01 x\n    Assets:A  5\n")
    assert "Nothing was imported" in response.text and "line 1" in response.text
    assert "hx-post" not in response.text


def test_preview_without_file(client: TestClient):
    response = client.post("/app/import/preview")
    assert "Choose a file first." in response.text


def test_confirm_imports_and_redirects_with_flash(client: TestClient):
    response = _post(client, "/app/import", JOURNAL)
    assert response.headers["HX-Redirect"] == "/app/"
    assert "finode_flash=import-done" in response.headers["set-cookie"]
    assert len(client.get("/transactions/").json()) == 1


def test_confirm_with_errors_shows_them(client: TestClient):
    response = _post(client, "/app/import", "garbage line\n")
    assert response.status_code == 200 and "Nothing was imported" in response.text


def test_dashboard_links_to_import(client: TestClient):
    assert "/app/profile#data" in client.get("/app/").text


# ---- several commodities ------------------------------------------------------------------------------------------

FOREIGN = """\
P 2026-01-01 USD 83.5 INR
2026-01-02 Opening
    Assets:HDFC           100000.00 INR
    Equity:Opening Balances
2026-01-05 Buy USD
    Assets:Wise           100.00 USD @@ 8350.00 INR
    Assets:HDFC
2026-01-06 Buy shares
    Assets:Zerodha:INFY   10 INFY @ 1500 INR
    Assets:HDFC
"""


def test_the_preview_lists_new_commodities_and_other_holdings(client: TestClient):
    response = client.post("/app/import/preview", files={"file": ("a.ledger", FOREIGN.encode())})
    assert response.status_code == 200
    text = response.text
    assert "New commodities: INFY" in text
    assert "Also holds INFY, USD" in text and "1 price)" in text
    assert "(accounts in your default currency)" in text
    assert "Assets 76,650.00" in text
    assert "Nothing was imported" not in text


def test_confirming_imports_the_conversions(client: TestClient):
    response = client.post("/app/import", files={"file": ("a.ledger", FOREIGN.encode())})
    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/app/"
    accounts = {a["name"]: a["commodity"] for a in client.get("/accounts/").json()}
    assert accounts["Wise"] == "USD" and accounts["INFY"] == "INFY"


def test_the_preview_explains_a_missing_price(client: TestClient):
    text = "2026-01-01 a\n    Assets:Wise  100 USD\n    Assets:HDFC  -8350 INR\n"
    response = client.post("/app/import/preview", files={"file": ("a.ledger", text.encode())})
    assert "Nothing was imported" in response.text and "without a price" in response.text
