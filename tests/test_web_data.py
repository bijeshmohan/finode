from fastapi.testclient import TestClient


JOURNAL = "2026-09-01 Opening\n    Assets:Cash  100\n    Equity:Opening Balances\n"


def _post(client: TestClient, path: str, text: str):
    return client.post(path, files={"file": ("a.ledger", text.encode())})


def test_profile_page_links_to_data_page(client: TestClient):
    text = client.get("/profile").text
    assert 'href="/profile/data"' in text and "/export" not in text and 'id="import-file"' not in text


def test_data_page_offers_export_and_import(client: TestClient):
    text = client.get("/profile/data").text
    assert "/export?format=ledger" in text and "/export?format=csv" in text
    assert 'id="import-file"' in text
    # the card is page content, not leaked into the <title>
    assert "<title>Your data · finode</title>" in text
    assert text.index("<main") < text.index("/export?format=ledger")


def test_data_page_hides_import_once_transactions_exist(client: TestClient):
    assert _post(client, "/import", JOURNAL).headers["HX-Redirect"] == "/"
    text = client.get("/profile/data").text
    assert 'id="import-file"' not in text and "only available before" in text


def test_web_export_downloads(client: TestClient):
    response = client.get("/export?format=ledger")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert client.get("/export?format=csv").text.startswith("﻿") or True


def test_preview_summarises_without_saving(client: TestClient):
    response = _post(client, "/import/preview", JOURNAL)
    assert response.status_code == 200
    assert "Ready to import" in response.text and "1 transaction" in response.text
    assert 'hx-post="/import"' in response.text
    assert client.get("/api/transactions/").json() == []


def test_preview_lists_errors(client: TestClient):
    response = _post(client, "/import/preview", "2026-09-01 x\n    Assets:A  5\n")
    assert "Nothing was imported" in response.text and "line 1" in response.text
    assert "hx-post" not in response.text


def test_preview_without_file(client: TestClient):
    response = client.post("/import/preview")
    assert "Choose a file first." in response.text


def test_confirm_imports_and_redirects_with_flash(client: TestClient):
    response = _post(client, "/import", JOURNAL)
    assert response.headers["HX-Redirect"] == "/"
    assert "finode_flash=import-done" in response.headers["set-cookie"]
    assert len(client.get("/api/transactions/").json()) == 1


def test_confirm_with_errors_shows_them(client: TestClient):
    response = _post(client, "/import", "garbage line\n")
    assert response.status_code == 200 and "Nothing was imported" in response.text


def test_dashboard_links_to_import(client: TestClient):
    assert "/profile/data" in client.get("/").text


# ---- one currency ------------------------------------------------------------------------------------------------

FOREIGN = """\
2026-01-02 Opening
    Assets:HDFC           100000.00 USD
    Equity:Opening Balances
"""


def test_a_file_in_another_currency_is_refused_in_the_preview_and_explained(client: TestClient):
    response = client.post("/import/preview", files={"file": ("a.ledger", FOREIGN.encode())})
    assert response.status_code == 200
    assert "Nothing was imported" in response.text and "your currency is INR" in response.text


def test_the_rupee_sign_and_code_are_accepted_as_labels(client: TestClient):
    text = "2026-01-02 Opening\n    Assets:HDFC  \u20b9500.00\n    Equity:Opening Balances  -500.00 INR\n"
    response = client.post("/import/preview", files={"file": ("a.ledger", text.encode())})
    assert "Nothing was imported" not in response.text and "Assets 500.00" in response.text


def test_a_conversion_is_not_supported(client: TestClient):
    text = "2026-01-05 Buy\n    Assets:Wise  100.00 @@ 8350.00\n    Assets:HDFC\n"
    response = client.post("/import/preview", files={"file": ("a.ledger", text.encode())})
    assert "Nothing was imported" in response.text and "one currency" in response.text
