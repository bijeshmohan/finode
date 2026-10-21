"""The built-in groups every new person starts with under Assets and Liabilities (Bank Accounts, Cash, Investments,
Credit Cards, Loans): they cannot be changed or removed, and what is made under them starts as the group says."""

import json

import pytest

from app.repositories import profile
from app.services import account as account_service

from .test_backup import OTHER, as_user, restore_as_other
from .conftest import TEST_USER_ID

NAMES = {
    "Assets": ["Bank Accounts", "Cash", "Investments"],
    "Liabilities": ["Credit Cards", "Loans"],
}


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    """A brand-new profile: the built-in groups exist, Advanced is off and the Plan starts with Spend only."""
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    monkeypatch.setattr(profile, "NEW_PROFILE_PLAN_BUILD", False)


def accounts(client):
    return client.get("/api/accounts/").json()


def group(client, name):
    return next(a for a in accounts(client) if a["name"] == name and a["system_key"])


def make(client, name, parent, **extra):
    response = client.post("/api/accounts/", json={"name": name, "parent_id": group(client, parent)["aid"], **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_person_starts_with_the_five_groups_in_order(client):
    found = {a["system_key"]: a for a in accounts(client) if a["system_key"]}
    assert set(found) == {"assets.bank", "assets.cash", "assets.investments", "liabilities.cards", "liabilities.loans"}
    roots = {a["aid"]: a["name"] for a in accounts(client) if a["parent_id"] is None}
    for root, names in NAMES.items():
        mine = sorted((a for a in found.values() if roots[a["parent_id"]] == root), key=lambda a: a["position"])
        assert [a["name"] for a in mine] == names


def test_the_groups_cannot_be_renamed_moved_closed_or_deleted(client, root_accounts):
    bank = group(client, "Bank Accounts")
    for change in ({"name": "Banks"}, {"parent_id": group(client, "Cash")["aid"]}, {"details": "x"}, {"on_budget": False}):
        refused = client.patch(f"/api/accounts/{bank['aid']}", json=change)
        assert refused.status_code == 400 and "built in" in refused.json()["detail"], change
    assert client.delete(f"/api/accounts/{bank['aid']}").status_code == 400
    assert "built in" in client.delete(f"/api/accounts/{bank['aid']}").json()["detail"]
    closed = client.post(f"/api/accounts/{bank['aid']}/close")
    assert closed.status_code == 400 and "built in" in closed.json()["detail"]
    assert group(client, "Bank Accounts")["name"] == "Bank Accounts"


def test_what_is_made_under_a_group_starts_as_the_group_says(client):
    expected = {
        ("HDFC", "Bank Accounts"): (True, False),
        ("Wallet", "Cash"): (True, False),
        ("Visa", "Credit Cards"): (True, False),
        ("Mutual Funds", "Investments"): (False, True),
        ("Home Loan", "Loans"): (False, True),
    }
    for (name, parent), (on_budget, saving) in expected.items():
        made = make(client, name, parent)
        assert (made["on_budget"], made["saving"]) == (on_budget, saving), name


def test_the_person_can_still_choose_otherwise(client):
    assert make(client, "Old savings", "Bank Accounts", on_budget=False)["on_budget"] is False
    loan = make(client, "Informal loan", "Loans", on_budget=False, saving=False)
    assert loan["saving"] is False and loan["on_budget"] is False


def test_the_first_account_under_build_switches_the_build_chip_on(client):
    assert ">Build<" not in client.get("/plan").text
    make(client, "HDFC", "Bank Accounts")
    assert ">Build<" not in client.get("/plan").text, "a bank is Spend"
    make(client, "Mutual Funds", "Investments")
    assert ">Build<" in client.get("/plan").text


def test_investments_show_in_build_as_a_group(client):
    make(client, "Mutual Funds", "Investments")
    make(client, "PPF", "Investments")
    text = client.get("/plan?tab=build").text
    assert "Investments" in text and "Mutual Funds" in text


def test_people_with_a_ledger_of_their_own_get_none(client, monkeypatch):
    """Provisioning happens only when the roots are first made, so nobody who already has accounts is touched."""
    assert any(a["system_key"] for a in accounts(client))
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", False)
    try:
        as_user(OTHER)
        assert not any(a["system_key"] for a in accounts(client))
    finally:
        as_user(TEST_USER_ID)


def test_an_account_can_be_moved_into_a_group_but_not_the_group_ordered(client):
    other = client.post("/api/accounts/", json={"name": "Piggy", "parent_id": next(a["aid"] for a in accounts(client) if a["name"] == "Assets" and a["parent_id"] is None)}).json()
    moved = client.patch(f"/api/accounts/{other['aid']}", json={"parent_id": group(client, "Cash")["aid"]})
    assert moved.status_code == 200, moved.text
    page = client.post(f"/accounts/{group(client, 'Cash')['aid']}/move", data={"direction": "up"})
    assert page.status_code in (400, 404, 422) or "built in" in page.text


def test_a_backup_round_trips_the_groups_by_key(client):
    make(client, "HDFC", "Bank Accounts", balance="500")
    doc = client.get("/api/backup").json()
    assert {a["system_key"] for a in doc["accounts"] if a["system_key"]} == {
        "assets.bank", "assets.cash", "assets.investments", "liabilities.cards", "liabilities.loans"}
    try:
        as_user(OTHER)
        done = restore_as_other(client, doc)
        assert done.status_code == 200, done.text
        again = client.get("/api/accounts/").json()
        keys = [a["system_key"] for a in again if a["system_key"]]
        assert sorted(keys) == sorted(set(keys)) and len(keys) == 5, "mapped onto the person's own, none twice"
        hdfc = next(a for a in again if a["name"] == "HDFC")
        bank = next(a for a in again if a["system_key"] == "assets.bank")
        assert hdfc["parent_id"] == bank["aid"] and hdfc["balance"] == "500.00"
    finally:
        as_user(TEST_USER_ID)


def test_a_backup_without_groups_brings_its_own_structure(client, monkeypatch):
    """An older file (or the ledger of somebody who had no built-in groups) restores exactly as it was."""
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", False)
    try:
        as_user(OTHER)
        roots = {a["name"]: a["aid"] for a in accounts(client) if a["parent_id"] is None}
        cash = client.post("/api/accounts/", json={"name": "Cash", "parent_id": roots["Assets"], "balance": "300"}).json()
        doc = client.get("/api/backup").json()
    finally:
        as_user(TEST_USER_ID)
    assert not any(a["system_key"] for a in doc["accounts"])
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    assert restore_as_other_from_new(client, doc).status_code == 200


def restore_as_other_from_new(client, doc):
    """Restore into a different brand-new person (who has the built-in groups, empty)."""
    from uuid import UUID

    third = UUID("00000000-0000-4000-8000-0000000000cc")
    try:
        as_user(third)
        monkeypatched = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert monkeypatched.status_code == 200, monkeypatched.text
        again = client.get("/api/accounts/").json()
        assert {a["system_key"] for a in again if a["system_key"]} == {
            "assets.bank", "assets.investments", "liabilities.cards", "liabilities.loans"}, "only the colliding Cash stepped aside"
        cash = next(a for a in again if a["name"] == "Cash")
        assert cash["balance"] == "300.00" and cash["parent_id"] == next(a["aid"] for a in again if a["name"] == "Assets" and a["parent_id"] is None)
        return monkeypatched
    finally:
        as_user(TEST_USER_ID)


def test_an_import_uses_the_groups_it_builds_on_and_sets_aside_the_rest(client):
    journal = """\
2026-09-01 Opening
    Assets:Bank Accounts:HDFC   1000.00
    Assets:Cash                  200.00
    Equity:Opening Balances
"""
    done = client.post("/api/import", files={"file": ("a.ledger", journal.encode())})
    assert done.status_code == 200, done.text
    found = accounts(client)
    bank = next(a for a in found if a["system_key"] == "assets.bank")
    assert next(a for a in found if a["name"] == "HDFC")["parent_id"] == bank["aid"]
    cash = next(a for a in found if a["name"] == "Cash")
    assert cash["system_key"] is None and cash["balance"] == "200.00", "a plain Assets:Cash replaced the empty group"
    assert {a["system_key"] for a in found if a["system_key"]} == {
        "assets.bank", "assets.investments", "liabilities.cards", "liabilities.loans"}, "only the colliding group stepped aside"


def test_erasing_the_books_gives_the_groups_back(client):
    make(client, "HDFC", "Bank Accounts", balance="500")
    done = client.post("/profile/data/erase", data={"confirm": " Test@Example.com "})
    assert done.status_code == 200, done.text
    found = accounts(client)
    assert {a["system_key"] for a in found if a["system_key"]} == {
        "assets.bank", "assets.cash", "assets.investments", "liabilities.cards", "liabilities.loans"}
    assert not any(a["name"] == "HDFC" for a in found)
