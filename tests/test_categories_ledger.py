"""Budget categories on the ledger: every Income or Expenses account has a category of the same id, every line of an
entry can say what it was for, and the rules of accounts (closing, deleting, merging) carry over to categories."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from app.models.budget import BudgetAllocation
from app.models.category import BudgetCategory
from app.models.transaction import Posting
from app.models.transaction_history import TransactionHistory
from app.schemas.category import CategoryCreate, CategoryUpdate

from .conftest import TEST_USER_ID
from .svc import services
from .test_budget import account, assign


def entry(client, lines, **extra):
    body = {
        "postings": [{"account": a, "side": s, "amount": x, **({"category": c} if c else {})} for a, s, x, c in lines]
    }
    response = client.post("/api/transactions/", json={**body, **extra})
    return response


def categories(session):
    return {c.name: c for c in session.exec(select(BudgetCategory).where(BudgetCategory.user == TEST_USER_ID)).all()}


def lines(session, tid):
    return {
        (p.account, p.side.value): p.category_id
        for p in session.exec(select(Posting).where(Posting.transaction == UUID(tid))).all()
    }


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    emi = account(client, root_accounts, "EMI", "Expenses")
    salary = account(client, root_accounts, "Salary", "Income")
    return {"bank": bank, "loan": loan, "food": food, "groceries": groceries, "emi": emi, "salary": salary}


# ---- an account and its category ---------------------------------------------------------------


def test_an_income_or_expenses_account_has_a_category_of_the_same_id(client, session, books):
    got = categories(session)
    assert set(got) == {"Food", "Groceries", "EMI", "Salary"}, "assets and liabilities have none"
    assert got["Groceries"].bcid == UUID(books["groceries"]["aid"])
    assert got["Groceries"].parent_id == got["Food"].bcid and got["Food"].parent_id is None
    assert (got["Food"].kind, got["Salary"].kind) == ("spending", "earning")
    accounts = {a["name"]: a for a in client.get("/api/accounts/").json()}
    assert "Bank" in accounts


def test_renaming_moving_and_closing_the_account_follow_into_the_category(client, session, books):
    groceries = books["groceries"]["aid"]
    client.patch(f"/api/accounts/{groceries}", json={"name": "Supermarket", "details": "weekly"})
    client.patch(f"/api/accounts/{groceries}", json={"parent_id": books["emi"]["aid"]})
    got = categories(session)
    assert got["Supermarket"].details == "weekly" and got["Supermarket"].parent_id == got["EMI"].bcid
    client.post(f"/api/accounts/{groceries}/close")
    session.expire_all()
    assert categories(session)["Supermarket"].closed_on is not None
    client.post(f"/api/accounts/{groceries}/reopen")
    session.expire_all()
    assert categories(session)["Supermarket"].closed_on is None


def test_deleting_an_unused_account_removes_its_category_and_restoring_brings_it_back(client, session, books):
    made = account(client, books_roots(client), "Hobbies", "Expenses")
    assert "Hobbies" in categories(session)
    svc = services(session)
    svc.accounts.delete(UUID(made["aid"]))
    session.expire_all()
    assert "Hobbies" not in categories(session)
    deleted = svc.accounts.restorable()[0]
    svc.accounts.restore_deleted(deleted["did"])
    session.expire_all()
    assert categories(session)["Hobbies"].bcid == UUID(made["aid"])


def books_roots(client):
    return {a["name"]: a["aid"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}


# ---- the lines of an entry ---------------------------------------------------------------------


def test_a_line_to_an_expenses_or_income_account_carries_its_category(client, session, books):
    made = entry(
        client, [(books["groceries"]["aid"], "debit", "400", None), (books["bank"]["aid"], "credit", "400", None)]
    )
    assert made.status_code == 201, made.text
    got = lines(session, made.json()["tid"])
    assert got[(UUID(books["groceries"]["aid"]), "debit")] == UUID(books["groceries"]["aid"])
    assert got[(UUID(books["bank"]["aid"]), "credit")] is None
    assert [p["category"] for p in made.json()["postings"]] == [books["groceries"]["aid"], None]


def test_a_payment_into_a_loan_carries_its_payment_category_only_when_it_touches_the_budget(client, session, books):
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["emi"]["aid"]})
    paid = entry(
        client, [(books["loan"]["aid"], "debit", "1000", None), (books["bank"]["aid"], "credit", "1000", None)]
    )
    assert lines(session, paid.json()["tid"])[(UUID(books["loan"]["aid"]), "debit")] == UUID(books["emi"]["aid"])
    payout = entry(
        client, [(books["bank"]["aid"], "debit", "5000", None), (books["loan"]["aid"], "credit", "5000", None)]
    )
    assert lines(session, payout.json()["tid"])[(UUID(books["loan"]["aid"]), "credit")] is None


def test_a_line_can_name_its_category_and_a_split_can_use_several(client, session, books):
    split = entry(
        client,
        [
            (books["loan"]["aid"], "debit", "14120", books["emi"]["aid"]),
            (books["groceries"]["aid"], "debit", "5157", None),
            (books["bank"]["aid"], "credit", "19277", None),
        ],
    )
    assert split.status_code == 201, split.text
    got = lines(session, split.json()["tid"])
    assert got[(UUID(books["loan"]["aid"]), "debit")] == UUID(books["emi"]["aid"])
    assert got[(UUID(books["groceries"]["aid"]), "debit")] == UUID(books["groceries"]["aid"])


def test_the_same_account_twice_with_different_categories_is_a_split_of_that_account(client, session, books):
    split = entry(
        client,
        [
            (books["loan"]["aid"], "debit", "14120", books["emi"]["aid"]),
            (books["loan"]["aid"], "debit", "5157", books["food"]["aid"]),
            (books["bank"]["aid"], "credit", "19277", None),
        ],
    )
    assert split.status_code == 201, split.text
    categories_on_loan = sorted(
        str(p.category_id)
        for p in session.exec(select(Posting).where(Posting.account == UUID(books["loan"]["aid"]))).all()
    )
    assert categories_on_loan == sorted([books["emi"]["aid"], books["food"]["aid"]])


@pytest.mark.parametrize(
    ("which", "message"),
    [("unknown", "not found"), ("earning_on_loan", "earning category"), ("mismatch", "stands for")],
)
def test_a_category_that_does_not_fit_the_line_is_refused(client, books, which, message):
    bad = {
        "unknown": (books["loan"]["aid"], "00000000-0000-4000-8000-0000000000aa"),
        "earning_on_loan": (books["loan"]["aid"], books["salary"]["aid"]),
        "mismatch": (books["groceries"]["aid"], books["emi"]["aid"]),
    }[which]
    response = entry(client, [(bad[0], "debit", "10", bad[1]), (books["bank"]["aid"], "credit", "10", None)])
    assert response.status_code == 400 and message in response.text


def test_a_closed_category_cannot_be_used_but_an_entry_that_already_has_it_can_be_edited(client, books):
    made = entry(
        client,
        [(books["loan"]["aid"], "debit", "10", books["emi"]["aid"]), (books["bank"]["aid"], "credit", "10", None)],
    )
    tid = made.json()["tid"]
    client.post(f"/api/accounts/{books['emi']['aid']}/close")
    refused = entry(
        client,
        [(books["loan"]["aid"], "debit", "10", books["emi"]["aid"]), (books["bank"]["aid"], "credit", "10", None)],
    )
    assert refused.status_code == 400
    again = client.patch(
        f"/api/transactions/{tid}",
        json={
            "postings": [
                {"account": books["loan"]["aid"], "side": "debit", "amount": "12", "category": books["emi"]["aid"]},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "12"},
            ]
        },
    )
    assert again.status_code == 200, again.text


# ---- history and restoring ---------------------------------------------------------------------


def test_history_remembers_the_categories_and_an_unchanged_save_adds_nothing(client, session, books):
    made = entry(
        client, [(books["groceries"]["aid"], "debit", "400", None), (books["bank"]["aid"], "credit", "400", None)]
    )
    tid = made.json()["tid"]
    snapshot = (
        session.exec(select(TransactionHistory).where(TransactionHistory.transaction_id == UUID(tid))).one().snapshot
    )
    assert {p["category"] for p in snapshot["postings"]} == {books["groceries"]["aid"], None}
    resave = {"postings": [p | {"category": p.get("category")} for p in made.json()["postings"]]}
    resave = {
        "postings": [
            {"account": p["account"], "side": p["side"], "amount": p["amount"]} for p in made.json()["postings"]
        ]
    }
    client.patch(f"/api/transactions/{tid}", json=resave)
    rows = session.exec(select(TransactionHistory).where(TransactionHistory.transaction_id == UUID(tid))).all()
    assert len(rows) == 1


def test_an_old_snapshot_without_categories_does_not_make_a_resave_look_like_a_change(client, session, books):
    made = entry(
        client, [(books["groceries"]["aid"], "debit", "400", None), (books["bank"]["aid"], "credit", "400", None)]
    )
    tid = made.json()["tid"]
    row = session.exec(select(TransactionHistory).where(TransactionHistory.transaction_id == UUID(tid))).one()
    row.snapshot = {
        **row.snapshot,
        "postings": [{k: v for k, v in p.items() if k != "category"} for p in row.snapshot["postings"]],
    }
    session.add(row)
    session.commit()
    client.patch(
        f"/api/transactions/{tid}",
        json={
            "postings": [
                {"account": p["account"], "side": p["side"], "amount": p["amount"]} for p in made.json()["postings"]
            ]
        },
    )
    assert (
        len(session.exec(select(TransactionHistory).where(TransactionHistory.transaction_id == UUID(tid))).all()) == 1
    )


def test_a_changed_category_is_told_in_the_changes(client, books):
    made = entry(
        client,
        [(books["loan"]["aid"], "debit", "10", books["emi"]["aid"]), (books["bank"]["aid"], "credit", "10", None)],
    )
    tid = made.json()["tid"]
    client.patch(
        f"/api/transactions/{tid}",
        json={
            "postings": [
                {"account": books["loan"]["aid"], "side": "debit", "amount": "10", "category": books["food"]["aid"]},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "10"},
            ]
        },
    )
    steps = client.get(f"/api/transactions/{tid}/changes").json()
    relabelled = steps[-1]["changes"]["postings"]["relabelled"]
    assert relabelled[0]["category_from"] == [books["emi"]["aid"]] and relabelled[0]["category_to"] == [
        books["food"]["aid"]
    ]


def test_a_restored_entry_gets_its_categories_back(client, session, books):
    made = entry(
        client,
        [(books["loan"]["aid"], "debit", "10", books["emi"]["aid"]), (books["bank"]["aid"], "credit", "10", None)],
    )
    tid = made.json()["tid"]
    client.delete(f"/api/transactions/{tid}")
    hid = client.get("/api/transactions/deleted").json()[0]["hid"]
    restored = client.post(f"/api/transactions/deleted/{hid}/restore")
    assert restored.status_code in (200, 201), restored.text
    assert lines(session, tid)[(UUID(books["loan"]["aid"]), "debit")] == UUID(books["emi"]["aid"])


# ---- deleting, merging and the plan ------------------------------------------------------------


def test_a_category_that_labels_entries_cannot_be_deleted_only_closed(client, session, books):
    entry(
        client,
        [(books["loan"]["aid"], "debit", "10", books["emi"]["aid"]), (books["bank"]["aid"], "credit", "10", None)],
    )
    svc = services(session)
    result = svc.categories.delete(UUID(books["emi"]["aid"]))
    assert result.outcome == "closed" and result.category.closed_on is not None
    unused = svc.categories.create(CategoryCreate(name="Gifts", kind="spending"))
    assert svc.categories.delete(unused.bcid).outcome == "deleted"
    assert svc.categories.read(unused.bcid) is None


def test_merging_two_expense_categories_moves_lines_labels_and_plan(client, session, books):
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["emi"]["aid"]})
    entry(client, [(books["loan"]["aid"], "debit", "10", None), (books["bank"]["aid"], "credit", "10", None)])
    spent = entry(client, [(books["emi"]["aid"], "debit", "7", None), (books["bank"]["aid"], "credit", "7", None)])
    assign(client, books["emi"], "500")
    assign(client, books["food"], "300")
    result = services(session).categories.merge(UUID(books["emi"]["aid"]), UUID(books["food"]["aid"]))
    assert result.merged
    session.expire_all()
    assert "EMI" not in categories(session)
    food = UUID(books["food"]["aid"])
    assert {p.category_id for p in session.exec(select(Posting)).all()} <= {food, None}
    assert lines(session, spent.json()["tid"])[(food, "debit")] == food
    rows = session.exec(select(BudgetAllocation)).all()
    assert [(r.category_id, r.amount) for r in rows] == [(food, Decimal("800"))]


def test_the_plan_is_kept_against_the_category(client, session, books):
    assign(client, books["food"], "300")
    row = session.exec(select(BudgetAllocation)).one()
    assert row.category_id == UUID(books["food"]["aid"])


# ---- the category service ----------------------------------------------------------------------


def test_the_category_service_makes_changes_closes_and_removes_categories(session, root_accounts):
    svc = services(session)
    food = svc.categories.create(CategoryCreate(name="Food", kind="spending"))
    dining = svc.categories.create(CategoryCreate(name="Dining", kind="spending", parent_id=food.bcid))
    assert dining.path == "Food:Dining" and dining.parent_id == food.bcid
    with pytest.raises(ValueError, match="cannot hold"):
        svc.categories.create(CategoryCreate(name="Tips", kind="earning", parent_id=food.bcid))
    with pytest.raises(ValueError):
        svc.categories.create(
            CategoryCreate(name="dining", kind="spending", parent_id=food.bcid)
        )  # taken (capitals aside)
    with pytest.raises(ValueError):  # three levels is one too many
        svc.categories.create(CategoryCreate(name="Pizza", kind="spending", parent_id=dining.bcid))
    renamed = svc.categories.update(dining.bcid, CategoryUpdate(name="Eating out"))
    assert renamed.path == "Food:Eating out"
    moved = svc.categories.update(dining.bcid, CategoryUpdate(parent_id=None))
    assert moved.parent_id is None and moved.path == "Eating out"
    assert svc.categories.close(dining.bcid).closed_on is not None
    assert [c.name for c in svc.categories.list()] == ["Food"], "closed ones are left out"
    assert {c.name for c in svc.categories.list(include_closed=True)} == {"Food", "Eating out"}
    with pytest.raises(ValueError, match="closed"):
        svc.categories.books_account(dining.bcid)
    assert svc.categories.reopen(dining.bcid).closed_on is None
    assert svc.categories.books_account(dining.bcid) == dining.bcid


def test_uncategorised_is_made_once_per_kind_and_comes_back_if_closed(session, root_accounts):
    svc = services(session)
    spending = svc.categories.uncategorised("spending")
    assert spending.system_key == "uncategorised.spending" and spending.kind == "spending"
    assert svc.categories.uncategorised("spending").bcid == spending.bcid
    assert svc.categories.uncategorised("earning").kind == "earning"
    svc.categories.close(spending.bcid)
    assert svc.categories.uncategorised("spending").closed_on is None
    svc.categories.update(spending.bcid, CategoryUpdate(name="Misc"))
    assert svc.categories.uncategorised("spending").bcid == spending.bcid, "found by its key, not its name"


def test_a_categories_list_is_sorted_by_kind_and_name(session, root_accounts):
    svc = services(session)
    for name, kind in (("Salary", "earning"), ("Rent", "spending"), ("Food", "spending")):
        svc.categories.create(CategoryCreate(name=name, kind=kind))
    assert [(c.kind, c.name) for c in svc.categories.list()] == [
        ("earning", "Salary"),
        ("spending", "Food"),
        ("spending", "Rent"),
    ]
    assert svc.categories.list(kind="earning")[0].name == "Salary"
