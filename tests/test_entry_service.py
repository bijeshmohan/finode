"""Saving an entry from a form (services/entry.py): what the web form and /api/entries both record."""

from decimal import Decimal
from uuid import UUID

import pytest

from app.models.transaction import PostingSide
from app.schemas.entry import EntryForm, EntryRow

from .books import category, post_account
from .svc import entries, services


@pytest.fixture
def places(client, root_accounts):
    def account(name, root, **extra):
        made = post_account(client, {"name": name, "parent_id": root_accounts[root], **extra})
        assert made.status_code == 201, made.text
        return UUID(made.json()["id"])

    return {
        "bank": account("Bank", "Assets", balance="1000"),
        "loan": account("Home Loan", "Liabilities", on_budget=False),
        "food": UUID(category(client, "Food")["id"]),
        "emi": UUID(category(client, "EMI")["id"]),
        "salary": UUID(category(client, "Salary", "earning")["id"]),
        "ada": UUID(client.post("/api/contacts/", json={"name": "Ada"}).json()["id"]),
        "expenses": root_accounts["Expenses"],
    }


def rows(*lines) -> list[EntryRow]:
    return [
        EntryRow(choice=c, side=PostingSide(s), amount=Decimal(a), **extra)
        for c, s, a, *more in lines
        for extra in (more[0] if more else {},)
    ]


def form(kind="expense", lines=(), **extra) -> EntryForm:
    return EntryForm(kind=kind, rows=rows(*lines), **extra)


def balanced(session) -> bool:
    return services(session).reports.trial_balance().balanced


def test_an_expense_on_a_category(session, places):
    saved = entries(session).create(
        form(lines=((places["bank"], "credit", "30"), (places["food"], "debit", "30")), payee="Swiggy")
    )
    assert saved.recorded == "transaction"
    entry = services(session).transactions.read(saved.transaction_id)
    line = next(p for p in entry.postings if p.side == PostingSide.DEBIT)
    assert str(line.account_id) == str(places["expenses"]) and line.category_id == places["food"]
    assert balanced(session)


def test_a_payment_into_a_loan_keeps_its_category(session, places):
    saved = entries(session).create(
        form(
            "transfer",
            ((places["bank"], "credit", "500"), (places["loan"], "debit", "500", {"category_id": places["emi"]})),
        )
    )
    entry = services(session).transactions.read(saved.transaction_id)
    assert next(p for p in entry.postings if p.side == PostingSide.DEBIT).category_id == places["emi"]
    assert balanced(session)


def test_a_person_on_a_transfer_is_a_loan(client, session, places):
    saved = entries(session).create(
        form("transfer", ((places["bank"], "credit", "200"), (places["ada"], "debit", "200")))
    )
    assert saved.recorded == "transfer"
    assert client.get(f"/api/contacts/{places['ada']}").json()["receivable"] == "200.00"
    assert balanced(session)


def test_naming_a_person_after_at_is_a_gift(client, session, places):
    saved = entries(session).create(
        form(
            lines=((places["bank"], "credit", "50"), (places["food"], "debit", "50")),
            payee="Ada",
            payee_contact=places["ada"],
        )
    )
    activity = client.get(f"/api/contacts/{places['ada']}/activity").json()
    assert str(saved.transaction_id) in str(activity)
    assert client.get(f"/api/contacts/{places['ada']}").json()["receivable"] == "0.00", "a gift leaves nothing owed"


def test_editing_a_loan_into_an_ordinary_entry_releases_it(client, session, places):
    service = entries(session)
    saved = service.create(form("transfer", ((places["bank"], "credit", "200"), (places["ada"], "debit", "200"))))
    again = service.update(
        saved.transaction_id, form(lines=((places["bank"], "credit", "200"), (places["food"], "debit", "200")))
    )
    assert again.transaction_id == saved.transaction_id and again.recorded == "transaction"
    assert client.get(f"/api/contacts/{places['ada']}").json()["receivable"] == "0.00"
    assert services(session).transactions.read(saved.transaction_id) is not None
    assert balanced(session)


def test_a_failed_edit_leaves_the_loan_as_it_was(client, session, places):
    service = entries(session)
    saved = service.create(form("transfer", ((places["bank"], "credit", "200"), (places["ada"], "debit", "200"))))
    with pytest.raises(ValueError):
        service.update(
            saved.transaction_id, form(lines=((places["bank"], "credit", "200"), (places["food"], "debit", "150")))
        )
    assert client.get(f"/api/contacts/{places['ada']}").json()["receivable"] == "200.00"
    assert balanced(session)


def test_refusals_say_why(session, places):
    with pytest.raises(
        ValueError, match="a person goes on one side, one of your accounts on the other, for one amount!"
    ):
        entries(session).create(form("transfer", ((places["ada"], "credit", "10"), (places["ada"], "debit", "10"))))


def test_an_unknown_entry(session, places):
    with pytest.raises(LookupError):
        entries(session).update(
            UUID("00000000-0000-4000-8000-0000000000aa"),
            form(lines=((places["bank"], "credit", "1"), (places["food"], "debit", "1"))),
        )
