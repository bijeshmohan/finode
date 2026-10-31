"""Categories in recurring rules, backups, the ledger file and the CSV."""

import json
from uuid import UUID

import pytest

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

from .conftest import TEST_USER_ID
from .test_budget import account, budget, line
from .test_budget_categories import paid

OTHER = UUID("00000000-0000-4000-8000-0000000000cc")


def as_user(user_id):
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=user_id, email="x@example.com", claims={}
    )


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    sip = account(client, root_accounts, "SIP", "Expenses")
    food = account(client, root_accounts, "Food", "Expenses")
    return {"bank": bank, "loan": loan, "emi": emi, "sip": sip, "food": food}


def restore(client, doc):
    return client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})


# ---- recurring rules ---------------------------------------------------------------------------


def make_rule(client, books, **extra):
    body = {
        "from_account": books["bank"]["aid"],
        "to_account": books["loan"]["aid"],
        "amount": "15000",
        "frequency": "monthly",
        "start_date": "2026-10-01",
        **extra,
    }
    response = client.post("/api/recurring/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_rule_can_name_the_category_of_what_it_pays(client, books):
    rule = make_rule(client, books, category=books["emi"]["aid"])
    assert rule["category"] == books["emi"]["aid"]
    client.get("/api/recurring/")  # lists (and records what is due)
    entry = next(
        t
        for t in client.get("/api/transactions/").json()
        if any(p["account"] == books["loan"]["aid"] for p in t["postings"])
    )
    labels = {p["account"]: p["category"] for p in entry["postings"]}
    assert labels[books["loan"]["aid"]] == books["emi"]["aid"]
    assert labels[books["bank"]["aid"]] is None
    assert line(budget(client), "EMI")["activity"] == "15000.00"


def test_a_rule_with_a_category_that_does_not_fit_is_refused(client, books):
    salary = client.post("/api/categories/", json={"name": "Salary", "kind": "earning"}).json()
    response = client.post(
        "/api/recurring/",
        json={
            "from_account": books["bank"]["aid"],
            "to_account": books["loan"]["aid"],
            "amount": "10",
            "category": salary["bcid"],
        },
    )
    assert response.status_code == 400


def test_a_change_that_does_not_mention_categories_keeps_the_rules(client, books):
    rule = make_rule(client, books, category=books["emi"]["aid"])
    body = {
        "from_account": books["bank"]["aid"],
        "to_account": books["loan"]["aid"],
        "amount": "16000",
        "frequency": "monthly",
        "start_date": "2026-10-01",
    }
    changed = client.put(f"/api/recurring/{rule['rid']}", json=body).json()
    assert changed["category"] == books["emi"]["aid"]
    taken_off = client.put(f"/api/recurring/{rule['rid']}", json={**body, "category": None}).json()
    assert taken_off["category"] is None


def test_split_rows_of_a_rule_carry_their_categories(client, books):
    rule = client.post(
        "/api/recurring/",
        json={
            "postings": [
                {"account": books["loan"]["aid"], "side": "debit", "amount": "14120", "category": books["emi"]["aid"]},
                {"account": books["loan"]["aid"], "side": "debit", "amount": "5157", "category": books["sip"]["aid"]},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "19277"},
            ],
            "start_date": "2026-10-01",
        },
    )
    assert rule.status_code == 201, rule.text
    assert sorted(p["category"] or "" for p in rule.json()["postings"]) == sorted(
        ["", books["emi"]["aid"], books["sip"]["aid"]]
    )


# ---- backup ------------------------------------------------------------------------------------


def test_a_backup_carries_the_category_of_each_line_and_rule_and_restoring_gives_them_back(client, books):
    paid(client, books["bank"], books["loan"], "300", books["sip"])  # said SIP on purpose
    paid(client, books["bank"], books["food"], "40")
    make_rule(client, books, category=books["emi"]["aid"])
    doc = client.get("/api/backup").json()
    assert doc["version"] == 5 and {c["name"] for c in doc["categories"]} >= {"SIP", "Food", "EMI"}
    labelled = [p for t in doc["transactions"] for p in t["postings"] if p["category"]]
    assert {p["category"] for p in labelled} == {books["sip"]["aid"], books["food"]["aid"], books["emi"]["aid"]}
    assert doc["recurring"][0]["category"] == books["emi"]["aid"]
    try:
        as_user(OTHER)
        assert restore(client, doc).status_code == 200
        again = client.get("/api/backup").json()
        names = {c["id"]: c["name"] for c in again["categories"]}
        got = {names[p["category"]] for t in again["transactions"] for p in t["postings"] if p["category"]}
        assert got == {"SIP", "Food", "EMI"}
        assert names[again["recurring"][0]["category"]] == "EMI"
        sip_activity = line(client.get("/api/budget/").json(), "SIP")["activity"]
        assert sip_activity == "300.00", "the budget counts the restored label"
    finally:
        as_user(TEST_USER_ID)


def as_old_file(doc, version=3):
    """A backup as finode wrote it before categories stood alone: every category an Expenses or Income account, a line to
    one posting to it, and no list of categories."""
    roots = {a["name"]: a["id"] for a in doc["accounts"] if a["parent_id"] is None}
    root_of = {"spending": roots["Expenses"], "earning": roots["Income"]}
    expenses = {v: k for k, v in root_of.items()}
    for c in doc.pop("categories"):
        doc["accounts"].append(
            {
                "id": c["id"],
                "parent_id": c["parent_id"] or root_of[c["kind"]],
                "name": c["name"],
                "details": c["details"],
                "closed_on": c["closed_on"],
            }
        )
    for t in doc["transactions"]:
        for p in t["postings"]:
            if p["account"] in expenses:
                p["account"], p["category"] = p["category"], None
    doc["version"] = version
    return doc


def test_an_older_backup_with_categories_as_accounts_still_restores(client, books):
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["emi"]["aid"]})
    paid(client, books["bank"], books["loan"], "700")
    paid(client, books["bank"], books["food"], "40")
    doc = as_old_file(client.get("/api/backup").json())
    try:
        as_user(OTHER)
        assert restore(client, doc).status_code == 200
        assert line(client.get("/api/budget/").json(), "EMI")["activity"] == "700.00"
        assert line(client.get("/api/budget/").json(), "Food")["activity"] == "40.00"
    finally:
        as_user(TEST_USER_ID)


def test_a_closed_category_is_still_closed_after_a_restore(client, books, session):
    from sqlmodel import select

    from app.models.category import BudgetCategory

    client.post(f"/api/categories/{books['sip']['aid']}/close")
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)
        assert restore(client, doc).status_code == 200
        mine = session.exec(select(BudgetCategory).where(BudgetCategory.user == OTHER)).all()
        assert {c.name: c.closed_on is not None for c in mine}["SIP"] is True
    finally:
        as_user(TEST_USER_ID)


def test_a_backup_with_a_category_that_does_not_fit_is_refused(client, books):
    paid(client, books["bank"], books["food"], "40")
    doc = client.get("/api/backup").json()
    salary = {"id": "00000000-0000-4000-8000-0000000000e1", "name": "Salary", "kind": "earning"}
    doc["categories"].append(salary)
    to_food = next(p for t in doc["transactions"] for p in t["postings"] if p["category"] == books["food"]["aid"])
    to_food["category"] = salary["id"]  # an earning category on a line to Expenses
    try:
        as_user(OTHER)
        refused = restore(client, doc)
        assert refused.status_code == 400 and "earning category on a line to Expenses" in refused.text
    finally:
        as_user(TEST_USER_ID)


# ---- the ledger file and the CSV ---------------------------------------------------------------


def test_a_payment_into_a_loan_is_exported_with_its_category_and_imported_back(client, books):
    paid(client, books["bank"], books["loan"], "300", books["sip"])
    paid(client, books["bank"], books["food"], "40")
    text = client.get("/api/export").text
    assert "; category: SIP" in text
    assert text.count("; category:") == 1, "only a label the account does not say itself is written"
    csv_lines = client.get("/api/export", params={"format": "csv"}).text.splitlines()
    assert any(row.endswith(",Expenses:Food,Food,40.00,") for row in csv_lines)
    assert any(",Liabilities:Home Loan,SIP,300.00," in row for row in csv_lines)
    try:
        as_user(OTHER)
        done = client.post("/api/import", files={"file": ("a.ledger", text.encode())})
        assert done.status_code == 200, done.text
        names = {a["aid"]: a["name"] for a in client.get("/api/accounts/").json()}
        category_names = {c["bcid"]: c["name"] for c in client.get("/api/categories/").json()}
        labelled = {
            category_names[p["category"]]
            for t in client.get("/api/transactions/").json()
            for p in t["postings"]
            if p["category"] and names[p["account"]] == "Home Loan"
        }
        assert labelled == {"SIP"}
    finally:
        as_user(TEST_USER_ID)


def test_an_import_names_a_category_that_is_not_there(client, root_accounts):
    text = "2026-10-01 Test\n    Liabilities:Loan  100.00  ; category: Nowhere\n    Assets:Bank  -100.00\n"
    refused = client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params={"dry_run": True})
    assert "Nowhere" in " ".join(refused.json()["errors"])
