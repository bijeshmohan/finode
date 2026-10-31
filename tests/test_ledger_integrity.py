"""The books stay sound: trial balance, history, stable postings, balances by date, database checks."""

from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.transaction import Posting, PostingSide

from .books import into, leg
from .svc import plain


def post(client, source, target, amount, on=None, **extra):
    """Money moves from the source account to the target one."""
    debit, credit = target, source
    body = {
        "postings": [
            leg(debit, "debit", amount),
            leg(credit, "credit", amount),
        ],
        **extra,
    }
    if on:
        body["date"] = on
    response = client.post("/api/transactions/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def trial(client, **params):
    response = client.get("/api/reports/trial-balance", params=params)
    assert response.status_code == 200
    return response.json()


# ---- trial balance -------------------------------------------------------------------------------


def test_an_empty_ledger_is_balanced(client, root_accounts):
    result = trial(client)
    assert (
        result["balanced"]
        and result["problems"] == []
        and result["lines"] == []
        and result["debit"] == result["credit"] == "0.00"
    )


def test_the_books_balance_through_every_kind_of_change(
    client, root_accounts, account, other_account, expense_account, income_account
):
    client.patch(f"/api/accounts/{account['id']}", json={"balance": "500"})  # opening balance adjustment
    first = post(client, account, expense_account, "40")
    post(client, account, other_account, "100")
    post(client, income_account, account, "900")
    client.patch(
        f"/api/transactions/{first['id']}",
        json={
            "postings": [
                leg(other_account, "debit", "55"),
                leg(account, "credit", "55"),
            ]
        },
    )
    gone = post(client, account, expense_account, "7")
    client.delete(f"/api/transactions/{gone['id']}")

    result = trial(client)
    assert result["balanced"], result["problems"]
    assert result["currency"] == "INR" and result["debit"] == result["credit"] == "1555.00"
    by_account = {line["account"]: line for line in result["lines"]}
    assert by_account["Assets:checking"]["debit"] == "1400.00" and by_account["Assets:checking"]["credit"] == "155.00"
    assert by_account["Equity:Opening Balances"]["credit"] == "500.00"


def test_the_trial_balance_names_a_transaction_that_does_not_balance(client, session, account, expense_account):
    made = post(client, account, expense_account, "10")
    # Bypass the service, the way a bug or manual SQL could.
    posting = (
        session.query(Posting)
        .filter(Posting.transaction_id == UUID(made["id"]), Posting.side == PostingSide.DEBIT)
        .one()
    )
    posting.amount = 11
    session.add(posting)
    session.commit()
    result = trial(client)
    assert not result["balanced"]
    assert any("does not balance" in p and made["id"] in p for p in result["problems"])


def test_a_transaction_with_one_posting_is_reported(client, session, account, expense_account):
    made = post(client, account, expense_account, "10")
    session.delete(session.query(Posting).filter(Posting.transaction_id == UUID(made["id"])).first())
    session.commit()
    problems = trial(client)["problems"]
    assert any("at least two are needed" in p for p in problems)


def test_the_trial_balance_stops_at_the_day_asked(client, account, expense_account):
    post(client, account, expense_account, "10", on="2026-01-05")
    post(client, account, expense_account, "20", on="2026-03-05")
    assert trial(client, as_of="2026-02-01")["debit"] == "10.00"
    assert trial(client)["debit"] == "30.00"


# ---- balances by date ----------------------------------------------------------------------------


def test_entries_dated_in_the_future_do_not_count_yet(client, root_accounts, account, expense_account):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    post(client, account, expense_account, "10", on=date.today().isoformat())
    post(client, account, expense_account, "25", on=tomorrow)
    expenses = root_accounts["Expenses"]
    assert client.get(f"/api/accounts/{expenses}").json()["balance"] == "10.00"
    assert client.get(f"/api/accounts/{expenses}", params={"as_of": tomorrow}).json()["balance"] == "35.00"
    listed = {a["name"]: a for a in client.get("/api/accounts/", params={"as_of": tomorrow}).json()}
    assert listed["Expenses"]["balance"] == "35.00"
    assert {a["name"]: a for a in client.get("/api/accounts/").json()}["Expenses"]["balance"] == "10.00"


def test_a_balance_as_of_a_past_day(client, root_accounts, account, expense_account):
    post(client, account, expense_account, "10", on="2026-01-05")
    post(client, account, expense_account, "20", on="2026-03-05")
    expenses = root_accounts["Expenses"]
    assert client.get(f"/api/accounts/{expenses}", params={"as_of": "2026-02-01"}).json()["balance"] == "10.00"


# ---- stable postings -----------------------------------------------------------------------------


def ids(client, transaction_id):
    return {
        (p["account_id"], p["side"]): p["id"]
        for p in client.get(f"/api/transactions/{transaction_id}").json()["postings"]
    }


def test_correcting_an_amount_keeps_the_postings(client, account, expense_account):
    made = post(client, account, expense_account, "10")
    before = ids(client, made["id"])
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(expense_account, "debit", "12"),
                leg(account, "credit", "12"),
            ]
        },
    )
    after = ids(client, made["id"])
    assert after == before
    assert client.get(f"/api/transactions/{made['id']}").json()["postings"][0]["amount"] in ("12.00", "12")


def test_moving_a_side_to_another_account_replaces_only_that_posting(
    client, root_accounts, account, other_account, expense_account
):
    made = post(client, account, expense_account, "10")
    before = ids(client, made["id"])
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(expense_account, "debit", "10"),
                leg(other_account, "credit", "10"),
            ]
        },
    )
    after = ids(client, made["id"])
    expenses = root_accounts["Expenses"]
    assert after[(expenses, "debit")] == before[(expenses, "debit")]
    assert (account["id"], "credit") not in after and (other_account["id"], "credit") in after


def test_swapping_the_sides_keeps_the_accounts_postings(client, account, expense_account):
    made = post(client, account, expense_account, "10")
    before = ids(client, made["id"])
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(account, "debit", "10"),
                leg(expense_account, "credit", "10"),
            ]
        },
    )
    after = ids(client, made["id"])
    assert set(after.values()) == set(before.values())
    assert trial(client)["balanced"]


def test_splitting_adds_a_posting_and_merging_removes_one(client, account, expense_account, other_account):
    made = post(client, account, expense_account, "10")
    before = ids(client, made["id"])
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(expense_account, "debit", "6"),
                leg(other_account, "debit", "4"),
                leg(account, "credit", "10"),
            ]
        },
    )
    split = ids(client, made["id"])
    assert len(split) == 3 and set(before.values()) <= set(split.values())
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(expense_account, "debit", "10"),
                leg(account, "credit", "10"),
            ]
        },
    )
    assert ids(client, made["id"]) == before
    assert trial(client)["balanced"]


# ---- history -------------------------------------------------------------------------------------


def test_history_follows_a_transaction_from_creation_to_deletion(client, account, expense_account, svc):
    made = post(client, account, expense_account, "10", payee="Shop")
    client.patch(f"/api/transactions/{made['id']}", json={"payee": "Market"})
    client.patch(
        f"/api/transactions/{made['id']}",
        json={
            "postings": [
                leg(expense_account, "debit", "12"),
                leg(account, "credit", "12"),
            ]
        },
    )
    client.delete(f"/api/transactions/{made['id']}")

    assert client.get(f"/api/transactions/{made['id']}").status_code == 404
    history = plain(svc.transactions.history(UUID(made["id"])))
    assert [h["action"] for h in history] == ["created", "updated", "updated", "deleted"]
    assert [h["payee"] for h in history] == ["Shop", "Market", "Market", "Market"]
    assert [h["via"] for h in history] == ["api"] * 4
    assert history[0]["postings"][0]["account"] in ("Expenses:groceries", "Assets:checking")
    assert {p["amount"] for p in history[0]["postings"]} == {"10.00"}
    assert {p["amount"] for p in history[3]["postings"]} == {"12.00"}

    deleted = plain(svc.transactions.deleted())
    assert [d["transaction_id"] for d in deleted] == [made["id"]]


def test_saving_without_changes_adds_nothing(client, account, expense_account, svc):
    made = post(client, account, expense_account, "10", payee="Shop")
    client.patch(f"/api/transactions/{made['id']}", json={"payee": "Shop"})
    assert len(svc.transactions.history(UUID(made["id"]))) == 1


def test_an_unknown_transaction_has_no_history(svc):
    assert svc.transactions.history(UUID("00000000-0000-4000-8000-0000000000aa")) == []


def test_history_belongs_to_one_user(client, session, account, expense_account, svc):
    from app.models.transaction_history import TransactionHistory

    theirs = TransactionHistory(
        user_id=UUID(int=99),
        transaction_id=UUID(int=5),
        action="created",
        snapshot={"date": "2026-01-01", "postings": []},
    )
    session.add(theirs)
    session.commit()
    assert svc.transactions.history(UUID(int=5)) == []
    assert svc.transactions.deleted() == []


def test_balance_adjustments_are_in_the_history_too(client, session, account):
    client.patch(f"/api/accounts/{account['id']}", json={"balance": "50"})
    from app.models.transaction_history import TransactionHistory

    rows = session.query(TransactionHistory).all()
    assert [r.action for r in rows] == ["created"]


# ---- database checks -----------------------------------------------------------------------------


@pytest.mark.parametrize(("column", "value"), [("amount", 0), ("amount", -1)])
def test_the_database_refuses_a_posting_that_is_not_positive(client, session, account, expense_account, column, value):
    made = post(client, account, expense_account, "10")
    posting = session.query(Posting).filter(Posting.transaction_id == UUID(made["id"])).first()
    setattr(posting, column, value)
    session.add(posting)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---- every way of writing keeps the books balanced -----------------------------------------------


JOURNAL = """\
2026-01-01 Opening
    Assets:Bank:HDFC    1000
    Equity:Opening Balances

2026-01-05 Groceries
    Expenses:Food    40
    Assets:Bank:HDFC
"""


def test_an_import_balances(client, root_accounts):
    response = client.post("/api/import", files={"file": ("a.ledger", JOURNAL.encode())})
    assert response.status_code == 200, response.text
    result = trial(client)
    assert result["balanced"], result["problems"]
    assert result["debit"] == result["credit"] == "1040.00"


def test_recurring_occurrences_balance(client, root_accounts, account, expense_account):
    response = client.post(
        "/api/recurring/",
        json={
            "from_account_id": account["id"],
            **into(client, expense_account),
            "amount": "9",
            "frequency": "monthly",
            "start_date": (date.today() - timedelta(days=70)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    client.get("/api/recurring/")
    result = trial(client)
    assert result["balanced"] and result["debit"] != "0.00", result


def test_the_edit_page_shows_no_history(client, account, expense_account):
    made = post(client, account, expense_account, "10", payee="Shop")
    client.patch(f"/api/transactions/{made['id']}", json={"payee": "Market"})
    page = client.get(f"/transactions/{made['id']}/edit").text
    assert "History" not in page and "history" not in page
