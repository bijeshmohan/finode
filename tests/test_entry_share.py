"""A bill or an income shared with people, saved from a form (services/entry_share.py through services/entry.py): what
the web form's Split and /api/entries both record."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.models.transaction import PostingSide
from app.schemas.entry import EntryForm, EntryRow, ExpenseShare, IncomePart, IncomeShare, PersonShare
from app.services.entry_share import expense_start, income_start

from .books import category, post_account
from .svc import entries, services


@pytest.fixture
def places(client, root_accounts):
    def account(name, root, **extra):
        made = post_account(client, {"name": name, "parent_id": root_accounts[root], **extra})
        assert made.status_code == 201, made.text
        return UUID(made.json()["id"])

    return {
        "bank": account("Bank", "Assets", balance="5000"),
        "food": UUID(category(client, "Food")["id"]),
        "rent": UUID(category(client, "Rent", "earning")["id"]),
        "alice": UUID(client.post("/api/contacts/", json={"name": "Alice"}).json()["id"]),
    }


def owed(client, person) -> tuple[str, str]:
    got = client.get(f"/api/contacts/{person}").json()
    return got["receivable"], got["payable"]


def balanced(session) -> bool:
    return services(session).reports.trial_balance().balanced


def bill(places, total="900", **share) -> EntryForm:
    data = {"kind": "expense", "category_id": places["food"], "account_id": places["bank"], "people": []} | share
    return EntryForm(kind="expense", payee="Dinner", total=Decimal(total), share=ExpenseShare(**data))


def test_an_equal_split_owes_each_their_part(client, session, places):
    saved = entries(session).create(bill(places, people=[PersonShare(contact_id=places["alice"])]))
    assert saved.recorded == "expense-shared"
    assert owed(client, places["alice"]) == ("450.00", "0.00")
    assert services(session).transactions.read(saved.transaction_id) is not None
    assert balanced(session)


def test_a_blank_self_paid_is_what_the_others_did_not_pay(client, session, places):
    entries(session).create(
        bill(places, "1000", self_paid=Decimal(0), people=[PersonShare(contact_id=places["alice"], paid=Decimal(1000))])
    )
    assert owed(client, places["alice"]) == ("0.00", "500.00")
    assert balanced(session)


def test_choose_the_account_you_paid_from(session, places):
    with pytest.raises(ValueError, match="choose the account you paid from!"):
        entries(session).create(bill(places, account_id=None, people=[PersonShare(contact_id=places["alice"])]))


def test_income_part_theirs(client, session, places):
    saved = entries(session).create(
        EntryForm(
            kind="income",
            payee="Rent, Flat 4B",
            total=Decimal(10000),
            share=IncomeShare(
                kind="income",
                category_id=places["rent"],
                account_id=places["bank"],
                people=[IncomePart(contact_id=places["alice"], theirs=Decimal(4000))],
            ),
        )
    )
    assert saved.recorded == "income-shared"
    assert owed(client, places["alice"]) == ("0.00", "4000.00")
    assert entries(session).incomes.read(saved.transaction_id).total_amount == Decimal(10000)
    assert balanced(session)


def test_a_person_who_is_not_yours_is_refused(session, places):
    with pytest.raises(ValueError, match="person not found"):
        entries(session).create(bill(places, people=[PersonShare(contact_id=uuid4())]))


def ordinary(session, places, amount="3000"):
    return entries(session).create(
        EntryForm(
            kind="expense",
            payee="Restaurant",
            date="2026-10-09",
            rows=[
                EntryRow(choice=places["bank"], side=PostingSide.CREDIT, amount=Decimal(amount)),
                EntryRow(choice=places["food"], side=PostingSide.DEBIT, amount=Decimal(amount)),
            ],
        )
    )


def test_an_ordinary_expense_edited_into_a_shared_bill(client, session, places):
    entry = ordinary(session, places)
    saved = entries(session).update(
        entry.transaction_id, bill(places, "3000", people=[PersonShare(contact_id=places["alice"])])
    )
    assert saved.transaction_id == entry.transaction_id and saved.recorded == "expense-shared"
    assert owed(client, places["alice"]) == ("1500.00", "0.00")
    assert str(services(session).transactions.read(entry.transaction_id).date) == "2026-10-09"
    assert balanced(session)


def test_a_shared_bill_edited_back_into_simple_releases_it(client, session, places):
    shared = entries(session).create(bill(places, people=[PersonShare(contact_id=places["alice"])]))
    entries(session).update(
        shared.transaction_id,
        EntryForm(
            kind="expense",
            payee="Dinner",
            rows=[
                EntryRow(choice=places["bank"], side=PostingSide.CREDIT, amount=Decimal(900)),
                EntryRow(choice=places["food"], side=PostingSide.DEBIT, amount=Decimal(900)),
            ],
        ),
    )
    assert owed(client, places["alice"]) == ("0.00", "0.00")
    assert services(session).transactions.read(shared.transaction_id) is not None
    assert balanced(session)


def test_a_failed_share_edit_leaves_the_bill_as_it_was(client, session, places):
    shared = entries(session).create(bill(places, people=[PersonShare(contact_id=places["alice"])]))
    with pytest.raises(ValueError, match="choose the account you paid from!"):
        entries(session).update(
            shared.transaction_id, bill(places, "600", account_id=None, people=[PersonShare(contact_id=places["alice"])])
        )
    assert owed(client, places["alice"]) == ("450.00", "0.00")
    assert balanced(session)


def test_the_start_values_of_a_bill(session, places):
    shared = entries(session).create(
        bill(
            places,
            "1000",
            method="percentage",
            self_value=Decimal(60),
            self_paid=Decimal(400),
            people=[PersonShare(contact_id=places["alice"], value=Decimal(40), paid=Decimal(600))],
        )
    )
    start = expense_start(entries(session).expenses.of_entry(shared.transaction_id), None)
    assert start.method == "percentage" and start.self_value == Decimal(60) and start.self_paid == Decimal(400)
    assert start.category_id == places["food"] and start.account_id == places["bank"]
    assert [(p.contact_id, p.value, p.paid) for p in start.people] == [(places["alice"], Decimal(40), Decimal(600))]


def test_blank_start_values(places):
    assert expense_start(None, places["alice"]).people == [PersonShare(contact_id=places["alice"])]
    assert income_start(None).people == []
