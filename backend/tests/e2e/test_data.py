"""The React app's Your data page in a browser (ports of test_erase.py, with import, backup and restore): erasing the
books, deleting the account, importing a ledger file and restoring a backup, each previewed or confirmed first."""

import re
from pathlib import Path

from playwright.sync_api import Page, expect

from finode.routers import data as data_router

from ..books import leg
from .conftest import Api

JOURNAL = """\
2026-09-01 Opening
    Assets:HDFC        10000.00
    Equity:Opening Balances
2026-09-03 DMart
    Expenses:Food           1250.50
    Assets:HDFC
"""


def open_row(page: Page, title: str):
    page.locator("main").get_by_role("button", name=re.compile(f"^{title}")).click()


def last_button(page: Page, name: str):
    return page.locator("main").get_by_role("button", name=name, exact=True).last


def test_erasing_the_books(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    assert [a for a in api.get("/accounts/") if a["parent_id"]], "there are accounts to erase"
    page.goto("/profile/data")
    open_row(page, "Erase my books")
    field = page.get_by_label(re.compile("to confirm"))
    page.once("dialog", lambda dialog: dialog.accept())
    field.fill("nobody@example.com")
    last_button(page, "Erase my books").click()
    expect(page.get_by_role("alert")).to_have_text("Type test@example.com to confirm.")
    assert [a for a in api.get("/accounts/") if a["parent_id"]], "a wrong confirmation erases nothing"
    page.once("dialog", lambda dialog: dialog.accept())
    field.fill("test@example.com")
    last_button(page, "Erase my books").click()
    page.wait_for_url(re.compile(r"/$"))
    expect(page.get_by_text("Your books were erased")).to_be_visible()
    assert [a["name"] for a in api.get("/accounts/") if a["parent_id"] and not a["system_key"]] == [], (
        "only the four types are left"
    )


def test_deleting_the_account(signed_in_page: Page, books, monkeypatch):
    from finode.config import settings

    removed = []
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(data_router, "delete_user", lambda user_id: removed.append(user_id))
    page = signed_in_page
    page.goto("/profile/data")
    open_row(page, "Delete my account")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label(re.compile("to confirm")).fill("test@example.com")
    last_button(page, "Delete my account").click()
    page.wait_for_url(re.compile(r"/sign-in"))
    expect(page.get_by_text("Your account was deleted. Goodbye!")).to_be_visible()
    assert len(removed) == 1
    assert "sb_secret_x" not in page.content(), "the service key never reaches the browser"


def test_importing_a_ledger_file(signed_in_page: Page, api: Api, tmp_path: Path):
    page = signed_in_page
    journal = tmp_path / "books.ledger"
    journal.write_text(JOURNAL)
    page.goto("/profile/data")
    open_row(page, "Import")
    page.get_by_label("Ledger file").set_input_files(journal)
    page.get_by_role("button", name="Preview import").click()
    expect(page.get_by_text("Ready to import")).to_be_visible()
    expect(page.locator("main")).to_contain_text("2 transactions, 1 Sep 2026 to 3 Sep 2026")
    page.get_by_role("button", name="Import 2 transactions").click()
    page.wait_for_url(re.compile(r"/$"))
    expect(page.get_by_text("Import complete")).to_be_visible()
    hdfc = next(a for a in api.get("/accounts/") if a["name"] == "HDFC")
    assert hdfc["balance"] == "8749.50"


def test_a_backup_downloads_and_restores_into_empty_books(
    signed_in_page: Page, api: Api, books, server: str, tmp_path: Path
):
    page = signed_in_page
    api.post(
        "/transactions/",
        payee="Kept",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    page.goto("/profile/data")
    open_row(page, "Backup")
    with page.expect_download() as got:
        page.get_by_role("link", name="Download backup").click()
    backup = tmp_path / "backup.json"
    got.value.save_as(backup)
    assert got.value.suggested_filename.startswith("finode-backup-")
    erased = page.request.post(
        "/api/erase",
        data={"confirm": "test@example.com"},
        headers={"X-Finode": "1", "Origin": server},
    )
    assert erased.status == 204, erased.text()
    page.reload()
    open_row(page, "Backup")
    page.get_by_label("Backup file").set_input_files(backup)
    page.get_by_role("button", name="Preview restore").click()
    expect(page.get_by_text("Ready to restore")).to_be_visible()
    page.get_by_role("button", name="Restore everything").click()
    page.wait_for_url(re.compile(r"/$"))
    expect(page.get_by_text("Backup restored")).to_be_visible()
    assert any(t["payee"] == "Kept" for t in api.get("/transactions/"))


def test_the_exports_download_files(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/profile/data")
    open_row(page, "Export")
    for name, ending in (("Export ledger file", ".ledger"), ("Export CSV", ".csv")):
        with page.expect_download() as got:
            page.get_by_role("link", name=name).click()
        assert got.value.suggested_filename.endswith(ending), got.value.suggested_filename
